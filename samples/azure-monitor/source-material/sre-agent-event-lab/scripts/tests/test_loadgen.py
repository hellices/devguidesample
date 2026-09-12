import importlib.util
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


LOADGEN_PATH = Path(__file__).parents[1] / "loadgen.py"


def load_module():
    spec = importlib.util.spec_from_file_location("loadgen", LOADGEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def http_server(status_code):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/test"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_loadgen_writes_success_summary(tmp_path):
    loadgen = load_module()
    output = tmp_path / "summary.json"

    with http_server(200) as url:
        exit_code = loadgen.main(
            [
                url,
                "--requests",
                "20",
                "--concurrency",
                "4",
                "--expect-status",
                "200",
                "--output",
                str(output),
            ]
        )

    summary = json.loads(output.read_text())
    assert exit_code == 0
    assert summary["total"] == 20
    assert summary["status_counts"] == {"200": 20}
    assert summary["errors"] == 0
    assert summary["p95_ms"] >= 0


def test_loadgen_returns_two_for_unexpected_status(tmp_path):
    loadgen = load_module()
    output = tmp_path / "summary.json"

    with http_server(200) as url:
        exit_code = loadgen.main(
            [
                url,
                "--requests",
                "3",
                "--concurrency",
                "1",
                "--expect-status",
                "500",
                "--output",
                str(output),
            ]
        )

    assert exit_code == 2
    assert json.loads(output.read_text())["status_counts"] == {"200": 3}


def test_loadgen_rejects_unsafe_bounds(tmp_path):
    loadgen = load_module()

    exit_code = loadgen.main(
        [
            "http://127.0.0.1:1",
            "--requests",
            "10001",
            "--output",
            str(tmp_path / "summary.json"),
        ]
    )

    assert exit_code == 2
