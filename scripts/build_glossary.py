"""Glosario de habilidades para usuarios: explicación en castellano + regla oficial
(Comprehensive Rules 701/702) + qué tan bien la maneja el simulador.

    python3 scripts/build_glossary.py   -> public/rules/glossary.json
"""
import collections
import gzip
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

import cardsdb  # noqa: E402
from keywords_es import KEYWORDS_ES  # noqa: E402

OUT = os.path.join(ROOT, "public", "rules", "glossary.json")
SAMPLE = 25

# variantes que comparten la regla de otra habilidad
_RULE_ALIAS = {"cycling": re.compile(r"cycling$"), "landwalk": re.compile(r"walk$"),
               "hexproof": re.compile(r"^hexproof from$"), "ninjutsu": re.compile(r"ninjutsu$")}


_DECK_RULES = {"partner", "partner with", "choose a background", "doctor's companion",
               "friends forever", "commander tax", "commander damage"}


def _rule_for(name, rules):
    r = rules.get(name.lower())
    if r:
        return r
    for base, rx in _RULE_ALIAS.items():
        if rx.search(name.lower()) and base in rules:
            return rules[base]
    return None


def _support(name, cards_with):
    """Fracción de líneas con la habilidad que el motor convierte en algo."""
    ok = tot = 0
    rx = re.compile(r"\b" + re.escape(name.lower()) + r"\b")
    for row in cards_with[:SAMPLE]:
        row = cardsdb._prefer_front_face(row)
        base_row = {k: v for k, v in row.items() if k != "produced_mana"}
        base_row.update(oracle_text="", keywords=[])
        try:
            base = cardsdb._card_sig(cardsdb.build_card_from_data(base_row))
        except Exception:  # noqa: BLE001
            continue
        kws = row.get("keywords") or []
        for ln in cardsdb._ability_lines(row.get("oracle_text") or ""):
            if not rx.search(cardsdb._strip_reminder(ln).lower()):
                continue
            tot += 1
            try:
                c = cardsdb.build_card_from_data(dict(
                    base_row, oracle_text=ln,
                    keywords=[k for k in kws if k.lower() in ln.lower()]))
                ok += cardsdb._card_sig(c) != base
            except Exception:  # noqa: BLE001
                pass
    if not tot:
        return None
    return round(ok / tot, 2)


def main():
    rules = json.load(open(os.path.join(ROOT, "data", "rules_keywords.json"),
                           encoding="utf-8"))
    db = cardsdb.full_db()
    rows = {}
    for r in db.values():
        rows[r["name"]] = r
    by_kw = collections.defaultdict(list)
    for r in sorted(rows.values(), key=lambda r: r["name"]):
        for k in r.get("keywords") or []:
            by_kw[k.lower()].append(r)
    entries = []
    for name, (kind, text) in sorted(KEYWORDS_ES.items(), key=lambda x: x[0].lower()):
        rule = _rule_for(name, rules["keywords"])
        cw = by_kw.get(name.lower(), [])
        sup = _support(name, cw) if cw else None
        if name.lower() in _DECK_RULES:
            sup = 1.0  # regla de construcción de mazo: la aplica el validador
        official = []
        if rule:
            n = 0
            for p in rule["text"]:
                if n > 700:
                    break
                official.append(p)
                n += len(p)
        entries.append({
            "n": name, "t": kind, "d": text,
            "r": rule["rule"] if rule else None, "o": official,
            "c": len(cw), "s": sup,
        })
        print(f"{name:32} {kind:9} cartas={len(cw):5} soporte={sup}", file=sys.stderr)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"source": rules.get("source"), "entries": entries},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(entries)} entradas -> {OUT} ({os.path.getsize(OUT)//1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
