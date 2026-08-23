[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._-]{1,64}$')]
    [string]$RunnerName,

    [Parameter(Mandatory = $true)]
    [switch]$RepositoryIsPrivate,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$RunnerVersion,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string]$RunnerSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryUrl = "https://github.com/CarlosCR1019/rey-taco-picks"
$RunnerDirectory = "C:\actions-runner"
$DownloadUrl = (
    "https://github.com/actions/runner/releases/download/" +
    "v$RunnerVersion/actions-runner-win-x64-$RunnerVersion.zip"
)
$ArchivePath = Join-Path ([IO.Path]::GetTempPath()) (
    "rey-taco-actions-runner-$([Guid]::NewGuid().ToString('N')).zip"
)

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $IsAdministrator) {
    throw "Abre PowerShell como administrador para instalar el runner."
}
if (-not $RepositoryIsPrivate.IsPresent) {
    throw "Confirma el repositorio privado con -RepositoryIsPrivate."
}

if (Test-Path -LiteralPath (Join-Path $RunnerDirectory ".runner")) {
    throw "Ya existe un runner configurado en C:\actions-runner."
}
if (Test-Path -LiteralPath $RunnerDirectory) {
    $ExistingFiles = @(Get-ChildItem -LiteralPath $RunnerDirectory -Force)
    if ($ExistingFiles.Count -gt 0) {
        throw "C:\actions-runner existe y no esta vacio. No se sobrescribira."
    }
} else {
    [void](New-Item -ItemType Directory -Path $RunnerDirectory)
}

$TokenPointer = [IntPtr]::Zero
$PlainRegistrationToken = $null
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath -UseBasicParsing

    $ObservedHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
    if ($ObservedHash -ine $RunnerSha256) {
        throw "El SHA-256 del runner no coincide con el publicado por GitHub."
    }

    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $RunnerDirectory
    $RegistrationToken = Read-Host -AsSecureString `
        "Pega el token temporal de registro de GitHub"
    $TokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
        $RegistrationToken
    )
    $PlainRegistrationToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        $TokenPointer
    )
    if ([string]::IsNullOrWhiteSpace($PlainRegistrationToken)) {
        throw "El token temporal no puede estar vacio."
    }

    Push-Location $RunnerDirectory
    try {
        & .\config.cmd `
            --url $RepositoryUrl `
            --token $PlainRegistrationToken `
            --name $RunnerName `
            --labels "playdoit-residential" `
            --work "_work" `
            --unattended `
            --replace `
            --runasservice
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub no pudo registrar el runner."
        }
    } finally {
        Pop-Location
    }

    Start-Sleep -Seconds 2
    $RunnerServices = @(Get-Service -Name "actions.runner.*" -ErrorAction SilentlyContinue)
    if ($RunnerServices.Count -ne 1) {
        throw "No se encontro exactamente un servicio actions.runner.*."
    }
    if ($RunnerServices[0].Status -ne "Running") {
        Start-Service -InputObject $RunnerServices[0]
        $RunnerServices[0].WaitForStatus("Running", [TimeSpan]::FromSeconds(20))
    }

    Write-Output "RESULT=RUNNER_INSTALLED NAME=$RunnerName SERVICE=$($RunnerServices[0].Name)"
} finally {
    $PlainRegistrationToken = $null
    if ($TokenPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TokenPointer)
    }
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }
}
