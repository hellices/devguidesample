package main

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"sync"
	"time"

	"github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
	"golang.org/x/net/http2"
)

func newClient(protocol, caFile string, timeout time.Duration) (*http.Client, func() error, error) {
	if protocol != "h2" && protocol != "h3" {
		return nil, nil, fmt.Errorf("unsupported protocol %q", protocol)
	}
	if timeout <= 0 {
		return nil, nil, fmt.Errorf("timeout must be positive")
	}
	ca, err := os.ReadFile(caFile)
	if err != nil {
		return nil, nil, err
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(ca) {
		return nil, nil, fmt.Errorf("CA file contains no valid certificates")
	}
	tlsConfig := &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS13}
	var transport http.RoundTripper
	var closeClient func() error
	if protocol == "h2" {
		h2 := &http2.Transport{TLSClientConfig: tlsConfig, DisableCompression: true}
		transport = h2
		closeClient = func() error { h2.CloseIdleConnections(); return nil }
	} else {
		h3 := &http3.Transport{
			TLSClientConfig: tlsConfig, DisableCompression: true,
			QUICConfig: &quic.Config{HandshakeIdleTimeout: timeout, MaxIdleTimeout: 60 * time.Second},
		}
		transport, closeClient = h3, h3.Close
	}
	return &http.Client{
		Transport: transport, Timeout: timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
	}, closeClient, nil
}

func measureBatch(client *http.Client, protocol, origin string, count, size int, expectedConnection string) result {
	r := result{Protocol: protocol, Requests: count}
	if count < 1 || count > 16 || size < 1 || size > 1<<20 {
		r.Errors = []string{"invalid batch dimensions"}
		return r
	}
	type observation struct {
		bytes      int64
		headersMS  float64
		connection string
		http       string
		alpn       string
		err        error
	}
	observations := make([]observation, count)
	var ready, finished sync.WaitGroup
	ready.Add(count)
	finished.Add(count)
	start := make(chan struct{})
	for i := range count {
		go func() {
			defer finished.Done()
			ready.Done()
			<-start
			begin := time.Now()
			response, err := client.Get(fmt.Sprintf("%s/bytes?size=%d&stream=%d", origin, size, i))
			o := &observations[i]
			o.headersMS = float64(time.Since(begin)) / float64(time.Millisecond)
			if err != nil {
				o.err = err
				return
			}
			body, readErr := io.ReadAll(io.LimitReader(response.Body, int64(size)+1))
			closeErr := response.Body.Close()
			o.bytes = int64(len(body))
			o.err = errors.Join(readErr, closeErr, verifyResponse(response, body, protocol, size))
			o.connection, o.http = response.Header.Get("X-Bench-Connection"), response.Proto
			if response.TLS != nil {
				o.alpn = response.TLS.NegotiatedProtocol
			}
			if o.connection == "" || (expectedConnection != "" && o.connection != expectedConnection) {
				o.err = errors.Join(o.err, fmt.Errorf("missing or changed connection identifier"))
			}
		}()
	}
	ready.Wait()
	begin := time.Now()
	close(start)
	finished.Wait()
	r.ElapsedMS = float64(time.Since(begin)) / float64(time.Millisecond)
	connections := make(map[string]bool)
	for i, o := range observations {
		r.Bytes += o.bytes
		if count == 1 {
			r.HeadersMS = o.headersMS
		}
		if o.connection != "" {
			connections[o.connection] = true
		}
		if o.err != nil {
			r.Errors = append(r.Errors, fmt.Sprintf("stream %d: %v", i, o.err))
			continue
		}
		r.Succeeded++
		r.NegotiatedHTTP, r.NegotiatedALPN, r.TLSVersion = o.http, o.alpn, "TLS 1.3"
	}
	for id := range connections {
		r.ConnectionIDs = append(r.ConnectionIDs, id)
	}
	sort.Strings(r.ConnectionIDs)
	r.Connections = len(connections)
	if r.Succeeded > 0 && r.Connections != 1 {
		r.Errors = append(r.Errors, fmt.Sprintf("batch used %d connections, expected exactly one", r.Connections))
	}
	return r
}
