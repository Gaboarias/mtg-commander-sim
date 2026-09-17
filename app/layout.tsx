import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
