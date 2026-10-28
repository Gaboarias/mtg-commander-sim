"""Batch 30: Coveted Jewel, Gisela, Veyran, Simic Ascendancy, Tomb Blade, Shard of the
Nightbringer, The World Tree, Goldspan Dragon, Cursed Mirror, Clever Concealment,
Resourceful Defense, Mimic Vat, Dread Return (flashback con sacrificio), Animate Dead (elige)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
import cards  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_coveted_jewel_changes_hands_when_unblocked():
    g, me, ops = new_game()
    jw = put(g, build("Coveted Jewel", "{6}", "Artifact", "When this artifact enters, draw three cards.\n{T}: Add three "
                      "mana of any one color.\nWhenever one or more creatures an opponent controls attack you and aren't "
                      "blocked, that player draws three cards and gains control of this artifact. Untap it."), me)
    a = put(g, creature("A", "1R", 2, 2), ops[0])
    a.summoning_sick = False
    ops[0].library = [land("M", [R], basic=True) for _ in range(5)]
    g.active_index = g.players.index(ops[0])
    decl = g._declare_attackers(ops[0], [(a, me)])
    g._finish_combat(decl)
    assert jw in ops[0].battlefield and len(ops[0].hand) == 3


def test_gisela_doubles_and_halves():
    g, me, ops = new_game()
    put(g, build("Gisela, Blade of Goldnight", "{4}{R}{R}{W}{W}", "Legendary Creature — Angel", "Flying, first strike\n"
                 "If a source would deal damage to an opponent or a permanent an opponent controls, that source deals "
                 "double that damage to that player or permanent instead.\nIf a source would deal damage to you or a "
                 "permanent you control, prevent half that damage, rounded up.", 5, 5), me)
    l0, m0 = ops[0].life, me.life
    g.deal_damage(None, ops[0], 3)
    g.deal_damage(None, me, 3)
    assert ops[0].life == l0 - 6 and me.life == m0 - 1


def test_simic_ascendancy_tomb_blade_shard():
    g, me, ops = new_game()
    sa = put(g, build("Simic Ascendancy", "{G}{U}", "Enchantment", "{1}{G}{U}: Put a +1/+1 counter on target creature "
                      "you control.\nWhenever one or more +1/+1 counters are put on a creature you control, put that "
                      "many growth counters on Simic Ascendancy.\nAt the beginning of your upkeep, if Simic Ascendancy "
                      "has twenty or more growth counters on it, you win the game."), me)
    c = put(g, creature("C", "1G", 1, 1), me)
    g.add_counters(c, "+1/+1", 20)
    assert sa.counters.get("growth") == 20
    g._run_trigger(sa.card.triggers["upkeep"], sa, {"player": me})
    assert all(o.lost for o in ops)
    g, me, ops = new_game()
    tb = put(g, build("Tomb Blade", "{3}", "Artifact Creature — Necron", "Whenever this creature deals combat damage to "
                      "a player, that player loses life equal to the number of creatures they control.", 3, 1), me)
    for i in range(3):
        put(g, creature(f"O{i}", "G", 1, 1), ops[0])
    l0 = ops[0].life
    g._run_trigger(tb.card.triggers["combat_damage_to_player"], tb, {"defender": ops[0], "amount": 3})
    assert ops[0].life == l0 - 3
    ops[0].life = 21
    put(g, build("Shard of the Nightbringer", "{4}{B}{B}", "Artifact Creature — Necron", "Drain Life — When this "
                 "creature enters, if you cast it, target opponent loses half their life, rounded up. You gain life "
                 "equal to the life lost this way.", 4, 4), me)
    assert ops[0].life == 10 and me.life == 51


def test_world_tree_goldspan_and_mirror():
    g, me, ops = new_game()
    for _ in range(6):
        put(g, land("Forest", [G], basic=True), me)
    put(g, build("The World Tree", "", "Land", "{T}: Add {G}.\nAs long as you control six or more lands, lands you "
                 "control have \"{T}: Add one mana of any color.\""), me)
    f = next(pm for pm in me.battlefield if pm.name == "Forest")
    assert set(me.produced(f)) == {"W", "U", "B", "R", "G"}
    put(g, build("Goldspan Dragon", "{3}{R}{R}", "Creature — Dragon", "Flying, haste\nWhenever this creature attacks or "
                 "becomes the target of a spell, create a Treasure token.\nTreasures you control have \"{T}, Sacrifice "
                 "this artifact: Add two mana of any one color.\"", 4, 4), me)
    tr = cards.make_resource_token(g, me, "treasure")
    tr = tr if tr is not None else next(pm for pm in me.battlefield if pm.name == "Treasure")
    assert max(me.produced(tr).values()) == 2
    g, me, ops = new_game()
    put(g, creature("Big", "4G", 6, 6), ops[0])
    cm = put(g, build("Cursed Mirror", "{2}{R}", "Artifact", "{T}: Add {R}.\nAs this artifact enters, you may have it "
                      "become a copy of any creature on the battlefield until end of turn, except it has haste."), me)
    assert cm.name == "Big" and cm.has("haste")


def test_dread_return_flashback_sacrifice_and_animate_dead_choice():
    g, me, ops = new_game()
    dr = build("Dread Return", "{2}{B}{B}", "Sorcery", "Return target creature card from your graveyard to the "
               "battlefield.\nFlashback—Sacrifice three creatures. (You may cast this card from your graveyard for its "
               "flashback cost. Then exile it.)")
    assert dr.gy_play.get("sac_n") == 3
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = g.players.index(me)
    me.graveyard = [creature("Small", "G", 1, 1), creature("Huge", "5G", 8, 8)]
    put(g, build("Animate Dead", "{1}{B}", "Enchantment — Aura", "Enchant creature card in a graveyard\nWhen Animate "
                 "Dead enters, if it's on the battlefield, it loses \"enchant creature card in a graveyard\" and gains "
                 "\"enchant creature put onto the battlefield with Animate Dead.\" Return enchanted creature card to the "
                 "battlefield under your control and attach Animate Dead to it. When Animate Dead leaves the "
                 "battlefield, that creature's controller sacrifices it.\nEnchanted creature gets -1/-0."), me)
    pc = g.pending_choice
    assert pc and any("Small" in o["name"] for o in pc["options"])
    idx = next(o["i"] for o in pc["options"] if "Small" in o["name"])
    g.pending_choice = None
    pc["_apply"](idx)
    assert any(pm.name == "Small" for pm in me.battlefield)


def test_forgotten_ancient_moves_counters_human():
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = g.players.index(me)
    fa = put(g, build("Forgotten Ancient", "{3}{G}", "Creature — Elemental", "Whenever a player casts a spell, you may "
                      "put a +1/+1 counter on this creature.\nAt the beginning of your upkeep, you may move any number of "
                      "+1/+1 counters from this creature onto other creatures.", 0, 3), me)
    x = put(g, creature("X", "1G", 2, 2), me)
    fa.counters["+1/+1"] = 3
    g._run_trigger(fa.card.triggers["upkeep"], fa, {"player": me})
    pc = g.pending_choice
    g.pending_choice = None
    pc["_apply"](next(o["i"] for o in pc["options"] if o["name"].startswith("X")))
    pc = g.pending_choice
    g.pending_choice = None
    pc["_apply"](next(o["i"] for o in pc["options"] if o["name"] == "2"))
    assert fa.counters["+1/+1"] == 1 and x.counters.get("+1/+1") == 2
