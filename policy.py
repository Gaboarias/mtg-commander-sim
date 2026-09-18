"""IA de juego. Decide que lanzar, con que atacar y como bloquear.

No conoce cartas concretas: puntua por `tags` (ver docs/API.md).

Tres niveles de habilidad (`level`):
  - "novato": tapea todo, no planea el mana, ataca con todo, bloquea mal,
    y a veces se saltea una jugada (misplay).
  - "intermedio": comportamiento equilibrado (el de referencia).
  - "avanzado": planea el mana (ramp primero, mejor tierra, rellena el sobrante),
    reserva mana para respuestas, bloquea y ataca con criterio.
"""
from __future__ import annotations

from engine import Cost

LEVELS = ("novato", "intermedio", "avanzado")


class Policy:
    def __init__(self, level: str = "intermedio"):
        self.level = level if level in LEVELS else "intermedio"

    # -- puntuacion de lanzamiento --------------------------------------- #
    def score(self, game, me, card) -> int:
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
            mine = len(me.creatures())
            if any(len(o.creatures()) >= 3 and len(o.creatures()) > mine for o in opps):
                s += 6
        if "creature" in tags:
            s += max(1, card.power)
        return s

    # -- fase principal --------------------------------------------------- #
    def main_phase(self, game, me, second: bool = False):
        adv = self.level == "avanzado"
        nov = self.level == "novato"

        # 1) jugar una tierra (avanzado/intermedio eligen mejor)
        if not second:
            self._play_land(game, me)

        # 2) avanzado: lanzar el ramp barato PRIMERO libera mana este mismo turno
        if adv and not second:
            self._cast_ramp_first(game, me)

        # 3) comandante
        self._maybe_cast_commander(game, me)

        # 4) hechizos por prioridad
        reserve = 0 if nov else self._reserve_mana(game, me)
        castables = self._castable_spells(game, me)
        castables.sort(key=lambda c: self.score(game, me, c), reverse=True)
        if nov:
            # el novato no siempre juega la mejor secuencia
            game.rng.shuffle(castables)
        for card in castables:
            if card not in me.hand or card.is_land():
                continue
            sc = self.score(game, me, card)
            if not second and sc <= 0 and not nov:
                continue
            # novato: a veces se olvida de jugar algo
            if nov and game.rng.random() < 0.22:
                continue
            targets = self.choose_targets(game, me, card)
            if card.target_spec and not targets:
                continue
            cmc = card.cost.cmc if card.cost else 0
            if reserve and me.available_mana() - cmc < reserve:
                continue
            if me.can_pay(card.cost):
                game.cast(me, card, targets=targets)

        # planeswalkers
        self._activate_planeswalkers(game, me)

    # -- planificacion de mana ------------------------------------------- #
    def _land_colors(self, card, me):
        if card.produces is None:
            return set()
        try:
            return set(card.produces(None, me) or {})
        except Exception:  # noqa: BLE001
            return set()

    def _play_land(self, game, me):
        lands = [c for c in me.hand if c.is_land()]
        if not lands:
            return
        if self.level == "novato":
            game.play_land(me, lands[0])
            return
        # colores que ya puedo producir
        have = set()
        for p in me.mana_sources():
            opts = p.card.produces(p, me) if p.card.produces else {}
            have |= set(opts or {})
        # preferir: agrega color nuevo, y entra sin tapear
        def key(c):
            adds_new = 1 if (self._land_colors(c, me) - have) else 0
            untapped = 0 if c.enters_tapped else 1
            return (adds_new, untapped)
        lands.sort(key=key, reverse=True)
        game.play_land(me, lands[0])

    def _cast_ramp_first(self, game, me):
        ramp = [c for c in me.hand
                if not c.is_land() and "ramp" in c.tags and c.cost is not None]
        ramp.sort(key=lambda c: c.cost.cmc)
        for card in ramp:
            if card in me.hand and me.can_pay(card.cost):
                game.cast(me, card)

    def _reserve_mana(self, game, me):
        if not game.opponents(me):
            return 0
        reactive = [c for c in me.hand
                    if "counter" in c.tags and c.cost is not None]
        return min((c.cost.cmc for c in reactive), default=0)

    def _maybe_cast_commander(self, game, me):
        on_field = any(p.card is me.commander_card for p in me.battlefield)
        if on_field:
            return
        cmd = me.commander_card
        if cmd not in me.command or cmd.cost is None:
            return
        pay_cost = Cost(generic=cmd.cost.generic + me.cmdr_tax, pips=cmd.cost.pips)
        if me.can_pay(pay_cost):
            game.cast(me, cmd, from_command=True)

    def _castable_spells(self, game, me):
        return [c for c in list(me.hand)
                if not c.is_land() and c.cost is not None]

    def choose_targets(self, game, me, card):
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
            idx = 0
            for i, (cost, _eff) in enumerate(abils):
                if cost < 0 and loy + cost >= 0 and loy >= 7:
                    idx = i
            game.activate_loyalty(perm, idx)

    # -- respuesta con instantaneos --------------------------------------- #
    def respond(self, game, me, top):
        if self.level == "novato":
            return False  # el novato no responde
        if getattr(top, "controller", None) is me:
            return False
        if str(getattr(top, "label", "")).startswith("trigger"):
            return False
        card = getattr(top, "source", None)
        if card is None or not hasattr(card, "types") or card.is_land():
            return False
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

    # -- mulligan --------------------------------------------------------- #
    def should_mulligan(self, hand, player=None):
        lands = sum(1 for c in hand if c.is_land())
        if self.level == "novato":
            return lands == 0            # el novato casi siempre se queda
        if lands <= 1:
            return True                  # mano trabada de mana: siempre mulligan
        # exceso de tierras: solo si el mazo NO es mayoritariamente tierras
        # (los decks inflados con relleno de basicas NO deben re-mulliganear a 4)
        if player is not None:
            cards = player.hand + player.library
            total = len(cards) or 1
            deck_lands = sum(1 for c in cards if c.is_land())
            return lands >= 6 and (deck_lands / total) < 0.5
        return lands >= 6

    # -- descarte --------------------------------------------------------- #
    def choose_discard(self, game, me):
        if self.level == "novato":
            return me.hand[-1]           # descarta la ultima, sin pensar
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
        target = min(opps, key=lambda o: o.life)
        pws = [perm for o in opps for perm in o.battlefield
               if "planeswalker" in perm.card.types]

        keep = 0
        if self.level != "novato":
            # no atacar con todo si un tercero amenaza (guardar bloqueadores)
            max_other = max((sum(c.power for c in o.creatures())
                             for o in opps if o is not target), default=0)
            attackers.sort(key=lambda c: c.power, reverse=True)
            if max_other >= me.life * 0.6:
                keep = max(1, len(attackers) // 3)
        sending = attackers[:len(attackers) - keep] if keep else attackers

        result = []
        pw_i = 0
        for i, atk in enumerate(sending):
            if pws and self.level != "novato" and i % 2 == 1:
                result.append((atk, pws[pw_i % len(pws)]))
                pw_i += 1
            else:
                result.append((atk, target))
        return result

    # -- bloqueo ---------------------------------------------------------- #
    def declare_blockers(self, game, me, incoming):
        blockers = [p for p in me.creatures() if not p.tapped]
        if not blockers:
            return []
        life_incoming = sum(a.power for a in incoming if a.attacking is me)

        if self.level == "novato":
            # solo bloquea si el dano al jugador seria letal, y sin criterio
            if life_incoming < me.life:
                return []
            result = []
            used = set()
            for atk in incoming:
                b = next((x for x in blockers if x.uid not in used), None)
                if b is None:
                    break
                used.add(b.uid)
                result.append((atk, b))
            return result

        def can_block(b, atk):
            return not (atk.has("flying") and not (b.has("flying") or b.has("reach")))

        result = []
        used = set()
        threats = sorted(incoming, key=lambda a: -a.power)
        lethal = life_incoming >= me.life
        for atk in threats:
            avail = [b for b in blockers if b.uid not in used and can_block(b, atk)]
            if not avail:
                continue
            # 1) bloqueo GRATIS: mata al atacante y sobrevive (no pierdo pieza)
            safe = next((b for b in avail
                         if b.power >= atk.toughness and b.toughness > atk.power), None)
            if safe is not None:
                result.append((atk, safe))
                used.add(safe.uid)
                continue
            # 2) solo bajo amenaza letal: chump/trade para no morir
            if lethal:
                b = max(avail, key=lambda x: x.toughness)
                result.append((atk, b))
                used.add(b.uid)
        return result
