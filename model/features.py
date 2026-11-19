"""Turn raw readings into the numbers the prediction model looks at.

The same function is used for training (60 days at once) and for live
prediction (the last 27 hours), so both see features built the same way.
"""
import pandas as pd

CHANNELS = ["temperature_c", "vibration_mm_s", "belt_speed_mps", "drift_mm"]
BASELINE_MIN = 1440          # a sensor's own normal level = middle value of its last 24 hours
HISTORY_MIN = BASELINE_MIN + 200   # minutes of history needed to build one row of features

FEATURES = ["temp_level", "temp_change_1h", "temp_change_3h",
            "vib_level", "vib_change_1h", "vib_change_3h",
            "drift_level", "drift_change_1h", "drift_change_3h",
            "speed_level", "speed_change_1h", "speed_change_3h"]


def build_features(readings):
    """readings: DataFrame with columns sensor_id, ts, the four channels and flags.

    Returns one row per sensor per minute with the 12 FEATURES columns.
    A value that is missing, impossible or stuck is simply absent: the
    features are built from whatever trusted values remain.
    """
    df = readings.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    # A channel that the backend flagged as stuck is not trusted.
    for ch in CHANNELS:
        stuck = df["flags"].str.contains("stuck:" + ch, regex=False)
        df.loc[stuck, ch] = float("nan")

    # One table per channel: rows = minutes, columns = sensors.
    minutes = pd.date_range(df["ts"].min(), df["ts"].max(), freq="min")
    wide = {}
    for ch in CHANNELS:
        table = df.pivot_table(index="ts", columns="sensor_id", values=ch, aggfunc="last")
        wide[ch] = table.reindex(minutes)
    sensors = list(wide["vibration_mm_s"].columns)

    # Temperature compared with the middle sensor of the same minute.
    # This removes the daily heat wave, which all sensors share.
    temp = wide["temperature_c"].sub(wide["temperature_c"].median(axis=1), axis=0)
    # The belt is one piece: its speed is the middle value of all sensors.
    belt_speed = wide["belt_speed_mps"].median(axis=1)
    speed = pd.DataFrame({sid: belt_speed for sid in sensors})

    tables = {}
    for name, table in [("temp", temp), ("vib", wide["vibration_mm_s"]),
                        ("drift", wide["drift_mm"]), ("speed", speed)]:
        # Middle value of the last 15 minutes: one wild reading cannot move it.
        now = table.rolling(15, min_periods=5).median()
        if name == "speed":
            level = now                                      # the normal belt speed is known: 4 m/s
        else:
            # Compare each sensor with its own normal level, so a sensor that
            # always reads a little high is not mistaken for a failing one.
            level = now - table.rolling(BASELINE_MIN, min_periods=180).median()
        if name == "drift":
            level, now = level.abs(), now.abs()              # left or right does not matter
        tables[name + "_level"] = level
        tables[name + "_change_1h"] = now - now.shift(60)    # compared with 1 hour earlier
        tables[name + "_change_3h"] = now - now.shift(180)   # compared with 3 hours earlier

    frames = []
    for sid in sensors:
        frame = pd.DataFrame({name: table[sid] for name, table in tables.items()})
        frame.insert(0, "sensor_id", sid)
        frame.insert(1, "ts", frame.index)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)[["sensor_id", "ts"] + FEATURES]
