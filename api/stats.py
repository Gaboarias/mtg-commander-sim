"""GET /api/stats — ranking global de partidas (anónimo).

GET /api/stats?limit=15  -> {top:[{commander, games, wins, pct}], total}

Las partidas las registra el SERVIDOR (`record`, llamado desde /api/replay con el
resultado que él mismo simuló). El POST público quedó como no-op: antes cualquiera
podía inventar resultados o guardar datos basura que rompían el ranking y /admin.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402


MAX_PLAYERS = 6
MAX_NAME = 120
RECENT = 5000          # el ranking mira las últimas N partidas (costo acotado)


def _clean_names(commanders):
    if not isinstance(commanders, list):
        return []
    out = [c.strip()[:MAX_NAME] for c in commanders if isinstance(c, str) and c.strip()]
    return out[:MAX_PLAYERS]


def record(winner, commanders, turns, timeout=5):
    """Registra una partida simulada por el servidor. Valida forma y tamaño:
    2-6 nombres de texto y un ganador que esté entre ellos."""
    cmds = _clean_names(commanders)
    w = winner.strip()[:MAX_NAME] if isinstance(winner, str) else ""
    if len(cmds) < 2 or w not in cmds:
        return {"ok": False}
    try:
        t = max(0, min(int(turns or 0), 10_000))
    except (TypeError, ValueError):
        t = 0
    _db.ensure_schema()
    _db.run([(
        "INSERT INTO mtg_matches (winner, commanders, turns, created_at) VALUES (?, ?, ?, ?)",
        [w, json.dumps(cmds), t, int(time.time())])], timeout=timeout)
    return {"ok": True}


def top(limit=30):
    limit = max(1, min(int(limit), 50))
    _db.ensure_schema()
    rows = _db.query(
        "SELECT winner, commanders FROM mtg_matches ORDER BY id DESC LIMIT ?", [RECENT])
    games, wins = {}, {}
    for r in rows:
        try:
            cmds = _clean_names(json.loads(r.get("commanders") or "[]"))
        except (TypeError, ValueError):
            cmds = []
        for c in cmds:
            games[c] = games.get(c, 0) + 1
        w = r.get("winner")
        if isinstance(w, str) and w:     # filas viejas con basura no rompen el ranking
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
        # no-op compatible: clientes viejos lo siguen llamando tras cada replay,
        # pero el resultado ya lo registró /api/replay en el servidor
        self._send(200, {"ok": True, "ignored": True})
