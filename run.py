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


def _build_game(keys, seed=0, log=False, max_turns=60, mulligan=False):
    players = []
    for i, key in enumerate(keys):
        deck, commander = decks.build(key)
        p = Player(f"{key}", deck, commander, policy=Policy())
        players.append(p)
    return Game(players, seed=seed, log=log, max_turns=max_turns,
                mulligan=mulligan)


def one(keys, seed=0, log=False, mulligan=False):
    """Corre UNA partida reproducible. Misma semilla => misma partida."""
    g = _build_game(keys, seed=seed, log=log, mulligan=mulligan)
    return g.play()


# --- decks arbitrarios (import / edicion) --------------------------------- #

def build_players_from_defs(deck_defs):
    """deck_defs: lista de (label, deck_list, commander_card)."""
    return [Player(label, deck, cmd, policy=Policy())
            for label, deck, cmd in deck_defs]


def play_defs(deck_defs, seed=0, log=False, max_turns=60):
    players = build_players_from_defs(deck_defs)
    return Game(players, seed=seed, log=log, max_turns=max_turns)


def many_defs(deck_defs, n=200):
    """Corre n partidas entre decks ya construidos. Devuelve Counter de wins."""
    wins = Counter()
    for i in range(n):
        g = play_defs(deck_defs, seed=i)
        wins[g.play()] += 1
    return wins


def many(keys, n=200, verbose=True, mulligan=False):
    wins = Counter()
    for i in range(n):
        winner = one(keys, seed=i, log=False, mulligan=mulligan)
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
    mulligan = False
    n = 200
    if "--log" in args:
        log = True
        args.remove("--log")
    if "--mull" in args:
        mulligan = True
        args.remove("--mull")
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
        winner = one(keys, seed=0, log=True, mulligan=mulligan)
        print(f"\nGanador: {winner}")
    else:
        many(keys, n=n, mulligan=mulligan)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
