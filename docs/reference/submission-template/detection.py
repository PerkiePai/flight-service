"""detection.py -- the model, nothing about flying. Replace Detector with your own.

This stub finds nothing, so the template runs without torch or weights.
Each Detection needs exactly these three fields (competition/harness.py reads them).
"""
from dataclasses import dataclass


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple            # (x1, y1, x2, y2) pixels in the source image


class Detector:
    def __init__(self):
        # Load weights here, NOT in on_start (on_start has a 200 ms budget).
        pass

    def detect(self, image):
        """image: numpy array (H, W, 3). Return a list of Detection."""
        return []
