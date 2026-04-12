import requests
import psycopg2
import time
import random
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield

app = FastAPI(lifespan=lifespan)

# Added CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# DATABASE CONNECTION
# ==============================
def get_connection():
    return psycopg2.connect(
        host="aws-1-ap-south-1.pooler.supabase.com",
        port="6543",
        database="postgres",
        user="postgres.cguaghcgesxgmrghaghg",
        password="SamiRaj@2416",
        sslmode="require"
    )

# ==============================
# CREATE TABLES
# ==============================
def create_tables():
    conn = get_connection()
    cur = conn.cursor()

    # Sensor data table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sensor_data (
        id SERIAL PRIMARY KEY,
        node_id VARCHAR(50),
        field1 FLOAT,
        field2 FLOAT,
        created_at TIMESTAMP
    )
    """)

    # Tank parameters table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tank_sensorparameters (
        id SERIAL PRIMARY KEY,
        node_id VARCHAR(50),
        tank_height_cm FLOAT,
        tank_length_cm FLOAT,
        tank_width_cm FLOAT,
        lat FLOAT,
        long FLOAT
    )
    """)

    conn.commit()
    cur.close()
    conn.close()


# ==============================
# THINGSPEAK CONFIG
# ==============================
TEST_MODE = False

# Node id of sensor
NODE_ID = "NODE_001"

# ThingSpeak API
# field1 = temperature, field2 = water level (ESP32 sends tankHeight − distance)
url = "https://api.thingspeak.com/channels/3284542/feeds.json?api_key=W7VTUWICXQ4NDTTQ&results=1"

last_created_at = None


# ==============================
# GENERATE TEST DATA
# ==============================
def generate_test_data():
    base_values = {
        "water_level": 94.0,
        "temperature": 20.8
    }
    return {
        "water_level": round(base_values["water_level"] + random.uniform(-10, 10), 1),
        "temperature": round(base_values["temperature"] + random.uniform(-2, 2), 1),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ==============================
# ON-DEMAND REFRESH ENDPOINT
# field1 = temperature, field2 = water level (cm)
# ==============================
@app.get("/refresh")
def refresh_sensor_data(node_id: str = NODE_ID):
    try:
        if TEST_MODE:
            data = generate_test_data()
            temperature = data["temperature"]
            water_level = data["water_level"]
            created_at = data["created_at"]
        else:
            response = requests.get(url)
            feed = response.json()["feeds"][0]
            temperature = float(feed["field1"])
            water_level = float(feed["field2"])
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sensor_data (node_id, field1, field2, created_at)
            VALUES (%s, %s, %s, %s)
        """, (node_id, temperature, water_level, created_at))
        conn.commit()
        cur.close()
        conn.close()

        print(f"[refresh] node={node_id} temp={temperature} level={water_level} at={created_at}")
        return {"status": "ok", "temperature": temperature, "water_level": water_level, "created_at": created_at}

    except Exception as e:
        print("Refresh error:", e)
        return {"status": "error", "detail": str(e)}


# ==============================
# REQUEST MODELS
# ==============================
class TankParameters(BaseModel):
    node_id: str
    tank_height_cm: float
    tank_diameter_cm: float   # cylindrical tank — stored as tank_length_cm
    lat: float
    long: float

class SensorData(BaseModel):
    node_id: str
    temperature: float    # field1
    water_level: float    # field2 (cm)


# ==============================
# POST API — Direct hardware ingest (ESP32 → Backend → Supabase)
# ==============================
@app.post("/ingest")
def ingest_sensor_data(data: SensorData):
    try:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sensor_data (node_id, field1, field2, created_at)
            VALUES (%s, %s, %s, %s)
        """, (data.node_id, data.temperature, data.water_level, created_at))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[ingest] node={data.node_id} temp={data.temperature} level={data.water_level} at={created_at}")
        return {"status": "ok", "node_id": data.node_id, "created_at": created_at}
    except Exception as e:
        print("Ingest error:", e)
        return {"status": "error", "detail": str(e)}


# ==============================
# POST API — Create tank node
# ==============================
@app.post("/tank-parameters")
def create_tank_parameters(data: TankParameters):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO tank_sensorparameters
    (node_id, tank_height_cm, tank_length_cm, tank_width_cm, lat, long)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
    """, (
        data.node_id,
        data.tank_height_cm,
        data.tank_diameter_cm,  # store diameter in tank_length_cm
        0,                       # 0 flags this as a cylindrical tank
        data.lat,
        data.long
    ))

    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    return {
        "message": "Tank parameters inserted successfully",
        "id": new_id
    }


# ==============================
# GET API — Get tank nodes
# ==============================
@app.get("/tank-parameters")
def get_tank_parameters():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM tank_sensorparameters")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "node_id": row[1],
            "tank_height_cm": row[2],
            "tank_length_cm": row[3],
            "tank_width_cm": row[4],
            "lat": row[5],
            "long": row[6]
        })

    return result

# ==============================
# DELETE API — Remove a tank node + its sensor data
# ==============================
@app.delete("/tank-parameters/{node_id}")
def delete_tank_node(node_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM sensor_data WHERE node_id = %s", (node_id,))
    cur.execute("DELETE FROM tank_sensorparameters WHERE node_id = %s", (node_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": f"Node '{node_id}' and all its sensor data deleted."}


# ==============================
# GET API — Get sensor data
# field1 = temperature, field2 = water level (cm)
# ==============================
@app.get("/sensor-data")
def get_sensor_data(node_id: str = None):
    conn = get_connection()
    cur = conn.cursor()

    if node_id:
        cur.execute("""
        SELECT id, node_id, field1, field2, created_at
        FROM sensor_data
        WHERE node_id = %s
        ORDER BY created_at DESC
        LIMIT 100
        """, (node_id,))
    else:
        cur.execute("""
        SELECT id, node_id, field1, field2, created_at
        FROM sensor_data
        ORDER BY created_at DESC
        LIMIT 100
        """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "node_id": row[1],
            "temperature": row[2],   # field1 = temperature
            "water_level": row[3],   # field2 = water level (cm)
            "created_at": row[4]
        })

    return result


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)