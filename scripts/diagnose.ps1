$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== ESP32 MultiBoard Studio 2.5.0 diagnostics ==" -ForegroundColor Cyan
Write-Host "uv:"; uv --version
Write-Host "py launchers:"; py --list
Write-Host "node:"; node --version
Write-Host "npm:"; npm --version

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $Py) {
    Write-Host "venv python:"; & $Py --version
    Write-Host "installed tool versions:"
    & $Py -c "import importlib.metadata as m; print('esptool',m.version('esptool')); print('mpremote',m.version('mpremote')); print('fastapi',m.version('fastapi')); print('pyserial',m.version('pyserial'))"
    Write-Host "esptool module entry point:"; & $Py -m esptool --help | Select-Object -First 4
    Write-Host "mpremote module entry point:"; & $Py -m mpremote --help | Select-Object -First 4
    Write-Host "serial ports:"
    & $Py -c "from serial.tools import list_ports; [print(p.device, '-', p.description, '-', p.hwid) for p in list_ports.comports()]"
} else {
    Write-Host ".venv is missing. Run REPAIR_ENV.cmd or SETUP.cmd" -ForegroundColor Yellow
}
