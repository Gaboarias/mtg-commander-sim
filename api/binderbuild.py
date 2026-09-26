"""POST /api/binderbuild — ¿qué mazo puedo armar con mi binder?

Body JSON: {"cards": ["<nombre>", ...]}   (nombres del binder, con o sin cantidad)
Respuesta: build_from_pool(...) — comandante sugerido, cartas usables, análisis
profundo, qué falta para ~99, bracket estimado y game changers en color para subir.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _analyze  # noqa: E402
import gamechangers  # noqa: E402

try:
    import _scry
except Exception:  # noqa: BLE001
    _scry = None

MAX_POOL = 400


def run(cards):
    names = []
    for c in (cards or [])[:MAX_POOL]:
        s = (c or "").strip()
        if s:
            names.append(s)
    if not names:
        raise ValueError("el binder está vacío")

    # resolvemos el pool + los game changers (para conocer su identidad de color)
    gc_names = list(gamechangers.GAME_CHANGERS_RAW)
    cache = _scry.resolve_many(names + gc_names) if _scry is not None else {}
    gc_cards = {_analyze._norm(n): cache.get(_analyze._norm(n)) for n in gc_names}
    return _analyze.build_from_pool(names, cache, gc_cards=gc_cards)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            body = run(req.get("cards", []))
            code = 200
        except Exception as exc:  # noqa: BLE001
            body, code = {"error": str(exc)}, 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
