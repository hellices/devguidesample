import socket
import time


def main(
    cluster_name: str,
    api_server_private_ip: str,
    hub_path: str = "Hub1(10.51.250.4)->Hub2/3",
) -> dict:
    """Probes TCP 443 reachability from the SRE Agent VNet subnet across Multi-Hub Firewall UDR routes to a Private AKS API server with a fast 1.5s timeout."""
    start = time.time()
    reachable = False
    err = None
    try:
        with socket.create_connection((api_server_private_ip, 443), timeout=1.5):
            reachable = True
    except Exception as e:
        err = str(e)
    ms = round((time.time() - start) * 1000, 1)
    return {
        "cluster": cluster_name,
        "apiPrivateIp": api_server_private_ip,
        "hopChain": f"10.42.4.0/24->{hub_path}->{api_server_private_ip}:443",
        "tcp443Reachable": reachable,
        "handshakeMs": ms,
        "note": "OK" if reachable else f"Unreachable ({err}) - check if FW/AKS is Stopped",
    }
