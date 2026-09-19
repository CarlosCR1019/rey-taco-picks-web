# Runbook: multimedia y Mini App

Este runbook describe una salida gradual y reversible. No cambia el scraper,
la selección de picks ni los cuatro horarios de publicación.

## Valores iniciales

```dotenv
MEDIA_STORAGE_BACKEND=supabase
REMOTION_ENABLED=false
VITE_PLAUSIBLE_DOMAIN=
VITE_TELEGRAM_MINI_APP_PATH=/?view=telegram
```

R2 permanece apagado hasta verificar manualmente el bucket privado, región,
dominio exacto y permisos mínimos. Las claves R2, service role, bot y Meta van
únicamente en el gestor de secretos; nunca en Git, fixtures, logs, issues,
capturas o mensajes.

## Secuencia de canario

1. Ejecutar pruebas locales de Python, frontend, `social-video` y la Edge
   Function sin credenciales reales.
2. Generar una historia y un reel en modo preview local. Confirmar digest,
   MIME, tamaño, dimensiones, duración y ausencia de datos premium o PII.
3. Verificar que `REMOTION_ENABLED=false` usa exactamente el renderer FFmpeg
   existente y que un fallo de Remotion vuelve a ese fallback.
4. Activar Plausible solo con un dominio válido y confirmar eventos agregados;
   si falta el dominio, no debe haber solicitudes externas.
5. Publicar la Edge Function de Mini App solo después de revisar HMAC, CORS,
   expiración, perfil vinculado y separación VIP. La función es de solo lectura.
   `supabase/config.toml` desactiva el JWT del gateway únicamente para esta
   función porque Telegram autentica cada solicitud con `initData` firmado;
   no retirar esa validación HMAC ni ampliar la excepción a otras funciones.
6. Conservar la publicación textual existente como indicador operativo. Un
   fallo multimedia o de Mini App no debe impedir picks ni Telegram textual.

## Revisión y rollback

- Si R2 falla, volver a `MEDIA_STORAGE_BACKEND=supabase` y conservar el ledger.
- Si Remotion falla, mantener `REMOTION_ENABLED=false`; el fallback no requiere
  migración ni reintento de publicación.
- Si la Mini App falla, retirar el enlace de entrada o desactivar su endpoint;
  el sitio raíz y el bot textual siguen operando.
- Si Plausible falla, dejar vacío `VITE_PLAUSIBLE_DOMAIN`; `dataLayer` local no
  contiene identificadores.
- No hacer reset de Supabase ni ejecutar migraciones remotas como parte de un
  rollback de contenido.

## Aceptación del canario

Guardar evidencia local de la validación, no de secretos: pruebas verdes,
diff limpio, una salida multimedia derivada y una comprobación de que no hubo
llamadas a publicación. La activación de producción requiere revisión humana y
autorización explícita posterior.
