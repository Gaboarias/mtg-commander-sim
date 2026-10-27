"""Batch 27: costes adicionales (sacrificar criatura calificada, girar N criaturas,
contador -1/-1, blight o pagar), elegir modo al entrar (Sieges), disparos de ataque
duplicados (Mardu), Dack Fayden (regalar criaturas provocadas) y evasión condicional."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_natural_order_needs_green_creature_and_tap_costs():
    g, me, ops = new_game()
    no = build("Natural Order", "{2}{G}{G}", "Sorcery", "As an additional cost to cast this spell, sacrifice a green "
               "creature.\nSearch your library for a green creature card, put it onto the battlefield, then shuffle.")
    assert no.additional_cost == {"sacrifice": "qual:green"}
    give_lands(g, me, 4, colors=(G,))
    put(g, creature("Blue", "1U", 1, 1), me)
    me.hand.append(no)
    assert not g.cast(me, no)                       # solo hay criatura azul
    elf = put(g, creature("Elf", "1G", 1, 1), me)
    me.library = [creature("Dragon", "6G", 7, 7)]
    assert g.cast(me, no)
    run(g)
    assert elf not in me.battlefield and any(pm.name == "Dragon" for pm in me.battlefield)
    g, me, ops = new_game()
    sd = build("Shared", "{G}", "Sorcery", "As an additional cost to cast this spell, tap four untapped creatures you "
               "control.\nReturn up to two target cards from your graveyard to your hand.")
    assert sd.additional_cost["tap_n"][0] == 4
    cs = [put(g, creature(f"C{i}", "1G", 1, 1), me) for i in range(3)]
    give_lands(g, me, 1, colors=(G,))
    me.hand.append(sd)
    assert not g.cast(me, sd)
    cs.append(put(g, creature("C3", "1G", 1, 1), me))
    assert g.cast(me, sd) and all(c.tapped for c in cs)


def test_minus_counter_and_blight_or_pay_costs():
    g, me, ops = new_game()
    ls = build("Sting", "{2}{B}", "Instant", "As an additional cost to cast this spell, put a -1/-1 counter on a creature "
               "you control.\nDestroy target creature.")
    assert ls.additional_cost.get("minus_ctr") == 1
    give_lands(g, me, 3, colors=(B,))
    me.hand.append(ls)
    foe = put(g, creature("Foe", "2G", 3, 3), ops[0])
    assert not g.cast(me, ls, targets=[foe])         # sin criatura propia
    x = put(g, creature("X", "1B", 2, 2), me)
    assert g.cast(me, ls, targets=[foe])
    assert x.counters.get("-1/-1") == 1
    be = build("Embrace", "{B}{B}", "Sorcery", "As an additional cost to cast this spell, blight 1 or pay {3}.\n"
               "Exile target creature.")
    assert be.additional_cost["blight_or"][0] == 1
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(B,))
    me.hand.append(be)
    foe = put(g, creature("Foe", "2G", 3, 3), ops[0])
    assert not g.cast(me, be, targets=[foe])         # sin criatura ni {3} extra


def test_siege_mode_choice_human_and_bot():
    text = ("As this enchantment enters, choose Mardu or Jeskai.\n• Mardu — If a creature attacking causes a triggered "
            "ability of a permanent you control to trigger, that ability triggers an additional time.\n• Jeskai — At "
            "the beginning of your upkeep, create a 1/1 red Goblin creature token. It gains lifelink and haste until "
            "end of turn.")
    sg = build("Windcrag Siege", "{1}{R}{W}", "Enchantment", text)
    assert [lab for lab, _t in sg.choice_modes] == ["Mardu", "Jeskai"]
    assert "upkeep" not in (sg.triggers or {})       # antes se aplicaba siempre Jeskai
    g, me, ops = new_game()
    g.interactive_human = me
    pm = put(g, build("Windcrag Siege", "{1}{R}{W}", "Enchantment", text), me)
    assert g.pending_choice["kind"] == "mode_choice" and len(g.pending_choice["options"]) == 2
    g.pending_choice["_apply"](1)
    assert pm.chosen_mode == "Jeskai" and "upkeep" in pm.card.triggers
    g.pending_choice = None
    g.interactive_human = None
    pm2 = put(g, build("Windcrag Siege", "{1}{R}{W}", "Enchantment", text), me)
    assert pm2.chosen_mode in ("Mardu", "Jeskai")
    g, me, ops = new_game()
    g.interactive_human = me
    pm = put(g, build("Windcrag Siege", "{1}{R}{W}", "Enchantment", text), me)
    g.pending_choice["_apply"](0)
    g.pending_choice = None
    g.interactive_human = None
    assert pm.card.attack_trig_extra == 1
    life = me.life
    a = put(g, build("Gainer", "{1}{W}", "Creature — Human", "Whenever this creature attacks, you gain 1 life.", 2, 2),
            me)
    a.summoning_sick = False
    g.active_index = g.players.index(me)
    g._declare_attackers(me, [(a, ops[0])])
    run(g)
    assert me.life == life + 2                       # el disparo de ataque se duplica


def test_dack_fayden_gifts_goaded_creatures():
    g, me, ops = new_game(3)
    me.library = [creature("A", "1G", 1, 1), land("F", [G], basic=True), creature("B", "2G", 2, 2),
                  creature("C", "3G", 3, 3), land("F2", [G], basic=True)]
    put(g, build("Dack Fayden, Helping Hand", "{3}{U}{R}", "Legendary Creature — Human Advisor", "When Dack Fayden "
                 "enters, reveal cards from the top of your library until you reveal X creature cards, where X is the "
                 "number of opponents you have. Put those creature cards onto the battlefield, then shuffle. They're "
                 "goaded for the rest of the game. For each of those permanents, choose a different opponent. Each "
                 "opponent gains control of the permanent for which they were chosen.", 4, 6), me)
    run(g)
    got = [pm for o in ops for pm in o.battlefield if pm.name in ("A", "B", "C")]
    assert len(got) == 3 and all(pm.goaded and pm.perma_goad for pm in got)
    assert len({pm.controller.name for pm in got}) == 3 and len(me.library) == 2


def test_conditional_evasion_and_conditions():
    import cardsdb
    for c in ("you've committed a crime this turn", "you've cast a historic spell this turn"):
        assert cardsdb._cond_gc(c) is not None, c
    g, me, ops = new_game()
    a = put(g, build("Sneak", "{1}{U}", "Creature — Human Rogue", "This creature can't be blocked if you've cast two or "
                     "more spells this turn.", 2, 2), me)
    me.spells_cast_turn = 0
    assert not a.has("unblockable")
    me.spells_cast_turn = 2
    assert a.has("unblockable")


def test_scaling_auras_and_equipment():
    g, me, ops = new_game()
    x = put(g, creature("X", "1G", 2, 2), me)
    give_lands(g, me, 3)
    put(g, build("Anthem", "{2}{W}", "Enchantment", "Creatures you control get +1/+1."), me)
    ea = put(g, build("Ethereal Armor", "{W}", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+1 "
                      "for each enchantment you control and has first strike."), me)
    ea.enchanting = x
    assert (x.power, x.toughness) == (5, 5) and x.has("first_strike")     # 2 encantamientos + anthem
    g, me, ops = new_game()
    x = put(g, creature("X", "1G", 2, 2), me)
    give_lands(g, me, 3)
    bb = put(g, build("Blackblade", "{1}", "Legendary Artifact — Equipment", "Equipped creature gets +1/+1 for each "
                      "land you control.\nEquip {7}"), me)
    bb.enchanting = x
    assert (x.power, x.toughness) == (5, 5)                                # sin el +1/+1 duplicado
    ls = put(g, build("Sash", "{1}{W}", "Artifact Creature — Equipment", "Equipped creature gets +1/+1 for each +1/+1 "
                      "counter on this Equipment.\nEquip {W}{W}", 1, 1), me)
    bb.enchanting = None
    ls.enchanting = x
    ls.counters["+1/+1"] = 3
    assert (x.power, x.toughness) == (5, 5)
