"""The journals of one run (design 13.4), open for the whole job. Every
/ws frame is split three ways the moment it arrives: telemetry (all of
PX4's fields), new agent log lines (events), and boxes (detections)."""
import time
from pathlib import Path

from .journal import Journal

POSE_KEYS = ("lat", "lon", "alt_m", "heading_deg")


def new_lines(prev, cur):
    """Lines of `cur` not already in `prev`. Both are the agent panel's
    sliding window (the last N lines), so the longest suffix of `prev`
    that is a prefix of `cur` is what we have already seen."""
    k = min(len(prev), len(cur))
    while k and cur[:k] != prev[-k:]:
        k -= 1
    return cur[k:]


class RunLog:
    def __init__(self, run_dir, fsync_every_s=1.0):
        d = Path(run_dir)
        self.telemetry = Journal(d / "telemetry.jsonl", fsync_every_s)
        self.events = Journal(d / "events.jsonl", fsync_every_s)
        self.detections = Journal(d / "detections.jsonl", fsync_every_s)
        self._log = []

    def event(self, kind, **fields):
        self.events.append({"t": time.time(), "kind": kind, **fields})

    def frame(self, t):
        now = time.time()
        agent = dict(t.get("agent") or {})
        log = agent.pop("log", None) or []
        boxes = agent.pop("detections", None) or []
        self.telemetry.append({**{k: v for k, v in t.items() if k != "agent"},
                               "t": now, "agent": agent})
        for line in new_lines(self._log, log):
            self.event("log", line=line)
        self._log = list(log)
        if boxes:
            self.detections.append({"t": now, "drone": {k: t.get(k) for k in POSE_KEYS},
                                    "boxes": boxes})

    def close(self):
        for j in (self.telemetry, self.events, self.detections):
            j.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
