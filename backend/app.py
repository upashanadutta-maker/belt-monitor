"""The HTTP layer. Each function below answers one URL.

Start it from the belt-monitor folder with:
    python -m uvicorn backend.app:app --port 8000
"""
from fastapi import Body, FastAPI

from simulator import config as C
from backend.db import connect
from backend.ingest import ingest

app = FastAPI(title="Belt monitor")

PROCESS_ANOMALIES = ["high_temperature", "high_vibration", "belt_drift", "belt_slip"]
SENSOR_FAULTS = ["sensor_offline", "sensor_stuck"]
DRIVE_SENSOR = "S10"         # belt slip happens at the drive pulley, which is where S10 sits


@app.get("/health")
def health():
    conn = connect()
    count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    clock = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    conn.close()
    return {"status": "ok", "readings": count, "clock": clock}


@app.post("/readings")
def post_readings(messages: list[dict] = Body(...)):
    """The simulator sends its messages here. Each message is checked one by one,
    so one bad message cannot make the whole batch fail."""
    conn = connect()
    summary = ingest(conn, messages, with_predictions=True)
    conn.close()
    return summary


@app.get("/readings")
def get_readings(sensor_id: str, limit: int = 240):
    """The newest readings of one sensor, oldest first (for the dashboard charts)."""
    conn = connect()
    rows = conn.execute("SELECT * FROM readings WHERE sensor_id = ? ORDER BY ts DESC LIMIT ?",
                        (sensor_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


@app.get("/anomalies")
def get_anomalies(active: bool = True, limit: int = 200):
    """Active anomalies, or the most recent ones of any state when active=false."""
    conn = connect()
    where = "WHERE ended_ts IS NULL" if active else ""
    rows = conn.execute(f"SELECT * FROM anomalies {where} ORDER BY started_ts DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/predictions")
def get_predictions(active: bool = True, limit: int = 200):
    """What the model expects to fail, where, and when."""
    conn = connect()
    where = "WHERE ended_ts IS NULL" if active else ""
    rows = conn.execute(f"SELECT * FROM predictions {where} ORDER BY started_ts DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


DEFECT_COLUMNS = ["id", "position_m", "lateral_mm", "type", "severity", "area_cm2", "growth_pct",
                  "first_seen_ts", "last_seen_ts", "laps_seen", "sightings", "confidence", "status", "image"]


@app.post("/defects")
def post_defects(records: list[dict] = Body(...)):
    """The vision component sends its current list of damaged spots. It replaces the old list."""
    conn = connect()
    conn.execute("DELETE FROM defects")
    for r in records:
        conn.execute("INSERT INTO defects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     [r.get(column) for column in DEFECT_COLUMNS])
    conn.commit()
    conn.close()
    return {"stored": len(records)}


@app.get("/defects")
def get_defects():
    """Wear and tear found by the vision component, one row per damaged spot."""
    conn = connect()
    rows = conn.execute("SELECT * FROM defects ORDER BY position_m").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/sensors")
def get_sensors():
    """One entry per sensor point: where it is, its newest reading and its status."""
    conn = connect()
    active = conn.execute("SELECT sensor_id, type, severity FROM anomalies "
                          "WHERE ended_ts IS NULL").fetchall()
    predicted = conn.execute("SELECT sensor_id, failure_type, hours_left FROM predictions "
                             "WHERE ended_ts IS NULL").fetchall()
    result = []
    for sid in C.SENSOR_IDS:
        newest = conn.execute("SELECT * FROM readings WHERE sensor_id = ? ORDER BY ts DESC LIMIT 1",
                              (sid,)).fetchone()
        # Belt slip is stored with sensor 'ALL'. It is shown at the drive pulley sensor.
        names = (sid, "ALL") if sid == DRIVE_SENSOR else (sid,)
        mine = [a for a in active if a["sensor_id"] in names]
        process = [a["type"] for a in mine if a["type"] in PROCESS_ANOMALIES]
        faults = [a["type"] for a in mine if a["type"] in SENSOR_FAULTS]
        expected = [dict(p) for p in predicted if p["sensor_id"] in names]
        if newest is None or "sensor_offline" in faults:
            status = "no_data"                 # no current reading: it cannot be called normal
        elif process:
            status = "abnormal"                # a current reading is past its limit
        elif expected:
            status = "predicted_failure"       # inside the limits, but the model expects a failure
        else:
            status = "normal"
        result.append({"sensor_id": sid, "position_m": C.SENSOR_POSITION_M[sid],
                       "status": status, "anomalies": process, "sensor_faults": faults,
                       "predictions": expected, "newest": dict(newest) if newest else None})
    conn.close()
    return result
