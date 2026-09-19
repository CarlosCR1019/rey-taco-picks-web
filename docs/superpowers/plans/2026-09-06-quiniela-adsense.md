# Plan separado: Quiniela semanal y contenido apto para AdSense

Este plan no autoriza todavía implementación, migraciones, publicación ni
activación de anuncios. Se ejecutará después de estabilizar scraper, Mini App,
multimedia y regresiones.

## Fase A: cumplimiento y alcance

1. Confirmar jurisdicción, edad mínima, términos del premio y responsable de la
   promoción.
2. Definir `season_key`, `week_key`, cierre, eventos elegibles, fuente de
   resultados y política de correcciones.
3. Redactar autoría, método, fuentes, FAQ, privacidad, términos y juego
   responsable antes de abrir inscripciones.
4. Obtener revisión humana de las afirmaciones editoriales y publicitarias.

Salida: especificación aprobada, sin cambios en módulos de picks.

## Fase B: quiniela aislada

1. Diseñar tablas de convocatoria, entrada, pronóstico, resultado y entrega de
   premio con claves únicas e idempotencia.
2. Implementar validación server-side de una entrada por cuenta y cierre; no
   confiar en restricciones del navegador.
3. Implementar importación o captura de resultados con fuente, timestamp,
   revisión y auditoría.
4. Resolver ranking y desempates con una función determinista probada.
5. Entregar siete días VIP mediante una operación separada, reversible y
   registrada; nunca alterar un pick existente.
6. Probar abuso básico: duplicados, reintentos, entrada tardía, cambios de
   zona horaria, resultado corregido y usuario sin cuenta.

## Fase C: biblioteca editorial y AdSense

1. Inventariar contenido actual y retirar páginas finas, repetitivas o sin
   autoría.
2. Publicar un núcleo de artículos originales con fuentes, ejemplos y fecha de
   actualización.
3. Añadir navegación, sitemap, robots, contacto, privacidad, términos y
   declaración de juego responsable.
4. Mantener AdSense desactivado durante la revisión de calidad y configurar
   anuncios solo después de disponer de contenido suficiente.
5. Revisar que no existan incentivos a clics, tráfico artificial, claims de
   ganancias o anuncios que oculten la información.

## Criterios de aceptación

- La quiniela no importa ni modifica `backend/scraper.py`, selección,
  visibilidad, ledger de entregas, Telegram textual o historial.
- Los reintentos no duplican entradas ni premios.
- Los resultados muestran fuente y estado de revisión.
- Cada artículo tiene autoría, método, fuentes y valor independiente.
- No se activa AdSense hasta una revisión manual y no se usan métricas con PII.
- Las pruebas de regresión existentes permanecen verdes.

## Orden recomendado

Primero cumplimiento y contenido editorial; después el ledger de quiniela en un
módulo aislado; finalmente una revisión de AdSense. Ninguna de estas fases debe
bloquear la operación del scraper ni ser parte de su pipeline.
