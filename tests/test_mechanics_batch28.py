"""Batch 28: habilidades activables y de lealtad que se podían activar pero no hacían
nada (barrido de los precons): manlands/keyrunes, contadores sobre la fuente, modos de
habilidades activadas, encore, enderezar/destruir/anexar dirigidos, adapt, regenerar,
contadores en grupo y habilidades de lealtad masivas."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _act(g, pm, frag):
    i = next(k for k, ab in enumerate(pm.card.activated_abilities) if frag.lower() in ab["label"].lower())
    return g.activate_ability(pm, i)


def test_manland_keyrune_and_vehicle_animate():
    g, me, ops = new_game()
    cc = put(g, build("Colonnade", "", "Land", "{T}: Add {W} or {U}.\n{3}{W}{U}: Until end of turn, this land becomes a "
                      "4/4 white and blue Elemental creature with flying and vigilance. It's still a land."), me)
    cc.tapped = False
    give_lands(g, me, 5, colors=(W, U))
    assert _act(g, cc, "becomes")
    run(g)
    assert cc.is_creature() and (cc.power, cc.toughness) == (4, 4) and cc.has("flying") and cc.has("vigilance")
    g.delayed_end and [f(g) for f in list(g.delayed_end)]
    g, me, ops = new_game()
    kr = put(g, build("Keyrune", "{3}", "Artifact", "{T}: Add {U} or {B}.\n{U}{B}: This artifact becomes a 2/2 blue and "
                      "black Horror artifact creature until end of turn and can't be blocked this turn."), me)
    give_lands(g, me, 2, colors=(U, B))
    assert _act(g, kr, "becomes")
    run(g)
    assert kr.is_creature() and (kr.power, kr.toughness) == (2, 2) and kr.has("unblockable")


def test_storage_counter_modal_ability_and_encore_shape():
    g, me, ops = new_game()
    cr = put(g, build("Crucible", "", "Land", "{T}: Add {C}.\n{1}, {T}: Put a storage counter on this land."), me)
    give_lands(g, me, 1)
    assert _act(g, cr, "storage")
    assert cr.counters.get("storage") == 1
    g, me, ops = new_game()
    g.interactive_human = me
    br = put(g, build("Breya", "{W}{U}{B}{R}", "Legendary Artifact Creature — Human", "{2}, Sacrifice two artifacts: "
                      "Choose one —\n• Breya deals 3 damage to target player or planeswalker.\n• Target creature gets "
                      "-4/-4 until end of turn.\n• You gain 5 life.", 4, 4), me)
    for i in range(2):
        put(g, build(f"Art{i}", "{1}", "Artifact", ""), me)
    give_lands(g, me, 2)
    life = me.life
    assert _act(g, br, "choose one")
    run(g)
    assert g.pending_choice is not None and g.pending_choice["kind"] == "mode_choice"
    assert len(g.pending_choice["options"]) == 3
    g.pending_choice["_apply"](2)
    assert me.life == life + 5


def test_targeted_activations_arbor_elf_attrition_adapt_regen():
    g, me, ops = new_game()
    el = put(g, build("Arbor Elf", "{G}", "Creature — Elf Druid", "{T}: Untap target Forest.", 1, 1), me)
    el.summoning_sick = False
    f = land("Forest", [G], basic=True)
    f.subtypes = {"forest"}
    fp = put(g, f, me)
    fp.tapped = True
    assert g.activate_ability(el, 0)
    run(g)
    assert not fp.tapped
    g, me, ops = new_game()
    at = put(g, build("Attrition", "{1}{B}{B}", "Enchantment", "{B}, Sacrifice a creature: Destroy target nonblack "
                      "creature."), me)
    give_lands(g, me, 1, colors=(B,))
    put(g, creature("Fodder", "1G", 1, 1), me)
    w = put(g, creature("W", "1W", 3, 3), ops[0])
    bk = put(g, creature("Bk", "1B", 5, 5), ops[0])
    assert g.activate_ability(at, 0)
    run(g)
    assert w not in ops[0].battlefield and bk in ops[0].battlefield
    g, me, ops = new_game()
    bb = put(g, build("Biomancer", "{U}", "Creature — Human", "{1}{U}: Adapt 1.", 0, 1), me)
    give_lands(g, me, 4, colors=(U,))
    _act(g, bb, "adapt")
    run(g)
    _act(g, bb, "adapt")
    run(g)
    assert bb.counters.get("+1/+1") == 1                 # adapt no suma si ya tiene contadores
    rg = put(g, build("Skel", "{1}{B}", "Creature — Skeleton", "{B}: Regenerate it.", 1, 1), me)
    give_lands(g, me, 1, colors=(B,))
    _act(g, rg, "regenerate")
    run(g)
    assert rg.regen_shields == 1


def test_loyalty_mass_destroy_untap_and_lands():
    g, me, ops = new_game()
    el = put(g, build("Elspeth", "{4}{W}{W}", "Legendary Planeswalker — Elspeth", "+1: Create three 1/1 white Soldier "
                      "creature tokens.\n−3: Destroy all creatures with power 4 or greater."), me)
    el.counters["loyalty"] = 6
    big = put(g, creature("Big", "4G", 5, 5), ops[0])
    sm = put(g, creature("Sm", "1G", 2, 2), ops[0])
    g.active_index = g.players.index(me)
    assert g.activate_loyalty(el, 1)
    run(g)
    assert big not in ops[0].battlefield and sm in ops[0].battlefield
    g, me, ops = new_game()
    gk = put(g, build("Garruk", "{2}{G}{G}", "Legendary Planeswalker — Garruk", "+1: Untap two target lands."), me)
    gk.counters["loyalty"] = 3
    ls = give_lands(g, me, 3) or [pm for pm in me.battlefield if pm.card.is_land()]
    for pm in me.battlefield:
        if pm.card.is_land():
            pm.tapped = True
    g.active_index = g.players.index(me)
    assert g.activate_loyalty(gk, 0)
    run(g)
    assert sum(1 for pm in me.battlefield if pm.card.is_land() and not pm.tapped) == 2
    g, me, ops = new_game()
    wr = put(g, build("Wrenn", "{3}{G}{G}", "Legendary Planeswalker — Wrenn", "0: Put any number of land cards from your "
                      "hand onto the battlefield tapped."), me)
    wr.counters["loyalty"] = 5
    me.hand = [land("Forest", [G], basic=True), land("Forest2", [G], basic=True), creature("C", "1G", 1, 1)]
    g.active_index = g.players.index(me)
    assert g.activate_loyalty(wr, 0)
    run(g)
    assert len(me.hand) == 1 and sum(1 for pm in me.battlefield if pm.card.is_land()) == 2


def test_group_counters_and_subtype_pump():
    g, me, ops = new_game()
    ia = put(g, build("Aristocrat", "{B}", "Creature — Vampire", "{2}, Sacrifice a creature: Put a +1/+1 counter on each "
                      "Vampire you control.", 1, 1), me)
    v2 = put(g, creature("V2", "1B", 3, 3, subtypes=("Vampire",)), me)
    put(g, creature("Fod", "1G", 1, 1), me)
    give_lands(g, me, 2, colors=(B,))
    assert _act(g, ia, "counter")
    run(g)
    assert v2.counters.get("+1/+1") == 1 and ia.counters.get("+1/+1") == 1
    gb = put(g, build("Burrows", "", "Land", "{1}{R}, {T}: Target Goblin creature gets +2/+0 until end of turn."), me)
    gob = put(g, creature("Gob", "1R", 1, 1, subtypes=("Goblin",)), me)
    give_lands(g, me, 2, colors=(R,))
    assert _act(g, gb, "goblin")
    run(g)
    assert gob.power == 3
