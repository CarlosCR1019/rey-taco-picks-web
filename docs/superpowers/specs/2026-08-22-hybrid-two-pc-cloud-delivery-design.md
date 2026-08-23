# Diseño híbrido: recolección en dos PCs y entrega desde GitHub Cloud

**Fecha:** 2026-08-22  
**Estado:** aprobado conceptualmente por Carlos; pendiente de revisión del documento escrito

## Objetivo

Operar Rey Taco Picks sin depender de IPs de datacenter para Playdoit. Una de
dos computadoras Windows 11 de confianza recolecta las líneas cuando está
encendida, mientras que GitHub Cloud ejecuta las tareas que no necesitan una IP
residencial: verificación de resultados, Telegram, Facebook e Instagram.

La automatización nunca apaga, suspende, reinicia ni cambia la configuración de
energía de ninguna computadora. Que una PC pueda apagarse después de terminar
significa únicamente que, si su usuario la apaga manualmente, los jobs cloud ya
iniciados no dependen de ella.

## Límites de seguridad

- `CarlosCR1019/rey-taco-picks` debe ser privado antes de registrar un runner.
- `CarlosCR1019/rey-taco-picks-web` continúa público y recibe únicamente el
  frontend estático revisado.
- Ningún workflow de `pull_request` puede alcanzar los runners personales.
- Los runners se registran a nivel repositorio con nombres únicos y las
  etiquetas `self-hosted`, `Windows`, `X64` y `playdoit-residential`.
- Los tokens de registro de GitHub no se guardan, no se reutilizan y se escriben
  únicamente en el instalador interactivo de cada PC.
- Los secretos de Supabase, Telegram y Meta permanecen en GitHub Actions. Los
  scripts de instalación y diagnóstico no los aceptan ni los escriben al disco.
- La cuenta de Windows, perfiles de Chrome, cookies y contraseñas personales no
  se usan para la recolección headless.

## Arquitectura

### 1. Workflow residencial de recolección

Un workflow `collector.yml` conserva los tres horarios de México y el despacho
manual. Su job primario se asigna a cualquier runner online con la etiqueta
`playdoit-residential`. Si el job termina con un fallo recuperable, un segundo
job con la misma etiqueta y la misma clave estable puede ser atendido por la
otra PC.

Ambos intentos usan:

```text
SCRAPER_RUN_KEY=residential:<github.run_id>
```

Supabase utiliza esa clave para impedir lotes duplicados. Los resultados sin
eventos o sin candidatos son salidas seguras y no disparan recuperación; los
fallos de infraestructura o fuente sí permiten un segundo intento acotado.

El CLI incorpora un modo `--collect-only`: recolecta, valida y persiste el lote,
pero no envía Telegram, Meta ni contenido web desde la PC. Este modo no recibe
los secretos de Telegram o Meta. La ausencia deliberada de entrega no se guarda
como error y no convierte una persistencia correcta en fallo de recolección.

### 2. Entrega social en GitHub Cloud

Después de los intentos de recolección —incluso si ambos fallan— un job
`deliver_cloud` con `always() && !cancelled()` en `ubuntu-latest` usa exactamente
la misma `SCRAPER_RUN_KEY`. Primero ejecuta el CLI en modo `--deliver-only`, que
puede reanudar únicamente un lote ya persistido y nunca abre Chrome ni intenta
recolectar. Después ejecuta el publicador Meta. El job:

1. consulta el lote persistido exacto;
2. no hace nada si no existe un lote elegible;
3. genera y valida captions e imagen;
4. publica Telegram según su ledger existente;
5. publica Facebook e Instagram con claims atómicos por destino;
6. registra inmediatamente recibos o errores sanitizados.

Si no existe un lote exacto, ambos comandos terminan de forma segura sin llamar
Telegram ni Meta. El job cloud no necesita que la PC siga encendida. No se
ejecuta en runners de pull requests y no recibe contenido privado distinto de
los secretos de Actions y la fila pública permitida por el RPC.

### 3. Verificación de resultados

La verificación permanece en `ubuntu-latest` porque no necesita Playdoit,
Chrome residencial ni una PC personal. Su horario y ejecución manual siguen
independientes del estado de los runners.

## Concurrencia, reintentos y cortes

- GitHub conserva una sola corrida de recolección por horario mediante un grupo
  de concurrencia estable.
- El recovery reutiliza la clave del primario.
- Antes de cada llamada a Meta, Supabase concede un claim temporal al destino.
  Otra PC o job no puede publicar ese destino mientras el claim esté vigente.
- Un éxito de Meta es terminal y un fallo tardío nunca lo sobrescribe.
- Si Meta acepta una publicación y el proceso muere antes de guardar el recibo,
  existe una ventana inevitable de entrega al-menos-una-vez. Se documenta y se
  revisa en el ledger; no se promete exactamente-una-vez.
- Si ambas PCs están apagadas, el collector queda en cola hasta que haya un
  runner disponible o hasta que GitHub lo cancele por sus límites. Los jobs
  cloud ya iniciados continúan sin ellas.

## Instalación en Windows 11

Cada PC tendrá tres scripts:

- `Test-ReyTacoRunnerHost.ps1`: diagnóstico de sólo lectura para Windows 11,
  x64, espacio, Chrome, Python, Git, HTTPS y suspensión en corriente alterna.
- `Install-ReyTacoRunner.ps1`: descarga exclusivamente el runner oficial,
  verifica SHA-256, solicita el token como `SecureString`, registra el nombre
  único y lo instala como servicio en `C:\actions-runner`.
- `Invoke-ReyTacoDryRun.ps1`: ejecuta el scraper sin persistencia, Telegram,
  Meta ni escritura de `frontend/public/picks.json` y elimina sus temporales.

El diagnóstico informa si la suspensión en corriente alterna no está en
`Never`, pero no modifica la configuración. El usuario decide cualquier cambio
de energía manualmente.

## Publicaciones y trabajo humano

El sistema puede producir como máximo una pieza social por corrida elegible.
Con los tres horarios actuales, eso equivale a entre cero y tres piezas únicas
al día, replicadas en Facebook e Instagram. Publicar la misma pieza en ambas
redes cuenta como dos entregas técnicas, pero como una sola pieza editorial.

La novia de Carlos no necesita publicar manualmente para que la operación
funcione. Para crecimiento puede complementar con historias, videos y respuestas
a comentarios, pero esas acciones no forman parte de la automatización ni se
requieren para mantener el scraper funcionando.

## Pruebas y activación

- Pruebas estáticas demuestran que sólo los jobs de recolección usan runners
  residenciales y que ningún evento de pull request los alcanza.
- Las pruebas de workflow comprueban la misma clave en primario, recuperación y
  entrega cloud, además de acciones fijadas por SHA y permisos mínimos.
- Los scripts PowerShell pasan el parser y contratos de no-secretos.
- Un dry-run separado se ejecuta en cada PC antes de habilitar el collector.
- Ninguna prueba offline llama Playdoit, Supabase de producción, Telegram, Meta
  ni el registro de runners.
- Se requiere aprobación inmediata antes de aplicar las migraciones de
  producción y otra aprobación antes de la primera publicación Meta real.
