# Operación de los dos recolectores Windows

El repositorio `CarlosCR1019/rey-taco-picks` debe permanecer **privado**. Cada
PC ejecuta el runner dentro de la sesión de Windows mediante la tarea programada
`Rey Taco Picks Interactive Runner`. Chrome se abre minimizado; el proceso no apaga,
reinicia, suspende ni cambia la energía de la computadora.

El runner funciona mientras la cuenta siga con sesión iniciada. La **pantalla bloqueada**
puede permanecer así después de iniciar el runner. Si la cuenta
cierra sesión o la PC se apaga, volverá a arrancar en el siguiente **inicio de
sesión natural**. El sistema no fuerza cierre de sesión, reinicio o encendido.

## Nombres y etiquetas obligatorias

- PC de Carlos: runner y etiqueta `rey-taco-carlos`.
- PC de respaldo: runner y etiqueta `rey-taco-respaldo`.
- Ambas: etiqueta `playdoit-residential`.

El instalador nuevo agrega las dos etiquetas automáticamente. Al convertir un
runner antiguo se conserva su registro; antes del workflow real, revisar en
**GitHub > Settings > Actions > Runners** que `rey-taco-carlos` también aparezca
como etiqueta personalizada. Sin esa etiqueta, GitHub no puede dirigir la
recuperación a la PC opuesta.

## Orden seguro por computadora

1. Ejecutar `Test-ReyTacoRunnerHost.ps1` y resolver cualquier `WARN`.
2. Ejecutar `Initialize-ReyTacoPythonToolcache.ps1` como administrador.
3. Instalar un runner nuevo o convertir el existente.
4. Iniciar manualmente la tarea `Rey Taco Picks Interactive Runner` con los
   comandos de la sección siguiente.
5. Ejecutar `Invoke-ReyTacoDryRun.ps1` y exigir `RESULT=DRY_RUN_SAFE`.
6. Confirmar en GitHub que el runner aparece `Idle`.
7. Pedir confirmación separada antes de ejecutar un workflow real.
8. Observar el arranque en el próximo inicio de sesión natural.
9. Repetir el mismo procedimiento en la PC de respaldo.

No se fuerza reinicio ni cierre de sesión para comprobar el paso 8.

## Tarea oculta y recuperación manual

`Rey Taco Picks Interactive Runner` es una tarea oculta intencionalmente para
mantener el runner y PowerShell en segundo plano. Por eso puede no aparecer en
la vista predeterminada del Programador de tareas. Para inspeccionarla o
iniciarla manualmente, abrir PowerShell como administrador y ejecutar:

```powershell
Get-ScheduledTask -TaskName "Rey Taco Picks Interactive Runner" |
    Select-Object TaskName, State
Start-ScheduledTask -TaskName "Rey Taco Picks Interactive Runner"
```

Después, confirmar que GitHub muestra el runner como `Idle`. No desocultar la
tarea ni cambiar su configuración sólo para usar la interfaz del Programador.

## Validación del host

Desde PowerShell, el siguiente comando encuentra el archivo sin conocer la
carpeta:

```powershell
$checker = Get-ChildItem -Path $env:USERPROFILE -Filter "Test-ReyTacoRunnerHost.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $checker) { throw "No se encontró Test-ReyTacoRunnerHost.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checker.FullName
```

`RESULT=READY` es ideal. `RESULT=READY_WITH_SETUP` enumera lo que falta sin
cambiar la PC.

## Preparar Python

Ejecutar una sola vez como administrador:

```powershell
$pythonSetup = Get-ChildItem -Path $env:USERPROFILE -Filter "Initialize-ReyTacoPythonToolcache.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $pythonSetup) { throw "No se encontró Initialize-ReyTacoPythonToolcache.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $pythonSetup.FullName
```

El resultado requerido es `RESULT=PYTHON_TOOLCACHE_READY`. El script instala la
versión fijada en `C:\actions-runner\_work\_tool` y valida su SHA-256.

## Convertir el runner existente de Carlos

No usar el instalador sobre `C:\actions-runner` si ya contiene `.runner`.
Abrir PowerShell como administrador y ejecutar:

```powershell
$migrator = Get-ChildItem -Path $env:USERPROFILE -Filter "Convert-ReyTacoRunnerToInteractive.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $migrator) { throw "No se encontró Convert-ReyTacoRunnerToInteractive.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $migrator.FullName
```

La conversión conserva `.runner`, `_work`, Python y los archivos del runner;
sólo sustituye el servicio por la tarea interactiva. El resultado requerido es
`RESULT=RUNNER_CONVERTED_INTERACTIVE`.

## Instalar el runner nuevo de respaldo

En el repositorio privado, abrir **Settings > Actions > Runners > New
self-hosted runner > Windows > x64** y generar un token temporal nuevo. No
enviarlo por WhatsApp ni guardarlo en archivos. Obtener de la versión oficial
del runner su número y SHA-256, y luego ejecutar como administrador:

```powershell
$runnerVersion = Read-Host "Versión oficial del runner"
$runnerSha256 = Read-Host "SHA-256 oficial del runner"
$installer = Get-ChildItem -Path $env:USERPROFILE -Filter "Install-ReyTacoRunner.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $installer) { throw "No se encontró Install-ReyTacoRunner.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer.FullName -RunnerName "rey-taco-respaldo" -RepositoryIsPrivate -RunnerVersion $runnerVersion -RunnerSha256 $runnerSha256
```

El token se pega sólo cuando PowerShell lo solicita. El resultado requerido es
`RESULT=RUNNER_INSTALLED_INTERACTIVE`.

## Prueba segura minimizada

La prueba busca el repositorio automáticamente, usa el Python fijado del runner
y ejecuta únicamente `--dry-run`. No escribe Supabase, Telegram, Facebook ni
Instagram:

```powershell
$probe = Get-ChildItem -Path $env:USERPROFILE -Filter "Invoke-ReyTacoDryRun.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $probe) { throw "No se encontró Invoke-ReyTacoDryRun.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe.FullName
```

Se requieren `browser_mode=interactive`, una fuente válida de Playdoit y
`RESULT=DRY_RUN_SAFE`. `source_blocked` o `source_invalid` hacen fallar la
prueba de forma segura.

## Recuperación entre PCs

El primer job puede usar cualquiera de las dos PCs disponibles. Si Playdoit
bloquea o entrega una fuente inválida, el segundo intento usa la **PC opuesta**.
Ambos intentos comparten la misma clave de lote para evitar duplicados. La PC de
respaldo no necesita estar encendida siempre, pero no habrá recuperación si está
apagada o sin sesión iniciada.

## Rollback al servicio anterior

Si la tarea interactiva falla, abrir PowerShell como administrador:

```powershell
$rollback = Get-ChildItem -Path $env:USERPROFILE -Filter "Restore-ReyTacoRunnerService.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $rollback) { throw "No se encontró Restore-ReyTacoRunnerService.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rollback.FullName
```

El rollback elimina sólo la tarea de Rey Taco y reinstala el servicio usando el
registro existente. No borra `C:\actions-runner`, el repositorio, `_work`,
Python, secretos ni archivos del usuario. El modo servicio vuelve a dejar el
runner disponible, aunque Playdoit puede bloquear su Chrome headless.
