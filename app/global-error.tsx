"use client";

import { useEffect } from "react";

// Boundary de último recurso (envuelve al layout raíz). Debe traer su propio
// <html>/<body>. Recarga sola ante un chunk viejo tras deploy.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const isChunk = /ChunkLoadError|Loading chunk|dynamically imported module|module script failed/i
    .test(`${error?.name} ${error?.message}`);

  useEffect(() => {
    if (!isChunk) return;
    try {
      const KEY = "mtgsim:reloaded-once";
      if (!sessionStorage.getItem(KEY)) { sessionStorage.setItem(KEY, "1"); location.reload(); }
    } catch { location.reload(); }
  }, [isChunk]);

  return (
    <html lang="es">
      <body style={{ background: "#0f1115", color: "#e8e8ea", fontFamily: "system-ui, sans-serif", padding: "48px 16px", textAlign: "center" }}>
        <h2>Algo falló al cargar</h2>
        <p style={{ opacity: 0.7 }}>
          {isChunk ? "Se actualizó el sitio. Recargando…" : "Ocurrió un error. Probá recargar la página."}
        </p>
        <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
          <button onClick={() => reset()} style={{ padding: "8px 16px", borderRadius: 8, cursor: "pointer" }}>Reintentar</button>
          <button onClick={() => location.reload()} style={{ padding: "8px 16px", borderRadius: 8, cursor: "pointer" }}>Recargar</button>
        </div>
      </body>
    </html>
  );
}
