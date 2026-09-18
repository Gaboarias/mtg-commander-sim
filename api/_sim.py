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

try:
    import _scry      # cliente Scryfall (solo en Vercel con red)
except Exception:     # noqa: BLE001
    _scry = None

MAX_N = 2000          # tope de partidas por request (serverless timeout)
MAX_CARDS = 200       # tope de entradas de decklist


def deck_list():
    out = []
    for name in decks.DECKS:
        _, commander = decks.build(name)
        out.append({"key": name, "commander": commander.name,
                    "identity": sorted(commander.identity())})
    return out


def simulate(matchup, n):
    matchup = [m for m in matchup if m in decks.DECKS]
    if len(matchup) < 2:
        raise ValueError("hacen falta al menos 2 mazos validos")
    n = max(1, min(int(n), MAX_N))
    wins = run.many(matchup, n=n, verbose=False)
    total = n
    results = [{"deck": k, "wins": wins.get(k, 0),
                "pct": round(100 * wins.get(k, 0) / total, 1)} for k in matchup]
    results.append({"deck": "EMPATE", "wins": wins.get("EMPATE", 0),
                    "pct": round(100 * wins.get("EMPATE", 0) / total, 1)})
    return {"matchup": matchup, "n": n, "results": results}


def game_log(matchup, seed):
    matchup = [m for m in matchup if m in decks.DECKS]
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

def _make_fetch(names):
    if _scry is None:
        return None
    return _scry.make_fetch([n for n in names if n])


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
    parsed = decklist.parse_decklist(text or "")
    if len(parsed["cards"]) > MAX_CARDS:
        raise ValueError(f"demasiadas cartas (max {MAX_CARDS})")
    names = ([parsed["commander"]] if parsed["commander"] else []) + \
            [n for _, n in parsed["cards"]]
    fetch = _make_fetch(names)

    cmd_name = parsed.get("commander")
    cmd_card = cardsdb.resolve(cmd_name, fetch) if cmd_name else None
    commander = None
    if cmd_card is not None:
        commander = _card_row(cmd_name, 1, cmd_card)

    rows = []
    missing = []
    implemented = 0
    total = 0
    suggested = None
    for qty, name in parsed["cards"]:
        card = cardsdb.resolve(name, fetch)
        row = _card_row(name, qty, card)
        rows.append(row)
        total += qty
        if card is None:
            missing.append(name)
        elif cardsdb.is_implemented(name):
            implemented += qty
        # auto-sugerir comandante: primera legendaria criatura/planeswalker
        if suggested is None and row.get("can_command"):
            suggested = row["name"]
    # Game Changers + estimacion de bracket (#4)
    all_names = ([cmd_name] if cmd_name else []) + [n for _, n in parsed["cards"]]
    gcs = gamechangers.find_in(all_names)
    est_bracket, est_label = gamechangers.bracket_hint(len(gcs))
    m = re.search(r"bracket[:\s]+([1-5])", text or "", re.IGNORECASE)
    declared_bracket = int(m.group(1)) if m else None

    return {
        "commander": commander,
        "commander_name": cmd_name,
        "commander_suggested": suggested,
        "cards": rows,
        "total": total,
        "implemented": implemented,
        "missing": missing,
        "scryfall_online": _scry is not None,
        "game_changers": gcs,
        "bracket_estimate": est_bracket,
        "bracket_label": est_label,
        "bracket_declared": declared_bracket,
    }


def _build_deck_defs(specs):
    """Arma [(label, deck, commander)] desde specs (registered/custom) con una
    sola resolucion de Scryfall para los custom. Devuelve (deck_defs, max_turns).
    """
    specs = [s for s in specs if s][:6]
    if len(specs) < 2:
        raise ValueError("elegí al menos 2 decks")

    custom_names = []
    for s in specs:
        if s.get("kind") == "custom":
            parsed = decklist.parse_decklist(s.get("text", ""))
            s["_parsed"] = parsed
            if parsed.get("commander"):
                custom_names.append(parsed["commander"])
            custom_names += [nm for _, nm in parsed["cards"]]
    fetch = _make_fetch(custom_names) if custom_names else None

    deck_defs = []
    seen = {}
    for s in specs:
        if s.get("kind") == "registered":
            key = s.get("key")
            if key not in decks.DECKS:
                raise ValueError(f"deck desconocido: {key}")
            deck, cmd = decks.build(key)
            label = s.get("name") or key
        else:
            deck, cmd, _rep = decklist.build_deck(s["_parsed"], fetch=fetch)
            label = s.get("name") or cmd.name
        base = label
        k = seen.get(base, 0)
        seen[base] = k + 1
        if k:
            label = f"{base} ({k + 1})"
        deck_defs.append((label, deck, cmd))

    # mas jugadores -> mas turnos para que la partida se resuelva
    max_turns = min(320, 40 + 40 * len(deck_defs))
    return deck_defs, max_turns


_LEVELS = ("novato", "intermedio", "avanzado")


def _lvl(level):
    return level if level in _LEVELS else "intermedio"


def match(specs, n=120, level="intermedio"):
    """Simula una mesa de 2 a 6 decks. Devuelve winrate por deck + notas
    (analitica en bulk) + partidas (para exportar)."""
    from collections import Counter
    from engine import Game

    n = max(1, min(int(n), 500))
    level = _lvl(level)
    deck_defs, max_turns = _build_deck_defs(specs)
    labels = [lbl for lbl, _d, _c in deck_defs]
    nplayers = len(deck_defs)
    deck_by_label = {lbl: deck for lbl, deck, _c in deck_defs}

    wins = Counter()
    turns_total = 0
    games = []
    cmd_turns = {l: [] for l in labels}
    cast_counts = {l: Counter() for l in labels}

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

    results = [{"deck": lbl, "wins": wins.get(lbl, 0),
                "pct": round(100 * wins.get(lbl, 0) / n, 1)} for lbl in labels]
    results.sort(key=lambda r: -r["pct"])
    results.append({"deck": "sin definir", "wins": wins.get("EMPATE", 0),
                    "pct": round(100 * wins.get("EMPATE", 0) / n, 1)})

    # notas por deck: turno del comandante y cartas que rara vez se juegan
    deck_notes = []
    for lbl in labels:
        cts = cmd_turns[lbl]
        cmd_avg = round(sum(cts) / len(cts) / nplayers, 1) if cts else None
        seen_names = set()
        rates = []
        for c in deck_by_label[lbl]:
            if c.is_land() or c.cost is None or c.name in seen_names:
                continue
            seen_names.add(c.name)
            rates.append((c.name, round(100 * cast_counts[lbl].get(c.name, 0) / n)))
        rates.sort(key=lambda x: x[1])
        slow = [{"name": nm, "pct": p} for nm, p in rates[:6] if p < 50]
        deck_notes.append({
            "deck": lbl,
            "commander_avg_turn": cmd_avg,
            "commander_pct": round(100 * len(cts) / n),
            "slow_cards": slow,
        })

    notes = {
        "avg_rounds": round(turns_total / n / nplayers, 1),
        "decided_pct": round(100 * (n - wins.get("EMPATE", 0)) / n),
        "decks": deck_notes,
    }
    return {"n": n, "players": nplayers, "level": level, "results": results,
            "notes": notes, "games": games}


def match_log(specs, level="intermedio"):
    """Juega UNA partida de la mesa y devuelve el relato turno a turno."""
    deck_defs, max_turns = _build_deck_defs(specs)
    g = run.play_defs(deck_defs, seed=0, log=False, max_turns=max_turns,
                      level=_lvl(level))
    winner = g.play()
    return {"players": len(deck_defs), "winner": winner, "turns": g.turn,
            "log": g.log_lines}


def simulate_custom(cards_list, commander_name, opponent, n):
    """Simula un deck editado (lista de {name, qty}) contra un mazo registrado."""
    if opponent not in decks.DECKS:
        raise ValueError(f"oponente desconocido: {opponent}")
    n = max(1, min(int(n), MAX_N))
    entries = [(int(c.get("qty", 1)), c["name"]) for c in cards_list
               if c.get("name")]
    parsed = {"commander": commander_name, "cards": entries}
    names = [commander_name] + [name for _, name in entries]
    fetch = _make_fetch(names)
    deck, cmd, report = decklist.build_deck(parsed, fetch=fetch)

    odeck, ocmd = decks.build(opponent)
    defs = [("importado", deck, cmd), (opponent, odeck, ocmd)]
    wins = run.many_defs(defs, n=n)
    results = [
        {"deck": "importado", "wins": wins.get("importado", 0),
         "pct": round(100 * wins.get("importado", 0) / n, 1)},
        {"deck": opponent, "wins": wins.get(opponent, 0),
         "pct": round(100 * wins.get(opponent, 0) / n, 1)},
        {"deck": "EMPATE", "wins": wins.get("EMPATE", 0),
         "pct": round(100 * wins.get("EMPATE", 0) / n, 1)},
    ]
    return {"n": n, "opponent": opponent, "results": results, "report": report}
