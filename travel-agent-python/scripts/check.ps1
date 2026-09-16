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

Step "offline tests"
$env:RAG_EMBEDDING_PROVIDER = "hashed"
uv run pytest tests/ -q --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step "contract export drift"
# CI python-agent job 同款检查：重跑导出后与入仓产物逐字节比对（G-1.1）
uv run python scripts/export_contracts.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --exit-code -- ../contracts ../travel-frontend-vue/src/types/generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "ALL GREEN" -ForegroundColor Green
