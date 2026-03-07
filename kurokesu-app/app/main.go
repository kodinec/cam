package main

import (
	"errors"
	"log"
	"net/http"
	"strings"
	"time"
)

func main() {
	cfg := loadConfig()
	log.Printf(
		"startup listen=%s camera=%s rtc_base=%s ptz_api_base=%s",
		cfg.Listen, cfg.CameraName, cfg.RTCBase, cfg.PTZAPIBase,
	)

	private := http.NewServeMux()
	cam1Path := streamProxyPath("cam1")
	private.HandleFunc("/", serveUI(cfg))
	// MediaMTX's built-in WebRTC player is more reliable when served at the
	// final stream path, instead of behind an extra prefix like /rtc/cam1/.
	private.HandleFunc(strings.TrimSuffix(cam1Path, "/"), func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, cam1Path, http.StatusMovedPermanently)
	})
	private.HandleFunc(cam1Path, makePrefixReverseProxy(streamProxyBaseURL(cfg.RTCBase, "cam1"), cam1Path, "cam1-rtc"))
	private.HandleFunc("/rtc/", makePrefixReverseProxy(cfg.RTCBase, "/rtc/", "cam-rtc"))
	private.HandleFunc("/api", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/api/", http.StatusMovedPermanently)
	})
	private.HandleFunc("/api/", makePrefixReverseProxy(cfg.PTZAPIBase, "/api/", "ptz-api"))

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
