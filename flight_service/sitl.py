"""drone-sitl's :8090 HTTP endpoints the runner uses."""
import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .jobs import JobFailed


def _open(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {"detail": str(e)}
    except (OSError, ValueError) as e:          # URLError, timeouts, bad JSON
        return None, {"detail": repr(e)}


def _call(method, url, timeout, headers=None):
    return _open(urllib.request.Request(url, method=method, headers=headers or {}), timeout)


def _send_file(url, path, timeout, headers=None):
    """POST a file without reading it into memory (urllib streams a file
    object when Content-Length is given)."""
    with open(path, "rb") as f:
        req = urllib.request.Request(url, data=f, method="POST", headers={
            **(headers or {}), "Content-Length": str(os.path.getsize(path)),
            "Content-Type": "application/octet-stream"})
        return _open(req, timeout)


def _fail(reason, code, body):
    lines = [body.get("detail", f"HTTP {code}")] + list(body.get("log") or [])[-5:]
    raise JobFailed(reason, " | ".join(str(l) for l in lines))


class Sitl:
    def __init__(self, web_url, call=_call, send_file=_send_file, token=""):
        self.web, self.call, self.send_file = web_url.rstrip("/"), call, send_file
        # drone-sitl started by this service refuses uploads/pulls without it
        self.auth = {"X-Upload-Token": token} if token else {}

    async def pull(self, ref, timeout):
        """docker pull + retag submission-<stem>-<ts> (drone-sitl's
        DockerBuild.pull). Blocks until the pull finishes."""
        url = f"{self.web}/agent/pull-docker?ref={urllib.parse.quote(ref, safe='')}"
        code, body = await asyncio.to_thread(self.call, "POST", url, timeout, self.auth)
        if code == 200 and body.get("image_tag"):
            return body["image_tag"]
        _fail("pull_failed", code, body)

    async def upload_bundle(self, path, name, timeout):
        """drone-sitl's /agent/upload-docker: build a bundle (Dockerfile FROM
        competition-base) and tag it submission-<name>-<ts>."""
        url = f"{self.web}/agent/upload-docker?name={urllib.parse.quote(name + '.tar')}"
        code, body = await asyncio.to_thread(self.send_file, url, path, timeout, self.auth)
        if code == 200 and body.get("image_tag"):
            return body["image_tag"]
        _fail("load_failed", code, body)

    async def detrec_status(self):
        code, body = await asyncio.to_thread(self.call, "GET", f"{self.web}/detrec/status", 10)
        return body if code == 200 else None
