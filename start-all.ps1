# Travel Assistant one-click launcher
# Starts redis(6380), backend-java(8080), agent-python(8000), frontend-vue(5173).
# Services already running are skipped. Each service opens in its own console window.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Port([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Start-ServiceWindow([string]$title, [string]$workdir, [string]$cmdline) {
    $args_ = "/k title $title && cd /d `"$workdir`" && $cmdline"
    Start-Process -FilePath "cmd.exe" -ArgumentList $args_
}

Write-Host "=== Travel Assistant launcher ==="

# --- redis (cache, optional but recommended) ---
if (-not (Test-Port 6380)) {
    $redisExe = Join-Path $env:LOCALAPPDATA "Temp\opencode\redis\redis-server.exe"
    if (Test-Path $redisExe) {
        Start-Process -FilePath $redisExe -ArgumentList "--port 6380" -WindowStyle Minimized
        Write-Host "[start] redis      :6380"
    } else {
        Write-Warning "redis-server.exe not found at $redisExe - cache-dependent APIs will fail"
    }
} else {
    Write-Host "[skip ] redis      :6380 already running"
}

# --- backend java :8080 ---
if (-not (Test-Port 8080)) {
    Start-ServiceWindow "backend-java" "$root\travel-backend-java" `
        "mvn spring-boot:run -Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8"
    Write-Host "[start] backend-java :8080"
} else {
    Write-Host "[skip ] backend-java :8080 already running"
}

# --- agent python :8000 ---
if (-not (Test-Port 8000)) {
    Start-ServiceWindow "agent-python" "$root\travel-agent-python" `
        "uv run python main.py"
    Write-Host "[start] agent-python :8000"
} else {
    Write-Host "[skip ] agent-python :8000 already running"
}

# --- frontend vue :5173 ---
if (-not (Test-Port 5173)) {
    Start-ServiceWindow "frontend-vue" "$root\travel-frontend-vue" `
        "npm run dev"
    Write-Host "[start] frontend-vue :5173"
} else {
    Write-Host "[skip ] frontend-vue :5173 already running"
}

# --- health check ---
Write-Host ""
Write-Host "Waiting for services to become healthy..."
$targets = @(
    @{ Name = "backend-java :8080"; Url = "http://127.0.0.1:8080/api/test/hello" },
    @{ Name = "agent-python :8000"; Url = "http://127.0.0.1:8000/api/agent/hello" },
    @{ Name = "frontend-vue :5173"; Url = "http://localhost:5173/" }
)
$deadline = (Get-Date).AddSeconds(150)
$pending = @($targets)
while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    foreach ($t in @($pending)) {
        try {
            Invoke-WebRequest -Uri $t.Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            Write-Host "[ ok   ] $($t.Name)"
            $pending = @($pending | Where-Object { $_ -ne $t })
        } catch { }
    }
}
foreach ($t in $pending) { Write-Host "[TIMEOUT] $($t.Name) not responding yet - check its window for errors" }

Write-Host ""
Write-Host "Done. Web UI: http://localhost:5173  (dev/dev123)"
