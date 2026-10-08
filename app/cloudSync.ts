// Sync de decks + binder con la nube (/api/cloud). Único camino para subir/bajar:
// el editor de decks (autosave, Subir, Bajar) y el login (importar locales).
import { effectiveCode, getToken } from "./auth";
import {
  clearDeletedDecks,
  isCloudSynced,
  listBinder,
  listDecks,
  listDeletedDecks,
  markCloudSynced,
  mergeBinder,
  mergeDecks,
  type BinderCard,
  type SavedDeck,
} from "./localDecks";

async function post(body: Record<string, unknown>) {
  const r = await fetch("/api/cloud", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (d.error) throw new Error(d.error);
  return d;
}

export type PullResult = { decks: SavedDeck[]; binder: BinderCard[]; pulled: number };

// baja la nube de `code` (por defecto la propia) y la FUSIONA con lo local.
export async function cloudPull(code?: string): Promise<PullResult> {
  const own = effectiveCode();
  const c = (code || own).trim();
  const d = await post({ action: "pull", code: c, token: getToken() });
  const incoming = Array.isArray(d.decks) ? d.decks : [];
  const decks = mergeDecks(incoming);
  const binder = mergeBinder(Array.isArray(d.binder) ? d.binder : []);
  if (c === own) markCloudSynced(own);
  return { decks, binder, pulled: incoming.length };
}

export type PushResult = {
  decks: SavedDeck[]; binder: BinderCard[]; capped: boolean; limit?: number;
};

// sube decks + binder + borrados. Si este navegador todavía no fusionó la nube de
// esta cuenta, primero la baja: si no, un dispositivo nuevo (o vacío) la pisaría.
export async function cloudPush(): Promise<PushResult> {
  const own = effectiveCode();
  if (!isCloudSynced(own)) await cloudPull(own);
  const deleted = listDeletedDecks();
  const d = await post({
    action: "push", code: own, token: getToken(),
    decks: listDecks(), binder: listBinder(), deleted,
  });
  clearDeletedDecks(deleted);
  return { decks: listDecks(), binder: listBinder(), capped: !!d.capped, limit: d.limit };
}
