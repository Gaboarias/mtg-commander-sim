# Referencia de API

## Constantes

```python
from engine import W, U, B, R, G, C, COLORS, KEYWORDS, Zone, Step
```

`KEYWORDS` implementadas: `flying`, `reach`, `trample`, `deathtouch`, `lifelink`,
`vigilance`, `haste`, `first_strike`, `double_strike`, `menace`, `indestructible`,
`hexproof` (declarada, sin efecto), `defender`, `flash` (declarada, sin efecto).

---

## `Cost` / `parse_cost(s)`

```python
parse_cost("2RW")      -> Cost(generic=2, pips=("R","W"))     cmc 4
parse_cost("UUURRR")   -> Cost(generic=0, pips=(U,U,U,R,R,R)) cmc 6
parse_cost("1")        -> Cost(generic=1, pips=())            cmc 1
```

El parser lee **todos** los digitos como un solo numero generico y cada letra
como un simbolo. No soporta hibridos, Phyrexianos ni X.

| Campo | Tipo |
|---|---|
| `generic` | `int` |
| `pips` | `tuple[str]` |
| `.cmc` | `int` (propiedad) |
| `.color_identity()` | `set[str]` |

---

## `Card`

Definicion inmutable de una carta. Una instancia por copia en el mazo.

| Campo | Tipo | Nota |
|---|---|---|
| `name` | `str` | usado por la regla de legendarios y `cmdr_damage` |
| `types` | `set[str]` | `land`, `creature`, `artifact`, `enchantment`, `instant`, `sorcery`, `planeswalker` |
| `cost` | `Cost \| None` | `None` solo para tierras y fichas |
| `power`, `toughness` | `int` | base, sin contadores |
| `keywords` | `set[str]` | de `KEYWORDS` |
| `subtypes`, `supertypes` | `set[str]` | `supertypes` acepta `legendary`, `basic` |
| `loyalty` | `int` | declarado, sin sistema de lealtad todavia |
| `color_id` | `set[str]` | identidad explicita; si esta vacia se deduce del coste |
| `enters_tapped` | `bool` | |
| `tags` | `set[str]` | **lo que lee la IA**, ver abajo |

### Ganchos

| Gancho | Firma | Cuando |
|---|---|---|
| `produces` | `(perm, player) -> dict[color,int]` | al calcular maná; devuelve OPCIONES |
| `on_etb` | `(game, controller, perm) -> None` | al entrar al campo |
| `on_death` | `(game, controller, perm) -> None` | antes de ir al cementerio |
| `on_cast_resolve` | `(game, controller, targets) -> None` | al resolver instantáneo/conjuro |
| `triggers` | `dict[str, (game, perm, **kw)]` | ver eventos |
| `activated` | `(game, perm) -> None` | declarado, sin invocar todavía |

### Tags que lee la IA

| Tag | Puntos |
|---|---|
| `engine` | +5 |
| `ramp` | +4 si turno <= 4, +1 después |
| `draw` | +3 |
| `removal` | +4 solo si algún oponente tiene criaturas |
| `wipe` | +6 solo si un oponente tiene 3+ criaturas y más que tú |
| `creature` | + su poder (mínimo 1) |
| `gy_exile` | sin puntos; lo consultan efectos que necesitan salida de cementerio |

---

## `Permanent`

Instancia en el campo de batalla. Envuelve una `Card`.

| Campo | Nota |
|---|---|
| `card`, `controller` | |
| `tapped`, `summoning_sick` | |
| `damage` | se borra en limpieza |
| `counters` | `dict[str,int]`; `"+1/+1"` afecta poder y resistencia |
| `attacking` | `Player` o `None` |
| `blocking`, `blocked_by` | listas de `Permanent` |
| `is_token` | los tokens no van al cementerio |
| `uid` | entero único, usado por el asignador de maná |

Propiedades: `.name`, `.power`, `.toughness` (incluyen contadores), `.keywords`
Métodos: `.is_creature()`, `.can_attack()`, `.lethal()`

---

## `Player`

| Campo | Nota |
|---|---|
| `life` | 40 por defecto |
| `library`, `hand`, `graveyard`, `exile`, `command`, `battlefield` | |
| `cmdr_tax` | sube +2 por cada lanzamiento desde la zona de mando |
| `cmdr_damage` | `dict[nombre_comandante, int]`; 21 elimina |
| `lands_played` | se reinicia cada turno |
| `lost` | |
| `policy` | instancia de `Policy` |

Métodos: `setup(rng)`, `draw(n, game)`, `creatures()`, `lands()`, `identity()`,
`mana_sources()`, `available_mana()`, `can_pay(cost)`, `pay(cost)`

---

## `Game`

| Método | Qué hace |
|---|---|
| `play()` | corre la partida, devuelve nombre del ganador o `"EMPATE"` |
| `run_turn()` | un turno completo |
| `combat(p)` | los cuatro pasos de combate |
| `cast(player, card, from_command=False, targets=None, chosen_modes=None, x_value=None)` | paga, apila y (headless) resuelve; modal/X soportados |
| `activate_ability(perm, index, targets=None)` | paga el coste y **apila** la habilidad (refactor A) |
| `activate_loyalty(perm, index)` | habilidad de lealtad (una por turno), va a la pila |
| `copy_spell_on_stack(obj, controller=None)` | Fork/Twincast: copia un hechizo del tope |
| `copy_ability_on_stack(obj, controller=None)` | Strionic: copia una habilidad concreta del tope |
| `copy_last_ability(ctrl)` | copia la última habilidad resuelta (`Game.last_ability`) |
| `emit(event, **kw)` | encola disparadores (`StackObject` kind="trigger") |
| `resolve_stack()` | vacía la pila, LIFO (con cortafuegos anti-bucle) |
| `_run_priority_and_resolve()` | drena la pila dando ventanas de prioridad/respuesta |
| `sba()` | acciones basadas en estado |
| `move_to_battlefield(card, player, is_token=False)` | devuelve el `Permanent` |
| `destroy(perm, reason)` | respeta indestructible |
| `to_graveyard(perm, reason)` | ignora indestructible; comandante vuelve a la zona de mando |
| `leave_graveyard(player, card, dest="exile")` | emite `leaves_graveyard`, devuelve `bool` |
| `deal_damage(source, target, amount, combat=False)` | `target` puede ser `Player` o `Permanent`; con `combat=True` y fuente comandante acumula daño de comandante |
| `opponents(p)`, `alive()`, `ap()` | |

### Eventos

| Evento | kwargs | Alcance |
|---|---|---|
| `etb` | `player`, `perm` | global |
| `death` | `player`, `perm` | global |
| `to_graveyard` | `player`, `card` | global |
| `leaves_graveyard` | `player`, `card` | global |
| `upkeep` | `player` | solo controlador |
| `end_step` | `player` | solo controlador |
| `draw` | `player` | solo controlador |
| `landfall` | `player` | solo controlador |
| `cast` | `player`, `card` | solo controlador |
| `begin_combat` | `player` | solo controlador |
| `attacks` | `defender` | solo el permanente atacante |

**El callback recibe `(game, perm, **kw)` sin la clave `perm` duplicada.**

---

## `Policy`

Métodos principales, todos sobreescribibles:

```python
score(game, me, card) -> int                      # prioridad de lanzamiento
                                                  #   (valora evasión/keywords, no solo fuerza)
main_phase(game, me, second=False) -> None        # tierra, comandante, hechizos,
                                                  #   cementerio/exilio, habilidades, foretell
choose_targets / _spec_targets(...)               # objetivos: _threat_value prioriza
                                                  #   comandantes y amenazas evasivas
declare_attackers(game, me) -> [(Permanent, Player|Permanent)]  # ataca jugadores o planeswalkers;
                                                  #   avanzado no ataca a muerte gratis
declare_blockers(game, me, incoming) -> [(atacante, bloqueador)]  # deathtouch/menace/trample/vuelo

# ventanas de prioridad (las llama _run_priority_and_resolve):
respond(game, me, top) -> bool                    # contrarrestar un hechizo rival que vale la pena
respond_copy(game, me, top) -> bool               # copiar el PROPIO hechizo con Fork/Twincast
respond_ability(game, me, top) -> bool            # copiar la PROPIA habilidad con Strionic
```

Niveles: `Policy("novato" | "intermedio" | "avanzado")`. Sustituir la política de un
jugador: `player.policy = MiPolitica()`.
