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
$ServiceIdentity = Join-Path $RunnerDirectory ".service"
$ServiceBinary = Join-Path $RunnerDirectory "bin\RunnerService.exe"
$Registrar = Join-Path $PSScriptRoot "Register-ReyTacoInteractiveStartup.ps1"
$Rollback = Join-Path $PSScriptRoot "Restore-ReyTacoRunnerService.ps1"
if (-not (Test-Path -LiteralPath $Registration)) {
    throw "Runner no registrado; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $ServiceIdentity)) {
    throw "Falta .service; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $ServiceBinary)) {
    throw "Falta RunnerService.exe; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $Registrar)) {
    throw "Falta el registrador interactivo; no se cambiara nada."
}
if (-not (Test-Path -LiteralPath $Rollback)) {
    throw "Falta el rollback del servicio; no se cambiara nada."
}

$ExpectedServiceName = (Get-Content -LiteralPath $ServiceIdentity -Raw).Trim()
if ($ExpectedServiceName -notmatch '^actions\.runner\.[A-Za-z0-9._-]+$') {
    throw "El nombre guardado en .service no es valido; no se cambiara nada."
}

$RunnerServices = @(Get-MatchingRunnerServices -ExpectedDirectory $RunnerDirectory)
if ($RunnerServices.Count -ne 1) {
    throw "Se requiere exactamente un servicio del runner en C:\actions-runner."
}
$ServiceName = $RunnerServices[0].Name
if ($ServiceName -cne $ExpectedServiceName) {
    throw "El servicio encontrado no coincide con .service; no se cambiara nada."
}
if ($RunnerServices[0].StartName -ine 'NT AUTHORITY\NETWORK SERVICE') {
    throw "La cuenta del servicio no es NETWORK SERVICE; no se cambiara nada."
}
$Service = Get-Service -Name $ServiceName
if ($Service.Status -ne "Stopped") {
    Stop-Service -InputObject $Service
    $Service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
}

try {
    & sc.exe delete $ServiceName
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo eliminar el registro del servicio del runner."
    }
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        $RemainingService = Get-CimInstance -ClassName Win32_Service |
            Where-Object { $_.Name -eq $ServiceName }
        if ($null -eq $RemainingService) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if ($null -ne (Get-CimInstance -ClassName Win32_Service |
        Where-Object { $_.Name -eq $ServiceName })) {
        throw "Windows no termino de eliminar el servicio del runner."
    }

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
    try {
        & $Rollback -RunnerDirectory $RunnerDirectory -TaskName $TaskName
    } catch {
        throw "La conversion fallo y el rollback automatico tambien fallo."
    }
    throw "La conversion fallo y el servicio original fue restaurado."
}

Write-Output "RESULT=RUNNER_CONVERTED_INTERACTIVE TASK=$TaskName SERVICE_REMOVED=$ServiceName"
