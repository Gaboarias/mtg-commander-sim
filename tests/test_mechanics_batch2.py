"""Batch 2: landwalk, split second, umbra armor, unleash, exert, exhaust/boast/
power-up, condiciones (raid, morbid, ferocious, threshold…), rebound, overload,
retrace, jump-start, miracle, plot, warp, prototype, surge/spectacle/prowl,
emerge, exploit, offspring, squad, casualty, bargain."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W, Cost  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


# ── estáticas / combate ─────────────────────────────────────────────────── #

def test_islandwalk_unblockable_vs_island():
    g, me, ops = new_game()
    a = build("Walker", "{1}{U}", "Creature — Merfolk", "Islandwalk", 2, 1,
              keywords=["Islandwalk", "Landwalk"])
    pa = put(g, a, me)
    pa.summoning_sick = False
    wall = put(g, creature("Wall", "1W", 0, 4), ops[0])
    decl = g._declare_attackers(me, [(pa, ops[0])])
    g._apply_block_pairs(decl, [(pa, wall)])
    assert pa.blocked_by == [wall]           # sin Isla: se puede bloquear
    g2, me2, ops2 = new_game()
    pa2 = put(g2, build("Walker", "{1}{U}", "Creature — Merfolk", "Islandwalk", 2, 1,
                        keywords=["Islandwalk"]), me2)
    pa2.summoning_sick = False
    w2 = put(g2, creature("Wall", "1W", 0, 4), ops2[0])
    put(g2, land("Island", [U], basic=True), ops2[0])
    d2 = g2._declare_attackers(me2, [(pa2, ops2[0])])
    g2._apply_block_pairs(d2, [(pa2, w2)])
    assert pa2.blocked_by == []


def test_split_second_prevents_responses():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    ss = build("Sudden Shock", "{1}{R}", "Instant",
               "Split second\nSudden Shock deals 2 damage to any target.",
               keywords=["Split second"])
    assert "split_second" in ss.keywords
    me.hand = [ss]
    called = []
    ops[0].policy.respond = lambda *a, **k: called.append(1) or False
    g.cast(me, ss, targets=[ops[0]])
    run(g)
    assert not called and ops[0].life == 38


def test_umbra_armor_saves_host():
    g, me, ops = new_game()
    host = put(g, creature("Bear", "1G", 2, 2), me)
    umb = build("Hyena Umbra", "{W}", "Enchantment — Aura",
                "Enchant creature\nEnchanted creature gets +1/+1 and has first strike.\n"
                "Umbra armor", keywords=["Enchant", "Umbra armor"])
    au = put(g, umb, me)
    au.enchanting = host
    g.destroy(host)
    g.sba()
    assert host in me.battlefield and au not in me.battlefield


def test_unleash_counter_and_cant_block():
    g, me, ops = new_game()
    c = build("Rakdos Cackler", "{B/R}", "Creature — Devil",
              "Unleash\nThis creature can't block as long as it has a +1/+1 counter on it.",
              1, 1, keywords=["Unleash"])
    pm = put(g, c, me)
    assert pm.counters.get("+1/+1") == 1 and pm.cant_block


def test_exert_trigger_and_no_untap():
    g, me, ops = new_game()
    c = build("Exerter", "{2}{R}", "Creature — Human",
              "You may exert this creature as it attacks. When you do, it gets +2/+0 until "
              "end of turn.", 2, 2, keywords=["Exert"])
    pm = put(g, c, me)
    pm.summoning_sick = False
    g._declare_attackers(me, [(pm, ops[0])])
    assert pm.power == 4 and pm.exerted
    g.end_turn(me)
    g.begin_turn(me)
    assert pm.tapped                          # no se enderezó


def test_exhaust_once_and_boast_needs_attack():
    g, me, ops = new_game()
    give_lands(g, me, 6)
    c = build("Exh", "{2}{G}", "Creature — Elf",
              "Exhaust — {1}: Put a +1/+1 counter on this creature.\n"
              "Boast — {1}: Put a +1/+1 counter on this creature.", 1, 1,
              keywords=["Exhaust", "Boast"])
    pm = put(g, c, me)
    assert g.activate_ability(pm, 0)
    run(g)
    assert not g.activate_ability(pm, 0)     # exhaust: una sola vez
    assert not g.activate_ability(pm, 1)     # boast: no atacó
    pm.summoning_sick = False
    pm.tapped = False
    g._declare_attackers(me, [(pm, ops[0])])
    assert g.activate_ability(pm, 1)
    run(g)
    assert not g.activate_ability(pm, 1)     # una vez por turno


# ── condiciones (palabras de habilidad) ─────────────────────────────────── #

def test_raid_etb_only_if_attacked():
    txt = ("Raid — When this creature enters, if you attacked this turn, create a 1/1 "
           "red Goblin creature token.")
    g, me, ops = new_game()
    put(g, build("Raider", "{2}{R}", "Creature — Orc", txt, 2, 2), me)
    assert not any(p.name == "Goblin" for p in me.battlefield)
    g, me, ops = new_game()
    me.attacked_turn = g.turn
    put(g, build("Raider", "{2}{R}", "Creature — Orc", txt, 2, 2), me)
    assert any(p.name == "Goblin" for p in me.battlefield)


def test_morbid_and_threshold_and_metalcraft():
    g, me, ops = new_game()
    mb = build("Morbid Test", "{1}{B}", "Sorcery",
               "Draw a card.\nMorbid — Draw two cards instead if a creature died this turn.")
    h = len(me.hand)
    mb.on_cast_resolve(g, me, [])
    assert len(me.hand) == h + 1
    g.death_turn = g.turn
    mb.on_cast_resolve(g, me, [])
    assert len(me.hand) == h + 3
    mc = build("Metal Test", "{2}", "Artifact Creature — Construct",
               "Metalcraft — This creature gets +2/+2 as long as you control three or more "
               "artifacts.", 1, 1)
    pm = put(g, mc, me)
    assert pm.power == 1
    for k in range(2):
        put(g, build(f"Rock{k}", "{1}", "Artifact", ""), me)
    assert pm.power == 3


# ── lanzamientos alternativos ──────────────────────────────────────────── #

def test_rebound_recasts_next_upkeep():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(R,))
    c = build("Staggershock", "{2}{R}", "Instant",
              "Staggershock deals 2 damage to any target.\nRebound", keywords=["Rebound"])
    me.hand = [c]
    g.cast(me, c, targets=[ops[0]])
    run(g)
    assert c in me.exile and ops[0].life == 38
    g.begin_turn(me)
    run(g)
    assert ops[0].life <= 36 and c in me.graveyard


def test_overload_hits_all_opponent_creatures():
    g, me, ops = new_game()
    give_lands(g, me, 7, colors=(U,))
    mine = put(g, creature("Mine", "G", 1, 1), me)
    a = put(g, creature("A", "G", 2, 2), ops[0])
    b = put(g, creature("B", "G", 2, 2), ops[0])
    rift = build("Cyclonic Rift", "{1}{U}", "Instant",
                 "Return target nonland permanent you don't control to its owner's hand.\n"
                 "Overload {6}{U}", keywords=["Overload"])
    me.hand = [rift]
    assert g.cast_overload(me, rift)
    run(g)
    assert a not in ops[0].battlefield and b not in ops[0].battlefield
    assert mine in me.battlefield


def test_retrace_discards_land_and_returns_to_graveyard():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(R,))
    jab = build("Flame Jab", "{R}", "Sorcery",
                "Flame Jab deals 1 damage to any target.\nRetrace", keywords=["Retrace"])
    me.graveyard = [jab]
    me.hand = [land("Mountain", [R], basic=True)]
    assert g.play_from_graveyard(me, jab, targets=[ops[0]])
    run(g)
    assert ops[0].life == 39 and jab in me.graveyard and not me.hand


def test_jump_start_discards_and_exiles():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U,))
    js = build("Chemister's Insight", "{3}{U}", "Instant",
               "Draw two cards.\nJump-start", keywords=["Jump-start"])
    js.cost = Cost(1, ("U",))
    js.gy_play["cost"] = js.cost
    me.graveyard = [js]
    me.hand = [creature("Junk", "1", 1, 1)]
    assert g.play_from_graveyard(me, js)
    run(g)
    assert js in me.exile and len(me.hand) == 2


def test_miracle_on_first_draw():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(W,))
    a = put(g, creature("A", "G", 2, 2), ops[0])
    term = build("Terminus", "{4}{W}{W}", "Sorcery",
                 "Put all creatures on the bottom of their owners' libraries.\nMiracle {W}",
                 keywords=["Miracle"])
    me.library.append(term)
    me.draw(1, g)
    run(g)
    assert any("milagro" in ln for ln in g.log_lines) and term not in me.hand


def test_plot_then_cast_free_later_turn():
    g, me, ops = new_game()
    give_lands(g, me, 2)
    c = build("Plotter", "{4}{G}", "Creature — Beast", "Plot {1}{G}", 5, 5,
              keywords=["Plot"])
    me.hand = [c]
    assert g.plot_card(me, c)
    assert not g.play_from_exile(me, c)      # mismo turno: no
    g.turn += 1
    assert g.play_from_exile(me, c)
    run(g)
    assert any(p.name == "Plotter" for p in me.battlefield)


def test_warp_exiles_at_end_and_is_castable_later():
    g, me, ops = new_game()
    give_lands(g, me, 2)
    drew = []
    c = build("Warper", "{4}{G}", "Creature — Alien",
              "When this creature enters, draw a card.\nWarp {1}{G}", 3, 3, keywords=["Warp"])
    me.hand = [c]
    h = len(me.hand)
    assert g.cast_warp(me, c)
    run(g)
    assert len(me.hand) == h                  # robó 1 (la carta salió de la mano)
    g.end_turn(me)
    assert c in me.exile_play and not any(p.card is c for p in me.battlefield)


def test_prototype_smaller_then_real_card_returns():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(B,))
    c = build("Phyrexian Fleshgorger", "{7}", "Artifact Creature — Phyrexian Wurm",
              "Prototype {1}{B}{B} — 3/3\nMenace, lifelink, ward—Pay life equal to this "
              "creature's power.", 7, 5, keywords=["Prototype", "Menace", "Lifelink", "Ward"])
    me.hand = [c]
    assert g.cast_prototype(me, c)
    run(g)
    pm = next(p for p in me.battlefield if p.name == c.name)
    assert (pm.power, pm.toughness) == (3, 3)
    g.destroy(pm)
    g.sba()
    assert c in me.graveyard


def test_surge_and_spectacle_alt_costs():
    g, me, ops = new_game()
    sg = build("Reckless Bushwhacker", "{2}{R}", "Creature — Goblin Warrior",
               "Surge {1}{R}\nHaste", 2, 1, keywords=["Surge", "Haste"])
    assert g.effective_cost(me, sg).cmc == 3
    me.spells_cast_turn = 1
    assert g.effective_cost(me, sg).cmc == 2
    sp = build("Spec", "{4}{R}", "Sorcery", "Spec deals 3 damage to any target.\nSpectacle {1}{R}",
               keywords=["Spectacle"])
    g._life_start = {id(o): o.life for o in g.players}
    assert g.effective_cost(me, sp).cmc == 5
    ops[0].life -= 1
    assert g.effective_cost(me, sp).cmc == 2


def test_emerge_sacrifices_and_reduces():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(U,))
    fodder = put(g, creature("Fodder", "3G", 1, 1), me)
    edf = build("Elder Deep-Fiend", "{8}", "Creature — Eldrazi Octopus",
                "Flash\nEmerge {5}{U}{U}", 5, 6, keywords=["Flash", "Emerge"])
    me.hand = [edf]
    assert g.cast_emerge(me, edf)
    run(g)
    assert fodder not in me.battlefield and any(p.name == "Elder Deep-Fiend" for p in me.battlefield)


def test_exploit_bot_sacrifices_token_and_triggers():
    g, me, ops = new_game()
    import cards as _c
    _c.make_token(g, me, "Zombie", 2, 2, subtypes=("Zombie",))
    sid = build("Exploiter", "{3}{B}", "Creature — Zombie",
                "Exploit\nWhen this creature exploits a creature, draw two cards.", 4, 6,
                keywords=["Exploit"])
    h = len(me.hand)
    put(g, sid, me)
    assert not any(p.name == "Zombie" for p in me.battlefield)
    assert len(me.hand) == h + 2


def test_offspring_creates_1_1_copy():
    g, me, ops = new_game()
    give_lands(g, me, 5)
    c = build("Offy", "{2}{G}", "Creature — Rabbit",
              "Offspring {2}", 3, 3, keywords=["Offspring"])
    me.hand = [c]
    g.cast(me, c)
    run(g)
    offs = [p for p in me.battlefield if p.name == "Offy"]
    assert len(offs) == 2 and sorted((p.power, p.toughness) for p in offs) == [(1, 1), (3, 3)]


def test_casualty_copies_spell():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    import cards as _c
    _c.make_token(g, me, "Devil", 2, 2, subtypes=("Devil",))
    cs = build("Cas", "{1}{R}", "Instant", "Casualty 1\nCas deals 2 damage to each opponent.",
               keywords=["Casualty"])
    me.hand = [cs]
    g.cast(me, cs)
    run(g)
    assert ops[0].life == 36


def test_conditional_keywords_threshold_and_hellbent():
    g, me, ops = new_game()
    c = build("Battlewise Aven", "{3}{W}", "Creature — Bird Soldier",
              "Flying\nThreshold — As long as there are seven or more cards in your graveyard, "
              "this creature gets +1/+1 and has first strike.", 2, 2,
              keywords=["Flying", "Threshold"])
    pm = put(g, c, me)
    assert pm.power == 2 and not pm.has("first_strike")
    me.graveyard = [land("Forest", [G], basic=True) for _ in range(7)]
    assert pm.power == 3 and pm.has("first_strike")


def test_exert_as_activation_cost():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(W,))
    c = build("Basri", "{1}{W}", "Legendary Creature — Human Soldier",
              "{W}, {T}, Exert this creature: Create a 1/1 white Cat creature token with "
              "lifelink.", 2, 3)
    pm = put(g, c, me)
    pm.summoning_sick = False
    assert g.activate_ability(pm, 0)
    run(g)
    assert pm.exerted and any(p.name == "Cat" for p in me.battlefield)
