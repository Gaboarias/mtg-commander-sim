"""GET /api/samples           -> decks de ejemplo bundleados (presets/text/*.txt)
   GET /api/samples?load=slug  -> ese deck como texto (para el editor)

Son listas en texto (Moxfield/`1 Nombre`) que se resuelven con Scryfall en el
editor. No son decks offline como los .md de presets/.
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "presets", "text")


def _slug_ok(slug):
    return bool(re.match(r"^[A-Za-z0-9_-]+$", slug or ""))


def _title(text, slug):
    # comandante = primera linea '1 X' tras 'Commander'
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "commander":
            for nxt in lines[i + 1:]:
                m = re.match(r"^\s*\d+\s+(.+?)\s*$", nxt)
                if m:
                    return m.group(1)
                if nxt.strip():
                    break
    return slug


def _list():
    out = []
    if not os.path.isdir(_DIR):
        return out
    for fn in sorted(os.listdir(_DIR)):
        if not fn.endswith(".txt"):
            continue
        slug = fn[:-4]
        try:
            text = open(os.path.join(_DIR, fn), encoding="utf-8").read()
        except Exception:  # noqa: BLE001
            continue
        out.append({"slug": slug, "name": _title(text, slug)})
    return out


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=3600")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        load = qs.get("load", [None])[0]
        try:
            if load:
                if not _slug_ok(load):
                    raise ValueError("slug invalido")
                path = os.path.join(_DIR, load + ".txt")
                if not os.path.isfile(path):
                    raise ValueError("deck de ejemplo no encontrado")
                text = open(path, encoding="utf-8").read()
                self._send(200, {"slug": load, "name": _title(text, load),
                                 "text": text})
            else:
                self._send(200, {"samples": _list()})
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
