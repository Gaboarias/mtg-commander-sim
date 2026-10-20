"""Batch 12: ramp de tierras (Wild Growth, Mana Reflection, Heartbeat), Spirit or
Arcane, auras con contadores / lifelink / False Demise y efectos 'that much'."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W, parse_cost  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_land_auras_and_mana_doublers():
    g, me, ops = new_game()
    f = put(g, land("Forest", [G], basic=True), me)
    put(g, build("Wild Growth", "{G}", "Enchantment — Aura", "Enchant land\nWhenever enchanted "
                 "land is tapped for mana, its controller adds an additional {G}."), me)
    assert me.produced(f) == {"G": 2}
    assert me.can_pay(parse_cost("1G")) and not me.can_pay(parse_cost("2G"))
    put(g, build("Heartbeat", "{2}{G}{G}", "Enchantment", "Whenever a player taps a land for mana, "
                 "that player adds one mana of any type that land produced."), ops[0])
    assert me.produced(f) == {"G": 3}


def test_spirit_or_arcane_trigger():
    g, me, ops = new_game()
    baku = put(g, build("Baku", "{2}", "Creature — Spirit", "Whenever you cast a Spirit or Arcane "
                        "spell, you may put a ki counter on this creature.", 1, 1), me)
    give_lands(g, me, 2, colors=(U,))
    arc = build("Arcane Thing", "{U}", "Instant — Arcane", "Draw a card.")
    me.hand.append(arc)
    assert g.cast(me, arc)
    run(g)
    assert baku.counters.get("ki") == 1


def test_aura_counters_lifelink_and_false_demise():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, build("Tether", "{1}{G}", "Enchantment — Aura", "Enchant creature\nAt the beginning of "
                 "your upkeep, put a +1/+1 counter on enchanted creature."), me)
    g.emit("upkeep", player=me)
    run(g)
    assert bear.counters.get("+1/+1") == 1
    foe = put(g, creature("Foe", "2B", 3, 3), ops[0])
    put(g, build("False Demise", "{2}{U}", "Enchantment — Aura", "Enchant creature\nWhen enchanted "
                 "creature dies, return that card to the battlefield under your control."), me)
    # se anexa a la mejor propia (Bear): que muera y vuelva bajo mi control
    g.to_graveyard(bear, "test")
    run(g)
    assert any(pm.name == "Bear" for pm in me.battlefield)


def test_that_much_and_discard_hand():
    g, me, ops = new_game()
    put(g, build("Sanguine", "{2}{B}", "Enchantment", "Whenever you gain life, target opponent "
                 "loses that much life."), me)
    life = ops[0].life
    g.gain_life(me, 3)
    run(g)
    assert ops[0].life == life - 3
    put(g, build("Nihil", "{1}{B}", "Enchantment", "Whenever an opponent discards a card, that "
                 "player loses 2 life."), me)
    life = ops[0].life
    g.discard_card(ops[0], creature("X", "1", 1, 1))
    run(g)
    assert ops[0].life == life - 2
