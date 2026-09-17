# Arquitectura

## Mapa de archivos

```
engine.py    Motor de reglas. No conoce ninguna carta concreta.
policy.py    IA. Decide que lanzar, con que atacar y como bloquear.
cards.py     Biblioteca de cartas: constructores y efectos concretos.
decks.py     Las tres listas de 99 + comandante.
run.py       CLI y agregacion estadistica.
coverage.py  Reporte de cuantas cartas tienen efecto real implementado.
```

**Regla de dependencias, en un solo sentido:**

```
run.py ──> decks.py ──> cards.py ──> engine.py
   └─────> policy.py ─────────────────> engine.py
```

`engine.py` no importa nada del proyecto. Si necesitas tocarlo para agregar una
carta, es senal de que falta un gancho generico, no de que esa carta sea especial.

## Ciclo de vida de una partida

```
Game.__init__      baraja, reparte 7, pone comandantes en zona de mando
Game.play()        bucle: mientras quede mas de 1 vivo y turn < max_turns
  └ run_turn()     un turno completo del jugador activo
      ├ UNTAP          endereza todo, limpia mareo de invocacion y marcas de combate
      ├ UPKEEP         emit("upkeep") -> resolve_stack()
      ├ DRAW           roba 1 (salvo jugador inicial en turno 1)
      ├ MAIN1          policy.main_phase()
      ├ combat()       ver abajo
      ├ MAIN2          policy.main_phase(second=True)
      ├ END_STEP       emit("end_step")
      └ CLEANUP        borra dano, descarta hasta 7
```

## Combate

```
DECLARE_ATTACKERS   policy.declare_attackers() -> [(perm, defensor)]
                    tapea salvo vigilancia, dispara "attacks" del atacante
DECLARE_BLOCKERS    por cada defensor: policy.declare_blockers()
                    valida amenaza (exige 2+ bloqueadores)
FIRST_STRIKE_DAMAGE solo primer golpe y doble golpe
COMBAT_DAMAGE       el resto, mas la segunda mitad del doble golpe
```

La asignacion de dano de un atacante bloqueado recorre `blocked_by` en orden,
asigna lo letal a cada uno, y el sobrante va al defensor solo si hay arrollar.

## Modelo de mana

Este es el punto donde el motor se rompio dos veces. La regla:

**`produces` devuelve OPCIONES, no produccion simultanea.**

```python
Plains       -> {W: 1}              1 mana blanco
Dual Boros   -> {R: 1, W: 1}        1 mana, rojo O blanco     (NO 2 manas)
Sol Ring     -> {C: 2}              2 manas incoloros
Tierra Omo   -> {W:1,U:1,B:1,R:1,G:1,C:3}   3 incoloros o 1 de color
```

- `available_mana()` -> total = suma de `max(opciones)` por fuente
- `_assign(cost)` -> emparejamiento: primero los simbolos de color con la fuente
  **menos flexible** que sirva, luego el generico con las que mas produzcan
- `can_pay()` es `_assign() is not None`; `pay()` tapea el plan

Cualquier cambio aqui exige volver a correr `run.py --log` y verificar a mano que
los costes caen en el turno correcto.

## Sistema de eventos

`Game.emit(event, **kw)` recorre los permanentes y encola en la pila los que
tengan `triggers[event]`.

**Alcance.** `Game.SELF_SCOPED` contiene los eventos que solo deben disparar
permanentes del jugador implicado:

```python
SELF_SCOPED = {"upkeep","end_step","draw","landfall","cast","begin_combat"}
```

Si `kw["player"]` esta presente y el evento es self-scoped, solo dispara ese
jugador. **Este filtro existe porque su ausencia causo dos bugs de duplicacion
de disparadores.** Cualquier evento nuevo que sea "en tu turno" o "cuando tu
haces X" debe entrar en ese conjunto.

`"attacks"` no usa `emit`: se dispara directo sobre el permanente atacante en
`combat()`, porque el disparador pertenece al atacante y no a todos.

## Acciones basadas en estado

`Game.sba()` corre en bucle hasta que no cambie nada:

- vidas <= 0 o veneno >= 10 -> jugador pierde
- cualquier entrada de `cmdr_damage` >= 21 -> jugador pierde
- criatura con resistencia <= 0 o dano letal -> al cementerio
- dos legendarios del mismo nombre -> el segundo al cementerio

Se invoca despues de cada resolucion de la pila, despues de cada paso de dano y
al final de cada turno.
