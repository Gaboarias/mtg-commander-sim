"""Batch 19: contadores escudo, impuesto de ataque dinámico, Razorjaw Oni, Tetsuko,
auras de tierra con habilidades, staples varios y cuerpos largos de disparos."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_shield_counters_prevent_damage_and_destroy():
    g, me, ops = new_game()
    a = put(g, creature("A", "1G", 2, 2), me)
    pm = build("Protection Magic", "{W}", "Instant", "Put a shield counter on each of up to three target creatures.")
    pm.on_cast_resolve(g, me, [])
    assert a.counters.get("shield") == 1
    g.deal_damage(None, a, 5)
    assert a.damage == 0 and a.counters.get("shield") == 0
    g.destroy(a, "test")
    assert a not in me.battlefield


def test_sphere_of_safety_razorjaw_tetsuko():
    g, me, ops = new_game()
    put(g, build("Sphere", "{4}{W}", "Enchantment", "Creatures can't attack you or planeswalkers you control unless "
                 "their controller pays {X} for each of those creatures, where X is the number of enchantments you "
                 "control."), me)
    put(g, build("Ench2", "{1}", "Enchantment", ""), me)
    assert g.attack_tax(me) == 2
    put(g, build("Razorjaw", "{3}{B}", "Creature — Demon Spirit", "Black creatures can't block.", 5, 3), me)
    bk = put(g, creature("Bk", "1B", 2, 2), ops[0])
    assert bk.cant_block
    put(g, build("Tetsuko", "{1}{U}", "Legendary Creature — Human Rogue", "Creatures you control with power or "
                 "toughness 1 or less can't be blocked.", 1, 3), me)
    small = put(g, creature("Small", "U", 1, 1), me)
    wall = put(g, creature("Wall", "1W", 0, 5), ops[0])
    assert not g._can_block_evasion(small, wall)


def test_land_aura_grants_ability_and_lurking_predators():
    g, me, ops = new_game()
    fo = put(g, land("Forest", [G], basic=True), me)
    put(g, build("Squirrel Nest", "{1}{G}{G}", "Enchantment — Aura", "Enchant land\nEnchanted land has "
                 "\"{T}: Create a 1/1 green Squirrel creature token.\""), me)
    idx = len(fo.card.activated_abilities) - 1
    assert idx >= 0 and g.activate_ability(fo, idx)
    run(g)
    assert any(pm.is_token for pm in me.battlefield)
    put(g, build("Lurking", "{4}{G}{G}", "Enchantment", "Whenever an opponent casts a spell, reveal the top card of "
                 "your library. If it's a creature card, put it onto the battlefield. Otherwise, you may put that card "
                 "on the bottom of your library."), me)
    me.library.append(creature("Free", "5G", 5, 5))
    g.emit("opp_cast", caster=ops[0], card=creature("X", "1R", 1, 1))
    g.emit("any_cast", caster=ops[0], card=creature("X", "1R", 1, 1))
    run(g)
    assert any(pm.name == "Free" for pm in me.battlefield)


def test_veteran_explorer_and_olivias_wrath():
    g, me, ops = new_game()
    for pl in (me, ops[0]):
        pl.library += [land("Forest", [G], basic=True) for _ in range(3)]
    ve = put(g, build("Veteran Explorer", "{G}", "Creature — Human Soldier Scout", "When this creature dies, each "
                      "player may search their library for up to two basic land cards, put them onto the battlefield, "
                      "then shuffle.", 1, 1), me)
    n0 = sum(1 for pm in me.battlefield if pm.card.is_land())
    g.to_graveyard(ve, "test")
    run(g)
    assert sum(1 for pm in me.battlefield if pm.card.is_land()) == n0 + 2
    for k in range(2):
        put(g, creature(f"V{k}", "1B", 2, 2, subtypes={"Vampire"}), me)
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    ow = build("Olivia's Wrath", "{4}{B}", "Sorcery", "Each non-Vampire creature gets -X/-X until end of turn, where X "
               "is the number of Vampires you control.")
    ow.on_cast_resolve(g, me, [])
    assert foe not in ops[0].battlefield
