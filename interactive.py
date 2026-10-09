"""Partida interactiva: un humano vs el sistema (Fase 2).

Conduce un `Game` paso a paso. El humano maneja SU turno (jugar tierra, lanzar,
atacar, terminar); los oponentes juegan solos con su política. En los turnos
rivales, la política del humano resuelve bloqueos y respuestas automáticamente
(simplificación del MVP: el humano todavía no elige bloqueos).

Es Python puro y sin red: corre igual en un test headless y dentro de Pyodide
en el navegador. La capa web solo llama a estos métodos y dibuja `state()`.
"""
from __future__ import annotations

import copy
import run
import carddesc
from engine import Game, Cost, ReactionPause


def _sick(pm):
    """¿Criatura con mareo de invocación (no puede usar habilidades de {T})?"""
    return pm.is_creature() and pm.summoning_sick and not pm.has("haste")


def _never_respond(*_a, **_k):
    """Reemplaza respond/respond_copy/respond_ability en la política del HUMANO:
    las respuestas las decide la persona en su ventana de reacción, no su IA."""
    return False


def from_registered(specs, human_index=0, seed=0, level="intermedio"):
    """Construye una partida interactiva desde decks REGISTRADOS (de ejemplo).
    `specs`: lista de {"key": <clave>, "name": <opcional>}."""
    import decks
    defs = []
    for s in specs:
        key = s["key"] if isinstance(s, dict) else s
        name = s.get("name") if isinstance(s, dict) else None
        deck, cmd = decks.build(key)
        defs.append((name or cmd.name, deck, cmd))
    return InteractiveGame(defs, human_index=human_index, seed=seed, level=level)


def from_specs(specs, datamap=None, human_index=0, seed=0, level="intermedio"):
    """Construye una partida mezclando decks registrados y decks IMPORTADOS.
    `specs`: lista de {"kind":"registered","key":..} o
             {"kind":"custom","name":..,"text":<decklist>}.
    `datamap`: {nombre_norm: datos_scryfall} ya resuelto por el servidor, para
    armar los custom sin red (build_deck usa este fetch)."""
    import decks
    import decklist
    import cardsdb
    datamap = datamap or {}

    def fetch(name):
        return datamap.get(cardsdb._norm(name))

    defs = []
    for s in specs:
        if s.get("kind") == "custom" and not s.get("key"):
            parsed = decklist.parse_decklist(s.get("text", ""))
            deck, cmd, _rep = decklist.build_deck(parsed, fetch=fetch)
            label = s.get("name") or cmd.name
        else:
            deck, cmd = decks.build(s["key"])
            label = s.get("name") or cmd.name
        defs.append((label, deck, cmd))
    # mismo tope de turnos que la simulación (api/_sim.py): una partida de
    # Commander puede ser larga, así que escalamos con la cantidad de mazos en
    # vez de cortar a los 60 turnos (antes la partida jugable terminaba mucho
    # antes que la simulación del mismo cruce).
    max_turns = min(320, 40 + 40 * len(defs))
    return InteractiveGame(defs, human_index=human_index, seed=seed, level=level,
                           max_turns=max_turns)


def _cost_str(card):
    return _cost_str_cost(card.cost)


def _cost_str_cost(c):
    if c is None:
        return ""
    return (str(c.generic) if c.generic else "") + "".join(c.pips)


class InteractiveGame:
    def __init__(self, deck_defs, human_index=0, seed=0, level="intermedio",
                 max_turns=60):
        self.players = run.build_players_from_defs(deck_defs, level=level)
        self.n = len(self.players)
        self.human_index = max(0, min(int(human_index), self.n - 1))
        self.g = Game(self.players, seed=int(seed), max_turns=max_turns,
                      trace=False)
        self.phase = "mulligan"     # mulligan | main | defense | over
        self.attacked = False
        self.winner = None
        self.mode = None            # None | "defense" | "combat" | "react"
        self._attacker = None       # jugador que ataca (durante defensa)
        self._declared = []         # atacantes declarados (Permanent)
        self._combat_declared = []  # atacantes en la ventana de daño (post-bloqueo)
        self._combat_resume = None  # cómo seguir tras aplicar el daño de combate
        self.mulls = 0              # mulligans que llevás (para el londrino)
        self._undo = []             # pila de snapshots para deshacer jugadas del turno
        self._react_armed = False   # ventana de reacción activa (durante main del bot)
        self._react_ctx = None      # {p, step, spell} para reanudar tras responder
        self.opp_turns = []         # resumen de los turnos rivales desde tu último turno
        self._draining = False      # mostrando decisiones encoladas durante el avance
        # la IA del humano no contrarresta/copia por él (antes, tras pasar en la
        # ventana de reacción, su política lanzaba igual su Counterspell)
        hp = self.human().policy
        if hp is not None:
            for name in ("respond", "respond_copy", "respond_ability"):
                setattr(hp, name, _never_respond)
        # el motor pausa una resolución cuando el HUMANO debe elegir (revelar, etc.)
        self.g.interactive_human = self.human()
        self.g.pending_choice = None
        # y pausa el turno del bot cuando el humano puede responder a un hechizo
        self.g.reaction_check = self._offer_reaction
        # cascada: cuando el humano cascadea un hechizo con objetivo, elige a mano
        self.g.cascade_target_hook = self._cascade_choose
        self._ai_mulligans()        # los rivales hacen mulligan solos
        # el humano decide en la fase "mulligan" (ver mulligan()/keep())

    # -- mulligan (regla de Commander: primer mulligan gratis) ------------ #
    def _draw7(self, p):
        p.library.extend(p.hand)
        p.hand = []
        self.g.rng.shuffle(p.library)
        for _ in range(7):
            if p.library:
                p.hand.append(p.library.pop())

    def _ai_mulligans(self, max_mulls=3):
        for p in self.players:
            if p is self.human():
                continue
            mulls = 0
            while (mulls < max_mulls and p.policy is not None
                   and hasattr(p.policy, "should_mulligan")
                   and p.policy.should_mulligan(p.hand, p)):
                self._draw7(p)
                mulls += 1
            for _ in range(max(0, mulls - 1)):   # primer mulligan gratis
                if not p.hand:
                    break
                card = self.g._bottom_choice(p)
                p.hand.remove(card)
                p.library.insert(0, card)

    def mulligan(self):
        """El humano hace un mulligan (roba 7 nuevas). El primero es gratis."""
        if self.phase != "mulligan":
            return self.state()
        self._draw7(self.human())
        self.mulls += 1
        return self.state()

    def keep(self, bottom_indices=None):
        """Se queda con la mano. Pone (mulligans-1) cartas al fondo (Commander:
        el primer mulligan no cuesta)."""
        if self.phase != "mulligan":
            return self.state()
        me = self.human()
        to_bottom = max(0, self.mulls - 1)
        chosen = [i for i in sorted(set(bottom_indices or []), reverse=True)
                  if 0 <= i < len(me.hand)][:to_bottom]
        for i in chosen:
            me.library.insert(0, me.hand.pop(i))
        while len(me.hand) > 7 - to_bottom and me.hand:   # completar si faltó
            card = self.g._bottom_choice(me)
            me.hand.remove(card)
            me.library.insert(0, card)
        self.phase = "waiting"
        self._advance_to_human()
        return self.state()

    # -- helpers ---------------------------------------------------------- #
    def human(self):
        return self.players[self.human_index]

    def _finish(self):
        alive = self.g.alive()
        self.winner = alive[0].name if len(alive) == 1 else "EMPATE"
        self.phase = "over"

    def _advance_to_human(self):
        """Corre turnos rivales hasta que sea el turno del humano, se pause por
        una defensa, o termine la partida. Antes de cada turno normal agota los
        turnos extra encolados (mismo criterio que engine.play)."""
        while True:
            if self._run_extra_turns():   # frenó: turno extra humano o me atacan
                return
            if len(self.g.alive()) <= 1 or self.g.turn_cap_reached():
                self._finish()
                return
            self.g.turn += 1
            self.g.active_index = (self.g.turn - 1) % self.n
            p = self.g.ap()
            if p.lost:
                continue
            if self.g.active_index == self.human_index:
                self.g.begin_turn(p)
                self.g.sba()
                if p.lost:
                    continue
                self.phase = "main"
                self.attacked = False
                # drenar decisiones que hayan quedado encoladas (p. ej. de un
                # disparo en mi mantenimiento): se muestran ahora, al inicio de
                # mi turno, sin marcar _draining (ya es mi turno), para que no
                # afloren a mitad de una jugada ni terminen el turno.
                self._surface_queued_choice()
                return
            n0 = len(self.g.log_lines)
            paused = self._ai_turn(p)     # pausó porque me atacan
            self._record_opp_turn(p, n0)
            if paused:
                return
            if self._surface_queued_choice():   # el bot me forzó una decisión
                return

    def _surface_queued_choice(self):
        """Si un efecto de un bot encoló una decisión del humano, la muestra ahora
        (arma pending_choice) y marca que hay que reanudar el avance al resolverla.
        Devuelve True si frenó el avance para que el humano decida."""
        while self.g.choice_queue and self.g.pending_choice is None:
            item = self.g.choice_queue.pop(0)
            if isinstance(item, dict):      # decisión ya armada que esperaba su turno
                self.g.pending_choice = item
                continue
            try:
                item()
            except Exception:
                continue
        if self.g.pending_choice is not None:
            # OJO: solo marcamos "draining" (reanudar el avance de turnos al
            # resolver) cuando estamos avanzando por turnos RIVALES y NO hay una
            # ventana abierta (defensa / daño / reacción). Si es el turno propio
            # del humano, o una ventana espera su respuesta, resolver la decisión
            # debe volver a esa ventana: marcar _draining haría avanzar turnos y
            # saltar el resto del turno (o el ataque en curso y el turno siguiente).
            if self.g.active_index != self.human_index and self.mode is None:
                self._draining = True
            return True
        return False

    def _run_extra_turns(self):
        """Agota `game.extra_turns` tras el turno recién jugado (tope 4). Devuelve
        True si hay que frenar el avance: el humano toma un turno extra, o un bot
        que toma su turno extra me ataca (pausa de defensa)."""
        taken = 0
        while (self.g.extra_turns and taken < 4
               and len(self.g.alive()) > 1 and not self.g.turn_cap_reached()):
            who = self.g.extra_turns.pop(0)
            if who.lost:
                continue
            self.g.active_index = self.g.players.index(who)
            self.g.log(f"{who.name} toma un turno extra")
            taken += 1
            if who is self.human():
                self.g.begin_turn(who)
                self.g.sba()
                if who.lost:
                    continue
                self.phase = "main"
                self.attacked = False
                return True          # el humano juega su turno extra
            n0 = len(self.g.log_lines)
            paused = self._ai_turn(who)
            self._record_opp_turn(who, n0)
            if paused:
                return True          # el bot me ataca en su turno extra
            if self._surface_queued_choice():
                return True          # el bot me forzó una decisión
        return False

    def _record_opp_turn(self, p, n0):
        """Guarda lo que hizo el rival `p` en su turno (rebanada del registro), para
        que el humano vea cada turno rival por separado en vez de todos juntos."""
        lines = []
        for ln in self.g.log_lines[n0:]:
            body = ln.split(" ", 1)[1] if ln[:1] == "T" and " " in ln else ln
            if body.startswith("‹turno›"):
                continue
            lines.append(body)
        if lines:
            self.opp_turns.append({"turn": self.g.turn, "player": p.name,
                                   "lines": lines[-12:]})

    # -- turno rival, con pausa en mi defensa / reacción ----------------- #
    def _ai_turn(self, p):
        self.g.begin_turn(p)
        self.g.sba()
        if p.lost:
            return False
        # ledger de habilidades usadas este turno: persiste a través de una
        # ReactionPause para que el bot no re-active lo mismo al reanudar.
        p._abil_perms_used = set()
        return self._ai_steps(p, "main1")

    def _ai_steps(self, p, step):
        """Corre el turno del bot desde `step` (main1 / combat / main2),
        capturando la pausa de reacción del humano. Devuelve True si hay que
        frenar (defensa o reacción); reanudable con el mismo `step`."""
        try:
            if step == "main1":
                if p.policy:
                    self._react_armed = True
                    try:
                        p.policy.main_phase(self.g, p, second=False)
                    finally:
                        self._react_armed = False
                    self.g.resolve_stack()
                self.g.sba()
                step = "combat"
            if step == "combat":
                if not p.lost and self.g.opponents(p):
                    if self._ai_combat(p):
                        return True          # pausa de defensa
                step = "main2"
            if step == "main2":
                if not p.lost and p.policy:
                    self._react_armed = True
                    try:
                        p.policy.main_phase(self.g, p, second=True)
                    finally:
                        self._react_armed = False
                    self.g.resolve_stack()
                self.g.sba()
                self.g.end_turn(p)
                self.g.sba()
            return False
        except ReactionPause as rp:
            self._react_ctx = {"p": p, "step": step, "spell": rp.spell}
            self.mode = "react"
            self.phase = "react"
            return True

    def _ready_copy_ability(self, hu):
        """(perm, index) de una habilidad 'copiar habilidad' del humano lista para
        activar (no girada si pide {T}, con maná), o None."""
        for pm in hu.battlefield:
            for j, ab in enumerate(getattr(pm.card, "activated_abilities", ()) or ()):
                if not ab.get("is_copy_ability"):
                    continue
                if ab.get("tap") and (pm.tapped or _sick(pm)):
                    continue
                if hu.can_pay(ab.get("cost"), exclude={pm} if ab.get("tap") else None):
                    return (pm, j)
        return None

    def _extra_cost_reason(self, p, pm, ab):
        """Motivo por el que un coste ADICIONAL (sacrificar otra permanente, pagar
        vida, descartar) no se puede pagar; None si sí se puede."""
        sac_o = ab.get("sacrifice_other")
        if sac_o:
            cands = self.g._sacrifice_candidates(p, sac_o["type"], sac_o["count"],
                                                 exclude=pm)
            if len(cands) < sac_o["count"]:
                return f"sin {sac_o['type']} que sacrificar"
        if (ab.get("pay_life") or 0) and p.life <= ab["pay_life"]:
            return "sin vida"
        disc = ab.get("discard") or 0
        if disc > 0 and len(p.hand) < disc:
            return "sin cartas para descartar"
        return None

    def _offer_reaction(self, caster, arg):
        """¿El humano puede/quiere responder a `arg` de `caster`? `arg` es una
        carta (hechizo) o un StackObject (habilidad). Solo durante la fase
        principal de un bot y si el objeto de la pila LO AFECTA (le apunta a él o
        a un permanente suyo, o es un barrido) y tiene con qué responder."""
        if not self._react_armed:
            return False
        if self.g.split_second_on_stack():
            return False                 # split second: nadie responde
        hu = self.human()
        if caster is hu or hu.lost or hu not in self.g.opponents(caster):
            return False
        # `arg` puede ser el StackObject del hechizo (que ya puede tener disparos
        # de "cast" encima): evaluarlo a ÉL, no al tope de la pila
        top = arg if hasattr(arg, "resolve") else (self.g.stack[-1] if self.g.stack else None)
        affects = self._affects_human(hu, top)
        kind = getattr(arg, "kind", None) or (top.kind if top else None)
        # HABILIDAD / disparo del rival: responder si el humano puede copiarla, o
        # con un instantáneo si el disparo lo afecta (edicto, quema por disparo…).
        if kind in ("ability", "trigger"):
            if self._ready_copy_ability(hu) is not None:
                return True
            return affects and self._has_instant_response(hu)
        # HECHIZO del rival: si lo afecta y tiene un instantáneo pagable, o si tiene
        # un contrahechizo con que responder a cualquier hechizo.
        if affects and self._has_instant_response(hu):
            return True
        return self._has_counter_response(hu)

    def _has_instant_response(self, hu, declared=None):
        """¿El humano tiene en mano un instantáneo/destello que pueda pagar (o un
        ninjutsu / una criatura boca abajo para dar vuelta)?"""
        if self._face_up_opts(only_playable=True):
            return True
        if declared is not None and self._ninjutsu_opts(declared):
            return True
        return any((("instant" in c.types) or ("flash" in c.keywords))
                   and c.cost is not None and hu.can_pay(self.g.effective_cost(hu, c)) for c in hu.hand)

    def _has_counter_response(self, hu):
        """¿El humano tiene un contrahechizo (apunta a la pila) que pueda pagar?"""
        return any(getattr(c, "target_spec", None) == "stack_spell"
                   and c.cost is not None and hu.can_pay(self.g.effective_cost(hu, c)) for c in hu.hand)

    def _affects_human(self, hu, top=None):
        """¿El objeto en el tope de la pila afecta al humano? Le apunta a él o a un
        permanente que controla, o es un barrido (destruye/exilia a todos)."""
        if top is None:
            top = self.g.stack[-1] if self.g.stack else None
        if top is None:
            return False
        for t in (top.targets or []):
            if t is hu:                              # le apunta a él
                return True
            if getattr(t, "controller", None) is hu:  # apunta a un permanente suyo
                return True
        # barridos y "cada oponente…": lo afectan sin apuntarle explícitamente
        return "wipe" in (getattr(top.source, "tags", set()) or set())

    def react(self, action=None, i=None, uid=None, index=0, target_uids=None):
        """El humano responde a un hechizo del rival (o pasa) y se reanuda el
        turno del bot. action: 'cast' (instantáneo de la mano) | 'ability' |
        'gy_ability' | None (pasar)."""
        if self.mode != "react" or not self._react_ctx:
            return self.state()
        ctx = self._react_ctx
        self._react_ctx = None
        self.mode = None
        self.phase = "waiting"
        hu = self.human()
        if action == "cast" and i is not None and 0 <= i < len(hu.hand):
            c = hu.hand[i]
            if (("instant" in c.types) or ("flash" in c.keywords)) and hu.can_pay(self.g.effective_cost(hu, c)):
                spec = getattr(c, "target_spec", None)
                if spec == "stack_spell":
                    tgt = [ctx["spell"]]                 # contrahechizo: apunta a la pila
                else:
                    tgt = self._chosen_targets(c, target_uids, spec=spec) if spec else None
                self.g.cast(hu, c, targets=tgt)
        elif action == "ability" and uid is not None:
            pm = self._find_perm(uid)
            if pm is not None:
                ab = (getattr(pm.card, "activated_abilities", ()) or (None,))[index] \
                    if index < len(getattr(pm.card, "activated_abilities", ()) or ()) else None
                # copiar habilidad: apuntar a la habilidad concreta del rival en la pila
                tgt = [ctx["spell"]] if (ab and ab.get("is_copy_ability")
                                         and getattr(ctx.get("spell"), "kind", None)
                                         in ("ability", "trigger")) else None
                self.g.activate_ability(pm, index, targets=tgt)
        elif action == "gy_ability" and i is not None and 0 <= i < len(hu.graveyard):
            self.g.activate_gy_ability(hu, hu.graveyard[i], index)
        # vaciar la pila (respuesta + hechizo original) con prioridad de todos
        self.g._run_priority_and_resolve()
        self.g.sba()
        if len(self.g.alive()) <= 1:
            self._finish()
            return self.state()
        # reanudar el turno del bot desde donde quedó
        if self._ai_steps(ctx["p"], ctx["step"]):
            return self.state()          # volvió a pausar (otra reacción o defensa)
        self._advance_to_human()
        return self.state()

    def _ai_combat(self, p):
        self.g._begin_combat(p)
        if not self.g.opponents(p):
            return False
        attackers = p.policy.declare_attackers(self.g, p) if p.policy else []
        declared = self.g._declare_attackers(p, attackers)
        if not declared:
            return False
        me = self.human()
        incoming = [a for a in declared if self.g._def_player(a) is me]
        if incoming and not me.lost:
            self._attacker = p
            self._declared = declared
            self.mode = "defense"
            self.phase = "defense"
            return True
        for d in self.g.opponents(p):
            self.g._ai_block(d, declared)
        self.g._finish_combat(declared)
        self.g.sba()
        return False

    # -- acciones de defensa (respuesta a un ataque) --------------------- #
    def _defense_incoming(self):
        me = self.human()
        return [a for a in self._declared
                if a in a.controller.battlefield and self.g._def_player(a) is me]

    def _auto_targets_def(self, card):
        ts = getattr(card, "target_spec", None)
        if ts == "opp_creature":
            n = max(1, getattr(card, "target_count", 1))
            legal = [a for a in self._defense_incoming()
                     if self.g.can_target(self.human(), a)]
            legal.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            return legal[:n]
        return self._auto_targets(card)

    def respond(self, i, target_uids=None, mode=None):
        """Lanza un instantáneo / carta con destello desde la mano en una ventana de
        combate (defensa antes de bloquear, o el paso de daño tras los bloqueos)."""
        if self.mode not in ("defense", "combat"):
            return self.state()
        me = self.human()
        if 0 <= i < len(me.hand):
            c = me.hand[i]
            fast = ("instant" in c.types) or ("flash" in c.keywords)
            if fast and c.cost is not None and me.can_pay(self.g.effective_cost(me, c)):
                modes = getattr(c, "modes", ())
                chosen = spec = None
                if modes and mode is not None and 0 <= mode < len(modes):
                    chosen = [mode]
                    spec = modes[mode].get("target_spec")
                tgt = (self._chosen_targets(c, target_uids, spec=spec)
                       if target_uids else self._auto_targets_def(c))
                self.g.cast(me, c, targets=tgt, chosen_modes=chosen)
                self.g.sba()
                if len(self.g.alive()) <= 1:
                    self.mode = None
                    self._finish()
        return self.state()

    def resolve_defense(self, pairs=None):
        """Aplica los bloqueos elegidos (pairs: [{attacker,blocker}]) y el daño;
        después completa el turno del atacante y sigue."""
        if self.mode != "defense":
            return self.state()
        me = self.human()
        p = self._attacker
        declared = [a for a in self._declared if a in a.controller.battlefield]
        incoming = [a for a in declared if self.g._def_player(a) is me]
        amap = {a.uid: a for a in incoming}
        bmap = {pm.uid: pm for pm in me.creatures()}
        human_pairs = []
        for pr in (pairs or []):
            a = amap.get(pr.get("attacker"))
            b = bmap.get(pr.get("blocker"))
            if a is not None and b is not None:
                human_pairs.append((a, b))
        self.g._apply_block_pairs(incoming, human_pairs)
        for d in self.g.opponents(p):
            if d is me:
                continue
            self.g._ai_block(d, declared)
        self.g.sba()
        if len(self.g.alive()) <= 1:
            self.mode = None
            self._finish()
            return self.state()
        # bloqueos declarados: se abre el PASO DE DAÑO, donde el humano puede lanzar
        # trucos antes de que se resuelva el daño (regla: prioridad tras bloquear).
        return self._enter_combat_damage(declared,
                                         resume=lambda: self._resume_after_defense(p))

    def _resume_after_defense(self, p):
        """Tras aplicar el daño del combate en un turno rival: completa el turno del
        atacante (main 2 + fin), reanudable por reacción."""
        self._declared = []
        if self._ai_steps(p, "main2"):
            return self.state()
        self._advance_to_human()
        return self.state()

    def _enter_combat_damage(self, declared, resume):
        """Abre la ventana de daño de combate (post-bloqueo): el humano puede lanzar
        instantáneos y luego pulsar 'Aplicar daño' (finish_combat). Si no tiene ningún
        instantáneo pagable, no hay nada que responder: aplica el daño directo."""
        # salimos del modo de declaración (defense/None): a partir de acá o abrimos
        # la ventana "combat" o resolvemos el daño de una.
        self.mode = None
        self._declared = []
        if not self._has_instant_response(self.human(), declared):
            self.g._finish_combat([a for a in declared if a in a.controller.battlefield])
            self.g.sba()
            if len(self.g.alive()) <= 1:
                self._finish()
                return self.state()
            return resume()
        self._combat_declared = declared
        self._combat_resume = resume
        self.mode = "combat"
        self.phase = "combat"
        return self.state()

    def finish_combat(self):
        """Aplica el daño de combate tras la ventana post-bloqueo y sigue."""
        if self.mode != "combat":
            return self.state()
        declared = [a for a in self._combat_declared
                    if a in a.controller.battlefield]
        resume = self._combat_resume
        self._combat_declared = []
        self._combat_resume = None
        self.mode = None
        self.g._finish_combat(declared)
        self.g.sba()
        if len(self.g.alive()) <= 1:
            self._finish()
            return self.state()
        if resume is not None:
            return resume()
        self._advance_to_human()
        return self.state()

    def _my_turn(self):
        return self.phase == "main" and self.g.active_index == self.human_index

    def _find_perm(self, uid):
        for pm in self.human().battlefield:
            if pm.uid == uid:
                return pm
        return None

    def _find_any_perm(self, uid):
        """Busca un permanente en CUALQUIER campo (p. ej. un planeswalker rival)."""
        for pl in self.players:
            for pm in pl.battlefield:
                if pm.uid == uid:
                    return pm
        return None

    # specs de permanente por tipo: el humano elige entre TODOS los que coincidan
    # (de cualquier jugador). Predicado sobre un Permanent.
    _PERM_SPECS = {
        "any_artifact": lambda pm: "artifact" in pm.card.types,
        "any_enchantment": lambda pm: "enchantment" in pm.card.types,
        "any_art_ench": lambda pm: bool({"artifact", "enchantment"} & pm.card.types),
        "any_planeswalker": lambda pm: "planeswalker" in pm.card.types,
        "any_nonland": lambda pm: not pm.card.is_land(),
        "any_perm": lambda pm: True,
    }

    def _perm_pool(self, pred):
        """Permanentes de cualquier jugador que cumplen `pred` y son objetivo legal."""
        me = self.human()
        out = []
        for pl in self.players:
            for pm in pl.battlefield:
                if pred(pm) and self.g.can_target(me, pm):
                    out.append(pm)
        return out

    def _auto_targets(self, card):
        """Objetivo(s) automático(s) (fallback si el humano no elige)."""
        p = self.human()
        ts = getattr(card, "target_spec", None)
        n = max(1, getattr(card, "target_count", 1))
        if ts == "own_creature":
            mine = list(p.creatures())
            mine.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            return mine[:n]
        if ts == "opp_creature":
            pool = self.g.legal_creature_targets(p)
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            return pool[:n]
        if ts == "opp_player":
            opps = self.g.opponents(p)
            return [min(opps, key=lambda o: o.life)] if opps else []
        if ts == "own_perm":
            mine = [pm for pm in p.battlefield if pm.card.on_etb] or p.battlefield
            if not mine:
                return []
            return [max(mine, key=lambda x: (x.card.cost.cmc if x.card.cost else 0))]
        if ts in self._PERM_SPECS:
            # preferir permanentes del rival; el más caro primero
            pool = self._perm_pool(self._PERM_SPECS[ts])
            pool.sort(key=lambda pm: (pm.controller is not p,
                                      pm.card.cost.cmc if pm.card.cost else 0),
                      reverse=True)
            return pool[:n]
        if ts == "stack_spell":
            return [self.g.stack[-1]] if self.g.stack else []
        return None

    def _find_any_perm(self, uid):
        for pl in self.players:
            for pm in pl.battlefield:
                if pm.uid == uid:
                    return pm
        return None

    def _targets_for_spec(self, ts):
        """Objetivos legales que el humano puede elegir para un target_spec."""
        if ts == "own_creature":
            return [{"uid": pm.uid, "name": pm.name, "power": pm.power,
                     "toughness": pm.toughness, "from": "tuyo"}
                    for pm in self.human().creatures()]
        if ts == "opp_creature":
            return [{"uid": pm.uid, "name": pm.name, "power": pm.power,
                     "toughness": pm.toughness, "from": pm.controller.name}
                    for pm in self.g.legal_creature_targets(self.human())]
        if ts == "opp_player":
            return [{"idx": self.players.index(o), "name": o.name,
                     "from": f"{o.life} de vida"}
                    for o in self.g.opponents(self.human())]
        if ts == "own_perm":
            return [{"uid": pm.uid, "name": pm.name,
                     "power": pm.power if pm.is_creature() else None,
                     "toughness": pm.toughness if pm.is_creature() else None,
                     "from": "tuyo"}
                    for pm in self.human().battlefield]
        if ts in self._PERM_SPECS:
            return [{"uid": pm.uid, "name": pm.name,
                     "power": pm.power if pm.is_creature() else None,
                     "toughness": pm.toughness if pm.is_creature() else None,
                     "from": ("tuyo" if pm.controller is self.human()
                              else pm.controller.name)}
                    for pm in self._perm_pool(self._PERM_SPECS[ts])]
        if ts == "stack_spell":
            return [{"idx": k, "name": getattr(o.source, "name", "?")}
                    for k, o in enumerate(self.g.stack)]
        return []

    def _targets_for(self, card):
        return self._targets_for_spec(getattr(card, "target_spec", None))

    # specs que EXIGEN al menos un objetivo (si no hay, la carta no se puede jugar).
    _MUST_TARGET = {"own_creature", "opp_creature", "opp_player", "own_perm",
                    "stack_spell", "any_artifact", "any_enchantment", "any_art_ench",
                    "any_planeswalker", "any_nonland", "any_perm"}

    def _has_legal_target(self, card, precomputed=None):
        """False sólo si la carta EXIGE objetivo, no es modal y no hay ninguno legal.
        Los hechizos modales se evalúan por modo aparte (no se bloquean acá)."""
        if getattr(card, "modes", ()):
            return True
        ts = getattr(card, "target_spec", None)
        if ts not in self._MUST_TARGET or getattr(card, "target_count", 1) < 1:
            return True
        opts = precomputed if precomputed is not None else self._targets_for(card)
        return len(opts) > 0

    def _modes_for(self, card):
        """Modos de un hechizo modal para la UI: cada uno con sus objetivos legales."""
        modes = getattr(card, "modes", ()) or ()
        out = []
        for i, m in enumerate(modes):
            spec = m.get("target_spec")
            out.append({"i": i, "label": m.get("label", f"Modo {i + 1}"),
                        "target_spec": spec, "target_count": m.get("target_count", 1),
                        "targets": self._targets_for_spec(spec)})
        return out

    def _chosen_targets(self, card, target_uids, spec=None):
        """Traduce la elección del humano (lista de uids) a `targets` del motor.
        `spec` fuerza el target_spec (para el modo elegido de un modal)."""
        ts = spec if spec is not None else getattr(card, "target_spec", None)
        if ts is None:
            return []
        if not target_uids:
            return self._auto_targets(card)
        uids = target_uids if isinstance(target_uids, list) else [target_uids]
        if ts == "own_creature":
            out = []
            for uid in uids:
                pm = self._find_any_perm(uid)
                if pm is not None and pm.controller is self.human() and pm.card.is_creature():
                    out.append(pm)
            return out
        if ts == "opp_creature":
            out = []
            for uid in uids:
                pm = self._find_any_perm(uid)
                if pm is not None and self.g.can_target(self.human(), pm):
                    out.append(pm)
            return out
        if ts == "own_perm":
            out = []
            for uid in uids:
                pm = self._find_any_perm(uid)
                if pm is not None and pm.controller is self.human():
                    out.append(pm)
            return out
        if ts in self._PERM_SPECS:
            pred = self._PERM_SPECS[ts]
            out = []
            for uid in uids:
                pm = self._find_any_perm(uid)
                if pm is not None and pred(pm) and self.g.can_target(self.human(), pm):
                    out.append(pm)
            return out
        if ts == "opp_player":
            opps = self.g.opponents(self.human())
            out = []
            for uid in uids:
                if isinstance(uid, int) and 0 <= uid < len(self.players):
                    pl = self.players[uid]
                    if pl in opps:
                        out.append(pl)
            return out
        if ts == "stack_spell":
            return [self.g.stack[u] for u in uids if 0 <= u < len(self.g.stack)]
        return None

    def _cascade_choose(self, card, ctrl):
        """Hook de cascada: el humano eligió cascadear un hechizo con objetivo.
        Arma un pending_choice con los objetivos legales; al confirmar, resuelve
        el hechizo gratis contra el objetivo elegido y lo manda al cementerio.
        Si no hay objetivo legal, lo resuelve igual (auto) para no trabar el flujo."""
        spec = getattr(card, "target_spec", None)
        opts = self._targets_for_spec(spec)

        def _resolve(targets):
            if getattr(card, "on_cast_resolve", None):
                card.on_cast_resolve(self.g, ctrl, targets or [])
            ctrl.graveyard.append(card)

        if not opts:
            _resolve(self._auto_targets(card))
            return

        keys = [o.get("uid", o.get("idx")) for o in opts]
        options = []
        for i, o in enumerate(opts):
            extra = f" · {o['from']}" if o.get("from") else ""
            options.append({"i": i, "name": f"{o['name']}{extra}"})

        def _apply(idx):
            if idx is None or not (0 <= idx < len(keys)):
                tgts = self._auto_targets(card)
            else:
                tgts = self._chosen_targets(card, [keys[idx]], spec=spec)
            _resolve(tgts)

        self.g.pending_choice = {
            "kind": "cascade_target",
            "prompt": f"Cascada: elegí el objetivo de {card.name}",
            "options": options,
            "card": card.name,
            "allow_none": False,
            "_apply": _apply,
        }

    # -- acciones del humano --------------------------------------------- #
    def play_land(self, i):
        if not self._my_turn():
            return self.state()
        p = self.human()
        if 0 <= i < len(p.hand) and p.hand[i].is_land():
            self._snapshot()
            self.g.play_land(p, p.hand[i])
            self.g.resolve_stack()      # resolver landfall (incl. disparos desde cementerio)
            self.g.sba()
        return self.state()

    def cast(self, i=None, zone="hand", target_uids=None, mode=None):
        if not self._my_turn():
            return self.state()
        self._snapshot()
        p = self.human()
        card = from_command = None
        if zone == "impulse":   # jugar una carta exiliada por "impulse" este turno
            if i is not None and 0 <= i < len(p.impulse):
                c = p.impulse[i]
                ok = self.g.play_land(p, c) if c.is_land() else self.g.cast(p, c)
                if ok is not False and c in p.impulse:
                    p.impulse.remove(c)
                self.g.sba()
            return self.state()
        if zone == "evoke":       # lanzar una criatura por evoke (ETB + sacrificio)
            if i is not None and 0 <= i < len(p.hand):
                self.g.cast_evoke(p, p.hand[i])
            return self.state()
        if zone == "suspend":     # suspender una carta de la mano
            if i is not None and 0 <= i < len(p.hand):
                self.g.suspend_card(p, p.hand[i])
            return self.state()
        if zone in ("overload", "plot", "warp", "prototype", "emerge"):
            if i is not None and 0 <= i < len(p.hand):
                c = p.hand[i]
                if zone == "overload":
                    self.g.cast_overload(p, c)
                elif zone == "plot":
                    self.g.plot_card(p, c)
                elif zone == "warp":
                    tg = self._chosen_targets(c, target_uids) if c.target_spec else None
                    self.g.cast_warp(p, c, targets=tg)
                elif zone == "prototype":
                    self.g.cast_prototype(p, c)
                else:
                    self.g.cast_emerge(p, c)
                self.g.sba()
            return self.state()
        if zone == "face_down":   # morph/disguise: boca abajo por {3}
            if i is not None and 0 <= i < len(p.hand):
                self.g.cast_face_down(p, p.hand[i])
                self.g.sba()
            return self.state()
        if zone == "bestow":      # bestow: como Aura sobre una criatura propia
            if i is not None and 0 <= i < len(p.hand):
                c = p.hand[i]
                tg = self._chosen_targets(c, target_uids, spec="own_creature") or []
                if not tg:
                    mine = sorted(p.creatures(), key=lambda x: (x.power, x.toughness),
                                  reverse=True)
                    tg = mine[:1]
                if tg:
                    self.g.cast_bestow(p, c, tg[0])
                    self.g.sba()
            return self.state()
        if zone in ("dash", "blitz"):   # cast alternativo con prisa
            if i is not None and 0 <= i < len(p.hand):
                self.g.cast_alt_haste(p, p.hand[i], zone)
            return self.state()
        if zone == "cycle":       # ciclar una carta de la mano
            if i is not None and 0 <= i < len(p.hand):
                self.g.cycle_card(p, p.hand[i])
            return self.state()
        if zone == "adventure":   # lanzar la cara de aventura de una carta de la mano
            if i is not None and 0 <= i < len(p.hand):
                c = p.hand[i]
                spec = getattr(c, "adventure", {}).get("target_spec")
                tgts = self._chosen_targets(c, target_uids, spec=spec) if spec else None
                self.g.cast_adventure(p, c, targets=tgts)
            return self.state()
        if zone == "back":        # jugar la cara TRASERA de un DFC modal (mano)
            if i is not None and 0 <= i < len(p.hand):
                c = p.hand[i]
                bf = getattr(c, "back_face", None)
                spec = getattr(bf, "target_spec", None) if bf is not None else None
                chosen = None
                if bf is not None and getattr(bf, "modes", ()) and mode is not None:
                    idxs = mode if isinstance(mode, list) else [mode]
                    chosen = [m for m in idxs if 0 <= m < len(bf.modes)]
                    for m in chosen:
                        if bf.modes[m].get("target_spec"):
                            spec = bf.modes[m].get("target_spec")
                            break
                tgts = self._chosen_targets(bf, target_uids, spec=spec) if spec else None
                self.g.play_dfc_back(p, c, targets=tgts, chosen_modes=chosen)
                self.g.sba()
            return self.state()
        if zone == "graveyard":   # jugar/lanzar desde el CEMENTERIO (flashback, etc.)
            self._play_from_graveyard(p, i, target_uids, mode)
            return self.state()
        if zone == "exile":       # jugar desde el EXILIO persistente (foretell, etc.)
            self._play_from_exile(p, i, target_uids, mode)
            return self.state()
        if zone == "command":
            cand = [c for c in p.command if c.cost is None or
                    p.can_pay(Cost(c.cost.generic + p.tax_for(c), c.cost.pips))]
            if i is None and cand:
                card = cand[0]
            elif i is not None and 0 <= i < len(p.command):
                card = p.command[i]
            from_command = True
        else:
            if i is not None and 0 <= i < len(p.hand) and not p.hand[i].is_land():
                card = p.hand[i]
        if card is not None:
            modes = getattr(card, "modes", ())
            chosen = spec = None
            if modes and mode is not None:
                # `mode` puede ser un índice o una lista (cartas "choose two")
                idxs = mode if isinstance(mode, list) else [mode]
                chosen = [m for m in idxs if 0 <= m < len(modes)]
                # objetivo del primer modo elegido que pida uno
                for m in chosen:
                    if modes[m].get("target_spec"):
                        spec = modes[m].get("target_spec")
                        break
            # regla: un hechizo que EXIGE objetivo y no tiene ninguno legal no se
            # puede lanzar (evita "quemar" la carta sin efecto).
            if not self._has_legal_target(card):
                self.g.log(f"{card.name} no se puede lanzar: sin objetivos legales")
                if self._undo:
                    self._undo.pop()          # deshacer el snapshot (no pasó nada)
                return self.state()
            targets = self._chosen_targets(card, target_uids, spec=spec)
            if getattr(card, "x_spell", False):
                self._prompt_x(p, card, bool(from_command), targets, chosen)
            else:
                self.g.cast(p, card, from_command=bool(from_command),
                            targets=targets, chosen_modes=chosen)
                self.g.sba()
        return self.state()

    def _prompt_x(self, p, card, from_command, targets, chosen):
        """Deja que el HUMANO elija X (0..máximo pagable) antes de lanzar."""
        base = card.cost
        extra = p.tax_for(card) if from_command else 0
        red = getattr(card, "cost_reduction", 0) or 0
        base_cmc = max(0, (base.cmc if base else 0) + extra - red)
        xc = max(1, getattr(card, "x_count", 1))        # maná por cada punto de X
        maxx = min(20, max(0, (p.available_mana() - base_cmc) // xc))

        def _apply(idx):
            x = idx if idx is not None else 0
            self.g.cast(p, card, from_command=from_command, targets=targets,
                        chosen_modes=chosen, x_value=x)
            self.g.sba()

        self.g.pending_choice = {
            "kind": "x",
            "prompt": f"Elegí X para {card.name} (0 a {maxx}).",
            "options": [{"i": v, "name": f"X = {v}"} for v in range(maxx + 1)],
            "allow_none": False, "_apply": _apply,
        }

    def _play_from_graveyard(self, p, i, target_uids, mode):
        """Fase A: jugar una carta desde el cementerio (delega en el motor, que la
        comparte con los bots). Acá solo se resuelven modos/objetivos del humano."""
        if i is None or not (0 <= i < len(p.graveyard)):
            return
        c = p.graveyard[i]
        modes = getattr(c, "modes", ())
        chosen = spec = None
        if modes and mode is not None and 0 <= mode < len(modes):
            chosen = [mode]
            spec = modes[mode].get("target_spec")
        targets = self._chosen_targets(c, target_uids, spec=spec) if spec else None
        self.g.play_from_graveyard(p, c, targets=targets, chosen_modes=chosen)

    def _play_from_exile(self, p, i, target_uids, mode):
        """Fase B: lanzar desde el exilio persistente (delega en el motor)."""
        if i is None or not (0 <= i < len(p.exile_play)):
            return
        c = p.exile_play[i]
        modes = getattr(c, "modes", ())
        chosen = spec = None
        if modes and mode is not None and 0 <= mode < len(modes):
            chosen = [mode]
            spec = modes[mode].get("target_spec")
        targets = self._chosen_targets(c, target_uids, spec=spec) if spec else None
        self.g.play_from_exile(p, c, targets=targets, chosen_modes=chosen)

    def foretell(self, i):
        """Predice (foretell) una carta de la mano (delega en el motor)."""
        if not self._my_turn():
            return self.state()
        self._snapshot()
        p = self.human()
        if i is not None and 0 <= i < len(p.hand):
            self.g.foretell_card(p, p.hand[i])
        return self.state()

    def activate_gy(self, i, index=0, target_uids=None):
        """Fase C: activa una habilidad de una carta EN EL CEMENTERIO (delega)."""
        if not self._my_turn():
            return self.state()
        self._snapshot()
        p = self.human()
        if i is not None and 0 <= i < len(p.graveyard):
            self.g.activate_gy_ability(p, p.graveyard[i], index)
        return self.state()

    def attack(self, uids=None, target_index=None, assign=None, target_pw=None):
        """Declara atacantes. Con `assign` (lista de {uid, target, pw}) cada atacante
        puede ir contra un rival o planeswalker distinto. Si no, todos los `uids`
        atacan al rival `target_index` (o al planeswalker `target_pw`)."""
        if not self._my_turn() or self.attacked:
            return self.state()
        p = self.human()
        foes = self.g.opponents(p)
        if not foes:
            return self.state()

        def _foe(idx):
            if idx is not None:
                for f in foes:
                    if self.players.index(f) == int(idx):
                        return f
            return foes[0]

        def _target(idx, pw_uid):
            # un planeswalker rival tiene prioridad si se indicó su uid
            if pw_uid is not None:
                pm = self._find_any_perm(pw_uid)
                if (pm is not None and "planeswalker" in pm.card.types
                        and pm.controller in foes):
                    return pm
            return _foe(idx)

        self.g._begin_combat(p)
        chosen = []
        if assign:                       # asignación por atacante (multi-objetivo)
            for a in assign:
                pm = self._find_perm(a.get("uid"))
                if pm is not None and pm.can_attack():
                    chosen.append((pm, _target(a.get("target"), a.get("pw"))))
        else:
            target = _target(target_index, target_pw)
            for uid in (uids or []):
                pm = self._find_perm(uid)
                if pm is not None and pm.can_attack():
                    chosen.append((pm, target))
        self.attacked = True
        # atacar revela información (bloqueos del rival, daño): ya no se deshace
        self._undo = []
        declared = self.g._declare_attackers(p, chosen)
        self.g.sba()
        if not declared or len(self.g.alive()) <= 1:
            if len(self.g.alive()) <= 1:
                self._finish()
                return self.state()
            return self._after_human_combat(p)
        # los rivales bloquean; después se abre el PASO DE DAÑO para que el humano
        # pueda lanzar un truco antes de que se resuelva el daño.
        for defender in self.g.opponents(p):
            self.g._ai_block(defender, declared)
        self.g.sba()
        if len(self.g.alive()) <= 1:
            self._finish()
            return self.state()
        return self._enter_combat_damage(declared,
                                         resume=lambda: self._after_human_combat(p))

    def _after_human_combat(self, p):
        """Tras el daño del combate propio del humano: maneja combate adicional y
        deja al humano en su fase principal."""
        # fase de combate adicional (Aggravated Assault, etc.): permite atacar de nuevo
        if getattr(self.g, "extra_combats", 0) > 0 and len(self.g.alive()) > 1:
            self.g.extra_combats -= 1
            self.attacked = False
            self.g.log(f"{p.name}: podés atacar otra vez (combate adicional)")
        if len(self.g.alive()) <= 1:
            self._finish()
        self.phase = "main"
        return self.state()

    def activate(self, uid, index=0):
        """Activa una habilidad de lealtad de un planeswalker del humano."""
        if not self._my_turn():
            return self.state()
        pm = self._find_perm(uid)
        if pm is not None:
            self._snapshot()
            self.g.activate_loyalty(pm, int(index))
            self.g.sba()
            if len(self.g.alive()) <= 1:
                self._finish()
        return self.state()

    def end_turn(self):
        if not self._my_turn():
            return self.state()
        p = self.human()
        # descarte por mano (más de 7): lo elige EL HUMANO, no su IA
        if len(p.hand) > 7 and self.g.pending_choice is None:
            self._prompt_discard(p)
            return self.state()
        self._finish_end_turn(p)
        return self.state()

    def _prompt_discard(self, p):
        """Pide al humano qué carta descartar (una a una) hasta quedar en 7."""
        def _apply(idx):
            if idx is not None and 0 <= idx < len(p.hand):
                c = p.hand.pop(idx)
                p.graveyard.append(c)
                self.g.emit("to_graveyard", player=p, card=c)
                self.g.log(f"{p.name} descarta {c.name}")
            if len(p.hand) > 7:
                self._prompt_discard(p)      # seguir descartando
            else:
                self._finish_end_turn(p)
        extra = len(p.hand) - 7
        self.g.pending_choice = {
            "kind": "discard",
            "prompt": f"Tenés {len(p.hand)} cartas: descartá hasta quedar en 7 "
                      f"(faltan {extra}).",
            "options": [{"i": j, "name": c.name, "is_land": c.is_land()}
                        for j, c in enumerate(p.hand)],
            "allow_none": False, "_apply": _apply,
        }

    def _finish_end_turn(self, p):
        self._undo = []                 # no se puede deshacer entre turnos
        self.opp_turns = []             # empezar a capturar los turnos rivales de nuevo
        self.g.end_turn(p)
        self.g.sba()
        self._advance_to_human()

    # -- deshacer jugada (fase principal del humano) --------------------- #
    def _snapshot(self):
        """Guarda el estado ANTES de una acción mutadora, para poder deshacerla.
        Solo en la fase principal del humano y sin una decisión pendiente."""
        if (self.phase == "main" and self._my_turn()
                and self.g.pending_choice is None):
            # memo {self: self}: los hooks del motor (reaction_check,
            # cascade_target_hook) son métodos de ESTA capa; sin el memo, el
            # deepcopy copiaba el InteractiveGame entero con todos los snapshots
            # anteriores adentro (crecía exponencial) y, tras deshacer, los hooks
            # quedaban apuntando a una copia vieja (sin ventanas de reacción).
            self._undo.append((copy.deepcopy(self.g, {id(self): self}), self.attacked))
            if len(self._undo) > 25:
                self._undo.pop(0)

    def can_undo(self):
        return bool(self._undo) and self._my_turn()

    def undo(self):
        """Vuelve al estado previo a la última jugada del turno."""
        if not self._undo or not self._my_turn():
            return self.state()
        g, attacked = self._undo.pop()
        self.g = g
        self.players = self.g.players        # el deepcopy creó jugadores nuevos
        self.g.interactive_human = self.human()
        self.attacked = attacked
        return self.state()

    # -- estado serializable --------------------------------------------- #
    def legal(self):
        p = self.human()
        lands, casts, attackers, activatables = [], [], [], []
        impulse = []
        graveyard = []
        exile_play, foretell_hand, gy_abilities = [], [], []
        if self._my_turn():
            for i, c in enumerate(p.impulse):   # exiliadas por impulse, jugables hoy
                playable = (c.is_land() and p.lands_played < self.g.land_limit(p)) or \
                           (not c.is_land() and c.cost is not None and p.can_pay(self.g.effective_cost(p, c)))
                impulse.append({"i": i, "name": c.name, "cost": _cost_str(c),
                                "is_land": c.is_land(), "playable": playable})
            for i, c in enumerate(p.exile_play):   # exilio persistente (foretell, etc.)
                pc = getattr(c, "_play_cost", None) or c.cost
                playable = (c.is_land() and p.lands_played < self.g.land_limit(p)) or \
                           (not c.is_land() and (pc is None or p.can_pay(pc)))
                if getattr(c, "_plot_turn", None) == self.g.turn:
                    playable = False         # plot: en un turno posterior
                exile_play.append({"i": i, "name": c.name,
                                   "cost": _cost_str_cost(pc) if pc else "0",
                                   "is_land": c.is_land(), "playable": playable})
            for i, c in enumerate(p.hand):        # cartas que se pueden predecir (foretell)
                fc = getattr(c, "foretell", None)
                if fc is not None:
                    foretell_hand.append({"i": i, "name": c.name,
                                          "playable": p.can_pay(Cost(2, ()))})
            for i, c in enumerate(p.graveyard):   # habilidades activadas desde el cementerio
                for j, ab in enumerate(getattr(c, "gy_abilities", ()) or ()):
                    cost = ab.get("cost")
                    gy_abilities.append({"i": i, "index": j, "name": c.name,
                                         "label": ab.get("label", "Habilidad"),
                                         "cost": _cost_str_cost(cost) if cost else "0",
                                         "playable": cost is None or p.can_pay(cost)})
            for i, c in enumerate(p.graveyard):   # jugables desde el cementerio
                gp = getattr(c, "gy_play", None) or {}
                if not gp:
                    continue
                cost = gp.get("cost")
                playable = cost is None or p.can_pay(cost)
                if gp.get("mode") == "escape":
                    need = gp.get("exile_n", 0) or 0
                    playable = playable and (len(p.graveyard) - 1) >= need
                graveyard.append({"i": i, "name": c.name,
                                  "cost": _cost_str_cost(cost) if cost else "0",
                                  "mode": gp.get("mode"), "playable": playable})
            for i, c in enumerate(p.hand):
                if c.is_land():
                    if p.lands_played < self.g.land_limit(p):
                        lands.append({"i": i, "name": c.name})
                elif c.cost is not None and p.can_pay(self.g.effective_cost(p, c)):
                    tgts = self._targets_for(c)
                    entry = {"i": i, "name": c.name, "zone": "hand",
                             "cost": _cost_str(c),
                             "target_spec": getattr(c, "target_spec", None),
                             "target_count": getattr(c, "target_count", 1),
                             "targets": tgts,
                             "modes": self._modes_for(c),
                             "mode_pick": getattr(c, "mode_pick", 1)}
                    if not self._has_legal_target(c, tgts):
                        entry["castable"] = False
                        entry["reason"] = "Sin objetivos legales"
                    casts.append(entry)
                # Suspend: opción extra para suspender (se lanza gratis en N turnos).
                sus = getattr(c, "suspend", None)
                if sus and p.can_pay(sus["cost"]):
                    casts.append({
                        "i": i, "name": f"{c.name} (suspend {sus['n']})", "zone": "suspend",
                        "cost": _cost_str_cost(sus["cost"]), "target_spec": None,
                        "target_count": 1, "targets": [], "modes": [], "mode_pick": 1})
                # Evoke: opción extra para lanzar por evoke (ETB + sacrificio).
                ev = getattr(c, "evoke_cost", None)
                if ev and p.can_pay(ev):
                    casts.append({
                        "i": i, "name": f"{c.name} (evoke)", "zone": "evoke",
                        "cost": _cost_str_cost(ev), "target_spec": None,
                        "target_count": 1, "targets": [], "modes": [], "mode_pick": 1})
                # Dash / Blitz: cast alternativo con prisa.
                for _kw, _attr in (("dash", "dash_cost"), ("blitz", "blitz_cost")):
                    _co = getattr(c, _attr, None)
                    if _co and p.can_pay(_co):
                        casts.append({
                            "i": i, "name": f"{c.name} ({_kw})", "zone": _kw,
                            "cost": _cost_str_cost(_co), "target_spec": None,
                            "target_count": 1, "targets": [], "modes": [], "mode_pick": 1})
                # Morph / Megamorph / Disguise: lanzarla boca abajo por {3}.
                _fk = ("disguise" if getattr(c, "disguise_cost", None) is not None
                       else "morph" if getattr(c, "morph_cost", None) is not None else None)
                if _fk and p.can_pay(Cost(3, ())):
                    casts.append({
                        "i": i, "name": f"{c.name} (boca abajo, {_fk})", "zone": "face_down",
                        "cost": "{3}", "target_spec": None,
                        "target_count": 1, "targets": [], "modes": [], "mode_pick": 1})
                # Bestow: lanzarla como Aura sobre una criatura tuya.
                _bc = getattr(c, "bestow_cost", None)
                if _bc is not None and p.can_pay(_bc):
                    _bt = self._targets_for_spec("own_creature")
                    casts.append({
                        "i": i, "name": f"{c.name} (bestow, como Aura)", "zone": "bestow",
                        "cost": _cost_str_cost(_bc), "target_spec": "own_creature",
                        "target_count": 1, "targets": _bt, "modes": [], "mode_pick": 1,
                        **({} if _bt else {"castable": False,
                                           "reason": "Sin criaturas para encantar"})})
                # batch 2: overload / plot / warp / prototype / emerge
                for _z, _lbl, _co in (
                        ("overload", "sobrecarga", getattr(c, "overload_cost", None)),
                        ("plot", "plot: jugarla en otro turno gratis",
                         getattr(c, "plot_cost", None)),
                        ("warp", "warp", getattr(c, "warp_cost", None)),
                        ("prototype", "prototipo", (getattr(c, "prototype", None) or {}).get("cost"))):
                    if _co is not None and p.can_pay(_co):
                        _tg = self._targets_for(c) if _z == "warp" else []
                        casts.append({
                            "i": i, "name": f"{c.name} ({_lbl})", "zone": _z,
                            "cost": _cost_str_cost(_co),
                            "target_spec": getattr(c, "target_spec", None) if _z == "warp" else None,
                            "target_count": getattr(c, "target_count", 1), "targets": _tg,
                            "modes": [], "mode_pick": 1})
                _em = self.g.emerge_option(p, c) if getattr(c, "emerge_cost", None) else None
                if _em:
                    casts.append({
                        "i": i, "name": f"{c.name} (emerge: sacrificar {_em[0].name})",
                        "zone": "emerge", "cost": _cost_str_cost(_em[1]), "target_spec": None,
                        "target_count": 1, "targets": [], "modes": [], "mode_pick": 1})
                # Cycling: descartar por robar una carta.
                _cy = getattr(c, "cycling", None)
                if _cy and p.can_pay(_cy):
                    casts.append({
                        "i": i, "name": f"{c.name} (ciclar)", "zone": "cycle",
                        "cost": _cost_str_cost(_cy), "target_spec": None,
                        "target_count": 1, "targets": [], "modes": [], "mode_pick": 1})
                # Adventure: opción extra para lanzar la cara de aventura.
                adv = getattr(c, "adventure", None)
                if adv and p.can_pay(adv["cost"]):
                    aspec = adv.get("target_spec")
                    casts.append({
                        "i": i, "name": f"{c.name} — {adv['label']} (aventura)",
                        "zone": "adventure", "cost": _cost_str_cost(adv["cost"]),
                        "target_spec": aspec, "target_count": adv.get("target_count", 1),
                        "targets": self._targets_for_spec(aspec), "modes": [],
                        "mode_pick": 1})
                # Modal DFC: jugar la cara TRASERA desde la mano (tierra o hechizo
                # con su propio coste, p.ej. una Pathway o un DFC modal).
                bf = getattr(c, "back_face", None)
                if bf is not None and getattr(c, "dfc", None) == "modal":
                    if bf.is_land():
                        if p.lands_played < self.g.land_limit(p):
                            casts.append({
                                "i": i, "name": f"{bf.name} (dorso)", "zone": "back",
                                "cost": "tierra", "is_land": True, "target_spec": None,
                                "target_count": 1, "targets": [], "modes": [],
                                "mode_pick": 1})
                    elif bf.cost is not None and p.can_pay(bf.cost):
                        bspec = getattr(bf, "target_spec", None)
                        casts.append({
                            "i": i, "name": f"{bf.name} (dorso)", "zone": "back",
                            "cost": _cost_str(bf), "target_spec": bspec,
                            "target_count": getattr(bf, "target_count", 1),
                            "targets": self._targets_for(bf),
                            "modes": self._modes_for(bf),
                            "mode_pick": getattr(bf, "mode_pick", 1)})
            for c in p.command:
                pay = None if c.cost is None else Cost(c.cost.generic + p.tax_for(c),
                                                       c.cost.pips)
                if pay is None or p.can_pay(pay):
                    casts.append({"name": c.name, "zone": "command",
                                  "cost": _cost_str(c),
                                  "tax": p.tax_for(c)})
            if not self.attacked:
                for pm in p.creatures():
                    if pm.can_attack():
                        attackers.append({"uid": pm.uid, "name": pm.name,
                                          "power": pm.power, "toughness": pm.toughness,
                                          "keywords": sorted(pm.keywords)})
            for pm in p.battlefield:
                if ("planeswalker" in pm.card.types and not pm.activated_this_turn
                        and pm.card.loyalty_abilities):
                    texts = pm.card.loyalty_texts or ()
                    activatables.append({
                        "uid": pm.uid, "name": pm.name,
                        "loyalty": pm.counters.get("loyalty", 0),
                        "abilities": [{"i": i, "cost": cost,
                                       "text": texts[i] if i < len(texts) else ""}
                                      for i, (cost, _e) in enumerate(pm.card.loyalty_abilities)],
                    })
        # habilidades activadas con maná (creaturas/permanentes/tierras)
        abilities = []
        for pm in p.battlefield:
            abs_ = getattr(pm.card, "activated_abilities", ()) or ()
            usable = []
            for i, ab in enumerate(abs_):
                # las habilidades NO se descartan: se muestran deshabilitadas con
                # el motivo, así no "desaparecen" al usar otra (girar / gastar maná).
                reason = None
                lr = ab.get("level_req")
                if ab.get("prepared") and not getattr(pm, "_prepared", False):
                    reason = "ya usada"
                elif lr is not None and pm.counters.get("level", 1) != lr - 1:
                    reason = f"requiere nivel {lr - 1}"
                elif ab.get("tap") and pm.tapped:
                    reason = "girada"
                elif ab.get("tap") and _sick(pm):
                    reason = "recién invocada"
                elif not p.can_pay(ab.get("cost"), exclude={pm} if ab.get("tap") else None):
                    reason = "sin maná"
                elif not self.g.ability_allowed(pm, i, ab):
                    reason = ("ya usada" if ab.get("once") or ab.get("once_turn")
                              else "no atacó este turno" if ab.get("boast")
                              else "condición no cumplida")
                else:
                    reason = self._extra_cost_reason(p, pm, ab)
                spec = ab.get("target_spec")
                ab_tgts = self._targets_for_spec(spec)
                if (reason is None and spec in self._MUST_TARGET
                        and ab.get("target_count", 1) >= 1 and not ab_tgts):
                    reason = "sin objetivos legales"
                usable.append({"i": i, "label": ab.get("label", f"Habilidad {i + 1}"),
                               "cost": _cost_str_cost(ab.get("cost")), "tap": bool(ab.get("tap")),
                               "target_spec": spec, "target_count": ab.get("target_count", 1),
                               "targets": ab_tgts,
                               "playable": reason is None, "reason": reason})
            if usable:
                abilities.append({"uid": pm.uid, "name": pm.name, "abilities": usable})

        atk_targets = []
        if self._my_turn() and not self.attacked:
            for f in self.g.opponents(p):
                atk_targets.append({"index": self.players.index(f),
                                    "name": f.name, "life": f.life})
                # planeswalkers del rival: también son objetivo de ataque
                for pm in f.battlefield:
                    if "planeswalker" in pm.card.types:
                        atk_targets.append({
                            "index": self.players.index(f), "pw_uid": pm.uid,
                            "name": f"{pm.name} (PW de {f.name})",
                            "life": pm.counters.get("loyalty", 0)})
        return {"lands": lands, "casts": casts, "attackers": attackers,
                "face_up": self._face_up_opts(),
                "activatables": activatables, "abilities": abilities,
                "impulse": impulse,
                "graveyard": graveyard,
                "exile_play": exile_play,
                "foretell_hand": foretell_hand,
                "gy_abilities": gy_abilities,
                "attack_targets": atk_targets,
                "can_attack": self._my_turn() and not self.attacked,
                "can_undo": self.can_undo(),
                "can_end": self._my_turn(),
                "mana": p.available_mana(),
                "mana_sources": len(p.mana_sources())}

    def activate_ability(self, uid, index=0, target_uids=None, x=None):
        if not self._my_turn():
            return self.state()
        pm = self._find_perm(uid)
        if pm is None:
            return self.state()
        self._snapshot()
        abs_ = getattr(pm.card, "activated_abilities", ()) or ()
        ab = abs_[index] if 0 <= index < len(abs_) else None
        if ab is None:
            return self.state()
        spec = ab.get("target_spec")
        tgt = self._chosen_targets(pm.card, target_uids, spec=spec) if spec else None
        # habilidad con {X}: el humano elige X (0..máximo pagable) antes de activar.
        if ab.get("x_cost") and x is None:
            p = self.human()
            base = ab.get("cost").cmc if ab.get("cost") else 0
            maxx = min(20, max(0, p.available_mana() - base))

            def _apply(idx, _pm=pm, _i=index, _tg=tgt):
                self.g.activate_ability(_pm, _i, targets=_tg, x=(idx or 0))
                self.g.sba()

            self.g.pending_choice = {
                "kind": "x",
                "prompt": f"Elegí X para «{ab.get('label', '')}» (0 a {maxx}).",
                "options": [{"i": v, "name": f"X = {v}"} for v in range(maxx + 1)],
                "allow_none": False, "_apply": _apply,
            }
            return self.state()
        self.g.activate_ability(pm, index, targets=tgt, x=(x or 0))
        self.g.sba()
        return self.state()

    def export(self):
        """Relato COMPLETO de la partida + resumen, para descargar y analizar."""
        return {
            "players": [p.name for p in self.players],
            "human": self.players[self.human_index].name,
            "winner": self.winner,
            "turns": self.g.turn,
            "log": list(self.g.log_lines),
        }

    # -- boca abajo / ninjutsu (humano) ----------------------------------- #
    def _face_up_opts(self, only_playable=False):
        """Criaturas boca abajo del humano que puede dar vuelta (acción especial:
        en cualquier momento en que tenga prioridad)."""
        hu = self.human()
        out = []
        for pm in hu.battlefield:
            real = getattr(pm.card, "_real", None)
            if real is None or getattr(pm.card, "_bestow", False):
                continue
            cost = self.g.face_up_cost(pm)
            if cost is None:
                continue
            ok = hu.can_pay(cost)
            if only_playable and not ok:
                continue
            out.append({"uid": pm.uid, "name": real.name,
                        "cost": _cost_str_cost(cost), "playable": ok})
        return out

    def face_up(self, uid):
        """Dar vuelta una criatura boca abajo propia (en tu turno o en una ventana
        de combate)."""
        if not (self._my_turn() or self.mode in ("defense", "combat")):
            return self.state()
        pm = self._find_perm(uid)
        if pm is not None:
            self.g.turn_face_up(self.human(), pm)
            self.g.sba()
            if len(self.g.alive()) <= 1:
                self.mode = None
                self._finish()
        return self.state()

    def _ninjutsu_opts(self, declared=None):
        """Ninjutsu disponible en el paso de daño de TU ataque: cartas con ninjutsu
        pagables y atacantes tuyos sin bloquear que pueden volver a la mano."""
        if declared is None:
            if self.mode != "combat":
                return []
            declared = getattr(self, "_combat_declared", [])
        hu = self.human()
        declared = [a for a in declared if a in a.controller.battlefield]
        unb = self.g.unblocked_attackers(hu, declared)
        if not unb:
            return []
        out = []
        for c, zone in self.g.ninjutsu_options(hu, declared):
            src = hu.hand if zone == "hand" else hu.command
            out.append({"i": src.index(c), "zone": zone, "name": c.name,
                        "cost": _cost_str_cost(c.ninjutsu_cost),
                        "attackers": [{"uid": a.uid, "name": a.name,
                                       "power": a.power, "toughness": a.toughness}
                                      for a in unb]})
        return out

    def ninjutsu(self, i, zone="hand", attacker_uid=None):
        """Usa ninjutsu en el paso de daño de tu ataque."""
        if self.mode != "combat":
            return self.state()
        hu = self.human()
        src = hu.hand if zone == "hand" else hu.command
        if i is None or not (0 <= i < len(src)):
            return self.state()
        atk = self._find_perm(attacker_uid)
        if atk is None:
            return self.state()
        perm = self.g.ninjutsu(hu, src[i], atk, self._combat_declared)
        if perm is not None:
            self.g.sba()
        return self.state()

    def _defense_state(self):
        """Datos de la ventana de defensa: quién me ataca, con qué puedo bloquear
        y qué instantáneos puedo lanzar en respuesta."""
        me = self.human()
        incoming = self._defense_incoming()
        attackers = [{
            "uid": a.uid, "name": a.name, "power": a.power, "toughness": a.toughness,
            "commander": self.g.commander_owner(a.card) is not None,
            "from": a.controller.name,
            # a quién ataca: None = a tu vida; si no, el nombre del planeswalker tuyo
            # (un Permanent tiene .card; el jugador no).
            "vs_pw": (getattr(a.attacking, "name", None)
                      if hasattr(a.attacking, "card") else None),
            "flying": a.has("flying"),   # solo bloqueable con volar/alcance
        } for a in incoming]
        blockers = [{
            "uid": pm.uid, "name": pm.name, "power": pm.power, "toughness": pm.toughness,
            "can_block_flyers": pm.has("flying") or pm.has("reach"),
        } for pm in me.creatures() if not pm.tapped]
        responses = [{
            "i": i, "name": c.name, "cost": _cost_str(c),
            "target_spec": getattr(c, "target_spec", None),
            "target_count": getattr(c, "target_count", 1),
            "targets": self._targets_for(c),
            "modes": self._modes_for(c), "mode_pick": getattr(c, "mode_pick", 1),
        } for i, c in enumerate(me.hand)
            if (("instant" in c.types) or ("flash" in c.keywords))
            and c.cost is not None and me.can_pay(self.g.effective_cost(me, c))]
        return {
            "stage": "declare",
            "face_up": self._face_up_opts(),
            "from": self._attacker.name if self._attacker else "",
            "attackers": attackers,
            "blockers": blockers,
            "responses": responses,
            "abilities": self._instant_abilities(),        # activar habilidades ahora
            "gy_abilities": self._instant_gy_abilities(),
            "incoming_damage": sum(a["power"] for a in attackers),
        }

    def _instant_abilities(self):
        """Habilidades activadas de los permanentes del humano usables AHORA
        (pagables, sin girar las ya giradas). Para ventanas de respuesta/combate."""
        me = self.human()
        out = []
        for pm in me.battlefield:
            for j, ab in enumerate(getattr(pm.card, "activated_abilities", ()) or ()):
                if ab.get("sorcery_speed"):        # a velocidad de conjuro: no en combate
                    continue
                if ab.get("tap") and (pm.tapped or _sick(pm)):
                    continue
                if not me.can_pay(ab.get("cost"), exclude={pm} if ab.get("tap") else None):
                    continue
                spec = ab.get("target_spec")
                out.append({"uid": pm.uid, "name": pm.name, "index": j,
                            "label": ab.get("label", "Habilidad"),
                            "cost": _cost_str_cost(ab.get("cost")),
                            "target_spec": spec, "target_count": ab.get("target_count", 1),
                            "targets": self._targets_for_spec(spec) if spec else []})
        return out

    def _instant_gy_abilities(self):
        me = self.human()
        out = []
        for i, c in enumerate(me.graveyard):
            for j, ab in enumerate(getattr(c, "gy_abilities", ()) or ()):
                if ab.get("cost") is None or me.can_pay(ab.get("cost")):
                    out.append({"i": i, "index": j, "name": c.name,
                                "label": ab.get("label", "Habilidad"),
                                "cost": _cost_str_cost(ab.get("cost"))})
        return out

    def activate_in_combat(self, uid, index=0, target_uids=None):
        """Activa una habilidad de un permanente del humano DURANTE la defensa o el
        paso de daño (pump, hacer una ficha para bloquear, remoción activada…).
        Se queda en la misma ventana para que el humano siga o bloquee/aplique daño."""
        if self.mode not in ("defense", "combat"):
            return self.state()
        pm = next((p for p in self.human().battlefield if p.uid == uid), None)
        if pm is not None:
            abs_ = getattr(pm.card, "activated_abilities", ()) or ()
            spec = abs_[index].get("target_spec") if 0 <= index < len(abs_) else None
            tgt = (self._chosen_targets(pm.card, target_uids, spec=spec) if target_uids
                   else self._auto_targets(pm.card)) if spec else None
            self.g.activate_ability(pm, index, targets=tgt)
            self.g.sba()
            if len(self.g.alive()) <= 1:
                self.mode = None
                self._finish()
        return self.state()

    def activate_gy_in_combat(self, i, index=0, target_uids=None):
        """Activa una habilidad DESDE EL CEMENTERIO durante defensa/daño."""
        if self.mode not in ("defense", "combat"):
            return self.state()
        hu = self.human()
        if 0 <= i < len(hu.graveyard):
            self.g.activate_gy_ability(hu, hu.graveyard[i], index)
            self.g.sba()
        return self.state()

    def _combat_damage_state(self):
        """Datos del paso de daño (post-bloqueo): atacantes con sus bloqueadores y los
        instantáneos que el humano puede lanzar antes de que se resuelva el daño."""
        me = self.human()
        declared = [a for a in self._combat_declared
                    if a in a.controller.battlefield]
        attacking = bool(declared) and declared[0].controller is me
        atk = [{
            "uid": a.uid, "name": a.name, "power": a.power, "toughness": a.toughness,
            "from": a.controller.name,
            "vs_pw": (getattr(a.attacking, "name", None)
                      if hasattr(a.attacking, "card") else None),
            "blocked_by": [{"uid": b.uid, "name": b.name,
                            "power": b.power, "toughness": b.toughness}
                           for b in a.blocked_by],
        } for a in declared]
        responses = [{
            "i": i, "name": c.name, "cost": _cost_str(c),
            "target_spec": getattr(c, "target_spec", None),
            "target_count": getattr(c, "target_count", 1),
            "targets": self._targets_for(c),
            "modes": self._modes_for(c), "mode_pick": getattr(c, "mode_pick", 1),
        } for i, c in enumerate(me.hand)
            if (("instant" in c.types) or ("flash" in c.keywords))
            and c.cost is not None and me.can_pay(self.g.effective_cost(me, c))]
        return {
            "stage": "damage",
            "ninjutsu": self._ninjutsu_opts(),
            "face_up": self._face_up_opts(),
            "attacking": attacking,
            "from": "Vos" if attacking else (self._attacker.name if self._attacker else ""),
            "attackers": atk,
            "responses": responses,
            "abilities": self._instant_abilities(),
            "gy_abilities": self._instant_gy_abilities(),
            "can_finish": True,
        }

    def _react_state(self):
        """Datos de la ventana de reacción: qué hechizo lanzó el rival y con qué
        puede responder el humano (instantáneos, habilidades, del cementerio)."""
        me = self.human()
        ctx = self._react_ctx or {}
        spell = ctx.get("spell")
        src = getattr(spell, "source", None)
        responses = [{
            "i": i, "name": c.name, "cost": _cost_str(c),
            "target_spec": getattr(c, "target_spec", None),
            "target_count": getattr(c, "target_count", 1),
            "targets": self._targets_for(c),
        } for i, c in enumerate(me.hand)
            if (("instant" in c.types) or ("flash" in c.keywords))
            and c.cost is not None and me.can_pay(self.g.effective_cost(me, c))]
        # item 4: habilidades a velocidad de instante (permanentes y cementerio)
        abilities = []
        for pm in me.battlefield:
            for j, ab in enumerate(getattr(pm.card, "activated_abilities", ()) or ()):
                if ab.get("tap") and (pm.tapped or _sick(pm)):
                    continue
                if not me.can_pay(ab.get("cost"), exclude={pm} if ab.get("tap") else None):
                    continue
                abilities.append({"uid": pm.uid, "name": pm.name, "index": j,
                                  "label": ab.get("label", "Habilidad"),
                                  "cost": _cost_str_cost(ab.get("cost"))})
        gy_abilities = []
        for i, c in enumerate(me.graveyard):
            for j, ab in enumerate(getattr(c, "gy_abilities", ()) or ()):
                if ab.get("cost") is None or me.can_pay(ab.get("cost")):
                    gy_abilities.append({"i": i, "index": j, "name": c.name,
                                         "label": ab.get("label", "Habilidad"),
                                         "cost": _cost_str_cost(ab.get("cost"))})
        # etiqueta legible del objeto en la pila (hechizo o habilidad del rival)
        kind = getattr(spell, "kind", "spell")
        if kind in ("ability", "trigger"):
            label = f"habilidad de {getattr(src, 'name', '?')}"
        else:
            label = getattr(src, "name", "?")
        return {
            "spell": label,
            "kind": kind,
            "from": spell.controller.name if spell is not None else "",
            "responses": responses,
            "abilities": abilities,
            "gy_abilities": gy_abilities,
        }

    def state(self):
        # la partida termina EN CUANTO queda un solo jugador (antes, matar al último
        # rival en tu turno no terminaba hasta que tocabas "Terminar turno")
        if self.phase != "over":
            if any(not pl.lost and (pl.life <= 0 or pl.poison >= 10) for pl in self.players):
                self.g.sba()
            if len(self.g.alive()) <= 1:
                self._finish()
        players = []
        for i, pl in enumerate(self.players):
            s = self.g._player_state(pl)
            if i == self.human_index:
                for pm, ps in zip(pl.battlefield, s["battlefield"]):
                    real = getattr(pm.card, "_real", None)
                    if real is None:
                        continue
                    if getattr(pm.card, "_bestow", False):
                        ps["name"] = real.name
                        ps["abilities"] = ([f"Aura (bestow) sobre {pm.enchanting.name}"]
                                           if pm.enchanting else []) + list(ps["abilities"] or [])
                    else:
                        cost = self.g.face_up_cost(pm)
                        ps["face_down"] = real.name
                        ps["abilities"] = [f"Boca abajo: es {real.name}"] + (
                            [f"Darla vuelta: {_cost_str_cost(cost)}"] if cost else [])
                s["hand_cards"] = [{
                    "i": j, "name": c.name, "is_land": c.is_land(),
                    "is_creature": c.is_creature(), "cost": _cost_str(c),
                    "power": c.power if c.is_creature() else None,
                    "toughness": c.toughness if c.is_creature() else None,
                    "types": sorted(c.types),
                    "keywords": sorted(c.keywords),
                    "abilities": carddesc.describe(c),
                } for j, c in enumerate(pl.hand)]
            players.append(s)
        pending = self.g.pending_choice
        return {
            "turn": self.g.turn,
            "active": self.g.active_index,
            "human_index": self.human_index,
            "phase": "choose" if pending else self.phase,
            "attacked": self.attacked,
            "winner": self.winner,
            "players": players,
            "legal": self.legal(),
            "combat": (self._defense_state() if self.mode == "defense"
                       else self._combat_damage_state() if self.mode == "combat"
                       else None),
            "react": self._react_state() if self.mode == "react" else None,
            "choice": self._choice_state(),
            "mulligan": ({"mulls": self.mulls, "to_bottom": max(0, self.mulls - 1),
                          "lands": sum(1 for c in self.human().hand if c.is_land())}
                         if self.phase == "mulligan" else None),
            "log": self.g.log_lines[-30:],
            # resumen de los turnos rivales desde tu último turno (uno por rival)
            "opp_turns": self.opp_turns,
            # feed de habilidades activadas/disparadas (para avisar en pantalla)
            "ability_feed": self.g.ability_events[-10:],
            # datos (coste/tipo/P-T/keywords) de las cartas en cementerio/exilio/
            # comando, por nombre: así al revisar una carta del cementerio también se
            # ve cuánto maná cuesta (el motor manda solo el nombre de esas zonas).
            "card_briefs": self._zone_briefs(),
        }

    def _zone_briefs(self):
        """Mapa nombre -> resumen (coste, tipo, P/T, keywords) de las cartas en las
        zonas que al serializarse van solo como nombre (cementerio, exilio, comando,
        impulso). Permite que el modal de inspección muestre el coste de maná."""
        out = {}
        for pl in self.players:
            zones = (pl.graveyard, pl.exile,
                     getattr(pl, "exile_play", ()) or (),
                     getattr(pl, "impulse", ()) or (),
                     getattr(pl, "command", ()) or ())
            for zone in zones:
                for c in zone:
                    nm = getattr(c, "name", None)
                    if nm and nm not in out:
                        out[nm] = self._card_brief(c)
        return out

    def _card_brief(self, c):
        """Resumen de una carta para los modales de decisión (scry/revelar):
        coste, P/T, tipo y keywords, para no decidir a ciegas."""
        if c is None:
            return None
        types = sorted(getattr(c, "types", set()) or set())
        subs = list(getattr(c, "subtypes", ()) or ())
        type_line = " ".join(t.capitalize() for t in types)
        if subs:
            type_line += " — " + " ".join(s.capitalize() for s in subs)
        is_crea = c.is_creature()
        return {
            "name": c.name,
            "cost": _cost_str(c) if getattr(c, "cost", None) is not None else "",
            "pt": (f"{c.power}/{c.toughness}" if is_crea else None),
            "type": type_line,
            "keywords": sorted(getattr(c, "keywords", set()) or set()),
            "is_land": c.is_land(),
        }

    def _choice_state(self):
        pc = self.g.pending_choice
        if not pc:
            return None
        return {"kind": pc.get("kind"), "prompt": pc.get("prompt"),
                "options": pc.get("options", []),
                "allow_none": bool(pc.get("allow_none")),
                "card": pc.get("card"),
                "card_detail": self._card_brief(pc.get("card_obj"))}

    def resolve_choice(self, index=None):
        """El humano eligió una opción de una decisión pendiente (revelar, etc.)."""
        pc = self.g.pending_choice
        if not pc:
            return self.state()
        self.g.pending_choice = None
        apply = pc.get("_apply")
        if apply:
            apply(index)
        self.g.sba()
        if len(self.g.alive()) <= 1:
            self._finish()
            return self.state()
        # el _apply pudo encadenar otra sub-decisión (p. ej. descartar de a una)
        if self.g.pending_choice is not None:
            return self.state()
        # decisiones encoladas por efectos de un bot: mostrar la próxima
        if self._surface_queued_choice():
            return self.state()
        # si estábamos drenando decisiones durante el avance de turnos rivales,
        # reanudar el avance hasta el turno del humano
        if self._draining and self.mode is None:
            self._draining = False
            self._advance_to_human()
        return self.state()
