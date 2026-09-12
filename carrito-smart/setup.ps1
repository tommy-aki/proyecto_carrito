$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalPython = Join-Path $ProjectRoot ".python312\python.exe"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $LocalPython) {
    $PythonExe = $LocalPython
} else {
    try {
        $PythonExe = (& py -3.12 -c "import sys; print(sys.executable)").Trim()
    } catch {
        throw "No se encontró Python 3.12. Instálelo desde python.org y ejecute de nuevo."
    }
}

Write-Host "Usando $(& $PythonExe --version)"
& $PythonExe -m venv (Join-Path $ProjectRoot ".venv")
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e "$ProjectRoot[dev]"

Write-Host ""
Write-Host "Instalación terminada. Ejecute .\run.ps1"

