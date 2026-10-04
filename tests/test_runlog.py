from fakes import BOX, frame

from flight_service.journal import read_jsonl
from flight_service.runlog import RunLog, new_lines


def test_new_lines():
    assert new_lines([], ["a", "b"]) == ["a", "b"]
    assert new_lines(["a", "b"], ["a", "b", "c"]) == ["c"]
    assert new_lines(["a", "b", "c"], ["b", "c", "d"]) == ["d"]     # window slid
    assert new_lines(["a"], ["a"]) == []
    assert new_lines(["x"], ["y", "z"]) == ["y", "z"]


def test_frame_splits_into_three_journals(tmp_path):
    f1 = frame("running", ["a"], boxes=[BOX])
    with RunLog(tmp_path) as rl:
        rl.frame(f1)
        rl.frame(frame("running", ["a", "b"]))
        rl.event("state", state="flying")
    assert f1["agent"]["log"] == ["a"]                       # caller's frame untouched
    tel = list(read_jsonl(tmp_path / "telemetry.jsonl"))
    assert len(tel) == 2 and tel[0]["alt_m"] == 20.0 and tel[0]["connected"] is True
    assert tel[0]["agent"] == {"state": "running"} and "t" in tel[0]
    ev = list(read_jsonl(tmp_path / "events.jsonl"))
    assert [e["line"] for e in ev if e["kind"] == "log"] == ["a", "b"]
    assert (ev[-1]["kind"], ev[-1]["state"]) == ("state", "flying")
    det = list(read_jsonl(tmp_path / "detections.jsonl"))
    assert len(det) == 1 and det[0]["boxes"] == [BOX]
    assert det[0]["drone"] == {"lat": 14.0, "lon": 100.0, "alt_m": 20.0, "heading_deg": 90.0}
