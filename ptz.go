package main

import (
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/tarm/serial"
)

type PTZ struct {
	mu               sync.Mutex
	port             *serial.Port
	serialPath       string
	cmdTimeout       time.Duration
	zoomMax          int
	xPerStep         float64
	yPerStep         float64
	feed             float64
	logicalZoom      int
	logicalFocus     int
	cam1Map          *Cam1Map
	cam1MapFeed      float64
	cam1HomeCfg      cam1HomeConfig
	cam1CurrentIndex int
}

func newPTZ(cfg Config) (*PTZ, error) {
	cam1Map, err := loadCam1Map(cfg.Cam1MapPath, cfg.Cam1MapSteps)
	if err != nil {
		return nil, fmt.Errorf("load cam1 map: %w", err)
	}

	sp, err := serial.OpenPort(&serial.Config{
		Name:        cfg.PTZSerial,
		Baud:        cfg.PTZBaud,
		ReadTimeout: 120 * time.Millisecond,
	})
	if err != nil {
		return nil, fmt.Errorf("open serial %s: %w", cfg.PTZSerial, err)
	}

	p := &PTZ{
		port:         sp,
		serialPath:   cfg.PTZSerial,
		cmdTimeout:   3 * time.Second,
		zoomMax:      cfg.PTZZoomMax,
		xPerStep:     cfg.PTZXPerStep,
		yPerStep:     cfg.PTZYPerStep,
		feed:         cfg.PTZFeed,
		logicalZoom:  0,
		logicalFocus: 0,
		cam1Map:      cam1Map,
		cam1MapFeed:  cfg.Cam1MapFeed,
		cam1HomeCfg: cam1HomeConfig{
			Reset:          cfg.Cam1Reset,
			LimitLED:       cfg.Cam1LimitLED,
			IrisOpen:       cfg.Cam1IrisOpen,
			HomeFocus:      cfg.Cam1HomeFocus,
			HomeTimeout:    time.Duration(cfg.Cam1HomeTimeout * float64(time.Second)),
			BackoffX:       cfg.Cam1BackoffX,
			BackoffY:       cfg.Cam1BackoffY,
			BackoffFeed:    cfg.Cam1BackoffFeed,
			StartX:         cfg.Cam1StartX,
			StartY:         cfg.Cam1StartY,
			GotoFeed:       cfg.Cam1GotoFeed,
			AutoRelease:    cfg.Cam1AutoRelease,
			ReleaseStepX:   cfg.Cam1ReleaseStepX,
			ReleaseStepY:   cfg.Cam1ReleaseStepY,
			ReleaseMaxStep: cfg.Cam1ReleaseMaxStep,
			ReleaseFeed:    cfg.Cam1ReleaseFeed,
		},
	}
	if cam1Map != nil && cam1Map.MaxIndex() >= 0 {
		p.zoomMax = cam1Map.MaxIndex()
	}

	p.mu.Lock()
	startupLines := p.readAvailableLocked(600 * time.Millisecond)
	if len(startupLines) > 0 {
		log.Printf("ptz startup lines: %v", startupLines)
	}

	g90Lines, err := p.sendExpectOKLocked("G90")
	if err != nil {
		p.mu.Unlock()
		_ = sp.Close()
		return nil, fmt.Errorf("startup G90 failed: %w (reply=%v)", err, g90Lines)
	}
	statusLines, err := p.sendExpectStatusLocked("?")
	p.mu.Unlock()
	if err != nil {
		_ = sp.Close()
		return nil, fmt.Errorf("startup status failed: %w (reply=%v)", err, statusLines)
	}

	log.Printf("ptz ready serial=%s g90_reply=%v status=%v", cfg.PTZSerial, g90Lines, statusLines)
	if cam1Map != nil {
		log.Printf("cam1 map loaded path=%s points=%d coord=%s preload=%.3f feed=%.1f", cam1Map.Path, len(cam1Map.ZoomX), cam1Map.CoordSpace, cam1Map.XPreload, cfg.Cam1MapFeed)
	}
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

func (p *PTZ) logicalState() (zoom int, focus int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.logicalZoom, p.logicalFocus
}

func (p *PTZ) setLogicalZoom(v int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.logicalZoom = clamp(v, 0, p.zoomMax)
}

func (p *PTZ) setLogicalFocus(v int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.logicalFocus = clamp(v, 0, p.zoomMax)
}

func (p *PTZ) commandThenStatus(cmd string) (reply []string, status []string, err error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	reply, err = p.sendExpectOKLocked("G90")
	if err != nil {
		return reply, nil, err
	}
	moveReply, err := p.sendExpectOKLocked(cmd)
	if err != nil {
		return append(reply, moveReply...), nil, err
	}
	reply = append(reply, moveReply...)
	status, err = p.sendExpectStatusLocked("?")
	return reply, status, err
}

func (p *PTZ) queryStatus() ([]string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sendExpectStatusLocked("?")
}

func (p *PTZ) commandOK(cmd string) ([]string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sendExpectOKLocked(cmd)
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

func (p *PTZ) sendExpectStatusLocked(cmd string) ([]string, error) {
	if err := p.writeLineLocked(cmd); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(p.cmdTimeout)
	lines := make([]string, 0, 2)

	for {
		line, err := p.readLineLocked(deadline)
		if err != nil {
			return lines, fmt.Errorf("wait status for %q: %w", cmd, err)
		}
		if line == "" {
			continue
		}
		lines = append(lines, line)
		if strings.HasPrefix(line, "<") && strings.HasSuffix(line, ">") {
			return lines, nil
		}
		lc := strings.ToLower(line)
		if strings.HasPrefix(lc, "error") {
			return lines, fmt.Errorf(line)
		}
	}
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
