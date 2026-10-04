import asyncio
import json

from fakes import BOX, FakeDocker, FakeSim, FakeSitl, frame, make_fly

from flight_service.config import Settings
from flight_service.jobs import (BOOTING, DONE, FAILED, FLYING, KILLED, PULLING,
                                 QUEUED, RUNNING_MARK, JobStore)
from flight_service.journal import read_jsonl
from flight_service.worker import Worker

TRUTH = ((14.0, 100.0), {"A": (0.0, 0.0)})
ONE = ["busy", "start_web", "start_sim", "wait_px4_ready", "stop"]


def setup(tmp_path, docker=None, sim=None, sitl=None, fly=None, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    kw.setdefault("data_retention_gb", 0)
    s = Settings(token="t" * 32, drone_sitl_dir=tmp_path / "sitl", runs_dir=tmp_path / "runs",
                 docker_root=tmp_path, min_free_gb=0, collect_timeout_s=0.05, **kw)
    store = JobStore(s.runs_dir)
    w = Worker(s, store, docker or FakeDocker(), sim or FakeSim(), sitl or FakeSitl(),
               fly=fly or make_fly(), truth=lambda: TRUTH)
    return s, store, w


def make_clip(tmp_path):
    clip = tmp_path / "rec" / "2026-10-05" / "120000_x"
    clip.mkdir(parents=True)
    (clip / "detections.mp4").write_bytes(b"mp4")
    (clip / "meta.json").write_text("{}")
    return clip


def run_bg(w, store, until, then=None):
    """Run the worker loop until until(oldest job) is true, then `then`."""
    async def scenario():
        loop = asyncio.create_task(w.run_forever())
        job = store.all()[-1]
        while not until(job):
            await asyncio.sleep(0.01)
        if then:
            await then(job)
        loop.cancel()
        return job
    return asyncio.run(scenario())


def test_happy_path(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    _, store, w = setup(tmp_path, docker=docker, sim=sim, sitl=FakeSitl(clip=make_clip(tmp_path)),
                        fly=make_fly(frames=[frame("running", ["[ 1s] hello"], boxes=[BOX]),
                                             frame("stopped", ["[ 1s] hello", "[ 2s] DONE"])]))
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert job.state == DONE, (job.reason, job.detail)
    assert sim.calls == ONE
    assert job.score_live == {"rows": 1, "trucks_found": 1, "trucks_total": 1}
    r = job.result
    assert (r["ended_by"], r["partial"], r["score"]["score"]) == ("agent", False, 100.0)
    assert {"telemetry.jsonl", "events.jsonl", "detections.jsonl", "track.jsonl", "panel.log",
            "detections.mp4", "score.json", "result.json"} <= set(r["files"])
    d = store.dir(job)
    assert (d / "panel.log").read_text() == "[ 1s] hello\n[ 2s] DONE\n"
    assert not (d / RUNNING_MARK).exists()
    ev = list(read_jsonl(d / "events.jsonl"))
    assert [e["state"] for e in ev if e["kind"] == "state"] == [PULLING, BOOTING, FLYING]
    assert ev[-1]["kind"] == "end" and ev[-1]["state"] == DONE
    assert ("rmi", "submission-x-20261005-120000") in docker.calls
    assert ("rmi", "perkiepai/x:1") in docker.calls          # this job brought it in
    assert ("rm_force", "submission-run-1") in docker.calls
    assert w.phase == "idle"


def test_preexisting_image_is_not_removed(tmp_path):
    docker = FakeDocker(exists=True)
    _, store, w = setup(tmp_path, docker=docker)
    asyncio.run(w.run_job(store.new("perkiepai/drone-rtdetr-submission:latest", 600)))
    assert ("rmi", "perkiepai/drone-rtdetr-submission:latest") not in docker.calls
    assert ("rmi", "submission-x-20261005-120000") in docker.calls


def test_keep_image(tmp_path):
    docker = FakeDocker()
    _, store, w = setup(tmp_path, docker=docker, keep_image=True)
    asyncio.run(w.run_job(store.new("perkiepai/x:1", 600)))
    assert not any(c[0] == "rmi" for c in docker.calls)


def test_sim_busy_fails_without_touching_the_sim(tmp_path):
    sim = FakeSim(busy=True)
    _, store, w = setup(tmp_path, sim=sim)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason, job.failed_in) == (FAILED, "sim_busy", PULLING)
    assert sim.calls == ["busy"] and job.result["partial"] is True


def test_pull_failure_stops_the_web_it_started(tmp_path):
    sim = FakeSim()
    _, store, w = setup(tmp_path, sim=sim, sitl=FakeSitl(fail="manifest unknown"))
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "pull_failed") and sim.calls[-1] == "stop"


def test_image_too_large_after_pull(tmp_path):
    docker = FakeDocker(size=20 * 1024 ** 3, manifest=None)
    _, store, w = setup(tmp_path, docker=docker)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "image_too_large")
    assert ("rmi", "submission-x-20261005-120000") in docker.calls


def test_px4_not_ready(tmp_path):
    sim = FakeSim(fail=("wait_px4_ready", "px4_not_ready", "no line"))
    _, store, w = setup(tmp_path, sim=sim)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason, job.failed_in) == (FAILED, "px4_not_ready", BOOTING)
    assert sim.calls[-1] == "stop"


def test_flight_failures_map_to_reasons_and_keep_data(tmp_path):
    for kind, reason, ended_by in [("crashed", "agent_crashed", "error"),
                                   ("refused", "run_refused", "error"),
                                   ("arming_timeout", "arming_timeout", "error"),
                                   ("timeout", "flight_timeout", "timeout"),
                                   ("ws_lost", "ws_lost", "error")]:
        _, store, w = setup(tmp_path / kind, fly=make_fly(kind, "why"))
        job = store.new("perkiepai/x:1", 600)
        asyncio.run(w.run_job(job))
        assert (job.state, job.reason, job.failed_in) == (FAILED, reason, FLYING)
        assert (job.result["outcome"], job.result["ended_by"]) == (kind, ended_by)
        assert job.result["track_points"] == 1


def test_missing_clip_still_finishes(tmp_path):
    _, store, w = setup(tmp_path, sitl=FakeSitl(clip=None))
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert job.state == DONE and "detections.mp4" in job.result["missing"]


def test_cleanup_failure_degrades_and_refuses_new_jobs(tmp_path):
    _, store, w = setup(tmp_path, sim=FakeSim(stop_ok=False))
    asyncio.run(w.run_job(store.new("perkiepai/x:1", 600)))
    assert w.phase == "degraded" and w.health()["ok"] is False
    job = store.new("perkiepai/y:1", 600)
    w.submit(job)
    run_bg(w, store, until=lambda _: store.get(job.id).state != QUEUED)
    assert (job.state, job.reason) == (FAILED, "runner_degraded")


def test_state_ends_only_after_cleanup(tmp_path):
    seen = {}

    class WatchSim(FakeSim):
        async def stop(self):
            seen["state"] = job.state
            return await super().stop()

    _, store, w = setup(tmp_path, sim=WatchSim())
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert seen["state"] == FLYING and job.state == DONE and w.phase == "idle"


def test_health_reports_room_for_one_pending_job(tmp_path):
    _, store, w = setup(tmp_path)
    assert w.health() == {"ok": True, "ready": True, "phase": "idle", "pending": 0}
    store.new("perkiepai/x:1", 600)                          # waiting in the slot
    assert w.health()["ready"] is False and w.health()["pending"] == 1


def test_kill_while_flying_keeps_the_data(tmp_path):
    sim, docker = FakeSim(), FakeDocker()
    _, store, w = setup(tmp_path, sim=sim, docker=docker, sitl=FakeSitl(clip=make_clip(tmp_path)),
                        fly=make_fly(hold=asyncio.Event()))
    job = store.new("perkiepai/x:1", 600)
    w.submit(job)

    async def kill(j):
        await asyncio.sleep(0.02)
        assert w.kill(j) is True
        while j.state == FLYING or w.phase != "idle":
            await asyncio.sleep(0.01)

    run_bg(w, store, until=lambda j: j.state == FLYING, then=kill)
    assert (job.state, job.reason, job.failed_in) == (KILLED, "killed", FLYING)
    r = job.result
    assert (r["ended_by"], r["partial"], r["track_points"]) == ("kill", True, 1)
    assert "detections.mp4" in r["files"]                 # clip closed by the agent stop
    assert sim.calls[-1] == "stop" and ("rm_force", "submission-run-1") in docker.calls


def test_kill_twice_is_harmless(tmp_path):
    _, store, w = setup(tmp_path, fly=make_fly(hold=asyncio.Event()))
    job = store.new("perkiepai/x:1", 600)
    w.submit(job)

    async def kill(j):
        assert w.kill(j) and w.kill(j)
        while w.phase != "idle":
            await asyncio.sleep(0.01)

    run_bg(w, store, until=lambda j: j.state == FLYING, then=kill)
    assert job.state == KILLED and job.result is not None


def test_kill_queued(tmp_path):
    _, store, w = setup(tmp_path)
    job = store.new("perkiepai/x:1", 600)
    assert w.kill(job) is True
    assert (job.state, job.failed_in, job.result) == (KILLED, QUEUED, None)
    assert w.kill(job) is False


def test_recover_finalizes_and_stops_only_owned_sims(tmp_path):
    s, store, _ = setup(tmp_path)
    flying = store.new("perkiepai/a:1", 600)
    flying.owns_sim, flying.image_tag = True, "submission-a-1"
    store.set_state(flying, FLYING)
    (store.dir(flying) / RUNNING_MARK).touch()
    (store.dir(flying) / "telemetry.jsonl").write_text(json.dumps(
        {"t": 1.0, "lat": 14.0, "lon": 100.0, "alt_m": 5.0, "agent": {"state": "running"}}) + "\n")
    queued = store.new("perkiepai/b:1", 600)
    sim, fresh = FakeSim(), JobStore(s.runs_dir)
    w = Worker(s, fresh, FakeDocker(), sim, FakeSitl(), fly=make_fly(), truth=lambda: TRUTH)
    asyncio.run(w.recover())
    a, b = fresh.get(flying.id), fresh.get(queued.id)
    assert (a.state, a.reason, a.failed_in) == (FAILED, "runner_restarted", FLYING)
    assert (a.result["ended_by"], a.result["partial"], a.result["track_points"]) == \
        ("runner_restarted", True, 1)
    assert not (s.runs_dir / a.id / RUNNING_MARK).exists()
    assert (b.state, b.reason, b.result) == (FAILED, "runner_restarted", None)
    assert sim.calls == ["stop"]


def test_retention_keeps_the_run_just_finished(tmp_path):
    _, store, w = setup(tmp_path, data_retention_gb=1e-9)        # ~1 byte cap
    old = store.new("perkiepai/old:1", 600)
    store.end(old, DONE)
    (store.dir(old) / "telemetry.jsonl").write_text("x" * 100)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert not store.dir(old).exists() and store.get(old.id) is None
    assert store.dir(job).exists() and store.get(job.id) is job


def test_service_shutdown_is_not_a_kill(tmp_path):
    """SIGTERM cancels run_job without kill(): leave the job for startup
    recovery (failed/runner_restarted), never record it as a user kill."""
    s, store, w = setup(tmp_path, fly=make_fly(hold=asyncio.Event()))
    job = store.new("perkiepai/x:1", 600)

    async def scenario():
        task = asyncio.create_task(w.run_job(job))
        while job.state != FLYING:
            await asyncio.sleep(0.01)
        task.cancel()                                  # what asyncio.run does at shutdown
        try:
            await task
        except asyncio.CancelledError:
            return "cancelled"

    assert asyncio.run(scenario()) == "cancelled"
    assert job.state == FLYING and job.result is None
    assert "stop" not in w.sim.calls                   # no cleanup on the way out
    assert (store.dir(job) / RUNNING_MARK).exists()
    fresh = JobStore(s.runs_dir)
    w2 = Worker(s, fresh, FakeDocker(), FakeSim(), FakeSitl(), fly=make_fly(), truth=lambda: TRUTH)
    asyncio.run(w2.recover())
    again = fresh.get(job.id)
    assert (again.state, again.reason, again.result["ended_by"]) == \
        (FAILED, "runner_restarted", "runner_restarted")
