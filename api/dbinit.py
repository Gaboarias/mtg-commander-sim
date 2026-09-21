"""GET /api/dbinit — diagnóstico de la base (Turso).

Crea las tablas si no existen y devuelve si la conexión funciona. Útil para
verificar en producción que las env vars de Turso están bien configuradas.
No expone credenciales.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _db.configured():
            body, code = {"ok": False, "error": "Turso no configurado (faltan env vars)"}, 200
        else:
            try:
                _db.ensure_schema()
                body, code = {"ok": True, "schema": "listo"}, 200
            except Exception as exc:  # noqa: BLE001
                body, code = {"ok": False, "error": str(exc)}, 200
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
