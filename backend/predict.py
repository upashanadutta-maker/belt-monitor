"""Run the trained model on the newest readings and keep the predictions table up to date.

Called by ingest() every 5 simulated minutes. If no trained model file exists yet,
it does nothing, so the backend also works before the model is trained.
"""
import os
from datetime import datetime, timedelta

from simulator import config as C
from backend.db import PROJECT_DIR
from backend.validate import TS_FORMAT

MODEL_PATH = os.environ.get("BELT_MODEL") or os.path.join(PROJECT_DIR, "model", "belt_model.joblib")
SLIP_SENSORS_NEEDED = 6      # belt slip is predicted only when this many sensors agree
_model = None


def load_model():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        import joblib
        _model = joblib.load(MODEL_PATH)
    return _model


def set_prediction(conn, active, sensor_id, position_m, kind, verdict, ts, probability, hours_left):
    """Open, update or close the prediction (sensor_id, kind). verdict: True, False or None."""
    key = (sensor_id, kind)
    if verdict is None:
        return                                             # no clear answer: keep the current state
    if verdict is False:
        if key in active:
            conn.execute("UPDATE predictions SET ended_ts = ? WHERE id = ?", (ts, active[key]))
        return
    fails_at = (datetime.strptime(ts, TS_FORMAT) + timedelta(hours=hours_left)).strftime(TS_FORMAT)
    if key in active:
        conn.execute("UPDATE predictions SET probability = ?, hours_left = ?, predicted_failure_ts = ?,"
                     " last_ts = ? WHERE id = ?", (probability, hours_left, fails_at, ts, active[key]))
    else:
        conn.execute("INSERT INTO predictions (sensor_id, position_m, failure_type, probability,"
                     " hours_left, predicted_failure_ts, started_ts, last_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (sensor_id, position_m, kind, probability, hours_left, fails_at, ts, ts))


def predict(conn, clock):
    """clock: the newest timestamp in the database (text)."""
    model = load_model()
    if model is None:
        return
    import pandas as pd
    from model.features import FEATURES, HISTORY_MIN, build_features

    step, in_a_row = model["step_min"], model["alert_in_a_row"]
    now = datetime.strptime(clock, TS_FORMAT)
    since = (now - timedelta(minutes=HISTORY_MIN + step * in_a_row)).strftime(TS_FORMAT)
    readings = pd.read_sql("SELECT * FROM readings WHERE ts >= ?", conn, params=(since,))
    rows = build_features(readings)
    # Keep the newest 3 prediction moments: now, 5 minutes ago, 10 minutes ago.
    moments = [pd.Timestamp(now - timedelta(minutes=step * k)) for k in range(in_a_row)]
    rows = rows[rows["ts"].dt.tz_localize(None).isin(moments)]
    if rows.empty:
        return
    probabilities = model["classifier"].predict_proba(rows[FEATURES])
    classes = model["classifier"].classes_
    rows = rows.assign(predicted=classes[probabilities.argmax(axis=1)],
                       probability=probabilities.max(axis=1))

    active = {(r["sensor_id"], r["failure_type"]): r["id"] for r in
              conn.execute("SELECT id, sensor_id, failure_type FROM predictions WHERE ended_ts IS NULL")}
    slip_votes = []
    for sid in C.SENSOR_IDS:
        mine = rows[rows["sensor_id"] == sid].sort_values("ts")
        if len(mine) < in_a_row:
            continue
        newest = mine.iloc[[-1]]
        answers = list(mine["predicted"])
        sure = all(mine["probability"] >= model["alert_probability"])
        for kind in ["seized_roller", "belt_drift", "belt_slip"]:
            if all(a == kind for a in answers) and sure:
                verdict = True                             # 3 sure answers in a row
            elif all(a != kind for a in answers):
                verdict = False                            # 3 answers in a row say it is not this
            else:
                verdict = None
            hours = float(model["regressors"][kind].predict(newest[FEATURES])[0]) if verdict else 0.0
            hours = max(hours, 0.0)
            if kind == "belt_slip":
                slip_votes.append((verdict, float(newest["probability"].iloc[0]), hours))
            else:
                set_prediction(conn, active, sid, C.SENSOR_POSITION_M[sid], kind, verdict, clock,
                               float(newest["probability"].iloc[0]), hours)

    # Belt slip concerns the whole belt, so the sensors vote.
    yes = [v for v in slip_votes if v[0] is True]
    no = [v for v in slip_votes if v[0] is False]
    if len(yes) >= SLIP_SENSORS_NEEDED:
        yes.sort(key=lambda v: v[2])
        middle = yes[len(yes) // 2]
        set_prediction(conn, active, "ALL", C.CONVEYOR_LENGTH_M, "belt_slip", True, clock, middle[1], middle[2])
    elif len(no) >= SLIP_SENSORS_NEEDED:
        set_prediction(conn, active, "ALL", C.CONVEYOR_LENGTH_M, "belt_slip", False, clock, 0.0, 0.0)
