"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useReducedMotion } from "framer-motion";
import { listDecks, type SavedDeck } from "../localDecks";
import { Seat, type PlayerState } from "../board";

type RegDeck = { key: string; commander: string; identity: string[]; theme?: string };
type MatchSpec =
  | { kind: "registered"; key: string; name: string }
  | { kind: "custom"; name: string; text: string };
type Pickable = { id: string; label: string; tag: string; spec: MatchSpec; mine: boolean };
type Step = { turn: number; active: number; label: string; stack: string[]; players: PlayerState[] };
type Replay = { players: string[]; winner: string; turns: number; steps: Step[]; images: Record<string, string> };

export default function Watch() {
  const [pickables, setPickables] = useState<Pickable[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [seed, setSeed] = useState(1);
  const [level, setLevel] = useState("intermedio");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const reduce = useReducedMotion() ?? false;

  useEffect(() => {
    const mine: Pickable[] = listDecks().map((d: SavedDeck) => ({
      id: "mine:" + d.id, label: d.name, tag: "mi deck",
      spec: { kind: "custom", name: d.name, text: d.text }, mine: true,
    }));
    fetch("/api/catalog")
      .then((r) => r.json())
      .then((d) => {
        const examples: Pickable[] = (d.decks || []).map((x: RegDeck) => ({
          id: "reg:" + x.key, label: x.commander, tag: x.theme || "ejemplo",
          spec: { kind: "registered", key: x.key, name: x.commander }, mine: false,
        }));
        const all = [...mine, ...examples];
        setPickables(all);
        setSelected(all.slice(0, 2).map((p) => p.id));
      })
      .catch(() => { setPickables(mine); setSelected(mine.slice(0, 2).map((p) => p.id)); });
  }, []);

  // auto-avance al reproducir
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!playing || !replay) return;
    timer.current = setInterval(() => {
      setIdx((i) => {
        if (i >= replay.steps.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, 900);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, replay]);

  function toggle(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length < 6 ? [...s, id] : s));
  }

  async function run() {
    const decks = selected.map((id) => pickables.find((p) => p.id === id)?.spec).filter(Boolean) as MatchSpec[];
    if (decks.length < 2) { setError("Elegí al menos 2 decks."); return; }
    setBusy(true); setError(null); setPlaying(false);
    try {
      const r = await fetch("/api/replay", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decks, seed, level }),
      });
      const raw = await r.text();
      let d;
      try { d = JSON.parse(raw); } catch { throw new Error(`HTTP ${r.status}: ${raw.slice(0, 200)}`); }
      if (d.error) throw new Error(d.error);
      setReplay(d); setIdx(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const step = replay?.steps[idx];
  const last = replay ? replay.steps.length - 1 : 0;

  return (
    <div className="wrap">
      <header>
        <h1>🎬 Ver una partida</h1>
        <p>Elegí de 2 a 6 decks y mirá cómo el sistema juega la mesa, turno a turno.</p>
      </header>

      <div className="card">
        <h2><span className="step">1</span> Elegí los decks ({selected.length}/6)</h2>
        <div className="decks">
          {pickables.map((p) => (
            <button key={p.id} className={`deck-btn ${selected.includes(p.id) ? "on" : ""}`} onClick={() => toggle(p.id)}>
              <div className="name">{p.mine ? "★ " : ""}{p.label}</div>
              <div className="sub">{p.tag}</div>
            </button>
          ))}
          {pickables.length === 0 && <span className="muted">Cargando…</span>}
        </div>
      </div>

      <div className="card">
        <h2><span className="step">2</span> Reproducir</h2>
        <div className="row">
          <label>Dificultad&nbsp;
            <select value={level} onChange={(e) => setLevel(e.target.value)}
              style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
              <option value="novato">Novato</option>
              <option value="intermedio">Intermedio</option>
              <option value="avanzado">Avanzado</option>
            </select>
          </label>
          <label>Semilla&nbsp;
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} style={{ width: 90 }} />
          </label>
          <button className="go" onClick={run} disabled={busy || selected.length < 2}>
            {busy ? "Jugando…" : "Ver repetición"}
          </button>
        </div>
        {error && <p className="err">⚠ {error}</p>}
      </div>

      {replay && step && (
        <div className="card">
          <div className="scrub">
            <button className="ghost" onClick={() => { setPlaying(false); setIdx(0); }} disabled={idx === 0}>⏮</button>
            <button className="ghost" onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }} disabled={idx === 0}>◀</button>
            <button className="go" onClick={() => setPlaying((v) => !v)}>{playing ? "⏸ Pausa" : "▶ Reproducir"}</button>
            <button className="ghost" onClick={() => { setPlaying(false); setIdx((i) => Math.min(last, i + 1)); }} disabled={idx === last}>▶</button>
            <button className="ghost" onClick={() => { setPlaying(false); setIdx(last); }} disabled={idx === last}>⏭</button>
            <input type="range" min={0} max={last} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="range" />
            <span className="muted">{idx + 1}/{last + 1}</span>
          </div>
          <div className="now">
            <span className="turnbadge">Turno {step.turn}</span>
            <span className="label">{step.label}</span>
          </div>
          {step.stack.length > 0 && <p className="muted">Pila: {step.stack.join(" → ")}</p>}

          <div className="seats" data-n={step.players.length}>
            {step.players.map((p, i) => (
              <Seat key={p.name} p={p} active={i === step.active} art={replay.images} reduce={reduce} />
            ))}
          </div>

          {idx === last && (
            <p className="win-line">🏆 Gana <b>{replay.winner}</b> en {replay.turns} turnos.</p>
          )}

          <details className="legend">
            <summary>¿Qué significa cada cosa? (nomenclatura)</summary>
            <div className="legend-grid">
              <span>▶ jugador en turno</span>
              <span>♥ vida (roja si ≤ 10)</span>
              <span>✋ cartas en mano</span>
              <span>📚 cartas en biblioteca</span>
              <span>⚰ cartas en cementerio</span>
              <span>👑 comandante</span>
              <span><b className="k-cmdr">🗡 N/21</b> = daño de comandante (21 elimina)</span>
              <span><b className="k-cmdr">☣ N/10</b> = veneno (10 elimina)</span>
              <span>☠ eliminado (por vida, daño de comandante o veneno)</span>
              <span>🂠 carta rotada = tapeada (girada)</span>
              <span><b className="k-atk">borde rojo</b> = atacando</span>
              <span><b className="k-pt">2/3</b> = fuerza/resistencia</span>
              <span><b className="k-dmg">−N</b> = daño recibido este turno</span>
              <span><b className="k-cnt">+N</b> = contadores +1/+1</span>
              <span>ficha de color = carta sin arte (casera)</span>
            </div>
          </details>
        </div>
      )}

      <footer>
        La partida la juega el sistema (dificultad elegida). Las cartas con arte real vienen
        de Scryfall; las cartas de ejemplo caseras usan una ficha simple.
        Para ver decks reales con arte, importalos en el <Link href="/deck">editor</Link> y guardalos.
      </footer>
    </div>
  );
}
