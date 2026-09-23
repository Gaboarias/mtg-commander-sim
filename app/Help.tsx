"use client";

import { useState } from "react";

// "?" de ayuda accesible: tooltip nativo en desktop (hover) + popover al tocar
// (mobile). Reutilizable para explicar términos como "código de partida".
export function Help({ text, label }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="help-wrap">
      <button
        type="button"
        className="help-dot"
        aria-label={label ? `Ayuda: ${label}` : "Ayuda"}
        aria-expanded={open}
        title={text}
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
      >
        ?
      </button>
      {open && (
        <span className="help-pop" role="tooltip">
          {text}
        </span>
      )}
    </span>
  );
}

export default Help;
