# Rey Taco Picks: archivo R2, Mini App de Telegram y video social

**Fecha:** 5 de septiembre de 2026
**Estado:** aprobado para especificación; pendiente de revisión escrita
**Alcance:** primera entrega de infraestructura multimedia, Mini App de consulta, video animado y medición de conversión

## Objetivo

Crear una capa de medios y conversión alrededor del flujo existente de Rey Taco
Picks sin alterar la extracción de Playdoit, la regla de máximo seis picks por
ventana, la separación Free/VIP ni el verificador de resultados.

La primera entrega debe permitir:

1. conservar de forma durable los originales y derivados multimedia en
   Cloudflare R2;
2. generar videos verticales animados y reproducibles con Remotion a partir de
   datos ya persistidos;
3. ofrecer una Mini App de Telegram de solo lectura con cartelera, ventanas,
   estado VIP, historial y CTA;
4. medir vistas y conversiones con Plausible sin enviar datos personales;
5. mantener las Stories estáticas y el renderer FFmpeg actuales como camino
   estable y fallback;
6. dejar preparada una segunda fase para quiniela semanal y mejoras de
   contenido para AdSense.

## Principios y límites

- Supabase continúa siendo la fuente autoritativa de picks, resultados,
  membresías, reclamaciones y recibos de publicación.
- R2 es almacenamiento de objetos, no una segunda base de datos ni una fuente
  de permisos.
- Ningún renderer puede leer Playdoit ni inventar selecciones; recibe paquetes
  inmutables derivados de Supabase.
- Todo comando de generación tiene dry-run o preview por defecto.
- No se publican Stories, Reels, Telegram o Meta durante pruebas locales o CI.
- No se guardan tokens, claves, `initData`, `file_id` de Telegram ni datos
  personales en logs, eventos de analítica, nombres de objetos o artefactos de
  prueba.
- La recuperación de una ventana vacía no despublica material anterior.
- La Mini App no contiene cobros, administración, edición de picks ni comandos
  de resultados en esta fase.

## Descomposición de entrega

La implementación se divide en PRs pequeños y ordenados:

1. **R2 y contrato multimedia:** adaptador de almacenamiento, configuración,
   ledger de objetos, URLs de entrega, retención y pruebas.
2. **Remotion:** paquete de video animado, composición de resultados/picks,
   validación MP4 y preview local; integración opcional con el publisher.
3. **Mini App:** ruta `/telegram`, puente seguro de Telegram a Supabase y
   componentes móviles de la opción C aprobada.
4. **Plausible y conversión:** carga condicional, eventos agregados, medición de
   ventana y CTA sin PII.
5. **Quiniela y AdSense:** diseño e implementación posterior, sin bloquear el
   scraper ni la entrega de medios.

R2 se entrega primero porque Remotion y el publisher necesitan un contrato
estable para subir y recuperar multimedia. Mini App puede desarrollarse en
paralelo desde el punto de vista de código, pero se valida contra la misma
fuente de datos.

## Arquitectura de almacenamiento R2

### Responsabilidades

El nuevo adaptador `R2MediaStore` utilizará la API S3-compatible de Cloudflare
R2. La interfaz será pequeña y testeable:

- `put(object_key, payload, content_type, metadata)`;
- `get(object_key)` solo para trabajos de servicio autorizados;
- `temporary_delivery_url(object_key, expires_in)`;
- `delete_temporary(object_key)`;
- `exists(object_key)` para evitar renders repetidos.

El adaptador no recibirá ni imprimirá credenciales. La configuración se obtiene
exclusivamente del entorno protegido:

- `R2_ACCOUNT_ID`;
- `R2_ACCESS_KEY_ID`;
- `R2_SECRET_ACCESS_KEY`;
- `R2_BUCKET`;
- `R2_PUBLIC_BASE_URL` solo si se habilita un dominio de entrega pública.

No se creará el bucket automáticamente. Antes de la salida se verificará el
bucket y el dominio exactos en Cloudflare, y se guardarán únicamente sus
nombres en configuración no secreta.

### Convención de objetos

Los objetos derivados usarán una clave estable y direccionada por contenido:

`derived/{portfolio_date}/{content_kind}/{sha256}.{extension}`

Los originales de evidencia usarán una zona privada separada:

`evidence/{received_date}/{sha256}.{extension}`

El hash se calcula sobre bytes y parámetros editoriales canónicos. No se usan
nombres de equipos, correos, IDs de Telegram ni texto libre en las rutas.

### Privacidad y ciclo de vida

- `evidence/` permanece privado y solo se sirve mediante URL temporal después de
  pasar la inspección existente.
- `derived/` contiene únicamente piezas aprobadas; una URL pública solo se
  habilita para piezas sin información privada.
- Los objetos temporales de una entrega fallida se eliminan de forma best
  effort y quedan registrados como fallo en Supabase.
- Los derivados aprobados y evidencias válidas se conservan para historial y
  auditoría; no se añade borrado automático destructivo en la primera versión.
- Supabase conserva el hash, clave, tipo MIME, tamaño, estado, origen,
  `portfolio_date` y recibo de entrega, nunca el secreto de acceso.

El ledger de `vertical_media_delivery` seguirá siendo la barrera idempotente:
una combinación de paquete, destino, digest y versión no se publica dos veces.

## Remotion

### Ubicación y entrada

Se añadirá un paquete independiente `social-video/` con Node, Remotion y una
composición registrada. Recibirá un `ReelInput` JSON validado que contenga:

- `batch_id` y `portfolio_date`;
- estados y datos de resultados ya verificados, o el pick público autorizado;
- textos editoriales escapados;
- digest de la plantilla;
- referencias a imágenes aprobadas, sin tokens ni URLs privadas permanentes.

Remotion no consultará Supabase, Telegram, Meta ni Playdoit. Python construirá
el paquete desde las fuentes existentes y el renderer solo producirá bytes.

### Contrato de salida

- MP4 H.264, 1080×1920, 30 FPS, `yuv420p` y `faststart`;
- 8–15 segundos para un reel editorial;
- tres a cinco escenas, con transición determinista;
- CTA final con `reytacopicks.com`, `18+` y juego responsable;
- sin música comercial, voz sintética ni assets externos sin licencia;
- validación con FFprobe antes de subir a R2 o solicitar a Meta.

La composición inicial será un reel de resultados y una variante de teaser de
ventana. El flujo FFmpeg actual permanece activo mientras Remotion pasa
preview, pruebas de contrato y una salida controlada. `REMOTION_ENABLED=false`
será el valor inicial en producción.

## Mini App de Telegram

### Experiencia

La opción C refinada se implementará dentro del frontend Vite existente en la
ruta `/telegram`. La primera pantalla contiene:

- encabezado de marca y fecha CDMX;
- resumen de ventana actual y cantidad pública;
- cartelera de las cuatro ventanas del día;
- tarjeta completa solo para picks públicos;
- bloque VIP con cantidad agregada, sin equipos, mercados, cuotas ni
  razonamiento premium;
- historial verificado;
- navegación inferior y CTA de acceso VIP/Telegram.

Los cuatro bloques permanecen visibles, incluidos los vacíos. Los estados son
`Cerrado`, `En curso`, `Próximo` y `Sin selección`, calculados con la misma
función de hora CDMX que usa la web.

### Identidad segura

Se añadirá una Edge Function `telegram-mini-app` que:

1. recibe `initData` por POST y nunca lo escribe en logs;
2. verifica la firma HMAC con el secreto del bot y rechaza datos vencidos;
3. obtiene el `telegram_id` verificado del payload, sin confiar en
   `initDataUnsafe` del navegador;
4. consulta el perfil vinculado y la membresía en Supabase;
5. devuelve un DTO mínimo con cartelera pública, conteo VIP, estado de vínculo,
   historial permitido y CTA;
6. no permite mutaciones, consultas arbitrarias ni acceso administrativo.

El enlace de cuenta reutiliza el flujo existente de tokens de Telegram. Un
usuario no vinculado ve la cartelera pública y una instrucción para vincularse;
un usuario VIP recibe los detalles completos mediante la respuesta autorizada.
El navegador nunca consulta directamente filas premium como visitante anónimo.

### Integración con Telegram

El bot podrá abrir la Mini App mediante un deep link `startapp` que solo
identifica la vista solicitada. La aplicación llamará `Telegram.WebApp.ready()`
si el SDK está presente, pero seguirá funcionando como página web móvil si se
abre fuera de Telegram.

## Plausible

La instrumentación actual conserva sus nombres de evento y añadirá un
transportador opcional a Plausible:

- `miniapp_opened`;
- `free_pick_viewed`;
- `vip_offer_viewed`;
- `telegram_clicked`;
- `checkout_started`;
- `subscription_confirmed`.

Los eventos pueden incluir solo propiedades agregadas como `window_slot` o
`surface` (`web`, `telegram_miniapp`). No se envían correo, usuario de
Telegram, pick ID, cuota, partido, token, IP ni texto libre. Si
`VITE_PLAUSIBLE_DOMAIN` no está configurado, la app conserva el `dataLayer` y
no genera solicitudes externas.

La primera revisión de conversión comparará publicaciones de 11 a. m. y 11
p. m. mediante la ventana agregada, no mediante datos identificables.

## Quiniela semanal y AdSense: fase posterior

### Quiniela

La quiniela será un módulo separado, no una fuente de picks. El diseño futuro
debe incluir registro de entrada, corte semanal explícito, una participación por
cuenta, resultados derivados de fuentes verificadas, desempate documentado y
premio de una semana VIP con ledger idempotente. No se promete una ventaja
deportiva ni se mezcla con la selección de seis picks.

### Contenido para AdSense

Antes de volver a solicitar AdSense se reforzará la web con contenido original
firmado y útil: método explicado, fuentes y limitaciones, guía de cuotas,
resultados completos, preguntas frecuentes, autoría, privacidad, términos y
juego responsable. No se crearán páginas repetitivas generadas para rellenar
espacio ni afirmaciones de ganancias.

## Flujo integrado

1. El scraper recolecta y persiste el lote exacto en Supabase.
2. El publisher construye una tarjeta estática o un `ReelInput` solo desde ese
   lote.
3. El renderer valida bytes, digest y contrato visual.
4. R2 guarda el derivado; Supabase registra la clave y el estado.
5. El orquestador solicita URL temporal solo para la ventana de entrega.
6. Meta/Telegram reciben la pieza mediante los transportes existentes; cada
   destino se reclama y registra por separado.
7. El objeto temporal se elimina después de un recibo confirmado; el derivado
   aprobado permanece archivado.
8. Plausible mide la interacción sin afectar la autorización de datos.

Un fallo de R2 no borra picks ni bloquea Telegram textual. Un fallo de una red
no revierte otra entrega exitosa. Un fallo de Remotion mantiene FFmpeg como
fallback mientras el modo de video animado esté desactivado.

## Verificación y salida

Cada PR debe incluir:

- pruebas unitarias de validación, digest, permisos y límites de tamaño;
- pruebas de contrato para el ledger y migraciones Supabase;
- preview local de una historia y un reel, sin publicaciones reales;
- prueba de Mini App con `initData` válido, vencido, manipulado y usuario no
  vinculado;
- prueba de que ninguna solicitud de analítica contiene PII;
- `pytest`, pruebas Vitest, `typecheck`, `build` y `git diff --check`;
- un canario explícito con `publish=false` antes de cualquier `--live`.

La aceptación de producción exige observar al menos un ciclo completo:
recolección, staging, liberación, entrega de destinos, visualización web y
recibos. El éxito de una acción de GitHub sin esos conteos no se considera
entrega completa.

## Fuera de alcance de esta especificación

- Cambiar la lógica de Playdoit, categorías o ranking de IA.
- Crear combinaciones infinitas de `Crear Apuesta`.
- Reemplazar la fuente de picks de Supabase.
- Cobros dentro de Telegram o un panel administrativo en la Mini App.
- Publicación automática en nuevas redes.
- Uso de tokens o credenciales encontrados en archivos de conversación.
- Borrar o reescribir historial de resultados.
