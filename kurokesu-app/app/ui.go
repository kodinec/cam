package main

import (
	"fmt"
	"net/http"
)

func serveUI(cfg Config) http.HandlerFunc {
	page := uiHTML(cfg)
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(page))
	}
}

func uiHTML(cfg Config) string {
	return fmt.Sprintf(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>kurokesu zoom helper</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-a: #f4efe6;
      --bg-b: #dae8f6;
      --ink: #1e2a36;
      --muted: #5a6b7b;
      --line: #b7c4cf;
      --card: rgba(255,255,255,0.84);
      --accent: #1f8f6a;
      --accent-2: #1364b8;
      --danger: #b4433f;
      --shadow: 0 16px 40px rgba(18, 36, 54, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Space Grotesk", "Trebuchet MS", "Segoe UI", sans-serif;
      background:
        radial-gradient(900px 380px at -10%% -20%%, #f7dcb9 0%%, transparent 62%%),
        radial-gradient(1000px 460px at 110%% 10%%, #b9d8fb 0%%, transparent 60%%),
        linear-gradient(135deg, var(--bg-a), var(--bg-b));
      min-height: 100vh;
    }
    .wrap {
      width: min(100%%, 1680px);
      margin: 0 auto;
      padding: clamp(10px, 1.4vw, 22px);
    }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
      padding: clamp(10px, 1.1vw, 16px);
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      box-shadow: var(--shadow);
    }
    .title {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    h1 { margin: 0; font-size: clamp(20px, 2.2vw, 34px); letter-spacing: 0.2px; }
    .panel {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px 14px;
      align-items: start;
      padding: clamp(10px, 1vw, 14px);
      border-bottom: 1px solid var(--line);
      background: #ffffffb5;
    }
    .panel-head h2 { margin: 0; font-size: clamp(15px, 1.35vw, 24px); line-height: 1.2; }
    .panel-tools { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .stream-wrap {
      background: #0a1117;
      position: relative;
      width: 100%%;
      aspect-ratio: 16 / 9;
      min-height: clamp(260px, 42vw, 78vh);
      border-bottom: 1px solid var(--line);
    }
    .stream-frame {
      position: absolute;
      inset: 0;
      width: 100%%;
      height: 100%%;
      border: 0;
      display: block;
      background: #000;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      padding: clamp(10px, 1vw, 14px);
      border-top: 1px dashed #c4d0d8;
    }
    .controls:first-of-type { border-top: none; }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 600;
      font-size: clamp(14px, 1.05vw, 18px);
    }
    button.accent { background: var(--accent); color: #fff; border-color: var(--accent); }
    button.blue { background: var(--accent-2); color: #fff; border-color: var(--accent-2); }
    button.danger { background: var(--danger); color: #fff; border-color: var(--danger); }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    input[type='number'] {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 8px;
      padding: 7px 8px;
      width: clamp(82px, 7vw, 120px);
      font-family: inherit;
      font-weight: 600;
      font-size: clamp(14px, 1vw, 17px);
    }
    .small { color: var(--muted); font-size: 12px; }
    .badge {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      background: #ffffffcc;
      font-size: 12px;
      color: var(--muted);
    }
    .badge-online {
      color: #0d5b45;
      background: rgba(31, 143, 106, 0.14);
      border-color: rgba(31, 143, 106, 0.35);
    }
    .badge-offline {
      color: #8d2d2a;
      background: rgba(180, 67, 63, 0.14);
      border-color: rgba(180, 67, 63, 0.35);
    }
    .badge-checking {
      color: var(--muted);
      background: #ffffffcc;
    }
    .log {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      background: var(--card);
      box-shadow: var(--shadow);
    }
    .log-head {
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: #ffffffb0;
      font-size: 13px;
      color: var(--muted);
    }
    pre {
      margin: 0;
      padding: 12px 14px;
      min-height: 170px;
      max-height: 320px;
      overflow: auto;
      background: #0f1921;
      color: #9be6b4;
      font-size: 12px;
      line-height: 1.45;
    }
    @media (max-width: 960px) {
      .head, .panel-head { grid-template-columns: 1fr; }
      .head { align-items: flex-start; flex-direction: column; }
      .panel-tools { justify-content: flex-start; }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header class="head">
    <div class="title">
      <h1>kurokesu zoom helper</h1>
    </div>
  </header>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Camera</h2>
      </div>
      <div class="panel-tools">
        <span id="cameraBadge" class="badge">camera checking</span>
        <button onclick="reloadStream()">Reload</button>
        <button onclick="openStream()">Open</button>
        <button class="blue" onclick="fullscreenStream()">Fullscreen</button>
      </div>
    </div>

    <div class="stream-wrap">
      <iframe id="rtcFrame" class="stream-frame" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>
    </div>

    <div class="controls">
      <button id="homeBtn" class="danger" onclick="camHome()">Start Flow + Step0</button>
      <button onclick="camStatus()">Status</button>
      <span id="mapInfo" class="small">Map: loading...</span>
    </div>

    <div class="controls">
      <button id="zoomMinus" onclick="camZoomDelta(-1)">Zoom -</button>
      <button id="zoomPlus" class="accent" onclick="camZoomDelta(1)">Zoom +</button>
      <label>Set step</label>
      <input id="zoomSet" type="number" min="0" max="7" value="0" />
      <button id="zoomApply" class="blue" onclick="camZoomSet()">Apply</button>
    </div>

    <div class="controls">
      <button id="focusMinus" onclick="camFocusDelta(-1)">Focus -</button>
      <button id="focusPlus" class="accent" onclick="camFocusDelta(1)">Focus +</button>
      <label>Set Y</label>
      <input id="focusSet" type="number" step="0.05" value="0.00" />
      <button id="focusApply" class="blue" onclick="camFocusSet()">Apply</button>
      <span id="positionInfo" class="small"></span>
    </div>
  </section>

  <section class="log">
    <div class="log-head">API log</div>
    <pre id="log">{}</pre>
  </section>
</div>

<script>
let streamFrameReady = false;

function rtcURL() {
  return '/cam1/';
}

function setCameraBadge(mode) {
  const badge = document.getElementById('cameraBadge');
  if (!badge) return;
  badge.classList.remove('badge-online', 'badge-offline', 'badge-checking');
  if (mode === true) {
    badge.textContent = 'camera online';
    badge.classList.add('badge-online');
    return;
  }
  if (mode === false) {
    badge.textContent = 'camera offline';
    badge.classList.add('badge-offline');
    return;
  }
  badge.textContent = 'camera checking';
  badge.classList.add('badge-checking');
}

function frameStatusLooksOffline() {
  const frame = document.getElementById('rtcFrame');
  if (!frame || !streamFrameReady) return null;
  try {
    const doc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
    const text = doc && doc.body ? String(doc.body.innerText || '').toLowerCase() : '';
    if (text.includes('error:') || text.includes('retrying') || text.includes('bad status') || text.includes('stream not found')) {
      return true;
    }
    return false;
  } catch (_) {
    return null;
  }
}

async function probeCameraStatus() {
  try {
    const r = await fetch(rtcURL(), { method: 'GET', cache: 'no-store' });
    if (!r.ok) {
      setCameraBadge(false);
      return false;
    }
  } catch (_) {
    setCameraBadge(false);
    return false;
  }

  const offline = frameStatusLooksOffline();
  if (offline === true) {
    setCameraBadge(false);
    return false;
  }
  if (offline === false) {
    setCameraBadge(true);
    return true;
  }
  setCameraBadge(null);
  return null;
}

function bindStream() {
  const url = rtcURL();
  const frame = document.getElementById('rtcFrame');
  if (frame) {
    frame.addEventListener('load', () => {
      streamFrameReady = true;
      probeCameraStatus();
    });
    frame.addEventListener('error', () => {
      streamFrameReady = false;
      setCameraBadge(false);
    });
  }
  if (frame && frame.src !== window.location.origin + url) {
    frame.src = url;
  }
}

function openStream() {
  window.open(rtcURL(), '_blank', 'noopener');
}

function reloadStream() {
  const frame = document.getElementById('rtcFrame');
  if (!frame) return;
  streamFrameReady = false;
  setCameraBadge(null);
  frame.src = 'about:blank';
  setTimeout(() => {
    frame.src = rtcURL() + '?_ts=' + Date.now();
  }, 120);
}

async function fullscreenStream() {
  const frame = document.getElementById('rtcFrame');
  if (!frame) return;
  try {
    if (frame.requestFullscreen) {
      await frame.requestFullscreen();
      return;
    }
  } catch (_) {}
  openStream();
}

async function api(url, method, body) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    const txt = await r.text();
    let data;
    try { data = JSON.parse(txt); } catch (_) { data = { raw: txt }; }
    data.httpStatus = r.status;
    data._url = url;
    document.getElementById('log').textContent = JSON.stringify(data, null, 2);
    return data;
  } catch (e) {
    const data = {
      error: e && e.message ? e.message : 'network error',
      httpStatus: 0,
      _url: url
    };
    document.getElementById('log').textContent = JSON.stringify(data, null, 2);
    return data;
  }
}

function setControlsEnabled(enabled) {
  for (const id of ['zoomMinus', 'zoomPlus', 'zoomSet', 'zoomApply', 'focusMinus', 'focusPlus', 'focusSet', 'focusApply']) {
    const el = document.getElementById(id);
    if (el) el.disabled = !enabled;
  }
}

function updateState(data) {
  if (!data) return data;
  const info = document.getElementById('mapInfo');
  const pos = document.getElementById('positionInfo');
  const zoomSet = document.getElementById('zoomSet');
  const focusSet = document.getElementById('focusSet');
  const state = data.mapState || (data.step0 && data.step0.mapState) || null;

  if (!data.available && data.available !== undefined) {
    if (info) info.textContent = data.error || 'PTZ is unavailable';
    setControlsEnabled(false);
    return data;
  }

  if (!state || !state.enabled) {
    if (info) info.textContent = 'Map is not configured';
    setControlsEnabled(false);
    return data;
  }

  const idx = Number(state.currentIndex ?? data.mapIndex ?? 0);
  const max = Number(state.maxIndex ?? 0);
  const homed = Boolean(state.homed);
  const coord = state.coordSpace || 'wpos';

  if (zoomSet) {
    zoomSet.max = String(max);
    zoomSet.value = String(idx);
  }
  if (info) {
    info.textContent = homed ? ('Map ready | ' + coord.toUpperCase()) : 'Homing required';
  }
  setControlsEnabled(homed);

  let currentY = null;
  if (coord === 'mpos' && typeof data.mposY === 'number') currentY = data.mposY;
  if (coord === 'wpos' && typeof data.wposY === 'number') currentY = data.wposY;
  if (typeof data.targetY === 'number') currentY = data.targetY;
  if (focusSet && currentY !== null) {
    focusSet.value = Number(currentY).toFixed(2);
  }

  const parts = [];
  if (typeof data.wposX === 'number' && typeof data.wposY === 'number') parts.push('WPos X=' + data.wposX.toFixed(3) + ' Y=' + data.wposY.toFixed(3));
  if (typeof data.mposX === 'number' && typeof data.mposY === 'number') parts.push('MPos X=' + data.mposX.toFixed(3) + ' Y=' + data.mposY.toFixed(3));
  if (data.limits) parts.push('Limits=' + data.limits);
  if (pos) pos.textContent = parts.join(' | ');
  return data;
}

function camHome() { return api('/api/home', 'POST', {}).then(updateState); }
function camStatus() { return api('/api/status', 'GET').then(updateState); }
function camZoomDelta(delta) { return api('/api/zoom', 'POST', { delta }).then(updateState); }
function camZoomSet() {
  const set = Number(document.getElementById('zoomSet').value);
  return api('/api/zoom', 'POST', { set }).then(updateState);
}
function camFocusDelta(delta) { return api('/api/focus', 'POST', { delta }).then(updateState); }
function camFocusSet() {
  const set = Number(document.getElementById('focusSet').value);
  return api('/api/focus', 'POST', { set }).then(updateState);
}

bindStream();
camStatus();
probeCameraStatus();
setInterval(() => { camStatus(); }, 15000);
setInterval(() => { probeCameraStatus(); }, 5000);
</script>
</body>
</html>`,
	)
}
