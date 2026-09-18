"""GET /api/catalog -> lista de mazos + comandante + cobertura.

(Nombre distinto de los modulos de la raiz para no colisionar en el import.)
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import deck_list, coverage_report  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"decks": deck_list(), **coverage_report()}
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
