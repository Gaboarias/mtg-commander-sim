"""Lista de 'Game Changers' del sistema de Brackets de Commander (WotC).

IMPORTANTE: esta es una lista CURADA de cartas que sabemos que estan (o han
estado) en la lista oficial de Game Changers. La lista oficial la mantiene y
actualiza Wizards; verificala/completala contra la fuente oficial. Editar aca.

Uso: detectar cuantos Game Changers trae un deck para estimar su bracket.
Brackets (WotC): 1 Exhibicion · 2 Base · 3 Mejorado · 4 Optimizado · 5 cEDH.
"""
from __future__ import annotations

import re

# Nombres tal como aparecen en Scryfall. Curada; ampliable.
GAME_CHANGERS_RAW = [
    # Ventaja de cartas / motores
    "Rhystic Study", "Mystic Remora", "Necropotence", "Smothering Tithe",
    "Consecrated Sphinx", "The One Ring", "Sylvan Library",
    # Contramagia / proteccion gratis
    "Mana Drain", "Fierce Guardianship", "Deflecting Swat", "Jeska's Will",
    # Tutores
    "Demonic Tutor", "Vampiric Tutor", "Imperial Seal", "Grim Tutor",
    "Enlightened Tutor", "Mystical Tutor", "Worldly Tutor", "Tainted Pact",
    "Gamble", "Grand Abolisher",
    # Combos / win-cons / bombas
    "Thassa's Oracle", "Demonic Consultation", "Underworld Breach",
    "Ad Nauseam", "Bolas's Citadel", "Coalition Victory", "Expropriate",
    "Cyclonic Rift",
    # Mana / aceleracion explosiva
    "Jeweled Lotus", "Mana Vault", "Grim Monolith", "Chrome Mox", "Mox Diamond",
    "Mishra's Workshop", "Ancient Tomb", "Gaea's Cradle", "Serra's Sanctum",
    "Lion's Eye Diamond",
    # Robo/negacion de recursos y stax
    "Hullbreacher", "Notion Thief", "Opposition Agent", "Drannith Magistrate",
    "Grand Arbiter Augustin IV", "Trinisphere", "Winter Orb", "Stasis",
    "Aura Shards",
    # Comandantes/piezas de alto impacto
    "Kinnan, Bonder Prodigy", "Urza, Lord High Artificer", "Winota, Joiner of Forces",
    "Yuriko, the Tiger's Shadow", "Najeela, the Blade-Blossom", "Tergrid, God of Fright",
    "Nadu, Winged Wisdom", "Gilded Drake",
]


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


GAME_CHANGERS = {_norm(n) for n in GAME_CHANGERS_RAW}


def is_game_changer(name):
    return _norm(name) in GAME_CHANGERS


def find_in(names):
    """Devuelve los nombres (tal cual entraron) que son Game Changers."""
    seen = set()
    out = []
    for n in names:
        k = _norm(n)
        if k in GAME_CHANGERS and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def bracket_hint(gc_count):
    """Estimacion GRUESA del bracket por cantidad de Game Changers.
    (El bracket real considera mas cosas: negacion masiva de tierras, turnos
    extra encadenados, combos de 2 cartas, tutores... esto es una guia.)"""
    if gc_count == 0:
        return 2, "Base (sin Game Changers)"
    if gc_count <= 3:
        return 3, "Mejorado (pocos Game Changers)"
    if gc_count <= 6:
        return 4, "Optimizado (varios Game Changers)"
    return 5, "cEDH (muchos Game Changers)"
