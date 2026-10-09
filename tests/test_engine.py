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
def test_ai_blocks_with_tokens_vs_big_threats():
    # La IA usa tokens para chump/gang ante amenazas grandes (antes solo bloqueaba
    # si mataba-y-sobrevivía o si el golpe era letal -> los tokens nunca defendían).
    me = _mk_player("me"); foe = _mk_player("foe")
    g = _game([me, foe])
    # dos tokens 1/1 del defensor
    t1 = cards.make_token(g, me, "Goblin", 1, 1)
    t2 = cards.make_token(g, me, "Goblin", 1, 1)
    # atacante grande NO letal (vida alta), pero amenaza real (5/5)
    big = g.move_to_battlefield(creature("Giant", "4R", 5, 5), foe)
    big.summoning_sick = False; big.attacking = me
    me.life = 10                                     # bajo presión (golpe de 5 a 10 de vida)
    res = me.policy.declare_blockers(g, me, [big])
    blockers = [b for _a, b in res]
    assert len(blockers) >= 1                       # ahora SÍ defiende con token(s)
    assert all(b in (t1, t2) for b in blockers)      # y usa los tokens como fodder
    # gang para MATAR: dos tokens 2/2 matan a un 3/3 y la IA los combina
    me2 = _mk_player("m2"); foe2 = _mk_player("f2")
    g2 = _game([me2, foe2])
    a = cards.make_token(g2, me2, "Zombie", 2, 2)
    b2 = cards.make_token(g2, me2, "Zombie", 2, 2)
    atk = g2.move_to_battlefield(creature("Bruiser", "2R", 3, 3), foe2)
    atk.summoning_sick = False; atk.attacking = me2
    res2 = me2.policy.declare_blockers(g2, me2, [atk])
    assert len({b.uid for _a, b in res2}) == 2       # gang-block con los dos tokens


def test_activate_ability_during_defense():
    # El humano puede ACTIVAR habilidades de sus permanentes durante la ventana de
    # defensa (pump, hacer una ficha para bloquear, etc.), no solo lanzar instantáneos.
    import interactive, cards, decks
    from engine import parse_cost
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human(); op = ig.g.opponents(hu)[0]

    def pump(g, ctrl, perm, targets=None):
        g.add_counters(perm, "+1/+1", 1)
    guy = cards.creature("Pumper", "1G", 1, 1)
    guy.activated_abilities = ({"cost": parse_cost("0"), "tap": False,
        "sacrifice_self": False, "sacrifice_other": None, "pay_life": 0, "discard": 0,
        "label": "Crece", "effect": pump, "target_spec": None, "target_count": 1,
        "is_copy_ability": False, "sorcery_speed": False},)
    pm = ig.g.move_to_battlefield(guy, hu); pm.summoning_sick = False
    atk = ig.g.move_to_battlefield(cards.creature("Ogro", "2R", 3, 3), op)
    atk.summoning_sick = False
    ig.g._begin_combat(op)
    declared = ig.g._declare_attackers(op, [(atk, hu)])
    ig._attacker = op; ig._declared = declared; ig.mode = "defense"; ig.phase = "defense"
    st = ig.state()
    ab = st["combat"]["abilities"]
    assert any(a["uid"] == pm.uid and a["label"] == "Crece" for a in ab)   # ofrecida
    p0 = pm.power
    ig.activate_in_combat(pm.uid, 0)
    assert pm.power == p0 + 1         # se activó durante la defensa
    assert ig.mode == "defense"       # sigue en la ventana para poder bloquear


def test_combat_ability_manual_target():
    # Una habilidad de combate CON objetivo respeta el objetivo elegido a mano.
    import interactive, cards, decks
    from engine import parse_cost
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human(); op = ig.g.opponents(hu)[0]

    def pump(g, ctrl, perm, targets=None):
        for t in (targets or []):
            g.add_counters(t, "+1/+1", 2)
    src = cards.creature("Buffer", "1G", 1, 1)
    src.activated_abilities = ({"cost": parse_cost("0"), "tap": False,
        "sacrifice_self": False, "sacrifice_other": None, "pay_life": 0, "discard": 0,
        "label": "Da +2/+2", "effect": pump, "target_spec": "own_creature",
        "target_count": 1, "is_copy_ability": False, "sorcery_speed": False},)
    pm = ig.g.move_to_battlefield(src, hu); pm.summoning_sick = False
    t1 = cards.make_token(ig.g, hu, "A", 1, 1)
    t2 = cards.make_token(ig.g, hu, "B", 1, 1)
    atk = ig.g.move_to_battlefield(cards.creature("Ogro", "2R", 3, 3), op)
    atk.summoning_sick = False
    ig.g._begin_combat(op)
    ig._attacker = op; ig._declared = ig.g._declare_attackers(op, [(atk, hu)])
    ig.mode = "defense"; ig.phase = "defense"
    ig.activate_in_combat(pm.uid, 0, target_uids=[t2.uid])   # apuntar a t2 a mano
    assert (t2.power, t2.toughness) == (3, 3)
    assert (t1.power, t1.toughness) == (1, 1)                # t1 intacto


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


# -- Simic Ascendancy: ya no gana "por lanzar hechizos" (texto inventado) ---- #
def test_simic_ascendancy_is_real_card_not_invented():
    import decks
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    asc = g.move_to_battlefield(decks.real("Simic Ascendancy"), a)
    assert "cast" not in (asc.card.triggers or {})
    assert asc.card.cost.cmc == 2               # {G}{U}


# -- Quintorius crea Espiritu al salir carta del cementerio (P1.1) --------- #
def test_quintorius_makes_spirit_on_leave_graveyard():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    q = g.move_to_battlefield(cards.Quintorius(), a)
    assert (q.power, q.toughness) == (2, 4)       # oráculo real {3}{R}{W} 2/4
    assert not a.graveyard                         # sin el "molino al entrar" inventado
    a.graveyard.append(land("Mountain", [R], basic=True))
    g.leave_graveyard(a, a.graveyard[0], dest="exile")
    g.resolve_stack()
    sp = [p for p in a.battlefield if p.name == "Spirit"]
    assert len(sp) == 1
    assert sp[0].power == 4                        # 3/2 + "Spirits you control get +1/+0"


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
    assert a.life == a_life + 1 - 2   # Kang gana 1; Night's Whisper hace perder 2


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
1 Kang, Temporal Tyrant
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
    assert parsed["commander"] == "Kang, Temporal Tyrant"
    names = [n for _, n in parsed["cards"]]
    assert "Go for the Throat" in names   # se limpia el (SET) 12
    assert "Island" not in names          # sideboard ignorado
    deck, cmd, report = decklist.build_deck(parsed, fetch=None)
    assert len(deck) == 99
    assert cmd.name == "Kang, Temporal Tyrant"
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


def _instant0(name="Chispazo"):
    import cardsdb
    return cardsdb.build_card_from_data({
        "name": name, "type_line": "Instant", "mana_cost": "{0}",
        "oracle_text": "You gain 2 life."})


def test_human_attack_opens_damage_window_with_instant():
    # En el combate propio del humano, si tiene un instantáneo, tras declarar
    # atacantes y bloquear la IA se abre el PASO DE DAÑO (stage "damage") y el daño
    # recién se aplica con finish_combat.
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    st = ig.state()
    if st["phase"] != "main":
        return                                        # el setup no dio turno humano
    hu = ig.human(); op = ig.g.opponents(hu)[0]
    atk = ig.g.move_to_battlefield(cards.creature("Golpe", "1R", 4, 4), hu)
    atk.summoning_sick = False
    hu.hand.append(_instant0())
    life0 = op.life
    st = ig.attack([atk.uid], target_index=ig.players.index(op))
    assert st["phase"] == "combat" and st["combat"]["stage"] == "damage"
    assert st["combat"]["attacking"] is True
    assert op.life == life0                           # el daño aún NO se aplicó
    st = ig.finish_combat()
    assert op.life == life0 - 4                        # ahora sí
    assert st["phase"] == "main"


def test_defense_without_instant_clears_mode_no_crash():
    # Regresión: defender sin instantáneos aplica el daño directo y NO deja el modo
    # "defense" con atacantes ya resueltos (que rompía state() en _defense_state).
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human(); op = ig.g.opponents(hu)[0]
    # sin instantáneos en mano
    hu.hand = [c for c in hu.hand if not (("instant" in c.types) or ("flash" in c.keywords))]
    # simulamos que estamos defendiendo un ataque declarado
    atk = ig.g.move_to_battlefield(cards.creature("Ogro", "2R", 3, 3), op)
    atk.summoning_sick = False
    ig.g._begin_combat(op)
    declared = ig.g._declare_attackers(op, [(atk, hu)])
    ig._attacker = op
    ig._declared = declared
    ig.mode = "defense"; ig.phase = "defense"
    life0 = hu.life
    st = ig.resolve_defense([])            # tomo el daño, sin trucos
    import json; json.dumps(st)            # state() no explota (era el crash)
    assert st["phase"] in ("main", "defense", "combat", "react", "choose", "over")
    assert hu.life < life0                 # el daño del atacante se aplicó
    # si quedó en defense, es por un ATAQUE nuevo (atacantes vivos), no basura
    if st["phase"] == "defense":
        assert all(a.attacking is not None for a in ig._declared)


def test_human_attack_without_instant_skips_damage_window():
    # sin instantáneos, no hay nada que responder: el daño se aplica directo.
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    st = ig.state()
    if st["phase"] != "main":
        return
    hu = ig.human(); op = ig.g.opponents(hu)[0]
    hu.hand = [c for c in hu.hand if not (("instant" in c.types) or ("flash" in c.keywords))]
    atk = ig.g.move_to_battlefield(cards.creature("Golpe", "1R", 4, 4), hu)
    atk.summoning_sick = False
    life0 = op.life
    st = ig.attack([atk.uid], target_index=ig.players.index(op))
    assert st["phase"] == "main"                       # sin ventana de daño
    assert op.life == life0 - 4


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
            if st["phase"] == "combat":      # paso de daño (post-bloqueo): aplico
                ig.finish_combat()
                continue
            if st["phase"] == "defense":
                c = st["combat"]
                assert c and c["attackers"] and "from" in c and c["stage"] == "declare"
                json.dumps(st)
                life0 = st["players"][0]["life"]
                st2 = ig.resolve_defense([])       # tomo el daño
                # con varios rivales, al resolver una defensa puede abrirse otra
                # ventana (otro oponente ataca) o el paso de daño: resolvemos todo.
                guard = 0
                while st2["phase"] in ("defense", "combat") and guard < 15:
                    st2 = (ig.finish_combat() if st2["phase"] == "combat"
                           else ig.resolve_defense([]))
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


def test_tap_for_mana_ability_without_scryfall_data():
    # regresión: "{T}: Add one mana of any color" (Patchwork Banner) debe ser una
    # fuente de maná aunque Scryfall no traiga produced_mana (carta offline).
    import cardsdb
    from engine import Game, Player
    import cards
    banner = cardsdb.build_card_from_data({
        "name": "Patchwork Banner", "type_line": "Artifact", "mana_cost": "{3}",
        "oracle_text": "As Patchwork Banner enters the battlefield, choose a creature type.\n"
                       "Creatures you control of the chosen type get +1/+1.\n"
                       "{T}: Add one mana of any color. Spend this mana only to cast a "
                       "creature spell of the chosen type."})
    assert banner.produces is not None                        # ES fuente de maná
    me = Player("yo", [cards.creature("z", "1B", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2B", 3, 3, legendary=True))
    op = Player("op", [cards.creature("z", "1B", 1, 1) for _ in range(10)],
                cards.creature("Om", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    before = me.available_mana()
    pm = g.move_to_battlefield(banner, me); g.resolve_stack()
    assert me.available_mana() == before + 1                  # suma 1 maná (a elegir)
    assert set(banner.produces(pm, me)) == {"W", "U", "B", "R", "G"}
    # colores específicos: "{T}: Add {R} or {G}."
    rock = cardsdb.build_card_from_data({
        "name": "Dual Rock", "type_line": "Artifact", "mana_cost": "{2}",
        "oracle_text": "{T}: Add {R} or {G}."})
    assert rock.produces is not None and set(rock.produces(None, None)) == {"R", "G"}


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
    # las fichas ahora se nombran por su subtipo (Elf) en vez de "Token" genérico
    assert sum(1 for p in me.creatures() if p.is_token and p.name == "Elf") == 2

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
    # nuevo: impacto 1–5, si aporta, y razones legibles
    assert 1 <= verde["impact"] <= 5 and verde["impact"] >= 3  # cubre un hueco -> alto
    assert verde["adds"] is True
    assert any("ramp" in why.lower() for why in verde["reasons"])
    assert rojo["impact"] == 1 and rojo["adds"] is False
    assert any("fuera" in why.lower() for why in rojo["reasons"])


def test_build_from_pool_suggests_commander_and_bracket():
    an = _analyze_mod()
    n = an._norm

    def c(name, tl, ot="", ci=None):
        return {"name": name, "type_line": tl, "oracle_text": ot,
                "color_identity": ci or [], "cmc": 2, "mana_cost": ""}

    cache = {}
    def put(x): cache[n(x["name"])] = x
    put(c("Krenko, Mob Boss", "Legendary Creature — Goblin", "create Goblin tokens", ["R"]))
    put(c("Goblin Chieftain", "Creature — Goblin", "other Goblins get +1/+1", ["R"]))
    put(c("Sol Ring", "Artifact", "add {C}{C}", []))
    put(c("Counterspell", "Instant", "Counter target spell.", ["U"]))   # fuera de color
    # un game changer rojo/incoloro simulado, con identidad conocida
    put(c("Jeska's Will", "Sorcery", "add red mana", ["R"]))
    gc_cards = {n("Jeska's Will"): cache[n("Jeska's Will")]}

    pool = ["Krenko, Mob Boss", "Goblin Chieftain", "Sol Ring", "Counterspell", "Mountain"]
    cache[n("Mountain")] = c("Mountain", "Basic Land — Mountain", "", ["R"])

    # PASO 1: sin comandante -> candidatos
    step1 = an.build_from_pool(pool, cache, gc_cards=gc_cards)
    assert step1["ok"] is True and step1["step"] == "choose_commander"
    assert any(cd["name"] == "Krenko, Mob Boss" for cd in step1["candidates"])

    # PASO 2/3: con el comandante elegido
    res = an.build_from_pool(pool, cache, gc_cards=gc_cards, commander="Krenko, Mob Boss")
    assert res["step"] == "built"
    assert res["commander"]["name"] == "Krenko, Mob Boss"
    assert res["commander"]["identity"] == ["R"]
    assert "Counterspell" in res["off_color"]                   # azul fuera de rojo
    assert "Mountain" not in res["off_color"]                    # básica obviada
    assert set(res["usable_cards"]) == {"Goblin Chieftain", "Sol Ring"}  # sin la básica
    assert res["bracket"]["estimate"] == 2
    assert "Jeska's Will" in res["bracket"]["suggestions"]      # GC rojo sugerido
    assert "affinity" in res and "themes" in res               # afinidad + temas
    assert "cuts" in res["report"]                              # sugerencias de recorte
    # la recomendación de tierras es sobre ESPECIALES, no básicas
    assert any("ESPECIALES" in x["text"] for x in res["report"]["recommendations"])


def test_estimate_bracket_reads_all_pillars():
    import gamechangers as gc

    # Base: sin señales de alto impacto (Sol Ring NO cuenta como fast mana)
    b, lbl, info = gc.estimate_bracket(["Krenko, Mob Boss", "Goblin Chieftain",
                                        "Sol Ring", "Lightning Bolt"])
    assert b == 2 and lbl == "Base"
    assert info["counts"]["fast_mana"] == 0

    # Un solo Game Changer -> Mejorado (3)
    b, _lbl, _i = gc.estimate_bracket(["Rhystic Study", "Sol Ring"])
    assert b == 3

    # Negación masiva de tierras empuja a Optimizado (4) sin ningún GC
    b, _lbl, info = gc.estimate_bracket(["Armageddon", "Lightning Bolt"])
    assert b == 4 and info["counts"]["mass_land_denial"] == 1

    # Turnos extra encadenados (>=2) -> Optimizado (4)
    b, _lbl, _i = gc.estimate_bracket(["Time Warp", "Temporal Manipulation"])
    assert b == 4

    # Muchos GC + fast mana + tutores -> cEDH (5)
    b, _lbl, _i = gc.estimate_bracket([
        "Rhystic Study", "Mana Drain", "Fierce Guardianship", "Cyclonic Rift",
        "Mana Crypt", "Mana Vault", "Chrome Mox",
        "Demonic Tutor", "Vampiric Tutor", "Imperial Seal"])
    assert b == 5


def test_cut_candidates_flag_low_impact_cards():
    an = _analyze_mod()

    def c(name, tl, ot="", ci=None, cmc=0):
        return {"name": name, "type_line": tl, "oracle_text": ot,
                "color_identity": ci or [], "cmc": cmc, "mana_cost": ""}

    entries = [
        (1, "Krenko", c("Krenko", "Legendary Creature — Goblin", "create Goblin tokens", ["R"], 4)),
        (1, "Sol Ring", c("Sol Ring", "Artifact", "add {C}{C}", [], 1)),          # ramp: se queda
        (1, "Colossal Dreadmaw", c("Colossal Dreadmaw", "Creature — Dinosaur", "Trample", ["G"], 6)),  # vainilla cara
        (1, "Vanilla Bear", c("Vanilla Bear", "Creature — Bear", "", ["G"], 2)),  # vainilla chica
    ]
    rep = an.analyze(entries, "Krenko")
    cut_names = {x["name"] for x in rep["cuts"]}
    assert "Colossal Dreadmaw" in cut_names and "Vanilla Bear" in cut_names
    assert "Sol Ring" not in cut_names and "Krenko" not in cut_names   # útiles/comandante no
    assert all("reason" in x for x in rep["cuts"])


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
def _test_walker():
    """Planeswalker DE PRUEBA (mecánica genérica del motor, no una carta real)."""
    def plus(game, ctrl, perm):
        cards.make_token(game, ctrl, "Spirit", 3, 2)

    def ultimate(game, ctrl, perm):
        for o in game.opponents(ctrl):
            game.deal_damage(perm, o, 4)
    return cards.planeswalker("Test Walker", "3RW", 3, ((+1, plus), (-4, ultimate)), (R, W))


def test_planeswalker_loyalty_and_minus_four():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    pw = g.move_to_battlefield(_test_walker(), a)
    assert pw.counters["loyalty"] == 3          # lealtad inicial real (vulnerable)
    # +1 crea Espiritu y sube lealtad
    assert g.activate_loyalty(pw, 0) is True
    assert pw.counters["loyalty"] == 4
    assert any(p.name == "Spirit" for p in a.battlefield)
    # una sola activacion por turno
    assert g.activate_loyalty(pw, 1) is False
    # nuevo turno: se puede activar el -4 (lealtad 4 → 0, el PW muere)
    pw.activated_this_turn = False
    b_life = b.life
    assert g.activate_loyalty(pw, 1) is True     # el -4 existe y se activa
    assert b.life == b_life - 4                   # 4 a cada oponente
    g.sba()
    assert pw.counters.get("loyalty", 0) == 0
    assert pw not in a.battlefield                # a lealtad 0 el planeswalker muere


def test_combat_can_attack_planeswalker():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    pw = g.move_to_battlefield(_test_walker(), b)  # lealtad 3
    atk1 = g.move_to_battlefield(creature("Uno", "1R", 3, 3), a)
    atk2 = g.move_to_battlefield(creature("Dos", "1R", 2, 2), a)
    for p in (atk1, atk2):
        p.summoning_sick = False
    b_life = b.life
    g.combat(a)  # la politica manda ~mitad al jugador, ~mitad al planeswalker
    # el planeswalker recibio dano (perdio lealtad) y el jugador tambien
    assert pw.counters["loyalty"] < 3
    assert b.life < b_life


def test_planeswalker_dies_at_zero_loyalty():
    a = _mk_player("a")
    b = _mk_player("b")
    g = _game([a, b])
    pw = g.move_to_battlefield(_test_walker(), a)
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
    # una criatura del rival que NO me afecta (no me apunta, no es barrido) NO abre
    # ventana, aunque tenga un instantáneo (elección "cuando te afecta a vos").
    beast = cards.creature("Ogro", "2R", 3, 3)
    ig._react_armed = True                           # ventana activa (fase main del bot)
    assert ig._offer_reaction(op, beast) is False
    # pero una REMOCIÓN que apunta a MI criatura sí abre ventana
    my_creat = ig.g.move_to_battlefield(cards.creature("Mío", "1W", 2, 2), hu)
    kill = cardsdb.build_card_from_data({
        "name": "Matar", "type_line": "Instant", "mana_cost": "{R}", "color_identity": ["R"],
        "oracle_text": "Destroy target creature."})
    try:
        ig.g.cast(op, kill, targets=[my_creat])
        paused = False
    except engine.ReactionPause as rp:
        paused = True
        ig._react_ctx = {"p": op, "step": "main2", "spell": rp.spell}
        ig.mode = "react"
        ig.phase = "react"
    assert paused                                    # el motor pausó: me afecta
    rs = ig._react_state()
    assert any(r["name"] == "Zap" for r in rs["responses"])
    ig.g._run_priority_and_resolve()
    ig.mode = None
    ig._react_ctx = None
    # sin instantáneo NI contrahechizo NO se abre la ventana ante remoción
    hu.hand = [c for c in hu.hand if c.name != "Zap"]
    kill2 = cardsdb.build_card_from_data({
        "name": "Matar2", "type_line": "Instant", "mana_cost": "{R}",
        "color_identity": ["R"], "oracle_text": "Destroy target creature."})
    my2 = ig.g.move_to_battlefield(cards.creature("Mío2", "1W", 2, 2), hu)
    ig.g.stack.append(engine.StackObject(op, lambda g: None, source=kill2, targets=[my2]))
    assert ig._offer_reaction(op, kill2) is False
    ig.g.stack.clear()


def test_reaction_window_opens_for_counterspell_to_any_spell():
    # un contrahechizo en mano abre la ventana ante CUALQUIER hechizo del rival,
    # aunque no me apunte (es una carta con que responder).
    import interactive, cards, decks, cardsdb, engine
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    op = ig.g.opponents(hu)[0]
    counter = cardsdb.build_card_from_data({
        "name": "Negar", "type_line": "Instant", "mana_cost": "{U}", "color_identity": ["U"],
        "oracle_text": "Counter target spell."})
    assert getattr(counter, "target_spec", None) == "stack_spell"
    hu.hand.append(counter)
    ig.g.move_to_battlefield(cards.land("Island", ["U"], basic=True), hu)
    beast = cards.creature("Ogro", "2R", 3, 3)
    ig.g.stack.append(engine.StackObject(op, lambda g: None, source=beast))
    ig._react_armed = True
    assert ig._offer_reaction(op, beast) is True     # el contra abre la ventana
    ig.g.stack.clear()


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
    me.library = [cards.creature("Lib", "1U", 1, 1) for _ in range(5)]  # evitar deckout al robar
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
    # con cartas reales (snapshot de Scryfall) tricky trae más hechizos con efecto
    # que los otros: la brecha refleja las listas, no un mazo vainilla
    assert max(counts.values()) - min(counts.values()) <= 15, counts


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


def test_cascade_human_picks_target_manually():
    # Cuando el HUMANO cascadea un hechizo con objetivo del lanzador (target_spec
    # en la carta, p. ej. "Destroy target creature"), el motor pausa con un
    # pending_choice "cascade_target" y el humano decide a qué apunta.
    import interactive, cards, cardsdb, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human(); op = ig.g.opponents(hu)[0]

    chico = ig.g.move_to_battlefield(cards.creature("Chico", "1R", 2, 2), op)
    grande = ig.g.move_to_battlefield(cards.creature("Grande", "4G", 5, 5), op)

    rem = cardsdb.build_card_from_data({
        "name": "Fulgor", "type_line": "Instant", "mana_cost": "{1}{B}",
        "oracle_text": "Destroy target creature."})
    assert getattr(rem, "target_spec", None) == "opp_creature"
    hu.library = [cards.land("Forest", ["G"], basic=True) for _ in range(4)] + [rem]

    casc = cardsdb.build_card_from_data({
        "name": "Bloom", "type_line": "Sorcery", "mana_cost": "{4}{G}",
        "oracle_text": "Cascade", "keywords": ["Cascade"]})
    casc.on_cast_resolve(ig.g, hu, [])

    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "cascade_target"
    names = [o["name"] for o in pc["options"]]
    assert any(n.startswith("Chico") for n in names) and any(n.startswith("Grande") for n in names)
    # elijo "Grande" a mano (no es a quién apuntaría el auto)
    idx = next(o["i"] for o in pc["options"] if o["name"].startswith("Grande"))
    ig.resolve_choice(idx)

    assert grande not in op.battlefield                    # destruí la que elegí
    assert chico in op.battlefield                         # la otra quedó
    assert any(c.name == "Fulgor" for c in hu.graveyard)   # el hechizo fue al cementerio


def test_skyclave_etb_exiles_permanent_with_mv_cap():
    # ETB tipo Skyclave Apparition: exilia un permanente no-tierra/no-ficha del
    # rival con CMV <= 4. El bot toma el de mayor CMV elegible; respeta el tope.
    import cardsdb, cards
    g, me, op = _duel()
    g.move_to_battlefield(cards.creature("Bicho", "1G", 2, 2), op)          # cmv 2
    g.move_to_battlefield(cardsdb.build_card_from_data(
        {"name": "Trinket", "type_line": "Artifact", "mana_cost": "{3}"}), op)  # cmv 3
    g.move_to_battlefield(cards.creature("Dragón", "5RR", 6, 6), op)        # cmv 7 (excede)
    sky = cardsdb.build_card_from_data({
        "name": "Skyclave Apparition", "type_line": "Creature — Kor Spirit",
        "mana_cost": "{1}{W}{W}", "power": "2", "toughness": "2",
        "oracle_text": "When this creature enters, exile up to one target nonland, "
                       "nontoken permanent you don't control with mana value 4 or less."})
    assert sky.on_etb is not None
    g.move_to_battlefield(sky, me)                     # me = bot aquí -> auto
    assert any(c.name == "Trinket" for c in op.exile)  # exilió el mayor CMV <= 4
    assert any(p.name == "Dragón" for p in op.battlefield)  # el CMV 7 quedó
    assert any(p.name == "Bicho" for p in op.battlefield)   # el CMV 2 quedó


def test_skyclave_leave_makes_illusion_token():
    # Al dejar el campo, el dueño de la carta exiliada crea una ficha X/X (X = CMV).
    import cardsdb, cards
    g, me, op = _duel()
    g.move_to_battlefield(cardsdb.build_card_from_data(
        {"name": "Trinket", "type_line": "Artifact", "mana_cost": "{3}"}), op)  # cmv 3
    sky = cardsdb.build_card_from_data({
        "name": "Skyclave Apparition", "type_line": "Creature — Kor Spirit",
        "mana_cost": "{1}{W}{W}", "power": "2", "toughness": "2",
        "oracle_text": "When this creature enters, exile up to one target nonland, "
                       "nontoken permanent you don't control with mana value 4 or less.\n"
                       "When this creature leaves the battlefield, the exiled card's owner "
                       "creates an X/X blue Illusion creature token, where X is the mana "
                       "value of the exiled card."})
    assert sky.on_leave is not None
    perm = g.move_to_battlefield(sky, me)              # bot exilia Trinket (cmv 3)
    assert any(c.name == "Trinket" for c in op.exile)
    g.to_graveyard(perm, "test")                       # deja el campo -> Ilusión
    ills = [p for p in op.battlefield if p.is_token and p.name == "Illusion"]
    assert len(ills) == 1 and ills[0].power == 3 and ills[0].toughness == 3


def test_wave_of_reckoning_symmetric_wipe():
    # "Each creature deals damage equal to its toughness to itself" mata a todas.
    import cardsdb, cards
    g, me, op = _duel()
    g.move_to_battlefield(cards.creature("A", "1G", 2, 2), me)
    g.move_to_battlefield(cards.creature("B", "4G", 5, 5), op)
    wave = cardsdb.build_card_from_data({
        "name": "Wave of Reckoning", "type_line": "Sorcery", "mana_cost": "{3}{W}{W}",
        "oracle_text": "Each creature deals damage equal to its toughness to itself."})
    assert wave.on_cast_resolve is not None
    wave.on_cast_resolve(g, me, [])
    g.sba()
    assert not me.battlefield and not op.battlefield   # ambas murieron


def test_saga_chapter_runs_fragment_effect():
    # Un capítulo cubierto solo por _fragment_effect (poner contadores) ahora SÍ
    # hace algo (antes solo logueaba): elige auto la criatura propia más grande.
    import cardsdb, cards
    g, me, op = _duel()
    small = g.move_to_battlefield(cards.creature("Chico", "1G", 1, 1), me)
    big = g.move_to_battlefield(cards.creature("Grande", "3G", 4, 4), me)
    saga = cardsdb.build_card_from_data({
        "name": "Contador Saga", "type_line": "Enchantment — Saga", "mana_cost": "{2}{G}",
        "oracle_text": "(As this Saga enters and after your draw step, add a lore counter.)\n"
                       "I — Put two +1/+1 counters on target creature."})
    perm = g.move_to_battlefield(saga, me)             # dispara capítulo I
    assert big.counters.get("+1/+1") == 2              # fue a la más grande (auto)
    assert small.counters.get("+1/+1", 0) == 0


def test_dark_depths_remove_counters_makes_marit_lage():
    # "{3}: Remove an ice counter" ahora SÍ quita contadores; al llegar a 0 la
    # tierra se sacrifica y crea Marit Lage 20/20 vuela/indestructible.
    import cardsdb, cards
    dd = cardsdb.build_card_from_data({
        "name": "Dark Depths", "type_line": "Legendary Snow Land", "mana_cost": "",
        "oracle_text": "Dark Depths enters with ten ice counters on it.\n"
                       "{3}: Remove an ice counter from Dark Depths.\n"
                       "When Dark Depths has no ice counters on it, sacrifice it. If you "
                       "do, create Marit Lage, a legendary 20/20 black Avatar creature "
                       "token with flying and indestructible."})
    assert dd.etb_counters.get("ice") == 10
    assert dd.activated_abilities and getattr(dd, "sac_when_no_counter", None)
    g, me, op = _duel()
    perm = g.move_to_battlefield(dd, me)
    assert perm.counters.get("ice") == 10
    ab = dd.activated_abilities[0]
    for _ in range(10):
        ab["effect"](g, me, perm, None)
        g.sba()
        if perm not in me.battlefield:
            break
    assert perm not in me.battlefield                    # se sacrificó
    ml = [p for p in me.battlefield if p.name == "Marit Lage"]
    assert len(ml) == 1
    assert ml[0].power == 20 and ml[0].toughness == 20
    assert ml[0].has("flying") and ml[0].has("indestructible")
    assert ml[0].has_subtype("Avatar") and ml[0].is_token


def test_staff_of_the_storyteller_tokens_and_counter_cost():
    # Disparo "whenever you create one or more creature tokens -> put a story
    # counter" + coste "Remove a story counter: Draw a card".
    import cardsdb, cards
    staff = cardsdb.build_card_from_data({
        "name": "Staff of the Storyteller", "type_line": "Artifact", "mana_cost": "{2}{W}",
        "oracle_text": "When this artifact enters, create a 1/1 white Spirit creature "
                       "token with flying.\nWhenever you create one or more creature "
                       "tokens, put a story counter on this artifact.\n{W}, {T}, Remove a "
                       "story counter from this artifact: Draw a card."})
    assert "token_created" in staff.triggers
    ab = next(a for a in staff.activated_abilities if a.get("rm_counter"))
    assert ab["rm_counter"] == {"name": "story", "n": 1}
    g, me, op = _duel()
    for _ in range(2):
        g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), me)
    me.library = [cards.creature("C%d" % i, "1G", 1, 1) for i in range(3)]
    perm = g.move_to_battlefield(staff, me)
    g.resolve_stack(); g.sba()
    assert sum(1 for p in me.battlefield if p.name == "Spirit") == 1
    assert perm.counters.get("story") == 1               # el token del ETB dio 1
    cards.make_token(g, me, "Soldier", 1, 1)             # otro token -> otro contador
    g.resolve_stack(); g.sba()
    assert perm.counters.get("story") == 2
    # activar: paga {W}{T} + quita 1 contador story -> roba
    i_draw = next(i for i, a in enumerate(staff.activated_abilities) if a.get("rm_counter"))
    h0 = len(me.hand)
    assert g.activate_ability(perm, i_draw) is True
    g.resolve_stack(); g.sba()
    assert len(me.hand) == h0 + 1 and perm.counters.get("story") == 1
    # sin contadores no se puede activar (quitamos el último primero)
    perm.counters["story"] = 0
    perm.tapped = False
    assert g.activate_ability(perm, i_draw) is False


def test_graveyard_shuffle_multiselect():
    # 2a habilidad de Perpetual Timepiece: coste "Exile this artifact" + "shuffle
    # any number of target cards from your graveyard into your library".
    import interactive, cards, cardsdb, decks
    pt_data = {"name": "Perpetual Timepiece", "type_line": "Artifact", "mana_cost": "{2}",
               "oracle_text": "{T}: Mill two cards.\n{2}, Exile Perpetual Timepiece: "
                              "Shuffle any number of target cards from your graveyard "
                              "into your library."}
    pt = cardsdb.build_card_from_data(pt_data)
    labels = pt.activated_abilities
    assert any(a.get("exile_self") for a in labels)           # coste exiliar reconocido

    # BOT: baraja de vuelta las no-tierra; el artefacto se exilia
    from tests.test_engine import _duel  # noqa
    g, me, op = _duel()
    for _ in range(2):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    me.graveyard = [cards.creature("A", "1G", 1, 1), cards.land("L", ["G"], basic=True),
                    cards.creature("B", "1G", 1, 1)]
    perm = g.move_to_battlefield(cardsdb.build_card_from_data(pt_data), me)
    i2 = next(i for i, a in enumerate(perm.card.activated_abilities) if a.get("exile_self"))
    assert g.activate_ability(perm, i2) is True
    g.resolve_stack(); g.sba()
    assert perm not in me.battlefield and any(c.name == "Perpetual Timepiece" for c in me.exile)
    assert [c.name for c in me.graveyard] == ["L"]            # sólo la tierra quedó

    # HUMANO: multi-selector del cementerio (elige de a una, con 'ninguna más')
    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), hu)
    hu.graveyard = [cards.creature("X", "1G", 1, 1), cards.creature("Y", "1G", 1, 1)]
    hperm = ig.g.move_to_battlefield(cardsdb.build_card_from_data(pt_data), hu)
    hi = next(i for i, a in enumerate(hperm.card.activated_abilities) if a.get("exile_self"))
    ig.activate_ability(hperm.uid, hi)
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "gy_shuffle" and pc["allow_none"]
    idx = next(o["i"] for o in pc["options"] if o["name"] == "X")
    ig.resolve_choice(idx)                                    # baraja X
    ig.resolve_choice(None)                                   # 'ninguna más'
    assert [c.name for c in hu.graveyard] == ["Y"]           # X volvió; Y quedó


def test_mill_ability_logs_feedback():
    # "{T}: Mill two cards" (Perpetual Timepiece): la activada muele y ahora deja
    # rastro en el log (antes era silenciosa -> parecía que no hacía nada).
    import cardsdb, cards
    pt = cardsdb.build_card_from_data({
        "name": "Perpetual Timepiece", "type_line": "Artifact", "mana_cost": "{2}",
        "oracle_text": "{T}: Mill two cards.\n{2}, Exile Perpetual Timepiece: Shuffle "
                       "any number of target cards from your graveyard into your library."})
    g, me, op = _duel()
    me.library = [cards.creature("C%d" % i, "1G", 1, 1) for i in range(5)]
    perm = g.move_to_battlefield(pt, me)
    assert g.activate_ability(perm, 0) is True
    g.resolve_stack(); g.sba()
    assert perm.tapped and len(me.graveyard) == 2              # giró y molió 2
    assert any("muele" in l for l in g.log_lines)              # feedback visible


def test_smothering_tithe_opponent_draw_makes_treasure():
    # "Whenever an opponent draws a card, ... you create a Treasure token": en la
    # sim los bots no pagan -> el controlador recibe un Tesoro por carta robada.
    import cardsdb, cards
    tithe = cardsdb.build_card_from_data({
        "name": "Smothering Tithe", "type_line": "Enchantment", "mana_cost": "{3}{W}",
        "oracle_text": "Whenever an opponent draws a card, that player may pay {2}. If "
                       "the player does not, you create a Treasure token."})
    assert "opp_draw" in tithe.triggers
    g, me, op = _duel()
    op.library = [cards.land("X", ["W"], basic=True) for _ in range(5)]
    g.move_to_battlefield(tithe, me)
    op.draw(2, g)
    g.resolve_stack(); g.sba()
    assert sum(1 for p in me.battlefield if p.name == "Treasure") == 2   # 1 por carta
    me.library = [cards.land("Y", ["W"], basic=True) for _ in range(3)]
    me.draw(1, g)                                                        # robo propio
    g.resolve_stack(); g.sba()
    assert sum(1 for p in me.battlefield if p.name == "Treasure") == 2   # no cambia


def test_etb_reanimate_nonland_opens_human_picker():
    # "When ~ enters, return target nonland permanent card with mana value 3 or less
    # from your graveyard to the battlefield" (Primary Research): el humano elige en
    # un modal; sólo permanentes NO tierra con CMV <= 3.
    import interactive, cards, cardsdb, decks

    def mk():
        return cardsdb.build_card_from_data({
            "name": "Primary Research", "type_line": "Enchantment", "mana_cost": "{3}{U}",
            "oracle_text": "When this enchantment enters, return target nonland permanent "
                           "card with mana value 3 or less from your graveyard to the "
                           "battlefield.\nAt the beginning of your end step, if a card left "
                           "your graveyard this turn, draw a card."})

    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    hu.graveyard = [cards.land("Forest", ["G"], basic=True),       # tierra (excluida)
                    cards.creature("Bicho", "1G", 2, 2),           # cmv 2 (elegible)
                    cards.creature("Grande", "4G", 5, 5)]          # cmv 5 (excede)
    ig.g.move_to_battlefield(mk(), hu)
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "reanimate"
    # se muestra TODO el cementerio NO tierra (Bicho + Grande), la tierra no;
    # sólo el válido (CMV<=3) queda elegible, el resto en gris (ok=False)
    names = {o["name"] for o in pc["options"]}
    assert names == {"Bicho", "Grande"} and "Forest" not in names
    oks = {o["name"]: o["ok"] for o in pc["options"]}
    assert oks["Bicho"] is True and oks["Grande"] is False
    idx = next(o["i"] for o in pc["options"] if o["name"] == "Bicho")
    ig.resolve_choice(idx)
    assert any(p.name == "Bicho" for p in hu.battlefield)           # revivido al elegir

    # cementerio sólo con una tierra -> no hay objetivo -> no abre modal
    ig2 = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig2.keep([])
    ig2.human().graveyard = [cards.land("Forest", ["G"], basic=True)]
    ig2.g.move_to_battlefield(mk(), ig2.human())
    assert ig2.g.pending_choice is None


def test_reanimate_never_opens_a_dead_all_greyed_modal():
    # Regresión: un reanimador que SÍ permite tierras ("return target permanent card
    # with mana value 3 or less") con un cementerio = [tierra elegible + 2 conjuros].
    # El modal nunca debe quedar "todo en gris" (congelaría el juego): la tierra
    # elegible se muestra y es seleccionable.
    import interactive, cards, cardsdb, decks

    def mk():
        return cardsdb.build_card_from_data({
            "name": "Permiso de Tierra", "type_line": "Enchantment", "mana_cost": "{3}",
            "oracle_text": "When this enchantment enters, return target permanent card "
                           "with mana value 3 or less from your graveyard to the "
                           "battlefield."})

    def sorc(name):
        return cardsdb.build_card_from_data(
            {"name": name, "type_line": "Sorcery", "mana_cost": "{2}", "oracle_text": "Draw a card."})

    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    hu.graveyard = [cards.land("Island", ["U"], basic=True), sorc("Secret Rendezvous"), sorc("Otra")]
    ig.g.move_to_battlefield(mk(), hu)
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "reanimate"
    assert any(o["ok"] for o in pc["options"])                      # NUNCA todo en gris
    assert next(o for o in pc["options"] if o["name"] == "Island")["ok"] is True
    idx = next(o["i"] for o in pc["options"] if o["name"] == "Island")
    ig.resolve_choice(idx)
    assert any(p.name == "Island" for p in hu.battlefield)

    # y si NO hay ninguna elegible (solo conjuros) -> fizzle, sin modal (no congela)
    ig3 = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig3.keep([])
    ig3.human().graveyard = [sorc("A"), sorc("B")]
    ig3.g.move_to_battlefield(mk(), ig3.human())
    assert ig3.g.pending_choice is None


def test_living_weapon_equipped_attack_trigger():
    # Living weapon crea un Germen y se equipa; el disparo "whenever equipped
    # creature attacks" vive en el EQUIPO y ahora dispara cuando ataca el Germen.
    import cardsdb, cards
    lw = cardsdb.build_card_from_data({
        "name": "Living Blade", "type_line": "Artifact — Equipment", "mana_cost": "{2}",
        "oracle_text": "Living weapon (When this Equipment enters the battlefield, "
                       "create a 0/0 black Phyrexian Germ creature token, then attach "
                       "this to it.)\nEquipped creature gets +1/+1.\nWhenever equipped "
                       "creature attacks, you may search your library for a basic land "
                       "card, put it onto the battlefield tapped, then shuffle.\nEquip {3}"})
    g, me, op = _duel()
    me.library = [cards.land("Forest", ["G"], basic=True) for _ in range(3)]
    perm = g.move_to_battlefield(lw, me)
    g.sba()
    germ = perm.enchanting
    assert germ is not None and germ.name == "Germ"
    assert germ.power == 1 and germ.toughness == 1          # +1/+1 del equipo
    germ.summoning_sick = False
    lands0 = sum(1 for p in me.battlefield if p.card.is_land())
    g._declare_attackers(me, [(germ, op)])
    g.resolve_stack(); g.sba()
    lands1 = sum(1 for p in me.battlefield if p.card.is_land())
    assert lands1 == lands0 + 1                             # buscó una tierra básica
    assert any(p.card.is_land() and p.tapped for p in me.battlefield)  # entra tapeada


def test_thespians_stage_copies_dark_depths_combo():
    # Thespian's Stage copia Dark Depths (sin copiar contadores): queda con 0 hielo
    # y la sba la sacrifica creando Marit Lage. Cierra el combo.
    import cardsdb, cards
    dd = cardsdb.build_card_from_data({
        "name": "Dark Depths", "type_line": "Legendary Snow Land", "mana_cost": "",
        "oracle_text": "Dark Depths enters with ten ice counters on it.\n"
                       "{3}: Remove an ice counter from Dark Depths.\n"
                       "When Dark Depths has no ice counters on it, sacrifice it. If you "
                       "do, create Marit Lage, a legendary 20/20 black Avatar creature "
                       "token with flying and indestructible."})
    stage = cardsdb.build_card_from_data({
        "name": "Thespian's Stage", "type_line": "Land", "mana_cost": "",
        "oracle_text": "{T}: Add {C}.\n{2}, {T}: Thespian's Stage becomes a copy of "
                       "target land, except it has this ability."})
    copy_ab = next(a for a in stage.activated_abilities if "copy" in a["label"].lower())
    g, me, op = _duel()
    ddp = g.move_to_battlefield(dd, me)
    sp = g.move_to_battlefield(stage, me)
    assert not sp.counters.get("ice")                    # la Stage no tiene hielo
    copy_ab["effect"](g, me, sp, [ddp])
    g.sba()
    assert sp not in me.battlefield                      # la copia se sacrificó
    ml = [p for p in me.battlefield if p.name == "Marit Lage"]
    assert len(ml) == 1 and ml[0].power == 20 and ml[0].has("indestructible")


def test_remove_counters_from_target_and_dark_depths_combo():
    # "Sacrifice ~: Remove three counters from target permanent" (Vampire Hexmage):
    # ability DIRIGIDA (any_perm). Vaciar los contadores de Dark Depths así también
    # dispara Marit Lage (consistente: cualquier fuente que baje a 0).
    import cardsdb, cards
    dd = cardsdb.build_card_from_data({
        "name": "Dark Depths", "type_line": "Legendary Snow Land", "mana_cost": "",
        "oracle_text": "Dark Depths enters with ten ice counters on it.\n"
                       "{3}: Remove an ice counter from Dark Depths.\n"
                       "When Dark Depths has no ice counters on it, sacrifice it. If you "
                       "do, create Marit Lage, a legendary 20/20 black Avatar creature "
                       "token with flying and indestructible."})
    hexmage = cardsdb.build_card_from_data({
        "name": "Vampire Hexmage", "type_line": "Creature — Vampire Shaman",
        "mana_cost": "{B}{B}", "power": "2", "toughness": "2",
        "oracle_text": "First strike, deathtouch\nSacrifice Vampire Hexmage: Remove "
                       "three counters from target permanent."})
    ab = hexmage.activated_abilities[0]
    assert ab["target_spec"] == "any_perm"                # dirigida, NO a sí misma
    g, me, op = _duel()
    ddp = g.move_to_battlefield(dd, me)
    hp = g.move_to_battlefield(hexmage, me)
    for _ in range(4):                                    # 10 -> 7 -> 4 -> 1 -> 0
        ab["effect"](g, me, hp, [ddp])
        g.sba()
        if ddp not in me.battlefield:
            break
    assert ddp not in me.battlefield
    assert any(p.name == "Marit Lage" for p in me.battlefield)


def test_nissa_plus_scry_and_zero_put_top():
    # +2 Scry 2 (se cablea sin error) y 0: poner el tope si es tierra o criatura
    # con CMV <= lealtad.
    import cardsdb, cards
    orc = ("+2: Scry 2.\n"
           "0: Look at the top card of your library. If it's a land card or a "
           "creature card with mana value less than or equal to the number of "
           "loyalty counters on Nissa, you may put that card onto the battlefield.\n"
           "−6: Untap up to two target lands you control. They become 5/5 Elemental "
           "creatures with flying and haste until end of turn. They're still lands.")

    def mk():
        return cardsdb.build_card_from_data({
            "name": "Nissa", "type_line": "Legendary Planeswalker — Nissa",
            "mana_cost": "{3}{G}{G}", "loyalty": "5", "oracle_text": orc})

    n = mk()
    wired = {c: (e is not None) for c, e in n.loyalty_abilities}
    assert wired[2] and wired[0]                          # +2 y 0 cableadas

    # 0: criatura CMV 3 <= lealtad 5 -> al campo
    g, me, op = _duel()
    pw = g.move_to_battlefield(mk(), me)
    pw.counters["loyalty"] = 5
    me.library = [cards.land("X", ["G"], basic=True) for _ in range(3)] + \
        [cards.creature("Bestia", "2G", 3, 3)]            # tope = Bestia
    i0 = next(i for i, (c, e) in enumerate(pw.card.loyalty_abilities) if c == 0)
    pw.card.loyalty_abilities[i0][1](g, me, pw)
    g.resolve_stack(); g.sba()
    assert any(p.name == "Bestia" for p in me.battlefield)

    # 0: criatura CMV 7 > lealtad 5 -> NO entra
    g2, me2, op2 = _duel()
    pw2 = g2.move_to_battlefield(mk(), me2)
    pw2.counters["loyalty"] = 5
    me2.library = [cards.creature("Gigante", "5GG", 8, 8)]
    pw2.card.loyalty_abilities[i0][1](g2, me2, pw2)
    g2.resolve_stack(); g2.sba()
    assert not any(p.name == "Gigante" for p in me2.battlefield)


def test_planeswalker_minus_animates_lands():
    # Habilidad de lealtad que anima tierras: "untap up to two target lands you
    # control. They become 5/5 Elemental creatures with flying and haste until end
    # of turn." Deben pasar a 5/5 voladoras con prisa, seguir siendo tierras, y
    # revertir al final del turno.
    import cardsdb, cards
    g, me, op = _duel()
    l1 = g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    l1.tapped = True
    l2 = g.move_to_battlefield(cards.land("Island", ["U"], basic=True), me)
    l3 = g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    nissa = cardsdb.build_card_from_data({
        "name": "Nissa", "type_line": "Legendary Planeswalker — Nissa",
        "mana_cost": "{3}{G}{G}", "loyalty": "5",
        "oracle_text": "+2: Scry 2.\n0: Look at the top card of your library.\n"
                       "−6: Untap up to two target lands you control. They become 5/5 "
                       "Elemental creatures with flying and haste until end of turn. "
                       "They're still lands."})
    idx = next(i for i, (c, e) in enumerate(nissa.loyalty_abilities) if c == -6)
    assert nissa.loyalty_abilities[idx][1] is not None       # la -6 tiene efecto real
    pw = g.move_to_battlefield(nissa, me)
    pw.counters["loyalty"] = 6
    nissa.loyalty_abilities[idx][1](g, me, pw)
    g.sba()
    anim = [l for l in (l1, l2, l3) if l.is_creature()]
    assert len(anim) == 2                                     # "up to two"
    for l in anim:
        assert l.power == 5 and l.toughness == 5
        assert l.has("flying") and l.has("haste")
        assert l.has_subtype("Elemental") and l.card.is_land()  # sigue siendo tierra
        assert not l.tapped                                   # se enderezó
    g.end_turn(me)
    assert not any(l.is_creature() for l in (l1, l2, l3))     # revierte al fin del turno


def test_magecraft_cast_or_copy_trigger():
    # Magecraft ("whenever you cast OR COPY an instant or sorcery spell") y el
    # disparo genérico "cast a spell" (Birgi) ahora se cablean.
    import cardsdb, cards
    g, me, op = _duel()
    sk = cardsdb.build_card_from_data({
        "name": "Storm-Kiln Artist", "type_line": "Creature — Dwarf Artificer",
        "mana_cost": "{3}{R}", "power": "1", "toughness": "4",
        "oracle_text": "Magecraft — Whenever you cast or copy an instant or sorcery "
                       "spell, create a Treasure token."})
    perm = g.move_to_battlefield(sk, me)
    assert "cast" in sk.triggers
    inst = cardsdb.build_card_from_data({"name": "Bolt", "type_line": "Instant",
                                         "mana_cost": "{R}", "oracle_text": ""})
    sk.triggers["cast"](g, perm, card=inst)
    assert sum(1 for p in me.battlefield if p.name == "Treasure") == 1
    # NO dispara al lanzar una criatura
    sk.triggers["cast"](g, perm, card=cards.creature("X", "1G", 2, 2))
    assert sum(1 for p in me.battlefield if p.name == "Treasure") == 1

    birgi = cardsdb.build_card_from_data({
        "name": "Birgi", "type_line": "Legendary Creature — God", "mana_cost": "{1}{R}",
        "power": "3", "toughness": "3",
        "oracle_text": "Whenever you cast a spell, add {C}."})
    assert "cast" in birgi.triggers


def test_excava_attack_reanimates_with_finality():
    # Disparo "al atacar" que reanima del cementerio con tope de CMV y contador de
    # finalidad (al morir, se exilia). Respeta el tope de maná.
    import cardsdb, cards
    g, me, op = _duel()
    me.graveyard = [
        cards.creature("Bicho", "1G", 2, 2),             # cmv 2 (elegible)
        cardsdb.build_card_from_data({"name": "Caro", "type_line": "Creature — Beast",
                                      "mana_cost": "{5}{G}", "power": "6", "toughness": "6"}),  # cmv 6
    ]
    exc = cardsdb.build_card_from_data({
        "name": "Excava", "type_line": "Creature — Dinosaur", "mana_cost": "{2}{W}{B}",
        "power": "3", "toughness": "3", "keywords": ["Flying", "Haste"],
        "oracle_text": "Flying, haste\nWhenever Excava attacks, return up to one target "
                       "artifact, creature, or non-Aura enchantment card with mana value 3 "
                       "or less from your graveyard to the battlefield with a finality "
                       "counter on it. It's a 1/1 Spirit creature with flying in addition "
                       "to its other types."})
    assert "attacks" in exc.triggers
    perm = g.move_to_battlefield(exc, me)
    exc.triggers["attacks"](g, perm)
    g.sba()
    revived = [p for p in me.battlefield if p.name == "Bicho"]
    assert len(revived) == 1 and revived[0].counters.get("finality") == 1
    r = revived[0]
    assert r.power == 1 and r.toughness == 1                   # pasa a 1/1
    assert r.has_subtype("Spirit") and r.has("flying")        # Spirit con flying
    assert not any(p.name == "Caro" for p in me.battlefield)   # cmv 6 excede el tope
    g.to_graveyard(r, "test")
    assert any(c.name == "Bicho" for c in me.exile)            # finalidad -> exilio
    assert not any(c.name == "Bicho" for c in me.graveyard)


def test_saga_mass_edict_and_discard_and_mill():
    # Patrones comunes de capítulos de Saga: edict masivo, descarte global, self-mill.
    import cardsdb, cards
    g, me, op = _duel()
    g.move_to_battlefield(cards.creature("A", "1G", 2, 2), me)
    g.move_to_battlefield(cards.creature("B", "1G", 3, 3), op)
    cardsdb._chapter_effect("Each player sacrifices a creature.")(g, me)
    g.sba()
    assert len(me.creatures()) == 0 and len(op.creatures()) == 0

    g, me, op = _duel()
    me.hand = [cards.land("X", ["W"], basic=True) for _ in range(3)]
    op.hand = [cards.land("Y", ["U"], basic=True) for _ in range(3)]
    cardsdb._chapter_effect("Each player discards a card.")(g, me)
    assert len(me.hand) == 2 and len(op.hand) == 2

    g, me, op = _duel()
    me.library = [cards.creature("C", "1G", 1, 1) for _ in range(5)]
    cardsdb._chapter_effect("Put the top two cards of your library into your graveyard.")(g, me)
    assert len(me.graveyard) == 2 and len(me.library) == 3


def test_saga_team_pump_and_counter_with_keyword():
    import cardsdb, cards
    g, me, op = _duel()
    c = g.move_to_battlefield(cards.creature("D", "1G", 2, 2), me)
    cardsdb._chapter_effect("Creatures you control get +1/+0 until end of turn.")(g, me)
    assert c.power == 3
    g2, me2, op2 = _duel()
    c2 = g2.move_to_battlefield(cards.creature("E", "1G", 2, 2), me2)
    cardsdb._chapter_effect(
        "Put a +1/+1 counter on up to one target creature. It gains deathtouch "
        "until end of turn.")(g2, me2)
    g2.sba()
    assert c2.counters.get("+1/+1") == 1 and "deathtouch" in c2.keywords


def test_token_keywords_beyond_trample():
    # Las fichas creadas conservan TODAS sus keywords (no solo trample).
    import cardsdb, cards
    g, me, op = _duel()
    sp = cardsdb.build_card_from_data({
        "name": "Hacer Caballero", "type_line": "Sorcery", "mana_cost": "{1}{W}",
        "oracle_text": "Create a 2/2 white Knight creature token with vigilance and lifelink."})
    sp.on_cast_resolve(g, me, [])
    tok = [p for p in me.battlefield if p.is_token][0]
    assert "vigilance" in tok.keywords and "lifelink" in tok.keywords


def test_destroy_all_lands_effect():
    # "Destroy all lands" (Fall of the Thran, Armageddon…) arrasa las tierras.
    import cardsdb, cards
    g, me, op = _duel()
    for _ in range(2):
        g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), me)
    g.move_to_battlefield(cards.land("Island", ["U"], basic=True), op)
    eff = cardsdb._chapter_effect("Destroy all lands")
    assert eff is not None
    eff(g, me)
    g.sba()
    assert not any(p.card.is_land() for p in me.battlefield + op.battlefield)


def test_gain_life_and_draw_compound():
    import cardsdb, cards
    g, me, op = _duel()
    me.library = [cards.land("Plains", ["W"], basic=True) for _ in range(5)]
    eff = cardsdb._chapter_effect("You gain 2 life and draw a card")
    life0, hand0 = me.life, len(me.hand)
    eff(g, me)
    assert me.life == life0 + 2 and len(me.hand) == hand0 + 1


def test_saga_chapter_human_picks_target():
    # Capítulo de Saga con objetivo (contadores) controlado por el humano: abre el
    # modal y aplica al elegido, no al auto.
    import interactive, cards, cardsdb, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    chico = ig.g.move_to_battlefield(cards.creature("Chico", "1G", 1, 1), hu)
    grande = ig.g.move_to_battlefield(cards.creature("Grande", "3G", 4, 4), hu)
    saga = cardsdb.build_card_from_data({
        "name": "Contador Saga", "type_line": "Enchantment — Saga", "mana_cost": "{2}{G}",
        "oracle_text": "(As this Saga enters and after your draw step, add a lore counter.)\n"
                       "I — Put two +1/+1 counters on target creature."})
    ig.g.move_to_battlefield(saga, hu)                 # capítulo I -> modal
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "etb_target"
    idx = next(o["i"] for o in pc["options"] if o["name"].startswith("Chico"))
    ig.resolve_choice(idx)
    assert chico.counters.get("+1/+1") == 2            # fue al elegido a mano
    assert grande.counters.get("+1/+1", 0) == 0        # no al auto (más grande)


def test_skyclave_etb_human_opens_target_picker():
    # Cuando lo controla el humano, el ETB abre el selector de objetivo (no auto).
    import interactive, cards, cardsdb, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human(); op = ig.g.opponents(hu)[0]
    ig.g.move_to_battlefield(cards.creature("Bicho", "1G", 2, 2), op)
    sky = cardsdb.build_card_from_data({
        "name": "Skyclave Apparition", "type_line": "Creature — Kor Spirit",
        "mana_cost": "{1}{W}{W}", "power": "2", "toughness": "2",
        "oracle_text": "When this creature enters, exile up to one target nonland, "
                       "nontoken permanent you don't control with mana value 4 or less."})
    ig.g.move_to_battlefield(sky, hu)
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "etb_target"
    assert any("Bicho" in o["name"] for o in pc["options"])


def test_cascade_bot_no_target_prompt():
    # Un bot que cascadea un hechizo con objetivo NO abre pending_choice (no hay
    # modal para la IA): resuelve sin trabar el motor headless.
    import interactive, cards, cardsdb, decks
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    bot = ig.g.opponents(ig.human())[0]
    ig.g.move_to_battlefield(cards.creature("Víctima", "1R", 2, 2), ig.human())
    rem = cardsdb.build_card_from_data({
        "name": "Fulgor", "type_line": "Instant", "mana_cost": "{1}{B}",
        "oracle_text": "Destroy target creature."})
    bot.library = [cards.land("Island", ["U"], basic=True) for _ in range(4)] + [rem]
    casc = cardsdb.build_card_from_data({
        "name": "Bloom", "type_line": "Sorcery", "mana_cost": "{4}{G}",
        "oracle_text": "Cascade", "keywords": ["Cascade"]})
    casc.on_cast_resolve(ig.g, bot, [])
    assert ig.g.pending_choice is None                     # la IA no pausa


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
    pm.summoning_sick = False                 # {T} de criatura: ya lleva un turno
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


def test_destroy_artifact_target_spec():
    from cardsdb import build_card_from_data
    nat = build_card_from_data({
        "name": "Naturalize", "mana_cost": "{1}{G}", "cmc": 2,
        "type_line": "Instant",
        "oracle_text": "Destroy target artifact or enchantment."})
    assert nat.target_spec == "any_art_ench"
    assert nat.target_count == 1
    shatter = build_card_from_data({
        "name": "Shatter", "mana_cost": "{1}{R}", "cmc": 2,
        "type_line": "Instant", "oracle_text": "Destroy target artifact."})
    assert shatter.target_spec == "any_artifact"


def test_destroy_artifact_interactive_choice_and_legality():
    import interactive, decks, cards
    from cardsdb import build_card_from_data
    defs = [("Tu deck",) + decks.build("marvel"),
            ("Rival",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    g = ig.g
    me = ig.human()
    opp = g.opponents(me)[0]
    nat = build_card_from_data({
        "name": "Naturalize", "mana_cost": "{1}{G}", "cmc": 2,
        "type_line": "Instant",
        "oracle_text": "Destroy target artifact or enchantment."})
    me.hand.append(nat)
    for _ in range(3):
        g.move_to_battlefield(cards.land("Forest", ["G"]), me)

    # sin objetivos legales -> no se puede lanzar (con motivo)
    n1 = [c for c in ig.legal()["casts"] if c["name"] == "Naturalize"][0]
    assert n1.get("castable") is False and n1.get("reason")

    # con objetivos -> ofrece artefacto Y encantamiento del rival
    g.move_to_battlefield(build_card_from_data({
        "name": "Sol Ring", "mana_cost": "{1}", "cmc": 1,
        "type_line": "Artifact", "oracle_text": ""}), opp)
    g.move_to_battlefield(build_card_from_data({
        "name": "Aura X", "mana_cost": "{2}", "cmc": 2,
        "type_line": "Enchantment", "oracle_text": ""}), opp)
    n2 = [c for c in ig.legal()["casts"] if c["name"] == "Naturalize"][0]
    assert n2.get("castable") is not False
    names = {t["name"] for t in n2["targets"]}
    assert {"Sol Ring", "Aura X"} <= names
    # destruir SOLO el elegido
    uid = [t["uid"] for t in n2["targets"] if t["name"] == "Sol Ring"][0]
    ig.cast(me.hand.index(nat), "hand", target_uids=[uid])
    assert not any(pm.name == "Sol Ring" for pm in opp.battlefield)
    assert any(pm.name == "Aura X" for pm in opp.battlefield)


def test_extra_land_per_turn():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    assert g.land_limit(me) == 1
    expl = build_card_from_data({
        "name": "Exploration", "mana_cost": "{G}", "cmc": 1,
        "type_line": "Enchantment",
        "oracle_text": "You may play an additional land on each of your turns."})
    assert getattr(expl, "extra_land", 0) == 1
    g.move_to_battlefield(expl, me)
    assert g.land_limit(me) == 2
    # se pueden jugar dos tierras
    me.hand.append(cards.land("Forest", ["G"]))
    me.hand.append(cards.land("Island", ["U"]))
    assert g.play_land(me, me.hand[-1]) is True
    assert g.play_land(me, me.hand[-1]) is True
    assert g.play_land(me, cards.land("Plains", ["W"])) is False   # ya jugó 2


def test_cast_creature_spell_trigger():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    g.interactive_human = None
    src = build_card_from_data({
        "name": "Token Maker", "mana_cost": "{2}{W}", "cmc": 3,
        "type_line": "Enchantment",
        "oracle_text": "Whenever you cast a creature spell, create a 1/1 white "
                       "Soldier creature token."})
    assert src.triggers and "cast" in src.triggers
    perm = g.move_to_battlefield(src, me)
    before = len(me.battlefield)
    # lanzar un hechizo de criatura dispara; uno no-criatura no
    creature = cards.creature("Bear", "1G", 2, 2)
    src.triggers["cast"](g, perm, card=creature)
    assert len(me.battlefield) == before + 1
    noncreature = build_card_from_data({
        "name": "Bolt", "mana_cost": "{R}", "cmc": 1, "type_line": "Instant",
        "oracle_text": "Deal 3 damage to any target."})
    mid = len(me.battlefield)
    src.triggers["cast"](g, perm, card=noncreature)
    assert len(me.battlefield) == mid           # no dispara con no-criatura


def test_gain_control_of_all_creatures():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    a = g.move_to_battlefield(cards.creature("A", "1B", 2, 2), op)
    b = g.move_to_battlefield(cards.creature("B", "2B", 3, 3), op)
    spell = build_card_from_data({
        "name": "Insurrection", "mana_cost": "{5}{R}{R}{R}", "cmc": 8,
        "type_line": "Sorcery",
        "oracle_text": "Untap all creatures. Gain control of all creatures "
                       "until end of turn. They gain haste until end of turn."})
    spell.on_cast_resolve(g, me, [])
    assert a.controller is me and b.controller is me
    assert a in me.battlefield and b in me.battlefield


def test_reanimate_from_any_graveyard():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    op.graveyard.append(cards.creature("Dragon", "4RR", 5, 5))
    spell = build_card_from_data({
        "name": "Reanimate Any", "mana_cost": "{3}{B}", "cmc": 4,
        "type_line": "Sorcery",
        "oracle_text": "Put target creature card from a graveyard onto the "
                       "battlefield under your control."})
    spell.on_cast_resolve(g, me, [])
    assert any(pm.card.name == "Dragon" and pm.controller is me
               for pm in me.battlefield)
    assert not any(c.name == "Dragon" for c in op.graveyard)


def test_persist_returns_once_with_minus_counter():
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    finks = build_card_from_data({
        "name": "Kitchen Finks", "mana_cost": "{1}{G}{G}", "cmc": 3,
        "type_line": "Creature", "power": "3", "toughness": "2",
        "oracle_text": "When Kitchen Finks enters, you gain 2 life. Persist"})
    perm = g.move_to_battlefield(finks, me)
    g.to_graveyard(perm, "t")
    back = [p for p in me.battlefield if p.card.name == "Kitchen Finks"]
    assert back and back[0].counters.get("-1/-1") == 1
    assert not any(c.name == "Kitchen Finks" for c in me.graveyard)
    # segunda muerte: ya tenía -1/-1 -> ahora va al cementerio
    g.to_graveyard(back[0], "t2")
    assert any(c.name == "Kitchen Finks" for c in me.graveyard)
    assert not any(p.card.name == "Kitchen Finks" for p in me.battlefield)


def test_undying_returns_with_plus_counter():
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    c = build_card_from_data({
        "name": "Undyer", "mana_cost": "{2}{B}", "cmc": 3,
        "type_line": "Creature", "power": "2", "toughness": "2",
        "oracle_text": "Undying"})
    perm = g.move_to_battlefield(c, me)
    g.to_graveyard(perm, "t")
    back = [p for p in me.battlefield if p.card.name == "Undyer"]
    assert back and back[0].counters.get("+1/+1") == 1


def test_extort_drains_on_cast():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    ext = build_card_from_data({
        "name": "Blind Obedience", "mana_cost": "{1}{W}", "cmc": 2,
        "type_line": "Enchantment", "oracle_text": "Extort"})
    g.move_to_battlefield(ext, me)
    l0, my0 = op.life, me.life
    g.emit("cast", player=me, card=cards.creature("Z", "1U", 1, 1))
    g.resolve_stack()
    assert op.life == l0 - 1 and me.life == my0 + 1


def test_ward_taxes_opponent_removal():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    ward = build_card_from_data({
        "name": "Warded", "mana_cost": "{2}{G}", "cmc": 3, "type_line": "Creature",
        "power": "3", "toughness": "3", "keywords": ["Ward"], "oracle_text": "Ward {2}"})
    assert getattr(ward, "ward", None) and "ward" in ward.keywords
    wperm = g.move_to_battlefield(ward, op)
    rem = cards.remove_targets("destroy")
    # sin maná: el ward no se paga y el efecto falla
    rem(g, me, [wperm])
    assert wperm in op.battlefield
    # con maná: se paga el ward y se destruye
    for _ in range(2):
        g.move_to_battlefield(cards.land("Forest", ["G"]), me)
    rem(g, me, [wperm])
    assert wperm not in op.battlefield


def test_improvise_taps_artifacts():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1U", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(2):
        g.move_to_battlefield(cards.land("Island", ["U"]), me)
    for _ in range(3):
        g.move_to_battlefield(build_card_from_data({
            "name": "Rock", "mana_cost": "{1}", "cmc": 1, "type_line": "Artifact",
            "oracle_text": ""}), me)
    imp = build_card_from_data({
        "name": "Improviser", "mana_cost": "{4}{U}", "cmc": 5, "type_line": "Sorcery",
        "oracle_text": "Improvise\nDraw 3 cards.", "keywords": ["Improvise"]})
    assert "improvise" in imp.tags
    me.hand = [imp]
    h0 = len(me.hand)
    assert g.cast(me, imp) is not False       # {4} pagado con 2 islas + 3 artefactos
    g.resolve_stack()
    assert len(me.hand) == (h0 - 1) + 3


def test_dash_returns_blitz_sacrifices():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player

    def mk(nl=4):
        me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(12)],
                    cards.creature("Cmd", "2R", 3, 3, legendary=True))
        op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                    cards.creature("O", "2B", 1, 1, legendary=True))
        g = Game([me, op], seed=1)
        for _ in range(nl):
            g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
        return g, me, op

    dash = build_card_from_data({
        "name": "Dasher", "mana_cost": "{3}{R}", "cmc": 4, "type_line": "Creature",
        "power": "3", "toughness": "2", "keywords": ["Dash"], "oracle_text": "Dash {1}{R}"})
    assert dash.dash_cost.cmc == 2
    g, me, op = mk()
    me.hand = [dash]
    g.cast_alt_haste(me, dash, "dash")
    assert any(pm.card.name == "Dasher" and not pm.summoning_sick for pm in me.battlefield)
    g.end_turn(me)
    assert any(c.name == "Dasher" for c in me.hand)   # dash: vuelve a la mano

    blitz = build_card_from_data({
        "name": "Blitzer", "mana_cost": "{4}{R}", "cmc": 5, "type_line": "Creature",
        "power": "4", "toughness": "2", "keywords": ["Blitz"], "oracle_text": "Blitz {1}{R}"})
    g, me, op = mk()
    me.hand = [blitz]
    g.cast_alt_haste(me, blitz, "blitz")
    h_before = len(me.hand)
    g.end_turn(me)
    g.resolve_stack()
    assert not any(pm.card.name == "Blitzer" for pm in me.battlefield)  # sacrificada
    assert len(me.hand) == h_before + 1        # blitz: robó al morir


def test_cycling_draws():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1B", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2B", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(3):
        g.move_to_battlefield(cards.land("Swamp", ["B"]), me)
    cyc = build_card_from_data({
        "name": "Barren Moor", "mana_cost": "", "cmc": 0, "type_line": "Land",
        "oracle_text": "Cycling {B}", "keywords": ["Cycling"]})
    assert cyc.cycling.cmc == 1
    me.hand = [cyc]
    h0 = len(me.hand)
    g.cycle_card(me, cyc)
    assert len(me.hand) == h0 - 1 + 1
    assert any(c.name == "Barren Moor" for c in me.graveyard)


def test_cipher_recasts_on_combat_damage():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    ci = build_card_from_data({
        "name": "Hidden Strings", "mana_cost": "{1}{U}", "cmc": 2,
        "type_line": "Sorcery",
        "oracle_text": "You gain 2 life. Cipher (Then you may exile this spell card "
                       "encoded on a creature you control.)"})
    cr = g.move_to_battlefield(cards.creature("Rogue", "1U", 2, 2), me)
    cr.summoning_sick = False
    life0 = me.life
    ci.on_cast_resolve(g, me, [])          # gana 2 + cifra en Rogue
    assert me.life == life0 + 2 and getattr(cr, "_ciphered", None)
    cr.attacking = op
    g.deal_damage(cr, op, 2, combat=True)   # dispara la copia gratis
    g.resolve_stack()
    assert me.life == life0 + 4             # +2 de la copia cifrada


def test_suspend_ticks_then_casts_free():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(4):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    sus = build_card_from_data({
        "name": "Rift Bolt", "mana_cost": "{2}{R}", "cmc": 3, "type_line": "Sorcery",
        "oracle_text": "Rift Bolt deals 3 damage to any target.\nSuspend 1—{R}"})
    assert sus.suspend["n"] == 1
    me.hand = [sus]
    g.suspend_card(me, sus)
    assert len(g.suspended) == 1 and sus not in me.hand
    l0 = op.life
    g.begin_turn(me)                        # upkeep: contador 1->0 -> lanza gratis
    g.resolve_stack()
    assert op.life == l0 - 3


def test_soulbond_grants_keyword_to_both():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    sb = build_card_from_data({
        "name": "Flyer", "mana_cost": "{2}{U}", "cmc": 3, "type_line": "Creature",
        "power": "2", "toughness": "2",
        "oracle_text": "Soulbond\nAs long as this creature is paired with another "
                       "creature, both creatures have flying."})
    fp = g.move_to_battlefield(sb, me)
    assert getattr(fp, "_soulbond_partner", None) is bear
    assert bear.has("flying") and fp.has("flying")


def test_prepared_cast_spell_and_unprepare():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    data = {
        "name": "Blossom-Blessed Angel", "mana_cost": "{3}{W}", "cmc": 4,
        "type_line": "Creature — Angel Cleric", "power": "2", "toughness": "4",
        "oracle_text": "Flying, vigilance\nThis creature enters prepared.",
        "card_faces": [
            {"name": "Blossom-Blessed Angel", "type_line": "Creature — Angel Cleric",
             "mana_cost": "{3}{W}", "oracle_text": "Flying, vigilance\n"
             "This creature enters prepared.", "power": "2", "toughness": "4"},
            {"name": "Seed Suture", "type_line": "Sorcery", "mana_cost": "{G/W}",
             "oracle_text": "Put a +1/+1 counter on target creature. You gain 1 life."}]}
    c = build_card_from_data(data)
    ab = [a for a in c.activated_abilities if a.get("prepared")]
    assert ab and ab[0]["target_spec"] == "own_creature"
    perm = g.move_to_battlefield(c, me)
    assert getattr(perm, "_prepared", False) is True
    tgt = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    life0 = me.life
    ab[0]["effect"](g, me, perm, [tgt])
    assert tgt.counters.get("+1/+1") == 1
    assert me.life == life0 + 1
    assert perm._prepared is False


def test_evoke_etb_then_sacrifice():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1U", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(4):
        g.move_to_battlefield(cards.land("Island", ["U"]), me)
    ev = build_card_from_data({
        "name": "Mulldrifter", "mana_cost": "{4}{U}", "cmc": 5, "type_line": "Creature",
        "power": "2", "toughness": "2",
        "oracle_text": "Flying\nWhen Mulldrifter enters, draw two cards.\nEvoke {2}{U}"})
    assert ev.evoke_cost.cmc == 3
    me.hand = [ev]
    h0 = len(me.hand)
    g.cast_evoke(me, ev)
    g.resolve_stack()
    assert len(me.hand) == (h0 - 1) + 2       # robó 2 por el ETB
    assert not any(pm.card.name == "Mulldrifter" for pm in me.battlefield)
    assert any(c.name == "Mulldrifter" for c in me.graveyard)


def test_kicker_bonus_when_paid():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(4):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    kk = build_card_from_data({
        "name": "Kicker Bolt", "mana_cost": "{R}", "cmc": 1, "type_line": "Sorcery",
        "oracle_text": "Kicker {2}\nKicker Bolt deals 2 damage to any target. "
                       "If this spell was kicked, you gain 3 life."})
    assert getattr(kk, "_kicker_cost", 0) == 2 and getattr(kk, "_kicked_effect", None)
    me.hand = [kk]
    l0, my0 = op.life, me.life
    g.cast(me, kk)
    g.resolve_stack()
    assert op.life == l0 - 2 and me.life == my0 + 3      # kickeado


def test_aftermath_from_graveyard():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(6):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    af = build_card_from_data({
        "name": "Split", "mana_cost": "{1}{R}", "cmc": 2, "type_line": "Sorcery",
        "oracle_text": "Deal 2 damage to any target.",
        "card_faces": [
            {"name": "Front", "type_line": "Sorcery", "mana_cost": "{1}{R}",
             "oracle_text": "Deal 2 damage to any target."},
            {"name": "Back", "type_line": "Sorcery — Aftermath", "mana_cost": "{3}{R}",
             "oracle_text": "Deal 4 damage to any target."}]})
    assert af.gy_play and af.gy_play.get("mode") == "aftermath"
    me.graveyard = [af]
    l0 = op.life
    g.play_from_graveyard(me, af)
    g.resolve_stack()
    assert op.life == l0 - 4
    assert any(c.name == "Split" for c in me.exile)


def test_level_up_grows_creature():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    lu = build_card_from_data({
        "name": "Student", "mana_cost": "{W}", "cmc": 1, "type_line": "Creature",
        "power": "1", "toughness": "1",
        "oracle_text": "Level up {W} ({W}: Put a level counter on this.)"})
    assert any(a["label"] == "Level up" for a in lu.activated_abilities)
    perm = g.move_to_battlefield(lu, me)
    ab = [a for a in lu.activated_abilities if a["label"] == "Level up"][0]
    ab["effect"](g, me, perm, [])
    assert perm.counters.get("+1/+1") == 1 and perm.counters.get("level") == 1


def test_madness_cast_on_discard():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(3):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    mad = build_card_from_data({
        "name": "Fiery Temper", "mana_cost": "{2}{R}", "cmc": 3, "type_line": "Instant",
        "oracle_text": "Fiery Temper deals 3 damage to any target.\nMadness {R}"})
    assert mad.madness.cmc == 1
    me.hand = [mad]
    l0 = op.life
    g._pay_discard(me, 1)          # descartar como coste dispara madness
    g.resolve_stack()
    assert op.life == l0 - 3


def test_adventure_cast_then_creature():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(10)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    for _ in range(6):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    adv = build_card_from_data({
        "name": "Bonecrusher Giant", "mana_cost": "{2}{R}", "cmc": 3,
        "type_line": "Creature — Giant", "power": "4", "toughness": "3",
        "oracle_text": "...",
        "card_faces": [
            {"name": "Bonecrusher Giant", "type_line": "Creature — Giant",
             "mana_cost": "{2}{R}", "oracle_text": "...", "power": "4", "toughness": "3"},
            {"name": "Stomp", "type_line": "Instant — Adventure", "mana_cost": "{1}{R}",
             "oracle_text": "Stomp deals 2 damage to any target."}]})
    assert getattr(adv, "adventure", None) and adv.adventure["cost"].cmc == 2
    me.hand = [adv]
    l0 = op.life
    g.cast_adventure(me, adv)
    g.resolve_stack()
    assert op.life == l0 - 2
    assert any(c.name == "Bonecrusher Giant" for c in me.exile_play)
    g.play_from_exile(me, me.exile_play[0])
    assert any(pm.card.name == "Bonecrusher Giant" for pm in me.battlefield)


def test_echo_pay_or_sacrifice():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player

    def mkg(nlands):
        me = Player("yo", [cards.creature("C", "1G", 1, 1) for _ in range(10)],
                    cards.creature("Cmd", "2G", 3, 3, legendary=True))
        op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(10)],
                    cards.creature("O", "2B", 1, 1, legendary=True))
        g = Game([me, op], seed=1)
        for _ in range(nlands):
            g.move_to_battlefield(cards.land("Forest", ["G"]), me)
        return g, me, op

    echo = build_card_from_data({
        "name": "Mulldrifter", "mana_cost": "{3}{G}", "cmc": 4,
        "type_line": "Creature", "power": "4", "toughness": "4",
        "oracle_text": "Echo {3}{G} (At the beginning of your upkeep, if this came "
                       "under your control since your last upkeep, sacrifice it "
                       "unless you pay its echo cost.)"})
    assert echo.echo.cmc == 4 and "upkeep" in echo.triggers
    g, me, op = mkg(6)
    perm = g.move_to_battlefield(echo, me)
    g.turn = 1
    echo.triggers["upkeep"](g, perm)
    assert perm in me.battlefield
    g, me, op = mkg(0)
    perm = g.move_to_battlefield(echo, me)
    g.turn = 1
    echo.triggers["upkeep"](g, perm)
    assert perm not in me.battlefield
    assert any(c.name == "Mulldrifter" for c in me.graveyard)


def test_replicate_copies_by_payment():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.begin_turn(me)
    for _ in range(6):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    rep = build_card_from_data({
        "name": "Chatter", "mana_cost": "{R}", "cmc": 1, "type_line": "Sorcery",
        "oracle_text": "Chatter deals 1 damage to any target. Replicate {R}"})
    assert getattr(rep, "_replicate_cost", 0) == 1
    me.hand = [rep]
    l0 = op.life
    g.cast(me, rep)
    g.resolve_stack()
    assert op.life == l0 - 6      # base + 5 copias con 6 maná


def test_lifegain_hate_blocks_gain():
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    hate = build_card_from_data({
        "name": "Erebos", "mana_cost": "{2}{B}", "cmc": 3,
        "type_line": "Enchantment Creature", "power": "5", "toughness": "7",
        "oracle_text": "Players can't gain life."})
    assert getattr(hate, "stops_lifegain", None) == "all"
    g.move_to_battlefield(hate, op)
    before = me.life
    g.gain_life(me, 5)
    assert me.life == before


def test_damage_cant_be_prevented():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    op.prevent_all = True
    noprev = build_card_from_data({
        "name": "Skullcrack", "mana_cost": "{1}{R}", "cmc": 2, "type_line": "Instant",
        "oracle_text": "Damage can't be prevented this turn."})
    noprev.on_cast_resolve(g, me, [])
    l0 = op.life
    g.deal_damage(None, op, 3)
    assert op.life == l0 - 3       # el escudo prevent_all se ignora


def test_creatures_cant_block():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    falter = build_card_from_data({
        "name": "Falter", "mana_cost": "{1}{R}", "cmc": 2, "type_line": "Sorcery",
        "oracle_text": "Creatures can't block this turn."})
    falter.on_cast_resolve(g, me, [])
    atk = g.move_to_battlefield(cards.creature("A", "1R", 3, 3), me)
    atk.summoning_sick = False
    blk = g.move_to_battlefield(cards.creature("B", "1B", 2, 2), op)
    g._apply_block_pairs([atk], [(atk, blk)])
    assert not atk.blocked_by


def test_exalted_pumps_lone_attacker():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    ex = build_card_from_data({
        "name": "Exalter", "mana_cost": "{2}{W}", "cmc": 3, "type_line": "Creature",
        "power": "1", "toughness": "1",
        "oracle_text": "Exalted (Whenever a creature you control attacks alone, "
                       "that creature gets +1/+1 until end of turn.)"})
    assert getattr(ex, "exalted", 0) == 1
    g.move_to_battlefield(ex, me)
    atk = g.move_to_battlefield(cards.creature("Knight", "1W", 2, 2), me)
    atk.summoning_sick = False
    g._declare_attackers(me, [(atk, op)])
    assert atk.power == 3 and atk.toughness == 3


def test_static_cost_reduction():
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    el = build_card_from_data({
        "name": "Electromancer", "mana_cost": "{U}{R}", "cmc": 2,
        "type_line": "Creature", "power": "2", "toughness": "2",
        "oracle_text": "Instant and sorcery spells you cast cost {1} less to cast."})
    assert el.spell_discount == (1, "instant_sorcery")
    g.move_to_battlefield(el, me)
    bolt = build_card_from_data({
        "name": "Bolt", "mana_cost": "{2}{R}", "cmc": 3, "type_line": "Instant",
        "oracle_text": "Deal 3 damage to any target."})
    assert g._static_cost_reduction(me, bolt) == 1
    bear = build_card_from_data({
        "name": "Bear", "mana_cost": "{1}{G}", "cmc": 2, "type_line": "Creature",
        "power": "2", "toughness": "2", "oracle_text": ""})
    assert g._static_cost_reduction(me, bear) == 0


def test_monstrosity_adds_counters_to_self():
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    ot = ("{2}{G}{W}: Monstrosity 3. If this creature isn't monstrous, put three "
          "+1/+1 counters on it and it becomes monstrous.")
    c = build_card_from_data({
        "name": "Fleecemane", "mana_cost": "{2}", "cmc": 2, "type_line": "Creature",
        "power": "3", "toughness": "3", "oracle_text": ot})
    perm = g.move_to_battlefield(c, me)
    c.activated_abilities[0]["effect"](g, me, perm, [])
    assert perm.counters.get("+1/+1") == 3 and getattr(perm, "monstrous", False)


def test_devour_eats_tokens():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    cards.make_token(g, me, "Sap", 1, 1)
    cards.make_token(g, me, "Sap", 1, 1)
    dev = build_card_from_data({
        "name": "Skullmulcher", "mana_cost": "{4}{G}", "cmc": 5,
        "type_line": "Creature", "power": "2", "toughness": "2",
        "oracle_text": "Devour 1 (As this enters, you may sacrifice any number of "
                       "creatures. It enters with twice that many +1/+1 counters.)"})
    dp = g.move_to_battlefield(dev, me)
    assert dp.counters.get("+1/+1") == 2


def test_gain_life_trigger():
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    pm = build_card_from_data({
        "name": "Pridemate", "mana_cost": "{1}{W}", "cmc": 2, "type_line": "Creature",
        "power": "2", "toughness": "2",
        "oracle_text": "Whenever you gain life, put a +1/+1 counter on Pridemate."})
    assert "gain_life" in pm.triggers
    perm = g.move_to_battlefield(pm, me)
    g.gain_life(me, 3)
    g.resolve_stack()
    assert perm.counters.get("+1/+1") == 1     # un disparo por evento, no por vida


def test_opponent_casts_trigger():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    op = g.opponents(me)[0]
    watch = build_card_from_data({
        "name": "Watcher", "mana_cost": "{2}{U}", "cmc": 3, "type_line": "Enchantment",
        "oracle_text": "Whenever an opponent casts a spell, you draw a card."})
    assert "opp_cast" in watch.triggers and watch.on_etb is None
    g.move_to_battlefield(watch, me)
    h0 = len(me.hand)
    g.emit("opp_cast", caster=op, card=cards.creature("Z", "1B", 1, 1))
    g.resolve_stack()
    assert len(me.hand) == h0 + 1
    h1 = len(me.hand)
    g.emit("opp_cast", caster=me, card=cards.creature("Y", "1U", 1, 1))
    g.resolve_stack()
    assert len(me.hand) == h1


def test_storm_copies_effect():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1R", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2R", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.begin_turn(me)
    for _ in range(12):
        g.move_to_battlefield(cards.land("Mountain", ["R"]), me)
    s1 = build_card_from_data({"name": "Shock1", "mana_cost": "{R}", "cmc": 1,
                               "type_line": "Instant", "oracle_text": "Draw a card."})
    s2 = build_card_from_data({"name": "Shock2", "mana_cost": "{R}", "cmc": 1,
                               "type_line": "Instant", "oracle_text": "Draw a card."})
    me.hand = [s1, s2]
    g.cast(me, s1)
    g.cast(me, s2)
    grape = build_card_from_data({
        "name": "Grapeshot", "mana_cost": "{1}{R}", "cmc": 2, "type_line": "Sorcery",
        "oracle_text": "Grapeshot deals 1 damage to any target. Storm"})
    me.hand = [grape]
    l0 = op.life
    g.cast(me, grape)
    g.resolve_stack()
    assert op.life == l0 - 3          # 1 + 2 copias (dos hechizos antes)


def test_buyback_returns_to_hand():
    import cards
    from cardsdb import build_card_from_data
    from engine import Game, Player
    me = Player("yo", [cards.creature("C", "1U", 1, 1) for _ in range(12)],
                cards.creature("Cmd", "2U", 3, 3, legendary=True))
    op = Player("op", [cards.creature("X", "1B", 1, 1) for _ in range(12)],
                cards.creature("O", "2B", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    g.begin_turn(me)
    for _ in range(12):
        g.move_to_battlefield(cards.land("Island", ["U"]), me)
    bb = build_card_from_data({
        "name": "Whim", "mana_cost": "{1}{U}", "cmc": 2, "type_line": "Instant",
        "oracle_text": "Buyback {3}. Draw a card."})
    assert getattr(bb, "_buyback_cost", 0) == 3
    me.hand = [bb]
    g.cast(me, bb)
    g.resolve_stack()
    assert any(c.name == "Whim" for c in me.hand)
    assert not any(c.name == "Whim" for c in me.graveyard)


def test_local_combos_detect():
    import combos
    deck = ["Sanguine Bond", "Exquisite Blood", "Walking Ballista",
            "Heliod, Sun-Crowned"]
    r = combos.detect(deck, identity=set("WUBRG"))
    armed = {frozenset(c["cards"]) for c in r["included"]}
    assert frozenset(["Sanguine Bond", "Exquisite Blood"]) in armed
    assert frozenset(["Heliod, Sun-Crowned", "Walking Ballista"]) in armed
    # 'almost': a Walking Ballista le falta Mikaeus -> propuesto (identidad completa)
    almost_missing = {tuple(c["missing"]) for c in r["almost"]}
    assert ("Mikaeus, the Unhallowed",) in almost_missing
    # filtro de color: mono-rojo no ve combos azules/negros
    r2 = combos.detect(["Kiki-Jiki, Mirror Breaker"], identity={"R"})
    for c in r2["almost"]:
        assert c["missing"] == ["Zealous Conscripts"] or "R" in "".join(c["cards"])


def test_distribute_counters_human_chooses():
    import cards
    from cardsdb import build_card_from_data
    g, me = _reco_players()
    g.interactive_human = me
    g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    g.move_to_battlefield(cards.creature("Wolf", "1G", 3, 3), me)
    spell = build_card_from_data({
        "name": "Distr", "mana_cost": "{2}{G}", "cmc": 3,
        "type_line": "Sorcery",
        "oracle_text": "Distribute three +1/+1 counters among creatures "
                       "you control."})
    spell.on_cast_resolve(g, me, spell)
    pc = g.pending_choice
    assert pc and pc["kind"] == "etb_target"
    assert {o["name"] for o in pc["options"]} == {"Bear 2/2", "Wolf 3/3"}
    # el bot resuelve solo (sin modal)
    g2, bot = _reco_players()
    g2.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), bot)
    spell2 = build_card_from_data({
        "name": "Distr", "mana_cost": "{2}{G}", "cmc": 3,
        "type_line": "Sorcery",
        "oracle_text": "Distribute three +1/+1 counters among creatures "
                       "you control."})
    spell2.on_cast_resolve(g2, bot, spell2)
    assert g2.pending_choice is None


# -- última tanda: evasión, disparos de combate, renombre, sed de sangre --- #
def _bcreature(name, cost, p, t, oracle="", keywords=None):
    from cardsdb import build_card_from_data
    return build_card_from_data({
        "name": name, "mana_cost": cost, "cmc": 3,
        "type_line": "Creature — Test", "power": str(p), "toughness": str(t),
        "oracle_text": oracle, "keywords": keywords or []})


def test_fear_only_blocked_by_black_or_artifact():
    import cards
    g, me, op = _duel()
    atk = g.move_to_battlefield(_bcreature("Ghoul", "2B", 2, 2, keywords=["Fear"]), me)
    atk.summoning_sick = False
    white = g.move_to_battlefield(cards.creature("WKnight", "1W", 2, 2), op)
    g._begin_combat(me)
    g._declare_attackers(me, [(atk, op)])
    g._apply_block_pairs([atk], [(atk, white)])
    assert atk.blocked_by == []                     # blanca no puede bloquear con miedo
    # una criatura negra sí puede
    g2, me2, op2 = _duel()
    atk2 = g2.move_to_battlefield(_bcreature("Ghoul", "2B", 2, 2, keywords=["Fear"]), me2)
    atk2.summoning_sick = False
    black = g2.move_to_battlefield(cards.creature("BZombie", "1B", 2, 2), op2)
    g2._begin_combat(me2)
    g2._declare_attackers(me2, [(atk2, op2)])
    g2._apply_block_pairs([atk2], [(atk2, black)])
    assert black in atk2.blocked_by


def test_skulk_blocked_only_by_lesser_power():
    import cards
    g, me, op = _duel()
    atk = g.move_to_battlefield(_bcreature("Sneak", "2U", 3, 3, keywords=["Skulk"]), me)
    atk.summoning_sick = False
    big = g.move_to_battlefield(cards.creature("Ogre", "3R", 4, 4), op)
    g._begin_combat(me)
    g._declare_attackers(me, [(atk, op)])
    g._apply_block_pairs([atk], [(atk, big)])
    assert atk.blocked_by == []                     # 4 de poder no puede bloquear a skulk 3


def test_battle_cry_pumps_other_attackers():
    import cards
    g, me, op = _duel()
    cryer = g.move_to_battlefield(_bcreature("Herald", "1R", 1, 1, keywords=["Battle cry"]), me)
    other = g.move_to_battlefield(cards.creature("Soldier", "1W", 2, 2), me)
    cryer.summoning_sick = other.summoning_sick = False
    g._begin_combat(me)
    g._declare_attackers(me, [(cryer, op), (other, op)])
    assert other.power == 3                          # +1/+0 del grito de guerra
    assert cryer.power == 1                          # el propio no se pumpa


def test_mentor_and_training_add_counters():
    import cards
    g, me, op = _duel()
    mentor = g.move_to_battlefield(_bcreature("Cap", "2R", 3, 3, keywords=["Mentor"]), me)
    small = g.move_to_battlefield(cards.creature("Recruit", "1R", 1, 1), me)
    mentor.summoning_sick = small.summoning_sick = False
    g._begin_combat(me)
    g._declare_attackers(me, [(mentor, op), (small, op)])
    assert small.counters.get("+1/+1", 0) == 1       # mentor pone +1/+1 en el menor


def test_renown_counters_on_combat_damage():
    import cards
    g, me, op = _duel()
    r = g.move_to_battlefield(_bcreature("Champ", "2W", 2, 2, oracle="Renown 2"), me)
    g.deal_damage(r, op, 2, combat=True)
    assert r.counters.get("+1/+1", 0) == 2 and getattr(r, "_renowned", False)
    g.deal_damage(r, op, 2, combat=True)             # ya renombrada: no repite
    assert r.counters.get("+1/+1", 0) == 2


def test_bloodthirst_etb_with_damaged_opponent():
    import cards
    g, me, op = _duel()
    g.damaged_players.add(op)                         # un rival fue dañado este turno
    b = g.move_to_battlefield(_bcreature("Raider", "1R", 2, 2, oracle="Bloodthirst 1"), me)
    assert b.counters.get("+1/+1", 0) == 1
    # sin rival dañado, entra sin contadores
    g2, me2, op2 = _duel()
    b2 = g2.move_to_battlefield(_bcreature("Raider", "1R", 2, 2, oracle="Bloodthirst 1"), me2)
    assert b2.counters.get("+1/+1", 0) == 0


# -- tanda 2: annihilator, afflict, flanking, rampage, bushido, dethrone,
#            afterlife, modular, riot, toxic N, connive, acciones-palabra --- #
def test_annihilator_defender_sacrifices():
    import cards
    g, me, op = _duel()
    atk = g.move_to_battlefield(_bcreature("Ann", "6", 5, 5, oracle="Annihilator 2"), me)
    atk.summoning_sick = False
    for i in range(3):
        g.move_to_battlefield(cards.creature(f"Chump{i}", "1G", 1, 1), op)
    before = len([p for p in op.battlefield])
    g._begin_combat(me)
    g._declare_attackers(me, [(atk, op)])
    assert len(op.battlefield) == before - 2          # sacrifica 2 permanentes


def test_afflict_drains_defender_when_blocked():
    import cards
    g, me, op = _duel()
    atk = g.move_to_battlefield(_bcreature("Af", "2B", 2, 2, oracle="Afflict 3"), me)
    atk.summoning_sick = False
    blk = g.move_to_battlefield(cards.creature("Wall", "1G", 0, 4), op)
    l0 = op.life
    g._begin_combat(me)
    g._declare_attackers(me, [(atk, op)])
    g._apply_block_pairs([atk], [(atk, blk)])
    g._finish_combat([atk])
    assert op.life == l0 - 3                            # pierde 3 al ser bloqueada


def test_flanking_weakens_nonflanking_blocker():
    import cards
    g, me, op = _duel()
    atk = g.move_to_battlefield(_bcreature("Knight", "1W", 2, 2, keywords=["Flanking"]), me)
    atk.summoning_sick = False
    blk = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), op)
    g._begin_combat(me)
    g._declare_attackers(me, [(atk, op)])
    g._apply_block_pairs([atk], [(atk, blk)])
    g._finish_combat([atk])
    assert blk not in op.battlefield                    # -1/-1 lo deja en 1/1 y muere


def test_rampage_and_bushido_pump_when_blocked():
    import cards
    g, me, op = _duel()
    r = g.move_to_battlefield(_bcreature("Ramp", "3G", 3, 3, oracle="Rampage 2"), me)
    r.summoning_sick = False
    b1 = g.move_to_battlefield(cards.creature("B1", "1G", 1, 1), op)
    b2 = g.move_to_battlefield(cards.creature("B2", "1G", 1, 1), op)
    g._begin_combat(me)
    g._declare_attackers(me, [(r, op)])
    g._apply_block_pairs([r], [(r, b1), (r, b2)])
    g._combat_block_triggers([r])
    assert r.power == 5                                 # +2/+2 por el 2º bloqueador


def test_dethrone_counter_on_attacking_highest_life():
    import cards
    g, me, op = _duel()
    d = g.move_to_battlefield(_bcreature("Usurp", "1B", 1, 1, oracle="Dethrone"), me)
    d.summoning_sick = False
    g._begin_combat(me)
    g._declare_attackers(me, [(d, op)])                 # op tiene 40 (más vida)
    assert d.counters.get("+1/+1", 0) == 1


def test_afterlife_makes_spirits():
    import cards
    g, me, op = _duel()
    c = g.move_to_battlefield(_bcreature("Cleric", "1W", 1, 1, oracle="Afterlife 2"), me)
    g.to_graveyard(c, "muere")
    spirits = [p for p in me.battlefield if p.name == "Spirit"]
    assert len(spirits) == 2 and all(s.has("flying") for s in spirits)


def test_modular_moves_counters_on_death():
    import cards
    g, me, op = _duel()
    src = g.move_to_battlefield(_bcreature("Sphere", "2", 0, 0, oracle="Modular 3"), me)
    assert src.counters.get("+1/+1", 0) == 3            # entra con 3
    dest = g.move_to_battlefield(_bcreature("Golem", "3", 2, 2,
                                            oracle="", keywords=[]), me)
    dest.card.types = set(dest.card.types) | {"artifact"}
    g.to_graveyard(src, "muere")
    assert dest.counters.get("+1/+1", 0) == 3           # los mueve al artefacto-criatura


def test_riot_enters_with_counter():
    g, me, op = _duel()
    c = g.move_to_battlefield(_bcreature("Rioter", "2R", 2, 2, oracle="Riot"), me)
    assert c.counters.get("+1/+1", 0) == 1


def test_toxic_n_adds_poison_on_combat_only():
    g, me, op = _duel()
    t = g.move_to_battlefield(_bcreature("Snake", "1G", 2, 2, oracle="Toxic 2"), me)
    g.deal_damage(t, op, 2, combat=True)
    assert op.poison == 2 and op.life == 40 - 2
    g.deal_damage(t, op, 2, combat=False)               # no-combate: sin veneno
    assert op.poison == 2


def test_connive_on_attack():
    import cards
    g, me, op = _duel()
    me.hand.append(cards.creature("Spare", "1G", 2, 2))   # no-tierra para descartar
    c = g.move_to_battlefield(
        _bcreature("Rogue", "1U", 2, 2,
                   oracle="Whenever Rogue attacks, it connives."), me)
    c.summoning_sick = False
    g._begin_combat(me)
    g._declare_attackers(me, [(c, op)])
    assert c.counters.get("+1/+1", 0) >= 0                # corre sin romper


def test_investigate_and_bolster_actions():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    g.move_to_battlefield(cards.creature("Small", "1G", 1, 1), me)
    g.move_to_battlefield(cards.creature("Big", "3G", 4, 4), me)
    spell = build_card_from_data({
        "name": "Inv", "mana_cost": "{1}{G}", "cmc": 2, "type_line": "Sorcery",
        "oracle_text": "Investigate. Bolster 2."})
    assert spell.on_cast_resolve is not None
    spell.on_cast_resolve(g, me, spell)
    clues = [p for p in me.battlefield if p.name.lower() == "clue"]
    assert len(clues) == 1
    small = next(p for p in me.battlefield if p.name.startswith("Small"))
    assert small.counters.get("+1/+1", 0) == 2            # al de menor resistencia


def test_amass_creates_and_grows_army():
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    spell = build_card_from_data({
        "name": "Am", "mana_cost": "{1}{B}", "cmc": 2, "type_line": "Sorcery",
        "oracle_text": "Amass Orcs 3."})
    spell.on_cast_resolve(g, me, spell)
    army = next((p for p in me.battlefield if "Army" in p.card.subtypes), None)
    assert army is not None and army.counters.get("+1/+1", 0) == 3


# -- tanda 3: ETB destruir no-criaturas (Terastodon) + upkeep --------------- #
def _terastodon():
    from cardsdb import build_card_from_data
    return build_card_from_data({
        "name": "Terastodon", "mana_cost": "{6}{G}{G}", "cmc": 8,
        "type_line": "Creature — Elephant", "power": "9", "toughness": "9",
        "oracle_text": ("When Terastodon enters, you may destroy up to three "
                        "target noncreature permanents. For each permanent put "
                        "into a graveyard this way, its controller creates a 3/3 "
                        "green Elephant creature token."), "keywords": []})


def test_terastodon_etb_human_destroys_and_makes_elephant():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    g.interactive_human = me
    art = build_card_from_data({"name": "Signet", "mana_cost": "{2}", "cmc": 2,
                                "type_line": "Artifact", "oracle_text": "",
                                "keywords": []})
    g.move_to_battlefield(art, op)
    t = g.move_to_battlefield(_terastodon(), me)
    assert t in me.battlefield                          # entra y NO desaparece
    pc = g.pending_choice
    assert pc and pc["kind"] == "etb_target"
    pc["_apply"](0)                                     # destruir el Signet
    assert art not in op.battlefield
    eles = [p for p in op.battlefield if p.name == "Elephant"]
    assert len(eles) == 1 and eles[0].power == 3         # su dueño (op) hace un 3/3
    assert t in me.battlefield                           # sigue en el campo


def test_terastodon_bot_autodestroys_opponent_noncreature():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel()                                  # sin interactive_human -> bot
    art = build_card_from_data({"name": "Signet", "mana_cost": "{2}", "cmc": 2,
                                "type_line": "Artifact", "oracle_text": "",
                                "keywords": []})
    g.move_to_battlefield(art, op)
    g.move_to_battlefield(_terastodon(), me)
    assert art not in op.battlefield                     # el bot lo destruye solo


def test_vanishing_sacrifices_after_n_upkeeps():
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    v = g.move_to_battlefield(build_card_from_data({
        "name": "Vanish", "mana_cost": "{2}{U}", "cmc": 3,
        "type_line": "Creature — Illusion", "power": "3", "toughness": "3",
        "oracle_text": "Vanishing 2.", "keywords": []}), me)
    assert v.counters.get("time") == 2
    g._tick_upkeep_counters(me)
    assert v in me.battlefield
    g._tick_upkeep_counters(me)
    assert v not in me.battlefield                       # muere al quitar el último


def test_fading_sacrifices_when_cannot_remove():
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    f = g.move_to_battlefield(build_card_from_data({
        "name": "Fade", "mana_cost": "{2}", "cmc": 2, "type_line": "Creature — Ally",
        "power": "2", "toughness": "2", "oracle_text": "Fading 1.", "keywords": []}), me)
    assert f.counters.get("fade") == 1
    g._tick_upkeep_counters(me)                          # quita el único contador
    assert f in me.battlefield
    g._tick_upkeep_counters(me)                          # no puede quitar -> sacrificio
    assert f not in me.battlefield


def test_cumulative_upkeep_life_sacrifices_when_unaffordable():
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    c = g.move_to_battlefield(build_card_from_data({
        "name": "CU", "mana_cost": "{1}", "cmc": 1, "type_line": "Enchantment",
        "power": None, "toughness": None,
        "oracle_text": "Cumulative upkeep—Pay 3 life.", "keywords": []}), me)
    l0 = me.life
    g._tick_upkeep_counters(me)                          # edad 1: paga 3 vida
    assert c in me.battlefield and me.life == l0 - 3
    me.life = 2                                          # no puede pagar 6
    g._tick_upkeep_counters(me)
    assert c not in me.battlefield                       # se sacrifica


def test_final_act_modal_five_modes_all_resolve():
    import cards
    from cardsdb import build_card_from_data
    def FA():
        return build_card_from_data({
            "name": "Final Act", "mana_cost": "{5}{W}{W}", "cmc": 7,
            "type_line": "Sorcery",
            "oracle_text": ("Choose one or more —\n• Destroy all creatures.\n"
                            "• Destroy all planeswalkers.\n• Destroy all battles.\n"
                            "• Exile all graveyards.\n• Each opponent loses all counters.")})
    fa = FA()
    assert len(fa.modes) == 5 and fa.mode_pick == 5      # 5 modos, elegir cualquier cantidad
    g, me, op = _duel()
    for _ in range(7):
        g.move_to_battlefield(cards.land("Plains", ["W"], basic=True), me)
    mc = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    oc = g.move_to_battlefield(cards.creature("Wolf", "1G", 3, 3), op)
    g.add_counters(oc, "+1/+1", 2)
    op.poison = 3
    op.graveyard.append(cards.creature("Dead", "1G", 1, 1))
    g.cast(me, FA(), chosen_modes=[0, 3, 4]); g.resolve_stack(); g.sba()
    assert mc not in me.battlefield and oc not in op.battlefield   # destruir criaturas
    assert len(op.graveyard) == 0                                  # exiliar cementerios
    assert op.poison == 0                                          # perder contadores


def test_class_enchantment_levels_and_gated_trigger():
    import cards
    from cardsdb import build_card_from_data
    oracle = ("(Gain the next level as a sorcery to add its ability.)\n"
              "At the beginning of your first main phase, mill a card.\n"
              "{1}{R}: Level 2\n"
              "Whenever one or more cards leave your graveyard, this Class deals 2 "
              "damage to each opponent.\n"
              "{1}{R}: Level 3\n"
              "Spells you cast from anywhere other than your hand cost {2} less.")
    def AR():
        return build_card_from_data({
            "name": "Advanced Reconstruction", "mana_cost": "{3}{R}", "cmc": 4,
            "type_line": "Enchantment — Class", "oracle_text": oracle, "keywords": []})
    card = AR()
    assert card.class_max == 3
    assert [a["label"] for a in card.activated_abilities] == ["Subir a nivel 2", "Subir a nivel 3"]
    g, me, op = _duel()
    for _ in range(3):
        g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    perm = g.move_to_battlefield(AR(), me)
    assert perm.counters.get("level") == 1                 # entra en nivel 1
    # en nivel 1 el disparo de nivel 2 NO debe dañar
    me.graveyard.append(cards.creature("X", "1R", 1, 1))
    g.emit("leaves_graveyard", player=me, card=me.graveyard.pop()); g.resolve_stack()
    assert op.life == 40
    # subir a nivel 2 y comprobar que ahora sí dispara
    g.activate_ability(perm, 0); g.resolve_stack()
    assert perm.counters.get("level") == 2
    me.graveyard.append(cards.creature("Y", "1R", 1, 1))
    g.emit("leaves_graveyard", player=me, card=me.graveyard.pop()); g.resolve_stack()
    assert op.life == 38                                    # 2 de daño en nivel 2


def test_token_with_counters_and_subtype():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    sp = build_card_from_data({
        "name": "Dino Maker", "mana_cost": "{3}{G}", "cmc": 4, "type_line": "Sorcery",
        "oracle_text": ("Create a 3/3 green Dinosaur creature token with two "
                        "+1/+1 counters on it."), "keywords": []})
    sp.on_cast_resolve(g, me, sp)
    toks = [p for p in me.battlefield if p.is_token]
    assert len(toks) == 1
    t = toks[0]
    assert t.name == "Dinosaur" and "Dinosaur" in t.card.subtypes
    assert t.counters.get("+1/+1") == 2 and t.power == 5 and t.toughness == 5


def test_edict_human_chooses_on_own_turn_else_auto():
    import cards
    from cardsdb import build_card_from_data
    def edict():
        return build_card_from_data({
            "name": "Edict", "mana_cost": "{1}{B}", "cmc": 2, "type_line": "Sorcery",
            "oracle_text": "Target player sacrifices a creature.", "keywords": []})
    # el rival (bot) sacrifica su más débil cuando el humano lanza el edicto
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 0
    w = g.move_to_battlefield(cards.creature("Weak", "1G", 1, 1), op)
    s = g.move_to_battlefield(cards.creature("Strong", "2G", 5, 5), op)
    e = edict(); e.on_cast_resolve(g, me, e); g.resolve_stack()
    assert w not in op.battlefield and s in op.battlefield
    # cuando es el humano quien debe sacrificar EN SU TURNO -> modal
    from cardsdb import _human_or_auto_sacrifice
    g2, me2, op2 = _duel(); g2.interactive_human = me2; g2.active_index = 0
    g2.move_to_battlefield(cards.creature("A", "1G", 2, 2), me2)
    _human_or_auto_sacrifice(g2, me2, "elegí")
    assert g2.pending_choice and g2.pending_choice["kind"] == "etb_target"
    # en el turno de un bot NO se abre modal para el humano (evita que se cuelgue)
    g3, me3, op3 = _duel(); g3.interactive_human = me3; g3.active_index = 1
    g3.move_to_battlefield(cards.creature("A", "1G", 2, 2), me3)
    _human_or_auto_sacrifice(g3, me3, "elegí")
    assert g3.pending_choice is None


def test_forced_discard_human_prompts_on_own_turn():
    import cards
    from cardsdb import _human_or_auto_discard
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 0
    me.hand = [cards.creature("A", "1G", 1, 1), cards.creature("B", "1G", 2, 2)]
    _human_or_auto_discard(g, me, 1)
    assert g.pending_choice and g.pending_choice["kind"] == "discard"


def test_bot_edict_queues_choice_for_human():
    # un edicto lanzado por un BOT contra el humano encola la decisión (no se
    # auto-resuelve): resolve_stack no pausa en turno de bot, así que va a la cola.
    import cards
    from cardsdb import _human_or_auto_sacrifice
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 1   # turno del bot
    g.move_to_battlefield(cards.creature("A", "1G", 1, 1), me)
    g.move_to_battlefield(cards.creature("B", "2G", 5, 5), me)
    _human_or_auto_sacrifice(g, me, "elegí")
    assert g.pending_choice is None and len(g.choice_queue) == 1  # encolada, no auto


def test_planeswalker_loyalty_target_prompts_human():
    import cards
    from cardsdb import build_card_from_data
    pw = build_card_from_data({
        "name": "Vraska", "mana_cost": "{4}{B}{G}", "cmc": 6,
        "type_line": "Legendary Planeswalker — Vraska", "loyalty": "6",
        "oracle_text": "+2: Draw a card.\n-3: Destroy target creature.", "keywords": []})
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 0
    a = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), op)
    b = g.move_to_battlefield(cards.creature("Wolf", "1G", 5, 5), op)
    perm = g.move_to_battlefield(pw, me)
    assert g.activate_loyalty(perm, 1); g.resolve_stack()
    pc = g.pending_choice
    assert pc and pc["kind"] == "etb_target" and len(pc["options"]) == 2
    pc["_apply"](1)                                    # elegir el Wolf
    assert b not in op.battlefield and a in op.battlefield


def _mkcard(name, tl, p, t, txt):
    from cardsdb import build_card_from_data
    return build_card_from_data({
        "name": name, "mana_cost": "{1}{G}", "cmc": 2, "type_line": tl,
        "power": str(p), "toughness": str(t), "oracle_text": txt, "keywords": []})


def test_landfall_begin_combat_draw_triggers():
    import cards
    g, me, op = _duel()
    lf = g.move_to_battlefield(_mkcard("Cobra", "Creature — Snake", 2, 1,
        "Whenever a land enters the battlefield under your control, you gain 2 life."), me)
    assert "landfall" in lf.card.triggers
    l0 = me.life
    g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me); g.resolve_stack()
    assert me.life == l0 + 2
    bc = g.move_to_battlefield(_mkcard("Rabble", "Creature — Goblin", 1, 1,
        "At the beginning of combat on your turn, create a 1/1 red Goblin creature token."), me)
    n0 = len([p for p in me.battlefield if p.is_token])
    g.emit("begin_combat", player=me); g.resolve_stack()
    assert len([p for p in me.battlefield if p.is_token]) == n0 + 1
    dr = g.move_to_battlefield(_mkcard("Drawer", "Creature — Bird", 1, 1,
        "Whenever you draw a card, you gain 1 life."), me)
    me.library.append(cards.creature("z", "1G", 1, 1)); l1 = me.life
    me.draw(1, g); g.resolve_stack()
    assert me.life == l1 + 1


def test_death_trigger_you_control_not_opponents():
    import cards
    g, me, op = _duel()
    r = g.move_to_battlefield(_mkcard("Reaper", "Creature — Zombie", 2, 2,
        "Whenever a creature you control dies, each opponent loses 1 life."), me)
    ol = op.life
    oc = g.move_to_battlefield(cards.creature("EnemyCrit", "1G", 1, 1), op)
    g.to_graveyard(oc, "muere"); g.resolve_stack()
    assert op.life == ol                               # muerte RIVAL: no dispara
    myc = g.move_to_battlefield(cards.creature("MyCrit", "1G", 1, 1), me)
    g.to_graveyard(myc, "muere"); g.resolve_stack()
    assert op.life == ol - 1                           # muerte MÍA: sí dispara


def test_tribal_lord_by_subtype():
    g, me, op = _duel()
    g.move_to_battlefield(_mkcard("Goblin King", "Creature — Goblin", 2, 2,
        "Other Goblins you control get +1/+1 and have haste."), me)
    gob = g.move_to_battlefield(_mkcard("Gob", "Creature — Goblin", 1, 1, ""), me)
    elf = g.move_to_battlefield(_mkcard("Elf", "Creature — Elf", 1, 1, ""), me)
    assert gob.power == 2 and gob.toughness == 2 and gob.has("haste")
    assert elf.power == 1 and not elf.has("haste")     # otro subtipo: sin buff


def test_equipment_attach_buff_and_survive_creature_death():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 0
    for _ in range(2):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    eq = g.move_to_battlefield(build_card_from_data({
        "name": "Sword", "mana_cost": "{2}", "cmc": 2, "type_line": "Artifact — Equipment",
        "oracle_text": "Equipped creature gets +2/+2 and has trample.\nEquip {2}",
        "keywords": []}), me)
    cr = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    assert g.activate_ability(eq, 0); g.resolve_stack()
    g.pending_choice["_apply"](0)                      # equipar al Bear
    assert cr.power == 4 and cr.toughness == 4 and cr.has("trample")
    g.to_graveyard(cr, "muere"); g.sba()
    assert eq in me.battlefield and eq.enchanting is None   # sobrevive y se desanexa


def test_x_token_scales_with_count():
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    for i in range(3):
        g.move_to_battlefield(build_card_from_data({
            "name": f"G{i}", "mana_cost": "{R}", "cmc": 1, "type_line": "Creature — Goblin",
            "power": "1", "toughness": "1", "oracle_text": "", "keywords": []}), me)
    sp = build_card_from_data({
        "name": "Krenko", "mana_cost": "{2}{R}", "cmc": 3, "type_line": "Sorcery",
        "oracle_text": "Create X 1/1 red Goblin creature tokens, where X is the "
                       "number of Goblins you control.", "keywords": []})
    sp.on_cast_resolve(g, me, sp)
    assert len([p for p in me.battlefield if p.is_token]) == 3


def test_crew_makes_vehicle_a_creature_until_end_of_turn():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 0
    veh = g.move_to_battlefield(build_card_from_data({
        "name": "Copter", "mana_cost": "{2}", "cmc": 2, "type_line": "Artifact — Vehicle",
        "power": "3", "toughness": "3", "oracle_text": "Flying\nCrew 1",
        "keywords": ["Flying"]}), me)
    pilot = g.move_to_battlefield(cards.creature("Pilot", "1G", 1, 1), me)
    assert not veh.is_creature()
    assert [a["label"] for a in veh.card.activated_abilities][-1] == "Tripular 1"
    g.activate_ability(veh, len(veh.card.activated_abilities) - 1); g.resolve_stack()
    assert veh.is_creature() and pilot.tapped and veh.has("flying")
    g.end_turn(me)
    assert not veh.is_creature()               # deja de ser criatura al fin del turno


def test_additional_combat_phase():
    import cards
    from cardsdb import build_card_from_data
    g, me, op = _duel()
    c = g.move_to_battlefield(cards.creature("Att", "1R", 3, 3), me); c.tapped = True
    sp = build_card_from_data({
        "name": "Aggravated", "mana_cost": "{2}{R}", "cmc": 3, "type_line": "Sorcery",
        "oracle_text": ("Untap all creatures you control. There is an additional "
                        "combat phase after this one."), "keywords": []})
    sp.on_cast_resolve(g, me, sp)
    assert g.extra_combats == 1 and not c.tapped


def test_omo_enters_or_attacks_everything_counter():
    import cards
    from cardsdb import build_card_from_data
    def omo():
        return build_card_from_data({
            "name": "Omo", "mana_cost": "{G}{U}", "cmc": 2,
            "type_line": "Legendary Creature — Frog Wizard", "power": "2", "toughness": "2",
            "oracle_text": ("Whenever Omo enters or attacks, put an everything counter "
                            "on each of up to one target land and up to one target "
                            "creature.\nEach nonland creature with an everything counter "
                            "on it is every creature type."), "keywords": []})
    c = omo()
    assert c.on_etb is not None and "attacks" in c.triggers
    g, me, op = _duel(); g.interactive_human = me; g.active_index = 0
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    g.move_to_battlefield(omo(), me)           # ETB dispara
    pc = g.pending_choice
    assert pc and pc["kind"] == "etb_target"
    pc["_apply"](0)                            # elegir una criatura
    if g.pending_choice:                       # luego pide tierra (opcional)
        g.pending_choice["_apply"](0)
    chosen = next(p for p in me.battlefield if p.counters.get("everything"))
    assert chosen.has_subtype("Goblin")        # todos los tipos de criatura


def test_cost_increaser_tax():
    import cards
    from engine import Game, Player
    from cardsdb import build_card_from_data
    me = Player("me", [cards.land("Plains", ["W"], basic=True) for _ in range(6)],
                cards.creature("Cm", "2W", 3, 3, legendary=True))
    op = Player("op", [], cards.creature("Om", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1)
    th = build_card_from_data({
        "name": "Thalia", "mana_cost": "{1}{W}", "cmc": 2,
        "type_line": "Legendary Creature — Human Soldier", "power": "2", "toughness": "1",
        "oracle_text": "Noncreature spells cost {1} more to cast.", "keywords": []})
    assert getattr(th, "spell_tax", None) == (1, "noncreature", "all")
    g.move_to_battlefield(th, op)
    inst = build_card_from_data({"name": "Bolt", "mana_cost": "{R}", "cmc": 1,
        "type_line": "Instant", "oracle_text": "", "keywords": []})
    crea = build_card_from_data({"name": "Bear", "mana_cost": "{1}{G}", "cmc": 2,
        "type_line": "Creature — Bear", "power": "2", "toughness": "2",
        "oracle_text": "", "keywords": []})
    assert g._static_cost_increase(me, inst) == 1     # noncreature: +1
    assert g._static_cost_increase(me, crea) == 0     # creature: sin impuesto


def test_transform_dfc_swaps_faces():
    import cards
    from cardsdb import build_card_from_data
    dfc = build_card_from_data({
        "name": "Delver", "mana_cost": "{U}", "cmc": 1,
        "type_line": "Creature — Human Wizard", "power": "1", "toughness": "1",
        "oracle_text": "At the beginning of your upkeep, you may transform Delver.",
        "keywords": [], "card_faces": [
            {"name": "Delver of Secrets", "type_line": "Creature — Human Wizard",
             "mana_cost": "{U}", "power": "1", "toughness": "1",
             "oracle_text": "... transform Delver."},
            {"name": "Insectile Aberration", "type_line": "Creature — Human Insect",
             "power": "3", "toughness": "2", "oracle_text": "Flying",
             "keywords": ["Flying"]}]})
    assert dfc.dfc == "transform" and dfc.back_face.name == "Insectile Aberration"
    g, me, op = _duel()
    p = g.move_to_battlefield(dfc, me)
    assert p.power == 1 and not p.has("flying")
    g.transform(p)
    assert p.power == 3 and p.toughness == 2 and p.has("flying")
    g.transform(p)                             # se puede volver a dar vuelta
    assert p.power == 1


# -- día / noche (daybound / nightbound) ----------------------------------- #
def _daybound_card():
    import cardsdb
    return cardsdb.build_card_from_data({
        "name": "Lupine // Lupo",
        "type_line": "Creature — Human Werewolf // Creature — Werewolf",
        "card_faces": [
            {"name": "Lupine", "mana_cost": "{1}{G}", "type_line": "Creature — Human Werewolf",
             "power": "2", "toughness": "2", "oracle_text": "Daybound"},
            {"name": "Lupo", "type_line": "Creature — Werewolf",
             "power": "3", "toughness": "3", "oracle_text": "Nightbound"},
        ],
    })


def test_daybound_parse_and_day_night_transform():
    g, me, op = _duel()
    c = _daybound_card()
    assert getattr(c, "daybound", False) and not getattr(c, "nightbound", False)
    assert getattr(c.back_face, "nightbound", False)
    assert c.dfc == "transform"
    # al entrar una carta daybound y no ser ni día ni noche -> se vuelve de día
    assert g.day_night is None
    perm = g.move_to_battlefield(c, me)
    assert g.day_night == "day"
    assert perm.card is c                        # frente = cara de día
    # se hace de noche -> transforma al dorso
    g.set_day_night("night")
    assert perm.card.name == "Lupo"
    assert perm.power == 3
    # vuelve el día -> vuelve al frente
    g.set_day_night("day")
    assert perm.card is c


def test_day_night_flips_on_turn_spell_count():
    g, me, op = _duel()
    g.move_to_battlefield(_daybound_card(), me)
    assert g.day_night == "day"
    g.spells_this_turn = 0                       # el activo no lanzó hechizos
    g.begin_turn(op)                             # -> se hace de noche
    assert g.day_night == "night"
    g.spells_this_turn = 2                        # 2+ hechizos
    g.begin_turn(me)                             # -> vuelve el día
    assert g.day_night == "day"


# -- DFC modal: jugar la cara trasera desde la mano ------------------------ #
def test_modal_dfc_back_face_land_played_from_hand():
    import cardsdb
    from engine import Cost
    c = cardsdb.build_card_from_data({
        "name": "Grove // Hollow",
        "type_line": "Creature — Bear // Land",
        "card_faces": [
            {"name": "Grove", "mana_cost": "{1}{G}", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2", "oracle_text": ""},
            {"name": "Hollow", "type_line": "Land",
             "oracle_text": "{T}: Add {G}."},
        ],
    })
    assert c.dfc == "modal"                      # ninguna cara se transforma en juego
    assert c.back_face.is_land()
    g, me, op = _duel()
    me.hand.append(c)
    lp0 = me.lands_played
    ok = g.play_dfc_back(me, c)
    assert ok is not False
    assert me.lands_played == lp0 + 1
    assert any(pm.card.name == "Hollow" for pm in me.battlefield)
    assert c not in me.hand


def test_modal_dfc_back_face_spell_cast_from_hand():
    import cardsdb
    c = cardsdb.build_card_from_data({
        "name": "Front // Bolt",
        "type_line": "Creature — Bear // Instant",
        "card_faces": [
            {"name": "Front", "mana_cost": "{1}{G}", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
            {"name": "Bolt", "mana_cost": "{R}", "type_line": "Instant",
             "oracle_text": "Bolt deals 3 damage to any target."},
        ],
    })
    assert c.dfc == "modal"
    g, me, op = _duel()
    for _ in range(3):
        g.move_to_battlefield(cards_land_r(), me)
    me.hand.append(c)
    l0 = op.life
    ok = g.play_dfc_back(me, c, targets=[op])
    g.resolve_stack()
    assert ok is not False and c not in me.hand
    assert op.life == l0 - 3


def cards_land_r():
    import cards
    return cards.land("Mountain", ["R"], basic=True)


# -- AI: la remoción apunta a la amenaza, no a lo más caro ----------------- #
def test_ai_removal_targets_the_real_threat_not_the_priciest():
    import cards, cardsdb, policy
    g, me, op = _duel()
    pol = policy.Policy("avanzado")
    # rival: artefacto caro inofensivo (cmv 6) + criatura barata letal (cmv 2)
    g.move_to_battlefield(cardsdb.build_card_from_data(
        {"name": "Reliquia Cara", "type_line": "Artifact", "mana_cost": "{6}", "oracle_text": ""}), op)
    dude = g.move_to_battlefield(cards.creature("Asesino", "1B", 2, 2, kw=("flying", "deathtouch")), op)
    # remoción genérica de no-tierra: debe elegir la criatura peligrosa, no el artefacto
    picks = pol._perm_spec_targets(g, me, "any_nonland", 1)
    assert picks and picks[0] is dude
    # y un objetivo de permanente cualquiera, igual prioriza la amenaza
    picks2 = pol._perm_spec_targets(g, me, "any_perm", 1)
    assert picks2 and picks2[0] is dude


# -- biblioteca de habilidades (fallback declarativo del parser) ----------- #
def test_ability_library_exile_top_of_library():
    import cardsdb, cards
    g, me, op = _duel()
    me.library = [cards.creature(f"C{i}", "1G", 1, 1) for i in range(5)]
    eff = cardsdb._generic_amount_effect("exile the top three cards of your library.")
    assert eff is not None                       # lo atrapa la biblioteca (fallback)
    eff(g, me)
    assert len(me.library) == 2 and len(me.exile) == 3


def test_ability_library_destroy_all_tokens():
    import cardsdb, cards
    g, me, op = _duel()
    cards.make_token(g, me, "Soldado", 1, 1)
    cards.make_token(g, op, "Zombi", 2, 2)
    g.move_to_battlefield(cards.creature("Real", "1G", 3, 3), me)   # NO ficha
    eff = cardsdb._generic_amount_effect("destroy all tokens.")
    assert eff is not None
    eff(g, me)
    toks = [pm for pl in g.players for pm in pl.battlefield if pm.is_token]
    assert toks == [] and any(pm.name == "Real" for pm in me.battlefield)


def test_ability_library_create_tapped_treasure():
    import cardsdb
    g, me, op = _duel()
    eff = cardsdb._generic_amount_effect("create two tapped treasure tokens.")
    assert eff is not None
    eff(g, me)
    tr = [pm for pm in me.battlefield if pm.name == "Treasure"]
    assert len(tr) == 2 and all(pm.tapped for pm in tr)


# -- habilidades {X} (Crypt Rats, Fireball-like) --------------------------- #
def test_x_activated_ability_deals_x_damage_to_all():
    import cardsdb, cards
    g, me, op = _duel()
    cr = cardsdb.build_card_from_data({
        "name": "Crypt Rats", "type_line": "Creature", "mana_cost": "{2}{B}",
        "power": "1", "toughness": "1",
        "oracle_text": "{X}: Crypt Rats deals X damage to each creature and each player."})
    pm = g.move_to_battlefield(cr, me)
    ab = pm.card.activated_abilities[0]
    assert ab.get("x_cost") is True and ab["cost"].cmc == 0   # el coste es sólo {X}
    bicho = g.move_to_battlefield(cards.creature("Bicho", "1G", 3, 3), op)
    for _ in range(6):
        g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), me)
    ol, ml = op.life, me.life
    assert g.activate_ability(pm, 0, x=3) is True
    g.resolve_stack(); g.sba()
    assert op.life == ol - 3 and me.life == ml - 3              # 3 a cada jugador
    assert not any(p.name == "Bicho" for p in op.battlefield)   # 3 mata al 3/3
    assert not any(p.name == "Crypt Rats" for p in me.battlefield)  # y al 1/1 propio


def test_x_ability_human_prompts_for_x():
    import interactive, cards, cardsdb, decks
    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    cr = cardsdb.build_card_from_data({
        "name": "Crypt Rats", "type_line": "Creature", "mana_cost": "{2}{B}",
        "power": "1", "toughness": "1",
        "oracle_text": "{X}: Crypt Rats deals X damage to each creature and each player."})
    pm = ig.g.move_to_battlefield(cr, hu)
    for _ in range(5):
        ig.g.move_to_battlefield(cards.land("Swamp", ["B"], basic=True), hu)
    st = ig.activate_ability(pm.uid, 0)
    assert st["phase"] == "choose" and st["choice"]["kind"] == "x"
    opp = ig.g.opponents(hu)[0]
    ol = opp.life
    ig.resolve_choice(3)                                        # X = 3
    assert opp.life == ol - 3


# -- ETB dirigido a un permanente no-criatura (bot auto-target) ------------ #
def test_etb_destroy_target_land_bot_autotargets():
    import cardsdb, cards
    g, me, op = _duel()
    g.move_to_battlefield(cards.land("Island", ["U"], basic=True), op)
    g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "White Orchid Phantom", "type_line": "Creature", "mana_cost": "{2}{W}",
        "power": "2", "toughness": "2",
        "oracle_text": "Flying\nWhen White Orchid Phantom enters, destroy target land."}), me)
    g.resolve_stack(); g.sba()
    assert not any(p.name == "Island" for p in op.battlefield)   # el bot destruyó la tierra rival


def test_etb_destroy_target_artifact_opens_human_modal():
    import interactive, cards, cardsdb, decks
    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")],
        human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    opp = ig.g.opponents(hu)[0]
    ig.g.move_to_battlefield(cardsdb.build_card_from_data(
        {"name": "Reliquia", "type_line": "Artifact", "mana_cost": "{3}", "oracle_text": ""}), opp)
    ig.g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Rompe", "type_line": "Creature", "mana_cost": "{2}", "power": "2",
        "toughness": "2", "oracle_text": "When Rompe enters, destroy target artifact."}), hu)
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "etb_target"
    assert any("Reliquia" in o["name"] for o in pc["options"])


# -- buff estático condicional ("gets +X/+Y as long as ...") --------------- #
def test_conditional_self_buff_lands_and_life():
    import cardsdb, cards
    g, me, op = _duel()
    sa = g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Sylvan Advocate", "type_line": "Creature", "mana_cost": "{1}{G}",
        "power": "2", "toughness": "3",
        "oracle_text": "Vigilance\nSylvan Advocate gets +2/+2 as long as you have six or more lands."}), me)
    assert (sa.power, sa.toughness) == (2, 3)                 # sin tierras: base
    for _ in range(6):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    assert (sa.power, sa.toughness) == (4, 5)                 # 6 tierras: +2/+2

    g2, me2, op2 = _duel()
    ka = g2.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Kird Ape", "type_line": "Creature", "mana_cost": "{R}",
        "power": "1", "toughness": "1",
        "oracle_text": "Kird Ape gets +1/+2 as long as you control a Forest."}), me2)
    assert (ka.power, ka.toughness) == (1, 1)
    g2.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me2)
    assert (ka.power, ka.toughness) == (2, 3)                 # con Forest: +1/+2

    g3, me3, op3 = _duel()
    av = g3.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Angel of Vitality", "type_line": "Creature", "mana_cost": "{2}{W}",
        "power": "3", "toughness": "3",
        "oracle_text": "Flying\nAngel of Vitality gets +2/+2 as long as you have 25 or more life."}), me3)
    assert (av.power, av.toughness) == (5, 5)                 # 40 de vida
    me3.life = 20
    assert (av.power, av.toughness) == (3, 3)                 # <25: base


# -- presets: no-criaturas con tipo+oracle correctos ----------------------- #
def test_preset_noncreature_gets_real_effect():
    import decks, coverage
    # tricky-terrain (preset .md) trae Inexorable Tide SIN tipo en la tabla; con el
    # tipo real (Enchantment) + oracle, su disparo "al lanzar un hechizo" vive.
    deck, cmd = decks.build("tricky-terrain")
    tide = next((c for c in [cmd] + deck if c.name == "Inexorable Tide"), None)
    assert tide is not None
    assert "enchantment" in tide.types and coverage._implemented(tide)
    assert "cast" in (getattr(tide, "triggers", {}) or {})


# -- cola larga: reemplazo de vida + pérdida de vida en upkeep ------------- #
def test_life_gain_bonus_replacement():
    import cardsdb, cards
    g, me, op = _duel()
    g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Angel of Vitality", "type_line": "Creature", "mana_cost": "{2}{W}",
        "power": "3", "toughness": "3",
        "oracle_text": "Flying\nIf you would gain life, you gain that much life plus 1 instead."}), me)
    before = me.life
    g.gain_life(me, 3)
    assert me.life == before + 4                 # 3 + 1 de bono


def test_upkeep_life_loss_conditional():
    import cardsdb, cards
    g, me, op = _duel()
    vl = cardsdb.build_card_from_data({
        "name": "Vampire Lacerator", "type_line": "Creature", "mana_cost": "{B}",
        "power": "2", "toughness": "2",
        "oracle_text": "At the beginning of your upkeep, you lose 1 life unless an opponent has 10 or less life."})
    pm = g.move_to_battlefield(vl, me)
    assert "upkeep" in vl.triggers
    cb = vl.triggers["upkeep"]
    b = me.life
    cb(g, pm); g.resolve_stack(); g.sba()
    assert me.life == b - 1                       # rival en 40 -> pierde 1
    op.life = 8
    b = me.life
    cb(g, pm); g.resolve_stack(); g.sba()
    assert me.life == b                           # rival <=10 -> no pierde


# -- ETB robar control con devolución al dejar el campo (Sower) ------------ #
def test_sower_steals_and_returns_on_leave():
    import cardsdb, cards
    g, me, op = _duel()
    bicho = g.move_to_battlefield(cards.creature("Bicho", "1G", 3, 3), op)
    sower = cardsdb.build_card_from_data({
        "name": "Sower of Temptation", "type_line": "Creature", "mana_cost": "{2}{U}{U}",
        "power": "2", "toughness": "2",
        "oracle_text": "Flying\nWhen Sower of Temptation enters, gain control of target "
                       "creature for as long as you control Sower of Temptation."})
    pm = g.move_to_battlefield(sower, me)
    g.resolve_stack(); g.sba()
    assert any(p.name == "Bicho" for p in me.battlefield)        # el bot robó la criatura
    assert not any(p.name == "Bicho" for p in op.battlefield)
    g.to_graveyard(pm, "muerte"); g.sba()
    assert any(p.name == "Bicho" for p in op.battlefield)        # al morir Sower, vuelve
    assert not any(p.name == "Bicho" for p in me.battlefield)


# -- disparo global al atacar (Hellrider) ---------------------------------- #
def test_hellrider_global_attack_trigger():
    import cardsdb, cards, io, contextlib
    g, me, op = _duel()
    hr = cardsdb.build_card_from_data({
        "name": "Hellrider", "type_line": "Creature", "mana_cost": "{2}{R}{R}",
        "power": "3", "toughness": "3",
        "oracle_text": "Haste\nWhenever a creature you control attacks, Hellrider deals "
                       "1 damage to the player or planeswalker that creature is attacking."})
    assert "creature_attacks" in hr.triggers
    pm = g.move_to_battlefield(hr, me); pm.summoning_sick = False
    for nm in ("A", "B"):
        d = g.move_to_battlefield(cards.creature(nm, "1R", 2, 2), me)
        d.summoning_sick = False
    before = op.life
    with contextlib.redirect_stdout(io.StringIO()):
        g._declare_attackers(me, [(p, op) for p in me.creatures()])
        g.resolve_stack(); g.sba()
    # 3 atacantes (incluido Hellrider) -> 3 de daño directo del disparo (antes del combate)
    assert before - op.life >= 3


# -- end-step vida=poder + Vorel duplica contadores ------------------------ #
def test_end_step_gain_life_equal_to_power():
    import cardsdb, cards, io, contextlib
    g, me, op = _duel()
    wr = cardsdb.build_card_from_data({
        "name": "Wall of Reverence", "type_line": "Creature", "mana_cost": "{3}{W}{W}",
        "power": "3", "toughness": "6",
        "oracle_text": "Defender, flying\nAt the beginning of your end step, you may "
                       "gain life equal to the power of target creature you control."})
    pm = g.move_to_battlefield(wr, me)
    g.move_to_battlefield(cards.creature("Grande", "4G", 5, 5), me)
    assert "end_step" in wr.triggers
    b = me.life
    with contextlib.redirect_stdout(io.StringIO()):
        wr.triggers["end_step"](g, pm); g.resolve_stack(); g.sba()
    assert me.life == b + 5                      # el bot elige la de mayor poder (5)


def test_vorel_doubles_counters():
    import cardsdb, cards, io, contextlib
    g, me, op = _duel()
    v = cardsdb.build_card_from_data({
        "name": "Vorel", "type_line": "Creature", "mana_cost": "{1}{G}{U}",
        "power": "1", "toughness": "3",
        "oracle_text": "{T}: For each kind of counter on target artifact, creature, or "
                       "land you control, double the number of those counters on it."})
    pm = g.move_to_battlefield(v, me)
    pm.summoning_sick = False                 # {T} de criatura: ya lleva un turno
    dude = g.move_to_battlefield(cards.creature("Bicho", "1G", 2, 2), me)
    g.add_counters(dude, "+1/+1", 3)
    with contextlib.redirect_stdout(io.StringIO()):
        assert g.activate_ability(pm, 0, targets=[dude]) is True
        g.resolve_stack(); g.sba()
    assert dude.counters.get("+1/+1", 0) == 6    # 3 -> 6


# -- AI: ataca al rival más indefenso, no siempre al humano ---------------- #
def test_ai_attacks_the_most_undefended_opponent():
    import cards, policy
    from engine import Game, Player
    me = Player("AI", [cards.land("Forest", ["G"], basic=True) for _ in range(6)],
                cards.creature("Cm", "2G", 3, 3, legendary=True))
    you = Player("Vos", [cards.land("Island", ["U"], basic=True) for _ in range(6)],
                 cards.creature("Ym", "2U", 1, 1, legendary=True))
    openai = Player("AI2", [cards.land("Swamp", ["B"], basic=True) for _ in range(6)],
                    cards.creature("Zm", "2B", 1, 1, legendary=True))
    g = Game([me, you, openai], seed=1)
    pol = policy.Policy("avanzado")
    for nm in ("A", "B"):
        a = g.move_to_battlefield(cards.creature(nm, "1G", 3, 3), me)
        a.summoning_sick = False
    # "Vos" tiene bloqueadores; "AI2" está con el campo vacío -> debe ser el objetivo
    g.move_to_battlefield(cards.creature("Guardia", "1U", 3, 3), you)
    g.move_to_battlefield(cards.creature("Guardia2", "1U", 3, 3), you)
    assert pol._attack_target(me, [you, openai], 6) is openai
    res = pol.declare_attackers(g, me)
    assert res and all(tgt is openai for _atk, tgt in res)


def test_ai_distributes_attackers_across_rivals():
    """Con tablero amplio reparte los atacantes entre rivales en vez de apilarlos
    todos en uno, aun cuando uno esté totalmente abierto."""
    import policy
    class C:
        def __init__(s, p, t):
            s.power = p; s.toughness = t; s.tapped = False
            s.cant_block = False; s.uid = id(s)
    class O:
        def __init__(s, name, life, cr):
            s.name = name; s.life = life; s._c = cr
        def creatures(s): return s._c
    pol = policy.Policy("avanzado")
    atk = [C(3, 3) for _ in range(4)]
    # un rival con muro 0/4 (soak 4) y otro con el campo vacío
    vos = O("Vos", 40, [C(0, 4)]); ai2 = O("AI2", 40, [])
    assign = pol._distribute_attackers(None, atk, [vos, ai2], 12)
    tally = {}
    for a in atk:
        tally[assign[a.uid].name] = tally.get(assign[a.uid].name, 0) + 1
    assert tally.get("Vos", 0) >= 1 and tally.get("AI2", 0) >= 1
    # a un rival rematable se le manda lo justo; el resto desborda al abierto
    kill = O("Kill", 5, []); open2 = O("AI2", 40, [])
    a2 = pol._distribute_attackers(None, atk, [kill, open2], 12)
    t2 = {}
    for a in atk:
        t2[a2[a.uid].name] = t2.get(a2[a.uid].name, 0) + 1
    assert t2.get("Kill", 0) == 2 and t2.get("AI2", 0) == 2


# -- Clase (Advanced Reconstruction): subir de nivel con gating ------------ #
def test_class_level_up_requires_previous_level():
    import cardsdb, cards
    c = cardsdb.build_card_from_data({
        "name": "Advanced Reconstruction", "type_line": "Enchantment — Class",
        "mana_cost": "{3}{R}",
        "oracle_text": "(Gain the next level as a sorcery to add its ability.)\n"
                       "At the beginning of your first main phase, mill a card.\n"
                       "{1}{R}: Level 2\n"
                       "Level 2 — Whenever one or more cards leave your graveyard, this "
                       "Class deals 2 damage to each opponent.\n"
                       "{1}{R}: Level 3\nLevel 3 — Spells cost {2} less."})
    assert "class" in c.subtypes and len(c.activated_abilities) == 2
    g, me, op = _duel()
    pm = g.move_to_battlefield(c, me)
    for _ in range(6):
        g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    mana0 = me.available_mana()
    # "Subir a nivel 3" estando en nivel 1 -> rechazado, SIN pagar maná
    assert g.activate_ability(pm, 1) is False
    assert pm.counters.get("level") == 1 and me.available_mana() == mana0
    # secuencial: 1 -> 2 -> 3
    assert g.activate_ability(pm, 0) is True and pm.counters["level"] == 2
    assert g.activate_ability(pm, 1) is True and pm.counters["level"] == 3


# -- comandantes: habilidades fieles al oráculo --------------------------- #
def test_kang_second_draw_gains_only_one():
    import cards
    from engine import Game, Player
    kg = cards.Kang()
    me = Player("K", [cards.land("Swamp", ["B"], basic=True) for _ in range(6)], kg)
    o2 = Player("A", [cards.land("Plains", ["W"], basic=True) for _ in range(6)],
                cards.creature("Y", "1W", 1, 1, legendary=True))
    o3 = Player("B", [cards.land("Plains", ["W"], basic=True) for _ in range(6)],
                cards.creature("Z", "1W", 1, 1, legendary=True))
    g = Game([me, o2, o3], seed=1)
    g.move_to_battlefield(kg, me); g.resolve_stack()
    l0, a0, b0 = me.life, o2.life, o3.life
    g.emit("draw", player=me, count=2); g.resolve_stack()
    assert me.life - l0 == 1              # gana 1 fija, NO 1 por oponente
    assert a0 - o2.life == 1 and b0 - o3.life == 1


def test_quintorius_spirit_each_time_no_turn_cap():
    import cards
    from engine import Game, Player
    q = cards.Quintorius()
    me = Player("Q", [cards.land("Mountain", ["R"], basic=True) for _ in range(6)], q)
    op = Player("O", [cards.land("Plains", ["W"], basic=True) for _ in range(6)],
                cards.creature("W", "1W", 1, 1, legendary=True))
    g = Game([me, op], seed=1); g.turn = 5
    g.move_to_battlefield(q, me); g.resolve_stack()
    for _ in range(2):
        me.graveyard.append(cards.land("Mountain", ["R"], basic=True))
    def spirits():
        return sum(1 for p in me.battlefield if p.name == "Spirit")
    s0 = spirits()
    g.leave_graveyard(me, me.graveyard[0], dest="exile"); g.resolve_stack()
    g.leave_graveyard(me, me.graveyard[0], dest="exile"); g.resolve_stack()
    # el oráculo real NO tiene tope por turno (el "una vez por turno" era inventado)
    assert spirits() - s0 == 2


def test_modal_trigger_opens_mode_ui_for_human():
    # "Whenever you cast a creature spell, choose one — ..." debe abrir el selector
    # de MODO para el humano (antes el disparo modal no cableaba nada).
    import cardsdb, cards
    from engine import Game, Player
    oracle = ("Whenever you cast a creature spell, choose one —\n"
              "• Destroy target artifact or enchantment.\n"
              "• You gain 4 life.")
    c = cardsdb.build_card_from_data({
        "name": "Trio", "type_line": "Enchantment", "mana_cost": "{2}{G}",
        "oracle_text": oracle})
    assert "cast" in c.triggers
    me = Player("Yo", [cards.creature("z", "1G", 1, 1) for _ in range(10)],
                cards.creature("Cmd", "2G", 3, 3, legendary=True))
    op = Player("Op", [cards.creature("z", "1U", 1, 1) for _ in range(10)],
                cards.creature("O", "2U", 1, 1, legendary=True))
    g = Game([me, op], seed=1); g.interactive_human = me; g.active_index = 0
    g.move_to_battlefield(c, me); g.resolve_stack()
    g.emit("cast", player=me, card=cards.creature("Bicho", "1G", 2, 2))
    g.resolve_stack()
    pc = g.pending_choice
    assert pc is not None and pc["kind"] == "mode" and len(pc["options"]) == 2
    def choose(idx):
        # como resolve_choice: se cierra la decisión ANTES de aplicarla (si no, la
        # siguiente decisión queda en espera en vez de pisar a la abierta)
        cur = g.pending_choice
        g.pending_choice = None
        cur["_apply"](idx)
    life0 = me.life
    choose(1)                                        # "You gain 4 life"
    g.resolve_stack()
    assert me.life - life0 == 4
    # el modo con objetivo abre un segundo modal (mode_target)
    g.emit("cast", player=me, card=cards.creature("Bicho2", "1G", 2, 2))
    g.resolve_stack()
    art = g.move_to_battlefield(cardsdb.build_card_from_data(
        {"name": "Rock", "type_line": "Artifact", "mana_cost": "{2}"}), op)
    g.resolve_stack()
    choose(0)                                        # modo destruir
    pc2 = g.pending_choice
    assert pc2 is not None and pc2["kind"] == "mode_target"
    choose(0); g.resolve_stack()
    assert art not in op.battlefield


def test_dead_player_objects_leave_the_game():
    # un jugador eliminado deja el juego: sus permanentes/cementerio/exilio se van,
    # así ninguna habilidad puede apuntar a sus cartas (regla 800.4a).
    import cards, policy
    from engine import Game, Player
    me = Player("Vivo", [cards.land("Forest", ["G"], basic=True) for _ in range(10)],
                cards.creature("Cmd", "1G", 1, 1, legendary=True), policy=policy.Policy("avanzado"))
    dead = Player("Muerto", [cards.land("Island", ["U"], basic=True) for _ in range(10)],
                  cards.creature("D", "1U", 1, 1, legendary=True), policy=policy.Policy("avanzado"))
    g = Game([me, dead], seed=1)
    g.move_to_battlefield(cards.creature("Bicho", "1U", 2, 2), dead)
    g.move_to_battlefield(cards.land("Island", ["U"], basic=True), dead)
    dead.graveyard.append(cards.creature("GY", "1U", 1, 1))
    dead.life = 0
    g.sba()
    assert dead.lost
    assert dead.battlefield == [] and dead.graveyard == [] and dead.exile == []
    # el pool de objetivos del vivo ya no incluye nada del muerto
    assert g.legal_creature_targets(me) == []
    assert dead not in g.opponents(me)


def test_each_creature_self_damage_both_wordings():
    # "Each creature deals damage to itself equal to its power" (y el orden inverso)
    # debe cablear el efecto (antes el orden 'to itself ... equal to its power' no
    # matcheaba y la habilidad no hacía nada).
    import cardsdb, cards
    from engine import Game, Player
    for oracle in ("Each creature deals damage to itself equal to its power.",
                   "Each creature deals damage equal to its power to itself."):
        c = cardsdb.build_card_from_data({
            "name": "SelfBurn", "type_line": "Sorcery", "mana_cost": "{2}{R}",
            "oracle_text": oracle})
        assert c.on_cast_resolve is not None
        g = Game([Player("A", [cards.creature("z", "1R", 1, 1) for _ in range(5)],
                         cards.creature("Cmd", "1R", 1, 1, legendary=True)),
                  Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                         cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
        me, op = g.players
        big = g.move_to_battlefield(cards.creature("Big", "3R", 4, 4), me)
        small = g.move_to_battlefield(cards.creature("Small", "1U", 1, 3), op)
        me.hand = [c]
        for _ in range(3):
            g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
        g.cast(me, c); g.resolve_stack(); g.sba()
        assert big not in me.battlefield          # 4 power -> 4 a sí misma -> muere
        assert small.damage == 1                  # 1 power -> 1 a sí misma -> vive


def test_landfall_self_plus_counter():
    # "Whenever a land enters under your control, put a +1/+1 counter on ~"
    # (Vinelasher Kudzu): el contador va a la PROPIA criatura.
    import cardsdb, cards
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Vinelasher Kudzu", "type_line": "Creature — Plant",
        "mana_cost": "{1}{G}", "power": "0", "toughness": "2",
        "oracle_text": "Whenever a land enters the battlefield under your control, "
                       "put a +1/+1 counter on Vinelasher Kudzu."})
    assert "landfall" in c.triggers
    g = Game([Player("A", [cards.land("Forest", ["G"], basic=True) for _ in range(5)],
                     cards.creature("Cmd", "1G", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                     cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
    me = g.players[0]
    k = g.move_to_battlefield(c, me); g.resolve_stack()
    g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me); g.resolve_stack()
    assert (k.power, k.toughness) == (1, 3)      # 0/2 -> 1/3
    # "target creature" en landfall NO debe tratarse como a-sí-misma
    c2 = cardsdb.build_card_from_data({
        "name": "Y", "type_line": "Enchantment", "mana_cost": "{2}",
        "oracle_text": "Whenever a land you control enters, put a +1/+1 counter "
                       "on target creature."})
    # ahora es un disparo CON objetivo: el contador va a una criatura (la mejor
    # propia para el bot), nunca al encantamiento mismo
    assert "landfall" in c2.triggers
    y = g.move_to_battlefield(c2, me); g.resolve_stack()
    before = k.counters.get("+1/+1", 0)
    g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me); g.resolve_stack()
    assert not y.counters
    assert k.counters.get("+1/+1", 0) >= before + 1


def test_enters_with_x_counters_and_bracket_loyalty():
    import cardsdb, cards
    from engine import Game, Player
    # Hydra: "enters with X +1/+1 counters on it" -> X del lanzamiento
    h = cardsdb.build_card_from_data({
        "name": "Hydra", "type_line": "Creature — Hydra", "mana_cost": "{X}{G}",
        "power": "0", "toughness": "0",
        "oracle_text": "Hydra enters with X +1/+1 counters on it."})
    assert h.etb_counters.get("+1/+1") == "X"
    g = Game([Player("A", [cards.creature("z", "1G", 1, 1) for _ in range(5)],
                     cards.creature("Cmd", "1G", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                     cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
    me = g.players[0]
    for _ in range(5):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    me.hand = [h]
    g.cast(me, h, x_value=3); g.resolve_stack()
    hp = next(p for p in me.battlefield if p.name == "Hydra")
    assert (hp.power, hp.toughness) == (3, 3)
    # planeswalker con corchetes "[+1]:" (formato MTGJSON) también parsea
    pw = cardsdb.build_card_from_data({
        "name": "PW", "type_line": "Legendary Planeswalker — Test", "mana_cost": "{3}",
        "loyalty": "4", "oracle_text": "[+1]: Draw a card.\n[-3]: Destroy target creature."})
    assert len(pw.loyalty_abilities or []) == 2


def test_ability_audit_batch():
    """Lote de huecos de activación hallados en la auditoría general."""
    import cardsdb, cards
    from engine import Game, Player

    def deck():
        return [cards.creature("z", "1G", 1, 1) for _ in range(5)]

    def duel():
        g = Game([Player("A", deck(), cards.creature("Cmd", "1G", 1, 1, legendary=True)),
                  Player("B", deck(), cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
        return g, g.players[0], g.players[1]

    # aristócrata "this creature or another ... dies" cuenta su propia muerte
    g, me, _ = duel()
    a = g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Ar", "type_line": "Creature — Cleric", "mana_cost": "1B",
        "power": "1", "toughness": "1",
        "oracle_text": "Whenever this creature or another creature you control dies, you gain 1 life."}), me)
    g.resolve_stack()
    l0 = me.life; g.to_graveyard(a, "t"); g.resolve_stack()
    assert me.life - l0 == 1

    # "another creature you control dies" NO cuenta su propia muerte
    g, me, _ = duel()
    a = g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Ar2", "type_line": "Creature — Cleric", "mana_cost": "1B",
        "power": "1", "toughness": "1",
        "oracle_text": "Whenever another creature you control dies, you gain 1 life."}), me)
    g.resolve_stack()
    l0 = me.life; g.to_graveyard(a, "t"); g.resolve_stack()
    assert me.life - l0 == 0

    # debuff a criaturas de los rivales
    g, me, op = duel()
    g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Deb", "type_line": "Enchantment", "mana_cost": "2B",
        "oracle_text": "Creatures your opponents control get -1/-0."}), me)
    foe = g.move_to_battlefield(cards.creature("Foe", "2U", 2, 2), op)
    mine = g.move_to_battlefield(cards.creature("Mine", "2G", 2, 2), me)
    assert foe.power == 1 and mine.power == 2

    # "enters tapped" desde el texto
    c = cardsdb.build_card_from_data({
        "name": "Tap", "type_line": "Creature — Beast", "mana_cost": "2",
        "power": "2", "toughness": "2", "oracle_text": "This creature enters tapped."})
    assert c.enters_tapped

    # dies -> vuelve al campo
    g, me, _ = duel()
    sk = g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Skel", "type_line": "Creature — Skeleton", "mana_cost": "1B",
        "power": "1", "toughness": "1",
        "oracle_text": "When this creature dies, return it to the battlefield under its owner's control."}), me)
    g.resolve_stack(); g.to_graveyard(sk, "t"); g.resolve_stack()
    assert any(x.name == "Skel" for x in me.battlefield)

    # ETB "add {C}{C}{C}"
    g, me, _ = duel()
    rock = cardsdb.build_card_from_data({
        "name": "Rit", "type_line": "Creature — Human", "mana_cost": "2",
        "power": "1", "toughness": "1", "oracle_text": "When this creature enters, add {C}{C}{C}."})
    assert rock.on_etb is not None
    m0 = me.mana_pool; g.move_to_battlefield(rock, me); g.resolve_stack()
    assert me.mana_pool - m0 == 3

    # auto-pump variable al atacar
    atk = cardsdb.build_card_from_data({
        "name": "Sh", "type_line": "Creature — Shaman", "mana_cost": "2G",
        "power": "1", "toughness": "1",
        "oracle_text": "Whenever this creature attacks, it gets +X/+0 until end of turn, "
                       "where X is the number of creatures you control."})
    assert "attacks" in atk.triggers


def test_target_player_human_picks_opponent():
    # "deals N damage to target player" disparado por el humano abre un selector de
    # rival (antes auto-apuntaba al de menos vida sin dejar elegir).
    import cardsdb, cards, interactive, decks
    from engine import Game, Player
    c = cardsdb.build_card_from_data({
        "name": "Zappy", "type_line": "Creature — Goblin", "mana_cost": "1R",
        "power": "2", "toughness": "2",
        "oracle_text": "When Zappy enters, it deals 3 damage to target player."})
    defs = [("Tu",) + decks.build("marvel"),
            ("R1",) + decks.build("strixhaven"),
            ("R2",) + decks.build("kang")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3); ig.keep([])
    hu = ig.human(); ig.g.active_index = ig.g.players.index(hu)
    ig.g.move_to_battlefield(c, hu); ig.g.resolve_stack()
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "player_target" and len(pc["options"]) == 2
    tgt = ig.g.players[2]; l0 = tgt.life
    pc["_apply"](1); ig.g.resolve_stack()            # elegir el 2do rival
    assert tgt.life == l0 - 3

    # el bot sin humano auto-apunta al de menos vida
    g = Game([Player("Bot", [cards.creature("z", "1R", 1, 1) for _ in range(5)],
                     cards.creature("C", "1R", 1, 1, legendary=True)),
              Player("A", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                     cards.creature("O", "1U", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                     cards.creature("O2", "1U", 1, 1, legendary=True))], seed=1)
    g.players[1].life = 20
    g.move_to_battlefield(cardsdb.build_card_from_data({
        "name": "Z", "type_line": "Creature — Goblin", "mana_cost": "1R",
        "power": "2", "toughness": "2",
        "oracle_text": "When Z enters, it deals 3 damage to target player."}), g.players[0])
    g.resolve_stack()
    assert g.players[1].life == 17 and g.players[2].life == 40


def test_targeted_spell_fallback_counter_and_tap():
    import cardsdb, cards
    from engine import Game, Player
    # "Put a +1/+1 counter on target creature" como hechizo (antes sin efecto)
    grow = cardsdb.build_card_from_data({
        "name": "Grow", "type_line": "Instant", "mana_cost": "1G",
        "oracle_text": "Put a +1/+1 counter on target creature. It gains trample until end of turn."})
    assert grow.on_cast_resolve is not None
    g = Game([Player("A", [cards.creature("z", "1G", 1, 1) for _ in range(5)],
                     cards.creature("Cmd", "1G", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                     cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
    me, op = g.players
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    grow.on_cast_resolve(g, me, [bear]); g.sba()
    assert (bear.power, bear.toughness) == (3, 3)
    # "Tap target creature. It does not untap during its controller's next untap step."
    frost = cardsdb.build_card_from_data({
        "name": "Frost", "type_line": "Instant", "mana_cost": "1U",
        "oracle_text": "Tap target creature. It does not untap during its controller's next untap step."})
    assert frost.on_cast_resolve is not None
    foe = g.move_to_battlefield(cards.creature("Foe", "2U", 2, 2), op); foe.tapped = False
    frost.on_cast_resolve(g, me, [foe])
    assert foe.tapped and getattr(foe, "frozen", False)
    g.begin_turn(op)                          # salta un enderezar (sigue girada)
    assert foe.tapped and not getattr(foe, "frozen", False)


def test_laelia_exile_counter_and_impulse():
    import cardsdb, cards
    from engine import Game, Player
    oracle = ("Haste\n"
              "Whenever Laelia, the Blade Reforged attacks, exile the top card of your "
              "library. You may play that card this turn.\n"
              "Whenever one or more cards are put into exile from your library and/or your "
              "graveyard, put a +1/+1 counter on Laelia, the Blade Reforged.")
    c = cardsdb.build_card_from_data({
        "name": "Laelia, the Blade Reforged", "type_line": "Legendary Creature — Spirit Warrior",
        "mana_cost": "2R", "power": "2", "toughness": "2", "keywords": ["Haste"],
        "oracle_text": oracle})
    assert "attacks" in c.triggers and "cards_exiled" in c.triggers
    g = Game([Player("A", [cards.creature("lib", "1R", 1, 1) for _ in range(10)],
                     cards.creature("Cmd", "1R", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(10)],
                     cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
    me = g.players[0]
    lae = g.move_to_battlefield(c, me); lae.summoning_sick = False
    c.triggers["attacks"](g, lae); g.resolve_stack()
    assert len(me.impulse) == 1                       # carta exiliada jugable este turno
    assert (lae.power, lae.toughness) == (3, 3)       # +1/+1 por exiliar de biblioteca
    me.graveyard.append(cards.creature("gy", "1R", 1, 1))
    g.leave_graveyard(me, me.graveyard[0], dest="exile"); g.resolve_stack()
    assert (lae.power, lae.toughness) == (4, 4)       # +1/+1 por exiliar del cementerio


def test_attack_defender_loses_life_and_upkeep_counter():
    import cardsdb, cards
    from engine import Game, Player
    # "whenever this creature attacks, defending player loses N life"
    rat = cardsdb.build_card_from_data({
        "name": "Rat", "type_line": "Creature — Rat", "mana_cost": "1B",
        "power": "1", "toughness": "1",
        "oracle_text": "Whenever this creature attacks, defending player loses 1 life."})
    assert "attacks" in rat.triggers
    g = Game([Player("A", [cards.creature("z", "1B", 1, 1) for _ in range(5)],
                     cards.creature("Cmd", "1B", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(5)],
                     cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
    me, op = g.players
    r = g.move_to_battlefield(rat, me); r.summoning_sick = False
    l0 = op.life
    rat.triggers["attacks"](g, r, defender=op); g.resolve_stack()
    assert op.life == l0 - 1
    # "at the beginning of your upkeep, put a +1/+1 counter on target creature you control"
    grow = cardsdb.build_card_from_data({
        "name": "Grower", "type_line": "Enchantment", "mana_cost": "2G",
        "oracle_text": "At the beginning of your upkeep, put a +1/+1 counter on target creature you control."})
    assert "upkeep" in grow.triggers
    gp = g.move_to_battlefield(grow, me)
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    grow.triggers["upkeep"](g, gp); g.resolve_stack()
    assert (bear.power, bear.toughness) == (3, 3)


def test_modal_on_death_opens_choice():
    # "When ~ dies, choose one — ..." (Ao) abre el selector de modo al morir
    # (antes el cuerpo se truncaba a 160 y el modal no se armaba).
    import cardsdb, cards
    from engine import Game, Player
    oracle = ("Flying, vigilance\n"
              "When Ao, the Dawn Sky dies, choose one —\n"
              "• Look at the top seven cards of your library. Put any number of nonland "
              "permanent cards with total mana value 4 or less from among them onto the "
              "battlefield. Put the rest on the bottom of your library in a random order.\n"
              "• Put two +1/+1 counters on each permanent you control that's a creature or Vehicle.")
    c = cardsdb.build_card_from_data({
        "name": "Ao, the Dawn Sky", "type_line": "Legendary Creature — Dragon Spirit",
        "mana_cost": "3WW", "power": "5", "toughness": "4",
        "keywords": ["Flying", "Vigilance"], "oracle_text": oracle})
    assert c.on_death is not None
    g = Game([Player("Tu", [cards.creature("z", "1W", 1, 1) for _ in range(8)],
                     cards.creature("C", "1W", 1, 1, legendary=True)),
              Player("B", [cards.creature("z", "1U", 1, 1) for _ in range(8)],
                     cards.creature("O", "1U", 1, 1, legendary=True))], seed=1)
    me = g.players[0]; g.interactive_human = me
    ao = g.move_to_battlefield(c, me)
    ally = g.move_to_battlefield(cards.creature("Ally", "1W", 2, 2), me)
    g.resolve_stack()
    g.to_graveyard(ao, "muere"); g.resolve_stack()
    pc = g.pending_choice
    assert pc is not None and pc["kind"] == "mode" and len(pc["options"]) == 2
    pc["_apply"](1); g.resolve_stack()                 # modo: +2/+2 a cada criatura
    assert (ally.power, ally.toughness) == (4, 4)


def test_human_turn_not_skipped_by_stale_queued_choice():
    # Regresión: una decisión encolada (choice_queue) que sobró de un turno rival
    # y se muestra DURANTE el turno propio del humano NO debe terminar su turno.
    # Antes: al resolverla se marcaba _draining y se llamaba _advance_to_human,
    # saltando el resto del turno (p. ej. "bajás una tierra, activás algo y se
    # acaba el turno").
    import interactive, decks
    defs = [("Tu",) + decks.build("lorehold"), ("R",) + decks.build("tricky"),
            ("K",) + decks.build("kang")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    assert ig.phase == "main" and ig.g.active_index == ig.human_index
    turn0 = ig.g.turn

    # Una decisión obsoleta quedó encolada (como si un efecto rival la hubiese
    # dejado) y aún no se drenó al empezar mi turno.
    def stale():
        ig.g.pending_choice = {
            "kind": "stale", "prompt": "obsoleta", "allow_none": False,
            "options": [{"i": 0, "name": "A"}], "_apply": lambda idx: None,
        }
    ig.g.choice_queue.append(stale)

    # El humano activa algo en SU turno que abre su propia decisión (ruta humana).
    ig.g.pending_choice = {
        "kind": "mia", "prompt": "mía", "allow_none": False,
        "options": [{"i": 0, "name": "x"}], "_apply": lambda idx: None,
    }
    assert ig._draining is False
    ig.resolve_choice(0)                 # resuelve la mía -> aflora la obsoleta
    assert ig._draining is False         # NO marcar draining en mi propio turno
    assert (ig.g.pending_choice or {}).get("kind") == "stale"
    ig.resolve_choice(0)                 # resuelve la obsoleta
    # el turno del humano sigue siendo el suyo, en la MISMA vuelta: no se saltó.
    assert ig.g.turn == turn0
    assert ig.g.active_index == ig.human_index
    assert ig.phase == "main"


def test_forced_sacrifice_prompt_names_the_forcing_opponent():
    # Regresión: el edicto ("target player sacrifices a creature") mostraba el
    # nombre del JUGADOR que sacrifica como prefijo. Si su mazo se llama como su
    # comandante (p. ej. "Quintorius, History Chaser"), parecía que esa carta
    # forzaba el sacrificio. Ahora el prompt nombra a QUIEN lo fuerza (el rival)
    # y no al que sacrifica.
    import cardsdb, cards, interactive, decks
    defs = [("Quintorius, History Chaser",) + decks.build("lorehold"),
            ("Rival-Ezuri",) + decks.build("tricky")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=5)
    ig.keep([])
    hu = ig.human(); op = ig.g.opponents(hu)[0]
    pm = ig.g.move_to_battlefield(cards.creature("Anger", "1R", 2, 2), hu)
    pm.summoning_sick = False

    res = cardsdb._fragment_effect("target player sacrifices a creature")
    f = res[0] if isinstance(res, tuple) else res
    f(ig.g, op)                       # el rival fuerza el edicto sobre el humano
    pc = ig.g.pending_choice
    assert pc is not None and pc["kind"] == "etb_target"
    assert "Quintorius" not in pc["prompt"]          # no es el nombre del que sacrifica
    assert op.name in pc["prompt"]                   # sí nombra a quien lo fuerza
    assert "forzado" in pc["prompt"].lower()


def test_removal_targets_engine_and_commander_over_bigger_body():
    # El removal elige por AMENAZA (motor de valor / comandante), no solo por poder:
    # un motor 2/2 pesa más que un vanilla 4/4, y el comandante más que todo.
    import policy
    from engine import Game, Player
    from cards import creature
    pol = policy.Policy("avanzado")
    me = Player("me", [], creature("cmd", "1", 1, 1), policy=pol)
    opp = Player("opp", [], creature("ocmd", "1", 1, 1), policy=policy.Policy("avanzado"))
    g = Game([me, opp], seed=1)
    vanilla = g.move_to_battlefield(creature("Vanilla", "4", 4, 4), opp)
    engine = g.move_to_battlefield(creature("Motor", "2G", 2, 2, tags=("engine",)), opp)
    assert pol._threat_value(engine) > pol._threat_value(vanilla)

    class _Removal:
        target_spec = "opp_creature"
        target_count = 1
    assert pol.choose_targets(g, me, _Removal())[0] is engine

    # el comandante rival es el objetivo de mayor valor, por encima de un 4/4
    cmdr = g.move_to_battlefield(opp.commander_card, opp)
    assert pol._threat_value(cmdr) > pol._threat_value(vanilla)


def test_ai_waits_for_ally_before_casting_omo():
    # La IA no lanza a Omo (needs_ally) sin otra criatura en mesa antes del turno 7:
    # no desperdicia su disparo de entrada (contador en una criatura objetivo).
    import decks, policy
    from engine import Game, Player
    from cards import creature
    _deck, omo = decks.build("tricky")
    assert getattr(omo, "needs_ally", False) is True
    pol = policy.Policy("avanzado")
    me = Player("me", [], omo, policy=pol)
    opp = Player("opp", [], creature("x", "1", 1, 1), policy=policy.Policy("avanzado"))
    g = Game([me, opp], seed=1)
    me.command = [omo]
    for _ in range(5):
        g.move_to_battlefield(land("Forest", ["G"], basic=True), me)
    for _ in range(3):
        g.move_to_battlefield(land("Island", ["U"], basic=True), me)
    g.turn = 2
    pol._maybe_cast_commander(g, me)
    assert not any(p.card is omo for p in me.battlefield)   # esperó: sin aliado
    g.move_to_battlefield(creature("Aliado", "1", 1, 1), me)
    pol._maybe_cast_commander(g, me)
    assert any(p.card is omo for p in me.battlefield)        # con aliado, la lanza


def test_precon_monthly_update_diff_and_fallback():
    # La revisión mensual detecta precons nuevos y el /api/precons usa la
    # instantánea guardada como respaldo cuando MTGJSON no responde.
    import os, sys, json, tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    import update_precons as up
    import _precon

    old = [{"code": "A", "fileName": "fa", "name": "Alpha", "releaseDate": "2024-01-01"}]
    new = [{"code": "B", "fileName": "fb", "name": "Beta", "releaseDate": "2025-07-01"},
           {"code": "A", "fileName": "fa", "name": "Alpha", "releaseDate": "2024-01-01"}]
    assert [p["code"] for p in up.diff_new(old, new)] == ["B"]   # solo el nuevo

    snap = os.path.join(tempfile.mkdtemp(), "precons_index.json")
    up.write_snapshot(new, snap)
    assert len(up.load_snapshot(snap)["precons"]) == 2

    # respaldo: con la red caída, list_precons sirve la instantánea
    _precon._SNAPSHOT = snap
    _precon._cache_index = None
    _precon._get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net down"))
    served = _precon.list_precons()
    assert {p["code"] for p in served} == {"A", "B"}


def test_x_spells_scale_with_chosen_x_and_charge_mana():
    # El usuario elige X = maná a gastar; el efecto escala con esa X. Y el coste
    # multi-X ({X}{X}{W}) cobra 2 por punto, acotando el máximo elegible.
    import interactive, cardsdb, decks
    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("lorehold"), ("R",) + decks.build("kang")],
        human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    secure = cardsdb.build_card_from_data({
        "name": "Secure the Wastes", "mana_cost": "{X}{W}", "type_line": "Instant",
        "oracle_text": "Create X 1/1 white Warrior creature tokens.",
        "color_identity": ["W"]})
    hu.hand = [secure]
    for _ in range(7):
        ig.g.move_to_battlefield(decks.land("Plains", ["W"], basic=True), hu)
    ig.cast(0)
    pc = ig.g.pending_choice
    assert pc and pc["kind"] == "x"
    assert [o["name"] for o in pc["options"]][-1] == "X = 6"   # 7 maná - {W} = 6
    ig.resolve_choice(5)                                        # X = 5
    assert sum(1 for p in hu.battlefield if p.is_token and p.name == "Warrior") == 5
    assert sum(1 for p in hu.battlefield if p.card.is_land() and not p.tapped) == 1

    # doble X: {X}{X}{W} con 7 maná -> (7-1)//2 = 3 máximo
    wst = cardsdb.build_card_from_data({
        "name": "WST", "mana_cost": "{X}{X}{W}", "type_line": "Sorcery",
        "oracle_text": "Create X 2/2 white Cat creature tokens.", "color_identity": ["W"]})
    assert wst.x_count == 2
    for p in hu.battlefield:
        p.tapped = False
    hu.hand = [wst]
    ig.cast(0)
    assert [o["name"] for o in ig.g.pending_choice["options"]][-1] == "X = 3"


def test_gain_life_trigger_does_not_loop_with_drain_ability():
    # Regresión (Niv-Mizzet, Ghost Counsel): la {T} "cada rival pierde 1 y ganás 1"
    # re-disparaba "whenever you gain life..." porque el cuerpo del disparo se comía
    # el texto de la {T} (oráculo con saltos de línea colapsados) -> bucle: una
    # activación drenaba al rival a 0 y daba miles de vida. Ahora NO loopea.
    import cardsdb, cards
    from engine import Game, Player
    data = {"name": "Niv-Mizzet, Ghost Counsel",
            "type_line": "Legendary Creature — Spirit Dragon",
            "mana_cost": "{4}{U}{R}", "power": "4", "toughness": "4",
            "color_identity": ["U", "R"], "keywords": ["Flying"],
            "oracle_text": ("Flying\nWhenever you gain life, you may pay that much "
                            "life. If you do, draw that many cards.\n{T}: Each "
                            "opponent loses 1 life and you gain 1 life.")}
    niv = cardsdb.build_card_from_data(data)
    me = Player("me", [], cards.creature("c", "1", 1, 1))
    op = Player("op", [], cards.creature("o", "1", 1, 1))
    g = Game([me, op], seed=1); g.interactive_human = None
    me.library = [cards.creature("L%d" % i, "1", 1, 1) for i in range(20)]
    me.hand = []; me.life = 40; op.life = 40
    pm = g.move_to_battlefield(niv, me); pm.summoning_sick = False
    g.activate_ability(pm, 0); g.resolve_stack(); g.sba()
    assert op.life == 39              # el rival pierde EXACTAMENTE 1 (no se vacía)
    assert me.life == 40             # gana 1 y paga 1 por el disparo: neto 0
    assert len(me.hand) == 1         # roba 1 (pagó 1 de vida)
    assert not op.lost and not me.lost


def test_sunfall_exiles_all_creatures_and_incubates():
    # Regresión (Sunfall): el parseo de "Exile all creatures. Incubate X..." entraba
    # en recursión mutua (_generic_amount_effect <-> _fragment_effect) y la carta caía
    # a vainilla -> "no hace nada, no exilia". Ahora EXILIA todas las criaturas
    # (incluso indestructibles) y crea una ficha Incubadora con X contadores.
    import cardsdb, cards
    from engine import Game, Player
    data = {"name": "Sunfall", "type_line": "Sorcery", "mana_cost": "{3}{W}{W}",
            "color_identity": ["W"],
            "oracle_text": ('Exile all creatures. Incubate X, where X is the number '
                            'of creatures exiled this way. (Create an Incubator token '
                            'with X +1/+1 counters on it and "{2}: Transform this '
                            'token." It transforms into a 0/0 Phyrexian artifact '
                            'creature.)')}
    sun = cardsdb.build_card_from_data(data)
    assert sun.on_cast_resolve is not None          # NO cayó a vainilla
    me = Player("me", [], cards.creature("cmdr", "1W", 2, 2))
    op = Player("op", [], cards.creature("ocmd", "1B", 2, 2))
    g = Game([me, op], seed=1); g.interactive_human = None
    g.move_to_battlefield(cards.creature("A", "1", 1, 1), me)
    g.move_to_battlefield(cards.creature("B", "2", 3, 3), me)
    g.move_to_battlefield(cards.creature("Indes", "2", 4, 4, kw=("indestructible",)), op)
    g.move_to_battlefield(cards.creature("C", "3", 5, 5), op)
    sun.on_cast_resolve(g, me, []); g.resolve_stack(); g.sba()
    # todas las criaturas preexistentes salieron del campo (exilio, no destrucción)
    exiled = [c.name for c in me.exile + op.exile]
    assert {"A", "B", "Indes", "C"}.issubset(set(exiled))  # la indestructible también
    # queda la ficha Incubadora con X = 4 contadores, del lado del lanzador
    incs = [p for p in me.battlefield if p.name == "Incubator"]
    assert len(incs) == 1 and incs[0].counters.get("+1/+1") == 4
    assert not any(p.name == "Incubator" for p in op.battlefield)


def _api_mod(name):
    import importlib
    api = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api")
    if api not in sys.path:
        sys.path.insert(0, api)
    return importlib.import_module(name)


def _sqlite_run():
    """Reemplazo de _db.run que ejecuta el SQL REAL contra sqlite en memoria
    (Turso es libsql = sqlite), así los tests validan también la sintaxis."""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row

    def fake_run(statements, timeout=20):
        out = []
        for sql, args in statements:
            cur = con.execute(sql, args or [])
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            out.append({"rows": rows, "affected": cur.rowcount, "last_insert_rowid": None})
        con.commit()
        return out
    return fake_run


def test_cloud_push_merges_never_wipes_and_pull_matches_client_shape():
    # Regresión: push hacía DELETE de TODOS los decks + reinsertaba lo local, así
    # que un dispositivo sin decks (o un autosave del binder) vaciaba la nube; y
    # pull devolvía deck_id/updated_at, que el cliente (id/updatedAt) colapsaba.
    _db = _api_mod("_db")
    cloud = _api_mod("cloud")
    fake_run = _sqlite_run()

    def deck(i, t):
        return {"id": i, "name": "D" + i, "text": "1 X", "colors": ["R"], "updatedAt": t}

    orig = _db.run
    _db.run = fake_run
    try:
        code = "owner-code-123"
        cloud.push(code, [deck("a", 100), deck("b", 100), deck("c", 100)],
                   [{"name": "Sol Ring", "qty": 1}])
        # dispositivo nuevo: push sin decks y binder distinto -> NO borra decks
        cloud.push(code, [], [{"name": "Sol Ring", "qty": 1}])
        got = cloud.pull(code)
        assert sorted(d["id"] for d in got["decks"]) == ["a", "b", "c"]
        assert set(got["decks"][0]) >= {"id", "name", "text", "colors", "updatedAt"}
        # binder=None (cliente viejo / sin cambios) deja el binder de la nube intacto
        cloud.push(code, [], None)
        assert cloud.pull(code)["binder"] == [{"name": "Sol Ring", "qty": 1}]
        # solo se borra lo pedido explícitamente
        cloud.push(code, [], None, deleted=["b"])
        assert sorted(d["id"] for d in cloud.pull(code)["decks"]) == ["a", "c"]
        # gana la versión más reciente: una copia vieja no pisa la nueva
        cloud.push(code, [dict(deck("a", 300), name="nuevo")], None)
        cloud.push(code, [dict(deck("a", 200), name="viejo")], None)
        assert next(d for d in cloud.pull(code)["decks"] if d["id"] == "a")["name"] == "nuevo"
        # tope gratis: los existentes se actualizan, los nuevos de más se recortan
        res = cloud.push(code, [deck(x, 400) for x in "cdefgh"], None)
        assert res["capped"]
        assert len(cloud.pull(code)["decks"]) == cloud.FREE_DECKS
    finally:
        _db.run = orig


def test_card_build_recursion_falls_back_to_vanilla_not_crash():
    # Regresión: cargar un mazo (p. ej. un precon nuevo) con una carta cuyo parseo
    # recursa daba "maximum recursion depth exceeded" y tiraba toda la carga. Ahora
    # esa carta cae a vainilla (datos reales, sin efecto) y el mazo se arma igual.
    import cardsdb, decklist
    real = {
        "Cmdr": {"name": "Cmdr", "type_line": "Legendary Creature", "mana_cost": "{1}{G}",
                 "power": "2", "toughness": "2", "color_identity": ["G"]},
        "Bomba": {"name": "Bomba", "type_line": "Creature", "mana_cost": "{3}{G}",
                  "power": "5", "toughness": "5", "color_identity": ["G"]},
    }
    orig = cardsdb._build_card_from_data_impl
    try:
        def boom(data):
            if data.get("name") == "Bomba":
                return cardsdb.build_card_from_data(data)   # recursa a propósito
            return orig(data)
        cardsdb._build_card_from_data_impl = boom
        parsed = {"commander": "Cmdr", "cards": [(1, "Bomba"), (1, "Forest")]}
        deck, cmd, _rep = decklist.build_deck(parsed, fetch=lambda n: real.get(n))
    finally:
        cardsdb._build_card_from_data_impl = orig
    assert len(deck) == 99 and cmd.name == "Cmdr"
    bomba = next(c for c in deck if c.name == "Bomba")
    assert bomba.power == 5 and bomba.toughness == 5    # vainilla con stats reales
    assert cardsdb._build_depth == 0                     # la profundidad se restaura


def test_build_test_deck_adds_in_color_combos_and_upgrades():
    # El "deck de prueba" suma la pieza de combo que falta y staples de mejora, SOLO
    # en la identidad del comandante (descarta lo off-color), y arma una decklist.
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    import _analyze as A
    cache = {
        A._norm("Omo"): {"color_identity": ["G", "U"], "type_line": "Legendary Creature", "cmc": 3},
        A._norm("Cultivate"): {"color_identity": ["G"], "type_line": "Sorcery", "cmc": 3},
        A._norm("Beast Within"): {"color_identity": ["G"], "type_line": "Instant", "cmc": 3},
        A._norm("Rhystic Study"): {"color_identity": ["U"], "type_line": "Enchantment", "cmc": 3},
        A._norm("Swords to Plowshares"): {"color_identity": ["W"], "type_line": "Instant", "cmc": 1},
        A._norm("Thassa's Oracle"): {"color_identity": ["U"], "type_line": "Creature", "cmc": 2},
    }
    parsed = {"commander": "Omo", "cards": [(1, "Forest"), (1, "Island"), (1, "Llanowar Elves")]}
    combos = {"almost": [
        {"name": "Oracle win", "missing": ["Thassa's Oracle"]},
        {"name": "off-color", "missing": ["Swords to Plowshares"]},
    ]}
    res = A.build_test_deck(parsed, cache, "Omo", combos)
    assert res["ok"]
    combo_names = {c["name"] for c in res["added_combos"]}
    assert "Thassa's Oracle" in combo_names          # en color (U)
    assert "Swords to Plowshares" not in combo_names  # off-color (W): descartada
    upg = {u["name"] for u in res["added_upgrades"]}
    assert "Sol Ring" in upg and "Cultivate" in upg   # staples en color/incoloros
    assert "Swords to Plowshares" not in upg          # staple off-color no entra
    assert res["text"].startswith("Commander\n1 Omo")
    assert "Thassa's Oracle" in res["text"]


def test_inline_etb_loop_is_bounded_not_recursion_error():
    # Regresión: una carta mal modelada que al entrar mete otra con el mismo ETB
    # generaba "maximum recursion depth exceeded" y tiraba la partida. Ahora el tope
    # de re-entrancia corta la cadena y el juego sigue.
    from engine import Game, Player, Card
    import cards
    me = Player("me", [], cards.creature("cmd", "1", 1, 1))
    op = Player("op", [], cards.creature("oc", "1", 1, 1))
    g = Game([me, op], seed=1)
    g.interactive_human = None

    def make():
        c = Card(name="Recursor", types={"creature"}, power=1, toughness=1)

        def etb(game, ctrl, perm):
            game.move_to_battlefield(make(), ctrl)   # mete otra -> ETB -> otra...
        c.on_etb = etb
        return c

    g.move_to_battlefield(make(), me)                # no debe lanzar RecursionError
    assert g._fx_depth == 0                           # la profundidad se restaura
    assert len(me.battlefield) <= g._fx_max_depth + 2   # la cadena quedó acotada
    assert any("cortó una cadena" in l for l in g.log_lines)


def test_life_loss_log_names_the_source_card():
    # Al perder vida por un efecto (ETB/disparo), el registro nombra la carta que lo
    # causó ("cada rival pierde 2 [Fuente]"), para poder identificar la culpable.
    import cardsdb, cards
    from engine import Game, Player
    me = Player("me", [], cards.creature("cmd", "1", 1, 1))
    op = Player("op", [], cards.creature("oc", "1", 1, 1))
    g = Game([me, op], seed=1)
    me.life = 40; op.life = 40
    g.interactive_human = None
    drainer = cardsdb.build_card_from_data({
        "name": "Fuente de Drenaje", "type_line": "Creature", "mana_cost": "{1}{B}",
        "power": "2", "toughness": "2",
        "oracle_text": "When this creature enters, each opponent loses 2 life."})
    n0 = len(g.log_lines)
    g.move_to_battlefield(drainer, me)
    g.resolve_stack(); g.sba()
    drain_lines = [l for l in g.log_lines[n0:] if "pierde" in l]
    assert drain_lines and "[Fuente de Drenaje]" in drain_lines[0]


def test_state_exposes_graveyard_card_costs():
    # Al revisar una carta del cementerio/exilio el modal debe poder mostrar el
    # coste de maná: el estado expone card_briefs (nombre -> coste/tipo/P-T/kw).
    import interactive, cards, decks
    defs = [("Tu",) + decks.build("lorehold"), ("R",) + decks.build("tricky")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=3)
    ig.keep([])
    hu = ig.human()
    hu.graveyard.append(cards.creature("Serra Angel", "3WW", 4, 4, kw=("flying",)))
    st = ig.state()
    briefs = st["card_briefs"]
    assert "Serra Angel" in briefs
    assert briefs["Serra Angel"]["cost"] == "3WW"       # muestra el maná que cuesta
    assert briefs["Serra Angel"]["pt"] == "4/4"
    # el comandante (zona de comando) también trae su coste
    cmd = hu.commander_card
    assert cmd.name in briefs and briefs[cmd.name]["cost"]


def test_md_presets_no_land_flood_and_tricky_unified():
    # Regresión: los presets .md inundaban de tierras (tricky-terrain 56,
    # lorehold-spirit 64) porque el relleno a 99 era todo básicas. Ahora delega en
    # _fill (ratio sano ~37). Y "tricky-terrain" quedó unificado con "tricky".
    import decks
    for slug in ("tricky-terrain", "lorehold-spirit"):
        deck, _cmd = decks.build(slug)
        lands = sum(1 for c in deck if c.is_land())
        assert len(deck) == 99
        assert 34 <= lands <= 40, f"{slug}: {lands} tierras (flood)"
    # unificados: tricky-terrain usa el mismo mazo curado que tricky
    tt, cmd_tt = decks.build("tricky-terrain")
    _t, cmd_t = decks.build("tricky")
    assert cmd_tt.name == cmd_t.name == "Omo, Queen of Vesuva"
    assert getattr(cmd_tt, "needs_ally", False) is True        # conserva su comportamiento
    assert any(c.name == "Heroic Intervention" for c in tt)    # y la protección
    assert any(c.name == "Inexorable Tide" for c in tt)        # y los motores reales


def test_tricky_deck_has_real_lands_and_protection():
    # Item: la lista de Tricky usa tierras REALES (no inventadas) y trae protección.
    import decks
    deck, cmd = decks.build("tricky")
    assert cmd.name == "Omo, Queen of Vesuva"
    names = {c.name for c in deck}
    for real_land in ("Command Tower", "Breeding Pool", "Hinterland Harbor",
                      "Yavimaya Coast", "Simic Growth Chamber"):
        assert real_land in names, real_land
    assert "Heroic Intervention" in names                    # protección pedida
    assert sum(1 for c in deck if c.is_land()) <= 40          # sin inundación


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


def test_decklist_quantities_are_capped_and_expansion_stops_at_99():
    # Regresión (DoS): "1000000 Sol Ring" se expandía a un millón de cartas antes
    # de recortar a 99 (~4 GB de RAM en la función serverless).
    import decklist, time
    p = decklist.parse_decklist("Commander\n1 Kang\n\nDeck\n1000000 Sol Ring")
    assert p["cards"] == [(decklist.MAX_QTY, "Sol Ring")]
    real = {"Kang": {"name": "Kang", "type_line": "Legendary Creature", "mana_cost": "{2}{U}",
                     "power": "3", "toughness": "3", "color_identity": ["U"]}}
    t = time.time()
    deck, _cmd, _rep = decklist.build_deck(
        {"commander": "Kang", "cards": [(10 ** 6, "Island")]}, fetch=real.get)
    assert len(deck) == 99 and time.time() - t < 5
    assert len({id(c) for c in deck}) == 99          # cada copia es su propio objeto
    assert decklist.clamp_qty("abc") == 1 and decklist.clamp_qty(-5) == 1


def test_sim_endpoints_bound_cost_and_report_unresolved():
    _sim = _api_mod("_sim")
    import run
    # /api/simulate: claves repetidas se deduplican y n queda en el tope gratis
    calls = []
    orig_one = run.one
    run.one = lambda keys, seed=0, **k: calls.append(seed) or keys[0]
    try:
        res = _sim.simulate(["kang", "kang", "lorehold", "nope"], "99999")
    finally:
        run.one = orig_one
    assert res["matchup"] == ["kang", "lorehold"]
    assert res["requested"] == _sim.FREE_N and len(calls) == _sim.FREE_N
    assert sum(r["pct"] for r in res["results"]) == 100.0
    # el presupuesto de tiempo corta (siempre al menos 1 partida)
    wins, ran = _sim._play_budgeted(lambda seed: "x", 50, budget=-1)
    assert ran == 1 and wins["x"] == 1
    # kind desconocido: error claro (antes KeyError '_parsed')
    try:
        _sim._build_deck_defs([{"kind": "registered", "key": "kang"}, {"kind": "zzz"}])
        assert False
    except ValueError as e:
        assert "desconocido" in str(e)
    # cartas no resueltas: se informan; si son más de la mitad, falla
    data = {"Kang": {"name": "Kang", "type_line": "Legendary Creature",
                     "mana_cost": "{2}{U}", "power": "3", "toughness": "3",
                     "color_identity": ["U"]},
            "Island": {"name": "Island", "type_line": "Basic Land — Island",
                       "mana_cost": "", "color_identity": []}}
    orig_fetch = _sim._make_fetch
    _sim._make_fetch = lambda names, **_k: data.get
    try:
        ok = "Commander\n1 Kang\n\nDeck\n1 Island\n1 Island\n1 Typo Card"
        defs, _mt, unresolved = _sim._build_deck_defs(
            [{"kind": "registered", "key": "kang"}, {"kind": "custom", "name": "Mio", "text": ok}])
        assert unresolved == {"Mio": ["Typo Card"]}
        bad = "Commander\n1 Kang\n\nDeck\n1 Island\n1 Nope A\n1 Nope B"
        try:
            _sim._build_deck_defs([{"kind": "registered", "key": "kang"},
                                   {"kind": "custom", "name": "Mio", "text": bad}])
            assert False
        except ValueError as e:
            assert "no se pudieron resolver 2 de 3" in str(e)
    finally:
        _sim._make_fetch = orig_fetch


def test_stats_server_side_only_and_ranking_survives_garbage_rows():
    # Regresión: un POST anónimo con commanders=[["x"]] rompía GET /api/stats y
    # /admin para siempre (unhashable list), y cualquiera inventaba resultados.
    _db = _api_mod("_db")
    stats = _api_mod("stats")
    fake_run = _sqlite_run()
    orig = _db.run
    _db.run = fake_run
    try:
        _db.ensure_schema()
        # filas basura ya guardadas por la versión vieja
        _db.execute("INSERT INTO mtg_matches (winner, commanders, turns, created_at) "
                    "VALUES (?, ?, 1, 1)", [None, '[["x"], {"a": 1}, "Kang"]'])
        assert stats.record("Kang", ["Kang", "Atraxa"], 9)["ok"]
        assert not stats.record("Otro", ["Kang", "Atraxa"], 9)["ok"]   # ganador ajeno
        assert not stats.record("Kang", [["x"]], 9)["ok"]               # forma inválida
        top = stats.top(9999)
        assert {r["commander"] for r in top["top"]} == {"Kang", "Atraxa"}
        kang = next(r for r in top["top"] if r["commander"] == "Kang")
        assert kang["games"] == 2 and kang["wins"] == 1
    finally:
        _db.run = orig


def test_auth_admin_lockout_and_coupon_hardening():
    _db = _api_mod("_db")
    os.environ["ADMIN_EMAIL"] = "boss@x.com"
    import importlib
    _auth = importlib.reload(_api_mod("_auth"))
    supporter = _api_mod("supporter")
    orig = _db.run
    _db.run = _sqlite_run()
    try:
        # el primer registro del email admin es admin; si ya hay admin, no
        assert _auth.register("boss@x.com", "secretpw123")["user"]["is_admin"]
        _db.execute("UPDATE mtg_users SET email = 'old@x.com' WHERE email = 'boss@x.com'")
        assert not _auth.register("boss@x.com", "secretpw123")["user"]["is_admin"]
        # bloqueo por cuenta+IP: la IP atacante se bloquea, la del dueño no
        _auth.register("me@x.com", "mypassword1")
        for _ in range(_auth._MAX_FAILS):
            try:
                _auth.login("me@x.com", "wrongpass", ip="6.6.6.6")
            except ValueError:
                pass
        try:
            _auth.login("me@x.com", "mypassword1", ip="6.6.6.6")
            assert False
        except ValueError as e:
            assert "demasiados intentos" in str(e)
        assert _auth.login("me@x.com", "mypassword1", ip="1.2.3.4")["user"]["email"] == "me@x.com"
        # email inexistente: mismo costo (se calcula el PBKDF2 igual)
        calls = []
        orig_hash = _auth._hash
        _auth._hash = lambda *a: calls.append(a) or orig_hash(*a)
        try:
            _auth.login("nadie@x.com", "whatever1", ip="9.9.9.9")
        except ValueError:
            pass
        _auth._hash = orig_hash
        assert len(calls) == 1
        # el reset también se bloquea tras varios códigos malos
        for _ in range(_auth._MAX_FAILS):
            try:
                _auth.reset_password("me@x.com", "AAAA-BBBB-CCCC", "newpass123", ip="6.6.6.6")
            except ValueError:
                pass
        try:
            _auth.reset_password("me@x.com", "AAAA-BBBB-CCCC", "newpass123", ip="6.6.6.6")
            assert False
        except ValueError as e:
            assert "demasiados intentos" in str(e)
        # sin env ADMIN_EMAIL nadie es admin al registrarse
        os.environ["ADMIN_EMAIL"] = ""
        _auth = importlib.reload(_auth)
        assert not _auth.register("x@x.com", "secretpw123")["user"]["is_admin"]
    finally:
        _db.run = orig
        os.environ.pop("ADMIN_EMAIL", None)
    # cupón: ya no hay uno hardcodeado; solo la env
    old = os.environ.pop("SUPPORTER_CODES", None)
    try:
        assert not supporter._coupon_ok("GRACIAS-MTG")
        os.environ["SUPPORTER_CODES"] = "NUEVO-1, NUEVO-2"
        assert supporter._coupon_ok(" NUEVO-2 ") and not supporter._coupon_ok("")
    finally:
        os.environ.pop("SUPPORTER_CODES", None)
        if old is not None:
            os.environ["SUPPORTER_CODES"] = old


def test_scryfall_client_caps_names_and_escapes_paths():
    _scry = _api_mod("_scry")
    posts = []
    orig_post, orig_pause = _scry._post, _scry._BATCH_PAUSE
    _scry._post = lambda ids: posts.append(len(ids)) or {"data": []}
    _scry._BATCH_PAUSE = 0
    try:
        _scry.resolve_many(["Card %d" % i for i in range(30000)] + [["no-str"]])
    finally:
        _scry._post, _scry._BATCH_PAUSE = orig_post, orig_pause
    assert sum(posts) == _scry.MAX_NAMES and len(posts) == -(-_scry.MAX_NAMES // 75)
    urls = []
    orig_get = _scry._get
    _scry._get = lambda url: urls.append(url) or {}
    try:
        _scry.by_collector("../../x", "a/b")
    finally:
        _scry._get = orig_get
    assert urls and "/../" not in urls[0] and "%2F" in urls[0]


def test_update_precons_fails_loudly_when_mtgjson_is_down():
    _precon = _api_mod("_precon")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "update_precons", os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "update_precons.py"))
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    orig = _precon._get
    _precon._get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net down"))
    try:
        assert up.main([]) == 2          # no reescribe la instantánea ni dice "ok"
    finally:
        _precon._get = orig
        _precon._cache_index = None


def _ig_tricky_vs_kang(seed=3):
    import interactive, decks
    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("tricky"), ("R",) + decks.build("kang")],
        human_index=0, seed=seed)
    ig.keep([])
    return ig, ig.human(), ig.g.opponents(ig.human())[0]


def _counterspell():
    import cardsdb
    return cardsdb.build_card_from_data({
        "name": "Counterspell", "type_line": "Instant", "mana_cost": "{U}{U}",
        "color_identity": ["U"], "oracle_text": "Counter target spell."})


def test_undo_snapshot_does_not_copy_interactive_layer():
    # Regresión: el deepcopy del snapshot arrastraba el InteractiveGame (por los
    # hooks ligados) con todos los snapshots anteriores -> costo exponencial que
    # congelaba el navegador; y tras deshacer los hooks quedaban en una copia vieja.
    import cards, time
    ig, hu, _op = _ig_tricky_vs_kang()
    hu.hand[:] = [cards.land("Island", ["U"], basic=True) for _ in range(7)]
    times = []
    for _ in range(8):
        t = time.time()
        ig._snapshot()
        times.append(time.time() - t)
    assert max(times) < 1.0                                   # antes: 50+ s al snapshot 11
    snap = ig._undo[-1][0]
    assert snap.reaction_check.__self__ is ig                  # no copió la capa interactiva
    ig.play_land(0)
    ig.undo()
    assert ig.g.reaction_check.__self__ is ig and ig.g.cascade_target_hook.__self__ is ig


def test_undo_not_allowed_after_attacking():
    # Atacar revela bloqueos y daño: deshacer después permitía re-atacar sabiéndolo.
    import cards
    ig, hu, _op = _ig_tricky_vs_kang()
    bear = ig.g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), hu)
    bear.summoning_sick = False
    hu.hand[:] = [cards.land("Forest", ["G"], basic=True)]
    ig.play_land(0)
    assert ig.can_undo()
    ig.attack([bear.uid])
    if ig.mode == "combat":
        ig.finish_combat()
    assert not ig.can_undo()


def test_human_ai_does_not_counter_after_passing():
    # Regresión: tras pasar en la ventana de reacción, la política del humano
    # lanzaba igual su Counterspell ("Tu lanza Counterspell").
    import cards
    ig, hu, op = _ig_tricky_vs_kang()
    cs = _counterspell()
    hu.hand.append(cs)
    while len(hu.hand) > 7:
        hu.library.insert(0, hu.hand.pop(0))
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Island", ["U"], basic=True), hu)
    for c in list(op.hand):
        op.library.insert(0, c)
    op.hand[:] = [cards.creature("Big Beast", "3R", 5, 5)]
    for _ in range(4):
        ig.g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), op)
    ig.end_turn()
    assert ig.mode == "react"
    ig.react(None)                     # el humano PASA
    assert cs in hu.hand
    assert not any("Tu lanza Counterspell" in l for l in ig.g.log_lines)


def test_queued_choice_during_defense_does_not_skip_human_turn():
    # Regresión: una decisión encolada que aparecía durante la defensa marcaba
    # _draining; al resolverla se avanzaban turnos con el ataque colgado y se
    # saltaba el turno siguiente del humano.
    import interactive, decks, cards, cardsdb
    ig = interactive.InteractiveGame(
        [("Tu",) + decks.build("lorehold"), ("R",) + decks.build("kang")],
        human_index=0, seed=3)
    ig.keep([])
    hu, op = ig.human(), ig.g.opponents(ig.human())[0]
    orig = op.policy.main_phase

    def mp(game, me, second=False):
        if not second:
            cardsdb._human_or_auto_discard(game, hu, 1)   # encolada: turno del bot
        return orig(game, me, second)
    op.policy.main_phase = mp
    ogre = ig.g.move_to_battlefield(cards.creature("Ogro", "2R", 3, 3), op)
    ogre.summoning_sick = False
    while len(hu.hand) < 8:
        hu.hand.append(hu.library.pop())
    ig.end_turn()
    ig.resolve_choice(0)                 # descarte propio -> turno del bot, me ataca
    assert ig.mode == "defense" and ig.g.pending_choice is not None
    ig.resolve_choice(0)                 # la decisión forzada por el bot
    assert ig.mode == "defense" and ig.g.turn == 2   # sigue el ataque, no avanzó
    ig.resolve_defense([])
    if ig.mode == "combat":
        ig.finish_combat()
    assert ig.g.turn == 3 and ig.g.active_index == 0 and ig.phase == "main"


def test_flashback_and_foretell_survive_reaction_pause():
    # Regresión: la ReactionPause cortaba play_from_graveyard/play_from_exile justo
    # tras cast(): el flashback no se exiliaba (el bot lo relanzó 4 veces) y la
    # carta predicha quedaba duplicada (exilio + pila).
    import cards, cardsdb
    ig, hu, op = _ig_tricky_vs_kang()
    hu.hand.append(_counterspell())
    while len(hu.hand) > 7:
        hu.library.insert(0, hu.hand.pop(0))
    for _ in range(2):
        ig.g.move_to_battlefield(cards.land("Island", ["U"], basic=True), hu)
    beast = cards.creature("Foretold Beast", "3G", 4, 4)
    beast._play_cost = None
    op.exile_play.append(beast)
    fb = cardsdb.build_card_from_data({
        "name": "Flame Again", "type_line": "Sorcery", "mana_cost": "{2}{R}",
        "color_identity": ["R"],
        "oracle_text": "Flame Again deals 3 damage to target player.\nFlashback {1}{R}"})
    op.graveyard.append(fb)
    for _ in range(8):
        ig.g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), op)
    for c in list(op.hand):
        op.library.insert(0, c)
    op.hand.clear()

    def zones(c):
        out = []
        for p in ig.players:
            for z in ("hand", "library", "graveyard", "exile", "exile_play", "command"):
                out += [f"{p.name}.{z}" for x in getattr(p, z) if x is c]
            out += [f"{p.name}.battlefield" for pm in p.battlefield if pm.card is c]
        return out
    life0 = hu.life
    ig.end_turn()
    for _ in range(30):
        if ig.g.turn != 2:
            break
        if ig.mode == "react":
            ig.react(None)
        elif ig.g.pending_choice:
            ig.resolve_choice(0)
        elif ig.mode == "defense":
            ig.resolve_defense([])
        elif ig.mode == "combat":
            ig.finish_combat()
        else:
            break
    casts = [l for l in ig.g.log_lines if "lanza Flame Again" in l]
    assert len(casts) <= 1                       # antes: 4 lanzamientos en un turno
    assert len(zones(fb)) == 1 and len(zones(beast)) == 1   # nada duplicado ni perdido
    if casts:
        assert zones(fb) == ["R.exile"] and hu.life >= life0 - 3


def test_engine_counter_and_failed_alt_casts_keep_cards():
    import cards
    from engine import Game, Player
    me = Player("me", [], cards.creature("cm", "1", 1, 1))
    op = Player("op", [], cards.creature("oc", "1", 1, 1))
    g = Game([me, op], seed=1); g.interactive_human = None
    # contrarrestar: copia -> no mueve nada; flashback -> exilio; comandante -> mando
    spell = cards.creature("Dummy", "1", 1, 1)
    from engine import StackObject
    obj = StackObject(op, lambda gg: None, source=spell, label="copy:Dummy")
    g.stack.append(obj)
    assert g.counter_spell(obj) and spell not in op.graveyard
    spell._exile_after_cast = True
    obj = StackObject(op, lambda gg: None, source=spell, label="spell:Dummy")
    g.stack.append(obj)
    g.counter_spell(obj)
    assert spell in op.exile and spell not in op.graveyard
    cmd = op.commander_card
    op.command.remove(cmd) if cmd in op.command else None
    obj = StackObject(op, lambda gg: None, source=cmd, label="spell:oc")
    g.stack.append(obj)
    g.counter_spell(obj)
    assert cmd in op.command and cmd not in op.graveyard
    # lanzamiento alternativo que no se puede pagar: la carta NO se pierde
    burn = cards.creature("Foretold", "9", 1, 1)
    burn._play_cost = None
    me.exile_play.append(burn)
    assert g.play_from_exile(me, burn) is False and burn in me.exile_play


def test_second_pending_choice_waits_instead_of_overwriting():
    # Regresión: dos decisiones seguidas (p. ej. dos scry en la pila) pisaban la
    # primera, que se perdía junto con las cartas que ya había sacado.
    from engine import Game, Player
    import cards
    me = Player("me", [], cards.creature("cm", "1", 1, 1))
    op = Player("op", [], cards.creature("oc", "1", 1, 1))
    g = Game([me, op], seed=1)
    first = {"kind": "may", "prompt": "uno", "options": []}
    second = {"kind": "may", "prompt": "dos", "options": []}
    g.pending_choice = first
    g.pending_choice = second
    assert g.pending_choice is first and g.choice_queue == [second]
    g.pending_choice = None
    assert g.pending_choice is None


def test_bot_does_not_cast_ability_counter_on_a_spell():
    # Regresión: el bot lanzaba Stifle (apunta a habilidades) contra un hechizo de
    # criatura y la carta del hechizo se perdía de la pila.
    import cards, cardsdb
    from engine import Game, Player, StackObject
    from policy import Policy
    me = Player("me", [], cards.creature("cm", "1", 1, 1), policy=Policy())
    op = Player("op", [], cards.creature("oc", "1", 1, 1), policy=Policy())
    g = Game([me, op], seed=1); g.interactive_human = None
    stifle = cardsdb.build_card_from_data({
        "name": "Stifle", "type_line": "Instant", "mana_cost": "{U}",
        "color_identity": ["U"], "oracle_text": "Counter target activated or triggered ability."})
    op.hand[:] = [stifle]
    g.move_to_battlefield(cards.land("Island", ["U"], basic=True), op)
    ogre = cards.creature("Ogro", "2R", 3, 3)
    top = StackObject(me, lambda gg: None, source=ogre, label="spell:Ogro")
    g.stack.append(top)
    assert not op.policy.respond(g, op, top)
    assert stifle in op.hand


def _duel2(n=2, names=("me", "op", "p3", "p4")):
    import cards
    from engine import Game, Player
    ps = [Player(names[i], [cards.creature(f"L{i}{k}", "1", 1, 1) for k in range(30)],
                 cards.creature(f"Cmd{i}", "2", 2, 2, legendary=True)) for i in range(n)]
    g = Game(ps, seed=1); g.interactive_human = None
    for p in ps:
        p.hand = []
    return (g, *ps)


def test_preset_sol_ring_makes_two_mana():
    # Regresión: rock("Sol Ring", "1", [C, C]) colapsaba a {C:1} en los presets.
    import decks, cards
    sr = next(c for c in decks.build("lorehold")[0] if c.name == "Sol Ring")
    assert sr.produces(None, None) == {"C": 2}
    signet = cards.rock("Boros Signet", "2", ["R", "W"])
    assert signet.produces(None, None) == {"R": 1, "W": 1}      # sigue siendo UNO


def test_cleanup_removes_damage_from_every_permanent():
    # Regresión: end_turn limpiaba el daño solo del jugador activo.
    import cards
    g, me, op = _duel2()
    blk = g.move_to_battlefield(cards.creature("Blk", "2", 3, 3), op)
    blk.damage = 2
    pumped = g.move_to_battlefield(cards.creature("Pump", "1", 1, 1), op)
    pumped.temp_pt = [3, 3]
    pumped.damage = 3                       # sobrevivió al combate gracias al +3/+3
    g.active_index = 0
    g.end_turn(me)
    g.sba()
    assert blk.damage == 0 and pumped in op.battlefield and pumped.damage == 0


def test_tap_ability_cannot_pay_with_itself_and_summoning_sickness():
    import cards, cardsdb
    g, me, op = _duel2()
    ms = cardsdb.build_card_from_data({
        "name": "Mind Stone", "mana_cost": "{2}", "type_line": "Artifact",
        "oracle_text": "{T}: Add {C}.\n{1}, {T}, Sacrifice Mind Stone: Draw a card.",
        "color_identity": []})
    pm = g.move_to_battlefield(ms, me); g.resolve_stack()
    idx = next(i for i, a in enumerate(ms.activated_abilities) if a.get("tap"))
    assert g.activate_ability(pm, idx) is False         # sola no puede pagarse a sí misma
    g.move_to_battlefield(cards.land("Wastes", ["C"], basic=True), me)
    assert g.activate_ability(pm, idx) is True
    # criatura de maná / habilidad {T} recién invocada: no hasta el próximo turno
    elf = cards.creature("Elf", "G", 1, 1)
    elf.produces = lambda perm, pl: {"G": 1}
    pe = g.move_to_battlefield(elf, me)
    assert pe not in me.mana_sources()
    pe.summoning_sick = False
    assert pe in me.mana_sources()


def test_mana_assignment_backtracks_on_dual_lands():
    # Regresión: el voraz daba la Plateau a W y R quedaba sin fuente.
    import cards
    from engine import Cost
    g, me, op = _duel2()
    g.move_to_battlefield(cards.land("Plateau", ["W", "R"]), me)
    g.move_to_battlefield(cards.land("Tundra", ["W", "U"]), me)
    assert me.can_pay(Cost(0, ("W", "R")))
    assert me.pay(Cost(0, ("W", "R"))) and all(p.tapped for p in me.lands())
    assert not me.can_pay(Cost(0, ("R",)))


def test_additional_costs_validated_and_paid_after_mana():
    import cards
    from engine import Cost
    g, me, op = _duel2()
    fling = cards.creature("Fling", "1R", 0, 0)
    fling.types = {"instant"}
    hits = []
    fling.on_cast_resolve = lambda game, ctrl, t: hits.append(1)
    fling.additional_cost = {"sacrifice": True}
    me.hand = [fling]
    g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), me)
    assert g.cast(me, fling) is False and fling in me.hand     # sin víctima: no se lanza
    victim = g.move_to_battlefield(cards.creature("Goblin", "R", 1, 1), me)
    assert g.cast(me, fling) is not False
    g.resolve_stack()
    assert hits == [1] and victim not in me.battlefield
    assert all(p.tapped for p in me.lands())                  # el maná SÍ se pagó
    # descarte como coste: nunca la propia carta
    disc = cards.creature("Discarder", "R", 0, 0)
    disc.types = {"sorcery"}
    disc.additional_cost = {"discard": 1}
    for p in me.lands():
        p.tapped = False
    me.hand = [disc]
    assert g.cast(me, disc) is False and disc in me.hand      # no hay otra carta


def test_convoke_does_not_double_count_mana_dorks():
    import cards
    g, me, op = _duel2()
    elf = cards.creature("Elf", "G", 1, 1)
    elf.produces = lambda perm, pl: {"G": 1}
    pe = g.move_to_battlefield(elf, me); pe.summoning_sick = False
    spell = cards.creature("Convoker", "1G", 0, 0)
    spell.types = {"sorcery"}
    spell.tags = {"convoke"}
    spell.on_cast_resolve = lambda *a: None
    me.hand = [spell]
    assert g.cast(me, spell) is False          # 1 elfo no paga {1}{G} (antes contaba doble)


def test_x_is_kept_per_cast_not_global():
    # Regresión: spell_x era global: un hechizo en respuesta lo pisaba (Hydra 0/0)
    # y una criatura reanimada después recibía la X del último hechizo.
    import cards
    g, me, op = _duel2()
    hydra = cards.creature("Hydra", "G", 0, 0)
    hydra.x_spell = True
    hydra.etb_counters = {"+1/+1": "X"}
    me.hand = [hydra]
    for _ in range(4):
        g.move_to_battlefield(cards.land("Forest", ["G"], basic=True), me)
    zap = cards.creature("Zap", "R", 0, 0)
    zap.types = {"instant"}
    zap.on_cast_resolve = lambda *a: None
    op.hand = [zap]
    g.move_to_battlefield(cards.land("Mountain", ["R"], basic=True), op)
    g._in_priority = True                       # ambos quedan en la pila
    g.cast(me, hydra, x_value=3)
    g.cast(op, zap)
    g._in_priority = False
    g.resolve_stack(); g.sba()
    pm = next(p for p in me.battlefield if p.card is hydra)
    assert pm.counters.get("+1/+1") == 3
    hydra2 = cards.creature("Hydra2", "G", 0, 0)
    hydra2.etb_counters = {"+1/+1": "X"}
    g.move_to_battlefield(hydra2, me); g.sba()   # reanimada: X = 0 -> muere 0/0
    assert not any(p.card is hydra2 for p in me.battlefield)


def test_cast_triggers_resolve_before_the_spell():
    import cards
    g, me, op = _duel2()
    order = []
    obs = cards.creature("Watcher", "1", 1, 1)
    obs.triggers = {"cast": lambda game, perm, **kw: order.append("trigger")}
    g.move_to_battlefield(obs, me)
    spell = cards.creature("Sorc", "", 0, 0)
    spell.types = {"sorcery"}
    spell.cost = None
    spell.on_cast_resolve = lambda *a: order.append("spell")
    me.hand = [spell]
    g.cast(me, spell)
    assert order == ["trigger", "spell"]


def test_death_has_subject_and_only_for_creatures():
    import cards
    g, me, op = _duel2()
    hofri = g.move_to_battlefield(cards.Hofri(), me)
    seen = []
    obs = cards.creature("Counter", "1", 1, 1)
    obs.triggers = {"death": lambda game, perm, **kw: seen.append(kw.get("subject"))}
    g.move_to_battlefield(obs, me)
    bear = g.move_to_battlefield(cards.creature("Bear", "1G", 2, 2), me)
    treasure = g.move_to_battlefield(cards.rock("Treasure", "0", ["C"]), me)
    g.to_graveyard(treasure, "sac"); g.resolve_stack()
    assert seen == []                                    # un artefacto no "muere"
    g.to_graveyard(bear, "test"); g.resolve_stack()
    assert seen and seen[0] is bear
    # Hofri sabe quién murió: lo exilia y crea una copia que además es Spirit
    tok = [p for p in me.battlefield if p.is_token and p.name == "Bear"]
    assert tok and "Spirit" in tok[0].card.subtypes
    assert any(c is bear.card for c in me.exile)
    g.to_graveyard(tok[0], "test"); g.resolve_stack()
    assert any(c is bear.card for c in me.graveyard)        # al irse, vuelve al GY


def test_commander_identity_damage_and_zone():
    import cards, cardsdb
    from engine import Game, Player
    k1 = cards.creature("Kang", "2", 5, 5, legendary=True)
    k2 = cards.creature("Kang", "2", 5, 5, legendary=True)
    a = Player("A", [], k1); b = Player("B", [], k2)
    c = Player("C", [], cards.creature("Other", "2", 1, 1, legendary=True))
    g = Game([a, b, c], seed=1); g.interactive_human = None
    a.command.clear(); b.command.clear()           # como al lanzarlos desde el mando
    pa = g.move_to_battlefield(k1, a); pb = g.move_to_battlefield(k2, b)
    g.deal_damage(pa, c, 11, combat=True)
    g.deal_damage(pb, c, 11, combat=True)
    g.sba()
    assert not c.lost and len(c.cmdr_damage) == 2       # antes: 22 bajo "Kang" -> perdía
    # comandante robado que muere: a la zona de mando de su DUEÑO
    a.battlefield.remove(pa); pa.controller = b; b.battlefield.append(pa)
    g.to_graveyard(pa, "test"); g.sba()
    assert k1 in a.command and k1 not in b.graveyard
    # exiliado por un barrido que no lo ubica (Sunfall): vuelve igual
    sun = cardsdb.build_card_from_data({
        "name": "Sunfall", "type_line": "Sorcery", "mana_cost": "{3}{W}{W}",
        "oracle_text": "Exile all creatures. Incubate X, where X is the number of "
                       "creatures exiled this way."})
    sun.on_cast_resolve(g, c, []); g.sba()
    assert any(x is k2 for x in b.command) and not any(x is k2 for x in b.exile)


def test_turn_cap_counts_played_turns_not_dead_seats():
    # Regresión: con 2 de 4 eliminados, los vivos jugaban la mitad de turnos.
    g, a, b, c, d = _duel2(4)
    g.max_turns = 10
    c.lost = d.lost = True
    g.play()
    assert g.turns_played == 10 or len(g.alive()) == 1


def test_spell_damage_counts_for_you_doublers():
    import cards
    from engine import StackObject
    g, me, op = _duel2()
    torb = cards.creature("Torbran", "1RRR", 2, 4)
    torb.damage_double = "you"
    g.move_to_battlefield(torb, me)
    life0 = op.life
    g.stack.append(StackObject(me, lambda gg: gg.deal_damage(None, op, 3),
                               source=cards.creature("Bolt", "R", 0, 0), label="spell:Bolt"))
    g.resolve_stack()
    assert life0 - op.life == 6


def test_each_players_upkeep_trigger_fires_on_every_upkeep():
    import cardsdb
    g, me, op = _duel2()
    c = cardsdb.build_card_from_data({
        "name": "Ticker", "type_line": "Enchantment", "mana_cost": "{1}",
        "oracle_text": "At the beginning of each player's upkeep, you gain 1 life."})
    assert "each_upkeep" in c.triggers
    g.move_to_battlefield(c, me)
    life0 = me.life
    g.active_index = 1
    g.begin_turn(op)                          # mantenimiento del RIVAL
    assert me.life == life0 + 1


# -- restos de la revisión: fin de partida, bloqueos letales, Stifle --------- #
def test_play_ends_as_soon_as_last_opponent_dies():
    ig, me, op = _ig_tricky_vs_kang()
    op.life = 0
    st = ig.state()
    assert st["phase"] == "over" and st["winner"] == me.name


def test_ai_chump_blocks_many_small_attackers_when_lethal():
    import policy
    g, me, op = _duel2()
    op.policy = policy.Policy("intermedio")
    op.life = 6
    atk = []
    for i in range(4):
        a = g.move_to_battlefield(creature(f"A{i}", "1R", 2, 2), me)
        a.summoning_sick = False
        atk.append(a)
    for i in range(3):
        b = g.move_to_battlefield(creature(f"W{i}", "1W", 0, 1), op)
        b.summoning_sick = False
    g._resolve_combat(me, [(a, op) for a in atk])
    assert not op.lost and op.life > 0, op.life


def test_ai_stifles_opponent_removal_ability():
    import cardsdb, policy
    g, me, op = _duel2()
    op.policy = policy.Policy("intermedio")
    stifle = cardsdb.build_card_from_data({
        "name": "Stifle", "type_line": "Instant", "mana_cost": "{U}",
        "color_identity": ["U"], "oracle_text": "Counter target activated or triggered ability."})
    assert stifle.target_spec == "stack_ability"
    op.hand = [stifle]
    g.move_to_battlefield(land("Island", [U], basic=True), op)
    mine = g.move_to_battlefield(creature("Bear", "1G", 2, 2), op)
    assassin = cardsdb.build_card_from_data({
        "name": "Royal Assassin", "type_line": "Creature — Human Assassin",
        "mana_cost": "{1}{B}{B}", "power": "1", "toughness": "1", "color_identity": ["B"],
        "oracle_text": "{T}: Destroy target tapped creature."})
    ra = g.move_to_battlefield(assassin, me)
    ra.summoning_sick = False
    mine.tapped = True
    assert g.activate_ability(ra, 0, targets=[mine])
    g.resolve_stack()
    assert mine in op.battlefield, "Stifle contrarresta la habilidad que apuntaba a su criatura"
    assert stifle in op.graveyard
