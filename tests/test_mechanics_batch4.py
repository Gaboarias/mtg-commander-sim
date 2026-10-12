"""Batch 4B: Undaunted, Epic, Ripple, Impending, Paradigm, Provoke, Recover,
Demonstrate, Eminence, Kinship, Haunt, Forecast, Soulbond, Cases, More Than Meets
the Eye, Addendum y Bargain en criaturas."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402

_GAIN = "You gain 3 life."


def _hand(me, card):
    me.hand.append(card)
    return card


def test_undaunted_costs_less_per_opponent():
    g, me, ops = new_game(n_opp=3)
    c = build("Breach", "{6}{U}", "Sorcery", "Undaunted\nDraw a card.", keywords=["Undaunted"])
    assert g.effective_cost(me, c).cmc == 4


def test_epic_locks_casting_and_copies_each_upkeep():
    g, me, ops = new_game()
    give_lands(g, me, 5, colors=(G,))
    ep = _hand(me, build("Ep", "{2}{G}", "Sorcery", _GAIN + "\nEpic", keywords=["Epic"]))
    life = me.life
    assert g.cast(me, ep)
    run(g)
    assert me.life == life + 3
    other = _hand(me, build("Other", "{G}", "Sorcery", _GAIN))
    assert not g.cast(me, other)
    g.begin_turn(me)
    run(g)
    assert me.life == life + 6


def test_ripple_casts_same_name_from_library():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(U,))
    rp = _hand(me, build("Rip", "{U}", "Instant", "Ripple 4\n" + _GAIN, keywords=["Ripple"]))
    me.library.append(build("Rip", "{U}", "Instant", "Ripple 4\n" + _GAIN, keywords=["Ripple"]))
    life = me.life
    assert g.cast(me, rp)
    run(g)
    assert me.life == life + 6


def test_impending_enters_as_noncreature_and_counts_down():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(B,))
    ov = _hand(me, build("Overlord", "{3}{B}{B}", "Enchantment Creature — Avatar",
                         "Impending 2—{1}{B}\nWhen this permanent enters, you gain 3 life.",
                         5, 5, keywords=["Impending"]))
    life = me.life
    assert g.cast_impending(me, ov)
    run(g)
    pm = next(p for p in me.battlefield if p.name == "Overlord")
    assert not pm.is_creature() and pm.counters.get("time") == 2
    assert me.life == life + 3
    g.end_turn(me)
    g.end_turn(me)
    assert pm.is_creature()


def test_paradigm_exiles_and_recasts_copy():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(B,))
    pd = _hand(me, build("Para", "{1}{B}", "Sorcery — Lesson", _GAIN + "\nParadigm",
                         keywords=["Paradigm"]))
    life = me.life
    assert g.cast(me, pd)
    run(g)
    assert pd in me.exile and me.life == life + 3
    g.begin_turn(me)
    run(g)
    assert me.life == life + 6


def test_demonstrate_copies_for_both():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    dm = _hand(me, build("Demo", "{1}{R}", "Sorcery", _GAIN + "\nDemonstrate",
                         keywords=["Demonstrate"]))
    life, olife = me.life, ops[0].life
    assert g.cast(me, dm)
    run(g)
    assert me.life == life + 6 and ops[0].life == olife + 3


def test_provoke_forces_block():
    g, me, ops = new_game()
    att = put(g, build("Prov", "{2}{G}", "Creature — Beast", "Provoke", 4, 4,
                       keywords=["Provoke"]), me)
    blk = put(g, creature("Wall", "1W", 0, 3), ops[0])
    blk.tapped = True
    att.summoning_sick = False
    g._resolve_combat(me, [(att, ops[0])])
    run(g)
    assert blk not in ops[0].battlefield        # bloqueó a la fuerza y murió
    assert ops[0].life == 40


def test_recover_returns_to_hand_when_creature_dies():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U,))
    rc = build("Rec", "{2}{U}", "Instant", "Draw a card.\nRecover {2}", keywords=["Recover"])
    me.graveyard.append(rc)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    g.to_graveyard(bear, "test")
    run(g)
    assert rc in me.hand


def test_recover_exiles_if_unpaid():
    g, me, ops = new_game()
    rc = build("Rec", "{2}{U}", "Instant", "Draw a card.\nRecover {5}", keywords=["Recover"])
    me.graveyard.append(rc)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    g.to_graveyard(bear, "test")
    run(g)
    assert rc in me.exile


def test_eminence_triggers_from_command_zone():
    g, me, ops = new_game()
    em = build("Edgy", "{2}{W}{B}", "Legendary Creature — Vampire",
               "Eminence — Whenever another nontoken creature you control enters, if Edgy is "
               "in the command zone or on the battlefield, you gain 1 life.", 3, 3,
               keywords=["Eminence"])
    me.commander = em
    me.command = [em]
    life = me.life
    put(g, creature("Bear", "1G", 2, 2), me)
    assert me.life == life + 1


def test_kinship_reveals_shared_type():
    g, me, ops = new_game()
    put(g, build("Kin", "{1}{U}", "Creature — Merfolk Wizard",
                 "Kinship — At the beginning of your upkeep, you may look at the top card of "
                 "your library. If it shares a creature type with this creature, you may "
                 "reveal it. If you do, you gain 3 life.", 1, 2, keywords=["Kinship"]), me)
    me.library.append(creature("Fish", "1U", 1, 1, subtypes={"Merfolk"}))
    life = me.life
    g.begin_turn(me)
    run(g)
    assert me.life == life + 3


def test_haunt_creature_repeats_when_haunted_dies():
    g, me, ops = new_game()
    th = put(g, build("Thrull", "{3}{W}", "Creature — Thrull",
                      "Haunt\nWhen this creature enters or the creature it haunts dies, you "
                      "gain 3 life.", 2, 2, keywords=["Haunt"]), me)
    victim = put(g, creature("Vic", "1B", 2, 2), ops[0])
    life = me.life
    g.to_graveyard(th, "test")
    run(g)
    assert th.card in me.exile
    g.to_graveyard(victim, "test")
    run(g)
    assert me.life == life + 3


def test_haunt_spell_after_resolving():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(W,))
    sp = _hand(me, build("Ben", "{W}", "Sorcery", "You gain 1 life.\nHaunt\nWhen the creature "
                         "this card haunts dies, you gain 3 life.", keywords=["Haunt"]))
    victim = put(g, creature("Vic", "1B", 2, 2), ops[0])
    life = me.life
    assert g.cast(me, sp)
    run(g)
    assert sp in me.exile and me.life == life + 1
    g.to_graveyard(victim, "test")
    run(g)
    assert me.life == life + 4


def test_forecast_in_upkeep():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(W,))
    fc = _hand(me, build("Fore", "{3}{W}", "Creature — Bird",
                         "Forecast — {W}, Reveal this card from your hand: You gain 2 life.",
                         2, 2, keywords=["Forecast"]))
    life = me.life
    g.begin_turn(me)
    run(g)
    assert me.life == life + 2 and fc in me.hand


def test_soulbond_pt_bonus_for_both():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    sb = put(g, build("Wolfir", "{4}{G}", "Creature — Wolf",
                      "Soulbond\nAs long as this creature is paired with another creature, "
                      "each of those creatures gets +4/+4.", 4, 4, keywords=["Soulbond"]), me)
    assert bear.power == 6 and sb.power == 8
    g.to_graveyard(sb, "test")
    run(g)
    assert bear.power == 2


def test_case_solves_and_unlocks_ability():
    g, me, ops = new_game()
    cs = put(g, build("Case of Tests", "{1}{G}", "Enchantment — Case",
                      "To solve — You control three or more creatures.\n"
                      "Solved — At the beginning of your end step, you gain 2 life.",
                      keywords=["Solved"]), me)
    life = me.life
    g.end_turn(me)
    run(g)
    assert not getattr(cs, "solved", False) and me.life == life
    for k in range(3):
        put(g, creature(f"B{k}", "1G", 1, 1), me)
    g.end_turn(me)
    run(g)
    assert cs.solved
    g.end_turn(me)
    run(g)
    assert me.life >= life + 2


def test_more_than_meets_the_eye_enters_converted():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(R,))
    data = {"name": "Bot // Car", "layout": "transform", "type_line": "Artifact Creature — Robot",
            "mana_cost": "{3}{R}", "keywords": ["More Than Meets the Eye", "Convert"],
            "card_faces": [
                {"name": "Bot", "mana_cost": "{3}{R}", "type_line": "Artifact Creature — Robot",
                 "oracle_text": "More Than Meets the Eye {1}{R}\nWhenever this creature "
                                "attacks, convert it.", "power": "3", "toughness": "3"},
                {"name": "Car", "mana_cost": "", "type_line": "Artifact — Vehicle",
                 "oracle_text": "Whenever this Vehicle attacks, convert it.",
                 "power": "4", "toughness": "2"}]}
    import cardsdb
    c = _hand(me, cardsdb.build_card_from_data(data))
    assert getattr(c, "mtmte_cost", None) is not None
    assert g.cast_converted(me, c)
    run(g)
    pm = next(p for p in me.battlefield if p.card is c or getattr(p, "_real", None) is c
              or p.name in ("Bot", "Car"))
    assert pm.name == "Car"


def test_addendum_bonus_only_in_main_phase():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(W,))
    ad = _hand(me, build("Add", "{W}", "Instant", "You gain 1 life.\nAddendum — If you cast "
                         "this spell during your main phase, you gain 3 life.",
                         keywords=["Addendum"]))
    life = me.life
    assert g.cast(me, ad)
    run(g)
    assert me.life == life + 4


def test_bargain_creature_etb_bonus():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(B,))
    import cards
    put(g, cards.creature("Tok", "0", 1, 1), me)
    me.battlefield[-1].is_token = True
    bf = _hand(me, build("Fae", "{2}{B}", "Creature — Faerie",
                         "Bargain\nWhen this creature enters, if it was bargained, you gain 3 "
                         "life.", 2, 2, keywords=["Bargain"]))
    life = me.life
    assert g.cast(me, bf)
    run(g)
    assert me.life == life + 3
