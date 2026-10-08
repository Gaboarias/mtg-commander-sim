"""Baja de Scryfall los datos REALES (coste, tipos, P/T, keywords, oráculo) de las
cartas de los mazos de ejemplo y los guarda en data/preset_cards.json.

Los presets se arman con estos datos en vez de texto/estadísticas tipeadas a mano
(regla 5 de CLAUDE.md: nada inventado). Lo corre el workflow 'preset-cards'
(necesita red); localmente: python3 scripts/snapshot_preset_cards.py
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = os.path.join(ROOT, "data", "preset_card_names.txt")
OUT = os.path.join(ROOT, "data", "preset_cards.json")
KEYS = ("name", "mana_cost", "cmc", "type_line", "oracle_text", "power", "toughness",
        "loyalty", "keywords", "color_identity", "produced_mana", "layout")


def _post(identifiers):
    req = urllib.request.Request(
        "https://api.scryfall.com/cards/collection",
        data=json.dumps({"identifiers": identifiers}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "mtg-commander-sim/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    names = [n.strip() for n in open(NAMES, encoding="utf-8") if n.strip()]
    out, missing = {}, []
    for i in range(0, len(names), 75):
        chunk = names[i:i + 75]
        data = _post([{"name": n} for n in chunk])
        for c in data.get("data", []):
            row = {k: c.get(k) for k in KEYS}
            if c.get("card_faces"):
                row["card_faces"] = [{k: f.get(k) for k in KEYS} for f in c["card_faces"]]
            out[c["name"]] = row
            for f in c.get("card_faces") or []:          # 'Barkchannel Pathway'
                out.setdefault(f.get("name"), row)
        missing += [x.get("name") for x in data.get("not_found", [])]
        time.sleep(0.15)
    json.dump({"cards": out, "missing": sorted(set(missing))},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    print(f"{len(out)} cartas, {len(missing)} no encontradas: {missing}")
    return 0 if out else 2


if __name__ == "__main__":
    sys.exit(main())
