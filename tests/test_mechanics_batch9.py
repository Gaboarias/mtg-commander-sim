"""Batch 9: eventos (sacrificar, scry/surveil, muertes rivales, otras que dejan
el campo), filtro por valor de maná, nombre propio en el cuerpo, Panharmonicon /
Teysa y 'The Ring tempts you'."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_opponent_death_and_own_name_in_body():
    g, me, ops = new_game()
    leg = put(g, build("Legolas, Counter of Kills", "{2}{G}{U}", "Legendary Creature — Elf Archer",
                       "Whenever a creature an opponent controls dies, put a +1/+1 counter on "
                       "Legolas.", 2, 3), me)
    mine = put(g, creature("Mine", "1G", 1, 1), me)
    foe = put(g, creature("Foe", "1B", 1, 1), ops[0])
    g.to_graveyard(mine, "test")
    run(g)
    assert not leg.counters.get("+1/+1")
    g.to_graveyard(foe, "test")
    run(g)
    assert leg.counters.get("+1/+1") == 1


def test_sacrifice_scry_and_leaves_triggers():
    import cardsdb
    g, me, ops = new_game()
    bb = put(g, build("Bloodbriar", "{2}{G}", "Creature — Plant Elemental",
                      "Whenever you sacrifice another permanent, put a +1/+1 counter on this "
                      "creature.", 2, 3), me)
    tok = put(g, creature("Tok", "0", 1, 1), me)
    g.to_graveyard(tok, "coste: sacrificio")
    run(g)
    assert bb.counters.get("+1/+1") == 1
    spy = put(g, build("Spybug", "{2}{U}", "Creature — Insect",
                       "Whenever you scry, put a +1/+1 counter on this creature.", 1, 1), me)
    for _ in range(3):
        me.library.append(land("Forest", [G], basic=True))
    cardsdb._effect_any("Scry 1.")(g, me)
    run(g)
    assert spy.counters.get("+1/+1") == 1
    ff = put(g, build("Fist", "{1}{R}", "Creature — Human",
                      "Whenever another creature you control leaves the battlefield, put a "
                      "+1/+1 counter on this creature.", 2, 2), me)
    other = put(g, creature("Other", "1W", 1, 1), me)
    g.exile_permanent(other, "test")
    run(g)
    assert ff.counters.get("+1/+1") == 1


def test_mana_value_cast_filter():
    g, me, ops = new_game()
    pk = put(g, build("Packleader", "{G}", "Creature — Human",
                      "Whenever you cast a spell with mana value 4 or greater, put a +1/+1 "
                      "counter on this creature.", 2, 2), me)
    give_lands(g, me, 5, colors=(G,))
    small = build("Small", "{G}", "Sorcery", "You gain 1 life.")
    big = build("Big", "{3}{G}", "Sorcery", "You gain 1 life.")
    me.hand += [small, big]
    g.cast(me, small)
    run(g)
    assert not pk.counters.get("+1/+1")
    g.cast(me, big)
    run(g)
    assert pk.counters.get("+1/+1") == 1


def test_panharmonicon_and_teysa():
    g, me, ops = new_game()
    put(g, build("Panharmonicon", "{4}", "Artifact",
                 "If an artifact or creature entering causes a triggered ability of a "
                 "permanent you control to trigger, that ability triggers an additional time."), me)
    life = me.life
    put(g, build("Healer", "{1}{W}", "Creature — Human",
                 "When this creature enters, you gain 2 life.", 1, 1), me)
    assert me.life == life + 4
    put(g, build("Teysa", "{4}", "Legendary Creature — Human",
                 "If a creature dying causes a triggered ability of a permanent you control to "
                 "trigger, that ability triggers an additional time.", 2, 4), me)
    put(g, build("Blood Artist", "{1}{B}", "Creature — Vampire",
                 "Whenever a creature dies, you gain 1 life.", 0, 1), me)
    v = put(g, creature("V", "1B", 1, 1), ops[0])
    life = me.life
    g.to_graveyard(v, "test")
    run(g)
    assert me.life == life + 2


def test_ring_tempts_you():
    import cardsdb
    g, me, ops = new_game()
    bearer = put(g, creature("Frodo", "1W", 2, 2), me)
    cardsdb._effect_any("The Ring tempts you.")(g, me)
    assert me.ring_level == 1 and bearer._ring_bearer
    big = put(g, creature("Big", "3G", 5, 5), ops[0])
    small = put(g, creature("Small", "1G", 1, 1), ops[0])
    assert not g._can_block_evasion(bearer, big)
    assert g._can_block_evasion(bearer, small)
