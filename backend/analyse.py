"""Turn stored readings into anomalies.

A limit must be broken by 3 readings in a row before an anomaly opens, and
3 readings in a row must be back inside the limit before it closes.
One wild reading therefore changes nothing.
"""
from datetime import datetime
from statistics import median

from simulator import config as C
from backend.validate import TS_FORMAT

IN_A_ROW = 3
STUCK_AFTER = 5              # the same value this many times in a row = stuck sensor
OFFLINE_AFTER_MIN = 5        # no reading for this many minutes = sensor offline

# anomaly type: (channel, warning limit, critical limit)
LIMITS = {
    "high_temperature": ("temperature_c", 70.0, 85.0),
    "high_vibration": ("vibration_mm_s", 4.5, 7.1),
    "belt_drift": ("drift_mm", 75.0, 120.0),          # distance from centre, either side
}
SLIP_WARNING = 0.95 * C.BELT_SPEED_MPS                 # 3.8 m/s
SLIP_CRITICAL = 0.85 * C.BELT_SPEED_MPS                # 3.4 m/s
DRIVE_PULLEY_M = C.CONVEYOR_LENGTH_M


def level(values, warning, critical, low_is_bad=False):
    """Judge the newest 3 values. Returns 'critical', 'warning', 'normal' or 'unknown'."""
    if len(values) < IN_A_ROW or None in values:
        return "unknown"                                # not enough trusted readings
    if low_is_bad:
        values = [-v for v in values]
        warning, critical = -warning, -critical
    if all(v > critical for v in values):
        return "critical"
    if all(v > warning for v in values):
        return "warning"
    if all(v <= warning for v in values):
        return "normal"
    return "unknown"                                    # mixed: keep the current state


def set_anomaly(conn, active, sensor_id, position_m, kind, verdict, ts, value):
    """Open, update or close the anomaly (sensor_id, kind) according to the verdict."""
    key = (sensor_id, kind)
    if verdict == "unknown":
        return
    if verdict == "normal":
        if key in active:
            conn.execute("UPDATE anomalies SET ended_ts = ? WHERE id = ?", (ts, active[key]))
            del active[key]
        return
    if key in active:
        conn.execute("UPDATE anomalies SET severity = ?, value = ?, last_ts = ? WHERE id = ?",
                     (verdict, value, ts, active[key]))
    else:
        cur = conn.execute(
            "INSERT INTO anomalies (sensor_id, position_m, type, severity, value, started_ts, last_ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", (sensor_id, position_m, kind, verdict, value, ts, ts))
        active[key] = cur.lastrowid


def analyse(conn, sensor_ids):
    """Run every rule. sensor_ids = the sensors that just sent a reading."""
    active = {(r["sensor_id"], r["type"]): r["id"] for r in
              conn.execute("SELECT id, sensor_id, type FROM anomalies WHERE ended_ts IS NULL")}
    clock = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    if clock is None:
        return

    for sid in C.SENSOR_IDS:
        position = C.SENSOR_POSITION_M[sid]
        newest = conn.execute("SELECT * FROM readings WHERE sensor_id = ? ORDER BY ts DESC LIMIT ?",
                              (sid, STUCK_AFTER)).fetchall()
        if not newest:
            continue

        # Rule 1: sensor offline. Its newest reading is too far behind the clock.
        behind = datetime.strptime(clock, TS_FORMAT) - datetime.strptime(newest[0]["ts"], TS_FORMAT)
        minutes = behind.total_seconds() / 60
        verdict = "warning" if minutes > OFFLINE_AFTER_MIN else "normal"
        set_anomaly(conn, active, sid, position, "sensor_offline", verdict, clock, minutes)
        if sid not in sensor_ids:
            continue                                    # nothing new from this sensor

        # Rule 2: stuck sensor. One channel shows the exact same value 5 times in a row.
        stuck = []
        for ch in C.CHANNELS:
            values = [r[ch] for r in newest]
            if len(values) == STUCK_AFTER and values[0] is not None and len(set(values)) == 1:
                stuck.append(ch)
        if stuck:
            flags = newest[0]["flags"].split(",") if newest[0]["flags"] else []
            flags += ["stuck:" + ch for ch in stuck if "stuck:" + ch not in flags]
            conn.execute("UPDATE readings SET flags = ? WHERE sensor_id = ? AND ts = ?",
                         (",".join(flags), sid, newest[0]["ts"]))
        set_anomaly(conn, active, sid, position, "sensor_stuck",
                    "warning" if stuck else "normal", newest[0]["ts"], None)

        # Rule 3: limits on temperature, vibration and drift.
        for kind, (ch, warning, critical) in LIMITS.items():
            values = []
            for r in newest[:IN_A_ROW]:
                trusted = r[ch] is not None and "stuck:" + ch not in r["flags"] and ch not in stuck
                values.append(abs(r[ch]) if trusted else None)
            set_anomaly(conn, active, sid, position, kind, level(values, warning, critical),
                        newest[0]["ts"], values[0])

    # Rule 4: belt slip. The belt is one piece, so its speed is judged once per minute
    # as the middle value (median) of all sensors, not sensor by sensor.
    rows = conn.execute("SELECT ts, belt_speed_mps FROM readings WHERE ts IN "
                        "(SELECT DISTINCT ts FROM readings ORDER BY ts DESC LIMIT ?)",
                        (IN_A_ROW,)).fetchall()
    by_minute = {}
    for r in rows:
        by_minute.setdefault(r["ts"], [])
        if r["belt_speed_mps"] is not None:
            by_minute[r["ts"]].append(r["belt_speed_mps"])
    speeds = []
    for ts in sorted(by_minute, reverse=True):
        speeds.append(median(by_minute[ts]) if len(by_minute[ts]) >= 5 else None)
    set_anomaly(conn, active, "ALL", DRIVE_PULLEY_M, "belt_slip",
                level(speeds, SLIP_WARNING, SLIP_CRITICAL, low_is_bad=True), clock,
                speeds[0] if speeds else None)
