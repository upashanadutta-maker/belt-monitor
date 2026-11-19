"""Compare what the backend stored with the simulator's ground-truth logs.

    python -m analysis.backend_check

Reads data/belt.db (filled by backend.load_csv) and data/train/*.csv.
"""
import csv
from datetime import datetime

from backend.db import connect

DATA = "data/train"
FMT = "%Y-%m-%dT%H:%M:%SZ"
conn = connect()
failures = list(csv.DictReader(open(f"{DATA}/failures.csv")))
faults = list(csv.DictReader(open(f"{DATA}/data_faults.csv")))
anomalies = [dict(r) for r in conn.execute("SELECT * FROM anomalies")]


def hours(a, b):
    return (datetime.strptime(b, FMT) - datetime.strptime(a, FMT)).total_seconds() / 3600


print("MESSY DATA")
# Impossible spikes must be stored as NULL with an out_of_range flag.
impossible = [x for x in faults if x["fault_type"] == "spike" and x["detail"].startswith("impossible")]
caught = 0
for x in impossible:
    r = conn.execute("SELECT * FROM readings WHERE sensor_id = ? AND ts = ?",
                     (x["sensor_id"], x["start_ts"])).fetchone()
    if r is not None and r[x["channel"]] is None and "out_of_range:" + x["channel"] in r["flags"]:
        caught += 1
print(f"  impossible spikes stored as NULL and flagged : {caught} of {len(impossible)}")

nulls = [x for x in faults if x["fault_type"] == "null_field"]
caught = sum(1 for x in nulls if conn.execute(
    "SELECT 1 FROM readings WHERE sensor_id = ? AND ts = ? AND flags LIKE ?",
    (x["sensor_id"], x["start_ts"], "%missing:" + x["channel"] + "%")).fetchone())
print(f"  null values flagged as missing              : {caught} of {len(nulls)}")

late = [x for x in faults if x["fault_type"] == "late"]
flagged = conn.execute("SELECT COUNT(*) FROM readings WHERE flags LIKE '%late%'").fetchone()[0]
print(f"  late readings flagged                       : {flagged} of {len(late)}")

for kind, anomaly_type in [("outage", "sensor_offline"), ("stuck", "sensor_stuck")]:
    windows = [x for x in faults if x["fault_type"] == kind]
    found = 0
    for x in windows:
        for a in anomalies:
            if (a["type"] == anomaly_type and a["sensor_id"] == x["sensor_id"]
                    and a["started_ts"] <= x["end_ts"] and (a["ended_ts"] or "9") >= x["start_ts"]):
                found += 1
                break
    extra = sum(1 for a in anomalies if a["type"] == anomaly_type and not any(
        a["sensor_id"] == x["sensor_id"] and a["started_ts"] <= x["end_ts"]
        and (a["ended_ts"] or "9") >= x["start_ts"] for x in windows))
    print(f"  {kind:6} periods with a {anomaly_type:14} anomaly: {found} of {len(windows)}"
          f"   (anomalies with no matching period: {extra})")

print("\nFAILURES   (warning = hours between the first anomaly and the failure)")
MATCH = {"seized_roller": ["high_vibration", "high_temperature"],
         "belt_drift": ["belt_drift"], "belt_slip": ["belt_slip"]}
for ftype, anomaly_types in MATCH.items():
    episodes = [f for f in failures if f["type"] == ftype]
    for anomaly_type in anomaly_types:
        leads = []
        for f in episodes:
            starts = [a["started_ts"] for a in anomalies
                      if a["type"] == anomaly_type and a["sensor_id"] == f["sensor_id"]
                      and f["onset_ts"] <= a["started_ts"] <= f["failure_ts"]]
            if starts:
                leads.append(hours(min(starts), f["failure_ts"]))
        leads.sort()
        mid = leads[len(leads) // 2] if leads else float("nan")
        # An anomaly is false when it does not overlap any episode of its failure type.
        false = sum(1 for a in anomalies if a["type"] == anomaly_type and not any(
            a["sensor_id"] == f["sensor_id"] and a["started_ts"] <= f["repaired_ts"]
            and (a["ended_ts"] or "9") >= f["onset_ts"] for f in episodes))
        total = sum(1 for a in anomalies if a["type"] == anomaly_type)
        print(f"  {ftype:14} {anomaly_type:17}: caught {len(leads)} of {len(episodes)},"
              f" median warning {mid:4.1f} h, anomalies opened {total}, false {false}")
