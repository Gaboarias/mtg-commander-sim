"""GET /api/health  — diagnostico SIN red.

Sirve para aislar problemas de deploy: si esto responde 200 con la lista de
mazos, las funciones Python y el import del motor funcionan (el problema seria
de red, Scryfall/MTGJSON). Si da 500, el bundling del motor esta fallando.
"""
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"ok": False, "python": sys.version.split()[0]}
        code = 500
        try:
            import _sim  # importa engine/decks/run via bridge
            body["decks"] = list(_sim.decks.DECKS.keys())
            body["scryfall_module"] = _sim._scry is not None
            body["ok"] = True
            code = 200
        except Exception:  # noqa: BLE001
            body["error"] = traceback.format_exc()[-1500:]
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
