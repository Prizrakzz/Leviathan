# S3 Data Gap Audit & Remediation Plan
*Initial audit: 2026-05-21 | Corrected recursive inspection: 2026-05-21*

---

## Part 1 — Corrected Source Inventory

> **Note on prior estimates**: The original audit estimated several sources as "essentially empty" based on top-level S3 folder counts rather than recursive file counts. The table below reflects actual recursive file counts from `aws s3 ls --recursive`.

### All Sources — True State

| Source | Recursive Files | Date Range | True Status |
|--------|----------------|------------|-------------|
| `usda_wasde` | **185** | 1973–1989, 1995 (Jan–Mar), 2024 (Jan–Mar) | 🔴 **441/626 missing** |
| `sagis_cec` | **3** | 2026 Mar–May only | 🔴 **~355 historical files missing** |
| `mpob` | **18** | Annual 2017–2026, PDFs 2010–2016, 1 monthly | 🟡 **119 monthly releases missing (2017–2026)** |
| `unica` | **41** | 1980/81 – 2020/21 | 🟡 **5 recent harvest years missing (2021–2026)** |
| `unica_biweekly` | **49** | 2012–2013, 2020–2026 (6 seasons) | 🟡 **2021/22 season absent from S3** |
| `faostat` | **2** | One QCL zip (duplicated) | 🟡 **Only QCL; FBS/Trade datasets absent** |
| `conab` | **57** | 2009/10 – 2025/26 | 🟢 Reasonable; some sparse early surveys |
| `fnc` | **58** | 2024–2026 cifras + exportaciones PDFs | 🟢 Covers available online archive |
| `mpoc` | **355** | Competitive prices + trade stats to 2023 | 🟢 Substantially present |
| `sagis_swb` | **707** | 2024–2026 monthly PDFs | 🟢 Present (pre-2024 not online) |
| `sagis_weekly` | **138** | Historical maize/wheat datasets | 🟢 Present |
| `usda_ams_cotton_classing` | **27** | Annual quality 1986–2025 | 🟢 Complete historical series |
| `usda_nass` | **1** | `qs.crops.txt.gz` 1.1 GB bulk | 🟢 Complete bulk download ✓ |
| `usda_nass_citrus` | **372** | Annual stats + monthly forecasts 2008–2025 | 🟢 Good coverage |
| `usda_psd` | **1** | `psd_alldata.zip` 10 MB bulk | 🟢 Complete historical database ✓ |
| `usda_fas_coffee_wmt` | **47** | Biannual circulars 2004–2025 | 🟢 Complete series |
| `usda_gain_sugar` | **885** | 1998–2026 | 🟢 Complete ✓ |
| `usda_gain_cotton` | **866** | 1998–2026 | 🟢 Complete ✓ |
| `usda_gain_wheat` | **16** | 2026 only (8 dupes) | 🔴 **Missing 2010–2025 + FR RU CN DE PL** |
| `usda_gain_corn` | **6** | 2026 only (3 dupes) | 🔴 **Missing 2010–2025 + CN ZA MX PH NG FR** |
| `usda_gain_soybeans` | **6** | 2026 only (3 dupes) | 🔴 **Missing 2010–2025 + BR US CN IN BO** |
| `usda_gain_palm_oil` | **4** | 2026 only, ID+TH only | 🔴 **MY absent; historical missing** |
| `usda_gain_rapeseed` | **6** | 2026 only (3 dupes) | 🔴 **Missing 2010–2025 + FR CN DE PL** |
| `usda_gain_rice` | **8** | 2026 only (4 dupes) | 🔴 **Missing 2010–2025 + ID CN** |
| `usda_gain_soybean_oil` | **1** | 2026 only, PY only | 🔴 **Wrong commodity_id; all major origins missing** |
| `usda_gain_soybean_meal` | **3** | 2025–2026, ID+PH+VN only | 🔴 **Wrong commodity_id; most origins missing** |
| `usda_gain_orange_juice` | **4** | 2025 only, BR MX TR ZA | 🔴 **Historical cut off; 9 countries missing** |
| `usda_gain_cocoa` | **5** | 2025 only, BR CI GH | 🔴 **Historical cut off; 10 countries missing** |
| `usda_gain_coffee` | **64** | Historical (some) BR CI CO | 🟡 **ET VN ID HN GT PE UG TZ missing** |

---

## Part 2 — Root Causes

### WASDE: Upload Job Stopped Prematurely
The manifest (`configs/sources/usda_wasde_manifest.yaml`) has all 626 release URLs, but the upload job only processed ~185. The 1990–2023 era (including the entire digital PDF era 2000–2023) was never uploaded. Fix: re-run `fetch_usda_wasde.py --skip-existing-s3`.

### SAGIS CEC: Only Latest Releases Fetched
The script discovers reports dynamically from SAGIS's WordPress API. The manifest was only written for 3 files. The entire 1999–2025 archive (~355 PDFs/DOCs) was never fetched. Fix: re-run `fetch_sagis_cec.py --skip-existing-s3`.

### MPOB: Manifest Contains Only 18 Entries
`fetch_mpob.py` reads only from `configs/sources/mpob_archive.yaml`. The manifest has annual summaries for 2017–2026, overview PDFs for 2010–2016, and only one monthly release (April 2026). Monthly releases for Jan 2017 – Mar 2026 (~119 months) follow a deterministic URL pattern and need to be added to the manifest before re-running.

### UNICA Annual: Config Stops at 2020/21
`configs/sources/unica_sources.yaml` lists harvest years only up to 2020/2021. Years 2021/22 through 2025/26 must be appended to the config, then re-run.

### UNICA Biweekly: 2021/22 Season Listed but Never Ingested
`configs/sources/unica_biweekly_sources.yaml` includes 2021/2022 but it was never discovered or uploaded. Re-run with `--discover` for that season.

### GAIN Shallow Coverage — Three Interlocking Issues
1. **Commodity ID temporal asymmetry**: Sugar (34) and cotton (6) are legacy taxonomy IDs FAS applied retroactively to reports back to 1998. Wheat (15), corn (14), soybeans (27), rapeseed (28), rice (16) are only tagged on very recent uploads — the Batch task correctly uses these IDs but can only find 2026 reports.
2. **13021/13022 too granular**: Soybean meal and oil subcategory IDs are rarely tagged on actual "Oilseeds and Products Annual" attaché reports. Those reports use commodity_id=27 (oilseeds general). Fix: switch to commodity_id=27 for both.
3. **max_empty_pages cuts off scattered history**: Cocoa and OJ use title-keyword crawls scanning ALL GAIN reports newest-first. After 200 consecutive non-matching pages the crawl stops — but pre-2024 reports lie thousands of pages back. Fix: increase max_empty_pages to 2000+.

---

## Phase 1 — Execute Existing Infrastructure
*Zero new code. Run existing fetch scripts with correct arguments.*

### P1-A · WASDE Full Backfill

**Gap**: 441/626 releases missing. Entire 1990–1994, 1996–2023, and 2025–2026 eras absent.

**Command**:
```bash
python jobs/ingest/fetch_usda_wasde.py --skip-existing-s3
```

**Expected outcome**: ~441 new files. Final count ≥ 626 objects under `raw/production/source=usda_wasde/`.

**Verification**:
```powershell
# 1. Total file count (must be ≥ 626)
$files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_wasde/" --recursive --region us-east-1 2>&1
Write-Host "Total WASDE files: $($files.Count)  (need ≥ 626)"

# 2. Per-decade checks — expect entries in every decade
foreach ($decade in @("release_date=199","release_date=200","release_date=201","release_date=202")) {
    $n = ($files | Where-Object { $_ -match $decade }).Count
    Write-Host "  ${decade}x: $n files"
}

# 3. Spot-check a known-missing release (e.g., March 2005)
$mar05 = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_wasde/" --recursive --region us-east-1 2>&1 | Where-Object { $_ -match "2005-03" }
Write-Host "March 2005: $($mar05.Count) file(s)"

# 4. Validate a file is non-trivially large (real WASDE PDFs ≥ 500 KB; TXTs ≥ 20 KB)
$files | Sort-Object | Select-Object -First 3 | ForEach-Object { Write-Host $_ }
```

**Failure signals**: Count < 600, any decade returning 0, any file < 20,000 bytes.

---

### P1-B · SAGIS CEC Historical Backfill

**Gap**: 3/~358 historical crop estimates committee reports. Only March–May 2026 present; 1999–2025 archive missing.

**Command**:
```bash
python jobs/ingest/fetch_sagis_cec.py --skip-existing-s3 --newest-first
```

The script discovers all historical report URLs live from the SAGIS WordPress API — no manifest rebuild required.

**Expected outcome**: ~355 additional files. Final count ≥ 355 under `raw/production/source=sagis_cec/`.

**Verification**:
```powershell
# 1. Total count (expect 355+)
$cec = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=sagis_cec/" --recursive --region us-east-1 2>&1
Write-Host "Total CEC files: $($cec.Count)  (need ≥ 300)"

# 2. Earliest file must be ~1999 (not 2026)
$cec | Sort-Object | Select-Object -First 5

# 3. File format distribution (PDF, DOC, XLS all expected across the 27-year archive)
Write-Host "PDFs: $(($cec | Where-Object { $_ -match '\.pdf' }).Count)"
Write-Host "DOCs: $(($cec | Where-Object { $_ -match '\.doc' }).Count)"
Write-Host "XLSs: $(($cec | Where-Object { $_ -match '\.xls' }).Count)"

# 4. Pre-2010 files must exist
$pre2010 = ($cec | Where-Object { $_ -match "CEC_200[0-9]|CEC_199" }).Count
Write-Host "Pre-2010 files: $pre2010  (need > 0)"
```

**Failure signals**: Count < 100, no pre-2010 files, zero DOC or XLS files (they are expected for 2001–2009 era).

---

### P1-C · MPOB Monthly Releases (2017–2026)

**Gap**: Only April 2026 present. Monthly releases for January 2017 – March 2026 (~119 pages) absent.

**Step 1 — Expand the manifest** (run from repo root):
```python
import yaml
from pathlib import Path

manifest_path = Path("configs/sources/mpob_archive.yaml")
data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

existing = {
    (r["release_type"], r["year"], r.get("month"))
    for r in data["releases"]
}

new_entries = []
for year in range(2017, 2027):
    for month in range(1, 13):
        if year == 2026 and month > 4:
            break  # data not yet published beyond April 2026
        if ("monthly_release", year, month) not in existing:
            new_entries.append({
                "release_type": "monthly_release",
                "year": year,
                "month": month,
                "stat_url": f"https://bepi.mpob.gov.my/stat/web_report1.php?val={year}75&val1={month:02d}",
            })

data["releases"].extend(new_entries)
manifest_path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(f"Added {len(new_entries)} monthly entries to manifest")
```

**Step 2 — Smoke test (1 file)**:
```bash
python jobs/ingest/fetch_mpob.py --release-type monthly_release --limit 1 --dry-run
python jobs/ingest/fetch_mpob.py --release-type monthly_release --limit 1
```

**Step 3 — Full run**:
```bash
python jobs/ingest/fetch_mpob.py --skip-existing-s3 --release-type monthly_release
```

**Expected outcome**: ~119 monthly HTML pages under `raw/production/source=mpob/release_type=monthly_release/`.

**Verification**:
```powershell
# 1. Count monthly releases (expect ~120)
$monthly = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=mpob/release_type=monthly_release/" --recursive --region us-east-1 2>&1
Write-Host "Monthly releases: $($monthly.Count)  (need ≥ 100)"

# 2. Every year 2017–2026 must have entries
for ($y = 2017; $y -le 2026; $y++) {
    $n = ($monthly | Where-Object { $_ -match "year=$y/" }).Count
    $expected = if ($y -eq 2026) { 4 } else { 12 }
    $status = if ($n -ge $expected) { "OK" } else { "INCOMPLETE" }
    Write-Host "  $y: $n months ($status, expect $expected)"
}

# 3. Sample download a file to confirm it contains the validation string
aws s3 cp "s3://leviathan-dev-shahem-001/raw/production/source=mpob/release_type=monthly_release/year=2020/month=06/mpob_monthly_2020_06.html" - 2>&1 | Select-String "CRUDE PALM OIL"
```

**Failure signals**: Count < 100, any year 2017–2025 with < 12 months, HTML file missing "CRUDE PALM OIL".

---

### P1-D · UNICA Annual Data — Recent Harvest Years

**Gap**: `configs/sources/unica_sources.yaml` stops at 2020/2021. Missing: 2021/22, 2022/23, 2023/24, 2024/25, 2025/26.

**Step 1 — Update config**. In `configs/sources/unica_sources.yaml`, append to `harvest_years`:
```yaml
  - "2021/2022"
  - "2022/2023"
  - "2023/2024"
  - "2024/2025"
  - "2025/2026"
```

**Step 2 — Run fetch**:
```bash
python jobs/ingest/fetch_unica.py --skip-existing-s3
```

**Expected outcome**: 5 new HTML pages (one per season).

**Verification**:
```powershell
# 1. Total season count (expect 46)
$unica = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=unica/" --region us-east-1 2>&1
Write-Host "UNICA seasons: $($unica.Count)  (need 46)"

# 2. Each new season has exactly 1 file ≥ 20 KB
foreach ($yr in @("2021_2022","2022_2023","2023_2024","2024_2025","2025_2026")) {
    $result = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=unica/harvest_year=$yr/" --recursive --region us-east-1 2>&1
    Write-Host "  $yr: $($result.Count) file(s)"
    $result | ForEach-Object { Write-Host "    $_" }
}
```

---

### P1-E · UNICA Biweekly — 2021/22 Season ✅ CLOSED — Permanently Unavailable

**Finding**: Exhaustive search confirmed 2021/22 biweekly bulletins are inaccessible from all sources:
- Wayback Machine CDX has **zero** `arquivos/pdfs/2021/` or `2022/01-03/` entries.
- The two `download_media.php` IDs captured by Wayback during the 2021/22 window (2022-01-20)
  both return empty responses — the files were deleted from the live server.
- The UNICADATA listing page (`listagem.php?idMn=63`) now shows only the most recent bulletin
  with **no harvest-year dropdown** — no historical navigation exists at all.

**Resolution**: Removed `"2021/2022"` from `configs/sources/unica_biweekly_sources.yaml`.
The Playwright timeout was improved (30s networkidle → 60s domcontentloaded + 5s settle)
as a side-effect fix.

**Note**: `unica_biweekly_sources.yaml` note updated; manifest unchanged (no 2021/22 entries).

---

### P1-F · CONAB — Confirm All Surveys Present

**Context**: 57 files already present (2009/10 – 2025/26). Run all three CONAB scripts with `--skip-existing-s3` to pick up any surveys in the manifest that weren't uploaded.

**Commands**:
```bash
python jobs/ingest/fetch_conab.py --skip-existing-s3
python jobs/ingest/fetch_conab_bulletin_xls.py --skip-existing-s3
python jobs/ingest/fetch_conab_historical.py --skip-existing-s3
```

**Verification**:
```powershell
$conab = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=conab/" --recursive --region us-east-1 2>&1
Write-Host "Total CONAB files: $($conab.Count)  (was 57; expect same or higher)"

# Each crop year from 2012/13 onward should have ≥ 4 surveys
foreach ($yr in @("2012_13","2015_16","2018_19","2020_21","2022_23","2024_25")) {
    $n = ($conab | Where-Object { $_ -match "crop_year=$yr/" }).Count
    Write-Host "  $yr: $n surveys"
}
```

---

### P1 Completion Gate

All assertions must pass before moving to Phase 2:
```powershell
$pass = $true

$wasde_n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_wasde/" --recursive --region us-east-1 2>&1).Count
if ($wasde_n -lt 620) { Write-Warning "WASDE: $wasde_n < 620"; $pass = $false } else { Write-Host "WASDE OK: $wasde_n" }

$cec_n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=sagis_cec/" --recursive --region us-east-1 2>&1).Count
if ($cec_n -lt 300) { Write-Warning "CEC: $cec_n < 300"; $pass = $false } else { Write-Host "SAGIS CEC OK: $cec_n" }

$mpob_m = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=mpob/release_type=monthly_release/" --recursive --region us-east-1 2>&1).Count
if ($mpob_m -lt 100) { Write-Warning "MPOB monthly: $mpob_m < 100"; $pass = $false } else { Write-Host "MPOB monthly OK: $mpob_m" }

$unica_n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=unica/" --region us-east-1 2>&1).Count
if ($unica_n -lt 45) { Write-Warning "UNICA seasons: $unica_n < 45"; $pass = $false } else { Write-Host "UNICA OK: $unica_n seasons" }

if ($pass) { Write-Host "`nPhase 1 COMPLETE — proceed to Phase 2" } else { Write-Warning "`nPhase 1 INCOMPLETE — resolve failures before Phase 2" }
```

---

## Phase 2 — Fix the GAIN Pipeline
*Code and config changes to the Batch submit script. May require ECR image rebuild for task-level changes.*

### P2-A · Fix soybean_oil and soybean_meal (Wrong Commodity ID)

**Problem**: commodity_id 13022 and 13021 are subcategory IDs rarely tagged on actual "Oilseeds and Products Annual" attaché reports. Those reports use commodity_id=27. soybean_oil got 1 file (PY), soybean_meal got 3 files.

**Fix in `jobs/submit/submit_batch_gain_backfill.py`** — replace the two entries:
```python
{"name": "soybean_oil",  "commodity_id": "27", "countries": "AR,BR,US,CN,IN,ID,PH,VN,PY,MY,MX,TH,DE,NL,BD,PK,EG,CO,PE", "title_filter": "oilseeds"},
{"name": "soybean_meal", "commodity_id": "27", "countries": "US,AR,BR,CN,IN,ID,PH,VN,TH,MX,DE,NL,PY,BD,KR,JP,EG,CO",   "title_filter": "oilseeds"},
```

**Resubmit**:
```bash
python jobs/submit/submit_batch_gain_backfill.py --commodities soybean_oil soybean_meal
```

**Expected outcome**: 50–100+ files per commodity spanning 1998–2026 (same depth as sugar/cotton).

**Verification**:
```powershell
foreach ($src in @("usda_gain_soybean_oil","usda_gain_soybean_meal")) {
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    Write-Host "$src: $($files.Count) files"
    $countries = $files | ForEach-Object { if ($_ -match "country=([A-Z]{2})/") { $Matches[1] } } | Sort-Object -Unique
    Write-Host "  Countries ($($countries.Count)): $($countries -join ',')"
    $years = $files | ForEach-Object { if ($_ -match "publication_date=(\d{4})") { $Matches[1] } } | Sort-Object -Unique
    Write-Host "  Year range: $($years[0]) – $($years[-1])"
}
```

**Failure signals**: < 50 files total, only 2026 dates, < 5 countries.

---

### P2-B · Fix palm_oil Malaysia (MY)

**Problem**: Commodity 13023 does not retrieve FAS Kuala Lumpur attaché reports for Malaysia. MY is completely absent.

**Investigation step first** — determine what ID/title the KL post uses:
```bash
# Test 1: commodity 27 + MY title filter
# Edit submit script temporarily, resubmit with --dry-run, inspect what FAS returns for MY

# Test 2: check if a direct FAS search finds KL palm oil reports
curl "https://fas.usda.gov/api/gain/recent?countryCode=MY&commodityCode=13023&limit=5" | python -m json.tool
curl "https://fas.usda.gov/api/gain/recent?countryCode=MY&commodityCode=27&limit=5" | python -m json.tool
```

**Fix** (once the correct approach is identified — likely one of):
```python
# Option A: title filter covers MY within existing palm_oil job
{"name": "palm_oil", "commodity_id": "13023", "countries": "MY,ID,TH,CO,NG,CM,GH", "title_filter": "palm oil"},

# Option B: separate entry for MY
{"name": "palm_oil",    "commodity_id": "13023", "countries": "ID,TH,CO,NG,CM,GH"},
{"name": "palm_oil_my", "commodity_id": "27",    "countries": "MY", "title_filter": "palm oil"},
```

**Resubmit**:
```bash
python jobs/submit/submit_batch_gain_backfill.py --commodities palm_oil
```

**Verification**:
```powershell
$my = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_palm_oil/country=MY/" --recursive --region us-east-1 2>&1
Write-Host "Malaysia palm oil: $($my.Count) files  (need ≥ 10)"
$my | Select-Object -First 5
$my | Select-Object -Last 3
```

**Failure signals**: 0 files for MY, all files 2026-only.

---

### P2-C · Expand Country Coverage — Grains and Oilseeds

**Problem**: Current country lists miss major producing/exporting nations. Critical for MATIF/Chicago/JSE price signals.

**Fix in `submit_batch_gain_backfill.py`**:
```python
{"name": "wheat",    "commodity_id": "15", "countries": "AR,AU,CA,UA,RU,IN,PK,EG,CN,FR,DE,PL,TR"},
{"name": "corn",     "commodity_id": "14", "countries": "BR,AR,CN,UA,FR,ZA,MX,PH,NG"},
{"name": "soybeans", "commodity_id": "27", "countries": "BR,AR,CN,PY,BO,IN,UA"},
{"name": "rapeseed", "commodity_id": "28", "countries": "CA,AU,FR,CN,DE,UA,PL"},
{"name": "rice",     "commodity_id": "16", "countries": "TH,VN,IN,CN,ID,PK"},
```

**Resubmit**:
```bash
python jobs/submit/submit_batch_gain_backfill.py --commodities wheat corn soybeans rapeseed rice
```

**Verification**:
```powershell
$checks = @{
    "usda_gain_wheat"    = @("FR","RU","CN","DE","PL")
    "usda_gain_corn"     = @("CN","ZA","MX","FR")
    "usda_gain_soybeans" = @("BR","CN")
    "usda_gain_rapeseed" = @("FR","CN","DE","PL")
    "usda_gain_rice"     = @("CN","ID")
}
foreach ($src in $checks.Keys) {
    Write-Host "$src:"
    foreach ($cc in $checks[$src]) {
        $n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/country=$cc/" --recursive --region us-east-1 2>&1).Count
        $status = if ($n -gt 0) { "OK ($n)" } else { "MISSING" }
        Write-Host "  $cc: $status"
    }
}
```

---

### P2-D · Fix Cocoa and OJ Historical Depth

**Problem**: `max_empty_pages=200` stops the title-keyword crawl short of pre-2024 reports. Only 4–5 recent files were captured for each.

**Fix in `submit_batch_gain_backfill.py`**:
```python
{"name": "orange_juice", "commodity_id": None, "countries": "BR,US,MX,ZA,AR,TR,EG,IN,CN,ES,NG,AU,PK", "title_filter": "citrus", "max_empty_pages": 2000},
{"name": "cocoa",        "commodity_id": None, "countries": "CI,GH,CM,NG,ID,EC,PE,BR,DO,MX,IN,DE,NL", "title_filter": "cocoa",  "max_empty_pages": 2000},
```

Confirm the Batch task definition allows jobs to run ≥ 4 hours (high max_empty_pages = long scan time).

**Resubmit**:
```bash
python jobs/submit/submit_batch_gain_backfill.py --commodities cocoa orange_juice
```

**Expected outcome**: 50–100+ cocoa files (2005–2026), 30–60+ OJ/citrus files.

**Verification**:
```powershell
foreach ($src in @("usda_gain_cocoa","usda_gain_orange_juice")) {
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    Write-Host "$src: $($files.Count) files"
    $years = $files | ForEach-Object { if ($_ -match "publication_date=(\d{4})") { $Matches[1] } } | Sort-Object -Unique
    Write-Host "  Year range: $($years[0]) – $($years[-1])"
    $countries = $files | ForEach-Object { if ($_ -match "country=([A-Z]{2})/") { $Matches[1] } } | Sort-Object -Unique
    Write-Host "  Countries ($($countries.Count)): $($countries -join ',')"
}
# Pre-2024 files must exist
$cocoa_old = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_cocoa/" --recursive --region us-east-1 2>&1 | Where-Object { $_ -match "publication_date=20(0|1[0-9]|2[0-3])" }).Count
Write-Host "Cocoa pre-2024: $cocoa_old files  (need > 0)"
```

**Failure signals**: < 20 files, all 2025–2026, < 5 countries.

---

### P2-E · Expand Coffee Origins (ET, VN, ID, HN, GT)

**Problem**: 64 coffee files cover only BR, CI, CO. Ethiopia (ET), Vietnam (VN, #2 world producer), Indonesia (ID) are absent.

**Check which script handles coffee** (Batch task vs `fetch_gain_coffee.py`):
```bash
aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_coffee/" --region us-east-1 | head -5
```

**Fix** — if using Batch task, update the coffee entry in `submit_batch_gain_backfill.py`:
```python
{"name": "coffee", "commodity_id": 609, "countries": "BR,CI,CO,ET,VN,ID,HN,GT,PE,UG,TZ,MX,IN,DE,NL"},
```

If using `fetch_gain_coffee.py`, update the `TARGET_COUNTRIES` constant or config file for that script.

**Resubmit**:
```bash
python jobs/submit/submit_batch_gain_backfill.py --commodities coffee
# OR
python jobs/ingest/fetch_gain_coffee.py --skip-existing-s3
```

**Verification**:
```powershell
foreach ($cc in @("ET","VN","ID","HN","GT")) {
    $n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_coffee/country=$cc/" --recursive --region us-east-1 2>&1).Count
    Write-Host "coffee/$cc: $n files  (need ≥ 5)"
    if ($n -eq 0) { Write-Warning "  $cc STILL MISSING" }
}
$total = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_coffee/" --recursive --region us-east-1 2>&1).Count
Write-Host "Coffee total: $total  (was 64)"
```

---

### P2-F · Deduplicate GAIN Double-Stored Files

**Problem**: Wheat, corn, soybeans, rapeseed, rice each have ~2 copies of every PDF under different `publication_date` partitions. The Batch task ran twice; GAIN updated its "posted" timestamp causing the same report to be stored under two dates.

**Investigation — confirm duplicates exist**:
```powershell
foreach ($src in @("usda_gain_wheat","usda_gain_corn","usda_gain_soybeans","usda_gain_rapeseed","usda_gain_rice")) {
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    $ids = $files | ForEach-Object { if ($_ -match "_([A-Z]{2}\d{4}-\d{4})\.pdf") { $Matches[1] } }
    $unique_ids = $ids | Sort-Object -Unique
    Write-Host "$src: $($files.Count) total, $($unique_ids.Count) unique report_ids — $($files.Count - $unique_ids.Count) duplicates"
}
```

**Preferred fix — bronze-layer dedup** (no raw layer changes):
In the bronze transform for GAIN PDFs, deduplicate on `report_id` extracted from the filename (e.g., `AR2026-0006`). Keep the row with the latest `publication_date`. This is safe, reversible, and touches no raw data.

**Alternative — raw S3 cleanup** (only if bronze dedup is not feasible):
```powershell
# For each commodity/country: find duplicate report_ids, delete the earlier partition
# Example — verify both copies are byte-identical before deleting:
# aws s3 cp "s3://.../publication_date=20260401/..." /tmp/copy1.pdf
# aws s3 cp "s3://.../publication_date=20260420/..." /tmp/copy2.pdf
# Compare-Object (Get-FileHash /tmp/copy1.pdf).Hash (Get-FileHash /tmp/copy2.pdf).Hash
# If identical: aws s3 rm "s3://.../publication_date=20260401/" --recursive
```

**⚠️ Only delete after confirming byte-identical copies. Do not delete without this check.**

**Verification** (after dedup):
```powershell
foreach ($src in @("usda_gain_wheat","usda_gain_corn","usda_gain_soybeans","usda_gain_rapeseed","usda_gain_rice")) {
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    $ids = $files | ForEach-Object { if ($_ -match "_([A-Z]{2}\d{4}-\d{4})\.pdf") { $Matches[1] } }
    $unique_ids = $ids | Sort-Object -Unique
    if ($files.Count -eq $unique_ids.Count) {
        Write-Host "$src: OK — no duplicates ($($files.Count) files)"
    } else {
        Write-Warning "$src: $($files.Count - $unique_ids.Count) duplicates REMAIN"
    }
}
```

---

### P2 Completion Gate

```powershell
$pass = $true

# soybean_oil/meal: expect > 50 files each
foreach ($src in @("usda_gain_soybean_oil","usda_gain_soybean_meal")) {
    $n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1).Count
    if ($n -lt 50) { Write-Warning "$src: $n < 50"; $pass = $false } else { Write-Host "$src OK: $n" }
}

# palm_oil MY: expect > 0
$my = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_palm_oil/country=MY/" --recursive --region us-east-1 2>&1).Count
if ($my -eq 0) { Write-Warning "palm_oil/MY MISSING"; $pass = $false } else { Write-Host "palm_oil/MY OK: $my" }

# cocoa + OJ: expect > 30 each
foreach ($src in @("usda_gain_cocoa","usda_gain_orange_juice")) {
    $n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1).Count
    if ($n -lt 30) { Write-Warning "$src: $n < 30"; $pass = $false } else { Write-Host "$src OK: $n" }
}

# Coffee ET and VN
foreach ($cc in @("ET","VN")) {
    $n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_coffee/country=$cc/" --recursive --region us-east-1 2>&1).Count
    if ($n -eq 0) { Write-Warning "coffee/$cc MISSING"; $pass = $false } else { Write-Host "coffee/$cc OK: $n" }
}

if ($pass) { Write-Host "`nPhase 2 COMPLETE — proceed to Phase 3" } else { Write-Warning "`nPhase 2 INCOMPLETE" }
```

---

## Phase 3 — Historical GAIN Depth (2010–2025)
*Grains and oilseeds currently have only 2026 data. Phase 3 recovers the 15-year history by switching to title-keyword crawls.*

### Background

Commodity IDs 15/14/27/28/16 are only tagged on very recent GAIN uploads. Historical "Grain and Feed Annual" and "Oilseeds and Products Annual" reports from 2010–2025 exist in the FAS database under category labels but without those commodity ID tags. The Batch task's commodity-ID crawl cannot reach them.

**Recovery approach**: Submit new Batch jobs with `commodity_id=None` and a `title_filter` matching the annual report series name. `max_empty_pages=5000` scans the full FAS GAIN catalogue back to ~2005. Each job will run for several hours.

**Pre-check — Batch job timeout**: Confirm the AWS Batch job definition timeout ≥ 6 hours:
```bash
aws batch describe-job-definitions --job-definition-name leviathan-dev-gain-backfill --region us-east-1 \
  | python -m json.tool | grep -A2 timeout
```

---

### P3-A · Wheat + Corn — "Grain and Feed Annual" (2010–2025)

Add to `submit_batch_gain_backfill.py` (or submit via `--commodities` with temporary entries):
```python
{"name": "wheat_historical",
 "commodity_id": None,
 "countries": "AR,AU,CA,UA,RU,IN,PK,EG,CN,FR,DE,PL,TR",
 "title_filter": "grain and feed annual",
 "max_empty_pages": 5000},
{"name": "corn_historical",
 "commodity_id": None,
 "countries": "BR,AR,CN,UA,FR,ZA,MX,PH,NG",
 "title_filter": "grain and feed annual",
 "max_empty_pages": 5000},
```

Note: "Grain and Feed Annual" is a single per-country report covering both wheat AND corn. One crawl retrieves data for both commodities from each attaché post. Files are stored under the commodity name matching the report content (wheat or corn), so both source prefixes benefit from the same crawl.

**Expected outcome**: ~150–250 wheat files (2010–2025 × ~13 countries), ~100–180 corn files.

**Verification**:
```powershell
foreach ($src in @("usda_gain_wheat","usda_gain_corn")) {
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    Write-Host "$src: $($files.Count) files"

    # Year distribution — must show 2010 or earlier
    $year_groups = $files | ForEach-Object { if ($_ -match "publication_date=(\d{4})") { $Matches[1] } } | Group-Object | Sort-Object Name
    $year_groups | ForEach-Object { Write-Host "  $($_.Name): $($_.Count) reports" }

    # Per-country depth — each major country should have ≥ 10 years
    foreach ($cc in @("AR","AU","FR","UA","RU")) {
        $n = ($files | Where-Object { $_ -match "country=$cc/" }).Count
        Write-Host "  $cc: $n files (expect ≥10)"
    }
}
```

**Failure signals**: < 50 files total, no pre-2024 dates, any key country (FR, RU, AU) with < 5 files.

---

### P3-B · Soybeans + Soybean Oil/Meal — "Oilseeds and Products Annual" (2010–2025)

```python
{"name": "soybeans_historical",
 "commodity_id": None,
 "countries": "BR,AR,CN,PY,BO,IN,UA",
 "title_filter": "oilseeds and products annual",
 "max_empty_pages": 5000},
{"name": "soybean_oil_historical",
 "commodity_id": None,
 "countries": "AR,BR,US,CN,IN,ID,PH,VN,PY,MY,MX,TH,DE,NL",
 "title_filter": "oilseeds and products annual",
 "max_empty_pages": 5000},
{"name": "soybean_meal_historical",
 "commodity_id": None,
 "countries": "US,AR,BR,CN,IN,ID,PH,VN,TH,MX,DE,NL,PY,BD,KR,JP",
 "title_filter": "oilseeds and products annual",
 "max_empty_pages": 5000},
```

**Verification**:
```powershell
# Brazil must be present in soybeans (world #1 producer)
$br = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_soybeans/country=BR/" --recursive --region us-east-1 2>&1).Count
Write-Host "Soybeans BR: $br files  (need ≥ 10)"

foreach ($src in @("usda_gain_soybeans","usda_gain_soybean_oil","usda_gain_soybean_meal")) {
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    $years = $files | ForEach-Object { if ($_ -match "publication_date=(\d{4})") { $Matches[1] } } | Sort-Object -Unique
    Write-Host "$src: $($files.Count) files, years $($years[0])–$($years[-1])"
}
```

---

### P3-C · Rapeseed — "Oilseeds and Products Annual" (2010–2025)

```python
{"name": "rapeseed_historical",
 "commodity_id": None,
 "countries": "CA,AU,FR,CN,DE,UA,PL",
 "title_filter": "oilseeds and products annual",
 "max_empty_pages": 5000},
```

**Verification**:
```powershell
$rape = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=usda_gain_rapeseed/" --recursive --region us-east-1 2>&1
Write-Host "Rapeseed total: $($rape.Count)"
foreach ($cc in @("FR","DE","CN","CA")) {
    $n = ($rape | Where-Object { $_ -match "country=$cc/" }).Count
    Write-Host "  $cc: $n files (expect ≥10)"
}
```

---

### P3-D · Rice — "Grain and Feed Annual" (2010–2025)

```python
{"name": "rice_historical",
 "commodity_id": None,
 "countries": "TH,VN,IN,CN,ID,PK",
 "title_filter": "grain and feed annual",
 "max_empty_pages": 5000},
```

---

### P3-E · Palm Oil — Historical (Post P2-B Investigation)

Once the correct commodity ID / title filter for MY is confirmed in P2-B, add the historical sweep:
```python
{"name": "palm_oil_historical",
 "commodity_id": None,
 "countries": "MY,ID,TH,CO,NG,CM,GH",
 "title_filter": "palm oil",
 "max_empty_pages": 5000},
```

---

### P3 Completion Gate

```powershell
$targets = @{
    "usda_gain_wheat"        = 100
    "usda_gain_corn"         = 80
    "usda_gain_soybeans"     = 70
    "usda_gain_soybean_oil"  = 100
    "usda_gain_soybean_meal" = 80
    "usda_gain_rapeseed"     = 60
    "usda_gain_rice"         = 50
    "usda_gain_palm_oil"     = 50
}

$all_pass = $true
foreach ($src in $targets.Keys) {
    $n = (aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1).Count
    $min = $targets[$src]
    $files = aws s3 ls "s3://leviathan-dev-shahem-001/raw/production/source=$src/" --recursive --region us-east-1 2>&1
    $pre2024 = ($files | Where-Object { $_ -match "publication_date=20(1[0-9]|2[0-3])" }).Count

    if ($n -lt $min) {
        Write-Warning "$src: $n files (need ≥$min) — COUNT FAIL"
        $all_pass = $false
    } elseif ($pre2024 -eq 0) {
        Write-Warning "$src: $n files OK but NO pre-2024 data — HISTORICAL FILL FAILED"
        $all_pass = $false
    } else {
        Write-Host "$src OK: $n files, $pre2024 pre-2024"
    }
}

if ($all_pass) { Write-Host "`nPhase 3 COMPLETE — all GAIN sources have historical depth" } else { Write-Warning "`nPhase 3 INCOMPLETE" }
```

---

## Summary Table

| Item | Phase | Action | Files Before | Expected After |
|------|-------|--------|-------------|----------------|
| WASDE | 1-A | `fetch_usda_wasde.py --skip-existing-s3` | 185 | ≥ 626 |
| SAGIS CEC | 1-B | `fetch_sagis_cec.py --skip-existing-s3` | 3 | ≥ 355 |
| MPOB monthly | 1-C | Expand manifest → `fetch_mpob.py` | 1 | ~120 |
| UNICA annual | 1-D | Add 5 years to config → `fetch_unica.py` | 41 | 46 |
| UNICA biweekly | 1-E | `fetch_unica_biweekly.py --discover` | 49 | ~69 |
| CONAB | 1-F | 3 CONAB scripts | 57 | 57+ |
| soybean_oil | 2-A | Switch commodity_id 13022→27 | 1 | ≥ 50 |
| soybean_meal | 2-A | Switch commodity_id 13021→27 | 3 | ≥ 50 |
| palm_oil MY | 2-B | Investigate + fix title filter | 0 | ≥ 10 |
| wheat FR/RU/CN | 2-C | Expand country list | 0 | ≥ 5 each |
| soybeans BR | 2-C | Expand country list | 0 | ≥ 5 |
| rapeseed FR/DE/CN | 2-C | Expand country list | 0 | ≥ 5 each |
| cocoa historical | 2-D | max_empty_pages: 200→2000 | 5 | ≥ 50 |
| OJ historical | 2-D | max_empty_pages: 200→2000 | 4 | ≥ 30 |
| coffee ET/VN/ID | 2-E | Add countries to coffee config | 0 | ≥ 5 each |
| GAIN duplicates | 2-F | Bronze dedup on report_id | ~8 dupes | 0 |
| wheat 2010–2025 | 3-A | title_filter crawl, max_empty=5000 | 8→16 | ≥ 150 |
| corn 2010–2025 | 3-A | title_filter crawl, max_empty=5000 | 3→6 | ≥ 100 |
| soybeans 2010–2025 | 3-B | title_filter crawl, max_empty=5000 | 3→6 | ≥ 70 |
| soybean_oil 2010–25 | 3-B | title_filter crawl, max_empty=5000 | 1→50 | ≥ 100 |
| soybean_meal 2010–25 | 3-B | title_filter crawl, max_empty=5000 | 3→50 | ≥ 80 |
| rapeseed 2010–2025 | 3-C | title_filter crawl, max_empty=5000 | 3→6 | ≥ 60 |
| rice 2010–2025 | 3-D | title_filter crawl, max_empty=5000 | 4→8 | ≥ 50 |
| palm_oil 2010–2025 | 3-E | title_filter crawl after P2-B | 4 | ≥ 50 |
