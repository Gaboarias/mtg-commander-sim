"""Parser de listas de mazo (Moxfield / Archidekt / texto plano) y armado de
un mazo jugable para el motor.

Formatos soportados por linea:
    1 Sol Ring
    1x Sol Ring
    1 Sol Ring (C21) 263        <- se ignora set/numero
    1 Golos, Tireless Pilgrim *CMDR*   <- marcador de comandante
Secciones: 'Commander'/'Comandante' marca al comandante; 'Sideboard'/
'Maybeboard' se ignoran.
"""
from __future__ import annotations

import re

import cardsdb
from cards import land
from engine import W, U, B, R, G, C

_LINE = re.compile(r"^\s*(?:(\d+)\s*x?\s+)?(.+?)\s*$", re.IGNORECASE)
_TRAIL = re.compile(r"\s*\(([^)]*)\)\s*[\dA-Za-z\-★]*\s*$")  # (SET) 123
_CMDR_MARK = re.compile(r"\*(cmdr|commander|comandante)\*", re.IGNORECASE)
# marcadores de Moxfield (*F* foil, *E* etched, *A* alter…) y etiquetas de color
# de Archidekt (^Have,#37d67a^)
_FLAGS = re.compile(r"\s*\*[A-Za-z]{1,3}\*", re.IGNORECASE)
_TAGS = re.compile(r"\s*\^[^^]*\^")
# categorías de Archidekt: "[Ramp]", "[Commander{top}]", "[Maybeboard{noDeck}{noPrice}]"
_CATS = re.compile(r"\s*\[([^\]]*)\]\s*$")
_HEADERS_CMD = {"commander", "comandante", "commanders", "comandantes"}
_HEADERS_SKIP = {"sideboard", "maybeboard", "sb", "considering", "tokens", "maybe",
                 "companion", "attractions", "stickers"}
_HEADERS_MAIN = {"deck", "mainboard", "main", "creatures", "lands", "spells",
                 "instants", "sorceries", "artifacts", "enchantments",
                 "planeswalkers", "other", "creature", "land", "instant", "sorcery",
                 "artifact", "enchantment", "planeswalker", "battle", "battles"}


MAX_QTY = 99            # un mazo de Commander nunca necesita más copias de una carta


def clamp_qty(q) -> int:
    """Cantidad por línea acotada a 1..MAX_QTY: "1000000 Sol Ring" no debe
    expandirse a un millón de objetos (tumbaba la función serverless)."""
    try:
        q = int(q)
    except (TypeError, ValueError):
        q = 1
    return max(1, min(q, MAX_QTY))


def _category_kind(cat: str) -> str:
    """Categoría de Archidekt -> 'commander' | 'skip' | 'main'."""
    c = cat.lower()
    if "{nodeck}" in c:
        return "skip"
    head = re.split(r"[{,]", c)[0].strip()
    if head in ("commander", "commanders"):
        return "commander"
    if head in ("maybeboard", "sideboard", "considering", "tokens"):
        return "skip"
    # "Ramp, Commander{top}": una carta puede tener varias categorías
    if any(x.strip().split("{")[0] == "commander" for x in c.split(",")):
        return "commander"
    return "main"


def parse_decklist(text: str) -> dict:
    """{'commander': str|None, 'commanders': [str] (1-2, partners), 'cards': [(qty, name)]}"""
    commanders = []
    entries = []            # [(qty, name)]
    blocks = []             # bloques del mazo principal separados por línea en blanco
    cur_block = []
    section = "main"

    def _close_block():
        nonlocal cur_block
        if cur_block:
            blocks.append(cur_block)
        cur_block = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            _close_block()
            # "Commander\n1 X\n\n1 Command Tower…": la línea en blanco cierra la
            # sección del comandante (antes la última carta del mazo pisaba al
            # comandante y el mazo quedaba vacío)
            if section == "commander" and commanders:
                section = "main"
            continue
        if line.startswith("#") or line.startswith("//"):
            continue
        low = re.sub(r"\s*\(\d+\)\s*$", "", line).lower().strip().rstrip(":").strip()
        if low in _HEADERS_CMD:
            _close_block()
            section = "commander"
            continue
        if low in _HEADERS_SKIP:
            _close_block()
            section = "skip"
            continue
        if low in _HEADERS_MAIN:
            _close_block()
            section = "main"
            continue
        m = _LINE.match(line)
        if not m:
            continue
        qty = clamp_qty(m.group(1)) if m.group(1) else 1
        name = m.group(2)
        is_cmd_mark = bool(_CMDR_MARK.search(name))
        name = _CMDR_MARK.sub("", name)
        name = _TAGS.sub("", name)
        kind = "main"
        mc = _CATS.search(name)
        if mc:
            kind = _category_kind(mc.group(1))
            name = name[:mc.start()]
        name = _FLAGS.sub("", name)
        name = _TRAIL.sub("", name).strip()
        name = _FLAGS.sub("", name).strip()
        if not name:
            continue
        if section == "skip" or kind == "skip":
            continue
        if section == "commander" or is_cmd_mark or kind == "commander":
            if name not in commanders and len(commanders) < 2:
                commanders.append(name)
            continue
        entries.append((qty, name))
        cur_block.append((qty, name))
    _close_block()

    # Moxfield crudo: sin sección/marcador, el ÚLTIMO bloque del mazo principal
    # (tras una línea en blanco) de 1 carta -o 2, partners, si el resto suma 98-
    # es el comandante. Un sideboard posterior ya no rompe la detección.
    if not commanders and len(blocks) >= 2:
        tail = blocks[-1]
        rest = sum(q for q, _n in entries) - sum(q for q, _n in tail)
        if all(q == 1 for q, _n in tail) and (
                len(tail) == 1 or (len(tail) == 2 and 96 <= rest <= 98)):
            commanders = [n for _q, n in tail]
            entries = entries[:len(entries) - len(tail)]

    return {"commander": commanders[0] if commanders else None,
            "commanders": commanders, "cards": entries}


def build_deck(parsed: dict, fetch=None, target=99):
    """Arma (deck, commander_card, report). `fetch(name)->dict|None` resuelve
    cartas no implementadas via Scryfall (en Vercel). report resume cobertura y
    cartas no resueltas."""
    unresolved = []
    implemented = 0

    # comandante
    cmd_name = parsed.get("commander")
    commander = cardsdb.resolve(cmd_name, fetch) if cmd_name else None
    if commander is None:
        raise ValueError("No se pudo resolver el comandante: "
                         f"{cmd_name!r}. Marca uno con *CMDR* o seccion Commander.")
    if cardsdb.is_implemented(cmd_name):
        implemented += 1
    # partner / "Choose a Background" / Friends forever: segundo comandante. Va como
    # atributo del primero para no cambiar la firma (Player lo toma de ahí).
    partner = None
    for pname in (parsed.get("commanders") or [])[1:2]:
        partner = cardsdb.resolve(pname, fetch)
        if partner is None:
            unresolved.append(pname)
        else:
            if cardsdb.is_implemented(pname):
                implemented += 1
            commander._partner = partner
            target -= 1                    # 98 + 2 comandantes

    deck = []
    for qty, name in parsed["cards"]:
        card = cardsdb.resolve(name, fetch)
        if card is None:
            unresolved.append(name)
            continue
        qty = clamp_qty(qty)
        if cardsdb.is_implemented(name):
            implemented += qty
        deck.append(card)
        for _ in range(min(qty, target - len(deck) + 1) - 1):
            deck.append(cardsdb.resolve(name, fetch))   # objeto propio por copia

    # ajustar a 99: recortar o rellenar con basicas de la identidad
    deck = deck[:target]
    ident = set(commander.identity()) | (set(partner.identity()) if partner else set())
    colors = [c for c in (W, U, B, R, G) if c in ident]
    i = 0
    basics = {W: "Plains", U: "Island", B: "Swamp", R: "Mountain", G: "Forest"}
    while len(deck) < target:
        if colors:
            color = colors[i % len(colors)]
            deck.append(land(basics[color], [color], basic=True))
        else:                          # comandante incoloro: Wastes (antes Forest)
            deck.append(land("Wastes", [C], basic=True))
        i += 1

    report = {
        "commander": commander.name + (f" + {partner.name}" if partner else ""),
        "count": len(deck),
        "implemented": implemented,
        "unresolved": unresolved,
    }
    return deck, commander, report
