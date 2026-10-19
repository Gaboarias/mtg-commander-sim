"""Batch 8: disparos por color/histórico, cementerio de encantamientos/artefactos,
habilidades desde la mano (Channel), goad masivo y efectos simples frecuentes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_color_and_historic_cast_triggers():
    g, me, ops = new_game()
    put(g, build("Watcher", "{1}{U}", "Creature — Human", "Whenever you cast a blue spell, "
                 "you gain 2 life.", 1, 1), me)
    give_lands(g, me, 2, colors=(U,))
    life = me.life
    sp = build("Blue Thing", "{U}", "Instant", "Draw a card.")
    me.hand.append(sp)
    assert g.cast(me, sp)
    run(g)
    assert me.life == life + 2
    red = build("Red Thing", "{R}", "Instant", "Draw a card.")
    give_lands(g, me, 1, colors=(R,), name="Mountain")
    me.hand.append(red)
    assert g.cast(me, red)
    run(g)
    assert me.life == life + 2


def test_enchantment_to_graveyard_trigger():
    g, me, ops = new_game()
    en = put(g, build("Omen", "{1}{U}", "Enchantment",
                      "When this enchantment is put into a graveyard from the battlefield, "
                      "you gain 3 life."), me)
    life = me.life
    g.to_graveyard(en, "test")
    run(g)
    assert me.life == life + 3


def test_channel_hand_ability():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(G,))
    ch = build("Channeler", "{5}{G}{G}", "Creature — Spirit",
               "{1}{G}, Discard this card: Create a Treasure token.", 7, 7)
    assert not ch.activated_abilities and ch.hand_abilities
    me.hand.append(ch)
    assert g.activate_from_hand(me, ch, 0)
    run(g)
    assert ch in me.graveyard and any(pm.name == "Treasure" for pm in me.battlefield)


def test_goad_all_and_simple_atomics():
    import cardsdb
    g, me, ops = new_game()
    a = put(g, creature("A", "1B", 2, 2), ops[0])
    cardsdb._effect_any("Goad all creatures your opponents control.")(g, me)
    assert a.goaded
    life_me, life_op = me.life, ops[0].life
    cardsdb._effect_any("Each player loses 2 life.")(g, me)
    assert me.life == life_me - 2 and ops[0].life == life_op - 2
    eg = put(g, build("Herald", "{2}{W}", "Creature — Human", "When this creature enters, "
                      "you gain 2 life.", 2, 2), me)
    rogue = put(g, build("Keymaster", "{5}{U}", "Creature — Rogue",
                         "When this creature enters, return a creature you control to its "
                         "owner's hand.", 4, 3), me)
    assert any(c.name == "Herald" for c in me.hand) or any(c.name == "Keymaster" for c in me.hand)
    end = put(g, build("Earthcarver", "{5}{G}", "Creature — Beast",
                       "When this creature enters, it endures 3.", 4, 4), me)
    assert end.counters.get("+1/+1") == 3
    put(g, build("Opp", "{3}", "Artifact Creature — Golem",
                 "When this creature enters, create a tapped Powerstone token.", 2, 2), me)
    ps = [pm for pm in me.battlefield if pm.name == "Powerstone"]
    assert ps and ps[0].tapped
    ops[0].graveyard += [creature("D1", "1B", 1, 1), creature("D2", "1B", 1, 1)]
    cardsdb._effect_any("Exile up to two target cards from a single graveyard.")(g, me)
    assert not ops[0].graveyard
