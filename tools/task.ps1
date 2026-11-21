param(
    [ValidateSet('doctor','validate','build','flash-check','flash','capture','probe')]
    [string]$Action = 'doctor'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Project Python is missing. See README.md to prepare the tools.'
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if ($Action -eq 'capture') {
    & $projectPython (Join-Path $PSScriptRoot 'capture_uart_rx.py') --seconds 20
} elseif ($Action -eq 'probe') {
    & $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') probe
} else {
    & $projectPython (Join-Path $PSScriptRoot 'project.py') $Action
}
exit $LASTEXITCODE
