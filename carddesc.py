"""Descripción legible de las habilidades de una carta, derivada de su
estructura (no hay oracle text en las cartas caseras). Puro y sin dependencias
del motor: recibe una Card por duck-typing.

Para las cartas reales, la web completa/reemplaza esto con el texto de Scryfall.
"""
from __future__ import annotations

KW_ES = {
    "flying": "Vuela", "vigilance": "Vigilancia", "trample": "Arrolla",
    "haste": "Prisa", "deathtouch": "Toque mortal", "lifelink": "Vínculo vital",
    "menace": "Amenaza", "first_strike": "Daña primero", "double_strike": "Daño doble",
    "hexproof": "Antimaleficio", "indestructible": "Indestructible",
    "defender": "Defensor", "reach": "Alcance",
}

_TRIG_ES = {
    "attacks": "Al atacar, hace su efecto.",
    "death": "Cuando muere, hace su efecto.",
    "upkeep": "En tu mantenimiento, hace su efecto.",
    "cast": "Cuando lanzás un hechizo, hace su efecto.",
    "draw": "Al robar una carta, puede hacer su efecto.",
    "leaves_graveyard": "Cuando una carta deja tu cementerio, hace su efecto.",
    "begin_combat": "Al empezar el combate, hace su efecto.",
    "landfall": "Cuando entra una tierra, hace su efecto.",
    "end_step": "Al final del turno, hace su efecto.",
}

_TARGET_ES = {
    "opp_creature": " (objetivo: una criatura rival)",
    "stack_spell": " (objetivo: un hechizo en la pila)",
}


def keyword_labels(card):
    return [KW_ES.get(k, k.capitalize()) for k in sorted(getattr(card, "keywords", ()) or ())]


def describe(card):
    """Lista de habilidades legibles (español)."""
    out = list(keyword_labels(card))
    for cost, _eff in (getattr(card, "loyalty_abilities", ()) or ()):
        out.append(f"Lealtad {cost:+d}: habilidad de planeswalker.")
    for ev in (getattr(card, "triggers", {}) or {}):
        out.append(_TRIG_ES.get(ev, f"Disparo ({ev}), hace su efecto."))
    if getattr(card, "on_etb", None):
        out.append("Al entrar al campo, hace su efecto.")
    if getattr(card, "on_death", None):
        out.append("Cuando muere, hace su efecto.")
    if getattr(card, "on_cast_resolve", None):
        ts = getattr(card, "target_spec", None)
        out.append("Al resolverse, hace su efecto" + _TARGET_ES.get(ts, "") + ".")
    if getattr(card, "static_mod", None):
        out.append("Da un bono continuo a tus criaturas (anthem).")
    if getattr(card, "counter_modifier", None):
        out.append("Modifica los contadores +1/+1 que pondrías.")
    if getattr(card, "produces", None) and not card.is_land():
        out.append("Produce maná.")
    seen, res = set(), []
    for a in out:
        if a not in seen:
            seen.add(a)
            res.append(a)
    return res
