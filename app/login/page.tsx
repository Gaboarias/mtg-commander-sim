"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getUser, setSession, clearSession, effectiveCode, getToken, type User } from "../auth";
import { listDecks, listBinder } from "../localDecks";
import { Icon } from "../icons";

type Mode = "login" | "register" | "reset";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [newRecovery, setNewRecovery] = useState<string | null>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);

  useEffect(() => { setUser(getUser()); }, []);

  async function submit() {
    setBusy(true); setErr(null); setNewRecovery(null);
    try {
      const action = mode;
      const r = await fetch("/api/auth", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, email, password, recovery_code: recovery }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      if (d.token && d.user) {
        setSession({ token: d.token, user: d.user });
        setUser(d.user);
        setPassword(""); setRecovery("");
        if (d.recovery_code) setNewRecovery(d.recovery_code);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  function logout() {
    const token = getToken();
    fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "logout", token }) }).catch(() => {});
    clearSession(); setUser(null); setNewRecovery(null); setImportMsg(null);
  }

  async function importLocal() {
    setImportMsg("Subiendo…");
    try {
      const r = await fetch("/api/cloud", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "push", code: effectiveCode(), token: getToken(),
          decks: listDecks(), binder: listBinder() }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setImportMsg(`Listo: ${listDecks().length} decks + binder en tu cuenta${d.capped ? " (recortado al tope)" : ""}.`);
    } catch (e) { setImportMsg("Error: " + (e instanceof Error ? e.message : String(e))); }
  }

  const inp = { background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", width: "100%" } as const;

  if (user) {
    return (
      <div className="wrap">
        <header><h1><Icon name="user" size={24} /> Tu cuenta</h1></header>
        <div className="card" style={{ maxWidth: 460 }}>
          <p>Sesión iniciada como <b>{user.email}</b>{user.is_admin ? " · admin" : ""}
            {user.is_supporter ? " · supporter (acceso ampliado)" : ""}.</p>
          {newRecovery && (
            <div className="alert" style={{ margin: "10px 0" }}>
              <b>Guardá tu código de recuperación</b> (se muestra una sola vez):<br />
              <code style={{ fontSize: "1.1rem" }}>{newRecovery}</code><br />
              <span className="muted" style={{ fontSize: ".8rem" }}>Sirve para recuperar tu cuenta si olvidás la contraseña. No lo compartas.</span>
            </div>
          )}
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button className="ghost" onClick={importLocal}>Importar mis decks locales</button>
            <button className="ghost" onClick={logout}>Cerrar sesión</button>
            {user.is_admin && <Link className="go" href="/admin" style={{ textDecoration: "none" }}>Panel admin</Link>}
          </div>
          {importMsg && <p className="muted" style={{ fontSize: ".82rem" }}>{importMsg}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="wrap">
      <header>
        <h1><Icon name="user" size={24} /> Ingresar / crear cuenta</h1>
        <p>Con cuenta, tus decks y binder quedan atados a vos (en cualquier dispositivo). Es opcional: sin cuenta seguís con el código anónimo.</p>
      </header>
      <div className="card" style={{ maxWidth: 460 }}>
        <div className="act-block" style={{ gap: 6 }}>
          <button className={mode === "login" ? "go" : "ghost"} onClick={() => setMode("login")}>Ingresar</button>
          <button className={mode === "register" ? "go" : "ghost"} onClick={() => setMode("register")}>Crear cuenta</button>
          <button className={mode === "reset" ? "go" : "ghost"} onClick={() => setMode("reset")}>Olvidé mi contraseña</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
          <label>Email<br /><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} style={inp} /></label>
          {mode === "reset" && (
            <label>Código de recuperación<br /><input value={recovery} onChange={(e) => setRecovery(e.target.value)} placeholder="XXXX-XXXX-XXXX" style={inp} /></label>
          )}
          <label>{mode === "reset" ? "Nueva contraseña" : "Contraseña"}<br />
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={inp} /></label>
          {mode === "register" && <span className="muted" style={{ fontSize: ".8rem" }}>Mínimo 8 caracteres. Al crear la cuenta te damos un código de recuperación: guardalo.</span>}
          <button className="go" onClick={submit} disabled={busy || !email || !password}>
            {busy ? "…" : mode === "login" ? "Ingresar" : mode === "register" ? "Crear cuenta" : "Restablecer"}
          </button>
          {err && <p className="err" role="alert">{err}</p>}
        </div>
        <p className="muted" style={{ fontSize: ".78rem", marginTop: 12 }}>
          Seguridad: contraseñas cifradas (pbkdf2). Sin verificación por email — la recuperación
          es por el código que te damos. <Link href="/">Volver</Link>
        </p>
      </div>
    </div>
  );
}
