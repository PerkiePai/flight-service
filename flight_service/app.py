"""HTTP API (design 3): six endpoints, one job each. Bearer token on
everything but /healthz."""
import asyncio
import hmac
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import policy
from .jobs import FILES, TERMINAL

MAX_BODY = 4096
MEDIA = {".mp4": "video/mp4", ".jsonl": "application/x-ndjson", ".json": "application/json",
         ".log": "text/plain", ".txt": "text/plain"}


def _send(fh, size, chunk=1 << 16):
    """Exactly `size` bytes of an open file. A journal keeps growing while a
    flight runs; sending what was there when the request came keeps the body
    equal to its Content-Length (design 13.4)."""
    with fh:
        left = size
        while left > 0:
            data = fh.read(min(chunk, left))
            if not data:
                break
            left -= len(data)
            yield data


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(max_length=512)
    flight_timeout_s: int | None = None


def create_app(settings, store, worker):
    expected = f"Bearer {settings.token}".encode()

    def auth(request: Request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
            raise HTTPException(401, "missing or wrong bearer token")

    @asynccontextmanager
    async def lifespan(app):
        await worker.recover()
        task = asyncio.create_task(worker.run_forever())
        yield
        task.cancel()

    # The six endpoints of design 3 only: no unauthenticated /docs, /redoc, /openapi.json.
    app = FastAPI(title="flight-service", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def job_or_404(job_id):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return job

    def flight_seconds(value):
        flight_s = value or settings.default_flight_s
        if not 30 <= flight_s <= settings.max_flight_s:
            raise HTTPException(400, f"flight_timeout_s must be 30..{settings.max_flight_s}")
        return flight_s

    receiving = [0]          # uploads still streaming in; each will need a pending slot (B1)

    def refuse_if_full():
        """None if a new job fits, else the response to send (design 5).
        Called again right before store.new with no await in between, so
        two requests can never both take the last slot."""
        if worker.phase == "degraded":
            return JSONResponse({"detail": "degraded"}, status_code=503)
        if not worker.accepting() or len(worker.queued()) + receiving[0] >= settings.max_pending:
            return JSONResponse({"detail": "busy",
                                 "current_job": worker.current.id if worker.current else None,
                                 "pending": [j.id for j in worker.queued()]}, status_code=409)
        return None

    def accepted(job):
        worker.submit(job)
        return {"job_id": job.id, "state": job.state, "source": job.source}

    async def create_from_registry(request):
        refused = refuse_if_full()
        if refused:
            return refused
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(413, f"body over {MAX_BODY} bytes")
        try:
            req = JobRequest.model_validate_json(body)
        except ValidationError as e:
            raise HTTPException(400, f"bad request: {e.errors(include_url=False)}")
        bad = policy.check_ref(req.image, settings.allowed_images)
        if bad:
            raise HTTPException(*bad)
        flight_s = flight_seconds(req.flight_timeout_s)
        refused = refuse_if_full()          # re-check: the slot may have gone while we read
        if refused:
            return refused
        return accepted(store.new(req.image, flight_s))

    async def create_from_upload(request):        # part B1
        raise HTTPException(415, "send JSON {\"image\": ...}")

    @app.get("/healthz")
    def healthz():
        return worker.health()

    @app.post("/jobs", status_code=202, dependencies=[Depends(auth)])
    async def create(request: Request):
        """JSON = image on a registry; anything else = an uploaded image file."""
        if request.headers.get("content-type", "").startswith("application/json"):
            return await create_from_registry(request)
        return await create_from_upload(request)

    @app.get("/jobs", dependencies=[Depends(auth)])
    def list_jobs():
        return {"jobs": [j.summary() for j in store.all()[:50]]}

    @app.get("/jobs/{job_id}", dependencies=[Depends(auth)])
    def get_job(job_id: str):
        return job_or_404(job_id).public()

    @app.post("/jobs/{job_id}/kill", dependencies=[Depends(auth)])
    async def kill(job_id: str):
        job = job_or_404(job_id)
        if job.state in TERMINAL or not worker.kill(job):
            raise HTTPException(409, f"job is {job.state}; nothing to kill")
        deadline = time.monotonic() + settings.kill_wait_s
        while job.state not in TERMINAL and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        return JSONResponse(job.public(), status_code=200 if job.state in TERMINAL else 202)

    @app.get("/jobs/{job_id}/files/{name}", dependencies=[Depends(auth)])
    def get_file(job_id: str, name: str):
        path = store.dir(job_or_404(job_id)) / name
        if name not in FILES or not path.is_file():
            raise HTTPException(404, "no such file for this job")
        fh = open(path, "rb")                       # size of this inode, now
        size = os.fstat(fh.fileno()).st_size
        return StreamingResponse(_send(fh, size),
                                 media_type=MEDIA.get(path.suffix, "application/octet-stream"),
                                 headers={"Content-Length": str(size),
                                          "Content-Disposition": f'attachment; filename="{name}"'})

    return app
