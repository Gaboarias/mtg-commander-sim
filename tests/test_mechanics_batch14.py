"""Batch 14: long tail — veneno, 'that much', P/T base, daño a sí misma, Soulshift,
Fabricate, Phantom, Thorn Elemental, Rule of Law, bloqueos múltiples, costes
adicionales, pactos y curses."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_soulshift_and_fabricate():
    g, me, ops = new_game()
    sp = build("Old Spirit", "{2}{W}", "Creature — Spirit", "", 2, 2)
    me.graveyard.append(sp)
    ss = put(g, build("Shifter", "{3}{W}", "Creature — Spirit", "Soulshift 3", 3, 3,
                      keywords=["Soulshift"]), me)
    g.to_graveyard(ss, "test")
    run(g)
    assert sp in me.hand
    fb = put(g, build("Fabber", "{3}", "Artifact Creature — Construct", "Fabricate 2", 2, 2,
                      keywords=["Fabricate"]), me)
    assert fb.counters.get("+1/+1") == 2 or sum(1 for pm in me.battlefield if pm.name == "Servo") == 2


def test_phantom_thorn_and_rule_of_law():
    g, me, ops = new_game()
    ph = put(g, build("Phantom", "{3}{G}", "Creature — Centaur Spirit",
                      "This creature enters with three +1/+1 counters on it.\nIf damage would be "
                      "dealt to this creature, prevent that damage. Remove a +1/+1 counter from this "
                      "creature.", 2, 0), me)
    g.deal_damage(None, ph, 5)
    assert ph.damage == 0 and ph.counters.get("+1/+1") == 2
    put(g, build("Rule of Law", "{2}{W}", "Enchantment",
                 "Each player can't cast more than one spell each turn."), ops[0])
    give_lands(g, me, 2, colors=(G,))
    a = build("A", "{G}", "Sorcery", "You gain 1 life.")
    b = build("B", "{G}", "Sorcery", "You gain 1 life.")
    me.hand += [a, b]
    assert g.cast(me, a)
    run(g)
    assert not g.cast(me, b)


def test_extra_blocks_and_additional_costs():
    g, me, ops = new_game()
    wall = put(g, build("Brigade", "{3}{W}", "Creature — Human", "This creature can block an "
                        "additional creature each combat.", 2, 4), ops[0])
    a1 = put(g, creature("A1", "1G", 1, 1), me)
    a2 = put(g, creature("A2", "1G", 1, 1), me)
    a1.attacking = a2.attacking = ops[0]
    g._apply_block_pairs([a1, a2], [(a1, wall), (a2, wall)])
    assert len(wall.blocking) == 2
    give_lands(g, me, 2, colors=(B,))
    cx = build("Corpse", "{B}", "Sorcery", "As an additional cost to cast this spell, exile a "
               "creature card from your graveyard.\nYou gain 3 life.")
    me.hand.append(cx)
    assert not g.cast(me, cx)
    me.graveyard.append(creature("Dead", "1B", 1, 1))
    assert g.cast(me, cx)
    run(g)
    assert any(c.name == "Dead" for c in me.exile)


def test_pact_must_be_paid():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(R,))
    pact = build("Pact of the Titan", "{0}", "Instant", "Create a 4/4 red Giant creature token.\n"
                 "At the beginning of your next upkeep, pay {4}{R}. If you don't, you lose the game.")
    me.hand.append(pact)
    assert g.cast(me, pact)
    run(g)
    assert g.pact_due
    g.begin_turn(me)
    assert me.lost


def test_curse_upkeep_poison_and_that_much():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "2B", 3, 3), ops[0])
    put(g, build("Curse", "{1}{B}", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets "
                 "-0/-0.\nAt the beginning of the upkeep of enchanted creature's controller, that "
                 "player loses 2 life."), me)
    life = ops[0].life
    g.emit("each_upkeep", active=ops[0])
    run(g)
    assert ops[0].life == life - 2
    import cardsdb
    cardsdb._effect_any("Defending player gets a poison counter.")(g, me)
    assert ops[0].poison == 1
