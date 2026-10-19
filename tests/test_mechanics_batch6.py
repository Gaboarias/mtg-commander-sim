"""Batch 6: werewolves, leylines, exiliar hasta que deje el campo, disparos de
bloqueo, lure, tap N objetivos, y plantillas chicas de mantenimiento/fin de turno."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _werewolf():
    import cardsdb
    return cardsdb.build_card_from_data({
        "name": "Pup // Wolf", "layout": "transform", "type_line": "Creature — Human Werewolf",
        "mana_cost": "{1}{R}", "card_faces": [
            {"name": "Pup", "mana_cost": "{1}{R}", "type_line": "Creature — Human Werewolf",
             "oracle_text": "At the beginning of each upkeep, if no spells were cast last turn, "
                            "transform this creature.", "power": "2", "toughness": "2"},
            {"name": "Wolf", "mana_cost": "", "type_line": "Creature — Werewolf",
             "oracle_text": "At the beginning of each upkeep, if a player cast two or more spells "
                            "last turn, transform this creature.", "power": "4", "toughness": "4"}]})


def test_werewolf_transforms_both_ways():
    g, me, ops = new_game()
    pm = put(g, _werewolf(), me)
    assert not pm.card.activated_abilities          # sin "Transformar" gratis
    g.begin_turn(me)                                # turno sin hechizos previos
    g.begin_turn(ops[0])
    run(g)
    assert pm.name == "Wolf"
    ops[0].spells_cast_turn = 2
    g.begin_turn(me)
    run(g)
    assert pm.name.startswith("Pup")


def test_leyline_starts_on_battlefield():
    g, me, ops = new_game()
    ley = build("Leyline of Tests", "{2}{G}{G}", "Enchantment",
                "If this card is in your opening hand, you may begin the game with it on the "
                "battlefield.\nCreatures you control get +1/+1.")
    me.hand.append(ley)
    g.begin_turn(me)
    assert any(pm.name == "Leyline of Tests" for pm in me.battlefield) and ley not in me.hand


def test_banishing_light_and_faceless_butcher():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "2B", 4, 4), ops[0])
    bl = put(g, build("Banishing Light", "{2}{W}", "Enchantment",
                      "When this enchantment enters, exile target nonland permanent an opponent "
                      "controls until this enchantment leaves the battlefield."), me)
    assert foe not in ops[0].battlefield
    g.to_graveyard(bl, "test")
    run(g)
    assert any(pm.name == "Foe" for pm in ops[0].battlefield)
    fb = put(g, build("Faceless Butcher", "{2}{B}{B}", "Creature — Nightmare Horror",
                      "When this creature enters, exile another target creature.\nWhen this "
                      "creature leaves the battlefield, return the exiled card to the "
                      "battlefield under its owner's control.", 2, 3), me)
    assert not any(pm.name == "Foe" for pm in ops[0].battlefield)
    g.to_graveyard(fb, "test")
    run(g)
    assert any(pm.name == "Foe" for pm in ops[0].battlefield)


def test_block_triggers_and_sacrifice_when_targeted():
    g, me, ops = new_game()
    atk = put(g, build("Rager", "{2}{R}", "Creature — Beast",
                       "Whenever this creature becomes blocked, it gets +2/+2 until end of turn.",
                       2, 2), me)
    blk = put(g, creature("Wall", "1W", 0, 3), ops[0])
    atk.summoning_sick = False
    atk.attacking = ops[0]
    g._apply_block_pairs([atk], [(atk, blk)])
    g._combat_block_triggers([atk])
    assert atk.power == 4
    fw = put(g, build("Frost Walker", "{1}{U}", "Creature — Elemental",
                      "When this creature becomes the target of a spell or ability, sacrifice it.",
                      4, 1), ops[0])
    g._targeted_triggers(me, [fw], spell=True)
    assert fw not in ops[0].battlefield


def test_lure_forces_blocks():
    g, me, ops = new_game()
    lure = put(g, build("Breaker", "{4}{G}", "Creature — Beast",
                        "All creatures able to block this creature do so.", 8, 8), me)
    b1 = put(g, creature("B1", "1W", 1, 1), ops[0])
    b2 = put(g, creature("B2", "1W", 1, 1), ops[0])
    lure.attacking = ops[0]
    g._after_blocks([lure])
    assert set(lure.blocked_by) == {b1, b2}


def test_tap_up_to_two_and_frozen():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U,))
    a = put(g, creature("A", "1B", 2, 2), ops[0])
    b = put(g, creature("B", "1B", 2, 2), ops[0])
    sp = build("Grasp", "{2}{U}", "Instant", "Tap up to two target creatures. Those creatures "
               "don't untap during their controller's next untap step.")
    assert sp.target_count == 2
    sp.on_cast_resolve(g, me, [a, b])
    assert a.tapped and b.tapped
    g.begin_turn(ops[0])
    assert a.tapped and b.tapped


def test_small_templates():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U,))
    # sacrificio salvo que pagues
    dr = put(g, build("Drifter", "{U}", "Creature — Spirit",
                      "At the beginning of your upkeep, sacrifice this creature unless you pay "
                      "{U}{U}.", 2, 1), me)
    g.emit("upkeep", player=me)
    run(g)
    assert dr in me.battlefield
    # +1/+1 por cada artefacto
    syn = put(g, build("Synergist", "{1}{W}", "Artifact Creature — Construct",
                       "This creature gets +1/+1 for each artifact you control.", 1, 1), me)
    put(g, build("Trinket", "{1}", "Artifact", ""), me)
    assert syn.power == 3
    # sin Islas se sacrifica
    dd = put(g, build("Dandan", "{U}{U}", "Creature — Fish",
                      "When you control no Islands, sacrifice this creature.", 4, 1), me)
    run(g)
    assert dd not in me.battlefield
    # debuff dirigido al entrar
    foe = put(g, creature("Foe", "1B", 2, 2), ops[0])
    put(g, build("Gigapede", "{4}{B}", "Creature — Insect",
                 "When this creature enters, target creature an opponent controls gets -2/-2 "
                 "until end of turn.", 6, 1), me)
    assert foe not in ops[0].battlefield
    # top of library
    foe2 = put(g, creature("Foe2", "1B", 3, 3), ops[0])
    top = build("Excommunicate", "{2}{W}", "Sorcery", "Put target creature on top of its owner's "
                "library.")
    top.on_cast_resolve(g, me, [foe2])
    assert ops[0].library[-1].name == "Foe2"
    # vuelve a la mano al morir
    roach = put(g, build("Roach", "{1}{B}{B}", "Creature — Insect",
                         "When this creature dies, return it to its owner's hand.", 1, 1), me)
    g.to_graveyard(roach, "test")
    run(g)
    assert any(c.name == "Roach" for c in me.hand)
