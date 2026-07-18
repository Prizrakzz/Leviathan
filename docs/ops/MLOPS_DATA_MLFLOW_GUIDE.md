# Leviathan Data & MLflow Guide (for the MLOps agent)

> State as of **2026-07-17** (post A1-A2 arming: the silver layer is autonomous — 22 EventBridge
> schedules, shadow→gate→canonical publish discipline). Bucket: `s3://leviathan-dev-shahem-001`.
> Glue database: `leviathan_dev`. Region: `us-east-1`. Registry of record:
> `configs/silver/tables/*.yaml` (43 tables) — when this doc and the registry disagree, the
> registry wins; regenerate DDLs with `scripts/silver/generate_ddls_from_registry.py`.

---

## 0. Ground rules (read first)

1. **Point-in-time (PIT) is the product.** Every consumer must ask "what was knowable on date X".
   Tables carry vintage semantics differently (see per-table notes): WASDE by `release_date`
   partition, ESR by vintage columns, PSD by release month, weather by observation date.
   Never join "latest" data into a backtest window.
2. **Canonical vs. non-canonical prefixes.** Only canonical prefixes are consumable:
   - `.../_shadow/...` = staged-but-unpromoted publish candidates. NEVER read.
   - `silver/weather/source=<s>/_staging/...` = month-grain b2s handoff to compaction,
     deliberately OUTSIDE the `commodity=` data plane. NEVER read; usually empty (retired
     after each promote).
   - `raw/weather/source=modis_ndvi/run_id=<rid>/_tasks.json` = fetch checkpoint, not data.
3. **NEVER `CAST()` a projected/partition column in Athena predicates.** The July 2-4 LIST-storm
   ($134, 26.8M ListBucket calls) came from a CAST-on-partition-column making the predicate
   non-sargable → full partition enumeration. Use sargable literals of the column's native type.
4. **Weather tables are `projection=legacy-quarantined` or registered — never re-enable Athena
   partition projection on them.** The weather trio was deliberately deprojected to a compacted
   `[commodity, year]` grain (SILVER-F047) to kill the ~590K-tiny-file layout.
5. **Prefer S3 LIST/GET over Athena for bulk scans of weather/evidence prefixes** (LIST-once
   discipline). Athena is for the numbers-agent-shaped, partition-pruned queries.
6. **Commodity identity is CONTRACT slugs almost everywhere** (`corn_cbot`, `white_sugar`,
   `soybean_meal_dce`, 31 total). The exception: **`silver_wasde` uses base names** (`corn`,
   `wheat`). `gold_weather_z` uses contract slugs (verified live 2026-07-17 — a base-name
   assumption here caused a real gate failure).
7. **Value floors:** most tables enforce `min_nonnull_frac` (V001, default 0.5) with per-column
   overrides where a column is null-by-construction (e.g. `silver_conab_coffee.
   production_revision_thousand_bags` = 0.30, it's a first-difference). If you add a derived
   column that is legitimately sparse, add an override — do not weaken the global floor.

---

## 1. Layer map

| Layer | Prefix root | What it is | Consumable? |
|---|---|---|---|
| raw | `raw/<domain>/source=<src>/...` | Fetcher output, source-faithful bytes (CSV/XLS/PDF/JSON) | No (pipeline input only) |
| bronze | `bronze/<domain>/source=<src>/...` | Parsed, typed, still source-shaped Parquet | No (producer input) |
| silver | `silver/...` | Curated, gated, canonical analytical tables (registry-governed) | **Yes — primary surface** |
| gold | `gold/...` | Derived analytics (z-anomalies) | **Yes** |
| text | `text/...` | `document.json` per doc: `full_text` + `extraction_method` (no OCR confidence retained) | GraphRAG only |
| evidence | `graphrag_evidence/...` | Chunked/embedded narrative props, slices, eval artifacts | GraphRAG only |
| census | `cascade_census/rolling/<schedule>/census.json` | Rolling gate baselines per schedule family | Gate infra only |
| mlflow | `mlflow/artifacts/...` | MLflow artifact store | Via MLflow API |

Raw source inventory (non-exhaustive; grep `src/leviathan/storage/paths.py` for the full set):
`raw/production/source={usda_wasde, usda_esr, usda_psd, conab, sagis_cec, sagis_weekly, unica,
unica_biweekly, fnc, wb_food_cpi, yfinance, mpob, mpoc, icco, nass_*, ams, fgis, cftc, gain, wap}`,
`raw/weather/source={modis_ndvi, chirps, cpc_soil, nasa_power, noaa_oni, noaa_iod}`.

---

## 2. Silver & gold tables (the 43), by domain

Grain notation: one row per (...). Cadence = the armed schedule that refreshes it.

### 2.1 Balance sheet / supply-demand
| Table | S3 prefix | Grain & notes |
|---|---|---|
| `silver_psd` | `silver/psd` | USDA PSD global S&D per (commodity, country, attribute, marketing year, **release vintage**). Flat. Cadence: `psd_monthly` (8-13th 18:00 UTC). PIT: release-month vintage columns — filter to releases ≤ as-of. Watch: env-mode invocation quirks (F2 lesson: `-m` module form). |
| `silver_wasde` | `silver/wasde` | WASDE balance sheets per (release_date, table, commodity, region, attribute, marketing year, projection role). **Registered partitions by `release_date`** — 488 releases 1973→present, full archival vintages. **BASE commodity names**. Strict natural-key resolver: junk regions (`ii`, `Sep Proj`, month abbrevs) are quarantined classes — if a new conflict class appears the producer RAISES (fail-closed); fix `classify_region`, never relax the resolver. Cadence: `wasde_monthly`. |
| `silver_wap_table01` (+`_revisions`) | `silver/wap_table01` | World Agricultural Production table 01 + revision linkage. 287 releases. The revisions table is derived — first-difference semantics. Cadence: `wap` (12-14th). |
| `silver_icco_cocoa`, `silver_mpob`, `silver_mpob_annual`, `silver_mpoc_stock_comparison` | `silver/{icco_cocoa, mpob, mpob_annual, mpoc_stock_comparison}` | Cocoa (ICCO QBCS) and Malaysian palm balance sheets, monthly/annual. Flat, contract slugs. |

### 2.2 Trade flows
| Table | S3 prefix | Grain & notes |
|---|---|---|
| `silver_esr` | `silver/production/source=usda_esr` | US Export Sales per (commodity_code, country, week, **vintage**). **Registered partitions** (F031/F032 per-week promotion + publication fail-safe). All-vintage window (B2-E12): query with explicit vintage predicates, never CAST the partition col (the LIST-storm trigger lived here). Cadence: `esr_weekly` (THU 14:00 UTC). |
| `silver_esr_compact` | `silver/esr` | Compacted ESR consumer view (commodity-partitioned). Prefer for bulk reads. |
| `silver_fgis` | `silver/fgis` | Grain inspections per (leviathan_slug, week/date). Weekly (`fgis`, THU). |
| `silver_mpoc_exports_by_country`, `silver_mpoc_trade_stats_monthly` | `silver/mpoc_*` | Malaysian palm exports/trade, monthly. |
| `silver_sagis_weekly_deliveries`, `silver_sagis_weekly_exports` | `silver/sagis_weekly_*` | South African grain weekly flows. Cadence: `sagis_weekly` (FRI 12:00 UTC — the first family ever to run fully autonomously, 2026-07-17). Note: 2026-07 SAGIS golden REPLACEMENT fixed a thousand-fold wheat corruption — treat pre-fix local caches as poisoned. |
| `silver_fnc_colombia_exports_port_type` | `silver/fnc_colombia/exports_port_type` | Colombian coffee exports by port/type, monthly. |

### 2.3 Production / crop condition
| Table | S3 prefix | Grain & notes |
|---|---|---|
| `silver_production` | `silver/production` | Multi-source production panel (commodity-partitioned). **`production_faostat` is NOT automated** (deferred: its legacy producer wrote canonical pre-gate) — FAOSTAT rows refresh only via manual runs; treat their staleness accordingly. |
| `silver_conab_coffee` | `silver/conab_coffee` | CONAB Brazil coffee surveys per (survey release, region). Revision column floor override 0.30. Cadence: `production_conab` (1st 06:00 UTC). |
| `silver_nass_annual`, `silver_nass_citrus`, `silver_nass_crop_progress` | `silver/nass_*` | US NASS annual production, citrus forecasts (Jan-Jul + Oct-Dec cadence), weekly crop progress/condition (TUE). Crop-progress is the in-season US condition signal. |
| `silver_unica_*` (5 tables) | `silver/unica*` | Brazil center-south sugar/ethanol: biweekly harvest (`release_series` = per-release vintages, `season_history` = final), annual by state, corn-ethanol, monthly ethanol sales. Biweekly release series is PIT-correct; season_history is not (finals only). |
| `silver_sagis_cec` | `silver/sagis_cec` | SA crop estimates committee per (production_year, crop, scope, estimate round) — **REPAIRED 2026-07-18** (task #118): era-aware raw→silver-direct producer, real estimate ordinals (no sentinel-99), post-2007 developing sector + 2002-04 xls era recovered; canonical replaced under approval cec-118-season-repair-20260718 (frozen archived at `_archive/`). Residue: ~72 transition-release docs quarantined pending a per-section reader. Cadence: `sagis_weekly` (FRI 12:00 UTC), restored to the chain. |
| `silver_fnc_colombia_area_department`, `silver_fnc_colombia_monthly` | `silver/fnc_colombia/*` | Colombian coffee area/production. |
| `silver_ams_cotton_quality` | `silver/ams_cotton_quality` | US cotton classing quality, weekly-ish. |

### 2.4 Weather / climate (the PIT-hardened plane)
| Table | S3 prefix | Grain & notes |
|---|---|---|
| `silver_chirps` | `silver/weather/source=chirps` | Precipitation per (commodity, country, region, year→**compacted [commodity, year] objects**, daily rows within). Cadence: `weather_daily` (08:00 UTC). |
| `silver_cpc_soil` | `silver/weather/source=cpc_soil` | Soil moisture, same layout/cadence. |
| `silver_nasa_power` | `silver/weather/source=nasa_power` | Temperature/radiation, same layout/cadence (nasa legs run on Glue Python Shell). |
| `silver_modis_ndvi` | `silver/weather/source=modis_ndvi` | Vegetation index (16-day composites) per (commodity, country, region, year). FLAT, LIST-discovered. Cadence: `modis_biweekly` (MON 09:00 UTC — weekly cron, deliberate over-schedule; delta fetch makes extra runs cheap). CLASS-B: scheduled runs publish **shadow only** + gate; canonical promotion is currently a manual step until the W4 upgrade. |
| `silver_noaa_oni` | `silver/weather/source=noaa_oni` | **El Niño/La Niña**: Oceanic Niño Index, monthly, 1950→present (917 rows). Cadence: `enso_monthly`. |
| `silver_noaa_iod` | `silver/weather/source=noaa_iod` | Indian Ocean Dipole DMI, monthly. |
| `gold_weather_z` | `gold/weather_z` | **Tall** PIT-safe z-anomalies per (commodity **contract slug**, country, region, year, month, metric). One file per contract (31). Rebuilt at the END of each weather_daily run from the **previous** promote's canonical → **one-cycle lag by design**; never treat it as same-day fresh. Columns: commodity, country, region, year, month, metric, value. |

Weather chain data flow (why `_staging` exists): per-source b2s write month-grain to
`silver/weather/source=<s>/_staging/`, the 3 compaction tasks read canonical ∪ staging, merge
within-year, publish the coarse `[commodity, year]` object canonically (through the gate), then
delete consumed staging. Feature extractors and gold must ONLY list `.../commodity=.../year=...`.

### 2.5 Prices / positioning / macro
| Table | S3 prefix | Grain & notes |
|---|---|---|
| `silver_futures_prices` | `silver/futures_prices` | **yfinance EOD only** (front-month-style continuous per contract slug): OHLCV, daily, Mon-Fri 23:00 UTC. NO intraday, NO options, NO full curve (quandl/CHRIS retired 2026-07-17 — Nasdaq paywalled; curve depth is a vendor roadmap item). |
| `silver_cot` | `silver/cot` | CFTC Commitments of Traders per (contract, trader class, week). FRI 20:30 UTC. Bronze loader is fail-closed (2026-07-17): a corrupt bronze file kills the run rather than shipping partial silver. |
| `silver_fred_fx` | `silver/fred_fx` | FX daily (BRL, ARS, CNY, EUR, ZAR, CAD ...) from FRED. Cadence: `fx_macro_daily` (Mon-Fri 18:00 UTC). Source-identity ADR: series are FRED-native IDs mapped to platform slugs. |
| `silver_food_cpi` | `silver/food_cpi` | World Bank food CPI, monthly, by country. |
| `silver_pink_sheet` | `silver/pink_sheet` | World Bank Pink Sheet commodity benchmark prices, monthly. |
| `silver_model_predictions` | `silver/model_predictions` | **Model OUTPUT plane** (partitioned by model_family): where certified predictions land. Producers: the training/certification stack, not ingest. Never use as a feature without explicit leakage review. |

---

## 3. Non-tabular data planes

### 3.1 Text layer — `text/`
One `document.json` per source doc: `full_text` + `extraction_method`. **No OCR confidence is
retained** — GraphRAG reads this layer and never re-OCRs. Scanned-era WASDE (1973-98) got a
Textract page-index pass (W1b) enabling PDF click-to-page.

### 3.2 GraphRAG evidence store — `graphrag_evidence/`
- S3 source of truth: 24 commodity + 92 driver slices + master doc cache; ~531K rows,
  2,573 chunks; `_raw/` archive re-routes free — **NEVER re-chunk** (chunking is the expensive
  step; batch outputs persist 29 days).
- Serving default backend: **pgvector on RDS** (t4g.micro, ~279K props, `EVIDENCE_BACKEND=pg`),
  VPC-only. S3 remains the rebuild source. No ANN index by design (exact scan is fine at this size).
- Eval/census artifacts: `graphrag_evidence/eval/` (e1_census, parity reports).
- Dark-driver semantics: 142/356 DAG ids have no narrative slice **by design** (waivers —
  many are numbers-lane series like FX). Metric to quote: evidence depth (41K routed props),
  not dark %.

### 3.3 Gate baselines — `cascade_census/rolling/<schedule>/census.json`
Rolling per-family census the `silver_rebuild_gate` compares against. Fail-closed on missing
baseline. Never hand-edit; re-seed via the census tooling with timestamped archives.

### 3.4 Reports — `reports/` (repo) and `s3://.../graphrag_evidence/eval/`
`reports/silver_readiness/` holds gate runs, runbooks (`R4_incident_runbooks.md`), value-census
artifacts. Treat as append-only evidence.

---

## 4. Orchestration context (affects freshness expectations)

- **One parameterized Step Functions machine**: `leviathan-dev-silver-thin-contract`
  (fetch → bronze → silver[shadow] → census gate → promote → reconcile), Maps serialized
  (`MaxConcurrency=1` — descriptor array order IS execution order).
- **22 EventBridge schedules ENABLED** (as of 2026-07-17). Classes:
  - CLASS-A `autonomous`: gate-green → KMS-signed canonical promote, no human.
  - CLASS-B `stop_and_notify` (e.g. modis): shadow+gate only; canonical is manual until W4.
- Failures: gate-red → `FailNotify` (SNS email) with canonical untouched; scheduler-level
  failures → `leviathan-dev-scheduler-target-errors` alarm (runbook R4).
- Idempotency: every fetcher is skip-existing; re-running a chain is safe and cheap.
- **Expect data lag = cadence + chain runtime.** gold_weather_z additionally lags one cycle.

---

## 5. MLflow: infra + how to use it

### 5.1 Infrastructure (as of 2026-07-16 relocation — EC2 is RETIRED)
- **Server**: MLflow **3.14** on **ECS Fargate** (`module.mlflow_fargate`, runs on the existing
  serving cluster; 2 gunicorn workers, 4GB). Image: baked `docker/mlflow/Dockerfile` →
  ECR `leviathan-dev-mlflow` (rebuild via `scripts/build_push_mlflow.ps1`).
- **Backend store**: the shared RDS Postgres — DSN injected from Secrets Manager
  (`backend_dsn_secret_arn`); the container runs ONLY
  `mlflow server --backend-store-uri $MLFLOW_BACKEND_STORE_URI --default-artifact-root
  $MLFLOW_DEFAULT_ARTIFACT_ROOT --host 0.0.0.0 --port 5000`.
- **Artifact root**: `s3://leviathan-dev-shahem-001/mlflow/artifacts/` (clients write S3
  directly — jobs need S3 perms for that prefix, not just network access to the server).
- **Two access paths**:
  - In-VPC (jobs/agents): `http://mlflow.leviathan.local:5000` (Cloud Map private DNS).
    This is the `MLFLOW_TRACKING_URI` baked into the train/certify jobdefs.
  - Humans: `https://mlflow.leviathanconvexity.com` — ALB with **Cognito (Google sign-in)**
    auth, reusing the serving wildcard cert. Kill-switch: `mlflow_public_https=false` falls
    back to HTTP:80 locked to admin CIDRs.
- **Laptop cannot reach** `mlflow.leviathan.local` (VPC-only). Local scripts either use the
  public HTTPS URL with auth, or run inside Batch (preferred — see cloud-first rule).

### 5.2 Logging conventions
- Trainer entrypoint: `jobs/batch/train_commodity.py` — `--tracking-uri` (defaults to
  `$MLFLOW_TRACKING_URI`), `--experiment` (default **`leviathan-tier1-production`**),
  `mlflow.set_experiment(...)` then per-run params/metrics/artifacts including the
  **experiment review bundle** (`log_experiment_review_bundle`) — diagnostics parquet/JSON
  mirrored under `data/feature_diagnostics/<runstamp>_<hash>_<phase>_.../` locally in the job.
- Jobdefs with tracking pre-wired: `register_train_jobdef.py`,
  `register_candidate_certification_jobdef.py`, `register_snapshot_candidate_certification_jobdef.py`
  (all set `MLFLOW_TRACKING_URI=http://mlflow.leviathan.local:5000`).
- Run hygiene for the agent: one MLflow run per (model_family, commodity, feature_set,
  train_window); log the corpus/data fingerprints you trained against (silver object
  LastModified max or census snapshot) so PIT reproducibility survives silver refreshes.

### 5.3 Operational rules (learned the hard way — do not relearn)
1. **Content-check images, never trust tags.** The trainer image once baked 4-commit-stale
   source because the docker build context was the caller's cwd; and its Dockerfile pinned
   `xgboost>=2.0,<3` overriding pyproject (fixed to `>=3.2,<4` on 2026-07-17). After ANY
   rebuild: `docker run --entrypoint python <img> -c "import xgboost, inspect, ..."` and
   assert the markers you depend on.
2. **Local functional test before deploying the MLflow image** (standing rule from the 5-layer
   relocation RCA): run the container locally against a scratch backend and hit /health before
   `-target=module.mlflow_fargate` applies.
3. **Terraform: ALWAYS `-target`.** Full applies have known destructive drift.
4. **Compute placement**: training/eval/embedding runs belong on Batch/Fargate, not the laptop
   (standing user directive). Batch job roles already carry the artifact-prefix S3 perms.
5. **Athena from training feature builds**: respect the sargable-predicate rule (§0.3) — the
   LIST-storm was triggered by a *feature pipeline's* vintage guard.

### 5.4 Quick env block for a job that trains + logs
```
MLFLOW_TRACKING_URI=http://mlflow.leviathan.local:5000   # in-VPC only
LEVIATHAN_BUCKET=leviathan-dev-shahem-001
AWS_REGION=us-east-1
EVIDENCE_BACKEND=pg                                       # if touching GraphRAG evidence
```

---

## 6. Fast path/prefix reference

```
raw/production/source=<src>/...                    fetcher output (per-source shapes)
raw/weather/source=<src>/...                       weather fetcher output; modis adds run_id=<rid>/
bronze/production/source=<src>/...                 parsed source-shaped parquet
bronze/weather/source=<s>/commodity=<c>/.../year=  cumulative typed weather (modis = YEAR-grain objects)
silver/<table-specific — see §2>                   canonical analytical surface
silver/weather/source=<s>/commodity=<c>/year=<y>/  compacted canonical weather ([commodity,year])
silver/weather/source=<s>/_staging/                b2s→compact handoff (never read)
silver/**/_shadow/                                 unpromoted publish stage (never read)
gold/weather_z/<contract>.parquet                  z-anomalies, one file per contract slug
text/.../document.json                             full_text + extraction_method
graphrag_evidence/...                              evidence slices/chunks/eval (don't re-chunk)
cascade_census/rolling/<schedule>/census.json      gate baselines
mlflow/artifacts/...                               MLflow artifact store
```

*Maintained by the platform session of 2026-07-17. Verify volatile claims (revisions, image
tags, schedule states) against live AWS + the registry before load-bearing use.*
