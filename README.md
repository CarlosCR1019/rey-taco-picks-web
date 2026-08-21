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

La configuración, migración y salida controlada a producción están documentadas
en [el runbook de seguridad, pagos y scraper](docs/operations/security-and-payments.md).
No ejecute el scraper en modo de publicación hasta completar ese procedimiento.

> Estado al 21 de agosto de 2026: esta tarea no aplicó migraciones remotas ni
> despachó el workflow de producción.
