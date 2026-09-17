"""Las tres listas de 99 + comandante.

Cada funcion devuelve (deck, commander): `deck` es la lista de 99 cartas y
`commander` la carta del comandante (va a la zona de mando, no al mazo).

El mazo se rellena con tierras basicas hasta 99 via `_fill()`.
"""
from __future__ import annotations

from engine import W, U, B, R, G, C
import cards
from cards import creature, land, rock


# --------------------------------------------------------------------------- #
# Tierras basicas
# --------------------------------------------------------------------------- #

_BASIC = {
    W: ("Plains", W),
    U: ("Island", U),
    B: ("Swamp", B),
    R: ("Mountain", R),
    G: ("Forest", G),
}


def _basic(color):
    name, c = _BASIC[color]
    return land(name, [c], basic=True)


def _fill(deck, identity):
    """Rellena con tierras basicas de la identidad del comandante hasta 99."""
    colors = [c for c in (W, U, B, R, G) if c in identity] or [C]
    i = 0
    while len(deck) < 99:
        color = colors[i % len(colors)]
        if color == C:
            deck.append(land("Wastes", [C], basic=True))
        else:
            deck.append(_basic(color))
        i += 1
    return deck[:99]


# --------------------------------------------------------------------------- #
# LOREHOLD (R/W)
# --------------------------------------------------------------------------- #

def lorehold():
    commander = cards.Quintorius()
    d = []
    # motor de Espiritus (P1.1): salidas de cementerio -> dispara Quintorius
    d.append(cards.Hofri())
    d.append(cards.BagOfHolding())
    d.append(cards.SevinnesReclamation())
    d.append(cards.FaithlessLooting())
    d.append(cards.UnderworldBreach())
    d.append(cards.SunTitan())
    d.append(cards.KarmicGuide())
    d.append(cards.CronistaEspectral())
    d.append(cards.MerodeadorDeTumbas())
    # criaturas de relleno tematicas
    d.append(creature("Historiador de Guerra", "1R", 2, 2, color_id=(R,)))
    d.append(creature("Cronista Lorehold", "2W", 2, 3, color_id=(W,)))
    d.append(creature("Angel de Basalto", "3WW", 4, 4, kw=("flying",), color_id=(W,)))
    d.append(creature("Elemental Igneo", "3R", 4, 3, kw=("haste",), color_id=(R,)))
    d.append(creature("Guardian de Piedra", "4W", 3, 6, kw=("vigilance",), color_id=(W,)))
    # ramp + removal + draw
    d.append(rock("Boros Signet", "2", [R, W]))
    d.append(rock("Arcane Signet", "2", [R, W]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(_boros_removal())
    d.append(_boros_wipe())
    d.append(_lorehold_draw())
    dual = land("Sacred Foundry", [R, W])
    d.append(dual)
    d.append(land("Templo del Triunfo", [R, W], tapped=True))
    return _fill(d, commander.identity()), commander


def _boros_removal():
    from engine import Card, parse_cost
    return Card("Justicia Angelical", {"instant"}, parse_cost("1W"),
                on_cast_resolve=cards.destroy_biggest, tags={"removal"},
                color_id={W})


def _boros_wipe():
    from engine import Card, parse_cost
    return Card("Furia Purificadora", {"sorcery"}, parse_cost("2RW"),
                on_cast_resolve=cards.wrath, tags={"wipe"}, color_id={R, W})


def _lorehold_draw():
    from engine import Card, parse_cost
    return Card("Sabiduria Ancestral", {"sorcery"}, parse_cost("2R"),
                on_cast_resolve=cards.draw_n(2), tags={"draw"}, color_id={R})


# --------------------------------------------------------------------------- #
# TRICKY (G/U) — contadores
# --------------------------------------------------------------------------- #

def tricky():
    commander = _tricky_commander()
    d = []
    d.append(cards.Managorger())
    d.append(cards.Kalonian())
    d.append(cards.SimicAscendancy())
    d.append(cards.BranchingEvolution())
    d.append(cards.HardenedScales())
    d.append(creature("Explorador Simic", "1G", 2, 1, color_id=(G,)))
    d.append(creature("Mistico de Marea", "1U", 1, 3, color_id=(U,)))
    d.append(creature("Hidra de Musgo", "3G", 3, 3, kw=("trample",), color_id=(G,)))
    d.append(creature("Serpiente de Kraken", "4U", 5, 5, color_id=(U,)))
    d.append(rock("Simic Signet", "2", [G, U]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(_tricky_draw())
    d.append(land("Breeding Pool", [G, U]))
    d.append(land("Templo de Mistica", [G, U], tapped=True))
    return _fill(d, commander.identity()), commander


def _tricky_commander():
    c = creature("Ezuri, Vanguardia", "2GU", 3, 3, legendary=True,
                 tags=("engine",), color_id=(G, U))

    def _attacks(game, perm, **kw):     # al atacar, tus criaturas ganan +1/+1
        for p in perm.controller.creatures():
            game.add_counters(p, "+1/+1", 1)
    c.triggers = {"attacks": _attacks}
    return c


def _tricky_draw():
    from engine import Card, parse_cost
    return Card("Consulta Profunda", {"sorcery"}, parse_cost("2U"),
                on_cast_resolve=cards.draw_n(2), tags={"draw"}, color_id={U})


# --------------------------------------------------------------------------- #
# KANG (B) — connive / drenaje
# --------------------------------------------------------------------------- #

def kang():
    commander = cards.Kang()
    d = []
    d.append(cards.GrayMerchant())
    d.append(cards.GoForTheThroat())
    d.append(cards.NightsWhisper())
    d.append(cards.DamnationWipe())
    d.append(creature("Acolito Sombrio", "1B", 2, 1, kw=("deathtouch",), color_id=(B,)))
    d.append(creature("Vampiro Nocturno", "2B", 3, 2, kw=("flying", "lifelink"), color_id=(B,)))
    d.append(creature("Horror del Foso", "3B", 4, 3, kw=("menace",), color_id=(B,)))
    d.append(creature("Demonio Menor", "4BB", 5, 5, kw=("flying",), color_id=(B,)))
    d.append(creature("Segador de Almas", "2BB", 3, 4, kw=("deathtouch",), color_id=(B,)))
    d.append(creature("Ladron Furtivo", "1B", 2, 2, kw=("menace",), color_id=(B,)))
    d.append(rock("Dimir Signet", "2", [U, B]))
    d.append(rock("Jet Medallion", "2", [B]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(cards.NightsWhisper())
    d.append(land("Cavernas Lobregas", [B], tapped=True))
    return _fill(d, commander.identity()), commander


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #

DECKS = {
    "lorehold": lorehold,
    "tricky": tricky,
    "kang": kang,
}


def build(name):
    if name not in DECKS:
        raise KeyError(f"mazo desconocido: {name}. Opciones: {list(DECKS)}")
    return DECKS[name]()
