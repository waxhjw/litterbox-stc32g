param(
    [ValidateSet('build','check','flash','status','watch','stop')][string]$Action='check'
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$projectPython=Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
if ($Action -in @('build','check')) {
    & $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') $Action --profile IR013
} elseif ($Action -eq 'flash') {
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py') --profile IR013 --debug --wait-seconds 300
} else {
    & $projectPython (Join-Path $PSScriptRoot 'watch_ir_link.py') $Action
}
exit $LASTEXITCODE
