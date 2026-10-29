"""Batch 31: disparos de la criatura equipada/encantada al hacer daño de combate (Swords,
Masks, Bloodforged Battle-Axe), Hooded Horror, Sidar Kondo, Fumiko, Disaster Radius,
Confiscation Coup, Aetherworks Marvel, Mechanized Production, Hunter's Insight, Geode Golem,
Silent-Blade Oni, Aethermage's Touch, Vedalken Humiliator, Scourge of Nel Toth, Crawling
Sensation, Trail of Mystery, Frontier Warmonger, Dispatch, Dearly Departed, Resurrection Orb,
Imprisoned in the Moon y elección humana del huésped de un Aura."""
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


def _choose(g, label):
    ch = g.pending_choice
    assert ch is not None
    idx = next(o["i"] for o in ch["options"] if label in o["name"])
    g.pending_choice = None
    ch["_apply"](idx)


def test_equipped_creature_combat_damage_trigger_fires():
    g, me, ops = new_game()
    sh = put(g, build("Specter's Shroud", "{2}", "Artifact — Equipment", "Equipped creature gets +1/+0.\nWhenever "
                      "equipped creature deals combat damage to a player, that player discards a card.\nEquip {1}"), me)
    a = put(g, creature("A", "1R", 2, 2), me)
    sh.enchanting = a
    ops[0].hand = [land("F", [G], basic=True), land("F", [G], basic=True)]
    _attack(g, me, [(a, ops[0])])
    assert len(ops[0].hand) == 1 and ops[0].life == 37


def test_bloodforged_battle_axe_copies_itself():
    g, me, ops = new_game()
    ax = put(g, build("Bloodforged Battle-Axe", "{1}", "Artifact — Equipment", "Equipped creature gets +2/+0.\n"
                      "Whenever equipped creature deals combat damage to a player, create a token that's a copy of this "
                      "Equipment.\nEquip {2}"), me)
    a = put(g, creature("A", "1R", 2, 2), me)
    ax.enchanting = a
    _attack(g, me, [(a, ops[0])])
    assert sum(1 for x in me.battlefield if x.name == "Bloodforged Battle-Axe") == 2


def test_hooded_horror_unblockable_vs_most_creatures():
    g, me, ops = new_game()
    hh = put(g, build("Hooded Horror", "{4}{B}", "Creature — Horror", "This creature can't be blocked as long as "
                      "defending player controls the most creatures or is tied for the most.", 4, 4), me)
    bl = put(g, creature("Wall", "1W", 0, 5), ops[0])
    assert not g._can_block_evasion(hh, bl)          # empatan (1 y 1)
    put(g, creature("X", "G", 1, 1), me)
    assert g._can_block_evasion(hh, bl)              # ahora yo tengo más


def test_sidar_small_creatures_evasion():
    g, me, ops = new_game()
    put(g, build("Sidar Kondo of Jamuraa", "{2}{G}{W}", "Legendary Creature — Human Knight", "Flanking\nCreatures your "
                 "opponents control without flying or reach can't block creatures with power 2 or less.", 2, 5), me)
    small = put(g, creature("S", "G", 2, 2), me)
    big = put(g, creature("B", "G", 3, 3), me)
    bl = put(g, creature("Bl", "1W", 1, 4), ops[0])
    assert not g._can_block_evasion(small, bl) and g._can_block_evasion(big, bl)


def test_fumiko_dynamic_bushido():
    g, me, ops = new_game()
    fu = put(g, build("Fumiko the Lowblood", "{2}{R}{R}", "Legendary Creature — Human Samurai", "Fumiko has bushido X, "
                      "where X is the number of attacking creatures.\nCreatures your opponents control attack each "
                      "combat if able.", 3, 2), me)
    a1 = put(g, creature("A1", "G", 1, 1), ops[0])
    a2 = put(g, creature("A2", "G", 1, 1), ops[0])
    a1.attacking = me
    a2.attacking = me
    assert g._bushido(fu) == 2


def test_disaster_radius_reveals_creature():
    g, me, ops = new_game()
    dr = build("Disaster Radius", "{5}{R}{R}", "Sorcery", "As an additional cost to cast this spell, reveal a creature "
               "card from your hand.\nDisaster Radius deals X damage to each creature your opponents control, where X "
               "is the revealed card's mana value.")
    me.hand = [creature("Big", "4GG", 6, 6), creature("Small", "G", 1, 1)]
    x = put(g, creature("X", "3G", 5, 5), ops[0])
    y = put(g, creature("Y", "3G", 7, 7), ops[0])
    dr.on_cast_resolve(g, me, [])
    run(g)
    assert x not in ops[0].battlefield and y in ops[0].battlefield


def test_confiscation_coup_steals_with_energy():
    g, me, ops = new_game()
    cc = build("Confiscation Coup", "{3}{U}{U}", "Sorcery", "Choose target artifact or creature. You get {E}{E}{E}{E} "
               "(four energy counters), then you may pay an amount of {E} equal to that permanent's mana value. If you "
               "do, gain control of it.")
    t = put(g, creature("T", "2G", 3, 3), ops[0])
    cc.on_cast_resolve(g, me, [])
    assert t in me.battlefield and me.energy == 1


def test_aetherworks_marvel_energy_and_cast():
    g, me, ops = new_game()
    am = put(g, build("Aetherworks Marvel", "{4}", "Legendary Artifact", "Whenever a permanent you control is put into "
                      "a graveyard, you get {E} (an energy counter).\n{T}, Pay six {E}: Look at the top six cards of your "
                      "library. You may cast a spell from among them without paying its mana cost. Put the rest on the "
                      "bottom of your library in a random order."), me)
    c = put(g, creature("C", "G", 1, 1), me)
    g.destroy(c)
    run(g)
    assert me.energy == 1
    me.energy = 6
    me.library.append(creature("Fatty", "6GG", 8, 8))
    idx = next(i for i, ab in enumerate(am.card.activated_abilities) if ab.get("energy") == 6)
    assert g.activate_ability(am, idx)
    run(g)
    assert any(x.name == "Fatty" for x in me.battlefield) and me.energy == 0


def test_mechanized_production_copies_own_artifact():
    g, me, ops = new_game()
    art = put(g, artifact("Thopter Gizmo"), me)
    put(g, creature("Opp art", "G", 1, 1), ops[0])
    mp = put(g, build("Mechanized Production", "{2}{U}{U}", "Enchantment — Aura", "Enchant artifact you control\nAt the "
                      "beginning of your upkeep, create a token that's a copy of enchanted artifact. Then if you control "
                      "eight or more artifacts with the same name as one another, you win the game."), me)
    assert mp.enchanting is art
    g.emit("upkeep", player=me)
    run(g)
    assert sum(1 for x in me.battlefield if x.name == "Thopter Gizmo") == 2


def test_hunters_insight_draws():
    g, me, ops = new_game()
    hi = build("Hunter's Insight", "{2}{G}", "Instant", "Choose target creature you control. Whenever that creature "
               "deals combat damage to a player or planeswalker this turn, draw that many cards.")
    a = put(g, creature("A", "2G", 4, 4), me)
    hi.on_cast_resolve(g, me, [])
    h = len(me.hand)
    _attack(g, me, [(a, ops[0])])
    assert len(me.hand) - h == 4


def test_geode_golem_casts_commander():
    g, me, ops = new_game()
    gg = put(g, build("Geode Golem", "{5}", "Artifact Creature — Golem", "Trample\nWhenever this creature deals combat "
                      "damage to a player, you may cast your commander from the command zone without paying its mana "
                      "cost. (You still pay any additional costs.)", 5, 3, keywords=("Trample",)), me)
    cmd = me.command[0]
    _attack(g, me, [(gg, ops[0])])
    assert any(x.card is cmd for x in me.battlefield)


def test_silent_blade_oni_casts_from_opponent_hand():
    g, me, ops = new_game()
    oni = put(g, build("Silent-Blade Oni", "{3}{U}{U}{B}{B}", "Creature — Demon Ninja", "Ninjutsu {4}{U}{B}\nWhenever "
                       "this creature deals combat damage to a player, look at that player's hand. You may cast a spell "
                       "from among those cards without paying its mana cost.", 6, 5), me)
    ops[0].hand = [creature("Theirs", "4G", 5, 5)]
    _attack(g, me, [(oni, ops[0])])
    assert any(x.name == "Theirs" for x in me.battlefield) and not ops[0].hand


def test_aethermages_touch_returns_at_end_step():
    g, me, ops = new_game()
    at = build("Aethermage's Touch", "{2}{W}{U}", "Instant", "Reveal the top four cards of your library. You may put a "
               "creature card from among them onto the battlefield. It gains \"At the beginning of your end step, return "
               "this creature to its owner's hand.\" Then put the rest of the cards revealed this way on the bottom of "
               "your library in any order.")
    me.library.append(creature("Dude", "3G", 4, 4))
    at.on_cast_resolve(g, me, [])
    run(g)
    pm = next(x for x in me.battlefield if x.name == "Dude")
    g.active_index = g.players.index(me)
    g.end_turn(me)
    assert pm not in me.battlefield and any(c.name == "Dude" for c in me.hand)


def test_vedalken_humiliator_metalcraft():
    g, me, ops = new_game()
    vh = put(g, build("Vedalken Humiliator", "{3}{U}", "Creature — Vedalken Wizard", "Metalcraft — Whenever this creature "
                      "attacks, if you control three or more artifacts, creatures your opponents control lose all "
                      "abilities and have base power and toughness 1/1 until end of turn.", 3, 4), me)
    for i in range(3):
        put(g, artifact(f"A{i}"), me)
    big = put(g, creature("Big", "4G", 6, 6, kw=("flying",)), ops[0])
    g.active_index = g.players.index(me)
    vh.summoning_sick = False
    g._declare_attackers(me, [(vh, ops[0])])
    run(g)
    assert (big.power, big.toughness) == (1, 1) and big.abilities_off()


def test_scourge_of_nel_toth_from_graveyard():
    g, me, ops = new_game()
    sc = build("Scourge of Nel Toth", "{5}{B}{B}", "Creature — Zombie Dragon", "Flying\nYou may cast this creature from "
               "your graveyard by paying {B}{B} and sacrificing two creatures rather than paying its mana cost.", 6, 6)
    me.graveyard.append(sc)
    put(g, creature("F1", "G", 1, 1), me)
    put(g, creature("F2", "G", 1, 1), me)
    give_lands(g, me, 2, colors=(B,))
    g.active_index = g.players.index(me)
    assert g.play_from_graveyard(me, sc)
    run(g)
    assert any(x.name == "Scourge of Nel Toth" for x in me.battlefield)
    assert not any(x.name in ("F1", "F2") for x in me.battlefield)


def test_crawling_sensation_insect_once_per_turn():
    g, me, ops = new_game()
    put(g, build("Crawling Sensation", "{2}{G}", "Enchantment", "At the beginning of your upkeep, you may mill two cards."
                 "\nWhenever one or more land cards are put into your graveyard from anywhere for the first time each "
                 "turn, create a 1/1 green Insect creature token."), me)
    l1 = put(g, land("L1", [G], basic=False), me)
    l2 = put(g, land("L2", [G], basic=False), me)
    g.destroy(l1)
    g.destroy(l2)
    run(g)
    assert sum(1 for x in me.battlefield if x.name == "Insect") == 1


def test_trail_of_mystery_face_up_pump():
    g, me, ops = new_game()
    tm = put(g, build("Trail of Mystery", "{1}{G}", "Enchantment", "Whenever a face-down creature you control enters, you "
                      "may search your library for a basic land card, reveal it, put it into your hand, then shuffle.\n"
                      "Whenever a permanent you control is turned face up, if it's a creature, it gets +2/+2 until end "
                      "of turn."), me)
    c = put(g, creature("C", "G", 2, 2), me)
    g.emit("turned_face_up", player=me, perm=c)
    run(g)
    assert c.power == 4 and tm in me.battlefield


def test_frontier_warmonger_menace():
    g, me, ops = new_game()
    put(g, build("Frontier Warmonger", "{3}{R}", "Creature — Human Warrior", "Whenever one or more creatures attack one "
                 "of your opponents or a planeswalker they control, those creatures gain menace until end of turn.",
                 4, 3), me)
    a = put(g, creature("A", "G", 2, 2), me)
    a.summoning_sick = False
    g.active_index = g.players.index(me)
    g._declare_attackers(me, [(a, ops[0])])
    run(g)
    assert a.has("menace")


def test_dispatch_metalcraft_exiles():
    g, me, ops = new_game()
    ds = build("Dispatch", "{W}", "Instant", "Tap target creature.\nMetalcraft — If you control three or more artifacts, "
               "exile that creature.")
    t = put(g, creature("T", "G", 3, 3), ops[0])
    ds.on_cast_resolve(g, me, [t])
    assert t in ops[0].battlefield and t.tapped
    for i in range(3):
        put(g, artifact(f"A{i}"), me)
    ds.on_cast_resolve(g, me, [t])
    assert t not in ops[0].battlefield


def test_dearly_departed_human_counter():
    g, me, ops = new_game()
    me.graveyard.append(build("Dearly Departed", "{4}{W}{W}", "Creature — Spirit", "Flying\nAs long as this creature is "
                              "in your graveyard, each Human creature you control enters with an additional +1/+1 "
                              "counter on it.", 5, 5))
    h = put(g, build("Villager", "{W}", "Creature — Human", "", 1, 1), me)
    assert h.counters.get("+1/+1", 0) == 1


def test_resurrection_orb_returns_at_end_step():
    g, me, ops = new_game()
    orb = put(g, build("Resurrection Orb", "{2}", "Artifact — Equipment", "Equipped creature has lifelink.\nWhenever "
                       "equipped creature dies, return that card to the battlefield under its owner's control at the "
                       "beginning of the next end step.\nEquip {4}"), me)
    c = put(g, creature("C", "G", 2, 2), me)
    orb.enchanting = c
    g.destroy(c)
    run(g)
    assert c not in me.battlefield and g.delayed_end
    while g.delayed_end:
        g.delayed_end.pop(0)(g)
    assert any(x.name == "C" for x in me.battlefield)


def test_imprisoned_in_the_moon_makes_colorless_land():
    g, me, ops = new_game()
    t = put(g, creature("Beast", "3G", 5, 5, kw=("flying",)), ops[0])
    t.summoning_sick = False
    put(g, build("Imprisoned in the Moon", "{2}{U}", "Enchantment — Aura", "Enchant creature, land, or planeswalker\n"
                 "Enchanted permanent is a colorless land with \"{T}: Add {C}\" and loses all other card types and "
                 "abilities."), me)
    assert not t.is_creature()
    assert ops[0].produced(t) == {"C": 1} and t in ops[0].mana_sources()


def test_human_chooses_aura_host():
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = g.players.index(me)
    a = put(g, creature("Big", "3G", 5, 5), ops[0])
    b = put(g, creature("Small", "G", 1, 1), ops[0])
    pac = put(g, build("Pacifism", "{1}{W}", "Enchantment — Aura", "Enchant creature\nEnchanted creature can't attack "
                       "or block."), me)
    assert g.pending_choice is not None and pac in me.battlefield
    _choose(g, "Small")
    assert pac.enchanting is b and a is not None
