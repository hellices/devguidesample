#!/usr/bin/env bash
set -euo pipefail
date -u +%FT%TZ
sha256sum /etc/nftables.conf
echo FILTER_POLICY
nft --stateless list table inet lab_filter | sha256sum
echo NAT_POLICY
nft --stateless list table ip lab_nat | sha256sum
echo HTTPS_CONNECTION_TRACKING
conntrack -L -p tcp --orig-src 10.77.2.0/24 --dport 443 -o extended | sed -n '1,4p'
echo SNAT_COUNTER
nft list chain ip lab_nat postrouting
echo PACKET_HEADERS_ONLY
status=0
timeout 20 tcpdump -i any -nn -c 8 \
  'tcp port 443 and (src net 10.77.2.0/24 or src host 10.77.1.4)' || status=$?
if [[ "$status" -eq 124 ]]; then
  echo 'Packet capture window ended before eight matching packets arrived.'
elif [[ "$status" -ne 0 ]]; then
  exit "$status"
fi
echo CAPTURE_COMPLETED
