# Leviathan Terminal - production build + deploy to S3/CloudFront (Phase 4 Stage 3).
# ASCII-only stdout (Windows cp1252). Run from the repo root or apps/terminal.
#
#   pwsh apps/terminal/scripts/deploy.ps1
#   pwsh apps/terminal/scripts/deploy.ps1 -ApiBase https://api.leviathanconvexity.com
#
# VITE_API_BASE is inlined at BUILD time (Vite), so it must be set before `vite build`.
param(
    [string]$ApiBase   = "https://api.leviathanconvexity.com",
    [string]$Bucket    = "leviathan-dev-terminal-spa",
    [string]$Alias     = "leviathanconvexity.com",
    [string]$Region    = "us-east-1",
    # Cognito (Google sign-in). Authority = the user pool's OIDC issuer; client id from the app client;
    # domain = the hosted-UI domain (5.6: enables full hosted-UI sign-out).
    [string]$CognitoAuthority = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_H4Fv4Leik",
    [string]$CognitoClientId  = "2paur1lbb8c8fs2d15s2so5u50",
    [string]$CognitoDomain    = "leviathan-terminal.auth.us-east-1.amazoncognito.com"
)
$ErrorActionPreference = "Stop"

# Resolve apps/terminal relative to this script.
$AppDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Write-Host "[deploy] app dir: $AppDir"
Write-Host "[deploy] API base: $ApiBase   bucket: $Bucket"

# 1) Production build (real backend, no mock). VITE_* are inlined at build time.
$env:VITE_API_BASE = $ApiBase
$env:VITE_MOCK = "0"
$env:VITE_COGNITO_AUTHORITY = $CognitoAuthority
$env:VITE_COGNITO_CLIENT_ID = $CognitoClientId
$env:VITE_COGNITO_REDIRECT_URI = "https://$Alias/auth/callback"
$env:VITE_COGNITO_DOMAIN = $CognitoDomain
Push-Location $AppDir
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "vite build failed" }
} finally {
    Pop-Location
}
$Dist = Join-Path $AppDir "dist"
if (-not (Test-Path (Join-Path $Dist "index.html"))) { throw "no dist/index.html - build did not emit" }

# 1b) D-TW-3b BUNDLE GUARD: refuse to ship a config-less build. The 2026-07-12 incident shipped a
# bundle built without VITE_* (bare `npm run build`): API base fell back to same-origin (CloudFront
# rewrote every /v1/* call to 200+index.html) and authEnabled=false removed the login wall. The env
# vars are inlined at build time, so their VALUES must be present in the emitted chunks - if either
# is missing, this build is the incident class, not a deployable artifact.
$ApiHost = ([uri]$ApiBase).Host
$chunkDir = Join-Path $Dist "assets"
$hasApi     = [bool](Select-String -Path (Join-Path $chunkDir "*.js") -Pattern ([regex]::Escape($ApiHost)) -Quiet)
$hasCognito = [bool](Select-String -Path (Join-Path $chunkDir "*.js") -Pattern ([regex]::Escape($CognitoClientId)) -Quiet)
if (-not $hasApi)     { throw "BUNDLE GUARD: built chunks do not contain the API host '$ApiHost' - VITE_API_BASE was not baked. REFUSING to deploy (the 2026-07-12 incident class)." }
if (-not $hasCognito) { throw "BUNDLE GUARD: built chunks do not contain the Cognito client id - VITE_COGNITO_* were not baked (authEnabled would be false in prod). REFUSING to deploy." }
Write-Host "[deploy] bundle guard PASS: API host + Cognito client id present in emitted chunks"

# 2) ATOMIC UPLOAD ORDER (S2.1): hashed assets FIRST, then verify every built asset is actually at the
#    origin, and ONLY THEN flip index.html. The old order (index first, assets after) left a ~40-60s window
#    where the new index referenced a chunk the origin lacked -> the SPA 403/404->index.html rewrite handed
#    the dynamic import HTML-with-200 instead of JS -> the lazy chunk load rejected -> blank screen.
Write-Host "[deploy] syncing assets (immutable) FIRST"
& aws s3 sync "$Dist/assets/" "s3://$Bucket/assets/" `
    --cache-control "public,max-age=31536000,immutable" --region $Region
if ($LASTEXITCODE -ne 0) { throw "s3 sync (assets) failed" }

# Completeness gate: every asset in the new build must exist at the origin before the shell flips. Guards a
# partial sync AND S3 read-after-write lag (short retry). A miss here means the flip would strand a chunk.
$assets = Get-ChildItem -File "$Dist/assets"
Write-Host "[deploy] verifying $($assets.Count) assets at the origin before flipping the shell"
foreach ($a in $assets) {
    $key = "assets/$($a.Name)"
    $ok = $false
    for ($try = 1; $try -le 3; $try++) {
        aws s3api head-object --bucket $Bucket --key $key --region $Region *> $null
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ok) { throw "asset missing at origin after sync: $key (aborting BEFORE flipping index.html)" }
}
Write-Host "[deploy] all assets present at origin"

# Now the shell: index.html + mark.svg etc. are no-cache so a new deploy surfaces immediately. --delete
# prunes stale non-asset files (never assets -> in-flight users on the old index keep their immutable chunks).
Write-Host "[deploy] flipping shell (no-cache, --delete, excluding assets)"
& aws s3 sync "$Dist/" "s3://$Bucket/" --delete --exclude "assets/*" `
    --cache-control "no-cache" --region $Region
if ($LASTEXITCODE -ne 0) { throw "s3 sync (root) failed" }

# 3) Invalidate the entrypoint on CloudFront (assets are immutable, so only the shell needs it).
$DistId = (& aws cloudfront list-distributions --region $Region `
    --query "DistributionList.Items[?contains(Aliases.Items, '$Alias')].Id | [0]" --output text)
if ([string]::IsNullOrWhiteSpace($DistId) -or $DistId -eq "None") {
    throw "could not find CloudFront distribution for alias $Alias"
}
Write-Host "[deploy] invalidating distribution $DistId"
& aws cloudfront create-invalidation --distribution-id $DistId --paths "/" "/index.html" `
    --region $Region --query "Invalidation.Id" --output text
if ($LASTEXITCODE -ne 0) { throw "cloudfront invalidation failed" }

Write-Host "[deploy] DONE at https://$Alias"

# 4) D-TW-2 POST-DEPLOY SMOKE - a deploy that cannot prove itself green prints why and FAILS.
#    (a) the live shell must reference a chunk that carries the baked API host (proves the flip landed);
#    (b) the API origin must answer 401 JSON anonymously (proves the backend contract the bundle needs).
Write-Host "[verify] fetching live index.html"
$idx = (Invoke-WebRequest -Uri "https://$Alias/?smoke=$(Get-Random)" -UseBasicParsing -TimeoutSec 30).Content
if ($idx -notmatch '/assets/(index-[A-Za-z0-9_-]+\.js)') { throw "VERIFY: live index.html references no main chunk" }
$mainChunk = $Matches[1]
$localChunk = Join-Path $chunkDir $mainChunk
if (-not (Test-Path $localChunk)) { throw "VERIFY: live shell references $mainChunk which is NOT in this build's dist/ - the flip did not land (stale index still served?)" }
Write-Host "[verify] live shell references this build's chunk: $mainChunk (flip landed; bundle guard already proved its contents)"
try {
    $probe = Invoke-WebRequest -Uri "$ApiBase/v1/profile" -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
    throw "VERIFY: anonymous $ApiBase/v1/profile returned HTTP $($probe.StatusCode) - expected 401. The API origin is NOT enforcing auth (or is serving HTML)."
} catch [System.Net.WebException] {
    $resp = $_.Exception.Response
    if (-not $resp) { throw "VERIFY: could not reach $ApiBase/v1/profile at all: $($_.Exception.Message)" }
    $code = [int]$resp.StatusCode
    $ct = $resp.ContentType
    if ($code -ne 401) { throw "VERIFY: anonymous /v1/profile returned $code (expected 401)" }
    if ($ct -notlike "*json*") { throw "VERIFY: /v1/profile 401 content-type is '$ct' (expected JSON)" }
    Write-Host "[verify] API origin PASS: anonymous /v1/profile -> 401 $ct"
}
Write-Host "[verify] SMOKE PASS - deploy is proven, not presumed"
