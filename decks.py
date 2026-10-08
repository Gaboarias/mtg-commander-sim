"""Mazos de ejemplo (99 + comandante).

Cada función devuelve (deck, commander). TODAS las cartas no-tierra se construyen
desde su oráculo REAL (data/preset_cards.json, bajado de Scryfall con
scripts/snapshot_preset_cards.py): coste, tipos, P/T, keywords y texto. Antes había
estadísticas y textos tipeados a mano, varios inventados (regla 5 de CLAUDE.md).
Las tierras usan el modelo simple del motor (una fuente = un maná).
"""
from __future__ import annotations

import copy
import json
import os

from engine import W, U, B, R, G, C
import cards
import cardsdb
from cards import land, rock

_SNAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                          "preset_cards.json")
_SNAP = None


def snapshot() -> dict:
    """{nombre: datos de Scryfall} de las cartas de los presets."""
    global _SNAP
    if _SNAP is None:
        try:
            with open(_SNAP_PATH, encoding="utf-8") as f:
                _SNAP = json.load(f).get("cards", {})
        except (OSError, ValueError):
            _SNAP = {}
    return _SNAP


_PROTO: dict = {}


def real_or_none(name, tags=()):
    """Carta REAL por nombre: implementación fiel del registro si existe; si no,
    su oráculo real vía el parser. None si no está en el snapshot. El parseo se
    cachea por nombre (cada partida arma los mazos de nuevo) y se devuelve una
    copia propia (como hace make_copy_token)."""
    if cardsdb.is_implemented(name):
        c = cardsdb.resolve(name)
    else:
        if name not in _PROTO:
            row = snapshot().get(name)
            _PROTO[name] = None if row is None else cardsdb.build_card_from_data(dict(row))
        if _PROTO[name] is None:
            return None
        c = copy.deepcopy(_PROTO[name])
    if tags:
        c.tags = set(c.tags) | set(tags)
    return c


def real(name, tags=()):
    c = real_or_none(name, tags)
    if c is None:
        raise KeyError(f"{name!r} no está en data/preset_cards.json (¿existe la carta?)")
    return c


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


# Objetivo de tierras de un mazo real de Commander (~37 de 99).
TARGET_LANDS = 37

# Pool de relleno: criaturas REALES por color (datos del snapshot).
_FILLER = {
    W: ["Wall of Omens", "Kor Skyfisher", "Blade Splicer", "Fiend Hunter",
        "Precinct Captain", "Thraben Inspector", "Banisher Priest", "Leonin Warleader",
        "Mentor of the Meek", "Palace Jailer", "Attended Knight", "Whitemane Lion",
        "Cloudgoat Ranger", "Skyhunter Skirmisher", "Auriok Champion", "Ranger of Eos",
        "Dawnbringer Charioteers", "Angel of Vitality"],
    U: ["Man-o'-War", "Cloudkin Seer", "Mulldrifter", "Pestermite", "Wall of Frost",
        "Silvergill Adept", "Looter il-Kor", "Aven Fisher", "Riftwing Cloudskate",
        "Cursecatcher", "Fog Bank", "Sower of Temptation", "Phantasmal Bear",
        "Deranged Assistant", "Cloud Elemental", "Sea Scryer", "Chasm Skulker",
        "Spire Owl", "Tandem Lookout"],
    B: ["Phyrexian Rager", "Nekrataal", "Gravedigger", "Bone Shredder", "Shriekmaw",
        "Bloodgift Demon", "Doomed Dissenter", "Carrion Feeder", "Big Game Hunter",
        "Fume Spitter", "Plaguecrafter", "Liliana's Reaver", "Grim Haruspex",
        "Vampire Hexmage", "Crypt Rats", "Bloodhusk Ritualist", "Dread Wanderer",
        "Nested Shambler", "Corpse Augur", "Vampire Sovereign", "Sengir Autocrat",
        "Bala Ged Scorpion", "Twisted Abomination", "Reassembling Skeleton",
        "Moaning Wall", "Nantuko Husk", "Gloomhunter", "Bloodghast", "Vampire Lacerator",
        "Gatekeeper of Malakir", "Skinrender", "Disciple of Bolas", "Child of Night",
        "Crypt Ghast", "Ravenous Rats", "Chittering Rats", "Vault Skirge",
        "Cackling Fiend", "Highborn Ghoul", "Festering Goblin", "Wight of Precinct Six"],
    R: ["Young Pyromancer", "Goblin Rabblemaster", "Hellrider", "Ash Zealot", "Kird Ape",
        "Fanatic of Mogis", "Charging Monstrosaur", "Torch Fiend", "Zealous Conscripts",
        "Hellspark Elemental", "Ember Hauler", "Pia Nalaar", "Chandra's Phoenix",
        "Magmatic Channeler", "Goblin Chainwhirler", "Fire Elemental",
        "Bogardan Dragonheart", "Cinder Pyromancer", "Viashino Pyromancer"],
    G: ["Sakura-Tribe Elder", "Beast Whisperer", "Elvish Visionary", "Wood Elves",
        "Yavimaya Elder", "Eternal Witness", "Acidic Slime", "Reclamation Sage",
        "Fauna Shaman", "Scavenging Ooze", "Nessian Courser", "Pelakka Wurm",
        "Ambush Viper", "Wall of Blossoms", "Deathgorge Scavenger", "Tireless Tracker",
        "Courser of Kruphix", "River Boa", "Vinelasher Kudzu", "Silverback Elder"],
}


def _fill(deck, identity):
    """Completa el mazo a 99: ~TARGET_LANDS tierras y el resto con criaturas reales
    del pool, SIN duplicar y SIN salir de la identidad (singleton)."""
    colors = [c for c in (W, U, B, R, G) if c in identity] or [C]

    def _add_land(idx):
        color = colors[idx % len(colors)]
        deck.append(land("Wastes", [C], basic=True) if color == C else _basic(color))

    i = 0
    while sum(1 for x in deck if x.is_land()) < TARGET_LANDS and len(deck) < 99:
        _add_land(i); i += 1

    used = {getattr(x, "name", "") for x in deck}
    ident = set(identity)
    # intercalar colores (no 20 blancas y después 20 rojas)
    pools = [list(_FILLER.get(c, [])) for c in colors]
    order = []
    while any(pools):
        for pl in pools:
            if pl:
                order.append(pl.pop(0))
    for name in order:
        if len(deck) >= 99:
            break
        if name in used:
            continue
        c = real_or_none(name)
        if c is None or not (set(c.identity()) - {C}) <= ident:
            continue
        used.add(name)
        deck.append(c)

    i = 0
    while len(deck) < 99:
        _add_land(i); i += 1
    return deck[:99]


# --------------------------------------------------------------------------- #
# LOREHOLD (R/W)
# --------------------------------------------------------------------------- #

def lorehold():
    commander = cards.Quintorius()
    d = [real(n) for n in (
        "Hofri Ghostforge", "Bag of Holding", "Sevinne's Reclamation", "Faithless Looting",
        "Underworld Breach", "Sun Titan", "Karmic Guide", "Doomed Traveler",
        "Bloodrage Brawler", "Glorious Anthem", "Quintorius Kand", "Goblin Cratermaker",
        "Seasoned Hallowblade", "Serra Angel", "Flametongue Kavu", "Wall of Reverence",
        "Swords to Plowshares", "Blasphemous Act", "Tormenting Voice")]
    d.append(rock("Boros Signet", "2", [R, W]))
    d.append(rock("Arcane Signet", "2", [R, W]))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(land("Sacred Foundry", [R, W]))
    d.append(land("Temple of Triumph", [R, W], tapped=True))
    return _fill(d, commander.identity()), commander


# --------------------------------------------------------------------------- #
# TRICKY (G/U) — contadores
# --------------------------------------------------------------------------- #

def _omo_commander():
    """Omo, Queen of Vesuva — oráculo real. La IA no lo lanza sin otra criatura
    (su disparo de entrada pone un contador en una criatura objetivo)."""
    c = real("Omo, Queen of Vesuva", tags=("engine",))
    c.needs_ally = True
    return c


def tricky():
    """Tricky Terrain (Omo, Queen of Vesuva) — cartas reales del precon."""
    commander = _omo_commander()
    d = [real(n) for n in (
        "Managorger Hydra", "Kalonian Hydra", "Simic Ascendancy", "Branching Evolution",
        "Hardened Scales", "Forgotten Ancient", "Evolution Sage", "Vorel of the Hull Clade",
        "Biogenic Ooze", "Zegana, Utopian Speaker", "Hydroid Krasis", "Trygon Predator",
        "Fathom Mage", "Sakura-Tribe Elder", "Eternal Witness", "Solemn Simulacrum",
        "Herd Baloth", "Bloated Contaminator", "Cultivate", "Kodama's Reach", "Farseek",
        "Inexorable Tide", "Counterspell", "Deep Analysis", "Heroic Intervention",
        "Beast Within", "Pongify", "Rapid Hybridization")]
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(rock("Arcane Signet", "2", [G, U]))
    d.append(rock("Simic Signet", "2", [G, U]))
    for name in ("Command Tower", "Breeding Pool", "Hinterland Harbor",
                 "Botanical Sanctum", "Yavimaya Coast", "Barkchannel Pathway"):
        d.append(land(name, [G, U]))
    for name in ("Temple of Mystery", "Woodland Stream", "Simic Growth Chamber",
                 "Rejuvenating Springs", "Lumbering Falls"):
        d.append(land(name, [G, U], tapped=True))
    d.append(land("Terramorphic Expanse", [C], tapped=True))
    return _fill(d, commander.identity()), commander


# --------------------------------------------------------------------------- #
# KANG (U/B) — connive / drenaje
# --------------------------------------------------------------------------- #

def _kang_core(identity):
    d = [real(n) for n in (
        "Gray Merchant of Asphodel", "Go for the Throat", "Night's Whisper", "Damnation",
        "Gifted Aetherborn", "Vampire Nighthawk", "Ravenous Chupacabra",
        "Archfiend of Depravity", "Sengir Vampire", "Dusk Legion Zealot")]
    d.append(rock("Arcane Signet", "2", sorted(identity)))
    if U in identity:
        d.append(rock("Dimir Signet", "2", [U, B]))
        d.append(real("Counterspell"))
    d.append(rock("Sol Ring", "1", [C, C]))
    d.append(land("Barren Moor", [B], tapped=True))
    return _fill(d, identity)


def kang():
    commander = cards.Kang()          # Kang, Temporal Tyrant {2}{U}{B}
    return _kang_core(commander.identity()), commander


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #

DECKS = {
    "lorehold": lorehold,
    "tricky": tricky,
    "kang": kang,
}

# Ejemplos públicos: reutilizan los 99 con otro comandante REAL de la misma
# identidad (marvel es mono-negro: arma su propio 99 sin cartas azules).

def strixhaven():
    deck, _cmd = lorehold()          # 99 R/W
    return deck, real("Feather, the Redeemed", tags=("engine",))


def old_guard():
    deck, _cmd = tricky()            # 99 G/U
    return deck, real("Kinnan, Bonder Prodigy", tags=("engine",))


def marvel():
    commander = real("Sheoldred, the Apocalypse", tags=("engine",))
    return _kang_core(commander.identity()), commander


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

# UNIFICACIÓN: "tricky-terrain" (el preset .md) y "tricky" son el MISMO mazo. La
# versión por código tiene a Omo con su habilidad real, tierras reales, rampeo,
# protección (Heroic Intervention) y un ratio de tierras sano (~37). El .md queda
# como documentación, pero el mazo jugable es el curado por código.
DECKS["tricky-terrain"] = tricky
DECK_SOURCE["tricky-terrain"] = "preset"


_BASIC_NAMES = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}


def validate(deck, commander):
    """Problemas de legalidad de Commander del mazo (lista vacía = legal):
    tamaño (99, o 98 con partner), singleton salvo básicas, e identidad de color."""
    problems = []
    partner = getattr(commander, "_partner", None)
    size = 98 if partner is not None else 99
    if len(deck) != size:
        problems.append(f"{len(deck)} cartas (deben ser {size})")
    ident = set(commander.identity()) | (set(partner.identity()) if partner else set())
    seen = {}
    for c in deck:
        if c.name not in _BASIC_NAMES:
            seen[c.name] = seen.get(c.name, 0) + 1
        extra = set(c.identity()) - ident - {C}
        if extra:
            problems.append(f"{c.name} fuera de la identidad ({''.join(sorted(extra))})")
    for n, k in seen.items():
        if k > 1:
            problems.append(f"{n} x{k} (singleton)")
    return problems


def build(name):
    if name not in DECKS:
        raise KeyError(f"mazo desconocido: {name}. Opciones: {list(DECKS)}")
    return DECKS[name]()
