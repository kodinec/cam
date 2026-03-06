package main

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	ctrlLineRe = regexp.MustCompile(`^\s*([a-z0-9_]+)\s+0x[0-9a-f]+ \(([^)]+)\)\s*:\s*(.*)$`)
	kvIntRe    = regexp.MustCompile(`([a-z_]+)=(-?\d+)`)
	lastIntRe  = regexp.MustCompile(`(-?\d+)\s*$`)
)

type v4l2Control struct {
	Name    string
	CType   string
	Min     *int
	Max     *int
	Step    *int
	Default *int
	Value   *int
}

type Cam2Zoom struct {
	mu sync.Mutex

	device    string
	step      int
	available bool
	lastErr   string

	control string
	mode    string // absolute | relative | continuous
	min     *int
	max     *int
	native  *int
	def     *int
	value   *int
}

func newCam2Zoom(cfg Config) *Cam2Zoom {
	step := cfg.Cam2ZoomStep
	if step <= 0 {
		step = 1
	}
	c := &Cam2Zoom{
		device: cfg.Cam2Device,
		step:   step,
	}
	_ = c.probeLocked()
	return c
}

func (c *Cam2Zoom) run(args ...string) (stdout string, stderr string, err error) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "v4l2-ctl", args...)
	var outB bytes.Buffer
	var errB bytes.Buffer
	cmd.Stdout = &outB
	cmd.Stderr = &errB

	if runErr := cmd.Run(); runErr != nil {
		if ctx.Err() != nil {
			return outB.String(), errB.String(), fmt.Errorf("v4l2-ctl timeout")
		}
		msg := strings.TrimSpace(errB.String())
		if msg == "" {
			msg = runErr.Error()
		}
		return outB.String(), errB.String(), fmt.Errorf("v4l2-ctl %s: %s", strings.Join(args, " "), msg)
	}

	return outB.String(), errB.String(), nil
}

func parseControlInt(v string) *int {
	n, err := strconv.Atoi(v)
	if err != nil {
		return nil
	}
	return &n
}

func parseControls(txt string) map[string]v4l2Control {
	out := make(map[string]v4l2Control)
	for _, line := range strings.Split(txt, "\n") {
		m := ctrlLineRe.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		name := strings.TrimSpace(m[1])
		ctype := strings.TrimSpace(m[2])
		rest := strings.TrimSpace(m[3])
		ctrl := v4l2Control{Name: name, CType: ctype}
		for _, kv := range kvIntRe.FindAllStringSubmatch(rest, -1) {
			key := kv[1]
			val := parseControlInt(kv[2])
			if val == nil {
				continue
			}
			switch key {
			case "min":
				ctrl.Min = val
			case "max":
				ctrl.Max = val
			case "step":
				ctrl.Step = val
			case "default":
				ctrl.Default = val
			case "value":
				ctrl.Value = val
			}
		}
		out[name] = ctrl
	}
	return out
}

func (c *Cam2Zoom) probeLocked() error {
	stdout, _, err := c.run("-d", c.device, "--list-ctrls-menus")
	if err != nil {
		c.available = false
		c.lastErr = err.Error()
		return err
	}

	ctrls := parseControls(stdout)
	choose := ""
	mode := ""
	for _, name := range []string{"zoom_absolute", "zoom_relative", "zoom_continuous"} {
		if _, ok := ctrls[name]; !ok {
			continue
		}
		choose = name
		switch name {
		case "zoom_absolute":
			mode = "absolute"
		case "zoom_relative":
			mode = "relative"
		case "zoom_continuous":
			mode = "continuous"
		}
		break
	}
	if choose == "" {
		c.available = false
		c.lastErr = "zoom control not found (zoom_absolute/zoom_relative/zoom_continuous)"
		return fmt.Errorf(c.lastErr)
	}

	ctrl := ctrls[choose]
	c.control = choose
	c.mode = mode
	c.min = ctrl.Min
	c.max = ctrl.Max
	c.native = ctrl.Step
	c.def = ctrl.Default
	c.value = ctrl.Value
	c.available = true
	c.lastErr = ""
	return nil
}

func (c *Cam2Zoom) getCurrentLocked() (int, error) {
	stdout, _, err := c.run("-d", c.device, "-C", c.control)
	if err != nil {
		return 0, err
	}
	line := strings.TrimSpace(stdout)
	m := lastIntRe.FindStringSubmatch(line)
	if m == nil {
		return 0, fmt.Errorf("cannot parse current value from %q", line)
	}
	n, _ := strconv.Atoi(m[1])
	return n, nil
}

func (c *Cam2Zoom) setValueLocked(v int) error {
	_, _, err := c.run("-d", c.device, "--set-ctrl", fmt.Sprintf("%s=%d", c.control, v))
	return err
}

func (c *Cam2Zoom) clamp(v int) int {
	if c.min != nil && v < *c.min {
		v = *c.min
	}
	if c.max != nil && v > *c.max {
		v = *c.max
	}
	return v
}

func (c *Cam2Zoom) status() map[string]any {
	c.mu.Lock()
	defer c.mu.Unlock()

	_ = c.probeLocked()
	return c.snapshotLocked()
}

func (c *Cam2Zoom) snapshotLocked() map[string]any {
	out := map[string]any{
		"available": c.available,
		"device":    c.device,
		"step":      c.step,
	}
	if c.control != "" {
		out["control"] = c.control
		out["mode"] = c.mode
	}
	if c.min != nil {
		out["min"] = *c.min
	}
	if c.max != nil {
		out["max"] = *c.max
	}
	if c.native != nil {
		out["nativeStep"] = *c.native
	}
	if c.def != nil {
		out["default"] = *c.def
	}
	if c.value != nil {
		out["reportedValue"] = *c.value
	}
	if c.available {
		if cur, err := c.getCurrentLocked(); err == nil {
			out["current"] = cur
		} else {
			out["currentError"] = err.Error()
		}
	}
	if c.lastErr != "" {
		out["error"] = c.lastErr
	}
	return out
}

func (c *Cam2Zoom) apply(set *int, delta *int) (map[string]any, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if err := c.probeLocked(); err != nil {
		return c.snapshotLocked(), err
	}

	res := map[string]any{
		"device":  c.device,
		"control": c.control,
		"mode":    c.mode,
		"step":    c.step,
	}

	switch c.mode {
	case "absolute":
		current, err := c.getCurrentLocked()
		if err != nil {
			return res, err
		}
		target := current
		if set != nil {
			target = c.clamp(*set)
		}
		if delta != nil {
			if *delta != -1 && *delta != 1 {
				return res, fmt.Errorf("delta must be -1 or +1")
			}
			target = c.clamp(current + (*delta * c.step))
		}

		if err := c.setValueLocked(target); err != nil {
			return res, err
		}
		after, _ := c.getCurrentLocked()
		res["current"] = current
		res["target"] = target
		res["after"] = after
		return res, nil

	case "relative", "continuous":
		if set != nil {
			return res, fmt.Errorf("set is not supported for %s", c.control)
		}
		if delta == nil || (*delta != -1 && *delta != 1) {
			return res, fmt.Errorf("delta must be -1 or +1")
		}
		if err := c.setValueLocked(*delta); err != nil {
			return res, err
		}
		res["pulse"] = *delta
		return res, nil
	}

	return res, fmt.Errorf("unsupported zoom mode")
}
