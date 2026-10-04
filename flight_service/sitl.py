"""drone-sitl's :8090 HTTP endpoints the runner uses."""
import asyncio
import json
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


def _call(method, url, timeout):
    return _open(urllib.request.Request(url, method=method), timeout)


def _fail(reason, code, body):
    lines = [body.get("detail", f"HTTP {code}")] + list(body.get("log") or [])[-5:]
    raise JobFailed(reason, " | ".join(str(l) for l in lines))


class Sitl:
    def __init__(self, web_url, call=_call):
        self.web, self.call = web_url.rstrip("/"), call

    async def pull(self, ref, timeout):
        """docker pull + retag submission-<stem>-<ts> (drone-sitl's
        DockerBuild.pull). Blocks until the pull finishes."""
        url = f"{self.web}/agent/pull-docker?ref={urllib.parse.quote(ref, safe='')}"
        code, body = await asyncio.to_thread(self.call, "POST", url, timeout)
        if code == 200 and body.get("image_tag"):
            return body["image_tag"]
        _fail("pull_failed", code, body)

    async def detrec_status(self):
        code, body = await asyncio.to_thread(self.call, "GET", f"{self.web}/detrec/status", 10)
        return body if code == 200 else None
