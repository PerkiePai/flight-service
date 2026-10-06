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


# -- run / watch --------------------------------------------------------------

class Progress:
    """What the flight looks like on stderr: one line per state change and
    one position line every SHOW_EVERY_S. Remembers the last state seen."""

    def __init__(self):
        self.state, self._shown = None, None

    def on_state(self, state, reason=None):
        if state != self.state:
            self.state = state
            say(f"state {state}" + (f" ({reason})" if reason else ""))

    def on_telemetry(self, t):
        now = time.monotonic()
        if self._shown is not None and now - self._shown < SHOW_EVERY_S:
            return
        self._shown = now
        agent = t.get("agent_state") or (t.get("agent") or {}).get("state")
        alt = t.get("alt_m")
        alt = round(alt, 1) if isinstance(alt, (int, float)) else alt
        say(f"{self.state} alt={alt} lat={t.get('lat')} lon={t.get('lon')} "
            f"mode={t.get('mode')} agent={agent}")


def wait_ready(api, deadline, waited):
    """Return once /healthz says ready. Degraded: stop now, waiting cannot
    fix it. Still busy at `deadline`: stop."""
    told = False
    while True:
        status, health = api.json("GET", "/healthz")
        if status != 200:
            raise Stop(explain(status, health))
        if health.get("ok") is False:
            raise Stop(f"service degraded (phase {health.get('phase')}): someone has to fix "
                       "the machine first (the service README says how)")
        if health.get("ready"):
            return
        if time.monotonic() >= deadline:
            raise Stop(f"service still busy after {waited:g}s (phase {health.get('phase')}, "
                       f"pending {health.get('pending')}): try again later or raise --wait")
        if not told:
            say(f"service busy (phase {health.get('phase')}, pending {health.get('pending')}); waiting")
            told = True
        sleep(READY_POLL_S)


def submit(api, args):
    """(status, body) of POST /jobs for an image name or a file."""
    if args.file:
        query = {"kind": args.kind, "name": args.name}
        if args.timeout is not None:
            query["flight_timeout_s"] = args.timeout
        say(f"uploading {args.file} ({os.path.getsize(args.file)} bytes)")
        return api.upload(args.file, urllib.parse.urlencode(query))
    body = {"image": args.image}
    if args.timeout is not None:
        body["flight_timeout_s"] = args.timeout
    return api.json("POST", "/jobs", body)


def follow(api, job_id, progress):
    """True once the stream delivered the job's `end`. False when there is
    no stream to be had (an older service, events this client cannot read,
    nothing for STREAM_GIVE_UP_S): the caller polls instead. A broken line
    is reconnected from the last telemetry line that arrived whole."""
    last_id, backoff, down_since = 0, BACKOFF_S, None
    while True:
        try:
            for event, data, eid in api.stream(job_id, last_id):
                backoff, down_since = BACKOFF_S, None
                data = json.loads(data)
                if event == "telemetry":
                    last_id = int(eid)
                    progress.on_telemetry(data)
                elif event == "state":
                    progress.on_state(data.get("state"), data.get("reason"))
                elif event == "end":
                    progress.on_state(data.get("state"), data.get("reason"))
                    return True
            why = "the service closed the stream"
        except HttpError as e:
            if e.status == 401:
                raise Stop(str(e))
            if e.status in (404, 405, 501):         # no such endpoint, or no such job:
                return False                        # the poll's own answer tells which
            why = str(e)
        except Unreachable as e:
            why = str(e)
        except (ValueError, TypeError) as e:        # an event this client cannot read:
            say(f"unreadable stream event ({e})")   # reconnecting would only bring it again
            return False
        now = time.monotonic()
        down_since = now if down_since is None else down_since
        if now - down_since >= STREAM_GIVE_UP_S:
            say(f"no stream for {STREAM_GIVE_UP_S:g}s ({why})")
            return False
        say(f"stream lost ({why}); reconnecting in {backoff:g}s after line {last_id}")
        sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_S)


def poll(api, job_id, progress):
    """GET /jobs/{id} every POLL_S until the job ended."""
    down_since = None
    while True:
        try:
            status, job = api.json("GET", f"/jobs/{job_id}")
            if status >= 500:                       # a proxy in front of a restarting service
                raise Unreachable(explain(status, job))
        except Unreachable as e:
            now = time.monotonic()
            down_since = now if down_since is None else down_since
            if now - down_since >= POLL_GIVE_UP_S:
                raise Stop(f"cannot reach the service for {POLL_GIVE_UP_S:g}s: {e}")
            sleep(POLL_S)
            continue
        down_since = None
        if status != 200:
            raise Stop(explain(status, job))
        progress.on_state(job.get("state"), job.get("reason"))
        if job.get("state") in TERMINAL:
            return
        if job.get("telemetry"):
            progress.on_telemetry(job["telemetry"])
        sleep(POLL_S)


def collect(api, job_id, out_root):
    """The ended job's record and every file it lists, into <out>/<job_id>/.
    (job, folder, names that could not be fetched)."""
    status, job = api.json("GET", f"/jobs/{job_id}")
    if status != 200:
        raise Stop(explain(status, job))
    out = os.path.join(out_root, job_id)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "job.json.part"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    os.replace(os.path.join(out, "job.json.part"), os.path.join(out, "job.json"))
    result = job.get("result") or {}
    failed = []
    for name, path in sorted((result.get("files") or {}).items()):
        plain = name == os.path.basename(name) and name not in ("", ".", "..", "job.json")
        if not plain or not api.download(path, os.path.join(out, name)):
            say(f"could not download {name}")
            failed.append(name)
    for name in result.get("missing") or []:            # the service's own word: no guessing
        say(f"missing {name}: the service has no such file for this job")
    return job, out, failed


def report(job_id, state, reason=None, score=None, out_dir=None, not_downloaded=()):
    """The one stdout line a calling program reads."""
    print(json.dumps({"job_id": job_id, "state": state, "reason": reason, "score": score,
                      "out_dir": out_dir, "not_downloaded": list(not_downloaded)}), flush=True)


def track(api, job_id, out_root):
    """Follow a job to its end, fetch what it left, report. The exit code."""
    progress = Progress()
    try:
        if not follow(api, job_id, progress):
            say(f"polling every {POLL_S:g}s instead")
            poll(api, job_id, progress)
        job, out, failed = collect(api, job_id, out_root)
    except KeyboardInterrupt:
        say(f"interrupted. Job {job_id} was NOT killed and keeps running on the service.")
        say(f"  follow it again:  flight.py watch {job_id}")
        say(f"  stop it:          flight.py kill {job_id}")
        report(job_id, progress.state)
        return EXIT_INTERRUPTED
    except (Stop, Unreachable) as e:
        say(str(e) if isinstance(e, Stop) else f"cannot reach the service: {e}")
        if progress.state is not None:              # the job is real: say how to get back to it
            say(f"job {job_id} was last seen {progress.state}:  flight.py watch {job_id}")
        report(job_id, progress.state)
        return e.code if isinstance(e, Stop) else EXIT_UNREACHABLE
    result = job.get("result") or {}
    score = (result.get("score") or {}).get("score")
    say(f"{job['state']}" + (f" ({job.get('reason')}: {job.get('detail')})" if job.get("reason") else "")
        + f"; score {score}; flew {result.get('flight_s')}s; files in {out}")
    report(job_id, job["state"], job.get("reason"), score, out, failed)
    if failed:
        return EXIT_UNREACHABLE
    return EXIT_OK if job["state"] == "done" else EXIT_FAILED


def cmd_run(api, args):
    if args.file and not os.path.isfile(args.file):
        raise Stop(f"no such file: {args.file}")
    deadline = time.monotonic() + args.wait
    while True:
        wait_ready(api, deadline, args.wait)
        status, body = submit(api, args)
        if status == 202:
            break
        if status != 409:
            raise Stop(explain(status, body))
        if time.monotonic() >= deadline:
            raise Stop(f"{explain(status, body)}; still so after {args.wait:g}s")
        say("someone else took the pending slot first; waiting for ready again")
        sleep(READY_POLL_S)
    say(f"job {body['job_id']} accepted")
    return track(api, body["job_id"], args.out)


def cmd_watch(api, args):
    return track(api, args.job_id, args.out)


# -- command line -------------------------------------------------------------

COMMANDS = {"health": cmd_health, "run": cmd_run, "watch": cmd_watch, "kill": cmd_kill}


def parser():
    p = argparse.ArgumentParser(prog="flight.py", description="Submit one image to "
                                "flight-service, follow the flight, fetch the results.")
    p.add_argument("--url", default=os.environ.get("FLIGHT_URL", DEFAULT_URL),
                   help="the service (default: $FLIGHT_URL or %s)" % DEFAULT_URL)
    p.add_argument("--token", default=os.environ.get("RUNNER_TOKEN", ""),
                   help="bearer token (default: $RUNNER_TOKEN)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="can the service take a job now?")
    run = sub.add_parser("run", help="submit an image, follow the flight, fetch the results")
    run.add_argument("image", nargs="?", help="image on a registry, e.g. perkiepai/truck-detector:TAG")
    run.add_argument("--file", help="send this file instead of an image name")
    run.add_argument("--kind", choices=("image", "bundle"),
                     help="what --file is: a `docker save` archive or a build bundle")
    run.add_argument("--name", help="name for the image made from --file")
    run.add_argument("--timeout", type=int, metavar="S", help="flight time limit (flight_timeout_s)")
    run.add_argument("--wait", type=float, default=60, metavar="S",
                     help="how long to wait for the service to be ready (default 60)")
    watch = sub.add_parser("watch", help="follow a job that is already there, fetch its results")
    watch.add_argument("job_id")
    for cmd in (run, watch):
        cmd.add_argument("--out", default="flight-out", metavar="DIR",
                         help="results go to DIR/<job_id>/ (default flight-out)")
    kill = sub.add_parser("kill", help="stop a job")
    kill.add_argument("job_id")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.cmd == "run":
        if bool(args.image) == bool(args.file):
            p.error("run takes an IMAGE or --file, one of them")
        if args.file and not (args.kind and args.name):
            p.error("--file needs --kind image|bundle and --name")
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
        say("interrupted before a job was accepted (if the service did take one, it is in GET /jobs)")
        return EXIT_INTERRUPTED


def _terminate(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)       # a supervisor's stop = Ctrl-C
    sys.exit(main())
