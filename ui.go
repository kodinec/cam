package main

import (
	"fmt"
	"net/http"
	"strings"
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
	esc := func(s string) string {
		r := strings.NewReplacer(
			"&", "&amp;",
			"<", "&lt;",
			">", "&gt;",
			`"`, "&quot;",
			"'", "&#39;",
		)
		return r.Replace(s)
	}
	max := cfg.PTZZoomMax

	return fmt.Sprintf(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>cam helper v.001</title>
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
      width: min(100%%, 1880px);
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
    .ver {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 10px;
      font-size: 12px;
      color: var(--muted);
      background: #ffffffcc;
    }
    .modes { display: flex; gap: 8px; flex-wrap: wrap; }
    .mode {
      border: 1px solid var(--line);
      background: #ffffffdd;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 600;
    }
    .mode.active {
      border-color: var(--accent-2);
      background: var(--accent-2);
      color: #fff;
    }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .grid.single { grid-template-columns: 1fr; }
    .panel {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel.hidden { display: none; }
    .panel-head {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px 14px;
      align-items: start;
      padding: clamp(10px, 1vw, 14px);
      border-bottom: 1px solid var(--line);
      background: #ffffffb5;
    }
    .panel-head h2 { margin: 0; font-size: clamp(15px, 1.35vw, 24px); line-height: 1.2; }
    .panel-title { min-width: 0; }
    .panel-tools { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .stream-label {
      margin-top: 6px;
      font-size: 12px;
      color: var(--muted);
      word-break: break-word;
    }
    .small { color: var(--muted); font-size: 12px; }
    .stream-wrap {
      background: #0a1117;
      position: relative;
      width: 100%%;
      aspect-ratio: 16 / 9;
      min-height: clamp(230px, 32vw, 72vh);
      border-bottom: 1px solid var(--line);
    }
    .stream-frame {
      position: absolute;
      inset: 0;
      width: 100%%;
      height: 100%%;
      display: block;
      background: #000;
    }
    .stream-frame {
      border: 0;
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
    .small a {
      color: var(--accent-2);
      text-decoration: none;
      border-bottom: 1px dotted var(--accent-2);
    }
    .stream-link {
      color: var(--accent-2);
      text-decoration: none;
      border-bottom: 1px dotted var(--accent-2);
    }
    .stream-link:hover { opacity: 0.85; }
    .small a:hover { opacity: 0.85; }
    pre {
      margin: 0;
      padding: 12px 14px;
      min-height: 170px;
      max-height: 300px;
      overflow: auto;
      background: #0f1921;
      color: #9be6b4;
      font-size: 12px;
      line-height: 1.45;
    }
    @media (max-width: 1380px) {
      .grid { grid-template-columns: 1fr; }
      .grid.single { grid-template-columns: 1fr; }
      .stream-wrap, .stream-frame { min-height: clamp(220px, 48vw, 70vh); }
      .panel-head { grid-template-columns: 1fr; }
      .panel-tools { justify-content: flex-start; }
    }
    @media (max-width: 720px) {
      .modes { width: 100%%; }
      .mode { flex: 1 1 auto; min-width: 0; }
      .controls { gap: 6px; }
      .controls label { width: 100%%; color: var(--muted); }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header class="head">
    <div class="title">
      <h1>cam helper</h1>
      <span class="ver">v.001</span>
    </div>
    <nav class="modes">
      <button id="mode-both" class="mode active" onclick="setView('both')">Both</button>
      <button id="mode-cam1" class="mode" onclick="setView('cam1')">Camera 1</button>
      <button id="mode-cam2" class="mode" onclick="setView('cam2')">Camera 2</button>
    </nav>
  </header>

  <main id="grid" class="grid">
    <section id="panel-cam1" class="panel">
      <div class="panel-head">
        <div class="panel-title">
          <h2>Camera 1: %s</h2>
          <div class="stream-label">WebRTC stream: <a id="cam1RtcLink" class="stream-link" href="/cam1/rtc/cam1" target="_blank" rel="noopener">/cam1/rtc/cam1</a></div>
        </div>
        <div class="panel-tools">
          <button onclick="reloadStream('cam1')">Reload</button>
          <button onclick="openStream('cam1')">Open</button>
          <button class="blue" onclick="fullscreenStream('cam1Rtc', 'cam1')">Fullscreen</button>
        </div>
      </div>
      <div class="stream-wrap">
        <iframe id="cam1Rtc" class="stream-frame" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>
      </div>
      <div class="controls">
        <button id="cam1HomeBtn" class="danger" onclick="cam1Home()">Start Flow + Step0</button>
        <span id="cam1MapInfo" class="small">Map: loading...</span>
      </div>
      <div class="controls">
        <button id="cam1ZoomMinus" onclick="cam1ZoomDelta(-1)">Zoom -</button>
        <button id="cam1ZoomPlus" class="accent" onclick="cam1ZoomDelta(1)">Zoom +</button>
        <label>Set</label>
        <input id="cam1ZoomSet" type="number" min="0" max="%d" value="0" />
        <button id="cam1ZoomApply" class="blue" onclick="cam1ZoomSet()">Apply</button>
      </div>
      <div class="controls">
        <button id="cam1FocusMinus" onclick="cam1FocusDelta(-1)">Focus -</button>
        <button id="cam1FocusPlus" class="accent" onclick="cam1FocusDelta(1)">Focus +</button>
        <label>Set Y</label>
        <input id="cam1FocusSet" type="number" step="0.05" value="0.00" />
        <button id="cam1FocusApply" class="blue" onclick="cam1FocusSet()">Apply</button>
        <button id="cam1StatusBtn" onclick="cam1Status()">Status</button>
      </div>
    </section>

    <section id="panel-cam2" class="panel">
      <div class="panel-head">
        <div class="panel-title">
          <h2>Camera 2: %s</h2>
          <div class="stream-label">WebRTC stream: <a id="cam2RtcLink" class="stream-link" href="/cam2/rtc/cam2" target="_blank" rel="noopener">/cam2/rtc/cam2</a></div>
        </div>
        <div class="panel-tools">
          <button onclick="reloadStream('cam2')">Reload</button>
          <button onclick="openStream('cam2')">Open</button>
          <button class="blue" onclick="fullscreenStream('cam2Rtc', 'cam2')">Fullscreen</button>
        </div>
      </div>
      <div class="stream-wrap">
        <iframe id="cam2Rtc" class="stream-frame" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>
      </div>
      <div class="controls">
        <button id="cam2ZoomMinus" onclick="cam2ZoomDelta(-1)">Zoom -</button>
        <button id="cam2ZoomPlus" class="accent" onclick="cam2ZoomDelta(1)">Zoom +</button>
        <label>Set</label>
        <input id="cam2ZoomSet" type="number" value="0" />
        <button id="cam2ZoomApply" class="blue" onclick="cam2ZoomSet()">Apply</button>
        <button onclick="cam2Status()">Status</button>
      </div>
      <div class="controls">
        <span id="cam2ZoomInfo" class="small">Linux control via v4l2-ctl (%s)</span>
      </div>
    </section>
  </main>

  <section class="log">
    <div class="log-head">API log</div>
    <pre id="log">{}</pre>
  </section>
</div>

<script>

function setActiveMode(mode) {
  for (const id of ['mode-both', 'mode-cam1', 'mode-cam2']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.classList.remove('active');
  }
  const active = document.getElementById('mode-' + mode);
  if (active) active.classList.add('active');
}

function setView(mode) {
  const grid = document.getElementById('grid');
  const cam1 = document.getElementById('panel-cam1');
  const cam2 = document.getElementById('panel-cam2');
  cam1.classList.remove('hidden');
  cam2.classList.remove('hidden');
  grid.classList.remove('single');
  if (mode === 'cam1') {
    cam2.classList.add('hidden');
    grid.classList.add('single');
  }
  if (mode === 'cam2') {
    cam1.classList.add('hidden');
    grid.classList.add('single');
  }
  setActiveMode(mode);
}

function mediaMTXWebRTCURL(streamName) {
  const u = new URL(window.location.href);
  u.port = '8889';
  u.pathname = '/' + streamName;
  u.search = 'controls=false&autoplay=true&muted=true&playsinline=true';
  u.hash = '';
  return u.toString();
}

function streamFrameId(streamName) {
  return streamName === 'cam1' ? 'cam1Rtc' : 'cam2Rtc';
}

function openStream(streamName) {
  const url = mediaMTXWebRTCURL(streamName);
  window.open(url, '_blank', 'noopener');
}

function reloadStream(streamName) {
  const frame = document.getElementById(streamFrameId(streamName));
  if (!frame) return;
  const url = mediaMTXWebRTCURL(streamName);
  frame.src = 'about:blank';
  setTimeout(() => {
    frame.src = url + '&_ts=' + Date.now();
  }, 120);
}

async function fullscreenStream(frameId, streamName) {
  const frame = document.getElementById(frameId);
  if (!frame) return;
  try {
    if (frame.requestFullscreen) {
      await frame.requestFullscreen();
      return;
    }
  } catch (_) {}
  openStream(streamName);
}

function bindStreamLinks() {
  const cam1RTCURL = mediaMTXWebRTCURL('cam1');
  const cam2RTCURL = mediaMTXWebRTCURL('cam2');

  const cam1RTCLink = document.getElementById('cam1RtcLink');
  if (cam1RTCLink) {
    cam1RTCLink.href = cam1RTCURL;
    cam1RTCLink.textContent = cam1RTCURL;
  }
  const cam2RTCLink = document.getElementById('cam2RtcLink');
  if (cam2RTCLink) {
    cam2RTCLink.href = cam2RTCURL;
    cam2RTCLink.textContent = cam2RTCURL;
  }

  const cam1RTC = document.getElementById('cam1Rtc');
  if (cam1RTC && cam1RTC.src !== cam1RTCURL) {
    cam1RTC.src = cam1RTCURL;
  }
  const cam2RTC = document.getElementById('cam2Rtc');
  if (cam2RTC && cam2RTC.src !== cam2RTCURL) {
    cam2RTC.src = cam2RTCURL;
  }
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

function updateCam1State(data) {
  if (!data) return data;
  const state = data.mapState || (data.step0 && data.step0.mapState) || null;
  const info = document.getElementById('cam1MapInfo');
  const zoomSet = document.getElementById('cam1ZoomSet');
  const controls = ['cam1ZoomMinus', 'cam1ZoomPlus', 'cam1ZoomSet', 'cam1ZoomApply', 'cam1FocusMinus', 'cam1FocusPlus', 'cam1FocusSet', 'cam1FocusApply'];

  if (state && state.enabled) {
    const idx = Number(state.currentIndex ?? data.mapIndex ?? 0);
    const max = Number(state.maxIndex ?? 0);
    const homed = Boolean(state.homed);
    if (zoomSet) {
      zoomSet.max = String(max);
      zoomSet.value = String(idx);
    }
    for (const id of controls) {
      const el = document.getElementById(id);
      if (el) el.disabled = !homed;
    }
    if (info) {
      const coord = state.coordSpace || 'wpos';
      const preload = Number(state.xPreload || 0).toFixed(3);
      if (homed) {
        info.textContent = 'Map ON: idx=' + idx + '/' + max + ' coord=' + coord + ' preload=' + preload;
      } else {
        info.textContent = 'Map ON but NOT HOMED. Press "Start Flow + Step0".';
      }
    }
  } else if (info) {
    for (const id of controls) {
      const el = document.getElementById(id);
      if (el) el.disabled = false;
    }
    info.textContent = 'Map OFF: legacy linear mode';
  }
  return data;
}

function cam1Home() { return api('/api/cam1/home', 'POST', {}).then(updateCam1State); }
function cam1ZoomDelta(delta) { return api('/api/cam1/zoom', 'POST', { delta }).then(updateCam1State); }
function cam1ZoomSet() {
  const set = Number(document.getElementById('cam1ZoomSet').value);
  return api('/api/cam1/zoom', 'POST', { set }).then(updateCam1State);
}
function cam1FocusDelta(delta) { return api('/api/cam1/focus', 'POST', { delta }).then(updateCam1State); }
function cam1FocusSet() {
  const set = Number(document.getElementById('cam1FocusSet').value);
  return api('/api/cam1/focus', 'POST', { set }).then(updateCam1State);
}
function cam1Status() { return api('/api/cam1/status', 'GET').then(updateCam1State); }

function cam2ZoomDelta(delta) { return api('/api/cam2/zoom', 'POST', { delta }); }
function cam2ZoomSet() {
  const set = Number(document.getElementById('cam2ZoomSet').value);
  return api('/api/cam2/zoom', 'POST', { set });
}
function setCam2ZoomEnabled(enabled, note) {
  for (const id of ['cam2ZoomMinus', 'cam2ZoomPlus', 'cam2ZoomSet', 'cam2ZoomApply']) {
    const el = document.getElementById(id);
    if (el) el.disabled = !enabled;
  }
  const info = document.getElementById('cam2ZoomInfo');
  if (info && note) info.textContent = note;
}
async function cam2Status() {
  const data = await api('/api/cam2/zoom/status', 'GET');
  if (data && data.available) {
    const mode = data.mode ? (' mode=' + data.mode) : '';
    const ctrl = data.control ? (' control=' + data.control) : '';
    setCam2ZoomEnabled(true, 'Linux control via v4l2-ctl' + ctrl + mode);
  } else {
    const err = (data && data.error) ? data.error : 'zoom control is not available in V4L2';
    setCam2ZoomEnabled(false, 'Camera 2 zoom disabled: ' + err);
  }
  return data;
}

setView('both');
bindStreamLinks();
cam1Status();
cam2Status();
setInterval(() => { cam2Status(); }, 15000);
</script>
</body>
</html>`,
		esc(cfg.Cam1Name),
		max,
		esc(cfg.Cam2Name),
		esc(cfg.Cam2CtrlDev),
	)
}
