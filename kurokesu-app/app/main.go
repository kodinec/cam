package main

import (
	"errors"
	"log"
	"net/http"
	"time"
)

func main() {
	cfg := loadConfig()
	log.Printf(
		"startup listen=%s camera=%s rtc_base=%s map_path=%s map_steps=%d strict_map_limits=%v ptz_serial=%s ptz_baud=%d",
		cfg.Listen, cfg.CameraName, cfg.RTCBase, cfg.MapPath, cfg.MapSteps, cfg.StrictMapLimits, cfg.PTZSerial, cfg.PTZBaud,
	)

	var ptz *PTZ
	var ptzInitErr error
	ptz, ptzInitErr = newPTZ(cfg)
	if ptzInitErr != nil {
		log.Printf("ptz init failed (service will run in degraded mode): %v", ptzInitErr)
	} else {
		defer ptz.Close()
	}

	private := http.NewServeMux()
	private.HandleFunc("/", serveUI(cfg))
	private.HandleFunc("/rtc/", makePrefixReverseProxy(cfg.RTCBase, "/rtc/", "cam-rtc"))
	if ptz != nil {
		private.HandleFunc("/api/status", handleStatus(ptz))
		private.HandleFunc("/api/home", handleHome(ptz))
		private.HandleFunc("/api/zoom", handleZoom(ptz))
		private.HandleFunc("/api/focus", handleFocus(ptz))
	} else {
		reason := ptzInitErr.Error()
		private.HandleFunc("/api/status", handleUnavailableStatus("ptz unavailable: "+reason))
		private.HandleFunc("/api/home", handleUnavailableControl("ptz unavailable: "+reason))
		private.HandleFunc("/api/zoom", handleUnavailableControl("ptz unavailable: "+reason))
		private.HandleFunc("/api/focus", handleUnavailableControl("ptz unavailable: "+reason))
	}

	root := http.NewServeMux()
	root.HandleFunc("/healthz", handleHealth())
	root.Handle("/", maybeBasicAuth(cfg.User, cfg.Pass, private))

	srv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           root,
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
