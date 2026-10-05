"""Detection results from a competitor's agent -- the organizer's side.

The organizer never runs a model. The competitor's image (see
examples/competition-submission/) runs its own detector inside on_frame and
sets agent.last_detections; competition/harness.py forwards them as a
{"type": "detections", "boxes": [...]} message on /agent/control. This module
is everything the server does with them after that: validate, keep for the
page, append to a per-run log.

One box on the wire (the whole contract):
    {"class_name": str, "confidence": 0..1, "bbox": [x1, y1, x2, y2]}
bbox is in pixels of the frame the agent was handed.
"""
import json
import math
import os
import time

MAX_BOXES = 50
_DRONE_KEYS = ("lat", "lon", "alt_m", "heading_deg")


def _box(b):
    try:
        name = b["class_name"]
        conf = float(b["confidence"])
        bbox = [float(v) for v in b["bbox"]]
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(name, str) or len(bbox) != 4:
        return None
    if not all(math.isfinite(v) for v in (conf, *bbox)) or not 0.0 <= conf <= 1.0:
        return None
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        return None
    return {"class_name": name[:64], "confidence": conf, "bbox": bbox}


def sanitize_boxes(boxes):
    """Well-formed boxes only. Anything malformed is dropped, never raised --
    a buggy agent must not take down the server or the page's canvas."""
    if not isinstance(boxes, list):
        return []
    out = []
    for b in boxes:
        if len(out) >= MAX_BOXES:
            break
        box = _box(b)
        if box is not None:
            out.append(box)
    return out


class DetectionLog:
    """Append-only JSONL, one line per message that carried at least one box,
    stamped with where the drone was. Opened per write: 5 Hz at most, and no
    file handle to leak when a run ends badly."""

    def __init__(self, path):
        self.path = path

    def write(self, boxes, telemetry):
        if not boxes:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        row = {"t": time.time(),
               "drone": {k: telemetry.get(k) for k in _DRONE_KEYS},
               "boxes": boxes}
        with open(self.path, "a") as f:
            f.write(json.dumps(row) + "\n")
