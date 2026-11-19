"""Train and test the failure prediction model.

    python -m model.train data/train.db data/train/failures.csv

It answers two questions for every sensor, every 5 minutes:
  1. Is a failure developing, and which one?      (classifier)
  2. If yes, how many hours are left?             (one regressor per failure type)

The history is cut in two by time. The model learns from the first part and is
tested on the second part, so no failure episode is seen in both.
"""
import sqlite3
import sys

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from model.features import FEATURES, build_features

STEP_MIN = 5                 # one prediction every 5 minutes
ALERT_PROBABILITY = 0.8      # how sure the model must be
ALERT_IN_A_ROW = 3           # for how many predictions in a row (3 x 5 = 15 minutes)
TRAIN_SHARE = 0.7
SETTLE_MIN = 20              # minutes after a repair that are left out of training and testing
TYPES = ["seized_roller", "belt_drift", "belt_slip"]
# Which backend anomalies belong to which failure type (used only for the comparison).
LIMIT_TYPES = {"seized_roller": ["high_vibration", "high_temperature"],
               "belt_drift": ["belt_drift"], "belt_slip": ["belt_slip"]}


def add_labels(rows, failures):
    """Give every row a label: 'none', a failure type, or 'settling' (just after a repair)."""
    rows = rows.copy()
    rows["label"] = "none"
    rows["hours_left"] = float("nan")
    rows["failure_id"] = ""
    # Slip first, so a fault on one sensor (roller, drift) overwrites it for that sensor.
    for f in failures.sort_values("type", key=lambda s: s != "belt_slip").itertuples():
        this_sensor = (rows["sensor_id"] == f.sensor_id) | (f.sensor_id == "ALL")
        # From onset to repair the fault is present. Before the failure moment the
        # hours left count down; from the failure moment on they are 0.
        present = this_sensor & (rows["ts"] >= f.onset_ts) & (rows["ts"] < f.repaired_ts)
        left = (f.failure_ts - rows.loc[present, "ts"]).dt.total_seconds() / 3600
        rows.loc[present, "label"] = f.type
        rows.loc[present, "hours_left"] = left.clip(lower=0)
        rows.loc[present, "failure_id"] = f.failure_id
        # Just after the repair the 15-minute window still holds failed readings.
        settled_ts = f.repaired_ts + pd.Timedelta(minutes=SETTLE_MIN)
        settling = this_sensor & (rows["ts"] >= f.repaired_ts) & (rows["ts"] < settled_ts)
        rows.loc[settling, "label"] = "settling"
    return rows


def find_alerts(rows, classifier):
    """Add the model's answer to every row, and mark where an alert would be raised."""
    rows = rows.sort_values(["sensor_id", "ts"]).copy()
    probabilities = classifier.predict_proba(rows[FEATURES])
    rows["predicted"] = classifier.classes_[probabilities.argmax(axis=1)]
    rows["probability"] = probabilities.max(axis=1)
    sure = (rows["predicted"] != "none") & (rows["probability"] >= ALERT_PROBABILITY)
    # An alert needs the same sure answer 3 times in a row on the same sensor.
    run = sure.astype(int)
    for back in range(1, ALERT_IN_A_ROW):
        same = (rows["sensor_id"] == rows["sensor_id"].shift(back)) & \
               (rows["predicted"] == rows["predicted"].shift(back))
        run = run + (sure.shift(back, fill_value=False) & same).astype(int)
    rows["alert"] = run == ALERT_IN_A_ROW
    return rows


def main(db_path, failures_path, model_path="model/belt_model.joblib"):
    conn = sqlite3.connect(db_path)
    readings = pd.read_sql("SELECT * FROM readings", conn)
    anomalies = pd.read_sql("SELECT * FROM anomalies", conn)
    anomalies["started_ts"] = pd.to_datetime(anomalies["started_ts"]).dt.tz_localize(None)
    failures = pd.read_csv(failures_path)
    for column in ["onset_ts", "failure_ts", "repaired_ts"]:
        failures[column] = pd.to_datetime(failures[column]).dt.tz_localize(None)

    rows = build_features(readings)
    rows["ts"] = rows["ts"].dt.tz_localize(None)
    rows = rows[rows["ts"].dt.minute % STEP_MIN == 0]
    rows = add_labels(rows, failures)

    # Cut the history by time, at a moment when no failure episode is running.
    start, end = rows["ts"].min(), rows["ts"].max()
    cut = start + (end - start) * TRAIN_SHARE
    while ((failures["onset_ts"] <= cut) & (failures["repaired_ts"] >= cut)).any():
        cut += pd.Timedelta(hours=1)
    usable = rows[rows["label"] != "settling"]
    train, test = usable[usable["ts"] < cut], usable[usable["ts"] >= cut]
    print(f"history cut at {cut}")
    print(f"train rows {len(train)}, test rows {len(test)}")
    for t in TYPES:
        print(f"  {t:14} episodes: train {train.loc[train.label == t, 'failure_id'].nunique()}, "
              f"test {test.loc[test.label == t, 'failure_id'].nunique()}")

    classifier = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=0)
    classifier.fit(train[FEATURES], train["label"])
    regressors = {}
    for t in TYPES:
        part = train[train["label"] == t]
        regressors[t] = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.1, random_state=0)
        regressors[t].fit(part[FEATURES], part["hours_left"])

    # ---------------- test on the part of the history the model has never seen
    test = find_alerts(test, classifier)
    print("\nTEST RESULTS")
    print(f"{'failure type':15}{'episodes':>9}{'warned':>8}{'model warning h':>16}{'fixed limits h':>17}"
          f"{'hours-left error h':>20}")
    test_failures = failures[failures["onset_ts"] >= cut]
    for t in TYPES:
        leads, limit_leads, errors = [], [], []
        episodes = test_failures[test_failures["type"] == t]
        for f in episodes.itertuples():
            # Alerts of the right type, raised before the failure moment.
            hit = test[(test["failure_id"] == f.failure_id) & test["alert"] &
                       (test["predicted"] == t) & (test["ts"] < f.failure_ts)]
            if len(hit):
                first = hit.sort_values("ts").iloc[0]
                leads.append((f.failure_ts - first["ts"]).total_seconds() / 3600)
                guess = regressors[t].predict(hit[FEATURES])
                errors.extend(abs(guess - hit["hours_left"]))
            # For comparison: when did the backend's fixed limits first react?
            mine = anomalies[(anomalies["sensor_id"] == f.sensor_id) & anomalies["type"].isin(LIMIT_TYPES[t]) &
                             (anomalies["started_ts"] >= f.onset_ts) & (anomalies["started_ts"] < f.failure_ts)]
            if len(mine):
                limit_leads.append((f.failure_ts - mine["started_ts"].min()).total_seconds() / 3600)
        leads = pd.Series(leads, dtype=float)
        errors = pd.Series(errors, dtype=float)
        limit_leads = pd.Series(limit_leads, dtype=float)
        print(f"{t:15}{len(episodes):>9}{len(leads):>8}{leads.median():>16.1f}{limit_leads.median():>17.1f}"
              f"{errors.median():>20.1f}")

    # A false alert = an alert on a sensor that has no failure developing.
    false = test[test["alert"] & (test["label"] == "none")]
    starts = false[~((false["sensor_id"] == false["sensor_id"].shift(1)) &
                     (false["ts"] - false["ts"].shift(1) <= pd.Timedelta(minutes=STEP_MIN)))]
    days = (end - cut).total_seconds() / 86400
    print(f"\nfalse alerts in {days:.0f} test days: {len(starts)}")
    wrong_type = test[test["alert"] & test["label"].isin(TYPES) & (test["predicted"] != test["label"])]
    print(f"alerts that named the wrong failure type: {len(wrong_type)} of {int(test['alert'].sum())}")

    joblib.dump({"classifier": classifier, "regressors": regressors, "features": FEATURES,
                 "alert_probability": ALERT_PROBABILITY, "alert_in_a_row": ALERT_IN_A_ROW,
                 "step_min": STEP_MIN}, model_path)
    print(f"\nmodel saved to {model_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
