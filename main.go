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
	log.Printf("startup listen=%s cam1_upstream=%s cam2_upstream=%s cam2_device=%s cam2_control_device=%s cam2_zoom_step=%d ptz_serial=%s ptz_baud=%d zoom_max=%d x_per_step=%.3f y_per_step=%.3f feed=%.1f raw=%v",
		cfg.Listen, cfg.Cam1Upstream, cfg.Cam2Upstream, cfg.Cam2Device, cfg.Cam2CtrlDev, cfg.Cam2ZoomStep, cfg.PTZSerial, cfg.PTZBaud, cfg.PTZZoomMax, cfg.PTZXPerStep, cfg.PTZYPerStep, cfg.PTZFeed, cfg.PTZAllowRaw,
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
	private.HandleFunc("/api/cam1/zoom", handleZoom(ptz))
	private.HandleFunc("/api/cam1/focus", handleFocus(ptz, cfg.PTZZoomMax))
	private.HandleFunc("/api/cam1/status", handleStatus(ptz))
	private.HandleFunc("/api/cam1/raw", handleRaw(ptz, cfg.PTZAllowRaw))
	private.HandleFunc("/api/cam2/zoom", handleCam2Zoom(cam2Zoom))
	private.HandleFunc("/api/cam2/zoom/status", handleCam2ZoomStatus(cam2Zoom))
	private.HandleFunc("/cam1/mjpeg", makeMJPEGProxy(proxyClient, cfg.Cam1Upstream, "cam1"))
	private.HandleFunc("/cam2/mjpeg", makeMJPEGProxy(proxyClient, cfg.Cam2Upstream, "cam2"))

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
