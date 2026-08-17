$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Virtualenv is missing; running bootstrap..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "bootstrap.ps1")
}

# EN: Expose console-script shims for manual commands; backend itself uses Python modules.
# RU: Добавляем CLI-shims в PATH для ручных команд; backend запускает модули через Python.
$VenvScripts = Join-Path $Root ".venv\Scripts"
$env:Path = "$VenvScripts;$env:Path"

if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    Write-Host "React build is missing; rebuilding..." -ForegroundColor Yellow
    Push-Location (Join-Path $Root "frontend")
    try {
        npm install --no-audit --no-fund
        npm run build
    }
    finally {
        Pop-Location
    }
}

Write-Host "Starting ESP32 MultiBoard Studio (port preflight will run first)..." -ForegroundColor Cyan
& $Py -m host.app
