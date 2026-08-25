[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("BLOCKER", "SETUP")][string]$Class,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [Parameter(Mandatory = $true)][string]$Detail
    )

    $Checks.Add([pscustomobject]@{
        Name = $Name
        Class = $Class
        Passed = $Passed
        Detail = $Detail
    })
}

try {
    $OperatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
    $IsWindows11 = $OperatingSystem.Caption -match "Windows 11"
    $Is64Bit = $OperatingSystem.OSArchitecture -match "64"
    Add-Check -Name "windows_11_64_bit" -Class "BLOCKER" `
        -Passed ($IsWindows11 -and $Is64Bit) `
        -Detail "$($OperatingSystem.Caption); $($OperatingSystem.OSArchitecture)"
} catch {
    Add-Check -Name "windows_11_64_bit" -Class "BLOCKER" -Passed $false `
        -Detail "No se pudo consultar Win32_OperatingSystem"
}

$IsX64 = $env:PROCESSOR_ARCHITECTURE -eq "AMD64"
Add-Check -Name "processor_x64" -Class "BLOCKER" -Passed $IsX64 `
    -Detail "Arquitectura: $($env:PROCESSOR_ARCHITECTURE)"

try {
    $FreeBytes = (Get-PSDrive -Name C).Free
    $FreeGiB = [math]::Round($FreeBytes / 1GB, 1)
    Add-Check -Name "disk_5gb" -Class "BLOCKER" -Passed ($FreeBytes -ge 5GB) `
        -Detail "Espacio libre en C: $FreeGiB GB"
} catch {
    Add-Check -Name "disk_5gb" -Class "BLOCKER" -Passed $false `
        -Detail "No se pudo consultar el espacio de C:"
}

foreach ($HostName in @("github.com", "api.github.com", "www.playdoit.mx")) {
    try {
        $Reachable = Test-NetConnection -ComputerName $HostName -Port 443 `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        Add-Check -Name "https_$($HostName.Replace('.', '_'))" -Class "BLOCKER" `
            -Passed ([bool]$Reachable) -Detail "HTTPS 443 hacia $HostName"
    } catch {
        Add-Check -Name "https_$($HostName.Replace('.', '_'))" -Class "BLOCKER" `
            -Passed $false -Detail "Sin conexión HTTPS 443 hacia $HostName"
    }
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
Add-Check -Name "administrator_session" -Class "SETUP" `
    -Passed $IsAdministrator `
    -Detail $(if ($IsAdministrator) {
        "PowerShell tiene permisos de administrador"
    } else {
        "Abrir PowerShell como administrador durante la instalación"
    })

$ChromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$ChromeCommand = Get-Command -Name "chrome.exe" -ErrorAction SilentlyContinue
$HasChrome = @($ChromeCandidates).Count -gt 0 -or $null -ne $ChromeCommand
Add-Check -Name "google_chrome" -Class "SETUP" -Passed $HasChrome `
    -Detail $(if ($HasChrome) { "Google Chrome encontrado" } else {
        "Instalar Google Chrome estable"
    })

$GitCommand = Get-Command -Name "git" -ErrorAction SilentlyContinue
Add-Check -Name "git" -Class "SETUP" -Passed ($null -ne $GitCommand) `
    -Detail $(if ($null -ne $GitCommand) { "Git encontrado" } else {
        "Instalar Git para Windows"
    })

$PythonLauncher = Get-Command -Name "py" -ErrorAction SilentlyContinue
$HasPython311 = $false
if ($null -ne $PythonLauncher) {
    & $PythonLauncher.Source -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" `
        2>$null
    $HasPython311 = $LASTEXITCODE -eq 0
}
Add-Check -Name "python_3_11" -Class "SETUP" -Passed $HasPython311 `
    -Detail $(if ($HasPython311) { "Python 3.11 o superior encontrado" } else {
        "Instalar Python 3.11 x64"
    })

$FfmpegCommand = Get-Command -Name "ffmpeg" -ErrorAction SilentlyContinue
Add-Check -Name "ffmpeg" -Class "SETUP" -Passed ($null -ne $FfmpegCommand) `
    -Detail $(if ($null -ne $FfmpegCommand) { "FFmpeg encontrado" } else {
        "Instalar FFmpeg y agregarlo al PATH"
    })

$FfprobeCommand = Get-Command -Name "ffprobe" -ErrorAction SilentlyContinue
Add-Check -Name "ffprobe" -Class "SETUP" -Passed ($null -ne $FfprobeCommand) `
    -Detail $(if ($null -ne $FfprobeCommand) { "FFprobe encontrado" } else {
        "Instalar FFprobe y agregarlo al PATH"
    })

$TesseractCommand = Get-Command -Name "tesseract" -ErrorAction SilentlyContinue
Add-Check -Name "tesseract" -Class "SETUP" -Passed ($null -ne $TesseractCommand) `
    -Detail $(if ($null -ne $TesseractCommand) { "Tesseract encontrado" } else {
        "Instalar Tesseract OCR y agregarlo al PATH"
    })

$NeverSleepOnAC = $false
try {
    $SleepQuery = powercfg.exe /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
    $AcLines = @($SleepQuery | Where-Object {
        ($_ -match "AC" -or $_ -match "CA") -and $_ -match "0x[0-9a-fA-F]{8}"
    })
    $NeverSleepOnAC = $AcLines.Count -gt 0 -and (
        $AcLines -join "`n"
    ) -match "0x00000000"
} catch {
    $NeverSleepOnAC = $false
}
Add-Check -Name "no_sleep_on_ac" -Class "SETUP" -Passed $NeverSleepOnAC `
    -Detail $(if ($NeverSleepOnAC) { "Suspensión en corriente: Nunca" } else {
        "Configurar suspensión en corriente como Nunca"
    })

$BlockingFailures = @($Checks | Where-Object {
    $_.Class -eq "BLOCKER" -and -not $_.Passed
})
$SetupFailures = @($Checks | Where-Object {
    $_.Class -eq "SETUP" -and -not $_.Passed
})

foreach ($Check in $Checks) {
    $Status = if ($Check.Passed) { "PASS" } elseif ($Check.Class -eq "SETUP") {
        "WARN"
    } else {
        "FAIL"
    }
    Write-Output "CHECK=$($Check.Name) STATUS=$Status DETAIL=$($Check.Detail)"
}

if ($BlockingFailures.Count -gt 0) {
    $Verdict = "NOT_READY"
    $ExitCode = 2
} elseif ($SetupFailures.Count -gt 0) {
    $Verdict = "READY_WITH_SETUP"
    $ExitCode = 0
} else {
    $Verdict = "READY"
    $ExitCode = 0
}

Write-Output "RESULT=$Verdict"
exit $ExitCode
