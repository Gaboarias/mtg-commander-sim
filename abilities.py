"""Biblioteca de habilidades: registro declarativo (patrón -> constructor de
efecto) que actúa como FALLBACK del parser principal.

`cardsdb._generic_amount_effect()` delega acá cuando NO reconoce un texto. Ese
parser central lo usan triggers, ETB, cast-resolve y modos, así que todo lo que
se agregue acá queda disponible en todos esos contextos a la vez.

AGREGAR UNA HABILIDAD NUEVA = agregar una fila a EXTRA_EFFECTS:

    (re.compile(r"patrón", re.I), lambda m: _constructor(...))

Cada constructor devuelve un efecto `eff(game, ctrl, *rest)` SIN objetivo. Mantener
el módulo PURO: usa `cards` / `game` / `ctrl`; NUNCA importar cardsdb (evita un
ciclo de imports). Si un efecto necesita objetivo del humano, va en cardsdb (que
arma el pending_choice); acá viven los efectos de resolución directa.
"""
from __future__ import annotations

import re

import cards

_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _num(word: str) -> int:
    word = (word or "").strip().lower()
    return int(word) if word.isdigit() else _NUMS.get(word, 1)


# -- constructores de efecto (reutilizables) -------------------------------- #
def exile_top_of_library(n: int):
    """Exilia las N cartas de arriba de TU biblioteca (top = final de la lista)."""
    def eff(game, ctrl, *_a, _n=n):
        moved = []
        for _ in range(_n):
            if not ctrl.library:
                break
            c = ctrl.library.pop()
            ctrl.exile.append(c)
            moved.append(c.name)
        if moved:
            game.log(f"{ctrl.name} exilia del tope de su biblioteca: {', '.join(moved)}")
    return eff


def destroy_all_tokens():
    """Destruye todas las fichas en juego (de todos los jugadores)."""
    def eff(game, ctrl, *_a):
        victims = [pm for pl in game.players for pm in list(pl.battlefield) if pm.is_token]
        for pm in victims:
            game.to_graveyard(pm, "destruida (ficha)")
        if victims:
            game.log(f"se destruyen {len(victims)} ficha(s)")
        game.sba()
    return eff


def create_tapped_resource(n: int, kind: str):
    """Crea N fichas-recurso (Treasure/Clue/Food/Blood/Gold) GIRADAS."""
    def eff(game, ctrl, *_a, _n=n, _k=kind):
        made = 0
        for _ in range(_n):
            tok = cards.make_resource_token(game, ctrl, _k)
            if tok is not None:
                tok.tapped = True
                made += 1
        if made:
            game.log(f"{ctrl.name} crea {made} ficha(s) {_k.capitalize()} (girada/s)")
    return eff


# -- registro declarativo: (regex, builder(match) -> eff) ------------------- #
# Orden: el primero que matchee gana. Patrones específicos antes que generales.
EXTRA_EFFECTS = [
    (re.compile(r"\bexile the top (\w+) cards? of your library\b", re.I),
     lambda m: exile_top_of_library(_num(m.group(1)))),

    (re.compile(r"\bdestroy all tokens\b", re.I),
     lambda m: destroy_all_tokens()),

    (re.compile(r"\bcreate (\w+) tapped (?:[\w-]+ )*?"
                r"(treasure|clue|food|blood|gold) tokens?\b", re.I),
     lambda m: create_tapped_resource(_num(m.group(1)), m.group(2))),
]


def effect_from_text(t: str, oracle: str | None = None):
    """Devuelve `eff(game, ctrl, *rest)` para el texto `t` (ya en minúsculas), o
    None si ninguna regla de la biblioteca aplica. Es un FALLBACK: solo corre para
    textos que el parser base de cardsdb no reconoció."""
    low = (t or "").lower()
    for rx, build in EXTRA_EFFECTS:
        m = rx.search(low)
        if m:
            return build(m)
    return None
