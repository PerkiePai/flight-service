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
    s = Settings(drone_sitl_dir=tmp_path / "sitl", runs_dir=tmp_path / "runs",
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
        deadline = asyncio.get_running_loop().time() + 15
        while not until(job):
            assert asyncio.get_running_loop().time() < deadline, f"condition never met; job {job.state}"
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


import io
import tarfile


def upload_job(store, kind="image", tags=("truck:1",)):
    """An upload as POST /jobs leaves it: data/uploads/<job_id>.tar, outside runs/."""
    job = store.new(f"upload:{kind}:truck", 600, source="upload", upload_kind=kind, upload_name="truck")
    up = store.root.parent / "uploads"
    up.mkdir(exist_ok=True)
    with tarfile.open(up / f"{job.id}.tar", "w") as tar:
        if kind == "image":
            members = [("manifest.json", json.dumps([{"Config": "c", "RepoTags": list(tags), "Layers": []}]).encode())]
        else:
            members = [("Dockerfile", b"FROM competition-base:latest\n"), ("agent.py", b"x")]
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return job


def upload_file(store, job):
    return store.root.parent / "uploads" / f"{job.id}.tar"


def test_image_archive_upload_flies_and_cleans_up(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    _, store, w = setup(tmp_path, docker=docker, sim=sim)
    job = upload_job(store)
    asyncio.run(w.run_job(job))
    assert job.state == DONE, (job.reason, job.detail)
    assert job.image_tag.startswith("submission-truck-")
    assert ("tag", "truck:1", job.image_tag) in docker.calls
    assert ("rmi", "docker.io/library/truck:1") in docker.calls    # the archive's own tag
    assert ("rmi", job.image_tag) in docker.calls              # cleanup
    assert ("rmi", job.image) not in docker.calls
    assert not upload_file(store, job).exists() and not (store.dir(job) / "upload.tar").exists()
    assert sim.calls == ["busy", "start_sim", "wait_px4_ready", "stop"]
    ev = list(read_jsonl(store.dir(job) / "events.jsonl"))
    assert [e["state"] for e in ev if e["kind"] == "state"][0] == "loading"


def test_archive_tag_that_exists_is_rejected(tmp_path):
    docker = FakeDocker(exists=True)
    _, store, w = setup(tmp_path, docker=docker)
    job = upload_job(store, tags=("competition-base:latest",))
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason, job.failed_in) == (FAILED, "archive_rejected", "loading")
    assert not any(c[0] == "load" for c in docker.calls)
    assert not any(c[0] == "rmi" and "competition-base" in c[1] for c in docker.calls)
    assert not upload_file(store, job).exists()


def test_bundle_upload_builds_through_drone_sitl(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    _, store, w = setup(tmp_path, docker=docker, sim=sim)
    job = upload_job(store, kind="bundle")
    asyncio.run(w.run_job(job))
    assert job.state == DONE, (job.reason, job.detail)
    assert job.image_tag == "submission-truck-20261005-120000"
    assert sim.calls == ONE                                  # web first, for the build
    assert ("rmi", job.image_tag) in docker.calls and not upload_file(store, job).exists()


def test_load_creating_an_undeclared_name_fails_and_degrades(tmp_path):
    """Caught in review: if docker load names the image differently from what
    was checked, a protected tag may have been overwritten -> stop taking jobs."""
    docker = FakeDocker()
    docker.loaded = ("competition-base:latest",)
    _, store, w = setup(tmp_path, docker=docker)
    job = upload_job(store)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "archive_rejected")
    assert "competition-base" in job.detail and w.phase == "degraded"


def test_kill_during_docker_load_removes_the_archive_names(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    docker.load_hold = asyncio.Event()
    _, store, w = setup(tmp_path, docker=docker, sim=sim)
    job = upload_job(store)
    w.submit(job)

    async def kill(j):
        assert w.kill(j)
        while w.phase != "idle":
            await asyncio.sleep(0.01)

    run_bg(w, store, until=lambda j: ("load", str(upload_file(store, j))) in docker.calls, then=kill)
    assert job.state == KILLED and job.failed_in == "loading"
    assert ("rmi", "docker.io/library/truck:1") in docker.calls
    assert not upload_file(store, job).exists()


def test_tag_failure_still_removes_what_the_load_brought(tmp_path):
    docker = FakeDocker()
    docker.tag_fails = True
    _, store, w = setup(tmp_path, docker=docker)
    job = upload_job(store)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "load_failed")
    assert ("rmi", "docker.io/library/truck:1") in docker.calls
    assert job.image_tag and ("rmi", job.image_tag) in docker.calls


def test_recover_cleans_an_upload_job_and_stale_upload_files(tmp_path):
    s, store, _ = setup(tmp_path)
    job = upload_job(store)
    job.extra_tags = ["docker.io/library/truck:1"]
    store.set_state(job, "loading")
    stray = s.uploads_dir / "0123abcd.tar.part"
    stray.write_bytes(b"half an upload")
    docker, sim, fresh = FakeDocker(), FakeSim(), JobStore(s.runs_dir)
    w = Worker(s, fresh, docker, sim, FakeSitl(), fly=make_fly(), truth=lambda: TRUTH)
    asyncio.run(w.recover())
    assert (fresh.get(job.id).state, fresh.get(job.id).reason) == (FAILED, "runner_restarted")
    assert ("rmi", "docker.io/library/truck:1") in docker.calls
    assert list(s.uploads_dir.iterdir()) == [] and sim.calls == []


def test_health_counts_an_upload_still_streaming_in(tmp_path):
    _, _, w = setup(tmp_path)
    w.receiving = 1
    assert w.health() == {"ok": True, "ready": False, "phase": "idle", "pending": 1}


def test_unsafe_bundle_is_rejected_before_drone_sitl_sees_it(tmp_path):
    sim = FakeSim()
    _, store, w = setup(tmp_path, sim=sim)
    job = store.new("upload:bundle:truck", 600, source="upload", upload_kind="bundle", upload_name="truck")
    (store.root.parent / "uploads").mkdir(exist_ok=True)
    with tarfile.open(upload_file(store, job), "w") as tar:
        for name, kind, target in (("Dockerfile", tarfile.REGTYPE, ""), ("a", tarfile.SYMTYPE, "/home")):
            info = tarfile.TarInfo(name)
            info.type, info.linkname = kind, target
            tar.addfile(info, io.BytesIO(b"") if kind == tarfile.REGTYPE else None)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "archive_rejected")
    assert "start_web" not in sim.calls


def test_kill_during_pull_stops_the_pull_and_removes_its_leftovers(tmp_path):
    """Review minor: the pull runs inside drone-sitl's web process; cancelling
    our request does not stop it, and stop-website.sh leaves its `docker pull`
    child running. The image (and a late retag) then stayed on the disk."""
    import time as _t
    docker, sim, sitl = FakeDocker(), FakeSim(), FakeSitl()
    sitl.pull_hold = asyncio.Event()
    late = f"submission-x-{_t.strftime('%Y%m%d-%H%M%S', _t.localtime(_t.time() + 5))}:latest"
    docker.tags_present = (late, "submission-x-20200101-000000:latest")   # one from long ago
    _, store, w = setup(tmp_path, docker=docker, sim=sim, sitl=sitl)
    job = store.new("perkiepai/x:1", 600)
    w.submit(job)

    async def kill(j):
        await asyncio.sleep(0.05)
        assert w.kill(j)
        while w.phase != "idle":
            await asyncio.sleep(0.01)

    run_bg(w, store, until=lambda j: j.pull_started is not None, then=kill)
    assert (job.state, job.failed_in) == (KILLED, PULLING)
    assert ("stop_pull", "perkiepai/x:1") in docker.calls
    assert ("rmi", late) in docker.calls                           # retagged after we gave up
    assert ("rmi", "submission-x-20200101-000000:latest") not in docker.calls
    assert ("rmi", "perkiepai/x:1") in docker.calls and sim.calls[-1] == "stop"


def test_a_finished_pull_leaves_nothing_to_sweep(tmp_path):
    docker = FakeDocker()
    _, store, w = setup(tmp_path, docker=docker)
    asyncio.run(w.run_job(store.new("perkiepai/x:1", 600)))
    assert not any(c[0] == "stop_pull" for c in docker.calls)
