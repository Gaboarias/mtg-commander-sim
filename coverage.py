"""Reporte de cuantas cartas tienen efecto real implementado.

Una carta cuenta como IMPLEMENTADA si tiene algun gancho (on_etb, on_death,
on_cast_resolve, triggers, activated, produces) o un tag de la IA distinto del
plano "creature". Las tierras basicas no se cuentan.
"""
from __future__ import annotations

import decks

AI_TAGS = {"engine", "ramp", "draw", "removal", "wipe", "gy_exile"}


def _is_basic(card):
    return "basic" in card.supertypes


def _implemented(card):
    if card.on_etb or card.on_death or card.on_cast_resolve:
        return True
    if card.triggers or card.activated:
        return True
    if card.produces is not None and not _is_basic(card):
        return True
    if card.tags & AI_TAGS:
        return True
    return False


def report(verbose=True):
    rows = []
    for name in decks.DECKS:
        deck, commander = decks.build(name)
        pool = [commander] + deck
        non_basic = [c for c in pool if not _is_basic(c)]
        impl = [c for c in non_basic if _implemented(c)]
        vanilla = [c for c in non_basic if not _implemented(c)]
        rows.append((name, len(impl), len(vanilla)))
    if verbose:
        print("Cobertura de cartas (efecto real implementado)\n")
        for name, impl, van in rows:
            print(f"  {name:10s} efecto implementado {impl:3d} | vainilla {van:3d}")
    return rows


if __name__ == "__main__":
    report()
