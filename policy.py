"""IA de juego. Decide que lanzar, con que atacar y como bloquear.

No conoce cartas concretas: puntua por `tags` (ver API.md).
"""
from __future__ import annotations

from engine import Cost


class Policy:
    # -- puntuacion de lanzamiento --------------------------------------- #
    def score(self, game, me, card) -> int:
        """Prioridad de lanzamiento segun los tags que lee la IA."""
        s = 0
        tags = card.tags
        opps = game.opponents(me)
        opp_creatures = any(o.creatures() for o in opps)

        if "engine" in tags:
            s += 5
        if "ramp" in tags:
            s += 4 if game.turn <= 4 else 1
        if "draw" in tags:
            s += 3
        if "removal" in tags and opp_creatures:
            s += 4
        if "wipe" in tags:
            # solo si un oponente tiene 3+ criaturas y mas que tu
            mine = len(me.creatures())
            if any(len(o.creatures()) >= 3 and len(o.creatures()) > mine for o in opps):
                s += 6
        if "creature" in tags:
            s += max(1, card.power)
        return s

    # -- fase principal --------------------------------------------------- #
    def main_phase(self, game, me, second: bool = False):
        # 1) jugar una tierra (la primera de la mano)
        if not second:
            land = next((c for c in me.hand if c.is_land()), None)
            if land is not None:
                game.play_land(me, land)

        # 2) lanzar el comandante si se puede pagar y no esta en mesa
        self._maybe_cast_commander(game, me)

        # 3) lanzar hechizos por prioridad mientras alcance el mana
        # P3.1: reservar mana si tengo un instantaneo de respuesta (counter) y
        # hay a quien responder. No tapeo por debajo de ese coste.
        reserve = self._reserve_mana(game, me)
        castables = self._castable_spells(game, me)
        # ordenar por score desc; en fase 2 tambien entran cartas sin tag util
        castables.sort(key=lambda c: self.score(game, me, c), reverse=True)
        for card in castables:
            if card not in me.hand:
                continue
            if card.is_land():
                continue
            sc = self.score(game, me, card)
            if not second and sc <= 0:
                continue  # sin tag util: esperar a fase 2
            targets = self.choose_targets(game, me, card)
            if card.target_spec and not targets:
                continue  # sin objetivo legal, no se puede lanzar
            cmc = card.cost.cmc if card.cost else 0
            if reserve and me.available_mana() - cmc < reserve:
                continue  # dejar mana para la respuesta
            if me.can_pay(card.cost):
                game.cast(me, card, targets=targets)

    def _reserve_mana(self, game, me):
        """Mana a reservar para respuestas: el coste del instantaneo reactivo
        mas barato en mano, si hay oponentes a quienes responder."""
        if not game.opponents(me):
            return 0
        reactive = [c for c in me.hand
                    if "counter" in c.tags and c.cost is not None]
        return min((c.cost.cmc for c in reactive), default=0)

        # 4) activar planeswalkers (P2.3): una habilidad por turno
        self._activate_planeswalkers(game, me)

    def choose_targets(self, game, me, card):
        """Elige objetivos legales segun el target_spec de la carta."""
        spec = getattr(card, "target_spec", None)
        if spec == "opp_creature":
            pool = game.legal_creature_targets(me)
            if not pool:
                return []
            return [max(pool, key=lambda p: (p.power, p.toughness))]
        return []

    def _activate_planeswalkers(self, game, me):
        for perm in list(me.battlefield):
            if "planeswalker" not in perm.card.types or perm.activated_this_turn:
                continue
            abils = perm.card.loyalty_abilities
            if not abils:
                continue
            loy = perm.counters.get("loyalty", 0)
            idx = 0  # por defecto la primera (normalmente el +)
            # usar el ultimate (coste negativo) si hay lealtad de sobra
            for i, (cost, _eff) in enumerate(abils):
                if cost < 0 and loy + cost >= 0 and loy >= 7:
                    idx = i
            game.activate_loyalty(perm, idx)

    def _maybe_cast_commander(self, game, me):
        on_field = any(p.card is me.commander_card for p in me.battlefield)
        if on_field:
            return
        cmd = me.commander_card
        if cmd not in me.command:
            return
        extra = me.cmdr_tax
        cost = cmd.cost
        if cost is None:
            return
        pay_cost = Cost(generic=cost.generic + extra, pips=cost.pips)
        if me.can_pay(pay_cost):
            game.cast(me, cmd, from_command=True)

    def _castable_spells(self, game, me) -> list:
        return [c for c in list(me.hand)
                if not c.is_land() and c.cost is not None]

    # -- respuesta con instantaneos (P2.1) -------------------------------- #
    def respond(self, game, me, top):
        """Ventana de prioridad: decide si lanzar un instantaneo en respuesta
        al tope de la pila. Hoy solo contrarresta hechizos amenazantes."""
        if getattr(top, "controller", None) is me:
            return False
        if str(getattr(top, "label", "")).startswith("trigger"):
            return False
        card = getattr(top, "source", None)
        if card is None or not hasattr(card, "types") or card.is_land():
            return False
        # solo vale la pena contrarrestar amenazas
        worth = bool(card.types & {"creature", "planeswalker"}) or \
            bool(card.tags & {"engine", "wipe", "removal"})
        if not worth:
            return False
        counter = next((c for c in me.hand
                        if "counter" in c.tags and me.can_pay(c.cost)), None)
        if counter is None:
            return False
        game.cast(me, counter, targets=[top])
        return True

    # -- mulligan (P2.5) -------------------------------------------------- #
    def should_mulligan(self, hand):
        """Mulligan con manos extremas: 0-1 o 6-7 tierras."""
        lands = sum(1 for c in hand if c.is_land())
        return lands <= 1 or lands >= 6

    # -- descarte --------------------------------------------------------- #
    def choose_discard(self, game, me):
        """Descarta la carta de MENOR puntuacion (prefiere tierras extra)."""
        extra_lands = [c for c in me.hand if c.is_land()]
        if len(me.lands()) >= 5 and extra_lands:
            return extra_lands[-1]
        return min(me.hand, key=lambda c: self.score(game, me, c))

    # -- ataque ----------------------------------------------------------- #
    def declare_attackers(self, game, me):
        opps = game.opponents(me)
        if not opps:
            return []
        attackers = [p for p in me.creatures() if p.can_attack()]
        if not attackers:
            return []
        # jugador con menos vidas como objetivo principal
        target = min(opps, key=lambda o: o.life)
        # planeswalkers rivales (amenazas a derribar)
        pws = [perm for o in opps for perm in o.battlefield
               if "planeswalker" in perm.card.types]

        # P3.2 conciencia multijugador: si OTRO rival (no el objetivo) tiene un
        # tablero amenazante, guardo bloqueadores en vez de atacar con todo.
        max_other = max((sum(c.power for c in o.creatures())
                         for o in opps if o is not target), default=0)
        # atacan los de mayor poder; se quedan de guardia los de mayor resistencia
        attackers.sort(key=lambda c: c.power, reverse=True)
        keep = 0
        if max_other >= me.life * 0.6:
            keep = max(1, len(attackers) // 3)
        sending = attackers[:len(attackers) - keep] if keep else attackers

        result = []
        pw_i = 0
        for i, atk in enumerate(sending):
            # manda ~la mitad de los atacantes a un planeswalker rival si existe
            if pws and i % 2 == 1:
                result.append((atk, pws[pw_i % len(pws)]))
                pw_i += 1
            else:
                result.append((atk, target))
        return result

    # -- bloqueo ---------------------------------------------------------- #
    def declare_blockers(self, game, me, incoming):
        """Bloquea para no morir: asigna bloqueadores a los atacantes mas
        grandes primero, evitando cambios claramente malos."""
        blockers = [p for p in me.creatures() if not p.tapped]
        result = []
        used = set()
        # ordenar atacantes por poder desc
        threats = sorted(incoming, key=lambda a: -a.power)
        for atk in threats:
            # bloqueador disponible que sobreviva o mate sin morir gratis
            best = None
            for b in blockers:
                if b.uid in used:
                    continue
                if atk.has("flying") and not (b.has("flying") or b.has("reach")):
                    continue
                best = b
                # preferir uno que mate al atacante y sobreviva
                if b.power >= atk.toughness and b.toughness > atk.power:
                    break
            # amenaza a la vida: solo cuenta el dano dirigido al JUGADOR
            # (los atacantes a un planeswalker no restan vida)
            life_incoming = sum(a.power for a in incoming if a.attacking is me)
            if best is not None and (life_incoming >= me.life or
                                     (best.power >= atk.toughness)):
                result.append((atk, best))
                used.add(best.uid)
        return result
