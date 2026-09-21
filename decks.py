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
    d.append(cards.anthem("Glorious Anthem", "1WW", 1, 1, (W,)))  # P2.4 anthem
    d.append(cards.QuintoriusPlaneswalker())                      # P2.3 planeswalker
    # criaturas de relleno tematicas (nombres reales -> traen ilustracion)
    d.append(creature("Goblin Cratermaker", "1R", 2, 2, color_id=(R,)))
    d.append(creature("Seasoned Hallowblade", "1W", 3, 2, color_id=(W,)))
    d.append(creature("Serra Angel", "3WW", 4, 4, kw=("flying",), color_id=(W,)))
    d.append(creature("Flametongue Kavu", "3R", 4, 3, kw=("haste",), color_id=(R,)))
    d.append(creature("Wall of Reverence", "4W", 3, 6, kw=("vigilance",), color_id=(W,)))
    # ramp + removal + draw
    d.append(rock("Boros Signet", "2", [R, W]))
    d.append(rock("Arcane Signet", "2", [R, W]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(_boros_removal())
    d.append(_boros_wipe())
    d.append(_lorehold_draw())
    dual = land("Sacred Foundry", [R, W])
    d.append(dual)
    d.append(land("Temple of Triumph", [R, W], tapped=True))
    return _fill(d, commander.identity()), commander


def _boros_removal():
    from engine import Card, parse_cost
    return Card("Swords to Plowshares", {"instant"}, parse_cost("W"),
                on_cast_resolve=cards.destroy_target, tags={"removal"},
                color_id={W}, target_spec="opp_creature")


def _boros_wipe():
    from engine import Card, parse_cost
    return Card("Blasphemous Act", {"sorcery"}, parse_cost("2RW"),
                on_cast_resolve=cards.wrath, tags={"wipe"}, color_id={R, W})


def _lorehold_draw():
    from engine import Card, parse_cost
    return Card("Tormenting Voice", {"sorcery"}, parse_cost("1R"),
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
    d.append(creature("Sylvan Advocate", "1G", 2, 1, color_id=(G,)))
    d.append(creature("Sea Gate Oracle", "1U", 1, 3, color_id=(U,)))
    d.append(creature("Kavu Titan", "3G", 3, 3, kw=("trample",), color_id=(G,)))
    d.append(creature("Frost Titan", "4U", 5, 5, color_id=(U,)))
    d.append(rock("Simic Signet", "2", [G, U]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(cards.Counterspell())        # P2.1 instantaneo de respuesta
    d.append(_tricky_draw())
    d.append(land("Breeding Pool", [G, U]))
    d.append(land("Temple of Mystery", [G, U], tapped=True))
    return _fill(d, commander.identity()), commander


def _tricky_commander():
    c = creature("Ezuri, Claw of Progress", "2GU", 3, 3, legendary=True,
                 tags=("engine",), color_id=(G, U))

    def _attacks(game, perm, **kw):     # al atacar, tus criaturas ganan +1/+1
        for p in perm.controller.creatures():
            game.add_counters(p, "+1/+1", 1)
    c.triggers = {"attacks": _attacks}
    return c


def _tricky_draw():
    from engine import Card, parse_cost
    return Card("Deep Analysis", {"sorcery"}, parse_cost("2U"),
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
    d.append(creature("Gifted Aetherborn", "1B", 2, 1, kw=("deathtouch",), color_id=(B,)))
    d.append(creature("Vampire Nighthawk", "2B", 3, 2, kw=("flying", "lifelink"), color_id=(B,)))
    d.append(creature("Ravenous Chupacabra", "3B", 4, 3, kw=("menace",), color_id=(B,)))
    d.append(creature("Archfiend of Depravity", "4BB", 5, 5, kw=("flying",), color_id=(B,)))
    d.append(creature("Sengir Vampire", "2BB", 3, 4, kw=("deathtouch",), color_id=(B,)))
    d.append(creature("Dusk Legion Zealot", "1B", 2, 2, kw=("menace",), color_id=(B,)))
    d.append(rock("Dimir Signet", "2", [U, B]))
    d.append(rock("Jet Medallion", "2", [B]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(cards.NightsWhisper())
    d.append(land("Barren Moor", [B], tapped=True))
    return _fill(d, commander.identity()), commander


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #

DECKS = {
    "lorehold": lorehold,
    "tricky": tricky,
    "kang": kang,
}

# Ejemplos publicos que ve un usuario nuevo (temas de precon). Reutilizan los
# 99 ya probados pero con comandantes PROPIOS y distintos, para no repetir los
# comandantes de los decks del usuario (Quintorius, Ezuri, Omo...).
#   Strixhaven    -> R/W academico
#   Marvel        -> Kang (mono-negro)
#   Vieja guardia -> Simic clasico (G/U)

def strixhaven():
    deck, _cmd = lorehold()          # reutiliza los 99 R/W
    commander = creature("Feather, the Redeemed", "1RRW", 3, 4, legendary=True,
                         kw=("flying",), tags=("engine",), color_id=(R, W))
    return deck, commander


def old_guard():
    deck, _cmd = tricky()            # reutiliza los 99 G/U
    commander = creature("Kinnan, Bonder Prodigy", "1GU", 2, 2,
                         legendary=True, tags=("engine",), color_id=(G, U))
    return deck, commander


def marvel():
    deck, _cmd = kang()              # reutiliza los 99 mono-B
    commander = creature("Sheoldred, the Apocalypse", "2BB", 4, 5,
                         legendary=True, kw=("deathtouch",), tags=("engine",),
                         color_id=(B,))
    return deck, commander


DECKS["strixhaven"] = strixhaven
DECKS["marvel"] = marvel
DECKS["old-guard"] = old_guard

EXAMPLES = ["strixhaven", "marvel", "old-guard"]
EXAMPLE_THEME = {
    "strixhaven": "Strixhaven",
    "marvel": "Marvel",
    "old-guard": "Old Guard",
}

# Origen de cada deck (los presets del usuario se marcan aparte y NO se
# muestran como ejemplos publicos en la portada).
DECK_SOURCE = {k: "ejemplo" for k in DECKS}


def _register_presets():
    """Registra cada presets/*.md (menos FORMATO.md) como un deck jugable."""
    import os
    import mdparse
    pdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")
    if not os.path.isdir(pdir):
        return
    for fn in sorted(os.listdir(pdir)):
        if not fn.endswith(".md") or fn.upper().startswith("FORMATO"):
            continue
        slug = fn[:-3]
        path = os.path.join(pdir, fn)

        def _loader(_p=path):
            deck, commander, _ = mdparse.parse_md_deck(open(_p, encoding="utf-8").read())
            return deck, commander

        DECKS[slug] = _loader
        DECK_SOURCE[slug] = "preset"


_register_presets()


def build(name):
    if name not in DECKS:
        raise KeyError(f"mazo desconocido: {name}. Opciones: {list(DECKS)}")
    return DECKS[name]()
