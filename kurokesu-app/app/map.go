package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

type ZoomMap struct {
	Path                 string
	CoordSpace           string
	XPreload             float64
	ZoomX                []float64
	FocusY               []*float64
	LimitXY              []string
	SourcePoints         int
	SourceFlaggedIndices []int
	SelectedFlagged      []int
}

type zoomMapFile struct {
	Meta struct {
		CoordSpace string   `json:"coord_space"`
		XPreload   *float64 `json:"x_preload"`
	} `json:"meta"`
	ZoomX   []float64  `json:"zoomX"`
	FocusY  []*float64 `json:"focusY"`
	LimitXY []string   `json:"limitXY"`
}

func (m *ZoomMap) MaxIndex() int {
	if m == nil {
		return -1
	}
	return len(m.ZoomX) - 1
}

func loadZoomMap(path string, steps int, strict bool) (*ZoomMap, error) {
	path = strings.TrimSpace(path)
	if path == "" {
		return nil, fmt.Errorf("map path is empty")
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read map %s: %w", path, err)
	}

	var mf zoomMapFile
	if err := json.Unmarshal(raw, &mf); err != nil {
		return nil, fmt.Errorf("parse map %s: %w", path, err)
	}
	if len(mf.ZoomX) == 0 {
		return nil, fmt.Errorf("map %s has empty zoomX", path)
	}
	if len(mf.FocusY) > 0 && len(mf.FocusY) != len(mf.ZoomX) {
		return nil, fmt.Errorf("map %s has zoomX/focusY length mismatch", path)
	}

	useN := len(mf.ZoomX)
	if steps > 0 {
		if steps > len(mf.ZoomX) {
			return nil, fmt.Errorf("map %s has %d zoom points, but CAM_MAP_STEPS=%d", path, len(mf.ZoomX), steps)
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

	limits := make([]string, useN)
	sourceFlagged := make([]int, 0, len(mf.LimitXY))
	selectedFlagged := make([]int, 0, useN)
	for i := 0; i < len(mf.ZoomX); i++ {
		flag := ""
		if i < len(mf.LimitXY) {
			flag = strings.ToUpper(strings.TrimSpace(mf.LimitXY[i]))
		}
		if flag != "" {
			sourceFlagged = append(sourceFlagged, i)
		}
		if i < useN {
			limits[i] = flag
			if flag != "" {
				selectedFlagged = append(selectedFlagged, i)
			}
		}
	}
	if strict && len(selectedFlagged) > 0 {
		return nil, fmt.Errorf("selected map points are flagged with limitXY: %s", joinInts(selectedFlagged))
	}

	return &ZoomMap{
		Path:                 path,
		CoordSpace:           coord,
		XPreload:             preload,
		ZoomX:                zoom,
		FocusY:               focus,
		LimitXY:              limits,
		SourcePoints:         len(mf.ZoomX),
		SourceFlaggedIndices: sourceFlagged,
		SelectedFlagged:      selectedFlagged,
	}, nil
}

func joinInts(v []int) string {
	if len(v) == 0 {
		return ""
	}
	parts := make([]string, 0, len(v))
	for _, n := range v {
		parts = append(parts, fmt.Sprintf("%d", n))
	}
	return strings.Join(parts, ",")
}
