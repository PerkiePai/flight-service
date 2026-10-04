"""Isaac Sim + PX4 + drone-sitl's :8090 web server, driven only through
drone-sitl's own scripts. Never pkill: stop-website.sh matches drone-sitl's
process signatures (trap 5)."""
import asyncio
import os
import subprocess
import time

from .dockerctl import sh, tail
from .jobs import JobFailed

READY_LINE = "Ready for takeoff"


def http_up(url, timeout=3.0):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:            # noqa: BLE001 -- any failure means "not up"
        return False


def px4_ready(console, since):
    """True once `console` was (re)written after `since` and holds READY_LINE
    (trap 1: RUN before it = PX4 refuses arm and AgentRun never retries).
    The mtime check keeps the previous boot's file from counting."""
    try:
        if os.stat(console).st_mtime < since:
            return False
        with open(console, errors="replace") as f:
            return READY_LINE in f.read()
    except OSError:
        return False


class SimControl:
    def __init__(self, settings, run=sh, up=http_up, alive=None):
        self.s, self.run, self.up = settings, run, up
        self.dir = settings.drone_sitl_dir
        self.console = self.dir / "logs" / "launch-sitl.console"
        self.alive = alive or self._isaac_alive

    def _isaac_alive(self):
        """drone-sitl's own isaac_running() check (read-only pgrep; we never kill by pattern)."""
        return subprocess.run(["pgrep", "-f", str(self.dir / "sim" / "bootstrap.py")],
                              capture_output=True).returncode == 0

    def _env(self, **extra):
        return {**os.environ, "DRONE_SITL_DOCKER_RUN_ARGS": self.s.docker_run_args,
                "DRONE_SITL_UPLOAD_TOKEN": self.s.sitl_upload_token, **extra}

    async def _up(self, url):
        return await asyncio.to_thread(self.up, url)

    async def busy(self):
        return await self._up(self.s.video_url) or await self._up(self.s.web_url + "/")

    async def start_web(self):
        """Only the :8090 server (SKIP_SIM=1): enough for pull/build."""
        _, out = await self.run(str(self.dir / "sim" / "run-website.sh"), timeout=90,
                                env=self._env(SKIP_SIM="1"), cwd=str(self.dir))
        if not await self._up(self.s.web_url + "/"):
            raise JobFailed("web_start_failed", tail(out))

    async def start_sim(self, poll=3.0, grace_s=30.0):
        """Isaac + PX4 (+ the web server if it is not up yet). run-website.sh
        can return before Isaac is up: its wait loop looks for bootstrap.py
        before launch-sitl.sh has started it and gives up at once (caught
        live, Task 13). So wait for the camera server here ourselves; fail
        early only once Isaac's process has really gone."""
        wait = int(self.s.boot_timeout_s)
        t0 = time.monotonic()
        await self.run(str(self.dir / "sim" / "run-website.sh"), timeout=wait + 60,
                       env=self._env(ISAAC_WAIT_S=str(wait)), cwd=str(self.dir))
        while time.monotonic() - t0 < wait:
            if await self._up(self.s.video_url):
                return
            if time.monotonic() - t0 >= grace_s and not await asyncio.to_thread(self.alive):
                raise JobFailed("sim_boot_timeout",
                                f"Isaac Sim exited before {self.s.video_url} came up; see {self.console}")
            await asyncio.sleep(poll)
        raise JobFailed("sim_boot_timeout",
                        f"camera server {self.s.video_url} not up after {wait}s; see {self.console}")

    async def wait_px4_ready(self, since, poll=2.0):
        deadline = time.monotonic() + self.s.px4_ready_timeout_s
        while time.monotonic() < deadline:
            if px4_ready(self.console, since):
                return
            await asyncio.sleep(poll)
        raise JobFailed("px4_not_ready", f"no '{READY_LINE}' in {self.console} after "
                                         f"{self.s.px4_ready_timeout_s:.0f}s")

    async def stop(self):
        """stop-website.sh; True once :8080 and :8090 no longer answer."""
        await self.run(str(self.dir / "sim" / "stop-website.sh"), timeout=self.s.cleanup_timeout_s,
                       env=self._env(), cwd=str(self.dir))
        return not await self.busy()
