"""Download the damage photos from Roboflow and keep the five belt-damage classes.

    export ROBOFLOW_API_KEY=...      (a free Roboflow account gives you one)
    python -m vision.prepare_dataset /kaggle/working/belt_damage

Source: https://universe.roboflow.com/sample-wy2mp/conveyor-belt-damage  (version 1, CC BY 4.0)
The download has 8 classes. Roller, Other Objects and Human are not belt wear,
so their outlines are removed and the other five classes are renumbered 0 to 4.
"""
import glob
import os
import sys

OLD_NAMES = ['Hole', 'Human', 'Other Objects', 'Puncture', 'Roller', 'Tear', 'impact damage', 'patch work']
KEEP = ['Tear', 'patch work', 'Puncture', 'Hole', 'impact damage']


def main(root):
    from roboflow import Roboflow
    rf = Roboflow(api_key=os.environ["ROBOFLOW_API_KEY"])
    project = rf.workspace("sample-wy2mp").project("conveyor-belt-damage")
    project.version(1).download("yolov11", location=root)

    if os.path.exists(f"{root}/belt.yaml"):
        print("already filtered, nothing changed")
        return
    kept = dropped = 0
    for path in glob.glob(f"{root}/*/labels/*.txt"):
        new_lines = []
        for line in open(path):
            parts = line.split()
            if not parts:
                continue
            name = OLD_NAMES[int(parts[0])]
            if name in KEEP:
                parts[0] = str(KEEP.index(name))
                new_lines.append(" ".join(parts) + "\n")
                kept += 1
            else:
                dropped += 1
        with open(path, "w") as f:
            f.writelines(new_lines)
    with open(f"{root}/belt.yaml", "w") as f:
        f.write(f"path: {root}\ntrain: train/images\nval: valid/images\ntest: test/images\nnames:\n")
        for number, name in enumerate(KEEP):
            f.write(f"  {number}: {name}\n")
    print("kept", kept, "outlines, dropped", dropped)


if __name__ == "__main__":
    main(sys.argv[1])
