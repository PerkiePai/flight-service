import json

from flight_service import journal
from flight_service.journal import Journal, read_jsonl, write_atomic


def test_append_is_readable_at_once(tmp_path):
    p = tmp_path / "a.jsonl"
    with Journal(p) as j:
        j.append({"n": 1})
        j.append({"n": 2, "s": "ไทย"})
        assert j.count == 2
        assert [r["n"] for r in read_jsonl(p)] == [1, 2]       # flushed, not yet closed
    assert list(read_jsonl(p))[1]["s"] == "ไทย"


def test_reopen_appends(tmp_path):
    p = tmp_path / "a.jsonl"
    with Journal(p) as j:
        j.append({"n": 1})
    with Journal(p) as j:
        j.append({"n": 2})
    assert [r["n"] for r in read_jsonl(p)] == [1, 2]


def test_torn_last_line_and_missing_file(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"n": 1}\n{"n": 2, "tr')
    assert [r["n"] for r in read_jsonl(p)] == [1]
    assert list(read_jsonl(tmp_path / "none.jsonl")) == []


def test_fsync_is_rate_limited(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(journal.os, "fsync", lambda fd: calls.append(fd))
    j = Journal(tmp_path / "a.jsonl", fsync_every_s=3600)
    for i in range(100):
        j.append({"i": i})
    assert calls == []
    j.close()
    assert len(calls) == 1
    j2 = Journal(tmp_path / "b.jsonl", fsync_every_s=0)
    j2.append({})
    assert len(calls) == 2
    j2.close()


def test_write_atomic(tmp_path):
    p = tmp_path / "s.json"
    write_atomic(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    write_atomic(p, "text\n")
    assert p.read_text() == "text\n"
    write_atomic(p, b"\x00\x01")
    assert p.read_bytes() == b"\x00\x01"
    assert [x.name for x in tmp_path.iterdir()] == ["s.json"]
