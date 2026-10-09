"""Verificador de reglas: juega muchas partidas con precons REALES (base local de
cartas, sin red) y revisa invariantes del juego al final de cada turno. Cualquier
violación o excepción se reporta con semilla y mazos para reproducirla.

    python3 scripts/rules_fuzz.py -n 200            # 200 partidas
    python3 scripts/rules_fuzz.py --seed 17 --log   # reproducir una
"""
import collections
import os
import random
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import decklist  # noqa: E402
from engine import Game, Player  # noqa: E402
from policy import Policy  # noqa: E402

PRECON_DIR = os.path.join(ROOT, "data", "precons", "decks")


def precon_files():
    return sorted(f for f in os.listdir(PRECON_DIR) if f.endswith(".txt"))


def build_precon(fn):
    parsed = decklist.parse_decklist(open(os.path.join(PRECON_DIR, fn), encoding="utf-8").read())
    deck, cmd, rep = decklist.build_deck(parsed, fetch=None)
    return deck, cmd


class Checker:
    def __init__(self, g):
        self.g = g
        self.problems = []
        self.lands_at_start = {}

    def bad(self, kind, msg):
        self.problems.append((self.g.turn, kind, msg))

    def zones(self):
        g = self.g
        seen = {}
        for p in g.players:
            for zname in ("library", "hand", "graveyard", "exile", "command",
                          "impulse", "exile_play"):
                for c in getattr(p, zname, []):
                    seen.setdefault(id(c), []).append(f"{p.name}.{zname}:{c.name}")
                for c in getattr(p, zname, []):
                    if getattr(c, "_real", None) is not None:
                        self.bad("sustituta", f"{c.name} (boca abajo/bestow) quedó en "
                                              f"{p.name}.{zname} en vez de la carta real")
            for pm in p.battlefield:
                seen.setdefault(id(pm.card), []).append(f"{p.name}.battlefield:{pm.name}")
                real = getattr(pm.card, "_real", None)
                if real is not None:
                    seen.setdefault(id(real), []).append(f"{p.name}.battlefield:{real.name}*")
                if pm.controller is not p:
                    self.bad("control", f"{pm.name} en el campo de {p.name} pero controlador "
                                        f"{pm.controller.name}")
        for k, where in seen.items():
            if len(where) > 1:
                self.bad("zona-doble", " / ".join(where))

    def board(self):
        g = self.g
        for p in g.players:
            if p.lost and p.battlefield:
                self.bad("eliminado", f"{p.name} perdió y conserva permanentes")
            legends = collections.Counter()
            for pm in p.battlefield:
                if pm.is_creature() and pm.toughness <= 0:
                    self.bad("sba-0", f"{pm.name} {pm.power}/{pm.toughness} sigue en juego")
                if "planeswalker" in pm.card.types and pm.counters.get("loyalty", 0) <= 0:
                    self.bad("sba-pw", f"{pm.name} con lealtad 0 sigue en juego")
                if "legendary" in pm.card.supertypes and not pm.is_token:
                    legends[pm.name] += 1
                ench = getattr(pm, "enchanting", None)
                if ench is not None and ench not in ench.controller.battlefield and \
                        "equipment" not in {s.lower() for s in pm.card.subtypes}:
                    self.bad("aura", f"{pm.name} anexada a {ench.name} que no está en juego")
                if pm.damage and pm.is_creature() and pm.damage >= pm.toughness \
                        and not pm.has("indestructible"):
                    self.bad("sba-daño", f"{pm.name} con daño letal ({pm.damage}) sigue en juego")
            for n, k in legends.items():
                if k > 1:
                    self.bad("leyenda", f"{p.name} controla {k}x {n}")
            if p.mana_pool < 0:
                self.bad("mana", f"{p.name} con maná flotante negativo")

    def end_of_turn(self, p):
        g = self.g
        if g.stack:
            self.bad("pila", f"quedaron {len(g.stack)} objetos en la pila al final del turno")
        self.zones()
        self.board()


# --mech: cada mazo recibe cartas con mecánicas de lanzamiento alternativo /
# boca abajo (morph, disguise, manifest, cloak, bestow, ninjutsu, madness,
# suspend) de su identidad, para estresar esas reglas.
MECH_KWS = {"Morph", "Megamorph", "Disguise", "Manifest", "Manifest dread", "Cloak",
            "Bestow", "Ninjutsu", "Commander ninjutsu", "Madness", "Suspend",
            # batch 2
            "Landwalk", "Split second", "Umbra armor", "Totem armor", "Unleash", "Exert",
            "Exhaust", "Boast", "Power-up", "Raid", "Morbid", "Hellbent", "Threshold",
            "Delirium", "Metalcraft", "Ferocious", "Spell mastery", "Revolt", "Corrupted",
            "Coven", "Celebration", "Descend", "Formidable", "Rebound", "Overload",
            "Retrace", "Jump-start", "Miracle", "Plot", "Warp", "Prototype", "Surge",
            "Spectacle", "Prowl", "Emerge", "Exploit", "Offspring", "Squad", "Casualty",
            "Bargain"}
_MECH_POOL = None


def _mech_pool():
    global _MECH_POOL
    if _MECH_POOL is None:
        import cardsdb
        seen, pool = set(), []
        for row in cardsdb.full_db().values():
            if row["name"] in seen or not (set(row.get("keywords") or []) & MECH_KWS):
                continue
            if "Land" in (row.get("type_line") or ""):
                continue
            seen.add(row["name"])
            pool.append(row)
        pool.sort(key=lambda r: r["name"])
        _MECH_POOL = pool
    return _MECH_POOL


def _inject_mech(deck, cmd, rng, n=14):
    import cardsdb
    ident = set()
    for c in ([cmd] if not isinstance(cmd, list) else cmd):
        ident |= {str(x).upper() for x in (c.identity() if hasattr(c, "identity") else [])}
    pool = [r for r in _mech_pool()
            if set(r.get("color_identity") or []) <= ident]
    slots = [i for i, c in enumerate(deck) if not c.is_land()]
    rng.shuffle(slots)
    for i in slots[:n]:
        if not pool:
            break
        deck[i] = cardsdb.build_card_from_data(rng.choice(pool))
    return deck


def run_one(seed, n_players=None, log=False, mech=False):
    rng = random.Random(seed)
    files = precon_files()
    n = n_players or rng.choice([2, 3, 4])
    picks = rng.sample(files, n)
    players = []
    for i, fn in enumerate(picks):
        deck, cmd = build_precon(fn)
        if mech:
            deck = _inject_mech(deck, cmd, rng)
        players.append(Player(f"P{i}:{fn[:-4]}", deck, cmd, policy=Policy()))
    g = Game(players, seed=seed, log=log, max_turns=40)
    chk = Checker(g)
    orig_end = g.end_turn
    orig_decl = g._declare_attackers

    def end_turn(p):
        r = orig_end(p)
        chk.end_of_turn(p)
        return r

    def declare(p, attackers):
        for perm, _d in attackers:
            if perm.summoning_sick and not perm.has("haste") and perm.can_attack():
                chk.bad("mareo", f"{perm.name} ataca con mareo de invocación")
        return orig_decl(p, attackers)
    orig_land = g.play_land

    def play_land(p, card):
        limit = g.land_limit(p)
        before = p.lands_played
        ok = orig_land(p, card)
        if ok and before >= limit:
            chk.bad("tierras", f"{p.name} jugó una tierra más allá del límite ({limit})")
        return ok
    g.end_turn = end_turn
    g._declare_attackers = declare
    g.play_land = play_land
    err = None
    try:
        winner = g.play()
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        winner = None
    warns = [ln for ln in g.log_lines if "aviso:" in ln]
    return {"seed": seed, "decks": picks, "winner": winner, "turns": g.turn,
            "problems": chk.problems, "error": err, "warnings": warns}


def main(argv):
    n = int(argv[argv.index("-n") + 1]) if "-n" in argv else 100
    if "--seed" in argv:
        r = run_one(int(argv[argv.index("--seed") + 1]), log="--log" in argv,
                    mech="--mech" in argv)
        print(r["decks"], r["winner"], r["turns"])
        for pr in r["problems"]:
            print("  ", pr)
        if r["error"]:
            print(r["error"])
        return 0
    jobs = int(argv[argv.index("--jobs") + 1]) if "--jobs" in argv else os.cpu_count() or 1
    start = int(argv[argv.index("--from") + 1]) if "--from" in argv else 0
    kinds = collections.Counter()
    examples = {}
    errors = collections.Counter()
    err_ex = {}
    import multiprocessing as mp
    with mp.Pool(jobs) as pool:
        import functools
        results = pool.map(functools.partial(run_one, mech="--mech" in argv),
                           range(start, start + n))
    for r in results:
        seed = r["seed"]
        for t, kind, msg in r["problems"]:
            kinds[kind] += 1
            examples.setdefault(kind, []).append((seed, t, msg))
        if r["error"]:
            last = r["error"].strip().splitlines()[-1]
            errors[last] += 1
            err_ex.setdefault(last, (seed, r["error"]))
        for w in r["warnings"]:
            kinds["aviso"] += 1
            examples.setdefault("aviso", []).append((seed, 0, w))
    print(f"partidas={n} violaciones={sum(kinds.values())} excepciones={sum(errors.values())}")
    for k, v in kinds.most_common():
        print(f"== {k}: {v}")
        for ex in examples[k][:4]:
            print("    seed", ex[0], "T", ex[1], ex[2][:200])
    for e, v in errors.most_common():
        print(f"== EXCEPCIÓN x{v}: {e}  (seed {err_ex[e][0]})")
        print("   " + "\n   ".join(err_ex[e][1].strip().splitlines()[-6:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
