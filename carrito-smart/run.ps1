$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "El entorno virtual no existe. Ejecute .\setup.ps1 primero."
}

Push-Location $ProjectRoot
try {
    & $VenvPython -m carrito_smart
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
