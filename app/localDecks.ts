// Perfil y decks del usuario, guardados en el navegador (sin backend, sin login).
// Todo con try/catch: en modo privado / storage bloqueado no debe romper.

const PROFILE_KEY = "mtgsim:profile";
const DECKS_KEY = "mtgsim:decks";
const BINDER_KEY = "mtgsim:binder";

export type SavedDeck = {
  id: string;
  name: string;
  text: string; // decklist en texto (Commander + '1 Nombre'), re-resoluble
  colors?: string[]; // identidad de color (para los pips), ej. ["R","W"]
  updatedAt: number;
};

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function getProfile(): string {
  return read<string>(PROFILE_KEY, "");
}

export function setProfile(name: string): void {
  write(PROFILE_KEY, name);
}

export function listDecks(): SavedDeck[] {
  const decks = read<SavedDeck[]>(DECKS_KEY, []);
  return Array.isArray(decks) ? decks.sort((a, b) => b.updatedAt - a.updatedAt) : [];
}

export function saveDeck(name: string, text: string, colors?: string[], id?: string): SavedDeck[] {
  const decks = listDecks();
  const now = Date.now();
  if (id) {
    const i = decks.findIndex((d) => d.id === id);
    if (i >= 0) decks[i] = { ...decks[i], name, text, colors, updatedAt: now };
  } else {
    decks.push({
      id: `${now}-${Math.random().toString(36).slice(2, 8)}`,
      name,
      text,
      colors,
      updatedAt: now,
    });
  }
  write(DECKS_KEY, decks);
  return listDecks();
}

export function removeDeck(id: string): SavedDeck[] {
  write(DECKS_KEY, listDecks().filter((d) => d.id !== id));
  return listDecks();
}

// ---- Mi binder (colección personal de cartas) ---------------------------- //
export type BinderCard = { name: string; qty: number };

export function listBinder(): BinderCard[] {
  const b = read<BinderCard[]>(BINDER_KEY, []);
  return Array.isArray(b) ? b : [];
}

export function addToBinder(name: string, qty = 1): BinderCard[] {
  const b = listBinder();
  const i = b.findIndex((c) => c.name.toLowerCase() === name.toLowerCase());
  if (i >= 0) b[i] = { ...b[i], qty: b[i].qty + qty };
  else b.push({ name, qty });
  write(BINDER_KEY, b);
  return listBinder();
}

export function removeFromBinder(name: string): BinderCard[] {
  write(BINDER_KEY, listBinder().filter((c) => c.name.toLowerCase() !== name.toLowerCase()));
  return listBinder();
}

export function storageAvailable(): boolean {
  try {
    const k = "mtgsim:test";
    localStorage.setItem(k, "1");
    localStorage.removeItem(k);
    return true;
  } catch {
    return false;
  }
}
