import os
import time

from flight_service.retention import prune


def mk(root, name, size, age):
    d = root / name
    d.mkdir()
    (d / "job.json").write_text("{}")
    (d / "blob").write_bytes(b"x" * size)
    t = time.time() - age
    os.utime(d / "job.json", (t, t))
    return d


def test_prune_oldest_first_until_under_cap(tmp_path):
    a, b, c = mk(tmp_path, "a", 400, 300), mk(tmp_path, "b", 400, 200), mk(tmp_path, "c", 400, 100)
    assert prune(tmp_path, 1000) == ["a"]
    assert not a.exists() and b.exists() and c.exists()


def test_prune_skips_kept_and_running(tmp_path):
    a = mk(tmp_path, "a", 400, 300)
    b = mk(tmp_path, "b", 400, 200)
    (b / "RUNNING").touch()
    mk(tmp_path, "c", 400, 100)
    assert prune(tmp_path, 300, keep={"a"}) == ["c"]     # a and b are older but untouchable
    assert a.exists() and b.exists()


def test_prune_off_and_missing_dir(tmp_path):
    mk(tmp_path, "a", 400, 300)
    assert prune(tmp_path, 0) == []
    assert prune(tmp_path / "none", 10) == []


def test_prune_ignores_the_size_of_runs_it_must_keep(tmp_path):
    """Caught in review: a 12 GB upload waiting in a kept run pushed the total
    over the cap and every finished run was deleted."""
    a = mk(tmp_path, "a", 400, 300)
    big = mk(tmp_path, "big", 5000, 100)
    assert prune(tmp_path, 1000, keep={"big"}) == []
    assert a.exists() and big.exists()
