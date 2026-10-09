import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn


@pytest.fixture
def serve():
    """serve(app) -> base URL of the app on a real uvicorn in a thread."""
    running = []

    def start(app):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        running.append((server, thread))
        return f"http://127.0.0.1:{port}"

    yield start
    for server, thread in running:
        server.should_exit = True
        thread.join(timeout=5)


def http(method, url, body=None, raw=False, ctype=None):
    """(status, parsed JSON | bytes)."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype or "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = r.read()
            return r.status, payload if raw else json.loads(payload)
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else json.loads(payload or b"{}")


def sse_events(payload):
    """[(event, id, data)] of a Server-Sent Events byte stream, data parsed
    as JSON. A keepalive comment is ("ping", None, None)."""
    out = []
    for block in payload.decode().split("\n\n"):
        if not block:
            continue
        if block.startswith(":"):
            out.append(("ping", None, None))
            continue
        f = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((f["event"], int(f["id"]) if "id" in f else None, json.loads(f["data"])))
    return out
