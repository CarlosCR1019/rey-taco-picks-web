# Rey Taco Picks: diseño editorial, distribución y web en vivo

Fecha: 24 de agosto de 2026
Estado: aprobado visualmente; pendiente de revisión escrita e implementación

## Objetivo

Convertir la salida técnica ya funcional del scraper en una experiencia editorial
atractiva, verificable y distinta para cada audiencia, sin duplicar publicaciones
ni inventar probabilidades, resultados, valor esperado o ganancias.

El flujo debe cubrir cuatro superficies:

1. Telegram VIP con las seis selecciones completas antes de los eventos.
2. Telegram free con dos selecciones públicas antes de los eventos.
3. Facebook e Instagram con una selección pública y copy editorial de marca.
4. La web con dos picks públicos activos, acceso VIP y el historial completo.

Después de los eventos, los resultados verificados de las seis selecciones dejan
de ser información premium anticipada y pueden mostrarse en free, VIP, Meta y web
como evidencia transparente del desempeño.

## Decisiones aprobadas

### Voz editorial

Se usará la opción **Premium equilibrado**:

- jerarquía clara, identidad de la corona y emojis medidos;
- tono cercano y comercial, sin verse como una ficha técnica;
- hechos auditables por encima de frases de certeza;
- lenguaje en español para México;
- avisos breves de momios variables, 18+ y juego responsable.

No se publicarán expresiones como “pick seguro”, “ganancia garantizada”, “IA no
falla”, “profit masivo” o “+EV” si el dato no fue calculado y persistido por un
proceso auditable.

### Distribución antes del evento

| Destino | Contenido | Cantidad |
| --- | --- | ---: |
| Telegram admin | Auditoría operativa completa | 6 |
| Telegram VIP | Cartelera editorial completa | 6 |
| Telegram free | Cartelera pública con CTA a VIP | 2 |
| Facebook | Pick público destacado | 1 |
| Instagram | Pick público destacado | 1 |
| Web pública | Tarjetas públicas activas | 2 |
| Web VIP autenticada | Portafolio completo | 6 |

La visibilidad persistida en Supabase es autoritativa. Telegram free, Meta y la
web pública nunca pueden promover una fila `premium` antes de que el evento sea
liquidado.

### Telegram VIP

El mensaje se construirá como una cartelera única y no como seis bloques técnicos.

Estructura:

1. encabezado `CARTELERA VIP DEL REY`, fecha y zona CDMX;
2. cantidad total de selecciones;
3. pick principal destacado;
4. lista compacta de las otras cinco selecciones con evento, mercado, momio y
   horario;
5. respaldo de datos únicamente con la etiqueta aprobada, sin tratarlo como
   probabilidad de ganar;
6. enlace a la web y aviso responsable.

Si el texto supera el límite de Telegram, se divide por secciones completas con
encabezado y pie repetidos; nunca se corta una selección por la mitad.

### Telegram free

El mensaje mantiene la misma identidad Premium equilibrada, pero solo contiene
las dos filas `public`:

1. encabezado `2 PICKS PÚBLICOS DEL REY`;
2. las dos selecciones completas;
3. indicación factual de que la cartelera VIP contiene cuatro selecciones
   adicionales;
4. CTA al acceso VIP y a `reytacopicks.com`;
5. aviso responsable.

`TELEGRAM_FREE_CHANNEL_ID` será un destino obligatorio para una publicación real.
Su ausencia debe registrarse como `not_configured`; no puede reinterpretarse el
canal VIP como free ni marcarse la entrega free como exitosa.

### Facebook e Instagram

Se conserva el arte actual aprobado de `PICK PÚBLICO DEL DÍA`. La corrección se
concentra en el copy.

El copy tendrá:

1. gancho corto de marca;
2. evento, selección, mercado, horario y momio observado;
3. una explicación editorial basada solo en datos persistidos disponibles;
4. CTA a la web y, cuando corresponda, a VIP;
5. aviso 18+ y hashtags limitados por plataforma.

Facebook podrá usar un texto un poco más narrativo. Instagram será más escaneable,
con párrafos cortos y hasta cuatro hashtags aprobados. Ambos deben conservar los
hechos protegidos y rechazar cualquier dato numérico o afirmación no presente en
la entrada auditada.

El proveedor de IA es opcional. Si falla o produce una afirmación prohibida, el
fallback determinista también debe ser editorialmente atractivo; nunca debe
regresar a la ficha plana `Evento / Selección / Momio / Observado`.

## Reportes de resultados

Habrá dos momentos:

1. **Reporte vespertino:** incluye solamente selecciones ya verificadas. Distingue
   ganadas, perdidas, void y pendientes; no presenta un récord definitivo.
2. **Cierre final:** se emite una sola vez cuando las seis filas del portafolio se
   encuentran en estado terminal. Si el cierre no ocurre en la noche, el siguiente
   verificador de la mañana puede emitirlo.

El verificador seguirá ejecutándose en GitHub-hosted runners, por lo que no depende
de que alguna PC residencial esté encendida. Se conservarán las verificaciones de
07:00 y 13:00 CDMX y se agregarán ventanas vespertina y nocturna.

Los reportes se entregarán a admin, VIP y free. Una vez terminados los eventos,
free puede ver las seis selecciones y sus resultados. Meta puede publicar el cierre
final; el reporte vespertino no se publica automáticamente en Meta para evitar
saturación.

La web muestra todas las filas verificadas del portafolio, incluidas las cuatro que
fueron premium antes del evento. Si una jornada termina 6–0, aparecen las seis filas
ganadas; cuando existan pérdidas, void o revisiones también se muestran. No habrá
selección favorable de resultados.

Cada reporte necesita una clave idempotente por portafolio, tipo de reporte y
destino. Un reintento puede completar destinos fallidos sin volver a enviar los que
ya tienen recibo exitoso.

## Web en vivo

### Causa confirmada del estado vacío

La vista anónima `public_picks` de Supabase responde correctamente y contiene las
dos filas públicas pendientes y el historial. La compilación desplegada no contiene
`VITE_SUPABASE_URL` ni `VITE_SUPABASE_ANON_KEY`, por lo que el frontend cae al
archivo estático `/picks.json`, actualmente `[]`.

### Solución aprobada

Render recibirá en build:

- `VITE_SUPABASE_URL`;
- `VITE_SUPABASE_ANON_KEY`.

La clave anónima es pública por diseño. La protección de información premium
permanece en RLS, vistas y RPC de Supabase; nunca se entrega la service-role key al
frontend.

El archivo `/picks.json` se conserva solo como fallback de indisponibilidad. No es
la fuente primaria ni requiere commits automáticos por cada corrida.

### Presentación aprobada

La interfaz conserva la gama crema, vino, dorado y azul oscuro:

- dos tarjetas públicas con liga, horario, evento, selección, momio y respaldo;
- bloque de conversión que comunica cuatro picks adicionales en VIP;
- historial `Los 6 picks que recibió VIP` después del cierre;
- las seis filas completas de la jornada, no un resumen recortado;
- filtros para todos, ganados y perdidos;
- estados void y revisión visibles cuando correspondan;
- aviso de resultados verificados y juego responsable.

En pantallas pequeñas, las dos tarjetas pasan a una columna y la tabla de historial
usa filas apiladas o desplazamiento horizontal controlado sin perder etiquetas.

## Modelo de datos y seguridad

- Supabase es la fuente autoritativa para picks, visibilidad y resultados.
- Solo filas `public` pueden salir antes del evento por free, Meta y web pública.
- Una fila premium solo se vuelve pública como historial cuando está en estado
  terminal.
- El resultado mostrado requiere `resultado_fuente`, `resultado_evento_id`,
  `resultado_marcador` y `resultado_verificado_at` válidos.
- Los textos públicos nunca incluyen razonamiento premium confidencial.
- Los logs registran destino, tipo de reporte, estado y recibo; no registran tokens.

## Manejo de fallos

- La falla de un destino no bloquea los demás.
- Un destino sin configuración queda explícitamente `not_configured`.
- Si Supabase falla en la web, se usa el fallback estático sin mostrar datos premium.
- Si no existe evidencia suficiente para liquidar un pick, permanece
  `revision_pendiente` y se presenta así; no se fuerza ganado o perdido.
- Si el copy de IA falla validación, se utiliza el fallback editorial determinista.
- Los reintentos respetan el ledger y no duplican Telegram ni Meta.

## Validación y pruebas de aceptación

1. Un lote de seis con dos públicas produce 6/2/1/1/2 filas para VIP, free,
   Facebook, Instagram y web pública respectivamente.
2. Free no recibe ninguna fila premium antes del inicio.
3. VIP recibe una cartelera editorial, no seis fichas `Evento:`.
4. Los captions de Meta son atractivos, factuales y distintos por plataforma.
5. La imagen social existente no cambia.
6. El reporte vespertino solo cuenta resultados verificados hasta ese momento.
7. El cierre final se emite una sola vez al quedar seis filas terminales.
8. Free y la web ven las seis filas después del cierre, incluidos resultados no
   ganadores cuando existan.
9. La compilación de producción contiene la configuración pública de Supabase y la
   web deja de depender de `picks.json` vacío.
10. La service-role key nunca aparece en artefactos del frontend.
11. Reintentar una entrega no duplica publicaciones exitosas.
12. La vista móvil conserva lectura, CTA y etiquetas de la tabla.

## Fuera de alcance inmediato

- Reels e historias automáticos.
- Rediseño de la imagen social aprobada.
- Cambio de precio o proceso de cobro VIP.
- Afirmaciones de rentabilidad o valor esperado sin un modelo auditado específico.
