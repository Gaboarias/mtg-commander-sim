// Sesión de cuenta (email + contraseña). Guardada en localStorage.
// Coexiste con el código anónimo: sin sesión, se usa el sync code de localDecks.
import { getSyncCode } from "./localDecks";

export type User = { id: string; email: string; is_admin: boolean; is_supporter: boolean };
type Session = { token: string; user: User };

const KEY = "mtgsim:session";

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function setSession(s: Session): void {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* modo privado */ }
}

export function clearSession(): void {
  try { localStorage.removeItem(KEY); } catch { /* */ }
}

export function getToken(): string {
  return getSession()?.token || "";
}

export function getUser(): User | null {
  return getSession()?.user || null;
}

// "owner key" efectiva para la nube: id de cuenta si hay sesión, si no el código anónimo.
export function effectiveCode(): string {
  const u = getUser();
  return u ? u.id : getSyncCode();
}
