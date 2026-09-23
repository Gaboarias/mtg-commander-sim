# Como agregar cartas

## Paso 1 — definirla en `cards.py`

### Criatura vainilla

```python
creature("Nombre", "2RW", 4, 4, kw=("flying","trample"), tags=("creature",))
#         nombre   coste  P  T
```

### Criatura legendaria

```python
creature("Hofri Ghostforge", "2RRW", 4, 4, legendary=True, tags=("engine",))
```

### Tierra

```python
land("Nombre", [R, W])                    # sin tapear, dos colores posibles
land("Nombre", [B], tapped=True)          # entra tapeada
land("Plains", [W], basic=True)           # basica
```

### Roca de mana

```python
rock("Dimir Signet", "2", [U, B])         # 1 mana, azul o negro
rock("Sol Ring", "1", [C, C])             # OJO: la lista son opciones.
                                          # Para 2 incoloros usa produces directo:
Card("Sol Ring", {"artifact"}, parse_cost("1"),
     produces=lambda p, pl: {C: 2}, tags={"ramp"})
```

### Instantaneo o conjuro

```python
Card("Go for the Throat", {"instant"}, parse_cost("1B"),
     on_cast_resolve=destroy_biggest,
     tags={"removal"})

Card("Night's Whisper", {"sorcery"}, parse_cost("1B"),
     on_cast_resolve=draw_n(2),
     tags={"draw"})
```

### Efecto propio

```python
def gray_merchant_etb(game, ctrl, perm):
    devocion = sum(1 for p in ctrl.battlefield
                   if p.card.cost and B in p.card.cost.pips)
    for o in game.opponents(ctrl):
        game.deal_damage(None, o, devocion)
    ctrl.life += devocion * len(game.opponents(ctrl))

def GrayMerchant():
    c = creature("Gray Merchant of Asphodel", "3BB", 2, 4, tags=("creature",))
    c.on_etb = gray_merchant_etb
    return c
```

### Disparador

```python
def Managorger():
    def on_cast(game, perm, **kw):
        perm.counters["+1/+1"] = perm.counters.get("+1/+1", 0) + 1
    c = creature("Managorger Hydra", "2G", 1, 1, kw=("trample",), tags=("creature",))
    c.triggers = {"cast": on_cast}
    return c
```

**Atencion:** `cast` esta en `SELF_SCOPED`, asi que solo dispara con tus propios
hechizos. Managorger real dispara con los de todos. Para eso hay que sacar `cast`
de `SELF_SCOPED` y filtrar dentro del callback — anotado en `BACKLOG.md`.

### Crear fichas

```python
from cards import make_token

def etb(game, ctrl, perm):
    for _ in range(3):
        make_token(game, ctrl, "Espiritu", 3, 2, kw=("flying",))
```

### Motor de salida de cementerio

```python
Card("Bag of Holding", {"artifact"}, parse_cost("1"),
     tags={"engine", "gy_exile"})
```

El tag `gy_exile` es lo que consulta `Quintorius()` para saber si puede crear
Espiritus. Si tu carta permite sacar cartas del cementerio, ponle ese tag.

---

## Paso 2 — meterla en el mazo

En `decks.py`, dentro de la funcion del mazo correspondiente:

```python
d.append(GrayMerchant())
```

El mazo se rellena automaticamente con tierras basicas hasta 99 via `_fill()`.
Si agregas cartas, se quitan basicas solas. Verifica con:

```bash
python3 -c "import decks; d,c = decks.kang(); print(len(d))"   # debe dar 99
```

---

## Paso 3 — verificar

```bash
python3 coverage.py                       # la cuenta de implementadas debe subir
python3 run.py lorehold kang --log | grep "Nombre"   # verla en accion
python3 run.py lorehold kang -n 300       # ver si mueve la aguja
```

---

## Efectos reutilizables ya disponibles

| Funcion | Que hace |
|---|---|
| `destroy_biggest(game, ctrl, targets)` | destruye la criatura mas grande de un oponente |
| `wrath(game, ctrl, targets)` | destruye todas las criaturas |
| `draw_n(n)` | devuelve un efecto que roba n |
| `dmg_all_opponents(n)` | devuelve un efecto que hace n a cada oponente |
| `make_token(game, player, nombre, p, t, kw=())` | crea una ficha, devuelve el `Permanent` |

---

## Errores comunes

**La carta nunca se lanza.** Revisa sus `tags`. Sin tags, `Policy.score()` le da
puntuacion baja y la IA prefiere otras. Una carta sin tag util solo se lanza en
fase principal 2.

**El disparador no se activa.** Verifica que el evento este emitido en `engine.py`
y que la firma sea `(game, perm, **kw)`. El kwarg `perm` se filtra antes de llamar
al callback, por eso el segundo parametro posicional es el permanente.

**El coste no cuadra.** `parse_cost("2RW")` son 4 manas, no 2. Los digitos son el
generico, cada letra un simbolo de color.

**La carta cuesta de menos.** Si es una roca que deberia dar 2+ manas, `rock()`
con dos entradas en la lista da UNA, no dos. Usa `produces=lambda p,pl: {C: 2}`.

---

## Dos caminos para una carta

1. **A mano en `cards.py`** (lo de arriba): control total, para los precons y las
   cartas clave. Es donde se escriben los efectos concretos.
2. **Auto desde Scryfall en `cardsdb.py`** (`build_card_from_data`): para decks del
   usuario. Lee el *oracle text* y arma la `Card` con las mecánicas reconocidas.

`cardsdb.py` ya cablea muchos ganchos extendidos del `Card`. Si agregás una
mecánica nueva, sumá su parser ahí (no en `engine.py`) y un test:

- `gy_play` (flashback/unearth/embalm/escape/recur), `foretell` (exilio),
  `gy_abilities` / `gy_triggers` / `gy_grant` (desde el cementerio, p. ej. Anger)
- `modes` (modal), `x_spell` ({X}), `etb_counters`, `aura_keywords`
- copiar: clon (`_clone_effect`), hechizo (`_copy_spell_effect`), habilidad
  (`copy_ab` -> `copy_ability_on_stack`/`copy_last_ability`), `populate`
- habilidades activadas (`activated_abilities`) — pasan por la pila al activarse

Regla que no cambia: **el motor no conoce cartas**. Si un parser nuevo necesita
tocar `engine.py`, lo que falta es un gancho genérico.
