"use client";

import { useEffect } from "react";

// Error boundary de ruta (App Router). Ante un chunk viejo tras un deploy
// (ChunkLoadError), recarga sola una vez; en cualquier otro error muestra un
// mensaje claro con botón de recargar en vez de la pantalla blanca de Next.
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const isChunk = /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported module|importing a module script failed/i
    .test(`${error?.name} ${error?.message}`);

  useEffect(() => {
    if (!isChunk) return;
    const KEY = "mtgsim:reloaded-once";
    try {
      if (!sessionStorage.getItem(KEY)) {
        sessionStorage.setItem(KEY, "1");
        location.reload();
      }
    } catch {
      location.reload();
    }
  }, [isChunk]);

  return (
    <div className="wrap">
      <div className="card" style={{ textAlign: "center" }}>
        <h2>Algo falló al cargar</h2>
        <p className="muted">
          {isChunk
            ? "Se actualizó el sitio. Recargando…"
            : "Ocurrió un error en esta vista. Probá recargar; si sigue, avisá."}
        </p>
        <div className="row" style={{ justifyContent: "center", gap: 8, marginTop: 8 }}>
          <button className="go" onClick={() => reset()}>Reintentar</button>
          <button className="ghost" onClick={() => location.reload()}>Recargar página</button>
        </div>
      </div>
    </div>
  );
}
