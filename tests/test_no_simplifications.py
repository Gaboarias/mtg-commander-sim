"""Reglas completas que antes eran aproximadas (batches 31-35): Offerings con sus dos partes,
Endless Detour, Grave Sifter, Coram, Eidolon con bestow, multikicker real, Stalking Leonin,
Garna, Vela (deja el campo), Marisi, Lier (flashback), Archangel of Tithes al bloquear, Rat
offering, Doctor Doom, Fallen Shinobi / Daxos hasta fin de turno, Gahiji con cualquier criatura,
Breena, Assault Suit, Spectacular Showdown con sobrecarga, Skeletal Scrying, Domineering Will,
Massacre Girl, Robe of the Archmagi, Killer Service."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W, Cost  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands, artifact  # noqa: E402


def _choose(g, label):
    ch = g.pending_choice
    assert ch is not None, "no hay elección pendiente"
    idx = next(o["i"] for o in ch["options"] if label in o["name"])
    g.pending_choice = None
    ch["_apply"](idx)


def test_infernal_offering_both_parts():
    g, me, ops = new_game()
    put(g, creature("Mine", "G", 1, 1), me)
    put(g, creature("Theirs", "G", 2, 2), ops[0])
    me.graveyard.append(creature("Back", "3G", 4, 4))
    ops[0].graveyard.append(creature("TheirBack", "G", 1, 1))
    io = build("Infernal Offering", "{4}{B}", "Sorcery", "Choose an opponent. You and that player each sacrifice a "
               "creature. Each player who sacrificed a creature this way draws two cards.\nChoose an opponent. Return a "
               "creature card from your graveyard to the battlefield, then that player returns a creature card from "
               "their graveyard to the battlefield.")
    io.on_cast_resolve(g, me, [])
    run(g)
    assert len(me.hand) == 2 and len(ops[0].hand) == 2
    assert any(x.name == "Back" for x in me.battlefield) and any(x.name in ("Theirs", "TheirBack")
                                                                 for x in ops[0].battlefield)


def test_intellectual_offering_both_parts():
    g, me, ops = new_game()
    a = put(g, artifact("Rock"), me)
    a.tapped = True
    io = build("Intellectual Offering", "{4}{U}", "Instant", "Choose an opponent. You and that player each draw three "
               "cards.\nChoose an opponent. Untap all nonland permanents you control and all nonland permanents that "
               "player controls.")
    io.on_cast_resolve(g, me, [])
    assert len(me.hand) == 3 and not a.tapped


def test_endless_detour_graveyard_card_human_bottom():
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = 0
    x = creature("Gy", "G", 1, 1)
    ops[0].graveyard.append(x)
    ed = build("Endless Detour", "{G}{W}{U}", "Instant", "The owner of target spell, nonland permanent, or card in a "
               "graveyard puts it on their choice of the top or bottom of their library.")
    ed.on_cast_resolve(g, me, [])
    _choose(g, "Gy · cementerio")
    assert x not in ops[0].graveyard and ops[0].library[-1] is x       # el bot dueño lo deja arriba


def test_grave_sifter_human_picks_type_and_cards():
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = 0
    e1, e2 = creature("E1", "G", 1, 1, subtypes=("Elf",)), creature("E2", "G", 1, 1, subtypes=("Elf",))
    z = creature("Z", "B", 2, 2, subtypes=("Zombie",))
    me.graveyard += [e1, e2, z]
    put(g, build("Grave Sifter", "{5}{G}", "Creature — Elemental Beast", "When this creature enters, each player chooses a "
                 "creature type and returns any number of cards of that type from their graveyard to their hand.", 5, 7),
        me)
    _choose(g, "Zombie")
    _choose(g, "Z")
    assert z in me.hand and e1 in me.graveyard


def test_coram_casts_milled_card_from_any_graveyard():
    g, me, ops = new_game()
    g.active_index = 0
    co = put(g, build("Coram, the Undertaker", "{1}{B}{R}{G}", "Legendary Creature — Human Warrior", "Coram gets +X/+0, "
                      "where X is the greatest power among creature cards in all graveyards.\nWhenever Coram attacks, "
                      "each player mills a card.\nDuring each of your turns, you may play a land and cast a spell from "
                      "among cards in graveyards that were put there from libraries this turn.", 0, 5), me)
    bear = creature("Bear", "1G", 2, 2)
    ops[0].library.append(bear)
    g._lib_snap = {id(c) for pl in g.players for c in pl.library}
    import cards
    cards.mill(g, ops[0], 1)
    run(g)
    assert bear in me.exile_play
    give_lands(g, me, 2)
    assert g.play_from_exile(me, bear)
    run(g)
    assert any(x.name == "Bear" for x in me.battlefield) and bear not in ops[0].graveyard and co is not None


def test_eidolon_bestowed_bonus():
    g, me, ops = new_game()
    e = build("Eidolon of Countless Battles", "{1}{W}{W}", "Enchantment Creature — Spirit", "Bestow {2}{W}{W}\nThis "
              "creature and enchanted creature each get +1/+1 for each creature you control and +1/+1 for each Aura "
              "you control.", 0, 0)
    assert e.bestow_static is not None


def test_multikicker_comet_storm_counts_kicks():
    g, me, ops = new_game(2)
    cs = build("Comet Storm", "{X}{R}{R}", "Instant", "Multikicker {1}\nChoose any target, then choose another target for "
               "each time this spell was kicked. Comet Storm deals X damage to each of them.")
    g.spell_x = 2
    cs._kick_n = 2
    l0, l1 = ops[0].life, ops[1].life
    cs.on_cast_resolve(g, me, [])
    assert ops[0].life == l0 - 2 and ops[1].life == l1 - 2


def test_stalking_leonin_human_chooses_attacker():
    g, me, ops = new_game()
    g.interactive_human = me
    sl = put(g, build("Stalking Leonin", "{2}{W}", "Creature — Cat Archer", "When this creature enters, secretly choose "
                      "an opponent.\nReveal the player you chose: Exile target creature that's attacking you if it's "
                      "controlled by the chosen player. Activate only once.", 3, 3), me)
    sl._leonin_opp = ops[0]
    g.pending_choice = None
    a1 = put(g, creature("Big", "G", 5, 5), ops[0])
    a2 = put(g, creature("Small", "G", 1, 1), ops[0])
    for a in (a1, a2):
        a.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    g._declare_attackers(ops[0], [(a1, me), (a2, me)])
    while g.choice_queue:
        g.choice_queue.pop(0)()
        if g.pending_choice:
            break
    _choose(g, "Small")
    assert a2 not in ops[0].battlefield and a1 in ops[0].battlefield


def test_garna_returns_discarded_creatures():
    g, me, ops = new_game()
    c = creature("Disc", "G", 2, 2)
    g.discard_card(me, c)
    run(g)
    put(g, build("Garna, the Bloodflame", "{3}{B}{R}", "Legendary Creature — Human Warrior", "Flash\nWhen Garna enters, "
                 "return to your hand all creature cards in your graveyard that were put there from anywhere this "
                 "turn.\nOther creatures you control have haste.", 3, 3), me)
    assert c in me.hand


def test_vela_triggers_on_bounce():
    g, me, ops = new_game()
    put(g, build("Vela the Night-Clad", "{4}{U}{B}", "Legendary Creature — Human Wizard", "Intimidate\nOther creatures you "
                 "control have intimidate.\nWhenever Vela or another creature you control leaves the battlefield, each "
                 "opponent loses 1 life.", 4, 4), me)
    c = put(g, creature("C", "G", 2, 2), me)
    import cardsdb
    l0 = ops[0].life
    cardsdb._bounce_pm(g, c)
    run(g)
    assert ops[0].life == l0 - 1


def test_marisi_blocks_spells_in_combat():
    g, me, ops = new_game()
    put(g, build("Marisi, Breaker of the Coil", "{1}{R}{G}{W}", "Legendary Creature — Cat Warrior", "Your opponents can't "
                 "cast spells during combat.\nWhenever a creature you control deals combat damage to a player, goad "
                 "each creature that player controls.", 5, 4), me)
    give_lands(g, ops[0], 2, colors=(R,))
    sh = build("Shock", "{R}", "Instant", "Shock deals 2 damage to any target.")
    ops[0].hand.append(sh)
    g._combat_on = True
    assert g.cast(ops[0], sh, targets=[me]) is False
    g._combat_on = False


def test_lier_grants_flashback():
    g, me, ops = new_game()
    put(g, build("Lier, Disciple of the Drowned", "{3}{U}{U}", "Legendary Creature — Human Wizard", "Spells can't be "
                 "countered.\nEach instant and sorcery card in your graveyard has flashback. The flashback cost is "
                 "equal to that card's mana cost.", 3, 4), me)
    dv = build("Divination", "{2}{U}", "Sorcery", "Draw two cards.")
    me.graveyard.append(dv)
    give_lands(g, me, 3, colors=(U,))
    g.active_index = 0
    assert g.gy_play_of(me, dv).get("mode") == "flashback"
    assert g.play_from_graveyard(me, dv)
    run(g)
    assert dv in me.exile and len(me.hand) == 2


def test_archangel_of_tithes_block_tax():
    g, me, ops = new_game()
    ang = put(g, build("Archangel of Tithes", "{1}{W}{W}{W}", "Creature — Angel", "Flying\nAs long as this creature is "
                       "untapped, creatures can't attack you or planeswalkers you control unless their controller pays "
                       "{1} for each of those creatures.\nAs long as this creature is attacking, creatures can't block "
                       "unless their controller pays {1} for each of those creatures.", 3, 5), me)
    bl = put(g, creature("Bl", "G", 2, 5, kw=("reach",)), ops[0])
    ang.attacking = ops[0]
    g._apply_block_pairs([ang], [(ang, bl)])
    assert bl not in ang.blocked_by           # sin maná para pagar
    give_lands(g, ops[0], 1)
    g._apply_block_pairs([ang], [(ang, bl)])
    assert bl in ang.blocked_by


def test_rat_offering():
    g, me, ops = new_game()
    pn = build("Patron of the Nezumi", "{5}{B}{B}", "Legendary Creature — Spirit", "Rat offering (You may cast this spell "
               "any time you could cast an instant by sacrificing a Rat and paying the difference in mana costs between "
               "this and the sacrificed Rat. Mana cost includes color.)\nWhenever a permanent is put into an opponent's "
               "graveyard, that player loses 1 life.", 6, 6)
    assert pn.offering_sub == "Rat"
    rat = put(g, build("Rat", "{1}{B}", "Creature — Rat", "", 1, 1), me)
    give_lands(g, me, 5, colors=(B,))
    me.hand.append(pn)
    g.active_index = 0
    opt = g.offering_option(me, pn)
    assert opt is not None and opt[1].cmc == 5
    assert g.cast_offering(me, pn)
    run(g)
    assert rat not in me.battlefield and any(x.name == "Patron of the Nezumi" for x in me.battlefield)


def test_fallen_shinobi_play_until_end_of_turn():
    g, me, ops = new_game()
    fs = put(g, build("Fallen Shinobi", "{3}{U}{B}", "Creature — Zombie Ninja", "Ninjutsu {2}{U}{B}\nWhenever this "
                      "creature deals combat damage to a player, that player exiles the top two cards of their library. "
                      "Until end of turn, you may play those cards without paying their mana costs.", 5, 4), me)
    ops[0].library += [creature("Big", "6G", 7, 7), land("Swamp", [B], basic=True)]
    fs.summoning_sick = False
    g.active_index = 0
    decl = g._declare_attackers(me, [(fs, ops[0])])
    g._finish_combat(decl)
    run(g)
    big = next(c for c in me.exile_play if c.name == "Big")
    assert g.play_from_exile(me, big)
    run(g)
    assert any(x.name == "Big" for x in me.battlefield)
    sw = next(c for c in me.exile_play if c.name == "Swamp")
    g.end_turn(me)
    assert sw not in me.exile_play and sw in ops[0].exile


def test_gahiji_any_creature_attacking_your_opponent():
    g, me, ops = new_game(2)
    put(g, build("Gahiji, Honored One", "{2}{R}{G}{W}", "Legendary Creature — Beast", "Whenever a creature attacks one of "
                 "your opponents or a planeswalker an opponent controls, that creature gets +2/+0 until end of turn.",
                 4, 4), me)
    a = put(g, creature("A", "G", 1, 1), ops[0])
    a.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    g._declare_attackers(ops[0], [(a, ops[1])])
    run(g)
    assert a.power == 3


def test_breena():
    g, me, ops = new_game(2)
    put(g, build("Breena, the Demagogue", "{1}{W}{B}", "Legendary Creature — Bird Warlock", "Flying\nWhenever a player "
                 "attacks one of your opponents, if that opponent has more life than another of your opponents, that "
                 "attacking player draws a card and you put two +1/+1 counters on a creature you control.", 1, 3), me)
    ops[1].life = 30
    a = put(g, creature("A", "G", 1, 1), ops[1])
    a.summoning_sick = False
    ops[0].life = 35
    g.active_index = g.players.index(ops[1])
    h = len(ops[1].hand)
    g._declare_attackers(ops[1], [(a, ops[0])])
    run(g)
    assert len(ops[1].hand) == h + 1 and any(x.counters.get("+1/+1") == 2 for x in me.battlefield)


def test_assault_suit_restrictions():
    g, me, ops = new_game()
    su = put(g, build("Assault Suit", "{4}", "Artifact — Equipment", "Equipped creature gets +2/+2, has haste, can't "
                      "attack you or planeswalkers you control, and can't be sacrificed.\nAt the beginning of each "
                      "opponent's upkeep, you may have that player gain control of equipped creature until end of turn. "
                      "If you do, untap it.\nEquip {3}"), me)
    c = put(g, creature("C", "G", 2, 2), me)
    su.enchanting = c
    g.to_graveyard(c, "sacrificio")
    assert c in me.battlefield
    g.emit("each_upkeep", active=ops[0])
    run(g)
    g.active_index = g.players.index(ops[0])
    c.summoning_sick = False
    assert g._declare_attackers(ops[0], [(c, me)]) == []


def test_spectacular_showdown_overload():
    g, me, ops = new_game()
    sd = build("Spectacular Showdown", "{1}{R}", "Sorcery", "Put a double strike counter on target creature, then goad "
               "each creature that had a double strike counter put on it this way.\nOverload {4}{R}{R}{R}")
    a = put(g, creature("A", "G", 1, 1), ops[0])
    b = put(g, creature("B", "G", 1, 1), me)
    sd.overload_effect(g, me, [])
    assert a.has("double_strike") and b.has("double_strike") and a.goaded


def test_skeletal_scrying_exiles_as_cost():
    g, me, ops = new_game()
    sk = build("Skeletal Scrying", "{X}{B}", "Instant", "As an additional cost to cast this spell, exile X cards from "
               "your graveyard.\nYou draw X cards and you lose X life.")
    me.graveyard += [land("F", [G], basic=True) for _ in range(2)]
    give_lands(g, me, 6, colors=(B,))
    me.hand.append(sk)
    g.active_index = 0
    l0 = me.life
    g.cast(me, sk)
    run(g)
    assert me.life == l0 - 2 and len(me.exile) == 2      # X limitado por el cementerio


def test_domineering_will_forces_block():
    g, me, ops = new_game(2)
    t = put(g, creature("T", "G", 2, 2), ops[1])
    dw = build("Domineering Will", "{3}{U}", "Instant", "Target player gains control of up to three target nonattacking "
               "creatures until end of turn. Untap those creatures. They block this turn if able.")
    a = put(g, creature("A", "G", 5, 5), ops[0])
    a.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    a.attacking = me
    dw.on_cast_resolve(g, me, [])
    assert t in me.battlefield and t._mb_turn == g.turn
    g._after_blocks([a])
    assert t in a.blocked_by                  # bloquea aunque pierda (debe bloquear si puede)


def test_massacre_girl_continues_after_leaving():
    g, me, ops = new_game()
    a = put(g, creature("A", "G", 1, 1), ops[0])
    b = put(g, creature("B", "G", 2, 2), ops[0])
    c = put(g, creature("C", "G", 3, 3), ops[0])
    mg = put(g, build("Massacre Girl", "{3}{B}{B}", "Legendary Creature — Human Assassin", "Menace\nWhen Massacre Girl "
                      "enters, each other creature gets -1/-1 until end of turn. Whenever a creature dies this turn, "
                      "each creature other than Massacre Girl gets -1/-1 until end of turn.", 4, 4), me)
    run(g)
    assert a not in ops[0].battlefield and b not in ops[0].battlefield
    assert c not in ops[0].battlefield and mg in me.battlefield


def test_robe_of_the_archmagi_restricted_equip():
    g, me, ops = new_game()
    rb = build("Robe of the Archmagi", "{2}{U}", "Artifact — Equipment", "Whenever equipped creature deals combat damage "
               "to a player, you draw that many cards.\nEquip Shaman, Warlock, or Wizard {1}\nEquip {6}")
    labels = [ab["label"] for ab in rb.activated_abilities]
    assert "Equipar (Shaman/Warlock/Wizard)" in labels


def test_killer_service_rhino():
    g, me, ops = new_game()
    ks = put(g, build("Killer Service", "{2}{G}", "Enchantment", "When this enchantment enters, create a number of Food "
                      "tokens equal to the number of opponents you have.\nAt the beginning of your end step, you may pay "
                      "{2} and sacrifice a token. If you do, create a 4/4 green Rhino Warrior creature token."), me)
    give_lands(g, me, 2)
    g.emit("end_step", player=me)
    run(g)
    assert any(x.name == "Rhino Warrior" for x in me.battlefield) and ks in me.battlefield
