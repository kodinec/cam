package main

import (
	"context"
	"errors"
	"io"
	"log"
	"net/http"
	"strings"
)

func makeMJPEGProxy(client *http.Client, upstream, label string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, upstream, nil)
		if err != nil {
			http.Error(w, "proxy build failed", http.StatusInternalServerError)
			return
		}
		req.Header.Set("User-Agent", "ptz-service/1.0")

		resp, err := client.Do(req)
		if err != nil {
			log.Printf("%s proxy upstream error: %v", label, err)
			http.Error(w, "upstream unavailable", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		for k, vv := range resp.Header {
			if strings.EqualFold(k, "Connection") || strings.EqualFold(k, "Proxy-Connection") || strings.EqualFold(k, "Keep-Alive") || strings.EqualFold(k, "Transfer-Encoding") || strings.EqualFold(k, "Upgrade") {
				continue
			}
			for _, v := range vv {
				w.Header().Add(k, v)
			}
		}
		if w.Header().Get("Content-Type") == "" {
			w.Header().Set("Content-Type", "multipart/x-mixed-replace")
		}
		w.WriteHeader(resp.StatusCode)

		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}

		_, err = io.Copy(w, resp.Body)
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Printf("%s proxy stream copy ended with error: %v", label, err)
		}
	}
}
