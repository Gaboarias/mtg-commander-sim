# Formato de lista para el simulador

Cada mazo es un `.md` con secciones y una tabla por seccion. El importador
(tarea P4 del backlog) lee las tablas e ignora todo lo demas.

```
| n | Carta | Coste | P/T | Keywords | Tags |
```

- **n** — cantidad. Siempre 1 salvo basicas.
- **Coste** — formato `parse_cost`: digitos = generico, letras = simbolos.
  `2RW` son 4 manas. Vacio para tierras.
- **P/T** — solo criaturas. Vacio para el resto.
- **Keywords** — separadas por espacio, de la lista soportada:
  `flying reach trample deathtouch lifelink vigilance haste first_strike
  double_strike menace indestructible defender`
- **Tags** — lo que lee la IA: `engine ramp draw removal wipe creature gy_exile`

**`?` en cualquier columna** = dato sin confirmar. El importador debe fallar
ruidosamente en vez de adivinar.

**Las tierras** van en su propia seccion con los colores que producen entre
corchetes: `[R W]`. Recuerda que eso son OPCIONES, no produccion simultanea.
