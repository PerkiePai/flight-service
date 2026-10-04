"""Crash-safe files for data that arrives over time (design 13.2-13.3).
No dependency on the rest of flight-service: copy it anywhere.

  Journal       append-only JSON Lines. Each record is one line, flushed at
                once; fsync'd at most every `fsync_every_s`. A crash loses
                at most a torn last line.
  read_jsonl    reads one back, skipping lines that do not parse.
  write_atomic  replaces a whole file (snapshot) so no reader ever sees
                half of it: write a temp file, fsync, os.replace.
"""
import json
import os
import time
from pathlib import Path


class Journal:
    def __init__(self, path, fsync_every_s=1.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fsync_every_s = fsync_every_s
        self._f = open(self.path, "a", encoding="utf-8")
        self._synced = time.monotonic()
        self.count = 0

    def append(self, record):
        self._f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._f.flush()
        self.count += 1
        if time.monotonic() - self._synced >= self.fsync_every_s:
            os.fsync(self._f.fileno())
            self._synced = time.monotonic()

    def close(self):
        if not self._f.closed:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def read_jsonl(path):
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return
    with f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        payload = data
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
