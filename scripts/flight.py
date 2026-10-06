#!/usr/bin/env python3
"""flight.py -- hand flight-service an image, watch the flight live, bring
the results home. One file, standard library only (Python 3.8+): copy it
anywhere.

  flight.py health
  flight.py run IMAGE [--timeout S] [--out DIR] [--wait S]
  flight.py run --file X.tar --kind image|bundle --name N [--timeout S] [--out DIR] [--wait S]
  flight.py watch JOB_ID [--out DIR]
  flight.py kill JOB_ID

Where and who: --url / FLIGHT_URL (default http://127.0.0.1:8095) and
--token / RUNNER_TOKEN. Progress goes to stderr; stdout carries one JSON
line for whatever called this.

Exit codes of run and watch:
  0  the job ended `done`
  1  the job ended `failed` or `killed`
  2  the service could not be reached, refused the job, or a result file
     could not be fetched
  3  interrupted (Ctrl-C, SIGTERM). The job is NOT killed: it belongs to
     the service. `watch` picks it up again, `kill` stops it.
health: 0 ready, 1 not ready, 2 unreachable. kill: 0 taken, 1 nothing to kill, 2 unreachable.
"""
import argparse
import http.client
import json
import os
import select
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8095"
TERMINAL = ("done", "failed", "killed")
EXIT_OK, EXIT_FAILED, EXIT_UNREACHABLE, EXIT_INTERRUPTED = 0, 1, 2, 3

HTTP_TIMEOUT_S = 30         # one ordinary request
KILL_TIMEOUT_S = 90         # a kill is answered after up to 60 s of cleanup
UPLOAD_TIMEOUT_S = 120      # silence on the line while a file goes up
EXPECT_WAIT_S = 2           # wait this long for "100 Continue", then send the file anyway
STREAM_IDLE_S = 45          # the service pings every 15 s: this long silent = the line is dead
BACKOFF_S, BACKOFF_MAX_S = 1, 10    # reconnect after 1, 2, 4, 8, 10, 10 ... seconds
STREAM_GIVE_UP_S = 60       # no stream for this long -> poll instead
POLL_S = 3
POLL_GIVE_UP_S = 300        # no answer at all for this long while polling -> exit 2
READY_POLL_S = 2
SHOW_EVERY_S = 5            # one position line per this many seconds
WHAT = {401: "token wrong or missing", 409: "pending slot full",
        503: "service degraded: someone has to fix the machine"}

sleep = time.sleep


class Stop(Exception):
    """Ends the command: a message for stderr and the exit code."""

    def __init__(self, message, code=EXIT_UNREACHABLE):
        super().__init__(message)
        self.code = code


class Unreachable(Exception):
    """No HTTP answer: refused, reset, timed out, cut off half way."""


class HttpError(Exception):
    """An HTTP answer that is not the 200 a stream needs."""

    def __init__(self, status, body):
        super().__init__(explain(status, body))
        self.status = status


def say(message):
    """One progress line on stderr; never dies on a terminal that is not UTF-8."""
    encoding = sys.stderr.encoding or "utf-8"
    line = f"{time.strftime('%H:%M:%S')} {message}\n"
    sys.stderr.write(line.encode(encoding, "backslashreplace").decode(encoding))
    sys.stderr.flush()


def explain(status, body):
    """An HTTP refusal as one line: what it means here + what the service said."""
    detail = body.get("detail") if isinstance(body, dict) else body
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    hint = f" ({WHAT[status]})" if status in WHAT else ""
    return f"HTTP {status}{hint}: {detail}"


def _parse(raw):
    """A JSON object, or {"detail": text} for anything else (a proxy's error page)."""
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    return body if isinstance(body, dict) else {"detail": raw.decode("utf-8", "replace")[:300]}


def _status(response):
    return response.code if isinstance(response, urllib.error.HTTPError) else response.status


def sse_events(lines):
    """(event, data, id) for each complete Server-Sent Event in an iterable
    of byte lines. Comment lines (the keepalive) are dropped, and so is an
    event cut off before its blank line."""
    event, data, eid = "message", [], None
    for raw in lines:
        line = raw.rstrip(b"\r\n").decode("utf-8", "replace")
        if not line:
            if data:
                yield event, "\n".join(data), eid
            event, data, eid = "message", [], None
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            eid = value


def _may_send(sock):
    """After the headers of an `Expect: 100-continue` request: True to send
    the body (the service said 100 Continue, or nothing at all for
    EXPECT_WAIT_S like a server that ignores Expect), False when its verdict
    is already there."""
    if not select.select([sock], [], [], EXPECT_WAIT_S)[0]:
        return True
    head = b""
    for _ in range(50):
        head = sock.recv(12, socket.MSG_PEEK)
        if len(head) >= 12 or not head:
            break
        time.sleep(0.02)
    return head.startswith(b"HTTP/1.1 100")


class Api:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def _open(self, method, path, body=None, headers=None, timeout=None):
        """The response, whatever its status. Unreachable if there is none."""
        req = urllib.request.Request(self.url + path, data=body, method=method,
                                     headers=headers or {})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            return urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            return e                                # an answer, just not 2xx
        except (OSError, http.client.HTTPException) as e:
            raise Unreachable(f"{self.url}: {getattr(e, 'reason', e)}")

    def json(self, method, path, body=None, timeout=None):
        """(status, body as a dict)."""
        headers = {}
        if body is not None:
            body, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
        with self._open(method, path, body, headers, timeout) as r:
            try:
                return _status(r), _parse(r.read())
            except (OSError, http.client.HTTPException) as e:
                raise Unreachable(f"{self.url}: {e}")

    def stream(self, job_id, last_id=0):
        """Events of GET /jobs/{id}/stream after telemetry line `last_id`.
        Returns when the service closes the line; HttpError if it does not
        open one; Unreachable if the line breaks or stays silent."""
        headers = {"Accept": "text/event-stream"}
        if last_id:
            headers["Last-Event-ID"] = str(last_id)
        with self._open("GET", f"/jobs/{job_id}/stream", headers=headers,
                        timeout=STREAM_IDLE_S) as r:
            try:
                if _status(r) != 200:
                    raise HttpError(_status(r), _parse(r.read()))
                yield from sse_events(r)
            except (OSError, http.client.HTTPException) as e:
                raise Unreachable(f"{self.url}: {e}")

    def download(self, path, dest):
        """Save GET `path` as `dest`: written as <dest>.part, renamed only
        when all of it arrived. False (and no file) otherwise."""
        part = dest + ".part"
        try:
            with self._open("GET", path) as r:
                if _status(r) != 200:
                    return False
                want, got = r.headers.get("Content-Length"), 0
                with open(part, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
            if want is not None and got != int(want):
                raise OSError(f"{got} of {want} bytes")
            os.replace(part, dest)
            return True
        except (Unreachable, OSError, http.client.HTTPException):
            if os.path.exists(part):
                os.remove(part)
            return False

    def upload(self, path, query):
        """POST a file as the body of /jobs?<query>, streamed from disk with
        its Content-Length, as `curl -T` does. Like curl it asks first
        (Expect: 100-continue): the service refuses a file it will not take
        -- slot full, too large, no disk -- before a byte of it is sent."""
        u = urllib.parse.urlsplit(self.url)
        tls = u.scheme == "https"                   # no peeking into a TLS socket: just send
        cls = http.client.HTTPSConnection if tls else http.client.HTTPConnection
        conn = cls(u.netloc, timeout=UPLOAD_TIMEOUT_S)
        try:
            with open(path, "rb") as f:
                conn.putrequest("POST", f"{u.path}/jobs?{query}")
                conn.putheader("Authorization", "Bearer " + self.token)
                conn.putheader("Content-Type", "application/octet-stream")
                conn.putheader("Content-Length", str(os.fstat(f.fileno()).st_size))
                if not tls:
                    conn.putheader("Expect", "100-continue")
                conn.endheaders()
                if tls or _may_send(conn.sock):
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        conn.send(chunk)
            r = conn.getresponse()
            return r.status, _parse(r.read())
        except (OSError, http.client.HTTPException) as e:
            raise Unreachable(f"{self.url}: upload of {path}: {e}")
        finally:
            conn.close()


# -- commands -----------------------------------------------------------------

def cmd_health(api, args):
    status, health = api.json("GET", "/healthz")
    if status != 200:
        raise Stop(explain(status, health))
    print(json.dumps(health), flush=True)
    return EXIT_OK if health.get("ready") else EXIT_FAILED


def cmd_kill(api, args):
    status, job = api.json("POST", f"/jobs/{args.job_id}/kill", timeout=KILL_TIMEOUT_S)
    if status not in (200, 202):
        raise Stop(explain(status, job), EXIT_FAILED if status in (404, 409) else EXIT_UNREACHABLE)
    if status == 202:
        say(f"kill taken; the service is still cleaning up: flight.py watch {args.job_id}")
    print(json.dumps({"job_id": args.job_id, "state": job.get("state"),
                      "reason": job.get("reason")}), flush=True)
    return EXIT_OK


# -- command line -------------------------------------------------------------

COMMANDS = {"health": cmd_health, "kill": cmd_kill}


def parser():
    p = argparse.ArgumentParser(prog="flight.py", description="Submit one image to "
                                "flight-service, follow the flight, fetch the results.")
    p.add_argument("--url", default=os.environ.get("FLIGHT_URL", DEFAULT_URL),
                   help="the service (default: $FLIGHT_URL or %s)" % DEFAULT_URL)
    p.add_argument("--token", default=os.environ.get("RUNNER_TOKEN", ""),
                   help="bearer token (default: $RUNNER_TOKEN)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="can the service take a job now?")
    kill = sub.add_parser("kill", help="stop a job")
    kill.add_argument("job_id")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.cmd != "health" and not args.token:
            raise Stop("no token: export RUNNER_TOKEN=... (the service's .env) or pass --token")
        return COMMANDS[args.cmd](Api(args.url, args.token), args)
    except Stop as e:
        say(str(e))
        return e.code
    except Unreachable as e:
        say(f"cannot reach the service: {e}")
        return EXIT_UNREACHABLE
    except KeyboardInterrupt:
        say("interrupted")
        return EXIT_INTERRUPTED


def _terminate(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)       # a supervisor's stop = Ctrl-C
    sys.exit(main())
