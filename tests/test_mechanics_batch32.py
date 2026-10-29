"""Batch 32: etiquetas de sabor ("Rot Fly —"), Szadek, Khârn, Everlasting Torment, contadores
extra al entrar (Tromell/Thrinax/Giada), Damia, Vorosh, Barrowgoyf, Archfiend of Ifnir,
Drumbellower, Desecrator Hag, Patron of the Nezumi, Leadership Vacuum, Let the Galaxy Burn,
Wrecking Ball Arm, Cloud, Harsh Mentor, Incite Rebellion, Archangel of Tithes, Massacre Girl,
Chocobo Knights, Heroes' Podium, Dazzling Sphinx, Thief of Sanity."""
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


def test_flavor_word_plague_drone():
    g, me, ops = new_game()
    put(g, build("Plague Drone", "{3}{B}", "Creature — Demon", "Flying\nRot Fly — If an opponent would gain life, that "
                 "player loses that much life instead.", 3, 3), me)
    l0 = ops[0].life
    g.gain_life(ops[0], 3)
    assert ops[0].life == l0 - 3


def test_szadek_counters_and_mill():
    g, me, ops = new_game()
    sz = put(g, build("Szadek, Lord of Secrets", "{3}{U}{U}{B}{B}", "Legendary Creature — Vampire", "Flying\nIf Szadek "
                      "would deal combat damage to a player, instead put that many +1/+1 counters on Szadek and that "
                      "player mills that many cards.", 5, 5), me)
    l0, lib0 = ops[0].life, len(ops[0].library)
    _attack(g, me, [(sz, ops[0])])
    assert ops[0].life == l0 and len(ops[0].library) == lib0 - 5 and sz.counters.get("+1/+1") == 5


def test_kharn_changes_control_when_damaged():
    g, me, ops = new_game()
    kh = put(g, build("Khârn the Betrayer", "{3}{R}", "Legendary Creature — Astartes Berserker", "Berzerker — Khârn the "
                      "Betrayer attacks or blocks each combat if able.\nSigil of Corruption — When you lose control of "
                      "Khârn the Betrayer, draw two cards.\nThe Betrayer — If damage would be dealt to Khârn the "
                      "Betrayer, prevent that damage and an opponent of your choice gains control of it.", 5, 1), me)
    h = len(me.hand)
    g.deal_damage(None, kh, 3)
    run(g)
    assert kh in ops[0].battlefield and len(me.hand) >= h + 2 and kh.damage == 0


def test_everlasting_torment_wither_and_no_gain():
    g, me, ops = new_game()
    put(g, build("Everlasting Torment", "{2}{B/R}", "Enchantment", "Players can't gain life.\nDamage can't be prevented."
                 "\nAll damage is dealt as though its source had wither."), me)
    c = put(g, creature("C", "G", 3, 3), ops[0])
    g.deal_damage(None, c, 1)
    l0 = me.life
    g.gain_life(me, 5)
    assert c.counters.get("-1/-1") == 1 and me.life == l0


def test_etb_counter_bonuses():
    g, me, ops = new_game()
    put(g, build("Tromell, Seymour's Butler", "{2}{G}", "Legendary Creature — Elf Advisor", "Each other nontoken "
                 "creature you control enters with an additional +1/+1 counter on it.", 2, 3), me)
    a = put(g, creature("A", "G", 1, 1), me)
    assert a.counters.get("+1/+1") == 1
    g2, me2, _ = new_game()
    put(g2, build("Giada, Font of Hope", "{1}{W}", "Legendary Creature — Angel", "Flying, vigilance\nEach other Angel "
                  "you control enters with an additional +1/+1 counter on it for each Angel you already control.", 2, 2),
        me2)
    an = put(g2, creature("Ang", "3W", 3, 3, subtypes=("Angel",)), me2)
    assert an.counters.get("+1/+1") == 1


def test_damia_draws_to_seven():
    g, me, ops = new_game()
    put(g, build("Damia, Sage of Stone", "{4}{B}{G}{U}", "Legendary Creature — Gorgon Wizard", "Deathtouch\nSkip your "
                 "draw step.\nAt the beginning of your upkeep, if you have fewer than seven cards in hand, draw cards "
                 "equal to the difference.", 4, 4), me)
    me.hand = [land("F", [G], basic=True)] * 2
    g.emit("upkeep", player=me)
    run(g)
    assert len(me.hand) == 7


def test_barrowgoyf_mills_and_takes_creature():
    g, me, ops = new_game()
    bg = put(g, build("Barrowgoyf", "{2}{B}", "Creature — Lhurgoyf", "Deathtouch, lifelink\nWhenever this creature deals "
                      "combat damage to a player, you may mill that many cards. If you do, you may put a creature card "
                      "from among them into your hand.", 3, 4), me)
    me.library.append(creature("Fat", "4G", 5, 5))
    _attack(g, me, [(bg, ops[0])])
    assert any(c.name == "Fat" for c in me.hand)


def test_archfiend_of_ifnir_on_discard():
    g, me, ops = new_game()
    put(g, build("Archfiend of Ifnir", "{3}{B}{B}", "Creature — Demon", "Flying\nWhenever you cycle or discard another "
                 "card, put a -1/-1 counter on each creature your opponents control.\nCycling {2}", 5, 4), me)
    c = put(g, creature("C", "G", 2, 2), ops[0])
    x = land("F", [G], basic=True)
    me.hand.append(x)
    me.hand.remove(x)
    g.discard_card(me, x)
    run(g)
    assert c.counters.get("-1/-1") == 1


def test_drumbellower_untaps_on_other_turns():
    g, me, ops = new_game()
    put(g, build("Drumbellower", "{2}{W}", "Creature — Spirit", "Flying\nUntap all creatures you control during each "
                 "other player's untap step.", 2, 1), me)
    c = put(g, creature("C", "G", 2, 2), me)
    c.tapped = True
    g.active_index = g.players.index(ops[0])
    g.begin_turn(ops[0])
    assert not c.tapped


def test_desecrator_hag_returns_biggest():
    g, me, ops = new_game()
    me.graveyard += [creature("Small", "G", 1, 1), creature("Big", "4G", 6, 6)]
    put(g, build("Desecrator Hag", "{2}{B/G}{B/G}", "Creature — Hag", "When this creature enters, return to your hand "
                 "the creature card in your graveyard with the greatest power. If two or more cards are tied for "
                 "greatest power, you choose one of them.", 2, 2), me)
    assert any(c.name == "Big" for c in me.hand)


def test_patron_of_the_nezumi():
    g, me, ops = new_game()
    put(g, build("Patron of the Nezumi", "{5}{B}{B}", "Legendary Creature — Spirit", "Whenever a permanent is put into "
                 "an opponent's graveyard, that player loses 1 life.", 6, 6), me)
    c = put(g, creature("C", "G", 2, 2), ops[0])
    l0 = ops[0].life
    g.destroy(c)
    run(g)
    assert ops[0].life == l0 - 1


def test_leadership_vacuum_bounces_commander():
    g, me, ops = new_game()
    cmd = ops[0].command[0]
    ops[0].command.remove(cmd)
    put(g, cmd, ops[0])
    lv = build("Leadership Vacuum", "{2}{U}", "Instant", "Target player returns each commander they control from the "
               "battlefield to the command zone.\nDraw a card.")
    lv.on_cast_resolve(g, me, [])
    assert cmd in ops[0].command


def test_let_the_galaxy_burn_spares_new():
    g, me, ops = new_game()
    old = put(g, creature("Old", "G", 3, 3), ops[0])
    old._etb_turn = -1
    new = put(g, creature("New", "G", 1, 1), ops[0])
    lb = build("Let the Galaxy Burn", "{X}{5}{R}", "Sorcery", "Cascade\nLet the Galaxy Burn deals X plus 2 damage to "
               "each creature that didn't enter this turn.")
    g.spell_x = 1
    lb.on_cast_resolve(g, me, [])
    assert old not in ops[0].battlefield and new in ops[0].battlefield


def test_wrecking_ball_arm():
    g, me, ops = new_game()
    arm = put(g, build("Wrecking Ball Arm", "{2}", "Legendary Artifact — Equipment", "Equipped creature has base power "
                       "and toughness 7/7 and can't be blocked by creatures with power 2 or less.\nEquip legendary "
                       "creature {3}\nEquip {7}"), me)
    a = put(g, creature("A", "G", 1, 1), me)
    arm.enchanting = a
    bl = put(g, creature("Bl", "G", 2, 5), ops[0])
    assert (a.power, a.toughness) == (7, 7) and not g._can_block_evasion(a, bl)


def test_cloud_attaches_equipment_on_etb():
    g, me, ops = new_game()
    eq = put(g, build("Blade", "{1}", "Artifact — Equipment", "Equipped creature gets +2/+0.\nEquip {2}"), me)
    cl = put(g, build("Cloud, Ex-SOLDIER", "{2}{R}{G}{W}", "Legendary Creature — Human Soldier Mercenary", "Haste\nWhen "
                      "Cloud enters, attach up to one target Equipment you control to it.\nWhenever Cloud attacks, draw "
                      "a card for each equipped attacking creature you control. Then if Cloud has power 7 or greater, "
                      "create two Treasure tokens.", 4, 4), me)
    assert eq.enchanting is cl


def test_harsh_mentor_punishes_activation():
    g, me, ops = new_game()
    put(g, build("Harsh Mentor", "{1}{R}", "Creature — Human Cleric", "Whenever an opponent activates an ability of an "
                 "artifact, creature, or land on the battlefield, if it isn't a mana ability, this creature deals 2 "
                 "damage to that player.", 2, 2), me)
    pinger = put(g, build("Pinger", "{1}{R}", "Creature — Human", "{T}: This creature deals 1 damage to any target.",
                          1, 1), ops[0])
    pinger.summoning_sick = False
    l0 = ops[0].life
    g.active_index = g.players.index(ops[0])
    assert g.activate_ability(pinger, 0, targets=[me])
    run(g)
    assert ops[0].life == l0 - 2


def test_incite_rebellion():
    g, me, ops = new_game()
    for i in range(2):
        put(g, creature(f"M{i}", "G", 3, 3), me)
    put(g, creature("O", "G", 1, 1), ops[0])
    ir = build("Incite Rebellion", "{4}{R}{R}", "Sorcery", "For each player, Incite Rebellion deals damage to that player "
               "and each creature that player controls equal to the number of creatures they control.")
    l0, o0 = me.life, ops[0].life
    ir.on_cast_resolve(g, me, [])
    assert me.life == l0 - 2 and ops[0].life == o0 - 1 and not ops[0].creatures()


def test_archangel_of_tithes_tax():
    g, me, ops = new_game()
    ang = put(g, build("Archangel of Tithes", "{1}{W}{W}{W}", "Creature — Angel", "Flying\nAs long as this creature is "
                       "untapped, creatures can't attack you or planeswalkers you control unless their controller pays "
                       "{1} for each of those creatures.\nAs long as this creature is attacking, creatures can't block "
                       "unless their controller pays {1} for each of those creatures.", 3, 5), me)
    assert g.attack_tax(me) == 1
    ang.tapped = True
    assert g.attack_tax(me) == 0


def test_massacre_girl_chain():
    g, me, ops = new_game()
    a = put(g, creature("A", "G", 1, 1), ops[0])
    b = put(g, creature("B", "G", 2, 2), ops[0])
    c = put(g, creature("C", "G", 4, 4), ops[0])
    put(g, build("Massacre Girl", "{3}{B}{B}", "Legendary Creature — Human Assassin", "Menace\nWhen Massacre Girl enters, "
                 "each other creature gets -1/-1 until end of turn. Whenever a creature dies this turn, each creature "
                 "other than Massacre Girl gets -1/-1 until end of turn.", 4, 4), me)
    run(g)
    assert a not in ops[0].battlefield and b not in ops[0].battlefield and c in ops[0].battlefield


def test_heroes_podium_and_chocobo():
    g, me, ops = new_game()
    put(g, build("Heroes' Podium", "{5}", "Legendary Artifact", "Each legendary creature you control gets +1/+1 for "
                 "each other legendary creature you control."), me)
    l1 = put(g, creature("L1", "G", 2, 2, legendary=True), me)
    put(g, creature("L2", "G", 2, 2, legendary=True), me)
    assert l1.power == 3


def test_dazzling_sphinx_casts_instant():
    g, me, ops = new_game()
    sp = put(g, build("Dazzling Sphinx", "{3}{U}{U}", "Creature — Sphinx", "Flying\nWhenever this creature deals combat "
                      "damage to a player, that player exiles cards from the top of their library until they exile an "
                      "instant or sorcery card. You may cast that card without paying its mana cost. Then that player "
                      "puts the exiled cards that weren't cast this way on the bottom of their library in a random "
                      "order.", 4, 5), me)
    ops[0].library.append(build("Divination", "{2}{U}", "Sorcery", "Draw two cards."))
    h = len(me.hand)
    _attack(g, me, [(sp, ops[0])])
    assert len(me.hand) == h + 2


def test_thief_of_sanity_exiles_playable():
    g, me, ops = new_game()
    th = put(g, build("Thief of Sanity", "{1}{U}{B}", "Creature — Specter", "Flying\nWhenever this creature deals combat "
                      "damage to a player, look at the top three cards of that player's library, exile one of them face "
                      "down, then put the rest into their graveyard. You may cast that card for as long as it remains "
                      "exiled, and mana of any type can be spent to cast that spell.", 2, 2), me)
    ops[0].library.append(creature("Good", "3G", 4, 4))
    _attack(g, me, [(th, ops[0])])
    assert any(c.name == "Good" for c in me.exile_play)
