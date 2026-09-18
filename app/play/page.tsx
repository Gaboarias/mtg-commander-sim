"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Seat, type PlayerState, type Perm } from "../board";

const PY_VERSION = "0.26.4";
const PY_BASE = `https://cdn.jsdelivr.net/pyodide/v${PY_VERSION}/full/`;

type RegDeck = { key: string; commander: string; identity: string[]; theme?: string };
type HandCard = {
  i: number; name: string; is_land: boolean; is_creature: boolean; cost: string;
  power: number | null; toughness: number | null; types: string[];
  keywords: string[]; abilities: string[];
};
type Activatable = { uid: number; name: string; loyalty: number; abilities: { i: number; cost: number }[] };
type Legal = {
  lands: { i: number; name: string }[];
  casts: { i?: number; name: string; zone: string; cost: string; tax?: number }[];
  attackers: { uid: number; name: string; power: number; toughness: number }[];
  activatables: Activatable[];
  can_attack: boolean; can_end: boolean;
};
type CardInfo = { art?: string; type?: string; oracle?: string };
type Inspect = {
  name: string; cost?: string; types?: string[]; power?: number | null;
  toughness?: number | null; keywords?: string[]; abilities?: string[];
};
type CombatAtk = { uid: number; name: string; power: number; toughness: number; commander: boolean; from: string };
type Combat = {
  from: string; incoming_damage: number;
  attackers: CombatAtk[];
  blockers: { uid: number; name: string; power: number; toughness: number }[];
  responses: { i: number; name: string; cost: string }[];
};
type GameState = {
  turn: number; active: number; human_index: number; phase: string; attacked: boolean;
  winner: string | null; players: PlayerState[]; legal: Legal; combat: Combat | null; log: string[];
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
    elif kind == 'activate': g.activate(a.get('uid'), a.get('index', 0))
    elif kind == 'respond': g.respond(a.get('i'))
    elif kind == 'defend': g.resolve_defense(a.get('pairs', []))
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
  const [art, setArt] = useState<Record<string, string>>({});
  const [info, setInfo] = useState<Record<string, CardInfo>>({});
  const [inspect, setInspect] = useState<Inspect | null>(null);
  const infoReq = useRef<Set<string>>(new Set());  // nombres ya pedidos
  const [assign, setAssign] = useState<Record<number, number>>({});  // bloqueador -> atacante

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
      if (kind === "defend") setAssign({});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function togglePick(uid: number) {
    setPicked((s) => { const n = new Set(s); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });
  }

  // trae arte + texto real (Scryfall) para las cartas que van apareciendo
  useEffect(() => {
    if (!state) return;
    const names = new Set<string>();
    for (const p of state.players) {
      p.commander.forEach((n) => names.add(n));
      p.graveyard.forEach((n) => names.add(n));
      p.battlefield.forEach((pm) => names.add(pm.name));
      (p.hand_cards || []).forEach((c) => names.add(c.name));
    }
    const need = [...names].filter((n) => n && !infoReq.current.has(n));
    if (need.length === 0) return;
    need.forEach((n) => infoReq.current.add(n));
    fetch("/api/cardinfo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names: need }),
    })
      .then((r) => r.json())
      .then((d) => {
        const gotInfo: Record<string, CardInfo> = d.info || {};
        setInfo((prev) => ({ ...prev, ...gotInfo }));
        setArt((prev) => {
          const next = { ...prev };
          for (const [n, v] of Object.entries(gotInfo)) if (v.art) next[n] = v.art;
          return next;
        });
      })
      .catch(() => {});
  }, [state]);

  function inspectCard(x: { name: string; cost?: string; types?: string[]; power?: number | null; toughness?: number | null; keywords?: string[]; abilities?: string[] }) {
    setInspect({
      name: x.name, cost: x.cost, types: x.types, power: x.power,
      toughness: x.toughness, keywords: x.keywords, abilities: x.abilities,
    });
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
                  key={p.name} p={p} active={i === state.active} art={art} reduce={reduce}
                  selectableUids={myTurn && i === meIdx && !state.attacked ? attackableUids : undefined}
                  selectedUids={i === meIdx ? picked : undefined}
                  onCard={i === meIdx ? togglePick : undefined}
                  onInspect={(pm: Perm) => inspectCard(pm)}
                />
              ))}
            </div>

            {state.winner && (
              <p className="win-line">🏆 {state.winner === "EMPATE" ? "Empate (límite de turnos)." : <>Gana <b>{state.winner}</b>.</>}</p>
            )}
          </div>

          {state.combat && (
            <motion.div className="card defense"
              initial={reduce ? false : { opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}>
              <h2 className="def-title">
                <motion.span className="alert"
                  animate={reduce ? {} : { scale: [1, 1.15, 1] }}
                  transition={{ repeat: Infinity, duration: 1.1 }}>⚔</motion.span>
                {state.combat.from} te ataca — {state.combat.incoming_damage} de daño en camino
              </h2>
              <div className="def-attackers">
                {state.combat.attackers.map((a) => (
                  <div key={a.uid} className={`atk-chip ${assign && Object.values(assign).includes(a.uid) ? "blocked" : ""}`}>
                    {a.commander ? "👑 " : ""}{a.name} <b>{a.power}/{a.toughness}</b>
                    <span className="muted">{Object.values(assign).includes(a.uid) ? " · bloqueado" : " · sin bloquear"}</span>
                  </div>
                ))}
              </div>

              {state.combat.responses.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Responder (instantáneo):</span>
                  {state.combat.responses.map((r) => (
                    <button key={r.i} className="ghost" onClick={() => doAct("respond", { i: r.i })}>
                      ⚡ {r.name} <span className="muted">{r.cost}</span>
                    </button>
                  ))}
                </div>
              )}

              {state.combat.blockers.length > 0 ? (
                <div className="def-blockers">
                  <span className="act-label">Tus bloqueadores:</span>
                  {state.combat.blockers.map((b) => (
                    <div key={b.uid} className="blk-row">
                      <span>{b.name} <b>{b.power}/{b.toughness}</b></span>
                      <select value={assign[b.uid] ?? ""}
                        onChange={(e) => setAssign((m) => {
                          const v = e.target.value;
                          const n = { ...m };
                          if (v === "") delete n[b.uid]; else n[b.uid] = Number(v);
                          return n;
                        })}
                        style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 8px" }}>
                        <option value="">— no bloquea —</option>
                        {state.combat!.attackers.map((a) => (
                          <option key={a.uid} value={a.uid}>bloquea a {a.name} ({a.power}/{a.toughness})</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No tenés criaturas para bloquear.</p>
              )}

              <div className="act-block">
                <button className="go" onClick={() => doAct("defend", {
                  pairs: Object.entries(assign).map(([blk, atk]) => ({ blocker: Number(blk), attacker: atk })),
                })}>
                  {Object.keys(assign).length > 0 ? "Confirmar bloqueos ✔" : "Recibir el ataque ✔"}
                </button>
              </div>
              <p className="muted" style={{ fontSize: ".8rem" }}>
                Antes de resolver el daño podés lanzar un instantáneo y asignar bloqueos.
                El registro completo queda en el relato de abajo.
              </p>
            </motion.div>
          )}

          {myTurn && (() => {
            const landIdx = new Set((legal?.lands || []).map((l) => l.i));
            const castIdx = new Set((legal?.casts || []).filter((c) => c.zone === "hand").map((c) => c.i));
            const commandCasts = (legal?.casts || []).filter((c) => c.zone === "command");
            const hand = state.players[meIdx]?.hand_cards || [];
            return (
              <div className="card">
                <h2>Tu mano</h2>
                <div className="hand">
                  {hand.map((hc) => {
                    const canLand = landIdx.has(hc.i);
                    const canCast = castIdx.has(hc.i);
                    return (
                      <div key={hc.i} className={`handcard ${canLand || canCast ? "playable" : ""}`}>
                        <div className="hc-art" onClick={() => inspectCard(hc)} title="Ver carta"
                          style={art[hc.name] ? { backgroundImage: `url(${art[hc.name]})` } : undefined}>
                          {!art[hc.name] && <span>{hc.name}</span>}
                          {hc.cost && <span className="hc-cost">{hc.cost}</span>}
                        </div>
                        <div className="hc-foot">
                          <span className="hc-name" onClick={() => inspectCard(hc)}>{hc.name}</span>
                          {canLand && <button className="go tiny" onClick={() => doAct("land", { i: hc.i })}>Jugar</button>}
                          {canCast && <button className="go tiny" onClick={() => doAct("cast", { i: hc.i, zone: "hand" })}>Lanzar</button>}
                        </div>
                      </div>
                    );
                  })}
                  {hand.length === 0 && <span className="muted">mano vacía</span>}
                </div>

                {commandCasts.length > 0 && (
                  <div className="act-block">
                    <span className="act-label">Zona de mando:</span>
                    {commandCasts.map((c, k) => (
                      <button key={k} className="ghost" onClick={() => doAct("cast", { zone: "command" })}>
                        👑 Lanzar {c.name} <span className="muted">{c.cost}{c.tax ? ` +${c.tax}` : ""}</span>
                      </button>
                    ))}
                  </div>
                )}

                {legal && legal.activatables.length > 0 && (
                  <div className="act-block">
                    <span className="act-label">Planeswalkers:</span>
                    {legal.activatables.map((pw) =>
                      pw.abilities.map((ab) => (
                        <button key={pw.uid + "-" + ab.i} className="ghost"
                          onClick={() => doAct("activate", { uid: pw.uid, index: ab.i })}>
                          {pw.name} {ab.cost >= 0 ? `+${ab.cost}` : ab.cost} <span className="muted">(◆{pw.loyalty})</span>
                        </button>
                      ))
                    )}
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
                  Tocá una carta para ver sus habilidades. Elegí criaturas tocándolas
                  en tu tablero para atacar. Cuando un rival te ataque, los bloqueos los
                  decide tu deck automáticamente (por ahora).
                </p>
              </div>
            );
          })()}

          <div className="card">
            <h2>Relato</h2>
            <div className="log">{(state.log || []).join("\n")}</div>
          </div>
        </>
      )}

      {inspect && (
        <div className="inspect-back" onClick={() => setInspect(null)}>
          <div className="inspect" onClick={(e) => e.stopPropagation()}>
            <button className="inspect-x" onClick={() => setInspect(null)}>✕</button>
            {art[inspect.name] ? (
              <div className="inspect-art" style={{ backgroundImage: `url(${art[inspect.name]})` }} />
            ) : (
              <div className="inspect-art ph"><span>{inspect.name}</span></div>
            )}
            <h3>{inspect.name} {inspect.cost ? <span className="muted">{inspect.cost}</span> : null}</h3>
            <p className="muted" style={{ margin: "2px 0" }}>
              {info[inspect.name]?.type || (inspect.types || []).join(" ")}
              {inspect.power != null ? ` · ${inspect.power}/${inspect.toughness}` : ""}
            </p>
            {info[inspect.name]?.oracle ? (
              <p className="oracle">{info[inspect.name]?.oracle}</p>
            ) : (inspect.abilities && inspect.abilities.length > 0) ? (
              <ul className="abil">{inspect.abilities.map((a, k) => <li key={k}>{a}</li>)}</ul>
            ) : (
              <p className="muted">Sin habilidades (carta básica).</p>
            )}
            {!info[inspect.name] && (
              <p className="muted" style={{ fontSize: ".75rem" }}>
                Carta de ejemplo (casera): se muestran sus habilidades del motor.
              </p>
            )}
          </div>
        </div>
      )}

      <footer>
        El sistema juega los turnos rivales con la dificultad elegida. Las cartas
        reales muestran su foto y texto de Scryfall; las de ejemplo, una ficha con
        sus habilidades. Tocá cualquier carta (o su ⓘ) para verla.
      </footer>
    </div>
  );
}
