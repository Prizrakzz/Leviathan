<#
.SYNOPSIS
    P1 live-smoke: replay the teardown questions against PROD /v1/respond and check the Answer-Track-A
    invariants (answer-first, <=1 caveat, zero internal vocabulary, contract+structured populated where a
    contract routes). W4.3 of the P1 plan.

.DESCRIPTION
    Hits the REAL API host (api.leviathanconvexity.com) -- NOT the apex, which is the SPA CloudFront and
    HTML-fallbacks every /v1/* path to 200 (the smoke-the-wrong-host trap). /v1/respond is auth + quota gated,
    so a bearer token is required: pass -Token or set $env:LEVIATHAN_SMOKE_TOKEN (a Cognito id token from an
    authed browser session -> devtools -> the Authorization header on any /v1 call).

    Read-only except that each /v1/respond is one Bedrock turn (counts against the caller's daily quota).

.EXAMPLE
    $env:LEVIATHAN_SMOKE_TOKEN = "<id-token>"; .\scripts\prod_smoke.ps1
    .\scripts\prod_smoke.ps1 -Token "<id-token>" -BaseUrl "https://api.leviathanconvexity.com"
#>
param(
    [string]$Token   = $env:LEVIATHAN_SMOKE_TOKEN,
    [string]$BaseUrl = "https://api.leviathanconvexity.com",
    [string]$Asof    = "2026-07-06"
)

$ErrorActionPreference = "Stop"
if (-not $Token) { throw "No token. Pass -Token or set `$env:LEVIATHAN_SMOKE_TOKEN (Cognito id token)." }

# (question, expectMap): the four D3 teardown phrasings + the A4 context-commodity query + one genuinely-
# numeric regime-worded query. expectMap=$true means routing should resolve a contract + structured (map).
$Cases = @(
    @{ q = "how many weeks before the squeeze fires?";               map = $true  },
    @{ q = "what's corn's stocks-to-use threshold number?";          map = $true  },
    @{ q = "how many weeks before the regime breaks?";               map = $true  },
    @{ q = "what can affect barley or sunflower in america?";        map = $false },  # A4 context-node: linkage-first
    @{ q = "how convex is corn on a yield shock?";                   map = $true  }
)

# Internal vocabulary that must NEVER reach reader prose (mirror register.py detectors + the P1.1 phrases
# + the P9-A mentor-voice ban on plain mood words).
$LeakRx = '(?i)(causal graph|mapped graph|live-feature layer|silver numbers layer|dated evidence item|' +
          'the node fired|\bconf\s*=|\bsign\s*=|any_n_of|silver_ref|\b\w+_\w+_\w+\b|bullish_\w+|bearish_\w+|' +
          '\b(bullish|bearish)\b)'
# A rough caveat-sentence counter (the A1 "<=1 caveat" goal).
$CaveatRx = '(?i)(i can''?t confirm|not in the evidence|isn''?t available|no dated|cannot confirm|not available here|magnitude not)'

$hdr = @{ Authorization = "Bearer $Token" }
$pass = 0; $fail = 0
Write-Host "`nP1 live-smoke -> $BaseUrl  (asof $Asof)`n$('=' * 64)"

foreach ($c in $Cases) {
    $body = @{ question = $c.q; asof = $Asof } | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Uri "$BaseUrl/v1/respond" -Method Post -Headers $hdr -ContentType "application/json" -Body $body -TimeoutSec 120
    } catch {
        Write-Host ("[FAIL] {0}`n       request error: {1}" -f $c.q, $_.Exception.Message) -ForegroundColor Red
        $fail++; continue
    }
    $ans = "$($r.answer)"
    $tldr = "$($r.structured.tldr)"
    $contract = "$($r.contract)"
    $hasStructured = $null -ne $r.structured
    $leak = [regex]::Match($ans + " " + $tldr, $LeakRx)
    $caveats = ([regex]::Matches($ans, $CaveatRx)).Count
    $answerFirst = $tldr.Length -gt 0

    $problems = @()
    if ($leak.Success)                       { $problems += "internal-vocab leak: '$($leak.Value)'" }
    if ($caveats -gt 1)                       { $problems += "$caveats caveat sentences (>1)" }
    if (-not $answerFirst)                    { $problems += "no answer-first tldr" }
    if ($c.map -and (-not $hasStructured))    { $problems += "structured=null (map won't mount)" }
    if ($c.map -and (-not $contract))         { $problems += "contract=null (map won't mount)" }

    if ($problems.Count -eq 0) {
        Write-Host ("[PASS] {0}" -f $c.q) -ForegroundColor Green
        Write-Host ("       intent={0} contract={1} caveats={2}" -f $r.intent, $contract, $caveats)
        $pass++
    } else {
        Write-Host ("[FAIL] {0}" -f $c.q) -ForegroundColor Red
        $problems | ForEach-Object { Write-Host "       - $_" -ForegroundColor Red }
        $fail++
    }
}

Write-Host ("`n{0}`nP1 smoke: {1} passed, {2} failed`n" -f ('=' * 64), $pass, $fail)
if ($fail -gt 0) { exit 1 }
