"""Detection score v0 (design 9.1): the agent's boxes against the map's
real trucks, using only what the competition contract carries -- boxes
plus where the drone was. Deliberately rough: no projection of boxes onto
the ground; a row is "near" when the drone is within max(alt, 10 m) of a
real truck."""
import math
import sys
from pathlib import Path

from .journal import read_jsonl

M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON_EQ = 111320.0


def enu(lat, lon, origin):
    olat, olon = origin
    return ((lon - olon) * M_PER_DEG_LON_EQ * math.cos(math.radians(olat)),
            (lat - olat) * M_PER_DEG_LAT)


class ScoreV0:
    def __init__(self, trucks, origin, min_radius_m=10.0):
        self.trucks, self.origin, self.min_radius_m = dict(trucks), origin, min_radius_m
        self.rows = self.near = 0
        self.found = set()
        self.by_class = {}           # class -> [count, conf sum, conf max]

    def add(self, drone, boxes):
        if not boxes:
            return
        self.rows += 1
        for b in boxes:
            c = self.by_class.setdefault(b["class_name"], [0, 0.0, 0.0])
            c[0] += 1
            c[1] += b["confidence"]
            c[2] = max(c[2], b["confidence"])
        lat, lon = drone.get("lat"), drone.get("lon")
        if lat is None or lon is None or not self.trucks:
            return
        x, y = enu(lat, lon, self.origin)
        radius = max(drone.get("alt_m") or 0.0, self.min_radius_m)
        dist, name = min((math.hypot(x - tx, y - ty), n) for n, (tx, ty) in self.trucks.items())
        if dist <= radius:
            self.near += 1
            self.found.add(name)

    def live(self):
        return {"rows": self.rows, "trucks_found": len(self.found), "trucks_total": len(self.trucks)}

    def result(self, site):
        total = len(self.trucks)
        recall = len(self.found) / total if total else 0.0
        precision = self.near / self.rows if self.rows else 0.0
        f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
        return {"version": "v0", "site": site,
                "boxes": {"rows": self.rows, "total": sum(c[0] for c in self.by_class.values()),
                          "by_class": {n: {"count": c[0], "conf_mean": round(c[1] / c[0], 3),
                                           "conf_max": round(c[2], 3)}
                                       for n, c in self.by_class.items()}},
                "truth": {"trucks_total": total, "trucks_found": len(self.found),
                          "found": sorted(self.found), "rows_near_truck": self.near,
                          "recall": round(recall, 3), "precision": round(precision, 3)},
                "score": round(100 * f1, 1)}


def score_file(path, trucks, origin, site):
    s = ScoreV0(trucks, origin)
    for row in read_jsonl(path):
        if isinstance(row, dict):
            s.add(row.get("drone") or {}, row.get("boxes") or [])
    return s.result(site)


def load_truth(drone_sitl_dir, site):
    """(origin (lat, lon), {truck: (east, north)}) from drone-sitl's own
    fly_headless.load_truth -- the truth its flight checker uses."""
    path = str(Path(drone_sitl_dir) / "examples" / "competition-submission")
    if path not in sys.path:
        sys.path.insert(0, path)
    import fly_headless
    site_obj, trucks, _bounds = fly_headless.load_truth(site)
    return (site_obj.latitude, site_obj.longitude), trucks
