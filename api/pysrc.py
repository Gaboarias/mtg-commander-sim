"""GET /api/pysrc — devuelve el código fuente de los módulos del motor para
cargarlo en Pyodide (navegador). Solo módulos puros (sin red).

Respuesta: {"modules": {"engine.py": "<source>", ...}}
"""
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# módulos que necesita interactive.InteractiveGame con decks de ejemplo
_MODULES = [
    "carddesc.py", "engine.py", "cards.py", "abilities.py", "cardsdb.py",
    "decklist.py", "mdparse.py", "policy.py", "decks.py", "run.py",
    "interactive.py",
    "data/preset_cards.json",      # datos reales de las cartas de los presets
    "data/keyword_reminders.json", # recordatorios de habilidades sin implementación
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
        # ETag por contenido: el navegador revalida y, si no cambió (mismo deploy),
        # recibe un 304 en vez de bajar ~900 KB en cada visita a /play
        etag = '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("ETag", etag)
        # navegador: siempre revalida; CDN de Vercel: cachea (se purga en cada deploy)
        self.send_header("Cache-Control", "public, max-age=0, must-revalidate, s-maxage=86400")
        self.end_headers()
        self.wfile.write(payload)
