[CmdletBinding()]
param(
    [string]$RunnerDirectory = "C:\actions-runner",
    [string]$TaskName = "Rey Taco Picks Interactive Runner"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
    if (-not $Principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        throw "Abre PowerShell como administrador para convertir el runner."
    }
}

function Get-MatchingRunnerServices {
    param([string]$ExpectedDirectory)

    $ResolvedDirectory = [IO.Path]::GetFullPath($ExpectedDirectory).TrimEnd('\')
    return @(
        Get-CimInstance -ClassName Win32_Service |
            Where-Object {
                $_.Name -like "actions.runner.*" -and
                $_.PathName -like "*$ResolvedDirectory*"
            }
    )
}

Assert-Administrator
$Registration = Join-Path $RunnerDirectory ".runner"
$ServiceCommand = Join-Path $RunnerDirectory "svc.cmd"
$Registrar = Join-Path $PSScriptRoot "Register-ReyTacoInteractiveStartup.ps1"
if (-not (Test-Path -LiteralPath $Registration)) {
    throw "Runner no registrado; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $ServiceCommand)) {
    throw "Falta svc.cmd; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $Registrar)) {
    throw "Falta el registrador interactivo; no se cambiara nada."
}

$RunnerServices = @(Get-MatchingRunnerServices -ExpectedDirectory $RunnerDirectory)
if ($RunnerServices.Count -ne 1) {
    throw "Se requiere exactamente un servicio del runner en C:\actions-runner."
}
$ServiceName = $RunnerServices[0].Name
$Service = Get-Service -Name $ServiceName
if ($Service.Status -ne "Stopped") {
    Stop-Service -InputObject $Service
    $Service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
}

Push-Location -LiteralPath $RunnerDirectory
try {
    & .\svc.cmd uninstall
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo desinstalar el servicio del runner."
    }
} finally {
    Pop-Location
}

try {
    & powershell.exe -NoLogo -NoProfile -NonInteractive `
        -ExecutionPolicy Bypass -File $Registrar `
        -RunnerDirectory $RunnerDirectory -TaskName $TaskName
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo registrar la tarea interactiva."
    }

    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 5
    $Task = Get-ScheduledTask -TaskName $TaskName
    $RunnerProcesses = @(
        Get-CimInstance -ClassName Win32_Process |
            Where-Object {
                $_.Name -eq "Runner.Listener.exe" -and
                $_.ExecutablePath -like "*$RunnerDirectory*"
            }
    )
    if ($Task.State -ne "Running" -and $RunnerProcesses.Count -eq 0) {
        throw "La tarea interactiva no quedo ejecutandose."
    }
} catch {
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $ExistingTask) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Push-Location -LiteralPath $RunnerDirectory
    try {
        & .\svc.cmd install
        if ($LASTEXITCODE -eq 0) {
            & .\svc.cmd start
        }
    } finally {
        Pop-Location
    }
    throw "La conversion fallo y se intento restaurar el servicio original."
}

Write-Output "RESULT=RUNNER_CONVERTED_INTERACTIVE TASK=$TaskName SERVICE_REMOVED=$ServiceName"
