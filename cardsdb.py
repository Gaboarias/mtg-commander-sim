"""Resolucion de cartas por nombre.

- REGISTRY: cartas con EFECTO implementado (las de cards.py), indexadas por
  nombre. Si un deck importado contiene una de estas, usa la version real.
- build_card_from_data: construye una carta "vainilla pero con stats reales"
  (coste, tipos, P/T, keywords, colores) a partir de un dict tipo Scryfall.
  NO inventa datos: lo que no viene en `data` queda por defecto.

La descarga desde Scryfall vive en la capa de API (corre en Vercel). Aca todo
es puro y testeable sin red.
"""
from __future__ import annotations

import re

from engine import Card, Cost, parse_cost, W, U, B, R, G, C, KEYWORDS
import cards

# --------------------------------------------------------------------------- #
# Registro de cartas implementadas (nombre -> constructor)
# --------------------------------------------------------------------------- #

_IMPLEMENTED = [
    cards.Quintorius, cards.Hofri, cards.BagOfHolding, cards.FaithlessLooting,
    cards.SevinnesReclamation, cards.UnderworldBreach, cards.SunTitan,
    cards.KarmicGuide, cards.CronistaEspectral, cards.MerodeadorDeTumbas,
    cards.Managorger, cards.Kalonian, cards.HardenedScales,
    cards.SimicAscendancy, cards.BranchingEvolution,
    cards.Kang, cards.GrayMerchant, cards.GoForTheThroat, cards.NightsWhisper,
    cards.DamnationWipe,
    cards.SolRing, cards.ArcaneSignet, cards.CommandTower,
]


def _build_registry():
    reg = {}
    for ctor in _IMPLEMENTED:
        c = ctor()
        reg[_norm(c.name)] = ctor
    return reg


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


REGISTRY = _build_registry()


# --------------------------------------------------------------------------- #
# Conversion de datos tipo Scryfall -> Card
# --------------------------------------------------------------------------- #

_COLOR_MAP = {"W": W, "U": U, "B": B, "R": R, "G": G, "C": C}


def mana_cost_to_str(mana_cost: str) -> str:
    """'{2}{R}{W}' -> '2RW'. Ignora X (0) e hibridos (toma el primer simbolo)."""
    if not mana_cost:
        return "0"
    generic = 0
    pips = ""
    for sym in re.findall(r"\{([^}]+)\}", mana_cost):
        s = sym.upper()
        if s.isdigit():
            generic += int(s)
        elif s == "X":
            continue
        elif "/" in s:               # hibrido / phyrexiano: primer color valido
            first = next((p for p in s.split("/") if p in _COLOR_MAP), None)
            if first:
                pips += first
        elif s in _COLOR_MAP and s != "C":
            pips += s
        # {C} incoloro no aporta pip de color
    return (str(generic) if generic else "") + pips or "0"


def parse_type_line(type_line: str):
    """Devuelve (types, supertypes, subtypes)."""
    tl = (type_line or "").lower()
    left = tl.split("—")[0]
    right = tl.split("—")[1] if "—" in tl else ""
    types = set()
    for t in ("land", "creature", "artifact", "enchantment", "instant",
              "sorcery", "planeswalker", "battle"):
        if t in left:
            types.add(t)
    supertypes = set()
    for s in ("legendary", "basic", "snow", "world"):
        if s in left:
            supertypes.add(s)
    subtypes = {w for w in right.split()} if right else set()
    return types, supertypes, subtypes


def _int_or_zero(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def build_card_from_data(data: dict) -> Card:
    """Construye una Card desde un dict tipo Scryfall (name, mana_cost,
    type_line, power, toughness, keywords, color_identity)."""
    name = data.get("name", "?")
    types, supertypes, subtypes = parse_type_line(data.get("type_line", ""))
    color_id = {_COLOR_MAP[c] for c in data.get("color_identity", [])
                if c in _COLOR_MAP}
    kws = {k.lower().replace(" ", "_") for k in data.get("keywords", [])}
    kws &= KEYWORDS

    cost = None
    if "land" not in types:
        cost = parse_cost(mana_cost_to_str(data.get("mana_cost", "")))

    card = Card(
        name=name,
        types=types or {"creature"},
        cost=cost,
        power=_int_or_zero(data.get("power")),
        toughness=_int_or_zero(data.get("toughness")),
        keywords=kws,
        supertypes=supertypes,
        subtypes=subtypes,
        color_id=color_id,
    )

    # tags minimos para que la IA la considere
    tags = set()
    if "creature" in card.types:
        tags.add("creature")
    card.tags = tags

    # tierras: producen mana segun su identidad de color (para que la base
    # de mana importada funcione). Sin identidad -> incoloro.
    if "land" in types:
        colors = [c for c in (W, U, B, R, G) if c in color_id] or [C]
        opts = {c: 1 for c in colors}
        card.produces = (lambda perm, pl, _o=opts: dict(_o))
        card.enters_tapped = bool(data.get("enters_tapped"))
    return card


# --------------------------------------------------------------------------- #
# Resolucion por nombre
# --------------------------------------------------------------------------- #

def resolve(name: str, fetch=None) -> Card:
    """Devuelve una Card para `name`.

    1) si esta implementada -> version con efecto real.
    2) si no, y hay `fetch(name)->dict` (Scryfall), construye vainilla con
       stats reales.
    3) si no hay datos -> None (el llamador decide: placeholder o descartar).
    """
    key = _norm(name)
    if key in REGISTRY:
        return REGISTRY[key]()
    # basicas conocidas sin red
    basic = _basic_land(name)
    if basic is not None:
        return basic
    if fetch is not None:
        data = fetch(name)
        if data:
            return build_card_from_data(data)
    return None


_BASICS = {
    "plains": W, "island": U, "swamp": B, "mountain": R, "forest": G,
    "wastes": C,
    "llanura": W, "isla": U, "pantano": B, "montana": R, "montaña": R,
    "bosque": G, "yermo": C,
}


def _basic_land(name: str):
    key = _norm(name)
    if key in _BASICS:
        color = _BASICS[key]
        from cards import land
        display = {W: "Plains", U: "Island", B: "Swamp", R: "Mountain",
                   G: "Forest", C: "Wastes"}[color]
        return land(display, [color], basic=True)
    return None


def is_implemented(name: str) -> bool:
    return _norm(name) in REGISTRY
