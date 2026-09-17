"""Mide el criterio de aceptacion P1.1:

En lorehold vs kang, el Lorehold crea al menos un Espiritu antes del turno N
en >=70% de 100 partidas con semillas 0-99.

Uso:  python3 tests/measure_spirits.py [turno_limite=6]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run  # noqa: E402

SPIRIT_RE = re.compile(r"^T(\d+) lorehold: (?:Quintorius crea|Hofri devuelve).*Espiritu",
                       re.IGNORECASE)


def spirit_turn(seed):
    g = run._build_game(["lorehold", "kang"], seed=seed, log=False)
    g.play()
    for line in g.log_lines:
        m = SPIRIT_RE.match(line)
        if m:
            return int(m.group(1))
    return None


def own_turn(game_turn, players=2):
    """Turno propio del jugador inicial dado el turno de juego (1v1: lorehold
    actua en turnos de juego impares)."""
    return (game_turn + players - 1) // players


def main(limit=6, n=100):
    hits_by_limit = 0
    ever = 0
    own_turns = []
    for seed in range(n):
        t = spirit_turn(seed)
        if t is not None:
            ever += 1
            ot = own_turn(t)
            own_turns.append(ot)
            if ot <= limit:
                hits_by_limit += 1
    print(f"lorehold vs kang, {n} partidas (semillas 0-{n-1})")
    print(f"  Espiritu ALGUNA vez:                 {ever:3d}/{n}  ({100*ever/n:.0f}%)")
    print(f"  Espiritu en/antes del turno propio {limit}: {hits_by_limit:3d}/{n}  "
          f"({100*hits_by_limit/n:.0f}%)  [criterio P1.1: >=70%]")
    if own_turns:
        print(f"  turno propio del primer Espiritu: min {min(own_turns)} | "
              f"mediana {sorted(own_turns)[len(own_turns)//2]} | max {max(own_turns)}")
    return hits_by_limit, ever


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    main(limit=limit)
