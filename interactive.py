"""Partida interactiva: un humano vs el sistema (Fase 2).

Conduce un `Game` paso a paso. El humano maneja SU turno (jugar tierra, lanzar,
atacar, terminar); los oponentes juegan solos con su política. En los turnos
rivales, la política del humano resuelve bloqueos y respuestas automáticamente
(simplificación del MVP: el humano todavía no elige bloqueos).

Es Python puro y sin red: corre igual en un test headless y dentro de Pyodide
en el navegador. La capa web solo llama a estos métodos y dibuja `state()`.
"""
from __future__ import annotations

import run
import carddesc
from engine import Game, Cost


def from_registered(specs, human_index=0, seed=0, level="intermedio"):
    """Construye una partida interactiva desde decks REGISTRADOS (de ejemplo).
    `specs`: lista de {"key": <clave>, "name": <opcional>}. Lo usa la web
    (Pyodide) para no tener que armar los mazos en JS."""
    import decks
    defs = []
    for s in specs:
        key = s["key"] if isinstance(s, dict) else s
        name = s.get("name") if isinstance(s, dict) else None
        deck, cmd = decks.build(key)
        defs.append((name or cmd.name, deck, cmd))
    return InteractiveGame(defs, human_index=human_index, seed=seed, level=level)


def _cost_str(card):
    c = card.cost
    if c is None:
        return ""
    return (str(c.generic) if c.generic else "") + "".join(c.pips)


class InteractiveGame:
    def __init__(self, deck_defs, human_index=0, seed=0, level="intermedio",
                 max_turns=200):
        self.players = run.build_players_from_defs(deck_defs, level=level)
        self.n = len(self.players)
        self.human_index = max(0, min(int(human_index), self.n - 1))
        self.g = Game(self.players, seed=int(seed), max_turns=max_turns,
                      trace=False)
        self.phase = "waiting"      # waiting | main | defense | over
        self.attacked = False
        self.winner = None
        self.mode = None            # None | "defense"
        self._attacker = None       # jugador que ataca (durante defensa)
        self._declared = []         # atacantes declarados (Permanent)
        self._advance_to_human()

    # -- helpers ---------------------------------------------------------- #
    def human(self):
        return self.players[self.human_index]

    def _finish(self):
        alive = self.g.alive()
        self.winner = alive[0].name if len(alive) == 1 else "EMPATE"
        self.phase = "over"

    def _advance_to_human(self):
        """Corre turnos rivales hasta que sea el turno del humano, se pause por
        una defensa, o termine la partida."""
        while True:
            if len(self.g.alive()) <= 1 or self.g.turn >= self.g.max_turns:
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
                return
            if self._ai_turn(p):     # pausó porque me atacan
                return

    # -- turno rival, con pausa en mi defensa ---------------------------- #
    def _ai_turn(self, p):
        self.g.begin_turn(p)
        self.g.sba()
        if p.lost:
            return False
        if p.policy:
            p.policy.main_phase(self.g, p, second=False)
            self.g.resolve_stack()
        self.g.sba()
        if not p.lost and self.g.opponents(p):
            if self._ai_combat(p):
                return True
        self._ai_after_combat(p)
        return False

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

    def _ai_after_combat(self, p):
        self.g.sba()
        if not p.lost and p.policy:
            p.policy.main_phase(self.g, p, second=True)
            self.g.resolve_stack()
        self.g.sba()
        self.g.end_turn(p)
        self.g.sba()

    # -- acciones de defensa (respuesta a un ataque) --------------------- #
    def _defense_incoming(self):
        me = self.human()
        return [a for a in self._declared
                if a in a.controller.battlefield and self.g._def_player(a) is me]

    def _auto_targets_def(self, card):
        ts = getattr(card, "target_spec", None)
        if ts == "opp_creature":
            legal = [a for a in self._defense_incoming()
                     if self.g.can_target(self.human(), a)]
            return [max(legal, key=lambda x: (x.power, x.toughness))] if legal else []
        return self._auto_targets(card)

    def respond(self, i, target_uid=None):
        """Lanza un instantáneo / carta con destello desde la mano en defensa."""
        if self.mode != "defense":
            return self.state()
        me = self.human()
        if 0 <= i < len(me.hand):
            c = me.hand[i]
            fast = ("instant" in c.types) or ("flash" in c.keywords)
            if fast and c.cost is not None and me.can_pay(c.cost):
                tgt = (self._chosen_target(c, target_uid)
                       if target_uid is not None else self._auto_targets_def(c))
                self.g.cast(me, c, targets=tgt)
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
        self.g._finish_combat(declared)
        self.g.sba()
        self.mode = None
        self._declared = []
        if len(self.g.alive()) <= 1:
            self._finish()
            return self.state()
        self._ai_after_combat(p)
        self._advance_to_human()
        return self.state()

    def _my_turn(self):
        return self.phase == "main" and self.g.active_index == self.human_index

    def _find_perm(self, uid):
        for pm in self.human().battlefield:
            if pm.uid == uid:
                return pm
        return None

    def _auto_targets(self, card):
        """Objetivo automático (fallback si el humano no elige)."""
        p = self.human()
        ts = getattr(card, "target_spec", None)
        if ts == "opp_creature":
            pool = self.g.legal_creature_targets(p)
            return [max(pool, key=lambda x: (x.power, x.toughness))] if pool else []
        if ts == "stack_spell":
            return [self.g.stack[-1]] if self.g.stack else []
        return None

    def _find_any_perm(self, uid):
        for pl in self.players:
            for pm in pl.battlefield:
                if pm.uid == uid:
                    return pm
        return None

    def _targets_for(self, card):
        """Objetivos legales que el humano puede elegir para `card`."""
        ts = getattr(card, "target_spec", None)
        if ts == "opp_creature":
            return [{"uid": pm.uid, "name": pm.name, "power": pm.power,
                     "toughness": pm.toughness, "from": pm.controller.name}
                    for pm in self.g.legal_creature_targets(self.human())]
        if ts == "stack_spell":
            return [{"idx": k, "name": getattr(o.source, "name", "?")}
                    for k, o in enumerate(self.g.stack)]
        return []

    def _chosen_target(self, card, target_uid):
        """Traduce la elección del humano a la lista `targets` del motor."""
        ts = getattr(card, "target_spec", None)
        if target_uid is None:
            return self._auto_targets(card)
        if ts == "opp_creature":
            pm = self._find_any_perm(target_uid)
            return [pm] if (pm is not None and self.g.can_target(self.human(), pm)) else []
        if ts == "stack_spell":
            return [self.g.stack[target_uid]] if 0 <= target_uid < len(self.g.stack) else []
        return None

    # -- acciones del humano --------------------------------------------- #
    def play_land(self, i):
        if not self._my_turn():
            return self.state()
        p = self.human()
        if 0 <= i < len(p.hand) and p.hand[i].is_land():
            self.g.play_land(p, p.hand[i])
            self.g.sba()
        return self.state()

    def cast(self, i=None, zone="hand", target_uid=None):
        if not self._my_turn():
            return self.state()
        p = self.human()
        card = from_command = None
        if zone == "command":
            cand = [c for c in p.command if c.cost is None or
                    p.can_pay(Cost(c.cost.generic + p.cmdr_tax, c.cost.pips))]
            if i is None and cand:
                card = cand[0]
            elif i is not None and 0 <= i < len(p.command):
                card = p.command[i]
            from_command = True
        else:
            if i is not None and 0 <= i < len(p.hand) and not p.hand[i].is_land():
                card = p.hand[i]
        if card is not None:
            self.g.cast(p, card, from_command=bool(from_command),
                        targets=self._chosen_target(card, target_uid))
            self.g.sba()
        return self.state()

    def attack(self, uids):
        """Declara atacantes (todos contra el primer rival vivo, MVP)."""
        if not self._my_turn() or self.attacked:
            return self.state()
        p = self.human()
        foes = self.g.opponents(p)
        if not foes:
            return self.state()
        target = foes[0]
        self.g._begin_combat(p)
        chosen = []
        for uid in (uids or []):
            pm = self._find_perm(uid)
            if pm is not None and pm.can_attack():
                chosen.append((pm, target))
        self.g._resolve_combat(p, chosen)
        self.g.sba()
        self.attacked = True
        if len(self.g.alive()) <= 1:
            self._finish()
        return self.state()

    def activate(self, uid, index=0):
        """Activa una habilidad de lealtad de un planeswalker del humano."""
        if not self._my_turn():
            return self.state()
        pm = self._find_perm(uid)
        if pm is not None:
            self.g.activate_loyalty(pm, int(index))
            self.g.sba()
            if len(self.g.alive()) <= 1:
                self._finish()
        return self.state()

    def end_turn(self):
        if not self._my_turn():
            return self.state()
        p = self.human()
        self.g.end_turn(p)
        self.g.sba()
        self._advance_to_human()
        return self.state()

    # -- estado serializable --------------------------------------------- #
    def legal(self):
        p = self.human()
        lands, casts, attackers, activatables = [], [], [], []
        if self._my_turn():
            for i, c in enumerate(p.hand):
                if c.is_land():
                    if p.lands_played < 1:
                        lands.append({"i": i, "name": c.name})
                elif c.cost is not None and p.can_pay(c.cost):
                    casts.append({"i": i, "name": c.name, "zone": "hand",
                                  "cost": _cost_str(c),
                                  "target_spec": getattr(c, "target_spec", None),
                                  "targets": self._targets_for(c)})
            for c in p.command:
                pay = None if c.cost is None else Cost(c.cost.generic + p.cmdr_tax,
                                                       c.cost.pips)
                if pay is None or p.can_pay(pay):
                    casts.append({"name": c.name, "zone": "command",
                                  "cost": _cost_str(c),
                                  "tax": p.cmdr_tax})
            if not self.attacked:
                for pm in p.creatures():
                    if pm.can_attack():
                        attackers.append({"uid": pm.uid, "name": pm.name,
                                          "power": pm.power, "toughness": pm.toughness})
            for pm in p.battlefield:
                if ("planeswalker" in pm.card.types and not pm.activated_this_turn
                        and pm.card.loyalty_abilities):
                    activatables.append({
                        "uid": pm.uid, "name": pm.name,
                        "loyalty": pm.counters.get("loyalty", 0),
                        "abilities": [{"i": i, "cost": cost}
                                      for i, (cost, _e) in enumerate(pm.card.loyalty_abilities)],
                    })
        return {"lands": lands, "casts": casts, "attackers": attackers,
                "activatables": activatables,
                "can_attack": self._my_turn() and not self.attacked,
                "can_end": self._my_turn()}

    def _defense_state(self):
        """Datos de la ventana de defensa: quién me ataca, con qué puedo bloquear
        y qué instantáneos puedo lanzar en respuesta."""
        me = self.human()
        incoming = self._defense_incoming()
        attackers = [{
            "uid": a.uid, "name": a.name, "power": a.power, "toughness": a.toughness,
            "commander": a.card is a.controller.commander_card,
            "from": a.controller.name,
        } for a in incoming]
        blockers = [{
            "uid": pm.uid, "name": pm.name, "power": pm.power, "toughness": pm.toughness,
        } for pm in me.creatures() if not pm.tapped]
        responses = [{
            "i": i, "name": c.name, "cost": _cost_str(c),
            "target_spec": getattr(c, "target_spec", None),
            "targets": self._targets_for(c),
        } for i, c in enumerate(me.hand)
            if (("instant" in c.types) or ("flash" in c.keywords))
            and c.cost is not None and me.can_pay(c.cost)]
        return {
            "from": self._attacker.name if self._attacker else "",
            "attackers": attackers,
            "blockers": blockers,
            "responses": responses,
            "incoming_damage": sum(a["power"] for a in attackers),
        }

    def state(self):
        players = []
        for i, pl in enumerate(self.players):
            s = self.g._player_state(pl)
            if i == self.human_index:
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
        return {
            "turn": self.g.turn,
            "active": self.g.active_index,
            "human_index": self.human_index,
            "phase": self.phase,
            "attacked": self.attacked,
            "winner": self.winner,
            "players": players,
            "legal": self.legal(),
            "combat": self._defense_state() if self.mode == "defense" else None,
            "log": self.g.log_lines[-14:],
        }
