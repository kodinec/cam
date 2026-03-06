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
