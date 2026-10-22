"""Batch 18: Clue/Food/Blood con habilidades reales, habilidades otorgadas por auras y
equipos, Etali, Sunbird's Invocation, Master Biomancer/Grumgully, Meren, Meteor Blast,
Hydra Omnivore, Wave Goodbye, Wash Out, Academy Manufactor, Temple of the False God."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
import cards  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_clue_food_tokens_have_abilities():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(G,))
    me.library += [creature(f"X{k}", "1G", 1, 1) for k in range(3)]
    cl = cards.make_resource_token(g, me, "clue")
    h = len(me.hand)
    assert g.activate_ability(cl, 0)
    run(g)
    assert len(me.hand) == h + 1 and cl not in me.battlefield
    fd = cards.make_resource_token(g, me, "food")
    life = me.life
    assert g.activate_ability(fd, 0)
    run(g)
    assert me.life == life + 3


def test_academy_manufactor_and_temple():
    g, me, ops = new_game()
    put(g, build("Manufactor", "{3}", "Artifact Creature — Assembly-Worker", "If you would create a Clue, "
                 "Food, or Treasure token, instead create one of each.", 1, 3), me)
    cards.make_resource_token(g, me, "treasure")
    names = sorted(pm.name for pm in me.battlefield if pm.is_token)
    assert names == ["Clue", "Food", "Treasure"]
    import cardsdb
    temple = cardsdb.build_card_from_data({"name": "Temple of the False God", "type_line": "Land",
                                           "produced_mana": ["C"], "oracle_text": "{T}: Add {C}{C}. Activate only "
                                           "if you control five or more lands."})
    g2, p2, _ = new_game()
    tp = put(g2, temple, p2)
    assert tp not in p2.mana_sources()
    give_lands(g2, p2, 4, colors=(G,))
    assert tp in p2.mana_sources() and p2.produced(tp) == {"C": 2}


def test_granted_ability_from_aura_and_biomancer():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    au = put(g, build("Gond", "{2}{G}", "Enchantment — Aura", "Enchant creature\nEnchanted creature has "
                      "\"{T}: Create a 1/1 green Elf Warrior creature token.\""), me)
    assert au.enchanting is bear
    bear.summoning_sick = False
    idx = len(bear.card.activated_abilities) - 1
    assert g.activate_ability(bear, idx)
    run(g)
    assert any(pm.is_token for pm in me.battlefield)
    g.to_graveyard(au, "test")
    assert not g.ability_allowed(bear, idx, bear.card.activated_abilities[idx])
    put(g, build("Biomancer", "{2}{G}{U}", "Creature — Elf Wizard", "Each other creature you control enters with "
                 "a number of additional +1/+1 counters on it equal to this creature's power and as a Mutant in "
                 "addition to its other types.", 2, 4), me)
    nb = put(g, creature("New", "1G", 1, 1), me)
    assert nb.counters.get("+1/+1") == 2


def test_meteor_wave_washout_meren():
    g, me, ops = new_game()
    for k in range(2):
        put(g, creature(f"O{k}", "1G", 2, 2), ops[0])
    g.spell_x = 3
    mb = build("Meteor Blast", "{X}{R}{R}{R}", "Sorcery", "Meteor Blast deals 4 damage to each of X targets.")
    ol = ops[0].life
    mb.on_cast_resolve(g, me, [])
    run(g)
    assert not ops[0].creatures() and ops[0].life == ol - 4
    put(g, creature("Mine", "1W", 2, 2), me)
    put(g, creature("TheirsW", "1W", 2, 2), ops[0])
    put(g, creature("TheirsW2", "1W", 2, 2), ops[0])
    wo = build("Wash Out", "{3}{U}", "Sorcery", "Return all permanents of the color of your choice to their "
               "owners' hands.")
    wo.on_cast_resolve(g, me, [])
    assert not ops[0].creatures()
    me.graveyard.append(creature("Cheap", "1B", 2, 2))
    me.experience = 3
    put(g, build("Meren", "{2}{B}{G}", "Legendary Creature — Human Shaman", "At the beginning of your end step, "
                 "choose target creature card in your graveyard. If that card's mana value is less than or equal "
                 "to the number of experience counters you have, return it to the battlefield. Otherwise, put it "
                 "into your hand.", 3, 4), me)
    g.end_turn(me)
    run(g)
    assert any(pm.name == "Cheap" for pm in me.battlefield)
