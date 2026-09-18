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


def planeswalker(name, cost, loyalty, abilities, color_id, tags=("engine",)):
    """Constructor de planeswalker (P2.3). `abilities` = ((coste, efecto), ...)
    con coste +N/-N y efecto(game, controller, perm)."""
    return Card(
        name=name,
        types={"planeswalker"},
        cost=parse_cost(cost),
        loyalty=loyalty,
        loyalty_abilities=tuple(abilities),
        supertypes={"legendary"},
        color_id=set(color_id),
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

def anthem(name, cost, dp, dt, color_id, tags=("engine",)):
    """Efecto continuo (P2.4): +dp/+dt a las criaturas de su controlador."""
    def mod(source_perm, target_perm):
        if (target_perm.controller is source_perm.controller
                and target_perm.is_creature()):
            return (dp, dt)
        return (0, 0)
    c = Card(name, {"enchantment"}, parse_cost(cost),
             color_id=set(color_id), tags=set(tags))
    c.static_mod = mod
    return c


def destroy_biggest(game, ctrl, targets):
    """Destruye la criatura mas grande de un oponente (sin sistema de objetivos;
    lo usan efectos que no 'apuntan')."""
    victims = []
    for o in game.opponents(ctrl):
        victims.extend(o.creatures())
    if not victims:
        return
    biggest = max(victims, key=lambda p: (p.power, p.toughness))
    game.destroy(biggest, "removal")


def destroy_target(game, ctrl, targets):
    """Removal DIRIGIDO (P2.2): destruye el objetivo si sigue siendo legal
    al resolver (revalida hexproof/ward)."""
    if not targets:
        return
    perm = targets[0]
    # el objetivo debe seguir en el campo y ser legal
    if perm not in perm.controller.battlefield:
        return
    if not game.can_target(ctrl, perm):
        game.log(f"{ctrl.name}: removal fizzlea (objetivo protegido)")
        return
    game.destroy(perm, "removal")


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
# Efectos GENERICOS por tag (para cartas no programadas) — aproximados
# --------------------------------------------------------------------------- #

def _g_wipe(game, ctrl):
    wrath(game, ctrl, None)


def _g_removal(game, ctrl):
    pool = game.legal_creature_targets(ctrl)   # respeta hexproof
    if pool:
        game.destroy(max(pool, key=lambda p: (p.power, p.toughness)), "removal generico")


def _g_draw(game, ctrl):
    ctrl.draw(2, game)


def _g_ramp(game, ctrl):
    # busca una tierra basica en la biblioteca y la pone tapeada (rampeo)
    for i, c in enumerate(ctrl.library):
        if c.is_land() and "basic" in c.supertypes:
            ctrl.library.pop(i)
            perm = game.move_to_battlefield(c, ctrl)
            perm.tapped = True
            return


def _g_gy_exile(game, ctrl):
    if ctrl.graveyard:
        game.leave_graveyard(ctrl, ctrl.graveyard[0], dest="exile")


# prioridad: el efecto mas definitorio primero
_GENERIC = [
    ("wipe", _g_wipe),
    ("removal", _g_removal),
    ("draw", _g_draw),
    ("ramp", _g_ramp),
    ("gy_exile", _g_gy_exile),
]


def attach_generic_effects(card):
    """Si la carta NO tiene efecto propio, le pone uno GENERICO segun su tag.
    Instantaneos/conjuros: al resolver. Permanentes: al entrar (ETB).
    No toca cartas que ya traen ganchos (las del registro)."""
    if (card.on_etb or card.on_cast_resolve or card.on_death or
            card.triggers or card.static_mod or card.loyalty_abilities or
            card.counter_modifier):
        return card
    eff = None
    for tag, fn in _GENERIC:
        if tag in card.tags:
            # el ramp de una roca ya se cubre con `produces`; no fetchear
            if tag == "ramp" and card.produces is not None:
                continue
            eff = fn
            break
    if eff is None:
        return card
    if {"instant", "sorcery"} & card.types:
        card.on_cast_resolve = (lambda g, ctrl, targets, _e=eff: _e(g, ctrl))
    elif {"creature", "artifact", "enchantment"} & card.types:
        card.on_etb = (lambda g, ctrl, perm, _e=eff: _e(g, ctrl))
    return card


# --------------------------------------------------------------------------- #
# LOREHOLD (R/W) — Espiritus cuando cartas dejan tu cementerio
# --------------------------------------------------------------------------- #

def mill(game, player, n):
    """Mueve las n cartas de arriba de la biblioteca al cementerio."""
    for _ in range(n):
        if not player.library:
            return
        card = player.library.pop()
        player.graveyard.append(card)
        game.emit("to_graveyard", player=player, card=card)


def reanimate(game, ctrl, card):
    """Saca `card` del cementerio y lo pone en el campo. Emite leaves_graveyard
    (por eso puede disparar a Quintorius)."""
    if card not in ctrl.graveyard:
        return None
    ctrl.graveyard.remove(card)
    game.emit("leaves_graveyard", player=ctrl, card=card)
    return game.move_to_battlefield(card, ctrl)


def _quintorius_lgy(game, perm, **kw):
    """Quintorius: cuando una o mas cartas dejan TU cementerio, crea un
    Espiritu 3/2."""
    if kw.get("player") is not perm.controller:
        return
    make_token(game, perm.controller, "Espiritu", 3, 2)
    game.log(f"{perm.controller.name}: Quintorius crea un Espiritu 3/2")


def _quintorius_upkeep(game, perm, **kw):
    """Motor auto-suficiente (decision de diseno del simulador): en tu
    mantenimiento exilia una carta de tu cementerio. Eso emite
    leaves_graveyard, que dispara la creacion del Espiritu. Sin esto, el
    arquetipo dependeria de robar un enabler concreto en un mazo singleton."""
    ctrl = perm.controller
    if ctrl.graveyard:
        card = next((c for c in ctrl.graveyard if c.is_land()), ctrl.graveyard[0])
        game.leave_graveyard(ctrl, card, dest="exile")


def Quintorius():
    c = creature("Quintorius, Historiador", "2RW", 3, 4, legendary=True,
                 tags=("engine",), color_id=(R, W))
    def etb(game, ctrl, perm):     # siembra el cementerio al entrar
        mill(game, ctrl, 2)
    c.on_etb = etb
    c.triggers = {"leaves_graveyard": _quintorius_lgy,
                  "upkeep": _quintorius_upkeep}
    return c


def _hofri_watch(game, hofri_perm, **kw):
    dead = kw.get("perm")
    if dead is None or dead.controller is not hofri_perm.controller:
        return
    if dead is hofri_perm or not dead.is_creature() or dead.is_token:
        return
    ctrl = hofri_perm.controller
    make_token(game, ctrl, dead.name + " (Espiritu)",
               dead.card.power + 1, dead.card.toughness + 1, kw=("haste",))
    game.log(f"{ctrl.name}: Hofri devuelve {dead.name} como Espiritu")


def Hofri():
    c = creature("Hofri Ghostforge", "2RRW", 4, 4, legendary=True,
                 tags=("engine", "gy_exile"), color_id=(R, W))
    c.triggers = {"death": _hofri_watch}
    return c


def _bag_upkeep(game, perm, **kw):
    # Bag of Holding: exilia una carta del cementerio en tu mantenimiento.
    # (motor repetible de salida de cementerio -> alimenta a Quintorius)
    ctrl = perm.controller
    if ctrl.graveyard:
        card = next((c for c in ctrl.graveyard if c.is_land()), ctrl.graveyard[0])
        game.leave_graveyard(ctrl, card, dest="exile")


def QuintoriusPlaneswalker():
    """Planeswalker Lorehold (P2.3): +1 crea un Espiritu 3/2; -4 hace 4 a cada
    oponente. (Es una carta distinta del comandante criatura Quintorius.)"""
    def plus(game, ctrl, perm):
        make_token(game, ctrl, "Espiritu", 3, 2)
        game.log(f"{ctrl.name}: PW crea un Espiritu 3/2")

    def ultimate(game, ctrl, perm):
        for o in game.opponents(ctrl):
            game.deal_damage(perm, o, 4)
        game.log(f"{ctrl.name}: PW -4 hace 4 a cada oponente")

    return planeswalker("Quintorius, Loremaster", "3RW", 4,
                        ((+1, plus), (-4, ultimate)), (R, W))


def BagOfHolding():
    c = Card("Bag of Holding", {"artifact"}, parse_cost("1"),
             tags={"engine", "gy_exile"})
    c.triggers = {"upkeep": _bag_upkeep}
    return c


def FaithlessLooting():
    # siembra el cementerio: roba 2, descarta 2 (a cementerio)
    def eff(game, ctrl, targets):
        ctrl.draw(2, game)
        for _ in range(2):
            if not ctrl.hand:
                break
            if ctrl.policy and hasattr(ctrl.policy, "choose_discard"):
                card = ctrl.policy.choose_discard(game, ctrl)
            else:
                card = ctrl.hand[-1]
            ctrl.hand.remove(card)
            ctrl.graveyard.append(card)
            game.emit("to_graveyard", player=ctrl, card=card)
    return Card("Faithless Looting", {"sorcery"}, parse_cost("R"),
                on_cast_resolve=eff, tags={"draw", "engine"}, color_id={R})


def CronistaEspectral():
    # auto-molienda barata: siembra el cementerio para el motor de Espiritus
    def etb(game, ctrl, perm):
        mill(game, ctrl, 3)
    c = creature("Cronista Espectral", "1W", 1, 2, tags=("engine",), color_id=(W,))
    c.on_etb = etb
    return c


def MerodeadorDeTumbas():
    def etb(game, ctrl, perm):
        mill(game, ctrl, 2)
    c = creature("Merodeador de Tumbas", "1R", 2, 1, tags=("engine",), color_id=(R,))
    c.on_etb = etb
    return c


def SevinnesReclamation():
    def eff(game, ctrl, targets):
        # devuelve un permanente de coste <=3 del cementerio a la mano
        opts = [c for c in ctrl.graveyard
                if c.cost and c.cost.cmc <= 3 and ({"creature", "artifact",
                 "enchantment"} & c.types)]
        if opts:
            card = max(opts, key=lambda c: c.cost.cmc)
            game.leave_graveyard(ctrl, card, dest="hand")
            game.log(f"{ctrl.name}: Sevinne's Reclamation recupera {card.name}")
    return Card("Sevinne's Reclamation", {"sorcery"}, parse_cost("1W"),
                on_cast_resolve=eff, tags={"engine", "gy_exile"}, color_id={W})


def UnderworldBreach():
    def etb(game, ctrl, perm):
        # exilia hasta 3 cartas del cementerio (cada una dispara leaves_graveyard)
        for _ in range(3):
            if not ctrl.graveyard:
                break
            game.leave_graveyard(ctrl, ctrl.graveyard[0], dest="exile")
    c = Card("Underworld Breach", {"enchantment"}, parse_cost("1R"),
             tags={"engine", "gy_exile"}, color_id={R})
    c.on_etb = etb
    return c


def SunTitan():
    def etb(game, ctrl, perm):
        opts = [c for c in ctrl.graveyard
                if c.cost and c.cost.cmc <= 3 and "creature" in c.types]
        if opts:
            card = max(opts, key=lambda c: c.cost.cmc)
            reanimate(game, ctrl, card)
            game.log(f"{ctrl.name}: Sun Titan reanima {card.name}")
    c = creature("Sun Titan", "4WW", 6, 6, kw=("vigilance",),
                 tags=("engine", "gy_exile"), color_id=(W,))
    c.on_etb = etb
    return c


def KarmicGuide():
    def etb(game, ctrl, perm):
        opts = [c for c in ctrl.graveyard if "creature" in c.types]
        if opts:
            card = max(opts, key=lambda c: c.cost.cmc if c.cost else 0)
            reanimate(game, ctrl, card)
            game.log(f"{ctrl.name}: Karmic Guide reanima {card.name}")
    c = creature("Karmic Guide", "3WW", 2, 2, kw=("flying",),
                 tags=("engine", "gy_exile"), color_id=(W,))
    c.on_etb = etb
    return c


# --------------------------------------------------------------------------- #
# TRICKY (G/U) — Contadores +1/+1
# --------------------------------------------------------------------------- #

def _managorger_cast(game, perm, **kw):
    game.add_counters(perm, "+1/+1", 1)


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
        game.add_counters(perm, "+1/+1", 4)
    c.on_etb = etb
    c.triggers = {"attacks": _kalonian_attacks}
    return c


def HardenedScales():
    # si vas a poner uno o mas contadores +1/+1, pone uno mas
    def mod(game, perm, kind, n):
        return n + 1 if kind == "+1/+1" else n
    c = Card("Hardened Scales", {"enchantment"}, parse_cost("G"),
             tags={"engine"}, color_id={G})
    c.counter_modifier = mod
    return c


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
    # duplica los contadores +1/+1 que pondrias
    def mod(game, perm, kind, n):
        return n * 2 if kind == "+1/+1" else n
    c = Card("Branching Evolution", {"enchantment"}, parse_cost("2G"),
             tags={"engine"}, color_id={G})
    c.counter_modifier = mod
    return c


# --------------------------------------------------------------------------- #
# KANG (B) — Connive / robo y drenaje
# --------------------------------------------------------------------------- #

def _connive(game, perm):
    """Connive: roba 1, luego descarta 1 elegida por la politica. Si lo
    descartado NO era tierra, pone un +1/+1 sobre `perm`."""
    ctrl = perm.controller
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
        game.add_counters(perm, "+1/+1", 1)
    game.log(f"{ctrl.name}: Kang connive (descarta {card.name})")


def _kang_attacks(game, perm, **kw):
    _connive(game, perm)


def _kang_draw(game, perm, **kw):
    # drena 1 a cada oponente con la SEGUNDA carta robada del turno,
    # venga del connive o de cualquier otro efecto (ej. Night's Whisper).
    if kw.get("count") != 2:
        return
    ctrl = perm.controller
    drained = 0
    for o in game.opponents(ctrl):
        game.deal_damage(perm, o, 1)
        drained += 1
    ctrl.life += drained
    if drained:
        game.log(f"{ctrl.name}: Kang drena {drained} (2da carta del turno)")


def Kang():
    c = creature("Kang, el Embaucador", "2B", 2, 2, kw=("menace",),
                 legendary=True, tags=("engine",), color_id=(B,))
    c.triggers = {"attacks": _kang_attacks, "draw": _kang_draw}
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
                on_cast_resolve=destroy_target, tags={"removal"}, color_id={B},
                target_spec="opp_creature")


def NightsWhisper():
    return Card("Night's Whisper", {"sorcery"}, parse_cost("1B"),
                on_cast_resolve=draw_n(2), tags={"draw"}, color_id={B})


def DamnationWipe():
    return Card("Damnation", {"sorcery"}, parse_cost("2BB"),
                on_cast_resolve=wrath, tags={"wipe"}, color_id={B})


# --------------------------------------------------------------------------- #
# STAPLES incoloros (en casi todos los decks) — registrados para import offline
# --------------------------------------------------------------------------- #

def SolRing():
    return Card("Sol Ring", {"artifact"}, parse_cost("1"),
                produces=lambda perm, pl: {C: 2}, tags={"ramp"})


def ArcaneSignet():
    # 1 mana de cualquier color de la identidad de tu comandante
    return Card("Arcane Signet", {"artifact"}, parse_cost("2"),
                produces=lambda perm, pl: {c: 1 for c in (pl.identity() or {C})},
                tags={"ramp"})


def CommandTower():
    c = Card("Command Tower", {"land"}, None)
    c.produces = lambda perm, pl: {col: 1 for col in (pl.identity() or {C})}
    return c


# --------------------------------------------------------------------------- #
# INSTANTANEOS de respuesta (P2.1)
# --------------------------------------------------------------------------- #

def Counterspell():
    def eff(game, ctrl, targets):
        if not targets:
            return
        obj = targets[0]
        if obj in game.stack:
            game.stack.remove(obj)
            card = obj.source
            name = getattr(card, "name", "?")
            if card is not None and not card.is_land():
                obj.controller.graveyard.append(card)
                game.emit("to_graveyard", player=obj.controller, card=card)
            game.log(f"{ctrl.name}: Counterspell contrarresta {name}")
    return Card("Counterspell", {"instant"}, parse_cost("UU"),
                on_cast_resolve=eff, tags={"counter"}, color_id={U},
                target_spec="stack_spell")
