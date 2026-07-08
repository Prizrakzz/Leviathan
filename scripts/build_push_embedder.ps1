<#
.SYNOPSIS
    Build the leviathan-embedder Docker image and push it to ECR.

.DESCRIPTION
    Authenticates to ECR, builds the image for linux/amd64 (required for AWS Batch Fargate x86-64), tags it,
    and pushes to the dev repository. Always also tags as :latest so Batch job definitions pick it up.

    The embedder image is the GraphRAG v2 evidence-build + serving worker: it bakes src/ + jobs/ + the gitignored
    configs/graphrag/ (causal DAGs, numbers/tables.yaml, eval_queries_*.yaml) into a PRIVATE ECR image. Rebuild
    whenever the serving code (orchestrator / numbers agent / intent / answer / register) or the eval queries
    change, so a Fargate eval run reads the current tree. The ~4.5 GB bge-m3 model is NOT baked (fetched from HF
    at runtime, in-region) — see the Dockerfile note.

.PARAMETER Tag
    Optional additional tag (e.g. a datestamp like "20260702"). Default: "latest" only.

.EXAMPLE
    .\scripts\build_push_embedder.ps1
    .\scripts\build_push_embedder.ps1 -Tag "20260702"
#>
param(
    [string]$Tag       = "latest",
    [string]$Region    = "us-east-1",
    [string]$AccountId = "668891723125",
    [string]$RepoName  = "leviathan-dev-leviathan-embedder",
    [switch]$ForceAmd64Platform
)

$ErrorActionPreference = "Stop"

# Build context = THIS script's repo root, NEVER the caller's cwd. The old `docker build ... .` silently
# packaged whatever tree the shell happened to sit in — on 2026-07-08 that baked a 4-commits-stale main-repo
# src/ into :20260708c (:latest), crashing the chained census gate on a 6h shadow rebuild and nearly shipping
# a serving image without the 6.5 route. Worktree-invoked builds now always package the worktree.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Write-Host "==> Build context: $RepoRoot" -ForegroundColor Cyan

$EcrBase     = "${AccountId}.dkr.ecr.${Region}.amazonaws.com"
$LatestImage = "${EcrBase}/${RepoName}:latest"
$TaggedImage = "${EcrBase}/${RepoName}:${Tag}"

# ---------------------------------------------------------------------------
# Step 1: Authenticate to ECR
# ---------------------------------------------------------------------------
Write-Host "==> Authenticating to ECR ($EcrBase)..." -ForegroundColor Cyan
# Note: --password-stdin via PowerShell pipe is unreliable on Windows; capture the token first.
$EcrToken = aws ecr get-login-password --region $Region
if ($LASTEXITCODE -ne 0) { throw "ecr get-login-password failed (exit $LASTEXITCODE)" }
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$null = docker login --username AWS --password $EcrToken $EcrBase 2>&1
$loginExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($loginExit -ne 0) { throw "ECR login failed (exit $loginExit)" }
Write-Host "ECR login succeeded." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 2: Build — must target linux/amd64 for Fargate (build host may differ)
# ---------------------------------------------------------------------------
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
    --file (Join-Path $RepoRoot "docker/leviathan_embedder/Dockerfile") `
    $RepoRoot 2>&1
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($buildExit -ne 0) { throw "docker build failed (exit $buildExit)" }

# ---------------------------------------------------------------------------
# Step 3: Tag with the extra label if one was requested
# ---------------------------------------------------------------------------
if ($Tag -ne "latest") {
    Write-Host "==> Tagging as $TaggedImage" -ForegroundColor Cyan
    docker tag $LatestImage $TaggedImage
    if ($LASTEXITCODE -ne 0) { throw "docker tag failed (exit $LASTEXITCODE)" }
}

# ---------------------------------------------------------------------------
# Step 4: Push
# ---------------------------------------------------------------------------
Write-Host "==> Pushing $LatestImage" -ForegroundColor Cyan
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
docker push $LatestImage 2>&1
$pushExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($pushExit -ne 0) { throw "docker push :latest failed (exit $pushExit)" }

if ($Tag -ne "latest") {
    Write-Host "==> Pushing $TaggedImage" -ForegroundColor Cyan
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    docker push $TaggedImage 2>&1
    $pushTagExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($pushTagExit -ne 0) { throw "docker push :$Tag failed (exit $pushTagExit)" }
}

Write-Host ""
Write-Host "==> Done. Image live in ECR:" -ForegroundColor Green
Write-Host "    $LatestImage" -ForegroundColor Green
if ($Tag -ne "latest") {
    Write-Host "    $TaggedImage" -ForegroundColor Green
}
Write-Host ""
Write-Host "New Batch tasks will pull :latest automatically on next run." -ForegroundColor DarkGray
