"""Biblioteca de cartas: constructores y efectos concretos.

Depende de engine.py. No toca el motor. Para agregar cartas ver ADDING_CARDS.md.
"""
from __future__ import annotations

import copy as _copy

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
    # las básicas tienen su tipo de tierra (Mountain, Island…): lo miran las
    # checklands ("unless you control a Mountain"), landwalk, etc.
    sub = {name} if basic and name in ("Plains", "Island", "Swamp", "Mountain", "Forest") else set()
    return Card(
        name=name,
        types={"land"},
        cost=None,
        subtypes=sub,
        supertypes={"basic"} if basic else set(),
        enters_tapped=tapped,
        color_id=set(colors) - {C},
        produces=(lambda perm, pl, _o=opts: dict(_o)),
    )


def rock(name, cost, colors, tags=("ramp",)):
    """Roca de mana: `colors` son OPCIONES de UN maná ([U, B] = U o B). Repetir un
    color suma cantidad: [C, C] = {C:2} (Sol Ring). Antes el dict colapsaba las
    repeticiones y el Sol Ring de los presets daba 1 solo maná."""
    opts = {}
    for c in colors:
        opts[c] = opts.get(c, 0) + 1
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


MAX_PERMANENTS = 300     # tope de seguridad: un bucle de fichas no cuelga la partida


def _token_cap(game, player) -> bool:
    if len(player.battlefield) < MAX_PERMANENTS:
        return False
    if not getattr(game, "_token_cap_warned", False):
        game._token_cap_warned = True
        game.log(f"aviso: {player.name} llegó a {MAX_PERMANENTS} permanentes; "
                 "no se crean más fichas (posible bucle)")
    return True


def make_token(game, player, name, power, toughness, kw=(), subtypes=(), counters=0):
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
    last = None
    made = 0
    for _ in range(game.token_multiplier(player)):     # dobladores de fichas
        if _token_cap(game, player):
            break
        last = game.move_to_battlefield(_copy.deepcopy(tok), player, is_token=True)
        if last is not None:
            made += 1
            if counters:                               # ficha "con N contadores +1/+1"
                game.add_counters(last, "+1/+1", counters)
    if made:
        # "whenever you create one or more creature tokens, …" (Staff of the
        # Storyteller, etc.). Una creación = un evento (no por ficha).
        game.emit("token_created", player=player, n=made)
    return last


def make_copy_token(game, player, src_card):
    """Ficha que es una COPIA de `src_card` (clon / populate / embalm avanzado).
    A diferencia de make_token, copia TODAS las características imprimibles y los
    ganchos de habilidad (ETB, muerte, activadas, disparadas, estáticas, lealtad),
    no solo P/T + keywords. Las funciones se comparten por referencia (deepcopy las
    trata como átomos); los sets se duplican para no compartir estado con el original."""
    # una copia no es la carta comandante ni conserva historial de zona
    last = None
    for _ in range(game.token_multiplier(player)):     # dobladores de fichas
        if _token_cap(game, player):
            break
        last = game.move_to_battlefield(_copy.deepcopy(src_card), player, is_token=True)
    return last


def make_resource_token(game, player, kind):
    """Treasure/Clue/Food/Blood como fichas-artefacto VISIBLES en el tablero.
    Treasure funciona como fuente de maná (aproximación de 'sacrificar por maná');
    las demás quedan en el campo (su sacrificio no se simula al detalle)."""
    k = (kind or "").lower()
    produces = None
    if k == "treasure":
        produces = (lambda perm, pl: {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    tok = Card(
        name=k.capitalize() or "Token",
        types={"artifact"},
        cost=None,
        power=0,
        toughness=0,
        keywords=set(),
        subtypes={k.capitalize()} if k else set(),
        tags={"token", k} if k else {"token"},
        produces=produces,
    )
    last = None
    for _ in range(game.token_multiplier(player)):     # dobladores de fichas
        last = game.move_to_battlefield(_copy.deepcopy(tok), player, is_token=True)
    return last


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


def remove_targets(mode="destroy"):
    """Aplica destruir / exiliar / devolver-a-la-mano a CADA objetivo elegido
    (lista `targets` de Permanent). Usado por remociones importadas dirigidas."""
    def eff(game, ctrl, targets):
        for perm in list(targets or []):
            if not hasattr(perm, "controller") or not hasattr(perm, "card"):
                continue                       # un jugador/objeto de pila no es permanente
            if perm not in perm.controller.battlefield:
                continue
            if not game.can_target(ctrl, perm):
                continue
            if not game.ward_ok(ctrl, perm):    # ward: se cobra al resolver
                continue
            owner = perm.controller
            if mode == "destroy":
                game.destroy(perm, "removal")
            elif mode == "exile":
                owner.battlefield.remove(perm)
                if perm.is_token:
                    continue
                if game.commander_owner(perm.card) is not None:   # a la zona de mando de su dueño
                    game.commander_owner(perm.card).command.append(perm.card)
                else:
                    owner.exile.append(perm.card)
            elif mode == "bounce":
                owner.battlefield.remove(perm)
                if perm.is_token:
                    continue
                if game.commander_owner(perm.card) is not None:
                    game.commander_owner(perm.card).command.append(perm.card)
                else:
                    owner.hand.append(perm.card)
    return eff


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
    milled = []
    for _ in range(n):
        if not player.library:
            break
        card = player.library.pop()
        player.graveyard.append(card)
        milled.append(card.name)
        game.emit("to_graveyard", player=player, card=card)
    if milled:
        game.log(f"{player.name} muele {len(milled)} carta(s): "
                 + ", ".join(milled))


def reanimate(game, ctrl, card):
    """Saca `card` del cementerio y lo pone en el campo. Emite leaves_graveyard
    (por eso puede disparar a Quintorius)."""
    if card not in ctrl.graveyard:
        return None
    ctrl.graveyard.remove(card)
    game.emit("leaves_graveyard", player=ctrl, card=card)
    return game.move_to_battlefield(card, ctrl)


def _from_oracle(data):
    """Carta desde su oráculo REAL vía el parser (import tardío: cardsdb importa cards)."""
    import cardsdb
    return cardsdb.build_card_from_data(dict(data, keywords=list(data.get("keywords", []))))


def _quintorius_lgy(game, perm, **kw):
    """Quintorius: 'Whenever one or more cards leave your graveyard, create a 3/2
    red and white Spirit creature token.'"""
    if kw.get("player") is not perm.controller:
        return
    make_token(game, perm.controller, "Spirit", 3, 2, subtypes=("Spirit",))
    game.log(f"{perm.controller.name}: Quintorius crea un Spirit 3/2")


def Quintorius():
    """Quintorius, Field Historian (oráculo real). El '+1/+0 a tus Spirits' lo
    cablea el parser; el disparo de salida del cementerio va acá."""
    c = _from_oracle({
        "name": "Quintorius, Field Historian", "mana_cost": "{3}{R}{W}",
        "type_line": "Legendary Creature — Elephant Cleric", "power": "2",
        "toughness": "4", "color_identity": ["R", "W"],
        "oracle_text": "Spirits you control get +1/+0.\nWhenever one or more cards "
                       "leave your graveyard, create a 3/2 red and white Spirit "
                       "creature token."})
    c.triggers = dict(c.triggers or {}, leaves_graveyard=_quintorius_lgy)
    c.tags = set(c.tags) | {"engine"}
    return c


def _hofri_watch(game, hofri_perm, **kw):
    """'Whenever another nontoken creature you control dies, exile it. If you do,
    create a token that's a copy of that creature, except it's a Spirit in addition
    to its other types and it has "When this token leaves the battlefield, return
    the exiled card to its owner's graveyard."'"""
    dead = kw.get("subject")         # la criatura que murió (sujeto del evento)
    if dead is None or dead.controller is not hofri_perm.controller:
        return
    if dead is hofri_perm or not dead.card.is_creature() or dead.is_token:
        return
    ctrl = hofri_perm.controller
    card = dead.card
    owner = next((pl for pl in game.players if any(c is card for c in pl.graveyard)), None)
    if owner is None:
        return                       # ya no está en el cementerio: "if you do" falla
    owner.graveyard[:] = [c for c in owner.graveyard if c is not card]
    owner.exile.append(card)
    game.emit("leaves_graveyard", player=owner, card=card)
    tok_card = _copy.deepcopy(card)
    tok_card.subtypes = set(getattr(tok_card, "subtypes", set()) or set()) | {"Spirit"}
    prev_leave = tok_card.on_leave

    def _back(g, c, perm, _card=card, _owner=owner, _prev=prev_leave):
        if _prev:
            _prev(g, c, perm)
        if any(x is _card for x in _owner.exile):
            _owner.exile[:] = [x for x in _owner.exile if x is not _card]
            _owner.graveyard.append(_card)
            g.log(f"{_card.name} vuelve al cementerio (Hofri)")
    tok_card.on_leave = _back
    make_copy_token(game, ctrl, tok_card)
    game.log(f"{ctrl.name}: Hofri devuelve {dead.name} como Spirit")


def Hofri():
    """Hofri Ghostforge (oráculo real): el anthem de Spirits lo cablea el parser;
    la copia-Spirit al morir va acá."""
    c = _from_oracle({
        "name": "Hofri Ghostforge", "mana_cost": "{3}{R}{W}",
        "type_line": "Legendary Creature — Human Shaman", "power": "4",
        "toughness": "5", "color_identity": ["R", "W"],
        "oracle_text": "Spirits you control get +1/+1 and have trample and haste."})
    c.triggers = dict(c.triggers or {}, death=_hofri_watch)
    c.tags = set(c.tags) | {"engine", "gy_exile"}
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


def SunTitan():
    """'Whenever this creature enters or attacks, you may return target permanent
    card with mana value 3 or less from your graveyard to the battlefield.'"""
    _perm_types = {"creature", "artifact", "enchantment", "land", "planeswalker", "battle"}

    def etb(game, ctrl, perm):
        from cardsdb import _pick_card_from_zone
        opts = [c for c in ctrl.graveyard if c.types & _perm_types
                and (c.cost.cmc if c.cost else 0) <= 3]
        opts.sort(key=lambda c: c.cost.cmc if c.cost else 0, reverse=True)

        def _do(card):
            reanimate(game, ctrl, card)
            game.log(f"{ctrl.name}: Sun Titan devuelve {card.name}")
        _pick_card_from_zone(game, ctrl, opts, _do,
                             "Sun Titan: elegí un permanente (CMV≤3) para devolver")
    c = creature("Sun Titan", "4WW", 6, 6, kw=("vigilance",),
                 tags=("engine", "gy_exile"), color_id=(W,))
    c.on_etb = etb
    c.triggers = {"attacks": lambda g, perm, **_kw: etb(g, perm.controller, perm)}
    return c


def KarmicGuide():
    def etb(game, ctrl, perm):
        from cardsdb import _pick_card_from_zone
        opts = [c for c in ctrl.graveyard if "creature" in c.types]
        opts.sort(key=lambda c: c.cost.cmc if c.cost else 0, reverse=True)

        def _do(card):
            reanimate(game, ctrl, card)
            game.log(f"{ctrl.name}: Karmic Guide reanima {card.name}")
        _pick_card_from_zone(game, ctrl, opts, _do,
                             "Karmic Guide: elegí una criatura para reanimar")
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
    # "Whenever a PLAYER casts a spell": los propios por "cast" y los ajenos por
    # "opp_cast" (antes solo contaba tus hechizos)
    c.triggers = {"cast": _managorger_cast,
                  "opp_cast": lambda g, perm, caster=None, **kw:
                      None if caster is perm.controller else _managorger_cast(g, perm)}
    return c


def _kalonian_attacks(game, perm, **kw):
    # "doblar" = poner tantos contadores como tiene: los dobladores/Hardened
    # Scales aplican (antes se asignaba directo y se los salteaba)
    ctrl = perm.controller
    for p in ctrl.creatures():
        cur = p.counters.get("+1/+1", 0)
        if cur > 0:
            game.add_counters(p, "+1/+1", cur)


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
    opps = game.opponents(ctrl)
    for o in opps:
        o.life -= 1                       # "each opponent LOSES 1 life" (no es daño)
    if opps:
        game.gain_life(ctrl, 1)           # "y ganás 1 vida" (1 fija, NO por oponente)
        game.log(f"{ctrl.name}: Kang — cada oponente pierde 1, ganás 1 (2da carta del turno)")


def Kang():
    """Kang, Temporal Tyrant {2}{U}{B} 3/4: al atacar connive; con tu 2da carta
    robada cada turno, cada rival pierde 1 y ganás 1."""
    c = creature("Kang, Temporal Tyrant", "2UB", 3, 4,
                 legendary=True, tags=("engine",), color_id=(U, B))
    c.triggers = {"attacks": _kang_attacks, "draw": _kang_draw}
    return c


def GrayMerchant():
    def etb(game, ctrl, perm):
        # devoción al negro = cantidad de SÍMBOLOS {B} en los costes de tus
        # permanentes (antes contaba permanentes: Gray Merchant mismo valía 1, no 2)
        devocion = sum(p.card.cost.pips.count(B) for p in ctrl.battlefield
                       if p.card.cost)
        # "each opponent loses X life. You gain life equal to the life lost"
        # (pérdida de vida, no daño: no se previene)
        lost = 0
        for o in game.opponents(ctrl):
            o.life -= devocion
            lost += devocion
        game.gain_life(ctrl, lost)
        game.log(f"{ctrl.name}: Gray Merchant drena {devocion} a cada rival")
    c = creature("Gray Merchant of Asphodel", "3BB", 2, 4, tags=("creature",),
                 color_id=(B,))
    c.on_etb = etb
    return c


def GoForTheThroat():
    return Card("Go for the Throat", {"instant"}, parse_cost("1B"),
                on_cast_resolve=destroy_target, tags={"removal"}, color_id={B},
                target_spec="opp_creature")


def NightsWhisper():
    def eff(game, ctrl, targets):        # "You draw two cards and lose 2 life."
        ctrl.draw(2, game)
        ctrl.life -= 2
    return Card("Night's Whisper", {"sorcery"}, parse_cost("1B"),
                on_cast_resolve=eff, tags={"draw"}, color_id={B})


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
        name = getattr(getattr(obj, "source", None), "name", "?")
        if game.counter_spell(obj):
            game.log(f"{ctrl.name}: Counterspell contrarresta {name}")
    return Card("Counterspell", {"instant"}, parse_cost("UU"),
                on_cast_resolve=eff, tags={"counter"}, color_id={U},
                target_spec="stack_spell")
