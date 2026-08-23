[CmdletBinding()]
param(
    [string]$RunnerDirectory = "C:\actions-runner"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RunCommand = Join-Path $RunnerDirectory "run.cmd"
$Registration = Join-Path $RunnerDirectory ".runner"
if (-not (Test-Path -LiteralPath $Registration)) {
    throw "Runner no registrado."
}
if (-not (Test-Path -LiteralPath $RunCommand)) {
    throw "Falta run.cmd."
}

$env:REY_TACO_BROWSER_MODE = "interactive"
Push-Location -LiteralPath $RunnerDirectory
try {
    & $RunCommand
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
