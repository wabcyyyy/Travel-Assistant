# Single-command local gate (G-0.4). Runs the cheap gates first, offline tests last.
# CI (ci.yml preflight job) runs the SAME steps in the SAME order: ruff check ->
# ruff format --check -> typecheck (pyright baseline ratchet) -> import-linter ->
# secret scan -> offline pytest.
# Usage (from anywhere): powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check.ps1
# NOTE: ASCII-only comments - Windows PowerShell 5.1 reads BOM-less files as ANSI.

$ErrorActionPreference = 'Stop'
$pkg = Split-Path -Parent $PSScriptRoot
Set-Location $pkg

function Step([string]$name) { Write-Host "==> $name" -ForegroundColor Cyan }

Step "ruff check"
uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "ruff format --check"
uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "typecheck (pyright baseline ratchet)"
uv run python scripts/typecheck.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "import boundaries (import-linter, G-1.2)"
uv run lint-imports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "code metrics (long functions / huge files ratchet)"
uv run python scripts/code_metrics.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "secret scan"
$root = Split-Path -Parent $pkg
$secrets = Join-Path $root "scripts\check-secrets.ps1"
if (Test-Path $secrets) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $secrets
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Step "offline tests (+ coverage)"
$env:RAG_EMBEDDING_PROVIDER = "hashed"
uv run pytest tests/ -q --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval --cov=app --cov-report=xml --cov-report=
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "coverage gate on changed lines (diff-cover, G-3.4)"
# 本次变更行覆盖率 >= 70%，门槛只升不降。基线取 origin/master；无该引用时
# （如浅克隆或离线仓库）跳过并提示，避免本地门禁因缺基线而误红。
git rev-parse --verify --quiet origin/master > $null
if ($LASTEXITCODE -eq 0) {
    uv run diff-cover coverage.xml --compare-branch=origin/master --fail-under=70
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "  skipped: origin/master not available (shallow clone?)" -ForegroundColor Yellow
}

Step "contract export drift"
# CI python-agent job 同款检查：重跑导出后与入仓产物逐字节比对（G-1.1）
uv run python scripts/export_contracts.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --exit-code -- ../contracts ../travel-frontend-vue/src/types/generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "ALL GREEN" -ForegroundColor Green
