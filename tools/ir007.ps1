param(
    [ValidateSet('build','check','flash','status','sample','probe','stop')][string]$Action='check',
    [ValidateRange(1,3)][int]$Channel=1,
    [ValidateSet('low','high')][string]$Level='high',
    [ValidateRange(1,1000)][int]$Count=100
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$projectPython=Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
if ($Action -eq 'build' -or $Action -eq 'check') {
    & $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') $Action --profile IR007
} elseif ($Action -eq 'flash') {
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py') --profile IR007 --debug --wait-seconds 60
} else {
    & $projectPython (Join-Path $PSScriptRoot 'array_probe.py') $Action --channel $Channel --level $Level --count $Count --version IR007
}
exit $LASTEXITCODE
