"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { listDecks, type SavedDeck } from "./localDecks";

const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];

type RegDeck = { key: string; commander: string; identity: string[] };
type MatchSpec =
  | { kind: "registered"; key: string; name: string }
  | { kind: "custom"; name: string; text: string };
type Pickable = { id: string; label: string; tag: string; colors: string[]; spec: MatchSpec; mine: boolean };
type Res = { deck: string; wins: number; pct: number };

function Pips({ ids }: { ids: string[] }) {
  if (!ids || ids.length === 0) return null;
  return (
    <>
      {ids.map((c) => (
        <span key={c} className={`pip pip-${c}`}>{c}</span>
      ))}
    </>
  );
}

export default function Home() {
  const [pickables, setPickables] = useState<Pickable[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [n, setN] = useState(120);
  const [level, setLevel] = useState("intermedio");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ players: number; n: number; results: Res[] } | null>(null);
  const [log, setLog] = useState<{ winner: string; turns: number; log: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mineCount, setMineCount] = useState(0);

  useEffect(() => {
    const mine: Pickable[] = listDecks().map((d: SavedDeck) => ({
      id: "mine:" + d.id,
      label: d.name,
      tag: "mi deck",
      colors: d.colors || [],
      spec: { kind: "custom", name: d.name, text: d.text },
      mine: true,
    }));
    setMineCount(mine.length);
    fetch("/api/catalog")
      .then((r) => r.json())
      .then((d) => {
        const examples: Pickable[] = (d.decks || []).map((x: RegDeck) => ({
          id: "reg:" + x.key,
          label: x.commander,
          tag: "ejemplo",
          colors: x.identity || [],
          spec: { kind: "registered", key: x.key, name: x.commander },
          mine: false,
        }));
        const all = [...mine, ...examples];
        setPickables(all);
        // preseleccionar: mis decks primero, o los primeros ejemplos
        const pre = (mine.length >= 2 ? mine : all).slice(0, Math.max(2, Math.min(2, all.length)));
        setSelected(pre.map((p) => p.id));
      })
      .catch(() => {
        setPickables(mine);
        setSelected(mine.slice(0, 2).map((p) => p.id));
      });
  }, []);

  function toggle(id: string) {
    setSelected((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : s.length < 6 ? [...s, id] : s
    );
  }

  function selectedSpecs(): MatchSpec[] {
    return selected
      .map((id) => pickables.find((p) => p.id === id)?.spec)
      .filter(Boolean) as MatchSpec[];
  }

  async function run(logMode: boolean) {
    const decks = selectedSpecs();
    if (decks.length < 2) {
      setError("Elegí al menos 2 decks.");
      return;
    }
    setBusy(true);
    setError(null);
    if (logMode) setResult(null);
    else setLog(null);
    try {
      const r = await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(logMode ? { decks, level, log: true } : { decks, n, level }),
      });
      const raw = await r.text();
      let d;
      try {
        d = JSON.parse(raw);
      } catch {
        throw new Error(`HTTP ${r.status}: ${raw.slice(0, 200)}`);
      }
      if (d.error) throw new Error(d.error);
      if (logMode) setLog(d);
      else setResult(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const reduce = useReducedMotion();
  const maxPct = result ? Math.max(...result.results.map((r) => r.pct), 1) : 1;

  // color por identidad del deck (orden de seleccion), no por ranking
  const colorOf = (deck: string): string => {
    if (deck === "sin definir") return "var(--s-none)";
    const specs = selectedSpecs();
    const i = specs.findIndex((s) => s.name === deck);
    return `var(${SERIES[(i >= 0 ? i : 0) % SERIES.length]})`;
  };

  return (
    <div className="wrap">
      <header>
        <h1>🎴 Simulador de partidas</h1>
        <p>
          Elegí de 2 a 6 decks y mirá cuánto gana cada uno en muchas partidas.
          Creá y guardá tus decks en el <Link href="/deck">editor de decks →</Link>.
        </p>
      </header>

      <div className="card">
        <h2>1 · Elegí los decks ({selected.length}/6)</h2>
        {mineCount === 0 && (
          <p className="muted">
            Todavía no guardaste decks. Podés usar los de ejemplo, o crear el tuyo
            en el <Link href="/deck">editor</Link>.
          </p>
        )}
        <div className="decks">
          {pickables.map((p) => (
            <button
              key={p.id}
              className={`deck-btn ${selected.includes(p.id) ? "on" : ""}`}
              onClick={() => toggle(p.id)}
            >
              <div className="name">
                {p.mine ? "★ " : ""}
                {p.label}
              </div>
              <div className="sub">
                <Pips ids={p.colors} /> {p.tag}
              </div>
            </button>
          ))}
          {pickables.length === 0 && <span className="muted">Cargando…</span>}
        </div>
      </div>

      <div className="card">
        <h2>2 · Jugar</h2>
        <div className="row">
          <label>
            Nivel de la IA&nbsp;
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              style={{
                background: "var(--panel-2)", color: "var(--text)",
                border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px",
              }}
            >
              <option value="novato">Novato</option>
              <option value="intermedio">Intermedio</option>
              <option value="avanzado">Avanzado</option>
            </select>
          </label>
          <label>
            Partidas a simular&nbsp;
            <input
              type="number"
              min={1}
              max={500}
              value={n}
              onChange={(e) => setN(Number(e.target.value))}
            />
          </label>
          <button className="go" onClick={() => run(false)} disabled={busy || selected.length < 2}>
            {busy ? "Jugando…" : "Simular la mesa"}
          </button>
          <button className="ghost" onClick={() => run(true)} disabled={busy || selected.length < 2}>
            Ver una partida
          </button>
        </div>
        {error && <p className="err">⚠ {error}</p>}
      </div>

      {result && (
        <motion.div
          className="card"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={reduce ? { duration: 0 } : { duration: 0.3 }}
        >
          <h2>
            Resultados · {result.players} decks · {result.n} partidas · IA {level}
          </h2>
          {result.results.map((r, i) => (
            <div className="bar-row" key={r.deck}>
              <div className="bar-head">
                <span className="deck">
                  <span className="swatch" style={{ background: colorOf(r.deck) }} />
                  {r.deck}
                </span>
                <span className="pct">
                  {r.pct}% <span className="muted">({r.wins})</span>
                </span>
              </div>
              <div className="bar-track">
                <motion.div
                  className="bar-fill"
                  style={{ background: colorOf(r.deck) }}
                  initial={{ width: 0 }}
                  animate={{ width: `${(r.pct / maxPct) * 100}%` }}
                  transition={reduce ? { duration: 0 } : { duration: 0.6, delay: i * 0.06, ease: "easeOut" }}
                />
              </div>
            </div>
          ))}
          <p className="muted" style={{ marginTop: 8 }}>
            «sin definir» = partidas que llegaron al límite sin un ganador claro.
          </p>
        </motion.div>
      )}

      {log && (
        <div className="card">
          <h2>
            Una partida · gana <span className="win">{log.winner}</span> en {log.turns} turnos
          </h2>
          <div className="log">{log.log.join("\n")}</div>
        </div>
      )}

      <footer>
        Los resultados son estimaciones de muchas partidas jugadas por una IA
        simple. Las cartas con efecto programado usan su habilidad; el resto se
        juega con sus datos reales (coste, fuerza, resistencia).
      </footer>
    </div>
  );
}
