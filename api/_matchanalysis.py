"""Análisis heurístico de una partida ya jugada, a partir del trace de replay().

Cada step del trace: {turn, active, label, players:[{name, life, cmdr_damage,
poison, battlefield:[...]}]}. Deducimos: cómo se ganó, jugadas clave, mejores
movidas del ganador, errores aproximados y el encadenamiento final.

Todo es APROXIMADO (se lee del log/estados, no es un comentarista experto).
"""
import re

_WIPE = re.compile(r"destroy all|exile all|destroy each|deals? \d+ damage to each creature"
                   r"|all creatures? get -", re.I)
_REMOVAL = re.compile(r"destr|exile|removal", re.I)
_CAST = re.compile(r"lanza", re.I)
_LAND = re.compile(r"juega tierra", re.I)
_ULT = re.compile(r"activa -\d|PW -", re.I)
_WIN = re.compile(r"GANA|EMPATE|pierde", re.I)


def _creatures(pl):
    return sum(1 for pm in (pl.get("battlefield") or []) if pm.get("is_creature"))


def _by_name(players):
    return {p["name"]: p for p in players}


def analyze(trace, winner, players, ability_events=None):
    names = [p.name for p in players]
    steps = trace or []
    if not steps:
        return {"win_type": "?", "summary": "Sin datos de la partida.",
                "key_plays": [], "best_moves": [], "mistakes": [], "chain": [],
                "abilities": []}

    final = steps[-1]["players"]
    fmap = _by_name(final)
    turns = steps[-1]["turn"]

    # --- tipo de victoria ---
    win_type = "último en pie"
    victim = None
    for nm, p in fmap.items():
        if any(v >= 21 for v in (p.get("cmdr_damage") or {}).values()):
            win_type, victim = "daño de comandante", nm
        elif (p.get("poison") or 0) >= 10:
            win_type, victim = "veneno", nm
        elif (p.get("life") or 0) <= 0 and win_type == "último en pie":
            win_type, victim = "combate/quema", nm
    if any(re.search(r"gana la partida|alt-win|ascendancy", s["label"], re.I) for s in steps):
        win_type = "victoria alternativa"

    # --- recorrer: deltas de vida por step (todos arrancan en 40 en Commander) ---
    prev_life = {n: 40 for n in names}
    key, best = [], []
    last_turn = turns
    for i, s in enumerate(steps):
        pm = _by_name(s["players"])
        actor = names[s["active"]] if 0 <= s["active"] < len(names) else None
        label = s["label"]
        is_land = bool(_LAND.search(label))
        # daño causado este step = caída de vida de rivales
        dmg = 0
        for n, p in pm.items():
            d = prev_life.get(n, 40) - (p.get("life") or 0)
            if n != actor and d > 0:
                dmg += d
            prev_life[n] = p.get("life") or 0
        # eventos definitorios (el daño no se atribuye a una jugada de tierra: la
        # baja de vida suele ser del combate del turno, no de bajar una tierra)
        why = None
        if _WIPE.search(label):
            why = "barrida"
        elif _ULT.search(label):
            why = "ult de planeswalker"
        elif "pierde" in label.lower():
            why = "eliminación"
        elif dmg >= 6 and not is_land:
            why = f"{dmg} de daño"
        if why:
            key.append({"turn": s["turn"], "label": label, "why": why, "step": i, "dmg": dmg})
        if actor == winner and dmg > 0 and not is_land:
            best.append({"turn": s["turn"], "label": label, "delta": dmg, "step": i})

    maxdmg = max([k.get("dmg", 0) for k in key] + [0])
    maxdelta = max([b["delta"] for b in best] + [0])

    def _key_reason(k):
        w = k["why"]
        if w == "eliminación":
            base = "sacó a un jugador de la partida"
            return base + (" — el golpe que cerró la partida" if k["turn"] >= last_turn else "")
        if w == "barrida":
            return "barrió el tablero: limpió las criaturas en juego y frenó a la mesa"
        if w == "ult de planeswalker":
            return "ultimate de un planeswalker: un efecto grande de una sola vez"
        s = f"en ese turno un rival perdió {k.get('dmg', 0)} de vida"
        if k.get("dmg", 0) and k["dmg"] == maxdmg:
            s += " — el mayor golpe de la partida"
        return s

    def _best_reason(b):
        s = f"le quitó {b['delta']} de vida al rival en ese turno"
        if b["delta"] == maxdelta and maxdelta:
            s += " (su golpe más fuerte)"
        return s

    for k in key:
        k["reason"] = _key_reason(k)
    for b in best:
        b["reason"] = _best_reason(b)

    key.sort(key=lambda k: (k["why"] != "eliminación", k["why"] != "barrida", -k.get("step", 0)))
    key = key[:8]
    best.sort(key=lambda b: b["delta"], reverse=True)
    best = best[:5]

    # --- errores aproximados de los perdedores ---
    mistakes = []
    losers = [n for n in names if n != winner]
    # último turno de cada jugador para medir tierras/actividad
    for n in losers:
        lands_by_turn = {}
        casts = 0
        for s in steps:
            actor = names[s["active"]] if 0 <= s["active"] < len(names) else None
            if actor != n:
                continue
            if _CAST.search(s["label"]):
                casts += 1
            p = _by_name(s["players"]).get(n) or {}
            lands = sum(1 for pm in (p.get("battlefield") or []) if pm.get("is_land"))
            lands_by_turn[s["turn"]] = lands
        # OJO: s["turn"] es el contador GLOBAL (sube por cada turno de cada jugador).
        # Para medir actividad hay que usar los turnos PROPIOS, no el máximo global.
        myturns = len(lands_by_turn)                      # turnos que jugó este rival
        last_lands = lands_by_turn.get(max(lands_by_turn), 0) if lands_by_turn else 0
        note = None
        if myturns >= 5 and last_lands <= 2:
            note = "trabado de maná (pocas tierras)"
        elif casts == 0 and myturns >= 3:
            note = "no llegó a desplegar su plan"
        elif (last_lands >= 8 and casts <= myturns // 2
              and (last_lands - casts) >= 4):
            # inundación REAL: muchas tierras, pocos hechizos y brecha grande entre
            # tierras jugadas y cosas lanzadas (no solo "tiene 7 tierras en turno 20").
            note = "inundado de tierras (poca acción)"
        elif casts <= max(1, myturns // 3) and myturns >= 6:
            note = "arranque lento (pocas jugadas)"
        # si no cae en ningún patrón: jugó normal y lo superó el rival (sin nota)
        if note:
            mistakes.append({"player": n, "note": note})

    # --- habilidades que se activaron (agrupadas por carta) ---
    turn_to_step = {}
    for i, s in enumerate(steps):
        turn_to_step.setdefault(s["turn"], i)
    groups = {}
    order = []
    for ev in (ability_events or []):
        cardn = ev.get("card")
        if not cardn:
            continue
        g = groups.get(cardn)
        if g is None:
            g = {"card": cardn, "controller": ev.get("controller"),
                 "count": 0, "turns": set(), "kinds": []}
            groups[cardn] = g
            order.append(cardn)
        g["count"] += 1
        g["turns"].add(ev.get("turn", 0))
        if ev.get("kind") and ev["kind"] not in g["kinds"]:
            g["kinds"].append(ev["kind"])
    abilities = []
    for cardn in order:
        g = groups[cardn]
        tsorted = sorted(g["turns"])
        abilities.append({"card": g["card"], "controller": g["controller"],
                          "count": g["count"], "turns": tsorted,
                          "kinds": g["kinds"], "step": turn_to_step.get(tsorted[0], 0)})
    abilities.sort(key=lambda x: (-x["count"], x["card"]))
    abilities = abilities[:30]

    # --- encadenamiento: key plays de los últimos ~4 turnos ---
    chain = [k for k in sorted(key, key=lambda k: k.get("step", 0))
             if k["turn"] >= max(1, turns - 3)]

    win_line = f"Ganó {winner} en {turns} turnos"
    if win_type == "daño de comandante" and victim:
        win_line += f" por daño de comandante sobre {victim}"
    elif win_type in ("combate/quema", "veneno") and victim:
        win_line += f" por {win_type} sobre {victim}"
    elif win_type == "último en pie":
        win_line += ", quedando último en pie"
    summary = win_line + "."

    return {"win_type": win_type, "summary": summary,
            "key_plays": key, "best_moves": best,
            "mistakes": mistakes, "chain": chain, "abilities": abilities}
