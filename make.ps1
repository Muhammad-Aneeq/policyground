<#
.SYNOPSIS
  PolicyGround task runner for Windows. Mirrors the Makefile target-for-target.

.DESCRIPTION
  GNU Make is not installed on the machine this repo was built on (BLOCKERS.md B3), and a
  quickstart that does not run on the machine that ships it is not a quickstart. Every target
  name here matches the Makefile exactly, so the README can document one vocabulary.

.EXAMPLE
  ./make.ps1 install
  ./make.ps1 ingest
  ./make.ps1 dev
  ./make.ps1 check
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'install', 'ingest', 'dev', 'api', 'web', 'test', 'lint',
                 'typecheck', 'eval', 'eval-offline', 'check', 'up', 'down', 'clean')]
    [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot

function Invoke-Step {
    param([string]$Label, [scriptblock]$Body)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit $LASTEXITCODE)" }
}

switch ($Target) {
    'help' {
        Write-Host "PolicyGround targets:" -ForegroundColor Cyan
        @(
            @{ n = 'install';      d = 'Sync Python (uv) + frontend (npm) deps' }
            @{ n = 'ingest';       d = 'Rebuild the retrieval index from corpus/' }
            @{ n = 'dev';          d = 'Full local demo: ingest, then API + SPA' }
            @{ n = 'api';          d = 'Backend only, http://localhost:8000' }
            @{ n = 'web';          d = 'Frontend only, http://localhost:5173' }
            @{ n = 'test';         d = 'Unit tests (LLM mocked)' }
            @{ n = 'lint';         d = 'ruff check + format --check' }
            @{ n = 'typecheck';    d = 'mypy (strict)' }
            @{ n = 'eval';         d = 'Groundedness suite + all four gates' }
            @{ n = 'eval-offline'; d = 'Same, judge cache-only (miss is fatal)' }
            @{ n = 'check';        d = 'Everything CI runs' }
            @{ n = 'up';           d = 'docker compose up -d' }
            @{ n = 'down';         d = 'docker compose down -v' }
            @{ n = 'clean';        d = 'Remove generated indexes and dev DB' }
        ) | ForEach-Object { "  {0,-14} {1}" -f $_.n, $_.d | Write-Host }
    }

    'install' {
        Invoke-Step 'uv sync' { uv sync --extra dev }
        Invoke-Step 'npm install' { Push-Location "$repo/frontend"; npm install; Pop-Location }
    }

    'ingest'       { Invoke-Step 'ingest' { uv run pg ingest --rebuild } }
    'api'          { Invoke-Step 'serve'  { uv run pg serve } }
    'web'          { Invoke-Step 'vite'   { Push-Location "$repo/frontend"; npm run dev; Pop-Location } }

    'dev' {
        Invoke-Step 'ingest' { uv run pg ingest --rebuild }
        Write-Host "==> starting API in a background job (http://localhost:8000)" -ForegroundColor Cyan
        $job = Start-Job -ScriptBlock { param($r) Set-Location $r; uv run pg serve } -ArgumentList $repo
        Write-Host "    API job id $($job.Id) - stop it with: Stop-Job $($job.Id)" -ForegroundColor DarkGray
        try {
            Push-Location "$repo/frontend"
            npm run dev
        } finally {
            Pop-Location
            Stop-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -Force -ErrorAction SilentlyContinue
        }
    }

    'test'         { Invoke-Step 'pytest tests' { uv run pytest tests -m "not live and not azure" } }
    'lint' {
        Invoke-Step 'ruff check'  { uv run ruff check backend/src tests evals }
        Invoke-Step 'ruff format' { uv run ruff format --check backend/src tests evals }
    }
    'typecheck'    { Invoke-Step 'mypy' { uv run mypy } }
    'eval'         { Invoke-Step 'pytest evals' { uv run pytest evals -m "not live and not azure" } }
    'eval-offline' {
        $env:OFFLINE = '1'
        try { Invoke-Step 'pytest evals (offline)' { uv run pytest evals -m "not live and not azure" } }
        finally { Remove-Item Env:OFFLINE -ErrorAction SilentlyContinue }
    }

    'check' {
        foreach ($t in 'lint', 'typecheck', 'test', 'eval') { & "$repo/make.ps1" $t }
        Write-Host "==> all checks passed" -ForegroundColor Green
    }

    'up'    { Invoke-Step 'compose up'   { docker compose up -d } }
    'down'  { Invoke-Step 'compose down' { docker compose down -v } }
    'clean' {
        foreach ($p in 'data', '.pytest_cache', '.ruff_cache', '.mypy_cache') {
            $full = Join-Path $repo $p
            if (Test-Path $full) { Remove-Item $full -Recurse -Force; Write-Host "  removed $p" }
        }
    }
}
