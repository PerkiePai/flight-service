"""Receive an uploaded file as a stream straight to disk, counting bytes
(design 12). The body never sits in memory; a bad upload leaves nothing."""
import asyncio
import os
from pathlib import Path

BUNDLE_MAX = 200 * 1024 ** 2          # drone-sitl's AGENT_DOCKER_MAX_BYTES
NAME_RE = r"[a-z0-9][a-z0-9_-]{0,63}"


class UploadError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


async def receive(chunks, dest, expected, limit, idle_timeout_s=60.0):
    """Stream `chunks` into `dest`. A client that sends nothing for
    `idle_timeout_s` is dropped (408) so it cannot hold the slot forever."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    n = 0
    it = chunks.__aiter__()
    try:
        with open(part, "wb") as f:
            while True:
                try:
                    chunk = await asyncio.wait_for(it.__anext__(), idle_timeout_s)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise UploadError(408, f"no data for {idle_timeout_s:.0f}s")
                n += len(chunk)
                if n > min(expected, limit):
                    raise UploadError(413, f"body larger than its Content-Length or the {limit} byte limit")
                f.write(chunk)
        if n != expected:
            raise UploadError(400, f"got {n} of {expected} bytes")
        os.replace(part, dest)
        return n
    except BaseException:
        part.unlink(missing_ok=True)
        raise
