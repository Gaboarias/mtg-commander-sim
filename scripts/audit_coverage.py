"""Auditoría de cobertura del parser sobre la base local de cartas.

Para cada carta de data/cards_db.json.gz arma la carta COMPLETA y, además, una
versión por cada línea de habilidad. Una línea está "sin efecto" si la carta armada
solo con esa línea no difiere en nada (ganchos, keywords, estáticas, costos…) de la
carta sin texto. Agrupa las líneas sin efecto por PATRÓN (nombre -> ~, números -> N,
maná -> {M}) y las ordena por cuántas cartas las usan.

    python3 scripts/audit_coverage.py            # resumen + docs/coverage_report.md
    python3 scripts/audit_coverage.py --json out.json
"""
import collections
import gzip
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cardsdb  # noqa: E402

DB = os.path.join(ROOT, "data", "cards_db.json.gz")
REPORT = os.path.join(ROOT, "docs", "coverage_report.md")

# líneas ESTRUCTURALES (reglas de mazo / restricciones de objetivo) o sin efecto de
# juego para la IA: no cuentan como faltantes
_STRUCTURAL = re.compile(
    r"^(?:enchant (?:creature|player|land|permanent|artifact|opponent|planeswalker"
    r"|creature you control|creature or vehicle|nonland permanent|[a-z ]+)$"
    r"|partner(?: with [^.]+)?$|partner—|friends forever$|choose a background$"
    r"|doctor's companion$|~ can be your commander|devoid$|changeling$"
    r"|you may look at the top card of your library any time"
    r"|play with the top card of your library revealed"
    r"|level \d|\d+/\d+$|\(|flavor)", re.I)


def load_db():
    with gzip.open(DB, "rt", encoding="utf-8") as f:
        return json.load(f)["cards"]


def _sig(card):
    out = {}
    for k, v in vars(card).items():
        if k in ("name",):
            continue
        if callable(v):
            out[k] = "fn"
        elif isinstance(v, dict):
            out[k] = tuple(sorted(map(str, v.keys())))
        elif isinstance(v, (set, frozenset, list, tuple)):
            out[k] = tuple(sorted(map(str, v)))
        else:
            out[k] = repr(v)
    return out


def _front(row):
    if row.get("card_faces") and not row.get("oracle_text"):
        f = dict(row["card_faces"][0])
        for k in ("color_identity", "keywords", "layout"):
            if k in row and k not in f:
                f[k] = row[k]
        return f
    return row


def _template(line, name):
    t = line.lower()
    for n in sorted({name.lower(), name.split(",")[0].lower()}, key=len, reverse=True):
        if n:
            t = t.replace(n, "~")
    t = re.sub(r"\{[^}]+\}", "{M}", t)
    t = re.sub(r"\b\d+\b", "N", t)
    t = re.sub(r"\b(?:one|two|three|four|five|six|seven|x)\b", "N", t)
    t = re.sub(r"[+-]N/[+-]N", "±N/±N", t)
    return t.strip()


def _is_keyword_line(line):
    words = [w.strip().lower() for w in re.split(r",|;", line) if w.strip()]
    kws = {k.replace("_", " ") for k in cardsdb.KEYWORDS}
    return bool(words) and all(re.sub(r"\s+\{.*|\s+\d+$", "", w) in kws for w in words)


def audit(db):
    lines_total = lines_bad = 0
    by_tpl = collections.Counter()
    tpl_examples = {}
    vanilla, partial, full = [], [], []
    for name, raw in db.items():
        row = _front(raw)
        oracle = cardsdb._strip_reminder(row.get("oracle_text") or "")
        if not oracle.strip():
            continue
        # base: SIN texto, sin keywords y sin maná producido; cada línea aporta solo
        # las keywords que nombra y el maná si dice "add"
        base_row = {k: v for k, v in row.items() if k not in ("produced_mana",)}
        base_row.update(oracle_text="", keywords=[])
        kw_all = row.get("keywords") or []
        try:
            base = _sig(cardsdb.build_card_from_data(base_row))
        except Exception:  # noqa: BLE001
            continue
        bad_here, n_here = [], 0
        try:
            full_sig = _sig(cardsdb.build_card_from_data(row))
        except Exception:  # noqa: BLE001
            full_sig = None
        all_lines = [x.strip() for x in cardsdb._ability_lines(oracle) if x.strip()]
        for ln in all_lines:
            if _STRUCTURAL.match(_template(ln, name)):
                continue
            n_here += 1
            try:
                lr = dict(base_row, oracle_text=ln,
                          keywords=[k for k in kw_all if k.lower() in ln.lower()])
                if re.search(r"\badd\b", ln, re.I) and row.get("produced_mana"):
                    lr["produced_mana"] = row["produced_mana"]
                c = cardsdb.build_card_from_data(lr)
                handled = _sig(c) != base
                if not handled and full_sig is not None and len(all_lines) > 1:
                    # ablación: quitar la línea de la carta completa cambia algo
                    rest = "\n".join(x for x in all_lines if x != ln)
                    c2 = cardsdb.build_card_from_data(dict(row, oracle_text=rest))
                    handled = _sig(c2) != full_sig
            except Exception:  # noqa: BLE001
                handled = False
            if not handled:
                bad_here.append(ln)
        if not n_here:
            continue
        lines_total += n_here
        lines_bad += len(bad_here)
        for ln in bad_here:
            t = _template(ln, name)
            by_tpl[t] += 1
            tpl_examples.setdefault(t, name)
        if len(bad_here) == n_here:
            vanilla.append(name)
        elif bad_here:
            partial.append(name)
        else:
            full.append(name)
    return {"lines_total": lines_total, "lines_bad": lines_bad, "by_tpl": by_tpl,
            "examples": tpl_examples, "vanilla": vanilla, "partial": partial, "full": full}


def write_report(res, path=REPORT, top=150):
    n = len(res["vanilla"]) + len(res["partial"]) + len(res["full"])
    pct = lambda a: 100 * a / max(1, n)  # noqa: E731
    out = [
        "# Cobertura del parser (base local de cartas)",
        "",
        f"- Cartas con texto: **{n}**",
        f"- Todas sus habilidades con efecto: **{len(res['full'])}** ({pct(len(res['full'])):.1f}%)",
        f"- Parciales (alguna habilidad sin efecto): **{len(res['partial'])}** ({pct(len(res['partial'])):.1f}%)",
        f"- Vainilla (ninguna habilidad con efecto): **{len(res['vanilla'])}** ({pct(len(res['vanilla'])):.1f}%)",
        f"- Líneas de habilidad sin efecto: **{res['lines_bad']} / {res['lines_total']}**",
        "",
        f"## Patrones sin efecto más frecuentes (top {top})",
        "",
        "| # | cartas | patrón | ejemplo |",
        "|---|---|---|---|",
    ]
    for i, (t, k) in enumerate(res["by_tpl"].most_common(top), 1):
        out.append(f"| {i} | {k} | {t.replace('|', '/')[:160]} | {res['examples'][t]} |")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def main(argv):
    res = audit(load_db())
    write_report(res)
    n = len(res["vanilla"]) + len(res["partial"]) + len(res["full"])
    print(f"cartas={n} completas={len(res['full'])} parciales={len(res['partial'])} "
          f"vainilla={len(res['vanilla'])} lineas_sin_efecto={res['lines_bad']}/{res['lines_total']}")
    if "--json" in argv:
        p = argv[argv.index("--json") + 1]
        json.dump({k: (dict(v) if isinstance(v, collections.Counter) else v)
                   for k, v in res.items()}, open(p, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
