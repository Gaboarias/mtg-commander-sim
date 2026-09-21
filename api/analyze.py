"""POST /api/analyze — analiza un mazo Commander: fortalezas, debilidades,
sinergias (heurístico) + combos reales (Commander Spellbook).

Body JSON: {"text": "<decklist>", "commander": "<nombre opcional>"}
Respuesta: el reporte de _analyze.analyze() + {"combos": {...}}.
"""
import json
import os
import re
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

MAX_CARDS = 200


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def run(text, commander=None):
    parsed = decklist.parse_decklist(text or "")
    if len(parsed["cards"]) > MAX_CARDS:
        raise ValueError(f"demasiadas cartas (max {MAX_CARDS})")

    cmd = commander or parsed.get("commander")
    cmd_norm = _norm(cmd) if cmd else None
    # main = todo menos el comandante
    main = [(qty, name) for qty, name in parsed["cards"] if _norm(name) != cmd_norm]

    all_names = ([cmd] if cmd else []) + [n for _, n in main]
    cache = _scry.resolve_many(all_names) if _scry is not None else {}

    entries = [(qty, name, cache.get(_norm(name))) for qty, name in main]
    if cmd:
        entries.append((1, cmd, cache.get(cmd_norm)))

    report = _analyze.analyze(entries, cmd)
    report["scryfall_online"] = _scry is not None
    report["combos"] = _analyze.find_combos(
        [cmd] if cmd else [], [n for _, n in main])

    _attach_prices(report, cache)
    return report


def _usd(raw):
    try:
        v = (raw.get("prices") or {}).get("usd")
        return round(float(v), 2) if v not in (None, "") else None
    except (TypeError, ValueError, AttributeError):
        return None


def _attach_prices(report, cache):
    """Resuelve el precio (Scryfall) de las cartas SUGERIDAS (staples de las
    recomendaciones + piezas que faltan para un combo) e inyecta el detalle."""
    # nombres sugeridos que aún no están en cache
    wanted = []
    for rec in report.get("recommendations", []):
        wanted += rec.get("cards", [])
    for c in (report.get("combos", {}) or {}).get("almost", []):
        wanted += c.get("missing", [])
    missing = [n for n in wanted if _norm(n) not in cache]
    if missing and _scry is not None:
        try:
            cache = {**cache, **_scry.resolve_many(missing)}
        except Exception:  # noqa: BLE001
            pass

    def priced(name):
        return {"name": name, "price": _usd(cache.get(_norm(name)))}

    for rec in report.get("recommendations", []):
        cards = [priced(n) for n in rec.get("cards", [])]
        rec["cards"] = cards
        sub = sum(c["price"] for c in cards if c["price"])
        rec["subtotal"] = round(sub, 2) if sub else None

    for c in (report.get("combos", {}) or {}).get("almost", []):
        c["missing_priced"] = [priced(n) for n in c.get("missing", [])]


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            body = run(req.get("text", ""), req.get("commander"))
            code = 200
        except Exception as exc:  # noqa: BLE001
            body, code = {"error": str(exc)}, 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
