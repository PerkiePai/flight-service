import json

from flight_service.jobs import (DONE, FAILED, FLYING, KILLED, PULLING, QUEUED,
                                 JobStore)


def test_new_job_is_queued_and_written(tmp_path):
    store = JobStore(tmp_path)
    job = store.new("perkiepai/x:1", 600)
    assert job.state == QUEUED and job.source == "registry"
    assert json.loads((tmp_path / job.id / "job.json").read_text())["image"] == "perkiepai/x:1"
    assert store.get(job.id) is job and not list(tmp_path.glob(f"{job.id}/.*.tmp"))


def test_upload_fields(tmp_path):
    job = JobStore(tmp_path).new("upload:image:truck", 600, source="upload",
                                 upload_kind="image", upload_name="truck")
    assert (job.source, job.upload_kind, job.upload_name) == ("upload", "image", "truck")


def test_fail_and_kill_record_where_and_why(tmp_path):
    store = JobStore(tmp_path)
    a = store.new("perkiepai/a:1", 600)
    store.set_state(a, PULLING)
    store.fail(a, "pull_failed", "no such image")
    assert (a.state, a.failed_in, a.reason, a.detail) == (FAILED, PULLING, "pull_failed", "no such image")
    b = store.new("perkiepai/b:1", 600)
    store.set_state(b, FLYING)
    store.end(b, KILLED, "killed", "killed while flying")
    assert (b.state, b.failed_in) == (KILLED, FLYING)
    c = store.new("perkiepai/c:1", 600)
    store.end(c, DONE)
    assert (c.state, c.failed_in, c.reason) == (DONE, None, None)
    assert b.public()["reason"] == "killed" and "telemetry" not in b.summary()


def test_load_returns_only_unfinished_and_skips_corrupt(tmp_path):
    store = JobStore(tmp_path)
    a, b, c = (store.new(f"perkiepai/{n}:1", 600) for n in "abc")
    store.set_state(a, FLYING)
    store.end(b, DONE)
    (tmp_path / c.id / "job.json").write_text("{not json")
    fresh = JobStore(tmp_path)
    assert [j.id for j in fresh.load()] == [a.id]
    assert fresh.get(b.id).state == DONE and fresh.get(c.id) is None


def test_forget(tmp_path):
    store = JobStore(tmp_path)
    job = store.new("perkiepai/x:1", 600)
    store.forget(job.id)
    assert store.get(job.id) is None and store.all() == []
