"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "./icons";

export type Perm = {
  uid: number; name: string; tapped: boolean; power: number | null; toughness: number | null;
  damage: number; counters: Record<string, number>; is_land: boolean; is_creature: boolean;
  is_token: boolean; attacking: boolean; sick: boolean;
  is_planeswalker?: boolean; loyalty?: number | null;
  loyalty_abilities?: { i: number; cost: number }[]; activated?: boolean;
  keywords?: string[]; types?: string[]; abilities?: string[];
};
export type PlayerState = {
  name: string; life: number; lost: boolean; hand: number; library: number;
  commander: string[]; cmdr_tax: number; cmdr_damage?: Record<string, number>;
  poison?: number; graveyard: string[]; battlefield: Perm[];
  hand_cards?: { i: number; name: string; is_land: boolean; cost: string }[];
};

export function CardMini({
  perm, art, reduce, selectable, selected, onClick, onInspect,
}: {
  perm: Perm; art?: string; reduce: boolean;
  selectable?: boolean; selected?: boolean; onClick?: () => void; onInspect?: () => void;
}) {
  const plus = perm.counters["+1/+1"] || 0;
  return (
    <motion.div
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, scale: 0.6, y: -8 }}
      animate={{ opacity: 1, scale: 1, y: 0, rotate: perm.tapped ? 9 : 0 }}
      exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.5, y: 10 }}
      transition={{ type: "spring", stiffness: 420, damping: 30 }}
      className={`cardmini ${perm.attacking ? "atk" : ""} ${selectable ? "sel-able" : ""} ${selected ? "sel" : ""}`}
      title={perm.name}
      onClick={onClick}
      style={onClick ? { cursor: "pointer" } : undefined}
    >
      {onInspect && (
        <button className="cm-info" title="Ver carta" aria-label="Ver detalle de la carta"
          onClick={(e) => { e.stopPropagation(); onInspect(); }}><Icon name="info" size={14} /></button>
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
      {plus > 0 && <span className="cm-counter">+{plus}</span>}
    </motion.div>
  );
}

export function Seat({
  p, active, art, reduce, selectableUids, selectedUids, onCard, onInspect,
}: {
  p: PlayerState; active: boolean; art: Record<string, string>; reduce: boolean;
  selectableUids?: Set<number>; selectedUids?: Set<number>; onCard?: (uid: number) => void;
  onInspect?: (perm: Perm) => void;
}) {
  const lands = p.battlefield.filter((x) => x.is_land);
  const nonlands = p.battlefield.filter((x) => !x.is_land);
  const maxCmdr = Math.max(0, ...Object.values(p.cmdr_damage || {}));
  return (
    <motion.div layout={!reduce} className={`seat ${active ? "active" : ""} ${p.lost ? "dead" : ""}`}>
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
        <motion.span key={"h" + p.hand} title="cartas en mano"
          initial={reduce ? false : { scale: 1.35, color: "var(--accent)" }}
          animate={{ scale: 1, color: "var(--muted)" }} transition={{ duration: 0.5 }}>
          <Icon name="hand" size={13} /> {p.hand}
        </motion.span>
        <motion.span key={"l" + p.library} title="cartas en biblioteca"
          initial={reduce ? false : { scale: 1.35, color: "var(--accent)" }}
          animate={{ scale: 1, color: "var(--muted)" }} transition={{ duration: 0.5 }}>
          <Icon name="library" size={13} /> {p.library}
        </motion.span>
        <span title="cementerio"><Icon name="grave" size={13} /> {p.graveyard.length}</span>
        <span title="comandante"><Icon name="crown" size={13} /> {p.commander.join(", ") || "—"}</span>
        {maxCmdr > 0 && (
          <span className={`cmdr-dmg ${maxCmdr >= 21 ? "fatal" : ""}`} title="daño de comandante recibido (21 elimina)">
            <Icon name="sword" size={13} /> {maxCmdr}/21
          </span>
        )}
        {(p.poison || 0) > 0 && (
          <span className={`poison ${(p.poison || 0) >= 10 ? "fatal" : ""}`} title="veneno (10 elimina)">
            <Icon name="poison" size={13} /> {p.poison}/10
          </span>
        )}
      </div>
      {nonlands.length > 0 && (
        <motion.div layout={!reduce} className="row-cards">
          <AnimatePresence>
            {nonlands.map((pm) => (
              <CardMini
                key={pm.uid} perm={pm} art={art[pm.name]} reduce={reduce}
                selectable={selectableUids?.has(pm.uid)}
                selected={selectedUids?.has(pm.uid)}
                onClick={onCard && selectableUids?.has(pm.uid) ? () => onCard(pm.uid) : undefined}
                onInspect={onInspect ? () => onInspect(pm) : undefined}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}
      {lands.length > 0 && (
        <motion.div layout={!reduce} className="row-cards lands">
          <AnimatePresence>
            {lands.map((pm) => (
              <CardMini key={pm.uid} perm={pm} art={art[pm.name]} reduce={reduce}
                onInspect={onInspect ? () => onInspect(pm) : undefined} />
            ))}
          </AnimatePresence>
        </motion.div>
      )}
      {p.battlefield.length === 0 && <p className="muted empty">sin permanentes</p>}
    </motion.div>
  );
}
