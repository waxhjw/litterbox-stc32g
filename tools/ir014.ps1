param(
    [ValidateSet('build','check','preflight','flash','status','watch','hall','hall-watch','watch-with-hall','stop')][string]$Action='check',
    [ValidateSet('IR014','IR015','IR016', 'IR017')][string]$Profile='IR014',
    [ValidateRange(1,300)][int]$Seconds=60,
    [ValidateSet('','high','low')][string]$RadarActive=''
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$projectPython=Join-Path $projectRoot '.tools/serial-venv/Scripts/python.exe'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
if ($Action -in @('build','check','preflight')) {
    & $projectPython (Join-Path $PSScriptRoot 'diagnostic.py') $Action --profile $Profile
} elseif ($Action -eq 'flash') {
    $downloadArgs = @('--profile', $Profile, '--debug', '--wait-seconds', '300')
    if ($Profile -in @('IR015','IR016', 'IR017')) {
        $downloadArgs += @('--transfer-baud', '38400')
    }
    & $projectPython (Join-Path $PSScriptRoot 'attempt_logger.py') @downloadArgs
} elseif ($Action -eq 'hall' -or $Action -eq 'hall-watch') {
    $mode = if ($Action -eq 'hall') { 'status' } else { 'watch' }
    & $projectPython (Join-Path $PSScriptRoot 'watch_ir_link.py') $mode --profile $Profile --hall --seconds $Seconds
} elseif ($Action -eq 'watch-with-hall') {
    & $projectPython (Join-Path $PSScriptRoot 'watch_ir_link.py') watch --profile $Profile --with-hall --seconds $Seconds
} elseif ($Action -eq 'status' -and $RadarActive) {
    & $projectPython (Join-Path $PSScriptRoot 'watch_ir_link.py') status --profile $Profile --radar-active $RadarActive
} else {
    & $projectPython (Join-Path $PSScriptRoot 'watch_ir_link.py') $Action --profile $Profile --seconds $Seconds
}
exit $LASTEXITCODE
