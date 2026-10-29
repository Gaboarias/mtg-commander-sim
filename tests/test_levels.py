"""Niveles de dificultad: Experto arranca con ventajas (no el humano), Avanzado/Experto
eligen el ataque simulando, y la simulación no altera la partida real."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decks  # noqa: E402
from engine import Game, Player  # noqa: E402
from policy import Policy, LEVELS  # noqa: E402


def _players(levels):
    out = []
    for i, (k, lv) in enumerate(zip(["lorehold", "kang", "tricky", "marvel"], levels)):
        d, c = decks.build(k)
        out.append(Player(f"P{i}", d, c, policy=Policy(lv)))
    return out


def test_levels_and_experto_bonus():
    assert LEVELS == ("novato", "intermedio", "avanzado", "experto")
    g = Game(_players(["experto", "intermedio"]), seed=1)
    ex, it = g.players
    assert ex.life == it.life + 10 and len(ex.hand) == 8
    assert 3 <= sum(1 for c in ex.hand if c.is_land()) <= 5


def test_interactive_human_gets_no_experto_bonus():
    import interactive
    defs = [("Tu",) + decks.build("lorehold"), ("A",) + decks.build("kang")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=2, level="experto")
    hu, bot = ig.players
    assert hu.life == 40 and len(hu.hand) == 7
    assert bot.life == 50 and bot.policy.level == "experto"


def test_simulated_attack_does_not_touch_real_game():
    g = Game(_players(["avanzado", "intermedio", "intermedio", "intermedio"]), seed=4, max_turns=60)
    for t in range(1, 21):
        g.turn = t
        g.active_index = (t - 1) % 4
        if g.ap().lost:
            continue
        g.run_turn()
        g.sba()
    me = g.players[0]
    snap = ([p.life for p in g.players], [len(p.battlefield) for p in g.players], len(me.library), g.turn)
    plan = me.policy.declare_attackers(g, me)
    assert isinstance(plan, list)
    assert snap == ([p.life for p in g.players], [len(p.battlefield) for p in g.players], len(me.library), g.turn)
