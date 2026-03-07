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

type zoomMapPoint struct {
	ZoomX   float64  `json:"zoomX"`
	FocusY  *float64 `json:"focusY"`
	LimitXY string   `json:"limitXY"`
}

type zoomMapFile struct {
	CoordSpace string         `json:"coordSpace"`
	XPreload   *float64       `json:"xPreload"`
	Points     []zoomMapPoint `json:"points"`

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

func (mf *zoomMapFile) normalizedPoints() ([]zoomMapPoint, error) {
	if len(mf.Points) > 0 {
		points := make([]zoomMapPoint, len(mf.Points))
		copy(points, mf.Points)
		return points, nil
	}

	if len(mf.ZoomX) == 0 {
		return nil, fmt.Errorf("empty points")
	}
	if len(mf.FocusY) > 0 && len(mf.FocusY) != len(mf.ZoomX) {
		return nil, fmt.Errorf("zoomX/focusY length mismatch")
	}

	points := make([]zoomMapPoint, len(mf.ZoomX))
	for i := range mf.ZoomX {
		points[i].ZoomX = mf.ZoomX[i]
		if i < len(mf.FocusY) && mf.FocusY[i] != nil {
			v := *mf.FocusY[i]
			points[i].FocusY = &v
		}
		if i < len(mf.LimitXY) {
			points[i].LimitXY = mf.LimitXY[i]
		}
	}
	return points, nil
}

func (mf *zoomMapFile) coordSpace() string {
	coord := strings.ToLower(strings.TrimSpace(mf.CoordSpace))
	if coord == "" {
		coord = strings.ToLower(strings.TrimSpace(mf.Meta.CoordSpace))
	}
	if coord == "" {
		coord = "wpos"
	}
	return coord
}

func (mf *zoomMapFile) xPreload(defaultValue float64) float64 {
	if mf.XPreload != nil {
		return *mf.XPreload
	}
	if mf.Meta.XPreload != nil {
		return *mf.Meta.XPreload
	}
	return defaultValue
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

	points, err := mf.normalizedPoints()
	if err != nil {
		return nil, fmt.Errorf("map %s: %w", path, err)
	}

	useN := len(points)
	if steps > 0 {
		if steps > len(points) {
			return nil, fmt.Errorf("map %s has %d zoom points, but CAM_MAP_STEPS=%d", path, len(points), steps)
		}
		useN = steps
	}

	coord := mf.coordSpace()
	if coord != "wpos" && coord != "mpos" {
		return nil, fmt.Errorf("map %s has unsupported coord_space=%q (expected wpos or mpos)", path, coord)
	}

	preload := mf.xPreload(0.02)

	zoom := make([]float64, useN)
	focus := make([]*float64, useN)
	for i := 0; i < useN; i++ {
		zoom[i] = points[i].ZoomX
		if points[i].FocusY != nil {
			v := *points[i].FocusY
			focus[i] = &v
		}
	}

	limits := make([]string, useN)
	sourceFlagged := make([]int, 0, len(points))
	selectedFlagged := make([]int, 0, useN)
	for i := range points {
		flag := strings.ToUpper(strings.TrimSpace(points[i].LimitXY))
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
		SourcePoints:         len(points),
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
