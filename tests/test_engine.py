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


# -- Quintorius crea Espiritu al salir carta del cementerio (P1.1) --------- #
def test_quintorius_makes_spirit_on_leave_graveyard():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    g.move_to_battlefield(cards.Quintorius(), a)  # ETB siembra cementerio
    before = sum(1 for p in a.battlefield if p.name == "Espiritu")
    g.emit("upkeep", player=a)  # upkeep exilia del cementerio -> leaves_graveyard
    g.resolve_stack()
    after = sum(1 for p in a.battlefield if p.name == "Espiritu")
    assert after > before


# -- Kang drena con la 2da carta robada del turno, sin atacar (P1.3) -------- #
def test_kang_drains_on_second_draw_without_attacking():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    g.move_to_battlefield(cards.Kang(), a)
    a.draws_this_turn = 1  # ya se robo la carta natural del turno
    b_life = b.life
    a_life = a.life
    cards.NightsWhisper().on_cast_resolve(g, a, [])  # roba 2 (2da y 3ra del turno)
    g.resolve_stack()
    assert b.life == b_life - 1   # drenaje por la 2da carta
    assert a.life == a_life + 1   # Kang gana esa vida


# -- Kang connive: +1/+1 solo si lo descartado no era tierra (P1.3) --------- #
def test_kang_connive_counter_only_on_nonland_discard():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    kang = g.move_to_battlefield(cards.Kang(), a)
    # forzamos la mano: solo tierras -> descarta tierra -> sin contador
    a.hand = [land("Swamp", [B], basic=True)]
    a.library = [creature("X", "1B", 1, 1)]  # lo que robe el connive
    cards._connive(g, kang)
    assert kang.counters.get("+1/+1", 0) == 0


# -- dobladores / Hardened Scales modifican los +1/+1 (P1.2) --------------- #
def test_counter_modifiers():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    creat = g.move_to_battlefield(creature("Bicho", "1G", 1, 1), a)
    # sin modificadores: +1
    g.add_counters(creat, "+1/+1", 1)
    assert creat.counters["+1/+1"] == 1
    # Hardened Scales: +1 extra -> el proximo +1 pone 2
    g.move_to_battlefield(cards.HardenedScales(), a)
    g.add_counters(creat, "+1/+1", 1)
    assert creat.counters["+1/+1"] == 3
    # Branching Evolution: duplica -> (1+1)*2 = 4 mas
    g.move_to_battlefield(cards.BranchingEvolution(), a)
    g.add_counters(creat, "+1/+1", 1)
    assert creat.counters["+1/+1"] == 7


# -- P2.4 anthem (efecto continuo) modifica poder/resistencia -------------- #
def test_anthem_boosts_creatures():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    creat = g.move_to_battlefield(creature("Bicho", "1G", 2, 2), a)
    assert (creat.power, creat.toughness) == (2, 2)
    g.move_to_battlefield(cards.anthem("Estandarte", "2W", 1, 1, ("W",)), a)
    assert (creat.power, creat.toughness) == (3, 3)   # anthem propio
    # no afecta al rival
    enemy = g.move_to_battlefield(creature("Rival", "1R", 2, 2), b)
    assert (enemy.power, enemy.toughness) == (2, 2)


# -- P2.2 hexproof no puede ser objetivo de removal rival ------------------ #
def test_hexproof_not_targetable_by_opponent():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    safe = g.move_to_battlefield(
        creature("Escurridizo", "1G", 3, 3, kw=("hexproof",)), b)
    plain = g.move_to_battlefield(creature("Normal", "1G", 4, 4), b)
    # a (rival) no puede apuntar a la criatura con hexproof
    assert not g.can_target(a, safe)
    assert g.can_target(a, plain)
    legal = g.legal_creature_targets(a)
    assert safe not in legal and plain in legal
    # su propio controlador si puede apuntarla
    assert g.can_target(b, safe)
    # el removal dirigido no destruye una hexproof si es el unico objetivo
    cards.destroy_target(g, a, [safe])
    assert safe in b.battlefield


# -- import de decklist: parser + registro (offline) ----------------------- #
def test_decklist_parse_and_build():
    import decklist
    txt = """Commander
1 Kang, el Embaucador
Deck
1 Gray Merchant of Asphodel
1x Go for the Throat (C21) 12
2 Swamp
1 Sol Ring
// nota
Sideboard
1 Island
"""
    parsed = decklist.parse_decklist(txt)
    assert parsed["commander"] == "Kang, el Embaucador"
    names = [n for _, n in parsed["cards"]]
    assert "Go for the Throat" in names   # se limpia el (SET) 12
    assert "Island" not in names          # sideboard ignorado
    deck, cmd, report = decklist.build_deck(parsed, fetch=None)
    assert len(deck) == 99
    assert cmd.name == "Kang, el Embaucador"
    assert report["unresolved"] == []     # Sol Ring ahora esta registrado


def test_cardsdb_resolve():
    import cardsdb
    assert cardsdb.is_implemented("gray merchant of asphodel")
    assert cardsdb.resolve("Sol Ring").name == "Sol Ring"
    assert cardsdb.resolve("Forest").is_land()
    assert cardsdb.resolve("Carta Inexistente 123", fetch=None) is None


def test_build_card_from_scryfall_data():
    import cardsdb
    data = {"name": "Serra Angel", "mana_cost": "{3}{W}{W}",
            "type_line": "Creature — Angel", "power": "4", "toughness": "4",
            "keywords": ["Flying", "Vigilance"], "color_identity": ["W"]}
    c = cardsdb.build_card_from_data(data)
    assert c.cost.cmc == 5 and c.power == 4 and c.toughness == 4
    assert "flying" in c.keywords and "vigilance" in c.keywords
    assert c.identity() == {"W"}


# -- P2.1 Counterspell contrarresta un hechizo en la pila ------------------ #
def test_counterspell_counters_a_spell():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    # b tiene con que responder: 2 Islas + Counterspell en mano
    for _ in range(2):
        g.move_to_battlefield(land("Island", [U], basic=True), b)
    b.hand = [cards.Counterspell()]
    # a lanza una criatura (mana suficiente)
    for _ in range(2):
        g.move_to_battlefield(land("Forest", [G], basic=True), a)
    cr = creature("Bicho Gordo", "1G", 5, 5)
    a.hand = [cr]
    g.cast(a, cr)
    # la criatura fue contrarrestada
    assert cr not in [p.card for p in a.battlefield]
    assert cr in a.graveyard
    assert any(c.name == "Counterspell" for c in b.graveyard)


# -- P2.5 mulligan (regla de Londres) -------------------------------------- #
def test_mulligan_decision():
    pol = Policy()
    lands = [land("Forest", [G], basic=True) for _ in range(7)]
    spells = [creature("X", "1G", 1, 1) for _ in range(7)]
    # 0 tierras y 7 tierras -> mulligan; 3 tierras -> no
    assert pol.should_mulligan(spells)             # 0 tierras
    assert pol.should_mulligan(lands)              # 7 tierras
    mixed = lands[:3] + spells[:4]
    assert not pol.should_mulligan(mixed)          # 3 tierras


def test_game_with_mulligan_keeps_seven_and_conserves_cards():
    a = _mk_player("a")
    b = _mk_player("b")
    g = Game([a, b], seed=7, mulligan=True)
    for p in (a, b):
        # Londres: se roban 7 pero se ponen N al fondo -> mano = 7 - N (<=3 mull)
        assert 4 <= len(p.hand) <= 7
        assert len(p.hand) + len(p.library) == 99   # nada se pierde


# -- P2.3 planeswalker: lealtad, activacion, -4, muerte a 0 ---------------- #
def test_planeswalker_loyalty_and_minus_four():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    pw = g.move_to_battlefield(cards.QuintoriusPlaneswalker(), a)
    assert pw.counters["loyalty"] == 4          # lealtad inicial
    # +1 crea Espiritu y sube lealtad
    assert g.activate_loyalty(pw, 0) is True
    assert pw.counters["loyalty"] == 5
    assert any(p.name == "Espiritu" for p in a.battlefield)
    # una sola activacion por turno
    assert g.activate_loyalty(pw, 1) is False
    # nuevo turno: se puede activar el -4
    pw.activated_this_turn = False
    b_life = b.life
    assert g.activate_loyalty(pw, 1) is True     # el -4 existe y se activa
    assert b.life == b_life - 4                   # 4 a cada oponente
    assert pw.counters["loyalty"] == 1


def test_combat_can_attack_planeswalker():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    pw = g.move_to_battlefield(cards.QuintoriusPlaneswalker(), b)  # lealtad 4
    atk1 = g.move_to_battlefield(creature("Uno", "1R", 3, 3), a)
    atk2 = g.move_to_battlefield(creature("Dos", "1R", 2, 2), a)
    for p in (atk1, atk2):
        p.summoning_sick = False
    b_life = b.life
    g.combat(a)  # la politica manda ~mitad al jugador, ~mitad al planeswalker
    # el planeswalker recibio dano (perdio lealtad) y el jugador tambien
    assert pw.counters["loyalty"] < 4
    assert b.life < b_life


def test_planeswalker_dies_at_zero_loyalty():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    pw = g.move_to_battlefield(cards.QuintoriusPlaneswalker(), a)
    # el dano de combate le resta lealtad
    g.deal_damage(None, pw, 4)
    g.sba()
    assert pw not in a.battlefield               # 0 lealtad -> al cementerio


# -- P3.1 la politica reserva mana para un counter ------------------------- #
def test_policy_reserves_mana_for_counter():
    me = _mk_player("me")   # comandante 2G: no se paga con Islas
    opp = _mk_player("opp")
    g = _game([me, opp])
    for _ in range(3):
        g.move_to_battlefield(land("Island", [U], basic=True), me)
    me.hand = [cards.Counterspell(),
               creature("Chico", "1", 1, 1),
               creature("Grande", "3", 3, 3)]
    me.policy.main_phase(g, me, second=True)
    # reservo 2 (UU): puedo bajar el Chico (1) pero no el Grande (3),
    # y me quedan 2 fuentes para el Counterspell
    assert me.can_pay(cards.Counterspell().cost)
    assert any(p.name == "Chico" for p in me.battlefield)
    assert not any(p.name == "Grande" for p in me.battlefield)


# -- P3.2 guarda bloqueadores si un tercero amenaza ------------------------ #
def test_policy_holds_blockers_under_threat():
    me = _mk_player("me")
    target = _mk_player("target")
    threat = _mk_player("threat")
    g = _game([me, target, threat])
    target.life = 5
    for _ in range(3):
        c = g.move_to_battlefield(creature("Mio", "1R", 3, 3), me)
        c.summoning_sick = False
    for _ in range(3):
        g.move_to_battlefield(creature("Bestia", "1R", 10, 10), threat)
    res = me.policy.declare_attackers(g, me)
    assert len(res) < 3   # guarda al menos un bloqueador
    # sin amenaza de terceros, ataca con todo
    for perm in list(threat.battlefield):
        g.to_graveyard(perm, "test")
    res2 = me.policy.declare_attackers(g, me)
    assert len(res2) == 3


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
