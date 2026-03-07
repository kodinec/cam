package main

import (
	"flag"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Listen          string
	User            string
	Pass            string
	CameraName      string
	RTCBase         string
	MapPath         string
	MapSteps        int
	StrictMapLimits bool

	PTZSerial         string
	PTZSerialFallback string
	PTZBaud           int
	MapFeed           float64
	FocusFineStep     float64
	Reset             bool
	LimitLED          bool
	IrisOpen          bool
	HomeFocus         bool
	HomeTimeout       float64
	BackoffX          float64
	BackoffY          float64
	BackoffFeed       float64
	StartX            float64
	StartY            float64
	GotoFeed          float64
	AutoRelease       bool
	ReleaseStepX      float64
	ReleaseStepY      float64
	ReleaseMaxSteps   int
	ReleaseFeed       float64
}

func loadConfig() Config {
	cfg := Config{}
	flag.StringVar(&cfg.Listen, "listen", envString("LISTEN", ":8787"), "HTTP listen address")
	flag.StringVar(&cfg.User, "user", envString("APP_USER", ""), "basic auth user")
	flag.StringVar(&cfg.Pass, "pass", envString("APP_PASS", ""), "basic auth password")
	flag.StringVar(&cfg.CameraName, "camera-name", envString("CAMERA_NAME", "Kurokesu C3 4K + L085/L085D"), "camera label")
	flag.StringVar(&cfg.RTCBase, "rtc-base", envString("RTC_BASE", "http://mediamtx:8889/"), "MediaMTX WebRTC base URL")
	flag.StringVar(&cfg.MapPath, "map-path", envString("CAM_MAP_PATH", "/app/zoom25_focusmap.json"), "zoom/focus map JSON path")
	flag.IntVar(&cfg.MapSteps, "map-steps", envInt("CAM_MAP_STEPS", 8), "number of map steps to use from the source map")
	flag.BoolVar(&cfg.StrictMapLimits, "strict-map-limits", envBool("CAM_STRICT_MAP_LIMITS", true), "reject selected map points flagged with limitXY")

	flag.StringVar(&cfg.PTZSerial, "ptz-serial", envString("PTZ_SERIAL", "/dev/ttyACM0"), "PTZ serial device")
	flag.StringVar(&cfg.PTZSerialFallback, "ptz-serial-fallback", envString("PTZ_SERIAL_FALLBACK", "/dev/serial/by-id/"), "fallback PTZ serial device path")
	flag.IntVar(&cfg.PTZBaud, "ptz-baud", envInt("PTZ_BAUD", 115200), "PTZ serial baud")
	flag.Float64Var(&cfg.MapFeed, "map-feed", envFloat("CAM_MAP_FEED", 180.0), "map move feed")
	flag.Float64Var(&cfg.FocusFineStep, "focus-fine-step", envFloat("CAM_FOCUS_FINE_STEP", 0.05), "manual focus fine step")
	flag.BoolVar(&cfg.Reset, "reset", envBool("CAM_RESET", true), "start flow: send Ctrl-X reset")
	flag.BoolVar(&cfg.LimitLED, "limit-led", envBool("CAM_LIMIT_LED", true), "start flow: enable limit LED")
	flag.BoolVar(&cfg.IrisOpen, "iris-open", envBool("CAM_IRIS_OPEN", true), "start flow: open iris")
	flag.BoolVar(&cfg.HomeFocus, "home-focus", envBool("CAM_HOME_FOCUS", true), "start flow: perform $HY")
	flag.Float64Var(&cfg.HomeTimeout, "home-timeout", envFloat("CAM_HOME_TIMEOUT", 25.0), "home timeout (seconds)")
	flag.Float64Var(&cfg.BackoffX, "backoff-x", envFloat("CAM_BACKOFF_X", 1.0), "backoff X after homing")
	flag.Float64Var(&cfg.BackoffY, "backoff-y", envFloat("CAM_BACKOFF_Y", 0.5), "backoff Y after homing")
	flag.Float64Var(&cfg.BackoffFeed, "backoff-feed", envFloat("CAM_BACKOFF_FEED", 120.0), "backoff feed")
	flag.Float64Var(&cfg.StartX, "start-x", envFloat("CAM_START_X", 0.0), "start X before zeroing")
	flag.Float64Var(&cfg.StartY, "start-y", envFloat("CAM_START_Y", 0.0), "start Y before zeroing")
	flag.Float64Var(&cfg.GotoFeed, "goto-feed", envFloat("CAM_GOTO_FEED", 200.0), "goto feed")
	flag.BoolVar(&cfg.AutoRelease, "auto-release", envBool("CAM_AUTO_RELEASE", true), "start flow: auto-release active X/Y limits")
	flag.Float64Var(&cfg.ReleaseStepX, "release-step-x", envFloat("CAM_RELEASE_STEP_X", 0.2), "auto-release X step")
	flag.Float64Var(&cfg.ReleaseStepY, "release-step-y", envFloat("CAM_RELEASE_STEP_Y", 0.2), "auto-release Y step")
	flag.IntVar(&cfg.ReleaseMaxSteps, "release-max-steps", envInt("CAM_RELEASE_MAX_STEPS", 40), "auto-release max attempts per direction")
	flag.Float64Var(&cfg.ReleaseFeed, "release-feed", envFloat("CAM_RELEASE_FEED", 80.0), "auto-release feed")
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
