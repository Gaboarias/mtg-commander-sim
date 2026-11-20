"use client";

import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon, type IconName } from "../icons";

/* Centro de la mesa: lo que se está jugando ahora (la pila, la última jugada grande y
   un hilo con las jugadas recientes). Las decisiones del combate y las respuestas se
   dibujan acá mismo (llegan como `children`), para que la acción ocurra en el medio. */

export type TableEvent = {
  seq: number; turn: number; kind: "cast" | "land" | "ability" | "attack" | string;
  player: string | null; card: string | null; text?: string | null;
  targets?: { name: string; owner?: string | null; player?: boolean }[];
  attacks?: { defender: string; attackers: { name: string; power: number }[] }[];
};
export type StackItem = { name: string; controller: string | null; kind: string; targets: string[] };

const KIND_ICON: Record<string, IconName> = { cast: "bolt", land: "land", ability: "sparkles", attack: "swords" };

function verb(e: TableEvent, me: string): string {
  const you = e.player === me;
  switch (e.kind) {
    case "cast": return you ? "Lanzaste" : "lanza";
    case "land": return you ? "Jugaste" : "juega";
    case "attack": return you ? "Atacaste" : "ataca";
    default: return you ? "Tu habilidad" : "habilidad";
  }
}

function targetsTxt(e: TableEvent, me: string): string {
  const t = e.targets || [];
  if (!t.length) return "";
  return t.map((x) => x.player ? (x.name === me ? "vos" : x.name)
    : `${x.name}${x.owner ? (x.owner === me ? " (tuya)" : ` (${x.owner})`) : ""}`).join(", ");
}

function CardFace({ name, art, big }: { name: string; art?: string; big?: boolean }) {
  return (
    <div className={`tc-card ${big ? "big" : ""}`} title={name}>
      {art ? <div className="tc-art" style={{ backgroundImage: `url(${art})` }} />
        : <div className="tc-art ph"><span>{name}</span></div>}
      <div className="tc-name">{name}</div>
    </div>
  );
}

export function TableCenter({
  events, stack, me, active, turn, phaseLabel, art, reduce, children, onInspectName, banner,
}: {
  events: TableEvent[]; stack: StackItem[]; me: string; active: string; turn: number; phaseLabel: string;
  art: Record<string, string>; reduce: boolean; children?: React.ReactNode;
  onInspectName?: (name: string) => void; banner?: React.ReactNode;
}) {
  // la jugada destacada: la última que no sea una tierra (las tierras van solo al hilo)
  const spotlight = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].kind !== "land") return events[i];
    return events[events.length - 1];
  }, [events]);
  const recent = events.slice(-9).reverse();
  const fromTop = spotlight && spotlight.player !== me;

  return (
    <section className="table-center" aria-label="Centro de la mesa">
      <div className="tc-head">
        <motion.span className="tc-turn" key={turn}
          initial={reduce ? false : { scale: 1.25 }} animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 320, damping: 20 }}>Turno {turn}</motion.span>
        <span className="tc-phase">{phaseLabel}</span>
        {active && active !== me && phaseLabel.indexOf(active) < 0 && <span className="tc-active"><Icon name="play" size={10} /> {active}</span>}
      </div>

      {banner}

      {children ? (
        <div className="tc-panel">{children}</div>
      ) : (
        <div className="tc-stage">
          {stack.length > 0 && (
            <div className="tc-stack" aria-label="En la pila">
              <span className="tc-label"><Icon name="cards" size={12} /> En la pila</span>
              <div className="tc-stack-cards">
                {stack.map((s, k) => (
                  <motion.div key={k + s.name} className="tc-stack-item"
                    initial={reduce ? false : { opacity: 0, y: -20, rotate: -4 }}
                    animate={{ opacity: 1, y: 0, rotate: (k - stack.length / 2) * 3 }}>
                    <CardFace name={s.name} art={art[s.name]} />
                    <span className="tc-who">{s.controller === me ? "vos" : s.controller}</span>
                  </motion.div>
                ))}
              </div>
            </div>
          )}
          <AnimatePresence mode="popLayout">
            {spotlight ? (
              <motion.div key={spotlight.seq} className={`tc-spot ${spotlight.player === me ? "mine" : "theirs"}`}
                initial={reduce ? false : { opacity: 0, y: fromTop ? -70 : 70, scale: 0.85 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.9 }}
                transition={{ type: "spring", stiffness: 260, damping: 24 }}>
                {spotlight.card ? (
                  <button type="button" className="tc-spot-card" onClick={() => onInspectName?.(spotlight.card!)}
                    title="Ver carta">
                    <CardFace name={spotlight.card} art={art[spotlight.card]} big />
                  </button>
                ) : (
                  <div className="tc-spot-icon"><Icon name={KIND_ICON[spotlight.kind] || "sparkles"} size={40} /></div>
                )}
                <div className="tc-spot-txt">
                  <div className="tc-spot-who">
                    {spotlight.player === me ? "" : <b>{spotlight.player}</b>} {verb(spotlight, me)}
                  </div>
                  {spotlight.kind === "ability" && spotlight.text && <div className="tc-spot-line">{spotlight.text}</div>}
                  {spotlight.kind === "attack" && (spotlight.attacks || []).map((a, k) => (
                    <div key={k} className="tc-spot-line">
                      <Icon name="swords" size={12} /> {a.attackers.map((x) => `${x.name} (${x.power})`).join(", ")}
                      {" "}<Icon name="arrow-right" size={12} /> <b>{a.defender === me ? "vos" : a.defender}</b>
                    </div>
                  ))}
                  {targetsTxt(spotlight, me) && (
                    <div className="tc-spot-line tgt"><Icon name="target" size={12} /> {targetsTxt(spotlight, me)}</div>
                  )}
                </div>
              </motion.div>
            ) : (
              <motion.p key="empty" className="tc-empty muted">La mesa está tranquila: todavía nadie jugó nada.</motion.p>
            )}
          </AnimatePresence>
        </div>
      )}

      {recent.length > 1 && !children && (
        <ol className="tc-feed" aria-label="Jugadas recientes">
          {recent.slice(1).map((e) => (
            <li key={e.seq} className={`tc-ev k-${e.kind} ${e.player === me ? "mine" : ""}`}>
              <Icon name={KIND_ICON[e.kind] || "sparkles"} size={11} />
              <span className="tc-ev-who">{e.player === me ? "Vos" : e.player}</span>
              <span className="tc-ev-what">
                {e.kind === "attack"
                  ? `ataca a ${(e.attacks || []).map((a) => a.defender === me ? "vos" : a.defender).join(", ")}`
                  : e.kind === "ability" ? `${e.card}: ${(e.text || "").replace(/^habilidad: /, "")}`
                    : `${e.kind === "land" ? "juega" : "lanza"} ${e.card}`}
                {targetsTxt(e, me) ? ` → ${targetsTxt(e, me)}` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
