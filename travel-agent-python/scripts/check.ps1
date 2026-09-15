# Single-command local gate (G-0.4). Runs the cheap gates first, offline tests last.
# CI (ci.yml preflight job) runs the SAME steps in the SAME order: ruff check ->
# ruff format --check -> typecheck (pyright baseline ratchet) -> secret scan ->
# offline pytest. import-linter joins here when G-1.2 lands.
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

Write-Host ""
Write-Host "ALL GREEN" -ForegroundColor Green
