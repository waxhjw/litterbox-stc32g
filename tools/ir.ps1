param([ValidateSet('build','check','flash','status','off','test38','link-low','link-high','watch','stop')][string]$Action='check')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$projectPython=Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
if ($Action -eq 'flash') {
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py') --profile IR003 --debug --wait-seconds 300
} elseif ($Action -eq 'build' -or $Action -eq 'check') {
    & $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') $Action --profile IR003 --debug
} else {
    & $projectPython (Join-Path $PSScriptRoot 'ir_status.py') $Action --profile IR003
}
exit $LASTEXITCODE
