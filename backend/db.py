"""The database: one SQLite file with five tables."""
import os
import sqlite3

# The file sits in belt-monitor/data/belt.db unless BELT_DB says otherwise.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("BELT_DB") or os.path.join(PROJECT_DIR, "data", "belt.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    sensor_id       TEXT NOT NULL,
    ts              TEXT NOT NULL,      -- when the sensor measured
    temperature_c   REAL,               -- NULL means missing or impossible
    vibration_mm_s  REAL,
    belt_speed_mps  REAL,
    drift_mm        REAL,
    flags           TEXT NOT NULL,      -- what was wrong with this reading, '' if nothing
    PRIMARY KEY (sensor_id, ts)         -- the same reading cannot be stored twice
);
CREATE INDEX IF NOT EXISTS readings_by_ts ON readings (ts);

CREATE TABLE IF NOT EXISTS rejected (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    reason  TEXT NOT NULL,
    raw     TEXT NOT NULL               -- the message exactly as it came in
);

CREATE TABLE IF NOT EXISTS anomalies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id   TEXT NOT NULL,          -- 'ALL' for belt slip
    position_m  INTEGER NOT NULL,
    type        TEXT NOT NULL,
    severity    TEXT NOT NULL,          -- 'warning' or 'critical'
    value       REAL,                   -- the latest value that broke the limit
    started_ts  TEXT NOT NULL,
    last_ts     TEXT NOT NULL,
    ended_ts    TEXT                    -- NULL while the anomaly is still active
);

CREATE TABLE IF NOT EXISTS predictions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id             TEXT NOT NULL,     -- 'ALL' for belt slip
    position_m            INTEGER NOT NULL,
    failure_type          TEXT NOT NULL,     -- what the model expects to fail
    probability           REAL NOT NULL,     -- how sure the model is, 0 to 1
    hours_left            REAL NOT NULL,     -- the model's estimate at last_ts
    predicted_failure_ts  TEXT NOT NULL,     -- last_ts + hours_left
    started_ts            TEXT NOT NULL,
    last_ts               TEXT NOT NULL,
    ended_ts              TEXT               -- NULL while the prediction is still active
);

CREATE TABLE IF NOT EXISTS defects (
    id             TEXT PRIMARY KEY,         -- one row per damaged spot on the belt
    position_m     REAL NOT NULL,            -- where on the 6 km loop
    lateral_mm     REAL NOT NULL,            -- how far across the belt
    type           TEXT NOT NULL,
    severity       TEXT NOT NULL,
    area_cm2       REAL NOT NULL,
    growth_pct     REAL,                     -- size change since first seen, NULL until 3 laps
    first_seen_ts  TEXT NOT NULL,
    last_seen_ts   TEXT NOT NULL,
    laps_seen      INTEGER NOT NULL,
    sightings      INTEGER NOT NULL,
    confidence     REAL NOT NULL,
    status         TEXT NOT NULL,            -- 'active', 'new', 'not_seen' or 'repaired'
    image          TEXT NOT NULL             -- path of the newest photo with the outline drawn
);
"""


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row          # rows can be read by column name
    conn.execute("PRAGMA journal_mode=WAL")  # the dashboard can read while the backend writes
    conn.executescript(SCHEMA)
    return conn
