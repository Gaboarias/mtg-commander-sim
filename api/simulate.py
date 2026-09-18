"""GET /api/simulate?matchup=lorehold,kang&n=200
   GET /api/simulate?matchup=lorehold,kang&log=1&seed=0

Devuelve winrates (n partidas) o el registro de una partida (log=1).
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import simulate, game_log  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        matchup = (qs.get("matchup", ["lorehold,kang"])[0]).split(",")
        matchup = [m.strip() for m in matchup if m.strip()]
        try:
            if qs.get("log", ["0"])[0] in ("1", "true"):
                seed = qs.get("seed", ["0"])[0]
                body = game_log(matchup, seed)
            else:
                n = qs.get("n", ["200"])[0]
                body = simulate(matchup, n)
            code = 200
        except Exception as exc:  # noqa: BLE001
            body = {"error": str(exc)}
            code = 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
