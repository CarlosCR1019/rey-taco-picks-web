# Diseño separado: Quiniela semanal y contenido apto para AdSense

Estado: propuesta documental; no implementada en esta fase.

## Objetivo

Diseñar dos líneas independientes para crecer Rey Taco Picks sin conectarlas al
scraper, al ranking de picks, a la membresía ni a la publicación automática.

1. Una quiniela semanal promocional con premio de una semana VIP.
2. Una biblioteca editorial original que pueda presentarse a revisión de
   AdSense después de corregir contenido de bajo valor.

## Quiniela semanal

- Una entrada por cuenta autenticada y semana; el servidor impone el límite.
- Cierre en una hora fija publicada antes del primer evento elegible.
- El participante pronostica un conjunto acotado de resultados definidos en la
  convocatoria; no puede modificar su entrada después del cierre.
- La fuente de resultados será una fuente oficial o un proveedor documentado;
  cada jornada conservará fuente, hora de consulta y estado de revisión.
- Desempates publicados antes de abrir la convocatoria: mayor número de
  aciertos, después menor diferencia acumulada y finalmente marca de tiempo de
  la entrada. Si persiste el empate, se reparte o se sortea según los términos.
- El ledger debe usar una clave única `(season_key, week_key, user_id)` y una
  transacción idempotente para entradas, correcciones y entrega del premio.
- El premio es acceso VIP por siete días, sujeto a disponibilidad y términos;
  no se presenta como dinero ni como ganancia garantizada.
- La página debe incluir autoría, método, fuentes, límites, FAQ, resultados
  históricos, privacidad, términos y juego responsable.
- No se debe reutilizar el scraper para generar la quiniela ni cambiar la
  visibilidad, cuota, estado o entrega de ningún pick.

## Contenido editorial y AdSense

Antes de solicitar otra revisión, la biblioteca debe aportar valor verificable:

- artículos firmados con autor y fecha de actualización;
- método reproducible para interpretar cuotas y probabilidades implícitas;
- glosario, ejemplos propios, gestión de banca y juego responsable;
- fuentes enlazadas y diferenciación editorial frente a páginas de picks;
- páginas de contacto, privacidad, términos y política de publicidad;
- navegación interna clara, sin páginas vacías, repetitivas o creadas solo para
  colocar anuncios;
- anuncios únicamente en espacios que no oculten el contenido ni incentiven
  clics.

AdSense queda desactivado hasta una revisión humana de calidad y cumplimiento.
No se deben fabricar tráfico, impresiones, clics, testimonios o resultados.

## Decisiones pendientes

- Jurisdicción y revisión legal del premio.
- Fuente oficial y calendario de cada semana.
- Texto final de términos y política de privacidad.
- Responsable editorial y calendario mínimo de publicación.
- Métricas agregadas de lectura, no identificadores personales.
