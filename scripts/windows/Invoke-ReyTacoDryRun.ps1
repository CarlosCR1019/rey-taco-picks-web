[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RelativeScraper = "backend\scraper.py"
$DirectCandidates = @(
    (Join-Path $env:USERPROFILE "rey-taco-picks"),
    (Join-Path $env:USERPROFILE "Desktop\rey-taco-picks"),
    (Join-Path $env:USERPROFILE "Documents\rey-taco-picks"),
    (Join-Path $env:USERPROFILE "Downloads\rey-taco-picks"),
    (Join-Path $env:USERPROFILE "source\repos\rey-taco-picks"),
    (Join-Path $env:USERPROFILE ".gemini\antigravity\scratch\rey-taco-picks")
)
$SearchRoots = @(
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "Documents"),
    (Join-Path $env:USERPROFILE "Downloads"),
    (Join-Path $env:USERPROFILE "source"),
    (Join-Path $env:USERPROFILE ".gemini\antigravity\scratch")
) | Where-Object { Test-Path -LiteralPath $_ }

$Candidates = [System.Collections.Generic.List[IO.DirectoryInfo]]::new()
foreach ($CandidatePath in $DirectCandidates) {
    if (Test-Path -LiteralPath (Join-Path $CandidatePath $RelativeScraper)) {
        $Candidates.Add((Get-Item -LiteralPath $CandidatePath))
    }
}
if ($Candidates.Count -eq 0) {
    foreach ($SearchRoot in $SearchRoots) {
        Get-ChildItem -LiteralPath $SearchRoot -Directory -Filter "rey-taco-picks" `
            -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
                if (Test-Path -LiteralPath (Join-Path $_.FullName $RelativeScraper)) {
                    $Candidates.Add($_)
                }
            }
    }
}
if ($Candidates.Count -eq 0) {
    throw "No se encontro una carpeta extraida de rey-taco-picks."
}

$Repository = $Candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$ScraperPath = Join-Path $Repository.FullName $RelativeScraper
$PythonExecutable = "C:\actions-runner\_work\_tool\Python\3.11.9\x64\python.exe"
if (-not (Test-Path -LiteralPath $PythonExecutable)) {
    throw "No se encontro Python 3.11.9 en el tool cache del runner."
}

$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$TempDirectory = Join-Path $TempRoot (
    "rey-taco-dryrun-$([Guid]::NewGuid().ToString('N'))"
)
[void](New-Item -ItemType Directory -Path $TempDirectory)
$PreviousBrowserMode = $env:REY_TACO_BROWSER_MODE
$HadBrowserMode = Test-Path -LiteralPath Env:\REY_TACO_BROWSER_MODE

try {
    $env:REY_TACO_BROWSER_MODE = "interactive"
    Push-Location $Repository.FullName
    try {
        $Output = @(& $PythonExecutable $ScraperPath --dry-run 2>&1)
        $ScraperExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $OutputText = $Output -join [Environment]::NewLine
    if ($OutputText -notmatch "dry_run=true") {
        throw "El scraper no confirmo el modo seguro dry_run=true."
    }
    if ($OutputText -notmatch "browser_mode=interactive") {
        throw "Chrome no confirmo el modo interactivo minimizado."
    }
    if ($OutputText -match "source_error=(source_blocked|source_invalid)") {
        throw "Playdoit no entrego una fuente valida."
    }
    $UnsafeMarkers = @(
        "persistence=written",
        "telegram=sent",
        "meta=sent",
        "cookie",
        "token"
    )
    foreach ($Marker in $UnsafeMarkers) {
        if ($OutputText.IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "La prueba produjo un marcador inseguro: $Marker"
        }
    }
    if ($ScraperExitCode -notin @(0, 3, 4)) {
        throw "El dry-run termino con codigo inesperado $ScraperExitCode."
    }

    $Output | ForEach-Object { Write-Output $_ }
    Write-Output "RESULT=DRY_RUN_SAFE REPOSITORY=$($Repository.FullName)"
} finally {
    if ($HadBrowserMode) {
        $env:REY_TACO_BROWSER_MODE = $PreviousBrowserMode
    } else {
        Remove-Item -LiteralPath Env:\REY_TACO_BROWSER_MODE -ErrorAction SilentlyContinue
    }
    $ResolvedTemp = [IO.Path]::GetFullPath($TempDirectory)
    if (
        $ResolvedTemp.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $ResolvedTemp) -like "rey-taco-dryrun-*" -and
        (Test-Path -LiteralPath $ResolvedTemp)
    ) {
        Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
    }
}
