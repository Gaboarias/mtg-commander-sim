"""Autenticación por email + contraseña sobre Turso (solo stdlib).

Seguridad: contraseñas y código de recuperación con pbkdf2_hmac (sha256, muchas
iteraciones) + salt por usuario; comparación en tiempo constante; errores
genéricos (no revela si el email existe); largo mínimo; throttling de intentos;
sesiones con expiración. Sin proveedor de email: la recuperación es por CÓDIGO
que se muestra UNA vez al registrarse (el usuario lo guarda).
"""
import hashlib
import hmac
import os
import re
import secrets
import time

import _db
import supporter as _supporter

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "garias1989@gmail.com").strip().lower()
_ITERS = 240_000
_SESSION_TTL = 90 * 86400          # 90 días
_MAX_FAILS = 5
_LOCK_SECS = 300                    # bloqueo tras 5 fallos, 5 min
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PW = 8


def _hash(secret, salt):
    return hashlib.pbkdf2_hmac("sha256", (secret or "").encode("utf-8"),
                               bytes.fromhex(salt), _ITERS).hex()


def _new_salt():
    return secrets.token_hex(16)


def _recovery_code():
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # sin caracteres ambiguos
    grp = lambda: "".join(secrets.choice(alpha) for _ in range(4))
    return f"{grp()}-{grp()}-{grp()}"


def _now():
    return int(time.time())


def _user_row(email):
    rows = _db.query("SELECT * FROM mtg_users WHERE email = ?", [email])
    return rows[0] if rows else None


def _public(u):
    return {"id": u["id"], "email": u["email"],
            "is_admin": bool(u["is_admin"]), "is_supporter": bool(u["is_supporter"])}


def _new_session(user_id):
    token = secrets.token_urlsafe(32)
    _db.execute("INSERT INTO mtg_sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                [token, user_id, _now()])
    return token


def register(email, pw):
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("email inválido")
    if len(pw or "") < _MIN_PW:
        raise ValueError(f"la contraseña necesita al menos {_MIN_PW} caracteres")
    _db.ensure_schema()
    if _user_row(email):
        raise ValueError("ese email ya está registrado")
    uid = secrets.token_hex(12)
    salt, rsalt = _new_salt(), _new_salt()
    rcode = _recovery_code()
    is_admin = 1 if email == ADMIN_EMAIL else 0
    _db.execute(
        "INSERT INTO mtg_users (id, email, pass_hash, salt, recovery_hash, "
        "recovery_salt, is_admin, is_supporter, created_at, fails, last_fail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
        [uid, email, _hash(pw, salt), salt, _hash(rcode, rsalt), rsalt,
         is_admin, is_admin, _now()])
    token = _new_session(uid)
    return {"token": token,
            "user": {"id": uid, "email": email, "is_admin": bool(is_admin),
                     "is_supporter": bool(is_admin)},
            "recovery_code": rcode}


def login(email, pw):
    email = (email or "").strip().lower()
    _db.ensure_schema()
    u = _user_row(email)
    generic = ValueError("email o contraseña incorrectos")
    if not u:
        raise generic
    if (u.get("fails") or 0) >= _MAX_FAILS and _now() - (u.get("last_fail") or 0) < _LOCK_SECS:
        raise ValueError("demasiados intentos; esperá unos minutos")
    if not hmac.compare_digest(_hash(pw, u["salt"]), u["pass_hash"]):
        _db.execute("UPDATE mtg_users SET fails = fails + 1, last_fail = ? WHERE id = ?",
                    [_now(), u["id"]])
        raise generic
    _db.execute("UPDATE mtg_users SET fails = 0 WHERE id = ?", [u["id"]])
    return {"token": _new_session(u["id"]), "user": _public(u)}


def reset_password(email, recovery_code, new_pw):
    email = (email or "").strip().lower()
    if len(new_pw or "") < _MIN_PW:
        raise ValueError(f"la contraseña necesita al menos {_MIN_PW} caracteres")
    _db.ensure_schema()
    u = _user_row(email)
    if not u or not u.get("recovery_hash") or not hmac.compare_digest(
            _hash(recovery_code, u["recovery_salt"]), u["recovery_hash"]):
        raise ValueError("email o código de recuperación incorrectos")
    salt, rsalt = _new_salt(), _new_salt()
    rcode = _recovery_code()
    _db.run([
        ("UPDATE mtg_users SET pass_hash = ?, salt = ?, recovery_hash = ?, "
         "recovery_salt = ?, fails = 0 WHERE id = ?",
         [_hash(new_pw, salt), salt, _hash(rcode, rsalt), rsalt, u["id"]]),
        ("DELETE FROM mtg_sessions WHERE user_id = ?", [u["id"]]),   # cierra sesiones viejas
    ])
    return {"token": _new_session(u["id"]), "user": _public(u), "recovery_code": rcode}


def user_from_token(token):
    if not token:
        return None
    try:
        _db.ensure_schema()
        rows = _db.query(
            "SELECT u.*, s.created_at AS s_created FROM mtg_sessions s "
            "JOIN mtg_users u ON u.id = s.user_id WHERE s.token = ?", [token])
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    u = rows[0]
    if _now() - (u.get("s_created") or 0) > _SESSION_TTL:
        return None
    return u


def logout(token):
    if token:
        _db.execute("DELETE FROM mtg_sessions WHERE token = ?", [token])
    return {"ok": True}


def identity(code, token):
    """Identidad efectiva para topes y owner de la nube.
    owner = id de usuario si hay sesión válida, si no el código anónimo."""
    u = user_from_token(token)
    admin = bool(u and u.get("is_admin"))
    sup = admin or bool(u and u.get("is_supporter")) or _supporter.is_supporter(code)
    owner = u["id"] if u else (code or "")
    return {"owner": owner, "admin": admin, "supporter": sup,
            "email": u["email"] if u else None}
