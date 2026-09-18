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
        self.phase = "waiting"      # waiting | main | over
        self.attacked = False
        self.winner = None
        self._advance_to_human()

    # -- helpers ---------------------------------------------------------- #
    def human(self):
        return self.players[self.human_index]

    def _finish(self):
        alive = self.g.alive()
        self.winner = alive[0].name if len(alive) == 1 else "EMPATE"
        self.phase = "over"

    def _advance_to_human(self):
        """Corre turnos rivales hasta que sea el turno del humano (o termine)."""
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
            self.g.run_turn()
            self.g.sba()

    def _my_turn(self):
        return self.phase == "main" and self.g.active_index == self.human_index

    def _find_perm(self, uid):
        for pm in self.human().battlefield:
            if pm.uid == uid:
                return pm
        return None

    def _auto_targets(self, card):
        """Objetivo automático para el MVP (después lo elige el humano)."""
        p = self.human()
        ts = getattr(card, "target_spec", None)
        if ts == "opp_creature":
            pool = self.g.legal_creature_targets(p)
            return [max(pool, key=lambda x: (x.power, x.toughness))] if pool else []
        if ts == "stack_spell":
            return [self.g.stack[-1]] if self.g.stack else []
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

    def cast(self, i=None, zone="hand"):
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
                        targets=self._auto_targets(card))
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
        lands, casts, attackers = [], [], []
        if self._my_turn():
            for i, c in enumerate(p.hand):
                if c.is_land():
                    if p.lands_played < 1:
                        lands.append({"i": i, "name": c.name})
                elif c.cost is not None and p.can_pay(c.cost):
                    casts.append({"i": i, "name": c.name, "zone": "hand",
                                  "cost": _cost_str(c)})
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
        return {"lands": lands, "casts": casts, "attackers": attackers,
                "can_attack": self._my_turn() and not self.attacked,
                "can_end": self._my_turn()}

    def state(self):
        players = []
        for i, pl in enumerate(self.players):
            s = self.g._player_state(pl)
            if i == self.human_index:
                s["hand_cards"] = [
                    {"i": j, "name": c.name, "is_land": c.is_land(),
                     "cost": _cost_str(c)} for j, c in enumerate(pl.hand)]
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
            "log": self.g.log_lines[-14:],
        }
