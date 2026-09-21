"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getUser, type User } from "./auth";
import { Icon } from "./icons";

const LINKS = [
  { href: "/", label: "Simulador" },
  { href: "/watch", label: "Ver partida" },
  { href: "/play", label: "Jugar" },
  { href: "/deck", label: "Editor de decks" },
  { href: "/reglas", label: "Reglas" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState("dark");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme || "dark");
  }, []);
  function toggle() {
    const next = (document.documentElement.dataset.theme || "dark") === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("mtgsim:theme", next);
    } catch {}
    setTheme(next);
  }
  return (
    <button
      className="theme-toggle"
      onClick={toggle}
      aria-label="Cambiar tema"
      title={theme === "light" ? "Modo oscuro" : "Modo claro"}
    >
      <Icon name={theme === "light" ? "moon" : "sun"} size={18} />
    </button>
  );
}

export default function Nav() {
  const path = usePathname();
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => { setUser(getUser()); }, [path]);
  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link href="/" className="nav-brand">
          <Icon name="cards" size={20} /> <span>MTG Commander Sim</span>
        </Link>
        <div className="nav-links">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`nav-link ${active ? "on" : ""}`}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
          {user?.is_admin && (
            <Link href="/admin" className={`nav-link ${path.startsWith("/admin") ? "on" : ""}`}>Admin</Link>
          )}
          <Link href="/login" className={`nav-link ${path.startsWith("/login") ? "on" : ""}`}>
            {user ? "Cuenta" : "Ingresar"}
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </nav>
  );
}
