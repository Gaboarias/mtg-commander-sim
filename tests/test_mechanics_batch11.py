"""Batch 11: 'when you cast this spell', titanes Eldrazi, y eventos nuevos
(you attack, each combat, first main phase, discard/cycle, crime, any cast,
enchanted creature dies, combat damage to a creature)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _gain(head, tl="Creature — Human", **kw):
    return build("Watcher", "{1}{W}", tl, head + ", you gain 2 life.", 1, 1, **kw)


def test_cast_trigger_resolves_before_spell():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(G,))
    k = build("Titan", "{3}", "Creature — Eldrazi",
              "When you cast this spell, draw two cards.", 5, 5)
    for _ in range(3):
        me.library.append(land("Forest", [G], basic=True))
    me.hand.append(k)
    h = len(me.hand)
    assert g.cast(me, k)
    run(g)
    assert len(me.hand) == h - 1 + 2


def test_kozilek_shuffles_graveyard():
    g, me, ops = new_game()
    koz = build("Kozilek", "{10}", "Legendary Creature — Eldrazi",
                "When Kozilek is put into a graveyard from anywhere, its owner shuffles their "
                "graveyard into their library.", 12, 12)
    me.graveyard += [koz, creature("Junk", "1G", 1, 1)]
    g.sba()
    assert not me.graveyard and koz in me.library


def test_you_attack_and_each_combat():
    g, me, ops = new_game()
    put(g, _gain("Whenever you attack"), me)
    a = put(g, creature("A", "1G", 2, 2), me)
    a.summoning_sick = False
    life = me.life
    g._declare_attackers(me, [(a, ops[0])])
    run(g)
    assert me.life == life + 2
    put(g, _gain("At the beginning of each combat"), ops[0])
    life_op = ops[0].life
    g._begin_combat(me)
    assert ops[0].life == life_op + 2


def test_discard_cycle_main1_crime_anycast():
    g, me, ops = new_game()
    put(g, _gain("Whenever you discard a card"), me)
    c = creature("C", "1G", 1, 1)
    life = me.life
    g.discard_card(me, c)
    run(g)
    assert me.life == life + 2
    cy = build("Cycler", "{3}", "Creature — Beast", "When you cycle this card, you gain 3 life.\n"
               "Cycling {1}", 3, 3, keywords=["Cycling"])
    give_lands(g, me, 1, colors=(G,))
    me.hand.append(cy)
    life = me.life
    assert g.cycle_card(me, cy)
    assert me.life >= life + 3
    put(g, _gain("At the beginning of your first main phase"), ops[0])
    life_op = ops[0].life
    g.begin_turn(ops[0])
    assert ops[0].life == life_op + 2
    put(g, _gain("Whenever you commit a crime"), me)
    foe = put(g, creature("Foe", "1B", 2, 2), ops[0])
    life = me.life
    g._targeted_triggers(me, [foe], spell=True)
    run(g)
    assert me.life == life + 2


def test_enchanted_dies_and_combat_damage_to_creature():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, build("Gift", "{1}{W}", "Enchantment — Aura",
                 "Enchant creature\nEnchanted creature gets +1/+1.\nWhen enchanted creature dies, "
                 "you gain 4 life."), me)
    life = me.life
    g.to_graveyard(bear, "test")
    run(g)
    assert me.life == life + 4
    hunter = put(g, build("Hunter", "{2}{G}", "Creature — Beast",
                          "Whenever this creature deals combat damage to a creature, you gain 2 "
                          "life.", 3, 3), me)
    foe = put(g, creature("Foe", "1B", 1, 1), ops[0])
    life = me.life
    g.deal_damage(hunter, foe, 3, combat=True)
    run(g)
    assert me.life == life + 2
