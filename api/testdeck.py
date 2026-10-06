"""POST /api/testdeck — arma un DECK DE PRUEBA sobre un mazo, sumando las
recomendaciones de combos (piezas que faltan) y de mejora (staples por rol).

Body JSON: {"text": "<decklist>", "commander": "<nombre opcional>"}
Respuesta: {ok, text, commander, identity, added_combos, added_upgrades, cut,
            deck_size, note}  (text = decklist lista para cargar/simular)
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import decklist  # noqa: E402
import _analyze  # noqa: E402

try:
    import _scry
except Exception:  # noqa: BLE001
    _scry = None

MAX_CARDS = 200


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def run(text, commander=None):
    parsed = decklist.parse_decklist(text or "")
    if len(parsed["cards"]) > MAX_CARDS:
        raise ValueError(f"demasiadas cartas (max {MAX_CARDS})")
    cmd = commander or parsed.get("commander")
    if not cmd:
        raise ValueError("No se encontró comandante. Marcá uno (sección Commander).")

    cmd_norm = _norm(cmd)
    main = [(q, n) for q, n in parsed["cards"] if _norm(n) != cmd_norm]

    # nombres a resolver: mazo + comandante + TODOS los staples candidatos (para
    # poder filtrarlos por color), y después las piezas de combo que falten.
    staples = [s for role in _analyze._STAPLES.values() for s in role]
    names = [cmd] + [n for _, n in main] + staples
    cache = _scry.resolve_many(names) if _scry is not None else {}

    # identidad para filtrar los 'almost' en color
    ident = set((cache.get(cmd_norm) or {}).get("color_identity") or [])
    if not ident:
        for _q, n in main:
            ident |= set((cache.get(_norm(n)) or {}).get("color_identity") or [])

    combos = _analyze.find_combos([cmd], [n for _, n in main], identity=ident)

    # resolver las piezas de combo que falten (para chequear su color)
    missing = [m for a in combos.get("almost", []) for m in a.get("missing", [])]
    missing = [m for m in missing if _norm(m) not in cache]
    if missing and _scry is not None:
        cache.update(_scry.resolve_many(missing))

    res = _analyze.build_test_deck(parsed, cache, cmd, combos)
    res["scryfall_online"] = _scry is not None
    if combos.get("error"):
        res["combos_note"] = f"Combos externos no disponibles ({combos['error']}); usé los locales."
    return res


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
            self._send(200, run(req.get("text", ""), req.get("commander")))
        except ValueError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(502, {"ok": False, "error": f"No se pudo armar: {exc}"})
