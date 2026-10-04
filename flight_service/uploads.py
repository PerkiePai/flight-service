"""Receive an uploaded file as a stream straight to disk, counting bytes
(design 12). The body never sits in memory; a bad upload leaves nothing."""
import os
from pathlib import Path

BUNDLE_MAX = 200 * 1024 ** 2          # drone-sitl's AGENT_DOCKER_MAX_BYTES
NAME_RE = r"[a-z0-9][a-z0-9_-]{0,63}"


class UploadError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


async def receive(chunks, dest, expected, limit):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    n = 0
    try:
        with open(part, "wb") as f:
            async for chunk in chunks:
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
