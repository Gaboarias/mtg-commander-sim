"""Resolucion de cartas por nombre.

- REGISTRY: cartas con EFECTO implementado (las de cards.py), indexadas por
  nombre. Si un deck importado contiene una de estas, usa la version real.
- build_card_from_data: construye una carta "vainilla pero con stats reales"
  (coste, tipos, P/T, keywords, colores) a partir de un dict tipo Scryfall.
  NO inventa datos: lo que no viene en `data` queda por defecto.

La descarga desde Scryfall vive en la capa de API (corre en Vercel). Aca todo
es puro y testeable sin red.
"""
from __future__ import annotations

import re

from engine import Card, Cost, parse_cost, W, U, B, R, G, C, KEYWORDS
import cards

# --------------------------------------------------------------------------- #
# Registro de cartas implementadas (nombre -> constructor)
# --------------------------------------------------------------------------- #

_IMPLEMENTED = [
    cards.Quintorius, cards.Hofri, cards.BagOfHolding, cards.FaithlessLooting,
    cards.SevinnesReclamation, cards.UnderworldBreach, cards.SunTitan,
    cards.KarmicGuide, cards.CronistaEspectral, cards.MerodeadorDeTumbas,
    cards.Managorger, cards.Kalonian, cards.HardenedScales,
    cards.SimicAscendancy, cards.BranchingEvolution,
    cards.Kang, cards.GrayMerchant, cards.GoForTheThroat, cards.NightsWhisper,
    cards.DamnationWipe,
    cards.SolRing, cards.ArcaneSignet, cards.CommandTower,
    cards.Counterspell, cards.QuintoriusPlaneswalker,
]


def _build_registry():
    reg = {}
    for ctor in _IMPLEMENTED:
        c = ctor()
        reg[_norm(c.name)] = ctor
    return reg


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


REGISTRY = _build_registry()


# --------------------------------------------------------------------------- #
# Conversion de datos tipo Scryfall -> Card
# --------------------------------------------------------------------------- #

_COLOR_MAP = {"W": W, "U": U, "B": B, "R": R, "G": G, "C": C}


def mana_cost_to_str(mana_cost: str) -> str:
    """'{2}{R}{W}' -> '2RW'. Ignora X (0) e hibridos (toma el primer simbolo)."""
    if not mana_cost:
        return "0"
    generic = 0
    pips = ""
    for sym in re.findall(r"\{([^}]+)\}", mana_cost):
        s = sym.upper()
        if s.isdigit():
            generic += int(s)
        elif s == "X":
            continue                 # X se maneja aparte (card.x_spell)
        elif "/" in s:               # híbrido / phyrexiano: pagable con cualquier
            generic += 1             # maná (aprox: cuenta como 1 genérico)
        elif s in _COLOR_MAP and s != "C":
            pips += s
        # {C} incoloro no aporta pip de color
    return (str(generic) if generic else "") + pips or "0"


def parse_type_line(type_line: str):
    """Devuelve (types, supertypes, subtypes)."""
    tl = (type_line or "").lower()
    left = tl.split("—")[0]
    right = tl.split("—")[1] if "—" in tl else ""
    types = set()
    for t in ("land", "creature", "artifact", "enchantment", "instant",
              "sorcery", "planeswalker", "battle"):
        if t in left:
            types.add(t)
    supertypes = set()
    for s in ("legendary", "basic", "snow", "world"):
        if s in left:
            supertypes.add(s)
    subtypes = {w for w in right.split()} if right else set()
    return types, supertypes, subtypes


def _int_or_zero(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _derive_tags(oracle_text, types):
    """Deriva tags aproximados del texto de la carta (para efectos genericos)."""
    t = (oracle_text or "").lower()
    tags = set()
    if "creature" in types:
        tags.add("creature")
    if re.search(r"draw (a|two|three|\w+) cards?", t):
        tags.add("draw")
    if re.search(r"destroy all|exile all|destroy each|each player sacrifices",
                 t):
        tags.add("wipe")
    elif re.search(r"destroy target|exile target", t):
        tags.add("removal")
    if re.search(r"search your library for.*land", t):
        tags.add("ramp")
    return tags


def _prefer_front_face(data: dict) -> dict:
    """Cartas de doble cara / split / adventure: Scryfall trae `type_line` y
    `mana_cost` combinados con '//' (o vacios) y los datos reales por cara en
    `card_faces`. Tomamos la cara frontal (la que se lanza) para esos campos,
    manteniendo el nombre completo y la identidad de color del nivel superior."""
    faces = data.get("card_faces")
    if not faces:
        return data
    front = faces[0]
    merged = dict(data)
    for key in ("type_line", "mana_cost", "power", "toughness", "oracle_text", "loyalty"):
        v = merged.get(key)
        if v in (None, "", []) or (isinstance(v, str) and "//" in v):
            fv = front.get(key)
            if fv not in (None, "", []):
                merged[key] = fv
    return merged


_NUMWORD = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


# tipo de objeto pedido por el texto -> target_spec que el humano puede elegir.
# El orden importa: "artifact or enchantment" antes que "artifact" o "enchantment".
_TARGET_TYPE_SPECS = [
    (r"artifact or enchantment", "any_art_ench"),
    (r"artifact", "any_artifact"),
    (r"enchantment", "any_enchantment"),
    (r"planeswalker", "any_planeswalker"),
    (r"nonland permanent", "any_nonland"),
    (r"permanent", "any_perm"),
    (r"creature", "opp_creature"),
]


def _targeted_spell(oracle: str):
    """Detecta remoción/bounce DIRIGIDA en el texto: (modo, cantidad, target_spec).
    Reconoce el TIPO de objeto (criatura/artefacto/encantamiento/planeswalker/
    permanente) para ofrecer los objetivos correctos, no sólo criaturas."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())
    for verb, mode in (("destroy", "destroy"), ("exile", "exile")):
        m = re.search(
            verb + r" (up to )?(\w+ )?target "
            r"((?:artifact or enchantment)|nonland permanent|artifact|enchantment|"
            r"planeswalker|permanent|creature)", t)
        if m:
            typ = m.group(3)
            spec = next((s for pat, s in _TARGET_TYPE_SPECS if pat in typ), "opp_creature")
            return mode, _NUMWORD.get((m.group(2) or "").strip(), 1), spec
    m = re.search(r"return (up to )?(\w+ )?target "
                  r"((?:nonland )?permanent|artifact|enchantment|creature)"
                  r"[^.]{0,40}hand", t)
    if m:
        typ = m.group(3)
        spec = next((s for pat, s in _TARGET_TYPE_SPECS if pat in typ), "opp_creature")
        return "bounce", _NUMWORD.get((m.group(2) or "").strip(), 1), spec
    return None


_PERMANENT_TYPES = {"creature", "artifact", "enchantment", "planeswalker",
                    "land", "battle"}


def _is_permanent_card(c):
    """¿La carta puede existir como permanente en el campo? Los instantáneos y
    conjuros NO pueden ir al campo (no se pueden reanimar/poner en juego)."""
    return bool(set(getattr(c, "types", set())) & _PERMANENT_TYPES)


def _cascade_effect(cmc):
    """Cascade: exilia del tope hasta hallar una no-tierra de CMV menor; la lanza
    GRATIS (permanente -> al campo con ETB; hechizo -> resuelve su efecto) y el
    resto va al fondo en orden aleatorio."""
    def eff(game, ctrl, *_a, _cmc=cmc):
        exiled = []
        hit = None
        while ctrl.library:
            c = ctrl.library.pop()
            cc = c.cost.cmc if getattr(c, "cost", None) else 0
            if not c.is_land() and cc < _cmc:
                hit = c
                break
            exiled.append(c)
        if hit is not None:
            game.log(f"{ctrl.name} cascadea y lanza gratis {hit.name}")
            if _is_permanent_card(hit):
                game.move_to_battlefield(hit, ctrl)
            else:
                if getattr(hit, "on_cast_resolve", None):
                    hit.on_cast_resolve(game, ctrl, [])
                ctrl.graveyard.append(hit)
        game.rng.shuffle(exiled)
        for c in exiled:
            ctrl.library.insert(0, c)      # al fondo
    return eff


def _gy_mass_cast_effect():
    """'Puedes jugar tierras y lanzar hechizos desde tu cementerio este turno'
    (Yawgmoth's Will / Underworld Breach). Aproximación: al resolver, relanza los
    hechizos SIN objetivo costeables del cementerio (los con objetivo abrirían
    elecciones en cadena) y pone una tierra en juego; lo jugado se exilia."""
    def eff(game, ctrl, *_a):
        ctrl.gy_cast_until = game.turn
        for c in list(ctrl.graveyard):
            if not ({"instant", "sorcery"} & c.types) or not c.on_cast_resolve:
                continue
            if getattr(c, "target_spec", None):        # con objetivo -> se omite (aprox)
                continue
            if c.cost is not None and not ctrl.can_pay(c.cost):
                continue
            if c not in ctrl.graveyard:
                continue
            if c.cost is not None:
                ctrl.pay(c.cost)
            ctrl.graveyard.remove(c)
            game.log(f"{ctrl.name} lanza {c.name} desde el cementerio")
            try:
                c.on_cast_resolve(game, ctrl, [])
            except Exception:
                pass
            ctrl.exile.append(c)                       # lo jugado desde el cementerio se exilia
        for c in list(ctrl.graveyard):                 # una tierra al campo
            if c.is_land() and ctrl.lands_played < 1:
                ctrl.graveyard.remove(c)
                game.move_to_battlefield(c, ctrl)
                ctrl.lands_played += 1
                break
    return eff


def _counter_ability_effect():
    """Contrarresta una habilidad activada/disparada objetivo (Stifle): la saca de
    la pila para que no se resuelva."""
    def eff(game, ctrl, targets):
        obj = (list(targets or []) or [None])[0]
        if obj is not None and obj in game.stack:
            game.stack.remove(obj)
            game.log(f"{ctrl.name} contrarresta una habilidad ({getattr(obj,'label','')})")
    return eff


def _counter_spell_effect():
    """Contrarresta el hechizo objetivo (StackObject): lo saca de la pila y su
    carta va al cementerio. Cubre Counterspell y variantes importadas de Scryfall."""
    def eff(game, ctrl, targets):
        obj = (list(targets or []) or [None])[0]
        if obj is None or obj not in game.stack:
            return
        game.stack.remove(obj)
        card = getattr(obj, "source", None)
        name = getattr(card, "name", "?")
        if card is not None and not card.is_land():
            obj.controller.graveyard.append(card)
            game.emit("to_graveyard", player=obj.controller, card=card)
        game.log(f"{ctrl.name} contrarresta {name}")
    return eff


def _pump_spell_effect(oracle: str):
    """Hechizo (instantáneo/conjuro) que da +X/+X o -X/-X — dirigido (Giant Growth,
    Grasp of Darkness) o masivo (pump de equipo, Infest). Devuelve
    (effect(game, ctrl, targets), target_spec, count) o None. La remoción por
    destruir/exiliar la maneja _targeted_spell; esto cubre lo de solo modificar P/T."""
    tl = re.sub(r"\s+", " ", (oracle or "")).lower()

    # 1) dirigido a UNA criatura: "target creature gets +X/+Y ..."
    m = re.search(r"target creature gets ([+-]\d+)/([+-]\d+)", tl)
    if m:
        dp, dt = int(m.group(1)), int(m.group(2))

        def eff(game, ctrl, targets, _p=dp, _t=dt):
            for tg in (targets or []):
                if hasattr(tg, "temp_pt"):
                    tg.temp_pt[0] += _p
                    tg.temp_pt[1] += _t
            game.sba()
        # bono -> tu criatura; penalización -> criatura rival
        return eff, ("opp_creature" if (dp < 0 or dt < 0) else "own_creature"), 1

    # 2) masivo (sin objetivo): tus criaturas, todas, o las del rival
    m = re.search(r"(creatures you control|all creatures|each creature|"
                  r"creatures (?:your )?opponents? control) get ([+-]\d+)/([+-]\d+)", tl)
    if m:
        who, dp, dt = m.group(1), int(m.group(2)), int(m.group(3))

        def eff(game, ctrl, targets, _who=who, _p=dp, _t=dt):
            if _who == "creatures you control":
                pool = list(ctrl.creatures())
            elif _who.startswith("creatures"):        # rival(es)
                pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()]
            else:                                      # all / each creature
                pool = [pm for pl in game.players for pm in pl.creatures()]
            for tg in pool:
                tg.temp_pt[0] += _p
                tg.temp_pt[1] += _t
            game.sba()
        return eff, None, 0

    return None


def _blink_effect():
    """Parpadeo: exilia el/los permanente(s) objetivo y los devuelve al campo
    (re-dispara ETB). Los tokens desaparecen."""
    def eff(game, ctrl, targets):
        for perm in list(targets or []):
            if perm not in perm.controller.battlefield:
                continue
            owner = perm.controller
            owner.battlefield.remove(perm)
            if perm.is_token:
                game.log(f"{perm.name} parpadea y desaparece (ficha)")
                continue
            game.log(f"{ctrl.name} hace parpadear {perm.card.name}")
            game.move_to_battlefield(perm.card, owner)   # vuelve y re-dispara ETB
    return eff


def _control_effect(temp):
    """Robo de control: mueve el permanente al campo de ctrl. Si temp=True
    (Threaten/Act of Treason) lo devuelve al fin del turno con haste."""
    def eff(game, ctrl, targets):
        for perm in list(targets or []):
            if perm not in perm.controller.battlefield or perm.controller is ctrl:
                continue
            old = perm.controller
            old.battlefield.remove(perm)
            perm.controller = ctrl
            ctrl.battlefield.append(perm)
            perm.summoning_sick = False        # entra listo para atacar
            perm.tapped = False
            game.log(f"{ctrl.name} toma el control de {perm.card.name}")
            if temp:
                perm.return_to = old
                game.control_returns.append(perm)
    return eff


def _clone_effect():
    """Clon: crea una ficha que es una COPIA COMPLETA del objetivo (P/T, keywords
    y también sus habilidades: ETB, activadas, disparadas, estáticas, lealtad)."""
    def eff(game, ctrl, targets):
        tg = (list(targets or []) or [None])[0]
        if tg is None:
            return
        cards.make_copy_token(game, ctrl, tg.card)
        game.log(f"{ctrl.name} crea una copia de {tg.card.name}")
    return eff


def _copy_spell_effect():
    """Copia un hechizo de la pila (Fork / Twincast / Reverberate). El objetivo es
    un StackObject (target_spec='stack_spell')."""
    def eff(game, ctrl, targets):
        obj = (list(targets or []) or [None])[0]
        if obj is None or obj not in game.stack:
            game.log(f"{ctrl.name}: no hay hechizo en la pila para copiar")
            return
        game.copy_spell_on_stack(obj, controller=ctrl)
    return eff


def _populate_effect():
    """Populate: crea una ficha copia de la MEJOR ficha de criatura que controlás."""
    def eff(game, ctrl, targets):
        toks = [pm for pm in ctrl.battlefield if pm.is_token and pm.is_creature()]
        if not toks:
            game.log(f"{ctrl.name} no tiene fichas de criatura para poblar (populate)")
            return
        best = max(toks, key=lambda c: (c.power, c.toughness))
        cards.make_copy_token(game, ctrl, best.card)
        game.log(f"{ctrl.name} puebla (populate): copia {best.name}")
    return eff


def _fight_effect():
    """'~ fights target creature' / 'deals damage equal to its power to target
    creature': la mejor criatura del controlador y el objetivo se hacen daño mutuo."""
    def eff(game, ctrl, targets):
        tg = (list(targets or []) or [None])[0]
        if tg is None or not tg.is_creature():
            return
        mine = [c for c in ctrl.creatures()]
        if not mine:
            return
        fighter = max(mine, key=lambda c: c.power)
        game.log(f"{fighter.name} pelea con {tg.name}")
        game.deal_damage(fighter, tg, fighter.power, combat=False)
        game.deal_damage(tg, fighter, tg.power, combat=False)
        game.sba()
    return eff


def _goad_effect():
    """'Goad target creature': la criatura queda obligada a atacar en su turno."""
    def eff(game, ctrl, targets):
        for perm in list(targets or []):
            perm.goaded = True
            game.log(f"{ctrl.name} provoca (goad) a {perm.name}")
    return eff


def _targeted_special(oracle: str):
    """Detecta hechizos dirigidos especiales -> (effect, target_spec, count).
    Parpadeo, robo de control, clon, pelea y goad. None si no matchea."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())
    # copiar hechizo (Fork / Twincast / Reverberate): apunta a un hechizo de la pila
    if re.search(r"copy target (?:instant or sorcery |instant |sorcery )?spell", t) or \
       re.search(r"copy that spell", t):
        return _copy_spell_effect(), "stack_spell", 1
    # robo de control
    if re.search(r"gain control of (?:up to \w+ )?target", t):
        temp = "until end of turn" in t or "end of turn" in t
        return _control_effect(temp), "opp_creature", 1
    # clon
    if re.search(r"copy of (?:up to \w+ )?target (?:creature|permanent)", t):
        return _clone_effect(), "opp_creature", 1
    # sacrificio forzado dirigido: "its controller sacrifices it" / "~'s controller
    # sacrifices it" (esquiva indestructible pero sigue siendo objetivo)
    if re.search(r"(?:its |that creature'?s? )?controller sacrifices (?:it|that creature)", t):
        def sac(game, ctrl, targets):
            for pm in list(targets or []):
                if pm in pm.controller.battlefield:
                    owner = pm.controller
                    game.to_graveyard(pm, "sacrificio forzado")
                    game.log(f"{owner.name} sacrifica {pm.name}")
        return sac, "opp_creature", 1
    # pelea (incluye "fights another target creature": aprox. tu mejor vs objetivo)
    if re.search(r"fights? (?:up to \w+ |another )?target creature", t) or \
       re.search(r"deals damage equal to its power to (?:up to \w+ )?target creature", t):
        return _fight_effect(), "opp_creature", 1
    # goad
    if re.search(r"goad (?:up to \w+ )?target creature", t):
        return _goad_effect(), "opp_creature", 1
    # parpadeo (exiliar y devolver al campo)
    if re.search(r"exile (?:up to \w+ )?target (?:creature|permanent)"
                 r"[^.]{0,80}?return (?:it|that card|them)[^.]{0,40}?battlefield", t):
        spec = "own_perm" if "you control" in t else "opp_creature"
        return _blink_effect(), spec, 1
    return None


def _short_label(s, n=52):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _fragment_effect(seg: str):
    """Parsea un fragmento de texto a (effect(g,ctrl,targets), target_spec, count).
    Reusa los helpers de remoción/monto/robar. effect=None si no se reconoce."""
    # copiar una habilidad activada/disparada (Strionic Resonator / Lithoform Engine):
    # como el motor resuelve las habilidades al instante, copiamos la última resuelta.
    if re.search(r"copy target (?:activated|triggered)", seg, re.I) or \
       re.search(r"copy (?:that|the target) (?:activated |triggered )?ability", seg, re.I):
        def copy_ab(game, ctrl, targets):
            obj = (list(targets or []) or [None])[0]
            # si apuntamos a una habilidad concreta en la pila, copiar ESA;
            # si no (activación en fase principal sin objetivo), copiar la última.
            if obj is not None and getattr(obj, "kind", None) in ("ability", "trigger"):
                game.copy_ability_on_stack(obj, ctrl)
            else:
                game.copy_last_ability(ctrl)
        return copy_ab, None, 1
    # buscar una tierra básica al campo (fetchlands: Evolving Wilds, panoramas…)
    if re.search(r"search your library for a basic land", seg, re.I):
        tapped = "tapped" in seg.lower()
        pred = lambda c: c.is_land() and "basic" in c.supertypes  # noqa: E731
        return (_search_library_effect(pred, to_battlefield=True, allow_none=False,
                                        label="una tierra básica", tapped=tapped),
                None, 1)
    # pump: "target creature gets +X/+Y until end of turn"
    mp = re.search(r"target creature gets ([+-]\d+)/([+-]\d+)(?:\s+until end of turn)?",
                   seg, re.I)
    if mp:
        dp, dt = int(mp.group(1)), int(mp.group(2))

        def pump(game, ctrl, targets, _p=dp, _t=dt):
            for tg in (targets or []):
                if hasattr(tg, "temp_pt"):
                    tg.temp_pt[0] += _p
                    tg.temp_pt[1] += _t
            game.sba()
        # bonus -> propia criatura; penalización -> criatura rival
        return pump, ("opp_creature" if (dp < 0 or dt < 0) else "own_creature"), 1
    # poner contadores +1/+1 en una criatura objetivo
    mc = re.search(r"put (\w+) \+1/\+1 counters? on target creature", seg, re.I)
    if mc and _count_word(mc.group(1)):
        n = _count_word(mc.group(1))

        def putc(game, ctrl, targets, _n=n):
            for tg in (targets or []):
                if hasattr(tg, "counters"):
                    game.add_counters(tg, "+1/+1", _n)
        return putc, "own_creature", 1
    # girar una criatura objetivo
    if re.search(r"\btap target creature", seg, re.I) and "untap" not in seg.lower():
        def tapc(game, ctrl, targets):
            for tg in (targets or []):
                if hasattr(tg, "tapped"):
                    tg.tapped = True
        return tapc, "opp_creature", 1
    spec = _targeted_spell(seg)
    if spec is not None:
        mode, count, tspec = spec
        return cards.remove_targets(mode), tspec, max(1, count)
    # quema a criatura elegida: "deals N damage to (up to M) target creature"
    mb = re.search(r"deals? (\w+) damage to (?:up to (\w+) )?target creature(?! or player)",
                   seg, re.I)
    if mb and (mb.group(1).lower() == "x" or _count_word(mb.group(1))):
        n = _count_word(mb.group(1))
        is_x = mb.group(1).lower() == "x"
        cnt = _count_word(mb.group(2)) if mb.group(2) else 1

        def burn(game, ctrl, targets, _n=n, _x=is_x):
            amt = getattr(game, "spell_x", 0) if _x else _n
            for tg in (targets or []):
                game.deal_damage(None, tg, amt)
        return burn, "opp_creature", max(1, cnt or 1)
    # quema a un JUGADOR elegido: "deals N damage to target player / any target /
    # creature or player / player or planeswalker" -> el humano elige a qué rival.
    mp = re.search(r"deals? (\w+) damage to (?:any target|target player|target opponent|"
                   r"target creature or player|target planeswalker or player|"
                   r"target player or planeswalker)", seg, re.I)
    if mp and (mp.group(1).lower() == "x" or _count_word(mp.group(1))):
        n = _count_word(mp.group(1))
        is_x = mp.group(1).lower() == "x"

        def burnp(game, ctrl, targets, _n=n, _x=is_x):
            amt = getattr(game, "spell_x", 0) if _x else _n
            tgts = [t for t in (targets or []) if hasattr(t, "life")]  # jugadores
            if not tgts:
                opps = game.opponents(ctrl)
                tgts = [min(opps, key=lambda o: o.life)] if opps else []
            for tg in tgts:
                game.deal_damage(None, tg, amt)
                game.log(f"{ctrl.name}: {amt} de daño a {tg.name}")
        return burnp, "opp_player", 1
    geff = _generic_amount_effect(seg)
    if geff is None:
        dm = re.search(r"draw (\w+) cards?", seg, re.I)
        n = _count_word(dm.group(1)) if dm else None
        if n:
            geff = cards.draw_n(n)
    return geff, None, 1


def _parse_modes(oracle: str):
    """Detecta un hechizo modal ('Choose one/two — ...') y devuelve
    (list[{label, effect, target_spec, target_count}], cuántos_elegir) o None.
    Si un modo tiene un efecto no modelado NO se descarta el modal: se le da un
    efecto de respaldo que lo registra, para que el selector SIEMPRE se ofrezca."""
    if not oracle:
        return None
    m = re.search(r"choose (one or both|one or more|one|two|three|up to \w+)"
                  r"\s*[—\-–:]\s*(.+)", oracle, re.I | re.S)
    if not m:
        return None
    head = m.group(1).lower()
    pick = 2 if ("two" in head or "both" in head or "more" in head) else 1
    body = m.group(2)
    parts = None
    for pat in (r"\s*•\s*", r"\s*\n\s*", r"\s*;\s*or\s+"):  # bullets, saltos, "; or"
        cand = [p.strip(" .\n•") for p in re.split(pat, body) if p.strip(" .\n•")]
        if len(cand) >= 2:
            parts = cand
            break
    if not parts:                       # último recurso: un solo " or " a nivel de modo
        cand = [p.strip(" .\n•") for p in re.split(r"\s+or\s+", body) if p.strip(" .\n•")]
        parts = cand if len(cand) == 2 else None
    if not parts:
        return None
    modes = []
    for seg in parts[:4]:
        eff, spec, count = _fragment_effect(seg)
        label = _short_label(seg)
        if eff is None:                 # efecto no modelado: respaldo visible
            eff = (lambda g, ctrl, targets=None, _l=label:
                   g.log(f"{ctrl.name} elige: {_l}"))
            spec, count = None, 1
        modes.append({"label": label, "effect": eff,
                      "target_spec": spec, "target_count": count})
    if len(modes) < 2:
        return None
    return modes, pick


def _parse_activated(oracle: str, name: str = ""):
    """Habilidades activadas con coste de MANÁ (+ opcional {T} y opcional
    'Sacrifice this ~' como coste). Devuelve una tupla de dicts {cost, tap,
    sacrifice_self, label, effect, target_spec, target_count}. Ignora otros costes
    (descartar, pagar vida) y efectos que no reconocemos."""
    name_key = re.sub(r"[^a-z]", "", (name or "").lower())
    out = []
    for raw in (oracle or "").split("\n"):
        m = re.match(r"([^:]+):\s*(.+)", raw.strip())
        if not m:
            continue
        costtxt, body = m.group(1), m.group(2)
        # el coste puede tener varias cláusulas separadas por comas: maná ({..}),
        # girar ({T}) y costes adicionales que sí modelamos (sacrificar esta misma
        # permanente, sacrificar OTRA permanente, pagar vida, descartar cartas).
        # Cualquier cláusula que no reconozcamos descarta la habilidad (bad=True).
        syms = []
        sac_self = False
        sac_other = None   # {"count": n, "type": "..."} — sacrificar OTRAS permanentes
        pay_life = 0
        discard = 0        # nº de cartas a descartar (-1 = toda la mano)
        bad = False
        for cl in costtxt.split(","):
            syms.extend(re.findall(r"\{([^}]+)\}", cl))
            rest = re.sub(r"\{[^}]+\}", "", cl).strip().lower().rstrip(".")
            if not rest:
                continue
            key = re.sub(r"[^a-z]", "", rest)
            if key.startswith("sacrifice"):
                tail = key[len("sacrifice"):]
                if tail.startswith(("this", "it", "~")) or (name_key and tail == name_key):
                    sac_self = True
                    continue
                mso = re.match(r"sacrifice (a|an|another|\d+|two|three|four|\w+) "
                               r"(creature|permanent|artifact|land|enchantment|token)s?",
                               rest)
                if mso:
                    qty = mso.group(1)
                    n = 1 if qty in ("a", "an", "another") else (_count_word(qty) or 1)
                    sac_other = {"count": n, "type": mso.group(2)}
                    continue
            mpl = re.match(r"pay (\d+) life", rest)
            if mpl:
                pay_life = int(mpl.group(1))
                continue
            if rest.startswith("discard"):
                if "hand" in rest:
                    discard = -1
                else:
                    md = re.match(r"discard (a|an|\d+|two|three|four|\w+)", rest)
                    q = md.group(1) if md else "a"
                    discard = 1 if q in ("a", "an") else (_count_word(q) or 1)
                continue
            bad = True
            break
        if bad:
            continue
        # se acepta una habilidad sin maná/{T} solo si tiene un coste real (sacrificio,
        # pagar vida, descartar) — p. ej. "Sacrifice a creature: Add {C}{C}".
        if not syms and not (sac_self or sac_other or pay_life or discard):
            continue
        tap = any(s.upper() == "T" for s in syms)
        mana = "".join("{%s}" % s for s in syms if s.upper() != "T")
        cost = parse_cost(mana_cost_to_str(mana)) if mana else parse_cost("0")
        # habilidades de "agregar maná": las de coste trivial ({T}/maná) ya las cubre
        # `produces`. Pero las que tienen un coste REAL (sacrificar otra permanente,
        # pagar vida, descartar) NO las cubre produces: Ashnod's Altar y compañía.
        # Esas se modelan como activadas que llenan el maná flotante.
        is_add_mana = bool(re.search(r"\badd\b.*\bmana\b", body, re.I)) or bool(
            re.match(r"add(\s*\{[wubrgc0-9/x]+\})+\s*\.?$", body.strip(), re.I))
        if is_add_mana:
            if not (sac_other or pay_life or discard):
                continue                       # coste trivial -> produces la cubre
            amt = len(re.findall(r"\{[wubrgc]\}", body, re.I))
            if not amt:
                mn = re.search(r"add (\w+) mana", body, re.I)
                amt = _count_word(mn.group(1)) if mn else 1
            eff = (lambda g, c, tg=None, _n=(amt or 1):
                   (setattr(c, "mana_pool", c.mana_pool + _n),
                    g.log(f"{c.name} agrega {_n} maná")))
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self,
                        "sacrifice_other": sac_other, "pay_life": pay_life,
                        "discard": discard, "label": _short_label(body),
                        "effect": (lambda g, c, perm, tg, _e=eff: _e(g, c, tg)),
                        "target_spec": None, "target_count": 1,
                        "is_copy_ability": False})
            continue
        # self-buff: "Monstrosity N" o "put N +1/+1 counters on it/this creature"
        # (usa el PERMANENTE fuente, que el wrapper genérico no pasa al efecto).
        msc = re.search(r"monstrosity (\w+)", body, re.I) or re.search(
            r"put (\w+) \+1/\+1 counters? on (?:it|itself|this creature|this permanent)",
            body, re.I)
        if msc and (scn := _count_word(msc.group(1))):
            def eff_self(g, c, perm, tg, _n=scn):
                if perm is not None:
                    g.add_counters(perm, "+1/+1", _n)
                    perm.monstrous = True
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self,
                        "sacrifice_other": sac_other, "pay_life": pay_life,
                        "discard": discard, "label": _short_label(body),
                        "effect": eff_self, "target_spec": None,
                        "target_count": 1, "is_copy_ability": False})
            continue
        eff, spec, count = _fragment_effect(body)
        if eff is None:
            # efecto no modelado: EXPONER igual la habilidad con un respaldo visible,
            # así el jugador puede activarla (mismo criterio que los modos).
            eff = (lambda g, c, tg=None, _l=_short_label(body):
                   g.log(f"{c.name} activa: {_l}"))
            spec, count = None, 1
        is_copy = bool(re.search(r"copy target (?:activated|triggered)", body, re.I)
                       or re.search(r"copy (?:that|the target) (?:activated |triggered )?ability",
                                    body, re.I))
        out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self,
                    "sacrifice_other": sac_other, "pay_life": pay_life,
                    "discard": discard,
                    "label": _short_label(body),
                    "effect": (lambda g, c, perm, tg, _e=eff: _e(g, c, tg)),
                    "target_spec": spec, "target_count": count,
                    "is_copy_ability": is_copy})
    return tuple(out[:4])


def _attack_trigger_effect(oracle: str):
    """'Whenever ~ attacks, <efecto>' -> callback de trigger (g, perm, **kw) o None.
    Cubre p. ej. Laelia (al atacar, exiliar el tope y poder jugarla)."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    m = re.search(r"whenever [^.]{0,50}? attacks,?\s*(.{0,180})", t, re.I)
    if not m:
        return None
    body = m.group(1)
    # auto-pump al atacar: "it/this creature gets +X/+Y until end of turn"
    mp = re.search(r"(?:it|this creature) gets ([+-]\d+)/([+-]\d+)", body, re.I)
    if mp:
        dp, dt = int(mp.group(1)), int(mp.group(2))

        def trig_pump(game, perm, _p=dp, _t=dt, **_kw):
            perm.temp_pt[0] += _p
            perm.temp_pt[1] += _t
            game.sba()
        return trig_pump
    eff, _spec, _count = _fragment_effect(body)
    if eff is None:
        return None

    def trig(game, perm, **_kw):
        eff(game, perm.controller, [])
    return trig


def _event_trigger_effect(oracle: str):
    """Detecta disparos comunes y devuelve {evento: callback(g, perm, **kw)}.
    Cubre 'cuando una criatura muere', 'daño de combate a un jugador' y
    'cuando lanzás un instant/sorcery' (magecraft). Reusa _generic_amount_effect
    sobre el texto del efecto (ficha, drenaje, robar, ganar vida, etc.)."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    out = {}
    specs = [
        (r"whenever (?:a|another) (?:nontoken )?creature (?:you control )?dies,?\s*"
         r"(.{0,160})", "death"),
        (r"whenever [\w' ,]{0,40}? deals combat damage to a player,?\s*(.{0,160})",
         "combat_damage_to_player"),
    ]
    for pat, ev in specs:
        if ev in out:
            continue
        m = re.search(pat, t, re.I)
        if not m:
            continue
        eff = _generic_amount_effect(m.group(1))
        if eff is None:
            continue

        def cb(game, perm, _e=eff, *_a, **_kw):
            _e(game, perm.controller)
        out[ev] = cb

    # "whenever an opponent casts a spell, <efecto>" (evento opp_cast sin scope; el
    # callback sólo actúa si el que lanzó es rival del permanente que observa).
    moc = re.search(r"whenever an opponent casts (?:a|an|another)? ?[\w' ]*?spell,?\s*"
                    r"(.{0,140})", t, re.I)
    if moc:
        effo = _generic_amount_effect(moc.group(1))
        if effo is not None:
            def cboc(game, perm, caster=None, **_kw):
                if caster is not None and caster is not perm.controller:
                    effo(game, perm.controller)
            out["opp_cast"] = cboc

    # "whenever you gain life, <efecto>" (soul sisters, Ajani's Pridemate, Heliod…).
    if "gain_life" not in out:
        mg = re.search(r"whenever you gain life,?\s*(.{0,140})", t, re.I)
        if mg:
            body = mg.group(1)
            # caso muy común: "put a/one +1/+1 counter on ~" sobre el propio permanente
            mcnt = re.search(r"put (a|an|one|\w+) \+1/\+1 counters? on", body, re.I)
            if mcnt:
                cn = _count_word(mcnt.group(1)) or 1

                def cbg(game, perm, _n=cn, **_kw):
                    game.add_counters(perm, "+1/+1", _n)
                out["gain_life"] = cbg
            else:
                effg = _generic_amount_effect(body)
                if effg is not None:
                    def cbg(game, perm, _e=effg, **_kw):
                        _e(game, perm.controller)
                    out["gain_life"] = cbg

    # "whenever you cast a(n) <tipo> spell, <efecto>" (magecraft, Young Pyromancer,
    # Talrand, disparos de fichas al lanzar criaturas, etc.). Filtra por el TIPO
    # de hechizo declarado; "your first ... each turn" se aproxima sin el límite.
    mc = re.search(r"whenever you cast (?:your first )?"
                   r"(an instant or sorcery|a noncreature|a creature|an artifact|"
                   r"an enchantment|a spell)"
                   r"[\w ]*? spell,?\s*(.{0,160})", t, re.I)
    if mc and "cast" not in out:
        qual = mc.group(1).lower()
        eff = _generic_amount_effect(mc.group(2))
        if eff is not None:
            if "instant or sorcery" in qual:
                need = {"instant", "sorcery"}
            elif "noncreature" in qual:
                need = None      # cualquier no-criatura (se filtra abajo)
            elif "a spell" in qual:
                need = set()     # cualquier hechizo
            else:
                need = {qual.split()[-1]}   # creature / artifact / enchantment

            def cbc(game, perm, card=None, _e=eff, _need=need, **_kw):
                if card is None:
                    return
                if _need is None:                        # noncreature
                    if "creature" in card.types:
                        return
                elif _need and not (_need & card.types):
                    return
                _e(game, perm.controller)
            out["cast"] = cbc

    # "whenever another creature (you control) dies, put N +1/+1 counters on this
    # creature" (aristócratas que crecen). El efecto va al permanente que observa.
    if "death" not in out:
        md = re.search(r"whenever (?:a|another) (?:nontoken )?creature (?:you control )?"
                       r"dies,?\s*put (\w+) \+1/\+1 counters? on (?:this creature|it)",
                       t, re.I)
        if md and (dn := _count_word(md.group(1))):
            def cbd(game, perm, _n=dn, *_a, **_kw):
                game.add_counters(perm, "+1/+1", _n)
            out["death"] = cbd

    # "cuando entra una criatura (que controlás) [con CMV N o menos], <efecto>"
    me = re.search(r"whenever (?:one or more|a|an|another) (?:nontoken )?creatures?"
                   r"(?: you control)?(?: with mana value (\d+) or less)?"
                   r"[^,]*?enters?(?: the battlefield)?[^,]*,\s*(.{0,160})", t, re.I)
    if me and "creature_enters" not in out:
        lim = int(me.group(1)) if me.group(1) else None
        eff = _generic_amount_effect(me.group(2))
        if eff is None:
            eff = (lambda g, ctrl, *_a, _l=_short_label(me.group(2)):
                   g.log(f"{ctrl.name}: {_l}"))
        yours = "you control" in t.lower()
        another = bool(re.match(r"\s*whenever another", t, re.I))
        once = "only once each turn" in t.lower()

        def cb(game, watcher, entered=None, _e=eff, _lim=lim,
               _yours=yours, _another=another, _once=once):
            if entered is None:
                return
            if _yours and entered.controller is not watcher.controller:
                return
            if _another and entered is watcher:
                return
            if _lim is not None and _cmc(entered) > _lim:
                return
            if _once and getattr(watcher, "_ce_turn", None) == game.turn:
                return
            watcher._ce_turn = game.turn
            _e(game, watcher.controller)
        out["creature_enters"] = cb
    return out


def _recurring_trigger_effects(oracle: str):
    """Disparos recurrentes 'At the beginning of (your) upkeep/end step, <efecto>'.
    Devuelve {"upkeep"|"end_step": callback(g, perm, **kw)} usando la capa genérica
    de efectos. Antes esto se cableaba mal como un ETB de una sola vez."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    out = {}
    for m in re.finditer(r"at the beginning of (your|each(?: player'?s?)?) "
                         r"(upkeep|end step|draw step)[,.]?\s*(.{0,160})", t, re.I):
        ev = "end_step" if "end" in m.group(2).lower() else "upkeep"
        eff = _generic_amount_effect(m.group(3))
        if eff is None or ev in out:
            continue

        def cb(game, perm, _e=eff, **_kw):
            _e(game, perm.controller)
        out[ev] = cb
    return out


def _death_self_effect(oracle: str, name: str = ""):
    """'When(ever) this creature/<nombre> dies, <efecto>' -> callback on_death
    (game, ctrl, perm). Usa la capa genérica. Antes esto se cableaba mal como ETB."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    nm = re.escape(name) if name else None
    who = r"(?:this creature|this permanent|this artifact|it" + (f"|{nm}" if nm else "") + r")"
    m = re.search(r"when(?:ever)? " + who + r" dies,?\s*(.{0,160})", t, re.I)
    if not m:
        return None
    body = m.group(1)
    # "put N +1/+1 counters on <the creature/target>": no aplica al morir; ignoramos
    eff = _generic_amount_effect(body)
    if eff is None:
        return None

    def on_death(game, ctrl, perm, _e=eff):
        _e(game, ctrl)
    return on_death


def _persist_undying_ondeath(oracle: str):
    """Persist / Undying: al morir, si NO tenía el contador correspondiente, la
    criatura vuelve al campo con un contador (-1/-1 persist, +1/+1 undying).
    Devuelve on_death(game, ctrl, perm) que retorna True si la reubicó (para que
    el motor no la mande al cementerio), o None si la carta no tiene la mecánica."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())
    undying = ("undying" in t
               or "return it to the battlefield under its owner's control with a "
                  "+1/+1 counter" in t)
    persist = ("persist" in t
               or "return it to the battlefield under its owner's control with a "
                  "-1/-1 counter" in t)
    if not (undying or persist):
        return None
    kind = "+1/+1" if undying else "-1/-1"

    def on_death(game, ctrl, perm, _kind=kind):
        if perm.is_token:                       # las fichas dejan de existir
            return False
        if perm.card is ctrl.commander_card:    # el comandante va a la zona de mando
            return False
        if perm.counters.get(_kind, 0) > 0:     # ya tenía el contador -> al cementerio
            return False
        new = game.move_to_battlefield(perm.card, ctrl)
        if new is not None:
            game.add_counters(new, _kind, 1)
            game.log(f"{perm.card.name} vuelve al campo "
                     f"({'undying' if _kind == '+1/+1' else 'persist'})")
            return True
        return False
    return on_death


def _static_anthem(oracle: str):
    """Anthem estático genérico de un permanente: 'creatures you control get +X/+X'
    y 'creatures you control have <keyword>'. Devuelve (static_mod, keywords) o
    (None, set())."""
    t = re.sub(r"\s+", " ", (oracle or "")).lower()
    m = re.search(r"(?:other )?creatures you control get ([+-]\d+)/([+-]\d+)", t)
    dp, dt = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    kws = set()
    mk = re.search(r"(?:other )?creatures you control have ([a-z ,and]+?)"
                   r"(?:\.|$|until)", t)
    if mk:
        for name, key in _KEYWORD_WORDS:
            if re.search(r"\b" + name + r"\b", mk.group(1)):
                kws.add(key)
    if not (dp or dt or kws):
        return None, set()
    others = "other creatures" in t

    def sm(source, target, _dp=dp, _dt=dt, _o=others):
        if not target.is_creature() or target.controller is not source.controller:
            return (0, 0)
        if _o and target is source:
            return (0, 0)
        return (_dp, _dt)
    return sm, kws


def _cmc(perm):
    """Coste de maná convertido de un permanente (0 si no tiene coste)."""
    c = getattr(perm, "card", perm)
    return c.cost.cmc if getattr(c, "cost", None) else 0


def _parse_gy_play(oracle: str, types: set):
    """Detecta cómo se puede jugar la carta DESDE EL CEMENTERIO. Devuelve un dict
    {mode, cost(Cost), after, exile_n} o {}. Cubre flashback / escape / unearth /
    embalm/eternalize / disturb / recursión ('{coste}: return ~ ... battlefield/hand')."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()

    def _cost(seq):
        return parse_cost(mana_cost_to_str(seq)) if seq else parse_cost("0")

    def _seq(kw):
        m = re.search(kw + r"\s*[—:-]?\s*((?:\{[^}]+\})+)", t, re.I)
        return m.group(1) if m else None

    # escape: "Escape—{cost}, Exile N other cards from your graveyard."
    me = re.search(r"escape\s*[—:-]?\s*((?:\{[^}]+\})+),?\s*exile (\w+)", t, re.I)
    if me:
        return {"mode": "escape", "cost": _cost(me.group(1)),
                "exile_n": _count_word(me.group(2)) or 0, "after": "exile"}
    for kw, mode, after in (
        ("unearth", "unearth", "exile_eot"),
        ("embalm", "embalm", "token"),
        ("eternalize", "embalm", "token"),
        ("disturb", "disturb", "exile"),
        ("flashback", "flashback", "exile"),
        ("jump-start", "flashback", "exile"),
    ):
        seq = _seq(kw)
        if seq:
            return {"mode": mode, "cost": _cost(seq), "after": after}
    # recursión activada: "{coste}: return ~ from your graveyard to the battlefield/your hand"
    mr = re.search(r"((?:\{[^}]+\})+)\s*:\s*return [^.]*?from your graveyard to "
                   r"(the battlefield|your hand)", t, re.I)
    if mr:
        dest = "battlefield" if "battlefield" in mr.group(2).lower() else "hand"
        return {"mode": "recur", "cost": _cost(mr.group(1)), "after": dest}
    return {}


def _wire_aura(card, oracle):
    """Si la carta es un Aura (Enchantment — Aura), la anexa a un permanente al
    entrar (huésped propio si el efecto es bueno, rival si es malo) y aplica su
    modificador de P/T y keywords SOLO a ese huésped. Se va al cementerio (SBA)
    si el huésped deja el campo."""
    if "aura" not in {s.lower() for s in card.subtypes}:
        return
    t = re.sub(r"\s+", " ", (oracle or "")).lower()
    m = re.search(r"enchanted creature gets ([+-]\d+)/([+-]\d+)", t)
    dp, dt = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    kws = set()
    for name, key in (("flying", "flying"), ("trample", "trample"),
                      ("deathtouch", "deathtouch"), ("lifelink", "lifelink"),
                      ("vigilance", "vigilance"), ("first strike", "first_strike"),
                      ("double strike", "double_strike"), ("menace", "menace"),
                      ("indestructible", "indestructible"), ("hexproof", "hexproof"),
                      ("reach", "reach"), ("haste", "haste")):
        if "enchanted creature" in t and re.search(r"\b" + re.escape(name) + r"\b", t):
            kws.add(key)
    bad = dp < 0 or dt < 0 or bool(re.search(
        r"enchanted creature (?:can't|doesn't|does not)", t))
    card.aura_keywords = kws
    if dp or dt:
        card.static_mod = (lambda src, target, _d=(dp, dt):
                           _d if target is getattr(src, "enchanting", None) else (0, 0))

    # auras de "cambio de características" (Darksteel Mutation, Kenrith's
    # Transformation, Lignify, Song of the Dryads, Imprisoned in the Moon…):
    # fijan P/T base y/o le quitan las habilidades al huésped -> removal blando.
    ab_off = bool(re.search(r"enchanted (?:creature|permanent).{0,60}?"
                            r"loses all abilities", t)) or \
        bool(re.search(r"loses all abilities", t))
    mset = re.search(r"(?:base power and toughness|base power and toughness are|"
                     r"has base power and toughness)\s*(\d+)/(\d+)", t)
    if not mset:
        mset = re.search(r"is a[n]? [\w ]*?(\d+)/(\d+)[\w ]*?(?:creature|elk|frog|"
                         r"treefolk|bird)", t)
    if mset:
        card.aura_pt_set = (int(mset.group(1)), int(mset.group(2)))
    # "is a land / isn't a creature": lo neutraliza (0/0 y sin habilidades)
    if re.search(r"is a[n]? [\w ]*land\b", t) or "isn't a creature" in t or \
       "is no longer a creature" in t:
        card.aura_pt_set = card.aura_pt_set or (0, 0)
        ab_off = True
    if ab_off:
        card.aura_abilities_off = True
    if ab_off or card.aura_pt_set:
        bad = True                     # es removal: se anexa a criatura rival
        card.tags = card.tags | {"removal"}   # la IA la valora y la juega como tal

    def _attach(game, ctrl, perm, _bad=bad):
        if _bad:
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield if pm.is_creature()]
        else:
            pool = [pm for pm in ctrl.battlefield if pm.is_creature() and pm is not perm]
        if pool:
            host = max(pool, key=lambda x: (x.power, x.toughness))
            perm.enchanting = host
            game.log(f"{ctrl.name}: {perm.name} se anexa a {host.name}")

    card.on_etb = _attach
    card.tags = card.tags | {"aura"}


def _parse_etb_counters(oracle: str):
    """'~ enters (the battlefield) with N +1/+1 counters' (o un contador nombrado
    como charge). Devuelve {kind: n}."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    out = {}
    m = re.search(r"enters (?:the battlefield )?with (\w+) \+1/\+1 counters?", t, re.I)
    if m and (n := _count_word(m.group(1))):
        out["+1/+1"] = n
    m = re.search(r"enters (?:the battlefield )?with (\w+) ([a-z]+) counters?", t, re.I)
    if m and (n := _count_word(m.group(1))):
        kind = m.group(2).lower()
        if kind not in ("loyalty",):
            out.setdefault(kind, n)
    return out


def _wipe_then_tokens_effect(oracle: str):
    """Barrida CON rider de fichas: 'Destroy all creatures. Then create a P/T …
    <subtipo> creature token for each nontoken creature you controlled that was
    destroyed this way.' (p. ej. Ceaseless Conflict). Devuelve effect(g,ctrl,targets)
    o None. El controlador recibe una ficha por cada criatura NO-ficha propia que
    fue destruida (las indestructibles que sobreviven no cuentan)."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    if not re.search(r"destroy all creatures", t, re.I):
        return None
    m = re.search(r"create an? (\d+)/(\d+)[^.]*?(\w+) creature tokens? for each "
                  r"nontoken creature you controlled that (?:was|were) destroyed this way",
                  t, re.I)
    if not m:
        return None
    p_, tgh, sub = int(m.group(1)), int(m.group(2)), m.group(3).capitalize()

    def eff(game, ctrl, targets=None, _p=p_, _t=tgh, _st=sub):
        mine = [pm for pm in list(ctrl.battlefield)
                if pm.is_creature() and not pm.is_token]
        cards.wrath(game, ctrl, None)
        destroyed = sum(1 for pm in mine if pm not in ctrl.battlefield)
        for _ in range(destroyed):
            cards.make_token(game, ctrl, _st, _p, _t, subtypes=(_st,))
        if destroyed:
            game.log(f"{ctrl.name}: crea {destroyed} ficha(s) {_p}/{_t} {_st}")
    return eff


def _parse_gy_grant(oracle: str):
    """Habilidad ESTÁTICA desde el cementerio (Anger/Brawn/Wonder): 'as long as
    ~ is in your graveyard[ and you control a <Subtipo>], creatures you control
    have <keyword>'. Devuelve {keyword, need_subtype} o None."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    m = re.search(r"as long as [^,]*?is in your graveyard"
                  r"(?: and you control (?:a|an) (\w+))?,\s*"
                  r"creatures you control have (\w+)", t, re.I)
    if not m:
        return None
    kw = m.group(2).lower()
    if kw not in KEYWORDS:
        return None
    return {"keyword": kw, "need_subtype": (m.group(1) or None)}


def _parse_foretell(oracle: str):
    """Fase B: 'Foretell {coste}' -> Cost para lanzarla ya predicha, o None."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    m = re.search(r"foretell\s*[—:-]?\s*((?:\{[^}]+\})+)", t, re.I)
    if not m:
        return None
    return parse_cost(mana_cost_to_str(m.group(1)))


def _parse_gy_abilities(oracle: str):
    """Fase C: habilidades ACTIVADAS desde el cementerio. Detecta líneas
    '{coste}[, Exile ~ from your graveyard]: efecto' cuyo texto menciona el
    cementerio. Devuelve tupla de {cost, label, effect(g,ctrl,card), exile_self}.
    (La recursión '{coste}: return ~ ...' la cubre gy_play, así que se salta.)"""
    out = []
    for raw in (oracle or "").split("\n"):
        line = raw.strip()
        low = line.lower()
        if "from your graveyard" not in low:
            continue
        if re.search(r"return .*to (the battlefield|your hand)", low):
            continue                                   # eso es recursión (gy_play)
        m = re.match(r"(.+?):\s*(.+)", line)
        if not m:
            continue
        costtxt, body = m.group(1), m.group(2)
        exile_self = bool(re.search(r"exile[^:]*from your graveyard", costtxt, re.I))
        syms = re.findall(r"\{([^}]+)\}", costtxt)
        mana = "".join("{%s}" % s for s in syms if s.upper() != "T")
        cost = parse_cost(mana_cost_to_str(mana)) if mana else parse_cost("0")
        eff, _spec, _count = _fragment_effect(body)
        if eff is None:
            eff = (lambda g, ctrl, tg=None, _l=_short_label(body):
                   g.log(f"{ctrl.name}: {_l}"))
        out.append({"cost": cost, "label": _short_label(body), "exile_self": exile_self,
                    "effect": (lambda g, ctrl, card, _e=eff: _e(g, ctrl, []))})
    return tuple(out[:3])


def _parse_gy_triggers(oracle: str):
    """Fase D: disparos MIENTRAS la carta está en el cementerio. Cubre el patrón
    landfall-recursión (Bloodghast): 'si ~ está en tu cementerio, ... devolvela al
    campo cuando entra una tierra'. Devuelve {evento: callback(g, player, card)}."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip().lower()
    out = {}
    if "in your graveyard" in t and "return" in t and \
       ("landfall" in t or re.search(r"land[^.]*enters", t)):
        def _ret(game, player, card, **_kw):
            if card in player.graveyard:
                player.graveyard.remove(card)
                game.move_to_battlefield(card, player)
                game.log(f"{card.name} vuelve del cementerio al campo (landfall)")
        out["landfall"] = _ret
    return out


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}


def _parse_saga(oracle: str):
    """Parsea los capítulos de un Saga: líneas 'I —', 'II, III —', etc.
    Devuelve ({n_capítulo: efecto(g,ctrl)}, último_capítulo) o None."""
    chapters = {}
    for line in (oracle or "").splitlines():
        m = re.match(r"\s*([IVX]+(?:\s*,\s*[IVX]+)*)\s*[—–-]+\s*(.+)", line.strip())
        if not m:
            continue
        nums = [_ROMAN.get(r.strip().lower()) for r in m.group(1).split(",")]
        body = m.group(2)
        eff = _generic_amount_effect(body)
        if eff is None:
            eff = (lambda g, ctrl, *_a, _l=_short_label(body):
                   g.log(f"{ctrl.name}: {_l}"))
        for n in nums:
            if n:
                chapters[n] = eff
    if not chapters:
        return None
    return chapters, max(chapters)


def _human_target_choice(game, ctrl, kind, prompt, options, apply_one,
                         allow_none=False):
    """Elección de objetivo genérica para efectos (p. ej. ETB dirigidos).
    `options` = lista de (etiqueta, objeto). El HUMANO elige vía pending_choice
    (mismo modal que scry/revelar); los bots aplican al primero (auto)."""
    if not options:
        return
    if ctrl is getattr(game, "interactive_human", None):
        objs = [o for _lbl, o in options]

        def _apply(idx, _objs=objs, _fn=apply_one):
            if idx is not None and 0 <= idx < len(_objs):
                _fn(_objs[idx])

        game.pending_choice = {
            "kind": kind,
            "prompt": prompt,
            "options": [{"i": i, "name": lbl, "ok": True}
                        for i, (lbl, _o) in enumerate(options)],
            "allow_none": bool(allow_none),
            "_apply": _apply,
        }
    else:
        apply_one(options[0][1])


def _pick_card_from_zone(game, ctrl, cards_list, apply_one, prompt, kind="reanimate"):
    """Elegir UNA carta de una zona (cementerio/exilio) para recuperar/revivir.
    El humano ve las cartas (imagen + nombre) en el modal y elige; el bot toma la
    primera (el que llama la lista ordenada de mejor a peor)."""
    cands = list(cards_list)
    if not cands:
        return
    if ctrl is getattr(game, "interactive_human", None):
        def _apply(idx, _objs=cands, _fn=apply_one):
            if idx is not None and 0 <= idx < len(_objs):
                _fn(_objs[idx])
        game.pending_choice = {
            "kind": kind,
            "prompt": prompt,
            "options": [{"i": i, "name": c.name, "is_land": c.is_land(), "ok": True}
                        for i, c in enumerate(cands)],
            "allow_none": False,
            "_apply": _apply,
        }
    else:
        apply_one(cands[0])


def _count_word(w):
    """Palabra o dígito -> int, o None."""
    w = (w or "").strip().lower()
    if w in _NUMWORD:
        return _NUMWORD[w]
    try:
        return int(w)
    except ValueError:
        return None


_LOY_LINE = re.compile(r"^\s*([+−\-]?\d+)\s*:\s*(.+?)\s*$")


def _loyalty_effect(text: str):
    """Efecto APROXIMADO de una habilidad de lealtad, deducido de su texto.
    Cubre los patrones comunes (daño, robo, vida, ficha). Si no reconoce nada,
    devuelve None: la habilidad solo cambia la lealtad (mejor que no existir)."""
    t = re.sub(r"\s+", " ", (text or "").lower())

    m = re.search(r"deals? (\w+) damage to each opponent", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, perm, _n=n):
            for o in game.opponents(ctrl):
                game.deal_damage(perm, o, _n)
        return eff

    m = re.search(r"deals? (\w+) damage", t)
    if m and "each opponent" not in t and (n := _count_word(m.group(1))):
        def eff(game, ctrl, perm, _n=n):
            opps = game.opponents(ctrl)
            if opps:
                game.deal_damage(perm, min(opps, key=lambda o: o.life), _n)
        return eff

    m = re.search(r"draw (\w+) cards?", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, perm, _n=n):
            ctrl.draw(_n, game)
        return eff

    m = re.search(r"gain (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, perm, _n=n):
            game.gain_life(ctrl, _n)
        return eff

    m = re.search(r"(\d+)/(\d+).{0,60}?token", t)
    if m:
        pw, tf = int(m.group(1)), int(m.group(2))
        def eff(game, ctrl, perm, _p=pw, _t=tf):
            cards.make_token(game, ctrl, "Token", _p, _t)
        return eff

    # efectos con objetivo (destruir / exiliar / rebote / -X/-X / tap / poner
    # contadores): reusar el parser de fragmentos y AUTO-elegir el objetivo, para
    # que la habilidad de lealtad haga algo real en vez de solo mover la lealtad.
    frag, spec, count = _fragment_effect(text or "")
    if frag is not None and spec is not None:
        def eff(game, ctrl, perm, _f=frag, _spec=spec, _n=count):
            _f(game, ctrl, _auto_loyalty_targets(game, ctrl, _spec, _n))
        return eff

    return None


def _auto_loyalty_targets(game, ctrl, spec, n):
    """Objetivos automáticos para una habilidad de lealtad (el humano aún no elige
    objetivo de lealtad): rival más amenazante, propia mejor criatura o rival con
    menos vida, según el `target_spec` del efecto."""
    n = max(1, n or 1)
    if spec == "opp_creature":
        pool = list(game.legal_creature_targets(ctrl))
        pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
        return pool[:n]
    if spec == "own_creature":
        mine = list(ctrl.creatures())
        mine.sort(key=lambda x: (x.power, x.toughness), reverse=True)
        return mine[:n]
    if spec == "opp_player":
        opps = game.opponents(ctrl)
        return [min(opps, key=lambda o: o.life)] if opps else []
    return []


def _planeswalker_abilities(oracle: str):
    """Parsea las habilidades de lealtad del texto de Scryfall.
    Devuelve (abilities, texts) con abilities = ((coste, efecto), ...)."""
    abilities, texts = [], []
    for line in (oracle or "").splitlines():
        m = _LOY_LINE.match(line)
        if not m:
            continue
        raw = m.group(1).replace("−", "-")
        try:
            cost = int(raw)
        except ValueError:
            continue
        text = m.group(2).strip()
        abilities.append((cost, _loyalty_effect(text)))
        texts.append(text)
    return tuple(abilities), tuple(texts)


def _scry_surveil_effect(n, to_graveyard, draw_n=0, draw_first=False, fateseal=False):
    """Scry/Surveil N (+ robar opcional). Con fateseal=True mira la biblioteca de
    un RIVAL en vez de la propia. El humano decide carta por carta vía
    pending_choice; los bots usan heurística.
    Top de la biblioteca = final de la lista (library.pop())."""
    verb = "Fateseal" if fateseal else ("Surveil" if to_graveyard else "Scry")

    def eff(game, ctrl, *_a, _n=min(n, 12), _gy=to_graveyard,
            _dn=draw_n, _df=draw_first, _fs=fateseal):
        # fateseal: opera sobre el rival de menos vida; el robar es siempre del ctrl
        who = ctrl
        if _fs:
            opps = game.opponents(ctrl)
            if not opps:
                return
            who = min(opps, key=lambda o: o.life)
        if _df and _dn:
            ctrl.draw(_dn, game)
        looked = []
        for _ in range(_n):
            if who.library:
                looked.append(who.library.pop())   # looked[0] = tope
        if not looked:
            if (not _df) and _dn:
                ctrl.draw(_dn, game)
            return
        kept = []          # quedan arriba, kept[0] = la más arriba
        st = {"i": 0}
        kind = "fateseal" if _fs else ("surveil" if _gy else "scry")

        def finish():
            for c in reversed(kept):   # kept[0] vuelve a quedar en el tope
                who.library.append(c)
            dest = "cementerio" if _gy else "fondo"
            moved = len(looked) - len(kept)
            whose = f"la biblioteca de {who.name}" if _fs else "su biblioteca"
            game.log(f"{ctrl.name} hace {verb} {len(looked)} sobre {whose}: "
                     f"{len(kept)} arriba, {moved} al {dest}")
            if (not _df) and _dn:
                ctrl.draw(_dn, game)

        def _apply(choice):
            c = looked[st["i"]]
            if choice == 0:                       # dejar arriba
                kept.append(c)
            elif _gy:                             # surveil -> cementerio
                who.graveyard.append(c)
            else:                                 # scry/fateseal -> fondo
                who.library.insert(0, c)
            st["i"] += 1
            if st["i"] < len(looked):
                _prompt()
            else:
                finish()

        def _prompt():
            c = looked[st["i"]]
            dest = "Al cementerio" if _gy else "Al fondo"
            head = (f"{verb} {len(looked)} (biblioteca de {who.name})" if _fs
                    else f"{verb} {len(looked)}")
            game.pending_choice = {
                "kind": kind,
                "prompt": f"{head} — carta {st['i'] + 1} de {len(looked)}: {c.name}",
                "card": c.name,
                "options": [{"i": 0, "name": "Dejar arriba"}, {"i": 1, "name": dest}],
                "allow_none": False,
                "_apply": _apply,
            }

        if ctrl is getattr(game, "interactive_human", None):
            _prompt()
        elif _fs:  # bot fateseal: manda al fondo los hechizos del rival (le niega amenazas)
            for c in looked:
                if c.is_land():
                    kept.append(c)               # que draw una tierra
                else:
                    who.library.insert(0, c)     # amenaza al fondo
            finish()
        else:  # bot propio: baja tierras si está inundado; el resto lo deja arriba
            lands = sum(1 for pm in ctrl.battlefield if pm.card.is_land())
            for c in looked:
                if c.is_land() and lands >= 5:
                    ctrl.graveyard.append(c) if _gy else ctrl.library.insert(0, c)
                else:
                    kept.append(c)
            finish()
    return eff


def _card_type_pred(word):
    """Predicado según un tipo de carta ('land','creature','instant',...)
    o cualquiera si no se reconoce."""
    w = (word or "").strip().lower()
    table = {
        "land": lambda c: c.is_land(),
        "basic land": lambda c: c.is_land(),
        "creature": lambda c: "creature" in c.types,
        "instant": lambda c: "instant" in c.types,
        "sorcery": lambda c: "sorcery" in c.types,
        "artifact": lambda c: "artifact" in c.types,
        "enchantment": lambda c: "enchantment" in c.types,
        "planeswalker": lambda c: "planeswalker" in c.types,
    }
    for key, pred in table.items():
        if key in w:
            return pred, key
    return (lambda c: True), "carta"


def _look_take_effect(n, keep_pred, rest_dest="bottom", allow_none=True,
                      kind="look_take", prompt=None):
    """Mira las top N; el humano se lleva UNA (que cumpla keep_pred) a la mano y el
    resto va al fondo/cementerio. Reusa pending_choice. rest_dest: 'bottom'|'graveyard'.
    Generaliza el viejo 'reveal_land' a cualquier tipo de carta."""
    def eff(game, ctrl, *_a, _n=min(n, 10)):
        revealed = []
        for _ in range(_n):
            if ctrl.library:
                revealed.append(ctrl.library.pop())
        if not revealed:
            return

        def _apply(idx, _rev=revealed):
            keep = None
            if idx is not None and 0 <= idx < len(_rev) and keep_pred(_rev[idx]):
                keep = _rev[idx]
            for c in _rev:
                if c is keep:
                    ctrl.hand.append(c)
                elif rest_dest == "graveyard":
                    ctrl.graveyard.append(c)
                else:
                    ctrl.library.insert(0, c)
            shown = ", ".join(c.name for c in _rev)
            tail = "cementerio" if rest_dest == "graveyard" else "fondo"
            game.log(f"{ctrl.name} revela {shown} — toma "
                     f"{keep.name if keep else 'ninguna'}, el resto al {tail}")

        if ctrl is getattr(game, "interactive_human", None):
            game.pending_choice = {
                "kind": kind,
                "prompt": prompt or "Elegí una carta para tu mano",
                "options": [{"i": i, "name": c.name, "is_land": c.is_land(),
                             "ok": bool(keep_pred(c))} for i, c in enumerate(revealed)],
                "allow_none": allow_none,
                "_apply": _apply,
            }
        else:  # bot: mejor candidato (tierra si busca tierra, si no mayor CMC)
            cand = [i for i, c in enumerate(revealed) if keep_pred(c)]
            pick = None
            if cand:
                pick = max(cand, key=lambda i: (revealed[i].cost.cmc
                                                if revealed[i].cost else 0))
            _apply(pick)
    return eff


def _search_library_effect(keep_pred, to_battlefield=False, allow_none=True,
                           label="una carta", tapped=False):
    """Tutor: buscar en la biblioteca una carta que cumpla keep_pred y ponerla en
    la mano (o al campo, opcionalmente girada). El humano elige; el bot toma el
    mejor candidato. Baraja después."""
    def eff(game, ctrl, *_a):
        cands = [c for c in ctrl.library if keep_pred(c)]
        if not cands:
            game.log(f"{ctrl.name} busca en su biblioteca pero no encuentra {label}")
            game.rng.shuffle(ctrl.library)
            return

        def _apply(idx, _cands=cands):
            if idx is not None and 0 <= idx < len(_cands):
                pick = _cands[idx]
                if pick in ctrl.library:
                    ctrl.library.remove(pick)
                    if to_battlefield:
                        perm = game.move_to_battlefield(pick, ctrl)
                        if tapped and perm is not None:
                            perm.tapped = True
                    else:
                        ctrl.hand.append(pick)
                    where = "al campo" if to_battlefield else "a la mano"
                    game.log(f"{ctrl.name} busca y toma {pick.name} {where}")
            else:
                game.log(f"{ctrl.name} no se lleva nada de la búsqueda")
            game.rng.shuffle(ctrl.library)

        if ctrl is getattr(game, "interactive_human", None):
            game.pending_choice = {
                "kind": "search",
                "prompt": f"Buscá {label} en tu biblioteca",
                "options": [{"i": i, "name": c.name, "is_land": c.is_land(), "ok": True}
                            for i, c in enumerate(cands[:60])],
                "allow_none": allow_none,
                "_apply": _apply,
            }
        else:  # bot: mejor no-tierra por CMC; si solo hay tierras, la primera
            pick = max(range(len(cands)),
                       key=lambda i: (0 if cands[i].is_land() else 1,
                                      cands[i].cost.cmc if cands[i].cost else 0))
            _apply(pick)
    return eff


def _explore_effect():
    """Explore: revela el tope; tierra -> mano; si no, +1/+1 al que explora y el
    humano decide dejarla arriba o mandarla al cementerio (bot: cava si es cara)."""
    def eff(game, ctrl, perm=None, *_a):
        if isinstance(perm, list):   # llamado como hechizo: perm llega como targets
            perm = next((x for x in perm if hasattr(x, "counters")), None)
        if not ctrl.library:
            return
        top = ctrl.library[-1]                 # ojear el tope
        if top.is_land():
            ctrl.library.pop()
            ctrl.hand.append(top)
            game.log(f"{ctrl.name} explora: {top.name} (tierra) a la mano")
            return
        if perm is not None:
            game.add_counters(perm, "+1/+1", 1)

        def _apply(idx):
            if idx == 1:
                if ctrl.library and ctrl.library[-1] is top:
                    ctrl.library.pop()
                ctrl.graveyard.append(top)
                game.log(f"{ctrl.name} explora: +1/+1 y {top.name} al cementerio")
            else:
                game.log(f"{ctrl.name} explora: +1/+1 y deja {top.name} arriba")

        if ctrl is getattr(game, "interactive_human", None):
            game.pending_choice = {
                "kind": "explore",
                "prompt": f"Explorás: {top.name} (no es tierra). +1/+1 al explorador. "
                          f"¿La dejás arriba o la mandás al cementerio?",
                "card": top.name,
                "options": [{"i": 0, "name": "Dejar arriba"}, {"i": 1, "name": "Al cementerio"}],
                "allow_none": False,
                "_apply": _apply,
            }
        else:  # bot: cava (al cementerio) si la carta es cara
            _apply(1 if (top.cost and top.cost.cmc >= 4) else 0)
    return eff


_KEYWORD_WORDS = [
    ("flying", "flying"), ("trample", "trample"), ("haste", "haste"),
    ("vigilance", "vigilance"), ("lifelink", "lifelink"), ("deathtouch", "deathtouch"),
    ("double strike", "double_strike"), ("first strike", "first_strike"),
    ("menace", "menace"), ("hexproof", "hexproof"),
    ("indestructible", "indestructible"), ("reach", "reach"),
]


def _count_fn(phrase: str):
    """Devuelve una función f(game, ctrl) -> int para expresiones de cantidad
    variable comunes ('the number of creatures you control', 'cards in your hand',
    'Elves you control', 'Swamps you control'…) o None si no se reconoce."""
    p = (phrase or "").lower()
    if "cards in your hand" in p or "in your hand" in p:
        return lambda g, c: len(c.hand)
    if "lands you control" in p:
        return lambda g, c: len(c.lands())
    if "artifacts you control" in p:
        return lambda g, c: sum(1 for pm in c.battlefield if "artifact" in pm.card.types)
    if "creatures you control" in p:
        return lambda g, c: len(c.creatures())
    m = re.search(r"number of ([\w']+?) (?:you control|on the battlefield)", p)
    if m:
        w = _singular(m.group(1))
        if w == "creature":
            return lambda g, c: len(c.creatures())
        if w == "land":
            return lambda g, c: len(c.lands())
        if w == "artifact":
            return lambda g, c: sum(1 for pm in c.battlefield if "artifact" in pm.card.types)
        # subtipo (Elf, Goblin, Swamp, Island…): cuenta permanentes con ese subtipo
        return lambda g, c, _w=w: sum(
            1 for pm in c.battlefield if _w in {s.lower() for s in pm.card.subtypes})
    return None


def _singular(w):
    """Singular aproximado de un sustantivo (para 'Elves'->'elf', 'Allies'->'ally')."""
    w = (w or "").lower()
    if w.endswith("ves"):
        return w[:-3] + "f"
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("s"):
        return w[:-1]
    return w


def _generic_amount_effect(oracle: str):
    """Efecto APROXIMADO con monto, deducido del oracle. Devuelve una función
    eff(game, ctrl, *_) o None. Cubre patrones comunes de creaturas/hechizos que
    la capa por tags (wipe/removal/draw/ramp) no modela. Prioridad: fichas >
    quema a cada rival > ganancia de vida > mill propio."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())

    # ritual de maná: "add {C}{C}{C}", "add {G}{G}", "add N mana of any color" ->
    # maná flotante (genérico) que sirve para el próximo hechizo del mismo turno.
    mr = re.match(r"add (.+)", t)
    if mr and ("mana" in mr.group(1) or re.search(r"\{[wubrgc0-9]\}", mr.group(1))):
        seg = mr.group(1)
        syms = len(re.findall(r"\{[wubrgc]\}", seg))
        if not syms:
            mn = re.search(r"add (\w+) mana", t)
            syms = _count_word(mn.group(1)) if mn else 0
        if syms:
            def eff(game, ctrl, *_a, _n=syms):
                ctrl.mana_pool += _n
                game.log(f"{ctrl.name} agrega {_n} maná (flotante)")
            return eff

    # cantidad VARIABLE ligada a un conteo ("equal to the number of …" o
    # "where X is the number of …"):
    mvar = re.search(r"(?:equal to the|where x is the) (number of [\w' ]+?)"
                     r"(?:\.|,| that|$)", t)
    cnt = _count_fn(mvar.group(1)) if mvar else None
    if cnt is not None:
        if re.search(r"\bdraws? cards?\b", t) or "draw that many" in t:
            def eff(game, ctrl, *_a, _c=cnt):
                ctrl.draw(max(0, _c(game, ctrl)), game)
            return eff
        if re.search(r"gains? life", t) or re.search(r"gain that (?:much|many) life", t):
            def eff(game, ctrl, *_a, _c=cnt):
                game.gain_life(ctrl, max(0, _c(game, ctrl)))
            return eff
        if re.search(r"(?:each opponent|target (?:player|opponent)) loses", t):
            each = "each opponent" in t

            def eff(game, ctrl, *_a, _c=cnt, _each=each):
                n = max(0, _c(game, ctrl))
                opps = game.opponents(ctrl)
                for o in (opps if _each else opps[:1]):
                    o.life -= n
                game.log(f"{ctrl.name}: el rival pierde {n} de vida")
            return eff
        if re.search(r"deals? damage", t):
            def eff(game, ctrl, *_a, _c=cnt):
                n = max(0, _c(game, ctrl))
                opps = game.opponents(ctrl)
                if opps and n:
                    tgt = min(opps, key=lambda o: o.life)
                    game.deal_damage(None, tgt, n)
                    game.log(f"{ctrl.name}: {n} de daño a {tgt.name}")
            return eff
        if re.search(r"gets \+x/\+x", t):
            def eff(game, ctrl, *_a, _c=cnt):
                n = max(0, _c(game, ctrl))
                pool = list(ctrl.creatures())
                if not pool:
                    return
                pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
                cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

                def _do(pm, _n=n):
                    pm.temp_pt[0] += _n
                    pm.temp_pt[1] += _n
                    game.sba()
                _human_target_choice(game, ctrl, "etb_target",
                                     f"Elegí una criatura (+{n}/+{n})", cands, _do)
            return eff

    # regenerar una criatura objetivo: aproximado como indestructible hasta fin de turno
    if re.search(r"regenerate target creature", t):
        def eff(game, ctrl, *_a):
            pool = list(ctrl.creatures())
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

            def _do(pm):
                pm.temp_keywords.add("indestructible")
                game.log(f"{pm.name} queda protegida (regeneración) este turno")
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura a regenerar", cands, _do)
        return eff

    # +1/+1 en masa: "put N +1/+1 counters on each creature you control"
    m = re.search(r"put (\w+) \+1/\+1 counters? on each creature(?: you control)?", t)
    if m and (n := _count_word(m.group(1))):
        yours = "you control" in t
        def eff(game, ctrl, *_a, _n=n, _yours=yours):
            pls = [ctrl] if _yours else game.players
            for pl in pls:
                for pm in pl.creatures():
                    game.add_counters(pm, "+1/+1", _n)
        return eff

    # distribuir N contadores +1/+1 entre criaturas objetivo: el humano elige la
    # criatura que los recibe (aprox: todos a una); el bot toma su mejor criatura.
    m = re.search(r"distribute (\w+) \+1/\+1 counters? among", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            pool = list(ctrl.creatures())
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

            def _do(pm, _n=_n):
                game.add_counters(pm, "+1/+1", _n)
                game.log(f"{ctrl.name} reparte {_n} contadores +1/+1 en {pm.name}")
            _human_target_choice(game, ctrl, "etb_target",
                                 f"Elegí una criatura ({_n} contadores +1/+1)",
                                 cands, _do)
        return eff

    # fin de partida directo
    if "you win the game" in t:
        def eff(game, ctrl, *_a):
            for o in game.opponents(ctrl):
                o.lost = True
            game.log(f"{ctrl.name} gana la partida")
        return eff
    if "you lose the game" in t:
        def eff(game, ctrl, *_a):
            ctrl.lost = True
            game.log(f"{ctrl.name} pierde la partida")
        return eff
    # turno extra
    if re.search(r"take an extra turn", t):
        def eff(game, ctrl, *_a):
            game.extra_turns.append(ctrl)
            game.log(f"{ctrl.name} tomará un turno extra")
        return eff

    # destruir una tierra NO básica (p. ej. White Orchid Phantom). El humano ELIGE
    # cuál; su dueño puede buscar una básica tapeada (compensación).
    if re.search(r"destroy (?:up to )?(?:one |a )?target nonbasic land", t):
        give = "basic land" in t and "search" in t
        opt = "up to" in t
        def eff(game, ctrl, *_a, _give=give, _opt=opt):
            cands = [(f"{pm.name} · {pm.controller.name}", pm)
                     for o in game.opponents(ctrl) for pm in o.battlefield
                     if pm.card.is_land() and "basic" not in pm.card.supertypes]
            if not cands:
                game.log(f"{ctrl.name}: no hay tierra no básica para destruir")
                return

            def _do(victim):
                owner = victim.controller
                game.destroy(victim, "destrucción de tierra")
                game.log(f"{ctrl.name} destruye {victim.name} (no básica) de {owner.name}")
                if _give:
                    basics = [c for c in owner.library
                              if c.is_land() and "basic" in c.supertypes]
                    if basics:
                        b = basics[0]
                        owner.library.remove(b)
                        p = game.move_to_battlefield(b, owner)
                        p.tapped = True
                        game.rng.shuffle(owner.library)
                        game.log(f"{owner.name} busca una tierra básica (tapeada)")

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una tierra no básica para destruir"
                                 + (" (o ninguna)" if _opt else ""),
                                 cands, _do, allow_none=_opt)
        return eff

    # destruir / exiliar una criatura objetivo como ETB (p. ej. Ravenous Chupacabra):
    # el humano elige a cuál; el bot toma la más grande del rival.
    m = re.search(r"(destroy|exile) (?:up to )?(?:one |a |target )?target creature", t)
    if m:
        mode = "exile" if m.group(1) == "exile" else "destroy"
        opt = "up to" in t
        def eff(game, ctrl, *_a, _mode=mode, _opt=opt):
            pool = game.legal_creature_targets(ctrl)
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(pm):
                if pm not in pm.controller.battlefield:
                    return
                if _mode == "exile":
                    owner = pm.controller
                    owner.battlefield.remove(pm)
                    if not pm.is_token and pm.card is not owner.commander_card:
                        owner.exile.append(pm.card)
                    game.log(f"{ctrl.name} exilia {pm.name}")
                else:
                    game.destroy(pm, "ETB")
                    game.log(f"{ctrl.name} destruye {pm.name}")

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura" + (" (o ninguna)" if _opt else ""),
                                 cands, _do, allow_none=_opt)
        return eff

    # fichas de recurso (Treasure/Clue/Food/Blood): visibles en el tablero.
    m = re.search(r"create (\w+) (treasure|clue|food|blood|gold) tokens?", t)
    if m:
        n = _count_word(m.group(1)) or 1
        kind = m.group(2)

        def eff(game, ctrl, *_a, _n=min(n, 12), _k=kind):
            for _ in range(_n):
                cards.make_resource_token(game, ctrl, _k)
            game.log(f"{ctrl.name} crea {_n} ficha(s) {_k.capitalize()}")
        return eff

    m = re.search(r"create (\w+) .{0,40}?(\d+)/(\d+).{0,40}?token", t)
    if m:
        n = _count_word(m.group(1)) or 1
        pw, tf = int(m.group(2)), int(m.group(3))

        def eff(game, ctrl, *_a, _n=min(n, 8), _p=pw, _t=tf):
            for _ in range(_n):
                cards.make_token(game, ctrl, "Token", _p, _t)
        return eff

    m = re.search(r"deals? (\w+) damage to each opponent", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            for o in game.opponents(ctrl):
                game.deal_damage(None, o, _n)
            game.log(f"{ctrl.name}: {_n} de daño a cada oponente")
        return eff

    # drenaje: "each opponent loses N life" (+ opcional "you gain that much/N life")
    m = re.search(r"each opponent loses (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        gain = bool(re.search(r"you gain (that much|\w+) life", t))
        def eff(game, ctrl, *_a, _n=n, _gain=gain):
            opps = game.opponents(ctrl)
            for o in opps:
                o.life -= _n
            if _gain:
                game.gain_life(ctrl, _n * max(1, len(opps)))
            game.log(f"{ctrl.name}: cada rival pierde {_n} de vida"
                     + (" y él gana vida" if _gain else ""))
        return eff

    # quema a un objetivo tipo jugador (any target / target player / creature or
    # player): se la mandamos al rival más débil (auto) y queda VISIBLE en la vida.
    m = re.search(r"deals? (\w+) damage to (?:any target|target player|"
                  r"target opponent|target creature or player|target planeswalker or player)", t)
    if m and (m.group(1).lower() == "x" or _count_word(m.group(1))):
        n = _count_word(m.group(1))
        is_x = m.group(1).lower() == "x"

        def eff(game, ctrl, *_a, _n=n, _x=is_x):
            amt = getattr(game, "spell_x", 0) if _x else _n
            opps = game.opponents(ctrl)
            if opps and amt:
                tgt = min(opps, key=lambda o: o.life)
                game.deal_damage(None, tgt, amt)
                game.log(f"{ctrl.name}: {amt} de daño a {tgt.name}")
        return eff

    # fijar / duplicar el total de vida
    m = re.search(r"your life total becomes (\d+)", t)
    if m:
        def eff(game, ctrl, *_a, _v=int(m.group(1))):
            ctrl.life = _v
            game.log(f"{ctrl.name}: su vida pasa a {_v}")
        return eff
    if re.search(r"double your life total", t):
        def eff(game, ctrl, *_a):
            ctrl.life *= 2
            game.log(f"{ctrl.name} duplica su vida ({ctrl.life})")
        return eff

    m = re.search(r"(?:you )?gain (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            game.gain_life(ctrl, _n)
        return eff

    # duplicar contadores +1/+1 (en cada criatura tuya, o en una objetivo)
    if re.search(r"double the number of \+1/\+1 counters on each creature you control", t):
        def eff(game, ctrl, *_a):
            for pm in ctrl.creatures():
                have = pm.counters.get("+1/+1", 0)
                if have:
                    game.add_counters(pm, "+1/+1", have)
        return eff
    if re.search(r"double the number of (?:\+1/\+1 )?counters on target", t):
        def eff(game, ctrl, *_a):
            pool = list(ctrl.creatures())
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

            def _do(pm):
                for k, v in list(pm.counters.items()):
                    if v > 0:
                        pm.counters[k] = v * 2
                game.sba()
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura (duplicar contadores)", cands, _do)
        return eff

    # quitar todos los contadores de una permanente objetivo
    if re.search(r"remove all counters from target", t):
        def eff(game, ctrl, *_a):
            allp = [pm for pl in game.players for pm in pl.battlefield
                    if any(v > 0 for v in pm.counters.values())]
            if not allp:
                return
            # el bot (auto) apunta a la rival con más contadores (uso como remoción)
            allp.sort(key=lambda pm: (pm.controller is not ctrl,
                                      sum(pm.counters.values())), reverse=True)
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in allp]

            def _do(pm):
                pm.counters.clear()
                game.sba()
                game.log(f"{ctrl.name} quita todos los contadores de {pm.name}")
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una permanente (quitar contadores)", cands, _do)
        return eff

    # quema a UNA criatura objetivo: "deals N damage to target creature" (Flame Slash,
    # etc.). La quema a jugador/any target ya está arriba; esto cubre solo-criatura.
    m = re.search(r"deals? (\w+) damage to (?:up to \w+ )?target creature(?! or player)", t)
    if m and (m.group(1).lower() == "x" or _count_word(m.group(1))):
        n = _count_word(m.group(1))
        is_x = m.group(1).lower() == "x"

        def eff(game, ctrl, *_a, _n=n, _x=is_x):
            amt = getattr(game, "spell_x", 0) if _x else _n
            pool = game.legal_creature_targets(ctrl)
            if not pool or not amt:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(pm, _amt=amt):
                game.deal_damage(None, pm, _amt)
                game.log(f"{ctrl.name}: {_amt} de daño a {pm.name}")
                game.sba()
            _human_target_choice(game, ctrl, "etb_target",
                                 f"Elegí una criatura para {amt} de daño", cands, _do)
        return eff

    # edict: "target player/opponent sacrifices a creature" (sacrificio forzado; el
    # dueño elige — aquí la más débil). "each player sacrifices" ya lo cubre wipe.
    if re.search(r"target (?:player|opponent) sacrifices? a creature", t):
        def eff(game, ctrl, *_a):
            for o in game.opponents(ctrl):
                cr = o.creatures()
                if cr:
                    victim = min(cr, key=lambda x: (x.power, x.toughness))
                    game.to_graveyard(victim, "sacrificio forzado")
                    game.log(f"{o.name} sacrifica {victim.name}")
                    break                          # "target player": uno solo
        return eff

    # descartar forzado: "target player/opponent discards N" / "each opponent discards"
    m = re.search(r"(each opponent|target player|target opponent) discards? "
                  r"(their hand|\w+)", t)
    if m:
        who = m.group(1)
        qty = m.group(2)
        n = -1 if qty == "their hand" else (_count_word(qty) or 1)

        def eff(game, ctrl, *_a, _who=who, _n=n):
            opps = game.opponents(ctrl)
            picks = opps if _who == "each opponent" else opps[:1]
            for o in picks:
                cnt = len(o.hand) if _n < 0 else _n
                for _ in range(cnt):
                    if not o.hand:
                        break
                    if o.policy and hasattr(o.policy, "choose_discard"):
                        card = o.policy.choose_discard(game, o)
                    else:
                        card = o.hand[-1]
                    o.hand.remove(card)
                    o.graveyard.append(card)
                    game.emit("to_graveyard", player=o, card=card)
                game.log(f"{o.name} descarta {cnt} carta(s)")
        return eff

    # robo para jugadores: "target player/you draws N" (el que lanza) / "each player".
    m = re.search(r"(each player|target player|you) draws? (\w+) cards?", t)
    if m and (n := _count_word(m.group(2))):
        who = m.group(1)

        def eff(game, ctrl, *_a, _who=who, _n=n):
            if _who == "each player":
                for pl in game.players:
                    pl.draw(_n, game)
            else:
                ctrl.draw(_n, game)
        return eff

    # proliferate: +1 a cada tipo de contador ya presente (en cualquier permanente).
    if re.search(r"\bproliferate\b", t):
        def eff(game, ctrl, *_a):
            for pl in game.players:
                for pm in pl.battlefield:
                    for k in list(pm.counters.keys()):
                        if pm.counters.get(k, 0) > 0:
                            if k == "+1/+1":
                                game.add_counters(pm, k, 1)
                            else:
                                pm.counters[k] += 1
            game.sba()
            game.log(f"{ctrl.name} prolifera")
        return eff

    # otorgar keyword(s) EN MASA a tus criaturas hasta el fin del turno
    # ("creatures you control gain indestructible/trample/… until end of turn").
    mmk = re.search(r"creatures you control (?:gain|have) "
                    r"([a-z ,and]+?) until end of turn", t)
    if mmk:
        found = [key for name, key in _KEYWORD_WORDS
                 if re.search(r"\b" + name + r"\b", mmk.group(1))]
        if found:
            def eff(game, ctrl, *_a, _kw=tuple(found)):
                for pm in ctrl.creatures():
                    pm.temp_keywords |= set(_kw)
                game.log(f"{ctrl.name}: sus criaturas ganan {', '.join(_kw)} este turno")
            return eff

    # otorgar keyword(s) a una criatura objetivo hasta el fin del turno (truco de
    # combate: "target creature gains flying/trample/… until end of turn").
    mk = re.search(r"target creature (?:you control )?gains? "
                   r"([a-z ,and]+?) until end of turn", t)
    if mk:
        found = [key for name, key in _KEYWORD_WORDS
                 if re.search(r"\b" + name + r"\b", mk.group(1))]
        if found:
            def eff(game, ctrl, *_a, _kw=tuple(found)):
                pool = list(ctrl.creatures())      # normalmente buffeás la tuya
                if not pool:
                    return
                pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
                cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

                def _do(pm, _k=_kw):
                    pm.temp_keywords |= set(_k)
                    game.log(f"{pm.name} gana {', '.join(_k)} hasta el fin del turno")
                _human_target_choice(game, ctrl, "etb_target",
                                     "Elegí tu criatura a mejorar", cands, _do)
            return eff

    # pump/debuff a una criatura objetivo (sobre todo para disparos ETB; los HECHIZOS
    # ya los cubre _pump_spell_effect antes de esta capa).
    mp = re.search(r"target creature (?:you control )?gets ([+-]\d+)/([+-]\d+)", t)
    if mp:
        dp, dt = int(mp.group(1)), int(mp.group(2))
        debuff = dp < 0 or dt < 0

        def eff(game, ctrl, *_a, _p=dp, _t=dt, _deb=debuff):
            pool = (game.legal_creature_targets(ctrl) if _deb
                    else list(ctrl.creatures()))
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

            def _do(pm, _pp=_p, _tt=_t):
                pm.temp_pt[0] += _pp
                pm.temp_pt[1] += _tt
                game.sba()
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura", cands, _do)
        return eff

    # rebote a la mano de una criatura objetivo (sobre todo ETB tipo Man-o'-War;
    # el rebote de HECHIZO lo cubre _targeted_spell antes de esta capa).
    if re.search(r"return target creature to (?:its|their) owner'?s? hand", t):
        def eff(game, ctrl, *_a):
            pool = game.legal_creature_targets(ctrl)
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]

            def _do(pm):
                owner = pm.controller
                if pm in owner.battlefield:
                    owner.battlefield.remove(pm)
                    if not pm.is_token:
                        owner.hand.append(pm.card)
                    game.log(f"{ctrl.name} devuelve {pm.name} a la mano")
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura para rebotar", cands, _do)
        return eff

    # girar una criatura objetivo (ETB u otro; el spec de hechizo lo cubre aparte)
    if re.search(r"\btap target creature", t) and "untap" not in t:
        def eff(game, ctrl, *_a):
            pool = game.legal_creature_targets(ctrl)
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura para girar", cands,
                                 lambda pm: setattr(pm, "tapped", True))
        return eff

    # "el daño no se puede prevenir este turno" (Skullcrack, Flames of the Blood Hand):
    # se combina con el efecto principal (quema) — acá sólo activa el flag del turno.
    if re.search(r"damage can'?t be prevented this turn", t):
        def eff(game, ctrl, *_a):
            game.no_prevention_turn = True
            game.log(f"{ctrl.name}: el daño no se puede prevenir este turno")
        return eff

    # "las criaturas no pueden bloquear este turno" (Falter/Nature's Will): permite
    # un golpe sin bloqueos.
    if re.search(r"creatures can'?t block this turn", t):
        def eff(game, ctrl, *_a):
            game.no_block_turn = True
            game.log(f"{ctrl.name}: las criaturas no pueden bloquear este turno")
        return eff

    # ganar el control de TODAS las criaturas (Insurrection/Mass Mutiny-style),
    # normalmente hasta el fin del turno + destrabar + prisa (finisher de robo).
    # Va ANTES de "untap all" porque suele incluir "untap all creatures" primero.
    if re.search(r"gain control of all creatures", t):
        temp = "until end of turn" in t or "end of turn" in t
        untap = "untap" in t
        haste = "haste" in t or temp

        def eff(game, ctrl, *_a, _temp=temp, _un=untap, _h=haste):
            for o in game.opponents(ctrl):
                for perm in list(o.battlefield):
                    if not perm.is_creature():
                        continue
                    o.battlefield.remove(perm)
                    perm.controller = ctrl
                    ctrl.battlefield.append(perm)
                    if _un:
                        perm.tapped = False
                    if _h:
                        perm.summoning_sick = False
                    if _temp:
                        perm.return_to = o
                        game.control_returns.append(perm)
            game.log(f"{ctrl.name} toma el control de todas las criaturas")
        return eff

    # enderezar: "untap all creatures/lands/permanents you control" o "untap target …"
    m = re.search(r"untap all (creatures|lands|permanents)", t)
    if m:
        kindw = m.group(1)

        def eff(game, ctrl, *_a, _k=kindw):
            for pm in ctrl.battlefield:
                if (_k == "permanents" or (_k == "creatures" and pm.is_creature())
                        or (_k == "lands" and pm.card.is_land())):
                    pm.tapped = False
            game.log(f"{ctrl.name} endereza sus {_k}")
        return eff
    if re.search(r"untap target (?:creature|permanent|land)", t):
        def eff(game, ctrl, *_a):
            tapped = [pm for pm in ctrl.battlefield if pm.tapped]
            if tapped:
                tapped.sort(key=lambda x: (x.power, x.toughness), reverse=True)
                tapped[0].tapped = False
                game.log(f"{ctrl.name} endereza {tapped[0].name}")
        return eff

    # girar en masa: "tap all creatures (target player/opponent controls)" (Sleep, etc.)
    if re.search(r"tap all (?:untapped )?creatures", t) and "untap" not in t:
        rival_only = "control" in t and "you control" not in t
        def eff(game, ctrl, *_a, _rival=rival_only):
            pls = game.opponents(ctrl) if _rival else game.players
            for pl in pls:
                for pm in pl.creatures():
                    pm.tapped = True
            game.log(f"{ctrl.name} gira las criaturas "
                     + ("rivales" if _rival else "en juego"))
        return eff

    # un JUGADOR objetivo pierde N de vida (drenaje dirigido)
    m = re.search(r"target (?:player|opponent) loses (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            opps = game.opponents(ctrl)
            if opps:
                tgt = min(opps, key=lambda o: o.life)
                tgt.life -= _n
                game.log(f"{tgt.name} pierde {_n} de vida")
        return eff

    # edict: "each opponent sacrifices a creature" (variante de "target player")
    if re.search(r"each opponent sacrifices? a creature", t):
        def eff(game, ctrl, *_a):
            for o in game.opponents(ctrl):
                cr = o.creatures()
                if cr:
                    victim = min(cr, key=lambda x: (x.power, x.toughness))
                    game.to_graveyard(victim, "sacrificio forzado")
                    game.log(f"{o.name} sacrifica {victim.name}")
        return eff

    # evasión: "target creature can't be blocked this turn" -> keyword temporal
    if re.search(r"target creature can'?t be blocked", t):
        def eff(game, ctrl, *_a):
            pool = list(ctrl.creatures())
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

            def _do(pm):
                pm.temp_keywords.add("unblockable")
                game.log(f"{pm.name} no puede ser bloqueada este turno")
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí tu atacante", cands, _do)
        return eff

    # rebote masivo: "return all creatures to their owners' hands" (Evacuation…)
    if re.search(r"return all creatures? to (?:their )?owners'? hands?", t):
        def eff(game, ctrl, *_a):
            for pl in game.players:
                for pm in list(pl.battlefield):
                    if not pm.is_creature():
                        continue
                    pl.battlefield.remove(pm)
                    if pm.is_token:
                        continue
                    if pm.card is pl.commander_card:
                        pl.command.append(pm.card)
                    else:
                        pl.hand.append(pm.card)
            game.log(f"{ctrl.name}: todas las criaturas vuelven a la mano")
        return eff

    # Fog: "prevent all combat damage (that would be dealt) this turn"
    if re.search(r"prevent all combat damage", t):
        def eff(game, ctrl, *_a):
            game.fog_turn = True
            game.log(f"{ctrl.name}: se previene todo el daño de combate este turno")
        return eff

    # prevención general: "prevent all damage ... to you" (todo) o "prevent the next
    # N damage ..." (escudo de N). Aprox: protege al que lanza (uso más común).
    if re.search(r"prevent all (?:the )?damage", t) and "combat damage" not in t:
        def eff(game, ctrl, *_a):
            ctrl.prevent_all = True
            game.log(f"{ctrl.name}: se previene todo el daño hasta el fin del turno")
        return eff
    mpv = re.search(r"prevent the next (\w+) damage", t)
    if mpv and (n := _count_word(mpv.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            ctrl.prevent += _n
            game.log(f"{ctrl.name}: escudo de {_n} de prevención de daño este turno")
        return eff

    # descarte dirigido con revelado (Thoughtseize/Duress): el rival revela la mano y
    # descarta su mejor no-tierra (o lo que pida el filtro básico).
    if (re.search(r"target (?:opponent|player) reveals their hand", t)
            and "discard" in t):
        noncre = "noncreature" in t or "nonland" in t
        def eff(game, ctrl, *_a, _noncre=noncre):
            opps = game.opponents(ctrl)
            if not opps:
                return
            o = max(opps, key=lambda x: len(x.hand))
            if not o.hand:
                return
            pool = [c for c in o.hand if not c.is_land()
                    and (not _noncre or "creature" not in c.types)] or o.hand
            card = max(pool, key=lambda c: (c.cost.cmc if c.cost else 0))
            o.hand.remove(card)
            o.graveyard.append(card)
            game.emit("to_graveyard", player=o, card=card)
            game.log(f"{ctrl.name} hace descartar {card.name} a {o.name}")
        return eff

    # explore: revelar el tope (tierra -> mano; si no, +1/+1 y decidir arriba/cementerio)
    if re.search(r"\bexplores?\b", t):
        return _explore_effect()

    # fateseal: mirar el tope de la biblioteca de un RIVAL
    mf = re.search(r"look at the top (\w+) cards? of (?:target )?"
                   r"(?:opponent|player|defending player)'?s? library", t)
    if mf and (fn := _count_word(mf.group(1))):
        return _scry_surveil_effect(fn, False, fateseal=True)

    # scry / surveil (con "then draw" opcional): el humano decide carta por carta.
    ms = re.search(r"\b(scry|surveil)\s+(\w+)", t)
    if ms and (sn := _count_word(ms.group(2))):
        to_gy = ms.group(1) == "surveil"
        dn, dfirst = 0, False
        md = re.search(r"draw (\w+) cards?", t)
        if md and (dd := _count_word(md.group(1))):
            dn = dd
            dfirst = md.start() < ms.start()   # "draw ..., then scry" -> robar primero
        return _scry_surveil_effect(sn, to_gy, draw_n=dn, draw_first=dfirst)

    # tutor: "search your library for a(n) [tipo] card ... into your hand / battlefield".
    # Excluye la búsqueda de tierras (ya cubierta por el tag ramp -> _g_ramp).
    mt = re.search(r"search your library for (a|an|one|two|up to \w+)?\s*"
                   r"([\w\- ]*?)\s*cards?", t)
    if mt and "land" not in (mt.group(2) or ""):
        pred, label_key = _card_type_pred(mt.group(2))
        to_bf = bool(re.search(r"onto the battlefield|into play", t))
        may = bool(re.search(r"you may search|search your library for up to", t))
        lbl = {"carta": "una carta"}.get(label_key, f"una carta de tipo {label_key}")
        return _search_library_effect(pred, to_battlefield=to_bf,
                                      allow_none=may, label=lbl)

    m = re.search(r"\bmill(?:s)? (\w+)", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            cards.mill(game, ctrl, _n)
        return eff

    # impulse: "exile the top (N) card(s) of your library ... you may play". Va a la
    # zona de exilio-jugable (ctrl.impulse): jugable ESTE turno; lo que no se juega
    # queda en el exilio al terminar el turno (engine.end_turn).
    m = re.search(r"exile the top (\w+ )?cards? of your library.{0,80}?(?:you )?may play", t)
    if m:
        n = _count_word((m.group(1) or "one").strip()) or 1

        def eff(game, ctrl, *_a, _n=min(n, 4)):
            moved = []
            for _ in range(_n):
                if ctrl.library:
                    c = ctrl.library.pop()
                    ctrl.impulse.append(c)
                    moved.append(c.name)
            if moved:
                game.log(f"{ctrl.name} exilia del tope {', '.join(moved)} "
                         f"y puede jugarla(s) este turno")
        return eff

    # reanimar al campo desde el cementerio (el TUYO, o CUALQUIERA con "from a
    # graveyard ... under your control"). El humano elige; el bot toma la mejor.
    if re.search(r"(?:return|put) .{0,70}?from (?:your|a) graveyard (?:on)?to the "
                 r"battlefield", t):
        lim = int(mvm.group(1)) if (mvm := re.search(r"mana value (\d+) or less", t)) else None
        cre = "creature card" in t
        any_gy = "from a graveyard" in t     # reanimación de cualquier cementerio

        def eff(game, ctrl, *_a, _lim=lim, _cre=cre, _any=any_gy):
            def ok(c):
                if not _is_permanent_card(c):        # instantáneos/conjuros NO al campo
                    return False
                if _cre and "creature" not in c.types:
                    return False
                if _lim is not None and c.cost and c.cost.cmc > _lim:
                    return False
                return True
            zones = ([(pl, pl.graveyard) for pl in game.players] if _any
                     else [(ctrl, ctrl.graveyard)])
            cands = [(owner, c) for owner, gy in zones for c in gy if ok(c)]
            if not cands:
                game.log(f"{ctrl.name}: sin carta válida en el cementerio para revivir")
                return
            cands.sort(key=lambda oc: (oc[1].cost.cmc if oc[1].cost else 0), reverse=True)
            picks = [c for _o, c in cands]
            owner_of = {id(c): o for o, c in cands}

            def _do(pick):
                owner = owner_of.get(id(pick))
                if owner and pick in owner.graveyard:
                    owner.graveyard.remove(pick)
                    game.move_to_battlefield(pick, ctrl)   # bajo control del que reanima
                    game.log(f"{ctrl.name} revive {pick.name} del cementerio")
            _pick_card_from_zone(game, ctrl, picks, _do,
                                 "Elegí una carta del cementerio para revivir")
        return eff

    # regresar una carta del cementerio a la mano (elección automática + log)
    if re.search(r"return .{0,70}?from your graveyard to your hand", t):
        def eff(game, ctrl, *_a):
            cands = [c for c in ctrl.graveyard if not c.is_land()]
            if not cands:
                return
            cands.sort(key=lambda c: (c.cost.cmc if c.cost else 0), reverse=True)

            def _do(pick):
                if pick in ctrl.graveyard:
                    ctrl.graveyard.remove(pick)
                    ctrl.hand.append(pick)
                    game.log(f"{ctrl.name} recupera {pick.name} del cementerio a la mano")
            _pick_card_from_zone(game, ctrl, cands, _do,
                                 "Elegí una carta del cementerio para tu mano")
        return eff

    # recuperar una carta tuya desde el exilio (a la mano o al campo, con elección)
    mex = re.search(
        r"(?:return|put) .{0,70}?(?:from|in|among the) .{0,20}?exile[d]?.{0,50}?"
        r"(?:to|into|onto) (?:your |the )?(hand|battlefield)", t)
    if mex:
        to_bf = mex.group(1) == "battlefield"

        def eff(game, ctrl, *_a):
            pool = list(getattr(ctrl, "exile", []) or [])
            cands = [c for c in pool if (not to_bf) or _is_permanent_card(c)]
            if not cands:
                return
            cands.sort(key=lambda c: (c.cost.cmc if c.cost else 0), reverse=True)

            def _do(pick):
                if pick in getattr(ctrl, "exile", []):
                    ctrl.exile.remove(pick)
                    if to_bf:
                        game.move_to_battlefield(pick, ctrl)
                        game.log(f"{ctrl.name} devuelve {pick.name} del exilio al campo")
                    else:
                        ctrl.hand.append(pick)
                        game.log(f"{ctrl.name} recupera {pick.name} del exilio a la mano")
            _pick_card_from_zone(game, ctrl, cands, _do,
                                 "Elegí una carta del exilio", kind="exile_pick")
        return eff

    # revelar las primeras N: quedarse una TIERRA en la mano, el resto al cementerio.
    m = re.search(r"(?:reveal|look at) the top (\w+) cards?.{0,140}?land card.{0,50}?hand", t)
    if m and (n := _count_word(m.group(1))):
        return _look_take_effect(
            n, lambda c: c.is_land(), rest_dest="graveyard", allow_none=True,
            kind="reveal_land",
            prompt="Elegí una tierra para tu mano (el resto va al cementerio)")

    # mirar/revelar las top N y llevarse UNA a la mano (cualquier tipo, o el que pida
    # el texto); el resto al fondo o al cementerio. Cubre "look at top N ... put one
    # into your hand" y el caso singular "reveal top card; if it's a [tipo] ... hand".
    mlt = re.search(r"(?:look at|reveal) the top (?:(\w+) )?cards?", t)
    if mlt and "into your hand" in t:
        ln = _count_word(mlt.group(1)) if mlt.group(1) else 1
        if ln:
            mtype = re.search(r"put (?:one|a|an|the|that)?\s*([\w\- ]*?)\s*"
                              r"cards?[^.]*into your hand", t)
            pred, _lk = _card_type_pred(mtype.group(1) if mtype else "")
            tail = t.split("into your hand", 1)[-1]
            rest = "graveyard" if "graveyard" in tail else "bottom"
            may = " may " in t
            return _look_take_effect(ln, pred, rest_dest=rest, allow_none=may,
                                     kind="look_take",
                                     prompt="Elegí una carta para tu mano")

    # respaldo: cualquier "look at the top N cards of your library" que no encajó en
    # los casos de arriba (mirar y reordenar, "put them back in any order", exiliar
    # una…). Lo tratamos como Scry N: el humano VE cada carta y decide arriba/fondo,
    # en vez de que la habilidad no muestre nada.
    ml = re.search(r"look at the top (\w+) cards? of your library", t)
    if ml and (ln := _count_word(ml.group(1))):
        return _scry_surveil_effect(ln, False)

    # (populate ya se cablea aparte vía _populate_effect en build_card_from_data)

    # "(you may) draw [N|an additional] card(s)": el controlador roba. Si es
    # OPCIONAL ('you may'), el humano decide; si es obligatorio, roba directo.
    md = re.search(r"(?:you may )?draw (a|an|one|two|three|four|five|\d+)"
                   r"(?: additional)? cards?", t)
    if md:
        n = _count_word(md.group(1)) or 1
        optional = bool(re.search(r"you may draw", t))

        def eff(game, ctrl, *_a, _opt=optional, _n=n):
            def _do(g, c):
                c.draw(_n, g)
                g.log(f"{c.name} roba {_n} carta(s)")
            if _opt:
                game.may(ctrl, f"¿Robar {n} carta(s)?", _do)
            else:
                _do(game, ctrl)
        return eff

    return None


def build_card_from_data(data: dict) -> Card:
    """Construye una Card desde un dict tipo Scryfall (name, mana_cost,
    type_line, power, toughness, keywords, color_identity)."""
    data = _prefer_front_face(data)
    name = data.get("name", "?")
    types, supertypes, subtypes = parse_type_line(data.get("type_line", ""))
    color_id = {_COLOR_MAP[c] for c in data.get("color_identity", [])
                if c in _COLOR_MAP}
    kws = {k.lower().replace(" ", "_") for k in data.get("keywords", [])}
    kws &= KEYWORDS

    cost = None
    if "land" not in types:
        cost = parse_cost(mana_cost_to_str(data.get("mana_cost", "")))

    card = Card(
        name=name,
        types=types or {"creature"},
        cost=cost,
        power=_int_or_zero(data.get("power")),
        toughness=_int_or_zero(data.get("toughness")),
        keywords=kws,
        supertypes=supertypes,
        subtypes=subtypes,
        color_id=color_id,
        x_spell=("{X}" in (data.get("mana_cost", "") or "").upper()),
    )

    # tags: de creatura + derivados (aprox) del texto de la carta, para que la
    # capa de efectos genericos funcione tambien con cartas de Scryfall
    card.tags = _derive_tags(data.get("oracle_text", ""), card.types)
    # reducciones de coste dinámicas (convoke / delve / affinity for artifacts)
    _ktext = (" ".join(data.get("keywords", []) or []) + " "
              + (data.get("oracle_text", "") or "")).lower()
    if "convoke" in _ktext:
        card.tags = card.tags | {"convoke"}
    if "delve" in _ktext:
        card.tags = card.tags | {"delve"}
    if "affinity for artifacts" in _ktext:
        card.tags = card.tags | {"affinity_art"}
    # auras: anexar a un huésped y bufearlo (antes de la capa ETB genérica)
    _wire_aura(card, data.get("oracle_text", ""))

    # jugar/lanzar desde el CEMENTERIO (flashback / escape / unearth / embalm /
    # disturb / recursión). Descriptor en card.gy_play; interactive lo ofrece.
    gyp = _parse_gy_play(data.get("oracle_text", ""), card.types)
    if gyp:
        card.gy_play = gyp
    # Fase B/C/D: jugar desde el exilio (foretell), habilidades y disparos desde
    # el cementerio.
    _fc = _parse_foretell(data.get("oracle_text", ""))
    if _fc is not None:
        card.foretell = _fc
    _gya = _parse_gy_abilities(data.get("oracle_text", ""))
    if _gya:
        card.gy_abilities = _gya
    _gyt = _parse_gy_triggers(data.get("oracle_text", ""))
    if _gyt:
        card.gy_triggers = _gyt
    _gyg = _parse_gy_grant(data.get("oracle_text", ""))
    if _gyg:
        card.gy_grant = _gyg
    _etc = _parse_etb_counters(data.get("oracle_text", ""))
    if _etc:
        card.etb_counters = _etc

    # Produccion de mana: usar `produced_mana` de Scryfall (el mana REAL que
    # produce la carta), no la identidad de color — las tierras no basicas son
    # objetos incoloros y su identidad suele venir vacia. Aplica a tierras y a
    # artefactos de mana (signets, rocas); las tierras basicas caen al fallback.
    produced = [_COLOR_MAP[c] for c in (data.get("produced_mana") or [])
                if c in _COLOR_MAP]
    if "land" in types:
        colors = produced or [c for c in (W, U, B, R, G) if c in color_id] or [C]
        opts = {c: 1 for c in colors}
        card.produces = (lambda perm, pl, _o=opts: dict(_o))
        card.enters_tapped = bool(data.get("enters_tapped"))
    elif produced and "artifact" in types:
        # roca de mana importada (Fellwar Stone, signets, etc.)
        opts = {c: 1 for c in produced}
        card.produces = (lambda perm, pl, _o=opts: dict(_o))
        card.tags = card.tags | {"ramp"}

    # SAGA (encantamiento con capítulos): aproximación jugable. Al entrar corre el
    # capítulo I; en cada mantenimiento del dueño avanza un capítulo (contador de
    # lore) y se sacrifica al terminar el último. Se cablea ANTES de la capa genérica.
    if "saga" in data.get("type_line", "").lower():
        saga = _parse_saga(data.get("oracle_text", ""))
        if saga:
            _chapters, _maxch = saga

            def _saga_run(game, ctrl, perm, n, _ch=_chapters, _mx=_maxch):
                perm.counters["lore"] = n
                e = _ch.get(n)
                if e:
                    e(game, ctrl)
                game.log(f"{perm.name}: capítulo {n}")
                if n >= _mx:
                    game.to_graveyard(perm, "saga completa")

            card.on_etb = (lambda g, ctrl, perm, _run=_saga_run: _run(g, ctrl, perm, 1))

            def _saga_upkeep(game, perm, _run=_saga_run, **_kw):
                _run(game, perm.controller, perm, perm.counters.get("lore", 0) + 1)

            card.triggers = dict(card.triggers)
            card.triggers["upkeep"] = _saga_upkeep
            card.tags = card.tags | {"saga"}

    # "Choose a creature type" + anthem tribal ("creatures ... of the chosen type
    # get +N/+N"): al entrar el humano elige el tipo (pending_choice); el bonus se
    # aplica como efecto estático (static_mod) a las criaturas de ese tipo.
    _otc = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    if "choose a creature type" in _otc and "of the chosen type" in _otc:
        mb = re.search(r"of the chosen type get \+(\d+)/\+(\d+)", _otc)
        dp, dt = (int(mb.group(1)), int(mb.group(2))) if mb else (1, 1)
        yours = "you control" in _otc

        def _etb_choose_type(game, ctrl, perm, _dp=dp, _dt=dt):
            # tipos de criatura del jugador, ORDENADOS por frecuencia (los que más
            # tiene primero) y con más peso a lo que ya está en juego, para que su
            # tribu real siempre aparezca entre las opciones. Antes se recortaba a
            # 14 en orden de escaneo y una tribu podía quedar fuera (bug).
            weight, first = {}, {}
            zones = ((ctrl.battlefield, 3), (ctrl.hand, 2),
                     (ctrl.command, 3), (ctrl.library, 1))
            order = 0
            for zone, w in zones:
                for it in zone:
                    cd = getattr(it, "card", it)
                    if not cd.is_creature():
                        continue
                    for st in cd.subtypes:
                        k = st.lower()
                        weight[k] = weight.get(k, 0) + w
                        if k not in first:
                            first[k] = (st, order)
                            order += 1
            found = [first[k][0] for k in sorted(
                weight, key=lambda k: (-weight[k], first[k][1]))]
            if not found:
                found = ["Human", "Elf", "Goblin", "Zombie", "Soldier", "Wizard"]
            found = found[:20]

            def _apply(idx, _t=found):
                if idx is not None and 0 <= idx < len(_t):
                    perm.chosen_type = _t[idx]
                    game.log(f"{ctrl.name} elige el tipo {_t[idx]}")

            if ctrl is getattr(game, "interactive_human", None):
                game.pending_choice = {
                    "kind": "creature_type",
                    "prompt": "Elegí un tipo de criatura",
                    "options": [{"i": i, "name": t, "ok": True}
                                for i, t in enumerate(found)],
                    "allow_none": False, "_apply": _apply,
                }
            else:   # bot: el tipo más común entre sus criaturas
                counts = {}
                for it in ctrl.battlefield:
                    cd = getattr(it, "card", it)
                    if cd.is_creature():
                        for st in cd.subtypes:
                            counts[st] = counts.get(st, 0) + 1
                best = max(counts, key=counts.get) if counts else found[0]
                perm.chosen_type = best
                game.log(f"{ctrl.name} elige el tipo {best}")

        card.on_etb = _etb_choose_type

        def _sm(source, target, _dp=dp, _dt=dt, _yours=yours):
            ct = getattr(source, "chosen_type", None)
            if not ct or not target.is_creature():
                return (0, 0)
            if _yours and target.controller is not source.controller:
                return (0, 0)
            if ct.lower() in {s.lower() for s in target.card.subtypes}:
                return (_dp, _dt)
            return (0, 0)

        card.static_mod = _sm
        card.tags = card.tags | {"anthem"}

    # planeswalker: lealtad inicial + habilidades del texto de Scryfall. Sin
    # esto entraría con lealtad 0 y moriría al instante (SBA), y no tendría
    # habilidades activables. Se cablea ANTES de la capa genérica.
    if "planeswalker" in types:
        loy = _int_or_zero(data.get("loyalty"))
        abils, texts = _planeswalker_abilities(data.get("oracle_text", ""))
        # sin lealtad válida en los datos, entraría con 0 y moriría al instante
        # (SBA). Como todo planeswalker tiene lealtad inicial impresa, usamos un
        # valor por defecto razonable para que no desaparezca del campo.
        card.loyalty = loy if loy > 0 else 3
        card.loyalty_abilities = abils
        card.loyalty_texts = texts

    # hechizo MODAL ("Choose one — ...): construir la lista de modos para que el
    # jugador elija. Se cablea antes que la remoción/genérica para no aplanarlo.
    if {"instant", "sorcery"} & types:
        modal = _parse_modes(data.get("oracle_text", ""))
        if modal is not None:
            modes, pick = modal
            card.modes = tuple(modes)
            card.mode_pick = pick
            for md in modes:
                if md.get("target_spec"):
                    card.target_spec = md["target_spec"]
                    card.target_count = md.get("target_count", 1)
                    break
            card.tags = card.tags | {"modal"}

    # counterspells (Scryfall no trae el gancho): "counter target spell". Se cablea
    # primero para que la capa de remoción no lo malinterprete.
    if ({"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve
            and re.search(r"counter target (?:[\w\- ]+ )?spell",
                          (data.get("oracle_text", "") or ""), re.I)):
        card.on_cast_resolve = _counter_spell_effect()
        card.target_spec = "stack_spell"
        card.target_count = 1
        card.tags = card.tags | {"counter"}

    # "puedes jugar/lanzar desde tu cementerio este turno" (Yawgmoth's Will…).
    if ({"instant", "sorcery"} & types and not card.on_cast_resolve
            and re.search(r"(?:play|cast)[\w ,]*from your graveyard this turn",
                          (data.get("oracle_text", "") or ""), re.I)):
        card.on_cast_resolve = _gy_mass_cast_effect()
        card.tags = card.tags | {"gy_recast"}

    # Stifle: "counter target activated or triggered ability".
    if ({"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve
            and re.search(r"counter target (?:activated|triggered)[\w /]*ability",
                          (data.get("oracle_text", "") or ""), re.I)):
        card.on_cast_resolve = _counter_ability_effect()
        card.target_spec = "stack_ability"
        card.target_count = 1
        card.tags = card.tags | {"counter"}

    # hechizos DIRIGIDOS especiales (parpadeo / robo de control / clon): se cablean
    # ANTES de la remoción para no colapsarlos a "destruir".
    if {"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve:
        sp = _targeted_special(data.get("oracle_text", ""))
        if sp is not None:
            eff, spec, count = sp
            card.on_cast_resolve = eff
            card.target_spec = spec
            card.target_count = max(1, count)
            card.tags = card.tags | {"targeted"}

    # barrida CON rider de fichas ("destroy all creatures, then create N tokens per
    # your nontoken creature destroyed this way"): p. ej. Ceaseless Conflict. Se
    # cablea antes de la capa genérica, que solo pondría el wrath pelado sin fichas.
    if {"instant", "sorcery"} & types and not card.on_cast_resolve:
        wt = _wipe_then_tokens_effect(data.get("oracle_text", ""))
        if wt is not None:
            card.on_cast_resolve = wt
            card.tags = card.tags | {"wipe"}

    # remoción / bounce DIRIGIDA (instantáneo o conjuro): dejar elegir objetivos.
    # Se cablea ANTES de la capa genérica para que no la reemplace.
    if {"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve:
        spec = _targeted_spell(data.get("oracle_text", ""))
        if spec is not None:
            mode, count, tspec = spec
            card.on_cast_resolve = cards.remove_targets(mode)
            card.target_spec = tspec
            card.target_count = max(1, count)
            card.tags = card.tags | {"removal"}

    # pump / debuff de HECHIZO (+X/+X o -X/-X), dirigido o masivo: Giant Growth,
    # Grasp of Darkness (-4/-4), pumps de equipo, Infest… La capa de remoción no
    # los cubre (no destruyen: solo modifican P/T), así que se cablean aquí.
    if {"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve:
        ps = _pump_spell_effect(data.get("oracle_text", ""))
        if ps is not None:
            eff, spec, count = ps
            card.on_cast_resolve = eff
            if spec is not None:
                card.target_spec = spec
                card.target_count = max(1, count)
            card.tags = card.tags | {"pump"}

    # efecto genérico CON MONTO leído del oracle (fichas, quema a cada rival,
    # ganancia de vida, mill). Cubre creaturas/hechizos comunes que la capa por
    # tags no modela. No pisa remoción/barrida (más definitorias) ni efectos ya
    # cableados. Se resuelve al entrar (permanentes) o al resolverse (hechizos).
    if (not card.on_cast_resolve and not card.on_etb and not card.modes
            and not (card.tags & {"wipe", "removal", "saga"})):
        geff = _generic_amount_effect(data.get("oracle_text", ""))
        if geff is not None:
            if {"instant", "sorcery"} & types:
                card.on_cast_resolve = geff
            elif ({"creature", "artifact", "enchantment"} & types
                  and re.search(r"\benters?\b", (data.get("oracle_text", "") or "").lower())):
                # solo como ETB si el texto tiene un disparo de entrada; si el efecto
                # pertenece a otro disparo (p. ej. "whenever ~ attacks"), no lo duplicamos
                card.on_etb = geff

    # ETB dirigido en un PERMANENTE (p. ej. destruir criatura/tierra al entrar):
    # se cablea aunque tenga tag removal/wipe (esos tags apuntan al camino de CAST,
    # que no aplica a una criatura/artefacto que entra al campo).
    if (not card.on_etb and not card.modes
            and {"creature", "artifact", "enchantment"} & types
            and re.search(r"\benters?\b", (data.get("oracle_text", "") or "").lower())):
        geff = _generic_amount_effect(data.get("oracle_text", ""))
        if geff is not None:
            card.on_etb = geff

    # populate ("Populate" / "then populate"): copia tu mejor ficha de criatura.
    # Se ejecuta al resolverse el hechizo (encadenado con el efecto previo si lo hay).
    if re.search(r"\bpopulate\b", (data.get("oracle_text", "") or ""), re.I) \
            and {"instant", "sorcery"} & types:
        _pop = _populate_effect()
        _prev = card.on_cast_resolve
        if _prev is None:
            card.on_cast_resolve = _pop
        else:
            def _combo(g, c, tg, _p=_prev, _q=_pop):
                _p(g, c, tg)
                _q(g, c, tg)
            card.on_cast_resolve = _combo
        card.tags = card.tags | {"populate"}

    # Cascade: al lanzar el hechizo, cascada. Se encadena a on_cast_resolve (hechizos)
    # o a on_etb (permanentes) para dispararse al ponerse en juego / resolverse.
    if "cascade" in _ktext:
        _casc = _cascade_effect(card.cost.cmc if card.cost else 0)
        if {"instant", "sorcery"} & types:
            _prev = card.on_cast_resolve
            card.on_cast_resolve = (_casc if _prev is None else
                (lambda g, c, tg, _p=_prev, _q=_casc: (_p(g, c, tg), _q(g, c))))
        else:
            _prev = card.on_etb
            card.on_etb = (
                (lambda g, c, perm, _q=_casc: _q(g, c)) if _prev is None else
                (lambda g, c, perm, _p=_prev, _q=_casc: (_p(g, c, perm), _q(g, c))))
        card.tags = card.tags | {"cascade"}

    # habilidades activadas con coste de maná (creaturas/permanentes/tierras):
    # "{cost}: efecto" -> se pueden activar en juego pagando el maná.
    if not ({"instant", "sorcery"} & types):
        ab = _parse_activated(data.get("oracle_text", ""), data.get("name", ""))
        if ab:
            card.activated_abilities = ab

    # disparo "al atacar" (whenever ~ attacks, ...): p. ej. Laelia (exiliar el tope
    # y poder jugarla). Se cablea como trigger de "attacks".
    atk_eff = _attack_trigger_effect(data.get("oracle_text", ""))
    if atk_eff is not None and "attacks" not in card.triggers:
        card.triggers = dict(card.triggers)
        card.triggers["attacks"] = atk_eff

    # anthem estático genérico ("creatures you control get +X/+X" / "have <kw>"),
    # p. ej. importado de Scryfall. Se cablea antes de la capa por tags.
    if ({"creature", "artifact", "enchantment", "planeswalker", "land"} & types
            and card.static_mod is None):
        sm, akw = _static_anthem(data.get("oracle_text", ""))
        if sm is not None:
            card.static_mod = sm
            card.tags = card.tags | {"anthem"}
        if akw:
            card.anthem_keywords = set(akw)
            card.anthem_others = "other creatures" in (
                data.get("oracle_text", "") or "").lower()

    # "play an additional land / X additional lands on each of your turns"
    # (Exploration, Azusa, Dryad…): sube el límite de tierras del controlador.
    _lt = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    ml = re.search(r"play (\w+) additional lands?(?: on each)?(?: of your)? turn", _lt)
    if ml:
        w = ml.group(1)
        card.extra_land = (1 if w in ("a", "an", "one")
                           else 99 if w == "any"
                           else (_count_word(w) or 1))

    # Exalted: "whenever a creature you control attacks alone, that creature gets
    # +1/+1" (o la keyword "exalted"). Cada instancia suma +1/+1 al atacante solo.
    if "exalted" in _lt or re.search(r"attacks alone.{0,40}gets \+1/\+1", _lt):
        card.exalted = getattr(card, "exalted", 0) + 1

    # reducción de coste ESTÁTICA a tus hechizos: "<tipo> spells you cast cost {N}
    # less to cast" (Goblin Electromancer, Medallion, etc.).
    mred = re.search(r"(creature|artifact|instant and sorcery|instant or sorcery|"
                     r"noncreature)?\s*spells? you cast cost \{(\d+)\} less", _lt)
    if mred:
        amt = int(mred.group(2))
        w = (mred.group(1) or "").strip()
        filt = ("creature" if w == "creature"
                else "artifact" if w == "artifact"
                else "noncreature" if "noncreature" in w
                else "instant_sorcery" if "instant" in w
                else "any")
        card.spell_discount = (amt, filt)

    # Storm: al lanzarse, se copia por cada hechizo lanzado antes este turno (el
    # motor repite el efecto). Marcamos con un tag; sólo aplica a instant/sorcery.
    if re.search(r"\bstorm\b", _lt) and {"instant", "sorcery"} & types:
        card.tags = card.tags | {"storm"}

    # Buyback {N}: coste adicional de maná; si se paga, la carta vuelve a la mano.
    mbb = re.search(r"buyback \{(\d+)\}", _lt)
    if mbb and {"instant", "sorcery"} & types:
        card._buyback_cost = int(mbb.group(1))

    # Replicate <coste>: coste que se paga varias veces; cada pago copia el hechizo.
    # Aprox: coste convertido a CMV entero; el motor paga cuanto se pueda.
    mrep = re.search(r"replicate ((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mrep and {"instant", "sorcery"} & types:
        cmv = 0
        for sym in re.findall(r"\{([wubrgc0-9/x]+)\}", mrep.group(1)):
            cmv += int(sym) if sym.isdigit() else 1
        if cmv > 0:
            card._replicate_cost = cmv

    # Echo {coste}: al entrar queda pendiente; en tu PRÓXIMO mantenimiento pagás el
    # coste de echo o la sacrificás. Auto: el bot paga si puede, si no la sacrifica.
    mecho = re.search(r"echo ((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mecho and "creature" in types:
        echo_cost = parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mecho.group(1)))))
        card.echo = echo_cost

        def _echo_etb(g, ctrl, perm, _prev=card.on_etb):
            perm._echo_pending = True
            perm._echo_turn = g.turn
            if _prev:
                _prev(g, ctrl, perm)
        card.on_etb = _echo_etb

        def _echo_upkeep(g, perm, _cost=echo_cost, **_kw):
            if not getattr(perm, "_echo_pending", False):
                return
            if getattr(perm, "_echo_turn", g.turn) >= g.turn:
                return                     # aún no llegó tu próximo mantenimiento
            ctrl = perm.controller
            perm._echo_pending = False
            if ctrl.can_pay(_cost):
                ctrl.pay(_cost)
                g.log(f"{ctrl.name} paga el echo de {perm.name}")
            else:
                g.log(f"{ctrl.name} no paga el echo: sacrifica {perm.name}")
                g.to_graveyard(perm, "echo impago")
        card.triggers = dict(card.triggers)
        card.triggers.setdefault("upkeep", _echo_upkeep)

    # Prohibición de ganar vida (Erebos, Archfiend of Despair, Sulfuric Vortex…).
    if re.search(r"players can'?t gain life", _lt):
        card.stops_lifegain = "all"
    elif re.search(r"(?:your opponents|each opponent|opponents) can'?t gain life", _lt):
        card.stops_lifegain = "opponents"

    # Devour N: al entrar, devora tus FICHAS de criatura (forraje) y entra con N
    # contadores +1/+1 por cada una (aprox: sólo come fichas, no cartas reales).
    mdev = re.search(r"devour (\d+)", _lt)
    if mdev and "creature" in types:
        mult = int(mdev.group(1))

        def _devour(g, ctrl, perm, _m=mult):
            fodder = [pm for pm in list(ctrl.battlefield)
                      if pm.is_creature() and pm.is_token and pm is not perm]
            for pm in fodder:
                g.to_graveyard(pm, "devorada")
            if fodder:
                g.add_counters(perm, "+1/+1", _m * len(fodder))
                g.log(f"{perm.name} devora {len(fodder)} ficha(s): "
                      f"+{_m * len(fodder)}/+{_m * len(fodder)}")
        _prev_dev = card.on_etb
        card.on_etb = (lambda g, ctrl, perm, _d=_devour, _p=_prev_dev:
                       (_d(g, ctrl, perm), _p(g, ctrl, perm) if _p else None))

    # Persist / Undying: recursión al morir con contador (tiene prioridad sobre
    # un disparo de muerte genérico, porque DEFINE qué pasa al morir).
    if card.on_death is None and "creature" in types:
        pu = _persist_undying_ondeath(data.get("oracle_text", ""))
        if pu is not None:
            card.on_death = pu

    # disparo de MUERTE propia ("when this creature dies, <efecto>"). Antes el
    # efecto se cableaba mal como ETB (se disparaba al entrar en vez de al morir).
    if card.on_death is None:
        od = _death_self_effect(data.get("oracle_text", ""), name)
        if od is not None:
            card.on_death = od

    # Extort: al lanzar un hechizo, drenás 1 por cada rival (aprox: pago automático
    # del coste {W/B}). Motor de drenaje típico de mazos aristócratas/blink.
    if re.search(r"\bextort\b", _otx := re.sub(r"\s+", " ",
                 (data.get("oracle_text", "") or "").lower())):
        def _extort(game, perm, card=None, **_kw):
            opps = game.opponents(perm.controller)
            drained = 0
            for o in opps:
                o.life -= 1
                drained += 1
            if drained:
                game.gain_life(perm.controller, drained)
                game.log(f"{perm.controller.name} extorsiona: drena {drained}")
        card.triggers = dict(card.triggers)
        card.triggers.setdefault("cast", _extort)

    # disparos recurrentes de mantenimiento / final de turno ("at the beginning of
    # your upkeep/end step, <efecto>"). Antes se cableaba mal como ETB de una vez.
    rec = _recurring_trigger_effects(data.get("oracle_text", ""))
    if rec:
        card.triggers = dict(card.triggers)
        for ev, cb in rec.items():
            card.triggers.setdefault(ev, cb)

    # disparos por evento: muerte de criatura, daño de combate a jugador, magecraft.
    evs = _event_trigger_effect(data.get("oracle_text", ""))
    if evs:
        card.triggers = dict(card.triggers)
        for ev, cb in evs.items():
            card.triggers.setdefault(ev, cb)

    # "no puede ser bloqueada" (incondicional) -> keyword unblockable
    _ot = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    if re.search(r"can't be blocked(?:\.|,| this turn|$)", _ot):
        card.keywords = set(card.keywords) | {"unblockable"}

    # costes alternativos: coste adicional al lanzar y reducción "cuesta {N} menos"
    if {"instant", "sorcery", "creature", "artifact", "enchantment", "planeswalker"} & types:
        add = {}
        mc = re.search(r"as an additional cost to cast [^,]+, ([^.]+)", _ot)
        if mc:
            seg = mc.group(1)
            ml = re.search(r"pay (\w+) life", seg)
            if ml and (nl := _count_word(ml.group(1))):
                add["pay_life"] = nl
            md = re.search(r"discard (\w+) cards?", seg)
            if md and (nd := _count_word(md.group(1))):
                add["discard"] = nd
            if "sacrifice a creature" in seg or "sacrifice another creature" in seg:
                add["sacrifice"] = True
        if add:
            card.additional_cost = add
        mr = re.search(r"this spell costs \{(\d+)\} less to cast", _ot)
        if mr:
            card.cost_reduction = int(mr.group(1))

    # efectos de REEMPLAZO estáticos (dobladores / muerte->exilio)
    _rt = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    if re.search(r"twice that many (?:of those )?tokens", _rt) or \
            "create twice as many" in _rt:
        card.token_double = True
    mch = re.search(r"twice that many (?:of those )?counters", _rt)
    if mch:
        only11 = "+1/+1" in _rt
        card.counter_modifier = (lambda g, perm, kind, n, _o=only11:
                                 n * 2 if (not _o or kind == "+1/+1") else n)
        if "token" in _rt:                         # Doubling Season dobla ambos
            card.token_double = True
    elif re.search(r"that many (?:of those counters )?plus one", _rt) and "+1/+1" in _rt:
        card.counter_modifier = (lambda g, perm, kind, n:
                                 n + 1 if kind == "+1/+1" else n)
    if re.search(r"deals? double that damage", _rt):
        card.damage_double = "you" if "source you control" in _rt else "all"
    if re.search(r"if [^.]*would die, exile (?:it|that creature|them) instead", _rt):
        if "you control" in _rt:
            card.die_exile = "you"
        elif "opponent" in _rt:
            card.die_exile = "opp"
        else:
            card.die_exile = "all"

    return cards.attach_generic_effects(card)


# --------------------------------------------------------------------------- #
# Resolucion por nombre
# --------------------------------------------------------------------------- #

def resolve(name: str, fetch=None) -> Card:
    """Devuelve una Card para `name`.

    1) si esta implementada -> version con efecto real.
    2) si no, y hay `fetch(name)->dict` (Scryfall), construye vainilla con
       stats reales.
    3) si no hay datos -> None (el llamador decide: placeholder o descartar).
    """
    key = _norm(name)
    if key in REGISTRY:
        return REGISTRY[key]()
    # basicas conocidas sin red
    basic = _basic_land(name)
    if basic is not None:
        return basic
    if fetch is not None:
        data = fetch(name)
        if data:
            return build_card_from_data(data)
    return None


_BASICS = {
    "plains": W, "island": U, "swamp": B, "mountain": R, "forest": G,
    "wastes": C,
    # singulares / plurales / typos comunes ("Plain" -> Plains, "Mountains" -> Mountain)
    "plain": W, "islands": U, "swamps": B, "mountains": R, "forests": G,
    "waste": C, "snow-covered plains": W, "snow-covered island": U,
    "snow-covered swamp": B, "snow-covered mountain": R, "snow-covered forest": G,
    "llanura": W, "isla": U, "pantano": B, "montana": R, "montaña": R,
    "bosque": G, "yermo": C, "llanuras": W, "islas": U, "pantanos": B,
    "montanas": R, "montañas": R, "bosques": G,
}


def _basic_land(name: str):
    key = _norm(name)
    if key in _BASICS:
        color = _BASICS[key]
        from cards import land
        display = {W: "Plains", U: "Island", B: "Swamp", R: "Mountain",
                   G: "Forest", C: "Wastes"}[color]
        return land(display, [color], basic=True)
    return None


def is_implemented(name: str) -> bool:
    return _norm(name) in REGISTRY
