# Backlog priorizado

Cada tarea lleva criterio de aceptacion verificable. El orden importa: las de
prioridad 1 son las que hacen que los porcentajes signifiquen algo.

---

## P1 — Cobertura de cartas (el cuello de botella real)

Estado actual (`python3 coverage.py`):

```
Lorehold   efecto implementado  12 | vainilla   9
Tricky     efecto implementado   8 | vainilla  14
Kang       efecto implementado  26 | vainilla  16
```

Kang gana 93% de las simulaciones porque es el unico mazo cuyas cartas estan
programadas. **No es un desequilibrio real, es un artefacto de cobertura.**

### P1.1 Motor de Espiritus del Lorehold
Hoy `Quintorius()` solo crea un Espiritu si hay un permanente con tag `gy_exile`
en mesa, y el mazo tiene 3. Falta:
- `Hofri Ghostforge` — las criaturas que mueren vuelven como Espiritu con +1/+1 y prisa
- `Anger` — mientras este en el cementerio y controles una Montana, todas tus criaturas tienen prisa
- `Sevinne's Reclamation` — devuelve permanente de coste <=3 del cementerio (sale del cementerio -> dispara Quintorius)
- `Sun Titan`, `Karmic Guide` — reanimacion al entrar
- `Underworld Breach` — lanzar desde el cementerio exiliando 3

**Aceptacion:** en `run.py lorehold kang --log`, el Lorehold crea al menos un
Espiritu antes del turno 6 en >=70% de 100 partidas con semillas 0-99.

### P1.2 Contadores del Tricky
- `Branching Evolution` / `Innkeeper's Talent` — duplicar contadores +1/+1 al ponerse
- `Kalonian Hydra` — al atacar, duplica los contadores de todas tus criaturas
- `Managorger Hydra`, `Forgotten Ancient` — contador por hechizo lanzado
- `Evolution Sage` — proliferar con landfall
- `Hardened Scales` — un contador extra
- `Simic Ascendancy` — acumula contadores, gana al llegar a 20 (condicion de victoria alternativa)

**Aceptacion:** `Simic Ascendancy` puede ganar una partida. Anadir test que lo verifique.

### P1.3 Kang connive real
Hoy el disparador roba 1 y descarta la ultima carta de la mano. Deberia:
- elegir el descarte con la politica, no `hand.pop()`
- poner +1/+1 solo si lo descartado no era tierra
- el drenaje debe dispararse por **la segunda carta robada del turno**, venga de donde venga, no solo del connive

**Aceptacion:** un `Night's Whisper` en el turno drena aunque Kang no ataque.

---

## P2 — Reglas que faltan

> **Estado: P2.1–P2.5 IMPLEMENTADAS** (ver tests en `tests/test_engine.py`).
> - P2.1 ventana de prioridad en `Game.cast` + `policy.respond` + `Counterspell`.
> - P2.2 `Game.can_target`/`legal_creature_targets`, hexproof/ward, removal dirigido.
> - P2.3 lealtad + `activate_loyalty` (una por turno) + la IA puede **atacar
>   planeswalkers** (daño redirigido que resta lealtad) + SBA a 0.
>   En esta build Quintorius sigue siendo comandante criatura (motor de Espíritus
>   del P1.1); el planeswalker con `-4` se agregó como carta aparte
>   (`Quintorius, Loremaster`).
> - P2.4 `Permanent.power/toughness` suman `static_mod` (anthems/capas).
> - P2.5 `Game(mulligan=True)` regla de Londres + `policy.should_mulligan`.

### P2.1 Prioridad e instantaneos
Hoy los instantaneos solo se lanzan en fase principal. Falta una ventana de
respuesta tras poner algo en la pila y antes de declarar bloqueadores.

**Diseno sugerido:** `Game.priority_round(active_player)` que recorra a los
jugadores en orden y llame `policy.respond(game, me, stack_top)`. Los counterspells
y el removal instantaneo dependen de esto.

**Aceptacion:** `Counterspell` puede contrarrestar un hechizo en la pila.

### P2.2 Objetivos reales
`destroy_biggest` ignora el sistema de objetivos. Falta:
- `StackObject.targets` poblado por la politica
- validacion de legalidad al lanzar y al resolver
- `hexproof` y `ward`

**Aceptacion:** una criatura con `hexproof` no puede ser objetivo de removal rival.

### P2.3 Planeswalkers
`Quintorius` esta modelado como permanente con un disparador de mantenimiento.
Falta: contadores de lealtad, una activacion por turno, poder atacarlos, dano
redirigido.

**Aceptacion:** el `-4` de Quintorius existe y se puede activar.

### P2.4 Efectos continuos por capas
No hay sistema de capas. Los anthems (`+1/+1` a todas tus criaturas), los
cambios de tipo y los efectos de "mientras X" no se pueden expresar.

**Diseno sugerido:** `Permanent.power` pasa de propiedad simple a calculo sobre
una lista de modificadores registrados en el juego.

### P2.5 Mulligan
Regla de Londres: robar 7, si se hace mulligan robar 7 de nuevo y poner N al
fondo. Hoy no existe y todas las manos se juegan como salgan.

**Aceptacion:** `Game(players, mulligan=True)` y una politica que haga mulligan
con 0-1 o 6-7 tierras.

---

## P3 — Calidad de la IA

> **Estado: P3.1–P3.3 IMPLEMENTADAS.**

### P3.1 La politica no guarda mana  ✅
`main_phase` reserva el coste del instantaneo reactivo (counter) mas barato en
mano cuando hay oponentes: no tapea por debajo de ese coste
(`policy._reserve_mana`). Test `test_policy_reserves_mana_for_counter`.

### P3.2 Los ataques ignoran la politica multijugador  ✅
`declare_attackers` sigue apuntando al rival con menos vida, pero si OTRO
oponente tiene un tablero amenazante (poder >= 60% de tu vida) guarda
bloqueadores (los de mayor resistencia) en vez de atacar con todo. Test
`test_policy_holds_blockers_under_threat`.

### P3.3 La eleccion de descarte es `hand.pop()`  ✅
Resuelto junto con P1.3: `policy.choose_discard` descarta la carta de menor
puntuacion (y prefiere tierras de sobra si estas inundado).

---

## P4 — Infraestructura

- **Tests.** No hay ninguno. Empezar por: coste de mana con duales, impuesto de
  comandante, 21 de dano de comandante, arrollar, amenaza, regla de legendarios.
- **Importar listas desde texto.** Parser de formato Moxfield -> `decks.py`.
- **Exportar partidas.** `--log` a JSON para analisis posterior.
- **Paralelizar.** `run.py` con `multiprocessing` para correr miles de partidas.
- **Semillas reproducibles.** `one(keys, seed=i)` ya lo hace; documentar que
  la misma semilla da la misma partida.

---

## Bugs corregidos (no reintroducir)

| Bug | Sintoma | Fix |
|---|---|---|
| Disparadores de mantenimiento globales | Quintorius robaba en el turno de todos | `Game.SELF_SCOPED` |
| Disparadores de ataque globales | Kang drenaba cuando atacaba el rival | `"attacks"` se dispara directo sobre el atacante en `combat()` |
| Tierras duales contando doble | comandante de 4 lanzado en turno 2 | `produces` son opciones; `_assign()` hace emparejamiento |

**Cualquier cambio al sistema de mana o de eventos exige volver a correr
`run.py lorehold kang --log` y verificar a mano que los costes caen en el turno
correcto.**
