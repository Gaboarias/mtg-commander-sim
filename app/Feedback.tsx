"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "./icons";
import {
  getSyncCode, getGamesPlayed, getFeedbackState, markFeedbackDone,
  dismissFeedbackBubble, storageAvailable,
} from "./localDecks";

const OWNER_MAIL = "garias1989@gmail.com";
const BUBBLE_AT = 5;                 // partidas para la burbuja proactiva
const SNOOZE_MS = 3 * 24 * 3600 * 1000;  // no re-mostrar la burbuja por 3 días

// Widget global: botón flotante de feedback + burbuja proactiva tras 5 partidas.
// Montado en el layout, aparece en todas las páginas.
export default function Feedback() {
  const [open, setOpen] = useState(false);
  const [bubble, setBubble] = useState(false);
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [msg, setMsg] = useState("");
  const [contact, setContact] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // decidir si mostrar la burbuja proactiva (una vez montado, solo cliente)
  useEffect(() => {
    if (!storageAvailable()) return;
    const st = getFeedbackState();
    if (st.done) return;
    if (getGamesPlayed() < BUBBLE_AT) return;
    if (st.dismissedAt && Date.now() - st.dismissedAt < SNOOZE_MS) return;
    const t = setTimeout(() => setBubble(true), 1200);   // deja cargar la página
    return () => clearTimeout(t);
  }, []);

  // cerrar con Escape
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open]);

  function openForm() {
    setBubble(false);
    setOpen(true);
    setErr(null);
    setDone(false);
  }
  function closeBubble() {
    setBubble(false);
    try { dismissFeedbackBubble(); } catch { /* storage off */ }
  }

  async function submit() {
    if (!msg.trim() || sending) return;
    setSending(true);
    setErr(null);
    try {
      const r = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msg.trim(),
          rating: rating || null,
          contact: contact.trim(),
          page: typeof window !== "undefined" ? window.location.pathname : "",
          code: getSyncCode(),
        }),
      });
      const d = await r.json();
      if (d.ok) {
        try { markFeedbackDone(); } catch { /* storage off */ }
        setDone(true);
        setTimeout(() => setOpen(false), 1600);
      } else {
        setErr(d.error || "No se pudo enviar.");
      }
    } catch {
      setErr("No se pudo enviar (sin conexión).");
    } finally {
      setSending(false);
    }
  }

  const mailto =
    `mailto:${OWNER_MAIL}?subject=${encodeURIComponent("Feedback MTG Sim")}` +
    `&body=${encodeURIComponent(msg || "")}`;

  return (
    <>
      {/* burbuja proactiva */}
      <AnimatePresence>
        {bubble && !open && (
          <motion.div
            className="fb-bubble"
            initial={{ opacity: 0, y: 12, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.9 }}
            transition={{ type: "spring", stiffness: 380, damping: 26 }}
            role="dialog"
            aria-label="Invitación a dejar feedback"
          >
            <button className="fb-bubble-x" aria-label="Cerrar" onClick={closeBubble}>
              <Icon name="x" size={14} />
            </button>
            <p className="fb-bubble-t">¿Jugaste unas cuantas partidas? 🎉</p>
            <p className="fb-bubble-s">Contanos qué te gustó y qué mejorarías.</p>
            <button className="fb-bubble-cta" onClick={openForm}>Dejar mi opinión</button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* botón flotante */}
      <button className="fb-fab" onClick={openForm} aria-label="Enviar feedback" title="Feedback">
        <Icon name="star" size={16} />
        <span className="fb-fab-label">Feedback</span>
      </button>

      {/* modal */}
      <AnimatePresence>
        {open && (
          <motion.div
            className="fb-overlay"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
          >
            <motion.div
              className="fb-panel"
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 16, scale: 0.97 }}
              transition={{ type: "spring", stiffness: 340, damping: 28 }}
              onClick={(e) => e.stopPropagation()}
              role="dialog" aria-modal="true" aria-label="Formulario de feedback"
            >
              <button className="fb-close" aria-label="Cerrar" onClick={() => setOpen(false)}>
                <Icon name="x" size={18} />
              </button>

              {done ? (
                <div className="fb-thanks">
                  <Icon name="check-circle" size={40} />
                  <p>¡Gracias por tu opinión!</p>
                </div>
              ) : (
                <>
                  <h2 className="fb-title">Tu opinión</h2>
                  <p className="fb-sub">Ayudanos a mejorar el simulador. Toma 20 segundos.</p>

                  <div className="fb-stars" role="radiogroup" aria-label="Puntuación">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        className={`fb-star ${(hover || rating) >= n ? "on" : ""}`}
                        onMouseEnter={() => setHover(n)}
                        onMouseLeave={() => setHover(0)}
                        onClick={() => setRating(n === rating ? 0 : n)}
                        aria-label={`${n} de 5`}
                        aria-pressed={rating === n}
                      >
                        <Icon name="star" size={26} />
                      </button>
                    ))}
                  </div>

                  <textarea
                    className="fb-text"
                    value={msg}
                    onChange={(e) => setMsg(e.target.value)}
                    placeholder="¿Qué te gustó? ¿Qué falló o mejorarías? ¿Alguna carta o regla rara?"
                    rows={4}
                    maxLength={4000}
                    autoFocus
                  />
                  <input
                    className="fb-contact"
                    value={contact}
                    onChange={(e) => setContact(e.target.value)}
                    placeholder="Tu email (opcional, por si querés respuesta)"
                    maxLength={200}
                  />

                  {err && (
                    <p className="fb-err">
                      {err} — también podés escribir a{" "}
                      <a href={mailto}>{OWNER_MAIL}</a>.
                    </p>
                  )}

                  <div className="fb-actions">
                    <button className="fb-cancel" onClick={() => setOpen(false)}>Cancelar</button>
                    <button className="fb-send" onClick={submit} disabled={!msg.trim() || sending}>
                      {sending ? "Enviando…" : "Enviar"}
                    </button>
                  </div>
                </>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
