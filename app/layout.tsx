import type { Metadata } from "next";
import "./globals.css";
import Nav from "./Nav";

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
          href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&display=swap"
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
      </body>
    </html>
  );
}
