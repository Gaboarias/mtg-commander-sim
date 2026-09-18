"""POST /api/match — simula una mesa de 2 a 6 decks.

Body JSON:
  {"decks":[{"kind":"registered","key":"tricky","name":"Tricky"},
            {"kind":"custom","name":"Mi deck","text":"<decklist>"}, ...],
   "n":120, "log":false}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import match, match_log  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            specs = req.get("decks", [])
            if req.get("log"):
                self._send(200, match_log(specs))
            else:
                self._send(200, match(specs, req.get("n", 120)))
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
