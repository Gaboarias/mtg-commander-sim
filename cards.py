"""Biblioteca de cartas: constructores y efectos concretos.

Depende de engine.py. No toca el motor. Para agregar cartas ver ADDING_CARDS.md.
"""
from __future__ import annotations

from engine import Card, Cost, Permanent, parse_cost, W, U, B, R, G, C


# --------------------------------------------------------------------------- #
# Constructores
# --------------------------------------------------------------------------- #

def creature(name, cost, power, toughness, kw=(), legendary=False,
             tags=("creature",), subtypes=(), color_id=None):
    return Card(
        name=name,
        types={"creature"},
        cost=parse_cost(cost),
        power=power,
        toughness=toughness,
        keywords=set(kw),
        supertypes={"legendary"} if legendary else set(),
        subtypes=set(subtypes),
        color_id=set(color_id) if color_id else set(),
        tags=set(tags),
    )


def land(name, colors, tapped=False, basic=False):
    """`colors` es una lista de opciones: [R, W] produce 1 mana rojo O blanco."""
    opts = {c: 1 for c in colors}
    return Card(
        name=name,
        types={"land"},
        cost=None,
        supertypes={"basic"} if basic else set(),
        enters_tapped=tapped,
        color_id=set(colors) - {C},
        produces=(lambda perm, pl, _o=opts: dict(_o)),
    )


def rock(name, cost, colors, tags=("ramp",)):
    """Roca de mana: `colors` son OPCIONES (una entrada = un mana)."""
    opts = {c: 1 for c in colors}
    return Card(
        name=name,
        types={"artifact"},
        cost=parse_cost(cost),
        color_id=set(colors) - {C},
        produces=(lambda perm, pl, _o=opts: dict(_o)),
        tags=set(tags),
    )


def make_token(game, player, name, power, toughness, kw=(), subtypes=()):
    tok = Card(
        name=name,
        types={"creature"},
        cost=None,
        power=power,
        toughness=toughness,
        keywords=set(kw),
        subtypes=set(subtypes),
        tags={"creature"},
    )
    return game.move_to_battlefield(tok, player, is_token=True)


# --------------------------------------------------------------------------- #
# Efectos reutilizables
# --------------------------------------------------------------------------- #

def destroy_biggest(game, ctrl, targets):
    """Destruye la criatura mas grande de un oponente."""
    victims = []
    for o in game.opponents(ctrl):
        victims.extend(o.creatures())
    if not victims:
        return
    biggest = max(victims, key=lambda p: (p.power, p.toughness))
    game.destroy(biggest, "removal")


def wrath(game, ctrl, targets):
    """Destruye todas las criaturas."""
    for p in game.players:
        for perm in list(p.battlefield):
            if perm.is_creature():
                game.destroy(perm, "wrath")


def draw_n(n):
    def _eff(game, ctrl, targets):
        ctrl.draw(n, game)
    return _eff


def dmg_all_opponents(n):
    def _eff(game, ctrl, targets):
        for o in game.opponents(ctrl):
            game.deal_damage(None, o, n)
    return _eff


# --------------------------------------------------------------------------- #
# LOREHOLD (R/W) — Espiritus desde el exilio del cementerio
# --------------------------------------------------------------------------- #

def _quintorius_upkeep(game, perm, **kw):
    ctrl = perm.controller
    has_engine = any("gy_exile" in p.card.tags for p in ctrl.battlefield)
    if has_engine:
        make_token(game, ctrl, "Espiritu", 3, 2)
        game.log(f"{ctrl.name}: Quintorius crea un Espiritu 3/2")


def Quintorius():
    c = creature("Quintorius, Historiador", "2RW", 3, 4, legendary=True,
                 tags=("engine",), color_id=(R, W))
    c.triggers = {"upkeep": _quintorius_upkeep}
    return c


def _hofri_watch(game, hofri_perm, **kw):
    dead = kw.get("perm")
    if dead is None or dead.controller is not hofri_perm.controller:
        return
    if dead is hofri_perm or not dead.is_creature():
        return
    ctrl = hofri_perm.controller
    tok = make_token(game, ctrl, dead.name + " (Espiritu)",
                     dead.card.power + 1, dead.card.toughness + 1, kw=("haste",))
    game.log(f"{ctrl.name}: Hofri devuelve {dead.name} como Espiritu")


def Hofri():
    c = creature("Hofri Ghostforge", "2RRW", 4, 4, legendary=True,
                 tags=("engine", "gy_exile"), color_id=(R, W))
    c.triggers = {"death": _hofri_watch}
    return c


def BagOfHolding():
    return Card("Bag of Holding", {"artifact"}, parse_cost("1"),
                tags={"engine", "gy_exile"})


def SevinnesReclamation():
    def eff(game, ctrl, targets):
        # devuelve un permanente de coste <=3 del cementerio a la mano
        opts = [c for c in ctrl.graveyard
                if c.cost and c.cost.cmc <= 3 and ({"creature", "artifact",
                 "enchantment", "land"} & c.types)]
        if opts:
            card = max(opts, key=lambda c: c.cost.cmc)
            game.leave_graveyard(ctrl, card, dest="hand")
            game.log(f"{ctrl.name}: Sevinne's Reclamation recupera {card.name}")
    return Card("Sevinne's Reclamation", {"sorcery"}, parse_cost("1W"),
                on_cast_resolve=eff, tags={"engine", "gy_exile"})


# --------------------------------------------------------------------------- #
# TRICKY (G/U) — Contadores +1/+1
# --------------------------------------------------------------------------- #

def _managorger_cast(game, perm, **kw):
    perm.counters["+1/+1"] = perm.counters.get("+1/+1", 0) + 1


def Managorger():
    c = creature("Managorger Hydra", "2G", 1, 1, kw=("trample",),
                 tags=("creature",), color_id=(G,))
    c.triggers = {"cast": _managorger_cast}
    return c


def _kalonian_attacks(game, perm, **kw):
    ctrl = perm.controller
    for p in ctrl.creatures():
        cur = p.counters.get("+1/+1", 0)
        if cur > 0:
            p.counters["+1/+1"] = cur * 2


def Kalonian():
    c = creature("Kalonian Hydra", "3GG", 0, 0, kw=("trample",),
                 tags=("creature",), color_id=(G,))
    def etb(game, ctrl, perm):        # entra con cuatro contadores +1/+1
        perm.counters["+1/+1"] = 4
    c.on_etb = etb
    c.triggers = {"attacks": _kalonian_attacks}
    return c


def HardenedScales():
    # simplificado: al entrar cada criatura tuya arranca con un contador extra
    return Card("Hardened Scales", {"enchantment"}, parse_cost("G"),
                tags={"engine"}, color_id={G})


def _ascendancy_cast(game, perm, **kw):
    perm.counters["growth"] = perm.counters.get("growth", 0) + 1
    if perm.counters["growth"] >= 20:
        # condicion de victoria alternativa: los demas pierden
        for o in game.opponents(perm.controller):
            o.lost = True
        game.log(f"{perm.controller.name} GANA con Simic Ascendancy")


def SimicAscendancy():
    c = Card("Simic Ascendancy", {"enchantment"}, parse_cost("1GU"),
             tags={"engine"}, color_id={G, U})
    # gana un contador de crecimiento cada vez que pones un +1/+1 (aprox: por hechizo)
    c.triggers = {"cast": _ascendancy_cast}
    return c


def BranchingEvolution():
    return Card("Branching Evolution", {"enchantment"}, parse_cost("2G"),
                tags={"engine"}, color_id={G})


# --------------------------------------------------------------------------- #
# KANG (B) — Connive / robo y drenaje
# --------------------------------------------------------------------------- #

def _kang_attacks(game, perm, **kw):
    ctrl = perm.controller
    # connive: roba 1, descarta la de menor puntuacion; si no era tierra +1/+1
    ctrl.draw(1, game)
    if not ctrl.hand:
        return
    if ctrl.policy and hasattr(ctrl.policy, "choose_discard"):
        card = ctrl.policy.choose_discard(game, ctrl)
    else:
        card = ctrl.hand[-1]
    ctrl.hand.remove(card)
    ctrl.graveyard.append(card)
    game.emit("to_graveyard", player=ctrl, card=card)
    if not card.is_land():
        perm.counters["+1/+1"] = perm.counters.get("+1/+1", 0) + 1
    game.log(f"{ctrl.name}: Kang connive (descarta {card.name})")


def Kang():
    c = creature("Kang, el Embaucador", "2B", 2, 2, kw=("menace",),
                 legendary=True, tags=("engine",), color_id=(B,))
    c.triggers = {"attacks": _kang_attacks}
    return c


def GrayMerchant():
    def etb(game, ctrl, perm):
        devocion = sum(1 for p in ctrl.battlefield
                       if p.card.cost and B in p.card.cost.pips)
        for o in game.opponents(ctrl):
            game.deal_damage(None, o, devocion)
        ctrl.life += devocion * len(game.opponents(ctrl))
        game.log(f"{ctrl.name}: Gray Merchant drena {devocion}")
    c = creature("Gray Merchant of Asphodel", "3BB", 2, 4, tags=("creature",),
                 color_id=(B,))
    c.on_etb = etb
    return c


def GoForTheThroat():
    return Card("Go for the Throat", {"instant"}, parse_cost("1B"),
                on_cast_resolve=destroy_biggest, tags={"removal"}, color_id={B})


def NightsWhisper():
    return Card("Night's Whisper", {"sorcery"}, parse_cost("1B"),
                on_cast_resolve=draw_n(2), tags={"draw"}, color_id={B})


def DamnationWipe():
    return Card("Damnation", {"sorcery"}, parse_cost("2BB"),
                on_cast_resolve=wrath, tags={"wipe"}, color_id={B})
