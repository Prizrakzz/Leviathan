<#
.SYNOPSIS
    Build the leviathan-trainer Docker image and push it to ECR.

.DESCRIPTION
    Builds docker/leviathan_trainer/Dockerfile (Python + torch CPU + the
    [training] extras: xgboost/lightgbm/sklearn/shap/mlflow) for linux/amd64 and
    pushes to the dev trainer repository, always tagging :latest so the
    leviathan-dev-train Batch job definition picks it up.

.EXAMPLE
    .\scripts\build_push_trainer.ps1
    .\scripts\build_push_trainer.ps1 -Tag "20260618"
#>
param(
    [string]$Tag       = "latest",
    [string]$Region    = "us-east-1",
    [string]$AccountId = "668891723125",
    [string]$RepoName  = "leviathan-dev-leviathan-trainer",
    [switch]$ForceAmd64Platform
)

$ErrorActionPreference = "Stop"

# SILVER-F085 (2026-07-23): NEVER push :latest-only. A latest-only image loses its tag when the
# next push steals :latest; digest-pinned jobdefs/taskdefs then reference an UNTAGGED image that
# ECR lifecycle rules may expire (broke the 14:00 UTC usda_esr run; 16 jobdef families stranded).
# Every push therefore carries a durable datestamp tag, auto-derived when -Tag was omitted.
if ($Tag -eq "latest") {
    $Tag = Get-Date -Format "yyyyMMddTHHmmss"
    Write-Host "==> No -Tag given: auto-datestamp tag '$Tag' (latest-only pushes are banned)" -ForegroundColor Yellow
}

# Build context = THIS script's repo root, NEVER the caller's cwd (the d9b2e10e trap: `docker build
# ... .` packaged whatever tree the shell sat in -- on 2026-07-18 that baked a stale main-repo src/
# into worker :latest, silently dropping the same-day CEC parser; caught by the in-container
# content-check gate before any job ran on it).
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Write-Host "==> Build context: $RepoRoot" -ForegroundColor Cyan

$EcrBase     = "${AccountId}.dkr.ecr.${Region}.amazonaws.com"
$LatestImage = "${EcrBase}/${RepoName}:latest"
$TaggedImage = "${EcrBase}/${RepoName}:${Tag}"

Write-Host "==> Authenticating to ECR ($EcrBase)..." -ForegroundColor Cyan
$EcrToken = aws ecr get-login-password --region $Region
if ($LASTEXITCODE -ne 0) { throw "ecr get-login-password failed (exit $LASTEXITCODE)" }
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$null = docker login --username AWS --password $EcrToken $EcrBase 2>&1
$loginExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($loginExit -ne 0) { throw "ECR login failed (exit $loginExit)" }
Write-Host "ECR login succeeded." -ForegroundColor Green

Write-Host "==> Building image: $LatestImage" -ForegroundColor Cyan
$DockerPlatform = docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
if ($LASTEXITCODE -ne 0) { throw "docker version failed (exit $LASTEXITCODE)" }
$PlatformArgs = @()
if ($ForceAmd64Platform -or $DockerPlatform.Trim() -ne "linux/amd64") {
    $PlatformArgs = @("--platform", "linux/amd64")
    Write-Host "    Using explicit platform linux/amd64 (Docker server: $DockerPlatform)" -ForegroundColor DarkGray
} else {
    Write-Host "    Docker server is already linux/amd64; omitting --platform." -ForegroundColor DarkGray
}
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
docker build `
    @PlatformArgs `
    --tag $LatestImage `
    --file (Join-Path $RepoRoot "docker/leviathan_trainer/Dockerfile") `
    $RepoRoot 2>&1
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($buildExit -ne 0) { throw "docker build failed (exit $buildExit)" }

if ($Tag -ne "latest") {
    docker tag $LatestImage $TaggedImage
    if ($LASTEXITCODE -ne 0) { throw "docker tag failed (exit $LASTEXITCODE)" }
}

Write-Host "==> Pushing $LatestImage" -ForegroundColor Cyan
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
docker push $LatestImage 2>&1
$pushExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($pushExit -ne 0) { throw "docker push :latest failed (exit $pushExit)" }

if ($Tag -ne "latest") {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    docker push $TaggedImage 2>&1
    $pushTagExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($pushTagExit -ne 0) { throw "docker push :$Tag failed (exit $pushTagExit)" }
}

Write-Host ""
Write-Host "==> Done. Trainer image live in ECR:" -ForegroundColor Green
Write-Host "    $LatestImage" -ForegroundColor Green
