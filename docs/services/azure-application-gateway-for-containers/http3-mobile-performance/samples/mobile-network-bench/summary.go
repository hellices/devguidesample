package main

import (
	"math"
	"sort"
)

type result struct {
	Profile        string   `json:"profile"`
	Workload       string   `json:"workload"`
	Protocol       string   `json:"protocol"`
	Pair           int      `json:"pair"`
	Requests       int      `json:"requests"`
	Succeeded      int      `json:"succeeded"`
	Bytes          int64    `json:"bytes"`
	Connections    int      `json:"connections"`
	ConnectionIDs  []string `json:"connection_ids,omitempty"`
	ElapsedMS      float64  `json:"elapsed_ms"`
	HeadersMS      float64  `json:"headers_ms"`
	NegotiatedALPN string   `json:"negotiated_alpn"`
	NegotiatedHTTP string   `json:"negotiated_http"`
	TLSVersion     string   `json:"tls_version"`
	WarmupFailed   bool     `json:"warmup_failed"`
	Errors         []string `json:"errors,omitempty"`
}

type summary struct {
	Profile        string   `json:"profile"`
	Workload       string   `json:"workload"`
	Protocol       string   `json:"protocol"`
	Trials         int      `json:"trials"`
	Successes      int      `json:"successes"`
	Failures       int      `json:"failures"`
	FailedRequests int      `json:"incomplete_requests"`
	WarmupFailures int      `json:"warmup_failures"`
	P50MS          *float64 `json:"p50_ms"`
	P95MS          *float64 `json:"p95_ms"`
	HeadersP50MS   *float64 `json:"headers_p50_ms"`
}

func summarize(results []result) []summary {
	groups := make(map[string][]result)
	var keys []string
	for _, r := range results {
		key := r.Profile + "\x00" + r.Workload + "\x00" + r.Protocol
		if _, exists := groups[key]; !exists {
			keys = append(keys, key)
		}
		groups[key] = append(groups[key], r)
	}
	sort.Strings(keys)
	summaries := make([]summary, 0, len(keys))
	for _, key := range keys {
		group := groups[key]
		s := summary{Profile: group[0].Profile, Workload: group[0].Workload, Protocol: group[0].Protocol}
		var elapsed, headers []float64
		for _, r := range group {
			s.Trials++
			s.FailedRequests += r.Requests - r.Succeeded
			if r.WarmupFailed {
				s.WarmupFailures++
			}
			if len(r.Errors) != 0 || r.Succeeded != r.Requests || r.WarmupFailed {
				s.Failures++
				continue
			}
			s.Successes++
			elapsed = append(elapsed, r.ElapsedMS)
			if r.Requests == 1 {
				headers = append(headers, r.HeadersMS)
			}
		}
		s.P50MS, s.P95MS = percentile(elapsed, 0.5), percentile(elapsed, 0.95)
		s.HeadersP50MS = percentile(headers, 0.5)
		summaries = append(summaries, s)
	}
	return summaries
}

func percentile(values []float64, fraction float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	sort.Float64s(values)
	value := values[int(math.Ceil(float64(len(values))*fraction))-1]
	return &value
}
