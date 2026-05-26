import psycopg2
import os
import time
import json
import ssl
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import paho.mqtt.client as mqtt_lib

# ==============================
# MQTT CONFIG — HiveMQ Public Broker (Plain TCP)
# ==============================
MQTT_BROKER   = "broker.hivemq.com"
MQTT_PORT     = 1883          # Plain TCP (no TLS)
MQTT_TOPIC    = "aquasense/#"  # listens to all nodes


# ==============================
# DATABASE CONNECTION
# ==============================
def get_connection():
    return psycopg2.connect(
        host="aws-1-ap-south-1.pooler.supabase.com",
        port="5432",
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sensor_data (
        id SERIAL PRIMARY KEY,
        node_id VARCHAR(50),
        field1 FLOAT,
        field2 FLOAT,
        created_at TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tank_sensorparameters (
        id SERIAL PRIMARY KEY,
        node_id VARCHAR(50),
        tank_height_cm FLOAT,
        tank_length_cm FLOAT,
        tank_width_cm  FLOAT,
        lat FLOAT,
        long FLOAT
    )
    """)
    conn.commit()
    cur.close()
    conn.close()


# ==============================
# MQTT CALLBACKS
# ==============================
def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print(f"[MQTT] Connected to {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        print(f"[MQTT] Subscribed to {MQTT_TOPIC}")
    else:
        print(f"[MQTT] Connection failed, rc={rc}")


def on_message(client, userdata, msg):
    """Receives MQTT message from hardware → inserts into Supabase."""
    try:
        raw = msg.payload.decode('utf-8', errors='ignore')
        print(f"[MQTT] Received on {msg.topic}: {raw}")
        payload     = json.loads(raw)
        node_id     = payload.get("node_id", "UNKNOWN")
        temperature = float(payload.get("temperature", 0))
        water_level = float(payload.get("water_level", 0))
        created_at  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO sensor_data (node_id, field1, field2, created_at)
            VALUES (%s, %s, %s, %s)
        """, (node_id, temperature, water_level, created_at))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[MQTT] Saved -> node={node_id}  temp={temperature}C  level={water_level}cm")
    except json.JSONDecodeError:
        print(f"[MQTT] Ignoring non-JSON message on {msg.topic}")
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")


def on_disconnect(client, userdata, flags, rc, properties):
    print(f"[MQTT] Disconnected (rc={rc})")


# ==============================
# MQTT SUBSCRIBER THREAD
# ==============================
def start_mqtt_subscriber():
    """Runs forever in background, reconnects automatically on failure."""
    client_id = f"AquaSense_Backend_{int(time.time())}"
    client = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2, client_id=client_id)

    # Public broker — no credentials or TLS needed

    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    while True:
        try:
            print(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT} (TCP)...")
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            print(f"[MQTT] Broker error: {e}. Retrying in 10s...")
            time.sleep(10)


# ==============================
# FASTAPI APP + LIFESPAN
# ==============================
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    t = threading.Thread(target=start_mqtt_subscriber, daemon=True)
    t.start()
    print("[MQTT] Subscriber thread started")
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
# GET /refresh — latest reading for a node (used by frontend)
# ==============================
@app.get("/refresh")
def refresh_sensor_data(node_id: str = "NODE_001"):
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT field1, field2, created_at
            FROM sensor_data
            WHERE node_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (node_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row is None:
            return {"status": "no_data", "detail": f"No data yet for {node_id}"}

        temperature, water_level, created_at = row
        return {
            "status": "ok",
            "node_id": node_id,
            "temperature": temperature,
            "water_level": water_level,
            "created_at": str(created_at)
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ==============================
# POST /ingest — fallback HTTP ingest (if MQTT fails)
# ==============================
@app.post("/ingest")
def ingest_sensor_data(data: SensorData):
    try:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO sensor_data (node_id, field1, field2, created_at)
            VALUES (%s, %s, %s, %s)
        """, (data.node_id, data.temperature, data.water_level, created_at))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[ingest] node={data.node_id} temp={data.temperature} level={data.water_level}")
        return {"status": "ok", "node_id": data.node_id, "created_at": created_at}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ==============================
# POST /tank-parameters — create tank node
# ==============================
@app.post("/tank-parameters")
def create_tank_parameters(data: TankParameters):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
    INSERT INTO tank_sensorparameters
    (node_id, tank_height_cm, tank_length_cm, tank_width_cm, lat, long)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
    """, (
        data.node_id,
        data.tank_height_cm,
        data.tank_diameter_cm,  # diameter stored in tank_length_cm
        0,                       # 0 = cylindrical tank flag
        data.lat,
        data.long
    ))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Tank parameters inserted successfully", "id": new_id}


# ==============================
# GET /tank-parameters — list all nodes
# ==============================
@app.get("/tank-parameters")
def get_tank_parameters():
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM tank_sensorparameters")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{
        "id":             row[0],
        "node_id":        row[1],
        "tank_height_cm": row[2],
        "tank_length_cm": row[3],
        "tank_width_cm":  row[4],
        "lat":            row[5],
        "long":           row[6]
    } for row in rows]


# ==============================
# DELETE /tank-parameters/{node_id}
# ==============================
@app.delete("/tank-parameters/{node_id}")
def delete_tank_node(node_id: str):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("DELETE FROM sensor_data WHERE node_id = %s", (node_id,))
    cur.execute("DELETE FROM tank_sensorparameters WHERE node_id = %s", (node_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": f"Node '{node_id}' and all its sensor data deleted."}


# ==============================
# GET /sensor-data — read from Supabase
# ==============================
@app.get("/sensor-data")
def get_sensor_data(node_id: str = None):
    conn = get_connection()
    cur  = conn.cursor()
    if node_id:
        cur.execute("""
            SELECT id, node_id, field1, field2, created_at
            FROM sensor_data WHERE node_id = %s
            ORDER BY created_at DESC LIMIT 100
        """, (node_id,))
    else:
        cur.execute("""
            SELECT id, node_id, field1, field2, created_at
            FROM sensor_data ORDER BY created_at DESC LIMIT 100
        """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{
        "id":          row[0],
        "node_id":     row[1],
        "temperature": row[2],   # field1
        "water_level": row[3],   # field2
        "created_at":  row[4]
    } for row in rows]


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)