"""The loop logic: many detections over many laps become one record per damaged spot.

The belt is a closed loop, so a fixed camera sees every damaged spot again on
every lap. Without this file each lap would report the same damage as new.
"""
from collections import Counter

REPAIR = "patch work"            # an old repair: recorded, but never an alarm


def loop_distance(a, b, loop_m):
    """Shortest distance between two belt positions, going either way round the loop."""
    d = abs(a - b) % loop_m
    return min(d, loop_m - d)


def severity_of(kind, area_cm2):
    """An assumption, stated in the README: bigger is worse, and holes and tears are worse."""
    if kind == REPAIR:
        return "repair"
    step = 0 if area_cm2 < 50 else 1 if area_cm2 < 300 else 2
    if kind in ("Tear", "Hole"):
        step += 1
    return ["minor", "moderate", "severe", "severe"][step]


class DefectTracker:
    def __init__(self, loop_m, use_position=True, base_tolerance_m=1.0, drift_per_m=0.0,
                 lateral_tolerance_mm=250.0):
        self.loop_m = loop_m
        self.use_position = use_position            # False = the naive way: every detection is new
        self.base_tolerance_m = base_tolerance_m    # how far apart two sightings of one spot may be
        self.drift_per_m = drift_per_m              # extra tolerance per metre since the reference mark
        self.lateral_tolerance_mm = lateral_tolerance_mm
        self.records = []

    def add(self, lap, ts, position_m, lateral_mm, kind, area_cm2, confidence,
            since_mark_m=0.0, image=""):
        """Add one detection. Returns the record it now belongs to."""
        sighting = {"lap": lap, "ts": ts, "kind": kind, "area_cm2": area_cm2,
                    "confidence": confidence, "image": image}
        best = None
        if self.use_position:
            # The position estimate gets worse the further the belt has moved
            # since the reference mark, so the tolerance grows with that distance.
            tolerance = self.base_tolerance_m + self.drift_per_m * since_mark_m
            best_score = None
            for record in self.records:
                if record["sightings"][-1]["lap"] == lap:
                    continue                        # already seen this lap: it is a different spot
                distance = loop_distance(position_m, record["position_m"], self.loop_m)
                sideways = abs(lateral_mm - record["lateral_mm"])
                if distance > tolerance or sideways > self.lateral_tolerance_mm:
                    continue
                # Several records can be within reach. Take the closest one, counting
                # distance along the belt, distance across it, and a different type.
                score = distance / tolerance + sideways / self.lateral_tolerance_mm
                if record["sightings"][-1]["kind"] != kind:
                    score += 0.5
                if best is None or score < best_score:
                    best, best_score = record, score
        if best is None:
            best = {"id": f"D{len(self.records) + 1:03d}", "position_m": position_m % self.loop_m,
                    "lateral_mm": lateral_mm, "sightings": []}
            self.records.append(best)
        best["sightings"].append(sighting)
        return best

    def summary(self, current_lap):
        """One dictionary per damaged spot, ready for the backend and the dashboard."""
        out = []
        for record in self.records:
            seen = record["sightings"]
            kinds = Counter(s["kind"] for s in seen[-3:])            # the last 3 sightings vote
            kind = kinds.most_common(1)[0][0]
            first, last = seen[0], seen[-1]
            laps_seen = len({s["lap"] for s in seen})
            # Growth compares like with like: only sightings of the same type count.
            # Otherwise a spot seen once as a small tear and later as a large area of
            # impact damage would look as if it had grown.
            same_type = [s for s in seen if s["kind"] == kind]
            growth = None
            if len({s["lap"] for s in same_type}) >= 3 and same_type[0]["area_cm2"] > 0:
                growth = round(100.0 * (same_type[-1]["area_cm2"] - same_type[0]["area_cm2"])
                               / same_type[0]["area_cm2"], 1)
            if last["lap"] >= current_lap - 1:
                status = "new" if first["lap"] == current_lap and current_lap > 1 else "active"
            else:
                status = "not_seen"                 # missed for 2 laps or more: repaired, covered or a false alarm
            if kind == REPAIR and any(s["kind"] != REPAIR for s in seen[:-3]):
                status = "repaired"                 # it used to be damage, now it is a patch
            out.append({"id": record["id"], "position_m": round(record["position_m"], 1),
                        "lateral_mm": round(record["lateral_mm"]), "type": kind,
                        "severity": severity_of(kind, last["area_cm2"]),
                        "area_cm2": round(last["area_cm2"], 1), "growth_pct": growth,
                        "first_seen_ts": first["ts"], "last_seen_ts": last["ts"],
                        "laps_seen": laps_seen, "sightings": len(seen),
                        "confidence": round(last["confidence"], 2), "status": status,
                        "image": last["image"]})
        return out
