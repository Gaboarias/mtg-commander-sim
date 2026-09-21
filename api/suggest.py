"""POST /api/suggest — ¿en cuáles de mis decks sirve una carta?

Body JSON: {"card": "<nombre>", "decks": [{"name": "..", "text": "<decklist>"}, ...]}
Respuesta: {"card", "roles", "colors", "decks": [{name, in_color, fills, verdict, score}]}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):            # api/ (para _analyze/_scry) y raíz (decklist)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import decklist  # noqa: E402
import _analyze  # noqa: E402

try:
    import _scry
except Exception:  # noqa: BLE001
    _scry = None

MAX_DECKS = 8


def run(card, decks):
    card = (card or "").strip()
    if not card:
        raise ValueError("falta la carta")
    decks = (decks or [])[:MAX_DECKS]

    parsed_decks = []
    names = [card]
    for d in decks:
        p = decklist.parse_decklist(d.get("text", ""))
        parsed_decks.append({"name": d.get("name") or "deck", "parsed": p})
        if p.get("commander"):
            names.append(p["commander"])
        names += [n for _, n in p["cards"]]

    cache = _scry.resolve_many(names) if _scry is not None else {}
    return _analyze.suggest_decks(card, parsed_decks, cache)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            body = run(req.get("card", ""), req.get("decks", []))
            code = 200
        except Exception as exc:  # noqa: BLE001
            body, code = {"error": str(exc)}, 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
