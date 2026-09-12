#!/usr/bin/env python3
"""Local dev server to demo Telepresence intercept.

When an intercept is active, traffic sent to the echo-server Service
in AKS is routed here instead.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {
                "source": "💻 LOCAL DEV MACHINE (via Telepresence intercept)",
                "path": self.path,
                "message": "This response came from your laptop, not the AKS pod!",
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[local-server] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    print(f"[local-server] listening on 0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
