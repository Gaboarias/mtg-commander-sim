"""Batch 14 (parte 2): condiciones estáticas nuevas, dioses de Theros, switch P/T,
costes adicionales con X, impuesto por targetear, maná real de tierras y efectos
de "that player" / ruedas / mano rival."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_conditional_keywords_and_buffs():
    g, me, ops = new_game()
    hx = put(g, build("Shy", "{1}{G}", "Creature — Elf",
                      "This creature has hexproof as long as it's untapped.", 2, 2), me)
    assert hx.has("hexproof")
    hx.tapped = True
    assert not hx.has("hexproof")
    tr = put(g, build("Bulky", "{2}{G}", "Creature — Beast",
                      "This creature has trample as long as it has a +1/+1 counter on it.", 3, 3), me)
    assert not tr.has("trample")
    tr.counters["+1/+1"] = 1
    assert tr.has("trample")
    fl = put(g, build("Kite", "{1}{W}", "Creature — Bird",
                      "This creature has flying as long as you control a blue creature.", 1, 1), me)
    assert not fl.has("flying")
    put(g, creature("Merfolk", "1U", 1, 1), me)
    assert fl.has("flying")
    isl = put(g, build("Seer", "{1}{R}", "Creature — Goblin",
                       "This creature gets +2/+0 as long as an opponent controls an Island.", 1, 1), me)
    assert isl.power == 1
    from cards import land
    put(g, land("Island", [U], basic=True), ops[0])
    assert isl.power == 3


def test_conditional_unblockable_and_life_condition():
    g, me, ops = new_game()
    sn = put(g, build("Sneak", "{1}{U}", "Creature — Rogue",
                      "This creature can't be blocked as long as defending player controls an "
                      "artifact.", 2, 1), me)
    assert not sn.has("unblockable")
    put(g, build("Rock", "{1}", "Artifact", ""), ops[0])
    assert sn.has("unblockable")
    ind = put(g, build("Stalwart", "{2}{W}", "Creature — Human",
                       "As long as your life total is less than or equal to half your starting "
                       "life total, this creature has indestructible.", 2, 2), me)
    assert not ind.has("indestructible")
    me.life = 15
    assert ind.has("indestructible")


def test_theros_god_needs_devotion():
    g, me, ops = new_game()
    god = put(g, build("Godly", "{1}{R}{G}", "Legendary Enchantment Creature — God",
                       "Indestructible\nAs long as your devotion to red and green is less than "
                       "seven, Godly isn't a creature.", 6, 5, keywords=["Indestructible"]), me)
    assert not god.is_creature()
    for k in range(3):
        put(g, creature(f"D{k}", "RG", 2, 2), me)
    assert god.is_creature()


def test_switch_power_toughness():
    g, me, ops = new_game()
    wall = put(g, creature("Wall", "1W", 0, 5), ops[0])
    sp = build("About Face", "{R}", "Instant",
               "Switch target creature's power and toughness until end of turn.")
    sp.on_cast_resolve(g, me, [])
    assert wall not in ops[0].battlefield


def test_pay_x_life_additional_cost():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(B,))
    bond = build("Bond", "{X}{B}", "Sorcery", "As an additional cost to cast this spell, pay X "
                 "life.\nEach other player loses X life.")
    bond.x_spell = True
    me.hand.append(bond)
    life, ol = me.life, ops[0].life
    assert g.cast(me, bond)
    run(g)
    assert me.life == life - 3


def test_target_tax_works_as_ward():
    g, me, ops = new_game()
    be = put(g, build("Boreal", "{4}{U}", "Creature — Elemental",
                      "Flying\nSpells your opponents cast that target this creature cost {2} more "
                      "to cast.", 3, 4, keywords=["Flying"]), ops[0])
    assert be.has("ward")
    assert not g.ward_ok(me, be)              # sin maná para pagar el impuesto


def test_sac_land_only_taps_for_fixed_color():
    import cardsdb
    c = cardsdb.build_card_from_data({
        "name": "Outpost", "type_line": "Land", "produced_mana": ["W", "U", "B", "R", "G"],
        "oracle_text": "This land enters tapped.\n{T}: Add {W}.\n{T}, Sacrifice this land: "
                       "Add one mana of any color."})
    assert c.produces(None, None) == {"W": 1}


def test_wheel_and_that_player_effects():
    g, me, ops = new_game()
    me.hand = [creature(f"H{k}", "1G", 1, 1) for k in range(2)]
    ops[0].hand = [creature(f"O{k}", "1B", 1, 1) for k in range(5)]
    wh = build("Wheel", "{2}{R}", "Sorcery",
               "Each player discards their hand, then draws seven cards.")
    wh.on_cast_resolve(g, me, [])
    assert len(me.hand) == 7 and len(ops[0].hand) == 7
    rag = put(g, build("Raider", "{2}{B}", "Creature — Horror",
                       "Whenever this creature deals combat damage to a player, that player "
                       "discards that many cards.", 3, 3), me)
    g.deal_damage(rag, ops[0], 3, combat=True)
    run(g)
    assert len(ops[0].hand) == 4
    ed = put(g, build("Edicter", "{3}{B}", "Creature — Horror",
                      "Whenever this creature deals combat damage to a player, that player "
                      "sacrifices a creature of their choice.", 2, 2), me)
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    g.deal_damage(ed, ops[0], 2, combat=True)
    run(g)
    assert foe not in ops[0].battlefield


def test_opponent_hand_and_tax_edict():
    g, me, ops = new_game()
    ops[0].hand = [creature("Big", "6G", 6, 6), creature("Small", "G", 1, 1)]
    sp = build("Thoughtpick", "{B}", "Sorcery", "Target opponent reveals their hand. You choose "
               "a nonland card from it and exile that card.")
    sp.on_cast_resolve(g, me, [])
    assert [c.name for c in ops[0].hand] == ["Small"]
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    put(g, build("Taxer", "{3}{B}", "Creature — Demon",
                 "When this creature enters, each opponent sacrifices a permanent of their choice "
                 "unless they pay {3}.", 3, 3), me)
    run(g)
    assert foe not in ops[0].battlefield


def test_optional_sacrifice_and_sac_unless():
    g, me, ops = new_game()
    import cards as _c
    tok = put(g, creature("Tok", "0", 1, 1), me)
    tok.is_token = True
    ber = put(g, build("Berserker", "{2}{R}", "Creature — Human",
                       "Whenever this creature attacks, you may sacrifice another creature. If you "
                       "do, this creature gains double strike until end of turn.", 3, 3), me)
    ber.summoning_sick = False
    cb = ber.card.triggers["attacks"]
    g._run_trigger(cb, ber, {"defender": ops[0]})
    assert tok not in me.battlefield and ber.has("double_strike")
    me.hand = [creature("Junk", "1G", 1, 1)]
    hm = put(g, build("Hound", "{1}{B}", "Creature — Dog",
                      "When this creature enters, sacrifice it unless you discard a card.", 4, 4), me)
    run(g)
    assert hm in me.battlefield and not me.hand
    hm2 = put(g, build("Hound2", "{1}{B}", "Creature — Dog",
                       "When this creature enters, sacrifice it unless you discard a card.", 4, 4), me)
    run(g)
    assert hm2 not in me.battlefield


def test_bounce_and_rad_and_dies_to_library():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "4G", 5, 5), ops[0])
    foe.tapped = True
    put(g, build("Bouncer", "{1}{U}", "Creature — Merfolk",
                 "When this creature enters, you may return target tapped creature to its owner's "
                 "hand.", 2, 2), me)
    run(g)
    assert foe not in ops[0].battlefield and any(c.name == "Foe" for c in ops[0].hand)
    from cards import land
    ops[0].library = [land("Forest", [G], basic=True)] + [creature(f"C{k}", "1G", 1, 1) for k in range(3)]
    put(g, build("Glower", "{1}{B}", "Creature — Mutant",
                 "When this creature enters, target player gets 2 rad counters.", 2, 2), me)
    run(g)
    assert ops[0].rad == 2
    life = ops[0].life
    g.begin_turn(ops[0])
    run(g)
    assert ops[0].life <= life - 1
    ph = put(g, build("Phoenixish", "{2}{R}", "Creature — Bird",
                      "When this creature dies, put it on top of its owner's library.", 2, 2), me)
    g.to_graveyard(ph, "test")
    run(g)
    assert me.library[-1].name == "Phoenixish"


def test_reanimate_it_gains_haste_and_sacrificed_at_end():
    g, me, ops = new_game()
    me.graveyard.append(creature("Dead", "4B", 5, 5))
    sp = build("Unearthy", "{2}{B}", "Sorcery", "Return target creature card from your graveyard "
               "to the battlefield. It gains haste until end of turn. Sacrifice it at the "
               "beginning of the next end step.")
    sp.on_cast_resolve(g, me, [])
    pm = next(p for p in me.battlefield if p.name == "Dead")
    assert pm.has("haste")
    g.end_turn(me)
    run(g)
    assert pm not in me.battlefield
