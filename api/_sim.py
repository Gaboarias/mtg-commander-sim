"""Puente entre las funciones serverless de Vercel y el motor en la raiz.

Agrega la raiz del repo al sys.path para poder importar engine/decks/run/etc.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import decks          # noqa: E402
import run            # noqa: E402
import coverage       # noqa: E402
import re            # noqa: E402
import cardsdb        # noqa: E402
import decklist       # noqa: E402
import gamechangers   # noqa: E402
from engine import Game, Player, COLORS  # noqa: E402
from policy import Policy        # noqa: E402
import _matchanalysis  # noqa: E402

try:
    import _scry      # cliente Scryfall (solo en Vercel con red)
except Exception:     # noqa: BLE001
    _scry = None

MAX_N = 2000          # tope de partidas por request (serverless timeout)
FREE_N = 100          # tope gratis de partidas por request (supporter sube a MAX_N)
MAX_CARDS = 200       # tope de entradas de decklist
MAX_DECKS = 6         # tope de mazos por mesa
BUDGET_S = 50.0       # la función serverless corta a los 60s: paramos antes


def _play_budgeted(play_one, n, budget=BUDGET_S):
    """Corre hasta n partidas (`play_one(seed) -> ganador`) y corta si se pasa del
    presupuesto de tiempo (siempre al menos 1). Devuelve (Counter, corridas)."""
    import time
    from collections import Counter
    start = time.monotonic()
    wins = Counter()
    ran = 0
    for i in range(n):
        wins[play_one(i)] += 1
        ran = i + 1
        if ran < n and time.monotonic() - start > budget:
            break
    return wins, ran


def _check_parsed(parsed):
    """Rechaza listas con demasiadas entradas (la cantidad por línea ya viene
    acotada por decklist.parse_decklist)."""
    if len(parsed["cards"]) > MAX_CARDS:
        raise ValueError(f"demasiadas cartas (max {MAX_CARDS})")
    return parsed


def deck_list():
    """Solo los ejemplos publicos (temas de precon). Los presets personales del
    usuario no se listan aca: un usuario nuevo arranca sin decks propios."""
    keys = getattr(decks, "EXAMPLES", None) or list(decks.DECKS)
    theme = getattr(decks, "EXAMPLE_THEME", {})
    out = []
    for name in keys:
        _, commander = decks.build(name)
        out.append({"key": name, "commander": commander.name,
                    "identity": sorted(commander.identity()),
                    "theme": theme.get(name, "ejemplo")})
    return out


def simulate(matchup, n):
    """GET público sin identidad: tope gratis de partidas, mazos sin repetir
    (con claves repetidas los wins se mezclaban) y presupuesto de tiempo."""
    matchup = list(dict.fromkeys(m for m in matchup if m in decks.DECKS))[:MAX_DECKS]
    if len(matchup) < 2:
        raise ValueError("hacen falta al menos 2 mazos validos (distintos)")
    n = max(1, min(int(n), FREE_N))
    wins, ran = _play_budgeted(lambda seed: run.one(matchup, seed=seed), n)
    results = [{"deck": k, "wins": wins.get(k, 0),
                "pct": round(100 * wins.get(k, 0) / ran, 1)} for k in matchup]
    results.append({"deck": "EMPATE", "wins": wins.get("EMPATE", 0),
                    "pct": round(100 * wins.get("EMPATE", 0) / ran, 1)})
    return {"matchup": matchup, "n": ran, "requested": n,
            "timed_out": ran < n, "results": results}


def game_log(matchup, seed):
    matchup = [m for m in matchup if m in decks.DECKS][:MAX_DECKS]
    if len(matchup) < 2:
        raise ValueError("hacen falta al menos 2 mazos validos")
    g = run._build_game(matchup, seed=int(seed), log=False)
    winner = g.play()
    return {"matchup": matchup, "seed": int(seed), "winner": winner,
            "turns": g.turn, "log": g.log_lines}


def coverage_report():
    rows = coverage.report(verbose=False)
    return {"coverage": [{"deck": name, "implemented": impl, "vanilla": van}
                         for name, impl, van in rows]}


# --------------------------------------------------------------------------- #
# Import / edicion de decks (Scryfall en Vercel)
# --------------------------------------------------------------------------- #

def _make_fetch(names, local_first=False):
    """fetch(nombre)->datos de Scryfall. Con local_first, los nombres que ya están en
    la base local (data/cards_db.json.gz) no se piden a Scryfall (cardsdb.resolve
    los toma de ahí): simular un precon no gasta red."""
    if _scry is None:
        return None
    if local_first:
        names = [n for n in names if n and cardsdb.local_card(n) is None]
    return _scry.make_fetch([n for n in names if n])


def _price_legal(raw):
    """Del dict crudo de Scryfall: (precio_usd|None, legal_en_commander:bool)."""
    if not raw:
        return None, True
    price = None
    try:
        v = (raw.get("prices") or {}).get("usd")
        price = float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    leg = (raw.get("legalities") or {}).get("commander")
    legal = leg in (None, "legal", "restricted")   # desconocido = no marcar ilegal
    return price, legal


def _card_row(name, qty, card):
    """Descriptor para la tabla editable del frontend."""
    if card is None:
        return {"name": name, "qty": qty, "source": "missing",
                "implemented": False, "type": "?", "cost": "?", "pt": ""}
    exact = cardsdb.is_implemented(name)
    generic = (not exact) and bool(
        card.on_etb or card.on_cast_resolve or card.on_death or card.triggers
        or card.static_mod or card.loyalty_abilities or card.counter_modifier)
    source = ("registry" if exact
              else "basic" if "basic" in card.supertypes
              else "scryfall")
    cost = ""
    if card.cost is not None:
        cost = (str(card.cost.generic) if card.cost.generic else "") + \
               "".join(card.cost.pips)
    types = " ".join(sorted(card.types))
    pt = f"{card.power}/{card.toughness}" if "creature" in card.types else ""
    colors = sorted(card.identity())
    can_command = ("legendary" in card.supertypes and
                   bool({"creature", "planeswalker"} & card.types))
    return {"name": card.name, "qty": qty, "source": source,
            "implemented": exact, "generic": generic, "can_command": can_command,
            "type": types, "cost": cost, "pt": pt, "colors": colors}


def resolve_decklist(text):
    """Parsea una lista y resuelve cada carta (registro + Scryfall). Devuelve
    la tabla editable, el comandante y un resumen de cobertura."""
    parsed = _check_parsed(decklist.parse_decklist(text or ""))
    names = list(parsed.get("commanders") or
                 ([parsed["commander"]] if parsed["commander"] else [])) + \
        [n for _, n in parsed["cards"]]
    fetch = _make_fetch(names)

    def _attach_price_legal(row, name, qty):
        price, legal = _price_legal(fetch(name)) if fetch else (None, True)
        row["price"] = price
        row["legal"] = legal
        return price

    cmd_name = parsed.get("commander")
    cmd_card = cardsdb.resolve(cmd_name, fetch) if cmd_name else None
    commander = None
    if cmd_card is not None:
        commander = _card_row(cmd_name, 1, cmd_card)
        _attach_price_legal(commander, cmd_name, 1)
    # segundo comandante (partner / background)
    partner_name = (parsed.get("commanders") or [None, None])[1:2]
    partner_name = partner_name[0] if partner_name else None
    partner = None
    if partner_name:
        p_card = cardsdb.resolve(partner_name, fetch)
        partner = _card_row(partner_name, 1, p_card)
        _attach_price_legal(partner, partner_name, 1)

    rows = []
    missing = []
    illegal = []
    implemented = 0
    total = 0
    price_total = 0.0
    suggested = None
    for qty, name in parsed["cards"]:
        card = cardsdb.resolve(name, fetch)
        row = _card_row(name, qty, card)
        price = _attach_price_legal(row, name, qty)
        if price:
            price_total += price * qty
        if row.get("legal") is False:
            illegal.append(row["name"])
        rows.append(row)
        total += qty
        if card is None:
            missing.append(name)
        elif cardsdb.is_implemented(name):
            implemented += qty
        # auto-sugerir comandante: primera legendaria criatura/planeswalker
        if suggested is None and row.get("can_command"):
            suggested = row["name"]
    if commander and commander.get("price"):
        price_total += commander["price"]
    if partner and partner.get("price"):
        price_total += partner["price"]
    # Game Changers + estimacion de bracket (#4)
    all_names = ([cmd_name] if cmd_name else []) + ([partner_name] if partner_name else []) \
        + [n for _, n in parsed["cards"]]
    gcs = gamechangers.find_in(all_names)
    est_bracket, est_label, bracket_info = gamechangers.estimate_bracket(all_names)
    m = re.search(r"bracket[:\s]+([1-5])", text or "", re.IGNORECASE)
    declared_bracket = int(m.group(1)) if m else None

    return {
        "commander": commander,
        "commander_name": cmd_name,
        "partner": partner,
        "partner_name": partner_name,
        "commander_suggested": suggested,
        "cards": rows,
        "total": total,
        "implemented": implemented,
        "missing": missing,
        "scryfall_online": _scry is not None,
        "game_changers": gcs,
        "bracket_estimate": est_bracket,
        "bracket_label": est_label,
        "bracket_reasons": bracket_info["reasons"],
        "bracket_signals": bracket_info["found"],
        "bracket_declared": declared_bracket,
        "price_total": round(price_total, 2),
        "illegal": illegal,
    }


def _build_deck_defs(specs):
    """Arma [(label, deck, commander)] desde specs (registered/custom) con una
    sola resolucion de Scryfall para los custom. Devuelve
    (deck_defs, max_turns, unresolved) con unresolved = {label: [cartas]}.
    """
    specs = [s for s in (specs or []) if isinstance(s, dict)][:MAX_DECKS]
    if len(specs) < 2:
        raise ValueError("elegí al menos 2 decks")
    for s in specs:
        if s.get("kind") not in ("registered", "custom"):
            raise ValueError(f"tipo de deck desconocido: {s.get('kind')!r}")

    custom_names = []
    for s in specs:
        if s.get("kind") == "custom":
            parsed = _check_parsed(decklist.parse_decklist(s.get("text") or ""))
            s["_parsed"] = parsed
            custom_names += list(parsed.get("commanders") or
                                 ([parsed["commander"]] if parsed.get("commander") else []))
            custom_names += [nm for _, nm in parsed["cards"]]
    fetch = _make_fetch(custom_names, local_first=True) if custom_names else None

    deck_defs = []
    unresolved = {}
    seen = {}
    for s in specs:
        missing = []
        if s.get("kind") == "registered":
            key = s.get("key")
            if key not in decks.DECKS:
                raise ValueError(f"deck desconocido: {key}")
            deck, cmd = decks.build(key)
            label = s.get("name") or key
        else:
            deck, cmd, rep = decklist.build_deck(s["_parsed"], fetch=fetch)
            label = s.get("name") or cmd.name
            missing = rep.get("unresolved") or []
            total = len(s["_parsed"]["cards"])
            # si no resuelve ni la mitad (Scryfall caído / rate limit) el mazo
            # sería casi todo básicas: mejor fallar que simular otra cosa
            if total and len(missing) * 2 > total:
                raise ValueError(
                    f"«{label}»: no se pudieron resolver {len(missing)} de {total} "
                    "cartas (¿Scryfall no disponible?). Probá de nuevo en un rato.")
        base = label
        k = seen.get(base, 0)
        seen[base] = k + 1
        if k:
            label = f"{base} ({k + 1})"
        deck_defs.append((label, deck, cmd))
        if missing:
            unresolved[label] = missing

    # mas jugadores -> mas turnos para que la partida se resuelva
    max_turns = min(320, 40 + 40 * len(deck_defs))
    return deck_defs, max_turns, unresolved


_LEVELS = ("novato", "intermedio", "avanzado")


def _lvl(level):
    return level if level in _LEVELS else "intermedio"


def _slow_reason(card, land_count, avg_rounds):
    """Motivo probable (heurístico) de por qué una carta se jugó poco: falta de
    maná / coste, ser reactiva (depende del rival) o depender de otras piezas."""
    cmc = card.cost.cmc if card.cost else 0
    tags = getattr(card, "tags", None) or set()
    types = getattr(card, "types", None) or set()
    reactive = ("instant" in types or bool(getattr(card, "target_spec", None))
                or bool({"removal", "counter", "protection", "wipe"} & tags))
    # coste alto para lo que duran las partidas
    if cmc >= 6 and avg_rounds < cmc + 1:
        return f"cuesta mucho (CMC {cmc}) para lo que suelen durar las partidas: rara vez hay maná a tiempo"
    if land_count and land_count < 34 and cmc >= 4:
        return f"coste {cmc} y el mazo tiene pocas tierras ({land_count}): a veces falta maná para lanzarla"
    if reactive:
        return "es reactiva (respuesta o remoción): se guarda para el momento justo y depende de lo que hagan los rivales"
    if cmc >= 5:
        return f"coste alto (CMC {cmc}): pocas veces hay maná disponible para jugarla"
    return "es situacional: rinde cuando ya tenés otras piezas del mazo en juego (poca química por sí sola)"


def match(specs, n=120, level="intermedio"):
    """Simula una mesa de 2 a 6 decks. Devuelve winrate por deck + notas
    (analitica en bulk) + partidas (para exportar)."""
    import time
    from collections import Counter
    from engine import Game

    n = max(1, min(int(n), 500))
    level = _lvl(level)
    deck_defs, max_turns, unresolved = _build_deck_defs(specs)
    labels = [lbl for lbl, _d, _c in deck_defs]
    nplayers = len(deck_defs)
    deck_by_label = {lbl: deck for lbl, deck, _c in deck_defs}

    wins = Counter()
    turns_total = 0
    games = []
    cmd_turns = {l: [] for l in labels}
    cast_counts = {l: Counter() for l in labels}

    # presupuesto de tiempo: la función serverless corta a los 60s. Paramos antes
    # (y devolvemos lo simulado hasta ahí) para no dar 504 con mesas pesadas.
    start = time.monotonic()
    budget = 50.0
    ran = 0
    for i in range(n):
        players = run.build_players_from_defs(deck_defs, level=level)
        g = Game(players, seed=i, max_turns=max_turns)
        w = g.play()
        wins[w] += 1
        turns_total += g.turn
        games.append({"seed": i, "winner": w, "turns": g.turn})
        for p in players:
            st = p.stats
            if st["commander_turn"] is not None:
                cmd_turns[p.name].append(st["commander_turn"])
            cast_counts[p.name].update(st["cast_counts"])
        ran = i + 1
        # corta tras cada partida si ya nos pasamos del presupuesto (al menos 1)
        if ran < n and time.monotonic() - start > budget:
            break

    d = max(1, ran)                      # divisor seguro (partidas realmente corridas)
    timed_out = ran < n

    results = [{"deck": lbl, "wins": wins.get(lbl, 0),
                "pct": round(100 * wins.get(lbl, 0) / d, 1)} for lbl in labels]
    results.sort(key=lambda r: -r["pct"])
    results.append({"deck": "sin definir", "wins": wins.get("EMPATE", 0),
                    "pct": round(100 * wins.get("EMPATE", 0) / d, 1)})

    # notas por deck: turno del comandante y cartas que rara vez se juegan
    avg_rounds = turns_total / d / nplayers if d else 0
    deck_notes = []
    for lbl in labels:
        cts = cmd_turns[lbl]
        cmd_avg = round(sum(cts) / len(cts) / nplayers, 1) if cts else None
        deck_cards = deck_by_label[lbl]
        land_count = sum(1 for c in deck_cards if c.is_land())
        seen_names = set()
        rates = []
        for c in deck_cards:
            if c.is_land() or c.cost is None or c.name in seen_names:
                continue
            seen_names.add(c.name)
            rates.append((c, round(100 * cast_counts[lbl].get(c.name, 0) / d)))
        rates.sort(key=lambda x: x[1])
        slow = [{"name": c.name, "pct": p,
                 "reason": _slow_reason(c, land_count, avg_rounds)}
                for c, p in rates[:6] if p < 50]
        deck_notes.append({
            "deck": lbl,
            "commander_avg_turn": cmd_avg,
            "commander_pct": round(100 * len(cts) / d),
            "slow_cards": slow,
        })

    notes = {
        "avg_rounds": round(turns_total / d / nplayers, 1),
        "decided_pct": round(100 * (ran - wins.get("EMPATE", 0)) / d),
        "decks": deck_notes,
    }
    return {"n": ran, "requested": n, "timed_out": timed_out,
            "players": nplayers, "level": level, "results": results,
            "notes": notes, "games": games, "unresolved": unresolved}


def _art_url(card):
    """Saca la mejor URL de arte de un dict de Scryfall (o de su cara frontal)."""
    iu = card.get("image_uris") or {}
    if not iu and card.get("card_faces"):
        iu = (card["card_faces"][0].get("image_uris") or {})
    return iu.get("art_crop") or iu.get("normal") or iu.get("small")


def _card_images(names):
    """{nombre: url_de_arte} para los nombres que existan en Scryfall. Las cartas
    caseras de los ejemplos no resuelven -> el front usa un placeholder."""
    names = [n for n in names if n]
    if _scry is None or not names:
        return {}
    data = _scry.resolve_many(names)
    out = {}
    for n in names:
        card = data.get(_scry._norm(n))
        if card:
            url = _art_url(card)
            if url:
                out[n] = url
    return out


def resolve_decks(texts):
    """Resuelve (via Scryfall) todas las cartas de una lista de decklists y
    devuelve {nombre_norm: datos_scryfall}. Lo usa /play para armar decks
    importados dentro de Pyodide sin necesitar red en el navegador."""
    names = set()
    for t in texts or []:
        parsed = decklist.parse_decklist(t or "")
        for c in (parsed.get("commanders") or
                  ([parsed["commander"]] if parsed.get("commander") else [])):
            names.add(c)
        for _q, n in parsed["cards"]:
            names.add(n)
    names = [n for n in names if n]
    # primero la base local (sin red); a Scryfall solo lo que falte
    local = {}
    for n in names:
        row = cardsdb.local_card(n)
        if row is not None:
            local[_scry._norm(n) if _scry else n.lower()] = row
    if _scry is None or not names:
        return local
    names = [n for n in names if cardsdb.local_card(n) is None]
    data = _scry.resolve_many(names) if names else {}
    data.update(local)
    # Fallback difuso: para los nombres que no matchearon exacto (typos, acentos,
    # nombre parcial en una lista pegada) intentamos la mejor coincidencia de
    # Scryfall y la guardamos bajo el nombre original. Cap para no abusar de la API.
    missing = [n for n in names if _scry._norm(n) not in data]
    for n in missing[:20]:
        try:
            hit = _scry.named_fuzzy(n)
        except Exception:  # noqa: BLE001
            hit = None
        if hit and hit.get("name"):
            data[_scry._norm(n)] = hit
    return data


def card_info(names):
    """{nombre: {art, type, oracle}} desde Scryfall para las cartas reales.
    Las cartas caseras no aparecen (el front usa lo que trae el motor)."""
    names = [n for n in names if n]
    if _scry is None or not names:
        return {}
    data = _scry.resolve_many(names)
    out = {}
    for n in names:
        c = data.get(_scry._norm(n))
        if not c:
            continue
        oracle = c.get("oracle_text") or ""
        if not oracle and c.get("card_faces"):
            oracle = c["card_faces"][0].get("oracle_text", "")
        out[n] = {"art": _art_url(c), "type": c.get("type_line", ""),
                  "oracle": oracle}
    return out


def replay(specs, seed=0, level="intermedio"):
    """Juega UNA partida con la traza activa y devuelve los pasos para el
    reproductor visual (Fase 1) + un mapa de arte por carta."""
    deck_defs, max_turns, unresolved = _build_deck_defs(specs)
    players = run.build_players_from_defs(deck_defs, level=_lvl(level))
    g = Game(players, seed=int(seed), max_turns=max_turns, trace=True)
    winner = g.play()

    names = set()
    for step in g.trace:
        for pl in step["players"]:
            names.update(pl["commander"])
            names.update(pl["graveyard"])
            for pm in pl["battlefield"]:
                names.add(pm["name"])
    return {
        "players": [p.name for p in players],
        "winner": winner,
        "turns": g.turn,
        "steps": g.trace,
        "log": list(g.log_lines),      # relato completo (líneas T-prefijadas)
        "analysis": _matchanalysis.analyze(g.trace, winner, players,
                                           getattr(g, "ability_events", None)),
        "images": _card_images(names),
        "unresolved": unresolved,
    }


def match_log(specs, level="intermedio"):
    """Juega UNA partida de la mesa y devuelve el relato turno a turno."""
    deck_defs, max_turns, unresolved = _build_deck_defs(specs)
    g = run.play_defs(deck_defs, seed=0, log=False, max_turns=max_turns,
                      level=_lvl(level))
    winner = g.play()
    return {"players": len(deck_defs), "winner": winner, "turns": g.turn,
            "log": g.log_lines, "unresolved": unresolved}


def simulate_custom(cards_list, commander_name, opponent, n):
    """Simula un deck editado (lista de {name, qty}) contra un mazo registrado."""
    if opponent not in decks.DECKS:
        raise ValueError(f"oponente desconocido: {opponent}")
    n = max(1, min(int(n), MAX_N))
    entries = [(decklist.clamp_qty(c.get("qty", 1)), str(c["name"]))
               for c in (cards_list or []) if isinstance(c, dict) and c.get("name")]
    parsed = _check_parsed({"commander": commander_name, "cards": entries})
    names = [commander_name] + [name for _, name in entries]
    fetch = _make_fetch(names, local_first=True)
    deck, cmd, report = decklist.build_deck(parsed, fetch=fetch)

    odeck, ocmd = decks.build(opponent)
    defs = [("importado", deck, cmd), (opponent, odeck, ocmd)]
    wins, ran = _play_budgeted(lambda seed: run.play_defs(defs, seed=seed).play(), n)
    results = [
        {"deck": "importado", "wins": wins.get("importado", 0),
         "pct": round(100 * wins.get("importado", 0) / ran, 1)},
        {"deck": opponent, "wins": wins.get(opponent, 0),
         "pct": round(100 * wins.get(opponent, 0) / ran, 1)},
        {"deck": "EMPATE", "wins": wins.get("EMPATE", 0),
         "pct": round(100 * wins.get("EMPATE", 0) / ran, 1)},
    ]
    return {"n": ran, "requested": n, "timed_out": ran < n,
            "opponent": opponent, "results": results, "report": report}
