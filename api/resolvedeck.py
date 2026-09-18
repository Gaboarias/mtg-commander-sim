"""POST /api/resolvedeck — resuelve las cartas (Scryfall) de una o varias
decklists y devuelve sus datos, para armar decks importados dentro de Pyodide.

Body JSON: {"texts": ["<decklist 1>", "<decklist 2>", ...]}
Respuesta: {"cards": {"<nombre_norm>": {<datos scryfall>}, ...}}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import resolve_decks  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            body = {"cards": resolve_decks(req.get("texts", []))}
            code = 200
        except Exception as exc:  # noqa: BLE001
            body, code = {"error": str(exc)}, 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
