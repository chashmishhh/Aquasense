import psycopg2
from psycopg2 import pool as pg_pool
import os
import time
import json
import ssl
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Query
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
# DATABASE — ThreadedConnectionPool (transaction mode, port 6543)
# Supabase session mode (port 5432) allows max 15 connections.
# Transaction mode (port 6543) supports many more concurrent clients.
# The pool keeps 1-8 connections alive and reuses them across requests.
# ==============================
DB_DSN = (
    "host=aws-1-ap-south-1.pooler.supabase.com "
    "port=6543 "
    "dbname=postgres "
    "user=postgres.cguaghcgesxgmrghaghg "
    "password=SamiRaj@2416 "
    "sslmode=require"
)

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

def get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=8, dsn=DB_DSN)
                print("[DB] Connection pool created (1-8 connections, transaction mode)")
    return _pool

def get_conn():
    """Borrow a connection from the pool."""
    return get_pool().getconn()

def put_conn(conn, success=True):
    """Return a connection to the pool. Rolls back on failure."""
    if conn is None:
        return
    try:
        if not success:
            conn.rollback()
    except Exception:
        pass
    get_pool().putconn(conn)

# Legacy alias — kept so create_tables() and MQTT handler work unchanged
def get_connection():
    return get_conn()


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
    put_conn(conn)


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
    conn = None
    try:
        raw = msg.payload.decode('utf-8', errors='ignore')
        print(f"[MQTT] Received on {msg.topic}: {raw}")
        payload     = json.loads(raw)
        node_id     = payload.get("node_id", "UNKNOWN")
        temperature = float(payload.get("temperature", 0))
        water_level = float(payload.get("water_level", 0))
        created_at  = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO sensor_data (node_id, field1, field2, created_at)
            VALUES (%s, %s, %s, %s)
        """, (node_id, temperature, water_level, created_at))
        conn.commit()
        cur.close()
        print(f"[MQTT] Saved -> node={node_id}  temp={temperature}C  level={water_level}cm")
    except json.JSONDecodeError:
        print(f"[MQTT] Ignoring non-JSON message on {msg.topic}")
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")
        put_conn(conn, success=False)
        conn = None
    finally:
        put_conn(conn)


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
    try:
        create_tables()
        print("[DB] Tables ready")
    except Exception as e:
        print(f"[DB] WARNING: Could not create tables on startup: {e}")
        print("[DB] Will retry on first request. Continuing startup...")
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
    conn = None
    try:
        conn = get_conn()
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
        put_conn(conn, success=False)
        conn = None
        return {"status": "error", "detail": str(e)}
    finally:
        put_conn(conn)


# ==============================
# POST /ingest — fallback HTTP ingest (if MQTT fails)
# ==============================
@app.post("/ingest")
def ingest_sensor_data(data: SensorData):
    conn = None
    try:
        created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO sensor_data (node_id, field1, field2, created_at)
            VALUES (%s, %s, %s, %s)
        """, (data.node_id, data.temperature, data.water_level, created_at))
        conn.commit()
        cur.close()
        print(f"[ingest] node={data.node_id} temp={data.temperature} level={data.water_level}")
        return {"status": "ok", "node_id": data.node_id, "created_at": created_at}
    except Exception as e:
        put_conn(conn, success=False)
        conn = None
        return {"status": "error", "detail": str(e)}
    finally:
        put_conn(conn)


# ==============================
# POST /tank-parameters — create tank node
# ==============================
@app.post("/tank-parameters")
def create_tank_parameters(data: TankParameters):
    conn = None
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
        INSERT INTO tank_sensorparameters
        (node_id, tank_height_cm, tank_length_cm, tank_width_cm, lat, long)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """, (
            data.node_id,
            data.tank_height_cm,
            data.tank_diameter_cm,
            0,
            data.lat,
            data.long
        ))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"message": "Tank parameters inserted successfully", "id": new_id}
    finally:
        put_conn(conn)


# ==============================
# GET /tank-parameters — list all nodes (with pagination)
# ==============================
@app.get("/tank-parameters")
def get_tank_parameters(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    sort_by: str = Query("id"),
    sort_order: str = Query("asc")
):
    conn = None
    try:
        conn = get_conn()
        cur  = conn.cursor()
        allowed_cols = {"id", "node_id", "tank_height_cm", "lat", "long"}
        col   = sort_by if sort_by in allowed_cols else "id"
        order = "DESC" if sort_order.lower() == "desc" else "ASC"
        cur.execute("SELECT COUNT(*) FROM tank_sensorparameters")
        total = cur.fetchone()[0]
        offset = (page - 1) * size
        cur.execute(
            f"SELECT * FROM tank_sensorparameters ORDER BY {col} {order} LIMIT %s OFFSET %s",
            (size, offset)
        )
        rows = cur.fetchall()
        cur.close()
        items = [{
            "id":             row[0],
            "node_id":        row[1],
            "tank_height_cm": row[2],
            "tank_length_cm": row[3],
            "tank_width_cm":  row[4],
            "lat":            row[5],
            "long":           row[6]
        } for row in rows]
        return {"total": total, "page": page, "size": size, "items": items}
    finally:
        put_conn(conn)


# ==============================
# DELETE /tank-parameters/{node_id}
# ==============================
@app.delete("/tank-parameters/{node_id}")
def delete_tank_node(node_id: str):
    conn = None
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("DELETE FROM sensor_data WHERE node_id = %s", (node_id,))
        cur.execute("DELETE FROM tank_sensorparameters WHERE node_id = %s", (node_id,))
        conn.commit()
        cur.close()
        return {"message": f"Node '{node_id}' and all its sensor data deleted."}
    finally:
        put_conn(conn)


# ==============================
# GET /node-status — returns online/offline based on last reading age
# ==============================
@app.get("/node-status")
def get_node_status(node_id: str = "NODE_001"):
    """Returns online=True if the node sent data in the last 10 minutes."""
    conn = None
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at FROM sensor_data
            WHERE node_id = %s
            ORDER BY created_at DESC LIMIT 1
        """, (node_id,))
        row = cur.fetchone()
        cur.close()
        if row is None:
            return {"online": False, "last_seen": None, "reason": "no_data"}
        last_seen = row[0]
        delta_seconds = (datetime.utcnow() - last_seen).total_seconds()
        online = delta_seconds <= 600
        return {"online": online, "last_seen": str(last_seen), "seconds_ago": int(delta_seconds)}
    except Exception as e:
        put_conn(conn, success=False)
        conn = None
        return {"online": False, "last_seen": None, "reason": str(e)}
    finally:
        put_conn(conn)


# ==============================
# GET /sensor-data — read from Supabase
# ==============================
@app.get("/sensor-data")
def get_sensor_data(node_id: str = None):
    conn = None
    try:
        conn = get_conn()
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
        return [{
            "id":          row[0],
            "node_id":     row[1],
            "temperature": row[2],
            "water_level": row[3],
            "created_at":  row[4]
        } for row in rows]
    finally:
        put_conn(conn)


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)