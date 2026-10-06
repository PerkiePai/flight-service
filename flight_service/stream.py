"""GET /jobs/{id}/stream as Server-Sent Events (design 3.1): one flight as
it happens, without polling. Three events:

  state      once on connect, then on every change    {"state","since","reason"}
  telemetry  one per line of telemetry.jsonl          the line as journaled; id = its line number
  end        the job ended and every line was sent    {"job_id","state","failed_in","reason","detail","result"}

Only telemetry carries an id, so a client that comes back with
Last-Event-ID: n gets line n+1 onwards: nothing lost, nothing twice.
No dependency on the worker: it reads the live Job and the run's journal."""
import asyncio
import json
import re
import time

from .jobs import TERMINAL

HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}   # nginx: pass it on at once
POLL_S = 0.2            # how often the journal and the state are looked at
PING_S = 15.0           # a comment line this often while there is nothing to say
CHUNK = 1 << 16
YIELD_EVERY = 100       # lines of a backlog sent before other tasks get a turn


def last_event_id(value):
    """Lines the client already has, from its Last-Event-ID header. Anything
    but a plain non-negative number means: from the start."""
    value = (value or "").strip()
    return int(value) if re.fullmatch(r"[0-9]{1,12}", value) else 0


class Tail:
    """Whole lines of a file that may still be growing, numbered from 1. A
    last line with no newline yet is held back until the rest arrives."""

    def __init__(self, path):
        self.path, self.n = path, 0
        self._f, self._rest = None, b""

    def lines(self):
        """(number, line) for every complete line not handed out before."""
        if self._f is None:
            try:
                self._f = open(self.path, "rb")
            except FileNotFoundError:           # queued, pulling: no journal yet
                return
        while True:
            chunk = self._f.read(CHUNK)
            if not chunk:
                return
            *whole, self._rest = (self._rest + chunk).split(b"\n")
            for line in whole:
                self.n += 1
                yield self.n, line

    def close(self):
        if self._f is not None:
            self._f.close()


def _readable(line):
    """One JSON value that fits one SSE data line. Anything else is skipped
    (as read_jsonl does) but keeps its line number."""
    if b"\r" in line:
        return False
    try:
        json.loads(line)
    except ValueError:
        return False
    return True


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def _event(name, data, eid=None):
    head = f"id: {eid}\n" if eid is not None else ""
    return f"{head}event: {name}\ndata: ".encode() + data + b"\n\n"


async def events(job, path, skip=0, poll_s=POLL_S, ping_s=PING_S):
    """The byte chunks of one connection, until the job ended or the client
    left. A terminal state is set only after the journal is closed and the
    result is built (design 5), so looking at the state first and the file
    second never ends a stream with lines still unsent."""
    tail = Tail(path)
    told = None                     # (state, state_since) the client last heard
    quiet = time.monotonic()        # when anything was last sent
    try:
        while True:
            state, since = job.state, job.state_since
            if (state, since) != told:
                told = (state, since)
                s = job.summary()
                yield _event("state", _json({"state": state, "since": s["state_since"],
                                             "reason": s["reason"]}))
                quiet = time.monotonic()
            sent = 0
            for n, line in tail.lines():
                if n <= skip or not _readable(line):
                    continue
                yield _event("telemetry", line, n)
                quiet = time.monotonic()
                sent += 1
                if sent % YIELD_EVERY == 0:
                    await asyncio.sleep(0)
            if state in TERMINAL:
                yield _event("end", _json({"job_id": job.id, "state": state,
                                           "failed_in": job.failed_in, "reason": job.reason,
                                           "detail": job.detail, "result": job.result}))
                return
            if time.monotonic() - quiet >= ping_s:
                yield b": ping\n\n"
                quiet = time.monotonic()
            await asyncio.sleep(poll_s)
    finally:
        tail.close()
