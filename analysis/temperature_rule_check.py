"""Answers one design question with data: which temperature warning rule to use?

Four rules are tested on every seized-roller episode in data/train:
  A  fixed limit        : reading above 70 C
  B  own recent average : reading 10 C above the sensor's own average of the last 1 hour
  C  own daily average  : reading 10 C above the sensor's own average of the last 24 hours
  D  other sensors      : reading 10 C above the middle value (median) of the other 9
                          sensors in the same minute

A rule counts only when it is true for 3 readings in a row, so one spike cannot set it off.

For each rule the script prints
  - in how many episodes it gave a warning before the failure, and how early
  - how many false warnings it gave on sensors that had no roller fault

Run with:  python -m analysis.temperature_rule_check
"""
import pandas as pd

DATA = "data/train"
IN_A_ROW = 3

readings = pd.read_csv(f"{DATA}/readings.csv", parse_dates=["ts"])
failures = pd.read_csv(f"{DATA}/failures.csv", parse_dates=["onset_ts", "failure_ts", "repaired_ts"])
rollers = failures[failures["type"] == "seized_roller"]

# One row per minute, one column per sensor. A missing or impossible reading is left empty.
temp = readings.pivot_table(index="ts", columns="sensor_id", values="temperature_c", aggfunc="last")
temp = temp.where((temp >= -20) & (temp <= 200))

rules = {}
rules["A fixed 70 C"] = temp > 70
rules["B own 1 h average + 10"] = temp > temp.rolling("60min").mean().shift(1) + 10
rules["C own 24 h average + 10"] = temp > temp.rolling("24h").mean().shift(1) + 10
others = pd.DataFrame({s: temp.drop(columns=s).median(axis=1) for s in temp.columns})
rules["D other sensors + 10"] = temp > others + 10

# True for the minutes where a sensor really has a roller fault (onset to repair).
faulty = pd.DataFrame(False, index=temp.index, columns=temp.columns)
for f in rollers.itertuples():
    faulty.loc[f.onset_ts:f.repaired_ts, f.sensor_id] = True

print(f"{len(rollers)} seized-roller episodes\n")
print(f"{'rule':26}{'warned before failure':>24}{'median warning (h)':>20}{'false warnings':>16}")
for name, hit in rules.items():
    # Keep a hit only if this reading and the 2 before it are all hits.
    hit = hit.astype(int).rolling(IN_A_ROW).sum() == IN_A_ROW
    lead_hours = []
    for f in rollers.itertuples():
        window = hit.loc[f.onset_ts:f.failure_ts, f.sensor_id]
        if window.any():
            first = window.idxmax()
            lead_hours.append((f.failure_ts - first).total_seconds() / 3600)
    # A false warning = the start of a run of hits on a sensor with no roller fault.
    false_hit = hit & ~faulty
    starts = false_hit & ~false_hit.shift(1, fill_value=False)
    median = pd.Series(lead_hours).median() if lead_hours else float("nan")
    print(f"{name:26}{len(lead_hours):>17} of {len(rollers):<4}{median:>20.1f}{int(starts.sum().sum()):>16}")
