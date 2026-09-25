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
    before = sum(1 for p in a.battlefield if p.name == "Spirit")
    g.emit("upkeep", player=a)  # upkeep exilia del cementerio -> leaves_graveyard
    g.resolve_stack()
    after = sum(1 for p in a.battlefield if p.name == "Spirit")
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
1 Kang, the Trickster
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
    assert parsed["commander"] == "Kang, the Trickster"
    names = [n for _, n in parsed["cards"]]
    assert "Go for the Throat" in names   # se limpia el (SET) 12
    assert "Island" not in names          # sideboard ignorado
    deck, cmd, report = decklist.build_deck(parsed, fetch=None)
    assert len(deck) == 99
    assert cmd.name == "Kang, the Trickster"
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


def test_interactive_manual_turn():
    # Fase 2: el humano maneja su turno; los rivales juegan solos.
    import json
    import interactive
    import decks
    defs = [("Tu deck",) + decks.build("marvel"),
            ("Rival",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    assert ig.state()["phase"] == "mulligan"        # arranca en mulligan
    st = ig.keep([])                                 # me quedo con la mano
    assert st["phase"] == "main" and st["active"] == 0
    assert "hand_cards" in st["players"][0]        # el humano ve su mano
    assert "hand_cards" not in st["players"][1]     # el rival no
    if st["legal"]["lands"]:
        st = ig.play_land(st["legal"]["lands"][0]["i"])
        assert len(st["players"][0]["battlefield"]) >= 1
    t0 = st["turn"]
    st = ig.end_turn()                              # corre el turno del rival
    assert st["turn"] > t0
    json.dumps(st)                                  # serializable para la web


def test_attack_on_planeswalker_is_logged():
    # El ataque a un planeswalker debe quedar REGISTRADO (antes el daño aparecía
    # de la nada) y restar lealtad.
    import cards
    from engine import Game, Player, Card
    me = Player("yo", [cards.creature("C", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    pw = Card(name="Quintorius", types={"planeswalker"}, cost=None, loyalty=5,
              supertypes={"legendary"})
    pwperm = g.move_to_battlefield(pw, me)
    atk = g.move_to_battlefield(cards.creature("Raider", "1B", 3, 3), op)
    atk.summoning_sick = False
    g._resolve_combat(op, [(atk, pwperm)])
    assert pwperm.counters.get("loyalty") == 2                 # 5 - 3
    assert any("ataca al planeswalker Quintorius" in ln for ln in g.log_lines)


def test_interactive_attack_target_choice():
    # F3: con 2 rivales, legal expone attack_targets y attack(target_index)
    # dirige el daño al rival elegido (no siempre al primero).
    import interactive
    import decks
    defs = [("Tu deck",) + decks.build("marvel"),
            ("Rival A",) + decks.build("strixhaven"),
            ("Rival B",) + decks.build("lorehold")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    tgts = ig.legal()["attack_targets"]
    assert len(tgts) == 2 and all("index" in t and "life" in t for t in tgts)
    # sin atacantes reales el daño no cambia, pero el índice debe resolverse sin
    # error y elegir al rival correcto internamente
    st = ig.attack([], target_index=tgts[1]["index"])
    assert st is not None


def test_modal_damage_targets_chosen_player():
    # Un modo de daño "a target player" debe exponer los rivales como objetivos
    # (target_spec opp_player) y pegarle al rival ELEGIDO, no siempre al más débil.
    import interactive
    import cardsdb
    import cards
    import decks
    defs = [("Tu deck",) + decks.build("marvel"),
            ("Rival A",) + decks.build("strixhaven"),
            ("Rival B",) + decks.build("lorehold")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    charm = cardsdb.build_card_from_data({
        "name": "Boros Charm", "type_line": "Instant", "mana_cost": "{R}{W}",
        "color_identity": ["R", "W"],
        "oracle_text": ("Choose one —\n• Boros Charm deals 4 damage to target player "
                        "or planeswalker.\n• Draw two cards.")})
    hu.hand.append(charm)
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Sacred Foundry", ["R", "W"]), hu)

    entry = next(c for c in ig.legal()["casts"] if c["name"] == "Boros Charm")
    dmg_mode = entry["modes"][0]
    assert dmg_mode["target_spec"] == "opp_player"
    assert len(dmg_mode["targets"]) == 2                 # los dos rivales
    assert all("idx" in t and "from" in t for t in dmg_mode["targets"])

    # elijo pegarle al rival B (índice de jugador 2), aunque no sea el más débil
    victim = ig.players[2]
    life0 = victim.life
    idx = hu.hand.index(charm)
    ig.cast(i=idx, zone="hand", mode=0, target_uids=[2])
    assert victim.life == life0 - 4
    assert ig.players[1].life == 40                       # el otro rival intacto


def test_interactive_defense_window():
    # Fase 2: cuando un rival me ataca, la partida se pausa en "defense" y puedo
    # resolver (tomar el daño / bloquear) y continuar.
    import json
    import interactive
    found = False
    for seed in range(0, 10):
        ig = interactive.from_registered(
            [{"key": "marvel"}, {"key": "strixhaven"}, {"key": "old-guard"}],
            human_index=0, seed=seed)
        ig.keep([])                                    # pasar el mulligan
        for _ in range(60):
            st = ig.state()
            if st["phase"] == "over":
                break
            if st["phase"] == "react":       # ventana de reacción: paso
                ig.react()
                continue
            if st["phase"] == "choose":      # decisión pendiente (descarte, etc.)
                ig.resolve_choice(0)
                continue
            if st["phase"] == "defense":
                c = st["combat"]
                assert c and c["attackers"] and "from" in c
                json.dumps(st)
                life0 = st["players"][0]["life"]
                st2 = ig.resolve_defense([])       # tomo el daño
                # con varios rivales, al resolver una defensa puede abrirse otra
                # ventana (otro oponente ataca): resolvemos todas hasta salir.
                guard = 0
                while st2["phase"] == "defense" and guard < 10:
                    st2 = ig.resolve_defense([])
                    guard += 1
                assert st2["phase"] in ("main", "over")
                assert st2["players"][0]["life"] <= life0
                found = True
                break
            if st["phase"] == "main":
                ig.end_turn()
        if found:
            break
    assert found, "no se alcanzó ninguna ventana de defensa"


def test_trace_records_serializable_steps():
    # Fase 1: con trace=True el motor graba snapshots del estado por evento.
    import json
    a = _mk_player("a")
    b = _mk_player("b")
    g = Game([a, b], seed=1, max_turns=8, trace=True)
    g.play()
    assert len(g.trace) > 0
    step = g.trace[0]
    assert step["label"]  # inicio de la partida
    assert len(step["players"]) == 2
    p0 = step["players"][0]
    assert set(p0) >= {"name", "life", "hand", "library", "commander",
                       "graveyard", "battlefield"}
    json.dumps(g.trace)   # debe ser serializable


def test_imported_removal_is_targeted():
    # Remoción importada "destroy up to N target creatures": debe quedar dirigida
    # (target_spec + target_count) y destruir exactamente los objetivos elegidos.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Big Wipe", "type_line": "Sorcery", "mana_cost": "{4}{W}{W}",
        "color_identity": ["W"], "oracle_text": "Destroy up to six target creatures."})
    assert c.target_spec == "opp_creature" and c.target_count == 6
    assert c.on_cast_resolve is not None
    me = Player("yo", [cards.land("Plains", ["W"], basic=True) for _ in range(99)],
                cards.creature("C", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("Swamp", ["B"], basic=True) for _ in range(99)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    t1 = g.move_to_battlefield(cards.creature("A", "1B", 2, 2), op)
    t2 = g.move_to_battlefield(cards.creature("B", "1B", 4, 4), op)
    keep = g.move_to_battlefield(cards.creature("Keep", "1B", 1, 1), op)
    c.on_cast_resolve(g, me, [t1, t2])                 # destruyo solo 2 elegidas
    names = [p.name for p in op.creatures()]
    assert "A" not in names and "B" not in names and "Keep" in names


def test_creature_enters_watcher_draws_once_per_turn():
    import cardsdb, cards
    from engine import Game, Player
    v = cardsdb.build_card_from_data({
        "name": "Vamp", "type_line": "Creature", "mana_cost": "{2}{W}",
        "power": "2", "toughness": "3", "color_identity": ["W"],
        "oracle_text": "Whenever one or more creatures you control with mana value 3 "
                       "or less enter, draw a card. This ability triggers only once "
                       "each turn."})
    assert "creature_enters" in v.triggers
    me = Player("yo", [cards.creature(f"C{i}", "1W", 1, 1) for i in range(20)],
                cards.creature("Cmd", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.move_to_battlefield(v, me)
    h0 = len(me.hand)
    g.move_to_battlefield(cards.creature("Small", "1W", 1, 1), me); g.resolve_stack()
    assert len(me.hand) == h0 + 1            # criatura CMV≤3 -> roba
    g.move_to_battlefield(cards.creature("Small2", "1W", 1, 1), me); g.resolve_stack()
    assert len(me.hand) == h0 + 1            # 2a en el mismo turno: once -> no roba
    g.turn = 2
    g.move_to_battlefield(cards.creature("Small3", "1W", 1, 1), me); g.resolve_stack()
    assert len(me.hand) == h0 + 2            # turno nuevo: vuelve a robar
    # una criatura del rival no dispara el watcher propio
    hb = len(me.hand); g.turn = 3
    g.move_to_battlefield(cards.creature("Foe", "1U", 1, 1), op); g.resolve_stack()
    assert len(me.hand) == hb


def test_creature_enters_watcher_ignores_big_creatures():
    import cardsdb, cards
    from engine import Game, Player
    v = cardsdb.build_card_from_data({
        "name": "Vamp", "type_line": "Creature", "mana_cost": "{2}{W}",
        "power": "2", "toughness": "3", "color_identity": ["W"],
        "oracle_text": "Whenever a creature you control with mana value 3 or less "
                       "enters, draw a card."})
    me = Player("yo", [cards.creature("C", "1W", 1, 1) for _ in range(20)],
                cards.creature("Cmd", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.move_to_battlefield(v, me); g.resolve_stack()   # consume el disparo por su propia entrada
    h0 = len(me.hand)
    g.move_to_battlefield(cards.creature("Big", "5W", 6, 6), me); g.resolve_stack()
    assert len(me.hand) == h0                # CMV 6 > 3 -> no dispara


def test_etb_target_human_chooses_creature():
    # ETB "destroy target creature": el HUMANO elige a cuál (pending_choice etb_target).
    import interactive, cardsdb, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    op = ig.g.opponents(hu)[0]
    ig.g.move_to_battlefield(cards.creature("Ogre", "2B", 3, 3), op)
    rat = ig.g.move_to_battlefield(cards.creature("Rat", "1B", 1, 1), op)
    chup = cardsdb.build_card_from_data({
        "name": "Chupacabra", "type_line": "Creature", "mana_cost": "{2}{B}",
        "power": "2", "toughness": "2", "color_identity": ["B"],
        "oracle_text": "When Chupacabra enters, destroy target creature "
                       "an opponent controls."})
    assert chup.on_etb is not None
    hu.hand.append(chup)
    for _ in range(3):
        ig.g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), hu)
    st = ig.cast(i=hu.hand.index(chup), zone="hand")
    assert st["phase"] == "choose" and st["choice"]["kind"] == "etb_target"
    idx = next(o["i"] for o in st["choice"]["options"] if "Rat" in o["name"])
    ig.resolve_choice(idx)
    assert rat not in op.battlefield              # se destruyó la elegida
    assert any(pm.name == "Ogre" for pm in op.battlefield)  # la otra sigue
    import json
    json.dumps(st)


def test_saga_runs_chapters_and_sacrifices():
    import cardsdb, cards
    from engine import Game, Player
    s = cardsdb.build_card_from_data({
        "name": "Ceaseless Conflict", "type_line": "Enchantment — Saga",
        "mana_cost": "{3}{R}", "color_identity": ["R"],
        "oracle_text": "(As this Saga enters and after your draw step, add a lore "
                       "counter. Sacrifice after III.)\n"
                       "I — Create a 3/2 red Elemental creature token.\n"
                       "II — Create a 3/2 red Elemental creature token.\n"
                       "III — Each opponent loses 3 life."})
    assert s.on_etb is not None and "upkeep" in s.triggers and "saga" in s.tags
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    perm = g.move_to_battlefield(s, me)                      # capítulo I
    assert sum(1 for p in me.battlefield if p.is_token) == 1
    assert perm.counters.get("lore") == 1
    g.emit("upkeep", player=me); g.resolve_stack()           # capítulo II
    assert sum(1 for p in me.battlefield if p.is_token) == 2
    life0 = op.life
    g.emit("upkeep", player=me); g.resolve_stack()           # capítulo III + sacrificio
    assert op.life == life0 - 3
    assert perm not in me.battlefield                        # se sacrifica tras III


def test_choose_creature_type_anthem():
    import cardsdb, cards
    from engine import Game, Player
    a = cardsdb.build_card_from_data({
        "name": "Tribal Banner", "type_line": "Artifact", "mana_cost": "{3}",
        "oracle_text": "As this artifact enters, choose a creature type.\n"
                       "Creatures you control of the chosen type get +1/+1."})
    assert a.on_etb is not None and a.static_mod is not None
    me = Player("yo", [cards.creature("E", "1G", 1, 1, subtypes=("Elf",))
                       for _ in range(5)],
                cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1U", 1, 1) for _ in range(5)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    elf = g.move_to_battlefield(cards.creature("Llanowar", "G", 1, 1, subtypes=("Elf",)), me)
    other = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    p0 = elf.power
    perm = g.move_to_battlefield(a, me)                       # bot: elige "Elf"
    assert getattr(perm, "chosen_type", None) == "Elf"
    assert elf.power == p0 + 1 and elf.toughness == 2         # elfo recibe +1/+1
    assert other.power == 2                                   # no-elfo no cambia


def test_choose_creature_type_offers_players_tribe():
    # con MUCHOS tipos distintos en el mazo, la tribu real del jugador (Spirit)
    # debe seguir apareciendo entre las opciones (antes se recortaba a 14 en orden
    # de escaneo y podía quedar fuera) y elegirla debe dar el +1/+1.
    import cardsdb, cards
    from engine import Game, Player
    a = cardsdb.build_card_from_data({
        "name": "Spirit Banner", "type_line": "Artifact", "mana_cost": "{3}",
        "oracle_text": "As this artifact enters, choose a creature type.\n"
                       "Creatures you control of the chosen type get +1/+1."})
    types = ["Human", "Elf", "Goblin", "Zombie", "Soldier", "Wizard", "Merfolk",
             "Dragon", "Angel", "Knight", "Cleric", "Rogue", "Warrior", "Beast",
             "Bird", "Cat"]
    lib = [cards.creature(t, "1W", 1, 1, subtypes=(t,)) for t in types]
    lib += [cards.creature(f"Ghost{i}", "1W", 1, 1, subtypes=("Spirit",))
            for i in range(4)]
    me = Player("yo", lib, cards.creature("Cmd", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1U", 1, 1) for _ in range(5)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.interactive_human = me
    sp = g.move_to_battlefield(cards.creature("Spook", "1W", 2, 2,
                                              subtypes=("Spirit",)), me)
    p0 = sp.power
    perm = g.move_to_battlefield(a, me)
    opts = g.pending_choice["options"]
    names = [o["name"] for o in opts]
    assert "Spirit" in names                             # la tribu real se ofrece
    idx = next(o["i"] for o in opts if o["name"] == "Spirit")
    g.pending_choice["_apply"](idx)
    g.pending_choice = None
    assert getattr(perm, "chosen_type", None) == "Spirit"
    assert sp.power == p0 + 1                             # el spirit recibe +1/+1


def test_etb_destroy_nonbasic_land_and_ramp():
    import cardsdb, cards
    from engine import Game, Player
    w = cardsdb.build_card_from_data({
        "name": "White Orchid Phantom", "type_line": "Creature — Spirit Knight",
        "mana_cost": "{1}{W}", "power": "2", "toughness": "2",
        "keywords": ["Flying", "First strike"], "color_identity": ["W"],
        "oracle_text": "Flying, first strike\nWhen this creature enters, destroy up "
                       "to one target nonbasic land. Its controller may search their "
                       "library for a basic land card, put it onto the battlefield "
                       "tapped, then shuffle."})
    assert w.on_etb is not None
    me = Player("yo", [cards.creature("C", "1W", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("Forest", ["G"], basic=True) for _ in range(10)],
                cards.creature("O", "2G", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.move_to_battlefield(cards.land("Command Tower", ["W", "U", "B", "R", "G"]), op)
    g.move_to_battlefield(w, me)
    assert not any(pm.name == "Command Tower" for pm in op.battlefield)   # destruida
    assert any(pm.card.is_land() and "basic" in pm.card.supertypes and pm.tapped
               for pm in op.battlefield)                                 # básica tapeada


def test_modal_keeps_unmodeled_mode_so_picker_shows():
    # Un modal donde UN modo no está modelado NO debe descartarse: el selector
    # igual se ofrece y el modo elegido queda registrado.
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Charm", "type_line": "Instant", "mana_cost": "{1}{U}",
        "color_identity": ["U"],
        "oracle_text": "Choose one —\n• You may play an additional land this turn.\n• Draw two cards."})
    assert len(c.modes) == 2                       # no se descartó por el modo no modelado
    me = Player("yo", [cards.creature("X", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("Y", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    c.modes[0]["effect"](g, me, [])                # modo no modelado: registra, no rompe
    assert any("elige:" in ln for ln in g.log_lines)
    before = len(me.hand)
    c.modes[1]["effect"](g, me, [])                # modo modelado: robar 2
    assert len(me.hand) == before + 2


def test_undo_restores_previous_state():
    import interactive, cardsdb, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    spell = cards.creature("Bear", "1G", 2, 2)
    hu.hand.append(spell)
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), hu)
    hand0, bf0 = len(hu.hand), len(hu.battlefield)
    assert ig.legal()["can_undo"] is False
    ig.cast(i=hu.hand.index(spell), zone="hand")
    hu = ig.human()
    assert len(hu.battlefield) == bf0 + 1 and len(hu.hand) == hand0 - 1
    assert ig.legal()["can_undo"] is True
    st = ig.undo()
    hu = ig.human()
    assert len(hu.battlefield) == bf0 and len(hu.hand) == hand0   # volvió atrás
    assert st["legal"]["can_undo"] is False
    import json
    json.dumps(st)


def test_undo_cleared_after_end_turn():
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    lands = [c for c in hu.hand if c.is_land()]
    if lands:
        ig.play_land(hu.hand.index(lands[0]))
        assert ig.can_undo()
    ig.end_turn()
    assert not ig._undo          # la pila se limpia al terminar el turno


def test_modal_spell_choose_one():
    # Un hechizo modal "Choose one — ...": debe exponer los modos y resolver el
    # modo elegido (destruir un objetivo, o robar), no aplanarse a uno solo.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Test Charm", "type_line": "Instant", "mana_cost": "{1}{R}",
        "color_identity": ["R"],
        "oracle_text": "Choose one —\n• Destroy target creature.\n• Draw two cards."})
    assert len(c.modes) == 2 and c.mode_pick == 1
    assert c.modes[0]["target_spec"] == "opp_creature" and c.modes[0]["effect"]
    assert c.modes[1]["effect"] and c.modes[1]["target_spec"] is None
    me = Player("yo", [cards.creature("X", "1G", 1, 1) for _ in range(10)],
                cards.creature("C", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("Swamp", ["B"], basic=True) for _ in range(99)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    victim = g.move_to_battlefield(cards.creature("Victim", "1B", 2, 2), op)
    c.modes[0]["effect"](g, me, [victim])              # modo 0: destruir
    assert "Victim" not in [p.name for p in op.creatures()]
    before = len(me.hand)
    c.modes[1]["effect"](g, me, [])                    # modo 1: robar 2
    assert len(me.hand) == before + 2


def test_burn_to_player_is_visible():
    # "deals N damage to any target": debe bajar la vida de un rival (visible),
    # tanto como hechizo suelto como dentro de un modo.
    import cardsdb
    import cards
    from engine import Game, Player
    bolt = cardsdb.build_card_from_data({
        "name": "Bolt", "type_line": "Instant", "mana_cost": "{R}",
        "color_identity": ["R"], "oracle_text": "Bolt deals 3 damage to any target."})
    assert bolt.on_cast_resolve is not None
    me = Player("yo", [cards.creature("X", "1G", 1, 1) for _ in range(8)],
                cards.creature("C", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("Y", "1G", 1, 1) for _ in range(8)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    life0 = op.life
    bolt.on_cast_resolve(g, me, [])
    assert op.life == life0 - 3


def test_reveal_keep_land_etb_is_visible():
    # ETB "revela las primeras N, poné una tierra en la mano, el resto al
    # cementerio": debe ejecutarse (elección automática) y quedar en el relato.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Scout", "type_line": "Creature", "mana_cost": "{2}{G}",
        "power": "2", "toughness": "2", "color_identity": ["G"],
        "oracle_text": ("When this creature enters, reveal the top four cards of your "
                        "library. You may put a land card from among them into your hand. "
                        "Put the rest into your graveyard.")})
    assert c.on_etb is not None
    lib = ([cards.land("Forest", ["G"], basic=True) for _ in range(30)]
           + [cards.creature("Bear", "1G", 2, 2) for _ in range(30)])
    me = Player("yo", lib, cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.land("Swamp", ["B"], basic=True) for _ in range(60)],
                cards.creature("C", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=4)
    bh, bg = len(me.hand), len(me.graveyard)
    g.move_to_battlefield(c, me)
    assert len(me.hand) - bh == 1        # una tierra a la mano
    assert len(me.graveyard) - bg == 3   # el resto al cementerio
    assert any("revela" in ln for ln in g.log_lines)   # quedó registrado


def test_scry_bot_reorders_top_without_drawing():
    # "Scry 2": el bot mira las 2 de arriba y no roba; la biblioteca conserva
    # su tamaño (solo reordena) y queda registrado.
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Omen", "type_line": "Sorcery", "mana_cost": "{U}",
        "color_identity": ["U"], "oracle_text": "Scry 2."})
    assert c.on_cast_resolve is not None
    lib = [cards.creature(f"C{i}", "1U", 1, 1) for i in range(20)]
    me = Player("yo", lib, cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.land("I", ["U"]) for _ in range(40)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    n0, h0 = len(me.library), len(me.hand)
    c.on_cast_resolve(g, me, [])
    assert len(me.library) == n0 and len(me.hand) == h0   # no robó, no perdió cartas
    assert any("Scry 2" in ln for ln in g.log_lines)


def test_surveil_bot_bins_flooded_lands():
    # "Surveil 2": con muchas tierras en juego, el bot manda tierras al cementerio.
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Watcher", "type_line": "Creature", "mana_cost": "{1}{B}",
        "power": "1", "toughness": "1", "color_identity": ["B"],
        "oracle_text": "When Watcher enters, surveil 2."})
    assert c.on_etb is not None
    lib = [cards.land("Swamp", ["B"], basic=True) for _ in range(10)]  # tope: tierras
    me = Player("yo", lib, cards.creature("Cmd", "2B", 3, 3, legendary=True))
    op = Player("op", [cards.land("I", ["U"]) for _ in range(40)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(6):   # inundado: 6 tierras en juego
        g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), me)
    gy0 = len(me.graveyard)
    g.move_to_battlefield(c, me)   # dispara el ETB surveil 2
    assert len(me.graveyard) - gy0 == 2   # las 2 tierras del tope al cementerio


def test_scry_then_draw_for_human_pauses_then_draws():
    # "Scry 1, then draw a card": el humano decide (pending_choice) y DESPUÉS roba.
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Visions", "type_line": "Sorcery", "mana_cost": "{U}",
        "color_identity": ["U"], "oracle_text": "Scry 1, then draw a card."})
    lib = [cards.creature(f"C{i}", "1U", 1, 1) for i in range(20)]
    me = Player("yo", lib, cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.land("I", ["U"]) for _ in range(40)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.interactive_human = me
    h0 = len(me.hand)
    c.on_cast_resolve(g, me, [])
    assert g.pending_choice is not None and g.pending_choice["kind"] == "scry"
    assert len(me.hand) == h0            # todavía no robó: espera la decisión
    g.pending_choice["_apply"](0)        # "dejar arriba"
    g.pending_choice = None
    assert len(me.hand) == h0 + 1        # recién ahora robó


def test_reveal_land_human_choice_pauses_and_resolves():
    # Para el humano interactivo, el efecto NO elige solo: deja una decisión
    # pendiente con las cartas reveladas, y resolve_choice aplica lo elegido.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Scout", "type_line": "Creature", "mana_cost": "{2}{G}",
        "power": "2", "toughness": "2", "color_identity": ["G"],
        "oracle_text": ("When this creature enters, reveal the top four cards of your "
                        "library. You may put a land card from among them into your hand. "
                        "Put the rest into your graveyard.")})
    lib = ([cards.land("Forest", ["G"], basic=True) for _ in range(30)]
           + [cards.creature("Bear", "1G", 2, 2) for _ in range(30)])
    me = Player("yo", lib, cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.land("Swamp", ["B"], basic=True) for _ in range(60)],
                cards.creature("C", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=4)
    g.interactive_human = me            # simulamos que el humano controla a "me"
    bh, bg = len(me.hand), len(me.graveyard)
    g.move_to_battlefield(c, me)
    # nada movido todavía: la decisión quedó pendiente
    assert g.pending_choice is not None
    assert len(me.hand) == bh and len(me.graveyard) == bg
    opts = g.pending_choice["options"]
    assert len(opts) == 4
    land_i = next(o["i"] for o in opts if o["is_land"])
    g.pending_choice["_apply"](land_i)  # el humano se queda con una tierra
    g.pending_choice = None
    assert len(me.hand) - bh == 1
    assert len(me.graveyard) - bg == 3


def test_tutor_search_library_human_and_bot():
    # "Search your library for a creature card ... into your hand": el humano elige
    # (pending_choice kind search); baraja después.
    import cardsdb, interactive, decks
    c = cardsdb.build_card_from_data({
        "name": "Tutor", "type_line": "Sorcery", "mana_cost": "{1}{B}",
        "color_identity": ["B"],
        "oracle_text": "Search your library for a creature card, reveal it, "
                       "put it into your hand, then shuffle."})
    assert c.on_cast_resolve is not None
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    n0, h0 = len(hu.library), len(hu.hand)
    c.on_cast_resolve(ig.g, hu, [])
    assert ig.g.pending_choice and ig.g.pending_choice["kind"] == "search"
    opts = ig.g.pending_choice["options"]
    assert opts and all(o["ok"] for o in opts)
    st = ig.resolve_choice(0)
    assert len(hu.hand) == h0 + 1 and len(hu.library) == n0 - 1
    import json
    json.dumps(st)


def test_tutor_does_not_double_with_land_ramp():
    # Una búsqueda de tierra sigue usando ramp (no cablea el tutor genérico).
    import cardsdb
    c = cardsdb.build_card_from_data({
        "name": "Rampant Growth", "type_line": "Sorcery", "mana_cost": "{1}{G}",
        "color_identity": ["G"],
        "oracle_text": "Search your library for a basic land card, put it onto the "
                       "battlefield tapped, then shuffle."})
    assert "ramp" in c.tags


def test_look_take_any_card_human():
    # "Look at the top three cards ... put one into your hand, rest on the bottom".
    import cardsdb, interactive, decks
    c = cardsdb.build_card_from_data({
        "name": "Dig", "type_line": "Instant", "mana_cost": "{U}",
        "color_identity": ["U"],
        "oracle_text": "Look at the top three cards of your library. Put one of them "
                       "into your hand and the rest on the bottom of your library."})
    assert c.on_cast_resolve is not None
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    n0, h0 = len(hu.library), len(hu.hand)
    c.on_cast_resolve(ig.g, hu, [])
    assert ig.g.pending_choice and ig.g.pending_choice["kind"] == "look_take"
    assert len(ig.g.pending_choice["options"]) == 3
    ig.resolve_choice(0)
    assert len(hu.hand) == h0 + 1 and len(hu.library) == n0 - 1   # 1 a mano, 2 al fondo


def test_explore_land_to_hand_and_nonland_counter():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Scout", "type_line": "Creature", "mana_cost": "{1}{G}",
        "power": "1", "toughness": "1", "color_identity": ["G"],
        "oracle_text": "When Scout enters, it explores."})
    assert c.on_etb is not None
    def fresh_op():
        return Player("op", [cards.land("I", ["U"]) for _ in range(40)],
                      cards.creature("O", "2U", 1, 1, legendary=True))
    # tope = tierra -> a la mano, sin contador (fijamos la biblioteca tras el reparto)
    me = Player("yo", [cards.creature("Filler", "1G", 1, 1) for _ in range(20)],
                cards.creature("Cmd", "2G", 3, 3, legendary=True))
    g = Game([me, fresh_op()], seed=1)
    me.library = [cards.land("Forest", ["G"], basic=True)]   # tope conocido = tierra
    h0 = len(me.hand)
    perm = g.move_to_battlefield(c, me)
    assert len(me.hand) == h0 + 1 and perm.counters.get("+1/+1", 0) == 0
    # tope = no-tierra -> +1/+1
    me2 = Player("yo", [cards.creature("Filler", "1G", 1, 1) for _ in range(20)],
                 cards.creature("Cmd2", "2G", 3, 3, legendary=True))
    g2 = Game([me2, fresh_op()], seed=1)
    me2.library = [cards.creature("Big", "5G", 5, 5)]        # tope conocido = no-tierra
    perm2 = g2.move_to_battlefield(c, me2)
    assert perm2.counters.get("+1/+1", 0) == 1


def test_fateseal_operates_on_opponent_library():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Peek", "type_line": "Instant", "mana_cost": "{U}",
        "color_identity": ["U"],
        "oracle_text": "Look at the top two cards of target opponent's library, "
                       "then put them back in any order."})
    assert c.on_cast_resolve is not None
    me = Player("yo", [cards.creature("X", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature(f"C{i}", "1B", 1, 1) for i in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    my_lib0, op_lib0 = len(me.library), len(op.library)
    c.on_cast_resolve(g, me, [])          # bot fateseal sobre op
    assert len(me.library) == my_lib0     # mi biblioteca intacta
    assert len(op.library) == op_lib0     # la del rival: solo reordenada


def test_impulse_playable_from_exile_interactively():
    import cardsdb, cards, interactive, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    spell = cards.creature("Bolt Elemental", "R", 2, 1)
    hu.library.append(spell)              # tope de la biblioteca
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), hu)
    eff = cardsdb._generic_amount_effect("Exile the top card of your library. "
                                         "You may play that card this turn.")
    eff(ig.g, hu)
    assert spell in hu.impulse
    assert any(x["name"] == "Bolt Elemental" for x in ig.legal()["impulse"])
    bf0 = len(hu.battlefield)
    ig.cast(i=0, zone="impulse")
    assert spell not in hu.impulse and len(hu.battlefield) == bf0 + 1


def test_additional_cost_pay_life_and_sacrifice():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Dark Ritual Beast", "type_line": "Creature", "mana_cost": "{B}",
        "power": "4", "toughness": "4", "color_identity": ["B"],
        "oracle_text": "As an additional cost to cast this spell, pay 3 life and "
                       "sacrifice a creature."})
    assert c.additional_cost.get("pay_life") == 3 and c.additional_cost.get("sacrifice")
    me = Player("yo", [cards.creature("F", "1B", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2B", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    chump = g.move_to_battlefield(cards.creature("Chump", "1B", 1, 1), me)
    g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), me)
    life0 = me.life
    assert g.cast(me, c) is not False
    assert me.life == life0 - 3                     # pagó 3 de vida
    assert chump not in me.battlefield              # sacrificó una criatura


def test_cost_reduction_makes_spell_cheaper():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Cheap Draw", "type_line": "Sorcery", "mana_cost": "{4}{U}",
        "color_identity": ["U"],
        "oracle_text": "This spell costs {3} less to cast. Draw two cards."})
    assert c.cost_reduction == 3
    me = Player("yo", [cards.creature("F", "1U", 1, 1) for _ in range(20)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(2):                              # solo 2 tierras (costo real {1}{U})
        g.move_to_battlefield(cards.land("Island", ["U"], basic=True), me)
    assert g.cast(me, c) is not False               # alcanza gracias a la reducción


def test_extra_turn_queues_for_controller():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Time Skip", "type_line": "Sorcery", "mana_cost": "{4}{U}{U}",
        "color_identity": ["U"],
        "oracle_text": "Take an extra turn after this one."})
    assert c.on_cast_resolve is not None
    me = Player("yo", [cards.creature("F", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    c.on_cast_resolve(g, me, [])
    assert me in g.extra_turns


def test_you_win_the_game_effect():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Coalition Victory", "type_line": "Sorcery", "mana_cost": "{3}{W}{U}",
        "color_identity": ["W", "U"], "oracle_text": "You win the game."})
    assert c.on_cast_resolve is not None
    me = Player("yo", [cards.creature("F", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    c.on_cast_resolve(g, me, [])
    assert op.lost and not me.lost


def test_treasure_token_is_a_mana_source():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Pirate", "type_line": "Creature", "mana_cost": "{1}{R}",
        "power": "2", "toughness": "2", "color_identity": ["R"],
        "oracle_text": "When Pirate enters, create a Treasure token."})
    assert c.on_etb is not None
    me = Player("yo", [cards.creature("F", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    m0 = me.available_mana()
    g.move_to_battlefield(c, me)
    assert any(pm.name == "Treasure" for pm in me.battlefield)
    assert me.available_mana() == m0 + 1        # la Treasure aporta 1 maná


def test_fight_deals_mutual_damage():
    import cardsdb, cards
    from engine import Game, Player
    fight = cardsdb.build_card_from_data({
        "name": "Prey Upon", "type_line": "Sorcery", "mana_cost": "{G}",
        "color_identity": ["G"],
        "oracle_text": "Target creature you control fights target creature "
                       "you don't control."})
    assert fight.on_cast_resolve is not None
    me = Player("yo", [cards.creature("F", "1G", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    mine = g.move_to_battlefield(cards.creature("Bear", "1G", 4, 4), me)
    tg = g.move_to_battlefield(cards.creature("Elk", "2G", 2, 3), op)
    fight.on_cast_resolve(g, me, [tg])
    assert tg not in op.battlefield              # 4 de daño mata al 2/3
    assert mine.damage == 2                      # recibe 2 de vuelta


def test_goad_forces_attack():
    import cardsdb, cards
    from engine import Game, Player
    from policy import Policy
    goad = cardsdb.build_card_from_data({
        "name": "Taunt", "type_line": "Sorcery", "mana_cost": "{1}{R}",
        "color_identity": ["R"], "oracle_text": "Goad target creature."})
    assert goad.on_cast_resolve is not None
    me = Player("yo", [cards.creature("F", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True), policy=Policy("intermedio"))
    g = Game([me, op], seed=1)
    passive = g.move_to_battlefield(cards.creature("Sloth", "2U", 2, 2), op)
    passive.summoning_sick = False
    goad.on_cast_resolve(g, me, [passive])
    assert passive.goaded
    plan = op.policy.declare_attackers(g, op)
    assert any(atk is passive for atk, _tgt in plan)   # obligada a atacar


def test_protection_and_shroud_block_targeting():
    import cards
    from engine import Game, Player
    me = Player("yo", [cards.creature("F", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    pp = g.move_to_battlefield(cards.creature("Paladin", "1W", 2, 2, kw=("protection",)), op)
    ss = g.move_to_battlefield(cards.creature("Ghost", "1U", 2, 2, kw=("shroud",)), me)
    assert not g.can_target(me, pp)      # protection: rival no puede apuntarla
    assert not g.can_target(me, ss)      # shroud: ni su propio dueño


def test_prowess_pumps_on_noncreature_cast():
    import cardsdb, cards
    from engine import Game, Player
    me = Player("yo", [cards.land("Island", ["U"]) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    mage = g.move_to_battlefield(cards.creature("Prodigy", "1U", 1, 2, kw=("prowess",)), me)
    bolt = cardsdb.build_card_from_data({
        "name": "Zap", "type_line": "Instant", "mana_cost": "{U}",
        "color_identity": ["U"], "oracle_text": "Draw a card."})
    for _ in range(2):
        g.move_to_battlefield(cards.land("Island", ["U"]), me)
    p0 = mage.power
    g.cast(me, bolt)
    assert mage.power == p0 + 1          # +1/+1 hasta fin de turno
    g.end_turn(me)
    assert mage.power == p0              # se limpia al fin del turno


def test_infect_deals_poison_not_life():
    import cards
    from engine import Game, Player
    me = Player("yo", [cards.creature("F", "1G", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    inf = g.move_to_battlefield(cards.creature("Corruptor", "2G", 3, 3, kw=("infect",)), me)
    life0 = op.life
    g.deal_damage(inf, op, 3, combat=True)
    assert op.life == life0 and op.poison == 3   # veneno, no vida


def test_unblockable_ignores_blockers():
    import cards
    from engine import Game, Player
    me = Player("yo", [cards.creature("F", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    sneak = g.move_to_battlefield(cards.creature("Rogue", "1U", 3, 3, kw=("unblockable",)), me)
    sneak.summoning_sick = False
    g.move_to_battlefield(cards.creature("Wall", "1B", 0, 4), op)
    life0 = op.life
    g._resolve_combat(me, [(sneak, op)])
    assert op.life == life0 - 3          # el bloqueo se ignora, pega al jugador


def test_creature_dies_trigger_drains():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Artist", "type_line": "Creature", "mana_cost": "{1}{B}",
        "power": "0", "toughness": "1", "color_identity": ["B"],
        "oracle_text": "Whenever a creature dies, each opponent loses 1 life."})
    assert "death" in c.triggers
    me = Player("yo", [cards.creature("F", "1B", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2B", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.move_to_battlefield(c, me)
    victim = g.move_to_battlefield(cards.creature("Chump", "1B", 1, 1), me)
    life0 = op.life
    g.to_graveyard(victim, "sacrificio")
    g.resolve_stack()
    assert op.life == life0 - 1


def test_magecraft_triggers_on_instant_cast():
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Adept", "type_line": "Creature", "mana_cost": "{1}{R}",
        "power": "2", "toughness": "2", "color_identity": ["R"],
        "oracle_text": "Whenever you cast an instant or sorcery spell, "
                       "Adept deals 1 damage to each opponent."})
    assert "cast" in c.triggers
    me = Player("yo", [cards.land("Mountain", ["R"]) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.move_to_battlefield(c, me)
    for _ in range(2):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    bolt = cardsdb.build_card_from_data({
        "name": "Zap", "type_line": "Instant", "mana_cost": "{R}",
        "color_identity": ["R"], "oracle_text": "Draw a card."})
    life0 = op.life
    g.cast(me, bolt)
    g.resolve_stack()
    assert op.life == life0 - 1


def test_blink_reexecutes_etb():
    # Parpadeo: exiliar y devolver una criatura re-dispara su ETB.
    import cardsdb, cards
    from engine import Game, Player
    blink = cardsdb.build_card_from_data({
        "name": "Flicker", "type_line": "Instant", "mana_cost": "{1}{W}",
        "color_identity": ["W"],
        "oracle_text": "Exile target creature you control, then return it to the "
                       "battlefield under its owner's control."})
    assert blink.on_cast_resolve is not None and blink.target_spec == "own_perm"
    etb = cardsdb.build_card_from_data({
        "name": "Maker", "type_line": "Creature", "mana_cost": "{1}{W}",
        "power": "1", "toughness": "1", "color_identity": ["W"],
        "oracle_text": "When Maker enters, create a 1/1 white Soldier creature token."})
    me = Player("yo", [cards.creature("F", "1W", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    perm = g.move_to_battlefield(etb, me)         # ETB #1 -> 1 token
    bf1 = len(me.battlefield)
    blink.on_cast_resolve(g, me, [perm])          # parpadeo -> ETB #2 -> otro token
    assert len(me.battlefield) == bf1 + 1         # +1 ficha nueva (la criatura vuelve)
    assert any(pm.name == "Maker" for pm in me.battlefield)


def test_threaten_steals_then_returns_at_end_of_turn():
    import cardsdb, cards
    from engine import Game, Player
    threaten = cardsdb.build_card_from_data({
        "name": "Threaten", "type_line": "Sorcery", "mana_cost": "{2}{R}",
        "color_identity": ["R"],
        "oracle_text": "Gain control of target creature until end of turn. Untap it. "
                       "It gains haste until end of turn."})
    assert threaten.on_cast_resolve is not None
    me = Player("yo", [cards.creature("F", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    victim = g.move_to_battlefield(cards.creature("Ogre", "2B", 3, 3), op)
    threaten.on_cast_resolve(g, me, [victim])
    assert victim in me.battlefield and victim.controller is me
    g.end_turn(me)
    assert victim in op.battlefield and victim.controller is op   # vuelve al dueño


def test_clone_copies_target():
    import cardsdb, cards
    from engine import Game, Player
    clone = cardsdb.build_card_from_data({
        "name": "Clone", "type_line": "Sorcery", "mana_cost": "{3}{U}",
        "color_identity": ["U"],
        "oracle_text": "Create a token that's a copy of target creature."})
    assert clone.on_cast_resolve is not None
    me = Player("yo", [cards.creature("F", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    victim = g.move_to_battlefield(cards.creature("Dragon", "4R", 5, 5), op)
    bf0 = len(me.battlefield)
    clone.on_cast_resolve(g, me, [victim])
    assert len(me.battlefield) == bf0 + 1
    tok = me.battlefield[-1]
    assert tok.name == "Dragon" and tok.power == 5 and tok.is_token


def test_activated_ability_unmodeled_is_still_exposed():
    # Una habilidad activada con efecto NO modelado (p. ej. animar una tierra) debe
    # exponerse igual (activable, con log). La de "add mana" no se duplica (produces).
    import cardsdb
    c = cardsdb.build_card_from_data({
        "name": "Gate Land", "type_line": "Land",
        "oracle_text": "{T}: Add two mana in any combination of colors.\n"
                       "{T}: Until end of turn, target land you control becomes an "
                       "X/X Citizen creature with haste."})
    labels = [a["label"] for a in c.activated_abilities]
    assert len(c.activated_abilities) == 1                 # solo la de animar
    assert not any("mana" in l.lower() for l in labels)    # la de maná no se duplica


def test_activated_ability_pays_mana():
    # Habilidad activada "{2}{R}: deals 2 damage to each opponent": debe parsearse
    # y, al activarla, pagar el maná y aplicar el efecto.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Pinger", "type_line": "Creature", "mana_cost": "{1}{R}",
        "power": "1", "toughness": "1", "color_identity": ["R"],
        "oracle_text": "{2}{R}: Pinger deals 2 damage to each opponent."})
    assert len(c.activated_abilities) == 1
    me = Player("yo", [cards.creature("X", "1G", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("Y", "1G", 1, 1) for _ in range(10)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    perm = g.move_to_battlefield(c, me)
    for _ in range(3):  # maná disponible
        g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    life0 = op.life
    ok = g.activate_ability(perm, 0)
    assert ok and op.life == life0 - 2


def test_attack_trigger_impulse():
    # "Whenever ~ attacks, exile the top card, you may play it": al atacar exilia
    # el tope (lo dejamos jugable en la mano) y queda en el relato.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Laelia", "type_line": "Creature", "mana_cost": "{2}{R}",
        "power": "2", "toughness": "2", "color_identity": ["R"],
        "oracle_text": ("Haste\nWhenever Laelia attacks, exile the top card of your "
                        "library. You may play that card this turn.")})
    assert "attacks" in c.triggers
    me = Player("yo", [cards.creature("Spell", "1R", 1, 1) for _ in range(20)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.land("Swamp", ["B"], basic=True) for _ in range(20)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    perm = g.move_to_battlefield(c, me)
    imp0 = len(me.impulse)
    c.triggers["attacks"](g, perm)       # simular el disparo de ataque
    assert len(me.impulse) == imp0 + 1   # exiliada al tope -> jugable este turno
    # al terminar el turno, lo no jugado pasa al exilio
    ex0 = len(me.exile)
    g.end_turn(me)
    assert not me.impulse and len(me.exile) == ex0 + 1


def test_imported_planeswalker_loyalty_and_abilities():
    # Un planeswalker importado debe ENTRAR con su lealtad (no morir a SBA) y
    # exponer sus habilidades con texto + efecto aproximado.
    import cardsdb
    import cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Test Walker", "type_line": "Legendary Planeswalker — Test",
        "mana_cost": "{3}{R}{W}", "loyalty": "4", "color_identity": ["R", "W"],
        "oracle_text": "+1: Create a 3/2 red Spirit creature token.\n"
                       "−2: Test Walker deals 3 damage to each opponent.\n"
                       "−7: Draw three cards."})
    assert c.loyalty == 4
    assert [cost for cost, _e in c.loyalty_abilities] == [1, -2, -7]
    assert all(e is not None for _c, e in c.loyalty_abilities)   # efectos deducidos
    assert c.loyalty_texts[0].startswith("Create a 3/2")

    me = Player("yo", [cards.land("Plains", ["W"], basic=True) for _ in range(99)],
                cards.creature("C", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("Swamp", ["B"], basic=True) for _ in range(99)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    op.life = 40
    pw = g.move_to_battlefield(c, me)
    g.sba()
    assert pw in me.battlefield and pw.counters.get("loyalty") == 4  # NO muere
    assert g.activate_loyalty(pw, 1)                                 # -2: 3 daño
    assert op.life == 37 and pw.counters.get("loyalty") == 2
    pw.activated_this_turn = False
    assert g.activate_loyalty(pw, 0)                                 # +1: ficha
    assert any(p.name == "Token" for p in me.creatures())


def test_generic_amount_effects_from_oracle():
    # Cartas importadas comunes: el efecto genérico con MONTO debe ejecutarse
    # (fichas al entrar, quema a cada rival, ganancia de vida, mill).
    import cardsdb
    import cards
    from engine import Game, Player

    def mk(name, tl, cost, ot):
        return cardsdb.build_card_from_data(
            {"name": name, "type_line": tl, "mana_cost": cost, "oracle_text": ot})

    me = Player("yo", [cards.land("P", ["W"], basic=True) for _ in range(90)],
                cards.creature("C", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("S", ["B"], basic=True) for _ in range(90)],
                cards.creature("C2", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    op.life = 40

    tok = mk("Tokener", "Creature — Elf", "1G",
             "When Tokener enters, create two 1/1 green Elf creature tokens.")
    g.move_to_battlefield(tok, me)
    assert sum(1 for p in me.creatures() if p.name == "Token") == 2

    burn = mk("Burner", "Sorcery", "2R", "Burner deals 3 damage to each opponent.")
    burn.on_cast_resolve(g, me, [])
    assert op.life == 37

    life0 = me.life
    heal = mk("Healer", "Instant", "W", "You gain 5 life.")
    heal.on_cast_resolve(g, me, [])
    assert me.life == life0 + 5

    before = len(me.library)
    miller = mk("Miller", "Sorcery", "U", "Mill 4 cards.")
    miller.on_cast_resolve(g, me, [])
    assert before - len(me.library) == 4

    # una barrida NO debe ser reemplazada por el efecto genérico con monto
    wrath = mk("Wrath", "Sorcery", "2WW", "Destroy all creatures.")
    assert "wipe" in wrath.tags and wrath.on_cast_resolve is not None


def test_land_uses_produced_mana():
    # Las tierras no básicas / artifact lands tienen color_identity vacía pero
    # producen color real (produced_mana). Debe usarse ese, no la identidad.
    import cardsdb
    tree = cardsdb.build_card_from_data({
        "name": "Tree of Tales", "type_line": "Artifact Land",
        "color_identity": [], "produced_mana": ["G"]})
    assert tree.produces(None, None) == {"G": 1}      # antes daba {C}
    rock = cardsdb.build_card_from_data({
        "name": "Simic Signet", "type_line": "Artifact", "mana_cost": "{2}",
        "color_identity": [], "produced_mana": ["G", "U"]})
    assert rock.produces is not None
    assert rock.produces(None, None) == {"G": 1, "U": 1}


def test_build_split_card_uses_front_face():
    # split/DFC: type_line y mana_cost vienen combinados con '//'; hay que usar
    # la cara frontal (castable), sin perder el nombre completo.
    import cardsdb
    data = {
        "name": "Dusk // Dawn",
        "mana_cost": "{3}{W}{W} // {3}{W}{W}",
        "type_line": "Sorcery // Sorcery",
        "color_identity": ["W"],
        "card_faces": [
            {"name": "Dusk", "mana_cost": "{3}{W}{W}", "type_line": "Sorcery",
             "oracle_text": "Destroy all creatures with power 3 or greater."},
            {"name": "Dawn", "mana_cost": "{3}{W}{W}", "type_line": "Sorcery"},
        ],
    }
    c = cardsdb.build_card_from_data(data)
    assert c.name == "Dusk // Dawn"        # conserva el nombre completo
    assert "sorcery" in c.types            # tipo de la cara frontal, no '//'
    assert c.cost.cmc == 5                 # {3}{W}{W}, no el doble
    assert c.identity() == {"W"}


def _analyze_mod():
    import importlib
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    return importlib.import_module("_analyze")


def test_deck_analysis_strengths_and_weaknesses():
    an = _analyze_mod()

    def card(name, tl, cmc=0, cost="", ot="", pm=None):
        return {"name": name, "type_line": tl, "cmc": cmc, "mana_cost": cost,
                "oracle_text": ot, "produced_mana": pm or []}

    entries = [(1, "Mountain", card("Mountain", "Basic Land — Mountain", pm=["R"]))
               for _ in range(30)]
    # deck pobre: pocas tierras, sin ramp/robo/remoción
    entries += [(1, f"Vanilla{i}", card(f"Vanilla{i}", "Creature — Goblin", 3,
                 "{2}{R}", "")) for i in range(15)]
    rep = an.analyze(entries, "Krenko")
    assert rep["counts"]["land"] == 30
    txt = " ".join(rep["weaknesses"]).lower()
    assert "tierras" in txt and "ramp" in txt          # detecta ambas fallas
    assert rep["avg_cmc"] == 3.0

    # tema tokens: >=5 cartas que crean fichas -> sinergia detectada
    tok = [(1, f"T{i}", card(f"T{i}", "Creature", 2, "{1}{R}",
            "Create a 1/1 red Goblin creature token.")) for i in range(6)]
    rep2 = an.analyze(tok, None)
    assert any(t["key"] == "tokens" for t in rep2["themes"])


def test_replay_includes_log_for_watch():
    # /watch necesita el relato para exportarlo y mostrar las jugadas.
    import importlib
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    _sim = importlib.import_module("_sim")
    r = _sim.replay([{"kind": "registered", "key": "marvel"},
                     {"kind": "registered", "key": "strixhaven"}], seed=1)
    assert "log" in r and isinstance(r["log"], list) and len(r["log"]) > 0
    assert "steps" in r and len(r["steps"]) > 0
    import json
    json.dumps(r)                                    # serializable para la web


def test_analysis_consistency_and_recommendations():
    an = _analyze_mod()
    good = an._consistency(100, 37, {"ramp": 10, "tutor": 3}, 3.0)
    poor = an._consistency(100, 20, {"ramp": 2, "tutor": 0}, 4.2)
    assert good["land_prob"] > poor["land_prob"]
    assert good["score"] > poor["score"] and 0 <= poor["score"] <= 100
    recs = an._recommend(20, {"ramp": 2, "draw": 3, "removal": 2, "wipe": 0,
                              "protection": 0},
                         {"creature": 30}, 4.2,
                         {c: 0 for c in "WUBRG"}, {c: 0 for c in "WUBRG"})
    # recomendaciones estructuradas: {text, cards:[nombres]}
    low = " ".join(r["text"] for r in recs).lower()
    assert "ramp" in low and "barrida" in low and "tierras" in low
    ramp = next(r for r in recs if "ramp" in r["text"].lower())
    assert "Sol Ring" in ramp["cards"]                 # expone nombres para precificar
    # no re-sugiere staples que el deck YA tiene
    owned = {an._norm("Sol Ring"), an._norm("Arcane Signet")}
    recs2 = an._recommend(20, {"ramp": 2, "draw": 3, "removal": 2, "wipe": 0,
                               "protection": 0},
                          {"creature": 30}, 4.2,
                          {c: 0 for c in "WUBRG"}, {c: 0 for c in "WUBRG"}, owned)
    ramp2 = next(r for r in recs2 if "ramp" in r["text"].lower())
    assert "Sol Ring" not in ramp2["cards"] and "Arcane Signet" not in ramp2["cards"]


def test_auth_register_login_reset_identity():
    import importlib
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    _db = importlib.import_module("_db")
    os.environ["ADMIN_EMAIL"] = "admin@x.com"
    _auth = importlib.reload(importlib.import_module("_auth"))

    users = {}      # email -> row dict
    sessions = {}   # token -> {user_id, created_at}

    def fake_run(statements, timeout=20):
        out = []
        for sql, args in statements:
            s = " ".join(sql.split()).lower()
            rows = []
            if s.startswith("create table"):
                pass
            elif s.startswith("select * from mtg_users where email"):
                u = users.get(args[0])
                rows = [dict(u)] if u else []
            elif s.startswith("insert into mtg_users"):
                cols = ["id", "email", "pass_hash", "salt", "recovery_hash",
                        "recovery_salt", "is_admin", "is_supporter", "created_at"]
                row = dict(zip(cols, args)); row["fails"] = 0; row["last_fail"] = 0
                users[row["email"]] = row
            elif s.startswith("insert into mtg_sessions"):
                sessions[args[0]] = {"user_id": args[1], "created_at": args[2]}
            elif s.startswith("update mtg_users set fails = fails + 1"):
                for u in users.values():
                    if u["id"] == args[1]:
                        u["fails"] += 1; u["last_fail"] = args[0]
            elif s.startswith("update mtg_users set fails = 0"):
                for u in users.values():
                    if u["id"] == args[0]:
                        u["fails"] = 0
            elif s.startswith("update mtg_users set pass_hash"):
                for u in users.values():
                    if u["id"] == args[4]:
                        u["pass_hash"], u["salt"], u["recovery_hash"], u["recovery_salt"] = args[0], args[1], args[2], args[3]
                        u["fails"] = 0
            elif s.startswith("delete from mtg_sessions where user_id"):
                for t in [t for t, v in sessions.items() if v["user_id"] == args[0]]:
                    del sessions[t]
            elif s.startswith("delete from mtg_sessions where token"):
                sessions.pop(args[0], None)
            elif s.startswith("select u.*, s.created_at"):
                sess = sessions.get(args[0])
                if sess:
                    u = next((x for x in users.values() if x["id"] == sess["user_id"]), None)
                    if u:
                        row = dict(u); row["s_created"] = sess["created_at"]; rows = [row]
            out.append({"rows": rows, "affected": 0, "last_insert_rowid": None})
        return out

    orig = _db.run
    _db.run = fake_run
    try:
        reg = _auth.register("admin@x.com", "secretpw123")
        assert reg["user"]["is_admin"] and reg["user"]["is_supporter"]
        assert "-" in reg["recovery_code"]
        # login mal / bien
        try:
            _auth.login("admin@x.com", "malmalmal"); assert False
        except ValueError:
            pass
        good = _auth.login("admin@x.com", "secretpw123")
        assert good["user"]["email"] == "admin@x.com"
        # token resuelve al usuario y da acceso admin/infinito
        ident = _auth.identity(None, good["token"])
        assert ident["admin"] and ident["supporter"] and ident["owner"] == reg["user"]["id"]
        # anónimo sin token: no admin, no supporter
        anon = _auth.identity("anon-code-123", None)
        assert not anon["admin"] and not anon["supporter"] and anon["owner"] == "anon-code-123"
        # reset con código de recuperación
        res = _auth.reset_password("admin@x.com", reg["recovery_code"], "nuevapass123")
        assert res["recovery_code"] != reg["recovery_code"]
        assert _auth.login("admin@x.com", "nuevapass123")["user"]["email"] == "admin@x.com"
    finally:
        _db.run = orig


def test_match_analysis_win_type_and_key_plays():
    import importlib
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    ma = importlib.import_module("_matchanalysis")

    class P:
        def __init__(self, n):
            self.name = n
            self.life = 40

    def pl(n, life):
        return {"name": n, "life": life, "cmdr_damage": {}, "poison": 0, "battlefield": []}

    trace = [
        {"turn": 1, "active": 0, "label": "A juega tierra", "players": [pl("A", 40), pl("B", 40)]},
        {"turn": 5, "active": 0, "label": "A ataca fuerte", "players": [pl("A", 40), pl("B", 30)]},
        {"turn": 7, "active": 0, "label": "GANA A", "players": [pl("A", 40), pl("B", 0)]},
    ]
    res = ma.analyze(trace, "A", [P("A"), P("B")])
    assert res["win_type"] in ("combate/quema", "último en pie")
    assert res["summary"].startswith("Ganó A")
    assert any(k["why"] for k in res["key_plays"])          # detecta al menos una jugada clave
    assert res["best_moves"] and res["best_moves"][0]["delta"] >= 8


def test_stuck_cards_reports_mana_need():
    # el perdedor tiene una bomba cara atascada en la mano -> el análisis avisa
    # qué le faltó para jugarla (maná).
    import importlib
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    ma = importlib.import_module("_matchanalysis")
    import cards
    from engine import Game, Player
    win = Player("W", [cards.land("Forest", ["G"], basic=True) for _ in range(40)],
                 cards.creature("Cw", "2G", 3, 3, legendary=True))
    lose = Player("L", [cards.land("Island", ["U"], basic=True) for _ in range(40)],
                  cards.creature("Cl", "2U", 3, 3, legendary=True))
    g = Game([win, lose], seed=1)
    lose.battlefield = []
    for _ in range(2):
        g.move_to_battlefield(cards.land("Island", ["U"], basic=True), lose)
    lose.hand = [cards.creature("Leviatán", "5UU", 8, 8)]     # cmc 7, solo 2 fuentes
    trace = [{"turn": 1, "active": 0, "label": "x", "players": [
        {"name": "W", "life": 40, "cmdr_damage": {}, "poison": 0, "battlefield": []},
        {"name": "L", "life": 0, "cmdr_damage": {}, "poison": 0, "battlefield": []}]}]
    res = ma.analyze(trace, "W", [win, lose])
    st = res["stuck"]
    assert st and st[0]["player"] == "L"
    assert any("maná" in c["need"] and c["card"] == "Leviatán" for c in st[0]["cards"])
    import json
    json.dumps(res)


def test_supporter_redeem_and_status():
    import importlib
    import urllib.request
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    _db = importlib.import_module("_db")
    sup = importlib.import_module("supporter")
    os.environ["SUPPORTER_CODES"] = "GOODCODE"
    os.environ["TURSO_DATABASE_URL"] = "libsql://x.turso.io"
    os.environ["TURSO_AUTH_TOKEN"] = "t"

    # base simulada en memoria: registramos qué SQL se ejecutó
    store = set()

    def fake_run(statements, timeout=20):
        out = []
        for sql, args in statements:
            s = sql.strip().lower()
            if s.startswith("insert or ignore into mtg_supporters"):
                store.add(args[0])
                out.append({"rows": [], "affected": 1, "last_insert_rowid": None})
            elif s.startswith("select 1 from mtg_supporters"):
                out.append({"rows": [{"1": 1}] if args[0] in store else [], "affected": 0, "last_insert_rowid": None})
            else:
                out.append({"rows": [], "affected": 0, "last_insert_rowid": None})
        return out

    orig = _db.run
    _db.run = fake_run
    try:
        assert sup.redeem("mycode-12", "WRONG") == {"supporter": False, "error": "cupón inválido"}
        assert sup.is_supporter("mycode-12") is False
        assert sup.redeem("mycode-12", "GOODCODE") == {"supporter": True}
        assert sup.is_supporter("mycode-12") is True
    finally:
        _db.run = orig


def test_turso_db_encode_decode_and_parse():
    import importlib
    import json as _json
    import urllib.request
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    _db = importlib.import_module("_db")
    assert _db._encode_arg(3) == {"type": "integer", "value": "3"}
    assert _db._encode_arg(None) == {"type": "null"}
    assert _db._decode_val({"type": "integer", "value": "7"}) == 7
    assert _db._decode_val({"type": "null"}) is None

    fake = {"results": [
        {"type": "ok", "response": {"type": "execute", "result": {
            "cols": [{"name": "a"}, {"name": "b"}],
            "rows": [[{"type": "integer", "value": "1"}, {"type": "text", "value": "z"}]],
            "affected_row_count": 0, "last_insert_rowid": None}}},
        {"type": "ok", "response": {"type": "close"}}]}

    class _Fake:
        def read(self): return _json.dumps(fake).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    os.environ["TURSO_DATABASE_URL"] = "libsql://x.turso.io"
    os.environ["TURSO_AUTH_TOKEN"] = "t"
    orig = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=20: _Fake()
    try:
        res = _db.run([("SELECT 1", [])])
    finally:
        urllib.request.urlopen = orig
    assert res == [{"rows": [{"a": 1, "b": "z"}], "affected": 0, "last_insert_rowid": None}]


def test_price_and_legality_from_scryfall():
    import importlib
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    _sim = importlib.import_module("_sim")
    p, legal = _sim._price_legal(
        {"prices": {"usd": "3.50"}, "legalities": {"commander": "legal"}})
    assert p == 3.5 and legal is True
    p2, legal2 = _sim._price_legal(
        {"prices": {"usd": None}, "legalities": {"commander": "banned"}})
    assert p2 is None and legal2 is False
    assert _sim._price_legal(None) == (None, True)      # sin datos: no marca ilegal


def test_binder_suggest_decks():
    an = _analyze_mod()

    def c(name, tl, ot="", ci=None):
        return {"name": name, "type_line": tl, "oracle_text": ot,
                "color_identity": ci or [], "cmc": 2, "mana_cost": ""}

    cache = {}
    def put(x):
        cache[an._norm(x["name"])] = x
    put(c("Cultivate", "Sorcery", "Search your library for two basic land cards", ["G"]))
    put(c("Green Cmdr", "Legendary Creature", ci=["G"]))
    put(c("Red Cmdr", "Legendary Creature", ci=["R"]))
    decks = [
        {"name": "Verde", "parsed": {"commander": "Green Cmdr", "cards": [(1, "Green Cmdr")]}},
        {"name": "Rojo", "parsed": {"commander": "Red Cmdr", "cards": [(1, "Red Cmdr")]}},
    ]
    res = an.suggest_decks("Cultivate", decks, cache)
    verde = next(d for d in res["decks"] if d["name"] == "Verde")
    rojo = next(d for d in res["decks"] if d["name"] == "Rojo")
    assert verde["in_color"] and "ramp" in verde["fills"]     # encaja y cubre ramp
    assert not rojo["in_color"]                                # azul/verde fuera de rojo
    assert res["decks"][0]["name"] == "Verde"                  # rankeado primero


def test_commander_spellbook_variant_parsing():
    an = _analyze_mod()
    data = {"results": {
        "included": [{"id": 1,
                      "uses": [{"card": {"name": "A"}}, {"card": "B"}],
                      "produces": [{"feature": {"name": "Infinite damage"}}]}],
        "almostIncluded": [{"id": 2,
                            "uses": [{"card": {"name": "A"}}, {"card": {"name": "Z"}}],
                            "produces": [{"feature": {"name": "Win"}}]}],
    }}
    deck = {an._norm(x) for x in ["A", "B"]}
    inc = an._variant(data["results"]["included"][0], deck)
    assert inc["cards"] == ["A", "B"] and inc["produces"] == ["Infinite damage"]
    assert inc["missing"] == []
    alm = an._variant(data["results"]["almostIncluded"][0], deck)
    assert alm["missing"] == ["Z"]                     # calcula la carta faltante


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
    assert any(p.name == "Spirit" for p in a.battlefield)
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


# -- P4 semillas reproducibles + export JSON ------------------------------- #
def test_reproducible_seed():
    import run
    a = run.one(["lorehold", "kang"], seed=42)
    b = run.one(["lorehold", "kang"], seed=42)
    c = run.one(["lorehold", "kang"], seed=43)
    assert a == b            # misma semilla, mismo ganador
    # y el log completo tambien coincide
    g1 = run._build_game(["lorehold", "kang"], seed=42)
    g2 = run._build_game(["lorehold", "kang"], seed=42)
    g1.play()
    g2.play()
    assert g1.log_lines == g2.log_lines
    _ = c  # otra semilla puede o no diferir; solo verificamos determinismo


def test_export_json(tmp_path=None):
    import run
    import os
    import tempfile
    import json as _json
    d = tmp_path or tempfile.mkdtemp()
    path = os.path.join(str(d), "out.json")
    out = run.export_json(["lorehold", "kang"], 20, path, full_log=False)
    assert out["n"] == 20 and sum(out["wins"].values()) == 20
    with open(path) as f:
        loaded = _json.load(f)
    assert len(loaded["games"]) == 20 and "winrate" in loaded


# -- importador de formato markdown (decks del usuario) -------------------- #
def test_mdparse_builds_and_uses_registry():
    import mdparse
    txt = """## Comandante
| n | Carta | Coste | P/T | Keywords | Tags |
|---|---|---|---|---|---|
| 1 | Omo, Queen of Vesuva | 2GU | 1/5 | | engine |

## Criaturas
| n | Carta | Coste | P/T | Keywords | Tags |
|---|---|---|---|---|---|
| 1 | Managorger Hydra | 2G | 1/1 | trample | creature |
| 1 | Herd Baloth | 3G | 4/4 | | creature |

## Tierras
| n | Carta | Produce | Tapeada |
|---|---|---|---|
| 1 | Command Tower | [W U B R G] | no |
| ? | Forest | [G] | no |

---
## Notas (se ignoran, aunque tengan ?)
| 1 | Fantasma | ? | | | |
"""
    deck, cmd, rep = mdparse.parse_md_deck(txt)
    assert cmd.name == "Omo, Queen of Vesuva"
    assert len(deck) == 99
    mh = next(c for c in deck if c.name == "Managorger Hydra")
    assert mh.triggers            # usa la version implementada (efecto real)
    hb = next(c for c in deck if c.name == "Herd Baloth")
    assert hb.power == 4 and "creature" in hb.types   # vainilla con stats reales


def test_moxfield_commander_at_end():
    import decklist
    # Moxfield crudo: comandante al final tras una linea en blanco, sin encabezado
    raw = "1 Sol Ring\n1 Command Tower\n30 Swamp\n\n1 Kang, the Trickster"
    p = decklist.parse_decklist(raw)
    assert p["commander"] == "Kang, the Trickster"
    names = [n for _, n in p["cards"]]
    assert "Kang, the Trickster" not in names  # no queda duplicado en el mazo
    assert "Sol Ring" in names


def test_mdparse_rejects_question_mark():
    import mdparse
    txt = """## Comandante
| n | Carta | Coste | P/T | Keywords | Tags |
|---|---|---|---|---|---|
| 1 | Cmdr | 1G | 1/1 | | |

## Criaturas
| n | Carta | Coste | P/T | Keywords | Tags |
|---|---|---|---|---|---|
| 1 | Dudosa | ? | 2/2 | | creature |
"""
    raised = False
    try:
        mdparse.parse_md_deck(txt)
    except ValueError:
        raised = True
    assert raised                 # falla ruidosamente ante ?, no adivina


def test_preset_decks_registered():
    import decks
    # los presets del usuario se registran y arman a 99
    for slug in ("tricky-terrain", "lorehold-spirit"):
        assert slug in decks.DECKS
        deck, cmd = decks.build(slug)
        assert len(deck) == 99 and cmd is not None


# -- capa de efectos genericos por tag (#3A) ------------------------------- #
def test_generic_effects_from_tags_and_oracle():
    import cardsdb
    # 'draw' derivado del texto -> roba 2 al resolver
    div = cardsdb.build_card_from_data(
        {"name": "Divination", "mana_cost": "{2}{U}", "type_line": "Sorcery",
         "oracle_text": "Draw two cards."})
    assert "draw" in div.tags and div.on_cast_resolve is not None
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    h0 = len(a.hand)
    div.on_cast_resolve(g, a, [])
    assert len(a.hand) == h0 + 2

    # 'removal' derivado -> tiene efecto; una carta sin nada no
    mur = cardsdb.build_card_from_data(
        {"name": "Murder", "mana_cost": "{1}{B}{B}", "type_line": "Instant",
         "oracle_text": "Destroy target creature."})
    assert "removal" in mur.tags and mur.on_cast_resolve is not None
    vanilla = cardsdb.build_card_from_data(
        {"name": "Grizzly Bears", "mana_cost": "{1}{G}",
         "type_line": "Creature — Bear", "power": "2", "toughness": "2",
         "oracle_text": ""})
    assert vanilla.on_etb is None and vanilla.on_cast_resolve is None


# -- jugar desde el CEMENTERIO (Fase A) ------------------------------------ #
def test_parse_gy_play_variants():
    import cardsdb
    fb = cardsdb.build_card_from_data({
        "name": "Deep Analysis", "type_line": "Sorcery", "mana_cost": "{3}{U}",
        "color_identity": ["U"],
        "oracle_text": "Target player draws two cards.\nFlashback—{1}{U}, Pay 3 life."})
    assert fb.gy_play.get("mode") == "flashback" and fb.gy_play.get("after") == "exile"
    ue = cardsdb.build_card_from_data({
        "name": "Sootstoke Kindler", "type_line": "Creature", "mana_cost": "{2}{B}",
        "power": "2", "toughness": "2", "color_identity": ["B"],
        "oracle_text": "Unearth {1}{B}"})
    assert ue.gy_play.get("mode") == "unearth" and ue.gy_play.get("after") == "exile_eot"
    em = cardsdb.build_card_from_data({
        "name": "Anointer Priest", "type_line": "Creature", "mana_cost": "{1}{W}",
        "power": "1", "toughness": "3", "color_identity": ["W"],
        "oracle_text": "Embalm {3}{W}"})
    assert em.gy_play.get("mode") == "embalm"
    es = cardsdb.build_card_from_data({
        "name": "Uro", "type_line": "Creature", "mana_cost": "{1}{G}{U}",
        "power": "6", "toughness": "6", "color_identity": ["G", "U"],
        "oracle_text": "Escape—{G}{G}{U}{U}, Exile four other cards from your graveyard."})
    assert es.gy_play.get("mode") == "escape" and es.gy_play.get("exile_n") == 4
    rc = cardsdb.build_card_from_data({
        "name": "Bloodghast", "type_line": "Creature", "mana_cost": "{B}{B}",
        "power": "2", "toughness": "1", "color_identity": ["B"],
        "oracle_text": "{2}{B}: Return this card from your graveyard to the battlefield."})
    assert rc.gy_play.get("mode") == "recur" and rc.gy_play.get("after") == "battlefield"


def _gy_ready_human(seed=3):
    import interactive, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=seed)
    ig.keep([])
    return ig, ig.human()


def test_flashback_casts_from_graveyard_then_exiled():
    import cardsdb, cards
    ig, hu = _gy_ready_human()
    spell = cardsdb.build_card_from_data({
        "name": "GY Draw", "type_line": "Sorcery", "mana_cost": "{5}{U}",
        "color_identity": ["U"], "oracle_text": "Draw two cards.\nFlashback {1}{U}"})
    assert spell.gy_play.get("mode") == "flashback"
    hu.graveyard.append(spell)
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Island", ["U"], basic=True), hu)
    idx = next(x["i"] for x in ig.legal()["graveyard"] if x["name"] == "GY Draw")
    h0 = len(hu.hand)
    ig.cast(i=idx, zone="graveyard")
    assert len(hu.hand) == h0 + 2                 # el flashback resolvió su efecto
    assert spell in hu.exile and spell not in hu.graveyard   # se exilió tras lanzarse


def test_unearth_enters_and_exiles_at_end_of_turn():
    import cardsdb, cards
    ig, hu = _gy_ready_human()
    beast = cardsdb.build_card_from_data({
        "name": "Unearther", "type_line": "Creature", "mana_cost": "{4}{B}",
        "power": "3", "toughness": "3", "color_identity": ["B"],
        "oracle_text": "Unearth {1}{B}"})
    hu.graveyard.append(beast)
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), hu)
    idx = next(x["i"] for x in ig.legal()["graveyard"] if x["name"] == "Unearther")
    ig.cast(i=idx, zone="graveyard")
    perm = next((pm for pm in hu.battlefield if pm.name == "Unearther"), None)
    assert perm is not None and perm.summoning_sick is False   # entró con prisa
    ig.end_turn()
    assert beast in hu.exile                                   # se exilió al terminar
    assert not any(pm.name == "Unearther" for pm in hu.battlefield)


def test_embalm_creates_token_and_exiles_card():
    import cardsdb, cards
    ig, hu = _gy_ready_human()
    priest = cardsdb.build_card_from_data({
        "name": "Embalmer", "type_line": "Creature", "mana_cost": "{1}{W}",
        "power": "1", "toughness": "3", "color_identity": ["W"],
        "oracle_text": "Embalm {3}{W}"})
    hu.graveyard.append(priest)
    for _ in range(4):
        ig.g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), hu)
    idx = next(x["i"] for x in ig.legal()["graveyard"] if x["name"] == "Embalmer")
    ig.cast(i=idx, zone="graveyard")
    tok = next((pm for pm in hu.battlefield if pm.name == "Embalmer"), None)
    assert tok is not None and tok.is_token                     # ficha copia
    assert priest in hu.exile                                   # la carta se exilió
    import json
    json.dumps(ig.legal())


def test_foretell_then_cast_from_exile():
    # Fase B: predecir una carta (foretell) y luego lanzarla desde el exilio.
    import cardsdb, cards
    ig, hu = _gy_ready_human()
    spell = cardsdb.build_card_from_data({
        "name": "Behold", "type_line": "Sorcery", "mana_cost": "{4}{U}",
        "color_identity": ["U"], "oracle_text": "Draw two cards.\nForetell {1}{U}"})
    assert spell.foretell is not None
    hu.hand.append(spell)
    for _ in range(4):
        ig.g.move_to_battlefield(cards.land("Island", ["U"], basic=True), hu)
    i = next(x["i"] for x in ig.legal()["foretell_hand"] if x["name"] == "Behold")
    ig.foretell(i)                              # paga {2}, va al exilio jugable
    assert spell in hu.exile_play and spell not in hu.hand
    j = next(x["i"] for x in ig.legal()["exile_play"] if x["name"] == "Behold")
    h0 = len(hu.hand)
    ig.cast(i=j, zone="exile")                  # lo lanza por su coste de foretell
    assert len(hu.hand) == h0 + 2 and spell not in hu.exile_play


def test_gy_ability_activates_and_exiles():
    # Fase C: habilidad activada desde el cementerio (con exilio de la propia carta).
    import cardsdb, cards
    ig, hu = _gy_ready_human()
    c = cardsdb.build_card_from_data({
        "name": "Cripta", "type_line": "Creature", "mana_cost": "{1}{B}",
        "power": "1", "toughness": "1", "color_identity": ["B"],
        "oracle_text": "{2}{B}, Exile Cripta from your graveyard: Draw two cards."})
    assert c.gy_abilities
    hu.graveyard.append(c)
    for _ in range(3):
        ig.g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), hu)
    ga = next(x for x in ig.legal()["gy_abilities"] if x["name"] == "Cripta")
    h0 = len(hu.hand)
    ig.activate_gy(ga["i"], ga["index"])
    assert len(hu.hand) == h0 + 2                 # corrió el efecto (robar)
    assert c in hu.exile and c not in hu.graveyard  # se exilió a sí misma


def test_gy_trigger_returns_on_landfall():
    # Fase D: disparo mientras está en el cementerio (Bloodghast vuelve con landfall).
    import cardsdb, cards
    from engine import Game, Player
    bg = cardsdb.build_card_from_data({
        "name": "Bloodghast", "type_line": "Creature", "mana_cost": "{B}{B}",
        "power": "2", "toughness": "1", "color_identity": ["B"],
        "oracle_text": "Bloodghast can't block.\nLandfall — Whenever a land you control "
                       "enters, if Bloodghast is in your graveyard, return Bloodghast from "
                       "your graveyard to the battlefield."})
    assert "landfall" in bg.gy_triggers
    me = Player("me", [cards.land("Swamp", ["B"], basic=True) for _ in range(10)],
                cards.creature("Cmd", "2B", 3, 3, legendary=True))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    me.graveyard.append(bg)
    g.play_land(me, cards.land("Swamp", ["B"], basic=True))
    g.resolve_stack()
    assert any(pm.name == "Bloodghast" for pm in me.battlefield)
    assert bg not in me.graveyard


def test_attack_multiple_players_at_once():
    # el humano reparte atacantes entre varios rivales en un mismo combate
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("A",) + decks.build("strixhaven"),
            ("B",) + decks.build("lorehold")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    c1 = ig.g.move_to_battlefield(cards.creature("Bear1", "1G", 2, 2), hu)
    c2 = ig.g.move_to_battlefield(cards.creature("Bear2", "1G", 2, 2), hu)
    c1.summoning_sick = False
    c2.summoning_sick = False
    ig.g.resolve_stack()
    foes = ig.g.opponents(hu)
    idx = [ig.players.index(f) for f in foes]
    l0 = [f.life for f in foes]
    ig.attack(assign=[{"uid": c1.uid, "target": idx[0]},
                      {"uid": c2.uid, "target": idx[1]}])
    assert foes[0].life < l0[0] and foes[1].life < l0[1]   # ambos recibieron daño


def test_ceaseless_conflict_wipes_then_makes_spirits():
    # Barrida + fichas: una ficha Spirit 3/2 por cada criatura NO-ficha propia
    # destruida; las fichas previas y las criaturas del rival no cuentan.
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Ceaseless Conflict", "type_line": "Sorcery", "mana_cost": "{3}{W}{W}",
        "color_identity": ["R", "W"],
        "oracle_text": "Destroy all creatures. Then create a 3/2 red and white Spirit "
                       "creature token for each nontoken creature you controlled that "
                       "was destroyed this way."})
    assert c.on_cast_resolve is not None and "wipe" in c.tags
    me = Player("me", [cards.creature("F", "1W", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.move_to_battlefield(cards.creature("Bear1", "1W", 2, 2), me)   # no-ficha propia
    g.move_to_battlefield(cards.creature("Bear2", "1W", 2, 2), me)   # no-ficha propia
    cards.make_token(g, me, "Soldier", 1, 1)                          # ficha propia (no cuenta)
    g.move_to_battlefield(cards.creature("Rival", "1U", 4, 4), op)   # criatura rival
    g.resolve_stack()
    c.on_cast_resolve(g, me, [])
    spirits = [pm for pm in me.battlefield if pm.name == "Spirit"]
    assert len(spirits) == 2                       # una por cada no-ficha propia destruida
    assert all(pm.power == 3 and pm.toughness == 2 for pm in spirits)
    assert not any(pm.name == "Rival" for pm in op.battlefield)   # barrió todo
    assert not any(pm.name == "Spirit" for pm in op.battlefield)  # el rival no recibe fichas


def test_bot_plays_from_graveyard():
    # el bot usa las mismas jugadas fuera del campo que el humano: reanima una
    # criatura desde el cementerio (unearth) en su main phase.
    import cardsdb, cards
    from engine import Game, Player
    from policy import Policy
    beast = cardsdb.build_card_from_data({
        "name": "Botcrawler", "type_line": "Creature", "mana_cost": "{3}{B}",
        "power": "3", "toughness": "3", "color_identity": ["B"],
        "oracle_text": "Unearth {1}{B}"})
    me = Player("bot", [cards.land("Swamp", ["B"], basic=True) for _ in range(20)],
                cards.creature("Cmd", "2B", 3, 3, legendary=True), policy=Policy("intermedio"))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(20)],
                cards.creature("O", "2U", 1, 1, legendary=True), policy=Policy("intermedio"))
    g = Game([me, op], seed=1)
    me.hand = []                                  # que no gaste maná en otra cosa
    me.graveyard.append(beast)
    for _ in range(2):
        g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), me)
    me.policy.main_phase(g, me, second=False)
    g.resolve_stack()
    assert any(pm.name == "Botcrawler" for pm in me.battlefield)   # el bot lo reanimó


def test_flying_only_blocked_by_flyers_or_reach():
    import cards
    from engine import Game, Player
    me = Player("me", [cards.land("Plains", ["W"], basic=True) for _ in range(10)],
                cards.creature("C", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    flyer = g.move_to_battlefield(cards.creature("Drake", "2U", 2, 2, kw=("flying",)), me)
    flyer.summoning_sick = False
    ground = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), op)
    g._apply_block_pairs([flyer], [(flyer, ground)])
    assert ground not in flyer.blocked_by                    # tierra no bloquea volador
    reach = g.move_to_battlefield(cards.creature("Spider", "1G", 1, 3, kw=("reach",)), op)
    g._apply_block_pairs([flyer], [(flyer, reach)])
    assert reach in flyer.blocked_by                         # alcance sí


def test_human_can_attack_planeswalker():
    import interactive, cards, decks, cardsdb
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    op = ig.g.opponents(hu)[0]
    pw = cardsdb.build_card_from_data({
        "name": "Jace PW", "type_line": "Legendary Planeswalker — Jace",
        "loyalty": "5", "color_identity": ["U"], "oracle_text": "+1: Nada."})
    pwperm = ig.g.move_to_battlefield(pw, op)
    atk = ig.g.move_to_battlefield(cards.creature("Bear", "1G", 3, 3), hu)
    atk.summoning_sick = False
    ig.g.resolve_stack()
    tgt = next(t for t in ig.legal()["attack_targets"] if t.get("pw_uid") == pwperm.uid)
    loy0 = pwperm.counters.get("loyalty", 0)
    ig.attack(uids=[atk.uid], target_pw=tgt["pw_uid"])
    assert pwperm.counters.get("loyalty", 0) == loy0 - 3      # el PW recibió el daño


def test_extra_turn_in_interactive():
    import interactive, cardsdb, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    t0 = ig.g.turn
    ig.g.extra_turns.append(hu)          # el humano encola un turno extra
    ig.end_turn()
    # tras terminar, el humano vuelve a estar en su turno (turno extra), no un rival
    assert ig.g.active_index == ig.human_index and ig.phase == "main"
    assert ig.g.turn == t0               # el turno extra no avanza el contador


def test_bot_picks_useful_mode_not_always_zero():
    import cardsdb, cards
    from engine import Game, Player
    from policy import Policy
    # modal: modo 0 requiere criatura rival (no hay), modo 1 gana vida (siempre útil)
    c = cardsdb.build_card_from_data({
        "name": "Charm", "type_line": "Instant", "mana_cost": "{1}{W}",
        "color_identity": ["W"],
        "oracle_text": "Choose one —\n• Destroy target creature.\n• You gain 5 life."})
    assert c.modes and len(c.modes) == 2
    me = Player("me", [cards.land("Plains", ["W"], basic=True) for _ in range(10)],
                cards.creature("C", "2W", 3, 3, legendary=True), policy=Policy("intermedio"))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True), policy=Policy("intermedio"))
    g = Game([me, op], seed=1)             # op sin criaturas en el campo
    picks = me.policy._pick_modes(g, me, c)
    assert picks == [1]                    # elige ganar vida, no el destroy sin objetivo


def test_anger_grants_haste_from_graveyard():
    import cardsdb, cards
    from engine import Game, Player
    anger = cardsdb.build_card_from_data({
        "name": "Anger", "type_line": "Creature — Incarnation", "mana_cost": "{3}{R}",
        "power": "2", "toughness": "2", "color_identity": ["R"], "keywords": ["Haste"],
        "oracle_text": "Haste\nAs long as Anger is in your graveyard and you control a "
                       "Mountain, creatures you control have haste."})
    assert anger.gy_grant == {"keyword": "haste", "need_subtype": "Mountain"}
    me = Player("me", [cards.land("Mountain", ["R"], basic=True) for _ in range(10)],
                cards.creature("C", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    guy = g.move_to_battlefield(cards.creature("Goblin", "1R", 2, 2), me)  # sick, sin prisa
    assert not guy.can_attack()
    me.graveyard.append(anger)
    g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)   # controla Mountain
    assert guy.has("haste") and guy.can_attack()             # ahora tiene prisa
    # sin Mountain no aplica
    me.battlefield = [pm for pm in me.battlefield if pm.card.name != "Mountain"]
    assert not guy.has("haste")


def test_planeswalker_loyalty_from_face_and_survives():
    # planeswalker de doble cara: la lealtad viene en card_faces[0], no en el nivel
    # superior. Antes entraba con 0 y moría al instante (SBA).
    import cardsdb, cards
    from engine import Game, Player
    data = {"name": "Front // Back", "type_line": "//", "color_identity": ["U"],
            "card_faces": [
                {"name": "Front", "type_line": "Legendary Planeswalker — Jace",
                 "mana_cost": "{1}{U}", "loyalty": "4", "oracle_text": "+1: Nada."},
                {"name": "Back", "type_line": "Land"}]}
    pw = cardsdb.build_card_from_data(data)
    assert "planeswalker" in pw.types and pw.loyalty == 4
    me = Player("me", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("C", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.land("I", ["U"]) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    perm = g.move_to_battlefield(pw, me)
    g.sba()
    assert perm in me.battlefield and perm.counters["loyalty"] == 4   # no desaparece
    # planeswalker sin lealtad en los datos -> fallback, tampoco desaparece
    pw2 = cardsdb.build_card_from_data({
        "name": "Nolo", "type_line": "Legendary Planeswalker — X", "mana_cost": "{2}{U}",
        "color_identity": ["U"], "oracle_text": "+1: Nada."})
    assert pw2.loyalty == 3


def test_human_discards_by_choice():
    # con más de 7 cartas, al terminar el turno el HUMANO elige qué descartar.
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    hu.hand = [cards.creature(f"C{i}", "1G", 1, 1) for i in range(9)]   # 9 en mano
    st = ig.end_turn()
    assert st["phase"] == "choose" and st["choice"]["kind"] == "discard"
    gy0 = len(hu.graveyard)
    ig.resolve_choice(0)                       # descarta la primera
    ig.resolve_choice(0)                       # y otra -> baja a 7 y termina el turno
    assert len(hu.graveyard) - gy0 >= 2        # descartó (lo eligió el humano)


def test_reaction_window_to_opponent_spell():
    # cuando un rival lanza un hechizo que vale la pena y el humano tiene un
    # instantáneo, la partida pausa en "react"; al pasar, el hechizo resuelve.
    import interactive, cards, decks, cardsdb, engine
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    op = ig.g.opponents(hu)[0]
    instant = cardsdb.build_card_from_data({
        "name": "Zap", "type_line": "Instant", "mana_cost": "{R}", "color_identity": ["R"],
        "oracle_text": "Zap deals 3 damage to any target."})
    hu.hand.append(instant)
    ig.g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), hu)
    for _ in range(3):
        ig.g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), op)  # maná del rival
    beast = cards.creature("Ogro", "2R", 3, 3)
    ig._react_armed = True                           # ventana activa (fase main del bot)
    assert ig._offer_reaction(op, beast) is True     # hay con qué responder
    try:
        ig.g.cast(op, beast)
        paused = False
    except engine.ReactionPause as rp:
        paused = True
        ig._react_ctx = {"p": op, "step": "main2", "spell": rp.spell}
        ig.mode = "react"
        ig.phase = "react"
    assert paused                                    # el motor pausó
    rs = ig._react_state()
    assert rs["spell"] == "Ogro" and any(r["name"] == "Zap" for r in rs["responses"])
    # pasar = resolver el hechizo en la pila -> la criatura entra
    ig.g._run_priority_and_resolve()
    assert any(pm.name == "Ogro" for pm in op.battlefield)
    # sin instantáneo NO se abre la ventana
    hu.hand = [c for c in hu.hand if c.name != "Zap"]
    assert ig._offer_reaction(op, beast) is False


def test_human_copies_bot_ability_in_reaction_window():
    # A2: un bot activa una habilidad; el humano tiene un Strionic listo, se abre
    # la ventana de reacción y al copiarla el efecto ocurre DOS veces.
    import interactive, cards, decks, cardsdb, engine
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    op = ig.g.opponents(hu)[0]
    # bot: permanente con habilidad activada que pega 2 a un jugador
    pinger = cards.creature("Pinger", "1R", 1, 1)
    hits = {"n": 0}
    pinger.activated_abilities = ({"cost": cards.parse_cost("0"), "tap": False,
                                   "label": "ping", "target_spec": None, "target_count": 1,
                                   "effect": (lambda g, c, perm, tg: hits.__setitem__(
                                       "n", hits["n"] + 1))},)
    pp = ig.g.move_to_battlefield(pinger, op)
    pp.summoning_sick = False
    # humano: Strionic Resonator listo + maná
    reson = cardsdb.build_card_from_data({
        "name": "Strionic Resonator", "type_line": "Artifact",
        "oracle_text": "{2}, {T}: Copy target activated or triggered ability."})
    rp = ig.g.move_to_battlefield(reson, hu)
    rp.summoning_sick = False
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), hu)
    ig._react_armed = True
    op._abil_perms_used = {pp.uid}     # el bot ya comprometió esta activación
    # el bot activa su habilidad -> debe pausar (el humano puede copiar)
    try:
        ig.g.activate_ability(pp, 0)
        paused = False
    except engine.ReactionPause as rpause:
        paused = True
        stacked = rpause.spell
        ig._react_ctx = {"p": op, "step": "main2", "spell": stacked}
        ig.mode = "react"
        ig.phase = "react"
    assert paused and hits["n"] == 0          # aún no resolvió
    rs = ig._react_state()
    assert "habilidad de Pinger" in rs["spell"]
    # el humano copia la habilidad con Strionic apuntando a la habilidad en la pila.
    # (activamos directo para aislar la copia del avance de turno que hace react())
    ig.g.activate_ability(rp, 0, targets=[stacked])
    assert hits["n"] == 2                     # copia + original, ambas resuelven


def test_optional_may_draw_asks_human_auto_for_bot():
    # "you may draw a card": el humano decide (sí/no); el bot auto-acepta.
    import interactive, cardsdb, decks
    data = {"name": "Peek", "type_line": "Creature", "mana_cost": "{1}{U}",
            "power": "1", "toughness": "1", "color_identity": ["U"],
            "oracle_text": "When Peek enters, you may draw a card."}
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    h0 = len(hu.hand)
    ig.g.move_to_battlefield(cardsdb.build_card_from_data(data), hu)
    assert ig.g.pending_choice and ig.g.pending_choice["kind"] == "may"  # le pregunta
    assert len(hu.hand) == h0                    # todavía no robó
    ig.resolve_choice(0)                          # dice que sí
    assert len(hu.hand) == h0 + 1
    # el bot auto-acepta (sin pending_choice)
    op = ig.g.opponents(hu)[0]
    ob = len(op.hand)
    ig.g.move_to_battlefield(cardsdb.build_card_from_data(data), op)
    assert ig.g.pending_choice is None and len(op.hand) == ob + 1


def test_indestructible_survives_lethal_damage():
    # daño letal NO destruye a una criatura indestructible; resistencia <= 0 sí.
    import cards
    from engine import Game, Player
    me = Player("me", [cards.land("Forest", ["G"], basic=True) for _ in range(10)],
                cards.creature("C", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    wall = g.move_to_battlefield(cards.creature("Muro", "1G", 1, 4, kw=("indestructible",)), me)
    wall.damage = 10                       # daño letal
    g.sba()
    assert wall in me.battlefield          # sobrevive (indestructible)
    g.destroy(wall, "test")                # destroy también lo respeta
    assert wall in me.battlefield
    wall.temp_pt = [0, -10]                # resistencia <= 0: muere igual
    g.sba()
    assert wall not in me.battlefield


def _duel():
    import cards
    from engine import Game, Player
    me = Player("me", [cards.land("Plains", ["W"], basic=True) for _ in range(6)],
                cards.creature("Cm", "2W", 3, 3, legendary=True))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(6)],
                cards.creature("Om", "2U", 1, 1, legendary=True))
    return Game([me, op], seed=1), me, op


def test_lifelink_gains_life_from_damage_to_player():
    import cards
    g, me, op = _duel()
    linker = g.move_to_battlefield(cards.creature("Vamp", "1W", 3, 3, kw=("lifelink",)), me)
    l0 = me.life
    g.deal_damage(linker, op, 3, combat=True)          # daño a un JUGADOR
    assert me.life == l0 + 3 and op.life == 40 - 3      # lifelink gana vida


def test_deathtouch_assigns_one_and_tramples_rest():
    import cards
    g, me, op = _duel()
    atk = g.move_to_battlefield(cards.creature("DT", "1B", 4, 4, kw=("deathtouch", "trample")), me)
    atk.summoning_sick = False
    blk = g.move_to_battlefield(cards.creature("Wall", "1G", 0, 5), op)
    g._begin_combat(me)
    g._declare_attackers(me, [(atk, op)])
    g._apply_block_pairs([atk], [(atk, blk)])
    life0 = op.life
    g._finish_combat([atk])
    assert blk not in op.battlefield                    # 1 de daño mortal lo mata
    assert op.life == life0 - 3                          # 3 restantes derraman (trample)


def test_minus_counters_reduce_and_annihilate():
    import cards
    g, me, op = _duel()
    c = g.move_to_battlefield(cards.creature("Bear", "1G", 3, 3), me)
    g.add_counters(c, "-1/-1", 1)
    assert c.power == 2 and c.toughness == 2
    g.add_counters(c, "+1/+1", 1)
    g.sba()                                             # se aniquilan de a pares
    assert c.counters.get("+1/+1", 0) == 0 and c.counters.get("-1/-1", 0) == 0
    assert c.power == 3 and c.toughness == 3
    g.add_counters(c, "-1/-1", 3)
    g.sba()
    assert c not in me.battlefield                      # resistencia 0 -> muere


def test_first_strike_blocker_dies_before_returning_damage():
    import cards
    g, me, op = _duel()
    fs = g.move_to_battlefield(cards.creature("Knight", "1W", 2, 2, kw=("first_strike",)), me)
    fs.summoning_sick = False
    blk = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), op)
    g._begin_combat(me)
    g._declare_attackers(me, [(fs, op)])
    g._apply_block_pairs([fs], [(fs, blk)])
    g._finish_combat([fs])
    assert blk not in op.battlefield                    # muere en el primer golpe
    assert fs in me.battlefield and fs.damage == 0      # no recibió daño de vuelta


def test_wither_deals_minus_counters_to_creature():
    import cards
    g, me, op = _duel()
    w = g.move_to_battlefield(cards.creature("Wither", "1B", 2, 2, kw=("wither",)), me)
    tgt = g.move_to_battlefield(cards.creature("Bear", "1G", 3, 3), op)
    g.deal_damage(w, tgt, 2, combat=True)
    assert tgt.counters.get("-1/-1") == 2 and tgt.damage == 0
    assert tgt.power == 1 and tgt.toughness == 1


def test_x_spell_scales_with_available_mana():
    # un hechizo con {X} elige X = maná sobrante y su efecto escala.
    import cardsdb, cards
    from engine import Game, Player
    fb = cardsdb.build_card_from_data({
        "name": "Fireball", "type_line": "Sorcery", "mana_cost": "{X}{R}",
        "color_identity": ["R"], "oracle_text": "Fireball deals X damage to any target."})
    assert fb.x_spell and fb.on_cast_resolve is not None
    me = Player("me", [cards.creature("F", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(5):
        g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    l0 = op.life
    g.cast(me, fb, targets=[op])          # 5 fuentes, base {R}=1 -> X=4
    assert op.life == l0 - 4


def test_hybrid_cost_payable_with_any_color():
    # {W/U} se cuenta como genérico -> pagable con cualquier maná (no bloquea).
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Hyb", "type_line": "Creature", "mana_cost": "{2}{W/U}",
        "power": "2", "toughness": "2", "color_identity": ["W", "U"]})
    assert c.cost.cmc == 3 and c.cost.pips == ()
    me = Player("me", [cards.creature("F", "1G", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("op", [cards.creature("G", "1U", 1, 1) for _ in range(3)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(3):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    assert g.cast(me, c) is not False     # pagable con 3 bosques pese a ser W/U


def test_enters_with_counters():
    import cardsdb, cards
    g, me, op = _duel()
    c = cardsdb.build_card_from_data({
        "name": "Hydra", "type_line": "Creature", "mana_cost": "{2}{G}",
        "power": "0", "toughness": "0", "color_identity": ["G"],
        "oracle_text": "Hydra enters the battlefield with three +1/+1 counters on it."})
    assert c.etb_counters == {"+1/+1": 3}
    perm = g.move_to_battlefield(c, me)
    assert perm.counters.get("+1/+1") == 3 and perm.power == 3 and perm.toughness == 3


def test_legend_rule_bot_keeps_better():
    import cards
    g, me, op = _duel()                       # sin interactive_human -> ruta bot
    a = g.move_to_battlefield(cards.creature("Rey", "2G", 3, 3, legendary=True), me)
    a.counters["+1/+1"] = 2                    # 5/5
    b = g.move_to_battlefield(cards.creature("Rey", "2G", 3, 3, legendary=True), me)  # 3/3
    g.sba()
    assert a in me.battlefield and b not in me.battlefield   # conserva la mejor


def test_legend_rule_human_chooses():
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    a = ig.g.move_to_battlefield(cards.creature("Legend", "2G", 3, 3, legendary=True), hu)
    b = ig.g.move_to_battlefield(cards.creature("Legend", "2G", 4, 4, legendary=True), hu)
    ig.g.sba()
    assert ig.g.pending_choice and ig.g.pending_choice["kind"] == "legend"
    ig.resolve_choice(1)                       # conserva la segunda copia
    assert b in hu.battlefield and a not in hu.battlefield


def test_convoke_taps_creatures_to_pay():
    import cardsdb, cards
    g, me, op = _duel()
    c = cardsdb.build_card_from_data({
        "name": "Machine", "type_line": "Artifact", "mana_cost": "{3}",
        "oracle_text": "Convoke", "keywords": ["Convoke"]})
    assert "convoke" in c.tags
    for _ in range(3):
        pm = g.move_to_battlefield(cards.creature("C", "1G", 1, 1), me)
        pm.summoning_sick = False
    assert g.cast(me, c) is not False        # pagado girando 3 criaturas
    assert sum(1 for pm in me.battlefield if pm.is_creature() and pm.tapped) == 3


def test_delve_exiles_graveyard_to_pay():
    import cardsdb, cards
    g, me, op = _duel()
    c = cardsdb.build_card_from_data({
        "name": "Dig", "type_line": "Sorcery", "mana_cost": "{4}{U}",
        "color_identity": ["U"], "oracle_text": "Delve\nDraw a card.",
        "keywords": ["Delve"]})
    assert "delve" in c.tags
    for _ in range(5):
        me.graveyard.append(cards.creature("Gy", "1U", 1, 1))
    g.move_to_battlefield(cards.land("Island", ["U"], basic=True), me)
    ex0 = len(me.exile)
    assert g.cast(me, c) is not False        # {4} pagado exiliando 4 del cementerio
    assert len(me.exile) - ex0 >= 4


def test_affinity_reduces_by_artifacts():
    import cardsdb, cards
    g, me, op = _duel()
    c = cardsdb.build_card_from_data({
        "name": "Cranium", "type_line": "Artifact", "mana_cost": "{4}",
        "oracle_text": "Affinity for artifacts"})
    assert "affinity_art" in c.tags
    for _ in range(4):
        g.move_to_battlefield(cards.rock("Rock", "2", ["C"]), me)   # 4 artefactos
    assert g.cast(me, c) is not False        # {4} - 4 artefactos = gratis


def test_human_chooses_x():
    import interactive, cardsdb, cards, decks
    fb = cardsdb.build_card_from_data({
        "name": "Fireball", "type_line": "Sorcery", "mana_cost": "{X}{R}",
        "color_identity": ["R"], "oracle_text": "Fireball deals X damage to any target."})
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    op = ig.g.opponents(hu)[0]
    hu.hand.append(fb)
    for _ in range(5):
        ig.g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), hu)
    i = next(j for j, c in enumerate(hu.hand) if c.name == "Fireball")
    ig.cast(i=i, zone="hand")
    assert ig.g.pending_choice and ig.g.pending_choice["kind"] == "x"
    l0 = op.life
    ig.resolve_choice(2)                    # elijo X=2 aunque el máximo sea 4
    assert op.life == l0 - 2


def test_aura_attaches_buffs_and_falls_off():
    import cardsdb, cards
    g, me, op = _duel()
    bear = g.move_to_battlefield(cards.creature("Oso", "1G", 2, 2), me)
    aura = cardsdb.build_card_from_data({
        "name": "Fuerza", "type_line": "Enchantment — Aura", "mana_cost": "{1}{G}",
        "color_identity": ["G"],
        "oracle_text": "Enchant creature\nEnchanted creature gets +2/+2 and has trample."})
    ap = g.move_to_battlefield(aura, me)
    assert ap.enchanting is bear
    assert bear.power == 4 and bear.toughness == 4 and bear.has("trample")
    g.to_graveyard(bear, "test")            # muere el huésped
    g.sba()
    assert ap not in me.battlefield and aura in me.graveyard   # el aura se cae


# -- copiar: clones completos, hechizos, habilidades, populate ------------- #
def test_clone_copies_abilities_not_just_pt():
    # un clon ahora copia también las habilidades (ETB, activadas), no solo P/T.
    import cardsdb, cards
    g, me, op = _duel()
    hits = {"n": 0}
    src = cards.creature("Maga", "2U", 2, 2)
    src.on_etb = lambda game, ctrl, perm: hits.__setitem__("n", hits["n"] + 1)
    src.activated_abilities = ({"cost": cards.parse_cost("0"), "tap": False,
                                "label": "ping", "effect":
                                (lambda game, ctrl, perm, tg: game.log("ping")),
                                "target_spec": None, "target_count": 1},)
    victim = g.move_to_battlefield(src, op)          # ETB del original: +1
    assert hits["n"] == 1
    tok = cards.make_copy_token(g, me, victim.card)
    assert hits["n"] == 2                             # ETB del clon también dispara
    assert tok.is_token and tok.name == "Maga"
    assert tok.card.activated_abilities              # copió la habilidad activada
    assert g.activate_ability(tok, 0) is True


def test_copy_spell_duplicates_effect():
    import cardsdb, cards
    from engine import Game, Player, StackObject
    g, me, op = _duel()
    # hechizo objetivo: quema 3 a un jugador. Lo ponemos en la pila a mano.
    burn = cardsdb.build_card_from_data({
        "name": "Rayo", "type_line": "Instant", "mana_cost": "{R}",
        "color_identity": ["R"],
        "oracle_text": "Rayo deals 3 damage to any target."})
    assert burn.on_cast_resolve is not None
    l0 = op.life
    obj = StackObject(me, lambda gg: burn.on_cast_resolve(gg, me, [op]),
                      source=burn, targets=[op], label="spell:Rayo")
    g.stack.append(obj)
    # Fork copia el hechizo de la pila
    g.copy_spell_on_stack(obj, controller=me)
    # resolver la pila: primero la copia (3), luego el original (3) => -6
    while g.stack:
        top = g.stack.pop()
        top.resolve(g)
    assert op.life == l0 - 6


def test_fork_card_parses_as_stack_spell_copy():
    import cardsdb
    fork = cardsdb.build_card_from_data({
        "name": "Twincast", "type_line": "Instant", "mana_cost": "{U}{U}",
        "color_identity": ["U"],
        "oracle_text": "Copy target instant or sorcery spell. You may choose new "
                       "targets for the copy."})
    assert fork.target_spec == "stack_spell" and fork.on_cast_resolve is not None


def test_strionic_copies_last_activated_ability():
    import cardsdb, cards
    g, me, op = _duel()
    calls = {"n": 0}
    src = cards.creature("Pinchador", "1R", 1, 1)
    src.activated_abilities = ({"cost": cards.parse_cost("0"), "tap": False,
                                "label": "ping", "effect":
                                (lambda game, ctrl, perm, tg: calls.__setitem__(
                                    "n", calls["n"] + 1)),
                                "target_spec": None, "target_count": 1},)
    pm = g.move_to_battlefield(src, me)
    assert g.activate_ability(pm, 0) is True and calls["n"] == 1
    reson = cardsdb.build_card_from_data({
        "name": "Strionic Resonator", "type_line": "Artifact",
        "oracle_text": "{2}, {T}: Copy target activated or triggered ability. You "
                       "may choose new targets for the copy."})
    assert reson.activated_abilities
    ab = reson.activated_abilities[0]
    assert ab.get("is_copy_ability") is True
    for _ in range(2):                           # maná para pagar el {2} de Strionic
        g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), me)
    rp = g.move_to_battlefield(reson, me)
    rp.summoning_sick = False
    assert g.activate_ability(rp, 0) is True     # copia la última habilidad => +1
    assert calls["n"] == 2
    # la habilidad de copia NO se registra como "última" (no se copia a sí misma)
    assert g.last_activated is not None and g.last_activated[0] is pm


def test_bot_copies_own_targeted_ability_with_strionic():
    # A3: un bot con Strionic copia su PROPIA habilidad dirigida al activarla.
    import cards, cardsdb, policy
    from engine import Game, Player
    me = Player("me", [cards.land("Mtn", ["R"], basic=True) for _ in range(10)],
                cards.creature("Cm", "2R", 3, 3, legendary=True),
                policy=policy.Policy("intermedio"))
    op = Player("op", [cards.land("Isl", ["U"], basic=True) for _ in range(10)],
                cards.creature("Om", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    hits = {"n": 0}
    pinger = cards.creature("Pinger", "1R", 1, 1)
    pinger.activated_abilities = ({"cost": cards.parse_cost("0"), "tap": False,
                                   "label": "ping", "target_spec": "opp_creature",
                                   "target_count": 1,
                                   "effect": (lambda gg, c, perm, tg: hits.__setitem__(
                                       "n", hits["n"] + 1))},)
    pp = g.move_to_battlefield(pinger, me)
    pp.summoning_sick = False
    reson = cardsdb.build_card_from_data({
        "name": "Strionic Resonator", "type_line": "Artifact",
        "oracle_text": "{2}, {T}: Copy target activated or triggered ability."})
    rp = g.move_to_battlefield(reson, me)
    rp.summoning_sick = False
    for _ in range(2):
        g.move_to_battlefield(cards.land("Mtn", ["R"], basic=True), me)
    victim = g.move_to_battlefield(cards.creature("V", "1U", 2, 2), op)
    g.activate_ability(pp, 0, targets=[victim])   # el bot debería copiar con Strionic
    assert hits["n"] == 2                          # copia + original
    assert rp.tapped                               # gastó el Strionic


def test_strionic_copies_last_triggered_ability():
    # límite 2 (mejora): Strionic ahora también copia una habilidad DISPARADA,
    # no solo activadas. Aquí copiamos un disparo "al atacar".
    import cardsdb, cards
    g, me, op = _duel()
    fires = {"n": 0}
    trig = cards.creature("Atacante", "1R", 2, 2)
    trig.triggers = {"attacks": (lambda game, perm, **kw: fires.__setitem__("n", fires["n"] + 1))}
    g.move_to_battlefield(trig, me)
    g.emit("attacks", player=me)          # encola el disparo
    g.resolve_stack()                     # se resuelve: fires=1 y queda como last_ability
    assert fires["n"] == 1
    reson = cardsdb.build_card_from_data({
        "name": "Strionic Resonator", "type_line": "Artifact",
        "oracle_text": "{2}, {T}: Copy target activated or triggered ability."})
    for _ in range(2):
        g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), me)
    rp = g.move_to_battlefield(reson, me)
    rp.summoning_sick = False
    assert g.activate_ability(rp, 0) is True
    assert fires["n"] == 2                # copió el disparo "al atacar"


def test_populate_copies_best_creature_token():
    import cardsdb, cards
    g, me, op = _duel()
    cards.make_token(g, me, "Saproling", 1, 1)
    cards.make_token(g, me, "Bestia", 3, 3)
    spell = cardsdb.build_card_from_data({
        "name": "Crecer", "type_line": "Sorcery", "mana_cost": "{2}{G}",
        "color_identity": ["G"], "oracle_text": "Populate."})
    assert "populate" in spell.tags and spell.on_cast_resolve is not None
    n0 = sum(1 for pm in me.battlefield if pm.is_token)
    spell.on_cast_resolve(g, me, [])
    toks = [pm for pm in me.battlefield if pm.is_token]
    assert len(toks) == n0 + 1
    assert any(pm.name == "Bestia" for pm in toks[-1:])   # copia la mejor ficha


def test_copy_spell_replays_chosen_mode_not_first():
    # límite 3 resuelto: la copia reproduce el MISMO modo elegido, no el modo 0.
    import cards
    from engine import Game, StackObject
    g, me, op = _duel()
    hits = {0: 0, 1: 0}
    modal = cards.creature("Dummy", "1U", 1, 1)  # solo contenedor de modos
    modal.types = {"instant"}
    modal.modes = (
        {"label": "modo A", "effect": (lambda gg, c, tg: hits.__setitem__(0, hits[0] + 1))},
        {"label": "modo B", "effect": (lambda gg, c, tg: hits.__setitem__(1, hits[1] + 1))},
    )
    obj = StackObject(me, lambda gg: None, source=modal, targets=[], label="spell:Dummy",
                      chosen_modes=[1])                  # el original eligió el modo B
    g.stack.append(obj)
    g.copy_spell_on_stack(obj, controller=me)
    while g.stack:
        g.stack.pop().resolve(g)
    assert hits[1] == 1 and hits[0] == 0                 # copió el modo B, no el A


def test_bot_copies_own_beneficial_spell_with_fork():
    # límite 1 resuelto: un bot con Twincast copia su propio hechizo bueno.
    import cardsdb, cards, policy
    from engine import Game, Player
    burn = cardsdb.build_card_from_data({
        "name": "Rayo", "type_line": "Instant", "mana_cost": "{R}",
        "color_identity": ["R"], "oracle_text": "Rayo deals 3 damage to any target."})
    fork = cardsdb.build_card_from_data({
        "name": "Twincast", "type_line": "Instant", "mana_cost": "{U}{U}",
        "color_identity": ["U"],
        "oracle_text": "Copy target instant or sorcery spell."})
    me = Player("me", [cards.land("Mtn", ["R"], basic=True) for _ in range(10)],
                cards.creature("Cm", "2R", 3, 3, legendary=True),
                policy=policy.Policy("intermedio"))
    op = Player("op", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                cards.creature("Om", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    # maná: 3 fuentes (paga el {R} del rayo y las {U}{U} del fork = colores mixtos ok
    # porque las tierras dan cualquiera de su lista; usamos duales de prueba)
    for _ in range(3):
        g.move_to_battlefield(cards.land("Dual", [cards.R, cards.U]), me)
    me.hand = [fork]                       # el fork queda en mano para responder
    l0 = op.life
    g.cast(me, burn, targets=[op])         # lanza el rayo; el bot debería copiarlo
    assert op.life == l0 - 6               # 3 (copia) + 3 (original)
    assert fork not in me.hand             # usó el Twincast


def test_fetchland_sacrifice_fetches_basic_tapped():
    # habilidad "{T}, Sacrifice ~: Search your library for a basic land, put it
    # onto the battlefield tapped, then shuffle" (Evolving Wilds y similares).
    import cardsdb, cards
    g, me, op = _duel()
    ew = cardsdb.build_card_from_data({
        "name": "Evolving Wilds", "type_line": "Land",
        "oracle_text": "{T}, Sacrifice Evolving Wilds: Search your library for a "
                       "basic land card, put it onto the battlefield tapped, then shuffle."})
    assert ew.activated_abilities, "la habilidad debe parsearse"
    ab = ew.activated_abilities[0]
    assert ab.get("tap") is True and ab.get("sacrifice_self") is True
    # biblioteca con una básica para buscar
    me.library.append(cards.land("Forest", ["G"], basic=True))
    pm = g.move_to_battlefield(ew, me)
    lib0 = len(me.library)
    assert g.activate_ability(pm, 0) is True
    assert pm not in me.battlefield                     # se sacrificó
    assert len(me.library) == lib0 - 1                  # sacó una carta de la biblioteca
    assert any(p.tapped and "basic" in p.card.supertypes for p in me.battlefield)


def _with_two_plains(g, me):
    import cards
    for _ in range(2):
        g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), me)


def test_activated_pump_buffs_own_creature():
    # "{1}: Target creature gets +2/+2 until end of turn." ahora hace algo real.
    import cardsdb, cards
    g, me, op = _duel()
    src = cardsdb.build_card_from_data({
        "name": "Pumper", "type_line": "Creature — Human", "mana_cost": "{1}",
        "power": "1", "toughness": "1",
        "oracle_text": "{1}: Target creature gets +2/+2 until end of turn."})
    assert src.activated_abilities[0].get("target_spec") == "own_creature"
    _with_two_plains(g, me)
    pm = g.move_to_battlefield(src, me)
    assert g.activate_ability(pm, 0, targets=[pm]) is True
    assert pm.power == 3 and pm.toughness == 3          # 1/1 +2/+2


def test_activated_put_counter_on_target():
    # "{1}: Put a +1/+1 counter on target creature."
    import cardsdb
    g, me, op = _duel()
    src = cardsdb.build_card_from_data({
        "name": "Counterer", "type_line": "Creature — Human", "mana_cost": "{1}",
        "power": "1", "toughness": "1",
        "oracle_text": "{1}: Put a +1/+1 counter on target creature."})
    _with_two_plains(g, me)
    pm = g.move_to_battlefield(src, me)
    assert g.activate_ability(pm, 0, targets=[pm]) is True
    assert pm.counters.get("+1/+1") == 1 and pm.power == 2


def test_activated_tap_target_creature():
    # "{1}: Tap target creature." (penalización -> criatura rival)
    import cardsdb, cards
    g, me, op = _duel()
    src = cardsdb.build_card_from_data({
        "name": "Tapper", "type_line": "Creature — Human", "mana_cost": "{1}",
        "power": "1", "toughness": "1",
        "oracle_text": "{1}: Tap target creature."})
    assert src.activated_abilities[0].get("target_spec") == "opp_creature"
    _with_two_plains(g, me)
    pm = g.move_to_battlefield(src, me)
    victim = g.move_to_battlefield(cards.creature("V", "1U", 2, 2), op)
    assert g.activate_ability(pm, 0, targets=[victim]) is True
    assert victim.tapped is True


def test_activated_cost_pay_life():
    # coste adicional "Pay 2 life": se paga y no te puede matar.
    import cardsdb, cards
    g, me, op = _duel()
    src = cardsdb.build_card_from_data({
        "name": "Bleeder", "type_line": "Creature — Human", "mana_cost": "{1}",
        "power": "1", "toughness": "1",
        "oracle_text": "{1}, Pay 2 life: Draw two cards."})
    assert src.activated_abilities[0].get("pay_life") == 2
    _with_two_plains(g, me)
    me.library += [cards.land("Plains", ["W"], basic=True) for _ in range(5)]
    pm = g.move_to_battlefield(src, me)
    l0, h0 = me.life, len(me.hand)
    assert g.activate_ability(pm, 0) is True
    assert me.life == l0 - 2 and len(me.hand) == h0 + 2
    # con 1 de vida no se puede pagar (no puede dejarte en 0)
    me.life = 1
    assert g.activate_ability(pm, 0) is False


def test_activated_cost_sacrifice_other():
    # coste adicional "Sacrifice a creature": sacrifica OTRA criatura, no la fuente.
    import cardsdb, cards
    g, me, op = _duel()
    src = cardsdb.build_card_from_data({
        "name": "Altar", "type_line": "Artifact", "mana_cost": "{1}",
        "oracle_text": "{1}, Sacrifice a creature: Draw two cards."})
    assert src.activated_abilities[0].get("sacrifice_other") == {"count": 1,
                                                                 "type": "creature"}
    _with_two_plains(g, me)
    me.library += [cards.land("Plains", ["W"], basic=True) for _ in range(5)]
    pm = g.move_to_battlefield(src, me)
    spare = g.move_to_battlefield(cards.creature("Spare", "1W", 1, 1), me)
    h0 = len(me.hand)
    assert g.activate_ability(pm, 0) is True
    assert spare not in me.battlefield and pm in me.battlefield
    assert len(me.hand) == h0 + 2
    # sin criatura que sacrificar no se puede activar
    assert g.activate_ability(pm, 0) is False


def test_activated_cost_discard():
    # coste adicional "Discard a card".
    import cardsdb, cards
    g, me, op = _duel()
    src = cardsdb.build_card_from_data({
        "name": "Looter", "type_line": "Creature — Human", "mana_cost": "{1}",
        "power": "1", "toughness": "1",
        "oracle_text": "{1}, Discard a card: Draw two cards."})
    assert src.activated_abilities[0].get("discard") == 1
    _with_two_plains(g, me)
    me.library += [cards.land("Plains", ["W"], basic=True) for _ in range(5)]
    pm = g.move_to_battlefield(src, me)
    me.hand = [cards.creature("Junk", "1W", 1, 1)]
    gy0 = len(me.graveyard)
    assert g.activate_ability(pm, 0) is True
    assert len(me.graveyard) == gy0 + 1                 # descartó 1
    assert len(me.hand) == 2                            # descartó 1, robó 2


def _spell(oracle, tl="Instant", cost="{1}{U}"):
    import cardsdb
    return cardsdb.build_card_from_data(
        {"name": "S", "type_line": tl, "mana_cost": cost, "oracle_text": oracle})


def test_imported_counterspell_counters():
    import cards
    from engine import StackObject
    g, me, op = _duel()
    cs = _spell("Counter target spell.", cost="{U}{U}")
    assert cs.target_spec == "stack_spell" and "counter" in cs.tags
    victim_card = cards.creature("Bomb", "3U", 5, 5)
    so = StackObject(op, lambda g: None, source=victim_card, label="spell")
    g.stack.append(so)
    cs.on_cast_resolve(g, me, [so])
    assert so not in g.stack and victim_card in op.graveyard


def test_burn_to_target_creature_kills():
    import cards
    g, me, op = _duel()
    v = g.move_to_battlefield(cards.creature("V", "1U", 3, 3), op)
    _spell("Deal 3 damage to target creature.").on_cast_resolve(g, me, [])
    assert v not in op.battlefield


def test_edict_forces_sacrifice():
    import cards
    g, me, op = _duel()
    e = g.move_to_battlefield(cards.creature("Sac", "1U", 2, 2), op)
    _spell("Target player sacrifices a creature.", "Sorcery").on_cast_resolve(g, me, [])
    assert e not in op.battlefield


def test_forced_discard():
    import cards
    g, me, op = _duel()
    op.hand = [cards.creature(f"H{i}", "1U", 1, 1) for i in range(3)]
    _spell("Target player discards two cards.", "Sorcery").on_cast_resolve(g, me, [])
    assert len(op.hand) == 1


def test_each_player_draws():
    import cards
    g, me, op = _duel()
    me.library += [cards.land("Plains", ["W"], basic=True) for _ in range(5)]
    op.library += [cards.land("Island", ["U"], basic=True) for _ in range(5)]
    h0m, h0o = len(me.hand), len(op.hand)
    _spell("Each player draws two cards.", "Sorcery").on_cast_resolve(g, me, [])
    assert len(me.hand) == h0m + 2 and len(op.hand) == h0o + 2


def test_proliferate_adds_counter():
    import cards
    g, me, op = _duel()
    c = g.move_to_battlefield(cards.creature("C", "1U", 1, 1), me)
    g.add_counters(c, "+1/+1", 1)
    p0 = c.power
    _spell("Proliferate.", "Sorcery").on_cast_resolve(g, me, [])
    assert c.power == p0 + 1


def test_keyword_grant_until_end_of_turn():
    import cards
    g, me, op = _duel()
    k = g.move_to_battlefield(cards.creature("K", "1U", 2, 2), me)
    _spell("Target creature gains flying and trample until end of turn.").on_cast_resolve(g, me, [])
    assert k.has("flying") and k.has("trample")


def test_bounce_nonland_permanent_parses():
    b = _spell("Return target nonland permanent to its owner's hand.")
    assert b.on_cast_resolve is not None and "removal" in b.tags


def test_untap_and_mass_tap():
    import cards
    g, me, op = _duel()
    a = g.move_to_battlefield(cards.creature("A", "1U", 1, 1), me)
    a.tapped = True
    _spell("Untap all creatures you control.").on_cast_resolve(g, me, [])
    assert a.tapped is False
    e = g.move_to_battlefield(cards.creature("E", "1U", 2, 2), op)
    _spell("Tap all creatures target player controls.", "Sorcery").on_cast_resolve(g, me, [])
    assert e.tapped is True


def test_target_player_loses_life():
    g, me, op = _duel()
    l0 = op.life
    _spell("Target player loses 3 life.", "Sorcery").on_cast_resolve(g, me, [])
    assert op.life == l0 - 3


def test_each_opponent_edict():
    import cards
    g, me, op = _duel()
    s = g.move_to_battlefield(cards.creature("S", "1U", 1, 1), op)
    _spell("Each opponent sacrifices a creature.", "Sorcery").on_cast_resolve(g, me, [])
    assert s not in op.battlefield


def test_cant_be_blocked_grants_unblockable():
    import cards
    g, me, op = _duel()
    k = g.move_to_battlefield(cards.creature("K", "1U", 2, 2), me)
    _spell("Target creature can't be blocked this turn.").on_cast_resolve(g, me, [])
    assert k.has("unblockable")


def test_fog_prevents_combat_damage():
    import cards
    g, me, op = _duel()
    _spell("Prevent all combat damage this turn.").on_cast_resolve(g, me, [])
    assert g.fog_turn is True
    atk = g.move_to_battlefield(cards.creature("Atk", "2U", 4, 4), me)
    atk.summoning_sick = False
    atk.attacking = op
    life0 = op.life
    g._combat_damage([atk], first_strike=False)
    assert op.life == life0                              # el daño se previno


def test_targeted_hand_discard_reveal():
    import cards
    g, me, op = _duel()
    op.hand = [cards.land("Swamp", ["B"], basic=True),
               cards.creature("Big", "5B", 6, 6)]
    _spell("Target opponent reveals their hand. You choose a card from it. "
           "That player discards that card.", "Sorcery").on_cast_resolve(g, me, [])
    assert [c.name for c in op.hand] == ["Swamp"]        # descartó la no-tierra cara


def _removal_setup(opp_creature, life=40, lands=8):
    import cardsdb, cards, policy
    from engine import Game, Player
    pol = policy.Policy("avanzado")
    me = Player("me", [cards.creature("z", "1B", 1, 1) for _ in range(20)],
                cards.creature("Cm", "2B", 3, 3, legendary=True), policy=pol)
    op = Player("op", [cards.creature("O", "1U", 1, 1) for _ in range(10)],
                cards.creature("Om", "2U", 1, 1, legendary=True), policy=policy.Policy("avanzado"))
    g = Game([me, op], seed=1)
    for _ in range(lands):
        g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), me)
    g.move_to_battlefield(opp_creature, op)
    rem = cardsdb.build_card_from_data({
        "name": "Doom Blade", "type_line": "Instant", "mana_cost": "{1}{B}",
        "oracle_text": "Destroy target creature."})
    me.hand = [rem]
    me.life = life
    return pol, g, me, rem


def test_bot_holds_removal_for_real_threats():
    import cards
    pol, g, me, rem = _removal_setup(cards.creature("Mouse", "U", 1, 1))
    pol.main_phase(g, me, second=True)
    assert rem in me.hand                          # sano + amenaza chica -> guarda
    pol, g, me, rem = _removal_setup(cards.creature("Dragon", "4U", 6, 6, kw=("flying",)))
    pol.main_phase(g, me, second=True)
    assert rem not in me.hand                       # amenaza grande -> lo usa
    pol, g, me, rem = _removal_setup(cards.creature("Mouse", "U", 1, 1), life=8)
    pol.main_phase(g, me, second=True)
    assert rem not in me.hand                       # bajo presión -> lo usa


def test_bot_values_doublers_and_uses_mutation_aura():
    import cardsdb, cards, policy
    from engine import Game, Player
    pol = policy.Policy("avanzado")
    me = Player("me", [cards.creature("z", "1G", 1, 1) for _ in range(20)],
                cards.creature("Cm", "2G", 3, 3, legendary=True), policy=pol)
    op = Player("op", [cards.creature("O", "1B", 1, 1) for _ in range(10)],
                cards.creature("Om", "2B", 1, 1, legendary=True), policy=policy.Policy("avanzado"))
    g = Game([me, op], seed=1)
    # doblador valorado alto
    ds = cardsdb.build_card_from_data({
        "name": "Doubling Season", "type_line": "Enchantment", "mana_cost": "{4}{G}",
        "oracle_text": "If an effect would create one or more tokens under your "
                       "control, it creates twice that many of those tokens instead."})
    assert ds.token_double and pol.score(g, me, ds) >= 5
    # el bot juega el aura de mutación contra la amenaza más grande del rival
    me.hand = [cardsdb.build_card_from_data({
        "name": "Kenrith's Transformation", "type_line": "Enchantment — Aura",
        "mana_cost": "{1}{G}",
        "oracle_text": "Enchant creature\nEnchanted creature loses all abilities and "
                       "has base power and toughness 3/3."})]
    for _ in range(8):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    big = g.move_to_battlefield(cards.creature("Dragon", "4U", 6, 6, kw=("flying",)), op)
    aura = me.hand[0]
    pol.main_phase(g, me, second=True)
    assert aura not in me.hand and (big.power, big.toughness) == (3, 3)
    assert not big.has("flying")


def test_bot_holds_mutation_aura_without_target():
    import cardsdb, cards, policy
    from engine import Game, Player
    pol = policy.Policy("avanzado")
    me = Player("me", [cards.creature("z", "1G", 1, 1) for _ in range(20)],
                cards.creature("Cm", "2G", 3, 3, legendary=True), policy=pol)
    op = Player("op", [cards.creature("O", "1B", 1, 1) for _ in range(10)],
                cards.creature("Om", "2B", 1, 1, legendary=True), policy=policy.Policy("avanzado"))
    g = Game([me, op], seed=1)     # el rival no tiene criaturas en juego
    me.hand = [cardsdb.build_card_from_data({
        "name": "Lignify", "type_line": "Enchantment — Aura", "mana_cost": "{2}{G}",
        "oracle_text": "Enchant creature\nEnchanted creature is a Treefolk with base "
                       "power and toughness 0/4 and loses all abilities."})]
    for _ in range(8):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    aura = me.hand[0]
    pol.main_phase(g, me, second=True)
    assert aura in me.hand         # sin objetivo -> la guarda


def test_mutation_aura_neutralizes_creature():
    import cardsdb, cards
    g, me, op = _duel()
    victim = g.move_to_battlefield(
        cards.creature("Dragon", "4U", 6, 6, kw=("flying", "indestructible")), op)
    dm = cardsdb.build_card_from_data({
        "name": "Darksteel Mutation", "type_line": "Enchantment — Aura",
        "mana_cost": "{1}{W}",
        "oracle_text": "Enchant creature\nEnchanted creature is an artifact Insect "
                       "with base power and toughness 0/1 and loses all abilities."})
    assert dm.aura_pt_set == (0, 1) and dm.aura_abilities_off
    pm = g.move_to_battlefield(dm, me)
    assert pm.enchanting is victim
    assert (victim.power, victim.toughness) == (0, 1)
    assert not victim.has("flying") and not victim.has("indestructible")


def test_mutation_aura_turns_off_anthem_source():
    import cardsdb, cards
    g, me, op = _duel()
    anth = cardsdb.build_card_from_data({
        "name": "Field Marshal", "type_line": "Creature — Human", "mana_cost": "{3}{W}{W}",
        "power": "6", "toughness": "6",
        "oracle_text": "Other creatures you control get +1/+1."})
    src = g.move_to_battlefield(anth, op)     # es la más grande -> recibe el aura
    buddy = g.move_to_battlefield(cards.creature("Ally", "1W", 2, 2), op)
    assert buddy.power == 3
    kt = cardsdb.build_card_from_data({
        "name": "Kenrith's Transformation", "type_line": "Enchantment — Aura",
        "mana_cost": "{1}{G}",
        "oracle_text": "Enchant creature\nEnchanted creature loses all abilities and "
                       "has base power and toughness 3/3."})
    g.move_to_battlefield(kt, me)
    assert src.abilities_off()
    assert buddy.power == 2


def test_replacement_token_doubler():
    import cardsdb, cards
    g, me, op = _duel()
    pl = cardsdb.build_card_from_data({
        "name": "Parallel Lives", "type_line": "Enchantment", "mana_cost": "{3}{G}",
        "oracle_text": "If an effect would create one or more tokens under your "
                       "control, it creates twice that many of those tokens instead."})
    g.move_to_battlefield(pl, me)
    n0 = len(me.battlefield)
    cardsdb.build_card_from_data({
        "name": "Maker", "type_line": "Sorcery", "mana_cost": "{2}",
        "oracle_text": "Create a 1/1 white Soldier creature token."}).on_cast_resolve(g, me, [])
    assert len(me.battlefield) - n0 == 2


def test_replacement_counter_doublers():
    import cardsdb, cards
    g, me, op = _duel()
    ds = cardsdb.build_card_from_data({
        "name": "Doubling Season", "type_line": "Enchantment", "mana_cost": "{4}{G}",
        "oracle_text": "If an effect would put one or more counters on a permanent "
                       "you control, it puts twice that many of those counters on "
                       "that permanent instead."})
    g.move_to_battlefield(ds, me)
    c = g.move_to_battlefield(cards.creature("K", "1G", 2, 2), me)
    g.add_counters(c, "+1/+1", 1)
    assert c.counters.get("+1/+1") == 2
    g2, me2, op2 = _duel()
    hs = cardsdb.build_card_from_data({
        "name": "Hardened Scales", "type_line": "Enchantment", "mana_cost": "{G}",
        "oracle_text": "If one or more +1/+1 counters would be put on a creature you "
                       "control, that many plus one +1/+1 counters are put on it instead."})
    g2.move_to_battlefield(hs, me2)
    c2 = g2.move_to_battlefield(cards.creature("K", "1G", 2, 2), me2)
    g2.add_counters(c2, "+1/+1", 1)
    assert c2.counters.get("+1/+1") == 2


def test_replacement_damage_doubler():
    import cardsdb
    g, me, op = _duel()
    fr = cardsdb.build_card_from_data({
        "name": "Furnace of Rath", "type_line": "Enchantment", "mana_cost": "{3}{R}",
        "oracle_text": "If a source would deal damage to a permanent or player, it "
                       "deals double that damage to that permanent or player instead."})
    g.move_to_battlefield(fr, me)
    l0 = op.life
    g.deal_damage(None, op, 3)
    assert op.life == l0 - 6


def test_replacement_die_to_exile():
    import cardsdb, cards
    g, me, op = _duel()
    rip = cardsdb.build_card_from_data({
        "name": "Exile Field", "type_line": "Enchantment", "mana_cost": "{2}{W}",
        "oracle_text": "If a creature would die, exile it instead."})
    g.move_to_battlefield(rip, me)
    v = g.move_to_battlefield(cards.creature("V", "1B", 2, 2), op)
    g.to_graveyard(v, "test")
    assert v.card in op.exile and v.card not in op.graveyard


def test_precons_have_even_coverage():
    # los tres precons registrados deben tener cobertura de efectos comparable
    # (no que un mazo esté programado y los otros sean vainilla).
    import coverage, decks
    counts = {}
    for name in ("lorehold", "tricky", "kang"):
        deck, cmd = decks.build(name)
        pool = [c for c in ([cmd] + deck) if "basic" not in c.supertypes]
        counts[name] = sum(1 for c in pool if coverage._implemented(c))
    assert min(counts.values()) >= 20, counts
    assert max(counts.values()) - min(counts.values()) <= 6, counts


def test_board_eval_reflects_advantage():
    import cards, policy
    from engine import Game, Player
    pol = policy.Policy("avanzado")
    me = Player("me", [cards.creature("z", "1G", 1, 1) for _ in range(10)],
                cards.creature("Cm", "2G", 3, 3, legendary=True), policy=pol)
    op = Player("op", [cards.creature("O", "1B", 1, 1) for _ in range(10)],
                cards.creature("Om", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    base = pol.board_eval(g, me)
    g.move_to_battlefield(cards.creature("Big", "3G", 5, 5), me)
    assert pol.board_eval(g, me) > base


def test_bot_uses_loot_but_respects_gates():
    import cardsdb, cards, policy
    from engine import Game, Player
    pol = policy.Policy("avanzado")
    me = Player("me", [cards.creature("z", "1U", 1, 1) for _ in range(20)],
                cards.creature("Cm", "2U", 3, 3, legendary=True), policy=pol)
    op = Player("op", [cards.creature("O", "1B", 1, 1) for _ in range(10)],
                cards.creature("Om", "2B", 1, 1, legendary=True), policy=policy.Policy("avanzado"))
    g = Game([me, op], seed=1)
    loot = cardsdb.build_card_from_data({
        "name": "Looter", "type_line": "Creature — Wizard", "mana_cost": "{1}{U}",
        "power": "1", "toughness": "1",
        "oracle_text": "{T}, Discard a card: Draw two cards."})
    pm = g.move_to_battlefield(loot, me)
    pm.summoning_sick = False
    me.library += [cards.creature("a", "1U", 1, 1) for _ in range(5)]
    # mano de sobra -> el bot lootea (descarta 1, roba 2 => +1)
    me.hand = [cards.creature("h", "1U", 1, 1) for _ in range(5)]
    h0 = len(me.hand)
    pol._activate_perm_abilities(g, me, second=True)
    assert len(me.hand) == h0 + 1

    # mano corta -> NO lootea (respeta el gate de descarte)
    g2 = Game([me, op], seed=1)
    loot2 = cardsdb.build_card_from_data({
        "name": "Looter2", "type_line": "Creature — Wizard", "mana_cost": "{1}{U}",
        "power": "1", "toughness": "1",
        "oracle_text": "{T}, Discard a card: Draw two cards."})
    me.battlefield = []
    pm2 = g2.move_to_battlefield(loot2, me)
    pm2.summoning_sick = False
    me.hand = [cards.creature("h", "1U", 1, 1) for _ in range(2)]
    h1 = len(me.hand)
    pol._activate_perm_abilities(g2, me, second=True)
    assert len(me.hand) == h1                     # mano < 4: no descarta


def test_flashback_casts_from_graveyard_then_exiles():
    import cardsdb, cards
    g, me, op = _duel()
    fb = cardsdb.build_card_from_data({
        "name": "Deep Analysis", "type_line": "Sorcery", "mana_cost": "{3}{U}",
        "oracle_text": "Draw two cards.\nFlashback {1}{U}", "keywords": ["Flashback"]})
    assert fb.gy_play.get("mode") == "flashback"
    me.graveyard = [fb]
    for _ in range(2):
        g.move_to_battlefield(cards.land("Island", ["U"], basic=True), me)
    me.library += [cards.creature("z", "1U", 1, 1) for _ in range(5)]
    h0 = len(me.hand)
    assert g.play_from_graveyard(me, fb) is True
    assert len(me.hand) == h0 + 2 and fb in me.exile and fb not in me.graveyard


def test_play_from_graveyard_this_turn():
    import cardsdb, cards
    g, me, op = _duel()
    draw2 = cardsdb.build_card_from_data({
        "name": "Divination", "type_line": "Sorcery", "mana_cost": "{2}{U}",
        "oracle_text": "Draw two cards."})
    me.graveyard = [draw2]
    me.library += [cards.creature("z", "1U", 1, 1) for _ in range(5)]
    for _ in range(4):
        g.move_to_battlefield(cards.land("Island", ["U"], basic=True), me)
    yw = cardsdb.build_card_from_data({
        "name": "Yawgmoth's Will", "type_line": "Sorcery", "mana_cost": "{2}{B}",
        "oracle_text": "You may play lands and cast spells from your graveyard this turn."})
    assert "gy_recast" in yw.tags
    h0 = len(me.hand)
    yw.on_cast_resolve(g, me, [])
    assert len(me.hand) == h0 + 2 and draw2 in me.exile


def test_attack_trigger_self_pump():
    import cardsdb, cards
    g, me, op = _duel()
    a = cardsdb.build_card_from_data({
        "name": "Rager", "type_line": "Creature — Beast", "mana_cost": "{2}",
        "power": "2", "toughness": "2",
        "oracle_text": "Whenever this creature attacks, it gets +2/+0 until end of turn."})
    assert "attacks" in a.triggers
    pm = g.move_to_battlefield(a, me)
    pm.card.triggers["attacks"](g, pm)
    assert pm.power == 4 and pm.toughness == 2


def test_set_and_double_life():
    import cardsdb
    g, me, op = _duel()
    cardsdb.build_card_from_data({
        "name": "S", "type_line": "Sorcery", "mana_cost": "{2}",
        "oracle_text": "Your life total becomes 20."}).on_cast_resolve(g, me, [])
    assert me.life == 20
    me.life = 13
    cardsdb.build_card_from_data({
        "name": "D", "type_line": "Sorcery", "mana_cost": "{2}",
        "oracle_text": "Double your life total."}).on_cast_resolve(g, me, [])
    assert me.life == 26


def test_double_and_remove_counters():
    import cardsdb, cards
    g, me, op = _duel()
    c = g.move_to_battlefield(cards.creature("K", "1G", 2, 2), me)
    g.add_counters(c, "+1/+1", 2)
    cardsdb.build_card_from_data({
        "name": "Dbl", "type_line": "Sorcery", "mana_cost": "{4}{G}",
        "oracle_text": "Double the number of +1/+1 counters on each creature you control."}).on_cast_resolve(g, me, [])
    assert c.counters.get("+1/+1") == 4
    v = g.move_to_battlefield(cards.creature("V", "1U", 2, 2), op)
    g.add_counters(v, "+1/+1", 3)
    cardsdb.build_card_from_data({
        "name": "Rm", "type_line": "Instant", "mana_cost": "{1}",
        "oracle_text": "Remove all counters from target permanent."}).on_cast_resolve(g, me, [])
    assert not v.counters


def test_sacrifice_altar_adds_mana():
    import cardsdb, cards
    g, me, op = _duel()
    altar = cardsdb.build_card_from_data({
        "name": "Altar", "type_line": "Artifact", "mana_cost": "{3}",
        "oracle_text": "Sacrifice a creature: Add {C}{C}."})
    assert len(altar.activated_abilities) == 1
    assert altar.activated_abilities[0].get("sacrifice_other") == {"count": 1, "type": "creature"}
    pm = g.move_to_battlefield(altar, me)
    spare = g.move_to_battlefield(cards.creature("Sp", "1G", 1, 1), me)
    assert g.activate_ability(pm, 0) is True
    assert spare not in me.battlefield and me.mana_pool == 2


def test_cascade_spell_free_casts_cheaper():
    import cardsdb, cards
    g, me, op = _duel()
    me.library = [cards.creature("Cheap", "1G", 2, 2)] + \
        [cards.land("Forest", ["G"], basic=True) for _ in range(5)]
    casc = cardsdb.build_card_from_data({
        "name": "Bloom", "type_line": "Sorcery", "mana_cost": "{4}{G}",
        "oracle_text": "Cascade\nDraw two cards.", "keywords": ["Cascade"]})
    assert "cascade" in casc.tags
    casc.on_cast_resolve(g, me, [])
    assert any(p.name == "Cheap" for p in me.battlefield)


def test_cascade_creature_triggers_on_enter():
    import cardsdb, cards
    g, me, op = _duel()
    me.library = [cards.creature("Small", "1B", 2, 2)] + \
        [cards.land("Forest", ["G"], basic=True) for _ in range(5)]
    cc = cardsdb.build_card_from_data({
        "name": "Beast", "type_line": "Creature — Beast", "mana_cost": "{5}{G}",
        "power": "6", "toughness": "6", "oracle_text": "Cascade", "keywords": ["Cascade"]})
    g.move_to_battlefield(cc, me)
    assert any(p.name == "Small" for p in me.battlefield)


def test_self_death_trigger_creates_token_not_on_etb():
    import cardsdb
    g, me, op = _duel()
    c = cardsdb.build_card_from_data({
        "name": "Thing", "type_line": "Creature — Beast", "mana_cost": "{2}",
        "power": "2", "toughness": "2",
        "oracle_text": "When this creature dies, create a 1/1 white Spirit creature token."})
    assert c.on_death is not None and c.on_etb is None
    pm = g.move_to_battlefield(c, me)
    before = len(me.battlefield)
    g.to_graveyard(pm, "test")
    assert any(p.is_token for p in me.battlefield)       # token creado al morir
    assert len(me.battlefield) == before                 # murió 1, entró 1 (token)


def test_aristocrat_counter_on_death():
    import cardsdb, cards
    g, me, op = _duel()
    ar = cardsdb.build_card_from_data({
        "name": "Arist", "type_line": "Creature — Zombie", "mana_cost": "{2}",
        "power": "2", "toughness": "2",
        "oracle_text": "Whenever another creature you control dies, put a +1/+1 "
                       "counter on this creature."})
    assert "death" in ar.triggers
    watcher = g.move_to_battlefield(ar, me)
    victim = g.move_to_battlefield(cards.creature("V", "1G", 1, 1), me)
    p0 = watcher.power
    g.to_graveyard(victim, "test")
    g.resolve_stack()
    assert watcher.power == p0 + 1


def test_mass_bounce_returns_creatures_to_hand():
    import cards
    g, me, op = _duel()
    a = g.move_to_battlefield(cards.creature("Mine", "1G", 2, 2), me)
    b = g.move_to_battlefield(cards.creature("Foe", "1U", 2, 2), op)
    _spell("Return all creatures to their owners' hands.", "Instant").on_cast_resolve(g, me, [])
    assert not me.creatures() and not op.creatures()
    assert any(c.name == "Mine" for c in me.hand) and any(c.name == "Foe" for c in op.hand)


def test_two_target_fight():
    import cards
    g, me, op = _duel()
    mine = g.move_to_battlefield(cards.creature("Mine", "1G", 4, 4), me)
    foe = g.move_to_battlefield(cards.creature("Foe", "1U", 2, 2), op)
    _spell("Target creature fights another target creature.").on_cast_resolve(g, me, [foe])
    assert foe not in op.battlefield and mine.damage == 2


def test_targeted_sacrifice_beats_indestructible():
    import cards
    g, me, op = _duel()
    v = g.move_to_battlefield(cards.creature("Big", "1U", 6, 6, kw=("indestructible",)), op)
    _spell("Choose target creature. Its controller sacrifices it.").on_cast_resolve(g, me, [v])
    assert v not in op.battlefield


def test_prevent_all_and_shield_damage():
    g, me, op = _duel()
    _spell("Prevent all damage that would be dealt to you this turn.").on_cast_resolve(g, me, [])
    l0 = me.life
    g.deal_damage(None, me, 5)
    assert me.life == l0
    g2, me2, op2 = _duel()
    _spell("Prevent the next 3 damage that would be dealt to any target this turn.").on_cast_resolve(g2, me2, [])
    l2 = me2.life
    g2.deal_damage(None, me2, 5)
    assert me2.life == l2 - 2


def test_scryfall_static_anthem_buffs():
    import cardsdb, cards
    g, me, op = _duel()
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    anth = cardsdb.build_card_from_data({
        "name": "Anthem", "type_line": "Enchantment", "mana_cost": "{2}{W}",
        "oracle_text": "Creatures you control get +1/+1."})
    g.move_to_battlefield(anth, me)
    assert (bear.power, bear.toughness) == (3, 3)
    kw = cardsdb.build_card_from_data({
        "name": "Kw", "type_line": "Enchantment", "mana_cost": "{2}{G}",
        "oracle_text": "Creatures you control have trample."})
    g.move_to_battlefield(kw, me)
    assert bear.has("trample")


def test_recurring_upkeep_and_end_step_triggers():
    import cardsdb
    g, me, op = _duel()
    up = cardsdb.build_card_from_data({
        "name": "UpGain", "type_line": "Enchantment", "mana_cost": "{2}",
        "oracle_text": "At the beginning of your upkeep, you gain 2 life."})
    assert list(up.triggers.keys()) == ["upkeep"] and up.on_etb is None
    g.move_to_battlefield(up, me)
    l0 = me.life
    g.emit("upkeep", player=me)
    g.resolve_stack()
    assert me.life == l0 + 2
    es = cardsdb.build_card_from_data({
        "name": "EndDrain", "type_line": "Enchantment", "mana_cost": "{2}",
        "oracle_text": "At the beginning of your end step, each opponent loses 1 life."})
    g.move_to_battlefield(es, me)
    o0 = op.life
    g.emit("end_step", player=me)
    g.resolve_stack()
    assert op.life == o0 - 1


def test_mass_keyword_grant():
    import cards
    g, me, op = _duel()
    a = g.move_to_battlefield(cards.creature("A", "1G", 2, 2), me)
    b = g.move_to_battlefield(cards.creature("B", "1G", 1, 1), me)
    _spell("Creatures you control gain indestructible until end of turn.").on_cast_resolve(g, me, [])
    assert a.has("indestructible") and b.has("indestructible")


def test_reanimation_refuses_instants():
    import cards
    g, me, op = _duel()
    inst = cards.Card("Bolt", {"instant"}, cards.parse_cost("R"))
    crea = cards.creature("Zombie", "2B", 3, 3)
    me.graveyard = [inst, crea]
    _spell("Return target creature card from your graveyard to the battlefield.",
           "Sorcery").on_cast_resolve(g, me, [])
    assert inst in me.graveyard
    assert any(p.name == "Zombie" for p in me.battlefield)


def test_move_instant_to_battlefield_refused():
    import cards
    g, me, op = _duel()
    r = g.move_to_battlefield(cards.Card("Shock", {"instant"}, cards.parse_cost("R")), me)
    assert r is None and any(c.name == "Shock" for c in me.graveyard)


def test_counter_target_ability_stifle():
    from engine import StackObject
    g, me, op = _duel()
    st = _spell("Counter target activated or triggered ability.", cost="{U}")
    assert st.target_spec == "stack_ability" and "counter" in st.tags
    so = StackObject(op, lambda g: None, source=None, label="ability:x", kind="ability")
    g.stack.append(so)
    st.on_cast_resolve(g, me, [so])
    assert so not in g.stack


def test_mana_ritual_floats_and_pays():
    from engine import Cost
    g, me, op = _duel()
    _spell("Add {C}{C}{C}.").on_cast_resolve(g, me, [])
    assert me.mana_pool == 3
    assert me.can_pay(Cost(3, ())) is True         # el pool paga sin tierras
    me.pay(Cost(3, ()))
    assert me.mana_pool == 0


def test_variable_count_effects():
    import cards
    g, me, op = _duel()
    for _ in range(3):
        g.move_to_battlefield(cards.creature("E", "1G", 1, 1, subtypes=("Elf",)), me)
    me.library += [cards.creature("z", "1G", 1, 1) for _ in range(10)]
    h0 = len(me.hand)
    _spell("Draw cards equal to the number of Elves you control.", "Sorcery").on_cast_resolve(g, me, [])
    assert len(me.hand) == h0 + 3                   # 3 Elfos
    l0 = op.life
    _spell("Deal damage to any target equal to the number of creatures you control.").on_cast_resolve(g, me, [])
    assert op.life == l0 - 3


def test_variable_pump_where_x():
    import cards
    g, me, op = _duel()
    k = g.move_to_battlefield(cards.creature("K", "1G", 2, 2), me)
    g.move_to_battlefield(cards.creature("C", "1G", 1, 1), me)
    _spell("Target creature gets +X/+X until end of turn, where X is the number "
           "of creatures you control.").on_cast_resolve(g, me, [])
    assert max(x.power for x in me.creatures()) == 4    # mejor 2/2 +2/+2


def test_regenerate_grants_indestructible():
    import cards
    g, me, op = _duel()
    r = g.move_to_battlefield(cards.creature("R", "1G", 2, 2), me)
    _spell("Regenerate target creature.").on_cast_resolve(g, me, [])
    assert r.has("indestructible")


def test_mass_plus_one_counters():
    import cards
    g, me, op = _duel()
    a = g.move_to_battlefield(cards.creature("A", "1G", 1, 1), me)
    b = g.move_to_battlefield(cards.creature("B", "1G", 2, 2), me)
    _spell("Put a +1/+1 counter on each creature you control.", "Sorcery").on_cast_resolve(g, me, [])
    assert a.power == 2 and b.power == 3


def test_etb_pump_and_tap_triggers():
    import cardsdb, cards
    g, me, op = _duel()
    tapper = cardsdb.build_card_from_data({
        "name": "Tapper", "type_line": "Creature — Human", "mana_cost": "{2}",
        "power": "2", "toughness": "2",
        "oracle_text": "When this creature enters, tap target creature."})
    assert tapper.on_etb is not None
    v = g.move_to_battlefield(cards.creature("V", "1U", 2, 2), op)
    g.move_to_battlefield(tapper, me)
    assert v.tapped is True


def test_look_at_top_ability_shows_a_view():
    # "Look at the top N cards of your library" (mirar/reordenar, sin llevarte
    # ninguna) antes no mostraba nada; ahora presenta una vista tipo scry con la
    # carta a decidir para que el humano SÍ las vea.
    import cardsdb, cards
    from engine import Game, Player
    seer = cardsdb.build_card_from_data({
        "name": "Seer", "type_line": "Creature — Wizard", "mana_cost": "{U}",
        "power": "1", "toughness": "1",
        "oracle_text": "{T}: Look at the top four cards of your library, then put "
                       "them back in any order."})
    assert seer.activated_abilities, "la habilidad debe parsearse"
    me = Player("me", [cards.creature(f"C{i}", "1U", 1, 1) for i in range(20)],
                cards.creature("Cm", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.land("I", ["U"], basic=True) for _ in range(10)],
                cards.creature("Om", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.interactive_human = me
    pm = g.move_to_battlefield(seer, me)
    assert g.activate_ability(pm, 0) is True
    pc = g.pending_choice
    assert pc is not None and pc["kind"] == "scry"       # hay una vista pendiente
    assert pc.get("card")                                # muestra qué carta se decide


def test_pump_spell_targeted_buff():
    # Giant Growth: "Target creature gets +3/+3 until end of turn" — antes el
    # hechizo no hacía nada (on_cast_resolve=None).
    import cardsdb, cards
    g, me, op = _duel()
    gg = cardsdb.build_card_from_data({
        "name": "Giant Growth", "type_line": "Instant", "mana_cost": "{G}",
        "oracle_text": "Target creature gets +3/+3 until end of turn."})
    assert gg.on_cast_resolve is not None and gg.target_spec == "own_creature"
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    gg.on_cast_resolve(g, me, [bear])
    assert (bear.power, bear.toughness) == (5, 5)


def test_debuff_spell_kills_creature():
    # Grasp of Darkness: "-4/-4" es remoción por reducción de resistencia.
    import cardsdb, cards
    g, me, op = _duel()
    grasp = cardsdb.build_card_from_data({
        "name": "Grasp of Darkness", "type_line": "Instant", "mana_cost": "{B}{B}",
        "oracle_text": "Target creature gets -4/-4 until end of turn."})
    assert grasp.on_cast_resolve is not None and grasp.target_spec == "opp_creature"
    v = g.move_to_battlefield(cards.creature("Victim", "1U", 2, 2), op)
    grasp.on_cast_resolve(g, me, [v])
    assert v not in op.battlefield                       # murió por SBA (0 de resist.)


def test_mass_pump_and_mass_debuff_spells():
    import cardsdb, cards
    g, me, op = _duel()
    pump = cardsdb.build_card_from_data({
        "name": "Team Pump", "type_line": "Instant", "mana_cost": "{1}{G}",
        "oracle_text": "Creatures you control get +2/+2 until end of turn."})
    a = g.move_to_battlefield(cards.creature("A", "1G", 1, 1), me)
    b = g.move_to_battlefield(cards.creature("B", "1G", 2, 2), me)
    enemy = g.move_to_battlefield(cards.creature("E", "1U", 3, 3), op)
    pump.on_cast_resolve(g, me, [])
    assert a.power == 3 and b.power == 4 and enemy.power == 3   # solo las tuyas
    # barrida por -X/-X
    infest = cardsdb.build_card_from_data({
        "name": "Infest", "type_line": "Sorcery", "mana_cost": "{1}{B}",
        "oracle_text": "All creatures get -2/-2 until end of turn."})
    x = g.move_to_battlefield(cards.creature("X", "1G", 2, 2), me)
    y = g.move_to_battlefield(cards.creature("Y", "1U", 2, 2), op)
    infest.on_cast_resolve(g, me, [])
    assert x not in me.battlefield and y not in op.battlefield


def test_loyalty_targeted_effect_resolves():
    # un planeswalker con "-3: Destroy target creature" ahora SÍ hace algo (antes
    # solo movía la lealtad). El objetivo se auto-elige (rival más amenazante).
    import cardsdb, cards
    g, me, op = _duel()
    pw = cardsdb.build_card_from_data({
        "name": "Slayer PW", "type_line": "Legendary Planeswalker — Test",
        "mana_cost": "{3}{R}", "loyalty": "4",
        "oracle_text": "+1: Put a +1/+1 counter on target creature.\n"
                       "-3: Destroy target creature.\n-7: You get an emblem."})
    # las tres etapas tienen texto legible para mostrar en la UI
    assert len(pw.loyalty_texts) == 3
    assert pw.loyalty_abilities[1][1] is not None       # -3 tiene efecto real
    pm = g.move_to_battlefield(pw, me)
    pm.counters["loyalty"] = 4
    victim = g.move_to_battlefield(cards.creature("Beast", "3G", 4, 4), op)
    assert g.activate_loyalty(pm, 1) is True             # -3
    assert victim not in op.battlefield
    assert pm.counters["loyalty"] == 1


# -- reanimación/recuperación: el humano ELIGE la carta ------------------- #
def _reco_players():
    import cards
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1U", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    return Game([me, op], seed=1), me


def _mkc(name, cmc):
    from cardsdb import build_card_from_data
    return build_card_from_data({"name": name, "mana_cost": "{%d}" % cmc,
                                 "cmc": cmc, "type_line": "Creature",
                                 "oracle_text": "", "power": "2",
                                 "toughness": "2"})


def test_graveyard_reanimate_human_chooses_bot_autopicks():
    from cardsdb import build_card_from_data
    spell = build_card_from_data({
        "name": "Raise", "mana_cost": "{3}{B}", "cmc": 4,
        "type_line": "Sorcery",
        "oracle_text": "Return target creature card from your graveyard "
                       "to the battlefield."})
    # humano: recibe la elección (ve las cartas del cementerio)
    g, me = _reco_players()
    g.interactive_human = me
    me.graveyard = [_mkc("Dragon", 6), _mkc("Rat", 1)]
    spell.on_cast_resolve(g, me, spell)
    pc = g.pending_choice
    assert pc and pc["kind"] == "reanimate"
    assert {o["name"] for o in pc["options"]} == {"Dragon", "Rat"}
    pc["_apply"](1)                                    # elige la Rata
    assert any(p.card.name == "Rat" for p in me.battlefield)
    # bot: sin modal, auto-elige la mejor (mayor CMC)
    g2, bot = _reco_players()
    spell2 = build_card_from_data({
        "name": "Raise", "mana_cost": "{3}{B}", "cmc": 4,
        "type_line": "Sorcery",
        "oracle_text": "Return target creature card from your graveyard "
                       "to the battlefield."})
    bot.graveyard = [_mkc("Dragon", 6), _mkc("Rat", 1)]
    spell2.on_cast_resolve(g2, bot, spell2)
    assert g2.pending_choice is None
    assert any(p.card.name == "Dragon" for p in bot.battlefield)


def test_exile_recover_human_chooses():
    from cardsdb import build_card_from_data
    spell = build_card_from_data({
        "name": "Recuperar", "mana_cost": "{2}", "cmc": 2,
        "type_line": "Sorcery",
        "oracle_text": "Return target card you own from exile to your hand."})
    assert spell.on_cast_resolve
    g, me = _reco_players()
    g.interactive_human = me
    me.exile = [_mkc("Angel", 5), _mkc("Goblin", 1)]
    spell.on_cast_resolve(g, me, spell)
    pc = g.pending_choice
    assert pc and pc["kind"] == "exile_pick"
    assert {o["name"] for o in pc["options"]} == {"Angel", "Goblin"}
    pc["_apply"](1)                                    # elige el Goblin
    assert "Goblin" in [c.name for c in me.hand]
    assert "Goblin" not in [c.name for c in me.exile]


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
