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
    # Otros de la lista oficial que faltaban
    "Mana Crypt", "Crop Rotation", "Fastbond", "Field of the Dead", "Food Chain",
    "Glacial Chasm", "Humility", "Intuition", "Panoptic Mirror",
    "Survival of the Fittest", "The Tabernacle at Pendrell Vale",
]

# --------------------------------------------------------------------------- #
# Pilares del sistema de brackets (además de los Game Changers).
# El bracket real de WotC mira estas categorías, no sólo la lista de GC:
#   - Negación masiva de tierras (Mass Land Denial)
#   - Turnos extra (sobre todo encadenados)
#   - Tutores (muchos = mazo más consistente/optimizado)
#   - Aceleración explosiva (fast mana, aparte del ubicuo Sol Ring)
# --------------------------------------------------------------------------- #

MASS_LAND_DENIAL_RAW = [
    "Armageddon", "Ravages of War", "Catastrophe", "Cataclysm", "Jokulhaups",
    "Obliterate", "Decree of Annihilation", "Winter Orb", "Static Orb", "Stasis",
    "Blood Moon", "Back to Basics", "Ruination", "Boil", "Boiling Seas",
    "Bend or Break", "Impending Disaster", "Fall of the Thran", "Sunder",
    "Mana Vortex", "Wildfire", "Burning of Xinye", "Tectonic Break",
    "Global Ruin", "Death Cloud", "Contamination",
]

EXTRA_TURNS_RAW = [
    "Time Warp", "Temporal Manipulation", "Capture of Jingzhou", "Time Stretch",
    "Walk the Aeons", "Temporal Mastery", "Nexus of Fate", "Part the Waterveil",
    "Karn's Temporal Sundering", "Alrund's Epiphany", "Temporal Trespass",
    "Time Sieve", "Timestream Navigator", "Seedtime", "Beacon of Tomorrows",
    "Savor the Moment", "Ugin's Nexus", "Notorious Throng", "Last Chance",
    "Final Fortune", "Plea for Power", "Emrakul, the Aeons Torn",
]

TUTORS_RAW = [
    "Demonic Tutor", "Vampiric Tutor", "Imperial Seal", "Grim Tutor",
    "Diabolic Tutor", "Diabolic Intent", "Beseech the Mirror", "Scheming Symmetry",
    "Wishclaw Talisman", "Enlightened Tutor", "Mystical Tutor", "Worldly Tutor",
    "Personal Tutor", "Sylvan Tutor", "Gamble", "Tainted Pact", "Demonic Consultation",
    "Green Sun's Zenith", "Chord of Calling", "Finale of Devastation",
    "Survival of the Fittest", "Fabricate", "Whir of Invention", "Tinker",
    "Gifts Ungiven", "Intuition", "Fauna Shaman", "Eldritch Evolution",
    "Natural Order", "Tooth and Nail", "Idyllic Tutor", "Steelshaper's Gift",
    "Stoneforge Mystic", "Recruiter of the Guard", "Imperial Recruiter",
]

# Fast mana explosiva; NO incluye Sol Ring (ubicuo, no restringido por WotC).
FAST_MANA_RAW = [
    "Mana Crypt", "Mana Vault", "Grim Monolith", "Jeweled Lotus", "Chrome Mox",
    "Mox Diamond", "Mox Opal", "Mox Amber", "Mox Jet", "Mox Ruby", "Mox Sapphire",
    "Mox Pearl", "Mox Emerald", "Lotus Petal", "Lion's Eye Diamond", "Black Lotus",
    "Dark Ritual", "Cabal Ritual", "Rite of Flame", "Pyretic Ritual",
    "Desperate Ritual", "Lotus Bloom", "Simian Spirit Guide", "Elvish Spirit Guide",
    "Ancient Tomb", "Gaea's Cradle", "Serra's Sanctum", "Mishra's Workshop",
]


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _mkset(raw):
    return {_norm(n) for n in raw}


GAME_CHANGERS = _mkset(GAME_CHANGERS_RAW)
MASS_LAND_DENIAL = _mkset(MASS_LAND_DENIAL_RAW)
EXTRA_TURNS = _mkset(EXTRA_TURNS_RAW)
TUTORS = _mkset(TUTORS_RAW)
FAST_MANA = _mkset(FAST_MANA_RAW)


def is_game_changer(name):
    return _norm(name) in GAME_CHANGERS


def find_in(names):
    """Devuelve los nombres (tal cual entraron) que son Game Changers."""
    return _found_in(names, GAME_CHANGERS)


def _found_in(names, table):
    """Nombres (tal cual entraron) presentes en `table` (set normalizado), únicos."""
    seen = set()
    out = []
    for n in names:
        k = _norm(n)
        if k in table and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def bracket_hint(gc_count):
    """Estimacion GRUESA del bracket SÓLO por cantidad de Game Changers.
    Se mantiene por compatibilidad; para una estimación real usá
    estimate_bracket(names), que mira todos los pilares del sistema."""
    if gc_count == 0:
        return 2, "Base (sin Game Changers)"
    if gc_count <= 3:
        return 3, "Mejorado (pocos Game Changers)"
    if gc_count <= 6:
        return 4, "Optimizado (varios Game Changers)"
    return 5, "cEDH (muchos Game Changers)"


def scan(names):
    """Detecta qué pilares del sistema de brackets están presentes en `names`.
    Devuelve un dict con las listas de cartas encontradas por categoría."""
    return {
        "game_changers": find_in(names),
        "mass_land_denial": _found_in(names, MASS_LAND_DENIAL),
        "extra_turns": _found_in(names, EXTRA_TURNS),
        "tutors": _found_in(names, TUTORS),
        "fast_mana": _found_in(names, FAST_MANA),
    }


_LABELS = {
    1: "Exhibición",
    2: "Base",
    3: "Mejorado",
    4: "Optimizado",
    5: "cEDH",
}


def estimate_bracket(names):
    """Estimación de bracket alineada a los pilares de WotC.

    Mira, además de los Game Changers: negación masiva de tierras, turnos extra
    (sobre todo encadenados), densidad de tutores y aceleración explosiva.
    Devuelve (bracket:int, label:str, info:dict) donde info trae las cartas que
    dispararon cada señal y los motivos legibles.
    """
    s = scan(names)
    n_gc = len(s["game_changers"])
    n_mld = len(s["mass_land_denial"])
    n_turns = len(s["extra_turns"])
    n_tutors = len(s["tutors"])
    n_fast = len(s["fast_mana"])

    reasons = []

    # --- Señales de bracket 4/5 (no permitidas en 1-3 por las reglas de WotC) ---
    # Negación masiva de tierras y turnos extra ENCADENADOS empujan a Optimizado.
    hard_signals = []
    if n_mld:
        hard_signals.append("negación masiva de tierras")
    if n_turns >= 2:
        hard_signals.append("turnos extra encadenados")
    if n_gc >= 4:
        hard_signals.append(f"{n_gc} Game Changers")

    # cEDH: combinación de mucho fast mana + tutores + game changers.
    cedh = n_gc >= 4 and n_fast >= 3 and n_tutors >= 3

    if cedh:
        bracket = 5
        reasons.append("Muchos Game Changers + aceleración y tutores densos (perfil cEDH).")
    elif hard_signals:
        bracket = 4
        reasons.append("Optimizado por: " + ", ".join(hard_signals) + ".")
    else:
        # --- Señales de bracket 3 (Mejorado) ---
        soft = []
        if n_gc >= 1:
            soft.append(f"{n_gc} Game Changer" + ("s" if n_gc > 1 else ""))
        if n_turns == 1:
            soft.append("un hechizo de turno extra")
        if n_tutors >= 3:
            soft.append(f"{n_tutors} tutores")
        if n_fast >= 3:
            soft.append(f"{n_fast} piezas de fast mana")
        if soft:
            bracket = 3
            reasons.append("Mejorado por: " + ", ".join(soft) + ".")
        else:
            bracket = 2
            reasons.append("Sin Game Changers ni combos/negación de recursos "
                           "de alto impacto: perfil Base.")

    # matices informativos (no cambian el bracket)
    if bracket <= 3 and 1 <= n_tutors <= 2:
        reasons.append(f"Tiene {n_tutors} tutor" + ("es" if n_tutors > 1 else "") +
                       " (pocos; no sube el bracket).")

    label = _LABELS[bracket]
    info = {
        "counts": {"game_changers": n_gc, "mass_land_denial": n_mld,
                   "extra_turns": n_turns, "tutors": n_tutors, "fast_mana": n_fast},
        "found": s,
        "reasons": reasons,
    }
    return bracket, label, info
