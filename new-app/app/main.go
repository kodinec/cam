package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

type config struct {
	Listen     string
	Cam1Device string
	Cam2Device string
	WebRTCPort string
}

type cameraStatus struct {
	Device  string `json:"device"`
	Present bool   `json:"present"`
	Error   string `json:"error,omitempty"`
	Stream  string `json:"stream"`
}

type statusResponse struct {
	Now  string       `json:"now"`
	Cam1 cameraStatus `json:"cam1"`
	Cam2 cameraStatus `json:"cam2"`
}

func main() {
	cfg := loadConfig()

	mux := http.NewServeMux()
	mux.HandleFunc("/", rootHandler(cfg))
	mux.HandleFunc("/api/status", statusHandler(cfg))
	mux.HandleFunc("/healthz", healthHandler)

	srv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	log.Printf("new-app web listen=%s cam1=%s cam2=%s webrtc_port=%s", cfg.Listen, cfg.Cam1Device, cfg.Cam2Device, cfg.WebRTCPort)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("listen failed: %v", err)
	}
}

func loadConfig() config {
	return config{
		Listen:     env("WEB_LISTEN", ":8787"),
		Cam1Device: env("CAM1_DEVICE", "/dev/v4l/by-id/usb-Kurokesu_C3_4K_00001-video-index0"),
		Cam2Device: env("CAM2_DEVICE", "/dev/v4l/by-id/usb-rockchip_UVC_2020-video-index0"),
		WebRTCPort: env("WEBRTC_PORT", "8889"),
	}
}

func env(key, def string) string {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	return v
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"ok":true}`))
}

func statusHandler(cfg config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		cam1Present, cam1Err := devicePresent(cfg.Cam1Device)
		cam2Present, cam2Err := devicePresent(cfg.Cam2Device)

		resp := statusResponse{
			Now: time.Now().Format(time.RFC3339),
			Cam1: cameraStatus{
				Device:  cfg.Cam1Device,
				Present: cam1Present,
				Error:   cam1Err,
				Stream:  streamURL(r, cfg.WebRTCPort, "cam1"),
			},
			Cam2: cameraStatus{
				Device:  cfg.Cam2Device,
				Present: cam2Present,
				Error:   cam2Err,
				Stream:  streamURL(r, cfg.WebRTCPort, "cam2"),
			},
		}

		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(resp); err != nil {
			log.Printf("encode status failed: %v", err)
		}
	}
}

func devicePresent(path string) (bool, string) {
	if strings.TrimSpace(path) == "" {
		return false, "device path is empty"
	}
	_, err := os.Stat(path)
	if err == nil {
		return true, ""
	}
	if os.IsNotExist(err) {
		return false, "device not found"
	}
	return false, err.Error()
}

func streamURL(r *http.Request, port, stream string) string {
	host := requestHost(r)
	addr := net.JoinHostPort(host, port)
	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	return fmt.Sprintf("%s://%s/%s?controls=false&autoplay=true&muted=true&playsinline=true", scheme, addr, stream)
}

func requestHost(r *http.Request) string {
	host := strings.TrimSpace(r.Host)
	if host == "" {
		return "localhost"
	}

	if h, _, err := net.SplitHostPort(host); err == nil {
		if h == "" {
			return "localhost"
		}
		return h
	}

	if strings.HasPrefix(host, "[") && strings.HasSuffix(host, "]") {
		return strings.Trim(host, "[]")
	}

	if strings.Count(host, ":") > 1 {
		return host
	}

	if i := strings.IndexByte(host, ':'); i > 0 {
		return host[:i]
	}

	return host
}

func rootHandler(cfg config) http.HandlerFunc {
	page := buildIndexHTML(cfg)
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(page))
	}
}

func buildIndexHTML(cfg config) string {
	return fmt.Sprintf(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>cam helper</title>
  <style>
    :root {
      --bg: #ecf2f8;
      --card: #ffffff;
      --ink: #1f2a37;
      --muted: #5b6b7c;
      --line: #cbd5df;
      --ok: #1f7a4f;
      --bad: #a0372d;
      --accent: #1565c0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(180deg, #f7fbff, var(--bg));
      color: var(--ink);
    }
    .wrap { max-width: 1700px; margin: 0 auto; padding: 14px; }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      margin-bottom: 12px;
    }
    .title { font-size: 28px; font-weight: 700; }
    .subtitle { color: var(--muted); font-size: 13px; }
    .modes { display: flex; gap: 8px; }
    .modes button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .modes button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .grid.single { grid-template-columns: 1fr; }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
    }
    .card.hidden { display: none; }
    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
    }
    .card-title { font-size: 24px; font-weight: 700; }
    .status { font-size: 13px; color: var(--muted); }
    .status.ok { color: var(--ok); font-weight: 700; }
    .status.bad { color: var(--bad); font-weight: 700; }
    .device { padding: 0 12px 10px; font-size: 12px; color: var(--muted); }
    .stream-wrap { width: 100%%; aspect-ratio: 16 / 9; background: #0f1720; border-top: 1px solid var(--line); }
    iframe { width: 100%%; height: 100%%; border: 0; display: block; }
    .actions {
      display: flex;
      gap: 8px;
      padding: 10px 12px;
      border-top: 1px solid var(--line);
    }
    .actions button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 8px;
      padding: 7px 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .actions button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
    .footer {
      margin-top: 12px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 12px;
      color: var(--muted);
      white-space: pre-wrap;
    }
    @media (max-width: 1200px) {
      .grid { grid-template-columns: 1fr; }
      .grid.single { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header class="head">
    <div>
      <div class="title">cam helper</div>
      <div class="subtitle">minimal dual camera monitor (clean baseline)</div>
    </div>
    <div class="modes">
      <button id="mode-both" class="active" onclick="setView('both')">Both</button>
      <button id="mode-cam1" onclick="setView('cam1')">Camera 1</button>
      <button id="mode-cam2" onclick="setView('cam2')">Camera 2</button>
    </div>
  </header>

  <main id="grid" class="grid">
    <section id="card-cam1" class="card">
      <div class="card-head">
        <div class="card-title">Camera 1</div>
        <div id="status-cam1" class="status">checking...</div>
      </div>
      <div id="device-cam1" class="device">device: %s</div>
      <div class="stream-wrap"><iframe id="frame-cam1" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe></div>
      <div class="actions">
        <button onclick="reloadStream('cam1')">Reload</button>
        <button onclick="openStream('cam1')">Open</button>
        <button class="primary" onclick="fullscreen('frame-cam1', 'cam1')">Fullscreen</button>
      </div>
    </section>

    <section id="card-cam2" class="card">
      <div class="card-head">
        <div class="card-title">Camera 2</div>
        <div id="status-cam2" class="status">checking...</div>
      </div>
      <div id="device-cam2" class="device">device: %s</div>
      <div class="stream-wrap"><iframe id="frame-cam2" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe></div>
      <div class="actions">
        <button onclick="reloadStream('cam2')">Reload</button>
        <button onclick="openStream('cam2')">Open</button>
        <button class="primary" onclick="fullscreen('frame-cam2', 'cam2')">Fullscreen</button>
      </div>
    </section>
  </main>

  <section id="log" class="footer">status: loading...</section>
</div>

<script>
const WEBRTC_PORT = %q;

function streamURL(name) {
  const proto = (window.location.protocol === 'https:') ? 'https:' : 'http:';
  return proto + '//' + window.location.hostname + ':' + WEBRTC_PORT + '/' + name + '?controls=false&autoplay=true&muted=true&playsinline=true';
}

function setView(mode) {
  const grid = document.getElementById('grid');
  const cam1 = document.getElementById('card-cam1');
  const cam2 = document.getElementById('card-cam2');
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
  for (const id of ['mode-both', 'mode-cam1', 'mode-cam2']) {
    document.getElementById(id).classList.remove('active');
  }
  document.getElementById('mode-' + mode).classList.add('active');
}

function setFrame(name, enabled) {
  const frame = document.getElementById('frame-' + name);
  const u = streamURL(name);
  if (enabled) {
    if (frame.dataset.src !== u) {
      frame.src = u;
      frame.dataset.src = u;
    }
  } else {
    if (frame.dataset.src) {
      frame.src = 'about:blank';
      frame.dataset.src = '';
    }
  }
}

function setStatus(name, present, err, device) {
  const el = document.getElementById('status-' + name);
  const dev = document.getElementById('device-' + name);
  dev.textContent = 'device: ' + device;
  el.classList.remove('ok', 'bad');
  if (present) {
    el.classList.add('ok');
    el.textContent = 'online';
    el.title = '';
  } else {
    el.classList.add('bad');
    el.textContent = 'offline';
    el.title = err || 'device not found';
  }
}

function openStream(name) {
  window.open(streamURL(name), '_blank', 'noopener');
}

function reloadStream(name) {
  const frame = document.getElementById('frame-' + name);
  const u = streamURL(name);
  frame.src = 'about:blank';
  frame.dataset.src = '';
  setTimeout(() => {
    frame.src = u + '&_ts=' + Date.now();
    frame.dataset.src = u;
  }, 120);
}

async function fullscreen(frameID, streamName) {
  const frame = document.getElementById(frameID);
  if (frame.requestFullscreen) {
    try {
      await frame.requestFullscreen();
      return;
    } catch (_) {}
  }
  openStream(streamName);
}

async function pollStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();

    setStatus('cam1', data.cam1.present, data.cam1.error, data.cam1.device);
    setStatus('cam2', data.cam2.present, data.cam2.error, data.cam2.device);

    setFrame('cam1', data.cam1.present);
    setFrame('cam2', data.cam2.present);

    document.getElementById('log').textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    document.getElementById('log').textContent = 'status error: ' + (e && e.message ? e.message : 'unknown');
  }
}

setView('both');
pollStatus();
setInterval(pollStatus, 2000);
</script>
</body>
</html>`, cfg.Cam1Device, cfg.Cam2Device, cfg.WebRTCPort)
}
