#!/usr/bin/env powershell
# Pre-commit / pre-push secret scan for Travel-Assistant.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-secrets.ps1
# Exit 1 if suspicious secrets found in project sources (skips local .env and vendor dirs).

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Patterns match real key shapes. Placeholders like "your-llm-api-key" are not matched.
$patterns = @(
    'sk-[A-Za-z0-9._-]{20,}'
    'sk-ws-[A-Za-z0-9._-]{10,}'
    'eyJhbGciOi[A-Za-z0-9_-]{20,}'
    '-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----'
    'AKIA[0-9A-Z]{16}'
    'AMAP_WEB_KEY=[a-f0-9]{25,}'
    'UNSPLASH_ACCESS_KEY=[A-Za-z0-9_-]{25,}'
)

$skip = '\\(\.git|node_modules|\.venv[^\\]*|\.uv-cache|\.uv-python|\.pnpm-store|models|dist|target|\.idea|\.vscode|data|logs|\.test-report|site-packages)\\'
$found = New-Object System.Collections.Generic.List[string]

$files = Get-ChildItem -Path $root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch $skip -and $_.Length -lt 2MB } |
    Where-Object {
        $_.Extension -match '^\.(md|java|py|ts|vue|js|yml|yaml|xml|json|ps1|cmd|sql|html|toml|txt)$' -or
        $_.Name -eq '.env.example' -or $_.Name -like '.env.*'
    }

foreach ($file in $files) {
    # Never scan real local .env (contains live keys by design; not tracked).
    if ($file.Name -eq '.env') { continue }
    # This scanner itself embeds pattern literals.
    if ($file.Name -eq 'check-secrets.ps1') { continue }
    if ($file.FullName -match 'package-lock|pnpm-lock|\.min\.(js|css)') { continue }

    $hits = Select-String -Path $file.FullName -Pattern $patterns -ErrorAction SilentlyContinue
    if (-not $hits) { continue }

    $rel = $file.FullName.Substring($root.Length).TrimStart('\', '/')
    Write-Host "HIT $rel"
    foreach ($h in ($hits | Select-Object -First 5)) {
        $line = $h.Line
        if ($line.Length -gt 140) { $line = $line.Substring(0, 140) }
        Write-Host ("  L{0}: {1}" -f $h.LineNumber, $line)
    }
    $found.Add($rel) | Out-Null
}

if ($found.Count -gt 0) {
    Write-Host ""
    Write-Host ("Found {0} file(s) with suspicious secrets. Rotate real keys and remove them from trackable files." -f $found.Count) -ForegroundColor Red
    exit 1
}

Write-Host "OK: no suspicious secrets in scannable project sources." -ForegroundColor Green
exit 0
