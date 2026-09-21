"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { listDecks, type SavedDeck } from "../localDecks";
import { Seat, type PlayerState } from "../board";
import { download, fileStamp } from "../download";
import { Icon } from "../icons";

type RegDeck = { key: string; commander: string; identity: string[]; theme?: string };
type MatchSpec =
  | { kind: "registered"; key: string; name: string }
  | { kind: "custom"; name: string; text: string };
type Pickable = { id: string; label: string; tag: string; spec: MatchSpec; mine: boolean };
type Step = { turn: number; active: number; label: string; stack: string[]; players: PlayerState[] };
type KeyPlay = { turn: number; label: string; why?: string; delta?: number; step: number };
type MatchAnalysis = {
  win_type: string; summary: string;
  key_plays: KeyPlay[]; best_moves: KeyPlay[];
  mistakes: { player: string; note: string }[]; chain: KeyPlay[];
};
type Replay = { players: string[]; winner: string; turns: number; steps: Step[]; log?: string[]; analysis?: MatchAnalysis; images: Record<string, string> };
type Combo = { id: string; cards: string[]; produces: string[] };
type DeckAnalysis = {
  name: string;
  consistency?: { score: number; land_prob: number };
  strengths?: string[];
  weaknesses?: string[];
  combos?: { included: Combo[]; error: string | null };
  error?: string;
};

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
  const [ranDecks, setRanDecks] = useState<MatchSpec[]>([]);
  const [byTurn, setByTurn] = useState(false);
  const [analysis, setAnalysis] = useState<DeckAnalysis[] | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
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
      setReplay(d); setIdx(0); setRanDecks(decks); setAnalysis(null);
      // registrar la partida para el ranking global (best-effort, no bloquea)
      if (d.winner && d.winner !== "EMPATE") {
        fetch("/api/stats", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ winner: d.winner, commanders: d.players || [], turns: d.turns || 0 }),
        }).catch(() => {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  // relato en texto (usa el log del backend si viene; si no, de los steps)
  function relatoLines(): string[] {
    if (!replay) return [];
    if (replay.log && replay.log.length) return replay.log;
    return replay.steps.map((s) => `T${s.turn}  ${s.label}`);
  }
  function exportJSON() {
    if (!replay) return;
    download(`partida-${fileStamp()}.json`, JSON.stringify(replay, null, 2), "application/json");
  }
  function exportTxt() {
    if (!replay) return;
    const head = `Partida — ${replay.players.join(" vs ")}\nGanador: ${replay.winner || "sin definir"} · ${replay.turns} turnos\n\n`;
    download(`partida-${fileStamp()}.txt`, head + relatoLines().join("\n"), "text/plain");
  }

  // agrupa los pasos por turno + un conteo simple (aprox, por texto)
  function turnGroups() {
    const groups: { turn: number; steps: { i: number; label: string }[] }[] = [];
    (replay?.steps || []).forEach((s, i) => {
      let g = groups[groups.length - 1];
      if (!g || g.turn !== s.turn) { g = { turn: s.turn, steps: [] }; groups.push(g); }
      g.steps.push({ i, label: s.label });
    });
    return groups.map((g) => {
      const t = { lands: 0, casts: 0, deaths: 0 };
      for (const s of g.steps) {
        if (/juega tierra/i.test(s.label)) t.lands++;
        else if (/lanza/i.test(s.label)) t.casts++;
        if (/muere|cementerio|destru|pierde/i.test(s.label)) t.deaths++;
      }
      return { ...g, tally: t };
    });
  }

  async function analyzeDecks() {
    const customs = ranDecks.filter((d) => d.kind === "custom") as Extract<MatchSpec, { kind: "custom" }>[];
    setAnalyzing(true);
    try {
      const out: DeckAnalysis[] = [];
      for (const d of customs) {
        try {
          const r = await fetch("/api/analyze", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: d.text, commander: null }),
          });
          const j = await r.json();
          if (j.error) out.push({ name: d.name, error: j.error });
          else out.push({ name: d.name, consistency: j.consistency, strengths: j.strengths, weaknesses: j.weaknesses, combos: j.combos });
        } catch (e) {
          out.push({ name: d.name, error: e instanceof Error ? e.message : String(e) });
        }
      }
      setAnalysis(out);
    } finally { setAnalyzing(false); }
  }

  const step = replay?.steps[idx];
  const last = replay ? replay.steps.length - 1 : 0;
  const customCount = ranDecks.filter((d) => d.kind === "custom").length;
  const exampleCount = ranDecks.length - customCount;

  return (
    <div className="wrap">
      <header>
        <h1><Icon name="film" size={26} /> Ver una partida</h1>
        <p>Elegí de 2 a 6 decks y mirá la partida completa, turno a turno, como si estuvieras en la mesa.</p>
      </header>

      <div className="card">
        <h2><span className="step">1</span> Elegí los decks ({selected.length}/6)</h2>
        <div className="decks">
          {pickables.map((p) => (
            <button key={p.id} className={`deck-btn ${selected.includes(p.id) ? "on" : ""}`} onClick={() => toggle(p.id)}>
              <div className="name">{p.mine ? <Icon name="star" size={13} /> : null}{p.mine ? " " : ""}{p.label}</div>
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
        {error && <p className="err" role="alert"><Icon name="warning" size={15} /> {error}</p>}
      </div>

      {replay && step && (
        <div className="card">
          <div className="scrub">
            <button className="ghost" aria-label="Ir al inicio" title="Inicio" onClick={() => { setPlaying(false); setIdx(0); }} disabled={idx === 0}><Icon name="skip-back" size={16} /></button>
            <button className="ghost" aria-label="Anterior" title="Anterior" onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }} disabled={idx === 0}><Icon name="chevron-left" size={16} /></button>
            <button className="go" onClick={() => setPlaying((v) => !v)} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>{playing ? <><Icon name="pause" size={15} /> Pausa</> : <><Icon name="play" size={15} /> Reproducir</>}</button>
            <button className="ghost" aria-label="Siguiente" title="Siguiente" onClick={() => { setPlaying(false); setIdx((i) => Math.min(last, i + 1)); }} disabled={idx === last}><Icon name="chevron-right" size={16} /></button>
            <button className="ghost" aria-label="Ir al final" title="Final" onClick={() => { setPlaying(false); setIdx(last); }} disabled={idx === last}><Icon name="skip-forward" size={16} /></button>
            <input type="range" aria-label="Posición de la repetición" min={0} max={last} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="range" />
            <span className="muted">{idx + 1}/{last + 1}</span>
          </div>
          <div className="now">
            <motion.span
              key={step.turn}
              className="turnbadge"
              initial={reduce ? false : { scale: 0.8, opacity: 0.4 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: "spring", stiffness: 400, damping: 24 }}
            >
              Turno {step.turn}
            </motion.span>
            <motion.span
              key={"who" + step.active}
              className="label"
              initial={reduce ? false : { opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3 }}
            >
              Juega <b>{step.players[step.active]?.name}</b>
            </motion.span>
          </div>
          <p className="muted" style={{ margin: "2px 0 8px", fontSize: ".85rem" }}>{step.label}</p>
          {step.stack.length > 0 && <p className="muted">Pila: {step.stack.join(" → ")}</p>}

          <div className="stage">
            {step.players.map((p, i) => (
              <Seat
                key={p.name} p={p} active={i === step.active} art={replay.images} reduce={reduce}
                variant={i === step.active ? "hero" : "mini"}
              />
            ))}
          </div>

          {idx === last && (
            <p className="win-line"><Icon name="trophy" size={18} /> Gana <b>{replay.winner}</b> en {replay.turns} turnos.</p>
          )}

          <div className="act-block" style={{ marginTop: 10 }}>
            <span className="act-label">Descargar:</span>
            <button className="ghost" onClick={exportJSON} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><Icon name="download" size={14} /> JSON (datos)</button>
            <button className="ghost" onClick={exportTxt} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><Icon name="download" size={14} /> Texto (relato)</button>
          </div>

          <details className="legend">
            <summary>¿Qué significa cada símbolo?</summary>
            <div className="legend-grid">
              <span><Icon name="play" size={12} /> jugador en turno</span>
              <span><Icon name="heart-fill" size={13} /> vida (roja si ≤ 10)</span>
              <span><Icon name="hand" size={13} /> cartas en mano</span>
              <span><Icon name="library" size={13} /> cartas en biblioteca</span>
              <span><Icon name="grave" size={13} /> cartas en cementerio</span>
              <span><Icon name="crown" size={13} /> comandante</span>
              <span><b className="k-cmdr"><Icon name="sword" size={13} /> N/21</b> = daño de comandante (21 elimina)</span>
              <span><b className="k-cmdr"><Icon name="poison" size={13} /> N/10</b> = veneno (10 elimina)</span>
              <span><Icon name="skull" size={13} /> eliminado (por vida, daño de comandante o veneno)</span>
              <span>carta rotada = tapeada (girada)</span>
              <span><b className="k-atk">borde rojo</b> = atacando</span>
              <span><b className="k-pt">2/3</b> = fuerza/resistencia</span>
              <span><b className="k-dmg">−N</b> = daño recibido este turno</span>
              <span><b className="k-cnt">+N</b> = contadores +1/+1</span>
              <span>ficha de color = carta sin arte (casera)</span>
            </div>
          </details>
        </div>
      )}

      {replay?.analysis && (
        <div className="card">
          <h2><Icon name="brain" size={20} /> Análisis de la partida</h2>
          <p style={{ marginTop: -4 }}>
            <span className="chip" style={{ marginRight: 8 }}>{replay.analysis.win_type}</span>
            {replay.analysis.summary}
          </p>
          <p className="muted" style={{ fontSize: ".8rem" }}>
            Una lectura rápida de qué inclinó la partida. Tocá cualquier jugada para saltar el tablero a ese momento.
          </p>
          <div className="row" style={{ gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div style={{ flex: "1 1 260px" }}>
              <h3 style={{ fontSize: ".95rem" }}>Jugadas clave</h3>
              {replay.analysis.key_plays.length === 0 && <p className="muted">—</p>}
              {replay.analysis.key_plays.map((k, i) => (
                <button key={i} className="play-line" onClick={() => { setPlaying(false); setIdx(k.step); }}>
                  <span className="pl-turn">T{k.turn}</span> {k.label}
                  {k.why ? <span className="muted"> · {k.why}</span> : null}
                </button>
              ))}
            </div>
            <div style={{ flex: "1 1 260px" }}>
              <h3 style={{ fontSize: ".95rem", color: "#7ad17a" }}>Las mejores jugadas de {replay.winner}</h3>
              {replay.analysis.best_moves.length === 0 && <p className="muted">—</p>}
              {replay.analysis.best_moves.map((k, i) => (
                <button key={i} className="play-line" onClick={() => { setPlaying(false); setIdx(k.step); }}>
                  <span className="pl-turn">T{k.turn}</span> {k.label}
                  {typeof k.delta === "number" ? <span className="muted"> · +{k.delta}</span> : null}
                </button>
              ))}
            </div>
          </div>
          {replay.analysis.mistakes.length > 0 && (
            <>
              <h3 style={{ fontSize: ".95rem", color: "#e0a35a" }}>Errores / puntos flojos</h3>
              <ul className="abil">
                {replay.analysis.mistakes.map((m, i) => <li key={i}><b>{m.player}</b>: {m.note}</li>)}
              </ul>
            </>
          )}
          {replay.analysis.chain.length > 0 && (
            <>
              <h3 style={{ fontSize: ".95rem" }}>Cómo se encadenó la victoria</h3>
              <div className="plays" style={{ maxHeight: 200 }}>
                {replay.analysis.chain.map((k, i) => (
                  <button key={i} className="play-line" onClick={() => { setPlaying(false); setIdx(k.step); }}>
                    <span className="pl-turn">T{k.turn}</span> {k.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {replay && (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}><Icon name="scroll" size={20} /> Jugadas</h2>
            <label className="muted" style={{ fontSize: ".85rem" }}>
              <input type="checkbox" checked={byTurn} onChange={(e) => setByTurn(e.target.checked)} />{" "}
              agrupar por turno
            </label>
          </div>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Tocá una jugada para saltar el tablero a ese momento.
          </p>
          <div className="plays">
            {!byTurn && replay.steps.map((s, i) => (
              <button key={i} className={`play-line${i === idx ? " on" : ""}`}
                onClick={() => { setPlaying(false); setIdx(i); }}>
                <span className="pl-turn">T{s.turn}</span> {s.label}
              </button>
            ))}
            {byTurn && turnGroups().map((g) => (
              <div key={g.turn} className="turn-group">
                <div className="turn-head">
                  Turno {g.turn}
                  <span className="muted"> · {g.tally.lands} tierras · {g.tally.casts} hechizos{g.tally.deaths ? ` · ${g.tally.deaths} bajas` : ""}</span>
                </div>
                {g.steps.map((s) => (
                  <button key={s.i} className={`play-line${s.i === idx ? " on" : ""}`}
                    onClick={() => { setPlaying(false); setIdx(s.i); }}>
                    {s.label}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {replay && (
        <div className="card">
          <h2><Icon name="flask" size={20} /> Análisis de los mazos</h2>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Fortalezas, debilidades, qué tan consistente es cada mazo y los combos que
            <b> podrían</b> armar (según Commander Spellbook). Ojo: son los combos posibles,
            no necesariamente los que pasaron en esta partida — para eso mirá el relato de arriba.
          </p>
          {customCount === 0 ? (
            <p className="muted">
              Esta partida usó solo decks de ejemplo, que ya vienen armados y no se analizan.
              Cargá los tuyos en el <Link href="/deck">editor</Link> para verlos en detalle.
            </p>
          ) : (
            <>
              <button className="go" disabled={analyzing} onClick={analyzeDecks}>
                {analyzing ? "Analizando…" : `Analizar los mazos (${customCount})`}
              </button>
              {exampleCount > 0 && (
                <p className="muted" style={{ fontSize: ".8rem" }}>
                  ({exampleCount} deck(s) de ejemplo no se analizan.)
                </p>
              )}
              {analysis && analysis.map((a, k) => (
                <div key={k} className="combo" style={{ marginTop: 12 }}>
                  <div><b>{a.name}</b>{a.consistency ? <span className="muted"> · consistencia {a.consistency.score}/100</span> : null}</div>
                  {a.error ? (
                    <p className="muted">No se pudo analizar: {a.error}</p>
                  ) : (
                    <div className="row" style={{ gap: 20, flexWrap: "wrap", alignItems: "flex-start" }}>
                      <div style={{ flex: "1 1 220px" }}>
                        <div style={{ color: "#7ad17a", fontSize: ".85rem" }}>Fortalezas</div>
                        <ul className="abil">{(a.strengths || []).slice(0, 3).map((s, i) => <li key={i}>{s}</li>)}</ul>
                      </div>
                      <div style={{ flex: "1 1 220px" }}>
                        <div style={{ color: "#e0a35a", fontSize: ".85rem" }}>Debilidades</div>
                        <ul className="abil">{(a.weaknesses || []).slice(0, 3).map((w, i) => <li key={i}>{w}</li>)}</ul>
                      </div>
                      <div style={{ flex: "1 1 220px" }}>
                        <div style={{ fontSize: ".85rem" }}>Combos posibles</div>
                        {a.combos?.error ? <p className="muted" style={{ fontSize: ".8rem" }}>no disponibles</p>
                          : (a.combos?.included || []).length === 0 ? <p className="muted" style={{ fontSize: ".8rem" }}>ninguno detectado</p>
                          : (a.combos!.included).slice(0, 4).map((c) => (
                            <div key={c.id} style={{ fontSize: ".82rem" }}>{c.cards.join(" + ")}</div>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      <footer>
        La partida la juega el sistema, en la dificultad que elijas. Las cartas reales van
        con su ilustración; las de ejemplo usan una ficha simple.
        Para ver tus decks con arte, cargalos y guardalos en el <Link href="/deck">editor</Link>.
      </footer>
    </div>
  );
}
