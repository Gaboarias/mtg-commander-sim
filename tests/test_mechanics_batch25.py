"""Batch 25: efectos de reemplazo (cementerio→exilio, daño triple/+N, daño→contadores,
redirección, turnos extra salteados, ganar→perder vida, Tesoro extra), lanzar
instantáneos/conjuros del cementerio, costes adicionales opcionales (teamwork, blight,
collect evidence, waterbend), fuse, equipar legendaria, Chancellors, búsqueda en
biblioteca y/o cementerio, prisa para habilidades y Torpor Orb."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land, make_resource_token  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _bolt():
    return build("Bolt", "{R}", "Instant", "Bolt deals 3 damage to any target.")


def test_graveyard_replacement_and_triple_damage():
    g, me, ops = new_game()
    put(g, build("RIP", "{1}{W}", "Enchantment", "If a card or token would be put into a graveyard from anywhere, "
                 "exile it instead."), me)
    x = put(g, creature("X", "1G", 2, 2), ops[0])
    g.to_graveyard(x, "test")
    assert not ops[0].graveyard and any(c.name == "X" for c in ops[0].exile)
    g, me, ops = new_game()
    put(g, build("Fiery", "{3}{R}{R}{R}", "Enchantment", "If a source you control would deal damage to a permanent "
                 "or player, it deals triple that damage instead."), me)
    s = put(g, creature("S", "1R", 1, 1), me)
    life = ops[0].life
    g.deal_damage(s, ops[0], 2)
    assert life - ops[0].life == 6


def test_damage_to_counters_and_small_damage_immunity():
    g, me, ops = new_game()
    h = put(g, build("Hydra", "{4}{G}", "Creature — Hydra", "If a creature would deal combat damage to this creature, "
                     "prevent that damage and put a +1/+1 counter on this creature.", 4, 4), me)
    o = put(g, creature("O", "2R", 5, 5), ops[0])
    g.deal_damage(o, h, 5, combat=True)
    run(g)
    assert h in me.battlefield and h.counters.get("+1/+1") == 1 and h.damage == 0
    cg = put(g, build("Giant", "{4}{R}", "Creature — Giant", "If a source would deal 3 or less damage to this "
                      "creature, prevent that damage.", 6, 6), me)
    g.deal_damage(o, cg, 3)
    assert cg.damage == 0
    g.deal_damage(o, cg, 4)
    assert cg.damage == 4


def test_cast_spell_from_graveyard_free_and_paid():
    g, me, ops = new_game()
    me.graveyard = [_bolt()]
    life = ops[0].life
    put(g, build("Gearhulk", "{4}{U}{U}", "Artifact Creature — Construct", "When this creature enters, you may cast "
                 "target instant card from your graveyard without paying its mana cost. If that spell would be put "
                 "into your graveyard, exile it instead.", 5, 6), me)
    run(g)
    assert life - ops[0].life == 3 and any(c.name == "Bolt" for c in me.exile)
    g, me, ops = new_game()
    me.graveyard = [_bolt()]
    e = __import__("cardsdb")._effect_any("you may cast target instant card from your graveyard. if that spell "
                                          "would be put into a graveyard, exile it instead.")
    life = ops[0].life
    e(g, me)                                           # sin maná: no se lanza
    run(g)
    assert ops[0].life == life and me.graveyard
    give_lands(g, me, 1, colors=(R,))
    e(g, me)
    run(g)
    assert life - ops[0].life == 3 and not me.graveyard


def test_damage_plus_redirect_and_unpreventable():
    g, me, ops = new_game()
    put(g, build("Torb", "{1}{R}{R}{R}", "Legendary Creature — Dwarf", "If a source you control would deal damage to "
                 "an opponent or a permanent an opponent controls, it deals that much damage plus 2 instead.", 2, 4), me)
    x = put(g, creature("X", "1R", 2, 2), me)
    life = ops[0].life
    g.deal_damage(x, ops[0], 2)
    assert life - ops[0].life == 4
    ml = me.life
    g.deal_damage(x, me, 1)
    assert ml - me.life == 1
    wall = put(g, build("Glacial", "{2}{W}", "Creature — Wall", "All damage that would be dealt to you is dealt to "
                        "this creature instead.", 0, 8), ops[0])
    life = ops[0].life
    g.deal_damage(x, ops[0], 1)
    assert ops[0].life == life and wall.damage == 3
    bl = put(g, build("Bl", "{1}{W}", "Creature — Wall", "Prevent all damage that would be dealt to this creature by "
                      "creatures it's blocking.", 0, 3), me)
    a = put(g, creature("A", "3G", 5, 5), ops[0])
    bl.blocking = [a]
    g.deal_damage(a, bl, 5, combat=True)
    assert bl.damage == 0 and bl in me.battlefield


def test_extra_turn_skip_remedy_treasure_plus_discard_to_battlefield():
    g, me, ops = new_game()
    put(g, build("Stranglehold", "{3}{R}", "Enchantment", "If an opponent would begin an extra turn, that player "
                 "skips that turn instead."), me)
    assert next(pm for pm in me.battlefield if pm.name == "Stranglehold").card.skip_extra_turns == "opp"
    put(g, build("Remedy", "{2}{B}", "Enchantment", "If an opponent would gain life, that player loses that much "
                 "life instead."), me)
    life = ops[0].life
    g.gain_life(ops[0], 3)
    assert life - ops[0].life == 3
    put(g, build("Goldspan", "{1}{R}", "Enchantment", "If you would create one or more Treasure tokens, instead create "
                 "those tokens plus an additional Treasure token."), me)
    n = len(me.battlefield)
    make_resource_token(g, me, "treasure")
    assert len(me.battlefield) - n == 2
    bal = build("Baloth", "{2}{G}{G}", "Creature — Beast", "If a spell or ability an opponent controls causes you to "
                "discard this card, put it onto the battlefield instead of putting it into your graveyard.", 4, 4)
    assert bal.discard_to_bf
    me.hand.append(bal)
    me.hand.remove(bal)
    g._fx_controller = ops[0]
    g.discard_card(me, bal)
    g._fx_controller = None
    assert any(pm.name == "Baloth" for pm in me.battlefield)


def test_optional_additional_costs_teamwork_and_blight():
    g, me, ops = new_game()
    cs = build("Cinder Strike", "{R}", "Sorcery", "As an additional cost to cast this spell, you may blight 1.\n"
               "Cinder Strike deals 2 damage to target creature. It deals 4 damage to that creature instead if this "
               "spell's additional cost was paid.")
    assert cs.opt_add == ("blight", 1)
    x = put(g, creature("X", "2G", 2, 3), me)
    foe = put(g, creature("Foe", "2G", 4, 4), ops[0])
    give_lands(g, me, 1, colors=(R,))
    me.hand.append(cs)
    assert g.cast(me, cs, targets=[foe])
    run(g)
    assert foe not in ops[0].battlefield and x.counters.get("-1/-1") == 1
    g, me, ops = new_game()
    aa = build("Atlantis", "{5}{U}{U}", "Sorcery", "Teamwork 4\nChoose one. If this spell was cast using teamwork, "
               "choose both instead.\n• Target player creates a 6/5 blue Leviathan creature token with hexproof.\n"
               "• Return one or two target nonland permanents to their owners' hands.")
    assert aa.opt_add == ("teamwork", 4) and aa.modes_all_if_opt and len(aa.modes) == 2
    for i in range(2):
        put(g, creature(f"C{i}", "2G", 2, 2), me)
    put(g, creature("F", "2G", 5, 5), ops[0])
    give_lands(g, me, 7, colors=(U,))
    me.hand.append(aa)
    assert g.cast(me, aa)
    run(g)
    assert any(pm.name == "Leviathan" for pm in me.battlefield) and any(c.name == "F" for c in ops[0].hand)


def test_fuse_equip_legendary_and_reminder_keywords():
    g, me, ops = new_game()
    import cardsdb
    aw = cardsdb.build_card_from_data({
        "name": "Alive // Well", "layout": "split", "keywords": ["Fuse"], "type_line": "Sorcery // Sorcery",
        "mana_cost": "{3}{G} // {W}", "card_faces": [
            {"name": "Alive", "mana_cost": "{3}{G}", "type_line": "Sorcery",
             "oracle_text": "Create a 3/3 green Centaur creature token.\nFuse"},
            {"name": "Well", "mana_cost": "{W}", "type_line": "Sorcery",
             "oracle_text": "You gain 2 life for each creature you control.\nFuse"}]})
    assert aw.fuse
    give_lands(g, me, 5, colors=(G, W))
    me.hand.append(aw)
    life = me.life
    assert g.cast(me, aw)
    run(g)
    assert any(pm.name == "Centaur" for pm in me.battlefield) and me.life == life + 2
    bb = build("Blackblade", "{1}", "Legendary Artifact — Equipment", "Equipped creature gets +1/+1.\n"
               "Equip legendary creature {3}\nEquip {7}")
    labels = {ab["label"]: ab["cost"].cmc for ab in bb.activated_abilities}
    assert labels == {"Equipar": 7, "Equipar (legendaria)": 3}
    az = cardsdb.build_card_from_data({"name": "Azula", "type_line": "Legendary Creature — Human Noble",
                                       "mana_cost": "{3}{B}", "oracle_text": "Firebending 2", "keywords": ["Firebending"],
                                       "power": "4", "toughness": "4"})
    assert "attacks" in (az.triggers or {})
    cane = cardsdb.build_card_from_data({"name": "Cane", "type_line": "Artifact — Equipment", "mana_cost": "{2}{U}",
                                         "oracle_text": "Job select\nEquipped creature gets +0/+2.\nEquip {2}",
                                         "keywords": ["Job select"]})
    g, me, ops = new_game()
    put(g, cane, me)
    run(g)
    assert any(pm.name == "Hero" for pm in me.battlefield)


def test_chancellor_search_zones_and_basic_land_to_hand():
    import cardsdb
    g, me, ops = new_game()
    ch = build("Chancellor", "{4}{B}{B}{B}", "Creature — Phyrexian Angel", "You may reveal this card from your opening "
               "hand. If you do, at the beginning of the first upkeep, each opponent loses 3 life.", 5, 5)
    me.hand.append(ch)
    for p in g.players:
        p.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    life = ops[0].life
    g.begin_turn(ops[0])
    run(g)
    assert life - ops[0].life == 3
    g, me, ops = new_game()
    me.library = [creature("C", "1G", 1, 1), land("Forest", [G], basic=True)]
    cardsdb._effect_any("search your library for a basic land card, reveal it, put it into your hand, then shuffle.")(
        g, me)
    run(g)
    assert any(c.name == "Forest" for c in me.hand) and not any(pm.name == "Forest" for pm in me.battlefield)
    g, me, ops = new_game()
    me.library = [creature("C", "1G", 1, 1)]
    me.graveyard = [land("Forest", [G], basic=True)]
    cardsdb._effect_any("search your library and/or graveyard for a basic land card, reveal it, and put it into "
                        "your hand.")(g, me)
    assert any(c.name == "Forest" for c in me.hand) and not me.graveyard


def test_haste_abilities_torpor_damage_up_to_targets_and_gy_leave():
    import cardsdb
    g, me, ops = new_game()
    put(g, build("Elixir", "{3}", "Legendary Artifact", "You may activate abilities of creatures you control as though "
                 "those creatures had haste."), me)
    pinger = put(g, build("Pinger", "{1}{R}", "Creature — Human", "{T}: This creature deals 1 damage to each "
                          "opponent.", 1, 1), me)
    assert pinger.summoning_sick and g.activate_ability(pinger, 0)
    g, me, ops = new_game()
    put(g, build("Orb", "{2}", "Artifact", "Creatures entering don't cause abilities to trigger."), me)
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    h = len(me.hand)
    put(g, build("Drawer", "{1}{U}", "Creature — Human", "When this creature enters, draw a card.", 1, 1), me)
    run(g)
    assert len(me.hand) == h
    g, me, ops = new_game()
    foes = [put(g, creature(f"F{k}", "1G", 2, 2), ops[0]) for k in range(2)]
    cardsdb._effect_any("~ deals 2 damage to each of up to two targets")(g, me)
    assert not any(f in ops[0].battlefield for f in foes)
    sk = put(g, build("Crew", "{2}{B}", "Creature — Skeleton", "Whenever one or more creature cards leave your "
                      "graveyard, create a 2/2 black Skeleton Pirate creature token.", 1, 1), me)
    n = len(me.battlefield)
    g.emit("leaves_graveyard", player=me, card=land("Swamp", [B], basic=True))     # no es criatura
    run(g)
    assert len(me.battlefield) == n
    g.emit("leaves_graveyard", player=me, card=creature("Dead", "1B", 1, 1))
    run(g)
    assert len(me.battlefield) == n + 1 and sk in me.battlefield
