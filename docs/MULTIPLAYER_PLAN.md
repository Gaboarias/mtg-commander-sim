# Plan — Multijugador live (4–6 jugadores)

> Estado: **planificado, no implementado.** Guardado para el futuro.
> Requisitos del usuario: 4–6 jugadores en vivo al mismo tiempo, con sus decks
> registrados; bracket por sala (deck fuera del bracket no puede jugarse); timer
> de acción (si no actúa en el lapso, pierde el turno); chat live in-app; solo
> usuarios registrados.

## La decisión que define todo

Hoy el motor corre **en el navegador** (Pyodide) para 1 humano vs bots. Para
multijugador real **no se puede confiar en el cliente**: el estado autoritativo
(barajar, manos ocultas, resolver la pila) tiene que vivir en **un servidor con
estado**. Vercel serverless **no sirve**: sus funciones son efímeras y no
sostienen WebSockets ni memoria entre requests.

→ **Necesitamos un servicio aparte, siempre encendido, autoritativo.** Como el
motor es Python, lo natural es un **servicio Python (FastAPI + WebSockets)** que
**importa `engine.py`/`interactive.py` tal cual** y mantiene las salas en
memoria. Reescribir el motor a JS para el edge es mucho más caro — descartado.

Vercel sigue siendo la web app (lobby, board); el game server es un segundo
deploy (Fly.io/Railway/Render, instancia chica always-on).

## Arquitectura

```
Navegador (Next.js /live)  ──WS──►  Game Server (Python, FastAPI+ws)  ──►  Turso
  - lobby / board / chat            - salas en memoria (autoritativo)       - salas, snapshots,
  - manda acciones                  - corre el motor (engine.py)              chat, resultados
  - recibe SU vista filtrada        - timers de turno + chat relay
                                    - valida token de sesión al conectar
        Vercel (web + /api)  ── auth existente (mtg_users/mtg_sessions), resolver de decks, brackets
```

## Componentes

1. **Lobby / salas.** Crear sala → fijar **bracket** y cupo (4–6) → código de
   invitación o lista pública → entran con un **deck registrado** → ready-check →
   start. Estado: `waiting → in_game → finished`.
2. **Game server autoritativo.** Una sala = una instancia de juego en memoria.
   Recibe acciones por seat, aplica en el motor, difunde a cada jugador **su**
   vista filtrada. Owner del RNG/seed.
3. **Realtime.** WebSocket por sala: estado del juego, chat, timer, presencia.
4. **Auth.** Reusa `mtg_users` + `mtg_sessions`. El token se valida **al abrir el
   WS**; sin sesión válida no entra (cumple "solo registrados").
5. **Brackets.** Al enviar deck a la sala, el server resuelve la lista y calcula el
   bracket con `gamechangers.py`; **rechaza** todo deck por encima del bracket,
   explicando por qué.
6. **Timer de acción.** Reloj **del server** por punto de decisión. Al vencer →
   auto-pasar (o resolver la decisión pendiente con un default). N timeouts
   seguidos → concede / pasa a bot.
7. **Chat live.** Mismo canal, scope sala, nombre de la cuenta, rate-limit.
8. **Reconexión.** Snapshot periódico a Turso; al reconectar, el seat recibe el
   estado actual.

## El mayor trabajo: motor multi-humano (crítico)

`interactive.py` hoy asume **un** humano (`human_index`; `ReactionPause` pausa para
ese único humano; `_ai_steps` reanuda su turno). Multi necesita:
- Generalizar a **K humanos + bots**, con cada decisión/prioridad **dirigida a un
  seat concreto**.
- La pausa (`ReactionPause`) y las `pending_choice` deben llevar **a qué seat**
  corresponden; el server espera la acción de **ese** jugador (o su timer).
- Ventanas de prioridad reales entre varios humanos (APNAP), no solo
  "el humano vs bots". (Reusa el refactor A: habilidades en la pila + prioridad.)

## Seguridad (no opcional)

El estado que hoy se exporta muestra **todo** (sirve para 1 jugador). En multi hay
que **filtrar por seat**: `state_for(seat)` oculta manos y bibliotecas ajenas,
revela solo lo público + lo propio. Si falla, se filtra info oculta = juego roto.

## Modelo de datos (Turso, tablas nuevas)

- `mtg_rooms` (id, host, bracket, cupo, estado, seed, created_at)
- `mtg_room_seats` (room_id, user_id, deck_text, seat_idx, status)
- `mtg_room_snapshots` (room_id, state_json, turn, updated_at) — reconexión/crash
- `mtg_chat` (room_id, user_id, msg, ts) — opcional persistir
- `mtg_match_results` — historial

## Análisis de riesgo

| # | Riesgo | Sev | Mitigación |
|---|--------|-----|-----------|
| 1 | Refactor motor multi-humano (interactive.py asume 1 humano) | **Alta** | Router de decisiones por seat; extender pausa/pending_choice con seat; reusar prioridad del refactor A |
| 2 | Infra realtime nueva (Vercel no sostiene WS/estado) | **Alta** | Servicio Python aparte (FastAPI+ws) que importa el motor; Fly.io/Railway always-on |
| 3 | Filtrado de info oculta por seat | Alta | `state_for(seat)`; tests que verifiquen que no se filtran manos ajenas |
| 4 | Timers + desconexiones + concede (edge cases) | Media | Máquina de estado por seat (activo/timeout/desconectado/concedido); default en timeout; a bot tras N |
| 5 | Costo/ops: server always-on nuevo | Media | Instancia chica (free/low tier); rooms en memoria; snapshot a Turso |
| 6 | Crash del server pierde salas en memoria | Media | Snapshot periódico + reconexión; MVP single-instance |
| 7 | Escala horizontal (varias instancias) | Baja (después) | Ruteo sticky sala→instancia o store compartido; no en MVP |
| 8 | Bracket es heurística → disputas | Baja | Reusar gamechangers; explicar el rechazo; override del host |

**A favor:** es **por turnos** → tolerante a latencia. No hace falta netcode de
rollback; con WS + estado autoritativo alcanza.

## Fases de entrega

- **F0 — Motor multi-humano** (sin red): generalizar interactive.py a K seats +
  `state_for(seat)`. Testeable headless. *Es el cimiento.*
- **F1 — Game server + WS**: FastAPI, salas en memoria, 2 humanos reales, vistas
  filtradas.
- **F2 — Lobby + auth + brackets + decks registrados**.
- **F3 — Timers + reconexión + concede.**
- **F4 — Chat + presencia + pulido UI** (reusar `app/board.tsx`).
- **F5 — 4–6 jugadores, snapshots, historial.**

## Decisiones abiertas (para cerrar el plan)

1. **Hosting del game server:** Fly.io vs Railway vs Render (recomiendo Fly.io).
2. **Timer:** ¿por decisión (~30–60s) o por turno (~2–3 min)? ¿auto-pasar o
   auto-jugar un default?
3. **Salas:** ¿solo por código, o también lista pública/matchmaking?
4. **Espectadores:** ¿se permiten? Afecta el filtrado de estado.
5. **Persistencia de chat:** ¿historial o efímero?
6. **Realtime propio vs gestionado:** servicio Python propio (recomendado, reusa
   motor) vs Ably/Pusher solo como pub/sub (Supabase Edge no corre Python).
