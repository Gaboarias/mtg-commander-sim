"""Las tres listas de 99 + comandante.

Cada funcion devuelve (deck, commander): `deck` es la lista de 99 cartas y
`commander` la carta del comandante (va a la zona de mando, no al mazo).

El mazo se rellena con tierras basicas hasta 99 via `_fill()`.
"""
from __future__ import annotations

import re

from engine import W, U, B, R, G, C
import cards
import cardsdb
from cards import creature, land, rock


# Oracle real de cartas del pool de relleno que SÍ tienen efecto conocido y
# parseable. Al construirlas vía cardsdb, el parser les da su comportamiento
# (ETB, muerte, activadas, disparos), subiendo la cobertura PAREJA en todos los
# mazos que comparten ese color. Las que no están aquí quedan como cuerpo simple.
_FILLER_ORACLE = {
    # --- blanco ---
    "Wall of Omens": "When Wall of Omens enters, draw a card.",
    "Blade Splicer": "When Blade Splicer enters, create a 3/3 colorless Phyrexian "
                     "Golem artifact creature token.",
    "Attended Knight": "When Attended Knight enters, create a 1/1 white Soldier "
                       "creature token.",
    "Cloudgoat Ranger": "When Cloudgoat Ranger enters, create three 1/1 white "
                        "Kithkin Soldier creature tokens.",
    "Leonin Warleader": "Whenever Leonin Warleader attacks, create two 1/1 white "
                        "Cat creature tokens.",
    # --- azul ---
    "Mulldrifter": "When Mulldrifter enters, draw two cards.",
    "Cloudkin Seer": "When Cloudkin Seer enters, draw a card.",
    "Silvergill Adept": "When Silvergill Adept enters, draw a card.",
    "Aven Fisher": "When Aven Fisher dies, draw a card.",
    # --- negro ---
    "Phyrexian Rager": "When Phyrexian Rager enters, draw a card.",
    "Gravedigger": "When Gravedigger enters, return target creature card from your "
                   "graveyard to your hand.",
    "Nekrataal": "When Nekrataal enters, destroy target creature.",
    "Shriekmaw": "When Shriekmaw enters, destroy target creature.",
    "Bone Shredder": "When Bone Shredder enters, destroy target creature.",
    "Bloodgift Demon": "At the beginning of your upkeep, you draw a card and you "
                       "lose 1 life.",
    "Plaguecrafter": "When Plaguecrafter enters, each opponent sacrifices a creature.",
    "Reassembling Skeleton": "{1}{B}: Return Reassembling Skeleton from your "
                             "graveyard to the battlefield.",
    "Corpse Augur": "When Corpse Augur dies, draw a card.",
    "Nantuko Husk": "Sacrifice a creature: Nantuko Husk gets +2/+2 until end of turn.",
    # --- rojo ---
    "Pia Nalaar": "When Pia Nalaar enters, create a 1/1 colorless Thopter "
                  "artifact creature token with flying.",
    "Zealous Conscripts": "When Zealous Conscripts enters, untap target permanent.",
    # --- verde ---
    "Elvish Visionary": "When Elvish Visionary enters, draw a card.",
    "Sakura-Tribe Elder": "Sacrifice Sakura-Tribe Elder: Search your library for a "
                          "basic land card, put it onto the battlefield tapped, "
                          "then shuffle.",
    "Wood Elves": "When Wood Elves enters, search your library for a Forest card, "
                  "put it onto the battlefield, then shuffle.",
    "Eternal Witness": "When Eternal Witness enters, return target creature card "
                       "from your graveyard to your hand.",
    "Beast Whisperer": "Whenever you cast a creature spell, draw a card.",
}


def _braces(cost: str) -> str:
    """'2U' / '1WW' -> '{2}{U}' / '{1}{W}{W}' para cardsdb."""
    return "".join("{%s}" % t for t in re.findall(r"\d+|[WUBRGC]", cost.upper()))


def _mk_filler(name, cost, pw, tf, kw, colors):
    """Criatura de relleno: con efecto real (vía cardsdb) si conocemos su oracle;
    si no, un cuerpo simple como antes."""
    oracle = _FILLER_ORACLE.get(name)
    if oracle:
        ci = list(dict.fromkeys(re.findall(r"[WUBRG]", cost.upper())))
        return cardsdb.build_card_from_data({
            "name": name, "type_line": "Creature", "mana_cost": _braces(cost),
            "power": str(pw), "toughness": str(tf),
            "keywords": [k for k in kw], "color_identity": ci,
            "oracle_text": oracle})
    return creature(name, cost, pw, tf, kw=kw, color_id=colors)


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


# Objetivo de tierras de un mazo real de Commander (~37 de 99). Antes se rellenaba
# TODO con basicas -> 77-86 tierras -> manos inundadas de tierra y el mulligan parecia
# no cambiar nada. Ahora topamos las tierras y completamos con cartas reales en color.
TARGET_LANDS = 37

# Pool de relleno: criaturas REALES por color (traen ilustracion de Scryfall).
# (nombre, coste, fuerza, resistencia, keywords)
_FILLER = {
    W: [
        ("Wall of Omens", "1W", 0, 4, ()), ("Kor Skyfisher", "1W", 2, 3, ("flying",)),
        ("Blade Splicer", "2W", 1, 1, ()), ("Fiend Hunter", "1WW", 1, 3, ()),
        ("Precinct Captain", "1W", 2, 2, ("first strike",)), ("Thraben Inspector", "W", 1, 2, ()),
        ("Banisher Priest", "1WW", 2, 2, ()), ("Leonin Warleader", "2WW", 4, 4, ()),
        ("Mentor of the Meek", "2W", 2, 2, ()), ("Palace Jailer", "3W", 2, 2, ()),
        ("Attended Knight", "2W", 2, 2, ("first strike",)), ("Whitemane Lion", "1W", 2, 2, ()),
        ("Cloudgoat Ranger", "3WW", 2, 2, ()), ("Loxodon Smiter", "1WW", 4, 4, ()),
        ("Skyhunter Skirmisher", "1W", 1, 1, ("flying", "double strike")),
        ("Sunlance Cleric", "1W", 2, 1, ()), ("Auriok Champion", "WW", 1, 1, ()),
        ("Ranger of Eos", "3W", 3, 2, ()), ("Dawnbringer Charioteers", "3W", 3, 4, ("flying",)),
        ("Angel of Vitality", "1WW", 2, 2, ("flying",)),
    ],
    U: [
        ("Man-o'-War", "2U", 2, 2, ()), ("Cloudkin Seer", "2U", 2, 2, ("flying",)),
        ("Mulldrifter", "4U", 2, 2, ("flying",)), ("Pestermite", "2U", 2, 1, ("flying", "flash")),
        ("Wall of Frost", "1UU", 0, 7, ()), ("Silvergill Adept", "1U", 2, 1, ()),
        ("Looter il-Kor", "1U", 1, 1, ()), ("Aven Fisher", "3U", 2, 2, ("flying",)),
        ("Riftwing Cloudskate", "3U", 2, 2, ("flying",)), ("Cursecatcher", "U", 1, 1, ()),
        ("Fog Bank", "1U", 0, 2, ("flying",)), ("Sower of Temptation", "2UU", 2, 2, ("flying",)),
        ("Phantasmal Bear", "U", 2, 2, ()), ("Deranged Assistant", "1U", 1, 1, ()),
        ("Cloud Elemental", "3U", 2, 3, ("flying",)), ("Sea Scryer", "1U", 1, 1, ()),
        ("Wavesifter", "3U", 2, 2, ("flying",)), ("Chasm Skulker", "1U", 1, 1, ()),
        ("Spire Owl", "2U", 1, 3, ("flying",)), ("Tandem Lookout", "3U", 2, 2, ()),
    ],
    B: [
        ("Phyrexian Rager", "2B", 2, 2, ()), ("Nekrataal", "2BB", 2, 1, ("first strike",)),
        ("Gravedigger", "3B", 2, 2, ()), ("Bone Shredder", "2B", 1, 1, ("flying",)),
        ("Shriekmaw", "4BB", 3, 2, ()), ("Bloodgift Demon", "3BB", 5, 4, ("flying",)),
        ("Doomed Dissenter", "1B", 1, 1, ()), ("Carrion Feeder", "B", 1, 1, ()),
        ("Big Game Hunter", "2B", 1, 1, ()), ("Fume Spitter", "B", 1, 1, ()),
        ("Plaguecrafter", "2B", 3, 2, ()), ("Liliana's Reaver", "3BB", 2, 4, ()),
        ("Grim Haruspex", "2B", 3, 2, ()), ("Vampire Hexmage", "BB", 2, 2, ("first strike",)),
        ("Crypt Rats", "2B", 1, 1, ()), ("Bloodhusk Ritualist", "2BB", 2, 2, ()),
        ("Dread Wanderer", "B", 2, 2, ()), ("Cave Scavenger", "3B", 3, 2, ()),
        ("Nested Shambler", "1B", 1, 1, ()), ("Corpse Augur", "2B", 3, 2, ()),
        ("Vampire Sovereign", "4BB", 3, 4, ("flying",)), ("Sengir Autocrat", "3B", 2, 2, ()),
        ("Bala Ged Scorpion", "3B", 2, 2, ()), ("Twisted Abomination", "5B", 5, 3, ()),
        ("Reassembling Skeleton", "1B", 1, 1, ()), ("Moaning Wall", "2B", 0, 4, ()),
        ("Nantuko Husk", "2B", 2, 2, ()), ("Gloomhunter", "3B", 2, 2, ("flying",)),
        ("Bloodghast", "B", 2, 1, ()), ("Vampire Lacerator", "B", 2, 2, ()),
        ("Gatekeeper of Malakir", "BB", 2, 2, ()), ("Skinrender", "3B", 3, 3, ()),
        ("Disciple of Bolas", "3B", 2, 2, ()), ("Child of Night", "1B", 2, 1, ("lifelink",)),
        ("Crypt Ghast", "2BB", 2, 2, ()), ("Ravenous Rats", "2B", 1, 1, ()),
        ("Chittering Rats", "2B", 2, 2, ()), ("Vault Skirge", "B", 1, 1, ("flying", "lifelink")),
        ("Cackling Fiend", "2B", 2, 2, ()), ("Highborn Ghoul", "1B", 2, 2, ("menace",)),
        ("Festering Goblin", "B", 1, 1, ()), ("Wight of Precinct Six", "1B", 1, 1, ()),
    ],
    R: [
        ("Young Pyromancer", "1R", 2, 1, ()), ("Goblin Rabblemaster", "2R", 2, 2, ()),
        ("Hellrider", "2RR", 3, 3, ("haste",)), ("Ash Zealot", "1RR", 2, 2, ("first strike", "haste")),
        ("Kird Ape", "R", 1, 1, ()), ("Fanatic of Mogis", "3R", 3, 2, ()),
        ("Charging Monstrosaur", "3RR", 5, 5, ("trample", "haste")), ("Torch Fiend", "2R", 2, 2, ()),
        ("Zealous Conscripts", "4R", 3, 3, ("haste",)), ("Hellspark Elemental", "R", 3, 1, ("trample", "haste")),
        ("Ember Hauler", "1R", 2, 2, ()), ("Pia Nalaar", "2R", 2, 2, ()),
        ("Chandra's Phoenix", "2R", 2, 2, ("flying", "haste")), ("Magmatic Channeler", "1R", 1, 3, ()),
        ("Goblin Chainwhirler", "RRR", 3, 3, ("first strike",)), ("Ash Barrens Marauder", "3R", 3, 2, ()),
        ("Fire Elemental", "3R", 5, 4, ()), ("Bogardan Dragonheart", "1R", 2, 1, ()),
        ("Cinder Pyromancer", "2R", 1, 1, ()), ("Viashino Pyromancer", "1R", 2, 1, ()),
    ],
    G: [
        ("Sakura-Tribe Elder", "1G", 1, 1, ()), ("Beast Whisperer", "3G", 2, 3, ()),
        ("Elvish Visionary", "1G", 1, 1, ()), ("Wood Elves", "2G", 1, 1, ()),
        ("Yavimaya Elder", "1GG", 2, 1, ()), ("Eternal Witness", "1GG", 2, 1, ()),
        ("Acidic Slime", "3GG", 2, 2, ("deathtouch",)), ("Reclamation Sage", "2G", 2, 1, ()),
        ("Fauna Shaman", "1G", 2, 2, ()), ("Scavenging Ooze", "1G", 2, 2, ()),
        ("Nessian Courser", "2G", 3, 3, ()), ("Pelakka Wurm", "5GG", 7, 7, ("trample",)),
        ("Ambush Viper", "1G", 2, 1, ("flash", "deathtouch")), ("Wall of Blossoms", "1G", 0, 4, ()),
        ("Deathgorge Scavenger", "2G", 3, 2, ()), ("Tireless Tracker", "2G", 3, 2, ()),
        ("Courser of Kruphix", "1GG", 2, 4, ()), ("River Boa", "1G", 2, 1, ()),
        ("Vinelasher Kudzu", "1G", 1, 1, ()), ("Silverback Elder", "3GG", 6, 6, ("trample",)),
    ],
}


def _fill(deck, identity):
    """Completa el mazo a 99 con un ratio jugable: ~TARGET_LANDS tierras y el resto
    con cartas reales en color (traen arte)."""
    colors = [c for c in (W, U, B, R, G) if c in identity] or [C]

    def _add_land(idx):
        color = colors[idx % len(colors)]
        deck.append(land("Wastes", [C], basic=True) if color == C else _basic(color))

    # 1) tierras basicas hasta ~TARGET_LANDS (o hasta llenar si el mazo es chico)
    i = 0
    while sum(1 for x in deck if x.is_land()) < TARGET_LANDS and len(deck) < 99:
        _add_land(i); i += 1

    # 2) relleno no-tierra con cartas reales en color, sin duplicar cuando se puede
    used = {getattr(x, "name", "") for x in deck}
    base_pool = [spec for c in colors for spec in _FILLER.get(c, [])]
    ordered = [s for s in base_pool if s[0] not in used]      # distintas primero
    k = 0
    while len(deck) + len(ordered) < 99 and base_pool:        # si faltan, ciclar (dups)
        ordered.append(base_pool[k % len(base_pool)]); k += 1
    for name, cost, pw, tf, kw in ordered:
        if len(deck) >= 99:
            break
        deck.append(_mk_filler(name, cost, pw, tf, kw, tuple(colors)))

    # 3) si el pool era chico (mono-color) y aun faltan slots, completar con tierras
    i = 0
    while len(deck) < 99:
        _add_land(i); i += 1
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
