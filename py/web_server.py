"""HTTP server with REST API for desk-cam control."""

import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlparse

from logger import get_logger

log = get_logger("web")

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# App reference set by app.py
_app = None


def set_app(app):
    global _app
    _app = app


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_WEB_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # suppress default access logs

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json_response(self._get_status())
        elif path == "/api/presets":
            self._json_response(self._get_presets())
        elif path == "/api/snapshot":
            self._snapshot_response()
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/api/roi":
            self._handle_roi(body)
        elif path == "/api/rotation":
            self._handle_rotation(body)
        elif path == "/api/snapshot/refresh":
            self._handle_refresh_snapshot()
        elif path == "/api/presets":
            self._handle_save_preset(body)
        elif path.startswith("/api/presets/") and path.endswith("/load"):
            name = path.split("/")[3]
            self._handle_load_preset(name)
        else:
            self._error_response(404, "not found")

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/presets/"):
            name = path.split("/")[3]
            self._handle_delete_preset(name)
        else:
            self._error_response(404, "not found")

    # --- API handlers ---

    def _get_status(self):
        if not _app:
            return {}
        return _app.get_status()

    def _get_presets(self):
        if not _app:
            return {}
        return _app.get_status().get("presets", {})

    def _snapshot_response(self):
        if not _app:
            self._error_response(503, "not ready")
            return
        jpeg = _app.get_snapshot_jpeg()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(jpeg)

    def _handle_refresh_snapshot(self):
        if not _app:
            self._error_response(503, "not ready")
            return
        _app.refresh_snapshot()
        self._snapshot_response()

    def _handle_roi(self, body):
        if not _app:
            self._error_response(503, "not ready")
            return
        try:
            _app.set_roi(body["x"], body["y"], body["w"], body["h"])
            self._json_response({"ok": True})
        except (KeyError, TypeError) as e:
            self._error_response(400, str(e))

    def _handle_rotation(self, body):
        if not _app:
            self._error_response(503, "not ready")
            return
        try:
            _app.set_rotation(body["enabled"])
            self._json_response({"ok": True})
        except (KeyError, TypeError) as e:
            self._error_response(400, str(e))

    def _handle_save_preset(self, body):
        if not _app:
            self._error_response(503, "not ready")
            return
        try:
            name = body["name"]
            _app.save_preset(name)
            self._json_response({"ok": True})
        except (KeyError, TypeError) as e:
            self._error_response(400, str(e))

    def _handle_load_preset(self, name):
        if not _app:
            self._error_response(503, "not ready")
            return
        if _app.load_preset(name):
            self._json_response({"ok": True})
        else:
            self._error_response(404, f"preset '{name}' not found")

    def _handle_delete_preset(self, name):
        if not _app:
            self._error_response(503, "not ready")
            return
        if _app.delete_preset(name):
            self._json_response({"ok": True})
        else:
            self._error_response(404, f"preset '{name}' not found")

    # --- Helpers ---

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, status, message):
        self._json_response({"error": message}, status)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start(port: int):
    """Start the HTTP server in a background thread."""
    server = ThreadedHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("listening on port %d", port)
    return server
