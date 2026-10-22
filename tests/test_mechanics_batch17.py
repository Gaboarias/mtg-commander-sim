"""Batch 17: curses (auras de jugador), y más staples de los precons."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_curse_attacked_each_attacker_does_same():
    g, me, ops = new_game(n_opp=2)
    cu = put(g, build("Curse of Disturbance", "{2}{B}", "Enchantment — Aura Curse",
                      "Enchant player\nWhenever enchanted player is attacked, create a 2/2 black Zombie "
                      "creature token. Each opponent attacking that player does the same."), me)
    run(g)
    victim = cu.enchanting_player
    assert victim in ops and cu in me.battlefield
    other = next(o for o in ops if o is not victim)
    atk = put(g, creature("Atk", "1R", 2, 2), other)
    atk.summoning_sick = False
    g._declare_attackers(other, [(atk, victim)])
    run(g)
    assert sum(1 for pm in me.creatures() if pm.name.lower().startswith("zombie")) == 1
    assert sum(1 for pm in other.creatures() if pm.name.lower().startswith("zombie")) == 1


def test_curse_creature_attacks_and_upkeep():
    g, me, ops = new_game()
    cu = put(g, build("Curse of Predation", "{2}{G}", "Enchantment — Aura Curse",
                      "Enchant player\nWhenever a creature attacks enchanted player, put a +1/+1 counter on it."), me)
    run(g)
    a = put(g, creature("A", "1G", 2, 2), me)
    a.summoning_sick = False
    g._declare_attackers(me, [(a, ops[0])])
    run(g)
    assert a.counters.get("+1/+1") == 1
    put(g, build("Curse of the Pierced Heart", "{1}{R}", "Enchantment — Aura Curse",
                 "Enchant player\nAt the beginning of enchanted player's upkeep, Curse of the Pierced "
                 "Heart deals 1 damage to that player."), me)
    run(g)
    life = ops[0].life
    g.begin_turn(ops[0])
    run(g)
    assert ops[0].life == life - 1


def test_animate_dead_and_necromancy_style():
    g, me, ops = new_game()
    ops[0].graveyard.append(creature("Dead", "6B", 6, 6))
    ad = put(g, build("Animate Dead", "{1}{B}", "Enchantment — Aura", "Enchant creature card in a graveyard\n"
                      "When this Aura enters, if it's on the battlefield, it loses \"enchant creature card in a "
                      "graveyard\" and gains \"enchant creature put onto the battlefield with this Aura.\" Return "
                      "enchanted creature card to the battlefield under your control and attach this Aura to it. "
                      "When this Aura leaves the battlefield, that creature's controller sacrifices it.\n"
                      "Enchanted creature gets -1/-0."), me)
    run(g)
    dead = next(pm for pm in me.battlefield if pm.name == "Dead")
    assert dead.power == 5 and ad.enchanting is dead
    g.to_graveyard(ad, "test")
    run(g)
    assert dead not in me.battlefield


def test_promise_gearhulk_dispatch():
    g, me, ops = new_game()
    for k in range(3):
        put(g, creature(f"M{k}", "1G", k + 1, k + 1), me)
        put(g, creature(f"O{k}", "1B", k + 1, k + 1), ops[0])
    pr = build("Promise", "{4}{W}", "Sorcery", "Each player puts a vow counter on a creature they control and "
               "sacrifices the rest. Each of those creatures can't attack you or planeswalkers you control for as "
               "long as it has a vow counter on it.")
    pr.on_cast_resolve(g, me, [])
    run(g)
    assert len(me.creatures()) == 1 and len(ops[0].creatures()) == 1
    foe = ops[0].creatures()[0]
    for k in range(3):
        put(g, build(f"Rock{k}", "{1}", "Artifact", ""), me)
    dp = build("Dispatch", "{W}", "Instant", "Tap target creature.\nMetalcraft — If you control three or more "
               "artifacts, exile that creature.")
    dp.on_cast_resolve(g, me, [])
    assert foe not in ops[0].battlefield


def test_sepulchral_and_hussar():
    g, me, ops = new_game()
    ops[0].graveyard.append(creature("TheirDead", "5B", 5, 5))
    put(g, build("Sepulchral", "{5}{B}{B}", "Creature — Avatar", "When this creature enters, for each opponent, "
                 "you may put up to one target creature card from that player's graveyard onto the battlefield "
                 "under your control.", 5, 4), me)
    run(g)
    assert any(pm.name == "TheirDead" for pm in me.battlefield)
    give_lands(g, me, 2, colors=(U,))
    hu = put(g, build("Hussar", "{2}{U}", "Creature — Human", "When this creature enters, sacrifice it unless "
                      "{W} was spent to cast it.", 1, 3), me)
    run(g)
    assert hu not in me.battlefield


def test_angel_of_serenity_and_forced_attack():
    g, me, ops = new_game()
    foes = [put(g, creature(f"F{k}", "3G", 4, 4), ops[0]) for k in range(3)]
    an = put(g, build("Serenity", "{6}{W}{W}{W}", "Creature — Angel", "Flying\nWhen this creature enters, you may "
                      "exile up to three other target creatures from the battlefield and/or creature cards from "
                      "graveyards until this creature leaves the battlefield.\nWhen this creature leaves the "
                      "battlefield, return the exiled cards to their owners' hands.", 5, 6,
                      keywords=["Flying"]), me)
    run(g)
    assert not ops[0].creatures()
    g.to_graveyard(an, "test")
    run(g)
    assert sum(1 for c in ops[0].hand if c.name.startswith("F")) == 3
    put(g, build("Warmonger", "{4}{R}{R}", "Creature — Dragon", "All creatures attack each combat if able.", 5, 5), ops[0])
    w = put(g, creature("Wall", "1W", 0, 4), me)
    w.summoning_sick = False
    atk = me.policy.declare_attackers(g, me)
    assert any((x[0] if isinstance(x, tuple) else x) is w for x in atk)


def test_sharuum_short_name_and_conditional_top_lands():
    g, me, ops = new_game()
    me.graveyard.append(build("Relic", "{4}", "Artifact", ""))
    put(g, build("Sharuum the Hegemon", "{3}{W}{U}{B}", "Legendary Artifact Creature — Sphinx",
                 "Flying\nWhen Sharuum enters, you may return target artifact card from your graveyard to the "
                 "battlefield.", 5, 5, keywords=["Flying"]), me)
    run(g)
    assert any(pm.name == "Relic" for pm in me.battlefield)
    put(g, build("Verge", "{2}{G}", "Creature — Elf Scout", "As long as an opponent controls more lands than you, "
                 "you may play lands from the top of your library.", 2, 2), me)
    me.library.append(land("Forest", [G], basic=True))
    lands_me = sum(1 for pm in me.battlefield if pm.card.is_land())
    assert not g.extra_land_plays(me) or lands_me < sum(1 for pm in ops[0].battlefield if pm.card.is_land())
    for k in range(lands_me + 1):
        put(g, land("Plains", [W], basic=True), ops[0])
    assert g.extra_land_plays(me)
