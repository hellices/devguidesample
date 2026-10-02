package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"

	"github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
	"golang.org/x/net/http2"
)

func makeCertificate(dir string) error {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return err
	}
	template := &x509.Certificate{
		SerialNumber: serial, Subject: pkix.Name{CommonName: "local-benchmark-only"},
		NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(24 * time.Hour),
		DNSNames: []string{"server", "localhost"}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")},
		KeyUsage:    x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IsCA:        true, BasicConstraintsValid: true,
	}
	certificate, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return err
	}
	privateKey, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "server.key"), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: privateKey}), 0600); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "server.crt"), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certificate}), 0644)
}

type servers struct {
	tcp net.Listener
	udp net.PacketConn
	h2  *http.Server
	h3  *http3.Server
}

func newServers(address, certFile, keyFile string) (*servers, error) {
	certificate, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, err
	}
	tlsConfig := &tls.Config{
		MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{certificate},
		SessionTicketsDisabled: true,
	}
	var nextConnection atomic.Uint64
	connectionContext := func(ctx context.Context) context.Context {
		return context.WithValue(ctx, connectionKey{}, nextConnection.Add(1))
	}
	h2 := &http.Server{
		Handler: http.HandlerFunc(payloadHandler), TLSConfig: tlsConfig.Clone(),
		ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second,
		ConnContext: func(ctx context.Context, _ net.Conn) context.Context { return connectionContext(ctx) },
	}
	if err := http2.ConfigureServer(h2, &http2.Server{}); err != nil {
		return nil, err
	}
	tcp, err := net.Listen("tcp", address)
	if err != nil {
		return nil, err
	}
	udp, err := net.ListenPacket("udp", tcp.Addr().String())
	if err != nil {
		return nil, errors.Join(err, tcp.Close())
	}
	h3 := &http3.Server{
		Handler: http.HandlerFunc(payloadHandler), TLSConfig: tlsConfig.Clone(),
		QUICConfig:  &quic.Config{Allow0RTT: false, MaxIdleTimeout: 60 * time.Second},
		ConnContext: func(ctx context.Context, _ *quic.Conn) context.Context { return connectionContext(ctx) },
	}
	return &servers{tcp: tcp, udp: udp, h2: h2, h3: h3}, nil
}

func (s *servers) serve(ctx context.Context) error {
	done := make(chan error, 2)
	go func() { done <- s.h2.ServeTLS(s.tcp, "", "") }()
	go func() { done <- s.h3.Serve(s.udp) }()
	var failure error
	remaining := 2
	select {
	case <-ctx.Done():
	case failure = <-done:
		remaining--
	}
	closeErrors := []error{s.h2.Close(), s.h3.Close(), s.udp.Close()}
	for range remaining {
		closeErrors = append(closeErrors, <-done)
	}
	for _, err := range closeErrors {
		if err != nil && !errors.Is(err, http.ErrServerClosed) && !errors.Is(err, net.ErrClosed) {
			failure = errors.Join(failure, err)
		}
	}
	return failure
}
