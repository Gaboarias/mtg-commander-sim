"""Análisis de un mazo Commander: fortalezas, debilidades, sinergias (heurístico
sobre datos de Scryfall) + combos reales vía Commander Spellbook.

Todo es APROXIMADO: las etiquetas de rol se deducen del oracle text (inglés). Los
combos por nombre sí son exactos porque los da Commander Spellbook. La llamada
externa se aísla: si falla, el resto del análisis igual se devuelve.
"""
import json
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
