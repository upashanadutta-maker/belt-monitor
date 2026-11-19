"""Belt health dashboard.

Start it from the belt-monitor folder with:
    python -m streamlit run dashboard/app.py --server.port 8501

It only reads from the backend's HTTP API, the same way any other program could.
"""
import json
import os
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

API = os.environ.get("BELT_API", "http://127.0.0.1:8000")
DOT = {"normal": "🟢", "abnormal": "🔴", "predicted_failure": "🟠", "no_data": "⚪"}
WORD = {"normal": "normal", "abnormal": "abnormal", "predicted_failure": "predicted failure",
        "no_data": "no data"}


def get(path):
    with urllib.request.urlopen(API + path, timeout=10) as response:
        return json.load(response)


def where(sensor_id, position_m):
    if sensor_id == "ALL":
        return f"drive pulley, {position_m} m"
    return f"{sensor_id}, {position_m} m"


st.set_page_config(page_title="Belt monitor", layout="wide")
st.title("Conveyor belt health")

try:
    health = get("/health")
except OSError as error:
    st.error(f"The backend is not reachable at {API}: {error}")
    st.stop()

sensors = get("/sensors")
anomalies = get("/anomalies")
predictions = get("/predictions")
defects = get("/defects")

st.caption(f"Belt time: {health['clock']}  |  3 km conveyor, 6 km belt loop, 4 m/s  |  "
           f"{health['readings']} readings stored")
if st.button("Refresh"):
    st.rerun()

faults = [a for a in anomalies if a["type"] in ("sensor_offline", "sensor_stuck")]
process = [a for a in anomalies if a not in faults]
open_damage = [d for d in defects if d["severity"] != "repair" and d["status"] in ("active", "new")]
top = st.columns(5)
top[0].metric("Sensor points normal", sum(1 for s in sensors if s["status"] == "normal"))
top[1].metric("Active anomalies", len(process))
top[2].metric("Predicted failures", len(predictions))
top[3].metric("Sensor faults", len(faults))
top[4].metric("Damaged spots on the belt", len(open_damage))

# ---------------------------------------------------------------- 1. sensor points
st.header("1. Sensor points")
st.caption("🟢 normal   🔴 abnormal: a reading is past its limit   "
           "🟠 predicted failure: inside the limits, but the model expects a failure   "
           "⚪ no data: the sensor is silent")
for column, s in zip(st.columns(len(sensors)), sensors):
    column.markdown(f"### {DOT[s['status']]} {s['sensor_id']}")
    column.caption(f"{s['position_m']} m")
    column.write(WORD[s["status"]])
    reading = s["newest"] or {}
    lines = []
    for label, key, unit in [("T", "temperature_c", "°C"), ("V", "vibration_mm_s", "mm/s"),
                             ("S", "belt_speed_mps", "m/s"), ("D", "drift_mm", "mm")]:
        value = reading.get(key)
        lines.append(f"{label}: {'missing' if value is None else f'{value:.1f} {unit}'}")
    column.caption("  \n".join(lines))
    if s["sensor_faults"]:
        column.caption("fault: " + ", ".join(f.replace("sensor_", "") for f in s["sensor_faults"]))

# ---------------------------------------------------------------- 2. anomalies
st.header("2. Active anomalies")
if process:
    st.dataframe(pd.DataFrame([{"location": where(a["sensor_id"], a["position_m"]),
                                "type": a["type"], "severity": a["severity"],
                                "latest value": a["value"], "since": a["started_ts"]}
                               for a in process]), hide_index=True)
else:
    st.success("No reading is past its limit.")
if faults:
    st.subheader("Sensor faults (the data cannot be trusted)")
    st.dataframe(pd.DataFrame([{"location": where(a["sensor_id"], a["position_m"]),
                                "type": a["type"], "since": a["started_ts"]}
                               for a in faults]), hide_index=True)

# ---------------------------------------------------------------- 3. predictions
st.header("3. Model predictions")
if predictions:
    st.dataframe(pd.DataFrame([{"what might fail": p["failure_type"],
                                "where": where(p["sensor_id"], p["position_m"]),
                                "when (estimate)": p["predicted_failure_ts"],
                                "hours left": round(p["hours_left"], 1),
                                "how sure": f"{p['probability'] * 100:.0f} %",
                                "predicted since": p["started_ts"]}
                               for p in predictions]), hide_index=True)
else:
    st.success("The model expects no failure.")

# ---------------------------------------------------------------- 4. vision
st.header("4. Vision: wear and tear on the belt")
st.caption("One row per damaged spot, however many laps the camera has seen it. "
           "Position is measured along the 6 km loop from the reference mark.")
if defects:
    table = pd.DataFrame(defects)
    by_type = table[table["severity"] != "repair"]["type"].value_counts()
    st.write("Damaged spots by type: " + ", ".join(f"{name} {count}" for name, count in by_type.items())
             + f"  |  old repairs (patch work): {int((table['severity'] == 'repair').sum())}")
    order = {"severe": 0, "moderate": 1, "minor": 2, "repair": 3}
    table["rank"] = table["severity"].map(order)
    table = table.sort_values(["rank", "growth_pct"], ascending=[True, False])
    st.dataframe(table[["id", "position_m", "lateral_mm", "type", "severity", "area_cm2",
                        "growth_pct", "laps_seen", "status", "last_seen_ts"]], hide_index=True)
    with_photo = [d for d in table.to_dict("records") if d["image"] and os.path.exists(d["image"])]
    if with_photo:
        names = [f"{d['id']}  {d['type']}  at {d['position_m']} m" for d in with_photo]
        chosen = st.selectbox("Show the newest photo of", names)
        st.image(with_photo[names.index(chosen)]["image"], width=520)
else:
    st.info("The vision component has not sent any records yet.")

# ---------------------------------------------------------------- 5. history
PANELS = [("temperature_c", "Temperature (°C)", [70, 85]),
          ("vibration_mm_s", "Vibration (mm/s)", [4.5, 7.1]),
          ("belt_speed_mps", "Belt speed (m/s)", [3.8, 3.4]),
          ("drift_mm", "Sideways drift (mm)", [75, 120, -75, -120])]


def history_figure(history):
    """Four small charts. Dashed lines are the limits: orange = warning, red = critical."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 6.5), sharex=True)
    for ax, (column, title, limits) in zip(axes.flat, PANELS):
        ax.plot(history.index, history[column], linewidth=1.2, color="#1f77b4")
        for number, limit in enumerate(limits):
            ax.axhline(limit, linestyle="--", linewidth=1, color="orange" if number % 2 == 0 else "red")
        ax.set_title(title, loc="left")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.tight_layout()
    return fig


st.header("5. One sensor over the last 4 hours")
# Sensors that are not normal come first in the list.
names = [s["sensor_id"] for s in sorted(sensors, key=lambda s: s["status"] == "normal")]
sensor_id = st.selectbox("Sensor", names)
history = pd.DataFrame(get(f"/readings?sensor_id={sensor_id}&limit=240"))
if len(history):
    # Belt time, without converting to the viewer's time zone.
    history["ts"] = pd.to_datetime(history["ts"]).dt.tz_localize(None)
    history = history.set_index("ts")
    st.caption("Dashed lines are the limits: orange = warning, red = critical. Times are belt time.")
    st.pyplot(history_figure(history))

with st.expander("Recently closed anomalies and predictions"):
    past = [a for a in get("/anomalies?active=false&limit=30") if a["ended_ts"]]
    st.dataframe(pd.DataFrame([{"location": where(a["sensor_id"], a["position_m"]), "type": a["type"],
                                "severity": a["severity"], "from": a["started_ts"], "to": a["ended_ts"]}
                               for a in past]), hide_index=True)
    past = [p for p in get("/predictions?active=false&limit=30") if p["ended_ts"]]
    st.dataframe(pd.DataFrame([{"what": p["failure_type"], "where": where(p["sensor_id"], p["position_m"]),
                                "from": p["started_ts"], "to": p["ended_ts"]} for p in past]),
                 hide_index=True)
