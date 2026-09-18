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
from engine import W, U, B, R, G

_LINE = re.compile(r"^\s*(?:(\d+)\s*x?\s+)?(.+?)\s*$", re.IGNORECASE)
_TRAIL = re.compile(r"\s*\(([^)]*)\)\s*[\dA-Za-z\-]*\s*$")  # (SET) 123
_CMDR_MARK = re.compile(r"\*(cmdr|commander|comandante)\*", re.IGNORECASE)
_HEADERS_CMD = {"commander", "comandante", "commanders"}
_HEADERS_SKIP = {"sideboard", "maybeboard", "sb", "considering", "tokens"}
_HEADERS_MAIN = {"deck", "mainboard", "main", "creatures", "lands", "spells",
                 "instants", "sorceries", "artifacts", "enchantments",
                 "planeswalkers", "other"}


def parse_decklist(text: str) -> dict:
    commander = None
    entries = []            # [(qty, name)]
    section = "main"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        low = re.sub(r"\s*\(\d+\)\s*$", "", line).lower().strip().rstrip(":")
        if low in _HEADERS_CMD:
            section = "commander"
            continue
        if low in _HEADERS_SKIP:
            section = "skip"
            continue
        if low in _HEADERS_MAIN:
            section = "main"
            continue
        m = _LINE.match(line)
        if not m:
            continue
        qty = int(m.group(1)) if m.group(1) else 1
        name = m.group(2)
        is_cmd_mark = bool(_CMDR_MARK.search(name))
        name = _CMDR_MARK.sub("", name)
        name = _TRAIL.sub("", name).strip()
        if not name:
            continue
        if section == "skip":
            continue
        if section == "commander" or is_cmd_mark:
            commander = name
            continue
        entries.append((qty, name))
    return {"commander": commander, "cards": entries}


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

    deck = []
    for qty, name in parsed["cards"]:
        card = cardsdb.resolve(name, fetch)
        if card is None:
            unresolved.append(name)
            continue
        if cardsdb.is_implemented(name):
            implemented += qty
        for _ in range(qty):
            deck.append(cardsdb.resolve(name, fetch))

    # ajustar a 99: recortar o rellenar con basicas de la identidad
    deck = deck[:target]
    ident = commander.identity()
    colors = [c for c in (W, U, B, R, G) if c in ident] or [G]
    i = 0
    basics = {W: "Plains", U: "Island", B: "Swamp", R: "Mountain", G: "Forest"}
    while len(deck) < target:
        color = colors[i % len(colors)]
        deck.append(land(basics[color], [color], basic=True))
        i += 1

    report = {
        "commander": commander.name,
        "count": len(deck),
        "implemented": implemented,
        "unresolved": unresolved,
    }
    return deck, commander, report
