"""Keep data/runs under a size cap (design 13.6): delete whole finished
runs, oldest first. Only ever touches folders inside runs_dir."""
import os
import shutil
from pathlib import Path

from .jobs import RUNNING_MARK


def _size(d):
    return sum(os.path.getsize(os.path.join(root, f))
               for root, _, files in os.walk(d) for f in files)


def _age_key(d):
    snap = d / "job.json"
    return (snap if snap.exists() else d).stat().st_mtime


def prune(runs_dir, max_bytes, keep=()):
    runs_dir = Path(runs_dir)
    if max_bytes <= 0 or not runs_dir.is_dir():
        return []
    runs = [d for d in runs_dir.iterdir() if d.is_dir()]
    sizes = {d: _size(d) for d in runs}
    total, deleted = sum(sizes.values()), []
    for d in sorted(runs, key=_age_key):
        if total <= max_bytes:
            break
        if d.name in keep or (d / RUNNING_MARK).exists():
            continue
        shutil.rmtree(d, ignore_errors=True)
        total -= sizes[d]
        deleted.append(d.name)
    return deleted
