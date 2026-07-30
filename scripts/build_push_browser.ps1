<#
.SYNOPSIS
    Build the leviathan-browser Docker image (playwright + chromium; W1c producers) and push to ECR.

.DESCRIPTION
    Mirrors build_push_worker.ps1's two load-bearing conventions:
      * build context = THIS script's repo root, never the caller's cwd (the d9b2e10e stale-src trap);
      * never push :latest alone -- every push carries a durable datestamp tag (SILVER-F085).
    Dockerfile lives at docker/leviathan_browser/Dockerfile; it needs the repo root as context
    (COPY src/ jobs/ configs/), same as the worker image.

.EXAMPLE
    .\scripts\build_push_browser.ps1 -Tag "20260730w1c"
#>
param(
    [string]$Tag       = "latest",
    [string]$Region    = "us-east-1",
    [string]$AccountId = "668891723125",
    [string]$RepoName  = "leviathan-dev-leviathan-browser"
)

$ErrorActionPreference = "Stop"

if ($Tag -eq "latest") {
    $Tag = Get-Date -Format "yyyyMMddTHHmmss"
    Write-Host "==> No -Tag given: auto-datestamp tag '$Tag' (latest-only pushes are banned)" -ForegroundColor Yellow
}

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Write-Host "==> Build context: $RepoRoot" -ForegroundColor Cyan

$EcrBase     = "${AccountId}.dkr.ecr.${Region}.amazonaws.com"
$LatestImage = "${EcrBase}/${RepoName}:latest"
$TaggedImage = "${EcrBase}/${RepoName}:${Tag}"

Write-Host "==> Authenticating to ECR ($EcrBase)..."
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $EcrBase
if ($LASTEXITCODE -ne 0) { throw "ECR login failed" }

Write-Host "==> Building $LatestImage"
docker build -f "$RepoRoot\docker\leviathan_browser\Dockerfile" -t $LatestImage "$RepoRoot"
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

# Runtime-closure smoke: the three producers import (lazily, so this proves module syntax +
# core deps) and playwright's chromium is actually installed where PLAYWRIGHT_BROWSERS_PATH says.
Write-Host "==> Runtime-closure smoke (producer imports + chromium presence)..."
docker run --rm --entrypoint python $LatestImage -c "import importlib.util as u; assert all(u.find_spec(m) for m in ('leviathan.ingest.browser_fetch','playwright')); import runpy, pathlib; [pathlib.Path('/app/jobs/ingest', f).exists() or (_ for _ in ()).throw(SystemExit('missing ' + f)) for f in ('fetch_dce_eod.py','fetch_euronext_eod.py','fetch_bursa_fcpo.py')]; import subprocess; r = subprocess.run(['python','-c','from playwright.sync_api import sync_playwright\nwith sync_playwright() as p: print(p.chromium.executable_path)'], capture_output=True, text=True); assert r.returncode == 0 and r.stdout.strip(), r.stderr[-400:]; print('smoke OK: ' + r.stdout.strip())"
if ($LASTEXITCODE -ne 0) { throw "runtime smoke failed" }

Write-Host "==> Tagging as $TaggedImage"
docker tag $LatestImage $TaggedImage

Write-Host "==> Pushing $LatestImage"
docker push $LatestImage
if ($LASTEXITCODE -ne 0) { throw "push :latest failed" }
Write-Host "==> Pushing $TaggedImage"
docker push $TaggedImage
if ($LASTEXITCODE -ne 0) { throw "push :$Tag failed" }

Write-Host "`n==> Done. Image live in ECR:" -ForegroundColor Green
Write-Host "    $LatestImage"
Write-Host "    $TaggedImage"
