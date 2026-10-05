// Detection clips: the REC / auto / star controls on the DETECTIONS panel.
// joystick-server records server-side (streaming/det_recorder.py): the
// camera the agent uses + its boxes + the latest log lines, to
// recordings/detections/<date>/<time>_<agent>/detections.mp4. With "auto"
// on (the default) every agent RUN is recorded and the clip ends with it.
// State comes from the /ws telemetry (t.detrec), so a second tab stays honest.
import { setStatus } from './telemetry.js';

const el = id => document.getElementById(id);
let state = { on: false, auto: true };

async function post(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}

export function initDetrec() {
  if (!el('dr-rec')) return;
  el('dr-rec').addEventListener('click', async () => {
    try {
      const j = await post(state.on ? '/detrec/stop' : '/detrec/start');
      if (j.saved) setStatus(`clip saved: ${j.saved.video}`, 'good');
    } catch (e) { setStatus(`clip: ${e.message}`, 'bad'); }
  });
  el('dr-auto').addEventListener('change', async e => {
    try { await post('/detrec/auto', { on: e.target.checked }); }
    catch (err) { setStatus(`clip auto: ${err.message}`, 'bad'); }
  });
  el('dr-star').addEventListener('click', async () => {
    try {
      const j = await post('/detrec/star');
      setStatus(`added to showcase: ${j.showcase}`, 'good');
    } catch (e) { setStatus(`showcase: ${e.message}`, 'bad'); }
  });
}

export function paintDetrec(t) {
  const s = t.detrec;
  if (!s || !el('dr-rec')) return;
  state = s;
  const btn = el('dr-rec');
  btn.classList.toggle('recording', !!s.on);
  if (s.on) {
    const secs = Math.max(0, Math.floor(s.now - s.started_at));
    btn.textContent = `● REC ${String(Math.floor(secs / 60)).padStart(2, '0')}:` +
      String(secs % 60).padStart(2, '0');
  } else {
    btn.textContent = '● REC';
  }
  if (document.activeElement !== el('dr-auto')) el('dr-auto').checked = !!s.auto;
  el('dr-star').disabled = !s.last;
}
