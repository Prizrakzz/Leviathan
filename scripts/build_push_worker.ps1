<#
.SYNOPSIS
    Build the leviathan-worker Docker image and push it to ECR.

.DESCRIPTION
    Authenticates to ECR, builds the image for linux/amd64 (required for
    AWS Batch Fargate x86-64), tags it, and pushes to the dev repository.
    Always also tags as :latest so Batch job definitions pick it up.

.PARAMETER Tag
    Optional additional tag (e.g. a datestamp like "20260529"). Default: "latest" only.

.PARAMETER Region
    AWS region. Default: us-east-1.

.EXAMPLE
    .\scripts\build_push_worker.ps1
    .\scripts\build_push_worker.ps1 -Tag "20260529"
#>
param(
    [string]$Tag       = "latest",
    [string]$Region    = "us-east-1",
    [string]$AccountId = "668891723125",
    [string]$RepoName  = "leviathan-dev-leviathan-worker"
)

$ErrorActionPreference = "Stop"

$EcrBase    = "${AccountId}.dkr.ecr.${Region}.amazonaws.com"
$LatestImage = "${EcrBase}/${RepoName}:latest"
$TaggedImage = "${EcrBase}/${RepoName}:${Tag}"

# ---------------------------------------------------------------------------
# Step 1: Authenticate to ECR
# ---------------------------------------------------------------------------
Write-Host "==> Authenticating to ECR ($EcrBase)..." -ForegroundColor Cyan
# Note: --password-stdin via PowerShell pipe is unreliable on Windows;
# capture the token first and pass it directly instead.
$EcrToken = aws ecr get-login-password --region $Region
if ($LASTEXITCODE -ne 0) { throw "ecr get-login-password failed (exit $LASTEXITCODE)" }
docker login --username AWS --password $EcrToken $EcrBase 2>&1 | Where-Object { $_ -notmatch "WARNING" }
if ($LASTEXITCODE -ne 0) { throw "ECR login failed (exit $LASTEXITCODE)" }

# ---------------------------------------------------------------------------
# Step 2: Build — must target linux/amd64 for Fargate (build host may differ)
# ---------------------------------------------------------------------------
Write-Host "==> Building image: $LatestImage" -ForegroundColor Cyan
docker build `
    --platform linux/amd64 `
    --tag $LatestImage `
    --file docker/leviathan_worker/Dockerfile `
    .
if ($LASTEXITCODE -ne 0) { throw "docker build failed (exit $LASTEXITCODE)" }

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
docker push $LatestImage
if ($LASTEXITCODE -ne 0) { throw "docker push :latest failed (exit $LASTEXITCODE)" }

if ($Tag -ne "latest") {
    Write-Host "==> Pushing $TaggedImage" -ForegroundColor Cyan
    docker push $TaggedImage
    if ($LASTEXITCODE -ne 0) { throw "docker push :$Tag failed (exit $LASTEXITCODE)" }
}

Write-Host ""
Write-Host "==> Done. Image live in ECR:" -ForegroundColor Green
Write-Host "    $LatestImage" -ForegroundColor Green
if ($Tag -ne "latest") {
    Write-Host "    $TaggedImage" -ForegroundColor Green
}
Write-Host ""
Write-Host "New Batch tasks will pull :latest automatically on next run." -ForegroundColor DarkGray
