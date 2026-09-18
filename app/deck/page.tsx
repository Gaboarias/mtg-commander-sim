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
  generic?: boolean;
  can_command?: boolean;
  type: string;
  cost: string;
  pt: string;
  colors?: string[];
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
        <input value={q} onChange={(e) => setQ(e.target.value)} style={{ ...inp, width: 200 }} />
        <button className="ghost" onClick={search} disabled={busy}>Buscar</button>
        <span className="muted">o por set/#:</span>
        <input placeholder="set" value={setCode} onChange={(e) => setSetCode(e.target.value)} style={{ ...inp, width: 64 }} />
        <input placeholder="n°" value={num} onChange={(e) => setNum(e.target.value)} style={{ ...inp, width: 64 }} />
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
        <h2><span className="step">1</span> Traé tu lista</h2>
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
            placeholder="nombre del comandante"
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
                  <td>
                    <Tag r={c} />
                    {c.generic && (
                      <span style={{ background: "#5a4a2a", padding: "2px 6px", borderRadius: 6, fontSize: ".68rem", marginLeft: 4 }}>
                        aprox
                      </span>
                    )}
                  </td>
                  <td>
                    <button className="ghost" style={{ padding: "4px 8px" }} onClick={() => remove(i)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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

      <footer>
        Las cartas con efecto programado se juegan con su habilidad; el resto usa
        sus datos reales (coste, fuerza, resistencia, tipos). No se inventan datos
        de cartas.
      </footer>
    </div>
  );
}
