from contextlib import closing
import socket
from threading import Thread


def test_tcp_relay_preserves_bytes_and_half_closed_response():
    from transport_proxy import relay

    caller, proxy_client = socket.socketpair()
    proxy_backend, backend = socket.socketpair()
    with closing(caller), closing(proxy_client), closing(proxy_backend), closing(backend):
        caller.settimeout(2)
        backend.settimeout(2)
        worker = Thread(target=relay, args=(proxy_client, proxy_backend, 2))
        worker.start()
        caller.sendall(b"\x00opaque-encrypted-request\xff")
        caller.shutdown(socket.SHUT_WR)
        assert backend.recv(1024) == b"\x00opaque-encrypted-request\xff"
        assert backend.recv(1024) == b""
        backend.sendall(b"response-after-request-eof")
        backend.shutdown(socket.SHUT_WR)
        assert caller.recv(1024) == b"response-after-request-eof"
        assert caller.recv(1024) == b""
        worker.join(timeout=3)
        assert not worker.is_alive()


def test_connect_authority_is_limited_to_approved_https_hosts():
    from transport_proxy import approved_target

    targets = {"approved.example.test": ("approved.example.test", 443)}
    assert approved_target("approved.example.test:443", targets) == targets["approved.example.test"]
    assert approved_target("unapproved.example.test:443", targets) is None
    assert approved_target("approved.example.test:80", targets) is None
    assert approved_target("user@approved.example.test:443", targets) is None
    assert approved_target("approved.example.test:443/path", targets) is None
    assert approved_target("approved.example.test:not-a-port", targets) is None


def test_proxy_rejects_unapproved_destinations_before_connecting():
    from transport_proxy import ProxyServer

    with ProxyServer(("127.0.0.1", 0), {"approved.example.test": ("127.0.0.1", 443)}) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as connection:
                connection.sendall(
                    b"CONNECT unapproved.example.test:443 HTTP/1.1\r\n"
                    b"Host: unapproved.example.test:443\r\n\r\n"
                )
                response = connection.recv(4096)
            assert b"403" in response.split(b"\r\n", 1)[0]
        finally:
            server.shutdown()
            worker.join(timeout=2)
