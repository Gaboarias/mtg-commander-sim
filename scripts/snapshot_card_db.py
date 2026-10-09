"""Base de cartas LOCAL: baja de Scryfall el texto real de TODAS las cartas de los
precons (data/precons/decks/*.txt) y de los presets, y lo guarda comprimido en
data/cards_db.json.gz. El motor la consulta sin red (cardsdb.local_card) y la usa
la auditoría de cobertura (scripts/audit_coverage.py).

Lo corre el workflow 'card-db' (necesita red). Local: python3 scripts/snapshot_card_db.py
"""
import gzip
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "data", "cards_db.json.gz")
KEYS = ("name", "mana_cost", "cmc", "type_line", "oracle_text", "power", "toughness",
        "loyalty", "keywords", "color_identity", "produced_mana", "layout", "defense")


def _names():
    import decklist
    names = set()
    d = os.path.join(ROOT, "data", "precons", "decks")
    for fn in sorted(os.listdir(d)):
        p = decklist.parse_decklist(open(os.path.join(d, fn), encoding="utf-8").read())
        names.update(p.get("commanders") or [])
        names.update(n for _q, n in p["cards"])
    extra = os.path.join(ROOT, "data", "preset_card_names.txt")
    if os.path.exists(extra):
        names.update(n.strip() for n in open(extra, encoding="utf-8") if n.strip())
    return sorted(n for n in names if n)


def _post(identifiers):
    req = urllib.request.Request(
        "https://api.scryfall.com/cards/collection",
        data=json.dumps({"identifiers": identifiers}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "mtg-commander-sim/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001 (429/red: reintentar)
            time.sleep(2 * (attempt + 1))
    return {"data": [], "not_found": [{"name": i["name"]} for i in identifiers]}


def main():
    names = _names()
    out, missing = {}, []
    for i in range(0, len(names), 75):
        chunk = names[i:i + 75]
        data = _post([{"name": n.split(" // ")[0]} for n in chunk])
        for c in data.get("data", []):
            row = {k: c.get(k) for k in KEYS if c.get(k) not in (None, [], "")}
            if c.get("card_faces"):
                row["card_faces"] = [{k: f.get(k) for k in KEYS if f.get(k) not in (None, [], "")}
                                     for f in c["card_faces"]]
            out[c["name"]] = row
        missing += [x.get("name") for x in data.get("not_found", [])]
        time.sleep(0.12)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"cards": out, "missing": sorted(set(m for m in missing if m))}, f,
                  ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"{len(out)} cartas, {len(missing)} no encontradas")
    return 0 if out else 2


if __name__ == "__main__":
    sys.exit(main())
