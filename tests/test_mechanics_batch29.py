"""Batch 29: cartas frecuentes de precons con líneas sin simular (Myr Battlesphere,
Martial Impetus, Duplicant, Rite of the Raging Storm, Dream Pillager, Selfless Squire,
Door of Destinies, Enduring Scalelord, Thunderbreak Regent, Hydroid Krasis, Whispersilk…)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _attack(g, me, pairs):
    g.active_index = g.players.index(me)
    for pm, _d in pairs:
        pm.summoning_sick = False
    g._declare_attackers(me, pairs)
    run(g)


def test_myr_battlesphere_taps_myr_for_damage():
    g, me, ops = new_game()
    bs = put(g, build("Myr Battlesphere", "{7}", "Artifact Creature — Myr Construct", "Whenever this creature attacks, "
                      "you may tap X untapped Myr you control. If you do, this creature gets +X/+0 until end of turn "
                      "and deals X damage to the player or planeswalker it's attacking.", 4, 7), me)
    myrs = [put(g, build("Myr", "{1}", "Artifact Creature — Myr", "", 1, 1), me) for _ in range(3)]
    life = ops[0].life
    _attack(g, me, [(bs, ops[0])])
    assert all(m.tapped for m in myrs) and bs.power == 7 and ops[0].life == life - 3


def test_martial_impetus_pumps_other_attackers():
    g, me, ops = new_game()
    a = put(g, creature("A", "1R", 2, 2), me)
    b = put(g, creature("B", "1R", 2, 2), me)
    mi = put(g, build("Martial Impetus", "{2}{W}", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets "
                      "+1/+1 and is goaded.\nWhenever enchanted creature attacks, each other creature that's attacking "
                      "one of your opponents gets +1/+1 until end of turn."), me)
    mi.enchanting = a
    _attack(g, me, [(a, ops[0]), (b, ops[0])])
    assert b.power == 3


def test_duplicant_copies_pt_and_rite_tokens_cant_attack_owner():
    g, me, ops = new_game()
    foe = put(g, creature("Big", "5G", 7, 6), ops[0])
    d = put(g, build("Duplicant", "{6}", "Artifact Creature — Shapeshifter", "Imprint — When this creature enters, you "
                     "may exile target nontoken creature.\nAs long as a card exiled with this creature is a creature "
                     "card, this creature has the power, toughness, and creature types of the last creature card "
                     "exiled with it. It's still a Shapeshifter.", 2, 4), me)
    assert foe not in ops[0].battlefield and (d.power, d.toughness) == (7, 6)
    g, me, ops = new_game()
    put(g, build("Rite of the Raging Storm", "{3}{R}{R}", "Enchantment", "Creatures named Lightning Rager can't "
                 "attack you or planeswalkers you control.\nAt the beginning of each player's upkeep, that player "
                 "creates a 5/1 red Elemental creature token named Lightning Rager. It has trample, haste, and \"At "
                 "the beginning of the end step, sacrifice this token.\""), me)
    g.emit("each_upkeep", active=ops[0])
    run(g)
    rag = next(pm for pm in ops[0].battlefield if pm.name == "Lightning Rager")
    assert rag.has("trample") and rag.has("haste")
    life = me.life
    g.active_index = g.players.index(ops[0])
    rag.summoning_sick = False
    g._declare_attackers(ops[0], [(rag, me)])
    run(g)
    assert rag.attacking is None and me.life == life


def test_dream_pillager_and_selfless_squire():
    g, me, ops = new_game()
    dp = put(g, build("Dream Pillager", "{5}{R}{R}", "Creature — Dragon", "Flying\nWhenever this creature deals combat "
                      "damage to a player, exile that many cards from the top of your library. Until end of turn, you "
                      "may cast spells from among those exiled cards.", 4, 4), me)
    g._run_trigger(dp.card.triggers["combat_damage_to_player"], dp, {"defender": ops[0], "amount": 4})
    assert len(me.impulse) == 4
    g, me, ops = new_game()
    sq = put(g, build("Selfless Squire", "{3}{W}", "Creature — Human Soldier", "Flash\nWhen this creature enters, "
                      "prevent all damage that would be dealt to you this turn.\nWhenever damage that would be dealt "
                      "to you is prevented, put that many +1/+1 counters on this creature.", 1, 1), me)
    me.prevent_all = True
    g.deal_damage(None, me, 5)
    run(g)
    assert me.life == 40 and sq.counters.get("+1/+1") == 5


def test_door_scalelord_thunderbreak():
    g, me, ops = new_game()
    dd = put(g, build("Door of Destinies", "{4}", "Artifact", "As this artifact enters, choose a creature type.\n"
                      "Whenever you cast a spell of the chosen type, put a charge counter on this artifact.\nCreatures "
                      "you control of the chosen type get +1/+1 for each charge counter on this artifact."), me)
    dd.chosen_type = "Elf"
    elf = put(g, build("Elf", "{G}", "Creature — Elf", "", 1, 1), me)
    g.emit("cast", player=me, card=build("Elf2", "{G}", "Creature — Elf", "", 1, 1))
    run(g)
    assert dd.counters.get("charge") == 1 and elf.power == 2
    sl = put(g, build("Enduring Scalelord", "{4}{G}{W}", "Creature — Dragon", "Flying\nWhenever one or more +1/+1 "
                      "counters are put on another creature you control, you may put a +1/+1 counter on this "
                      "creature.", 4, 4), me)
    g.add_counters(elf, "+1/+1", 2)
    run(g)
    assert sl.counters.get("+1/+1") == 1
    tb = put(g, build("Thunderbreak Regent", "{2}{R}{R}", "Creature — Dragon", "Flying\nWhenever a Dragon you control "
                      "becomes the target of a spell or ability an opponent controls, this creature deals 3 damage to "
                      "that player.", 4, 4), me)
    life = ops[0].life
    g._targeted_triggers(ops[0], [tb], spell=True)
    run(g)
    assert ops[0].life == life - 3


def test_krasis_biomass_nighthawk_whispersilk_idol():
    g, me, ops = new_game()
    hk = build("Hydroid Krasis", "{X}{G}{U}", "Creature — Jellyfish Hydra Beast", "When you cast this spell, you gain "
               "half X life and draw half X cards. Round down each time.\nFlying, trample\nThis creature enters with "
               "X +1/+1 counters on it.", 0, 0)
    hk._cast_x = 5
    me.library = [land("F", [G], basic=True) for _ in range(5)]
    hk.cast_trigger(g, me)
    assert me.life == 42 and len(me.hand) == 2
    bm = build("Biomass Mutation", "{X}{G/U}{G/U}", "Instant", "Creatures you control have base power and toughness "
               "X/X until end of turn.")
    c = put(g, creature("C", "G", 1, 1), me)
    g.spell_x = 6
    bm.on_cast_resolve(g, me, [])
    assert (c.power, c.toughness) == (6, 6)
    nh = put(g, build("Nighthawk Scavenger", "{1}{B}{B}", "Creature — Vampire Rogue", "Flying, deathtouch, lifelink\n"
                      "Nighthawk Scavenger's power is equal to 1 plus the number of card types among cards in your "
                      "opponents' graveyards.", 1, 3), me)
    ops[0].graveyard = [creature("D", "B", 1, 1), land("L", [B], basic=True)]
    assert nh.power == 3
    wc = put(g, build("Whispersilk Cloak", "{3}", "Artifact — Equipment", "Equipped creature can't be blocked and has "
                      "shroud.\nEquip {2}"), me)
    wc.enchanting = c
    assert c.has("unblockable") and c.has("shroud")
    idol = build("Idol of Oblivion", "{2}", "Artifact", "{T}: Draw a card. Activate only if you created a token this "
                 "turn.\n{8}, {T}, Sacrifice this artifact: Create a 10/10 colorless Eldrazi creature token.")
    ab = idol.activated_abilities[0]
    assert ab.get("only_if") is not None and not ab["only_if"](g, me)
    import cards as C
    C.make_token(g, me, "Tok", 1, 1)
    assert ab["only_if"](g, me)


def test_war_room_heirloom_maskwood_puresteel():
    g, me, ops = new_game()
    wr = build("War Room", "", "Land", "{T}: Add {C}.\n{3}, {T}, Pay life equal to the number of colors in your "
               "commanders' color identity: Draw a card.")
    assert any(ab.get("pay_life") == "cmd_colors" for ab in wr.activated_abilities)
    hb = put(g, build("Heirloom Blade", "{3}", "Artifact — Equipment", "Equipped creature gets +3/+1.\nWhenever "
                      "equipped creature dies, you may reveal cards from the top of your library until you reveal a "
                      "creature card that shares a creature type with it. Put that card into your hand and the rest "
                      "on the bottom of your library in a random order.\nEquip {1}"), me)
    elf = put(g, build("Elf", "{G}", "Creature — Elf Warrior", "", 1, 1), me)
    hb.enchanting = elf
    me.library = [build("Elf Two", "{G}", "Creature — Elf", "", 1, 1), land("F", [G], basic=True)]
    g.destroy(elf, "test")
    run(g)
    assert [c.name for c in me.hand] == ["Elf Two"]
    put(g, build("Maskwood Nexus", "{4}", "Artifact", "Creatures you control are every creature type. The same is true "
                 "for creature spells you control and creature cards you own that aren't on the battlefield.\n{3}, {T}: "
                 "Create a 2/2 blue Shapeshifter creature token with changeling."), me)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    assert bear.has_subtype("Dragon") and bear.has_subtype("Elf")
    g, me, ops = new_game()
    put(g, build("Puresteel Paladin", "{W}{W}", "Creature — Human Knight", "Whenever an Equipment you control enters, "
                 "you may draw a card.\nMetalcraft — Equipment you control have equip {0} as long as you control three "
                 "or more artifacts.", 2, 2), me)
    eqs = [put(g, build(f"Eq{i}", "{1}", "Artifact — Equipment", "Equipped creature gets +1/+0.\nEquip {3}"), me)
           for i in range(3)]
    tgt = put(g, creature("T", "1W", 2, 2), me)
    g.active_index = g.players.index(me)
    assert g.activate_ability(eqs[0], 0, targets=[tgt])       # sin maná: equip {0}


def test_blink_gy_exile_and_mystic_forge():
    g, me, ops = new_game()
    ops[0].graveyard = [creature("Dead", "B", 1, 1)]
    put(g, build("Hedonist's Trove", "{5}{B}{B}", "Enchantment", "When this enchantment enters, exile target "
                 "opponent's graveyard."), me)
    assert not ops[0].graveyard
    me.graveyard = [creature("Mine", "G", 1, 1)]
    pg = build("Purify the Grave", "{W}", "Instant", "Exile target card from a graveyard.\nFlashback {W}")
    pg.on_cast_resolve(g, me, [])
    assert ops[0].exile or len(me.exile) == 1
    mf = put(g, build("Mystic Forge", "{4}", "Artifact", "You may look at the top card of your library any time.\nYou "
                      "may cast artifact spells and colorless spells from the top of your library.\n{T}, Pay 1 life: "
                      "Exile the top card of your library."), me)
    me.library = [build("Rock", "{2}", "Artifact", "{T}: Add {C}.")]
    assert g.castable_from_top(me) is not None
    me.library = [creature("Bear", "1G", 2, 2)]
    assert g.castable_from_top(me) is None and mf


def test_kaalia_myriad_liege_patron():
    g, me, ops = new_game(2)
    k = put(g, build("Kaalia of the Vast", "{1}{R}{W}{B}", "Legendary Creature — Human Cleric", "Flying\nWhenever Kaalia "
                     "attacks an opponent, you may put an Angel, Demon, or Dragon creature card from your hand onto the "
                     "battlefield tapped and attacking that opponent.", 2, 2), me)
    me.hand = [build("Big Dragon", "{6}{R}", "Creature — Dragon", "Flying", 6, 6), creature("Elf", "G", 1, 1)]
    life = ops[0].life
    g.active_index = 0
    k.summoning_sick = False
    decl = g._declare_attackers(me, [(k, ops[0])])
    drg = next(pm for pm in me.battlefield if pm.name == "Big Dragon")
    assert drg.attacking is ops[0] and drg in decl
    put(g, build("Legion Loyalty", "{6}", "Enchantment", "Creatures you control have myriad."), me)
    assert k.has("myriad")
    ml = put(g, build("Murkfiend Liege", "{2}{G/U}{G/U}{G/U}", "Creature — Merfolk", "Other green creatures you "
                      "control get +1/+1.\nOther blue creatures you control get +1/+1.\nUntap all green and/or blue "
                      "creatures you control during each other player's untap step.", 4, 4), me)
    gr = put(g, creature("Gr", "1G", 2, 2), me)
    gr.tapped = True
    g.emit("each_upkeep", active=ops[0])
    run(g)
    assert not gr.tapped and ml
    pv = put(g, build("Patron of the Vein", "{4}{B}{B}", "Creature — Vampire Shaman", "Flying\nWhen Patron of the Vein "
                      "enters, destroy target creature an opponent controls.\nWhenever a creature an opponent controls "
                      "dies, exile it and put a +1/+1 counter on each Vampire you control.", 4, 4), me)
    run(g)
    v = put(g, build("Vamp", "{B}", "Creature — Vampire", "", 1, 1), me)
    foe = put(g, creature("Foe", "1G", 2, 2), ops[1])
    c0 = v.counters.get("+1/+1", 0)
    g.destroy(foe, "t")
    run(g)
    assert v.counters.get("+1/+1", 0) == c0 + 1 and any(c.name == "Foe" for c in ops[1].exile) and pv


def test_mazemind_goreclaw_flail_hammer():
    g, me, ops = new_game()
    mt = put(g, build("Mazemind Tome", "{2}", "Artifact", "{T}, Put a page counter on this artifact: Scry 1.\n{2}, {T}, "
                      "Put a page counter on this artifact: Draw a card.\nWhen there are four or more page counters on "
                      "this artifact, exile it. If you do, you gain 4 life."), me)
    for _ in range(4):
        g.add_counters(mt, "page", 1)
    assert mt not in me.battlefield and me.life == 44
    gc = build("Goreclaw, Terror of Qal Sisma", "{3}{G}", "Legendary Creature — Bear", "Creature spells you cast with "
               "power 4 or greater cost {2} less to cast.\nWhenever Goreclaw attacks, each creature you control with "
               "power 4 or greater gets +1/+1 and gains trample until end of turn.", 4, 3)
    put(g, gc, me)
    assert g.effective_cost(me, creature("Fat", "5G", 5, 5)).generic == 3
    g, me, ops = new_game()
    fl = put(g, build("Conqueror's Flail", "{2}", "Artifact — Equipment", "Equipped creature gets +1/+1 for each color "
                      "among permanents you control.\nAs long as this Equipment is attached to a creature, your "
                      "opponents can't cast spells during your turn.\nEquip {2}"), me)
    assert fl.card.opp_no_cast_your_turn and fl.card.ncast_attached
    x = put(g, creature("X", "1G", 3, 3), me)
    put(g, build("Hammer of Nazahn", "{4}", "Legendary Artifact — Equipment", "Whenever Hammer of Nazahn or another "
                 "Equipment you control enters, you may attach that Equipment to target creature you control.\n"
                 "Equipped creature gets +2/+0 and has indestructible.\nEquip {4}"), me)
    run(g)
    assert any(pm.enchanting is x for pm in me.battlefield if pm.name == "Hammer of Nazahn")


def test_apex_devastator_cascades_four_times_on_cast():
    g, me, ops = new_game()
    give_lands(g, me, 10, colors=(G,))
    ad = build("Apex Devastator", "{8}{G}{G}", "Creature — Chimera Hydra", "Cascade, cascade, cascade, cascade (When "
               "you cast this spell, exile cards from the top of your library until you exile a nonland card that "
               "costs less. You may cast it without paying its mana cost. Put the exiled cards on the bottom in a "
               "random order. Multiple instances of cascade each trigger separately.)", 10, 10)
    me.library = [creature(f"C{i}", "2G", 2, 2) for i in range(6)] + [land("F", [G], basic=True) for _ in range(3)]
    me.hand.append(ad)
    g.active_index = g.players.index(me)
    assert g.cast(me, ad)
    run(g)
    assert sum(1 for pm in me.battlefield if pm.name.startswith("C")) == 4
    assert any(pm.name == "Apex Devastator" for pm in me.battlefield)


def test_jyoti_dryads_and_combat_pump():
    g, me, ops = new_game()
    me.cmdr_taxes = [4]                               # lanzó su comandante 2 veces
    j = put(g, build("Jyoti, Moag Ancient", "{3}{G}", "Legendary Creature — Elemental", "When Jyoti enters, create a "
                     "1/1 green Forest Dryad land creature token for each time you've cast your commander from the "
                     "command zone this game. (They're affected by summoning sickness.)\nAt the beginning of each "
                     "combat, land creatures you control get +X/+X until end of turn, where X is Jyoti's power.", 2, 4),
            me)
    dry = [pm for pm in me.battlefield if pm.name == "Forest Dryad"]
    assert len(dry) == 2 and all(pm.card.is_land() and pm.is_creature() for pm in dry)
    g.emit("each_combat", active=me)
    run(g)
    assert all((pm.power, pm.toughness) == (3, 3) for pm in dry) and (j.power, j.toughness) == (2, 4)


def test_propaganda_taxes_each_attacker_and_logs():
    g, me, ops = new_game()
    put(g, build("Propaganda", "{2}{U}", "Enchantment", "Creatures can't attack you unless their controller pays {2} "
                 "for each creature they control that's attacking you."), me)
    give_lands(g, ops[0], 2, colors=(R,))
    a1 = put(g, creature("A", "1R", 3, 3), ops[0])
    a2 = put(g, creature("B", "1R", 3, 3), ops[0])
    for x in (a1, a2):
        x.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    decl = g._declare_attackers(ops[0], [(a1, me), (a2, me)])
    assert len(decl) == 1                                    # solo pudo pagar una
    assert all(pm.tapped for pm in ops[0].battlefield if pm.card.is_land())
    assert any("paga {2} para atacar" in ln for ln in g.log_lines)
