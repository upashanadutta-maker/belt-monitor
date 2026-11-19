"""Conveyor belt sensor simulator.

One BeltSimulator object produces three things:
  ticks()      -> the sensor messages, minute by minute, in the order they ARRIVE
  failures     -> ground truth: every failure episode that was injected
  data_faults  -> ground truth: every piece of messy data that was injected

Time is counted in whole minutes from the start. "m" always means "minute number".
"""
import math
import random
from datetime import datetime, timedelta

from simulator import config as C


class BeltSimulator:
    def __init__(self, days, seed, start="2026-09-01T00:00:00Z", messy=True):
        self.rng = random.Random(seed)          # same seed -> exactly the same data
        self.total_min = int(days * 24 * 60)
        self.start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        self.messy = messy                      # False -> no messy data, failures only
        self.data_faults = []

        # One fixed offset per sensor per channel.
        self.offsets = {}
        for sid in C.SENSOR_IDS:
            self.offsets[sid] = {}
            for ch in C.CHANNELS:
                self.offsets[sid][ch] = self.rng.uniform(-C.OFFSET_MAX[ch], C.OFFSET_MAX[ch])

        # Everything that has a start and an end is decided now, before any reading exists.
        self.failures = self._schedule_failures()
        self.outages = self._schedule_windows("outage", C.OUTAGE_MEAN_GAP_H, C.OUTAGE_MINUTES)
        self.stuck = self._schedule_windows("stuck", C.STUCK_MEAN_GAP_H, C.STUCK_MINUTES)

    # ------------------------------------------------------------ helpers
    def ts(self, m):
        """Minute number -> timestamp text, e.g. 2026-09-01T00:05:00Z."""
        return (self.start + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def ambient(self, m):
        """Air temperature at minute m: a daily wave, hottest at 15:00."""
        t = self.start + timedelta(minutes=m)
        hour = t.hour + t.minute / 60
        angle = 2 * math.pi * (hour - C.AMBIENT_HOTTEST_HOUR) / 24
        return C.AMBIENT_MEAN_C + C.AMBIENT_SWING_C * math.cos(angle)

    def _log_fault(self, fault_type, sensor_id, channel, start_m, end_m, detail=""):
        self.data_faults.append({"fault_type": fault_type, "sensor_id": sensor_id,
                                 "channel": channel, "start_ts": self.ts(start_m),
                                 "end_ts": self.ts(end_m), "detail": detail})

    # ------------------------------------------------------------ schedules
    def _schedule_failures(self):
        failures = []
        for ftype in C.FAILURE_DURATION_H:
            shortest_h, longest_h = C.FAILURE_DURATION_H[ftype]
            m = int(self.rng.expovariate(1 / (C.FAILURE_MEAN_GAP_H * 60)))
            while True:
                duration = self.rng.randint(shortest_h * 60, longest_h * 60)
                repair = self.rng.randint(C.REPAIR_MINUTES[0], C.REPAIR_MINUTES[1])
                if m + duration + repair >= self.total_min:
                    break
                # Slip happens at the drive pulley and slows the whole belt,
                # so it belongs to no single sensor.
                sensor_id = "ALL" if ftype == "belt_slip" else self.rng.choice(C.SENSOR_IDS)
                new = {"type": ftype, "sensor_id": sensor_id, "onset_min": m,
                       "failure_min": m + duration, "repaired_min": m + duration + repair,
                       "direction": self.rng.choice([-1, 1])}
                # Keep it only if this sensor has no other episode at the same time.
                clash = False
                for old in failures:
                    if (old["sensor_id"] == sensor_id and new["onset_min"] < old["repaired_min"]
                            and old["onset_min"] < new["repaired_min"]):
                        clash = True
                if not clash:
                    failures.append(new)
                gap = int(self.rng.expovariate(1 / (C.FAILURE_MEAN_GAP_H * 60)))
                m = m + duration + repair + gap

        failures.sort(key=lambda f: f["onset_min"])
        for number, f in enumerate(failures, start=1):
            f["failure_id"] = f"F{number:03d}"
            f["onset_ts"] = self.ts(f["onset_min"])
            f["failure_ts"] = self.ts(f["failure_min"])
            f["repaired_ts"] = self.ts(f["repaired_min"])
        return failures

    def _schedule_windows(self, kind, mean_gap_h, minutes_range):
        """Outage and stuck periods. Returns {sensor_id: [(start_m, end_m, channel), ...]}."""
        windows = {sid: [] for sid in C.SENSOR_IDS}
        if not self.messy:
            return windows
        for sid in C.SENSOR_IDS:
            m = int(self.rng.expovariate(1 / (mean_gap_h * 60)))
            while m < self.total_min:
                length = self.rng.randint(minutes_range[0], minutes_range[1])
                end_m = min(m + length, self.total_min - 1)
                channel = "all" if kind == "outage" else self.rng.choice(C.CHANNELS)
                windows[sid].append((m, end_m, channel))
                self._log_fault(kind, sid, channel, m, end_m)
                m = end_m + int(self.rng.expovariate(1 / (mean_gap_h * 60)))
        return windows

    @staticmethod
    def _window_at(windows, m):
        for w in windows:
            if w[0] <= m <= w[1]:
                return w
        return None

    # ------------------------------------------------------------ signal model
    def _healthy(self, sid, ambient):
        off = self.offsets[sid]
        g = self.rng.gauss
        return {
            "temperature_c": ambient + C.BEARING_RISE_C + off["temperature_c"]
                             + g(0, C.NOISE_SD["temperature_c"]),
            "vibration_mm_s": max(0.0, C.VIBRATION_BASE_MM_S + off["vibration_mm_s"]
                                  + g(0, C.NOISE_SD["vibration_mm_s"])),
            "belt_speed_mps": C.BELT_SPEED_MPS + g(0, C.NOISE_SD["belt_speed_mps"]),
            "drift_mm": off["drift_mm"] + g(0, C.NOISE_SD["drift_mm"]),
        }

    @staticmethod
    def progress(f, m):
        """0.0 at onset, 1.0 at failure, stays 1.0 until repaired."""
        p = (m - f["onset_min"]) / (f["failure_min"] - f["onset_min"])
        return min(1.0, p)

    def _apply_failure(self, values, f, m):
        p = self.progress(f, m)
        if f["type"] == "seized_roller":
            values["vibration_mm_s"] += C.ROLLER_VIBRATION_ADD * p ** 1.5
            values["temperature_c"] += C.ROLLER_TEMPERATURE_ADD * p ** 3
        elif f["type"] == "belt_drift":
            values["drift_mm"] += f["direction"] * C.DRIFT_ADD_MM * p ** 2
        elif f["type"] == "belt_slip":
            values["belt_speed_mps"] *= 1 - C.SLIP_SPEED_LOSS * p ** 2

    # ------------------------------------------------------------ main loop
    def ticks(self):
        """Yield (arrival_ts, [messages]) once per minute.

        A message that is late is held back and comes out in a later minute,
        so its own "ts" is older than the arrival_ts it comes out with.
        """
        rng = self.rng
        pending = {}        # arrival minute -> messages that will arrive then
        frozen = {}         # (sensor, stuck window start) -> the value it is stuck at

        for m in range(self.total_min):
            ambient = self.ambient(m)
            active = [f for f in self.failures if f["onset_min"] <= m < f["repaired_min"]]

            for sid in C.SENSOR_IDS:
                # 1. The true physical values.
                values = self._healthy(sid, ambient)
                for f in active:
                    if f["sensor_id"] == sid or f["sensor_id"] == "ALL":
                        self._apply_failure(values, f, m)
                for ch in C.CHANNELS:
                    values[ch] = round(values[ch], C.DECIMALS[ch])

                delay = 0
                if self.messy:
                    # 2. Outage: the sensor is silent, no message at all.
                    if self._window_at(self.outages[sid], m):
                        continue
                    # 3. Dropped: this single message is never sent.
                    if rng.random() < C.P_DROPPED:
                        self._log_fault("dropped", sid, "all", m, m)
                        continue
                    # 4. Stuck: one channel repeats the value it had when it froze.
                    w = self._window_at(self.stuck[sid], m)
                    if w:
                        key = (sid, w[0])
                        if key not in frozen:
                            frozen[key] = values[w[2]]
                        values[w[2]] = frozen[key]
                    # 5. Spike: one value replaced by a wild number.
                    if rng.random() < C.P_SPIKE:
                        ch = rng.choice(C.CHANNELS)
                        if rng.random() < 0.5:
                            values[ch] = rng.choice(C.IMPOSSIBLE_SPIKES[ch])
                            kind = "impossible"
                        else:
                            low, high = C.PLAUSIBLE_SPIKE_ADD[ch]
                            values[ch] = round(values[ch] + rng.uniform(low, high), C.DECIMALS[ch])
                            kind = "plausible"
                        self._log_fault("spike", sid, ch, m, m, f"{kind} value={values[ch]}")
                    # 6. Null field: the message arrives but one value is empty.
                    if rng.random() < C.P_NULL_FIELD:
                        ch = rng.choice(C.CHANNELS)
                        values[ch] = None
                        self._log_fault("null_field", sid, ch, m, m)
                    # 7. Late: the message is sent, but arrives some minutes later.
                    if rng.random() < C.P_LATE:
                        delay = rng.randint(C.LATE_MINUTES[0], C.LATE_MINUTES[1])
                        self._log_fault("late", sid, "all", m, m, f"delay_min={delay}")

                message = {"sensor_id": sid, "ts": self.ts(m)}
                message.update(values)
                pending.setdefault(m + delay, []).append(message)

            yield self.ts(m), pending.pop(m, [])

        # Messages that were still on their way when the run ended.
        for m in sorted(pending):
            yield self.ts(m), pending[m]
