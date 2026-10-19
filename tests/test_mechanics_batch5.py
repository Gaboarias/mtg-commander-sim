"""Batch 5: plantillas comunes — Mass Polymorph, auras de bloqueo / control,
restricciones de ataque y enderezar, evasión por fuerza, costes adicionales."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402

_POLY = ("Exile all creatures you control, then reveal cards from the top of your library "
         "until you reveal that many creature cards. Put all creature cards revealed this way "
         "onto the battlefield, then shuffle the rest of the revealed cards into your library.")


def test_mass_polymorph_only_exiles_mine_and_reveals():
    g, me, ops = new_game()
    give_lands(g, me, 6, colors=(U,))
    put(g, creature("Tok1", "1G", 1, 1), me)
    put(g, creature("Tok2", "1G", 1, 1), me)
    theirs = put(g, creature("Theirs", "1B", 2, 2), ops[0])
    me.library += [creature("Big1", "6G", 6, 6), land("Forest", [G], basic=True),
                   creature("Big2", "6G", 7, 7)]
    mp = build("Mass Polymorph", "{5}{U}", "Sorcery", _POLY)
    assert "wipe" not in mp.tags
    me.hand.append(mp)
    assert g.cast(me, mp)
    run(g)
    names = {pm.name for pm in me.battlefield if pm.is_creature()}
    assert names == {"Big1", "Big2"}
    assert theirs in ops[0].battlefield
    assert any(c.name == "Tok1" for c in me.exile)


def test_pacifism_stops_attack_and_block():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "1B", 3, 3), ops[0])
    put(g, build("Pacifism", "{1}{W}", "Enchantment — Aura",
                 "Enchant creature\nEnchanted creature can't attack or block."), me)
    foe.summoning_sick = False
    assert not foe.can_attack() and foe.cant_block


def test_aura_doesnt_untap_and_taps_on_enter():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "1B", 3, 3), ops[0])
    put(g, build("Claustro", "{1}{U}{U}", "Enchantment — Aura",
                 "Enchant creature\nWhen this Aura enters, tap enchanted creature.\n"
                 "Enchanted creature doesn't untap during its controller's untap step."), me)
    assert foe.tapped
    g.begin_turn(ops[0])
    assert foe.tapped


def test_control_aura_steals_and_returns():
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "1B", 5, 5), ops[0])
    mc = put(g, build("Mind Control", "{3}{U}{U}", "Enchantment — Aura",
                      "Enchant creature\nYou control enchanted creature."), me)
    assert foe in me.battlefield and foe.controller is me
    g.to_graveyard(mc, "test")
    run(g)
    assert foe in ops[0].battlefield and foe.controller is ops[0]


def test_attacks_each_combat_and_doesnt_untap():
    g, me, ops = new_game()
    berserk = put(g, build("Berserk", "{1}{R}", "Creature — Goblin",
                           "This creature attacks each combat if able.", 0, 1), me)
    berserk.summoning_sick = False
    atk = me.policy.declare_attackers(g, me)
    assert any((a[0] if isinstance(a, tuple) else a) is berserk for a in atk)
    golem = put(g, build("Golem", "{4}", "Artifact Creature — Golem",
                         "This creature doesn't untap during your untap step.", 4, 4), me)
    golem.tapped = True
    g.begin_turn(me)
    assert golem.tapped


def test_power_evasion_and_max_blockers():
    g, me, ops = new_game()
    wolf = put(g, build("Wolf", "{2}{G}", "Creature — Wolf",
                        "This creature can't be blocked by creatures with power 2 or less.", 3, 3), me)
    small = put(g, creature("Small", "1W", 2, 5), ops[0])
    big = put(g, creature("Big", "3W", 3, 3), ops[0])
    assert not g._can_block_evasion(wolf, small)
    assert g._can_block_evasion(wolf, big)
    kr = put(g, build("Krushok", "{4}{G}", "Creature — Beast",
                      "This creature can't be blocked by more than one creature.", 6, 6), me)
    kr.attacking = ops[0]
    g._apply_block_pairs([kr], [(kr, small), (kr, big)])
    assert len(kr.blocked_by) == 1


def test_enters_with_minus_counters_and_end_step_sacrifice():
    g, me, ops = new_game()
    h = put(g, build("Hatchling", "{3}", "Creature — Elemental",
                     "This creature enters with four -1/-1 counters on it.", 6, 6), me)
    assert h.power == 2
    arc = put(g, build("Arc Runner", "{2}{R}", "Creature — Elemental Ox",
                       "Haste\nAt the beginning of the end step, sacrifice this creature.", 5, 1), me)
    g.end_turn(me)
    run(g)
    assert arc not in me.battlefield


def test_aura_returns_to_hand():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    asp = put(g, build("Aspect", "{2}{G}", "Enchantment — Aura",
                       "Enchant creature\nEnchanted creature has shroud.\nWhen this Aura is put "
                       "into a graveyard from the battlefield, return it to its owner's hand."), me)
    assert asp.enchanting is bear
    g.to_graveyard(bear, "test")
    run(g)
    run(g)                                     # el aura cae por SBA y su disparo resuelve
    assert any(c.name == "Aspect" for c in me.hand)


def test_additional_cost_sacrifice_artifact_and_self_exile():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(R,))
    give_lands(g, me, 1, colors=(W,), name="Plains")
    sp = build("Forge", "{R}", "Sorcery", "As an additional cost to cast this spell, sacrifice an "
               "artifact.\nYou gain 3 life.")
    me.hand.append(sp)
    assert not g.cast(me, sp)                      # sin artefacto no se puede lanzar
    put(g, build("Trinket", "{1}", "Artifact", ""), me)
    life = me.life
    assert g.cast(me, sp)
    run(g)
    assert me.life == life + 3 and not any(pm.name == "Trinket" for pm in me.battlefield)
    wr = build("Wrathy", "{W}", "Sorcery", "You gain 2 life.\nExile Wrathy.")
    me.hand.append(wr)
    assert g.cast(me, wr)
    run(g)
    assert wr in me.exile


def test_during_your_turn_first_strike_and_hand_rules():
    g, me, ops = new_game()
    d = put(g, build("Duelist", "{1}{W}", "Creature — Human",
                     "During your turn, this creature has first strike.", 2, 2), me)
    g.active_index = 0
    assert d.has("first_strike")
    g.active_index = 1
    assert not d.has("first_strike")
    g.active_index = 0
    put(g, build("Spellbook", "{0}", "Artifact", "You have no maximum hand size."), me)
    me.hand = [creature(f"C{k}", "1G", 1, 1) for k in range(10)]
    g.end_turn(me)
    assert len(me.hand) == 10
