param(
    [switch]$SkipFrontendInstall
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $Root "frontend"
$Spec = Join-Path $Root "packaging\searchviewer.spec"
$Dist = Join-Path $Root "dist"
$ExampleSettings = Join-Path $Root "packaging\SearchViewerSettings.example.yaml"

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
try {
    Invoke-Checked "py" @("-m", "pip", "install", "-e", ".[dev]")

    Push-Location $Frontend
    try {
        if (-not $SkipFrontendInstall -and -not (Test-Path (Join-Path $Frontend "node_modules"))) {
            Invoke-Checked "npm" @("install")
        }
        Invoke-Checked "npm" @("run", "build")
    }
    finally {
        Pop-Location
    }

    Invoke-Checked "py" @("-m", "PyInstaller", "--noconfirm", $Spec)

    if (Test-Path $ExampleSettings) {
        Copy-Item -LiteralPath $ExampleSettings -Destination (Join-Path $Dist "SearchViewerSettings.example.yaml") -Force
    }

    Write-Host "Built: $(Join-Path $Dist 'SearchViewer.exe')"
    Write-Host "Place SearchViewerSettings.yaml next to SearchViewer.exe before distribution."
}
finally {
    Pop-Location
}
