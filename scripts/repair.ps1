$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== ESP32 MultiBoard Studio environment repair ==" -ForegroundColor Cyan

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not found in PATH. Install uv first."
}

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Creating .venv with Python 3.13..." -ForegroundColor Yellow
    uv venv --python 3.13 .venv
}

$Version = & $Py -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if (-not $Version.StartsWith("3.13.")) {
    Write-Host "Recreating .venv because Python is $Version, expected 3.13.x" -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".venv"
    uv venv --python 3.13 .venv
    $Py = Join-Path $Root ".venv\Scripts\python.exe"
}

Write-Host "Synchronizing Python dependencies..." -ForegroundColor Green
uv sync --python $Py

Write-Host "Checking modules in the exact Studio interpreter..." -ForegroundColor Green
& $Py -c "import importlib.metadata as m; import esptool, mpremote, fastapi, serial; print('esptool', m.version('esptool')); print('mpremote', m.version('mpremote')); print('fastapi', m.version('fastapi')); print('pyserial', m.version('pyserial'))"
if ($LASTEXITCODE -ne 0) { throw "Python tool verification failed." }

Write-Host "Checking CLI module entry points..." -ForegroundColor Green
& $Py -m esptool --help *> $null
if ($LASTEXITCODE -ne 0) { throw "python -m esptool failed." }
& $Py -m mpremote --help *> $null
if ($LASTEXITCODE -ne 0) { throw "python -m mpremote failed." }

Write-Host "" 
Write-Host "Environment repaired successfully." -ForegroundColor Cyan
Write-Host "Now run START_STUDIO.cmd" -ForegroundColor White
