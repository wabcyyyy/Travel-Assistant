# Stops backend-java(8080), agent-python(8000), frontend-vue(5173) process trees.
# Add -IncludeRedis to also stop redis on 6380.
param([switch]$IncludeRedis)

$ports = @(8080, 8000, 5173)
if ($IncludeRedis) { $ports += 6380 }

$found = $false
foreach ($p in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($c in ($conns | Sort-Object OwningProcess -Unique)) {
        $found = $true
        Write-Host "[stop] port $p pid $($c.OwningProcess)"
        taskkill /PID $c.OwningProcess /T /F 2>$null | Out-Null
    }
}
if (-not $found) { Write-Host "Nothing to stop." }
