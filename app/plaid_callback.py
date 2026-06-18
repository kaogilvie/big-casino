"""Tiny background HTTP server that receives the Plaid Link callback.

Plaid Link's onSuccess fires in a sandboxed iframe — the sandbox blocks
window.parent.location navigation, so we can't pass the public_token back
via URL params directly. Instead, the iframe POSTs to this localhost server
(CORS-open, localhost only), and Streamlit polls the result on rerun.

Started once as a daemon thread; subsequent calls to ensure_running() are no-ops.
"""
from __future__ import annotations

import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

PORT = 8766

_state: dict = {"public_token": None, "institution": None}
_lock = threading.Lock()
_started = False


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/plaid_result":
            with _lock:
                _state["public_token"] = params.get("token", [None])[0]
                _state["institution"] = params.get("institution", ["Unknown"])[0]
            self._respond(200, b"ok")
        else:
            self._respond(404, b"not found")

    def do_OPTIONS(self) -> None:
        self._respond(200, b"")

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # silence request logs


def ensure_running() -> None:
    global _started
    if _started:
        return
    try:
        server = HTTPServer(("localhost", PORT), _Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        _started = True
    except OSError:
        _started = True  # already bound (e.g. hot-reload)


def pop_result() -> tuple[Optional[str], Optional[str]]:
    """Return (public_token, institution) and clear the stored result."""
    with _lock:
        token = _state.pop("public_token", None)
        institution = _state.pop("institution", None)
    return token, institution


def has_result() -> bool:
    with _lock:
        return _state.get("public_token") is not None
