"""Receive one batch of messages: validate, store, analyse."""
import json

from backend.analyse import analyse
from backend.validate import validate


def ingest(conn, messages, commit=True, with_predictions=False):
    """Store a list of messages. Returns counts of what happened to them."""
    summary = {"received": len(messages), "stored": 0, "rejected": 0, "duplicate": 0, "late": 0}
    # The backend's clock is the newest timestamp it has stored so far.
    clock = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    touched = set()

    for message in messages:
        row, flags, reason = validate(message)
        if reason is not None:
            conn.execute("INSERT INTO rejected (reason, raw) VALUES (?, ?)",
                         (reason, json.dumps(message, default=str)))
            summary["rejected"] += 1
            continue
        late = clock is not None and row["ts"] < clock
        if late:
            flags.append("late")                 # older than something already stored
        cur = conn.execute(
            "INSERT OR IGNORE INTO readings VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["sensor_id"], row["ts"], row["temperature_c"], row["vibration_mm_s"],
             row["belt_speed_mps"], row["drift_mm"], ",".join(flags)))
        if cur.rowcount == 0:
            summary["duplicate"] += 1            # this sensor and timestamp are already stored
            continue
        summary["stored"] += 1
        summary["late"] += 1 if late else 0
        touched.add(row["sensor_id"])

    if summary["stored"]:
        analyse(conn, touched)
        # Every 5 simulated minutes, ask the prediction model.
        newest = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
        if with_predictions and newest != clock and int(newest[14:16]) % 5 == 0:
            from backend.predict import predict
            predict(conn, newest)
    if commit:
        conn.commit()
    return summary
