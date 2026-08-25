# Cartelera por bloques y Muro de victorias

**Fecha:** 2026-08-25  
**Estado:** diseño aprobado  
**Zona horaria canónica:** Ciudad de México (`America/Mexico_City`)

## Objetivo

Evitar que la portada parezca vacía cuando ya terminaron sus selecciones, organizar la cartelera diaria en cuatro periodos fáciles de entender y reforzar la transparencia con las fotografías originales de boletos ganadores recibidas por el bot de Telegram.

La entrega mantiene la política comercial vigente: antes de comenzar los eventos solamente se revelan dos picks públicos por portafolio; una vez liquidados, todos los resultados pasan a ser públicos.

## Alcance aprobado

1. Dividir la cartelera del día en cuatro bloques visibles y apilados:
   - 00:00–05:59
   - 06:00–11:59
   - 12:00–17:59
   - 18:00–23:59
2. Destacar el bloque correspondiente a la hora actual en CDMX.
3. Mantener los picks liquidados en su bloque hasta las 23:59 del mismo día y conservarlos además en el historial público.
4. Cerrar los dos picks vigentes únicamente cuando exista evidencia final, y emitir un solo reporte final con el boleto original correspondiente.
5. Conservar la tabla “Los picks que recibió VIP” y añadir inmediatamente debajo un “Muro de victorias”.
6. Mostrar seis fotografías al inicio y revelar las demás en grupos de seis mediante “Cargar más victorias”.

## Fuera de alcance

- Integración con Gemini o con una API de generación de video.
- Cambiar la política de seis picks totales y dos picks públicos antes del evento.
- Crear cuatro portafolios independientes o exigir una PC encendida a las 05:00.
- Fabricar, reconstruir o editar el contenido de los boletos originales.
- Considerar ganado un pick sin evidencia final verificable.

## Diseño de la cartelera

### Estructura visual

La opción aprobada es **cuatro bloques apilados**. Todos permanecen visibles simultáneamente para que no haya información escondida detrás de pestañas.

Cada encabezado muestra:

- icono del periodo;
- intervalo horario CDMX;
- estado: `Cerrado`, `En curso`, `Próximo` o `Sin selección`;
- cantidad de picks o resultados disponibles.

El periodo actual usa el borde dorado de la marca. Los periodos pasados se muestran con menor contraste, pero siguen siendo legibles. Los futuros mantienen el estilo normal. Un bloque sin picks no desaparece: explica que no se publicó una selección solamente para llenar espacio.

### Asignación temporal

La fecha y hora del evento se obtienen de `fecha_evento` y `horario`, normalizadas como hora CDMX. Una función pura asigna cada fila al índice `0..3` mediante la hora entera:

- `0 <= hora < 6` → bloque 0;
- `6 <= hora < 12` → bloque 1;
- `12 <= hora < 18` → bloque 2;
- `18 <= hora < 24` → bloque 3.

Los datos inválidos no se colocan silenciosamente en un bloque. Se excluyen de la cartelera, continúan disponibles en el historial y producen un estado de diagnóstico controlado en desarrollo.

### Ciclo de vida y acceso

- Un pick `pendiente` y `public` aparece completo en su bloque.
- Un pick `pendiente` y `premium` no se expone al visitante anónimo. El bloque muestra un teaser agregado de picks VIP, sin evento, selección ni cuota.
- Un pick `ganado`, `perdido`, `void` o `revision_pendiente` ya no tiene valor prepartido y se vuelve público mediante el flujo de liquidación existente.
- Los picks liquidados del día permanecen en su bloque hasta medianoche CDMX.
- Al cambiar el día, dejan la cartelera y permanecen en la tabla histórica.
- Un usuario VIP autenticado puede ver sus picks pendientes completos dentro de los bloques correspondientes.

La portada consulta los picks públicos pendientes y liquidados de la fecha CDMX actual. La vista pública sigue siendo la frontera de seguridad: el navegador anónimo nunca consulta directamente filas premium.

### Recolección y cobertura

No se crean nuevos horarios de ejecución. La recolección ligera existente continúa cada 30 minutos y los escaneos completos siguen a las 08:00, 12:00, 16:00, 20:00 y 23:00 CDMX. El escaneo de las 23:00 utiliza el horizonte de 48 horas para cubrir el bloque de 06:00–11:59 de la mañana siguiente sin necesitar una PC a las 05:00.

Los cuatro bloques son una organización de presentación, no cuatro promesas de que siempre habrá un pick. El sistema puede dejar un bloque vacío si no encuentra una selección defendible.

## Cierre de los dos picks vigentes

El verificador conserva comportamiento de fallo seguro:

1. Consulta evidencia de resultado final para cada pick pendiente.
2. Si el evento no finalizó o las fuentes no coinciden, conserva `pendiente` o `revision_pendiente`; no adivina.
3. Cuando ambos picks estén liquidados, el sistema recompone el reporte diario completo.
4. Publica un solo cierre en los destinos configurados y registra los recibos idempotentes existentes.
5. Si existe un boleto original coincidente, adjunta esa fotografía sin recrearla ni cubrir su ID.
6. Una repetición del flujo detecta el recibo anterior y no duplica la publicación.

El cierre de resultados y la representación en bloques usan la misma fuente de verdad (`picks`). No se mantiene un segundo estado en el frontend.

## Muro de victorias

### Ubicación

Se conserva la tabla “Los picks que recibió VIP”. Inmediatamente debajo se agrega:

- kicker “Evidencia original”;
- título “Muro de victorias”;
- cuadrícula de imágenes;
- contador de evidencias;
- botón “Cargar más victorias”.

Esta composición mantiene dos formas complementarias de transparencia: el registro estructurado de todos los resultados y la evidencia visual original.

### Fuente de imágenes

El bot ya guarda cada foto administrativa en `frontend/public/tickets/ticket_<timestamp>.jpg` y agrega el nombre a `frontend/public/tickets/manifest.json`. También registra metadatos privados en `tickets_ganadores`, pero el frontend público no debe exponer `file_id`, `file_unique_id` ni `telegram_chat_id`.

La auditoría de diseño encontró **28 imágenes presentes y 28 entradas de manifiesto, sin archivos faltantes** al 2026-08-25. Por lo tanto, el muro puede construirse con la fuente existente y no requiere una migración de datos para su primera versión.

### Presentación y rendimiento

- Seis imágenes al cargar la página.
- “Cargar más victorias” agrega seis por interacción hasta agotar el manifiesto.
- Tres columnas en escritorio, dos en tableta y una en móvil.
- `loading="lazy"` y `decoding="async"` para no bloquear la portada.
- Cada miniatura abre la fotografía original en un visor accesible.
- El ID del boleto permanece visible porque aporta trazabilidad; no se imprime ningún identificador interno de Telegram.
- El orden es el del manifiesto, actualmente del más reciente al más antiguo.
- Si una imagen falla, aparece una tarjeta de evidencia no disponible sin romper el resto de la página.
- Si el manifiesto falla o está vacío, la tabla histórica continúa operativa y el muro muestra un mensaje neutral.

### Ingesta futura

Cuando el admin envía una nueva foto al bot:

1. el listener descarga el JPEG;
2. lo agrega al inicio del manifiesto si no existe;
3. registra sus metadatos privados en Supabase;
4. el siguiente despliegue/sincronización del repositorio incorpora la imagen a la web.

La primera versión no publica directamente un archivo local de una PC a producción sin pasar por el flujo de repositorio y despliegue existente.

## Manejo de errores

- Un error al cargar la cartelera no borra el historial ni el muro.
- Un error en el manifiesto no afecta picks, métricas ni resultados.
- Un error de una imagen individual no oculta las demás.
- Un error del verificador no produce un resultado o reporte falso.
- Estados vacíos distinguen entre “sin selección” y “no se pudieron consultar datos”.

## Accesibilidad y contenido

- Encabezados de bloque semánticos y estados anunciables.
- No depender únicamente del color para distinguir estados.
- Botones navegables por teclado y foco visible.
- Texto alternativo neutral para cada boleto, sin afirmar datos que no puedan extraerse del manifiesto.
- Conservación del aviso `18+` y de juego responsable.
- Nada de “ganancia garantizada”, “dinero seguro” ni afirmaciones de rentabilidad futura.

## Pruebas y aceptación

### Pruebas unitarias

- límites exactos de 00, 06, 12, 18 y 24 horas;
- fecha CDMX frente a UTC;
- orden cronológico dentro de cada bloque;
- bloque vacío visible;
- resultados del día conservados y resultados anteriores excluidos de la cartelera;
- visitante anónimo sin detalles premium;
- seis imágenes iniciales y paginación de seis;
- manifiesto vacío, inválido e imagen individual fallida;
- visor accesible y cierre por teclado.

### Pruebas de integración

- Supabase devuelve dos pendientes públicos y todos los liquidados del día;
- VIP autenticado recibe sus pendientes completos sin cambiar la vista anónima;
- el historial conserva todos los estados;
- las 28 imágenes actuales son alcanzables desde el manifiesto;
- el reporte final se publica una vez y una repetición no duplica recibos.

### Criterios de aceptación visual

- Los cuatro periodos son visibles sin cambiar de pestaña.
- El periodo actual se reconoce inmediatamente.
- Un periodo pasado conserva sus resultados hasta medianoche.
- En móvil no hay desplazamiento horizontal en la cartelera o el muro.
- La tabla histórica permanece intacta.
- El muro aparece debajo de la tabla y muestra fotografías originales, no recreaciones.

## Orden de implementación

1. Pruebas y funciones puras de fecha/bloques.
2. Consulta diaria y render de los cuatro bloques.
3. Estados, acceso anónimo/VIP y estilos responsive.
4. Pruebas y cargador seguro del manifiesto.
5. Muro, carga progresiva y visor.
6. Verificación real de los dos picks, reporte único y boleto original.
7. Suite completa, build y validación visual local/producción.
