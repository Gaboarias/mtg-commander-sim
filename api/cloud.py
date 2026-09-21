"""POST/GET /api/cloud — sync de decks/binder por código anónimo + compartir deck.

POST body:
  {"action":"pull","code":"<uuid>"}            -> {decks:[...], binder:[...]}
  {"action":"push","code":"<uuid>","decks":[...],"binder":[...]}  -> {ok, updated_at}
  {"action":"share","name":..,"text":..,"commander":..}           -> {id}
GET:
  /api/cloud?share=<id>                         -> {name, text, commander} | 404

Sin login: el `code` es un UUID secreto; el acceso es server-side y filtrado por él.
"""
import json
import os
import re
import sys
import time
import random
import string
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _db  # noqa: E402
from supporter import is_supporter  # noqa: E402

_CODE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
FREE_DECKS = 5         # tope gratis de decks en la nube (supporter sin tope práctico)


def _now():
    return int(time.time())


def _short_id(n=8):
    alpha = string.ascii_lowercase + string.digits
    return "".join(random.choice(alpha) for _ in range(n))


def pull(code):
    if not _CODE_RE.match(code or ""):
        raise ValueError("código inválido")
    _db.ensure_schema()
    decks = _db.query(
        "SELECT deck_id, name, text, colors, updated_at FROM mtg_decks "
        "WHERE owner_code = ? ORDER BY updated_at DESC", [code])
    for d in decks:
        try:
            d["colors"] = json.loads(d.get("colors") or "[]")
        except (TypeError, ValueError):
            d["colors"] = []
    brows = _db.query("SELECT cards FROM mtg_binder WHERE owner_code = ?", [code])
    binder = []
    if brows:
        try:
            binder = json.loads(brows[0].get("cards") or "[]")
        except (TypeError, ValueError):
            binder = []
    return {"decks": decks, "binder": binder}


def push(code, decks, binder):
    if not _CODE_RE.match(code or ""):
        raise ValueError("código inválido")
    _db.ensure_schema()
    decks = decks or []
    capped = False
    if not is_supporter(code) and len(decks) > FREE_DECKS:
        decks = decks[:FREE_DECKS]
        capped = True
    stmts = [("DELETE FROM mtg_decks WHERE owner_code = ?", [code])]
    now = _now()
    for d in decks[:200]:
        stmts.append((
            "INSERT INTO mtg_decks (owner_code, deck_id, name, text, colors, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [code, str(d.get("id") or _short_id()), d.get("name") or "deck",
             d.get("text") or "", json.dumps(d.get("colors") or []),
             int(d.get("updatedAt") or now)]))
    stmts.append((
        "INSERT OR REPLACE INTO mtg_binder (owner_code, cards, updated_at) VALUES (?, ?, ?)",
        [code, json.dumps(binder or []), now]))
    _db.run(stmts)
    return {"ok": True, "updated_at": now, "capped": capped, "limit": FREE_DECKS}


def share_put(name, text, commander):
    if not (text or "").strip():
        raise ValueError("lista vacía")
    _db.ensure_schema()
    sid = _short_id(8)
    _db.execute(
        "INSERT INTO mtg_shares (id, name, text, commander, created_at) VALUES (?, ?, ?, ?, ?)",
        [sid, (name or "deck")[:120], text, (commander or "")[:120], _now()])
    return {"id": sid}


def share_get(sid):
    if not _CODE_RE.match(sid or ""):
        return None
    rows = _db.query(
        "SELECT name, text, commander FROM mtg_shares WHERE id = ?", [sid])
    return rows[0] if rows else None


def _dispatch(req):
    action = req.get("action")
    if action == "pull":
        return pull(req.get("code", ""))
    if action == "push":
        return push(req.get("code", ""), req.get("decks", []), req.get("binder", []))
    if action == "share":
        return share_put(req.get("name"), req.get("text"), req.get("commander"))
    raise ValueError(f"acción desconocida: {action}")


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("share") or [""])[0]
            row = share_get(sid)
            if row is None:
                self._send(404, {"error": "no encontrado"})
            else:
                self._send(200, row)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            self._send(200, _dispatch(req))
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})
