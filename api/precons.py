"""GET /api/precons            -> lista de precons de Commander (MTGJSON)
   GET /api/precons?load=NAME  -> ese precon como decklist de texto
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _precon import list_precons, precon_to_text  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body, cache="s-maxage=86400"):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        try:
            load = qs.get("load", [None])[0]
            if load:
                self._send(200, precon_to_text(load), cache="s-maxage=604800")
            else:
                self._send(200, {"precons": list_precons()})
        except Exception as exc:  # noqa: BLE001
            self._send(502, {"error": f"MTGJSON no disponible: {exc}"})
