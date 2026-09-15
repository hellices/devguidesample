#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
samples="${SAMPLES:-30}"
if ! [[ "$samples" =~ ^[0-9]+$ ]] || ((10#$samples < 1 || 10#$samples > 100)); then
    printf 'SAMPLES must be an integer between 1 and 100.\n' >&2
    exit 2
fi
samples=$((10#$samples))
run_id="$(date -u +%Y%m%d-%H%M%S)-$$"
prefix="http3-control-$run_id"
out="evidence/$run_id"
mkdir -p "$out"

image="$prefix:local"
client="$prefix-client"
server="$prefix-server"
router="$prefix-router"
client_net="$prefix-client-net"
server_net="$prefix-server-net"
certs="$prefix-certs"
containers=()
networks=()
volumes=()
image_created=false

cleanup() {
    status=$?
    trap - EXIT
    # Bash 3 treats an empty array as unset when nounset is enabled.
    if ((${#containers[@]})); then
        for name in "${containers[@]}"; do
            if ! docker rm --force "$name" >/dev/null; then
                printf 'Cleanup failed for container %s\n' "$name" >&2
                status=2
            fi
        done
    fi
    if ((${#networks[@]})); then
        for name in "${networks[@]}"; do
            if ! docker network rm "$name" >/dev/null; then
                printf 'Cleanup failed for network %s\n' "$name" >&2
                status=2
            fi
        done
    fi
    if ((${#volumes[@]})); then
        for name in "${volumes[@]}"; do
            if ! docker volume rm "$name" >/dev/null; then
                printf 'Cleanup failed for certificate volume %s\n' "$name" >&2
                status=2
            fi
        done
    fi
    if [ "$image_created" = true ]; then
        if ! docker image rm "$image" >/dev/null; then
            printf 'Cleanup failed for image %s\n' "$image" >&2
            status=2
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker info --format 'Docker={{.ServerVersion}} Kernel={{.KernelVersion}} Arch={{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}}' >"$out/environment.txt"
docker build --tag "$image" . >&2
image_created=true
docker image inspect "$image" --format 'Image={{.Id}}' >>"$out/environment.txt"
docker network create --internal "$client_net" >/dev/null
networks+=("$client_net")
docker network create --internal "$server_net" >/dev/null
networks+=("$server_net")
docker volume create "$certs" >/dev/null
volumes+=("$certs")
docker run --rm --network none --cap-drop ALL \
    --volume "$certs:/certs" "$image" cert /certs

docker run --detach --name "$router" --network "$client_net" \
    --cap-drop ALL --cap-add NET_ADMIN --read-only \
    --security-opt no-new-privileges --sysctl net.ipv4.ip_forward=1 \
    --entrypoint sleep "$image" 86400 >/dev/null
containers+=("$router")
docker network connect "$server_net" "$router"
docker run --detach --name "$server" --network "$server_net" \
    --cap-drop ALL --cap-add NET_ADMIN --read-only \
    --security-opt no-new-privileges \
    --volume "$certs:/certs:ro" "$image" serve /certs >/dev/null
containers+=("$server")

container_ip() {
    docker inspect --format "{{(index .NetworkSettings.Networks \"$2\").IPAddress}}" "$1"
}
server_ip="$(container_ip "$server" "$server_net")"
router_client_ip="$(container_ip "$router" "$client_net")"
router_server_ip="$(container_ip "$router" "$server_net")"
docker run --detach --name "$client" --network "$client_net" \
    --cap-drop ALL --cap-add NET_ADMIN --read-only \
    --security-opt no-new-privileges --add-host "server:$server_ip" \
    --volume "$certs:/certs:ro" --entrypoint sleep "$image" 86400 >/dev/null
containers+=("$client")
client_ip="$(container_ip "$client" "$client_net")"
docker exec "$client" ip route add "$server_ip/32" via "$router_client_ip"
docker exec "$server" ip route add "$client_ip/32" via "$router_server_ip"

for name in "$client" "$server" "$router"; do
    docker exec "$name" ethtool -K eth0 tso off gso off gro off tx-udp-segmentation off
done
docker exec "$router" ethtool -K eth1 tso off gso off gro off tx-udp-segmentation off
docker exec "$client" sysctl net.ipv4.tcp_congestion_control >>"$out/environment.txt"
docker exec "$router" tc -V >>"$out/environment.txt"
docker exec "$router" ethtool --version >>"$out/environment.txt"
docker exec "$client" apk list --installed >"$out/packages.txt"
docker exec "$client" ethtool -k eth0 >"$out/client-offloads.txt"
docker exec "$server" ethtool -k eth0 >"$out/server-offloads.txt"
for device in eth0 eth1; do
    docker exec "$router" ethtool -k "$device" >"$out/router-$device-offloads.txt"
done

ready=false
for attempt in {1..15}; do
    if docker exec "$client" /bench bench --samples 1 --timeout 1s --profile preflight >"$out/preflight.jsonl"; then
        ready=true
        break
    else
        status=$?
        if [ "$status" -ne 1 ]; then
            printf 'Protocol preflight failed before measurements (exit %s).\n' "$status" >&2
            exit "$status"
        fi
    fi
    sleep 0.2
done
if [ "$ready" != true ]; then
    docker logs "$server" >&2
    printf 'Strict HTTP/2 and HTTP/3 preflight did not succeed.\n' >&2
    exit 1
fi

failed=0
for profile in unshaped mobile-clean mobile-loss; do
    for device in eth0 eth1; do
        case "$profile" in
            unshaped)
                docker exec "$router" tc qdisc replace dev "$device" root netem limit 10000
                ;;
            mobile-clean)
                docker exec "$router" tc qdisc replace dev "$device" root netem limit 10000 delay 40ms rate 10mbit
                ;;
            mobile-loss)
                seed=20260915
                if [ "$device" = eth1 ]; then seed=20260916; fi
                docker exec "$router" tc qdisc replace dev "$device" root netem limit 10000 delay 40ms loss random 1% rate 10mbit seed "$seed"
                ;;
        esac
    done
    docker exec "$router" tc -j -s qdisc show >"$out/$profile-qdisc-before.json"
    docker exec "$client" ping -n -c 10 -i 0.2 -W 2 server >"$out/$profile-ping.txt"
    printf 'Measuring %s: %s paired trials per workload.\n' "$profile" "$samples" >&2
    if docker exec "$client" /bench bench --samples "$samples" --profile "$profile" |
        tee "$out/$profile.jsonl" >>"$out/all.jsonl"; then
        :
    else
        status=$?
        if [ "$status" -ne 1 ]; then
            printf 'Benchmark execution failed (exit %s).\n' "$status" >&2
            exit "$status"
        fi
        failed=1
    fi
    if [ "$(wc -l <"$out/$profile.jsonl")" -ne "$((samples * 4))" ]; then
        printf 'Incomplete measurement file for %s.\n' "$profile" >&2
        exit 2
    fi
    docker exec "$router" tc -j -s qdisc show >"$out/$profile-qdisc-after.json"
done
docker exec -i "$client" /bench summarize <"$out/all.jsonl" >"$out/summary.json"
docker logs "$server" >"$out/server.log" 2>&1
printf 'Local control evidence: %s\n' "$out"
exit "$failed"
