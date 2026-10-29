"""Equipos: el estado dice a qué están anexados (la UI los agrupa), no se ofrece
re-equipar a la misma criatura y el bot no gasta maná re-equipando."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G  # noqa: E402
from cards import creature  # noqa: E402
from test_parser_corpus import build, new_game, put, give_lands  # noqa: E402

EQ = "Equipped creature gets +2/+0.\nEquip {1}"


def test_perm_state_reports_attachment_and_no_reequip_same_host():
    g, me, ops = new_game()
    give_lands(g, me, 4, colors=(G,))
    x = put(g, creature("X", "1G", 2, 2), me)
    eq = put(g, build("Sword", "{1}", "Artifact — Equipment", EQ), me)
    eq.enchanting = x
    st = g._perm_state(eq)
    assert st["attached_to"] == x.uid and st["attached_name"] == "X"
    assert g._perm_state(x)["attached_to"] is None
    g.interactive_human = me
    g.active_index = g.players.index(me)
    eq.card.activated_abilities[0]["effect"](g, me, eq, [])
    assert g.pending_choice is None and eq.enchanting is x       # solo había esa criatura


def test_interactive_label_and_bot_skip():
    import interactive
    import decks
    defs = [("Tu",) + decks.build("lorehold"), ("A",) + decks.build("kang")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=1)
    ig.keep([])
    me = ig.human()
    give_lands(ig.g, me, 4, colors=(G,))
    x = put(ig.g, creature("X", "1G", 2, 2), me)
    eq = put(ig.g, build("Sword", "{1}", "Artifact — Equipment", EQ), me)
    eq.enchanting = x
    abil = next(a for a in ig.state()["legal"]["abilities"] if a["uid"] == eq.uid)["abilities"][0]
    assert abil["label"].startswith("Mover equipo") and not abil["playable"]
    put(ig.g, creature("Y", "1G", 3, 3), me)
    abil = next(a for a in ig.state()["legal"]["abilities"] if a["uid"] == eq.uid)["abilities"][0]
    assert abil["playable"]
    # bot: no re-equipa un equipo ya puesto
    from policy import Policy
    g, bot, ops = new_game()
    give_lands(g, bot, 4, colors=(G,))
    b1 = put(g, creature("B1", "1G", 2, 2), bot)
    put(g, creature("B2", "1G", 5, 5), bot)
    beq = put(g, build("Sword", "{1}", "Artifact — Equipment", EQ), bot)
    beq.enchanting = b1
    Policy("intermedio")._activate_perm_abilities(g, bot, True)
    assert beq.enchanting is b1
