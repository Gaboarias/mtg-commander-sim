"""POST /api/replay — juega UNA partida y devuelve la traza para el reproductor
visual (Fase 1).

Body JSON:
  {"decks":[{"kind":"registered","key":"marvel","name":"Kang"},
            {"kind":"custom","name":"Mi deck","text":"<decklist>"}, ...],
   "seed": 0, "level": "intermedio"}
"""
import gzip
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path
from _sim import replay  # noqa: E402
import stats as _stats  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body).encode("utf-8")
        # la traza (una foto de la mesa por paso) pesa 3-9 MB con 4-6 mazos y Vercel
        # corta las respuestas en 4,5 MB; comprimida queda ~70x más chica
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            payload = gzip.compress(payload, compresslevel=6)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            res = replay(req.get("decks", []), req.get("seed", 0),
                         req.get("level", "intermedio"))
            # ranking global: lo registra el servidor con el resultado que simuló
            # (best-effort: si la base no responde, el replay sale igual)
            if res.get("winner") and res["winner"] != "EMPATE" and _stats._db.configured():
                try:
                    _stats.record(res["winner"], res.get("players"), res.get("turns"))
                except Exception:  # noqa: BLE001
                    pass
            self._send(200, res)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
