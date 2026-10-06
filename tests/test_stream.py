"""stream.events against a journal file and a Job: no HTTP, no worker."""
import asyncio
import json

from conftest import sse_events

from flight_service import stream
from flight_service.jobs import DONE, FAILED, FLYING, PULLING, Job

RESULT = {"ended_by": "agent", "partial": False, "score": {"score": 95.6}}


def a_job(state, **kw):
    return Job("j-1", "perkiepai/x:1", 600, state=state, **kw)


def journal(tmp_path, *lines):
    path = tmp_path / "telemetry.jsonl"
    path.write_bytes(b"".join(lines))
    return path


def row(i):
    return json.dumps({"t": i, "alt_m": 10.0 + i}).encode() + b"\n"


def append(path, data):
    with open(path, "ab") as f:
        f.write(data)


def connect(job, path, script=None, limit=10_000, **kw):
    """Everything one connection receives. `script` is what happens meanwhile:
    {n: fn} runs fn right after the n-th chunk arrived. Stops by itself when
    the stream ends, or after `limit` chunks (the client hangs up)."""
    kw.setdefault("poll_s", 0.001)

    async def go():
        chunks = []
        gen = stream.events(job, path, **kw)
        async for chunk in gen:
            chunks.append(chunk)
            if script and len(chunks) in script:
                script[len(chunks)]()
            if len(chunks) >= limit:
                break
        await gen.aclose()
        return chunks

    return sse_events(b"".join(asyncio.run(asyncio.wait_for(go(), 10))))


def test_a_finished_job_replays_state_every_line_then_end(tmp_path):
    job = a_job(DONE, result=RESULT)
    got = connect(job, journal(tmp_path, row(1), row(2), row(3)))
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 1), ("telemetry", 2),
                                          ("telemetry", 3), ("end", None)]
    assert got[0][2] == {"state": "done", "since": job.summary()["state_since"], "reason": None}
    assert got[2][2] == {"t": 2, "alt_m": 12.0}                 # the line as journaled
    assert got[-1][2] == {"job_id": "j-1", "state": "done", "failed_in": None, "reason": None,
                          "detail": None, "result": RESULT}


def test_last_event_id_skips_the_lines_the_client_already_has(tmp_path):
    path = journal(tmp_path, row(1), row(2), row(3))
    got = connect(a_job(DONE), path, skip=2)
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 3), ("end", None)]
    got = connect(a_job(DONE), path, skip=99)                   # more than the file has
    assert [e for e, _, _ in got] == ["state", "end"]


def test_last_event_id_header():
    for value, want in ((None, 0), ("", 0), ("0", 0), ("5", 5), (" 7 ", 7), ("-1", 0),
                        ("1.5", 0), ("abc", 0), ("1_0", 0), ("٣", 0), ("9" * 5000, 0)):
        assert stream.last_event_id(value) == want, value


def test_tail_holds_a_line_back_until_its_newline(tmp_path):
    path = journal(tmp_path, row(1), b'{"t":')
    tail = stream.Tail(path)
    assert list(tail.lines()) == [(1, row(1)[:-1])]
    assert list(tail.lines()) == []                             # the half line: not yet
    append(path, b' 2}\n' + row(3))
    assert list(tail.lines()) == [(2, b'{"t": 2}'), (3, row(3)[:-1])]
    tail.close()


def test_tail_waits_for_a_journal_that_does_not_exist_yet(tmp_path):
    tail = stream.Tail(tmp_path / "telemetry.jsonl")
    assert list(tail.lines()) == []                             # queued, pulling
    journal(tmp_path, row(1))
    assert list(tail.lines()) == [(1, row(1)[:-1])]
    tail.close()


def test_a_torn_last_line_is_never_sent(tmp_path):
    """A crash leaves at most a torn last line (journal.py): the stream ends without it."""
    got = connect(a_job(FAILED, reason="runner_restarted"), journal(tmp_path, row(1), b'{"t": 2, "al'))
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 1), ("end", None)]


def test_unreadable_lines_are_skipped_but_keep_their_number(tmp_path):
    path = journal(tmp_path, row(1), b"not json\n", b"\n", b'{"t":\r4}\n', row(5))
    got = connect(a_job(DONE), path)
    assert [i for e, i, _ in got if e == "telemetry"] == [1, 5]
    assert [i for e, i, _ in connect(a_job(DONE), path, skip=4) if e == "telemetry"] == [5]


def test_a_live_job_sends_each_state_change_and_each_new_line(tmp_path):
    job, path = a_job(PULLING), tmp_path / "telemetry.jsonl"

    def to(state, **fields):
        def change():
            job.state, job.state_since = state, job.state_since + 1
            for k, v in fields.items():
                setattr(job, k, v)
        return change

    got = connect(job, path, script={
        1: to("booting"),                                       # after "state pulling"
        2: to(FLYING),                                          # after "state booting"
        3: lambda: path.write_bytes(row(1)),                    # after "state flying"
        4: lambda: append(path, row(2)),                        # after "telemetry 1"
        5: to(FAILED, reason="flight_timeout", detail="600 s", failed_in=FLYING,
              result={"ended_by": "timeout"}),                  # after "telemetry 2"
    })
    assert [(e, i) for e, i, _ in got] == [
        ("state", None), ("state", None), ("state", None), ("telemetry", 1), ("telemetry", 2),
        ("state", None), ("end", None)]
    assert [d["state"] for e, _, d in got if e == "state"] == ["pulling", "booting", "flying", "failed"]
    assert got[5][2]["reason"] == "flight_timeout"
    assert got[6][2] == {"job_id": "j-1", "state": "failed", "failed_in": "flying",
                         "reason": "flight_timeout", "detail": "600 s",
                         "result": {"ended_by": "timeout"}}


def test_keepalive_comment_while_there_is_nothing_to_say(tmp_path):
    got = connect(a_job(PULLING), tmp_path / "telemetry.jsonl", limit=3, ping_s=0.01)
    assert [e for e, _, _ in got] == ["state", "ping", "ping"]


def test_no_keepalive_while_lines_flow(tmp_path):
    job, path = a_job(FLYING), journal(tmp_path, row(1))
    more = {n: (lambda n=n: append(path, row(n))) for n in range(2, 30)}
    got = connect(job, path, script=more, limit=30, ping_s=5)
    assert "ping" not in [e for e, _, _ in got]


def test_a_long_backlog_arrives_whole_and_in_order(tmp_path):
    """Lines the size of real ones (~1.3 KB), enough to cross many 64 KB reads."""
    rows = [json.dumps({"t": i, "pad": "x" * 1300}).encode() + b"\n" for i in range(1, 601)]
    got = connect(a_job(DONE), journal(tmp_path, *rows))
    lines = [(i, d["t"]) for e, i, d in got if e == "telemetry"]
    assert lines == [(i, i) for i in range(1, 601)] and got[-1][0] == "end"
