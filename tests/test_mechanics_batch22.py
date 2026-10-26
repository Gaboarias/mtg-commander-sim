"""Batch 22: levelers (bandas de nivel), regeneración con escudos, restricciones de
enderezado, destello con coste/sacrificio, disparos de auras sobre el encantado,
'attacks and isn't blocked', bloqueos filtrados por color, restricciones de
lanzamiento y estáticas globales nuevas."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _attach(g, card, pl, host):
    a = g.move_to_battlefield(card, pl)
    a.enchanting = host
    run(g)
    return a


def test_leveler_bands_set_pt_and_keywords():
    g, me, ops = new_game()
    st = build("Student", "{W}", "Creature — Human Warrior",
               "Level up {W}\nLEVEL 2-6\n3/3\nFirst strike\nLEVEL 7+\n4/4\nDouble strike", 1, 1)
    pm = put(g, st, me)
    assert (pm.power, pm.toughness) == (1, 1) and not pm.has("first_strike")
    pm.counters["level"] = 2
    assert (pm.power, pm.toughness) == (3, 3) and pm.has("first_strike")
    pm.counters["level"] = 7
    assert (pm.power, pm.toughness) == (4, 4) and pm.has("double_strike")
    lu = next(a for a in st.activated_abilities if a["label"] == "Level up")
    assert lu.get("sorcery_speed")


def test_regeneration_shield_and_cant_be_regenerated():
    g, me, ops = new_game()
    tr = put(g, build("Troll", "{2}{G}", "Creature — Troll", "{G}: Regenerate this creature.", 2, 2), me)
    give_lands(g, me, 2, colors=(G,))
    assert g.activate_ability(tr, 0)
    run(g)
    g.destroy(tr)
    assert tr in me.battlefield and tr.tapped
    g.destroy(tr)
    assert tr not in me.battlefield
    auto = put(g, build("Auto", "{3}{G}", "Creature — Troll", "If this creature would be destroyed, regenerate it.",
                        3, 3), ops[0])
    wog = build("Wrath", "{2}{W}{W}", "Sorcery", "Destroy all creatures. They can't be regenerated.")
    give_lands(g, me, 4, colors=(W,))
    me.hand.append(wog)
    assert g.cast(me, wog)
    run(g)
    assert auto not in ops[0].battlefield


def test_untap_restrictions_parse():
    a = build("Seed", "{2}{G}", "Creature — Elf", "Untap this creature during each other player's untap step.", 2, 2)
    assert a.untap_others_turn
    b = build("Dep", "", "Land", "This land enters tapped and doesn't untap during your untap step.")
    assert b.enters_tapped and b.no_untap_self
    c = build("Depl", "", "Land", "This land doesn't untap during your untap step if it has a depletion counter on it.")
    assert c.no_untap_if_counter == "depletion"


def test_flash_tax_and_flash_sacrifice():
    g, me, ops = new_game()
    rout = build("Rout", "{3}{W}{W}", "Sorcery", "You may cast this spell as though it had flash if you pay {2} more "
                 "to cast it.\nDestroy all creatures.")
    base = g.effective_cost(me, rout).cmc
    g._fast_cast = me
    assert g.effective_cost(me, rout).cmc == base + 2
    g._fast_cast = None
    fs = build("Sacy", "{1}{G}", "Creature — Elf", "You may cast this spell as though it had flash. If you cast it any "
               "time a sorcery couldn't have been cast, the controller of the permanent it becomes sacrifices it "
               "at the beginning of the next cleanup step.", 3, 3)
    give_lands(g, me, 2, colors=(G,))
    me.hand.append(fs)
    g._fast_cast = me
    assert g.cast(me, fs)
    run(g)
    g._fast_cast = None
    assert any(pm.name == "Sacy" for pm in me.battlefield) and g.delayed_end


def test_attack_as_though_no_defender_and_uncopyable():
    g, me, ops = new_game()
    w = put(g, build("Wall", "{1}{W}", "Creature — Wall", "Defender", 0, 4, keywords=["Defender"]), me)
    w.summoning_sick = False
    assert not w.can_attack()
    put(g, build("Roll", "{2}{G}", "Enchantment", "Creatures you control can attack as though they didn't have "
                 "defender."), me)
    assert w.can_attack()
    assert build("Solo", "{R}", "Instant", "This spell can't be copied.\nThis spell deals 2 damage to any target."
                 ).uncopyable


def test_aura_triggers_on_enchanted_permanent():
    g, me, ops = new_game()
    lnd = put(g, land("Forest", [G], basic=True), ops[0])
    _attach(g, build("Venom", "{1}{B}", "Enchantment — Aura", "Enchant land\nWhenever enchanted land becomes "
                     "tapped, its controller loses 2 life."), me, lnd)
    life = ops[0].life
    assert ops[0].pay(build("X", "{G}", "Instant", "").cost)
    run(g)
    assert life - ops[0].life == 2
    bear = put(g, creature("Bear", "1G", 2, 2), ops[0])
    cur = _attach(g, build("Curse", "{1}{B}", "Enchantment — Aura", "Enchant creature\nWhen enchanted creature is "
                           "dealt damage, destroy it."), me, bear)
    g.deal_damage(cur, bear, 1)
    run(g)
    assert bear not in ops[0].battlefield


def test_unblocked_poison_and_attacks_or_blocks():
    g, me, ops = new_game()
    a = put(g, build("Snake", "{1}{G}", "Creature — Snake", "Whenever this creature attacks and isn't blocked, "
                     "defending player gets a poison counter.", 1, 1), me)
    assert "unblocked" in a.card.triggers and "attacks" not in a.card.triggers
    t = build("Rider", "{1}{R}", "Creature — Goblin", "When this creature attacks or blocks, sacrifice it at end of "
              "combat.", 3, 3)
    assert {"attacks", "blocks"} <= set(t.triggers)
    a.summoning_sick = False
    g.active_index = g.players.index(me)
    g._resolve_combat(me, [(a, ops[0])])
    run(g)
    assert ops[0].poison == 1


def test_blocked_by_color_filter():
    g, me, ops = new_game()
    k = put(g, build("Knight", "{1}{B}{B}", "Creature — Zombie Knight", "Whenever this creature blocks or becomes "
                     "blocked by a nonblack creature, destroy that creature at end of combat.", 2, 2), me)
    blk = put(g, creature("Elf", "1G", 1, 3), ops[0])
    k.attacking, k.blocked_by, blk.blocking = ops[0], [blk], [k]
    g._combat_block_triggers([k])
    run(g)
    for fn in list(g.delayed_end):
        fn(g)
    assert blk not in ops[0].battlefield


def test_cast_restrictions_and_global_statics():
    g, me, ops = new_game()
    sp = build("Second", "{R}", "Instant", "Cast this spell only if you've cast another spell this turn.\n"
               "This spell deals 2 damage to any target.")
    assert sp.cast_only_if is not None
    give_lands(g, me, 2, colors=(R,))
    me.hand.append(sp)
    assert not g.cast(me, sp)
    put(g, build("Amulet", "{2}", "Artifact", "Lands you control enter untapped."), me)
    tl = put(g, build("Tapland", "", "Land", "This land enters tapped.\n{T}: Add {B}."), me)
    assert not tl.tapped
    put(g, build("Teferi", "{3}{W}{U}", "Creature — Human Wizard", "Each opponent can cast spells only any time "
                 "they could cast a sorcery.", 3, 4), me)
    give_lands(g, ops[0], 2, colors=(B,))
    ins = build("Dark", "{B}", "Instant", "Target player loses 1 life.")
    ops[0].hand.append(ins)
    g.active_index = g.players.index(me)
    assert not g.cast(ops[0], ins)
    vf = put(g, build("Vedalken", "{3}{U}", "Creature — Vedalken", "You may cast creature spells as though they had "
                      "flash.", 2, 3), me)
    bear = creature("Bear", "1G", 2, 2)
    me.hand.append(bear)
    assert vf.card.grant_flash == "creature" and g.flash_granted(bear)


def test_depletion_counter_removal_on_land():
    g, me, ops = new_game()
    dl = put(g, build("Depl", "", "Land", "At the beginning of your upkeep, remove a depletion counter from this "
                      "land.\nThis land doesn't untap during your untap step if it has a depletion counter on it."), me)
    dl.counters["depletion"] = 2
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    g.begin_turn(me)
    run(g)
    assert dl.counters.get("depletion") == 1


def test_counter_cost_and_end_of_combat_effects():
    g, me, ops = new_game()
    m = put(g, build("Medic", "{1}{W}", "Creature — Kithkin", "Put a -1/-1 counter on this creature: Untap this "
                     "creature.", 2, 2), me)
    m.tapped = True
    assert g.activate_ability(m, 0)
    run(g)
    assert not m.tapped and m.counters.get("-1/-1") == 1
    fe = build("Fog", "{2}{U}", "Creature — Elemental", "When this creature attacks or blocks, destroy it at end of "
               "combat.", 4, 4)
    pm = put(g, fe, me)
    pm.card.triggers["blocks"](g, pm, subject=None)
    for fn in list(g.delayed_end):
        fn(g)
    assert pm not in me.battlefield


def test_borderpost_and_tap_creature_alt_costs():
    g, me, ops = new_game()
    bp = build("Post", "{1}{G}{U}", "Artifact", "You may pay {1} and return a basic land you control to its owner's "
               "hand rather than pay this spell's mana cost.\n{T}: Add {G} or {U}.")
    put(g, land("Forest", [G], basic=True), me)
    put(g, land("Forest", [G], basic=True), me)
    me.hand.append(bp)
    assert g.cast(me, bp)
    run(g)
    assert any(pm.name == "Post" for pm in me.battlefield) and any(c.name == "Forest" for c in me.hand)
    g, me, ops = new_game()
    af = build("Favor", "{3}{W}", "Instant", "If you control a Plains, you may tap an untapped creature you control "
               "rather than pay this spell's mana cost.\nCreate a 4/4 white Angel creature token with flying.")
    put(g, land("Plains", [W], basic=True), me)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    me.hand.append(af)
    assert g.cast(me, af)
    run(g)
    assert bear.tapped and any(pm.name == "Angel" for pm in me.battlefield)


def test_blood_moon_urborg_null_rod_and_choke():
    import cardsdb
    g, me, ops = new_game()
    dual = put(g, cardsdb.build_card_from_data({"name": "Trop", "type_line": "Land — Forest Island", "mana_cost": "",
                                                "oracle_text": "({T}: Add {G} or {U}.)", "produced_mana": ["G", "U"]}), me)
    bm = put(g, build("Moon", "{2}{R}", "Enchantment", "Nonbasic lands are Mountains."), ops[0])
    assert me.produced(dual) == {"R": 1}
    g.to_graveyard(bm, "test")
    put(g, build("Urb", "{2}{B}", "Enchantment", "Each land is a Swamp in addition to its other land types."), ops[0])
    assert "B" in me.produced(dual)
    sol = put(g, cardsdb.build_card_from_data({"name": "Rock", "type_line": "Artifact", "mana_cost": "{1}",
                                               "oracle_text": "{T}: Add {C}{C}.", "produced_mana": ["C"]}), me)
    assert sol in me.mana_sources()
    put(g, build("Rod", "{2}", "Artifact", "Activated abilities of artifacts can't be activated."), ops[0])
    assert sol not in me.mana_sources()
    isl = put(g, land("Island", [U], basic=True), me)
    isl.tapped = True
    put(g, build("Choke", "{2}{G}", "Enchantment", "Islands don't untap during their controllers' untap steps."), ops[0])
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(3)]
    g.begin_turn(me)
    assert isl.tapped


def test_aura_defender_counter_on_host_and_when_another_dies():
    g, me, ops = new_game()
    assert "defender" in build("Trap", "{W}", "Enchantment — Aura", "Enchant creature\nEnchanted creature has "
                               "defender.").aura_keywords
    bear = put(g, creature("Bear", "1G", 3, 3), ops[0])
    teth = _attach(g, build("Tether", "{1}{B}", "Enchantment — Aura", "Enchant creature\nAt the beginning of your "
                            "upkeep, put a -1/-1 counter on enchanted creature."), me, bear)
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(3)]
    g.begin_turn(me)
    run(g)
    assert bear.counters.get("-1/-1") == 1 and teth in me.battlefield
    life = me.life
    put(g, build("Mourner", "{1}{W}", "Creature — Human", "When another creature you control dies, you gain 1 life.",
                 1, 1), me)
    x = put(g, creature("X", "1G", 1, 1), me)
    g.to_graveyard(x, "test")
    run(g)
    assert me.life == life + 1


def test_life_loss_triggers_and_exquisite_combo():
    g, me, ops = new_game()
    put(g, build("Blood", "{4}{B}", "Enchantment", "Whenever an opponent loses life, you gain that much life."), me)
    life = me.life
    ops[0].life -= 3
    run(g)
    assert me.life == life + 3
    put(g, build("Bond", "{3}{B}{B}", "Enchantment", "Whenever you gain life, target opponent loses that much life."), me)
    g.gain_life(me, 1)
    run(g)
    assert all(o.lost for o in ops)


def test_attacks_you_trigger_mana_spent_counters_and_revealed_hand():
    import cardsdb
    g, me, ops = new_game()
    put(g, build("Reck", "{3}{B}", "Enchantment", "Whenever a creature attacks you or a planeswalker you control, "
                 "that creature's controller loses 1 life."), me)
    ogre = put(g, creature("Ogre", "2R", 3, 3), ops[0])
    ogre.summoning_sick = False
    life = ops[0].life
    g.active_index = g.players.index(ops[0])
    g._declare_attackers(ops[0], [(ogre, me)])
    run(g)
    assert life - ops[0].life == 1
    g, me, ops = new_game()
    dy = cardsdb.build_card_from_data({"name": "Dyad, Amalgam", "type_line": "Artifact Creature — Construct",
                                       "mana_cost": "{3}", "power": "0", "toughness": "0",
                                       "oracle_text": "Dyad enters with a number of +1/+1 counters on it equal to the "
                                                      "amount of mana spent to cast it."})
    give_lands(g, me, 3, colors=(G,))
    me.hand.append(dy)
    assert g.cast(me, dy)
    run(g)
    pm = next(p for p in me.battlefield if p.name.startswith("Dyad"))
    assert pm.counters.get("+1/+1") == 3
    assert "revealed" not in g._player_state(ops[0])
    put(g, build("Seer", "{3}{U}", "Enchantment", "Your opponents play with their hands revealed."), me)
    assert "revealed" in g._player_state(ops[0]) and "revealed" not in g._player_state(me)


def test_ability_cost_reduction():
    g, me, ops = new_game()
    put(g, build("Familiar", "{G}{U}", "Creature — Rat", "Activated abilities of creatures you control cost {2} less "
                 "to activate. This effect can't reduce the mana in that cost to less than one mana.", 1, 1), me)
    pump = put(g, build("Pumper", "{1}{G}", "Creature — Elf", "{3}: This creature gets +1/+1 until end of turn.",
                        1, 1), me)
    give_lands(g, me, 1, colors=(G,))
    assert g.activate_ability(pump, 0)
    run(g)
    assert pump.power == 2


def test_sacrifice_kicker_crew_bonus_and_offturn_cast_trigger():
    g, me, ops = new_game()
    ej = build("Eject", "{4}{R}", "Sorcery", "Kicker—Sacrifice an artifact or creature.\nThis spell deals 4 damage "
               "to target creature. If this spell was kicked, it deals 4 damage to each opponent too.")
    assert ej._kicker_sac == (1, "artifact|creature")
    give_lands(g, me, 5, colors=(R,))
    tok = put(g, creature("Tok", "", 1, 1), me)
    tok.is_token = True
    put(g, creature("Foe", "1G", 2, 2), ops[0])
    me.hand.append(ej)
    assert g.cast(me, ej)
    run(g)
    assert tok not in me.battlefield and ej._kicked
    assert build("Cap", "{1}{W}", "Creature — Human", "This creature crews Vehicles as though its power were 2 "
                 "greater.", 1, 1).crew_bonus == 2
    g, me, ops = new_game()
    put(g, build("Jockey", "{1}{R}", "Creature — Human", "Whenever a player casts a spell, if it's not their turn, "
                 "this creature deals 2 damage to them.", 2, 2), me)
    g.active_index = g.players.index(me)
    give_lands(g, ops[0], 1, colors=(R,))
    sp = build("Shock", "{R}", "Instant", "Shock deals 2 damage to any target.")
    ops[0].hand.append(sp)
    life = ops[0].life
    assert g.cast(ops[0], sp, targets=[me])
    run(g)
    assert life - ops[0].life == 2


def test_unblocked_assigns_no_damage_and_group_unblocked():
    g, me, ops = new_game()
    k = put(g, build("Keeper", "{4}{B}", "Creature — Zombie Giant", "Whenever this creature attacks and isn't "
                     "blocked, it assigns no combat damage this turn and defending player loses 2 life.", 5, 5), me)
    k.summoning_sick = False
    g.active_index = g.players.index(me)
    life = ops[0].life
    g._resolve_combat(me, [(k, ops[0])])
    run(g)
    assert life - ops[0].life == 2
    g, me, ops = new_game()
    put(g, build("Bandit", "{1}{B}", "Creature — Goblin Rogue", "Whenever a Rogue you control attacks and isn't "
                 "blocked, it gets +2/+1 until end of turn.", 2, 1), me)
    r = put(g, creature("Rogue", "1B", 1, 1, subtypes=("Rogue",)), me)
    r.summoning_sick = False
    g.active_index = g.players.index(me)
    life = ops[0].life
    g._resolve_combat(me, [(r, ops[0])])
    run(g)
    assert life - ops[0].life == 3


def test_astral_dragon_copies_noncreature_as_dragons_without_loop():
    import cardsdb
    g, me, ops = new_game()
    put(g, cardsdb.build_card_from_data({"name": "Rock", "type_line": "Artifact", "mana_cost": "{2}",
                                         "oracle_text": "{T}: Add {C}.", "produced_mana": ["C"]}), ops[0])
    put(g, build("Astral", "{6}{U}{U}", "Creature — Dragon", "Flying\nWhen this creature enters, create two tokens "
                 "that are copies of target noncreature permanent, except they're 3/3 Dragon creatures in addition "
                 "to their other types, and they have flying.", 4, 4, keywords=["Flying"]), me)
    toks = [pm for pm in me.battlefield if pm.is_token]
    assert len(toks) == 2 and all(t.name == "Rock" and t.power == 3 and t.has("flying") for t in toks)
