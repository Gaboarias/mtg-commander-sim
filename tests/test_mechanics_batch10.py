"""Batch 10: acciones sobre la propia carta o el sujeto del disparo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_self_bounce_sacrifice_and_that_player_damage():
    g, me, ops = new_game()
    sp = put(g, build("Spirit", "{1}{U}", "Creature — Spirit",
                      "Whenever this creature deals combat damage to a player, return this creature "
                      "to its owner's hand.", 2, 2), me)
    g.emit("upkeep", player=me)
    assert sp in me.battlefield
    cb = sp.card.triggers.get("combat_damage_to_player")
    assert cb is not None
    cb(g, sp)
    assert sp not in me.battlefield and any(c.name == "Spirit" for c in me.hand)
    ob = put(g, build("Pinger", "{2}{R}", "Creature — Devil",
                      "Whenever an opponent casts a spell, this creature deals 1 damage to that "
                      "player.", 2, 2), me)
    life = ops[0].life
    give_lands(g, ops[0], 1, colors=(B,), name="Swamp")
    sp2 = build("Thing", "{B}", "Sorcery", "You gain 1 life.")
    ops[0].hand.append(sp2)
    g.cast(ops[0], sp2)
    run(g)
    assert ops[0].life == life - 1 + 1


def test_destroy_blocker_subject():
    g, me, ops = new_game()
    bas = put(g, build("Basilisk", "{2}{G}", "Creature — Basilisk",
                       "Whenever this creature blocks or becomes blocked by a creature, destroy "
                       "that creature.", 1, 3), me)
    foe = put(g, creature("Foe", "2B", 4, 4), ops[0])
    bas.attacking = ops[0]
    g._apply_block_pairs([bas], [(bas, foe)])
    g._combat_block_triggers([bas])
    run(g)
    assert foe not in ops[0].battlefield
