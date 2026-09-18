"""Cliente de Scryfall (solo stdlib). Corre en Vercel (tiene internet).

Usa el endpoint /cards/collection: resuelve hasta 75 nombres por request, asi
un mazo de 100 cartas son ~2 llamadas. Devuelve dicts que
cardsdb.build_card_from_data entiende directamente (los campos coinciden con
Scryfall: mana_cost, type_line, power, toughness, keywords, color_identity).
"""
import json
import re
import urllib.request

_ENDPOINT = "https://api.scryfall.com/cards/collection"
_UA = "mtg-commander-sim/1.0 (https://github.com/Gaboarias/mtg-commander-sim)"


def _norm(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def _post(identifiers):
    body = json.dumps({"identifiers": identifiers}).encode("utf-8")
    req = urllib.request.Request(
        _ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_many(names):
    """names: iterable de nombres. Devuelve {nombre_norm: data} para los
    encontrados. Los faltantes simplemente no aparecen."""
    uniq = []
    seen = set()
    for n in names:
        k = _norm(n)
        if k and k not in seen:
            seen.add(k)
            uniq.append(n)
    out = {}
    for i in range(0, len(uniq), 75):
        chunk = uniq[i:i + 75]
        idents = [{"name": n} for n in chunk]
        try:
            data = _post(idents)
        except Exception:  # noqa: BLE001 (red caida / rate limit)
            continue
        for card in data.get("data", []):
            # cartas de doble cara: usar la cara frontal si hace falta
            if not card.get("type_line") and card.get("card_faces"):
                face = card["card_faces"][0]
                card = {**card, **face}
            out[_norm(card.get("name", ""))] = card
    return out


def make_fetch(names):
    """Devuelve un fetch(name)->dict que resuelve contra un cache precargado."""
    cache = resolve_many(names)
    def fetch(name):
        return cache.get(_norm(name))
    return fetch
