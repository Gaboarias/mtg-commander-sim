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
            continue
        elif "/" in s:               # hibrido / phyrexiano: primer color valido
            first = next((p for p in s.split("/") if p in _COLOR_MAP), None)
            if first:
                pips += first
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
    for key in ("type_line", "mana_cost", "power", "toughness", "oracle_text"):
        v = merged.get(key)
        if v in (None, "", []) or (isinstance(v, str) and "//" in v):
            fv = front.get(key)
            if fv not in (None, "", []):
                merged[key] = fv
    return merged


_NUMWORD = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _targeted_spell(oracle: str):
    """Detecta remoción/bounce DIRIGIDA en el texto: (modo, cantidad de objetivos).
    Aproximado, pero permite ELEGIR el/los objetivo(s) en vez de auto."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())
    for verb, mode in (("destroy", "destroy"), ("exile", "exile")):
        m = re.search(verb + r" (up to )?(\w+ )?target (?:creature|permanent)", t)
        if m:
            return mode, _NUMWORD.get((m.group(2) or "").strip(), 1)
    m = re.search(r"return (up to )?(\w+ )?target (?:creature|permanent)[^.]{0,40}hand", t)
    if m:
        return "bounce", _NUMWORD.get((m.group(2) or "").strip(), 1)
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
    """Clon: crea una ficha copia (P/T + keywords) del objetivo."""
    def eff(game, ctrl, targets):
        tg = (list(targets or []) or [None])[0]
        if tg is None:
            return
        cards.make_token(game, ctrl, tg.card.name, tg.card.power, tg.card.toughness,
                         kw=tuple(tg.card.keywords))
        game.log(f"{ctrl.name} crea una copia de {tg.card.name}")
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
    # robo de control
    if re.search(r"gain control of (?:up to \w+ )?target", t):
        temp = "until end of turn" in t or "end of turn" in t
        return _control_effect(temp), "opp_creature", 1
    # clon
    if re.search(r"copy of (?:up to \w+ )?target (?:creature|permanent)", t):
        return _clone_effect(), "opp_creature", 1
    # pelea
    if re.search(r"fights? (?:up to \w+ )?target creature", t) or \
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
    spec = _targeted_spell(seg)
    if spec is not None:
        mode, count = spec
        return cards.remove_targets(mode), "opp_creature", max(1, count)
    # quema a criatura elegida: "deals N damage to (up to M) target creature"
    mb = re.search(r"deals? (\w+) damage to (?:up to (\w+) )?target creature(?! or player)",
                   seg, re.I)
    if mb and (n := _count_word(mb.group(1))):
        cnt = _count_word(mb.group(2)) if mb.group(2) else 1

        def burn(game, ctrl, targets, _n=n):
            for tg in (targets or []):
                game.deal_damage(None, tg, _n)
        return burn, "opp_creature", max(1, cnt or 1)
    # quema a un JUGADOR elegido: "deals N damage to target player / any target /
    # creature or player / player or planeswalker" -> el humano elige a qué rival.
    mp = re.search(r"deals? (\w+) damage to (?:any target|target player|target opponent|"
                   r"target creature or player|target planeswalker or player|"
                   r"target player or planeswalker)", seg, re.I)
    if mp and (n := _count_word(mp.group(1))):
        def burnp(game, ctrl, targets, _n=n):
            tgts = [t for t in (targets or []) if hasattr(t, "life")]  # jugadores
            if not tgts:
                opps = game.opponents(ctrl)
                tgts = [min(opps, key=lambda o: o.life)] if opps else []
            for tg in tgts:
                game.deal_damage(None, tg, _n)
                game.log(f"{ctrl.name}: {_n} de daño a {tg.name}")
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
    (list[{label, effect, target_spec, target_count}], cuántos_elegir) o None."""
    if not oracle:
        return None
    m = re.search(r"choose (one|two|up to \w+)\s*[—\-–]\s*(.+)", oracle, re.I | re.S)
    if not m:
        return None
    pick = 2 if "two" in m.group(1).lower() else 1
    body = m.group(2)
    parts = None
    for pat in (r"\s*•\s*", r"\s*;\s*or\s+", r"\s*\n\s*"):  # bullets, "; or", saltos
        cand = [p.strip(" .\n") for p in re.split(pat, body) if p.strip(" .\n")]
        if len(cand) >= 2:
            parts = cand
            break
    if not parts:
        return None
    modes = []
    for seg in parts[:4]:
        eff, spec, count = _fragment_effect(seg)
        modes.append({"label": _short_label(seg), "effect": eff,
                      "target_spec": spec, "target_count": count})
    if not any(md["effect"] for md in modes):
        return None
    return modes, pick


def _parse_activated(oracle: str):
    """Habilidades activadas con coste de MANÁ (y opcional {T}). Devuelve una tupla
    de dicts {cost, tap, label, effect, target_spec, target_count}. Ignora costes
    con sacrificio/descarte y efectos que no reconocemos."""
    out = []
    for raw in (oracle or "").split("\n"):
        m = re.match(r"([^:]+):\s*(.+)", raw.strip())
        if not m:
            continue
        costtxt, body = m.group(1), m.group(2)
        syms = re.findall(r"\{([^}]+)\}", costtxt)
        # el coste debe ser SOLO símbolos {..}; si queda texto (sacrifice, discard) saltar
        if not syms or re.sub(r"\{[^}]+\}|[,\s]", "", costtxt):
            continue
        tap = any(s.upper() == "T" for s in syms)
        mana = "".join("{%s}" % s for s in syms if s.upper() != "T")
        cost = parse_cost(mana_cost_to_str(mana)) if mana else parse_cost("0")
        eff, spec, count = _fragment_effect(body)
        if eff is None:
            continue
        out.append({"cost": cost, "tap": tap, "label": _short_label(body),
                    "effect": (lambda g, c, perm, tg, _e=eff: _e(g, c, tg)),
                    "target_spec": spec, "target_count": count})
    return tuple(out[:4])


def _attack_trigger_effect(oracle: str):
    """'Whenever ~ attacks, <efecto>' -> callback de trigger (g, perm, **kw) o None.
    Cubre p. ej. Laelia (al atacar, exiliar el tope y poder jugarla)."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    m = re.search(r"whenever [^.]{0,50}? attacks,?\s*(.{0,180})", t, re.I)
    if not m:
        return None
    eff, _spec, _count = _fragment_effect(m.group(1))
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
        (r"whenever you cast (?:an instant or sorcery|a noncreature|your first "
         r"[\w ]*?) spell,?\s*(.{0,160})", "cast"),
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
        if ev == "cast":
            def cb(game, perm, card=None, _e=eff, **_kw):
                if card is not None and ({"instant", "sorcery"} & card.types):
                    _e(game, perm.controller)
        else:
            def cb(game, perm, _e=eff, *_a, **_kw):
                _e(game, perm.controller)
        out[ev] = cb
    return out


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
            ctrl.life += _n
        return eff

    m = re.search(r"(\d+)/(\d+).{0,60}?token", t)
    if m:
        pw, tf = int(m.group(1)), int(m.group(2))
        def eff(game, ctrl, perm, _p=pw, _t=tf):
            cards.make_token(game, ctrl, "Token", _p, _t)
        return eff

    return None


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
                           label="una carta"):
    """Tutor: buscar en la biblioteca una carta que cumpla keep_pred y ponerla en
    la mano (o al campo). El humano elige; el bot toma el mejor candidato. Baraja
    después."""
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
                        game.move_to_battlefield(pick, ctrl)
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


def _generic_amount_effect(oracle: str):
    """Efecto APROXIMADO con monto, deducido del oracle. Devuelve una función
    eff(game, ctrl, *_) o None. Cubre patrones comunes de creaturas/hechizos que
    la capa por tags (wipe/removal/draw/ramp) no modela. Prioridad: fichas >
    quema a cada rival > ganancia de vida > mill propio."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())

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
                ctrl.life += _n * max(1, len(opps))
            game.log(f"{ctrl.name}: cada rival pierde {_n} de vida"
                     + (" y él gana vida" if _gain else ""))
        return eff

    # quema a un objetivo tipo jugador (any target / target player / creature or
    # player): se la mandamos al rival más débil (auto) y queda VISIBLE en la vida.
    m = re.search(r"deals? (\w+) damage to (?:any target|target player|"
                  r"target opponent|target creature or player|target planeswalker or player)", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            opps = game.opponents(ctrl)
            if opps:
                tgt = min(opps, key=lambda o: o.life)
                game.deal_damage(None, tgt, _n)
                game.log(f"{ctrl.name}: {_n} de daño a {tgt.name}")
        return eff

    m = re.search(r"(?:you )?gain (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            ctrl.life += _n
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

    # reanimar desde el cementerio al campo (elección automática, visible en el log)
    if re.search(r"return .{0,70}?from your graveyard to the battlefield", t):
        lim = int(mvm.group(1)) if (mvm := re.search(r"mana value (\d+) or less", t)) else None
        cre = "creature card" in t

        def eff(game, ctrl, *_a, _lim=lim, _cre=cre):
            def ok(c):
                if c.is_land():
                    return False
                if _cre and "creature" not in c.types:
                    return False
                if _lim is not None and c.cost and c.cost.cmc > _lim:
                    return False
                return True
            cands = [c for c in ctrl.graveyard if ok(c)]
            if not cands:
                game.log(f"{ctrl.name}: sin carta válida en el cementerio para revivir")
                return
            pick = max(cands, key=lambda c: (c.cost.cmc if c.cost else 0))
            ctrl.graveyard.remove(pick)
            game.move_to_battlefield(pick, ctrl)
            game.log(f"{ctrl.name} revive {pick.name} del cementerio")
        return eff

    # regresar una carta del cementerio a la mano (elección automática + log)
    if re.search(r"return .{0,70}?from your graveyard to your hand", t):
        def eff(game, ctrl, *_a):
            cands = [c for c in ctrl.graveyard if not c.is_land()]
            if not cands:
                return
            pick = max(cands, key=lambda c: (c.cost.cmc if c.cost else 0))
            ctrl.graveyard.remove(pick)
            ctrl.hand.append(pick)
            game.log(f"{ctrl.name} recupera {pick.name} del cementerio a la mano")
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

    # "you may draw a card" (opcional, singular): la tomamos y lo registramos.
    if re.search(r"(?:you may )?draw a card", t):
        def eff(game, ctrl, *_a):
            ctrl.draw(1, game)
            game.log(f"{ctrl.name} roba una carta")
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
    )

    # tags: de creatura + derivados (aprox) del texto de la carta, para que la
    # capa de efectos genericos funcione tambien con cartas de Scryfall
    card.tags = _derive_tags(data.get("oracle_text", ""), card.types)

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

    # planeswalker: lealtad inicial + habilidades del texto de Scryfall. Sin
    # esto entraría con lealtad 0 y moriría al instante (SBA), y no tendría
    # habilidades activables. Se cablea ANTES de la capa genérica.
    if "planeswalker" in types:
        loy = _int_or_zero(data.get("loyalty"))
        abils, texts = _planeswalker_abilities(data.get("oracle_text", ""))
        if loy > 0:
            card.loyalty = loy
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

    # remoción / bounce DIRIGIDA (instantáneo o conjuro): dejar elegir objetivos.
    # Se cablea ANTES de la capa genérica para que no la reemplace.
    if {"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve:
        spec = _targeted_spell(data.get("oracle_text", ""))
        if spec is not None:
            mode, count = spec
            card.on_cast_resolve = cards.remove_targets(mode)
            card.target_spec = "opp_creature"
            card.target_count = max(1, count)
            card.tags = card.tags | {"removal"}

    # efecto genérico CON MONTO leído del oracle (fichas, quema a cada rival,
    # ganancia de vida, mill). Cubre creaturas/hechizos comunes que la capa por
    # tags no modela. No pisa remoción/barrida (más definitorias) ni efectos ya
    # cableados. Se resuelve al entrar (permanentes) o al resolverse (hechizos).
    if not card.on_cast_resolve and not card.modes and not (card.tags & {"wipe", "removal"}):
        geff = _generic_amount_effect(data.get("oracle_text", ""))
        if geff is not None:
            if {"instant", "sorcery"} & types:
                card.on_cast_resolve = geff
            elif ({"creature", "artifact", "enchantment"} & types
                  and re.search(r"\benters?\b", (data.get("oracle_text", "") or "").lower())):
                # solo como ETB si el texto tiene un disparo de entrada; si el efecto
                # pertenece a otro disparo (p. ej. "whenever ~ attacks"), no lo duplicamos
                card.on_etb = geff

    # habilidades activadas con coste de maná (creaturas/permanentes/tierras):
    # "{cost}: efecto" -> se pueden activar en juego pagando el maná.
    if not ({"instant", "sorcery"} & types):
        ab = _parse_activated(data.get("oracle_text", ""))
        if ab:
            card.activated_abilities = ab

    # disparo "al atacar" (whenever ~ attacks, ...): p. ej. Laelia (exiliar el tope
    # y poder jugarla). Se cablea como trigger de "attacks".
    atk_eff = _attack_trigger_effect(data.get("oracle_text", ""))
    if atk_eff is not None and "attacks" not in card.triggers:
        card.triggers = dict(card.triggers)
        card.triggers["attacks"] = atk_eff

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
    "llanura": W, "isla": U, "pantano": B, "montana": R, "montaña": R,
    "bosque": G, "yermo": C,
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
