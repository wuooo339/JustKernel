param([int]$Port = 4173, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$bundledUv = Join-Path $PSScriptRoot '.runtime-tools\bin\uv.exe'
if ($uvCommand) { $uvPath = $uvCommand.Source }
elseif (Test-Path -LiteralPath $bundledUv) { $uvPath = $bundledUv }
else { $uvPath = $null }
try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/lab/health" -TimeoutSec 2
  if ($health.generation -eq 'deepagents-v2') {
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
    Write-Host "JustKernel is already running at http://127.0.0.1:$Port/"
    exit 0
  }
} catch { }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  Write-Host "Port $Port is occupied. Close its window or run: .\start.ps1 -Port 4174"
  exit 1
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
  if (-not $uvPath) { throw 'Install uv from https://docs.astral.sh/uv/ and try again.' }
  & $uvPath sync --locked
  if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
Write-Host "JustKernel: http://127.0.0.1:$Port/  (Ctrl+C stops this service)"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
& $pythonPath -m aworker.lab.supervisor --port $Port
exit $LASTEXITCODE
