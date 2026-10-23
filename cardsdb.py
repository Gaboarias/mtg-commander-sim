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

import json
import os
import re

from engine import Card, Cost, parse_cost, W, U, B, R, G, C, KEYWORDS
import cards

# --------------------------------------------------------------------------- #
# Registro de cartas implementadas (nombre -> constructor)
# --------------------------------------------------------------------------- #

# Solo implementaciones FIELES al oráculo real (regla 5). Las que antes tenían
# texto inventado (Bag of Holding, Sevinne's Reclamation, Underworld Breach,
# Simic Ascendancy, Doomed Traveler, Bloodrage Brawler, Quintorius Kand) ya no
# están: se construyen desde su oráculo real con el parser.
_IMPLEMENTED = [
    cards.Quintorius, cards.Hofri, cards.FaithlessLooting, cards.SunTitan,
    cards.KarmicGuide, cards.Managorger, cards.Kalonian, cards.HardenedScales,
    cards.BranchingEvolution,
    cards.Kang, cards.GrayMerchant, cards.GoForTheThroat, cards.NightsWhisper,
    cards.DamnationWipe,
    cards.SolRing, cards.ArcaneSignet, cards.CommandTower,
    cards.Counterspell,
]


def _build_registry():
    reg = {}
    for ctor in _IMPLEMENTED:
        c = ctor()
        reg[_norm(c.name)] = ctor
    return reg


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# REGISTRY se arma al FINAL del módulo: algunas implementaciones (Quintorius,
# Hofri) se construyen desde su oráculo con build_card_from_data.
REGISTRY: dict = {}


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
        elif s in _COLOR_MAP:
            pips += s            # {C} es un pip INCOLORO (Thought-Knot Seer: CMC 4)
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
        # P/T variable ("*", "1+*"): la base numérica (sin modelar el conteo)
        m = re.match(r"\s*(\d+)\s*\+\s*\*", str(v or ""))
        return int(m.group(1)) if m else 0


def _toughness_of(data):
    """Resistencia impresa; si es variable ('*', '1+*') nunca menos de 1: antes
    Tarmogoyf entraba 0/0 y moría por SBA, peor que una carta vainilla."""
    v = data.get("toughness")
    n = _int_or_zero(v)
    return max(1, n) if "*" in str(v or "") else n


# --------------------------------------------------------------------------- #
# Segmentación del oráculo en habilidades (refactor del parser)
# --------------------------------------------------------------------------- #
# Las regex de abajo trabajaban sobre TODO el texto con los saltos de línea
# colapsados: el texto recordatorio y las habilidades activadas/disparadas se
# colaban en otros efectos (Mind Stone robaba al entrar, Soul Warden se disparaba
# con su propia entrada, el recordatorio de Treasure daba maná...). Estos helpers
# separan el oráculo en líneas = habilidades y clasifican cada una.

_REMINDER_RE = re.compile(r"\s*\([^()]*\)")


def _strip_reminder(text):
    """Quita el texto recordatorio entre paréntesis (no es parte de la regla)."""
    return _REMINDER_RE.sub("", text or "")


def _ability_lines(text):
    """Líneas del oráculo = habilidades. Los modos '• …' se pegan a su línea."""
    out = []
    for raw in (text or "").split("\n"):
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("•") and out:
            out[-1] = out[-1] + " " + ln
        else:
            out.append(ln)
    return out


_COSTISH = re.compile(r"\{|^[+−\-]?(?:\d+|x)$|sacrific|discard|pay |remove |exile |"
                      r"tap |untap |return |reveal |collect evidence|forage", re.I)


def _is_activated_line(line):
    """'<coste>: <efecto>' (incluye lealtad '+1:' / '−3:')."""
    m = re.match(r'^([^:"“]{1,120}):\s', line or "")
    if not m:
        return False
    pre = m.group(1).strip()
    if re.match(r"(?i)(when|whenever|at the beginning|as long as|if |chapter|level)", pre):
        return False
    return bool(_COSTISH.search(pre))


def _is_triggered_line(line):
    return bool(re.match(r"(?i)^(?:\w[\w ]*\s—\s)?(when|whenever|at the beginning)\b",
                         line or ""))


def _non_activated_text(text):
    """Oráculo sin las habilidades activadas (para tags de efectos genéricos)."""
    return "\n".join(l for l in _ability_lines(text) if not _is_activated_line(l))


def _static_text(text):
    """Solo habilidades ESTÁTICAS sin condición ni duración: sin activadas, sin
    disparadas, sin 'until end of turn' / 'as long as' / 'if' ni texto citado
    (emblemas). Lo usa el anthem estático."""
    out = []
    for l in _ability_lines(text):
        low = l.lower()
        if (_is_activated_line(l) or _is_triggered_line(l) or '"' in l or "“" in l
                or "until end of turn" in low or "as long as" in low
                or low.startswith(("if ", "during ", "for as long"))):
            continue
        out.append(l)
    return "\n".join(out)


def _self_names(name):
    full = (name or "").split(" // ")[0].strip()
    names = {full.lower()}
    if "," in full:
        names.add(full.split(",")[0].strip().lower())
    mt = re.match(r"([A-Z][\w'-]+) (?:the|of) [A-Z]", full)
    if mt:                                 # "Sharuum the Hegemon" -> "Sharuum"
        names.add(mt.group(1).lower())
    return names


def _self_etb_body(text, name):
    """Cuerpo del disparo de ENTRADA PROPIO ('When <esta carta> enters, <cuerpo>').
    Devuelve (cuerpo, también_al_atacar) o (None, False). 'Whenever another
    creature enters' NO es una entrada propia."""
    # patrón FIJO (cacheado por re) y el sujeto se compara en Python: armar una
    # regex con el nombre de cada carta desbordaba la caché de re y duplicaba el
    # tiempo de armar mazos
    names = _self_names(name)
    for l in _ability_lines(text):
        m = _SELF_ETB_RE.match(l)
        if m and (m.group(1).lower() in names or _SELF_SUBJ_RE.match(m.group(1))):
            return m.group(3), bool(m.group(2))
    return None, False


_SELF_ETB_RE = re.compile(
    r"^when(?:ever)? (.+?) (?:enters|enters the battlefield|is turned face up)( or attacks| or dies)?"
    r"(?: under your control)?,\s*(.+)$", re.I)
_SELF_SUBJ_RE = re.compile(
    r"^(?:this (?:creature|artifact|enchantment|permanent|land|vehicle|equipment|aura|"
    r"battle|planeswalker)|~)$", re.I)


def _has_keyword(data, kw):
    """¿La carta TIENE la keyword? Por la lista 'keywords' de Scryfall o por una
    línea que empieza con ella (cartas caseras). No vale una mención suelta."""
    if kw in {k.lower() for k in (data.get("keywords") or [])}:
        return True
    # al inicio de una línea (no "Storm Crow…") o como oración suelta tras un punto
    return bool(re.search(r"(?:^|[.\n])\s*" + kw + r"\s*(?:$|[.\n(—–-]|\d)",
                          (data.get("oracle_text", "") or "").lower(), re.M))


def _enters_tapped_rule(oracle):
    """True (entra girado), None (no), o f(game, player)->bool 'entra DESENGIRADO'
    para las condiciones de tierras: checklands, fastlands, slowlands, battlebond,
    shocklands (pagar 2 vida), reveal-lands, Promenade, Crater…"""
    t = re.sub(r"\s+", " ", _strip_reminder(oracle or "")).lower()
    t = re.sub(r"\b(?:this land|this creature|this artifact|this permanent)\b", "~", t)
    if re.search(r"enters (?:the battlefield )?tapped and attacking", t):
        return None                                   # otra mecánica
    m = re.search(r"enters (?:the battlefield )?tapped unless ([^.]+)\.", t)
    if m:
        cond = m.group(1)
        mc = re.match(r"you control (\w+) or (more|fewer) (other |basic )?lands", cond)
        if mc and (n := _count_word(mc.group(1))) is not None:
            more, basic = mc.group(2) == "more", (mc.group(3) or "").strip() == "basic"

            def f(g, p, _n=n, _more=more, _basic=basic):
                k = sum(1 for pm in p.lands()
                        if not _basic or "basic" in pm.card.supertypes)
                return k >= _n if _more else k <= _n
            return f
        mo = re.match(r"you control (\w+) or more other (\w+?)s$", cond)
        if mo and (n := _count_word(mo.group(1))) is not None:
            return (lambda g, p, _n=n, _st=mo.group(2):
                    sum(1 for pm in p.lands() if pm.has_subtype(_st)) >= _n)
        if re.match(r"you have two or more opponents", cond):
            return lambda g, p: len(g.opponents(p)) >= 2
        mo = re.match(r"your opponents control (\w+) or more lands", cond)
        if mo and (n := _count_word(mo.group(1))) is not None:
            return (lambda g, p, _n=n:
                    sum(len(o.lands()) for o in g.opponents(p)) >= _n)
        mt = re.match(r"you control an? ([a-z]+)(?: or an? ([a-z]+))?$", cond)
        if mt:
            subs = tuple(x for x in mt.groups() if x)
            return (lambda g, p, _s=subs:
                    any(pm.has_subtype(st) for pm in p.battlefield for st in _s))
        return True                     # condición desconocida: girada (conservador)
    m = re.search(r"you may pay (\d+) life\. if you don't, (?:it|~) enters tapped", t)
    if m:
        n = int(m.group(1))

        def shock(g, p, _n=n):
            if p.life > _n + 8:                     # la IA paga si le sobra vida
                p.life -= _n
                g.log(f"{p.name} paga {_n} de vida para que entre sin girar")
                return True
            return False
        return shock
    m = re.search(r"you may reveal an? ([a-z]+)(?: or ([a-z]+))? card from your hand\. "
                  r"if you don't, (?:it|~) enters tapped", t)
    if m:
        kinds = tuple(x for x in m.groups() if x)
        return (lambda g, p, _k=kinds: any(
            any(k in {s.lower() for s in c.subtypes} or k in c.types for k in _k)
            for c in p.hand))
    if re.search(r"(?:^|\. |~ )enters (?:the battlefield )?tapped(?:\.| with)", t) or \
            re.search(r"enters (?:the battlefield )?tapped\.", t):
        return True
    return None


def _mana_amount(oracle):
    """(cantidad, color|None) de la primera habilidad '{T}: Add …'. {C}{C} -> (2, C);
    '{R} or {W}' -> (1, None); 'three mana of any one color' -> (3, None)."""
    for l in _ability_lines(oracle):
        m = re.match(r"\{t\}(?:,[^:]*)?:\s*add ([^.]+)", l, re.I)
        if not m:
            continue
        seg = m.group(1).lower()
        syms = re.findall(r"\{([wubrgc])\}", seg)
        if len(syms) > 1 and len(set(syms)) == 1 and " or " not in seg:
            return len(syms), _COLOR_MAP[syms[0].upper()]
        if len(syms) > 1 and " or " not in seg and "," not in seg:
            # {W}{U} (bouncelands): 2 maná. El motor modela opciones de UN color, así
            # que se aproxima como 2 de cualquiera de esos colores.
            return len(syms), None
        mn = re.search(r"(\w+) mana (?:of any one color|in any combination)", seg)
        if mn and (_count_word(mn.group(1)) or 0) > 1:
            return _count_word(mn.group(1)), None
        return 1, None
    return 1, None


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
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}

# keywords que puede traer una ficha ("... token with vigilance and lifelink")
_TOKEN_KEYWORDS = [
    (r"\bflying\b", "flying"), (r"\btrample\b", "trample"),
    (r"\bvigilance\b", "vigilance"), (r"\blifelink\b", "lifelink"),
    (r"\bdeathtouch\b", "deathtouch"), (r"\bmenace\b", "menace"),
    (r"\bhaste\b", "haste"), (r"\breach\b", "reach"),
    (r"\bdefender\b", "defender"), (r"\bhexproof\b", "hexproof"),
    (r"\bindestructible\b", "indestructible"),
    (r"\bfirst strike\b", "first_strike"), (r"\bdouble strike\b", "double_strike"),
]


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
            r"planeswalker|permanent|creature)(?!\s+cards?)", t)
        if m:
            typ = m.group(3)
            spec = next((s for pat, s in _TARGET_TYPE_SPECS if pat in typ), "opp_creature")
            return mode, _NUMWORD.get((m.group(2) or "").strip(), 1), spec
    # "target creature CARD" (Disentomb, Deathrite): es una carta de un cementerio,
    # no un permanente en el campo -> no es remoción/bounce
    m = re.search(r"return (up to )?(\w+ )?target "
                  r"((?:nonland )?permanent|artifact|enchantment|creature)(?!\s+cards?)"
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
                hook = getattr(game, "cascade_target_hook", None)
                spec = getattr(hit, "target_spec", None)
                cnt = getattr(hit, "target_count", 1) or 0
                if (hook is not None and spec and cnt >= 1
                        and ctrl is getattr(game, "interactive_human", None)):
                    # el humano elige el objetivo del hechizo cascadeado
                    # (el hook arma pending_choice y resuelve al confirmar)
                    hook(hit, ctrl)
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


def _counter_filter(qual):
    """'noncreature' / 'creature' / 'instant or sorcery' / 'artifact or enchantment'…
    -> predicado sobre la carta del hechizo, o None si no hay calificador."""
    q = (qual or "").strip().lower()
    if not q:
        return None
    neg = q.startswith("non")
    words = [w for w in re.split(r"\s+or\s+|,\s*|\s+", q.replace("non", "", 1) if neg else q)
             if w and w not in ("or", "and")]
    known = {"creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker",
             "land", "permanent", "legendary"}
    if not words or not all(w in known for w in words):
        return "?"

    def ok(card, _w=tuple(words), _neg=neg):
        types = set(getattr(card, "types", set()))
        hit = any((w == "permanent" and types & {"creature", "artifact", "enchantment",
                                                 "planeswalker", "land", "battle"})
                  or (w == "legendary" and "legendary" in getattr(card, "supertypes", set()))
                  or w in types for w in _w)
        return not hit if _neg else hit
    return ok


def _counter_spell_effect(filt=None, unless=None):
    """Contrarresta el hechizo objetivo (StackObject): lo saca de la pila y su
    carta va al cementerio. Cubre Counterspell y variantes importadas de Scryfall.
    `filt`: solo hechizos de ese tipo. `unless`: N genérico que el controlador del
    hechizo puede pagar para evitarlo (Mana Leak)."""
    def eff(game, ctrl, targets, _f=filt, _u=unless):
        obj = (list(targets or []) or [None])[0]
        if obj is None:
            return
        src = getattr(obj, "source", None)
        name = getattr(src, "name", "?")
        if _f is not None and src is not None and not _f(src):
            game.log(f"{name} no es un objetivo legal para el contrahechizo")
            return
        if _u:
            payer = getattr(obj, "controller", None)
            if payer is not None and payer.can_pay(Cost(generic=_u, pips=())):
                payer.pay(Cost(generic=_u, pips=()))
                game.log(f"{payer.name} paga {{{_u}}} y {name} no se contrarresta")
                return
        if game.counter_spell(obj):
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
        mine.sort(key=lambda c: c.power, reverse=True)   # el bot pelea con la más fuerte

        def _do(fighter, _tg=tg):
            if fighter not in fighter.controller.battlefield or _tg not in _tg.controller.battlefield:
                return
            game.log(f"{fighter.name} pelea con {_tg.name}")
            game.deal_damage(fighter, _tg, fighter.power, combat=False)
            game.deal_damage(_tg, fighter, _tg.power, combat=False)
            game.sba()
        cands = [(f"{c.name} {c.power}/{c.toughness}", c) for c in mine]
        _human_target_choice(game, ctrl, "etb_target",
                             f"Elegí tu criatura para pelear con {tg.name}", cands, _do)
    return eff


def _bite_effect():
    """'Target creature you control deals damage equal to its power to target
    creature': tu criatura (la más fuerte; el humano elige) hace el daño, sin recibir."""
    def eff(game, ctrl, targets):
        tg = (list(targets or []) or [None])[0]
        if tg is None or not tg.is_creature():
            return
        mine = sorted(ctrl.creatures(), key=lambda c: c.power, reverse=True)
        if not mine:
            return

        def _do(src, _tg=tg):
            if src not in src.controller.battlefield or _tg not in _tg.controller.battlefield:
                return
            game.log(f"{src.name} le hace {src.power} de daño a {_tg.name}")
            game.deal_damage(src, _tg, src.power, combat=False)
            game.sba()
        cands = [(f"{c.name} {c.power}/{c.toughness}", c) for c in mine]
        _human_target_choice(game, ctrl, "etb_target",
                             f"Elegí tu criatura que hace el daño a {tg.name}", cands, _do)
    return eff


def _do_connive(game, perm, n=1):
    """Connive N: roba N, descarta N (la política elige), y pone un +1/+1 en `perm`
    por cada carta NO-tierra descartada."""
    ctrl = perm.controller
    ctrl.draw(n, game)
    added = 0
    for _ in range(n):
        if not ctrl.hand:
            break
        if ctrl.policy and hasattr(ctrl.policy, "choose_discard"):
            c = ctrl.policy.choose_discard(game, ctrl)
        else:
            c = ctrl.hand[-1]
        ctrl.hand.remove(c)
        ctrl.graveyard.append(c)
        game.emit("to_graveyard", player=ctrl, card=c)
        if not c.is_land():
            added += 1
    if added:
        game.add_counters(perm, "+1/+1", added)
    game.log(f"{perm.name} connive {n} (+{added}/+{added})")


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
    if re.search(r"copy of (?:up to \w+ )?(?:another )?target (?:nonlegendary )?"
                 r"(?:creature|permanent)", t):
        _cs = _copy_token_spec(t)
        if _cs is not None and _cs["kind"] == "target":
            def eff(game, ctrl, targets, _s=_cs):
                tg = (list(targets or []) or [None])[0]
                if tg is not None and hasattr(tg, "card"):
                    _make_token_copies(game, ctrl, tg, _s)
            # copiar lo PROPIO salvo que exija una criatura rival
            return eff, ("opp_creature" if _cs.get("opp") else "own_creature"), 1
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
    # "Target creature you control deals damage equal to its power to target …"
    # (Rabid Bite, Ram Through): daño de UN solo lado; antes se modelaba como pelea
    # y tu criatura recibía el daño de vuelta
    if re.search(r"deals damage equal to its power to (?:up to \w+ )?(?:another )?"
                 r"target creature", t):
        return _bite_effect(), "opp_creature", 1
    if re.search(r"fights? (?:up to \w+ |another )?target creature", t):
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


_MASS_TYPES = {"creature", "artifact", "enchantment", "planeswalker", "land",
               "battle", "permanent", "nonland permanent", "nonland permanent"}


def _mass_destroy_effect(text):
    """'Destroy all <tipos> [you don't control] [with mana value N or less/greater]
    [and all <tipos> …]'. Devuelve eff(game, ctrl, targets), None si el texto no
    es un 'destroy all', o "?" si lo es pero con un calificador que no se entiende
    (la carta queda sin efecto: antes Plague Wind / Austere Command / el Disk se
    volvían un Wrath total que mataba también lo propio o lo que no correspondía)."""
    t = re.sub(r"\s+", " ", _strip_reminder(text or "").lower())
    m = re.search(r"destroy all ([^.]+)", t)
    if not m:
        return None
    specs = []
    for item in re.split(r",? and all ", m.group(1)):
        mi = re.match(r"([a-z ,]+?)(?: (you don't control|your opponents control|you control))?"
                      r"(?: with (?:mana value|converted mana cost) (\d+) or (less|greater))?"
                      r"(?:,? then .*)?$", item.strip())
        if not mi:
            return "?"
        kinds = []
        for k in re.split(r",\s*(?:and |or )?|\s+(?:and|or)\s+", mi.group(1).strip()):
            k = k.strip()
            k = k[:-1] if k.endswith("s") else k
            if k not in _MASS_TYPES:
                return "?"
            kinds.append(k)
        n = int(mi.group(3)) if mi.group(3) else None
        specs.append((tuple(kinds), mi.group(2), n, mi.group(4)))

    def _hit(pm, ctrl, spec):
        kinds, who, n, cmp_ = spec
        if who in ("you don't control", "your opponents control") and pm.controller is ctrl:
            return False
        if who == "you control" and pm.controller is not ctrl:
            return False
        if n is not None:
            mv = pm.card.cost.cmc if getattr(pm.card, "cost", None) else 0
            if (cmp_ == "less" and mv > n) or (cmp_ == "greater" and mv < n):
                return False
        for k in kinds:
            if (k == "permanent" or (k == "nonland permanent" and not pm.card.is_land())
                    or (k == "land" and pm.card.is_land())
                    or (k == "creature" and pm.is_creature()) or k in pm.card.types):
                return True
        return False

    def eff(game, ctrl, targets=None, _specs=tuple(specs)):
        doomed = [pm for pl in game.players for pm in pl.battlefield
                  if any(_hit(pm, ctrl, sp) for sp in _specs)]
        for pm in doomed:
            game.destroy(pm, "barrida")
        game.sba()
        game.log(f"{ctrl.name}: barrida ({len(doomed)} permanente(s))")
    return eff


# --------------------------------------------------------------------------- #
# COPIAS de criaturas/permanentes
# --------------------------------------------------------------------------- #

def _copy_card(src_card, haste=False, nonlegendary=False):
    """Copia de las características copiables de `src_card` (para una ficha copia
    o un clon). 'except it has haste' / 'except it isn't legendary'."""
    import copy as _cp
    c = _cp.deepcopy(src_card)
    if nonlegendary:
        c.supertypes = set(c.supertypes) - {"legendary"}
    if haste:
        c.keywords = set(c.keywords) | {"haste"}
    return c


_COPY_TOKEN_RE = re.compile(
    r"create (a|an|one|two|three|four|five|x|\w+) tokens? that(?:'s| are) (?:a )?"
    r"cop(?:y|ies) of ([^,.]+?)(?:,? except ([^.]+))?(?:\.|$)", re.I)


def _copy_token_spec(text, name=""):
    """'create a token that's a copy of <X>[, except …]' -> dict o None.
    kind: target (elegir), subject ('that creature'), attached ('equipped
    creature'), self (esta carta)."""
    t = re.sub(r"\s+", " ", _strip_reminder(text or "")).lower()
    m = _COPY_TOKEN_RE.search(t)
    if not m:
        return None
    n = _count_word(m.group(1)) or 1
    who = m.group(2).strip()
    exc = (m.group(3) or "") + " " + t[m.end():m.end() + 80]
    spec = {"n": n, "who": who,
            "haste": bool(re.search(r"\bhas haste|gains? haste|with haste", exc)),
            "nonleg": bool(re.search(r"isn't legendary|is not legendary|nonlegendary copy", exc)),
            "eot": (lambda m2: m2.group(1) if m2 else None)(re.search(
                r"(sacrifice|exile) (?:it|them|that token|those tokens|the token|the tokens)"
                r" at (?:the beginning of the next end step|end of turn)", t)),
            "nonlegendary_only": "nonlegendary" in who,
            "nontoken_only": "nontoken" in who}
    if "target" in who:
        spec["kind"] = "target"
        spec["mine"] = "you control" in who
        spec["opp"] = bool(re.search(r"an opponent controls|you don't control", who))
        spec["another"] = "another" in who
        spec["type"] = "artifact" if re.search(r"\bartifact\b", who) and "creature" not in who \
            else "permanent" if "permanent" in who else "creature"
    elif who in ("that creature", "it", "that token", "that permanent", "that artifact"):
        spec["kind"] = "subject"
    elif re.match(r"(?:equipped|enchanted) creature", who):
        spec["kind"] = "attached"
    elif who in ("~", "this creature", "this permanent") or who in _self_names(name):
        spec["kind"] = "self"
    else:
        return None
    return spec


def _copy_candidates(game, ctrl, spec, source=None):
    pool = []
    for pl in game.players:
        if spec.get("mine") and pl is not ctrl:
            continue
        if spec.get("opp") and pl is ctrl:
            continue
        for pm in pl.battlefield:
            if spec.get("type") == "creature" and not pm.is_creature():
                continue
            if spec.get("type") == "artifact" and "artifact" not in pm.card.types:
                continue
            if spec.get("another") and pm is source:
                continue
            if spec.get("nonlegendary_only") and "legendary" in pm.card.supertypes:
                continue
            if spec.get("nontoken_only") and pm.is_token:
                continue
            if pl is not ctrl and not game.can_target(ctrl, pm):
                continue
            pool.append(pm)
    pool.sort(key=lambda pm: (pm.power + pm.toughness if pm.is_creature() else 0,
                              pm.card.cost.cmc if pm.card.cost else 0), reverse=True)
    return pool


def _make_token_copies(game, ctrl, src_perm, spec):
    """Crea spec['n'] fichas copia de `src_perm` con sus excepciones."""
    if src_perm is None:
        return
    card = _copy_card(src_perm.card, haste=spec.get("haste"), nonlegendary=spec.get("nonleg"))
    for _ in range(max(1, spec.get("n", 1))):
        before = set(id(p) for p in ctrl.battlefield)
        cards.make_copy_token(game, ctrl, card)
        made = [p for p in ctrl.battlefield if id(p) not in before]
        for tok in made:
            if spec.get("haste"):
                tok.summoning_sick = False
            if spec.get("eot"):                 # "sacrifice/exile it at the next end step"
                attr = "blitz_sac" if spec["eot"] == "sacrifice" else "unearth_eot"
                lst = getattr(game, attr, None)
                if lst is None:
                    lst = []
                    setattr(game, attr, lst)
                lst.append((ctrl, tok.card))
    game.log(f"{ctrl.name} crea una ficha copia de {src_perm.name}")


def _copy_token_effect(spec):
    """Efecto genérico (ETB / disparo / hechizo sin objetivo previo): elige la
    fuente de la copia según spec. Firma eff(game, ctrl, *a, subject=None):
    a[0] puede ser el permanente fuente (para 'equipped creature' / 'self')."""
    def eff(game, ctrl, *a, subject=None, _s=spec, **_kw):
        src = a[0] if a and hasattr(a[0], "card") else getattr(game, "_trigger_source", None)
        if subject is None:
            subject = getattr(game, "_trigger_subject", None)
        kind = _s["kind"]
        if kind == "subject":
            _make_token_copies(game, ctrl, subject, _s)
        elif kind == "self":
            _make_token_copies(game, ctrl, src, _s)
        elif kind == "attached":
            host = None
            if src is not None:
                host = getattr(src, "enchanting", None)
            _make_token_copies(game, ctrl, host, _s)
        else:
            pool = _copy_candidates(game, ctrl, _s, source=src)
            if not pool:
                return
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}"
                      if pm.is_creature() else f"{pm.name} · {pm.controller.name}", pm)
                     for pm in pool]
            _human_target_choice(game, ctrl, "etb_target", "Elegí qué copiar", cands,
                                 lambda pm: _make_token_copies(game, ctrl, pm, _s))
    return eff


def _clone_enter_spec(text, name):
    """'You may have ~ enter (the battlefield) as a copy of any creature on the
    battlefield[, except …]' (Clone, Phantasmal Image, Spark Double…)."""
    names = _self_names(name)
    for l in _ability_lines(text):
        m = re.match(r"you may have (.+?) enter(?: the battlefield)? as a copy of "
                     r"(?:any|a|an) ([a-z ]+?) (on the battlefield|you control)"
                     r"(?:,? except (.+))?$", l.strip().rstrip("."), re.I)
        if not m:
            continue
        subj = m.group(1).lower()
        if subj not in names and subj not in ("~", "this creature", "this artifact",
                                              "this permanent"):
            continue
        types = [x for x in re.split(r"\s+or\s+|,\s*", m.group(2).lower()) if x]
        exc = (m.group(4) or "").lower()
        return {"types": types, "mine": m.group(3).lower() == "you control",
                "nonleg": "isn't legendary" in exc or "is not legendary" in exc,
                "plus1": bool(re.search(r"additional \+1/\+1 counter", exc))}
    return None


def _clone_enter_effect(spec):
    """ETB de un clon: el permanente PASA A SER una copia del elegido (se conserva el
    mismo Permanent) y luego resuelve el ETB de lo copiado."""
    def _ok(pm, _t=tuple(spec["types"])):
        return any((t in ("creature", "creatures") and pm.is_creature())
                   or t.rstrip("s") in pm.card.types or t == "permanent" for t in _t)

    def eff(game, ctrl, perm, _s=spec):
        pool = [pm for pl in game.players for pm in pl.battlefield
                if pm is not perm and _ok(pm) and (not _s["mine"] or pl is ctrl)]
        pool.sort(key=lambda pm: (pm.power + pm.toughness if pm.is_creature() else 0,
                                  pm.card.cost.cmc if pm.card.cost else 0), reverse=True)
        if not pool:
            game.log(f"{perm.name}: no hay nada que copiar")
            return

        human = ctrl is getattr(game, "interactive_human", None)
        if human:
            # mientras el humano elige, el clon (0/0) no debe morir por SBA
            perm.temp_pt[1] += 1000

        def _unguard():
            if human:
                perm.temp_pt[1] -= 1000
                game.sba()

        def _become(tg):
            if human:
                perm.temp_pt[1] -= 1000
            new = _copy_card(tg.card, nonlegendary=_s["nonleg"])
            perm.card = new
            if _s["plus1"] and perm.is_creature():
                game.add_counters(perm, "+1/+1", 1)
            if "planeswalker" in new.types and new.loyalty:
                perm.counters["loyalty"] = new.loyalty + (1 if _s["plus1"] else 0)
            game.log(f"{ctrl.name}: {perm.name} entra como copia de {tg.name}")
            if new.on_etb:                       # entra como esa carta: su ETB dispara
                new.on_etb(game, ctrl, perm)
            game.sba()
        cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}"
                  if pm.is_creature() else f"{pm.name} · {pm.controller.name}", pm)
                 for pm in pool]
        _human_target_choice(game, ctrl, "etb_target", "Elegí qué copiar al entrar",
                             cands, _become, allow_none=True, on_none=_unguard)
    return eff


def _fragment_effect(seg: str):
    """Parsea un fragmento de texto a (effect(g,ctrl,targets), target_spec, count).
    Reusa los helpers de remoción/monto/robar. effect=None si no se reconoce."""
    # suspect / detain dirigidos
    msu = re.search(r"suspect (?:up to one )?target creature( you control| an opponent controls|"
                    r" you don't control)?", seg or "", re.I)
    if msu:
        who = (msu.group(1) or "").strip().lower()

        def eff_suspect(game, ctrl, targets):
            for t in (targets or []):
                if hasattr(t, "card"):
                    t.suspected = True
                    t.perma_keywords.add("menace")
                    game.log(f"{t.name} es sospechosa")
        return eff_suspect, ("own_creature" if who == "you control" else "opp_creature"), 1
    mdt = re.search(r"detain (?:up to (\w+) )?target (?:nonland permanent|creature)s?"
                    r"(?: an opponent controls| you don't control)?", seg or "", re.I)
    if mdt:
        def eff_detain(game, ctrl, targets):
            for t in (targets or []):
                if hasattr(t, "card"):
                    t._detained_by = ctrl
                    game.log(f"{ctrl.name} detiene a {t.name}")
        return eff_detain, "opp_creature", _count_word(mdt.group(1) or "one") or 1
    # "put target creature/nonland permanent on top of its owner's library"
    mtop = re.match(r"\s*put target (creature|nonland permanent|permanent|artifact or creature)"
                    r"( an opponent controls| you don't control)? on (top|the bottom) of its "
                    r"owner's library\.?\s*$", seg or "", re.I)
    if mtop:
        def eff_top(game, ctrl, targets, _bottom=mtop.group(3).lower() != "top"):
            for t in (targets or []):
                if not hasattr(t, "card") or t not in t.controller.battlefield:
                    continue
                pl = t.controller
                pl.battlefield.remove(t)
                if t.card.on_leave:
                    t.card.on_leave(game, pl, t)
                game.emit("leave", perm=t)
                if t.is_token:
                    continue
                real = getattr(t.card, "_real", None) or t.card
                owner = game.commander_owner(real)
                if owner is not None:
                    owner.command.append(real)
                elif _bottom:
                    pl.library.insert(0, real)
                else:
                    pl.library.append(real)
                game.log(f"{t.name} va {'al fondo' if _bottom else 'arriba'} de la biblioteca")
        return eff_top, ("opp_creature" if mtop.group(1).lower() == "creature"
                         else "any_nonland"), 1
    # "tap (up to) N target creatures[. They/Those creatures don't untap during their
    # controller's next untap step]" (Chilling Grasp, A Good Day to Pie)
    mtp = re.match(r"\s*tap (?:up to )?(\w+) target (creature|permanent|artifact)s?"
                   r"( an opponent controls| you don't control| your opponents control)?\.?"
                   r"(?:\s*(?:they|those (?:creatures|permanents)|it) (?:don't|doesn't) untap during "
                   r"(?:their|its) controllers?(?:'s|s'|')? next untap steps?\.?)?\s*$", seg or "", re.I)
    if mtp and (n_tp := _count_word(mtp.group(1))) and n_tp > 1:
        frz = "untap" in (seg or "").lower()

        def eff_tap_n(game, ctrl, targets, _f=frz):
            for t in (targets or []):
                if hasattr(t, "card") and t in t.controller.battlefield:
                    t.tapped = True
                    if _f:
                        t.frozen = True
            game.log(f"{ctrl.name} gira {len(targets or [])} objetivo(s)")
        return eff_tap_n, ("opp_creature" if mtp.group(2).lower() == "creature"
                           else "any_nonland"), n_tp
    # phasing dirigido: "target creature (you control) phases out"
    mph = re.search(r"(?:up to one )?target (creature|permanent|nonland permanent|artifact|"
                    r"creature or planeswalker)( you control| an opponent controls| you "
                    r"don't control)? phases out", seg or "", re.I)
    if mph:
        who = (mph.group(2) or "").strip().lower()
        kind = mph.group(1).lower()
        spec = ("own_creature" if who == "you control" and kind == "creature" else
                "own_perm" if who == "you control" else
                "opp_creature" if kind == "creature" else "any_nonland")

        def eff_phase(game, ctrl, targets):
            for t in (targets or []):
                if hasattr(t, "card"):
                    game.phase_out(t)
        return eff_phase, spec, 1
    # reanimación: "return [up to N] target <tipos> card... [with mana value N or less]
    # from your graveyard to the battlefield [with a finality counter] [... flying]"
    mre = re.search(r"return (?:up to \w+ )?target ([\w ,/'-]+?) cards?"
                    r"(?: with (?:mana value|converted mana cost) (\d+) or less)?"
                    r" from your graveyard to the battlefield", seg, re.I)
    if mre:
        _tt = mre.group(1).lower()
        _cap = int(mre.group(2)) if mre.group(2) else None
        _fin = "finality counter" in seg.lower()
        _fly = bool(re.search(r"with flying", seg[mre.end():], re.I))
        # "It's a 1/1 Spirit creature with flying in addition to its other types"
        _mbec = re.search(r"it'?s? an? (\d+)/(\d+) (\w+) creature"
                          r"(?: with ([\w ,]+?))?(?: in addition|\.|$)",
                          seg[mre.end():], re.I)
        _becomes = None
        if _mbec:
            _bk = [v for pat, v in _TOKEN_KEYWORDS
                   if re.search(pat, _mbec.group(4) or "", re.I)]
            _becomes = (int(_mbec.group(1)), int(_mbec.group(2)),
                        _mbec.group(3).capitalize(), _bk)

        def _ok(c, _t=_tt):
            hit = False
            if "creature" in _t and c.is_creature():
                hit = True
            if "artifact" in _t and "artifact" in c.types:
                hit = True
            if "enchantment" in _t and "enchantment" in c.types:
                if "aura" in _t:                       # "non-Aura enchantment"
                    hit = hit or ("Aura" not in getattr(c, "subtypes", set()))
                else:
                    hit = True
            if "permanent" in _t and bool(c.types & _PERMANENT_TYPES):
                hit = True
            if "land" in _t and c.is_land():
                hit = True
            return hit

        def reanimate(game, ctrl, targets, _cap2=_cap, _fin2=_fin, _fly2=_fly,
                      _bec=_becomes):
            pool = [c for c in ctrl.graveyard if _ok(c)
                    and (_cap2 is None or (c.cost.cmc if c.cost else 0) <= _cap2)]
            if not pool:
                return
            pool.sort(key=lambda c: (c.is_creature(),
                                     (c.power + c.toughness) if c.is_creature() else 0),
                      reverse=True)

            def _do(card):
                if card not in ctrl.graveyard:
                    return
                ctrl.graveyard.remove(card)
                perm = game.move_to_battlefield(card, ctrl)
                if perm is not None:
                    if _fin2:
                        perm.counters["finality"] = perm.counters.get("finality", 0) + 1
                    if _fly2:
                        perm.perma_keywords.add("flying")
                    if _bec:                       # "es un 1/1 Spirit con flying…"
                        px, ty, sub, bks = _bec
                        perm.set_base_pt = (px, ty)
                        perm.added_subtypes.add(sub)
                        perm.temp_creature = True   # garantiza que sea criatura
                        for k in bks:
                            perm.perma_keywords.add(k)
                    game.log(f"{ctrl.name} revive {card.name} del cementerio"
                             + (" (contador de finalidad)" if _fin2 else "")
                             + (f", ahora {_bec[0]}/{_bec[1]} {_bec[2]}" if _bec else ""))
            _pick_card_from_zone(game, ctrl, pool, _do,
                                 "Elegí una carta del cementerio para reanimar",
                                 allow_none=True)
        return reanimate, None, 1
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
    # pump TEMPORAL a tu equipo: "creatures you control get +X/+Y until end of turn"
    mtp = re.search(r"creatures you control get ([+-]\d+)/([+-]\d+)", seg, re.I)
    if mtp:
        dp, dt = int(mtp.group(1)), int(mtp.group(2))

        def team_pump(game, ctrl, targets, _p=dp, _t=dt):
            for pm in list(ctrl.creatures()):
                pm.temp_pt[0] += _p
                pm.temp_pt[1] += _t
            game.sba()
            game.log(f"{ctrl.name}: sus criaturas +{_p}/+{_t} este turno")
        return team_pump, None, 1
    # poner N +1/+1 en CADA criatura (o criatura/Vehicle) que controlás (Ao, etc.)
    mec = re.search(r"put (\w+) \+1/\+1 counters? on each (?:permanent you control that'?s "
                    r"a creature or vehicle|creature you control|other creature you control)",
                    seg, re.I)
    if mec and (nec := _count_word(mec.group(1))):
        other = "other creature" in seg.lower()
        def put_each(game, ctrl, targets, _n=nec, _o=other, _src=None):
            for pm in list(ctrl.creatures()):
                game.add_counters(pm, "+1/+1", _n)
            game.log(f"{ctrl.name}: +{_n}/+{_n} a cada criatura que controla")
        return put_each, None, 1
    # poner contadores +1/+1 en una criatura objetivo (incluye "up to one target")
    mc = re.search(r"put (\w+) \+1/\+1 counters? on (?:up to \w+ )?target creature", seg, re.I)
    if mc and _count_word(mc.group(1)):
        n = _count_word(mc.group(1))
        kw_grant = next((v for pat, v in _TOKEN_KEYWORDS
                         if re.search(r"(?:gains?|has) .*" + pat, seg, re.I)), None)

        def putc(game, ctrl, targets, _n=n, _kw=kw_grant):
            for tg in (targets or []):
                if hasattr(tg, "counters"):
                    game.add_counters(tg, "+1/+1", _n)
                    if _kw:
                        tg.temp_keywords.add(_kw)
        return putc, "own_creature", 1
    # Barridas por tipo como MODO ("destroy all creatures/planeswalkers/battles",
    # "exile all graveyards"). En un modo van por _fragment_effect (no por el tag wipe).
    _cs = _copy_token_spec(seg)
    if _cs is not None:
        if _cs["kind"] == "target":
            def copy_tg(game, ctrl, targets, _s=_cs):
                tg = (list(targets or []) or [None])[0]
                if (tg is None or not hasattr(tg, "card")
                        or (_s.get("nonlegendary_only") and "legendary" in tg.card.supertypes)
                        or (_s.get("nontoken_only") and tg.is_token)):
                    _copy_token_effect(_s)(game, ctrl)     # sin objetivo: elegir acá
                    return
                _make_token_copies(game, ctrl, tg, _s)
            return copy_tg, ("opp_creature" if _cs.get("opp") else "own_creature"), 1
        _ce = _copy_token_effect(_cs)
        return (lambda game, ctrl, targets=None, _e=_ce: _e(game, ctrl)), None, 1
    _md = _mass_destroy_effect(seg)
    if _md == "?":
        return None, None, 1         # calificador desconocido: sin efecto (regla 5)
    if _md is not None:
        return (lambda game, ctrl, targets=None, _e=_md: _e(game, ctrl, targets)), None, 1
    mall = re.search(r"destroy all (creatures?|planeswalkers?|battles?|lands?|"
                     r"artifacts?|enchantments?|nonland permanents?|permanents?)", seg, re.I)
    if mall:
        kind = mall.group(1).lower().rstrip("s")

        def _matches(pm, _k=kind):
            if _k == "land":
                return pm.card.is_land()
            if _k == "permanent":
                return True
            if _k == "nonland permanent":
                return not pm.card.is_land()
            return _k in pm.card.types

        def wipe_type(game, ctrl, targets, _k=kind):
            for pl in game.players:
                for pm in list(pl.battlefield):
                    if _matches(pm):
                        game.destroy(pm, f"destruir todos los {_k}")
            game.sba()
            game.log(f"Se destruyen todos los {_k}")
        return wipe_type, None, 1
    if re.search(r"exile all graveyards", seg, re.I):
        def exile_gys(game, ctrl, targets):
            for pl in game.players:
                while pl.graveyard:
                    pl.exile.append(pl.graveyard.pop())
            game.log("Se exilian todos los cementerios")
        return exile_gys, None, 1
    # "Each opponent loses all counters" (Final Act): quita contadores de sus
    # permanentes y el veneno del jugador.
    if re.search(r"each opponent loses all counters", seg, re.I):
        def lose_counters(game, ctrl, targets):
            for o in game.opponents(ctrl):
                for pm in o.battlefield:
                    pm.counters = {}
                o.poison = 0
            game.sba()
            game.log("Cada rival pierde todos sus contadores")
        return lose_counters, None, 1
    # Investigate (N): crea N fichas Pista (Clue).
    minv = re.search(r"\binvestigate(?: (\w+))?\b", seg, re.I)
    if minv:
        ninv = _count_word(minv.group(1)) if minv.group(1) else 1

        def investigate(game, ctrl, targets, _n=ninv or 1):
            for _ in range(_n):
                cards.make_resource_token(game, ctrl, "Clue")
            game.log(f"{ctrl.name} investiga: {_n} ficha(s) Pista")
        return investigate, None, 1
    # Bolster N: N contadores +1/+1 en la criatura propia de MENOR resistencia.
    mbo = re.search(r"bolster (\w+)", seg, re.I)
    if mbo and _count_word(mbo.group(1)):
        nbo = _count_word(mbo.group(1))

        def bolster(game, ctrl, targets, _n=nbo):
            mine = list(ctrl.creatures())
            if mine:
                game.add_counters(min(mine, key=lambda c: c.toughness), "+1/+1", _n)
                game.log(f"Reforzar (bolster) {_n}")
        return bolster, None, 1
    # Support N: +1/+1 en cada una de hasta N criaturas objetivo (bot: propias).
    msu = re.search(r"support (\w+)", seg, re.I)
    if msu and _count_word(msu.group(1)):
        nsu = _count_word(msu.group(1))

        def support(game, ctrl, targets, _n=nsu):
            tgs = list(targets or [])
            if not tgs:
                tgs = sorted(ctrl.creatures(), key=lambda c: -(c.power + c.toughness))[:_n]
            for tg in tgs[:_n]:
                if hasattr(tg, "counters"):
                    game.add_counters(tg, "+1/+1", 1)
        return support, "own_creature", nsu
    # Amass N (Orcs/Zombies): pon N +1/+1 en un Ejército; si no hay, crea uno 0/0.
    mam = re.search(r"amass (?:\w+ )?(\w+)", seg, re.I)
    if mam and _count_word(mam.group(1)):
        nam = _count_word(mam.group(1))

        def amass(game, ctrl, targets, _n=nam):
            army = next((pm for pm in ctrl.battlefield
                         if "Army" in getattr(pm.card, "subtypes", set())), None)
            if army is None:
                army = cards.make_token(game, ctrl, "Army", 0, 0, subtypes=("Army",))
            if army is not None:
                game.add_counters(army, "+1/+1", _n)
                game.log(f"Amasar {_n}: el Ejército crece")
        return amass, None, 1
    # Incubate N: crea una ficha Incubadora con N +1/+1 (aprox: 0/0 con N contadores).
    minc = re.search(r"incubate (\w+)", seg, re.I)
    if minc and _count_word(minc.group(1)):
        ninc = _count_word(minc.group(1))

        def incubate(game, ctrl, targets, _n=ninc):
            tok = cards.make_token(game, ctrl, "Phyrexian", 0, 0, subtypes=("Phyrexian",))
            if tok is not None:
                game.add_counters(tok, "+1/+1", _n)
                game.log(f"Incubar {_n}")
        return incubate, None, 1
    # girar una criatura objetivo (acepta el rider "does not untap…"; solo evita
    # confundirse con "untap target creature", que es lo contrario)
    if re.search(r"\btap target creature", seg, re.I) and not re.search(
            r"\buntap target", seg, re.I):
        def tapc(game, ctrl, targets):
            for tg in (targets or []):
                if hasattr(tg, "tapped"):
                    tg.tapped = True
                    if re.search(r"does ?n'?o?t untap", seg, re.I):
                        tg.frozen = True            # no se endereza en su próximo enderezar
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
            if not amt:
                return
            tgts = [t for t in (targets or []) if hasattr(t, "life")]  # jugadores
            if tgts:                                   # objetivo ya elegido
                for tg in tgts:
                    game.deal_damage(None, tg, amt)
                    game.log(f"{ctrl.name}: {amt} de daño a {tg.name}")
            else:                                      # si no, el humano elige el rival
                _pick_opponent(game, ctrl, lambda o, _a=amt: (
                    game.deal_damage(None, o, _a),
                    game.log(f"{ctrl.name}: {_a} de daño a {o.name}")))
        return burnp, "opp_player", 1
    geff = _generic_amount_effect(seg)
    if geff is None:
        dm = re.search(r"draw (\w+) cards?", seg, re.I)
        if dm and dm.group(1).lower() == "x":        # "draw X cards" -> X elegido
            def geff(game, ctrl, *_a):               # noqa: F811
                ctrl.draw(min(40, int(getattr(game, "spell_x", 0) or 0)), game)
        elif dm and (n := _count_word(dm.group(1))):
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
    for seg in parts[:8]:               # hasta 8 modos (Final Act tiene 5)
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
    # cuántos modos se pueden elegir (según el encabezado)
    if "more" in head:                  # "choose one or more": cualquier cantidad
        pick = len(modes)
    elif "both" in head or "two" in head:
        pick = 2
    elif "three" in head:
        pick = 3
    elif head.startswith("up to"):
        pick = _count_word(head.replace("up to", "").strip()) or 1
    else:
        pick = 1
    pick = min(pick, len(modes))
    return modes, pick


def _modal_targets_for(game, ctrl, spec):
    """Objetivos legales para el spec de un modo (rival primero). [] si no aplica."""
    if not spec:
        return []
    perms = [p for pl in game.players for p in pl.battlefield]
    if spec == "opp_player":
        return [(f"{o.name} ({o.life} de vida)", o) for o in game.targetable_opponents(ctrl)]
    if spec == "opp_creature":
        pool = [pm for pm in perms if pm.is_creature()
                and pm.controller is not ctrl and game.can_target(ctrl, pm)]
    elif spec == "own_creature":
        pool = [pm for pm in perms if pm.is_creature() and pm.controller is ctrl]
    elif spec in ("any_art_ench", "any_artifact", "any_enchantment",
                  "any_planeswalker", "any_nonland", "any_perm"):
        def pred(pm, _s=spec):
            tp = pm.card.types
            return {
                "any_art_ench": bool({"artifact", "enchantment"} & tp),
                "any_artifact": "artifact" in tp,
                "any_enchantment": "enchantment" in tp,
                "any_planeswalker": "planeswalker" in tp,
                "any_nonland": not pm.card.is_land(),
                "any_perm": True,
            }[_s]
        pool = [pm for pm in perms if pred(pm) and game.can_target(ctrl, pm)]
        pool = [pm for pm in pool if pm.controller is not ctrl] or pool
    else:
        return []
    return [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]


def _modal_run_one(game, ctrl, mode):
    """Ejecuta un modo: si pide objetivo, el humano lo elige (pending_choice) y el
    bot auto-apunta; si no, se aplica directo."""
    eff = mode.get("effect")
    if eff is None:
        return
    spec = mode.get("target_spec")
    opts = _modal_targets_for(game, ctrl, spec)
    if spec and opts:
        _human_target_choice(
            game, ctrl, "mode_target",
            f"Objetivo para «{mode.get('label', '')}»",
            opts, lambda obj: eff(game, ctrl, [obj]), allow_none=False)
    else:
        eff(game, ctrl, [])                           # sin objetivo (o ninguno legal)


def _modal_run(game, ctrl, modes):
    """Abre el selector de MODO: humano elige vía pending_choice; el bot prefiere un
    modo con objetivo disponible y lo auto-aplica."""
    if ctrl is getattr(game, "interactive_human", None):
        _human_target_choice(
            game, ctrl, "mode", "Elegí un modo",
            [(m["label"], i) for i, m in enumerate(modes)],
            lambda i: _modal_run_one(game, ctrl, modes[i]), allow_none=False)
    else:
        best = next((m for m in modes if m.get("target_spec")
                     and _modal_targets_for(game, ctrl, m["target_spec"])), None)
        if best is None:
            best = next((m for m in modes if not m.get("target_spec")), modes[0])
        _modal_run_one(game, ctrl, best)


def _modal_trigger_runner(full_oracle: str):
    """Para un disparo MODAL ('... , choose one — • ... • ...'): devuelve un runner
    run(game, perm) que abre el selector de modo. None si no es modal. Parsea los
    modos del oráculo COMPLETO (la captura del disparo se trunca y perdería modos)."""
    parsed = _parse_modes(full_oracle)
    if parsed is None:
        return None
    modes = parsed[0]
    return lambda game, perm: _modal_run(game, perm.controller, modes)


def _parse_activated(oracle: str, name: str = ""):
    """Envoltorio: por línea, quita los rótulos Exhaust / Boast / Power-up y las
    restricciones 'Activate only …' del cuerpo, parsea la habilidad y le anota las
    restricciones (una vez por partida, solo si atacó, solo si <condición>, solo
    como conjuro, una vez por turno)."""
    out = []
    for raw in (oracle or "").split("\n"):
        ln = raw.strip()
        flags = {}
        mex_cost = re.search(r"(?i),?\s*exert (?:this creature|this land|this artifact|~|"
                             + re.escape(name or "~") + r")(?=\s*[,:]|$)", ln.split(":")[0]
                             if ":" in ln else "")
        if mex_cost:
            flags["exert_self"] = True
            ln = ln.replace(mex_cost.group(0), "", 1)
        mto = re.search(r"(?i),?\s*tap (an|a|another|one|two|three|four|five|\d+) untapped ([a-z]+?s?(?: and/or [a-z]+?s?)?)"
                        r" you control(?=\s*[,:]|$)", ln.split(":")[0] if ":" in ln else "")
        if mto:
            flags["tap_others"] = {"n": _count_word(mto.group(1).lower().replace("another", "a")) or 1,
                                   "type": "|".join(_sing(x) for x in mto.group(2).lower().split(" and/or "))}
            ln = ln.replace(mto.group(0), "", 1)
            if ln.lstrip().startswith(":"):          # solo era el coste de girar: coste {0}
                ln = "{0}" + ln.lstrip()
        mpre = re.match(r"(?i)(exhaust|boast|power-up)\s*[—–-]\s*", ln)
        if mpre:
            kw = mpre.group(1).lower()
            flags["boast" if kw == "boast" else "once"] = True
            ln = ln[mpre.end():]
        for mo in list(re.finditer(r"(?i)\s*activate (?:this ability )?only ([^.]+)\.", ln)):
            _parts = [x.strip() for x in re.split(r",? and only |, only ", mo.group(1).strip().lower()) if x.strip()]
            if len(_parts) > 1:
                for cond in _parts:
                    if cond in ("as a sorcery", "any time you could cast a sorcery"):
                        flags["sorcery_speed"] = True
                    elif cond == "once each turn":
                        flags["once_turn"] = True
                    elif cond == "once":
                        flags["once"] = True
                    elif cond.startswith("if ") and (gc := _cond_gc(cond[3:])) is not None:
                        _pg = flags.get("only_if")
                        flags["only_if"] = gc if _pg is None else (lambda g, p, _a=_pg, _b=gc: _a(g, p) and _b(g, p))
                    elif cond.startswith("during your turn"):
                        _pg = flags.get("only_if")
                        _dt = (lambda g, p: g.players[g.active_index] is p)
                        flags["only_if"] = _dt if _pg is None else (lambda g, p, _a=_pg, _b=_dt: _a(g, p) and _b(g, p))
                    else:
                        flags = None
                        break
                if flags is None:
                    break
                ln = ln.replace(mo.group(0), "")
                continue
            cond = mo.group(1).strip().lower()
            if cond == "once":
                flags["once"] = True
                ln = ln.replace(mo.group(0), "")
                continue
            if cond in ("if this case is solved", "if ~ is solved"):
                flags["solved_req"] = True
            elif cond in ("as a sorcery", "any time you could cast a sorcery"):
                flags["sorcery_speed"] = True
            elif cond == "once each turn":
                flags["once_turn"] = True
            elif cond.startswith("if "):
                gc = _cond_gc(cond[3:])
                if gc is None:
                    flags = None             # restricción desconocida: no se cablea
                    break
                flags["only_if"] = gc
            elif cond.startswith("during your turn"):
                flags["only_if"] = lambda g, p: g.players[g.active_index] is p
            else:
                flags = None
                break
            ln = ln.replace(mo.group(0), "")
        if flags is None:
            continue
        for ab in _parse_activated_core(ln, name):
            if flags:
                ab = dict(ab, **flags)
            out.append(ab)
    return tuple(out)


_ENERGY_COST = re.compile(r"pay (?:((?:\{e\})+)|(\w+) \{e\})", re.I)


def _parse_activated_core(oracle: str, name: str = ""):
    """Envoltorio: las líneas con energía en el coste ('Pay {E}{E}: …', '{T}, Pay
    eight {E}: …') se parsean con el coste de energía reemplazado por {0} y el
    dict lleva 'energy': N (el motor lo cobra al activar)."""
    lines = (oracle or "").split("\n")

    def _en(ln):
        if ":" not in ln:
            return None
        mm = _ENERGY_COST.search(ln.split(":")[0])
        if not mm:
            return None
        n = mm.group(1).lower().count("{e}") if mm.group(1) else _count_word(mm.group(2).lower())
        return (n, ln.replace(mm.group(0), "{0}", 1)) if n else None
    if not any(_en(ln) for ln in lines):
        return _parse_activated_core0(oracle, name)
    out = list(_parse_activated_core0("\n".join(ln for ln in lines if not _en(ln)), name))
    for ln in lines:
        e = _en(ln)
        if e:
            out.extend(dict(ab, energy=e[0]) for ab in _parse_activated_core0(e[1], name))
    return tuple(out[:4])


def _parse_activated_core0(oracle: str, name: str = ""):
    """Habilidades activadas con coste de MANÁ (+ opcional {T} y opcional
    'Sacrifice this ~' como coste). Devuelve una tupla de dicts {cost, tap,
    sacrifice_self, label, effect, target_spec, target_count}. Ignora otros costes
    (descartar, pagar vida) y efectos que no reconocemos."""
    name_key = re.sub(r"[^a-z]", "", (name or "").lower())
    out = []
    _fh = [0, False]                   # (inicio de la línea previa en out, ¿desde la mano?)
    _xc = [[]]                         # costes extra de la línea previa (batch 21)
    for raw in (oracle or "").split("\n") + [""]:
        if _fh[1]:
            for _ab in out[_fh[0]:]:
                _ab["from_hand"] = True
        if _xc[0]:
            for _ab in out[_fh[0]:]:
                _ab["extra_cost"] = list(_xc[0])
        _xc[0] = []
        _fh[0], _fh[1] = len(out), False
        if not raw:
            continue
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
        exile_self = False
        rm_counter = None  # {"name": str, "n": int} — quitar contadores de SÍ MISMA (coste)
        sac_other = None   # {"count": n, "type": "..."} — sacrificar OTRAS permanentes
        _extra_cost = []   # batch 21: [(tipo, clase, n)] costes extra que cobra el motor
        pay_life = 0
        discard = 0        # nº de cartas a descartar (-1 = toda la mano)
        from_hand = False  # coste "discard this card": se activa DESDE LA MANO
        bad = False
        for cl in costtxt.split(","):
            syms.extend(re.findall(r"\{([^}]+)\}", cl))
            rest = re.sub(r"\{[^}]+\}", "", cl).strip().lower().rstrip(".")
            if not rest:
                continue
            key = re.sub(r"[^a-z]", "", rest)
            if key.startswith("exile"):          # "Exile this/~/<nombre>" como coste
                tail = key[len("exile"):]
                if tail.startswith(("this", "it", "~")) or (name_key and tail == name_key):
                    exile_self = True
                    continue
            # "Remove a/N <X> counter(s) from this/~/<nombre>" como coste
            mrc_cost = re.match(r"remove (a|an|\d+|two|three|four|five|\w+) "
                                r"([a-z+\-/0-9]+) counters? from ([\w' ]+)", rest)
            if mrc_cost and _count_word(mrc_cost.group(1)):
                _frm = re.sub(r"[^a-z]", "", mrc_cost.group(3))
                if _frm.startswith(("this", "it", "~")) or (name_key and name_key in _frm):
                    rm_counter = {"name": mrc_cost.group(2).lower(),
                                  "n": _count_word(mrc_cost.group(1))}
                    continue
            if key.startswith("sacrifice"):
                tail = key[len("sacrifice"):]
                if tail.startswith(("this", "it", "~")) or (name_key and tail == name_key):
                    sac_self = True
                    continue
                rest = re.sub(r"^sacrifice (a|an|another) nontoken artifact$", r"sacrifice \1 artifact", rest)
                rest = re.sub(r"^sacrifice (a|an|another) creature or planeswalker$", r"sacrifice \1 creature", rest)
                msu = re.fullmatch(r"sacrifice (a|an|another) (creature|artifact|enchantment|land|planeswalker|token)"
                                   r",? or (?:an? )?(creature|artifact|enchantment|land|planeswalker|token|blood token|food)", rest)
                if msu:
                    sac_other = {"count": 1, "type": msu.group(2) + "|" + msu.group(3).replace(" token", "")}
                    continue
                msc = re.fullmatch(r"sacrifice (a|an|another) (white|blue|black|red|green|colorless|nontoken|[a-z]+) creature", rest)
                if msc:
                    _w = msc.group(2)
                    sac_other = {"count": 1, "type": ("color:" + _w) if _w in ("white", "blue", "black", "red", "green",
                                                                              "colorless") else
                                 ("nontoken_creature" if _w == "nontoken" else _w)}
                    continue
                mso = re.match(r"sacrifice (a|an|another|\d+|two|three|four|\w+) "
                               r"(creature|permanent|artifact|land|enchantment|token|[a-z]+?)s?$",
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
            # batch 21: costes extra (devolver/exiliar/quitar contadores de otro/poner arriba)
            mrb = re.fullmatch(r"return (a|an|another|one|two|three|\d+) (land|forest|island|swamp|mountain|plains|creature|"
                               r"artifact|enchantment|permanent|elf|goblin)s? you control to (?:its|their) owner(?:'s|s') hands?",
                               rest)
            if mrb and _count_word(mrb.group(1).replace("another", "a")):
                _extra_cost.append(("bounce", mrb.group(2), _count_word(mrb.group(1).replace("another", "a"))))
                continue
            if re.fullmatch(r"return (?:this (?:enchantment|creature|artifact|permanent)|~|" + re.escape((name or "~").lower())
                            + r") to its owner's hand", rest):
                _extra_cost.append(("bounce_self", None, 1))
                continue
            mxg = re.fullmatch(r"exile (?:the top (creature )?card of your graveyard|(a|an|another|one|two|three|\d+) "
                               r"(creature |instant or sorcery |artifact |land |)cards? from your graveyard)", rest)
            if mxg:
                _k = (mxg.group(1) or mxg.group(3) or "").strip()
                _n = 1 if not mxg.group(2) else (_count_word(mxg.group(2).replace("another", "a")) or 1)
                _extra_cost.append(("exile_gy", _k, _n))
                continue
            mrca = re.fullmatch(r"remove (a|an|one|two|three|\d+) (\+1/\+1 |[a-z]+ |)counters? from (a|another) "
                                r"(creature|permanent|artifact) you control", rest)
            if mrca and _count_word(mrca.group(1)):
                _extra_cost.append(("rm_counter_any", mrca.group(2).strip() or None, _count_word(mrca.group(1))))
                continue
            mrcs = re.fullmatch(r"remove (a|an|one|two|three|\d+|x) counters? from (?:this \w+|~|it)", rest)
            if mrcs and _count_word(mrcs.group(1)):
                rm_counter = {"name": "*any*", "n": _count_word(mrcs.group(1))}
                continue
            if rest in ("put a card from your hand on top of your library",):
                _extra_cost.append(("hand_top", None, 1))
                continue
            if rest.startswith("discard"):
                _dt = rest[len("discard"):].strip()
                if _dt in ("this card", "~") or (name_key and re.sub(r"[^a-z]", "", _dt) == name_key):
                    from_hand = True             # Channel / "discard this card:" (desde la mano)
                    _fh[1] = True
                    continue
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
        _xc[0] = _extra_cost
        # se acepta una habilidad sin maná/{T} solo si tiene un coste real (sacrificio,
        # exiliarse, quitar contadores, pagar vida, descartar).
        if not syms and not (sac_self or exile_self or rm_counter or sac_other
                             or pay_life or discard or from_hand or _extra_cost):
            continue
        tap = any(s.upper() == "T" for s in syms)
        x_cost = any(s.upper() == "X" for s in syms)   # habilidad con {X} en el coste
        mana = "".join("{%s}" % s for s in syms if s.upper() not in ("T", "X"))
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
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self, "exile_self": exile_self, "rm_counter": rm_counter,
                        "sacrifice_other": sac_other, "pay_life": pay_life,
                        "discard": discard, "label": _short_label(body),
                        "effect": (lambda g, c, perm, tg, _e=eff: _e(g, c, tg)),
                        "target_spec": None, "target_count": 1,
                        "is_copy_ability": False})
            continue
        # habilidad {X}: "{X}: ~ deals X damage to <objetivo>" (Crypt Rats, Fireball,
        # Comet Storm, Blaze…). El valor de X lo elige quien activa; el motor lo pasa
        # al efecto vía game._ability_x.
        if x_cost:
            mxd = re.search(r"deals x damage to ([\w' ,]+)", body, re.I)
            if mxd:
                dest = mxd.group(1).lower()
                all_cre = "each creature" in dest
                all_pl = "each player" in dest
                each_opp = "each opponent" in dest
                tgt_creature = ("target creature" in dest) and not all_cre

                def eff_xdmg(g, c, perm, tg, _ac=all_cre, _ap=all_pl,
                             _eo=each_opp, _tc=tgt_creature):
                    x = max(0, int(getattr(g, "_ability_x", 0) or 0))
                    if x <= 0:
                        return
                    if _ac or _ap or _eo:
                        if _ac:
                            for pl in g.players:
                                for pm in list(pl.creatures()):
                                    g.deal_damage(perm, pm, x)
                        if _ap:
                            for pl in g.players:
                                g.deal_damage(perm, pl, x)
                        if _eo:
                            for o in g.opponents(c):
                                g.deal_damage(perm, o, x)
                    elif _tc and tg:
                        g.deal_damage(perm, tg[0], x)
                    else:                       # "any target"/"target player" -> rival
                        opps = g.opponents(c)
                        if opps:
                            g.deal_damage(perm, min(opps, key=lambda o: o.life), x)
                    g.log(f"{c.name}: {perm.name if perm else '—'} inflige {x} de daño (X)")
                    g.sba()
                out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self,
                            "exile_self": exile_self, "rm_counter": rm_counter,
                            "sacrifice_other": sac_other, "pay_life": pay_life,
                            "discard": discard, "label": _short_label(body),
                            "effect": eff_xdmg,
                            "target_spec": ("opp_creature" if tgt_creature else None),
                            "target_count": 1, "is_copy_ability": False,
                            "x_cost": True,
                            # pega a cada criatura/jugador -> el bot lo evita (auto-daño)
                            "x_self_harm": bool(all_cre or all_pl)})
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
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self, "exile_self": exile_self, "rm_counter": rm_counter,
                        "sacrifice_other": sac_other, "pay_life": pay_life,
                        "discard": discard, "label": _short_label(body),
                        "effect": eff_self, "target_spec": None,
                        "target_count": 1, "is_copy_ability": False})
            continue
        # Vorel: "for each kind of counter on target ... double the number of those
        # counters on it" -> duplica TODO tipo de contador en un permanente tuyo.
        if re.search(r"double the number of those counters", body, re.I):
            def eff_double(g, c, perm, tg):
                for pmt in list(tg or []):
                    for k in list(pmt.counters.keys()):
                        cur = pmt.counters.get(k, 0)
                        if cur <= 0:
                            continue
                        if k == "+1/+1":
                            g.add_counters(pmt, k, cur)     # respeta dobladores
                        else:
                            pmt.counters[k] += cur
                    g.log(f"{c.name} duplica los contadores de {pmt.name}")
                g.sba()
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self,
                        "exile_self": exile_self, "rm_counter": rm_counter,
                        "sacrifice_other": sac_other, "pay_life": pay_life,
                        "discard": discard, "label": _short_label(body),
                        "effect": eff_double, "target_spec": "own_creature",
                        "target_count": 1, "is_copy_ability": False})
            continue
        # quitar contadores: "remove a/N <X> counter(s) from <destino>".
        #   destino = this/it/~/<nombre>  -> de SÍ MISMA (usa el permanente fuente).
        #   destino = target permanent/... -> de un objetivo elegido.
        mrc = re.search(r"remove (a|an|\d+|two|three|four|five|\w+) "
                        r"(?:([a-z]+) )?counters? from ([\w' ]+)", body, re.I)
        if mrc and (_rn := _count_word(mrc.group(1))):
            _cn = (mrc.group(2) or "counters").lower()
            _from = re.sub(r"[^a-z]", "", mrc.group(3).lower())
            _self = (_from in ("this", "thispermanent", "thiscreature", "thisland",
                               "thisartifact", "thisenchantment", "it", "itself", "")
                     or (name_key and name_key and name_key in _from))

            def _strip(perm, _n=_rn, _k=_cn):
                if _k in ("counter", "counters"):      # genérico: cualquier tipo
                    left = _n
                    for kk in sorted(perm.counters, key=lambda x: -perm.counters[x]):
                        if left <= 0:
                            break
                        take = min(left, perm.counters[kk])
                        perm.counters[kk] -= take
                        left -= take
                else:
                    perm.counters[_k] = max(0, perm.counters.get(_k, 0) - _n)

            if _self:
                def eff_self_rc(g, c, perm, tg, _s=_strip):
                    if perm is not None:
                        _s(perm)
                        g.log(f"{perm.name}: quita contadores")
                        g.sba()
                out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self, "exile_self": exile_self, "rm_counter": rm_counter,
                            "sacrifice_other": sac_other, "pay_life": pay_life,
                            "discard": discard, "label": _short_label(body),
                            "effect": eff_self_rc, "target_spec": None,
                            "target_count": 1, "is_copy_ability": False})
                continue
            if _from.startswith("target"):
                def eff_tgt_rc(g, c, tg=None, _s=_strip):
                    for t_ in (tg or []):
                        if hasattr(t_, "counters"):
                            _s(t_)
                            g.log(f"{c.name}: quita contadores de {t_.name}")
                    g.sba()
                out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self, "exile_self": exile_self, "rm_counter": rm_counter,
                            "sacrifice_other": sac_other, "pay_life": pay_life,
                            "discard": discard, "label": _short_label(body),
                            "effect": (lambda g, c, perm, tg, _e=eff_tgt_rc: _e(g, c, tg)),
                            "target_spec": "any_perm", "target_count": 1,
                            "is_copy_ability": False})
                continue
        # "~ becomes a copy of target land, except it has this ability" (Thespian's
        # Stage). Copia la carta OBJETIVO sobre el permanente fuente SIN copiar los
        # contadores ni re-disparar el ETB -> si copia Dark Depths, queda con 0
        # contadores de hielo y la sba la sacrifica creando Marit Lage.
        if re.search(r"becomes? a copy of target land", body, re.I):
            def eff_copy(g, ctrl, perm, tg):
                import copy as _copylib
                cands = [pm for pl in g.players for pm in pl.battlefield
                         if pm.card.is_land() and pm is not perm]
                if not cands:
                    return
                keep = tuple(a for a in (perm.card.activated_abilities or ())
                             if "copy of target land" in a.get("label", "").lower())

                def _do(target):
                    newcard = _copylib.deepcopy(target.card)
                    # "except it has this ability": conserva la habilidad de copiar
                    newcard.activated_abilities = (
                        tuple(newcard.activated_abilities or ()) + keep)
                    perm.card = newcard
                    g.log(f"{perm.name} se vuelve una copia de {target.name}")
                    g.sba()
                # bot: prioriza una tierra que sea combo (sac al quedar sin contadores)
                cands.sort(key=lambda pm: getattr(pm.card, "sac_when_no_counter", None) is None)
                labels = [(f"{pm.name} · {pm.controller.name}", pm) for pm in cands]
                _human_target_choice(g, ctrl, "etb_target",
                                     "Elegí la tierra a copiar", labels, _do)
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self, "exile_self": exile_self, "rm_counter": rm_counter,
                        "sacrifice_other": sac_other, "pay_life": pay_life,
                        "discard": discard, "label": _short_label(body),
                        "effect": eff_copy, "target_spec": None,
                        "target_count": 1, "is_copy_ability": False})
            continue
        # "shuffle any number of target cards from your graveyard into your library"
        # (Perpetual Timepiece): multi-selector del cementerio (el humano elige
        # cuántas y cuáles, de a una; el bot baraja de vuelta las no-tierra).
        if re.search(r"shuffle any number of target cards? from your graveyard into "
                     r"your library", body, re.I):
            def eff_shuffle_gy(g, ctrl, perm, tg):
                _shuffle_graveyard_into_library(g, ctrl)
            out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self,
                        "exile_self": exile_self, "sacrifice_other": sac_other,
                        "pay_life": pay_life, "discard": discard,
                        "label": _short_label(body), "effect": eff_shuffle_gy,
                        "target_spec": None, "target_count": 1, "is_copy_ability": False})
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
        out.append({"cost": cost, "tap": tap, "sacrifice_self": sac_self, "exile_self": exile_self, "rm_counter": rm_counter,
                    "sacrifice_other": sac_other, "pay_life": pay_life,
                    "discard": discard,
                    "label": _short_label(body),
                    "effect": (lambda g, c, perm, tg, _e=eff: _e(g, c, tg)),
                    "target_spec": spec, "target_count": count,
                    "is_copy_ability": is_copy})
    if _fh[1]:
        for _ab in out[_fh[0]:]:
            _ab["from_hand"] = True
    return tuple(out[:4])


def _attack_trigger_effect(oracle: str):
    """'Whenever ~ attacks, <efecto>' -> callback de trigger (g, perm, **kw) o None.
    Cubre p. ej. Laelia (al atacar, exiliar el tope y poder jugarla)."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    m = re.search(r"whenever [^.]{0,50}? attacks,?\s*(.{0,400})", t, re.I)
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
    # connive (N): al atacar, la criatura connive.
    mcon = re.search(r"connives?(?: (\w+))?", body, re.I)
    if mcon:
        ncon = _count_word(mcon.group(1)) if mcon.group(1) else 1

        def trig_connive(game, perm, _n=ncon or 1, **_kw):
            _do_connive(game, perm, _n)
        return trig_connive
    # "defending player / that player loses N life" o "deals N damage to defending
    # player": afecta al jugador atacado (defender viene en el disparo).
    mdp = re.search(r"(?:defending player|that player) loses (\w+) life", body, re.I)
    mdd = re.search(r"deals? (\w+) damage to (?:defending player|that player)", body, re.I)
    if mdp or mdd:
        is_dmg = mdd is not None
        nm = (mdd if is_dmg else mdp).group(1)
        amt = _count_word(nm) or 1

        def trig_def(game, perm, defender=None, _n=amt, _dmg=is_dmg, **_kw):
            pl = defender if hasattr(defender, "life") else getattr(defender, "controller", None)
            if pl is None or not hasattr(pl, "life"):
                return
            if _dmg:
                game.deal_damage(perm, pl, _n)
            else:
                pl.life -= _n
            game.log(f"{perm.name}: {pl.name} pierde {_n} de vida (ataque)")
        return trig_def
    eff, _spec, _count = _fragment_effect(body)
    if eff is None:
        return None

    def trig(game, perm, **_kw):
        eff(game, perm.controller, [])
    return trig


def _everything_counter_effect():
    """Omo: pon un contador 'everything' en hasta 1 tierra objetivo y hasta 1
    criatura objetivo (el humano elige, encadenado; puede omitir). La criatura pasa
    a ser de todos los tipos de criatura y la tierra de todos los tipos de tierra
    (ver Permanent.has_subtype)."""
    def eff(game, ctrl, perm=None):
        def _put(pm):
            if pm is None:
                return
            pm.counters["everything"] = pm.counters.get("everything", 0) + 1
            game.log(f"{pm.name} recibe un contador 'todo' (todos los tipos)")
            game.sba()

        lands = [pm for pl in game.players for pm in pl.battlefield if pm.card.is_land()]
        creats = [pm for pl in game.players for pm in pl.battlefield if pm.is_creature()]
        lands.sort(key=lambda x: x.controller is not ctrl)     # propias primero (bot)
        creats.sort(key=lambda x: (x.controller is not ctrl, -(x.power + x.toughness)))

        def _choose_land():
            if not lands:
                return
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in lands]
            _human_target_choice(game, ctrl, "etb_target",
                                 "Contador 'todo': elegí una tierra (o ninguna)",
                                 cands, _put, allow_none=True)

        if creats:
            ccands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                      for pm in creats]

            def _do_creat(pm):
                _put(pm)
                _choose_land()
            _human_target_choice(game, ctrl, "etb_target",
                                 "Contador 'todo': elegí una criatura (o ninguna)",
                                 ccands, _do_creat, allow_none=True)
        else:
            _choose_land()
    return eff


def _ability_clause(body: str) -> str:
    """Recorta el cuerpo de un disparo en el límite de la SIGUIENTE habilidad.
    Como el oráculo colapsa los saltos de línea a espacios, una captura ávida
    (p. ej. `.{0,140}`) puede 'comerse' el texto de otra habilidad posterior
    ({T}: ... u otro disparo) y producir efectos cruzados o BUCLES (Niv-Mizzet,
    Ghost Counsel: 'gano 1 vida' re-disparaba 'cada rival pierde 1 y gano 1')."""
    cut = re.search(r"\{[^}]*\}\s*:|(?:^|\s)(?:whenever|at the beginning of)\b",
                    body, re.I)
    return body[:cut.start()].strip() if cut else body


_SPELL_TYPES = {"creature", "artifact", "enchantment", "instant", "sorcery",
                "planeswalker", "land", "battle"}
_UNKNOWN_SPELL_QUALS = {"multicolored", "colorless", "historic", "legendary", "kicked",
                        "white", "blue", "black", "red", "green", "monocolored", "copy",
                        "permanent", "nonartifact", "noninstant"}


def _spell_filter(words):
    """'instant or sorcery' / 'noncreature' / 'creature' / 'Elf' / '' -> predicado
    card->bool; None si el calificador no se entiende (regla 5: mejor no cablear
    que disparar con cualquier hechizo, como pasaba con 'an Elf spell')."""
    w = (words or "").strip().lower()
    if not w:
        return lambda c: True
    if w in ("instant or sorcery", "instant and sorcery"):
        return lambda c: bool({"instant", "sorcery"} & c.types)
    mmv = re.fullmatch(r"(?:([a-z ]+?) )?spell with mana value (\d+) or (greater|less)", w)
    if mmv:
        base = _spell_filter(mmv.group(1) or "") if mmv.group(1) else (lambda c: True)
        if base is None:
            return None
        n, ge = int(mmv.group(2)), mmv.group(3) == "greater"
        return lambda c, _b=base, _n=n, _g=ge: _b(c) and (
            ((c.cost.cmc if c.cost else 0) >= _n) if _g else ((c.cost.cmc if c.cost else 0) <= _n))
    # colores / multicolor / histórico / legendario (Shrine, Jhoira, Sram…)
    _cmap = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

    def _cols(c):
        out = set()
        for p in (getattr(getattr(c, "cost", None), "pips", None) or ()):
            out |= {x for x in str(p).upper() if x in "WUBRG"}
        return out
    cw = [x for x in re.split(r",\s*(?:and |or )?|\s+(?:and|or)\s+", w) if x]
    if cw and all(x in _cmap for x in cw):
        return lambda c, _k=frozenset(_cmap[x] for x in cw): bool(_k & _cols(c))
    if w in ("multicolored", "multicolor"):
        return lambda c: len(_cols(c)) >= 2
    if w in ("colorless",):
        return lambda c: not _cols(c)
    if w == "monocolored":
        return lambda c: len(_cols(c)) == 1
    if w == "historic":
        return lambda c: ("artifact" in c.types or c.is_legendary()
                          or any(x.lower() == "saga" for x in c.subtypes))
    if w == "legendary":
        return lambda c: c.is_legendary()
    if w == "noncreature":
        return lambda c: "creature" not in c.types
    mct = re.fullmatch(r"(white|blue|black|red|green|multicolored|colorless|legendary) (creature|artifact|enchantment|"
                       r"instant|sorcery|planeswalker|noncreature)", w)
    if mct:
        _a, _b = _spell_filter(mct.group(1)), _spell_filter(mct.group(2))
        if _a is not None and _b is not None:
            return lambda c, _a=_a, _b=_b: _a(c) and _b(c)
    if w in _SPELL_TYPES:
        return lambda c, _t=w: _t in c.types
    # lista de tipos: "artifact and enchantment", "instant, sorcery, or artifact"
    parts = [x for x in re.split(r",\s*(?:and |or )?|\s+(?:and|or)\s+", w) if x]
    if len(parts) > 1 and all(x in _SPELL_TYPES for x in parts):
        return lambda c, _ts=frozenset(parts): bool(_ts & c.types)
    # tipos y subtipos mezclados: "Spirit or Arcane", "Dragon or Wizard"
    if len(parts) > 1 and all(re.fullmatch(r"[a-z]+", x) for x in parts):
        _ps = frozenset(x[:-1] if x.endswith("s") and not x.endswith("ss") else x for x in parts)
        return lambda c, _p=_ps: bool(_p & c.types) or any(x.lower() in _p for x in c.subtypes)
    if " " in w or w in _UNKNOWN_SPELL_QUALS or w.startswith("non"):
        return None
    sub = w[:-1] if w.endswith("s") and not w.endswith("ss") else w
    return lambda c, _s=sub: any(x.lower() == _s for x in c.subtypes)


def _cost_filter(words):
    """Filtro para spell_discount / spell_tax: los nombres simples de siempre
    (any/creature/noncreature/instant_sorcery/artifact) o un predicado para los
    demás (tribus, listas de tipos). None si no se entiende."""
    w = (words or "").strip().lower()
    simple = {"": "any", "creature": "creature", "noncreature": "noncreature",
              "artifact": "artifact", "instant and sorcery": "instant_sorcery",
              "instant or sorcery": "instant_sorcery"}
    if w in simple:
        return simple[w]
    return _spell_filter(w)


def _once_per_turn(cb):
    """Disparo con tope 'for the first time each turn' / 'only once each turn'."""
    def gated(game, perm, *a, _cb=cb, **kw):
        if getattr(perm, "_opt_turn", {}).get(id(_cb)) == game.turn:
            return None
        if not hasattr(perm, "_opt_turn"):
            perm._opt_turn = {}
        perm._opt_turn[id(_cb)] = game.turn
        return _cb(game, perm, *a, **kw)
    return gated


def _event_trigger_effect(oracle: str, _gate_once: bool = True):
    """Detecta disparos comunes y devuelve {evento: callback(g, perm, **kw)}.
    Los disparos de una línea con 'for the first time each turn' / 'only once each
    turn' se limitan a uno por turno (antes se ignoraba el tope: bucles infinitos
    como Prosperous Innkeeper + Gourmand's Talent)."""
    out = _event_trigger_effect_impl(oracle)
    if _gate_once and out:
        for ln in _ability_lines(oracle or ""):
            if re.search(r"for the first time (?:each|during each of your) turn|"
                         r"only once each turn|(?:first|second) [a-z ]*?each turn", ln, re.I):
                for ev in _event_trigger_effect(ln, _gate_once=False):
                    if ev in out:
                        out[ev] = _once_per_turn(out[ev])
    return out


def _event_trigger_effect_impl(oracle: str):
    """Detecta disparos comunes y devuelve {evento: callback(g, perm, **kw)}.
    Cubre 'cuando una criatura muere', 'daño de combate a un jugador' y
    'cuando lanzás un instant/sorcery' (magecraft). Reusa _generic_amount_effect
    sobre el texto del efecto (ficha, drenaje, robar, ganar vida, etc.)."""
    t = re.sub(r"[ \t]+", " ", (oracle or "")).strip()   # conserva \n: "." no cruza habilidades
    out = {}
    # muerte de criatura: distingue "a creature" (cualquiera) de "a creature you
    # control" (solo las tuyas) para no sobre-dispararse con muertes rivales.
    md = None
    for _ln in _ability_lines(oracle):
        md = re.search(r"whenever (this creature or |~ or |[\w,' -]+? or (?=another))?(a|an|another) (nontoken )?"
                       r"(creature|(?!creature)[a-z]+)( you control| an opponent controls| your opponents control| "
                       r"you don't control)? dies,?\s*(.{0,400})", _ln, re.I)
        if md and md.group(4).lower() != "creature" and not re.search(r"another", md.group(2), re.I):
            md = None                        # "a <subtipo> dies": solo con "another <subtipo>"
        if md:
            break
    if md:
        _sub_d = md.group(4).lower()
        md = re.search(r"whenever (this creature or |~ or |[\w,' -]+? or (?=another))?(a|an|another) (nontoken )?"
                       r"(?:creature|[a-z]+)( you control| an opponent controls| your opponents control| "
                       r"you don't control)? dies,?\s*(.{0,400})", md.group(0), re.I)
    if md:
        eff = _effect_any(md.group(5))
        if eff is not None:
            yours = (md.group(4) or "").strip().lower() == "you control"
            theirs = bool(md.group(4)) and not yours
            nontoken = bool(md.group(3))
            # "a/an creature" o "this creature or ..." incluyen a la propia; "another"
            # (sin "this creature or") excluye su propia muerte.
            self_counts = bool(md.group(1)) or md.group(2).lower() in ("a", "an")

            def cb_death(game, perm, player=None, self_death=False, subject=None,
                         _e=eff, _y=yours, _th=theirs, _nt=nontoken, _sc=self_counts, _sd=_sub_d, **_kw):
                if self_death and not _sc:
                    return                       # "another": no cuenta su propia muerte
                if _y and player is not None and player is not perm.controller:
                    return                       # "you control": solo tus criaturas
                if _th and (player is None or player is perm.controller):
                    return                       # "an opponent controls": solo las rivales
                if _nt and subject is not None and subject.is_token:
                    return                       # "nontoken": una ficha no cuenta
                if _sd != "creature" and (subject is None or not subject.has_subtype(_sd)):
                    return                       # "another Elemental you control dies"
                _prev_sj = getattr(game, "_trigger_subject", None)
                if subject is not None:
                    game._trigger_subject = subject      # "it" = la criatura que murió
                try:
                    _e(game, perm.controller)
                finally:
                    game._trigger_subject = _prev_sj
            cb_death.__defaults__ = cb_death.__defaults__
            out["death"] = cb_death

    # recursión: "when this creature dies, return it to the battlefield under its
    # owner's control" (criaturas que vuelven solas). La carta ya está en el
    # cementerio cuando resuelve el disparo -> la devolvemos al campo.
    if "death" not in out and re.search(
            r"when (?:this creature|~|it) dies, return it to the battlefield", t, re.I):
        def cb_death_return(game, perm, **_kw):
            card = perm.card
            ctrl = perm.controller
            if card in ctrl.graveyard:
                ctrl.graveyard.remove(card)
                game.move_to_battlefield(card, ctrl)
                game.log(f"{card.name} vuelve al campo tras morir")
        out["death"] = cb_death_return
    if "death" not in out and re.search(
            r"when (?:this creature|~|it) dies, return it to its owner's hand", t, re.I):
        def cb_death_hand(game, perm, **_kw):
            card = getattr(perm.card, "_real", None) or perm.card
            for pl in game.players:
                if card in pl.graveyard:
                    pl.graveyard.remove(card)
                    pl.hand.append(card)
                    game.log(f"{card.name} vuelve a la mano tras morir")
                    break
        out["death"] = cb_death_hand
    if "death" not in out and re.search(
            r"when (?:this creature|~|it) dies, it deals damage equal to its power to any target",
            t, re.I):
        def cb_death_power(game, perm, self_death=False, **_kw):
            if not self_death and perm in perm.controller.battlefield:
                return                  # el disparo "death" global: solo su PROPIA muerte
            n = max(0, perm.power)
            ctrl = perm.controller
            if n <= 0:
                return
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            kill = [pm for o in opps for pm in o.creatures()
                    if pm.toughness - pm.damage <= n and game.can_target(ctrl, pm)]
            cands = ([(f"{pm.name} {pm.power}/{pm.toughness}", pm)
                      for pm in sorted(kill, key=lambda x: x.power + x.toughness, reverse=True)]
                     + [(f"{o.name} ({o.life})", o) for o in sorted(opps, key=lambda o: o.life)])

            def _do(t, _n=n):
                game.deal_damage(perm, t, _n)
                game.sba()
            _human_target_choice(game, ctrl, "etb_target", f"{perm.name}: {n} de daño a…",
                                 cands, _do)
        out["death"] = cb_death_power
    # daño de combate a un jugador
    mcd = re.search(r"whenever [\w' ,]{0,40}? deals (?:combat )?damage to (?:a player|an opponent),?\s*"
                    r"(.{0,400})", t, re.I)
    if mcd:
        eff = _effect_any(mcd.group(1))
        if eff is not None:
            def cb_cd(game, perm, _e=eff, *_a, **_kw):
                _e(game, perm.controller, perm)
            out["combat_damage_to_player"] = cb_cd

    # disparo GLOBAL al atacar: "whenever a creature you control attacks, <efecto>"
    # (Hellrider: pega N al jugador/planeswalker atacado; otros: efecto genérico).
    mca = re.search(r"whenever an? (nontoken )?creature you control attacks,?\s*(.{0,400})",
                    t, re.I)
    if mca:
        _nt = bool(mca.group(1))
        _body = mca.group(2)
        mdmg = re.search(r"deals? (\w+) damage to (?:the player|that player|"
                         r"the player or planeswalker|it)", _body, re.I)
        if mdmg and (dn := _count_word(mdmg.group(1))):
            def cb_ca(game, perm, attacker=None, defender=None, _n=dn, _nt=_nt, **_kw):
                if _nt and getattr(attacker, "is_token", False):
                    return
                if defender is not None:
                    game.deal_damage(perm, defender, _n)
            out["creature_attacks"] = cb_ca
        else:
            _eff = _effect_any(_body)
            if _eff is not None:
                def cb_ca2(game, perm, attacker=None, defender=None, _e=_eff, _nt=_nt, **_kw):
                    if _nt and getattr(attacker, "is_token", False):
                        return
                    _e(game, perm.controller)
                out["creature_attacks"] = cb_ca2

    # auto-pump al atacar: "whenever this creature attacks, it gets +X/+Y until end
    # of turn[, where X is the number of ...]" (el bono puede ser fijo o variable).
    mas = re.search(r"whenever (?:this creature|~|it) attacks,? it gets "
                    r"([+-](?:\d+|x))/([+-](?:\d+|x)) until end of turn", t, re.I)
    if mas and "attacks" not in out:
        mx = re.search(r"where x is the (number of [\w' ]+?)(?:\.|,|$)", t, re.I)
        _cntf = _count_fn(mx.group(1)) if mx else None

        def _amt(tok, game, ctrl, _c=_cntf):
            sign = -1 if tok[0] == "-" else 1
            body = tok[1:]
            if body.lower() == "x":
                return sign * (_c(game, ctrl) if _c else 0)
            return sign * int(body)

        def cb_atk_self(game, perm, _dp=mas.group(1), _dt=mas.group(2), **_kw):
            ctrl = perm.controller
            perm.temp_pt[0] += _amt(_dp, game, ctrl)
            perm.temp_pt[1] += _amt(_dt, game, ctrl)
        out["attacks"] = cb_atk_self

    # landfall: "whenever a land enters (the battlefield) under your control, …" /
    # "Landfall — …". El evento landfall es self-scoped (solo tus tierras).
    ml = re.search(r"(?:landfall\s*[—–-]\s*|whenever a land (?:you control )?enters"
                   r"(?: the battlefield)?(?: under your control)?,?\s*)(.{0,400})",
                   t, re.I)
    if ml and re.search(r"return (?:this card|~|it|this creature|[a-z][\w' ,]+?) from your "
                        r"graveyard to the battlefield", ml.group(1), re.I) \
            and not re.search(r"return target", ml.group(1), re.I):
        ml = None      # disparo DESDE EL CEMENTERIO de la propia carta: _parse_gy_triggers
    if ml:
        body_lf = ml.group(1)
        # "put N +1/+1 counter(s) on this/~/<su nombre>" (Vinelasher Kudzu): el
        # contador va a la PROPIA criatura, no al controlador (ni a un objetivo).
        # El lookahead evita confundirlo con "... on target/each/another creature".
        msc = re.search(r"put (\w+) \+1/\+1 counters? on "
                        r"(?!target|each|another|a |an |up to|that )"
                        r"(?:this creature|this|it|~|[a-z][\w' ,]+)", body_lf, re.I)
        if msc and (n_lf := _count_word(msc.group(1))):
            def cb_lf(game, perm, _n=n_lf, **_kw):
                game.add_counters(perm, "+1/+1", _n)
            out["landfall"] = cb_lf
        else:
            eff = _effect_any(body_lf)
            if eff is not None:
                def cb_lf(game, perm, _e=eff, **_kw):
                    _e(game, perm.controller)
                out["landfall"] = cb_lf

    # Laelia: "whenever one or more cards are put into exile from your library
    # and/or your graveyard, put N +1/+1 counter(s) on ~" -> contador a sí misma.
    mex = re.search(r"whenever one or more cards? (?:are|is) put into exile from "
                    r"your (?:library|graveyard)[^,]*,\s*put (\w+) \+1/\+1 counters? on",
                    t, re.I)
    if mex and (nex := _count_word(mex.group(1))) and "cards_exiled" not in out:
        def cb_exiled(game, perm, _n=nex, **_kw):
            game.add_counters(perm, "+1/+1", _n)
        out["cards_exiled"] = cb_exiled

    # inicio de combate: "at the beginning of combat on your turn, …"
    mbc = re.search(r"at the beginning of combat on your turn,?\s*(.{0,400})", t, re.I)
    if mbc:
        eff = _effect_any(mbc.group(1))
        if eff is not None:
            def cb_bc(game, perm, _e=eff, **_kw):
                prev = getattr(game, "_trigger_source", None)
                game._trigger_source = perm      # 'equipped creature' / '~' (copias)
                try:
                    _e(game, perm.controller)
                finally:
                    game._trigger_source = prev
            out["begin_combat"] = cb_bc

    # robo: "whenever you draw a/your first/second card, …" (self-scoped)
    mdr = re.search(r"whenever you draw (a|your (?:first|second|third|fourth|fifth)) "
                    r"card(?: each turn)?,?\s*(.{0,400})", t, re.I)
    if mdr:
        eff = _effect_any(_ability_clause(mdr.group(2)))
        nth = {"your first": 1, "your second": 2, "your third": 3, "your fourth": 4,
               "your fifth": 5}.get(mdr.group(1).lower())
        if eff is not None:
            # "your second card each turn" (Alandra): solo en ESE robo del turno
            def cb_dr(game, perm, _e=eff, _n=nth, count=None, **_kw):
                if _n is not None and count is not None and count != _n:
                    return
                _e(game, perm.controller)
            out["draw"] = cb_dr

    # "whenever an opponent casts a spell, <efecto>" (evento opp_cast sin scope; el
    # callback sólo actúa si el que lanzó es rival del permanente que observa).
    moc = None
    for _oln in _ability_lines(oracle):          # por línea, con el cuerpo completo
        moc = re.search(r"whenever an opponent casts (?:a |an |another |their first )?"
                        r"([\w' ]*?) ?spells?(?: each turn)?,?\s*(.*)$", re.sub(r"\s+", " ", _oln).strip(), re.I)
        if moc:
            break
    _ofilt = _spell_filter(moc.group(1)) if moc else None
    if moc and _ofilt is not None:
        effo = _effect_any(_ability_clause(moc.group(2)))
        if effo is not None:
            # filtra por el TIPO del hechizo del rival (Mystic Remora: no-criatura)
            def cboc(game, perm, caster=None, card=None, _f=_ofilt, **_kw):
                if caster is not None and caster is not perm.controller \
                        and (card is None or _f(card)):
                    effo(game, perm.controller)
            out["opp_cast"] = cboc

    # "whenever an opponent draws a card, <efecto>" (Smothering Tithe…). En la
    # simulación los bots no pagan el impuesto -> el controlador recibe el efecto
    # (p. ej. crea un Tesoro). Evento opp_draw sin scope; el callback filtra.
    mod = re.search(r"whenever an opponent draws (?:a|their first) card,?\s*(.{0,400})",
                    t, re.I)
    if mod:
        effd = _effect_any(mod.group(1))
        if effd is not None:
            def cbod(game, perm, drawer=None, _e=effd, **_kw):
                if drawer is not None and drawer is not perm.controller:
                    _e(game, perm.controller)
            out["opp_draw"] = cbod

    # "whenever you create one or more (creature) tokens, <efecto>" (Staff of the
    # Storyteller: pon un contador 'story' en este artefacto; y similares).
    mtok = re.search(r"whenever you create one or more (?:creature )?tokens?,?\s*"
                     r"(.{0,400})", t, re.I)
    if mtok and "token_created" not in out:
        body = mtok.group(1)
        mcnt = re.search(r"put (a|an|one|\w+) ([a-z]+) counters? on "
                         r"(?:this|~|itself|it)\b", body, re.I)
        if mcnt and _count_word(mcnt.group(1)):
            _cn = _count_word(mcnt.group(1))
            _ck = mcnt.group(2).lower()

            def cbt(game, perm, _n=_cn, _k=_ck, **_kw):
                perm.counters[_k] = perm.counters.get(_k, 0) + _n
                game.log(f"{perm.name} recibe {_n} contador(es) {_k}")
            out["token_created"] = cbt
        else:
            efft = _effect_any(body)
            if efft is not None:
                def cbt2(game, perm, _e=efft, **_kw):
                    _e(game, perm.controller)
                out["token_created"] = cbt2

    # "whenever you gain life, <efecto>" (soul sisters, Ajani's Pridemate, Heliod…).
    if "gain_life" not in out:
        mg = re.search(r"whenever you gain life(?: for the first time (?:each|during each of your)"
                       r" turns?)?,?\s*(.{0,400})", t, re.I)
        if mg:
            # recortar en el límite de la siguiente habilidad: evita que el cuerpo
            # se 'coma' una {T}: ... posterior y haga bucles (Niv-Mizzet, Ghost Counsel).
            body = _ability_clause(mg.group(1))
            # caso muy común: "put a/one +1/+1 counter on ~" sobre el propio permanente
            mcnt = re.search(r"put (a|an|one|\w+) \+1/\+1 counters? on", body, re.I)
            # Niv-Mizzet, Ghost Counsel: "you may pay that much life. if you do, draw
            # that many cards." -> paga la vida GANADA y roba esa cantidad (usa amount).
            if re.search(r"pay that much life", body, re.I) and \
                    re.search(r"draw that many cards", body, re.I):
                def cbg(game, perm, amount=0, **_kw):
                    n = max(0, int(amount or 0))
                    ctrl = perm.controller
                    if n <= 0 or ctrl.life - n < 10:   # no suicidarse por cartas
                        return
                    ctrl.life -= n
                    ctrl.draw(n, game)
                    game.log(f"{ctrl.name} paga {n} vida y roba {n} ({perm.name})")
                out["gain_life"] = cbg
            elif mcnt:
                cn = _count_word(mcnt.group(1)) or 1

                def cbg(game, perm, _n=cn, **_kw):
                    game.add_counters(perm, "+1/+1", _n)
                out["gain_life"] = cbg
            else:
                effg = _effect_any(body)
                if effg is not None:
                    def cbg(game, perm, _e=effg, **_kw):
                        _e(game, perm.controller)
                    out["gain_life"] = cbg

    # "whenever you cast a(n) <tipo> spell, <efecto>" (magecraft, Young Pyromancer,
    # Talrand, disparos de fichas al lanzar criaturas, etc.). Filtra por el TIPO
    # de hechizo declarado; "your first ... each turn" se aproxima sin el límite.
    mc = None
    for _ln in _ability_lines(oracle):
        mc = re.search(r"whenever you cast (?:or copy )?(?:your first |an? )"
                       r"([\w ]*?) ?spells?(?: from your hand)?(?: each turn)?,?\s*(.{0,400})",
                       _ln, re.I)
        mmv2 = re.search(r"whenever you cast an? ((?:[a-z]+ )?spell with mana value \d+ or "
                         r"(?:greater|less)),\s*(.{0,400})", _ln, re.I)
        if mmv2:
            mc = mmv2
        if mc:
            break
    _cfilt = _spell_filter(mc.group(1)) if mc else None
    if mc and _cfilt is not None and "cast" not in out:
        # disparo MODAL ("... , choose one — ..."): el modal se parsea del oráculo
        # COMPLETO (la captura del disparo se trunca a 160 y perdería modos).
        modal_run = (_modal_trigger_runner(t)
                     if re.search(r"\bchoose (one|two|three|one or more|one or both)\b",
                                  mc.group(2), re.I) else None)
        eff = None if modal_run is not None else _effect_any(mc.group(2))
        if eff is not None or modal_run is not None:
            def cbc(game, perm, card=None, _e=eff, _m=modal_run, _f=_cfilt, **_kw):
                if card is None or not _f(card):
                    return
                if _m is not None:
                    _m(game, perm)                       # modal: abre UI / auto-elige
                else:
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
    # por LÍNEA (habilidad): antes se buscaba en todo el texto y "you control" /
    # "another" se calculaban sobre el oráculo entero
    me = None
    for _ln in _ability_lines(oracle):
        me = re.search(r"whenever (?:(?:this creature|~) or )?(?:one or more|a|an|another) (?:nontoken )?creatures?"
                       r"(?: you control)?(?: with mana value (\d+) or less)?"
                       r"[^,]*?enters?(?: the battlefield)?[^,]*,\s*(.{0,400})", _ln, re.I)
        if me:
            break
    if me and "creature_enters" not in out and re.search(
            r"causes an? (?:triggered )?abilit", me.group(0), re.I):
        # Aboleth Spawn / Elesh Norn-like: "whenever a creature entering under an
        # opponent's control causes a triggered ability of that creature to trigger,
        # you may copy that ability" -> copia el disparo de ENTRADA de esa criatura
        # (si no tiene, no hay nada que copiar). Antes copiaba la última habilidad
        # resuelta en cada entrada: bucle de fichas.
        _opp_only = "opponent" in me.group(0).lower()

        def cb_copy_etb(game, watcher, entered=None, _o=_opp_only, **_kw):
            if entered is None or entered.card.on_etb is None:
                return
            if _o and entered.controller is watcher.controller:
                return
            game.note_ability(watcher.card, "copia un disparo de entrada",
                              controller=watcher.controller)
            game.log(f"{watcher.controller.name} copia el disparo de entrada de "
                     f"{entered.name}")
            game._run_fx(f"copy etb {entered.name}",
                         lambda: entered.card.on_etb(game, watcher.controller, entered))
        out["creature_enters"] = cb_copy_etb
        me = None
    if me and "creature_enters" not in out:
        lim = int(me.group(1)) if me.group(1) else None
        eff = _effect_any(me.group(2))
        if eff is None:
            eff = (lambda g, ctrl, *_a, _l=_short_label(me.group(2)):
                   g.log(f"{ctrl.name}: {_l}"))
        head = me.group(0)[:me.start(2) - me.start(0)].lower()
        yours = "you control" in head or "under your control" in head
        opp = bool(re.search(r"(?:an opponent|your opponents?) controls?", head))
        another = "another" in head and not re.search(r"(?:this creature|~) or another", head)
        nontoken = "nontoken" in head
        once = "only once each turn" in t.lower()
        # "… creature … WITH <keyword> / with power N or greater enters": filtro. Antes
        # se ignoraba y Wingmantle Chaplain ("another creature with defender") creaba
        # un Pájaro por cada Pájaro que entraba (bucle hasta el tope de fichas).
        with_kw = with_pow = None
        _mw = re.search(r"\bwith ([a-z ]+?)(?: you control)?(?: enters|,|$)", head)
        if _mw and not re.match(r"mana value", _mw.group(1)):
            _q = _mw.group(1).strip()
            _mp = re.match(r"power (\d+) or greater", _q)
            if _mp:
                with_pow = int(_mp.group(1))
            elif _q.replace(" ", "_") in KEYWORDS:
                with_kw = _q.replace(" ", "_")
            else:
                with_kw = "__unknown__"      # calificador no modelado: no dispara

        def cb(game, watcher, entered=None, _e=eff, _lim=lim,
               _yours=yours, _opp=opp, _another=another, _once=once, _nt=nontoken,
               _wk=with_kw, _wp=with_pow):
            if entered is None:
                return
            if _wk is not None and not entered.has(_wk):
                return
            if _wp is not None and entered.power < _wp:
                return
            if _yours and entered.controller is not watcher.controller:
                return
            if _opp and entered.controller is watcher.controller:
                return
            if _another and entered is watcher:
                return
            if _nt and entered.is_token:
                return
            if _lim is not None and _cmc(entered) > _lim:
                return
            if _once and getattr(watcher, "_ce_turn", None) == game.turn:
                return
            watcher._ce_turn = game.turn
            prev = (getattr(game, "_trigger_subject", None),
                    getattr(game, "_trigger_source", None))
            game._trigger_subject, game._trigger_source = entered, watcher
            try:
                _e(game, watcher.controller)      # 'that creature' = la que entró
            finally:
                game._trigger_subject, game._trigger_source = prev
        out["creature_enters"] = cb
    return out


def _misc_trigger_effects(oracle: str, name: str = ""):
    """Disparos de palabras de habilidad y eventos propios: entra un permanente
    de un tipo (constellation, eerie, rally, 'another Elf enters'), enrage, inspired,
    heroic, valiant, battalion, pack tactics, survival y flurry."""
    out = {}
    names = _self_names(name)
    me_re = r"(?:~|this creature|" + "|".join(re.escape(n) for n in names if n) + r")"

    def _eff(body):
        return _effect_any(body.strip())

    for ln in _ability_lines(oracle):
        l = ln.strip()
        # --- entra un permanente de un tipo / subtipo
        m = re.match(r"(?i)when(?:ever)? (?:(this creature|~|" + "|".join(re.escape(n) for n in names if n)
                     + r") or )?(a|an|another|one or more) (nontoken )?(artifact|enchantment|"
                     r"land|planeswalker|permanent|battle|token|[A-Z][a-z]+)(?: creature)?s?"
                     r"( you control)?(?: and whenever [^,]+?)?"
                     r" enters?(?: the battlefield)?( under your control)?,\s*(.+)$", l)
        if m and m.group(4).lower() not in ("creature", "land", "creatures") \
                and "perm_enters" not in out:
            kind = m.group(4)
            eff = _eff(m.group(7))
            if eff is not None:
                incl_self = bool(m.group(1))
                another = m.group(2).lower() == "another"
                yours = bool(m.group(5) or m.group(6))
                nontoken = bool(m.group(3))
                kl = kind.lower()
                is_type = kl in ("artifact", "enchantment", "land", "planeswalker",
                                 "permanent", "battle", "token")
                once = bool(re.search(r"only once each turn|this ability only once each turn",
                                      oracle or "", re.I))

                def cb_pe(game, watcher, entered=None, _e=eff, _k=kl, _t=is_type,
                          _a=another, _y=yours, _nt=nontoken, _s=incl_self, _o=once, **_kw):
                    if entered is None:
                        return
                    if _o and getattr(watcher, "_pe_turn", None) == game.turn:
                        return
                    if entered is watcher and not _s:
                        if _a or not _t or _k != "permanent":
                            return
                    if _y and entered.controller is not watcher.controller:
                        return
                    if _nt and entered.is_token:
                        return
                    if _t:
                        if _k == "token":
                            if not entered.is_token:
                                return
                        elif _k != "permanent" and _k not in entered.card.types:
                            return
                    elif not entered.has_subtype(_k) and entered is not watcher:
                        return
                    if _o:
                        watcher._pe_turn = game.turn
                    prev = (getattr(game, "_trigger_subject", None),
                            getattr(game, "_trigger_source", None))
                    game._trigger_subject, game._trigger_source = entered, watcher
                    try:
                        _e(game, watcher.controller, watcher)
                    finally:
                        game._trigger_subject, game._trigger_source = prev
                out["perm_enters"] = cb_pe
            continue
        me_any = r"(?:" + me_re[3:-1] + r"|this enchantment|this aura|this artifact|this " \
            r"permanent|this land|this vehicle|this equipment)"
        simple = [
            ("self_to_gy", r"when(?:ever)? " + me_any + r" (?:enters or dies|is put into a "
             r"graveyard from the battlefield|dies or is put into exile from the "
             r"battlefield),\s*(.+)$"),
            ("becomes_tapped", r"whenever " + me_re + r" becomes tapped,\s*(.+)$"),
            ("group_combat_damage", r"whenever one or more (?:[a-z]+ )?creatures you control "
             r"deal combat damage to a player,\s*(.+)$"),
            ("__leave", r"when(?:ever)? " + me_re + r" leaves the battlefield,\s*(.+)$"),
            ("dealt_damage", r"whenever " + me_re + r" is dealt damage,\s*(.+)$"),
            ("untapped", r"whenever " + me_re + r" becomes untapped,\s*(.+)$"),
            ("targeted_by_spell", r"whenever you cast a spell that targets " + me_re + r",\s*(.+)$"),
            ("targeted_first", r"whenever " + me_re + r" becomes the target of a spell or "
             r"ability you control for the first time each turn,\s*(.+)$"),
            ("battalion", r"whenever " + me_re + r" and at least two other creatures attack,"
             r"\s*(.+)$"),
            ("pack_tactics", r"whenever " + me_re + r" attacks, if you attacked with creatures "
             r"with total power 6 or greater this combat,\s*(.+)$"),
            ("main2", r"at the beginning of (?:your second main phase|your postcombat main phase|each of "
             r"your postcombat main phases), (?:if " + me_re + r" is tapped, )?(.+)$"),
            ("scry", r"whenever you scry,\s*(.+)$"),
            ("you_attack", r"whenever you attack,\s*(.+)$"),
            ("each_combat", r"at the beginning of each combat,\s*(.+)$"),
            ("main1", r"at the beginning of (?:your )?(?:first|precombat) main phase,\s*(.+)$"),
            ("discarded", r"whenever you (?:cycle or )?discard (?:a|one or more) cards?"
             r"(?: for the first time each turn)?,\s*(.+)$"),
            ("crime", r"whenever you commit a crime,\s*(.+)$"),
            ("curse_upkeep", r"at the beginning of the upkeep of enchanted (?:creature's|permanent's) "
             r"controller,\s*(.+)$"),
            ("opp_discarded", r"whenever an opponent discards a card,\s*(.+)$"),
            ("any_cast", r"whenever a player casts a spell,\s*(.+)$"),
            ("enchanted_dies", r"when(?:ever)? enchanted creature dies,\s*(.+)$"),
            ("combat_damage_creature", r"whenever " + me_re + r" deals combat damage to a "
             r"creature,\s*(.+)$"),
            ("leaves_graveyard", r"whenever one or more (?:other )?cards leave your graveyard,"
             r"\s*(.+)$"),
            ("ring_tempts", r"whenever the ring tempts you,\s*(.+)$"),
            ("surveil", r"whenever you surveil,\s*(.+)$"),
            ("blocks_or_blocked", r"whenever " + me_re + r" blocks or becomes blocked"
             r"(?: by a creature)?,\s*(.+)$"),
            ("blocks", r"whenever " + me_re + r" blocks(?: a creature)?(?: with flying)?,\s*(.+)$"),
            ("becomes_blocked", r"whenever " + me_re + r" becomes blocked(?: by a creature)?,"
             r"\s*(.+)$"),
        ]
        for key, pat in simple:
            mm = re.match("(?i)" + pat, l)
            if not mm or key in out:
                continue
            _body = mm.group(1)
            if key not in ("perm_enters", "group_combat_damage", "main2", "__leave", "self_to_gy"):
                # disparo sobre la PROPIA criatura: "it" es ella misma
                _body = re.sub(r"(?i)^it (gets|gains|deals|has)\b", r"this creature \1", _body)
            eff = _eff(_body)
            if eff is None:
                continue
            need_tapped = key == "main2" and " is tapped," in l.lower()

            _own = key in ("leaves_graveyard",)
            _fly = key == "blocks" and "with flying" in l.lower()
            _once = bool(re.search(r"(?:triggers only once each turn|for the first time each "
                                   r"turn)", l, re.I))

            def cb_s(game, perm, _e=eff, _nt=need_tapped, _ow=_own, _o1=_once, _k=key, _fl=_fly,
                     **_kw):
                if _nt and not perm.tapped:
                    return
                if _fl and not (_kw.get("subject") is not None and _kw["subject"].has("flying")):
                    return
                if _ow and _kw.get("player") is not perm.controller:
                    return
                if _k == "curse_upkeep":
                    host = getattr(perm, "enchanting", None)
                    if host is None or _kw.get("active") is not host.controller:
                        return
                if _k == "opp_discarded" and (_kw.get("player") is None
                                              or _kw.get("player") is perm.controller):
                    return
                if _o1:
                    if getattr(perm, "_once_turn", {}).get(_k) == game.turn:
                        return
                    if not hasattr(perm, "_once_turn"):
                        perm._once_turn = {}
                    perm._once_turn[_k] = game.turn
                _e(game, perm.controller, perm)
            out[key] = cb_s
        if "curse_upkeep" in out:                    # se dispara con el evento each_upkeep
            _cu = out.pop("curse_upkeep")
            _pv = out.get("each_upkeep")
            out["each_upkeep"] = ((lambda g, perm, _a=_cu, _b=_pv, **kw: (_b(g, perm, **kw),
                                                                          _a(g, perm, **kw)))
                                  if _pv else _cu)
        if "blocks_or_blocked" in out:
            _bb = out.pop("blocks_or_blocked")
            out.setdefault("blocks", _bb)
            out.setdefault("becomes_blocked", _bb)
        # "whenever you sacrifice (another) <tipo>, <efecto>"
        msac = re.match(r"(?i)whenever you sacrifice (another |one or more )?(?:an? )?([a-z]+?)s?"
                        r"(?: or (?:an? )?([a-z]+?)s?)?,\s*(.+)$", l)
        if msac and "sacrificed" not in out:
            eff = _eff(re.sub(r"(?i)^it (gets|gains)\b", r"this creature \1", msac.group(4)))
            if eff is not None:
                kinds = {k.lower() for k in (msac.group(2), msac.group(3)) if k}
                another = bool(msac.group(1)) and "another" in msac.group(1).lower()

                def cb_sac(game, perm, player=None, subject=None, _e=eff, _k=kinds,
                           _an=another, **_kw):
                    if player is not perm.controller or subject is None:
                        return
                    if _an and subject is perm:
                        return
                    if "permanent" not in _k and not any(
                            (k == "creature" and subject.card.is_creature()) or
                            k in subject.card.types or subject.has_subtype(k) for k in _k):
                        return
                    _e(game, perm.controller, perm)
                out["sacrificed"] = cb_sac
        # "whenever another creature you control leaves the battlefield, ..."
        mlv = re.match(r"(?i)whenever (?:a|another) (nontoken )?creature you control leaves the "
                       r"battlefield,\s*(.+)$", l)
        if mlv and "other_leaves" not in out:
            eff = _eff(mlv.group(2))
            if eff is not None:
                def cb_lv(game, perm, subject=None, _e=eff, _nt=bool(mlv.group(1)), **_kw):
                    if subject is None or subject is perm or subject.controller is not perm.controller \
                            or not subject.card.is_creature() or (_nt and subject.is_token):
                        return
                    _e(game, perm.controller, perm)
                out["other_leaves"] = cb_lv
        # ── batch 15: disparos EXTRA por evento ("__x_<evento>") con filtro ──
        _xs = []                                   # (evento, filtro(game, perm, kw), cuerpo)
        _ll = l.lower()
        mx = re.match(r"whenever (a player|an opponent|you) casts? (?:a|an) ([a-z ,]+?) spell,\s*(.+)$", _ll)
        if mx and mx.group(2) not in ("", "creature or planeswalker"):
            _who = mx.group(1)
            _sf = (lambda c: bool(getattr(c, "_kicked", False))) if mx.group(2) == "kicked" \
                else _spell_filter(mx.group(2))
            if _sf is not None and not (_who == "you" and mx.group(2) != "kicked"):
                def _f_cast(g, pm, kw, _sf=_sf, _w=_who):
                    c, who = kw.get("card"), kw.get("caster")
                    if c is None or not _sf(c):
                        return False
                    if _w == "an opponent" and who is pm.controller:
                        return False
                    if _w == "you" and who is not pm.controller:
                        return False
                    return True
                _xs.append(("any_cast", _f_cast, mx.group(3)))
        if _ll.startswith("whenever you cast a spell from your hand, reveal the top x cards of your library, where x "
                          "is that spell's mana value"):
            def _sunbird(game, perm, card=None, **kw):
                if card is None or getattr(game, "_sunbird_on", False) or card.cost is None:
                    return
                if not getattr(card, "_cast_from_hand", True):
                    return
                ctrl = perm.controller
                x = card.cost.cmc
                rev = [ctrl.library.pop() for _ in range(min(x, len(ctrl.library)))]
                pick = [c for c in rev if not c.is_land() and c.cost is not None and c.cost.cmc <= x]
                pick.sort(key=lambda c: -c.cost.cmc)
                game._sunbird_on = True
                try:
                    for c in pick:
                        rev.remove(c)
                        orig = c.cost
                        c.cost = Cost(generic=0, pips=())
                        ctrl.hand.append(c)
                        try:
                            ok = game.cast(ctrl, c)
                        finally:
                            c.cost = orig
                        if ok:
                            break
                        if c in ctrl.hand:
                            ctrl.hand.remove(c)
                        rev.append(c)
                finally:
                    game._sunbird_on = False
                game.rng.shuffle(rev)
                ctrl.library[:0] = rev
            out["__x_cast"] = _sunbird
        mx = re.match(r"whenever a player draws a card,\s*(.+)$", _ll)
        if mx:
            _xs.append(("draw", lambda g, pm, kw: True, mx.group(1)))
            _xs.append(("opp_draw", lambda g, pm, kw: True, mx.group(1)))
        mx = re.match(r"whenever one or more creatures attack,\s*(.+)$", _ll)
        if mx:
            _xs.append(("you_attack", lambda g, pm, kw: True, mx.group(1)))
        mx = re.match(r"whenever another (nontoken )?creature leaves the battlefield,\s*(.+)$", _ll)
        if mx:
            _xs.append(("other_leaves", (lambda g, pm, kw, _nt=bool(mx.group(1)):
                                         kw.get("subject") is not None and kw["subject"] is not pm
                                         and kw["subject"].card.is_creature()
                                         and not (_nt and kw["subject"].is_token)), mx.group(2)))
        mx = re.match(r"whenever a player sacrifices (another )?(?:a )?(permanent|creature|artifact),\s*(.+)$", _ll)
        if mx:
            _xs.append(("sacrificed", (lambda g, pm, kw, _a=bool(mx.group(1)), _k=mx.group(2):
                                       kw.get("subject") is not None and not (_a and kw["subject"] is pm)
                                       and (_k == "permanent" or (_k == "creature" and kw["subject"].is_creature())
                                            or _k in kw["subject"].card.types)), mx.group(3)))
        mx = re.match(r"whenever an opponent casts their (second|first) spell each turn,\s*(.+)$", _ll)
        if mx:
            _xs.append(("any_cast", (lambda g, pm, kw, _n=2 if mx.group(1) == "second" else 1:
                                     kw.get("caster") is not None and kw["caster"] is not pm.controller
                                     and getattr(kw["caster"], "spells_cast_turn", 0) == _n), mx.group(2)))
        mx = re.match(r"whenever (you|a player) cycles? (?:or discards? )?(?:a|another) cards?,\s*(.+)$", _ll)
        if mx:
            _xs.append(("cycled", (lambda g, pm, kw, _y=mx.group(1) == "you":
                                   not _y or kw.get("player") is pm.controller), mx.group(2)))
        mx = re.match(r"whenever " + me_re.lower() + r" deals damage to (an opponent|a player|a creature),\s*(.+)$", _ll)
        if mx:
            def _f_dmg(g, pm, kw, _k=mx.group(1)):
                if kw.get("source") is not pm:
                    return False
                t = kw.get("target")
                if _k == "a creature":
                    return hasattr(t, "card")
                if not hasattr(t, "life"):
                    return False
                return _k == "a player" or t is not pm.controller
            _xs.append(("damage", _f_dmg, mx.group(2)))
        mx = re.match(r"whenever a source you control deals (noncombat )?damage to an opponent,\s*(.+)$", _ll)
        if mx:
            def _f_src(g, pm, kw, _nc=bool(mx.group(1))):
                src, t = kw.get("source"), kw.get("target")
                return (getattr(src, "controller", None) is pm.controller and hasattr(t, "life")
                        and t is not pm.controller and not (_nc and kw.get("combat")))
            _xs.append(("damage", _f_src, mx.group(2)))
        mx = re.match(r"whenever a source deals damage to " + me_re.lower() + r",\s*(.+)$", _ll)
        if mx:
            _xs.append(("damage", lambda g, pm, kw: kw.get("target") is pm, mx.group(1)))
        mx = (re.match(r"whenever you attack with (\w+) or more creatures,\s*(.+)$", _ll)
              or re.match(r"whenever (\w+) or more creatures you control attack,\s*(.+)$", _ll))
        if mx and _count_word(mx.group(1)):
            _xs.append(("you_attack", (lambda g, pm, kw, _n=_count_word(mx.group(1)):
                                       sum(1 for c in pm.controller.creatures()
                                           if c.attacking is not None) >= _n), mx.group(2)))
        mx = re.match(r"whenever (?:a|an) (land|creature|artifact|enchantment|planeswalker|nonland permanent|"
                      r"permanent) an opponent controls enters(?: the battlefield)?,\s*(.+)$", _ll)
        if mx:
            def _f_oetb(g, pm, kw, _k=mx.group(1)):
                sj = kw.get("subject")
                if sj is None or sj.controller is pm.controller:
                    return False
                if _k == "creature":
                    return sj.is_creature()
                if _k == "nonland permanent":
                    return not sj.card.is_land()
                return _k == "permanent" or _k in sj.card.types
            _xs.append(("etb", _f_oetb, mx.group(2)))
        mx = re.match(r"whenever (?:a|an) (artifact|creature|enchantment|land|nontoken creature)( an opponent "
                      r"controls| you control)? is put into a graveyard from the battlefield,\s*(.+)$", _ll)
        if mx:
            def _f_togy(g, pm, kw, _k=mx.group(1), _w=(mx.group(2) or "").strip()):
                sj = kw.get("subject")
                if sj is None or sj.is_token:
                    return False
                if _w == "an opponent controls" and sj.controller is pm.controller:
                    return False
                if _w == "you control" and sj.controller is not pm.controller:
                    return False
                if "creature" in _k and not sj.card.is_creature():
                    return False
                if "creature" not in _k and _k not in sj.card.types:
                    return False
                real = getattr(sj.card, "_real", None) or sj.card
                return any(real in p_.graveyard for p_ in g.players)
            _xs.append(("other_leaves", _f_togy, mx.group(3)))
        # ── batch 21: cabezas nuevas con filtro ──
        mx = re.match(r"whenever (another |a |an )((?:[a-z]+ )?(?:creature|artifact|planeswalker|token|enchantment)"
                      r"(?: or (?:an? )?(?:creature|artifact|planeswalker|enchantment))?|creature token)"
                      r"( you control| an opponent controls| your opponents control)? dies( during your turn)?,\s*(.+)$", _ll)
        if mx and not mx.group(2).startswith("nontoken") and (" or " in mx.group(2) or "token" in mx.group(2)
                                                              or mx.group(4) or len(mx.group(2).split()) == 2) and (_kp21 := _kind_pred21(mx.group(2).replace("creature token", "token")
                                                                             if mx.group(2) != "creature token" else "token")):
            def _f_d21(g, pm, kw, _p=_kp21, _a=mx.group(1).strip() == "another", _s=(mx.group(3) or "").strip(),
                       _t=bool(mx.group(4))):
                sj = kw.get("subject")
                if sj is None or (_a and sj is pm) or not _p(sj):
                    return False
                if _s == "you control" and sj.controller is not pm.controller:
                    return False
                if _s and _s != "you control" and sj.controller is pm.controller:
                    return False
                if _t and g.players[g.active_index] is not pm.controller:
                    return False
                return True
            _xs.append(("death", _f_d21, mx.group(5)))
        mx = re.match(r"whenever a (nontoken creature|creature|token|nonland permanent|permanent) you control leaves the "
                      r"battlefield,\s*(.+)$", _ll)
        if mx and mx.group(1) in ("token", "nonland permanent", "permanent"):
            _xs.append(("other_leaves", (lambda g, pm, kw, _k=mx.group(1): (
                kw.get("subject") is not None and kw["subject"] is not pm and kw["subject"].controller is pm.controller
                and (kw["subject"].is_token if _k == "token" else
                     (not kw["subject"].card.is_land()) if _k == "nonland permanent" else True))), mx.group(2)))
        mx = re.match(r"whenever (?:a|an) (land|creature|artifact|instant or sorcery|nonland|) ?card is put into (your|an "
                      r"opponent's) graveyard from anywhere,\s*(.+)$", _ll)
        if mx:
            def _f_gy21(g, pm, kw, _k=mx.group(1), _w=mx.group(2)):
                c, pl = kw.get("card"), kw.get("player")
                if c is None or pl is None or (_w == "your") != (pl is pm.controller):
                    return False
                if not _k:
                    return True
                if _k == "nonland":
                    return not c.is_land()
                if _k == "instant or sorcery":
                    return bool({"instant", "sorcery"} & c.types)
                return c.is_creature() if _k == "creature" else _k in c.types
            _xs.append(("to_graveyard", _f_gy21, mx.group(3)))
        mx = re.match(r"whenever (an opponent|a player) plays a land,\s*(.+)$", _ll)
        if mx:
            _xs.append(("etb", (lambda g, pm, kw, _o=mx.group(1) == "an opponent": (
                kw.get("subject") is not None and kw["subject"].card.is_land()
                and (not _o or kw["subject"].controller is not pm.controller))), mx.group(2)))
        mx = re.match(r"whenever you cast (?:a|an|your first) ?(?:([a-z ]+?) )?spell (during an opponent's turn|during each "
                      r"opponent's turn|other than your first spell each turn),\s*(.+)$", _ll)
        if mx:
            _sf21 = _spell_filter(mx.group(1)) if mx.group(1) else None

            def _f_ct21(g, pm, kw, _w=mx.group(2), _sf=_sf21, _first="your first" in _ll):
                c = kw.get("card")
                if kw.get("player") is not pm.controller or c is None or (_sf is not None and not _sf(c)):
                    return False
                if "opponent's turn" in _w:
                    if g.players[g.active_index] is pm.controller:
                        return False
                    return not _first or getattr(pm.controller, "spells_cast_turn", 0) == 1
                return getattr(pm.controller, "spells_cast_turn", 0) >= 2
            _xs.append(("cast", _f_ct21, mx.group(3)))
        mx = re.match(r"whenever an opponent sacrifices (?:a|an) (creature|permanent|artifact),\s*(.+)$", _ll)
        if mx:
            _xs.append(("sacrificed", (lambda g, pm, kw, _k=mx.group(1): (
                kw.get("player") is not None and kw["player"] is not pm.controller and kw.get("subject") is not None
                and (_k == "permanent" or (kw["subject"].is_creature() if _k == "creature" else
                                           _k in kw["subject"].card.types)))), mx.group(2)))
        mx = re.match(r"whenever an opponent is dealt (noncombat |combat |)damage,\s*(.+)$", _ll)
        if mx:
            _xs.append(("damage", (lambda g, pm, kw, _k=mx.group(1).strip(): (
                hasattr(kw.get("target"), "life") and kw["target"] is not pm.controller and (kw.get("amount") or 0) > 0
                and (not _k or (_k == "combat") == bool(kw.get("combat"))))), mx.group(2)))
        mx = re.match(r"whenever (?:a|another) creature you control is dealt damage,\s*(.+)$", _ll)
        if mx:
            _xs.append(("damage", (lambda g, pm, kw: (
                hasattr(kw.get("target"), "card") and kw["target"].controller is pm.controller
                and kw["target"].is_creature() and (kw.get("amount") or 0) > 0)), mx.group(1)))
        mx = re.match(r"whenever a creature dealt damage by " + me_re.lower() + r" this turn dies,\s*(.+)$", _ll)
        if mx:
            def _f_dby(g, pm, kw):
                sj = kw.get("subject")
                return (sj is not None and getattr(sj, "_dmg_by_turn", None) == g.turn
                        and id(pm) in getattr(sj, "_dmg_by", ()))
            _xs.append(("death", _f_dby, mx.group(1)))
        for _ev, _flt, _bd in _xs:
            _bd = re.sub(r"(?i)^it (gets|gains|deals|has)\b", r"this creature \1", _bd)
            _e = _eff(_bd)
            if _e is None:
                continue

            def cb_x(game, perm, _e=_e, _f=_flt, **_kw):
                try:
                    if not _f(game, perm, _kw):
                        return
                except Exception:  # noqa: BLE001
                    return
                if _kw.get("subject") is not None:
                    game._trigger_subject = _kw["subject"]
                _e(game, perm.controller, perm)
            _k = "__x_" + _ev
            if _k in out:
                _prev_x = out[_k]
                out[_k] = (lambda g, pm, _a=_prev_x, _b=cb_x, **kw: (_a(g, pm, **kw), _b(g, pm, **kw)))
            else:
                out[_k] = cb_x
        # "when this creature enters or is turned face up / leaves the battlefield",
        # "when this land enters untapped"
        mx = re.match(r"when " + me_any.lower() + r" enters (or is turned face up|or leaves the battlefield|"
                      r"untapped),\s*(.+)$", _ll)
        if mx and "__etb_self" not in out:
            _e = _eff(mx.group(2))
            if _e is not None:
                _unt = mx.group(1) == "untapped"

                def cb_etbx(game, ctrl, perm, _e=_e, _u=_unt):
                    if _u and perm.tapped:
                        return
                    game._run_trigger(lambda g, pm, **kw: _e(g, pm.controller, pm), perm, {})
                out["__etb_self"] = cb_etbx
                if mx.group(1) == "or is turned face up":
                    out.setdefault("turned_face_up", lambda g, pm, _e=_e, **kw: (
                        _e(g, pm.controller, pm) if kw.get("subject") is pm else None))
                elif mx.group(1) == "or leaves the battlefield":
                    out.setdefault("__leave", lambda g, pm, _e=_e, **kw: _e(g, pm.controller, pm))
        mf = re.match(r"(?i)whenever you cast your second spell each turn,\s*(.+)$", l)
        if mf and "cast" not in out:
            eff = _eff(mf.group(1))
            if eff is not None:
                def cb_fl(game, perm, card=None, _e=eff, **_kw):
                    if getattr(perm.controller, "spells_cast_turn", 0) == 2:
                        _e(game, perm.controller, perm)
                out["cast"] = cb_fl
    return out


def _recurring_trigger_effects(oracle: str):
    """Disparos recurrentes 'At the beginning of (your) upkeep/end step, <efecto>'.
    Devuelve {"upkeep"|"end_step": callback(g, perm, **kw)} usando la capa genérica
    de efectos. Antes esto se cableaba mal como un ETB de una sola vez."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    out = {}
    _ms = []
    for _al in _ability_lines(oracle):
        # por LÍNEA y con el cuerpo completo (antes se cortaba a 160 caracteres)
        _mm = re.search(r"at the beginning of (your|each(?: player'?s?| opponent'?s?)?) "
                        r"(upkeep|end step|draw step)[,.]?\s*(.*)$", re.sub(r"\s+", " ", _al).strip(), re.I)
        if _mm:
            _ms.append(_mm)
    for m in _ms:
        ev = "end_step" if "end" in m.group(2).lower() else "upkeep"
        opp_only = "opponent" in m.group(1).lower()
        if m.group(1).lower().startswith("each"):
            ev = "each_" + ev          # cada jugador: no solo en tu propio turno
        body = m.group(3)
        # "put N +1/+1 counter(s) on target creature you control": el genérico no lo
        # cubre (va a una criatura propia elegida; humano elige, bot la mejor).
        msc = re.search(r"put (\w+) \+1/\+1 counters? on (?:up to \w+ )?"
                        r"target creature you control", body, re.I)
        if msc and (nn := _count_word(msc.group(1))):
            def cb_up(game, perm, _n=nn, **_kw):
                ctrl = perm.controller
                pool = sorted(ctrl.creatures(),
                              key=lambda p: (p.power + p.toughness), reverse=True)
                if not pool:
                    return
                cands = [(f"{p.name} {p.power}/{p.toughness}", p) for p in pool]
                _human_target_choice(game, ctrl, "etb_target",
                                     f"Elegí una criatura (+{_n}/+{_n})", cands,
                                     lambda pm, _k=_n: game.add_counters(pm, "+1/+1", _k))
            out[ev] = cb_up
            continue
        # condición de intervención ("if you control six or more lands, …"): antes
        # se ignoraba y Dragonmaster Outcast hacía un dragón en cada mantenimiento
        cond = None
        mif = re.match(r"if ([^,]+),\s*(.+)$", _ability_clause(body), re.I)
        if mif:
            cond = _parse_static_condition(mif.group(1))
            if cond is None:
                continue                 # condición desconocida: no se cablea
            body = mif.group(2)
        eff = _effect_any(_ability_clause(body))
        if eff is None:
            continue

        def cb(game, perm, _e=eff, _c=cond, _o=opp_only, active=None, **_kw):
            if _o and (active is None or active is perm.controller):
                return                   # "each opponent's": solo turnos rivales
            if _c is not None and not _c(perm):
                return
            _e(game, perm.controller)
        if ev in out:                    # segundo disparo del mismo paso: se encadena
            out[ev] = (lambda g, perm, _a=out[ev], _b=cb, **kw: (_a(g, perm, **kw), _b(g, perm, **kw)))
        else:
            out[ev] = cb
    return out


_CLASS_MARK = re.compile(r"^\s*((?:\{[^}]+\})+)\s*:\s*level\s+(\d+)\s*$", re.I)


def _parse_class(card, oracle):
    """Encantamiento — Clase: niveles que se suben pagando un coste; cada nivel
    agrega una habilidad. Modela el contador 'level', las habilidades de subir de
    nivel y cablea (aprox.) las habilidades de cada nivel con verificación de nivel."""
    lines = [ln.strip() for ln in (oracle or "").split("\n") if ln.strip()]
    lines = [ln for ln in lines if not ln.lower().startswith("(gain the next level")]
    segments = {1: []}
    levelup = {}
    cur = 1
    for ln in lines:
        m = _CLASS_MARK.match(ln)
        if m:
            cur = int(m.group(2))
            segments.setdefault(cur, [])
            levelup[cur] = parse_cost(re.sub(r"[{}]", "", m.group(1)))
        else:
            segments.setdefault(cur, []).append(ln)
    card.class_max = max(segments) if segments else 1

    def _class_etb(g, ctrl, perm):
        perm.counters["level"] = max(1, perm.counters.get("level", 0))
    card.on_etb = _class_etb

    # habilidades de subir de nivel (reemplazan el mal-parseo de _parse_activated)
    abils = []
    for n in range(2, card.class_max + 1):
        cost = levelup.get(n)
        if cost is None:
            continue

        def _lvl(g, ctrl, perm, targets=None, _n=n):
            # el motor ya verifica el nivel (level_req) antes de pagar; esto es red.
            if perm.counters.get("level", 1) == _n - 1:
                perm.counters["level"] = _n
                g.log(f"{perm.name} sube a nivel {_n}")
        abils.append({"cost": cost, "tap": False, "sacrifice_self": False,
                      "sacrifice_other": None, "pay_life": 0, "discard": 0,
                      "label": f"Subir a nivel {n}", "effect": _lvl,
                      "target_spec": None, "target_count": 1,
                      "is_copy_ability": False,
                      # solo activable estando en el nivel inmediatamente anterior
                      "level_req": n})
    card.activated_abilities = tuple(abils)

    # habilidades por nivel (disparos), con verificación de nivel
    triggers = dict(card.triggers)
    card._class_segments = {n: " ".join(b) for n, b in segments.items() if b}
    for n, body_lines in segments.items():
        body = " ".join(body_lines)
        if not body:
            continue
        # disparo recurrente: "at the beginning of your (first) main phase/upkeep"
        body_up = re.sub(r"(?:first |precombat |postcombat |post-combat )?main phase",
                         "upkeep", body, flags=re.I)
        for ev, cb in _recurring_trigger_effects(body_up).items():
            def gated(g, perm, _cb=cb, _n=n, **kw):
                if perm.counters.get("level", 1) >= _n:
                    _cb(g, perm, **kw)
            triggers[ev] = gated
        # "whenever one or more cards leave your graveyard, <efecto>"
        mlg = re.search(r"whenever one or more cards? leave your graveyard,?\s*"
                        r"(.{0,160})", body, re.I)
        if mlg:
            eff = _effect_any(mlg.group(1))
            if eff:
                def cb_lg(g, perm, player=None, _e=eff, _n=n, **kw):
                    if perm.counters.get("level", 1) >= _n and player is perm.controller:
                        _e(g, perm.controller)
                triggers["leaves_graveyard"] = cb_lg
    card.triggers = triggers
    card.tags = card.tags | {"class"}


def _death_self_effect(oracle: str, name: str = ""):
    """'When(ever) this creature/<nombre> dies, <efecto>' -> callback on_death
    (game, ctrl, perm). Usa la capa genérica. Antes esto se cableaba mal como ETB."""
    t = re.sub(r"[ \t]+", " ", (oracle or "")).strip()   # conserva \n: "." no cruza habilidades
    nm = "|".join(re.escape(x) for x in sorted(_self_names(name) | {name.lower()}, key=len, reverse=True)
                  if x) if name else None
    who = r"(?:this creature|this permanent|this artifact|it" + (f"|{nm}" if nm else "") + r")"
    m = re.search(r"when(?:ever)? " + who + r" dies,?\s*(.{0,400})", t, re.I)
    if not m:
        return None
    body = m.group(1)
    # disparo de muerte MODAL ("when ~ dies, choose one — …"): los modos se parsean
    # del oráculo COMPLETO (la captura del cuerpo se trunca a 160 y los perdería).
    if re.search(r"\bchoose (one|two|three|one or more|one or both)\b", body, re.I):
        _parsed = _parse_modes(oracle)
        if _parsed is not None:
            _modes = _parsed[0]

            def on_death(game, ctrl, perm, _m=_modes):
                _modal_run(game, ctrl, _m)
            return on_death
    # "put N +1/+1 counters on <the creature/target>": no aplica al morir; ignoramos
    eff = _effect_any(body)
    if eff is None:
        return None

    def on_death(game, ctrl, perm, _e=eff):
        prev = getattr(game, "_trigger_source", None)
        game._trigger_source = perm          # "it" = la criatura que murió
        try:
            _e(game, ctrl)
        finally:
            game._trigger_source = prev
    return on_death


def _persist_undying_ondeath(oracle: str):
    """Persist / Undying: al morir, si NO tenía el contador correspondiente, la
    criatura vuelve al campo con un contador (-1/-1 persist, +1/+1 undying).
    Devuelve on_death(game, ctrl, perm) que retorna True si la reubicó (para que
    el motor no la mande al cementerio), o None si la carta no tiene la mecánica."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())
    # la KEYWORD al inicio de una habilidad, no cualquier subcadena: "Persistent
    # Petitioners" tenía persist y "Other … creatures have undying" (Mikaeus) le
    # daba undying a la propia carta
    def _kw(word):        # la keyword sola: al inicio de línea o como oración suelta
        return bool(re.search(r"(?:^|[.\n])\s*" + word + r"\s*(?:$|[.\n(])",
                              (oracle or "").lower(), re.M))
    undying = (_kw("undying")
               or "return it to the battlefield under its owner's control with a "
                  "+1/+1 counter" in t)
    persist = (_kw("persist")
               or "return it to the battlefield under its owner's control with a "
                  "-1/-1 counter" in t)
    if not (undying or persist):
        return None
    kind = "+1/+1" if undying else "-1/-1"

    def on_death(game, ctrl, perm, _kind=kind):
        if perm.is_token:                       # las fichas dejan de existir
            return False
        if game.commander_owner(perm.card) is not None:    # el comandante va a la zona de mando
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


def _qualified_anthem(t):
    """'creatures you control with flying get +1/+1', 'other black creatures get +1/+1',
    'creatures you control that are enchanted get +1/+1', 'white creatures get +1/+1'."""
    m = re.search(r"(other )?(?:(white|blue|black|red|green|nonwhite|nonblack|nonred|nongreen|nonblue|"
                  r"attacking|blocking|tapped|untapped|legendary|nontoken|artifact|enchantment) )?creatures"
                  r"( you control)?( with [a-z ]+?| that are (?:enchanted|equipped)| of the chosen color)? "
                  r"get ([+-]\d+)/([+-]\d+)(?:\.|$| and)", t)
    if not m or (not m.group(2) and not m.group(4)) or "until end of turn" in t[m.end():m.end() + 25]:
        return None
    if m.group(4) and "chosen color" in m.group(4):
        return None
    others, q, yours, wq = bool(m.group(1)), m.group(2), bool(m.group(3)), (m.group(4) or "").strip()
    if not others and not wq and q and (q in ("white", "blue", "black", "red", "green")
                                        or (q.startswith("non") and q != "nontoken")):
        return "skip"                     # "<color> creatures (you control) get": lo cablea el bloque m13
    dp, dt = int(m.group(5)), int(m.group(6))
    _cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

    def _pips(c):
        return {x for pp in (getattr(c.cost, "pips", None) or ()) for x in str(pp).upper()}

    def sm(source, target, _o=others, _q=q, _y=yours, _w=wq, _dp=dp, _dt=dt):
        if not target.is_creature():
            return (0, 0)
        if _y and target.controller is not source.controller:
            return (0, 0)
        if _o and target is source:
            return (0, 0)
        if _q:
            if _q in _cm and _cm[_q] not in _pips(target.card):
                return (0, 0)
            if _q.startswith("non") and _q[3:] in _cm and _cm[_q[3:]] in _pips(target.card):
                return (0, 0)
            if _q == "attacking" and target.attacking is None:
                return (0, 0)
            if _q == "blocking" and not getattr(target, "blocking", None):
                return (0, 0)
            if _q == "tapped" and not target.tapped or _q == "untapped" and target.tapped:
                return (0, 0)
            if _q == "legendary" and not target.card.is_legendary():
                return (0, 0)
            if _q == "nontoken" and target.is_token:
                return (0, 0)
            if _q in ("artifact", "enchantment") and _q not in target.card.types:
                return (0, 0)
        if _w.startswith("with "):
            if not all(target.has(k.strip().replace(" ", "_")) for k in _w[5:].split(" and ")):
                return (0, 0)
        elif _w and target.game is not None:
            sub = "aura" if "enchanted" in _w else "equipment"
            if not any(getattr(x, "enchanting", None) is target and sub in {y.lower() for y in x.card.subtypes}
                       for pl in target.game.players for x in pl.battlefield):
                return (0, 0)
        return (_dp, _dt)
    return sm


def _static_anthem(oracle: str):
    """Anthem estático de un permanente. Cubre el genérico ('creatures you control
    get +X/+X' / 'have <kw>') y los LORDS por subtipo ('other Goblins you control
    get +1/+1'). Devuelve (static_mod, keywords, subtype) o (None, set(), None).
    subtype != None => el buff/keyword solo aplica a criaturas de ese subtipo."""
    t = re.sub(r"\s+", " ", (oracle or "")).lower()
    _qpre = _qualified_anthem(t)            # "creatures you control with flying get…": calificado
    if _qpre == "skip":
        return None, set(), None
    # el sustantivo puede ser "creatures" (genérico) o un subtipo ("goblins", "elves")
    m = re.search(r"(?:other )?([a-z]+) you control get ([+-]\d+)/([+-]\d+)", t)
    dp = dt = 0
    subtype = None
    scope = "you"
    if m:
        noun = m.group(1)
        dp, dt = int(m.group(2)), int(m.group(3))
        if noun not in ("creatures", "creature"):
            subtype = (noun[:-1] if noun.endswith("s") else noun).capitalize()
    else:
        # debuff a los RIVALES: "creatures your opponents control get -1/-0"
        mo = re.search(r"([a-z]+) (?:your )?opponents control get ([+-]\d+)/([+-]\d+)", t)
        if mo:
            scope = "opp"
            noun = mo.group(1)
            dp, dt = int(mo.group(2)), int(mo.group(3))
            if noun not in ("creatures", "creature"):
                subtype = (noun[:-1] if noun.endswith("s") else noun).capitalize()
    kws = set()
    mk = re.search(r"(?:other )?([a-z]+) you control (?:get [+-]\d+/[+-]\d+ and )?"
                   r"have ([a-z ,and]+?)(?:\.|$|until)", t)
    if mk:
        knoun = mk.group(1)
        for name, key in _KEYWORD_WORDS:
            if re.search(r"\b" + name + r"\b", mk.group(2)):
                kws.add(key)
        if kws and subtype is None and knoun not in ("creatures", "creature"):
            subtype = (knoun[:-1] if knoun.endswith("s") else knoun).capitalize()
    if not (dp or dt or kws):
        if _qpre is not None:
            return _qpre, set(), None
        return None, set(), None
    others = "other " in t

    def sm(source, target, _dp=dp, _dt=dt, _o=others, _sub=subtype, _sc=scope):
        if not target.is_creature():
            return (0, 0)
        if _sc == "opp":                      # aplica a criaturas de los RIVALES
            if target.controller is source.controller:
                return (0, 0)
        else:                                 # aplica a las tuyas
            if target.controller is not source.controller:
                return (0, 0)
            if _o and target is source:
                return (0, 0)
        if _sub and not target.has_subtype(_sub):
            return (0, 0)
        return (_dp, _dt)
    return (_qpre or sm), kws, subtype


_CARD_TYPES = ("artifact", "battle", "creature", "enchantment", "instant", "kindred",
               "land", "planeswalker", "sorcery", "tribal")


_COLOR_W = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


def _cond_eval(c, src):
    """Evalúa una condición f(game, ctrl) de una ESTÁTICA con `src` como fuente."""
    g = getattr(src, "game", None)
    if g is None:
        return False
    prev = getattr(g, "_static_src", None)
    g._static_src = src
    try:
        return bool(c(g, src.controller))
    except Exception:  # noqa: BLE001
        return False
    finally:
        g._static_src = prev


def _cond_src(g, p):
    """Permanente fuente de la habilidad cuya condición se evalúa."""
    ss = getattr(g, "_static_src", None)
    if ss is not None:
        return ss
    ts = getattr(g, "_trigger_source", None)
    if ts is not None and hasattr(ts, "card"):
        return ts
    nm = getattr(g, "_fx_source", None)
    if nm:
        for pm in reversed(p.battlefield):
            if pm.name == nm:
                return pm
    return None


def _perm_colors(pm):
    cols = set()
    for pp in (getattr(pm.card.cost, "pips", None) or ()):
        cols |= set(str(pp).upper()) & set("WUBRG")
    return cols


def _cond_kind_ok(pm, k):
    """¿El permanente es de tipo/subtipo/color `k` (singular, minúscula)?"""
    if k in ("creature",):
        return pm.is_creature()
    if k in ("artifact", "enchantment", "land", "planeswalker", "battle"):
        return k in pm.card.types
    if k == "permanent":
        return True
    if k == "nonland permanent":
        return not pm.card.is_land()
    if k == "token" or k == "creature token":
        return pm.is_token and (k == "token" or pm.is_creature())
    if k == "legendary creature":
        return "legendary" in pm.card.supertypes and pm.is_creature()
    if k == "multicolored permanent":
        return len(_perm_colors(pm)) >= 2
    if k == "colorless creature":
        return pm.is_creature() and not _perm_colors(pm)
    m = re.fullmatch(r"(white|blue|black|red|green) (permanent|creature)", k)
    if m:
        return _COLOR_W[m.group(1)] in _perm_colors(pm) and (m.group(2) == "permanent" or pm.is_creature())
    return pm.has_subtype(k) or pm.name.lower() == k


def _sing(w):
    w = w.strip()
    for a, b in (("ves", "f"), ("ies", "y"), ("es", "") if re.search(r"(?:ss|sh|ch|x)es$", w) else ("s", "")):
        if w.endswith(a):
            return w[: len(w) - len(a)] + b
    return w


def _cond21(c):
    """Condiciones de intervención frecuentes (batch 21): monarca, vida ganada,
    mano, control de tipos/colores/subtipos, estado de la fuente y del encantado,
    lanzado/kicker, cementerio, entradas del turno."""
    turn = lambda g: g.turn  # noqa: E731
    if c in ("you're the monarch", "you are the monarch"):
        return lambda g, p: getattr(g, "monarch", None) is p
    if c == "there is no monarch":
        return lambda g, p: getattr(g, "monarch", None) is None
    m = re.fullmatch(r"you(?:'ve)? gained (\w+) or more life this turn", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: (getattr(p, "gained_amt", (None, 0))[0] == g.turn
                                   and p.gained_amt[1] >= _n)
    if c == "you gained or lost life this turn":
        return lambda g, p: (getattr(p, "gained_turn", None) == g.turn or
                             p.life < (getattr(g, "_life_start", {}) or {}).get(id(p), p.life))
    m = re.fullmatch(r"you have (\w+) or more cards in (?:your )?hand", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: len(p.hand) >= _n
    m = re.fullmatch(r"you have fewer than (\w+) cards in hand", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: len(p.hand) < _n
    if c == "you have more cards in hand than each opponent":
        return lambda g, p: all(len(p.hand) > len(o.hand) for o in g.opponents(p) if not o.lost)
    m = re.fullmatch(r"your life total is less than (\w+)", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: p.life < _n
    if c == "your life total is less than your starting life total":
        return lambda g, p: p.life < getattr(p, "starting_life", 40)
    m = re.fullmatch(r"you have (\w+) or more life", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: p.life >= _n
    m = re.fullmatch(r"you have at least (\w+) life more than your starting life total", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: p.life >= getattr(p, "starting_life", 40) + _n
    if c == "an opponent's life total is less than half their starting life total":
        return lambda g, p: any(o.life < getattr(o, "starting_life", 40) / 2 for o in g.opponents(p) if not o.lost)
    # control de tipos / subtipos / colores
    m = re.fullmatch(r"you control (another|a|an) ([a-z ]+?)(?: or (?:a |an )?([a-z ]+?))?", c)
    if m and m.group(2) not in ("creature with power", "commander") and not re.search(r"\bwith\b|\band\b", c):
        _oth = m.group(1) == "another"
        _ks = [x for x in (m.group(2), m.group(3)) if x]

        def _ctl(g, p, _ks=_ks, _o=_oth):
            src = _cond_src(g, p) if _o else None
            return any(pm is not src and any(_cond_kind_ok(pm, k) for k in _ks) for pm in p.battlefield)
        return _ctl
    m = re.fullmatch(r"you control a (white|blue|black|red|green) permanent and a (white|blue|black|red|green) permanent", c)
    if m:
        return lambda g, p, _a=_COLOR_W[m.group(1)], _b=_COLOR_W[m.group(2)]: (
            any(_a in _perm_colors(pm) for pm in p.battlefield) and any(_b in _perm_colors(pm) for pm in p.battlefield))
    m = re.fullmatch(r"you control (\w+) or more ([a-z ]+?)s", c)
    if m and (n := _count_word(m.group(1))):
        _k = _sing(m.group(2) + "s")
        return lambda g, p, _n=n, _k=_k: sum(1 for pm in p.battlefield if _cond_kind_ok(pm, _k)) >= _n
    m = re.fullmatch(r"you control exactly (\w+) creatures?", c)
    if m and _count_word(m.group(1)) is not None:
        return lambda g, p, _n=_count_word(m.group(1)): len(p.creatures()) == _n
    if c == "you control a creature with a counter on it":
        return lambda g, p: any(any(v > 0 for v in pm.counters.values()) for pm in p.creatures())
    m = re.fullmatch(r"you control another creature with power (\d+) or greater", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): any(pm is not _cond_src(g, p) and pm.power >= _n for pm in p.creatures())
    if c in ("you control a commander", "you control a commander as you cast this spell",
             "you control your commander"):
        return lambda g, p: any(p.is_commander(pm.card) for pm in p.battlefield)
    # cementerio
    m = re.fullmatch(r"(?:there are|you have) (\w+) or more (creature|land|instant and/or sorcery|artifact|enchantment) "
                     r"cards in your graveyard", c)
    if m and (n := _count_word(m.group(1))):
        _k = m.group(2)
        return lambda g, p, _n=n, _k=_k: sum(1 for cd in p.graveyard if (
            bool({"instant", "sorcery"} & cd.types) if "sorcery" in _k else
            (cd.is_creature() if _k == "creature" else _k in cd.types))) >= _n
    m = re.fullmatch(r"there are (\w+) or more card types among cards in your graveyard", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: len({t for cd in p.graveyard for t in cd.types if t in _CARD_TYPES}) >= _n
    m = re.fullmatch(r"there are (\w+) or more mana values among cards in your graveyard", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: len({cd.cost.cmc if cd.cost else 0 for cd in p.graveyard}) >= _n
    # turno
    m = re.fullmatch(r"(\w+) or more creatures died this turn", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: getattr(g, "_deaths_turn", None) == g.turn and getattr(g, "deaths_count", 0) >= _n
    m = re.fullmatch(r"(?:another creature|an? (artifact|creature|enchantment|land|planeswalker)) entered the battlefield "
                     r"under your control this turn", c)
    if m:
        _k = m.group(1) or "creature"
        _oth = c.startswith("another")
        return lambda g, p, _k=_k, _o=_oth: (getattr(p, "_entered_kinds", (None, {}))[0] == g.turn
                                             and p._entered_kinds[1].get(_k, 0) >= (2 if _o else 1))
    if c in ("a permanent left the battlefield under your control this turn",):
        return lambda g, p: getattr(p, "left_turn", None) == g.turn
    if c in ("you've cast a noncreature spell this turn", "you cast a noncreature spell this turn"):
        return lambda g, p: getattr(p, "_noncr_cast_turn", None) == g.turn
    if c == "no creatures attacked this turn":
        return lambda g, p: all(getattr(x, "attacked_turn", None) != g.turn for x in g.players)
    if c == "you didn't attack with a creature this turn":
        return lambda g, p: getattr(p, "attacked_turn", None) != g.turn
    if c in ("it's the first combat phase of the turn",):
        return lambda g, p: True
    m = re.fullmatch(r"(?:this creature|~)'s power is (\d+) or greater", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): getattr(_cond_src(g, p), "power", 0) >= _n
    m = re.fullmatch(r"you control a creature with (flying|toughness (\d+) or greater|power (\d+) or greater)", c)
    if m:
        def _cwith(g, p, _w=m.group(1)):
            for pm in p.creatures():
                if _w == "flying" and pm.has("flying"):
                    return True
                if _w.startswith("toughness") and pm.toughness >= int(_w.split()[1]):
                    return True
                if _w.startswith("power") and pm.power >= int(_w.split()[1]):
                    return True
            return False
        return _cwith
    if c == "an opponent controls a creature with flying":
        return lambda g, p: any(pm.has("flying") for o in g.opponents(p) for pm in o.creatures())
    if c in ("you control no creatures",):
        return lambda g, p: not p.creatures()
    if c in ("you've cast an instant or sorcery spell this turn", "you cast an instant or sorcery spell this turn"):
        return lambda g, p: getattr(p, "_is_cast_turn", None) == g.turn
    m = re.fullmatch(r"you(?:'ve| have) cast (\w+) or more spells this turn", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: getattr(p, "spells_cast_turn", 0) >= _n
    m = re.fullmatch(r"you have exactly (\w+) cards? in hand", c)
    if m and _count_word(m.group(1)) is not None:
        return lambda g, p, _n=_count_word(m.group(1)): len(p.hand) == _n
    m = re.fullmatch(r"you attacked with (\w+) or more creatures this turn", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: getattr(p, "attacked_turn", None) == g.turn and getattr(p, "_attackers_n", 0) >= _n
    m = re.fullmatch(r"there are (\w+) or more colors among permanents you control|there are (\w+) colors among permanents you control", c)
    if m and (n := _count_word(m.group(1) or m.group(2))):
        return lambda g, p, _n=n: len(set().union(*[_perm_colors(pm) for pm in p.battlefield]) if p.battlefield else set()) >= _n
    if c in ("you had a creature enter the battlefield under your control this turn",):
        return lambda g, p: getattr(p, "_entered_kinds", (None, {}))[0] == g.turn and p._entered_kinds[1].get("creature", 0) > 0
    if re.fullmatch(r"(?:a|one or more) cards? left your graveyard this turn", c):
        return lambda g, p: getattr(p, "gy_left_turn", None) == g.turn
    m = re.fullmatch(r"there are at least (\w+) ([a-z]+) (creature )?cards in your graveyard", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n, _k=m.group(2): sum(
            1 for cd in p.graveyard if any(st.lower() == _k for st in cd.subtypes) or _k in cd.types) >= _n
    if c in ("you've cast a creature spell this turn", "you cast a creature spell this turn"):
        return lambda g, p: (getattr(p, "_cr_cast", None) or (None,))[0] == g.turn
    if c in ("an opponent has been dealt damage this turn", "an opponent was dealt damage this turn"):
        return lambda g, p: any(o.life < (getattr(g, "_life_start", {}) or {}).get(id(o), o.life) for o in g.opponents(p))
    m = re.fullmatch(r"there (?:is an?|are (\w+) or more) (mountain|island|swamp|forest|plains|[a-z]+?)s? on the battlefield", c)
    if m:
        return lambda g, p, _n=_count_word(m.group(1) or "one") or 1, _k=m.group(2): sum(
            1 for pl in g.players for pm in pl.battlefield if pm.has_subtype(_k) or pm.name.lower() == _k) >= _n
    m = re.fullmatch(r"you control (\w+) or more other ([a-z]+?)s", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n, _k=m.group(2): sum(1 for pm in p.battlefield if pm is not _cond_src(g, p)
                                                     and _cond_kind_ok(pm, _k)) >= _n
    if c in ("you control more creatures than an opponent",):
        return lambda g, p: any(len(p.creatures()) > len(o.creatures()) for o in g.opponents(p) if not o.lost)
    if c in ("an opponent controls an untapped land",):
        return lambda g, p: any(pm.card.is_land() and not pm.tapped for o in g.opponents(p) for pm in o.battlefield)
    if c in ("you control an untapped land",):
        return lambda g, p: any(pm.card.is_land() and not pm.tapped for pm in p.battlefield)
    if c in ("this creature is blocked", "~ is blocked"):
        return lambda g, p: bool(getattr(_cond_src(g, p), "blocked_by", None))
    if c == "it's neither day nor night":
        return lambda g, p: getattr(g, "day_night", None) is None
    if c in ("it's not their turn",):
        return lambda g, p: (_that_player(g, p) or p) is not g.players[g.active_index]
    # "that player" del disparo
    m = re.fullmatch(r"that player has (\w+) or (fewer|more) cards in hand", c)
    if m and _count_word(m.group(1)) is not None:
        def _tp_hand(g, p, _n=_count_word(m.group(1)), _f=m.group(2) == "fewer"):
            tp = _that_player(g, p)
            if tp is None:
                return False
            return len(tp.hand) <= _n if _f else len(tp.hand) >= _n
        return _tp_hand
    if c == "that player has no cards in hand":
        return lambda g, p: (_that_player(g, p) is not None and not _that_player(g, p).hand)
    # estado de la FUENTE
    m = re.fullmatch(r"(?:this (?:creature|artifact|land|enchantment|permanent)|~|it) is (untapped|tapped|attacking|"
                     r"blocking|equipped|enchanted|renowned)", c)
    if m:
        def _st(g, p, _w=m.group(1)):
            src = _cond_src(g, p)
            if src is None:
                return False
            if _w in ("untapped", "tapped"):
                return src.tapped == (_w == "tapped")
            if _w == "attacking":
                return src.attacking is not None
            if _w == "blocking":
                return bool(src.blocking)
            if _w in ("equipped", "enchanted"):
                sub = "equipment" if _w == "equipped" else "aura"
                return any(getattr(x, "enchanting", None) is src and x.has_subtype(sub) for x in g.all_permanents())
            return bool(getattr(src, "renowned", False))
        return _st
    m = re.fullmatch(r"(?:this (?:creature|artifact|land|enchantment|permanent)|~|it) has (\w+) or more "
                     r"(\+1/\+1 |[a-z]+ |)counters on it", c)
    if m and (n := _count_word(m.group(1))):
        def _ctrs(g, p, _n=n, _k=m.group(2).strip()):
            src = _cond_src(g, p)
            if src is None:
                return False
            return (src.counters.get(_k, 0) if _k else sum(src.counters.values())) >= _n
        return _ctrs
    m = re.fullmatch(r"there are (\w+) or more ([a-z+/1]+) counters on (?:this (?:creature|artifact|enchantment|land)|~)", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n, _k=m.group(2): (_cond_src(g, p) is not None
                                                  and _cond_src(g, p).counters.get(_k, 0) >= _n)
    m = re.fullmatch(r"this (?:creature|permanent) is enchanted by (\w+) or more auras", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: sum(1 for x in g.all_permanents() if getattr(x, "enchanting", None) is _cond_src(g, p)
                                      and x.has_subtype("aura")) >= _n
    m = re.fullmatch(r"this permanent is an? (enchantment|creature|artifact)", c)
    if m:
        return lambda g, p, _k=m.group(1): (_cond_src(g, p) is not None and (
            _cond_src(g, p).is_creature() if _k == "creature" else _k in _cond_src(g, p).card.types))
    if c in ("this creature didn't attack this turn", "~ didn't attack this turn"):
        return lambda g, p: getattr(_cond_src(g, p), "attacked_turn", None) != g.turn
    if c in ("~ attacked this turn", "this creature attacked this turn", "it attacked this turn"):
        return lambda g, p: getattr(_cond_src(g, p), "attacked_turn", None) == g.turn
    if c in ("you cast it", "it was cast", "he was cast", "she was cast", "they were cast", "you cast this creature"):
        return lambda g, p: bool(getattr(_cond_src(g, p), "_was_cast", False))
    if c in ("you cast it from your hand",):
        return lambda g, p: bool(getattr(_cond_src(g, p), "_was_cast", False)
                                 and getattr(_cond_src(g, p), "_cast_from_hand", False))
    if c in ("you cast it from anywhere other than your hand",):
        return lambda g, p: bool(getattr(_cond_src(g, p), "_was_cast", False)
                                 and not getattr(_cond_src(g, p), "_cast_from_hand", False))
    if c in ("it was kicked", "this creature was kicked", "~ was kicked"):
        return lambda g, p: bool(getattr(_cond_src(g, p), "_was_cast", False)
                                 and getattr(getattr(_cond_src(g, p), "card", None), "_kicked", False))
    if c in ("this spell was kicked",):
        return lambda g, p: bool(getattr(getattr(g, "_resolving_card", None), "_kicked", False))
    # estado del ENCANTADO
    m = re.fullmatch(r"enchanted (?:permanent|creature) is an? (creature|equipment|vehicle|artifact|land|"
                     r"white|blue|black|red|green)(?: creature)?", c)
    if m:
        def _enc(g, p, _k=m.group(1)):
            src = _cond_src(g, p)
            h = getattr(src, "enchanting", None) if src is not None else None
            if h is None:
                return False
            if _k in _COLOR_W:
                return _COLOR_W[_k] in _perm_colors(h)
            if _k == "creature":
                return h.is_creature()
            return h.has_subtype(_k) or _k in h.card.types
        return _enc
    m = re.fullmatch(r"enchanted creature's power is (\d+) or greater", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): (getattr(_cond_src(g, p), "enchanting", None) is not None
                                                 and _cond_src(g, p).enchanting.power >= _n)
    return None


def _kind_pred21(phrase):
    """'artifact, creature, or enchantment' / 'creature with flying' / 'snow land' /
    'creature with power 4 or greater' / 'nonland permanent' -> pred(pm) o None."""
    p = re.sub(r"\s+", " ", (phrase or "").lower().strip())
    mw = re.fullmatch(r"(.+?) with (flying|power (\d+) or greater|power (\d+) or less|mana value (\d+) or less|"
                      r"mana value (\d+) or greater)", p)
    extra = None
    if mw:
        p, w = mw.group(1), mw.group(2)
        if w == "flying":
            extra = lambda pm: pm.has("flying")  # noqa: E731
        elif mw.group(3):
            extra = lambda pm, _n=int(mw.group(3)): pm.power >= _n  # noqa: E731
        elif mw.group(4):
            extra = lambda pm, _n=int(mw.group(4)): pm.power <= _n  # noqa: E731
        elif mw.group(5):
            extra = lambda pm, _n=int(mw.group(5)): (pm.card.cost.cmc if pm.card.cost else 0) <= _n  # noqa: E731
        else:
            extra = lambda pm, _n=int(mw.group(6)): (pm.card.cost.cmc if pm.card.cost else 0) >= _n  # noqa: E731
    parts = [x.strip() for x in re.split(r",\s*(?:or\s+|and/or\s+)?|\s+(?:or|and/or)\s+", p) if x.strip()]
    preds = []
    for k in parts:
        k = re.sub(r"^(?:a|an) ", "", k)
        if k == "spell":
            continue
        if k == "snow land":
            preds.append(lambda pm: pm.card.is_land() and "snow" in pm.card.supertypes)
        elif k == "nontoken creature":
            preds.append(lambda pm: pm.is_creature() and not pm.is_token)
        elif k == "enchanted permanent":
            preds.append(lambda pm: any(getattr(x, "enchanting", None) is pm for x in pm.game.all_permanents())
                         if pm.game else False)
        elif k in ("creature", "artifact", "enchantment", "land", "planeswalker", "permanent", "nonland permanent",
                   "battle") or re.fullmatch(r"[a-z]+", k):
            preds.append(lambda pm, _k=_sing(k + "s") if k not in ("permanent", "nonland permanent") else k:
                         _cond_kind_ok(pm, _k))
        else:
            return None
    if not preds:
        return None
    return lambda pm, _ps=tuple(preds), _e=extra: any(f(pm) for f in _ps) and (_e is None or _e(pm))


def _cond_misc17(c):
    m = re.fullmatch(r"you control (\w+) or more lands with the same name", c)
    if m and (n := _count_word(m.group(1))):
        import collections as _co
        return lambda g, p, _n=n: max(_co.Counter(pm.name for pm in p.battlefield if pm.card.is_land()).values(),
                                       default=0) >= _n
    m = re.fullmatch(r"an opponent controls (\w+) or more lands", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: any(sum(1 for pm in o.battlefield if pm.card.is_land()) >= _n
                                       for o in g.opponents(p))
    m = re.fullmatch(r"you control no ([a-z]+?)s?", c)
    if m:
        return lambda g, p, _k=m.group(1): not any(pm.has_subtype(_k) or _k in pm.card.types for pm in p.battlefield)
    m = re.fullmatch(r"you have at least (\d+) life more than your starting life total", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): p.life >= 40 + _n
    if c in ("you control your commander", "you control a commander"):
        return lambda g, p: any(p.is_commander(pm.card) for pm in p.battlefield)
    return None


def _cond_more_than_you(c):
    m = re.fullmatch(r"(an opponent|that player) controls more (lands|creatures|artifacts|enchantments) than you", c)
    if not m:
        return None
    k = m.group(2)[:-1]

    def _n(pl):
        return sum(1 for pm in pl.battlefield if (pm.is_creature() if k == "creature" else k in pm.card.types))

    if m.group(1) == "an opponent":
        return lambda g, p: any(_n(o) > _n(p) for o in g.opponents(p))

    def _that(g, p):
        kw = getattr(g, "_trigger_kw", None) or {}
        o = kw.get("active") or kw.get("player") or kw.get("defender")
        o = o if hasattr(o, "life") else getattr(o, "controller", None)
        return o is not None and o is not p and _n(o) > _n(p)
    return _that


def _cond_gc(cond_text: str):
    """Condición de juego -> f(game, ctrl) -> bool (palabras de habilidad: raid,
    morbid, hellbent, delirium, metalcraft, ferocious, spell mastery, formidable,
    revolt, corrupted, coven, celebration, descend, void…). None si no se conoce."""
    c = re.sub(r"\s+", " ", (cond_text or "")).strip().lower().rstrip(".")
    c = re.sub(r"^(?:if|as long as|only if) ", "", c)
    _mt = _cond_more_than_you(c) or _cond_misc17(c) or _cond21(c)
    if _mt is not None:
        return _mt
    turn = lambda g: g.turn  # noqa: E731
    # werewolves (Innistrad): hechizos del turno anterior
    if re.fullmatch(r"no spells were cast last turn", c):
        return lambda g, p: getattr(g, "turns_played", 0) > 1 and \
            getattr(g, "spells_last_turn", 0) == 0
    if re.fullmatch(r"a player cast two or more spells last turn", c):
        return lambda g, p: getattr(g, "max_player_spells_last_turn", 0) >= 2
    # eminence: funciona desde la zona de mando o el campo (siempre verdadero acá)
    if re.fullmatch(r"[\w ,'~-]+ is in the command zone or on the battlefield", c):
        return lambda g, p: True
    # caso resuelto (el disparo se evalúa sobre el permanente fuente)
    if re.fullmatch(r"(?:this case|~|it) is solved", c):
        def _solved(g, p):
            src = getattr(g, "_fx_source", None)
            pool = [pm for pm in p.battlefield if "case" in {x.lower() for x in pm.card.subtypes}]
            own = [pm for pm in pool if pm.name == src]
            return any(getattr(pm, "solved", False) for pm in (own or pool))
        return _solved
    # addendum: al resolver en tu turno fuera del combate (= lanzado en main)
    if re.fullmatch(r"you cast (?:this spell|it) during your main phase", c):
        return lambda g, p: (g.players[g.active_index] is p and not any(
            getattr(pm, "attacking", None) for pm in p.battlefield))
    # kinship: la de arriba de tu biblioteca comparte tipo de criatura con la fuente
    if re.fullmatch(r"the top card of your library shares a creature type with [\w ,'~-]+", c):
        def _kin(g, p):
            if not p.library:
                return False
            src = getattr(g, "_fx_source", None)
            me = next((pm for pm in p.battlefield if pm.name == src), None)
            top = p.library[-1]
            if me is None or "creature" not in top.types and "kindred" not in top.types \
                    and "tribal" not in top.types:
                return False
            return bool(top.subtypes) and any(me.has_subtype(st) for st in top.subtypes) \
                or "changeling" in (top.keywords or set())
        return _kin
    if re.fullmatch(r"you attacked(?: with (?:a|one or more) creatures?)? this turn", c):
        return lambda g, p: getattr(p, "attacked_turn", None) == turn(g)
    if re.fullmatch(r"(?:a|one or more) creatures? died this turn", c):
        return lambda g, p: getattr(g, "death_turn", None) == turn(g)
    m = re.fullmatch(r"(?:there are )?(\w+) or more cards (?:are )?in your graveyard", c)
    if m and (n := _count_word(m.group(1))):
        return lambda g, p, _n=n: len(p.graveyard) >= _n
    if re.fullmatch(r"you have no cards in hand", c):
        return lambda g, p: not p.hand
    m = re.fullmatch(r"you have (\w+) or fewer cards in hand", c)
    if m and _count_word(m.group(1)) is not None:
        return lambda g, p, _n=_count_word(m.group(1)): len(p.hand) <= _n
    if re.fullmatch(r"there are four or more card types among cards in your graveyard", c):
        return lambda g, p: len({t for cd in p.graveyard for t in cd.types
                                 if t in _CARD_TYPES}) >= 4
    m = re.fullmatch(r"you control (\w+) or more (artifact|enchantment|creature|land|"
                     r"planeswalker|legendary creature|legendary permanent|token)s?", c)
    if m and (n := _count_word(m.group(1))):
        kind = m.group(2)

        def _cnt(g, p, _n=n, _k=kind):
            def ok(pm):
                if _k == "token":
                    return pm.is_token
                if _k.startswith("legendary"):
                    return "legendary" in pm.card.supertypes and (
                        _k.endswith("permanent") or pm.is_creature())
                return pm.is_creature() if _k == "creature" else _k in pm.card.types
            return sum(1 for pm in p.battlefield if ok(pm)) >= _n
        return _cnt
    m = re.fullmatch(r"you control (?:a|an) (artifact|enchantment|creature|planeswalker|"
                     r"legendary creature|equipment|aura|vehicle)", c)
    if m:
        k = m.group(1)
        return lambda g, p, _k=k: any(
            (pm.has_subtype(_k) if _k in ("equipment", "aura", "vehicle") else
             ("legendary" in pm.card.supertypes and pm.is_creature()) if _k.startswith("legendary")
             else pm.is_creature() if _k == "creature" else _k in pm.card.types)
            for pm in p.battlefield)
    m = re.fullmatch(r"you control a creature with power (\d+) or greater", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): any(pm.power >= _n for pm in p.creatures())
    if re.fullmatch(r"there are two or more instant and/or sorcery cards in your graveyard", c):
        return lambda g, p: sum(1 for cd in p.graveyard
                                if {"instant", "sorcery"} & cd.types) >= 2
    m = re.fullmatch(r"creatures you control have total power (\d+) or greater", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): sum(max(0, pm.power)
                                                    for pm in p.creatures()) >= _n
    if re.fullmatch(r"a permanent you controlled left the battlefield this turn", c):
        return lambda g, p: getattr(p, "left_turn", None) == turn(g)
    if re.fullmatch(r"an opponent has three or more poison counters", c):
        return lambda g, p: any(o.poison >= 3 for o in g.opponents(p))
    if re.fullmatch(r"you control three or more creatures with different powers", c):
        return lambda g, p: len({pm.power for pm in p.creatures()}) >= 3
    if re.fullmatch(r"two or more nonland permanents entered the battlefield under your "
                    r"control this turn", c):
        return lambda g, p: (getattr(p, "_entered_turn", None) == turn(g)
                             and getattr(p, "entered_nonland", 0) >= 2)
    m = re.fullmatch(r"there are (\w+) or more permanent cards in your graveyard", c)
    if m and (n := _count_word(m.group(1))):
        _perm = {"artifact", "battle", "creature", "enchantment", "land", "planeswalker"}
        return lambda g, p, _n=n: sum(1 for cd in p.graveyard if _perm & cd.types) >= _n
    if re.fullmatch(r"a nonland permanent left the battlefield this turn(?: or a spell "
                    r"was warped this turn)?", c):
        return lambda g, p: (getattr(g, "nonland_left_turn", None) == turn(g)
                             or getattr(g, "warped_turn", None) == turn(g))
    if re.fullmatch(r"an opponent lost life this turn", c):
        return lambda g, p: any(o.life < (getattr(g, "_life_start", {}) or {}).get(id(o), o.life)
                                for o in g.opponents(p))
    if re.fullmatch(r"you(?:'ve| have) cast (?:another|two or more) spells? this turn", c):
        need = 2
        return lambda g, p, _n=need: getattr(p, "spells_cast_turn", 0) >= _n
    m = re.fullmatch(r"you have (\d+) or less life", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): p.life <= _n
    if re.fullmatch(r"you(?:'ve| have) completed a dungeon", c):
        return lambda g, p: getattr(p, "dungeons_completed", 0) > 0
    if re.fullmatch(r"you have the initiative", c):
        return lambda g, p: getattr(p, "initiative", False)
    if re.fullmatch(r"you have the city'?s blessing", c):
        return lambda g, p: getattr(p, "citys_blessing", False)
    m = re.fullmatch(r"your speed is (\d+)(?: or greater)?", c)
    if m:
        return lambda g, p, _n=int(m.group(1)): getattr(p, "speed", 0) >= _n
    if re.fullmatch(r"(?:the )?gift was promised", c):
        return lambda g, p: bool(getattr(getattr(g, "_resolving_card", None),
                                         "_gift_promised", False)
                                 or getattr(getattr(getattr(g, "_trigger_source", None),
                                                    "card", None), "_gift_promised", False))
    if re.fullmatch(r"(?:this spell|it) was bargained", c):
        return lambda g, p: bool(getattr(getattr(g, "_resolving_card", None),
                                         "_bargained", False)
                                 or getattr(getattr(getattr(g, "_trigger_source", None),
                                                    "card", None), "_bargained", False))
    if re.fullmatch(r"you(?:'ve| have)? gained life this turn", c):
        return lambda g, p: getattr(p, "gained_turn", None) == turn(g)
    if re.fullmatch(r"it'?s your turn", c):
        return lambda g, p: g.players[g.active_index] is p
    if re.fullmatch(r"it'?s not your turn", c):
        return lambda g, p: g.players[g.active_index] is not p
    return None


def _known_if(body):
    """'if <condición>, …' con una condición que sabemos evaluar."""
    m = re.match(r"\s*if ([^,]+),", body or "", re.I)
    return bool(m and _cond_gc(m.group(1)) is not None)


def _parse_static_condition(cond_text: str):
    """'condición' de un buff estático condicional -> predicado cond(perm)->bool,
    evaluado dinámicamente sobre el CONTROLADOR del permanente. None si no la
    reconocemos. Cubre: controlás una tierra básica de tipo X; N+ tierras; N+ de
    vida; N+ criaturas; N+ cartas en tu cementerio."""
    c = re.sub(r"\s+", " ", (cond_text or "")).strip().lower()
    mland = re.search(r"you control (?:a|an) (forest|plains|island|swamp|mountain)", c)
    if mland:
        sub = mland.group(1).capitalize()
        # la tierra básica puede traer el subtipo o solo el nombre -> aceptar ambos
        return (lambda p, _s=sub: any(
            pm.card.is_land() and (pm.has_subtype(_s) or pm.name == _s)
            for pm in p.controller.battlefield))
    ml = re.search(r"you (?:have|control) (\w+) or more lands", c)
    if ml and (n := _count_word(ml.group(1))):
        return (lambda p, _n=n: sum(1 for pm in p.controller.battlefield
                                    if pm.card.is_land()) >= _n)
    mlife = re.search(r"you have (\d+) or more life", c)
    if mlife:
        return (lambda p, _n=int(mlife.group(1)): p.controller.life >= _n)
    mcre = re.search(r"you control (\w+) or more creatures", c)
    if mcre and (n := _count_word(mcre.group(1))):
        return (lambda p, _n=n: sum(1 for _ in p.controller.creatures()) >= _n)
    mgy = re.search(r"(\w+) or more cards? (?:in|are in) your graveyard", c)
    if mgy and (n := _count_word(mgy.group(1))):
        return (lambda p, _n=n: len(p.controller.graveyard) >= _n)
    # "a card left your graveyard this turn" (Primary Research, Lorehold)
    if re.search(r"(?:a|one or more) cards? left your graveyard this turn", c):
        return (lambda p: getattr(p.controller, "gy_left_turn", None) == p.game.turn)
    # condiciones sobre el PROPIO permanente
    if re.fullmatch(r"(?:it'?s|it is|this creature is|~ is) saddled", c):
        return lambda p: getattr(p, "saddled_turn", None) == p.game.turn
    if re.fullmatch(r"(?:it'?s|this creature is|~ is) tapped", c):
        return lambda p: p.tapped
    if re.fullmatch(r"(?:it'?s|it is|this creature is|~ is) attacking", c):
        return lambda p: getattr(p, "attacking", None) is not None
    if re.fullmatch(r"(?:it'?s|it is|this creature is|~ is) blocking", c):
        return lambda p: bool(getattr(p, "blocking", None))
    if re.fullmatch(r"(?:this creature|~|it) is monstrous", c):
        return lambda p: bool(getattr(p, "monstrous", False))
    if re.fullmatch(r"(?:this case|~|it) is solved", c):
        return lambda p: bool(getattr(p, "solved", False))
    # ── batch 14: más condiciones del propio permanente ──
    S = r"(?:it'?s|it is|this creature is|~ is|this creature's|it's)"
    mcc = re.fullmatch(r"(?:it|this creature|~) has (?:a|an|one or more) ([+\-\d/a-z]+ )?counters? on it", c)
    if mcc:
        k = (mcc.group(1) or "").strip()
        return (lambda p, _k=k: (p.counters.get(_k, 0) > 0) if _k else
                any(v > 0 for v in p.counters.values()))
    if re.fullmatch(S + r" untapped", c):
        return lambda p: not p.tapped
    if re.fullmatch(r"(?:it|this creature|~) entered (?:the battlefield )?this turn", c):
        return lambda p: bool(p.summoning_sick)
    if re.fullmatch(S + r" (enchanted|equipped)", c):
        _sub = "aura" if "enchanted" in c else "equipment"
        return (lambda p, _s=_sub: p.game is not None and any(
            getattr(src, "enchanting", None) is p and _s in {x.lower() for x in src.card.subtypes}
            for pl in p.game.players for src in pl.battlefield))
    if re.fullmatch(S + r" modified", c):
        return (lambda p: any(v > 0 for v in p.counters.values()) or (p.game is not None and any(
            getattr(src, "enchanting", None) is p for pl in p.game.players for src in pl.battlefield)))
    mctl = re.fullmatch(r"you control (another |a |an |two or more |three or more |\w+ or more )?"
                        r"(untapped )?(white |blue |black |red |green |legendary |nontoken )?"
                        r"([a-z]+?)s?(?: creature)?s?", c)
    if mctl and mctl.group(1) is not None:
        many = mctl.group(1).strip()
        n = (_count_word(many.split()[0]) if "or more" in many else 1) or 1
        other = many == "another"
        col = (mctl.group(3) or "").strip()
        kind = mctl.group(4)
        cmap = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

        def _ok(pm, src, _k=kind, _c=col, _o=other, _u=bool(mctl.group(2))):
            if _o and pm is src:
                return False
            if _u and pm.tapped:
                return False
            if _c in cmap:
                pips = set()
                for pp in (getattr(pm.card.cost, "pips", None) or ()):
                    pips |= set(str(pp).upper())
                if cmap[_c] not in pips:
                    return False
            elif _c == "legendary" and not pm.card.is_legendary():
                return False
            elif _c == "nontoken" and pm.is_token:
                return False
            if _k == "creature":
                return pm.is_creature()
            if _k in ("artifact", "enchantment", "planeswalker", "land", "battle"):
                return _k in pm.card.types
            if _k == "permanent":
                return True
            return pm.has_subtype(_k)
        return (lambda p, _n=n: sum(1 for pm in p.controller.battlefield if _ok(pm, p)) >= _n)
    if re.fullmatch(r"you control no untapped lands", c):
        return lambda p: not any(pm.card.is_land() and not pm.tapped for pm in p.controller.battlefield)
    mop = re.fullmatch(r"(?:an opponent|defending player) controls (?:a|an) ([a-z]+)", c)
    if mop:
        k = mop.group(1)
        return (lambda p, _k=k: p.game is not None and any(
            (_k in pm.card.types or pm.has_subtype(_k) or (_k == "creature" and pm.is_creature()))
            for o in p.game.opponents(p.controller) for pm in o.battlefield))
    mdr = re.fullmatch(r"you've drawn (\w+) or more cards this turn", c)
    if mdr and (n := _count_word(mdr.group(1))):
        return lambda p, _n=n: getattr(p.controller, "draws_this_turn", 0) >= _n
    mog = re.fullmatch(r"an opponent has (\w+) or more cards in their graveyard", c)
    if mog and (n := _count_word(mog.group(1))):
        return (lambda p, _n=n: p.game is not None and any(
            len(o.graveyard) >= _n for o in p.game.opponents(p.controller)))
    if re.fullmatch(r"your life total is less than or equal to half your starting life total", c):
        return lambda p: p.controller.life <= 20
    mlm = re.fullmatch(r"you have at least (\d+) life more than your starting life total", c)
    if mlm:
        return lambda p, _n=int(mlm.group(1)): p.controller.life >= 40 + _n
    mtg = re.fullmatch(r"there(?:'s| is) an? ([a-z]+) card in your graveyard", c)
    if mtg:
        return (lambda p, _k=mtg.group(1): any(
            _k in x.types or any(st.lower() == _k for st in x.subtypes) for x in p.controller.graveyard))
    gc = _cond_gc(c)
    if gc is not None:
        return (lambda p, _g=gc: p.game is not None and _cond_eval(_g, p))
    return None


def _conditional_self_keywords(oracle: str, name: str = ""):
    """'This creature has <kw> as long as <cond>' / 'As long as <cond>, this
    creature gets +X/+Y and has <kw>' -> [(keyword, cond(perm))]."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    subj = r"this creature|it|~"
    if name:
        subj = "|".join(re.escape(x) for x in sorted(_self_names(name) | {name.lower()}, key=len, reverse=True)
                        if x) + r"|" + subj
    out = []
    for m in re.finditer(r"(?:" + subj + r") can't be blocked as long as ([^.]+)", t, re.I):
        cond = _parse_static_condition(m.group(1))
        if cond is not None:
            out.append(("unblockable", cond))
    pats = [
        (r"(?:" + subj + r") has ([a-z ,]+?) as long as ([^.]+)", 1, 2),
        (r"(?:" + subj + r") gets [+-]\d+/[+-]\d+ and has ([a-z ,]+?) as long as ([^.]+)", 1, 2),
        (r"as long as ([^,]+), (?:" + subj + r") (?:gets [+-]\d+/[+-]\d+ and )?has "
         r"([a-z ,]+?)(?:\.|$| and )", 2, 1),
    ]
    for pat, gk, gc in pats:
        for m in re.finditer(pat, t, re.I):
            cond = _parse_static_condition(m.group(gc))
            if cond is None:
                continue
            for w in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(gk)):
                k = w.strip().lower().replace(" ", "_")
                if k in KEYWORDS:
                    out.append((k, cond))
    return out


def _conditional_self_buff(oracle: str, name: str = ""):
    """'<Nombre/This creature/It> gets +X/+Y as long as <condición>' -> static_mod
    que aplica +X/+Y SOLO a esta misma criatura mientras la condición se cumpla
    (Sylvan Advocate, Kird Ape, Angel of Vitality…). None si no matchea."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    subj = r"this creature|it|~"
    if name:
        subj = "|".join(re.escape(x) for x in sorted(_self_names(name) | {name.lower()}, key=len, reverse=True)
                        if x) + r"|" + subj
    m = re.search(r"(?:" + subj + r") gets ([+-]\d+)/([+-]\d+)(?: and has [^.]+?)? as long "
                  r"as ([^.]+)", t, re.I)
    if m:
        dp, dt, cond_txt = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"as long as ([^,]+), (?:" + subj + r") gets ([+-]\d+)/([+-]\d+)",
                      t, re.I)
        if not m:
            return None
        dp, dt, cond_txt = int(m.group(2)), int(m.group(3)), m.group(1)
    cond = _parse_static_condition(cond_txt)
    if cond is None:
        return None

    def sm(source, target, _dp=dp, _dt=dt, _c=cond):
        if target is not source:
            return (0, 0)
        try:
            return (_dp, _dt) if _c(source) else (0, 0)
        except Exception:  # noqa: BLE001
            return (0, 0)
    return sm


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


def _wire_reanimate_aura(card, t):
    """Animate Dead / Necromancy / Dance of the Dead: devuelve una criatura de un
    cementerio bajo tu control con el Aura anexada (-1/-0 si lo dice); si el Aura
    deja el campo, se sacrifica la criatura."""
    card.tags = card.tags | {"aura", "reanimate"}
    mg = re.search(r"enchanted creature gets ([+-]\d+)/([+-]\d+)", t)
    if mg:
        _d = (int(mg.group(1)), int(mg.group(2)))
        card.static_mod = (lambda src, target, _d=_d:
                           _d if target is getattr(src, "enchanting", None) else (0, 0))
    _own_only = "in your graveyard" in t

    def _etb(game, ctrl, perm):
        pools = [ctrl] if _own_only else game.players
        cands = [(pl, c) for pl in pools for c in pl.graveyard if c.is_creature()]
        if not cands:
            return
        pl, c = max(cands, key=lambda x: ((x[1].cost.cmc if x[1].cost else 0), x[1].power, x[0] is ctrl))
        pl.graveyard.remove(c)
        host = game.move_to_battlefield(c, ctrl)
        if host is not None:
            perm.enchanting = host
            game.log(f"{ctrl.name} reanima {c.name} con {perm.name}")
    card.on_etb = _etb

    def _leave(game, ctrl, perm, _prev=card.on_leave):
        host = getattr(perm, "enchanting", None)
        if host is not None and host in host.controller.battlefield:
            game.to_graveyard(host, "sacrificio (el Aura dejó el campo)")
        if _prev:
            _prev(game, ctrl, perm)
    card.on_leave = _leave


def _granted_abilities(t, who):
    """'enchanted creature has "{T}: …"' / 'equipped creature has "…"' -> habilidades
    activadas que el huésped gana mientras esté anexado."""
    out = []
    for m in re.finditer(who + r" (?:has|gains) \"([^\"]+)\"", t):
        out.extend(_parse_activated(m.group(1).replace("this creature", "~"), "~"))
    return tuple(out)


def _grant_to_host(game, src, host):
    """Le agrega al huésped las habilidades que otorga `src` (aura/equipo)."""
    gr = getattr(src.card, "granted_abilities", None)
    if not gr or host is None:
        return
    have = [a for a in (host.card.activated_abilities or ()) if a.get("granted_by") is src]
    if have:
        return
    host.card.activated_abilities = tuple(host.card.activated_abilities or ()) + tuple(
        dict(a, granted_by=src) for a in gr)


def _wire_player_aura(card, t):
    """Aura de JUGADOR (curses): se anexa a un rival al entrar. Cablea los disparos
    'whenever enchanted player is attacked' (+ 'each opponent attacking that player
    does the same'), 'whenever a creature attacks enchanted player' y 'at the
    beginning of enchanted player's upkeep'."""
    card.tags = card.tags | {"aura", "curse"}

    def _etb(game, ctrl, perm, _prev=card.on_etb):
        opps = [o for o in game.opponents(ctrl) if not o.lost]
        if opps:
            # el rival que más vida tiene: el que más van a atacar (curses de grupo)
            perm.enchanting_player = max(opps, key=lambda o: o.life)
            game.log(f"{ctrl.name}: {perm.name} encanta a {perm.enchanting_player.name}")
        if _prev:
            _prev(game, ctrl, perm)
    card.on_etb = _etb
    m = re.search(r"whenever enchanted player is attacked, ([^.]+)\.( each opponent attacking that player does "
                  r"the same\.)?", t)
    if m and (eff := _effect_any(m.group(1))) is not None:
        def _att(game, src, attacker, _e=eff, _same=bool(m.group(2))):
            game._run_trigger(lambda g, pm, **kw: _e(g, pm.controller, pm), src, {"player": attacker})
            if _same and attacker is not src.controller and not attacker.lost:
                _e(game, attacker, src)
        card.curse_attacked = _att
    m = re.search(r"whenever a creature attacks enchanted player(?: or a planeswalker they control)?, ([^.]+)", t)
    if m:
        body = m.group(1).strip()
        mc = re.fullmatch(r"(?:put a \+1/\+1 counter on it|its controller (.+))", body)
        if mc and mc.group(1) is None:
            card.curse_creature_attacks = lambda game, src, a: (
                game.add_counters(a, "+1/+1", 1) if a in a.controller.battlefield else None)
        elif mc and (eff := _effect_any("you " + re.sub(r"^(\w+?)s\b", r"\1", mc.group(1)))) is not None:
            card.curse_creature_attacks = lambda game, src, a, _e=eff: _e(game, a.controller, src)
    m = re.search(r"at the beginning of (?:the upkeep of enchanted player|enchanted player's upkeep), ([^.]+(?:\.[^.]+)?)", t)
    if m and (eff := _effect_any(m.group(1).strip().rstrip("."))) is not None:
        def _upk(game, perm, _e=eff, **kw):
            ep = getattr(perm, "enchanting_player", None)
            if ep is None or kw.get("active") is not ep:
                return
            _e(game, perm.controller, perm)
        card.triggers = dict(card.triggers or {}, each_upkeep=_upk)


def _wire_aura(card, oracle):
    """Si la carta es un Aura (Enchantment — Aura), la anexa a un permanente al
    entrar (huésped propio si el efecto es bueno, rival si es malo) y aplica su
    modificador de P/T y keywords SOLO a ese huésped. Se va al cementerio (SBA)
    si el huésped deja el campo."""
    if "aura" not in {s.lower() for s in card.subtypes}:
        return
    t = re.sub(r"\s+", " ", (oracle or "")).lower()
    if re.search(r"(?:^|\. |\n)?enchant (?:player|opponent)\b", t):
        _wire_player_aura(card, t)
        return
    if "enchant creature card in a graveyard" in t:
        _wire_reanimate_aura(card, t)
        return
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
    for _mh in re.finditer(r"enchanted creature (?:gets [+-]\d+/[+-]\d+ and )?(?:has|gains) ([^.\"]+)", t):
        for name, key in _KEYWORD_WORDS + [("infect", "infect"), ("wither", "wither"), ("shroud", "shroud"),
                                           ("intimidate", "intimidate"), ("fear", "fear"),
                                           ("shadow", "shadow"), ("flanking", "flanking"),
                                           ("skulk", "skulk"), ("prowess", "prowess")]:
            if re.search(r"\b" + re.escape(name) + r"\b", _mh.group(1)):
                kws.add(key)
    if re.search(r"whenever enchanted creature deals damage, you gain that much life", t):
        kws.add("lifelink")
    _curse = bool(re.search(r"upkeep of enchanted (?:creature's|permanent's) controller, that "
                            r"player (?:loses|sacrifices|discards|mills)", t))
    bad = dp < 0 or dt < 0 or _curse or bool(re.search(
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
    # auras de BLOQUEO (Pacifism, Claustrophobia, Arrest…) y de CONTROL (Mind
    # Control): restricciones sobre el huésped que el motor consulta
    mca = re.search(r"enchanted (?:creature|permanent) can't ([a-z ,]+?)(?:\.|$| and its)", t)
    if mca:
        card.aura_no_attack = "attack" in mca.group(1)
        card.aura_no_block = "block" in mca.group(1)
    card.aura_no_activate = bool(re.search(
        r"(?:its|enchanted (?:creature|permanent)'s) activated abilities can't be activated", t))
    card.aura_no_untap = bool(re.search(
        r"enchanted (?:creature|permanent|artifact|land) doesn't untap during its "
        r"controller's untap step", t))
    card.granted_abilities = (_granted_abilities(t, "enchanted creature")
                              + _granted_abilities(t, "enchanted land"))
    if card.granted_abilities:
        bad = False
    card.aura_must_attack = bool(re.search(r"enchanted creature attacks each (?:combat|turn) if able", t))
    card.aura_no_dmg_out = bool(re.search(r"prevent all damage that would be dealt by enchanted creature", t))
    card.aura_no_combat_dmg_out = bool(re.search(
        r"prevent all combat damage that would be dealt to and dealt by enchanted creature", t))
    _mlt = re.search(r"enchanted land is an? (plains|island|swamp|mountain|forest)\b", t)
    if _mlt:
        card.aura_land_type = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R",
                               "forest": "G"}[_mlt.group(1)]
    if card.aura_no_dmg_out or card.aura_no_combat_dmg_out or getattr(card, "aura_land_type", None):
        card.tags = card.tags | {"removal"}
        bad = True
    card.aura_tap_etb = bool(re.search(
        r"when this aura enters, tap enchanted (?:creature|permanent)", t))
    card.aura_control = bool(re.search(
        r"you control enchanted (?:creature|permanent|artifact|land|planeswalker)", t))
    if any(getattr(card, f, False) for f in ("aura_no_attack", "aura_no_block",
                                             "aura_no_activate", "aura_no_untap",
                                             "aura_control")):
        ab_off = ab_off or False
        bad = True
        card.tags = card.tags | {"removal"}
    if ab_off or card.aura_pt_set:
        bad = True                     # es removal: se anexa a criatura rival
        card.tags = card.tags | {"removal"}   # la IA la valora y la juega como tal

    _mland = re.search(r"enchant (land|forest|plains|island|swamp|mountain|nonbasic land)\b", t)
    _land_sub = _mland.group(1) if _mland else None

    def _attach(game, ctrl, perm, _bad=bad, _ls=_land_sub):
        if _ls is not None:                       # aura de TIERRA (Wild Growth, Utopia Sprawl)
            lands = [pm for pm in (game.opponents(ctrl)[0].battlefield if (_bad and game.opponents(ctrl))
                                   else ctrl.battlefield)
                     if pm.card.is_land() and (_ls in ("land", "nonbasic land")
                                               or pm.has_subtype(_ls.capitalize()))]
            taken = {id(getattr(x, "enchanting", None)) for x in ctrl.battlefield}
            free = [pm for pm in lands if id(pm) not in taken] or lands
            if free:
                host = free[0]
                perm.enchanting = host
                game.log(f"{ctrl.name}: {perm.name} se anexa a {host.name}")
                _grant_to_host(game, perm, host)
            return
        if _bad:
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield if pm.is_creature()]
        else:
            pool = [pm for pm in ctrl.battlefield if pm.is_creature() and pm is not perm]
        if _bad:
            pool = [pm for pm in pool if game.can_target(ctrl, pm)] or pool
            if getattr(perm.card, "aura_no_untap", False) or getattr(perm.card, "aura_tap_etb", False):
                pool.sort(key=lambda x: x.tapped, reverse=True)
        if pool:
            host = max(pool, key=lambda x: (x.power, x.toughness))
            perm.enchanting = host
            game.log(f"{ctrl.name}: {perm.name} se anexa a {host.name}")
            _grant_to_host(game, perm, host)
            if getattr(perm.card, "aura_tap_etb", False):
                host.tapped = True
            if getattr(perm.card, "aura_control", False) and host.controller is not ctrl:
                old = host.controller
                old.battlefield.remove(host)
                host.controller = ctrl
                ctrl.battlefield.append(host)
                host.summoning_sick = True
                host.attacking = None
                perm._stolen = (host, old)
                game.log(f"{ctrl.name} toma el control de {host.name} ({perm.name})")

    # el ETB propio del Aura (scry, robar, incubate…) se ejecuta tras anexarse
    _aura_body, _ = _self_etb_body(oracle, card.name)
    _aura_etb = _effect_any(_aura_body) if (_aura_body and not re.match(
        r"(?i)\s*(?:attach|enchant|tap enchanted)", _aura_body)) else None

    def _attach_and_etb(game, ctrl, perm, _a=_attach, _e=_aura_etb):
        _a(game, ctrl, perm)
        if _e is not None:
            prev = (getattr(game, "_trigger_subject", None),
                    getattr(game, "_trigger_source", None))
            game._trigger_subject = getattr(perm, "enchanting", None)
            game._trigger_source = perm
            try:
                _e(game, ctrl, perm)
            finally:
                game._trigger_subject, game._trigger_source = prev
    card.on_etb = _attach_and_etb
    if _aura_etb is not None:
        card.aura_etb = True             # ETB propio cableado (visible para la auditoría)
    card.tags = card.tags | {"aura"}
    if card.aura_control:
        def _return_host(game, ctrl, perm, _prev=card.on_leave):
            st = getattr(perm, "_stolen", None)
            if st:
                host, old = st
                if host in host.controller.battlefield and host.controller is not old \
                        and not old.lost:
                    host.controller.battlefield.remove(host)
                    host.controller = old
                    old.battlefield.append(host)
                    host.attacking = None
                    game.log(f"{host.name} vuelve a {old.name}")
                perm._stolen = None
            if _prev:
                _prev(game, ctrl, perm)
        card.on_leave = _return_host


def _wire_equipment(card, oracle):
    """Equipo (Artifact — Equipment): habilidad 'Equip {N}' que lo anexa a una
    criatura tuya (reusa `enchanting`), y buff 'equipped creature gets +X/+X /
    has <kw>' que aplica solo a la criatura equipada. No muere si la criatura se
    va (se desanexa; ver SBA). Living weapon: crea una ficha Germen 0/0 y se equipa."""
    if "equipment" not in {s.lower() for s in card.subtypes}:
        return
    t = re.sub(r"\s+", " ", (oracle or "")).lower()
    m = re.search(r"equipped creature gets ([+-]\d+)/([+-]\d+)", t)
    dp, dt = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    kws = set()
    for name, key in _KEYWORD_WORDS:
        if "equipped creature" in t and re.search(r"\b" + re.escape(name) + r"\b", t):
            kws.add(key)
    if dp or dt:
        card.static_mod = (lambda src, target, _d=(dp, dt):
                           _d if target is getattr(src, "enchanting", None) else (0, 0))
    if kws:
        card.aura_keywords = set(kws)
    card.granted_abilities = _granted_abilities(t, "equipped creature")

    # coste de equipar: "Equip {N}" / "Equip—{N}" / "Equip {W}"
    meq = re.search(r"equip[ —–-]*((?:\{[^}]+\})+)", t)
    if meq:
        eq_cost = parse_cost(re.sub(r"[{}]", "", meq.group(1)))
    else:
        meq2 = re.search(r"equip[ —–-]+(\d+)", t)
        eq_cost = parse_cost(meq2.group(1)) if meq2 else parse_cost("2")

    def _equip_eff(game, ctrl, perm, targets=None):
        pool = [pm for pm in ctrl.battlefield if pm.is_creature()]
        if not pool:
            return
        pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)

        def _do(tgt):
            if tgt in ctrl.battlefield:
                perm.enchanting = tgt
                game.log(f"{ctrl.name}: {perm.name} se equipa a {tgt.name}")
                _grant_to_host(game, perm, tgt)
                game.sba()
        cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]
        _human_target_choice(game, ctrl, "etb_target",
                             f"Equipar {perm.name} a una criatura", cands, _do)

    equip_ab = {"cost": eq_cost, "tap": False, "sacrifice_self": False,
                "sacrifice_other": None, "pay_life": 0, "discard": 0,
                "label": "Equipar", "effect": _equip_eff, "target_spec": None,
                "target_count": 1, "is_copy_ability": False, "sorcery_speed": True}
    card.activated_abilities = tuple(card.activated_abilities or ()) + (equip_ab,)

    # Living weapon: al entrar, crea una ficha Germen 0/0 negra y se equipa a ella.
    if "living weapon" in t:
        def _living(game, ctrl, perm):
            germ = cards.make_token(game, ctrl, "Germ", 0, 0, subtypes=("Germ",))
            if germ is not None:
                perm.enchanting = germ
                game.sba()
        _prev = card.on_etb
        card.on_etb = (lambda g, c, p, _l=_living, _p=_prev:
                       (_l(g, c, p), _p(g, c, p) if _p else None))
    card.tags = card.tags | {"equipment"}


def _parse_etb_counters(oracle: str):
    """'~ enters (the battlefield) with N +1/+1 counters' (o un contador nombrado
    como charge). Devuelve {kind: n}."""
    t = re.sub(r"\s+", " ", (oracle or "")).strip()
    out = {}
    m = re.search(r"enters (?:the battlefield )?with (\w+) \+1/\+1 counters?", t, re.I)
    if m:
        if m.group(1).lower() == "x":
            out["+1/+1"] = "X"          # X contadores = el X pagado al lanzar (Hydra)
        elif (n := _count_word(m.group(1))):
            out["+1/+1"] = n
    m1 = re.search(r"enters (?:the battlefield )?with (\w+) -1/-1 counters?", t, re.I)
    if m1 and (n := _count_word(m1.group(1))):
        out["-1/-1"] = n
    m = re.search(r"enters (?:the battlefield )?with (\w+) ([a-z]+) counters?", t, re.I)
    if m and (m.group(1).lower() == "x" or (n := _count_word(m.group(1)))):
        kind = m.group(2).lower()
        if kind not in ("loyalty",):
            out.setdefault(kind, "X" if m.group(1).lower() == "x" else n)
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


def _exile_all_creatures_effect(oracle: str):
    """Barrida por EXILIO: 'Exile all creatures' (Sunfall, Farewell parcial…).
    A diferencia de 'destroy', esquiva indestructible y manda las criaturas al
    exilio (no al cementerio). Si el texto incuba X = criaturas exiliadas, crea una
    ficha Incubator aproximada (artefacto que se transforma en 0/0 con X contadores).
    Devuelve effect(g, ctrl, targets) o None."""
    t = re.sub(r"\s+", " ", (oracle or "").lower())
    mx = re.search(r"exile all creatures( you control| your opponents control| you don't control)?", t)
    if not mx:
        return None
    scope = (mx.group(1) or "").strip()
    incubate = ("incubate" in t and ("creatures exiled" in t or "incubate x" in t))
    # Mass Polymorph / Synthetic Destiny: revelar hasta N criaturas y ponerlas
    poly = bool(re.search(r"reveal cards from the top of your library until you reveal "
                          r"that many creature cards", t))
    poly_later = poly and "at the beginning of the next end step" in t

    def eff(game, ctrl, targets=None, _inc=incubate, _scope=scope):
        n = 0
        if _scope == "you control":
            who = [ctrl]
        elif _scope:
            who = game.opponents(ctrl)
        else:
            who = list(game.players)
        for pl in who:
            for pm in list(pl.battlefield):
                if not pm.is_creature():
                    continue
                if game.exile_permanent(pm, "exile all"):
                    n += 1
        game.sba()
        game.log(f"{ctrl.name}: exilia {'sus' if _scope == 'you control' else 'todas las'} "
                 f"criaturas ({n})")
        if poly and n > 0:
            def _poly(g, _n=n, _c=ctrl):
                revealed, found = [], []
                while len(found) < _n and _c.library:
                    c = _c.library.pop()
                    (found if c.is_creature() else revealed).append(c)
                for c in found:
                    g.move_to_battlefield(c, _c)
                if revealed:
                    _c.library.extend(revealed)
                    g.rng.shuffle(_c.library)
                g.log(f"{_c.name} revela hasta {_n} criatura(s): pone "
                      f"{', '.join(c.name for c in found) or 'ninguna'} en el campo")
            if poly_later:
                game.delayed_end.append(_poly)
            else:
                _poly(game)
        if _inc and n > 0:
            # Incubate X: ficha Incubator (artefacto) con X contadores +1/+1 y
            # "{2}: transformar" en una 0/0 Phyrexian. La aproximamos como un
            # artefacto-criatura durmiente X/X que entra sin poder atacar aún.
            tok = cards.make_token(game, ctrl, "Incubator", 0, 0,
                                   subtypes=("Phyrexian",), counters=n)
            if tok is not None:
                tok.card.types = set(tok.card.types) | {"artifact"}
            game.log(f"{ctrl.name}: incuba X={n} (ficha {n}/{n})")
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
    # "landfall — … return <esta carta> from your graveyard to the battlefield"
    # (Bloodghast: redacción actual, sin "in your graveyard")
    self_ret = re.search(r"(?:landfall\s*[—–-]|whenever a land[^.]*enters)[^.]*"
                         r"return (?:this card|~|it|this creature|[a-z][\w' ,]+?) "
                         r"from your graveyard to the battlefield", t)
    if self_ret or ("in your graveyard" in t and "return" in t and
                    ("landfall" in t or re.search(r"land[^.]*enters", t))):
        def _ret(game, player, card, **_kw):
            if card in player.graveyard:
                player.graveyard.remove(card)
                game.move_to_battlefield(card, player)
                game.log(f"{card.name} vuelve del cementerio al campo (landfall)")
        out["landfall"] = _ret
    return out


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}


def _saga_candidates(game, ctrl, spec):
    """Objetivos legales (etiqueta, objeto) para un capítulo de Saga con `spec`,
    ordenados de mejor a peor (el bot toma los primeros)."""
    def cl(pm):
        return (f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}"
                if pm.is_creature() else f"{pm.name} · {pm.controller.name}")
    if spec == "own_creature":
        pool = sorted(ctrl.creatures(), key=lambda p: (p.power + p.toughness), reverse=True)
        return [(f"{p.name} {p.power}/{p.toughness}", p) for p in pool]
    if spec == "opp_creature":
        pool = sorted(game.legal_creature_targets(ctrl),
                      key=lambda p: (p.power, p.toughness), reverse=True)
        return [(cl(p), p) for p in pool]
    if spec == "opp_player":
        return [(f"{o.name} ({o.life} de vida)", o)
                for o in sorted(game.targetable_opponents(ctrl), key=lambda o: o.life)]
    if spec == "own_perm":
        return [(cl(p), p) for p in ctrl.battlefield]
    typ_pred = {
        "any_artifact": lambda p: "artifact" in p.card.types,
        "any_enchantment": lambda p: "enchantment" in p.card.types,
        "any_art_ench": lambda p: bool(p.card.types & {"artifact", "enchantment"}),
        "any_planeswalker": lambda p: "planeswalker" in p.card.types,
        "any_nonland": lambda p: not p.card.is_land(),
        "any_perm": lambda p: True,
    }
    pred = typ_pred.get(spec)
    if pred:
        pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield
                if pred(pm) and game.can_target(ctrl, pm)]
        pool.sort(key=lambda p: (p.is_creature(), p.power if p.is_creature() else 0),
                  reverse=True)
        return [(cl(p), p) for p in pool]
    return []


def _saga_run_targeted(game, ctrl, feff, spec, count):
    """Ejecuta el efecto dirigido de un capítulo. El HUMANO elige objetivo (modal,
    hasta `count`, opcional); el bot toma automáticamente los mejores (determinista)."""
    n = max(1, count or 1)
    cands = _saga_candidates(game, ctrl, spec)
    if not cands:
        return
    if ctrl is getattr(game, "interactive_human", None):
        st = {"left": n}

        def _prompt():
            if st["left"] <= 0:
                return
            pool = _saga_candidates(game, ctrl, spec)   # recomputar: el tablero cambió
            if not pool:
                return

            def _do(obj, _f=feff):
                _f(game, ctrl, [obj])
                st["left"] -= 1
                _prompt()                               # encadena la siguiente elección
            _human_target_choice(
                game, ctrl, "etb_target",
                f"Elegí objetivo ({st['left']} restante(s), o ninguno)",
                pool, _do, allow_none=True)
        _prompt()
    else:
        feff(game, ctrl, [obj for _l, obj in cands[:n]])


def _chapter_effect(body: str):
    """Efecto de un capítulo de Saga. Primero el parser de monto (que ya abre UI de
    objetivo para remoción puntual); si no, el parser por fragmento / dirigido. Los
    efectos con objetivo abren el modal para el humano y auto-apuntan para el bot."""
    eff = _generic_amount_effect(body)
    if eff is not None:
        return eff
    # "you may <efecto>" (sin coste): el efecto (bots: casi siempre conviene)
    _mm = re.match(r"(?i)\s*you may (?!pay|sacrifice|discard|exile a card|tap|return a land|"
                   r"have)(.+)$", body or "")
    if _mm and not re.search(r"\bif you do\b|\botherwise\b", body, re.I):
        _inner = _chapter_effect(_mm.group(1))
        if _inner is not None:
            return _inner
    # texto con condición ("if you do", "otherwise") que el genérico no resolvió:
    # el parser por fragmento tomaría una parte y aplicaría el efecto SIEMPRE
    if re.search(r"\bif you do\b|\botherwise\b|\bif you don't\b", body or "", re.I):
        return None
    for parser in (_fragment_effect, _targeted_special):
        res = parser(body)
        if res and res[0] is not None:
            feff, spec, count = res
            if spec is None:
                return (lambda g, ctrl, *_a, _f=feff: _f(g, ctrl, []))

            def run(g, ctrl, *_a, _f=feff, _s=spec, _n=count):
                _saga_run_targeted(g, ctrl, _f, _s, _n)
            return run
    return None


_CUR_NAMES: list = []          # pila de nombres de la carta que se está armando


def _devotion(p, cols):
    n = 0
    for pm in p.battlefield:
        for pp in (getattr(pm.card.cost, "pips", None) or ()):
            if set(str(pp).upper()) & cols:
                n += 1
    return n


def _count21(phrase):
    """Cantidad variable RELATIVA a la fuente / sujeto / hechizo del disparo:
    f(game, ctrl) -> int. Cae a _count_fn para las globales."""
    p = re.sub(r"\s+", " ", (phrase or "").lower().strip().rstrip("."))

    def _src(g, c):
        return _cond_src(g, c)

    def _subj(g):
        sj = getattr(g, "_trigger_subject", None)
        return sj if sj is not None and hasattr(sj, "card") else None

    def _spell(g):
        k = getattr(g, "_trigger_kw", None) or {}
        c = k.get("card") or getattr(k.get("spell"), "source", None)
        return c if c is not None and hasattr(c, "types") else None
    if p in ("this creature's power", "~'s power", "its power", "this vehicle's power", "his power", "her power"):
        return lambda g, c: max(0, getattr(_src(g, c), "power", 0) or 0)
    if p in ("this creature's toughness", "~'s toughness", "its toughness"):
        return lambda g, c: max(0, getattr(_src(g, c), "toughness", 0) or 0)
    if p in ("that creature's power", "the sacrificed creature's power"):
        return lambda g, c: max(0, getattr(_subj(g), "power", 0) or 0)
    if p in ("that creature's mana value",):
        return lambda g, c: (_subj(g).card.cost.cmc if _subj(g) is not None and _subj(g).card.cost else 0)
    if p in ("that spell's mana value", "the mana value of that spell", "that card's mana value"):
        return lambda g, c: (_spell(g).cost.cmc if _spell(g) is not None and _spell(g).cost else 0)
    if p in ("the amount of mana spent to cast this spell", "the amount of mana spent to cast it"):
        return lambda g, c: ((getattr(g, "_resolving_card", None) or getattr(getattr(_src(g, c), "card", None), "cost", None)
                              and 0) or (getattr(getattr(g, "_resolving_card", None), "cost", None).cmc
                                         if getattr(getattr(g, "_resolving_card", None), "cost", None) else 0))
    m = re.fullmatch(r"the number of (\+1/\+1|[a-z]+) counters on (?:~|this creature|it|this enchantment|this artifact)", p)
    if m:
        return lambda g, c, _k=m.group(1): (_src(g, c).counters.get(_k, 0) if _src(g, c) is not None else 0)
    m = re.fullmatch(r"your devotion to (white|blue|black|red|green)(?: and (white|blue|black|red|green))?", p)
    if m:
        cols = {_COLOR_W[x] for x in (m.group(1), m.group(2)) if x}
        return lambda g, c, _c=cols: _devotion(c, _c)
    if p in ("the number of colors among permanents you control", "the number of colors among permanents you control"):
        return lambda g, c: len(set().union(*[_perm_colors(pm) for pm in c.battlefield]) if c.battlefield else set())
    if p in ("the number of attacking creatures", "the number of attacking creatures you control"):
        return lambda g, c: sum(1 for pm in c.creatures() if pm.attacking is not None)
    if p in ("the amount of life you gained this turn", "the amount of life you've gained this turn"):
        return lambda g, c: (getattr(c, "gained_amt", (None, 0))[1] if getattr(c, "gained_amt", (None,))[0] == g.turn else 0)
    if p == "the number of experience counters you have":
        return lambda g, c: getattr(c, "experience", 0)
    if p == "your speed":
        return lambda g, c: getattr(c, "speed", 0)
    if p in ("the number of spells you've cast this turn", "the number of spells you have cast this turn"):
        return lambda g, c: getattr(c, "spells_cast_turn", 0)
    m = re.fullmatch(r"the number of (\+1/\+1|[a-z]+) counters on (?:it|that creature)", p)
    if m:
        def _subj_ctr(g, c, _k=m.group(1)):
            sj = getattr(g, "_trigger_subject", None)
            pm = sj if sj is not None and hasattr(sj, "counters") else _cond_src(g, c)
            return pm.counters.get(_k, 0) if pm is not None else 0
        return _subj_ctr
    if p in ("its power", "that creature's power") and False:
        return None
    if p == "the number of creatures in your party":
        def _party(g, c):
            used, n = set(), 0
            for pm in c.creatures():
                for k in ("cleric", "rogue", "warrior", "wizard"):
                    if k not in used and pm.has_subtype(k):
                        used.add(k)
                        n += 1
                        break
            return n
        return _party
    if p == "the greatest mana value among permanents you control":
        return lambda g, c: max([pm.card.cost.cmc for pm in c.battlefield if pm.card.cost] or [0])
    if p in ("the greatest mana value among cards in your graveyard",):
        return lambda g, c: max([x.cost.cmc for x in c.graveyard if x.cost] or [0])
    if p in ("the greatest power among creature cards in your graveyard",):
        return lambda g, c: max([x.power or 0 for x in c.graveyard if x.is_creature()] or [0])
    if p == "the greatest power among creatures you control":
        return lambda g, c: max([pm.power for pm in c.creatures()] or [0])
    if p in ("the number of different mana values among cards in your graveyard",
             "the number of mana values among cards in your graveyard"):
        return lambda g, c: len({x.cost.cmc if x.cost else 0 for x in c.graveyard})
    if p in ("the number of cards in their hand", "the number of cards in that player's hand"):
        return lambda g, c: len(getattr(_that_player(g, c), "hand", []) or [])
    if p == "the number of historic permanents you control":
        return lambda g, c: sum(1 for pm in c.battlefield if "artifact" in pm.card.types
                                or "legendary" in pm.card.supertypes or pm.has_subtype("saga"))
    m = re.fullmatch(r"the number of (white|blue|black|red|green) creatures on the battlefield", p)
    if m:
        return lambda g, c, _k=_COLOR_W[m.group(1)]: sum(1 for pl in g.players for pm in pl.creatures()
                                                         if _k in _perm_colors(pm))
    if p == "the number of untapped lands they control":
        return lambda g, c: sum(1 for pm in (getattr(_that_player(g, c), "battlefield", []) or [])
                                if pm.card.is_land() and not pm.tapped)
    m = re.fullmatch(r"(\w+) plus (.+)", p)
    if m and _count_word(m.group(1)) is not None and (f2 := _count21(m.group(2))) is not None:
        return lambda g, c, _k=_count_word(m.group(1)), _f=f2: _k + _f(g, c)
    return _count_fn(p)


_XSUB_CACHE = {}


def _where_x_effect(body):
    """'<efecto con X>, where X is <cantidad>' -> se evalúa X al resolver y se
    parsea el efecto con el número (cacheado por valor)."""
    m = re.match(r"(?is)\s*(.*?\bx\b.*?),? where x is ([^.]+?)(?:\.|$)\s*(.*)$", body or "")
    if not m or m.group(3).strip():
        return None
    f = _count21(m.group(2))
    if f is None:
        return None
    tpl = m.group(1).strip()
    if _CUR_NAMES:
        for nm in sorted(_CUR_NAMES[-1], key=len, reverse=True):
            if len(nm) >= 3:
                tpl = re.sub(r"(?<![\w'])" + re.escape(nm) + r"(?![\w'])", "~", tpl, flags=re.I)

    def _sub(n):
        t2 = re.sub(r"(?i)([+-])x/([+-])x", lambda mm: f"{mm.group(1)}{n}/{mm.group(2)}{n}", tpl)
        t2 = re.sub(r"(?i)([+-])x/([+-])0", lambda mm: f"{mm.group(1)}{n}/{mm.group(2)}0", t2)
        t2 = re.sub(r"(?i)([+-])0/([+-])x", lambda mm: f"{mm.group(1)}0/{mm.group(2)}{n}", t2)
        return re.sub(r"(?i)\bx\b", str(n), t2)
    probe = _sub(2)
    if re.search(r"(?i)\bx\b", probe) or _chapter_effect(probe) is None:
        return None

    def eff_where_x(game, ctrl, *a, _f=f, _t=tpl, **kw):
        try:
            n = max(0, int(_f(game, ctrl)))
        except Exception:  # noqa: BLE001
            n = 0
        if n <= 0:
            return
        key = (_t, n)
        e = _XSUB_CACHE.get(key)
        if e is None:
            e = _XSUB_CACHE[key] = _chapter_effect(_sub(n)) or (lambda *_x, **_k: None)
        e(game, ctrl, *a)
    return eff_where_x


def _effect_any(body: str):
    """Efecto de un DISPARO / ENTRADA / capítulo: el parser genérico y, si no lo
    reconoce, el dirigido con objetivo elegido al resolver (humano: modal; bot:
    el mejor). Antes los disparos solo aceptaban efectos sin objetivo: 'when this
    creature enters, return target nonland permanent…' quedaba sin efecto."""
    eff = _chapter_effect(body)
    if eff is None and _CUR_NAMES and body:
        # "put a +1/+1 counter on Elenda" / "Kozilek deals 3 damage…": el nombre
        # propio como "~" (lo que entienden los atómicos)
        b2 = body
        for nm in sorted(_CUR_NAMES[-1], key=len, reverse=True):
            if len(nm) >= 3:
                b2 = re.sub(r"(?<![\w'])" + re.escape(nm) + r"(?![\w'])", "~", b2, flags=re.I)
        if b2 != body:
            eff = _chapter_effect(b2)
    if eff is None and body and re.search(r"(?i)where x is", body):
        eff = _where_x_effect(body)
    if eff is None and body:
        mo = re.match(r"(?is)\s*(.+?)\.?\s*(?:this ability triggers only once each turn|do this only once each turn)\.?\s*$",
                      body)
        if mo and (inner := _effect_any(mo.group(1).strip() + ".")) is not None:
            def eff_once(game, ctrl, *a, _e=inner, **kw):
                src = _src_perm(game, a)
                key = id(src) if src is not None else id(ctrl)
                done = getattr(game, "_once21", None)
                if done is None:
                    done = game._once21 = {}
                if done.get((key, id(_e))) == game.turn:
                    return
                done[(key, id(_e))] = game.turn
                _e(game, ctrl, *a)
            eff = eff_once
    return eff


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
        eff = _chapter_effect(body)
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
                         allow_none=False, on_none=None):
    """Elección de objetivo genérica para efectos (p. ej. ETB dirigidos).
    `options` = lista de (etiqueta, objeto). El HUMANO elige vía pending_choice
    (mismo modal que scry/revelar); los bots aplican al primero (auto)."""
    if not options:
        return
    if ctrl is getattr(game, "interactive_human", None):
        objs = [o for _lbl, o in options]

        def _apply(idx, _objs=objs, _fn=apply_one, _none=on_none):
            if idx is not None and 0 <= idx < len(_objs):
                _fn(_objs[idx])
            elif _none is not None:
                _none()

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


def _pick_opponent(game, ctrl, apply_one):
    """Elegir a QUÉ rival afecta un efecto 'target player/opponent'. El humano lo
    elige (pending_choice); el bot va al de menos vida. Con un solo rival, directo."""
    opps = game.opponents(ctrl)
    if not opps:
        return
    if len(opps) == 1:
        apply_one(opps[0])
        return
    if ctrl is getattr(game, "interactive_human", None):
        cands = [(f"{o.name} ({o.life} de vida)", o) for o in opps]
        _human_target_choice(game, ctrl, "player_target",
                             "Elegí a qué rival", cands, apply_one)
    else:
        apply_one(min(opps, key=lambda o: o.life))


def _shuffle_graveyard_into_library(game, ctrl):
    """'Shuffle any number of target cards from your graveyard into your library':
    multi-selector. El humano elige de a una (puede parar con 'ninguna más'); el
    bot baraja de vuelta sus cartas NO tierra (valor: re-dibujarlas)."""
    if not ctrl.graveyard:
        return

    def _do(card):
        if card in ctrl.graveyard:
            ctrl.graveyard.remove(card)
            ctrl.library.append(card)
            game.rng.shuffle(ctrl.library)
            game.log(f"{ctrl.name} baraja {card.name} en su biblioteca")

    if ctrl is getattr(game, "interactive_human", None):
        def _prompt():
            pool = list(ctrl.graveyard)
            if not pool:
                return

            def _pick(card):
                _do(card)
                _prompt()                     # seguir eligiendo (any number)
            _pick_card_from_zone(
                game, ctrl, pool, _pick,
                "Elegí cartas del cementerio para barajar en tu biblioteca "
                "(una por una, o 'ninguna más')", kind="gy_shuffle", allow_none=True)
        _prompt()
    else:
        for c in [c for c in list(ctrl.graveyard) if not c.is_land()]:
            _do(c)


def _pick_card_from_zone(game, ctrl, cards_list, apply_one, prompt, kind="reanimate",
                         allow_none=False, ok_fn=None):
    """Elegir UNA carta de una zona (cementerio/exilio) para recuperar/revivir.
    El humano ve las cartas (imagen + nombre) en el modal y elige; el bot toma la
    primera elegible (el que llama la lista ordenada de mejor a peor).

    `ok_fn(card)->bool` marca qué cartas son ELEGIBLES. Si se pasa, la lista puede
    incluir cartas no elegibles (se muestran en gris, deshabilitadas): así el humano
    ve TODO el cementerio y entiende por qué una carta no se puede elegir. El humano
    nunca puede confirmar una no elegible (el botón va deshabilitado y `_apply` igual
    la ignora)."""
    cands = list(cards_list)
    if not cands:
        return

    def _ok(c):
        return True if ok_fn is None else bool(ok_fn(c))

    selectable = [c for c in cands if _ok(c)]
    if ctrl is getattr(game, "interactive_human", None):
        # Red de seguridad: nunca abrir un modal donde NADA se puede elegir (y sin
        # "ninguna"), porque dejaría al humano sin forma de avanzar -> juego congelado.
        # Si no hay nada elegible, la habilidad simplemente no hace nada.
        if not selectable and not allow_none:
            return
        def _apply(idx, _objs=cands, _fn=apply_one, _okf=_ok):
            if idx is not None and 0 <= idx < len(_objs) and _okf(_objs[idx]):
                _fn(_objs[idx])
        game.pending_choice = {
            "kind": kind,
            "prompt": prompt,
            "options": [{"i": i, "name": c.name, "is_land": c.is_land(), "ok": _ok(c)}
                        for i, c in enumerate(cands)],
            "allow_none": bool(allow_none),
            "_apply": _apply,
        }
    elif selectable:
        apply_one(selectable[0])


def _route_choice(game, player, prompt_fn, auto_fn):
    """Enruta una decisión de `player`:
      - es el humano y es SU turno -> `prompt_fn()` arma el pending_choice ya (la pila
        del turno del humano pausa bien);
      - es el humano pero es el turno de un BOT -> se encola `prompt_fn` en
        game.choice_queue (resolve_stack no pausa en turno de bot; la capa interactiva
        drena la cola al volver el control al humano);
      - es un bot -> `auto_fn()` resuelve solo."""
    hu = getattr(game, "interactive_human", None)
    if player is not hu or hu is None:
        auto_fn()
        return
    try:
        own_turn = game.ap() is hu
    except Exception:
        own_turn = False
    if own_turn:
        prompt_fn()
    else:
        game.choice_queue.append(prompt_fn)


def _human_or_auto_sacrifice(game, player, prompt="Elegí una criatura para sacrificar",
                             pool=None):
    """El jugador `player` sacrifica una criatura: humano elige (modal), bot la más débil."""
    cr = list(pool) if pool is not None else list(player.creatures())
    if not cr:
        return
    cr.sort(key=lambda x: (x.power, x.toughness))   # auto: la más débil

    def _do(pm):
        if pm in pm.controller.battlefield:
            game.to_graveyard(pm, "sacrificio forzado")
            game.log(f"{pm.controller.name} sacrifica {pm.name}")
            game.sba()

    def _prompt():
        cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm)
                 for pm in player.creatures()]
        if cands:
            _human_target_choice(game, player, "etb_target", prompt, cands, _do)
    _route_choice(game, player, _prompt, lambda: _do(cr[0]))


def _human_or_auto_discard(game, player, n):
    """El jugador `player` descarta N cartas: humano elige (modal, una a una), bot auto."""
    n = len(player.hand) if n < 0 else n

    def _prompt_one(remaining):
        if remaining <= 0 or not player.hand:
            return

        def _apply(idx, _r=remaining):
            if idx is not None and 0 <= idx < len(player.hand):
                c = player.hand.pop(idx)
                player.graveyard.append(c)
                game.emit("to_graveyard", player=player, card=c)
                game.log(f"{player.name} descarta {c.name}")
            _prompt_one(_r - 1)                     # encadena la próxima
        game.pending_choice = {
            "kind": "discard",
            "prompt": f"Descartá una carta ({remaining} restante(s)).",
            "options": [{"i": j, "name": c.name, "is_land": c.is_land()}
                        for j, c in enumerate(player.hand)],
            "allow_none": False, "_apply": _apply,
        }

    def _auto():
        rem = n
        while rem > 0 and player.hand:
            if player.policy and hasattr(player.policy, "choose_discard"):
                c = player.policy.choose_discard(game, player)
            else:
                c = player.hand[-1]
            player.hand.remove(c)
            player.graveyard.append(c)
            game.emit("to_graveyard", player=player, card=c)
            rem -= 1
    _route_choice(game, player, lambda: _prompt_one(n), _auto)


def _count_word(w):
    """Palabra o dígito -> int, o None."""
    w = (w or "").strip().lower()
    if w in _NUMWORD:
        return _NUMWORD[w]
    try:
        return int(w)
    except ValueError:
        return None


_LOY_LINE = re.compile(r"^\s*\[?([+−\-]?\d+)\]?\s*:\s*(.+?)\s*$")  # acepta "+1:" y "[+1]:"


def _loyalty_effect(text: str):
    """Efecto APROXIMADO de una habilidad de lealtad, deducido de su texto.
    Cubre los patrones comunes (daño, robo, vida, ficha). Si no reconoce nada,
    devuelve None: la habilidad solo cambia la lealtad (mejor que no existir)."""
    t = re.sub(r"\s+", " ", (text or "").lower())

    # Scry N (p. ej. Nissa +2): mira el tope y decide dejar/mandar al fondo.
    ms = re.search(r"\bscry (\w+)", t)
    if ms and (k := _count_word(ms.group(1))):
        _scry = _scry_surveil_effect(k, False)
        def eff(game, ctrl, perm, _s=_scry):
            _s(game, ctrl)
        return eff

    # "Look at the top card of your library. If it's a land (or a creature with
    # mana value <= loyalty counters on this), you may put it onto the battlefield."
    if re.search(r"look at the top card of your library", t) and "onto the battlefield" in t:
        _allow_land = "land card" in t
        _cre_cap = "creature card with mana value" in t

        def eff(game, ctrl, perm, _land=_allow_land, _cap=_cre_cap):
            if not ctrl.library:
                return
            top = ctrl.library[-1]                       # tope = final de la lista
            loy = perm.counters.get("loyalty", 0)
            cmv = top.cost.cmc if getattr(top, "cost", None) else 0
            ok = (_land and top.is_land()) or (top.is_creature()
                                               and (not _cap or cmv <= loy))
            if not ok:
                game.log(f"{ctrl.name} mira el tope ({top.name}): no es elegible")
                return

            def _put(g, c):
                if ctrl.library and ctrl.library[-1] is top:
                    ctrl.library.pop()
                    g.move_to_battlefield(top, ctrl)
                    g.log(f"{ctrl.name} pone {top.name} desde el tope al campo")
            game.may(ctrl, f"¿Poner {top.name} (del tope) en el campo?", _put)
        return eff

    m = re.search(r"deals? (\w+) damage to each opponent", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, perm, _n=n):
            for o in game.opponents(ctrl):
                game.deal_damage(perm, o, _n)
        return eff

    m = re.search(r"deals? (\w+) damage", t)
    # daño a "target creature/planeswalker": lo resuelve el parser dirigido de abajo
    # (antes el −3 de Chandra le pegaba 4 al rival de menos vida)
    _to_perm = re.search(r"damage to (?:up to \w+ )?(?:another )?target "
                         r"(?:creature|planeswalker)(?! or player)", t)
    if m and "each opponent" not in t and not _to_perm and (n := _count_word(m.group(1))):
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

    # animar tierras: "untap up to N target lands you control. They become X/Y
    # <Sub> creatures with <kw> until end of turn. They're still lands." (Nissa…)
    ma = re.search(r"up to (\w+) target lands?.{0,80}?become (\d+)/(\d+) "
                   r"(\w+) creatures?(?: with ([\w, ]+?))?(?: until end of turn|\.)", t)
    if ma and _count_word(ma.group(1)):
        n = _count_word(ma.group(1))
        px, ty = int(ma.group(2)), int(ma.group(3))
        sub = ma.group(4).capitalize()
        kws = [v for pat, v in _TOKEN_KEYWORDS if re.search(pat, ma.group(5) or "")]
        do_untap = "untap" in t

        def eff(game, ctrl, perm, _n=n, _p=px, _tf=ty, _s=sub, _k=kws, _u=do_untap):
            _animate_lands(game, ctrl, _n, _p, _tf, _s, _k, _u)
        return eff

    # efectos con objetivo (destruir / exiliar / rebote / -X/-X / tap / poner
    # contadores): reusar el parser de fragmentos y AUTO-elegir el objetivo, para
    # que la habilidad de lealtad haga algo real en vez de solo mover la lealtad.
    frag, spec, count = _fragment_effect(text or "")
    if frag is not None and spec is not None:
        def eff(game, ctrl, perm, _f=frag, _spec=spec, _n=count):
            _choose_loyalty_targets(game, ctrl, _spec, _n,
                                    lambda tgs: _f(game, ctrl, tgs))
        return eff

    return None


def _choose_loyalty_targets(game, ctrl, spec, n, apply_targets):
    """Habilidad de lealtad dirigida: el humano (en su turno) elige el objetivo en un
    modal; el bot usa el objetivo automático. Objetivo único (n<=1); si n>1, auto."""
    auto = _auto_loyalty_targets(game, ctrl, spec, n)
    if spec == "opp_creature":
        pool = list(game.legal_creature_targets(ctrl))
    elif spec == "own_creature":
        pool = list(ctrl.creatures())
    elif spec == "opp_player":
        pool = list(game.targetable_opponents(ctrl))
    else:
        pool = []
    if not pool or (n or 1) > 1:
        apply_targets(auto)
        return

    def _prompt():
        if spec == "opp_player":
            cands = [(o.name, o) for o in pool]
        else:
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

        def _do(obj):
            apply_targets([obj])
        _human_target_choice(game, ctrl, "etb_target",
                             "Elegí el objetivo de la habilidad de lealtad", cands, _do)
    _route_choice(game, ctrl, _prompt, lambda: apply_targets(auto))


def _animate_lands(game, ctrl, n, power, tough, sub, kws, do_untap):
    """Convierte hasta `n` tierras propias en criaturas X/Y hasta el fin del turno
    (temporal: temp_creature + temp_pt + temp_subtypes + temp_keywords). El humano
    elige cuáles (modal, encadenado); el bot toma las primeras. Opcionalmente las
    endereza. Siguen siendo tierras."""
    def _do(land):
        if do_untap:
            land.tapped = False
        land.temp_creature = True
        land.temp_pt = [power, tough]            # base de tierra es 0/0 -> X/Y
        if sub:
            land.temp_subtypes.add(sub)
        for k in kws:
            land.temp_keywords.add(k)
        game.log(f"{land.name} se vuelve una criatura {power}/{tough} {sub}")

    lands = [pm for pm in ctrl.battlefield if pm.card.is_land()]
    if not lands:
        return
    if ctrl is getattr(game, "interactive_human", None):
        st = {"left": max(1, n)}

        def _prompt():
            if st["left"] <= 0:
                return
            pool = [pm for pm in ctrl.battlefield if pm.card.is_land()
                    and not pm.temp_creature]
            if not pool:
                return
            cands = [(pm.name + (" (girada)" if pm.tapped else ""), pm) for pm in pool]

            def _pick(land):
                _do(land)
                st["left"] -= 1
                _prompt()
            _human_target_choice(
                game, ctrl, "etb_target",
                f"Elegí una tierra para animar ({st['left']} restante(s), o ninguna)",
                cands, _pick, allow_none=True)
        _route_choice(game, ctrl, _prompt, lambda: [_do(l) for l in lands[:max(1, n)]])
    else:
        # bot: prioriza tierras ya enderezadas/sin animar, hasta n
        picks = sorted(lands, key=lambda pm: pm.tapped)[:max(1, n)]
        for l in picks:
            _do(l)


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
        opps = game.targetable_opponents(ctrl)
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
            if not _fs:                           # "whenever you scry / surveil"
                game.emit(kind, player=ctrl)

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
                "card_obj": c,
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
    if w == "nonland":
        return (lambda c: not c.is_land()), "no tierra"
    # subtipo ("a Plains card", "an Aura card", "a Dragon card"): antes tomaba cualquiera
    mw = re.fullmatch(r"(?:basic )?([a-z][a-z'-]+)", w)
    if mw and mw.group(1) not in ("card", "permanent", "the", "any", "other"):
        _st = mw.group(1)
        return (lambda c, _s=_st: any(x.lower() == _s for x in c.subtypes)), _st
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
                           label="una carta", tapped=False, to_top=False):
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
                    elif not to_top:
                        ctrl.hand.append(pick)
                    where = ("al campo" if to_battlefield else
                             "arriba de la biblioteca" if to_top else "a la mano")
                    game.log(f"{ctrl.name} busca y toma {pick.name} {where}")
                    if to_top:              # barajar y LUEGO ponerla arriba (Vampiric)
                        game.rng.shuffle(ctrl.library)
                        ctrl.library.append(pick)
                        return
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
                "card_obj": top,
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


def _each_count_fn(phrase: str):
    """'creature on the battlefield' / 'artifact you control' / 'opponent you have'
    (lo que sigue a 'for each') -> f(game, ctrl) o None."""
    p = (phrase or "").lower().strip()
    if p in ("color among permanents you control", "colors among permanents you control"):
        return lambda g, c: len({x for pm in c.battlefield
                                 for pp in (getattr(pm.card.cost, "pips", None) or ()) for x in str(pp).upper()
                                 if x in "WUBRG"})
    if re.fullmatch(r"basic land types? among lands you control", p):
        return _count_fn(p)
    if re.match(r"opponents? you have", p):
        return lambda g, c: len(g.opponents(c))
    if re.match(r"cards? in your hand", p):
        return lambda g, c: len(c.hand)
    if p in ("creature that died this turn", "creature that died this turn"):
        return lambda g, c: (getattr(g, "deaths_count", 0) if getattr(g, "_deaths_turn", None) == g.turn else 0)
    if p == "attacking creature":
        return lambda g, c: sum(1 for pl in g.players for pm in pl.creatures() if pm.attacking is not None)
    if p == "creature that attacked this turn":
        return lambda g, c: sum(1 for pl in g.players for pm in pl.creatures()
                                if getattr(pm, "attacked_turn", None) == g.turn)
    if re.fullmatch(r"instant and(?:/or)? sorcery cards? in your graveyard", p):
        return lambda g, c: sum(1 for x in c.graveyard if {"instant", "sorcery"} & x.types)
    mgy = re.fullmatch(r"(creature|artifact|land|enchantment|instant|sorcery) cards? in your "
                       r"graveyard", p)
    if mgy:
        return lambda g, c, _k=mgy.group(1): sum(1 for x in c.graveyard if _k in x.types)
    if re.fullmatch(r"creatures? in your party", p):
        def _party(g, c):
            used, n = set(), 0
            for cl in ("Cleric", "Rogue", "Warrior", "Wizard"):
                for pm in c.creatures():
                    if pm.uid not in used and pm.has_subtype(cl):
                        used.add(pm.uid)
                        n += 1
                        break
            return n
        return _party
    mk = re.match(r"creatures? with ([a-z ]+?) (on the battlefield|you control|"
                  r"your opponents control)$", p)
    if mk and mk.group(1).replace(" ", "_") in KEYWORDS:
        _kw = mk.group(1).replace(" ", "_")

        def _cnt_kw(g, c, _k=_kw, _w=mk.group(2)):
            pls = ([c] if _w == "you control" else
                   g.opponents(c) if "opponents" in _w else g.players)
            return sum(1 for pl in pls for pm in pl.battlefield
                       if pm.is_creature() and pm.has(_k))
        return _cnt_kw
    m = re.match(r"(creature|artifact|enchantment|land|planeswalker|permanent)s? "
                 r"(on the battlefield|you control|your opponents control)$", p)
    if not m:
        return None
    kind, whose = m.group(1), m.group(2)

    def _cnt(g, c, _k=kind, _w=whose):
        pls = ([c] if _w == "you control" else
               g.opponents(c) if "opponents" in _w else g.players)
        return sum(1 for pl in pls for pm in pl.battlefield
                   if _k == "permanent" or (pm.is_creature() if _k == "creature"
                                            else _k in pm.card.types))
    return _cnt


def _count_fn(phrase: str):
    """Devuelve una función f(game, ctrl) -> int para expresiones de cantidad
    variable comunes ('the number of creatures you control', 'cards in your hand',
    'Elves you control', 'Swamps you control'…) o None si no se reconoce."""
    p = (phrase or "").lower().strip()
    if p in ("color among permanents you control", "colors among permanents you control"):
        return _each_count_fn(p)
    if re.fullmatch(r"(creature|artifact|enchantment|land|planeswalker)s? on the battlefield", p):
        return _count_fn("the number of " + p)
    if p in ("the total power of creatures you control", "total power of creatures you control"):
        return lambda g, c: sum(max(0, pm.power) for pm in c.creatures())
    m2 = re.match(r"twice (.+)$", p)
    if m2 and (f2 := _count_fn(m2.group(1))) is not None:
        return lambda g, c, _f=f2: 2 * _f(g, c)
    if p in ("your life total", "your life"):
        return lambda g, c: max(0, c.life)
    # domain: tipos de tierra básica entre tus tierras
    if re.fullmatch(r"(?:the number of )?basic land types? among lands you control", p):
        def _dom(g, c):
            subs = set()
            for pm in c.battlefield:
                if pm.card.is_land():
                    for b in ("plains", "island", "swamp", "mountain", "forest"):
                        if pm.has_subtype(b) or pm.name.lower() == b:
                            subs.add(b)
            return len(subs)
        return _dom

    # cartas en cementerios: "(the number of) [creature|land|instant and sorcery|
    # artifact] cards in your/all/your opponents' graveyard(s)"
    mg = re.match(r"(?:the number of )?(?:(other )?([a-z]+(?: and [a-z]+)?) )?cards? in "
                  r"(your|all|your opponents'|each opponent's) graveyards?$", p)
    if mg:
        kinds = [k for k in re.split(r" and ", mg.group(2) or "") if k]
        whose = mg.group(3)

        def _gy(g, c, _k=tuple(kinds), _w=whose):
            pls = ([c] if _w == "your" else g.players if _w == "all" else g.opponents(c))
            return sum(1 for pl in pls for x in pl.graveyard
                       if not _k or any(k in x.types or (k == "permanent" and
                                        x.types & {"creature", "artifact", "enchantment",
                                                   "land", "planeswalker"}) for k in _k))
        return _gy
    if re.match(r"(?:the number of )?card types among cards in all graveyards$", p):
        _CT = ("artifact", "battle", "creature", "enchantment", "instant", "land",
               "planeswalker", "sorcery", "kindred")
        return lambda g, c: len({t for pl in g.players for x in pl.graveyard
                                 for t in x.types if t in _CT})
    mo = re.match(r"(?:the number of )?(nonbasic )?([a-z]+?)s? your opponents control$", p)
    if mo:
        nb, kind = bool(mo.group(1)), mo.group(2)
        return (lambda g, c, _k=kind, _nb=nb: sum(
            1 for o in g.opponents(c) for pm in o.battlefield
            if (_k in pm.card.types or (_k == "creature" and pm.is_creature()))
            and (not _nb or "basic" not in pm.card.supertypes)))
    mcol = re.match(r"(?:the number of )?(white|blue|black|red|green) permanents you control$", p)
    if mcol:
        col = {"white": W, "blue": U, "black": B, "red": R, "green": G}[mcol.group(1)]
        return lambda g, c, _c=col: sum(1 for pm in c.battlefield if _c in pm.card.identity())
    if "cards in your hand" in p or "in your hand" in p:
        return lambda g, c: len(c.hand)
    if "lands you control" in p:
        return lambda g, c: len(c.lands())
    if "artifacts you control" in p:
        return lambda g, c: sum(1 for pm in c.battlefield if "artifact" in pm.card.types)
    if "creatures you control" in p:
        return lambda g, c: len(c.creatures())
    ml = re.search(r"number of ([a-z, ]+?) (you control|your opponents control|"
                   r"opponents control|on the battlefield)", p)
    if ml:
        kinds = [_singular(k) for k in re.split(r",\s*(?:and |or )?|\s+(?:and|or)\s+",
                                               ml.group(1)) if k]
        if len(kinds) > 1 and all(k in ("artifact", "enchantment", "creature", "land",
                                        "planeswalker") for k in kinds):
            whose = ml.group(2)

            def _cnt(g, c, _ks=tuple(kinds), _w=whose):
                pls = ([c] if _w == "you control" else
                       g.opponents(c) if "opponents" in _w else g.players)
                return sum(1 for pl in pls for pm in pl.battlefield
                           if any(k in pm.card.types for k in _ks))
            return _cnt
    m = re.search(r"number of ([\w']+?) (you control|on the battlefield)", p)
    if m:
        w = _singular(m.group(1))
        if m.group(2) == "on the battlefield":   # de TODOS los jugadores (antes solo las tuyas)
            def _all(g, c, _w=w):
                pms = [pm for pl in g.players for pm in pl.battlefield]
                if _w == "creature":
                    return sum(1 for pm in pms if pm.is_creature())
                if _w in ("land", "artifact", "enchantment", "planeswalker"):
                    return sum(1 for pm in pms if _w in pm.card.types)
                return sum(1 for pm in pms if _w in {s.lower() for s in pm.card.subtypes})
            return _all
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


_amt_depth = 0


_CLAUSE_SPLIT = re.compile(
    r"(?<=\.)\s+(?=[A-Z])|,? and (?=(?:you lose|you gain|you draw|draw |create |"
    r"each opponent |each player |you get ))", re.I)
_CONDITIONAL = re.compile(r"^(?:if|otherwise|unless|then if|instead)\b|\bif you do\b|"
                          r"\bthis way\b|\bif (?:you|it|that|a|an|the)\b", re.I)



# --------------------------------------------------------------------------- #
# EFECTOS ATÓMICOS (sobre la propia carta, el sujeto del disparo, etc.)
# --------------------------------------------------------------------------- #

# "it" NO va acá: en "put a counter on target creature. It gains deathtouch" el
# "it" es el objetivo, no la fuente. Solo se acepta en los contadores (abajo).
_SELF_REF = r"(?:~|this creature|this permanent|this artifact|this enchantment)"


def _src_perm(game, a):
    """Permanente FUENTE del efecto: el que llega como argumento (ETB, activada) o
    el que dejó el motor al resolver un disparo/habilidad."""
    if a and hasattr(a[0], "card") and hasattr(a[0], "controller"):
        return a[0]
    return getattr(game, "_trigger_source", None)


def _it_perm(game, a, ctrl):
    """'it' de un efecto encadenado: el sujeto del disparo, o lo que acaba de entrar
    ("return … to the battlefield. It gains haste"), o la fuente."""
    subj = getattr(game, "_trigger_subject", None)
    src = _src_perm(game, a)
    if subj is not None and hasattr(subj, "card") and subj is not src \
            and subj in subj.controller.battlefield:
        return subj
    le = getattr(game, "_last_entered", None)
    if (le is not None and le.controller is ctrl and le in ctrl.battlefield
            and getattr(le, "_etb_turn", None) == game.turn
            and (src is None or getattr(le, "_etb_seq", 0) > getattr(src, "_etb_seq", 0))):
        return le
    return src


def _cmc_of(pm):
    c = getattr(pm, "card", pm)
    return c.cost.cmc if getattr(c, "cost", None) else 0


def _bounce_pm(game, pm, why="vuelve a la mano"):
    """Devuelve un permanente a la mano de su dueño (comandante -> zona de mando)."""
    pl = pm.controller
    if pm not in pl.battlefield:
        return False
    pl.battlefield.remove(pm)
    if hasattr(game, "note_departure"):
        game.note_departure(pm, "bounced")
    if pm.card.on_leave:
        pm.card.on_leave(game, pl, pm)
    if not pm.is_token:
        real = getattr(pm.card, "_real", None) or pm.card
        owner = game.commander_owner(real)
        (owner.command if owner else pl.hand).append(real)
    game.log(f"{pm.name} {why}")
    return True


_KIND_RX = (r"(another creature or artifact|another creature|a creature|another nontoken creature|"
            r"a nontoken creature|a nonartifact creature|an artifact|another artifact|a food|a land|"
            r"a clue|a treasure|an enchantment|another enchantment|a permanent|another permanent|"
            r"a (?:non-)?\w+ creature|an? \w+)")


def _kind_ok(pm, kind, src):
    k = kind
    if k.startswith("another") and pm is src:
        return False
    k = re.sub(r"^(?:another|a|an) ", "", k)
    if "nontoken" in k and pm.is_token:
        return False
    if "creature or artifact" in k:
        return pm.is_creature() or "artifact" in pm.card.types
    if k.startswith("nonartifact") and "artifact" in pm.card.types:
        return False
    if k in ("food", "clue", "treasure"):
        return pm.has_subtype(k)
    if k == "permanent":
        return True
    if k in ("artifact", "enchantment", "land"):
        return k in pm.card.types
    mk = re.fullmatch(r"(non-)?(\w+) creature", k)
    if mk and mk.group(2) not in ("nontoken", "nonartifact"):
        has = pm.has_subtype(mk.group(2))
        return pm.is_creature() and (not has if mk.group(1) else has)
    if "creature" in k:
        return pm.is_creature()
    return pm.has_subtype(k) or k in pm.card.types


def _fodder(game, ctrl, kind, src, optional=True):
    """Permanente a sacrificar como coste opcional: fichas y cosas baratas; si no es
    opcional, lo de menos valor."""
    pool = [pm for pm in ctrl.battlefield if pm is not src and _kind_ok(pm, kind, src)
            and not ctrl.is_commander(pm.card)]
    if optional:
        pool = [pm for pm in pool if pm.is_token or (
            _cmc_of(pm) <= 2 and pm.card.produces is None and not pm.card.is_land()
            and (not pm.is_creature() or pm.power + pm.toughness <= 3))]
    if not pool:
        return None
    return min(pool, key=lambda pm: (not pm.is_token, _cmc_of(pm),
                                     pm.power + pm.toughness if pm.is_creature() else 0))


def _that_player(game, ctrl):
    """'that player' de un disparo: el defensor / el que lanzó / el que robó…"""
    kw = getattr(game, "_trigger_kw", None) or {}
    for k in ("defender", "caster", "drawer", "player", "target", "active"):
        v = kw.get(k)
        if v is not None:
            v = v if hasattr(v, "life") else getattr(v, "controller", None)
            if v is not None and v is not ctrl:
                return v
    return None


def _atomic_effect(text):
    """Efectos atómicos que el parser genérico no cubría. Devuelve eff o None."""
    t = re.sub(r"\s+", " ", _strip_reminder(text or "")).strip().rstrip(".").lower()
    t = re.sub(r"^(?:then |and )", "", t)
    if _ATOM_NAMES and _CUR_NAMES:         # reintento: el nombre propio como "~" ("Probe deals…")
        for nm in sorted(_CUR_NAMES[-1], key=len, reverse=True):
            if len(nm) >= 3:
                t = re.sub(r"(?<![\w'])" + re.escape(nm.lower()) + r"(?![\w'])", "~", t)

    if t in ("the ring tempts you", "the ring tempts you again"):
        return lambda game, ctrl, *a, **kw: game.ring_tempt(ctrl)
    if t in ("this creature deals damage equal to its power to any target",
             "~ deals damage equal to its power to any target",
             "it deals damage equal to its power to any target"):
        def eff_pow_any(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            n = max(0, getattr(src, "power", 0) or 0) if src is not None else 0
            if n <= 0:
                return
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            kill = [pm for o in opps for pm in o.creatures()
                    if pm.toughness - pm.damage <= n and game.can_target(ctrl, pm)]
            cands = ([(f"{pm.name} {pm.power}/{pm.toughness}", pm)
                      for pm in sorted(kill, key=lambda x: x.power + x.toughness, reverse=True)]
                     + [(f"{o.name} ({o.life})", o) for o in sorted(opps, key=lambda o: o.life)])

            def _do(tg, _n=n):
                game.deal_damage(src, tg, _n)
                game.sba()
            _human_target_choice(game, ctrl, "etb_target", f"{src.name}: {n} de daño a…", cands, _do)
        return eff_pow_any
    m = re.fullmatch(r"attacking creatures (?:you control )?get \+(\d+)/\+(\d+)(?: and gain ([a-z ]+?))? "
                     r"until end of turn", t)
    if m:
        _kws = {k.strip().replace(" ", "_") for k in re.split(r",| and ", m.group(3) or "") if k.strip()}

        def eff_att_buff(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), _k=_kws, **kw):
            for pm in ctrl.creatures():
                if pm.attacking is not None:
                    pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                    pm.temp_keywords |= _k
        return eff_att_buff
    m = re.fullmatch(r"it (?:gets ([+-]\d+)/([+-]\d+)|gains ([a-z ,]+?))(?: and gains ([a-z ,]+?))? "
                     r"until end of turn", t)
    if m:
        _kws = {k.strip().replace(" ", "_") for k in re.split(r",| and ", (m.group(3) or "") + ","
                                                                + (m.group(4) or "")) if k.strip()}
        _dp, _dt = int(m.group(1) or 0), int(m.group(2) or 0)

        def eff_it_eot(game, ctrl, *a, _k=_kws, _dp=_dp, _dt=_dt, **kw):
            pm = _it_perm(game, a, ctrl)
            if pm is None or pm not in pm.controller.battlefield:
                return
            pm.temp_pt = [pm.temp_pt[0] + _dp, pm.temp_pt[1] + _dt]
            pm.temp_keywords |= _k
            if "haste" in _k:
                pm.summoning_sick = False
        return eff_it_eot
    m = re.fullmatch(r"(sacrifice|exile) it at the beginning of the next end step", t)
    if m:
        def eff_it_later(game, ctrl, *a, _ex=m.group(1) == "exile", **kw):
            pm = _it_perm(game, a, ctrl)
            if pm is None:
                return

            def _go(g, _pm=pm):
                if _pm in _pm.controller.battlefield:
                    if _ex:
                        g.exile_permanent(_pm, "fin de turno")
                    else:
                        g.to_graveyard(_pm, "sacrificio (fin de turno)")
            game.delayed_end.append(_go)
        return eff_it_later
    if t == "exile the top card of your library":
        def eff_exile_top(game, ctrl, *a, **kw):
            if ctrl.library:
                c = ctrl.library.pop()
                ctrl.exile.append(c)
                game.log(f"{ctrl.name} exilia {c.name} de la parte superior")
        return eff_exile_top
    if t in ("reveal the top card of your library", "look at the top card of your library"):
        return lambda game, ctrl, *a, **kw: None
    if t == "you may discard a card":
        def eff_may_discard(game, ctrl, *a, **kw):
            lands = [c for c in ctrl.hand if c.is_land()]
            if len(lands) >= 2 or len(ctrl.hand) >= 6:
                c = lands[0] if len(lands) >= 2 else min(ctrl.hand, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
        return eff_may_discard
    m = re.fullmatch(r"(?:this enchantment|this artifact|this aura|this land) deals (\w+) damage to that player", t)
    if m and (n := _count_word(m.group(1))):
        def eff_ench_dmg_that(game, ctrl, *a, _n=n, **kw):
            pl = _that_player(game, ctrl)
            if pl is not None and not pl.lost:
                game.deal_damage(_src_perm(game, a), pl, _n)
        return eff_ench_dmg_that
    m = re.fullmatch(r"(?:you may have )?target (?:player|opponent) mills? (\w+) cards?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_tp_mill(game, ctrl, *a, _n=n, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if opps:
                cards.mill(game, max(opps, key=lambda o: len(o.library) and -len(o.library)), _n)
        return eff_tp_mill
    m = re.fullmatch(r"~ deals x damage to each creature, where x is (.+)", t)
    if m and (_cf := _count_fn(m.group(1))) is not None:
        def eff_chain_rx(game, ctrl, *a, _f=_cf, **kw):
            n = _f(game, ctrl)
            src = _src_perm(game, a)
            for pl in game.players:
                for pm in list(pl.creatures()):
                    game.deal_damage(src, pm, n)
            game.sba()
        return eff_chain_rx
    if t == "return all artifact and enchantment cards from all graveyards to the battlefield under their owners' control":
        def eff_vaults(game, ctrl, *a, **kw):
            for pl in game.players:
                for c in [c for c in pl.graveyard if {"artifact", "enchantment"} & c.types]:
                    pl.graveyard.remove(c)
                    game.move_to_battlefield(c, pl)
        return eff_vaults
    if t == "return target nonland permanent and all other permanents with the same name as that permanent to their owners' hands":
        def eff_echo(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield
                    if not pm.card.is_land() and game.can_target(ctrl, pm)]
            if not pool:
                return
            import collections as _co
            cnt = _co.Counter(pm.name for pm in pool)
            nm = max(pool, key=lambda x: (cnt[x.name], _cmc_of(x))).name
            for pl in game.players:
                for pm in list(pl.battlefield):
                    if pm.name == nm:
                        _bounce_pm(game, pm)
        return eff_echo
    if t in ("shuffle ~ into its owner's library", "shuffle this card into its owner's library"):
        def eff_self_shuffle(game, ctrl, *a, **kw):
            c = getattr(game, "_resolving_card", None)
            for pl in game.players:
                for x in list(pl.graveyard):
                    if c is not None and x is c:
                        pl.graveyard.remove(x)
                        pl.library.append(x)
                        game.rng.shuffle(pl.library)
                        return
            if c is not None:
                c._shuffle_after_cast = True
        return eff_self_shuffle
    if t in ("until your next turn, those creatures can't block", "those creatures can't block this turn"):
        def eff_those_cant_block(game, ctrl, *a, **kw):
            for o in game.opponents(ctrl):
                for pm in o.creatures():
                    if getattr(pm, "goaded", False):
                        pm.temp_keywords.add("cant_block")
        return eff_those_cant_block
    if t == "each player loses a third of their life, rounded up":
        def eff_third(game, ctrl, *a, **kw):
            for pl in game.players:
                if not pl.lost and pl.life > 0:
                    pl.life -= -(-pl.life // 3)
        return eff_third
    if t in ("you gain life and draw cards equal to its power", "you gain life equal to its power and draw that many cards"):
        def eff_lifeblood(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            n = max(0, getattr(src, "power", 0) or 0)
            if n:
                game.gain_life(ctrl, n)
                ctrl.draw(min(n, 15), game)
        return eff_lifeblood
    m = re.fullmatch(r"you may cast target (instant or sorcery|instant|sorcery) card with mana value (\d+) or less from "
                     r"your graveyard without paying its mana cost(?:\. if that (?:spell|card) would be put into "
                     r"(?:your|a) graveyard,? exile it instead)?", t)
    if m:
        def eff_gdd(game, ctrl, *a, _n=int(m.group(2)), _k=m.group(1), **kw):
            pool = [c for c in ctrl.graveyard if ({"instant", "sorcery"} & c.types) and c.cost is not None
                    and c.cost.cmc <= _n and (_k == "instant or sorcery" or _k in c.types)
                    and getattr(c, "on_cast_resolve", None) is not None]
            if not pool:
                return
            c = max(pool, key=lambda x: x.cost.cmc)
            ctrl.graveyard.remove(c)
            ctrl.hand.append(c)
            c._exile_after_cast = True
            orig = c.cost
            c.cost = Cost(generic=0, pips=())
            ok = False
            try:
                ok = game.cast(ctrl, c)
            finally:
                c.cost = orig
                if not ok:
                    c._exile_after_cast = False
                    if c in ctrl.hand:
                        ctrl.hand.remove(c)
                        ctrl.graveyard.append(c)
        return eff_gdd
    m = re.fullmatch(r"(?:you may )?return target (artifact|enchantment|permanent) card from your graveyard "
                     r"to the battlefield", t)
    if m:
        def eff_reanim_kind(game, ctrl, *a, _k=m.group(1), **kw):
            pool = [c for c in ctrl.graveyard if _k == "permanent" and not ({"instant", "sorcery"} & c.types)
                    or _k in c.types]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.graveyard.remove(c)
                game.move_to_battlefield(c, ctrl)
        return eff_reanim_kind
    def _subj20(game, a, ctrl):
        sj = getattr(game, "_trigger_subject", None)
        if sj is not None and hasattr(sj, "card"):
            return sj
        return _it_perm(game, a, ctrl)

    def _amt20(game):
        k = getattr(game, "_trigger_kw", None) or {}
        n = k.get("amount") or 0
        return n if isinstance(n, int) and n > 0 else 0

    def _opp_best(game, ctrl, pred=lambda pm: True, key=lambda pm: (pm.power, _cmc_of(pm))):
        pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield if pred(pm) and game.can_target(ctrl, pm)]
        return max(pool, key=key) if pool else None

    # ── batch 20: long tail de efectos atómicos ──
    m = re.fullmatch(r"put target (.+?)(?: an opponent controls| you don't control)? on (top|the bottom) of its owner's library", t)
    if m and (_kp := _kind_pred21(m.group(1))) is not None and m.group(1) != "creature":
        def eff_tuck_kind(game, ctrl, *a, _p=_kp, _top=m.group(2) == "top", **kw):
            pm = _opp_best(game, ctrl, _p, key=lambda x: (_cmc_of(x), x.power))
            if pm is None:
                return
            pm.controller.battlefield.remove(pm)
            if not pm.is_token:
                own = getattr(pm, "owner", None) or pm.controller
                c = getattr(pm.card, "_real", None) or pm.card
                if _top:
                    own.library.append(c)
                else:
                    own.library.insert(0, c)
            game.sba()
        return eff_tuck_kind
    m = re.fullmatch(r"return target (.+?) (?:an opponent controls |you don't control )?to its owner's hand", t)
    if m and re.search(r",| or |with|enchanted", m.group(1)) and "card" not in m.group(1) and \
            (_kp := _kind_pred21(m.group(1))) is not None:
        def eff_bounce_kind(game, ctrl, *a, _p=_kp, **kw):
            pm = _opp_best(game, ctrl, _p, key=lambda x: (_cmc_of(x), x.power))
            if pm is not None:
                _bounce_pm(game, pm)
        return eff_bounce_kind
    m = re.fullmatch(r"return target (creature|artifact|enchantment|artifact or enchantment|instant or sorcery|permanent|land) "
                     r"card from a graveyard to its owner's hand", t)
    if m:
        def eff_gy_any_hand(game, ctrl, *a, _k=m.group(1), **kw):
            def ok(c):
                return any((x == "creature" and c.is_creature()) or x in c.types or x == "permanent"
                           for x in _k.split(" or "))
            pool = [c for c in ctrl.graveyard if ok(c)]
            if pool:
                c = max(pool, key=lambda c: c.cost.cmc if c.cost else 0)
                ctrl.graveyard.remove(c)
                ctrl.hand.append(c)
        return eff_gy_any_hand
    m = re.fullmatch(r"destroy any number of target (.+?)s?", t)
    if m and (_kp := _kind_pred21(re.sub(r"s( |$)", r"\1", m.group(1)).replace("and/ors", "and/or"))) is not None:
        def eff_destroy_any(game, ctrl, *a, _p=_kp, **kw):
            for o in game.opponents(ctrl):
                for pm in list(o.battlefield):
                    if _p(pm) and game.can_target(ctrl, pm):
                        game.destroy(pm, "destruida")
            game.sba()
        return eff_destroy_any
    m = re.fullmatch(r"destroy (two|three|four|\d+) target (.+?)s", t)
    if m and (n := _count_word(m.group(1))) and (_kp := _kind_pred21(m.group(2))) is not None:
        def eff_destroy_n_kind(game, ctrl, *a, _n=n, _p=_kp, **kw):
            pool = sorted([pm for o in game.opponents(ctrl) for pm in o.battlefield if _p(pm) and game.can_target(ctrl, pm)],
                          key=lambda x: ("basic" not in x.card.supertypes, _cmc_of(x), x.power), reverse=True)
            for pm in pool[:_n]:
                game.destroy(pm, "destruida")
            game.sba()
        return eff_destroy_n_kind
    m = re.fullmatch(r"target (?:player|opponent) sacrifices (a|an|one|two|three|\d+) (.+?)s?(?: of their choice)?", t)
    if m and (n := _count_word(m.group(1))) and (n >= 2 or m.group(2) != "creature") and \
            (_kp := _kind_pred21(m.group(2))) is not None:
        def eff_tp_sac(game, ctrl, *a, _n=n, _p=_kp, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost and any(_p(pm) for pm in o.battlefield)]
            if not opps:
                return
            o = max(opps, key=lambda x: sum(1 for pm in x.battlefield if _p(pm)))
            for _ in range(_n):
                pool = [pm for pm in o.battlefield if _p(pm)]
                if not pool:
                    break
                _human_or_auto_sacrifice(game, o, "Sacrificio forzado", pool=pool)
            game.sba()
        return eff_tp_sac
    m = re.fullmatch(r"target player gains (\w+) life and draws (\w+) cards?", t)
    if m and _count_word(m.group(1)) and _count_word(m.group(2)):
        def eff_gain_draw(game, ctrl, *a, _l=_count_word(m.group(1)), _d=_count_word(m.group(2)), **kw):
            game.gain_life(ctrl, _l)
            ctrl.draw(_d, game)
        return eff_gain_draw
    if t == "each player returns all creature cards from their graveyard to their hand":
        def eff_all_gy_hand(game, ctrl, *a, **kw):
            for pl in game.players:
                for c in [c for c in pl.graveyard if c.is_creature()]:
                    pl.graveyard.remove(c)
                    pl.hand.append(c)
        return eff_all_gy_hand
    if t == "each player puts a creature card from their graveyard onto the battlefield":
        def eff_exhume(game, ctrl, *a, **kw):
            for pl in game.players:
                pool = [c for c in pl.graveyard if c.is_creature()]
                if pool:
                    c = max(pool, key=lambda c: (c.cost.cmc if c.cost else 0, c.power or 0))
                    pl.graveyard.remove(c)
                    game.move_to_battlefield(c, pl)
        return eff_exhume
    if t in ("target creature can't attack this turn", "target creature can't attack or block this turn"):
        def eff_no_attack(game, ctrl, *a, _b="block" in t, **kw):
            pm = _opp_best(game, ctrl, lambda x: x.is_creature(), key=lambda x: x.power)
            if pm is not None:
                pm._no_attack_turn = game.turn
                if _b:
                    pm.temp_keywords.add("cant_block")
        return eff_no_attack
    # batch 21: cambios temporales de características
    t21 = re.sub(r"^until end of turn, (.+?)$", r"\1 until end of turn", t) if t.startswith("until end of turn, ") \
        and "until end of turn" not in t[len("until end of turn, "):] else t
    m = re.fullmatch(r"(target creature|target creature an opponent controls|each creature target player controls|"
                     r"target nonland permanent) loses all abilities(?:,| and) (?:has base power and toughness (\d+)/(\d+)|"
                     r"becomes (?:a|an) [a-z ]+? with base power and toughness (\d+)/(\d+))(?: and gains ([a-z ]+))?"
                     r"(?: until end of turn)?", t21) or re.fullmatch(
                     r"(target creature|target creature an opponent controls|each creature target player controls|"
                     r"target nonland permanent) loses all abilities(?: until end of turn)?", t21)
    if m:
        def eff_humble(game, ctrl, *a, _w=m.group(1), _pt=((int(m.group(2) or m.group(4)), int(m.group(3) or m.group(5)))
                                                         if m.lastindex and m.lastindex >= 3 and (m.group(2) or m.group(4))
                                                         else None), **kw):
            if _w.startswith("each creature"):
                opps = [o for o in game.opponents(ctrl) if not o.lost and o.creatures()]
                pool = max(opps, key=lambda o: sum(x.power for x in o.creatures())).creatures() if opps else []
            else:
                pm = _opp_best(game, ctrl, lambda x: x.is_creature() or not x.card.is_land(),
                               key=lambda x: (x.power + x.toughness, _cmc_of(x)))
                pool = [pm] if pm is not None else []
            for pm in pool:
                pm._abil_off_turn = game.turn
                if _pt is not None:
                    old = pm.set_base_pt
                    pm.set_base_pt = _pt
                    game.delayed_end.append(lambda g, _pm=pm, _o=old: setattr(_pm, "set_base_pt", _o))
            game.sba()
        return eff_humble
    m = re.fullmatch(r"(target creature|target creature an opponent controls) (?:becomes (?:a|an) [a-z ]+? with base power and "
                     r"toughness (\d+)/(\d+)|has base power and toughness (\d+)/(\d+))(?: and gains ([a-z ,]+?))?"
                     r"(?: until end of turn)?", t21)
    if m and t21 != t or (m and "becomes" in t21):
        def eff_poly(game, ctrl, *a, _p=int(m.group(2) or m.group(4)), _q=int(m.group(3) or m.group(5)),
                     _kw=[k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(6) or "")
                          if k.strip()], **kw):
            mine = (_p + _q) >= 6
            if mine and ctrl.creatures():
                pm = max(ctrl.creatures(), key=lambda x: (x.attacking is not None, -(x.power + x.toughness)))
            else:
                pm = _opp_best(game, ctrl, lambda x: x.is_creature(), key=lambda x: x.power + x.toughness)
            if pm is None:
                return
            old = pm.set_base_pt
            pm.set_base_pt = (_p, _q)
            game.delayed_end.append(lambda g, _pm=pm, _o=old: setattr(_pm, "set_base_pt", _o))
            for k in _kw:
                pm.temp_keywords.add(k)
            game.sba()
        return eff_poly
    m = re.fullmatch(r"target creature(?: an opponent controls)? loses (flying|first strike|trample|deathtouch|lifelink|"
                     r"reach|menace|vigilance|haste|indestructible|hexproof|all abilities)(?: and [a-z ]+)? until end of turn", t21)
    if m and m.group(1) != "all abilities":
        def eff_lose_kw(game, ctrl, *a, _k=m.group(1).replace(" ", "_"), **kw):
            pm = _opp_best(game, ctrl, lambda x: x.is_creature() and x.has(_k), key=lambda x: x.power)
            if pm is not None:
                pm._lost_kw = (game.turn, {_k})
        return eff_lose_kw
    m = re.fullmatch(r"target land (?:you control )?becomes (?:a|an) (\d+)/(\d+)(?: [a-z ]+?)? creature"
                     r"(?: with ([a-z ,]+?))?(?: that's still a land)?(?: until end of turn)?(?:\. it's still a land)?", t21)
    if m:
        def eff_animate_land(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)),
                             _kw=[k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(3) or "")
                                  if k.strip()], **kw):
            lands = [pm for pm in ctrl.battlefield if pm.card.is_land() and not pm.is_creature()]
            if not lands:
                return
            pm = max(lands, key=lambda x: x.tapped)
            pm.temp_creature = True
            old = pm.set_base_pt
            pm.set_base_pt = (_p, _q)
            game.delayed_end.append(lambda g, _pm=pm, _o=old: setattr(_pm, "set_base_pt", _o))
            for k in _kw:
                pm.temp_keywords.add(k)
        return eff_animate_land
    m = re.fullmatch(r"(?:you may )?copy (?:it|that spell)(?: for each time you've cast your commander from the command zone "
                     r"this game)?", t)
    if m:
        def eff_copy_trig_spell(game, ctrl, *a, _cmd="commander" in t, **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            c = k.get("card")
            obj = next((o for o in reversed(game.stack) if getattr(o, "source", None) is c and c is not None
                        and getattr(o, "kind", "") == "spell"), None)
            if obj is None:
                return
            n = 1
            if _cmd:
                n = sum(getattr(ctrl, "cmdr_taxes", [0]) or [0]) // 2
            for _ in range(n):
                game.copy_spell_on_stack(obj, controller=ctrl)
        return eff_copy_trig_spell
    m = re.fullmatch(r"copy the next (instant or sorcery |instant |sorcery |)spell you cast this turn(?: when you cast it)?", t)
    if m:
        def eff_copy_next(game, ctrl, *a, _k=m.group(1).strip(), **kw):
            ctrl._copy_next = (game.turn, _k)
        return eff_copy_next
    if t in ("exile ~", "exile this creature", "exile this permanent", "exile this artifact", "exile this enchantment"):
        def eff_exile_self_any(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                game.exile_permanent(src, "se exilia")
                return
            c = getattr(game, "_resolving_card", None)
            if c is not None and {"instant", "sorcery"} & c.types:
                c._exile_after_cast = True
        return eff_exile_self_any
    if t in ("you may discard your hand", "discard your hand"):
        def eff_discard_hand(game, ctrl, *a, _may=t.startswith("you may"), **kw):
            if _may and len(ctrl.hand) > 2:
                return                       # el bot solo descarta una mano corta
            for c in list(ctrl.hand):
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
        return eff_discard_hand
    m = re.fullmatch(r"(?:they|that player) loses? (\w+) life", t)
    if m and _count_word(m.group(1)):
        def eff_they_lose(game, ctrl, *a, _n=_count_word(m.group(1)), **kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                k = getattr(game, "_trigger_kw", None) or {}
                pl = k.get("caster") or k.get("player")
                pl = pl if hasattr(pl, "life") else None
            if pl is not None and not pl.lost:
                pl.life -= _n
                game.log(f"{pl.name} pierde {_n} de vida{game.src_tag()}")
        return eff_they_lose
    m = re.fullmatch(r"flip a coin\. if you (win|lose) the flip, (.+?)(?:\. if you (win|lose) the flip, (.+))?", t)
    if m and m.group(1) != m.group(3):
        _e1 = _effect_any(m.group(2))
        _e2 = _effect_any(m.group(4)) if m.group(4) else None
        if _e1 is not None and (m.group(4) is None or _e2 is not None):
            def eff_flip(game, ctrl, *a, _w1=m.group(1) == "win", _a=_e1, _b=_e2, **kw):
                won = game.rng.random() < 0.5
                game.log(f"{ctrl.name} tira una moneda: {'gana' if won else 'pierde'}")
                if won == _w1:
                    _a(game, ctrl, *a)
                elif _b is not None:
                    _b(game, ctrl, *a)
            return eff_flip
    m = re.fullmatch(r"return (?:the exiled card to its owner's hand|the exiled card to the battlefield "
                     r"under its owner's control)", t)
    if m:
        def eff_return_exiled(game, ctrl, *a, _bf="battlefield" in t, **kw):
            src = _src_perm(game, a)
            for c, o in list(getattr(src, "_exiled_with", None) or []):
                if c in o.exile:
                    o.exile.remove(c)
                    if _bf:
                        game.move_to_battlefield(c, o)
                    else:
                        o.hand.append(c)
                    game.log(f"{c.name} vuelve de exilio a {o.name}")
            if src is not None:
                src._exiled_with = []
        return eff_return_exiled
    if t in ("sacrifice it unless it escaped", "sacrifice this creature unless it escaped"):
        def eff_sac_unless_escaped(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None and not getattr(src, "_escaped", False) and src in src.controller.battlefield:
                game.to_graveyard(src, "no escapó")
        return eff_sac_unless_escaped
    if t == "untap enchanted creature":
        def eff_untap_host(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            host = getattr(src, "enchanting", None) or getattr(game, "_trigger_subject", None)
            if host is not None and hasattr(host, "tapped"):
                host.tapped = False
        return eff_untap_host
    if t in ("you get that many {e}", "you get that much {e}"):
        def eff_energy_many(game, ctrl, *a, **kw):
            n = _amt20(game)
            if n:
                n *= 2 ** sum(1 for pm in ctrl.battlefield if getattr(pm.card, "energy_double", False))
                ctrl.energy = getattr(ctrl, "energy", 0) + n
        return eff_energy_many
    if t == "return that creature to its owner's hand at end of combat":
        def eff_bounce_subj_eoc(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None)
            if sj is None or not hasattr(sj, "card"):
                return
            game.delayed_end.append(lambda g, _s=sj: _bounce_pm(g, _s) if _s in _s.controller.battlefield else None)
        return eff_bounce_subj_eoc
    m = re.fullmatch(r"destroy (two|three|four|\d+) target (lands|creatures|artifacts|enchantments|nonland permanents)", t)
    if m and (n := _count_word(m.group(1))):
        def eff_destroy_n(game, ctrl, *a, _n=n, _k=m.group(2), **kw):
            def ok(x):
                if _k == "lands":
                    return x.card.is_land()
                if _k == "creatures":
                    return x.is_creature()
                if _k == "nonland permanents":
                    return not x.card.is_land()
                return _k[:-1] in x.card.types
            pool = sorted([pm for o in game.opponents(ctrl) for pm in o.battlefield if ok(pm) and game.can_target(ctrl, pm)],
                          key=lambda x: ("basic" not in x.card.supertypes, _cmc_of(x), x.power), reverse=True)
            for pm in pool[:_n]:
                game.destroy(pm, "destruida")
            game.sba()
        return eff_destroy_n
    m = re.fullmatch(r"untap (?:up to (\w+) target creatures\. they each get|target (?:nonattacking )?creature\. it gets) "
                     r"([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_untap_pump(game, ctrl, *a, _n=_count_word(m.group(1) or "one") or 1, _p=int(m.group(2)),
                           _q=int(m.group(3)), **kw):
            pool = sorted(ctrl.creatures(), key=lambda x: (not x.tapped, -x.power))
            for pm in pool[:_n]:
                pm.tapped = False
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
        return eff_untap_pump
    if t in ("you may tap or untap target artifact, creature, or land", "you may tap or untap target permanent",
             "tap or untap target permanent", "you may tap or untap target creature"):
        def eff_tap_or_untap(game, ctrl, *a, **kw):
            pm = _opp_best(game, ctrl, lambda x: x.is_creature() and not x.tapped, key=lambda x: x.power)
            if pm is not None:
                pm.tapped = True
        return eff_tap_or_untap
    if t == "put all creatures on the bottom of their owners' libraries":
        def eff_bottom_all(game, ctrl, *a, **kw):
            for pl in game.players:
                for pm in list(pl.creatures()):
                    pl.battlefield.remove(pm)
                    if not pm.is_token:
                        own = getattr(pm, "owner", None) or pl
                        own.library.insert(0, getattr(pm.card, "_real", None) or pm.card)
            game.sba()
        return eff_bottom_all
    if t == "shuffle any number of target creature cards from your graveyard into your library":
        def eff_gy_shuffle_cr(game, ctrl, *a, **kw):
            pool = [c for c in ctrl.graveyard if c.is_creature()]
            for c in pool:
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
            if pool:
                game.rng.shuffle(ctrl.library)
        return eff_gy_shuffle_cr
    m = re.fullmatch(r"any number of target creatures each get ([+-]\d+)/([+-]\d+)(?: and gain ([a-z ]+?))? until end of turn", t)
    if m:
        def eff_any_pump(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), _kw=(m.group(3) or "").replace(" ", "_"), **kw):
            for pm in ctrl.creatures():
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                if _kw:
                    pm.temp_keywords.add(_kw)
        return eff_any_pump
    m = re.fullmatch(r"(target creature you control|up to (\w+) target creatures you control each) deals? damage equal to "
                     r"(twice its power|its power|their power) to target creature an opponent controls", t)
    if m:
        def eff_bite_x(game, ctrl, *a, _n=_count_word(m.group(2) or "one") or 1, _two=m.group(3).startswith("twice"), **kw):
            foe = _opp_best(game, ctrl, lambda x: x.is_creature(), key=lambda x: (x.power, _cmc_of(x)))
            mine = sorted(ctrl.creatures(), key=lambda x: -x.power)[:_n]
            if foe is None or not mine:
                return
            for pm in mine:
                if foe in foe.controller.battlefield and pm.power > 0:
                    game.deal_damage(pm, foe, pm.power * (2 if _two else 1))
            game.sba()
        return eff_bite_x
    if t in ("~ deals damage to each player equal to the number of lands they control",
             "this creature deals damage to each player equal to the number of lands they control"):
        def eff_dmg_lands_each(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            for pl in game.players:
                if not pl.lost:
                    n = sum(1 for pm in pl.battlefield if pm.card.is_land())
                    if n:
                        game.deal_damage(src, pl, n)
        return eff_dmg_lands_each
    m = re.fullmatch(r"look at target (?:opponent|player)'s hand and choose (\w+) cards? from it\. that player discards "
                     r"(?:those cards|that card)", t)
    if m and (n := _count_word(m.group(1))):
        def eff_pick_discard(game, ctrl, *a, _n=n, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost and o.hand]
            if not opps:
                return
            o = max(opps, key=lambda x: len(x.hand))
            for c in sorted(o.hand, key=lambda c: (not c.is_land(), c.cost.cmc if c.cost else 0), reverse=True)[:_n]:
                o.hand.remove(c)
                game.discard_card(o, c)
        return eff_pick_discard
    if t in ("target opponent reveals their hand. you choose a nonland card from that player's graveyard or hand and exile it",):
        def eff_exile_from_hand(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            best = None
            for o in opps:
                for zone in (o.hand, o.graveyard):
                    for c in zone:
                        if not c.is_land() and (best is None or (c.cost.cmc if c.cost else 0) > best[0]):
                            best = ((c.cost.cmc if c.cost else 0), zone, c, o)
            if best:
                best[1].remove(best[2])
                best[3].exile.append(best[2])
        return eff_exile_from_hand
    m = re.fullmatch(r"search target opponent's library for an? (artifact|creature|enchantment|land) card and put that card "
                     r"onto the battlefield under your control\. then that player shuffles", t)
    if m:
        def eff_steal_lib(game, ctrl, *a, _k=m.group(1), **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            pool = [(c, o) for o in opps for c in o.library if _k in c.types or (_k == "creature" and c.is_creature())]
            if not pool:
                return
            c, o = max(pool, key=lambda x: x[0].cost.cmc if x[0].cost else 0)
            o.library.remove(c)
            game.rng.shuffle(o.library)
            game.move_to_battlefield(c, ctrl)
        return eff_steal_lib
    if t == "target player can't play lands this turn":
        def eff_no_lands(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if opps:
                act = game.players[game.active_index]
                (act if act in opps else opps[0]).no_land_turn = game.turn
        return eff_no_lands

    if t in ("target creature attacks this turn if able", "target creature an opponent controls attacks this turn if able"):
        def eff_force_attack(game, ctrl, *a, **kw):
            act = game.players[game.active_index] if game.players else None
            if act is None or act is ctrl:
                return
            pool = [pm for pm in act.creatures() if game.can_target(ctrl, pm) and not pm.summoning_sick]
            if pool:
                min(pool, key=lambda x: x.toughness - x.damage).must_attack = True
        return eff_force_attack
    if t in ("all creatures able to block target creature this turn do so",
             "all creatures able to block target creature this turn do so"):
        def eff_lure_t(game, ctrl, *a, **kw):
            pool = [pm for pm in ctrl.creatures() if not pm.tapped or pm.attacking is not None]
            if pool:
                pm = max(pool, key=lambda x: (x.attacking is not None, x.toughness + x.power))
                pm._lure_turn = game.turn
        return eff_lure_t
    if t in ("put that many +1/+1 counters on it", "put that many +1/+1 counters on that creature"):
        def eff_that_many_ctr_it(game, ctrl, *a, **kw):
            n = _amt20(game)
            sj = getattr(game, "_trigger_subject", None)
            pm = sj if sj is not None and hasattr(sj, "counters") and t.endswith("that creature") else _src_perm(game, a)
            if pm is not None and n:
                game.add_counters(pm, "+1/+1", n)
        return eff_that_many_ctr_it
    m = re.fullmatch(r"(?:up to (\w+)|(\w+) or (\w+)) target creatures each get ([+-]\d+)/([+-]\d+)"
                     r"(?: and gain ([a-z ]+?))? until end of turn", t)
    if m:
        _nn = _count_word(m.group(1) or m.group(3) or "")
        if _nn:
            def eff_n_each_pump(game, ctrl, *a, _n=_nn, _p=int(m.group(4)), _q=int(m.group(5)),
                                _kw=(m.group(6) or "").replace(" ", "_"), **kw):
                if _p + _q < 0 and not _kw:
                    pool = sorted([pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)],
                                  key=lambda x: (x.toughness - x.damage + _q > 0, -x.power))
                else:
                    pool = sorted(ctrl.creatures(), key=lambda x: (x.attacking is None, -x.power))
                for pm in pool[:_n]:
                    pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                    if _kw:
                        pm.temp_keywords.add(_kw)
                game.sba()
            return eff_n_each_pump
    if t == "put any number of target creature cards from your graveyard on top of your library":
        def eff_gy_top_any(game, ctrl, *a, **kw):
            pool = sorted([c for c in ctrl.graveyard if c.is_creature()], key=lambda c: c.cost.cmc if c.cost else 0)
            for c in pool[-2:]:
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
        return eff_gy_top_any
    if t == "put target land on top of its owner's library":
        def eff_land_top(game, ctrl, *a, **kw):
            pm = _opp_best(game, ctrl, lambda x: x.card.is_land(), key=lambda x: ("basic" not in x.card.supertypes, not x.tapped))
            if pm is not None:
                pm.controller.battlefield.remove(pm)
                if not pm.is_token:
                    (getattr(pm, "owner", None) or pm.controller).library.append(getattr(pm.card, "_real", None) or pm.card)
                game.log(f"{pm.name} vuelve arriba de la biblioteca")
        return eff_land_top
    m = re.fullmatch(r"(?:choose target (artifact or enchantment|creature|nonland permanent|permanent|artifact|enchantment)\. "
                     r"its owner shuffles it into their library|the owner of target (artifact or enchantment|creature|"
                     r"nonland permanent|permanent|artifact|enchantment) shuffles it into their library)", t)
    if m:
        def eff_tuck_shuffle(game, ctrl, *a, _k=m.group(1) or m.group(2), **kw):
            def ok(x):
                if _k == "artifact or enchantment":
                    return bool({"artifact", "enchantment"} & x.card.types)
                if _k == "creature":
                    return x.is_creature()
                if _k == "nonland permanent":
                    return not x.card.is_land()
                return _k == "permanent" or _k in x.card.types
            pm = _opp_best(game, ctrl, ok, key=lambda x: (_cmc_of(x), x.power))
            if pm is None:
                return
            pm.controller.battlefield.remove(pm)
            if not pm.is_token:
                own = getattr(pm, "owner", None) or pm.controller
                own.library.append(getattr(pm.card, "_real", None) or pm.card)
                game.rng.shuffle(own.library)
            game.log(f"{pm.name} se baraja en la biblioteca")
            game.sba()
        return eff_tuck_shuffle
    if t == "the owner of target nonland permanent puts it into their library second from the top or on the bottom":
        def eff_tuck_second(game, ctrl, *a, **kw):
            pm = _opp_best(game, ctrl, lambda x: not x.card.is_land(), key=lambda x: (_cmc_of(x), x.power))
            if pm is None:
                return
            pm.controller.battlefield.remove(pm)
            if not pm.is_token:
                own = getattr(pm, "owner", None) or pm.controller
                own.library.insert(max(0, len(own.library) - 1), getattr(pm.card, "_real", None) or pm.card)
            game.sba()
        return eff_tuck_second
    if t in ("search target player's library for a card and exile it. then that player shuffles",
             "search target opponent's library for a card and exile it. then that player shuffles"):
        def eff_search_exile(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost and o.library]
            if not opps:
                return
            o = opps[0]
            c = max(o.library, key=lambda x: (not x.is_land(), x.cost.cmc if x.cost else 0))
            o.library.remove(c)
            o.exile.append(c)
            game.rng.shuffle(o.library)
            game.log(f"{ctrl.name} exilia {c.name} de la biblioteca de {o.name}")
        return eff_search_exile
    if t == "target opponent chooses a creature they control. other creatures they control can't block this turn":
        def eff_one_blocker(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost and o.creatures()]
            if not opps:
                return
            o = max(opps, key=lambda x: len(x.creatures()))
            keep = max(o.creatures(), key=lambda x: (x.toughness, x.power))
            for pm in o.creatures():
                if pm is not keep:
                    pm.temp_keywords.add("cant_block")
        return eff_one_blocker

    m = re.fullmatch(r"put (a|an|one|two|three|\w+) \+1/\+1 counters? on (enchanted creature|enchanted permanent|equipped creature)", t)
    if m and (n := _count_word(m.group(1))):
        def eff_ctr_host(game, ctrl, *a, _n=n, **kw):
            src = _src_perm(game, a)
            host = getattr(src, "enchanting", None)
            if host is not None and host in host.controller.battlefield:
                game.add_counters(host, "+1/+1", _n)
        return eff_ctr_host
    m = re.fullmatch(r"(?:it|this aura|~) deals (\d+) damage to enchanted creature", t)
    if m:
        def eff_dmg_host(game, ctrl, *a, _n=int(m.group(1)), **kw):
            src = _src_perm(game, a)
            host = getattr(src, "enchanting", None)
            if host is not None:
                game.deal_damage(src, host, _n)
                game.sba()
        return eff_dmg_host
    if t in ("you may untap it and remove it from combat", "untap it and remove it from combat",
             "untap this creature and remove it from combat", "remove it from combat"):
        def eff_remove_combat(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None:
                src.tapped = False
                src.attacking = None
        return eff_remove_combat
    m = re.fullmatch(r"each creature blocking it gets ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_blockers_pump(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            src = _src_perm(game, a)
            for b in list(getattr(src, "blocked_by", None) or []):
                b.temp_pt = [b.temp_pt[0] + _p, b.temp_pt[1] + _q]
            game.sba()
        return eff_blockers_pump
    if t == "that player discards all the cards in their hand, then draws that many cards":
        def eff_that_wheel(game, ctrl, *a, **kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                return
            n = len(pl.hand)
            for c in list(pl.hand):
                pl.hand.remove(c)
                game.discard_card(pl, c)
            pl.draw(n, game)
        return eff_that_wheel
    if t in ("this creature's owner shuffles it into their library", "shuffle it into its owner's library",
             "shuffle this creature into its owner's library"):
        def eff_self_shuffle_lib(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is None:
                return
            c = getattr(src.card, "_real", None) or src.card
            if src in src.controller.battlefield:
                src.controller.battlefield.remove(src)
                if not src.is_token:
                    src.controller.library.append(c)
                    game.rng.shuffle(src.controller.library)
                return
            for pl in game.players:
                if c in pl.graveyard:
                    pl.graveyard.remove(c)
                    pl.library.append(c)
                    game.rng.shuffle(pl.library)
                    return
        return eff_self_shuffle_lib
    m = re.fullmatch(r"its controller (loses|gains) (\d+) life", t)
    if m:
        def eff_its_ctrl(game, ctrl, *a, _l=m.group(1) == "loses", _n=int(m.group(2)), **kw):
            sj = getattr(game, "_trigger_subject", None)
            src = _src_perm(game, a)
            host = sj if sj is not None and hasattr(sj, "controller") else getattr(src, "enchanting", None)
            if host is None:
                return
            if _l:
                host.controller.life -= _n
            else:
                game.gain_life(host.controller, _n)
        return eff_its_ctrl
    m = re.fullmatch(r"you may have target creature get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_may_pump(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            if _p + _q < 0:
                pm = _opp_best(game, ctrl, lambda x: x.is_creature(), key=lambda x: (x.toughness - x.damage + _q <= 0, x.power))
            else:
                pm = max(ctrl.creatures(), key=lambda x: (x.attacking is not None, x.power)) if ctrl.creatures() else None
            if pm is not None:
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                game.sba()
        return eff_may_pump
    if t in ("return that card to its owner's hand", "return it to its owner's hand", "return it to your hand",
             "return that card to your hand", "put it into your hand"):
        def eff_card_to_hand(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None)
            src = _src_perm(game, a)
            pm = sj if sj is not None and hasattr(sj, "card") else src
            if pm is None:
                return
            c = getattr(pm.card, "_real", None) or pm.card

            def _mv(g, _c=c):
                for pl in g.players:
                    if _c in pl.graveyard:
                        pl.graveyard.remove(_c)
                        pl.hand.append(_c)
                        return True
                    if _c in pl.exile:
                        pl.exile.remove(_c)
                        pl.hand.append(_c)
                        return True
                return False
            if pm in pm.controller.battlefield:
                _bounce_pm(game, pm)
            elif not _mv(game):
                from engine import StackObject
                game.stack.append(StackObject(ctrl, _mv, source=None, label=f"a la mano: {c.name}"))
        return eff_card_to_hand
    if t in ("look at the top card of target player's library", "look at target player's hand",
             "look at the top card of that player's library", "each player reveals the top card of their library"):
        return lambda game, ctrl, *a, **kw: None
    m = re.fullmatch(r"return (\w+) creatures? you control to (?:their|its) owner(?:'s|s') hands?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_bounce_n_own(game, ctrl, *a, _n=n, **kw):
            src = _src_perm(game, a)
            pool = sorted([pm for pm in ctrl.creatures() if pm is not src],
                          key=lambda x: (not (x.card.on_etb is not None and _cmc_of(x) <= 3), _cmc_of(x)))
            for pm in pool[:_n]:
                _bounce_pm(game, pm)
        return eff_bounce_n_own
    m = re.fullmatch(r"(?:~|this creature) gets ([+-]\d+)/([+-]\d+) until end of turn and can't be blocked this turn", t)
    if m:
        def eff_pump_unbl(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            src = _src_perm(game, a)
            if src is not None:
                src.temp_pt = [src.temp_pt[0] + _p, src.temp_pt[1] + _q]
                src.temp_keywords.add("unblockable")
        return eff_pump_unbl
    m = re.fullmatch(r"(?:~|this creature) gets \+x/\+(x|0) until end of turn, where x is that spell's mana value", t)
    if m:
        def eff_pump_mv(game, ctrl, *a, _t=m.group(1) == "x", **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            c = k.get("card")
            n = c.cost.cmc if (c is not None and c.cost) else 0
            src = _src_perm(game, a)
            if src is not None and n:
                src.temp_pt = [src.temp_pt[0] + n, src.temp_pt[1] + (n if _t else 0)]
        return eff_pump_mv
    m = re.fullmatch(r"return a (white|blue|black|red|green) or (white|blue|black|red|green) creature you control to its owner's hand", t)
    if m:
        def eff_bounce_2col(game, ctrl, *a, _c={m.group(1), m.group(2)}, **kw):
            cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
            cols = {cm[x] for x in _c}
            src = _src_perm(game, a)
            pool = [pm for pm in ctrl.creatures() if cols & {x for pp in (getattr(pm.card.cost, "pips", None) or ())
                                                             for x in str(pp).upper()}]
            if pool:
                _bounce_pm(game, min(pool, key=lambda pm: (pm is src, _cmc_of(pm))))
        return eff_bounce_2col
    if t in ("exile a land you control",):
        def eff_exile_own_land(game, ctrl, *a, **kw):
            pool = [pm for pm in ctrl.battlefield if pm.card.is_land()]
            if pool:
                game.exile_permanent(min(pool, key=lambda x: (not x.tapped, x.card.produces is not None)), "coste")
        return eff_exile_own_land
    if t in ("defending player discards a card", "that player discards a card at random"):
        def eff_def_discard(game, ctrl, *a, **kw):
            pl = _that_player(game, ctrl)
            if pl is not None and pl.hand:
                _human_or_auto_discard(game, pl, 1)
        return eff_def_discard
    if t in ("that player sacrifices a permanent of their choice", "that player sacrifices a permanent",
             "defending player sacrifices a creature"):
        def eff_that_sac_perm(game, ctrl, *a, _cr="creature" in t, **kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                return
            pool = [pm for pm in pl.battlefield if (pm.is_creature() if _cr else True) and not pl.is_commander(pm.card)]
            if pool:
                _human_or_auto_sacrifice(game, pl, "Sacrificio forzado", pool=pool)
        return eff_that_sac_perm
    m = re.fullmatch(r"each opponent creates (?:a|an|\w+) (\d+)/(\d+) (\w+) ([a-z]+) creature tokens?", t)
    if m:
        def eff_opp_token(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), _s=m.group(4).capitalize(), **kw):
            for o in game.opponents(ctrl):
                if not o.lost:
                    cards.make_token(game, o, _s, _p, _q, subtypes=(_s,))
        return eff_opp_token
    if t in ("destroy both creatures", "destroy that creature and this creature"):
        def eff_both(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None)
            src = _src_perm(game, a)
            for pm in (sj, src):
                if pm is not None and pm in pm.controller.battlefield:
                    game.destroy(pm, "destruida")
        return eff_both
    if t in ("draw that many cards, then discard a card",):
        def eff_draw_many_disc(game, ctrl, *a, **kw):
            n = _amt20(game)
            if n:
                ctrl.draw(min(n, 10), game)
                _human_or_auto_discard(game, ctrl, 1)
        return eff_draw_many_disc
    m = re.fullmatch(r"(?:this enchantment|this artifact|~) deals damage to that player equal to the number of "
                     r"(artifacts|creatures|lands|cards in their hand) they control", t)
    if m:
        def eff_dmg_count_that(game, ctrl, *a, _k=m.group(1), **kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                return
            n = (len(pl.hand) if "hand" in _k else sum(1 for pm in pl.battlefield if (
                pm.is_creature() if _k == "creatures" else pm.card.is_land() if _k == "lands"
                else "artifact" in pm.card.types)))
            if n:
                game.deal_damage(_src_perm(game, a), pl, n)
        return eff_dmg_count_that
    m = re.fullmatch(r"(?:you may have )?target (\w+)(?: creature)? you control gets? ([+-]\d+)/([+-]\d+)(?: and gains ([a-z ]+?))? "
                     r"until end of turn", t)
    if m and m.group(1) not in ("creature",):
        def eff_tg_type_pump(game, ctrl, *a, _k=m.group(1), _p=int(m.group(2)), _q=int(m.group(3)),
                             _kw=(m.group(4) or "").replace(" ", "_"), **kw):
            pool = [pm for pm in ctrl.creatures() if pm.has_subtype(_k) or _k in pm.card.types]
            if pool:
                pm = max(pool, key=lambda x: (x.attacking is not None, x.power))
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                if _kw:
                    pm.temp_keywords.add(_kw)
        return eff_tg_type_pump
    m = re.fullmatch(r"(?:you may )?put target (\w+) card from your graveyard on top of your library", t)
    if m and m.group(1) not in ("creature", "card"):
        def eff_gy_top_sub(game, ctrl, *a, _k=m.group(1), **kw):
            pool = [c for c in ctrl.graveyard if any(x.lower() == _k for x in c.subtypes) or _k in c.types]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
        return eff_gy_top_sub
    m = re.fullmatch(r"choose target creature that player controls\. the player sacrifices that creature", t)
    if m:
        def eff_choose_sac(game, ctrl, *a, **kw):
            pl = _that_player(game, ctrl)
            if pl is not None and pl.creatures():
                game.to_graveyard(max(pl.creatures(), key=lambda x: (x.power, _cmc_of(x))), "sacrificio")
        return eff_choose_sac
    m = re.fullmatch(r"put a \+1/\+1 counter on each other (\w+) creature you control", t)
    if m:
        def eff_ctr_each_other_kind(game, ctrl, *a, _k=m.group(1), **kw):
            src = _src_perm(game, a)
            for pm in ctrl.creatures():
                if pm is not src and (pm.has_subtype(_k) or _k in pm.card.types):
                    game.add_counters(pm, "+1/+1", 1)
        return eff_ctr_each_other_kind
    m = re.fullmatch(r"exile up to (\w+) target tapped creatures?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_exile_tapped(game, ctrl, *a, _n=n, **kw):
            pool = sorted([pm for o in game.opponents(ctrl) for pm in o.creatures() if pm.tapped
                           and game.can_target(ctrl, pm)], key=lambda x: -(x.power + _cmc_of(x)))
            for pm in pool[:_n]:
                game.exile_permanent(pm, "exilio")
        return eff_exile_tapped
    if t == "return target land to its owner's hand":
        def eff_bounce_land(game, ctrl, *a, **kw):
            pm = _opp_best(game, ctrl, lambda x: x.card.is_land(), key=lambda x: (not x.tapped, "basic" not in x.card.supertypes))
            if pm is not None:
                _bounce_pm(game, pm)
        return eff_bounce_land
    m = re.fullmatch(r"(?:it|~|this creature) deals damage to target (?:player|opponent) equal to the number of (nonbasic lands|lands|"
                     r"creatures|artifacts) that player controls", t)
    if m:
        def eff_dmg_count_tp(game, ctrl, *a, _k=m.group(1), **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if not opps:
                return

            def cnt(o):
                return sum(1 for pm in o.battlefield if (
                    (pm.card.is_land() and "basic" not in pm.card.supertypes) if _k == "nonbasic lands"
                    else pm.card.is_land() if _k == "lands" else pm.is_creature() if _k == "creatures"
                    else "artifact" in pm.card.types))
            o = max(opps, key=cnt)
            if cnt(o):
                game.deal_damage(_src_perm(game, a), o, cnt(o))
        return eff_dmg_count_tp
    m = re.fullmatch(r"(?:each opponent|target opponent|each player) gains (\d+) life", t)
    if m:
        def eff_opp_gain(game, ctrl, *a, _n=int(m.group(1)), _all=t.startswith("each player"), **kw):
            for pl in (game.players if _all else game.opponents(ctrl)[:1] if t.startswith("target") else game.opponents(ctrl)):
                if not pl.lost:
                    game.gain_life(pl, _n)
        return eff_opp_gain
    if t == "it deals that much damage to each creature that player controls":
        def eff_dmg_each_cr_that(game, ctrl, *a, **kw):
            n = _amt20(game)
            pl = _that_player(game, ctrl)
            if pl is None or not n:
                return
            for pm in list(pl.creatures()):
                game.deal_damage(_src_perm(game, a), pm, n)
            game.sba()
        return eff_dmg_each_cr_that
    if t in ("remove all +1/+1 counters from it", "remove all counters from it"):
        def eff_rm_all_it(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None:
                src.counters.pop("+1/+1", None)
        return eff_rm_all_it
    if t in ("you may put it on your choice of the top or bottom of its owner's library",):
        return _atomic_effect("put it on top of its owner's library")
    m = re.fullmatch(r"each player searches their library for up to (\w+) basic land cards?, puts? (?:them|it) onto the battlefield"
                     r"(?: tapped)?, then shuffles", t)
    if m and (n := _count_word(m.group(1))):
        def eff_each_basics(game, ctrl, *a, _n=n, **kw):
            for pl in game.players:
                if pl.lost:
                    continue
                for c in [c for c in pl.library if c.is_land() and "basic" in c.supertypes][:_n]:
                    pl.library.remove(c)
                    game.move_to_battlefield(c, pl)
                game.rng.shuffle(pl.library)
        return eff_each_basics
    if t in ("sacrifice this aura", "sacrifice this enchantment", "sacrifice this artifact", "sacrifice this land"):
        def eff_sac_this(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                game.to_graveyard(src, "sacrificio")
        return eff_sac_this

    m = re.fullmatch(r"(target player|defending player|each opponent|that player) mills? half their library,? rounded (down|up)", t)
    if m:
        def eff_half_mill(game, ctrl, *a, _w=m.group(1), _up=m.group(2) == "up", **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if _w == "that player" or _w == "defending player":
                tp = _that_player(game, ctrl)
                opps = [tp] if tp is not None else opps[:1]
            elif _w == "target player":
                opps = opps[:1]
            for o in opps:
                n = (len(o.library) + (1 if _up else 0)) // 2
                cards.mill(game, o, n)
        return eff_half_mill
    if t in ("create that many treasure tokens", "create that many tapped treasure tokens"):
        def eff_that_many_treasure(game, ctrl, *a, **kw):
            for _ in range(min(10, _amt20(game))):
                cards.make_resource_token(game, ctrl, "treasure")
        return eff_that_many_treasure
    m = re.fullmatch(r"you may put (?:a|an) (creature|artifact|land|enchantment|permanent|legendary creature|[a-z]+ creature) "
                     r"card from your hand onto the battlefield( tapped)?", t)
    if m:
        def eff_put_from_hand(game, ctrl, *a, _k=m.group(1), _t=bool(m.group(2)), **kw):
            def ok(c):
                if _k == "permanent":
                    return not ({"instant", "sorcery"} & c.types)
                if _k == "creature":
                    return c.is_creature()
                if _k == "legendary creature":
                    return c.is_creature() and c.is_legendary()
                if _k.endswith(" creature"):
                    return c.is_creature() and any(x.lower() == _k.split()[0] for x in c.subtypes)
                return _k in c.types
            pool = [c for c in ctrl.hand if ok(c)]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.hand.remove(c)
                pm = game.move_to_battlefield(c, ctrl)
                if pm is not None and _t:
                    pm.tapped = True
        return eff_put_from_hand
    if t in ("shuffle your library", "shuffle", "then shuffle"):
        return lambda game, ctrl, *a, **kw: game.rng.shuffle(ctrl.library)
    m = re.fullmatch(r"untap (another target creature you control|them|those creatures|that creature|it|all nonland "
                     r"permanents you control|all creatures you control|target creature you control|target permanent|"
                     r"all lands you control|each creature you control)", t)
    if m:
        def eff_untap20(game, ctrl, *a, _w=m.group(1), **kw):
            src = _src_perm(game, a)
            if _w in ("all nonland permanents you control",):
                for pm in ctrl.battlefield:
                    if not pm.card.is_land():
                        pm.tapped = False
            elif _w in ("all creatures you control", "each creature you control"):
                for pm in ctrl.creatures():
                    pm.tapped = False
            elif _w == "all lands you control":
                for pm in ctrl.battlefield:
                    if pm.card.is_land():
                        pm.tapped = False
            elif _w in ("them", "those creatures"):
                for pm in ctrl.creatures():
                    if pm.attacking is not None or pm.tapped:
                        pm.tapped = False
            elif _w in ("that creature", "it"):
                sj = _subj20(game, a, ctrl)
                if sj is not None:
                    sj.tapped = False
            else:
                pool = [pm for pm in ctrl.battlefield if pm.tapped and pm is not src
                        and (pm.is_creature() or _w == "target permanent")]
                if pool:
                    max(pool, key=lambda x: (x.power, _cmc_of(x))).tapped = False
        return eff_untap20
    m = re.fullmatch(r"(that creature|they|it|those creatures) gains? (haste|flying|trample|first strike|deathtouch|lifelink|"
                     r"vigilance|menace|indestructible|hexproof|double strike) until end of turn", t)
    if m:
        def eff_subj_kw(game, ctrl, *a, _k=m.group(2).replace(" ", "_"), **kw):
            sj = _subj20(game, a, ctrl)
            if sj is not None:
                sj.temp_keywords.add(_k)
                if _k == "haste":
                    sj.summoning_sick = False
        return eff_subj_kw
    m = re.fullmatch(r"(that creature|they each|it) gets? ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_subj_pump(game, ctrl, *a, _p=int(m.group(2)), _q=int(m.group(3)), **kw):
            sj = _subj20(game, a, ctrl)
            if sj is not None and sj in sj.controller.battlefield:
                sj.temp_pt = [sj.temp_pt[0] + _p, sj.temp_pt[1] + _q]
                game.sba()
        return eff_subj_pump
    m = re.fullmatch(r"discard (any number of|up to (\w+)) cards, then draw that many cards(?: plus (\w+))?", t)
    if m:
        def eff_rummage20(game, ctrl, *a, _cap=(_count_word(m.group(2)) if m.group(2) else 99),
                          _plus=(_count_word(m.group(3)) or 0) if m.group(3) else 0, **kw):
            lands = [c for c in ctrl.hand if c.is_land()]
            keep_l = 1 if sum(1 for pm in ctrl.battlefield if pm.card.is_land()) >= 5 else 3
            disc = lands[keep_l:][:_cap]
            for c in disc:
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
            ctrl.draw(len(disc) + _plus, game)
        return eff_rummage20
    m = re.fullmatch(r"(?:~|it|this creature) deals that much damage to (target opponent|each opponent|any target|target player)", t)
    if m:
        def eff_that_much_dmg(game, ctrl, *a, _w=m.group(1), **kw):
            n = _amt20(game)
            src = _src_perm(game, a)
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if not n or not opps:
                return
            for o in (opps if _w == "each opponent" else [min(opps, key=lambda o: o.life)]):
                game.deal_damage(src, o, n)
        return eff_that_much_dmg
    if t in ("exile a card from a graveyard", "exile target card from a graveyard", "exile up to one target card from a graveyard"):
        def eff_exile_gy1(game, ctrl, *a, **kw):
            pool = [(o, c) for o in game.opponents(ctrl) for c in o.graveyard]
            if pool:
                o, c = max(pool, key=lambda x: (x[1].is_creature(), x[1].cost.cmc if x[1].cost else 0))
                o.graveyard.remove(c)
                o.exile.append(c)
        return eff_exile_gy1
    m = re.fullmatch(r"tap (target permanent|target untapped creature|target nonland permanent an opponent controls|that creature|"
                     r"target artifact|target land|this creature|up to one target creature)", t)
    if m:
        def eff_tap20(game, ctrl, *a, _w=m.group(1), **kw):
            if _w == "this creature":
                src = _src_perm(game, a)
                if src is not None:
                    src.tapped = True
                return
            if _w == "that creature":
                sj = _subj20(game, a, ctrl)
                if sj is not None:
                    sj.tapped = True
                return
            pm = _opp_best(game, ctrl, lambda x: not x.tapped and (
                x.is_creature() if "creature" in _w else "artifact" in x.card.types if "artifact" in _w
                else x.card.is_land() if "land" in _w and "nonland" not in _w else not x.card.is_land()
                if "nonland" in _w else True))
            if pm is not None:
                pm.tapped = True
        return eff_tap20
    m = re.fullmatch(r"look at the top (\w+) cards of your library\. put (\w+) of them into your hand and the rest (on the bottom "
                     r"of your library in (?:a random|any) order|into your graveyard)", t)
    if m and (n := _count_word(m.group(1))) and (k := _count_word(m.group(2))):
        def eff_dig_k(game, ctrl, *a, _n=n, _k=k, _gy="graveyard" in m.group(3), **kw):
            top = [ctrl.library.pop() for _ in range(min(_n, len(ctrl.library)))]
            top.sort(key=lambda c: (not c.is_land(), c.cost.cmc if c.cost else 0), reverse=True)
            ctrl.hand.extend(top[:_k])
            rest = top[_k:]
            if _gy:
                ctrl.graveyard.extend(rest)
            else:
                ctrl.library[:0] = rest
        return eff_dig_k
    if t in ("discard that many cards",):
        def eff_disc_many(game, ctrl, *a, **kw):
            n = _amt20(game)
            if n:
                _human_or_auto_discard(game, ctrl, n)
        return eff_disc_many
    m = re.fullmatch(r"~ deals (\d+) damage to each (attacking|blocking|attacking or blocking|tapped|untapped) creature", t)
    if m:
        def eff_dmg_state(game, ctrl, *a, _n=int(m.group(1)), _w=m.group(2), **kw):
            src = _src_perm(game, a)
            for pl in game.players:
                for pm in list(pl.creatures()):
                    att, blk = pm.attacking is not None, bool(getattr(pm, "blocking", None))
                    if ((_w == "attacking" and att) or (_w == "blocking" and blk) or
                            (_w == "attacking or blocking" and (att or blk)) or (_w == "tapped" and pm.tapped)
                            or (_w == "untapped" and not pm.tapped)):
                        game.deal_damage(src, pm, _n)
            game.sba()
        return eff_dmg_state
    m = re.fullmatch(r"target creature with power (\d+) or less can't be blocked this turn", t)
    if m:
        def eff_small_unbl(game, ctrl, *a, _n=int(m.group(1)), **kw):
            pool = [pm for pm in ctrl.creatures() if pm.power <= _n]
            if pool:
                max(pool, key=lambda x: x.power).temp_keywords.add("unblockable")
        return eff_small_unbl
    m = re.fullmatch(r"creatures (target player|target opponent) controls get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_tp_creatures(game, ctrl, *a, _p=int(m.group(2)), _q=int(m.group(3)), **kw):
            if _p + _q >= 0:
                tgt = ctrl
            else:
                opps = [o for o in game.opponents(ctrl) if o.creatures()]
                if not opps:
                    return
                tgt = max(opps, key=lambda o: len(o.creatures()))
            for pm in tgt.creatures():
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
            game.sba()
        return eff_tp_creatures
    m = re.fullmatch(r"(?:this enchantment|this aura|~|this creature) deals (\d+) damage to (it|that creature's controller|"
                     r"that creature)", t)
    if m:
        def eff_dmg_subj(game, ctrl, *a, _n=int(m.group(1)), _w=m.group(2), **kw):
            sj = _subj20(game, a, ctrl)
            src = _src_perm(game, a)
            if sj is None:
                return
            game.deal_damage(src, sj.controller if "controller" in _w else sj, _n)
            game.sba()
        return eff_dmg_subj
    m = re.fullmatch(r"put up to (\w+) target (instant or sorcery|creature|) ?cards? from your graveyard on top of your library", t)
    if m and (n := _count_word(m.group(1))):
        def eff_gy_top_n(game, ctrl, *a, _n=n, _k=m.group(2), **kw):
            pool = [c for c in ctrl.graveyard if not _k or (_k == "creature" and c.is_creature())
                    or (_k == "instant or sorcery" and {"instant", "sorcery"} & c.types)]
            for c in sorted(pool, key=lambda x: -(x.cost.cmc if x.cost else 0))[:_n]:
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
        return eff_gy_top_n
    m = re.fullmatch(r"target creature and all other creatures with the same name as that creature get ([+-]\d+)/([+-]\d+) "
                     r"until end of turn", t)
    if m:
        def eff_same_name(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            if _p + _q < 0:
                pm = _opp_best(game, ctrl, lambda x: x.is_creature())
            else:
                pm = max(ctrl.creatures(), key=lambda x: x.power) if ctrl.creatures() else None
            if pm is None:
                return
            for pl in game.players:
                for x in pl.creatures():
                    if x.name == pm.name:
                        x.temp_pt = [x.temp_pt[0] + _p, x.temp_pt[1] + _q]
            game.sba()
        return eff_same_name
    m = re.fullmatch(r"(?:that player|target player|target opponent|each opponent|defending player) gets? (\w+) poison counters?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_poison_n(game, ctrl, *a, _n=n, _each=t.startswith("each"), **kw):
            tp = _that_player(game, ctrl)
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            for o in (opps if _each else ([tp] if tp is not None else opps[:1])):
                o.poison += _n
        return eff_poison_n
    m = re.fullmatch(r"put a \+1/\+1 counter on (another target creature you control|another target [a-z]+ you control|each other "
                     r"creature you control|target creature you control)", t)
    if m:
        def eff_ctr_other(game, ctrl, *a, _w=m.group(1), **kw):
            src = _src_perm(game, a)
            msub = re.match(r"another target ([a-z]+) you control", _w)
            sub = msub.group(1) if msub and msub.group(1) != "creature" else None
            pool = [pm for pm in ctrl.creatures() if (pm is not src or "another" not in _w and "other" not in _w)
                    and (sub is None or pm.has_subtype(sub))]
            if not pool:
                return
            if _w.startswith("each other"):
                for pm in pool:
                    game.add_counters(pm, "+1/+1", 1)
            else:
                game.add_counters(max(pool, key=lambda x: x.power), "+1/+1", 1)
        return eff_ctr_other
    if t in ("exile enchanted creature", "exile equipped creature"):
        def eff_exile_host(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            host = getattr(src, "enchanting", None)
            if host is not None and host in host.controller.battlefield:
                game.exile_permanent(host, "Aura")
        return eff_exile_host
    m = re.fullmatch(r"~ deals (\d+) damage to each of up to (\w+) targets", t)
    if m and (n := _count_word(m.group(2))):
        def eff_up_to_n(game, ctrl, *a, _d=int(m.group(1)), _n=n, **kw):
            src = _src_perm(game, a)
            done = 0
            for pm in sorted([pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)
                              and pm.toughness - pm.damage <= _d], key=lambda x: -x.power):
                if done >= _n:
                    break
                game.deal_damage(src, pm, _d)
                done += 1
            for o in sorted([o for o in game.opponents(ctrl) if not o.lost], key=lambda o: o.life):
                if done >= _n:
                    break
                game.deal_damage(src, o, _d)
                done += 1
            game.sba()
        return eff_up_to_n
    if t == "discard a card at random":
        def eff_disc_random(game, ctrl, *a, **kw):
            if ctrl.hand:
                c = game.rng.choice(ctrl.hand)
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
        return eff_disc_random
    m = re.fullmatch(r"(you|each opponent|target opponent|each player) loses? half (?:your|their) life,? rounded (up|down)", t)
    if m:
        def eff_half_life(game, ctrl, *a, _w=m.group(1), _up=m.group(2) == "up", **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            pls = ([ctrl] if _w == "you" else opps if _w == "each opponent" else game.players if _w == "each player"
                   else opps[:1])
            for pl in pls:
                pl.life -= (pl.life + (1 if _up else 0)) // 2
        return eff_half_life
    if t in ("its owner shuffles it into their library", "its owner shuffles it into their library afterward"):
        def eff_owner_shuffle(game, ctrl, *a, **kw):
            sj = _subj20(game, a, ctrl)
            if sj is None or sj not in sj.controller.battlefield:
                return
            pl = sj.controller
            pl.battlefield.remove(sj)
            if not sj.is_token:
                pl.library.append(getattr(sj.card, "_real", None) or sj.card)
                game.rng.shuffle(pl.library)
        return eff_owner_shuffle
    m = re.fullmatch(r"remove (a|an|one|two|\w+) (\+1/\+1|-1/-1|[a-z]+) counters? from (it|this creature|~|that creature)", t)
    if m and (n := _count_word(m.group(1))):
        def eff_rm_ctr(game, ctrl, *a, _n=n, _k=m.group(2), _w=m.group(3), **kw):
            pm = _subj20(game, a, ctrl) if _w in ("it", "that creature") else _src_perm(game, a)
            if pm is not None and pm.counters.get(_k, 0):
                pm.counters[_k] = max(0, pm.counters[_k] - _n)
        return eff_rm_ctr
    m = re.fullmatch(r"draw (?:cards|a number of cards) equal to (?:its|that creature's) (power|toughness|mana value)", t)
    if m:
        def eff_draw_eq(game, ctrl, *a, _w=m.group(1), **kw):
            sj = _subj20(game, a, ctrl)
            if sj is None:
                return
            n = (sj.power if _w == "power" else sj.toughness if _w == "toughness" else _cmc_of(sj))
            if n > 0:
                ctrl.draw(min(n, 15), game)
        return eff_draw_eq
    m = re.fullmatch(r"sacrifice (that creature|it|those creatures|that token|them) at (the beginning of the next end step|end of combat)", t)
    if m:
        def eff_sac_later20(game, ctrl, *a, **kw):
            pm = _subj20(game, a, ctrl)
            if pm is None:
                return
            game.delayed_end.append(lambda g, _pm=pm: g.to_graveyard(_pm, "sacrificio (fin de turno)")
                                    if _pm in _pm.controller.battlefield else None)
        return eff_sac_later20
    m = re.fullmatch(r"target creature gains (fear|intimidate|shadow|horsemanship|flanking|shroud|protection from [a-z]+) "
                     r"until end of turn", t)
    if m:
        def eff_tg_kw2(game, ctrl, *a, _k=m.group(1).split()[0], **kw):
            if ctrl.creatures():
                max(ctrl.creatures(), key=lambda x: x.power).temp_keywords.add(_k)
        return eff_tg_kw2
    m = re.fullmatch(r"target (instant or sorcery|instant|sorcery) card in your graveyard gains flashback until end of turn(?:\. "
                     r"the flashback cost is equal to its mana cost)?", t)
    if m:
        def eff_snap(game, ctrl, *a, _k=m.group(1), **kw):
            pool = [c for c in ctrl.graveyard if ({"instant", "sorcery"} & c.types) and c.cost is not None
                    and not getattr(c, "gy_play", None) and (_k == "instant or sorcery" or _k in c.types)]
            if pool:
                c = max(pool, key=lambda x: x.cost.cmc)
                c.gy_play = {"mode": "flashback", "cost": c.cost, "after": "exile"}
                game.delayed_end.append(lambda g, _c=c: setattr(_c, "gy_play", None))
        return eff_snap
    m = re.fullmatch(r"creatures without (flying|reach|flying or reach) can't block this turn", t)
    if m:
        def eff_noblock(game, ctrl, *a, _k=m.group(1), **kw):
            for o in game.opponents(ctrl):
                for pm in o.creatures():
                    if not (pm.has("flying") or ("reach" in _k and pm.has("reach"))):
                        pm.temp_keywords.add("cant_block")
        return eff_noblock
    if t in ("that land doesn't untap during its controller's next untap step",
             "that creature doesn't untap during its controller's next untap step",
             "it doesn't untap during its controller's next untap step",
             "those creatures don't untap during their controllers' next untap steps"):
        def eff_freeze20(game, ctrl, *a, **kw):
            sj = _subj20(game, a, ctrl)
            if sj is not None:
                sj.frozen = True
        return eff_freeze20
    m = re.fullmatch(r"(?:that player|each opponent|target opponent) loses (\d+) life unless (?:they pay|that player pays) "
                     r"((?:\{[^}]+\})+)", t)
    if m:
        def eff_unless_pay(game, ctrl, *a, _n=int(m.group(1)), _c=m.group(2), **kw):
            try:
                cost = parse_cost("".join(re.findall(r"\{([^}]+)\}", _c)))
            except ValueError:
                cost = None
            tp = _that_player(game, ctrl)
            opps = [tp] if (tp is not None and t.startswith("that")) else [o for o in game.opponents(ctrl) if not o.lost]
            if t.startswith("target"):
                opps = opps[:1]
            for o in opps:
                if cost is not None and o.can_pay(cost) and o.life <= 10:
                    o.pay(cost)
                else:
                    o.life -= _n
        return eff_unless_pay
    m = re.fullmatch(r"(?:this aura|this enchantment|~) deals (\d+) damage to (?:that creature's|enchanted creature's) controller", t)
    if m:
        def eff_aura_ctrl_dmg(game, ctrl, *a, _n=int(m.group(1)), **kw):
            src = _src_perm(game, a)
            host = getattr(src, "enchanting", None) or _subj20(game, a, ctrl)
            if host is not None:
                game.deal_damage(src, host.controller, _n)
        return eff_aura_ctrl_dmg
    if t in ("put those cards onto the battlefield under your control", "put that card onto the battlefield under your control"):
        def eff_put_those(game, ctrl, *a, **kw):
            last = getattr(game, "_last_exiled", None) or []
            for pl, c in list(last):
                if c in pl.exile and not ({"instant", "sorcery"} & c.types):
                    pl.exile.remove(c)
                    game.move_to_battlefield(c, ctrl)
        return eff_put_those
    # ── batch 19 ──
    if t.startswith("each player may search their library for up to two basic land cards, put them onto the battlefield"):
        def eff_vet(game, ctrl, *a, **kw):
            for pl in game.players:
                if pl.lost:
                    continue
                basics = [c for c in pl.library if c.is_land() and "basic" in c.supertypes][:2]
                for c in basics:
                    pl.library.remove(c)
                    game.move_to_battlefield(c, pl)
                game.rng.shuffle(pl.library)
        return eff_vet
    m = re.fullmatch(r"(?:it|~|this creature) deals damage equal to the number of ([a-z]+?)s you control to each non-\1 creature", t)
    if m:
        def eff_thunder(game, ctrl, *a, _k=m.group(1), **kw):
            src = _src_perm(game, a)
            n = sum(1 for pm in ctrl.creatures() if pm.has_subtype(_k))
            for pl in game.players:
                for pm in list(pl.creatures()):
                    if not pm.has_subtype(_k):
                        game.deal_damage(src, pm, n)
            game.sba()
        return eff_thunder
    m = re.fullmatch(r"return target creature card from your graveyard to the battlefield\. you gain life equal to its mana value", t)
    if m:
        def eff_hospitaller(game, ctrl, *a, **kw):
            pool = [c for c in ctrl.graveyard if c.is_creature()]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.graveyard.remove(c)
                game.move_to_battlefield(c, ctrl)
                game.gain_life(ctrl, c.cost.cmc if c.cost else 0)
        return eff_hospitaller
    m = re.fullmatch(r"return each creature your opponents control with toughness x or less to its owner's hand, where x "
                     r"is the number of (\w+?)s you control", t)
    if m:
        def eff_fleets(game, ctrl, *a, _k=m.group(1), **kw):
            n = sum(1 for pm in ctrl.battlefield if pm.has_subtype(_k))
            for o in game.opponents(ctrl):
                for pm in list(o.creatures()):
                    if pm.toughness <= n:
                        _bounce_pm(game, pm)
        return eff_fleets
    if re.fullmatch(r"creatures you control gain trample and get \+x/\+x until end of turn, where x is the greatest power "
                    r"among creatures you control", t):
        def eff_ibex(game, ctrl, *a, **kw):
            n = max((pm.power for pm in ctrl.creatures()), default=0)
            for pm in ctrl.creatures():
                pm.temp_pt = [pm.temp_pt[0] + n, pm.temp_pt[1] + n]
                pm.temp_keywords.add("trample")
        return eff_ibex
    m = re.fullmatch(r"each non-(\w+) creature gets -x/-x until end of turn, where x is the number of \w+? you control", t)
    if m:
        def eff_olivia(game, ctrl, *a, _k=m.group(1), **kw):
            n = sum(1 for pm in ctrl.creatures() if pm.has_subtype(_k))
            for pl in game.players:
                for pm in pl.creatures():
                    if not pm.has_subtype(_k):
                        pm.temp_pt = [pm.temp_pt[0] - n, pm.temp_pt[1] - n]
            game.sba()
        return eff_olivia
    if t.startswith("put target creature card from an opponent's graveyard onto the battlefield tapped under your control, "
                    "then exile that player's graveyard"):
        def eff_nurgle(game, ctrl, *a, **kw):
            pool = [(o, c) for o in game.opponents(ctrl) for c in o.graveyard if c.is_creature()]
            if not pool:
                return
            o, c = max(pool, key=lambda x: (x[1].cost.cmc if x[1].cost else 0))
            o.graveyard.remove(c)
            pm = game.move_to_battlefield(c, ctrl)
            if pm is not None:
                pm.tapped = True
            o.exile.extend(o.graveyard)
            o.graveyard.clear()
        return eff_nurgle
    if t == "put x +1/+1 counters on target creature you control. it deals damage equal to its power to each other creature":
        def eff_nova(game, ctrl, *a, **kw):
            n = max(0, int(getattr(game, "spell_x", 0) or 0))
            if not ctrl.creatures():
                return
            src = max(ctrl.creatures(), key=lambda x: x.toughness)
            if n:
                game.add_counters(src, "+1/+1", n)
            for pl in game.players:
                for pm in list(pl.creatures()):
                    if pm is not src:
                        game.deal_damage(src, pm, max(0, src.power))
            game.sba()
        return eff_nova
    if t == "you may cast target instant or sorcery card from an opponent's graveyard without paying its mana cost":
        def eff_plunder(game, ctrl, *a, **kw):
            pool = [(o, c) for o in game.opponents(ctrl) for c in o.graveyard
                    if {"instant", "sorcery"} & c.types and getattr(c, "on_cast_resolve", None) and c.cost is not None]
            if not pool:
                return
            o, c = max(pool, key=lambda x: x[1].cost.cmc)
            o.graveyard.remove(c)
            ctrl.hand.append(c)
            orig = c.cost
            c.cost = Cost(generic=0, pips=())
            try:
                ok = game.cast(ctrl, c)
            finally:
                c.cost = orig
            if not ok and c in ctrl.hand:
                ctrl.hand.remove(c)
                o.graveyard.append(c)
        return eff_plunder
    if t == "return all legendary creature cards from your graveyard to your hand":
        def eff_lychguard(game, ctrl, *a, **kw):
            for c in [c for c in ctrl.graveyard if c.is_creature() and c.is_legendary()]:
                ctrl.graveyard.remove(c)
                ctrl.hand.append(c)
        return eff_lychguard
    m = re.fullmatch(r"return target creature card with mana value less than or equal to (?:~|this creature)'s power from "
                     r"your graveyard to the battlefield.*", t)
    if m:
        def eff_winter(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            p = getattr(src, "power", 0) or 0
            pool = [c for c in ctrl.graveyard if c.is_creature() and (c.cost.cmc if c.cost else 0) <= p]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.graveyard.remove(c)
                game.move_to_battlefield(c, ctrl)
        return eff_winter
    if t.startswith("target opponent exiles cards from the top of their library until they exile a nonland card. until "
                    "end of turn, you may cast that card without paying its mana cost"):
        def eff_stolen(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if o.library]
            if not opps:
                return
            o = opps[0]
            while o.library:
                c = o.library.pop()
                if c.is_land():
                    o.exile.append(c)
                    continue
                ctrl.hand.append(c)
                orig = c.cost
                c.cost = Cost(generic=0, pips=())
                ok = False
                try:
                    ok = c.cost is not None and game.cast(ctrl, c)
                finally:
                    c.cost = orig
                if not ok and c in ctrl.hand:
                    ctrl.hand.remove(c)
                    o.exile.append(c)
                break
        return eff_stolen
    m = re.fullmatch(r"put a shield counter on (each of up to (\w+) target creatures|target creature you control|each "
                     r"creature you control)", t)
    if m:
        def eff_shield(game, ctrl, *a, _n=(_count_word(m.group(2)) if m.group(2) else (1 if "target" in m.group(1) else 99)),
                       **kw):
            for pm in sorted(ctrl.creatures(), key=lambda x: -(x.power + x.toughness))[:_n]:
                game.add_counters(pm, "shield", 1)
        return eff_shield
    if t.startswith("put a shield counter on target noncommander creature you don't control. you gain control of that creature"):
        def eff_broker(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                    if not o.is_commander(pm.card) and game.can_target(ctrl, pm)]
            if not pool:
                return
            pm = max(pool, key=lambda x: (x.power + x.toughness))
            game.add_counters(pm, "shield", 1)
            o = pm.controller
            o.battlefield.remove(pm)
            pm.controller = ctrl
            ctrl.battlefield.append(pm)
            game.log(f"{ctrl.name} toma el control de {pm.name}")
        return eff_broker
    if t.startswith("target player shuffles any number of target cards from their graveyard into their library"):
        def eff_loam(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if any(c.is_creature() for c in o.graveyard)]
            if opps:
                o = max(opps, key=lambda x: sum(1 for c in x.graveyard if c.is_creature()))
                o.library.extend(o.graveyard)
                o.graveyard.clear()
                game.rng.shuffle(o.library)
        return eff_loam
    if t == "double the power and toughness of each creature you control until end of turn":
        def eff_unnatural(game, ctrl, *a, **kw):
            for pm in ctrl.creatures():
                pm.temp_pt = [pm.temp_pt[0] + max(0, pm.power), pm.temp_pt[1] + max(0, pm.toughness)]
        return eff_unnatural
    if t in ("you may put that many +1/+1 counters on each creature you control. do this only once each turn",
             "you may put that many +1/+1 counters on each creature you control"):
        def eff_nykthos(game, ctrl, *a, **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or 0
            if getattr(ctrl, "_nyk_turn", None) == game.turn or not isinstance(n, int) or n <= 0:
                return
            ctrl._nyk_turn = game.turn
            for pm in ctrl.creatures():
                game.add_counters(pm, "+1/+1", n)
        return eff_nykthos
    if t.startswith("reveal the top card of your library. if it's a creature card, put it onto the battlefield. otherwise, "
                    "you may put that card on the bottom of your library"):
        def eff_lurking(game, ctrl, *a, **kw):
            if not ctrl.library:
                return
            top = ctrl.library[-1]
            if top.is_creature():
                ctrl.library.pop()
                game.move_to_battlefield(top, ctrl)
            elif not top.is_land() or sum(1 for pm in ctrl.battlefield if pm.card.is_land()) >= 6:
                ctrl.library.insert(0, ctrl.library.pop())
        return eff_lurking
    if t.startswith("choose an opponent at random. ~ deals damage equal to that spell's mana value to that player"):
        def eff_vial(game, ctrl, *a, **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            c = k.get("card")
            n = c.cost.cmc if (c is not None and c.cost) else 0
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if n and opps:
                game.deal_damage(_src_perm(game, a), game.rng.choice(opps), n)
        return eff_vial
    # ── batch 18 ──
    def _free_cast18(game, ctrl, c):
        orig = c.cost
        c.cost = Cost(generic=0, pips=())
        ctrl.hand.append(c)
        ok = False
        try:
            ok = game.cast(ctrl, c)
        finally:
            c.cost = orig
            if not ok and c in ctrl.hand:
                ctrl.hand.remove(c)
        return ok

    if t.startswith("exile the top card of each player's library, then you may cast any number of spells from among "
                    "those cards without paying their mana costs"):
        def eff_etali(game, ctrl, *a, **kw):
            for pl in game.players:
                if pl.lost or not pl.library:
                    continue
                c = pl.library.pop()
                if not c.is_land() and c.cost is not None and (c.is_creature() or getattr(c, "on_cast_resolve", None)
                                                                or {"artifact", "enchantment"} & c.types):
                    if _free_cast18(game, ctrl, c):
                        continue
                pl.exile.append(c)
        return eff_etali
    m = re.fullmatch(r"(?:~|this creature|it) deals (\d+) damage to each of (x|\w+) targets", t)
    if m:
        def eff_meteor(game, ctrl, *a, _d=int(m.group(1)), _n=m.group(2), **kw):
            n = max(0, int(getattr(game, "spell_x", 0) or 0)) if _n == "x" else (_count_word(_n) or 0)
            src = _src_perm(game, a)
            pool = sorted([pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)],
                          key=lambda x: (x.toughness - x.damage > _d, -x.power))
            done = 0
            for pm in pool:
                if done >= n:
                    break
                game.deal_damage(src, pm, _d)
                done += 1
            opps = sorted([o for o in game.opponents(ctrl) if not o.lost], key=lambda o: o.life)
            for o in opps:
                if done >= n:
                    break
                game.deal_damage(src, o, _d)
                done += 1
            game.sba()
        return eff_meteor
    if t in ("it deals that much damage to each other opponent", "~ deals that much damage to each other opponent"):
        def eff_omnivore(game, ctrl, *a, **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            n, d = k.get("amount") or 0, k.get("defender")
            src = _src_perm(game, a)
            for o in game.opponents(ctrl):
                if o is not d and not o.lost and isinstance(n, int) and n > 0:
                    game.deal_damage(src, o, n)
        return eff_omnivore
    m = re.fullmatch(r"put x \+1/\+1 counters on target creature you control, where x is the power of the creature "
                     r"that died", t)
    if m:
        def eff_deaths_presence(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None)
            n = max(0, getattr(sj, "power", 0) or 0)
            pool = [pm for pm in ctrl.creatures() if pm is not sj]
            if n and pool:
                game.add_counters(max(pool, key=lambda x: x.power), "+1/+1", n)
        return eff_deaths_presence
    if t == "each other creature you control gets +x/+x until end of turn, where x is this creature's power":
        def eff_beastmaster(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            n = max(0, getattr(src, "power", 0) or 0)
            for pm in ctrl.creatures():
                if pm is not src:
                    pm.temp_pt = [pm.temp_pt[0] + n, pm.temp_pt[1] + n]
        return eff_beastmaster
    if t == "return each creature without a +1/+1 counter on it to its owner's hand":
        def eff_wave(game, ctrl, *a, **kw):
            for pl in game.players:
                for pm in list(pl.creatures()):
                    if not pm.counters.get("+1/+1"):
                        _bounce_pm(game, pm)
        return eff_wave
    if t == "return all permanents of the color of your choice to their owners' hands":
        def eff_washout(game, ctrl, *a, **kw):
            def cols(pm):
                return {x for pp in (getattr(pm.card.cost, "pips", None) or ()) for x in str(pp).upper() if x in "WUBRG"}
            best, score = None, -99
            for c in "WUBRG":
                sc = sum(1 for o in game.opponents(ctrl) for pm in o.battlefield if c in cols(pm)) - \
                    sum(1 for pm in ctrl.battlefield if c in cols(pm))
                if sc > score:
                    best, score = c, sc
            for pl in game.players:
                for pm in list(pl.battlefield):
                    if best in cols(pm):
                        _bounce_pm(game, pm)
        return eff_washout
    if t == "you get an experience counter":
        def eff_exp(game, ctrl, *a, **kw):
            ctrl.experience = getattr(ctrl, "experience", 0) + 1
        return eff_exp
    if t.startswith("choose target creature card in your graveyard. if that card's mana value is less than or equal to "
                    "the number of experience counters you have, return it to the battlefield"):
        def eff_meren(game, ctrl, *a, **kw):
            pool = [c for c in ctrl.graveyard if c.is_creature()]
            if not pool:
                return
            exp = getattr(ctrl, "experience", 0)
            ok = [c for c in pool if (c.cost.cmc if c.cost else 0) <= exp]
            c = max(ok or pool, key=lambda x: (x.cost.cmc if x.cost else 0))
            ctrl.graveyard.remove(c)
            if c in ok:
                game.move_to_battlefield(c, ctrl)
            else:
                ctrl.hand.append(c)
        return eff_meren
    if t.startswith("return that card to the battlefield under its owner's control. return this card to the battlefield "
                    "attached to that creature at the beginning of the next end step"):
        def eff_gift(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            host_card = getattr(game, "_gift_host", None)
            sj = getattr(game, "_trigger_subject", None)
            c = getattr(sj, "card", None) if sj is not None else host_card
            c = getattr(c, "_real", None) or c
            for pl in game.players:
                if c is not None and c in pl.graveyard:
                    pl.graveyard.remove(c)
                    game.move_to_battlefield(c, pl)
                    break
            ac = getattr(getattr(src, "card", None), "_real", None) or getattr(src, "card", None)

            def _back(g, _ac=ac, _c=ctrl):
                for pl in g.players:
                    if _ac is not None and _ac in pl.graveyard:
                        pl.graveyard.remove(_ac)
                        g.move_to_battlefield(_ac, _c)
                        return
            game.delayed_end.append(_back)
        return eff_gift
    m = re.fullmatch(r"each player may put two \+1/\+1 counters on a creature they control\. (goad each creature that had "
                     r"counters put on it this way|if a player does, creatures that player controls can't attack you[^.]*)",
                     t.split(". (")[0])
    if m:
        def eff_ant(game, ctrl, *a, _goad=m.group(1).startswith("goad"), **kw):
            for pl in game.players:
                cr = pl.creatures()
                if not cr or pl.lost:
                    continue
                if pl is not ctrl and not _goad:
                    continue                       # Advokist: los rivales no aceptan (no podrían atacarte)
                pm = max(cr, key=lambda x: x.power)
                game.add_counters(pm, "+1/+1", 2)
                if _goad and pl is not ctrl:
                    pm.goaded = True
        return eff_ant
    if t.startswith("reveal cards from the top of your library until you reveal a creature card. put that card into "
                    "your hand and the rest on the bottom of your library in a random order"):
        def eff_whistle(game, ctrl, *a, _ctr="+1/+1 counters" in t, **kw):
            rev = []
            found = None
            while ctrl.library:
                c = ctrl.library.pop()
                if c.is_creature():
                    found = c
                    break
                rev.append(c)
            game.rng.shuffle(rev)
            ctrl.library[:0] = rev
            if found is not None:
                ctrl.hand.append(found)
                if _ctr and ctrl.creatures() and found.cost is not None:
                    game.add_counters(max(ctrl.creatures(), key=lambda x: x.power), "+1/+1", found.cost.cmc)
        return eff_whistle
    # ── batch 17 ──
    m = re.fullmatch(r"you may exile up to (\w+) other target creatures from the battlefield and/or creature cards "
                     r"from graveyards(?: until [^.]+)?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_serenity(game, ctrl, *a, _n=n, **kw):
            src = _src_perm(game, a)
            pool = sorted([pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)],
                          key=lambda x: -(_cmc_of(x) + x.power))
            taken = []
            for pm in pool[:_n]:
                if game.exile_permanent(pm, "Angel of Serenity"):
                    taken.append(getattr(pm.card, "_real", None) or pm.card)
            if len(taken) < _n:                    # el resto: criaturas de tu cementerio (vuelven a tu mano)
                gy = sorted([c for c in ctrl.graveyard if c.is_creature()], key=lambda c: -(c.cost.cmc if c.cost else 0))
                for c in gy[:_n - len(taken)]:
                    ctrl.graveyard.remove(c)
                    ctrl.exile.append(c)
                    taken.append(c)
            if src is not None:
                src._serenity = taken
        return eff_serenity
    if t == "return the exiled cards to their owners' hands":
        def eff_serenity_back(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            for c in list(getattr(src, "_serenity", None) or []):
                for pl in game.players:
                    if c in pl.exile:
                        pl.exile.remove(c)
                        pl.hand.append(c)
                        break
            if src is not None:
                src._serenity = []
        return eff_serenity_back

    m = re.fullmatch(r"(this creature|~|it) gets ([+-]\d+)/([+-]\d+) and gains ([a-z ,]+?) until end of turn", t)
    if m:
        _kw = {k.strip().replace(" ", "_") for k in re.split(r",| and ", m.group(4)) if k.strip()}

        def eff_self_pump_kw(game, ctrl, *a, _p=int(m.group(2)), _q=int(m.group(3)), _k=_kw, _it=m.group(1) == "it",
                             **kw):
            pm = _it_perm(game, a, ctrl) if _it else _src_perm(game, a)
            if pm is not None and pm in pm.controller.battlefield:
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                pm.temp_keywords |= _k
        return eff_self_pump_kw
    m = re.fullmatch(r"put (x|\w+) -1/-1 counters? on each creature", t)
    if m:
        def eff_bsz(game, ctrl, *a, _n=m.group(1), **kw):
            n = max(0, int(getattr(game, "spell_x", 0) or 0)) if _n == "x" else (_count_word(_n) or 0)
            if n:
                for pl in game.players:
                    for pm in list(pl.creatures()):
                        game.add_counters(pm, "-1/-1", n)
                game.sba()
        return eff_bsz
    if t == "you may discard all the cards in your hand. if you do, draw that many cards":
        def eff_forgotten(game, ctrl, *a, **kw):
            lands = sum(1 for c in ctrl.hand if c.is_land())
            if ctrl.hand and (lands >= 2 or lands * 2 >= len(ctrl.hand)):
                n = len(ctrl.hand)
                for c in list(ctrl.hand):
                    ctrl.hand.remove(c)
                    game.discard_card(ctrl, c)
                ctrl.draw(n, game)
        return eff_forgotten
    m = re.fullmatch(r"return this card to (its owner's hand|the battlefield at the beginning of the next end step)", t)
    if m:
        def eff_aura_back(game, ctrl, *a, _bf="battlefield" in m.group(1), **kw):
            src = _src_perm(game, a)
            c = getattr(src, "card", None)
            c = getattr(c, "_real", None) or c
            if c is None:
                return

            def _mv(g, _c=c):
                for pl in g.players:
                    if _c in pl.graveyard:
                        pl.graveyard.remove(_c)
                        if _bf:
                            g.move_to_battlefield(_c, pl)
                        else:
                            pl.hand.append(_c)
                        return True
                return False
            if _bf:
                game.delayed_end.append(_mv)
            elif not _mv(game):
                from engine import StackObject
                game.stack.append(StackObject(ctrl, _mv, source=None, label=f"vuelve {c.name}"))
        return eff_aura_back
    if t == "draw cards equal to the greatest mana value among artifacts you control":
        return lambda game, ctrl, *a, **kw: ctrl.draw(min(15, max(
            (_cmc_of(pm) for pm in ctrl.battlefield if "artifact" in pm.card.types), default=0)), game)
    if t == "each player's life total becomes the highest life total among all players":
        def eff_arbiter(game, ctrl, *a, **kw):
            hi = max(pl.life for pl in game.players if not pl.lost)
            for pl in game.players:
                if not pl.lost:
                    pl.life = hi
        return eff_arbiter
    m = re.fullmatch(r"put target nonland permanent into its owner's library just beneath the top (x|\w+) cards of that library", t)
    if m:
        def eff_absent(game, ctrl, *a, _n=m.group(1), **kw):
            n = max(0, int(getattr(game, "spell_x", 0) or 0)) if _n == "x" else (_count_word(_n) or 0)
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield if not pm.card.is_land()
                    and game.can_target(ctrl, pm)]
            if not pool:
                return
            pm = max(pool, key=_cmc_of)
            pl = pm.controller
            pl.battlefield.remove(pm)
            if pm.card.on_leave:
                pm.card.on_leave(game, pl, pm)
            if not pm.is_token:
                real = getattr(pm.card, "_real", None) or pm.card
                owner = game.commander_owner(real)
                if owner is not None:
                    owner.command.append(real)
                else:
                    pl.library.insert(max(0, len(pl.library) - n), real)
        return eff_absent
    m = re.fullmatch(r"that player chooses up to (\w+) creatures? they control, then sacrifices the rest", t)
    if m and (n := _count_word(m.group(1))):
        def eff_archfiend(game, ctrl, *a, _n=n, **kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                return
            cr = sorted(pl.creatures(), key=lambda x: -(x.power + x.toughness))
            for pm in cr[_n:]:
                game.to_graveyard(pm, "sacrificio")
        return eff_archfiend
    if t == "put all creature cards from all graveyards onto the battlefield under your control":
        def eff_dark_realms(game, ctrl, *a, **kw):
            for pl in game.players:
                for c in [c for c in pl.graveyard if c.is_creature()]:
                    pl.graveyard.remove(c)
                    game.move_to_battlefield(c, ctrl)
        return eff_dark_realms
    m = re.fullmatch(r"each player draws (x|\w+) cards?", t)
    if m and m.group(1) == "x":
        def eff_each_draw_x(game, ctrl, *a, **kw):
            n = max(0, int(getattr(game, "spell_x", 0) or 0))
            for pl in game.players:
                if not pl.lost:
                    pl.draw(n, game)
        return eff_each_draw_x
    if t == "each player chooses a creature they control. destroy the rest":
        def eff_reckoning(game, ctrl, *a, **kw):
            for pl in game.players:
                cr = pl.creatures()
                if not cr:
                    continue
                keep = max(cr, key=lambda x: (pl.is_commander(x.card), x.power + x.toughness))
                for pm in list(cr):
                    if pm is not keep and not pm.has("indestructible"):
                        game.to_graveyard(pm, "destruida")
        return eff_reckoning
    if t == "draw cards equal to the power of target creature you control":
        return lambda game, ctrl, *a, **kw: ctrl.draw(min(15, max((pm.power for pm in ctrl.creatures()),
                                                                  default=0)), game)
    if t in ("target player sacrifices an attacking creature of their choice",
             "target player sacrifices an attacking creature"):
        def eff_wing_shards(game, ctrl, *a, **kw):
            for o in game.opponents(ctrl):
                pool = [pm for pm in o.creatures() if pm.attacking is not None]
                if pool:
                    _human_or_auto_sacrifice(game, o, "Sacrificá una criatura atacante", pool=pool)
                    return
        return eff_wing_shards
    m = re.fullmatch(r"each player exiles all (artifact|enchantment) cards from their graveyard, then sacrifices all "
                     r"\1s they control, then puts all cards they exiled this way onto the battlefield", t)
    if m:
        def eff_scrap(game, ctrl, *a, _k=m.group(1), **kw):
            pend = {}
            for pl in game.players:
                pend[id(pl)] = [c for c in pl.graveyard if _k in c.types]
                for c in pend[id(pl)]:
                    pl.graveyard.remove(c)
            for pl in game.players:
                for pm in list(pl.battlefield):
                    if _k in pm.card.types:
                        game.to_graveyard(pm, "sacrificio")
            for pl in game.players:
                for c in pend[id(pl)]:
                    game.move_to_battlefield(c, pl)
        return eff_scrap

    if t.startswith("each player puts a vow counter on a creature they control and sacrifices the rest"):
        def eff_promise(game, ctrl, *a, **kw):
            for pl in game.players:
                cr = pl.creatures()
                if not cr:
                    continue
                keep = max(cr, key=lambda x: (pl.is_commander(x.card), x.power + x.toughness))
                keep.counters["vow"] = keep.counters.get("vow", 0) + 1
                for pm in list(cr):
                    if pm is not keep:
                        game.to_graveyard(pm, "sacrificio")
        return eff_promise
    if t.startswith("each player chooses an artifact, a creature, an enchantment, and a planeswalker from among the "
                    "nonland permanents they control, then sacrifices the rest"):
        def eff_gearhulk(game, ctrl, *a, **kw):
            for pl in game.players:
                keep = set()
                for k in ("artifact", "creature", "enchantment", "planeswalker"):
                    pool = [pm for pm in pl.battlefield if not pm.card.is_land() and k in pm.card.types
                            and id(pm) not in keep]
                    if pool:
                        keep.add(id(max(pool, key=lambda x: (pl.is_commander(x.card), _cmc_of(x)))))
                for pm in list(pl.battlefield):
                    if not pm.card.is_land() and id(pm) not in keep:
                        game.to_graveyard(pm, "sacrificio")
        return eff_gearhulk
    m = re.fullmatch(r"tap target creature\. (?:metalcraft — )?if you control (\w+) or more artifacts, exile that creature", t)
    if m and (n := _count_word(m.group(1))):
        def eff_dispatch(game, ctrl, *a, _n=n, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)]
            if not pool:
                return
            pm = max(pool, key=lambda x: (x.power, _cmc_of(x)))
            pm.tapped = True
            if sum(1 for x in ctrl.battlefield if "artifact" in x.card.types) >= _n:
                game.exile_permanent(pm, "Dispatch")
        return eff_dispatch
    m = re.fullmatch(r"creatures you control have base power and toughness (\d+)/(\d+) until end of turn", t)
    if m:
        def eff_biomass(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            for pm in ctrl.creatures():
                old = pm.set_base_pt
                pm.set_base_pt = (_p, _q)
                game.delayed_end.append(lambda g, _pm=pm, _o=old: setattr(_pm, "set_base_pt", _o))
        return eff_biomass
    m = re.fullmatch(r"sacrifice (?:it|~|this creature) unless \{([wubrg])\} was spent to cast it", t)
    if m:
        def eff_hussar(game, ctrl, *a, _c=m.group(1).upper(), **kw):
            src = _src_perm(game, a)
            if src is None or src not in src.controller.battlefield:
                return
            ok = any(_c in (ctrl.produced(pm) or {}) for pm in ctrl.battlefield
                     if pm.card.produces is not None and pm is not src)
            if not ok:
                game.to_graveyard(src, f"no se gastó {{{_c}}}")
        return eff_hussar
    if t.startswith("for each opponent, you may put up to one target creature card from that player's graveyard "
                    "onto the battlefield under your control"):
        def eff_sepulchral(game, ctrl, *a, **kw):
            for o in game.opponents(ctrl):
                pool = [c for c in o.graveyard if c.is_creature()]
                if pool:
                    c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                    o.graveyard.remove(c)
                    game.move_to_battlefield(c, ctrl)
        return eff_sepulchral
    if t.startswith("choose a card at random in your graveyard. if it's a creature card, put it onto the battlefield"):
        def eff_deadbridge(game, ctrl, *a, **kw):
            if not ctrl.graveyard:
                return
            c = game.rng.choice(ctrl.graveyard)
            ctrl.graveyard.remove(c)
            if c.is_creature():
                game.move_to_battlefield(c, ctrl)
            else:
                ctrl.hand.append(c)
        return eff_deadbridge
    if t in ("it deals damage equal to its power to target player or planeswalker",
             "it deals damage equal to its power to any target",
             "it deals damage equal to its power to target opponent"):
        def eff_sv(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None) or _src_perm(game, a)
            n = max(0, getattr(sj, "power", 0) or 0)
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if n and opps:
                game.deal_damage(sj, min(opps, key=lambda o: o.life), n)
        return eff_sv
    if t in ("you may have target attacking creature gain double strike until end of turn",
             "target attacking creature gains double strike until end of turn"):
        def eff_heritage(game, ctrl, *a, **kw):
            pool = [pm for pm in ctrl.creatures() if pm.attacking is not None]
            if pool:
                max(pool, key=lambda x: x.power).temp_keywords.add("double_strike")
        return eff_heritage
    # ── batch 16: staples de Commander ──
    def _x(game):
        return max(0, int(getattr(game, "spell_x", 0) or 0))

    def _free_cast(game, ctrl, card):
        """Lanza `card` de la mano sin pagar su coste de maná."""
        orig = card.cost
        card.cost = Cost(generic=0, pips=())
        try:
            return game.cast(ctrl, card)
        finally:
            card.cost = orig

    def _greatest_power(ctrl):
        return max((pm.power for pm in ctrl.creatures()), default=0)

    m = re.fullmatch(r"the owner of target (nonland )?permanent shuffles it into their library, then "
                     r"(reveals the top card of their library\. if it's a permanent card, they put it onto the "
                     r"battlefield|draws (\w+) cards)", t)
    if m:
        def eff_chaos_warp(game, ctrl, *a, _rev="reveals" in m.group(2),
                           _n=_count_word(m.group(3)) if m.group(3) else 0, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield if game.can_target(ctrl, pm)
                    and not pm.card.is_land()]
            if not pool:
                return
            pm = max(pool, key=lambda x: (x.is_creature(), _cmc_of(x)))
            pl = pm.controller
            pl.battlefield.remove(pm)
            if pm.card.on_leave:
                pm.card.on_leave(game, pl, pm)
            if not pm.is_token:
                real = getattr(pm.card, "_real", None) or pm.card
                owner = game.commander_owner(real)
                if owner is not None:
                    owner.command.append(real)
                else:
                    pl.library.append(real)
                    game.rng.shuffle(pl.library)
            game.log(f"{pm.name} se baraja en la biblioteca de {pl.name}")
            if _rev and pl.library:
                top = pl.library[-1]
                if {"creature", "artifact", "enchantment", "planeswalker", "land", "battle"} & top.types:
                    pl.library.pop()
                    game.move_to_battlefield(top, pl)
            if _n:
                pl.draw(_n, game)
        return eff_chaos_warp
    m = re.fullmatch(r"~ deals (x|\d+) damage to each (nonartifact |non-?[a-z]+ )?creature( without flying| with "
                     r"flying)?(?: and each (player|planeswalker))?", t)
    if m and (m.group(1) == "x" or m.group(2)):
        def eff_sweep(game, ctrl, *a, _n=m.group(1), _na=(m.group(2) or "").strip(), _fl=(m.group(3) or "").strip(),
                      _pl=m.group(4), **kw):
            n = _x(game) if _n == "x" else int(_n)
            if n <= 0:
                return
            src = _src_perm(game, a)
            for pl in game.players:
                for pm in list(pl.creatures()):
                    if _na == "nonartifact" and "artifact" in pm.card.types:
                        continue
                    if _fl == "without flying" and pm.has("flying"):
                        continue
                    if _fl == "with flying" and not pm.has("flying"):
                        continue
                    game.deal_damage(src, pm, n)
                if _pl == "player" and not pl.lost:
                    game.deal_damage(src, pl, n)
                if _pl == "planeswalker":
                    for pm in list(pl.battlefield):
                        if "planeswalker" in pm.card.types:
                            game.deal_damage(src, pm, n)
            game.sba()
        return eff_sweep
    m = re.fullmatch(r"put a \+1/\+1 counter on each ([a-z]+) creature you control", t)
    if m:
        def eff_ctr_sub(game, ctrl, *a, _k=m.group(1), **kw):
            for pm in ctrl.creatures():
                if pm.has_subtype(_k):
                    game.add_counters(pm, "+1/+1", 1)
        return eff_ctr_sub
    if re.fullmatch(r"until end of turn, creatures you control gain trample and get \+x/\+x, where x is the greatest "
                    r"power among creatures you control", t):
        def eff_stampede(game, ctrl, *a, **kw):
            n = _greatest_power(ctrl)
            for pm in ctrl.creatures():
                pm.temp_pt = [pm.temp_pt[0] + n, pm.temp_pt[1] + n]
                pm.temp_keywords.add("trample")
        return eff_stampede
    m = re.fullmatch(r"you may cast (?:a|an) (creature |noncreature |instant or sorcery |)spell with mana value "
                     r"(\d+) or less from your hand without paying its mana cost", t)
    if m:
        def eff_free_hand(game, ctrl, *a, _k=m.group(1).strip(), _n=int(m.group(2)), **kw):
            pool = [c for c in ctrl.hand if not c.is_land() and c.cost is not None and c.cost.cmc <= _n
                    and (not _k or (_k == "creature" and c.is_creature())
                         or (_k == "noncreature" and not c.is_creature())
                         or (_k == "instant or sorcery" and {"instant", "sorcery"} & c.types))]
            pool.sort(key=lambda c: -c.cost.cmc)
            for c in pool:
                if _free_cast(game, ctrl, c):
                    return
        return eff_free_hand
    if t == "draw cards equal to the greatest power among creatures you control":
        return lambda game, ctrl, *a, **kw: ctrl.draw(min(15, _greatest_power(ctrl)), game)
    m = re.fullmatch(r"return all attacking creatures to their owner(?:'s|s'|s) hands?", t)
    if m:
        def eff_aetherize(game, ctrl, *a, **kw):
            for o in game.opponents(ctrl):
                for pm in list(o.creatures()):
                    if pm.attacking is not None:
                        _bounce_pm(game, pm)
        return eff_aetherize
    m = re.fullmatch(r"choose (\w+) target creature cards in your graveyard\. sacrifice a creature\. if you do, "
                     r"return the chosen cards to the battlefield( tapped)?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_victimize(game, ctrl, *a, _n=n, _t=bool(m.group(2)), **kw):
            pool = sorted([c for c in ctrl.graveyard if c.is_creature()], key=lambda c: -(c.cost.cmc if c.cost else 0))
            v = _fodder(game, ctrl, "a creature", None, optional=False)
            if not pool or v is None:
                return
            game.to_graveyard(v, "sacrificio")
            for c in pool[:_n]:
                if c in ctrl.graveyard:
                    ctrl.graveyard.remove(c)
                    pm = game.move_to_battlefield(c, ctrl)
                    if pm is not None and _t:
                        pm.tapped = True
        return eff_victimize
    m = re.fullmatch(r"each opponent sacrifices an? (artifact|enchantment|creature|land|nonland permanent)(?: or "
                     r"(?:an? )?(artifact|enchantment|creature|planeswalker))?(?: of their choice)?", t)
    if m:
        def eff_edict2(game, ctrl, *a, _k={m.group(1), m.group(2)} - {None}, **kw):
            for o in game.opponents(ctrl):
                pool = [pm for pm in o.battlefield if any(
                    (k == "creature" and pm.is_creature()) or (k == "nonland permanent" and not pm.card.is_land())
                    or k in pm.card.types for k in _k) and not o.is_commander(pm.card)]
                if pool:
                    _human_or_auto_sacrifice(game, o, f"Sacrificio forzado (lo fuerza {ctrl.name})", pool=pool)
        return eff_edict2
    if t in ("you may put target creature card from your graveyard on top of your library",
             "put target creature card from your graveyard on top of your library"):
        def eff_gy_top_cr(game, ctrl, *a, **kw):
            pool = [c for c in ctrl.graveyard if c.is_creature()]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
        return eff_gy_top_cr
    if t.startswith("each player exiles all creature cards from their graveyard, then sacrifices all creatures they "
                    "control, then puts all cards they exiled this way onto the battlefield"):
        def eff_living_death(game, ctrl, *a, **kw):
            pend = {}
            for pl in game.players:
                pend[id(pl)] = [c for c in pl.graveyard if c.is_creature()]
                for c in pend[id(pl)]:
                    pl.graveyard.remove(c)
                    pl.exile.append(c)
            for pl in game.players:
                for pm in list(pl.creatures()):
                    game.to_graveyard(pm, "sacrificio (Living Death)")
            for pl in game.players:
                for c in pend[id(pl)]:
                    if c in pl.exile:
                        pl.exile.remove(c)
                        game.move_to_battlefield(c, pl)
            game.sba()
        return eff_living_death
    m = re.fullmatch(r"all creatures get -x/-x until end of turn", t)
    if m:
        def eff_minus_x_all(game, ctrl, *a, **kw):
            n = _x(game)
            for pl in game.players:
                for pm in pl.creatures():
                    pm.temp_pt = [pm.temp_pt[0] - n, pm.temp_pt[1] - n]
            game.sba()
        return eff_minus_x_all
    if t == "put target attacking creature on the bottom of its owner's library. its controller gains life equal to its toughness":
        def eff_condemn(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures() if pm.attacking is not None
                    and game.can_target(ctrl, pm)]
            if not pool:
                return
            pm = max(pool, key=lambda x: x.power)
            pl, tough = pm.controller, max(0, pm.toughness)
            pl.battlefield.remove(pm)
            if pm.card.on_leave:
                pm.card.on_leave(game, pl, pm)
            if not pm.is_token:
                real = getattr(pm.card, "_real", None) or pm.card
                owner = game.commander_owner(real)
                (owner.command.append(real) if owner else pl.library.insert(0, real))
            game.gain_life(pl, tough)
        return eff_condemn
    m = re.fullmatch(r"creatures target player controls get \+(\d+)/\+(\d+) until end of turn\. untap them", t)
    if m:
        def eff_oak(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            for pm in ctrl.creatures():
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
                pm.tapped = False
        return eff_oak
    if t == "target creature you control deals damage equal to its power to each other creature and each opponent":
        def eff_ignition(game, ctrl, *a, **kw):
            if not ctrl.creatures():
                return
            src = max(ctrl.creatures(), key=lambda x: x.power)
            n = max(0, src.power)
            for pl in game.players:
                for pm in list(pl.creatures()):
                    if pm is not src:
                        game.deal_damage(src, pm, n)
            for o in game.opponents(ctrl):
                game.deal_damage(src, o, n)
            game.sba()
        return eff_ignition
    if t.startswith("put target creature card from an opponent's graveyard onto the battlefield under your control"):
        def eff_clique(game, ctrl, *a, _h="haste" in t, _ex="exile it" in t, **kw):
            pool = [(o, c) for o in game.opponents(ctrl) for c in o.graveyard if c.is_creature()]
            if not pool:
                return
            o, c = max(pool, key=lambda x: (x[1].cost.cmc if x[1].cost else 0))
            o.graveyard.remove(c)
            pm = game.move_to_battlefield(c, ctrl)
            if pm is None:
                return
            if _h:
                pm.summoning_sick = False
                pm.temp_keywords.add("haste")
            if _ex:
                game.delayed_end.append(lambda g, _pm=pm: g.exile_permanent(_pm, "fin de turno")
                                        if _pm in _pm.controller.battlefield else None)
        return eff_clique
    if t == "gain control of all artifacts that player controls":
        def eff_steal_arts(game, ctrl, *a, **kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                return
            for pm in list(pl.battlefield):
                if "artifact" in pm.card.types:
                    pl.battlefield.remove(pm)
                    pm.controller = ctrl
                    ctrl.battlefield.append(pm)
            game.log(f"{ctrl.name} toma el control de los artefactos de {pl.name}")
        return eff_steal_arts
    if t == "choose an opponent. if that player has more cards in hand than you, draw cards equal to the difference":
        def eff_sandstone(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if opps:
                o = max(opps, key=lambda x: len(x.hand))
                d = len(o.hand) - len(ctrl.hand)
                if d > 0:
                    ctrl.draw(d, game)
        return eff_sandstone
    m = re.fullmatch(r"target player draws (x|\w+) cards?(?: and loses (x|\w+) life)?", t)
    if m and (m.group(1) == "x" or _count_word(m.group(1))):
        def eff_tp_draw(game, ctrl, *a, _n=m.group(1), _l=m.group(2), **kw):
            n = _x(game) if _n == "x" else _count_word(_n)
            ctrl.draw(min(n, 20), game)
            if _l:
                ctrl.life -= _x(game) if _l == "x" else (_count_word(_l) or 0)
        return eff_tp_draw
    if t in ("permanents you control gain hexproof and indestructible until end of turn",
             "creatures you control gain hexproof and indestructible until end of turn"):
        def eff_hi(game, ctrl, *a, **kw):
            for pm in ctrl.battlefield:
                pm.temp_keywords |= {"hexproof", "indestructible"}
        return eff_hi
    m = re.fullmatch(r"(?:target player|you) gains? (\w+) life for each creature on the battlefield", t)
    if m and (n := _count_word(m.group(1))):
        def eff_congregate(game, ctrl, *a, _n=n, **kw):
            game.gain_life(ctrl, _n * sum(len(pl.creatures()) for pl in game.players))
        return eff_congregate
    m = re.fullmatch(r"each opponent loses x life, where x is your devotion to (white|blue|black|red|green)\. you gain "
                     r"life equal to the life lost this way", t)
    if m:
        def eff_gary(game, ctrl, *a, _c={"white": "W", "blue": "U", "black": "B", "red": "R",
                                          "green": "G"}[m.group(1)], **kw):
            n = ctrl.devotion({_c})
            lost = 0
            for o in game.opponents(ctrl):
                if not o.lost:
                    o.life -= n
                    lost += n
            if lost:
                game.gain_life(ctrl, lost)
        return eff_gary
    m = re.fullmatch(r"each player other than target player creates (?:a|an|\w+) (\d+)/(\d+) (\w+) ([a-z]+) creature "
                     r"tokens? with flying", t)
    if m:
        def eff_dbd(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), _s=m.group(4).capitalize(), **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            skip = max(opps, key=lambda o: len(o.creatures())) if opps else None
            for pl in game.players:
                if pl is not skip and not pl.lost:
                    cards.make_token(game, pl, _s, _p, _q, kw=("flying",), subtypes=(_s,))
        return eff_dbd
    m = re.fullmatch(r"choose up to (\w+) creatures?\. destroy the rest", t)
    if m and (n := _count_word(m.group(1))):
        def eff_duneblast(game, ctrl, *a, _n=n, **kw):
            keep = set(id(pm) for pm in sorted(ctrl.creatures(), key=lambda x: -(x.power + x.toughness))[:_n])
            for pl in game.players:
                for pm in list(pl.creatures()):
                    if id(pm) not in keep and not pm.has("indestructible"):
                        game.to_graveyard(pm, "destruida")
        return eff_duneblast
    if t == "each instant and sorcery card in your graveyard gains flashback until end of turn. the flashback cost is equal to its mana cost":
        def eff_pif(game, ctrl, *a, **kw):
            for c in ctrl.graveyard:
                if {"instant", "sorcery"} & c.types and c.cost is not None and not getattr(c, "gy_play", None):
                    c.gy_play = {"mode": "flashback", "cost": c.cost, "after": "exile"}
                    game.delayed_end.append(lambda g, _c=c: setattr(_c, "gy_play", None))
        return eff_pif
    if t == "you gain life equal to that creature's toughness":
        def eff_life_tough(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None) or _src_perm(game, a)
            if sj is not None and hasattr(sj, "toughness") and sj.toughness > 0:
                game.gain_life(ctrl, sj.toughness)
        return eff_life_tough
    m = re.fullmatch(r"you may draw cards equal to its power\. if you do, discard (\w+) cards", t)
    if m and (n := _count_word(m.group(1))):
        def eff_wits(game, ctrl, *a, _n=n, **kw):
            src = _src_perm(game, a)
            p = max(0, getattr(src, "power", 0) or 0)
            if p > _n:
                ctrl.draw(p, game)
                _human_or_auto_discard(game, ctrl, _n)
        return eff_wits
    if t == "you and that player each draw that many cards":
        def eff_diviner(game, ctrl, *a, **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or 0
            pl = _that_player(game, ctrl)
            if isinstance(n, int) and n > 0:
                ctrl.draw(n, game)
                if pl is not None:
                    pl.draw(n, game)
        return eff_diviner
    if t == "put a +1/+1 counter on that creature":
        def eff_ctr_that(game, ctrl, *a, **kw):
            sj = getattr(game, "_trigger_subject", None)
            if sj is not None and hasattr(sj, "counters") and sj in sj.controller.battlefield:
                game.add_counters(sj, "+1/+1", 1)
        return eff_ctr_that
    if t == "double the number of each kind of counter on any number of target permanents":
        def eff_skate(game, ctrl, *a, **kw):
            for pm in ctrl.battlefield:
                for k, v in list(pm.counters.items()):
                    if v > 0 and k != "-1/-1":
                        game.add_counters(pm, k, v)
        return eff_skate
    m = re.fullmatch(r"sacrifice a creature\. if you can't, sacrifice (?:this artifact|this enchantment|this creature|~)", t)
    if m:
        def eff_monument(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            v = _fodder(game, ctrl, "a creature", src, optional=False)
            if v is not None:
                game.to_graveyard(v, "sacrificio")
            elif src is not None:
                game.to_graveyard(src, "sacrificio")
        return eff_monument
    # ── batch 15: hechizos varios ──
    m = re.fullmatch(r"(up to )?(\w+) target creatures each get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m and (n := _count_word(m.group(2))):
        def eff_multi_pump(game, ctrl, *a, _n=n, _p=int(m.group(3)), _q=int(m.group(4)), **kw):
            if _p + _q >= 0:
                pool = sorted(ctrl.creatures(), key=lambda x: (x.attacking is None, -x.power))
            else:
                pool = [pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)]
                pool.sort(key=lambda x: (x.toughness - x.damage + _q > 0, -x.power))
            for pm in pool[:_n]:
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
            game.sba()
        return eff_multi_pump
    m = re.fullmatch(r"(target )?blocking creatures? gets? ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_block_pump(game, ctrl, *a, _one=bool(m.group(1)), _p=int(m.group(2)), _q=int(m.group(3)), **kw):
            pool = [pm for pm in ctrl.creatures() if getattr(pm, "blocking", None)]
            if _one:
                pool = sorted(pool, key=lambda x: -x.power)[:1]
            for pm in pool:
                pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
        return eff_block_pump
    m = re.fullmatch(r"put target (attacking or blocking |nonland |)?(creature|permanent) (?:into its owner's library "
                     r"(second|third) from the top|on top of its owner's library)", t)
    if m:
        def eff_tuck(game, ctrl, *a, _f=(m.group(1) or "").strip(), _k=m.group(2),
                     _pos={"second": 1, "third": 2}.get(m.group(3) or "", 0), **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield if game.can_target(ctrl, pm)
                    and (pm.is_creature() if _k == "creature" else True)
                    and not (_f == "nonland" and pm.card.is_land())
                    and not (_f == "attacking or blocking" and pm.attacking is None
                             and not getattr(pm, "blocking", None))]
            if not pool:
                return
            pm = max(pool, key=_cmc_of)
            pl = pm.controller
            pl.battlefield.remove(pm)
            if pm.card.on_leave:
                pm.card.on_leave(game, pl, pm)
            if not pm.is_token:
                real = getattr(pm.card, "_real", None) or pm.card
                owner = game.commander_owner(real)
                if owner is not None:
                    owner.command.append(real)
                else:
                    pl.library.insert(max(0, len(pl.library) - _pos), real)
            game.log(f"{pm.name} va a la biblioteca de {pl.name}")
        return eff_tuck
    if t == "put target card from your graveyard on top of your library":
        def eff_gy_top(game, ctrl, *a, **kw):
            pool = [c for c in ctrl.graveyard if not c.is_land()]
            if pool:
                c = max(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
        return eff_gy_top
    if t == "target player shuffles their graveyard into their library":
        def eff_gy_shuffle(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            cand = max(opps + [ctrl], key=lambda x: (sum(1 for c in x.graveyard if c.is_creature()),
                                                     len(x.graveyard)))
            if not cand.graveyard:
                return
            cand.library.extend(cand.graveyard)
            cand.graveyard.clear()
            game.rng.shuffle(cand.library)
            game.log(f"{cand.name} baraja su cementerio en su biblioteca")
        return eff_gy_shuffle
    m = re.fullmatch(r"~ deals (\d+) damage to target tapped creature", t)
    if m:
        def eff_dmg_tapped(game, ctrl, *a, _n=int(m.group(1)), **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures() if pm.tapped
                    and game.can_target(ctrl, pm)]
            if pool:
                pm = max(pool, key=lambda x: (x.toughness - x.damage <= _n, x.power))
                game.deal_damage(_src_perm(game, a), pm, _n)
                game.sba()
        return eff_dmg_tapped
    if t in ("discard all the cards in your hand, then draw that many cards",
             "discard your hand, then draw that many cards"):
        def eff_rummage_all(game, ctrl, *a, **kw):
            n = len(ctrl.hand)
            for c in list(ctrl.hand):
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
            ctrl.draw(n, game)
        return eff_rummage_all
    if t in ("your opponents can't cast spells this turn", "each opponent can't cast spells this turn"):
        def eff_silence(game, ctrl, *a, **kw):
            ctrl.silence_turn = game.turn
            game.log(f"los rivales de {ctrl.name} no pueden lanzar hechizos este turno")
        return eff_silence
    m = re.fullmatch(r"you may play (an|two|\w+) additional lands? this turn", t)
    if m:
        def eff_extra_land(game, ctrl, *a, _n=_count_word(m.group(1)) or 1, **kw):
            cur = getattr(ctrl, "extra_land_turn", None)
            ctrl.extra_land_turn = (game.turn, (cur[1] if cur and cur[0] == game.turn else 0) + _n)
        return eff_extra_land
    m = re.fullmatch(r"creatures of the creature type of your choice get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_type_pump(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            import collections as _co
            cnt = _co.Counter(st for pm in ctrl.creatures() for st in pm.card.subtypes)
            if not cnt:
                return
            st = cnt.most_common(1)[0][0]
            for pl in game.players:
                for pm in pl.creatures():
                    if pm.has_subtype(st):
                        pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
        return eff_type_pump
    if t in ("target player gets an additional turn after this one",
             "target player takes an extra turn after this one"):
        def eff_xturn(game, ctrl, *a, **kw):
            game.extra_turns.append(ctrl)
            game.log(f"{ctrl.name} tomará un turno extra")
        return eff_xturn
    # ── batch 14c: sacrificio opcional, "unless", rebotes, varios ──
    m = re.fullmatch(r"you may sacrifice " + _KIND_RX, t)
    if m:
        def eff_may_sac(game, ctrl, *a, _k=m.group(1), **kw):
            v = _fodder(game, ctrl, _k, _src_perm(game, a))
            if v is not None:
                game.to_graveyard(v, "sacrificio")
        return eff_may_sac
    m = re.fullmatch(r"(?:sacrifice|you sacrifice) " + _KIND_RX, t)
    if m and m.group(1) not in ("a creature", "a permanent", "a land"):
        def eff_must_sac(game, ctrl, *a, _k=m.group(1), **kw):
            v = _fodder(game, ctrl, _k, _src_perm(game, a), optional=False)
            if v is not None:
                game.to_graveyard(v, "sacrificio")
        return eff_must_sac
    m = re.fullmatch(r"sacrifice (?:it|~|this creature|this aura|this enchantment|this artifact) unless "
                     r"you (discard a card at random|discard (?:a|an) ([a-z]+ )?card|pay ((?:\{[^}]+\})+)|"
                     r"return another creature you control to its owner's hand|sacrifice (?:a|an) (\w+)|discard \w+ cards|"
                     r"return an untapped (\w+) you control to its owner's hand)", t)
    if m and m.group(3) and not t.startswith("sacrifice this aura"):
        m = None                         # "this creature … unless you pay" ya lo cubre el mantenimiento
    if m:
        try:
            _pc = parse_cost("".join(re.findall(r"\{([^}]+)\}", m.group(3)))) if m.group(3) else None
        except ValueError:
            _pc = None

        def eff_sac_unless(game, ctrl, *a, _w=m.group(1), _dk=(m.group(2) or "").strip(),
                           _pc=_pc, _sk=m.group(4), _rk=(m.group(5) or ""), **kw):
            src = _src_perm(game, a)
            if src is None or src not in src.controller.battlefield:
                return
            paid = False
            if _w.startswith("discard a card at random") and ctrl.hand:
                c = game.rng.choice(ctrl.hand)
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
                paid = True
            elif re.match(r"discard (\w+) cards", _w) and _count_word(_w.split()[1]):
                _nd = _count_word(_w.split()[1])
                if len(ctrl.hand) >= _nd:
                    _human_or_auto_discard(game, ctrl, _nd)
                    paid = True
            elif _w.startswith("discard"):
                pool = [c for c in ctrl.hand if not _dk or (_dk == "land" and c.is_land())
                        or _dk in c.types]
                if pool:
                    c = min(pool, key=lambda x: (x.cost.cmc if x.cost else 0))
                    ctrl.hand.remove(c)
                    game.discard_card(ctrl, c)
                    paid = True
            elif _w.startswith("pay") and _pc is not None and ctrl.can_pay(_pc):
                ctrl.pay(_pc)
                paid = True
            elif _w.startswith("return an untapped"):
                pool = [pm for pm in ctrl.battlefield if pm is not src and not pm.tapped and pm.card.is_land()
                        and (pm.has_subtype(_rk) or _rk == "land")]
                if pool:
                    paid = _bounce_pm(game, pool[0])
            elif _w.startswith("return"):
                pool = [pm for pm in ctrl.creatures() if pm is not src]
                if pool:
                    paid = _bounce_pm(game, min(pool, key=_cmc_of))
            elif _sk:
                v = _fodder(game, ctrl, "a " + _sk, src, optional=False)
                if v is not None:
                    game.to_graveyard(v, "coste")
                    paid = True
            if not paid:
                game.to_graveyard(src, "sacrificio (no pagó)")
        return eff_sac_unless
    m = re.fullmatch(r"(?:this creature|~|it|target creature) can't be blocked this turn", t)
    if m:
        def eff_unbl_turn(game, ctrl, *a, _tg=t.startswith("target"), **kw):
            src = _src_perm(game, a)
            if _tg:
                pool = [pm for pm in ctrl.creatures() if not pm.tapped or pm.attacking is not None]
                src = max(pool, key=lambda x: x.power) if pool else None
            if src is not None:
                src.temp_keywords.add("unblockable")
        return eff_unbl_turn
    m = re.fullmatch(r"(?:you may )?return (?:up to (\w+) )?(other )?target (tapped )?(creature|permanent|"
                     r"nonland permanent)s?( you control)? to (?:its|their) owner(?:'s|s'|s) hands?", t)
    if m and (m.group(1) or m.group(2) or m.group(3) or m.group(5)):
        def eff_bounce_tg(game, ctrl, *a, _n=(_count_word(m.group(1)) if m.group(1) else 1) or 1,
                          _oth=bool(m.group(2)), _tap=bool(m.group(3)), _k=m.group(4),
                          _mine=bool(m.group(5)), **kw):
            src = _src_perm(game, a)

            def ok(pm):
                if _oth and pm is src:
                    return False
                if _tap and not pm.tapped:
                    return False
                if _k == "creature" and not pm.is_creature():
                    return False
                if _k == "nonland permanent" and pm.card.is_land():
                    return False
                return True
            if _mine:
                pool = [pm for pm in ctrl.battlefield if ok(pm) and not pm.is_token
                        and pm.card.on_etb is not None and _cmc_of(pm) <= 3]
                pool.sort(key=_cmc_of)
            else:
                pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield
                        if ok(pm) and game.can_target(ctrl, pm)]
                pool.sort(key=lambda pm: -_cmc_of(pm))
            for pm in pool[:_n]:
                _bounce_pm(game, pm)
        return eff_bounce_tg
    m = re.fullmatch(r"other attacking creatures get \+(\d+)/\+(\d+) until end of turn", t)
    if m:
        def eff_oth_att(game, ctrl, *a, _p=int(m.group(1)), _q=int(m.group(2)), **kw):
            src = _src_perm(game, a)
            for pm in ctrl.creatures():
                if pm is not src and pm.attacking is not None:
                    pm.temp_pt = [pm.temp_pt[0] + _p, pm.temp_pt[1] + _q]
        return eff_oth_att
    if t in ("it doesn't untap during its controller's next untap step",
             "this creature doesn't untap during your next untap step"):
        def eff_freeze_self(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None:
                src.frozen = True
        return eff_freeze_self
    m = re.fullmatch(r"remove all (\+1/\+1|-1/-1|\w+) counters from (?:~|this creature|this permanent)", t)
    if m:
        def eff_rm_all(game, ctrl, *a, _k=m.group(1), **kw):
            src = _src_perm(game, a)
            if src is not None:
                src.counters.pop(_k, None)
        return eff_rm_all
    m = re.fullmatch(r"(?:you may )?put it on (top|the bottom) of its owner's library", t)
    if m:
        def eff_gy_to_lib(game, ctrl, *a, _top=m.group(1) == "top", **kw):
            src = _src_perm(game, a)
            c = getattr(src, "card", None)
            if c is None:
                return
            c = getattr(c, "_real", None) or c

            def _mv(g, _c=c):
                for pl in g.players:
                    if _c in pl.graveyard:
                        pl.graveyard.remove(_c)
                        if _top:
                            pl.library.append(_c)
                        else:
                            pl.library.insert(0, _c)
                        g.log(f"{_c.name} va {'arriba' if _top else 'abajo'} de la biblioteca")
                        return True
                return False
            if not _mv(game):                # on_death corre antes de llegar al cementerio
                from engine import StackObject
                game.stack.append(StackObject(ctrl, _mv, source=None, label=f"a la biblioteca: {c.name}"))
        return eff_gy_to_lib
    m = re.fullmatch(r"you gain life equal to your devotion to (white|blue|black|red|green)", t)
    if m:
        _cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

        def eff_dev_life(game, ctrl, *a, _c=_cm[m.group(1)], **kw):
            n = ctrl.devotion({_c})
            if n:
                game.gain_life(ctrl, n)
        return eff_dev_life
    if t == "shuffle the cards from your hand into your library, then draw that many cards":
        def eff_reshuffle(game, ctrl, *a, **kw):
            n = len(ctrl.hand)
            ctrl.library.extend(ctrl.hand)
            ctrl.hand.clear()
            game.rng.shuffle(ctrl.library)
            ctrl.draw(n, game)
        return eff_reshuffle
    m = re.fullmatch(r"return (?:a|an) (\w+ )?(creature|land|artifact|enchantment) you control to its "
                     r"owner's hand", t)
    if m and m.group(1):
        def eff_bounce_col(game, ctrl, *a, _q=m.group(1).strip(), _k=m.group(2), **kw):
            cmap = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
            pool = [pm for pm in ctrl.battlefield if (pm.is_creature() if _k == "creature" else
                    _k in pm.card.types) and ((_q in cmap and cmap[_q] in pm.card.identity())
                                              or pm.has_subtype(_q))]
            if pool:
                _bounce_pm(game, min(pool, key=lambda pm: (pm is _src_perm(game, a), _cmc_of(pm))))
        return eff_bounce_col
    m = re.fullmatch(r"sacrifice a creature other than (?:this creature|~)\. if you can't, (?:this creature|~) "
                     r"deals (\d+) damage to you", t)
    if m:
        def eff_sac_or_dmg(game, ctrl, *a, _n=int(m.group(1)), **kw):
            src = _src_perm(game, a)
            v = _fodder(game, ctrl, "another creature", src, optional=False)
            if v is not None:
                game.to_graveyard(v, "sacrificio")
            else:
                game.deal_damage(src, ctrl, _n)
        return eff_sac_or_dmg
    if t == "your life total becomes half your starting life total, rounded up":
        def eff_half_start(game, ctrl, *a, **kw):
            ctrl.life = 20
        return eff_half_start
    m = re.fullmatch(r"you discard a card, lose (\d+) life, and sacrifice a creature", t)
    if m:
        def eff_trio(game, ctrl, *a, _n=int(m.group(1)), **kw):
            _human_or_auto_discard(game, ctrl, 1)
            ctrl.life -= _n
            v = _fodder(game, ctrl, "a creature", _src_perm(game, a), optional=False)
            if v is not None:
                game.to_graveyard(v, "sacrificio")
        return eff_trio
    m = re.fullmatch(r"tap up to one target creature and put a stun counter on it", t)
    if m:
        def eff_stun(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures() if game.can_target(ctrl, pm)]
            if pool:
                pm = max(pool, key=lambda x: x.power)
                pm.tapped = True
                pm.counters["stun"] = pm.counters.get("stun", 0) + 1
        return eff_stun
    m = re.fullmatch(r"target (?:player|opponent) gets (\w+) rad counters?", t)
    if m and (n := _count_word(m.group(1))):
        def eff_rad(game, ctrl, *a, _n=n, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if opps:
                o = min(opps, key=lambda x: x.life)
                o.rad = getattr(o, "rad", 0) + _n
                game.log(f"{o.name} recibe {_n} contador(es) rad")
        return eff_rad
    if t in ("you may exile it", "exile it from your graveyard", "you may exile this card from your graveyard"):
        def eff_exile_self_gy(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            c = getattr(src, "card", None)
            c = getattr(c, "_real", None) or c
            if c is None or src is None or src in src.controller.battlefield:
                return
            # on_death corre antes de que la carta llegue al cementerio: la carta se
            # marca para ir al exilio en vez de al cementerio
            for pl in game.players:
                if c in pl.graveyard:
                    pl.graveyard.remove(c)
                    pl.exile.append(c)
                    return
            def _mv(g, _c=c):
                for pl in g.players:
                    if _c in pl.graveyard:
                        pl.graveyard.remove(_c)
                        pl.exile.append(_c)
                        g.log(f"{_c.name} se exilia del cementerio")
                        return
            from engine import StackObject
            game.stack.append(StackObject(ctrl, _mv, source=None, label=f"exiliar {c.name}"))
            game._sig_bump = getattr(game, "_sig_bump", 0) + 1     # cuenta como "if you do"
        return eff_exile_self_gy
    # ── batch 14b: ruedas, "that player", mano rival, daño por conteo ──
    m = re.fullmatch(r"each player (discards their hand|shuffles their hand and graveyard into their "
                     r"library), then draws (\w+) cards", t)
    if m and (n := _count_word(m.group(2))):
        def eff_wheel(game, ctrl, *a, _n=n, _tw="shuffles" in m.group(1), **kw):
            for pl in game.players:
                if pl.lost:
                    continue
                if _tw:
                    pl.library.extend(pl.hand + pl.graveyard)
                    pl.hand.clear()
                    pl.graveyard.clear()
                    game.rng.shuffle(pl.library)
                else:
                    for c in list(pl.hand):
                        pl.hand.remove(c)
                        game.discard_card(pl, c)
                pl.draw(_n, game)
        return eff_wheel
    if t == "each player discards their hand, then draws cards equal to the greatest number of cards a player discarded this way":
        def eff_windfall(game, ctrl, *a, **kw):
            n = max((len(pl.hand) for pl in game.players if not pl.lost), default=0)
            for pl in game.players:
                if pl.lost:
                    continue
                for c in list(pl.hand):
                    pl.hand.remove(c)
                    game.discard_card(pl, c)
                pl.draw(n, game)
        return eff_windfall
    m = re.fullmatch(r"each player may draw up to (\w+) cards", t)
    if m and (n := _count_word(m.group(1))):
        def eff_each_draw(game, ctrl, *a, _n=n, **kw):
            for pl in game.players:
                if not pl.lost:
                    pl.draw(_n, game)
        return eff_each_draw
    m = re.fullmatch(r"(?:~|this creature|it) deals (\d+) damage to each player", t)
    if m:
        def eff_dmg_each_pl(game, ctrl, *a, _n=int(m.group(1)), **kw):
            src = _src_perm(game, a)
            for pl in game.players:
                if not pl.lost:
                    game.deal_damage(src, pl, _n)
        return eff_dmg_each_pl
    if t in ("look at target opponent's hand", "look at target player's hand",
             "target opponent reveals their hand", "target player reveals their hand"):
        return lambda game, ctrl, *a, **kw: game.log(f"{ctrl.name} mira la mano de un rival")
    if t == "target opponent exiles a card from their hand":
        def eff_opp_exile_hand(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if o.hand]
            if not opps:
                return
            o = max(opps, key=lambda x: len(x.hand))
            c = min(o.hand, key=lambda x: (x.cost.cmc if x.cost else 0))   # elige el rival
            o.hand.remove(c)
            o.exile.append(c)
            game.log(f"{o.name} exilia {c.name} de su mano")
        return eff_opp_exile_hand
    if re.fullmatch(r"target opponent reveals their hand(?: and|\.) you choose a nonland card from it"
                    r"(?:\. exile that card| and exile that card)", t):
        def eff_opp_exile_best(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if any(not c.is_land() for c in o.hand)]
            if not opps:
                return
            o = max(opps, key=lambda x: len(x.hand))
            c = max((x for x in o.hand if not x.is_land()), key=lambda x: (x.cost.cmc if x.cost else 0))
            o.hand.remove(c)
            o.exile.append(c)
            src = _src_perm(game, a)
            if src is not None and hasattr(src, "card"):
                src._exiled_with = list(getattr(src, "_exiled_with", None) or []) + [(c, o)]
            game.log(f"{ctrl.name} exilia {c.name} de la mano de {o.name}")
        return eff_opp_exile_best
    m = re.fullmatch(r"that player (sacrifices a creature(?: of their choice)?|discards that many cards|"
                     r"mills (twice )?that many cards|discards their hand)", t)
    if m:
        def eff_that_pl(game, ctrl, *a, _w=m.group(1), **kw):
            pl = _that_player(game, ctrl)
            if pl is None or pl.lost:
                return
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or 0
            n = n if isinstance(n, int) else 0
            if _w.startswith("sacrifices"):
                pool = pl.creatures()
                if pool:
                    _human_or_auto_sacrifice(game, pl, f"Sacrificio forzado (lo fuerza {ctrl.name})",
                                             pool=pool)
            elif _w == "discards their hand":
                for c in list(pl.hand):
                    pl.hand.remove(c)
                    game.discard_card(pl, c)
            elif _w.startswith("discards") and n > 0:
                _human_or_auto_discard(game, pl, n)
            elif _w.startswith("mills") and n > 0:
                cards.mill(game, pl, n * (2 if "twice" in _w else 1))
        return eff_that_pl
    if t in ("it deals damage equal to its power to each opponent",
             "~ deals damage equal to its power to each opponent",
             "this creature deals damage equal to its power to each opponent"):
        def eff_pow_each_opp(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            n = max(0, getattr(src, "power", 0) or 0) if src is not None else 0
            for o in game.opponents(ctrl):
                if n and not o.lost:
                    game.deal_damage(src, o, n)
        return eff_pow_each_opp
    if t in ("~ deals damage to target player equal to the number of cards in that player's hand",
             "~ deals damage to target opponent equal to the number of cards in that player's hand"):
        def eff_hand_dmg(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if opps:
                o = max(opps, key=lambda x: len(x.hand))
                if o.hand:
                    game.deal_damage(_src_perm(game, a), o, len(o.hand))
        return eff_hand_dmg
    m = re.fullmatch(r"~ deals damage to each opponent equal to the number of (lands|islands|swamps|"
                     r"mountains|forests|plains|creatures|artifacts) that player controls", t)
    if m:
        def eff_cnt_dmg(game, ctrl, *a, _k=m.group(1)[:-1], **kw):
            src = _src_perm(game, a)
            for o in game.opponents(ctrl):
                n = sum(1 for pm in o.battlefield if (
                    pm.card.is_land() if _k == "land" else pm.is_creature() if _k == "creature"
                    else "artifact" in pm.card.types if _k == "artifact" else pm.has_subtype(_k)))
                if n and not o.lost:
                    game.deal_damage(src, o, n)
        return eff_cnt_dmg
    if re.fullmatch(r"search target opponent's library for a creature card and put that card onto the "
                    r"battlefield under your control\. then that player shuffles", t):
        def eff_steal_lib(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if any(c.is_creature() for c in o.library)]
            if not opps:
                return
            o = opps[0]
            c = max((x for x in o.library if x.is_creature()), key=lambda x: (x.cost.cmc if x.cost else 0))
            o.library.remove(c)
            game.rng.shuffle(o.library)
            game.move_to_battlefield(c, ctrl)
            game.log(f"{ctrl.name} pone {c.name} de la biblioteca de {o.name} bajo su control")
        return eff_steal_lib
    if re.fullmatch(r"target opponent exiles a creature(?: or planeswalker)? they control with the greatest "
                    r"mana value among [a-z ]+ they control", t):
        def eff_exile_big(game, ctrl, *a, **kw):
            opps = [o for o in game.opponents(ctrl) if o.creatures()]
            if not opps:
                return
            o = max(opps, key=lambda x: max(_cmc_of(pm) for pm in x.creatures()))
            pm = max(o.creatures(), key=_cmc_of)
            game.exile_permanent(pm, "edicto (exilio)")
        return eff_exile_big
    m = re.fullmatch(r"each opponent sacrifices a (permanent|creature|nonland permanent)(?: of their choice)? "
                     r"unless they pay \{(\d+)\}", t)
    if m:
        def eff_tax_edict(game, ctrl, *a, _k=m.group(1), _n=int(m.group(2)), **kw):
            cost = parse_cost(str(_n))
            for o in game.opponents(ctrl):
                if o.lost:
                    continue
                if o.can_pay(cost):
                    o.pay(cost)
                    game.log(f"{o.name} paga {{{_n}}} para no sacrificar")
                    continue
                pool = [pm for pm in o.battlefield if (pm.is_creature() if _k == "creature" else
                        not pm.card.is_land() if _k == "nonland permanent" else True)
                        and not o.is_commander(pm.card)]
                if pool:
                    _human_or_auto_sacrifice(game, o, "Sacrificio (no pagaste)", pool=pool)
        return eff_tax_edict
    # ── batch 14: veneno, "that much", P/T base, daño a sí misma, etc. ──
    if t in ("defending player gets a poison counter", "that player gets a poison counter"):
        def eff_poison(game, ctrl, *a, **kw):
            pl = _that_player(game, ctrl) or next(iter(game.opponents(ctrl)), None)
            if pl is not None:
                pl.poison += 1
        return eff_poison
    if t in ("that player loses half their life, rounded up", "each opponent loses half their life, "
             "rounded up"):
        def eff_half(game, ctrl, *a, _each=t.startswith("each"), **kw):
            pls = game.opponents(ctrl) if _each else [_that_player(game, ctrl)]
            for pl in pls:
                if pl is not None and pl.life > 0:
                    pl.life -= (pl.life + 1) // 2
        return eff_half
    m = re.fullmatch(r"(you gain|you lose) that much life|(?:it|~|this creature) deals that much "
                     r"damage to you", t)
    if m:
        def eff_much(game, ctrl, *a, _m=m.group(1), **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or 0
            if not isinstance(n, int) or n <= 0:
                return
            if _m == "you gain":
                game.gain_life(ctrl, n)
            elif _m == "you lose":
                ctrl.life -= n
            else:
                game.deal_damage(_src_perm(game, a), ctrl, n)
        return eff_much
    m = re.fullmatch(r"target creature(?: an opponent controls)? has base power and toughness "
                     r"(\d+)/(\d+) until end of turn", t)
    if m:
        def eff_base_pt(game, ctrl, *a, _p=int(m.group(1)), _t=int(m.group(2)), **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                    if game.can_target(ctrl, pm)]
            if not pool:
                return
            pm = max(pool, key=lambda x: x.power + x.toughness)
            old = pm.set_base_pt
            pm.set_base_pt = (_p, _t)
            game.delayed_end.append(lambda g, _pm=pm, _o=old: setattr(_pm, "set_base_pt", _o))
            game.log(f"{pm.name} pasa a ser {_p}/{_t} hasta el fin del turno")
            game.sba()
        return eff_base_pt
    if t == "switch target creature's power and toughness until end of turn":
        def eff_switch(game, ctrl, *a, **kw):
            # rival con poca fuerza y mucha resistencia muere; propia: más fuerza
            tg = [x for x in (a[0] if a and isinstance(a[0], (list, tuple)) else []) if hasattr(x, "temp_pt")]
            pool = tg or [pm for o in game.opponents(ctrl) for pm in o.creatures()
                          if game.can_target(ctrl, pm) and pm.power - pm.damage <= 0 < pm.toughness]
            pool = pool or [pm for pm in ctrl.creatures() if pm.toughness > pm.power]
            if not pool:
                return
            pm = pool[0] if tg else max(pool, key=lambda x: x.toughness - x.power)
            pw, th = pm.power, pm.toughness
            pm.temp_pt = [pm.temp_pt[0] + th - pw, pm.temp_pt[1] + pw - th]
            game.log(f"{pm.name} intercambia fuerza y resistencia ({th}/{pw})")
            game.sba()
        return eff_switch
    if t == "target creature deals damage to itself equal to its power":
        def eff_self_dmg(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                    if game.can_target(ctrl, pm) and pm.power >= pm.toughness - pm.damage]
            pool = pool or [pm for o in game.opponents(ctrl) for pm in o.creatures()
                            if game.can_target(ctrl, pm)]
            if pool:
                pm = max(pool, key=lambda x: x.power)
                game.deal_damage(pm, pm, pm.power)
                game.sba()
        return eff_self_dmg
    m = re.fullmatch(r"[\w,' -]+? deals (\w+) damage to each of (?:up to )?(\w+) (?:other )?"
                     r"targets?(?: creatures?)?", t)
    if m and (n := _count_word(m.group(1))) and (k := _count_word(m.group(2))):
        def eff_each_of(game, ctrl, *a, _n=n, _k=k, **kw):
            src = getattr(game, "_trigger_source", None)
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                    if game.can_target(ctrl, pm)]
            pool.sort(key=lambda x: (x.toughness - x.damage <= _n, x.power), reverse=True)
            hits = 0
            for pm in pool[:_k]:
                game.deal_damage(src, pm, _n)
                hits += 1
            for o in sorted(game.targetable_opponents(ctrl), key=lambda o: o.life):
                if hits >= _k:
                    break
                game.deal_damage(src, o, _n)
                hits += 1
            game.sba()
        return eff_each_of
    if re.fullmatch(r"(?:up to one )?target creature you control gains protection from the color of "
                    r"your choice until end of turn", t):
        def eff_prot(game, ctrl, *a, **kw):
            pool = sorted(ctrl.creatures(), key=lambda x: x.power + x.toughness, reverse=True)
            if pool:
                pool[0].temp_keywords.add("protection")
                game.log(f"{pool[0].name} gana protección hasta el fin del turno")
        return eff_prot
    if re.fullmatch(r"target creature's owner puts it on their choice of the top or bottom of their "
                    r"library", t):
        def eff_owner_tb(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                    if game.can_target(ctrl, pm)]
            if not pool:
                return
            pm = max(pool, key=lambda x: x.power + x.toughness)
            pl = pm.controller
            pl.battlefield.remove(pm)
            if pm.card.on_leave:
                pm.card.on_leave(game, pl, pm)
            if not pm.is_token:
                real = getattr(pm.card, "_real", None) or pm.card
                owner = game.commander_owner(real)
                (owner.command if owner else pl.library).append(real)
            game.log(f"{pm.name} vuelve a la biblioteca de {pl.name}")
        return eff_owner_tb
    m = re.fullmatch(r"target player shuffles up to (\w+) target cards? from their graveyard into "
                     r"their library", t)
    if m:
        def eff_shuffle_gy(game, ctrl, *a, _n=_count_word(m.group(1)) or 1, **kw):
            opps = [o for o in game.opponents(ctrl) if o.graveyard]
            if not opps:
                return
            o = max(opps, key=lambda x: len(x.graveyard))
            pick = sorted(o.graveyard, key=lambda c: (c.is_creature(), c.cost.cmc if c.cost else 0),
                          reverse=True)[:_n]
            for c in pick:
                o.graveyard.remove(c)
                o.library.append(c)
            game.rng.shuffle(o.library)
        return eff_shuffle_gy
    if re.fullmatch(r"tap that creature(?:\. it| and it) doesn't untap during its controller's next "
                    r"untap step", t):
        def eff_tap_freeze(game, ctrl, *a, **kw):
            subj = getattr(game, "_trigger_subject", None)
            if subj is not None and hasattr(subj, "card"):
                subj.tapped = True
                subj.frozen = True
        return eff_tap_freeze
    m = re.fullmatch(r"(?:it|this creature|~) gets \+(\d+)/\+(\d+) until end of turn for each "
                     r"creature blocking it", t)
    if m:
        def eff_per_blocker(game, ctrl, *a, _p=int(m.group(1)), _t=int(m.group(2)), **kw):
            src = _src_perm(game, a)
            if src is not None:
                n = len(getattr(src, "blocked_by", []) or [])
                src.temp_pt[0] += _p * n
                src.temp_pt[1] += _t * n
        return eff_per_blocker
    if t in ("put its counters on target creature you control",
             "you may put its counters on target creature you control"):
        def eff_move_ctrs(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is None or not src.counters:
                return
            pool = [pm for pm in ctrl.creatures() if pm is not src]
            if not pool:
                return
            tgt = max(pool, key=lambda x: x.power + x.toughness)
            for k, v in list(src.counters.items()):
                if v > 0:
                    game.add_counters(tgt, k, v)
            game.log(f"{tgt.name} recibe los contadores de {src.name}")
        return eff_move_ctrs
    # ── batch 12: criatura encantada, "that much", fin de combate ──
    m = re.fullmatch(r"put (a|an|one|two|three|\w+) \+1/\+1 counters? on enchanted creature", t)
    if m and (k := _count_word(m.group(1))):
        def eff_ench_ctr(game, ctrl, *a, _k=k, **kw):
            src = _src_perm(game, a)
            host = getattr(src, "enchanting", None) if src is not None else None
            if host is not None and host in host.controller.battlefield:
                game.add_counters(host, "+1/+1", _k)
        return eff_ench_ctr
    if t in ("return that card to the battlefield under your control",
             "return that card to the battlefield under its owner's control"):
        def eff_return_subj(game, ctrl, *a, _own="owner" in t, **kw):
            subj = getattr(game, "_trigger_subject", None)
            c = getattr(getattr(subj, "card", None), "_real", None) or getattr(subj, "card", None)
            if c is None:
                return
            for pl in game.players:
                if c in pl.graveyard:
                    pl.graveyard.remove(c)
                    game.move_to_battlefield(c, pl if _own else ctrl)
                    game.log(f"{c.name} vuelve al campo")
                    break
        return eff_return_subj
    m = re.fullmatch(r"(target opponent|each opponent) loses that much life", t)
    if m:
        def eff_that_much(game, ctrl, *a, _each=m.group(1) == "each opponent", **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or 0
            if not isinstance(n, int) or n <= 0:
                return
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            for o in (opps if _each else opps[:1] and [min(opps, key=lambda x: x.life)]):
                o.life -= n
        return eff_that_much
    if t == "draw that many cards":
        def eff_draw_that(game, ctrl, *a, **kw):
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or 0
            if isinstance(n, int) and n > 0:
                ctrl.draw(min(n, 10), game)
        return eff_draw_that
    if t == "discard your hand":
        def eff_discard_hand(game, ctrl, *a, **kw):
            for c in list(ctrl.hand):
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
        return eff_discard_hand
    m = re.fullmatch(r"(sacrifice it|return it to its owner's hand) at end of combat", t)
    if m:
        def eff_eoc_self(game, ctrl, *a, _sac=m.group(1).startswith("sac"), **kw):
            src = _src_perm(game, a)
            if src is None:
                return

            def _later(g, _s=src):
                if _s not in _s.controller.battlefield:
                    return
                if _sac:
                    g.to_graveyard(_s, "sacrificio (fin del combate)")
                else:
                    pl = _s.controller
                    pl.battlefield.remove(_s)
                    if not _s.is_token:
                        real = getattr(_s.card, "_real", None) or _s.card
                        owner = g.commander_owner(real)
                        (owner.command if owner else pl.hand).append(real)
            game.delayed_end.append(_later)
        return eff_eoc_self
    # ── batch 10: acciones sobre la propia carta / el sujeto del disparo ──
    _SELF10 = r"(?:~|this creature|this permanent|this enchantment|this artifact|this land)"
    if re.fullmatch(r"transform " + _SELF10, t):
        def eff_tf_self(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                game.transform(src)
        return eff_tf_self
    if re.fullmatch(r"sacrifice (?:" + _SELF10[3:-1] + r"|it)", t):
        def eff_sac_self(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            subj = getattr(game, "_trigger_subject", None)
            if t.endswith(" it") and subj is not None and subj is not src and hasattr(subj, "card"):
                src = subj if subj.controller is ctrl else src
            if src is not None and src in src.controller.battlefield:
                game.to_graveyard(src, "sacrificio")
        return eff_sac_self
    if re.fullmatch(r"return " + _SELF10 + r" to its owner's hand", t):
        def eff_bounce_self(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is None or src not in src.controller.battlefield:
                return
            pl = src.controller
            pl.battlefield.remove(src)
            if src.card.on_leave:
                src.card.on_leave(game, pl, src)
            if not src.is_token:
                real = getattr(src.card, "_real", None) or src.card
                owner = game.commander_owner(real)
                (owner.command if owner else pl.hand).append(real)
            game.log(f"{src.name} vuelve a la mano")
        return eff_bounce_self
    m = re.fullmatch(r"(?:~|this creature|it) deals (\w+) damage to that player", t)
    if m and (n := _count_word(m.group(1))):
        def eff_dmg_that(game, ctrl, *a, _n=n, **kw):
            pl = _that_player(game, ctrl)
            if pl is not None:
                game.deal_damage(_src_perm(game, a), pl, _n)
        return eff_dmg_that
    if t in ("destroy it", "destroy that creature", "destroy that permanent"):
        def eff_destroy_subj(game, ctrl, *a, **kw):
            subj = getattr(game, "_trigger_subject", None)
            if subj is not None and hasattr(subj, "card") and subj in subj.controller.battlefield:
                game.destroy(subj, "disparo")
        return eff_destroy_subj
    if re.fullmatch(r"put that many \+1/\+1 counters on " + _SELF10, t):
        def eff_that_many(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            k = getattr(game, "_trigger_kw", None) or {}
            n = k.get("amount") or k.get("n") or k.get("damage") or 0
            if src is not None and isinstance(n, int) and n > 0:
                game.add_counters(src, "+1/+1", n)
        return eff_that_many
    if t == "put the top card of your library into your graveyard":
        def eff_mill1(game, ctrl, *a, **kw):
            if ctrl.library:
                ctrl.graveyard.append(ctrl.library.pop())
        return eff_mill1
    # ── batch 8: efectos simples frecuentes en ETB / upkeep / ataque ──
    m = re.fullmatch(r"each player loses (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        def eff_each_lose(game, ctrl, *a, _n=n, **kw):
            for pl in game.players:
                if not pl.lost:
                    pl.life -= _n
            game.log(f"cada jugador pierde {_n} vida")
        return eff_each_lose
    m = re.fullmatch(r"(?:it|~|this creature|this permanent) deals (\w+) damage to you", t)
    if m and (n := _count_word(m.group(1))):
        def eff_dmg_you(game, ctrl, *a, _n=n, **kw):
            game.deal_damage(_src_perm(game, a), ctrl, _n)
        return eff_dmg_you
    if re.fullmatch(r"you gain life equal to (?:its|~'s|this creature's) (power|toughness)", t):
        _pt = "power" in t

        def eff_gain_pt(game, ctrl, *a, _p=_pt, **kw):
            src = _src_perm(game, a)
            if src is not None:
                game.gain_life(ctrl, max(0, src.power if _p else src.toughness))
        return eff_gain_pt
    m = re.fullmatch(r"tap all (other )?creatures( your opponents control| you don't control)?", t)
    if m:
        def eff_tap_all(game, ctrl, *a, _o=bool(m.group(1)), _opp=bool(m.group(2)), **kw):
            src = _src_perm(game, a)
            for pl in (game.opponents(ctrl) if _opp else game.players):
                for pm in pl.creatures():
                    if not (_o and pm is src):
                        pm.tapped = True
        return eff_tap_all
    m = re.fullmatch(r"all (other )?creatures get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_all_pt(game, ctrl, *a, _o=bool(m.group(1)), _p=int(m.group(2)),
                       _t=int(m.group(3)), **kw):
            src = _src_perm(game, a)
            for pl in game.players:
                for pm in pl.creatures():
                    if not (_o and pm is src):
                        pm.temp_pt[0] += _p
                        pm.temp_pt[1] += _t
            game.sba()
        return eff_all_pt
    m = re.fullmatch(r"put (a|an|one|two|three|\w+) \+1/\+1 counters? on (?:each of )?(?:up to "
                     r"(\w+) )?(another |other )?target creatures?( you control)?", t)
    if m and (k := _count_word(m.group(1))) and (m.group(2) or m.group(3) or "each of" in t):
        nt = _count_word(m.group(2)) if m.group(2) else 1

        def eff_ctr_others(game, ctrl, *a, _k=k, _n=nt or 1, _oth=bool(m.group(3)), **kw):
            src = _src_perm(game, a)
            pool = [pm for pm in ctrl.creatures() if not (_oth and pm is src)]
            pool.sort(key=lambda x: (x.power + x.toughness), reverse=True)
            if ctrl is getattr(game, "interactive_human", None) and _n == 1:
                _human_target_choice(game, ctrl, "etb_target", f"+1/+1 x{_k} a…",
                                     [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool],
                                     lambda pm: game.add_counters(pm, "+1/+1", _k))
                return
            for pm in pool[:_n]:
                game.add_counters(pm, "+1/+1", _k)
        return eff_ctr_others
    m = re.fullmatch(r"return (a|another) (creature|permanent|land|artifact|enchantment|nonland "
                     r"permanent) you control to its owner's hand", t)
    if m:
        def eff_bounce_own(game, ctrl, *a, _an=m.group(1) == "another", _k=m.group(2), **kw):
            src = _src_perm(game, a)

            def ok(pm):
                if _an and pm is src:
                    return False
                if _k == "creature":
                    return pm.is_creature()
                if _k == "permanent":
                    return True
                if _k == "nonland permanent":
                    return not pm.card.is_land()
                return _k in pm.card.types
            pool = [pm for pm in ctrl.battlefield if ok(pm)]
            if not pool:
                return
            # bot: no se devuelve a sí misma si hay otra opción; prefiere re-jugar un
            # ETB barato (no la fuente), después una tierra ya girada, después lo más
            # barato; nunca el comandante si se puede evitar
            def _worth(pm):
                cmc = pm.card.cost.cmc if pm.card.cost else 0
                return (pm is src, ctrl.is_commander(pm.card), pm.is_token,
                        not (pm.card.on_etb is not None and cmc <= 3),
                        not (pm.card.is_land() and pm.tapped), cmc)
            pool.sort(key=_worth)

            def _do(pm):
                if pm not in ctrl.battlefield:
                    return
                ctrl.battlefield.remove(pm)
                if pm.card.on_leave:
                    pm.card.on_leave(game, ctrl, pm)
                if not pm.is_token:
                    real = getattr(pm.card, "_real", None) or pm.card
                    owner = game.commander_owner(real)
                    (owner.command if owner else ctrl.hand).append(real)
                game.log(f"{ctrl.name} devuelve {pm.name} a la mano")
            _human_target_choice(game, ctrl, "etb_target", "Devolvé a la mano:",
                                 [(pm.name, pm) for pm in pool], _do)
        return eff_bounce_own
    m = re.fullmatch(r"untap up to (\w+) lands", t)
    if m and (n := _count_word(m.group(1))):
        def eff_untap_lands(game, ctrl, *a, _n=n, **kw):
            for pm in [pm for pm in ctrl.battlefield if pm.card.is_land() and pm.tapped][:_n]:
                pm.tapped = False
        return eff_untap_lands
    if re.fullmatch(r"untap (?:~|this creature|this permanent|this artifact|it)", t):
        def eff_untap_self(game, ctrl, *a, **kw):
            src = _src_perm(game, a)
            if src is not None:
                src.tapped = False
        return eff_untap_self
    m = re.fullmatch(r"(?:~|this creature|it) endures (\w+)", t)
    if m and (n := _count_word(m.group(1))):
        def eff_endure(game, ctrl, *a, _n=n, **kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                game.add_counters(src, "+1/+1", _n)
            else:
                cards.make_token(game, ctrl, "Spirit", _n, _n, subtypes=("Spirit",))
        return eff_endure
    m = re.fullmatch(r"(?:up to one )?target creature( an opponent controls| you don't control)? "
                     r"can't block this turn", t)
    if m:
        def eff_cant_block(game, ctrl, *a, **kw):
            pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                    if game.can_target(ctrl, pm) and not pm.tapped]
            pool.sort(key=lambda x: x.power + x.toughness, reverse=True)

            def _do(pm):
                pm.temp_keywords.add("cant_block")
            _human_target_choice(game, ctrl, "etb_target", "No puede bloquear:",
                                 [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool], _do)
        return eff_cant_block
    if re.fullmatch(r"destroy (?:that creature|it) at end of combat", t):
        def eff_destroy_eoc(game, ctrl, *a, **kw):
            tgt = getattr(game, "_trigger_subject", None)
            if tgt is not None and hasattr(tgt, "card"):
                game.delayed_end.append(
                    lambda g, _t=tgt: g.destroy(_t, "fin del combate")
                    if _t in _t.controller.battlefield else None)
        return eff_destroy_eoc
    m = re.fullmatch(r"exile (?:up to (\w+) )?target cards? from (?:a single|target player's|an "
                     r"opponent's) graveyard", t)
    if m:
        def eff_gy_hate(game, ctrl, *a, _n=_count_word(m.group(1) or "one") or 1, **kw):
            opps = [o for o in game.opponents(ctrl) if o.graveyard]
            if not opps:
                return
            o = max(opps, key=lambda x: sum(1 for c in x.graveyard if c.is_creature()))
            pick = sorted(o.graveyard, key=lambda c: (c.is_creature(),
                                                     c.cost.cmc if c.cost else 0), reverse=True)
            for c in pick[:_n]:
                o.graveyard.remove(c)
                o.exile.append(c)
            game.log(f"{ctrl.name} exilia {min(_n, len(pick))} carta(s) del cementerio de {o.name}")
        return eff_gy_hate
    # ── batch 7: daño dividido ("deals N damage divided as you choose among …") ──
    m = re.fullmatch(r"(?:[\w,' -]+?) deals (\w+) damage divided (?:as you choose |evenly )?among "
                     r"(any number of targets|any number of target creatures(?: and/or "
                     r"planeswalkers)?|one or two targets|one, two, or three targets|"
                     r"one or two target creatures(?: and/or planeswalkers)?|up to (\w+) targets|"
                     r"(\w+) targets|any number of target creatures your opponents control)", t)
    if m and (n := _count_word(m.group(1))):
        who = m.group(2)
        cr_only = "creature" in who
        cap = (99 if "any number" in who else 2 if "one or two" in who else
               3 if "one, two, or three" in who else
               (_count_word(m.group(3) or m.group(4) or "") or 99))

        def eff_divided(game, ctrl, *a, _n=n, _c=cr_only, _cap=cap, **kw):
            src = getattr(game, "_trigger_source", None)
            left, hits = _n, 0
            pool = sorted([pm for o in game.opponents(ctrl) for pm in o.creatures()
                           if game.can_target(ctrl, pm)],
                          key=lambda x: (x.power + x.toughness), reverse=True)
            for pm in pool:                      # matar lo más grande que alcance
                need = max(1, pm.toughness - pm.damage)
                if pm.has("indestructible") or need > left or hits >= _cap:
                    continue
                game.deal_damage(src, pm, need)
                left -= need
                hits += 1
            if left > 0 and hits < _cap:
                if not _c:
                    opps = [o for o in game.opponents(ctrl) if not o.lost and not o.has_hexproof()]
                    if opps:
                        game.deal_damage(src, min(opps, key=lambda o: o.life), left)
                elif pool:
                    alive = [pm for pm in pool if pm in pm.controller.battlefield]
                    if alive:
                        game.deal_damage(src, alive[0], left)
            game.log(f"{ctrl.name} reparte {_n} de daño")
            game.sba()
        return eff_divided
    # ── batch 6: debuffs / pumps en masa y dirigidos, top of library ──
    m = re.fullmatch(r"creatures your opponents control get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_opp_mass(game, ctrl, *a, _p=int(m.group(1)), _t=int(m.group(2)), **kw):
            for o in game.opponents(ctrl):
                for pm in o.creatures():
                    pm.temp_pt[0] += _p
                    pm.temp_pt[1] += _t
            game.sba()
        return eff_opp_mass
    m = re.fullmatch(r"attacking creatures(?: you control)? get ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        def eff_atk_mass(game, ctrl, *a, _p=int(m.group(1)), _t=int(m.group(2)), **kw):
            for pm in ctrl.creatures():
                if pm.attacking is not None:
                    pm.temp_pt[0] += _p
                    pm.temp_pt[1] += _t
        return eff_atk_mass
    m = re.fullmatch(r"(?:up to one )?target creature( an opponent controls| you don't control| you "
                     r"control)? gets ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        dp, dt = int(m.group(2)), int(m.group(3))
        who = (m.group(1) or "").strip()

        def eff_tgt_pt(game, ctrl, *a, _p=dp, _t=dt, _w=who, **kw):
            bad = _p < 0 or _t < 0
            if _w == "you control" or (not bad and not _w):
                pool = sorted(ctrl.creatures(), key=lambda x: x.power + x.toughness, reverse=True)
            else:
                pool = [pm for o in game.opponents(ctrl) for pm in o.creatures()
                        if game.can_target(ctrl, pm)]
                pool.sort(key=lambda x: (x.toughness - x.damage + _t <= 0, x.power), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(pm):
                if pm in pm.controller.battlefield:
                    pm.temp_pt[0] += _p
                    pm.temp_pt[1] += _t
                    game.log(f"{pm.name} recibe {_p:+d}/{_t:+d}")
                    game.sba()
            _human_target_choice(game, ctrl, "etb_target", f"Elegí la criatura ({_p:+d}/{_t:+d})",
                                 cands, _do)
        return eff_tgt_pt
    # ── acciones clave (batch 3) ──
    m = re.fullmatch(r"(?:you may )?earthbend (\w+)", t)
    if m and (n := _count_word(m.group(1))):
        return lambda game, ctrl, *a, _n=n, **kw: game.animate_land(ctrl, _n, earthbend=True)
    if t in ("venture into the dungeon", "you venture into the dungeon"):
        return lambda game, ctrl, *a, **kw: game.venture(ctrl)
    if t in ("venture into undercity", "you venture into undercity"):
        return lambda game, ctrl, *a, **kw: game.venture(ctrl, undercity=True)
    if t in ("you take the initiative", "take the initiative"):
        return lambda game, ctrl, *a, **kw: game.take_initiative(ctrl)
    m = re.fullmatch(r"(?:you may )?blight (\w+)", t)
    if m and (n := _count_word(m.group(1))):
        def eff_blight(game, ctrl, *a, _n=n, **_kw):
            pool = list(ctrl.creatures())
            if not pool:
                return
            pm = min(pool, key=lambda x: (not x.is_token, x.power + x.toughness))
            game.add_counters(pm, "-1/-1", _n)
            game.log(f"{ctrl.name} plaga {_n} sobre {pm.name}")
            game.sba()
        return eff_blight
    m = re.fullmatch(r"(?:you may )?collect evidence (\d+)", t)
    if m:
        def eff_evidence(game, ctrl, *a, _n=int(m.group(1)), **_kw):
            pool = sorted(ctrl.graveyard, key=lambda c: -(c.cost.cmc if c.cost else 0))
            pick, tot = [], 0
            for c in pool:
                if tot >= _n:
                    break
                v = c.cost.cmc if c.cost else 0
                if v <= 0:
                    continue
                pick.append(c)
                tot += v
            if tot < _n:
                return
            for c in pick:
                ctrl.graveyard.remove(c)
                ctrl.exile.append(c)
            game.emit("leaves_graveyard", player=ctrl)
            game.log(f"{ctrl.name} reúne evidencia ({tot})")
        return eff_evidence
    if t in ("learn", "you learn"):
        def eff_learn(game, ctrl, *a, **_kw):
            if ctrl.hand:
                pol = ctrl.policy
                c = pol.choose_discard(game, ctrl) if pol and hasattr(pol, "choose_discard") \
                    else ctrl.hand[-1]
                if c in ctrl.hand:
                    ctrl.hand.remove(c)
                    game.discard_card(ctrl, c)
            ctrl.draw(1, game)
            game.log(f"{ctrl.name} aprende (descarta y roba)")
        return eff_learn
    if t in ("recruit", "you recruit"):
        def eff_recruit(game, ctrl, *a, **_kw):
            ctrl.draw(1, game)
            if not ctrl.hand:
                return
            pol = ctrl.policy
            c = pol.choose_discard(game, ctrl) if pol and hasattr(pol, "choose_discard") \
                else ctrl.hand[-1]
            if c in ctrl.hand:
                ctrl.hand.remove(c)
                game.discard_card(ctrl, c)
                if not c.is_land():
                    cards.make_token(game, ctrl, "Human Soldier", 1, 1,
                                     subtypes=("Human", "Soldier"))
        return eff_recruit
    if t in ("forage", "you forage"):
        def eff_forage(game, ctrl, *a, **_kw):
            if len(ctrl.graveyard) >= 3:
                for _ in range(3):
                    ctrl.exile.append(ctrl.graveyard.pop(0))
                game.emit("leaves_graveyard", player=ctrl)
                game.log(f"{ctrl.name} forrajea (exilia 3 del cementerio)")
                return
            food = [pm for pm in ctrl.battlefield if pm.name.lower() == "food"]
            if food:
                game.to_graveyard(food[0], "forage")
                game.log(f"{ctrl.name} forrajea (sacrifica una Comida)")
        return eff_forage
    if t in ("time travel", "you time travel"):
        def eff_tt(game, ctrl, *a, **_kw):
            for e in game.suspended:
                if e["player"] is ctrl and e["n"] > 1:
                    e["n"] -= 1
            for pm in ctrl.battlefield:
                if pm.counters.get("time", 0) > 1:
                    pm.counters["time"] -= 1
            game.log(f"{ctrl.name} viaja en el tiempo")
        return eff_tt
    m = re.fullmatch(r"(?:you may )?suspect (it|that creature|" + _SELF_REF + r")", t)
    if m:
        def eff_suspect_self(game, ctrl, *a, _w=m.group(1), **_kw):
            pm = (getattr(game, "_trigger_subject", None) if _w in ("it", "that creature")
                  else None) or _src_perm(game, a)
            if pm is not None and hasattr(pm, "card"):
                pm.suspected = True
                pm.perma_keywords.add("menace")
                game.log(f"{pm.name} es sospechosa")
        return eff_suspect_self

    # phasing sin objetivo: "all permanents/creatures you control phase out",
    # "~ phases out"
    m = re.fullmatch(r"(?:all|each) (permanents?|creatures?|nonland permanents?) you control "
                     r"phases? out|" + _SELF_REF + r" phases out", t)
    if m:
        kind = (m.group(1) or "").rstrip("s")

        def eff_phase_all(game, ctrl, *a, _k=kind, **_kw):
            if not _k:
                src = _src_perm(game, a)
                if src is not None:
                    game.phase_out(src)
                return
            for pm in list(ctrl.battlefield):
                if _k == "creature" and not pm.is_creature():
                    continue
                if _k.startswith("nonland") and pm.card.is_land():
                    continue
                if pm.enchanting is None:
                    game.phase_out(pm)
        return eff_phase_all

    # manifest / manifest dread / cloak: criatura 2/2 boca abajo desde la biblioteca
    m = re.fullmatch(r"(?:you may )?(?:(manifest dread)( twice)?|(manifest|cloak) the top "
                     r"(?:(two|three|four|\d+) )?cards? of your library)"
                     r"(?:,? (?:then|and) put (a|an|one|two|three|\d+) \+1/\+1 counters? on "
                     r"(?:it|that creature|each of them))?"
                     r"(?:,? (?:then|and) attach this (?:equipment|enchantment) to "
                     r"(?:it|that creature))?", t)
    if m:
        dread = bool(m.group(1))
        kind = "cloak" if m.group(3) == "cloak" else "manifest"
        n = 2 if m.group(2) else (_count_word(m.group(4)) or 1 if m.group(4) else 1)
        ctr = (_count_word(m.group(5)) or 1) if m.group(5) else 0
        attach = "attach this" in t

        def eff_manifest(game, ctrl, *a, _n=n, _k=kind, _d=dread, _c=ctr, _at=attach,
                         **_kw):
            made = game.manifest(ctrl, _n, kind=_k, dread=_d)
            for pm in made:
                if _c:
                    game.add_counters(pm, "+1/+1", _c)
            if _at and made:
                src = _src_perm(game, a)
                if src is not None and src in src.controller.battlefield:
                    src.enchanting = made[-1]
                    game.log(f"{src.name} se anexa a la criatura boca abajo")
        return eff_manifest

    # contadores sobre la PROPIA carta: "put a +1/+1 counter on this creature / ~ / it"
    m = re.fullmatch(r"put (a|an|one|two|three|four|five|\d+) ([+-]\d+/[+-]\d+|[a-z]+) "
                     r"counters? on (?:" + _SELF_REF + r"|it)", t)
    if m:
        n, kind = _count_word(m.group(1)) or 1, m.group(2)

        def eff_self_counter(game, ctrl, *a, _n=n, _k=kind, **_kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                game.add_counters(src, _k, _n)
                game.sba()
        return eff_self_counter

    # -1/-1 (o +1/+1) en criatura OBJETIVO: el bot elige (rival para -1/-1)
    m = re.fullmatch(r"put (a|an|one|two|three|\d+) ([+-]1/[+-]1) counters? on "
                     r"(?:up to one )?target creature(?: (you control|an opponent controls|"
                     r"you don't control))?", t)
    if m:
        n, kind, who = _count_word(m.group(1)) or 1, m.group(2), m.group(3) or ""
        hostile = kind.startswith("-")

        def eff_tgt_counter(game, ctrl, *a, _n=n, _k=kind, _h=hostile, _w=who, **_kw):
            if _w == "you control":
                pool = list(ctrl.creatures())
            elif _w:
                pool = game.legal_creature_targets(ctrl)
            else:
                pool = (game.legal_creature_targets(ctrl) if _h else list(ctrl.creatures())) \
                    or [pm for pl in game.players for pm in pl.creatures()]
            if not pool:
                return
            pool.sort(key=lambda pm: (pm.toughness if _h else -(pm.power + pm.toughness)))
            if _h:   # rival: primero lo que mata, si no lo más grande
                kill = [pm for pm in pool if pm.toughness <= _n]
                pool = kill + [pm for pm in pool if pm not in kill]
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(pm):
                game.add_counters(pm, _k, _n)
                game.sba()
            _human_target_choice(game, ctrl, "etb_target",
                                 f"Elegí una criatura ({_n} contador {_k})", cands, _do)
        return eff_tgt_counter

    # "this creature deals N damage to that creature" (bloqueo / disparo con sujeto)
    m = re.fullmatch(_SELF_REF + r" deals (\w+) damage to that creature", t)
    if m and (n := _count_word(m.group(1))):
        def eff_dmg_subject(game, ctrl, *a, _n=n, **_kw):
            src = _src_perm(game, a)
            tgt = getattr(game, "_trigger_subject", None)
            if tgt is not None and hasattr(tgt, "card") and tgt in tgt.controller.battlefield:
                game.deal_damage(src, tgt, _n)
                game.sba()
        return eff_dmg_subject
    # la propia criatura: "+N/+N hasta fin de turno" / "gana <keyword> hasta fin de turno"
    m = re.fullmatch(_SELF_REF + r" gets ([+-]\d+)/([+-]\d+) until end of turn", t)
    if m:
        dp, dt = int(m.group(1)), int(m.group(2))

        def eff_self_pump(game, ctrl, *a, _p=dp, _t=dt, **_kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                src.temp_pt[0] += _p
                src.temp_pt[1] += _t
                game.sba()
        return eff_self_pump
    m = re.fullmatch(_SELF_REF + r" gains? ([a-z ,]+?) until end of turn", t)
    if m:
        kws = [k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+",
                                                             m.group(1)) if k.strip()]
        if kws and all(k in KEYWORDS for k in kws):
            def eff_self_kw(game, ctrl, *a, _k=tuple(kws), **_kw):
                src = _src_perm(game, a)
                if src is not None:
                    src.temp_keywords |= set(_k)
            return eff_self_kw
    if re.fullmatch(r"regenerate " + _SELF_REF, t):
        def eff_regen(game, ctrl, *a, **_kw):
            src = _src_perm(game, a)
            if src is not None:
                src.temp_keywords.add("indestructible")    # aproximación de regenerar
        return eff_regen
    m = re.fullmatch(r"create an? ([a-z]+(?: hero)?) role token attached to (another target "
                     r"creature you control|up to one target creature you control|target "
                     r"creature you control|it|this creature|target creature an opponent "
                     r"controls|target creature)", t)
    if m:
        def eff_role(game, ctrl, *a, _k=m.group(1), _w=m.group(2), **_kw):
            src = _src_perm(game, a)
            if _w in ("it", "this creature"):
                host = getattr(game, "_trigger_subject", None) or src
            elif "opponent" in _w or (_k == "cursed" and _w == "target creature"):
                pool = game.legal_creature_targets(ctrl)
                host = max(pool, key=lambda x: x.power + x.toughness) if pool else None
            else:
                pool = [pm for pm in ctrl.creatures() if not ("another" in _w and pm is src)]
                host = max(pool, key=lambda x: x.power + x.toughness) if pool else None
            if host is not None and hasattr(host, "card"):
                game.create_role(ctrl, host, _k)
        return eff_role
    m = re.fullmatch(r"discover (\d+)", t)
    if m:
        return lambda game, ctrl, *a, _n=int(m.group(1)), **kw: game.discover(ctrl, _n)
    m = re.fullmatch(r"clash with (?:an opponent|defending player)(?:\. if you win, (.+))?", t)
    if m:
        _we = _effect_any(m.group(1)) if m.group(1) else None

        def eff_clash(game, ctrl, *a, _e=_we, **_kw):
            if game.clash(ctrl) and _e is not None:
                _e(game, ctrl, *a)
        return eff_clash
    m = re.fullmatch(r"attach (?:it|this equipment|~) to (?:up to one )?target creature you "
                     r"control", t)
    if m:
        def eff_attach_eq(game, ctrl, *a, **_kw):
            src = _src_perm(game, a)
            pool = [pm for pm in ctrl.creatures() if pm is not src]
            if src is None or not pool:
                return
            host = max(pool, key=lambda pm: (pm.power + pm.toughness))
            src.enchanting = host
            game._trigger_subject = host
            game.log(f"{ctrl.name}: {src.name} se anexa a {host.name}")
        return eff_attach_eq
    m = re.fullmatch(r"(?:you )?get ((?:\{e\})+)", t)
    if m:
        n = m.group(1).count("{e}")

        def eff_energy(game, ctrl, *a, _n=n, **_kw):
            _n *= 2 ** sum(1 for pm in ctrl.battlefield if getattr(pm.card, "energy_double", False))
            ctrl.energy = getattr(ctrl, "energy", 0) + _n
            game.log(f"{ctrl.name} obtiene {_n} de energía")
        return eff_energy
    m = re.fullmatch(r"double the number of \+1/\+1 counters on (?:" + _SELF_REF + r"|it|"
                     r"that creature|target creature you control)", t)
    if m:
        def eff_double_ctr(game, ctrl, *a, _t=t, **_kw):
            pm = (getattr(game, "_trigger_subject", None) if ("that creature" in _t or
                  _t.endswith(" it")) else None) or _src_perm(game, a)
            if "target creature" in _t:
                pool = [x for x in ctrl.creatures() if x.counters.get("+1/+1", 0)]
                pm = max(pool, key=lambda x: x.counters["+1/+1"]) if pool else None
            if pm is not None and hasattr(pm, "counters") and pm.counters.get("+1/+1", 0):
                game.add_counters(pm, "+1/+1", pm.counters["+1/+1"])
        return eff_double_ctr
    m = re.fullmatch(r"double (?:target creature's|" + _SELF_REF + r"'s|its) power(?: and "
                     r"toughness)? until end of turn", t)
    if m:
        def eff_double_pw(game, ctrl, *a, _t=t, **_kw):
            if "target" in _t:
                pool = list(ctrl.creatures())
                pm = max(pool, key=lambda x: x.power) if pool else None
            else:
                pm = _src_perm(game, a)
            if pm is not None and hasattr(pm, "temp_pt"):
                pm.temp_pt[0] += max(0, pm.power)
                if "toughness" in _t:
                    pm.temp_pt[1] += max(0, pm.toughness)
        return eff_double_pw
    if t in ("populate", "then populate"):
        _pe = _populate_effect()
        return lambda game, ctrl, *a, _p=_pe, **kw: _p(game, ctrl, [])
    m = re.fullmatch(r"(?:it|that creature|target creature you control) connives?", t)
    if m:
        def eff_it_connive(game, ctrl, *a, _t=t, **_kw):
            if "target" in _t:
                pool = list(ctrl.creatures())
                pm = max(pool, key=lambda x: x.power) if pool else None
            else:
                pm = getattr(game, "_trigger_subject", None) or _src_perm(game, a)
            if pm is not None and hasattr(pm, "card"):
                _do_connive(game, pm, 1)
        return eff_it_connive
    if re.fullmatch(_SELF_REF + r" connives?", t) or t == "connive":
        def eff_connive(game, ctrl, *a, **_kw):
            src = _src_perm(game, a)
            if src is not None and src in src.controller.battlefield:
                _do_connive(game, src, 1)
        return eff_connive
    # monarca (regla del juego en el motor: robo al final del turno; se roba con
    # daño de combate)
    if t == "you become the monarch":
        def eff_monarch(game, ctrl, *a, **_kw):
            game.set_monarch(ctrl)
        return eff_monarch

    # goad / pelear / no puede bloquear (con objetivo elegido al resolver)
    if re.fullmatch(r"goad (?:all|each) creatures? (?:you don't control|your opponents control)", t) \
            or re.fullmatch(r"goad each creature target (?:player|opponent) controls", t):
        _one = "target" in t

        def eff_goad_all(game, ctrl, *a, _o=_one, **_kw):
            opps = game.targetable_opponents(ctrl) if _o else game.opponents(ctrl)
            if _o and opps:
                opps = [max(opps, key=lambda o: sum(pm.power for pm in o.creatures()))]
            n = 0
            for o in opps:
                for pm in o.creatures():
                    pm.goaded = True
                    n += 1
            game.log(f"{ctrl.name} provoca (goad) a {n} criatura(s)")
        return eff_goad_all
    if re.fullmatch(r"(?:you may )?goad (?:up to one )?target creature(?: an opponent controls| "
                    r"defending player controls| that player controls)?", t):
        def eff_goad(game, ctrl, *a, **_kw):
            pool = sorted(game.legal_creature_targets(ctrl),
                          key=lambda pm: -(pm.power + pm.toughness))
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(pm):
                pm.goaded = True
                game.log(f"{ctrl.name} provoca (goad) a {pm.name}")
            _human_target_choice(game, ctrl, "etb_target", "Provocar (goad):", cands, _do)
        return eff_goad
    if re.fullmatch(_SELF_REF + r" fights (?:up to one )?target creature"
                    r"(?: you don't control| an opponent controls)?", t) or \
            re.fullmatch(r"fight (?:up to one )?target creature(?: you don't control| an "
                         r"opponent controls)?", t):
        def eff_fight(game, ctrl, *a, **_kw):
            src = _src_perm(game, a)
            if src is None or src not in src.controller.battlefield:
                return
            pool = [pm for pm in game.legal_creature_targets(ctrl)]
            # el bot pelea con lo que mata sin morir; si no, con lo que mata
            pool.sort(key=lambda pm: (not (src.power >= pm.toughness and pm.power < src.toughness),
                                      not (src.power >= pm.toughness), -pm.power))
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(pm):
                a1, a2 = src.power, pm.power
                game.deal_damage(src, pm, a1)
                game.deal_damage(pm, src, a2)
                game.log(f"{src.name} pelea con {pm.name}")
                game.sba()
            _human_target_choice(game, ctrl, "etb_target", "Pelear con:", cands, _do,
                                 allow_none=True)
        return eff_fight
    if re.fullmatch(r"(?:up to one )?target creature can't block this turn", t):
        def eff_cant_block(game, ctrl, *a, **_kw):
            pool = sorted(game.legal_creature_targets(ctrl), key=lambda pm: -pm.toughness)
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]
            _human_target_choice(game, ctrl, "etb_target", "No puede bloquear:", cands,
                                 lambda pm: pm.temp_keywords.add("cant_block"))
        return eff_cant_block

    # sacrificar como EFECTO propio ("sacrifice a creature/artifact")
    m = re.fullmatch(r"(?:you )?sacrifice (?:a|an|another) (creature|artifact|land|"
                     r"enchantment|permanent)", t)
    if m:
        def eff_sac(game, ctrl, *a, _k=m.group(1), **_kw):
            src = _src_perm(game, a)
            v = game._sacrifice_candidates(ctrl, _k, 1, exclude=src if "another" in t else None)
            if v:
                game.to_graveyard(v[0], "sacrificio")
                game.log(f"{ctrl.name} sacrifica {v[0].name}")
        return eff_sac

    # exiliar del cementerio (odio de cementerio puntual)
    m = re.fullmatch(r"exile (?:up to one )?target (creature |nonland |artifact |"
                     r"instant or sorcery )?card from (?:a|an opponent's) graveyard", t)
    if m:
        _kind = (m.group(1) or "").strip()

        def _ok(c, _k=_kind):
            if _k == "creature":
                return "creature" in c.types
            if _k == "nonland":
                return not c.is_land()
            if _k == "artifact":
                return "artifact" in c.types
            if _k == "instant or sorcery":
                return bool({"instant", "sorcery"} & c.types)
            return True

        def eff_gy_hate(game, ctrl, *a, **_kw):
            best = None
            for o in game.opponents(ctrl):
                for c in [x for x in o.graveyard if _ok(x)]:
                    v = (("creature" in c.types) * 10 + (c.cost.cmc if c.cost else 0))
                    if best is None or v > best[0]:
                        best = (v, o, c)
            if best:
                _v, o, c = best
                o.graveyard[:] = [x for x in o.graveyard if x is not c]
                o.exile.append(c)
                game.emit("leaves_graveyard", player=o, card=c)
                game.log(f"{ctrl.name} exilia {c.name} del cementerio de {o.name}")
        return eff_gy_hate

    m = re.fullmatch(r"each (other player|opponent|player) sacrifices (?:a|an|one) "
                     r"(creature|artifact|enchantment|land|permanent|nonland permanent)"
                     r"(?: of their choice)?", t)
    if m:
        def eff_each_sac(game, ctrl, *a, _w=m.group(1), _k=m.group(2), **_kw):
            pls = (game.players if _w == "player" else game.opponents(ctrl))
            for pl in list(pls):
                if pl.lost:
                    continue
                k = "permanent" if _k == "nonland permanent" else _k
                pool = game._sacrifice_candidates(pl, k, 5)
                if _k == "nonland permanent":
                    pool = [pm for pm in pool if not pm.card.is_land()]
                if pool:
                    game.to_graveyard(pool[0], "sacrificio")
                    game.log(f"{pl.name} sacrifica {pool[0].name}")
            game.sba()
        return eff_each_sac
    m = re.fullmatch(r"return all (nonland permanents|creatures|other creatures|"
                     r"artifacts|enchantments|attacking creatures) to their owners'? hands?", t)
    if m:
        def eff_mass_bounce(game, ctrl, *a, _k=m.group(1), **_kw):
            src = _src_perm(game, a)
            for pl in game.players:
                for pm in list(pl.battlefield):
                    hit = ((_k == "nonland permanents" and not pm.card.is_land())
                           or (_k in ("creatures", "other creatures") and pm.is_creature()
                               and not (_k == "other creatures" and pm is src))
                           or (_k == "attacking creatures" and pm.attacking is not None)
                           or (_k == "artifacts" and "artifact" in pm.card.types)
                           or (_k == "enchantments" and "enchantment" in pm.card.types))
                    if not hit:
                        continue
                    pl.battlefield.remove(pm)
                    if pm.is_token:
                        continue
                    owner = game.commander_owner(pm.card)
                    (owner.command if owner is not None else pl.hand).append(pm.card)
            game.log(f"{ctrl.name} devuelve {_k} a la mano")
            game.sba()
        return eff_mass_bounce
    m = re.fullmatch(r"exile all (creatures|nonland permanents|artifacts|enchantments|"
                     r"creatures you don't control|graveyards)", t)
    if m:
        def eff_mass_exile(game, ctrl, *a, _k=m.group(1), **_kw):
            if _k == "graveyards":
                for pl in game.players:
                    for c in list(pl.graveyard):
                        pl.graveyard.remove(c)
                        pl.exile.append(c)
                        game.emit("leaves_graveyard", player=pl, card=c)
                return
            for pl in game.players:
                for pm in list(pl.battlefield):
                    hit = ((_k.startswith("creatures") and pm.is_creature()
                            and not (_k.endswith("control") and pl is ctrl))
                           or (_k == "nonland permanents" and not pm.card.is_land())
                           or (_k == "artifacts" and "artifact" in pm.card.types)
                           or (_k == "enchantments" and "enchantment" in pm.card.types))
                    if not hit:
                        continue
                    pl.battlefield.remove(pm)
                    if pm.card.on_leave:
                        pm.card.on_leave(game, pl, pm)
                    if pm.is_token:
                        continue
                    owner = game.commander_owner(pm.card)
                    (owner.command if owner is not None else pl.exile).append(pm.card)
            game.log(f"{ctrl.name} exilia {_k}")
            game.sba()
        return eff_mass_exile
    if re.fullmatch(r"shuffle your graveyard into your library", t):
        def eff_gy_shuffle(game, ctrl, *a, **_kw):
            for c in list(ctrl.graveyard):
                ctrl.graveyard.remove(c)
                ctrl.library.append(c)
                game.emit("leaves_graveyard", player=ctrl, card=c)
            game.rng.shuffle(ctrl.library)
        return eff_gy_shuffle

    m = re.fullmatch(r"(?:you may )?put a land card from your hand onto the battlefield( tapped)?", t)
    if m:
        def eff_land_from_hand(game, ctrl, *a, _tap=bool(m.group(1)), **_kw):
            lands = [c for c in ctrl.hand if c.is_land()]
            if not lands:
                return
            c = lands[0]
            ctrl.hand.remove(c)
            pm = game.move_to_battlefield(c, ctrl)
            if pm is not None and _tap:
                pm.tapped = True
            game.log(f"{ctrl.name} pone {c.name} en el campo desde la mano")
        return eff_land_from_hand

    # "that player" del disparo (defensor / quien lanzó / quien robó)
    m = re.fullmatch(r"that player (discards|loses|draws|mills) (a|an|one|two|three|\d+) ?"
                     r"(cards?|life)?", t)
    if m:
        verb, n = m.group(1), _count_word(m.group(2)) or 1

        def eff_that_player(game, ctrl, *a, _v=verb, _n=n, **_kw):
            pl = _that_player(game, ctrl)
            if pl is None:
                return
            if _v == "discards":
                _human_or_auto_discard(game, pl, _n)
            elif _v == "loses":
                pl.life -= _n
            elif _v == "draws":
                pl.draw(_n, game)
            elif _v == "mills":
                cards.mill(game, pl, _n)
        return eff_that_player
    return None


def _state_sig(game):
    """Huella del estado (zonas, vida, contadores) para saber si un efecto 'hizo algo'."""
    out = []
    for p in game.players:
        out.append((len(p.library), len(p.hand), len(p.graveyard), len(p.exile),
                    len(p.battlefield), p.life, p.poison,
                    sum(sum(pm.counters.values()) for pm in p.battlefield),
                    sum(1 for pm in p.battlefield if pm.tapped)))
    out.append(getattr(game, "_sig_bump", 0))
    return tuple(out)


_RIDER_RX = re.compile(
    r"(?:it|they|that creature|those creatures) can't be regenerated"
    r"|this effect doesn't remove (?:this aura|~)"
    r"|you may choose new targets for the cop(?:y|ies)"
    r"|if (?:that spell|a spell cast this way|it) would be put into (?:your|a|its owner's) graveyard,? exile it instead"
    r"|if you search your library this way, shuffle"
    r"|each player who searched their library this way shuffles"
    r"|(?:that player|then|target player) shuffles?(?: their library)?"
    r"|shuffle your library|then shuffle|shuffle"
    r"|exile ~|exile this (?:spell|card)"
    r"|(?:this|that) damage can't be prevented"
    r"|you may choose the same mode more than once"
    r"|this effect can't reduce the mana in that cost to less than (?:one|\d+) mana"
    r"|spend this mana only to cast [^.]+")


_EQ_RW = [
    (r"(.*?)\bdraws? cards equal to (.+)", r"\1draw x cards, where x is \2"),
    (r"(.*?)\b(gains?) life equal to (.+)", r"\1\2 x life, where x is \3"),
    (r"(.*?)\b(loses?) life equal to (.+)", r"\1\2 x life, where x is \3"),
    (r"(.*?)\bdeals? damage to (.+?) equal to (.+)", r"\1deals x damage to \2, where x is \3"),
    (r"(.*?)\bdeals? damage equal to (.+?) to (.+)", r"\1deals x damage to \3, where x is \2"),
    (r"(.*?)\bcreate a number of (.+?) tokens? equal to (.+)", r"\1create x \2 tokens, where x is \3"),
    (r"(.*?)\bmills? cards equal to (.+)", r"\1mill x cards, where x is \2"),
    (r"(.*?)\bput a number of (\+1/\+1|[a-z]+) counters on (.+?) equal to (.+)",
     r"\1put x \2 counters on \3, where x is \4"),
    (r"(.*?)\bscry (?:a number )?equal to (.+)", r"\1scry x, where x is \2"),
    (r"(.*?)\bdiscards? cards equal to (.+)", r"\1discard x cards, where x is \2"),
]


def _equal_to_effect(text):
    """'draw cards equal to <cantidad>' y afines -> forma 'X …, where X is …'."""
    t = re.sub(r"\s+", " ", (text or "")).strip().rstrip(".")
    if t.count(".") or "equal to" not in t.lower():
        return None
    for pat, sub in _EQ_RW:
        if re.fullmatch("(?i)" + pat, t):
            return _where_x_effect(re.sub("(?i)" + pat, sub, t) + ".")
    return None


def _generic_amount_effect(oracle: str):
    r = _generic_amount_effect0(oracle)
    if r is None and oracle and re.search(r"(?i)where x is", oracle):
        r = _where_x_effect(_strip_reminder(oracle))
    if r is None and oracle and re.search(r"(?i)equal to", oracle):
        r = _equal_to_effect(_strip_reminder(oracle))
    return r


def _generic_amount_effect0(oracle: str):
    """Efecto genérico de un texto, ENCADENANDO las oraciones independientes.

    _generic_amount_single devuelve la PRIMERA regla que coincide: "You draw two
    cards and you lose 2 life" (Night's Whisper) caía en "lose N life" y no robaba;
    "Draw two cards and create two Treasure tokens" solo creaba los tesoros. Acá se
    parte el texto en cláusulas; si 2 o más producen efecto y ninguna es
    condicional ("if you do", "otherwise"...), se aplican todas en orden. Si no,
    queda el comportamiento de siempre (una sola regla sobre todo el texto)."""
    # sin habilidades activadas (un instantáneo como Lightning Storm trae
    # "Discard a land card: …" que no es parte de su efecto al resolver)
    text = _non_activated_text(_strip_reminder(oracle or ""))
    # "X damage, where X is N plus the number of charge counters on it": los
    # contadores de carga de un hechizo en la pila no se modelan -> X = N
    text = re.sub(r"deals x damage(.*?),? where x is (\d+) plus the number of charge "
                  r"counters on (?:it|[\w' ,]+?)\.", r"deals \2 damage\1.", text, flags=re.I)
    # el coste adicional NO es un efecto ("As an additional cost to cast this
    # spell, discard a card." lo paga el motor al lanzar)
    sents = [x for x in re.split(r"(?<=\.)\s+", re.sub(r"\s+", " ", text).strip()) if x]
    sents = [x for x in sents if not re.match(r"as an additional cost", x, re.I)]
    # oraciones "cola" sin efecto de juego en la simulación: no deben bloquear el
    # parseo del resto de la habilidad (antes una sola de estas dejaba toda la línea
    # sin efecto)
    sents = [x for x in sents if not _RIDER_RX.fullmatch(x.strip().rstrip(".").lower())] or sents
    text = " ".join(sents)
    text = re.sub(r"\.\s*when you do,", ". If you do,", text, flags=re.I)
    low = text.lower()
    # "<base>. <alt> instead if <cond>." / "<base>. If <cond>, <alt> instead." (Cabal
    # Ritual, spell mastery, delirium…): uno u otro, nunca la suma de ambos.
    if len(sents) >= 2:
        _last = sents[-1]
        _mi = (re.match(r"(?P<alt>.+?) instead if (?P<cond>.+?)\.?$", _last, re.I)
               or re.match(r"if (?P<cond>[^,]+), (?P<alt>.+?) instead\.?$", _last, re.I))
        if _mi:
            _base = _generic_amount_effect(" ".join(sents[:-1]))
            _gc = _cond_gc(_mi.group("cond"))
            _alt = _effect_any(_mi.group("alt").strip() + ".") if _gc is not None else None
            if _base is None:
                return None
            if _alt is None:
                return _base                   # condición desconocida: solo la base

            def eff_instead(game, ctrl, *a, _b=_base, _a=_alt, _c=_gc, **kw):
                try:
                    ok = _c(game, ctrl)
                except Exception:  # noqa: BLE001
                    ok = False
                (_a if ok else _b)(game, ctrl, *a)
            return eff_instead
    # condición de intervención "if <condición>, <efecto>" (raid, morbid, revolt,
    # ferocious…): el efecto solo si la condición se cumple al resolver
    _mif = re.match(r"\s*if ([^,]+),\s*(.+)$", text, re.I | re.S)
    if _mif and (_gc := _cond_gc(_mif.group(1))) is not None:
        _body = re.sub(r"\s+instead\.?$", ".", _mif.group(2).strip())
        _eb = _effect_any(_body)
        if _eb is None:
            return None

        def eff_if(game, ctrl, *a, _c=_gc, _e=_eb, **kw):
            try:
                ok = _c(game, ctrl)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                _e(game, ctrl, *a)
        return eff_if
    # "<A>. If you do, <B>": B solo si A tuvo efecto (cambió zonas/vida/campo).
    # Antes se ignoraba la condición (Uchuulon copiaba aunque no exiliara nada).
    _iyd = re.match(r"\s*(?!you may pay)(.+?)\.\s*if you do,\s*(.+)$", text, re.I | re.S)
    if _iyd:
        _ea = _effect_any(_iyd.group(1))
        _eb = _effect_any(_iyd.group(2))
        if _ea is None or _eb is None:
            return _atomic_effect(text)       # texto completo como atómico (Victimize…) o nada

        def eff_if_you_do(game, ctrl, *a, _a=_ea, _b=_eb, **kw):
            before = _state_sig(game)
            _a(game, ctrl, *a)
            if _state_sig(game) != before:
                _b(game, ctrl, *a)
        return eff_if_you_do
    # pago OPCIONAL de ENERGÍA: "you may pay {E}{E}. If you do, <efecto>"
    _mpe = re.match(r"\s*you may pay (?:((?:\{e\})+)|(\w+) \{e\})\.\s*(?:if|when) you do,\s*(.+)$", text, re.I)
    if _mpe:
        _ne = (_mpe.group(1).lower().count("{e}") if _mpe.group(1) else _count_word(_mpe.group(2).lower())) or 0
        _inner = _effect_any(_mpe.group(3)) if _ne else None
        if _inner is not None:
            def eff_may_pay_energy(game, ctrl, *a, _n=_ne, _e=_inner, **kw):
                if getattr(ctrl, "energy", 0) >= _n:
                    ctrl.energy -= _n
                    game.log(f"{ctrl.name} paga {_n} de energía")
                    _e(game, ctrl, *a)
            return eff_may_pay_energy
        return None
    # pago OPCIONAL de VIDA: "you may pay N life. If you do, <efecto>"
    _mpl = re.match(r"\s*you may pay (\w+) life\.\s*(?:if|when) you do,\s*(.+)$", text, re.I)
    if _mpl and _count_word(_mpl.group(1).lower()):
        _inner = _effect_any(_mpl.group(2))
        if _inner is not None:
            def eff_may_pay_life(game, ctrl, *a, _n=_count_word(_mpl.group(1).lower()), _e=_inner, **kw):
                if ctrl.life > _n + 8:
                    ctrl.life -= _n
                    _e(game, ctrl, *a)
            return eff_may_pay_life
    # pago OPCIONAL: "you may pay {N}. If you do, <efecto>" -> paga si puede
    _mp = re.match(r"\s*you may pay ((?:\{[^}]+\})+)\.\s*if you do,\s*(.+)$", text, re.I)
    if _mp:
        try:
            _pc = parse_cost("".join(re.findall(r"\{([^}]+)\}", _mp.group(1))))
        except ValueError:
            _pc = None
        _inner = _effect_any(_mp.group(2)) if _pc is not None else None
        if _inner is not None:
            def eff_may_pay(game, ctrl, *a, _c=_pc, _e=_inner, **kw):
                if ctrl.can_pay(_c):
                    ctrl.pay(_c)
                    _e(game, ctrl, *a)
            return eff_may_pay
    # ficha COPIA: "…, except it has haste. Sacrifice it at the beginning of the next
    # end step." es UNA habilidad (la 2ª oración no es un sacrificio independiente)
    _cs = _copy_token_spec(text)
    if _cs is not None:
        return _copy_token_effect(_cs)
    if (not text or re.search(r"choose (?:one|two|three|one or more|one or both)", low)
            or "for each" in low):
        return _generic_amount_single(text)
    parts = [x.strip(" .,") for x in _CLAUSE_SPLIT.split(text) if x and x.strip(" .,")]
    if len(parts) >= 2 and not any(_CONDITIONAL.search(x) for x in parts):
        effs = [_generic_amount_single(x) for x in parts]
        got = [e for e in effs if e is not None]
        if len(got) >= 2:
            def chained(game, ctrl, *a, _es=tuple(got)):
                for e in _es:
                    e(game, ctrl, *a)
            return chained
    return _generic_amount_single(text)


_ATOM_NAMES = False


def _generic_amount_single(oracle: str):
    """Ver _generic_amount_single_core; si nada lo reconoce, reintenta los atómicos
    con el nombre propio de la carta como '~'."""
    global _ATOM_NAMES
    eff = _generic_amount_single_core(oracle)
    if eff is None and _CUR_NAMES and not _ATOM_NAMES:
        _ATOM_NAMES = True
        try:
            eff = _atomic_effect(oracle)
        finally:
            _ATOM_NAMES = False
    return eff


def _generic_amount_single_core(oracle: str):
    """Efecto APROXIMADO con monto, deducido del oracle. Devuelve una función
    eff(game, ctrl, *_) o None. Cubre patrones comunes de creaturas/hechizos que
    la capa por tags (wipe/removal/draw/ramp) no modela. Prioridad: fichas >
    quema a cada rival > ganancia de vida > mill propio."""
    # cortafuegos de recursión mutua con _fragment_effect: ciertos textos (p. ej.
    # "Incubate X, where X is..." de Sunfall) hacían rebotar _generic<->_fragment sin
    # fin -> RecursionError -> la carta caía a vainilla (no hacía NADA). Limitamos la
    # anidación para que el parseo continúe con las otras ramas (barrida, etc.).
    global _amt_depth
    if _amt_depth > 6:
        return None
    t = re.sub(r"\s+", " ", (oracle or "").lower())

    # ficha COPIA de una criatura/permanente (ETB, disparos, hechizos)
    _cs = _copy_token_spec(oracle)
    if _cs is not None:
        return _copy_token_effect(_cs)

    _at = _atomic_effect(oracle)
    if _at is not None:
        return _at

    # bounceland: "return a land you control to its owner's hand" (la de menos valor;
    # puede ser ella misma). Gateway Plaza & co: "sacrifice it unless you pay {N}".
    if re.fullmatch(r"\s*return a land you control to its owner's hand\.?\s*", oracle or "", re.I):
        def eff_bounce_land(game, ctrl, *a):
            lands = [pm for pm in ctrl.lands()]
            if not lands:
                return
            src = a[0] if a and hasattr(a[0], "card") else None
            lands.sort(key=lambda pm: (pm is src, "basic" not in pm.card.supertypes,
                                       not pm.tapped))
            pm = lands[0]
            ctrl.battlefield.remove(pm)
            ctrl.hand.append(pm.card)
            game.log(f"{ctrl.name} devuelve {pm.name} a la mano")
        return eff_bounce_land
    _mpay = re.fullmatch(r"\s*sacrifice it unless you pay \{(\d+)\}\.?\s*", oracle or "", re.I)
    if _mpay:
        def eff_sac_unless(game, ctrl, *a, _n=int(_mpay.group(1))):
            src = a[0] if a and hasattr(a[0], "card") else None
            if src is None:
                return
            if ctrl.can_pay(Cost(generic=_n, pips=())):
                ctrl.pay(Cost(generic=_n, pips=()))
            else:
                game.to_graveyard(src, "no pagó")
        return eff_sac_unless

    # "Discard a card." / "you discard two cards" como efecto PROPIO (Bloodrage
    # Brawler al entrar): antes no se parseaba y la carta no tenía su contra.
    _md = re.fullmatch(r"\s*(?:you )?discard (a|one|two|three|\d+) cards?\.?\s*",
                       oracle or "", re.I)
    if _md:
        _dn = _count_word(_md.group(1)) or 1

        def eff_discard(game, ctrl, *a, _n=_dn):
            _human_or_auto_discard(game, ctrl, _n)
        return eff_discard

    # barrida de DAÑO: "deals N damage to each creature [and each player]"
    # (Pyroclasm, Anger of the Gods, Blasphemous Act…). Antes no se parseaba: la
    # carta no hacía nada.
    _sw = re.search(r"deals? (\d+) damage to each (creature|other creature)"
                    r"( you don't control| your opponents control| an opponent controls)?"
                    r"(?:,? and|,)? ?(?:each (player|opponent|planeswalker))?",
                    oracle or "", re.I)
    _sw_sent = ""
    if _sw:
        _o = oracle or ""
        _a = _o.rfind(".", 0, _sw.start()) + 1
        _b = _o.find(".", _sw.end())
        _sw_sent = _o[_a:_b if _b >= 0 else len(_o)]
    _flyf = None
    if _sw:
        _mfl = re.search(r"each (?:other )?creature (with|without) flying", _sw_sent, re.I)
        _flyf = _mfl.group(1).lower() if _mfl else None
    if _sw and not re.search(r"with (?:power|toughness)|\bif |for each", _sw_sent, re.I) and \
            (_flyf or not re.search(r"with(?:out)? flying", _sw_sent, re.I)):
        _n = int(_sw.group(1))
        _opp_only = bool(_sw.group(3))
        _also = (_sw.group(4) or "").lower()

        def eff_sweep(game, ctrl, *a, _n=_n, _oo=_opp_only, _al=_also, _ff=_flyf):
            src = getattr(game, "_trigger_source", None)
            for pl in list(game.players):
                if _oo and pl is ctrl:
                    continue
                for pm in list(pl.battlefield):
                    if pm.is_creature() and pm is not src and (
                            _ff is None or (_ff == "with") == pm.has("flying")):
                        game.deal_damage(src, pm, _n)
            if _al in ("player", "opponent"):
                for pl in list(game.players):
                    if not pl.lost and (_al == "player" or pl is not ctrl):
                        game.deal_damage(src, pl, _n)
            game.log(f"{ctrl.name}: {_n} de daño a cada criatura")
            game.sba()
        eff_sweep._is_sweep = True
        return eff_sweep

    # efecto MODAL ("choose one/two/… — • ... • ..."): abre el selector de modo para
    # el humano (y el bot auto-elige). Cubre disparos/ETB modales que antes caían en
    # un patrón suelto y mostraban solo el primer modo.
    if re.search(r"choose (?:one|two|three|one or more|one or both)\s*[—\-–:]", t):
        _parsed = _parse_modes(oracle)
        if _parsed is not None:
            _modes = _parsed[0]
            return lambda game, ctrl, *_a, _m=_modes: _modal_run(game, ctrl, _m)

    # ritual de maná: "add {C}{C}{C}", "add {G}{G}", "add N mana of any color" ->
    # maná flotante (genérico). re.search (no match) para tomarlo también cuando va
    # tras un disparo ("when ~ enters, add {C}{C}{C}").
    mr = re.search(r"(?:^|[,] )add (.+)", t)
    if mr and ("mana" in mr.group(1) or re.search(r"\{[wubrgc0-9]\}", mr.group(1))):
        # solo la PRIMERA cláusula ("Add {B}{B}{B}." y no el "Threshold — Add
        # {B}x5 instead" que sigue: Cabal Ritual daba 8)
        seg = re.split(r"[.;]| instead", mr.group(1))[0]
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
                if not n:
                    return
                if _each:
                    for o in game.opponents(ctrl):
                        o.life -= n
                    game.log(f"{ctrl.name}: cada rival pierde {n} de vida" + game.src_tag())
                else:
                    _pick_opponent(game, ctrl, lambda o, _n=n: (
                        setattr(o, "life", o.life - _n),
                        game.log(f"{ctrl.name}: {o.name} pierde {_n} de vida" + game.src_tag())))
            return eff
        if re.search(r"deals? damage", t):
            def eff(game, ctrl, *_a, _c=cnt):
                n = max(0, _c(game, ctrl))
                if not n:
                    return
                _pick_opponent(game, ctrl, lambda o, _n=n: (
                    game.deal_damage(None, o, _n),
                    game.log(f"{ctrl.name}: {_n} de daño a {o.name}")))
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

    # fin de partida directo: SOLO si la oración es incondicional. Antes bastaba la
    # subcadena: Thassa's Oracle / Approach / Happily Ever After ganaban siempre y
    # los Pacts hacían perder a quien los lanzaba al resolver.
    def _uncond(phrase):
        ms = re.search(r"(?:^|[.;]\s*)([^.;]*" + phrase + r")", t)
        return bool(ms) and not re.search(
            r"\b(?:if|unless|at the beginning|when|whenever|otherwise|as long as)\b",
            ms.group(1))
    if _uncond("you win the game"):
        def eff(game, ctrl, *_a):
            for o in game.opponents(ctrl):
                o.lost = True
            game.log(f"{ctrl.name} gana la partida")
        return eff
    if _uncond("you lose the game"):
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

    # fase de combate adicional (Aggravated Assault, Combat Celebrant, Moraug…);
    # suele venir con "untap all creatures you control".
    if re.search(r"additional combat phase", t):
        untap = "untap all creatures" in t

        def eff(game, ctrl, *_a, _u=untap):
            if _u:
                for pm in ctrl.creatures():
                    pm.tapped = False
            game.extra_combats = getattr(game, "extra_combats", 0) + 1
            game.log(f"{ctrl.name}: fase de combate adicional este turno")
        return eff

    # destruir HASTA N permanentes NO-criatura (Terastodon, Decimate-tipo). El humano
    # elige uno por uno (puede parar); por cada uno destruido su controlador crea una
    # ficha 3/3 verde Elefante si el texto lo indica (Terastodon).
    mnc = re.search(r"destroy (?:up to )?(\w+ )?target noncreature permanents?", t)
    if mnc:
        n_nc = _count_word((mnc.group(1) or "").strip()) or 1
        make_ele = "elephant" in t and "3/3" in t

        def eff(game, ctrl, *_a, _n=n_nc, _ele=make_ele):
            def _pool():
                return [pm for pl in game.players for pm in pl.battlefield
                        if not pm.is_creature()]

            def _destroy_one(victim):
                if victim not in victim.controller.battlefield:
                    return
                owner = victim.controller
                game.destroy(victim, "Terastodon")
                game.log(f"{ctrl.name} destruye {victim.name} de {owner.name}")
                if _ele:
                    cards.make_token(game, owner, "Elephant", 3, 3, subtypes=("Elephant",))

            if ctrl is getattr(game, "interactive_human", None):
                st = {"left": _n}

                def _prompt():
                    if st["left"] <= 0:
                        return
                    pool = _pool()
                    if not pool:
                        return
                    cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]

                    def _do(victim):
                        _destroy_one(victim)
                        st["left"] -= 1
                        _prompt()                      # encadena la siguiente elección
                    _human_target_choice(
                        game, ctrl, "etb_target",
                        f"Elegí un permanente no-criatura para destruir "
                        f"({st['left']} restante(s), o ninguno)",
                        cands, _do, allow_none=True)
                _prompt()
            else:
                opp = [pm for o in game.opponents(ctrl) for pm in o.battlefield
                       if not pm.is_creature()]
                opp.sort(key=lambda pm: pm.card.is_land())   # no-tierras primero
                for pm in opp[:_n]:
                    _destroy_one(pm)
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

    # exiliar un permanente no-tierra (y no-ficha) que NO controlás, con CMV <= N
    # (p. ej. Skyclave Apparition). El humano elige; el bot toma el de mayor CMV.
    m = re.search(
        r"exile (?:up to \w+ )?target (?:nonland[,\s]+)?(?:nontoken[,\s]+)?permanent "
        r"(?:you don.?t control|an opponent controls)"
        r"(?: with (?:mana value|converted mana cost) (\d+) or less)?", t)
    if m:
        mv_cap = int(m.group(1)) if m.group(1) else None
        opt = "up to" in t

        def eff(game, ctrl, *_a, _cap=mv_cap, _opt=opt):
            def _cmv(pm):
                return pm.card.cost.cmc if getattr(pm.card, "cost", None) else 0
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield
                    if not pm.card.is_land() and not pm.is_token
                    and (_cap is None or _cmv(pm) <= _cap)]
            if not pool:
                game.log(f"{ctrl.name}: no hay permanente rival válido para exiliar")
                return
            pool.sort(key=lambda pm: _cmv(pm), reverse=True)   # el bot toma el mayor CMV
            cands = [(f"{pm.name} (CMV {_cmv(pm)}) · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(victim):
                owner = victim.controller
                if victim not in owner.battlefield:
                    return
                owner.battlefield.remove(victim)
                if not victim.is_token and game.commander_owner(victim.card) is None:
                    owner.exile.append(victim.card)
                game.log(f"{ctrl.name} exilia {victim.name} "
                         f"(CMV {_cmv(victim)}) de {owner.name}")
                game.sba()

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí un permanente del rival para exiliar"
                                 + (" (o ninguno)" if _opt else ""),
                                 cands, _do, allow_none=_opt)
        return eff

    # destruir / exiliar una criatura objetivo como ETB (p. ej. Ravenous Chupacabra):
    # el humano elige a cuál; el bot toma la más grande del rival.
    m = re.search(r"(destroy|exile) (?:up to )?(?:one |a |target )?target creature"
                  r"(?!\s+cards?)", t)        # "creature CARD" = carta del cementerio
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
                    if not pm.is_token and game.commander_owner(pm.card) is None:
                        owner.exile.append(pm.card)
                    game.log(f"{ctrl.name} exilia {pm.name}")
                else:
                    game.destroy(pm, "ETB")
                    game.log(f"{ctrl.name} destruye {pm.name}")

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura" + (" (o ninguna)" if _opt else ""),
                                 cands, _do, allow_none=_opt)
        return eff

    # destruir / exiliar un PERMANENTE NO criatura objetivo (tierra, artefacto,
    # encantamiento, planeswalker, permanente): White Orchid Phantom, Frost Titan,
    # etc. El humano elige; el bot toma el del RIVAL de mayor coste.
    mp = re.search(r"(destroy|exile) (?:up to )?(?:one |a |target )?target "
                   r"(land|artifact or enchantment|artifact|enchantment|planeswalker|"
                   r"nonland permanent|permanent)(?!\s+cards?)", t)
    if mp:
        _mode = "exile" if mp.group(1) == "exile" else "destroy"
        _kind = mp.group(2)
        _opt = "up to" in t

        def _match(pm, _k=_kind):
            tp = pm.card.types
            if _k == "land":
                return pm.card.is_land()
            if _k == "artifact":
                return "artifact" in tp
            if _k == "enchantment":
                return "enchantment" in tp
            if _k == "planeswalker":
                return "planeswalker" in tp
            if _k == "artifact or enchantment":
                return bool({"artifact", "enchantment"} & tp)
            if _k == "nonland permanent":
                return not pm.card.is_land()
            return True                               # "permanent"

        def eff(game, ctrl, *_a, _mode=_mode, _opt=_opt, _m=_match):
            pool = [pm for pl in game.players for pm in pl.battlefield
                    if pm.controller is not ctrl and _m(pm) and game.can_target(ctrl, pm)]
            if not pool:
                return
            pool.sort(key=lambda x: (x.card.cost.cmc if x.card.cost else 0), reverse=True)
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]

            def _do(pm):
                if pm not in pm.controller.battlefield:
                    return
                if _mode == "exile":
                    owner = pm.controller
                    owner.battlefield.remove(pm)
                    if not pm.is_token and game.commander_owner(pm.card) is None:
                        owner.exile.append(pm.card)
                    game.log(f"{ctrl.name} exilia {pm.name}")
                else:
                    game.destroy(pm, "ETB")
                    game.log(f"{ctrl.name} destruye {pm.name}")

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí un permanente" + (" (o ninguno)" if _opt else ""),
                                 cands, _do, allow_none=_opt)
        return eff

    # ETB robar control de una criatura rival (Sower of Temptation): el humano
    # elige; el bot toma la más grande. La devolución al dejar el campo la cablea
    # build_card_from_data (on_leave) cuando el texto dice "as long as you control".
    if (re.search(r"gain control of (?:up to \w+ )?target creature", t)
            and "until end of turn" not in t):
        def eff(game, ctrl, *_a):
            perm = _a[0] if _a and hasattr(_a[0], "card") else None
            pool = [pm for pm in game.legal_creature_targets(ctrl)
                    if pm.controller is not ctrl]
            if not pool:
                return
            pool.sort(key=lambda x: (x.power, x.toughness), reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness} · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(tgt, _perm=perm):
                if tgt not in tgt.controller.battlefield or tgt.controller is ctrl:
                    return
                old = tgt.controller
                old.battlefield.remove(tgt)
                tgt.controller = ctrl
                ctrl.battlefield.append(tgt)
                # cambiar de control no la endereza ni le da prisa: queda con mareo
                # de invocación bajo su nuevo controlador
                tgt.summoning_sick = True
                if _perm is not None:
                    _perm._stolen = (tgt, old)
                game.log(f"{ctrl.name} toma el control de {tgt.name}")

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura rival para controlar", cands, _do)
        return eff

    # fichas de recurso (Treasure/Clue/Food/Blood): visibles en el tablero.
    m = re.search(r"create (\w+) (tapped )?(treasure|clue|food|blood|gold|powerstone|map|lander|"
                  r"mutagen|junk|shard) tokens?", t)
    if m:
        n = _count_word(m.group(1)) or 1
        kind = m.group(3)
        _tapped = bool(m.group(2))
        # "create X Treasure tokens, where X is the number of …" (Dockside)
        xcnt = cnt if (m.group(1) == "x" and cnt is not None) else None

        def eff(game, ctrl, *_a, _n=min(n, 12), _k=kind, _xc=xcnt, _tp=_tapped):
            k = min(12, max(0, _xc(game, ctrl))) if _xc is not None else _n
            for _ in range(k):
                tk = cards.make_resource_token(game, ctrl, _k)
                if _tp and tk is not None:
                    tk.tapped = True
            game.log(f"{ctrl.name} crea {k} ficha(s) {_k.capitalize()}")
        return eff

    # ficha ÚNICA X/X (Shark Typhoon, etc.): "create an X/X <color> <sub> creature
    # token [with <kw>]" — P/T = el X elegido al lanzar (spell_x).
    mxx = re.search(r"create an? x/x ([\w' ]*?)(?:creature )?token", t)
    if mxx:
        _words = [w for w in (mxx.group(1) or "").split()
                  if w not in ("green", "white", "blue", "black", "red", "colorless",
                               "and", "or", "artifact", "enchantment", "legendary")]
        _sub = _words[-1].capitalize() if _words else "Token"
        _tail = re.split(r"[.;]", t[mxx.end():])[0]
        _kw = tuple(v for pat, v in _TOKEN_KEYWORDS if re.search(pat, _tail))

        def eff(game, ctrl, *_a, _s=_sub, _kw=_kw):
            x = min(40, int(getattr(game, "spell_x", 0) or 0))
            if x <= 0:
                return
            cards.make_token(game, ctrl, _s, x, x, kw=_kw, subtypes=(_s,))
            game.log(f"{ctrl.name} crea una ficha {_s} {x}/{x}")
        return eff

    m = re.search(r"create (\w+) .{0,40}?(\d+)/(\d+)\s*([\w' ]*?)(?:creature )?tokens?", t)
    if m:
        n = _count_word(m.group(1)) or 1
        pw, tf = int(m.group(2)), int(m.group(3))
        # subtipo(s) de la ficha: última palabra descriptiva (p. ej. "green Dinosaur")
        words = [w for w in (m.group(4) or "").split()
                 if w not in ("green", "white", "blue", "black", "red", "colorless",
                              "and", "or", "artifact", "enchantment", "legendary", "tapped")]
        sub = words[-1].capitalize() if words else "Token"
        # "with N +1/+1 counters on it" (contadores de entrada de la ficha)
        mc = re.search(r"with (\w+) \+1/\+1 counters?", t)
        cn = _count_word(mc.group(1)) if mc else 0
        # keywords de la ficha: sólo las de ESTA oración (tras "token ...") para no
        # arrastrar keywords de otras cláusulas del texto.
        _tail = re.split(r"[.;]", t[m.end():])[0]
        # "… with flying for each creature with defender you control": lo que sigue a
        # "for each" describe qué se cuenta, no las keywords de la ficha
        _tail = re.split(r"\bfor each\b|\bwhere x\b|\bequal to\b", _tail)[0]
        kw = tuple(v for pat, v in _TOKEN_KEYWORDS if re.search(pat, _tail))
        # cantidad VARIABLE: "X ... where X is the number of …" / "for each …"
        cnt_fn = None
        mvar = re.search(r"(?:for each|equal to the number of|where x is the number of) "
                         r"([\w' ]+)", t)
        if mvar and (m.group(1).lower() == "x" or "for each" in t):
            cnt_fn = (_count_fn("number of " + mvar.group(1)) or _count_fn(mvar.group(1))
                      or _each_count_fn(mvar.group(1)))
        # X del hechizo ("Create X ... tokens"): usa el X elegido al lanzar (spell_x).
        if cnt_fn is None and m.group(1).lower() == "x":
            cnt_fn = lambda game, ctrl: int(getattr(game, "spell_x", 0) or 0)  # noqa: E731

        def eff(game, ctrl, *_a, _n=min(n, 8), _p=pw, _t=tf, _s=sub, _c=cn or 0,
                _kw=kw, _cf=cnt_fn):
            reps = min(_cf(game, ctrl), 40) if _cf else _n
            for _ in range(max(0, reps)):
                cards.make_token(game, ctrl, _s, _p, _t, kw=_kw,
                                 subtypes=(_s,), counters=_c)
        return eff

    m = re.search(r"deals? (\w+) damage to each opponent", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            for o in game.opponents(ctrl):
                game.deal_damage(None, o, _n)
            game.log(f"{ctrl.name}: {_n} de daño a cada oponente" + game.src_tag())
        return eff

    # barrida simétrica: "each creature deals damage equal to its (power|toughness)
    # to itself" (Wave of Reckoning) o el orden inverso "...to itself equal to its
    # power" (ambas redacciones existen). Cada criatura se autodaña ese monto.
    m = (re.search(r"each creature deals damage equal to its (power|toughness) to itself", t)
         or re.search(r"each creature deals damage to itself equal to its (power|toughness)", t))
    if m:
        which = m.group(1)

        def eff(game, ctrl, *_a, _w=which):
            for pl in game.players:
                for pm in list(pl.creatures()):
                    amt = pm.toughness if _w == "toughness" else pm.power
                    if amt > 0:
                        game.deal_damage(pm, pm, amt)
            game.sba()
            game.log(f"{ctrl.name}: cada criatura se hace daño igual a su {_w}")
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
                     + (" y él gana vida" if _gain else "") + game.src_tag())
        return eff

    # drenaje dirigido fijo: "target player/opponent loses N life" -> el humano
    # elige el rival; el bot va al de menos vida.
    m = re.search(r"target (?:player|opponent) loses (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        gain = bool(re.search(r"you gain (that much|\w+) life", t))
        def eff(game, ctrl, *_a, _n=n, _gain=gain):
            def _do(o, _n2=_n, _g=_gain):
                o.life -= _n2
                if _g:
                    game.gain_life(ctrl, _n2)
                game.log(f"{ctrl.name}: {o.name} pierde {_n2} de vida"
                         + (" y él gana vida" if _g else "") + game.src_tag())
            _pick_opponent(game, ctrl, _do)
        return eff

    # pérdida de vida propia: "you lose N life" (drawback; Vampire Lacerator…),
    # con condición opcional "unless an opponent has X or less life".
    m = re.search(r"you lose (\w+) life", t)
    if m and (n := _count_word(m.group(1))):
        munless = re.search(r"unless an opponent has (\d+) or less life", t)
        thresh = int(munless.group(1)) if munless else None

        def eff(game, ctrl, *_a, _n=n, _th=thresh):
            if _th is not None and any(o.life <= _th for o in game.opponents(ctrl)):
                return                              # condición cumplida: no pierde vida
            ctrl.life -= _n
            game.log(f"{ctrl.name} pierde {_n} de vida" + game.src_tag())
        return eff

    # edict masivo: "each player sacrifices a creature [or planeswalker]"
    if re.search(r"each player sacrifices? a creature(?: or planeswalker)?", t):
        incl_pw = "planeswalker" in t

        def eff(game, ctrl, *_a, _pw=incl_pw):
            for pl in game.players:
                pool = [pm for pm in pl.battlefield
                        if pm.is_creature() or (_pw and "planeswalker" in pm.card.types)]
                if pool:
                    why = "" if pl is ctrl else f" (lo fuerza {ctrl.name})"
                    _human_or_auto_sacrifice(
                        game, pl, f"Sacrificio forzado{why}: elegí qué sacrificar",
                        pool=pool)
        return eff

    # cada jugador descarta N carta(s)
    m = re.search(r"each player discards? (\w+) cards?", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            for pl in game.players:
                _human_or_auto_discard(game, pl, _n)
        return eff

    # self-mill: "put the top N cards of your library into your graveyard"
    m = re.search(r"put the top (\w+) cards? of your library into your graveyard", t)
    if m and (n := _count_word(m.group(1))):
        def eff(game, ctrl, *_a, _n=n):
            cards.mill(game, ctrl, _n)
        return eff

    # odio de cementerio: "exile all creature cards from (all) graveyards"
    if re.search(r"exile all creature cards? from (?:all )?graveyards?", t):
        def eff(game, ctrl, *_a):
            for pl in game.players:
                keep = [c for c in pl.graveyard if not c.is_creature()]
                gone = len(pl.graveyard) - len(keep)
                if gone:
                    pl.exile.extend(c for c in pl.graveyard if c.is_creature())
                    pl.graveyard[:] = keep
            game.log(f"{ctrl.name}: exilia las criaturas de los cementerios")
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
            if not amt:
                return
            # el 3er arg es lista de objetivos (camino de CAST) o el permanente
            # (camino ETB). Sólo honramos objetivos ya elegidos si vino una lista.
            pre = next((a for a in _a if isinstance(a, (list, tuple))), None)
            tgts = [t for t in (pre or []) if hasattr(t, "life")]
            if tgts:
                for tg in tgts:
                    game.deal_damage(None, tg, amt)
                    game.log(f"{ctrl.name}: {amt} de daño a {tg.name}")
                return
            _pick_opponent(game, ctrl, lambda o, _amt=amt: (   # si no, el humano elige
                game.deal_damage(None, o, _amt),
                game.log(f"{ctrl.name}: {_amt} de daño a {o.name}")))
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

    # ganar vida igual al poder de una criatura tuya objetivo (Wall of Reverence):
    # el humano elige; el bot toma su criatura más grande. (Va ANTES del "gain N
    # life" genérico para no capturar el número equivocado.)
    if re.search(r"gain life equal to (?:the power of|its power)", t) and "target creature" in t:
        def eff(game, ctrl, *_a):
            pool = [pm for pm in ctrl.creatures()]
            if not pool:
                return
            pool.sort(key=lambda x: x.power, reverse=True)
            cands = [(f"{pm.name} {pm.power}/{pm.toughness}", pm) for pm in pool]

            def _do(tgt):
                if tgt is not None:
                    game.gain_life(ctrl, max(0, tgt.power))
                    game.log(f"{ctrl.name} gana {max(0, tgt.power)} de vida (poder de {tgt.name})")
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí una criatura (ganás vida = su poder)",
                                 cands, _do, allow_none=True)
        return eff

    m = re.search(r"(?:you )?gain (\w+) life", t)
    if m and (m.group(1).lower() == "x" or _count_word(m.group(1))):
        # compuesto frecuente: "gain N life and draw M card(s)"
        _gx = m.group(1).lower() == "x"
        n = _count_word(m.group(1)) or 0
        md = re.search(r"draw (\w+) cards?", t)
        _dx = bool(md) and md.group(1).lower() == "x"
        dn = _count_word(md.group(1)) if md else 0

        def eff(game, ctrl, *_a, _n=n, _d=dn, _gx=_gx, _dx=_dx):
            g_amt = min(99, int(getattr(game, "spell_x", 0) or 0)) if _gx else _n
            if g_amt:
                game.gain_life(ctrl, g_amt)
            d_amt = min(40, int(getattr(game, "spell_x", 0) or 0)) if _dx else _d
            if d_amt:
                ctrl.draw(d_amt, game)
                game.log(f"{ctrl.name} roba {d_amt} carta(s)")
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
                if o.creatures():
                    # el DUEÑO elige qué sacrificar (modal si es humano, si no la más débil)
                    _human_or_auto_sacrifice(
                        game, o,
                        f"Sacrificio forzado (lo fuerza {ctrl.name}): "
                        f"elegí una criatura")
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
                # el que descarta elige sus cartas (modal si es humano)
                _human_or_auto_discard(game, o, _n)
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
                game.log(f"{tgt.name} pierde {_n} de vida" + game.src_tag())
        return eff

    # edict: "each opponent sacrifices a creature" (variante de "target player")
    if re.search(r"each opponent sacrifices? a creature", t):
        def eff(game, ctrl, *_a):
            for o in game.opponents(ctrl):
                if o.creatures():
                    _human_or_auto_sacrifice(
                        game, o,
                        f"Sacrificio forzado (lo fuerza {ctrl.name}): "
                        f"elegí una criatura")
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
                    if game.commander_owner(pm.card) is not None:
                        game.commander_owner(pm.card).command.append(pm.card)
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
        top = bool(re.search(r"on top(?: of your library)?", t)) and not to_bf
        return _search_library_effect(pred, to_battlefield=to_bf,
                                      allow_none=may, label=lbl, to_top=top)

    m = re.search(r"\b(?:(target (?:player|opponent)|each opponent|each player) )?"
                  r"mill(?:s)? (\w+)", t)
    if m and (n := _count_word(m.group(2))):
        who = (m.group(1) or "").lower()

        # "target player/opponent mills N" va a un RIVAL (antes siempre al propio
        # controlador: Glimpse the Unthinkable se molía 10 a sí mismo)
        def eff(game, ctrl, *_a, _n=n, _w=who):
            if _w == "each opponent":
                for o in game.opponents(ctrl):
                    cards.mill(game, o, _n)
            elif _w == "each player":
                for pl in [ctrl] + game.opponents(ctrl):
                    cards.mill(game, pl, _n)
            elif _w.startswith("target"):
                _pick_opponent(game, ctrl, lambda o, _k=_n: cards.mill(game, o, _k))
            else:
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
                game.emit("cards_exiled", player=ctrl, count=len(moved))  # Laelia, etc.
        return eff

    # reanimar al campo desde el cementerio (el TUYO, o CUALQUIERA con "from a
    # graveyard ... under your control"). El humano elige; el bot toma la mejor.
    if re.search(r"(?:return|put) .{0,70}?from (?:your|a) graveyard (?:on)?to the "
                 r"battlefield", t):
        lim = int(mvm.group(1)) if (mvm := re.search(r"mana value (\d+) or less", t)) else None
        cre = "creature card" in t
        nonland = "nonland permanent" in t or "noncreature, nonland" in t
        any_gy = "from a graveyard" in t     # reanimación de cualquier cementerio

        def eff(game, ctrl, *_a, _lim=lim, _cre=cre, _nl=nonland, _any=any_gy):
            def ok(c):
                if not _is_permanent_card(c):        # instantáneos/conjuros NO al campo
                    return False
                if _cre and "creature" not in c.types:
                    return False
                if _nl and c.is_land():               # "nonland permanent": sin tierras
                    return False
                if _lim is not None and c.cost and c.cost.cmc > _lim:
                    return False
                return True
            zones = ([(pl, pl.graveyard) for pl in game.players] if _any
                     else [(ctrl, ctrl.graveyard)])
            eligibles = [(owner, c) for owner, gy in zones for c in gy if ok(c)]
            if not eligibles:
                game.log(f"{ctrl.name}: sin carta válida en el cementerio para revivir")
                return
            # Mostrar el cementerio relevante: TODA carta elegible (aunque sea tierra,
            # si el efecto las permite) + las no-tierra no elegibles en gris, para que
            # el humano VEA el cementerio y entienda por qué puede o no elegir cada una.
            # (Incluir siempre las elegibles evita un modal "todo en gris" que congela.)
            shown = [(owner, c) for owner, gy in zones for c in gy
                     if ok(c) or not c.is_land()]
            shown.sort(key=lambda oc: (0 if ok(oc[1]) else 1,
                                       -(oc[1].cost.cmc if oc[1].cost else 0)))
            picks = [c for _o, c in shown]
            owner_of = {id(c): o for o, c in shown}

            def _do(pick):
                owner = owner_of.get(id(pick))
                if owner and pick in owner.graveyard and ok(pick):
                    owner.graveyard.remove(pick)
                    game.move_to_battlefield(pick, ctrl)   # bajo control del que reanima
                    game.log(f"{ctrl.name} revive {pick.name} del cementerio")
            _hint = " (las grises no son elegibles)" if any(not ok(c) for c in picks) else ""
            _pick_card_from_zone(game, ctrl, picks, _do,
                                 "Elegí una carta del cementerio para revivir" + _hint,
                                 ok_fn=ok)
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

    # acciones-palabra clave sin objetivo (investigate/bolster/amass/incubate):
    # se delega en _fragment_effect por oración, encadenando las reconocidas.
    if re.search(r"\b(investigate|bolster|amass|incubate)\b", t):
        effs = []
        for frag in re.split(r"[.;]", oracle or ""):
            if re.search(r"\b(investigate|bolster|amass|incubate)\b", frag, re.I):
                _amt_depth += 1
                try:
                    keff, _spec, _cnt = _fragment_effect(frag)
                finally:
                    _amt_depth -= 1
                if keff is not None and _spec is None:
                    effs.append(keff)
        if effs:
            def eff(game, ctrl, *_a, _e=effs):
                for f in _e:
                    f(game, ctrl, [])
            return eff

    # fallback: biblioteca de habilidades (registro declarativo, fácil de extender)
    import abilities
    return abilities.effect_from_text(t, oracle)


def _vanilla_from_data(data: dict) -> Card:
    """Carta 'vainilla' con los datos base (nombre, tipos, coste, P/T, keywords) y
    SIN parsear efectos. Se usa como RED DE SEGURIDAD si el parseo completo de una
    carta falla o recursa demasiado, para que cargar el mazo no reviente por una sola
    carta rara."""
    data = _prefer_front_face(data)
    types, supertypes, subtypes = parse_type_line(data.get("type_line", ""))
    color_id = {_COLOR_MAP[c] for c in data.get("color_identity", []) if c in _COLOR_MAP}
    kws = {k.lower().replace(" ", "_") for k in data.get("keywords", [])} & KEYWORDS
    cost = None
    # sin coste de maná impreso (Ancestral Vision, Living End, Lotus Bloom): NO se
    # puede lanzar normalmente (solo suspend / "sin pagar su coste"). Antes el
    # coste vacío se leía como {0} y se lanzaba gratis.
    _no_mc = (("mana_cost" in data or "cmc" in data)
              and not (data.get("mana_cost") or "").strip()
              and not data.get("card_faces"))
    if "land" not in types and not _no_mc:
        cost = parse_cost(mana_cost_to_str(data.get("mana_cost", "")))
    if "land" in types:                       # una tierra vainilla debe producir maná
        prod = [_COLOR_MAP[c] for c in (data.get("produced_mana") or [])
                if c in _COLOR_MAP] or (list(color_id) or [C])
        return Card(name=data.get("name", "?"), types=types or {"land"},
                    supertypes=supertypes, subtypes=subtypes, color_id=color_id,
                    produces=(lambda perm, pl, _o={c: 1 for c in prod}: dict(_o)))
    _v = Card(name=data.get("name", "?"), types=types or {"creature"}, cost=cost,
              power=_int_or_zero(data.get("power")),
              toughness=_toughness_of(data),
              keywords=kws, supertypes=supertypes, subtypes=subtypes,
              color_id=color_id,
              x_spell=("{X}" in (data.get("mana_cost", "") or "").upper()))
    _v.x_count = max(1, (data.get("mana_cost", "") or "").upper().count("{X}"))
    return _v


_build_depth = 0
_BUILD_MAX = 8          # anidación legítima máxima (p. ej. cara trasera de un DFC = 1)


def build_card_from_data(data: dict) -> Card:
    """Construye una Card desde un dict tipo Scryfall (name, mana_cost,
    type_line, power, toughness, keywords, color_identity).

    Protegido contra recursión: si el parseo de efectos se anida demasiado o falla,
    cae a una carta vainilla (datos reales, sin efecto) en vez de reventar la carga
    del mazo con "maximum recursion depth exceeded"."""
    global _build_depth
    if _build_depth > _BUILD_MAX:
        return _vanilla_from_data(data)
    _build_depth += 1
    try:
        _n_before = len(_CUR_NAMES)
        try:
            c = _build_card_from_data_impl(data)
        finally:
            del _CUR_NAMES[_n_before:]
        # habilidades con coste "discard this card" (Channel…): se activan DESDE LA
        # MANO, no desde el campo (antes descartaban otra carta al azar en el campo)
        abs_ = tuple(c.activated_abilities or ())
        if any(ab.get("from_hand") for ab in abs_):
            c.hand_abilities = tuple(ab for ab in abs_ if ab.get("from_hand"))
            c.activated_abilities = tuple(ab for ab in abs_ if not ab.get("from_hand"))
        return c
    except RecursionError:
        return _vanilla_from_data(data)
    finally:
        _build_depth -= 1


# ── Consulta de reglas: habilidades sin implementación propia ───────────────
# Si el motor no entiende una habilidad clave (Riot, Prowess, Exalted…), lee su
# TEXTO RECORDATORIO como una habilidad más: el de la propia carta o, si la carta
# no lo imprime, el más común en la base completa (data/keyword_reminders.json).

_KW_REMINDERS = None
_KW_NATIVE = {}


def keyword_reminders() -> dict:
    global _KW_REMINDERS
    if _KW_REMINDERS is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                   "keyword_reminders.json"), encoding="utf-8") as f:
                _KW_REMINDERS = json.load(f)
        except (OSError, ValueError):
            _KW_REMINDERS = {}
    return _KW_REMINDERS


def _card_sig(card):
    out = {}
    for k, v in vars(card).items():
        if k == "name":
            continue
        if callable(v):
            out[k] = "fn"
        elif isinstance(v, dict):
            out[k] = tuple(sorted(map(str, v.keys())))
        elif isinstance(v, (set, frozenset, list, tuple)):
            # sin direcciones de memoria ("<function … at 0x…>"): la firma debe ser estable
            out[k] = tuple(sorted(re.sub(r" at 0x[0-9a-f]+", "", str(x)) for x in v))
        else:
            out[k] = repr(v)
    return out


# habilidades que el motor arma por el TIPO de la carta (Equipo, Aura, Vehículo):
# la sonda de una línea sola no las ve porque el tipo ya las trae
_KW_BY_TYPE = {"equip", "enchant", "crew", "living weapon"}


def _kw_native(part, kw, type_line="Creature — Human"):
    """¿El motor ya entiende esta habilidad clave tal como está escrita
    ('Equip {2}', 'Annihilator 2', 'Prowess') sin su recordatorio?"""
    if kw.lower() in _KW_BY_TYPE:
        return True
    tl = (type_line or "Creature").split("//")[0].strip()
    key = (re.sub(r"\d+", "N", part.lower()), kw, tl)
    if key not in _KW_NATIVE:
        _KW_NATIVE[key] = True  # evita recursión mientras se prueba
        base = {"name": "Kw Probe", "type_line": tl, "mana_cost": "{2}",
                "power": "2", "toughness": "2", "_no_reminder": True}
        try:
            a = _card_sig(build_card_from_data(dict(base, oracle_text="", keywords=[])))
            b = _card_sig(build_card_from_data(dict(base, oracle_text=part, keywords=[kw])))
            _KW_NATIVE[key] = a != b
        except Exception:  # noqa: BLE001
            _KW_NATIVE[key] = True
    return _KW_NATIVE[key]


_KW_PARAM = re.compile(r"^(.+?)(?:\s+(?:\d+|x|\{.*)|—.*)?$", re.I)


def _expand_reminders(text, keywords, name, type_line="Creature"):
    """Agrega como líneas propias los recordatorios de habilidades clave que el
    motor no implementa. No toca el resto del texto."""
    if not text or not keywords:
        return text
    kwmap = {k.lower(): k for k in keywords}
    extra = []
    for ln in text.split("\n"):
        head, _, rest = ln.partition("(")
        parts = [x.strip() for x in re.split(r",|;", head) if x.strip()]
        if not parts:
            continue
        found = []
        for part in parts:
            m = _KW_PARAM.match(part)
            kw = kwmap.get((m.group(1) if m else part).strip().lower())
            if not kw:
                found = []
                break
            found.append((part, kw))
        own = rest.rsplit(")", 1)[0].strip() if rest else ""
        for part, kw in found:
            if _kw_native(part, kw, type_line):
                continue
            rem = own if len(found) == 1 and own else ""
            if not rem:
                if re.search(r"\d|\{|—", part):
                    continue  # parámetro propio sin recordatorio: no adivinar
                rem = keyword_reminders().get(kw, "")
            if rem:
                extra.append(rem.replace("~", name))
    return text + ("\n" + "\n".join(extra) if extra else "")


# Palabras de habilidad (Raid, Morbid, Landfall…): son solo un rótulo; el efecto
# está escrito después del "—". Se quitan para que el parser lea la habilidad.
_ABILITY_WORD_RE = re.compile(r"^(?:Will of the Planeswalkers|Will of the council|Fathomless descent|Council's dilemma|Tempting offer|Secret council|Constellation|Spell mastery|Hero's Reward|Fateful hour|Pack tactics|Join forces|Undergrowth|Celebration|Formidable|Lieutenant|Metalcraft|Battalion|Bloodrush|Ferocious|Threshold|Magecraft|Corrupted|Disappear|Covercast|Converge|Delirium|Grandeur|Hellbent|Inspired|Landfall|Radiance|Addendum|Eminence|Landship|Underdog|Alliance|Survival|Repartee|Infusion|Channel|Imprint|Kinship|Adamant|Kinfall|Descend|Paradox|Valiant|Chroma|Cohort|Domain|Heroic|Morbid|Parley|Strive|Enrage|Legacy|Revolt|Flurry|Eerie|Rally|Sweep|Coven|Renew|Vivid|Raid|Void|Opus)\s*[—–]\s*", re.M)


# palabras de habilidad / flavor words genéricas ("Whirlwind — When…", "Jump — During…"):
# no tienen significado de reglas. Se excluyen las etiquetas que SÍ lo tienen.
_FLAVOR_WORD_RE = re.compile(
    r"^(?!(?:[IVX]+(?:, [IVX]+)*|Exhaust|Power-up|Max speed|Visit|Boast|To solve|Solved|Forecast|Companion|"
    r"Prototype|Choose|Spree|Escalate|Tiered|Kicker|Equip|Level|Chapter|Station|Crew|Saddle|Ward)\b)"
    r"[A-Z][\w'’!?.,…-]*(?: [\w'’!?.,…-]+){0,7} — (?=(?:When|Whenever|At |\{|During|As long as|Creatures|"
    r"This|Target|Sacrifice|Exile|Pay|Tap|Remove|Discard|Return|Each|You|Spells|Other|Draw|Destroy|Up to|"
    r"[A-Z][a-z]+ (?:gets|has|deals|can't)))", re.M)


def _strip_ability_words(text):
    return _FLAVOR_WORD_RE.sub("", _ABILITY_WORD_RE.sub("", text or ""))


def _rewrite_mechanics(text):
    """Reescrituras de texto a formas que el parser ya entiende:
    - 'Max speed — <habilidad>': solo con velocidad 4.
    - 'waterbend {N}' -> 'pay {N}' (se puede pagar girando; aprox: maná).
    - 'airbend target X' -> 'return target X to its owner's hand' (aprox)."""
    out = []
    for ln in (text or "").split("\n"):
        m = re.match(r"(?i)max speed\s*[—–-]\s*(.+)$", ln.strip())
        if m:
            body = m.group(1).strip()
            mk = re.fullmatch(r"([A-Za-z ,]+)\.?", body)
            if re.match(r"(?i)(when|whenever|at the beginning)", body):
                ln = re.sub(r",\s*", ", if your speed is 4, ", body, count=1)
            elif ":" in body.split(".")[0]:
                ln = body.rstrip(".") + ". Activate only if your speed is 4."
            elif mk and all(w.strip().lower().replace(" ", "_") in KEYWORDS
                            for w in re.split(r",\s*(?:and\s+)?|\s+and\s+", mk.group(1))
                            if w.strip()):
                ln = f"This creature has {mk.group(1).lower()} as long as your speed is 4."
            else:
                ln = body
        st = ln.strip()
        # batch 4B: líneas que se cablean aparte (no como texto suelto)
        if re.match(r"(?i)(forecast|to solve|impending \d+|more than meets the eye|recover)"
                    r"\b\s*[—–-]?", st) or re.match(
                    r"(?i)when the creature (?:this card|it|~) haunts dies", st):
            continue
        # haunt: "When this creature enters or the creature it haunts dies, X"
        ln = re.sub(r"(?i)^(when (?:this creature|~|[^,]+?) enters) or the creature it haunts "
                    r"dies,", r"\1,", st)
        # caso resuelto: "Solved — <habilidad>" con la condición explícita
        msv = re.match(r"(?i)solved\s*[—–-]\s*(.+)$", ln)
        if msv:
            body = msv.group(1).strip()
            if re.match(r"(?i)(when|whenever|at the beginning)", body):
                ln = re.sub(r",\s*", ", if this case is solved, ", body, count=1)
            elif ":" in body.split(".")[0]:
                ln = body.rstrip(".") + ". Activate only if this case is solved."
            else:
                ln = "As long as this case is solved, " + body[0].lower() + body[1:]
        # kinship: "...look at the top card... If it shares a creature type with
        # this creature, you may reveal it. If you do, X" -> disparo con condición
        mkin = re.match(r"(?i)at the beginning of your upkeep, you may look at the top card of "
                        r"your library\. if it shares a creature type with ([^,]+), you may "
                        r"reveal it\. if you do, (.+)$", ln)
        if mkin:
            ln = (f"At the beginning of your upkeep, if the top card of your library shares "
                  f"a creature type with {mkin.group(1)}, {mkin.group(2)}")
        # eminence: la condición "is in the command zone or on the battlefield" es
        # siempre cierta donde el motor la evalúa (campo o zona de mando)
        ln = re.sub(r"(?i),? if [^,]+? is in the command zone or on the battlefield,", ",", ln)
        ln = re.sub(r"(?i)^as long as [^,]+? is in the command zone or on the battlefield, ",
                    "", ln)
        # batch 5: formas equivalentes que el parser ya entiende
        ln = re.sub(r"(?i)^during your turn, (this creature|~|[^,]+?) (has|gets) ([^.]+)\.$",
                    lambda m: f"{m.group(1)[0].upper() + m.group(1)[1:]} {m.group(2)} "
                              f"{m.group(3)} as long as it's your turn.", ln)
        ln = re.sub(r"(?i)\bto target attacking or blocking creature\b", "to target creature", ln)
        ln = re.sub(r"(?i)(?<!put )\btarget attacking creature\b", "target creature", ln)
        ln = re.sub(r"(?i)^target player gains (\w+) life\.$", r"You gain \1 life.", ln)
        ln = re.sub(r"(?i)^as long as enchanted permanent is a creature, it gets ([+-]\d+/[+-]\d+)\.$",
                    r"Enchanted creature gets \1.", ln)
        ln = re.sub(r"(?i)^as long as (?![^,]*\bis in your graveyard)([^,]+), ((?:other )?(?:creatures|permanents|creature tokens|artifacts|[a-z]+s)"
                    r"(?: you control| your opponents control)?) (get|have) ([^.\"]+)\.$",
                    lambda m: f"{m.group(2)[0].upper() + m.group(2)[1:]} {m.group(3)} {m.group(4)} as long as "
                              f"{m.group(1)}.", ln)
        ln = re.sub(r"(?i)^(?:threshold|metalcraft|hellbent|delirium|fateful hour|infusion) — (.+ as long as .+)$",
                    r"\1", ln)
        ln = re.sub(r"(?i)^during turns other than yours, (this creature|~|[^,]+?) (gets|has) ([^.]+)\.$",
                    lambda m: f"{m.group(1)[0].upper() + m.group(1)[1:]} {m.group(2)} {m.group(3)} as long as "
                              f"it's not your turn.", ln)
        ln = re.sub(r"(?i)^outlast ((?:\{[^}]+\})+)$",
                    r"\1, {T}: Put a +1/+1 counter on this creature. Activate only as a sorcery.", ln)
        # convert (Transformers) = transform
        ln = re.sub(r"(?i)\bconvert(ed|s)?\b", lambda m: "transform" + (m.group(1) or ""), ln)
        # "Waterbend {X}: …" como coste de activada -> "{X}: …"
        ln = re.sub(r"(?i)^waterbend ((?:\{[^}]+\})+)\s*:", r"\1:", ln.strip())
        ln = re.sub(r"(?i)\bwaterbend (\{[^}]+\}(?:\{[^}]+\})*)", r"pay \1", ln)
        ln = re.sub(r"(?i)\bairbend (up to (?:one|two) )?target ([a-z ]+?)(\.|,| and)",
                    r"return \1target \2 to its owner's hand\3", ln)
        out.append(ln)
    return "\n".join(out)


def _build_card_from_data_impl(data: dict) -> Card:
    data = _prefer_front_face(data)
    if not data.get("_no_reminder"):
        data = dict(data)
        data["oracle_text"] = _expand_reminders(data.get("oracle_text", ""),
                                                data.get("keywords") or [],
                                                data.get("name", "?"),
                                                data.get("type_line") or "Creature")
    # sin texto recordatorio: el "(It's an artifact with '{T}, Sacrifice…: Add one
    # mana…')" de Treasure/Food/etc. se parseaba como efecto propio de la carta
    data = dict(data)
    # station: "It's an artifact creature at N+" vive en el recordatorio
    _mst = re.search(r"artifact creature at (\d+)\+", data.get("oracle_text", "") or "", re.I)
    _station_at = int(_mst.group(1)) if _mst else 0
    _pre4 = _strip_ability_words(_strip_reminder(data.get("oracle_text", "")))
    data["oracle_text"] = _rewrite_mechanics(_pre4)
    if str(data.get("power") or "").isdigit() and re.search(r"(?im)^scavenge ", data["oracle_text"] or ""):
        data["oracle_text"] = re.sub(
            r"(?im)^scavenge ((?:\{[^}]+\})+)\s*$",
            lambda m, _pw=int(data["power"]): (f"{m.group(1)}, Exile this card from your graveyard: Put {_pw} +1/+1 "
                                              f"counters on target creature. Activate only as a sorcery."),
            data["oracle_text"])
    # nombres propios de la carta en construcción: _effect_any los lee como "~"
    _CUR_NAMES.append(_self_names(data.get("name") or ""))
    # hechizo "<efecto>. If <condición>, <bonus>." (addendum, raid, morbid…): el
    # bonus se separa y se aplica solo si se cumple al resolver. Antes el parser
    # genérico lo aplicaba SIEMPRE (o tomaba solo una de las dos partes).
    _cond_bonus = None
    if re.search(r"\b(?:instant|sorcery)\b", (data.get("type_line") or "").lower()) \
            and not data.get("card_faces"):
        _ot = data.get("oracle_text", "") or ""
        mcb = re.search(r"(?:(?<=\.)\s+|\n)If ([^,.]+), ([^.]+\.)\s*$", _ot)
        if mcb and _ot[:mcb.start()].strip() and not re.search(
                r"\binstead\b|kicked|bargained|gift|paid|evidence|foretold|spent|was cast|"
                r"you do\b|you don't|it's|that|those|they|its\b", mcb.group(0), re.I):
            _cg = _cond_gc(mcb.group(1))
            if _cg is not None:
                _be = _effect_any(mcb.group(2))
                if _be is not None:
                    _cond_bonus = (_cg, _be)
                    data["oracle_text"] = _ot[:mcb.start()].rstrip()
        elif mcb and _ot[:mcb.start()].strip() and _cond_gc(mcb.group(1)) is not None \
                and re.search(r"\b(?:those|they|them)\b", mcb.group(2), re.I) \
                and not re.search(r"\binstead\b", mcb.group(0), re.I):
            # bonus sobre lo del efecto base (addendum de Unbreakable Formation): no
            # modelado -> se descarta en vez de aplicarlo siempre
            data["oracle_text"] = _ot[:mcb.start()].rstrip()
    # cleave: el texto normal sin corchetes; el de cleave sin lo que va entre ellos
    _cleave_txt = None
    if "[" in (data.get("oracle_text") or "") and "cleave" in {
            k.lower() for k in (data.get("keywords") or [])}:
        _cleave_txt = re.sub(r"\s*\[[^\]]*\]", "", data["oracle_text"])
        data["oracle_text"] = data["oracle_text"].replace("[", "").replace("]", "")
    # station: líneas "N+ | <habilidad>" se cablean aparte (no como texto suelto)
    _station_lines = re.findall(r"(?m)^(\d+)\+\s*\|\s*(.+)$", data.get("oracle_text") or "")
    if _station_lines:
        data["oracle_text"] = re.sub(r"(?m)^\d+\+\s*\|.*$\n?", "", data["oracle_text"])
    if data.get("card_faces"):
        data["card_faces"] = [dict(f, oracle_text=_strip_ability_words(
            _strip_reminder(f.get("oracle_text", "")))) for f in data["card_faces"]]
    name = data.get("name", "?")
    # disparo de entrada PROPIO (el único texto que puede cablearse como ETB genérico)
    _etb_body, _etb_or_attacks = _self_etb_body(data.get("oracle_text", ""), name)
    types, supertypes, subtypes = parse_type_line(data.get("type_line", ""))
    color_id = {_COLOR_MAP[c] for c in data.get("color_identity", [])
                if c in _COLOR_MAP}
    kws = {k.lower().replace(" ", "_") for k in data.get("keywords", [])}
    kws &= KEYWORDS

    cost = None
    # sin coste de maná impreso (Ancestral Vision, Living End, Lotus Bloom): NO se
    # puede lanzar normalmente (solo suspend / "sin pagar su coste"). Antes el
    # coste vacío se leía como {0} y se lanzaba gratis.
    _no_mc = (("mana_cost" in data or "cmc" in data)
              and not (data.get("mana_cost") or "").strip()
              and not data.get("card_faces"))
    if "land" not in types and not _no_mc:
        cost = parse_cost(mana_cost_to_str(data.get("mana_cost", "")))

    card = Card(
        name=name,
        types=types or {"creature"},
        cost=cost,
        power=_int_or_zero(data.get("power")),
        toughness=_toughness_of(data),
        keywords=kws,
        supertypes=supertypes,
        subtypes=subtypes,
        color_id=color_id,
        x_spell=("{X}" in (data.get("mana_cost", "") or "").upper()),
    )
    # cuántos {X} tiene el coste (White Sun's Twilight = {X}{X}{W} -> 2): cada X
    # cuesta esa cantidad de maná. Lo usa el motor para cobrar X*x_count.
    card.x_count = max(1, (data.get("mana_cost", "") or "").upper().count("{X}"))

    # tags: de creatura + derivados (aprox) del texto de la carta, para que la
    # capa de efectos genericos funcione tambien con cartas de Scryfall
    # (sin las habilidades activadas: "{1},{T}: draw" no es un efecto al entrar)
    card.tags = _derive_tags(_non_activated_text(data.get("oracle_text", "")), card.types)
    # reducciones de coste dinámicas (convoke / delve / affinity for artifacts)
    _ktext = (" ".join(data.get("keywords", []) or []) + " "
              + (data.get("oracle_text", "") or "")).lower()
    if "convoke" in _ktext:
        card.tags = card.tags | {"convoke"}
    if "delve" in _ktext:
        card.tags = card.tags | {"delve"}
    if "affinity for artifacts" in _ktext:
        card.tags = card.tags | {"affinity_art"}
    else:
        _maf = re.search(r"affinity for ([a-z]+?)s?\b", _ktext)
        if _maf:
            _ak = _maf.group(1).lower()
            _ak = {"forest": "forest", "equipment": "equipment"}.get(_ak, _ak)

            def _aff(g, p, _k=_ak):
                if _k in ("creature", "enchantment", "artifact", "land", "planeswalker"):
                    return sum(1 for pm in p.battlefield
                               if (pm.is_creature() if _k == "creature" else _k in pm.card.types))
                return sum(1 for pm in p.battlefield if pm.has_subtype(_k)
                           or pm.name.lower() == _k)
            card.cost_reduction_fn = _aff
    if "improvise" in _ktext:      # como convoke pero girando artefactos
        card.tags = card.tags | {"improvise"}

    # Ward: impuesto al ser objetivo de un rival (maná o pagar vida). Se guarda el
    # coste; el motor lo cobra al resolver (ver Game.ward_ok). "ward" ya está en las
    # keywords (whitelist) para que has('ward') sea True.
    _wl = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    mwl = re.search(r"ward[—-]\s*pay (\w+) life", _wl)
    mwm = re.search(r"ward\s*((?:\{[wubrgc0-9/x]+\})+)", _wl)
    if mwl and _count_word(mwl.group(1)):
        card.ward = {"life": _count_word(mwl.group(1))}
        card.keywords = set(card.keywords) | {"ward"}
    elif mwm:
        card.ward = {"mana": parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mwm.group(1)))))}
        card.keywords = set(card.keywords) | {"ward"}
    elif re.search(r"\bward\b", _wl):     # "Ward" sin coste explícito (raro)
        card.keywords = set(card.keywords) | {"ward"}
    # auras: anexar a un huésped y bufearlo (antes de la capa ETB genérica)
    _wire_aura(card, data.get("oracle_text", ""))
    _nt = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "")).lower()
    if ("enchantment" in types and "aura" not in {x.lower() for x in card.subtypes}
            and re.search(r"put target creature card from a graveyard onto the battlefield under your control "
                          r"and attach (?:this enchantment|~|[\w' ]+) to it", _nt)):
        card.subtypes = set(card.subtypes) | {"Aura"}      # Necromancy: se vuelve Aura al entrar
        _wire_reanimate_aura(card, _nt)
    _wire_equipment(card, data.get("oracle_text", ""))

    # Vehículos (crew N): habilidad que lo convierte en criatura este turno tapeando
    # criaturas cuyo poder total sea >= N.
    _mcrew = re.search(r"crew (\d+)", re.sub(r"\s+", " ",
                       (data.get("oracle_text", "") or "").lower()))
    if _mcrew and "vehicle" in {s.lower() for s in card.subtypes}:
        _cn = int(_mcrew.group(1))

        def _crew_eff(game, ctrl, perm, targets=None, _n=_cn):
            if getattr(perm, "temp_creature", False):
                return                          # ya está tripulado este turno
            avail = [pm for pm in ctrl.battlefield
                     if pm.is_creature() and not pm.tapped and pm is not perm]
            avail.sort(key=lambda c: c.power)   # tapea las de menor poder primero
            used, total = [], 0
            for c in avail:
                if total >= _n:
                    break
                used.append(c)
                total += c.power
            if total >= _n:
                for c in used:
                    c.tapped = True
                perm.temp_creature = True
                game.log(f"{ctrl.name} tripula {perm.name}")
            else:
                game.log(f"{ctrl.name}: no puede tripular {perm.name} (falta poder)")
        crew_ab = {"cost": parse_cost("0"), "tap": False, "sacrifice_self": False,
                   "sacrifice_other": None, "pay_life": 0, "discard": 0,
                   "label": f"Tripular {_cn}", "effect": _crew_eff, "target_spec": None,
                   "target_count": 1, "is_copy_ability": False, "sorcery_speed": True}
        card.activated_abilities = tuple(card.activated_abilities or ()) + (crew_ab,)

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
    # P/T variable (característica definida): "~'s power and toughness are each
    # equal to the number of …" / "~'s power is equal to … and its toughness is …"
    _ot_cda = re.sub(r"\s+", " ", _strip_reminder(data.get("oracle_text", "") or ""))
    _selfalt = "|".join(re.escape(x) for x in sorted(_self_names(name) | {name.lower()},
                                                       key=len, reverse=True) if x)
    _mc = re.search(r"(?:~|this creature|" + _selfalt + r")'s power and toughness are "
                    r"each equal to ([^.]+)\.", _ot_cda, re.I)
    if _mc and (_f := _count_fn(_mc.group(1))) is not None:
        card.cda_pt = (lambda g, c, _f=_f: (_f(g, c), _f(g, c)))
    else:
        _mc = re.search(r"(?:~|this creature|" + _selfalt + r")'s power is equal to "
                        r"([^.]+?)(?:,? and its toughness is equal to (?:that number )?"
                        r"(?:plus (\d+)|([^.]+)))?\.", _ot_cda, re.I)
        if _mc and (_f := _count_fn(_mc.group(1))) is not None:
            if _mc.group(2):
                card.cda_pt = (lambda g, c, _f=_f, _k=int(_mc.group(2)): (_f(g, c), _f(g, c) + _k))
            elif _mc.group(3) and (_ft := _count_fn(_mc.group(3))) is not None:
                card.cda_pt = (lambda g, c, _f=_f, _t=_ft: (_f(g, c), _t(g, c)))
            elif not _mc.group(3):
                card.cda_pt = (lambda g, c, _f=_f, _bt=card.toughness: (_f(g, c), _bt))
        else:
            _mc = re.search(r"(?:~|this creature|" + _selfalt + r")'s toughness is equal to (?:(\d+) plus )?"
                            r"([^.]+)\.", _ot_cda, re.I)
            if _mc and (_f := _count_fn(_mc.group(2))) is not None:
                card.cda_pt = (lambda g, c, _f=_f, _bp=card.power, _k=int(_mc.group(1) or 0): (_bp, _k + _f(g, c)))
    # "If you control a commander, you may cast this spell without paying its mana
    # cost" (Deadly Rollick, Fierce Guardianship, Flawless Maneuver…)
    if re.search(r"if you control a commander, you may cast this spell without paying "
                 r"its mana cost", (data.get("oracle_text", "") or ""), re.I):
        card.free_with_commander = True
    # "This spell can't be countered." / "Spells you control can't be countered."
    _otu = (data.get("oracle_text", "") or "").lower()
    if re.search(r"(?:this spell|~) can't be countered", _otu) or \
            re.search(re.escape(name.lower()) + r" can't be countered", _otu):
        card.uncounterable = True
    if re.search(r"(?:^|\n)creature spells can't be countered", _otu):
        card.global_uncounterable = "creature"
    if re.search(r"(?:spells you control|creature spells you control) can't be countered", _otu):
        card.grants_uncounterable = ("creature" if "creature spells you control" in _otu
                                     else "any")
    # "This creature can't block." (estática propia)
    if any(re.fullmatch(r"(?:~|this creature|" + re.escape(name.lower()) + r") can't block\.?",
                        l.strip().lower()) for l in _ability_lines(data.get("oracle_text", ""))):
        card.cant_block_static = True
    # "~ enters (the battlefield) tapped [unless …]": incondicional -> entra girado;
    # con condición -> el motor la evalúa al entrar (card.etb_untapped_if).
    _et = _enters_tapped_rule(data.get("oracle_text", "") or "")
    if _et is True:
        card.enters_tapped = True
    elif callable(_et):
        card.etb_untapped_if = _et

    # estado "cuando ~ no tenga contadores <X>, sacrifícala; crea <ficha>" (Dark
    # Depths -> Marit Lage). Se evalúa en sba() (consistente para cualquier fuente
    # que llegue a 0 contadores).
    _noc = re.search(
        r"has no (\w+) counters? on it,? sacrifice it\.?\s*(?:if you do,?\s*)?"
        r"create ([a-z][\w' ]+?), an? (?:legendary )?(\d+)/(\d+) "
        r"[\w ]*?(\w+) creature token(?: with ([\w, ]+))?",
        re.sub(r"\s+", " ", data.get("oracle_text", "") or ""), re.I)
    if _noc:
        _kws = [v for pat, v in _TOKEN_KEYWORDS if re.search(pat, _noc.group(6) or "")]
        card.sac_when_no_counter = (_noc.group(1).lower(), {
            "name": _noc.group(2).strip().title(),
            "power": int(_noc.group(3)), "toughness": int(_noc.group(4)),
            "subtypes": (_noc.group(5).capitalize(),), "keywords": _kws})

    # Produccion de mana: usar `produced_mana` de Scryfall (el mana REAL que
    # produce la carta), no la identidad de color — las tierras no basicas son
    # objetos incoloros y su identidad suele venir vacia. Aplica a tierras y a
    # artefactos de mana (signets, rocas); las tierras basicas caen al fallback.
    produced = [_COLOR_MAP[c] for c in (data.get("produced_mana") or [])
                if c in _COLOR_MAP]
    # CUÁNTO maná da la habilidad "{T}: Add …" (produced_mana trae solo colores):
    # Hedron Archive / Ancient Tomb {C}{C} = 2, Thran Dynamo 3, Gilded Lotus
    # "three mana of any one color" = 3. Antes todas daban 1.
    _amt, _amt_col = _mana_amount(data.get("oracle_text", ""))
    if "land" in types and produced:
        _free, _costed = [], False
        for _al in _ability_lines(_strip_reminder(data.get("oracle_text", "") or "")):
            _al = _al.strip().lower()
            _mf = re.match(r"\{t\}: add ([^.]+)", _al)
            if _mf:
                _free.append(_mf.group(1))
            elif re.match(r"[^:]*sacrifice[^:]*: add ", _al):
                _costed = True           # "{T}, Sacrifice this land: Add any color" (Outpost)
        if _free and _costed and not any("any color" in f or "any one color" in f or "any type" in f
                                          or "chosen color" in f or "of the chosen" in f
                                          or "that a land" in f for f in _free):
            _syms = {_COLOR_MAP[x.upper()] for f in _free for x in re.findall(r"\{([wubrgc])\}", f)}
            _fx = [c for c in produced if c in _syms]
            if _fx:
                produced = _fx
    _mtf = re.search(r"\{t\}: add ((?:\{[wubrgc]\})+)\. activate only if you control (\w+) or more lands",
                     (data.get("oracle_text", "") or "").lower())
    if "land" in types and _mtf and (_ntf := _count_word(_mtf.group(2))):
        _tf_opts = {}
        for _sym in re.findall(r"\{([wubrgc])\}", _mtf.group(1)):
            _tf_opts[_sym.upper()] = _tf_opts.get(_sym.upper(), 0) + 1
        card.produces = (lambda perm, pl, _o=_tf_opts, _n=_ntf: dict(_o) if pl is not None and sum(
            1 for x in pl.battlefield if x.card.is_land()) >= _n else {})
        card.enters_tapped = card.enters_tapped or bool(data.get("enters_tapped"))
        card._cond_mana = True                    # sin maná hasta tener N tierras
        produced = []
    elif "land" in types:
        colors = produced or [c for c in (W, U, B, R, G) if c in color_id] or [C]
        opts = ({_amt_col: _amt} if (_amt > 1 and _amt_col) else
                {c: _amt for c in colors})
        card.produces = (lambda perm, pl, _o=opts: dict(_o))
        # (antes se pisaba con False: las tierras que "enter tapped" entraban sin girar)
        card.enters_tapped = card.enters_tapped or bool(data.get("enters_tapped"))
    elif produced and "artifact" in types:
        # roca de mana importada (Fellwar Stone, signets, etc.)
        opts = ({_amt_col: _amt} if (_amt > 1 and _amt_col) else
                {c: _amt for c in produced})
        card.produces = (lambda perm, pl, _o=opts: dict(_o))
        card.tags = card.tags | {"ramp"}

    # fuente de maná "{T}: Add ..." que Scryfall no trajo como produced_mana
    # (cartas caseras/offline, p. ej. Patchwork Banner). El parser de activadas
    # descarta el maná de coste trivial esperando `produces`; si nadie lo setea,
    # la habilidad de maná quedaba muerta. Acá la reconstruimos como `produces`
    # (una opción = UN maná a elegir; ignoramos la restricción de "gastarlo solo
    # para X", una simplificación aceptable).
    if card.produces is None and "land" not in types:
        _mt = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "")).lower()
        mm = re.search(r"\{t\}:\s*add ([^.]+)", _mt)
        if mm:
            seg = mm.group(1)
            if "any color" in seg or "any one color" in seg:
                opts = {c: _amt for c in (W, U, B, R, G)}
            elif _amt > 1 and _amt_col:
                opts = {_amt_col: _amt}
            else:
                syms = re.findall(r"\{([wubrgc])\}", seg)
                opts = {_COLOR_MAP[s.upper()]: 1 for s in syms} if syms else None
            if opts:
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
        dp, dt = (int(mb.group(1)), int(mb.group(2))) if mb else (0, 0)
        _mdisc = re.search(r"(?:creature )?spells you cast of the chosen type cost \{(\d+)\} less to cast", _otc)
        if _mdisc:
            def _f_ct(c, pl, g, _cd=card):
                pm = next((x for x in pl.battlefield if x.card is _cd), None)
                ct = getattr(pm, "chosen_type", None) if pm is not None else None
                return bool(ct) and c.is_creature() and ct.lower() in {x.lower() for x in c.subtypes}
            _f_ct._wp = True
            card.spell_discount = (int(_mdisc.group(1)), _f_ct)
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

        if dp or dt:
            card.static_mod = _sm
            card.tags = card.tags | {"anthem"}

    # "As ~ enters, choose a color" + "creatures you control of the chosen color get +N/+N" (Caged Sun)
    if "choose a color" in _otc and (mcc := re.search(r"creatures you control of the chosen color get "
                                                       r"\+(\d+)/\+(\d+)", _otc)):
        def _etb_color(game, ctrl, perm, _prev=card.on_etb):
            cnt = {}
            for z in (ctrl.battlefield, ctrl.hand, ctrl.library, ctrl.command):
                for it in z:
                    cd = getattr(it, "card", it)
                    if cd.is_creature():
                        for pp in (getattr(cd.cost, "pips", None) or ()):
                            for x in str(pp).upper():
                                if x in "WUBRG":
                                    cnt[x] = cnt.get(x, 0) + 1
            perm.chosen_color = max(cnt, key=cnt.get) if cnt else "W"
            game.log(f"{ctrl.name} elige el color {perm.chosen_color}")
            if _prev:
                _prev(game, ctrl, perm)
        card.on_etb = _etb_color

        def _sm_cc(source, target, _a=int(mcc.group(1)), _b=int(mcc.group(2)), _p=card.static_mod):
            base = _p(source, target) if _p else (0, 0)
            cc = getattr(source, "chosen_color", None)
            if not cc or not target.is_creature() or target.controller is not source.controller:
                return base
            pips = {x for pp in (getattr(target.card.cost, "pips", None) or ()) for x in str(pp).upper()}
            return (base[0] + _a, base[1] + _b) if cc in pips else base
        card.static_mod = _sm_cc
        card.tags = card.tags | {"anthem"}

    # ── batch 21: elecciones genéricas al entrar ("as ~ enters, choose …") ──
    _mch = re.search(r"as (?:this \w+|~|" + "|".join(re.escape(n) for n in _self_names(name) if n) +
                     r") enters,? (?:you may )?(?:secretly )?choose (a color(?: other than \w+)?|a creature type|an opponent|"
                     r"a player|an opponent and a card name[^.]*|a (?:nonland |nonbasic land |)card name)", _otc)
    _done_ch = ("choose a creature type" in _otc and "of the chosen type" in _otc) or (
        "choose a color" in _otc and re.search(r"creatures you control of the chosen color get", _otc))
    if _mch and not _done_ch:
        _what = _mch.group(1)
        _hostile = bool(re.search(r"protection from the chosen color|can't be blocked by creatures of the chosen color|"
                                  r"sources? of the chosen color", _otc))

        def _etb_choice(game, ctrl, perm, _w=_what, _h=_hostile, _prev=card.on_etb):
            opps = [o for o in game.opponents(ctrl) if not o.lost]
            if "color" in _w:
                cnt = {}
                for pl in (opps if _h else [ctrl]):
                    for z in ([x.card for x in pl.battlefield], pl.hand if pl is ctrl else [], pl.library if pl is ctrl else []):
                        for cd in z:
                            for pp in (getattr(cd.cost, "pips", None) or ()):
                                for x in str(pp).upper():
                                    if x in "WUBRG":
                                        cnt[x] = cnt.get(x, 0) + 1
                mo = re.search(r"other than (\w+)", _w)
                if mo:
                    cnt.pop(_COLOR_W.get(mo.group(1), "?"), None)
                perm.chosen_color = max(cnt, key=cnt.get) if cnt else "R"
                game.log(f"{ctrl.name} elige el color {perm.chosen_color}")
            if "creature type" in _w:
                counts = {}
                for it in list(ctrl.battlefield) + list(ctrl.hand) + list(ctrl.library):
                    cd = getattr(it, "card", it)
                    if cd.is_creature():
                        for st in cd.subtypes:
                            counts[st] = counts.get(st, 0) + 1
                perm.chosen_type = max(counts, key=counts.get) if counts else "Human"
                game.log(f"{ctrl.name} elige el tipo {perm.chosen_type}")
                if getattr(perm.card, "is_chosen_type", None) == "all":
                    game._ct_all = True
            if "opponent" in _w or "player" in _w:
                if opps:
                    perm.chosen_opp = max(opps, key=lambda o: (sum(x.power for x in o.creatures()), o.life))
                    game.log(f"{ctrl.name} elige a {perm.chosen_opp.name}")
            if "card name" in _w:
                names = []
                for o in opps:
                    for c in list(getattr(o, "command", []) or []) + [x.card for x in o.battlefield]:
                        if not c.is_land() and ("nonbasic land" not in _w):
                            names.append(c.name)
                        elif "nonbasic land" in _w and c.is_land() and "basic" not in c.supertypes:
                            names.append(c.name)
                if names:
                    perm.chosen_name = names[0]
                    game.log(f"{ctrl.name} nombra {perm.chosen_name}")
            if _prev:
                _prev(game, ctrl, perm)
        card.on_etb = _etb_choice
        card.etb_choice = _what
    if re.search(r"(?:^|\n)(?:this creature|~|" + "|".join(re.escape(n) for n in _self_names(name) if n) +
                 r") has protection from the chosen color", _otc) or \
            re.search(r"(?:this creature|~) has protection from the chosen color", _otc):
        card.keywords = set(card.keywords) | {"protection"}
    if "enchanted creature has protection from the chosen color" in _otc:
        card.aura_keywords = set(getattr(card, "aura_keywords", None) or ()) | {"protection"}
    if re.search(r"(?:this creature|~) is the chosen type in addition to its other types", _otc):
        card.is_chosen_type = "self"
    if "creatures you control are the chosen type in addition to their other types" in _otc:
        card.is_chosen_type = "all"
    _mcn = re.search(r"(your opponents can't|you can't|players can't|) ?cast spells with the chosen name|"
                     r"spells with the chosen name can't be cast", _otc)
    if _mcn and "chosen name" in _otc:
        card.name_lock_cast = "opp" if "opponents" in (_mcn.group(1) or "") else "all"
    if re.search(r"activated abilities of sources with the chosen name can't be activated", _otc):
        card.name_lock_abilities = "nonmana" if "unless they're mana abilities" in _otc else "all"
    _mst = re.search(r"spells you cast of the chosen type cost \{(\d+)\} less to cast", _otc)
    if _mst and getattr(card, "spell_discount", None) is None:
        def _f_ct21(c, pl, g, _cd=card):
            pm = next((x for x in pl.battlefield if x.card is _cd), None)
            ct = getattr(pm, "chosen_type", None) if pm is not None else None
            return bool(ct) and ct.lower() in {x.lower() for x in c.subtypes}
        _f_ct21._wp = True
        card.spell_discount = (int(_mst.group(1)), _f_ct21)

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
    _mcs = re.search(r"counter target ((?:[\w\-]+,? )*?)spell(?: unless its controller pays "
                     r"\{(\d+)\})?", (data.get("oracle_text", "") or ""), re.I)
    if ({"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve
            and _mcs):
        _cf = _counter_filter(_mcs.group(1))
        if _cf != "?":
            card.on_cast_resolve = _counter_spell_effect(
                _cf, int(_mcs.group(2)) if _mcs.group(2) else None)
            card.counter_filter = _cf
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

    # barrida por EXILIO ("exile all creatures": Sunfall) — se cablea antes de la capa
    # genérica para que EXILIE (no destruya) y maneje el incubate.
    if {"instant", "sorcery"} & types and not card.on_cast_resolve:
        xa = _exile_all_creatures_effect(data.get("oracle_text", ""))
        if xa is not None:
            card.on_cast_resolve = xa
            if re.search(r"exile all creatures you control",
                         (data.get("oracle_text", "") or "").lower()):
                card.tags = (card.tags - {"wipe"}) | {"polymorph"}   # no es barrida
            else:
                card.tags = card.tags | {"wipe"}

    # barrida CON rider de fichas ("destroy all creatures, then create N tokens per
    # your nontoken creature destroyed this way"): p. ej. Ceaseless Conflict. Se
    # cablea antes de la capa genérica, que solo pondría el wrath pelado sin fichas.
    if {"instant", "sorcery"} & types and not card.on_cast_resolve:
        wt = _wipe_then_tokens_effect(data.get("oracle_text", ""))
        if wt is not None:
            card.on_cast_resolve = wt
            card.tags = card.tags | {"wipe"}

    # barrida "destroy all …" con tipos/filtros (Plague Wind, Austere Command…)
    if {"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve:
        _md = _mass_destroy_effect(data.get("oracle_text", ""))
        if _md == "?":
            # no la entendemos: sin efecto, en vez del Wrath genérico del tag "wipe"
            card.on_cast_resolve = (lambda g, c, tg, _n=name:
                                    g.log(f"{c.name} resuelve {_n} (efecto complejo: "
                                          f"no se simula en detalle)"))
        elif _md is not None:
            card.on_cast_resolve = _md
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
        if {"instant", "sorcery"} & types:
            geff = _generic_amount_effect(data.get("oracle_text", ""))
            if geff is not None:
                card.on_cast_resolve = geff
                if getattr(geff, "_is_sweep", False):
                    card.tags = set(card.tags) | {"wipe"}   # la IA lo evalúa como barrida
        elif ({"creature", "artifact", "enchantment", "land"} & types and _etb_body
              and (not re.match(r"if\b", _etb_body, re.I) or _known_if(_etb_body))):
            # solo el CUERPO del disparo de entrada propio (antes se parseaba todo el
            # oráculo: "whenever ANOTHER creature enters", landfall, "if it was
            # kicked", habilidades activadas… se cableaban como ETB)
            geff = _effect_any(_etb_body)
            if geff is not None:
                card.on_etb = geff

    # último recurso para hechizos DIRIGIDOS: instant/sorcery aún sin efecto cuyo
    # texto reconozca _fragment_effect (p. ej. "put a +1/+1 counter on target
    # creature", "tap target creature"). Va DESPUÉS del genérico para no pisar los
    # cableados más específicos (burn/bolster/etc.).
    if {"instant", "sorcery"} & types and not card.modes and not card.on_cast_resolve:
        _fe, _fspec, _fcount = _fragment_effect(data.get("oracle_text", ""))
        if _fe is not None:
            card.on_cast_resolve = _fe
            if _fspec is not None:
                card.target_spec = _fspec
                card.target_count = max(1, _fcount)

    # ETB dirigido en un PERMANENTE (p. ej. destruir criatura/tierra al entrar):
    # se cablea aunque tenga tag removal/wipe (esos tags apuntan al camino de CAST,
    # que no aplica a una criatura/artefacto que entra al campo).
    if (not card.on_etb and not card.modes
            and {"creature", "artifact", "enchantment", "land"} & types
            and _etb_body and (not re.match(r"if\b", _etb_body, re.I)
                               or _known_if(_etb_body))):
        geff = _effect_any(_etb_body)
        if geff is not None:
            card.on_etb = geff

    # CLONES: "You may have ~ enter as a copy of any creature on the battlefield"
    # (Clone, Phantasmal Image, Spark Double…): al entrar PASA A SER esa carta.
    if {"creature", "artifact", "enchantment"} & types:
        _cl = _clone_enter_spec(data.get("oracle_text", ""), name)
        if _cl is not None:
            card.on_etb = _clone_enter_effect(_cl)

    # Skyclave Apparition y similares: ETB exilia un permanente rival con tope de
    # CMV y, al DEJAR el campo, el dueño crea una ficha X/X (X = CMV exiliado).
    _sky_t = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    _sky_etb = re.search(r"exile (?:up to \w+ )?target .*?permanent .*?"
                         r"with (?:mana value|converted mana cost) (\d+) or less", _sky_t)
    _sky_leave = re.search(r"leaves the battlefield.*?creates? an x/x (.*?) creature token"
                           r".*?mana value of the exiled card", _sky_t)
    if "creature" in types and _sky_etb and _sky_leave:
        _cap = int(_sky_etb.group(1))
        _subw = [w for w in (_sky_leave.group(1) or "").split()
                 if w not in ("green", "white", "blue", "black", "red", "colorless", "and")]
        _ill = _subw[-1].capitalize() if _subw else "Illusion"

        def _skyclave_etb(game, ctrl, perm, _cap2=_cap):
            def _cmv(pm):
                return pm.card.cost.cmc if getattr(pm.card, "cost", None) else 0
            pool = [pm for o in game.opponents(ctrl) for pm in o.battlefield
                    if not pm.card.is_land() and not pm.is_token and _cmv(pm) <= _cap2]
            if not pool:
                game.log(f"{ctrl.name}: no hay permanente rival válido para exiliar")
                return
            pool.sort(key=lambda pm: _cmv(pm), reverse=True)
            cands = [(f"{pm.name} (CMV {_cmv(pm)}) · {pm.controller.name}", pm)
                     for pm in pool]

            def _do(victim):
                owner = victim.controller
                if victim not in owner.battlefield:
                    return
                mv = victim.card.cost.cmc if getattr(victim.card, "cost", None) else 0
                owner.battlefield.remove(victim)
                if not victim.is_token and game.commander_owner(victim.card) is None:
                    owner.exile.append(victim.card)
                perm._skyclave_exiled = (owner, mv)     # recordar para la salida
                game.log(f"{ctrl.name} exilia {victim.name} (CMV {mv}) de {owner.name}")
                game.sba()

            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí un permanente del rival para exiliar (o ninguno)",
                                 cands, _do, allow_none=True)

        def _skyclave_leave(game, ctrl, perm, _sub=_ill):
            info = getattr(perm, "_skyclave_exiled", None)
            if not info:
                return
            owner, mv = info
            perm._skyclave_exiled = None
            cards.make_token(game, owner, _sub, mv, mv, subtypes=(_sub,))
            game.log(f"{owner.name} crea una ficha {_sub} {mv}/{mv} "
                     f"(por la carta exiliada de {perm.name})")

        card.on_etb = _skyclave_etb
        card.on_leave = _skyclave_leave

    # populate ("Populate" / "then populate"): copia tu mejor ficha de criatura.
    # Se ejecuta al resolverse el hechizo (encadenado con el efecto previo si lo hay).
    if re.search(r"\bpopulate\b", (data.get("oracle_text", "") or ""), re.I) \
            and {"instant", "sorcery"} & types:
        card.tags = card.tags | {"populate"}
    if re.search(r"\bpopulate\b", (data.get("oracle_text", "") or ""), re.I) \
            and {"instant", "sorcery"} & types and card.on_cast_resolve is None:
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
    # Solo la KEYWORD propia (no "...gains cascade" que otorga a otros: Yidris
    # cascadeaba al entrar).
    if _has_keyword(data, "cascade"):
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

    # Encantamiento — Clase (level up por coste, habilidad por nivel). Se cablea
    # DESPUÉS de _parse_activated para reemplazar el mal-parseo de "{coste}: Level N".
    if "class" in {s.lower() for s in getattr(card, "subtypes", set())}:
        _parse_class(card, data.get("oracle_text", ""))

    # disparo "al atacar" (whenever ~ attacks, ...): p. ej. Laelia (exiliar el tope
    # y poder jugarla). Se cablea como trigger de "attacks".
    atk_eff = _attack_trigger_effect(data.get("oracle_text", ""))
    if atk_eff is not None and "attacks" not in card.triggers:
        card.triggers = dict(card.triggers)
        card.triggers["attacks"] = atk_eff

    # disparo combinado "whenever ~ enters OR attacks, <efecto>" (Omo, etc.): se
    # cablea a la vez como ETB y como disparo de "attacks".
    _oatxt = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "")).lower()
    meoa = re.search(r"when(?:ever)? [\w' ,]+? enters or attacks,?\s*(.{0,200})", _oatxt)
    if meoa and "creature" in types:
        body = meoa.group(1)
        if "everything counter" in body:
            _eoa = _everything_counter_effect()
        else:
            _e2, _s2, _c2 = _fragment_effect(body)
            _eoa = (lambda g, c, p, _e=_e2: _e(g, c, [])) if _e2 else None
        if _eoa is not None:
            # el ETB genérico ya cableó este mismo cuerpo ("enters or attacks"):
            # encadenarlo otra vez duplicaba el efecto (Grave Titan creaba 4 Zombies)
            if card.on_etb is None:
                card.on_etb = (lambda g, c, p, _e=_eoa: _e(g, c, p))
            card.triggers = dict(card.triggers)
            card.triggers.setdefault(
                "attacks", lambda g, perm, _e=_eoa, **kw: _e(g, perm.controller, perm))

    # anthem estático genérico ("creatures you control get +X/+X" / "have <kw>"),
    # p. ej. importado de Scryfall. Se cablea antes de la capa por tags.
    if ({"creature", "artifact", "enchantment", "land"} & types
            and "planeswalker" not in types and card.static_mod is None):
        # solo habilidades ESTÁTICAS incondicionales: antes un "as long as…", un
        # "+1/+0 until end of turn" activado o el emblema de un planeswalker
        # quedaban como anthem permanente (Beastmaster Ascension, Gideon, Elspeth)
        sm, akw, asub = _static_anthem(_static_text(data.get("oracle_text", "")))
        if sm is not None:
            card.static_mod = sm
            card.tags = card.tags | {"anthem"}
        if akw:
            card.anthem_keywords = set(akw)
            card.anthem_others = "other " in (
                data.get("oracle_text", "") or "").lower()
            if asub:
                card.anthem_subtype = asub

    # buff ESTÁTICO CONDICIONAL de la propia criatura ("~ gets +X/+Y as long as
    # <condición>"): Sylvan Advocate, Kird Ape, Angel of Vitality…
    if card.static_mod is None and "creature" in types:
        _csb = _conditional_self_buff(data.get("oracle_text", ""), card.name)
        if _csb is not None:
            card.static_mod = _csb
    if "creature" in types:
        _ckw = _conditional_self_keywords(data.get("oracle_text", ""), card.name)
        if _ckw:
            card.cond_keywords = tuple(_ckw)

    # reemplazo de ganancia de vida: "if you would gain life, you gain that much
    # life plus N instead" (Angel of Vitality, Boon Reflection…). +N por evento.
    _lgb = re.search(r"if you would gain life, you gain that much life plus (\d+) instead",
                     re.sub(r"\s+", " ", (data.get("oracle_text", "") or "")), re.I)
    if _lgb:
        card.life_gain_bonus = int(_lgb.group(1))

    # Sower of Temptation: al dejar el campo, la criatura robada vuelve a su dueño
    # ("gain control ... for as long as you control ~"). El robo lo hace el ETB.
    _ctl = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    if ("creature" in types and card.on_leave is None
            and re.search(r"gain control of .*?target creature", _ctl)
            and re.search(r"as long as (?:you control|[\w,' ]+ remains on the battlefield)", _ctl)):
        def _return_stolen(game, ctrl, perm):
            st = getattr(perm, "_stolen", None)
            if st:
                tgt, old = st
                if tgt in ctrl.battlefield:
                    ctrl.battlefield.remove(tgt)
                    tgt.controller = old
                    old.battlefield.append(tgt)
                    game.log(f"{tgt.name} vuelve a {old.name}")
                perm._stolen = None
        card.on_leave = _return_stolen

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

    # Disparos de combate al atacar (keyword o texto). Los aplica el motor con la
    # lista completa de atacantes (battle cry, mentor, melee, training).
    if "creature" in types:
        _kws_lc = {k.lower() for k in (data.get("keywords") or [])}
        if "battle cry" in _kws_lc or "battle cry" in _lt:
            card.battle_cry = True
        if "mentor" in _kws_lc or re.search(r"\bmentor\b", _lt):
            card.mentor = True
        if "melee" in _kws_lc or re.search(r"\bmelee\b", _lt):
            card.melee = True
        if "training" in _kws_lc or re.search(r"\btraining\b", _lt):
            card.training = True
        # Renombre N: al pegar daño de combate a un jugador (no renombrada) gana
        # N contadores +1/+1. Lo resuelve el motor en deal_damage.
        mren = re.search(r"renown (\d+)", _lt)
        if mren:
            card.renown = int(mren.group(1))
        # Bloodthirst N: entra con N contadores +1/+1 si un rival fue dañado este turno.
        mbt = re.search(r"bloodthirst (\d+)", _lt)
        if mbt:
            _bt = int(mbt.group(1))

            def _bloodthirst(g, ctrl, perm, _n=_bt):
                if any(pl in getattr(g, "damaged_players", set())
                       for pl in g.opponents(ctrl)):
                    g.add_counters(perm, "+1/+1", _n)
                    g.log(f"Sed de sangre: {perm.name} entra con +{_n}/+{_n}")
            _prev_bt = card.on_etb
            card.on_etb = (lambda g, ctrl, perm, _d=_bloodthirst, _p=_prev_bt:
                           (_d(g, ctrl, perm), _p(g, ctrl, perm) if _p else None))
        # Dethrone: keyword/estática al atacar (lo resuelve el motor).
        if "dethrone" in _kws_lc or re.search(r"\bdethrone\b", _lt):
            card.dethrone = True
        # Myriad: copias atacando a cada otro rival (lo resuelve el motor).
        if "myriad" in _kws_lc or _has_keyword(data, "myriad"):
            card.myriad = True
        # Aniquilador N: al atacar, el defensor sacrifica N permanentes.
        man = re.search(r"annihilator (\d+)", _lt)
        if man:
            card.annihilator = int(man.group(1))
        # Aflicción N: al ser bloqueada, el defensor pierde N vida.
        maf = re.search(r"afflict (\d+)", _lt)
        if maf:
            card.afflict = int(maf.group(1))
        # Arrasar N (rampage): +N/+N por cada bloqueador extra.
        mrp = re.search(r"rampage (\d+)", _lt)
        if mrp:
            card.rampage = int(mrp.group(1))
        # Bushido N: +N/+N al bloquear o ser bloqueada.
        mbu = re.search(r"bushido (\d+)", _lt)
        if mbu:
            card.bushido = int(mbu.group(1))
        # Toxic N: N contadores de veneno por daño de combate.
        mtx = re.search(r"toxic (\d+)", _lt)
        if mtx:
            card.toxic_n = int(mtx.group(1))
            card.keywords = set(card.keywords) | {"toxic"}   # asegura has("toxic")
        # Modular N: entra con N contadores +1/+1; al morir, los mueve a otro
        # artefacto-criatura.
        mmo = re.search(r"modular (\d+)", _lt)
        if mmo:
            _mn = int(mmo.group(1))
            card.etb_counters = dict(getattr(card, "etb_counters", None) or {})
            card.etb_counters["+1/+1"] = card.etb_counters.get("+1/+1", 0) + _mn

            def _modular_death(g, ctrl, perm):
                moved = perm.counters.get("+1/+1", 0)
                if moved:
                    dests = [pm for pm in ctrl.battlefield
                             if pm is not perm and pm.is_creature()
                             and "artifact" in pm.card.types]
                    if dests:
                        g.add_counters(max(dests, key=lambda p: p.power), "+1/+1", moved)
                        g.log(f"Modular: {perm.name} mueve {moved} contador(es) +1/+1")
                return False
            if card.on_death is None:
                card.on_death = _modular_death
        # Afterlife N: al morir, N fichas 1/1 blanca y negra Espíritu con vuelo.
        mal = re.search(r"afterlife (\d+)", _lt)
        if mal:
            _an = int(mal.group(1))

            def _afterlife_death(g, ctrl, perm, _n=_an):
                for _ in range(_n):
                    cards.make_token(g, ctrl, "Spirit", 1, 1, kw=("flying",),
                                     subtypes=("Spirit",))
                g.log(f"Vida después de la muerte: {_n} ficha(s) Espíritu 1/1 volador")
                return False
            if card.on_death is None:
                card.on_death = _afterlife_death
        # Riot: entra con prisa O un contador +1/+1 (motor: apply_riot elige).
        if "creature" in types and ("riot" in _kws_lc or re.search(r"(?:^|\n)riot\b", _lt)):
            def _riot_etb(g, ctrl, perm):
                g.apply_riot(perm)
            _prev_ri = card.on_etb
            card.on_etb = (lambda g, ctrl, perm, _d=_riot_etb, _p=_prev_ri:
                           (_d(g, ctrl, perm), _p(g, ctrl, perm) if _p else None))

    # Fading N / Vanishing N: entran con N contadores; el motor los va quitando en el
    # mantenimiento y sacrifica al agotarse (_tick_upkeep_counters).
    mfa = re.search(r"fading (\d+)", _lt)
    if mfa:
        card.fading = int(mfa.group(1))
        card.etb_counters = dict(getattr(card, "etb_counters", None) or {})
        card.etb_counters["fade"] = card.fading
    mva = re.search(r"vanishing (\d+)", _lt)
    if mva:
        card.vanishing = int(mva.group(1))
        card.etb_counters = dict(getattr(card, "etb_counters", None) or {})
        card.etb_counters["time"] = card.vanishing
    # Cumulative upkeep: coste creciente cada mantenimiento (maná o vida).
    if "cumulative upkeep" in _lt:
        ml = re.search(r"cumulative upkeep[—\-\s]*pay (\d+) life", _lt)
        if ml:
            card.cumulative_upkeep = {"kind": "life", "amount": int(ml.group(1))}
        else:
            mg = re.search(r"cumulative upkeep[—\-\s]*\{(\d+)\}", _lt)
            if mg:
                amt = int(mg.group(1))
            else:  # coste de color: contar símbolos {W}{U}… tras "cumulative upkeep"
                mc2 = re.search(r"cumulative upkeep[—\-\s]*((?:\{[wubrgc]\})+)", _lt)
                amt = len(re.findall(r"\{[wubrgc]\}", mc2.group(1))) if mc2 else 1
            card.cumulative_upkeep = {"kind": "mana", "amount": amt or 1}

    # reducción de coste ESTÁTICA a tus hechizos: "<tipo> spells you cast cost {N}
    # less to cast" (Goblin Electromancer, Medallion, etc.).
    # por LÍNEA y con el calificador completo: "Goblin spells you cast…" o
    # "Artifact and enchantment spells your opponents cast…" antes caían en el
    # filtro "any" (Goblin Warchief abarataba todo; Aura of Silence gravaba todo).
    # Un calificador que no se entiende deja la carta sin el efecto (regla 5).
    for _ln in _ability_lines(data.get("oracle_text", "")):
        _l = _ln.lower()
        mred = re.match(r"([\w ,]*?)\s*spells? you cast cost \{(\d+)\} less", _l)
        if mred and getattr(card, "spell_discount", None) is None:
            _f = _cost_filter(mred.group(1))
            if _f is not None:
                card.spell_discount = (int(mred.group(2)), _f)
        mtax = re.match(r"([\w ,]*?)\s*spells?\s*(your opponents? cast|you cast|cast)?"
                        r"\s*cost \{(\d+)\} more", _l)
        if mtax and getattr(card, "spell_tax", None) is None:
            _f = _cost_filter(mtax.group(1))
            if _f is not None:
                whose = "opponents" if "opponent" in (mtax.group(2) or "") else "all"
                card.spell_tax = (int(mtax.group(3)), _f, whose)

    # (el impuesto de coste estático se parsea arriba, junto a la reducción)

    # Storm: al lanzarse, se copia por cada hechizo lanzado antes este turno (el
    # motor repite el efecto). Marcamos con un tag; sólo aplica a instant/sorcery.
    # keyword propia (no el nombre "Lightning Storm" dentro del texto)
    if _has_keyword(data, "storm") and {"instant", "sorcery"} & types:
        card.tags = card.tags | {"storm"}

    # Buyback {N}: coste adicional de maná; si se paga, la carta vuelve a la mano.
    mbb = re.search(r"buyback \{(\d+)\}", _lt)
    if mbb and {"instant", "sorcery"} & types:
        card._buyback_cost = int(mbb.group(1))

    # Adventure: carta de criatura con una cara de hechizo (Adventure). Se puede
    # lanzar la aventura (efecto) y luego la criatura queda jugable desde el exilio.
    _faces = data.get("card_faces") or []
    if (len(_faces) == 2 and "creature" in types
            and "adventure" in (_faces[1].get("type_line", "") or "").lower()):
        adv = _faces[1]
        adv_cost = parse_cost(mana_cost_to_str(adv.get("mana_cost", "") or "0"))
        aeff, aspec, acount = _fragment_effect(adv.get("oracle_text", "") or "")
        if aeff is None:
            aeff2 = _generic_amount_effect(adv.get("oracle_text", "") or "")
            aeff = (lambda g, c, tg=None, _e=aeff2: _e(g, c)) if aeff2 else None
            aspec, acount = None, 1
        if aeff is not None:
            card.adventure = {"cost": adv_cost, "effect": aeff, "label": adv.get("name", "Aventura"),
                              "target_spec": aspec, "target_count": acount}

    # Prepared (set FRA): la criatura entra "preparada" y, mientras lo esté, podés
    # lanzar UNA copia de su hechizo (cara card_faces[1]). Hacerlo la desprepara.
    if (len(_faces) == 2 and "creature" in types and "prepared" in _lt
            and {"instant", "sorcery"} & set(parse_type_line(
                _faces[1].get("type_line", ""))[0])):
        spell = _faces[1]
        pcost = parse_cost(mana_cost_to_str(spell.get("mana_cost", "") or "0"))
        peff, pspec, pcount = _fragment_effect(spell.get("oracle_text", "") or "")
        if peff is None:
            peff2 = _generic_amount_effect(spell.get("oracle_text", "") or "")
            peff = (lambda g, c, tg=None, _e=peff2: _e(g, c)) if peff2 else None
            pspec, pcount = None, 1
        if peff is not None:
            def _prep_etb(g, ctrl, perm, _prev=card.on_etb):
                perm._prepared = True
                if _prev:
                    _prev(g, ctrl, perm)
            card.on_etb = _prep_etb

            _mgl = re.search(r"gain (\w+) life", spell.get("oracle_text", "") or "", re.I)
            _gl = _count_word(_mgl.group(1)) if _mgl else 0

            def _prep_eff(g, c, perm, tg, _e=peff, _gain=_gl):
                _e(g, c, tg)
                if _gain:
                    g.gain_life(c, _gain)
                if perm is not None:
                    perm._prepared = False
            card.activated_abilities = tuple(card.activated_abilities) + ({
                "cost": pcost, "tap": False, "sacrifice_self": False,
                "sacrifice_other": None, "pay_life": 0, "discard": 0,
                "label": f"Lanzar {spell.get('name', 'hechizo')} (preparada)",
                "effect": _prep_eff, "target_spec": pspec,
                "target_count": pcount, "is_copy_ability": False,
                "prepared": True},)

    # "Spells your opponents cast that target this creature cost {N} more to cast":
    # se aproxima como ward {N} (el rival paga N extra o el efecto falla).
    _mtax = re.search(r"spells your opponents cast that target (?:this creature|~|this permanent) "
                      r"cost \{(\d+)\} more to cast", _lt)
    if _mtax and not getattr(card, "ward", None):
        card.ward = {"mana": parse_cost(_mtax.group(1))}
        card.keywords = set(card.keywords) | {"ward"}

    # Changeling: la criatura es de TODOS los tipos de criatura (para sinergias
    # tribales). Marcamos el flag; los conteos por tipo lo tratan como comodín.
    if "changeling" in _lt and "creature" in types:
        card.changeling = True

    # Evoke {coste}: se puede lanzar por un coste alternativo más barato; al entrar
    # se sacrifica (te quedás con el ETB). El bot la usa por el ETB.
    mev = re.search(r"evoke ((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mev and "creature" in types:
        card.evoke_cost = parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mev.group(1)))))

    # Dash / Blitz / Ninjutsu: cast alternativo con prisa (comportamiento a fin de
    # turno según la mecánica; ver Game.cast_alt_haste).
    for _kw, _attr in (("dash", "dash_cost"), ("blitz", "blitz_cost"),
                       ("ninjutsu", "ninjutsu_cost")):
        _m = re.search(_kw + r"\s*((?:\{[wubrgc0-9/x]+\})+)", _lt)
        if _m and "creature" in types:
            setattr(card, _attr, parse_cost(mana_cost_to_str(
                "".join(re.findall(r"\{[wubrgc0-9/x]+\}", _m.group(1))))))

    # Cycling {coste}: {coste}, descartar esta carta: robar una. Habilidad DESDE LA
    # MANO (ver Game.cycle_card). También ciclos tipográficos ("typecycling") se
    # aproximan como robar 1.
    mcy = re.search(r"(?:\w+)?cycling\s*((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mcy:
        card.cycling = parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mcy.group(1)))))

    # Entwine {coste}: en una carta modal, pagás el coste de entwine para elegir
    # TODOS los modos en vez de uno.
    men = re.search(r"entwine(?:—|\s)((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if men:
        card._entwine_cost = sum(int(s) if s.isdigit() else 1
                                 for s in re.findall(r"\{([wubrgc0-9/x]+)\}", men.group(1)))

    # Aftermath: la mitad de "secuela" de una carta partida se lanza SOLO desde el
    # cementerio. Exponemos esa cara como jugable desde el cementerio (gy_play).
    if (len(_faces) == 2 and "aftermath" in ((_faces[1].get("oracle_text", "") or "")
            + " " + (_faces[1].get("type_line", "") or "")).lower()):
        af = _faces[1]
        aff, _s, _c = _fragment_effect(af.get("oracle_text", "") or "")
        if aff is None:
            aff2 = _generic_amount_effect(af.get("oracle_text", "") or "")
            aff = (lambda g, ctrl, tg=None, _e=aff2: _e(g, ctrl)) if aff2 else None
        if aff is not None and not getattr(card, "gy_play", None):
            card.gy_play = {"mode": "aftermath", "cost": parse_cost(
                mana_cost_to_str(af.get("mana_cost", "") or "0")),
                "effect": aff, "label": af.get("name", "Secuela")}

    # Cartas de DOBLE CARA (transform / modal DFC): construye la cara trasera como
    # Card aparte y guarda cómo se accede. Excluye adventure/aftermath/prepared/split
    # (ya manejados) y las que no son de doble cara real.
    if (len(_faces) == 2 and not getattr(card, "adventure", None)
            and not getattr(card, "gy_play", None) and "prepared" not in _lt
            and "adventure" not in (_faces[1].get("type_line", "") or "").lower()
            and "aftermath" not in ((_faces[1].get("oracle_text", "") or "").lower())):
        _back_raw = _faces[1]
        _back_data = dict(data)
        _back_data["card_faces"] = None
        for _k in ("type_line", "mana_cost", "power", "toughness",
                   "oracle_text", "loyalty", "name", "keywords"):
            if _back_raw.get(_k) not in (None, "", []):
                _back_data[_k] = _back_raw[_k]
        _back_data["name"] = _back_raw.get("name") or (card.name + " (dorso)")
        try:
            _back = build_card_from_data(_back_data)
        except Exception:
            _back = None
        if _back is not None:
            card.back_face = _back
            # daybound / nightbound (día-noche): el frente es daybound, el dorso
            # nightbound. Detección por keywords u oracle de cada cara.
            _f0_txt = ((_faces[0].get("oracle_text", "") or "") + " "
                       + " ".join(_faces[0].get("keywords", []) or [])).lower()
            _f1_txt = ((_back_raw.get("oracle_text", "") or "") + " "
                       + " ".join(_back_raw.get("keywords", []) or [])).lower()
            _day = any(k in _f0_txt + _f1_txt for k in ("daybound", "nightbound"))
            # transform vs modal (MDFC): es "transform" si se da vuelta en juego
            # (día/noche, o el texto dice "transform"); si no, es modal -> ambas
            # caras se juegan desde la mano (Pathways, DFC modal tierra/hechizo).
            _is_transform = _day or bool(re.search(r"\b(?:transform|convert)\b|more than meets the eye",
                                                   _f0_txt + _f1_txt))
            card.dfc = "transform" if _is_transform else "modal"
            if _day:
                card.daybound = "daybound" in _f0_txt
                card.nightbound = "nightbound" in _f0_txt
                _back.daybound = "daybound" in _f1_txt
                _back.nightbound = "nightbound" in _f1_txt
            # habilidad manual "Transformar" si el texto la usa (aprox. de werewolves/
            # DFC que se dan vuelta; sin modelar día/noche automático).
            # solo si NINGUNA habilidad activada del texto ya transforma con su coste
            # real (Westvale Abbey: "{5},{T}, sacrifice five creatures: Transform");
            # antes se agregaba igual una gratis y se volvía Ormendahl sin pagar
            _act_tf = any(_is_activated_line(l) and re.search(r"\btransform\b", l, re.I)
                          for l in _ability_lines(data.get("oracle_text", "")))
            _ww = re.search(r"at the beginning of each upkeep, if (?:no spells were cast|a "
                            r"player cast two or more spells) last turn, transform", _lt)
            if card.dfc == "transform" and re.search(r"\btransform\b", _lt) and not _act_tf \
                    and not _ww:
                def _tf_eff(game, ctrl, perm, targets=None):
                    game.transform(perm)
                card.activated_abilities = tuple(card.activated_abilities or ()) + (
                    {"cost": parse_cost("0"), "tap": False, "sacrifice_self": False,
                     "sacrifice_other": None, "pay_life": 0, "discard": 0,
                     "label": "Transformar", "effect": _tf_eff, "target_spec": None,
                     "target_count": 1, "is_copy_ability": False, "sorcery_speed": True},)

    # Kicker {coste} / Multikicker: coste adicional opcional al lanzar; "if (this was)
    # kicked, <efecto>" resuelve el bono. Auto: se paga si el jugador puede.
    mk = re.search(r"(?:multikicker|kicker)(?:—|\s)((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mk:
        card._kicker_cost = sum(int(s) if s.isdigit() else 1
                                for s in re.findall(r"\{([wubrgc0-9/x]+)\}", mk.group(1)))
        mkb = re.search(r"if (?:this spell was |this creature was |this was |it was |"
                        r"[\w~' ]{0,15}was |)kicked,?\s*(.{0,140})", _lt)
        if mkb:
            beff = _generic_amount_effect(mkb.group(1))
            if beff is not None:
                card._kicked_effect = beff
                if "creature" in types:      # el bono corre al entrar (ETB)
                    def _kick_etb(g, ctrl, perm, _prev=card.on_etb, _b=beff):
                        if getattr(perm.card, "_kicked", False):
                            _b(g, ctrl)
                        if _prev:
                            _prev(g, ctrl, perm)
                    card.on_etb = _kick_etb

    # Madness <coste>: si se descarta, se puede lanzar por el coste de madness en
    # vez de ir al cementerio (el motor lo hace automático si hay maná).
    mmad = re.search(r"madness ((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mmad:
        card.madness = parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mmad.group(1)))))

    # Morph / Megamorph / Disguise {coste}: se puede lanzar boca abajo por {3} como
    # 2/2 sin nombre y darla vuelta pagando este coste (ver Game.cast_face_down).
    _mana_re = r"((?:\{[wubrgc0-9/x]+\})+)"
    for _kw, _attr in (("megamorph", "morph_cost"), ("morph", "morph_cost"),
                       ("disguise", "disguise_cost")):
        _m = re.search(r"(?:^|\n|\. )" + _kw + r"[ —]*" + _mana_re,
                       "\n" + (data.get("oracle_text", "") or "").lower())
        if _m and "creature" in types and getattr(card, _attr, None) is None:
            setattr(card, _attr, parse_cost(mana_cost_to_str(
                "".join(re.findall(r"\{[wubrgc0-9/x]+\}", _m.group(1))))))
            if _kw == "megamorph":
                card.megamorph = True
    # "When ~ is turned face up, <efecto>"
    for _ln in _ability_lines(data.get("oracle_text", "") or ""):
        _mf = re.match(r"(?i)when (?:~|this creature|this permanent|"
                       + re.escape(name) + r"|" + re.escape(name.split(",")[0])
                       + r") is turned face up, (.+)$", _ln.strip())
        if _mf:
            _eff = _effect_any(_mf.group(1))
            if _eff is not None:
                card.on_turn_face_up = (lambda g, ctrl, perm, _e=_eff: _e(g, ctrl, perm))
    # Bestow {coste}: se lanza como Aura; el huésped recibe +X/+Y y sus keywords.
    mbe = re.search(r"bestow[ —]*" + _mana_re, _lt)
    if mbe and "creature" in types:
        card.bestow_cost = parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mbe.group(1)))))
        _mb = re.search(r"enchanted creature gets ([+-]\d+)/([+-]\d+)", _lt)
        _bkw = set()
        _hm = re.search(r"enchanted creature (?:gets [+-]\d+/[+-]\d+ and )?has ([a-z ,]+?)"
                        r"(?:\.|$| and gets)", _lt)
        if _hm:
            for _w in re.split(r",\s*(?:and\s+)?|\s+and\s+", _hm.group(1)):
                _k = _w.strip().replace(" ", "_")
                if _k in KEYWORDS:
                    _bkw.add(_k)
        card.bestow_mod = ((int(_mb.group(1)), int(_mb.group(2))) if _mb else (0, 0)) \
            + (tuple(sorted(_bkw)),)
        card.tags = card.tags | {"bestow"}
    # ── batch 2: lanzamientos alternativos / costes extra / estáticas ──────
    def _kwcost(kw):
        m = re.search(r"(?:^|\n)" + kw + r"[ —–]*((?:\{[wubrgc0-9/x]+\})+)",
                      "\n" + (data.get("oracle_text", "") or "").lower())
        return parse_cost(mana_cost_to_str("".join(
            re.findall(r"\{[wubrgc0-9/x]+\}", m.group(1))))) if m else None
    _kws_l = {k.lower() for k in (data.get("keywords") or [])}
    _spell = bool({"instant", "sorcery"} & types)
    if "rebound" in _kws_l and _spell:
        card.rebound = True
    if "split second" in _kws_l:
        card.keywords = set(card.keywords) | {"split_second"}
    if _spell and (oc := _kwcost("overload")) is not None:
        # sobrecarga: el MISMO efecto sobre todo lo que podría ser objetivo (el
        # motor arma la lista al lanzar); "you don't control" -> solo rivales
        card.overload_cost = oc
        card.overload_opp = "you don't control" in _lt or "an opponent controls" in _lt
    if "retrace" in _kws_l and card.cost is not None:
        card.gy_play = {"mode": "retrace", "cost": card.cost, "after": "graveyard",
                        "discard": "land"}
    if "jump-start" in _kws_l and _spell and card.cost is not None:
        card.gy_play = {"mode": "jump-start", "cost": card.cost, "after": "exile",
                        "discard": "any"}
    if (mc := _kwcost("miracle")) is not None:
        card.miracle_cost = mc
    if (pc := _kwcost("plot")) is not None:
        card.plot_cost = pc
    if (wc := _kwcost("warp")) is not None:
        card.warp_cost = wc
    mproto = re.search(r"(?:^|\n)prototype ((?:\{[wubrgc0-9/x]+\})+)\s*[—–-]\s*(\d+)/(\d+)",
                       "\n" + (data.get("oracle_text", "") or "").lower())
    if mproto and "creature" in types:
        card.prototype = {"cost": parse_cost(mana_cost_to_str("".join(
            re.findall(r"\{[wubrgc0-9/x]+\}", mproto.group(1))))),
            "p": int(mproto.group(2)), "t": int(mproto.group(3))}
    _alts = []
    if (sc := _kwcost("surge")) is not None:
        _alts.append(("surge", sc, lambda g, p, c: getattr(p, "spells_cast_turn", 0) >= 1))
    if (spc := _kwcost("spectacle")) is not None:
        _alts.append(("spectacle", spc, lambda g, p, c: any(
            o.life < (getattr(g, "_life_start", {}) or {}).get(id(o), o.life)
            for o in g.opponents(p))))
    if (prc := _kwcost("prowl")) is not None:
        _alts.append(("prowl", prc, lambda g, p, c: getattr(p, "_prowl_turn", None) == g.turn
                      and bool({x.lower() for x in c.subtypes} & getattr(p, "prowl_types", set()))))
    _olt = re.sub(r"\s+", " ", _strip_reminder(data.get("oracle_text", "") or "")).lower()
    _ma = re.search(r"you may pay ((?:\{[wubrgc0-9/]+\})+) rather than pay this spell's mana cost", _olt)
    if _ma:
        _alts.append(("alt", parse_cost(mana_cost_to_str(_ma.group(1))), lambda g, p, c: True))
    _ma = re.search(r"you may (sacrifice|return) (a|an|two|three|\d+) (mountain|island|forest|swamp|plains|"
                    r"land|creature|artifact)s?(?: you control to (?:its|their) owner(?:'s|s') hands?)? rather "
                    r"than pay this spell's mana cost", _olt)
    if _ma and card.cost is not None:
        _n = _count_word(_ma.group(2)) or 1
        _k = ("sac" if _ma.group(1) == "sacrifice" else "bounce", _ma.group(3), _n)
        _alts.append((_k, Cost(generic=0, pips=()), lambda g, p, c, _k=_k: (
            not p.can_pay(c.cost) and sum(1 for pm in p.battlefield if pm.has_subtype(_k[1])
                                          or _k[1] in pm.card.types) >= _k[2])))
    _ma = re.search(r"(?:if you control an? (plains|island|swamp|mountain|forest), )?you may pay (\d+) life rather "
                    r"than pay this spell's mana cost", _olt)
    if _ma and card.cost is not None:
        _k = ("life", _ma.group(1) or "", int(_ma.group(2)))
        _alts.append((_k, Cost(generic=0, pips=()), lambda g, p, c, _k=_k: (
            not p.can_pay(c.cost) and p.life > _k[2] + 5
            and (not _k[1] or any(pm.has_subtype(_k[1]) for pm in p.battlefield)))))
    _ma = re.search(r"you may exile (a|an|two) (white|blue|black|red|green) cards? from your hand rather than "
                    r"pay this spell's mana cost", _olt)
    if _ma and card.cost is not None:
        _cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
        _k = ("exile_hand", _cm[_ma.group(2)], _count_word(_ma.group(1)) or 1)
        _alts.append((_k, Cost(generic=0, pips=()), lambda g, p, c, _k=_k: (
            not p.can_pay(c.cost) and sum(1 for x in p.hand if x is not c and _k[1] in {
                y for pp in (getattr(x.cost, "pips", None) or ()) for y in str(pp).upper()}) >= _k[2])))
    if _alts and card.cost is not None:
        card.alt_costs = tuple(_alts)
        card._printed_cost = card.cost
    if (ec := _kwcost("emerge")) is not None and "creature" in types:
        card.emerge_cost = ec
    if (ofc := _kwcost("offspring")) is not None and "creature" in types:
        card.offspring_cost = ofc
    if (sqc := _kwcost("squad")) is not None and "creature" in types:
        card.squad_cost = sqc
    mcas = re.search(r"(?:^|\n)casualty (\d+|x)", "\n" + (data.get("oracle_text", "") or "").lower())
    if mcas and _spell and mcas.group(1).isdigit():
        card.casualty = int(mcas.group(1))
    if "bargain" in _kws_l and _spell:
        mbg = re.search(r"if this spell was bargained, ([^.]+\.)", _lt)
        if mbg:
            _btxt = mbg.group(1)
            _inst = bool(re.search(r"\binstead\b", _btxt))
            _btxt = re.sub(r",? instead", "", _btxt)
            _beff = _effect_any(_btxt)
            if _beff is not None:
                card.bargain = True
                card.bargain_instead = _inst
                card.bargain_effect = (lambda g, ctrl, tg, _e=_beff: _e(g, ctrl, *tg))
    if _spell and card.on_cast_resolve is not None and "damage divided" in _lt:
        card.tags = set(card.tags) | {"removal"}     # la IA lo valora como remoción
    # Pacts: "At the beginning of your next upkeep, pay {X}. If you don't, you lose the game."
    mpact = re.search(r"at the beginning of your next upkeep, pay ((?:\{[^}]+\})+)\. if you don't, "
                      r"you lose the game", _lt)
    if mpact and _spell:
        card.pact_cost = parse_cost(mana_cost_to_str(mpact.group(1)))

        def _pact_resolve(g, ctrl, tg, _base=card.on_cast_resolve, _c=card.pact_cost):
            if _base is not None:
                _base(g, ctrl, tg)
            g.pact_due.append((ctrl, _c))
            g.log(f"{ctrl.name} deberá pagar el pacto en su próximo mantenimiento")
        card.on_cast_resolve = _pact_resolve
    if _cond_bonus is not None:
        def _cb_resolve(g, ctrl, tg, _base=card.on_cast_resolve, _cb=_cond_bonus):
            if _base is not None:
                _base(g, ctrl, tg)
            if _cb[0](g, ctrl):
                _cb[1](g, ctrl)
        card.on_cast_resolve = _cb_resolve
    # Exiliar HASTA que deje el campo (Banishing Light, O-Ring, Faceless Butcher):
    # el ETB exilia el objetivo y lo recuerda; al irse, vuelve bajo su dueño.
    _xl = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    for _nm5 in _self_names(name):
        if _nm5:
            _xl = _xl.replace(_nm5, "~")
    mxu = re.search(r"when (?:~|this \w+) enters, (?:you may )?exile ((?:up to one |another )?target [^.]+?) until "
                    r"(?:~|this \w+) leaves the battlefield", _xl)
    mxb = None if mxu else re.search(
        r"when (?:~|this \w+) enters, (?:you may )?exile ((?:up to one |another )?target [^.]+?)\. ", _xl + " ")
    if mxb and not re.search(r"leaves the battlefield, return the exiled card to the battlefield "
                             r"under its owner's control", _xl):
        mxb = None
    _mx = mxu or mxb
    if _mx and "aura" not in {x.lower() for x in card.subtypes}:
        _d = _mx.group(1)
        _opt = _d.startswith("up to one")
        _opp = bool(re.search(r"an opponent controls|you don't control", _d))
        _tapped = " tapped " in f" {_d} "
        _kinds = set(re.findall(r"\b(creature|artifact|enchantment|planeswalker|land|battle)\b",
                                _d))
        _nonland = "nonland permanent" in _d
        _anyperm = not _kinds and not _nonland
        _mvcap = re.search(r"mana value (\d+) or less", _d)
        _mvcap = int(_mvcap.group(1)) if _mvcap else None

        def _xok(pm, src, ctrl, _k=_kinds, _nl=_nonland, _ap=_anyperm, _o=_opp, _t=_tapped,
                 _cap=_mvcap):
            if pm is src or (_o and pm.controller is ctrl):
                return False
            if _t and not pm.tapped:
                return False
            if _cap is not None and (pm.card.cost.cmc if pm.card.cost else 0) > _cap:
                return False
            if _nl:
                return not pm.card.is_land()
            if _ap:
                return True
            return any((k == "creature" and pm.is_creature()) or
                       (k != "creature" and k in pm.card.types) for k in _k)

        def _exile_until_etb(game, ctrl, perm, _ok=_xok, _optional=_opt):
            pool = [pm for o in game.players for pm in o.battlefield
                    if _ok(pm, perm, ctrl) and game.can_target(ctrl, pm)]
            # el bot apunta a lo del rival (lo más valioso); nunca a lo propio si hay rival
            pool.sort(key=lambda pm: (pm.controller is not ctrl,
                                      (pm.power + pm.toughness) if pm.is_creature()
                                      else (pm.card.cost.cmc if pm.card.cost else 0)),
                      reverse=True)
            if ctrl is not getattr(game, "interactive_human", None):
                pool = [pm for pm in pool if pm.controller is not ctrl] or \
                    ([] if _optional else pool)
            cands = [(f"{pm.name} · {pm.controller.name}", pm) for pm in pool]

            def _do(victim, _src=perm):
                if victim not in victim.controller.battlefield or not game.ward_ok(ctrl, victim):
                    return
                owner = victim.controller
                real = getattr(victim.card, "_real", None) or victim.card
                tok = victim.is_token
                if game.exile_permanent(victim, "exiliada hasta que se vaya"):
                    game.log(f"{ctrl.name}: {_src.name} exilia {victim.name}")
                    if not tok and real in owner.exile:
                        _src._exiled_until = list(getattr(_src, "_exiled_until", None) or []) \
                            + [(owner, real)]
            _human_target_choice(game, ctrl, "etb_target",
                                 "Elegí qué exiliar mientras siga en el campo",
                                 cands, _do, allow_none=_optional)

        def _exile_until_leave(game, ctrl, perm, _prev=card.on_leave):
            for owner, c in list(getattr(perm, "_exiled_until", None) or []):
                if c in owner.exile and not owner.lost:
                    owner.exile.remove(c)
                    game.move_to_battlefield(c, owner)
                    game.log(f"{c.name} vuelve al campo ({perm.name} dejó el campo)")
            perm._exiled_until = None
            if _prev:
                _prev(game, ctrl, perm)
        card.on_etb = _exile_until_etb
        card.on_leave = _exile_until_leave
        card.tags = set(card.tags) | {"removal"}

    # "When you cycle this card, <efecto>"
    for _lc in _ability_lines(data.get("oracle_text", "")):
        mcy = re.match(r"(?i)when you cycle (?:this card|~|" + "|".join(
            re.escape(x) for x in _self_names(name) if x) + r"),\s*(.+)$", _lc.strip())
        if mcy and (_cye := _effect_any(mcy.group(1))) is not None:
            card.cycle_trigger = (lambda g, p, _e=_cye: _e(g, p))
            break
    # "When you cast this spell, <efecto>" (Kozilek: robar 4, Ulamog: destruir, …)
    for _lc in _ability_lines(data.get("oracle_text", "")):
        mcs = re.match(r"(?i)when you cast (?:this spell|~|" + "|".join(
            re.escape(x) for x in _self_names(name) if x) + r"),\s*(.+)$", _lc.strip())
        if mcs:
            _ce = _effect_any(mcs.group(1))
            if _ce is not None:
                card.cast_trigger = (lambda g, p, _e=_ce: _e(g, p))
            break
    # werewolves: "At the beginning of each upkeep, if <hechizos del turno anterior>,
    # transform this creature." (cada cara trae su propia condición)
    mww = re.search(r"at the beginning of each upkeep, if (no spells were cast last turn|a "
                    r"player cast two or more spells last turn), transform (?:this creature|~|it)",
                    _lt)
    if mww and (_wc := _cond_gc(mww.group(1))) is not None:
        def _ww_upkeep(g, perm, _c=_wc, _prev=(card.triggers or {}).get("each_upkeep"), **_kw):
            if _prev:
                _prev(g, perm, **_kw)
            if perm in perm.controller.battlefield and _c(g, perm.controller):
                if g.transform(perm):
                    g.log(f"{perm.name} se transforma (luna llena)")
        card.triggers = dict(card.triggers or {}, each_upkeep=_ww_upkeep)
    # ── batch 4B: undaunted, epic, ripple, impending, paradigm, provoke, recover,
    # demonstrate, eminence, haunt, forecast, cases, MTMTE, bargain en criaturas ──
    _p4l = "\n" + (_pre4 or "").lower()

    def _mcost(txt):
        return parse_cost(mana_cost_to_str("".join(re.findall(r"\{[wubrgc0-9/x]+\}", txt))))
    if "bargain" in _kws_l and not _spell and re.search(r"if it was bargained", _lt):
        card.bargain = True
    if "undaunted" in _kws_l:
        def _undaunted(g, p, _pv=getattr(card, "cost_reduction_fn", None)):
            return len(g.opponents(p)) + (_pv(g, p) if _pv else 0)
        card.cost_reduction_fn = _undaunted
    if _spell:
        card.epic = "epic" in _kws_l
        card.paradigm = "paradigm" in _kws_l
        card.demonstrate = "demonstrate" in _kws_l
        if (mrip := re.search(r"\nripple (\d+)", _p4l)):
            card.ripple = int(mrip.group(1))
    if "provoke" in _kws_l and "creature" in types:
        card.provoke = True
    if "eminence" in _kws_l:
        card.eminence = True
    if (mimp := re.search(r"\nimpending (\d+)\s*[—–-]\s*((?:\{[^}]+\})+)", _p4l)):
        card.impending_n = int(mimp.group(1))
        card.impending_cost = _mcost(mimp.group(2))
    if (mmt := re.search(r"\nmore than meets the eye\s*((?:\{[^}]+\})+)", _p4l)) \
            and getattr(card, "dfc", None) == "transform":
        card.mtmte_cost = _mcost(mmt.group(1))
    # Recover: cuando una criatura va a TU cementerio desde el campo, pagás el
    # coste (vuelve a la mano) o se exilia.
    mrec = re.search(r"\nrecover\s*[—–-]?\s*((?:\{[^}]+\})+|pay half your life)", _p4l)
    if mrec:
        _rc = None if mrec.group(1).startswith("pay") else _mcost(mrec.group(1))

        def _recover(g, pl, c, dying=None, _rc=_rc, _prev=(card.gy_triggers or {}).get("death"),
                     **_kw):
            if _prev:
                _prev(g, pl, c, dying=dying, **_kw)
            if c not in pl.graveyard or dying is None or dying.is_token \
                    or dying.card is c or dying.controller is not pl:
                return
            pl.graveyard.remove(c)
            if _rc is not None and pl.can_pay(_rc):
                pl.pay(_rc)
                pl.hand.append(c)
                g.log(f"{pl.name} paga recover: {c.name} vuelve a la mano")
            elif _rc is None and pl.life > 10:
                pl.life -= (pl.life + 1) // 2
                pl.hand.append(c)
                g.log(f"{pl.name} paga la mitad de su vida: {c.name} vuelve a la mano")
            else:
                pl.exile.append(c)
                g.log(f"{c.name} se exilia (recover sin pagar)")
        card.gy_triggers = dict(card.gy_triggers or {}, death=_recover)
    # Haunt: al morir (criatura) / tras resolver (hechizo) se exilia rondando una
    # criatura; cuando esa muere, se repite el efecto.
    if "haunt" in _kws_l:
        mh = (re.search(r"\nwhen (?:this creature|~|[^,\n]+?) enters or the creature it haunts "
                        r"dies, ([^\n]+)", _p4l)
              or re.search(r"\nwhen the creature (?:this card|it|~) haunts dies, ([^\n]+)", _p4l))
        _heff = _effect_any(mh.group(1)) if mh else None
        if _heff is not None:
            card.haunt = True
            _hf = (lambda g, owner, _e=_heff: _e(g, owner))
            if _spell:
                card.haunt_effect = _hf
            elif "creature" in types:
                def _haunt_die(g, perm, _hf=_hf, _prev=(card.triggers or {}).get("self_to_gy"),
                               **_kw):
                    if _prev:
                        _prev(g, perm, **_kw)
                    own = next((p for p in g.players if perm.card in p.graveyard), None)
                    if own is not None:
                        g._haunt(own, perm.card, _hf)
                card.triggers = dict(card.triggers or {}, self_to_gy=_haunt_die)
    # Forecast — {coste}, reveal this card from your hand: efecto (solo en tu upkeep)
    mfc = re.search(r"\nforecast\s*[—–-]\s*((?:\{[^}]+\})+), reveal (?:this card|~|[^:]+?) "
                    r"from your hand: ([^\n]+)", _p4l)
    if mfc and (_fe := _effect_any(mfc.group(2))) is not None:
        card.forecast = {"cost": _mcost(mfc.group(1)),
                         "effect": (lambda g, p, _e=_fe: _e(g, p))}
    # Case: "To solve — <condición>" se chequea en tu paso final
    if (mcs := re.search(r"\nto solve\s*[—–-]\s*([^\n]+)", _p4l)):
        card.case_cond = _cond_gc(mcs.group(1).strip().rstrip("."))
    if "unleash" in _kws_l and "creature" in types:
        card.unleash = True

        def _unleash_etb(g, ctrl, perm, _prev=card.on_etb):
            human = ctrl is getattr(g, "interactive_human", None)
            if human:
                g.may(ctrl, f"Unleash: ¿{perm.name} entra con un contador +1/+1? "
                            f"(no podrá bloquear)",
                      lambda gg, c: gg.add_counters(perm, "+1/+1", 1))
            else:
                g.add_counters(perm, "+1/+1", 1)
            if _prev:
                _prev(g, ctrl, perm)
        card.on_etb = _unleash_etb
    if re.search(r"\b(?:umbra|totem) armor\b", _lt) or {"umbra armor", "totem armor"} & _kws_l:
        card.umbra_armor = True
    mex = re.search(r"you may exert (?:~|this creature|" + re.escape(name.lower()) +
                    r") as it attacks\. when you do, ([^.]+\.)", _lt)
    if mex:
        _xb = re.sub(r"^it\b", "this creature", mex.group(1).strip())
        _xb = re.sub(r"\bit deals\b", "this creature deals", _xb)
        _xe = _effect_any(_xb)
        if _xe is not None:
            card.exert_effect = (lambda g, ctrl, perm, _e=_xe: _e(g, ctrl, perm))
    if "exploit" in _kws_l and "creature" in types:
        mxp = re.search(r"when (?:~|this creature|" + re.escape(name.lower()) +
                        r") exploits a creature, ([^\n]+)", _lt)
        _xpe = _effect_any(mxp.group(1)) if mxp else None

        def _exploit_etb(g, ctrl, perm, _prev=card.on_etb, _e=_xpe):
            if _prev:
                _prev(g, ctrl, perm)
            g.exploit(ctrl, perm, _e)
        card.on_etb = _exploit_etb

    # ── batch 3: mutate / splice / saddle / station / champion / companion… ──
    if (mtc := _kwcost("mutate")) is not None and "creature" in types:
        card.mutate_cost = mtc
        mmu = re.search(r"whenever (?:this creature|~|" + re.escape(name.lower()) +
                        r") mutates, ([^\n]+)", _lt)
        if mmu and (_me := _effect_any(mmu.group(1))) is not None:
            card.on_mutate = (lambda g, ctrl, perm, _e=_me: _e(g, ctrl, perm))
    msp = re.search(r"(?:^|\n)splice onto (?:arcane|instant or sorcery)[ —–]*((?:\{[wubrgc0-9/x]+\})+)",
                    "\n" + (data.get("oracle_text", "") or "").lower())
    if msp:
        card.splice_cost = parse_cost(mana_cost_to_str("".join(
            re.findall(r"\{[wubrgc0-9/x]+\}", msp.group(1)))))
    msd = re.search(r"(?:^|\n)saddle (\d+)", "\n" + (data.get("oracle_text", "") or "").lower())
    if msd and "creature" in types:
        _sn = int(msd.group(1))
        card.saddle_n = _sn
        card.activated_abilities = tuple(card.activated_abilities or ()) + ({
            "cost": parse_cost("0"), "tap": False, "sacrifice_self": False,
            "sacrifice_other": None, "pay_life": 0, "discard": 0,
            "label": f"Ensillar {_sn}", "target_spec": None, "target_count": 1,
            "is_copy_ability": False, "sorcery_speed": True,
            "effect": (lambda g, ctrl, perm, targets=None, _n=_sn: g.saddle(ctrl, perm, _n)),
        },)
        mws = re.search(r"whenever (?:this creature|~|" + re.escape(name.lower()) +
                        r") attacks while saddled, ([^\n]+)", _lt)
        if mws and (_we := _effect_any(mws.group(1))) is not None:
            def _atk_saddled(g, perm, _e=_we, _prev=(card.triggers or {}).get("attacks"), **kw):
                if _prev is not None:
                    _prev(g, perm, **kw)
                if getattr(perm, "saddled_turn", None) == g.turn:
                    _e(g, perm.controller, perm)
            card.triggers = dict(card.triggers or {})
            card.triggers["attacks"] = _atk_saddled
    if "station" in _kws_l:
        card.station_creature_at = _station_at
        card.activated_abilities = tuple(card.activated_abilities or ()) + ({
            "cost": parse_cost("0"), "tap": False, "sacrifice_self": False,
            "sacrifice_other": None, "pay_life": 0, "discard": 0,
            "label": "Cargar (station)", "target_spec": None, "target_count": 1,
            "is_copy_ability": False, "sorcery_speed": True,
            "effect": (lambda g, ctrl, perm, targets=None: g.station(ctrl, perm)),
        },)
        _ckw = list(getattr(card, "cond_keywords", ()) or ())
        for _thr, _txt in _station_lines:
            _thr = int(_thr)
            _words = [w.strip().lower().replace(" ", "_")
                      for w in re.split(r",\s*(?:and\s+)?|\s+and\s+", _txt.strip().rstrip("."))]
            if _words and all(w in KEYWORDS for w in _words):
                for w in _words:
                    _ckw.append((w, lambda pm, _n=_thr: pm.counters.get("charge", 0) >= _n))
                continue
            for _ab in _parse_activated(_txt, name):
                card.activated_abilities = tuple(card.activated_abilities) + (
                    dict(_ab, station_req=_thr),)
        if _ckw:
            card.cond_keywords = tuple(_ckw)
    mch = re.search(r"(?:^|\n)champion an? ([a-z ]+?)(?:\.|\n|$)", "\n" + (data.get("oracle_text", "") or "").lower())
    if mch and "creature" in types:
        _ck = mch.group(1).strip()

        def _champ_etb(g, ctrl, perm, _k=_ck, _prev=card.on_etb):
            g.champion_etb(ctrl, perm, _k)
            if _prev and perm in ctrl.battlefield:
                _prev(g, ctrl, perm)

        def _champ_leave(g, ctrl, perm, _prev=card.on_leave):
            ch = getattr(perm, "_championed", None)
            if ch:
                cd, owner = ch
                perm._championed = None
                if cd in owner.exile:
                    owner.exile.remove(cd)
                    g.move_to_battlefield(cd, owner)
                    g.log(f"{cd.name} vuelve al campo (champion)")
            if _prev:
                _prev(g, ctrl, perm)
        card.on_etb = _champ_etb
        card.on_leave = _champ_leave
    if "ascend" in _kws_l:
        card.ascend = True
    if (snc := _kwcost("sneak")) is not None and "creature" in types:
        card.ninjutsu_cost = snc
        card.sneak = True
    if "spree" in _kws_l:
        _sm, _scs = [], []
        for _l in (data.get("oracle_text") or "").split("\n"):
            _mm = re.match(r"\s*\+\s*((?:\{[^}]+\})+)\s*[—–-]\s*(.+)$", _l)
            if not _mm:
                continue
            _fe, _fs, _fc = _fragment_effect(_mm.group(2))
            if _fe is None:
                _ge = _effect_any(_mm.group(2))
                if _ge is None:
                    continue
                _fe, _fs, _fc = (lambda g, ctrl, tg, _e=_ge: _e(g, ctrl)), None, 1
            _sm.append({"label": _short_label(_mm.group(2)), "effect": _fe,
                        "target_spec": _fs, "target_count": _fc})
            _scs.append(parse_cost(mana_cost_to_str("".join(
                re.findall(r"\{[^}]+\}", _mm.group(1))))))
        if _sm:
            card.modes = tuple(_sm)
            card.mode_pick = len(_sm)
            card.spree_costs = tuple(_scs)
    if (esc := _kwcost("escalate")) is not None and card.modes:
        card.escalate_cost = esc
        card.mode_pick = len(card.modes)
    maw = re.search(r"(?:^|\n)awaken (\d+)\s*[—–-]\s*((?:\{[wubrgc0-9/x]+\})+)", "\n" + (data.get("oracle_text", "") or "").lower())
    if maw and _spell:
        card.awaken_n = int(maw.group(1))
        card.awaken_cost = parse_cost(mana_cost_to_str("".join(
            re.findall(r"\{[wubrgc0-9/x]+\}", maw.group(2)))))
    if _cleave_txt is not None and (clc := _kwcost("cleave")) is not None and _spell:
        _ct = "\n".join(l for l in _cleave_txt.split("\n") if not re.match(r"(?i)cleave", l.strip()))
        _ce = _generic_amount_effect(_ct)
        if _ce is None:
            _cfe, _cfs, _cfc = _fragment_effect(_ct)
            _ce = (lambda g, ctrl, tg, _f=_cfe: _f(g, ctrl, tg)) if _cfe else None
        else:
            _ce = (lambda g, ctrl, tg, _e=_ce: _e(g, ctrl))
        if _ce is not None:
            card.cleave_cost = clc
            card.cleave_effect = _ce
    if "enlist" in _kws_l:
        card.enlist = True
    if (frc := _kwcost("freerunning")) is not None and card.cost is not None:
        card.alt_costs = tuple(getattr(card, "alt_costs", ()) or ()) + ((
            "freerunning", frc, lambda g, p, c: getattr(p, "_prowl_turn", None) == g.turn
            and bool({"assassin", "commander"} & getattr(p, "prowl_types", set()))),)
        card._printed_cost = card.cost
    if "conspire" in _kws_l:
        card.conspire = True
    if (hmc := _kwcost("harmonize")) is not None:
        card.gy_play = {"mode": "harmonize", "cost": hmc, "after": "exile"}
    if (myc := _kwcost("mayhem")) is not None:
        card.gy_play = {"mode": "mayhem", "cost": myc, "after": "graveyard"}
    mrf = re.search(r"(?:^|\n)reinforce (\d+|x)\s*[—–-]\s*((?:\{[wubrgc0-9/x]+\})+)", "\n" + (data.get("oracle_text", "") or "").lower())
    if mrf and mrf.group(1).isdigit():
        card.reinforce = {"n": int(mrf.group(1)), "cost": parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mrf.group(2)))))}
    if (tmc := _kwcost("transmute")) is not None:
        card.transmute_cost = tmc
    mtr = re.search(r"(?:^|\n)tribute (\d+)", "\n" + (data.get("oracle_text", "") or "").lower())
    if mtr and "creature" in types:
        _tn = int(mtr.group(1))
        mtw = re.search(r"if tribute wasn'?t paid, ([^\n]+)", _lt)
        _te = _effect_any(mtw.group(1)) if mtw else None

        def _tribute_etb(g, ctrl, perm, _n=_tn, _e=_te, _prev=card.on_etb):
            # el rival elige: paga el tributo (contadores) si son pocos
            paid = _n <= 2 or _e is None
            if paid:
                g.add_counters(perm, "+1/+1", _n)
                g.log(f"Un rival paga el tributo: {perm.name} recibe {_n} contador(es)")
            elif _e is not None:
                g.log(f"No se pagó el tributo de {perm.name}")
                _e(g, ctrl, perm)
            if _prev:
                _prev(g, ctrl, perm)
        card.on_etb = _tribute_etb
    if (wsc := _kwcost("web-slinging")) is not None and "creature" in types:
        card.web_slinging_cost = wsc
    mamp = re.search(r"(?:^|\n)amplify (\d+)", "\n" + (data.get("oracle_text", "") or "").lower())
    if mamp and "creature" in types:
        _an = int(mamp.group(1))

        def _amp_etb(g, ctrl, perm, _n=_an, _prev=card.on_etb):
            subs = {x.lower() for x in perm.card.subtypes}
            k = sum(1 for c in ctrl.hand if c.is_creature()
                    and subs & {x.lower() for x in c.subtypes})
            if k:
                g.add_counters(perm, "+1/+1", _n * k)
                g.log(f"{perm.name} amplifica: revela {k} carta(s)")
            if _prev:
                _prev(g, ctrl, perm)
        card.on_etb = _amp_etb
    if "increment" in _kws_l and "creature" in types:
        def _incr(g, perm, card=None, **_kw):
            c = card
            if c is None or perm.controller is None:
                return
            spent = c.cost.cmc if c.cost is not None else 0
            if spent > min(perm.power, perm.toughness):
                g.add_counters(perm, "+1/+1", 1)
        card.triggers = dict(card.triggers or {})
        card.triggers.setdefault("cast", _incr)
    if "ingest" in _kws_l:
        card.keywords = set(card.keywords) | {"ingest"}
    if "start your engines!" in _kws_l:
        card.start_engines = True

        def _engines_etb(g, ctrl, perm, _prev=card.on_etb):
            if not getattr(ctrl, "speed", 0):
                ctrl.speed = 1
                g.log(f"{ctrl.name} arranca motores: velocidad 1")
            if _prev:
                _prev(g, ctrl, perm)
        card.on_etb = _engines_etb
    mgf = re.search(r"(?:^|\n)gift (a card|a food|a treasure|a clue|a tapped fish|an octopus|"
                    r"an extra turn)", "\n" + (data.get("oracle_text", "") or "").lower())
    if mgf:
        card.gift_kind = mgf.group(1).replace("extra turn", "extra turn")

    # Commander ninjutsu: también desde la zona de mando
    if re.search(r"commander ninjutsu", _lt):
        card.commander_ninjutsu = True

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

    # Level up {coste}: habilidad activada que sube de nivel. Aprox: cada nivel
    # suma un contador +1/+1 (la criatura crece; sumidero de maná).
    mlvl = re.search(r"level up ((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if mlvl and "creature" in types:
        lvl_cost = parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", mlvl.group(1)))))

        def _level_up(g, c, perm, tg, *_a):
            if perm is not None:
                g.add_counters(perm, "+1/+1", 1)
                perm.counters["level"] = perm.counters.get("level", 0) + 1
                g.log(f"{perm.name} sube de nivel ({perm.counters['level']})")
        card.activated_abilities = tuple(card.activated_abilities) + ({
            "cost": lvl_cost, "tap": False, "sacrifice_self": False,
            "sacrifice_other": None, "pay_life": 0, "discard": 0,
            "label": "Level up", "effect": _level_up,
            "target_spec": None, "target_count": 1, "is_copy_ability": False},)

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

    # palabras de habilidad / eventos propios (constellation, enrage, heroic…)
    _mte = _misc_trigger_effects(data.get("oracle_text", ""), name)
    _ex_etb = _mte.pop("__etb_self", None)
    if _ex_etb is not None:
        def _etb_chain(g, ctrl, perm, _cb=_ex_etb, _prev=card.on_etb):
            if _prev:
                _prev(g, ctrl, perm)
            _cb(g, ctrl, perm)
        card.on_etb = _etb_chain
    _lv = _mte.pop("__leave", None)
    if _lv is not None:
        def _leave_chain(g, ctrl, perm, _cb=_lv, _prev=card.on_leave):
            if _prev:
                _prev(g, ctrl, perm)
            g._run_trigger(_cb, perm, {})
        card.on_leave = _leave_chain
    if _mte:
        card.triggers = dict(card.triggers)
        for ev, cb in _mte.items():
            card.triggers.setdefault(ev, cb)

    # disparos por evento: muerte de criatura, daño de combate a jugador, magecraft.
    evs = _event_trigger_effect(data.get("oracle_text", ""))
    if evs:
        card.triggers = dict(card.triggers)
        for ev, cb in evs.items():
            card.triggers.setdefault(ev, cb)
    # Clase: los disparos que aparecen en un NIVEL >= 2 solo funcionan desde ese
    # nivel (antes Gourmand's Talent creaba Raccoons en nivel 1)
    for _lvl, _body in sorted((getattr(card, "_class_segments", None) or {}).items()):
        if _lvl < 2:
            continue
        for _ev in list(_event_trigger_effect(_body)) + list(_recurring_trigger_effects(_body)):
            cb0 = (card.triggers or {}).get(_ev)
            if cb0 is None or getattr(cb0, "_class_gated", False):
                continue

            def _gated(g, perm, *a, _cb=cb0, _n=_lvl, **kw):
                if perm.counters.get("level", 1) >= _n:
                    return _cb(g, perm, *a, **kw)
            _gated._class_gated = True
            card.triggers = dict(card.triggers)
            card.triggers[_ev] = _gated

    # "no puede ser bloqueada" (incondicional) -> keyword unblockable
    _ot = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    # solo si el SUJETO es esta carta: "Target creature can't be blocked this turn"
    # (Whirler Rogue, activada) volvía imbloqueable a la propia carta
    _names = _self_names(name)
    for _l in _ability_lines(data.get("oracle_text", "")):
        _mu = re.match(r"(.+?) can't be blocked\.?$", _l, re.I)
        if _mu and (_mu.group(1).lower() in _names
                    or _mu.group(1).lower() in ("this creature", "~")):
            card.keywords = set(card.keywords) | {"unblockable"}
            break

    # ── batch 5: restricciones, evasión y reglas de turno estáticas ──────────
    _subj5 = r"(?:this creature|this enchantment|this artifact|this land|this permanent|~|it|" + \
        "|".join(re.escape(n) for n in _names if n) + r")"
    for _l in _ability_lines(data.get("oracle_text", "")):
        _l5 = _strip_reminder(_l).strip().lower().rstrip(".")
        if re.fullmatch(_subj5 + r" attacks each (?:combat|turn) if able", _l5):
            card.attacks_each_combat = True
        elif re.fullmatch(_subj5 + r" (?:doesn't|does not) untap during your untap step", _l5):
            card.no_untap_self = True
        elif re.fullmatch(_subj5 + r" can't attack", _l5):
            card.cant_attack_static = True
        elif re.fullmatch(_subj5 + r" can't attack or block", _l5):
            card.cant_attack_static = True
            card.cant_block_static = True
        elif (m5 := re.fullmatch(_subj5 + r" can't attack unless defending player controls "
                                 r"an? (island|swamp|forest|mountain|plains)", _l5)):
            card.attack_needs_land = m5.group(1).capitalize()
        elif (m5 := re.fullmatch(_subj5 + r" can't be blocked by creatures with power (\d+) "
                                 r"or (less|greater)", _l5)):
            if m5.group(2) == "less":
                card.unblock_power_le = int(m5.group(1))
            else:
                card.unblock_power_ge = int(m5.group(1))
        elif re.fullmatch(r"creatures with power less than " + _subj5 + r"(?:'s)? power can't "
                          r"block it", _l5):
            card.unblock_power_lt_self = True
        elif (m5 := re.fullmatch(_subj5 + r" can't be blocked by more than (\w+) creatures?", _l5)):
            card.max_blockers = _count_word(m5.group(1)) or 1
        elif re.fullmatch(r"at the beginning of (?:the|each|your) end step, return " + _subj5 +
                          r" to its owner's hand", _l5):
            _ev6 = "end_step" if "your end step" in _l5 else "each_end_step"

            def _eot_bounce(g, perm, _prev=(card.triggers or {}).get(_ev6), **_kw):
                if _prev:
                    _prev(g, perm, **_kw)
                pl = perm.controller
                if perm in pl.battlefield:
                    pl.battlefield.remove(perm)
                    if perm.card.on_leave:
                        perm.card.on_leave(g, pl, perm)
                    if not perm.is_token:
                        owner = g.commander_owner(perm.card)
                        (owner.command if owner else pl.hand).append(
                            getattr(perm.card, "_real", None) or perm.card)
                    g.log(f"{perm.name} vuelve a la mano al final del turno")
            card.triggers = dict(card.triggers or {}, **{_ev6: _eot_bounce})
        elif (m6 := re.fullmatch(r"at the beginning of your upkeep, sacrifice " + _subj5 +
                                 r" unless you pay ((?:\{[wubrgc0-9/]+\})+)", _l5)):
            _uc = parse_cost(mana_cost_to_str(m6.group(1)))

            def _upk_tax(g, perm, _c=_uc, _prev=(card.triggers or {}).get("upkeep"), **_kw):
                if _prev:
                    _prev(g, perm, **_kw)
                pl = perm.controller
                if perm not in pl.battlefield:
                    return
                if pl.can_pay(_c):
                    pl.pay(_c)
                    g.log(f"{pl.name} paga el mantenimiento de {perm.name}")
                else:
                    g.log(f"{perm.name} se sacrifica (no pagó su mantenimiento)")
                    g.to_graveyard(perm, "mantenimiento impago")
            card.triggers = dict(card.triggers or {}, upkeep=_upk_tax)
        elif (m6 := re.fullmatch(r"at the beginning of your upkeep, " + _subj5 +
                                 r" deals (\w+) damage to you", _l5)) and _count_word(m6.group(1)):
            def _upk_dmg(g, perm, _n=_count_word(m6.group(1)),
                         _prev=(card.triggers or {}).get("upkeep"), **_kw):
                if _prev:
                    _prev(g, perm, **_kw)
                g.deal_damage(perm, perm.controller, _n)
            card.triggers = dict(card.triggers or {}, upkeep=_upk_dmg)
        elif (m6 := re.fullmatch(r"when you control no (islands|swamps|forests|mountains|plains), "
                                 r"sacrifice " + _subj5, _l5)):
            card.sac_without_land = {"islands": "Island", "swamps": "Swamp", "forests": "Forest",
                                     "mountains": "Mountain", "plains": "Plains"}[m6.group(1)]
        elif (m6 := re.fullmatch(_subj5 + r" is also an? ([a-z]+(?:(?:,| and|, and) an? [a-z]+|(?:,| and|, and) [a-z]+)*)",
                                 _l5)):
            _st6 = [w.strip().capitalize() for w in re.split(r",\s*(?:and\s+)?|\s+and\s+", m6.group(1))]
            _st6 = [re.sub(r"^An? ", "", w).capitalize() for w in _st6 if w]
            card.subtypes = tuple(dict.fromkeys(tuple(card.subtypes) + tuple(_st6)))
        elif re.fullmatch(_subj5 + r" blocks each combat if able", _l5):
            card.must_block_each = True
        elif (m6 := re.fullmatch(r"spells you cast from (your graveyard|exile|anywhere other than your hand|"
                                 r"your graveyard or from exile) cost \{(\d+)\} less to cast", _l5)):
            def _f20z(c, pl, g, _z=m6.group(1)):
                zn = getattr(c, "_cast_zone", None)
                if _z == "your graveyard":
                    return zn == "graveyard" or c in pl.graveyard
                if _z == "exile":
                    return zn == "exile" or c in pl.exile
                if _z == "your graveyard or from exile":
                    return zn in ("graveyard", "exile") or c in pl.graveyard or c in pl.exile
                return c not in pl.hand
            _f20z._wp = True
            if getattr(card, "spell_discount", None) is None:
                card.spell_discount = (int(m6.group(2)), _f20z)
        elif (m6 := re.fullmatch(_subj5 + r" can't (attack|block|attack or block) (unless|if) (.+)", _l5)) and \
                (_gc6 := _cond_gc(re.sub(r"\b(?:defending|attacking) player\b", "an opponent", m6.group(3)))) is not None:
            _neg6 = m6.group(2) == "unless"
            _cf6 = (lambda pm, _c=_gc6, _n=_neg6: (not _cond_eval(_c, pm)) if _n else _cond_eval(_c, pm))
            if "attack" in m6.group(1):
                card.cant_attack_if = _cf6
            if "block" in m6.group(1):
                card.cant_block_if = _cf6
        elif (m6 := re.fullmatch(r"if (a source|a source an opponent controls|a source you don't control|a creature|"
                                 r"a creature an opponent controls|an? (?:red|blue|black|white|green) source) would deal "
                                 r"(combat |noncombat |)damage to (you|this creature|~|creatures you control|enchanted creature|"
                                 r"you or a permanent you control|you or another permanent you control), prevent (\w+) of that "
                                 r"damage", _l5)) and _count_word(m6.group(4)):
            card.prevent_static = tuple(getattr(card, "prevent_static", ()) or ()) + (
                (m6.group(3), _count_word(m6.group(4)), m6.group(1), m6.group(2).strip()),)
        elif (m6 := re.fullmatch(r"prevent all (combat |noncombat |)damage that would be dealt to (you|this creature|~|"
                                 r"creatures you control|enchanted creature|you and permanents you control|other creatures "
                                 r"you control)(?: by (artifact sources|artifact creatures|creatures|black sources|red sources|"
                                 r"white sources|blue sources|green sources|sources your opponents control|[a-z]+ creatures))?",
                                 _l5)):
            card.prevent_static = tuple(getattr(card, "prevent_static", ()) or ()) + (
                (m6.group(2), 10 ** 6, m6.group(3) or "a source", m6.group(1).strip()),)
        elif re.fullmatch(_subj5 + r" can't have counters put on it", _l5):
            card.no_counters = True
        elif re.fullmatch(_subj5 + r" can't block alone", _l5):
            card.cant_block_alone = True
        elif (m6 := re.fullmatch(_subj5 + r" can't block (white|blue|black|red|green|artifact) creatures", _l5)):
            card.cant_block_kind = m6.group(1)
        elif re.fullmatch(_subj5 + r" can block only creatures with flying", _l5):
            card.block_only_flying = True
        elif (m6 := re.fullmatch(_subj5 + r" can't be blocked except by ([a-z]+)s?", _l5)) and \
                m6.group(1) not in ("two", "three", "creature", "creatures"):
            card.unblock_except_sub = m6.group(1)
        elif (m6 := re.fullmatch(_subj5 + r" can't be blocked except by (white|blue|black|red|green) creatures", _l5)):
            card.unblock_except_color = _COLOR_W[m6.group(1)]
        elif re.fullmatch(_subj5 + r" can't be blocked by tokens", _l5):
            card.unblock_by_tokens = True
        elif re.fullmatch(_subj5 + r" can't be blocked by creatures with flying", _l5):
            card.unblock_by_flying = True
        elif re.fullmatch(_subj5 + r" can't be blocked by creatures with greater power", _l5):
            card.unblock_power_gt_self = True
        elif (m6 := re.fullmatch(_subj5 + r" can't block creatures with power (\d+) or less", _l5)):
            card.cant_block_pow_le = int(m6.group(1))
        elif (m6 := re.fullmatch(_subj5 + r" can't block creatures with power (\d+) or greater", _l5)):
            card.cant_block_pow_ge = int(m6.group(1))
        elif re.fullmatch(_subj5 + r" can't be blocked as long as it's attacking alone", _l5):
            card.unblock_alone = True
        elif re.fullmatch(_subj5 + r" attacks or blocks each combat if able", _l5):
            card.attacks_each_combat = True
            card.must_block_each = True
        elif _l5 == "all creatures block each combat if able":
            card.global_must_block = True
        elif _l5 in ('the "legend rule" doesn\'t apply to permanents you control',
                     "the “legend rule” doesn't apply to permanents you control"):
            card.no_legend_rule = True
        elif _l5 == "you can't cast creature spells":
            card.self_no_creature_cast = True
        elif re.fullmatch(r"if you would get (?:one or more|\w+ or more) \{e\}(?: \(energy counters\))?, you get twice "
                          r"that many \{e\} instead", _l5):
            card.energy_double = True
        elif (m6 := re.fullmatch(r"(nontoken |other |other nontoken |)creatures you control have riot", _l5)):
            card.grant_riot = m6.group(1).strip() or "all"
        elif _l5 == "you can't cast noncreature spells":
            card.self_no_noncreature_cast = True
        elif (m6 := re.fullmatch(r"your maximum hand size is (\w+)", _l5)) and _count_word(m6.group(1)):
            card.max_hand_set = _count_word(m6.group(1))
        elif _l5 == "players can't play lands":
            card.global_no_lands = True
        elif (m6 := re.fullmatch(r"during turns other than yours, spells you cast cost \{(\d+)\} less to cast", _l5)):
            def _f20o(c, pl, g):
                return bool(g.players) and g.players[g.active_index] is not pl
            _f20o._wp = True
            if getattr(card, "spell_discount", None) is None:
                card.spell_discount = (int(m6.group(1)), _f20o)
        elif re.fullmatch(_subj5 + r" can't be blocked except by two or more creatures", _l5):
            card.keywords = set(card.keywords) | {"menace"}
        elif (m6 := re.fullmatch(_subj5 + r" gets ([+-]\d+)/([+-]\d+) for each (?:aura (?:and|or|and/or) equipment|"
                                 r"equipment (?:and|or) aura) attached to it", _l5)):
            def _sm6a(src, target, _a=int(m6.group(1)), _b=int(m6.group(2)), _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if target is src and getattr(src, "game", None) is not None:
                    n = sum(1 for x in src.game.all_permanents() if getattr(x, "enchanting", None) is src)
                    return (base[0] + _a * n, base[1] + _b * n)
                return base
            card.static_mod = _sm6a
        elif (m6 := re.fullmatch(_subj5 + r" gets ([+-]\d+)/([+-]\d+) for each (?!(?:equipment|aura) attached "
                                 r"to it$|other [a-z]+ you control$|[a-z+/1]+ counter on (?:it|~|this creature)$)(.+)", _l5)):
            _cf6 = (_count_fn(m6.group(3)) or _count_fn(re.sub(r"^(\w+)", r"\1s", m6.group(3)))
                    or _count_fn("the number of " + re.sub(r"^(\w+)", r"\1s", m6.group(3))))
            if _cf6 is not None:
                def _sm6(src, target, _a=int(m6.group(1)), _b=int(m6.group(2)), _f=_cf6,
                         _p=card.static_mod):
                    base = _p(src, target) if _p else (0, 0)
                    if target is src and getattr(src, "game", None) is not None:
                        n = _f(src.game, src.controller)
                        return (base[0] + _a * n, base[1] + _b * n)
                    return base
                card.static_mod = _sm6
        elif re.fullmatch(r"if this card is in your opening hand, you may begin the game with "
                          r"it on the battlefield", _l5):
            card.leyline = True
        elif re.fullmatch(r"when " + _subj5 + r" becomes the target of a spell or ability, "
                          r"sacrifice it", _l5):
            card.sac_when_targeted = True
        elif re.fullmatch(r"all creatures able to block " + _subj5 + r" do so", _l5):
            card.lure_all = True
        elif re.fullmatch(_subj5 + r" must be blocked if able", _l5) or \
                re.fullmatch(_subj5 + r" must be blocked each combat if able", _l5):
            card.must_be_blocked = True
        elif (m9 := re.fullmatch(r"if an? (artifact or creature|permanent|creature|nontoken creature) "
                                 r"entering(?: the battlefield)? causes a triggered ability of a "
                                 r"permanent you control to trigger, that ability triggers an "
                                 r"additional time", _l5)):
            card.etb_double = {"artifact or creature": "artifact_creature",
                               "permanent": "permanent"}.get(m9.group(1), "creature")
        elif re.fullmatch(r"if a creature dying causes a triggered ability of a permanent you "
                          r"control to trigger, that ability triggers an additional time", _l5):
            card.death_double = True
        elif (m12 := re.fullmatch(r"whenever enchanted (?:land|forest|plains|island|swamp|mountain) "
                                  r"is tapped for mana, its controller adds an additional "
                                  r"(.+?)(?: of any color| of the chosen color| in any combination "
                                  r"of colors| of any type that land produced)?", _l5)):
            _amt = m12.group(1)
            _syms = re.findall(r"\{[wubrgc]\}", _amt)
            mn = re.match(r"(one|two|three|\w+) mana", _amt)
            card.land_mana_bonus = len(_syms) or (_count_word(mn.group(1)) if mn else 1) or 1
        elif re.fullmatch(r"whenever you tap a land for mana, add (?:one|an additional) mana of any "
                          r"type that land produced", _l5):
            card.your_land_bonus = 1
        elif re.fullmatch(r"whenever a player taps a land for mana, that player adds (?:one|an "
                          r"additional) mana of any type that land produced", _l5):
            card.any_land_bonus = 1
        elif re.fullmatch(r"if you tap a permanent for mana, it produces (twice|three times) as "
                          r"much of that mana instead", _l5):
            card.mana_mult = 2 if "twice" in _l5 else 3
        elif re.fullmatch(r"each creature (?:you control )?assigns combat damage equal to its toughness "
                          r"rather than its power", _l5):
            card.toughness_damage = "you" if "you control" in _l5 else "all"
        elif re.fullmatch(r"each creature you control with toughness greater than its power assigns "
                          r"combat damage equal to its toughness rather than its power", _l5):
            card.toughness_damage = "you_tough"
        elif (m13 := re.fullmatch(r"creatures can't attack you(?: or planeswalkers you control)? unless "
                                  r"their controller pays \{(\d+|w/p|x)\} for each (?:creature they control "
                                  r"that's attacking you|of those creatures)(, where x is the number of enchantments "
                                  r"you control)?", _l5)):
            if m13.group(1) == "x":
                card.attack_tax_ench = True
            else:
                card.attack_tax = 1 if m13.group(1) == "w/p" else int(m13.group(1))
        elif re.fullmatch(_subj5 + r" can't attack(?: or block)? alone", _l5):
            card.attack_not_alone = True
        elif _l5 in ("you can't lose the game and your opponents can't win the game",
                     "you can't lose the game"):
            card.cant_lose = True
        elif re.fullmatch(r"you don't lose the game for having 0 or less life", _l5):
            card.no_life_loss = True
        elif _l5 == "damage can't be prevented":
            card.no_prevention_static = True
        elif (m13 := re.fullmatch(r"(white|blue|black|red|green|nonwhite|nonblue|nonblack|nonred|"
                                  r"nongreen|multicolored|colorless) creatures(?: you control)? get "
                                  r"([+-]\d+)/([+-]\d+)", _l5)):
            _col13 = m13.group(1)
            _mine13 = "you control" in _l5

            def _sm13(src, target, _c=_col13, _m=_mine13, _a=int(m13.group(2)), _b=int(m13.group(3)),
                      _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if _m and target.controller is not src.controller:
                    return base
                cols = set()
                for pp in (getattr(target.card.cost, "pips", None) or ()):
                    cols |= {x for x in str(pp).upper() if x in "WUBRG"}
                cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
                if _c in cm:
                    ok = cm[_c] in cols
                elif _c.startswith("non") and _c[3:] in cm:
                    ok = cm[_c[3:]] not in cols
                elif _c == "multicolored":
                    ok = len(cols) >= 2
                else:
                    ok = not cols
                return (base[0] + _a, base[1] + _b) if ok else base
            card.static_mod = _sm13
        elif re.fullmatch(r"you may play lands from your graveyard", _l5):
            card.play_lands_gy = True
        elif re.fullmatch(r"you may play lands from the top of your library", _l5) or \
                re.fullmatch(r"you may play the top card of your library if it's a land", _l5):
            card.play_lands_top = True
        elif (m14 := re.fullmatch(r"soulshift (\d+)", _l5)):
            _ss = int(m14.group(1))

            def _soulshift(g, ctrl, perm, _n=_ss, _prev=card.on_death):
                r = _prev(g, ctrl, perm) if _prev else None
                pool = [c for c in ctrl.graveyard if c is not perm.card
                        and any(x.lower() == "spirit" for x in c.subtypes)
                        and (c.cost.cmc if c.cost else 0) <= _n]
                if pool:
                    c = max(pool, key=lambda x: x.cost.cmc if x.cost else 0)
                    ctrl.graveyard.remove(c)
                    ctrl.hand.append(c)
                    g.log(f"Soulshift: {c.name} vuelve a la mano de {ctrl.name}")
                return r
            card.on_death = _soulshift
        elif (m14 := re.fullmatch(r"fabricate (\d+)", _l5)):
            def _fabricate(g, ctrl, perm, _n=int(m14.group(1)), _prev=card.on_etb):
                if _prev:
                    _prev(g, ctrl, perm)
                # bot: contadores si la criatura ya es buena; fichas Servo si conviene ancho
                if perm.power >= 2 or len(ctrl.creatures()) <= 2:
                    g.add_counters(perm, "+1/+1", _n)
                else:
                    for _ in range(_n):
                        tk = cards.make_token(g, ctrl, "Servo", 1, 1, subtypes=("Servo",))
                        if tk is not None:
                            tk.card.types = set(tk.card.types) | {"artifact"}
            card.on_etb = _fabricate
        elif re.fullmatch(r"cast this spell only (?:during combat|during the declare (?:attackers|"
                          r"blockers) step|during combat (?:before|after) blockers are declared)"
                          r"(?: and only if [^.]+)?", _l5):
            card.combat_only = True
        elif (m14 := (re.fullmatch(r"each (?:other )?creature you control with an? (\+1/\+1|[a-z]+) counter "
                                   r"on it has ([a-z ,]+)", _l5)
                      or re.fullmatch(r"(?:other )?creatures you control with (\+1/\+1 |[a-z]+ |)counters "
                                      r"on them have ([a-z ,]+)", _l5))):
            _ck = [k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+",
                                                                  m14.group(2)) if k.strip()]
            if _ck and all(k in KEYWORDS for k in _ck):
                card.counter_grants = (m14.group(1).strip() or "any", tuple(_ck))
        elif (m14 := re.fullmatch(r"each player can't cast more than (\w+) spells? each turn", _l5)):
            card.spell_limit = _count_word(m14.group(1)) or 1
        elif re.fullmatch(r"if damage would be dealt to " + _subj5 + r", prevent that damage\. remove a "
                          r"\+1/\+1 counter from " + _subj5, _l5):
            card.phantom = True
        elif re.fullmatch(r"you may have " + _subj5 + r" assign its combat damage as though it "
                          r"weren't blocked", _l5):
            card.unblocked_damage = True
        elif (m14 := re.fullmatch(_subj5 + r" gets \+(\d+)/\+(\d+) for each ([a-z+/1]+) counter on "
                                  r"(?:it|~|this creature)", _l5)):
            def _sm14(src, target, _a=int(m14.group(1)), _b=int(m14.group(2)), _k=m14.group(3),
                      _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if target is src:
                    n = src.counters.get(_k, 0)
                    return (base[0] + _a * n, base[1] + _b * n)
                return base
            card.static_mod = _sm14
        elif (m14 := re.fullmatch(_subj5 + r" can block (an additional|any number of|(\w+) additional) "
                                  r"creatures?(?: each combat)?", _l5)):
            card.extra_blocks = (99 if "any number" in _l5 else
                                 _count_word(m14.group(2)) if m14.group(2) else 1) or 1
        elif (m14 := re.fullmatch(r"as long as your devotion to ([a-z]+)(?: and ([a-z]+))? is less than "
                                  r"(\w+), " + _subj5 + r" isn't a creature", _l5)):
            _cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
            cols = frozenset(_cm[x] for x in (m14.group(1), m14.group(2)) if x in _cm)
            card.devotion_req = (cols, _count_word(m14.group(3)) or 5)
        elif (m15 := re.fullmatch(r"you may (?:play lands and )?cast (creature|artifact|enchantment|instant and "
                                  r"sorcery|noncreature)? ?spells from the top of your library", _l5)):
            card.cast_top = {"creature": "creature", "artifact": "artifact",
                             "enchantment": "enchantment"}.get(m15.group(1) or "", "any")
            if "play lands" in _l5:
                card.play_lands_top = True
        elif re.fullmatch(r"you may cast (?:this card|~) from your graveyard", _l5) and \
                card.cost is not None and not getattr(card, "gy_play", None):
            card.gy_play = {"mode": "gy_cast", "cost": card.cost, "after": "graveyard"}
        elif (m15 := re.fullmatch(r"you may cast (?:this card|~) from your graveyard (?:if|as long as) (.+)", _l5)) and \
                card.cost is not None and not getattr(card, "gy_play", None) and \
                (_gc15 := _cond_gc(m15.group(1))) is not None:
            card.gy_play = {"mode": "gy_cast", "cost": card.cost, "after": "graveyard", "cond": _gc15}
        elif (m15 := re.fullmatch(r"you may cast ([a-z]+(?:(?:,| and|, and) [a-z]+)*) spells from the top of your library", _l5)) \
                and not getattr(card, "cast_top", None):
            _ks15 = [_sing(x.strip() + "s") for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", m15.group(1)) if x.strip()]
            card.cast_top = "sub:" + "|".join(_ks15)
        elif (m15 := re.fullmatch(r"the (first|second) (creature |noncreature |instant or sorcery |)spell you cast "
                                  r"each turn costs \{(\d+)\} less to cast", _l5)):
            _nth = 1 if m15.group(1) == "first" else 2
            _sk = m15.group(2).strip()

            def _f15(c, pl, g, _n=_nth, _k=_sk):
                if _k == "creature":
                    if not c.is_creature():
                        return False
                    ct = getattr(pl, "_cr_cast", None)
                    done = ct[1] if ct and ct[0] == g.turn else 0
                    return done == _n - 1
                if _k == "noncreature" and c.is_creature():
                    return False
                if _k == "instant or sorcery" and not ({"instant", "sorcery"} & c.types):
                    return False
                return getattr(pl, "spells_cast_turn", 0) == _n - 1
            _f15._wp = True
            card.spell_discount = (int(m15.group(3)), _f15)
        elif _l5 in ("each player may play an additional land on each of their turns",
                     "each player may play an additional land during each of their turns"):
            card.extra_land_all = 1
        elif _l5 == "untap all permanents you control during each other player's untap step":
            card.seedborn = True
        elif re.fullmatch(r"prevent all combat damage that would be dealt to and dealt by " + _subj5, _l5):
            card.prevent_combat_to = True
            card.prevent_combat_from = True
        elif re.fullmatch(r"creatures with power less than " + _subj5 + r"(?:'s)? power can't block creatures "
                          r"you control", _l5):
            card.lambholt = True
        elif re.fullmatch(r"(?:when|whenever) " + _subj5 + r" is put into a graveyard from the battlefield, "
                          r"return (?:it|~|this card) to its owner's hand", _l5):
            def _spine(game, perm, _c=card, **_kw):
                for pl in game.players:
                    real = getattr(_c, "_real", None) or _c
                    if real in pl.graveyard:
                        pl.graveyard.remove(real)
                        pl.hand.append(real)
                        game.log(f"{real.name} vuelve a la mano")
                        return
            card.triggers = dict(card.triggers or {})
            card.triggers.setdefault("self_to_gy", _spine)
        elif (m16 := re.fullmatch(r"(?:metalcraft — |[a-z ]+ — )?(other )?(creatures|creature tokens|[a-z]+?s)"
                                  r"( you control| your opponents control) (?:also )?get "
                                  r"([+-]\d+)/([+-]\d+)(?: and have ([a-z ,]+?))? as long as (.+)", _l5)) \
                and _cond_gc(m16.group(7)) is not None \
                and all(k.strip().replace(" ", "_") in KEYWORDS for k in re.split(r",\s*(?:and\s+)?|\s+and\s+",
                                                                              m16.group(6) or "") if k.strip()):
            _g16 = m16.group(2)
            _sb16 = None if _g16 in ("creatures", "creature tokens") else _sing(_g16)

            def _sm16(src, target, _o=bool(m16.group(1)), _a=int(m16.group(4)), _b=int(m16.group(5)),
                      _c=_cond_gc(m16.group(7)), _p=card.static_mod, _sb=_sb16, _tk=_g16 == "creature tokens",
                      _opp="opponents" in m16.group(3)):
                base = _p(src, target) if _p else (0, 0)
                if not target.is_creature() or (target.controller is src.controller) == _opp or (_o and target is src):
                    return base
                if (_sb and not target.has_subtype(_sb)) or (_tk and not target.is_token):
                    return base
                return (base[0] + _a, base[1] + _b) if _cond_eval(_c, src) else base
            card.static_mod = _sm16
            if m16.group(6):
                card.cond_anthem_kw = tuple(getattr(card, "cond_anthem_kw", ()) or ()) + ((
                    bool(m16.group(1)), _sb16, "opp" if "opponents" in m16.group(3) else "you",
                    frozenset(k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+", m16.group(6))
                              if k.strip()), _cond_gc(m16.group(7))),)
        elif (m16 := re.fullmatch(r"(?:[a-z ]+ — )?(other )?(creatures|permanents|artifacts|creature tokens|[a-z]+?s)"
                                  r"( you control| your opponents control)? have ([a-z ,]+?) as long as (.+)", _l5)) \
                and _cond_gc(m16.group(5)) is not None \
                and all(k.strip().replace(" ", "_") in KEYWORDS for k in re.split(r",\s*(?:and\s+)?|\s+and\s+",
                                                                              m16.group(4)) if k.strip()):
            _g16 = m16.group(2)
            card.cond_anthem_kw = tuple(getattr(card, "cond_anthem_kw", ()) or ()) + ((
                bool(m16.group(1)), None if _g16 in ("creatures", "permanents", "artifacts", "creature tokens")
                else _sing(_g16), "opp" if "opponents" in (m16.group(3) or "") else "you",
                frozenset(k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+", m16.group(4))
                          if k.strip()), _cond_gc(m16.group(5))),)
        elif _l5 == "lands you control are every basic land type in addition to their other types":
            card.all_basic_types = True
        elif _l5.startswith("if one or more creature tokens would be created under your control, that many 4/4 "
                            "white angel creature tokens with flying and vigilance are created instead"):
            card.token_angels = True
        elif (m17 := re.fullmatch(r"this spell costs \{x\} less to cast, where x is (.+)", _l5)) and \
                (_cf17 := _count_fn(m17.group(1))) is not None:
            card.cost_reduction_fn = (lambda g, p, _f=_cf17: _f(g, p))
        elif (m17 := re.fullmatch(r"you may cast this card from your graveyard as long as you control an? (\w+)", _l5)) \
                and card.cost is not None and not getattr(card, "gy_play", None):
            card.gy_play = {"mode": "gy_cast", "cost": card.cost, "after": "graveyard"}
        elif _l5 in ("all creatures attack each combat if able", "creatures your opponents control attack each "
                     "combat if able", "all creatures have double strike and attack each combat if able"):
            card.forced_attack = "opp" if "opponents" in _l5 else "all"
            if "double strike" in _l5:
                card.global_keywords = tuple(getattr(card, "global_keywords", None) or ()) + (("double_strike", None),)
        elif (m17 := re.fullmatch(r"(?:[a-z ]+ — )?as long as (.+?), you may (play lands|cast creature spells|play "
                                  r"lands and cast spells) from the top of your library", _l5)) \
                and _cond_gc(m17.group(1)) is not None:
            card.cast_top_cond = _cond_gc(m17.group(1))
            if "play lands" in m17.group(2):
                card.play_lands_top = True
            if "cast" in m17.group(2):
                card.cast_top = "creature" if "creature" in m17.group(2) else "any"
        elif (m17 := re.fullmatch(r"(?:[a-z ]+ — )?as long as (.+?), " + _subj5 + r" gets ([+-]\d+)/([+-]\d+)"
                                  r"(?: and creatures you control have ([a-z ]+))?", _l5)) \
                and _cond_gc(m17.group(1)) is not None:
            _c17 = _cond_gc(m17.group(1))

            def _sm17(src, target, _c=_c17, _a=int(m17.group(2)), _b=int(m17.group(3)), _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if target is src:
                    try:
                        ok = src.game is not None and _c(src.game, src.controller)
                    except Exception:  # noqa: BLE001
                        ok = False
                    if ok:
                        return (base[0] + _a, base[1] + _b)
                return base
            card.static_mod = _sm17
        elif (m18 := re.fullmatch(r"each other (non-human )?creature you control enters with (?:an additional \+1/\+1 "
                                  r"counter|a number of additional \+1/\+1 counters on it equal to (?:this creature|~)'s "
                                  r"power)(?: on it)?.*", _l5)):
            card.etb_counter_bonus = (("nonhuman", 1) if m18.group(1) else
                                      ("power", 0) if "equal to" in _l5 else ("flat", 1))
        elif _l5.startswith("if you would create a clue, food, or treasure token, instead create one of each"):
            card.manufactor = True
        elif (m19 := re.fullmatch(r"(white|blue|black|red|green) creatures can't block", _l5)):
            card.no_block_color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m19.group(1)]
        elif re.fullmatch(r"creatures you control with power or toughness (\d+) or less can't be blocked", _l5):
            card.global_unblock_small = int(re.search(r"(\d+)", _l5).group(1))
        elif _l5 in ("you have hexproof", "you have shroud"):
            card.player_hexproof = True
        elif (m15 := re.fullmatch(_subj5 + r" can't be blocked except by creatures with ([a-z ]+?)", _l5)):
            card.unblock_except = frozenset(
                k.strip().replace(" ", "_") for k in re.split(r",| or |and/or", m15.group(1)) if k.strip())
        elif (m15 := re.fullmatch(_subj5 + r" can't be blocked by (white|blue|black|red|green|artifact|"
                                  r"enchantment)(?: (?:and|or) (white|blue|black|red|green))? creatures", _l5)):
            _cm = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
            if m15.group(1) in _cm:
                card.unblock_by_kind = ("color", frozenset(_cm[x] for x in (m15.group(1), m15.group(2)) if x))
            else:
                card.unblock_by_kind = ("type", m15.group(1))
        elif (m15 := re.fullmatch(r"(your|each opponent's) maximum hand size is (reduced|increased) by (\w+)",
                                  _l5)) and _count_word(m15.group(3)):
            _d = _count_word(m15.group(3)) * (-1 if m15.group(2) == "reduced" else 1)
            card.hand_size_mod = ("you" if m15.group(1) == "your" else "opp", "add", _d)
        elif (m15 := re.fullmatch(r"your maximum hand size is (\w+)", _l5)) and _count_word(m15.group(1)) is not None:
            card.hand_size_mod = ("you", "set", _count_word(m15.group(1)))
        elif _l5 == "players have no maximum hand size":
            card.no_max_hand_all = True
        elif re.fullmatch(r"prevent all combat damage that would be dealt to " + _subj5, _l5):
            card.prevent_combat_to = True
        elif _l5 == "your opponents can't cast spells during your turn":
            card.opp_no_cast_your_turn = True
        elif (m15 := re.fullmatch(r"you can't cast more than (\w+) spells? each turn", _l5)) \
                and _count_word(m15.group(1)):
            card.self_spell_limit = _count_word(m15.group(1))
        elif (m15 := re.fullmatch(_subj5 + r" gets \+(\d+)/\+(\d+) for each (equipment|aura) attached to it",
                                  _l5)):
            def _sm15(src, target, _a=int(m15.group(1)), _b=int(m15.group(2)), _k=m15.group(3),
                      _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if target is src and src.game is not None:
                    n = sum(1 for pl in src.game.players for x in pl.battlefield
                            if getattr(x, "enchanting", None) is src
                            and _k in {st.lower() for st in x.card.subtypes})
                    return (base[0] + _a * n, base[1] + _b * n)
                return base
            card.static_mod = _sm15
        elif (m15 := re.fullmatch(_subj5 + r" gets \+(\d+)/\+(\d+) for each other (artifact|creature|"
                                  r"enchantment|land|[a-z]+) you control", _l5)):
            def _sm15b(src, target, _a=int(m15.group(1)), _b=int(m15.group(2)), _k=m15.group(3),
                       _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if target is src:
                    n = sum(1 for x in src.controller.battlefield if x is not src and (
                        x.is_creature() if _k == "creature" else
                        _k in x.card.types if _k in ("artifact", "enchantment", "land")
                        else x.has_subtype(_k)))
                    return (base[0] + _a * n, base[1] + _b * n)
                return base
            card.static_mod = _sm15b
        elif _l5 == "if you would gain life, you gain twice that much life instead":
            card.life_gain_double = True
        elif re.fullmatch(r"(?:when " + _subj5 + r" is put into a graveyard from anywhere, shuffle "
                          r"it into its owner's library|if " + _subj5 + r" would be put into a "
                          r"graveyard from anywhere, (?:reveal " + _subj5 + r" and )?shuffle it "
                          r"into its owner's library instead)", _l5):
            card.shuffle_from_gy = True
        elif re.fullmatch(r"when " + _subj5 + r" is put into a graveyard from anywhere, its owner "
                          r"shuffles their graveyard into their library", _l5):
            card.shuffle_from_gy = "all"
        elif re.fullmatch(r"creatures (?:your opponents control|your opponents control and "
                          r"lands your opponents control) enter(?: the battlefield)? tapped", _l5):
            card.opp_creatures_enter_tapped = True
        elif _l5 == "at the beginning of each player's draw step, that player draws an additional card":
            card.each_draw_extra = True
        elif re.fullmatch(_subj5 + r" can't block", _l5):
            card.cant_block_static = True
        elif re.fullmatch(_subj5 + r" can't block and can't be blocked", _l5):
            card.cant_block_static = True
            card.keywords = set(card.keywords) | {"unblockable"}
        elif (m7 := re.fullmatch(_subj5 + r" can't be blocked except by (\w+) or more creatures",
                                 _l5)) and (_count_word(m7.group(1)) or 0) >= 3:
            card.min_blockers = _count_word(m7.group(1))
        elif re.fullmatch(_subj5 + r" can't be blocked by walls", _l5):
            card.unblock_by_walls = True
        elif (m7 := re.fullmatch(r"all (?:([a-z]+) )?creatures have ([a-z ,]+?)", _l5)):
            _gk = [k.strip().replace(" ", "_") for k in re.split(r",\s*(?:and\s+)?|\s+and\s+",
                                                                  m7.group(2)) if k.strip()]
            if _gk and all(k in KEYWORDS for k in _gk):
                _gs = m7.group(1).capitalize() if m7.group(1) else None
                card.global_keywords = tuple(getattr(card, "global_keywords", None) or ()) + \
                    tuple((k, _gs) for k in _gk)
        elif (m7 := re.fullmatch(r"(?:all ([a-z]+) creatures|all ([a-z]+?)(?<!creature)s()|(creature tokens)"
                                 r"(?: you control)?) get ([+-]\d+)/([+-]\d+)", _l5)) and m7.group(2) != "creature":
            m7 = re.fullmatch(r"(?:all ([a-z]+?)(?: creatures|s)|(creature tokens)(?: you control)?) "
                              r"get ([+-]\d+)/([+-]\d+)", _l5)
            _gsub = m7.group(1).capitalize() if m7.group(1) else None
            _toks = bool(m7.group(2))
            _mine = "you control" in _l5

            def _sm7(src, target, _a=int(m7.group(3)), _b=int(m7.group(4)), _s=_gsub, _t=_toks,
                     _m=_mine, _p=card.static_mod):
                base = _p(src, target) if _p else (0, 0)
                if _m and target.controller is not src.controller:
                    return base
                if (_s and target.has_subtype(_s)) or (_t and target.is_token):
                    return (base[0] + _a, base[1] + _b)
                return base
            card.static_mod = _sm7
        elif _l5 == "you have no maximum hand size":
            card.no_max_hand = True
        elif _l5 == "skip your draw step":
            card.skip_draw = True
        elif re.fullmatch(r"whenever " + _subj5 + r" deals damage, you gain that much life", _l5):
            card.keywords = set(card.keywords) | {"lifelink"}
        elif re.fullmatch(r"at the beginning of (?:the|each) end step, sacrifice " + _subj5, _l5) \
                or re.fullmatch(r"at the beginning of your end step, sacrifice " + _subj5, _l5):
            _ev5 = "end_step" if "your end step" in _l5 else "each_end_step"

            def _eot_sac(g, perm, _prev=(card.triggers or {}).get(_ev5), **_kw):
                if _prev:
                    _prev(g, perm, **_kw)
                if perm in perm.controller.battlefield:
                    g.log(f"{perm.name} se sacrifica al final del turno")
                    g.to_graveyard(perm, "fin de turno")
            card.triggers = dict(card.triggers or {}, **{_ev5: _eot_sac})
        elif re.fullmatch(r"when (?:this aura|this enchantment|~) is put into a graveyard from the "
                          r"battlefield, return (?:it|~|this card) to its owner's hand", _l5):
            def _back_to_hand(g, perm, _prev=(card.triggers or {}).get("self_to_gy"), **_kw):
                if _prev:
                    _prev(g, perm, **_kw)
                for pl in g.players:
                    if perm.card in pl.graveyard:
                        pl.graveyard.remove(perm.card)
                        pl.hand.append(perm.card)
                        g.log(f"{perm.name} vuelve a la mano de {pl.name}")
                        break
            card.triggers = dict(card.triggers or {}, self_to_gy=_back_to_hand)
    # hechizo que se exilia a sí mismo al resolver ("Exile Avatar's Wrath.")
    if _spell and card.on_cast_resolve is not None and any(
            re.fullmatch(r"exile (?:~|this spell|" + "|".join(re.escape(n) for n in _names if n)
                         + r")\.?", _strip_reminder(_l).strip().lower())
            for _l in _ability_lines(data.get("oracle_text", ""))):
        def _self_exile(g, ctrl, tg, _base=card.on_cast_resolve, _c=card):
            _base(g, ctrl, tg)
            _c._exile_after_cast = True
        card.on_cast_resolve = _self_exile

    # escape con contadores: "this creature escapes with N +1/+1 counters on it"
    _mesc = re.search(r"(?:this creature|~|" + "|".join(re.escape(n) for n in _names if n) +
                      r") escapes with (a|an|one|two|three|four|five|\w+) \+1/\+1 counters? on it",
                      re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower()))
    if _mesc and _count_word(_mesc.group(1)):
        card.escape_counters = _count_word(_mesc.group(1))

    # costes alternativos: coste adicional al lanzar y reducción "cuesta {N} menos"
    if {"instant", "sorcery", "creature", "artifact", "enchantment", "planeswalker"} & types:
        add = {}
        mc = re.search(r"as an additional cost to cast [^,]+, ([^.]+)", _ot)
        if mc:
            seg = mc.group(1)
            ml = re.search(r"pay (\w+) life", seg)
            if ml and ml.group(1) == "x":
                add["pay_life_x"] = True
            elif ml and (nl := _count_word(ml.group(1))):
                add["pay_life"] = nl
            md = re.search(r"discard (\w+) cards?", seg)
            if md and md.group(1) == "x":
                add["discard_x"] = True
            elif md and (nd := _count_word(md.group(1))):
                add["discard"] = nd
            mxg = re.search(r"exile (a|an|one|two|three|four|five|\w+) (creature |instant or sorcery |"
                            r")?cards? from your graveyard", seg)
            mrs = re.search(r"return (two|three|\d+) (swamp|island|forest|mountain|plains|land)s you control to their owner's hand",
                            seg)
            if mrs:
                add["bounce_own"] = mrs.group(2)
                add["bounce_n"] = _count_word(mrs.group(1))
            mdc = re.search(r"discard (two|three|\d+) (creature|land|instant|sorcery) cards", seg)
            if mdc:
                add["discard"] = _count_word(mdc.group(1))
            if mxg and (nxg := _count_word(mxg.group(1))):
                add["exile_gy"] = (nxg, (mxg.group(2) or "").strip())
            msn = re.search(r"sacrifice (two|three|four|\d+) creatures", seg)
            if msn:
                add["sacrifice_n"] = _count_word(msn.group(1))
            msl = re.search(r"sacrifice (two|three|four|\d+) (lands|artifacts|enchantments|permanents)", seg)
            if msl:
                add["sacrifice_nk"] = (_count_word(msl.group(1)), msl.group(2)[:-1])
            mbo = re.search(r"return (?:a|an) (land|creature|permanent|artifact|enchantment|nonland permanent) you control "
                            r"to its owner's hand", seg)
            if mbo:
                add["bounce_own"] = mbo.group(1)
            if re.search(r"exile (?:a|another) creature you control", seg):
                add["exile_own"] = "creature"
            mrv = re.search(r"^reveal (?:a|an) ([a-z]+) card from your hand", seg)
            if mrv:
                add["reveal"] = mrv.group(1)
            if "sacrifice a creature" in seg or "sacrifice another creature" in seg:
                add["sacrifice"] = True
            else:
                mcp = re.search(r"sacrifice (?:a|an) (white|blue|black|red|green) permanent", seg)
                if mcp:
                    add["sacrifice"] = "color:" + mcp.group(1)
                msk = None if mcp else re.search(r"sacrifice (?:a|an|another) ((?:artifact|creature|enchantment|land|"
                                                 r"permanent|token|planeswalker)(?:,? (?:or|and/or) (?:an? )?"
                                                 r"(?:artifact|creature|enchantment|land|planeswalker|token))*)", seg)
                if msk:
                    add["sacrifice"] = "|".join(re.findall(
                        r"artifact|creature|enchantment|land|permanent|token|planeswalker",
                        msk.group(1)))
                elif not mcp and (msk := re.search(r"sacrifice (?:a|an|another) (nonland permanent|nontoken creature|[a-z]+)$",
                                                   seg)) and not msn and not msl:
                    add["sacrifice"] = msk.group(1).replace(" ", "_")
        if add:
            card.additional_cost = add
        mrx = re.search(r"this spell costs \{x\} less to cast, where x is ([^.]+)", _ot)
        if mrx and (_fx := _count21(mrx.group(1))) is not None:
            card.cost_reduction_fn = (lambda g, p, _f=_fx: _f(g, p))
        mr = None if mrx else re.search(r"this spell costs \{(\d+)\} less to cast(?: for each ([^.]+))?", _ot)
        if mr and mr.group(2):
            # "{1} menos por CADA criatura en el campo…": reducción dinámica (antes
            # quedaba fija en 1: Blasphemous Act costaba 8)
            _fn = _each_count_fn(mr.group(2))
            if _fn is not None:
                card.cost_reduction_fn = (lambda g, p, _n=int(mr.group(1)), _f=_fn:
                                          _n * _f(g, p))
        elif mr:
            card.cost_reduction = int(mr.group(1))

    # efectos de REEMPLAZO estáticos (dobladores / muerte->exilio)
    _rt = re.sub(r"\s+", " ", (data.get("oracle_text", "") or "").lower())
    if re.search(r"twice that many (?:of those )?tokens", _rt) or \
            "create twice as many" in _rt:
        card.token_double = True
    mch = re.search(r"twice that many (?:of those |\+1/\+1 )?counters", _rt)
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

    # Cipher: tras resolver el hechizo, se cifra en una criatura tuya; cuando esa
    # criatura pega daño de combate a un jugador, lanzás una copia GRATIS.
    if ("cipher" in _lt and {"instant", "sorcery"} & types
            and card.on_cast_resolve is not None):
        _base_ci = card.on_cast_resolve

        def _cipher_resolve(g, ctrl, tg, _b=_base_ci, _nm=name):
            _b(g, ctrl, tg)
            mine = [pm for pm in ctrl.battlefield if pm.is_creature()]
            if mine:
                enc = max(mine, key=lambda p: (p.power, p.toughness))
                lst = getattr(enc, "_ciphered", None)
                if lst is None:
                    lst = enc._ciphered = []
                lst.append(_b)
                g.log(f"{ctrl.name} cifra {_nm} en {enc.name}")
        card.on_cast_resolve = _cipher_resolve
        card.cipher = True

    # Suspend N—<coste>: en vez de lanzar, pagás el coste y la exiliás con N
    # contadores de tiempo; cada mantenimiento se quita uno y al llegar a 0 se lanza
    # gratis. El motor administra los contadores (game.suspended).
    msus = re.search(r"suspend (\d+)\s*[—-]\s*((?:\{[wubrgc0-9/x]+\})+)", _lt)
    if msus:
        card.suspend = {"n": int(msus.group(1)), "cost": parse_cost(mana_cost_to_str(
            "".join(re.findall(r"\{[wubrgc0-9/x]+\}", msus.group(2)))))}

    # Soulbond: al entrar (ella u otra), se empareja con otra criatura tuya sin
    # pareja; mientras sigan emparejadas, AMBAS tienen el bono (motor: _paired).
    if ("soulbond" in {k.lower() for k in (data.get("keywords") or [])}
            or re.search(r"(?:^|\n)soulbond\b", (data.get("oracle_text", "") or "").lower())) \
            and "creature" in types:
        card.soulbond = True
        msb = re.search(r"as long as [^,]+? is paired with another creature, (?:each of those "
                        r"creatures|both creatures|they each) ([^.]+)", _lt)
        if msb:
            _sbt = msb.group(1)
            mpt = re.search(r"gets? \+(\d+)/\+(\d+)", _sbt)
            if mpt:
                card.soulbond_pt = (int(mpt.group(1)), int(mpt.group(2)))
            mhv = re.search(r"ha(?:ve|s) ([a-z ,]+?)(?:$| and get| as long)", _sbt)
            gained = set()
            if mhv and '"' not in _sbt:
                for nm2, key in _KEYWORD_WORDS:
                    if re.search(r"\b" + nm2 + r"\b", mhv.group(1)):
                        gained.add(key)
            card.soulbond_kws = frozenset(gained)

    # efecto genérico POR TAG: en un hechizo, al resolver; en un permanente, solo si
    # tiene un disparo de entrada propio y con los tags de ESE cuerpo (antes un
    # "whenever ~ attacks, draw" o un "{T}: destroy" se volvía un ETB gratis)
    if {"instant", "sorcery"} & types:
        return cards.attach_generic_effects(card)
    if not _etb_body or re.match(r"if\b", _etb_body, re.I):
        return card
    _all_tags = card.tags
    card.tags = _derive_tags(_etb_body, card.types)
    cards.attach_generic_effects(card)
    card.tags = _all_tags
    return card




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
    # base LOCAL de cartas (texto real de Scryfall, sin red): precons + presets
    data = local_card(name)
    if data is None and fetch is not None:
        data = fetch(name)
    if data is not None:
        if data:
            try:
                return build_card_from_data(dict(data))
            except Exception:            # noqa: BLE001  (red de seguridad total)
                # el parseo completo falló: no tirar la carga del mazo por una carta;
                # devolvemos sus datos reales como vainilla.
                try:
                    return _vanilla_from_data(data)
                except Exception:        # noqa: BLE001
                    return None
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


_LOCAL_DB = None


def local_db() -> dict:
    """{nombre normalizado: datos de Scryfall} de data/cards_db.json.gz (todas las
    cartas de los precons y presets). Vacío si el archivo no está (p. ej. Pyodide)."""
    global _LOCAL_DB
    if _LOCAL_DB is None:
        import gzip
        import json
        import os
        _LOCAL_DB = {}
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                            "cards_db.json.gz")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for nm, row in json.load(f).get("cards", {}).items():
                    _LOCAL_DB[_norm(nm)] = row
                    for face in row.get("card_faces") or []:      # 'A // B' por cara
                        if face.get("name"):
                            _LOCAL_DB.setdefault(_norm(face["name"]), row)
        except (OSError, ValueError):
            pass
    return _LOCAL_DB


_FULL_DB = None


def full_db() -> dict:
    """Base COMPLETA (data/cards_full.json.gz, ~31k cartas de Scryfall). Se carga
    solo si una carta no está en la base de precons. Vacía si no está el archivo."""
    global _FULL_DB
    if _FULL_DB is None:
        import gzip
        import json
        import os
        _FULL_DB = {}
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                            "cards_full.json.gz")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for nm, row in json.load(f).get("cards", {}).items():
                    _FULL_DB[_norm(nm)] = row
                    for face in row.get("card_faces") or []:
                        if face.get("name"):
                            _FULL_DB.setdefault(_norm(face["name"]), row)
        except (OSError, ValueError):
            pass
    return _FULL_DB


def local_card(name: str):
    """Datos reales de la carta desde la base local (precons) o la completa, o None."""
    if not name:
        return None
    for n in (name, name.split(" // ")[0]):
        row = local_db().get(_norm(n))
        if row is not None:
            return row
    for n in (name, name.split(" // ")[0]):
        row = full_db().get(_norm(n))
        if row is not None:
            return row
    return None


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


REGISTRY.update(_build_registry())
