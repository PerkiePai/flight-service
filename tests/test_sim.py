import asyncio
import os
import time

import pytest

from flight_service.config import Settings
from flight_service.jobs import JobFailed
from flight_service.sim import SimControl, px4_ready


def settings(tmp_path, **kw):
    return Settings(drone_sitl_dir=tmp_path, runs_dir=tmp_path / "runs",
                    px4_ready_timeout_s=0.3, **kw)


class Runs:
    def __init__(self):
        self.calls = []

    async def __call__(self, *argv, timeout=60.0, env=None, cwd=None):
        self.calls.append((argv, env or {}))
        return 0, "ok"


def test_px4_ready_needs_the_line_and_a_fresh_file(tmp_path):
    console = tmp_path / "launch-sitl.console"
    assert px4_ready(console, 0) is False
    console.write_text("INFO [commander] \x1b[32mReady for takeoff!\x1b[0m\n")
    old = time.time() - 600
    os.utime(console, (old, old))
    assert px4_ready(console, time.time() - 60) is False          # last boot's file
    console.write_text("booting...\n")
    assert px4_ready(console, time.time() - 60) is False
    console.write_text("INFO [commander] \x1b[32mReady for takeoff!\x1b[0m\n")
    assert px4_ready(console, time.time() - 60) is True


def test_start_web_passes_skip_sim_and_run_args(tmp_path):
    run, s = Runs(), settings(tmp_path)
    asyncio.run(SimControl(s, run=run, up=lambda u, timeout=3.0: True).start_web())
    argv, env = run.calls[0]
    assert argv[0].endswith("sim/run-website.sh") and env["SKIP_SIM"] == "1"
    assert "--cap-drop ALL" in env["DRONE_SITL_DOCKER_RUN_ARGS"]
    # flight-service owns the server it starts: only it may upload or pull there
    assert env["DRONE_SITL_UPLOAD_TOKEN"] == s.sitl_upload_token != ""


def test_start_sim_fails_when_camera_never_answers(tmp_path):
    sim = SimControl(settings(tmp_path, boot_timeout_s=0.2), run=Runs(),
                     up=lambda u, timeout=3.0: False, alive=lambda: True)
    with pytest.raises(JobFailed) as e:
        asyncio.run(sim.start_sim(poll=0.01))
    assert e.value.reason == "sim_boot_timeout" and "not up after" in e.value.detail


def test_start_sim_waits_for_the_camera_after_the_script_returns(tmp_path):
    """Caught live: run-website.sh can return at once ("Isaac Sim exited
    before coming up") because it looks for bootstrap.py before
    launch-sitl.sh has started it. Isaac is still booting; wait for :8080."""
    answers = iter([False, False, False, True])
    calls = []

    def up(url, timeout=3.0):
        calls.append(url)
        return next(answers) if url.endswith(":8080/") else True

    sim = SimControl(settings(tmp_path, boot_timeout_s=5), run=Runs(), up=up, alive=lambda: True)
    asyncio.run(sim.start_sim(poll=0.01))
    assert calls.count("http://127.0.0.1:8080/") == 4


def test_start_sim_fails_fast_when_isaac_is_gone(tmp_path):
    sim = SimControl(settings(tmp_path, boot_timeout_s=60), run=Runs(),
                     up=lambda u, timeout=3.0: False, alive=lambda: False)
    with pytest.raises(JobFailed) as e:
        asyncio.run(sim.start_sim(poll=0.01, grace_s=0.0))
    assert e.value.reason == "sim_boot_timeout" and "exited" in e.value.detail


def test_wait_px4_ready_times_out(tmp_path):
    sim = SimControl(settings(tmp_path), run=Runs(), up=lambda u, timeout=3.0: True)
    with pytest.raises(JobFailed) as e:
        asyncio.run(sim.wait_px4_ready(time.time(), poll=0.05))
    assert e.value.reason == "px4_not_ready"


def test_busy_and_stop(tmp_path):
    up, run = {"v": True}, Runs()
    sim = SimControl(settings(tmp_path), run=run, up=lambda u, timeout=3.0: up["v"])
    assert asyncio.run(sim.busy()) is True
    up["v"] = False
    assert asyncio.run(sim.stop()) is True
    assert run.calls[-1][0][0].endswith("sim/stop-website.sh")
