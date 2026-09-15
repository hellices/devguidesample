package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestStrictTransportsAndSingleConnectionFanout(t *testing.T) {
	dir := t.TempDir()
	if err := makeCertificate(dir); err != nil {
		t.Fatal(err)
	}
	servers, err := newServers("127.0.0.1:0", filepath.Join(dir, "server.crt"), filepath.Join(dir, "server.key"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- servers.serve(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(5 * time.Second):
			t.Error("server shutdown timed out")
		}
	})
	for _, protocol := range []string{"h2", "h3"} {
		t.Run(protocol, func(t *testing.T) {
			client, closeClient, err := newClient(protocol, filepath.Join(dir, "server.crt"), 3*time.Second)
			if err != nil {
				t.Fatal(err)
			}
			defer func() {
				if err := closeClient(); err != nil {
					t.Error(err)
				}
			}()
			origin := "https://" + servers.tcp.Addr().String()
			warmup := measureBatch(client, protocol, origin, 1, 1024, "")
			if warmup.Succeeded != 1 || warmup.Connections != 1 || len(warmup.Errors) != 0 {
				t.Fatalf("warmup failed: %+v", warmup)
			}
			result := measureBatch(client, protocol, origin, 16, 16384, warmup.ConnectionIDs[0])
			if result.Succeeded != 16 || result.Bytes != 16*16384 || result.Connections != 1 || len(result.Errors) != 0 {
				t.Fatalf("fanout is not a valid single-connection measurement: %+v", result)
			}
			if result.NegotiatedALPN != protocol || result.TLSVersion != "TLS 1.3" {
				t.Fatalf("wire protocol was not recorded: %+v", result)
			}
			mismatch := measureBatch(client, protocol, origin, 1, 16, "wrong-connection")
			if mismatch.Succeeded != 0 || len(mismatch.Errors) == 0 {
				t.Fatal("connection reuse mismatch was accepted")
			}
		})
	}
	var output bytes.Buffer
	options := benchOptions{
		origin: "https://" + servers.tcp.Addr().String(), ca: filepath.Join(dir, "server.crt"),
		profile: "integration", samples: 2, timeout: 3 * time.Second,
	}
	if err := runBench(options, &output); err != nil {
		t.Fatal(err)
	}
	records, err := readResults(&output)
	if err != nil || len(records) != 8 {
		t.Fatalf("paired runner did not emit eight valid records: %v", err)
	}
	for i, expected := range []string{"h2", "h3", "h2", "h3", "h3", "h2", "h3", "h2"} {
		if records[i].Protocol != expected || records[i].Pair != i/4+1 {
			t.Fatalf("pair order was not alternated: %+v", records[i])
		}
	}
}

func TestHTTP3DoesNotFallBackToTCP(t *testing.T) {
	dir := t.TempDir()
	if err := makeCertificate(dir); err != nil {
		t.Fatal(err)
	}
	certificate, err := tls.LoadX509KeyPair(filepath.Join(dir, "server.crt"), filepath.Join(dir, "server.key"))
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewUnstartedServer(http.HandlerFunc(payloadHandler))
	server.EnableHTTP2 = true
	server.TLS = &tls.Config{MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{certificate}}
	server.Config.ConnContext = func(ctx context.Context, _ net.Conn) context.Context {
		return context.WithValue(ctx, connectionKey{}, uint64(1))
	}
	server.StartTLS()
	defer server.Close()
	tcpClient, closeTCP, err := newClient("h2", filepath.Join(dir, "server.crt"), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	control := measureBatch(tcpClient, "h2", server.URL, 1, 1024, "")
	if err := closeTCP(); err != nil {
		t.Fatal(err)
	}
	if control.Succeeded != 1 || len(control.Errors) != 0 {
		t.Fatalf("TCP positive control is not reachable and trusted: %+v", control)
	}
	client, closeClient, err := newClient("h3", filepath.Join(dir, "server.crt"), 150*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if err := closeClient(); err != nil {
			t.Error(err)
		}
	}()
	result := measureBatch(client, "h3", server.URL, 1, 1024, "")
	if result.Succeeded != 0 || len(result.Errors) == 0 {
		t.Fatalf("HTTP/3 unexpectedly succeeded without a UDP server: %+v", result)
	}
}

func TestInvalidBenchmarkOptions(t *testing.T) {
	for _, args := range [][]string{
		{"--samples", "0"},
		{"--samples", "101"},
		{"--timeout", "0s"},
		{"--timeout", "61s"},
		{"--url", "http://server:8443"},
		{"--url", "https://user:password@server:8443"},
		{"--url", "https://server:8443/?token=test"},
		{"--url", "https://server:8443/not-the-benchmark"},
		{"--profile", ""},
		{"unexpected-positional-argument"},
	} {
		if _, err := parseBenchOptions(args); err == nil {
			t.Errorf("accepted invalid options: %q", args)
		}
	}
	if _, err := parseBenchOptions([]string{"--samples", "1", "--profile", "smoke"}); err != nil {
		t.Fatalf("valid options failed: %v", err)
	}
}

func TestSummaryInputRejectsTruncationAndInvalidRecords(t *testing.T) {
	for _, input := range []string{
		"",
		`{"profile":`,
		`{"profile":"mobile","protocol":"h3","workload":"cold","requests":1,"succeeded":2}`,
		`{"profile":"mobile","protocol":"h3","workload":"cold","requests":1,"succeeded":1,"elapsed_ms":-1}`,
		`{"profile":"mobile","protocol":"h3","workload":"cold","requests":1,"succeeded":0}`,
	} {
		if _, err := readResults(strings.NewReader(input)); err == nil {
			t.Errorf("accepted invalid measurement file: %s", input)
		}
	}
	record := result{
		Profile: "mobile", Protocol: "h3", Workload: "cold", Pair: 1, Requests: 1, Succeeded: 0,
		Errors: []string{"timeout"},
	}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	results, err := readResults(strings.NewReader(string(data)))
	if err != nil || len(results) != 1 {
		t.Fatalf("valid failure record rejected: %v", err)
	}
}

func TestSummaryInputRequiresSuccessfulWireEvidence(t *testing.T) {
	valid := result{
		Profile: "mobile", Protocol: "h3", Workload: "cold", Pair: 1, Requests: 1, Succeeded: 1,
		Bytes: 1024, Connections: 1, ConnectionIDs: []string{"1"}, ElapsedMS: 2, HeadersMS: 1,
		NegotiatedALPN: "h3", NegotiatedHTTP: "HTTP/3.0", TLSVersion: "TLS 1.3",
	}
	for name, invalidate := range map[string]func(*result){
		"fallback":          func(r *result) { r.NegotiatedHTTP = "HTTP/2.0" },
		"wrong ALPN":        func(r *result) { r.NegotiatedALPN = "h2" },
		"wrong TLS":         func(r *result) { r.TLSVersion = "TLS 1.2" },
		"missing bytes":     func(r *result) { r.Bytes = 0 },
		"zero latency":      func(r *result) { r.ElapsedMS = 0 },
		"extra connections": func(r *result) { r.Connections = 2 },
		"missing connection": func(r *result) {
			r.ConnectionIDs = nil
		},
		"invalid pair": func(r *result) { r.Pair = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			record := valid
			invalidate(&record)
			data, err := json.Marshal(record)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := readResults(bytes.NewReader(data)); err == nil {
				t.Fatalf("accepted an unverified success: %s", data)
			}
		})
	}
}

func TestNewClientRejectsInvalidInput(t *testing.T) {
	dir := t.TempDir()
	ca := filepath.Join(dir, "invalid.crt")
	if err := os.WriteFile(ca, []byte("not a certificate"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, protocol := range []string{"h1", "h2", "h3"} {
		if _, closeClient, err := newClient(protocol, ca, time.Second); err == nil {
			if closeClient != nil {
				if err := closeClient(); err != nil {
					t.Error(err)
				}
			}
			t.Errorf("accepted invalid client configuration for %s", protocol)
		}
	}
	if _, err := readResults(io.LimitReader(strings.NewReader("{}"), 0)); err == nil {
		t.Fatal("accepted empty results")
	}
}
