"""Motor de reglas de Magic: The Gathering (formato Commander).

Este modulo NO conoce ninguna carta concreta. Si para implementar una carta
hace falta editarlo, lo que falta es un gancho generico (ver ARCHITECTURE.md).

Python puro, sin dependencias externas.
"""
from __future__ import annotations

import copy
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

import carddesc as _carddesc     # descripción legible de habilidades (puro)

# Margen de recursión: algunas partidas (deepcopy de tableros grandes en el juego
# interactivo, parseo de cartas modales/clon anidadas, cadenas de disparos) superan
# el tope por defecto de Python (1000) y reventaban con "maximum recursion depth
# exceeded". 3000 frames (~3 MB de pila) es holgado y seguro en CPython.
# OJO: bajo Pyodide (WASM, navegador) la pila es MUCHO más chica; subir el límite ahí
# puede provocar un desborde FATAL (no capturable) en vez de un RecursionError. Por
# eso solo lo subimos fuera de Pyodide; en el navegador confiamos en los topes de
# re-entrancia (_fx_depth, _BUILD_DEPTH) y en los fallbacks a carta vainilla.
_IS_PYODIDE = (sys.platform == "emscripten") or ("pyodide" in sys.modules)
if not _IS_PYODIDE:
    if sys.getrecursionlimit() < 3000:
        sys.setrecursionlimit(3000)
elif sys.getrecursionlimit() > 1200:
    # en el navegador, un tope más bajo garantiza un RecursionError CAPTURABLE
    # (los builders de carta lo atrapan y caen a vainilla) antes de desbordar WASM.
    sys.setrecursionlimit(1200)

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #

W, U, B, R, G, C = "W", "U", "B", "R", "G", "C"
COLORS = (W, U, B, R, G)

KEYWORDS = {
    "flying", "reach", "trample", "deathtouch", "lifelink", "vigilance",
    "haste", "first_strike", "double_strike", "menace", "indestructible",
    "hexproof", "defender", "flash",
    "shroud", "protection", "prowess", "infect", "toxic", "wither",
    "unblockable", "ward",
    "fear", "intimidate", "shadow", "skulk", "horsemanship", "flanking",
    # landwalk: no puede ser bloqueada si el defensor controla una tierra así
    "islandwalk", "swampwalk", "forestwalk", "mountainwalk", "plainswalk",
    "desertwalk", "nonbasic_landwalk", "legendary_landwalk", "split_second",
    "phasing", "ingest",
}

_LANDWALK = {"islandwalk": "island", "swampwalk": "swamp", "forestwalk": "forest",
             "mountainwalk": "mountain", "plainswalk": "plains", "desertwalk": "desert"}


class ReactionPause(Exception):
    """Se lanza cuando un rival pone un hechizo en la pila y el humano puede
    responder: la partida interactiva la captura, muestra la ventana de reacción
    y reanuda el turno del bot tras la respuesta (o el paso)."""
    def __init__(self, spell):
        super().__init__("reaction")
        self.spell = spell


class Zone(Enum):
    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    EXILE = "exile"
    COMMAND = "command"
    STACK = "stack"


class Step(Enum):
    UNTAP = "untap"
    UPKEEP = "upkeep"
    DRAW = "draw"
    MAIN1 = "main1"
    BEGIN_COMBAT = "begin_combat"
    DECLARE_ATTACKERS = "declare_attackers"
    DECLARE_BLOCKERS = "declare_blockers"
    FIRST_STRIKE = "first_strike"
    COMBAT_DAMAGE = "combat_damage"
    END_COMBAT = "end_combat"
    MAIN2 = "main2"
    END_STEP = "end_step"
    CLEANUP = "cleanup"


# --------------------------------------------------------------------------- #
# Coste de mana
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Cost:
    generic: int = 0
    pips: tuple = ()  # tuple[str] de simbolos de color

    @property
    def cmc(self) -> int:
        return self.generic + len(self.pips)

    def color_identity(self) -> set:
        return {p for p in self.pips if p in COLORS}


def _cmc_card(card) -> int:
    return card.cost.cmc if getattr(card, "cost", None) is not None else 0


def _cost_txt(c) -> str:
    """'{2}{R}' legible a partir de un Cost."""
    if c is None:
        return "{0}"
    out = f"{{{c.generic}}}" if c.generic or not c.pips else ""
    return out + "".join(f"{{{x}}}" for x in c.pips)


def parse_cost(s: str) -> Cost:
    """Lee TODOS los digitos como un solo numero generico y cada letra como
    un simbolo de color. No soporta hibridos, Phyrexianos ni X.

    parse_cost("2RW")   -> Cost(generic=2, pips=("R","W"))  cmc 4
    parse_cost("UUU")   -> Cost(generic=0, pips=("U","U","U"))
    parse_cost("1")     -> Cost(generic=1, pips=())
    """
    generic_digits = ""
    pips = []
    for ch in s:
        if ch.isdigit():
            generic_digits += ch
        elif ch.upper() in (W, U, B, R, G, C):
            pips.append(ch.upper())
        else:
            raise ValueError(f"simbolo de mana no soportado: {ch!r} en {s!r}")
    generic = int(generic_digits) if generic_digits else 0
    return Cost(generic=generic, pips=tuple(pips))


# --------------------------------------------------------------------------- #
# Card (definicion inmutable)
# --------------------------------------------------------------------------- #

@dataclass
class Card:
    name: str
    types: set = field(default_factory=set)
    cost: Optional[Cost] = None
    power: int = 0
    toughness: int = 0
    keywords: set = field(default_factory=set)
    subtypes: set = field(default_factory=set)
    supertypes: set = field(default_factory=set)  # "legendary", "basic"
    loyalty: int = 0
    color_id: set = field(default_factory=set)    # identidad explicita
    enters_tapped: bool = False
    tags: set = field(default_factory=set)

    # Ganchos
    produces: Optional[Callable] = None            # (perm, player) -> dict[color,int] OPCIONES
    on_etb: Optional[Callable] = None              # (game, controller, perm) -> None
    on_death: Optional[Callable] = None            # (game, controller, perm) -> None
    on_leave: Optional[Callable] = None            # (game, controller, perm) -> None (deja el campo)
    on_cast_resolve: Optional[Callable] = None     # (game, controller, targets) -> None
    triggers: dict = field(default_factory=dict)   # {evento: (game, perm, **kw)}
    activated: Optional[Callable] = None           # declarado, sin invocar todavia
    counter_modifier: Optional[Callable] = None    # (game, perm, kind, n) -> n' (reemplazo)
    token_double: bool = False                     # dobla las fichas que creás (Doubling Season)
    damage_double: Optional[str] = None            # "you"|"all": dobla el daño (Furnace of Rath)
    die_exile: Optional[str] = None                # "all"|"you"|"opp": muertes van al exilio
    static_mod: Optional[Callable] = None          # (fuente, objetivo) -> (dP, dT) anthem/capas
    loyalty_abilities: tuple = ()                  # planeswalker: ((coste_lealtad, efecto), ...)
    loyalty_texts: tuple = ()                       # texto legible por habilidad de lealtad
    target_spec: Optional[str] = None              # "opp_creature" | "stack_spell" | None
    target_count: int = 1                          # cuántos objetivos (remoción múltiple)
    modes: tuple = ()                              # modal "elegí una": cada modo es
    #   {"label", "effect"(g,ctrl,targets), "target_spec", "target_count"}
    mode_pick: int = 1                             # cuántos modos elige el jugador
    activated_abilities: tuple = ()                # habilidades activadas con maná:
    #   {"cost"(Cost), "tap"(bool), "label", "effect"(g,ctrl,perm,targets),
    #    "target_spec", "target_count"}
    additional_cost: dict = field(default_factory=dict)  # coste extra al lanzar:
    #   {"pay_life": int, "discard": int, "sacrifice": bool}
    cost_reduction: int = 0                        # "cuesta {N} menos" (genérico)
    gy_play: dict = field(default_factory=dict)    # jugar desde el CEMENTERIO:
    #   {"mode": flashback|escape|unearth|embalm|disturb|recur, "cost": Cost,
    #    "after": exile|exile_eot|token|hand|battlefield, "exile_n": int}
    foretell: Optional[Cost] = None                # coste para lanzarla ya predicha (exilio)
    gy_abilities: tuple = ()                        # habilidades activadas DESDE el cementerio:
    #   {"cost"(Cost), "label", "effect"(g,ctrl,card), "exile_self"(bool)}
    gy_triggers: dict = field(default_factory=dict)  # disparos MIENTRAS está en cementerio/exilio:
    #   {evento: callback(game, player, card, **kw)}
    x_spell: bool = False                            # el coste tiene {X} (se elige al lanzar)
    etb_counters: dict = field(default_factory=dict)  # "entra con N contadores": {kind: n}
    aura_keywords: set = field(default_factory=set)   # aura: keywords que da al huésped
    aura_pt_set: tuple = ()                            # aura: fija P/T base del huésped (p,t)
    aura_abilities_off: bool = False                   # aura: el huésped pierde sus habilidades
    anthem_keywords: set = field(default_factory=set)  # anthem: keyword a tus criaturas
    anthem_others: bool = False                       # el anthem excluye a la fuente
    gy_grant: dict = field(default_factory=dict)     # habilidad ESTÁTICA desde el cementerio
    #   (Anger/Brawn/Wonder): {"keyword": str, "need_subtype": str|None}. Mientras esta
    #   carta está en tu cementerio (y controlás un need_subtype si aplica), tus criaturas
    #   tienen `keyword`.

    def identity(self) -> set:
        """Identidad de color: explicita si existe, si no se deduce del coste."""
        if self.color_id:
            return set(self.color_id)
        ident = set()
        if self.cost:
            ident |= self.cost.color_identity()
        return ident

    def is_land(self) -> bool:
        return "land" in self.types

    def is_creature(self) -> bool:
        return "creature" in self.types

    def is_legendary(self) -> bool:
        return "legendary" in self.supertypes


# --------------------------------------------------------------------------- #
# Permanent (instancia en el campo de batalla)
# --------------------------------------------------------------------------- #

_UID = 0


def _next_uid() -> int:
    global _UID
    _UID += 1
    return _UID


class Permanent:
    def __init__(self, card: Card, controller: "Player", is_token: bool = False):
        self.card = card
        self.controller = controller
        self.tapped = False
        self.summoning_sick = True
        self.damage = 0
        self.counters: dict = {}
        self.attacking: Optional[Player] = None
        self.blocking: list = []
        self.blocked_by: list = []
        self.is_token = is_token
        self.uid = _next_uid()
        self.temp_pt = [0, 0]            # +P/+T "hasta el fin del turno" (prowess, pumps)
        self.temp_keywords = set()       # keywords otorgadas "hasta el fin del turno"
        self.temp_creature = False       # vehículo tripulado (crew): criatura este turno
        self.perma_keywords = set()      # keywords persistentes (soulbond, etc.)
        self.set_base_pt = None          # P/T FIJADA por un efecto ("es un 1/1 …")
        self.added_subtypes = set()      # subtipos otorgados (p. ej. Spirit) "además"
        self.temp_subtypes = set()       # subtipos "hasta el fin del turno" (tierras animadas)
        self.goaded = False              # goad: debe atacar en su próximo turno
        self.must_attack = False
        self._cant_block = False
        self.game = None                 # backref, lo pone move_to_battlefield
        self.activated_this_turn = False  # planeswalker: una activacion por turno
        self.enchanting = None           # si es un aura: el permanente al que anexó

    @property
    def cant_block(self) -> bool:
        """No puede bloquear: marca propia, 'this creature can't block' de la carta
        o 'can't block this turn' (keyword temporal)."""
        return (self._cant_block or getattr(self.card, "cant_block_static", False)
                or "cant_block" in self.temp_keywords
                or (getattr(self.card, "unleash", False)
                    and self.counters.get("+1/+1", 0) > 0)
                or getattr(self, "_detained_by", None) is not None
                or getattr(self, "suspected", False))

    @cant_block.setter
    def cant_block(self, v):
        self._cant_block = bool(v)

    def _mutation(self):
        """Auras de 'cambio de características' anexadas a este permanente
        (Darksteel Mutation, Kenrith's Transformation, Lignify…): devuelve
        (pt_set|None, abilities_off). La última anexada gana."""
        pt, off = None, False
        if self.game is None:
            return pt, off
        for src in self.game.all_permanents():
            if getattr(src, "enchanting", None) is self:
                if getattr(src.card, "aura_pt_set", ()):
                    pt = src.card.aura_pt_set
                if getattr(src.card, "aura_abilities_off", False):
                    off = True
        return pt, off

    def abilities_off(self) -> bool:
        return self._mutation()[1]

    def _static_delta(self):
        """Suma (dP, dT) de los modificadores estaticos (anthems/capas) que
        aplican a este permanente. Una fuente con habilidades anuladas no aporta."""
        dp = dt = 0
        mate = getattr(self, "_paired", None)
        if mate is not None and self.game is not None and mate in mate.controller.battlefield:
            for c in (self.card, mate.card):
                b = getattr(c, "soulbond_pt", None)
                if b:
                    dp += b[0]
                    dt += b[1]
        if self.game is not None and self.is_creature():
            for src in self.game.all_permanents():
                sm = src.card.static_mod
                if sm is not None and not src.abilities_off():
                    d = sm(src, self)
                    if d:
                        dp += d[0]
                        dt += d[1]
        return dp, dt

    # -- propiedades derivadas -------------------------------------------- #
    @property
    def name(self) -> str:
        return self.card.name

    def _base_pt(self):
        pt, _off = self._mutation()
        if pt:
            return pt
        if self.set_base_pt is not None:         # "es un 1/1 …" fija la P/T base
            return self.set_base_pt
        cda = getattr(self.card, "cda_pt", None)  # P/T variable ("… equal to the number of")
        if cda is not None and self.game is not None:
            try:
                return cda(self.game, self.controller)
            except Exception:  # noqa: BLE001
                pass
        return (self.card.power, self.card.toughness)

    @property
    def power(self) -> int:
        return (self._base_pt()[0] + self.counters.get("+1/+1", 0)
                - self.counters.get("-1/-1", 0)
                + self._static_delta()[0] + self.temp_pt[0])

    @property
    def toughness(self) -> int:
        return (self._base_pt()[1] + self.counters.get("+1/+1", 0)
                - self.counters.get("-1/-1", 0)
                + self._static_delta()[1] + self.temp_pt[1])

    @property
    def keywords(self) -> set:
        if self.abilities_off():
            return set()
        ks = set(self.card.keywords) | self.temp_keywords | self.perma_keywords
        if getattr(self.card, "cond_keywords", None) or getattr(self, "_paired", None):
            ks |= self._cond_kws()
        return ks

    def is_creature(self) -> bool:
        if getattr(self.card, "impending_n", 0) and getattr(self, "_impending", False) \
                and self.counters.get("time", 0) > 0:
            return False                 # impending: todavía no es criatura
        if self.card.is_creature() or self.temp_creature or getattr(self, "animated", False):
            return True
        st = getattr(self.card, "station_creature_at", 0)
        return bool(st) and self.counters.get("charge", 0) >= st

    def has_subtype(self, sub: str) -> bool:
        """¿Tiene el subtipo `sub`? Honra changeling y el contador 'everything'
        (Omo): una criatura con esos es de TODOS los tipos de criatura; una tierra
        con 'everything' es de todos los tipos de tierra."""
        s = sub.lower()
        if s in {x.lower() for x in self.card.subtypes}:
            return True
        if s in {x.lower() for x in self.added_subtypes}:
            return True
        if s in {x.lower() for x in self.temp_subtypes}:
            return True
        if self.counters.get("everything", 0) > 0:
            return True
        if self.is_creature() and getattr(self.card, "changeling", False):
            return True
        return False

    def _cond_kws(self) -> set:
        out = set()
        mate = getattr(self, "_paired", None)
        if mate is not None and self.game is not None and \
                mate in mate.controller.battlefield:
            for c in (self.card, mate.card):
                out |= set(getattr(c, "soulbond_kws", ()) or ())
        for k, cond in (getattr(self.card, "cond_keywords", None) or ()):
            try:
                if self.game is not None and cond(self):
                    out.add(k)
            except Exception:  # noqa: BLE001
                pass
        return out

    def has(self, kw: str) -> bool:
        if self.abilities_off():
            return False                 # perdió todas sus habilidades (mutación)
        if kw in self.card.keywords or kw in self.temp_keywords or kw in self.perma_keywords:
            return True
        if (getattr(self.card, "cond_keywords", None) or getattr(self, "_paired", None)) \
                and kw in self._cond_kws():
            return True
        # keywords otorgadas por efectos estáticos (p. ej. Anger desde el cementerio)
        return self.game is not None and self.game.grants_keyword(self, kw)

    def can_attack(self) -> bool:
        if not self.is_creature() or self.tapped:
            return False
        if getattr(self, "_detained_by", None) is not None:
            return False
        if self.has("defender"):
            return False
        if self.summoning_sick and not self.has("haste"):
            return False
        return True

    def lethal(self) -> int:
        """Dano que falta para matarla (considerando deathtouch se calcula fuera)."""
        return max(0, self.toughness - self.damage)

    def __repr__(self) -> str:
        return f"<{self.name} {self.power}/{self.toughness}{' T' if self.tapped else ''}>"


# --------------------------------------------------------------------------- #
# Player
# --------------------------------------------------------------------------- #

class Player:
    def __init__(self, name: str, deck: list, commander: Card, policy=None, partner=None):
        self.name = name
        self.deck_template = deck            # lista de Card (99, o 98 con partner)
        self.commander_card = commander
        if partner is None:
            partner = getattr(commander, "_partner", None)
        # 1 o 2 comandantes (partner / background / friends forever)
        self.commanders: list = [commander] + ([partner] if partner is not None else [])
        self.cmdr_taxes: list = [0] * len(self.commanders)
        self.life = 40
        self.poison = 0
        self.library: list = []
        self.hand: list = []
        self.graveyard: list = []
        self.exile: list = []
        self.impulse: list = []              # exiliadas por "impulse", jugables este turno
        self.exile_play: list = []           # jugables desde el exilio de forma persistente
        #   (predichas por foretell, etc.); cada carta lleva ._play_cost (Cost)
        self.command: list = list(self.commanders)
        # companion: fuera del juego; {3} a velocidad de conjuro lo pone en la mano
        self.companion = getattr(commander, "_companion", None)
        self.speed = 0                       # velocidad (Start your engines!)
        self.dungeon_room = 0                # sala actual del dungeon (0 = fuera)
        self.dungeon_kind = None
        self.dungeons_completed = 0
        self.initiative = False
        self.citys_blessing = False          # ascend
        self.battlefield: list = []          # lista de Permanent
        self.cmdr_damage: dict = {}          # {nombre_comandante: int}; 21 elimina
        self.lands_played = 0
        self.mana_pool = 0           # maná flotante (genérico) de rituales; se vacía por turno
        self.prevent = 0             # escudo de prevención de daño (hasta fin de turno)
        self.gy_cast_until = -1      # turno hasta el que puede lanzar desde el cementerio
        self.prevent_all = False     # previene TODO el daño a este jugador este turno
        self.draws_this_turn = 0     # se reinicia cada turno (para efectos "2do robo")
        self.lost = False
        self.policy = policy
        # telemetria de la partida (para analitica en bulk)
        self.stats = {"commander_turn": None, "cast_counts": Counter()}

    # -- preparacion ------------------------------------------------------ #
    def setup(self, rng: random.Random):
        self.library = [c for c in self.deck_template]
        rng.shuffle(self.library)
        self.hand = []
        for _ in range(7):
            if self.library:
                self.hand.append(self.library.pop())

    def draw(self, n: int, game: "Game"):
        for _ in range(n):
            if not self.library:
                self.lost = True     # perder por deckout
                return
            drawn = self.library.pop()
            self.hand.append(drawn)
            self.draws_this_turn += 1
            # Miracle: la PRIMERA carta que robás en el turno (de cualquiera)
            if getattr(self, "_first_draw_turn", None) != game.turn:
                self._first_draw_turn = game.turn
                if getattr(drawn, "miracle_cost", None) is not None:
                    game.try_miracle(self, drawn)
            # `count` = cuantas cartas van robadas este turno (para efectos como
            # el drenaje de Kang, que mira la SEGUNDA carta robada del turno).
            game.emit("draw", player=self, count=self.draws_this_turn)
            # evento sin scope para "whenever an opponent draws a card" (Smothering
            # Tithe): se despacha a los permanentes de TODOS; el callback filtra.
            game.emit("opp_draw", drawer=self)

    # -- consultas -------------------------------------------------------- #
    def creatures(self) -> list:
        return [p for p in self.battlefield if p.is_creature()]

    def lands(self) -> list:
        return [p for p in self.battlefield if p.card.is_land()]

    def identity(self) -> set:
        ident = set()
        for c in self.commanders:
            ident |= set(c.identity())
        return ident

    # -- comandantes ------------------------------------------------------ #
    def is_commander(self, card) -> bool:
        """¿`card` es uno de MIS comandantes? (por identidad: Card compara por valor)"""
        return card is not None and any(c is card for c in self.commanders)

    def _cmdr_index(self, card) -> int:
        for i, c in enumerate(self.commanders):
            if c is card:
                return i
        return 0

    def tax_for(self, card) -> int:
        """Impuesto de comandante de ESA carta (+2 por cada lanzamiento previo
        desde la zona de mando; cada partner lleva el suyo)."""
        return self.cmdr_taxes[self._cmdr_index(card)]

    def add_tax(self, card):
        self.cmdr_taxes[self._cmdr_index(card)] += 2

    @property
    def cmdr_tax(self) -> int:
        """Impuesto del comandante principal (compatibilidad)."""
        return self.cmdr_taxes[0]

    @cmdr_tax.setter
    def cmdr_tax(self, v):
        self.cmdr_taxes[0] = v

    def mana_sources(self, exclude=None) -> list:
        """Fuentes de maná utilizables: sin girar, sin mareo de invocación si son
        criaturas (un elfo de maná no se gira el turno que entra, salvo prisa) y
        sin las de `exclude` (p. ej. el permanente que se gira como coste de su
        propia habilidad, o las criaturas ya giradas para convoke)."""
        return [p for p in self.battlefield
                if p.card.produces is not None and not p.tapped
                and not (exclude and p in exclude)
                and not (p.is_creature() and p.summoning_sick and not p.has("haste"))]

    def available_mana(self) -> int:
        """Cota superior: suma de max(opciones) por fuente sin tapear + pool flotante."""
        total = self.mana_pool
        for p in self.mana_sources():
            opts = p.card.produces(p, self)
            if opts:
                total += max(opts.values())
        return total

    # -- pago de mana ----------------------------------------------------- #
    def _assign(self, cost: Cost, exclude=None):
        """Empareja fuentes de mana con el coste. Devuelve un plan (lista de
        (permanente, color, cantidad)) o None si no alcanza.

        `produces` devuelve OPCIONES: una tierra dual {R:1,W:1} vale UN mana
        (rojo O blanco), no dos.

        Primero el reparto voraz de siempre (mismo resultado que antes cuando
        alcanza); si falla, una búsqueda con vuelta atrás sobre los colores: el
        voraz daba falsos negativos (Plateau W/R + Tundra W/U no pagaban {W}{R}).
        """
        sources = []
        for p in self.mana_sources(exclude):
            opts = p.card.produces(p, self)
            if opts:
                sources.append((p, dict(opts)))
        plan = self._assign_greedy(cost, sources)
        if plan is None and cost.pips:
            plan = self._assign_search(cost, sources)
        return plan

    @staticmethod
    def _generic_plan(cost, sources, used, surplus):
        """Completa el genérico con las fuentes no usadas (las que más producen
        primero). Devuelve la parte del plan o None si no alcanza."""
        need = cost.generic - surplus
        plan = []
        if need <= 0:
            return plan
        rest = sorted((i for i in range(len(sources)) if i not in used),
                      key=lambda i: -max(sources[i][1].values()))
        for i in rest:
            if need <= 0:
                break
            p, opts = sources[i]
            color = max(opts, key=lambda k: opts[k])
            plan.append((p, color, opts[color]))
            need -= opts[color]
        return plan if need <= 0 else None

    def _assign_search(self, cost, sources, max_nodes=3000):
        """Vuelta atrás sobre los pips (el más restringido primero)."""
        cands = {}
        for pip in set(cost.pips):
            cands[pip] = sorted((i for i, (_p, o) in enumerate(sources) if pip in o),
                                key=lambda i: (len(sources[i][1]), max(sources[i][1].values())))
        if any(not cands[pip] for pip in cands):
            return None
        pips = sorted(cost.pips, key=lambda c: len(cands[c]))
        nodes = [0]

        def rec(k, used, surplus, plan):
            if k == len(pips):
                g = self._generic_plan(cost, sources, used, surplus)
                return None if g is None else plan + g
            nodes[0] += 1
            if nodes[0] > max_nodes:
                return None
            pip = pips[k]
            for i in cands[pip]:
                if i in used:
                    continue
                amt = sources[i][1][pip]
                r = rec(k + 1, used | {i}, surplus + amt - 1,
                        plan + [(sources[i][0], pip, amt)])
                if r is not None:
                    return r
            return None
        return rec(0, frozenset(), 0, [])

    def _assign_greedy(self, cost, sources):
        """Reparto voraz: cada pip con la fuente MENOS flexible que sirva."""
        used = set()
        plan = []
        generic_pool = 0  # mana sobrante de fuentes usadas para pips

        # 1) simbolos de color: el mas restrictivo primero conceptualmente,
        #    resuelto con la fuente MENOS flexible que sirva.
        for pip in cost.pips:
            best = None
            best_key = None
            for i, (p, opts) in enumerate(sources):
                if i in used or pip not in opts:
                    continue
                flexibility = (len(opts), max(opts.values()))
                if best is None or flexibility < best_key:
                    best = i
                    best_key = flexibility
            if best is None:
                return None
            p, opts = sources[best]
            used.add(best)
            amt = opts[pip]
            plan.append((p, pip, amt))
            generic_pool += amt - 1  # 1 paga el pip, el resto va a generico

        # 2) generico: primero el sobrante, luego las fuentes que mas produzcan.
        need = cost.generic - generic_pool
        if need > 0:
            rest = sorted(
                (i for i in range(len(sources)) if i not in used),
                key=lambda i: -max(sources[i][1].values()),
            )
            for i in rest:
                if need <= 0:
                    break
                p, opts = sources[i]
                color = max(opts, key=lambda k: opts[k])
                amt = opts[color]
                plan.append((p, color, amt))
                used.add(i)
                need -= amt
            if need > 0:
                return None
        return plan

    def can_pay(self, cost: Cost, exclude=None) -> bool:
        if cost is None:
            return True
        return self._assign(self._pool_reduced(cost), exclude) is not None

    def _pool_reduced(self, cost: Cost) -> Cost:
        """El maná flotante (genérico) cubre parte del coste genérico."""
        if self.mana_pool <= 0 or cost is None:
            return cost
        return Cost(max(0, cost.generic - self.mana_pool), cost.pips)

    def pay(self, cost: Cost, exclude=None) -> bool:
        if cost is None:
            return True
        use = min(self.mana_pool, cost.generic) if self.mana_pool > 0 else 0
        plan = self._assign(self._pool_reduced(cost), exclude)
        if plan is None:
            return False
        for perm, _color, _amt in plan:
            perm.tapped = True
        self.mana_pool -= use
        return True


# --------------------------------------------------------------------------- #
# Stack
# --------------------------------------------------------------------------- #

class StackObject:
    def __init__(self, controller, resolve, source=None, targets=None, label="",
                 chosen_modes=None, kind="spell", perm=None, is_copy_ability=False):
        self.controller = controller
        self.resolve = resolve          # (game) -> None
        self.source = source
        self.targets = targets or []
        self.label = label
        self.chosen_modes = list(chosen_modes) if chosen_modes else None
        # kind: "spell" | "ability" | "trigger" — para responder/copiar habilidades.
        # Disparos apilados sin kind explícito (attacks:, creature_enters:, cdmg:…)
        # son habilidades disparadas, no hechizos.
        if kind == "spell" and label and not label.startswith(("spell:", "copy:", "cipher")):
            kind = "trigger"
        self.kind = kind
        self.perm = perm                # permanente fuente si es una habilidad activada
        self.is_copy_ability = is_copy_ability  # la propia habilidad de copia (no copiable)
        self.copied = False             # ya fue copiada (evita copiarla de nuevo)


# --------------------------------------------------------------------------- #
# Game
# --------------------------------------------------------------------------- #

class Game:
    SELF_SCOPED = {"upkeep", "end_step", "draw", "landfall", "cast", "begin_combat",
                   "gain_life", "token_created", "cards_exiled", "main2"}
    # descripción amigable de cada evento, para el resumen de habilidades
    EVENT_KIND = {
        "etb": "cuando algo entra al campo", "landfall": "al jugar una tierra",
        "attacks": "al atacar", "death": "cuando muere una criatura",
        "to_graveyard": "cuando algo va al cementerio",
        "leaves_graveyard": "cuando algo deja el cementerio",
        "upkeep": "en tu mantenimiento", "end_step": "al final del turno",
        "each_upkeep": "en cada mantenimiento", "each_end_step": "al final de cada turno",
        "cast": "cuando lanzás un hechizo", "draw": "al robar",
        "begin_combat": "al empezar el combate",
    }

    def __init__(self, players: list, seed: int = 0, max_turns: int = 60,
                 log: bool = False, mulligan: bool = False, trace: bool = False):
        self.players = players
        self.rng = random.Random(seed)
        self.max_turns = max_turns
        self.log_enabled = log
        self.log_lines: list = []
        self.turn = 0
        # turnos JUGADOS (los asientos de jugadores eliminados no cuentan): el tope
        # max_turns se aplica sobre esto. Antes contaba `turn`, que avanza también
        # por los asientos muertos: con 2 de 4 eliminados los vivos jugaban la mitad
        # de turnos y los empates se inflaban.
        self.turns_played = 0
        self.active_index = 0
        self.stack: list = []
        self._in_priority = False    # evita recursion al lanzar en respuesta
        self.trace_enabled = trace   # graba snapshots del estado (replay visual)
        self.trace: list = []
        # registro de habilidades que se activaron (para el resumen de la partida):
        # {turn, controller, card, kind}. No crea pasos en la traza.
        self.ability_events: list = []
        # nombre de la carta cuyo efecto se está resolviendo ahora (ETB, disparo o
        # hechizo en la pila): se usa para ATRIBUIR en el registro quién causó una
        # pérdida de vida / daño ("cada rival pierde 2 [Fuente]").
        self._fx_source = None
        # controlador del objeto que se está resolviendo: el daño de un hechizo
        # (deal_damage con fuente None) cuenta como fuente de ese jugador para los
        # dobladores "de fuentes que controlás" (Torbran, Fiery Emancipation)
        self._fx_controller = None
        # profundidad de efectos INLINE re-entrantes (ETB/muerte que disparan ETB/
        # muerte...). Corta bucles patológicos de una carta mal modelada antes de que
        # revienten la pila de Python ("maximum recursion depth exceeded").
        self._fx_depth = 0
        self._fx_max_depth = 60
        # decisión pendiente del humano (juego interactivo): el motor pausa un
        # efecto que requiere elegir (revelar, etc.) hasta resolve_choice().
        self.interactive_human = None
        self.pending_choice = None
        # cola de decisiones del humano diferidas (forzadas durante el turno de un
        # bot, donde no se puede pausar la pila): thunks que arman pending_choice.
        self.choice_queue: list = []
        # control temporal (Threaten): permanentes a devolver al fin del turno
        self.control_returns: list = []
        # turnos extra pendientes (para el mismo jugador)
        self.extra_turns: list = []
        self.extra_combats = 0     # fases de combate adicionales este turno (Aggravated Assault…)
        self.day_night = None      # None / "day" / "night" (daybound/nightbound)
        self.spell_x = 0            # X elegido del último hechizo con {X} lanzado
        self.spells_this_turn = 0   # hechizos lanzados este turno (storm)
        self.damaged_players: set = set()   # jugadores dañados este turno (bloodthirst)
        self.suspended: list = []   # cartas suspendidas: {card, player, n}
        # cartas "sustitutas" en juego: criaturas boca abajo (morph, disguise,
        # manifest, cloak) y criaturas lanzadas con bestow como Aura. Cada una
        # guarda la carta real en `_real`; si sale del campo vuelve la real.
        self._proxies: list = []
        self.rebound: list = []          # (jugador, carta) a relanzar en su mantenimiento
        self.epic: list = []             # (jugador, carta) épicas: se copian en su mantenimiento
        self.paradigm: list = []         # (jugador, carta) paradigma: copia gratis por turno
        self.phased: list = []           # (permanente, controlador) fuera de fase
        self.warp_eot: list = []         # (jugador, carta) lanzadas por warp este turno
        self.dash_return: list = [] # criaturas jugadas por dash a devolver al fin de turno
        self.blitz_sac: list = []   # criaturas jugadas por blitz a sacrificar al fin de turno
        self.no_prevention_turn = False   # "el daño no se puede prevenir este turno"
        self.no_block_turn = False        # "las criaturas no pueden bloquear este turno"
        # última habilidad activada resuelta (para copiarla: Strionic Resonator):
        # (perm, ability_dict, targets)
        self.last_activated = None
        # última habilidad COPIABLE (activada O disparada) para Strionic Resonator:
        # {"source": card, "perm": perm, "label": str, "run": callable(game)}
        self.last_ability = None
        for p in players:
            p.setup(self.rng)
        if mulligan:
            for p in players:
                self._mulligan(p)
        if self.trace_enabled:
            self._snapshot("inicio de la partida")

    # -- mulligan (regla de Londres, P2.5) -------------------------------- #
    def _mulligan(self, p: "Player", max_mulls: int = 3):
        mulls = 0
        while (mulls < max_mulls and p.policy is not None
               and hasattr(p.policy, "should_mulligan")
               and p.policy.should_mulligan(p.hand, p)):
            p.library.extend(p.hand)
            p.hand = []
            self.rng.shuffle(p.library)
            for _ in range(7):
                if p.library:
                    p.hand.append(p.library.pop())
            mulls += 1
        # Londres: por cada mulligan, poner una carta al fondo
        for _ in range(mulls):
            if not p.hand:
                break
            card = self._bottom_choice(p)
            p.hand.remove(card)
            p.library.insert(0, card)   # el fondo (pop() saca del final = tope)
        if mulls:
            self.log(f"{p.name} hizo {mulls} mulligan(s)")

    def _bottom_choice(self, p: "Player"):
        lands = [c for c in p.hand if c.is_land()]
        if len(lands) > 3:
            return lands[0]
        nonlands = [c for c in p.hand if not c.is_land()]
        if nonlands:
            return max(nonlands, key=lambda c: c.cost.cmc if c.cost else 0)
        return p.hand[0]

    # -- registro de habilidades activadas (resumen) ---------------------- #
    def note_ability(self, card, kind: str, controller=None):
        """Anota que se activó una habilidad de `card` (kind = descripción corta
        del disparo: 'entra al campo', 'al morir una criatura', 'lealtad +1'...)."""
        name = getattr(card, "name", None)
        if not name:
            return
        who = getattr(controller, "name", None)
        self.ability_events.append({
            "turn": self.turn, "controller": who, "card": name, "kind": kind,
        })

    def src_tag(self) -> str:
        """Sufijo con la carta-fuente del efecto en curso, para atribuir en el
        registro quién causó una pérdida de vida o daño. Vacío si no se conoce."""
        s = getattr(self, "_fx_source", None)
        return f" [{s}]" if s else ""

    def _run_fx(self, label, fn):
        """Corre un efecto INLINE (ETB / muerte / al dejar el campo) con tope de
        re-entrancia. Si una carta mal modelada se auto-dispara en cadena, corta el
        bucle y sigue, en vez de reventar la pila de Python (RecursionError)."""
        if self._fx_depth >= self._fx_max_depth:
            self.log(f"aviso: se cortó una cadena de efectos ({label}) por posible bucle")
            return None
        self._fx_depth += 1
        try:
            return fn()
        finally:
            self._fx_depth -= 1

    # -- logging ---------------------------------------------------------- #
    def log(self, msg: str):
        line = f"T{self.turn} {msg}"
        self.log_lines.append(line)
        if self.log_enabled:
            print(line)
        if self.trace_enabled:
            self._snapshot(msg)

    # -- traza para replay visual (Fase 1) -------------------------------- #
    def _snapshot(self, label: str):
        """Guarda un estado serializable de la mesa en el momento de `label`.
        Se dispara desde log(): cada linea de relato queda emparejada con el
        tablero resultante, listo para reproducir paso a paso."""
        self.trace.append({
            "turn": self.turn,
            "active": self.active_index,
            "label": label,
            "stack": [getattr(o.source, "name", "?") for o in self.stack],
            "players": [self._player_state(p) for p in self.players],
        })

    def _perm_state(self, pm: "Permanent") -> dict:
        creature = pm.is_creature()
        pw = "planeswalker" in pm.card.types
        loy_abils = []
        if pw:
            texts = pm.card.loyalty_texts or ()
            for i, (cost, _eff) in enumerate(pm.card.loyalty_abilities or ()):
                loy_abils.append({"i": i, "cost": cost,
                                  "text": texts[i] if i < len(texts) else ""})
        return {
            "uid": pm.uid,
            "name": pm.name,
            "tapped": pm.tapped,
            "power": pm.power if creature else None,
            "toughness": pm.toughness if creature else None,
            "damage": pm.damage,
            "counters": {k: v for k, v in pm.counters.items() if v},
            "is_land": pm.card.is_land(),
            "is_creature": creature,
            "is_planeswalker": pw,
            "loyalty": pm.counters.get("loyalty", 0) if pw else None,
            "loyalty_abilities": loy_abils,
            "activated": pm.activated_this_turn,
            "is_token": pm.is_token,
            "attacking": bool(pm.attacking),
            "sick": pm.summoning_sick,
            "keywords": sorted(pm.keywords),
            "types": sorted(pm.card.types),
            "subtypes": sorted(set(pm.card.subtypes) | pm.added_subtypes),
            "abilities": _carddesc.describe(pm.card),
        }

    def _player_state(self, p: "Player") -> dict:
        return {
            "name": p.name,
            "life": p.life,
            "lost": p.lost,
            "hand": len(p.hand),
            "library": len(p.library),
            "commander": [c.name for c in p.command],
            "cmdr_tax": p.cmdr_tax,
            "cmdr_damage": dict(p.cmdr_damage),   # daño de comandante RECIBIDO
            "poison": p.poison,
            "experience": getattr(p, "experience", 0),   # contadores de experiencia (Ezuri…)
            "energy": getattr(p, "energy", 0),            # contadores de energía
            "graveyard": [c.name for c in p.graveyard],
            "exile": [c.name for c in p.exile],
            "battlefield": [self._perm_state(pm) for pm in p.battlefield],
        }

    # -- helpers de jugadores -------------------------------------------- #
    def alive(self) -> list:
        return [p for p in self.players if not p.lost]

    def ap(self) -> "Player":
        return self.players[self.active_index]

    # Decisión pendiente del humano. Si un efecto pide OTRA decisión mientras ya
    # hay una abierta (p. ej. dos "scry" que resuelven seguidos en la pila), la
    # nueva espera en choice_queue en vez de pisar a la primera: antes la primera
    # se perdía junto con las cartas que ya había sacado de la biblioteca.
    @property
    def pending_choice(self):
        return getattr(self, "_pending_choice", None)

    @pending_choice.setter
    def pending_choice(self, value):
        if value is not None and getattr(self, "_pending_choice", None) is not None:
            self.choice_queue.append(value)
            return
        self._pending_choice = value

    def commander_owner(self, card):
        """Jugador DUEÑO de `card` si es un comandante (aunque lo controle otro)."""
        for p in self.players:
            if p.is_commander(card):
                return p
        return None

    def cmdr_key(self, owner, card=None) -> str:
        """Clave del daño de comandante: el nombre de ESE comandante (con partners
        cada uno cuenta aparte), y el dueño si otro jugador tiene un comandante con
        el mismo nombre (antes dos Kang sumaban juntos)."""
        name = (card if card is not None else owner.commander_card).name
        if sum(1 for p in self.players for c in p.commanders if c.name == name) > 1:
            return f"{name} ({owner.name})"
        return name

    def opponents(self, p: "Player") -> list:
        return [o for o in self.players if o is not p and not o.lost]

    def all_permanents(self) -> list:
        out = []
        for pl in self.players:
            out.extend(pl.battlefield)
        return out

    def may(self, ctrl: "Player", prompt: str, on_yes) -> None:
        """Decisión OPCIONAL ('podés hacer X'). El humano elige sí/no vía
        pending_choice; los bots auto-aceptan (heurística: suele convenir).
        `on_yes(game, ctrl)` corre solo si se acepta."""
        if ctrl is getattr(self, "interactive_human", None):
            self.pending_choice = {
                "kind": "may", "prompt": prompt,
                "options": [{"i": 0, "name": "Sí"}, {"i": 1, "name": "No"}],
                "allow_none": False,
                "_apply": (lambda idx, _f=on_yes, _c=ctrl:
                           _f(self, _c) if idx == 0 else None),
            }
        else:
            on_yes(self, ctrl)

    def grants_keyword(self, perm: "Permanent", kw: str) -> bool:
        """¿Alguna habilidad estática le OTORGA `kw` a `perm`? Hoy cubre las
        estáticas desde el cementerio (Anger/Brawn/Wonder): 'mientras esta carta
        esté en tu cementerio (y controles un <subtipo>), tus criaturas tienen
        <keyword>'."""
        if not perm.is_creature():
            return False
        ctrl = perm.controller
        # auras anexadas a este permanente que otorgan la keyword
        for src in self.all_permanents():
            if src.enchanting is perm and kw in (getattr(src.card, "aura_keywords", None) or set()):
                return True
        # anthems estáticos que dan keyword a las criaturas de su controlador
        for src in self.all_permanents():
            ak = getattr(src.card, "anthem_keywords", None)
            if ak and kw in ak and src.controller is ctrl:
                asub = getattr(src.card, "anthem_subtype", None)
                if asub and not perm.has_subtype(asub):
                    continue                    # lord por subtipo: solo ese tipo
                if not (getattr(src.card, "anthem_others", False) and src is perm):
                    return True
        for card in ctrl.graveyard:
            g = getattr(card, "gy_grant", None)
            if not g or g.get("keyword") != kw:
                continue
            sub = g.get("need_subtype")
            if sub:
                sl = sub.lower()
                have = any(sl in {s.lower() for s in pm.card.subtypes}
                           or pm.card.name.lower() == sl   # tierras básicas: subtipo = nombre
                           for pm in ctrl.battlefield)
                if not have:
                    continue
            return True
        return False

    # -- objetivos (P2.2) ------------------------------------------------- #
    def can_target(self, caster: "Player", perm: "Permanent") -> bool:
        """Reglas de objetivo. hexproof/protección: no puede ser objetivo de un
        OPONENTE. shroud: nadie. ward NO bloquea el objetivo (es un impuesto que se
        cobra al resolver, ver `ward_ok`)."""
        if perm.has("shroud"):            # ni su propio controlador lo apunta
            return False
        if perm.controller is caster:
            return True
        if perm.has("hexproof") or perm.has("protection"):
            return False
        return True

    def ward_ok(self, caster: "Player", perm: "Permanent") -> bool:
        """Ward: al RESOLVER un efecto de un rival sobre `perm`, se cobra el coste de
        ward. Si el rival no puede pagarlo, el efecto se contrarresta sobre ese
        objetivo (devuelve False). El propio controlador no paga ward."""
        if perm.controller is caster:
            return True
        w = getattr(perm.card, "ward", None)
        if not w or not perm.has("ward"):
            return True
        if w.get("life"):
            n = w["life"]
            if caster.life > n:           # no puede quedar en 0 o menos por ward
                caster.life -= n
                self.log(f"{caster.name} paga {n} de vida (ward de {perm.name})")
                return True
            self.log(f"{perm.name}: ward no pagado — el efecto falla")
            return False
        cost = w.get("mana")
        if cost is not None and caster.can_pay(cost):
            caster.pay(cost)
            self.log(f"{caster.name} paga el ward de {perm.name}")
            return True
        self.log(f"{perm.name}: ward no pagado — el efecto falla")
        return False

    def legal_creature_targets(self, caster: "Player",
                               opponents_only: bool = True) -> list:
        pool = []
        players = self.opponents(caster) if opponents_only else self.players
        for pl in players:
            for perm in pl.creatures():
                if self.can_target(caster, perm):
                    pool.append(perm)
        return pool

    # -- eventos ---------------------------------------------------------- #
    def emit(self, event: str, **kw):
        """Encola en la pila los disparadores registrados para `event`.

        Alcance: si el evento es SELF_SCOPED y viene con `player`, solo
        disparan permanentes de ese jugador.
        """
        who = kw.get("player")
        # registro genérico para condiciones "if a card left your graveyard this turn"
        if event == "leaves_graveyard" and who is not None:
            who.gy_left_turn = self.turn
        for pl in self.players:
            if pl.lost:
                continue
            if event in self.SELF_SCOPED and who is not None and pl is not who:
                continue
            for perm in list(pl.battlefield):
                cb = perm.card.triggers.get(event)
                if cb is None:
                    continue
                # El callback recibe (game, perm, **kw): `perm` es el permanente que
                # OBSERVA; el permanente SUJETO del evento (el que entra/muere) llega
                # como `subject` (antes se descartaba y Hofri nunca sabía quién murió).
                inner = {k: v for k, v in kw.items() if k != "perm"}
                if "perm" in kw:
                    inner["subject"] = kw["perm"]
                self.stack.append(StackObject(
                    controller=pl,
                    resolve=(lambda g, _cb=cb, _perm=perm, _kw=inner:
                             g._run_trigger(_cb, _perm, _kw)),
                    source=perm,
                    label=f"trigger:{event}:{perm.name}",
                    kind="trigger", perm=perm,
                ))
                self.note_ability(perm.card, self.EVENT_KIND.get(event, event),
                                  controller=pl)
                # registrar esta disparada como la última habilidad COPIABLE
                # (Strionic Resonator puede copiar "activated OR triggered").
                self.last_ability = {
                    "source": perm.card, "perm": perm,
                    "label": self.EVENT_KIND.get(event, event),
                    "run": (lambda g, _cb=cb, _perm=perm, _kw=inner:
                            g._run_trigger(_cb, _perm, _kw)),
                }
            # Eminence: comandantes con eminencia disparan desde la zona de mando
            for card in list(pl.command):
                if not getattr(card, "eminence", False):
                    continue
                cb = (card.triggers or {}).get(event)
                if cb is None:
                    continue
                stand = getattr(card, "_cz_perm", None)
                if stand is None:
                    stand = Permanent(card, pl)
                    stand.game = self
                    card._cz_perm = stand
                stand.controller = pl
                inner = {k: v for k, v in kw.items() if k != "perm"}
                if "perm" in kw:
                    inner["subject"] = kw["perm"]
                self.stack.append(StackObject(
                    controller=pl,
                    resolve=(lambda g, _cb=cb, _perm=stand, _kw=inner:
                             g._run_trigger(_cb, _perm, _kw)),
                    source=stand, label=f"eminence:{event}:{card.name}", kind="trigger"))
            # Fase D: disparos MIENTRAS la carta está en el cementerio/exilio.
            for zone in (pl.graveyard, pl.exile):
                for card in list(zone):
                    cb = getattr(card, "gy_triggers", {}).get(event)
                    if cb is None:
                        continue
                    # el dueño va posicional (_p); evitamos duplicar 'player'/'perm' del kw
                    inner = {k: v for k, v in kw.items() if k not in ("perm", "player")}
                    if event == "death":
                        inner["dying"] = kw.get("perm")      # recover: de quién era
                    self.stack.append(StackObject(
                        controller=pl,
                        resolve=(lambda g, _cb=cb, _p=pl, _c=card, _kw=inner: _cb(g, _p, _c, **_kw)),
                        source=card,
                        label=f"gy_trigger:{event}:{card.name}",
                        kind="trigger",
                    ))
                    self.note_ability(card, "desde el cementerio", controller=pl)

    def resolve_stack(self):
        """Vacia la pila en orden LIFO."""
        guard = 0
        while self.stack:
            guard += 1
            if guard > 5000:            # cortafuegos anti-bucle (nunca en juego normal)
                self.log("aviso: se cortó el vaciado de la pila (límite de seguridad)")
                self.stack.clear()
                break
            obj = self.stack.pop()
            if obj.controller.lost:
                continue
            prev = self._fx_source
            prev_c = self._fx_controller
            self._fx_source = getattr(getattr(obj, "source", None), "name", None)
            self._fx_controller = obj.controller
            try:
                obj.resolve(self)
            finally:
                self._fx_source = prev
                self._fx_controller = prev_c
            self.sba()

    # -- movimiento de cartas -------------------------------------------- #
    # -- efectos de reemplazo (dobladores / muerte->exilio) -------------- #
    def token_multiplier(self, player: "Player") -> int:
        """×2 por cada permanente del jugador que doble sus fichas (Doubling
        Season, Parallel Lives, Anointed Procession)."""
        mult = 1
        for pm in player.battlefield:
            if getattr(pm.card, "token_double", False):
                mult *= 2
        return mult

    def damage_multiplier(self, source) -> int:
        """×2 por cada doblador de daño en juego cuyo alcance cubra a `source`.
        'all' cubre cualquier fuente; 'you' solo fuentes del controlador."""
        mult = 1
        src_ctrl = (source.controller if isinstance(source, Permanent)
                    else getattr(self, "_fx_controller", None))
        for pl in self.players:
            for pm in pl.battlefield:
                scope = getattr(pm.card, "damage_double", None)
                if scope == "all" or (scope == "you" and src_ctrl is pm.controller):
                    mult *= 2
        return mult

    def _dies_to_exile(self, perm: "Permanent") -> bool:
        """¿Una muerte de `perm` se reemplaza por exilio? (odio de cementerio)."""
        for pl in self.players:
            for pm in pl.battlefield:
                scope = getattr(pm.card, "die_exile", None)
                if scope == "all":
                    return True
                if scope == "you" and perm.controller is pm.controller:
                    return True
                if scope == "opp" and perm.controller is not pm.controller:
                    return True
        return False

    def gain_life(self, player: "Player", n: int, reason: str = ""):
        """Suma vida y dispara 'gain_life' (soul sisters, Ajani's Pridemate,
        Heliod…). Sólo cuenta ganancia real (n > 0). Respeta la prohibición de
        ganar vida (Erebos, Archfiend of Despair, Sulfuric Vortex…)."""
        if n <= 0:
            return
        for pl in self.players:
            for pm in pl.battlefield:
                stop = getattr(pm.card, "stops_lifegain", None)
                if stop == "all" or (stop == "opponents" and pl is not player):
                    self.log(f"{player.name} no puede ganar vida ({pm.name})")
                    return
        # reemplazo "si ganarías vida, ganás esa cantidad +N" (Angel of Vitality,
        # Boon Reflection…): +N por evento, por cada fuente del controlador.
        bonus = 0
        for pm in player.battlefield:
            b = getattr(pm.card, "life_gain_bonus", 0)
            if b and not pm.abilities_off():
                bonus += b
        n += bonus
        player.life += n
        player.gained_turn = self.turn
        self.emit("gain_life", player=player, amount=n)

    def add_counters(self, perm: Permanent, kind: str, n: int):
        """Pone `n` contadores de tipo `kind` sobre `perm`, aplicando los
        modificadores de reemplazo (doblar, sumar) de los permanentes de su
        controlador. Gancho generico: las cartas definen `counter_modifier`.
        """
        if n > 0:
            for other in perm.controller.battlefield:
                mod = other.card.counter_modifier
                if mod is not None:
                    n = mod(self, perm, kind, n)
        perm.counters[kind] = perm.counters.get(kind, 0) + n
        return n

    def _run_trigger(self, cb, perm, kw, subject=None):
        """Resuelve una disparada dejando a mano la FUENTE (el permanente que
        observa) y el SUJETO del evento, para efectos que dicen '~' / 'that
        creature' / 'equipped creature' sin recibirlos como argumento."""
        prev = (getattr(self, "_trigger_source", None),
                getattr(self, "_trigger_subject", None),
                getattr(self, "_trigger_kw", None))
        self._trigger_source = perm
        self._trigger_subject = subject if subject is not None else kw.get("subject")
        self._trigger_kw = kw
        try:
            return cb(self, perm, **kw)
        finally:
            self._trigger_source, self._trigger_subject, self._trigger_kw = prev

    def move_to_battlefield(self, card: Card, player: "Player",
                            is_token: bool = False) -> Permanent:
        # salvaguarda: un instantáneo/conjuro NUNCA puede entrar al campo. Si algún
        # efecto lo intenta (reanimación mal parseada, etc.), va al cementerio.
        host = getattr(card, "_mutate_onto", None)
        if host is not None:
            card._mutate_onto = None
            real = getattr(card, "_real", None) or card
            self._drop_proxy(card)
            if (host in host.controller.battlefield and host.is_creature()
                    and not host.has_subtype("human") and host.controller is player):
                return self._do_mutate(real, host, player)
            card = real                   # objetivo ilegal: entra como criatura
        perm_types = {"creature", "artifact", "enchantment", "planeswalker",
                      "land", "battle"}
        if not (set(card.types) & perm_types):
            if not is_token and card not in player.graveyard:
                player.graveyard.append(card)
            self.log(f"{card.name} no puede entrar al campo (no es permanente)")
            return None
        perm = Permanent(card, player, is_token=is_token)
        perm.game = self
        if card.enters_tapped:
            perm.tapped = True
        # "entra girada A MENOS QUE …" (checklands, fastlands, shocks…): condición
        # evaluada al entrar (antes de sumarse al campo: 'other lands')
        cond = getattr(card, "etb_untapped_if", None)
        if cond is not None:
            try:
                perm.tapped = not cond(self, player)
            except Exception:  # noqa: BLE001
                perm.tapped = True
        # planeswalker: entra con su lealtad inicial
        if "planeswalker" in card.types and card.loyalty:
            perm.counters["loyalty"] = card.loyalty
        # "entra con N contadores" (efecto de reemplazo: antes de los disparos ETB).
        # N == "X" -> usa el X elegido al lanzar (Hydras con {X}).
        for kind, n in (getattr(card, "etb_counters", None) or {}).items():
            if n == "X":
                n = max(0, getattr(self, "spell_x", 0) or 0)
            if n:
                perm.counters[kind] = perm.counters.get(kind, 0) + n
        player.battlefield.append(perm)
        if not card.is_land():                # celebration: permanentes no tierra que entraron
            if getattr(player, "_entered_turn", None) != self.turn:
                player._entered_turn, player.entered_nonland = self.turn, 0
            player.entered_nonland += 1
        if card.on_etb:
            self.note_ability(card, "entra al campo", controller=player)
            prev = self._fx_source
            prev_c = self._fx_controller
            self._fx_source = card.name
            self._fx_controller = player
            try:
                self._run_fx(f"ETB {card.name}",
                             lambda: card.on_etb(self, player, perm))
            finally:
                self._fx_source = prev
                self._fx_controller = prev_c
        if getattr(card, "_impending_cast", False):
            card._impending_cast = False
            perm._impending = True
            perm.counters["time"] = perm.counters.get("time", 0) + card.impending_n
        if getattr(card, "_enter_converted", False):
            card._enter_converted = False
            self.transform(perm)
        if perm.is_creature():
            self._soulbond_pair(perm)
        self.emit("etb", player=player, perm=perm)
        # Offspring (1 copia 1/1) / Squad (una copia por pago), si se pagaron
        if not is_token and (getattr(card, "_offspring_paid", False)
                             or getattr(card, "_squad_n", 0)):
            import cards as _cards
            n_off = 1 if card._offspring_paid else 0
            n_sq = card._squad_n
            card._offspring_paid, card._squad_n = False, 0
            for _ in range(n_off):
                c2 = copy.deepcopy(card)
                c2.power = c2.toughness = 1
                _cards.make_copy_token(self, player, c2)
                self.log(f"{player.name} crea una copia 1/1 de {card.name} (offspring)")
            for _ in range(n_sq):
                _cards.make_copy_token(self, player, copy.deepcopy(card))
            if n_sq:
                self.log(f"{player.name} crea {n_sq} copia(s) de {card.name} (squad)")
        # daybound/nightbound: si entra una carta así y no es ni de día ni de noche,
        # se vuelve de día (regla 502/711).
        if self.day_night is None and (getattr(card, "daybound", False)
                                       or getattr(card, "nightbound", False)):
            self.set_day_night("day")
        # disparadores "cuando entra una criatura (que controlás)": necesitan la
        # criatura que entró, así que se despachan aparte (emit no la pasa).
        if card.is_creature():
            for w in self.all_permanents():
                cb = w.card.triggers.get("creature_enters")
                if cb is None:
                    continue
                self.stack.append(StackObject(
                    controller=w.controller,
                    resolve=(lambda g, _cb=cb, _w=w, _e=perm: _cb(g, _w, entered=_e)),
                    source=w, label=f"creature_enters:{w.name}"))
                self.note_ability(w.card, "cuando entra una criatura",
                                  controller=w.controller)
            # eminence: también desde la zona de mando
            for pl in self.players:
                for cz in list(pl.command):
                    cb = (cz.triggers or {}).get("creature_enters") \
                        if getattr(cz, "eminence", False) else None
                    if cb is None:
                        continue
                    stand = getattr(cz, "_cz_perm", None)
                    if stand is None:
                        stand = Permanent(cz, pl)
                        stand.game = self
                        cz._cz_perm = stand
                    stand.controller = pl
                    self.stack.append(StackObject(
                        controller=pl,
                        resolve=(lambda g, _cb=cb, _w=stand, _e=perm: _cb(g, _w, entered=_e)),
                        source=stand, label=f"eminence:creature_enters:{cz.name}"))
        for w in self.all_permanents():
            cb = (w.card.triggers or {}).get("perm_enters")
            if cb is None:
                continue
            self.stack.append(StackObject(
                controller=w.controller,
                resolve=(lambda g, _cb=cb, _w=w, _e=perm: _cb(g, _w, entered=_e)),
                source=w, label=f"perm_enters:{w.name}", kind="trigger"))
        if card.is_land():
            self.emit("landfall", player=player)
        return perm

    def destroy(self, perm: Permanent, reason: str = ""):
        """Respeta indestructible y umbra armor."""
        if perm.has("indestructible"):
            return
        if self._umbra_save(perm):
            return
        self.to_graveyard(perm, reason)

    def _umbra_save(self, perm: Permanent) -> bool:
        """Umbra armor / totem armor: si la criatura encantada sería destruida, en
        su lugar se le quita todo el daño y se destruye el Aura."""
        for src in self.all_permanents():
            if src.enchanting is perm and getattr(src.card, "umbra_armor", False):
                perm.damage = 0
                self.log(f"{src.name} se destruye en lugar de {perm.name} (umbra armor)")
                self.to_graveyard(src, "umbra armor")
                return True
        return False

    def to_graveyard(self, perm: Permanent, reason: str = ""):
        """Ignora indestructible. El comandante vuelve a la zona de mando.
        Los tokens desaparecen."""
        ctrl = perm.controller
        if perm not in ctrl.battlefield:
            return
        ctrl.battlefield.remove(perm)
        if perm.card.on_leave:                # "cuando deja el campo" (muerte/exilio)
            self._run_fx(f"on_leave {perm.name}",
                         lambda: perm.card.on_leave(self, ctrl, perm))
        if getattr(perm, "_blitz", False):    # blitz: su muerte roba una carta
            ctrl.draw(1, self)
            self.log(f"{ctrl.name} roba una carta (blitz de {perm.name})")
        relocated = False
        if perm.card.on_death:
            # on_death puede devolver True (persist/undying) para indicar que la
            # carta ya volvió al campo y NO debe ir al cementerio.
            relocated = bool(self._run_fx(f"on_death {perm.name}",
                                          lambda: perm.card.on_death(self, ctrl, perm)))
        # "muere" = una CRIATURA va del campo al cementerio. Antes se emitía también
        # para artefactos/fichas no-criatura (sacrificar una Treasure disparaba a
        # los aristócratas) y para criaturas exiliadas por un reemplazo.
        exiled_instead = perm.card.is_creature() and (
            self._dies_to_exile(perm) or perm.counters.get("finality"))
        dies = perm.is_creature() and not exiled_instead
        ctrl.left_turn = self.turn            # revolt: un permanente tuyo dejó el campo
        if not perm.card.is_land():
            self.nonland_left_turn = self.turn   # void
        if dies:
            self.death_turn = self.turn       # morbid: murió una criatura este turno
            self.emit("death", player=ctrl, perm=perm)
        # disparo de muerte PROPIA: emit() escanea el campo y la carta ya no está,
        # así que su propio triggers["death"] (aristócratas "this creature or ...",
        # criaturas que vuelven al morir) se despacha aparte.
        _own_death = (perm.card.triggers or {}).get("death") if dies else None
        if _own_death:
            self.stack.append(StackObject(
                ctrl,
                (lambda g, _cb=_own_death, _p=perm, _pl=ctrl: _cb(g, _p, player=_pl, self_death=True)),
                source=perm, label=f"death-self:{perm.name}", kind="trigger"))
        if not exiled_instead:
            self._push_self_trigger(perm, "self_to_gy", "va al cementerio")
        for owner, heff in (getattr(perm, "_haunted_by", None) or []):
            self.log(f"Muere {perm.name}: se dispara su fantasma (haunt)")
            self._run_fx("haunt", lambda _e=heff, _o=owner: _e(self, _o))
        if perm.is_token:
            return
        if relocated:
            return
        # comandante: vuelve a la zona de mando de su DUEÑO (eleccion; aqui siempre)
        owner = self.commander_owner(perm.card)
        if owner is not None:
            owner.command.append(perm.card)
            self.log(f"{perm.name} vuelve a la zona de mando")
            return
        # reemplazo "si moriría, exíliala en su lugar" (odio de cementerio) o
        # contador de finalidad (finality counter): se exilia en vez de ir al GY.
        if perm.card.is_creature() and (self._dies_to_exile(perm)
                                        or perm.counters.get("finality")):
            ctrl.exile.append(getattr(perm.card, "_real", None) or perm.card)
            self.log(f"{perm.name} es exiliada en vez de ir al cementerio")
            return
        card = perm.card
        extra_cards = []
        if getattr(card, "_real", None) is not None:   # boca abajo / bestow / mutate
            self._drop_proxy(card)
            extra_cards = [x for x in (getattr(card, "_extra_cards", None) or [])
                           if x is not card._real]
            card = card._real
        for x in extra_cards:                         # el resto de la pila mutada
            ctrl.graveyard.append(x)
        ctrl.graveyard.append(card)
        self.emit("to_graveyard", player=ctrl, card=card)
        if getattr(perm, "_earthbent", False) and card in ctrl.graveyard:
            ctrl.graveyard.remove(card)
            np = self.move_to_battlefield(card, ctrl)
            if np is not None:
                np.tapped = True
                self.log(f"{card.name} vuelve al campo girada (tierra-control)")

    def _sacrifice_candidates(self, ctrl, typ, n, exclude=None):
        """Permanentes propios que sirven para pagar un coste 'Sacrifice a <tipo>'.
        Devuelve los `n` menos valiosos (para no tirar lo mejor). No sacrifica al
        comandante si hay alternativa."""
        def match(pm):
            if pm is exclude:
                return False
            t = pm.card.types
            if typ == "creature":
                return pm.is_creature()
            if typ == "land":
                return pm.card.is_land()
            if typ == "token":
                return pm.is_token
            if typ in ("artifact", "enchantment"):
                return typ in t
            return True   # "permanent"
        pool = [pm for pm in ctrl.battlefield if match(pm)]
        # valor aproximado: comandante y tokens/criaturas fuertes valen más; ofrecemos
        # primero lo más barato de perder.
        def worth(pm):
            v = pm.card.power + pm.card.toughness if pm.is_creature() else 0
            if ctrl.is_commander(pm.card):
                v += 100
            return v
        pool.sort(key=worth)
        return pool[:n]

    def discard_card(self, ctrl, card):
        """Descarta una carta ya quitada de la mano. Madness (regla 702.35): la
        carta se descarta AL EXILIO y su dueño puede lanzarla por el coste de
        madness; si no lo hace, va al cementerio. El humano elige; los bots la
        lanzan si pueden pagarla."""
        card._discarded_turn = self.turn
        mad = getattr(card, "madness", None)
        if mad is None:
            ctrl.graveyard.append(card)
            self.emit("to_graveyard", player=ctrl, card=card)
            return
        ctrl.exile.append(card)
        self.log(f"{ctrl.name} descarta {card.name} al exilio (madness)")

        def _decline(g=self, c=ctrl):
            if card in c.exile:
                c.exile.remove(card)
                c.graveyard.append(card)
                g.emit("to_graveyard", player=c, card=card)

        def _cast(g=self, c=ctrl):
            if card not in c.exile or not c.can_pay(mad):
                _decline()
                return
            c.exile.remove(card)
            targets = None
            pol = c.policy
            if getattr(card, "target_spec", None) and pol is not None \
                    and hasattr(pol, "choose_targets"):
                try:
                    targets = pol.choose_targets(g, c, card)
                except Exception:  # noqa: BLE001
                    targets = None
            orig = card.cost
            ok = False
            try:
                card.cost = mad
                g.log(f"{c.name} lanza {card.name} por madness")
                ok = g.cast(c, card, targets=targets)
            except ReactionPause:
                ok = True
                raise
            finally:
                card.cost = orig
                if ok is False and card not in c.graveyard:
                    c.graveyard.append(card)
                    g.emit("to_graveyard", player=c, card=card)

        if not ctrl.can_pay(mad):
            _decline()
            return
        if ctrl is getattr(self, "interactive_human", None):
            self.pending_choice = {
                "kind": "may", "card": card.name,
                "prompt": f"Madness: ¿lanzar {card.name} por {_cost_txt(mad)}? "
                          f"(si no, va al cementerio)",
                "options": [{"i": 0, "name": "Lanzarla"},
                            {"i": 1, "name": "Al cementerio"}],
                "allow_none": False,
                "_apply": lambda idx: _cast() if idx == 0 else _decline(),
            }
            return
        _cast()

    def _pay_discard(self, ctrl, n):
        """Descarta `n` cartas (o toda la mano si n<0) como coste. Usa la política
        del jugador si expone choose_discard; si no, descarta las últimas."""
        count = len(ctrl.hand) if n < 0 else n
        for _ in range(count):
            if not ctrl.hand:
                break
            if ctrl.policy and hasattr(ctrl.policy, "choose_discard"):
                card = ctrl.policy.choose_discard(self, ctrl)
            else:
                card = ctrl.hand[-1]
            ctrl.hand.remove(card)
            self.discard_card(ctrl, card)
        self.log(f"{ctrl.name} descarta {count} carta(s) (coste)")

    def leave_graveyard(self, player: "Player", card: Card, dest: str = "exile") -> bool:
        """Saca una carta del cementerio. Emite leaves_graveyard. Devuelve bool."""
        if card not in player.graveyard:
            return False
        player.graveyard.remove(card)
        if dest == "exile":
            player.exile.append(card)
            self.emit("cards_exiled", player=player, count=1)   # exilio desde el cementerio
        elif dest == "hand":
            player.hand.append(card)
        self.emit("leaves_graveyard", player=player, card=card)
        return True

    # -- dano ------------------------------------------------------------- #
    def deal_damage(self, source, target, amount: int, combat: bool = False):
        if amount <= 0:
            return
        # dobladores de daño (Furnace of Rath / Gratuitous Violence) — reemplazo
        # que se aplica antes de la prevención.
        mult = self.damage_multiplier(source)
        if mult > 1:
            amount *= mult
        # "el daño no se puede prevenir este turno" (Skullcrack, Flames of the Blood
        # Hand…): ignora todos los escudos de prevención.
        no_prev = getattr(self, "no_prevention_turn", False)
        # prevención de daño (escudos "hasta el fin del turno")
        if not no_prev and isinstance(target, Player):
            if getattr(target, "prevent_all", False):
                self.log(f"se previene el daño a {target.name}")
                return
            pv = getattr(target, "prevent", 0)
            if pv > 0:
                blocked = min(pv, amount)
                target.prevent = pv - blocked
                amount -= blocked
                if amount <= 0:
                    return
        elif not no_prev and isinstance(target, Permanent):
            pv = getattr(target, "prevent", 0)
            if pv > 0:
                blocked = min(pv, amount)
                target.prevent = pv - blocked
                amount -= blocked
                if amount <= 0:
                    return
        src_perm = isinstance(source, Permanent)
        if isinstance(target, Player):
            if amount > 0:
                self.damaged_players.add(target)   # bloodthirst: rival dañado este turno
                if combat and src_perm:            # prowl: daño de combate con <tipo>
                    sc = source.controller
                    if getattr(sc, "_prowl_turn", None) != self.turn:
                        sc._prowl_turn, sc.prowl_types = self.turn, set()
                    sc.prowl_types |= {x.lower() for x in source.card.subtypes}
                    sc.prowl_types.add("*")
            if src_perm and source.has("infect"):
                target.poison += amount            # infect: veneno en vez de vida
            elif src_perm and source.has("toxic"):
                target.life -= amount              # toxic: daño normal
                if combat:                         # + N veneno SOLO por daño de combate
                    target.poison += getattr(source.card, "toxic_n", 1)
            else:
                target.life -= amount
            # dano de comandante
            # dano de comandante (por identidad: cuenta aunque lo controle otro)
            cowner = self.commander_owner(source.card) if (combat and src_perm) else None
            if cowner is not None:
                key = self.cmdr_key(cowner, source.card)
                target.cmdr_damage[key] = target.cmdr_damage.get(key, 0) + amount
            # Cipher: al pegar daño de combate a un jugador, lanzar una copia GRATIS
            # de cada hechizo cifrado en esta criatura.
            if combat and src_perm and getattr(target, "initiative", False) \
                    and source.controller is not target:
                self.take_initiative(source.controller)
            # monarca: el daño de combate le roba la corona
            if (combat and src_perm and getattr(self, "monarch", None) is target
                    and source.controller is not target):
                self.set_monarch(source.controller)
            if combat and src_perm and getattr(source, "_ciphered", None):
                for ceff in list(source._ciphered):
                    self.stack.append(StackObject(
                        source.controller,
                        (lambda g, _e=ceff, _c=source.controller: _e(g, _c, [])),
                        source=source, label=f"cipher:{source.name}"))
                self.note_ability(source.card, "cifrado (cipher)",
                                  controller=source.controller)
            # Renombre N: al pegar daño de combate a un jugador, si no está renombrada,
            # recibe N contadores +1/+1 y queda renombrada.
            if combat and src_perm and getattr(source.card, "renown", 0):
                if not getattr(source, "_renowned", False):
                    n = source.card.renown
                    self.add_counters(source, "+1/+1", n)
                    source._renowned = True
                    self.log(f"Renombre: {source.name} recibe {n} contador(es) +1/+1")
                    self.note_ability(source.card, f"renombre {source.card.renown}",
                                      controller=source.controller)
            if combat and src_perm and source.has("ingest") and target.library:
                ex = target.library.pop()
                target.exile.append(ex)
                self.log(f"{target.name} exilia la carta de arriba (ingest)")
            if combat and src_perm and getattr(source.controller, "_prowl_turn", None) == self.turn \
                    and source.controller.is_commander(getattr(source.card, "_real", None) or source.card):
                source.controller.prowl_types.add("commander")   # freerunning
            if combat and src_perm:
                step = (self.turn, getattr(self, "_dmg_step", 0))
                for w in list(source.controller.battlefield):
                    if (w.card.triggers or {}).get("group_combat_damage") and \
                            getattr(w, "_gcd_step", None) != step:
                        w._gcd_step = step
                        self._push_self_trigger(w, "group_combat_damage",
                                                "daño de combate de tus criaturas",
                                                damaged=target)
            # disparo "cuando ~ hace daño de combate a un jugador"
            if combat and src_perm:
                cb = source.card.triggers.get("combat_damage_to_player")
                if cb:
                    self.stack.append(StackObject(
                        source.controller,
                        (lambda g, _cb=cb, _p=source: _cb(g, _p)),
                        source=source, label=f"cdmg:{source.name}"))
                    self.note_ability(source.card, "daño de combate a un jugador",
                                      controller=source.controller)
        elif isinstance(target, Permanent):
            if "planeswalker" in target.card.types:
                # el dano a un planeswalker le quita lealtad (P2.3)
                target.counters["loyalty"] = target.counters.get("loyalty", 0) - amount
            elif src_perm and (source.has("infect") or source.has("wither")):
                # infect/wither: el daño se pone como contadores -1/-1 (no cura al
                # enderezar). Con deathtouch, alcanza para matarla.
                self.add_counters(target, "-1/-1", amount)
                if source.has("deathtouch") and target.toughness > 0:
                    self.add_counters(target, "-1/-1", target.toughness)
            else:
                target.damage += amount
                if src_perm and source.has("deathtouch") and amount > 0:
                    target.damage = max(target.damage, target.toughness)
            if amount > 0:
                self._push_self_trigger(target, "dealt_damage", "recibe daño (enrage)",
                                        amount=amount)
        # lifelink: la fuente gana vida = daño hecho, contra CUALQUIER objetivo
        if src_perm and source.has("lifelink"):
            self.gain_life(source.controller, amount)

    # -- acciones basadas en estado -------------------------------------- #
    def _return_commander(self, p) -> bool:
        return any([self._return_one_commander(p, c) for c in p.commanders])

    def _return_one_commander(self, p, cmd) -> bool:
        if cmd is None or any(c is cmd for c in p.command):
            return False
        for pl in self.players:
            for pm in pl.battlefield:
                c = pm.card
                if c is cmd or getattr(c, "_real", None) is cmd or \
                        any(x is cmd for x in (getattr(c, "_extra_cards", None) or ())):
                    return False         # en juego (también mutado / bestow / boca abajo)
            if any(c is cmd for c in pl.hand) or any(c is cmd for c in pl.library):
                return False            # en mano/biblioteca: se queda ahí
        if any(getattr(o, "source", None) is cmd for o in self.stack):
            return False                # se está lanzando
        if any(pm.card is cmd for pm, _c in self.phased):
            return False                # fuera de fase (phasing): sigue siendo suyo
        for pl in self.players:
            for zone in (pl.graveyard, pl.exile, pl.exile_play, pl.impulse):
                zone[:] = [c for c in zone if c is not cmd]
        p.command.append(cmd)
        self.log(f"{cmd.name} vuelve a la zona de mando")
        return True

    def sba(self):
        changed = True
        while changed:
            changed = False
            if self._normalize_proxies():
                changed = True
            for _p in self.players:
                if not _p.citys_blessing and not _p.lost:
                    self._check_ascend(_p)
            # perdida por vida / veneno / dano de comandante
            for p in self.players:
                if p.lost:
                    continue
                if p.life <= 0 or p.poison >= 10:
                    p.lost = True
                    changed = True
                    self.log(f"{p.name} pierde (vida {p.life}, veneno {p.poison})")
                    continue
                if any(v >= 21 for v in p.cmdr_damage.values()):
                    p.lost = True
                    changed = True
                    self.log(f"{p.name} pierde por dano de comandante")
            # comandante en un cementerio o exilio (de cualquiera: lo pudo robar otro)
            # o fuera de toda zona (efectos que exilian y no lo ubican): vuelve a la
            # zona de mando de su dueño. Antes un "exiliá todas las criaturas" o un
            # comandante robado que moría lo perdían para siempre.
            for p in self.players:
                if not p.lost and self._return_commander(p):
                    changed = True
            # el monarca que deja el juego: la corona pasa al jugador activo
            mon = getattr(self, "monarch", None)
            if mon is not None and mon.lost:
                ap = self.players[self.active_index]
                self.monarch = None
                if not ap.lost:
                    self.set_monarch(ap)
            # un jugador ELIMINADO deja el juego: todos sus objetos se van (regla
            # 800.4a). Así ninguna habilidad puede apuntar a sus cartas (campo,
            # cementerio, exilio) ni siguen activos sus efectos estáticos/disparos.
            for p in self.players:
                if not p.lost:
                    continue
                if p.battlefield or p.graveyard or p.exile or p.impulse or p.exile_play:
                    if p.battlefield:
                        changed = True          # sus estáticos/anthems dejan de aplicar
                    p.battlefield = []
                    p.graveyard = []
                    p.exile = []
                    p.impulse = []
                    p.exile_play = []
                    p.hand = []
                    p.library = []
                    p.command = []
            # contadores +1/+1 y -1/-1 se aniquilan de a pares
            for p in self.players:
                for perm in p.battlefield:
                    plus = perm.counters.get("+1/+1", 0)
                    minus = perm.counters.get("-1/-1", 0)
                    n = min(plus, minus)
                    if n:
                        perm.counters["+1/+1"] = plus - n
                        perm.counters["-1/-1"] = minus - n
                        changed = True
            # criaturas muertas: resistencia <= 0 muere SIEMPRE (no es destrucción);
            # el daño letal la destruye SALVO que sea indestructible.
            for p in self.players:
                for perm in list(p.battlefield):
                    if not perm.is_creature():
                        continue
                    if perm.toughness <= 0:
                        self.to_graveyard(perm, "resistencia 0")
                        changed = True
                    elif perm.damage >= perm.toughness and not perm.has("indestructible"):
                        if not self._umbra_save(perm):
                            self.to_graveyard(perm, "daño letal")
                        changed = True
            # planeswalkers sin lealtad
            for p in self.players:
                for perm in list(p.battlefield):
                    if ("planeswalker" in perm.card.types
                            and perm.counters.get("loyalty", 0) <= 0):
                        self.to_graveyard(perm, "loyalty 0")
                        changed = True
            # estado: "cuando ~ no tenga contadores <X>, sacrifícala y crea <ficha>"
            # (Dark Depths -> Marit Lage). Se dispara una sola vez por permanente.
            for p in self.players:
                for perm in list(p.battlefield):
                    spec = getattr(perm.card, "sac_when_no_counter", None)
                    if not spec or getattr(perm, "_no_counter_fired", False):
                        continue
                    cname, tok = spec
                    if perm.counters.get(cname, 0) <= 0:
                        perm._no_counter_fired = True
                        self.to_graveyard(perm, f"sin contadores {cname}")
                        if tok:
                            import cards as _cards
                            _cards.make_token(
                                self, p, tok["name"], tok["power"], tok["toughness"],
                                kw=tuple(tok.get("keywords", ())),
                                subtypes=tuple(tok.get("subtypes", ())))
                            self.log(f"{p.name} crea {tok['name']} "
                                     f"{tok['power']}/{tok['toughness']}")
                        changed = True
            # aura sin huésped válido -> al cementerio (bestow: vuelve a ser criatura)
            for p in self.players:
                for perm in list(p.battlefield):
                    subs = {s.lower() for s in perm.card.subtypes}
                    host = perm.enchanting
                    if "aura" in subs and getattr(perm.card, "_bestow", False):
                        if (host is None or host not in host.controller.battlefield
                                or not host.is_creature()):
                            self._unbestow(perm, "su huésped dejó el campo")
                            changed = True
                        continue
                    if "aura" in subs:
                        if host is None or host not in host.controller.battlefield:
                            self.to_graveyard(perm, "aura sin objetivo")
                            changed = True
                    elif "equipment" in subs and host is not None:
                        # el equipo NO muere: si su criatura se fue, se desanexa
                        if host not in host.controller.battlefield:
                            perm.enchanting = None
                            changed = True
            # regla de legendarios: el controlador elige cuál conserva. El humano
            # decide (pending_choice); los bots conservan la "mejor" copia.
            human = getattr(self, "interactive_human", None)
            for p in self.players:
                by_name = {}
                for perm in list(p.battlefield):
                    if perm.card.is_legendary():
                        by_name.setdefault(perm.name, []).append(perm)
                for _name, dupes in by_name.items():
                    if len(dupes) < 2:
                        continue
                    if p is human and self.pending_choice is None:
                        self._legend_choice(p, dupes)   # se resuelve por elección
                    else:
                        keep = max(dupes, key=lambda x: (x.power, x.toughness))
                        for perm in dupes:
                            if perm is not keep:
                                self.to_graveyard(perm, "legend rule")
                                changed = True
        self._normalize_proxies()

    def _legend_choice(self, p: "Player", dupes: list):
        """El humano elige cuál copia legendaria conserva; el resto va al cementerio."""
        keep_list = list(dupes)

        def _apply(idx):
            keep = keep_list[idx] if idx is not None and 0 <= idx < len(keep_list) else keep_list[0]
            for perm in keep_list:
                if perm is not keep and perm in p.battlefield:
                    self.to_graveyard(perm, "legend rule")
            self.sba()

        self.pending_choice = {
            "kind": "legend",
            "prompt": f"Tenés {len(dupes)} copias de {dupes[0].name}: elegí cuál conservás "
                      f"(las otras van al cementerio).",
            "options": [{"i": i, "name": f"{d.name} ({d.power}/{d.toughness})"}
                        for i, d in enumerate(dupes)],
            "allow_none": False, "_apply": _apply,
        }

    # -- lanzar hechizos -------------------------------------------------- #
    def effective_cost(self, player: "Player", card: Card, from_command: bool = False):
        """Coste a pagar de verdad: impuesto de comandante, reducciones ("cuesta {N}
        menos", "{1} menos por cada criatura…", descuentos de permanentes) e
        impuestos (stax). La IA y /play lo usan para saber qué es lanzable."""
        cost = card.cost
        if cost is None:
            return None
        # surge / spectacle / prowl: coste alternativo si se cumple la condición
        # (solo sobre el coste impreso: no cuando ya se lanza por otro coste)
        for _kind, alt, cond in (getattr(card, "alt_costs", None) or ()):
            if card.cost is getattr(card, "_printed_cost", None) and alt.cmc < cost.cmc:
                try:
                    if cond(self, player, card):
                        cost = alt
                except Exception:  # noqa: BLE001
                    pass
        # "si controlás un comandante, podés lanzarlo sin pagar su coste de maná"
        if getattr(card, "free_with_commander", False) and any(
                player.is_commander(pm.card) for pm in player.battlefield):
            return Cost(generic=0, pips=())
        extra = player.tax_for(card) if from_command else 0
        red = (getattr(card, "cost_reduction", 0) or 0) + self._static_cost_reduction(player, card)
        fn = getattr(card, "cost_reduction_fn", None)
        if fn is not None:
            red += fn(self, player)
        tax = self._static_cost_increase(player, card)      # stax: "cuesta {N} más"
        if extra or red or tax:
            return Cost(generic=max(0, cost.generic + extra - red + tax), pips=cost.pips)
        return cost

    def cast(self, player: "Player", card: Card, from_command: bool = False,
             targets=None, chosen_modes=None, x_value=None):
        if getattr(player, "epic_locked", False):
            return False                 # epic: no podés lanzar hechizos por el resto
        cost = card.cost
        # impuesto de comandante + reducciones + stax
        pay_cost = self.effective_cost(player, card, from_command)
        # hechizos con {X}: se elige X = maná sobrante tras pagar el coste base.
        # X se guarda EN ESTE lanzamiento (cast_x) y se expone como game.spell_x
        # solo mientras resuelve: antes era global, así que un hechizo lanzado en
        # respuesta lo pisaba (la Hydra entraba 0/0) y una criatura reanimada
        # después recibía la X del último hechizo.
        cast_x = 0
        if getattr(card, "x_spell", False) and cost is not None:
            base = pay_cost if pay_cost is not None else cost
            xc = max(1, getattr(card, "x_count", 1))   # {X}{X}... -> xc maná por X
            # X elegido (humano) o, si no, el máximo pagable (auto para bots)
            x = (x_value if x_value is not None
                 else max(0, (player.available_mana() - base.cmc) // xc))
            x = max(0, x)
            if x:
                cast_x = x
                pay_cost = Cost(generic=base.generic + x * xc, pips=base.pips)
                self.log(f"{player.name} elige X = {x} para {card.name}")
        # reducciones dinámicas: affinity (artefactos), convoke (girar criaturas),
        # delve (exiliar del cementerio). Bajan el genérico y consumen recursos.
        convoke_tap, delve_n = [], 0
        tags = getattr(card, "tags", set()) or set()
        if pay_cost is not None and (tags & {"affinity_art", "convoke", "delve", "improvise"}):
            gen = pay_cost.generic
            if "affinity_art" in tags:
                arts = sum(1 for pm in player.battlefield if "artifact" in pm.card.types)
                gen = max(0, gen - arts)
            if "convoke" in tags:
                # primero las criaturas que NO dan maná: girar un elfo de maná para
                # convoke o como fuente paga lo mismo, pero no puede hacer ambas
                creqs = sorted((pm for pm in player.battlefield
                                if pm.is_creature() and not pm.tapped),
                               key=lambda pm: pm.card.produces is not None)
                use = min(gen, len(creqs))
                convoke_tap = creqs[:use]
                gen -= use
            if "improvise" in tags:      # como convoke pero girando ARTEFACTOS
                arts = sorted((pm for pm in player.battlefield
                               if "artifact" in pm.card.types and not pm.tapped
                               and pm not in convoke_tap),
                              key=lambda pm: pm.card.produces is not None)
                use = min(gen, len(arts))
                convoke_tap += arts[:use]
                gen -= use
            if "delve" in tags:
                delve_n = min(gen, len(player.graveyard))
                gen -= delve_n
            pay_cost = Cost(generic=gen, pips=pay_cost.pips)
        # Entwine: si se eligieron TODOS los modos de una carta modal, se suma el coste.
        ent = getattr(card, "_entwine_cost", 0) or 0
        if (ent and pay_cost is not None and chosen_modes
                and getattr(card, "modes", None)
                and len(set(chosen_modes)) >= len(card.modes)):
            pay_cost = Cost(generic=pay_cost.generic + ent, pips=pay_cost.pips)
        # Kicker: coste adicional OPCIONAL; si se paga, se resuelve el bono "if kicked".
        card._kicked = False
        kick = getattr(card, "_kicker_cost", 0) or 0
        if kick and pay_cost is not None:
            k_cost = Cost(generic=pay_cost.generic + kick, pips=pay_cost.pips)
            if player.can_pay(k_cost):
                pay_cost = k_cost
                card._kicked = True
        # Buyback: coste adicional de maná; si se paga, la carta vuelve a la mano al
        # resolver. Auto: se paga si el jugador puede afrontar coste base + buyback.
        card._buyback_used = False
        bb = getattr(card, "_buyback_cost", 0) or 0
        if bb and pay_cost is not None:
            bb_cost = Cost(generic=pay_cost.generic + bb, pips=pay_cost.pips)
            if player.can_pay(bb_cost):
                pay_cost = bb_cost
                card._buyback_used = True
        # Spree: cada modo elegido suma su coste. Escalate: cada modo extra suma.
        if pay_cost is not None and chosen_modes:
            sc = getattr(card, "spree_costs", None)
            if sc:
                for mi in set(chosen_modes):
                    if 0 <= mi < len(sc) and sc[mi] is not None:
                        pay_cost = Cost(generic=pay_cost.generic + sc[mi].generic,
                                        pips=pay_cost.pips + sc[mi].pips)
            ec = getattr(card, "escalate_cost", None)
            if ec is not None and len(set(chosen_modes)) > 1:
                k = len(set(chosen_modes)) - 1
                pay_cost = Cost(generic=pay_cost.generic + ec.generic * k,
                                pips=pay_cost.pips + ec.pips * k)
        # Splice onto Arcane: otras cartas de la mano con splice suman su efecto
        card._spliced = []
        if pay_cost is not None and "arcane" in {x.lower() for x in card.subtypes}:
            for sp in list(player.hand):
                spc = getattr(sp, "splice_cost", None)
                if sp is card or spc is None:
                    continue
                trial = Cost(generic=pay_cost.generic + spc.generic, pips=pay_cost.pips + spc.pips)
                if player.can_pay(trial) and sp.on_cast_resolve is not None:
                    pay_cost = trial
                    card._spliced.append(sp)
        # Offspring {N} / Squad {N}: costes adicionales opcionales (auto si alcanza):
        # al entrar crea 1 copia 1/1 (offspring) o una copia por pago (squad).
        card._offspring_paid = False
        card._squad_n = 0
        for _attr in ("offspring_cost", "squad_cost"):
            oc = getattr(card, _attr, None)
            if oc is None or pay_cost is None:
                continue
            reps_ = 1 if _attr == "offspring_cost" else 3
            for _ in range(reps_):
                trial = Cost(generic=pay_cost.generic + oc.generic, pips=pay_cost.pips + oc.pips)
                if not player.can_pay(trial):
                    break
                pay_cost = trial
                if _attr == "offspring_cost":
                    card._offspring_paid = True
                else:
                    card._squad_n += 1
        # Replicate {N}: se paga cuantas veces se pueda (auto); cada pago copia el
        # hechizo. Se suma al genérico y se anota el número de copias.
        card._replicate_copies = 0
        rep = getattr(card, "_replicate_cost", 0) or 0
        if rep and pay_cost is not None:
            remaining = player.available_mana() - pay_cost.cmc
            copies = max(0, remaining // rep) if rep else 0
            if copies:
                pay_cost = Cost(generic=pay_cost.generic + rep * copies, pips=pay_cost.pips)
                card._replicate_copies = copies
        # lo girado para convoke/improvise no puede además girarse por maná
        excl = set(convoke_tap)
        if not player.can_pay(pay_cost, exclude=excl):
            return False
        # Casualty N / Bargain: sacrificios OPCIONALES (auto: solo fichas o lo de
        # menor valor que no sea el comandante).
        card._casualty_copy = False
        card._bargained = False
        cas_victim = barg_victim = None
        if getattr(card, "casualty", 0):
            cands = [pm for pm in player.creatures() if pm.power >= card.casualty
                     and not player.is_commander(pm.card) and pm.card is not card]
            cands = [pm for pm in cands if pm.is_token or pm.power + pm.toughness <= 4]
            if cands:
                cas_victim = min(cands, key=lambda pm: (not pm.is_token,
                                                        pm.power + pm.toughness))
        if getattr(card, "bargain", False):
            cands = [pm for pm in player.battlefield if pm.is_token or (
                not pm.is_creature() and not pm.card.is_land()
                and ({"artifact", "enchantment"} & pm.card.types)
                and not player.is_commander(pm.card))]
            cands = [pm for pm in cands if pm is not cas_victim
                     and (pm.is_token or pm.card.produces is None)]
            if cands:
                barg_victim = min(cands, key=lambda pm: (not pm.is_token,
                                                         _cmc_card(pm.card)))
        # coste adicional al lanzar (pagar vida / descartar / sacrificar): se
        # VALIDA todo antes de pagar nada; si falta algo, el hechizo no se lanza
        # (antes se lanzaba igual sin víctima, o el sacrificio se llevaba la fuente
        # de maná y el pago fallaba en silencio: el hechizo salía gratis).
        add = getattr(card, "additional_cost", None) or {}
        victim = None
        if add:
            if add.get("pay_life") and player.life < add["pay_life"]:
                return False
            n_disc = add.get("discard", 0) or 0
            if n_disc and sum(1 for c in player.hand if c is not card) < n_disc:
                return False
            if add.get("sacrifice"):
                creqs = [pm for pm in player.battlefield if pm.is_creature()
                         and pm.card is not card]
                if not creqs:
                    return False
                victim = min(creqs, key=lambda c: (c.power, c.toughness))
        # maná primero: una fuente girada (p. ej. un elfo) igual puede sacrificarse
        if not player.pay(pay_cost, exclude=excl):
            return False
        # Conspire: girar dos criaturas que compartan color -> copia
        card._conspired = False
        if getattr(card, "conspire", False):
            ident = card.identity()
            cr = [pm for pm in player.creatures() if not pm.tapped and pm.attacking is None
                  and (pm.card.identity() & ident)
                  and (pm.summoning_sick or getattr(player, "attacked_turn", None) == self.turn)]
            if len(cr) >= 2:
                for pm in cr[:2]:
                    pm.tapped = True
                card._conspired = True
                self.log(f"{player.name} conspira con {cr[0].name} y {cr[1].name}")
        card._demonstrated = bool(getattr(card, "demonstrate", False))
        # Gift: prometer el regalo a un rival (no se promete un turno extra)
        card._gift_promised = False
        gk = getattr(card, "gift_kind", None)
        if gk and gk != "extra turn":
            card._gift_promised = True
        if cas_victim is not None and cas_victim in player.battlefield:
            self.to_graveyard(cas_victim, "casualty")
            card._casualty_copy = True
            self.log(f"{player.name} sacrifica {cas_victim.name} (casualty): copia el hechizo")
        if barg_victim is not None and barg_victim in player.battlefield:
            self.to_graveyard(barg_victim, "bargain")
            card._bargained = True
            self.log(f"{player.name} sacrifica {barg_victim.name} (bargain)")
        # consumir recursos de las reducciones dinámicas
        for pm in convoke_tap:
            pm.tapped = True
        if convoke_tap:
            self.log(f"{player.name} gira {len(convoke_tap)} criatura(s) (convoke)")
        if delve_n:
            for _ in range(delve_n):
                if player.graveyard:
                    player.exile.append(player.graveyard.pop())
            self.log(f"{player.name} exilia {delve_n} del cementerio (delve)")

        # quitar de la zona de origen
        if from_command:
            if card in player.command:
                player.command.remove(card)
            player.add_tax(card)
        else:
            card._cast_from_hand = card in player.hand
            if card in player.hand:
                player.hand.remove(card)

        # costes adicionales, ya con la carta fuera de la mano (no se descarta a sí
        # misma) y con el maná pagado
        if add:
            if add.get("pay_life"):
                player.life -= add["pay_life"]
            for _ in range(add.get("discard", 0) or 0):
                if player.hand:
                    player.graveyard.append(player.hand.pop())
            if victim is not None and victim in player.battlefield:
                self.to_graveyard(victim, "coste adicional")
            self.log(f"{player.name} paga el coste adicional de {card.name}")

        self.log(f"{player.name} lanza {card.name}")
        # telemetria: registrar el lanzamiento y el turno del comandante
        st = getattr(player, "stats", None)
        if st is not None:
            st["cast_counts"][card.name] += 1
            if player.is_commander(card) and st["commander_turn"] is None:
                st["commander_turn"] = self.turn
        # Storm: copias = hechizos ya lanzados este turno ANTES de este.
        # Replicate: copias = pagos extra ya calculados arriba. Ambas repiten efecto.
        storm_copies = self.spells_this_turn if (getattr(card, "tags", set())
                                                 and "storm" in card.tags) else 0
        storm_copies += getattr(card, "_replicate_copies", 0) or 0
        storm_copies += 1 if getattr(card, "_casualty_copy", False) else 0
        storm_copies += 1 if getattr(card, "_conspired", False) else 0
        self.spells_this_turn += 1
        player.spells_cast_turn = getattr(player, "spells_cast_turn", 0) + 1
        # Buyback: si se pagó el coste adicional de buyback, la carta vuelve a la mano.
        buyback_used = bool(getattr(card, "_buyback_used", False))
        card._cast_x = cast_x            # las copias del hechizo conservan su X

        def _resolve(g):
            prev_x = g.spell_x
            g.spell_x = cast_x
            prev_rc = getattr(g, "_resolving_card", None)
            g._resolving_card = card
            try:
                if getattr(card, "_gift_promised", False):
                    g._give_gift(player, card)
                if getattr(card, "ascend", False):
                    g._check_ascend(player, force=True)
                _resolve_spell(g)
            finally:
                g.spell_x = prev_x
                g._resolving_card = prev_rc

        def _resolve_spell(g):
            if card.is_land():  # las tierras no se lanzan, pero por seguridad
                g.move_to_battlefield(card, player)
            elif {"instant", "sorcery"} & card.types:
                if card.modes:
                    picks = chosen_modes if chosen_modes else [0]
                    per_mode = g.split_mode_targets(card.modes, picks, targets or [])
                    for mi in picks:
                        if 0 <= mi < len(card.modes):
                            m = card.modes[mi]
                            g.note_ability(card, f"modo «{m.get('label', '')}»", controller=player)
                            eff = m.get("effect")
                            if eff:
                                eff(g, player, per_mode.get(mi, []))
                elif card.on_cast_resolve:
                    g.note_ability(card, "resuelve su efecto", controller=player)
                    reps = 1 + storm_copies      # storm: repetir el efecto por copia
                    if storm_copies:
                        g.log(f"Storm: {card.name} se copia {storm_copies} vez(ces)")
                    eff = card.on_cast_resolve
                    if getattr(card, "_cleaved", False) and \
                            getattr(card, "cleave_effect", None) is not None:
                        eff = card.cleave_effect
                    if getattr(card, "_overloaded", False) and \
                            getattr(card, "overload_effect", None) is not None:
                        eff = card.overload_effect
                        g.log(f"{card.name} con sobrecarga (overload)")
                    if getattr(card, "_bargained", False) and \
                            getattr(card, "bargain_effect", None) is not None:
                        be = card.bargain_effect
                        eff = be if getattr(card, "bargain_instead", False) else (
                            lambda gg, pp, tt, _a=eff, _b=be: (_a(gg, pp, tt), _b(gg, pp, tt)))
                    for _ in range(reps):
                        eff(g, player, targets or [])
                    # demonstrate: un rival también copia el hechizo
                    if getattr(card, "_demonstrated", False):
                        card._demonstrated = False
                        opps = g.opponents(player)
                        if opps:
                            o = min(opps, key=lambda x: sum(pm.power for pm in x.creatures()))
                            eff(g, player, targets or [])
                            g.log(f"{player.name} demuestra: copia para sí y para {o.name}")
                            eff(g, o, g._auto_targets(o, card) or [])
                    # epic: desde ahora no lanzás hechizos; se copia cada mantenimiento
                    if getattr(card, "epic", False):
                        player.epic_locked = True
                        g.epic.append((player, card))
                        g.log(f"{player.name}: épico — ya no lanza hechizos")
                    # paradigm: primera vez -> exiliada y copia gratis cada turno
                    if getattr(card, "paradigm", False) and not any(
                            c is card for _p, c in g.paradigm):
                        g.paradigm.append((player, card))
                        card._exile_after_cast = True
                    # splice: los efectos empalmados se suman
                    for sp in getattr(card, "_spliced", None) or []:
                        g.log(f"{card.name}: se empalma {sp.name} (splice)")
                        stg = g._auto_targets(player, sp) or []
                        sp.on_cast_resolve(g, player, stg)
                    card._spliced = []
                    # awaken: una tierra tuya se vuelve criatura con N contadores
                    if getattr(card, "_awakened", False):
                        card._awakened = False
                        g.animate_land(player, getattr(card, "awaken_n", 0))
                else:
                    # carta sin efecto modelado (mecánica compleja): que al menos se
                    # vea que se resolvió, en vez de "no pasó nada".
                    g.log(f"{player.name} resuelve {card.name} "
                          f"(efecto complejo: no se simula en detalle)")
                # Kicker: bono adicional si se pagó el coste de kicker.
                if getattr(card, "_kicked", False) and getattr(card, "_kicked_effect", None):
                    g.log(f"{card.name} fue kickeado: bono")
                    card._kicked_effect(g, player)
                card._overloaded = False
                card._cleaved = False
                # Rebound: lanzada desde la mano -> al exilio y en tu próximo
                # mantenimiento se lanza gratis.
                if (getattr(card, "rebound", False) and getattr(card, "_cast_from_hand", False)
                        and not getattr(card, "_exile_after_cast", False)):
                    card._cast_from_hand = False
                    player.exile.append(card)
                    g.rebound.append((player, card))
                    g.log(f"{card.name} se exilia (rebound): se relanza en el próximo mantenimiento")
                # Flashback/escape: al dejar la pila va al exilio (aunque la
                # resolución ocurra después de una pausa de reacción del humano).
                elif getattr(card, "_exile_after_cast", False):
                    card._exile_after_cast = False
                    player.exile.append(card)
                    g.log(f"{card.name} se exilia tras lanzarse desde el cementerio")
                # Buyback: vuelve a la mano en vez de al cementerio.
                elif buyback_used:
                    player.hand.append(card)
                    g.log(f"{card.name} vuelve a la mano (buyback)")
                else:
                    player.graveyard.append(card)
                    g.emit("to_graveyard", player=player, card=card)
                    # haunt (hechizo): tras resolver se exilia rondando una criatura
                    if getattr(card, "haunt_effect", None) is not None:
                        g._haunt(player, card, card.haunt_effect)
            else:
                g.move_to_battlefield(card, player)

        spell_obj = StackObject(player, _resolve, source=card, targets=targets,
                                label=f"spell:{card.name}", chosen_modes=chosen_modes)
        self.stack.append(spell_obj)
        self._targeted_triggers(player, targets, spell=True)
        # Ripple N: revelá N de arriba; las del mismo nombre se lanzan gratis
        rn = getattr(card, "ripple", 0)
        if rn and getattr(card, "_cast_from_hand", False):
            top = player.library[-rn:]
            del player.library[-rn:]
            same = [c for c in top if c.name == card.name]
            rest = [c for c in top if c.name != card.name]
            player.library[0:0] = rest
            for c in same:
                self.log(f"Ripple: {player.name} lanza otra {c.name}")
                self.stack.append(StackObject(
                    player, (lambda g, _c=c: (_c.on_cast_resolve(g, player,
                             g._auto_targets(player, _c) or []) if _c.on_cast_resolve
                             else None, player.graveyard.append(_c))),
                    source=c, label=f"ripple:{c.name}", kind="trigger"))
        # disparos "cuando lanzás un hechizo" DESPUÉS de apilar el hechizo: quedan
        # encima y resuelven antes que él (magecraft, "copiá ese hechizo"...).
        self.emit("cast", player=player, card=card)
        # disparos "cuando un RIVAL lanza un hechizo": evento sin scope; el callback
        # sólo actúa si el permanente que observa NO es del que lanzó.
        self.emit("opp_cast", caster=player, card=card)
        # prowess: al lanzar un hechizo no-criatura, +1/+1 a las criaturas con prowess
        if {"instant", "sorcery"} & card.types:
            for perm in player.battlefield:
                if perm.has("prowess"):
                    perm.temp_pt[0] += 1
                    perm.temp_pt[1] += 1
        # la ventana de reacción es sobre el HECHIZO (no sobre un disparo de encima)
        return self._after_stack_push(player, spell_obj, obj=spell_obj)

    def _after_stack_push(self, player, react_arg, obj=None):
        """Tras poner un objeto en la pila (hechizo o habilidad): si ya estamos en
        una ventana de prioridad, dejarlo para el bucle externo; si hay un humano
        que puede reaccionar, pausar (ReactionPause); si no, drenar con prioridad."""
        if self._in_priority:
            return True   # puesto en respuesta: el bucle externo lo resolverá
        # ventana de reacción del humano: si un rival hace algo que el humano
        # podría responder, pausamos (la capa interactiva reanuda tras responder).
        rc = getattr(self, "reaction_check", None)
        if rc is not None and rc(player, react_arg):
            raise ReactionPause(obj if obj is not None else self.stack[-1])
        self._run_priority_and_resolve()
        return True

    def ability_allowed(self, perm: Permanent, index: int, ab: dict) -> bool:
        """Exhaust / Power-up: una sola vez. Boast: solo si atacó este turno y una
        vez por turno. 'Activate only if …': la condición."""
        used = getattr(perm, "_abil_used", None) or {}
        if ab.get("once") and used.get(index):
            return False
        if ab.get("boast"):
            if getattr(perm, "attacked_turn", None) != self.turn:
                return False
            if used.get(index) == self.turn:
                return False
        if ab.get("once_turn") and used.get(index) == self.turn:
            return False
        sr = ab.get("station_req")
        if sr and perm.counters.get("charge", 0) < sr:
            return False
        if ab.get("solved_req") and not getattr(perm, "solved", False):
            return False
        cond = ab.get("only_if")
        if cond is not None:
            try:
                if not cond(self, perm.controller):
                    return False
            except Exception:  # noqa: BLE001
                return False
        return True

    def _mark_ability_used(self, perm: Permanent, index: int, ab: dict):
        if ab.get("once") or ab.get("boast") or ab.get("once_turn"):
            if getattr(perm, "_abil_used", None) is None:
                perm._abil_used = {}
            perm._abil_used[index] = True if ab.get("once") else self.turn

    def _targeted_triggers(self, caster, targets, spell=True):
        """Heroic ('whenever you cast a spell that targets ~') y valiant ('becomes
        the target of a spell or ability you control for the first time each turn')."""
        for t in (targets or []):
            if not isinstance(t, Permanent) or t.controller is not caster:
                continue
            if spell:
                self._push_self_trigger(t, "targeted_by_spell", "heroico")
            if getattr(t, "_valiant_turn", None) != self.turn and \
                    (t.card.triggers or {}).get("targeted_first"):
                t._valiant_turn = self.turn
                self._push_self_trigger(t, "targeted_first", "valiente")

    def _push_self_trigger(self, perm, key, label, **kw):
        """Encola el disparo `key` del propio permanente (enrage, inspired,
        heroic, battalion…). El callback recibe (game, perm, **kw)."""
        cb = (perm.card.triggers or {}).get(key)
        if cb is None or perm.abilities_off():
            return
        self.stack.append(StackObject(
            perm.controller,
            (lambda g, _cb=cb, _p=perm, _kw=kw: g._run_trigger(_cb, _p, _kw)),
            source=perm, label=f"{key}:{perm.name}", kind="trigger", perm=perm))
        self.note_ability(perm.card, label, controller=perm.controller)

    def split_second_on_stack(self) -> bool:
        return any(str(getattr(o, "label", "")).startswith("spell:")
                   and "split_second" in (getattr(getattr(o, "source", None), "keywords",
                                                  None) or ())
                   for o in self.stack)

    def _uncounterable(self, obj, card) -> bool:
        if getattr(card, "uncounterable", False):
            return True
        ctrl = getattr(obj, "controller", None)
        for pm in (ctrl.battlefield if ctrl is not None else []):
            g = getattr(pm.card, "grants_uncounterable", None)
            if g == "any" or (g == "creature" and card.is_creature()):
                return True
        return False

    def counter_spell(self, obj) -> bool:
        """Contrarresta el objeto `obj` de la pila y manda su carta a donde
        corresponde: nada si es una COPIA (la carta original sigue en la pila o ya
        resolvió), exilio si se lanzó con flashback/escape, zona de mando si es el
        comandante, cementerio en otro caso. Devuelve False si ya no estaba."""
        if obj not in self.stack:
            return False
        card = getattr(obj, "source", None)
        # "can't be countered" (la carta o un permanente de su controlador)
        if card is not None and hasattr(card, "types") and self._uncounterable(obj, card):
            self.log(f"{card.name} no puede ser contrarrestado")
            return False
        self.stack.remove(obj)
        if card is None or card.is_land() or str(getattr(obj, "label", "")).startswith("copy:"):
            return True
        ctrl = obj.controller
        if getattr(card, "_exile_after_cast", False):
            card._exile_after_cast = False
            ctrl.exile.append(card)
        elif self.commander_owner(card) is not None:
            self.commander_owner(card).command.append(card)
            self.log(f"{card.name} vuelve a la zona de mando")
        else:
            ctrl.graveyard.append(card)
            self.emit("to_graveyard", player=ctrl, card=card)
        return True

    def _respond_order(self):
        """Jugadores que pueden responder al tope de la pila (los oponentes de
        quien controla el tope), en orden de turno."""
        top = self.stack[-1]
        n = len(self.players)
        order = []
        for k in range(n):
            pl = self.players[(self.active_index + k) % n]
            if pl is not top.controller and not pl.lost:
                order.append(pl)
        return order

    def _run_priority_and_resolve(self):
        """Ventana de prioridad (P2.1): tras poner algo en la pila, cada
        oponente puede responder (instantaneos). Cuando todos pasan, resuelve
        el tope. Repite hasta vaciar la pila."""
        self._in_priority = True
        guard = 0
        try:
            while self.stack:
                guard += 1
                if guard > 5000:        # cortafuegos anti-bucle (nunca en juego normal)
                    self.log("aviso: se cortó la ventana de prioridad (límite de seguridad)")
                    self.stack.clear()
                    break
                responded = False
                # split second: mientras esté en la pila, nadie puede responder
                if self.split_second_on_stack():
                    top = self.stack.pop()
                    if not top.controller.lost:
                        top.resolve(self)
                    self.sba()
                    continue
                # el controlador del tope puede copiar su PROPIO hechizo (Fork/Twincast)
                top = self.stack[-1]
                ctrl = getattr(top, "controller", None)
                if ctrl is not None and not ctrl.lost:
                    pol = ctrl.policy
                    if pol is not None and hasattr(pol, "respond_copy"):
                        if pol.respond_copy(self, ctrl, top):
                            continue
                    # A3: el controlador puede copiar su PROPIA habilidad con un
                    # permanente 'copiar habilidad' (Strionic) si vale la pena.
                    if pol is not None and hasattr(pol, "respond_ability"):
                        if pol.respond_ability(self, ctrl, top):
                            continue
                for pl in self._respond_order():
                    pol = pl.policy
                    if pol is not None and hasattr(pol, "respond"):
                        if pol.respond(self, pl, self.stack[-1]):
                            responded = True
                            break
                if responded:
                    continue
                top = self.stack.pop()
                if not top.controller.lost:
                    prev_c = self._fx_controller
                    self._fx_controller = top.controller
                    try:
                        top.resolve(self)
                    finally:
                        self._fx_controller = prev_c
                self.sba()
        finally:
            self._in_priority = False

    def activate_loyalty(self, perm: Permanent, index: int) -> bool:
        """Activa una habilidad de lealtad (P2.3). Una por turno. `index`
        selecciona la habilidad en card.loyalty_abilities = ((coste, efecto),..)
        con coste +N (sube) o -N (baja, exige lealtad suficiente)."""
        if perm.activated_this_turn or "planeswalker" not in perm.card.types:
            return False
        abilities = perm.card.loyalty_abilities
        if not abilities or not (0 <= index < len(abilities)):
            return False
        cost, eff = abilities[index]
        loy = perm.counters.get("loyalty", 0)
        if cost < 0 and loy + cost < 0:
            return False
        # el coste de lealtad se paga al activar (una por turno), pero el EFECTO
        # va a la pila y se resuelve con prioridad (refactor A: habilidades en pila).
        perm.counters["loyalty"] = loy + cost
        perm.activated_this_turn = True
        self.log(f"{perm.controller.name}: {perm.name} activa {cost:+d} "
                 f"(lealtad {perm.counters['loyalty']})")
        self.note_ability(perm.card, f"lealtad {cost:+d}", controller=perm.controller)
        ctrl = perm.controller

        def _resolve(g, _eff=eff, _c=ctrl, _p=perm, _cost=cost):
            if _eff:
                _eff(g, _c, _p)
            g.last_ability = {
                "source": _p.card, "perm": _p, "label": f"lealtad {_cost:+d}",
                "run": (lambda gg, __e=_eff, __c=_c, __p=_p: __e(gg, __c, __p) if __e else None),
            }

        self.stack.append(StackObject(
            ctrl, _resolve, source=perm.card, label=f"ability:{perm.name}:loyalty",
            kind="ability", perm=perm))
        return self._after_stack_push(ctrl, self.stack[-1])

    def activate_ability(self, perm: Permanent, index: int, targets=None, x=0) -> bool:
        """Activa una habilidad con coste de maná (y opcionalmente girar) de un
        permanente. El coste se paga al activar; el EFECTO va a la pila y se
        resuelve con prioridad (refactor A). Se puede repetir mientras haya con
        qué pagar. `x` es el valor de X para habilidades con {X} en el coste."""
        abils = perm.card.activated_abilities
        if not abils or not (0 <= index < len(abils)):
            return False
        ab = abils[index]
        if ab.get("tap") and perm.tapped:
            return False
        # {T} de una criatura con mareo de invocación (sin prisa): no se puede
        if ab.get("tap") and perm.is_creature() and perm.summoning_sick \
                and not perm.has("haste"):
            return False
        ctrl = perm.controller
        # si la habilidad gira el permanente, éste no puede además girarse como
        # fuente de maná para pagarla (Mind Stone sola activaba {1},{T})
        excl = {perm} if ab.get("tap") else None
        # Clase: una habilidad de "subir a nivel N" solo se puede activar estando en
        # el nivel N-1 (si no, antes pagaba el maná y no hacía nada).
        lr = ab.get("level_req")
        if lr is not None and perm.counters.get("level", 1) != lr - 1:
            return False
        if not self.ability_allowed(perm, index, ab):
            return False
        if getattr(perm, "_detained_by", None) is not None:
            return False                     # detenido: no activa habilidades
        # habilidad con {X}: el coste efectivo suma X maná genérico.
        base_cost = ab.get("cost")
        xv = max(0, int(x)) if ab.get("x_cost") else 0
        pay_cost = Cost(base_cost.generic + xv, base_cost.pips) if (xv and base_cost) else base_cost
        if not ctrl.can_pay(pay_cost, exclude=excl):
            return False
        # "girá N <tipo> enderezados que controles" (cohort, etc.)
        to = ab.get("tap_others")
        tap_victims = []
        if to:
            k = to["type"]
            pool = [pm for pm in ctrl.battlefield if pm is not perm and not pm.tapped and (
                pm.is_creature() if k == "creature" else
                (k in pm.card.types) if k in ("artifact", "land", "enchantment")
                else pm.has_subtype(k))]
            pool.sort(key=lambda x: (not x.summoning_sick, x.power))
            if len(pool) < to["n"]:
                return False
            tap_victims = pool[:to["n"]]
        # costes adicionales: verificar que se pueden pagar ANTES de tocar nada.
        sac_o = ab.get("sacrifice_other")
        pay_life = ab.get("pay_life") or 0
        disc = ab.get("discard") or 0
        sac_victims = []
        if sac_o:
            sac_victims = self._sacrifice_candidates(ctrl, sac_o["type"],
                                                     sac_o["count"], exclude=perm)
            if len(sac_victims) < sac_o["count"]:
                return False
        if pay_life and ctrl.life <= pay_life:
            return False   # pagar vida no puede dejarte en 0 o menos
        if disc > 0 and len(ctrl.hand) < disc:
            return False
        rmc = ab.get("rm_counter")
        if rmc and perm.counters.get(rmc["name"], 0) < rmc["n"]:
            return False   # sin contadores suficientes para pagar el coste
        ctrl.pay(pay_cost, exclude=excl)
        for tv in tap_victims:
            tv.tapped = True
        self._mark_ability_used(perm, index, ab)
        if ab.get("tap") and not perm.tapped:
            self._push_self_trigger(perm, "becomes_tapped", "se gira")
        if ab.get("exert_self"):
            perm.exerted = True          # no se endereza en tu próximo enderezar
        if rmc:
            perm.counters[rmc["name"]] = perm.counters.get(rmc["name"], 0) - rmc["n"]
            self.log(f"{ctrl.name} quita {rmc['n']} contador(es) {rmc['name']} "
                     f"de {perm.name} (coste)")
        if ab.get("tap"):
            perm.tapped = True
        # pagar los costes adicionales (todos son parte del coste, no van a la pila)
        for v in sac_victims:
            self.to_graveyard(v, "coste: sacrificio")
        if pay_life:
            ctrl.life -= pay_life
            self.log(f"{ctrl.name} paga {pay_life} de vida (coste)")
        if disc:
            self._pay_discard(ctrl, disc)
        if ab.get("sacrifice_self"):
            # el sacrificio es parte del COSTE: se paga al activar (el efecto ya
            # está en la pila y no necesita al permanente).
            self.to_graveyard(perm, "coste: sacrificio")
        if ab.get("exile_self"):
            # exiliar ESTE permanente como coste (Perpetual Timepiece, etc.).
            if perm in ctrl.battlefield:
                ctrl.battlefield.remove(perm)
                if not perm.is_token and not ctrl.is_commander(perm.card):
                    ctrl.exile.append(perm.card)
                self.log(f"{ctrl.name} exilia {perm.name} (coste)")
        self.log(f"{ctrl.name}: {perm.name} activa «{ab.get('label', '')}»")
        self.note_ability(perm.card, f"habilidad: {ab.get('label', '')}", controller=ctrl)
        eff = ab.get("effect")
        _t = list(targets or [])
        is_copy = bool(ab.get("is_copy_ability"))

        def _resolve(g, _eff=eff, _c=ctrl, _p=perm, _tg=_t, _ab=ab, _is_copy=is_copy, _x=xv):
            if _eff:
                g._ability_x = _x            # valor de X para habilidades {X}
                prev = getattr(g, "_trigger_source", None)
                g._trigger_source = _p       # '~' / 'this creature' = la fuente
                try:
                    _eff(g, _c, _p, _tg)
                finally:
                    g._trigger_source = prev
                    g._ability_x = 0
            # recordar esta habilidad para "copiá la última habilidad" (Strionic).
            # La propia habilidad de copia NO se registra (evita copiarse a sí misma).
            if not _is_copy:
                g.last_activated = (_p, _ab, list(_tg))
                if _eff:
                    g.last_ability = {
                        "source": _p.card, "perm": _p, "label": _ab.get("label", ""),
                        "run": (lambda gg, __e=_eff, __c=_c, __p=_p, __tg=_tg:
                                __e(gg, __c, __p, list(__tg))),
                    }

        self.stack.append(StackObject(
            ctrl, _resolve, source=perm.card, targets=_t,
            label=f"ability:{perm.name}:{ab.get('label', '')}", kind="ability",
            perm=perm, is_copy_ability=is_copy))
        return self._after_stack_push(ctrl, self.stack[-1])

    _SPEC_OK = {
        "opp_creature": lambda o: isinstance(o, Permanent) and o.is_creature(),
        "own_creature": lambda o: isinstance(o, Permanent) and o.is_creature(),
        "any_creature": lambda o: isinstance(o, Permanent) and o.is_creature(),
        "opp_player": lambda o: isinstance(o, Player),
        "any_artifact": lambda o: isinstance(o, Permanent) and "artifact" in o.card.types,
        "any_enchantment": lambda o: isinstance(o, Permanent) and "enchantment" in o.card.types,
        "any_art_ench": lambda o: isinstance(o, Permanent)
        and bool({"artifact", "enchantment"} & o.card.types),
        "any_planeswalker": lambda o: isinstance(o, Permanent)
        and "planeswalker" in o.card.types,
        "any_nonland": lambda o: isinstance(o, Permanent) and not o.card.is_land(),
        "any_perm": lambda o: isinstance(o, Permanent),
        "own_perm": lambda o: isinstance(o, Permanent),
        "stack_spell": lambda o: isinstance(o, StackObject),
        "stack_ability": lambda o: isinstance(o, StackObject),
    }

    def split_mode_targets(self, modes, picks, targets) -> dict:
        """Reparte los objetivos de un hechizo MODAL entre los modos elegidos según
        el tipo que pide cada uno (antes cada modo recibía TODOS: 'destruí un
        artefacto' destruía también la criatura y apuntaba al jugador)."""
        rest = list(targets or [])
        out = {}
        for mi in picks:
            if not (0 <= mi < len(modes)):
                continue
            spec = modes[mi].get("target_spec")
            if not spec:
                out[mi] = []
                continue
            ok = self._SPEC_OK.get(spec, lambda o: True)
            n = max(1, modes[mi].get("target_count", 1) or 1)
            mine = [o for o in rest if ok(o)][:n]
            for o in mine:
                rest.remove(o)
            out[mi] = mine
        return out

    def copy_spell_on_stack(self, obj, controller=None):
        """Pone en la pila una COPIA del hechizo `obj` (StackObject). La copia se
        resuelve con el mismo efecto y objetivos y luego deja de existir (no va a
        ninguna zona). Cubre Fork / Twincast / Reverberate."""
        src = getattr(obj, "source", None)
        if src is None:
            return
        ctrl = controller or obj.controller
        tgts = list(getattr(obj, "targets", None) or [])
        picks = list(getattr(obj, "chosen_modes", None) or [])

        def _resolve(g, _src=src, _ctrl=ctrl, _tgts=tgts, _picks=picks):
            prev_x = g.spell_x
            g.spell_x = getattr(_src, "_cast_x", 0) or 0     # la copia conserva X
            try:
                _resolve_copy(g, _src, _ctrl, _tgts, _picks)
            finally:
                g.spell_x = prev_x

        def _resolve_copy(g, _src, _ctrl, _tgts, _picks):
            g.note_ability(_src, "copia del hechizo se resuelve", controller=_ctrl)
            if getattr(_src, "modes", None):
                # la copia reproduce los MISMOS modos que eligió el original
                idxs = _picks if _picks else [0]
                per_mode = g.split_mode_targets(_src.modes, idxs, _tgts)
                for mi in idxs:
                    if 0 <= mi < len(_src.modes):
                        e = _src.modes[mi].get("effect")
                        if e:
                            e(g, _ctrl, per_mode.get(mi, []))
            elif _src.on_cast_resolve:
                _src.on_cast_resolve(g, _ctrl, _tgts)
            else:
                g.log(f"copia de {_src.name} (efecto complejo: no se simula en detalle)")
            # una copia no se pone en ninguna zona: deja de existir al resolverse

        self.stack.append(StackObject(ctrl, _resolve, source=src, targets=tgts,
                                      label=f"copy:{src.name}"))
        self.log(f"{ctrl.name} copia el hechizo {src.name}")

    def copy_ability_on_stack(self, obj, controller=None):
        """Pone en la pila una COPIA de una habilidad `obj` (StackObject de tipo
        'ability'/'trigger') que aún está en la pila. Re-ejecuta el mismo efecto
        (misma fuente y objetivos). Cubre Strionic Resonator apuntando a una
        habilidad concreta (no solo 'la última')."""
        if obj is None or getattr(obj, "resolve", None) is None:
            return
        ctrl = controller or obj.controller
        src = getattr(obj, "source", None)
        label = getattr(obj, "label", "")

        def _resolve(g, _r=obj.resolve):
            _r(g)   # re-ejecuta el efecto de la habilidad copiada

        self.stack.append(StackObject(
            ctrl, _resolve, source=src, label=f"copy:{label}", kind="ability",
            perm=getattr(obj, "perm", None)))
        self.log(f"{ctrl.name} copia la habilidad ({label})")

    def copy_last_ability(self, ctrl):
        """Copia (vuelve a ejecutar) la última habilidad COPIABLE resuelta —
        activada O disparada— sin volver a pagar su coste. Aproximación de Strionic
        Resonator: como el motor resuelve las habilidades al instante y sin ventana
        de prioridad, se copia la más reciente registrada en `last_ability`."""
        la = self.last_ability
        if not la or not la.get("run"):
            self.log(f"{ctrl.name}: no hay habilidad reciente para copiar")
            return
        label = la.get("label", "")
        self.note_ability(la.get("source"), f"copia de «{label}»", controller=ctrl)
        self.log(f"{ctrl.name} copia la habilidad «{label}»")
        la["run"](self)
        self.sba()

    def _static_cost_reduction(self, player: "Player", card: Card) -> int:
        """Reducción de coste genérico que dan permanentes del jugador a los
        hechizos que lanza ('creature spells you cast cost {N} less', etc.).
        card.spell_discount = (monto, filtro) con filtro any/creature/noncreature/
        instant_sorcery/artifact."""
        types = getattr(card, "types", set())
        total = 0
        for pm in player.battlefield:
            disc = getattr(pm.card, "spell_discount", None)
            if not disc:
                continue
            amt, filt = disc
            ok = filt(card) if callable(filt) else (filt == "any"
                  or (filt == "creature" and "creature" in types)
                  or (filt == "noncreature" and "creature" not in types)
                  or (filt == "instant_sorcery" and ({"instant", "sorcery"} & types))
                  or (filt == "artifact" and "artifact" in types))
            if ok:
                total += amt
        return total

    def _static_cost_increase(self, player: "Player", card: Card) -> int:
        """Impuesto de coste (stax) que dan permanentes EN JUEGO a los hechizos que
        lanza `player`. card.spell_tax = (monto, filtro, quien) con quien in
        {'all','opponents'} y filtro any/creature/noncreature/instant_sorcery/artifact."""
        types = getattr(card, "types", set())
        total = 0
        for pm in self.all_permanents():
            tx = getattr(pm.card, "spell_tax", None)
            if not tx:
                continue
            amt, filt, whose = tx
            if whose == "opponents" and pm.controller is player:
                continue
            ok = filt(card) if callable(filt) else (filt == "any"
                  or (filt == "creature" and "creature" in types)
                  or (filt == "noncreature" and "creature" not in types)
                  or (filt == "instant_sorcery" and ({"instant", "sorcery"} & types))
                  or (filt == "artifact" and "artifact" in types))
            if ok:
                total += amt
        return total

    def set_day_night(self, value: str):
        """Cambia a 'day'/'night' y transforma las cartas daybound/nightbound a la
        cara correcta (daybound: frente=día, dorso=noche; nightbound al revés)."""
        if value == self.day_night:
            return
        self.day_night = value
        self.log(f"Ahora es de {'día' if value == 'day' else 'noche'}")
        for pl in self.players:
            for perm in list(pl.battlefield):
                faces = getattr(perm, "_dfc_faces", None)
                if faces:
                    front = faces[0]
                else:
                    # aún no transformado: la cara actual es el frente
                    if getattr(perm.card, "back_face", None) is None:
                        continue
                    front = perm.card
                # sólo las cartas daybound/nightbound se transforman con el día/noche
                if not (getattr(front, "daybound", False)
                        or getattr(front, "nightbound", False)):
                    continue
                # frente = cara de día; dorso = cara de noche
                want_front = (value == "day")
                idx = getattr(perm, "_dfc_idx", 0)
                if (idx == 0) != want_front:
                    self.transform(perm)

    def _update_day_night(self, active: "Player"):
        """Regla simplificada: si el jugador activo no lanzó hechizos este turno,
        se hace de noche; si alguien lanzó 2+ hechizos, se hace de día."""
        if self.day_night is None:
            return
        casts = getattr(self, "spells_this_turn", 0)
        if self.day_night == "day" and casts == 0:
            self.set_day_night("night")
        elif self.day_night == "night" and casts >= 2:
            self.set_day_night("day")

    def transform(self, perm: "Permanent") -> bool:
        """Da vuelta un permanente de doble cara (transform): intercambia su carta
        actual con la cara trasera, conservando contadores/estado. Devuelve True si
        transformó."""
        faces = getattr(perm, "_dfc_faces", None)
        if faces is None:
            back = getattr(perm.card, "back_face", None)
            if back is None:
                return False
            faces = perm._dfc_faces = [perm.card, back]
            perm._dfc_idx = 0
        perm._dfc_idx ^= 1
        perm.card = faces[perm._dfc_idx]
        self.log(f"{perm.name} se transforma")
        self.sba()
        return True

    def play_dfc_back(self, player: "Player", front: Card, targets=None,
                      chosen_modes=None, x_value=None):
        """Juega la cara TRASERA de un DFC modal desde la mano (Pathway, DFC modal
        tierra/hechizo). Sólo modal: la trasera tiene su propio coste."""
        back = getattr(front, "back_face", None)
        if back is None or getattr(front, "dfc", None) != "modal":
            return False
        if front not in player.hand:
            return False
        # canjeamos el frente por el dorso en la mano y jugamos el dorso
        idx = player.hand.index(front)
        player.hand[idx] = back
        if back.is_land():
            ok = self.play_land(player, back)
        else:
            ok = self.cast(player, back, targets=targets,
                           chosen_modes=chosen_modes, x_value=x_value)
        if ok is False and back in player.hand:      # revertir si no se pudo
            player.hand[player.hand.index(back)] = front
        return ok

    def land_limit(self, player: "Player") -> int:
        """Cuántas tierras puede jugar este turno: 1 + las 'additional land' que
        le den sus permanentes en juego (Exploration, Azusa, etc.)."""
        extra = sum(getattr(pm.card, "extra_land", 0) or 0
                    for pm in player.battlefield)
        return 1 + extra

    def play_land(self, player: "Player", card: Card) -> bool:
        if player.lands_played >= self.land_limit(player):
            return False
        if card in player.hand:
            player.hand.remove(card)
        player.lands_played += 1
        self.log(f"{player.name} juega tierra {card.name}")
        self.move_to_battlefield(card, player)
        return True

    # -- jugar/activar fuera del campo (compartido por humano y bots) ------ #
    def play_from_graveyard(self, p: "Player", card: Card,
                            targets=None, chosen_modes=None) -> bool:
        """Juega una carta desde el cementerio según su `gy_play` (flashback,
        escape, unearth, embalm, disturb, recursión). Devuelve True si se jugó."""
        import cards as _cards
        gp = getattr(card, "gy_play", None) or {}
        cost = gp.get("cost")
        if not gp or card not in p.graveyard:
            return False
        if cost is not None and not p.can_pay(cost):
            return False
        # retrace (descartar una tierra) / jump-start (descartar una carta)
        disc_kind = gp.get("discard")
        disc_pool = []
        if disc_kind:
            disc_pool = [c for c in p.hand if disc_kind == "any" or c.is_land()]
            if not disc_pool:
                return False
        m, after = gp.get("mode"), gp.get("after")
        if m == "mayhem" and getattr(card, "_discarded_turn", None) != self.turn:
            return False
        if m == "harmonize" and cost is not None:
            cr = [pm for pm in p.creatures() if not pm.tapped and pm.attacking is None]
            if cr:
                best = max(cr, key=lambda x: x.power)
                red = min(cost.generic, max(0, best.power))
                if red:
                    best.tapped = True
                    cost = Cost(cost.generic - red, cost.pips)
                    self.log(f"{p.name} gira {best.name} para armonizar (-{red})")
        def _discard_for_play():
            if not disc_pool:
                return
            pol = p.policy
            pick = None
            if disc_kind == "any" and pol is not None and hasattr(pol, "choose_discard"):
                try:
                    pick = pol.choose_discard(self, p)
                except Exception:  # noqa: BLE001
                    pick = None
                if pick not in disc_pool:
                    pick = None
            pick = pick or min(disc_pool, key=lambda c: (not c.is_land(), _cmc_card(c)))
            p.hand.remove(pick)
            self.log(f"{p.name} descarta {pick.name} ({m})")
            self.discard_card(p, pick)
        if m == "aftermath":
            # secuela: se lanza SÓLO desde el cementerio, resuelve su efecto y exilia.
            if cost is not None:
                p.pay(cost)
            p.graveyard.remove(card)
            eff = gp.get("effect")
            if eff:
                eff(self, p, targets or [])
            p.exile.append(card)
            self.log(f"{p.name} lanza la secuela de {card.name}")
            self.sba()
            return True
        if m == "escape":
            others = [x for x in p.graveyard if x is not card]
            need = gp.get("exile_n", 0) or 0
            if len(others) < need:
                return False
            for x in others[:need]:
                p.graveyard.remove(x)
                p.exile.append(x)
            if need:
                self.log(f"{p.name} exilia {need} carta(s) del cementerio (escape)")
        if m == "embalm":
            if cost is not None:
                p.pay(cost)
            p.graveyard.remove(card)
            p.exile.append(card)
            _cards.make_token(self, p, card.name, card.power, card.toughness,
                              kw=tuple(getattr(card, "keywords", ()) or ()),
                              subtypes=tuple(getattr(card, "subtypes", ()) or ()))
            self.log(f"{p.name} crea una ficha de {card.name} (embalm/eternalize)")
            self.sba()
            return True
        is_spell = bool({"instant", "sorcery"} & card.types) and not card.is_creature()
        if not is_spell and after != "hand":
            if cost is not None:
                p.pay(cost)
            _discard_for_play()
            p.graveyard.remove(card)
            perm = self.move_to_battlefield(card, p)
            if perm is None:
                return False        # no era permanente: no se pudo poner en juego
            if m == "unearth":
                perm.summoning_sick = False
                lst = getattr(self, "unearth_eot", None)
                if lst is None:
                    lst = self.unearth_eot = []
                lst.append((p, card))
            self.log(f"{p.name} devuelve {card.name} del cementerio al campo ({m})")
            self.sba()
            return True
        if after == "hand":
            if cost is not None:
                p.pay(cost)
            p.graveyard.remove(card)
            p.hand.append(card)
            self.log(f"{p.name} devuelve {card.name} del cementerio a la mano")
            return True
        # hechizo (flashback / escape / disturb): lanzar por el coste alternativo,
        # luego exiliar. Se reusa cast() sobreescribiendo el coste temporalmente.
        # La carta queda marcada para ir al exilio cuando deje la pila: si cast()
        # pausa por una reacción del humano (ReactionPause), el código de abajo no
        # corre, y antes la carta volvía al cementerio y se relanzaba.
        _discard_for_play()
        p.graveyard.remove(card)
        orig = card.cost
        card._exile_after_cast = after != "graveyard"
        ok = False
        try:
            if cost is not None:
                card.cost = cost
            ok = self.cast(p, card, targets=targets, chosen_modes=chosen_modes)
        except ReactionPause:
            ok = True            # está en la pila esperando la reacción
            raise
        finally:
            card.cost = orig
            if ok is False:      # no se pudo lanzar (p. ej. impuesto stax): no se pierde
                card._exile_after_cast = False
                if card not in p.graveyard:
                    p.graveyard.append(card)
        if ok is False:
            return False
        self.sba()
        return True

    def play_from_exile(self, p: "Player", card: Card,
                        targets=None, chosen_modes=None) -> bool:
        """Juega una carta desde el exilio persistente (foretell / impulse no
        acotado) pagando su coste alternativo `_play_cost`."""
        if card not in p.exile_play:
            return False
        if getattr(card, "_plot_turn", None) == self.turn:
            return False                 # plot: en un turno POSTERIOR
        cost = getattr(card, "_play_cost", None) or card.cost
        if cost is not None and not p.can_pay(cost):
            return False
        if card.is_land():
            if p.lands_played >= self.land_limit(p):
                return False
            p.exile_play.remove(card)
            self.play_land(p, card)
            self.sba()
            return True
        # sacarla del exilio ANTES de lanzar: si cast() pausa por una reacción
        # del humano, antes quedaba a la vez en el exilio y en la pila (duplicada)
        p.exile_play.remove(card)
        orig = card.cost
        ok = False
        try:
            card.cost = cost
            ok = self.cast(p, card, targets=targets, chosen_modes=chosen_modes)
        except ReactionPause:
            ok = True
            raise
        finally:
            card.cost = orig
            if ok is False and card not in p.exile_play:
                p.exile_play.append(card)     # no se lanzó: vuelve al exilio
        self.sba()
        return ok is not False

    def suspend_card(self, p: "Player", card: Card) -> bool:
        """Suspende una carta de la mano: paga el coste de suspend, la exilia con N
        contadores de tiempo. Cada mantenimiento se quita uno; a 0 se lanza gratis."""
        sus = getattr(card, "suspend", None)
        if not sus or card not in p.hand:
            return False
        cost = sus["cost"]
        if cost is not None and not p.can_pay(cost):
            return False
        if cost is not None:
            p.pay(cost)
        p.hand.remove(card)
        self.suspended.append({"card": card, "player": p, "n": sus["n"]})
        self.log(f"{p.name} suspende {card.name} ({sus['n']} contadores)")
        return True

    def _tick_suspended(self, p: "Player"):
        """Quita un contador de tiempo a las cartas suspendidas de `p`; las que llegan
        a 0 se lanzan gratis (con prisa si son criaturas)."""
        ready = []
        for entry in list(self.suspended):
            if entry["player"] is not p:
                continue
            entry["n"] -= 1
            if entry["n"] <= 0:
                self.suspended.remove(entry)
                ready.append(entry["card"])
        for card in ready:
            orig = card.cost
            try:
                card.cost = None                 # se lanza sin pagar su coste
                self.log(f"{p.name} lanza {card.name} desde suspensión (gratis)")
                self.cast(p, card)
            finally:
                card.cost = orig
            # prisa: si entró como criatura, puede atacar ya
            for pm in p.battlefield:
                if pm.card is card:
                    pm.summoning_sick = False

    def _tick_upkeep_counters(self, p: "Player"):
        """Fading, vanishing y cumulative upkeep en el mantenimiento de `p`."""
        for perm in list(p.battlefield):
            if perm not in p.battlefield:
                continue
            # Fading N: quita un contador fade; si no puede (0), se sacrifica.
            if getattr(perm.card, "fading", 0):
                if perm.counters.get("fade", 0) > 0:
                    perm.counters["fade"] -= 1
                else:
                    self.log(f"Fading: {perm.name} se sacrifica")
                    self.to_graveyard(perm, "fading")
                continue
            # Vanishing N: quita un contador de tiempo; al quitar el último, sacrificio.
            if getattr(perm.card, "vanishing", 0):
                if perm.counters.get("time", 0) > 0:
                    perm.counters["time"] -= 1
                    if perm.counters["time"] <= 0:
                        self.log(f"Vanishing: {perm.name} se sacrifica")
                        self.to_graveyard(perm, "vanishing")
                continue
            # Cumulative upkeep: +1 contador de edad; pagar coste × edad o sacrificar.
            cu = getattr(perm.card, "cumulative_upkeep", None)
            if cu:
                perm.counters["age"] = perm.counters.get("age", 0) + 1
                age = perm.counters["age"]
                paid = False
                need = cu["amount"] * age
                if cu.get("kind") == "life":
                    if p.life > need:               # no se suicida
                        p.life -= need
                        paid = True
                else:                               # maná genérico (aprox, sin tapear)
                    paid = p.available_mana() >= need
                if not paid:
                    self.log(f"Cumulative upkeep: {perm.name} se sacrifica")
                    self.to_graveyard(perm, "cumulative upkeep")
        self.sba()

    def cycle_card(self, p: "Player", card: Card) -> bool:
        """Cycling: paga el coste de cycling, descarta esta carta (madness aplica) y
        roba una. Es una habilidad de la MANO."""
        cost = getattr(card, "cycling", None)
        if cost is None or card not in p.hand or not p.can_pay(cost):
            return False
        p.pay(cost)
        p.hand.remove(card)
        self.log(f"{p.name} cicla {card.name}")
        self.discard_card(p, card)     # respeta madness
        p.draw(1, self)
        return True

    def cast_alt_haste(self, p: "Player", card: Card, mode: str) -> bool:
        """Lanza una criatura por un coste alternativo con PRISA. `mode`:
        - 'dash': vuelve a la mano al fin del turno.
        - 'blitz': se sacrifica al fin del turno; su muerte roba una carta.
        (Ninjutsu es aparte: Game.ninjutsu, después de declarar bloqueos.)"""
        attr = {"dash": "dash_cost", "blitz": "blitz_cost"}.get(mode)
        cost = getattr(card, attr, None) if attr else None
        if cost is None or card not in p.hand or not p.can_pay(cost):
            return False
        p.pay(cost)
        p.hand.remove(card)
        self.log(f"{p.name} lanza {card.name} por {mode}")
        perm = self.move_to_battlefield(card, p)
        if perm is None:
            return False
        perm.summoning_sick = False          # prisa
        if mode == "dash":
            self.dash_return.append((p, card))
        elif mode == "blitz":
            perm._blitz = True
            self.blitz_sac.append((p, card))
        self.sba()
        return True

    def cast_evoke(self, p: "Player", card: Card) -> bool:
        """Lanza una criatura por su coste de evoke: entra (dispara su ETB) y se
        sacrifica de inmediato."""
        ec = getattr(card, "evoke_cost", None)
        if ec is None or card not in p.hand or not p.can_pay(ec):
            return False
        p.pay(ec)
        p.hand.remove(card)
        self.log(f"{p.name} lanza {card.name} por evoke")
        perm = self.move_to_battlefield(card, p)   # dispara ETB
        if perm is not None and perm in p.battlefield:
            self.to_graveyard(perm, "evoke")
        self.sba()
        return True

    def cast_adventure(self, p: "Player", card: Card, targets=None) -> bool:
        """Lanza la cara de Aventura de una carta: paga su coste, resuelve el efecto
        y exilia la carta como jugable después (la criatura queda disponible)."""
        adv = getattr(card, "adventure", None)
        if not adv or card not in p.hand:
            return False
        cost = adv["cost"]
        if cost is not None and not p.can_pay(cost):
            return False
        if cost is not None:
            p.pay(cost)
        p.hand.remove(card)
        self.log(f"{p.name} lanza la aventura {adv['label']} de {card.name}")
        eff = adv.get("effect")
        if eff:
            eff(self, p, targets or [])
        # la carta va al exilio, jugable después como criatura por su coste normal
        p.exile_play.append(card)
        self.sba()
        return True

    def foretell_card(self, p: "Player", card: Card) -> bool:
        """Predice (foretell) una carta de la mano: paga {2}, la exilia y queda
        jugable después por su coste de foretell."""
        fc = getattr(card, "foretell", None)
        if fc is None or card not in p.hand or not p.can_pay(Cost(2, ())):
            return False
        p.pay(Cost(2, ()))
        p.hand.remove(card)
        card._play_cost = fc
        p.exile_play.append(card)
        self.log(f"{p.name} predice una carta (foretell)")
        self.sba()
        return True

    # -- caras boca abajo: morph / megamorph / disguise / manifest / cloak -- #
    FACE_DOWN_NAME = "Criatura boca abajo"

    def _drop_proxy(self, px):
        """Quita una sustituta de la lista POR IDENTIDAD (Card es un dataclass:
        dos criaturas boca abajo son 'iguales' campo a campo)."""
        self._proxies = [x for x in self._proxies if x is not px]

    def _face_down_proxy(self, card: Card, owner: "Player", kind: str) -> Card:
        """Carta sustituta de una criatura boca abajo: 2/2 incolora, sin nombre,
        sin habilidades ni tipos de criatura (regla 708). Disguise y cloak además
        tienen ward {2}. La carta real queda en `_real`."""
        px = Card(name=self.FACE_DOWN_NAME, types={"creature"}, cost=Cost(3, ()),
                  power=2, toughness=2, tags={"face_down", f"_px{_next_uid()}"})
        if kind in ("disguise", "cloak"):
            px.keywords = {"ward"}
            px.ward = {"mana": Cost(2, ())}
        px._real = card
        px._fd_kind = kind
        px._owner = owner
        self._proxies.append(px)
        return px

    def face_up_cost(self, perm: Permanent):
        """Coste para dar vuelta un permanente boca abajo, o None si no se puede:
        morph/megamorph/disguise, o su coste de maná si es una carta de criatura
        manifestada/encubierta (manifest/cloak)."""
        px = perm.card
        real = getattr(px, "_real", None)
        if real is None or getattr(px, "_bestow", False):
            return None
        opts = [c for c in (getattr(real, "morph_cost", None),
                            getattr(real, "disguise_cost", None)) if c is not None]
        if (getattr(px, "_fd_kind", "") in ("manifest", "cloak") and real.is_creature()
                and real.cost is not None):
            opts.append(real.cost)
        return min(opts, key=lambda c: c.cmc) if opts else None

    def cast_face_down(self, p: "Player", card: Card) -> bool:
        """Lanza una carta con morph/megamorph/disguise BOCA ABAJO por {3} como una
        criatura 2/2 sin nombre (regla 702.37 / 702.168)."""
        if card not in p.hand:
            return False
        if getattr(card, "disguise_cost", None) is not None:
            kind = "disguise"
        elif getattr(card, "morph_cost", None) is not None:
            kind = "morph"
        else:
            return False
        px = self._face_down_proxy(card, p, kind)
        if not p.can_pay(self.effective_cost(p, px)):
            self._drop_proxy(px)
            return False
        p.hand.remove(card)
        ok = False
        try:
            ok = self.cast(p, px)
        except ReactionPause:
            ok = True
            raise
        finally:
            if ok is False:
                self._drop_proxy(px)
                p.hand.append(card)
        return ok is not False

    def turn_face_up(self, p: "Player", perm: Permanent) -> bool:
        """Acción especial (no usa la pila): pagar el coste y dar vuelta la
        criatura. No 'entra' al campo (sin ETB) pero dispara 'cuando se da vuelta'.
        Megamorph: además recibe un contador +1/+1."""
        if perm.controller is not p or perm not in p.battlefield:
            return False
        cost = self.face_up_cost(perm)
        if cost is None or not p.can_pay(cost):
            return False
        p.pay(cost)
        px = perm.card
        real = px._real
        perm.card = real
        self._drop_proxy(px)
        self.log(f"{p.name} da vuelta {real.name}")
        self.note_ability(real, "se da vuelta", controller=p)
        if getattr(real, "megamorph", False):
            self.add_counters(perm, "+1/+1", 1)
        cb = getattr(real, "on_turn_face_up", None)
        if cb is not None:
            self._run_fx(f"face up {real.name}",
                         lambda: self._run_trigger(lambda g, pm, **kw: cb(g, p, pm),
                                                   perm, {}))
        self.emit("turned_face_up", player=p, perm=perm)
        self.sba()
        return True

    def manifest(self, p: "Player", n: int = 1, kind: str = "manifest",
                 dread: bool = False) -> list:
        """Manifest / cloak: pone la primera carta de tu biblioteca en el campo boca
        abajo como 2/2 (cloak: con ward {2}). Manifest dread: mirá dos, manifestá
        una y la otra va al cementerio. Devuelve los permanentes creados."""
        out = []
        for _ in range(n):
            if not p.library:
                break
            if dread:
                look = p.library[:2]
                del p.library[:2]
                pick = max(look, key=lambda c: (c.is_creature(), c.power + c.toughness))
                for c in look:
                    if c is not pick:
                        p.graveyard.append(c)
                        self.emit("to_graveyard", player=p, card=c)
                card = pick
            else:
                card = p.library.pop(0)
            px = self._face_down_proxy(card, p, kind)
            perm = self.move_to_battlefield(px, p)
            if perm is not None:
                out.append(perm)
            self.log(f"{p.name} {'encubre' if kind == 'cloak' else 'manifiesta'} "
                     f"la carta de arriba de su biblioteca")
        self.sba()
        return out

    # -- bestow: criatura lanzada como Aura ------------------------------- #
    def cast_bestow(self, p: "Player", card: Card, host: Permanent) -> bool:
        """Lanza una criatura con bestow por su coste de bestow como Aura sobre
        `host` (regla 702.103). Mientras está anexada no es criatura: el huésped
        recibe su bono. Si el huésped deja el campo, vuelve a ser criatura."""
        bc = getattr(card, "bestow_cost", None)
        if bc is None or card not in p.hand or host is None:
            return False
        if not (host.is_creature() and host in host.controller.battlefield):
            return False
        if not self.can_target(p, host):
            return False
        px = copy.copy(card)
        px.types = {"enchantment"}
        px.subtypes = {"Aura"}
        px.power = px.toughness = 0
        px.keywords = set()
        px.cost = bc
        px.on_death = None              # una Aura no "muere"
        dp, dt, kws = getattr(card, "bestow_mod", (0, 0, ()))
        px.aura_keywords = set(kws)
        px.static_mod = (lambda src, target, _d=(dp, dt):
                         _d if target is getattr(src, "enchanting", None) else (0, 0))
        px.tags = set(px.tags) | {"bestowed", f"_px{_next_uid()}"}
        px._real = card
        px._bestow = True
        px._owner = p
        real_etb = card.on_etb

        def _attach(game, ctrl, perm, _h=host, _etb=real_etb):
            if _h.is_creature() and _h in _h.controller.battlefield:
                perm.enchanting = _h
                game.log(f"{ctrl.name}: {card.name} se anexa a {_h.name} (bestow)")
            else:
                game._unbestow(perm, "su objetivo ya no está")
            if _etb is not None:
                _etb(game, ctrl, perm)

        px.on_etb = _attach
        self._proxies.append(px)
        p.hand.remove(card)
        ok = False
        try:
            ok = self.cast(p, px, targets=[host])
        except ReactionPause:
            ok = True
            raise
        finally:
            if ok is False:
                self._drop_proxy(px)
                p.hand.append(card)
        return ok is not False

    def _unbestow(self, perm: Permanent, why: str = ""):
        """El Aura de bestow queda sin huésped: deja de ser Aura y es la criatura
        (no entra de nuevo: sin ETB)."""
        px = perm.card
        real = getattr(px, "_real", None)
        if real is None:
            return
        perm.card = real
        perm.enchanting = None
        self._drop_proxy(px)
        self.log(f"{real.name} vuelve a ser una criatura"
                 + (f" ({why})" if why else ""))

    def _normalize_proxies(self) -> bool:
        """Una sustituta (boca abajo / bestow) que salió del campo vuelve a ser la
        carta real en la zona a la que fue (mano, cementerio, exilio, biblioteca)."""
        if not self._proxies:
            return False
        on_bf = {id(pm.card) for pl in self.players for pm in pl.battlefield}
        on_stack = {id(getattr(o, "source", None)) for o in self.stack}
        changed = False
        for px in list(self._proxies):
            if id(px) in on_bf or id(px) in on_stack:
                continue
            real = px._real
            found = False
            for pl in self.players:
                for zname in ("hand", "graveyard", "exile", "library", "command",
                              "exile_play", "impulse"):
                    zone = getattr(pl, zname, None)
                    if not zone:
                        continue
                    for k, c in enumerate(zone):
                        if c is px:
                            zone[k] = real
                            extra = [x for x in (getattr(px, "_extra_cards", None) or [])
                                     if x is not real]
                            if extra:
                                zone[k + 1:k + 1] = extra
                            found = changed = True
                            break
            # si todavía no llegó a ninguna zona (está "en tránsito": un SBA corrió
            # en medio del movimiento), se conserva para normalizarla después
            if found:
                self._drop_proxy(px)
        return changed

    # -- ninjutsu (después de declarar bloqueos) -------------------------- #
    def ninjutsu_options(self, p: "Player", declared: list) -> list:
        """(carta, zona) con ninjutsu que `p` puede usar ahora y los atacantes
        suyos sin bloquear que puede devolver."""
        cards = [(c, "hand") for c in p.hand
                 if getattr(c, "ninjutsu_cost", None) is not None]
        cards += [(c, "command") for c in p.command
                  if getattr(c, "commander_ninjutsu", False)
                  and getattr(c, "ninjutsu_cost", None) is not None]
        return [(c, z) for c, z in cards if p.can_pay(c.ninjutsu_cost)]

    def unblocked_attackers(self, p: "Player", declared: list) -> list:
        return [a for a in declared if a.controller is p and a.attacking is not None
                and not a.blocked_by and a in p.battlefield]

    def ninjutsu(self, p: "Player", card: Card, attacker: Permanent,
                 declared: Optional[list] = None) -> Optional[Permanent]:
        """Ninjutsu (regla 702.49): pagá el coste y devolvé a la mano un atacante
        tuyo NO bloqueado; la carta entra girada y atacando al mismo defensor (no
        fue 'declarada' como atacante: no dispara 'cuando ataca')."""
        cost = getattr(card, "ninjutsu_cost", None)
        from_cmd = card in p.command and getattr(card, "commander_ninjutsu", False)
        if cost is None or not (card in p.hand or from_cmd):
            return None
        if (attacker.controller is not p or attacker.attacking is None
                or attacker.blocked_by or attacker not in p.battlefield):
            return None
        if not p.can_pay(cost):
            return None
        p.pay(cost)
        defender = attacker.attacking
        # el atacante vuelve a la mano de su dueño
        p.battlefield.remove(attacker)
        attacker.attacking = None
        if attacker.card.on_leave:
            self._run_fx(f"on_leave {attacker.name}",
                         lambda: attacker.card.on_leave(self, p, attacker))
        if declared is not None and attacker in declared:
            declared.remove(attacker)
        if not attacker.is_token:
            back = getattr(attacker.card, "_real", None) or attacker.card
            if getattr(attacker.card, "_real", None) is not None:
                self._drop_proxy(attacker.card)
            owner = self.commander_owner(back)
            (owner.command if owner is not None else p.hand).append(back)
        if from_cmd:
            p.command.remove(card)
        else:
            p.hand.remove(card)
        self.log(f"{p.name} usa ninjutsu: {attacker.name} vuelve y entra {card.name} atacando")
        perm = self.move_to_battlefield(card, p)
        if perm is None:
            return None
        perm.tapped = True
        perm.attacking = defender
        if declared is not None:
            declared.append(perm)
        self.sba()
        return perm

    def _after_blocks(self, declared: list):
        """Ventana tras declarar bloqueos: los bots usan ninjutsu y dan vuelta
        criaturas boca abajo (el humano lo hace desde su ventana de combate)."""
        for a in declared:                       # provoke: bloqueo forzado
            for pl in self.players:
                for pm in pl.battlefield:
                    if getattr(pm, "_must_block", None) is a:
                        pm._must_block = None
                        if not pm.blocking and not pm.tapped and pm.is_creature() \
                                and a not in pm.blocking:
                            self._apply_block_pairs([a], [(a, pm)])
        human = getattr(self, "interactive_human", None)
        ap = self.players[self.active_index] if self.players else None
        order = ([ap] if ap else []) + [pl for pl in self.players if pl is not ap]
        for pl in order:
            if pl is None or pl.lost or pl is human:
                continue
            pol = pl.policy
            if pol is not None and hasattr(pol, "after_blocks"):
                try:
                    pol.after_blocks(self, pl, declared)
                except Exception:  # noqa: BLE001
                    pass

    # -- lanzamientos alternativos (batch 2) ------------------------------ #
    def _cast_with(self, p: "Player", card: Card, cost, targets=None, chosen_modes=None,
                   remove_from=None):
        """Lanza `card` pagando `cost` en vez de su coste (restaura el coste
        impreso). `remove_from`: zona de la que sale (si no es la mano)."""
        if remove_from is not None and card in remove_from:
            remove_from.remove(card)
        orig = card.cost
        ok = False
        try:
            card.cost = cost
            ok = self.cast(p, card, targets=targets, chosen_modes=chosen_modes)
        except ReactionPause:
            ok = True
            raise
        finally:
            card.cost = orig
            if ok is False and remove_from is not None and card not in remove_from:
                remove_from.append(card)
        return ok is not False

    def _auto_targets(self, p, card):
        pol = p.policy
        if getattr(card, "target_spec", None) and pol is not None \
                and hasattr(pol, "choose_targets"):
            try:
                return pol.choose_targets(self, p, card)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _tick_rebound(self, p: "Player"):
        for entry in list(self.rebound):
            owner, card = entry
            if owner is not p:
                continue
            self.rebound.remove(entry)
            if card not in p.exile:
                continue
            p.exile.remove(card)
            self.log(f"{p.name} relanza {card.name} (rebound, gratis)")
            card._cast_from_hand = False
            card._exile_after_cast = False
            ok = self._cast_with(p, card, None, targets=self._auto_targets(p, card))
            if not ok and card not in p.graveyard:
                p.graveyard.append(card)

    def overload_targets(self, p: "Player", card: Card) -> list:
        """Todo lo que podría ser objetivo del hechizo (overload no apunta)."""
        pred = self._SPEC_OK.get(getattr(card, "target_spec", None) or "")
        if pred is None:
            return []
        if card.target_spec == "opp_player":
            return [o for o in self.opponents(p)]
        pls = self.opponents(p) if getattr(card, "overload_opp", False) else self.players
        return [pm for pl in pls for pm in pl.battlefield if pred(pm)]

    def cast_overload(self, p: "Player", card: Card) -> bool:
        """Overload: pagá el coste de sobrecarga; 'target' pasa a ser 'each' (el
        efecto se aplica a todo lo que podría ser objetivo)."""
        oc = getattr(card, "overload_cost", None)
        if oc is None or card not in p.hand or not p.can_pay(oc):
            return False
        tgs = self.overload_targets(p, card)
        card._overloaded = True
        self.log(f"{p.name} lanza {card.name} con sobrecarga")
        ok = self._cast_with(p, card, oc, targets=tgs)
        card._overloaded = False
        return ok

    def try_miracle(self, p: "Player", card: Card):
        """Miracle: si es la primera carta que robás en el turno, podés lanzarla
        por su coste de milagro (humano elige; bots si pueden pagarla)."""
        mc = getattr(card, "miracle_cost", None)
        if mc is None or card not in p.hand or not p.can_pay(mc):
            return

        def _do(g=self, c=p):
            if card in c.hand and c.can_pay(mc):
                g.log(f"{c.name} revela {card.name}: ¡milagro!")
                g._cast_with(c, card, mc, targets=g._auto_targets(c, card))
        if p is getattr(self, "interactive_human", None):
            self.may(p, f"Milagro: ¿lanzar {card.name} por {_cost_txt(mc)}?",
                     lambda g, c: _do())
            return
        _do()

    def plot_card(self, p: "Player", card: Card) -> bool:
        """Plot: pagá el coste de plot y exiliala; en un turno POSTERIOR la podés
        lanzar gratis (a velocidad de conjuro)."""
        pc = getattr(card, "plot_cost", None)
        if pc is None or card not in p.hand or not p.can_pay(pc):
            return False
        p.pay(pc)
        p.hand.remove(card)
        card._play_cost = Cost(0, ())
        card._plot_turn = self.turn
        p.exile_play.append(card)
        self.log(f"{p.name} planea (plot) {card.name}")
        return True

    def cast_warp(self, p: "Player", card: Card, targets=None) -> bool:
        """Warp: lanzala por su coste de warp; al final del turno se exilia y la
        podés volver a lanzar después desde el exilio."""
        wc = getattr(card, "warp_cost", None)
        if wc is None or card not in p.hand or not p.can_pay(wc):
            return False
        ok = self._cast_with(p, card, wc, targets=targets)
        if ok:
            self.warped_turn = self.turn
            if card.is_creature() or {"artifact", "enchantment"} & card.types:
                self.warp_eot.append((p, card))
        return ok

    def cast_prototype(self, p: "Player", card: Card) -> bool:
        """Prototype: lanzala con el coste y la F/R menores (sustituta)."""
        pr = getattr(card, "prototype", None)
        if not pr or card not in p.hand or not p.can_pay(pr["cost"]):
            return False
        px = copy.copy(card)
        px.cost = pr["cost"]
        px.power, px.toughness = pr["p"], pr["t"]
        px.tags = set(px.tags) | {"prototype", f"_px{_next_uid()}"}
        px._real = card
        px._owner = p
        self._proxies.append(px)
        p.hand.remove(card)
        ok = False
        try:
            ok = self.cast(p, px)
        except ReactionPause:
            ok = True
            raise
        finally:
            if ok is False:
                self._drop_proxy(px)
                p.hand.append(card)
        return ok is not False

    def emerge_option(self, p: "Player", card: Card):
        """(víctima, coste) para Emerge: sacrificar una criatura y restar su valor de
        maná del coste de emerge. La IA elige la de mejor descuento entre las de
        menor valor (nunca el comandante)."""
        ec = getattr(card, "emerge_cost", None)
        if ec is None or card not in p.hand:
            return None
        best = None
        for pm in p.creatures():
            if p.is_commander(pm.card) or pm.is_token:
                continue
            red = _cmc_card(getattr(pm.card, "_real", None) or pm.card)
            cost = Cost(generic=max(0, ec.generic - red), pips=ec.pips)
            if not p.can_pay(cost):
                continue
            key = (pm.power + pm.toughness - red, cost.cmc)
            if best is None or key < best[0]:
                best = (key, pm, cost)
        return (best[1], best[2]) if best else None

    def cast_emerge(self, p: "Player", card: Card, victim=None) -> bool:
        opt = self.emerge_option(p, card)
        if opt is None:
            return False
        vic, cost = opt
        if victim is not None and victim in p.battlefield:
            red = _cmc_card(getattr(victim.card, "_real", None) or victim.card)
            vic, cost = victim, Cost(generic=max(0, card.emerge_cost.generic - red),
                                     pips=card.emerge_cost.pips)
        self.to_graveyard(vic, "emerge")
        self.log(f"{p.name} sacrifica {vic.name} (emerge)")
        return self._cast_with(p, card, cost)

    def exploit(self, ctrl: "Player", perm: Permanent, effect):
        """Exploit: al entrar, podés sacrificar una criatura; si lo hacés, su
        efecto. Bots: una ficha o una criatura chica (o ella misma si no hay
        otra y el efecto vale más). Humano: elige."""
        pool = [pm for pm in ctrl.creatures() if not ctrl.is_commander(pm.card)]

        def _sac(victim, g=self):
            if victim is None or victim not in victim.controller.battlefield:
                return
            g.to_graveyard(victim, "exploit")
            g.log(f"{ctrl.name} explota (exploit) {victim.name}")
            if effect is not None:
                g._run_trigger(lambda gg, pm, **kw: effect(gg, ctrl, pm), perm, {},
                               subject=victim)
            g.sba()
        if ctrl is getattr(self, "interactive_human", None):
            opts = [{"i": 0, "name": "No sacrificar"}] + [
                {"i": k + 1, "name": f"{pm.name} {pm.power}/{pm.toughness}"}
                for k, pm in enumerate(pool)]
            self.pending_choice = {
                "kind": "may", "prompt": "Exploit: ¿sacrificar una criatura?",
                "options": opts, "allow_none": False,
                "_apply": lambda idx, _p=pool: _sac(_p[idx - 1]) if idx else None,
            }
            return
        cheap = [pm for pm in pool if pm is not perm
                 and (pm.is_token or pm.power + pm.toughness <= 3)]
        if cheap:
            _sac(min(cheap, key=lambda pm: (not pm.is_token, pm.power + pm.toughness)))

    # -- batch 3: mutate / splice / saddle / station / phasing / champion -- #
    def _give_gift(self, p: "Player", card: Card):
        """Gift: el rival menos amenazante recibe el regalo prometido."""
        opps = self.opponents(p)
        if not opps:
            return
        o = min(opps, key=lambda x: (sum(pm.power for pm in x.creatures()), x.life))
        k = card.gift_kind
        import cards as _cards
        if k == "a card":
            o.draw(1, self)
        elif k in ("a food", "a treasure", "a clue"):
            _cards.make_resource_token(self, o, k.split()[-1])
        elif k == "a tapped fish":
            t = _cards.make_token(self, o, "Fish", 1, 1, subtypes=("Fish",))
            if t is not None:
                t.tapped = True
        elif k == "an octopus":
            _cards.make_token(self, o, "Octopus", 8, 8, subtypes=("Octopus",))
        self.log(f"{p.name} regala {k} a {o.name} (gift)")

    def _check_ascend(self, p: "Player", force=False):
        """Ascend: con 10+ permanentes obtenés la bendición de la ciudad (para
        siempre)."""
        if p.citys_blessing:
            return
        if force or any(getattr(pm.card, "ascend", False) for pm in p.battlefield):
            if len(p.battlefield) >= 10:
                p.citys_blessing = True
                self.log(f"{p.name} obtiene la bendición de la ciudad")

    # -- batch 4B: impending / MTMTE / provoke / haunt / forecast / soulbond -- #
    def cast_impending(self, p: "Player", card: Card) -> bool:
        ic = getattr(card, "impending_cost", None)
        if ic is None or card not in p.hand or not p.can_pay(ic):
            return False
        card._impending_cast = True
        ok = self._cast_with(p, card, ic)
        if not ok:
            card._impending_cast = False
        return ok

    def cast_converted(self, p: "Player", card: Card) -> bool:
        """More Than Meets the Eye: lanzala convertida (entra por su otra cara)."""
        mc = getattr(card, "mtmte_cost", None)
        if mc is None or card not in p.hand or not p.can_pay(mc):
            return False
        card._enter_converted = True
        ok = self._cast_with(p, card, mc)
        if not ok:
            card._enter_converted = False
        return ok

    def _forecast(self, p: "Player"):
        """Forecast: en tu mantenimiento, mostrás la carta y pagás su habilidad
        (los bots si la pueden pagar)."""
        if p is getattr(self, "interactive_human", None):
            return
        for c in list(p.hand):
            fc = getattr(c, "forecast", None)
            if fc and p.can_pay(fc["cost"]):
                p.pay(fc["cost"])
                self.log(f"{p.name} pronostica con {c.name}")
                fc["effect"](self, p)

    def _soulbond_pair(self, perm: Permanent):
        """Soulbond: empareja a la que entra con otra criatura tuya sin pareja."""
        ctrl = perm.controller
        if getattr(perm, "_paired", None) is not None or not perm.is_creature():
            return
        mates = [pm for pm in ctrl.creatures() if pm is not perm
                 and getattr(pm, "_paired", None) is None
                 and (getattr(perm.card, "soulbond", False) or getattr(pm.card, "soulbond", False))]
        if not mates:
            return
        mate = max(mates, key=lambda x: x.power + x.toughness)
        perm._paired, mate._paired = mate, perm
        self.log(f"{perm.name} se empareja con {mate.name} (soulbond)")

    def _provoke(self, attacker: Permanent, defender):
        dp = defender if isinstance(defender, Player) else defender.controller
        pool = [pm for pm in dp.creatures() if not pm.cant_block]
        if not pool:
            return
        kill = [pm for pm in pool if pm.toughness <= attacker.power]
        tgt = max(kill or pool, key=lambda x: x.power + x.toughness)
        tgt.tapped = False
        tgt._must_block = attacker
        self.log(f"{attacker.name} provoca a {tgt.name}")

    def _haunt(self, owner: "Player", card: Card, effect):
        """Haunt: la carta se exilia 'rondando' una criatura; cuando esa muere, se
        repite su efecto."""
        pool = [pm for o in self.opponents(owner) for pm in o.creatures()] or \
            [pm for pm in owner.creatures()]
        if not pool or card not in owner.graveyard:
            return
        tgt = max(pool, key=lambda x: x.power + x.toughness)
        owner.graveyard.remove(card)
        owner.exile.append(card)
        if getattr(tgt, "_haunted_by", None) is None:
            tgt._haunted_by = []
        tgt._haunted_by.append((owner, effect))
        self.log(f"{card.name} ronda a {tgt.name} (haunt)")

    # -- batch 4: roles / discover / clash ----------------------------------- #
    _ROLES = {
        "cursed": {"pt_set": (1, 1)},
        "monster": {"dp": 1, "dt": 1, "kw": {"trample"}},
        "royal": {"dp": 1, "dt": 1, "kw": {"ward"}},
        "sorcerer": {"dp": 1, "dt": 1},
        "virtuous": {"dp": 1, "dt": 1},
        "wicked": {"dp": 1, "dt": 1},
        "young hero": {"dp": 1, "dt": 1},
        "huntsman": {"dp": 1, "dt": 1},
    }

    def create_role(self, ctrl: "Player", host: Permanent, kind: str):
        """Ficha de Rol: Aura que da su bono al huésped. Un mismo jugador solo
        puede tener un Rol en cada criatura (el nuevo reemplaza al anterior)."""
        if host is None or host not in host.controller.battlefield:
            return None
        spec = self._ROLES.get(kind.lower(), {"dp": 1, "dt": 1})
        for pm in list(ctrl.battlefield):
            if pm.enchanting is host and getattr(pm.card, "_role", False):
                self.to_graveyard(pm, "rol reemplazado")
        dp, dt = spec.get("dp", 0), spec.get("dt", 0)
        rc = Card(name=f"{kind.title()} Role", types={"enchantment"}, subtypes={"Aura", "Role"},
                  cost=None)
        rc._role = True
        rc.aura_keywords = set(spec.get("kw", set()))
        if spec.get("pt_set"):
            rc.aura_pt_set = spec["pt_set"]
        if "ward" in rc.aura_keywords:
            host.card.ward = getattr(host.card, "ward", None) or {"mana": Cost(1, ())}
        rc.static_mod = (lambda src, target, _d=(dp, dt):
                         _d if target is getattr(src, "enchanting", None) else (0, 0))
        rp = self.move_to_battlefield(rc, ctrl, is_token=True)
        if rp is not None:
            rp.enchanting = host
            self.log(f"{ctrl.name}: Rol {kind} sobre {host.name}")
        return rp

    def discover(self, p: "Player", n: int):
        """Discover N: exiliá de arriba hasta una no-tierra de valor N o menos;
        lanzala gratis (o a la mano). El resto, al fondo."""
        revealed, hit = [], None
        while p.library:
            c = p.library.pop()
            if not c.is_land() and (c.cost.cmc if c.cost else 0) <= n:
                hit = c
                break
            revealed.append(c)
        self.rng.shuffle(revealed)
        p.library[0:0] = revealed
        if hit is None:
            return
        self.log(f"{p.name} descubre {hit.name}")
        if hit.is_land() or (getattr(hit, "target_spec", None) and not self._auto_targets(p, hit)):
            p.hand.append(hit)
            return
        p.hand.append(hit)
        self._cast_with(p, hit, None, targets=self._auto_targets(p, hit))

    def clash(self, p: "Player") -> bool:
        """Clash: vos y un rival revelan la de arriba; gana el mayor valor de maná
        (empate: nadie). Cada uno puede mandar la suya al fondo."""
        opps = self.opponents(p)
        if not opps or not p.library:
            return False
        o = opps[0]
        mine = p.library[-1]
        theirs = o.library[-1] if o.library else None
        mv = lambda c: c.cost.cmc if (c is not None and c.cost is not None) else 0  # noqa: E731
        win = mv(mine) > mv(theirs)
        for pl, c in ((p, mine), (o, theirs)):
            if c is not None and c.is_land() and sum(
                    1 for pm in pl.battlefield if pm.card.is_land()) >= 5:
                pl.library.remove(c)
                pl.library.insert(0, c)
        self.log(f"{p.name} hace clash con {o.name}: {'gana' if win else 'no gana'}")
        return win

    # -- acciones clave del batch 3 ---------------------------------------- #
    # Dungeons simplificados: cada sala aplica un efecto típico de su recorrido.
    _DUNGEON_ROOMS = {
        "lost mine": ["scry", "goblin", "drain", "draw"],
        "undercity": ["land", "skeleton", "scry2", "drain", "draw2"],
    }

    def venture(self, p: "Player", undercity: bool = False):
        """Venture into the dungeon (o Undercity con la iniciativa): avanza a la
        sala siguiente y aplica su efecto; al terminar, completás el dungeon."""
        import cards as _cards
        if p.dungeon_room == 0:
            p.dungeon_kind = "undercity" if undercity else "lost mine"
        rooms = self._DUNGEON_ROOMS[p.dungeon_kind]
        p.dungeon_room += 1
        eff = rooms[p.dungeon_room - 1]
        if eff == "scry" or eff == "scry2":
            n = 1 if eff == "scry" else 2
            top = p.library[-n:]
            lands = sum(1 for pm in p.battlefield if pm.card.is_land())
            for c in list(top):
                if c.is_land() and lands >= 5:
                    p.library.remove(c)
                    p.library.insert(0, c)
        elif eff == "goblin":
            _cards.make_token(self, p, "Goblin", 1, 1, subtypes=("Goblin",))
        elif eff == "skeleton":
            _cards.make_token(self, p, "Skeleton", 4, 1, kw=("menace",), subtypes=("Skeleton",))
        elif eff == "drain":
            for o in self.opponents(p):
                o.life -= 1
            self.gain_life(p, 1)
        elif eff in ("draw", "draw2"):
            p.draw(1 if eff == "draw" else 2, self)
        elif eff == "land":
            for c in list(reversed(p.library)):
                if c.is_land() and "basic" in c.supertypes:
                    p.library.remove(c)
                    p.hand.append(c)
                    break
        self.log(f"{p.name} se aventura en el dungeon (sala {p.dungeon_room}/{len(rooms)})")
        if p.dungeon_room >= len(rooms):
            p.dungeon_room = 0
            p.dungeons_completed += 1
            self.log(f"{p.name} completa el dungeon")
        self.sba()

    def take_initiative(self, p: "Player"):
        for pl in self.players:
            pl.initiative = False
        p.initiative = True
        self.log(f"{p.name} toma la iniciativa")
        self.venture(p, undercity=True)

    def cast_mutate(self, p: "Player", card: Card, host: Permanent) -> bool:
        """Mutate: lanzala por su coste de mutar sobre una criatura NO Humana tuya.
        Al resolver se fusionan; si el objetivo ya no es legal, entra sola."""
        mc = getattr(card, "mutate_cost", None)
        if mc is None or card not in p.hand or host is None or not p.can_pay(mc):
            return False
        if host.controller is not p or host.has_subtype("human") or not host.is_creature():
            return False
        px = copy.copy(card)
        px.cost = mc
        px.tags = set(px.tags) | {"mutating", f"_px{_next_uid()}"}
        px._real = card
        px._owner = p
        px._mutate_onto = host
        self._proxies.append(px)
        p.hand.remove(card)
        ok = False
        try:
            ok = self.cast(p, px, targets=[host])
        except ReactionPause:
            ok = True
            raise
        finally:
            if ok is False:
                self._drop_proxy(px)
                p.hand.append(card)
        return ok is not False

    def _do_mutate(self, card: Card, host: Permanent, player: "Player"):
        """Fusiona `card` con `host`: arriba queda la de mayor cuerpo (la IA y el
        humano ponen arriba la mejor); la criatura tiene las características de
        la de arriba y TODAS las habilidades. No 'entra' (sin ETB ni mareo nuevo)."""
        stack = list(getattr(host, "_mutate_stack", None) or [])
        if not stack:
            base = getattr(host.card, "_real", None) if getattr(host.card, "_mutated", False) \
                else host.card
            stack = [base]
        on_top = (card.power + card.toughness) >= (stack[0].power + stack[0].toughness)
        stack = [card] + stack if on_top else stack + [card]
        host._mutate_stack = stack
        top = stack[0]
        merged = copy.copy(top)
        merged.tags = set(top.tags) | {"mutated", f"_px{_next_uid()}"}
        kws, acts, trig = set(), [], {}
        for c in stack:
            kws |= set(c.keywords)
            acts.extend(c.activated_abilities or ())
            for ev, cb in (c.triggers or {}).items():
                if ev in trig:
                    prev = trig[ev]
                    trig[ev] = (lambda g, pm, *a, _p=prev, _c=cb, **kw:
                                (_p(g, pm, *a, **kw), _c(g, pm, *a, **kw)))
                else:
                    trig[ev] = cb
        merged.keywords = kws
        merged.activated_abilities = tuple(acts)
        merged.triggers = trig
        merged.on_etb = None
        merged._mutated = True
        # cartas reales: la de arriba en _real, el resto en _extra_cards (las fichas
        # no son cartas y desaparecen al salir)
        real_cards = [c for c in stack if not getattr(c, "_is_token_card", False)]
        merged._real = top
        merged._extra_cards = [c for c in real_cards if c is not top]
        merged._owner = player
        old = host.card
        if getattr(old, "_mutated", False):
            self._drop_proxy(old)
        host.card = merged
        self._proxies.append(merged)
        self.log(f"{player.name} muta {card.name} {'sobre' if on_top else 'bajo'} "
                 f"{host.name}")
        for c in stack:
            eff = getattr(c, "on_mutate", None)
            if eff is not None:
                self._run_fx(f"mutate {c.name}",
                             lambda _e=eff: self._run_trigger(
                                 lambda g, pm, **kw: _e(g, player, pm), host, {}))
        self.sba()
        return host

    def phase_out(self, perm: Permanent):
        """Fuera de fase: se trata como si no existiera hasta el próximo enderezar
        de su controlador (con lo que tenga anexado)."""
        ctrl = perm.controller
        if perm not in ctrl.battlefield:
            return
        group = [perm] + [pm for pm in self.all_permanents() if pm.enchanting is perm]
        for pm in group:
            if pm in pm.controller.battlefield:
                pm.controller.battlefield.remove(pm)
                pm.attacking = None
                pm.blocking, pm.blocked_by = [], []
                pm._phased_now = True
                self.phased.append((pm, ctrl))
        self.log(f"{perm.name} queda fuera de fase")

    def _phase_step(self, p: "Player"):
        back = [(pm, c) for pm, c in self.phased if c is p]
        self.phased = [(pm, c) for pm, c in self.phased if c is not p]
        for pm, c in back:
            pm.controller.battlefield.append(pm)
            pm._phased_now = False
        if back:
            self.log(f"{p.name}: {len(back)} permanente(s) vuelven a estar en fase")
        returned = {id(pm) for pm, _c in back}
        for pm in list(p.battlefield):
            if pm.has("phasing") and id(pm) not in returned:
                self.phase_out(pm)

    def saddle(self, p: "Player", perm: Permanent, n: int) -> bool:
        """Saddle N: girá otras criaturas tuyas con fuerza total N o más; la Montura
        queda ensillada este turno."""
        if getattr(perm, "saddled_turn", None) == self.turn:
            return False
        avail = sorted((pm for pm in p.creatures() if pm is not perm and not pm.tapped
                        and pm.attacking is None),
                       key=lambda c: (not c.summoning_sick, c.power))
        used, total = [], 0
        for c in avail:
            if total >= n:
                break
            used.append(c)
            total += max(0, c.power)
        if total < n:
            return False
        for c in used:
            c.tapped = True
        perm.saddled_turn = self.turn
        perm.saddled_by = used
        self.log(f"{p.name} ensilla a {perm.name}")
        return True

    def station(self, p: "Player", perm: Permanent) -> bool:
        """Station: girá otra criatura tuya: pone contadores de carga iguales a su
        fuerza en la nave (Spacecraft)."""
        avail = [pm for pm in p.creatures() if pm is not perm and not pm.tapped
                 and pm.attacking is None and pm.power > 0]
        if not avail:
            return False
        c = max(avail, key=lambda x: (x.summoning_sick, x.power))
        c.tapped = True
        self.add_counters(perm, "charge", c.power)
        self.log(f"{p.name} carga {perm.name} con {c.name} (+{c.power})")
        return True

    def champion_etb(self, ctrl: "Player", perm: Permanent, kind: str):
        """Champion: exiliá otra criatura/permanente del tipo; si no, se sacrifica.
        Al dejar el campo, la exiliada vuelve."""
        k = kind.lower()

        def ok(pm):
            if pm is perm:
                return False
            if k in ("creature", "permanent"):
                return pm.is_creature() if k == "creature" else True
            return pm.has_subtype(k)
        pool = [pm for pm in ctrl.battlefield if ok(pm) and not ctrl.is_commander(pm.card)]
        if not pool:
            self.log(f"{perm.name}: no hay {kind} para campeonar — se sacrifica")
            self.to_graveyard(perm, "champion")
            return
        victim = min(pool, key=lambda pm: (not pm.is_token, pm.power + pm.toughness))
        ctrl.battlefield.remove(victim)
        if not victim.is_token:
            card = getattr(victim.card, "_real", None) or victim.card
            ctrl.exile.append(card)
            perm._championed = (card, ctrl)
        self.log(f"{perm.name} campeona a {victim.name} (exiliada)")

    def companion_to_hand(self, p: "Player") -> bool:
        c = getattr(p, "companion", None)
        if c is None or not p.can_pay(Cost(3, ())):
            return False
        p.pay(Cost(3, ()))
        p.hand.append(c)
        p.companion = None
        self.log(f"{p.name} pone a su compañero {c.name} en la mano")
        return True

    def animate_land(self, p: "Player", n: int, haste: bool = True, earthbend=False):
        """Awaken / earthbend: una tierra tuya pasa a ser criatura 0/0 con prisa y N
        contadores +1/+1 (la IA elige una que no sea la última de su color)."""
        lands = [pm for pm in p.battlefield if pm.card.is_land()
                 and not getattr(pm, "animated", False)]
        if not lands:
            return None
        pm = max(lands, key=lambda x: (x.tapped, "basic" in x.card.supertypes))
        pm.animated = True
        pm.set_base_pt = (0, 0)
        if haste:
            pm.perma_keywords.add("haste")
        pm.added_subtypes.add("Elemental")
        if earthbend:
            pm._earthbent = True
        self.add_counters(pm, "+1/+1", n)
        self.log(f"{p.name}: {pm.name} se vuelve una criatura {n}/{n}")
        return pm

    def cast_alt_effect(self, p: "Player", card: Card, cost, flag: str,
                        targets=None) -> bool:
        """Lanzamiento con coste y efecto alternativos (cleave / awaken)."""
        if card not in p.hand or cost is None or not p.can_pay(cost):
            return False
        setattr(card, flag, True)
        ok = self._cast_with(p, card, cost, targets=targets)
        if not ok:
            setattr(card, flag, False)
        return ok

    def reinforce(self, p: "Player", card: Card, target: Permanent = None) -> bool:
        rf = getattr(card, "reinforce", None)
        if not rf or card not in p.hand or not p.can_pay(rf["cost"]):
            return False
        pool = [pm for pm in p.creatures()]
        if target is None or target not in pool:
            if not pool:
                return False
            target = max(pool, key=lambda pm: pm.power + pm.toughness)
        p.pay(rf["cost"])
        p.hand.remove(card)
        self.discard_card(p, card)
        self.add_counters(target, "+1/+1", rf["n"])
        self.log(f"{p.name} refuerza a {target.name} (+{rf['n']} contadores)")
        return True

    def transmute(self, p: "Player", card: Card) -> bool:
        tc = getattr(card, "transmute_cost", None)
        if tc is None or card not in p.hand or not p.can_pay(tc):
            return False
        mv = _cmc_card(card)
        pool = [c for c in p.library if _cmc_card(c) == mv]
        p.pay(tc)
        p.hand.remove(card)
        self.discard_card(p, card)
        if pool:
            pick = max(pool, key=lambda c: (not c.is_land(), c.power + c.toughness))
            p.library.remove(pick)
            p.hand.append(pick)
            self.rng.shuffle(p.library)
            self.log(f"{p.name} transmuta: busca {pick.name}")
        return True

    def cast_web_slinging(self, p: "Player", card: Card, back: Permanent = None) -> bool:
        wc = getattr(card, "web_slinging_cost", None)
        if wc is None or card not in p.hand or not p.can_pay(wc):
            return False
        pool = [pm for pm in p.creatures() if pm.tapped and not p.is_commander(pm.card)]
        if back is None or back not in pool:
            if not pool:
                return False
            back = min(pool, key=lambda pm: pm.power + pm.toughness)
        p.battlefield.remove(back)
        if not back.is_token:
            p.hand.append(getattr(back.card, "_real", None) or back.card)
        self.log(f"{p.name} devuelve {back.name} a la mano (web-slinging)")
        return self._cast_with(p, card, wc)

    def activate_gy_ability(self, p: "Player", card: Card, index: int = 0) -> bool:
        """Activa una habilidad de una carta EN EL CEMENTERIO (`gy_abilities`)."""
        abs_ = getattr(card, "gy_abilities", ()) or ()
        if card not in p.graveyard or not (0 <= index < len(abs_)):
            return False
        ab = abs_[index]
        cost = ab.get("cost")
        if cost is not None and not p.can_pay(cost):
            return False
        if cost is not None:
            p.pay(cost)
        if ab.get("exile_self") and card in p.graveyard:
            p.graveyard.remove(card)
            p.exile.append(card)
        self.note_ability(card, "habilidad desde el cementerio", controller=p)
        eff = ab.get("effect")
        if eff:
            eff(self, p, card)
        self.log(f"{p.name} activa {card.name} desde el cementerio")
        self.sba()
        return True

    # -- combate ---------------------------------------------------------- #
    def _def_player(self, attacker: Permanent) -> "Player":
        """Jugador que defiende contra `attacker`: el jugador atacado, o el
        controlador del planeswalker atacado."""
        d = attacker.attacking
        return d if isinstance(d, Player) else d.controller

    def combat(self, p: "Player"):
        self._begin_combat(p)
        if not self.opponents(p):
            return
        attackers = p.policy.declare_attackers(self, p) if p.policy else []
        self._resolve_combat(p, attackers)

    def _begin_combat(self, p: "Player"):
        self.emit("begin_combat", player=p)
        self.resolve_stack()

    def _declare_attackers(self, p: "Player", attackers: list) -> list:
        """Marca los atacantes válidos, los tapea (sin vigilancia) y dispara
        'attacks'. Devuelve la lista de Permanent que efectivamente atacan."""
        declared = []
        for perm, defender in attackers:
            if not perm.can_attack():
                continue
            if isinstance(defender, Player):
                if defender.lost:
                    continue
            else:  # planeswalker
                if (defender.controller.lost
                        or defender not in defender.controller.battlefield):
                    continue
            perm.attacking = defender
            if not perm.has("vigilance"):
                perm.tapped = True
                self._push_self_trigger(perm, "becomes_tapped", "se gira")
            declared.append(perm)
            if getattr(perm.card, "provoke", False):
                self._provoke(perm, defender)
            p.attacked_turn = self.turn          # raid: atacaste este turno
            perm.attacked_turn = self.turn       # boast: esta criatura atacó
            # Enlist: girá una criatura que no ataca (sin mareo) y sumá su fuerza
            if getattr(perm.card, "enlist", False):
                atk_now = {id(x) for x, _d in attackers}
                helpers = [pm for pm in p.creatures() if id(pm) not in atk_now
                           and pm is not perm and not pm.tapped and not pm.summoning_sick
                           and pm.power > 0]
                if helpers:
                    h = max(helpers, key=lambda x: x.power)
                    h.tapped = True
                    perm.temp_pt[0] += h.power
                    self.log(f"{perm.name} recluta a {h.name} (enlist, +{h.power})")
            # Exert: "podés agotarla al atacar" -> no se endereza en tu próximo
            # enderezar y dispara su bono. Bots y humano la agotan (auto).
            if getattr(perm.card, "exert_effect", None) is not None and \
                    not getattr(perm, "exerted", False):
                perm.exerted = True
                self.log(f"{p.name} agota (exert) a {perm.name}")
                ex = perm.card.exert_effect
                self._run_fx(f"exert {perm.name}",
                             lambda _e=ex, _pm=perm: self._run_trigger(
                                 lambda g, pm, **kw: _e(g, p, pm), _pm, {}, subject=_pm))
            # registrar el ataque para que se vea en el relato/resumen (antes no
            # quedaba nada, y los ataques a un planeswalker parecían daño de la nada)
            if isinstance(defender, Player):
                self.log(f"{p.name}: {perm.name} ({perm.power}) ataca a {defender.name}")
            else:
                self.log(f"{p.name}: {perm.name} ({perm.power}) ataca al "
                         f"planeswalker {defender.name} de {defender.controller.name}")
            cb = perm.card.triggers.get("attacks")
            if cb:
                self.stack.append(StackObject(
                    p, (lambda g, _cb=cb, _perm=perm, _d=defender:
                        g._run_trigger(_cb, _perm, {"defender": _d}, subject=_perm)),
                    source=perm, label=f"attacks:{perm.name}"))
            # disparos "whenever EQUIPPED creature attacks": viven en el equipo/aura
            # anexado al atacante, no en la criatura. Se disparan con el equipo.
            for src in self.all_permanents():
                if getattr(src, "enchanting", None) is perm:
                    ecb = src.card.triggers.get("attacks")
                    if ecb:
                        self.stack.append(StackObject(
                            p, (lambda g, _cb=ecb, _s=src, _d=defender, _a=perm:
                                g._run_trigger(_cb, _s, {"defender": _d}, subject=_a)),
                            source=src, label=f"attacks:{src.name}"))
            # disparos GLOBALES "whenever a creature you control attacks" (Hellrider…):
            # cuentan CADA criatura tuya que ataca, incluida la fuente si ella misma
            # ataca. (La clave es distinta de "attacks", así que no se duplica.)
            for src in p.battlefield:
                gcb = src.card.triggers.get("creature_attacks")
                if gcb:
                    self.stack.append(StackObject(
                        p, (lambda g, _cb=gcb, _s=src, _a=perm, _d=defender:
                            g._run_trigger(_cb, _s, {"attacker": _a, "defender": _d},
                                           subject=_a)),
                        source=src, label=f"creature_attacks:{src.name}"))
        # Exalted: si atacó UNA sola criatura, recibe +1/+1 por cada permanente
        # con exaltación que controle el atacante.
        if len(declared) == 1:
            bonus = sum(getattr(pm.card, "exalted", 0) or 0 for pm in p.battlefield)
            if bonus:
                lone = declared[0]
                lone.temp_pt[0] += bonus
                lone.temp_pt[1] += bonus
                self.log(f"Exaltación: {lone.name} recibe +{bonus}/+{bonus}")
        if declared:
            self._combat_declare_triggers(p, declared)
        self.resolve_stack()
        return declared

    def _combat_declare_triggers(self, p: "Player", declared: list):
        """Disparos al declarar atacantes que necesitan la lista completa de
        atacantes: battle cry, mentor, melee, training, battalion, pack tactics."""
        if len(declared) >= 3:
            for a in declared:
                self._push_self_trigger(a, "battalion", "batallón")
        if sum(max(0, a.power) for a in declared) >= 6:
            for a in declared:
                self._push_self_trigger(a, "pack_tactics", "tácticas de manada")
        # battle cry: cada atacante con battle_cry da +1/+0 a CADA otro atacante.
        cries = sum(1 for a in declared if getattr(a.card, "battle_cry", False))
        if cries:
            for a in declared:
                boost = cries - (1 if getattr(a.card, "battle_cry", False) else 0)
                if boost:
                    a.temp_pt[0] += boost
            self.log(f"Grito de guerra: +{cries}/+0 al resto de atacantes")
        # myriad: por cada OTRO rival, una ficha copia girada y atacándolo; se
        # exilian al final del combate. Se agregan a `declared` (misma lista).
        for a in list(declared):
            if not getattr(a.card, "myriad", False) or a.is_token and getattr(a, "_myriad", False):
                continue
            dfn = a.attacking if isinstance(a.attacking, Player) else a.attacking.controller
            for opp in self.opponents(p):
                if opp is dfn or opp.lost:
                    continue
                for _ in range(self.token_multiplier(p)):
                    tok = self.move_to_battlefield(copy.deepcopy(a.card), p, is_token=True)
                    if tok is None:
                        continue
                    tok._myriad = True
                    tok.tapped = True
                    tok.summoning_sick = False
                    tok.attacking = opp
                    declared.append(tok)
                    self.log(f"Miríada: copia de {a.name} ataca a {opp.name}")
        # melee: +1/+1 por cada jugador atacado este combate.
        opp_players = {(a.attacking if isinstance(a.attacking, Player)
                        else a.attacking.controller) for a in declared}
        nplayers = len(opp_players)
        for a in declared:
            if getattr(a.card, "melee", False) and nplayers:
                a.temp_pt[0] += nplayers
                a.temp_pt[1] += nplayers
                self.log(f"Melé: {a.name} recibe +{nplayers}/+{nplayers}")
        # mentor: pone un contador +1/+1 en otro atacante de menor poder.
        for a in declared:
            if not getattr(a.card, "mentor", False):
                continue
            cands = [o for o in declared if o is not a and o.power < a.power]
            if cands:
                tgt = max(cands, key=lambda o: o.power)
                self.add_counters(tgt, "+1/+1", 1)
                self.log(f"Mentor: {a.name} pone +1/+1 en {tgt.name}")
        # training: si ataca junto a una criatura de MAYOR poder, gana un +1/+1.
        for a in declared:
            if not getattr(a.card, "training", False):
                continue
            if any(o is not a and o.power > a.power for o in declared):
                self.add_counters(a, "+1/+1", 1)
                self.log(f"Entrenamiento: {a.name} recibe un contador +1/+1")
        # dethrone: al atacar al jugador con MÁS vida, un contador +1/+1.
        max_life = max((pl.life for pl in self.players if not pl.lost), default=0)
        for a in declared:
            if getattr(a.card, "dethrone", False) and isinstance(a.attacking, Player) \
                    and a.attacking.life >= max_life:
                self.add_counters(a, "+1/+1", 1)
                self.log(f"Destronar: {a.name} recibe un contador +1/+1")
        # annihilator N: el defensor sacrifica N permanentes al ser atacado.
        for a in declared:
            n = getattr(a.card, "annihilator", 0)
            if not n:
                continue
            defn = a.attacking if isinstance(a.attacking, Player) else a.attacking.controller
            victims = self._sacrifice_candidates(defn, "permanent", n)
            for v in victims:
                self.to_graveyard(v, "aniquilador")
            if victims:
                self.log(f"Aniquilador {n}: {defn.name} sacrifica "
                         f"{len(victims)} permanente(s)")
                self.sba()

    def _apply_block_pairs(self, incoming: list, pairs: list):
        """pairs: [(atacante, bloqueador), ...] ya como Permanent."""
        if getattr(self, "no_block_turn", False):     # "las criaturas no pueden bloquear"
            return
        for attacker, blocker in pairs:
            if attacker not in incoming:
                continue
            if blocker.tapped or not blocker.is_creature() or blocker.attacking:
                continue
            if blocker.cant_block:              # "can't block" (propia o este turno)
                continue
            # evasión: un atacante con volar solo puede bloquearse con volar o alcance
            if attacker.has("flying") and not (blocker.has("flying") or blocker.has("reach")):
                continue
            if not self._can_block_evasion(attacker, blocker):
                continue
            attacker.blocked_by.append(blocker)
            blocker.blocking.append(attacker)

    def _can_block_evasion(self, attacker, blocker) -> bool:
        """Reglas de evasión no-vuelo: fear, intimidate, shadow, horsemanship, skulk."""
        b_art = "artifact" in blocker.card.types
        if attacker.has("shadow") and not blocker.has("shadow"):
            return False
        if blocker.has("shadow") and not attacker.has("shadow"):
            return False   # las de sombra solo bloquean a las de sombra
        if attacker.has("horsemanship") and not blocker.has("horsemanship"):
            return False
        if attacker.has("fear") and not (b_art or (B in blocker.card.identity())):
            return False
        if attacker.has("intimidate") and not (
                b_art or (attacker.card.identity() & blocker.card.identity())):
            return False
        if attacker.has("skulk") and blocker.power > attacker.power:
            return False
        # landwalk: si el DEFENSOR controla una tierra de ese tipo, no se bloquea
        dfn = blocker.controller
        lands = [pm for pm in dfn.battlefield if pm.card.is_land()]
        for kw, sub in _LANDWALK.items():
            if attacker.has(kw) and any(pm.has_subtype(sub) or pm.name.lower() == sub
                                        for pm in lands):
                return False
        if attacker.has("nonbasic_landwalk") and any(
                "basic" not in pm.card.supertypes for pm in lands):
            return False
        if attacker.has("legendary_landwalk") and any(
                "legendary" in pm.card.supertypes for pm in lands):
            return False
        return True

    def _ai_block(self, defender: "Player", declared: list):
        """Deja que la política de `defender` bloquee a sus atacantes."""
        incoming = [a for a in declared if self._def_player(a) is defender]
        if not incoming or not defender.policy:
            return
        pairs = defender.policy.declare_blockers(self, defender, incoming)
        self._apply_block_pairs(incoming, pairs)

    def _combat_block_triggers(self, declared: list):
        """Disparos/estáticas que dependen de los bloqueadores ya asignados:
        afflict, flanking, rampage, bushido."""
        for a in declared:
            blockers = list(a.blocked_by)
            if not blockers:
                continue
            # afflict N: al ser bloqueada, el defensor pierde N vida.
            n = getattr(a.card, "afflict", 0)
            if n:
                defn = (a.attacking if isinstance(a.attacking, Player)
                        else a.attacking.controller)
                defn.life -= n
                self.log(f"Aflicción {n}: {defn.name} pierde {n} vida")
            # flanking: cada bloqueador SIN flanking recibe -1/-1 hasta fin de turno.
            if a.has("flanking"):
                for b in blockers:
                    if not b.has("flanking"):
                        b.temp_pt[0] -= 1
                        b.temp_pt[1] -= 1
                self.log(f"Flanqueo: los bloqueadores de {a.name} reciben -1/-1")
            # rampage N: +N/+N por cada bloqueador MÁS ALLÁ del primero.
            r = getattr(a.card, "rampage", 0)
            if r and len(blockers) > 1:
                bonus = r * (len(blockers) - 1)
                a.temp_pt[0] += bonus
                a.temp_pt[1] += bonus
                self.log(f"Arrasar {r}: {a.name} recibe +{bonus}/+{bonus}")
            # bushido N: al ser bloqueada, +N/+N hasta fin de turno.
            bu = getattr(a.card, "bushido", 0)
            if bu:
                a.temp_pt[0] += bu
                a.temp_pt[1] += bu
                self.log(f"Bushido {bu}: {a.name} recibe +{bu}/+{bu}")
        # bushido también aplica al BLOQUEADOR que bloquea (una vez por combate).
        seen = set()
        for a in declared:
            for b in a.blocked_by:
                bu = getattr(b.card, "bushido", 0)
                if bu and id(b) not in seen:
                    seen.add(id(b))
                    b.temp_pt[0] += bu
                    b.temp_pt[1] += bu
                    self.log(f"Bushido {bu}: {b.name} recibe +{bu}/+{bu}")
        self.sba()

    def _finish_combat(self, declared: list):
        """Valida amenaza, aplica daño (primer golpe + normal) y limpia."""
        for a in declared:
            if a.has("menace") and 0 < len(a.blocked_by) < 2:
                for b in a.blocked_by:
                    b.blocking.remove(a)
                a.blocked_by = []
            if a.has("unblockable") and a.blocked_by:   # "no puede ser bloqueada"
                for b in a.blocked_by:
                    b.blocking.remove(a)
                a.blocked_by = []
        self._after_blocks(declared)
        self._combat_block_triggers(declared)
        self._combat_damage(declared, first_strike=True)
        self.sba()
        self._combat_damage(declared, first_strike=False)
        self.sba()
        for a in declared:
            a.attacking = None
            for b in a.blocked_by:
                if a in b.blocking:
                    b.blocking.remove(a)
            a.blocked_by = []
            if getattr(a, "_myriad", False) and a in a.controller.battlefield:
                a.controller.battlefield.remove(a)     # myriad: exiliar al fin del combate
                self.log(f"Miríada: la copia de {a.name} se exilia")

    def _resolve_combat(self, p: "Player", attackers: list):
        """Aplica los atacantes declarados (por la política o por un humano):
        dispara 'attacks', deja bloquear a los rivales y resuelve el daño."""
        declared = self._declare_attackers(p, attackers)
        if not declared:
            return
        for defender in self.opponents(p):
            self._ai_block(defender, declared)
        self._finish_combat(declared)

    def _combat_damage(self, attackers: list, first_strike: bool):
        """first_strike=True: solo first_strike y double_strike.
        first_strike=False: el resto, mas la segunda mitad del double_strike."""
        self._dmg_step = getattr(self, "_dmg_step", 0) + 1
        if getattr(self, "fog_turn", False):     # Fog: se previene el daño de combate
            return
        def deals_now(perm):
            if first_strike:
                return perm.has("first_strike") or perm.has("double_strike")
            # dano normal: todos menos los que SOLO tienen first_strike
            return not (perm.has("first_strike") and not perm.has("double_strike"))

        def alive(pm):
            return pm in pm.controller.battlefield

        # atacantes
        for a in attackers:
            if a.attacking is None or not deals_now(a) or not alive(a):
                continue
            blockers = [b for b in a.blocked_by if alive(b)]
            if not blockers:
                # sin bloquear pega directo; si fue bloqueado pero el bloqueador
                # murió (p. ej. en el primer golpe), no pasa daño salvo arrolladora
                if not a.blocked_by or a.has("trample"):
                    self.deal_damage(a, a.attacking, a.power, combat=True)
                continue
            dt = a.has("deathtouch")
            remaining = a.power
            for b in blockers:
                if remaining <= 0:
                    break
                lethal = 1 if dt else max(1, b.toughness - b.damage)   # deathtouch: 1 basta
                assign = min(remaining, lethal)
                self.deal_damage(a, b, assign, combat=True)
                remaining -= assign
            if remaining > 0 and a.has("trample"):
                self.deal_damage(a, a.attacking, remaining, combat=True)

        # bloqueadores devuelven dano al atacante (si siguen vivos)
        for a in attackers:
            if not alive(a):
                continue
            for b in list(a.blocked_by):
                if deals_now(b) and alive(b):
                    self.deal_damage(b, a, b.power, combat=True)

    # -- turno ------------------------------------------------------------ #
    def begin_turn(self, p: "Player"):
        """UNTAP + UPKEEP + DRAW + SBA. Compartido por el turno de la política
        (run_turn) y por el turno manual de un humano (interactive)."""
        self.turns_played += 1
        # encabezado de turno: separa visualmente los turnos en el registro
        self.log(f"‹turno› {p.name}")
        # UNTAP (antes: phasing — lo que estaba fuera de fase entra, y lo que
        # tiene phasing sale)
        self._phase_step(p)
        _was_tapped = [pm for pm in p.battlefield if pm.tapped]
        for perm in p.battlefield:
            if getattr(perm, "frozen", False):
                perm.frozen = False          # "no se endereza en su próximo enderezar": salta uno
            elif getattr(perm, "exerted", False):
                perm.exerted = False         # exert: no se endereza esta vez
            else:
                perm.tapped = False
            perm.summoning_sick = False
            perm.damage = 0
            perm.activated_this_turn = False
        p.lands_played = 0
        p.draws_this_turn = 0
        for pm in _was_tapped:
            if not pm.tapped and pm in p.battlefield:
                self._push_self_trigger(pm, "untapped", "se endereza (inspired)")
        # día/noche: la regla mira los hechizos del turno ANTERIOR, así que se
        # evalúa antes de reiniciar el contador de hechizos.
        self._update_day_night(p)
        self.spells_this_turn = 0    # para storm (hechizos lanzados este turno)
        # "este turno" para palabras de habilidad (raid, spectacle, surge…)
        for pl in self.players:
            pl.spells_cast_turn = 0
        self._life_start = {id(pl): pl.life for pl in self.players}
        self.damaged_players = set() # para bloodthirst (rivales dañados este turno)
        self.extra_combats = 0       # fases de combate adicionales se agotan por turno
        p.mana_pool = 0              # el maná flotante se vacía al empezar el turno
        for pl in self.players:      # los escudos de prevención se agotan por turno
            pl.prevent = 0
            pl.prevent_all = False
        self.fog_turn = False        # "prevenir daño de combate este turno" se agota
        self.no_prevention_turn = False   # "el daño no se puede prevenir" se agota
        self.no_block_turn = False        # "las criaturas no pueden bloquear" se agota

        # UPKEEP
        self._tick_suspended(p)          # quita contadores de tiempo (suspend)
        self._tick_rebound(p)            # rebound: relanzar gratis desde el exilio
        for owner, card in list(self.epic):          # épico: copia en tu mantenimiento
            if owner is p and card.on_cast_resolve is not None:
                self.log(f"{p.name} copia {card.name} (épico)")
                card.on_cast_resolve(self, p, self._auto_targets(p, card) or [])
        for owner, card in list(self.paradigm):      # paradigma: copia gratis
            if owner is p and card.on_cast_resolve is not None and card in p.exile:
                self.log(f"{p.name} lanza una copia de {card.name} (paradigma)")
                card.on_cast_resolve(self, p, self._auto_targets(p, card) or [])
        self._forecast(p)
        if getattr(p, "initiative", False):
            self.venture(p, undercity=True)  # la iniciativa: Undercity en tu mantenimiento
        for pl in self.players:          # detain: termina al empezar el turno de quien detuvo
            for pm in pl.battlefield:
                if getattr(pm, "_detained_by", None) is p:
                    pm._detained_by = None
        self._tick_upkeep_counters(p)    # fading / vanishing / cumulative upkeep
        self.emit("upkeep", player=p)
        # "at the beginning of EACH player's upkeep": sin alcance (dispara para todos)
        self.emit("each_upkeep", active=p)
        self.resolve_stack()

        # DRAW (el jugador inicial no roba en el turno 1)
        if not (self.turn == 1 and self.active_index == 0):
            p.draw(1, self)
            self.resolve_stack()
        self.sba()

    def set_monarch(self, player):
        """Monarca (regla de Commander Legends): roba una carta extra al final de su
        turno; quien le hace daño de combate pasa a ser el monarca."""
        if player is None or player.lost or getattr(self, "monarch", None) is player:
            return
        self.monarch = player
        self.log(f"{player.name} es ahora el monarca")
        self.emit("become_monarch", player=player)

    def end_turn(self, p: "Player"):
        """END STEP + CLEANUP + SBA. Compartido por run_turn y el turno manual."""
        if getattr(self, "monarch", None) is p and not p.lost:
            p.draw(1, self)                     # el monarca roba al final de su turno
            self.log(f"{p.name} roba una carta (monarca)")
        for pm in list(p.battlefield):
            if getattr(pm, "_impending", False) and pm.counters.get("time", 0) > 0:
                pm.counters["time"] -= 1
                if pm.counters["time"] <= 0:
                    self.log(f"{pm.name} deja de ser inminente (ya es criatura)")
            cc = getattr(pm.card, "case_cond", None)
            if cc is not None and not getattr(pm, "solved", False):
                try:
                    if cc(self, p):
                        pm.solved = True
                        self.log(f"{p.name} resuelve el caso {pm.name}")
                except Exception:  # noqa: BLE001
                    pass
        # velocidad: sube 1 (máx 4) si un rival perdió vida en tu turno
        if getattr(p, "speed", 0) and p.speed < 4 and any(
                o.life < (getattr(self, "_life_start", {}) or {}).get(id(o), o.life)
                for o in self.opponents(p)):
            p.speed += 1
            self.log(f"{p.name}: velocidad {p.speed}")
        self.emit("end_step", player=p)
        self.emit("each_end_step", active=p)
        self.resolve_stack()
        # limpieza: el daño marcado y los efectos "hasta el fin del turno" se van de
        # TODOS los permanentes a la vez (antes el daño solo del jugador activo: un
        # bloqueador rival seguía dañado en el turno siguiente, y uno potenciado
        # moría en la limpieza al perder el +X/+X con el daño todavía encima).
        for pl in self.players:
            for perm in pl.battlefield:
                perm.damage = 0
                perm.temp_pt = [0, 0]
                perm.temp_keywords = set()
                perm.temp_creature = False       # el vehículo/tierra deja de ser criatura
                perm.temp_subtypes = set()       # subtipos temporales (tierras animadas)
        # el goad/obligación de atacar del jugador activo se agota tras su combate
        for perm in p.battlefield:
            perm.goaded = False
            perm.must_attack = False
        while len(p.hand) > 7:
            if p.policy and hasattr(p.policy, "choose_discard"):
                card = p.policy.choose_discard(self, p)
            else:
                card = p.hand[-1]
            p.hand.remove(card)
            p.graveyard.append(card)
            self.emit("to_graveyard", player=p, card=card)
        # las cartas exiliadas por "impulse" ya no son jugables: quedan en el exilio
        if p.impulse:
            p.exile.extend(p.impulse)
            p.impulse.clear()
        # unearth: las criaturas devueltas se exilian al final del turno
        pend = getattr(self, "unearth_eot", None)
        if pend:
            for owner, card in list(pend):
                for perm in list(owner.battlefield):
                    if perm.card is card:
                        owner.battlefield.remove(perm)
                        if not perm.is_token:     # una ficha exiliada deja de existir
                            owner.exile.append(card)
                        self.log(f"{card.name} se exilia (fin de turno)")
                        break
            pend.clear()
        # Dash: las criaturas jugadas por dash vuelven a la mano al fin del turno.
        dret = getattr(self, "dash_return", None)
        if dret:
            for owner, card in list(dret):
                for perm in list(owner.battlefield):
                    if perm.card is card:
                        owner.battlefield.remove(perm)
                        owner.hand.append(card)
                        self.log(f"{card.name} vuelve a la mano (dash)")
                        break
            dret.clear()
        # Warp: lo lanzado por warp se exilia al final del turno y queda jugable
        # desde el exilio por su coste normal en un turno posterior.
        if self.warp_eot:
            for owner, card in list(self.warp_eot):
                for perm in list(owner.battlefield):
                    if perm.card is card:
                        owner.battlefield.remove(perm)
                        if perm.card.on_leave:
                            self._run_fx(f"on_leave {perm.name}",
                                         lambda _pm=perm, _o=owner: _pm.card.on_leave(self, _o, _pm))
                        card._play_cost = card.cost
                        owner.exile_play.append(card)
                        self.log(f"{card.name} se exilia (warp): se puede volver a lanzar")
                        break
            self.warp_eot.clear()
        # Blitz: se sacrifican al fin del turno (y su muerte roba una carta).
        bsac = getattr(self, "blitz_sac", None)
        if bsac:
            for owner, card in list(bsac):
                for perm in list(owner.battlefield):
                    if perm.card is card:
                        self.to_graveyard(perm, "blitz (fin de turno)")
                        break
            bsac.clear()
        # control temporal (Threaten): devolver los permanentes a su dueño original
        if self.control_returns:
            for perm in list(self.control_returns):
                back = getattr(perm, "return_to", None)
                if back is not None and perm in perm.controller.battlefield:
                    perm.controller.battlefield.remove(perm)
                    perm.controller = back
                    back.battlefield.append(perm)
                    perm.tapped = True   # se "usó" este turno
                    self.log(f"{perm.name} vuelve al control de {back.name}")
                perm.return_to = None
            self.control_returns.clear()
        self.sba()
        # sacrificios / exilios de fin de turno (blitz, warp, unearth) pueden
        # disparar habilidades (muerte, deja el campo): resolverlas ahora
        if self.stack:
            self.resolve_stack()
            self.sba()

    def run_turn(self):
        p = self.ap()
        self.begin_turn(p)
        if p.lost:
            return

        # MAIN 1
        if p.policy:
            p.policy.main_phase(self, p, second=False)
            self.resolve_stack()
        self.sba()

        # COMBATE
        if not p.lost and self.opponents(p):
            self.combat(p)
        self.sba()

        # MAIN 2
        if not p.lost and p.policy:
            self.emit("main2", player=p)
            self.resolve_stack()
            p.policy.main_phase(self, p, second=True)
            self.resolve_stack()
        self.sba()

        # fases de combate adicionales (Aggravated Assault, Combat Celebrant…)
        guard = 0
        while self.extra_combats > 0 and not p.lost and self.opponents(p) and guard < 10:
            self.extra_combats -= 1
            guard += 1
            self.log(f"{p.name}: fase de combate adicional")
            self.combat(p)
            self.sba()
        self.extra_combats = 0

        self.end_turn(p)

    def turn_cap_reached(self) -> bool:
        return self.turns_played >= self.max_turns

    def play(self) -> str:
        """Corre la partida. Devuelve el nombre del ganador o 'EMPATE'."""
        while len(self.alive()) > 1 and not self.turn_cap_reached():
            self.turn += 1
            self.active_index = (self.turn - 1) % len(self.players)
            if self.ap().lost:
                continue
            self.run_turn()
            self.sba()
            # turnos extra ("take an extra turn"), con tope de seguridad
            taken = 0
            while (self.extra_turns and taken < 4
                   and len(self.alive()) > 1 and not self.turn_cap_reached()):
                who = self.extra_turns.pop(0)
                if who.lost:
                    continue
                self.active_index = self.players.index(who)
                self.log(f"{who.name} toma un turno extra")
                self.run_turn()
                self.sba()
                taken += 1
            self.extra_turns.clear()
        alive = self.alive()
        if len(alive) == 1:
            self.log(f"GANA {alive[0].name}")
            return alive[0].name
        self.log("EMPATE (limite de turnos)")
        return "EMPATE"
