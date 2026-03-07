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
  <title>Dual Camera Console v.001</title>
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
    .wrap { max-width: 1500px; margin: 0 auto; padding: 18px; }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
      padding: 14px 16px;
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
    h1 { margin: 0; font-size: 22px; letter-spacing: 0.2px; }
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
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
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
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 8px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #ffffffb5;
    }
    .panel-head h2 { margin: 0; font-size: 15px; }
    .small { color: var(--muted); font-size: 12px; }
    .stream-wrap {
      background: #0a1117;
      position: relative;
      min-height: 260px;
      border-bottom: 1px solid var(--line);
    }
    .stream,
    .stream-frame {
      width: 100%%;
      height: 100%%;
      display: block;
      min-height: 260px;
      object-fit: contain;
      background: #000;
    }
    .stream-frame {
      border: 0;
    }
    .stream-hidden {
      display: none !important;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      padding: 12px 14px;
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
      width: 92px;
      font-family: inherit;
      font-weight: 600;
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
    @media (max-width: 1040px) {
      .grid { grid-template-columns: 1fr; }
      .grid.single { grid-template-columns: 1fr; }
      .stream-wrap, .stream, .stream-frame { min-height: 220px; }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header class="head">
    <div class="title">
      <h1>Dual Camera Control Panel</h1>
      <span class="ver">v.001</span>
    </div>
    <nav class="modes">
      <button id="mode-both" class="mode active" onclick="setView('both')">Both</button>
      <button id="mode-cam1" class="mode" onclick="setView('cam1')">Camera 1</button>
      <button id="mode-cam2" class="mode" onclick="setView('cam2')">Camera 2</button>
      <button id="transport-webrtc" class="mode active" onclick="setTransport('webrtc')">WebRTC</button>
      <button id="transport-hls" class="mode" onclick="setTransport('hls')">HLS</button>
    </nav>
  </header>

  <main id="grid" class="grid">
    <section id="panel-cam1" class="panel">
      <div class="panel-head">
        <h2>Camera 1: %s</h2>
        <span class="small">RTC: <a id="cam1RtcLink" href="/cam1/rtc/cam1" target="_blank" rel="noopener">/cam1/rtc/cam1</a> | HLS: <a id="cam1HlsLink" href="/cam1/hls/index.m3u8" target="_blank" rel="noopener">/cam1/hls/index.m3u8</a></span>
      </div>
      <div class="stream-wrap">
        <iframe id="cam1Rtc" class="stream-frame" allow="autoplay; fullscreen; picture-in-picture"></iframe>
        <video id="cam1Video" class="stream stream-hidden" muted autoplay playsinline controls></video>
      </div>
      <div class="controls">
        <button class="danger" onclick="cam1Home()">Start Flow + Step0</button>
        <span id="cam1MapInfo" class="small">Map: loading...</span>
      </div>
      <div class="controls">
        <button onclick="cam1ZoomDelta(-1)">Zoom -</button>
        <button class="accent" onclick="cam1ZoomDelta(1)">Zoom +</button>
        <label>Set</label>
        <input id="cam1ZoomSet" type="number" min="0" max="%d" value="0" />
        <button class="blue" onclick="cam1ZoomSet()">Apply</button>
      </div>
      <div class="controls">
        <button onclick="cam1FocusDelta(-1)">Focus -</button>
        <button class="accent" onclick="cam1FocusDelta(1)">Focus +</button>
        <label>Set</label>
        <input id="cam1FocusSet" type="number" min="0" max="%d" value="0" />
        <button class="blue" onclick="cam1FocusSet()">Apply</button>
        <button onclick="cam1Status()">Status</button>
      </div>
    </section>

    <section id="panel-cam2" class="panel">
      <div class="panel-head">
        <h2>Camera 2: %s</h2>
        <span class="small">RTC: <a id="cam2RtcLink" href="/cam2/rtc/cam2" target="_blank" rel="noopener">/cam2/rtc/cam2</a> | HLS: <a id="cam2HlsLink" href="/cam2/hls/index.m3u8" target="_blank" rel="noopener">/cam2/hls/index.m3u8</a> (stream: %s)</span>
      </div>
      <div class="stream-wrap">
        <iframe id="cam2Rtc" class="stream-frame" allow="autoplay; fullscreen; picture-in-picture"></iframe>
        <video id="cam2Video" class="stream stream-hidden" muted autoplay playsinline controls></video>
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

<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js"></script>
<script>
function keepNearLiveEdge(video) {
  if (!video || video._liveEdgeTimer) return;
  video._liveEdgeTimer = setInterval(() => {
    if (!video.buffered || video.buffered.length === 0 || video.seeking || video.paused) return;
    const end = video.buffered.end(video.buffered.length - 1);
    const lag = end - video.currentTime;
    if (lag > 2.5) {
      video.currentTime = Math.max(0, end - 0.15);
      return;
    }
    if (lag > 1.2 && video.playbackRate < 1.07) {
      video.playbackRate = 1.07;
      return;
    }
    if (lag < 0.7 && video.playbackRate !== 1.0) {
      video.playbackRate = 1.0;
    }
  }, 350);
}

function attachHLS(videoId, url) {
  const video = document.getElementById(videoId);
  if (!video) return;
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = url;
    keepNearLiveEdge(video);
    video.play().catch(() => {});
    return;
  }
  if (window.Hls && window.Hls.isSupported()) {
    const hls = new window.Hls({
      enableWorker: true,
      lowLatencyMode: true,
      liveSyncDurationCount: 1,
      liveMaxLatencyDurationCount: 2,
      maxLiveSyncPlaybackRate: 1.15,
      maxBufferLength: 1.5,
      maxMaxBufferLength: 3,
      backBufferLength: 5,
      startPosition: -1
    });
    hls.loadSource(url);
    hls.attachMedia(video);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
      keepNearLiveEdge(video);
      video.play().catch(() => {});
    });
    hls.on(window.Hls.Events.ERROR, (_, data) => {
      if (!data || !data.fatal) return;
      if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR) {
        hls.startLoad();
        return;
      }
      if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR) {
        hls.recoverMediaError();
        return;
      }
      hls.destroy();
    });
    return;
  }
  const log = document.getElementById('log');
  if (log) {
    log.textContent = JSON.stringify({ error: 'HLS unsupported in this browser', url }, null, 2);
  }
}

function setActiveMode(mode) {
  for (const id of ['mode-both', 'mode-cam1', 'mode-cam2']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.classList.remove('active');
  }
  const active = document.getElementById('mode-' + mode);
  if (active) active.classList.add('active');
}

function setTransport(mode) {
  const resolved = mode === 'hls' ? 'hls' : 'webrtc';
  for (const m of ['webrtc', 'hls']) {
    const el = document.getElementById('transport-' + m);
    if (!el) continue;
    el.classList.toggle('active', m === resolved);
  }
  const useRTC = resolved === 'webrtc';
  for (const cam of ['cam1', 'cam2']) {
    const rtc = document.getElementById(cam + 'Rtc');
    const hls = document.getElementById(cam + 'Video');
    if (rtc) rtc.classList.toggle('stream-hidden', !useRTC);
    if (hls) hls.classList.toggle('stream-hidden', useRTC);
    if (!useRTC && hls && hls.paused) {
      hls.play().catch(() => {});
    }
  }
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

function absoluteURL(path) {
  return new URL(path, window.location.origin).toString();
}

function bindStreamLinks() {
  const cam1HLSPath = '/cam1/hls/index.m3u8';
  const cam2HLSPath = '/cam2/hls/index.m3u8';
  const cam1RTCPath = '/cam1/rtc/cam1?controls=false&autoplay=true&muted=true&playsinline=true';
  const cam2RTCPath = '/cam2/rtc/cam2?controls=false&autoplay=true&muted=true&playsinline=true';
  const cam1HLSURL = absoluteURL(cam1HLSPath);
  const cam2HLSURL = absoluteURL(cam2HLSPath);
  const cam1RTCURL = absoluteURL(cam1RTCPath);
  const cam2RTCURL = absoluteURL(cam2RTCPath);

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

  const cam1Link = document.getElementById('cam1HlsLink');
  if (cam1Link) {
    cam1Link.href = cam1HLSURL;
    cam1Link.textContent = cam1HLSURL;
  }
  const cam2Link = document.getElementById('cam2HlsLink');
  if (cam2Link) {
    cam2Link.href = cam2HLSURL;
    cam2Link.textContent = cam2HLSURL;
  }

  const cam1RTC = document.getElementById('cam1Rtc');
  if (cam1RTC && cam1RTC.src !== cam1RTCURL) {
    cam1RTC.src = cam1RTCURL;
  }
  const cam2RTC = document.getElementById('cam2Rtc');
  if (cam2RTC && cam2RTC.src !== cam2RTCURL) {
    cam2RTC.src = cam2RTCURL;
  }

  attachHLS('cam1Video', cam1HLSURL);
  attachHLS('cam2Video', cam2HLSURL);
}

async function api(url, method, body) {
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
}

function updateCam1State(data) {
  if (!data) return data;
  const state = data.mapState || (data.step0 && data.step0.mapState) || null;
  const info = document.getElementById('cam1MapInfo');
  const zoomSet = document.getElementById('cam1ZoomSet');

  if (state && state.enabled) {
    const idx = Number(state.currentIndex ?? data.mapIndex ?? 0);
    const max = Number(state.maxIndex ?? 0);
    if (zoomSet) {
      zoomSet.max = String(max);
      zoomSet.value = String(idx);
    }
    if (info) {
      const coord = state.coordSpace || 'wpos';
      const preload = Number(state.xPreload || 0).toFixed(3);
      info.textContent = 'Map ON: idx=' + idx + '/' + max + ' coord=' + coord + ' preload=' + preload;
    }
  } else if (info) {
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
setTransport('webrtc');
cam1Status();
cam2Status();
</script>
</body>
</html>`,
		esc(cfg.Cam1Name),
		max,
		max,
		esc(cfg.Cam2Name),
		esc(cfg.Cam2Device),
		esc(cfg.Cam2CtrlDev),
	)
}
