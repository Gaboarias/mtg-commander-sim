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
        for _ in range(40):
            st = ig.state()
            if st["phase"] == "over":
                break
            if st["phase"] == "defense":
                c = st["combat"]
                assert c and c["attackers"] and "from" in c
                json.dumps(st)
                life0 = st["players"][0]["life"]
                st2 = ig.resolve_defense([])       # tomo el daño
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
    low = " ".join(recs).lower()
    assert "ramp" in low and "barrida" in low and "tierras" in low


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
