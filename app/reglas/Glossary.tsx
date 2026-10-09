"use client";
import { useEffect, useMemo, useState } from "react";
import { Icon } from "../icons";

export type GlossaryEntry = {
  n: string; t: string; d: string; r: string | null; o: string[]; c: number; s: number | null;
};

let _cache: Promise<GlossaryEntry[]> | null = null;
/** Glosario completo (public/rules/glossary.json), cargado una sola vez. */
export function loadGlossary(): Promise<GlossaryEntry[]> {
  if (!_cache) {
    _cache = fetch("/rules/glossary.json")
      .then((r) => (r.ok ? r.json() : { entries: [] }))
      .then((j) => j.entries as GlossaryEntry[])
      .catch(() => { _cache = null; return []; });
  }
  return _cache;
}

// acciones que son palabras comunes del texto (no hace falta explicarlas en cada carta)
const _PLAIN_ACTIONS = new Set([
  "activate", "attach", "cast", "counter", "create", "destroy", "discard", "double",
  "exchange", "exile", "fight", "play", "reveal", "sacrifice", "search", "shuffle",
  "tap", "untap", "triple", "vote", "transform", "regenerate", "heal",
]);

/** Habilidades del glosario que aparecen en el texto/keywords de una carta. */
export function keywordsIn(entries: GlossaryEntry[], text: string, keywords: string[] = []): GlossaryEntry[] {
  const low = text.toLowerCase();
  const kws = new Set(keywords.map((k) => k.toLowerCase().replace(/_/g, " ")));
  return entries.filter((e) => {
    const n = e.n.toLowerCase();
    if (kws.has(n)) return true;
    if (n.length < 4 || (e.t === "acción" && _PLAIN_ACTIONS.has(n))) return false;
    return new RegExp(`(^|[^a-z])${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z]|$)`).test(low);
  });
}

export function supportLabel(s: number | null): { txt: string; cls: string } {
  if (s === null) return { txt: "sin datos", cls: "sup-na" };
  if (s >= 0.75) return { txt: "el simulador la aplica", cls: "sup-ok" };
  if (s >= 0.3) return { txt: "soporte parcial", cls: "sup-mid" };
  return { txt: "todavía no la aplica", cls: "sup-no" };
}

const TYPES: [string, string][] = [
  ["", "Todas"], ["habilidad", "Habilidades"], ["acción", "Acciones"],
  ["palabra", "Palabras de habilidad"], ["mecánica", "Mecánicas"],
];

export default function Glossary() {
  const [all, setAll] = useState<GlossaryEntry[] | null>(null);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => { loadGlossary().then(setAll); }, []);

  const list = useMemo(() => {
    if (!all) return [];
    const t = q.trim().toLowerCase();
    return all
      .filter((e) => !type || e.t === type)
      .filter((e) => !t || e.n.toLowerCase().includes(t) || e.d.toLowerCase().includes(t))
      .sort((a, b) => {
        // la coincidencia por nombre primero, después las más usadas
        const an = t && a.n.toLowerCase().startsWith(t) ? 0 : 1;
        const bn = t && b.n.toLowerCase().startsWith(t) ? 0 : 1;
        return an - bn || b.c - a.c || a.n.localeCompare(b.n);
      });
  }, [all, q, type]);

  if (!all) return <p className="muted">Cargando glosario…</p>;
  return (
    <div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flex: "1 1 220px" }}>
          <Icon name="search" size={16} />
          <input
            type="search" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Buscá una habilidad: convoke, cascade, ward…"
            aria-label="Buscar habilidad" style={{ flex: 1, minWidth: 0 }}
          />
        </span>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Tipo">
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      <p className="muted" style={{ fontSize: ".8rem", margin: "0 0 10px" }}>
        {list.length} de {all.length}. Ordenadas por cuántas cartas las usan. Tocá una para
        ver la regla oficial.
      </p>
      <div className="gloss">
        {list.slice(0, q || type ? 400 : 60).map((e) => {
          const sup = supportLabel(e.s);
          const isOpen = open === e.n;
          return (
            <div key={e.n} className="combo gloss-item" style={{ margin: 0 }}>
              <button
                type="button" className="gloss-head" aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : e.n)}
              >
                <b>{e.n}</b>
                <span className="chip">{e.t}</span>
              </button>
              <div style={{ fontSize: ".86rem" }}>{e.d}</div>
              <div className="gloss-meta">
                <span className={`sup ${sup.cls}`}>{sup.txt}</span>
                {e.c > 0 && <span className="muted">{e.c.toLocaleString("es-AR")} cartas</span>}
              </div>
              {isOpen && (
                <div className="gloss-rule">
                  {e.r ? (
                    <>
                      <div className="muted" style={{ fontSize: ".75rem" }}>
                        Regla oficial {e.r} (Comprehensive Rules, en inglés)
                      </div>
                      {e.o.map((p, i) => <p key={i}>{p}</p>)}
                    </>
                  ) : (
                    <p className="muted">
                      No tiene regla propia: es un rótulo y el efecto está escrito en cada carta.
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {!q && !type && list.length > 60 && (
        <p className="muted" style={{ fontSize: ".8rem" }}>
          Mostrando las 60 más usadas. Buscá o filtrá por tipo para ver el resto.
        </p>
      )}
    </div>
  );
}
