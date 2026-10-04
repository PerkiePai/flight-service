import asyncio

import pytest

from flight_service.jobs import JobFailed
from flight_service.sitl import Sitl


def test_pull_quotes_the_ref_and_returns_the_tag():
    seen = []

    def call(method, url, timeout):
        seen.append((method, url, timeout))
        return 200, {"image_tag": "submission-truck-detector-20261005-120000"}

    assert asyncio.run(Sitl("http://w", call).pull("perkiepai/truck-detector:1", 99)) == \
        "submission-truck-detector-20261005-120000"
    assert seen == [("POST", "http://w/agent/pull-docker?ref=perkiepai%2Ftruck-detector%3A1", 99)]


def test_pull_failure_carries_the_log_tail():
    with pytest.raises(JobFailed) as e:
        asyncio.run(Sitl("http://w", lambda m, u, t: (400, {"detail": "pull failed",
                                                             "log": ["a", "manifest unknown"]})).pull("perkiepai/x:1", 5))
    assert e.value.reason == "pull_failed" and "manifest unknown" in e.value.detail


def test_detrec_status():
    assert asyncio.run(Sitl("http://w", lambda m, u, t: (200, {"on": False})).detrec_status()) == {"on": False}
    assert asyncio.run(Sitl("http://w", lambda m, u, t: (None, {})).detrec_status()) is None


def test_upload_bundle_streams_the_file(tmp_path):
    p = tmp_path / "upload.tar"
    p.write_bytes(b"tar")
    seen = []

    def send_file(url, path, timeout):
        seen.append((url, str(path), timeout))
        return 200, {"stored": "truck-1.tar", "image_tag": "submission-truck-20261005-120000"}

    tag = asyncio.run(Sitl("http://w", send_file=send_file).upload_bundle(p, "truck", 99))
    assert tag == "submission-truck-20261005-120000"
    assert seen == [("http://w/agent/upload-docker?name=truck.tar", str(p), 99)]


def test_upload_bundle_build_failure():
    with pytest.raises(JobFailed) as e:
        asyncio.run(Sitl("http://w", send_file=lambda u, p, t: (400, {"detail": "build failed",
                                                                       "log": ["pip: no such package"]}))
                    .upload_bundle("/x.tar", "truck", 5))
    assert e.value.reason == "load_failed" and "pip" in e.value.detail


def test_send_file_streams_a_real_file_to_a_server(tmp_path):
    """_send_file against a real HTTP server: body arrives whole, JSON comes back."""
    import http.server
    import threading
    from flight_service.sitl import _send_file

    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            got["body"] = self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"image_tag": "submission-t-1"}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    p = tmp_path / "b.tar"
    p.write_bytes(b"x" * 300_000)
    code, body = _send_file(f"http://127.0.0.1:{srv.server_port}/agent/upload-docker?name=t.tar", p, 10)
    srv.server_close()
    assert (code, body) == (200, {"image_tag": "submission-t-1"}) and got["body"] == b"x" * 300_000
