"""GET /api/cardsearch  — ayuda a corregir cartas no encontradas (#5).

  ?q=nombre            -> {"suggestions":[nombres], "best":"nombre"|null}
  ?set=xxx&number=nn   -> {"name":..,"type_line":..,"mana_cost":..} | {"error":..}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
import _scry  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        setcode = qs.get("set", [None])[0]
        number = qs.get("number", [None])[0]
        q = qs.get("q", [None])[0]
        try:
            if setcode and number:
                card = _scry.by_collector(setcode, number)
                if not card or not card.get("name"):
                    self._send(200, {"error": "no encontrada para ese set/numero"})
                    return
                self._send(200, {"name": card.get("name"),
                                 "type_line": card.get("type_line", ""),
                                 "mana_cost": card.get("mana_cost", "")})
            elif q:
                suggestions = _scry.autocomplete(q)
                best = None
                if not suggestions:
                    fz = _scry.named_fuzzy(q)
                    if fz and fz.get("name"):
                        best = fz["name"]
                        suggestions = [best]
                else:
                    best = suggestions[0]
                self._send(200, {"query": q, "suggestions": suggestions,
                                 "best": best})
            else:
                self._send(400, {"error": "falta q, o set + number"})
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
