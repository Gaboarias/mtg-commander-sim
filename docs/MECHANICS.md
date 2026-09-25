# Catálogo de mecánicas

Qué mecánicas de Magic entiende el motor, cómo se modelan y dónde vive cada una.
Las mecánicas se leen del **oracle text** (Scryfall) en `cardsdb.py` y se ejecutan
sobre las primitivas de `engine.py`. **Toda acción que requiere una decisión del
jugador tiene su gesto de UI en `/play`** (modal de elección, selector de objetivo,
selector de X, etc.). Los bots toman la misma decisión de forma automática y
determinista (misma semilla ⇒ misma partida).

Aproximaciones: el objetivo es una simulación fiel a nivel de winrate, no un motor
de reglas exhaustivo. Donde se aproxima, se indica.

---

## Pila, prioridad y respuestas

- Hechizos, habilidades **activadas** y **disparadas** pasan por la pila.
- Ventana de reacción a velocidad de instante para el humano (`ReactionPause`) y
  para los bots (`policy.respond`). Contrarrestar (`Counterspell`), removal
  instantáneo, copiar hechizos.
- Headless se resuelve de forma síncrona (determinismo preservado); interactivo
  usa `pending_choice` + `ReactionPause`.

## Objetivos y decisiones (UI)

Todo pasa por `pending_choice` (modal genérico en `/play`, con arte de la carta):

- **Objetivo de hechizo/habilidad** — `target_spec`: criatura propia/rival,
  jugador, permanente, y por tipo: **artefacto, encantamiento, artefacto o
  encantamiento, planeswalker, no-tierra, cualquier permanente**. Si un hechizo
  **exige** objetivo y no hay ninguno legal, **no se puede jugar** (aviso en la UI,
  bloqueo también server-side).
- **Elegir carta del cementerio / del exilio** (reanimar, recuperar) — muestra las
  cartas de la zona y el jugador elige.
- **Modos** (cartas modales / entwine), **X**, **scry/surveil/fateseal**,
  **buscar (tutor)**, **explorar**, **mirar-y-tomar**, **elegir tipo de criatura**,
  **"¿querés hacerlo?"** (opcionales), **descarte** (mano > 7), **regla de
  legendarios**, **repartir contadores**.

## Combate y palabras clave

Vuelo, alcance, arrolla, mortal, vínculo vital, vigilancia, prisa, primer golpe,
doble golpe, amenaza, indestructible, hexproof, shroud, protección, prowess,
infección/toxic, wither, defensor, destello, no-bloqueable. Ataques a planeswalkers
(daño redirigido que resta lealtad). Exaltación (atacante solo → +1/+1).

## Efectos continuos / capas

`static_mod` para anthems (+X/+X y keywords a "tus criaturas"), auras de mutación
acotadas, `perma_keywords` por permanente (soulbond). Reducción de coste estática
("tus hechizos de tipo X cuestan {N} menos").

---

## Costes alternativos y lanzar desde otra zona

| Mecánica | Modelo | Dónde |
|---|---|---|
| Flashback / Jump-start / Retrace | lanzar desde el cementerio, luego exiliar | `gy_play` |
| Escape | lanzar desde el cementerio exiliando N cartas | `gy_play` mode `escape` |
| Unearth | volver al campo con prisa, exiliar a fin de turno | `gy_play` mode `unearth` |
| Embalm / Eternalize | ficha copia desde el cementerio | `gy_play` mode `embalm` |
| Disturb | lanzar la cara trasera desde el cementerio | `gy_play` mode `disturb` |
| Aftermath | secuela: lanzar **solo** desde el cementerio, luego exiliar | `gy_play` mode `aftermath` |
| Foretell | predecir ({2}, exiliar) y lanzar después por su coste | `exile_play` |
| Madness | al descartar, lanzar por el coste de madness (auto) | `Game.discard_card` |
| Evoke | cast barato: entra, dispara ETB, se sacrifica | `Game.cast_evoke` |
| Suspend N—{coste} | exiliar con N contadores; -1 por mantenimiento; a 0 se lanza gratis | `Game.suspend_card` / `_tick_suspended` |
| Adventure | lanzar la aventura (efecto) y la criatura queda jugable desde el exilio | `Game.cast_adventure` |
| Prepared (FRA) | la criatura entra "preparada"; habilidad que lanza una copia de su hechizo y la desprepara | `on_etb` + activada `prepared` |

Los que se lanzan desde la mano por un coste alternativo (evoke, suspend, adventure)
aparecen como **opciones extra de casteo** en `/play`.

## Mecánicas complejas

| Mecánica | Modelo (aprox donde aplique) |
|---|---|
| Cascade | exiliar del tope hasta una no-tierra de CMV menor y lanzarla gratis |
| Storm | copia el efecto por cada hechizo lanzado antes ese turno (`spells_this_turn`) |
| Replicate | copias = pagos extra que alcance el maná |
| Buyback | coste adicional; si se paga, vuelve a la mano al resolver |
| Kicker | coste adicional opcional (auto si alcanza); bono "if kicked" al resolver / en ETB |
| Entwine | en cartas modales, si se paga, se eligen todos los modos |
| Echo | al entrar queda pendiente; en tu próximo mantenimiento pagás o sacrificás |
| Cipher | tras resolver, se cifra en tu mejor criatura; al pegar daño de combate lanza una copia gratis |
| Level up | activada que sube de nivel; cada nivel = un +1/+1 (sumidero de maná) |
| Monstrosity | activada que pone N +1/+1 en sí misma y la vuelve monstruosa |
| Devour | al entrar come tus fichas de criatura → N contadores por cada una |
| Exalted | si ataca una sola criatura, +1/+1 por cada instancia |
| Extort | al lanzar un hechizo, drena 1 por rival |
| Persist / Undying | vuelve al campo con un -1/-1 (persist) o +1/+1 (undying) una vez |
| Soulbond | al entrar se empareja con una criatura sin pareja; ambas reciben la keyword |
| Changeling | flag de todos los tipos de criatura |

## Disparos por evento

`etb`, `death`, `cast` (tuyo, por tipo de hechizo: criatura/no-criatura/
instant-sorcery/artefacto), **`opp_cast`** (cuando un rival lanza), **`gain_life`**
(cuando ganás vida), `combat_damage_to_player`, `upkeep`, `end_step`, `draw_step`,
`landfall`, `begin_combat`, `creature_enters`.

## Efectos de reemplazo

Dobladores de fichas (`token_double`), de daño (`damage_double`), de contadores
(`counter_modifier`); "si moriría, exíliala en su lugar" (`die_exile`).

## Efectos de "regla" y globales

- Tierra extra por turno (Exploration/Azusa): `land_limit()` dinámico.
- Ganar el control de **todas** las criaturas (Insurrection).
- "Los jugadores no pueden ganar vida" (Erebos/Archfiend): `stops_lifegain`.
- "El daño no se puede prevenir este turno": `no_prevention_turn`.
- "Las criaturas no pueden bloquear este turno": `no_block_turn`.
- Reanimar desde **cualquier** cementerio (no solo el tuyo).

---

## Analizador de mazo (`/deck`)

- Fortalezas, debilidades, curva de maná, demanda/fuentes de color, consistencia
  (probabilidad hipergeométrica de mano jugable), temas/sinergias.
- **Combos**: base local curada (`combos.py`, ~35 combos EDH conocidos) que corre
  **siempre** (aunque Commander Spellbook esté caído), fusionada con la API de
  Commander Spellbook. Detecta combos armados y "a una carta de", filtrando estos
  últimos por la identidad de color del mazo.
- Recomendaciones accionables (qué sumar por rol) con precios de Scryfall.

## Qué NO se modela

Nichos de bajo impacto en 1v1 o que requieren infra específica no incluida:
multijugador live (ver `MULTIPLAYER_PLAN.md`), y decisiones forzadas por el rival
a mitad del turno del bot (edicto/descarte forzado sobre el humano) se auto-resuelven
de forma justa (la carta/criatura menos valiosa) porque el turno del bot corre
síncrono y sólo pausa para *responder*, no para elegir.
