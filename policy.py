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
        # anthem: cuanto más criaturas tengas, más vale el bono estático
        if "anthem" in tags:
            s += 2 + len(me.creatures())
        # cascade: valor gratis extra al lanzarlo
        if "cascade" in tags:
            s += 3
        # relanzar desde el cementerio: bueno con cementerio cargado
        if "gy_recast" in tags:
            if sum(1 for c in me.graveyard if not c.is_land()) >= 2:
                s += 5
        # dobladores de #3 (fichas / daño / contadores): motores muy fuertes
        if getattr(card, "token_double", False) or getattr(card, "damage_double", None):
            s += 5
        if getattr(card, "counter_modifier", None) is not None and "creature" not in tags:
            s += 3
        if "creature" in tags:
            s += max(1, card.power)
            # las palabras clave suben el valor real de la criatura (evasión,
            # mortalidad, resiliencia), no solo la fuerza bruta.
            kw = getattr(card, "keywords", set()) or set()
            s += sum(1 for k in ("flying", "menace", "trample", "deathtouch",
                                 "lifelink", "double_strike", "vigilance",
                                 "hexproof", "indestructible", "unblockable") if k in kw)
            if "flying" in kw or "unblockable" in kw:
                s += 1                      # evasión pura vale un poco más
            s += max(0, (getattr(card, "toughness", 0) - 1)) // 3  # cuerpos resistentes
        return s

    # -- valuación de estado --------------------------------------------- #
    def board_eval(self, game, me) -> int:
        """Puntúa el estado desde la óptica de `me`: tu tablero + ventaja de cartas
        + vida, menos la mayor amenaza rival. Sirve para decidir con criterio de
        tablero, no solo por carta suelta."""
        def board_power(p):
            v = 0
            for pm in p.creatures():
                v += pm.power + pm.toughness
                for k in ("flying", "trample", "deathtouch", "double_strike",
                          "menace", "lifelink", "unblockable"):
                    if pm.has(k):
                        v += 2
            return v
        mine = board_power(me)
        opps = game.opponents(me)
        worst = max((board_power(o) for o in opps), default=0)
        return (mine - worst) + me.life // 3 + len(me.hand) * 2

    def _under_pressure(self, game, me) -> bool:
        """¿Estoy bajo presión? (poca vida o un tablero rival amenazante)."""
        if me.life <= 12:
            return True
        thr = max((sum(c.power for c in o.creatures())
                   for o in game.opponents(me)), default=0)
        return thr >= me.life * 0.5

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

        # 4) hechizos por prioridad. Secuenciación: primero por valor, y a igual
        # valor el más barato (entra más por turno: mejor uso del maná).
        reserve = 0 if nov else self._reserve_mana(game, me)
        spare_removal = sum(1 for c in me.hand
                            if "removal" in c.tags and c.cost is not None)
        pressured = False if nov else self._under_pressure(game, me)
        castables = self._castable_spells(game, me)
        castables.sort(key=lambda c: (self.score(game, me, c),
                                      -(c.cost.cmc if c.cost else 0)), reverse=True)
        if nov:
            # el novato no siempre juega la mejor secuencia
            game.rng.shuffle(castables)
        for card in castables:
            if card not in me.hand:
                continue
            # Cycling: si estoy inundado (>=6 tierras en juego) y la carta ciclable es
            # una tierra, la ciclo por una carta nueva (sin riesgo de tirar algo bueno).
            cy = getattr(card, "cycling", None)
            if (not nov and cy and card.is_land() and me.can_pay(cy)
                    and sum(1 for pm in me.battlefield if pm.card.is_land()) >= 6):
                game.cycle_card(me, card)
                continue
            if card.is_land():
                continue
            # Suspend: si puedo pagar el coste de suspend pero no el cuerpo completo,
            # la suspendo (se lanzará gratis en unos turnos).
            sus = getattr(card, "suspend", None)
            if (not nov and sus and me.can_pay(sus["cost"])
                    and not (card.cost and me.can_pay(card.cost))):
                game.suspend_card(me, card)
                continue
            # Dash / Ninjutsu / Blitz: si no puedo pagar el cuerpo completo pero sí un
            # coste alternativo, entro con prisa para presionar.
            for _mode, _at in (("dash", "dash_cost"), ("ninjutsu", "ninjutsu_cost"),
                               ("blitz", "blitz_cost")):
                _co = getattr(card, _at, None)
                if (not nov and _co and me.can_pay(_co)
                        and not (card.cost and me.can_pay(card.cost))):
                    game.cast_alt_haste(me, card, _mode)
                    break
            if card not in me.hand:
                continue
            # Evoke: si tiene ETB valioso y no puedo (o no quiero) pagar el cuerpo
            # completo pero sí el coste de evoke, la lanzo por evoke (ETB + sacrificio).
            ev = getattr(card, "evoke_cost", None)
            if (not nov and ev and card.on_etb and me.can_pay(ev)
                    and not (card.cost and me.can_pay(card.cost))):
                game.cast_evoke(me, card)
                continue
            # Adventure: si puedo pagar la aventura pero aún no la criatura, lanzo la
            # aventura por su valor (la criatura queda jugable desde el exilio).
            adv = getattr(card, "adventure", None)
            if (not nov and adv and me.can_pay(adv["cost"])
                    and not (card.cost and me.can_pay(card.cost))):
                atg = self._spec_targets(game, me, adv.get("target_spec"),
                                         adv.get("target_count", 1)) if adv.get("target_spec") else []
                if not (adv.get("target_spec") and not atg):
                    game.cast_adventure(me, card, targets=atg)
                    continue
            sc = self.score(game, me, card)
            if not second and sc <= 0 and not nov:
                continue
            # no malgastar remoción (incluye auras de mutación) si el rival no tiene
            # criaturas: no hay a qué apuntarla.
            if (not nov and "removal" in card.tags
                    and not any(o.creatures() for o in game.opponents(me))):
                continue
            # novato: a veces se olvida de jugar algo
            if nov and game.rng.random() < 0.22:
                continue
            chosen_modes = None
            if getattr(card, "modes", ()):
                chosen_modes = self._pick_modes(game, me, card)
                targets = []
                for mi in (chosen_modes or []):
                    sp = card.modes[mi].get("target_spec")
                    if sp:
                        targets += self._spec_targets(game, me, sp, 1)
            else:
                targets = self.choose_targets(game, me, card)
                if card.target_spec and not targets:
                    continue
                # contención de remoción: no gastar un removal dirigido en una
                # amenaza chica si no estoy presionado y no me sobra removal —
                # se guarda para un objetivo que valga la pena.
                if (not nov and "removal" in card.tags
                        and card.target_spec == "opp_creature" and targets
                        and not pressured and spare_removal <= 1
                        and self._threat_value(targets[0]) <= 3):
                    continue
            cmc = card.cost.cmc if card.cost else 0
            if reserve and me.available_mana() - cmc < reserve:
                continue
            if me.can_pay(card.cost):
                game.cast(me, card, targets=targets, chosen_modes=chosen_modes)

        # 5) las MISMAS jugadas fuera del campo que puede hacer el humano:
        # cementerio (flashback/unearth/embalm/recur), exilio (foretell), y las
        # habilidades activadas de permanentes en juego.
        self._use_extra_abilities(game, me, second)

        # planeswalkers
        self._activate_planeswalkers(game, me)

    # -- habilidades fuera del campo / activadas (bots) ------------------- #
    def _use_extra_abilities(self, game, me, second):
        if me.lost:
            return
        nov = self.level == "novato"
        if nov and game.rng.random() < 0.5:
            return                     # el novato a veces no las usa
        used = 0
        # jugar desde el cementerio (reanimar/flashback/unearth/embalm/recur)
        for c in list(me.graveyard):
            if used >= 3:
                break
            if getattr(c, "gy_play", None) and game.play_from_graveyard(me, c):
                used += 1
        # jugar lo predicho/exiliado jugable
        for c in list(me.exile_play):
            if used >= 3:
                break
            if game.play_from_exile(me, c):
                used += 1
        # habilidades activadas DESDE el cementerio
        for c in list(me.graveyard):
            if used >= 3:
                break
            for j, ab in enumerate(getattr(c, "gy_abilities", ()) or ()):
                if me.can_pay(ab.get("cost")) and game.activate_gy_ability(me, c, j):
                    used += 1
                    break
        # habilidades activadas de permanentes en el campo
        self._activate_perm_abilities(game, me, second)
        # foretell: predecir una carta cara que todavía no podemos lanzar
        if not second and not nov:
            self._maybe_foretell(game, me)

    def _activate_perm_abilities(self, game, me, second):
        used = 0
        # registro de permanentes ya usados este turno (si existe): evita que, al
        # reanudar la fase principal tras una ReactionPause, el bot re-active la
        # misma habilidad (refactor A, riesgo 2). En headless el atributo no existe
        # y no cambia nada.
        done = getattr(me, "_abil_perms_used", None)
        for perm in list(me.battlefield):
            if used >= 4:
                return
            if done is not None and perm.uid in done:
                continue
            for j, ab in enumerate(getattr(perm.card, "activated_abilities", ()) or ()):
                # "prepared" (mecánica Prepared): sólo mientras la criatura lo esté
                if ab.get("prepared") and not getattr(perm, "_prepared", False):
                    continue
                # no girar criaturas antes del combate (podrían atacar): las de {T}
                # solo se usan en la 2da main
                if ab.get("tap") and not second and perm.is_creature():
                    continue
                if ab.get("tap") and perm.tapped:
                    continue
                if not me.can_pay(ab.get("cost")):
                    continue
                # costes adicionales agresivos: se pagan solo cuando conviene, para
                # que el bot USE altares/aristócratas/loot sin autolesionarse.
                if not self._agg_cost_ok(me, perm, ab):
                    continue
                spec = ab.get("target_spec")
                tgt = self._spec_targets(game, me, spec, ab.get("target_count", 1))
                if spec and not tgt:
                    continue
                # habilidades {X}: elegir X = maná sobrante tras el coste base (tope
                # 10). Las que se auto-dañan (pegan a cada criatura/jugador) el bot las
                # evita para no barrerse su propio tablero.
                xv = 0
                if ab.get("x_cost"):
                    if ab.get("x_self_harm"):
                        continue
                    base = ab.get("cost").cmc if ab.get("cost") else 0
                    xv = min(10, max(0, me.available_mana() - base))
                    if xv < 1:
                        continue        # sin maná para X no aporta nada
                # marcar ANTES de activar: si la activación pausa (ReactionPause),
                # al reanudar este permanente ya queda descartado.
                if done is not None:
                    done.add(perm.uid)
                if game.activate_ability(perm, j, targets=tgt, x=xv):
                    used += 1
                    break              # una habilidad por permanente por turno

    def _agg_cost_ok(self, me, perm, ab):
        """¿Conviene pagar el coste adicional agresivo de una habilidad activada?
        - pagar vida: solo con colchón de vida.
        - descartar: solo con mano de sobra (descarta lo peor).
        - sacrificar OTRA: solo si hay 'carne' prescindible (ficha o cuerpo chico) y
          no es nuestra única criatura."""
        pay_life = ab.get("pay_life") or 0
        disc = ab.get("discard") or 0
        sac_o = ab.get("sacrifice_other")
        if pay_life and me.life - pay_life < 12:
            return False
        if disc and len(me.hand) < 4:
            return False
        if sac_o:
            creatures = me.creatures()
            fodder = [pm for pm in creatures
                      if pm is not perm and (pm.is_token or pm.power <= 1)]
            if not fodder or len(creatures) <= 1:
                return False
        return True

    def _pick_modes(self, game, me, card):
        """Elige qué modo(s) de una carta modal jugar (los bots ya no van siempre
        al modo 0). Prefiere modos con objetivo válido; devuelve una lista de
        índices de tamaño `mode_pick`."""
        modes = getattr(card, "modes", ())
        if not modes:
            return None
        # Entwine: si puedo pagar base + entwine, elijo TODOS los modos.
        ent = getattr(card, "_entwine_cost", 0) or 0
        if ent and card.cost is not None:
            from engine import Cost
            if me.can_pay(Cost(card.cost.generic + ent, card.cost.pips)):
                return list(range(len(modes)))
        pick = max(1, getattr(card, "mode_pick", 1))
        scored = []
        for i, m in enumerate(modes):
            spec = m.get("target_spec")
            ok = True
            if spec == "opp_creature":
                ok = bool(game.legal_creature_targets(me))
            elif spec == "opp_player":
                ok = bool(game.opponents(me))
            scored.append((1 if ok else -1, i))
        scored.sort(reverse=True)
        return sorted(i for _s, i in scored[:pick])

    def _threat_value(self, perm):
        """Cuán peligrosa es una criatura rival como objetivo de remoción: cuerpo,
        evasión/keywords, y si es el comandante (matarlo es muy valioso)."""
        v = perm.power * 2 + perm.toughness
        for k in ("flying", "trample", "deathtouch", "double_strike", "menace",
                  "lifelink", "unblockable"):
            if perm.has(k):
                v += 3
        try:
            if perm.card is perm.controller.commander_card:
                v += 9              # el comandante es el objetivo de mayor valor
        except AttributeError:
            pass
        return v

    # predicados de los specs de permanente por tipo (destruir/exiliar/bounce)
    _PERM_SPEC_PRED = {
        "any_artifact": lambda pm: "artifact" in pm.card.types,
        "any_enchantment": lambda pm: "enchantment" in pm.card.types,
        "any_art_ench": lambda pm: bool({"artifact", "enchantment"} & pm.card.types),
        "any_planeswalker": lambda pm: "planeswalker" in pm.card.types,
        "any_nonland": lambda pm: not pm.card.is_land(),
        "any_perm": lambda pm: True,
    }

    def _perm_target_rank(self, pm):
        """Prioridad de un permanente rival como objetivo de remoción. Rankea por
        PELIGRO real, no solo por coste: una criatura chica pero con evasión/letal
        (o el comandante) pesa más que un artefacto caro inofensivo."""
        cmc = pm.card.cost.cmc if pm.card.cost else 0
        if pm.is_creature():
            return self._threat_value(pm) + cmc          # cuerpo + keywords + comandante
        if "planeswalker" in pm.card.types:
            loy = getattr(pm, "loyalty", 0) or 0
            return 12 + loy + cmc                         # los PW son amenazas serias
        return cmc * 2                                    # motores caros (artef./ench.)

    def _perm_spec_targets(self, game, me, spec, count):
        """Objetivos para un spec de permanente: los del RIVAL primero (el más
        PELIGROSO), y sólo si no hay, los propios. Legal-target aware."""
        pred = self._PERM_SPEC_PRED[spec]
        opp = []
        for pm in [p for pl in game.players for p in pl.battlefield]:
            if not pred(pm) or not game.can_target(me, pm):
                continue
            if pm.controller is not me:
                opp.append(pm)
        if not opp:                           # el bot no se destruye lo propio
            return []
        opp.sort(key=self._perm_target_rank, reverse=True)
        return opp[:max(1, count)]

    def _spec_targets(self, game, me, spec, count):
        if spec in self._PERM_SPEC_PRED:
            return self._perm_spec_targets(game, me, spec, count)
        if spec == "own_creature":
            mine = [c for c in me.creatures()]
            if not mine:
                return []
            mine.sort(key=lambda p: (p.power, p.toughness), reverse=True)
            return mine[:max(1, count)]
        if spec == "opp_creature":
            pool = game.legal_creature_targets(me)
            if not pool:
                return []
            pool.sort(key=lambda p: self._threat_value(p), reverse=True)
            return pool[:max(1, count)]
        if spec == "opp_player":
            opps = game.opponents(me)
            return [min(opps, key=lambda o: o.life)] if opps else []
        if spec == "own_perm":
            if not me.battlefield:
                return []
            return [max(me.battlefield,
                        key=lambda x: (x.card.cost.cmc if x.card.cost else 0))]
        return []

    def _maybe_foretell(self, game, me):
        for c in list(me.hand):
            if getattr(c, "foretell", None) is None:
                continue
            # solo si NO podemos lanzarla normal pero sí pagar el foretell {2}
            if not me.can_pay(c.cost) and me.can_pay(Cost(2, ())):
                game.foretell_card(me, c)
                return

    # -- planificacion de mana ------------------------------------------- #
    def _land_colors(self, card, me):
        if card.produces is None:
            return set()
        try:
            return set(card.produces(None, me) or {})
        except Exception:  # noqa: BLE001
            return set()

    def _play_land(self, game, me):
        # jugar hasta el límite del turno (1 + 'additional land' de Exploration/Azusa…)
        while me.lands_played < game.land_limit(me):
            lands = [c for c in me.hand if c.is_land()]
            if not lands:
                return
            if self.level == "novato":
                game.play_land(me, lands[0])
                continue
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
            if game.play_land(me, lands[0]) is False:
                return

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
        if spec in self._PERM_SPEC_PRED:
            return self._perm_spec_targets(game, me, spec,
                                           max(1, getattr(card, "target_count", 1)))
        if spec == "own_creature":
            mine = [c for c in me.creatures()]
            if not mine:
                return []
            n = max(1, getattr(card, "target_count", 1))
            mine.sort(key=lambda p: (p.power, p.toughness), reverse=True)
            return mine[:n]
        if spec == "opp_creature":
            pool = game.legal_creature_targets(me)
            if not pool:
                return []
            n = max(1, getattr(card, "target_count", 1))
            pool.sort(key=lambda p: self._threat_value(p), reverse=True)
            return pool[:n]           # las N más amenazantes (no solo las más grandes)
        if spec == "opp_player":
            opps = game.opponents(me)
            return [min(opps, key=lambda o: o.life)] if opps else []
        if spec == "own_perm":
            mine = [pm for pm in me.battlefield if pm.card.on_etb] or me.battlefield
            if not mine:
                return []
            return [max(mine, key=lambda x: (x.card.cost.cmc if x.card.cost else 0))]
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
        if getattr(top, "kind", "spell") != "spell":
            return False          # no se contrarrestan habilidades/disparos
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

    def respond_copy(self, game, me, top):
        """Copiar el PROPIO hechizo del tope con un Fork/Twincast si vale la pena."""
        if self.level == "novato":
            return False
        if getattr(top, "kind", "spell") != "spell":
            return False          # respond_copy solo copia HECHIZOS
        src = getattr(top, "source", None)
        if src is None or not hasattr(src, "types"):
            return False
        # no copiar counters ni otras copias (evita bucles y jugadas inútiles)
        if getattr(src, "target_spec", None) == "stack_spell" or (src.tags & {"counter"}):
            return False
        if not ({"instant", "sorcery"} & src.types):
            return False
        # solo hechizos "buenos" con efecto: remoción, dirigidos, motores, modales
        worth = bool(src.tags & {"removal", "targeted", "engine", "modal"}) \
            or (src.on_cast_resolve is not None and not (src.tags & {"wipe"}))
        if not worth:
            return False
        copier = next((c for c in me.hand
                       if getattr(c, "target_spec", None) == "stack_spell"
                       and "counter" not in c.tags
                       and getattr(c, "on_cast_resolve", None) is not None
                       and me.can_pay(c.cost)), None)
        if copier is None:
            return False
        game.cast(me, copier, targets=[top])
        return True

    def _ability_worth_copying(self, top):
        """Heurística: vale copiar una habilidad si es DIRIGIDA (remoción/quema/
        robo: tiene objetivos) o si su fuente tiene tags de motor/ramp/robo."""
        if getattr(top, "targets", None):
            return True
        src = getattr(top, "source", None)
        tags = getattr(src, "tags", set()) or set()
        return bool(tags & {"removal", "engine", "ramp", "draw"})

    def respond_ability(self, game, me, top):
        """A3: copiar la PROPIA habilidad del tope con un permanente 'copiar
        habilidad' (Strionic) si vale la pena. Una sola vez por habilidad."""
        if self.level == "novato":
            return False
        if getattr(top, "kind", "spell") not in ("ability", "trigger"):
            return False
        if getattr(top, "is_copy_ability", False) or getattr(top, "copied", False):
            return False
        if str(getattr(top, "label", "")).startswith("copy:"):
            return False
        if getattr(top, "controller", None) is not me:
            return False          # solo copiamos habilidades propias
        if not self._ability_worth_copying(top):
            return False
        for perm in list(me.battlefield):
            for j, ab in enumerate(getattr(perm.card, "activated_abilities", ()) or ()):
                if not ab.get("is_copy_ability"):
                    continue
                if ab.get("tap") and perm.tapped:
                    continue
                if not me.can_pay(ab.get("cost")):
                    continue
                top.copied = True     # marcar antes de activar (evita bucle)
                game.activate_ability(perm, j, targets=[top])
                return True
        return False

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

    def _attack_target(self, me, opps, atk_power):
        """A quién atacar en multijugador. No siempre al de menos vida (eso fijaba
        el foco en el jugador que recibía daño primero). Prioriza:
        1) rematar a un rival que probablemente puedo matar YA (menos vida primero);
        2) si no, el rival MÁS INDEFENSO (menos bloqueadores sin girar), y recién de
           desempate la vida más baja. Así un rival con el campo vacío se vuelve el
           objetivo natural en vez del jugador humano.
        El novato se mantiene simple (siempre al de menos vida)."""
        if self.level == "novato" or not opps:
            return min(opps, key=lambda o: o.life) if opps else None

        def defense(o):
            bl = [c for c in o.creatures() if not c.tapped and not getattr(c, "cant_block", False)]
            return len(bl), sum(max(1, c.toughness) for c in bl)

        # 1) remate: rivales a los que el daño que pasa (aprox) alcanza su vida
        killable = [o for o in opps if atk_power - defense(o)[1] >= o.life]
        if killable:
            return min(killable, key=lambda o: o.life)
        # 2) el más indefenso: menos bloqueadores -> menos capacidad de soak -> vida baja
        return min(opps, key=lambda o: (defense(o)[0], defense(o)[1], o.life))

    # -- ataque ----------------------------------------------------------- #
    def declare_attackers(self, game, me):
        opps = game.opponents(me)
        if not opps:
            return []
        # solo atacar con criaturas que hacen daño (>0): mandar una 0/x no aporta
        # y solo la expone a morir.
        forced = [p for p in me.creatures() if p.can_attack()
                  and (p.goaded or p.must_attack)]
        attackers = [p for p in me.creatures() if p.can_attack() and p.power > 0]
        for p in forced:               # goad/obligación: deben atacar aunque no convenga
            if p not in attackers:
                attackers.append(p)
        if not attackers:
            return []
        atk_power = sum(a.power for a in attackers)
        target = self._attack_target(me, opps, atk_power)
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
        sending = list(sending)
        # avanzado: no mandar una criatura a morir gratis (un bloqueador rival la
        # mata y sobrevive, y ella no mata a nadie), salvo obligación.
        if self.level == "avanzado":
            def dies_for_free(atk):
                for b in target.creatures():
                    if b.tapped:
                        continue
                    b_kills = b.power >= atk.toughness or (b.has("deathtouch") and b.power > 0)
                    b_survives = b.toughness > atk.power and not atk.has("deathtouch")
                    atk_kills = atk.power >= b.toughness or (atk.has("deathtouch") and atk.power > 0)
                    if b_kills and b_survives and not atk_kills:
                        return True
                return False
            sending = [a for a in sending if a in forced or not dies_for_free(a)]
        for p in forced:               # nunca dejar en casa a un atacante obligado
            if p not in sending:
                sending.append(p)

        # repartir los atacantes entre los rivales (no todos a uno): se satura al más
        # indefenso y el excedente derrama al siguiente. El novato sigue mandando todo
        # a un solo objetivo.
        if self.level == "novato" or len(opps) == 1:
            assign = {a.uid: target for a in sending}
        else:
            assign = self._distribute_attackers(me, sending, opps, atk_power)

        result = []
        local = {}                      # índice de atacantes por rival, para alternar
        for atk in sending:
            o = assign.get(atk.uid, target)
            o_pws = [perm for perm in o.battlefield if "planeswalker" in perm.card.types]
            k = local.get(id(o), 0)
            local[id(o)] = k + 1
            # alternar dentro de cada rival: parte del daño a su planeswalker (presión
            # mixta jugador/planeswalker) sin dejar al jugador sin recibir nada
            if o_pws and self.level != "novato" and k % 2 == 1:
                result.append((atk, o_pws[(k // 2) % len(o_pws)]))
            else:
                result.append((atk, o))
        return result

    def _distribute_attackers(self, me, sending, opps, atk_power):
        """Reparte los atacantes entre los rivales en vez de mandarlos todos a uno.
        - A un rival REMATABLE se le asignan los que hagan falta para cubrir su vida.
        - El resto se reparte con una CUOTA JUSTA por rival (≈ parejo), enrutando por
          el soak (resistencia de bloqueadores sin girar) para preferir dónde conecta.
        Así, con tablero amplio, se presiona a varios rivales y no solo al humano."""
        def defense(o):
            return sum(max(1, c.toughness) for c in o.creatures()
                       if not c.tapped and not getattr(c, "cant_block", False))

        def could_die(atk, o):
            # ¿algún bloqueador sin girar del rival mataría a este atacante?
            for b in o.creatures():
                if b.tapped or getattr(b, "cant_block", False):
                    continue
                bhas = getattr(b, "has", lambda _k: False)
                if b.power >= atk.toughness or (bhas("deathtouch") and b.power > 0):
                    return True
            return False

        killable = {id(o) for o in opps if atk_power - defense(o) >= o.life}
        order = sorted(opps, key=lambda o: (0 if id(o) in killable else 1,
                                            defense(o), o.life))
        soak = {id(o): defense(o) for o in opps}
        need = {id(o): o.life + defense(o) for o in opps}   # daño para asegurar letal
        count = {id(o): 0 for o in opps}
        committed = {id(o): 0 for o in opps}
        fair = max(1, -(-len(sending) // len(opps)))        # ceil: cuota pareja por rival
        assign = {}
        for atk in sorted(sending, key=lambda c: c.power, reverse=True):
            def key(o, atk=atk):
                # un rival queda 'saturado' al asegurar su remate (rematables) o al
                # llegar a su cuota pareja (no rematables); entonces desborda al próximo.
                # Pero nunca derrama a un rival donde el atacante moriría pudiendo pegar
                # gratis en otro: ese cambio desfavorable va último.
                if id(o) in killable:
                    satisfied = committed[id(o)] >= need[id(o)]
                else:
                    satisfied = count[id(o)] >= fair
                return (could_die(atk, o), satisfied,
                        max(0, soak[id(o)]), order.index(o))
            best = min(order, key=key)
            assign[atk.uid] = best
            count[id(best)] += 1
            committed[id(best)] += atk.power
            soak[id(best)] = max(0, soak[id(best)] - atk.power)
        return assign

    # -- bloqueo ---------------------------------------------------------- #
    def declare_blockers(self, game, me, incoming):
        blockers = [p for p in me.creatures() if not p.tapped and not p.cant_block]
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

        def kills(b, atk):    # ¿b mata a atk? deathtouch: con 1 alcanza
            return b.power >= atk.toughness or (b.has("deathtouch") and b.power > 0)

        def survives(b, atk):  # ¿b sobrevive al atacante? deathtouch: nunca
            return b.toughness > atk.power and not atk.has("deathtouch")

        result = []
        used = set()
        threats = sorted(incoming, key=lambda a: -a.power)
        lethal = life_incoming >= me.life
        # golpe serio aunque no letal: te saca >=1/3 de la vida, o te deja bajo (<=12)
        pressured = (life_incoming * 3 >= me.life) or (me.life - life_incoming <= 12)

        def expendable(b):
            # fichas y criaturas chiquitas: fodder ideal para chump/gang
            return b.is_token or (b.power <= 1 and not b.card.keywords)

        for atk in threats:
            avail = [b for b in blockers if b.uid not in used and can_block(b, atk)]
            need = 2 if atk.has("menace") else 1     # amenaza: hacen falta 2+
            if len(avail) < need:
                continue
            # 1) bloqueo GRATIS: mata al atacante y sobrevive (no pierdo pieza)
            safe = next((b for b in avail if kills(b, atk) and survives(b, atk)), None)
            if safe is not None and need == 1:
                result.append((atk, safe))
                used.add(safe.uid)
                continue
            big = atk.power >= 3 or atk.has("flying") or atk.has("trample")
            # 2) GANG para MATAR una amenaza grande, perdiendo lo mínimo (fodder primero).
            if big:
                pool = sorted(avail, key=lambda x: (not expendable(x), x.power))
                pick, dmg = [], 0
                for b in pool:
                    pick.append(b)
                    dmg += b.power
                    if len(pick) >= need and dmg >= atk.toughness:
                        break
                kills_it = dmg >= atk.toughness or any(x.has("deathtouch") and x.power > 0 for x in pick)
                # vale la pena si lo mata y solo arriesgamos fodder, o estamos presionados
                if kills_it and len(pick) >= need and (
                        all(expendable(b) or survives(b, atk) for b in pick) or pressured):
                    for b in pick:
                        result.append((atk, b))
                        used.add(b.uid)
                    continue
            # 3) CHUMP con fodder (tokens) ante una amenaza grande bajo presión/letal.
            #    con arrolladora, el chump no frena el derrame salvo que lo mate.
            if (lethal or pressured) and big:
                fodder = [b for b in avail if expendable(b)]
                chump = fodder[:need] if len(fodder) >= need else avail[:need]
                if len(chump) >= need and not (
                        atk.has("trample") and sum(b.power for b in chump) < atk.toughness):
                    for b in chump:
                        result.append((atk, b))
                        used.add(b.uid)
        return result
