"""POST /api/feedback — recibe comentarios de los usuarios.

Body:
  {"message":"...", "rating":1-5|null, "page":"/play", "contact":"", "code":"<sync>"}
  -> {"ok": true} | {"ok": false, "error": "..."}

Guarda en la tabla mtg_feedback (Turso). Si la base no está configurada, devuelve
ok:false para que el front ofrezca un fallback (mailto). No expone credenciales.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402

_MAX = 4000


def save(message, rating, page, contact, code):
    msg = (message or "").strip()[:_MAX]
    if not msg:
        return {"ok": False, "error": "mensaje vacío"}
    try:
        r = int(rating)
        if not (1 <= r <= 5):
            r = None
    except (TypeError, ValueError):
        r = None
    if not _db.configured():
        return {"ok": False, "error": "sin base configurada"}
    _db.ensure_schema()
    _db.execute(
        "INSERT INTO mtg_feedback (code, rating, message, page, contact, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(code or "")[:64], r, msg, (page or "")[:120],
         (contact or "").strip()[:200], int(time.time())])
    return {"ok": True}


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
            body = save(req.get("message", ""), req.get("rating"),
                        req.get("page", ""), req.get("contact", ""),
                        req.get("code", ""))
            self._send(200, body)
        except Exception as exc:  # noqa: BLE001
            self._send(200, {"ok": False, "error": str(exc)})
