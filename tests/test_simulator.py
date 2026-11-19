"""Checks that the simulator output agrees with its own ground-truth logs.

Run with:  python -m tests.test_simulator      (or: pytest tests/)
"""
from simulator import config as C
from simulator.generate import BeltSimulator


def collect(sim):
    """Run the simulator. Return a list of (arrival_ts, message)."""
    rows = []
    for arrival_ts, messages in sim.ticks():
        for msg in messages:
            rows.append((arrival_ts, msg))
    return rows


def test_same_seed_gives_same_data():
    a = collect(BeltSimulator(days=2, seed=1))
    b = collect(BeltSimulator(days=2, seed=1))
    c = collect(BeltSimulator(days=2, seed=2))
    assert a == b
    assert a != c


def test_clean_run_has_every_reading():
    sim = BeltSimulator(days=3, seed=5, messy=False)
    rows = collect(sim)
    assert len(rows) == 3 * 24 * 60 * len(C.SENSOR_IDS)
    assert sim.data_faults == []
    for arrival_ts, msg in rows:
        assert arrival_ts == msg["ts"]
        for ch in C.CHANNELS:
            low, high = C.VALID_RANGE[ch]
            assert low <= msg[ch] <= high


def test_every_failure_reaches_its_failure_level():
    sim = BeltSimulator(days=30, seed=3, messy=False)
    by_key = {(msg["sensor_id"], msg["ts"]): msg for _, msg in collect(sim)}
    assert len(sim.failures) > 20
    for f in sim.failures:
        sensor = "S10" if f["sensor_id"] == "ALL" else f["sensor_id"]
        at_onset = by_key[(sensor, f["onset_ts"])]
        at_failure = by_key[(sensor, f["failure_ts"])]
        if f["type"] == "seized_roller":
            assert at_onset["temperature_c"] < 70
            assert at_failure["temperature_c"] >= 85
            assert at_failure["vibration_mm_s"] >= 7
        elif f["type"] == "belt_drift":
            assert abs(at_onset["drift_mm"]) < 40
            assert abs(at_failure["drift_mm"]) >= 120
        elif f["type"] == "belt_slip":
            assert at_onset["belt_speed_mps"] > 3.9
            assert at_failure["belt_speed_mps"] <= 0.82 * C.BELT_SPEED_MPS


def test_slip_is_seen_by_every_sensor():
    sim = BeltSimulator(days=30, seed=3, messy=False)
    by_key = {(msg["sensor_id"], msg["ts"]): msg for _, msg in collect(sim)}
    slips = [f for f in sim.failures if f["type"] == "belt_slip"]
    assert slips
    for f in slips:
        for sid in C.SENSOR_IDS:
            assert by_key[(sid, f["failure_ts"])]["belt_speed_mps"] <= 0.82 * C.BELT_SPEED_MPS


def test_messy_data_matches_the_fault_log():
    sim = BeltSimulator(days=20, seed=11)
    rows = collect(sim)
    faults = sim.data_faults
    by_key = {(msg["sensor_id"], msg["ts"]): (arrival, msg) for arrival, msg in rows}

    def logged(kind):
        return [x for x in faults if x["fault_type"] == kind]

    for kind in ["outage", "stuck", "spike", "null_field", "dropped", "late"]:
        assert logged(kind), f"no {kind} was injected"

    # Messages come out in arrival order, and never arrive before they were measured.
    arrivals = [arrival for arrival, _ in rows]
    assert arrivals == sorted(arrivals)
    for arrival, msg in rows:
        assert arrival >= msg["ts"]

    # A message is late exactly when the log says so.
    late_keys = {(x["sensor_id"], x["start_ts"]) for x in logged("late")}
    dropped_keys = {(x["sensor_id"], x["start_ts"]) for x in logged("dropped")}
    for key, (arrival, msg) in by_key.items():
        assert (arrival > msg["ts"]) == (key in late_keys)

    # A dropped message does not exist.
    for key in dropped_keys:
        assert key not in by_key

    # No message has a timestamp inside an outage of its sensor.
    for x in logged("outage"):
        for (sid, ts) in by_key:
            assert not (sid == x["sensor_id"] and x["start_ts"] <= ts <= x["end_ts"])

    # A null value and an out-of-range value appear only where the log says so.
    null_keys = {(x["sensor_id"], x["start_ts"], x["channel"]) for x in logged("null_field")}
    spike_keys = {(x["sensor_id"], x["start_ts"], x["channel"]) for x in logged("spike")}
    for (sid, ts), (_, msg) in by_key.items():
        for ch in C.CHANNELS:
            if msg[ch] is None:
                assert (sid, ts, ch) in null_keys
            else:
                low, high = C.VALID_RANGE[ch]
                if not low <= msg[ch] <= high:
                    assert (sid, ts, ch) in spike_keys

    # Inside a stuck period the channel holds one single value
    # (a spike or a null on the same reading may overwrite it, so skip those).
    for x in logged("stuck"):
        seen = set()
        for (sid, ts), (_, msg) in by_key.items():
            if sid == x["sensor_id"] and x["start_ts"] <= ts <= x["end_ts"]:
                ch = x["channel"]
                if (sid, ts, ch) not in null_keys and (sid, ts, ch) not in spike_keys:
                    seen.add(msg[ch])
        assert len(seen) <= 1

    # Row count = every possible reading minus outage minutes minus dropped messages.
    outage_keys = set()
    for x in logged("outage"):
        m = 0
        while sim.ts(m) < x["start_ts"]:
            m += 1
        while m < sim.total_min and sim.ts(m) <= x["end_ts"]:
            outage_keys.add((x["sensor_id"], m))
            m += 1
    possible = sim.total_min * len(C.SENSOR_IDS)
    assert len(rows) == possible - len(outage_keys) - len(dropped_keys)


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("passed", name)
