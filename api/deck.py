"""POST /api/deck  — import y simulacion de decks editados.

Body JSON:
  {"action":"resolve",  "list":"<texto decklist>"}
  {"action":"simulate", "cards":[{"name":..,"qty":..}], "commander":"..",
                        "opponent":"tricky", "n":200}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import resolve_decklist, simulate_custom, FREE_N, MAX_N  # noqa: E402
import _auth  # noqa: E402


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
            action = req.get("action", "resolve")
            if action == "resolve":
                body = resolve_decklist(req.get("list", ""))
            elif action == "simulate":
                ident = _auth.identity(req.get("code"), req.get("token"))
                cap = MAX_N if ident["supporter"] else FREE_N
                n = min(int(req.get("n", 100)), cap)
                body = simulate_custom(
                    req.get("cards", []), req.get("commander", ""),
                    req.get("opponent", "kang"), n)
                body["free_cap"] = cap
            else:
                raise ValueError(f"accion desconocida: {action}")
            self._send(200, body)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
