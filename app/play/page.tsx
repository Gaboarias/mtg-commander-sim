"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Seat, type PlayerState, type Perm } from "../board";
import { listDecks, type SavedDeck } from "../localDecks";
import { download, fileStamp } from "../download";
import { Icon } from "../icons";

const PY_VERSION = "0.26.4";
const PY_BASE = `https://cdn.jsdelivr.net/pyodide/v${PY_VERSION}/full/`;

type RegDeck = { key: string; commander: string; identity: string[]; theme?: string };
type Spec = { kind: "registered"; key: string; name: string } | { kind: "custom"; name: string; text: string };
type Pickable = { id: string; label: string; tag: string; spec: Spec; mine: boolean };
type HandCard = {
  i: number; name: string; is_land: boolean; is_creature: boolean; cost: string;
  power: number | null; toughness: number | null; types: string[];
  keywords: string[]; abilities: string[];
};
type Activatable = { uid: number; name: string; loyalty: number; abilities: { i: number; cost: number; text?: string }[] };
type TargetOpt = { uid?: number; idx?: number; name: string; power?: number; toughness?: number; from?: string };
type ModeOpt = { i: number; label: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[] };
type CastOpt = { i?: number; name: string; zone: string; cost: string; tax?: number; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; modes?: ModeOpt[]; mode_pick?: number };
type Legal = {
  lands: { i: number; name: string }[];
  casts: CastOpt[];
  attackers: { uid: number; name: string; power: number; toughness: number }[];
  activatables: Activatable[];
  attack_targets: { index: number; name: string; life: number }[];
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
  responses: { i: number; name: string; cost: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; modes?: ModeOpt[]; mode_pick?: number }[];
};
type Mulligan = { mulls: number; to_bottom: number; lands: number };
type GameState = {
  turn: number; active: number; human_index: number; phase: string; attacked: boolean;
  winner: string | null; players: PlayerState[]; legal: Legal; combat: Combat | null;
  mulligan: Mulligan | null; log: string[];
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
def new_game(specs_json, datamap_json, seed, level):
    specs = json.loads(specs_json)
    datamap = json.loads(datamap_json or '{}')
    _IG['g'] = interactive.from_specs(specs, datamap, 0, int(seed), level)
    return json.dumps(_IG['g'].state())
def act(kind, arg_json):
    g = _IG['g']; a = json.loads(arg_json or '{}')
    if kind == 'land': g.play_land(a['i'])
    elif kind == 'cast': g.cast(a.get('i'), a.get('zone', 'hand'), a.get('target_uids'), a.get('mode'))
    elif kind == 'attack': g.attack(a.get('uids', []), a.get('target'))
    elif kind == 'end': g.end_turn()
    elif kind == 'activate': g.activate(a.get('uid'), a.get('index', 0))
    elif kind == 'respond': g.respond(a.get('i'), a.get('target_uids'), a.get('mode'))
    elif kind == 'defend': g.resolve_defense(a.get('pairs', []))
    elif kind == 'mulligan': g.mulligan()
    elif kind == 'keep': g.keep(a.get('bottom', []))
    return json.dumps(g.state())
def export_game():
    return json.dumps(_IG['g'].export())
`;

export default function Play() {
  const reduce = useReducedMotion() ?? false;
  const [pickables, setPickables] = useState<Pickable[]>([]);
  const [mineId, setMineId] = useState<string>("");
  const [foeIds, setFoeIds] = useState<string[]>([]);
  const [level, setLevel] = useState("intermedio");
  const [seed, setSeed] = useState(1);

  const pyRef = useRef<any>(null);
  const [status, setStatus] = useState<string>("");   // texto de carga
  const [booting, setBooting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());  // atacantes elegidos
  const [atkTarget, setAtkTarget] = useState<number | null>(null); // rival a atacar
  const [art, setArt] = useState<Record<string, string>>({});
  const [info, setInfo] = useState<Record<string, CardInfo>>({});
  const [inspect, setInspect] = useState<Inspect | null>(null);
  const infoReq = useRef<Set<string>>(new Set());  // nombres ya pedidos
  const [assign, setAssign] = useState<Record<number, number>>({});  // bloqueador -> atacante
  const [targeting, setTargeting] = useState<{ kind: "cast" | "respond"; i?: number; zone?: string; name: string; targets: TargetOpt[]; count: number; mode?: number } | null>(null);
  const [modePick, setModePick] = useState<{ kind: "cast" | "respond"; i?: number; zone?: string; name: string; modes: ModeOpt[] } | null>(null);
  const [tsel, setTsel] = useState<number[]>([]);  // objetivos elegidos (multi)
  const [bottom, setBottom] = useState<number[]>([]);  // cartas al fondo tras mulligan

  const examplesRef = useRef<Pickable[]>([]);

  function myPickables(): Pickable[] {
    return listDecks().map((d: SavedDeck) => ({
      id: "mine:" + d.id, label: d.name, tag: "mi deck",
      spec: { kind: "custom", name: d.name, text: d.text }, mine: true,
    }));
  }

  // arma la lista completa (mis decks + ejemplos), preservando la selección
  function rebuild(examples: Pickable[]) {
    const mine = myPickables();
    const all = [...mine, ...examples];
    setPickables(all);
    setMineId((prev) => (all.some((p) => p.id === prev) ? prev : (mine[0] || all[0])?.id || ""));
    setFoeIds((prev) => {
      const keep = prev.filter((id) => all.some((p) => p.id === id));
      if (keep.length > 0) return keep;
      const first = all.find((p) => p.id !== (mine[0] || all[0])?.id);
      return first ? [first.id] : [];
    });
  }

  useEffect(() => {
    fetch("/api/catalog").then((r) => r.json()).then((d) => {
      examplesRef.current = (d.decks || []).map((x: RegDeck) => ({
        id: "reg:" + x.key, label: x.commander, tag: x.theme || "ejemplo",
        spec: { kind: "registered", key: x.key, name: x.commander }, mine: false,
      }));
      rebuild(examplesRef.current);
    }).catch(() => rebuild([]));
    // volver del editor: refrescar mis decks guardados al recuperar el foco
    const refresh = () => { if (document.visibilityState === "visible") rebuild(examplesRef.current); };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function ensurePyodide() {
    if (pyRef.current) return pyRef.current;
    setStatus("Preparando el motor… la primera vez puede tardar unos segundos.");
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

  function toggleFoe(id: string) {
    setFoeIds((f) => (f.includes(id) ? f.filter((x) => x !== id) : f.length < 3 ? [...f, id] : f));
  }

  async function start() {
    setError(null); setBooting(true);
    try {
      const mineP = pickables.find((p) => p.id === mineId);
      const foesP = foeIds.map((id) => pickables.find((p) => p.id === id)).filter(Boolean) as Pickable[];
      if (!mineP || foesP.length < 1) { setError("Elegí tu deck y al menos un rival."); setBooting(false); return; }
      const specs: Spec[] = [mineP.spec, ...foesP.map((p) => p.spec)];

      // decks importados: resolver sus cartas (Scryfall) en el servidor
      let datamap: Record<string, any> = {};
      const customTexts = specs.filter((s) => s.kind === "custom").map((s) => (s as { text: string }).text);
      if (customTexts.length > 0) {
        setStatus("Buscando las fotos y los textos de tus cartas…");
        const r = await fetch("/api/resolvedeck", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ texts: customTexts }),
        });
        const d = await r.json();
        if (d.error) throw new Error(d.error);
        datamap = d.cards || {};
        // sembrar arte + texto para no volver a pedirlos
        const seedArt: Record<string, string> = {};
        const seedInfo: Record<string, CardInfo> = {};
        for (const c of Object.values(datamap) as any[]) {
          const nm: string = c?.name;
          if (!nm) continue;
          const iu = c.image_uris || (c.card_faces && c.card_faces[0] && c.card_faces[0].image_uris) || {};
          const url = iu.art_crop || iu.normal || iu.small;
          if (url) seedArt[nm] = url;
          seedInfo[nm] = { art: url, type: c.type_line || "", oracle: c.oracle_text || (c.card_faces && c.card_faces[0] && c.card_faces[0].oracle_text) || "" };
          infoReq.current.add(nm);
        }
        setArt((p) => ({ ...seedArt, ...p }));
        setInfo((p) => ({ ...seedInfo, ...p }));
      }

      const py = await ensurePyodide();
      const newGame = py.globals.get("new_game");
      const raw = newGame(JSON.stringify(specs), JSON.stringify(datamap), seed, level);
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
      if (kind === "mulligan" || kind === "keep") setBottom([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function togglePick(uid: number) {
    setPicked((s) => { const n = new Set(s); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });
  }

  function exportGame(fmt: "json" | "txt") {
    const py = pyRef.current;
    if (!py) return;
    const fn = py.globals.get("export_game");
    const raw = fn();
    fn.destroy?.();
    const data = JSON.parse(raw);
    const stamp = fileStamp();
    if (fmt === "json") {
      download(`partida-${stamp}.json`, JSON.stringify(data, null, 2), "application/json");
    } else {
      const head = `Partida — ${data.players.join(" vs ")}\nGanador: ${data.winner || "sin definir"} · ${data.turns} turnos\n\n`;
      download(`partida-${stamp}.txt`, head + (data.log || []).join("\n"), "text/plain");
    }
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

  // lanzar: si es modal, elegir modo; si necesita objetivo, abrir el selector
  function castCard(c: CastOpt) {
    if (c.modes && c.modes.length > 0) {
      setModePick({ kind: "cast", i: c.i, zone: c.zone, name: c.name, modes: c.modes });
    } else if (c.target_spec && c.targets && c.targets.length > 0) {
      setTsel([]);
      setTargeting({ kind: "cast", i: c.i, zone: c.zone, name: c.name, targets: c.targets, count: c.target_count || 1 });
    } else {
      doAct("cast", { i: c.i, zone: c.zone });
    }
  }
  function respondCard(r: { i: number; name: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; modes?: ModeOpt[] }) {
    if (r.modes && r.modes.length > 0) {
      setModePick({ kind: "respond", i: r.i, name: r.name, modes: r.modes });
    } else if (r.target_spec && r.targets && r.targets.length > 0) {
      setTsel([]);
      setTargeting({ kind: "respond", i: r.i, name: r.name, targets: r.targets, count: r.target_count || 1 });
    } else {
      doAct("respond", { i: r.i });
    }
  }
  // elegido un modo: si necesita objetivo, encadenar el selector; si no, disparar
  function chooseMode(m: ModeOpt) {
    if (!modePick) return;
    const base = modePick;
    setModePick(null);
    if (m.target_spec && m.targets && m.targets.length > 0) {
      setTsel([]);
      setTargeting({ kind: base.kind, i: base.i, zone: base.zone, name: `${base.name} — ${m.label}`,
        targets: m.targets, count: m.target_count || 1, mode: m.i });
    } else {
      doAct(base.kind, { i: base.i, zone: base.zone, mode: m.i });
    }
  }
  function dispatchTargets(uids: number[]) {
    if (!targeting) return;
    doAct(targeting.kind, { i: targeting.i, zone: targeting.zone, target_uids: uids, mode: targeting.mode });
    setTargeting(null);
    setTsel([]);
  }
  function chooseTarget(t: TargetOpt) {
    const tu = (t.uid ?? t.idx) as number;
    if (!targeting) return;
    if (targeting.count <= 1) {
      dispatchTargets([tu]);            // objetivo único: dispara directo
    } else {
      setTsel((s) => s.includes(tu) ? s.filter((x) => x !== tu)
        : s.length < targeting.count ? [...s, tu] : s);   // multi: hasta N
    }
  }

  const meIdx = state?.human_index ?? 0;
  const myTurn = !!state && state.phase === "main" && state.active === meIdx;
  const legal = state?.legal;
  const attackableUids = new Set((legal?.attackers || []).map((a) => a.uid));

  return (
    <div className="wrap">
      <header>
        <h1><Icon name="gamepad" size={26} /> Jugar contra el sistema</h1>
        <p>Elegí tu deck y hasta 3 rivales. Todo corre en tu navegador y vos manejás tu turno; el resto lo juega el sistema.</p>
      </header>

      {!state && (
        <div className="card">
          <h2><span className="step">1</span> Preparar la partida</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Tus decks guardados (<Icon name="star" size={12} />) del <a href="/deck">editor</a> aparecen acá.
            {pickables.some((p) => p.mine)
              ? " "
              : " Todavía no tenés decks guardados: creá y guardá uno en el editor."}
            <button className="ghost" style={{ padding: "2px 10px", marginLeft: 8, display: "inline-flex", alignItems: "center", gap: 5 }}
              onClick={() => rebuild(examplesRef.current)}><Icon name="refresh" size={13} /> Actualizar mis decks</button>
          </p>
          <div className="row" style={{ flexWrap: "wrap", gap: 14 }}>
            <label>Tu deck&nbsp;
              <select value={mineId} onChange={(e) => setMineId(e.target.value)}
                style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
                {pickables.map((p) => <option key={p.id} value={p.id}>{p.mine ? "★ " : ""}{p.label}</option>)}
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
          <p className="muted" style={{ marginTop: 12, marginBottom: 6 }}>Rivales ({foeIds.length}/3):</p>
          <div className="decks">
            {pickables.filter((p) => p.id !== mineId).map((p) => (
              <button key={p.id} className={`deck-btn ${foeIds.includes(p.id) ? "on" : ""}`} onClick={() => toggleFoe(p.id)}>
                <div className="name">{p.mine ? <Icon name="star" size={13} /> : null}{p.mine ? " " : ""}{p.label}</div>
                <div className="sub">{p.tag}</div>
              </button>
            ))}
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="go" onClick={start} disabled={booting || !mineId || foeIds.length < 1}>
              {booting ? "Preparando…" : "Empezar partida"}
            </button>
          </div>
          {status && <p className="muted" style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 6 }}><Icon name="hourglass" size={14} /> {status}</p>}
          {error && <p className="err" role="alert"><Icon name="warning" size={15} /> {error}</p>}
          <p className="muted" style={{ marginTop: 10, fontSize: ".8rem" }}>
            Podés jugar con tus decks guardados (<Icon name="star" size={12} />) o los de ejemplo.
            A tus cartas les buscamos la foto y el texto antes de empezar.
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
              <button className="ghost" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5 }} onClick={() => { setState(null); setError(null); }}>
                <Icon name="undo" size={14} /> Nueva partida
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
              <p className="win-line"><Icon name="trophy" size={18} /> {state.winner === "EMPATE" ? "Empate (límite de turnos)." : <>Gana <b>{state.winner}</b>.</>}</p>
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
                  transition={reduce ? undefined : { repeat: Infinity, duration: 1.1 }}><Icon name="swords" size={18} /></motion.span>
                {state.combat.from} te ataca — {state.combat.incoming_damage} de daño en camino
              </h2>
              <div className="def-attackers">
                {state.combat.attackers.map((a) => (
                  <div key={a.uid} className={`atk-chip ${assign && Object.values(assign).includes(a.uid) ? "blocked" : ""}`}>
                    {a.commander ? <Icon name="crown" size={13} /> : null}{a.commander ? " " : ""}{a.name} <b>{a.power}/{a.toughness}</b>
                    <span className="muted">{Object.values(assign).includes(a.uid) ? " · bloqueado" : " · sin bloquear"}</span>
                  </div>
                ))}
              </div>

              {state.combat.responses.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Responder (instantáneo):</span>
                  {state.combat.responses.map((r) => (
                    <button key={r.i} className="ghost" onClick={() => respondCard(r)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="bolt" size={13} /> {r.name}{r.target_spec ? <Icon name="target" size={12} /> : null} <span className="muted">{r.cost}</span>
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
                <button className="go" style={{ display: "inline-flex", alignItems: "center", gap: 6 }} onClick={() => doAct("defend", {
                  pairs: Object.entries(assign).map(([blk, atk]) => ({ blocker: Number(blk), attacker: atk })),
                })}>
                  {Object.keys(assign).length > 0 ? <><Icon name="check" size={14} /> Confirmar bloqueos</> : <><Icon name="check" size={14} /> Recibir el ataque</>}
                </button>
              </div>
              <p className="muted" style={{ fontSize: ".8rem" }}>
                Antes de resolver el daño podés lanzar un instantáneo y asignar bloqueos.
                El registro completo queda en el relato de abajo.
              </p>
            </motion.div>
          )}

          {state.mulligan && (() => {
            const m = state.mulligan;
            const hand = state.players[meIdx]?.hand_cards || [];
            const enough = bottom.length === m.to_bottom;
            return (
              <div className="card">
                <h2><Icon name="hand" size={19} /> Mano inicial{m.mulls > 0 ? ` · mulligan ${m.mulls}` : ""}</h2>
                <p className="muted" style={{ marginTop: 0 }}>
                  {m.lands} tierra{m.lands === 1 ? "" : "s"} en mano.
                  {m.lands <= 1 && <b style={{ color: "#e0684f" }}> Con tan pocas tierras, conviene mulligan.</b>}
                  {" "}En Commander el primer mulligan es <b>gratis</b>; a partir del segundo, mandás 1 carta al fondo por cada uno.
                </p>
                {m.to_bottom > 0 && (
                  <p className="muted">Elegí <b>{m.to_bottom}</b> carta{m.to_bottom === 1 ? "" : "s"} para el fondo ({bottom.length}/{m.to_bottom}).</p>
                )}
                <div className="hand">
                  {hand.map((hc) => {
                    const sel = bottom.includes(hc.i);
                    return (
                      <div key={hc.i} className={`handcard ${sel ? "playable" : ""}`}>
                        <div className="hc-art" title="Tocar para ver / elegir"
                          onClick={() => {
                            if (m.to_bottom > 0) {
                              setBottom((b) => b.includes(hc.i) ? b.filter((x) => x !== hc.i)
                                : b.length < m.to_bottom ? [...b, hc.i] : b);
                            } else { inspectCard(hc); }
                          }}
                          style={art[hc.name] ? { backgroundImage: `url(${art[hc.name]})` } : undefined}>
                          {!art[hc.name] && <span>{hc.name}</span>}
                          {hc.cost && <span className="hc-cost">{hc.cost}</span>}
                          {sel && <span className="cm-counter" style={{ left: "auto", right: 2, display: "inline-flex", alignItems: "center", gap: 2 }}><Icon name="arrow-down" size={11} /> fondo</span>}
                        </div>
                        <div className="hc-foot">
                          <span className="hc-name" onClick={() => inspectCard(hc)}>{hc.name}{hc.is_land ? <> <Icon name="land" size={12} /></> : null}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="act-block">
                  <button className="ghost" onClick={() => doAct("mulligan")} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><Icon name="refresh" size={14} /> Mulligan</button>
                  <button className="go" style={{ display: "inline-flex", alignItems: "center", gap: 5 }} onClick={() => doAct("keep", { bottom })} disabled={m.to_bottom > 0 && !enough}>
                    <Icon name="check" size={14} /> Mantener{m.to_bottom > 0 ? ` (fondo: ${bottom.length}/${m.to_bottom})` : ""}
                  </button>
                </div>
              </div>
            );
          })()}

          {myTurn && (() => {
            const landIdx = new Set((legal?.lands || []).map((l) => l.i));
            const castMap = new Map((legal?.casts || []).filter((c) => c.zone === "hand").map((c) => [c.i, c]));
            const commandCasts = (legal?.casts || []).filter((c) => c.zone === "command");
            const hand = state.players[meIdx]?.hand_cards || [];
            return (
              <div className="card">
                <h2>Tu mano</h2>
                <div className="hand">
                  {hand.map((hc) => {
                    const canLand = landIdx.has(hc.i);
                    const castOpt = castMap.get(hc.i);
                    return (
                      <div key={hc.i} className={`handcard ${canLand || castOpt ? "playable" : ""}`}>
                        <div className="hc-art" onClick={() => inspectCard(hc)} title="Ver carta"
                          style={art[hc.name] ? { backgroundImage: `url(${art[hc.name]})` } : undefined}>
                          {!art[hc.name] && <span>{hc.name}</span>}
                          {hc.cost && <span className="hc-cost">{hc.cost}</span>}
                        </div>
                        <div className="hc-foot">
                          <span className="hc-name" onClick={() => inspectCard(hc)}>{hc.name}</span>
                          {canLand && <button className="go tiny" onClick={() => doAct("land", { i: hc.i })}>Jugar</button>}
                          {castOpt && <button className="go tiny" onClick={() => castCard(castOpt)} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                            Lanzar{castOpt.target_spec ? <Icon name="target" size={12} /> : null}
                          </button>}
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
                      <button key={k} className="ghost" onClick={() => castCard(c)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name="crown" size={13} /> Lanzar {c.name}{c.target_spec ? <Icon name="target" size={12} /> : null} <span className="muted">{c.cost}{c.tax ? ` +${c.tax}` : ""}</span>
                      </button>
                    ))}
                  </div>
                )}

                {legal && legal.activatables.length > 0 && (
                  <div className="act-block">
                    <span className="act-label">Planeswalkers:</span>
                    {legal.activatables.map((pw) =>
                      pw.abilities.map((ab) => (
                        <button key={pw.uid + "-" + ab.i} className="ghost pw-ab"
                          title={ab.text || ""}
                          onClick={() => doAct("activate", { uid: pw.uid, index: ab.i })}>
                          <b>{pw.name} {ab.cost >= 0 ? `+${ab.cost}` : ab.cost}</b>{" "}
                          <span className="muted">(◆{pw.loyalty})</span>
                          {ab.text ? <em className="pw-txt">{ab.text}</em> : null}
                        </button>
                      ))
                    )}
                  </div>
                )}

                <div className="act-block">
                  {(legal?.attack_targets?.length || 0) > 1 && (
                    <label className="muted" style={{ fontSize: ".82rem" }}>
                      Atacar a:{" "}
                      <select value={atkTarget ?? legal!.attack_targets[0].index}
                        onChange={(e) => setAtkTarget(Number(e.target.value))}>
                        {legal!.attack_targets.map((t) => (
                          <option key={t.index} value={t.index}>{t.name} ({t.life}♥)</option>
                        ))}
                      </select>
                    </label>
                  )}
                  <button className="go" onClick={() => doAct("attack", {
                    uids: [...picked],
                    target: atkTarget ?? legal?.attack_targets?.[0]?.index,
                  })}
                    disabled={!legal?.can_attack || picked.size === 0}
                    style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <Icon name="swords" size={15} /> Atacar {picked.size > 0 ? `(${picked.size})` : ""}
                  </button>
                  <button className="ghost" onClick={() => doAct("end")} disabled={!legal?.can_end} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>Terminar turno <Icon name="skip-forward" size={14} /></button>
                </div>
                <p className="muted" style={{ fontSize: ".8rem" }}>
                  Tocá una carta para ver sus habilidades. Elegí criaturas tocándolas
                  en tu tablero para atacar y, si hay más de un rival, a quién atacar.
                  Cuando un rival te ataque, vos elegís los bloqueos y podés responder
                  con instantáneos.
                </p>
              </div>
            );
          })()}

          <div className="card">
            <h2>Relato</h2>
            <div className="log">{(state.log || []).join("\n")}</div>
            <div className="act-block" style={{ marginTop: 10 }}>
              <span className="act-label">Exportar todas las jugadas:</span>
              <button className="ghost" onClick={() => exportGame("json")} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><Icon name="download" size={14} /> JSON</button>
              <button className="ghost" onClick={() => exportGame("txt")} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><Icon name="download" size={14} /> Texto</button>
            </div>
          </div>
        </>
      )}

      {modePick && (
        <div className="inspect-back" onClick={() => setModePick(null)}>
          <div className="inspect" onClick={(e) => e.stopPropagation()}>
            <button className="inspect-x" aria-label="Cerrar" title="Cerrar" onClick={() => setModePick(null)}><Icon name="x" size={16} /></button>
            <h3><Icon name="sparkles" size={17} /> {modePick.name} — elegí un modo</h3>
            <p className="muted" style={{ marginTop: 2 }}>¿Qué querés que haga?</p>
            <div className="target-list">
              {modePick.modes.map((m) => (
                <button key={m.i} className="ghost" onClick={() => chooseMode(m)} style={{ textAlign: "left" }}>
                  {m.label}{m.target_spec ? <Icon name="target" size={12} /> : null}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {targeting && (
        <div className="inspect-back" onClick={() => setTargeting(null)}>
          <div className="inspect" onClick={(e) => e.stopPropagation()}>
            <button className="inspect-x" aria-label="Cerrar" title="Cerrar" onClick={() => setTargeting(null)}><Icon name="x" size={16} /></button>
            <h3><Icon name="target" size={17} /> Objetivo{targeting.count > 1 ? "s" : ""} de {targeting.name}</h3>
            <p className="muted" style={{ marginTop: 2 }}>
              {targeting.count > 1
                ? `Elegí hasta ${targeting.count} objetivos (${tsel.length}/${targeting.count}):`
                : "Elegí a qué apunta:"}
            </p>
            <div className="target-list">
              {targeting.targets.map((t, k) => {
                const tu = (t.uid ?? t.idx) as number;
                const sel = tsel.includes(tu);
                return (
                  <button key={k} className={`ghost ${sel ? "on" : ""}`} onClick={() => chooseTarget(t)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {targeting.count > 1 ? <Icon name={sel ? "check-circle" : "plus"} size={13} /> : null}
                    {t.name}{t.power != null ? ` ${t.power}/${t.toughness}` : ""}
                    {t.from ? <span className="muted"> · {t.from}</span> : null}
                  </button>
                );
              })}
            </div>
            {targeting.count > 1 && (
              <div className="act-block" style={{ marginTop: 10 }}>
                <button className="go" onClick={() => dispatchTargets(tsel)} disabled={tsel.length === 0}>
                  Confirmar ({tsel.length}/{targeting.count})
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {inspect && (
        <div className="inspect-back" onClick={() => setInspect(null)}>
          <div className="inspect" onClick={(e) => e.stopPropagation()}>
            <button className="inspect-x" aria-label="Cerrar" title="Cerrar" onClick={() => setInspect(null)}><Icon name="x" size={16} /></button>
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
        Los rivales los juega el sistema, en la dificultad que elijas. Tus decks
        (<Icon name="star" size={12} />) van con foto y texto real; los de ejemplo usan una ficha simple.
        Tocá cualquier carta (o su <Icon name="info" size={12} />) para verla de cerca.
      </footer>
    </div>
  );
}
