package main

import (
	"os"
	"path/filepath"
	"testing"
)

func writeTempMap(t *testing.T, body string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "map.json")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("write map: %v", err)
	}
	return path
}

func TestLoadZoomMapRejectsSelectedFlaggedPoints(t *testing.T) {
	path := writeTempMap(t, `{
  "coordSpace": "wpos",
  "xPreload": 0.02,
  "points": [
    {"zoomX": 0, "focusY": 0},
    {"zoomX": 1, "focusY": 0.5, "limitXY": "X"},
    {"zoomX": 2, "focusY": 1}
  ]
}`)

	if _, err := loadZoomMap(path, 2, true); err == nil {
		t.Fatal("expected error for selected flagged points")
	}
}

func TestLoadZoomMapAllowsFlagsOutsideSelectedRange(t *testing.T) {
	path := writeTempMap(t, `{
  "coordSpace": "wpos",
  "xPreload": 0.02,
  "points": [
    {"zoomX": 0, "focusY": 0},
    {"zoomX": 1, "focusY": 0.5},
    {"zoomX": 2, "focusY": 1},
    {"zoomX": 3, "focusY": 1.5, "limitXY": "Y"}
  ]
}`)

	m, err := loadZoomMap(path, 3, true)
	if err != nil {
		t.Fatalf("loadZoomMap() error = %v", err)
	}
	if got, want := len(m.ZoomX), 3; got != want {
		t.Fatalf("len(ZoomX) = %d, want %d", got, want)
	}
	if got, want := len(m.SelectedFlagged), 0; got != want {
		t.Fatalf("len(SelectedFlagged) = %d, want %d", got, want)
	}
	if got, want := len(m.SourceFlaggedIndices), 1; got != want {
		t.Fatalf("len(SourceFlaggedIndices) = %d, want %d", got, want)
	}
	if got, want := m.SourceFlaggedIndices[0], 3; got != want {
		t.Fatalf("SourceFlaggedIndices[0] = %d, want %d", got, want)
	}
}

func TestLoadZoomMapSupportsLegacyArraySchema(t *testing.T) {
	path := writeTempMap(t, `{
  "meta": {"coord_space":"mpos","x_preload":0.05},
  "zoomX": [0, 1],
  "focusY": [0.1, 0.2],
  "limitXY": ["", ""]
}`)

	m, err := loadZoomMap(path, 2, true)
	if err != nil {
		t.Fatalf("loadZoomMap() error = %v", err)
	}
	if got, want := m.CoordSpace, "mpos"; got != want {
		t.Fatalf("CoordSpace = %q, want %q", got, want)
	}
	if got, want := m.XPreload, 0.05; got != want {
		t.Fatalf("XPreload = %v, want %v", got, want)
	}
	if got, want := len(m.ZoomX), 2; got != want {
		t.Fatalf("len(ZoomX) = %d, want %d", got, want)
	}
}
