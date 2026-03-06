package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"path"
	"strings"
)

func makePrefixReverseProxy(baseURL, prefix, label string) http.HandlerFunc {
	u, err := url.Parse(baseURL)
	if err != nil {
		log.Printf("%s proxy invalid base URL %q: %v", label, baseURL, err)
		return func(w http.ResponseWriter, r *http.Request) {
			http.Error(w, "proxy misconfigured", http.StatusInternalServerError)
		}
	}

	proxy := httputil.NewSingleHostReverseProxy(u)
	orig := proxy.Director
	proxy.Director = func(req *http.Request) {
		orig(req)
		suffix := strings.TrimPrefix(req.URL.Path, prefix)
		if !strings.HasPrefix(suffix, "/") {
			suffix = "/" + suffix
		}
		basePath := u.Path
		if basePath == "" {
			basePath = "/"
		}
		req.URL.Path = path.Join(basePath, suffix)
		req.URL.RawPath = req.URL.EscapedPath()
		req.Host = u.Host
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, e error) {
		log.Printf("%s reverse proxy error: %v", label, e)
		http.Error(w, "upstream unavailable", http.StatusBadGateway)
	}

	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		proxy.ServeHTTP(w, r)
	}
}
