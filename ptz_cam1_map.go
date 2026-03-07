package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/tarm/serial"
)

var (
	mposRe = regexp.MustCompile(`MPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)`)
	wposRe = regexp.MustCompile(`WPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)`)
	wcoRe  = regexp.MustCompile(`WCO:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)`)
	pnRe   = regexp.MustCompile(`Pn:([A-Z]+)`)
)

type Cam1Map struct {
	Path       string
	CoordSpace string
	XPreload   float64
	ZoomX      []float64
	FocusY     []*float64
}

func (m *Cam1Map) MaxIndex() int {
	if m == nil {
		return -1
	}
	return len(m.ZoomX) - 1
}

type cam1MapFile struct {
	Meta struct {
		CoordSpace string   `json:"coord_space"`
		XPreload   *float64 `json:"x_preload"`
	} `json:"meta"`
	ZoomX  []float64  `json:"zoomX"`
	FocusY []*float64 `json:"focusY"`
}

type cam1HomeConfig struct {
	Reset          bool
	LimitLED       bool
	IrisOpen       bool
	HomeFocus      bool
	HomeTimeout    time.Duration
	BackoffX       float64
	BackoffY       float64
	BackoffFeed    float64
	StartX         float64
	StartY         float64
	GotoFeed       float64
	AutoRelease    bool
	ReleaseStepX   float64
	ReleaseStepY   float64
	ReleaseMaxStep int
	ReleaseFeed    float64
}

func loadCam1Map(path string, steps int) (*Cam1Map, error) {
	path = strings.TrimSpace(path)
	if path == "" {
		return nil, nil
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read map %s: %w", path, err)
	}

	var mf cam1MapFile
	if err := json.Unmarshal(raw, &mf); err != nil {
		return nil, fmt.Errorf("parse map %s: %w", path, err)
	}
	if len(mf.ZoomX) == 0 {
		return nil, fmt.Errorf("map %s has empty zoomX", path)
	}

	useN := len(mf.ZoomX)
	if steps > 0 {
		if steps > len(mf.ZoomX) {
			return nil, fmt.Errorf("map %s has %d zoom points, but CAM1_MAP_STEPS=%d", path, len(mf.ZoomX), steps)
		}
		useN = steps
	}

	coord := strings.ToLower(strings.TrimSpace(mf.Meta.CoordSpace))
	if coord == "" {
		coord = "wpos"
	}
	if coord != "wpos" && coord != "mpos" {
		return nil, fmt.Errorf("map %s has unsupported coord_space=%q (expected wpos or mpos)", path, coord)
	}

	preload := 0.02
	if mf.Meta.XPreload != nil {
		preload = *mf.Meta.XPreload
	}

	zoom := append([]float64(nil), mf.ZoomX[:useN]...)
	focus := make([]*float64, useN)
	for i := 0; i < useN; i++ {
		if i >= len(mf.FocusY) || mf.FocusY[i] == nil {
			continue
		}
		v := *mf.FocusY[i]
		focus[i] = &v
	}

	return &Cam1Map{
		Path:       path,
		CoordSpace: coord,
		XPreload:   preload,
		ZoomX:      zoom,
		FocusY:     focus,
	}, nil
}

func parseStatusState(line string) string {
	if !strings.HasPrefix(line, "<") {
		return ""
	}
	s := strings.TrimPrefix(line, "<")
	if i := strings.IndexByte(s, '|'); i >= 0 {
		s = s[:i]
	}
	if i := strings.IndexByte(s, '>'); i >= 0 {
		s = s[:i]
	}
	return strings.TrimSpace(s)
}

func parse4(line string, re *regexp.Regexp) (float64, float64, float64, float64, bool) {
	m := re.FindStringSubmatch(line)
	if len(m) != 5 {
		return 0, 0, 0, 0, false
	}
	var vals [4]float64
	for i := 0; i < 4; i++ {
		var v float64
		if _, err := fmt.Sscanf(m[i+1], "%f", &v); err != nil {
			return 0, 0, 0, 0, false
		}
		vals[i] = v
	}
	return vals[0], vals[1], vals[2], vals[3], true
}

func parseMPos(line string) (float64, float64, float64, float64, bool) {
	return parse4(line, mposRe)
}

func parseWPos(line string) (float64, float64, float64, float64, bool) {
	if x, y, z, a, ok := parse4(line, wposRe); ok {
		return x, y, z, a, true
	}
	mx, my, mz, ma, mok := parseMPos(line)
	wx, wy, wz, wa, wok := parse4(line, wcoRe)
	if !mok || !wok {
		return 0, 0, 0, 0, false
	}
	return mx - wx, my - wy, mz - wz, ma - wa, true
}

func parseLimitAxes(line string) map[string]bool {
	out := map[string]bool{}
	m := pnRe.FindStringSubmatch(line)
	if len(m) != 2 {
		return out
	}
	for _, ch := range m[1] {
		out[string(ch)] = true
	}
	return out
}

func (p *PTZ) waitForIdle(timeout time.Duration) ([]string, error) {
	deadline := time.Now().Add(timeout)
	var last []string
	for time.Now().Before(deadline) {
		statusLines, err := p.queryStatus()
		if err != nil {
			last = statusLines
			time.Sleep(70 * time.Millisecond)
			continue
		}
		last = statusLines
		st := statusLine(statusLines)
		state := strings.ToLower(parseStatusState(st))
		if state == "idle" {
			return statusLines, nil
		}
		if strings.HasPrefix(state, "alarm") {
			return statusLines, fmt.Errorf("controller alarm: %s", st)
		}
		time.Sleep(70 * time.Millisecond)
	}
	return last, fmt.Errorf("timeout waiting for idle")
}

func (p *PTZ) moveAbsWPos(x *float64, y *float64, feed float64, timeout time.Duration) ([]string, []string, error) {
	if x == nil && y == nil {
		return nil, nil, nil
	}
	parts := make([]string, 0, 3)
	if x != nil {
		parts = append(parts, fmt.Sprintf("X%.3f", *x))
	}
	if y != nil {
		parts = append(parts, fmt.Sprintf("Y%.3f", *y))
	}
	cmd := fmt.Sprintf("G1 %s F%.1f", strings.Join(parts, " "), feed)

	r1, err := p.commandOK("G90")
	if err != nil {
		return r1, nil, err
	}
	r2, err := p.commandOK(cmd)
	if err != nil {
		return append(r1, r2...), nil, err
	}
	st, err := p.waitForIdle(timeout)
	return append(r1, r2...), st, err
}

func (p *PTZ) moveRel(dx *float64, dy *float64, feed float64, timeout time.Duration) ([]string, []string, error) {
	if dx == nil && dy == nil {
		return nil, nil, nil
	}
	parts := make([]string, 0, 3)
	if dx != nil {
		parts = append(parts, fmt.Sprintf("X%.3f", *dx))
	}
	if dy != nil {
		parts = append(parts, fmt.Sprintf("Y%.3f", *dy))
	}
	moveCmd := fmt.Sprintf("G1 %s F%.1f", strings.Join(parts, " "), feed)

	r1, err := p.commandOK("G91")
	if err != nil {
		return r1, nil, err
	}
	r2, err := p.commandOK(moveCmd)
	if err != nil {
		_, _ = p.commandOK("G90")
		return append(r1, r2...), nil, err
	}
	r3, err := p.commandOK("G90")
	if err != nil {
		return append(append(r1, r2...), r3...), nil, err
	}
	st, err := p.waitForIdle(timeout)
	return append(append(r1, r2...), r3...), st, err
}

func (p *PTZ) moveToMPos(x *float64, y *float64, feed float64, timeout time.Duration) ([]string, []string, error) {
	if x == nil && y == nil {
		return nil, nil, nil
	}

	statusLines, err := p.queryStatus()
	if err != nil {
		return nil, statusLines, err
	}
	st := statusLine(statusLines)
	curX, curY, _, _, ok := parseMPos(st)
	if !ok {
		return nil, statusLines, fmt.Errorf("cannot parse MPos from status: %s", st)
	}

	var dx *float64
	var dy *float64
	if x != nil {
		v := *x - curX
		dx = &v
	}
	if y != nil {
		v := *y - curY
		dy = &v
	}
	return p.moveRel(dx, dy, feed, timeout)
}

func (p *PTZ) cam1MapState() map[string]any {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cam1Map == nil {
		return map[string]any{"enabled": false, "homed": p.cam1Homed}
	}
	return map[string]any{
		"enabled":       true,
		"path":          p.cam1Map.Path,
		"coordSpace":    p.cam1Map.CoordSpace,
		"xPreload":      p.cam1Map.XPreload,
		"points":        len(p.cam1Map.ZoomX),
		"maxIndex":      p.cam1Map.MaxIndex(),
		"currentIndex":  p.cam1CurrentIndex,
		"homed":         p.cam1Homed,
		"focusFineStep": p.cam1FocusFineStep,
	}
}

func (p *PTZ) cam1MapMeta() (enabled bool, coord string, homed bool, focusFineStep float64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cam1Map == nil {
		return false, "", p.cam1Homed, p.cam1FocusFineStep
	}
	return true, p.cam1Map.CoordSpace, p.cam1Homed, p.cam1FocusFineStep
}

func (p *PTZ) cam1MapMaxIndex() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cam1Map == nil {
		return -1
	}
	return p.cam1Map.MaxIndex()
}

func (p *PTZ) cam1MapCurrentIndex() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.cam1CurrentIndex
}

func (p *PTZ) gotoCam1MapIndex(idx int) (map[string]any, error) {
	p.mu.Lock()
	m := p.cam1Map
	feed := p.cam1MapFeed
	homed := p.cam1Homed
	p.mu.Unlock()
	if m == nil {
		return nil, errors.New("cam1 map is not configured")
	}
	if !homed {
		return nil, errors.New("cam1 map is not homed yet. Run /api/cam1/home first")
	}
	if idx < 0 || idx > m.MaxIndex() {
		return nil, fmt.Errorf("index must be in range 0..%d", m.MaxIndex())
	}

	targetX := m.ZoomX[idx]
	var targetY *float64
	if idx < len(m.FocusY) && m.FocusY[idx] != nil {
		y := *m.FocusY[idx]
		targetY = &y
	}

	var allReply []string
	var statusLines []string
	move := func(x *float64, y *float64) error {
		var reply []string
		var st []string
		var err error
		if m.CoordSpace == "mpos" {
			reply, st, err = p.moveToMPos(x, y, feed, 20*time.Second)
		} else {
			reply, st, err = p.moveAbsWPos(x, y, feed, 20*time.Second)
		}
		allReply = append(allReply, reply...)
		if len(st) > 0 {
			statusLines = st
		}
		return err
	}

	if m.XPreload > 0 {
		preX := targetX - math.Abs(m.XPreload)
		if err := move(&preX, nil); err != nil {
			return nil, err
		}
	}
	if err := move(&targetX, nil); err != nil {
		return nil, err
	}
	if targetY != nil {
		if err := move(nil, targetY); err != nil {
			return nil, err
		}
	}
	if len(statusLines) == 0 {
		st, err := p.queryStatus()
		if err == nil {
			statusLines = st
		}
	}

	p.mu.Lock()
	p.cam1CurrentIndex = idx
	p.logicalZoom = clamp(idx, 0, p.zoomMax)
	p.mu.Unlock()

	resp := map[string]any{
		"mapEnabled":  true,
		"mapIndex":    idx,
		"mapMaxIndex": m.MaxIndex(),
		"targetX":     targetX,
		"coordSpace":  m.CoordSpace,
		"xPreload":    m.XPreload,
		"replyLines":  allReply,
		"statusReply": statusLine(statusLines),
		"statusLines": statusLines,
	}
	if targetY != nil {
		resp["targetY"] = *targetY
	}
	return resp, nil
}

func (p *PTZ) runCam1StartFlow() (map[string]any, error) {
	p.mu.Lock()
	flow := p.cam1HomeCfg
	p.mu.Unlock()

	logSteps := make([]string, 0, 16)
	logSteps = append(logSteps, "=== START FLOW ===")

	if flow.Reset {
		logSteps = append(logSteps, "1) RESET")
		if err := p.ctrlXResetAndReconnect(1 * time.Second); err != nil {
			return nil, err
		}
	} else {
		logSteps = append(logSteps, "1) RESET skipped")
	}

	logSteps = append(logSteps, "2) UNLOCK ($X)")
	if _, err := p.commandOK("$X"); err != nil {
		return nil, err
	}
	if _, err := p.commandOK("G90"); err != nil {
		return nil, err
	}

	if flow.LimitLED {
		logSteps = append(logSteps, "3) LIMIT LED ON (M120 P1)")
		if _, err := p.commandOK("M120 P1"); err != nil {
			return nil, err
		}
	} else {
		logSteps = append(logSteps, "3) LIMIT LED skipped")
	}

	if flow.IrisOpen {
		logSteps = append(logSteps, "4) IRIS OPEN (M114 P1)")
		if _, err := p.commandOK("M114 P1"); err != nil {
			return nil, err
		}
	} else {
		logSteps = append(logSteps, "4) IRIS OPEN skipped")
	}

	logSteps = append(logSteps, "5) HOME ZOOM ($HX)")
	if _, err := p.commandOK("$HX"); err != nil {
		return nil, err
	}
	if _, err := p.waitForIdle(flow.HomeTimeout); err != nil {
		return nil, err
	}

	if flow.HomeFocus {
		logSteps = append(logSteps, "6) HOME FOCUS ($HY)")
		if _, err := p.commandOK("$HY"); err != nil {
			return nil, err
		}
		if _, err := p.waitForIdle(flow.HomeTimeout); err != nil {
			return nil, err
		}
	} else {
		logSteps = append(logSteps, "6) HOME FOCUS skipped")
	}

	logSteps = append(logSteps, "7) BACKOFF")
	if _, _, err := p.moveRel(&flow.BackoffX, &flow.BackoffY, flow.BackoffFeed, 10*time.Second); err != nil {
		return nil, err
	}

	logSteps = append(logSteps, fmt.Sprintf("8) GOTO START X=%.3f Y=%.3f", flow.StartX, flow.StartY))
	if _, _, err := p.moveAbsWPos(&flow.StartX, &flow.StartY, flow.GotoFeed, 20*time.Second); err != nil {
		return nil, err
	}

	if flow.AutoRelease {
		logSteps = append(logSteps, "8b) AUTO RELEASE LIMITS")
		if err := p.autoReleaseCam1Limits(flow.ReleaseStepX, flow.ReleaseStepY, flow.ReleaseMaxStep, flow.ReleaseFeed); err != nil {
			return nil, err
		}
	} else {
		logSteps = append(logSteps, "8b) AUTO RELEASE LIMITS skipped")
	}

	logSteps = append(logSteps, "9) SET X0 Y0 (G92 X0 Y0)")
	if _, err := p.commandOK("G92 X0 Y0"); err != nil {
		return nil, err
	}
	statusLines, err := p.queryStatus()
	if err != nil {
		return nil, err
	}

	p.mu.Lock()
	p.cam1CurrentIndex = 0
	p.logicalZoom = 0
	p.logicalFocus = 0
	p.cam1Homed = true
	p.mu.Unlock()

	resp := map[string]any{
		"ok":          true,
		"flow":        logSteps,
		"statusReply": statusLine(statusLines),
		"statusLines": statusLines,
	}
	return resp, nil
}

func (p *PTZ) ctrlXResetAndReconnect(wait time.Duration) error {
	p.mu.Lock()
	if p.port == nil {
		p.mu.Unlock()
		return errors.New("serial port closed")
	}
	if _, err := p.port.Write([]byte{0x18}); err != nil {
		p.mu.Unlock()
		return fmt.Errorf("ctrl-x reset write failed: %w", err)
	}
	p.mu.Unlock()

	time.Sleep(wait)

	// GRBL-based controllers can drop the serial endpoint after Ctrl-X.
	// Re-open the port to avoid EOF on first command after reset.
	if err := p.reopenSerial(); err != nil {
		return fmt.Errorf("reopen serial after reset failed: %w", err)
	}
	return nil
}

func (p *PTZ) reopenSerial() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.port != nil {
		_ = p.port.Close()
		p.port = nil
	}

	sp, err := serial.OpenPort(&serial.Config{
		Name:        p.serialPath,
		Baud:        p.serialBaud,
		ReadTimeout: 120 * time.Millisecond,
	})
	if err != nil {
		return err
	}
	p.port = sp

	_, _ = p.port.Write([]byte("\r\n\r\n"))
	time.Sleep(200 * time.Millisecond)
	_ = p.readAvailableLocked(500 * time.Millisecond)
	return nil
}

func (p *PTZ) autoReleaseCam1Limits(stepX, stepY float64, maxSteps int, feed float64) error {
	statusLines, err := p.queryStatus()
	if err != nil {
		return err
	}
	lim := parseLimitAxes(statusLine(statusLines))
	if len(lim) == 0 {
		return nil
	}
	if lim["X"] {
		ok, err := p.releaseCam1LimitAxis("X", stepX, maxSteps, feed)
		if err != nil {
			return err
		}
		if !ok {
			log.Printf("warning: X limit still active after auto-release")
		}
	}
	if lim["Y"] {
		ok, err := p.releaseCam1LimitAxis("Y", stepY, maxSteps, feed)
		if err != nil {
			return err
		}
		if !ok {
			return errors.New("could not release Y limit automatically")
		}
	}
	return nil
}

func (p *PTZ) releaseCam1LimitAxis(axis string, step float64, maxSteps int, feed float64) (bool, error) {
	axis = strings.ToUpper(strings.TrimSpace(axis))
	if axis != "X" && axis != "Y" {
		return false, fmt.Errorf("unsupported axis %q", axis)
	}
	if maxSteps <= 0 || step == 0 {
		return false, nil
	}
	step = math.Abs(step)

	checkReleased := func() (bool, error) {
		statusLines, err := p.queryStatus()
		if err != nil {
			return false, err
		}
		lim := parseLimitAxes(statusLine(statusLines))
		return !lim[axis], nil
	}

	if ok, err := checkReleased(); err != nil || ok {
		return ok, err
	}

	for _, dir := range []float64{1.0, -1.0} {
		for i := 0; i < maxSteps; i++ {
			d := dir * step
			var dx *float64
			var dy *float64
			if axis == "X" {
				dx = &d
			} else {
				dy = &d
			}
			if _, _, err := p.moveRel(dx, dy, feed, 10*time.Second); err != nil {
				return false, err
			}
			ok, err := checkReleased()
			if err != nil {
				return false, err
			}
			if ok {
				return true, nil
			}
		}
	}
	return false, nil
}
