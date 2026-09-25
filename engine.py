"""Motor de reglas de Magic: The Gathering (formato Commander).

Este modulo NO conoce ninguna carta concreta. Si para implementar una carta
hace falta editarlo, lo que falta es un gancho generico (ver ARCHITECTURE.md).

Python puro, sin dependencias externas.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

import carddesc as _carddesc     # descripción legible de habilidades (puro)

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
    "unblockable",
}


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
        self.goaded = False              # goad: debe atacar en su próximo turno
        self.must_attack = False
        self.cant_block = False
        self.game = None                 # backref, lo pone move_to_battlefield
        self.activated_this_turn = False  # planeswalker: una activacion por turno
        self.enchanting = None           # si es un aura: el permanente al que anexó

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
        return pt if pt else (self.card.power, self.card.toughness)

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
        return set(self.card.keywords) | self.temp_keywords

    def is_creature(self) -> bool:
        return self.card.is_creature()

    def has(self, kw: str) -> bool:
        if self.abilities_off():
            return False                 # perdió todas sus habilidades (mutación)
        if kw in self.card.keywords or kw in self.temp_keywords:
            return True
        # keywords otorgadas por efectos estáticos (p. ej. Anger desde el cementerio)
        return self.game is not None and self.game.grants_keyword(self, kw)

    def can_attack(self) -> bool:
        if not self.is_creature() or self.tapped:
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
    def __init__(self, name: str, deck: list, commander: Card, policy=None):
        self.name = name
        self.deck_template = deck            # lista de Card (99)
        self.commander_card = commander
        self.life = 40
        self.poison = 0
        self.library: list = []
        self.hand: list = []
        self.graveyard: list = []
        self.exile: list = []
        self.impulse: list = []              # exiliadas por "impulse", jugables este turno
        self.exile_play: list = []           # jugables desde el exilio de forma persistente
        #   (predichas por foretell, etc.); cada carta lleva ._play_cost (Cost)
        self.command: list = [commander]
        self.battlefield: list = []          # lista de Permanent
        self.cmdr_tax = 0                    # +2 por lanzamiento desde la zona de mando
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
            self.hand.append(self.library.pop())
            self.draws_this_turn += 1
            # `count` = cuantas cartas van robadas este turno (para efectos como
            # el drenaje de Kang, que mira la SEGUNDA carta robada del turno).
            game.emit("draw", player=self, count=self.draws_this_turn)

    # -- consultas -------------------------------------------------------- #
    def creatures(self) -> list:
        return [p for p in self.battlefield if p.is_creature()]

    def lands(self) -> list:
        return [p for p in self.battlefield if p.card.is_land()]

    def identity(self) -> set:
        ident = set(self.commander_card.identity())
        return ident

    def mana_sources(self) -> list:
        return [p for p in self.battlefield
                if p.card.produces is not None and not p.tapped]

    def available_mana(self) -> int:
        """Cota superior: suma de max(opciones) por fuente sin tapear + pool flotante."""
        total = self.mana_pool
        for p in self.mana_sources():
            opts = p.card.produces(p, self)
            if opts:
                total += max(opts.values())
        return total

    # -- pago de mana ----------------------------------------------------- #
    def _assign(self, cost: Cost):
        """Empareja fuentes de mana con el coste. Devuelve un plan (lista de
        (permanente, color, cantidad)) o None si no alcanza.

        `produces` devuelve OPCIONES: una tierra dual {R:1,W:1} vale UN mana
        (rojo O blanco), no dos.
        """
        sources = []
        for p in self.mana_sources():
            opts = p.card.produces(p, self)
            if opts:
                sources.append((p, dict(opts)))

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

    def can_pay(self, cost: Cost) -> bool:
        if cost is None:
            return True
        return self._assign(self._pool_reduced(cost)) is not None

    def _pool_reduced(self, cost: Cost) -> Cost:
        """El maná flotante (genérico) cubre parte del coste genérico."""
        if self.mana_pool <= 0 or cost is None:
            return cost
        return Cost(max(0, cost.generic - self.mana_pool), cost.pips)

    def pay(self, cost: Cost) -> bool:
        if cost is None:
            return True
        use = min(self.mana_pool, cost.generic) if self.mana_pool > 0 else 0
        plan = self._assign(self._pool_reduced(cost))
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
        # kind: "spell" | "ability" | "trigger" — para responder/copiar habilidades
        self.kind = kind
        self.perm = perm                # permanente fuente si es una habilidad activada
        self.is_copy_ability = is_copy_ability  # la propia habilidad de copia (no copiable)
        self.copied = False             # ya fue copiada (evita copiarla de nuevo)


# --------------------------------------------------------------------------- #
# Game
# --------------------------------------------------------------------------- #

class Game:
    SELF_SCOPED = {"upkeep", "end_step", "draw", "landfall", "cast", "begin_combat",
                   "gain_life"}
    # descripción amigable de cada evento, para el resumen de habilidades
    EVENT_KIND = {
        "etb": "cuando algo entra al campo", "landfall": "al jugar una tierra",
        "attacks": "al atacar", "death": "cuando muere una criatura",
        "to_graveyard": "cuando algo va al cementerio",
        "leaves_graveyard": "cuando algo deja el cementerio",
        "upkeep": "en tu mantenimiento", "end_step": "al final del turno",
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
        self.active_index = 0
        self.stack: list = []
        self._in_priority = False    # evita recursion al lanzar en respuesta
        self.trace_enabled = trace   # graba snapshots del estado (replay visual)
        self.trace: list = []
        # registro de habilidades que se activaron (para el resumen de la partida):
        # {turn, controller, card, kind}. No crea pasos en la traza.
        self.ability_events: list = []
        # decisión pendiente del humano (juego interactivo): el motor pausa un
        # efecto que requiere elegir (revelar, etc.) hasta resolve_choice().
        self.interactive_human = None
        self.pending_choice = None
        # control temporal (Threaten): permanentes a devolver al fin del turno
        self.control_returns: list = []
        # turnos extra pendientes (para el mismo jugador)
        self.extra_turns: list = []
        self.spell_x = 0            # X elegido del último hechizo con {X} lanzado
        self.spells_this_turn = 0   # hechizos lanzados este turno (storm)
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
            "graveyard": [c.name for c in p.graveyard],
            "exile": [c.name for c in p.exile],
            "battlefield": [self._perm_state(pm) for pm in p.battlefield],
        }

    # -- helpers de jugadores -------------------------------------------- #
    def alive(self) -> list:
        return [p for p in self.players if not p.lost]

    def ap(self) -> "Player":
        return self.players[self.active_index]

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
        """Reglas de objetivo. hexproof: no puede ser objetivo de hechizos/
        habilidades que controla un OPONENTE. ward: aqui se modela como
        'intargeteable por rivales' salvo que el atacante pague (simplificado:
        no lo puede pagar la IA, asi que protege)."""
        if perm.has("shroud"):            # ni su propio controlador lo apunta
            return False
        if perm.controller is caster:
            return True
        if perm.has("hexproof") or perm.has("protection"):
            return False
        if "ward" in perm.card.subtypes:  # ward simplificado
            return False
        return True

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
        for pl in self.players:
            if pl.lost:
                continue
            if event in self.SELF_SCOPED and who is not None and pl is not who:
                continue
            for perm in list(pl.battlefield):
                cb = perm.card.triggers.get(event)
                if cb is None:
                    continue
                # El callback recibe (game, perm, **kw) sin duplicar `perm`.
                inner = {k: v for k, v in kw.items() if k != "perm"}
                self.stack.append(StackObject(
                    controller=pl,
                    resolve=(lambda g, _cb=cb, _perm=perm, _kw=inner: _cb(g, _perm, **_kw)),
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
                    "run": (lambda g, _cb=cb, _perm=perm, _kw=inner: _cb(g, _perm, **_kw)),
                }
            # Fase D: disparos MIENTRAS la carta está en el cementerio/exilio.
            for zone in (pl.graveyard, pl.exile):
                for card in list(zone):
                    cb = getattr(card, "gy_triggers", {}).get(event)
                    if cb is None:
                        continue
                    # el dueño va posicional (_p); evitamos duplicar 'player'/'perm' del kw
                    inner = {k: v for k, v in kw.items() if k not in ("perm", "player")}
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
            obj.resolve(self)
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
        src_ctrl = source.controller if isinstance(source, Permanent) else None
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
        Heliod…). Sólo cuenta ganancia real (n > 0)."""
        if n <= 0:
            return
        player.life += n
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

    def move_to_battlefield(self, card: Card, player: "Player",
                            is_token: bool = False) -> Permanent:
        # salvaguarda: un instantáneo/conjuro NUNCA puede entrar al campo. Si algún
        # efecto lo intenta (reanimación mal parseada, etc.), va al cementerio.
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
        # planeswalker: entra con su lealtad inicial
        if "planeswalker" in card.types and card.loyalty:
            perm.counters["loyalty"] = card.loyalty
        # "entra con N contadores" (efecto de reemplazo: antes de los disparos ETB)
        for kind, n in (getattr(card, "etb_counters", None) or {}).items():
            if n:
                perm.counters[kind] = perm.counters.get(kind, 0) + n
        player.battlefield.append(perm)
        if card.on_etb:
            self.note_ability(card, "entra al campo", controller=player)
            card.on_etb(self, player, perm)
        self.emit("etb", player=player, perm=perm)
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
        if card.is_land():
            self.emit("landfall", player=player)
        return perm

    def destroy(self, perm: Permanent, reason: str = ""):
        """Respeta indestructible."""
        if perm.has("indestructible"):
            return
        self.to_graveyard(perm, reason)

    def to_graveyard(self, perm: Permanent, reason: str = ""):
        """Ignora indestructible. El comandante vuelve a la zona de mando.
        Los tokens desaparecen."""
        ctrl = perm.controller
        if perm not in ctrl.battlefield:
            return
        ctrl.battlefield.remove(perm)
        relocated = False
        if perm.card.on_death:
            # on_death puede devolver True (persist/undying) para indicar que la
            # carta ya volvió al campo y NO debe ir al cementerio.
            relocated = bool(perm.card.on_death(self, ctrl, perm))
        self.emit("death", player=ctrl, perm=perm)
        if perm.is_token:
            return
        if relocated:
            return
        # comandante: vuelve a la zona de mando (eleccion; aqui siempre)
        if perm.card is ctrl.commander_card:
            ctrl.command.append(perm.card)
            self.log(f"{perm.name} vuelve a la zona de mando")
            return
        # reemplazo "si moriría, exíliala en su lugar" (odio de cementerio)
        if perm.card.is_creature() and self._dies_to_exile(perm):
            ctrl.exile.append(perm.card)
            self.log(f"{perm.name} es exiliada en vez de ir al cementerio")
            return
        ctrl.graveyard.append(perm.card)
        self.emit("to_graveyard", player=ctrl, card=perm.card)

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
            if pm.card is ctrl.commander_card:
                v += 100
            return v
        pool.sort(key=worth)
        return pool[:n]

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
            ctrl.graveyard.append(card)
            self.emit("to_graveyard", player=ctrl, card=card)
        self.log(f"{ctrl.name} descarta {count} carta(s) (coste)")

    def leave_graveyard(self, player: "Player", card: Card, dest: str = "exile") -> bool:
        """Saca una carta del cementerio. Emite leaves_graveyard. Devuelve bool."""
        if card not in player.graveyard:
            return False
        player.graveyard.remove(card)
        if dest == "exile":
            player.exile.append(card)
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
        # prevención de daño (escudos "hasta el fin del turno")
        if isinstance(target, Player):
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
        elif isinstance(target, Permanent):
            pv = getattr(target, "prevent", 0)
            if pv > 0:
                blocked = min(pv, amount)
                target.prevent = pv - blocked
                amount -= blocked
                if amount <= 0:
                    return
        src_perm = isinstance(source, Permanent)
        if isinstance(target, Player):
            if src_perm and source.has("infect"):
                target.poison += amount            # infect: veneno en vez de vida
            elif src_perm and source.has("toxic"):
                target.life -= amount              # toxic: daño normal + veneno (aprox)
                target.poison += 1
            else:
                target.life -= amount
            # dano de comandante
            if combat and src_perm and source.card is source.controller.commander_card:
                key = source.name
                target.cmdr_damage[key] = target.cmdr_damage.get(key, 0) + amount
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
        # lifelink: la fuente gana vida = daño hecho, contra CUALQUIER objetivo
        if src_perm and source.has("lifelink"):
            self.gain_life(source.controller, amount)

    # -- acciones basadas en estado -------------------------------------- #
    def sba(self):
        changed = True
        while changed:
            changed = False
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
                        self.to_graveyard(perm, "daño letal")
                        changed = True
            # planeswalkers sin lealtad
            for p in self.players:
                for perm in list(p.battlefield):
                    if ("planeswalker" in perm.card.types
                            and perm.counters.get("loyalty", 0) <= 0):
                        self.to_graveyard(perm, "loyalty 0")
                        changed = True
            # aura sin huésped válido -> al cementerio
            for p in self.players:
                for perm in list(p.battlefield):
                    if "aura" not in {s.lower() for s in perm.card.subtypes}:
                        continue
                    host = perm.enchanting
                    if host is None or host not in host.controller.battlefield:
                        self.to_graveyard(perm, "aura sin objetivo")
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
    def cast(self, player: "Player", card: Card, from_command: bool = False,
             targets=None, chosen_modes=None, x_value=None):
        cost = card.cost
        # impuesto de comandante + reducción "cuesta {N} menos"
        extra = player.cmdr_tax if from_command else 0
        red = (getattr(card, "cost_reduction", 0) or 0) + self._static_cost_reduction(player, card)
        pay_cost = cost
        if cost is not None and (extra or red):
            pay_cost = Cost(generic=max(0, cost.generic + extra - red), pips=cost.pips)
        # hechizos con {X}: se elige X = maná sobrante tras pagar el coste base
        self.spell_x = 0
        if getattr(card, "x_spell", False) and cost is not None:
            base = pay_cost if pay_cost is not None else cost
            # X elegido (humano) o, si no, el máximo pagable (auto para bots)
            x = x_value if x_value is not None else max(0, player.available_mana() - base.cmc)
            x = max(0, x)
            if x:
                self.spell_x = x
                pay_cost = Cost(generic=base.generic + x, pips=base.pips)
                self.log(f"{player.name} elige X = {x} para {card.name}")
        # reducciones dinámicas: affinity (artefactos), convoke (girar criaturas),
        # delve (exiliar del cementerio). Bajan el genérico y consumen recursos.
        convoke_tap, delve_n = [], 0
        tags = getattr(card, "tags", set()) or set()
        if pay_cost is not None and (tags & {"affinity_art", "convoke", "delve"}):
            gen = pay_cost.generic
            if "affinity_art" in tags:
                arts = sum(1 for pm in player.battlefield if "artifact" in pm.card.types)
                gen = max(0, gen - arts)
            if "convoke" in tags:
                creqs = [pm for pm in player.battlefield if pm.is_creature() and not pm.tapped]
                use = min(gen, len(creqs))
                convoke_tap = creqs[:use]
                gen -= use
            if "delve" in tags:
                delve_n = min(gen, len(player.graveyard))
                gen -= delve_n
            pay_cost = Cost(generic=gen, pips=pay_cost.pips)
        # Buyback: coste adicional de maná; si se paga, la carta vuelve a la mano al
        # resolver. Auto: se paga si el jugador puede afrontar coste base + buyback.
        card._buyback_used = False
        bb = getattr(card, "_buyback_cost", 0) or 0
        if bb and pay_cost is not None:
            bb_cost = Cost(generic=pay_cost.generic + bb, pips=pay_cost.pips)
            if player.can_pay(bb_cost):
                pay_cost = bb_cost
                card._buyback_used = True
        if not player.can_pay(pay_cost):
            return False
        # coste adicional al lanzar (pagar vida / descartar / sacrificar)
        add = getattr(card, "additional_cost", None) or {}
        if add:
            if add.get("pay_life"):
                player.life -= add["pay_life"]
            for _ in range(add.get("discard", 0)):
                if player.hand:
                    player.graveyard.append(player.hand.pop())
            if add.get("sacrifice"):
                creqs = [pm for pm in player.battlefield if pm.is_creature()
                         and pm.card is not card]
                if creqs:
                    victim = min(creqs, key=lambda c: (c.power, c.toughness))
                    self.to_graveyard(victim, "coste adicional")
            self.log(f"{player.name} paga el coste adicional de {card.name}")
        player.pay(pay_cost)
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
            player.cmdr_tax += 2
        else:
            if card in player.hand:
                player.hand.remove(card)

        self.log(f"{player.name} lanza {card.name}")
        # telemetria: registrar el lanzamiento y el turno del comandante
        st = getattr(player, "stats", None)
        if st is not None:
            st["cast_counts"][card.name] += 1
            if card is player.commander_card and st["commander_turn"] is None:
                st["commander_turn"] = self.turn
        # Storm: copias = hechizos ya lanzados este turno ANTES de este.
        storm_copies = self.spells_this_turn if (getattr(card, "tags", set())
                                                 and "storm" in card.tags) else 0
        self.spells_this_turn += 1
        # Buyback: si se pagó el coste adicional de buyback, la carta vuelve a la mano.
        buyback_used = bool(getattr(card, "_buyback_used", False))
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

        def _resolve(g):
            if card.is_land():  # las tierras no se lanzan, pero por seguridad
                g.move_to_battlefield(card, player)
            elif {"instant", "sorcery"} & card.types:
                if card.modes:
                    picks = chosen_modes if chosen_modes else [0]
                    for mi in picks:
                        if 0 <= mi < len(card.modes):
                            m = card.modes[mi]
                            g.note_ability(card, f"modo «{m.get('label', '')}»", controller=player)
                            eff = m.get("effect")
                            if eff:
                                eff(g, player, targets or [])
                elif card.on_cast_resolve:
                    g.note_ability(card, "resuelve su efecto", controller=player)
                    reps = 1 + storm_copies      # storm: repetir el efecto por copia
                    if storm_copies:
                        g.log(f"Storm: {card.name} se copia {storm_copies} vez(ces)")
                    for _ in range(reps):
                        card.on_cast_resolve(g, player, targets or [])
                else:
                    # carta sin efecto modelado (mecánica compleja): que al menos se
                    # vea que se resolvió, en vez de "no pasó nada".
                    g.log(f"{player.name} resuelve {card.name} "
                          f"(efecto complejo: no se simula en detalle)")
                # Buyback: vuelve a la mano en vez de al cementerio.
                if buyback_used:
                    player.hand.append(card)
                    g.log(f"{card.name} vuelve a la mano (buyback)")
                else:
                    player.graveyard.append(card)
                    g.emit("to_graveyard", player=player, card=card)
            else:
                g.move_to_battlefield(card, player)

        self.stack.append(StackObject(player, _resolve, source=card,
                                      targets=targets, label=f"spell:{card.name}",
                                      chosen_modes=chosen_modes))
        return self._after_stack_push(player, card)

    def _after_stack_push(self, player, react_arg):
        """Tras poner un objeto en la pila (hechizo o habilidad): si ya estamos en
        una ventana de prioridad, dejarlo para el bucle externo; si hay un humano
        que puede reaccionar, pausar (ReactionPause); si no, drenar con prioridad."""
        if self._in_priority:
            return True   # puesto en respuesta: el bucle externo lo resolverá
        # ventana de reacción del humano: si un rival hace algo que el humano
        # podría responder, pausamos (la capa interactiva reanuda tras responder).
        rc = getattr(self, "reaction_check", None)
        if rc is not None and rc(player, react_arg):
            raise ReactionPause(self.stack[-1])
        self._run_priority_and_resolve()
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
                    top.resolve(self)
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

    def activate_ability(self, perm: Permanent, index: int, targets=None) -> bool:
        """Activa una habilidad con coste de maná (y opcionalmente girar) de un
        permanente. El coste se paga al activar; el EFECTO va a la pila y se
        resuelve con prioridad (refactor A). Se puede repetir mientras haya con
        qué pagar."""
        abils = perm.card.activated_abilities
        if not abils or not (0 <= index < len(abils)):
            return False
        ab = abils[index]
        if ab.get("tap") and perm.tapped:
            return False
        ctrl = perm.controller
        if not ctrl.can_pay(ab.get("cost")):
            return False
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
        ctrl.pay(ab.get("cost"))
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
        self.log(f"{ctrl.name}: {perm.name} activa «{ab.get('label', '')}»")
        self.note_ability(perm.card, f"habilidad: {ab.get('label', '')}", controller=ctrl)
        eff = ab.get("effect")
        _t = list(targets or [])
        is_copy = bool(ab.get("is_copy_ability"))

        def _resolve(g, _eff=eff, _c=ctrl, _p=perm, _tg=_t, _ab=ab, _is_copy=is_copy):
            if _eff:
                _eff(g, _c, _p, _tg)
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
            g.note_ability(_src, "copia del hechizo se resuelve", controller=_ctrl)
            if getattr(_src, "modes", None):
                # la copia reproduce los MISMOS modos que eligió el original
                idxs = _picks if _picks else [0]
                for mi in idxs:
                    if 0 <= mi < len(_src.modes):
                        e = _src.modes[mi].get("effect")
                        if e:
                            e(g, _ctrl, _tgts)
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
            ok = (filt == "any"
                  or (filt == "creature" and "creature" in types)
                  or (filt == "noncreature" and "creature" not in types)
                  or (filt == "instant_sorcery" and ({"instant", "sorcery"} & types))
                  or (filt == "artifact" and "artifact" in types))
            if ok:
                total += amt
        return total

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
        m, after = gp.get("mode"), gp.get("after")
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
        p.graveyard.remove(card)
        orig = card.cost
        try:
            if cost is not None:
                card.cost = cost
            self.cast(p, card, targets=targets, chosen_modes=chosen_modes)
        finally:
            card.cost = orig
        if card in p.graveyard:
            p.graveyard.remove(card)
            p.exile.append(card)
            self.log(f"{card.name} se exilia tras lanzarse desde el cementerio")
        self.sba()
        return True

    def play_from_exile(self, p: "Player", card: Card,
                        targets=None, chosen_modes=None) -> bool:
        """Juega una carta desde el exilio persistente (foretell / impulse no
        acotado) pagando su coste alternativo `_play_cost`."""
        if card not in p.exile_play:
            return False
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
        orig = card.cost
        try:
            card.cost = cost
            ok = self.cast(p, card, targets=targets, chosen_modes=chosen_modes)
        finally:
            card.cost = orig
        if ok is not False and card in p.exile_play:
            p.exile_play.remove(card)
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
            declared.append(perm)
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
                    p, (lambda g, _cb=cb, _perm=perm, _d=defender: _cb(g, _perm, defender=_d)),
                    source=perm, label=f"attacks:{perm.name}"))
        # Exalted: si atacó UNA sola criatura, recibe +1/+1 por cada permanente
        # con exaltación que controle el atacante.
        if len(declared) == 1:
            bonus = sum(getattr(pm.card, "exalted", 0) or 0 for pm in p.battlefield)
            if bonus:
                lone = declared[0]
                lone.temp_pt[0] += bonus
                lone.temp_pt[1] += bonus
                self.log(f"Exaltación: {lone.name} recibe +{bonus}/+{bonus}")
        self.resolve_stack()
        return declared

    def _apply_block_pairs(self, incoming: list, pairs: list):
        """pairs: [(atacante, bloqueador), ...] ya como Permanent."""
        for attacker, blocker in pairs:
            if attacker not in incoming:
                continue
            if blocker.tapped or not blocker.is_creature() or blocker.attacking:
                continue
            # evasión: un atacante con volar solo puede bloquearse con volar o alcance
            if attacker.has("flying") and not (blocker.has("flying") or blocker.has("reach")):
                continue
            attacker.blocked_by.append(blocker)
            blocker.blocking.append(attacker)

    def _ai_block(self, defender: "Player", declared: list):
        """Deja que la política de `defender` bloquee a sus atacantes."""
        incoming = [a for a in declared if self._def_player(a) is defender]
        if not incoming or not defender.policy:
            return
        pairs = defender.policy.declare_blockers(self, defender, incoming)
        self._apply_block_pairs(incoming, pairs)

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
        # UNTAP
        for perm in p.battlefield:
            perm.tapped = False
            perm.summoning_sick = False
            perm.damage = 0
            perm.activated_this_turn = False
        p.lands_played = 0
        p.draws_this_turn = 0
        self.spells_this_turn = 0    # para storm (hechizos lanzados este turno)
        p.mana_pool = 0              # el maná flotante se vacía al empezar el turno
        for pl in self.players:      # los escudos de prevención se agotan por turno
            pl.prevent = 0
            pl.prevent_all = False
        self.fog_turn = False        # "prevenir daño de combate este turno" se agota

        # UPKEEP
        self.emit("upkeep", player=p)
        self.resolve_stack()

        # DRAW (el jugador inicial no roba en el turno 1)
        if not (self.turn == 1 and self.active_index == 0):
            p.draw(1, self)
            self.resolve_stack()
        self.sba()

    def end_turn(self, p: "Player"):
        """END STEP + CLEANUP + SBA. Compartido por run_turn y el turno manual."""
        self.emit("end_step", player=p)
        self.resolve_stack()
        for perm in p.battlefield:
            perm.damage = 0
        # limpieza "hasta el fin del turno": buffs temporales de TODOS los permanentes
        for pl in self.players:
            for perm in pl.battlefield:
                perm.temp_pt = [0, 0]
                perm.temp_keywords = set()
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
                        owner.exile.append(card)
                        self.log(f"{card.name} se exilia (unearth)")
                        break
            pend.clear()
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
            p.policy.main_phase(self, p, second=True)
            self.resolve_stack()
        self.sba()

        self.end_turn(p)

    def play(self) -> str:
        """Corre la partida. Devuelve el nombre del ganador o 'EMPATE'."""
        while len(self.alive()) > 1 and self.turn < self.max_turns:
            self.turn += 1
            self.active_index = (self.turn - 1) % len(self.players)
            if self.ap().lost:
                continue
            self.run_turn()
            self.sba()
            # turnos extra ("take an extra turn"), con tope de seguridad
            taken = 0
            while (self.extra_turns and taken < 4
                   and len(self.alive()) > 1 and self.turn < self.max_turns):
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
