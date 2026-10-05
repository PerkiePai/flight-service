#!/usr/bin/env python3
"""fly_headless.py -- fly a built submission image and check it, no browser.

Does exactly what the website's RUN button does (a {"type": "agent",
"action": "run"} message on /ws), keeps that socket open (AgentRun's
arm -> takeoff -> offboard only advances while a /ws client is connected),
and records what the Agent panel would show plus the drone's track:

    logs/flights/<ts>/panel.log     every line the Agent panel showed
    logs/flights/<ts>/track.jsonl   telemetry at 5 Hz (t, lat, lon, alt, heading,
                                    roll, pitch, ground speed, vz, agent state)

Then it checks the flight against the map's ground truth (map_setup_tool's
drone_map_vehicles.json + the site's georeference): every DETECT's ground
estimate vs the nearest real truck, the drone's closest pass to each truck,
and whether the track stayed on the map.

    conda run --no-capture-output -n drone python \\
        examples/competition-submission/fly_headless.py submission-truck-detector-<ts>
    ... fly_headless.py --analyze logs/flights/<ts>          # re-check an old flight

Needs the `drone` env (websockets) and a running ./sim/run-website.sh.
Stops the agent when the log says DONE, when it exits, or after --timeout.
Truth defaults to the nt-testgs site; the truth is only used here, never
by the agent.
"""
import argparse
import asyncio
import json
import math
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim"))

LINE_RE = re.compile(r"\[\s*([\d.]+)s\] DETECT .*? new #(\d+) at ([-\d.]+), ([-\d.]+)")


async def fly(image, out_dir, timeout, url, kind="docker"):
    import websockets
    panel = open(os.path.join(out_dir, "panel.log"), "w")
    track = open(os.path.join(out_dir, "track.jsonl"), "w")
    seen = None        # panel lines already accounted for
    started = False    # this run has reached arming/running
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "agent", "action": "run",
                                  "kind": kind, "identifier": image}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            t = json.loads(await ws.recv())
            a = t.get("agent") or {}
            track.write(json.dumps({
                "t": round(time.time() - t0, 2), "lat": t.get("lat"),
                "lon": t.get("lon"), "alt": t.get("alt_m"),
                "heading": t.get("heading_deg"), "roll": t.get("roll_deg"),
                "pitch": t.get("pitch_deg"), "gs": t.get("gs"), "vz": t.get("vz"),
                "state": a.get("state")}) + "\n")
            log = a.get("log", [])
            if seen is None:
                # Whatever the panel shows before RUN takes effect is the
                # PREVIOUS run's tail (maybe even its DONE): not ours.
                seen = list(log)
                continue
            started = started or a.get("state") in ("arming", "running")
            # The panel is a sliding window of the last 40 lines: find how much
            # of it we already printed (longest suffix of `seen` = its prefix).
            k = min(len(log), len(seen))
            while k and log[:k] != seen[-k:]:
                k -= 1
            new = log[k:]
            for line in new:
                print(line, flush=True)
                panel.write(line + "\n")
                seen.append(line)
            if started and any(re.search(r"\] DONE\b", l) for l in new):
                break
            if started and a.get("state") in ("error", "stopped"):
                break
        await ws.send(json.dumps({"type": "agent", "action": "stop"}))
        await asyncio.sleep(1)


def load_truth(site_name):
    import sites
    site = sites.get_site(site_name)
    stage_dir = os.path.dirname(str(site.resolved_stage_path()))
    trucks = json.load(open(os.path.join(stage_dir, "drone_map_vehicles.json")))["trucks"]
    report = json.load(open(os.path.join(stage_dir, "drone_map_report.json")))
    lo, hi = report["terrain"]["bounds_min"], report["terrain"]["bounds_max"]
    return site, {t["name"]: tuple(t["center"][:2]) for t in trucks}, (lo[0], hi[0], lo[1], hi[1])


def analyze(out_dir, site_name):
    site, trucks, (xmin, xmax, ymin, ymax) = load_truth(site_name)
    mlat = 110574.0
    mlon = 111320.0 * math.cos(math.radians(site.latitude))

    def enu(lat, lon):
        return (lon - site.longitude) * mlon, (lat - site.latitude) * mlat

    text = open(os.path.join(out_dir, "panel.log")).read()
    print(f"\n=== check vs {site.name} truth ({len(trucks)} trucks) ===")
    print("DONE:", "yes" if re.search(r"\] DONE\b", text) else "NO")
    stops = {name: [] for name in trucks}
    for m in LINE_RE.finditer(text):
        e, n = enu(float(m[3]), float(m[4]))
        dist, name = min((math.hypot(e - x, n - y), k) for k, (x, y) in trucks.items())
        tag = "ok" if dist <= 10 else ("dup/offset" if dist <= 30 else "no truck near")
        if dist <= 30:
            stops[name].append(dist)
        print(f"  DETECT #{m[2]:>2} t={float(m[1]):6.1f}s  est ({e:6.1f}, {n:6.1f})  "
              f"nearest {name} {dist:5.1f} m  [{tag}]")
    for name, hits in stops.items():
        print(f"  {name}: stops {len(hits)}" + (f", best {min(hits):.1f} m" if hits else ""))
    rows = [json.loads(l) for l in open(os.path.join(out_dir, "track.jsonl"))]
    pts = [enu(r["lat"], r["lon"]) for r in rows if r.get("lat") is not None]
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        inside = xmin <= min(xs) and max(xs) <= xmax and ymin <= min(ys) and max(ys) <= ymax
        print(f"  track x {min(xs):.1f}..{max(xs):.1f}  y {min(ys):.1f}..{max(ys):.1f}  "
              f"-> {'on the map' if inside else 'LEFT THE MAP'}")
        for name, (x, y) in trucks.items():
            print(f"  closest pass to {name}: "
                  f"{min(math.hypot(p[0] - x, p[1] - y) for p in pts):.1f} m (horizontal)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image", nargs="?", help="docker image tag, e.g. submission-truck-detector-<ts>")
    ap.add_argument("--analyze", metavar="DIR", help="only re-check a recorded flight")
    ap.add_argument("--site", default="nt-testgs")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--url", default="ws://127.0.0.1:8090/ws")
    ap.add_argument("--kind", default="docker", choices=("docker", "script"),
                    help="script = an uploaded .py in logs/agents (name as the dropdown shows it)")
    a = ap.parse_args()
    if a.analyze:
        analyze(a.analyze, a.site)
        return
    if not a.image:
        ap.error("give an image tag, or --analyze DIR")
    image = a.image if a.kind == "script" or ":" in a.image else a.image + ":latest"
    out_dir = os.path.join(ROOT, "logs", "flights", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    print(f">>> flying {image}; recording to {out_dir}", flush=True)
    asyncio.run(fly(image, out_dir, a.timeout, a.url, a.kind))
    analyze(out_dir, a.site)


if __name__ == "__main__":
    main()
