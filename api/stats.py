"""POST/GET /api/stats — ranking global de partidas (anónimo).

POST body: {"winner":"<comandante>", "commanders":["..",".."], "turns": 8}
  registra una partida (best-effort desde /watch o el simulador batch).
GET /api/stats?top=1  -> {top:[{commander, games, wins, pct}], total}
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402


def record(winner, commanders, turns):
    _db.ensure_schema()
    _db.execute(
        "INSERT INTO mtg_matches (winner, commanders, turns, created_at) VALUES (?, ?, ?, ?)",
        [(winner or "")[:120], json.dumps(commanders or []),
         int(turns or 0), int(time.time())])
    return {"ok": True}


def top(limit=30):
    _db.ensure_schema()
    rows = _db.query("SELECT winner, commanders FROM mtg_matches", [])
    games, wins = {}, {}
    for r in rows:
        try:
            cmds = json.loads(r.get("commanders") or "[]")
        except (TypeError, ValueError):
            cmds = []
        for c in cmds:
            games[c] = games.get(c, 0) + 1
        w = r.get("winner")
        if w:
            wins[w] = wins.get(w, 0) + 1
    table = []
    for c, g in games.items():
        won = wins.get(c, 0)
        table.append({"commander": c, "games": g, "wins": won,
                      "pct": round(100 * won / g, 1) if g else 0.0})
    table.sort(key=lambda x: (x["pct"], x["games"]), reverse=True)
    return {"top": table[:limit], "total": len(rows)}


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            lim = int((qs.get("limit") or ["30"])[0])
            self._send(200, top(lim))
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            self._send(200, record(req.get("winner"), req.get("commanders"), req.get("turns")))
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
