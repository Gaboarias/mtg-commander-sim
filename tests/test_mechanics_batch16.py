"""Batch 16: staples de Commander de los precons (Chaos Warp, Living Death, Gray
Merchant, Duneblast, Rishkar's Expertise, Condemn, Victimize, barridos con X,
Seedborn Muse, Rites of Flourishing, Fog Bank, Champion of Lambholt, Caged Sun…)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_chaos_warp_and_living_death():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "4G", 5, 5), ops[0])
    ops[0].library.append(creature("Next", "1G", 1, 1))
    cw = build("Chaos Warp", "{2}{R}", "Instant", "The owner of target permanent shuffles it into their "
               "library, then reveals the top card of their library. If it's a permanent card, they put "
               "it onto the battlefield.")
    cw.on_cast_resolve(g, me, [])
    assert foe not in ops[0].battlefield
    g2, me2, ops2 = new_game()
    mine = put(g2, creature("Mine", "1G", 1, 1), me2)
    me2.graveyard.append(creature("BigDead", "6G", 6, 6))
    ld = build("Living Death", "{3}{B}{B}", "Sorcery", "Each player exiles all creature cards from their "
               "graveyard, then sacrifices all creatures they control, then puts all cards they exiled "
               "this way onto the battlefield.")
    ld.on_cast_resolve(g2, me2, [])
    names = {pm.name for pm in me2.battlefield}
    assert "BigDead" in names and mine not in me2.battlefield


def test_gray_merchant_and_duneblast():
    g, me, ops = new_game()
    for k in range(2):
        put(g, creature(f"Bk{k}", "BB", 2, 2), me)
    life, ol = me.life, ops[0].life
    put(g, build("Gary", "{3}{B}{B}", "Creature — Zombie", "When this creature enters, each opponent "
                 "loses X life, where X is your devotion to black. You gain life equal to the life lost "
                 "this way.", 2, 4), me)
    run(g)
    assert ops[0].life == ol - 6 and me.life == life + 6
    for k in range(3):
        put(g, creature(f"Op{k}", "1G", 3, 3), ops[0])
    db = build("Duneblast", "{4}{W}{B}{G}", "Sorcery", "Choose up to one creature. Destroy the rest.")
    db.on_cast_resolve(g, me, [])
    assert not ops[0].creatures() and len(me.creatures()) == 1


def test_rishkar_and_x_sweeper():
    g, me, ops = new_game()
    put(g, creature("Big", "4G", 6, 6), me)
    me.library += [creature(f"L{k}", "1G", 1, 1) for k in range(10)]
    me.hand = [creature("FreeOne", "4G", 5, 5)]
    rk = build("Rishkar's Expertise", "{4}{G}{G}", "Sorcery", "Draw cards equal to the greatest power "
               "among creatures you control.\nYou may cast a spell with mana value 5 or less from your "
               "hand without paying its mana cost.")
    rk.on_cast_resolve(g, me, [])
    run(g)
    assert any(pm.name == "FreeOne" for pm in me.battlefield)
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    g.spell_x = 3
    sw = build("Starstorm", "{X}{R}{R}", "Instant", "Starstorm deals X damage to each creature.")
    sw.on_cast_resolve(g, me, [])
    assert foe not in ops[0].battlefield


def test_condemn_and_victimize():
    g, me, ops = new_game()
    atk = put(g, creature("Atk", "4G", 5, 5), ops[0])
    atk.attacking = me
    life = ops[0].life
    cd = build("Condemn", "{W}", "Instant", "Put target attacking creature on the bottom of its owner's "
               "library. Its controller gains life equal to its toughness.")
    cd.on_cast_resolve(g, me, [])
    assert atk not in ops[0].battlefield and ops[0].life == life + 5 and ops[0].library[0].name == "Atk"
    tok = put(g, creature("Tok", "0", 1, 1), me)
    tok.is_token = True
    me.graveyard += [creature("D1", "5B", 5, 5), creature("D2", "4B", 4, 4)]
    vc = build("Victimize", "{2}{B}", "Sorcery", "Choose two target creature cards in your graveyard. "
               "Sacrifice a creature. If you do, return the chosen cards to the battlefield tapped.")
    vc.on_cast_resolve(g, me, [])
    names = {pm.name for pm in me.battlefield}
    assert {"D1", "D2"} <= names and tok not in me.battlefield


def test_seedborn_rites_fogbank_lambholt():
    g, me, ops = new_game()
    put(g, build("Seedborn", "{2}{G}", "Creature — Plant", "Untap all permanents you control during "
                 "each other player's untap step.", 2, 4), me)
    t = put(g, creature("T", "1G", 1, 1), me)
    t.tapped = True
    g.begin_turn(ops[0])
    assert not t.tapped
    put(g, build("Rites", "{2}{G}", "Enchantment", "Each player may play an additional land on each of "
                 "their turns."), me)
    assert g.land_limit(ops[0]) == 2
    fb = put(g, build("Fog Bank", "{1}{U}", "Creature — Wall", "Prevent all combat damage that would be "
                      "dealt to and dealt by this creature.", 0, 2), me)
    big = put(g, creature("Big", "4G", 5, 5), ops[0])
    g.deal_damage(big, fb, 5, combat=True)
    assert fb.damage == 0
    lam = put(g, build("Lambholt", "{1}{G}{G}", "Creature — Human", "Creatures with power less than this "
                       "creature's power can't block creatures you control.", 4, 4), me)
    small = put(g, creature("Small", "1W", 2, 2), ops[0])
    assert not g._can_block_evasion(t, small)


def test_caged_sun_and_herald_horn():
    g, me, ops = new_game()
    for k in range(2):
        put(g, creature(f"G{k}", "1G", 2, 2), me)
    put(g, build("Sun", "{6}", "Artifact", "As this artifact enters, choose a color.\nCreatures you "
                 "control of the chosen color get +1/+1."), me)
    assert all(pm.power == 3 for pm in me.creatures())
    hh = put(g, build("Horn", "{3}", "Artifact", "As this artifact enters, choose a creature type.\n"
                      "Creature spells you cast of the chosen type cost {1} less to cast."), me)
    hh.chosen_type = "Elf"
    elf = creature("Elfy", "2G", 2, 2, subtypes={"Elf"})
    assert g.effective_cost(me, elf).cmc == 2
    assert all(pm.power == 3 for pm in me.creatures())     # Horn no da anthem


def test_subtype_death_trigger_and_more_lands_condition():
    g, me, ops = new_game()
    om = put(g, build("Omnath, Locus of Rage", "{3}{R}{R}{G}{G}", "Legendary Creature — Elemental",
                      "Whenever Omnath or another Elemental you control dies, Omnath deals 3 damage to any "
                      "target.", 5, 5), me)
    el = put(g, creature("Ele", "1R", 1, 1, subtypes={"Elemental"}), me)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    ol = ops[0].life
    g.to_graveyard(bear, "test")
    run(g)
    assert ops[0].life == ol
    g.to_graveyard(el, "test")
    run(g)
    assert ops[0].life == ol - 3
    for k in range(3):
        put(g, land("Plains", [W], basic=True), ops[0])
    me.library.append(land("Plains", [W], basic=True))
    put(g, build("Knight", "{2}{W}", "Creature — Human Knight", "When this creature enters, if an opponent "
                 "controls more lands than you, you may search your library for a Plains card, put it "
                 "onto the battlefield, then shuffle.", 2, 2), me)
    run(g)
    assert any(pm.name == "Plains" for pm in me.battlefield)


def test_sacrifice_watch_and_monument():
    g, me, ops = new_game()
    put(g, build("Mazirek", "{3}{B}{G}", "Legendary Creature — Insect Shaman", "Whenever a player "
                 "sacrifices another permanent, put a +1/+1 counter on each creature you control.", 2, 2), me)
    t = put(g, creature("T", "1G", 1, 1), ops[0])
    g.to_graveyard(t, "sacrificio")
    run(g)
    assert all(pm.counters.get("+1/+1") == 1 for pm in me.creatures())


def test_activated_costs_subtype_sac_counters_tap_artifacts():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    sg = put(g, build("Siege-Gang", "{3}{R}{R}", "Creature — Human Warrior", "{1}{R}, Sacrifice a Goblin: "
                      "This creature deals 2 damage to any target.", 2, 2), me)
    gob = put(g, creature("Gob", "R", 1, 1, subtypes={"Goblin"}), me)
    assert sg.card.activated_abilities[0]["sacrifice_other"]["type"] == "goblin"
    ol = ops[0].life
    assert g.activate_ability(sg, 0, targets=[ops[0]]) is not False
    run(g)
    assert gob not in me.battlefield and ops[0].life == ol - 2
    wb = put(g, build("Wicker", "{3}{G}", "Creature — Treefolk", "{G}, Remove a +1/+1 counter from this "
                      "creature: Destroy target artifact or enchantment.", 4, 4), me)
    assert wb.card.activated_abilities[0]["rm_counter"] == {"name": "+1/+1", "n": 1}


def test_chain_reaction_and_snuff_out_and_dryad():
    g, me, ops = new_game()
    for k in range(3):
        put(g, creature(f"C{k}", "1G", 2, 3), ops[0])
    cr = build("Chain Reaction", "{2}{R}{R}", "Sorcery", "Chain Reaction deals X damage to each creature, where "
               "X is the number of creatures on the battlefield.")
    cr.on_cast_resolve(g, me, [])
    run(g)
    assert not ops[0].creatures()
    put(g, land("Swamp", [B], basic=True), me)
    me.battlefield[-1].tapped = True
    so = build("Snuff Out", "{3}{B}", "Instant", "If you control a Swamp, you may pay 4 life rather than pay "
               "this spell's mana cost.\nDestroy target nonblack creature. It can't be regenerated.")
    me.hand.append(so)
    put(g, creature("Foe", "1G", 2, 2), ops[0])
    life = me.life
    assert g.cast(me, so)
    run(g)
    assert me.life == life - 4
    fo = put(g, land("Forest", [G], basic=True), me)
    put(g, build("Dryad", "{1}{G}", "Enchantment Creature — Dryad", "Lands you control are every basic land "
                 "type in addition to their other types.", 2, 4), me)
    assert set(me.produced(fo)) == {"W", "U", "B", "R", "G"}


def test_conditional_anthem_and_dark_dwellers():
    g, me, ops = new_game()
    jk = put(g, build("Jor", "{3}{R}{W}", "Legendary Creature — Human", "Metalcraft — Creatures you control get "
                      "+3/+0 as long as you control three or more artifacts.", 2, 2), me)
    assert jk.power == 2
    for k in range(3):
        put(g, build(f"Rock{k}", "{1}", "Artifact", ""), me)
    assert jk.power == 5
    me.graveyard.append(build("Bolt", "{R}", "Instant", "Bolt deals 3 damage to any target."))
    ol = ops[0].life
    put(g, build("Dweller", "{4}{R}", "Creature — Goblin", "When this creature enters, you may cast target "
                 "instant or sorcery card with mana value 3 or less from your graveyard without paying its "
                 "mana cost. If that spell would be put into your graveyard, exile it instead.", 4, 4), me)
    run(g)
    assert ops[0].life == ol - 3 and any(c.name == "Bolt" for c in me.exile)
