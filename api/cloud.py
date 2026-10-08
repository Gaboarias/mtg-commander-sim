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
import _auth  # noqa: E402

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
    rows = _db.query(
        "SELECT deck_id, name, text, colors, updated_at FROM mtg_decks "
        "WHERE owner_code = ? ORDER BY updated_at DESC", [code])
    decks = []
    for r in rows:
        try:
            colors = json.loads(r.get("colors") or "[]")
        except (TypeError, ValueError):
            colors = []
        # misma forma que SavedDeck del cliente (id/updatedAt), no la de la tabla
        decks.append({"id": r.get("deck_id"), "name": r.get("name"),
                      "text": r.get("text") or "", "colors": colors,
                      "updatedAt": int(r.get("updated_at") or 0)})
    brows = _db.query("SELECT cards FROM mtg_binder WHERE owner_code = ?", [code])
    binder = []
    if brows:
        try:
            binder = json.loads(brows[0].get("cards") or "[]")
        except (TypeError, ValueError):
            binder = []
    return {"decks": decks, "binder": binder}


_UPSERT_DECK = (
    "INSERT INTO mtg_decks (owner_code, deck_id, name, text, colors, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(owner_code, deck_id) DO UPDATE SET name = excluded.name, "
    "text = excluded.text, colors = excluded.colors, updated_at = excluded.updated_at "
    "WHERE excluded.updated_at >= mtg_decks.updated_at")


def push(code, decks, binder, supporter=False, deleted=None):
    """Fusiona, no reemplaza: upsert por deck_id (gana la versión más reciente) y
    solo borra los ids que el cliente manda en `deleted`. Antes hacía DELETE de
    todo + reinsertar lo local: un dispositivo sin decks (o un autosave del
    binder) vaciaba la nube. `binder=None` deja el binder de la nube intacto."""
    if not _CODE_RE.match(code or ""):
        raise ValueError("código inválido")
    _db.ensure_schema()
    decks = [d for d in (decks or []) if isinstance(d, dict)][:200]
    deleted = {str(i) for i in (deleted or []) if isinstance(i, (str, int))}
    existing = {r.get("deck_id") for r in _db.query(
        "SELECT deck_id FROM mtg_decks WHERE owner_code = ?", [code])}
    kept = existing - deleted
    stmts = [("DELETE FROM mtg_decks WHERE owner_code = ? AND deck_id = ?", [code, i])
             for i in sorted(deleted & existing)]
    now_ms = int(time.time() * 1000)   # el cliente usa Date.now() (ms)
    capped = False
    for d in decks:
        did = str(d.get("id") or _short_id())
        if did in deleted:
            continue
        if did not in kept:
            # tope gratis: los decks ya guardados siempre se pueden actualizar
            if not supporter and len(kept) >= FREE_DECKS:
                capped = True
                continue
            kept.add(did)
        stmts.append((_UPSERT_DECK, [
            code, did, d.get("name") or "deck", d.get("text") or "",
            json.dumps(d.get("colors") or []), int(d.get("updatedAt") or now_ms)]))
    now = _now()
    if binder is not None:
        stmts.append((
            "INSERT OR REPLACE INTO mtg_binder (owner_code, cards, updated_at) VALUES (?, ?, ?)",
            [code, json.dumps(binder), now]))
    if stmts:
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
    ident = _auth.identity(req.get("code", ""), req.get("token"))
    owner = ident["owner"]
    if action == "pull":
        return pull(owner)
    if action == "push":
        return push(owner, req.get("decks", []), req.get("binder"), ident["supporter"],
                    req.get("deleted"))
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
