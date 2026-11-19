"""Run the trained damage model on one image."""


def load_model(path):
    from ultralytics import YOLO
    return YOLO(path)


def detect(model, image, confidence=0.25):
    """Return (detections, result). Each detection says what was found and where in the frame.

    cx, cy and area_fraction are fractions of the frame (0 to 1), so they do
    not depend on the size of the photo.
    """
    result = model(image, conf=confidence, verbose=False)[0]
    detections = []
    if result.masks is None:
        return detections, result
    for outline, box in zip(result.masks.xyn, result.boxes):
        if len(outline) < 3:
            continue
        xs, ys = outline[:, 0], outline[:, 1]
        # Area inside the outline (shoelace formula).
        area = 0.5 * abs(float((xs * ys[list(range(1, len(ys))) + [0]]).sum()
                               - (ys * xs[list(range(1, len(xs))) + [0]]).sum()))
        detections.append({"kind": result.names[int(box.cls[0])],
                           "confidence": float(box.conf[0]),
                           "cx": float(xs.mean()), "cy": float(ys.mean()),
                           "area_fraction": area})
    return detections, result
