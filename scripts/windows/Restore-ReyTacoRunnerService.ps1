[CmdletBinding()]
param(
    [string]$RunnerDirectory = "C:\actions-runner",
    [string]$TaskName = "Rey Taco Picks Interactive Runner"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    throw "Abre PowerShell como administrador para restaurar el servicio."
}

$Registration = Join-Path $RunnerDirectory ".runner"
$ServiceIdentity = Join-Path $RunnerDirectory ".service"
$ServiceBinary = Join-Path $RunnerDirectory "bin\RunnerService.exe"
if (-not (Test-Path -LiteralPath $Registration)) {
    throw "Runner no registrado; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $ServiceIdentity)) {
    throw "Falta .service; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $ServiceBinary)) {
    throw "Falta RunnerService.exe; no se cambiara nada."
}

$ServiceName = (Get-Content -LiteralPath $ServiceIdentity -Raw).Trim()
if ($ServiceName -notmatch '^actions\.runner\.[A-Za-z0-9._-]+$') {
    throw "El nombre guardado en .service no es valido; no se cambiara nada."
}
$DisplaySuffix = $ServiceName.Substring('actions.runner.'.Length)
$DisplayName = "GitHub Actions Runner ($DisplaySuffix)"

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$ExistingServices = @(
    Get-CimInstance -ClassName Win32_Service |
        Where-Object {
            $_.Name -like "actions.runner.*" -and
            $_.PathName -like "*$RunnerDirectory*"
        }
)
if ($ExistingServices.Count -eq 0) {
    & sc.exe create $ServiceName `
        binPath= "`"$ServiceBinary`"" `
        start= delayed-auto `
        obj= "NT AUTHORITY\NETWORK SERVICE" `
        DisplayName= $DisplayName
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo reinstalar el servicio del runner."
    }
} elseif ($ExistingServices.Count -ne 1 -or $ExistingServices[0].Name -ne $ServiceName) {
    throw "Se encontro un servicio inesperado para el runner."
}

& sc.exe config $ServiceName `
    binPath= "`"$ServiceBinary`"" `
    start= delayed-auto `
    obj= "NT AUTHORITY\NETWORK SERVICE" `
    DisplayName= $DisplayName
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo restaurar la configuracion del servicio."
}
& sc.exe failure $ServiceName `
    reset= 0 `
    actions= "restart/0/restart/60000/restart/60000"
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron restaurar las acciones de recuperacion."
}

$CurrentService = Get-Service -Name $ServiceName
if ($CurrentService.Status -ne "Running") {
    & sc.exe start $ServiceName
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo iniciar el servicio del runner."
    }
    $CurrentService.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
}

$RunnerServices = @(
    Get-CimInstance -ClassName Win32_Service |
        Where-Object {
            $_.Name -like "actions.runner.*" -and
            $_.PathName -like "*$RunnerDirectory*"
        }
)
if ($RunnerServices.Count -ne 1 -or $RunnerServices[0].State -ne "Running") {
    throw "El servicio del runner no quedo en ejecucion."
}

Write-Output "RESULT=RUNNER_SERVICE_RESTORED SERVICE=$($RunnerServices[0].Name)"
