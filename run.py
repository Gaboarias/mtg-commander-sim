"""CLI y agregacion estadistica.

Uso:
    python3 run.py                         # baseline: 4-mazos default, 200 partidas
    python3 run.py lorehold kang           # ese enfrentamiento, 200 partidas
    python3 run.py lorehold kang -n 500    # 500 partidas
    python3 run.py lorehold kang --log     # una partida comentada turno a turno
    python3 run.py --log lorehold kang tricky
    python3 run.py lorehold kang -n 2000 --jobs 8    # paralelo en 8 procesos
    python3 run.py lorehold kang -n 500 --json out.json          # exporta resumen
    python3 run.py lorehold kang -n 50  --json out.json --full-log  # + registro

Semillas reproducibles: `one(keys, seed=i)` da SIEMPRE la misma partida para la
misma semilla; `many`/`export` usan semillas 0..n-1.
"""
from __future__ import annotations

import json
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

def build_players_from_defs(deck_defs, level="intermedio"):
    """deck_defs: lista de (label, deck_list, commander_card)."""
    return [Player(label, deck, cmd, policy=Policy(level))
            for label, deck, cmd in deck_defs]


def play_defs(deck_defs, seed=0, log=False, max_turns=60, level="intermedio"):
    players = build_players_from_defs(deck_defs, level=level)
    return Game(players, seed=seed, log=log, max_turns=max_turns)


def many_defs(deck_defs, n=200, max_turns=60, level="intermedio"):
    """Corre n partidas entre decks ya construidos. Devuelve Counter de wins."""
    wins = Counter()
    for i in range(n):
        g = play_defs(deck_defs, seed=i, max_turns=max_turns, level=level)
        wins[g.play()] += 1
    return wins


# --- paralelizacion (P4) -------------------------------------------------- #

def _worker(task):
    """Worker de multiprocessing: corre una partida y devuelve (seed, winner).
    Debe ser top-level para poder picklearse."""
    keys, seed, mulligan = task
    return seed, one(keys, seed=seed, mulligan=mulligan)


def _run_many(keys, n, mulligan=False, jobs=1):
    """Corre n partidas (semillas 0..n-1). jobs>1 usa multiprocessing.
    Devuelve lista de (seed, winner) en orden de semilla."""
    tasks = [(keys, i, mulligan) for i in range(n)]
    if jobs and jobs > 1:
        import multiprocessing as mp
        with mp.Pool(processes=jobs) as pool:
            results = pool.map(_worker, tasks)
    else:
        results = [_worker(t) for t in tasks]
    results.sort(key=lambda x: x[0])
    return results


def many(keys, n=200, verbose=True, mulligan=False, jobs=1):
    results = _run_many(keys, n, mulligan=mulligan, jobs=jobs)
    wins = Counter(w for _seed, w in results)
    if verbose:
        print(f"\n=== {' vs '.join(keys)}  ({n} partidas) ===")
        for key in keys:
            w = wins.get(key, 0)
            print(f"  {key:12s} {w:5d}  {100*w/n:5.1f}%")
        draws = wins.get("EMPATE", 0)
        print(f"  {'EMPATE':12s} {draws:5d}  {100*draws/n:5.1f}%")
    return wins


def export_json(keys, n, path, mulligan=False, jobs=1, full_log=False):
    """Exporta n partidas a un JSON: resumen + por-partida (semilla, ganador,
    turnos y, si full_log, el registro turno a turno)."""
    games = []
    if full_log:
        # necesitamos el log de cada partida -> corremos secuencial capturando
        for i in range(n):
            g = _build_game(keys, seed=i, mulligan=mulligan)
            winner = g.play()
            games.append({"seed": i, "winner": winner, "turns": g.turn,
                          "log": g.log_lines})
    else:
        for seed, winner in _run_many(keys, n, mulligan=mulligan, jobs=jobs):
            games.append({"seed": seed, "winner": winner})
    wins = Counter(x["winner"] for x in games)
    out = {
        "matchup": keys,
        "n": n,
        "mulligan": mulligan,
        "wins": dict(wins),
        "winrate": {k: round(100 * wins.get(k, 0) / n, 2)
                    for k in keys + ["EMPATE"]},
        "games": games,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Exportadas {n} partidas a {path}")
    return out


def main(argv):
    args = list(argv)
    log = False
    mulligan = False
    full_log = False
    n = 200
    jobs = 1
    json_path = None
    if "--log" in args:
        log = True
        args.remove("--log")
    if "--mull" in args:
        mulligan = True
        args.remove("--mull")
    if "--full-log" in args:
        full_log = True
        args.remove("--full-log")
    if "-n" in args:
        i = args.index("-n")
        n = int(args[i + 1])
        del args[i:i + 2]
    if "--jobs" in args:
        i = args.index("--jobs")
        jobs = int(args[i + 1])
        del args[i:i + 2]
    if "--json" in args:
        i = args.index("--json")
        json_path = args[i + 1]
        del args[i:i + 2]

    keys = args if args else DEFAULT_MATCHUP
    for k in keys:
        if k not in decks.DECKS:
            print(f"mazo desconocido: {k}. Opciones: {list(decks.DECKS)}")
            return 1

    if json_path:
        export_json(keys, n, json_path, mulligan=mulligan, jobs=jobs,
                    full_log=full_log)
    elif log:
        winner = one(keys, seed=0, log=True, mulligan=mulligan)
        print(f"\nGanador: {winner}")
    else:
        many(keys, n=n, mulligan=mulligan, jobs=jobs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
