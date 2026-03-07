package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveSerialPathPrefersExistingPrimary(t *testing.T) {
	dir := t.TempDir()
	primary := filepath.Join(dir, "tty-primary")
	fallback := filepath.Join(dir, "tty-fallback")
	if err := os.WriteFile(primary, []byte(""), 0o644); err != nil {
		t.Fatalf("write primary: %v", err)
	}
	if err := os.WriteFile(fallback, []byte(""), 0o644); err != nil {
		t.Fatalf("write fallback: %v", err)
	}
	if got := resolveSerialPath(primary, fallback); got != primary {
		t.Fatalf("resolveSerialPath() = %q, want %q", got, primary)
	}
}

func TestResolveSerialPathUsesFallbackWhenPrimaryMissing(t *testing.T) {
	dir := t.TempDir()
	primary := filepath.Join(dir, "tty-primary")
	fallback := filepath.Join(dir, "tty-fallback")
	if err := os.WriteFile(fallback, []byte(""), 0o644); err != nil {
		t.Fatalf("write fallback: %v", err)
	}
	if got := resolveSerialPath(primary, fallback); got != fallback {
		t.Fatalf("resolveSerialPath() = %q, want %q", got, fallback)
	}
}

func TestParseWPosWithSoftWCOFallsBackToCachedWCO(t *testing.T) {
	line := "<Idle|MPos:5.000,-2.000,0.000,0.000|FS:0,0>"
	soft := &[4]float64{1.25, -0.75, 0, 0}

	x, y, _, _, ok := parseWPosWithSoftWCO(line, soft)
	if !ok {
		t.Fatalf("parseWPosWithSoftWCO() did not parse fallback WPos")
	}
	if x != 3.75 || y != -1.25 {
		t.Fatalf("parseWPosWithSoftWCO() = (%v, %v), want (3.75, -1.25)", x, y)
	}
}

func TestRememberStatusCachesWCO(t *testing.T) {
	p := &PTZ{}
	p.rememberStatus("<Idle|MPos:1.000,2.000,0.000,0.000|WCO:0.500,1.500,0.000,0.000>")

	x, y, _, _, ok := p.parseWPos("<Idle|MPos:1.000,2.000,0.000,0.000>")
	if !ok {
		t.Fatalf("parseWPos() did not use cached WCO")
	}
	if x != 0.5 || y != 0.5 {
		t.Fatalf("parseWPos() = (%v, %v), want (0.5, 0.5)", x, y)
	}
}

func TestStatusLinePrefersLastStatusFrame(t *testing.T) {
	lines := []string{
		"ok",
		"<Idle|MPos:0.000,0.200,0.000,0.000|Pn:>",
		"<Run|MPos:0.000,-0.500,0.000,0.000|Pn:>",
		"<Idle|MPos:0.000,-2.000,0.000,0.000|Pn:>",
	}

	if got := statusLine(lines); got != lines[3] {
		t.Fatalf("statusLine() = %q, want %q", got, lines[3])
	}
}
