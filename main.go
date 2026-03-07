package main

import (
	"errors"
	"log"
	"net"
	"net/http"
	"time"
)

func main() {
	cfg := loadConfig()
	log.Printf("startup listen=%s cam1_hls_base=%s cam2_hls_base=%s cam1_map_path=%s cam1_map_steps=%d cam2_device=%s cam2_control_device=%s cam2_zoom_step=%d ptz_serial=%s ptz_baud=%d zoom_max=%d x_per_step=%.3f y_per_step=%.3f feed=%.1f raw=%v",
		cfg.Listen, cfg.Cam1HLSBase, cfg.Cam2HLSBase, cfg.Cam1MapPath, cfg.Cam1MapSteps, cfg.Cam2Device, cfg.Cam2CtrlDev, cfg.Cam2ZoomStep, cfg.PTZSerial, cfg.PTZBaud, cfg.PTZZoomMax, cfg.PTZXPerStep, cfg.PTZYPerStep, cfg.PTZFeed, cfg.PTZAllowRaw,
	)

	ptz, err := newPTZ(cfg)
	if err != nil {
		log.Fatalf("ptz init failed: %v", err)
	}
	defer ptz.Close()
	cam2Zoom := newCam2Zoom(cfg)

	proxyClient := &http.Client{
		Transport: &http.Transport{
			Proxy: http.ProxyFromEnvironment,
			DialContext: (&net.Dialer{
				Timeout:   3 * time.Second,
				KeepAlive: 30 * time.Second,
			}).DialContext,
			ResponseHeaderTimeout: 5 * time.Second,
		},
	}

	private := http.NewServeMux()
	private.HandleFunc("/", serveUI(cfg))
	private.HandleFunc("/api/cam1/home", handleCam1Home(ptz))
	private.HandleFunc("/api/cam1/zoom", handleZoom(ptz))
	private.HandleFunc("/api/cam1/focus", handleFocus(ptz))
	private.HandleFunc("/api/cam1/status", handleStatus(ptz))
	private.HandleFunc("/api/cam1/raw", handleRaw(ptz, cfg.PTZAllowRaw))
	private.HandleFunc("/api/cam2/zoom", handleCam2Zoom(cam2Zoom))
	private.HandleFunc("/api/cam2/zoom/status", handleCam2ZoomStatus(cam2Zoom))
	private.HandleFunc("/cam1/mjpeg", makeMJPEGProxy(proxyClient, cfg.Cam1Upstream, "cam1"))
	private.HandleFunc("/cam2/mjpeg", makeMJPEGProxy(proxyClient, cfg.Cam2Upstream, "cam2"))
	private.HandleFunc("/cam1/hls/", makePrefixReverseProxy(cfg.Cam1HLSBase, "/cam1/hls/", "cam1-hls"))
	private.HandleFunc("/cam2/hls/", makePrefixReverseProxy(cfg.Cam2HLSBase, "/cam2/hls/", "cam2-hls"))

	handler := basicAuth(cfg.User, cfg.Pass, private)

	srv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	log.Printf("listening on %s", cfg.Listen)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatalf("server error: %v", err)
	}
}

func init() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
}
