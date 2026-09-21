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


def analyze(trace, winner, players):
    names = [p.name for p in players]
    steps = trace or []
    if not steps:
        return {"win_type": "?", "summary": "Sin datos de la partida.",
                "key_plays": [], "best_moves": [], "mistakes": [], "chain": []}

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
    for i, s in enumerate(steps):
        pm = _by_name(s["players"])
        actor = names[s["active"]] if 0 <= s["active"] < len(names) else None
        label = s["label"]
        # daño causado este step = caída de vida de rivales
        dmg = 0
        for n, p in pm.items():
            d = prev_life.get(n, 40) - (p.get("life") or 0)
            if n != actor and d > 0:
                dmg += d
            prev_life[n] = p.get("life") or 0
        # eventos definitorios
        why = None
        if _WIPE.search(label):
            why = "barrida"
        elif _ULT.search(label):
            why = "ult de planeswalker"
        elif dmg >= 6:
            why = f"{dmg} de daño"
        if why:
            key.append({"turn": s["turn"], "label": label, "why": why, "step": i})
        if actor == winner and dmg > 0:
            best.append({"turn": s["turn"], "label": label, "delta": dmg, "step": i})

    key.sort(key=lambda k: (k["why"] != "barrida", -k.get("step", 0)))
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
        maxturn = max(lands_by_turn) if lands_by_turn else 0
        last_lands = lands_by_turn.get(maxturn, 0)
        if maxturn >= 5 and last_lands <= 2:
            mistakes.append({"player": n, "note": "trabado de maná (pocas tierras)"})
        elif last_lands >= 7 and casts <= maxturn // 2:
            mistakes.append({"player": n, "note": "inundado de tierras (poca acción)"})
        if casts == 0 and maxturn >= 2:
            mistakes.append({"player": n, "note": "no llegó a desplegar su plan"})

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
            "mistakes": mistakes, "chain": chain}
