"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { Seat, type PlayerState } from "../board";

const PY_VERSION = "0.26.4";
const PY_BASE = `https://cdn.jsdelivr.net/pyodide/v${PY_VERSION}/full/`;

type RegDeck = { key: string; commander: string; identity: string[]; theme?: string };
type Legal = {
  lands: { i: number; name: string }[];
  casts: { i?: number; name: string; zone: string; cost: string; tax?: number }[];
  attackers: { uid: number; name: string; power: number; toughness: number }[];
  can_attack: boolean; can_end: boolean;
};
type GameState = {
  turn: number; active: number; human_index: number; phase: string; attacked: boolean;
  winner: string | null; players: PlayerState[]; legal: Legal; log: string[];
};

/* eslint-disable @typescript-eslint/no-explicit-any */
function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.onload = () => resolve(); s.onerror = () => reject(new Error("no se pudo cargar " + src));
    document.head.appendChild(s);
  });
}

const BOOTSTRAP = `
import sys, json
sys.path.insert(0, '.')
import interactive
_IG = {'g': None}
def new_game(specs_json, seed, level):
    _IG['g'] = interactive.from_registered(json.loads(specs_json), 0, int(seed), level)
    return json.dumps(_IG['g'].state())
def act(kind, arg_json):
    g = _IG['g']; a = json.loads(arg_json or '{}')
    if kind == 'land': g.play_land(a['i'])
    elif kind == 'cast': g.cast(a.get('i'), a.get('zone', 'hand'))
    elif kind == 'attack': g.attack(a.get('uids', []))
    elif kind == 'end': g.end_turn()
    return json.dumps(g.state())
`;

export default function Play() {
  const reduce = useReducedMotion() ?? false;
  const [decks, setDecks] = useState<RegDeck[]>([]);
  const [mine, setMine] = useState<string>("");
  const [foes, setFoes] = useState<string[]>([]);
  const [level, setLevel] = useState("intermedio");
  const [seed, setSeed] = useState(1);

  const pyRef = useRef<any>(null);
  const [status, setStatus] = useState<string>("");   // texto de carga
  const [booting, setBooting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());  // atacantes elegidos

  useEffect(() => {
    fetch("/api/catalog").then((r) => r.json()).then((d) => {
      const list: RegDeck[] = d.decks || [];
      setDecks(list);
      if (list[0]) setMine(list[0].key);
      if (list[1]) setFoes([list[1].key]);
    }).catch(() => {});
  }, []);

  async function ensurePyodide() {
    if (pyRef.current) return pyRef.current;
    setStatus("Cargando el motor (Python en el navegador)… puede tardar unos segundos la primera vez.");
    if (!(window as any).loadPyodide) await loadScript(PY_BASE + "pyodide.js");
    const py = await (window as any).loadPyodide({ indexURL: PY_BASE });
    setStatus("Cargando reglas del juego…");
    const res = await fetch("/api/pysrc");
    const { modules } = await res.json();
    for (const [name, src] of Object.entries(modules as Record<string, string>)) {
      py.FS.writeFile(name, src);
    }
    py.runPython(BOOTSTRAP);
    pyRef.current = py;
    setStatus("");
    return py;
  }

  function toggleFoe(key: string) {
    setFoes((f) => (f.includes(key) ? f.filter((x) => x !== key) : f.length < 3 ? [...f, key] : f));
  }

  async function start() {
    setError(null); setBooting(true);
    try {
      const py = await ensurePyodide();
      const specs = [{ key: mine }, ...foes.map((k) => ({ key: k }))];
      const newGame = py.globals.get("new_game");
      const raw = newGame(JSON.stringify(specs), seed, level);
      newGame.destroy?.();
      setState(JSON.parse(raw));
      setPicked(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBooting(false); }
  }

  function doAct(kind: string, arg: object = {}) {
    const py = pyRef.current;
    if (!py) return;
    try {
      const act = py.globals.get("act");
      const raw = act(kind, JSON.stringify(arg));
      act.destroy?.();
      setState(JSON.parse(raw));
      if (kind === "attack" || kind === "end") setPicked(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function togglePick(uid: number) {
    setPicked((s) => { const n = new Set(s); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });
  }

  const meIdx = state?.human_index ?? 0;
  const myTurn = !!state && state.phase === "main" && state.active === meIdx;
  const legal = state?.legal;
  const attackableUids = new Set((legal?.attackers || []).map((a) => a.uid));

  return (
    <div className="wrap">
      <header>
        <h1>🕹️ Jugar contra el sistema</h1>
        <p>Elegí tu deck y hasta 3 rivales. El motor corre en tu navegador (Pyodide); vos manejás tu turno.</p>
      </header>

      {!state && (
        <div className="card">
          <h2><span className="step">1</span> Preparar la partida</h2>
          <div className="row" style={{ flexWrap: "wrap", gap: 14 }}>
            <label>Tu deck&nbsp;
              <select value={mine} onChange={(e) => setMine(e.target.value)}
                style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
                {decks.map((d) => <option key={d.key} value={d.key}>{d.commander}</option>)}
              </select>
            </label>
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
          </div>
          <p className="muted" style={{ marginTop: 12, marginBottom: 6 }}>Rivales ({foes.length}/3):</p>
          <div className="decks">
            {decks.filter((d) => d.key !== mine).map((d) => (
              <button key={d.key} className={`deck-btn ${foes.includes(d.key) ? "on" : ""}`} onClick={() => toggleFoe(d.key)}>
                <div className="name">{d.commander}</div>
                <div className="sub">{d.theme || "ejemplo"}</div>
              </button>
            ))}
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="go" onClick={start} disabled={booting || !mine || foes.length < 1}>
              {booting ? "Preparando…" : "Empezar partida"}
            </button>
          </div>
          {status && <p className="muted" style={{ marginTop: 10 }}>⏳ {status}</p>}
          {error && <p className="err">⚠ {error}</p>}
          <p className="muted" style={{ marginTop: 10, fontSize: ".8rem" }}>
            Por ahora se juega con los decks de ejemplo (sin conexión). Los decks
            importados con arte real llegan en un próximo paso.
          </p>
        </div>
      )}

      {state && (
        <>
          <div className="card">
            <div className="now">
              <span className="turnbadge">Turno {state.turn}</span>
              <span className="label">
                {state.phase === "over" ? "Partida terminada"
                  : myTurn ? "Tu turno — jugá tus cartas" : `Juega ${state.players[state.active]?.name}`}
              </span>
              <button className="ghost" style={{ marginLeft: "auto" }} onClick={() => { setState(null); setError(null); }}>
                ↩ Nueva partida
              </button>
            </div>

            <div className="seats" data-n={state.players.length}>
              {state.players.map((p, i) => (
                <Seat
                  key={p.name} p={p} active={i === state.active} art={{}} reduce={reduce}
                  selectableUids={myTurn && i === meIdx && !state.attacked ? attackableUids : undefined}
                  selectedUids={i === meIdx ? picked : undefined}
                  onCard={i === meIdx ? togglePick : undefined}
                />
              ))}
            </div>

            {state.winner && (
              <p className="win-line">🏆 {state.winner === "EMPATE" ? "Empate (límite de turnos)." : <>Gana <b>{state.winner}</b>.</>}</p>
            )}
          </div>

          {myTurn && (
            <div className="card">
              <h2>Tu turno</h2>
              {legal && legal.lands.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Jugar tierra:</span>
                  {legal.lands.slice(0, 1).map((l) => (
                    <button key={l.i} className="ghost" onClick={() => doAct("land", { i: l.i })}>🏞 {l.name}</button>
                  ))}
                  {legal.lands.length > 1 && <span className="muted">(+{legal.lands.length - 1} más en mano)</span>}
                </div>
              )}
              {legal && legal.casts.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Lanzar:</span>
                  {legal.casts.map((c, k) => (
                    <button key={k} className="ghost" onClick={() => doAct("cast", { i: c.i, zone: c.zone })}>
                      {c.zone === "command" ? "👑 " : ""}{c.name} <span className="muted">{c.cost}{c.zone === "command" && c.tax ? ` +${c.tax}` : ""}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="act-block">
                <button className="go" onClick={() => doAct("attack", { uids: [...picked] })}
                  disabled={!legal?.can_attack || picked.size === 0}>
                  ⚔ Atacar {picked.size > 0 ? `(${picked.size})` : ""}
                </button>
                <button className="ghost" onClick={() => doAct("end")} disabled={!legal?.can_end}>Terminar turno ⏭</button>
              </div>
              <p className="muted" style={{ fontSize: ".8rem" }}>
                Elegí criaturas tocándolas en tu tablero para atacar. Cuando un rival
                te ataque, los bloqueos los decide tu deck automáticamente (por ahora).
              </p>
            </div>
          )}

          <div className="card">
            <h2>Relato</h2>
            <div className="log">{(state.log || []).join("\n")}</div>
          </div>
        </>
      )}

      <footer>
        El sistema juega los turnos rivales con la dificultad elegida. Cartas de
        ejemplo con ficha simple; el arte real llega al soportar decks importados.
      </footer>
    </div>
  );
}
