param(
    [switch]$SkipFrontendInstall,
    [switch]$SkipPythonInstall,
    [string]$SearchDbSrc
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $Root "frontend"
$Spec = Join-Path $Root "packaging\searchviewer.spec"
$Dist = Join-Path $Root "dist"
$ExampleSettings = Join-Path $Root "packaging\SearchViewerSettings.example.yaml"
$SearchDbSrcPath = if ($SearchDbSrc) {
    (Resolve-Path $SearchDbSrc).Path
} else {
    Join-Path (Split-Path $Root -Parent) "SearchDB\src"
}
$SearchDbPackage = Join-Path $SearchDbSrcPath "searchdb"
$BuildVenv = Join-Path $Root ".venv-build"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$NpmCommand = if ($env:OS -eq "Windows_NT") { "npm.cmd" } else { "npm" }

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

Push-Location $Root
$PreviousSearchDbSrc = $env:SEARCHVIEWER_SEARCHDB_SRC
try {
    if (-not (Test-Path $SearchDbPackage)) {
        throw "SearchDB package source not found: $SearchDbPackage"
    }
    $env:SEARCHVIEWER_SEARCHDB_SRC = $SearchDbSrcPath

    if (-not (Test-Path $BuildPython)) {
        Invoke-Checked "py" @("-m", "venv", "--system-site-packages", $BuildVenv)
    }
    if (-not $SkipPythonInstall) {
        Invoke-Checked $BuildPython @("-m", "pip", "install", "-e", ".[dev]")
    }

    Push-Location $Frontend
    try {
        if (-not $SkipFrontendInstall -and -not (Test-Path (Join-Path $Frontend "node_modules"))) {
            Invoke-Checked $NpmCommand @("install")
        }
        Invoke-Checked $NpmCommand @("run", "build")
    }
    finally {
        Pop-Location
    }

    Invoke-Checked $BuildPython @("-m", "PyInstaller", "--noconfirm", $Spec)

    if (Test-Path $ExampleSettings) {
        Copy-Item -LiteralPath $ExampleSettings -Destination (Join-Path $Dist "SearchViewerSettings.example.yaml") -Force
    }

    Write-Host "Built: $(Join-Path $Dist 'SearchViewer.exe')"
    Write-Host "Place SearchViewerSettings.yaml next to SearchViewer.exe before distribution."
}
finally {
    $env:SEARCHVIEWER_SEARCHDB_SRC = $PreviousSearchDbSrc
    Pop-Location
}
