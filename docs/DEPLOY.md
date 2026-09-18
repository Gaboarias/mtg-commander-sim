# Deploy (Vercel)

Producción se despliega desde la rama **`main`**. `mtg-commander-sim.vercel.app`
sirve el último deploy de producción listo.

## Regla importante: pushear a `main` PRIMERO

Vercel deduplica los deploys por **SHA de commit**. Si se pushea el **mismo
commit** a la rama de desarrollo y a `main` casi al mismo tiempo (un fast-forward
deja el mismo SHA en ambas refs), Vercel puede crear el deploy de **preview** de
la rama y **saltear el build de producción** de `main`. Resultado: producción
queda atrasada respecto a `main`.

Para evitarlo, al publicar:

1. `git push origin main` (esto dispara el build de **producción**).
2. Recién después, `git push origin <rama-de-trabajo>` (preview).

Así el SHA llega primero a `main` y Vercel sí construye producción.

## Verificar qué hay en producción

- Deployments y su commit/estado: panel de Vercel del proyecto
  `mtg-commander-sim`, o la API/MCP de Vercel (`list_deployments`).
- El deploy de producción vigente es el más reciente con `target: production` y
  `state: READY`.
