"""POST /api/auth — cuentas (email + contraseña) sobre Turso.

Body: {"action": "register"|"login"|"reset"|"logout"|"whoami", ...}
- register {email, password}     -> {token, user, recovery_code}
- login    {email, password}     -> {token, user}
- reset    {email, recovery_code, password} -> {token, user, recovery_code}
- logout   {token}               -> {ok}
- whoami   {token}               -> {user} | {user: null}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _auth  # noqa: E402


def _dispatch(req):
    action = req.get("action")
    if action == "register":
        return _auth.register(req.get("email"), req.get("password"))
    if action == "login":
        return _auth.login(req.get("email"), req.get("password"))
    if action == "reset":
        return _auth.reset_password(req.get("email"), req.get("recovery_code"),
                                    req.get("password"))
    if action == "logout":
        return _auth.logout(req.get("token"))
    if action == "whoami":
        u = _auth.user_from_token(req.get("token"))
        return {"user": _auth._public(u) if u else None}
    raise ValueError(f"acción desconocida: {action}")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            body, code = _dispatch(req), 200
        except Exception as exc:  # noqa: BLE001
            body, code = {"error": str(exc)}, 400
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
