# Plan: Simulador visual

Progresión en 3 fases. Cada fase deja construida la base de la siguiente
(1 → 2 → 3 es el orden más eficiente, no solo el más prudente).

## Base común (se construye en Fase 1, la reusan las 3)

- **Traza estructurada del motor:** además del log de texto, el motor emite el
  estado paso a paso (zonas, vida, permanentes con tapped/contadores, la pila).
  Es el corazón de todo lo visual.
- **Componente de carta** con arte de Scryfall (`image_uris.art_crop`) + cache
  en el navegador.
- **Renderer de tablero** para 2-6 jugadores (mano, campo, cementerio,
  comandante, vida).

---

## Fase 1 — Ver jugar al sistema (replay visual)

**Qué:** elegís decks y semilla → el motor juega → se ve el tablero animado
turno a turno con una línea de tiempo (play/pausa, ir a turno N).

- **Motor:** grabador de traza (snapshots por evento). Endpoint `/api/replay`.
- **Front:** board renderer + scrubber + animaciones (framer-motion, ya está).
- **Herramientas:** las actuales. **Sin base de datos.**
- **Esfuerzo:** M. **Riesgo:** bajo.

## Fase 2 — Jugar vos vs el sistema

**Qué:** hacés clic (jugar tierra, lanzar, atacar, bloquear); el sistema responde.

- **Motor:** modo "esperar acción del humano" en las ventanas de prioridad
  (hoy juega solo).
- **Arquitectura recomendada:** correr el motor Python en el navegador con
  **Pyodide (WASM)** → interactivo sin ida y vuelta al servidor, reusando el
  mismo motor sin reescribirlo en JS.
- **UI:** acciones legales resaltadas, targeting, fase de combate.
- **Herramientas:** + Pyodide. **Sin base de datos.**
- **Esfuerzo:** L. **Riesgo:** medio.

## Fase 3 — Multijugador entre personas

**Qué:** varias personas en la misma partida en vivo.

- **Servidor autoritativo + tiempo real:** acá **sí entra Supabase**
  (Postgres + Realtime + Auth); Vercel serverless no sostiene conexiones en vivo.
- **El trabajo grande son las reglas, no la red:** el motor es una aproximación;
  para humanos jugando en serio hay que cerrar huecos de reglas (targeting real,
  respuestas, timing, casos borde). Es más grande que todo lo visual junto.
- **Herramientas:** + Supabase (Realtime/Auth) y posiblemente un runtime con
  estado (no serverless puro).
- **Esfuerzo:** XL. **Riesgo:** alto.

---

## Herramientas por fase

| | Fase 1 | Fase 2 | Fase 3 |
|---|---|---|---|
| Scryfall (arte) | ✅ | ✅ | ✅ |
| framer-motion | ✅ | ✅ | ✅ |
| Traza del motor | ✅ | ✅ | ✅ |
| Pyodide (motor en navegador) | — | ✅ | opcional |
| Supabase (Realtime + Auth) | — | — | ✅ |
| Reglas completas de MTG | — | parcial | ✅ (grande) |

**Factibilidad:** Fases 1 y 2 son viables con lo que hay + Pyodide. Fase 3 es
viable pero es un proyecto en sí mismo (por las reglas, no por Supabase).

---

## Fase 1 — desglose de tareas

1. **Traza en el motor** (`engine.py`): grabador opcional que, tras cada evento
   relevante (inicio de turno, robo, tierra, lanzamiento, resolución, combate,
   muerte, cambio de vida), guarda un snapshot serializable del estado de todos
   los jugadores. Activable por flag para no afectar la simulación masiva.
2. **Serialización de estado**: helper que vuelca `Game`/`Player`/`Permanent` a
   dicts JSON (vida, mano [conteo/cartas], campo, cementerio, comando, pila,
   turno, jugador activo).
3. **Endpoint** `/api/replay`: recibe specs + semilla, juega UNA partida con la
   traza activa y devuelve `{players, winner, turns, steps:[...]}`.
4. **Página** `/watch` (o dentro de la home): elige decks + semilla → pide la
   traza → renderiza el tablero.
5. **Board renderer + Card**: arte de Scryfall, vida, permanentes tapeados/con
   contadores, mano (dorso o cara), cementerio, zona de comando.
6. **Scrubber**: línea de tiempo con play/pausa, paso a paso, ir a turno N;
   animaciones de movimiento de carta con framer-motion.
