"""Cliente de Scryfall (solo stdlib). Corre en Vercel (tiene internet).

Usa el endpoint /cards/collection: resuelve hasta 75 nombres por request, asi
un mazo de 100 cartas son ~2 llamadas. Devuelve dicts que
cardsdb.build_card_from_data entiende directamente (los campos coinciden con
Scryfall: mana_cost, type_line, power, toughness, keywords, color_identity).
"""
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote

_ENDPOINT = "https://api.scryfall.com/cards/collection"
_BASE = "https://api.scryfall.com"
_UA = "mtg-commander-sim/1.0 (https://github.com/Gaboarias/mtg-commander-sim)"


def _norm(name):
    return re.sub(r"\s+", " ", name.strip().lower())


# Tope de nombres únicos por request y pausa entre lotes: Scryfall pide <=10 req/s
# y banea la IP/UA si se abusa (lo pagan todos los usuarios). 1200 alcanza para 6
# mazos de 100 o un binder grande; lo que pase del tope queda sin resolver.
MAX_NAMES = 1200
_BATCH_PAUSE = 0.1


def _post(identifiers):
    body = json.dumps({"identifiers": identifiers}).encode("utf-8")
    req = urllib.request.Request(
        _ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA,
                 "Accept": "application/json"})
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 429: respetar Retry-After (acotado) y reintentar UNA vez
            if exc.code != 429 or attempt:
                raise
            try:
                wait = float(exc.headers.get("Retry-After") or 1)
            except (TypeError, ValueError):
                wait = 1.0
            time.sleep(min(max(wait, 0.5), 3.0))


def _front_face(name):
    """'Dusk // Dawn' -> 'Dusk'. Sirve para reintentar contra Scryfall cuando el
    nombre combinado no matchea."""
    return re.split(r"\s*//\s*", name)[0].strip() if "//" in name else name


def _index(out, card):
    """Indexa una carta devuelta por Scryfall bajo su nombre completo Y bajo el
    de cada cara (asi 'Dusk // Dawn', 'Dusk' o 'Dawn' resuelven a la misma)."""
    full = card.get("name", "")
    if full:
        out[_norm(full)] = card
    for face in (card.get("card_faces") or []):
        fn = face.get("name")
        if fn:
            out.setdefault(_norm(fn), card)


def resolve_many(names):
    """names: iterable de nombres. Devuelve {nombre_norm: data} para los
    encontrados. Los faltantes simplemente no aparecen. Maneja cartas de doble
    cara / split (Dusk // Dawn) indexando por nombre completo y por cara, y
    reintentando por la cara frontal cuando el nombre combinado no matchea."""
    uniq = []
    seen = set()
    for n in names:
        if not isinstance(n, str):
            continue
        k = _norm(n)
        if k and k not in seen:
            seen.add(k)
            uniq.append(n)
            if len(uniq) >= MAX_NAMES:
                break
    out = {}
    for i in range(0, len(uniq), 75):
        chunk = uniq[i:i + 75]
        if i:
            time.sleep(_BATCH_PAUSE)
        try:
            data = _post([{"name": n} for n in chunk])
        except Exception:  # noqa: BLE001 (red caida / rate limit)
            continue
        for card in data.get("data", []):
            _index(out, card)

    # segunda pasada: nombres con '//' que no matchearon -> probar la cara frontal
    retry = [n for n in uniq if "//" in n and _norm(n) not in out]
    for i in range(0, len(retry), 75):
        chunk = retry[i:i + 75]
        time.sleep(_BATCH_PAUSE)
        try:
            data = _post([{"name": _front_face(n)} for n in chunk])
        except Exception:  # noqa: BLE001
            continue
        for card in data.get("data", []):
            _index(out, card)   # el nombre completo devuelto vuelve a mapear "Dusk // Dawn"
    return out


def make_fetch(names):
    """Devuelve un fetch(name)->dict que resuelve contra un cache precargado."""
    cache = resolve_many(names)
    def fetch(name):
        return cache.get(_norm(name))
    return fetch


# --------------------------------------------------------------------------- #
# Correccion de cartas no encontradas (#5)
# --------------------------------------------------------------------------- #

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def autocomplete(q):
    """Sugerencias de nombre (hasta 20) para un texto parcial/con typo."""
    if not q or not q.strip():
        return []
    try:
        data = _get(_BASE + "/cards/autocomplete?q=" + quote(q.strip()))
        return (data.get("data") or [])[:20]
    except Exception:  # noqa: BLE001
        return []


def named_fuzzy(q):
    """Mejor coincidencia difusa (una carta). Devuelve el dict o None."""
    if not q or not q.strip():
        return None
    try:
        return _get(_BASE + "/cards/named?fuzzy=" + quote(q.strip()))
    except Exception:  # noqa: BLE001
        return None


def by_collector(setcode, number):
    """Carta exacta por set + numero de coleccion. Devuelve el dict o None."""
    if not setcode or not number:
        return None
    try:
        # safe="": "/" y ".." no pueden cambiar la ruta pedida a Scryfall
        return _get(f"{_BASE}/cards/{quote(str(setcode).strip().lower(), safe='')}/"
                    f"{quote(str(number).strip(), safe='')}")
    except Exception:  # noqa: BLE001
        return None
