import json
from math import cos, radians

import pytest

from flight_service.score import ScoreV0, enu, score_file

ORIGIN = (14.0, 100.0)
TRUCKS = {"A": (0.0, 0.0), "B": (100.0, 0.0)}
BOX = {"class_name": "Truck", "confidence": 0.8, "bbox": [0, 0, 1, 1]}


def at(east, north, alt=20.0):
    return {"lat": ORIGIN[0] + north / 110574.0,
            "lon": ORIGIN[1] + east / (111320.0 * cos(radians(ORIGIN[0]))), "alt_m": alt}


def test_enu_round_trip():
    p = at(30, -40)
    e, n = enu(p["lat"], p["lon"], ORIGIN)
    assert e == pytest.approx(30, abs=0.01) and n == pytest.approx(-40, abs=0.01)


def test_one_truck_found_one_false_alarm():
    s = ScoreV0(TRUCKS, ORIGIN)
    s.add(at(5, 5), [BOX])
    s.add(at(500, 500), [BOX])
    s.add(at(100, 0), [])
    r = s.result("nt-testgs")
    assert r["boxes"]["rows"] == 2 and r["boxes"]["total"] == 2
    assert r["boxes"]["by_class"]["Truck"] == {"count": 2, "conf_mean": 0.8, "conf_max": 0.8}
    assert r["truth"]["found"] == ["A"] and r["truth"]["recall"] == 0.5 and r["truth"]["precision"] == 0.5
    assert r["score"] == 50.0
    assert s.live() == {"rows": 2, "trucks_found": 1, "trucks_total": 2}


def test_radius_grows_with_altitude():
    s = ScoreV0(TRUCKS, ORIGIN)
    s.add(at(30, 0, alt=40.0), [BOX])
    s.add(at(30, 0, alt=5.0), [BOX])
    assert s.result("x")["truth"]["rows_near_truck"] == 1


def test_no_truth_or_no_boxes_scores_zero(tmp_path):
    assert ScoreV0({}, ORIGIN).result("x")["score"] == 0.0
    assert score_file(tmp_path / "missing.jsonl", TRUCKS, ORIGIN, "x")["score"] == 0.0


def test_score_file_reads_detection_journal(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps({"t": 1, "drone": at(0, 0), "boxes": [BOX]}) + "\ngarbage\n"
                 + json.dumps({"t": 2, "drone": at(100, 2), "boxes": [BOX]}) + "\n")
    r = score_file(p, TRUCKS, ORIGIN, "x")
    assert r["truth"]["found"] == ["A", "B"] and r["score"] == 100.0

