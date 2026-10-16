"""The vendored drone-sitl copy and map: complete, self-contained, and what
flight-service expects (vendor/README.md)."""
import hashlib
import importlib.util
import modulefinder
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from flight_service.score import load_truth

ROOT = Path(__file__).resolve().parent.parent
SITL = ROOT / "vendor" / "drone-sitl"
MAP = ROOT / "vendor" / "maps" / "nt-testgs"
BIG = ("nt_testgs.usdc", "Truck2.usd")       # not in git: copied across by hand
LOCAL = {"offboard", "waypoints", "agent_control", "docker_build", "detections",
         "det_recorder", "competition", "competition.agent", "competition.commands",
         "competition.frames", "competition.harness", "competition.state",
         "sites", "stage_builder"}


def manifest():
    lines = (ROOT / "vendor" / "drone-sitl.manifest").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def sums():
    """{file name: sha256} from SHA256SUMS."""
    pairs = (ln.split(None, 1) for ln in (MAP / "SHA256SUMS").read_text().splitlines() if ln.strip())
    return {name: digest for digest, name in pairs}


def test_every_manifest_path_is_in_the_copy():
    assert [p for p in manifest() if not (SITL / p).exists()] == []


def test_the_copy_records_its_source_and_patch():
    rec = dict(ln.split("=", 1) for ln in (SITL / "VENDORED").read_text().splitlines())
    assert re.fullmatch(r"[0-9a-f]{40}", rec["source_commit"])
    patches = sorted(p.name for p in (ROOT / "vendor" / "patches" / "drone-sitl").glob("*.patch"))
    assert rec["patches"].split() == patches
    assert "0002-agent-container-name-drone-sim.patch" in patches


def test_the_scripts_flight_service_runs_are_executable():
    for name in ("run-website.sh", "stop-website.sh", "launch-sitl.sh"):
        assert os.access(SITL / "sim" / name, os.X_OK), name


@pytest.mark.parametrize("script", ["joystick-server.py", "agent_runner.py", "sim/bootstrap.py",
                                    "examples/competition-submission/fly_headless.py"])
def test_local_imports_resolve_inside_the_copy(script):
    mf = modulefinder.ModuleFinder(path=[str(SITL / d) for d in ("", "streaming", "sim")] + sys.path)
    mf.run_script(str(SITL / script))
    assert sorted(LOCAL & set(mf.badmodules)) == []
    outside = [m.__file__ for n, m in mf.modules.items()
               if n in LOCAL and not Path(m.__file__).is_relative_to(SITL)]
    assert outside == []


def test_vendored_code_names_no_home_directory():
    hits = [str(p.relative_to(SITL)) for p in SITL.rglob("*")
            if p.is_file() and p.suffix in {".py", ".sh"}
            and re.search(r"/home/\w", p.read_text(errors="replace"))]
    assert hits == []


def test_site_stage_is_the_vendored_map(monkeypatch):
    spec = importlib.util.spec_from_file_location("_vendored_sites", SITL / "sim" / "sites.py")
    sites = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, sites)   # dataclasses look the module up
    spec.loader.exec_module(sites)
    site = sites.get_site("nt-testgs")
    assert site.resolved_stage_path() == MAP / "drone_map.usda"
    assert site.uses_cesium is False


def test_map_references_stay_inside_its_folder():
    refs = set(re.findall(r"@([^@]+)@", (MAP / "drone_map.usda").read_text()))
    assert refs == {"./drone_map_physics.usdc", "./nt_testgs.usdc", "./Truck2.usd"}
    assert {r[2:] for r in refs} <= set(sums())


def test_small_map_files_match_and_big_ones_are_ignored():
    for name, digest in sums().items():
        f = MAP / name
        if name in BIG and not f.exists():
            continue                                  # fresh clone: preflight reports it
        assert hashlib.sha256(f.read_bytes()).hexdigest() == digest, name
    for name in BIG:                                  # check-ignore is 0 if ANY path is ignored
        ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(MAP / name)])
        assert ignored.returncode == 0, name


def test_load_truth_reads_the_vendored_map():
    origin, trucks = load_truth(SITL, "nt-testgs")
    assert origin == pytest.approx((14.028519616, 100.43642032))
    assert sorted(trucks) == ["Vehicle_01", "Vehicle_02", "Vehicle_03"]
    import fly_headless
    assert Path(fly_headless.__file__).is_relative_to(SITL)
