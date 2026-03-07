package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestStreamProxyBaseURL(t *testing.T) {
	tests := []struct {
		name   string
		base   string
		stream string
		want   string
	}{
		{
			name:   "root base",
			base:   "http://mediamtx:8889/",
			stream: "cam1",
			want:   "http://mediamtx:8889/cam1/",
		},
		{
			name:   "base with path",
			base:   "http://mediamtx:8889/webrtc",
			stream: "cam1",
			want:   "http://mediamtx:8889/webrtc/cam1/",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := streamProxyBaseURL(tc.base, tc.stream); got != tc.want {
				t.Fatalf("streamProxyBaseURL() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestMakePrefixReverseProxyPreservesStreamSubPath(t *testing.T) {
	var gotPath string
	var gotMethod string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotMethod = r.Method
		w.WriteHeader(http.StatusNoContent)
	}))
	defer upstream.Close()

	proxy := makePrefixReverseProxy(streamProxyBaseURL(upstream.URL, "cam1"), "/cam1/", "test-cam1")
	req := httptest.NewRequest(http.MethodPost, "/cam1/whep", nil)
	rr := httptest.NewRecorder()

	proxy(rr, req)

	if rr.Code != http.StatusNoContent {
		t.Fatalf("proxy status = %d, want %d", rr.Code, http.StatusNoContent)
	}
	if gotMethod != http.MethodPost {
		t.Fatalf("upstream method = %q, want %q", gotMethod, http.MethodPost)
	}
	if gotPath != "/cam1/whep" {
		t.Fatalf("upstream path = %q, want %q", gotPath, "/cam1/whep")
	}
}
