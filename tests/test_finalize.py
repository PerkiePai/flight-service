import asyncio
import json
import time

from fakes import BOX, frame

from flight_service.finalize import finalize, wait_clip
from flight_service.jobs import RUNNING_MARK
from flight_service.journal import read_jsonl
from flight_service.runlog import RunLog

TRUTH = ((14.0, 100.0), {"A": (0.0, 0.0)})


def make_run(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / RUNNING_MARK).touch()
    with RunLog(d) as rl:
        rl.frame(frame("running", ["[1s] hi"], boxes=[BOX]))
        rl.frame(frame("stopped", ["[1s] hi", "[2s] DONE"], lat=14.0 + 100 / 110574.0, alt=40.0))


def test_finalize_builds_everything_from_journals(tmp_path):
    make_run(tmp_path)
    r = finalize(tmp_path, job_id="j1", ended_by="agent", outcome="done", done_line=True,
                 truth=TRUTH, site="x")
    assert (r["ended_by"], r["partial"], r["outcome"]) == ("agent", False, "done")
    assert r["track_points"] == 2 and abs(r["distance_m"] - 100) < 0.5 and r["max_alt_m"] == 40.0
    assert r["score"] == {"version": "v0", "score": 100.0, "recall": 1.0, "precision": 1.0,
                          "trucks_found": 1, "trucks_total": 1}
    assert (tmp_path / "panel.log").read_text() == "[1s] hi\n[2s] DONE\n"
    track = list(read_jsonl(tmp_path / "track.jsonl"))
    assert track[0]["t"] == 0.0 and set(track[0]) == {"t", "lat", "lon", "alt", "heading", "roll",
                                                      "pitch", "gs", "vz", "mode", "armed", "state"}
    assert not (tmp_path / RUNNING_MARK).exists()
    assert json.loads((tmp_path / "result.json").read_text()) == r
    assert r["files"]["result.json"] == "/jobs/j1/files/result.json"
    assert "detections.mp4" in r["missing"] and "analysis.txt" not in r["missing"]


def test_finalize_is_idempotent(tmp_path):
    make_run(tmp_path)
    kw = dict(job_id="j1", ended_by="kill", truth=TRUTH, site="x")
    assert finalize(tmp_path, **kw) == finalize(tmp_path, **kw)


def test_finalize_with_nothing_on_disk(tmp_path):
    r = finalize(tmp_path, job_id="j1", ended_by="error", truth=TRUTH, site="x")
    assert r["partial"] is True and r["track_points"] == 0 and r["score"]["score"] == 0.0


def test_finalize_copies_the_clip(tmp_path):
    clip = tmp_path / "clip"
    clip.mkdir()
    (clip / "detections.mp4").write_bytes(b"mp4")
    (clip / "meta.json").write_text("{}")
    run = tmp_path / "run"
    make_run(run)
    r = finalize(run, job_id="j1", ended_by="agent", truth=TRUTH, site="x", clip_dir=clip)
    assert (run / "detections.mp4").read_bytes() == b"mp4" and r["missing"] == []


def test_wait_clip_waits_for_meta(tmp_path):
    clip = tmp_path / "2026-10-05" / "120005_x"
    clip.mkdir(parents=True)
    states = [{"on": True, "last": None}, {"on": False, "last": str(clip / "detections.mp4")}]

    async def status():
        if len(states) > 1:
            return states.pop(0)
        (clip / "meta.json").write_text("{}")
        return states[0]

    assert asyncio.run(wait_clip(status, time.time() - 5, 2.0, poll=0.01)) == clip


def test_wait_clip_gives_up(tmp_path):
    async def status():
        return {"on": False, "last": None}
    assert asyncio.run(wait_clip(status, time.time(), 0.05, poll=0.01)) is None
