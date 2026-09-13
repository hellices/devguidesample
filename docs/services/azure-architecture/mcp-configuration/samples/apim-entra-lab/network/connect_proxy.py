"""Loopback-only HTTPS CONNECT endpoint used with kubectl port-forward."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import os
import select
import socket
from urllib.parse import urlsplit


LOGGER = logging.getLogger(__name__)


def relay(client: socket.socket, upstream: socket.socket, idle_timeout: float = 180) -> None:
    readers = {client, upstream}
    peers = {client: upstream, upstream: client}
    while readers:
        ready, _, _ = select.select(list(readers), [], [], idle_timeout)
        if not ready:
            raise TimeoutError("idle CONNECT tunnel")
        for current in ready:
            data = current.recv(65536)
            if data:
                peers[current].sendall(data)
            else:
                readers.remove(current)
                peers[current].shutdown(socket.SHUT_WR)


def approved_target(
    authority: str, targets: dict[str, tuple[str, int]]
) -> tuple[str, int] | None:
    try:
        parsed = urlsplit("//" + authority)
        port = parsed.port
    except ValueError:
        return None
    if (
        port != 443 or parsed.username is not None or parsed.password is not None
        or parsed.path or parsed.query or parsed.fragment
    ):
        return None
    return targets.get((parsed.hostname or "").casefold())


class ProxyHandler(BaseHTTPRequestHandler):
    rbufsize = 0
    server: "ProxyServer"

    def log_request(self, code="-", size="-"):
        LOGGER.info("CONNECT response status=%s", code)

    def log_error(self, format, *args):
        LOGGER.warning("CONNECT protocol error")

    def do_CONNECT(self) -> None:
        target = approved_target(self.path, self.server.targets)
        if target is None:
            self.send_error(403, "Destination is not an approved lab HTTPS endpoint")
            return
        try:
            upstream = socket.create_connection(target, timeout=15)
        except OSError as error:
            LOGGER.warning("CONNECT upstream failed: %s", type(error).__name__)
            self.send_error(502, "Approved lab endpoint is not reachable")
            return
        with upstream:
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.close_connection = True
            try:
                relay(self.connection, upstream)
            except OSError as error:
                LOGGER.warning("CONNECT relay failed: %s", type(error).__name__)

    def do_GET(self) -> None:
        self.send_error(405, "Only HTTPS CONNECT is supported")


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], targets: dict[str, tuple[str, int]]):
        self.targets = targets
        super().__init__(address, ProxyHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-host", action="append")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    hosts = args.allow_host or os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
    if not hosts or any(not host.strip() for host in hosts):
        parser.error("set MCP_ALLOWED_HOSTS or provide --allow-host")
    targets = {host.strip().casefold(): (host.strip(), 443) for host in hosts}
    logging.basicConfig(level=logging.INFO)
    with ProxyServer(("127.0.0.1", args.port), targets) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
