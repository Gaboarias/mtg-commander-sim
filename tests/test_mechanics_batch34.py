"""Batch 34: Assault Suit, Comet Storm, Stalking Leonin, Centaur Vinecrasher (desde el
cementerio), Yedora, Wildfire Devils, The Mimeoplasm, Sewer Nemesis, Dawnbreak Reclaimer,
Cunning Rhetoric, Cartographer's Hawk, Sudden Spoiling, Solidarity of Heroes, Skeletal Scrying,
Stoneshock Giant, Villainous Wealth, Vesuva, Turntimber Sower, Spectacular Showdown, Scrap
Trawler, Triskaidekaphile."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands, artifact  # noqa: E402


def test_assault_suit_gives_control_on_opp_upkeep():
    g, me, ops = new_game()
    su = put(g, build("Assault Suit", "{4}", "Artifact — Equipment", "Equipped creature gets +2/+2, has haste, can't "
                      "attack you or planeswalkers you control, and can't be sacrificed.\nAt the beginning of each "
                      "opponent's upkeep, you may have that player gain control of equipped creature until end of turn. "
                      "If you do, untap it.\nEquip {3}"), me)
    c = put(g, creature("C", "G", 2, 2), me)
    su.enchanting = c
    c.tapped = True
    g.emit("each_upkeep", active=ops[0])
    run(g)
    assert c in ops[0].battlefield and not c.tapped and c in g.control_returns


def test_comet_storm_kicked_two_targets():
    g, me, ops = new_game()
    cs = build("Comet Storm", "{X}{R}{R}", "Instant", "Multikicker {1}\nChoose any target, then choose another target for "
               "each time this spell was kicked. Comet Storm deals X damage to each of them.")
    a = put(g, creature("A", "G", 3, 3), ops[0])
    g.spell_x = 3
    cs._kicked = True
    l0 = ops[0].life
    cs.on_cast_resolve(g, me, [])
    assert a not in ops[0].battlefield and ops[0].life == l0 - 3


def test_stalking_leonin_exiles_attacker():
    g, me, ops = new_game()
    sl = put(g, build("Stalking Leonin", "{2}{W}", "Creature — Cat Archer", "When this creature enters, secretly choose "
                      "an opponent.\nReveal the player you chose: Exile target creature that's attacking you if it's "
                      "controlled by the chosen player. Activate only once.", 3, 3), me)
    assert sl._leonin_opp is ops[0]
    a = put(g, creature("A", "G", 4, 4), ops[0])
    a.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    g._declare_attackers(ops[0], [(a, me)])
    run(g)
    assert a not in ops[0].battlefield


def test_centaur_vinecrasher_returns_from_graveyard():
    g, me, ops = new_game()
    cv = build("Centaur Vinecrasher", "{3}{G}", "Creature — Plant Centaur", "Trample\nThis creature enters with a number "
               "of +1/+1 counters on it equal to the number of land cards in all graveyards.\nWhenever a land card is "
               "put into a graveyard from anywhere, you may pay {G}{G}. If you do, return this card from your graveyard "
               "to your hand.", 1, 1)
    me.graveyard.append(cv)
    give_lands(g, me, 2)
    l = put(g, land("L", [G], basic=False), ops[0])
    g.destroy(l)
    run(g)
    assert cv in me.hand


def test_yedora_returns_as_forest():
    g, me, ops = new_game()
    put(g, build("Yedora, Grave Gardener", "{4}{G}", "Legendary Creature — Treefolk Druid", "Whenever another nontoken "
                 "creature you control dies, you may return it to the battlefield face down under its owner's control. "
                 "It's a Forest land. (It has no other types or abilities.)", 5, 5), me)
    c = put(g, creature("C", "G", 2, 2), me)
    g.destroy(c)
    run(g)
    f = [x for x in me.battlefield if x.card.is_land() and "face_down" in x.card.tags]
    assert f and not f[0].is_creature() and me.produced(f[0]) == {"G": 1}


def test_mimeoplasm_copies_with_counters():
    g, me, ops = new_game()
    me.graveyard.append(creature("Big", "5G", 6, 6))
    ops[0].graveyard.append(creature("Bear", "1G", 2, 2))
    mm = put(g, build("The Mimeoplasm", "{2}{B}{G}{U}", "Legendary Creature — Ooze", "As The Mimeoplasm enters, you may "
                      "exile two creature cards from graveyards. If you do, it enters as a copy of one of those cards "
                      "with a number of additional +1/+1 counters on it equal to the power of the other card.", 0, 0), me)
    assert mm in me.battlefield and mm.name == "Big" and mm.counters.get("+1/+1") == 2


def test_sewer_nemesis_power_and_mill():
    g, me, ops = new_game()
    ops[0].graveyard += [land("F", [G], basic=True) for _ in range(4)]
    sn = put(g, build("Sewer Nemesis", "{3}{B}", "Creature — Horror", "As this creature enters, choose a player.\nSewer "
                      "Nemesis's power and toughness are each equal to the number of cards in the chosen player's "
                      "graveyard.\nWhenever the chosen player casts a spell, that player mills a card.", 0, 0), me)
    assert sn in me.battlefield and sn.power == 4 and sn.toughness == 4
    g.emit("any_cast", caster=ops[0], card=creature("X", "G", 1, 1))
    run(g)
    assert len(ops[0].graveyard) == 5


def test_dawnbreak_reclaimer_returns_both():
    g, me, ops = new_game()
    put(g, build("Dawnbreak Reclaimer", "{4}{W}{W}", "Creature — Angel", "Flying\nAt the beginning of your end step, "
                 "choose a creature card in an opponent's graveyard, then that player chooses a creature card in your "
                 "graveyard. You may return those cards to the battlefield under their owners' control.", 5, 5), me)
    me.graveyard.append(creature("Mine", "3G", 4, 4))
    ops[0].graveyard.append(creature("Theirs", "G", 1, 1))
    g.emit("end_step", player=me)
    run(g)
    assert any(x.name == "Mine" for x in me.battlefield) and any(x.name == "Theirs" for x in ops[0].battlefield)


def test_cunning_rhetoric_exiles_once_per_attack():
    g, me, ops = new_game()
    put(g, build("Cunning Rhetoric", "{2}{B}", "Enchantment", "Whenever an opponent attacks you and/or one or more "
                 "planeswalkers you control, exile the top card of that player's library. You may play that card for "
                 "as long as it remains exiled, and you may spend mana as though it were mana of any color to cast it."),
        me)
    a1 = put(g, creature("A1", "G", 1, 1), ops[0])
    a2 = put(g, creature("A2", "G", 1, 1), ops[0])
    for a in (a1, a2):
        a.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    g._declare_attackers(ops[0], [(a1, me), (a2, me)])
    run(g)
    assert len(me.exile_play) == 1


def test_sudden_spoiling_and_solidarity():
    g, me, ops = new_game()
    big = put(g, creature("Big", "4G", 6, 6, kw=("flying",)), ops[0])
    ss = build("Sudden Spoiling", "{1}{B}{B}", "Instant", "Split second\nUntil end of turn, creatures target player "
               "controls lose all abilities and have base power and toughness 0/2.")
    ss.on_cast_resolve(g, me, [])
    assert (big.power, big.toughness) == (0, 2) and not big.has("flying")
    c = put(g, creature("C", "G", 1, 1), me)
    g.add_counters(c, "+1/+1", 3)
    sh = build("Solidarity of Heroes", "{1}{G}", "Instant", "Strive — This spell costs {1}{G} more to cast for each "
               "target beyond the first.\nChoose any number of target creatures. Double the number of +1/+1 counters "
               "on each of them.")
    sh.on_cast_resolve(g, me, [])
    assert c.counters["+1/+1"] == 6


def test_stoneshock_giant_no_block():
    g, me, ops = new_game()
    sg = put(g, build("Stoneshock Giant", "{3}{R}{R}", "Creature — Giant", "{6}{R}{R}: Monstrosity 3.\nWhen this creature "
                      "becomes monstrous, creatures without flying your opponents control can't block this turn.", 5, 4),
             me)
    b = put(g, creature("B", "G", 1, 1), ops[0])
    g._push_self_trigger(sg, "monstrous", "monstruoso")
    run(g)
    assert b._no_block_turn == g.turn


def test_villainous_wealth_casts_free():
    g, me, ops = new_game()
    ops[0].library += [creature("C1", "2G", 3, 3), creature("C2", "4G", 5, 5)]
    vw = build("Villainous Wealth", "{X}{B}{G}{U}", "Sorcery", "Target opponent exiles the top X cards of their library. "
               "You may cast any number of spells with mana value X or less from among them without paying their mana "
               "costs.")
    g.spell_x = 3
    vw.on_cast_resolve(g, me, [])
    run(g)
    assert any(x.name == "C1" for x in me.battlefield) and not any(x.name == "C2" for x in me.battlefield)


def test_vesuva_copies_land():
    g, me, ops = new_game()
    put(g, build("Gaea's Cradle", "", "Legendary Land", "{T}: Add {G} for each creature you control."), ops[0])
    v = put(g, build("Vesuva", "", "Land", "You may have this land enter tapped as a copy of any land on the "
                     "battlefield."), me)
    assert v.name == "Gaea's Cradle" and v.tapped


def test_spectacular_showdown_and_scrap_trawler():
    g, me, ops = new_game()
    t = put(g, creature("T", "G", 3, 3), ops[0])
    sd = build("Spectacular Showdown", "{1}{R}", "Sorcery", "Put a double strike counter on target creature, then goad "
               "each creature that had a double strike counter put on it this way.\nOverload {4}{R}{R}{R}")
    sd.on_cast_resolve(g, me, [t])
    assert t.goaded and t.has("double_strike")
    put(g, build("Scrap Trawler", "{3}", "Artifact Creature — Construct", "Whenever this creature dies or another "
                 "artifact you control is put into a graveyard from the battlefield, return to your hand target "
                 "artifact card in your graveyard with lesser mana value.", 3, 2), me)
    me.graveyard.append(artifact("Small"))
    big = put(g, build("Bigart", "{4}", "Artifact", ""), me)
    g.destroy(big)
    run(g)
    assert any(c.name == "Small" for c in me.hand)
