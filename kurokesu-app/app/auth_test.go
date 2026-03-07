package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestMaybeBasicAuthChallengesWithoutCredentials(t *testing.T) {
	protected := maybeBasicAuth("admin", "change-me", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()
	protected.ServeHTTP(rr, req)

	if got, want := rr.Code, http.StatusUnauthorized; got != want {
		t.Fatalf("status = %d, want %d", got, want)
	}
	if got := rr.Header().Get("WWW-Authenticate"); got == "" {
		t.Fatal("expected WWW-Authenticate header")
	}
}

func TestMaybeBasicAuthAllowsCorrectCredentials(t *testing.T) {
	protected := maybeBasicAuth("admin", "change-me", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.SetBasicAuth("admin", "change-me")
	rr := httptest.NewRecorder()
	protected.ServeHTTP(rr, req)

	if got, want := rr.Code, http.StatusOK; got != want {
		t.Fatalf("status = %d, want %d", got, want)
	}
}

func TestMaybeBasicAuthBypassesWhenDisabled(t *testing.T) {
	protected := maybeBasicAuth("", "", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()
	protected.ServeHTTP(rr, req)

	if got, want := rr.Code, http.StatusNoContent; got != want {
		t.Fatalf("status = %d, want %d", got, want)
	}
}
