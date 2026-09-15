package main

import (
	"bytes"
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPayloadHandler(t *testing.T) {
	for _, tc := range []struct {
		name   string
		method string
		path   string
		status int
		size   int
	}{
		{"payload", "GET", "/bytes?size=1024", 200, 1024},
		{"missing size", "GET", "/bytes", 400, 0},
		{"negative size", "GET", "/bytes?size=-1", 400, 0},
		{"zero size", "GET", "/bytes?size=0", 400, 0},
		{"oversized", "GET", "/bytes?size=1048577", 400, 0},
		{"invalid size", "GET", "/bytes?size=bad", 400, 0},
		{"wrong path", "GET", "/missing?size=1024", 404, 0},
		{"wrong method", "POST", "/bytes?size=1024", 405, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			payloadHandler(recorder, httptest.NewRequest(tc.method, tc.path, nil))
			if recorder.Code != tc.status {
				t.Fatalf("status = %d, want %d", recorder.Code, tc.status)
			}
			if tc.status == http.StatusOK {
				if !bytes.Equal(recorder.Body.Bytes(), payload(tc.size)) {
					t.Fatal("response payload differs from requested bytes")
				}
				if recorder.Header().Get("Cache-Control") != "no-store" {
					t.Fatal("benchmark response must disable caching")
				}
			}
		})
	}
}

func TestVerifyResponseRejectsInvalidMeasurements(t *testing.T) {
	for _, tc := range []struct {
		name        string
		protocol    string
		actualMajor int
		status      int
		body        []byte
		encoding    string
		wantError   bool
	}{
		{"h2", "h2", 2, 200, payload(16), "", false},
		{"h3", "h3", 3, 200, payload(16), "", false},
		{"h3 fallback to h2", "h3", 2, 200, payload(16), "", true},
		{"h2 fallback to h1", "h2", 1, 200, payload(16), "", true},
		{"unknown protocol", "h1", 1, 200, payload(16), "", true},
		{"redirect", "h3", 3, 302, payload(16), "", true},
		{"backend error", "h2", 2, 503, payload(16), "", true},
		{"short payload", "h2", 2, 200, payload(15), "", true},
		{"wrong content", "h3", 3, 200, bytes.Repeat([]byte{255}, 16), "", true},
		{"compressed payload", "h3", 3, 200, payload(16), "gzip", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			response := &http.Response{
				StatusCode: tc.status,
				ProtoMajor: tc.actualMajor,
				Header:     make(http.Header),
				TLS:        &tls.ConnectionState{Version: tls.VersionTLS13, NegotiatedProtocol: tc.protocol},
			}
			response.Header.Set("Content-Encoding", tc.encoding)
			err := verifyResponse(response, tc.body, tc.protocol, 16)
			if (err != nil) != tc.wantError {
				t.Fatalf("error = %v, wantError = %v", err, tc.wantError)
			}
		})
	}
}

func TestVerifyResponseRejectsInvalidTLS(t *testing.T) {
	for _, state := range []*tls.ConnectionState{
		nil,
		{Version: tls.VersionTLS12, NegotiatedProtocol: "h2"},
		{Version: tls.VersionTLS13, NegotiatedProtocol: "http/1.1"},
	} {
		response := &http.Response{StatusCode: 200, ProtoMajor: 2, Header: make(http.Header), TLS: state}
		if err := verifyResponse(response, payload(16), "h2", 16); err == nil {
			t.Fatalf("accepted invalid TLS state: %+v", state)
		}
	}
}

func TestSummariesUseSuccessfulTrialsAndExposeFailures(t *testing.T) {
	results := []result{
		{Profile: "mobile", Workload: "cold", Protocol: "h2", Requests: 1, Succeeded: 1, ElapsedMS: 30},
		{Profile: "mobile", Workload: "cold", Protocol: "h2", Requests: 1, Succeeded: 1, ElapsedMS: 10},
		{Profile: "mobile", Workload: "cold", Protocol: "h2", Requests: 1, Succeeded: 1, ElapsedMS: 20},
		{Profile: "mobile", Workload: "cold", Protocol: "h2", Requests: 1, ElapsedMS: 9000, Errors: []string{"timeout"}},
		{Profile: "mobile", Workload: "cold", Protocol: "h3", Requests: 1, Errors: []string{"QUIC unavailable"}},
	}
	summaries := summarize(results)
	if len(summaries) != 2 {
		t.Fatalf("groups = %d, want 2", len(summaries))
	}
	h2, h3 := summaries[0], summaries[1]
	if h2.Trials != 4 || h2.Successes != 3 || h2.Failures != 1 || h2.FailedRequests != 1 {
		t.Fatalf("failure accounting is wrong: %+v", h2)
	}
	if h2.P50MS == nil || *h2.P50MS != 20 || h2.P95MS == nil || *h2.P95MS != 30 {
		t.Fatalf("nearest-rank percentiles are wrong: %+v", h2)
	}
	if h3.P50MS != nil || h3.P95MS != nil || h3.Failures != 1 {
		t.Fatalf("failed-only group must not produce a zero-latency success: %+v", h3)
	}
}
