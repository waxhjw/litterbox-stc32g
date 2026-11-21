param([ValidateSet('build','check','probe','flash')][string]$Action = 'check')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') $Action
exit $LASTEXITCODE
