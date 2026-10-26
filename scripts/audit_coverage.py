"""Auditoría de cobertura del parser sobre la base local de cartas.

Para cada carta de data/cards_db.json.gz arma la carta COMPLETA y, además, una
versión por cada línea de habilidad. Una línea está "sin efecto" si la carta armada
solo con esa línea no difiere en nada (ganchos, keywords, estáticas, costos…) de la
carta sin texto. Agrupa las líneas sin efecto por PATRÓN (nombre -> ~, números -> N,
maná -> {M}) y las ordena por cuántas cartas las usan.

    python3 scripts/audit_coverage.py            # resumen + docs/coverage_report.md
    python3 scripts/audit_coverage.py --json out.json
    python3 scripts/audit_coverage.py --full --jobs 4   # en paralelo
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
    r"|creature you control|creature or vehicle|nonland permanent|[a-z -]+)$"
    r"|partner(?: with [^.]+)?$|partner—|friends forever$|choose a background$"
    r"|doctor's companion$|~ can be your commander|devoid$|changeling$"
    r"|you may look at the top card of your library any time"
    r"|play with the top card of your library revealed"
    r"|level (?:\d|n)|(?:\d+|n)/(?:\d+|n)$|\(|flavor"
    # reglas de draft / ante: sin efecto en una partida de Commander
    r"|draft ~ face up|draft this card face up|reveal (?:this card|~) as you draft"
    r"|remove (?:this card|~) from your deck before playing if you're not playing for ante)", re.I)


FULL = os.path.join(ROOT, "data", "cards_full.json.gz")

# tipos que NO van en un mazo de Commander: se excluyen de la auditoría
_NON_DECK = re.compile(r"\b(?:Plane|Phenomenon|Scheme|Vanguard|Dungeon|Stickers|Attraction|Conspiracy|"
                       r"Emblem)\b")


def load_db(full=False):
    with gzip.open(FULL if full else DB, "rt", encoding="utf-8") as f:
        return json.load(f)["cards"]


_ADDR = re.compile(r" at 0x[0-9a-f]+")


def _sig(card):
    out = {}
    for k, v in vars(card).items():
        if k in ("name",):
            continue
        if k == "produces" and callable(v):
            # maná de tierras: comparar lo que produce de verdad (no solo "fn")
            try:
                out[k] = repr(sorted((v(None, None) or {}).items()))
            except Exception:  # noqa: BLE001
                out[k] = "fn"
        elif callable(v):
            out[k] = "fn"
        elif isinstance(v, dict):
            out[k] = tuple(sorted(map(str, v.keys())))
        elif isinstance(v, (set, frozenset, list, tuple)):
            # sin direcciones de memoria ("<function … at 0x…>"): hacían que dos
            # armados idénticos difirieran y la ablación diera falsos positivos
            out[k] = tuple(sorted(_ADDR.sub("", str(x)) for x in v))
        else:
            out[k] = _ADDR.sub("", repr(v))
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


# también los filtros "{1}, {T}: Add {U}{B}" / "{W/U}, {T}: Add {W}{W}": el motor los
# modela como fuente de esos colores (mismo maná neto)
_MANA_LINE = re.compile(r"^(?:\{[^}]+\},\s*)?\{T\}: Add ((?:\{[WUBRGC]\})+|one mana of any color)\.?$", re.I)


def _mana_line_ok(line, row):
    """'{T}: Add {B}.' en una carta cuyo maná ya sale de su identidad/produced_mana
    (tierras, artefactos de maná): la línea no cambia la firma pero el motor SÍ
    produce ese maná. Cuenta como cubierta si la carta completa lo produce."""
    m = _MANA_LINE.match(line.strip())
    if not m:
        return False
    try:
        c = cardsdb.build_card_from_data(row)
        got = c.produces(None, None) if callable(c.produces) else (c.produces or {})
    except Exception:  # noqa: BLE001
        return False
    if not got:
        return False
    if m.group(1).lower().startswith("one mana"):
        return len(got) >= 3
    need = set(re.findall(r"[WUBRGC]", m.group(1).upper()))
    return need <= set(got)


# keywords cuyo cableado depende de la carta ENTERA (caras, otra línea): la línea
# sola no cambia la firma. Se cuenta cubierta solo si la carta completa tiene el
# atributo que la implementa.
_KW_WIRED = {
    "daybound": lambda c: getattr(c, "daybound", False),
    "nightbound": lambda c: getattr(c, "nightbound", False),
    "if it's neither day nor night, it becomes day as this creature enters.":
        lambda c: getattr(c, "daybound", False),
    "bargain": lambda c: getattr(c, "bargain", False),
    "spree": lambda c: bool(getattr(c, "spree_costs", None)),
    "read ahead": lambda c: getattr(c, "read_ahead", False),
    "haunt": lambda c: getattr(c, "haunt", False),
    "storm": lambda c: "storm" in (getattr(c, "tags", None) or ()),
    "this creature enters prepared.": lambda c: any(
        ab.get("prepared") for ab in (getattr(c, "activated_abilities", None) or ())),
    "~ enters prepared.": lambda c: any(
        ab.get("prepared") for ab in (getattr(c, "activated_abilities", None) or ())),
}


def _kw_wired(tpl, row):
    fn = _KW_WIRED.get(tpl)
    if fn is None:
        return False
    try:
        return bool(fn(cardsdb.build_card_from_data(row)))
    except Exception:  # noqa: BLE001
        return False


def audit(db):
    lines_total = lines_bad = 0
    by_tpl = collections.Counter()
    tpl_examples = {}
    vanilla, partial, full = [], [], []
    for name, raw in db.items():
        row = _front(raw)
        if _NON_DECK.search(row.get("type_line") or raw.get("type_line") or ""):
            continue                  # no son cartas de un mazo de Commander (planos, stickers…)
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
            if not handled and (_mana_line_ok(ln, row) or _kw_wired(_template(ln, name), raw)):
                handled = True
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


def _audit_chunk(items):
    return audit(dict(items))


def audit_parallel(db, jobs):
    """Igual que audit() pero repartiendo la base en `jobs` procesos (tramos
    contiguos: el orden de ejemplos y listas queda igual que en secuencial)."""
    import multiprocessing as mp
    items = list(db.items())
    k = max(1, -(-len(items) // jobs))
    chunks = [items[i:i + k] for i in range(0, len(items), k)]
    with mp.get_context("fork").Pool(jobs) as pool:
        parts = pool.map(_audit_chunk, chunks)
    res = {"lines_total": 0, "lines_bad": 0, "by_tpl": collections.Counter(), "examples": {},
           "vanilla": [], "partial": [], "full": []}
    for r in parts:
        res["lines_total"] += r["lines_total"]
        res["lines_bad"] += r["lines_bad"]
        res["by_tpl"].update(r["by_tpl"])
        for t, ex in r["examples"].items():
            res["examples"].setdefault(t, ex)
        for key in ("vanilla", "partial", "full"):
            res[key] += r[key]
    return res


def main(argv):
    full = "--full" in argv
    jobs = int(argv[argv.index("--jobs") + 1]) if "--jobs" in argv else 1
    db = load_db(full)
    res = audit_parallel(db, jobs) if jobs > 1 else audit(db)
    write_report(res, path=REPORT.replace(".md", "_full.md") if full else REPORT)
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
