"""POST /api/admin — panel de estadísticas (solo admin).

Body: {"action":"stats","token":"<token de sesión admin>"}
Devuelve conteos globales + top comandantes + últimas partidas/usuarios.
Sin token admin: 403. No expone hashes ni datos sensibles.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402
import _auth  # noqa: E402
import stats as _stats  # noqa: E402


def _count(sql):
    try:
        rows = _db.query(sql, [])
        return rows[0].get("n", 0) if rows else 0
    except Exception:  # noqa: BLE001
        return 0


def admin_stats():
    _db.ensure_schema()
    counts = {
        "users": _count("SELECT COUNT(*) AS n FROM mtg_users"),
        "supporters": _count("SELECT COUNT(*) AS n FROM mtg_users WHERE is_supporter = 1")
                      + _count("SELECT COUNT(*) AS n FROM mtg_supporters"),
        "decks": _count("SELECT COUNT(*) AS n FROM mtg_decks"),
        "shares": _count("SELECT COUNT(*) AS n FROM mtg_shares"),
        "matches": _count("SELECT COUNT(*) AS n FROM mtg_matches"),
    }
    top = _stats.top(15)
    recent_matches = _db.query(
        "SELECT winner, turns, created_at FROM mtg_matches ORDER BY id DESC LIMIT 10", [])
    recent_users = _db.query(
        "SELECT email, is_admin, is_supporter, created_at FROM mtg_users "
        "ORDER BY created_at DESC LIMIT 10", [])
    return {"counts": counts, "top": top.get("top", []),
            "recent_matches": recent_matches, "recent_users": recent_users}


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
            u = _auth.user_from_token(req.get("token"))
            if not (u and u.get("is_admin")):
                self._send(403, {"error": "solo admin"})
                return
            self._send(200, admin_stats())
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
