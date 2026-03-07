package main

import (
	"flag"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Listen       string
	User         string
	Pass         string
	Cam1Name     string
	Cam2Name     string
	Cam1Upstream string
	Cam2Upstream string
	Cam1HLSBase  string
	Cam2HLSBase  string
	Cam1MapPath  string
	Cam1MapSteps int
	Cam1MapFeed  float64
	Cam2Device   string
	Cam2CtrlDev  string
	Cam2ZoomStep int

	PTZSerial   string
	PTZBaud     int
	PTZZoomMax  int
	PTZXPerStep float64
	PTZYPerStep float64
	PTZFeed     float64
	PTZAllowRaw bool

	Cam1Reset       bool
	Cam1LimitLED    bool
	Cam1IrisOpen    bool
	Cam1HomeFocus   bool
	Cam1HomeTimeout float64
	Cam1BackoffX    float64
	Cam1BackoffY    float64
	Cam1BackoffFeed float64
	Cam1StartX      float64
	Cam1StartY      float64
	Cam1GotoFeed    float64

	Cam1AutoRelease    bool
	Cam1ReleaseStepX   float64
	Cam1ReleaseStepY   float64
	Cam1ReleaseMaxStep int
	Cam1ReleaseFeed    float64
}

func loadConfig() Config {
	cfg := Config{}
	flag.StringVar(&cfg.Listen, "listen", envString("LISTEN", ":8787"), "HTTP listen address")
	flag.StringVar(&cfg.User, "user", envString("PTZ_USER", "admin"), "basic auth user")
	flag.StringVar(&cfg.Pass, "pass", envString("PTZ_PASS", "admin"), "basic auth password")
	flag.StringVar(&cfg.Cam1Name, "cam1-name", envString("CAM1_NAME", "Kurokesu C3 4K (L085)"), "camera #1 label")
	flag.StringVar(&cfg.Cam2Name, "cam2-name", envString("CAM2_NAME", "NVECTECH PATRIOT 2 H50"), "camera #2 label")
	flag.StringVar(&cfg.Cam1Upstream, "cam1-upstream", envString("CAM1_UPSTREAM", "http://127.0.0.1:8080/?action=stream"), "camera #1 MJPEG upstream")
	flag.StringVar(&cfg.Cam2Upstream, "cam2-upstream", envString("CAM2_UPSTREAM", "http://127.0.0.1:8081/?action=stream"), "camera #2 MJPEG upstream")
	flag.StringVar(&cfg.Cam1HLSBase, "cam1-hls-base", envString("CAM1_HLS_BASE", "http://mediamtx:8888/cam1/"), "camera #1 HLS base URL for reverse proxy")
	flag.StringVar(&cfg.Cam2HLSBase, "cam2-hls-base", envString("CAM2_HLS_BASE", "http://mediamtx:8888/cam2/"), "camera #2 HLS base URL for reverse proxy")
	flag.StringVar(&cfg.Cam1MapPath, "cam1-map-path", envString("CAM1_MAP_PATH", ""), "camera #1 calibration map JSON path")
	flag.IntVar(&cfg.Cam1MapSteps, "cam1-map-steps", envInt("CAM1_MAP_STEPS", 8), "camera #1 number of points to use from map")
	flag.Float64Var(&cfg.Cam1MapFeed, "cam1-map-feed", envFloat("CAM1_MAP_FEED", 180.0), "camera #1 map move feed rate")
	flag.StringVar(&cfg.Cam2Device, "cam2-device", envString("CAM2_DEVICE", "/dev/video2"), "camera #2 stream device")
	flag.StringVar(&cfg.Cam2CtrlDev, "cam2-control-device", envString("CAM2_CONTROL_DEVICE", envString("CAM2_DEVICE", "/dev/video2")), "camera #2 control device for v4l2 zoom")
	flag.IntVar(&cfg.Cam2ZoomStep, "cam2-zoom-step", envInt("CAM2_ZOOM_STEP", 1), "camera #2 zoom step for zoom_absolute control")

	flag.StringVar(&cfg.PTZSerial, "ptz-serial", envString("PTZ_SERIAL", "/dev/ttyACM0"), "PTZ serial device")
	flag.IntVar(&cfg.PTZBaud, "ptz-baud", envInt("PTZ_BAUD", 115200), "PTZ serial baud")
	flag.IntVar(&cfg.PTZZoomMax, "ptz-zoom-max", envInt("PTZ_ZOOM_MAX", 25), "logical max zoom/focus step")
	flag.Float64Var(&cfg.PTZXPerStep, "ptz-x-per-step", envFloat("PTZ_X_PER_STEP", 10.0), "axis X units per logical zoom step")
	flag.Float64Var(&cfg.PTZYPerStep, "ptz-y-per-step", envFloat("PTZ_Y_PER_STEP", 10.0), "axis Y units per logical focus step")
	flag.Float64Var(&cfg.PTZFeed, "ptz-feed", envFloat("PTZ_FEED", 200.0), "move feed rate")
	flag.BoolVar(&cfg.PTZAllowRaw, "ptz-allow-raw", envBool("PTZ_ALLOW_RAW", false), "allow /api/cam1/raw")

	flag.BoolVar(&cfg.Cam1Reset, "cam1-reset", envBool("CAM1_RESET", true), "camera #1 start flow: send Ctrl-X reset")
	flag.BoolVar(&cfg.Cam1LimitLED, "cam1-limit-led", envBool("CAM1_LIMIT_LED", true), "camera #1 start flow: enable limit LED (M120 P1)")
	flag.BoolVar(&cfg.Cam1IrisOpen, "cam1-iris-open", envBool("CAM1_IRIS_OPEN", true), "camera #1 start flow: iris open (M114 P1)")
	flag.BoolVar(&cfg.Cam1HomeFocus, "cam1-home-focus", envBool("CAM1_HOME_FOCUS", true), "camera #1 start flow: perform $HY")
	flag.Float64Var(&cfg.Cam1HomeTimeout, "cam1-home-timeout", envFloat("CAM1_HOME_TIMEOUT", 25.0), "camera #1 home timeout (seconds)")
	flag.Float64Var(&cfg.Cam1BackoffX, "cam1-backoff-x", envFloat("CAM1_BACKOFF_X", 1.0), "camera #1 backoff X after homing")
	flag.Float64Var(&cfg.Cam1BackoffY, "cam1-backoff-y", envFloat("CAM1_BACKOFF_Y", 0.5), "camera #1 backoff Y after homing")
	flag.Float64Var(&cfg.Cam1BackoffFeed, "cam1-backoff-feed", envFloat("CAM1_BACKOFF_FEED", 120.0), "camera #1 backoff feed")
	flag.Float64Var(&cfg.Cam1StartX, "cam1-start-x", envFloat("CAM1_START_X", 0.0), "camera #1 start X before zeroing")
	flag.Float64Var(&cfg.Cam1StartY, "cam1-start-y", envFloat("CAM1_START_Y", 0.0), "camera #1 start Y before zeroing")
	flag.Float64Var(&cfg.Cam1GotoFeed, "cam1-goto-feed", envFloat("CAM1_GOTO_FEED", 200.0), "camera #1 goto feed")
	flag.BoolVar(&cfg.Cam1AutoRelease, "cam1-auto-release", envBool("CAM1_AUTO_RELEASE", true), "camera #1 start flow: auto release active X/Y limits")
	flag.Float64Var(&cfg.Cam1ReleaseStepX, "cam1-release-step-x", envFloat("CAM1_RELEASE_STEP_X", 0.2), "camera #1 auto-release step for X")
	flag.Float64Var(&cfg.Cam1ReleaseStepY, "cam1-release-step-y", envFloat("CAM1_RELEASE_STEP_Y", 0.2), "camera #1 auto-release step for Y")
	flag.IntVar(&cfg.Cam1ReleaseMaxStep, "cam1-release-max-steps", envInt("CAM1_RELEASE_MAX_STEPS", 40), "camera #1 auto-release max attempts per direction")
	flag.Float64Var(&cfg.Cam1ReleaseFeed, "cam1-release-feed", envFloat("CAM1_RELEASE_FEED", 80.0), "camera #1 auto-release feed")
	flag.Parse()

	if strings.TrimSpace(cfg.Cam1MapPath) != "" && cfg.Cam1MapSteps > 0 && cfg.PTZZoomMax > cfg.Cam1MapSteps-1 {
		cfg.PTZZoomMax = cfg.Cam1MapSteps - 1
	}
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
