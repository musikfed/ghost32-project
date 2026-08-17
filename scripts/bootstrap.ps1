param(
    [switch]$KeepVenv
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== ESP32 MultiBoard Studio 2.5.0 setup ==" -ForegroundColor Cyan

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not found in PATH. Install uv first."
}

if (-not $KeepVenv -and (Test-Path ".venv")) {
    Write-Host "Removing old .venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".venv"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv with Python 3.13..." -ForegroundColor Green
    uv venv --python 3.13 .venv
}

$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Version = & $Py -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if (-not $Version.StartsWith("3.13.")) {
    throw "Wrong virtualenv Python: $Version. Expected Python 3.13.x"
}
Write-Host "Virtualenv Python: $Version" -ForegroundColor Green

Write-Host "Installing Python dependencies with uv..." -ForegroundColor Green
uv sync --python $Py

Write-Host "Verifying ESP host tools in .venv..." -ForegroundColor Green
& $Py -c "import importlib.metadata as m; import esptool, mpremote; print('esptool', m.version('esptool')); print('mpremote', m.version('mpremote'))"
if ($LASTEXITCODE -ne 0) { throw "esptool/mpremote verification failed. Run REPAIR_ENV.cmd." }
& $Py -m esptool --help *> $null
if ($LASTEXITCODE -ne 0) { throw "python -m esptool failed." }
& $Py -m mpremote --help *> $null
if ($LASTEXITCODE -ne 0) { throw "python -m mpremote failed." }

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required to build the React UI. Install Node.js 20+ or 22+ and rerun this script."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not found in PATH."
}

$NodeMajor = [int]((& node --version).TrimStart('v').Split('.')[0])
if ($NodeMajor -lt 20) {
    throw "Node.js 20+ is required. Found: $(& node --version)"
}

Write-Host "Building React frontend..." -ForegroundColor Green
Push-Location (Join-Path $Root "frontend")
try {
    npm install --no-audit --no-fund
    npm run build
}
finally {
    Pop-Location
}

Write-Host "" 
Write-Host "Setup complete." -ForegroundColor Cyan
Write-Host "Start with: .\scripts\run.ps1" -ForegroundColor White
