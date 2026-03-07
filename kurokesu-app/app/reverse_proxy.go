package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
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
		inPath := req.URL.Path
		orig(req)
		suffix := strings.TrimPrefix(inPath, prefix)
		if !strings.HasPrefix(suffix, "/") {
			suffix = "/" + suffix
		}
		basePath := u.Path
		if basePath == "" {
			basePath = "/"
		}
		req.URL.Path = joinURLPath(basePath, suffix)
		req.URL.RawPath = req.URL.EscapedPath()
		req.Host = u.Host
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, e error) {
		log.Printf("%s reverse proxy error: %v", label, e)
		http.Error(w, "upstream unavailable", http.StatusBadGateway)
	}
	return proxy.ServeHTTP
}

func joinURLPath(basePath, suffix string) string {
	if basePath == "" {
		basePath = "/"
	}
	if !strings.HasPrefix(suffix, "/") {
		suffix = "/" + suffix
	}
	if basePath == "/" {
		return suffix
	}
	return strings.TrimRight(basePath, "/") + suffix
}
