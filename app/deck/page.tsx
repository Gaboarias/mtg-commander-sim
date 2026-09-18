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
  type SavedDeck,
} from "../localDecks";

type Precon = { code: string; fileName: string; name: string; releaseDate: string };

type Row = {
  name: string;
  qty: number;
  source: "registry" | "basic" | "scryfall" | "missing";
  implemented: boolean;
  type: string;
  cost: string;
  pt: string;
  colors?: string[];
};
type Resolved = {
  commander: Row | null;
  commander_name: string | null;
  cards: Row[];
  total: number;
  implemented: number;
  missing: string[];
  scryfall_online: boolean;
};
type SimResult = { deck: string; wins: number; pct: number };

const SAMPLE = `Commander
1 Kang, el Embaucador

Deck
1 Gray Merchant of Asphodel
1 Go for the Throat
1 Night's Whisper
1 Damnation
1 Sol Ring
1 Arcane Signet
1 Command Tower
30 Swamp`;

function Tag({ r }: { r: Row }) {
  const map: Record<string, [string, string]> = {
    registry: ["#2f6b3a", "efecto"],
    basic: ["#3a3f4a", "básica"],
    scryfall: ["#3a5a8a", "stats reales"],
    missing: ["#7a3030", "no resuelta"],
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
  const [opponent, setOpponent] = useState("tricky");
  const [n, setN] = useState(200);
  const [busy, setBusy] = useState(false);
  const [sim, setSim] = useState<{ n: number; opponent: string; results: SimResult[] } | null>(null);
  const [lastPct, setLastPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [precons, setPrecons] = useState<Precon[]>([]);
  const [preconMsg, setPreconMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [opponents, setOpponents] = useState<string[]>(["kang", "tricky", "lorehold"]);
  const [profile, setProfileState] = useState("");
  const [savedDecks, setSavedDecks] = useState<SavedDeck[]>([]);
  const [deckName, setDeckName] = useState("");
  const [noStorage, setNoStorage] = useState(false);

  useEffect(() => {
    if (!storageAvailable()) {
      setNoStorage(true);
      return;
    }
    setProfileState(getProfile());
    setSavedDecks(listDecks());
  }, []);

  function currentDeckText(): string {
    if (!resolved) return text;
    const lines = ["Commander"];
    if (resolved.commander_name) lines.push(`1 ${resolved.commander_name}`);
    lines.push("", "Deck");
    for (const c of resolved.cards) if (c.qty > 0) lines.push(`${c.qty} ${c.name}`);
    return lines.join("\n");
  }

  function onSaveDeck() {
    const name =
      deckName.trim() || resolved?.commander_name || "Mi deck";
    setSavedDecks(saveDeck(name, currentDeckText()));
    setDeckName("");
  }

  function onLoadSaved(d: SavedDeck) {
    setText(d.text);
    setResolved(null);
    setSim(null);
    setLastPct(null);
  }

  function onDeleteSaved(id: string) {
    setSavedDecks(removeDeck(id));
  }

  function onProfileChange(v: string) {
    setProfileState(v);
    saveProfile(v);
  }

  useEffect(() => {
    fetch("/api/catalog")
      .then((r) => r.json())
      .then((d) => {
        const keys = (d.decks || []).map((x: { key: string }) => x.key);
        if (keys.length) {
          setOpponents(keys);
          setOpponent(keys.includes("tricky") ? "tricky" : keys[0]);
        }
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

  async function loadPrecon(fileName: string) {
    if (!fileName) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/precons?load=${encodeURIComponent(fileName)}`);
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
      setSim(null);
      setLastPct(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function postJson(action: string, extra: object) {
    const r = await fetch("/api/deck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...extra }),
    });
    const raw = await r.text();
    let d: { error?: string; [k: string]: unknown };
    try {
      d = JSON.parse(raw);
    } catch {
      throw new Error(`HTTP ${r.status} — respuesta no-JSON: ${raw.slice(0, 240)}`);
    }
    if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  }

  async function resolve() {
    setBusy(true);
    setError(null);
    setSim(null);
    try {
      const d = await postJson("resolve", { list: text });
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
    const cards = resolved.cards.filter((_, j) => j !== i);
    setResolved({ ...resolved, cards });
  }

  async function simulate() {
    if (!resolved?.commander_name) {
      setError("Falta el comandante (marca uno con *CMDR* o sección Commander).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const cards = resolved.cards.filter((c) => c.qty > 0).map((c) => ({ name: c.name, qty: c.qty }));
      const d = await postJson("simulate", {
        cards,
        commander: resolved.commander_name,
        opponent,
        n,
      });
      if (sim) {
        const prev = sim.results.find((x) => x.deck === "importado");
        setLastPct(prev ? prev.pct : null);
      }
      setSim(d as unknown as { n: number; opponent: string; results: SimResult[] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const myPct = sim?.results.find((r) => r.deck === "importado")?.pct ?? null;
  const delta = myPct != null && lastPct != null ? +(myPct - lastPct).toFixed(1) : null;
  const totalQty = resolved ? resolved.cards.reduce((s, c) => s + c.qty, 0) : 0;

  return (
    <div className="wrap">
      <header>
        <h1>🛠️ Editor de decks</h1>
        <p>
          Pegá tu lista (Moxfield / Archidekt / texto), resolvé las cartas, editá
          cantidades y <strong>probá variaciones</strong> midiendo la tasa de
          victoria. <Link href="/">← volver al simulador</Link>
        </p>
      </header>

      <div className="card">
        <h2>👤 Mi perfil (en este navegador)</h2>
        {noStorage ? (
          <p className="muted">
            Tu navegador bloquea el almacenamiento local (modo privado?), así que
            no puedo guardar decks acá. Igual podés pegar y simular.
          </p>
        ) : (
          <>
            <div className="row">
              <label>
                Nombre&nbsp;
                <input
                  value={profile}
                  onChange={(e) => onProfileChange(e.target.value)}
                  placeholder="tu nombre"
                  style={{
                    background: "var(--panel-2)", color: "var(--text)",
                    border: "1px solid var(--border)", borderRadius: 8,
                    padding: "8px 10px", width: 180,
                  }}
                />
              </label>
              <span className="muted">
                Tus decks se guardan solo en este dispositivo.
              </span>
            </div>

            <div className="row" style={{ marginTop: 12 }}>
              <input
                value={deckName}
                onChange={(e) => setDeckName(e.target.value)}
                placeholder={resolved?.commander_name || "nombre del deck"}
                style={{
                  background: "var(--panel-2)", color: "var(--text)",
                  border: "1px solid var(--border)", borderRadius: 8,
                  padding: "8px 10px", width: 220,
                }}
              />
              <button className="go" onClick={onSaveDeck}>
                Guardar deck actual
              </button>
              <span className="muted">
                guarda lo que tengas en el cuadro / la tabla editada
              </span>
            </div>

            {savedDecks.length > 0 && (
              <table style={{ marginTop: 14 }}>
                <thead>
                  <tr><th>Deck guardado</th><th>Actualizado</th><th></th></tr>
                </thead>
                <tbody>
                  {savedDecks.map((d) => (
                    <tr key={d.id}>
                      <td>{d.name}</td>
                      <td className="muted">
                        {new Date(d.updatedAt).toLocaleDateString()}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="ghost" style={{ padding: "4px 10px", marginRight: 6 }}
                          onClick={() => onLoadSaved(d)}>
                          Cargar
                        </button>
                        <button className="ghost" style={{ padding: "4px 8px" }}
                          onClick={() => onDeleteSaved(d.id)}>
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>0 · Cargar un precon oficial (opcional)</h2>
        {precons.length > 0 ? (
          <div className="row">
            <input
              placeholder="filtrar por nombre…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{
                background: "var(--panel-2)", color: "var(--text)",
                border: "1px solid var(--border)", borderRadius: 8,
                padding: "8px 10px", width: 200,
              }}
            />
            <select
              onChange={(e) => loadPrecon(e.target.value)}
              defaultValue=""
              style={{
                background: "var(--panel-2)", color: "var(--text)",
                border: "1px solid var(--border)", borderRadius: 8,
                padding: "8px 10px", maxWidth: 380,
              }}
            >
              <option value="">— elegí un precon ({precons.length}) —</option>
              {precons
                .filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()))
                .slice(0, 300)
                .map((p) => (
                  <option key={p.fileName} value={p.fileName}>
                    {p.name} · {p.releaseDate}
                  </option>
                ))}
            </select>
            <span className="muted">se carga en el cuadro de abajo</span>
          </div>
        ) : (
          <p className="muted">
            {preconMsg || "Cargando catálogo desde MTGJSON…"} (requiere internet;
            funciona en el deploy de Vercel)
          </p>
        )}
      </div>

      <div className="card">
        <h2>1 · Pegá la lista</h2>
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
          <button className="go" onClick={resolve} disabled={busy}>
            {busy ? "Resolviendo…" : "Resolver cartas"}
          </button>
          {resolved && (
            <span className="muted">
              {totalQty} cartas · {resolved.implemented} con efecto ·{" "}
              {resolved.missing.length} sin resolver
            </span>
          )}
        </div>
        {error && <p className="err">⚠ {error}</p>}
        {resolved && !resolved.scryfall_online && (
          <p className="muted">
            Scryfall no disponible en este entorno: solo resuelven cartas
            registradas y básicas. En Vercel se resuelven todas.
          </p>
        )}
      </div>

      {resolved && (
        <div className="card">
          <h2>2 · Editá el mazo</h2>
          {resolved.commander ? (
            <p>
              <strong>Comandante:</strong> {resolved.commander.name}{" "}
              <Tag r={resolved.commander} />
            </p>
          ) : (
            <p className="err">Sin comandante resuelto.</p>
          )}
          <table>
            <thead>
              <tr>
                <th>Cant.</th>
                <th>Carta</th>
                <th>Coste</th>
                <th>Tipo</th>
                <th>P/T</th>
                <th>Estado</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {resolved.cards.map((c, i) => (
                <tr key={i} style={{ opacity: c.qty === 0 ? 0.4 : 1 }}>
                  <td>
                    <input
                      type="number"
                      min={0}
                      value={c.qty}
                      onChange={(e) => setQty(i, Number(e.target.value))}
                      style={{ width: 56 }}
                    />
                  </td>
                  <td>{c.name}</td>
                  <td>{c.cost}</td>
                  <td className="muted">{c.type}</td>
                  <td>{c.pt}</td>
                  <td><Tag r={c} /></td>
                  <td>
                    <button className="ghost" style={{ padding: "4px 8px" }} onClick={() => remove(i)}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resolved && (
        <div className="card">
          <h2>3 · Probar variación</h2>
          <div className="row">
            <label>
              Rival&nbsp;
              <select
                value={opponent}
                onChange={(e) => setOpponent(e.target.value)}
                style={{
                  background: "var(--panel-2)", color: "var(--text)",
                  border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px",
                }}
              >
                {opponents.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </label>
            <label>
              Partidas&nbsp;
              <input type="number" min={1} max={2000} value={n}
                onChange={(e) => setN(Number(e.target.value))} />
            </label>
            <button className="go" onClick={simulate} disabled={busy}>
              {busy ? "Corriendo…" : "Simular"}
            </button>
          </div>

          {sim && (
            <div style={{ marginTop: 16 }}>
              {sim.results.map((r) => (
                <div className="bar-row" key={r.deck}>
                  <div className="bar-head">
                    <span className="deck">{r.deck}</span>
                    <span>{r.pct}% <span className="muted">({r.wins})</span></span>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${r.pct}%` }} />
                  </div>
                </div>
              ))}
              {delta != null && (
                <p style={{ marginTop: 8 }}>
                  Cambio vs corrida anterior del deck importado:{" "}
                  <strong style={{ color: delta >= 0 ? "var(--g)" : "var(--r)" }}>
                    {delta >= 0 ? "+" : ""}{delta} pts
                  </strong>
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <footer>
        Las cartas con efecto programado se simulan con sus habilidades; el resto
        usa stats reales de Scryfall (coste, P/T, tipos, keywords) — combate,
        maná y curva son fieles aunque el efecto especial no esté. No se inventan
        datos de cartas.
      </footer>
    </div>
  );
}
