# Leviathan Terminal - production build + deploy to S3/CloudFront (Phase 4 Stage 3).
# ASCII-only stdout (Windows cp1252). Run from the repo root or apps/terminal.
#
#   pwsh apps/terminal/scripts/deploy.ps1
#   pwsh apps/terminal/scripts/deploy.ps1 -ApiBase https://api.leviathanconvexity.com
#   pwsh apps/terminal/scripts/deploy.ps1 -SkipGate      # EMERGENCY ONLY - see the banner it prints
#
# VITE_API_BASE is inlined at BUILD time (Vite), so it must be set before `vite build`.
#
# D-TW-20: the local gate (typecheck + lint + unit + e2e) runs BEFORE the build. A red tree must never
#          reach `vite build`, let alone S3.
# D-TW-21: bucket / distribution / Cognito config is READ FROM TERRAFORM OUTPUTS when they are available;
#          the parameter defaults below are the fallback, not the source of truth.
param(
    [string]$ApiBase   = "https://api.leviathanconvexity.com",
    [string]$Bucket    = "leviathan-dev-terminal-spa",
    [string]$Alias     = "leviathanconvexity.com",
    [string]$Region    = "us-east-1",
    # Cognito (Google sign-in). Authority = the user pool's OIDC issuer; client id from the app client;
    # domain = the hosted-UI domain (5.6: enables full hosted-UI sign-out).
    [string]$CognitoAuthority = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_H4Fv4Leik",
    [string]$CognitoClientId  = "2paur1lbb8c8fs2d15s2so5u50",
    [string]$CognitoDomain    = "leviathan-terminal.auth.us-east-1.amazoncognito.com",
    # Empty = resolve it (terraform output first, then the CloudFront alias lookup).
    [string]$DistributionId = "",
    # Empty = infra/terraform/envs/dev relative to this script.
    [string]$TerraformDir = "",
    # D-TW-20 emergency escape. Loudly logged; never the default path.
    [switch]$SkipGate
)
$ErrorActionPreference = "Stop"

# Resolve apps/terminal relative to this script.
$AppDir   = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RepoRoot = Split-Path -Parent (Split-Path -Parent $AppDir)
if ([string]::IsNullOrWhiteSpace($TerraformDir)) {
    $TerraformDir = Join-Path $RepoRoot "infra\terraform\envs\dev"
}
Write-Host "[deploy] app dir: $AppDir"

# ---------------------------------------------------------------------------------------------------
# 0) D-TW-20 GATE. The e2e specs and the unit suite exist; nothing ran them, so they were red for weeks
#    and every defect this wave fixed shipped past them. A gate that only runs in CI is advisory - this
#    one is the hard stop, at the one moment that matters: before anything is built or uploaded.
# ---------------------------------------------------------------------------------------------------
if ($SkipGate) {
    Write-Host ""
    Write-Host "[deploy] *****************************************************************************"
    Write-Host "[deploy] *** GATE SKIPPED (-SkipGate). This build is UNVERIFIED: no typecheck, no    ***"
    Write-Host "[deploy] *** lint, no unit tests, no e2e. Emergency path only - the next deploy      ***"
    Write-Host "[deploy] *** MUST run the gate, and whatever this ships is unproven until it does.   ***"
    Write-Host "[deploy] *****************************************************************************"
    Write-Host ""
} else {
    Push-Location $AppDir
    try {
        Write-Host "[deploy] gate 1/2: npm run ci (typecheck + lint + unit)"
        npm run ci
        if ($LASTEXITCODE -ne 0) { throw "GATE FAILED: npm run ci (typecheck / lint / unit) - REFUSING to build" }
        # The e2e webServer starts its OWN mock dev server on :5173 - except that playwright REUSES a server
        # already listening there. A hand-started `npm run dev` is not VITE_MOCK=1, so the specs would drive
        # a real backend and fail; stop it and re-run rather than reading the failure as a product defect.
        Write-Host "[deploy] gate 2/2: npx playwright test (mock-driven shell smoke)"
        npx playwright test
        if ($LASTEXITCODE -ne 0) {
            throw "GATE FAILED: playwright e2e - REFUSING to build. (missing browser -> npx playwright install --with-deps chromium; a non-mock dev server already on :5173 is reused and will fail the specs)"
        }
    } finally {
        Pop-Location
    }
    Write-Host "[deploy] gate PASS (typecheck + lint + unit + e2e)"
}

# ---------------------------------------------------------------------------------------------------
# 0b) D-TW-21 CONFIG FROM TERRAFORM. Every hand-pinned constant above is a second source of truth, and
#     its failure mode is not a broken deploy - it is a SUCCESSFUL deploy of the wrong config (a stale
#     Cognito client id fails only at a user's sign-in, hours later). So read the outputs terraform
#     already exposes, and fall back to the pins with a WARNING that names the risk.
#
#     Rules, in order:
#       - terraform is READ ONLY here (`output`), never plan/apply. Any failure is non-fatal.
#       - an EXPLICIT parameter always wins: -Bucket on the command line is an operator overriding this
#         on purpose, and terraform must not silently undo it.
#       - every resolved value must pass a shape check before it is used. A value that fails is treated
#         as drift and DISCARDED - notably the bucket, which must end in `-terminal-spa`: the root
#         `bucket_name` output is the DATA LAKE, and the `--delete` sync below aimed at it would prune it.
# ---------------------------------------------------------------------------------------------------
function Get-TfOutput {
    param([string]$Dir, [string]$Name)
    # Best-effort by contract: a missing output, an empty/locked state, or a terraform that errors all
    # return "". $ErrorActionPreference is relaxed INSIDE the call because PS 5.1 turns a native command's
    # redirected stderr into a terminating NativeCommandError under "Stop".
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & terraform "-chdir=$Dir" output -raw $Name 2>$null
        if ($LASTEXITCODE -ne 0) { return "" }
        $val = ($out | Select-Object -First 1)
        if ($null -eq $val) { return "" }
        return ([string]$val).Trim()
    } catch {
        return ""
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Resolve-TfValue {
    param(
        [string]$Dir,
        [string]$OutputName,
        [string]$Pattern,      # shape guard: a value that fails it is drift, not truth
        [string]$Fallback,     # the pinned constant
        [string]$Label,
        [switch]$StripScheme   # the cognito domain output is a URL; consumers want it bare
    )
    $shown = $Fallback
    if ([string]::IsNullOrWhiteSpace($shown)) { $shown = "(none pinned)" }
    $v = Get-TfOutput -Dir $Dir -Name $OutputName
    if ($StripScheme -and $v) {
        # module.cognito emits https://<prefix>.auth.<region>.amazoncognito.com, but VITE_COGNITO_DOMAIN is
        # consumed BARE (UserMenu builds `https://${domain}/logout`) - leaving the scheme on would produce
        # https://https://... and break sign-out only, silently, for signed-in users.
        $v = ($v -replace '^https?://', '').TrimEnd('/')
    }
    if ([string]::IsNullOrWhiteSpace($v)) {
        Write-Host "[deploy]   WARNING: terraform output '$OutputName' unreadable - keeping the pinned $Label ($shown). DRIFT RISK: if terraform moved this value, the deploy ships the OLD one."
        return $Fallback
    }
    if ($v -notmatch $Pattern) {
        Write-Host "[deploy]   WARNING: terraform '$OutputName' = '$v' fails its shape check ($Pattern) - DISCARDED, keeping $Label ($shown)."
        return $Fallback
    }
    if ($v -ne $Fallback) {
        Write-Host "[deploy]   $Label <- terraform: $v   [pinned default was $shown - DRIFT, terraform wins]"
    } else {
        Write-Host "[deploy]   $Label <- terraform: $v"
    }
    return $v
}

$tfWhy = ""
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    $tfWhy = "terraform is not on PATH"
} elseif (-not (Test-Path $TerraformDir)) {
    $tfWhy = "no terraform env dir at $TerraformDir"
} elseif (-not (Test-Path (Join-Path $TerraformDir "terraform.tfstate"))) {
    # State is LOCAL-ONLY in this repo (the 2026-08-01 truncation incident), so no local file = nothing to read.
    $tfWhy = "no local terraform.tfstate in $TerraformDir"
}

if ($tfWhy) {
    Write-Host "[deploy] WARNING: config NOT read from terraform ($tfWhy). Using the hand-pinned defaults in this script's param block."
    Write-Host "[deploy] WARNING: DRIFT RISK - if the SPA bucket, the distribution, or the Cognito pool/client/domain changed in terraform, this deploy ships stale config and the failure surfaces at a user's sign-in, not here."
} else {
    Write-Host "[deploy] reading config from terraform outputs ($TerraformDir)"
    if (-not $PSBoundParameters.ContainsKey("Bucket")) {
        $Bucket = Resolve-TfValue -Dir $TerraformDir -OutputName "terminal_spa_bucket_name" `
            -Pattern '\-terminal\-spa$' -Fallback $Bucket -Label "bucket"
    }
    if (-not $PSBoundParameters.ContainsKey("DistributionId")) {
        $DistributionId = Resolve-TfValue -Dir $TerraformDir -OutputName "terminal_spa_distribution_id" `
            -Pattern '^[A-Z0-9]{8,20}$' -Fallback $DistributionId -Label "distribution id"
    }
    if (-not $PSBoundParameters.ContainsKey("CognitoClientId")) {
        $CognitoClientId = Resolve-TfValue -Dir $TerraformDir -OutputName "cognito_app_client_id" `
            -Pattern '^[a-z0-9]{16,64}$' -Fallback $CognitoClientId -Label "cognito client id"
    }
    if (-not $PSBoundParameters.ContainsKey("CognitoDomain")) {
        $CognitoDomain = Resolve-TfValue -Dir $TerraformDir -OutputName "cognito_hosted_domain" -StripScheme `
            -Pattern '^[A-Za-z0-9][A-Za-z0-9\.\-]*\.[A-Za-z]{2,}$' -Fallback $CognitoDomain -Label "cognito domain"
    }
    if (-not $PSBoundParameters.ContainsKey("CognitoAuthority")) {
        # There is no `authority` output - it is the pool's OIDC issuer, DERIVED from the pool id. The
        # region embedded in the pool id must match -Region, else the issuer we build would name a pool
        # that does not exist in the region we are deploying to (an unsignable-in prod).
        $pool = Get-TfOutput -Dir $TerraformDir -Name "cognito_user_pool_id"
        if ($pool -match '^[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+$' -and $pool.Split("_")[0] -eq $Region) {
            $authority = "https://cognito-idp.$Region.amazonaws.com/$pool"
            if ($authority -ne $CognitoAuthority) {
                Write-Host "[deploy]   cognito authority <- terraform: $authority   [pinned default was $CognitoAuthority - DRIFT, terraform wins]"
            } else {
                Write-Host "[deploy]   cognito authority <- terraform: $authority"
            }
            $CognitoAuthority = $authority
        } elseif ($pool) {
            Write-Host "[deploy]   WARNING: terraform 'cognito_user_pool_id' = '$pool' is not a $Region pool id - DISCARDED, keeping $CognitoAuthority."
        } else {
            Write-Host "[deploy]   WARNING: terraform output 'cognito_user_pool_id' unreadable - keeping the pinned authority ($CognitoAuthority). DRIFT RISK as above."
        }
    }
}
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

# 3) Invalidate the entrypoint on CloudFront (assets are immutable, so only the shell needs it). D-TW-21:
#    the id comes from terraform (or -DistributionId); the alias scan is the fallback for when it does not.
if (-not [string]::IsNullOrWhiteSpace($DistributionId)) {
    $DistId = $DistributionId
} else {
    Write-Host "[deploy] no distribution id from terraform/param - falling back to the CloudFront alias scan"
    $DistId = (& aws cloudfront list-distributions --region $Region `
        --query "DistributionList.Items[?contains(Aliases.Items, '$Alias')].Id | [0]" --output text)
}
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
