"""CLI y agregacion estadistica.

Uso:
    python3 run.py                         # baseline: 4-mazos default, 200 partidas
    python3 run.py lorehold kang           # ese enfrentamiento, 200 partidas
    python3 run.py lorehold kang -n 500    # 500 partidas
    python3 run.py lorehold kang --log     # una partida comentada turno a turno
    python3 run.py --log lorehold kang tricky
"""
from __future__ import annotations

import sys
from collections import Counter

import decks
from engine import Game, Player
from policy import Policy

DEFAULT_MATCHUP = ["lorehold", "tricky", "kang"]


def _build_game(keys, seed=0, log=False, max_turns=60):
    players = []
    for i, key in enumerate(keys):
        deck, commander = decks.build(key)
        p = Player(f"{key}", deck, commander, policy=Policy())
        players.append(p)
    return Game(players, seed=seed, log=log, max_turns=max_turns)


def one(keys, seed=0, log=False):
    """Corre UNA partida reproducible. Misma semilla => misma partida."""
    g = _build_game(keys, seed=seed, log=log)
    return g.play()


def many(keys, n=200, verbose=True):
    wins = Counter()
    for i in range(n):
        winner = one(keys, seed=i, log=False)
        wins[winner] += 1
    if verbose:
        print(f"\n=== {' vs '.join(keys)}  ({n} partidas) ===")
        for key in keys:
            w = wins.get(key, 0)
            print(f"  {key:12s} {w:5d}  {100*w/n:5.1f}%")
        draws = wins.get("EMPATE", 0)
        print(f"  {'EMPATE':12s} {draws:5d}  {100*draws/n:5.1f}%")
    return wins


def main(argv):
    args = list(argv)
    log = False
    n = 200
    if "--log" in args:
        log = True
        args.remove("--log")
    if "-n" in args:
        i = args.index("-n")
        n = int(args[i + 1])
        del args[i:i + 2]

    keys = args if args else DEFAULT_MATCHUP
    for k in keys:
        if k not in decks.DECKS:
            print(f"mazo desconocido: {k}. Opciones: {list(decks.DECKS)}")
            return 1

    if log:
        winner = one(keys, seed=0, log=True)
        print(f"\nGanador: {winner}")
    else:
        many(keys, n=n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
