"""GET /api/catalog -> lista de mazos + comandante + cobertura.

(Nombre distinto de los modulos de la raiz para no colisionar en el import.)
"""
import json
from http.server import BaseHTTPRequestHandler

from _sim import deck_list, coverage_report


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"decks": deck_list(), **coverage_report()}
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=3600")
        self.end_headers()
        self.wfile.write(payload)
