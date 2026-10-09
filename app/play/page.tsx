"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { Seat, type PlayerState, type Perm } from "../board";
import { listDecks, bumpGamesPlayed, type SavedDeck } from "../localDecks";
import { download, fileStamp } from "../download";
import { Icon } from "../icons";
import { Help } from "../Help";
import { loadGlossary, keywordsIn, supportLabel, type GlossaryEntry } from "../reglas/Glossary";

// etiquetas cortas de keywords (mismo criterio que el tablero)
const KW_SHORT: Record<string, string> = {
  flying: "vuela", reach: "alcance", first_strike: "1er golpe", double_strike: "doble golpe",
  deathtouch: "mortal", trample: "arrolla", lifelink: "vínculo", vigilance: "vigila",
  haste: "prisa", menace: "amenaza", indestructible: "indestr.", hexproof: "antimaleficio",
  shroud: "velo", defender: "muro", flash: "destello", prowess: "prowess",
  infect: "infectar", toxic: "toxic", wither: "marchitar", unblockable: "imbloqueable",
  protection: "protección",
};
// daño efectivo que entra de un atacante sin bloquear (doble golpe pega 2 veces)
function effDamage(a: { power: number; keywords?: string[] }): number {
  const p = Math.max(0, a.power || 0);
  return (a.keywords || []).includes("double_strike") ? p * 2 : p;
}

const TURN_MARK = "‹turno› ";
// Agrupa el relato por turno: cada línea "‹turno› Nombre" abre un grupo nuevo.
// Lo previo al primer turno (mulligan, preparación) va a un grupo sin encabezado.
function groupLog(log: string[]): { head: string | null; lines: string[] }[] {
  const groups: { head: string | null; lines: string[] }[] = [];
  let turn = 0;
  for (const raw of log) {
    if (raw.startsWith(TURN_MARK)) {
      turn++;
      groups.push({ head: `Turno ${turn} · ${raw.slice(TURN_MARK.length)}`, lines: [] });
    } else {
      if (groups.length === 0) groups.push({ head: null, lines: [] });
      groups[groups.length - 1].lines.push(raw);
    }
  }
  return groups;
}

type RegDeck = { key: string; commander: string; identity: string[]; theme?: string };
type Spec = { kind: "registered"; key: string; name: string } | { kind: "custom"; name: string; text: string };
type Pickable = { id: string; label: string; tag: string; spec: Spec; mine: boolean };
type HandCard = {
  i: number; name: string; is_land: boolean; is_creature: boolean; cost: string;
  power: number | null; toughness: number | null; types: string[];
  keywords: string[]; abilities: string[];
};
type Activatable = { uid: number; name: string; loyalty: number; abilities: { i: number; cost: number; text?: string }[] };
type AbilityOpt = { i: number; label: string; cost: string; tap: boolean; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; playable?: boolean; reason?: string | null };
type PermAbility = { uid: number; name: string; abilities: AbilityOpt[] };
type TargetOpt = { uid?: number; idx?: number; name: string; power?: number; toughness?: number; from?: string };
type ModeOpt = { i: number; label: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[] };
type CastOpt = { i?: number; name: string; zone: string; cost: string; tax?: number; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; modes?: ModeOpt[]; mode_pick?: number; castable?: boolean; reason?: string | null };
type Legal = {
  lands: { i: number; name: string }[];
  casts: CastOpt[];
  attackers: { uid: number; name: string; power: number; toughness: number; keywords?: string[] }[];
  activatables: Activatable[];
  abilities?: PermAbility[];
  impulse?: { i: number; name: string; cost: string; is_land: boolean; playable: boolean }[];
  graveyard?: { i: number; name: string; cost: string; mode: string; playable: boolean }[];
  exile_play?: { i: number; name: string; cost: string; is_land: boolean; playable: boolean }[];
  foretell_hand?: { i: number; name: string; playable: boolean }[];
  face_up?: FaceUpOpt[];
  gy_abilities?: { i: number; index: number; name: string; label: string; cost: string; playable: boolean }[];
  attack_targets: { index: number; name: string; life: number; pw_uid?: number }[];
  can_attack: boolean; can_end: boolean; can_undo?: boolean;
  mana?: number; mana_sources?: number;
};
type CardInfo = { art?: string; type?: string; oracle?: string };
type Inspect = {
  name: string; cost?: string; types?: string[]; power?: number | null;
  toughness?: number | null; keywords?: string[]; abilities?: string[];
  is_token?: boolean; subtypes?: string[];
};
type FaceUpOpt = { uid: number; name: string; cost: string; playable: boolean };
type NinjaOpt = { i: number; zone: string; name: string; cost: string; attackers: { uid: number; name: string; power: number; toughness: number }[] };
type CombatAtk = { uid: number; name: string; power: number; toughness: number; commander?: boolean; from: string; vs_pw?: string | null; flying?: boolean; blocked_by?: { uid: number; name: string; power: number; toughness: number }[] };
type Combat = {
  stage?: "declare" | "damage";
  attacking?: boolean;
  can_finish?: boolean;
  from: string; incoming_damage?: number;
  attackers: CombatAtk[];
  blockers?: { uid: number; name: string; power: number; toughness: number; can_block_flyers?: boolean }[];
  responses: { i: number; name: string; cost: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; modes?: ModeOpt[]; mode_pick?: number }[];
  abilities?: { uid: number; name: string; index: number; label: string; cost: string; target_spec?: string | null }[];
  gy_abilities?: { i: number; index: number; name: string; label: string; cost: string }[];
  face_up?: FaceUpOpt[];
  ninjutsu?: NinjaOpt[];
};
type Mulligan = { mulls: number; to_bottom: number; lands: number };
type ChoiceOpt = { i: number; name: string; is_land?: boolean; ok?: boolean };
type CardDetail = { name: string; cost: string; pt: string | null; type: string; keywords: string[]; is_land: boolean };
type Choice = { kind: string; prompt: string; options: ChoiceOpt[]; allow_none: boolean; card?: string; card_detail?: CardDetail | null };
type ReactState = {
  spell: string; from: string; kind?: string;
  responses: { i: number; name: string; cost: string; target_spec?: string | null }[];
  abilities: { uid: number; name: string; index: number; label: string; cost: string }[];
  gy_abilities: { i: number; index: number; name: string; label: string; cost: string }[];
};
type GameState = {
  turn: number; active: number; human_index: number; phase: string; attacked: boolean;
  winner: string | null; players: PlayerState[]; legal: Legal; combat: Combat | null;
  react?: ReactState | null;
  choice: Choice | null; mulligan: Mulligan | null; log: string[];
  ability_feed?: AbilityEvent[];
  opp_turns?: OppTurn[];
  card_briefs?: Record<string, CardDetail>;
  engine_error?: string;
};
type AbilityEvent = { turn: number; controller: string | null; card: string; kind: string };
type OppTurn = { turn: number; player: string; lines: string[] };

/* eslint-disable @typescript-eslint/no-explicit-any */
// Motor compartido entre visitas a /play (navegación del lado del cliente): al
// volver a la página no se baja ni se inicializa Pyodide de nuevo.
let SHARED_WORKER: Worker | null = null;
const SHARED_PENDING = new Map<number, { resolve: (v: string | null) => void; reject: (e: Error) => void }>();
let SHARED_MSG_ID = 0;

type AtkTarget = { index: number; name: string; life: number; pw_uid?: number };

// clave estable de un objetivo de ataque (jugador o planeswalker)
function atkKey(t?: AtkTarget): string {
  if (!t) return "";
  return t.pw_uid ? `pw:${t.pw_uid}` : `p:${t.index}`;
}

// objetivo elegido por clave; si ya no existe (murió/cayó), el primero de la lista
function atkTargetFor(at: AtkTarget[], key?: string): AtkTarget | undefined {
  return at.find((t) => atkKey(t) === key) || at[0];
}

export default function Play() {
  const reduce = useReducedMotion() ?? false;
  const [pickables, setPickables] = useState<Pickable[]>([]);
  const [mineId, setMineId] = useState<string>("");
  const [foeIds, setFoeIds] = useState<string[]>([]);
  const [level, setLevel] = useState("intermedio");
  const [seed, setSeed] = useState(1);

  // motor en un Web Worker: los turnos de los bots corren fuera del hilo de UI,
  // así la pantalla no se congela mientras resuelven.
  const workerRef = useRef<Worker | null>(null);
  const pendingRef = useRef(SHARED_PENDING);
  const [thinking, setThinking] = useState(false);   // el motor está procesando
  const gameRef = useRef(0);       // id de la partida: descarta respuestas de una anterior
  const [choiceHidden, setChoiceHidden] = useState(false);  // modal de decisión minimizado
  const [status, setStatus] = useState<string>("");   // texto de carga
  const [booting, setBooting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const countedRef = useRef(false);
  // contar la partida cuando termina (una sola vez por partida)
  useEffect(() => {
    if (state?.winner && !countedRef.current) {
      countedRef.current = true;
      try { bumpGamesPlayed(); } catch { /* storage off */ }
    }
    if (!state?.winner) countedRef.current = false;   // reset para la próxima
  }, [state?.winner]);
  const [picked, setPicked] = useState<Set<number>>(new Set());  // atacantes elegidos
  // atacante -> objetivo, por CLAVE estable ("p:<jugador>" / "pw:<uid>"): antes se
  // guardaba la posición en la lista y, si la lista cambiaba (muere un planeswalker,
  // cae un rival), el ataque iba a otro objetivo
  const [atkAssign, setAtkAssign] = useState<Record<number, string>>({});
  const [abilityToast, setAbilityToast] = useState<AbilityEvent | null>(null);
  const abilitySeen = useRef<number>(0);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [art, setArt] = useState<Record<string, string>>({});
  const [info, setInfo] = useState<Record<string, CardInfo>>({});
  const [inspect, setInspect] = useState<Inspect | null>(null);
  // glosario de habilidades: se baja la primera vez que se inspecciona una carta
  const [gloss, setGloss] = useState<GlossaryEntry[] | null>(null);
  useEffect(() => {
    if (inspect && !gloss) loadGlossary().then(setGloss);
  }, [inspect, gloss]);
  const [zoneView, setZoneView] = useState<{ title: string; names: string[] } | null>(null);
  const infoReq = useRef<Set<string>>(new Set());  // nombres ya pedidos
  const [assign, setAssign] = useState<Record<number, number>>({});  // bloqueador -> atacante
  const [targeting, setTargeting] = useState<{ kind: "cast" | "respond" | "ability" | "combat_ability"; i?: number; zone?: string; name: string; targets: TargetOpt[]; count: number; mode?: number; uid?: number; index?: number } | null>(null);
  const [modePick, setModePick] = useState<{ kind: "cast" | "respond"; i?: number; zone?: string; name: string; modes: ModeOpt[]; pick?: number } | null>(null);
  const [modeSel, setModeSel] = useState<number[]>([]);  // modos elegidos (choose two)
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

  // aviso en pantalla cuando se activa/dispara una habilidad
  useEffect(() => {
    const feed = state?.ability_feed || [];
    if (feed.length > abilitySeen.current) {
      const ev = feed[feed.length - 1];
      abilitySeen.current = feed.length;
      setAbilityToast(ev);
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setAbilityToast(null), 3600);
    }
    if (feed.length < abilitySeen.current) abilitySeen.current = feed.length; // nueva partida
  }, [state]);

  // Escape cierra los modales informativos/opcionales (no las decisiones forzadas)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (inspect) setInspect(null);
      else if (targeting) setTargeting(null);
      else if (modePick) { setModePick(null); setModeSel([]); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inspect, targeting, modePick]);

  // el worker del motor NO se termina al salir de la página: queda compartido
  // (Pyodide + el código del motor ya cargados) para la próxima visita a /play
  useEffect(() => () => { workerRef.current = null; }, []);

  // auto-scroll del relato a la última jugada (la más nueva está abajo)
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state?.log]);

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

  function getWorker(): Worker {
    if (workerRef.current) return workerRef.current;
    if (SHARED_WORKER) {
      workerRef.current = SHARED_WORKER;
      return SHARED_WORKER;
    }
    const w = new Worker(new URL("./engine.worker.ts", import.meta.url));
    w.onmessage = (e: MessageEvent) => {
      const { id, ok, result, error } = e.data || {};
      const p = pendingRef.current.get(id);
      if (!p) return;
      pendingRef.current.delete(id);
      if (ok) p.resolve(result);
      else p.reject(new Error(error || "error del motor"));
    };
    w.onerror = (e) => {
      // rechazar todo lo pendiente ante un error del worker
      for (const [, p] of pendingRef.current) p.reject(new Error(e.message || "error del worker"));
      pendingRef.current.clear();
    };
    SHARED_WORKER = w;
    workerRef.current = w;
    return w;
  }

  function callWorker(type: string, payload?: object): Promise<string | null> {
    const w = getWorker();
    const id = ++SHARED_MSG_ID;
    return new Promise<string | null>((resolve, reject) => {
      pendingRef.current.set(id, { resolve, reject });
      w.postMessage({ id, type, payload: payload || {} });
    });
  }

  async function ensureEngine() {
    setStatus("Preparando el motor… la primera vez puede tardar unos segundos.");
    try {
      await callWorker("init");
    } finally {
      setStatus("");
    }
  }

  // aplica un estado nuevo del motor; si trae un error, lo muestra sin perder la partida
  function applyState(raw: string | null) {
    if (!raw) return;
    const st = JSON.parse(raw) as GameState;
    setState(st);
    setChoiceHidden(false);
    setError(st.engine_error
      ? `El motor tuvo un error (${st.engine_error}). La partida sigue: podés deshacer, seguir jugando o empezar una nueva.`
      : null);
  }

  function newGame() {
    gameRef.current++;           // una acción en curso de la partida vieja se descarta
    setState(null); setError(null); setChoiceHidden(false);
  }

  function toggleFoe(id: string) {
    setFoeIds((f) => (f.includes(id) ? f.filter((x) => x !== id) : f.length < 3 ? [...f, id] : f));
  }

  async function start() {
    setError(null); setBooting(true);
    const gid = ++gameRef.current;
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

      await ensureEngine();
      const raw = await callWorker("new_game", {
        specs: JSON.stringify(specs), datamap: JSON.stringify(datamap), seed, level,
      });
      if (gid !== gameRef.current) return;      // el usuario ya salió de esta partida
      applyState(raw);
      setPicked(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBooting(false); }
  }

  async function doAct(kind: string, arg: object = {}) {
    if (!workerRef.current || thinking) return;   // una acción a la vez (motor de 1 hilo)
    const gid = gameRef.current;
    setThinking(true);
    try {
      const raw = await callWorker("act", { kind, arg: JSON.stringify(arg) });
      if (gid !== gameRef.current) return;   // "Nueva partida" mientras pensaba: descartar
      applyState(raw);
      if (kind === "attack" || kind === "end") setPicked(new Set());
      if (kind === "defend") setAssign({});
      if (kind === "mulligan" || kind === "keep") setBottom([]);
    } catch (e) {
      if (gid !== gameRef.current) return;
      setError((e instanceof Error ? e.message : String(e)) +
        " — se recargó el estado de la partida.");
      // resincronizar con lo que el motor tiene de verdad
      try { applyState(await callWorker("state")); } catch { /* el worker murió */ }
    } finally {
      setThinking(false);
    }
  }

  function togglePick(uid: number) {
    setPicked((s) => { const n = new Set(s); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });
  }

  async function exportGame(fmt: "json" | "txt") {
    if (!workerRef.current) return;
    const raw = await callWorker("export");
    if (!raw) return;
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

  function inspectCard(x: { name: string; cost?: string; types?: string[]; power?: number | null; toughness?: number | null; keywords?: string[]; abilities?: string[]; is_token?: boolean; subtypes?: string[] }) {
    setInspect({
      name: x.name, cost: x.cost, types: x.types, power: x.power,
      toughness: x.toughness, keywords: x.keywords, abilities: x.abilities,
      is_token: x.is_token, subtypes: x.subtypes,
    });
  }

  // lanzar: si es modal, elegir modo; si necesita objetivo, abrir el selector
  function castCard(c: CastOpt) {
    if (c.modes && c.modes.length > 0) {
      setModeSel([]);
      setModePick({ kind: "cast", i: c.i, zone: c.zone, name: c.name, modes: c.modes, pick: c.mode_pick || 1 });
    } else if (c.target_spec && c.targets && c.targets.length > 0) {
      setTsel([]);
      setTargeting({ kind: "cast", i: c.i, zone: c.zone, name: c.name, targets: c.targets, count: c.target_count || 1 });
    } else {
      doAct("cast", { i: c.i, zone: c.zone });
    }
  }
  function respondCard(r: { i: number; name: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[]; modes?: ModeOpt[]; mode_pick?: number }) {
    if (r.modes && r.modes.length > 0) {
      setModeSel([]);
      setModePick({ kind: "respond", i: r.i, name: r.name, modes: r.modes, pick: r.mode_pick || 1 });
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
  // "choose two/more": acumular modos y confirmar (objetivos se autoeligen, aprox)
  function toggleMode(m: ModeOpt) {
    setModeSel((s) => s.includes(m.i) ? s.filter((x) => x !== m.i) : [...s, m.i]);
  }
  function confirmModes() {
    if (!modePick) return;
    const base = modePick;
    const sel = [...modeSel].sort((a, b) => a - b);
    setModePick(null);
    setModeSel([]);
    if (sel.length > 0) doAct(base.kind, { i: base.i, zone: base.zone, mode: sel });
  }
  function useAbility(uid: number, ab: AbilityOpt) {
    if (ab.target_spec && ab.targets && ab.targets.length > 0) {
      setTsel([]);
      setTargeting({ kind: "ability", uid, index: ab.i, name: ab.label, targets: ab.targets, count: ab.target_count || 1 });
    } else {
      doAct("ability", { uid, index: ab.i });
    }
  }
  // habilidad activada durante defensa/daño: con objetivo abre el selector manual
  function useCombatAbility(ab: { uid: number; index: number; label: string; target_spec?: string | null; target_count?: number; targets?: TargetOpt[] }) {
    if (ab.target_spec && ab.targets && ab.targets.length > 0) {
      setTsel([]);
      setTargeting({ kind: "combat_ability", uid: ab.uid, index: ab.index, name: ab.label, targets: ab.targets, count: ab.target_count || 1 });
    } else {
      doAct("combat_ability", { uid: ab.uid, index: ab.index });
    }
  }
  function dispatchTargets(uids: number[]) {
    if (!targeting) return;
    if (targeting.kind === "ability") {
      doAct("ability", { uid: targeting.uid, index: targeting.index, target_uids: uids });
    } else if (targeting.kind === "combat_ability") {
      doAct("combat_ability", { uid: targeting.uid, index: targeting.index, target_uids: uids });
    } else {
      doAct(targeting.kind, { i: targeting.i, zone: targeting.zone, target_uids: uids, mode: targeting.mode });
    }
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
      {thinking && (
        <div aria-live="polite" style={{
          position: "fixed", top: 12, right: 12, zIndex: 50,
          display: "inline-flex", alignItems: "center", gap: 6,
          background: "var(--panel-2)", border: "1px solid var(--border)",
          borderRadius: 999, padding: "5px 12px", fontSize: ".8rem",
          color: "var(--muted)", boxShadow: "var(--shadow)",
        }}>
          <Icon name="hourglass" size={13} /> pensando…
        </div>
      )}
      <AnimatePresence>
        {abilityToast && (
          <motion.div className="ability-toast" role="status"
            initial={reduce ? false : { opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -12 }}
            transition={{ type: "spring", stiffness: 400, damping: 28 }}>
            <Icon name="sparkles" size={16} />
            <span>
              <b>{abilityToast.card}</b>: {abilityToast.kind}
              {abilityToast.controller ? <span className="muted"> — {abilityToast.controller}</span> : null}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
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
            <label style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              Código de partida
              <Help label="código de partida" text="Fija el azar de la partida: con el mismo código y los mismos decks sale exactamente la misma partida. Cambialo para ver otra (o compartilo para que otra persona vea la misma)." />
              &nbsp;
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
              <motion.span className="turnbadge" key={state.turn}
                initial={reduce ? false : { scale: 1.3, backgroundColor: "rgba(224,163,90,.35)" }}
                animate={{ scale: 1, backgroundColor: "rgba(255,255,255,0)" }}
                transition={{ type: "spring", stiffness: 320, damping: 22 }}>Turno {state.turn}</motion.span>
              <span className="label">
                {state.phase === "over" ? "Partida terminada"
                  : myTurn ? "Tu turno · jugá tus cartas" : `Juega ${state.players[state.active]?.name}`}
              </span>
              {myTurn && legal && legal.mana != null && (
                <span className="mana-pool" title="maná disponible (fuentes sin girar)">
                  <Icon name="sparkles" size={13} /> {legal.mana} maná
                  <span className="muted"> · {legal.mana_sources} fuentes</span>
                </span>
              )}
              <button className="ghost" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5 }} onClick={newGame}>
                <Icon name="undo" size={14} /> Nueva partida
              </button>
            </div>
            {error && (
              <p className="err" role="alert" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Icon name="warning" size={15} /> <span style={{ flex: 1 }}>{error}</span>
                <button className="inspect-x" style={{ position: "static" }} aria-label="Cerrar aviso" title="Cerrar" onClick={() => setError(null)}><Icon name="x" size={14} /></button>
              </p>
            )}

            {myTurn && state.opp_turns && state.opp_turns.length > 0 && (
              <div className="opp-recap">
                <div className="opp-recap-head">
                  <Icon name="scroll" size={13} /> Mientras no jugabas — turnos rivales
                </div>
                {state.opp_turns.map((ot, k) => (
                  <div className="opp-turn" key={k}>
                    <b>Turno {ot.turn} · {ot.player}</b>
                    <ul>
                      {ot.lines.length === 0
                        ? <li className="muted">pasó sin jugar</li>
                        : ot.lines.map((l, j) => <li key={j}>{l}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            )}

            <div className="seats" data-n={state.players.length}>
              {state.players.map((p, i) => (
                <Seat
                  key={p.name} p={p} active={i === state.active} art={art} reduce={reduce}
                  selectableUids={myTurn && i === meIdx && !state.attacked ? attackableUids : undefined}
                  selectedUids={i === meIdx ? picked : undefined}
                  onCard={i === meIdx ? togglePick : undefined}
                  onInspect={(pm: Perm) => inspectCard(pm)}
                  onZone={(title, names) => setZoneView({ title, names })}
                />
              ))}
            </div>

            {state.winner && (
              <motion.p className="win-line"
                initial={reduce ? false : { scale: 0.7, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 300, damping: 16 }}>
                <Icon name="trophy" size={18} /> {state.winner === "EMPATE" ? "Empate (límite de turnos)." : <>Gana <b>{state.winner}</b>.</>}</motion.p>
            )}
          </div>

          {state.combat && state.combat.stage !== "damage" && (
            <motion.div className="card defense"
              initial={reduce ? false : { opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}>
              <h2 className="def-title">
                <motion.span className="alert"
                  animate={reduce ? {} : { scale: [1, 1.15, 1] }}
                  transition={reduce ? undefined : { repeat: Infinity, duration: 1.1 }}><Icon name="swords" size={18} /></motion.span>
                {state.combat.from} te ataca · {state.combat.incoming_damage} de daño en camino
              </h2>
              <div className="def-attackers">
                {state.combat.attackers.map((a) => (
                  <div key={a.uid} className={`atk-chip ${assign && Object.values(assign).includes(a.uid) ? "blocked" : ""}`}>
                    {a.commander ? <Icon name="crown" size={13} /> : null}{a.commander ? " " : ""}{a.name} <b>{a.power}/{a.toughness}</b>
                    {a.vs_pw ? <span className="muted" style={{ color: "var(--accent)" }}> → {a.vs_pw} (planeswalker)</span> : null}
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

              {(state.combat.abilities?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Activar habilidad:</span>
                  {(state.combat.abilities ?? []).map((ab) => (
                    <button key={ab.uid + "-" + ab.index} className="ghost" onClick={() => useCombatAbility(ab)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="sparkles" size={13} /> {ab.name}: {ab.label}{ab.target_spec ? <Icon name="target" size={12} /> : null} <span className="muted">{ab.cost}</span>
                    </button>
                  ))}
                </div>
              )}
              {(state.combat.gy_abilities?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Desde el cementerio:</span>
                  {(state.combat.gy_abilities ?? []).map((ab) => (
                    <button key={"gy" + ab.i + "-" + ab.index} className="ghost" onClick={() => doAct("combat_gy_ability", { i: ab.i, index: ab.index })} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="grave" size={13} /> {ab.name}: {ab.label} <span className="muted">{ab.cost}</span>
                    </button>
                  ))}
                </div>
              )}
              {(state.combat.face_up?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Dar vuelta:</span>
                  {(state.combat.face_up ?? []).map((f) => (
                    <button key={"dfu" + f.uid} className="ghost" disabled={!f.playable}
                      onClick={() => doAct("face_up", { uid: f.uid })}
                      style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="refresh" size={13} /> {f.name} <span className="muted">{f.cost}</span>
                    </button>
                  ))}
                </div>
              )}

              {(state.combat.blockers?.length ?? 0) > 0 ? (
                <div className="def-blockers">
                  <span className="act-label">Tus bloqueadores:</span>
                  {(state.combat.blockers ?? []).map((b) => (
                    <div key={b.uid} className="blk-row">
                      <span>{b.name} <b>{b.power}/{b.toughness}</b>{b.can_block_flyers ? <span className="muted"> · puede bloquear voladores</span> : null}</span>
                      <select value={assign[b.uid] ?? ""}
                        onChange={(e) => setAssign((m) => {
                          const v = e.target.value;
                          const n = { ...m };
                          if (v === "") delete n[b.uid]; else n[b.uid] = Number(v);
                          return n;
                        })}
                        style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 8px" }}>
                        <option value="">No bloquea</option>
                        {state.combat!.attackers
                          .filter((a) => b.can_block_flyers || !a.flying)   // sin volar/alcance no puede bloquear voladores
                          .map((a) => (
                          <option key={a.uid} value={a.uid}>bloquea a {a.name} ({a.power}/{a.toughness}){a.flying ? " ✦vuela" : ""}</option>
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

          {state.combat && state.combat.stage === "damage" && (
            <motion.div className="card defense"
              initial={reduce ? false : { opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}>
              <h2 className="def-title">
                <Icon name="swords" size={18} />{" "}
                {state.combat.attacking ? "Tu ataque — paso de daño" : "Bloqueos declarados — paso de daño"}
              </h2>
              <div className="def-attackers">
                {state.combat.attackers.map((a) => (
                  <div key={a.uid} className="atk-chip">
                    {a.name} <b>{a.power}/{a.toughness}</b>
                    {a.vs_pw ? <span className="muted" style={{ color: "var(--accent)" }}> → {a.vs_pw}</span> : null}
                    {a.blocked_by && a.blocked_by.length > 0
                      ? <span className="muted"> · bloqueado por {a.blocked_by.map((b) => `${b.name} (${b.power}/${b.toughness})`).join(", ")}</span>
                      : <span className="muted"> · sin bloquear</span>}
                  </div>
                ))}
              </div>

              {state.combat.responses.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Responder antes del daño (instantáneo):</span>
                  {state.combat.responses.map((r) => (
                    <button key={r.i} className="ghost" onClick={() => respondCard(r)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="bolt" size={13} /> {r.name}{r.target_spec ? <Icon name="target" size={12} /> : null} <span className="muted">{r.cost}</span>
                    </button>
                  ))}
                </div>
              )}

              {(state.combat.abilities?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Activar habilidad:</span>
                  {(state.combat.abilities ?? []).map((ab) => (
                    <button key={ab.uid + "-" + ab.index} className="ghost" onClick={() => useCombatAbility(ab)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="sparkles" size={13} /> {ab.name}: {ab.label}{ab.target_spec ? <Icon name="target" size={12} /> : null} <span className="muted">{ab.cost}</span>
                    </button>
                  ))}
                </div>
              )}
              {(state.combat.gy_abilities?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Desde el cementerio:</span>
                  {(state.combat.gy_abilities ?? []).map((ab) => (
                    <button key={"gy" + ab.i + "-" + ab.index} className="ghost" onClick={() => doAct("combat_gy_ability", { i: ab.i, index: ab.index })} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="grave" size={13} /> {ab.name}: {ab.label} <span className="muted">{ab.cost}</span>
                    </button>
                  ))}
                </div>
              )}

              {(state.combat.ninjutsu?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Ninjutsu (devolvé un atacante sin bloquear):</span>
                  {(state.combat.ninjutsu ?? []).flatMap((n) => n.attackers.map((a) => (
                    <button key={"nj" + n.zone + n.i + "-" + a.uid} className="ghost"
                      onClick={() => doAct("ninjutsu", { i: n.i, zone: n.zone, attacker: a.uid })}
                      style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="swords" size={13} /> {n.name} <span className="muted">{n.cost}</span> ⇄ {a.name} ({a.power}/{a.toughness})
                    </button>
                  )))}
                </div>
              )}
              {(state.combat.face_up?.length ?? 0) > 0 && (
                <div className="act-block">
                  <span className="act-label">Dar vuelta:</span>
                  {(state.combat.face_up ?? []).map((f) => (
                    <button key={"cfu" + f.uid} className="ghost" disabled={!f.playable}
                      onClick={() => doAct("face_up", { uid: f.uid })}
                      style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="refresh" size={13} /> {f.name} <span className="muted">{f.cost}</span>
                    </button>
                  ))}
                </div>
              )}

              <div className="act-block">
                <button className="go" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                  onClick={() => doAct("finish_combat", {})}>
                  <Icon name="check" size={14} /> Aplicar daño
                </button>
              </div>
              <p className="muted" style={{ fontSize: ".8rem" }}>
                Última ventana para lanzar instantáneos antes de que se resuelva el daño de combate.
              </p>
            </motion.div>
          )}

          {state.react && (
            <motion.div className="card def-panel"
              initial={reduce ? false : { opacity: 0, y: -10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 380, damping: 26 }}>
              <h2 style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                <Icon name="bolt" size={18} /> {state.react.from} {state.react.kind === "ability" || state.react.kind === "trigger" ? "activa" : "lanza"} <b>{state.react.spell}</b> — ¿respondés?
              </h2>
              {state.react.responses.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Responder (instantáneo):</span>
                  {state.react.responses.map((r) => (
                    <button key={"rr" + r.i} className="ghost" onClick={() => doAct("react", { action: "cast", i: r.i })}
                      style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Icon name="bolt" size={13} /> {r.name}{r.target_spec ? <Icon name="target" size={12} /> : null} <span className="muted">{r.cost}</span>
                    </button>
                  ))}
                </div>
              )}
              {state.react.abilities.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Habilidades:</span>
                  {state.react.abilities.map((a) => (
                    <button key={"ra" + a.uid + "-" + a.index} className="ghost pw-ab"
                      onClick={() => doAct("react", { action: "ability", uid: a.uid, index: a.index })}>
                      <b>{a.name}</b> <span className="muted">{a.cost}</span> <em className="pw-txt">{a.label}</em>
                    </button>
                  ))}
                </div>
              )}
              {state.react.gy_abilities.length > 0 && (
                <div className="act-block">
                  <span className="act-label">Del cementerio:</span>
                  {state.react.gy_abilities.map((a) => (
                    <button key={"rg" + a.i + "-" + a.index} className="ghost pw-ab"
                      onClick={() => doAct("react", { action: "gy_ability", i: a.i, index: a.index })}>
                      <Icon name="grave" size={12} /> <b>{a.name}</b> <span className="muted">{a.cost}</span> <em className="pw-txt">{a.label}</em>
                    </button>
                  ))}
                </div>
              )}
              <div className="act-block">
                <button className="go" onClick={() => doAct("react", {})} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <Icon name="skip-forward" size={14} /> Pasar (dejar que resuelva)
                </button>
              </div>
              <p className="muted" style={{ fontSize: ".8rem" }}>
                Un rival lanzó un hechizo y podés responder antes de que resuelva
                (contrahechizo, remoción a velocidad de instante, o pasar).
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
                          role="button" tabIndex={0}
                          aria-pressed={m.to_bottom > 0 ? sel : undefined}
                          aria-label={m.to_bottom > 0 ? `${hc.name}${sel ? " (al fondo)" : ""}` : `Ver ${hc.name}`}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault(); (e.currentTarget as HTMLElement).click();
                            }
                          }}
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
            // casts alternativos (dorso de DFC modal, aventura, evoke, dash, ciclar…)
            const altCasts = (legal?.casts || []).filter((c) => c.zone !== "hand" && c.zone !== "command");
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
                          {castOpt && castOpt.castable === false
                            ? <em className="pw-txt" title={castOpt.reason || ""}>({castOpt.reason || "no jugable"})</em>
                            : castOpt && <button className="go tiny" onClick={() => castCard(castOpt)} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                                Lanzar{castOpt.target_spec ? <Icon name="target" size={12} /> : null}
                              </button>}
                        </div>
                      </div>
                    );
                  })}
                  {hand.length === 0 && <span className="muted">mano vacía</span>}
                </div>

                {altCasts.length > 0 && (
                  <div className="act-block">
                    <span className="act-label">Alternativas:</span>
                    {altCasts.map((c, k) => (
                      <button key={"alt" + k} className="ghost" onClick={() => castCard(c)}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name={c.zone === "back" ? "cards" : "cards"} size={12} />
                        Lanzar {c.name}{c.target_spec ? <Icon name="target" size={12} /> : null}{" "}
                        <span className="muted">{c.cost}</span>
                      </button>
                    ))}
                  </div>
                )}

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

                {legal && (legal.impulse?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Exilio (jugable este turno):</span>
                    {legal.impulse!.map((im) => (
                      <button key={"imp" + im.i} className="ghost pw-ab"
                        disabled={!im.playable}
                        onClick={() => doAct("cast", { i: im.i, zone: "impulse" })}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name={im.is_land ? "land" : "cards"} size={12} />
                        <b>{im.name}</b> <span className="muted">{im.cost}</span>
                        {!im.playable ? <em className="pw-txt">sin maná / tierra ya jugada</em> : null}
                      </button>
                    ))}
                  </div>
                )}

                {legal && (legal.graveyard?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Cementerio (jugable):</span>
                    {legal.graveyard!.map((gy) => (
                      <button key={"gy" + gy.i} className="ghost pw-ab"
                        disabled={!gy.playable}
                        onClick={() => doAct("cast", { i: gy.i, zone: "graveyard" })}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name="cards" size={12} />
                        <b>{gy.name}</b> <span className="muted">{gy.cost}</span>
                        <em className="pw-txt">{gy.mode}</em>
                        {!gy.playable ? <em className="pw-txt">sin maná</em> : null}
                      </button>
                    ))}
                  </div>
                )}

                {legal && (legal.exile_play?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Exilio (jugable):</span>
                    {legal.exile_play!.map((ex) => (
                      <button key={"exp" + ex.i} className="ghost pw-ab"
                        disabled={!ex.playable}
                        onClick={() => doAct("cast", { i: ex.i, zone: "exile" })}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name={ex.is_land ? "land" : "cards"} size={12} />
                        <b>{ex.name}</b> <span className="muted">{ex.cost}</span>
                        {!ex.playable ? <em className="pw-txt">sin maná</em> : null}
                      </button>
                    ))}
                  </div>
                )}

                {legal && (legal.gy_abilities?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Habilidades del cementerio:</span>
                    {legal.gy_abilities!.map((ga) => (
                      <button key={"gya" + ga.i + "-" + ga.index} className="ghost pw-ab"
                        disabled={!ga.playable}
                        onClick={() => doAct("activate_gy", { i: ga.i, index: ga.index })}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name="grave" size={12} />
                        <b>{ga.name}</b> <span className="muted">{ga.cost}</span>
                        <em className="pw-txt">{ga.label}</em>
                        {!ga.playable ? <em className="pw-txt">sin maná</em> : null}
                      </button>
                    ))}
                  </div>
                )}

                {legal && (legal.foretell_hand?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Predecir (foretell, {"{2}"}):</span>
                    {legal.foretell_hand!.map((f) => (
                      <button key={"ft" + f.i} className="ghost pw-ab"
                        disabled={!f.playable}
                        onClick={() => doAct("foretell", { i: f.i })}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name="cards" size={12} />
                        <b>{f.name}</b>
                        {!f.playable ? <em className="pw-txt">sin maná</em> : null}
                      </button>
                    ))}
                  </div>
                )}

                {legal && (legal.face_up?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Dar vuelta (boca abajo):</span>
                    {legal.face_up!.map((f) => (
                      <button key={"fu" + f.uid} className="ghost pw-ab"
                        disabled={!f.playable}
                        onClick={() => doAct("face_up", { uid: f.uid })}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <Icon name="refresh" size={12} />
                        <b>{f.name}</b> <span className="muted">{f.cost}</span>
                        {!f.playable ? <em className="pw-txt">sin maná</em> : null}
                      </button>
                    ))}
                  </div>
                )}

                {legal && (legal.abilities?.length || 0) > 0 && (
                  <div className="act-block">
                    <span className="act-label">Habilidades (pagar maná):</span>
                    {legal.abilities!.map((pm) =>
                      pm.abilities.map((ab) => (
                        <button key={pm.uid + "-a" + ab.i} className="ghost pw-ab"
                          disabled={ab.playable === false}
                          onClick={() => useAbility(pm.uid, ab)}>
                          <b>{pm.name}</b> <span className="muted" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>{ab.cost}{ab.tap ? <Icon name="refresh" size={11} /> : null}{ab.target_spec ? <Icon name="target" size={11} /> : null}</span>
                          <em className="pw-txt">{ab.label}</em>
                          {ab.playable === false && ab.reason ? <em className="pw-txt">({ab.reason})</em> : null}
                        </button>
                      ))
                    )}
                  </div>
                )}

                {(legal?.attack_targets?.length || 0) > 1 && picked.size > 0 && (
                  <div className="act-block" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
                    <span className="act-label">A quién ataca cada criatura (rivales o sus planeswalkers):</span>
                    {[...picked].map((uid) => {
                      const atk = legal!.attackers.find((a) => a.uid === uid);
                      const def = atkKey(legal!.attack_targets[0]);
                      const cur = legal!.attack_targets.some((t) => atkKey(t) === atkAssign[uid])
                        ? atkAssign[uid] : def;
                      return (
                        <label key={"asg" + uid} className="muted" style={{ fontSize: ".82rem", display: "flex", alignItems: "center", gap: 6 }}>
                          <Icon name="swords" size={12} />
                          <b style={{ color: "#eef1f6" }}>{atk?.name ?? "?"}</b> →{" "}
                          <select value={cur}
                            onChange={(e) => setAtkAssign((m) => ({ ...m, [uid]: e.target.value }))}>
                            {legal!.attack_targets.map((t) => (
                              <option key={atkKey(t)} value={atkKey(t)}>{t.name} {t.pw_uid ? `(${t.life}⬧)` : `(${t.life}♥)`}</option>
                            ))}
                          </select>
                        </label>
                      );
                    })}
                  </div>
                )}
                {picked.size > 0 && (() => {
                  const at = legal?.attack_targets || [];
                  const pickedAtk = [...picked]
                    .map((uid) => legal!.attackers.find((a) => a.uid === uid))
                    .filter((a): a is NonNullable<typeof a> => !!a);
                  const dmgByPos: Record<number, number> = {};
                  for (const a of pickedAtk) {
                    const t = atkTargetFor(at, atkAssign[a.uid]);
                    const pos = Math.max(0, at.indexOf(t as (typeof at)[number]));
                    dmgByPos[pos] = (dmgByPos[pos] || 0) + effDamage(a);
                  }
                  return (
                    <div className="act-block atk-summary" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
                      <span className="act-label">Atacantes y habilidades:</span>
                      <div className="atk-chips">
                        {pickedAtk.map((a) => (
                          <span key={a.uid} className="atk-chip">
                            <b>{a.name}</b> <span className="atk-pt">{a.power}/{a.toughness}</span>
                            {(a.keywords || []).filter((k) => KW_SHORT[k]).map((k) => (
                              <span key={k} className="atk-kw" title={k}>{KW_SHORT[k]}</span>
                            ))}
                          </span>
                        ))}
                      </div>
                      <span className="act-label">Daño que enviás:</span>
                      <div className="atk-dmg">
                        {Object.entries(dmgByPos).map(([pos, dmg]) => {
                          const t = at[Number(pos)] || at[0];
                          const lethal = !!t && !t.pw_uid && dmg >= t.life;
                          return (
                            <span key={pos} className={`dmg-to ${lethal ? "lethal" : ""}`}>
                              <Icon name="swords" size={12} /> {dmg} a <b>{t?.name ?? "rival"}</b>
                              {t ? <span className="muted"> ({t.pw_uid ? `${t.life}⬧` : `${t.life}♥`}{lethal ? " · letal" : ""})</span> : null}
                            </span>
                          );
                        })}
                      </div>
                      <span className="hint-muted" style={{ fontSize: ".72rem" }}>
                        Daño sin contar bloqueos (el rival puede bloquear). Doble golpe cuenta ×2.
                      </span>
                    </div>
                  );
                })()}
                <div className="act-block">
                  <button className="go" onClick={() => {
                    const at = legal?.attack_targets || [];
                    const tgt = (key?: string) => {
                      const t = atkTargetFor(at, key);
                      return { target: t?.index, pw: t?.pw_uid };
                    };
                    if (at.length > 1) {
                      doAct("attack", { assign: [...picked].map((uid) => ({ uid, ...tgt(atkAssign[uid]) })) });
                    } else {
                      const t0 = tgt();
                      doAct("attack", { uids: [...picked], target: t0.target, target_pw: t0.pw });
                    }
                    setAtkAssign({});
                  }}
                    disabled={!legal?.can_attack || picked.size === 0}
                    style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <Icon name="swords" size={15} /> Atacar {picked.size > 0 ? `(${picked.size})` : ""}
                  </button>
                  <button className="ghost" onClick={() => doAct("undo")} disabled={!legal?.can_undo} title="Deshacer la última jugada de este turno" style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><Icon name="undo" size={14} /> Deshacer</button>
                  <button className="ghost" onClick={() => doAct("end")} disabled={!legal?.can_end} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>Terminar turno <Icon name="skip-forward" size={14} /></button>
                </div>
                <p className="muted" style={{ fontSize: ".8rem" }}>
                  Tocá una carta para ver sus habilidades. Elegí criaturas tocándolas
                  en tu tablero para atacar y, si hay más de un rival, podés repartir
                  tus atacantes entre varios rivales a la vez.
                  Cuando un rival te ataque, vos elegís los bloqueos y podés responder
                  con instantáneos.
                </p>
              </div>
            );
          })()}

          <div className="card">
            <h2>Relato</h2>
            <div className="log" ref={logRef}>
              {groupLog(state.log || []).map((g, gi) => (
                <div key={gi} className="log-turn">
                  {g.head && <div className="log-turn-head">{g.head}</div>}
                  {g.lines.map((ln, li) => <div key={li} className="log-line">{ln}</div>)}
                </div>
              ))}
            </div>
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
            <h3><Icon name="sparkles" size={17} /> {modePick.name} — {(modePick.pick || 1) > 1 ? `elegí ${modePick.pick} modos` : "elegí un modo"}</h3>
            <p className="muted" style={{ marginTop: 2 }}>
              {(modePick.pick || 1) > 1 ? `Tocá los modos que querés (${modeSel.length}/${modePick.pick}):` : "¿Qué querés que haga?"}
            </p>
            <div className="target-list">
              {modePick.modes.map((m) => {
                const multi = (modePick.pick || 1) > 1;
                const on = modeSel.includes(m.i);
                return (
                  <button key={m.i} className={`ghost ${on ? "on" : ""}`}
                    onClick={() => multi ? toggleMode(m) : chooseMode(m)}
                    style={{ textAlign: "left", display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {multi ? <Icon name={on ? "check-circle" : "plus"} size={13} /> : null}
                    {m.label}{m.target_spec ? <Icon name="target" size={12} /> : null}
                  </button>
                );
              })}
            </div>
            {(modePick.pick || 1) > 1 && (
              <button className="go" style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 6 }}
                disabled={modeSel.length !== modePick.pick}
                onClick={confirmModes}><Icon name="check" size={14} /> Confirmar</button>
            )}
          </div>
        </div>
      )}

      {targeting && (
        <div className="inspect-back" onClick={() => setTargeting(null)}>
          <div className="inspect" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
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
                    {art[t.name]
                      ? <span className="choice-thumb" style={{ backgroundImage: `url(${art[t.name]})` }} />
                      : (targeting.count > 1 ? <Icon name={sel ? "check-circle" : "plus"} size={13} /> : null)}
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

      {state?.phase === "choose" && state.choice && choiceHidden && (
        <button className="go" onClick={() => setChoiceHidden(false)}
          style={{ position: "fixed", bottom: 16, left: "50%", transform: "translateX(-50%)", zIndex: 50,
                   display: "inline-flex", alignItems: "center", gap: 6, boxShadow: "var(--shadow)" }}>
          <Icon name="book" size={14} /> Tenés una decisión pendiente · Abrir
        </button>
      )}

      {state?.phase === "choose" && state.choice && !choiceHidden && (() => {
        const ch = state.choice;
        const isCardPick = ch.options.some((o) => o.is_land !== undefined);
        const titles: Record<string, string> = {
          scry: "Scry", surveil: "Surveil", fateseal: "Fateseal (biblioteca rival)",
          explore: "Explorar", search: "Buscar en la biblioteca",
          look_take: "Mirar y elegir", reveal_land: "Revelar y elegir",
          etb_target: "Elegí un objetivo", creature_type: "Elegí un tipo de criatura",
          discard: "Descartar", may: "¿Querés hacerlo?",
          legend: "Regla de legendarios", x: "Elegí X",
          reanimate: "Revivir desde el cementerio", exile_pick: "Elegí una carta del exilio",
          cascade_target: "Cascada: elegí el objetivo",
          gy_shuffle: "Barajar cartas del cementerio",
        };
        // Una línea que EXPLICA la mecánica (sobre todo la jerga de MTG), debajo del
        // título. El `prompt` del motor da el detalle puntual (qué carta, cuántas faltan).
        const hints: Record<string, string> = {
          scry: "Mirá las cartas de arriba de tu biblioteca y mandá cada una arriba o al fondo.",
          surveil: "Mirá las cartas de arriba y mandá cada una arriba o al cementerio.",
          fateseal: "Mirá arriba de la biblioteca del rival y decidís si la dejás arriba o al fondo.",
          explore: "Si la carta de arriba es tierra va a tu mano; si no, la criatura crece +1/+1.",
          search: "Elegí una carta de tu biblioteca; después se baraja.",
          legend: "Tenés dos legendarias iguales: conservá una, la otra va al cementerio.",
          x: "Elegí cuánto maná pagar por X.",
          etb_target: "Elegí a qué apunta la habilidad.",
          cascade_target: "Cascada: elegí a qué carta revelada apuntar.",
          gy_shuffle: "Elegí cartas de tu cementerio para barajar de vuelta a la biblioteca.",
          look_take: "Mirá las cartas reveladas y llevate la que elijas.",
          reveal_land: "Elegí una de las cartas reveladas.",
          reanimate: "Elegí una carta del cementerio para ponerla en el campo de batalla.",
          exile_pick: "Elegí una carta del exilio.",
          creature_type: "Elegí un tipo de criatura (p. ej. Zombi, Elfo, Dragón).",
          discard: "Elegí qué carta mandar al cementerio.",
          may: "Decidí si querés aplicar el efecto opcional.",
        };
        const title = titles[ch.kind] || "Elegí una carta";
        const hint = hints[ch.kind];
        const noneLabel = ch.kind === "etb_target" ? "No elegir ninguno"
          : ch.kind === "gy_shuffle" ? "Ninguna más"
          : "No llevarme ninguna";
        return (
          <div className="inspect-back" role="dialog" aria-modal="true" aria-label={title}>
            <div className="inspect" onClick={(e) => e.stopPropagation()}>
              {/* minimizar (no resuelve): deja ver el tablero y llegar a "Nueva partida" */}
              <button className="inspect-x" aria-label="Ocultar decisión" title="Ocultar (mirar el tablero)" onClick={() => setChoiceHidden(true)}><Icon name="x" size={16} /></button>
              <h3><Icon name="book" size={17} /> {title}</h3>
              {hint && <p className="muted" style={{ marginTop: 2, fontSize: ".82rem", opacity: .85 }}>{hint}</p>}
              <p className="muted" style={{ marginTop: 2 }}>{ch.prompt}</p>
              {ch.card && (() => {
                const d = ch.card_detail;
                return (
                  <div className="choice-card">
                    {art[ch.card]
                      ? <div className="inspect-art" style={{ backgroundImage: `url(${art[ch.card]})` }} />
                      : <div className="inspect-art ph"><span>{ch.card}</span></div>}
                    <div className="choice-card-info">
                      <b style={{ fontSize: "1.02rem" }}>{ch.card}</b>
                      {d && (
                        <>
                          <div className="choice-card-line">
                            {d.cost ? <span className="choice-cost">{d.cost}</span> : null}
                            {d.pt ? <span className="choice-pt">{d.pt}</span> : null}
                          </div>
                          {d.type ? <span className="choice-type">{d.type}</span> : null}
                          {d.keywords.length > 0 && (
                            <div className="choice-kws">
                              {d.keywords.filter((k) => KW_SHORT[k]).map((k) => (
                                <span key={k} className="atk-kw" title={k}>{KW_SHORT[k]}</span>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                );
              })()}
              <div className="target-list">
                {ch.options.map((o) => (
                  <button
                    key={o.i}
                    className="ghost"
                    disabled={o.ok === false}
                    onClick={() => doAct("choose", { index: o.i })}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {art[o.name]
                      ? <span className="choice-thumb" style={{ backgroundImage: `url(${art[o.name]})` }} />
                      : <Icon name={isCardPick ? (o.is_land ? "land" : "cards") : "chevron-right"} size={13} />}
                    {o.name}
                    {o.ok === false ? <span className="muted"> · no elegible</span> : null}
                  </button>
                ))}
              </div>
              {ch.allow_none && (
                <div className="act-block" style={{ marginTop: 10 }}>
                  <button className="ghost" onClick={() => doAct("choose", { index: null })}>
                    {noneLabel}
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {zoneView && (
        <div className="inspect-back" onClick={() => setZoneView(null)}>
          <div className="inspect zone-view" onClick={(e) => e.stopPropagation()}>
            <button className="inspect-x" aria-label="Cerrar" title="Cerrar" onClick={() => setZoneView(null)}><Icon name="x" size={16} /></button>
            <h3><Icon name="grave" size={16} /> {zoneView.title} <span className="muted">({zoneView.names.length})</span></h3>
            {zoneView.names.length === 0 ? (
              <p className="muted">Vacío.</p>
            ) : (
              <div className="zone-grid">
                {zoneView.names.map((n, k) => {
                  const br = state?.card_briefs?.[n];
                  return (
                  <button key={k} type="button" className="zone-card"
                    onClick={() => setInspect({
                      name: n,
                      cost: br?.cost,
                      types: br?.type ? br.type.split(" — ")[0].split(" ").map((t) => t.toLowerCase()) : undefined,
                      power: br?.pt ? Number(br.pt.split("/")[0]) : null,
                      toughness: br?.pt ? Number(br.pt.split("/")[1]) : null,
                      keywords: br?.keywords,
                    } as Inspect)}
                    title={n}>
                    {art[n]
                      ? <span className="zone-thumb" style={{ backgroundImage: `url(${art[n]})` }} />
                      : <span className="zone-thumb ph"><span>{n}</span></span>}
                    <span className="zone-name">{n}</span>
                  </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {inspect && (() => {
        // Las fichas (tokens) se describen SIEMPRE con los datos reales del motor:
        // buscar por nombre en Scryfall colisiona (p. ej. "Treasure" trae la ficha
        // doble Dinosaurio//Treasure, con poder y trample que esta ficha no tiene).
        const tok = !!inspect.is_token;
        const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
        const engineType = [
          ...(inspect.types || []).map(cap),
        ].join(" ") + ((inspect.subtypes && inspect.subtypes.length)
          ? ` — ${inspect.subtypes.join(" ")}` : "");
        const typeText = tok
          ? `Ficha${engineType ? " " + engineType : ""}`
          : (info[inspect.name]?.type || (inspect.types || []).join(" "));
        const showArt = !tok && art[inspect.name];
        const oracle = tok ? "" : info[inspect.name]?.oracle;
        // coste de maná: lo que trae la inspección, o el resumen del motor (p. ej.
        // al revisar una carta del cementerio/exilio, que llega solo como nombre).
        const briefCost = state?.card_briefs?.[inspect.name]?.cost;
        const costText = inspect.cost || (tok ? "" : briefCost);
        return (
        <div className="inspect-back" onClick={() => setInspect(null)}>
          <div className="inspect" onClick={(e) => e.stopPropagation()}>
            <button className="inspect-x" aria-label="Cerrar" title="Cerrar" onClick={() => setInspect(null)}><Icon name="x" size={16} /></button>
            {showArt ? (
              <div className="inspect-art" style={{ backgroundImage: `url(${art[inspect.name]})` }} />
            ) : (
              <div className="inspect-art ph"><span>{inspect.name}</span></div>
            )}
            <h3>{inspect.name} {costText ? <span className="muted">{costText}</span> : null}</h3>
            <p className="muted" style={{ margin: "2px 0" }}>
              {typeText}
              {inspect.power != null ? ` · ${inspect.power}/${inspect.toughness}` : ""}
            </p>
            {(inspect.keywords && inspect.keywords.length > 0) && (
              <p className="muted" style={{ margin: "2px 0", fontSize: ".82rem" }}>
                {inspect.keywords.map(cap).join(", ")}
              </p>
            )}
            {oracle ? (
              <p className="oracle">{oracle}</p>
            ) : (inspect.abilities && inspect.abilities.length > 0) ? (
              <ul className="abil">{inspect.abilities.map((a, k) => <li key={k}>{a}</li>)}</ul>
            ) : (
              <p className="muted">{tok ? "Ficha sin habilidades." : "Sin habilidades (carta básica)."}</p>
            )}
            {!tok && !info[inspect.name] && (
              <p className="muted" style={{ fontSize: ".75rem" }}>
                Carta de ejemplo (casera): se muestran sus habilidades del motor.
              </p>
            )}
            {(() => {
              if (!gloss) return null;
              const found = keywordsIn(gloss,
                [oracle || "", ...(inspect.abilities || [])].join("\n"),
                inspect.keywords || []).slice(0, 8);
              if (!found.length) return null;
              return (
                <div className="kw-help">
                  {found.map((e) => {
                    const sup = supportLabel(e.s);
                    return (
                      <div key={e.n}>
                        <b>{e.n}</b>: {e.d}
                        {e.s !== null && e.s < 0.75 && <span className={`sup ${sup.cls}`} style={{ marginLeft: 6, fontSize: ".7rem" }}>{sup.txt}</span>}
                      </div>
                    );
                  })}
                  <a href="/reglas#glosario" target="_blank" rel="noreferrer" className="muted" style={{ fontSize: ".72rem" }}>Ver glosario completo</a>
                </div>
              );
            })()}
          </div>
        </div>
        );
      })()}

      <footer>
        Los rivales los juega el sistema, en la dificultad que elijas. Tus decks
        (<Icon name="star" size={12} />) van con foto y texto real; los de ejemplo usan una ficha simple.
        Tocá cualquier carta (o su <Icon name="info" size={12} />) para verla de cerca.
      </footer>
    </div>
  );
}
