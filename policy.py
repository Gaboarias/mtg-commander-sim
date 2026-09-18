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
            if me.can_pay(card.cost):
                game.cast(me, card, targets=targets)

    def choose_targets(self, game, me, card):
        """Elige objetivos legales segun el target_spec de la carta."""
        spec = getattr(card, "target_spec", None)
        if spec == "opp_creature":
            pool = game.legal_creature_targets(me)
            if not pool:
                return []
            return [max(pool, key=lambda p: (p.power, p.toughness))]
        return []

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
        # atacar al jugador con menos vidas
        target = min(opps, key=lambda o: o.life)
        result = []
        for perm in me.creatures():
            if perm.can_attack():
                result.append((perm, target))
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
            # bloquear solo si somos agresivos o si el dano acumulado nos mata
            total_incoming = sum(a.power for a in incoming)
            if best is not None and (total_incoming >= me.life or
                                     (best.power >= atk.toughness)):
                result.append((atk, best))
                used.add(best.uid)
        return result
