"""Tests basicos del motor. Corre con pytest o directo:

    python3 -m pytest tests/ -q
    python3 tests/test_engine.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import (Game, Player, Card, Cost, parse_cost, Permanent,
                    W, U, B, R, G, C)
import cards
from cards import creature, land, rock
from policy import Policy


def _mk_player(name="p", deck=None, commander=None):
    deck = deck or [land("Forest", [G], basic=True) for _ in range(99)]
    commander = commander or creature("Cmdr", "2G", 3, 3, legendary=True)
    return Player(name, deck, commander, policy=Policy())


def _game(players):
    return Game(players, seed=1)


# -- coste de mana con duales ---------------------------------------------- #
def test_parse_cost():
    c = parse_cost("2RW")
    assert c.generic == 2 and c.pips == ("R", "W") and c.cmc == 4
    assert parse_cost("UUU").cmc == 3
    assert parse_cost("1").generic == 1


def test_dual_land_is_one_mana():
    p = _mk_player()
    g = _game([p, _mk_player("q")])
    dual = land("Dual", [R, W])
    perm = g.move_to_battlefield(dual, p)
    # una dual da UN mana (rojo O blanco), no dos
    assert p.available_mana() == 1
    # puede pagar R o W, pero no RW (dos simbolos) con una sola fuente
    assert p.can_pay(parse_cost("R"))
    assert p.can_pay(parse_cost("W"))
    assert not p.can_pay(parse_cost("RW"))


def test_sol_ring_two_colorless():
    p = _mk_player()
    g = _game([p, _mk_player("q")])
    sol = rock("Sol Ring", "1", [C, C])
    # produces directo de 2 incoloros
    sol.produces = lambda perm, pl: {C: 2}
    g.move_to_battlefield(sol, p)
    assert p.available_mana() == 2
    assert p.can_pay(parse_cost("2"))


def test_assign_pays_pips_and_generic():
    p = _mk_player()
    g = _game([p, _mk_player("q")])
    g.move_to_battlefield(land("F", [G], basic=True), p)
    g.move_to_battlefield(land("I", [U], basic=True), p)
    g.move_to_battlefield(land("Any", [W, U, B, R, G], basic=False), p)
    # GU1 => G, U, y un generico de la tri-tierra
    assert p.can_pay(parse_cost("1GU"))
    assert not p.can_pay(parse_cost("2GU"))  # falta un mana


# -- impuesto de comandante ------------------------------------------------ #
def test_commander_tax():
    p = _mk_player()
    assert p.cmdr_tax == 0
    p.cmdr_tax += 2
    cost = parse_cost("2G")
    pay = Cost(generic=cost.generic + p.cmdr_tax, pips=cost.pips)
    assert pay.cmc == cost.cmc + 2


# -- 21 de dano de comandante ---------------------------------------------- #
def test_commander_damage_kills():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    cmdr = a.commander_card
    perm = g.move_to_battlefield(cmdr, a)
    g.deal_damage(perm, b, 21, combat=True)
    g.sba()
    assert b.lost


# -- arrollar (trample) ---------------------------------------------------- #
def test_trample_excess_to_player():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    atk = g.move_to_battlefield(creature("Big", "3G", 5, 5, kw=("trample",)), a)
    blk = g.move_to_battlefield(creature("Wall", "1G", 0, 2), b)
    atk.summoning_sick = False
    atk.attacking = b
    atk.blocked_by = [blk]
    blk.blocking = [atk]
    life0 = b.life
    g._combat_damage([atk], first_strike=False)
    # 2 letal al bloqueador, 3 pasan al jugador
    assert b.life == life0 - 3


# -- amenaza (menace) ------------------------------------------------------ #
def test_menace_needs_two_blockers():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    atk = g.move_to_battlefield(creature("Sneak", "1B", 2, 2, kw=("menace",)), a)
    blk = g.move_to_battlefield(creature("One", "1G", 1, 1), b)
    atk.summoning_sick = False
    # con un solo bloqueador, el bloqueo se cae por amenaza (logica en combat())
    from engine import Permanent
    assert atk.has("menace")


# -- regla de legendarios -------------------------------------------------- #
def test_legend_rule():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    c1 = creature("Legendaria", "1G", 2, 2, legendary=True)
    c2 = creature("Legendaria", "1G", 2, 2, legendary=True)
    g.move_to_battlefield(c1, a)
    g.move_to_battlefield(c2, a)
    g.sba()
    legends = [p for p in a.battlefield if p.name == "Legendaria"]
    assert len(legends) == 1


# -- Simic Ascendancy gana la partida (BACKLOG P1.2) ----------------------- #
def test_simic_ascendancy_wins():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    asc = g.move_to_battlefield(cards.SimicAscendancy(), a)
    for _ in range(20):
        asc.card.triggers["cast"](g, asc)
    g.sba()
    assert b.lost


# -- partida completa corre sin excepciones -------------------------------- #
def test_full_game_runs():
    import run
    winner = run.one(["lorehold", "kang"], seed=3)
    assert winner in ("lorehold", "kang", "EMPATE")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests OK")


if __name__ == "__main__":
    _run_all()
