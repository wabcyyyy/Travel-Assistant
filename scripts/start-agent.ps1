# Travel Assistant agent start/restart script
# Usage:
#   .\start-agent.ps1          # stop if running, then start
#   .\start-agent.ps1 -Keep    # skip if already running

param([switch]$Keep)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root 'travel-agent-python'))) {
    # Works whether this script sits at the repo root or under travel-agent-python.
    $root = $PSScriptRoot
}

$agentDir = Join-Path $root 'travel-agent-python'
$logDir = Join-Path $root 'logs'
$logFile = Join-Path $logDir 'agent-python.log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$env:UV_CACHE_DIR = Join-Path $root '.uv-cache'

# Root .env -> process env (child services inherit it; module-local .env is re-applied by python-dotenv)
$rootEnv = Join-Path $root '.env'
if (Test-Path $rootEnv) {
    Get-Content $rootEnv | ForEach-Object {
        if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*)\s*$') {
            Set-Item -Path "env:$($Matches[1])" -Value $Matches[2]
        }
    }
    Write-Host "[env] loaded $rootEnv"
}

function Test-Port([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Stop-AgentOnPort([int]$port = 8000) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in @($conns)) {
        $procId = $c.OwningProcess
        if (-not $procId) { continue }
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "[stop] pid=$procId on :$port"
        } catch {
            Write-Warning "failed to stop pid=$procId : $($_.Exception.Message)"
        }
    }
}

if (Test-Port 8000) {
    if ($Keep) {
        Write-Host '[skip] agent-python :8000 already running'
        exit 0
    }
    Write-Host '[stop] agent-python :8000 restarting...'
    Stop-AgentOnPort 8000
    Start-Sleep -Milliseconds 800
}

Write-Host "[start] agent-python :8000  log=$logFile"
Start-Process -FilePath 'cmd.exe' -ArgumentList @(
    '/k', 'title agent-python',
    '&&', 'cd', '/d', "`"$agentDir`"",
    '&&', 'uv', 'run', 'python', 'main.py',
    '>', "`"$logFile`"", '2>&1'
) -WindowStyle Hidden

$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Port 8000) { $ok = $true; break }
}

if ($ok) {
    $pidInfo = (Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -First 1).OwningProcess
    Write-Host "[ok] agent listening on http://127.0.0.1:8000 (pid=$pidInfo)"
    Write-Host "     tail log: Get-Content `"$logFile`" -Tail 50 -Wait"
} else {
    Write-Error "agent did not open :8000 within 30s -- check $logFile"
    if (Test-Path $logFile) { Get-Content $logFile -Tail 40 }
    exit 1
}
