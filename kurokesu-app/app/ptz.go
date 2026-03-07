package main

import (
	"fmt"
	"log"
	"math"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/tarm/serial"
)

var (
	mposRe = regexp.MustCompile(`MPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)`)
	wposRe = regexp.MustCompile(`WPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)`)
	wcoRe  = regexp.MustCompile(`WCO:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)`)
	pnRe   = regexp.MustCompile(`Pn:([A-Z]+)`)
)

type homeConfig struct {
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

type PTZ struct {
	opMu          sync.Mutex
	mu            sync.Mutex
	port          *serial.Port
	serialPath    string
	serialBaud    int
	cmdTimeout    time.Duration
	zoomMap       *ZoomMap
	mapFeed       float64
	focusFineStep float64
	home          homeConfig
	currentIndex  int
	homed         bool
	softWCO       *[4]float64
}

func newPTZ(cfg Config) (*PTZ, error) {
	zoomMap, err := loadZoomMap(cfg.MapPath, cfg.MapSteps, cfg.StrictMapLimits)
	if err != nil {
		return nil, fmt.Errorf("load zoom map: %w", err)
	}

	serialPath := resolveSerialPath(cfg.PTZSerial, cfg.PTZSerialFallback)
	sp, err := serial.OpenPort(&serial.Config{
		Name:        serialPath,
		Baud:        cfg.PTZBaud,
		ReadTimeout: 120 * time.Millisecond,
	})
	if err != nil {
		return nil, fmt.Errorf("open serial %s: %w", serialPath, err)
	}

	p := &PTZ{
		port:          sp,
		serialPath:    serialPath,
		serialBaud:    cfg.PTZBaud,
		cmdTimeout:    3 * time.Second,
		zoomMap:       zoomMap,
		mapFeed:       cfg.MapFeed,
		focusFineStep: cfg.FocusFineStep,
		home: homeConfig{
			Reset:          cfg.Reset,
			LimitLED:       cfg.LimitLED,
			IrisOpen:       cfg.IrisOpen,
			HomeFocus:      cfg.HomeFocus,
			HomeTimeout:    time.Duration(cfg.HomeTimeout * float64(time.Second)),
			BackoffX:       cfg.BackoffX,
			BackoffY:       cfg.BackoffY,
			BackoffFeed:    cfg.BackoffFeed,
			StartX:         cfg.StartX,
			StartY:         cfg.StartY,
			GotoFeed:       cfg.GotoFeed,
			AutoRelease:    cfg.AutoRelease,
			ReleaseStepX:   cfg.ReleaseStepX,
			ReleaseStepY:   cfg.ReleaseStepY,
			ReleaseMaxStep: cfg.ReleaseMaxSteps,
			ReleaseFeed:    cfg.ReleaseFeed,
		},
	}

	if err := p.wakeSerial(); err != nil {
		_ = sp.Close()
		return nil, fmt.Errorf("wake serial %s: %w", serialPath, err)
	}

	g90Lines, statusLines, err := p.startupHandshake(5)
	if err != nil {
		_ = sp.Close()
		return nil, fmt.Errorf("startup handshake failed: %w", err)
	}
	log.Printf(
		"ptz ready serial=%s requested_serial=%s fallback_serial=%s g90_reply=%v status=%v map_points=%d source_points=%d selected_flags=%v source_flags=%v",
		serialPath, cfg.PTZSerial, cfg.PTZSerialFallback, g90Lines, statusLines, len(zoomMap.ZoomX), zoomMap.SourcePoints, zoomMap.SelectedFlagged, zoomMap.SourceFlaggedIndices,
	)
	return p, nil
}

func (p *PTZ) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.port == nil {
		return nil
	}
	err := p.port.Close()
	p.port = nil
	return err
}

func (p *PTZ) startupHandshake(maxAttempts int) (g90Lines []string, statusLines []string, err error) {
	if maxAttempts < 1 {
		maxAttempts = 1
	}

	var lastErr error
	gotG90 := false
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		p.mu.Lock()
		startupLines := p.readAvailableLocked(450 * time.Millisecond)
		p.mu.Unlock()
		if len(startupLines) > 0 {
			log.Printf("ptz startup banner attempt=%d lines=%v", attempt, startupLines)
		}

		g90Lines, err = p.commandOK("G90")
		if err != nil {
			lastErr = fmt.Errorf("G90 attempt %d: %w (reply=%v)", attempt, err, g90Lines)
			log.Printf("ptz startup: %v", lastErr)
			if attempt < maxAttempts {
				_ = p.reopenSerial()
				time.Sleep(250 * time.Millisecond)
			}
			continue
		}
		gotG90 = true

		statusLines, err = p.queryStatus()
		if err == nil {
			return g90Lines, statusLines, nil
		}

		lastErr = fmt.Errorf("status ? attempt %d: %w (reply=%v)", attempt, err, statusLines)
		log.Printf("ptz startup: %v", lastErr)
		if attempt < maxAttempts {
			_ = p.reopenSerial()
			time.Sleep(250 * time.Millisecond)
		}
	}

	if gotG90 {
		log.Printf("ptz startup: proceeding without initial status after retries; last_err=%v", lastErr)
		return g90Lines, statusLines, nil
	}
	return g90Lines, statusLines, lastErr
}

func (p *PTZ) mapState() map[string]any {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.mapStateLocked()
}

func (p *PTZ) mapStateLocked() map[string]any {
	if p.zoomMap == nil {
		return map[string]any{"enabled": false, "homed": p.homed}
	}
	return map[string]any{
		"enabled":              true,
		"path":                 p.zoomMap.Path,
		"coordSpace":           p.zoomMap.CoordSpace,
		"xPreload":             p.zoomMap.XPreload,
		"points":               len(p.zoomMap.ZoomX),
		"sourcePoints":         p.zoomMap.SourcePoints,
		"maxIndex":             p.zoomMap.MaxIndex(),
		"currentIndex":         p.currentIndex,
		"homed":                p.homed,
		"focusFineStep":        p.focusFineStep,
		"sourceFlaggedIndices": append([]int(nil), p.zoomMap.SourceFlaggedIndices...),
		"selectedFlagged":      append([]int(nil), p.zoomMap.SelectedFlagged...),
	}
}

func (p *PTZ) statusResponse() map[string]any {
	p.opMu.Lock()
	defer p.opMu.Unlock()

	status, err := p.queryStatus()
	resp := map[string]any{
		"available": true,
		"mapState":  p.mapState(),
	}
	if err != nil {
		resp["error"] = err.Error()
		resp["statusReply"] = statusLine(status)
		resp["statusLines"] = status
		return resp
	}
	resp["statusReply"] = statusLine(status)
	resp["statusLines"] = status
	st := statusLine(status)
	if x, y, _, _, ok := parseMPos(st); ok {
		resp["mposX"] = x
		resp["mposY"] = y
	}
	if x, y, _, _, ok := p.parseWPos(st); ok {
		resp["wposX"] = x
		resp["wposY"] = y
	}
	lim := parseLimitAxes(st)
	if len(lim) > 0 {
		axes := make([]string, 0, len(lim))
		for _, a := range []string{"X", "Y", "Z", "A", "R"} {
			if lim[a] {
				axes = append(axes, a)
			}
		}
		resp["limits"] = strings.Join(axes, "")
	}
	return resp
}

func (p *PTZ) gotoIndex(idx int) (map[string]any, error) {
	p.opMu.Lock()
	defer p.opMu.Unlock()

	p.mu.Lock()
	m := p.zoomMap
	feed := p.mapFeed
	homed := p.homed
	p.mu.Unlock()

	if m == nil {
		return nil, fmt.Errorf("zoom map is not configured")
	}
	if !homed {
		return nil, fmt.Errorf("zoom map is not homed yet. Run /api/home first")
	}
	if idx < 0 || idx > m.MaxIndex() {
		return nil, fmt.Errorf("index must be in range 0..%d", m.MaxIndex())
	}
	if flag := strings.TrimSpace(m.LimitXY[idx]); flag != "" {
		return nil, fmt.Errorf("map index %d is flagged with limitXY=%s", idx, flag)
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
	p.currentIndex = idx
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
		"mapState":    p.mapState(),
	}
	if targetY != nil {
		resp["targetY"] = *targetY
	}
	return resp, nil
}

func (p *PTZ) focus(set *float64, delta *int) (map[string]any, error) {
	p.opMu.Lock()
	defer p.opMu.Unlock()

	p.mu.Lock()
	m := p.zoomMap
	fineStep := p.focusFineStep
	homed := p.homed
	feed := p.mapFeed
	p.mu.Unlock()

	if m == nil {
		return nil, fmt.Errorf("zoom map is not configured")
	}
	if !homed {
		return nil, fmt.Errorf("zoom map is not homed yet. Run /api/home first")
	}
	if fineStep <= 0 {
		fineStep = 0.05
	}

	var reply []string
	var status []string
	var err error
	if delta != nil {
		if *delta != -1 && *delta != 1 {
			return nil, fmt.Errorf("delta must be -1 or +1")
		}
		dy := float64(*delta) * fineStep
		reply, status, err = p.moveRel(nil, &dy, feed, 10*time.Second)
	} else {
		targetY := *set
		if m.CoordSpace == "mpos" {
			reply, status, err = p.moveToMPos(nil, &targetY, feed, 20*time.Second)
		} else {
			reply, status, err = p.moveAbsWPos(nil, &targetY, feed, 20*time.Second)
		}
	}
	if err != nil {
		return nil, err
	}

	resp := map[string]any{
		"ok":          true,
		"coordSpace":  m.CoordSpace,
		"focusStep":   fineStep,
		"replyLines":  reply,
		"statusReply": statusLine(status),
		"statusLines": status,
		"mapState":    p.mapState(),
	}
	if set != nil {
		resp["targetY"] = *set
	}
	if delta != nil {
		resp["delta"] = *delta
	}
	return resp, nil
}

func (p *PTZ) runStartFlow() (map[string]any, error) {
	p.opMu.Lock()
	defer p.opMu.Unlock()

	p.mu.Lock()
	flow := p.home
	p.mu.Unlock()

	logSteps := []string{"=== START FLOW ==="}
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
	if _, err := p.commandLoose("$HX", 3*time.Second); err != nil {
		return nil, err
	}
	if _, err := p.waitForIdle(flow.HomeTimeout); err != nil {
		return nil, err
	}

	if flow.HomeFocus {
		logSteps = append(logSteps, "6) HOME FOCUS ($HY)")
		if _, err := p.commandLoose("$HY", 3*time.Second); err != nil {
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
		if err := p.autoReleaseLimits(flow.ReleaseStepX, flow.ReleaseStepY, flow.ReleaseMaxStep, flow.ReleaseFeed); err != nil {
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
	p.currentIndex = 0
	p.homed = true
	p.mu.Unlock()

	return map[string]any{
		"ok":          true,
		"flow":        logSteps,
		"statusReply": statusLine(statusLines),
		"statusLines": statusLines,
		"mapState":    p.mapState(),
	}, nil
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

func parseWPosWithSoftWCO(line string, soft *[4]float64) (float64, float64, float64, float64, bool) {
	if x, y, z, a, ok := parseWPos(line); ok {
		return x, y, z, a, true
	}
	if soft == nil {
		return 0, 0, 0, 0, false
	}
	mx, my, mz, ma, ok := parseMPos(line)
	if !ok {
		return 0, 0, 0, 0, false
	}
	return mx - soft[0], my - soft[1], mz - soft[2], ma - soft[3], true
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

func (p *PTZ) autoReleaseLimits(stepX, stepY float64, maxSteps int, feed float64) error {
	statusLines, err := p.queryStatus()
	if err != nil {
		return err
	}
	lim := parseLimitAxes(statusLine(statusLines))
	if len(lim) == 0 {
		return nil
	}
	if lim["X"] {
		ok, err := p.releaseLimitAxis("X", stepX, maxSteps, feed)
		if err != nil {
			return err
		}
		if !ok {
			log.Printf("warning: X limit still active after auto-release")
		}
	}
	if lim["Y"] {
		ok, err := p.releaseLimitAxis("Y", stepY, maxSteps, feed)
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("could not release Y limit automatically")
		}
	}
	return nil
}

func (p *PTZ) releaseLimitAxis(axis string, step float64, maxSteps int, feed float64) (bool, error) {
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

func (p *PTZ) ctrlXResetAndReconnect(wait time.Duration) error {
	p.mu.Lock()
	if p.port == nil {
		p.mu.Unlock()
		return fmt.Errorf("serial port closed")
	}
	if _, err := p.port.Write([]byte{0x18}); err != nil {
		p.mu.Unlock()
		return fmt.Errorf("ctrl-x reset write failed: %w", err)
	}
	p.mu.Unlock()

	time.Sleep(wait)
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
	p.primeSerialLocked()
	return nil
}

func (p *PTZ) wakeSerial() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.port == nil {
		return fmt.Errorf("serial port closed")
	}
	p.primeSerialLocked()
	return nil
}

func (p *PTZ) primeSerialLocked() {
	if p.port == nil {
		return
	}
	_, _ = p.port.Write([]byte("\r\n\r\n"))
	time.Sleep(350 * time.Millisecond)
	_ = p.readAvailableLocked(650 * time.Millisecond)
}

func (p *PTZ) queryStatus() ([]string, error) {
	status, err := p.queryStatusOnce()
	p.rememberStatus(statusLine(status))
	if err == nil || !isRetryableSerialErr(err) {
		return status, err
	}
	log.Printf("ptz status transient err=%v; reopening serial and retrying", err)
	if reopenErr := p.reopenSerial(); reopenErr != nil {
		return status, fmt.Errorf("%w; reopen failed: %v", err, reopenErr)
	}
	status, err = p.queryStatusOnce()
	p.rememberStatus(statusLine(status))
	return status, err
}

func (p *PTZ) queryStatusOnce() ([]string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sendExpectStatusLocked("?")
}

func (p *PTZ) commandOK(cmd string) ([]string, error) {
	lines, err := p.commandOKOnce(cmd)
	if err == nil || !isRetryableSerialErr(err) {
		return lines, err
	}
	log.Printf("ptz command transient cmd=%q err=%v; reopening serial and retrying", cmd, err)
	if reopenErr := p.reopenSerial(); reopenErr != nil {
		return lines, fmt.Errorf("%w; reopen failed: %v", err, reopenErr)
	}
	return p.commandOKOnce(cmd)
}

func (p *PTZ) commandLoose(cmd string, wait time.Duration) ([]string, error) {
	lines, err := p.commandLooseOnce(cmd, wait)
	if err == nil || !isRetryableSerialErr(err) {
		return lines, err
	}
	log.Printf("ptz loose command transient cmd=%q err=%v; reopening serial and retrying", cmd, err)
	if reopenErr := p.reopenSerial(); reopenErr != nil {
		return lines, fmt.Errorf("%w; reopen failed: %v", err, reopenErr)
	}
	return p.commandLooseOnce(cmd, wait)
}

func (p *PTZ) commandOKOnce(cmd string) ([]string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sendExpectOKLocked(cmd)
}

func (p *PTZ) commandLooseOnce(cmd string, wait time.Duration) ([]string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sendAllowMissingOKLocked(cmd, wait)
}

func (p *PTZ) sendExpectOKLocked(cmd string) ([]string, error) {
	if err := p.writeLineLocked(cmd); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(p.cmdTimeout)
	lines := make([]string, 0, 4)
	for {
		line, err := p.readLineLocked(deadline)
		if err != nil {
			return lines, fmt.Errorf("wait ok for %q: %w", cmd, err)
		}
		if line == "" {
			continue
		}
		lines = append(lines, line)
		lc := strings.ToLower(line)
		if lc == "ok" || strings.HasPrefix(lc, "ok ") {
			return lines, nil
		}
		if strings.HasPrefix(lc, "error") {
			return lines, fmt.Errorf(line)
		}
	}
}

func (p *PTZ) sendAllowMissingOKLocked(cmd string, wait time.Duration) ([]string, error) {
	if err := p.writeLineLocked(cmd); err != nil {
		return nil, err
	}
	if wait <= 0 {
		wait = 250 * time.Millisecond
	}
	lines := p.readAvailableLocked(wait)
	if bad, ok := firstFatalReplyLine(lines); ok {
		return lines, fmt.Errorf(bad)
	}
	return lines, nil
}

func (p *PTZ) sendExpectStatusLocked(cmd string) ([]string, error) {
	if err := p.writeLineLocked(cmd); err != nil {
		return nil, err
	}
	// Match the Python runtime: give the controller a short moment to emit all
	// queued status lines, then use the last status from the batch.
	time.Sleep(120 * time.Millisecond)

	deadline := time.Now().Add(p.cmdTimeout)
	lines := make([]string, 0, 4)
	for time.Now().Before(deadline) {
		lines = append(lines, p.readAvailableLocked(180*time.Millisecond)...)
		if st := statusLine(lines); strings.HasPrefix(st, "<") && strings.HasSuffix(st, ">") {
			return lines, nil
		}
		for _, line := range lines {
			lc := strings.ToLower(line)
			if strings.HasPrefix(lc, "error") {
				return lines, fmt.Errorf(line)
			}
		}
		time.Sleep(40 * time.Millisecond)
	}
	return lines, fmt.Errorf("wait status for %q: timeout", cmd)
}

func (p *PTZ) writeLineLocked(cmd string) error {
	if p.port == nil {
		return fmt.Errorf("serial port closed")
	}
	cmd = strings.TrimSpace(cmd)
	if cmd == "" {
		return fmt.Errorf("empty command")
	}
	payload := []byte(cmd + "\r\n")
	n, err := p.port.Write(payload)
	if err != nil {
		return fmt.Errorf("write %q failed: %w", cmd, err)
	}
	if n != len(payload) {
		return fmt.Errorf("short write for %q: %d/%d", cmd, n, len(payload))
	}
	return nil
}

func (p *PTZ) readLineLocked(deadline time.Time) (string, error) {
	if p.port == nil {
		return "", fmt.Errorf("serial port closed")
	}
	var b [1]byte
	var sb strings.Builder
	for {
		if time.Now().After(deadline) {
			if sb.Len() > 0 {
				return strings.TrimSpace(sb.String()), nil
			}
			return "", fmt.Errorf("timeout")
		}
		n, err := p.port.Read(b[:])
		if err != nil {
			return "", err
		}
		if n == 0 {
			continue
		}
		c := b[0]
		if c == '\r' {
			continue
		}
		if c == '\n' {
			line := strings.TrimSpace(sb.String())
			sb.Reset()
			if line == "" {
				continue
			}
			return line, nil
		}
		sb.WriteByte(c)
	}
}

func (p *PTZ) readAvailableLocked(window time.Duration) []string {
	out := make([]string, 0, 8)
	deadline := time.Now().Add(window)
	for {
		line, err := p.readLineLocked(deadline)
		if err != nil {
			break
		}
		if line != "" {
			out = append(out, line)
		}
		if time.Now().After(deadline) {
			break
		}
	}
	return out
}

func isRetryableSerialErr(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "eof") ||
		strings.Contains(msg, "input/output error") ||
		strings.Contains(msg, "serial port closed") ||
		strings.Contains(msg, "device or resource busy")
}

func statusLine(lines []string) string {
	for i := len(lines) - 1; i >= 0; i-- {
		if strings.HasPrefix(lines[i], "<") {
			return lines[i]
		}
	}
	if len(lines) == 0 {
		return ""
	}
	return lines[len(lines)-1]
}

func firstFatalReplyLine(lines []string) (string, bool) {
	for _, line := range lines {
		lc := strings.ToLower(line)
		if strings.HasPrefix(lc, "error") || strings.HasPrefix(lc, "alarm") {
			return line, true
		}
	}
	return "", false
}

func resolveSerialPath(primary, fallback string) string {
	primary = strings.TrimSpace(primary)
	fallback = strings.TrimSpace(fallback)
	if pathExists(primary) {
		return primary
	}
	if fallback != "" && fallback != primary && fallback != "/dev/serial/by-id/" && pathExists(fallback) {
		return fallback
	}
	if fallback == "/dev/serial/by-id/" {
		if match := firstExistingSerialByID(); match != "" {
			return match
		}
	}
	return primary
}

func pathExists(path string) bool {
	if strings.TrimSpace(path) == "" {
		return false
	}
	_, err := os.Stat(path)
	return err == nil
}

func firstExistingSerialByID() string {
	const dir = "/dev/serial/by-id"
	entries, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		path := dir + "/" + entry.Name()
		if pathExists(path) {
			return path
		}
	}
	return ""
}

func (p *PTZ) rememberStatus(line string) {
	if strings.TrimSpace(line) == "" {
		return
	}
	if x, y, z, a, ok := parse4(line, wcoRe); ok {
		p.mu.Lock()
		p.softWCO = &[4]float64{x, y, z, a}
		p.mu.Unlock()
	}
}

func (p *PTZ) parseWPos(line string) (float64, float64, float64, float64, bool) {
	p.mu.Lock()
	soft := p.softWCO
	p.mu.Unlock()
	return parseWPosWithSoftWCO(line, soft)
}
