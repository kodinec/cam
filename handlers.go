package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"strings"
	"time"
)

type setDeltaRequest struct {
	Set   *int `json:"set"`
	Delta *int `json:"delta"`
}

type rawRequest struct {
	Cmd string `json:"cmd"`
}

type focusSetDeltaRequest struct {
	Set   *float64 `json:"set"`
	Delta *int     `json:"delta"`
}

type apiError struct {
	Error string `json:"error"`
}

func parseSetDelta(r *http.Request) (set *int, delta *int, err error) {
	defer r.Body.Close()
	var req setDeltaRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&req); err != nil {
		return nil, nil, fmt.Errorf("invalid json: %w", err)
	}
	if (req.Set == nil && req.Delta == nil) || (req.Set != nil && req.Delta != nil) {
		return nil, nil, fmt.Errorf("provide exactly one of: set or delta")
	}
	return req.Set, req.Delta, nil
}

func parseFocusSetDelta(r *http.Request) (set *float64, delta *int, err error) {
	defer r.Body.Close()
	var req focusSetDeltaRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&req); err != nil {
		return nil, nil, fmt.Errorf("invalid json: %w", err)
	}
	if (req.Set == nil && req.Delta == nil) || (req.Set != nil && req.Delta != nil) {
		return nil, nil, fmt.Errorf("provide exactly one of: set or delta")
	}
	return req.Set, req.Delta, nil
}

func handleZoom(ptz *PTZ) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		set, delta, err := parseSetDelta(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, apiError{Error: err.Error()})
			return
		}

		currentZoom, _ := ptz.logicalState()
		if ptz.cam1MapMaxIndex() >= 0 {
			_, _, mapHomed, _ := ptz.cam1MapMeta()
			if !mapHomed {
				writeJSON(w, http.StatusConflict, map[string]any{
					"error":       "cam1 map is not homed yet. Run /api/cam1/home first",
					"logicalZoom": currentZoom,
					"mapState":    ptz.cam1MapState(),
				})
				return
			}
			nextIdx := ptz.cam1MapCurrentIndex()
			maxIdx := ptz.cam1MapMaxIndex()
			if set != nil {
				if *set < 0 || *set > maxIdx {
					writeJSON(w, http.StatusBadRequest, apiError{Error: fmt.Sprintf("set must be in range 0..%d", maxIdx)})
					return
				}
				nextIdx = *set
			}
			if delta != nil {
				if *delta != -1 && *delta != 1 {
					writeJSON(w, http.StatusBadRequest, apiError{Error: "delta must be -1 or +1"})
					return
				}
				nextIdx = clamp(nextIdx+*delta, 0, maxIdx)
			}

			resp, err := ptz.gotoCam1MapIndex(nextIdx)
			if err != nil {
				log.Printf("cam1 map zoom failed idx=%d err=%v", nextIdx, err)
				writeJSON(w, http.StatusBadGateway, map[string]any{
					"error":       err.Error(),
					"logicalZoom": currentZoom,
					"mapState":    ptz.cam1MapState(),
				})
				return
			}
			resp["logicalZoom"] = nextIdx
			resp["mapState"] = ptz.cam1MapState()
			writeJSON(w, http.StatusOK, resp)
			return
		}

		nextZoom := currentZoom
		if set != nil {
			if *set < 0 || *set > ptz.zoomMax {
				writeJSON(w, http.StatusBadRequest, apiError{Error: fmt.Sprintf("set must be in range 0..%d", ptz.zoomMax)})
				return
			}
			nextZoom = *set
		}
		if delta != nil {
			if *delta != -1 && *delta != 1 {
				writeJSON(w, http.StatusBadRequest, apiError{Error: "delta must be -1 or +1"})
				return
			}
			nextZoom = clamp(currentZoom+*delta, 0, ptz.zoomMax)
		}

		targetX := float64(nextZoom) * ptz.xPerStep
		cmd := fmt.Sprintf("G1 X%.3f F%.0f", targetX, ptz.feed)
		reply, status, err := ptz.commandThenStatus(cmd)
		if err != nil {
			log.Printf("zoom cmd failed cmd=%q err=%v", cmd, err)
			writeJSON(w, http.StatusBadGateway, map[string]any{
				"error":       err.Error(),
				"logicalZoom": currentZoom,
				"targetX":     targetX,
				"cmd":         cmd,
				"replyLines":  reply,
				"statusReply": statusLine(status),
				"statusLines": status,
			})
			return
		}

		ptz.setLogicalZoom(nextZoom)
		writeJSON(w, http.StatusOK, map[string]any{
			"logicalZoom": nextZoom,
			"targetX":     targetX,
			"cmd":         cmd,
			"replyLines":  reply,
			"statusReply": statusLine(status),
			"statusLines": status,
		})
	}
}

func handleFocus(ptz *PTZ) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		set, delta, err := parseFocusSetDelta(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, apiError{Error: err.Error()})
			return
		}

		mapEnabled, mapCoord, mapHomed, fineStep := ptz.cam1MapMeta()
		if mapEnabled {
			if !mapHomed {
				writeJSON(w, http.StatusConflict, apiError{Error: "cam1 map is not homed yet. Run /api/cam1/home first"})
				return
			}
			if fineStep <= 0 {
				fineStep = 0.05
			}

			var reply []string
			var status []string
			if delta != nil {
				if *delta != -1 && *delta != 1 {
					writeJSON(w, http.StatusBadRequest, apiError{Error: "delta must be -1 or +1"})
					return
				}
				dy := float64(*delta) * fineStep
				reply, status, err = ptz.moveRel(nil, &dy, ptz.feed, 10*time.Second)
			} else {
				targetY := *set
				if mapCoord == "mpos" {
					reply, status, err = ptz.moveToMPos(nil, &targetY, ptz.feed, 20*time.Second)
				} else {
					reply, status, err = ptz.moveAbsWPos(nil, &targetY, ptz.feed, 20*time.Second)
				}
			}
			if err != nil {
				writeJSON(w, http.StatusBadGateway, map[string]any{
					"error":       err.Error(),
					"replyLines":  reply,
					"statusReply": statusLine(status),
					"statusLines": status,
					"mapState":    ptz.cam1MapState(),
				})
				return
			}
			resp := map[string]any{
				"ok":          true,
				"mapEnabled":  true,
				"coordSpace":  mapCoord,
				"focusStep":   fineStep,
				"replyLines":  reply,
				"statusReply": statusLine(status),
				"statusLines": status,
				"mapState":    ptz.cam1MapState(),
			}
			if set != nil {
				resp["targetY"] = *set
			}
			if delta != nil {
				resp["delta"] = *delta
			}
			writeJSON(w, http.StatusOK, resp)
			return
		}

		_, currentFocus := ptz.logicalState()
		logicalMax := ptz.zoomMax
		nextFocus := currentFocus
		if set != nil {
			setInt := int(math.Round(*set))
			if setInt < 0 || setInt > logicalMax {
				writeJSON(w, http.StatusBadRequest, apiError{Error: fmt.Sprintf("set must be in range 0..%d", logicalMax)})
				return
			}
			nextFocus = setInt
		}
		if delta != nil {
			if *delta != -1 && *delta != 1 {
				writeJSON(w, http.StatusBadRequest, apiError{Error: "delta must be -1 or +1"})
				return
			}
			nextFocus = clamp(currentFocus+*delta, 0, logicalMax)
		}

		targetY := float64(nextFocus) * ptz.yPerStep
		cmd := fmt.Sprintf("G1 Y%.3f F%.0f", targetY, ptz.feed)
		reply, status, err := ptz.commandThenStatus(cmd)
		if err != nil {
			log.Printf("focus cmd failed cmd=%q err=%v", cmd, err)
			writeJSON(w, http.StatusBadGateway, map[string]any{
				"error":        err.Error(),
				"logicalFocus": currentFocus,
				"targetY":      targetY,
				"cmd":          cmd,
				"replyLines":   reply,
				"statusReply":  statusLine(status),
				"statusLines":  status,
			})
			return
		}

		ptz.setLogicalFocus(nextFocus)
		writeJSON(w, http.StatusOK, map[string]any{
			"logicalFocus": nextFocus,
			"targetY":      targetY,
			"cmd":          cmd,
			"replyLines":   reply,
			"statusReply":  statusLine(status),
			"statusLines":  status,
		})
	}
}

func handleStatus(ptz *PTZ) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		status, err := ptz.queryStatus()
		if err != nil {
			log.Printf("status failed err=%v", err)
			writeJSON(w, http.StatusBadGateway, map[string]any{
				"error":       err.Error(),
				"statusReply": statusLine(status),
				"statusLines": status,
			})
			return
		}
		zoom, focus := ptz.logicalState()
		resp := map[string]any{
			"logicalZoom":  zoom,
			"logicalFocus": focus,
			"statusReply":  statusLine(status),
			"statusLines":  status,
			"mapState":     ptz.cam1MapState(),
		}
		st := statusLine(status)
		if x, y, _, _, ok := parseMPos(st); ok {
			resp["mposX"] = x
			resp["mposY"] = y
		}
		if x, y, _, _, ok := parseWPos(st); ok {
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
		writeJSON(w, http.StatusOK, resp)
	}
}

func handleCam1Home(ptz *PTZ) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		resp, err := ptz.runCam1StartFlow()
		if err != nil {
			log.Printf("cam1 start flow failed err=%v", err)
			writeJSON(w, http.StatusBadGateway, map[string]any{
				"error": err.Error(),
			})
			return
		}

		if ptz.cam1MapMaxIndex() >= 0 {
			step0, err := ptz.gotoCam1MapIndex(0)
			if err != nil {
				writeJSON(w, http.StatusBadGateway, map[string]any{
					"error":       err.Error(),
					"flowResult":  resp,
					"mapState":    ptz.cam1MapState(),
					"afterHomeOK": true,
				})
				return
			}
			resp["step0"] = step0
		}
		resp["mapState"] = ptz.cam1MapState()
		writeJSON(w, http.StatusOK, resp)
	}
}

func handleRaw(ptz *PTZ, allowRaw bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !allowRaw {
			writeJSON(w, http.StatusForbidden, apiError{Error: "raw endpoint is disabled (PTZ_ALLOW_RAW=false)"})
			return
		}

		defer r.Body.Close()
		var req rawRequest
		if err := json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, apiError{Error: fmt.Sprintf("invalid json: %v", err)})
			return
		}
		cmd := strings.TrimSpace(req.Cmd)
		if cmd == "" {
			writeJSON(w, http.StatusBadRequest, apiError{Error: "cmd is required"})
			return
		}
		if strings.ContainsAny(cmd, "\r\n") {
			writeJSON(w, http.StatusBadRequest, apiError{Error: "cmd must be single-line"})
			return
		}

		var reply []string
		var err error
		if cmd == "?" {
			reply, err = ptz.queryStatus()
		} else {
			reply, err = ptz.commandOK(cmd)
		}

		if err != nil {
			log.Printf("raw cmd failed cmd=%q err=%v", cmd, err)
			writeJSON(w, http.StatusBadGateway, map[string]any{
				"error":      err.Error(),
				"cmd":        cmd,
				"replyLines": reply,
			})
			return
		}

		writeJSON(w, http.StatusOK, map[string]any{
			"cmd":        cmd,
			"replyLines": reply,
		})
	}
}

func handleCam1UnavailableStatus(reason string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"available": false,
			"error":     "cam1 ptz unavailable: " + reason,
			"mapState": map[string]any{
				"enabled": false,
				"homed":   false,
			},
		})
	}
}

func handleCam1UnavailableControl(method string, reason string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != method {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"error": "cam1 ptz unavailable: " + reason,
		})
	}
}

func handleCam2Zoom(cam2 *Cam2Zoom) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		set, delta, err := parseSetDelta(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, apiError{Error: err.Error()})
			return
		}
		resp, applyErr := cam2.apply(set, delta)
		if applyErr != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{
				"error": applyErr.Error(),
				"info":  resp,
			})
			return
		}
		writeJSON(w, http.StatusOK, resp)
	}
}

func handleCam2ZoomStatus(cam2 *Cam2Zoom) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusOK, cam2.status())
	}
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
