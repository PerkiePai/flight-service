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


class FakeConnect:
    """websockets connect() stand-in that hands out one item per call: a FakeWS
    (one connection) or an exception (that connect attempt fails). The last
    item is reused once the others are used up."""

    def __init__(self, *items):
        self.items, self.calls = list(items), 0

    def __call__(self, url, **kw):
        self.calls += 1
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item


def frame(state, log=(), lat=14.0, lon=100.0, alt=20.0, boxes=()):
    return {"connected": True, "lat": lat, "lon": lon, "alt_m": alt, "heading_deg": 90.0,
            "roll_deg": 0.0, "pitch_deg": 0.0, "gs": 3.0, "vz": 0.0, "mode": "OFFBOARD",
            "armed": True,
            "agent": {"state": state, "log": list(log), "detections": list(boxes)}}


# --- pipeline fakes (Task 9) ------------------------------------------------
import os
import time

from flight_service.flightsession import Outcome
from flight_service.jobs import JobFailed


class FakeDocker:
    def __init__(self, exists=False, size=5 * 1024 ** 3, manifest=4 * 1024 ** 3):
        self._exists, self._size, self._manifest, self.calls = exists, size, manifest, []

    async def exists(self, ref):
        self.calls.append(("exists", ref))
        return self._exists

    async def manifest_bytes(self, ref, timeout):
        return self._manifest

    async def size(self, ref):
        return self._size

    async def containers_of(self, tag):
        return ["submission-run-1"]

    async def rm_force(self, name):
        self.calls.append(("rm_force", name))

    async def rmi(self, ref):
        self.calls.append(("rmi", ref))
        return True

    loaded = ("truck:1",)
    load_hold = None            # an asyncio.Event to wait on inside docker load
    tag_fails = False

    async def load(self, path, timeout):
        self.calls.append(("load", str(path)))
        if self.load_hold is not None:
            await self.load_hold.wait()
        return list(self.loaded)

    async def tag(self, src, dst):
        self.calls.append(("tag", src, dst))
        if self.tag_fails:
            raise JobFailed("load_failed", "no such image")


class FakeSim:
    def __init__(self, busy=False, fail=None, stop_ok=True):
        self._busy, self.fail, self.stop_ok, self.calls = busy, fail, stop_ok, []

    async def _step(self, name):
        self.calls.append(name)
        if self.fail and self.fail[0] == name:
            raise JobFailed(*self.fail[1:])

    async def busy(self):
        self.calls.append("busy")
        return self._busy

    async def start_web(self):
        await self._step("start_web")

    async def start_sim(self):
        await self._step("start_sim")

    async def wait_px4_ready(self, since):
        await self._step("wait_px4_ready")

    async def stop(self):
        self.calls.append("stop")
        return self.stop_ok


class FakeSitl:
    def __init__(self, tag="submission-x-20261005-120000", fail=None, clip=None):
        self.tag, self.fail, self.clip = tag, fail, clip

    async def pull(self, ref, timeout):
        if self.fail:
            raise JobFailed("pull_failed", self.fail)
        return self.tag

    async def upload_bundle(self, path, name, timeout):
        assert os.path.exists(path)
        return f"submission-{name}-20261005-120000"

    async def detrec_status(self):
        if not self.clip:
            return {"on": False, "last": None}
        os.utime(self.clip / "meta.json")       # the recorder just closed this run's clip
        return {"on": False, "last": str(self.clip / "detections.mp4")}


def make_fly(kind="done", detail="", hold=None, frames=None):
    """flightsession.fly stand-in: journals `frames`, then waits on `hold`."""
    frames = [frame("running", ["[ 0s] up"])] if frames is None else frames

    async def fly(ws_url, tag, runlog, flight_s, arming_s, on_telemetry=None):
        for f in frames:
            runlog.frame(f)
            on_telemetry(f)
        if hold is not None:
            await hold.wait()
        return Outcome(kind, detail, kind == "done", time.time())

    return fly
