[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PythonVersion = "3.11.9"
$ExpectedSha256 = "C92A530D9AC9539FEEA075BB033E7E03580412999D2E2833B7B62D948DA60D03"
$ToolDirectory = "C:\actions-runner\_work\_tool"
$PythonDirectory = Join-Path $ToolDirectory "Python\$PythonVersion\x64"
$CompleteMarker = Join-Path $ToolDirectory "Python\$PythonVersion\x64.complete"
$PythonExecutable = Join-Path $PythonDirectory "python.exe"
$DownloadUrl = "https://github.com/actions/python-versions/releases/download/3.11.9-9947079978/python-3.11.9-win32-x64.zip"

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $IsAdministrator) {
    throw "Abre PowerShell como administrador para preparar Python 3.11."
}

if (
    (Test-Path -LiteralPath $CompleteMarker) -and
    (Test-Path -LiteralPath $PythonExecutable)
) {
    & $PythonExecutable --version
    if ($LASTEXITCODE -ne 0) {
        throw "El Python 3.11 del tool cache no responde."
    }
    Write-Output "RESULT=PYTHON_TOOLCACHE_READY STATUS=EXISTING VERSION=$PythonVersion"
    exit 0
}

$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$TempDirectory = Join-Path $TempRoot (
    "rey-taco-python-toolcache-$([Guid]::NewGuid().ToString('N'))"
)
$ArchivePath = Join-Path $TempDirectory "python-$PythonVersion-win32-x64.zip"
$ExtractDirectory = Join-Path $TempDirectory "unpacked"
$PreviousToolDirectory = $env:AGENT_TOOLSDIRECTORY

try {
    [void](New-Item -ItemType Directory -Path $TempDirectory)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath -UseBasicParsing

    $ObservedHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
    if ($ObservedHash -ine $ExpectedSha256) {
        throw "El SHA-256 del paquete oficial de Python no coincide."
    }

    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractDirectory
    $SetupPath = Join-Path $ExtractDirectory "setup.ps1"
    if (-not (Test-Path -LiteralPath $SetupPath)) {
        throw "El paquete oficial no contiene setup.ps1."
    }

    $env:AGENT_TOOLSDIRECTORY = $ToolDirectory
    & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $SetupPath
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo preparar Python 3.11 en el tool cache."
    }

    if (
        -not (Test-Path -LiteralPath $CompleteMarker) -or
        -not (Test-Path -LiteralPath $PythonExecutable)
    ) {
        throw "La instalación de Python terminó sin x64.complete o python.exe."
    }
    & $PythonExecutable --version
    if ($LASTEXITCODE -ne 0) {
        throw "El Python 3.11 instalado no responde."
    }

    Write-Output "RESULT=PYTHON_TOOLCACHE_READY STATUS=INSTALLED VERSION=$PythonVersion"
} finally {
    if ($null -eq $PreviousToolDirectory) {
        Remove-Item Env:AGENT_TOOLSDIRECTORY -ErrorAction SilentlyContinue
    } else {
        $env:AGENT_TOOLSDIRECTORY = $PreviousToolDirectory
    }

    $ResolvedTemp = [IO.Path]::GetFullPath($TempDirectory)
    $SafePrefix = $TempRoot.TrimEnd('\') + '\'
    $SafeLeaf = Split-Path -Leaf $ResolvedTemp
    if (
        (Test-Path -LiteralPath $ResolvedTemp) -and
        $ResolvedTemp.StartsWith($SafePrefix, [StringComparison]::OrdinalIgnoreCase) -and
        $SafeLeaf.StartsWith(
            "rey-taco-python-toolcache-",
            [StringComparison]::Ordinal
        )
    ) {
        Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
    }
}
