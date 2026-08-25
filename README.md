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

## Historias y reels

El contenido vertical se genera localmente con las plantillas auditadas de Rey
Taco. Las historias son JPEG de 1080 x 1920 y el reel diario es un MP4 vertical
creado con FFmpeg a partir de resultados ya verificados. No depende de un
servicio generativo de pago ni abre una ventana del navegador.

Toda ejecución exige indicar de forma explícita si es una prueba o una
publicación real. Para guardar material revisable sin contactar a Meta:

```powershell
$env:VERTICAL_DRY_RUN_OUTPUT = "artifacts/vertical-preview"
python -m backend.vertical_publisher --mode pre-event --dry-run
python -m backend.vertical_publisher --mode final --dry-run
```

El modo real requiere `--live`, las migraciones aplicadas y los secretos de
Supabase y Meta configurados. Las dos salidas controladas pueden separarse:

```powershell
python -m backend.vertical_publisher --mode final --live --stories-only
python -m backend.vertical_publisher --mode final --live --reel-only
```

La API devuelve un recibo de la historia de Instagram. Si Meta la muestra
también como historia de Facebook por crossposting, esa aparición se valida por
separado; no se presenta como si fuera un segundo recibo de la API. El ledger de
Supabase impide volver a publicar una pieza ya completada y conserva como
`pending_review` cualquier respuesta remota ambigua.

Las variables de ejemplo solo nombran la configuración. Nunca guarde tokens en
los archivos `.env.example`; los secretos de producción pertenecen a GitHub
Actions o al entorno protegido del runner.

> Estado al 25 de agosto de 2026: el flujo vertical está implementado y validado
> localmente. Su despliegue permanece detenido hasta aplicar las migraciones
> pendientes y completar una salida controlada con recibos verificados.
