"""Puente entre las funciones serverless de Vercel y el motor en la raiz.

Agrega la raiz del repo al sys.path para poder importar engine/decks/run/etc.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import decks          # noqa: E402
import run            # noqa: E402
import coverage       # noqa: E402
from engine import Game, Player  # noqa: E402
from policy import Policy        # noqa: E402

MAX_N = 2000          # tope de partidas por request (serverless timeout)


def deck_list():
    out = []
    for name in decks.DECKS:
        _, commander = decks.build(name)
        out.append({"key": name, "commander": commander.name,
                    "identity": sorted(commander.identity())})
    return out


def simulate(matchup, n):
    matchup = [m for m in matchup if m in decks.DECKS]
    if len(matchup) < 2:
        raise ValueError("hacen falta al menos 2 mazos validos")
    n = max(1, min(int(n), MAX_N))
    wins = run.many(matchup, n=n, verbose=False)
    total = n
    results = [{"deck": k, "wins": wins.get(k, 0),
                "pct": round(100 * wins.get(k, 0) / total, 1)} for k in matchup]
    results.append({"deck": "EMPATE", "wins": wins.get("EMPATE", 0),
                    "pct": round(100 * wins.get("EMPATE", 0) / total, 1)})
    return {"matchup": matchup, "n": n, "results": results}


def game_log(matchup, seed):
    matchup = [m for m in matchup if m in decks.DECKS]
    if len(matchup) < 2:
        raise ValueError("hacen falta al menos 2 mazos validos")
    g = run._build_game(matchup, seed=int(seed), log=False)
    winner = g.play()
    return {"matchup": matchup, "seed": int(seed), "winner": winner,
            "turns": g.turn, "log": g.log_lines}


def coverage_report():
    rows = coverage.report(verbose=False)
    return {"coverage": [{"deck": name, "implemented": impl, "vanilla": van}
                         for name, impl, van in rows]}
