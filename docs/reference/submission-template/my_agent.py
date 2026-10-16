"""my_agent.py -- the one Agent subclass. Climb to 15 m, fly north for 10 s, hover.

The harness owns the loop; override only the callbacks you need. Every
callback returns a Command or None (None = keep doing what you were doing).
flight(left_x, left_y, right_x, right_y), each in [-1, 1]:
    left_y = climb   left_x = yaw   right_y = forward   right_x = strafe right
"""
from competition import Agent, Command, flight
from detection import Detector

TARGET_ALT_M = 15.0
FORWARD_S = 10.0


class MyAgent(Agent):
    def __init__(self):
        self.detector = Detector()      # heavy setup goes here, not in on_start
        self.last_detections = []       # the website draws these boxes
        self.t_level = None

    def on_start(self, arena):
        return Command(flight=flight(0, 1.0, 0, 0))

    def on_frame(self, image, state):   # ~5 Hz
        if image is not None:
            self.last_detections = self.detector.detect(image)
        return None

    def on_tick(self, state):           # ~20 Hz; re-issue flight() every tick
        if state.alt_agl < TARGET_ALT_M - 1.0 and self.t_level is None:
            return Command(flight=flight(0, 1.0, 0, 0))             # climb
        if self.t_level is None:
            self.t_level = state.time_elapsed
        if state.time_elapsed - self.t_level < FORWARD_S:
            return Command(flight=flight(0, 0, 0, 0.5))             # forward
        return Command(flight=flight(0, 0, 0, 0))                   # hover
