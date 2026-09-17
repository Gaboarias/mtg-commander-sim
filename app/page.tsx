"use client";

import { useEffect, useState } from "react";

type Deck = { key: string; commander: string; identity: string[] };
type Cov = { deck: string; implemented: number; vanilla: number };
type SimResult = { deck: string; wins: number; pct: number };

function Pips({ ids }: { ids: string[] }) {
  return (
    <>
      {ids.map((c) => (
        <span key={c} className={`pip ${c}`}>
          {c}
        </span>
      ))}
    </>
  );
}

export default function Home() {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [coverage, setCoverage] = useState<Cov[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [n, setN] = useState(200);
  const [seed, setSeed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [sim, setSim] = useState<{ n: number; results: SimResult[] } | null>(null);
  const [log, setLog] = useState<{ winner: string; turns: number; log: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/catalog")
      .then((r) => r.json())
      .then((d) => {
        setDecks(d.decks || []);
        setCoverage(d.coverage || []);
        setSelected((d.decks || []).slice(0, 2).map((x: Deck) => x.key));
      })
      .catch(() => setError("No se pudo cargar el catalogo de mazos."));
  }, []);

  function toggle(key: string) {
    setSelected((s) =>
      s.includes(key) ? s.filter((k) => k !== key) : s.length < 4 ? [...s, key] : s
    );
  }

  async function runSim() {
    if (selected.length < 2) return;
    setBusy(true);
    setError(null);
    setLog(null);
    try {
      const r = await fetch(`/api/simulate?matchup=${selected.join(",")}&n=${n}`);
      const d = await r.json();
      if (d.error) setError(d.error);
      else setSim(d);
    } catch {
      setError("Error al simular.");
    } finally {
      setBusy(false);
    }
  }

  async function runLog() {
    if (selected.length < 2) return;
    setBusy(true);
    setError(null);
    setSim(null);
    try {
      const r = await fetch(
        `/api/simulate?matchup=${selected.join(",")}&log=1&seed=${seed}`
      );
      const d = await r.json();
      if (d.error) setError(d.error);
      else setLog(d);
    } catch {
      setError("Error al generar la partida.");
    } finally {
      setBusy(false);
    }
  }

  const maxPct = sim ? Math.max(...sim.results.map((r) => r.pct), 1) : 1;

  return (
    <div className="wrap">
      <header>
        <h1>🎴 MTG Commander Sim</h1>
        <p>
          Motor de simulacion de <strong>Magic: The Gathering</strong> (formato
          Commander) en Python puro. Elegi 2 a 4 mazos, corre miles de partidas y
          medi la tasa de victoria — o mira una partida turno a turno.
        </p>
      </header>

      <div className="card">
        <h2>1 · Elegi los mazos ({selected.length}/4)</h2>
        <div className="decks">
          {decks.map((d) => (
            <button
              key={d.key}
              className={`deck-btn ${selected.includes(d.key) ? "on" : ""}`}
              onClick={() => toggle(d.key)}
            >
              <div className="name">{d.key}</div>
              <div className="sub">
                <Pips ids={d.identity} /> {d.commander}
              </div>
            </button>
          ))}
          {decks.length === 0 && !error && <span className="muted">Cargando…</span>}
        </div>
      </div>

      <div className="card">
        <h2>2 · Simular</h2>
        <div className="row">
          <label>
            Partidas&nbsp;
            <input
              type="number"
              min={1}
              max={2000}
              value={n}
              onChange={(e) => setN(Number(e.target.value))}
            />
          </label>
          <button className="go" onClick={runSim} disabled={busy || selected.length < 2}>
            {busy ? "Corriendo…" : "Correr simulacion"}
          </button>
          <label>
            Semilla&nbsp;
            <input
              type="number"
              min={0}
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </label>
          <button className="ghost" onClick={runLog} disabled={busy || selected.length < 2}>
            Ver una partida
          </button>
        </div>
        {selected.length < 2 && <p className="muted">Elegi al menos 2 mazos.</p>}
        {error && <p className="err">⚠ {error}</p>}
      </div>

      {sim && (
        <div className="card">
          <h2>Resultados · {sim.n} partidas</h2>
          {sim.results.map((r) => (
            <div className="bar-row" key={r.deck}>
              <div className="bar-head">
                <span className="deck">{r.deck}</span>
                <span>
                  {r.pct}% <span className="muted">({r.wins})</span>
                </span>
              </div>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(r.pct / maxPct) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {log && (
        <div className="card">
          <h2>
            Partida (semilla {seed}) · Gana <span className="win">{log.winner}</span> en{" "}
            {log.turns} turnos
          </h2>
          <div className="log">{log.log.join("\n")}</div>
        </div>
      )}

      {coverage.length > 0 && (
        <div className="card">
          <h2>Cobertura de cartas</h2>
          <p className="muted">
            Cuantas cartas de cada mazo tienen efecto implementado vs. vainilla.
          </p>
          <table>
            <thead>
              <tr>
                <th>Mazo</th>
                <th>Con efecto</th>
                <th>Vainilla</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map((c) => (
                <tr key={c.deck}>
                  <td style={{ textTransform: "capitalize" }}>{c.deck}</td>
                  <td>{c.implemented}</td>
                  <td>{c.vanilla}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer>
        Motor en Python puro (sin dependencias) · API serverless en Vercel ·
        interfaz Next.js. El codigo del motor vive en <code>engine.py</code>,{" "}
        <code>cards.py</code>, <code>decks.py</code>, <code>policy.py</code>. Ver{" "}
        <code>ADDING_CARDS.md</code> para agregar cartas.
      </footer>
    </div>
  );
}
