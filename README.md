# Rey Taco Picks

Plataforma mexicana de análisis deportivo con una selección pública y contenido
VIP. El scraper publica lotes idempotentes en Supabase, genera una proyección
pública sin razonamiento premium y entrega Telegram por destino de forma
independiente.

## Desarrollo local

Desde la raíz del repositorio:

```powershell
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
deno test --allow-env supabase/functions
```

Si Deno no está instalado globalmente, use:

```powershell
npx --yes deno test --allow-env supabase/functions
```

El modo seguro del scraper no requiere `SUPABASE_SERVICE_ROLE_KEY` y no escribe
en Supabase, archivos ni Telegram:

```powershell
python backend/scraper.py --dry-run
```

## Operacion hibrida en dos PC

La recoleccion de Playdoit vive en `.github/workflows/collector.yml` y se
asigna solamente a un runner Windows privado con la etiqueta
`playdoit-residential`. La PC ejecuta `--collect-only`: valida y persiste el
lote exacto, pero no recibe secretos de Telegram o Meta, no publica contenido
y nunca es apagada o suspendida por la automatizacion.

El job `deliver_cloud` reanuda el mismo `SCRAPER_RUN_KEY` en `ubuntu-latest`
con `--deliver-only`; desde ahi salen Telegram y, cuando sus IDs esten
configurados, Facebook e Instagram. La verificacion de resultados tambien
permanece en GitHub Cloud. Consulte [la instalacion de los dos runners](docs/operations/windows-runners.md).

La configuración, migración y salida controlada a producción están documentadas
en [el runbook de seguridad, pagos y scraper](docs/operations/security-and-payments.md).
No ejecute el scraper en modo de publicación hasta completar ese procedimiento.

> Estado al 23 de agosto de 2026: el esquema seguro y la clave de servicio ya
> estan configurados. Todavia no se ha despachado el nuevo collector ni se ha
> autorizado una publicacion real desde este flujo.
