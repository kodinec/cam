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
