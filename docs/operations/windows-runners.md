# Operacion de los dos recolectores Windows

El repositorio fuente `CarlosCR1019/rey-taco-picks` debe permanecer **privado**.
El runner se instala como servicio de Windows y puede trabajar con la sesion
bloqueada; no necesita Chrome abierto ni una cuenta de Playdoit. La
automatizacion no apaga, reinicia, suspende ni cambia la configuracion de
energia de ninguna computadora.

## Requisitos por computadora

1. Windows 11 x64, Google Chrome, Git y Python 3.11 o superior.
2. Una copia extraida o clonada de `CarlosCR1019/rey-taco-picks`.
3. PowerShell abierto como administrador solamente durante la instalacion.
4. Cinco GB libres y acceso HTTPS a GitHub, su API y Playdoit.

Ejecutar primero, desde cualquier carpeta:

```powershell
$checker = Get-ChildItem -Path $env:USERPROFILE -Filter "Test-ReyTacoRunnerHost.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $checker) { throw "No se encontro Test-ReyTacoRunnerHost.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checker.FullName
```

`RESULT=READY` es ideal. `RESULT=READY_WITH_SETUP` enumera lo que se debe
instalar o ajustar manualmente; el script no cambia la PC.

## Obtener los valores oficiales

En GitHub abrir el repositorio privado y entrar a **Settings > Actions >
Runners > New self-hosted runner > Windows > x64**. Esa pantalla muestra la
version vigente, el SHA-256 oficial y un token de registro que dura poco tiempo.
Cada computadora necesita un token nuevo; nunca se reutiliza ni se envia por
WhatsApp.

En PowerShell se pueden capturar la version y el hash sin dejarlos fijos en el
archivo:

```powershell
$runnerVersion = Read-Host "Version oficial mostrada por GitHub"
$runnerSha256 = Read-Host "SHA-256 oficial mostrado por GitHub"
$installer = Get-ChildItem -Path $env:USERPROFILE -Filter "Install-ReyTacoRunner.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $installer) { throw "No se encontro Install-ReyTacoRunner.ps1" }
```

El instalador ejecuta `Initialize-ReyTacoPythonToolcache.ps1` antes de registrar
el servicio. Esa preparacion descarga Python 3.11.9 desde el repositorio oficial
`actions/python-versions`, valida su SHA-256 y completa el tool cache con la
sesion administrativa. El servicio cotidiano conserva la cuenta limitada
`NETWORK SERVICE`.

Si el runner ya estaba instalado antes de incorporar esta preparacion, ejecutarla
una sola vez desde PowerShell como administrador:

```powershell
$pythonSetup = Get-ChildItem -Path $env:USERPROFILE -Filter "Initialize-ReyTacoPythonToolcache.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $pythonSetup) { throw "No se encontro Initialize-ReyTacoPythonToolcache.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $pythonSetup.FullName
```

El resultado requerido es `RESULT=PYTHON_TOOLCACHE_READY`. No se debe cambiar
la cuenta del servicio a administrador.

## PC de Carlos

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer.FullName -RunnerName "rey-taco-carlos" -RepositoryIsPrivate -RunnerVersion $runnerVersion -RunnerSha256 $runnerSha256
```

Cuando lo solicite, pegar el token temporal directamente en PowerShell.

## PC de respaldo

Repetir la consulta de GitHub para generar **otro token** y ejecutar:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer.FullName -RunnerName "rey-taco-respaldo" -RepositoryIsPrivate -RunnerVersion $runnerVersion -RunnerSha256 $runnerSha256
```

GitHub debe mostrar los dos nombres en **Settings > Actions > Runners**. Al
menos uno debe aparecer `Idle` antes de probar el workflow.

## Prueba segura en cada PC

Este comando busca el repositorio sin pedir su direccion. Ignora el `.env`, no
escribe en Supabase, no envia Telegram o Meta y no cambia
`frontend/public/picks.json`:

```powershell
$probe = Get-ChildItem -Path $env:USERPROFILE -Filter "Invoke-ReyTacoDryRun.ps1" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $probe) { throw "No se encontro Invoke-ReyTacoDryRun.ps1" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe.FullName
```

Se requiere `RESULT=DRY_RUN_SAFE` en las dos computadoras antes de habilitar
los horarios. Una sola PC encendida e inactiva puede aceptar una corrida; si
ambas estan encendidas, GitHub asigna el job a una sola. El sistema no apaga la
PC al terminar.

## Retirar una computadora

Primero eliminar su runner en GitHub y obtener el token de eliminacion. Luego,
desde `C:\actions-runner`, ejecutar `config.cmd remove` con ese token. No borrar
la carpeta antes de desregistrar el servicio.
