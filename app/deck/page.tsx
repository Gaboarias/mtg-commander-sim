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

const SAMPLE = `Commander
1 Kang, el Embaucador

Deck
1 Gray Merchant of Asphodel
1 Go for the Throat
1 Night's Whisper
1 Sol Ring
1 Arcane Signet
1 Command Tower
30 Swamp`;

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

  useEffect(() => {
    if (!storageAvailable()) {
      setNoStorage(true);
      return;
    }
    setProfileState(getProfile());
    setSavedDecks(listDecks());
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

  function onSaveDeck() {
    const name = deckName.trim() || resolved?.commander_name || "Mi deck";
    setSavedDecks(saveDeck(name, currentDeckText()));
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

  async function resolve() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/deck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "resolve", list: text }),
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
                  placeholder="tu nombre"
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
        <h2>1 · Traé tu lista</h2>
        <div className="row" style={{ marginBottom: 10, flexWrap: "wrap" }}>
          <span className="muted">Empezar desde:</span>
          {precons.length > 0 ? (
            <>
              <input
                placeholder="filtrar precon…"
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
          <button className="go" onClick={resolve} disabled={busy}>
            {busy ? "Revisando…" : "Revisar cartas"}
          </button>
          <span className="muted">
            pegá tu lista (Moxfield / Archidekt / «1 Nombre») con su comandante
          </span>
        </div>
        {error && <p className="err">⚠ {error}</p>}
      </div>

      {resolved && (
        <div className="card">
          <h2>2 · Revisá y editá</h2>
          {resolved.commander ? (
            <p>
              <strong>Comandante:</strong> {resolved.commander.name}{" "}
              <Tag r={resolved.commander} />
            </p>
          ) : (
            <p className="err">Falta el comandante (marcalo con una sección «Commander»).</p>
          )}
          <p className="muted">
            {totalQty} cartas · {resolved.implemented} con efecto programado ·{" "}
            {resolved.missing.length} no encontradas
          </p>
          {!resolved.scryfall_online && (
            <p className="muted">
              (Sin conexión a la base de cartas: solo se reconocen las cartas ya
              programadas y las tierras básicas. En el sitio publicado se
              reconocen todas.)
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>Cant.</th><th>Carta</th><th>Coste</th><th>Tipo</th>
                <th>F/R</th><th>Estado</th><th></th>
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
                  <td>{c.name}</td>
                  <td>{c.cost}</td>
                  <td className="muted">{c.type}</td>
                  <td>{c.pt}</td>
                  <td><Tag r={c} /></td>
                  <td>
                    <button className="ghost" style={{ padding: "4px 8px" }} onClick={() => remove(i)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resolved && !noStorage && (
        <div className="card">
          <h2>3 · Guardar en mis decks</h2>
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

      <footer>
        Las cartas con efecto programado se juegan con su habilidad; el resto usa
        sus datos reales (coste, fuerza, resistencia, tipos). No se inventan datos
        de cartas.
      </footer>
    </div>
  );
}
