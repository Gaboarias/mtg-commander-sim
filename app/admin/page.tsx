"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getUser, getToken } from "../auth";

type Stats = {
  counts: Record<string, number>;
  top: { commander: string; games: number; wins: number; pct: number }[];
  recent_matches: { winner: string; turns: number; created_at: number }[];
  recent_users: { email: string; is_admin: number; is_supporter: number; created_at: number }[];
};

export default function AdminPage() {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u || !u.is_admin) { setIsAdmin(false); return; }
    setIsAdmin(true);
    fetch("/api/admin", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "stats", token: getToken() }),
    }).then((r) => r.json()).then((d) => {
      if (d.error) setErr(d.error); else setStats(d as Stats);
    }).catch((e) => setErr(String(e)));
  }, []);

  if (isAdmin === false) {
    return (
      <div className="wrap">
        <header><h1>🔒 Admin</h1></header>
        <div className="card"><p>Esta sección es solo para el admin. <Link href="/login">Ingresar</Link>.</p></div>
      </div>
    );
  }

  const fmt = (t: number) => t ? new Date(t * 1000).toLocaleDateString() : "";
  const CARDS: [string, string][] = [
    ["users", "Usuarios"], ["supporters", "Supporters"], ["decks", "Decks en la nube"],
    ["shares", "Decks compartidos"], ["matches", "Partidas registradas"],
  ];

  return (
    <div className="wrap">
      <header><h1>📊 Panel admin</h1><p>Métricas globales del sitio.</p></header>
      {err && <div className="card"><p className="err">{err}</p></div>}
      {stats && (
        <>
          <div className="card">
            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              {CARDS.map(([k, label]) => (
                <div key={k} style={{ minWidth: 120 }}>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: "1.9rem", fontWeight: 700, color: "var(--accent)" }}>
                    {stats.counts[k] ?? 0}
                  </div>
                  <div className="muted" style={{ fontSize: ".82rem" }}>{label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h2>Top comandantes</h2>
            {stats.top.length === 0 ? <p className="muted">Sin partidas aún.</p> : stats.top.map((r) => (
              <div key={r.commander} className="bar-row" style={{ display: "flex", alignItems: "center", gap: 10, margin: "4px 0" }}>
                <span style={{ width: 180 }}>{r.commander}</span>
                <span className="bar-track" style={{ flex: 1 }}><span className="bar-fill" style={{ display: "block", height: "100%", width: `${r.pct}%` }} /></span>
                <span className="muted" style={{ width: 90, textAlign: "right" }}>{r.pct}% ({r.wins}/{r.games})</span>
              </div>
            ))}
          </div>

          <div className="card">
            <h2>Últimos usuarios</h2>
            {stats.recent_users.length === 0 ? <p className="muted">—</p> : (
              <ul className="abil">
                {stats.recent_users.map((u, i) => (
                  <li key={i}>{u.email}{u.is_admin ? " · admin" : ""}{u.is_supporter ? " · supporter" : ""} <span className="muted">({fmt(u.created_at)})</span></li>
                ))}
              </ul>
            )}
            <h2 style={{ marginTop: 14 }}>Últimas partidas</h2>
            {stats.recent_matches.length === 0 ? <p className="muted">—</p> : (
              <ul className="abil">
                {stats.recent_matches.map((m, i) => (
                  <li key={i}>Ganó <b>{m.winner}</b> en {m.turns} turnos <span className="muted">({fmt(m.created_at)})</span></li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
      {!stats && !err && <div className="card"><p className="muted">Cargando…</p></div>}
    </div>
  );
}
