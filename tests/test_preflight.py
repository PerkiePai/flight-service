import hashlib
import io
import subprocess

import pytest

from flight_service import preflight
from flight_service.config import HERE

TOKEN = "t" * 32
FAKE_SITES = '''
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Site:
    name: str
    stage_usd: object

    @property
    def uses_cesium(self):
        return self.stage_usd is None

    def resolved_stage_path(self):
        if self.stage_usd is None:
            return None
        return (Path(__file__).resolve().parent.parent / self.stage_usd).resolve()


SITES = {"mapsite": Site("mapsite", "../maps/m/drone_map.usda"), "tiles": Site("tiles", None)}


def get_site(name):
    return SITES[name]
'''


class Machine:
    """A fake box on which everything preflight looks for is present."""

    def __init__(self, root):
        self.root, self.home = root, root / "home"
        isaac = self.home / "isaac-sim6" / "isaac-sim.streaming.sh"
        isaac.parent.mkdir(parents=True)
        isaac.write_text("#!/bin/sh\n")
        isaac.chmod(0o755)
        self.px4 = root / "px4" / "build" / "px4_sitl_default" / "bin" / "px4"
        self.px4.parent.mkdir(parents=True)
        self.px4.write_text("")
        cfg = self.home / "PegasusSimulator" / "extensions" / "pegasus.simulator" / "config" / "configs.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f"ardupilot_dir: ~/ardupilot\npx4_dir: {root / 'px4'}\n")
        (self.home / ".docker").mkdir()
        (self.home / ".docker" / "config.json").write_text('{"auths": {"https://index.docker.io/v1/": {}}}')
        self.sitl = root / "drone-sitl"
        for f in preflight.SITL_FILES:
            (self.sitl / f).parent.mkdir(parents=True, exist_ok=True)
            (self.sitl / f).write_text("")
        (self.sitl / "sim" / "sites.py").write_text(FAKE_SITES)
        (self.sitl / "VENDORED").write_text("source_commit=" + "a" * 40 + "\npatches=\n")
        self.map = root / "maps" / "m"
        self.map.mkdir(parents=True)
        layers = {"drone_map.usda": b"#usda 1.0\n", "big.usdc": b"layer"}
        for name, data in layers.items():
            (self.map / name).write_bytes(data)
        (self.map / "SHA256SUMS").write_text(
            "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in layers.items()))
        self.env = {"HOME": str(self.home), "RUNNER_TOKEN": TOKEN,
                    "DRONE_SITL_DIR": str(self.sitl), "SITE": "mapsite"}
        self.fail = set()          # "conda run", "docker info", "docker image"
        self.missing = set()       # tool names which() does not find
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if " ".join(cmd[:2]) in self.fail else 0, "", "")

    def which(self, name):
        return None if name in self.missing else f"/usr/bin/{name}"

    def checks(self, **env):
        return {c.name: c for c in preflight.run_checks({**self.env, **env}, self.run, self.which)}

    def main(self, **env):
        out = io.StringIO()
        code = preflight.main({**self.env, **env}, out=out, run=self.run, which=self.which)
        return code, out.getvalue()


@pytest.fixture
def box(tmp_path):
    return Machine(tmp_path)


def test_a_ready_machine_passes_every_check(box):
    assert [n for n, c in box.checks().items() if not c.ok] == []
    code, out = box.main()
    assert code == 0 and "preflight: ready" in out


def test_missing_isaac_fails_and_says_where_it_looked(box):
    c = box.checks(ISAAC_DIR=str(box.root / "nowhere"))["isaac sim"]
    assert not c.ok and "nowhere" in c.detail and "ISAAC_DIR" in c.fix


def test_px4_is_found_through_the_pegasus_config(box):
    box.px4.unlink()
    c = box.checks()["px4 sitl"]
    assert not c.ok and str(box.px4) in c.detail and "make px4_sitl_default" in c.fix


def test_no_pegasus_fails_both_pegasus_and_px4(box):
    c = box.checks(PEGASUS_EXTS=str(box.root / "nowhere"))
    assert not c["pegasus"].ok and "PEGASUS_EXTS" in c["pegasus"].fix and not c["px4 sitl"].ok


def test_map_reports_missing_and_changed_files(box):
    (box.map / "big.usdc").unlink()
    (box.map / "drone_map.usda").write_bytes(b"edited")
    c = box.checks()["map"]
    assert not c.ok and "missing: big.usdc" in c.detail and "changed: drone_map.usda" in c.detail
    assert "vendor/README.md" in c.fix


def test_map_without_sha256sums_only_needs_the_stage_file(box):
    (box.map / "SHA256SUMS").unlink()
    assert box.checks()["map"].ok
    (box.map / "drone_map.usda").unlink()
    assert not box.checks()["map"].ok


def test_a_map_site_needs_no_cesium(box):
    c = box.checks()["cesium"]
    assert c.ok and "not needed" in c.detail


def test_a_cesium_site_needs_extensions_and_a_token(box):
    c = box.checks(SITE="tiles")
    assert not c["cesium"].ok and "CESIUM_EXTS" in c["cesium"].fix
    assert c["map"].ok                                   # tile sites have no stage file
    (box.home / "cesium-omniverse-6.0-build" / "exts").mkdir(parents=True)
    assert "CESIUM_ION_TOKEN" in box.checks(SITE="tiles")["cesium"].detail
    (box.sitl / "sim" / "secrets.env").write_text("export CESIUM_ION_TOKEN=abc\n")
    assert box.checks(SITE="tiles")["cesium"].ok


def test_an_unknown_site_is_a_failed_check_not_a_crash(box):
    c = box.checks(SITE="nope")
    assert not c["site"].ok and "nope" in c["site"].detail and "map" not in c


def test_a_conda_env_without_the_modules_fails_with_the_install_line(box):
    box.fail.add("conda run")
    c = box.checks()["conda env"]
    assert not c.ok and "requirements-drone.txt" in c.fix
    assert any("cv2" in " ".join(cmd) for cmd in box.calls)


def test_docker_gpu_runtime_and_base_image(box):
    box.missing.add("nvidia-container-runtime")
    box.fail.add("docker image")
    c = box.checks()
    assert not c["gpu runtime"].ok and "nvidia-container-toolkit" in c["gpu runtime"].fix
    assert not c["competition-base"].ok
    assert "docker/competition-base/Dockerfile" in c["competition-base"].fix


def test_commands_that_are_not_installed_are_failed_checks(box):
    def run(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    c = {c.name: c for c in preflight.run_checks(box.env, run, box.which)}
    assert not c["docker"].ok and not c["conda env"].ok


def test_no_registry_login_is_only_a_warning(box):
    (box.home / ".docker" / "config.json").unlink()
    code, out = box.main()
    assert code == 0 and "warn registry login" in out and "docker login" in out


def test_a_short_token_fails(box):
    code, out = box.main(RUNNER_TOKEN="short")
    assert code == 1 and "FAIL token" in out and "1 required check(s) failed" in out


def test_the_vendored_copy_passes_the_drone_sitl_check():
    c = preflight.check_sitl(HERE / "vendor" / "drone-sitl")
    assert c.ok and "vendored @" in c.detail
