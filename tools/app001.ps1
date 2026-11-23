param(
    [ValidateSet('build','check','flash','status','watch','radar-high','stop','arm-watch','optical-check','period-check','phase-check')][string]$Action='status',
    [ValidateSet('APP001','APP002','APP003','APP004','APP005','DRUM001','DRUM002','DRUM003','DRUM004','DRUM005','DRUM006','DRUM007','DRUM008','DRUM009','DRUM010','DRUM011','DRUM012','DRUM013')][string]$Profile='APP001',
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
    & $python (Join-Path $PSScriptRoot 'app001_status.py') $Action --profile $Profile --seconds $Seconds
}
exit $LASTEXITCODE
