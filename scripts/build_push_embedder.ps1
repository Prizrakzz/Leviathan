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

# SILVER-F085 (2026-07-23): NEVER push :latest-only. A latest-only image loses its tag when the
# next push steals :latest; digest-pinned jobdefs/taskdefs then reference an UNTAGGED image that
# ECR lifecycle rules may expire (broke the 14:00 UTC usda_esr run; 16 jobdef families stranded).
# Every push therefore carries a durable datestamp tag, auto-derived when -Tag was omitted.
if ($Tag -eq "latest") {
    $Tag = Get-Date -Format "yyyyMMddTHHmmss"
    Write-Host "==> No -Tag given: auto-datestamp tag '$Tag' (latest-only pushes are banned)" -ForegroundColor Yellow
}

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
# FENCE (incident I-1): inject the build provenance. .dockerignore excludes .git, so the image can
# NEVER read its own commit at runtime. This image runs the MANUAL silver-gate path
# (jobs/submit/submit_batch_silver_rebuild_gate.py:34 -> leviathan-dev-evidence-build).
$BuildCommit = (git -C $RepoRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or -not $BuildCommit) { throw "git rev-parse HEAD failed -- refusing to build an anonymous image" }
$BuildCommit = $BuildCommit.Trim()
$BuildTime   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$StampArgs   = @("--build-arg", "BUILD_GIT_COMMIT=$BuildCommit", "--build-arg", "BUILD_TIME=$BuildTime")
Write-Host "    Stamping image: commit=$BuildCommit built=$BuildTime" -ForegroundColor DarkGray

$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
docker build `
    @PlatformArgs `
    @StampArgs `
    --tag $LatestImage `
    --file (Join-Path $RepoRoot "docker/leviathan_embedder/Dockerfile") `
    $RepoRoot 2>&1
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($buildExit -ne 0) { throw "docker build failed (exit $buildExit)" }

# ---------------------------------------------------------------------------
# IMAGE-MANIFEST smoke (FENCE, incident I-1). Same contract as the worker
# script: refuse to push an UNSTAMPED image, or one stamped against a tree it
# did not actually COPY. Kept identical on purpose -- the two build scripts
# drifting is exactly how half a fence ends up shipping, which is why
# tests/unit/test_image_config_fence.py::test_build_scripts_assert_manifest
# regexes BOTH files.
# ---------------------------------------------------------------------------
Write-Host "==> IMAGE_MANIFEST smoke (provenance stamp + host-vs-container fingerprint)..." -ForegroundColor Cyan
$HostFp = python -c "import sys; sys.path.insert(0, sys.argv[1]); from leviathan.common.image_stamp import fingerprint_dir; import os; print(fingerprint_dir(os.path.join(sys.argv[2],'configs','silver','tables'))[1])" (Join-Path $RepoRoot "src") $RepoRoot
if ($LASTEXITCODE -ne 0 -or -not $HostFp) { throw "host fingerprint failed -- cannot verify IMAGE_MANIFEST" }
$HostFp = $HostFp.Trim()
docker run --rm --entrypoint python $LatestImage -c "import json,sys; m=json.load(open('/app/IMAGE_MANIFEST.json')); assert m.get('git_commit') and m['git_commit']!='unknown', 'IMAGE_MANIFEST git_commit is unknown -- build-arg not injected'; assert m['silver_tables_fp']==sys.argv[1], 'baked fp %s != host fp %s -- the image COPYed a different tree than was stamped' % (m['silver_tables_fp'], sys.argv[1]); print('manifest OK commit=%s built=%s silver_tables=%d fp=%s' % (m['git_commit'][:8], m['build_time_utc'], m['silver_tables_count'], m['silver_tables_fp']))" $HostFp
if ($LASTEXITCODE -ne 0) { throw "IMAGE_MANIFEST smoke FAILED (exit $LASTEXITCODE) -- image is unstamped or stamped against the wrong tree; NOT pushing" }

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

# ---------------------------------------------------------------------------
# MANIFEST SIDECAR (FENCE, incident I-1) -- see build_push_worker.ps1 Step 5.
# ---------------------------------------------------------------------------
$PushedDigest = docker inspect --format '{{index .RepoDigests 0}}' $LatestImage
if ($LASTEXITCODE -eq 0 -and $PushedDigest -and $PushedDigest.Contains("@sha256:")) {
    $Digest = "sha256:" + $PushedDigest.Split("@sha256:")[-1]
    $SidecarKey = "image_manifests/${RepoName}/" + $Digest.Replace(":", "_") + ".json"
    $TmpManifest = Join-Path $env:TEMP "IMAGE_MANIFEST_$Tag.json"
    docker run --rm --entrypoint cat $LatestImage /app/IMAGE_MANIFEST.json | Out-File -FilePath $TmpManifest -Encoding utf8
    if ($LASTEXITCODE -eq 0) {
        aws s3 cp $TmpManifest "s3://leviathan-dev-shahem-001/$SidecarKey" --region $Region
        if ($LASTEXITCODE -eq 0) {
            Write-Host "==> Manifest sidecar: s3://leviathan-dev-shahem-001/$SidecarKey" -ForegroundColor Green
        } else {
            Write-Host "WARN: manifest sidecar PUT failed -- the auditor will treat $Digest as UNKNOWN PROVENANCE" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "WARN: could not resolve pushed digest -- no manifest sidecar written" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==> Done. Image live in ECR:" -ForegroundColor Green
Write-Host "    $LatestImage" -ForegroundColor Green
if ($Tag -ne "latest") {
    Write-Host "    $TaggedImage" -ForegroundColor Green
}
Write-Host ""
Write-Host "New Batch tasks will pull :latest automatically on next run." -ForegroundColor DarkGray
