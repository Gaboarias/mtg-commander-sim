"""POST /api/supporter — estado y canje del modo "supporter" (freemium suave).

Body:
  {"action":"status","code":"<sync code>"}            -> {supporter: bool}
  {"action":"redeem","code":"<sync code>","coupon":"<cupón>"} -> {supporter} | {error}

Sin cobro real: `coupon` se valida contra la env SUPPORTER_CODES (lista separada por
comas). Es el enganche para conectar Ko-fi/Patreon más adelante (un webhook podría
escribir directamente en mtg_supporters). El core del sitio NO depende de esto: solo
sube topes gratis (simulaciones grandes, más decks en la nube).
"""
import hmac
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402

_CODE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def _valid_coupons():
    """Cupones válidos: SOLO la env SUPPORTER_CODES. Antes había uno hardcodeado
    acá (público en el repo y sin forma de desactivarlo)."""
    raw = os.environ.get("SUPPORTER_CODES", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _coupon_ok(coupon):
    given = (coupon or "").strip().encode("utf-8")
    ok = False
    for c in _valid_coupons():      # recorre todos: tiempo constante por cupón
        ok |= hmac.compare_digest(given, c.encode("utf-8"))
    return bool(given) and ok


def is_supporter(code):
    """True si `code` está marcado como supporter. Tolerante a fallos (si la base
    no responde, devuelve False y el sitio sigue en modo gratis)."""
    if not code or not _CODE_RE.match(code):
        return False
    try:
        _db.ensure_schema()
        rows = _db.query("SELECT 1 FROM mtg_supporters WHERE code = ?", [code])
        return bool(rows)
    except Exception:  # noqa: BLE001
        return False


def redeem(code, coupon):
    if not _CODE_RE.match(code or ""):
        raise ValueError("código inválido")
    if not _coupon_ok(coupon):
        return {"supporter": False, "error": "cupón inválido"}
    _db.ensure_schema()
    _db.execute(
        "INSERT OR IGNORE INTO mtg_supporters (code, since) VALUES (?, ?)",
        [code, int(time.time())])
    return {"supporter": True}


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
            action = req.get("action", "status")
            if action == "status":
                body = {"supporter": is_supporter(req.get("code", ""))}
            elif action == "redeem":
                body = redeem(req.get("code", ""), req.get("coupon", ""))
            else:
                raise ValueError(f"acción desconocida: {action}")
            self._send(200, body)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
