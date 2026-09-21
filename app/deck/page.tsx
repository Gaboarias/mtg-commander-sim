"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getProfile,
  setProfile as saveProfile,
  listDecks,
  saveDeck,
  removeDeck,
  storageAvailable,
  listBinder,
  addToBinder,
  removeFromBinder,
  getSyncCode,
  mergeDecks,
  setBinder as saveBinder,
  type SavedDeck,
  type BinderCard,
} from "../localDecks";
import { download, fileStamp } from "../download";
import { KOFI_URL, PAYPAL_URL, FREE_SIM, FREE_DECKS } from "../support";
import { effectiveCode, getToken, getUser } from "../auth";

type Precon = { code: string; fileName: string; name: string; releaseDate: string };

type Row = {
  name: string;
  qty: number;
  source: "registry" | "basic" | "scryfall" | "missing";
  implemented: boolean;
  generic?: boolean;
  can_command?: boolean;
  type: string;
  cost: string;
  pt: string;
  colors?: string[];
  price?: number | null;
  legal?: boolean;
};
type Resolved = {
  commander: Row | null;
  commander_name: string | null;
  commander_suggested?: string | null;
  cards: Row[];
  total: number;
  implemented: number;
  missing: string[];
  scryfall_online: boolean;
  game_changers?: string[];
  bracket_estimate?: number;
  bracket_label?: string;
  bracket_declared?: number | null;
  price_total?: number;
  illegal?: string[];
};
type SimResult = { n: number; opponent: string; results: { deck: string; wins: number; pct: number }[] };
type Suggestion = { name: string; in_color: boolean; fills: string[]; verdict: string; score: number };
type SuggestResp = { card: string; roles: string[]; colors: string[]; decks: Suggestion[] };
type PricedCard = { name: string; price: number | null };
type Combo = { id: string; cards: string[]; produces: string[]; missing: string[]; missing_priced?: PricedCard[] };
type Recommendation = { text: string; cards: PricedCard[]; subtotal?: number | null };
type Analysis = {
  commander: string | null;
  total: number;
  unknown: number;
  counts: Record<string, number>;
  roles: Record<string, number>;
  curve: Record<string, number>;
  avg_cmc: number;
  themes: { key: string; label: string; count: number; cards: string[] }[];
  strengths: string[];
  weaknesses: string[];
  recommendations: Recommendation[];
  consistency: { land_prob: number; score: number };
  combos: { included: Combo[]; almost: Combo[]; error: string | null };
};

// Plantillas de arranque (nunca la de Kang). Se elige una al azar al abrir el
// editor. Son solo un punto de partida para editar; se resuelven con Scryfall.
const TEMPLATES = [
  `Commander
1 Quintorius Kand

Deck
1 Lightning Helix
1 Anguished Unmaking
1 Faithless Looting
1 Sol Ring
1 Arcane Signet
1 Command Tower
15 Mountain
15 Plains`,
  `Commander
1 Ezuri, Claw of Progress

Deck
1 Cultivate
1 Rapid Hybridization
1 Counterspell
1 Sol Ring
1 Arcane Signet
1 Command Tower
15 Forest
15 Island`,
  `Commander
1 Kaalia of the Vast

Deck
1 Swords to Plowshares
1 Terminate
1 Read the Bones
1 Sol Ring
1 Arcane Signet
1 Command Tower
10 Mountain
10 Plains
10 Swamp`,
  `Commander
1 Atraxa, Praetors' Voice

Deck
1 Cultivate
1 Anguished Unmaking
1 Doubling Season
1 Sol Ring
1 Arcane Signet
1 Command Tower
10 Forest
10 Plains
10 Swamp`,
];

const SAMPLE = TEMPLATES[0];

function MissingFixer({ name, onPick }: { name: string; onPick: (n: string) => void }) {
  const [q, setQ] = useState(name);
  const [sugg, setSugg] = useState<string[]>([]);
  const [setCode, setSetCode] = useState("");
  const [num, setNum] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function search() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch(`/api/cardsearch?q=${encodeURIComponent(q)}`);
      const d = await r.json();
      if (d.error) setMsg(d.error);
      else setSugg(d.suggestions || []);
      if ((d.suggestions || []).length === 0) setMsg("Sin sugerencias.");
    } catch {
      setMsg("Error al buscar.");
    } finally {
      setBusy(false);
    }
  }

  async function byNumber() {
    if (!setCode || !num) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch(
        `/api/cardsearch?set=${encodeURIComponent(setCode)}&number=${encodeURIComponent(num)}`
      );
      const d = await r.json();
      if (d.error || !d.name) setMsg(d.error || "no encontrada");
      else onPick(d.name);
    } catch {
      setMsg("Error al buscar.");
    } finally {
      setBusy(false);
    }
  }

  const inp = {
    background: "var(--panel-2)", color: "var(--text)",
    border: "1px solid var(--border)", borderRadius: 8, padding: "6px 9px",
  } as const;

  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "12px 0" }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="err" style={{ minWidth: 140 }}>⚠ {name}</span>
        <input value={q} aria-label="Nombre de la carta a corregir" onChange={(e) => setQ(e.target.value)} style={{ ...inp, width: 200 }} />
        <button className="ghost" onClick={search} disabled={busy}>Buscar</button>
        <span className="muted">o por set/#:</span>
        <input placeholder="set" aria-label="Código de set" value={setCode} onChange={(e) => setSetCode(e.target.value)} style={{ ...inp, width: 64 }} />
        <input placeholder="n°" aria-label="Número de colección" value={num} onChange={(e) => setNum(e.target.value)} style={{ ...inp, width: 64 }} />
        <button className="ghost" onClick={byNumber} disabled={busy}>Traer</button>
      </div>
      {sugg.length > 0 && (
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {sugg.map((s) => (
            <button key={s} className="ghost" style={{ padding: "4px 10px" }} onClick={() => onPick(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      {msg && <p className="muted" style={{ marginTop: 6 }}>{msg}</p>}
    </div>
  );
}

// Caja con autocompletado para agregar una carta por nombre (reusa /api/cardsearch).
function CardAdder({ onAdd, placeholder }: { onAdd: (name: string) => void; placeholder: string }) {
  const [q, setQ] = useState("");
  const [sugg, setSugg] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function search() {
    if (!q.trim()) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/cardsearch?q=${encodeURIComponent(q)}`);
      const d = await r.json();
      setSugg(d.suggestions || []);
    } catch {
      setSugg([]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <input value={q} placeholder={placeholder} aria-label={placeholder}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") search(); }}
          style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 9px", width: 240 }} />
        <button className="ghost" onClick={search} disabled={busy}>Buscar</button>
      </div>
      {sugg.length > 0 && (
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {sugg.map((s) => (
            <button key={s} className="ghost" style={{ padding: "4px 10px" }}
              onClick={() => { onAdd(s); setSugg([]); setQ(""); }}>
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Tag({ r }: { r: Row }) {
  const map: Record<string, [string, string]> = {
    registry: ["#2f6b3a", "con efecto"],
    basic: ["#3a3f4a", "básica"],
    scryfall: ["#3a5a8a", "datos reales"],
    missing: ["#7a3030", "no encontrada"],
  };
  const [bg, label] = map[r.source] || ["#3a3f4a", r.source];
  return (
    <span style={{ background: bg, padding: "2px 7px", borderRadius: 6, fontSize: ".72rem" }}>
      {label}
    </span>
  );
}

export default function DeckPage() {
  const [text, setText] = useState(SAMPLE);
  const [resolved, setResolved] = useState<Resolved | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [precons, setPrecons] = useState<Precon[]>([]);
  const [preconMsg, setPreconMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [samples, setSamples] = useState<{ slug: string; name: string }[]>([]);
  const [profile, setProfileState] = useState("");
  const [savedDecks, setSavedDecks] = useState<SavedDeck[]>([]);
  const [deckName, setDeckName] = useState("");
  const [noStorage, setNoStorage] = useState(false);
  const [justSaved, setJustSaved] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisErr, setAnalysisErr] = useState<string | null>(null);
  const [hand, setHand] = useState<Row[] | null>(null);
  const [sim, setSim] = useState<SimResult | null>(null);
  const [simming, setSimming] = useState(false);
  const [opponent, setOpponent] = useState("");
  const [simN, setSimN] = useState(100);
  const [opponents, setOpponents] = useState<{ key: string; label: string }[]>([]);
  const [copied, setCopied] = useState(false);
  const [binder, setBinder] = useState<BinderCard[]>([]);
  const [syncCode, setSyncCode] = useState("");
  const [otherCode, setOtherCode] = useState("");
  const [cloudMsg, setCloudMsg] = useState<string | null>(null);
  const [cloudBusy, setCloudBusy] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [supporter, setSupporter] = useState(false);
  const [coupon, setCoupon] = useState("");
  const [supMsg, setSupMsg] = useState<string | null>(null);
  const supportUrl = KOFI_URL;
  const [suggest, setSuggest] = useState<SuggestResp | null>(null);
  const [suggesting, setSuggesting] = useState<string | null>(null);

  // plantilla al azar al abrir (solo en cliente, para no romper la hidratación)
  useEffect(() => {
    setText(TEMPLATES[Math.floor(Math.random() * TEMPLATES.length)]);
  }, []);

  useEffect(() => {
    if (!storageAvailable()) {
      setNoStorage(true);
      return;
    }
    setProfileState(getProfile());
    setSavedDecks(listDecks());
    setBinder(listBinder());
    const code = getSyncCode();
    setSyncCode(code);
    const acct = getUser();
    if (acct?.is_supporter || acct?.is_admin) setSupporter(true);
    fetch("/api/supporter", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "status", code }),
    }).then((r) => r.json()).then((d) => setSupporter((s) => s || !!d.supporter)).catch(() => {});
  }, []);

  async function redeemCoupon() {
    setSupMsg(null);
    try {
      const r = await fetch("/api/supporter", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "redeem", code: getSyncCode(), coupon }),
      });
      const d = await r.json();
      if (d.supporter) { setSupporter(true); setSupMsg("¡Listo! Modo supporter activado. Gracias 🙏"); setCoupon(""); }
      else setSupMsg(d.error || "Cupón inválido.");
    } catch { setSupMsg("Error al canjear."); }
  }

  // abrir un deck compartido por link (?share=<id>)
  useEffect(() => {
    const sid = new URLSearchParams(window.location.search).get("share");
    if (!sid) return;
    (async () => {
      try {
        const r = await fetch(`/api/cloud?share=${encodeURIComponent(sid)}`);
        const d = await r.json();
        if (d.error || !d.text) { setError("No se encontró el deck compartido."); return; }
        setText(d.text);          // el texto ya incluye la sección Commander
        resolve(d.text);
      } catch { setError("No se pudo cargar el deck compartido."); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // rivales para "probar el deck" (decks registrados del catálogo)
  useEffect(() => {
    fetch("/api/catalog")
      .then((r) => r.json())
      .then((d) => {
        const opts = (d.decks || []).map((x: { key: string; commander: string }) => ({ key: x.key, label: x.commander }));
        setOpponents(opts);
        if (opts[0]) setOpponent((o) => o || opts[0].key);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch("/api/precons")
      .then(async (r) => {
        const raw = await r.text();
        let d;
        try {
          d = JSON.parse(raw);
        } catch {
          throw new Error(`HTTP ${r.status}: ${raw.slice(0, 200)}`);
        }
        if (d.error) throw new Error(d.error);
        setPrecons(d.precons || []);
      })
      .catch((e) => setPreconMsg(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    fetch("/api/samples")
      .then((r) => r.json())
      .then((d) => setSamples(d.samples || []))
      .catch(() => {});
  }, []);

  function currentDeckText(): string {
    if (!resolved) return text;
    const lines = ["Commander"];
    if (resolved.commander_name) lines.push(`1 ${resolved.commander_name}`);
    lines.push("", "Deck");
    for (const c of resolved.cards) if (c.qty > 0) lines.push(`${c.qty} ${c.name}`);
    return lines.join("\n");
  }

  // agregar una carta al deck abierto (por búsqueda o desde el binder)
  function addCardToDeck(name: string) {
    if (resolved) {
      const i = resolved.cards.findIndex((c) => c.name.toLowerCase() === name.toLowerCase());
      if (i >= 0) { setQty(i, resolved.cards[i].qty + 1); return; }
    }
    const base = currentDeckText().replace(/\s*$/, "");
    const next = `${base}\n1 ${name}`;
    setText(next);
    resolve(next);
  }

  // exportar / copiar la lista
  function copyList() {
    const txt = currentDeckText();
    try {
      navigator.clipboard?.writeText(txt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch { /* sin portapapeles: el usuario puede usar Descargar */ }
  }
  function exportTxt() {
    download(`deck-${fileStamp()}.txt`, currentDeckText(), "text/plain");
  }

  // probar el deck contra un rival registrado
  async function simulateDeck() {
    if (!resolved) return;
    setSimming(true);
    setSim(null);
    try {
      const r = await fetch("/api/deck", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "simulate",
          cards: resolved.cards.filter((c) => c.qty > 0).map((c) => ({ name: c.name, qty: c.qty })),
          commander: resolved.commander_name || "",
          opponent, n: simN, code: effectiveCode(), token: getToken(),
        }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setSim(d as SimResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setSimming(false); }
  }

  // binder
  function binderAdd(name: string) { setBinder(addToBinder(name)); }
  function binderRemove(name: string) {
    setBinder(removeFromBinder(name));
    if (suggest?.card.toLowerCase() === name.toLowerCase()) setSuggest(null);
  }
  async function whereDoesItHelp(card: string) {
    const decks = listDecks();
    if (decks.length === 0) { setError("Guardá al menos un deck para ver dónde te sirve."); return; }
    setSuggesting(card);
    setSuggest(null);
    try {
      const r = await fetch("/api/suggest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ card, decks: decks.map((d) => ({ name: d.name, text: d.text })) }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setSuggest(d as SuggestResp);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setSuggesting(null); }
  }

  // nube: subir / bajar por código
  async function pushCloud() {
    setCloudBusy(true); setCloudMsg(null);
    try {
      const r = await fetch("/api/cloud", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "push", code: effectiveCode(), token: getToken(), decks: listDecks(), binder: listBinder() }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setCloudMsg(`Subido: ${listDecks().length} decks + binder.`);
    } catch (e) { setCloudMsg("Error al subir: " + (e instanceof Error ? e.message : String(e))); }
    finally { setCloudBusy(false); }
  }
  async function pullCloud() {
    const code = (otherCode.trim() || effectiveCode()).trim();
    if (!code) return;
    setCloudBusy(true); setCloudMsg(null);
    try {
      const r = await fetch("/api/cloud", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "pull", code, token: getToken() }),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setSavedDecks(mergeDecks(d.decks || []));
      if (Array.isArray(d.binder)) setBinder(saveBinder(d.binder));
      setCloudMsg(`Bajado: ${(d.decks || []).length} decks + binder (fusionado con lo local).`);
    } catch (e) { setCloudMsg("Error al bajar: " + (e instanceof Error ? e.message : String(e))); }
    finally { setCloudBusy(false); }
  }
  async function shareDeck() {
    setShareUrl(null);
    try {
      const r = await fetch("/api/cloud", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "share", name: resolved?.commander_name || "deck",
          text: currentDeckText(), commander: resolved?.commander_name || "" }),
      });
      const d = await r.json();
      if (d.error || !d.id) throw new Error(d.error || "sin id");
      const url = `${window.location.origin}/deck?share=${d.id}`;
      setShareUrl(url);
      try { await navigator.clipboard?.writeText(url); } catch { /* copiar manual */ }
    } catch (e) { setError("No se pudo compartir: " + (e instanceof Error ? e.message : String(e))); }
  }

  async function analyzeDeck() {
    setAnalyzing(true);
    setAnalysisErr(null);
    try {
      const r = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: currentDeckText(),
          commander: resolved?.commander_name || null,
        }),
      });
      const raw = await r.text();
      let d;
      try {
        d = JSON.parse(raw);
      } catch {
        throw new Error(`HTTP ${r.status}: ${raw.slice(0, 200)}`);
      }
      if (d.error) throw new Error(d.error);
      setAnalysis(d as Analysis);
    } catch (e) {
      setAnalysisErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzing(false);
    }
  }

  function drawHand() {
    if (!resolved) return;
    const pool: Row[] = [];
    for (const c of resolved.cards) {
      for (let i = 0; i < Math.max(0, c.qty); i++) pool.push(c);
    }
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    setHand(pool.slice(0, 7));
  }

  function deckColors(): string[] {
    const order = ["W", "U", "B", "R", "G"];
    const set = new Set<string>();
    (resolved?.commander?.colors || []).forEach((c) => set.add(c));
    resolved?.cards.forEach((c) => (c.colors || []).forEach((x) => set.add(x)));
    return order.filter((c) => set.has(c));
  }

  function onSaveDeck() {
    const name = deckName.trim() || resolved?.commander_name || "Mi deck";
    setSavedDecks(saveDeck(name, currentDeckText(), deckColors()));
    setDeckName("");
    setJustSaved(name);
    setTimeout(() => setJustSaved(null), 4000);
  }
  function onLoadSaved(d: SavedDeck) {
    setText(d.text);
    setResolved(null);
  }
  function onDeleteSaved(id: string) {
    setSavedDecks(removeDeck(id));
  }
  function onProfileChange(v: string) {
    setProfileState(v);
    saveProfile(v);
  }

  async function loadInto(url: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(url);
      const raw = await r.text();
      let d;
      try {
        d = JSON.parse(raw);
      } catch {
        throw new Error(`HTTP ${r.status}: ${raw.slice(0, 200)}`);
      }
      if (d.error) throw new Error(d.error);
      setText(d.text);
      setResolved(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const [cmdChoice, setCmdChoice] = useState("");
  useEffect(() => {
    if (resolved && !resolved.commander_name) {
      setCmdChoice(resolved.commander_suggested || resolved.cards[0]?.name || "");
    }
  }, [resolved]);

  function setCommander(name: string) {
    if (!resolved || !name) return;
    const lines = ["Commander", `1 ${name}`, "", "Deck"];
    let removed = false;
    for (const c of resolved.cards) {
      let qty = c.qty;
      if (!removed && c.name === name) {
        qty -= 1;
        removed = true;
      }
      if (qty > 0) lines.push(`${qty} ${c.name}`);
    }
    const next = lines.join("\n");
    setText(next);
    resolve(next);
  }

  const [cmdName, setCmdName] = useState("");

  function _lineName(line: string): string {
    const m = line.match(/^\s*\d+\s*x?\s+(.+?)\s*$/);
    let n = m ? m[1] : line.trim();
    n = n
      .replace(/\s*\([^)]*\)\s*[\dA-Za-z-]*\s*$/, "") // (SET) 123
      .replace(/\*(cmdr|commander|comandante)\*/i, "")
      .trim();
    return n;
  }

  // arma una lista con seccion Commander poniendo `name` de comandante y
  // quitando UNA copia de esa carta del resto
  function buildWithCommander(name: string): string {
    const rest: string[] = [];
    let removed = false;
    for (const raw of text.split("\n")) {
      const l = raw.trim();
      if (!l) continue;
      if (/^(commander|comandante|deck|mainboard|sideboard|maybeboard)\b/i.test(l)) continue;
      if (!removed && _lineName(l).toLowerCase() === name.toLowerCase()) {
        removed = true;
        continue;
      }
      rest.push(raw);
    }
    return `Commander\n1 ${name}\n\nDeck\n${rest.join("\n")}`;
  }

  function markFirstAsCommander() {
    for (const raw of text.split("\n")) {
      const l = raw.trim();
      if (!l || l.startsWith("#") || l.startsWith("//")) continue;
      if (/^(commander|comandante|deck|mainboard|sideboard|maybeboard)\b/i.test(l)) continue;
      const name = _lineName(l);
      if (!name) continue;
      const next = buildWithCommander(name);
      setText(next);
      resolve(next);
      return;
    }
  }

  function markNamedCommander() {
    const name = cmdName.trim();
    if (!name) return;
    const next = buildWithCommander(name);
    setText(next);
    setCmdName("");
    resolve(next);
  }

  function replaceCard(oldName: string, newName: string) {
    if (!newName || oldName === newName) return;
    const next = text.split(oldName).join(newName);
    setText(next);
    resolve(next);
  }

  async function resolve(listText?: string) {
    const list = listText ?? text;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/deck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "resolve", list }),
      });
      const raw = await r.text();
      let d: { error?: string; [k: string]: unknown };
      try {
        d = JSON.parse(raw);
      } catch {
        throw new Error(`HTTP ${r.status} — respuesta no-JSON: ${raw.slice(0, 240)}`);
      }
      if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
      setResolved(d as unknown as Resolved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function setQty(i: number, q: number) {
    if (!resolved) return;
    const cards = resolved.cards.slice();
    cards[i] = { ...cards[i], qty: Math.max(0, q) };
    setResolved({ ...resolved, cards });
  }
  function remove(i: number) {
    if (!resolved) return;
    setResolved({ ...resolved, cards: resolved.cards.filter((_, j) => j !== i) });
  }

  const totalQty = resolved ? resolved.cards.reduce((s, c) => s + c.qty, 0) : 0;

  return (
    <div className="wrap">
      <header>
        <h1>🛠️ Editor de decks</h1>
        <p>
          Traé tu lista, revisá las cartas y <strong>guardá el deck en tu perfil</strong>.
          Después lo elegís para jugar en la <Link href="/">página principal →</Link>.
        </p>
      </header>

      <div className="card">
        <h2>👤 Mis decks (en este navegador)</h2>
        {noStorage ? (
          <p className="muted">
            Tu navegador bloquea el almacenamiento local (¿modo privado?), así que
            no puedo guardar decks acá.
          </p>
        ) : (
          <>
            <div className="row">
              <label>
                Nombre&nbsp;
                <input
                  value={profile}
                  onChange={(e) => onProfileChange(e.target.value)}
                  placeholder="tu nombre" aria-label="Tu nombre de perfil"
                  style={{
                    background: "var(--panel-2)", color: "var(--text)",
                    border: "1px solid var(--border)", borderRadius: 8,
                    padding: "8px 10px", width: 180,
                  }}
                />
              </label>
              <span className="muted">Tus decks se guardan solo en este dispositivo.</span>
            </div>
            {savedDecks.length > 0 ? (
              <table style={{ marginTop: 14 }}>
                <thead>
                  <tr><th>Deck guardado</th><th>Actualizado</th><th></th></tr>
                </thead>
                <tbody>
                  {savedDecks.map((d) => (
                    <tr key={d.id}>
                      <td>{d.name}</td>
                      <td className="muted">{new Date(d.updatedAt).toLocaleDateString()}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="ghost" style={{ padding: "4px 10px", marginRight: 6 }}
                          onClick={() => onLoadSaved(d)}>Cargar</button>
                        <button className="ghost" style={{ padding: "4px 8px" }}
                          aria-label={`Borrar deck ${d.name}`} title="Borrar"
                          onClick={() => onDeleteSaved(d.id)}>✕</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted" style={{ marginTop: 10 }}>
                Todavía no guardaste ningún deck. Armá uno abajo y guardalo.
              </p>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2><span className="step">1</span> Traé tu lista</h2>
        <div className="row" style={{ marginBottom: 10, flexWrap: "wrap" }}>
          <span className="muted">Empezar desde:</span>
          {precons.length > 0 ? (
            <>
              <input
                placeholder="filtrar precon…" aria-label="Filtrar precons"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                style={{
                  background: "var(--panel-2)", color: "var(--text)",
                  border: "1px solid var(--border)", borderRadius: 8,
                  padding: "8px 10px", width: 160,
                }}
              />
              <select
                onChange={(e) => e.target.value &&
                  loadInto(`/api/precons?load=${encodeURIComponent(e.target.value)}`)}
                defaultValue=""
                style={{
                  background: "var(--panel-2)", color: "var(--text)",
                  border: "1px solid var(--border)", borderRadius: 8,
                  padding: "8px 10px", maxWidth: 300,
                }}
              >
                <option value="">— un precon oficial —</option>
                {precons
                  .filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()))
                  .slice(0, 300)
                  .map((p) => (
                    <option key={p.fileName} value={p.fileName}>
                      {p.name} · {p.releaseDate}
                    </option>
                  ))}
              </select>
            </>
          ) : (
            <span className="muted">{preconMsg || "cargando precons…"}</span>
          )}
          {samples.length > 0 && (
            <select
              onChange={(e) => e.target.value &&
                loadInto(`/api/samples?load=${encodeURIComponent(e.target.value)}`)}
              defaultValue=""
              style={{
                background: "var(--panel-2)", color: "var(--text)",
                border: "1px solid var(--border)", borderRadius: 8,
                padding: "8px 10px", maxWidth: 260,
              }}
            >
              <option value="">— un deck de ejemplo —</option>
              {samples.map((s) => (
                <option key={s.slug} value={s.slug}>{s.name}</option>
              ))}
            </select>
          )}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          style={{
            width: "100%", minHeight: 180, background: "#0a0c10",
            color: "#c8cdd8", border: "1px solid var(--border)", borderRadius: 10,
            padding: 12, fontFamily: "ui-monospace, monospace", fontSize: ".85rem",
          }}
        />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="go" onClick={() => resolve()} disabled={busy}>
            {busy ? "Revisando…" : "Revisar cartas"}
          </button>
          <span className="muted">
            pegá tu lista (Moxfield / Archidekt / «1 Nombre»)
          </span>
        </div>
        {error && <p className="err">⚠ {error}</p>}
        <div className="row" style={{ marginTop: 10, flexWrap: "wrap", gap: 8 }}>
          <span className="muted">¿No marca el comandante?</span>
          <button className="ghost" style={{ padding: "6px 12px" }} onClick={markFirstAsCommander}>
            La 1ª carta es el comandante
          </button>
          <span className="muted">o</span>
          <input
            placeholder="nombre del comandante" aria-label="Nombre del comandante"
            value={cmdName}
            onChange={(e) => setCmdName(e.target.value)}
            style={{
              background: "var(--panel-2)", color: "var(--text)",
              border: "1px solid var(--border)", borderRadius: 8,
              padding: "6px 10px", width: 200,
            }}
          />
          <button className="ghost" style={{ padding: "6px 12px" }} onClick={markNamedCommander}>
            Marcar
          </button>
        </div>
      </div>

      {resolved && !resolved.commander_name && (
        <div className="card">
          <h2>⚑ Elegí tu comandante</h2>
          <p className="muted">
            No detecté el comandante en la lista (Moxfield no siempre lo marca).
            Elegí cuál es y lo pongo en la zona de mando:
          </p>
          <div className="row">
            <select
              value={cmdChoice}
              onChange={(e) => setCmdChoice(e.target.value)}
              style={{
                background: "var(--panel-2)", color: "var(--text)",
                border: "1px solid var(--border)", borderRadius: 8,
                padding: "8px 10px", maxWidth: 340,
              }}
            >
              {[...resolved.cards]
                .sort((a, b) => (b.can_command ? 1 : 0) - (a.can_command ? 1 : 0))
                .map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}{c.can_command ? " · legendaria" : ""}
                  </option>
                ))}
            </select>
            <button className="go" onClick={() => setCommander(cmdChoice)}>
              Usar como comandante
            </button>
          </div>
        </div>
      )}

      {resolved && (
        <div className="card">
          <h2><span className="step">2</span> Revisá y editá</h2>
          {resolved.commander ? (
            <p>
              <strong>Comandante:</strong> {resolved.commander.name}{" "}
              <Tag r={resolved.commander} />
            </p>
          ) : (
            <p className="err">Elegí tu comandante en el recuadro de arriba ⚑</p>
          )}
          <p className="muted">
            {totalQty} cartas · {resolved.implemented} con efecto programado ·{" "}
            {resolved.missing.length} no encontradas
            {typeof resolved.price_total === "number" && resolved.price_total > 0
              ? ` · ~US$ ${resolved.price_total.toFixed(2)}` : ""}
          </p>
          {(resolved.illegal?.length || 0) > 0 && (
            <p className="err">⛔ No legales en Commander: {resolved.illegal!.join(", ")}</p>
          )}
          {!resolved.scryfall_online && (
            <p className="muted">
              (Sin conexión a la base de cartas: solo se reconocen las cartas ya
              programadas y las tierras básicas. En el sitio publicado se
              reconocen todas.)
            </p>
          )}

          <div className="row" style={{ gap: 8, flexWrap: "wrap", margin: "6px 0 4px" }}>
            <span className="muted">Agregar carta:</span>
            <CardAdder onAdd={addCardToDeck} placeholder="nombre de la carta…" />
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
            <button className="ghost" onClick={copyList}>{copied ? "¡Copiado! ✔" : "Copiar lista"}</button>
            <button className="ghost" onClick={exportTxt}>⬇ Descargar .txt</button>
            <button className="ghost" onClick={shareDeck}>🔗 Compartir por link</button>
          </div>
          {shareUrl && (
            <p className="muted" style={{ fontSize: ".82rem" }}>
              Link (copiado): <a href={shareUrl}>{shareUrl}</a>
            </p>
          )}

          <table>
            <thead>
              <tr>
                <th>Cant.</th><th>Carta</th><th>Coste</th><th>Tipo</th>
                <th>F/R</th><th>Precio</th><th>Estado</th><th></th>
              </tr>
            </thead>
            <tbody>
              {resolved.cards.map((c, i) => (
                <tr key={i} style={{ opacity: c.qty === 0 ? 0.4 : 1 }}>
                  <td>
                    <input type="number" min={0} value={c.qty}
                      onChange={(e) => setQty(i, Number(e.target.value))}
                      style={{ width: 56 }} />
                  </td>
                  <td>
                    {c.name}
                    {c.legal === false && <span title="No legal en Commander"> ⛔</span>}
                  </td>
                  <td>{c.cost}</td>
                  <td className="muted">{c.type}</td>
                  <td>{c.pt}</td>
                  <td className="muted">{typeof c.price === "number" ? `$${c.price.toFixed(2)}` : "—"}</td>
                  <td>
                    <Tag r={c} />
                    {c.generic && (
                      <span style={{ background: "#5a4a2a", padding: "2px 6px", borderRadius: 6, fontSize: ".68rem", marginLeft: 4 }}>
                        aprox
                      </span>
                    )}
                  </td>
                  <td>
                    <button className="ghost" style={{ padding: "4px 8px" }} aria-label={`Quitar ${c.name}`} title="Quitar" onClick={() => remove(i)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resolved && (
        <div className="card">
          <h2>⚔ Probar este deck</h2>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Simula tu lista contra un rival (el sistema juega ambos). Aproximado y contra
            UN rival registrado — sirve como termómetro, no como veredicto.
          </p>
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <label>Rival&nbsp;
              <select value={opponent} onChange={(e) => setOpponent(e.target.value)}
                style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 10px" }}>
                {opponents.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
              </select>
            </label>
            <label>Partidas&nbsp;
              <input type="number" min={10} max={2000} value={simN}
                onChange={(e) => setSimN(Number(e.target.value))} style={{ width: 80 }} />
            </label>
            <button className="go" onClick={simulateDeck} disabled={simming || !opponent || !resolved.commander_name}>
              {simming ? "Simulando…" : "Simular"}
            </button>
          </div>
          {!resolved.commander_name && <p className="muted" style={{ fontSize: ".8rem" }}>Marcá el comandante primero.</p>}
          {!supporter && simN > FREE_SIM && (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Tope gratis: {FREE_SIM} partidas por corrida. <a href={KOFI_URL} target="_blank" rel="noreferrer">Apoyá</a> para subirlo.
            </p>
          )}
          {sim && (
            <div style={{ marginTop: 12 }}>
              {sim.results.map((r) => (
                <div key={r.deck} className="bar-row" style={{ display: "flex", alignItems: "center", gap: 10, margin: "4px 0" }}>
                  <span style={{ width: 120 }}>{r.deck === "importado" ? "Tu deck" : r.deck === "EMPATE" ? "Empates" : r.deck}</span>
                  <span className="bar-track" style={{ flex: 1, background: "var(--panel-2)", borderRadius: 6, height: 14, overflow: "hidden" }}>
                    <span className="bar-fill" style={{ display: "block", height: "100%", width: `${r.pct}%`, background: r.deck === "importado" ? "var(--accent)" : "#5a6172" }} />
                  </span>
                  <span className="muted" style={{ width: 70, textAlign: "right" }}>{r.pct}% ({r.wins})</span>
                </div>
              ))}
              <p className="muted" style={{ fontSize: ".8rem" }}>{sim.n} partidas vs {sim.opponent}.</p>
            </div>
          )}
        </div>
      )}

      {resolved && (
        <div className="card">
          <h2>🏅 Poder del deck (bracket)</h2>
          <div className="row" style={{ gap: 24, alignItems: "flex-start" }}>
            <div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: "2rem", fontWeight: 700, color: "var(--accent)" }}>
                Bracket {resolved.bracket_declared ?? resolved.bracket_estimate}
              </div>
              <div className="muted" style={{ fontSize: ".85rem" }}>
                {resolved.bracket_declared
                  ? "declarado en la lista"
                  : `estimado · ${resolved.bracket_label}`}
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ marginBottom: 6 }}>
                <strong>{resolved.game_changers?.length || 0}</strong> Game Changers
              </div>
              <div className="row" style={{ gap: 6 }}>
                {(resolved.game_changers || []).map((g) => (
                  <span key={g} style={{ background: "#5a4a2a", color: "#f0e2c0", padding: "3px 9px", borderRadius: 999, fontSize: ".78rem" }}>
                    {g}
                  </span>
                ))}
                {(resolved.game_changers || []).length === 0 && (
                  <span className="muted">ninguno detectado</span>
                )}
              </div>
            </div>
          </div>
          <p className="muted" style={{ marginTop: 12, fontSize: ".8rem" }}>
            La lista de Game Changers es curada (subconjunto de la oficial de WotC,
            que se actualiza); el bracket estimado es una guía por cantidad de
            Game Changers, no considera combos ni negación masiva de tierras.
          </p>
        </div>
      )}

      {resolved && (
        <div className="card">
          <h2>🔬 Análisis del deck</h2>
          <p className="muted" style={{ marginTop: -6, fontSize: ".82rem" }}>
            Fortalezas, debilidades y sinergias (heurístico sobre el texto de las
            cartas) + combos reales de Commander Spellbook. Todo aproximado salvo
            los combos, que son por nombre.
          </p>
          <button className="go" disabled={analyzing} onClick={analyzeDeck}>
            {analyzing ? "Analizando…" : "Analizar deck"}
          </button>
          {analysisErr && <p className="err">Error: {analysisErr}</p>}

          <div style={{ marginTop: 12 }}>
            <button className="ghost" onClick={drawHand}>
              {hand ? "Robar otra mano ↻" : "Robar mano de prueba"}
            </button>
            {hand && (
              <div style={{ marginTop: 8 }}>
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  {hand.map((c, i) => (
                    <span key={i} className={`chip${(c.type || "").includes("land") ? " land" : ""}`}>
                      {c.name}
                    </span>
                  ))}
                </div>
                <p className="muted" style={{ fontSize: ".82rem" }}>
                  {hand.filter((c) => (c.type || "").includes("land")).length} tierras en la mano.
                </p>
              </div>
            )}
          </div>

          {analysis && (
            <div style={{ marginTop: 16 }}>
              <div className="row" style={{ gap: 24, flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 280px" }}>
                  <h3 style={{ color: "#7ad17a" }}>✔ Fortalezas</h3>
                  <ul className="abil">
                    {analysis.strengths.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
                <div style={{ flex: "1 1 280px" }}>
                  <h3 style={{ color: "#e0a35a" }}>▲ Debilidades</h3>
                  <ul className="abil">
                    {analysis.weaknesses.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              </div>

              {analysis.recommendations.length > 0 && (
                <>
                  <h3 style={{ marginTop: 14, color: "#8ab4ff" }}>➜ Recomendaciones</h3>
                  <ul className="abil">
                    {analysis.recommendations.map((r, i) => (
                      <li key={i}>
                        {r.text}
                        {r.cards.length > 0 && (
                          <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                            {r.cards.map((c) => (
                              <span key={c.name} className="chip">
                                {c.name} <b style={{ color: "var(--accent)" }}>{typeof c.price === "number" ? `$${c.price.toFixed(2)}` : "—"}</b>
                              </span>
                            ))}
                            {typeof r.subtotal === "number" && r.subtotal > 0 && (
                              <span className="muted" style={{ fontSize: ".78rem" }}>≈ ${r.subtotal.toFixed(2)} el set</span>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              <h3 style={{ marginTop: 14 }}>Consistencia</h3>
              <div className="row" style={{ gap: 16, alignItems: "center" }}>
                <div style={{ fontFamily: "var(--font-display)", fontSize: "1.8rem", fontWeight: 700, color: "var(--accent)" }}>
                  {analysis.consistency.score}/100
                </div>
                <div className="muted" style={{ fontSize: ".84rem" }}>
                  {Math.round(analysis.consistency.land_prob * 100)}% de manos iniciales
                  con 2–5 tierras (jugables sin mulligan).
                </div>
              </div>

              <h3 style={{ marginTop: 14 }}>Curva de maná</h3>
              <div className="curve">
                {Object.entries(analysis.curve).map(([k, v]) => {
                  const max = Math.max(1, ...Object.values(analysis.curve));
                  return (
                    <div key={k} className="curve-col">
                      <div className="curve-bar" style={{ height: `${8 + (v / max) * 90}px` }} />
                      <div className="curve-n">{v}</div>
                      <div className="muted" style={{ fontSize: ".72rem" }}>{k === "7" ? "7+" : k}</div>
                    </div>
                  );
                })}
              </div>
              <p className="muted" style={{ fontSize: ".8rem" }}>
                CMC promedio {analysis.avg_cmc} · {analysis.counts.land} tierras ·{" "}
                {analysis.counts.creature} criaturas
                {analysis.unknown ? ` · ${analysis.unknown} sin datos` : ""}
              </p>

              <h3 style={{ marginTop: 10 }}>Roles</h3>
              <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                {Object.entries({
                  ramp: "Ramp", draw: "Robo", removal: "Remoción",
                  wipe: "Barridas", counter: "Counters", protection: "Protección",
                  recursion: "Recursión", tutor: "Tutores",
                }).map(([k, lbl]) => (
                  <span key={k} className="chip">{lbl}: <b>{analysis.roles[k] ?? 0}</b></span>
                ))}
              </div>

              {analysis.themes.length > 0 && (
                <>
                  <h3 style={{ marginTop: 14 }}>Sinergias detectadas</h3>
                  {analysis.themes.map((t) => (
                    <div key={t.key} style={{ marginBottom: 8 }}>
                      <b>{t.label}</b> <span className="muted">({t.count} cartas)</span>
                      <div className="muted" style={{ fontSize: ".8rem" }}>{t.cards.join(", ")}</div>
                    </div>
                  ))}
                </>
              )}

              <h3 style={{ marginTop: 14 }}>Combos</h3>
              {analysis.combos.error ? (
                <p className="muted">No se pudieron consultar los combos ({analysis.combos.error}). El resto del análisis es válido.</p>
              ) : (
                <>
                  {analysis.combos.included.length === 0 && (
                    <p className="muted">No se detectaron combos completos en la lista.</p>
                  )}
                  {analysis.combos.included.map((c) => (
                    <div key={c.id} className="combo">
                      <div><b>{c.cards.join(" + ")}</b></div>
                      <div className="muted" style={{ fontSize: ".82rem" }}>→ {c.produces.join(", ")}</div>
                    </div>
                  ))}
                  {analysis.combos.almost.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 12, fontSize: ".95rem" }}>A una carta de un combo</h3>
                      {analysis.combos.almost.map((c) => {
                        const priceOf = (n: string) => c.missing_priced?.find((m) => m.name === n)?.price;
                        return (
                          <div key={c.id} className="combo almost">
                            <div>{c.cards.map((n) => {
                              if (!c.missing.includes(n)) return <span key={n}>{n} + </span>;
                              const p = priceOf(n);
                              return <b key={n} style={{ color: "var(--accent)" }}>＋{n}{typeof p === "number" ? ` ($${p.toFixed(2)})` : ""} </b>;
                            })}</div>
                            <div className="muted" style={{ fontSize: ".82rem" }}>→ {c.produces.join(", ")}</div>
                          </div>
                        );
                      })}
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {resolved && resolved.missing.length > 0 && (
        <div className="card">
          <h2>⚠ Cartas no encontradas ({resolved.missing.length})</h2>
          <p className="muted">
            Corregí el nombre (buscá y elegí la sugerencia correcta) o traela por
            código de set + número de colección. Al elegir, se reemplaza en la lista
            y se vuelve a revisar.
          </p>
          {resolved.missing.map((m) => (
            <MissingFixer key={m} name={m} onPick={(n) => replaceCard(m, n)} />
          ))}
        </div>
      )}

      {resolved && !noStorage && (
        <div className="card">
          <h2><span className="step">3</span> Guardar en mis decks</h2>
          <div className="row">
            <input
              value={deckName}
              onChange={(e) => setDeckName(e.target.value)}
              placeholder={resolved.commander_name || "nombre del deck"}
              style={{
                background: "var(--panel-2)", color: "var(--text)",
                border: "1px solid var(--border)", borderRadius: 8,
                padding: "8px 10px", width: 220,
              }}
            />
            <button className="go" onClick={onSaveDeck}>Guardar deck</button>
            {justSaved && (
              <span style={{ color: "var(--g)" }}>
                ✓ «{justSaved}» guardado — ya lo podés elegir en la{" "}
                <Link href="/">página principal</Link>.
              </span>
            )}
          </div>
        </div>
      )}

      {!noStorage && (
        <div className="card">
          <h2>☁️ Nube (sync entre dispositivos)</h2>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Sin cuentas: tus decks + binder se guardan bajo un <b>código</b>. Subí desde
            este dispositivo y bajá pegando el mismo código en otro. Quien tenga el código
            puede ver tus decks — no lo compartas si querés privacidad.
          </p>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span className="muted">Tu código:</span>
            <code style={{ background: "var(--panel-2)", padding: "3px 8px", borderRadius: 6, fontSize: ".8rem" }}>{syncCode}</code>
            <button className="ghost" style={{ padding: "3px 8px" }}
              onClick={() => { try { navigator.clipboard?.writeText(syncCode); setCloudMsg("Código copiado."); } catch { /* */ } }}>Copiar código</button>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
            <button className="go" disabled={cloudBusy} onClick={pushCloud}>⬆ Subir a la nube</button>
            <input placeholder="pegá un código para bajar…" aria-label="Código para bajar de la nube" value={otherCode}
              onChange={(e) => setOtherCode(e.target.value)}
              style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 9px", width: 240 }} />
            <button className="ghost" disabled={cloudBusy} onClick={pullCloud}>⬇ Bajar de la nube</button>
          </div>
          {cloudMsg && <p className="muted" style={{ fontSize: ".82rem" }}>{cloudMsg}</p>}
          <div style={{ borderTop: "1px solid var(--border)", marginTop: 12, paddingTop: 12 }}>
            {supporter ? (
              <p className="muted" style={{ fontSize: ".85rem" }}>💛 Sos <b>supporter</b>: topes ampliados (simulaciones grandes y más decks en la nube). ¡Gracias!</p>
            ) : (
              <>
                <p className="muted" style={{ fontSize: ".82rem" }}>
                  Todo el sitio es gratis. Los topes gratis (simular hasta {FREE_SIM} partidas, hasta {FREE_DECKS} decks en la nube)
                  se amplían si apoyás el proyecto — es para bancar la infraestructura, no la IP de MTG.
                </p>
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <input placeholder="canjear código de supporter" aria-label="Código de supporter" value={coupon}
                    onChange={(e) => setCoupon(e.target.value)}
                    style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 9px", width: 220 }} />
                  <button className="ghost" onClick={redeemCoupon} disabled={!coupon.trim()}>Canjear</button>
                  <a className="ghost" href={KOFI_URL} target="_blank" rel="noreferrer" style={{ padding: "6px 12px", textDecoration: "none" }}>💛 Ko-fi</a>
                  <a className="ghost" href={PAYPAL_URL} target="_blank" rel="noreferrer" style={{ padding: "6px 12px", textDecoration: "none" }}>PayPal</a>
                </div>
              </>
            )}
            {supMsg && <p className="muted" style={{ fontSize: ".82rem" }}>{supMsg}</p>}
          </div>
        </div>
      )}

      {!noStorage && (
        <div className="card">
          <h2>🗃️ Mi binder</h2>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Tu colección de cartas (guardada en este navegador). Agregá cartas y fijate
            en cuáles de tus decks guardados te sirve cada una.
          </p>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
            <span className="muted">Agregar al binder:</span>
            <CardAdder onAdd={binderAdd} placeholder="nombre de la carta…" />
          </div>
          {binder.length === 0 ? (
            <p className="muted">Tu binder está vacío.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {binder.map((c) => (
                <div key={c.name} className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <span style={{ minWidth: 180 }}>{c.qty > 1 ? `${c.qty}× ` : ""}{c.name}</span>
                  {resolved && <button className="ghost" style={{ padding: "3px 8px" }} onClick={() => addCardToDeck(c.name)}>+ al deck</button>}
                  <button className="ghost" style={{ padding: "3px 8px" }} disabled={suggesting === c.name}
                    onClick={() => whereDoesItHelp(c.name)}>
                    {suggesting === c.name ? "Buscando…" : "¿Dónde me sirve?"}
                  </button>
                  <button className="ghost" style={{ padding: "3px 8px" }} aria-label={`Quitar ${c.name} del binder`} title="Quitar" onClick={() => binderRemove(c.name)}>✕</button>
                </div>
              ))}
            </div>
          )}
          {suggest && (
            <div style={{ marginTop: 12 }}>
              <b>{suggest.card}</b>
              <span className="muted"> · {suggest.colors.length ? suggest.colors.join("") : "incolora"}{suggest.roles.length ? ` · ${suggest.roles.join(", ")}` : ""}</span>
              {suggest.decks.length === 0 ? (
                <p className="muted">No tenés decks guardados para comparar.</p>
              ) : suggest.decks.map((d) => (
                <div key={d.name} className="combo" style={{ borderLeftColor: d.in_color ? (d.fills.length ? "var(--accent)" : "#5a6172") : "#7a3030" }}>
                  <div><b>{d.name}</b> <span className="muted">— {d.verdict}</span></div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <footer>
        Las cartas con efecto programado se juegan con su habilidad; el resto usa
        sus datos reales (coste, fuerza, resistencia, tipos). No se inventan datos
        de cartas.
      </footer>
    </div>
  );
}
