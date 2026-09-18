"""Importador del formato de tablas markdown (ver presets/FORMATO.md).

Cada mazo es un .md con tablas por seccion:
    | n | Carta | Coste | P/T | Keywords | Tags |
y una tabla de tierras:
    | n | Carta | Produce | Tapeada |

Reglas:
- Solo se leen las tablas ANTES del primer '---' (lo de despues son notas /
  pendientes / cambios y se ignora).
- La seccion '## Comandante' define el comandante.
- `?` en una columna de una carta real = dato sin confirmar -> ERROR ruidoso
  (no se adivina). `n = ?` solo vale en basicas: significa "rellena hasta 99".
- Si la carta esta implementada en el registro (cardsdb) y el tipo coincide
  (criatura<->criatura), se usa la version con EFECTO; si no, se construye
  vainilla con los datos exactos de la tabla.
- `parse_cost` no soporta X: se trata como 0.
"""
from __future__ import annotations

import re

from engine import Card, parse_cost, W, U, B, R, G, C, KEYWORDS
from cards import land
import cardsdb

_COLOR = {"W": W, "U": U, "B": B, "R": R, "G": G, "C": C}
_BASICS = {"plains": W, "island": U, "swamp": B, "mountain": R, "forest": G,
           "wastes": C}


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_sep(line):
    return bool(re.match(r"^\|?[\s:|-]+\|?$", line.strip())) and "-" in line


def _strip_x(cost):
    return re.sub(r"[Xx]", "", cost or "")


def _clean_cost(cost):
    return _strip_x(cost).strip()


def _build_card_row(name, coste, pt, kws, tags):
    # `?` = sin confirmar -> fallar
    for col, label in ((coste, "coste"), (pt, "P/T"), (kws, "keywords"),
                       (tags, "tags")):
        if col.strip() == "?":
            raise ValueError(f"'{name}': {label} sin confirmar (?). "
                             "El importador no adivina; completa el dato.")
    is_creature = bool(pt.strip())
    # usar la version implementada si existe y el tipo coincide
    reg = cardsdb.resolve(name)
    if reg is not None and cardsdb.is_implemented(name):
        if ("creature" in reg.types) == is_creature:
            return reg
    # construir vainilla con datos exactos de la tabla
    power = tough = 0
    types = {"sorcery"}
    if is_creature:
        m = re.match(r"^(-?\d+)\s*/\s*(-?\d+)$", pt.strip())
        if not m:
            raise ValueError(f"'{name}': P/T invalido {pt!r}")
        power, tough = int(m.group(1)), int(m.group(2))
        types = {"creature"}
    cost = parse_cost(_clean_cost(coste)) if coste.strip() else None
    kw = {k for k in kws.split()} & KEYWORDS
    tagset = {t for t in tags.split()}
    return Card(name=name, types=types, cost=cost, power=power, toughness=tough,
                keywords=kw, tags=tagset)


def _build_land_row(name, produce, tapeada):
    reg = cardsdb.resolve(name)
    if reg is not None and cardsdb.is_implemented(name) and reg.is_land():
        return reg
    inside = re.search(r"\[([^\]]*)\]", produce)
    colors = []
    if inside:
        for tok in inside.group(1).split():
            if tok.upper() in _COLOR:
                colors.append(_COLOR[tok.upper()])
    if not colors:
        colors = [C]
    tapped = tapeada.strip().lower() in ("si", "sí", "yes", "true", "1")
    basic = name.strip().lower() in _BASICS
    return land(name, colors, tapped=tapped, basic=basic)


def parse_md_deck(text, target=99):
    """Devuelve (deck, commander, report)."""
    lines = []
    for ln in text.splitlines():
        if ln.strip() == "---":
            break                       # corta antes de notas/pendientes
        lines.append(ln)

    commander = None
    deck = []
    fill_colors = []                    # colores de basicas con n = ?
    cur_header = ""
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("#"):
            cur_header = s.lstrip("#").strip().lower()
            i += 1
            continue
        # cabecera de tabla?
        if s.startswith("|") and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            header = [c.lower() for c in _cells(s)]
            is_land = any("produce" in h for h in header)
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = _cells(lines[i])
                i += 1
                if is_land:
                    if len(row) < 3:
                        continue
                    n, name, produce = row[0], row[1], row[2]
                    tapeada = row[3] if len(row) > 3 else "no"
                    if n.strip() == "?":
                        color = _BASICS.get(name.strip().lower(), G)
                        fill_colors.append(color)
                        continue
                    count = int(n) if n.strip().isdigit() else 1
                    for _ in range(count):
                        deck.append(_build_land_row(name, produce, tapeada))
                else:
                    if len(row) < 2:
                        continue
                    n, name = row[0], row[1]
                    coste = row[2] if len(row) > 2 else ""
                    pt = row[3] if len(row) > 3 else ""
                    kws = row[4] if len(row) > 4 else ""
                    tags = row[5] if len(row) > 5 else ""
                    card = _build_card_row(name, coste, pt, kws, tags)
                    if cur_header.startswith("comandante"):
                        commander = card
                        continue
                    if n.strip() == "?":
                        raise ValueError(f"'{name}': n = ? solo vale en basicas")
                    count = int(n) if n.strip().isdigit() else 1
                    for _ in range(count):
                        deck.append(card if count == 1
                                    else _build_card_row(name, coste, pt, kws, tags))
            continue
        i += 1

    if commander is None:
        raise ValueError("No se encontro comandante (seccion '## Comandante').")

    # rellenar hasta `target` con las basicas marcadas con n = ?
    deck = deck[:target]
    if not fill_colors:
        ident = commander.identity()
        fill_colors = [c for c in (W, U, B, R, G) if c in ident] or [G]
    names = {W: "Plains", U: "Island", B: "Swamp", R: "Mountain", G: "Forest",
             C: "Wastes"}
    k = 0
    while len(deck) < target:
        color = fill_colors[k % len(fill_colors)]
        deck.append(land(names[color], [color], basic=True))
        k += 1

    implemented = sum(1 for c in deck if cardsdb.is_implemented(c.name))
    if cardsdb.is_implemented(commander.name):
        implemented += 1
    report = {"commander": commander.name, "count": len(deck),
              "implemented": implemented}
    return deck, commander, report
