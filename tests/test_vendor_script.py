"""scripts/vendor-drone-sitl.sh against a throwaway drone-sitl git repo."""
import difflib
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vendor-drone-sitl.sh"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
SITES_V1 = 'STAGE = "/home/someone/map.usda"\n'


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def commit(repo, files, msg):
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if name.endswith(".sh"):
            p.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


def patch(path, old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"a/{path}", f"b/{path}"))


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def record(dest):
    return dict(line.split("=", 1) for line in (dest / "VENDORED").read_text().splitlines())


@pytest.fixture
def src(tmp_path):
    repo = tmp_path / "drone-sitl"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, {"sim/run.sh": "#!/bin/sh\necho run\n", "sim/sites.py": SITES_V1,
                  "web/index.html": "<html></html>\n", "logs/old.console": "not wanted\n",
                  "examples/huge.bin": "not wanted\n"}, "one")
    return repo


@pytest.fixture
def vendor(tmp_path):
    """vendor(src, *args, manifest=..., patches={name: text}) -> (CompletedProcess, dest)"""
    dest = tmp_path / "vendor" / "drone-sitl"
    pdir = tmp_path / "patches"
    pdir.mkdir()

    def run(src, *args, manifest="# what we run\n\nsim/run.sh\nsim/sites.py\nweb\n", patches=None):
        (tmp_path / "manifest").write_text(manifest)
        for f in pdir.iterdir():
            f.unlink()
        for name, text in (patches or {}).items():
            (pdir / name).write_text(text)
        env = {**os.environ, **GIT_ENV, "VENDOR_DIR": str(dest),
               "VENDOR_MANIFEST": str(tmp_path / "manifest"), "VENDOR_PATCHES": str(pdir)}
        r = subprocess.run(["bash", str(SCRIPT), str(src), *args], env=env,
                           capture_output=True, text=True)
        return r, dest
    return run


def test_copies_only_manifest_paths_and_records_the_commit(src, vendor):
    r, dest = vendor(src)
    assert r.returncode == 0, r.stderr
    assert files(dest) == ["VENDORED", "sim/run.sh", "sim/sites.py", "web/index.html"]
    assert os.access(dest / "sim" / "run.sh", os.X_OK)
    assert record(dest)["source_commit"] == git(src, "rev-parse", "HEAD")
    assert record(dest)["patches"] == ""


def test_takes_the_commit_not_the_working_tree(src, vendor):
    old = git(src, "rev-parse", "HEAD")
    commit(src, {"sim/sites.py": 'STAGE = "v2"\n'}, "two")
    (src / "sim" / "sites.py").write_text("uncommitted\n")
    r, dest = vendor(src, old)
    assert r.returncode == 0, r.stderr
    assert (dest / "sim" / "sites.py").read_text() == SITES_V1
    assert record(dest)["source_commit"] == old


def test_an_unknown_commit_fails_before_copying(src, vendor):
    r, dest = vendor(src, "no-such-rev")
    assert r.returncode != 0 and "no-such-rev" in r.stderr and not dest.exists()


def test_applies_patches_in_name_order(src, vendor):
    mid = 'STAGE = "../maps/m/drone_map.usda"\n'
    r, dest = vendor(src, patches={
        "0002-more.patch": patch("sim/sites.py", mid, mid + "EXTRA = 1\n"),
        "0001-map.patch": patch("sim/sites.py", SITES_V1, mid)})
    assert r.returncode == 0, r.stderr
    assert (dest / "sim" / "sites.py").read_text() == mid + "EXTRA = 1\n"
    assert record(dest)["patches"].split() == ["0001-map.patch", "0002-more.patch"]
    assert not list(dest.rglob("*.orig")) and not list(dest.rglob("*.rej"))


def test_a_patch_that_no_longer_applies_leaves_the_copy_alone(src, vendor):
    _, dest = vendor(src)
    before = {f: (dest / f).read_text() for f in files(dest)}
    r, _ = vendor(src, patches={"0001-x.patch": patch("sim/sites.py", "something else\n", "y\n")})
    assert r.returncode != 0 and "0001-x.patch" in r.stderr
    assert {f: (dest / f).read_text() for f in files(dest)} == before


def test_a_manifest_path_missing_from_the_commit_fails_before_copying(src, vendor):
    r, dest = vendor(src, manifest="sim/run.sh\nsim/gone.py\n")
    assert r.returncode != 0 and not dest.exists()


def test_resync_keeps_runtime_output_and_drops_what_left_the_manifest(src, vendor):
    _, dest = vendor(src)
    for keep in ("logs/launch-sitl.console", "recordings/a.mp4", "sim/secrets.env"):
        (dest / keep).parent.mkdir(parents=True, exist_ok=True)
        (dest / keep).write_text("keep\n")
    r, dest = vendor(src, manifest="sim/run.sh\nsim/sites.py\n")
    assert r.returncode == 0, r.stderr
    assert files(dest) == ["VENDORED", "logs/launch-sitl.console", "recordings/a.mp4",
                           "sim/run.sh", "sim/secrets.env", "sim/sites.py"]
