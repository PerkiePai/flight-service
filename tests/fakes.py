"""Stand-ins for everything outside this repo. No sim, no docker, no network."""
import asyncio
import json

BOX = {"class_name": "Truck", "confidence": 0.9, "bbox": [0, 0, 1, 1]}


class FakeWS:
    """websockets connect() stand-in: replays `frames` to recv(), records
    send(). After the last frame recv() blocks, or raises `end`."""

    def __init__(self, frames, end=None):
        self.frames, self.end, self.sent = list(frames), end, []

    def __call__(self, url, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        await asyncio.sleep(0)
        if self.frames:
            return json.dumps(self.frames.pop(0))
        if self.end:
            raise self.end
        await asyncio.Event().wait()


def frame(state, log=(), lat=14.0, lon=100.0, alt=20.0, boxes=()):
    return {"connected": True, "lat": lat, "lon": lon, "alt_m": alt, "heading_deg": 90.0,
            "roll_deg": 0.0, "pitch_deg": 0.0, "gs": 3.0, "vz": 0.0, "mode": "OFFBOARD",
            "armed": True,
            "agent": {"state": state, "log": list(log), "detections": list(boxes)}}
