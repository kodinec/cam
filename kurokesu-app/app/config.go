package main

import (
	"flag"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Listen     string
	User       string
	Pass       string
	CameraName string
	RTCBase    string
	PTZAPIBase string
}

func loadConfig() Config {
	cfg := Config{}
	flag.StringVar(&cfg.Listen, "listen", envString("LISTEN", ":8787"), "HTTP listen address")
	flag.StringVar(&cfg.User, "user", envString("APP_USER", ""), "basic auth user")
	flag.StringVar(&cfg.Pass, "pass", envString("APP_PASS", ""), "basic auth password")
	flag.StringVar(&cfg.CameraName, "camera-name", envString("CAMERA_NAME", "Kurokesu C3 4K + L085/L085D"), "camera label")
	flag.StringVar(&cfg.RTCBase, "rtc-base", envString("RTC_BASE", "http://mediamtx:8889/"), "MediaMTX WebRTC base URL")
	flag.StringVar(&cfg.PTZAPIBase, "ptz-api-base", envString("PTZ_API_BASE", "http://ptz:8081/api/"), "Python PTZ API base URL")
	flag.Parse()
	return cfg
}

func envString(key, def string) string {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	return v
}

func envInt(key string, def int) int {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

func envFloat(key string, def float64) float64 {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return def
	}
	return n
}

func envBool(key string, def bool) bool {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.ParseBool(v)
	if err != nil {
		return def
	}
	return n
}
