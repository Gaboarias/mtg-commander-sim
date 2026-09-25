"""Base de combos EDH curada (offline). Complementa a Commander Spellbook: la
API externa puede estar caída o bloqueada, y este detector siempre propone algo.

Cada combo: piezas (nombres EXACTOS de Scryfall, para poder sumarlas), qué
produce (en español, corto) y su identidad de color `ci` (para no proponer un
combo azul a un mazo mono-rojo). El detector devuelve la misma forma que usa el
frontend: {id, cards, produces, missing}.

- included: TODAS las piezas están en el mazo (combo armado).
- almost:  falta EXACTAMENTE una pieza y el combo entra en la identidad del mazo
           (accionable: "estás a una carta").
"""
import re

# --------------------------------------------------------------------------- #
# Combos curados (2–3 piezas, conocidos y que ganan/hacen infinito)
# --------------------------------------------------------------------------- #
# (piezas, produce, identidad_de_color)
_COMBOS = [
    # --- salir del mazo / ganar directo (UB) ---
    (["Thassa's Oracle", "Demonic Consultation"],
     "Ganás la partida (vaciás tu biblioteca y Thassa's Oracle gana)", "UB"),
    (["Thassa's Oracle", "Tainted Pact"],
     "Ganás la partida (biblioteca a 0 + Thassa's Oracle)", "UB"),
    (["Laboratory Maniac", "Demonic Consultation"],
     "Ganás la partida (te quedás sin biblioteca con Lab Maniac en juego)", "UB"),
    (["Jace, Wielder of Mysteries", "Demonic Consultation"],
     "Ganás la partida (robás con la biblioteca vacía)", "UB"),
    (["Underworld Breach", "Lion's Eye Diamond", "Brain Freeze"],
     "Molés a todos hasta ganar (bucle con Underworld Breach)", "UR"),

    # --- fichas / criaturas infinitas (rojo) ---
    (["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"],
     "Fichas de ataque infinitas (con prisa)", "R"),
    (["Kiki-Jiki, Mirror Breaker", "Restoration Angel"],
     "Fichas infinitas de Restoration Angel", "RW"),
    (["Splinter Twin", "Deceiver Exarch"],
     "Fichas de ataque infinitas", "UR"),
    (["Splinter Twin", "Pestermite"],
     "Fichas de ataque infinitas", "UR"),

    # --- maná infinito ---
    (["Isochron Scepter", "Dramatic Reversal"],
     "Maná infinito (con rocas/dorks que den 3+)", "U"),
    (["Basalt Monolith", "Rings of Brighthearth"],
     "Maná incoloro infinito", ""),
    (["Grand Architect", "Pili-Pala"],
     "Maná infinito", "U"),
    (["Devoted Druid", "Vizier of Remedies"],
     "Maná verde infinito", "G"),
    (["Peregrine Drake", "Deadeye Navigator"],
     "Maná infinito", "U"),
    (["Palinchron", "Deadeye Navigator"],
     "Maná infinito", "U"),
    (["Nim Deathmantle", "Ashnod's Altar"],
     "Fichas/maná infinito con cualquier criatura que entre", ""),

    # --- daño / drenaje infinito ---
    (["Mikaeus, the Unhallowed", "Walking Ballista"],
     "Daño infinito a todos", "B"),
    (["Mikaeus, the Unhallowed", "Triskelion"],
     "Daño infinito a todos", "B"),
    (["Heliod, Sun-Crowned", "Walking Ballista"],
     "Daño infinito", "W"),
    (["Sanguine Bond", "Exquisite Blood"],
     "Drenaje infinito: ganás vida y el rival la pierde", "B"),
    (["Exquisite Blood", "Vizkopa Guildmage"],
     "Drenaje infinito", "WB"),
    (["Niv-Mizzet, the Firemind", "Curiosity"],
     "Daño infinito (robás y pinchás por cada carta)", "UR"),
    (["Niv-Mizzet, the Firemind", "Ophidian Eye"],
     "Daño infinito", "UR"),

    # --- aristócratas / persistencia (BG) ---
    (["Mikaeus, the Unhallowed", "Ballista", "Blood Artist"],
     "Drenás toda la mesa (persistencia + aristócrata)", "B"),
    (["Melira, Sylvok Outcast", "Murderous Redcap", "Goblin Bombardment"],
     "Daño infinito (persist + sac outlet)", "BG"),
    (["Karmic Guide", "Reveillark", "Ashnod's Altar"],
     "Bucle de reanimación / sacrificio infinito", "W"),

    # --- combates / turnos extra ---
    (["Godo, Bandit Warlord", "Helm of the Host"],
     "Combates infinitos", "R"),
    (["Aggravated Assault", "Bear Umbra"],
     "Combates infinitos", "RG"),
    (["Time Warp", "Archaeomancer", "Ghostly Flicker"],
     "Turnos infinitos", "U"),

    # --- artefactos ---
    (["Thopter Foundry", "Sword of the Meek", "Ashnod's Altar"],
     "Fichas Thopter y vida infinitas", "WUB"),
    (["Krark-Clan Ironworks", "Myr Retriever", "Scrap Trawler"],
     "Bucle de artefactos / maná", ""),

    # --- reanimación rota ---
    (["Worldgorger Dragon", "Animate Dead"],
     "Maná infinito y ETBs (loop de Worldgorger)", "B"),

    # --- Food Chain ---
    (["Food Chain", "Eternal Scourge"],
     "Maná de criatura infinito", "B"),
    (["Food Chain", "Squee, the Immortal"],
     "Maná de criatura infinito", "R"),

    # --- Dockside ---
    (["Dockside Extortionist", "Temur Sabertooth"],
     "Tesoros infinitos (si el rival tiene artefactos/encantamientos)", "RG"),
]


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _ci(s):
    return set(c for c in (s or "").upper() if c in "WUBRG")


def detect(deck_names, identity=None):
    """`deck_names`: iterable de nombres (comandante + main). `identity`: set de
    colores del mazo (WUBRG) para filtrar los 'almost'. Devuelve {included, almost}."""
    deck = {_norm(n) for n in deck_names if n}
    ident = set(identity or set())
    included, almost = [], []
    for i, (pieces, produces, ci) in enumerate(_COMBOS):
        norm_pieces = [_norm(p) for p in pieces]
        missing = [p for p, npc in zip(pieces, norm_pieces) if npc not in deck]
        present = len(pieces) - len(missing)
        if present == 0:
            continue                                  # nada del combo: no interesa
        entry = {"id": f"local:{i}", "cards": pieces,
                 "produces": [produces], "missing": missing}
        if not missing:
            included.append(entry)
        elif len(missing) == 1:
            # solo proponer si el combo cabe en la identidad de color del mazo
            if not ident or _ci(ci) <= ident:
                almost.append(entry)
    # los 'almost' con más piezas ya presentes primero (más cerca de armarlo)
    almost.sort(key=lambda e: len(e["cards"]) - len(e["missing"]), reverse=True)
    return {"included": included, "almost": almost}
