"""Is this machine ready to fly? Checks what the repo cannot carry -- Isaac
Sim, Pegasus + PX4, the conda env, Docker + GPU runtime, the base image,
the map's big layers -- and says how to fix each gap. Read-only.

    ./scripts/preflight.sh        (sources .env like run-service.sh)
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

# What flight-service runs from DRONE_SITL_DIR (sim.py, score.py, finalize.py).
SITL_FILES = ("joystick-server.py", "sim/run-website.sh", "sim/stop-website.sh",
              "sim/launch-sitl.sh", "sim/sites.py",
              "examples/competition-submission/fly_headless.py")
# joystick-server.py + streaming/ + this service share one env (requirements-drone.txt).
ENV_MODULES = ("fastapi", "uvicorn", "pydantic", "websockets", "pymavlink", "numpy", "PIL", "cv2")
BASE_IMAGE = "competition-base:latest"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    required: bool = True


def _succeeds(run, cmd, timeout=120):
    try:
        return run(cmd, capture_output=True, text=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def load_site(sitl_dir, name):
    """drone-sitl's own sites.get_site(name), loaded from the file without
    putting drone-sitl on sys.path."""
    spec = importlib.util.spec_from_file_location("_preflight_sites",
                                                  Path(sitl_dir) / "sim" / "sites.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses look the module up while building Site
    try:
        spec.loader.exec_module(mod)
        return mod.get_site(name)
    finally:
        sys.modules.pop(spec.name, None)


def check_token(env):
    ok = len(env.get("RUNNER_TOKEN", "")) >= 32
    return Check("token", ok, "RUNNER_TOKEN set" if ok else "RUNNER_TOKEN missing or under 32 characters",
                 "python3 -c 'import secrets;print(secrets.token_urlsafe(32))' -> RUNNER_TOKEN= in .env")


def check_sitl(sitl_dir):
    missing = [f for f in SITL_FILES if not (sitl_dir / f).is_file()]
    if missing:
        return Check("drone-sitl", False, f"{sitl_dir}: missing {', '.join(missing)}",
                     "DRONE_SITL_DIR=vendor/drone-sitl (the copy in this repo) or a full drone-sitl checkout")
    origin = "checkout"
    rec = sitl_dir / "VENDORED"
    if rec.is_file():
        fields = dict(ln.split("=", 1) for ln in rec.read_text().splitlines() if "=" in ln)
        origin = f"vendored @ {fields.get('source_commit', '?')[:7]}"
    return Check("drone-sitl", True, f"{sitl_dir} ({origin})")


def check_map(site):
    stage = site.resolved_stage_path()
    if stage is None:
        return Check("map", True, f"site {site.name} streams Cesium tiles; no stage file")
    fix = "copy the map folder across (vendor/README.md, 'map'), or ./scripts/vendor-map.sh"
    sums = stage.parent / "SHA256SUMS"
    if not sums.is_file():
        return Check("map", stage.is_file(), f"{stage} (no SHA256SUMS: layers not verified)", fix)
    bad = []
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        f = stage.parent / name.lstrip("*")
        if not f.is_file():
            bad.append(f"missing: {f.name}")
        elif _sha256(f) != digest:
            bad.append(f"changed: {f.name}")
    if bad:
        return Check("map", False, f"{stage.parent}: {'; '.join(bad)}", fix)
    return Check("map", True, f"{stage.parent} (SHA256SUMS ok)")


def _cesium_token(env, sitl_dir):
    if env.get("CESIUM_ION_TOKEN"):
        return True
    secrets = Path(env.get("SECRETS_FILE") or Path(sitl_dir) / "sim" / "secrets.env")
    try:
        text = secrets.read_text()
    except OSError:
        return False
    return bool(re.search(r"^\s*(?:export\s+)?CESIUM_ION_TOKEN=['\"]?[^'\"\s]", text, re.M))


def check_cesium(site, env, home, sitl_dir):
    if not site.uses_cesium:
        return Check("cesium", True, f"not needed: site {site.name} is a map stage")
    exts = Path(env.get("CESIUM_EXTS") or home / "cesium-omniverse-6.0-build" / "exts")
    if not exts.is_dir():
        return Check("cesium", False, f"no Cesium extensions at {exts}",
                     "build cesium-omniverse there, or set CESIUM_EXTS= in .env")
    if not _cesium_token(env, sitl_dir):
        return Check("cesium", False, "CESIUM_ION_TOKEN not set",
                     f"cp {sitl_dir}/sim/secrets.env.example {sitl_dir}/sim/secrets.env and fill it in")
    return Check("cesium", True, f"{exts} + token")


def check_isaac(env, home):
    sh = Path(env.get("ISAAC_DIR") or home / "isaac-sim6") / "isaac-sim.streaming.sh"
    return Check("isaac sim", os.access(sh, os.X_OK), str(sh),
                 "install Isaac Sim 6 there, or set ISAAC_DIR= in .env")


def check_pegasus(env, home):
    exts = Path(env.get("PEGASUS_EXTS") or home / "PegasusSimulator" / "extensions")
    cfg = exts / "pegasus.simulator" / "config" / "configs.yaml"
    if not cfg.is_file():
        return [Check("pegasus", False, f"no {cfg}",
                      "install PegasusSimulator there, or set PEGASUS_EXTS= in .env"),
                Check("px4 sitl", False, "unknown: no Pegasus config to read px4_dir from",
                      "fix pegasus first")]
    m = re.search(r"^px4_dir:\s*(\S+)", cfg.read_text(), re.M)
    if not m:
        return [Check("pegasus", True, str(exts)),
                Check("px4 sitl", False, f"no px4_dir in {cfg}", f"set px4_dir: in {cfg}")]
    px4_dir = Path(m.group(1)).expanduser()
    px4 = px4_dir / "build" / "px4_sitl_default" / "bin" / "px4"
    return [Check("pegasus", True, str(exts)),
            Check("px4 sitl", px4.is_file(), str(px4),
                  f"cd {px4_dir} && make px4_sitl_default (or fix px4_dir in {cfg})")]


def check_conda(env, run):
    name = env.get("CONDA_ENV", "drone")
    ok = _succeeds(run, ["conda", "run", "-n", name, "python", "-c", "import " + ", ".join(ENV_MODULES)])
    return Check("conda env", ok, f"{name}: {' '.join(ENV_MODULES)}",
                 f"conda create -n {name} python=3.11 && conda run -n {name} pip install -r requirements-drone.txt")


def check_ffmpeg(which):
    path = which("ffmpeg")
    return Check("ffmpeg", bool(path), path or "not on PATH (detection clips need it)",
                 "sudo apt install ffmpeg")


def check_docker(run):
    return Check("docker", _succeeds(run, ["docker", "info", "--format", "{{.ServerVersion}}"], 30),
                 "daemon reachable as this user",
                 "install Docker and add this user to the docker group")


def check_gpu_runtime(which):
    path = which("nvidia-container-runtime")
    return Check("gpu runtime", bool(path),
                 path or "missing: drone-sitl would run agents without --gpus",
                 "install nvidia-container-toolkit and restart docker")


def check_base_image(run, sitl_dir):
    ok = _succeeds(run, ["docker", "image", "inspect", BASE_IMAGE], 30)
    return Check("competition-base", ok,
                 f"{BASE_IMAGE} {'present' if ok else 'missing'} (bundle uploads build FROM it)",
                 f"cd {sitl_dir} && docker build -t {BASE_IMAGE} -f docker/competition-base/Dockerfile .")


def check_registry_login(env, home):
    cfg = Path(env.get("DOCKER_CONFIG") or home / ".docker") / "config.json"
    try:
        conf = json.loads(cfg.read_text())
    except (OSError, ValueError):
        conf = {}
    ok = bool(conf.get("credsStore") or conf.get("credHelpers")
              or any("docker.io" in k for k in conf.get("auths", {})))
    return Check("registry login", ok, str(cfg) if ok else "no Docker Hub login found",
                 "docker login  (perkiepai/* images are private)", required=False)


def run_checks(env, run=subprocess.run, which=shutil.which):
    home = Path(env.get("HOME") or Path.home())
    s = Settings.from_env({**env, "RUNNER_TOKEN": "x" * 32})    # the token gets its own check
    checks = [check_token(env), check_sitl(s.drone_sitl_dir)]
    try:
        site = load_site(s.drone_sitl_dir, s.site)
    except Exception as e:                       # noqa: BLE001 -- any failure = no usable site
        checks.append(Check("site", False, f"{s.site}: {e!r}", "SITE= must name a site in sim/sites.py"))
    else:
        checks += [Check("site", True, s.site), check_map(site),
                   check_cesium(site, env, home, s.drone_sitl_dir)]
    checks += [check_isaac(env, home), *check_pegasus(env, home), check_conda(env, run),
               check_ffmpeg(which), check_docker(run), check_gpu_runtime(which),
               check_base_image(run, s.drone_sitl_dir), check_registry_login(env, home)]
    return checks


def main(env=None, out=sys.stdout, run=subprocess.run, which=shutil.which):
    checks = run_checks(dict(os.environ if env is None else env), run, which)
    for c in checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "warn")
        print(f"{mark} {c.name:<17} {c.detail}", file=out)
        if not c.ok:
            print(f"     fix: {c.fix}", file=out)
    bad = [c for c in checks if c.required and not c.ok]
    print("\npreflight: " + ("ready" if not bad else f"{len(bad)} required check(s) failed"), file=out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
