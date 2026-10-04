"""The single worker: one job at a time through acquire -> boot -> fly,
then finalize from the run's journals and clean up -- however the job
ended, kill included (design 2, 4, 5, 7, 13). The sim is one shared
resource (trap 4), so there is exactly one Worker per process."""
import asyncio
import logging
import shutil
import time

from . import finalize as fin
from . import archive, flightsession, policy, retention
from . import score as scoring
from .config import GB
from .jobs import (BOOTING, DONE, FAILED, FLYING, KILLED, LOADING, PULLING, QUEUED,
                   RUNNING_MARK, TERMINAL, JobFailed)
from .runlog import RunLog

log = logging.getLogger("flight_service")

FAIL_REASON = {"crashed": "agent_crashed", "refused": "run_refused",
               "arming_timeout": "arming_timeout", "timeout": "flight_timeout",
               "ws_lost": "ws_lost"}
TELEM_KEYS = ("lat", "lon", "alt_m", "heading_deg", "roll_deg", "pitch_deg",
              "gs", "vz", "mode", "armed")


class Worker:
    def __init__(self, settings, store, docker, sim, sitl, fly=flightsession.fly, truth=None):
        self.s, self.store = settings, store
        self.docker, self.sim, self.sitl, self.fly = docker, sim, sitl, fly
        self._truth_fn = truth or (lambda: scoring.load_truth(settings.drone_sitl_dir, settings.site))
        self._truth = None
        self.queue = asyncio.Queue()
        self.current = None
        self._task = None
        self._kill_sent = False
        self.phase = "idle"          # idle | running | finishing | cleanup | degraded

    # -- queue -----------------------------------------------------------

    def submit(self, job):
        self.queue.put_nowait(job.id)

    def queued(self):
        return [j for j in self.store.all() if j.state == QUEUED]

    def accepting(self):
        """Room for one more job: not degraded, and fewer than max_pending
        waiting behind the running one (design 5: the real queue is the
        caller's; this small one only absorbs a dispatch race)."""
        return self.phase != "degraded" and len(self.queued()) < self.s.max_pending

    def kill(self, job):
        """True if taken. Queued: ends at once. Running: interrupted, then
        finalized and cleaned up like any other end (design 13.5)."""
        if job.state == QUEUED:
            self.store.end(job, KILLED, "killed", "killed while queued")
            return True
        if self.current is job:
            if self.phase == "running" and not self._kill_sent and self._task:
                self._kill_sent = True
                self._task.cancel()
            return True              # already finishing: it ends anyway
        return False

    def health(self):
        return {"ok": self.phase != "degraded", "ready": self.accepting(),
                "phase": self.phase, "pending": len(self.queued())}

    async def run_forever(self):
        while True:
            job = self.store.get(await self.queue.get())
            if job is None or job.state != QUEUED:
                continue             # killed while queued
            if self.phase == "degraded":
                self.store.fail(job, "runner_degraded",
                                "an earlier cleanup could not stop the sim; run "
                                "sim/stop-website.sh by hand, then restart the service")
                continue
            self._task = asyncio.create_task(self.run_job(job))
            await asyncio.wait({self._task})     # never raises for the job's own end

    async def recover(self):
        """At startup: finalize what a restart interrupted, stop a sim it had
        started. A job that was only queued never touched anything."""
        for job in self.store.load():
            was = job.state
            if was != QUEUED:
                job.result = await asyncio.to_thread(
                    self._finalize, job, "runner_restarted", None,
                    f"runner restarted while {was}", None)
                if job.owns_sim and not await self._cleanup(job):
                    self.phase = "degraded"
            self.store.fail(job, "runner_restarted", f"runner restarted while {was}")
        self._prune()

    # -- one job -----------------------------------------------------------

    async def run_job(self, job):
        self.current, self.phase, self._kill_sent = job, "running", False
        run_dir = self.store.dir(job)
        (run_dir / RUNNING_MARK).touch()
        runlog = RunLog(run_dir)
        outcome = None
        end = (FAILED, "error", "internal_error", "worker stopped before the job ended")
        shutting_down = False
        try:
            try:
                runlog.event("start", image=job.image, source=job.source)
                await self._acquire(job, runlog)
                await self._boot(job, runlog)
                outcome = await self._fly(job, runlog)
                if outcome.kind == "done":
                    end = (DONE, "agent", None, outcome.detail)
                elif outcome.kind == "timeout":
                    end = (FAILED, "timeout", "flight_timeout", outcome.detail)
                else:
                    end = (FAILED, "error", FAIL_REASON[outcome.kind], outcome.detail)
            except JobFailed as e:
                end = (FAILED, "error", e.reason, e.detail)
            except asyncio.CancelledError:
                if not self._kill_sent:
                    # The service is stopping (SIGTERM), not a kill: leave the
                    # job as it is for startup recovery -> runner_restarted.
                    shutting_down = True
                    raise
                end = (KILLED, "kill", "killed", f"killed while {job.state}")
            except Exception as e:                  # noqa: BLE001
                log.exception("job %s", job.id)
                end = (FAILED, "error", "internal_error", repr(e))
            self.phase = "finishing"                # a kill from here on is a no-op
            state, ended_by, reason, detail = end
            runlog.event("end", state=state, ended_by=ended_by, reason=reason, detail=detail)
            runlog.close()
            clip = None
            if job.run_at:                          # RUN was sent -> det_recorder has a clip
                clip = await fin.wait_clip(self.sitl.detrec_status, job.run_at,
                                           self.s.collect_timeout_s)
            job.result = await asyncio.to_thread(self._finalize, job, ended_by, outcome,
                                                 detail, clip)
        finally:
            runlog.close()
            if not shutting_down:           # a `return` here would swallow the CancelledError
                self.phase = "cleanup"
                ok = await self._cleanup(job)
                self.phase = "idle" if ok else "degraded"
                self.current, self._task = None, None
                state, _, reason, detail = end
                self.store.end(job, state, reason, detail)  # only now: cleanup is done (design 4)
                self._prune(also_keep=job.id)

    def _set(self, job, runlog, state):
        self.store.set_state(job, state)
        runlog.event("state", state=state)

    async def _precheck(self, job, runlog, state):
        self._set(job, runlog, state)
        if await self.sim.busy():
            raise JobFailed("sim_busy", "drone-sitl web (:8090) or sim (:8080) is already "
                                        "running and this runner did not start it")

    async def _acquire(self, job, runlog):
        """Put the image on this box as job.image_tag."""
        if job.source == "registry":
            await self._pull(job, runlog)
        elif job.source == "upload":
            await self._load(job, runlog)
        else:
            raise JobFailed("unsupported_source", job.source)

    async def _load(self, job, runlog):
        await self._precheck(job, runlog, LOADING)
        upload = self.store.dir(job) / "upload.tar"
        try:
            if job.upload_kind == "image":
                await self._load_image(job, upload)
            elif job.upload_kind == "bundle":
                await self._load_bundle(job, upload)
            else:
                raise JobFailed("unsupported_source", f"upload kind {job.upload_kind!r}")
            self.store.save(job)
        finally:
            upload.unlink(missing_ok=True)          # up to 16 GB: not kept for the flight
        await self._check_size(job)

    async def _load_image(self, job, upload):
        tags = await asyncio.to_thread(archive.repo_tags, upload)
        for t in tags:
            if await self.docker.exists(t):
                raise JobFailed("archive_rejected",
                                f"archive tag {t} already exists on this box and would be overwritten")
        loaded = await self.docker.load(upload, self.s.pull_timeout_s)
        if not loaded:
            raise JobFailed("load_failed", "docker load reported nothing loaded")
        tag = f"submission-{job.upload_name}-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            await self.docker.tag(loaded[0], tag)
            job.image_tag = tag
        finally:
            for t in tags:                          # untag what the archive brought in;
                await self.docker.rmi(t)            # the image stays under our own tag

    async def _load_bundle(self, job, upload):     # replaced in B3
        raise JobFailed("unsupported_source", "bundle uploads come in B3")

    async def _pull(self, job, runlog):
        await self._precheck(job, runlog, PULLING)
        size = await self.docker.manifest_bytes(job.image, self.s.manifest_timeout_s)
        policy.check_space(shutil.disk_usage(self.s.docker_root).free, size,
                           self.s.min_free_gb, self.s.max_image_gb)
        job.image_preexisting = await self.docker.exists(job.image)
        job.owns_sim = True
        self.store.save(job)
        await self.sim.start_web()
        job.image_tag = await self.sitl.pull(job.image, self.s.pull_timeout_s)
        self.store.save(job)
        await self._check_size(job)

    async def _check_size(self, job):
        real = await self.docker.size(job.image_tag)
        if real is not None and real > self.s.max_image_gb * GB:
            raise JobFailed("image_too_large", f"{real / GB:.1f} GB > {self.s.max_image_gb:g} GB")

    async def _boot(self, job, runlog):
        self._set(job, runlog, BOOTING)
        job.owns_sim = True
        self.store.save(job)
        since = time.time()
        await self.sim.start_sim()
        await self.sim.wait_px4_ready(since)

    def _load_truth(self):
        if self._truth is None:
            try:
                self._truth = self._truth_fn()
            except Exception as e:                  # noqa: BLE001 -- score 0, flight still counts
                log.warning("no map truth for score: %r", e)
                self._truth = ((0.0, 0.0), {})
        return self._truth

    async def _fly(self, job, runlog):
        self._set(job, runlog, FLYING)
        origin, trucks = await asyncio.to_thread(self._load_truth)
        live = scoring.ScoreV0(trucks, origin)
        last_save = [0.0]

        def on_telemetry(t):
            agent = t.get("agent") or {}
            job.telemetry = {**{k: t.get(k) for k in TELEM_KEYS}, "agent_state": agent.get("state")}
            job.log_tail = list((agent.get("log") or [])[-20:])
            live.add(t, agent.get("detections") or [])
            job.score_live = live.live()
            if time.monotonic() - last_save[0] > 5.0:
                self.store.save(job)
                last_save[0] = time.monotonic()

        job.run_at = time.time()
        self.store.save(job)
        return await self.fly(self.s.ws_url, job.image_tag, runlog, job.flight_timeout_s,
                              self.s.arming_timeout_s, on_telemetry=on_telemetry)

    def _finalize(self, job, ended_by, outcome, detail, clip):
        return fin.finalize(self.store.dir(job), job_id=job.id, ended_by=ended_by,
                            outcome=outcome.kind if outcome else None, detail=detail,
                            done_line=bool(outcome and outcome.done_line),
                            truth=self._load_truth(), site=self.s.site, clip_dir=clip,
                            drone_sitl_dir=self.s.drone_sitl_dir)

    async def _cleanup(self, job):
        """Remove what this job brought in, keep its data. True if the sim is down."""
        ok = True
        try:
            if job.image_tag:
                for name in await self.docker.containers_of(job.image_tag):
                    await self.docker.rm_force(name)
            if job.owns_sim:
                ok = await self.sim.stop()
            if not self.s.keep_image:
                if job.image_tag:
                    await self.docker.rmi(job.image_tag)
                if job.source == "registry" and job.owns_sim and not job.image_preexisting:
                    await self.docker.rmi(job.image)
        except Exception:                           # noqa: BLE001
            log.exception("cleanup of %s", job.id)
            ok = False
        return ok

    def _prune(self, also_keep=None):
        keep = {j.id for j in self.store.all() if j.state not in TERMINAL} | {also_keep}
        for jid in retention.prune(self.s.runs_dir, self.s.data_retention_gb * GB, keep):
            self.store.forget(jid)
