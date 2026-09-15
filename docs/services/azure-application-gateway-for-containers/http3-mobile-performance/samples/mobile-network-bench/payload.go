package main

import (
	"bytes"
	"crypto/tls"
	"fmt"
	"log"
	"net/http"
	"strconv"
)

type connectionKey struct{}

func payload(size int) []byte {
	body := make([]byte, size)
	for i := range body {
		body[i] = byte(i % 251)
	}
	return body
}

func payloadHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/bytes" {
		http.NotFound(w, r)
		return
	}
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		http.Error(w, "GET required", http.StatusMethodNotAllowed)
		return
	}
	size, err := strconv.Atoi(r.URL.Query().Get("size"))
	if err != nil || size < 1 || size > 1<<20 {
		http.Error(w, "size must be between 1 and 1048576 bytes", http.StatusBadRequest)
		return
	}
	if id, ok := r.Context().Value(connectionKey{}).(uint64); ok {
		w.Header().Set("X-Bench-Connection", strconv.FormatUint(id, 10))
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.Itoa(size))
	if _, err := w.Write(payload(size)); err != nil {
		log.Printf("payload write failed: %v", err)
	}
}

func verifyResponse(response *http.Response, body []byte, protocol string, size int) error {
	major := map[string]int{"h2": 2, "h3": 3}[protocol]
	if major == 0 || response.ProtoMajor != major {
		return fmt.Errorf("protocol mismatch: requested %s, received HTTP/%d", protocol, response.ProtoMajor)
	}
	if response.TLS == nil || response.TLS.Version != tls.VersionTLS13 || response.TLS.NegotiatedProtocol != protocol {
		return fmt.Errorf("expected TLS 1.3 with ALPN %s", protocol)
	}
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP status %d", response.StatusCode)
	}
	if response.Header.Get("Content-Encoding") != "" {
		return fmt.Errorf("unexpected response compression")
	}
	if !bytes.Equal(body, payload(size)) {
		return fmt.Errorf("payload mismatch: received %d bytes, expected %d identical bytes", len(body), size)
	}
	return nil
}
