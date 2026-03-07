package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
)

type setDeltaRequest struct {
	Set   *int `json:"set"`
	Delta *int `json:"delta"`
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

func handleHealth() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	}
}

func handleStatus(ptz *PTZ) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusOK, ptz.statusResponse())
	}
}

func handleHome(ptz *PTZ) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		resp, err := ptz.homeAndStep0()
		if err != nil {
			log.Printf("start flow failed err=%v", err)
			out := map[string]any{
				"error":    err.Error(),
				"mapState": ptz.mapState(),
			}
			for k, v := range resp {
				out[k] = v
			}
			writeJSON(w, http.StatusBadGateway, out)
			return
		}
		writeJSON(w, http.StatusOK, resp)
	}
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

		state := ptz.mapState()
		maxIdx, _ := state["maxIndex"].(int)
		nextIdx, _ := state["currentIndex"].(int)
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

		resp, err := ptz.gotoIndex(nextIdx)
		if err != nil {
			log.Printf("zoom failed idx=%d err=%v", nextIdx, err)
			status := http.StatusBadGateway
			if maxIdx >= 0 && nextIdx >= 0 && nextIdx <= maxIdx {
				status = http.StatusConflict
			}
			writeJSON(w, status, map[string]any{
				"error":    err.Error(),
				"mapState": ptz.mapState(),
			})
			return
		}
		writeJSON(w, http.StatusOK, resp)
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
		resp, err := ptz.focus(set, delta)
		if err != nil {
			status := http.StatusBadGateway
			if delta != nil && (*delta != -1 && *delta != 1) {
				status = http.StatusBadRequest
			}
			writeJSON(w, status, map[string]any{
				"error":    err.Error(),
				"mapState": ptz.mapState(),
			})
			return
		}
		writeJSON(w, http.StatusOK, resp)
	}
}

func handleUnavailableStatus(reason string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"available": false,
			"error":     reason,
			"mapState": map[string]any{
				"enabled": false,
				"homed":   false,
			},
		})
	}
}

func handleUnavailableControl(reason string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": reason})
	}
}
