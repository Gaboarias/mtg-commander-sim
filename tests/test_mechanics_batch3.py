"""Batch 3: palabras de habilidad (constellation, enrage, heroic, inspired, battalion,
rally, survival, flurry), Mutate, Splice, Saddle, Station, Phasing, Champion,
Companion y acciones clave."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W, Cost  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _c(text, name="X", tl="Creature — Human Ally", p=2, t=2, kws=()):
    return build(name, "{2}", tl, text, p, t, keywords=list(kws))


# ── 3A: disparos de palabras de habilidad ─────────────────────────────── #

def test_constellation_enchantment_enters():
    g, me, ops = new_game()
    pm = put(g, _c("Constellation — Whenever an enchantment you control enters, put a "
                   "+1/+1 counter on this creature."), me)
    put(g, build("Ench", "{1}", "Enchantment", ""), me)
    assert pm.counters.get("+1/+1") == 1
    put(g, creature("Bear", "1G", 2, 2), me)
    assert pm.counters.get("+1/+1") == 1


def test_enrage_on_damage():
    g, me, ops = new_game()
    pm = put(g, _c("Enrage — Whenever this creature is dealt damage, create a 1/1 red "
                   "Goblin creature token.", p=3, t=5), me)
    g.deal_damage(None, pm, 1)
    run(g)
    assert any(p.name == "Goblin" for p in me.battlefield)


def test_heroic_on_targeting_spell():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(W,))
    pm = put(g, _c("Heroic — Whenever you cast a spell that targets this creature, put a "
                   "+1/+1 counter on this creature."), me)
    sp = build("Pump", "{W}", "Instant", "Target creature gets +1/+1 until end of turn.")
    me.hand = [sp]
    g.cast(me, sp, targets=[pm])
    run(g)
    assert pm.counters.get("+1/+1") == 1


def test_inspired_on_untap():
    g, me, ops = new_game()
    pm = put(g, _c("Inspired — Whenever this creature becomes untapped, you gain 2 life."), me)
    pm.tapped = True
    life = me.life
    g.begin_turn(me)
    run(g)
    assert me.life == life + 2


def test_battalion_needs_three_attackers():
    g, me, ops = new_game()
    pm = put(g, _c("Battalion — Whenever this creature and at least two other creatures "
                   "attack, you gain 3 life."), me)
    others = [put(g, creature(f"B{k}", "1G", 1, 1), me) for k in range(2)]
    for x in [pm] + others:
        x.summoning_sick = False
    life = me.life
    g._declare_attackers(me, [(x, ops[0]) for x in [pm] + others])
    assert me.life == life + 3


def test_rally_and_another_subtype_enters():
    g, me, ops = new_game()
    put(g, _c("Rally — Whenever this creature or another Ally you control enters, you "
              "gain 1 life."), me)
    life = me.life
    put(g, build("Ally2", "{1}", "Creature — Elf Ally", "", 1, 1), me)
    put(g, creature("Bear", "1G", 2, 2), me)
    assert me.life == life + 1


def test_flurry_second_spell():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    put(g, _c("Flurry — Whenever you cast your second spell each turn, draw a card."), me)
    sps = [build(f"S{k}", "{R}", "Instant", "You gain 1 life.") for k in range(2)]
    me.hand = list(sps)
    h0 = 0
    g.cast(me, sps[0]); run(g)
    g.cast(me, sps[1]); run(g)
    assert len(me.hand) == h0 + 1


# ── 3B: mutate / splice / saddle / station / phasing / champion / companion ── #

def _shark():
    return build("Pouncing Shoreshark", "{4}{U}", "Creature — Shark",
                 "Mutate {3}{U}\nFlash\nWhenever this creature mutates, draw a card.", 4, 3,
                 keywords=["Mutate", "Flash"])


def test_mutate_merges_and_triggers_and_both_cards_leave():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(U,))
    host = put(g, build("Beast", "{2}{G}", "Creature — Beast", "Trample", 3, 3,
                        keywords=["Trample"]), me)
    sh = _shark()
    me.hand = [sh]
    assert g.cast_mutate(me, sh, host)
    run(g)
    assert host in me.battlefield and len(me.creatures()) == 1
    assert (host.power, host.toughness) == (4, 3) and host.has("trample") and host.has("flash")
    assert len(me.hand) == 1                  # robó por el disparo de mutar
    g.destroy(host)
    g.sba()
    names = sorted(c.name for c in me.graveyard)
    assert names == ["Beast", "Pouncing Shoreshark"]


def test_mutate_not_onto_human():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(U,))
    hu = put(g, creature("Human", "W", 1, 1, subtypes=("Human",)), me)
    me.hand = [_shark()]
    assert not g.cast_mutate(me, me.hand[0], hu)


def test_splice_onto_arcane():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(R,))
    arc = build("Arc Bolt", "{R}", "Instant — Arcane", "Arc Bolt deals 1 damage to each opponent.")
    gl = build("Glacial Ray", "{1}{R}", "Instant — Arcane",
               "Glacial Ray deals 2 damage to each opponent.\nSplice onto Arcane {1}{R}",
               keywords=["Splice"])
    me.hand = [arc, gl]
    g.cast(me, arc)
    run(g)
    assert ops[0].life == 37 and gl in me.hand


def test_saddle_and_attack_trigger():
    g, me, ops = new_game()
    mount = put(g, build("Mount", "{2}{R}", "Creature — Horse Mount",
                         "Whenever this creature attacks while saddled, it gets +2/+0 until "
                         "end of turn.\nSaddle 1", 3, 3, keywords=["Saddle"]), me)
    rider = put(g, creature("Rider", "R", 1, 1), me)
    mount.summoning_sick = False
    ab = next(i for i, a in enumerate(mount.card.activated_abilities)
              if a["label"].startswith("Ensillar"))
    assert g.activate_ability(mount, ab)
    run(g)
    assert rider.tapped and mount.saddled_turn == g.turn
    g._declare_attackers(me, [(mount, ops[0])])
    run(g)
    assert mount.power == 5


def test_station_charges_and_becomes_creature():
    g, me, ops = new_game()
    ship = put(g, build("Kill-Ship", "{4}", "Artifact — Spacecraft",
                        "Station (Tap another creature you control: Put charge counters equal "
                        "to its power on this Spacecraft. Station only as a sorcery. It's an "
                        "artifact creature at 7+.)\n7+ | Flying", 7, 7, keywords=["Station"]), me)
    big = put(g, creature("Big", "4G", 7, 7), me)
    assert not ship.is_creature()
    ab = next(i for i, a in enumerate(ship.card.activated_abilities) if "station" in a["label"])
    assert g.activate_ability(ship, ab)
    run(g)
    assert ship.counters.get("charge") == 7 and ship.is_creature() and ship.has("flying")


def test_phasing_alternates_and_teferis_protection():
    g, me, ops = new_game()
    ph = put(g, build("Phaser", "{1}{U}", "Creature — Spirit", "Phasing", 2, 2,
                      keywords=["Phasing"]), me)
    g.begin_turn(me)
    assert ph not in me.battlefield
    g.begin_turn(me)
    assert ph in me.battlefield
    tp = build("Teferi's Protection", "{2}{W}", "Instant",
               "All permanents you control phase out.")
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    tp.on_cast_resolve(g, me, [])
    assert bear not in me.battlefield


def test_champion_exiles_and_returns():
    g, me, ops = new_game()
    f = put(g, build("Fae", "{U}", "Creature — Faerie", "", 1, 1), me)
    ch = put(g, build("Champ", "{2}{U}", "Creature — Faerie", "Flying\nChampion a Faerie",
                      3, 3, keywords=["Flying", "Champion"]), me)
    assert f not in me.battlefield and f.card in me.exile
    g.destroy(ch)
    g.sba()
    assert any(p.card is f.card for p in me.battlefield)


def test_champion_without_victim_sacrifices():
    g, me, ops = new_game()
    ch = put(g, build("Champ", "{2}{U}", "Creature — Faerie", "Champion a Faerie", 3, 3,
                      keywords=["Champion"]), me)
    assert ch not in me.battlefield


def test_companion_decklist_and_to_hand():
    import decklist
    parsed = decklist.parse_decklist("Commander\n1 Sol Ring\n\nCompanion\n1 Lurrus of the Dream-Den\n\n1 Island")
    assert parsed["companion"] == "Lurrus of the Dream-Den"
    g, me, ops = new_game()
    give_lands(g, me, 3)
    me.companion = creature("Comp", "1WB", 3, 2)
    assert g.companion_to_hand(me) and me.hand[-1].name == "Comp"


def test_spree_costs_and_modes():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(R,))
    sp = build("Spree Test", "{R}", "Instant",
               "Spree\n+ {1} — Spree Test deals 1 damage to each opponent.\n"
               "+ {2} — You gain 3 life.", keywords=["Spree"])
    assert len(sp.modes) == 2 and len(sp.spree_costs) == 2
    picks = me.policy._pick_modes(g, me, sp)
    assert picks == [0, 1]
    life = me.life
    g.cast(me, sp, chosen_modes=picks)
    run(g)
    assert ops[0].life == 39 and me.life == life + 3 and me.available_mana() == 0


def test_awaken_animates_land():
    g, me, ops = new_game()
    give_lands(g, me, 5, colors=(G,))
    aw = build("Awake", "{G}", "Sorcery", "You gain 1 life.\nAwaken 3—{4}{G}", keywords=["Awaken"])
    me.hand = [aw]
    assert g.cast_alt_effect(me, aw, aw.awaken_cost, "_awakened")
    run(g)
    el = [p for p in me.battlefield if p.card.is_land() and p.is_creature()]
    assert len(el) == 1 and el[0].power == 3 and el[0].has("haste")


def test_speed_and_max_speed():
    g, me, ops = new_game()
    eng = put(g, build("Racer", "{1}{R}", "Creature — Goblin",
                       "Start your engines!\nMax speed — Flying", 2, 2,
                       keywords=["Start your engines!", "Max speed"]), me)
    assert me.speed == 1 and not eng.has("flying")
    me.speed = 4
    assert eng.has("flying")


# ── 3C: acciones clave ─────────────────────────────────────────────────── #

def test_venture_completes_dungeon():
    import cardsdb
    g, me, ops = new_game()
    eff = cardsdb._effect_any("Venture into the dungeon.")
    for _ in range(4):
        eff(g, me)
    assert me.dungeons_completed == 1 and any(p.name == "Goblin" for p in me.battlefield)


def test_initiative_ventures_each_upkeep_and_is_stolen():
    g, me, ops = new_game()
    g.take_initiative(me)
    assert me.initiative and me.dungeon_room == 1
    g.begin_turn(me)
    assert me.dungeon_room == 2
    atk = put(g, creature("Bear", "1G", 2, 2), ops[0])
    g.deal_damage(atk, me, 2, combat=True)
    assert ops[0].initiative and not me.initiative


def test_blight_collect_evidence_suspect_detain():
    import cardsdb
    g, me, ops = new_game()
    tok = put(g, creature("Tok", "G", 2, 2), me)
    cardsdb._effect_any("Blight 1.")(g, me)
    assert tok.counters.get("-1/-1") == 1
    me.graveyard = [creature(f"C{k}", "2G", 1, 1) for k in range(3)]
    cardsdb._effect_any("Collect evidence 6.")(g, me)
    assert len(me.graveyard) == 1 and len(me.exile) == 2
    foe = put(g, creature("Foe", "1R", 3, 3), ops[0])
    eff, spec, _n = cardsdb._fragment_effect("Suspect target creature.")
    eff(g, me, [foe])
    assert foe.has("menace") and foe.cant_block
    eff, spec, _n = cardsdb._fragment_effect("Detain target nonland permanent an opponent controls.")
    foe2 = put(g, creature("Foe2", "1R", 3, 3), ops[0])
    foe2.summoning_sick = False
    eff(g, me, [foe2])
    assert not foe2.can_attack()
    g.begin_turn(me)
    assert foe2.can_attack()


def test_recruit_and_learn():
    import cardsdb
    g, me, ops = new_game()
    me.library.append(creature("Spell", "1R", 1, 1))
    me.hand = []
    cardsdb._effect_any("Recruit.")(g, me)
    assert any(p.name == "Human Soldier" for p in me.battlefield)


# ── otras palabras clave del batch 3 ──────────────────────────────────── #

def test_enlist_adds_power():
    g, me, ops = new_game()
    a = put(g, build("Enlister", "{2}{W}", "Creature — Human", "Enlist", 2, 2,
                     keywords=["Enlist"]), me)
    h = put(g, creature("Helper", "1G", 3, 3), me)
    a.summoning_sick = h.summoning_sick = False
    g._declare_attackers(me, [(a, ops[0])])
    assert h.tapped and a.power == 5


def test_ingest_exiles_top_card():
    g, me, ops = new_game()
    a = put(g, build("Ingester", "{1}{C}", "Creature — Eldrazi Drone", "Ingest", 2, 1,
                     keywords=["Ingest"]), me)
    n = len(ops[0].library)
    g.deal_damage(a, ops[0], 2, combat=True)
    assert len(ops[0].library) == n - 1 and len(ops[0].exile) == 1


def test_mayhem_only_if_discarded_this_turn():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    c = build("Mayhem Test", "{3}{R}", "Sorcery",
              "Mayhem Test deals 2 damage to each opponent.\nMayhem {1}{R}",
              keywords=["Mayhem"])
    me.graveyard = [c]
    assert not g.play_from_graveyard(me, c)
    me.graveyard = []
    g.discard_card(me, c)
    assert g.play_from_graveyard(me, c)
    run(g)
    assert ops[0].life == 38


def test_gift_promised_bonus():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(G,))
    c = build("Gifty", "{1}{G}", "Sorcery",
              "Gift a card\nYou gain 2 life. If the gift was promised, draw a card.",
              keywords=["Gift"])
    me.hand = [c]
    h_op = len(ops[0].hand)
    g.cast(me, c)
    run(g)
    assert len(ops[0].hand) == h_op + 1 and len(me.hand) == 1


def test_tribute_paid_small():
    g, me, ops = new_game()
    c = build("Trib", "{2}{R}", "Creature — Giant",
              "Tribute 2\nWhen this creature enters, if tribute wasn't paid, it deals 3 "
              "damage to each opponent.", 3, 3, keywords=["Tribute"])
    pm = put(g, c, me)
    assert pm.counters.get("+1/+1") == 2


def test_ascend_blessing():
    g, me, ops = new_game()
    put(g, build("Asc", "{1}{W}", "Creature — Human", "Ascend\nThis creature has flying as long "
                 "as you have the city's blessing.", 2, 2, keywords=["Ascend"]), me)
    give_lands(g, me, 9)
    g.sba()
    asc = next(p for p in me.battlefield if p.name == "Asc")
    assert me.citys_blessing and asc.has("flying")
