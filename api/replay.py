"""POST /api/replay — juega UNA partida y devuelve la traza para el reproductor
visual (Fase 1).

Body JSON:
  {"decks":[{"kind":"registered","key":"marvel","name":"Kang"},
            {"kind":"custom","name":"Mi deck","text":"<decklist>"}, ...],
   "seed": 0, "level": "intermedio"}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import replay  # noqa: E402


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
            self._send(200, replay(req.get("decks", []),
                                   req.get("seed", 0),
                                   req.get("level", "intermedio")))
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
