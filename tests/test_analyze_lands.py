"""Análisis de mazo: conteo de tierras (cara frontal) y mazos de tamaño inválido."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

import _analyze  # noqa: E402


def _land(n):
    return (1, n, {"name": n, "type_line": "Land", "cmc": 0, "oracle_text": "{T}: Add {G}."})


def test_back_face_land_is_not_a_land():
    dfc = (1, "Legion's Landing", {"name": "Legion's Landing", "cmc": 1, "mana_cost": "{W}",
                                   "type_line": "Legendary Enchantment // Legendary Land", "oracle_text": ""})
    mdfc = (1, "Valakut Awakening", {"name": "Valakut Awakening", "cmc": 3, "mana_cost": "{2}{R}",
                                     "type_line": "Instant // Land", "oracle_text": ""})
    r = _analyze.analyze([_land(f"L{k}") for k in range(36)] + [dfc, mdfc], None)
    assert r["counts"]["land"] == 36


def test_inflated_list_reports_size_not_flood():
    r = _analyze.analyze([_land(f"L{k}") for k in range(123)], None)
    assert any("123 cartas" in w for w in r["weaknesses"])
    assert not any("Demasiadas tierras" in w for w in r["weaknesses"])
