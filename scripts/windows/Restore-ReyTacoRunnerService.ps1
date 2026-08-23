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
$ServiceCommand = Join-Path $RunnerDirectory "svc.cmd"
if (-not (Test-Path -LiteralPath $Registration)) {
    throw "Runner no registrado; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $ServiceCommand)) {
    throw "Falta svc.cmd; no se cambiara nada."
}

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Push-Location -LiteralPath $RunnerDirectory
try {
    $ExistingServices = @(
        Get-CimInstance -ClassName Win32_Service |
            Where-Object {
                $_.Name -like "actions.runner.*" -and
                $_.PathName -like "*$RunnerDirectory*"
            }
    )
    if ($ExistingServices.Count -eq 0) {
        & .\svc.cmd install
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo reinstalar el servicio del runner."
        }
    } elseif ($ExistingServices.Count -ne 1) {
        throw "Se encontro mas de un servicio para el runner."
    }

    & .\svc.cmd start
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo iniciar el servicio del runner."
    }
} finally {
    Pop-Location
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
