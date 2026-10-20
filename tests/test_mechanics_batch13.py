"""Batch 13: Ghostly Prison, Doran, Platinum Angel, anthems por color,
'can't attack alone', 'damage can't be prevented' y tierras fuera de la mano."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_ghostly_prison_tax():
    g, me, ops = new_game()
    put(g, build("Ghostly Prison", "{2}{W}", "Enchantment", "Creatures can't attack you unless "
                 "their controller pays {2} for each creature they control that's attacking you."),
        ops[0])
    a = put(g, creature("A", "1G", 2, 2), me)
    b = put(g, creature("B", "1G", 2, 2), me)
    a.summoning_sick = b.summoning_sick = False
    give_lands(g, me, 2, colors=(G,))
    declared = g._declare_attackers(me, [(a, ops[0]), (b, ops[0])])
    assert len(declared) == 1


def test_doran_and_platinum_angel():
    g, me, ops = new_game()
    put(g, build("Doran", "{W}{B}{G}", "Legendary Creature — Treefolk", "Each creature assigns "
                 "combat damage equal to its toughness rather than its power.", 0, 5), me)
    wall = put(g, creature("Wall", "1W", 0, 6), me)
    assert g.combat_power(wall) == 6
    put(g, build("Platinum Angel", "{7}", "Artifact Creature — Angel", "Flying\nYou can't lose the "
                 "game and your opponents can't win the game.", 4, 4), me)
    me.life = -5
    g.sba()
    assert not me.lost


def test_color_anthem_and_not_alone():
    g, me, ops = new_game()
    put(g, build("Crusade", "{W}{W}", "Enchantment", "White creatures get +1/+1."), me)
    wk = put(g, build("Knight", "{1}{W}", "Creature — Human", "", 2, 2), ops[0])
    gr = put(g, creature("Bear", "1G", 2, 2), me)
    assert wk.power == 3 and gr.power == 2
    bc = put(g, build("Bonded", "{2}", "Artifact Creature — Construct",
                      "This creature can't attack alone.", 3, 1), me)
    bc.summoning_sick = False
    assert g._declare_attackers(me, [(bc, ops[0])]) == []


def test_crucible_land_from_graveyard_and_ui():
    import interactive
    g, me, ops = new_game()
    put(g, build("Crucible", "{3}", "Artifact", "You may play lands from your graveyard."), me)
    f = land("Forest", [G], basic=True)
    me.graveyard.append(f)
    me.hand = []
    me.policy._play_land(g, me)
    assert f not in me.graveyard and any(pm.card is f for pm in me.battlefield)
