import * as React from "react";

// Set de íconos SVG inline (estilo stroke, currentColor). Reemplazan a los emojis
// que se usaban como íconos. Decorativos por defecto (aria-hidden); pasá `label`
// cuando el ícono es el único contenido de un control accesible.

export type IconName =
  | "cards" | "sun" | "moon" | "x" | "close" | "download" | "upload"
  | "warning" | "arrow-right" | "arrow-down" | "crown" | "trophy" | "medal"
  | "heart" | "heart-fill" | "check" | "check-circle" | "target" | "skull"
  | "hand" | "library" | "grave" | "sword" | "swords" | "poison" | "user"
  | "edit" | "skip-back" | "skip-forward" | "play" | "pause" | "flask"
  | "flag" | "ban" | "refresh" | "lock" | "chart" | "film" | "brain"
  | "scroll" | "wrench" | "link" | "cloud" | "archive" | "gamepad"
  | "hourglass" | "undo" | "bolt" | "land" | "plus" | "search" | "info"
  | "chevron-left" | "chevron-right" | "star" | "sparkles";

// Cada entrada es el contenido interno del <svg viewBox="0 0 24 24">.
const P: Record<IconName, React.ReactNode> = {
  cards: <><rect x="3" y="5" width="13" height="16" rx="2" transform="rotate(-8 9.5 13)"/><rect x="9" y="4" width="13" height="16" rx="2" transform="rotate(6 15.5 12)"/></>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>,
  x: <path d="M18 6 6 18M6 6l12 12"/>,
  close: <path d="M18 6 6 18M6 6l12 12"/>,
  download: <><path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M5 21h14"/></>,
  upload: <><path d="M12 21V9"/><path d="m7 13 5-5 5 5"/><path d="M5 3h14"/></>,
  warning: <><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/></>,
  "arrow-right": <path d="M5 12h14M13 5l7 7-7 7"/>,
  "arrow-down": <path d="M12 5v14M5 12l7 7 7-7"/>,
  crown: <path d="M3 7l4 4 5-7 5 7 4-4-2 12H5L3 7Z"/>,
  trophy: <><path d="M7 4h10v4a5 5 0 0 1-10 0V4Z"/><path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3"/><path d="M9 17h6M10 20h4M12 13v4"/></>,
  medal: <><circle cx="12" cy="15" r="5"/><path d="M12 13v0M9 3l3 5 3-5"/><path d="m7 3 2 4M17 3l-2 4"/></>,
  heart: <path d="M12 20s-7-4.4-9.3-8.5C1.2 8.7 2.6 5.5 5.8 5.5c2 0 3.2 1.2 4.2 2.5 1-1.3 2.2-2.5 4.2-2.5 3.2 0 4.6 3.2 3.1 6C19 15.6 12 20 12 20Z"/>,
  "heart-fill": <path d="M12 20s-7-4.4-9.3-8.5C1.2 8.7 2.6 5.5 5.8 5.5c2 0 3.2 1.2 4.2 2.5 1-1.3 2.2-2.5 4.2-2.5 3.2 0 4.6 3.2 3.1 6C19 15.6 12 20 12 20Z" fill="currentColor" stroke="none"/>,
  check: <path d="M20 6 9 17l-5-5"/>,
  "check-circle": <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
  target: <><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.5" fill="currentColor"/></>,
  skull: <><path d="M12 3a8 8 0 0 0-5 14v3h10v-3a8 8 0 0 0-5-14Z"/><circle cx="9" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.4" fill="currentColor" stroke="none"/></>,
  hand: <path d="M8 11V5.5a1.5 1.5 0 0 1 3 0V10V4a1.5 1.5 0 0 1 3 0v6V5.5a1.5 1.5 0 0 1 3 0V13a6 6 0 0 1-6 6 6 6 0 0 1-5.2-3l-2.1-3.6a1.5 1.5 0 0 1 2.5-1.6L8 12Z"/>,
  library: <><path d="M5 4v16M9 4v16"/><rect x="12" y="4" width="4" height="16" rx="1"/><path d="M18 5l3 15"/></>,
  grave: <path d="M6 21V10a6 6 0 0 1 12 0v11M4 21h16M9 9h6M12 9v6"/>,
  sword: <path d="M14 3h7v7l-9 9-1-1 3-3-6-6-3 3-1-1 9-9Z"/>,
  swords: <><path d="M14.5 3H21v6.5L9 21H3v-6L14.5 3Z"/><path d="m16 16 5 5M5 3l4 4"/></>,
  poison: <><path d="M12 3c3.2 4.3 5.5 7 5.5 10a5.5 5.5 0 0 1-11 0c0-3 2.3-5.7 5.5-10Z"/><path d="M9.5 13.5a2.6 2.6 0 0 0 5 0"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  edit: <><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/></>,
  "skip-back": <path d="M19 5v14L9 12l10-7ZM5 5v14"/>,
  "skip-forward": <path d="M5 5v14l10-7L5 5ZM19 5v14"/>,
  play: <path d="M6 4v16l14-8L6 4Z"/>,
  pause: <path d="M8 5v14M16 5v14"/>,
  flask: <><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3"/><path d="M7.5 15h9"/></>,
  flag: <path d="M5 21V4h11l-1.5 4L16 12H5"/>,
  ban: <><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></>,
  refresh: <><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 4v5h-5"/></>,
  lock: <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>,
  film: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/></>,
  brain: <path d="M12 5a2.5 2.5 0 0 0-4.6-1.3A2.5 2.5 0 0 0 4.5 7 2.5 2.5 0 0 0 4 11a2.5 2.5 0 0 0 1.5 4.5A2.5 2.5 0 0 0 10 18a2 2 0 0 0 2-1.5V5Zm0 0a2.5 2.5 0 0 1 4.6-1.3A2.5 2.5 0 0 1 19.5 7 2.5 2.5 0 0 1 20 11a2.5 2.5 0 0 1-1.5 4.5A2.5 2.5 0 0 1 14 18a2 2 0 0 1-2-1.5"/>,
  scroll: <><path d="M7 4h11a2 2 0 0 1 2 2v11M5 4a2 2 0 0 0-2 2v1h4"/><path d="M20 17a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V7h14v10Z"/><path d="M8 10h7M8 14h5"/></>,
  wrench: <path d="M15 6a4 4 0 0 0-5 5L3 18l3 3 7-7a4 4 0 0 0 5-5l-2.5 2.5L14 9l1.5-3Z"/>,
  link: <><path d="M10 13a4 4 0 0 0 6 .5l2-2a4 4 0 0 0-5.7-5.7L11 7"/><path d="M14 11a4 4 0 0 0-6-.5l-2 2a4 4 0 0 0 5.7 5.7L13 17"/></>,
  cloud: <path d="M6.5 18a4.5 4.5 0 0 1-.5-9 6 6 0 0 1 11.6 1.5A3.8 3.8 0 0 1 17 18H6.5Z"/>,
  archive: <><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/></>,
  gamepad: <><rect x="2" y="7" width="20" height="11" rx="5.5"/><path d="M7 11v3M5.5 12.5h3"/><circle cx="15.5" cy="11.5" r="1.1" fill="currentColor" stroke="none"/><circle cx="18" cy="14" r="1.1" fill="currentColor" stroke="none"/></>,
  hourglass: <path d="M6 3h12M6 21h12M8 3c0 4 8 6 8 9s-8 5-8 9M16 3c0 4-8 6-8 9s8 5 8 9"/>,
  undo: <path d="M9 14 4 9l5-5M4 9h9a7 7 0 0 1 0 14h-3"/>,
  bolt: <path d="M13 2 4 14h7l-2 8 9-12h-7l2-8Z"/>,
  land: <path d="M3 20h18L14 8l-3 5-2-3-6 10Z"/>,
  plus: <path d="M12 5v14M5 12h14"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
  "chevron-left": <path d="M15 5l-7 7 7 7"/>,
  "chevron-right": <path d="M9 5l7 7-7 7"/>,
  star: <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 17l-5.2 2.6 1-5.8-4.3-4.1 5.9-.9L12 3.5Z"/>,
  sparkles: <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3ZM19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z"/>,
};

// Perilla global de tamaño: sube ~30% todos los íconos sin tocar los call sites.
// Si al verlo parece mucho/poco, ajustar acá (p. ej. 1.25 o 1.35).
const SCALE = 1.3;

export function Icon({
  name,
  size = 18,
  label,
  className,
  style,
  strokeWidth = 2.4,
}: {
  name: IconName;
  size?: number;
  label?: string;
  className?: string;
  style?: React.CSSProperties;
  strokeWidth?: number;
}) {
  const px = Math.round(size * SCALE);
  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      className={className}
      style={{ flex: "0 0 auto", verticalAlign: "-0.15em", display: "inline-block", ...style }}
    >
      {P[name]}
    </svg>
  );
}

export default Icon;
