"""Cliente mínimo de Turso (libSQL) por HTTP — solo stdlib (urllib).

La integración Turso↔Vercel inyecta las credenciales como variables de entorno.
Leemos varios nombres posibles por robustez. Todo el acceso a la base es
server-side: el token nunca llega al navegador.

API usada: POST {host}/v2/pipeline con {"requests":[{execute}, {close}]}.
Docs: https://docs.turso.tech/sdk/http/reference
"""
import json
import os
import urllib.request

_URL_KEYS = ("TURSO_DATABASE_URL", "TURSO_DB_URL", "LIBSQL_URL", "DATABASE_URL")
_TOKEN_KEYS = ("TURSO_AUTH_TOKEN", "TURSO_TOKEN", "LIBSQL_AUTH_TOKEN", "DATABASE_AUTH_TOKEN")


def configured() -> bool:
    return bool(_env(_URL_KEYS) and _env(_TOKEN_KEYS))


def _env(keys):
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    return None


def _endpoint():
    url = _env(_URL_KEYS)
    token = _env(_TOKEN_KEYS)
    if not url or not token:
        raise RuntimeError("Turso no configurado (faltan env vars de conexión)")
    # libsql://host  ->  https://host/v2/pipeline
    http = url.replace("libsql://", "https://").rstrip("/")
    if not http.startswith("http"):
        http = "https://" + http
    return http + "/v2/pipeline", token


def _encode_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": str(v)}
    return {"type": "text", "value": str(v)}


def _decode_val(cell):
    t = cell.get("type")
    val = cell.get("value")
    if t == "null" or val is None:
        return None
    if t == "integer":
        try:
            return int(val)
        except (TypeError, ValueError):
            return val
    if t == "float":
        try:
            return float(val)
        except (TypeError, ValueError):
            return val
    return val


def run(statements, timeout=20):
    """statements: lista de (sql, args). Ejecuta todo en UN pipeline (misma
    conexión, secuencial). Devuelve una lista de dicts por statement:
    {rows:[{col:val}...], affected:int, last_insert_rowid:int|None}."""
    endpoint, token = _endpoint()
    reqs = [{"type": "execute",
             "stmt": {"sql": sql, "args": [_encode_arg(a) for a in (args or [])]}}
            for sql, args in statements]
    reqs.append({"type": "close"})
    body = json.dumps({"requests": reqs}).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out = []
    for r in data.get("results", []):
        if r.get("type") != "ok":
            raise RuntimeError((r.get("error") or {}).get("message") or "error de Turso")
        resp_obj = r.get("response") or {}
        if resp_obj.get("type") != "execute":
            continue
        res = resp_obj.get("result") or {}
        cols = [c.get("name") for c in (res.get("cols") or [])]
        rows = [dict(zip(cols, (_decode_val(cell) for cell in row)))
                for row in (res.get("rows") or [])]
        lir = res.get("last_insert_rowid")
        out.append({"rows": rows,
                    "affected": res.get("affected_row_count", 0),
                    "last_insert_rowid": int(lir) if lir not in (None, "") else None})
    return out


def query(sql, args=None):
    return run([(sql, args or [])])[0]["rows"]


def execute(sql, args=None):
    return run([(sql, args or [])])[0]


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mtg_decks (
         owner_code TEXT NOT NULL, deck_id TEXT NOT NULL, name TEXT,
         text TEXT, colors TEXT, updated_at INTEGER,
         PRIMARY KEY (owner_code, deck_id))""",
    """CREATE TABLE IF NOT EXISTS mtg_binder (
         owner_code TEXT PRIMARY KEY, cards TEXT, updated_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS mtg_shares (
         id TEXT PRIMARY KEY, name TEXT, text TEXT, commander TEXT,
         created_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS mtg_matches (
         id INTEGER PRIMARY KEY AUTOINCREMENT, winner TEXT, commanders TEXT,
         turns INTEGER, created_at INTEGER)""",
]


def ensure_schema():
    """Crea las tablas si no existen (idempotente)."""
    run([(sql, []) for sql in _SCHEMA])
