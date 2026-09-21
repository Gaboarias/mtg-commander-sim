import type { Metadata } from "next";
import "./globals.css";
import Nav from "./Nav";
import { KOFI_URL, PAYPAL_URL, HOSTINGER_URL } from "./support";

export const metadata: Metadata = {
  title: "MTG Commander Sim",
  description:
    "Motor de simulacion de Magic: The Gathering (Commander) en Python puro, con interfaz web. Corre miles de partidas y mide tasas de victoria.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('mtgsim:theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}",
          }}
        />
      </head>
      <body>
        <Nav />
        {children}
        <div style={{ textAlign: "center", padding: "24px 16px 40px" }}>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap", marginBottom: 14 }}>
            <a href={KOFI_URL} target="_blank" rel="noreferrer"
               style={{ padding: "8px 16px", borderRadius: 999, background: "var(--accent, #d8b23a)", color: "#1a1400", fontWeight: 700, textDecoration: "none" }}>
              💛 Apoyar en Ko-fi
            </a>
            <a href={PAYPAL_URL} target="_blank" rel="noreferrer"
               style={{ padding: "8px 16px", borderRadius: 999, border: "1px solid var(--border, #3a4150)", color: "inherit", textDecoration: "none" }}>
              Apoyar por PayPal
            </a>
            <a href={HOSTINGER_URL} target="_blank" rel="noreferrer sponsored"
               title="Contratá hosting con Hostinger — ayuda a mantener el dominio online"
               style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 14px", borderRadius: 999, border: "1px solid var(--border, #3a4150)", textDecoration: "none" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/hostinger.svg" alt="Hostinger" height={20} style={{ height: 20 }} />
              <span style={{ fontSize: ".82rem", color: "var(--muted)" }}>ayuda a mantener el dominio</span>
            </a>
          </div>
          <div style={{ fontSize: ".8rem", color: "var(--muted)", maxWidth: 640, margin: "0 auto", lineHeight: 1.5 }}>
            El sitio es gratis; apoyar banca la infraestructura, no la IP de MTG.
            {" "}Datos de cartas: <a href="https://scryfall.com" target="_blank" rel="noreferrer">Scryfall</a> ·
            {" "}Combos: <a href="https://commanderspellbook.com" target="_blank" rel="noreferrer">Commander Spellbook</a>.
            {" "}Proyecto fan, no afiliado a Wizards of the Coast. Contenido bajo su Fan Content Policy.
          </div>
        </div>
      </body>
    </html>
  );
}
