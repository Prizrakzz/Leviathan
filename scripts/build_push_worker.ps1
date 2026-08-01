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
    [string]$RepoName  = "leviathan-dev-leviathan-worker",
    [switch]$ForceAmd64Platform
)

$ErrorActionPreference = "Stop"

# SILVER-F085 (2026-07-23): NEVER push :latest-only. A latest-only image loses its tag when the
# next push steals :latest; digest-pinned Batch jobdefs then reference an UNTAGGED image that ECR
# lifecycle rules may expire (this broke the 14:00 UTC usda_esr run and stranded 16 jobdef
# families on deleted digests). Every push therefore carries a durable datestamp tag: auto-derived
# here whenever -Tag was omitted/left as "latest".
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
# Suppress stderr (docker --password warning) without tripping PowerShell NativeCommandError
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
# NEVER read its own commit at runtime -- it has to be told at build time. Without this every
# container is anonymous, which is why the 2026-07-24 gate log could not say "I am e0a33bf2".
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
    --file (Join-Path $RepoRoot "docker/leviathan_worker/Dockerfile") `
    $RepoRoot 2>&1
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($buildExit -ne 0) { throw "docker build failed (exit $buildExit)" }

# ---------------------------------------------------------------------------
# Step 3a: RUNTIME-CLOSURE SMOKE (SILVER-F085 family, 2026-07-24). Three prod
# incidents in one night came from images that BUILT fine but lacked what the
# shared silver-gate step needs at RUNTIME (psycopg via the pg extra; the
# sql/athena/ddl tree for the node_silver_map lint) -- old images had them only
# through STALE cached layers, so the first honest rebuild broke the 14:00 UTC
# fires. A broken image must fail HERE, never in a scheduled gate.
# ---------------------------------------------------------------------------
Write-Host "==> Runtime-closure smoke (psycopg + sql/ + gate imports)..." -ForegroundColor Cyan
docker run --rm --entrypoint python $LatestImage -c "import os, psycopg; assert os.path.isdir('sql/athena/ddl') and os.listdir('sql/athena/ddl'), 'sql/athena/ddl missing/empty'; assert os.path.isdir('configs/silver/tables'), 'configs missing'; import importlib; importlib.import_module('jobs.audit.silver_rebuild_gate'); importlib.import_module('jobs.audit.value_census'); print('closure smoke OK: psycopg', psycopg.__version__)"
if ($LASTEXITCODE -ne 0) { throw "runtime-closure smoke FAILED (exit $LASTEXITCODE) -- image would break the scheduled silver-gate; NOT pushing" }

# ---------------------------------------------------------------------------
# Step 3b: IMAGE-MANIFEST SMOKE (FENCE, incident I-1). An image that would be
# pushed UNSTAMPED, or stamped against a different tree than it actually
# COPYed, is refused here -- it would be an anonymous container all over again,
# and the fleet auditor (check_ecr_pinned_digests.py --config-drift) would have
# no sidecar to read. Asserts the manifest EXISTS and that its
# silver_tables_fp equals a fingerprint computed on the HOST tree.
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
# Step 5: MANIFEST SIDECAR (FENCE, incident I-1). Publish this image's baked
# provenance to S3 keyed by its PUSHED DIGEST, so the fleet auditor
# (scripts/ops/check_ecr_pinned_digests.py --config-drift) can answer "what
# configs did the digest this jobdef is pinned to actually bake?" WITHOUT
# pulling layers. One ~4 KB PUT. Non-fatal: the image is already live and the
# in-container preflight does not depend on this -- a missing sidecar is
# reported by the auditor as UNKNOWN PROVENANCE (treated as stale), never as OK.
# ---------------------------------------------------------------------------
$PushedDigest = docker inspect --format '{{index .RepoDigests 0}}' $LatestImage
if ($LASTEXITCODE -eq 0 -and $PushedDigest -and $PushedDigest.Contains("@sha256:")) {
    # .Split(string) treats the arg as a CHAR SET (this mangled every sidecar key until 2026-08-02);
    # split on the single '@' -- the tail is already "sha256:<64hex>".
    $Digest = $PushedDigest.Split('@')[-1]
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
