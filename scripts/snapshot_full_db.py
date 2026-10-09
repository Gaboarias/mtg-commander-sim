"""Base COMPLETA de cartas + reglas oficiales.

1) Scryfall bulk 'oracle_cards' (una entrada por carta, ~30k) -> filtra las que
   existen en papel y no son fichas/arte -> data/cards_full.json.gz (campos de juego).
2) Reglas Completas de Wizards (MagicCompRules*.txt) -> extrae 701 (acciones
   clave) y 702 (habilidades clave) -> data/rules_keywords.json
3) Catálogos de Scryfall (keyword-abilities / keyword-actions / ability-words).

Lo corre el workflow 'full-db' (necesita red). Local: python3 scripts/snapshot_full_db.py
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CARDS = os.path.join(ROOT, "data", "cards_full.json.gz")
OUT_RULES = os.path.join(ROOT, "data", "rules_keywords.json")
UA = {"User-Agent": "mtg-commander-sim/1.0", "Accept": "application/json"}
KEYS = ("name", "mana_cost", "cmc", "type_line", "oracle_text", "power", "toughness",
        "loyalty", "keywords", "color_identity", "produced_mana", "layout", "defense")
SKIP_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series", "vanguard",
                "scheme", "planar", "reversible_card"}


def _get(url, raw=False, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            return data if raw else json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def cards():
    bulk = _get("https://api.scryfall.com/bulk-data")
    entries = bulk.get("data") or []
    ent = next((b for b in entries if b.get("type") == "oracle_cards"), None)
    if ent is None:
        raise RuntimeError(f"bulk sin oracle_cards: {[b.get('type') for b in entries]}")
    uri = ent.get("download_uri")
    if not uri:
        print("claves del bulk:", sorted(ent.keys()))
        detail = _get(ent["uri"]) if ent.get("uri") else {}
        uri = detail.get("download_uri") or next(
            (v for v in list(ent.values()) + list(detail.values())
             if isinstance(v, str) and re.search(r"\.json(?:\.gz)?$", v)), None)
    if not uri:
        raise RuntimeError(f"no encontré el link de descarga: {ent}")
    raw = _get(uri, raw=True)
    if raw[:2] == b"\x1f\x8b":                  # vino comprimido
        raw = gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8"))
    out = {}
    for c in data:
        if c.get("layout") in SKIP_LAYOUTS or "paper" not in (c.get("games") or []):
            continue
        if (c.get("legalities") or {}).get("commander") == "not_legal" and \
                c.get("set_type") in ("funny", "memorabilia"):
            continue
        row = {k: c.get(k) for k in KEYS if c.get(k) not in (None, [], "")}
        row["legal"] = (c.get("legalities") or {}).get("commander", "not_legal")
        if c.get("card_faces"):
            row["card_faces"] = [{k: f.get(k) for k in KEYS if f.get(k) not in (None, [], "")}
                                 for f in c["card_faces"]]
        out[c["name"]] = row
    with gzip.open(OUT_CARDS, "wt", encoding="utf-8") as f:
        json.dump({"cards": out}, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"cartas: {len(out)}")


def _rules_txt():
    page = _get("https://magic.wizards.com/en/rules", raw=True).decode("utf-8", "replace")
    m = re.search(r'https://media\.wizards\.com/[^"\']+?MagicCompRules[^"\']*?\.txt', page)
    if not m:
        raise RuntimeError("no encontré el link a las Reglas Completas")
    url = m.group(0).replace(" ", "%20")
    raw = _get(url, raw=True)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), url
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), url


def rules():
    txt, url = _rules_txt()
    lines = [ln.rstrip() for ln in txt.replace("\r\n", "\n").split("\n")]
    # quedarnos con la sección de reglas (después del índice, antes del glosario)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("100.1."))
    end = next(i for i, ln in enumerate(lines) if ln.strip() == "Glossary" and i > start)
    body = lines[start:end]
    out = {}
    cur = None
    for ln in body:
        m = re.match(r"^(70[12])\.(\d+)\. (.+)$", ln)
        if m:
            cur = {"rule": f"{m.group(1)}.{m.group(2)}", "name": m.group(3).strip(),
                   "kind": "action" if m.group(1) == "701" else "ability", "text": []}
            out[cur["name"].lower()] = cur
            continue
        m2 = re.match(r"^(70[12])\.(\d+)[a-z]+\. (.+)$", ln)
        if m2 and cur is not None and f"{m2.group(1)}.{m2.group(2)}" == cur["rule"]:
            cur["text"].append(m2.group(3).strip())
            continue
        if re.match(r"^\d{3}\.", ln):
            cur = None
    for v in out.values():
        v["text"] = v["text"][:6]
    cats = {}
    for cat in ("keyword-abilities", "keyword-actions", "ability-words"):
        try:
            cats[cat] = _get(f"https://api.scryfall.com/catalog/{cat}")["data"]
        except Exception:  # noqa: BLE001
            cats[cat] = []
        time.sleep(0.15)
    json.dump({"source": url, "keywords": out, "catalogs": cats},
              open(OUT_RULES, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    print(f"reglas: {len(out)} habilidades/acciones clave")


def main():
    cards()
    try:
        rules()
    except Exception as e:  # noqa: BLE001
        print("reglas: falló", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
