"""Decisiones que antes tomaba el motor solo y ahora elige el HUMANO por modal:
costes (sacrificio adicional, kicker), sacrificar como coste de habilidad, looting,
edictos ("cada oponente sacrifica") y "conservá N, sacrificá el resto"."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, B, R  # noqa: E402
from cards import creature  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def _choose(g, label):
    ch = g.pending_choice
    assert ch is not None
    idx = next(o["i"] for o in ch["options"] if label in o["name"])
    g.pending_choice = None
    ch["_apply"](idx)


def test_edict_human_chooses_bot_auto():
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = g.players.index(me)
    big = put(g, creature("Big", "3G", 5, 5), me)
    small = put(g, creature("Small", "G", 1, 1), me)
    foe1 = put(g, creature("F1", "G", 1, 1), ops[0])
    put(g, creature("F2", "G", 4, 4), ops[0])
    ed = build("Edict", "{1}{B}", "Sorcery", "Each player sacrifices a creature.")
    give_lands(g, ops[0], 2, colors=(B,))
    ops[0].hand.append(ed)
    g.active_index = g.players.index(me)
    ed.on_cast_resolve(g, ops[0], [])
    # el bot sacrificó solo la más débil; el humano tiene que elegir
    assert foe1 not in ops[0].battlefield
    q = g.pending_choice or (g.choice_queue.pop(0)() or g.pending_choice)
    assert q["kind"] == "sacrifice"
    _choose(g, "Big")
    assert big not in me.battlefield and small in me.battlefield


def test_keep_then_sacrifice_human():
    import cardsdb
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = g.players.index(me)
    cs = [put(g, creature(f"C{i}", "G", i + 1, i + 1), me) for i in range(3)]
    cardsdb._human_keep_then_sac(g, me, cs, 1)
    assert g.pending_choice["kind"] == "keep"
    _choose(g, "C0")
    assert cs[0] in me.battlefield and cs[1] not in me.battlefield and cs[2] not in me.battlefield


def test_looting_discards_for_bot_and_human():
    g, me, ops = new_game()
    lo = build("Loot", "{U}", "Sorcery", "Draw two cards, then discard a card.")
    me.library = [creature("A", "G", 1, 1), creature("B", "G", 1, 1)]
    me.hand = []
    lo.on_cast_resolve(g, me, [])
    assert len(me.hand) == 1 and len(me.graveyard) >= 1
    g, me, ops = new_game()
    g.interactive_human = me
    g.active_index = g.players.index(me)
    me.library = [creature("A", "G", 1, 1), creature("B", "G", 1, 1)]
    me.hand = []
    build("Loot", "{U}", "Sorcery", "Draw two cards, then discard a card.").on_cast_resolve(g, me, [])
    assert g.pending_choice and g.pending_choice["kind"] == "discard"
    _choose(g, "B")
    assert [c.name for c in me.hand] == ["A"]


def test_kicker_and_sac_cost_prefs():
    g, me, ops = new_game()
    bl = build("Burst Lightning", "{R}", "Instant", "Kicker {4}\nBurst Lightning deals 2 damage to any target. If this "
               "spell was kicked, it deals 4 damage instead.")
    give_lands(g, me, 5, colors=(R,))
    me.hand.append(bl)
    g.interactive_human = me
    g._human_pref = {"kicker": False}
    life = ops[0].life
    assert g.cast(me, bl, targets=[ops[0]])
    g._human_pref = None
    run(g)
    assert ops[0].life == life - 2
    g, me, ops = new_game()
    no = build("Natural Order", "{2}{G}{G}", "Sorcery", "As an additional cost to cast this spell, sacrifice a green "
               "creature.\nSearch your library for a green creature card, put it onto the battlefield, then shuffle.")
    give_lands(g, me, 4, colors=(G,))
    a = put(g, creature("ElfA", "G", 1, 1), me)
    b = put(g, creature("ElfB", "G", 3, 3), me)
    me.library = [creature("Dragon", "6G", 7, 7)]
    me.hand.append(no)
    g.interactive_human = me
    g._human_pref = {"sac": [b]}
    assert g.cast(me, no)
    g._human_pref = None
    assert b not in me.battlefield and a in me.battlefield


def _human_game(n_opp=1):
    g, me, ops = new_game(n_opp)
    g.interactive_human = me
    g.active_index = g.players.index(me)
    return g, me, ops


def test_qualified_removal_asks_human_and_bot_spares_own():
    g, me, ops = _human_game()
    mine = put(g, creature("Mine", "1G", 5, 5), me)
    a = put(g, creature("OppA", "1G", 2, 2), ops[0])
    b = put(g, creature("OppB", "1R", 4, 4), ops[0])
    put(g, creature("OppBlack", "1B", 6, 6), ops[0])
    t = build("Terror", "{1}{B}", "Instant", "Destroy target nonartifact, nonblack creature. It can't be regenerated.")
    t.on_cast_resolve(g, me, [])
    ch = g.pending_choice
    assert ch and ch["kind"] == "etb_target" and not any("OppBlack" in o["name"] for o in ch["options"])
    _choose(g, "OppA")
    assert a not in ops[0].battlefield and b in ops[0].battlefield
    # bot: la más amenazante del rival, nunca la propia
    g.interactive_human = None
    t2 = build("Terror", "{1}{B}", "Instant", "Destroy target nonartifact, nonblack creature. It can't be regenerated.")
    t2.on_cast_resolve(g, me, [])
    assert b not in ops[0].battlefield and mine in me.battlefield


def test_non_removal_generic_no_longer_kills_creatures():
    g, me, ops = new_game()
    big = put(g, creature("Big", "3G", 6, 6), ops[0])
    pg = build("Purify the Grave", "{W}", "Instant", "Exile target card from a graveyard.\nFlashback {W}")
    pg.on_cast_resolve(g, me, [])
    assert big in ops[0].battlefield


def test_divided_damage_human_assigns():
    g, me, ops = _human_game()
    a = put(g, creature("OppA", "1G", 2, 2), ops[0])
    b = put(g, creature("OppB", "1G", 1, 1), ops[0])
    put(g, build("Titan", "{4}{R}{R}", "Creature — Giant", "When this creature enters, it deals 3 damage divided as you "
                 "choose among one, two, or three targets.", 6, 6), me)
    _choose(g, "OppA")
    assert g.pending_choice["kind"] == "amount"
    _choose(g, "2")
    _choose(g, "OppB")
    assert a not in ops[0].battlefield and b not in ops[0].battlefield


def test_target_player_mill_can_pick_self_and_color_choice():
    g, me, ops = _human_game(2)
    me.library = [creature("X", "G", 1, 1) for _ in range(5)]
    gm = build("Mindcrusher", "{4}{U}{U}", "Creature — Zombie Horror", "When this creature enters, target player mills "
               "five cards.", 5, 5)
    put(g, gm, me)
    assert g.pending_choice["kind"] == "player_target"
    _choose(g, "Vos")
    assert len(me.graveyard) == 5
    cs = build("Caged", "{6}", "Artifact", "As this artifact enters, choose a color.\nCreatures you control of the "
               "chosen color get +1/+1.")
    pm = put(g, cs, me)
    assert g.pending_choice["kind"] == "color"
    _choose(g, "Azul")
    assert pm.chosen_color == "U"


def test_tap_or_untap_and_unblockable_choice():
    g, me, ops = _human_game()
    a = put(g, creature("OppA", "1G", 2, 2), ops[0])
    put(g, creature("OppB", "1G", 3, 3), ops[0])
    put(g, build("Pester", "{2}{U}", "Creature — Faerie", "Flash\nFlying\nWhen this creature enters, you may tap or "
                 "untap target permanent.", 2, 1), me)
    _choose(g, "OppA")
    assert g.pending_choice["kind"] == "may"
    _choose(g, "Girar")
    assert a.tapped
