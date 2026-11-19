"""Command line for the simulator.

History for training (writes three CSV files):
    python -m simulator.run batch --days 60 --seed 42 --out data/train

Live feed for the backend (one HTTP POST per simulated minute):
    python -m simulator.run live --url http://127.0.0.1:8000/readings --seed 7 --speedup 600
"""
import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request

from simulator import config as C
from simulator.generate import BeltSimulator

FAILURE_COLUMNS = ["failure_id", "type", "sensor_id", "onset_ts", "failure_ts", "repaired_ts"]
FAULT_COLUMNS = ["fault_type", "sensor_id", "channel", "start_ts", "end_ts", "detail"]


def write_csv(path, columns, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_batch(args):
    sim = BeltSimulator(args.days, args.seed, args.start, messy=not args.clean)
    os.makedirs(args.out, exist_ok=True)
    count = 0
    with open(os.path.join(args.out, "readings.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["arrival_ts", "sensor_id", "ts"] + C.CHANNELS)
        for arrival_ts, messages in sim.ticks():
            for msg in messages:
                # A null value is written as an empty cell.
                row = [arrival_ts, msg["sensor_id"], msg["ts"]]
                for ch in C.CHANNELS:
                    row.append("" if msg[ch] is None else msg[ch])
                writer.writerow(row)
                count += 1
    write_csv(os.path.join(args.out, "failures.csv"), FAILURE_COLUMNS, sim.failures)
    write_csv(os.path.join(args.out, "data_faults.csv"), FAULT_COLUMNS, sim.data_faults)

    expected = sim.total_min * len(C.SENSOR_IDS)
    print(f"readings written : {count} of {expected} possible")
    for ftype in C.FAILURE_DURATION_H:
        print(f"{ftype:17}: {sum(1 for x in sim.failures if x['type'] == ftype)} episodes")
    for kind in ["outage", "stuck", "spike", "null_field", "dropped", "late"]:
        print(f"{kind:17}: {sum(1 for x in sim.data_faults if x['fault_type'] == kind)}")


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


def run_live(args):
    sim = BeltSimulator(args.days, args.seed, args.start, messy=not args.clean)
    os.makedirs(args.out, exist_ok=True)
    # The failure schedule is known before the first reading, so write it now.
    write_csv(os.path.join(args.out, "failures.csv"), FAILURE_COLUMNS, sim.failures)
    pause = C.READING_INTERVAL_S / args.speedup      # real seconds per simulated minute
    sent = failed = 0
    try:
        for minute, (arrival_ts, messages) in enumerate(sim.ticks()):
            if args.stop_after is not None and minute >= args.stop_after * 24 * 60:
                print(f"stopped on purpose at {arrival_ts}")
                break
            if messages:
                try:
                    post_json(args.url, messages)
                    sent += len(messages)
                except (urllib.error.URLError, OSError) as error:
                    failed += len(messages)
                    print(f"{arrival_ts} POST failed: {error}")
            time.sleep(pause)
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        write_csv(os.path.join(args.out, "data_faults.csv"), FAULT_COLUMNS, sim.data_faults)
        print(f"messages sent: {sent}, not delivered: {failed}")


def main():
    parser = argparse.ArgumentParser(description="Conveyor belt sensor simulator")
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ["batch", "live"]:
        p = sub.add_parser(name)
        p.add_argument("--days", type=float, default=60)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--start", default="2026-09-01T00:00:00Z")
        p.add_argument("--clean", action="store_true", help="no messy data, failures only")
        p.add_argument("--out", default="data/train" if name == "batch" else "data/live")
        if name == "live":
            p.add_argument("--url", default="http://127.0.0.1:8000/readings")
            p.add_argument("--speedup", type=float, default=600,
                           help="600 means one simulated minute takes 0.1 real seconds")
            p.add_argument("--stop-after", type=float, default=None,
                           help="stop sending after this many simulated days (the run itself "
                                "is still planned for --days, so the data stays the same)")
    args = parser.parse_args()
    if args.mode == "batch":
        run_batch(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
