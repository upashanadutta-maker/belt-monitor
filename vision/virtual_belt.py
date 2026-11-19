"""A pretend belt built from the test photos, used to test the loop logic.

    python -m vision.virtual_belt /kaggle/working/belt_damage /kaggle/working/runs/belt_seg/weights/best.pt

Every test photo gets a fixed place on the 6 km loop. A pretend camera then
watches the belt go round several times. Because we placed the photos
ourselves, we know the true number of damaged spots, and can compare it with
the number of records the system creates.

No public dataset shows the same real damage over many laps, so the laps are
simulated: each lap the photo is made a little brighter or darker, and a few
frames are skipped as if material covered the belt.
"""
import glob
import json
import os
import random
import sys
import urllib.request
from datetime import datetime, timedelta

from simulator import config as C
from vision.tracker import DefectTracker

FRAME_LENGTH_M = 2.0         # assumption: one photo shows 2 m of belt, across the full width
SLOT_M = 3                   # photos are placed in 3 m slots, so two photos never overlap
LAPS = 5
COVERED_CHANCE = 0.05        # chance that a frame is hidden by material on a given lap
GROWING_FRAMES = 5           # this many photos are enlarged a little every lap (simulated growth)
GROWTH_PER_LAP = 0.06
START = datetime(2026, 9, 1)
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vision")


def build_belt(dataset_dir, seed=0):
    """Give every test photo a fixed place on the loop."""
    images = sorted(glob.glob(os.path.join(dataset_dir, "test", "images", "*")))
    rng = random.Random(seed)
    slots = rng.sample(range(C.BELT_LOOP_M // SLOT_M), len(images))
    frames = []
    for image, slot in zip(images, slots):
        label = os.path.join(dataset_dir, "test", "labels",
                             os.path.splitext(os.path.basename(image))[0] + ".txt")
        true_spots = sum(1 for line in open(label) if line.strip()) if os.path.exists(label) else 0
        frames.append({"image": image, "position_m": slot * SLOT_M + SLOT_M / 2,
                       "true_spots": true_spots, "growing": False})
    frames.sort(key=lambda f: f["position_m"])
    with_damage = [f for f in frames if f["true_spots"] > 0]
    for f in rng.sample(with_damage, min(GROWING_FRAMES, len(with_damage))):
        f["growing"] = True
    return frames


def lap_view(frame, lap, rng):
    """The photo as the camera sees it on this lap."""
    import cv2
    image = cv2.imread(frame["image"])
    image = cv2.convertScaleAbs(image, alpha=rng.uniform(0.75, 1.25))    # lighting changes
    if frame["growing"]:
        # Enlarge around the centre: the damage looks bigger each lap.
        zoom = 1 + GROWTH_PER_LAP * (lap - 1)
        h, w = image.shape[:2]
        big = cv2.resize(image, None, fx=zoom, fy=zoom)
        top, left = (big.shape[0] - h) // 2, (big.shape[1] - w) // 2
        image = big[top:top + h, left:left + w]
    return image


def watch(model, frames, detect, laps=LAPS, seed=0, save_last_lap=True):
    """Run the camera for some laps. Returns one observation per frame per lap."""
    rng = random.Random(seed)
    os.makedirs(os.path.join(OUT_DIR, "frames"), exist_ok=True)
    observations = []
    for lap in range(1, laps + 1):
        for number, frame in enumerate(frames):
            if rng.random() < COVERED_CHANCE:
                continue                                  # hidden under material this lap
            detections, result = detect(model, lap_view(frame, lap, rng))
            image_path = ""
            if save_last_lap and lap == laps and detections:
                image_path = os.path.join(OUT_DIR, "frames", f"frame_{number:03d}.jpg")
                result.save(filename=image_path)          # the photo with the outlines drawn on it
            observations.append({"lap": lap, "position_m": frame["position_m"],
                                 "detections": detections, "image": image_path})
    return observations


def track(observations, speed_error=0.0, seed=0, **tracker_settings):
    """Feed the observations to the loop logic.

    speed_error: each lap the belt position is estimated from speed x time, and the
    speed is off by about this share (0.001 = 0.1%). The error is zero at the
    reference mark (position 0, for example the belt splice) and grows from there.
    """
    rng = random.Random(seed)
    tracker = DefectTracker(C.BELT_LOOP_M, **tracker_settings)
    error_of_lap = {}
    for obs in observations:
        lap = obs["lap"]
        if lap not in error_of_lap:
            error_of_lap[lap] = rng.gauss(0, speed_error)
        estimate = obs["position_m"] * (1 + error_of_lap[lap])
        seconds = ((lap - 1) * C.BELT_LOOP_M + obs["position_m"]) / C.BELT_SPEED_MPS
        ts = (START + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for d in obs["detections"]:
            tracker.add(lap=lap, ts=ts,
                        position_m=estimate + (d["cy"] - 0.5) * FRAME_LENGTH_M,
                        lateral_mm=d["cx"] * C.BELT_WIDTH_MM, kind=d["kind"],
                        area_cm2=d["area_fraction"] * FRAME_LENGTH_M * 100 * C.BELT_WIDTH_MM / 10,
                        confidence=d["confidence"], since_mark_m=obs["position_m"],
                        image=obs["image"])
    return tracker


def report(frames, observations, laps=LAPS):
    true_spots = sum(f["true_spots"] for f in frames)
    per_lap = [sum(len(o["detections"]) for o in observations if o["lap"] == lap)
               for lap in range(1, laps + 1)]
    print(f"photos on the belt        : {len(frames)}")
    print(f"true damaged spots        : {true_spots}")
    print(f"detections on each lap    : {per_lap}")
    print(f"\nrecords created after {laps} laps (the true number is {true_spots})")
    print(f"{'position error per lap':24}{'rule off':>10}{'fixed 1 m':>11}{'growing':>9}")
    for error in [0.0, 0.001, 0.003]:
        off = track(observations, error, use_position=False)
        fixed = track(observations, error, base_tolerance_m=1.0)
        growing = track(observations, error, base_tolerance_m=1.0, drift_per_m=6 * error)
        print(f"{error * 100:>21.1f} %{len(off.records):>10}{len(fixed.records):>11}{len(growing.records):>9}")


def main(dataset_dir, weights, url="http://127.0.0.1:8000/defects"):
    from vision.detect import detect, load_model
    model = load_model(weights)
    frames = build_belt(dataset_dir)
    observations = watch(model, frames, detect)
    report(frames, observations)

    # The records shown on the dashboard: 0.1% position error, growing tolerance.
    tracker = track(observations, 0.001, base_tolerance_m=1.0, drift_per_m=0.006)
    records = tracker.summary(current_lap=LAPS)
    with open(os.path.join(OUT_DIR, "defects.json"), "w") as f:
        json.dump(records, f, indent=1)
    print(f"\n{len(records)} records saved to {os.path.join(OUT_DIR, 'defects.json')}")
    grown = sorted([r for r in records if r["growth_pct"] is not None],
                   key=lambda r: -r["growth_pct"])[:GROWING_FRAMES]
    for r in grown:
        print(f"  {r['id']} {r['type']:14} at {r['position_m']:7.1f} m  grew {r['growth_pct']:+.0f}% "
              f"over {r['laps_seen']} laps")
    try:
        request = urllib.request.Request(url, data=json.dumps(records).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            print("sent to the backend:", response.read().decode())
    except OSError as error:
        print("backend not reachable, records were only saved to the file:", error)


if __name__ == "__main__":
    main(*sys.argv[1:])
