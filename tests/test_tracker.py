"""Checks of the loop logic with made-up detections (no camera, no model).

Run with:  python -m tests.test_tracker
"""
import random

from vision.tracker import DefectTracker, loop_distance, severity_of

LOOP = 6000.0


def make_spots(rng, n):
    """n damaged spots at random places on the belt."""
    return [{"position": rng.uniform(0, LOOP), "lateral": rng.uniform(200, 1400),
             "kind": rng.choice(["Tear", "patch work", "Puncture", "impact damage"]),
             "area": rng.uniform(20, 400)} for _ in range(n)]


def run(tracker, spots, laps, rng, position_error=0.0, miss=0.0):
    for lap in range(1, laps + 1):
        stretch = rng.gauss(0, position_error)          # this lap's speed error
        for s in sorted(spots, key=lambda s: s["position"]):
            if rng.random() < miss:
                continue
            estimate = s["position"] * (1 + stretch)
            tracker.add(lap, f"lap{lap}", estimate, s["lateral"] + rng.gauss(0, 10), s["kind"],
                        s["area"], 0.9, since_mark_m=s["position"])
    return tracker


def test_loop_distance_wraps_around():
    assert loop_distance(5999, 1, LOOP) == 2
    assert loop_distance(100, 400, LOOP) == 300


def test_without_position_rule_every_lap_counts_again():
    rng = random.Random(1)
    spots = make_spots(rng, 50)
    tracker = run(DefectTracker(LOOP, use_position=False), spots, laps=4, rng=rng)
    assert len(tracker.records) == 200                  # 50 spots x 4 laps


def test_with_position_rule_one_record_per_spot():
    rng = random.Random(1)
    spots = make_spots(rng, 50)
    tracker = run(DefectTracker(LOOP), spots, laps=4, rng=rng)
    assert len(tracker.records) == 50
    assert all(r["laps_seen"] == 4 for r in tracker.summary(current_lap=4))


def test_a_spot_near_the_end_of_the_loop_matches_across_zero():
    tracker = DefectTracker(LOOP)
    tracker.add(1, "a", 5999.8, 800, "Tear", 100, 0.9)
    tracker.add(2, "b", 0.3, 800, "Tear", 100, 0.9)       # same spot, estimate wrapped past 0
    assert len(tracker.records) == 1


def test_two_close_spots_in_one_lap_stay_two():
    tracker = DefectTracker(LOOP)
    for lap in (1, 2, 3):
        tracker.add(lap, "t", 100.0, 800, "Tear", 100, 0.9)
        tracker.add(lap, "t", 100.4, 820, "Tear", 100, 0.9)
    assert len(tracker.records) == 2


def test_growth_status_and_repair():
    tracker = DefectTracker(LOOP)
    for lap, area in enumerate([100, 120, 150], start=1):
        tracker.add(lap, f"lap{lap}", 500.0, 800, "Tear", area, 0.9)
    tracker.add(1, "lap1", 900.0, 400, "Puncture", 30, 0.9)       # seen once, then never again
    growing, gone = tracker.summary(current_lap=3)
    assert growing["growth_pct"] == 50.0 and growing["status"] == "active"
    assert gone["status"] == "not_seen"
    # A tear that later shows up as patch work has been repaired.
    tracker = DefectTracker(LOOP)
    for lap in (1, 2, 3):
        tracker.add(lap, "t", 700.0, 800, "Tear", 100, 0.9)
    for lap in (4, 5, 6):
        tracker.add(lap, "t", 700.0, 800, "patch work", 150, 0.9)
    assert tracker.summary(current_lap=6)[0]["status"] == "repaired"
    assert severity_of("patch work", 999) == "repair"


def test_position_error_breaks_a_fixed_tolerance_but_not_a_growing_one():
    rng = random.Random(3)
    spots = make_spots(rng, 100)
    # Each lap the position estimate is off by about 0.1% of the distance travelled.
    fixed = run(DefectTracker(LOOP, base_tolerance_m=1.0), spots, 5, random.Random(4), position_error=0.001)
    growing = run(DefectTracker(LOOP, base_tolerance_m=1.0, drift_per_m=0.006), spots, 5,
                  random.Random(4), position_error=0.001)
    assert len(fixed.records) > 200                     # many spots were counted again
    assert abs(len(growing.records) - 100) <= 5


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("passed", name)
