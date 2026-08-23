[CmdletBinding()]
param(
    [string]$RunnerDirectory = "C:\actions-runner",
    [string]$TaskName = "Rey Taco Picks Interactive Runner"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$AdministratorPrincipal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $AdministratorPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $IsAdministrator) {
    throw "Abre PowerShell como administrador para registrar el inicio interactivo."
}

$Registration = Join-Path $RunnerDirectory ".runner"
$SourceLauncher = Join-Path $PSScriptRoot "Start-ReyTacoInteractiveRunner.ps1"
if (-not (Test-Path -LiteralPath $Registration)) {
    throw "Runner no registrado."
}
if (-not (Test-Path -LiteralPath $SourceLauncher)) {
    throw "Falta Start-ReyTacoInteractiveRunner.ps1 junto al registrador."
}

$UserAccount = (Get-CimInstance -ClassName Win32_ComputerSystem).UserName
if ([string]::IsNullOrWhiteSpace($UserAccount)) {
    throw "No hay una cuenta con sesion iniciada para registrar la tarea."
}

$AssetDirectory = Join-Path $RunnerDirectory "_rey-taco"
if (-not (Test-Path -LiteralPath $AssetDirectory)) {
    [void](New-Item -ItemType Directory -Path $AssetDirectory)
}
$InstalledLauncher = Join-Path $AssetDirectory "Start-ReyTacoInteractiveRunner.ps1"
Copy-Item -LiteralPath $SourceLauncher -Destination $InstalledLauncher -Force

$PowerShellPath = Join-Path $PSHOME "powershell.exe"
$ActionArguments = (
    '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden ' +
    '-ExecutionPolicy Bypass -File "{0}" -RunnerDirectory "{1}"' -f
    $InstalledLauncher, $RunnerDirectory
)
$Action = New-ScheduledTaskAction `
    -Execute $PowerShellPath `
    -Argument $ActionArguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserAccount
$Principal = New-ScheduledTaskPrincipal `
    -UserId $UserAccount `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

[void](Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Force)

Write-Output "RESULT=INTERACTIVE_STARTUP_REGISTERED TASK=$TaskName USER=$UserAccount"
