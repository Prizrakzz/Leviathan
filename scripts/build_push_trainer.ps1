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
    [string]$RepoName  = "leviathan-dev-leviathan-trainer"
)

$ErrorActionPreference = "Stop"

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
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
docker build `
    --platform linux/amd64 `
    --tag $LatestImage `
    --file docker/leviathan_trainer/Dockerfile `
    . 2>&1
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
