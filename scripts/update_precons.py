#!/usr/bin/env python3
"""Revisión mensual de precons de Commander.

Baja el índice de mazos precon de Commander desde MTGJSON, lo compara con la
instantánea guardada y:
  - actualiza la instantánea `api/precons_index.json` (el /api/precons la usa como
    respaldo cuando MTGJSON está caído),
  - descarga las decklists NUEVAS a `data/precons/decks/<fileName>.txt`,
  - imprime un reporte de los mazos nuevos (y lo escribe en `data/precons/NEW.md`).

Pensado para correr mensualmente (GitHub Action) y abrir un PR con los cambios,
pero también sirve a mano:  python3 scripts/update_precons.py [--download] [--dry-run]

No requiere dependencias externas (urllib). La red a MTGJSON debe estar abierta
(en el contenedor del agente suele estar bloqueada; corre en CI).
"""
import argparse
import datetime as _dt
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "api"))

SNAPSHOT = os.path.join(_ROOT, "api", "precons_index.json")
DECKS_DIR = os.path.join(_ROOT, "data", "precons", "decks")
REPORT = os.path.join(_ROOT, "data", "precons", "NEW.md")


def load_snapshot(path=SNAPSHOT):
    """Instantánea previa: {'updated': ISO, 'precons': [ {code, fileName, name,
    releaseDate}, ... ]}. Si no existe o está corrupta, devuelve vacía."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("precons"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"updated": None, "precons": []}


def diff_new(old_precons, new_precons):
    """Precons presentes en `new` cuyo `code` no estaba en `old`. Preserva el orden
    de `new` (MTGJSON ya los entrega del más reciente al más viejo)."""
    seen = {p.get("code") for p in old_precons if p.get("code")}
    return [p for p in new_precons if p.get("code") and p.get("code") not in seen]


def _safe_slug(file_name):
    return "".join(c for c in (file_name or "") if c.isalnum() or c in ("_", "-"))


def write_snapshot(precons, path=SNAPSHOT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"updated": _dt.date.today().isoformat(), "precons": precons}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_report(new, path=REPORT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    today = _dt.date.today().isoformat()
    lines = [f"# Precons nuevos — revisión {today}", ""]
    if not new:
        lines.append("Sin precons nuevos desde la última revisión.")
    else:
        lines.append(f"{len(new)} mazo(s) nuevo(s):")
        lines.append("")
        lines.append("| Lanzamiento | Código | Mazo |")
        lines.append("|---|---|---|")
        for p in new:
            lines.append(f"| {p.get('releaseDate','?')} | {p.get('code','?')} "
                         f"| {p.get('name','?')} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def download_decklists(new, out_dir=DECKS_DIR):
    """Baja la decklist de cada precon nuevo a un .txt (formato que carga el editor)."""
    import _precon
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for p in new:
        fn = p.get("fileName")
        if not fn:
            continue
        try:
            got = _precon.precon_to_text(fn)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! no se pudo bajar {fn}: {exc}", file=sys.stderr)
            continue
        dest = os.path.join(out_dir, _safe_slug(fn) + ".txt")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(got.get("text", ""))
        saved.append(dest)
    return saved


def main(argv=None):
    ap = argparse.ArgumentParser(description="Revisión mensual de precons de Commander")
    ap.add_argument("--download", action="store_true",
                    help="bajar la decklist de cada precon nuevo a data/precons/decks/")
    ap.add_argument("--dry-run", action="store_true",
                    help="no escribe archivos; solo reporta qué cambiaría")
    args = ap.parse_args(argv)

    import _precon
    _precon._cache_index = None     # fuerza una lectura fresca de la red
    current = _precon.list_precons()
    old = load_snapshot()
    new = diff_new(old.get("precons", []), current)

    print(f"precons en MTGJSON: {len(current)} | conocidos: "
          f"{len(old.get('precons', []))} | nuevos: {len(new)}")
    for p in new:
        print(f"  + {p.get('releaseDate','?')}  {p.get('code','?'):8s}  {p.get('name','?')}")

    if args.dry_run:
        print("(dry-run: no se escribió nada)")
        return 0

    write_snapshot(current)
    write_report(new)
    if args.download and new:
        saved = download_decklists(new)
        print(f"decklists bajadas: {len(saved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
