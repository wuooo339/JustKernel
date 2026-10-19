param([int]$Port = 4173, [switch]$NoBrowser, [switch]$Background)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$boundProcess = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($boundProcess) {
  $recordedPid = [int]($boundProcess | Select-Object -First 1).OwningProcess
  $runningProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid"
  if ($runningProcess) {
    $expectedPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))
    $ownedProcess = $runningProcess.ExecutablePath -eq $expectedPython
    # On Windows the venv launcher remains the parent of the base Python process.
    if (-not $ownedProcess -and (Test-Path -LiteralPath $expectedPython)) {
      $basePython = & $expectedPython -c 'import sys; print(sys._base_executable)'
      if ($LASTEXITCODE -ne 0) { throw 'Cannot verify this project Python interpreter.' }
      $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$($runningProcess.ParentProcessId)"
      $ownedProcess = $runningProcess.ExecutablePath -eq $basePython.Trim() -and
        $launcher.ExecutablePath -eq $expectedPython -and
        $launcher.CommandLine -like '*aworker.lab.cli*serve*' -and
        $launcher.CreationDate -le $runningProcess.CreationDate
      if (-not $ownedProcess -and $runningProcess.ExecutablePath -eq $basePython.Trim()) {
        $supervisorPath = Join-Path $PSScriptRoot '.justkernel\supervisor.json'
        if (Test-Path -LiteralPath $supervisorPath) {
          $supervisor = Get-Content -LiteralPath $supervisorPath -Raw | ConvertFrom-Json
          $ownedProcess = $launcher.ExecutablePath -eq $basePython.Trim() -and
            $launcher.CommandLine -like '*aworker.lab.supervisor*' -and
            $supervisor.supervisor_pid -eq $launcher.ProcessId -and
            $supervisor.service_pid -eq $recordedPid -and
            $supervisor.root -eq (Join-Path $PSScriptRoot '.justkernel') -and
            $launcher.CreationDate -le $runningProcess.CreationDate
        }
      }
    }
    if (-not $ownedProcess -or $runningProcess.CommandLine -notlike '*aworker.lab.cli*serve*') {
      throw 'Port owner does not match this project. No process was stopped.'
    }
    $snapshot = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/lab/snapshot" -TimeoutSec 20
    if ($snapshot.continuous.enabled) { throw 'Pause continuous search in the dashboard before restarting.' }
    if ($snapshot.judge_selector_running) {
      $judge = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/lab/workspace/judge" -TimeoutSec 20
      # Read-only selection may be interrupted only during an explicitly paused maintenance window.
      if ($snapshot.continuous.enabled -or $judge.automation.enabled -or $judge.automation.busy) {
        throw 'Pause continuous search and official judging before restarting active selection.'
      }
    }
    if ($snapshot.setup_running -or $snapshot.judge_submission_running -or @($snapshot.operations | Where-Object state -eq 'running').Count -or @($snapshot.jobs | Where-Object state -In @('queued','running')).Count) {
      throw 'Finish running model/device work before restarting.'
    }
    Stop-Process -Id $recordedPid -ErrorAction Stop
    Wait-Process -Id $recordedPid -ErrorAction SilentlyContinue
    $monitorStatusPath = Join-Path $PSScriptRoot '.justkernel\supervisor.json'
    if (Test-Path -LiteralPath $monitorStatusPath) {
      $monitorStatus = Get-Content -LiteralPath $monitorStatusPath -Raw | ConvertFrom-Json
      if ($monitorStatus.service_pid -eq $recordedPid -and $monitorStatus.state -eq 'watching') {
        $oldMonitor = Get-Process -Id $monitorStatus.supervisor_pid -ErrorAction SilentlyContinue
        if ($oldMonitor) { Wait-Process -Id $oldMonitor.Id -Timeout 15 -ErrorAction Stop }
      }
    }
  }
}
if ($Background) {
  $servicePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $servicePython)) { throw 'Run start.ps1 once to install dependencies.' }
  $logDirectory = Join-Path $PSScriptRoot '.justkernel\service-logs'
  New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
  $logLabel = Get-Date -Format 'yyyyMMdd-HHmmss'
  $serviceProcess = Start-Process -FilePath $servicePython -ArgumentList @('-m', 'aworker.lab.supervisor', '--port', "$Port") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory "$logLabel.stdout.log") -RedirectStandardError (Join-Path $logDirectory "$logLabel.stderr.log") -PassThru
  Write-Host "JustKernel background service started (launcher $($serviceProcess.Id)): http://127.0.0.1:$Port/"
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
} else {
  & (Join-Path $PSScriptRoot 'start.ps1') -Port $Port -NoBrowser:$NoBrowser
}
