"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "./icons";

export type Perm = {
  uid: number; name: string; tapped: boolean; power: number | null; toughness: number | null;
  damage: number; counters: Record<string, number>; is_land: boolean; is_creature: boolean;
  is_token: boolean; attacking: boolean; sick: boolean;
  is_planeswalker?: boolean; loyalty?: number | null;
  loyalty_abilities?: { i: number; cost: number }[]; activated?: boolean;
  keywords?: string[]; types?: string[]; subtypes?: string[]; abilities?: string[];
  attached_to?: number | null; attached_name?: string | null;   // equipo/aura anexado a…
};
// salida del campo registrada por el motor (destruida, exiliada, devuelta…)
export type Departure = {
  seq: number; turn: number; uid: number; name: string; player: string;
  kind: string; source?: string | null; creature?: boolean; token?: boolean;
};
export const LEAVE_LABEL: Record<string, string> = {
  destroyed: "destruida", died: "murió", sacrificed: "sacrificada", exiled: "exiliada",
  bounced: "a la mano", library: "a la biblioteca", gone: "deja el campo",
};
const LEAVE_MS = 1700;

export type PlayerState = {
  name: string; life: number; lost: boolean; hand: number; library: number;
  commander: string[]; cmdr_tax: number; cmdr_damage?: Record<string, number>;
  poison?: number; experience?: number; energy?: number;
  graveyard: string[]; exile?: string[]; battlefield: Perm[]; revealed?: string[];
  hand_cards?: { i: number; name: string; is_land: boolean; cost: string }[];
};

export function CardMini({
  perm, art, reduce, selectable, selected, onClick, onInspect, isCommander, leaving, leaveSource, targeted,
  attachedLabel,
}: {
  perm: Perm; art?: string; reduce: boolean;
  selectable?: boolean; selected?: boolean; onClick?: () => void; onInspect?: () => void;
  isCommander?: boolean;
  leaving?: string;            // se está yendo del campo (destroyed/exiled/…): se anima
  leaveSource?: string | null; // carta que lo causó
  targeted?: boolean;          // objetivo de un hechizo/habilidad en la pila
  attachedLabel?: string;      // "equipada a X" / "encanta a X" (anexado a otro permanente)
}) {
  const plus = perm.counters["+1/+1"] || 0;
  const minus = perm.counters["-1/-1"] || 0;
  const otherCounters = Object.entries(perm.counters || {})
    .filter(([k, v]) => k !== "+1/+1" && k !== "-1/-1" && k !== "loyalty" && v);
  const KW_SHORT: Record<string, string> = {
    flying: "vuela", reach: "alcance", first_strike: "1er golpe", double_strike: "doble",
    deathtouch: "mortal", trample: "arrolla", lifelink: "vínculo", vigilance: "vigila",
    haste: "prisa", menace: "amenaza", indestructible: "indes", hexproof: "antimal.",
    shroud: "velo", defender: "muro", flash: "destello", prowess: "prowess",
    infect: "infect", toxic: "toxic", wither: "wither", unblockable: "imbloq.",
    protection: "protec.",
  };
  const kws = (perm.keywords || []).filter((k) => KW_SHORT[k]);
  // doble golpe: resaltar la carta de forma especial (temporal o permanente da igual)
  const doubleStrike = (perm.keywords || []).includes("double_strike");
  return (
    <motion.div
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, scale: 0.6, y: -8 }}
      animate={{ opacity: 1, scale: 1, y: 0, rotate: perm.tapped ? 9 : 0 }}
      exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.5, y: 10 }}
      transition={{ type: "spring", stiffness: 420, damping: 30 }}
      className={`cardmini ${perm.attacking ? "atk" : ""} ${perm.tapped ? "tapped" : ""} ${selectable ? "sel-able" : ""} ${selected ? "sel" : ""} ${doubleStrike ? "dstrike" : ""} ${leaving ? `leaving lv-${leaving}${reduce ? " lv-static" : ""}` : ""} ${targeted ? "targeted" : ""}`}
      title={leaving ? `${perm.name}: ${LEAVE_LABEL[leaving] || "deja el campo"}${leaveSource ? ` (${leaveSource})` : ""}`
        : perm.tapped ? `${perm.name} (girada)` : perm.name}
      onClick={onClick}
      style={onClick ? { cursor: "pointer" } : undefined}
      // seleccionable con teclado (Tab + Enter/Espacio) para elegir atacantes
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-pressed={onClick ? !!selected : undefined}
      aria-label={onClick ? `${perm.name}${selected ? " (elegida)" : ""}` : undefined}
      onKeyDown={onClick ? (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); }
      } : undefined}
    >
      {leaving && (
        <div className={`cm-leave lv-${leaving}`} role="status">
          <span className="cm-leave-k">{LEAVE_LABEL[leaving] || "deja el campo"}</span>
          {leaveSource ? <span className="cm-leave-src">{leaveSource}</span> : null}
        </div>
      )}
      {attachedLabel && !leaving && (
        <span className="cm-badge att" title={attachedLabel}>
          <Icon name="link" size={9} /> {attachedLabel}
        </span>
      )}
      {targeted && !leaving && (
        <span className="cm-badge tgt" title="objetivo de un hechizo o habilidad en la pila">
          <Icon name="target" size={10} /> objetivo
        </span>
      )}
      {onInspect && !leaving && (
        <button className="cm-info" title="Ver carta" aria-label="Ver detalle de la carta"
          onClick={(e) => { e.stopPropagation(); onInspect(); }}><Icon name="info" size={14} /></button>
      )}
      {isCommander && (
        <span className="cm-badge cmdr" title="comandante"><Icon name="crown" size={10} /></span>
      )}
      {doubleStrike && (
        <span className="cm-badge ds" title="doble golpe (pega dos veces)">
          <Icon name="swords" size={9} /> ×2
        </span>
      )}
      {perm.is_token && <span className="cm-badge tok" title="ficha">ficha</span>}
      {perm.is_creature && perm.sick && (
        <span className="cm-badge sick" title="mareo de invocación (no puede atacar este turno)">zzz</span>
      )}
      {art ? (
        <div className="art" style={{ backgroundImage: `url(${art})` }} />
      ) : (
        <div className={`art ph ${perm.is_land ? "land" : perm.is_creature ? "crea" : "other"}`}>
          <span>{perm.name}</span>
        </div>
      )}
      <div className="cm-name">{perm.name}</div>
      {perm.is_creature && (
        <div className="cm-pt">
          {perm.power}/{perm.toughness}
          {perm.damage > 0 ? <span className="dmg"> −{perm.damage}</span> : null}
        </div>
      )}
      {perm.is_planeswalker && perm.loyalty != null && <span className="cm-loy">◆{perm.loyalty}</span>}
      {plus > 0 && <span className="cm-counter plus">+{plus}</span>}
      {minus > 0 && <span className="cm-counter minus">−{minus}</span>}
      {otherCounters.map(([k, v]) => (
        <span key={k} className="cm-counter other" title={k}>{v}·{k.slice(0, 3)}</span>
      ))}
      {kws.length > 0 && (
        <div className="cm-kws">
          {kws.map((k) => <span key={k} className="cm-kw" title={k}>{KW_SHORT[k]}</span>)}
        </div>
      )}
    </motion.div>
  );
}

// firma para agrupar fichas idénticas (debe reflejar todo lo que muestra CardMini)
function tokenSig(pm: Perm): string {
  return JSON.stringify([
    pm.name, pm.power, pm.toughness, pm.damage, pm.tapped, pm.sick, pm.attacking,
    pm.is_creature, pm.is_planeswalker, pm.loyalty ?? null,
    pm.counters || {}, (pm.keywords || []).slice().sort(),
  ]);
}

// pila de fichas idénticas: colapsada muestra una carta con ×N; clic la expande
function TokenStack({
  members, reduce, onInspect, isCommander,
}: {
  members: Perm[]; reduce: boolean;
  onInspect?: (pm: Perm) => void; isCommander?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (open) {
    return (
      <>
        <button type="button" className="stack-collapse" title="agrupar fichas iguales"
          onClick={() => setOpen(false)}>
          <Icon name="x" size={12} /> agrupar
        </button>
        {members.map((pm) => (
          <CardMini key={pm.uid} perm={pm} reduce={reduce} isCommander={isCommander}
            onInspect={onInspect ? () => onInspect(pm) : undefined} />
        ))}
      </>
    );
  }
  const rep = members[0];
  return (
    <div className="token-stack" title={`${members.length}× ${rep.name} — clic para expandir`}
      onClick={() => setOpen(true)} style={{ cursor: "pointer" }}>
      <span className="stack-count">×{members.length}</span>
      <CardMini perm={rep} reduce={reduce} isCommander={isCommander}
        onInspect={onInspect ? () => onInspect(rep) : undefined} />
    </div>
  );
}

type Ghost = { perm: Perm; kind: string; source?: string | null; at: number };

// permanentes que acaban de dejar el campo: se siguen dibujando ~1,7 s con una
// etiqueta animada (destruida / exiliada / a la mano…) en vez de desaparecer.
function useGhosts(p: PlayerState, departures: Departure[] | undefined, guess: boolean): Ghost[] {
  const prevRef = useRef<PlayerState>(p);
  const [ghosts, setGhosts] = useState<Ghost[]>([]);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = p;
    if (prev === p) return;
    const now = new Set(p.battlefield.map((x) => x.uid));
    const gone = prev.battlefield.filter((x) => !now.has(x.uid));
    if (gone.length === 0) return;
    const byUid = new Map((departures || []).map((d) => [d.uid, d]));
    const count = (arr: string[] | undefined, n: string) => (arr || []).filter((x) => x === n).length;
    const add: Ghost[] = [];
    const t = Date.now();
    for (const pm of gone) {
      const d = byUid.get(pm.uid);
      let kind = d?.kind;
      if (!kind) {
        if (!guess) continue;
        if (count(p.graveyard, pm.name) > count(prev.graveyard, pm.name)) kind = "died";
        else if (count(p.exile, pm.name) > count(prev.exile, pm.name)) kind = "exiled";
        else if (p.hand > prev.hand) kind = "bounced";
        else if (p.library > prev.library) kind = "library";
        else kind = pm.is_token ? "died" : "gone";
      }
      add.push({ perm: pm, kind, source: d?.source ?? null, at: t });
    }
    if (add.length === 0) return;
    setGhosts((g) => [...g.filter((x) => !add.some((a) => a.perm.uid === x.perm.uid) && !now.has(x.perm.uid)), ...add]);
    const ids = add.map((a) => a.perm.uid);
    // el timer NO se cancela si el estado cambia de nuevo enseguida (los bots
    // juegan rápido): si no, el fantasma quedaba pegado en la mesa
    timers.current.push(setTimeout(() => setGhosts((g) => g.filter((x) => !ids.includes(x.perm.uid))), LEAVE_MS));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p]);
  useEffect(() => () => { timers.current.forEach(clearTimeout); }, []);
  // un fantasma que volvió al campo (mismo uid) deja de mostrarse
  return ghosts.filter((g) => !p.battlefield.some((x) => x.uid === g.perm.uid));
}

export function Seat({
  p, active, art, reduce, selectableUids, selectedUids, onCard, onInspect, onZone, variant = "grid",
  departures, guessDepartures = false, targetedUids,
}: {
  p: PlayerState; active: boolean; art: Record<string, string>; reduce: boolean;
  selectableUids?: Set<number>; selectedUids?: Set<number>; onCard?: (uid: number) => void;
  onInspect?: (perm: Perm) => void; onZone?: (title: string, names: string[]) => void;
  variant?: "grid" | "hero" | "mini";
  departures?: Departure[]; guessDepartures?: boolean; targetedUids?: Set<number>;
}) {
  const ghosts = useGhosts(p, departures, guessDepartures);
  const ghostBy = new Map(ghosts.map((g) => [g.perm.uid, g]));
  const field = [...p.battlefield, ...ghosts.map((g) => g.perm)];
  const lands = field.filter((x) => x.is_land);
  const nonlands = field.filter((x) => !x.is_land);
  const maxCmdr = Math.max(0, ...Object.values(p.cmdr_damage || {}));
  return (
    <motion.div layout={!reduce} className={`seat seat-${variant} ${active ? "active" : ""} ${p.lost ? "dead" : ""}`}>
      <div className="seat-head">
        <span className="seat-name">
          {p.lost ? <Icon name="skull" size={13} /> : active ? <Icon name="play" size={11} /> : null}
          {(p.lost || active) ? " " : ""}{p.name}
          {p.lost && <span className="dead-badge">eliminado</span>}
        </span>
        <motion.span
          key={p.life}
          initial={reduce ? false : { scale: 1.35 }}
          animate={{ scale: 1 }}
          transition={{ duration: 0.35 }}
          className={`life ${p.life <= 10 ? "low" : ""}`}
        >
          <Icon name="heart-fill" size={13} /> {p.life}
        </motion.span>
      </div>
      <div className="seat-meta">
        {onZone && p.revealed ? (
          <button type="button" className="zone-chip" title="mano revelada: ver cartas"
            onClick={() => onZone(`Mano de ${p.name} (revelada)`, p.revealed || [])}>
            <Icon name="hand" size={13} /> {p.hand}
          </button>
        ) : (
          <motion.span key={"h" + p.hand} title="cartas en mano"
            initial={reduce ? false : { scale: 1.35, color: "var(--accent)" }}
            animate={{ scale: 1, color: "var(--muted)" }} transition={{ duration: 0.5 }}>
            <Icon name="hand" size={13} /> {p.hand}
          </motion.span>
        )}
        <motion.span key={"l" + p.library} title="cartas en biblioteca"
          initial={reduce ? false : { scale: 1.35, color: "var(--accent)" }}
          animate={{ scale: 1, color: "var(--muted)" }} transition={{ duration: 0.5 }}>
          <Icon name="library" size={13} /> {p.library}
        </motion.span>
        {onZone && p.graveyard.length > 0 ? (
          <button type="button" className="zone-chip" title="ver cementerio"
            onClick={() => onZone(`Cementerio de ${p.name}`, p.graveyard)}>
            <Icon name="grave" size={13} /> {p.graveyard.length}
          </button>
        ) : (
          <span title="cementerio"><Icon name="grave" size={13} /> {p.graveyard.length}</span>
        )}
        {(p.exile?.length || 0) > 0 && (
          onZone ? (
            <button type="button" className="zone-chip" title="ver exilio"
              onClick={() => onZone(`Exilio de ${p.name}`, p.exile || [])}>
              <Icon name="x" size={13} /> {p.exile!.length}
            </button>
          ) : (
            <span title="exilio"><Icon name="x" size={13} /> {p.exile!.length}</span>
          )
        )}
        <span title="comandante"><Icon name="crown" size={13} /> {p.commander.join(", ") || "—"}</span>
      </div>
      {/* chips de ESTADO destacados: peligros (veneno, daño de comandante) y recursos
          (experiencia, energía). Solo aparecen cuando hay algo que mostrar. */}
      {(maxCmdr > 0 || (p.poison || 0) > 0 || (p.experience || 0) > 0 || (p.energy || 0) > 0) && (
        <div className="seat-status">
          {(p.poison || 0) > 0 && (
            <span className={`status-chip danger ${(p.poison || 0) >= 8 ? "near" : ""} ${(p.poison || 0) >= 10 ? "fatal" : ""}`}
              title="veneno (10 elimina)">
              <Icon name="poison" size={12} /> {p.poison}/10 veneno
            </span>
          )}
          {/* daño de comandante RECIBIDO, uno por comandante (21 de un mismo comandante elimina) */}
          {Object.entries(p.cmdr_damage || {}).filter(([, v]) => v > 0)
            .sort((a, b) => b[1] - a[1]).map(([src, v]) => (
              <span key={src} className={`status-chip danger ${v >= 18 ? "near" : ""} ${v >= 21 ? "fatal" : ""}`}
                title={`daño de comandante recibido de ${src}: ${v} (21 de un mismo comandante elimina)`}>
                <Icon name="sword" size={12} /> {v}/21 {src.split(",")[0].split(" (")[0]}
              </span>
            ))}
          {(p.experience || 0) > 0 && (
            <span className="status-chip res" title="contadores de experiencia">
              <Icon name="medal" size={12} /> {p.experience} exp
            </span>
          )}
          {(p.energy || 0) > 0 && (
            <span className="status-chip res" title="contadores de energía">
              <Icon name="bolt" size={12} /> {p.energy} energía
            </span>
          )}
        </div>
      )}
      {nonlands.length > 0 && (() => {
        // agrupar fichas idénticas en una pila; lo que requiere interacción propia
        // (seleccionable/seleccionada) o no es ficha se dibuja individual
        const individuals: Perm[] = [];
        const groups = new Map<string, Perm[]>();
        // equipos/auras anexados a una criatura de ESTA mesa: se dibujan pegados a ella
        const hostUids = new Set(nonlands.map((x) => x.uid));
        const attachedBy = new Map<number, Perm[]>();
        for (const pm of nonlands) {
          if (pm.attached_to != null && hostUids.has(pm.attached_to) && pm.attached_to !== pm.uid) {
            (attachedBy.get(pm.attached_to) || attachedBy.set(pm.attached_to, []).get(pm.attached_to)!).push(pm);
          }
        }
        const isAttached = (pm: Perm) => pm.attached_to != null && attachedBy.get(pm.attached_to)?.includes(pm);
        const attLabel = (pm: Perm) => pm.attached_name
          ? `${(pm.subtypes || []).some((x) => x.toLowerCase() === "aura") ? "en" : "equipa a"} ${pm.attached_name}` : undefined;
        for (const pm of nonlands) {
          if (isAttached(pm)) continue;
          if (attachedBy.has(pm.uid)) { individuals.push(pm); continue; }
          const interactive = selectableUids?.has(pm.uid) || selectedUids?.has(pm.uid)
            || ghostBy.has(pm.uid) || targetedUids?.has(pm.uid);
          if (pm.is_token && !interactive) {
            const sig = tokenSig(pm);
            (groups.get(sig) || groups.set(sig, []).get(sig)!).push(pm);
          } else {
            individuals.push(pm);
          }
        }
        const stacks = [...groups.values()];
        return (
          <motion.div layout={!reduce} className="row-cards">
            <AnimatePresence>
              {individuals.map((pm) => {
                const card = (x: Perm, extra?: { attachedLabel?: string }) => (
                  <CardMini
                    key={x.uid} perm={x} art={x.is_token ? undefined : art[x.name]} reduce={reduce}
                    selectable={!ghostBy.has(x.uid) && selectableUids?.has(x.uid)}
                    selected={selectedUids?.has(x.uid)}
                    isCommander={p.commander.includes(x.name)}
                    onClick={onCard && !ghostBy.has(x.uid) && selectableUids?.has(x.uid) ? () => onCard(x.uid) : undefined}
                    onInspect={onInspect && !ghostBy.has(x.uid) ? () => onInspect(x) : undefined}
                    leaving={ghostBy.get(x.uid)?.kind}
                    leaveSource={ghostBy.get(x.uid)?.source}
                    targeted={targetedUids?.has(x.uid)}
                    attachedLabel={extra?.attachedLabel}
                  />
                );
                const atts = attachedBy.get(pm.uid);
                if (!atts) return card(pm, { attachedLabel: attLabel(pm) });
                // la criatura con lo que tiene anexado, agrupado (los equipos asoman debajo)
                return (
                  <motion.div key={pm.uid} layout={!reduce} className="attach-group"
                    title={`${pm.name} + ${atts.map((a) => a.name).join(", ")}`}>
                    {card(pm)}
                    <div className="attach-list">
                      {atts.map((a) => (
                        <div key={a.uid} className="attach-item">{card(a, { attachedLabel: attLabel(a) })}</div>
                      ))}
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
            {stacks.map((members) => (
              members.length === 1 ? (
                <CardMini
                  key={members[0].uid} perm={members[0]} reduce={reduce}
                  isCommander={p.commander.includes(members[0].name)}
                  onInspect={onInspect ? () => onInspect(members[0]) : undefined}
                />
              ) : (
                <TokenStack
                  key={tokenSig(members[0])} members={members} reduce={reduce}
                  isCommander={p.commander.includes(members[0].name)}
                  onInspect={onInspect}
                />
              )
            ))}
          </motion.div>
        );
      })()}
      {lands.length > 0 && (
        <motion.div layout={!reduce} className="row-cards lands">
          <AnimatePresence>
            {lands.map((pm) => (
              <CardMini key={pm.uid} perm={pm} art={pm.is_token ? undefined : art[pm.name]} reduce={reduce}
                isCommander={p.commander.includes(pm.name)}
                onInspect={onInspect && !ghostBy.has(pm.uid) ? () => onInspect(pm) : undefined}
                leaving={ghostBy.get(pm.uid)?.kind} leaveSource={ghostBy.get(pm.uid)?.source}
                targeted={targetedUids?.has(pm.uid)} />
            ))}
          </AnimatePresence>
        </motion.div>
      )}
      {p.battlefield.length === 0 && <p className="muted empty">sin permanentes</p>}
    </motion.div>
  );
}
