"""Build a run's results from its journals -- the one way every job ends:
the agent finished, timeout, error, kill, or a runner restart (design
13.2). Reads only what is on disk and rewrites every derived file, so
running it twice gives the same result."""
import asyncio
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import score as scoring
from .jobs import FILES, RUNNING_MARK
from .journal import read_jsonl, write_atomic

CLIP_FILES = ("detections.mp4", "meta.json")
# track.jsonl keeps fly_headless's row shape so its analyze() reads our runs.
TRACK_KEYS = (("lat", "lat"), ("lon", "lon"), ("alt", "alt_m"), ("heading", "heading_deg"),
              ("roll", "roll_deg"), ("pitch", "pitch_deg"), ("gs", "gs"), ("vz", "vz"),
              ("mode", "mode"), ("armed", "armed"))


def _derive_track(run_dir):
    rows, t0 = [], None
    for r in read_jsonl(run_dir / "telemetry.jsonl"):
        t0 = r.get("t", 0.0) if t0 is None else t0
        rows.append({"t": round(r.get("t", t0) - t0, 2),
                     **{k: r.get(src) for k, src in TRACK_KEYS},
                     "state": (r.get("agent") or {}).get("state")})
    write_atomic(run_dir / "track.jsonl", "".join(json.dumps(x) + "\n" for x in rows))
    return rows


def _derive_panel(run_dir):
    lines = [e["line"] for e in read_jsonl(run_dir / "events.jsonl")
             if isinstance(e, dict) and e.get("kind") == "log" and "line" in e]
    write_atomic(run_dir / "panel.log", "".join(l + "\n" for l in lines))


def _summarise(rows):
    pts = [(r["lat"], r["lon"]) for r in rows if r["lat"] is not None and r["lon"] is not None]
    dist = 0.0
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        dist += math.hypot((lo2 - lo1) * 111320.0 * math.cos(math.radians(la1)),
                           (la2 - la1) * 110574.0)
    alts = [r["alt"] for r in rows if r["alt"] is not None]
    return {"track_points": len(rows), "flight_s": rows[-1]["t"] if rows else 0.0,
            "distance_m": round(dist, 1), "max_alt_m": round(max(alts), 1) if alts else None}


async def wait_clip(status_fn, since, timeout, poll=1.0):
    """det_recorder's clip folder for this run once finished (meta.json is
    written last), or None after `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = await status_fn()
        last = (st or {}).get("last")
        if st and not st.get("on") and last:
            meta = Path(last).parent / "meta.json"
            if meta.exists() and meta.stat().st_mtime >= since:
                return meta.parent
        await asyncio.sleep(poll)
    return None


def run_analysis(run_dir, drone_sitl_dir, site, timeout=60):
    """drone-sitl's own flight checker, for humans (not scored)."""
    examples = Path(drone_sitl_dir) / "examples" / "competition-submission"
    if not (examples / "fly_headless.py").exists():
        return
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import fly_headless; "
            "fly_headless.analyze(sys.argv[2], sys.argv[3])")
    try:
        p = subprocess.run([sys.executable, "-c", code, str(examples), str(run_dir), site],
                           capture_output=True, text=True, timeout=timeout)
        write_atomic(Path(run_dir) / "analysis.txt", p.stdout + p.stderr)
    except (OSError, subprocess.TimeoutExpired):
        pass


def finalize(run_dir, *, job_id, ended_by, outcome=None, detail="", done_line=False,
             truth=((0.0, 0.0), {}), site="nt-testgs", clip_dir=None, drone_sitl_dir=None):
    run_dir = Path(run_dir)
    rows = _derive_track(run_dir)
    _derive_panel(run_dir)
    if clip_dir is not None:
        for name in CLIP_FILES:
            if (Path(clip_dir) / name).exists():
                shutil.copy2(Path(clip_dir) / name, run_dir / name)
    origin, trucks = truth
    sc = scoring.score_file(run_dir / "detections.jsonl", trucks, origin, site)
    write_atomic(run_dir / "score.json", sc)
    if drone_sitl_dir is not None and rows:
        run_analysis(run_dir, drone_sitl_dir, site)
    result = {"ended_by": ended_by, "partial": ended_by != "agent", "outcome": outcome,
              "detail": detail, "done_line": done_line, **_summarise(rows),
              "score": {"version": sc["version"], "score": sc["score"],
                        **{k: sc["truth"][k] for k in ("recall", "precision",
                                                       "trucks_found", "trucks_total")}}}
    present = [n for n in FILES if n == "result.json" or (run_dir / n).exists()]
    result["files"] = {n: f"/jobs/{job_id}/files/{n}" for n in present}
    result["missing"] = [n for n in FILES if n not in present and n != "analysis.txt"]
    write_atomic(run_dir / "result.json", result)
    (run_dir / RUNNING_MARK).unlink(missing_ok=True)
    return result
