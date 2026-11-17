"""Counter Intelligence (Inspirit, Flagship Vessel): station, proliferate (Tekuthal x2, Kilo,
Peacemaker con crímenes, Ripples con fase), sunburst/converge (Solar Array, Lux Artillery, Etched
Oracle, Crawler), Cloud Key, Darksteel Reactor, Depthshaker Titan, Gavel, Seedshark/Incubator,
Thunderhulk, Wake the Past, Hangarback, Experimental Augury, Moxite Refinery, Empowered
Autogenerator, Coretapper, Mycosynth Gardens y Emry."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import U, W, R, B, G, Cost  # noqa: E402
from cards import creature  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands, artifact  # noqa: E402

_D = {
    'Insight Engine': ('{2}{U}', 'Artifact', '{2}, {T}: Put a charge counter on this artifact, then draw a card for each charge counter on it.', None, None, None),
    'Tekuthal, Inquiry Dominus': ('{2}{U}{U}', 'Legendary Creature — Phyrexian Horror', 'Flying\nIf you would proliferate, proliferate twice instead.\n{1}{U/P}{U/P}, Remove three counters from among other artifacts, creatures, and planeswalkers you control: Put an indestructible counter on Tekuthal. ({U/P} can be paid with either {U} or 2 life.)', '3', '5', ['Flying', 'Proliferate']),
    'Alibou, Ancient Witness': ('{3}{R}{W}', 'Legendary Artifact Creature — Golem', 'Other artifact creatures you control have haste.\nWhenever one or more artifact creatures you control attack, Alibou deals X damage to any target and you scry X, where X is the number of tapped artifacts you control.', '4', '5', ['Scry']),
    'Cloud Key': ('{3}', 'Artifact', 'As this artifact enters, choose artifact, creature, enchantment, instant, or sorcery.\nSpells you cast of the chosen type cost {1} less to cast.', None, None, None),
    'Darksteel Reactor': ('{4}', 'Artifact', 'Indestructible (Effects that say "destroy" don\'t destroy this artifact.)\nAt the beginning of your upkeep, you may put a charge counter on this artifact.\nWhen this artifact has twenty or more charge counters on it, you win the game.', None, None, ['Indestructible']),
    'Depthshaker Titan': ('{5}{R}{R}', 'Artifact Creature — Robot', 'When this creature enters, any number of target noncreature artifacts you control become 3/3 artifact creatures. Sacrifice them at the beginning of the next end step.\nEach artifact creature you control has melee, trample, and haste. (Whenever a creature with melee attacks, it gets +1/+1 until end of turn for each opponent you attacked this combat.)', '5', '5', None),
    'Gavel of the Righteous': ('{2}', 'Artifact — Equipment', 'At the beginning of combat on your turn, put a charge counter on this Equipment.\nEquipped creature gets +1/+1 for each counter on this Equipment.\nAs long as this Equipment has four or more counters on it, equipped creature has double strike.\nEquip—Pay {3} or remove a counter from this Equipment.', None, None, ['Equip']),
    'Lux Artillery': ('{4}', 'Artifact', 'Whenever you cast an artifact creature spell, it gains sunburst. (It enters with a +1/+1 counter on it for each color of mana spent to cast it.)\nAt the beginning of your end step, if there are thirty or more counters among artifacts and creatures you control, this artifact deals 10 damage to each opponent.', None, None, None),
    'Chrome Host Seedshark': ('{2}{U}', 'Creature — Phyrexian Shark', 'Flying\nWhenever you cast a noncreature spell, incubate X, where X is that spell\'s mana value. (Create an Incubator token with X +1/+1 counters on it and "{2}: Transform this token." It transforms into a 0/0 Phyrexian artifact creature.)', '2', '4', ['Flying', 'Incubate', 'Transform']),
    'Threefold Thunderhulk': ('{7}', 'Artifact Creature — Gnome', 'This creature enters with three +1/+1 counters on it.\nWhenever this creature enters or attacks, create a number of 1/1 colorless Gnome artifact creature tokens equal to its power.\n{2}, Sacrifice another artifact: Put a +1/+1 counter on this creature.', '0', '0', None),
    'Wake the Past': ('{5}{R}{W}', 'Sorcery', 'Return all artifact cards from your graveyard to the battlefield. They gain haste until end of turn.', None, None, None),
    'Hangarback Walker': ('{X}{X}', 'Artifact Creature — Construct', 'This creature enters with X +1/+1 counters on it.\nWhen this creature dies, create a 1/1 colorless Thopter artifact creature token with flying for each +1/+1 counter on this creature.\n{1}, {T}: Put a +1/+1 counter on this creature.', '0', '0', None),
    'Experimental Augury': ('{1}{U}', 'Instant', 'Look at the top three cards of your library. Put one of them into your hand and the rest on the bottom of your library in any order. Proliferate. (Choose any number of permanents and/or players, then give each another counter of each kind already there.)', None, None, ['Proliferate']),
    'Moxite Refinery': ('{2}', 'Artifact', '{2}, {T}, Remove X counters from an artifact or creature you control: Choose one. Activate only as a sorcery.\n• Put X charge counters on target artifact.\n• Put X +1/+1 counters on target creature.', None, None, None),
    'Empowered Autogenerator': ('{4}', 'Artifact', 'This artifact enters tapped.\n{T}: Put a charge counter on this artifact. Add X mana of any one color, where X is the number of charge counters on this artifact.', None, None, None),
    'Patrolling Peacemaker': ('{2}{W}', 'Artifact Creature — Robot Soldier', "This creature enters with two +1/+1 counters on it.\nWhenever an opponent commits a crime, proliferate. (They commit a crime if they target an opponent, anything an opponent controls, and/or cards in an opponent's graveyard. To proliferate, you choose any number of permanents and/or players, then give each another counter of each kind already there.)", '0', '0', ['Proliferate']),
    'Solar Array': ('{3}', 'Artifact', "{T}: Add one mana of any color. When you next cast an artifact spell this turn, that spell gains sunburst. (If it's a creature, it enters with a +1/+1 counter on it for each color of mana spent to cast it. Otherwise, it enters with that many charge counters on it.)", None, None, None),
    'Etched Oracle': ('{4}', 'Artifact Creature — Wizard', 'Sunburst (This creature enters with a +1/+1 counter on it for each color of mana spent to cast it.)\n{1}, Remove four +1/+1 counters from this creature: Target player draws three cards.', '0', '0', ['Sunburst']),
    'Crystalline Crawler': ('{4}', 'Artifact Creature — Construct', 'Converge — This creature enters with a +1/+1 counter on it for each color of mana spent to cast it.\nRemove a +1/+1 counter from this creature: Add one mana of any color.\n{T}: Put a +1/+1 counter on this creature.', '1', '1', ['Converge']),
    'Coretapper': ('{2}', 'Artifact Creature — Myr', '{T}: Put a charge counter on target artifact.\nSacrifice this creature: Put two charge counters on target artifact.', '1', '1', None),
    'The Mycosynth Gardens': (None, 'Land — Sphere', '{T}: Add {C}.\n{1}, {T}: Add one mana of any color.\n{X}, {T}: This land becomes a copy of target nontoken artifact you control with mana value X.', None, None, None),
    'Ripples of Potential': ('{1}{U}', 'Instant', "Proliferate, then choose any number of permanents you control that had a counter put on them this way. Those permanents phase out. (To proliferate, choose any number of permanents and/or players, then give each another counter of each kind already there. Treat phased-out permanents and anything attached to them as though they don't exist until their controller's next turn.)", None, None, ['Proliferate']),
    'Emry, Lurker of the Loch': ('{2}{U}', 'Legendary Creature — Merfolk Wizard', 'Affinity for artifacts (This spell costs {1} less to cast for each artifact you control.)\nWhen Emry enters, mill four cards.\n{T}: Choose target artifact card in your graveyard. You may cast that card this turn. (You still pay its costs. Timing rules still apply.)', '1', '2', ['Affinity', 'Mill']),
    'Kilo, Apogee Mind': ('{U}{R}{W}', 'Legendary Artifact Creature — Robot Artificer', 'Haste\nWhenever Kilo becomes tapped, proliferate. (Choose any number of permanents and/or players, then give each another counter of each kind already there.)', '3', '3', ['Haste', 'Proliferate']),
    'Inspirit, Flagship Vessel': ('{U}{R}{W}', 'Legendary Artifact — Spacecraft', "Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery. It's an artifact creature at 8+.)\n1+ | At the beginning of combat on your turn, put your choice of a +1/+1 counter or two charge counters on up to one other target artifact.\n8+ | Flying\nOther artifacts you control have hexproof and indestructible.", '5', '5', ['Station']),
    'Steel Overseer': ('{2}', 'Artifact Creature — Construct', '{T}: Put a +1/+1 counter on each artifact creature you control.', '1', '1', None),
    "Tezzeret's Gambit": ('{3}{U/P}', 'Sorcery', '({U/P} can be paid with either {U} or 2 life.)\nDraw two cards, then proliferate. (Choose any number of permanents and/or players, then give each another counter of each kind already there.)', None, None, ['Proliferate']),
}


_KW = {"Inspirit, Flagship Vessel": ("Station",)}


def _mk(name):
    mc, tl, ot, p, t, _kw = _D[name]
    return build(name, mc or "", tl, ot, p=p, t=t, keywords=_KW.get(name, ()))


def _choose(g, label):
    ch = g.pending_choice
    assert ch is not None, "no hay elección pendiente"
    idx = next(o["i"] for o in ch["options"] if label in o["name"])
    g.pending_choice = None
    ch["_apply"](idx)


def _none(g):
    ch = g.pending_choice
    assert ch is not None
    g.pending_choice = None
    ch["_apply"](None)


def test_insight_engine_draws_per_counter():
    g, me, _ = new_game()
    ie = put(g, _mk("Insight Engine"), me)
    give_lands(g, me, 4)
    h = len(me.hand)
    assert g.activate_ability(ie, 0)
    run(g)
    assert ie.counters["charge"] == 1 and len(me.hand) == h + 1
    for pm in me.battlefield:
        pm.tapped = False
    g.activate_ability(ie, 0)
    run(g)
    assert ie.counters["charge"] == 2 and len(me.hand) == h + 3


def test_tekuthal_proliferates_twice_and_indestructible_counter():
    g, me, _ = new_game()
    tk = put(g, _mk("Tekuthal, Inquiry Dominus"), me)
    r = put(g, artifact("R"), me)
    g.add_counters(r, "charge", 1)
    _mk("Tezzeret's Gambit").on_cast_resolve(g, me, [])
    run(g)
    assert r.counters["charge"] == 3
    give_lands(g, me, 1)
    life = me.life
    i = next(k for k, a in enumerate(tk.card.activated_abilities) if "indestructible" in a["label"])
    assert g.activate_ability(tk, i)
    run(g)
    assert r.counters["charge"] == 0 and me.life == life - 4      # {U/P}{U/P} pagados con vida
    assert tk.has("indestructible") and tk.counters["indestructible"] == 1


def test_alibou_haste_and_attack_damage_scry():
    g, me, ops = new_game()
    put(g, _mk("Alibou, Ancient Witness"), me)
    gol = put(g, creature("Gol", "3", 3, 3), me)
    gol.card.types = {"artifact", "creature"}
    assert gol.has("haste")
    put(g, artifact("Tapped"), me).tapped = True
    l0 = ops[0].life
    g.active_index = 0
    g._declare_attackers(me, [(gol, ops[0])])
    run(g)
    assert ops[0].life == l0 - 2      # X = artefactos girados (Gol atacando + Tapped)


def test_cloud_key_chosen_type_discount():
    g, me, _ = new_game()
    g.interactive_human = me
    put(g, _mk("Cloud Key"), me)
    _choose(g, "conjuro")
    sorc = build("S", "{2}{U}", "Sorcery", "Draw a card.")
    art = build("A", "{3}", "Artifact", "")
    assert g.effective_cost(me, sorc).cmc == 2 and g.effective_cost(me, art).cmc == 3


def test_darksteel_reactor_wins_at_twenty():
    g, me, ops = new_game()
    dr = put(g, _mk("Darksteel Reactor"), me)
    g.add_counters(dr, "charge", 20)
    g.sba()
    assert ops[0].lost


def test_depthshaker_titan_animates_and_grants():
    g, me, ops = new_game()
    g.interactive_human = me
    rock = put(g, artifact("Rock"), me)
    put(g, _mk("Depthshaker Titan"), me)
    _choose(g, "Rock")            # único candidato: al elegirlo termina
    assert rock.is_creature() and rock.power == 3 and rock.toughness == 3
    assert rock.has("haste") and rock.has("trample") and rock.has("melee")
    g.active_index = 0
    rock.summoning_sick = False
    g._declare_attackers(me, [(rock, ops[0])])
    assert rock.power == 4                       # melé: +1/+1 por oponente atacado
    for f in list(g.delayed_end):
        f(g)
    assert rock not in me.battlefield


def test_gavel_counters_double_strike_and_alt_equip():
    g, me, _ = new_game()
    gv = put(g, _mk("Gavel of the Righteous"), me)
    c = put(g, creature("C", "G", 2, 2), me)
    gv.enchanting = c
    for _ in range(3):
        g.emit("begin_combat", player=me)
        run(g)
    assert c.power == 5 and not c.has("double_strike")
    g.emit("begin_combat", player=me)
    run(g)
    assert c.power == 6 and c.has("double_strike")
    labels = [a["label"] for a in gv.card.activated_abilities]
    assert "Equipar (quitar un contador)" in labels
    eq = next(a for a in gv.card.activated_abilities if a["label"] == "Equipar")
    assert eq["cost"].cmc == 3


def test_lux_artillery_end_step_and_sunburst_grant():
    g, me, ops = new_game()
    put(g, _mk("Lux Artillery"), me)
    c = put(g, creature("C", "G", 2, 2), me)
    g.add_counters(c, "+1/+1", 29)
    l0 = ops[0].life
    g.emit("end_step", player=me)
    run(g)
    assert ops[0].life == l0
    g.add_counters(c, "+1/+1", 1)
    g.emit("end_step", player=me)
    run(g)
    assert ops[0].life == l0 - 10
    ac = build("Bot", "{2}", "Artifact Creature — Construct", "", p=1, t=1)
    g.emit("cast", player=me, card=ac)
    run(g)
    assert getattr(ac, "_sunburst_grant", False)


def test_seedshark_incubator_transforms():
    g, me, _ = new_game()
    put(g, _mk("Chrome Host Seedshark"), me)
    g.emit("cast", player=me, card=build("Spell", "{2}{U}", "Instant", "Draw a card."))
    run(g)
    inc = [x for x in me.battlefield if x.name == "Incubator"]
    assert inc and not inc[0].is_creature() and inc[0].counters["+1/+1"] == 3
    give_lands(g, me, 2)
    assert g.activate_ability(inc[0], 0)
    run(g)
    assert inc[0].is_creature() and inc[0].has_subtype("Phyrexian") and inc[0].power == 3


def test_thunderhulk_gnomes_equal_power():
    g, me, ops = new_game()
    th = put(g, _mk("Threefold Thunderhulk"), me)
    gn = [x for x in me.battlefield if x.name == "Gnome"]
    assert th.power == 3 and len(gn) == 3 and "artifact" in gn[0].card.types
    g.active_index = 0
    th.summoning_sick = False
    g._declare_attackers(me, [(th, ops[0])])
    run(g)
    assert len([x for x in me.battlefield if x.name == "Gnome"]) == 6


def test_wake_the_past_returns_artifact_creatures_with_haste():
    g, me, _ = new_game()
    me.graveyard += [artifact("A1"), _mk("Patrolling Peacemaker")]
    _mk("Wake the Past").on_cast_resolve(g, me, [])
    run(g)
    names = {x.name for x in me.battlefield}
    assert {"A1", "Patrolling Peacemaker"} <= names
    assert next(x for x in me.battlefield if x.name == "Patrolling Peacemaker").has("haste")


def test_hangarback_one_thopter_per_counter():
    g, me, _ = new_game()
    hwc = _mk("Hangarback Walker")
    hwc.etb_counters = {"+1/+1": 3}               # X = 3
    hw = put(g, hwc, me)
    g.destroy(hw)
    run(g)
    th = [x for x in me.battlefield if x.name == "Thopter"]
    assert len(th) == 3 and th[0].has("flying") and "artifact" in th[0].card.types


def test_experimental_augury_one_to_hand_rest_bottom_proliferate():
    g, me, _ = new_game()
    r = put(g, artifact("R"), me)
    g.add_counters(r, "charge", 1)
    top3 = me.library[-3:]
    h = len(me.hand)
    _mk("Experimental Augury").on_cast_resolve(g, me, [])
    run(g)
    assert len(me.hand) == h + 1 and r.counters["charge"] == 2
    assert all(x in me.library[:2] for x in top3 if x not in me.hand)


def test_moxite_refinery_moves_x_counters():
    g, me, _ = new_game()
    mx = put(g, _mk("Moxite Refinery"), me)
    src = put(g, artifact("Src"), me)
    g.add_counters(src, "charge", 3)
    c = put(g, creature("C", "G", 1, 1), me)
    give_lands(g, me, 2)
    g._xctr_src = src
    assert g.activate_ability(mx, 1, targets=[c], x=2)
    g._xctr_src = None
    run(g)
    assert src.counters["charge"] == 1 and c.counters["+1/+1"] == 2


def test_empowered_autogenerator_mana_grows():
    g, me, _ = new_game()
    ea = put(g, _mk("Empowered Autogenerator"), me)
    assert ea.tapped
    ea.tapped = False
    assert me.produced(ea)["R"] == 1
    assert me.pay(Cost(1, ()))
    assert ea.counters["charge"] == 1
    ea.tapped = False
    assert me.produced(ea)["G"] == 2


def test_patrolling_peacemaker_proliferates_on_opponent_crime():
    g, me, ops = new_game()
    pp = put(g, _mk("Patrolling Peacemaker"), me)
    assert pp.counters["+1/+1"] == 2
    g.emit("opp_crime", criminal=ops[0])
    run(g)
    assert pp.counters["+1/+1"] == 3


def test_sunburst_and_converge_flags():
    eo, cc = _mk("Etched Oracle"), _mk("Crystalline Crawler")
    assert getattr(eo, "sunburst", False) and not (eo.etb_counters or {}).get("+1/+1")
    assert getattr(cc, "converge_ctr", None) == "+1/+1" and not (cc.etb_counters or {}).get("+1/+1")
    assert getattr(_mk("Solar Array"), "solar_array", False)


def test_coretapper_targets_artifact():
    g, me, _ = new_game()
    ct = put(g, _mk("Coretapper"), me)
    ct.summoning_sick = False
    r = put(g, artifact("R"), me)
    assert ct.card.activated_abilities[0]["target_spec"] == "ben_artifact"
    g.activate_ability(ct, 0, targets=[r])
    run(g)
    assert r.counters["charge"] == 1
    g.activate_ability(ct, 1, targets=[r])
    run(g)
    assert r.counters["charge"] == 3 and ct not in me.battlefield


def test_mycosynth_gardens_copies_artifact_of_mv_x():
    g, me, _ = new_game()
    mg = put(g, _mk("The Mycosynth Gardens"), me)
    ie = put(g, _mk("Insight Engine"), me)
    give_lands(g, me, 3)
    i = next(k for k, a in enumerate(mg.card.activated_abilities) if a.get("x_from_target_mv"))
    assert g.activate_ability(mg, i, targets=[ie], x=3)
    run(g)
    assert mg.name == "Insight Engine" and not mg.card.is_land()


def test_ripples_of_potential_phases_out_chosen():
    g, me, _ = new_game()
    g.interactive_human = me
    r = put(g, artifact("R"), me)
    g.add_counters(r, "charge", 1)
    _mk("Ripples of Potential").on_cast_resolve(g, me, [])
    _choose(g, "R")              # proliferar (único candidato: termina solo)
    _choose(g, "R")              # fase (único candidato: termina solo)
    assert r.counters["charge"] == 2 and r not in me.battlefield and any(pm is r for pm, _c in g.phased)


def test_emry_lets_cast_artifact_from_graveyard_this_turn():
    g, me, _ = new_game()
    em = put(g, _mk("Emry, Lurker of the Loch"), me)
    assert len(me.graveyard) == 4
    art = artifact("GyArt")
    me.graveyard.append(art)
    em.summoning_sick = False
    assert g.activate_ability(em, 0)
    run(g)
    give_lands(g, me, 2)
    assert g.play_from_graveyard(me, art)
    run(g)
    assert any(x.name == "GyArt" for x in me.battlefield)
    other = artifact("Later")
    me.graveyard.append(other)
    assert not g.play_from_graveyard(me, other)


def test_kilo_proliferates_when_tapped():
    g, me, ops = new_game()
    k = put(g, _mk("Kilo, Apogee Mind"), me)
    r = put(g, artifact("R"), me)
    g.add_counters(r, "charge", 1)
    g.active_index = 0
    k.summoning_sick = False
    g._declare_attackers(me, [(k, ops[0])])
    run(g)
    assert r.counters["charge"] == 2


def test_inspirit_station_tiers():
    g, me, _ = new_game()
    insp = put(g, _mk("Inspirit, Flagship Vessel"), me)
    rock = put(g, artifact("Rock"), me)
    assert not insp.is_creature()
    g.add_counters(insp, "charge", 8)
    assert insp.is_creature() and insp.has("flying")
    assert rock.has("hexproof") and rock.has("indestructible")


def _ig():
    import decks
    import interactive
    defs = [("Tu deck",) + decks.build("marvel"), ("Rival",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    return ig


def test_moxite_refinery_human_ui_picks_source_and_x():
    from cards import land
    ig = _ig()
    g, me = ig.g, ig.human()
    g.active_index = 0
    for _ in range(3):
        g.move_to_battlefield(land("Src", [U]), me)
    mx = g.move_to_battlefield(_mk("Moxite Refinery"), me)
    src = g.move_to_battlefield(artifact("Battery"), me)
    g.add_counters(src, "charge", 3)
    c = g.move_to_battlefield(creature("C", "G", 1, 1), me)
    run(g)
    ig.activate_ability(mx.uid, 1, [c.uid])
    ch = g.pending_choice
    assert ch and "de qué permanente" in ch["prompt"]
    _choose(g, "Battery")
    ch = g.pending_choice
    assert ch and "X" in ch["prompt"]
    ig.resolve_choice(2)
    run(g)
    assert src.counters["charge"] == 1 and c.counters["+1/+1"] == 2


def test_mycosynth_gardens_human_x_is_target_mv():
    from cards import land
    ig = _ig()
    g, me = ig.g, ig.human()
    g.active_index = 0
    for _ in range(4):
        g.move_to_battlefield(land("Src", [U]), me)
    mg = g.move_to_battlefield(_mk("The Mycosynth Gardens"), me)
    ie = g.move_to_battlefield(_mk("Insight Engine"), me)
    run(g)
    i = next(k for k, a in enumerate(mg.card.activated_abilities) if a.get("x_from_target_mv"))
    ig.activate_ability(mg.uid, i, [ie.uid])
    run(g)
    assert mg.name == "Insight Engine"
