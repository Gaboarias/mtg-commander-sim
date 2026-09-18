"""Catalogo de mazos precon de Commander desde MTGJSON (corre en Vercel).

- list_precons(): indice de precons (code, fileName, name, releaseDate).
- precon_to_text(fileName): baja el mazo y lo devuelve como decklist de texto
  (seccion Commander + lista), lista para cargar en el editor.

MTGJSON:
  indice  https://mtgjson.com/api/v5/DeckList.json
  mazo    https://mtgjson.com/api/v5/decks/<fileName>.json
"""
import json
import urllib.request

_INDEX = "https://mtgjson.com/api/v5/DeckList.json"
_DECK = "https://mtgjson.com/api/v5/decks/{}.json"
_UA = "mtg-commander-sim/1.0 (https://github.com/Gaboarias/mtg-commander-sim)"

_cache_index = None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_precons():
    global _cache_index
    if _cache_index is not None:
        return _cache_index
    data = _get(_INDEX).get("data", [])
    out = []
    for d in data:
        if "commander" in (d.get("type", "").lower()):
            out.append({
                "code": d.get("code"),
                "fileName": d.get("fileName"),
                "name": d.get("name"),
                "releaseDate": d.get("releaseDate"),
            })
    out.sort(key=lambda x: (x.get("releaseDate") or "", x.get("name") or ""),
             reverse=True)
    _cache_index = out
    return out


def precon_to_text(file_name):
    if not file_name or "/" in file_name or ".." in file_name:
        raise ValueError("fileName invalido")
    deck = _get(_DECK.format(file_name)).get("data", {})
    commanders = deck.get("commander", []) or []
    lines = ["Commander"]
    if commanders:
        for c in commanders:
            lines.append(f"1 {c.get('name')}")
    lines.append("")
    lines.append("Deck")
    for c in deck.get("mainBoard", []) or []:
        lines.append(f"{c.get('count', 1)} {c.get('name')}")
    return {
        "name": deck.get("name", file_name),
        "commander": commanders[0].get("name") if commanders else None,
        "text": "\n".join(lines),
    }
