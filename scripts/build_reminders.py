"""Mapa habilidad clave -> texto recordatorio, sacado de la base completa de cartas
(el texto entre paréntesis que acompaña a la keyword). El motor lo usa cuando no
tiene implementada una habilidad: lee su recordatorio como una habilidad normal.

    python3 scripts/build_reminders.py   -> data/keyword_reminders.json
"""
import collections
import gzip
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "cards_full.json.gz")
OUT = os.path.join(ROOT, "data", "keyword_reminders.json")


def main():
    cards = json.load(gzip.open(SRC, "rt", encoding="utf-8"))["cards"]
    rem = collections.defaultdict(collections.Counter)
    for name, r in cards.items():
        faces = r.get("card_faces") or [r]
        kws = set(r.get("keywords") or [])
        for f in faces:
            for ln in (f.get("oracle_text") or "").split("\n"):
                m = re.match(r"^([A-Z][A-Za-z' -]+?)(?:[ —]+[^(]*?)? \(([^()]+)\)\s*$", ln)
                if not m or m.group(1) not in kws:
                    continue
                txt = m.group(2).strip()
                # solo recordatorios SIN parámetro propio de la carta (números/costes
                # varían); los con parámetro se leen de cada carta
                if re.search(r"\d|\{", ln.split("(")[0][len(m.group(1)):]):
                    continue
                nm = re.escape(f.get("name") or name)
                txt = re.sub(nm, "~", txt)
                rem[m.group(1)][txt] += 1
    out = {k: v.most_common(1)[0][0] for k, v in rem.items()}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
              sort_keys=True)
    print(f"{len(out)} recordatorios")


if __name__ == "__main__":
    sys.exit(main())
