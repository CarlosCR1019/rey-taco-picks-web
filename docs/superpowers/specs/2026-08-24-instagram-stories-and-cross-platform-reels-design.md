# Rey Taco Picks: historias de Instagram y reels multiplataforma

**Fecha:** 24 de agosto de 2026
**Estado:** aprobado en conversación; pendiente de revisión escrita
**Alcance:** generación local gratuita, publicación desatendida y evidencia original

## Objetivo

Extender el flujo editorial existente con historias verticales de Instagram y
reels para Instagram y Facebook, sin depender de servicios generativos de pago,
sin operar el navegador y sin modificar el comportamiento actual del bot de
Telegram.

La solución debe:

1. publicar un pick público y un avance VIP antes de los eventos;
2. mostrar los seis resultados de la jornada después de la liquidación;
3. acompañar una tarjeta de resultado con la fotografía original del ticket;
4. conservar visible el ID completo del ticket como evidencia;
5. convertir las mismas piezas verticales en un reel corto;
6. funcionar de forma idempotente cuando cualquiera de las dos PC Windows esté
   disponible;
7. permitir que los reportes de resultados sigan funcionando aun cuando ninguna
   fotografía esté disponible;
8. mantener Telegram, la web, el scraper, los Salmos y las publicaciones actuales
   de feed sin regresiones.

## Decisión técnica

Se utilizará un motor local y determinista:

- HTML/CSS o Pillow para imágenes de 1080 por 1920 píxeles;
- FFmpeg para video MP4 vertical;
- Supabase como fuente autoritativa, ledger y alojamiento temporal;
- Telegram Bot API para recuperar la fotografía original mediante el `file_id`
  ya registrado por el bot;
- Meta Graph API para publicar historias en Instagram y reels en Instagram y
  Facebook.

No se utilizarán como dependencia de producción APIs gratuitas de video, modelos
generativos, automatización visual de Meta Business Suite ni Canva. Esas opciones
añaden cuotas, variación, sesiones interactivas o fragilidad y no mejoran los
datos del contenido.

Referencias de integración vigentes al aprobar el diseño:

- [Instagram API oficial de Meta](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Facebook Reels API oficial de Meta](https://www.postman.com/meta/facebook/folder/simabyk/reels-publishing)

## Experiencia editorial aprobada

### Antes del evento

La secuencia previa contiene como máximo dos historias:

1. **Pick público del día.** Muestra la selección pública destacada, evento,
   mercado, momio observado, horario CDMX y aviso responsable.
2. **Avance VIP.** Muestra la cantidad total de selecciones y una invitación al
   acceso VIP, pero no revela equipos, mercados, momios ni razonamiento de las
   cuatro filas premium.

La selección pública proviene únicamente del lote persistido. No se puede usar
una selección premium ni un archivo local viejo como sustituto.

### Después del evento

La secuencia de resultados contiene:

1. **Resumen de jornada.** Muestra las seis selecciones y sus estados terminales,
   incluidos ganados, perdidos y void. No se escogen solamente resultados
   favorables.
2. **Resultado verificado.** Tarjeta de marca para una selección o ticket
   destacado, con partido, selección, momio observado, marcador y fecha de
   verificación.
3. **Evidencia original.** Fotografía completa del ticket, sin reconstrucción,
   recorte de información deportiva ni ocultamiento del ID.

Si la fotografía todavía no existe, se publican el resumen y la tarjeta. Cuando
la evidencia aparezca y sea validada, se añade como una historia posterior. La
ausencia de fotografía nunca cambia el resultado ni bloquea Telegram, la web o el
reporte social de datos.

### Reel diario

El reel reutiliza de tres a cinco piezas aprobadas:

- portada de resultados;
- resumen de la jornada;
- una o más tarjetas destacadas;
- una fotografía original cuando exista evidencia válida;
- cierre con `reytacopicks.com`, `18+` y apuesta responsable.

Su duración objetivo es de 8 a 15 segundos. Solo se genera cuando haya un cierre
final o contenido suficiente; no se crea un video vacío para cumplir una cuota.
Se recomienda como máximo un reel al día.

## Identidad visual y copy

- Paleta principal: azul marino, dorado y crema del logotipo.
- El logotipo de Rey Taco se conserva con zona de seguridad y sin deformación.
- La información esencial permanece dentro de la zona segura vertical para no
  quedar cubierta por la interfaz de Instagram.
- El ticket original se ajusta con `contain`: nunca se recorta. Cuando no cubra
  9:16, se utiliza un fondo oscuro o una copia desenfocada detrás de la fotografía.
- La casa de apuestas solo aparece dentro de la evidencia original. Rey Taco no
  imita su interfaz ni afirma patrocinio o asociación.
- El ID completo del ticket permanece visible.
- El texto usa español para México, bloques cortos y jerarquía clara.
- Se prohíben afirmaciones como `seguro`, `garantizado`, `IA no falla`, `profit
  masivo` o `+EV` cuando no exista un cálculo auditado persistido.
- Cada pieza incluye `18+` y una referencia breve a apuesta responsable.

## Contratos de medios

### Historias

- JPEG estándar;
- 1080 por 1920 píxeles;
- orientación 9:16;
- perfil de color sRGB;
- límite de tamaño compatible con el bucket y Meta;
- texto derivado solo de datos validados;
- fotografía original conservada en proporción y sin re-muestreo destructivo.

### Reels

- contenedor MP4;
- video H.264, 1080 por 1920, 30 FPS y `yuv420p`;
- duración entre 8 y 15 segundos en la salida editorial;
- `faststart` habilitado;
- audio AAC solo cuando exista una pista autorizada; la ausencia de audio es una
  salida válida;
- validación con FFprobe antes de cualquier solicitud a Meta.

La primera versión usa transiciones locales simples. No añade música comercial,
voz sintética ni contenido de terceros sin licencia.

## Fuentes de verdad

### Picks y resultados

Supabase sigue siendo la única fuente autoritativa de:

- lote activo y fecha de portafolio;
- visibilidad pública o premium;
- evento, mercado, selección, momio y horario;
- estado del resultado;
- marcador, fuente y momento de verificación;
- entregas ya completadas.

Las historias previas requieren una fila pública, pendiente, activa y futura. Las
historias de resultados requieren filas terminales verificadas. Una fila en
revisión no puede anunciarse como ganada o perdida.

### Fotografías del bot

`backend/ticket_listener.py` conserva su comportamiento actual:

1. recibe la fotografía del administrador autorizado;
2. descarga el JPEG a `frontend/public/tickets`;
3. actualiza el manifiesto local;
4. registra `archivo`, `caption` y `file_id` en `tickets_ganadores` cuando
   Supabase está disponible;
5. reenvía la fotografía a los grupos configurados.

El nuevo flujo no vuelve a reenviar la fotografía ni modifica ese orden. Un
adaptador independiente lee las filas de `tickets_ganadores` y recupera el
archivo original desde Telegram con el `file_id`, por lo que la evidencia no
depende de una ruta local específica ni de cuál PC recibió el mensaje.

## Validación y vinculación de evidencia

Una fotografía puede convertirse en evidencia social solo si:

- fue registrada por el chat administrador autorizado;
- Telegram devuelve un JPEG válido dentro de los límites configurados;
- no contiene metadatos o dimensiones anómalas;
- la inspección de privacidad no detecta nombre, teléfono, correo, saldo,
  usuario u otro identificador personal;
- existe coincidencia suficiente con el portafolio liquidado.

La inspección será un límite inyectable. En producción podrá utilizar OCR local
gratuito; las pruebas usan salidas deterministas. Si el OCR no está disponible o
su resultado es ambiguo, la evidencia queda `pending_review`. Nunca se publica
suponiendo que pertenece a un partido.

Para un ticket individual, la coincidencia necesita al menos el evento o los dos
equipos junto con un marcador/selección compatible. Para un ticket múltiple, debe
haber coincidencias con varias selecciones del mismo portafolio. El ID del ticket
se extrae para trazabilidad, no como credencial, y se conserva visible en la
imagen.

## Componentes

La implementación separará estas responsabilidades:

- `StoryPackageRepository`: obtiene el lote exacto y reclama cada pieza social;
- `StoryRenderer`: genera historias previas y tarjetas de resultado;
- `TicketEvidenceRepository`: obtiene evidencia pendiente y persiste su estado;
- `TicketMediaFetcher`: recupera bytes originales desde Telegram sin registrar el
  token;
- `EvidenceInspector`: valida archivo, privacidad y coincidencia;
- `ShortVideoRenderer`: compone y valida el MP4 con FFmpeg/FFprobe;
- `TemporaryMediaStore`: publica el archivo solo durante el tiempo necesario;
- `InstagramStoryTransport`: crea, espera y publica el contenedor de historia;
- `InstagramReelTransport`: crea, espera y publica el contenedor de reel;
- `FacebookReelTransport`: ejecuta las fases de inicio, carga y finalización;
- `StoryReelOrchestrator`: coordina destinos de forma independiente.

El HTML heredado `backend/report_story_9_16.html` contiene datos fijos, fuentes de
red y afirmaciones antiguas. No puede ser una plantilla de producción. Debe
reemplazarse por un renderer que reciba un paquete explícito y escapado, o quedar
retirado del flujo.

## Flujo de publicación

### Historias previas

1. El collector persiste el lote y concluye la entrega de picks.
2. El orquestador solicita exactamente el lote de esa ejecución.
3. Supabase concede una reclamación para `public_pick_story` y luego para
   `vip_teaser_story`.
4. El renderer produce el JPEG local.
5. Storage expone una URL HTTPS temporal y validada.
6. Instagram crea el contenedor `STORIES`, se espera un estado apto y se publica.
7. Se registra el ID remoto y se elimina el objeto temporal después de confirmar
   la publicación.

### Resultados y evidencia

1. El verificador liquida filas con evidencia deportiva válida.
2. El reporte final existente se publica en sus destinos actuales.
3. El orquestador reclama `final_results_story` y publica el resumen completo.
4. Si existe evidencia vinculada, reclama `verified_result_story` y
   `ticket_evidence_story` en ese orden.
5. Si la evidencia aparece después, una ejecución posterior puede reclamar solo
   la pieza pendiente sin repetir el resumen.

### Reel

1. Un cierre final elegible reclama `daily_results_reel`.
2. Se renderizan o recuperan únicamente piezas aprobadas del mismo portafolio.
3. FFmpeg produce el MP4 y FFprobe valida el contrato.
4. Instagram y Facebook se reclaman como destinos separados.
5. El éxito de una red se conserva aunque la otra falle.
6. Un reintento llama únicamente al destino incompleto.

## Integración con Meta

### Instagram Stories

La cuenta debe seguir siendo profesional Business. El transporte:

1. envía `image_url` y `media_type=STORIES` a `/<IG_USER_ID>/media`;
2. exige un ID de contenedor;
3. consulta un estado documentado con espera corta y limitada;
4. publica mediante `/<IG_USER_ID>/media_publish`;
5. exige un ID de media antes de marcar éxito.

### Instagram Reels

El transporte crea un contenedor `REELS` con una URL pública temporal, espera el
procesamiento, publica mediante `media_publish` y registra el ID remoto. El reel
puede compartirse al feed para ampliar alcance cuando el parámetro siga disponible
en la versión configurada de Graph.

### Facebook Reels

El transporte de Page Reels usa las fases oficiales:

1. inicio en `/<FB_PAGE_ID>/video_reels`;
2. carga binaria o por URL al destino `rupload` retornado;
3. consulta opcional de estado;
4. finalización con estado publicado;
5. recibo remoto obligatorio.

### Facebook Stories

El diseño no promete un endpoint que Meta no documenta en la integración actual.
La historia de Facebook depende del uso compartido automático configurado entre
Instagram y Facebook. La prueba controlada debe confirmar ese comportamiento. Si
no ocurre, el estado se reporta como `crosspost_unverified`; no se simula éxito ni
se automatiza el navegador.

## Alojamiento temporal

Las historias y reels usan prefijos separados dentro de Storage:

- `stories/<portfolio-date>/<content-key>-<digest>.jpg`;
- `reels/<portfolio-date>/<content-key>-<digest>.mp4`;
- `evidence/<portfolio-date>/<evidence-id>-<digest>.jpg`.

Solo se aceptan objetos generados o validados por el proceso confiable. Las URLs
deben apuntar al host exacto de Supabase y al prefijo esperado. El token de Meta,
el token del bot, picks premium previos, HTML fuente y logs nunca entran al bucket.

El objeto se elimina únicamente después de que Meta confirme que terminó de
recibir/procesar el medio y se registre el recibo. Una limpieza posterior elimina
objetos abandonados con antigüedad mayor al límite definido. Un fallo de limpieza
se registra por separado y no convierte una entrega real en fracaso.

## Idempotencia y concurrencia

Una nueva migración debe proporcionar reclamación y finalización atómicas por:

- portafolio;
- tipo de contenido;
- digest del contenido;
- destino;
- versión de plantilla.

Los estados mínimos son `pending`, `claimed`, `complete`, `failed` y
`pending_review`. Una reclamación posee `attempt_id` y vencimiento. Solo el dueño
del intento puede finalizarla.

Dos PC pueden iniciar la misma tarea, pero Supabase concede una sola reclamación.
Una entrega `complete` nunca se repite para el mismo digest. Si los datos cambian
legítimamente, cambia el digest y se crea una revisión explícita; no se sobrescribe
el recibo anterior.

## Fallos y recuperación

- El scraper y Telegram no se revierten por un fallo de historia o reel.
- Cada destino se intenta y registra independientemente.
- Configuración ausente produce `not_configured`.
- Token inválido produce `token_invalid` sin imprimir la respuesta ni el secreto.
- Medio rechazado produce `media_invalid`.
- Evidencia ambigua produce `pending_review`, no `complete`.
- Una respuesta sin ID remoto no puede marcarse exitosa.
- Los reintentos usan espera limitada y nunca ocupan indefinidamente al runner.
- El canal administrativo recibe un resumen seguro cuando una pieza queda
  incompleta después de los reintentos permitidos.
- Una ejecución posterior puede recuperar reclamaciones vencidas y completar
  únicamente las piezas faltantes.

## Ejecución en segundo plano

La solución no abre Chrome, no usa Playwright para Meta, no mueve el mouse y no
presenta ventanas. Los renderers y transportes se ejecutan como procesos de consola
ocultos dentro de los workflows existentes o de los runners Windows interactivos
ya aprobados.

El trabajo previo se activa después de un lote publicado. El trabajo de resultados
se activa después del verificador. La evidencia tardía se revisa en ejecuciones
posteriores. La misma lógica funciona en cualquiera de las dos PC porque los
datos, reclamaciones y `file_id` viven en Supabase.

## Seguridad

- `META_SYSTEM_USER_ACCESS_TOKEN` y el token del bot permanecen en secretos.
- Los tokens se envían en cuerpo o encabezados y nunca en URLs registradas.
- Los errores de Meta y Telegram se reducen a clases permitidas.
- No se registran cuerpos de respuesta, imágenes ni OCR completo.
- La descarga de Telegram acepta únicamente su host documentado y el `file_path`
  devuelto para un `file_id` registrado.
- El renderer escapa todo texto y no carga fuentes, scripts o imágenes remotas no
  autorizadas.
- La imagen original no se edita para ocultar el ID; si contiene datos personales,
  se detiene toda la evidencia.
- No se afirma afiliación con Playdoit ni otra casa de apuestas.

## Pruebas

La implementación seguirá TDD e incluirá:

1. contratos de paquetes previos y finales;
2. rechazo de filas premium en historias previas;
3. resumen completo con ganados, perdidos y void;
4. JPEG 1080 por 1920 y zonas seguras;
5. ajuste `contain` de fotografías sin recorte;
6. ID completo preservado en evidencia válida;
7. rechazo de archivo, fuente o datos personales no permitidos;
8. coincidencia individual, múltiple y ambigua;
9. salida `pending_review` cuando OCR no está disponible;
10. MP4 válido verificado con FFprobe;
11. secuencias HTTP de Instagram Stories, Instagram Reels y Facebook Reels;
12. sanitización de tokens y errores;
13. reclamación exclusiva con dos trabajadores concurrentes;
14. reintento de un solo destino fallido;
15. limpieza segura de objetos temporales;
16. conservación de Telegram, feed, web y Salmos;
17. pruebas de workflow que demuestren ejecución oculta sin navegador.

Las pruebas automatizadas no publican contenido real.

## Despliegue gradual

1. Generar localmente las historias y el reel a partir de un portafolio fixture.
2. Revisar visualmente dimensiones, copy, fotografía original y legibilidad.
3. Ejecutar el flujo en `dry-run` con Supabase y transportes falsos.
4. Publicar una historia real controlada de un resultado verificado.
5. Confirmar su recibo y, cuando esté activado, el uso compartido a Facebook.
6. Publicar un reel real controlado en Instagram y Facebook.
7. Verificar los recibos y la ausencia de duplicados en un reintento.
8. Activar los disparadores automáticos en las dos PC.

## Criterios de aceptación

1. El pick público y el avance VIP se generan desde el lote exacto.
2. Ninguna fila premium se revela antes del evento.
3. El resumen final muestra las seis filas, no solo las ganadas.
4. La tarjeta de resultado y la fotografía original se publican como historias
   consecutivas cuando existe evidencia válida.
5. La fotografía conserva todo su contenido deportivo y el ID completo.
6. La ausencia o ambigüedad de fotografía no bloquea el resumen de datos.
7. El reel cumple el contrato MP4 y se publica en Instagram y Facebook.
8. Instagram Stories devuelve y persiste un ID remoto.
9. Facebook Stories se informa como crosspost confirmado o no verificado, nunca
   como éxito inventado.
10. Dos trabajadores no duplican ninguna pieza.
11. Un destino exitoso no se repite cuando otro destino falla.
12. No se abre ni controla el navegador durante producción.
13. Ningún secreto, dato personal u OCR completo aparece en logs o artefactos.
14. Telegram, web, scraper, feed, membresías, resultados y Salmos conservan su
   comportamiento.

## Fuera de alcance

- generación de video o imágenes mediante una API de IA;
- música comercial, narración sintética o clips de partidos;
- automatización visual de Meta Business Suite;
- publicación de historias en cuentas personales;
- mensajes directos, comentarios o anuncios pagados;
- cambios al algoritmo de selección, mercados, precios VIP o liquidación;
- ocultar el ID de ticket aprobado por el usuario;
- prometer alcance, monetización, aprobación de Meta o resultados deportivos.
