# MTG Commander Sim

Motor de simulación de **Magic: The Gathering**, formato Commander, en **Python
puro** (sin dependencias externas), con una **interfaz web Next.js** y una **API
serverless en Vercel**. Sirve para medir con miles de partidas si un cambio a un
mazo mejora su tasa de victoria.

> Cloud-first: desplegado en Vercel. El motor corre como funciones Python
> serverless bajo `/api`, y el frontend Next.js las consume.

## Qué hay

```
engine.py     Motor de reglas. No conoce ninguna carta concreta.
policy.py     IA. Decide qué lanzar, con qué atacar y cómo bloquear.
cards.py      Biblioteca de cartas: constructores y efectos concretos.
decks.py      Las tres listas de 99 + comandante (lorehold / tricky / kang).
run.py        CLI y agregación estadística.
coverage.py   Reporte de cuántas cartas tienen efecto real implementado.
tests/        Tests del motor (mana, comandante, combate, legendarios…).

api/          Funciones serverless de Vercel (Python):
  _sim.py       Puente al motor (agrega la raíz al sys.path).
  simulate.py   GET /api/simulate?matchup=lorehold,kang&n=200
                GET /api/simulate?matchup=lorehold,kang&log=1&seed=0
  catalog.py    GET /api/catalog  (mazos + comandante + cobertura)

app/          Frontend Next.js (App Router).
docs/         ARCHITECTURE.md, API.md, BACKLOG.md, ADDING_CARDS.md
CLAUDE.md     Reglas del proyecto para trabajar el motor.
```

## Uso local (CLI)

Solo hace falta Python 3.11+ (nada que instalar):

```bash
python3 run.py                       # baseline: lorehold vs tricky vs kang, 200 partidas
python3 run.py lorehold kang         # ese enfrentamiento, 200 partidas
python3 run.py lorehold kang -n 500  # 500 partidas
python3 run.py lorehold kang --log   # una partida comentada turno a turno
python3 coverage.py                  # cobertura de cartas por mazo
python3 tests/test_engine.py         # tests (o: python3 -m pytest tests/ -q)
```

Misma semilla ⇒ misma partida: `run.one(keys, seed=i)` es reproducible.

## Uso web (local)

```bash
npm install
npm run dev     # http://localhost:3000
```

En local, las funciones de `/api/*.py` requieren el runtime de Vercel
(`vercel dev`). Para probar solo el frontend contra datos reales, desplegá a
Vercel (abajo) o usá `vercel dev` con el CLI de Vercel instalado.

## Despliegue en Vercel

1. Importá este repo en [vercel.com/new](https://vercel.com/new). Vercel detecta
   **Next.js** como framework y construye las funciones de `/api/*.py` con el
   runtime de **Python** (config en `vercel.json`).
2. No hacen falta variables de entorno ni base de datos.
3. Cada push a `main` publica producción; las ramas generan previews.

`vercel.json` fija `includeFiles: "*.py"` para que las funciones serverless
empaqueten el motor (los `.py` de la raíz) junto al handler.

## Perfil de usuario (local, sin login)

En `/deck` cada usuario tiene un **perfil local** (guardado en el navegador,
sin cuentas ni backend): un nombre y una lista de **decks guardados**
(`app/localDecks.ts`, `localStorage`). Puede guardar el deck que armó/editó,
recargarlo cuando quiera y simularlo. Los decks viven solo en ese dispositivo
(no sincronizan entre navegadores/personas); es la opción simple pedida. Para
cuentas reales cross-device haría falta auth + DB (p. ej. Supabase), no incluido.

## Tus decks (presets) y el formato de tablas

Los mazos propios viven como `.md` en `presets/` (formato en
`presets/FORMATO.md`): una tabla por sección con
`| n | Carta | Coste | P/T | Keywords | Tags |` y una tabla de tierras con
`| n | Carta | Produce | Tapeada |`. `mdparse.py` los lee **offline** (sin
Scryfall) y `decks.py` los registra como mazos jugables — aparecen solos en el
simulador y como oponentes.

Reglas del importador (`mdparse.py`):
- Solo lee las tablas **antes del primer `---`** (lo de después son notas).
- `## Comandante` define el comandante; `?` en una columna = **error ruidoso**
  (no adivina); `n = ?` en básicas = rellena hasta 99.
- Si la carta está implementada (registro `cardsdb`) y el tipo coincide, usa la
  versión con **efecto**; si no, la arma **vainilla con los datos exactos** de la
  tabla. `X` en el coste se trata como 0.
- Nota: si la lista es parcial, el relleno de básicas infla las tierras (mana
  flood). Para winrates fieles, exportá la lista completa.

Para agregar un deck: dejá su `.md` en `presets/` con ese formato.

### Cargar un precon desde Moxfield

El desplegable de precons (MTGJSON) es una comodidad y puede fallar según la
red del deploy. Alternativa siempre confiable: abrí el precon en Moxfield →
**Export** → copiá el texto (`1 Nombre de Carta`) → pegalo en `/deck` →
**Resolver**. Scryfall lo construye en Vercel. (La API de Moxfield no es pública
y bloquea automatización, por eso no se consume directo.)

## Importar y editar decks (precon / propios)

La app permite **cargar una lista de mazo**, editar cartas y **probar
variaciones** midiendo la tasa de victoria (`/deck` en la web).

**De dónde sale la info de cartas:**

| Fuente | Qué aporta |
|---|---|
| [Scryfall](https://scryfall.com/docs/api) `/cards/collection` | Datos reales de cada carta (coste, tipos, P/T, keywords, colores). Se llama en runtime desde la función serverless (Vercel), hasta 75 cartas por request. |
| [MTGJSON](https://mtgjson.com/data-models/deck/) `/api/v5/decks/` | Listas **precon completas** de Commander (para poblar un catálogo). |
| Moxfield / Archidekt | Export de texto del deck propio (`1 Nombre de Carta`). |

**Cómo funciona la cobertura:** las cartas con **efecto programado** (registro en
`cardsdb.py`) se simulan con sus habilidades; el resto se construye con **stats
reales de Scryfall** (vainilla pero con coste/P/T/tipos/keywords correctos), así
combate, maná y curva son fieles aunque el efecto especial no esté. **No se
inventan datos** (regla del proyecto): lo que no está registrado se resuelve por
Scryfall o queda marcado como no resuelto.

**Piezas:**
- `cardsdb.py` — registro nombre→carta implementada + `build_card_from_data`
  (dict tipo Scryfall → `Card`). Puro y testeable sin red.
- `decklist.py` — parser de listas (Moxfield/Archidekt/texto) y armado a 99.
- `api/_scry.py` — cliente Scryfall (stdlib, corre en Vercel).
- `api/deck.py` — `POST /api/deck` con `action: "resolve"` (tabla editable) y
  `action: "simulate"` (winrate del deck editado vs un mazo registrado).
- `app/deck/` — UI: pegar lista → tabla editable → probar variación.

> Nota: la resolución vía Scryfall requiere salida a internet. En Vercel
> funciona; en entornos de red restringida solo resuelven las cartas
> registradas y las tierras básicas.

## Cómo agregar cartas

Ver [`docs/ADDING_CARDS.md`](docs/ADDING_CARDS.md). Resumen: una entrada en
`cards.py` con sus ganchos y tags, y una línea en `decks.py`. Verificá con
`python3 coverage.py` y `python3 run.py <a> <b> --log`.

## Reglas del proyecto

Ver [`CLAUDE.md`](CLAUDE.md) y [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Las tres invariantes que ya causaron bugs y no se deben reintroducir:

1. **`engine.py` no conoce cartas concretas.** Si hace falta tocarlo para una
   carta, lo que falta es un gancho genérico.
2. **`produces` devuelve OPCIONES, no producción simultánea.** Una tierra dual
   `{R:1, W:1}` vale UN maná.
3. **Todo evento "en tu turno" va en `Game.SELF_SCOPED`**, o dispara para todos.
