"""Load a readings.csv written by the simulator into the database.

    python -m backend.load_csv data/train/readings.csv

Rows are fed to ingest() minute by minute in arrival order, so the backend
sees exactly what it would see from the live feed.
"""
import csv
import sys
import time

from simulator import config as C
from backend.db import connect
from backend.ingest import ingest


def to_message(row):
    message = {"sensor_id": row["sensor_id"], "ts": row["ts"]}
    for ch in C.CHANNELS:
        message[ch] = None if row[ch] == "" else float(row[ch])
    return message


def load(csv_path, db_path=None):
    conn = connect(db_path)
    total = {"received": 0, "stored": 0, "rejected": 0, "duplicate": 0, "late": 0}
    batch, batch_arrival, batches = [], None, 0
    started = time.time()

    def flush():
        result = ingest(conn, batch, commit=False)
        for key in total:
            total[key] += result[key]

    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row["arrival_ts"] != batch_arrival and batch:
                flush()
                batch = []
                batches += 1
                if batches % 1000 == 0:
                    conn.commit()
            batch_arrival = row["arrival_ts"]
            batch.append(to_message(row))
    if batch:
        flush()
    conn.commit()
    print(f"{total} in {time.time() - started:.0f} s")
    return conn


if __name__ == "__main__":
    load(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
