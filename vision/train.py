"""Train the damage model and score it on the test photos.

    python -m vision.train /kaggle/working/belt_damage /kaggle/working/runs

Needs a GPU. On a Kaggle T4 the 60 rounds took about 20 minutes.
"""
import os
import sys

os.environ["WANDB_MODE"] = "disabled"


def main(dataset_dir, runs_dir):
    from ultralytics import YOLO
    model = YOLO("yolo26s-seg.pt")
    model.train(data=f"{dataset_dir}/belt.yaml", epochs=60, imgsz=640, batch=16, patience=15,
                seed=0, project=runs_dir, name="belt_seg", exist_ok=True)
    best = YOLO(f"{runs_dir}/belt_seg/weights/best.pt")
    best.val(data=f"{dataset_dir}/belt.yaml", split="test", project=runs_dir,
             name="belt_seg_test", exist_ok=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
