param(
    [ValidateSet('build','check','flash','status','watch','pair','baud')][string]$Action='status',
    [ValidateSet('WIFI001','WIFI002')][string]$Profile='WIFI001',
    [ValidateRange(1,300)][int]$Seconds=60
)
$ErrorActionPreference='Stop'
$python=Join-Path (Split-Path -Parent $PSScriptRoot) '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8='1'
if ($Action -in @('build','check')) {
    & $python (Join-Path $PSScriptRoot 'diagnostic.py') $Action --profile $Profile
} elseif ($Action -eq 'flash') {
    & $python (Join-Path $PSScriptRoot 'attempt_logger.py') --profile $Profile --debug --wait-seconds 300 --transfer-baud 38400
} else {
    & $python (Join-Path $PSScriptRoot 'wifi001_status.py') $Action --profile $Profile --seconds $Seconds
}
exit $LASTEXITCODE
