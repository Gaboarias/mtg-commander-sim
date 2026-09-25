# Instrucciones para Claude Code

## Que es esto

Motor de simulacion de Magic: The Gathering, formato Commander. Python puro, sin
dependencias externas. Sirve para medir con miles de partidas si un cambio a un
mazo mejora su tasa de victoria.

## Antes de tocar nada

```bash
python3 run.py                       # baseline, debe correr sin errores
python3 coverage.py                  # cuantas cartas tienen efecto real
python3 run.py lorehold kang --log   # partida comentada turno a turno
```

Guarda la salida de `run.py` antes de tu cambio. Cualquier modificacion al motor
que mueva los porcentajes mas de ~5 puntos sin que hayas tocado cartas es
sospechosa de bug.

## Reglas del proyecto

1. **`engine.py` no conoce cartas concretas.** Si para implementar una carta
   necesitas editar `engine.py`, lo que falta es un gancho generico. Anade el
   gancho, no el caso especial.

2. **`produces` devuelve opciones, no produccion simultanea.** Una tierra dual es
   `{R:1, W:1}` y vale UN mana. Este error ya se cometio una vez y hacia que los
   comandantes de 4 salieran en turno 2.

3. **Todo evento "en tu turno" o "cuando tu haces X" va en `Game.SELF_SCOPED`.**
   Si no, dispara para todos los jugadores. Este error ya se cometio dos veces.

4. **Despues de tocar mana o eventos, corre `--log` y verifica a mano** que los
   hechizos caen en el turno correcto segun su coste.

5. **No inventes texto de cartas.** Si no estas seguro del texto exacto, deja la
   carta como vainilla y anotala en `BACKLOG.md`. Una carta mal implementada
   contamina todas las estadisticas y es peor que una carta ausente.

6. **La pila no debe romper el determinismo headless.** Hechizos y habilidades
   pasan por la pila y por `_run_priority_and_resolve()`. En headless (sims/tests)
   no hay `reaction_check`, así que se drena sincrónicamente: misma semilla =>
   misma partida. La pausa `ReactionPause` solo vive en `interactive.py`. Tras
   tocar la pila, corre `python3 -c "import run; ...seeds..."` y confirma que
   `run.one(k, seed=i)` sigue siendo reproducible.

## Capa web e interactiva

- `interactive.py` = juego de UNA persona + bots (para `/play`). Usa `pending_choice`
  y `ReactionPause` para pausar en cada decisión del humano.
- `app/` (Next.js) + `api/*.py` (funciones Vercel que envuelven el motor). El motor
  también corre en el navegador vía Pyodide para `/play`.
- Para ver un cambio de UI de verdad: `npm run build` y, si hace falta, renderizar
  con el Chromium preinstalado (Playwright) — capturas, no a ciegas.
- Skill de diseño instalado en `.claude/skills/impeccable` (invocable con
  `/impeccable`); guía el pulido de UI.

## Orden de trabajo sugerido

Sigue `BACKLOG.md` en orden. P1 primero: la cobertura de cartas es lo que hace
que los numeros signifiquen algo. No vale la pena implementar prioridad e
instantaneos (P2.1) si el Lorehold todavia no sabe hacer Espiritus (P1.1).

## Como agregar una carta

Ver `ADDING_CARDS.md`. Resumen: una entrada en `cards.py` con sus ganchos y sus
tags, y una linea en `decks.py`.

## Definicion de terminado, por tarea

- El codigo corre: `python3 run.py` sin excepciones
- `python3 tests/test_engine.py` en verde (244 tests)
- Si tocaste el frontend: `npm run build` limpio
- `python3 coverage.py` muestra el incremento esperado de cartas implementadas
- Existe al menos una partida con `--log` donde se ve el efecto funcionando
- El criterio de aceptacion de la tarea en `BACKLOG.md` se cumple
- Si tocaste `engine.py`, los tres bugs de la tabla al final de `BACKLOG.md`
  siguen sin reaparecer, y el determinismo headless se mantiene
