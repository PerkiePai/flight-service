"""The Detections panel as an MP4 -- clips to show people.

Server-side on purpose: the page's canvas draws a frame from the camera
server on another port (:8080, no CORS header), so the browser refuses to
record it, and a browser recording would also need the tab left open. Here
joystick-server pulls the same camera the agent is using, draws the agent's
boxes the way web/js/detections.js does, adds a HUD line on top and the
latest agent log lines in small type along the bottom, and pipes it to
ffmpeg (H.264, so it plays in any browser).

    recordings/                                   (gitignored)
      detections/<YYYY-MM-DD>/<HHMMSS>_<label>/
        detections.mp4    the clip
        panel.log         every agent log line while recording
        meta.json         label, kind, times, frames, event counts, end state
      showcase/           clips picked for showing (the web page's star button)
        README.md         one line per clip -- edit to describe them

Nothing here knows about the model: boxes arrive already computed (the
organizer runs no model -- see streaming/detections.py).
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np

CLIP_W, CLIP_H = 640, 400          # the camera streams' size (drone_setup STREAM_W/H)
PANEL_H = 80                       # log panel under the frame
LOG_LINES = 4
FPS = 10
EVENT_TAGS = ("DETECT", "APPROACH", "INSPECT", "GIVEUP", "ABORT", "SAFEHOLD", "DONE")

GREEN = (80, 255, 51)              # BGR of the page's #3f6
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _fit(text, scale, width):
    """Trim `text` so it fits `width` px at `scale`."""
    if cv2.getTextSize(text, FONT, scale, 1)[0][0] <= width:
        return text
    while text and cv2.getTextSize(text + "...", FONT, scale, 1)[0][0] > width:
        text = text[:-1]
    return text + "..."


def screen_lines(log_lines):
    """What the bottom strip shows: the log minus STATUS, which repeats every
    5 s and would push the events (DETECT, INSPECT, ...) off the strip.
    panel.log keeps every line."""
    return [l for l in log_lines if not re.search(r"\] STATUS\b", l)]


def hud_text(hud, n_boxes):
    """Top line. The time is the CLIP's (REC mm:ss): log lines carry the
    agent's own clock, which starts later (after arming and takeoff)."""
    parts = []
    if hud.get("t") is not None:
        secs = int(hud["t"])
        parts.append(f"REC {secs // 60:02d}:{secs % 60:02d}")
    if hud.get("alt") is not None:
        parts.append(f"alt {hud['alt']:.1f} m")
    if hud.get("heading") is not None:
        parts.append(f"hdg {hud['heading']:.0f}")
    parts.append(f"boxes {n_boxes}")
    if hud.get("label"):
        parts.append(hud["label"])
    return "  |  ".join(parts)


def render_frame(frame_bgr, boxes, hud, log_lines):
    """One clip frame: camera (resized to CLIP_W x CLIP_H) + boxes + a HUD
    line on top + the last LOG_LINES log lines on a dark strip below."""
    fh, fw = frame_bgr.shape[:2]
    sx, sy = CLIP_W / fw, CLIP_H / fh
    img = frame_bgr if (fw, fh) == (CLIP_W, CLIP_H) else cv2.resize(frame_bgr, (CLIP_W, CLIP_H))
    out = np.zeros((CLIP_H + PANEL_H, CLIP_W, 3), np.uint8)
    out[:CLIP_H] = img

    for b in boxes or ():
        try:
            x1, y1, x2, y2 = (float(v) for v in b["bbox"])
            label = f"{b.get('class_name', '?')} {round(float(b.get('confidence', 0)) * 100)}%"
        except (KeyError, TypeError, ValueError):
            continue
        p1 = (int(x1 * sx), int(y1 * sy))
        p2 = (int(x2 * sx), int(y2 * sy))
        cv2.rectangle(out, p1, p2, GREEN, 2)
        cv2.putText(out, label, (p1[0] + 2, max(p1[1] - 4, 12)), FONT, 0.5, GREEN, 1, cv2.LINE_AA)

    text = _fit(hud_text(hud, len(boxes or ())), 0.45, CLIP_W - 12)
    cv2.rectangle(out, (0, 0), (CLIP_W, 20), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 14), FONT, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.rectangle(out, (0, CLIP_H), (CLIP_W, CLIP_H + PANEL_H), (24, 24, 24), -1)
    for i, line in enumerate(screen_lines(log_lines)[-LOG_LINES:]):
        y = CLIP_H + 16 + i * 18
        cv2.putText(out, _fit(line, 0.38, CLIP_W - 12), (6, y), FONT, 0.38,
                    (215, 215, 215), 1, cv2.LINE_AA)
    return out


class _FfmpegWriter:
    """Raw BGR frames on stdin -> H.264 MP4 (browser-playable, faststart)."""

    def __init__(self, path, w, h, fps):
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
             "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", path],
            stdin=subprocess.PIPE)

    def write(self, frame):
        self.proc.stdin.write(frame.tobytes())

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=30)


class _Cv2Writer:
    """Fallback without ffmpeg: plays in VLC, not in every browser."""

    def __init__(self, path, w, h, fps):
        self.w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    def write(self, frame):
        self.w.write(frame)

    def close(self):
        self.w.release()


def _writer(path, w, h, fps):
    return (_FfmpegWriter if shutil.which("ffmpeg") else _Cv2Writer)(path, w, h, fps)


def _label(text):
    text = re.sub(r":latest$", "", os.path.basename(text or "manual"))
    text = re.sub(r"\.py$", "", text)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:60] or "manual"


class DetRecorder:
    """One recording at a time. `source_factory()` returns something with
    .latest() (RGB ndarray or None), .select(camera) and .stop() -- in the
    server that is competition.frames.MjpegFrames. boxes_fn / telem_fn /
    camera_fn are read every frame."""

    def __init__(self, root, source_factory, boxes_fn, telem_fn, camera_fn,
                 fps=FPS, writer_factory=_writer):
        self.root = root
        self.source_factory = source_factory
        self.boxes_fn, self.telem_fn, self.camera_fn = boxes_fn, telem_fn, camera_fn
        self.fps = fps
        self.writer_factory = writer_factory
        self.auto = True                   # record every agent run by default
        self._lock = threading.Lock()
        self._on = False
        self._thread = None
        self._stop = threading.Event()
        self._lines = []
        self._meta = {}
        self._dir = None
        self._last = None                  # the last finished clip's mp4
        self._frames = self._frames_with_boxes = 0

    # -- control -------------------------------------------------------------

    def start(self, label, meta=None):
        """Start recording (no-op if already on). Returns the clip folder."""
        with self._lock:
            if self._on:
                return self._dir
            now = datetime.datetime.now()
            name = _label(label)
            self._dir = os.path.join(self.root, "detections", now.strftime("%Y-%m-%d"),
                                     f"{now.strftime('%H%M%S')}_{name}")
            os.makedirs(self._dir, exist_ok=True)
            self._meta = {"label": name, "identifier": label, **(meta or {}),
                          "started": now.isoformat(timespec="seconds"),
                          "started_at": time.time(), "fps": self.fps}
            self._lines = []
            self._frames = self._frames_with_boxes = 0
            self._on = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return self._dir

    def stop(self, extra_meta=None):
        """Finish the clip; returns {"dir", "video"} or None if not recording."""
        with self._lock:
            if not self._on:
                return None
            self._on = False
            thread, d = self._thread, self._dir
        self._stop.set()
        thread.join(timeout=30)
        video = os.path.join(d, "detections.mp4")
        with self._lock:
            lines = list(self._lines)
            meta = dict(self._meta, **(extra_meta or {}))
            meta.update(ended=datetime.datetime.now().isoformat(timespec="seconds"),
                        duration_s=round(time.time() - meta["started_at"], 1),
                        frames=self._frames, frames_with_boxes=self._frames_with_boxes,
                        events={tag: sum(1 for l in lines if re.search(r"\] " + tag + r"\b", l))
                                for tag in EVENT_TAGS},
                        files=["detections.mp4", "panel.log", "meta.json"])
            self._last = video
        with open(os.path.join(d, "panel.log"), "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(meta, f, indent=1)
        return {"dir": d, "video": video}

    def note(self, line):
        """An agent log line; kept only while recording."""
        with self._lock:
            if self._on:
                self._lines.append(line)

    def status(self):
        with self._lock:
            return {"on": self._on, "auto": self.auto,
                    "label": self._meta.get("label") if self._on else None,
                    "started_at": self._meta.get("started_at") if self._on else None,
                    "frames": self._frames if self._on else None,
                    "last": self._last, "now": time.time()}

    def star(self):
        """Copy the last clip into showcase/ and list it in its README.
        Returns the new path, or None if nothing has been recorded yet."""
        with self._lock:
            last = self._last
        if not last or not os.path.isfile(last):
            return None
        show = os.path.join(self.root, "showcase")
        os.makedirs(show, exist_ok=True)
        clip_dir = os.path.dirname(last)
        date = os.path.basename(os.path.dirname(clip_dir))
        name = f"{date}_{os.path.basename(clip_dir)}.mp4"
        dst = os.path.join(show, name)
        shutil.copy2(last, dst)
        readme = os.path.join(show, "README.md")
        if not os.path.isfile(readme):
            with open(readme, "w") as f:
                f.write("# Showcase clips\n\nPicked with the star button on the "
                        "Detections panel. Source folder (panel.log, meta.json) in "
                        "brackets -- replace the TODO with what the clip shows.\n\n")
        with open(readme, "a") as f:
            rel = os.path.relpath(clip_dir, self.root)
            f.write(f"- `{name}` ({rel}) -- TODO: describe\n")
        return dst

    def list_clips(self, limit=50):
        """Recorded clips, newest first, paths relative to the root."""
        base = os.path.join(self.root, "detections")
        out = []
        if os.path.isdir(base):
            for date in sorted(os.listdir(base), reverse=True):
                for clip in sorted(os.listdir(os.path.join(base, date)), reverse=True):
                    d = os.path.join(base, date, clip)
                    mp4, meta = os.path.join(d, "detections.mp4"), os.path.join(d, "meta.json")
                    if not os.path.isfile(mp4):
                        continue
                    m = {}
                    if os.path.isfile(meta):
                        try:
                            m = json.load(open(meta))
                        except (OSError, ValueError):
                            m = {}
                    out.append({"video": os.path.relpath(mp4, self.root),
                                "log": os.path.relpath(os.path.join(d, "panel.log"), self.root),
                                "started": m.get("started", f"{date} {clip[:6]}"),
                                "label": m.get("label", clip[7:]),
                                "duration_s": m.get("duration_s"),
                                "events": m.get("events", {}),
                                "end_state": m.get("end_state")})
                    if len(out) >= limit:
                        return out
        return out

    # -- the recording thread -------------------------------------------------

    def _run(self):
        src = self.source_factory()
        camera = None
        writer = self.writer_factory(os.path.join(self._dir, "detections.mp4"),
                                     CLIP_W, CLIP_H + PANEL_H, self.fps)
        period = 1.0 / self.fps
        t0 = time.time()
        nxt = t0
        try:
            while not self._stop.is_set():
                cam = self.camera_fn() or "oblique"
                if cam != camera:
                    camera = cam
                    src.select(cam)
                rgb = src.latest()
                if rgb is not None:
                    boxes = self.boxes_fn() or []
                    tel = self.telem_fn() or {}
                    with self._lock:
                        lines = screen_lines(self._lines[-60:])
                        label = self._meta.get("label")
                    frame = render_frame(
                        np.ascontiguousarray(rgb[:, :, ::-1]), boxes,
                        {"t": time.time() - t0, "alt": tel.get("alt_m"),
                         "heading": tel.get("heading_deg"), "label": label}, lines)
                    writer.write(frame)
                    with self._lock:
                        self._frames += 1
                        self._frames_with_boxes += 1 if boxes else 0
                nxt += period
                self._stop.wait(max(0.0, nxt - time.time()))
        finally:
            writer.close()
            src.stop()
