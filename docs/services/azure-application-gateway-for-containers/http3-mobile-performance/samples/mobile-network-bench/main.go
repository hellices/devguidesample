package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

var errFailedTrials = errors.New("one or more trials failed; inspect the recorded errors")

type benchOptions struct {
	origin  string
	ca      string
	profile string
	samples int
	timeout time.Duration
}

func parseBenchOptions(args []string) (benchOptions, error) {
	var o benchOptions
	flags := flag.NewFlagSet("bench", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.StringVar(&o.origin, "url", "https://server:8443", "benchmark origin")
	flags.StringVar(&o.ca, "ca", "/certs/server.crt", "trusted local certificate")
	flags.StringVar(&o.profile, "profile", "unshaped", "network profile label")
	flags.IntVar(&o.samples, "samples", 30, "paired trials, 1..100")
	flags.DurationVar(&o.timeout, "timeout", 20*time.Second, "per-request timeout, at most 60s")
	if err := flags.Parse(args); err != nil {
		return o, err
	}
	u, err := url.Parse(o.origin)
	if err != nil {
		return o, err
	}
	if flags.NArg() != 0 || o.samples < 1 || o.samples > 100 || o.timeout <= 0 || o.timeout > 60*time.Second || strings.TrimSpace(o.profile) == "" {
		return o, fmt.Errorf("invalid arguments: require 1..100 samples, timeout in (0s,60s], and a profile label")
	}
	if u.Scheme != "https" || u.Hostname() == "" || u.User != nil ||
		u.ForceQuery || u.RawQuery != "" || strings.Contains(o.origin, "#") ||
		(u.Path != "" && u.Path != "/") {
		return o, fmt.Errorf("url must be an HTTPS origin without credentials, path, query, or fragment")
	}
	o.origin = (&url.URL{Scheme: u.Scheme, Host: u.Host}).String()
	return o, nil
}

func runBench(o benchOptions, output io.Writer) error {
	encoder := json.NewEncoder(output)
	failed := false
	for pair := 1; pair <= o.samples; pair++ {
		protocols := []string{"h2", "h3"}
		if pair%2 == 0 {
			protocols[0], protocols[1] = protocols[1], protocols[0]
		}
		for _, workload := range []string{"cold", "warm"} {
			for _, protocol := range protocols {
				client, closeClient, err := newClient(protocol, o.ca, o.timeout)
				if err != nil {
					return err
				}
				var r result
				if workload == "cold" {
					r = measureBatch(client, protocol, o.origin, 1, 1024, "")
				} else {
					warmup := measureBatch(client, protocol, o.origin, 1, 1024, "")
					if len(warmup.Errors) != 0 || warmup.Succeeded != 1 {
						r = result{Requests: 16, WarmupFailed: true, Errors: append([]string{"unmeasured warmup failed"}, warmup.Errors...)}
					} else {
						r = measureBatch(client, protocol, o.origin, 16, 16384, warmup.ConnectionIDs[0])
					}
				}
				if err := closeClient(); err != nil {
					r.Errors = append(r.Errors, fmt.Sprintf("close client: %v", err))
				}
				r.Profile, r.Workload, r.Protocol, r.Pair = o.profile, workload, protocol, pair
				if len(r.Errors) != 0 || r.Succeeded != r.Requests {
					failed = true
				}
				if err := encoder.Encode(r); err != nil {
					return err
				}
			}
		}
	}
	if failed {
		return errFailedTrials
	}
	return nil
}

func readResults(input io.Reader) ([]result, error) {
	decoder := json.NewDecoder(input)
	var results []result
	for {
		var r result
		if err := decoder.Decode(&r); err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			return nil, fmt.Errorf("invalid measurement JSON: %w", err)
		}
		if r.Profile == "" || (r.Protocol != "h2" && r.Protocol != "h3") ||
			(r.Workload != "cold" && r.Workload != "warm") || r.Requests < 1 ||
			r.Succeeded < 0 || r.Succeeded > r.Requests || r.ElapsedMS < 0 || r.HeadersMS < 0 ||
			r.Pair < 1 || r.Pair > 100 || r.Bytes < 0 ||
			(r.Succeeded != r.Requests && len(r.Errors) == 0) {
			return nil, fmt.Errorf("invalid measurement record")
		}
		count, size := 1, 1024
		if r.Workload == "warm" {
			count, size = 16, 16384
		}
		if r.Requests != count {
			return nil, fmt.Errorf("request count does not match workload")
		}
		if len(r.Errors) == 0 {
			httpVersion := map[string]string{"h2": "HTTP/2.0", "h3": "HTTP/3.0"}[r.Protocol]
			if r.WarmupFailed || r.ElapsedMS <= 0 || r.HeadersMS > r.ElapsedMS ||
				r.Bytes != int64(count*size) || r.Connections != 1 ||
				len(r.ConnectionIDs) != 1 || r.ConnectionIDs[0] == "" ||
				r.NegotiatedHTTP != httpVersion || r.NegotiatedALPN != r.Protocol || r.TLSVersion != "TLS 1.3" {
				return nil, fmt.Errorf("successful measurement lacks matching wire-protocol, connection, timing, or payload evidence")
			}
		}
		results = append(results, r)
	}
	if len(results) == 0 {
		return nil, fmt.Errorf("measurement input is empty")
	}
	return results, nil
}

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: bench cert DIRECTORY | serve DIRECTORY | bench [OPTIONS] | summarize < JSONL")
	}
	switch args[0] {
	case "cert":
		if len(args) != 2 {
			return fmt.Errorf("cert requires a destination directory")
		}
		return makeCertificate(args[1])
	case "serve":
		if len(args) != 2 {
			return fmt.Errorf("serve requires a certificate directory")
		}
		s, err := newServers(":8443", filepath.Join(args[1], "server.crt"), filepath.Join(args[1], "server.key"))
		if err != nil {
			return err
		}
		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer cancel()
		return s.serve(ctx)
	case "bench":
		o, err := parseBenchOptions(args[1:])
		if err != nil {
			return err
		}
		return runBench(o, os.Stdout)
	case "summarize":
		if len(args) != 1 {
			return fmt.Errorf("summarize reads JSONL from standard input and accepts no arguments")
		}
		results, err := readResults(os.Stdin)
		if err != nil {
			return err
		}
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		return encoder.Encode(summarize(results))
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		if errors.Is(err, errFailedTrials) {
			os.Exit(1)
		}
		os.Exit(2)
	}
}
