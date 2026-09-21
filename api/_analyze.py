"""Análisis de un mazo Commander: fortalezas, debilidades, sinergias (heurístico
sobre datos de Scryfall) + combos reales vía Commander Spellbook.

Todo es APROXIMADO: las etiquetas de rol se deducen del oracle text (inglés). Los
combos por nombre sí son exactos porque los da Commander Spellbook. La llamada
externa se aísla: si falla, el resto del análisis igual se devuelve.
"""
import json
import math
import re
import urllib.request

_UA = "mtg-commander-sim/1.0 (https://github.com/Gaboarias/mtg-commander-sim)"
_CS_ENDPOINT = "https://backend.commanderspellbook.com/find-my-combos"

_COLORS = ("W", "U", "B", "R", "G")
_COLOR_ES = {"W": "blanco", "U": "azul", "B": "negro", "R": "rojo", "G": "verde"}


# --------------------------------------------------------------------------- #
# Clasificación de una carta (rol) a partir de su dict de Scryfall
# --------------------------------------------------------------------------- #

def _oracle(card):
    return re.sub(r"\s+", " ", (card.get("oracle_text") or "").lower())


def _roles(card):
    """Conjunto de roles aproximados de una carta (dict tipo Scryfall)."""
    tl = (card.get("type_line") or "").lower()
    ot = _oracle(card)
    r = set()
    is_land = "land" in tl
    if is_land:
        r.add("land")
    if "creature" in tl:
        r.add("creature")
    if "planeswalker" in tl:
        r.add("planeswalker")
    if "artifact" in tl:
        r.add("artifact")
    if "enchantment" in tl:
        r.add("enchantment")
    if "instant" in tl or "sorcery" in tl:
        r.add("spell")

    # ramp (no tierras): produce maná extra o busca tierras
    if not is_land and (re.search(r"\badd \{", ot)
                        or re.search(r"search your library for .{0,30}land", ot)
                        or "produced_mana" in card and "artifact" in tl and card.get("produced_mana")):
        r.add("ramp")
    # robo / ventaja de cartas
    if re.search(r"draw (a|one|two|three|four|\d+) cards?", ot):
        r.add("draw")
    # remoción puntual (dirigida)
    if (re.search(r"(destroy|exile) target", ot)
            or re.search(r"deals? \d+ damage to (target|any target)", ot)
            or re.search(r"return target .{0,30}(hand|owner)", ot)):
        r.add("removal")
    # barrida
    if (re.search(r"destroy all|exile all|destroy each", ot)
            or re.search(r"all creatures get -\d", ot)
            or re.search(r"deals? \d+ damage to each creature", ot)
            or re.search(r"each player sacrifices", ot)):
        r.add("wipe")
    # contramagia
    if re.search(r"counter target", ot):
        r.add("counter")
    # protección
    if re.search(r"hexproof|indestructible|protection from|can'?t be countered"
                 r"|shroud|phase out|ward", ot):
        r.add("protection")
    # recursión / cementerio
    if "from your graveyard" in ot or "from a graveyard" in ot:
        r.add("recursion")
    # tutores (no de tierra)
    if re.search(r"search your library for a", ot) and "land" not in ot[:120]:
        r.add("tutor")
    return r, is_land


_THEMES = [
    ("tokens", "Fichas / go-wide",
     lambda ot, tl: ("token" in ot and "create" in ot)
     or "creatures you control get" in ot),
    ("counters", "Contadores +1/+1",
     lambda ot, tl: "+1/+1 counter" in ot),
    ("graveyard", "Cementerio / recursión",
     lambda ot, tl: "from your graveyard" in ot or "mill" in ot
     or "into your graveyard" in ot),
    ("sacrifice", "Sacrificio / aristócratas",
     lambda ot, tl: "sacrifice a" in ot or "whenever a creature you control dies" in ot
     or ", sacrifice" in ot),
    ("spellslinger", "Spellslinger (instantáneos/conjuros)",
     lambda ot, tl: "instant or sorcery" in ot
     or "whenever you cast an instant or sorcery" in ot),
    ("lifegain", "Ganancia de vida",
     lambda ot, tl: "gain life" in ot or "whenever you gain life" in ot),
    ("artifacts", "Artefactos importan",
     lambda ot, tl: "artifact" in ot and ("metalcraft" in ot or "affinity" in ot
     or "artifacts you control" in ot or "whenever an artifact" in ot)),
    ("landfall", "Landfall / tierras",
     lambda ot, tl: "landfall" in ot or "whenever a land enters" in ot
     or "whenever a land you control enters" in ot),
    ("blink", "Parpadeo / ETB",
     lambda ot, tl: "exile" in ot and "return" in ot and "battlefield" in ot
     and ("enters the battlefield" in ot or "you may" in ot)),
]


# --------------------------------------------------------------------------- #
# Maná: demanda de color (pips) y fuentes
# --------------------------------------------------------------------------- #

def _pips(mana_cost):
    out = {c: 0 for c in _COLORS}
    for sym in re.findall(r"\{([^}]+)\}", mana_cost or ""):
        s = sym.upper()
        for c in _COLORS:
            if c in s:
                out[c] += 1
    return out


# --------------------------------------------------------------------------- #
# Análisis heurístico
# --------------------------------------------------------------------------- #

def analyze(entries, commander_name=None):
    """entries: lista de (qty, name, card_dict|None). Devuelve el reporte."""
    total = lands = 0
    roles = {k: 0 for k in ("ramp", "draw", "removal", "wipe", "counter",
                            "protection", "recursion", "tutor")}
    counts = {k: 0 for k in ("creature", "artifact", "enchantment",
                             "planeswalker", "spell")}
    curve = {str(i): 0 for i in range(8)}   # 0..7 (7 = 7+)
    curve["7"] = 0
    demand = {c: 0 for c in _COLORS}
    sources = {c: 0 for c in _COLORS}
    theme_hits = {k: [] for k, _l, _f in _THEMES}
    cmc_sum = nonland = 0
    unknown = 0

    for qty, name, card in entries:
        total += qty
        if card is None:
            unknown += qty
            continue
        r, is_land = _roles(card)
        tl = (card.get("type_line") or "").lower()
        ot = _oracle(card)

        if is_land:
            lands += qty
            for c, n in _pips_from_produced(card).items():
                sources[c] += qty if n else 0
        else:
            cmc = int(card.get("cmc") or 0)
            curve[str(min(cmc, 7))] += qty
            cmc_sum += cmc * qty
            nonland += qty
            for c, n in _pips(card.get("mana_cost")).items():
                demand[c] += n * qty
            # rocas/dorks que producen color -> fuentes también
            for c, n in _pips_from_produced(card).items():
                sources[c] += qty if n else 0

        for k in roles:
            if k in r:
                roles[k] += qty
        for k in counts:
            if k in r:
                counts[k] += qty
        for key, _lbl, fn in _THEMES:
            try:
                if fn(ot, tl):
                    theme_hits[key].append(card.get("name") or name)
            except Exception:  # noqa: BLE001
                pass

    avg_cmc = round(cmc_sum / nonland, 2) if nonland else 0.0
    ramp_eff = lands + roles["ramp"]     # "fuentes de maná" efectivas aprox

    themes = [{"key": k, "label": lbl, "count": len(theme_hits[k]),
               "cards": sorted(set(theme_hits[k]))[:12]}
              for k, lbl, _f in _THEMES if len(theme_hits[k]) >= 5]
    themes.sort(key=lambda t: t["count"], reverse=True)

    strengths, weaknesses = _judge(total, lands, ramp_eff, roles, counts,
                                   avg_cmc, curve, demand, sources, themes)
    owned = {_norm(n) for _q, n, _c in entries}
    if commander_name:
        owned.add(_norm(commander_name))
    recommendations = _recommend(lands, roles, counts, avg_cmc, demand, sources, owned)
    consistency = _consistency(total, lands, roles, avg_cmc)

    return {
        "commander": commander_name,
        "total": total,
        "unknown": unknown,
        "counts": {**counts, "land": lands},
        "roles": roles,
        "curve": curve,
        "avg_cmc": avg_cmc,
        "mana": {"demand": demand, "sources": sources},
        "themes": themes,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recommendations,
        "consistency": consistency,
    }


def _pips_from_produced(card):
    out = {c: 0 for c in _COLORS}
    for c in (card.get("produced_mana") or []):
        if c in out:
            out[c] = 1
    return out


def _judge(total, lands, ramp_eff, roles, counts, avg_cmc, curve,
           demand, sources, themes):
    """Reglas sobre líneas base de Commander (100 cartas)."""
    S, W = [], []

    # --- base de maná ---
    if lands < 33:
        W.append(f"Pocas tierras ({lands}). En Commander se apunta a ~36–38; "
                 "podés trabarte de maná.")
    elif lands > 42:
        W.append(f"Demasiadas tierras ({lands}); vas a inundarte. Bajá a ~37 y "
                 "sumá hechizos.")
    else:
        S.append(f"Base de maná sana ({lands} tierras).")

    if roles["ramp"] < 8:
        W.append(f"Poco ramp ({roles['ramp']}). Con ~10 acelerás y jugás el "
                 "comandante antes.")
    elif roles["ramp"] >= 10:
        S.append(f"Buen ramp ({roles['ramp']}): arranque rápido.")

    # --- cartas / robo ---
    if roles["draw"] < 8:
        W.append(f"Poco robo ({roles['draw']}). Sin motores de cartas te quedás "
                 "sin recursos a media partida.")
    elif roles["draw"] >= 10:
        S.append(f"Buen motor de cartas ({roles['draw']} fuentes de robo).")

    # --- interacción ---
    if roles["removal"] < 5:
        W.append(f"Poca remoción puntual ({roles['removal']}). Te cuesta "
                 "responder a amenazas rivales.")
    elif roles["removal"] >= 8:
        S.append(f"Mucha interacción ({roles['removal']} remociones).")

    if roles["wipe"] == 0:
        W.append("Sin barridas: te ganan por acumulación (go-wide).")
    elif roles["wipe"] >= 2:
        S.append(f"{roles['wipe']} barridas para reiniciar el tablero.")

    if roles["counter"] >= 4:
        S.append(f"{roles['counter']} counters: podés proteger tu plan y frenar el rival.")

    # --- curva ---
    if avg_cmc >= 3.6:
        W.append(f"Curva alta (CMC promedio {avg_cmc}). Riesgo de manos lentas; "
                 "sumá caídas baratas o más ramp.")
    elif avg_cmc and avg_cmc <= 2.8:
        S.append(f"Curva baja y ágil (CMC promedio {avg_cmc}).")
    top = curve.get("6", 0) + curve.get("7", 0)
    if top >= 12:
        W.append(f"{top} cartas de CMC 6+: cima pesada, difícil de desplegar.")

    # --- vulnerabilidad a barridas ---
    if counts["creature"] >= 28 and roles["protection"] < 3:
        W.append(f"Muchas criaturas ({counts['creature']}) y poca protección: "
                 "una barrida rival te desarma.")

    # --- balance de color ---
    active = [c for c in _COLORS if demand[c] > 0]
    for c in active:
        need = demand[c]
        have = sources[c]
        if need >= 8 and have < max(5, need // 3):
            W.append(f"Base de maná floja para {_COLOR_ES[c]}: mucha demanda "
                     f"({need} símbolos) y pocas fuentes ({have}).")

    # --- consistencia por tutores ---
    if roles["tutor"] >= 4:
        S.append(f"Consistente: {roles['tutor']} tutores para buscar tus piezas.")

    # --- temas ---
    if themes:
        t = themes[0]
        S.append(f"Tema marcado: {t['label']} ({t['count']} cartas) — hay sinergia "
                 "para explotar.")

    if not S:
        S.append("Mazo equilibrado sin picos claros.")
    if not W:
        W.append("No se detectaron debilidades estructurales obvias. ¡Buen mazo!")
    return S, W


# --------------------------------------------------------------------------- #
# Recomendaciones (qué sumar/cortar) y consistencia
# --------------------------------------------------------------------------- #

# staples curados por rol (autocontenido, sin depender de EDHREC)
_STAPLES = {
    "ramp": ["Sol Ring", "Arcane Signet", "Cultivate", "Kodama's Reach", "Fellwar Stone"],
    "draw": ["Rhystic Study", "Phyrexian Arena", "Night's Whisper", "Guardian Project"],
    "removal": ["Swords to Plowshares", "Beast Within", "Generous Gift", "Chaos Warp", "Go for the Throat"],
    "wipe": ["Blasphemous Act", "Damnation", "Wrath of God", "Toxic Deluge"],
    "protection": ["Heroic Intervention", "Teferi's Protection", "Flawless Maneuver"],
}
_FIX = {
    "W": "Plains, duales blancas, Command Tower, fetchlands",
    "U": "Island, duales azules, Command Tower, fetchlands",
    "B": "Swamp, duales negras, Command Tower, fetchlands",
    "R": "Mountain, duales rojas, Command Tower, fetchlands",
    "G": "Forest, duales verdes, Command Tower, fetchlands",
}


def _staples(role, owned):
    """Staples del rol que el deck NO tiene todavía (para no recomendar lo puesto)."""
    return [s for s in _STAPLES[role] if _norm(s) not in (owned or set())][:5]


def _recommend(lands, roles, counts, avg_cmc, demand, sources, owned=None):
    """Sugerencias ACCIONABLES. Devuelve [{text, cards:[nombre...]}]; los precios se
    inyectan después (capa de API, que tiene Scryfall). `owned`: nombres normalizados
    ya en el deck (para no sugerir lo que ya tenés)."""
    owned = owned or set()
    recs = []

    def rec(text, cards=None):
        recs.append({"text": text, "cards": cards or []})

    def tip(base, role):
        recs.append({"text": base, "cards": _staples(role, owned)})

    if lands < 36:
        rec(f"Sumá {36 - lands} tierras (apuntá a ~36–38) para no trabarte.")
    elif lands > 40:
        rec(f"Bajá ~{lands - 38} tierras y meté hechizos: te vas a inundar.")
    if roles["ramp"] < 10:
        tip(f"Sumá ~{10 - roles['ramp']} piezas de ramp", "ramp")
    if roles["draw"] < 10:
        tip("Sumá motores de robo", "draw")
    if roles["removal"] < 8:
        tip("Sumá remoción puntual", "removal")
    if roles["wipe"] == 0:
        tip("Meté 1–2 barridas", "wipe")
    if counts["creature"] >= 28 and roles["protection"] < 3:
        tip("Protegé tu tablero de barridas", "protection")
    for c in _COLORS:
        if demand[c] >= 8 and sources[c] < max(5, demand[c] // 3):
            rec(f"Reforzá fuentes de {_COLOR_ES[c]} ({_FIX[c]}).")
    if not recs:
        rec("El mazo está bien balanceado; afiná según tu meta local.")
    return recs


def _consistency(total, lands, roles, avg_cmc):
    """Prob. de una mano inicial jugable (2–5 tierras en 7) + score 0–100.
    Hipergeométrico exacto con math.comb (stdlib)."""
    n = total or 100
    hand = min(7, n)
    prob = 0.0
    if 0 < lands <= n:
        denom = math.comb(n, hand)
        for k in range(2, 6):                       # 2..5 tierras = mano jugable
            if 0 <= k <= lands and 0 <= hand - k <= n - lands:
                prob += math.comb(lands, k) * math.comb(n - lands, hand - k) / denom
    prob = round(prob, 3)

    score = prob * 55                                # peso principal: base de maná
    score += min(roles["ramp"], 10) / 10 * 20        # ramp
    score += min(roles["tutor"], 6) / 6 * 10         # tutores
    score += max(0.0, (3.6 - avg_cmc)) / 1.6 * 15    # curva baja ayuda
    score = max(0, min(100, round(score)))
    return {"land_prob": prob, "score": score}


# --------------------------------------------------------------------------- #
# Sugerencia: ¿en qué deck me sirve una carta?
# --------------------------------------------------------------------------- #

_ROLE_ES = {"ramp": "ramp", "draw": "robo", "removal": "remoción",
            "wipe": "barridas", "counter": "counters", "protection": "protección",
            "recursion": "recursión", "tutor": "tutores"}


def _needs(report):
    """Roles que a un deck le FALTAN, según su reporte de analyze()."""
    roles = report["roles"]
    counts = report["counts"]
    need = set()
    if roles["ramp"] < 10:
        need.add("ramp")
    if roles["draw"] < 10:
        need.add("draw")
    if roles["removal"] < 8:
        need.add("removal")
    if roles["wipe"] == 0:
        need.add("wipe")
    if counts.get("creature", 0) >= 28 and roles["protection"] < 3:
        need.add("protection")
    return need


def suggest_decks(card_name, decks, cache):
    """¿En cuáles de `decks` sirve `card_name`? Puro y testeable: la resolución de
    Scryfall se hace afuera y se pasa en `cache` {nombre_norm: dict}.
    `decks`: [{"name", "parsed": {commander, cards:[(qty,name)]}}]."""
    craw = cache.get(_norm(card_name))
    card_roles, _ = _roles(craw) if craw else (set(), False)
    card_roles &= set(_ROLE_ES)                       # solo roles “de necesidad”
    card_colors = set((craw or {}).get("color_identity") or [])

    out = []
    for d in decks:
        parsed = d["parsed"]
        # identidad del deck = la del comandante; si no, unión de las cartas
        ident = set()
        cmd = parsed.get("commander")
        cmd_raw = cache.get(_norm(cmd)) if cmd else None
        if cmd_raw:
            ident = set(cmd_raw.get("color_identity") or [])
        if not ident:
            for _q, cn in parsed["cards"]:
                r = cache.get(_norm(cn))
                if r:
                    ident |= set(r.get("color_identity") or [])
        in_color = card_colors <= ident

        entries = [(q, cn, cache.get(_norm(cn))) for q, cn in parsed["cards"]]
        report = analyze(entries, cmd)
        fills = sorted(card_roles & _needs(report))
        score = (2 if in_color else 0) + (len(fills) if in_color else 0)

        if not in_color:
            verdict = "Fuera de color"
        elif fills:
            verdict = "Encaja y cubre " + ", ".join(_ROLE_ES[f] for f in fills)
        else:
            verdict = "Encaja en color (no cubre un hueco claro)"

        out.append({"name": d["name"], "in_color": in_color,
                    "fills": [_ROLE_ES[f] for f in fills],
                    "verdict": verdict, "score": score})
    out.sort(key=lambda x: x["score"], reverse=True)
    return {"card": card_name, "roles": sorted(_ROLE_ES[r] for r in card_roles),
            "colors": sorted(card_colors), "decks": out}


# --------------------------------------------------------------------------- #
# Commander Spellbook: combos reales por nombre
# --------------------------------------------------------------------------- #

def _names_from_uses(uses):
    out = []
    for u in uses or []:
        c = u.get("card") if isinstance(u, dict) else None
        if isinstance(c, dict):
            out.append(c.get("name"))
        elif isinstance(c, str):
            out.append(c)
        elif isinstance(u, dict) and u.get("name"):
            out.append(u["name"])
    return [n for n in out if n]


def _features(produces):
    out = []
    for p in produces or []:
        f = p.get("feature") if isinstance(p, dict) else None
        if isinstance(f, dict):
            out.append(f.get("name"))
        elif isinstance(p, dict) and p.get("name"):
            out.append(p["name"])
        elif isinstance(p, str):
            out.append(p)
    return [n for n in out if n]


def _variant(v, deck_norm):
    cards = _names_from_uses(v.get("uses"))
    feats = _features(v.get("produces"))
    missing = [c for c in cards if _norm(c) not in deck_norm]
    return {
        "id": str(v.get("id") or ""),
        "cards": cards,
        "produces": feats,
        "missing": missing,
    }


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _cs_post(payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _CS_ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_combos(commanders, main, timeout=25):
    """Consulta Commander Spellbook. Devuelve {included, almost, error}.
    Prueba el formato de objetos y, si falla, el de strings (la API ha usado
    ambos); así seguimos funcionando ante cambios menores del esquema."""
    cs = [c for c in commanders if c]
    mn = [n for n in main if n]
    payloads = [
        {"commanders": [{"card": c, "quantity": 1} for c in cs],
         "main": [{"card": n, "quantity": 1} for n in mn]},
        {"commanders": cs, "main": mn},
    ]
    data, last_err = None, None
    for payload in payloads:
        try:
            data = _cs_post(payload, timeout)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
    if data is None:
        return {"included": [], "almost": [], "error": last_err or "sin respuesta"}

    res = data.get("results", data) if isinstance(data, dict) else {}
    deck_norm = {_norm(c) for c in (commanders + main)}
    included = [_variant(v, deck_norm) for v in (res.get("included") or [])]
    almost = [_variant(v, deck_norm) for v in (res.get("almostIncluded") or [])]
    # solo los "casi" a los que les falta exactamente 1 carta (accionable)
    almost = [a for a in almost if len(a["missing"]) == 1]
    return {"included": included[:40], "almost": almost[:30], "error": None}
