param([switch]$Trace)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if ($Trace) {
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py') --debug
} else {
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py')
}
$attemptExitCode = $LASTEXITCODE
Write-Output ('EXIT: ' + $attemptExitCode)
exit $attemptExitCode
