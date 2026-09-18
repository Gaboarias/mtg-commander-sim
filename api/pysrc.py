"""GET /api/pysrc — devuelve el código fuente de los módulos del motor para
cargarlo en Pyodide (navegador). Solo módulos puros (sin red).

Respuesta: {"modules": {"engine.py": "<source>", ...}}
"""
import json
import os
from http.server import BaseHTTPRequestHandler

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# módulos que necesita interactive.InteractiveGame con decks de ejemplo
_MODULES = [
    "engine.py", "cards.py", "cardsdb.py", "decklist.py", "mdparse.py",
    "policy.py", "decks.py", "run.py", "interactive.py",
]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        mods = {}
        for fn in _MODULES:
            try:
                with open(os.path.join(_ROOT, fn), encoding="utf-8") as f:
                    mods[fn] = f.read()
            except Exception:  # noqa: BLE001
                pass
        payload = json.dumps({"modules": mods}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
