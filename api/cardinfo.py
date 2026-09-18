"""POST /api/cardinfo — arte + tipo + texto (Scryfall) para una lista de
nombres. Lo usa /play para mostrar fotos y habilidades reales.

Body JSON: {"names": ["Sol Ring", "Counterspell", ...]}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import card_info  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            body = {"info": card_info(req.get("names", []))}
            code = 200
        except Exception as exc:  # noqa: BLE001
            body, code = {"error": str(exc)}, 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=86400")
        self.end_headers()
        self.wfile.write(payload)
