# Leviathan — Codebase Cleanup Plan

> **Purpose:** Systematic cleanup across 8 dimensions to make the codebase idempotent, reproducible, coherent, and decoupled. Each dimension has its own subagent scope, phased work, and specific file targets. All subagents should read first, write a critical assessment with exact function/line references, then implement.

---

## How to Execute

Run one subagent per dimension. Each should:
1. **Read phase** — read every file listed under "Scope"
2. **Assess phase** — produce a written critical assessment with specific references (file, function, line pattern) before making any changes
3. **Implement phase** — apply all high-confidence changes
4. **Verify phase** — run `pytest` after changes; confirm zero regressions

### Prerequisites
```powershell
# Activate venv
.venv\Scripts\Activate.ps1
# Run tests to establish baseline
pytest tests/unit/ -v
```

---

## Dimension 1 — Deduplication & DRY

**Goal:** Eliminate copy-paste logic that creates maintenance surface. Only consolidate where it reduces complexity, not where it increases abstraction overhead.

### Critical findings from audit

| Cluster | Files | What's duplicated |
|---------|-------|-------------------|
| **Submit scripts** | `jobs/submit_batch_cpc_raw_to_bronze.py`, `jobs/submit_batch_backfill_chirps.py`, `jobs/submit_batch_b2s_chirps.py` | `build_tasks()`, `submit_tasks()`, `save_run_record()`, argparse boilerplate — ~80% of each file is identical |
| **Region loading** | `jobs/batch/cpc_raw_to_bronze_task.py`, `jobs/batch/chirps_to_bronze_task.py` | `_load_regions(s3_client, bucket, commodity)` — identical signatures and logic |
| **GDAL env setup** | `src/leviathan/ingestion/weather/chirps.py`, `jobs/batch/chirps_to_bronze_task.py` | The same 5-line `os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", ...)` block appears in both. `cpc_soil_moisture.py` does **not** set these — only CHIRPS uses them. |
| **S3 retry config** | `src/leviathan/storage/s3.py` + any direct `boto3.client()` with `Config(retries=...)` in ingest scripts | Retry config dict repeated 4–6 times |
| **ID column list** | `src/leviathan/transforms/bronze_to_silver/chirps_weather.py` | `_ID_COLS` is only defined here. `nasa_power_weather.py` has a similar but non-identical inline `required = {"date", ...}` set — it is not a duplicate. Consolidating `_ID_COLS` to `constants.py` is worthwhile; do not assume `nasa_power_weather.py` needs the same treatment. |
| **Variable rename maps** | `src/leviathan/transforms/bronze_to_silver/nasa_power_weather.py` (`WEATHER_RENAME_MAP`), `src/leviathan/transforms/bronze_to_silver/faostat_production.py` (`ELEMENT_TO_METRIC`) | Hardcoded dicts that perform the same "source label → canonical name" role |

### Phase 1 — Submit script consolidation

The three submit scripts share identical boilerplate in their submission loops and run-record writers, but their shapes differ:

- `submit_batch_backfill_chirps.py` — `build_tasks(commodities, start_year, end_year)` + `submit_tasks(tasks, ...)` + `save_run_record(submitted, commodities, start_year, end_year)`
- `submit_batch_cpc_raw_to_bronze.py` — `build_tasks(start_year, end_year, variable)` + `submit_tasks(tasks, ...)` + `save_run_record(submitted, start_year, end_year, variable)`
- `submit_batch_b2s_chirps.py` — **no `build_tasks()`**; `submit_tasks(commodities, ...)` takes the list directly + `save_run_record(submitted, commodities)`

**`jobs/utils/` already exists** with `trigger_glue_job.py`, `athena_utils.py`, etc. Add `batch_submit.py` here.

Extract the two shared inner patterns:
```python
# jobs/utils/batch_submit.py

def submit_batch_jobs(
    tasks: list[dict[str, str]],
    job_queue: str,
    job_definition: str,
    build_job_name: Callable[[dict[str, str]], str],
    aws_region: str,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    """Submit tasks to AWS Batch; return the list with job_ids filled in."""
    ...

def write_run_record(path: Path, payload: dict) -> None:
    """Serialize payload as JSON to data/batch_runs/{path}."""
    ...
```

Each script keeps its own `build_tasks()`, `build_job_name()`, and `main()`. Only the boto3 loop and file write are extracted. Job-specific metadata (what goes in the run record) stays in each script.

### Phase 2 — Region loading consolidation

Move `_load_regions(s3_client, bucket, commodity)` into `src/leviathan/storage/s3.py` or a new `src/leviathan/storage/configs.py`. The function is pure S3 + YAML — it belongs in the storage layer, not in individual task files.

### Phase 3 — GDAL env setup

The same 5-line `os.environ.setdefault(...)` block appears in both `chirps.py` (the library) and `chirps_to_bronze_task.py` (the batch entrypoint). The task sets them before importing the library, making the library's block redundant — but `setdefault` is idempotent so there is no bug.

**Correct fix:** Remove the 5-line block from `chirps_to_bronze_task.py` only. Keep it in `chirps.py`, which is the authoritative place for its own GDAL dependencies.

> **Do NOT extract to a function.** GDAL env vars must be set at module top level before `import rasterio`. A helper function would arrive too late if rasterio had already been imported by another module. The `E402 # noqa` comment in `chirps.py` is intentional and must stay.

### Phase 4 — Polling: do NOT merge

`poll_glue_runs` and `poll_batch_jobs` look similar (both `while remaining:` loops) but have meaningfully different APIs and logic:

- **Glue**: input is `dict[str, str]` (run_id → job_name); makes one `get_job_run()` call per job per tick
- **Batch**: input is `list[str]` (job IDs); makes chunked `describe_jobs()` calls capped at 100 items — an AWS API hard limit

Both are imported by name in 5+ callers (`orchestrate_backfill.py`, `run_faostat_backfill.py`, `trigger_glue_job.py`). A generic merge would force signature changes in all callers for no real benefit.

**Correct action:** Leave both functions as-is. Add `# --- Glue polling ---` / `# --- Batch polling ---` section comments to `polling.py` so the file is easier to navigate.

### Phase 5 — ID cols

Move `_ID_COLS` from `chirps_weather.py` to `src/leviathan/common/constants.py` as `SILVER_WEATHER_ID_COLS`. Update `chirps_weather.py` to import it. This is a small but clean win — one fewer private constant buried inside a transform module.

`nasa_power_weather.py` has a similar but non-identical inline `required` set — leave it alone.

### Scope
- `jobs/submit_batch_cpc_raw_to_bronze.py`
- `jobs/submit_batch_backfill_chirps.py`
- `jobs/submit_batch_b2s_chirps.py` *(note: no `build_tasks()` — submit loop is the consolidation target)*
- `jobs/batch/cpc_raw_to_bronze_task.py`
- `jobs/batch/chirps_to_bronze_task.py`
- `src/leviathan/ingestion/weather/chirps.py`
- `src/leviathan/common/polling.py` *(read-only — add section comments only)*
- `src/leviathan/transforms/bronze_to_silver/chirps_weather.py`
- `src/leviathan/transforms/bronze_to_silver/nasa_power_weather.py`
- `src/leviathan/transforms/bronze_to_silver/faostat_production.py`

---

## Dimension 2 — Type Consolidation

**Goal:** All shared type definitions live in `src/leviathan/common/types.py`. No TypedDicts, Literal unions, or structural types scattered across files.

### Critical findings from audit

| Type | Currently in | Should be in |
|------|-------------|--------------|
| `Region` TypedDict (country, region, latitude, longitude) | `src/leviathan/common/types.py` | Already there — verify all callers use it |
| `ProcessResult` TypedDict | `src/leviathan/common/types.py` | Already there — verify callers use it |
| `CommodityName` Literal union | Nowhere — `ALL_COMMODITIES: list[str]` in `constants.py` | Add `CommodityName = Literal["arabica_coffee", ...]` in `types.py` |
| `SourceName` Literal union | Nowhere — strings used ad-hoc | Add `SourceName = Literal["nasa_power", "chirps", "cpc_soil", "faostat", ...]` |
| Crawled record dict (gain_backfill_task.py) | Implicit `dict` in `jobs/batch/gain_backfill_task.py` | Add `GainRecord = TypedDict(...)` in `types.py` or in gain task |
| Submit task dict | `dict[str, str]` inline | Add `BatchTask = TypedDict("BatchTask", {"year": str, "variable": str, "bucket": str, ...})` |
| S3 key components | Implicit strings | Add `S3Key = NewType("S3Key", str)` for safety |
| `BronzeKey`, `SilverKey` | Already in `types.py` | Verify consistent usage throughout |

### Phase 1 — Audit all TypedDicts

Search for any `TypedDict`, `@dataclass`, and `NamedTuple` definitions outside `types.py`. Move them in.

### Phase 2 — Harden `constants.py`

Replace `ALL_COMMODITIES: list[str]` with:
```python
from typing import get_args
CommodityName = Literal[
    "arabica_coffee", "brazilian_arabica_coffee", "campinas_corn_reference_bmf",
    # ... all 31
]
ALL_COMMODITIES: list[CommodityName] = list(get_args(CommodityName))
```
This gives type-checked commodity names everywhere they are used.

### Phase 3 — Fix `dict[str, Any]` function signatures

Every function that accepts or returns `dict[str, Any]` where the structure is known should be updated:
- `load_yaml()` — return type depends on context; acceptable to remain `dict[str, Any]` with a note
- `_load_regions()` in batch tasks — return `list[Region]` (already a TypedDict, just not used consistently)
- `all_commodity_locations` in `cpc_raw_to_bronze_task.py` — type as `dict[CommodityName, list[Region]]`
- Crawled records in `gain_backfill_task.py` — define and use `GainRecord`

### Phase 4 — boto3 type stubs

Install `boto3-stubs[batch,glue,s3,logs]` as a dev dependency:
```toml
[project.optional-dependencies]
dev = [..., "boto3-stubs[batch,glue,s3,logs]"]
```
Replace all `client: Any` and `s3_client: Any` annotations with `S3Client`, `BatchClient`, `GlueClient`.

### Scope
- `src/leviathan/common/types.py`
- `src/leviathan/common/constants.py`
- `src/leviathan/common/polling.py`
- `src/leviathan/storage/s3.py`
- `src/leviathan/storage/dead_letter.py`
- `src/leviathan/ingestion/weather/cpc_soil_moisture.py`
- `jobs/batch/cpc_raw_to_bronze_task.py`
- `jobs/batch/chirps_to_bronze_task.py`
- `jobs/batch/gain_backfill_task.py`
- `pyproject.toml`

---

## Dimension 3 — Unused Code Removal

**Goal:** Delete every function, import, module, and variable that is never referenced. Confirm with cross-references before deleting.

### Critical findings from audit

| Item | Location | Assessment |
|------|----------|-----------|
| `src/leviathan/common/base_jobs.py` | This module is a deprecation stub | The entire file can be deleted once all importers are updated |
| `save_raw_json()` | `src/leviathan/ingestion/weather/nasa_power.py` | Only called from `jobs/ingest/fetch_nasa_power.py`; this helper belongs in the ingest layer, not the library |
| `_get_html()` in gain task | `jobs/batch/gain_backfill_task.py` | Defined as standalone function but only called once inline; can be inlined |
| Glue chirps job | `jobs/glue/chirps_to_bronze.py` (if it exists) | Superseded by Batch; `currentstate.md` says "should NOT be used" |
| Dead `scratch/` scripts | `scratch/*.py` — many are one-off probes | Review each; move to archive or delete |

### Phase 1 — Find all unused imports

Run:
```powershell
# Install if not present
pip install ruff
ruff check src/ jobs/ --select F401 --output-format text
```
Remove every flagged unused import. Do NOT use `# noqa` to suppress — fix the import.

### Phase 2 — Find all unreferenced functions

```powershell
ruff check src/ jobs/ --select F811,F841 --output-format text
```
For any function not found by grep in the entire codebase:
```powershell
Select-String -Path "src/**/*.py","jobs/**/*.py" -Pattern "function_name" -Recurse
```
Confirm truly unreferenced before removing.

### Phase 3 — Delete `common/base_jobs.py` stub

The file contains only a module-level docstring — zero Python code. A search confirms there are no callers: `from leviathan.common.base_jobs` appears nowhere in `src/`, `jobs/`, or `tests/`. The test file `tests/unit/test_base_jobs.py` already imports from `leviathan.storage.base_jobs` directly.

1. Confirm: `grep -r "from leviathan.common.base_jobs" src/ jobs/ tests/` → zero results
2. Delete `src/leviathan/common/base_jobs.py`
3. Run `pytest tests/unit/test_base_jobs.py -v` — must stay green

### Phase 4 — Audit `scratch/` directory

The `scratch/` directory contains 15+ one-off probe scripts. These are NOT part of the library but clutter the repo. For each file in `scratch/`:
- If it was a one-off diagnostic: delete
- If it embeds reusable discovery logic: move relevant logic to the appropriate ingest script under `jobs/ingest/`
- Do NOT keep dead probe scripts in the main branch

### Phase 5 — Verify Glue chirps job is tombstoned

Confirm `jobs/glue/chirps_to_bronze.py` either does not exist or is clearly tombstoned with a `raise RuntimeError("Deprecated — use Batch task")` at the top so it cannot be accidentally re-invoked.

### Scope
- All `src/leviathan/**/*.py`
- All `jobs/**/*.py`
- `scratch/*.py`
- `tests/**/*.py`

---

## Dimension 4 — Circular Dependency Elimination

**Goal:** No module should import from a layer above it. The dependency graph should be a DAG: `common` → `storage` → `ingestion` → `transforms` → `jobs`.

### Expected clean dependency graph

```
common/        ← no internal leviathan imports
storage/       ← imports from common/
ingestion/     ← imports from common/, storage/
transforms/    ← imports from common/, storage/
jobs/batch/    ← imports from all of the above
jobs/glue/     ← imports from all of the above
jobs/ingest/   ← imports from all of the above
```

### Critical findings from audit

- `src/leviathan/storage/base_jobs.py` imports from `src/leviathan/common/` — ✅ correct
- `src/leviathan/common/base_jobs.py` (stub) imports from `storage/base_jobs.py` — this is an upward import (common importing storage). **This is the circular risk.** The stub should be deleted (Dimension 3).
- `src/leviathan/common/quality.py` may import from `storage/` — verify it does not.
- `src/leviathan/common/polling.py` — verify it does not import from `storage/`.

### Phase 1 — Map the actual import graph

```powershell
pip install pydeps
pydeps src/leviathan --max-bacon=3 --cluster --show-dot
```
Or manually grep:
```powershell
Get-ChildItem src/leviathan -Recurse -Filter "*.py" | ForEach-Object {
    $path = $_.FullName
    Select-String -Path $path -Pattern "^from leviathan\." | ForEach-Object {
        "$($path.Split('leviathan\')[1]) -> $($_.Matches[0].Value)"
    }
}
```

### Phase 2 — Identify violations

Any import where a lower layer imports a higher layer:
- `common` importing from `storage`, `ingestion`, `transforms`, or `jobs` → **violation**
- `storage` importing from `ingestion`, `transforms`, or `jobs` → **violation**

### Phase 3 — Fix violations

The most likely issue: `quality.py` uses pandas DataFrames that are also used in `transforms/`. If it imports from transforms, that import must be reversed (transforms calls quality, not the other way around).

Move any type that creates a circular import into `common/types.py` — that is its purpose.

### Phase 4 — Add import linting

Add to `pyproject.toml`:
```toml
[tool.ruff.lint]
select = ["I"]  # isort — enforces consistent import ordering
# Consider: import-linter for architectural boundary enforcement
```

### Scope
- All `src/leviathan/**/*.py`
- `pyproject.toml`

---

## Dimension 5 — Weak Type Hardening

**Goal:** Remove all `Any`, untyped `dict`, bare `dict[str, Any]`, and `Optional` without `None`-guard enforcement. Replace with precise types. Do not use `type: ignore` as a fix — fix the code.

### Critical findings from audit

| Location | Weak type | Correct replacement |
|----------|-----------|---------------------|
| `src/leviathan/storage/s3.py` — `get_thread_local_s3_client()` | Returns `Any` | Returns `S3Client` (from boto3-stubs) |
| `src/leviathan/common/polling.py` — `client: Any` | Accepts any object | `client: GlueClient \| BatchClient` |
| `src/leviathan/ingestion/weather/cpc_soil_moisture.py` — `locations: list[dict]` | Untyped dict | `locations: list[Region]` |
| `src/leviathan/ingestion/weather/chirps.py` — `locations: list[dict]` | Untyped dict | `locations: list[Region]` |
| `jobs/batch/cpc_raw_to_bronze_task.py` — `all_commodity_locations: dict[str, list[dict]]` | Nested untyped | `dict[CommodityName, list[Region]]` |
| `jobs/batch/gain_backfill_task.py` — `record: dict` | Bare dict | `GainRecord` TypedDict |
| `src/leviathan/common/config.py` — `load_yaml() -> dict[str, Any]` | Overly broad | Acceptable — annotate with comment that caller should narrow |
| `src/leviathan/storage/dead_letter.py` — `error_detail: dict` | Bare dict | `ErrorDetail` TypedDict |
| `src/leviathan/common/constants.py` — `ALL_COMMODITIES: list[str]` | Should be `list[CommodityName]` | After adding `CommodityName` Literal (Dimension 2) |

### Phase 1 — Run mypy baseline

```powershell
pip install mypy
mypy src/leviathan --strict --ignore-missing-imports 2>&1 | Tee-Object mypy_baseline.txt
```
Count current error count. Goal: reduce by 80%+.

### Phase 2 — Fix `Any`-typed boto3 clients

Install `boto3-stubs` (Dimension 2 prerequisite). Then:
- Replace `s3_client: Any` → `s3_client: S3Client`
- Replace `client: Any` in `polling.py` → overload or Union
- Replace return type of `get_thread_local_s3_client()` → `S3Client`

### Phase 3 — Fix `list[dict]` location signatures

In `chirps.py` and `cpc_soil_moisture.py`:
```python
# Before
def extract_region_values(tif_bytes: bytes, locations: list[dict], ...) -> dict[str, float | None]:

# After
from leviathan.common.types import Region
def extract_region_values(tif_bytes: bytes, locations: list[Region], ...) -> dict[str, float | None]:
```
Verify all callers pass `list[Region]` (they should — `_load_regions()` already returns this type).

### Phase 4 — Fix `dict` return types in transforms

Any transform function that returns `dict[str, Any]` where the structure is known: replace with proper TypedDict. Focus on `_read_raw_records()`, `_parse_one_station()` patterns in ingest scripts.

### Phase 5 — Verify with mypy

After fixes:
```powershell
mypy src/leviathan --strict --ignore-missing-imports 2>&1 | Tee-Object mypy_after.txt
```
Compare error counts. Any remaining `Any` must have a `# type: ignore[assignment]` with a comment explaining why.

### Scope
- `src/leviathan/storage/s3.py`
- `src/leviathan/common/polling.py`
- `src/leviathan/ingestion/weather/chirps.py`
- `src/leviathan/ingestion/weather/cpc_soil_moisture.py`
- `src/leviathan/ingestion/weather/nasa_power.py`
- `jobs/batch/cpc_raw_to_bronze_task.py`
- `jobs/batch/chirps_to_bronze_task.py`
- `jobs/batch/gain_backfill_task.py`
- `src/leviathan/common/constants.py`
- `src/leviathan/storage/dead_letter.py`
- `pyproject.toml`

---

## Dimension 6 — Exception Handling Audit

**Goal:** No exception is swallowed silently. `try/except` is only used where: (a) handling genuinely unknown input (network, files, user data), or (b) implementing an explicit retry/dead-letter pattern with documented intent. Error hiding and fallback patterns are removed.

### Critical findings from audit

This codebase has a **deliberate pattern** of swallowing exceptions in non-critical write operations (dead letter, metadata writing, quality reporting). These are intentional. The audit must distinguish between:

- ✅ **Intentional suppression** — `write_dead_letter()`, `write_quality_report_to_s3()`, `write_raw_s3_metadata()` — these should NEVER crash the main processing loop
- ❌ **Accidental suppression** — broad `except Exception` inside processing loops that masks the *real* failure

| Location | Pattern | Assessment |
|----------|---------|------------|
| `src/leviathan/storage/dead_letter.py` | `except Exception: logger.error(...)` (no reraise) | ✅ Intentional — write failure must not abort main flow |
| `src/leviathan/storage/raw_metadata.py` | `except Exception: logger.warning(...)` | ✅ Intentional — metadata is best-effort |
| `src/leviathan/common/quality.py` — `write_quality_report_to_s3()` | `except Exception: logger.error(...)` | ✅ Intentional |
| `src/leviathan/storage/base_jobs.py` — `_process_one()` | `except Exception` → dead-letter | ✅ Intentional — this is the dead-letter gateway |
| `src/leviathan/storage/base_jobs.py` — `_load_expected_countries()` | `except Exception: return []` | ❌ **Hides real failures** — should log the exception and re-raise if the file is expected |
| `jobs/batch/chirps_to_bronze_task.py` — `_fetch_day()` | `except Exception: return None` | ❌ **Silently skips days** — should distinguish HTTP 404 (expected) from all other errors |
| `src/leviathan/ingestion/weather/chirps.py` — `_read_cog_values()` | `except Exception` | ❌ Catches all rasterio errors including programming bugs — should only catch `RasterioIOError` |
| `src/leviathan/ingestion/weather/cpc_soil_moisture.py` — `_read_cog_values()` | Same | ❌ Same issue |
| `jobs/ingest/fetch_nasa_power.py` | `except Exception` in main loop | ❌ All loop iterations silently continue on any error |
| `jobs/batch/gain_backfill_task.py` — `_get_html()` | `except Exception: return None` | ❌ Network errors and parsing errors handled identically — split by exception type |
| `jobs/glue/raw_to_bronze_faostat.py` | `except Exception` accumulates failures | ❓ Borderline — acceptable for bulk batch processing but should log full traceback |

### Phase 1 — Add `# intentional-suppress` comment to all legitimate suppressions

For every `except Exception` that is intentional, add a standardized comment:
```python
except Exception:  # intentional: dead-letter non-critical write; must not crash main loop
    logger.error("Failed to write dead letter: %s", exc_info=True)
```
This makes the intent explicit and prevents future "cleanup" from incorrectly removing them.

### Phase 2 — Fix narrow-able catches

In `chirps.py` and `cpc_soil_moisture.py`:
```python
# Before (too broad)
except Exception:
    return None

# After (precise)
import rasterio.errors
except rasterio.errors.RasterioIOError as exc:
    if "404" in str(exc) or "not found" in str(exc).lower():
        logger.debug("TIF not found at %s", url)
        return None
    raise  # all other rasterio errors are programming bugs
```

### Phase 3 — Fix `_load_expected_countries()`

```python
# Before
except Exception:
    return []

# After
except Exception:
    logger.warning("Could not load expected countries for %s: %s", commodity, exc_info=True)
    return []  # intentional: missing country list is non-fatal; treated as unconstrained
```

### Phase 4 — Fix ingest loop exception handling

In `fetch_nasa_power.py` and similar ingest scripts:
```python
# Before
except Exception:
    logger.error("Failed for %s", region)
    continue

# After
except requests.HTTPError as exc:
    if exc.response.status_code == 429:
        raise  # never silently skip rate-limit; abort and retry at job level
    logger.error("HTTP error for %s: %s", region, exc)
    continue
except Exception:
    logger.exception("Unexpected error for %s; continuing", region)
    continue
```

### Phase 5 — Verify test coverage

Every changed `except` clause should have a unit test that exercises the specific exception type. Add tests in `tests/unit/` for each narrowed exception.

### Scope
- `src/leviathan/storage/base_jobs.py`
- `src/leviathan/storage/dead_letter.py`
- `src/leviathan/storage/raw_metadata.py`
- `src/leviathan/common/quality.py`
- `src/leviathan/ingestion/weather/chirps.py`
- `src/leviathan/ingestion/weather/cpc_soil_moisture.py`
- `jobs/batch/chirps_to_bronze_task.py`
- `jobs/batch/gain_backfill_task.py`
- `jobs/ingest/fetch_nasa_power.py`
- `jobs/glue/raw_to_bronze_faostat.py`

---

## Dimension 7 — Legacy & Dead Code Path Removal

**Goal:** One canonical code path per operation. No deprecated shims, no commented-out old implementations, no "v1/v2" flags.

### Critical findings from audit

| Item | Location | Action |
|------|----------|--------|
| `src/leviathan/common/base_jobs.py` | Entire file is a deprecation shim redirecting to `storage/base_jobs.py` | Delete after updating all imports |
| Glue CHIRPS job | `jobs/glue/` (verify existence) | If present: add `raise RuntimeError("DEPRECATED: use jobs/batch/chirps_to_bronze_task.py")` as first line; remove from Terraform if wired |
| `scratch/*.py` (15+ files) | `scratch/` directory | Audit each: probe files that served their purpose should be deleted; any reusable discovery logic should be merged into proper ingest scripts |
| Old CHIRPS submit scripts | Possibly `jobs/submit_batch_backfill_chirps.py` — check if an "old" version exists alongside a "new" | Confirm only one submit script per pipeline exists |
| Legacy Glue bootstrap egg | `build/lib/leviathan/`, `build/bdist.win-amd64/` | These are build artifacts; confirm `.gitignore` covers them; delete locally |
| `pyproject.toml` — `[tool.ruff.lint.per-file-ignores]` for `jobs/glue/` | If this is for `E402` on bootstrap imports | Keep — this is necessary, not legacy |

### Phase 1 — Enumerate `scratch/`

For each file in `scratch/`:
```
scratch/audit_manifest.py        → was used to audit manifests; likely done → DELETE
scratch/check_manifest.py        → diagnostic → DELETE after confirming no longer needed
scratch/fix_stale_uuids.py       → one-off fix → DELETE (fix already applied)
scratch/probe_*.py (10 files)    → all are exploration probes → DELETE
scratch/resolve_*.py             → one-off resolvers → DELETE
scratch/scrape_archive_links.py  → if logic is in an ingest script → DELETE
scratch/wap_status.json          → data artifact → DELETE or move to data/
scratch/conab/                   → probe subdir → DELETE
scratch/gain/                    → probe subdir → DELETE
scratch/mpob/                    → probe subdir → DELETE
scratch/mpoc/                    → probe subdir → DELETE
scratch/pdf_samples/             → sample data → DELETE (binary blobs in repo)
```
**Do not delete without confirming no canonical script depends on them.**

### Phase 2 — Kill `common/base_jobs.py`

1. `grep -r "from leviathan.common.base_jobs" src/ jobs/ tests/`
2. For each match, update import to `from leviathan.storage.base_jobs`
3. `grep -r "from leviathan.common import base_jobs"` — same fix
4. Delete `src/leviathan/common/base_jobs.py`
5. Run `pytest` — must be green

### Phase 3 — Verify Glue CHIRPS tombstone

```powershell
# Check if chirps glue job exists
Test-Path jobs/glue/chirps_to_bronze.py
# Check if it's referenced in terraform
Select-String -Path "infra/**/*.tf" -Pattern "chirps.to.bronze" -Recurse
```
If the job exists and is referenced in Terraform: add tombstone in Python file AND remove from Terraform job definition. If the Terraform resource is commented out: clean it up.

### Phase 4 — Confirm no `v1`/`v2` flags or commented-out alternative implementations

```powershell
Select-String -Path "src/**/*.py","jobs/**/*.py" -Pattern "# OLD|# LEGACY|# v1|# TODO.*remove|# deprecated" -Recurse
```
Each match: either remove the commented block or implement the TODO.

### Phase 5 — Build artifact cleanup

Confirm `.gitignore` includes:
```
build/
dist/
*.egg-info/
```
Delete local `build/` and `dist/` if present.

### Scope
- `src/leviathan/common/base_jobs.py` — delete
- `scratch/` directory — audit + clean
- `jobs/glue/` — tombstone CHIRPS if present
- `infra/terraform/` — remove any commented-out resources
- `build/`, `dist/` — confirm gitignored

---

## Dimension 8 — Comment & Documentation Quality

**Goal:** Every comment either (a) explains *why* something non-obvious is done, or (b) provides orientation for a new reader. Comments that restate the code, describe completed refactors, or document things that no longer exist are removed. No AI slop.

### What to look for

**AI slop patterns to remove:**
```python
# Initialize the logger
logger = get_logger(__name__)

# Process each commodity
for commodity in commodities:

# Return the result
return result
```

**Stale motion comments to remove:**
```python
# TODO: migrate this to Batch (DONE — remove this comment)
# Previously this used X, now it uses Y
# This was added as a temporary workaround for Z
```

**Good comments to keep:**
```python
# CPC TIFs use 0–360° longitude convention; convert to -180–180 before matching
# Glue Python Shell runs inside a container that does NOT have leviathan pre-installed
# exit code 1 from PowerShell when stderr is piped is a false positive; check last log line
```

### Phase 1 — Sweep for motion/progress comments

```powershell
Select-String -Path "src/**/*.py","jobs/**/*.py" -Pattern "# TODO|# FIXME|# HACK|# XXX|# NOTE: previously|# old|# legacy|# temp|# workaround" -Recurse
```
For each:
- If the item described is complete: delete the comment
- If genuinely still pending: keep and link to GitHub issue number
- If it's a workaround that's permanent: explain *why* it exists

### Phase 2 — Remove restating comments

Search for comments that literally describe the next line of code. Delete them. Examples:
```python
# Check if the file exists → remove this, the code is self-explanatory
if s3_object_exists(bucket, key):
```

### Phase 3 — Audit module-level docstrings

Each module in `src/leviathan/` should have a module-level docstring that says:
- What the module does
- What it does NOT do (scope boundary)
- Any non-obvious conventions

Modules that currently have no docstring: add a 2–4 sentence one. Do not write essays.

### Phase 4 — Audit `__init__.py` re-exports

Check all `__init__.py` files:
```powershell
Get-ChildItem src/leviathan -Recurse -Filter "__init__.py" | Get-Content
```
Each `__init__.py` should either:
- Be empty (sub-packages that are imported directly)
- Re-export the package's public API clearly

Remove any `__init__.py` that has commented-out old imports.

### Phase 5 — Verify README accuracy

`README.md` must accurately reflect the current structure. Sections describing CHIRPS Glue (superseded by Batch) or other outdated infrastructure should be updated. Read `README.md` and compare against `currentstate.md` — flag discrepancies.

### Scope
- All `src/leviathan/**/*.py`
- All `jobs/**/*.py`
- All `tests/**/*.py`
- `README.md`
- All `__init__.py` files

---

## Cross-Cutting Constraints for All Subagents

1. **Never use `# noqa` or `# type: ignore` to suppress a lint/type error — fix the root cause.** The only exception is genuinely unresolvable boto3 typing issues, which should have an inline comment explaining exactly why.

2. **Run `pytest tests/unit/ -v` before and after every change.** Zero regressions is a hard requirement. If a test must be updated, the test update is part of the fix, not a workaround.

3. **Never rename public API surfaces** (functions exported from `src/leviathan/`) without also updating every caller. Use grep to find all callers before renaming.

4. **Do not add error handling** to places that don't have it — only remove/improve existing handlers. Adding new try/except is out of scope for this cleanup.

5. **`scratch/` files may have been used to discover live data states.** Do not delete any `scratch/` file without confirming its output or purpose is captured elsewhere or is genuinely disposable.

6. **Idempotency check:** All Batch tasks should be safe to re-run. After cleanup, verify that `_write_bronze_partition()` and equivalent functions still check for existing output before writing (i.e., `force_overwrite=False` is respected).

---

## Execution Order

Run dimensions in this order to minimize re-work:

```
Phase A (no breaking changes):
  Dimension 8 (comments) → safe, no logic changes
  Dimension 3 (dead code) → remove stubs first so later dimensions don't trip on them

Phase B (type system):
  Dimension 2 (type consolidation) → establish type system
  Dimension 5 (weak types) → depends on Dimension 2 types being in place

Phase C (structural):
  Dimension 1 (deduplication) → now that types are clean, consolidate logic
  Dimension 6 (exception handling) → now that logic is consolidated, fix error paths
  Dimension 4 (circular deps) → verify graph is clean after restructuring

Phase D (final):
  Dimension 7 (legacy removal) → delete what no longer has callers after above
  Full test suite → green
  mypy --strict → near-zero errors
  ruff check → zero errors
```

---

## Definition of Done

The cleanup is complete when:

- [ ] `pytest tests/unit/ -v` — **100% pass** (no tests skipped or xfailed)
- [ ] `ruff check src/ jobs/ tests/` — **zero errors** (no `# noqa` suppressions added)
- [ ] `mypy src/leviathan --strict --ignore-missing-imports` — **< 10 errors** (target: zero)
- [ ] `grep -r "from leviathan.common.base_jobs" src/ jobs/` — **zero results**
- [ ] `grep -r "Any" src/leviathan/ --include="*.py"` — **< 5 results** (only in `load_yaml` return and unavoidable boto3 spots)
- [ ] `ls scratch/` — **empty or deleted**
- [ ] `grep -rP "# (TODO|FIXME|HACK|XXX|OLD|LEGACY)" src/ jobs/` — **zero results** (or each has a GitHub issue number)
- [ ] All three `submit_batch_*.py` scripts share a common `jobs/utils/batch_submit.py`
- [ ] `_load_regions()` exists in exactly **one place** in the codebase
