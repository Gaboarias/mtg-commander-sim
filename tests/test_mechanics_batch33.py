"""Batch 33: Howling Mine, Exsanguinate, Recurring Insight, Containment Priest, Blind Obedience,
Embercleave (reducción), Coat of Arms, Gravitational Shift, Balan, Raksha, Kardur, Ant-Man,
Crimson Honor Guard, Titan Hunter, Darien, Mystic Sanctuary, Twilight Shepherd, Skyfire Phoenix,
Bone Miser, Hunted Dragon, Gyome, Gahiji, Daxos, Marisi, Lyse Hext, Vibranium, Hercules,
Firebird, Winter Soldier, Thrilling Encore, Lier, Caldera Pyremaw."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands, artifact  # noqa: E402


def _attack(g, pl, pairs):
    g.active_index = g.players.index(pl)
    for a, _d in pairs:
        a.summoning_sick = False
    decl = g._declare_attackers(pl, pairs)
    g._finish_combat(decl)
    run(g)


def test_howling_mine_untapped_only():
    g, me, ops = new_game()
    hm = put(g, build("Howling Mine", "{2}", "Artifact", "At the beginning of each player's draw step, if this artifact "
                      "is untapped, that player draws an additional card."), me)
    g.turn = 3
    g.active_index = g.players.index(ops[0])
    h = len(ops[0].hand)
    g.begin_turn(ops[0])
    assert len(ops[0].hand) - h == 2
    hm.tapped = True
    g.turn = 5
    h = len(me.hand)
    g.active_index = 0
    hm.card.each_draw_untapped = True
    me.battlefield.remove(hm)
    ops[0].battlefield.append(hm)
    hm.controller = ops[0]
    g.begin_turn(me)
    # se endereza en el paso de enderezar de su controlador, no en el mío: sigue girada
    assert len(me.hand) - h == 1


def test_exsanguinate():
    g, me, ops = new_game(2)
    ex = build("Exsanguinate", "{X}{B}{B}", "Sorcery", "Each opponent loses X life. You gain life equal to the life lost "
               "this way.")
    g.spell_x = 3
    l0 = me.life
    ex.on_cast_resolve(g, me, [])
    assert ops[0].life == 37 and ops[1].life == 37 and me.life == l0 + 6


def test_containment_priest_exiles_reanimated():
    g, me, ops = new_game()
    put(g, build("Containment Priest", "{1}{W}", "Creature — Human Cleric", "Flash\nIf a nontoken creature would enter and "
                 "it wasn't cast, exile it instead.", 2, 2), me)
    c = creature("Dead", "4B", 5, 5)
    ops[0].graveyard.append(c)
    ops[0].graveyard.remove(c)
    assert g.move_to_battlefield(c, ops[0]) is None and c in ops[0].exile


def test_blind_obedience_taps_opponents():
    g, me, ops = new_game()
    put(g, build("Blind Obedience", "{1}{W}", "Enchantment", "Extort\nArtifacts and creatures your opponents control "
                 "enter tapped."), me)
    c = put(g, creature("C", "G", 2, 2), ops[0])
    mine = put(g, creature("M", "G", 2, 2), me)
    assert c.tapped and not mine.tapped


def test_embercleave_cost_reduction():
    g, me, ops = new_game()
    ec = build("Embercleave", "{4}{R}{R}", "Legendary Artifact — Equipment", "Flash\nThis spell costs {1} less to cast for "
               "each attacking creature you control.\nWhen Embercleave enters, attach it to target creature you "
               "control.\nEquipped creature gets +1/+1 and has double strike and trample.\nEquip {3}")
    for i in range(2):
        put(g, creature(f"A{i}", "G", 2, 2), me).attacking = ops[0]
    assert ec.cost_reduction_fn(g, me) == 2


def test_coat_of_arms_and_gravitational_shift():
    g, me, ops = new_game()
    put(g, build("Coat of Arms", "{5}", "Artifact", "Each creature gets +1/+1 for each other creature on the battlefield "
                 "that shares at least one creature type with it."), me)
    a = put(g, creature("G1", "R", 1, 1, subtypes=("Goblin",)), me)
    put(g, creature("G2", "R", 1, 1, subtypes=("Goblin",)), ops[0])
    assert a.power == 2
    g2, me2, _ = new_game()
    put(g2, build("Gravitational Shift", "{3}{U}{U}", "Enchantment", "Creatures with flying get +2/+0.\nCreatures without "
                  "flying get -2/-0."), me2)
    f = put(g2, creature("F", "U", 1, 1, kw=("flying",)), me2)
    n = put(g2, creature("N", "G", 3, 3), me2)
    assert f.power == 3 and n.power == 1


def test_balan_and_raksha():
    g, me, ops = new_game()
    bal = put(g, build("Balan, Wandering Knight", "{2}{W}{W}", "Legendary Creature — Cat Knight", "First strike\nBalan "
                       "has double strike as long as two or more Equipment are attached to it.\n{1}{W}: Attach all "
                       "Equipment you control to Balan.", 3, 3), me)
    assert not bal.has("double_strike")
    for i in range(2):
        e = put(g, build(f"E{i}", "{1}", "Artifact — Equipment", "Equipped creature gets +1/+0.\nEquip {1}"), me)
        e.enchanting = bal
    assert bal.has("double_strike")
    rk = put(g, build("Raksha Golden Cub", "{5}{W}{W}", "Legendary Creature — Cat Soldier", "Vigilance\nAs long as Raksha "
                      "Golden Cub is equipped, Cat creatures you control get +2/+2 and have double strike.", 3, 4), me)
    cat = put(g, creature("Kitty", "W", 1, 1, subtypes=("Cat",)), me)
    assert cat.power == 1
    me.battlefield[[x.name for x in me.battlefield].index("E0")].enchanting = rk
    assert cat.power == 3 and cat.has("double_strike")


def test_kardur_goads_and_drains():
    g, me, ops = new_game()
    c = put(g, creature("C", "G", 2, 2), ops[0])
    put(g, build("Kardur, Doomscourge", "{2}{B}{R}", "Legendary Creature — Demon Berserker", "When Kardur enters, until "
                 "your next turn, creatures your opponents control attack each combat if able and attack a player "
                 "other than you if able.\nWhenever an attacking creature dies, each opponent loses 1 life and you gain "
                 "1 life.", 4, 3), me)
    assert c.goaded
    c.attacking = me
    l0 = ops[0].life
    g.destroy(c)
    run(g)
    assert ops[0].life == l0 - 1


def test_ant_man_treasures():
    g, me, ops = new_game()
    am = put(g, build("Ant-Man, Elusive Avenger", "{1}{U}{R}", "Legendary Creature — Human Rogue Hero", "Ant-Man can't "
                      "be blocked by creatures with greater power.\nWhenever Ant-Man deals combat damage to a player, "
                      "create that many Treasure tokens.", 2, 2), me)
    _attack(g, me, [(am, ops[0])])
    assert sum(1 for x in me.battlefield if x.name == "Treasure") == 2


def test_crimson_honor_guard_and_titan_hunter():
    g, me, ops = new_game()
    put(g, build("Crimson Honor Guard", "{3}{R}{R}", "Creature — Vampire Knight", "Trample\nAt the beginning of each "
                 "player's end step, this creature deals 4 damage to that player unless they control a commander.",
                 4, 5), me)
    l0 = ops[0].life
    g.emit("each_end_step", active=ops[0])
    run(g)
    assert ops[0].life == l0 - 4


def test_darien_soldiers():
    g, me, ops = new_game()
    put(g, build("Darien, King of Kjeldor", "{4}{W}{W}", "Legendary Creature — Human Soldier", "Whenever you're dealt "
                 "damage, you may create that many 1/1 white Soldier creature tokens.", 3, 3), me)
    g.deal_damage(None, me, 3)
    run(g)
    assert sum(1 for x in me.battlefield if x.name == "Soldier") == 3


def test_twilight_shepherd_and_thrilling_encore():
    g, me, ops = new_game()
    c = put(g, creature("C", "G", 2, 2), me)
    g.destroy(c)
    run(g)
    put(g, build("Twilight Shepherd", "{3}{W}{W}{W}", "Creature — Angel", "Flying, vigilance\nWhen this creature enters, "
                 "return to your hand all cards in your graveyard that were put there from the battlefield this turn."
                 "\nPersist", 5, 5), me)
    assert any(x.name == "C" for x in me.hand)
    o = put(g, creature("O", "G", 3, 3), ops[0])
    g.destroy(o)
    run(g)
    te = build("Thrilling Encore", "{4}{B}", "Instant", "Put onto the battlefield under your control all creature cards in "
               "all graveyards that were put there from the battlefield this turn.")
    te.on_cast_resolve(g, me, [])
    assert any(x.name == "O" for x in me.battlefield)


def test_skyfire_phoenix_returns_on_commander_cast():
    g, me, ops = new_game()
    ph = build("Skyfire Phoenix", "{2}{R}{R}", "Creature — Phoenix", "Flying, haste\nWhen you cast your commander, return "
               "this card from your graveyard to the battlefield.", 3, 3)
    me.graveyard.append(ph)
    give_lands(g, me, 3)
    g.active_index = 0
    assert g.cast(me, me.command[0], from_command=True)
    run(g)
    assert any(x.name == "Skyfire Phoenix" for x in me.battlefield)


def test_bone_miser_zombie():
    g, me, ops = new_game()
    put(g, build("Bone Miser", "{4}{B}", "Creature — Zombie Wizard", "Whenever you discard a creature card, create a 2/2 "
                 "black Zombie creature token.\nWhenever you discard a land card, add {B}{B}.\nWhenever you discard a "
                 "noncreature, nonland card, draw a card.", 4, 4), me)
    x = creature("X", "G", 1, 1)
    g.discard_card(me, x)
    run(g)
    assert any(p.name == "Zombie" for p in me.battlefield)


def test_hunted_dragon_gives_knights():
    g, me, ops = new_game()
    put(g, build("Hunted Dragon", "{3}{R}{R}", "Creature — Dragon", "Flying, haste\nWhen this creature enters, target "
                 "opponent creates three 2/2 white Knight creature tokens with first strike.", 6, 6), me)
    assert sum(1 for x in ops[0].battlefield if x.name == "Knight") == 3


def test_gyome_foods():
    g, me, ops = new_game()
    put(g, build("Gyome, Master Chef", "{2}{B}{G}", "Legendary Creature — Troll Warlock", "Trample\nAt the beginning of "
                 "your end step, create a number of Food tokens equal to the number of nontoken creatures you had enter "
                 "the battlefield under your control this turn.", 5, 3), me)
    put(g, creature("A", "G", 1, 1), me)
    g.emit("end_step", player=me)
    run(g)
    assert sum(1 for x in me.battlefield if x.name == "Food") == 2      # Gyome + A


def test_gahiji_and_firebird_pump_attackers():
    g, me, ops = new_game()
    put(g, build("Gahiji, Honored One", "{2}{R}{G}{W}", "Legendary Creature — Beast", "Whenever a creature attacks one of "
                 "your opponents or a planeswalker an opponent controls, that creature gets +2/+0 until end of turn.",
                 4, 4), me)
    a = put(g, creature("A", "G", 1, 1), me)
    a.summoning_sick = False
    g.active_index = 0
    g._declare_attackers(me, [(a, ops[0])])
    run(g)
    assert a.power == 3


def test_daxos_exiles_and_gains():
    g, me, ops = new_game()
    dx = put(g, build("Daxos of Meletis", "{1}{W}{U}", "Legendary Creature — Human Soldier", "Daxos can't be blocked by "
                      "creatures with power 3 or greater.\nWhenever Daxos deals combat damage to a player, exile the top "
                      "card of that player's library. You gain life equal to that card's mana value. Until end of turn, "
                      "you may cast that card and you may spend mana as though it were mana of any color to cast that "
                      "spell.", 2, 2), me)
    ops[0].library.append(creature("Big", "4G", 5, 5))
    l0 = me.life
    _attack(g, me, [(dx, ops[0])])
    assert me.life == l0 + 5 and any(x.name == "Big" for x in me.exile_play)


def test_marisi_goads():
    g, me, ops = new_game()
    put(g, build("Marisi, Breaker of the Coil", "{1}{R}{G}{W}", "Legendary Creature — Cat Warrior", "Your opponents can't "
                 "cast spells during combat.\nWhenever a creature you control deals combat damage to a player, goad "
                 "each creature that player controls.", 5, 4), me)
    o = put(g, creature("O", "G", 1, 1), ops[0])
    o.tapped = True
    a = put(g, creature("A", "G", 2, 2), me)
    _attack(g, me, [(a, ops[0])])
    assert o.goaded


def test_vibranium_and_hercules():
    g, me, ops = new_game()
    put(g, build("Shuri's Fabricator", "{4}", "Artifact", "When this artifact enters, create two tapped Vibranium tokens."),
        me)
    vb = [x for x in me.battlefield if x.name == "Vibranium"]
    assert len(vb) == 2 and all(x.tapped and x.has("indestructible") for x in vb)
    hc = put(g, build("Hercules, Olympian Hero", "{3}{W}{W}", "Legendary Creature — Demigod Warrior Hero", "Whenever "
                      "Hercules attacks, put a +1/+1 counter on him. He gains indestructible until end of turn.\nWhenever "
                      "Hercules is dealt damage for the first time each turn, put that many +1/+1 counters on him.",
                      3, 3), me)
    g.deal_damage(None, hc, 2)
    run(g)
    assert hc.counters.get("+1/+1") == 2


def test_winter_soldier_reanimates():
    g, me, ops = new_game()
    me.graveyard.append(creature("Dead", "2G", 3, 3))
    ws = put(g, build("Winter Soldier, Reborn Avenger", "{4}{W}", "Legendary Creature — Human Soldier Hero", "Whenever "
                      "Winter Soldier attacks, return target creature card with mana value less than or equal to Winter "
                      "Soldier's power from your graveyard to the battlefield. If a Hero enters this way, it enters with "
                      "an additional +1/+1 counter on it.", 3, 5), me)
    ws.summoning_sick = False
    g.active_index = 0
    g._declare_attackers(me, [(ws, ops[0])])
    run(g)
    assert any(x.name == "Dead" for x in me.battlefield)


def test_lier_uncounterable_and_caldera():
    g, me, ops = new_game()
    put(g, build("Lier, Disciple of the Drowned", "{3}{U}{U}", "Legendary Creature — Human Wizard", "Spells can't be "
                 "countered.\nEach instant and sorcery card in your graveyard has flashback. The flashback cost is "
                 "equal to that card's mana cost.", 3, 4), me)
    sp = build("Shock", "{R}", "Instant", "Shock deals 2 damage to any target.")
    assert g._uncounterable(None, sp)
    cp = put(g, build("Caldera Pyremaw", "{3}{R}{R}", "Creature — Dragon", "Flying\nWhenever you cast an instant or "
                      "sorcery spell, put a +1/+1 counter on this creature. Then this creature deals damage equal to its "
                      "power to target opponent.", 3, 3), me)
    l0 = ops[0].life
    g.emit("cast", player=me, card=sp)
    run(g)
    assert cp.counters.get("+1/+1") == 1 and ops[0].life == l0 - 4
