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

# 2) Upload. Hashed assets are immutable (1yr); everything else (index.html, mark.svg) is no-cache
#    so a new deploy surfaces immediately. --delete on the root pass prunes stale non-asset files.
Write-Host "[deploy] syncing root (no-cache, --delete, excluding assets)"
& aws s3 sync "$Dist/" "s3://$Bucket/" --delete --exclude "assets/*" `
    --cache-control "no-cache" --region $Region
if ($LASTEXITCODE -ne 0) { throw "s3 sync (root) failed" }

Write-Host "[deploy] syncing assets (immutable)"
& aws s3 sync "$Dist/assets/" "s3://$Bucket/assets/" `
    --cache-control "public,max-age=31536000,immutable" --region $Region
if ($LASTEXITCODE -ne 0) { throw "s3 sync (assets) failed" }

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
