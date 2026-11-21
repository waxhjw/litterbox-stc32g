param([ValidateSet('build','check','flash','status','stop')][string]$Action = 'check')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if ($Action -eq 'flash') {
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py') --profile MOTOR003 --debug
} elseif ($Action -eq 'status' -or $Action -eq 'stop') {
    & $projectPython (Join-Path $PSScriptRoot 'motor_status.py') $Action
} else {
    & $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') $Action --profile MOTOR003 --debug
}
exit $LASTEXITCODE
