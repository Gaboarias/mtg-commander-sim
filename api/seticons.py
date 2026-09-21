"""GET /api/seticons -> {"icons": {SETCODE: icon_svg_uri}}

Una sola llamada a Scryfall /sets con todos los sets; el front la cruza con el
codigo de cada precon para mostrar el simbolo del set. Cacheado fuerte (7 dias).
"""
import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ en el path

_SETS = "https://api.scryfall.com/sets"
_UA = "mtg-commander-sim/1.0 (https://github.com/Gaboarias/mtg-commander-sim)"

_cache = None


def _set_icons():
    global _cache
    if _cache is not None:
        return _cache
    req = urllib.request.Request(
        _SETS, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    icons = {}
    for s in data.get("data", []):
        code = (s.get("code") or "").upper()
        icon = s.get("icon_svg_uri")
        if code and icon:
            icons[code] = icon
    _cache = icons
    return icons


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = {"icons": _set_icons()}
            cache = "s-maxage=604800"
            code = 200
        except Exception as exc:  # noqa: BLE001
            body = {"error": f"Scryfall no disponible: {exc}", "icons": {}}
            cache = "no-store"
            code = 502
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(payload)
