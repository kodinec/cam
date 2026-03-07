package main

import (
	"crypto/tls"
	"net/http/httptest"
	"testing"
)

func TestRequestHost(t *testing.T) {
	tests := []struct {
		name string
		host string
		want string
	}{
		{name: "empty", host: "", want: "localhost"},
		{name: "hostname", host: "example.local", want: "example.local"},
		{name: "ipv4 with port", host: "10.10.45.39:8787", want: "10.10.45.39"},
		{name: "ipv6 with port", host: "[2001:db8::1]:8787", want: "2001:db8::1"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", "http://localhost/", nil)
			r.Host = tt.host
			got := requestHost(r)
			if got != tt.want {
				t.Fatalf("requestHost(%q)=%q, want %q", tt.host, got, tt.want)
			}
		})
	}
}

func TestStreamURL(t *testing.T) {
	r := httptest.NewRequest("GET", "http://localhost/", nil)
	r.Host = "10.10.45.39:8787"

	gotHTTP := streamURL(r, "8889", "cam1")
	wantHTTP := "http://10.10.45.39:8889/cam1?controls=false&autoplay=true&muted=true&playsinline=true"
	if gotHTTP != wantHTTP {
		t.Fatalf("streamURL http=%q, want %q", gotHTTP, wantHTTP)
	}

	r.TLS = &tls.ConnectionState{}
	gotHTTPS := streamURL(r, "8889", "cam2")
	wantHTTPS := "https://10.10.45.39:8889/cam2?controls=false&autoplay=true&muted=true&playsinline=true"
	if gotHTTPS != wantHTTPS {
		t.Fatalf("streamURL https=%q, want %q", gotHTTPS, wantHTTPS)
	}
}
