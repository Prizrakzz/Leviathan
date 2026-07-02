# ML Experiment Data Audit — Root Causes of Poor Experiment Performance

**Date:** 2026-07-03 · **Auditor:** GraphRAG-side agent (independent review) · **Code audited:** origin/main @ f5fbc405
**Trigger:** the ESR marketing-year discovery (a silent cross-source label mismatch found while building the GraphRAG SQL agent) prompted a ground-up audit of data prep, preprocessing, and feature engineering.

---

## Executive summary — the honest hierarchy

I reviewed the ingestion transforms, extractors, computations, visibility layer, spine, model-ready builders, target construction, and CV code, plus your own audit docs (Phase 0 audit, anomaly RCAs, feature diagnostics). The headline, stated plainly:

1. **The pipeline engineering is largely SOUND.** Trailing-only trend targets, `shift(1).rolling` z-scores, the `visible_slice` choke point, leakage-column exclusion, grouped walk-forward CV, availability policies, permutation certification — these are all correct. **Do not burn time re-auditing them** (§5 lists everything I verified healthy so you don't).
2. **The #1 cause of poor experiments is statistical, not a bug: sample starvation.** ~44 annual labels per commodity (dense windows as short as 13–15 years for "full" tiers) against 250–450-column feature stacks. No modeling choice can overcome n≈15–44, p≈430. Your own diagnostics already show it (437-feature weather block with 430 features ≥50% missing; best bad-year recall 0.36). §4.1 gives the strategy to actually fix it.
3. **There ARE real semantic landmines of the ESR class** — silent unit-of-time/label mismatches that make features describe a different year than intended, or leak. One is confirmed-likely (ESR), the same *pattern* is unpinned across six more sources. §3 details each with file:line and the fix.
4. Several issues you already know about (PSD fake vintages, WASDE region garbage, coin-flip event labels) need to be *enforced*, not just documented — they currently rely on analyst memory.

**Expected payoff order:** fixing §4.1 (sample strategy) moves metrics the most; §3.1–3.2 (ESR + region whitelist) removes silent wrongness; §3.4 (convention pin-tests) prevents the next six ESR-class incidents for half a day of work.

---

## 1. What triggered this: the ESR discovery (context you need)

While validating the GraphRAG SQL agent against Athena, querying `silver_esr` for soybeans with `market_year = 2023` (the PSD/start-year convention for MY 2023/24) returned **zero rows**, while identical semantics against `silver_psd` return correct data. The fetcher (`jobs/ingest/fetch_usda_esr.py:134`) passes `marketYear` verbatim to the USDA FAS ESR API, and FAS labels row-crop marketing years by their **END year** (soybeans Sep-2023→Aug-2024 = marketYear **2024**). PSD labels by **START year** (same MY = 2023).

**Same physical year, two different integers, depending on which USDA API produced the table.** Any code that equates `market_year` across these sources is silently off by one year.

> Confirmation probe (run once, ~2–5 min full scan each — `commodity_name` is not a partition):
> ```sql
> SELECT market_year, min(CAST(week_ending_date AS varchar)), max(CAST(week_ending_date AS varchar)), count(*)
> FROM leviathan_dev.silver_esr WHERE commodity_name = 'soybeans_cbot'
> GROUP BY market_year ORDER BY 1 DESC LIMIT 6
> ```
> **CONFIRMED 2026-07-03** (direct parquet read of `silver/esr/commodity=soybeans_cbot/`): `market_year=2024` spans week endings **2023-09-07 → 2024-09-05** = MY 2023/24. ESR labels by END year. Note: the Athena GROUP-BY route hit the 30-minute query timeout — read the hive-partitioned parquet directly (seconds). Wheat classes should still be spot-checked the same way.

---

## 2. Impact-ranked findings

| # | Finding | Severity | Class | Status |
|---|---|---|---|---|
| F1 | Sample starvation: n≈15–44 labels vs p≈250–450 features per commodity | **Critical** | statistical | partially known — needs a strategy change, not more gates |
| F2 | ESR marketing-year label convention unpinned → features either 1-yr stale or leaky | **High** | semantic | new |
| F3 | WASDE region taxonomy garbage flows into aggregates unless whitelisted | **High** | data quality | known in audit, not enforced in code |
| F4 | Six more sources' year-label conventions are assumed, never pin-tested | **High** (risk) | semantic | new (pattern generalized from F2) |
| F5 | Event labels at fixed 5/10% thresholds are near coin-flips (38–58% base rate) | Medium | label design | known — finish the migration |
| F6 | PSD "vintage" surface is latest-bulk, not true vintages | Medium | data fidelity | known — keep the block enforced |
| F7 | ESR features broadcast US totals to every origin + z-scores from 3-sample windows | Medium | semantic/statistical | new |
| F8 | Lake heterogeneity: date types (DATE vs varchar), country naming, injected partitions | Low-Med | hygiene | new (bites SQL consumers, not parquet readers) |
| F9 | HPO/eval hygiene at tiny n | Low | methodology | mostly fine — keep guardrails |

---

## 3. Detailed findings and fixes

### 3.1 F2 — ESR marketing-year convention (`src/leviathan/features/computations/esr_exports.py`)

`compute_esr_exports` aggregates weekly ESR rows to **annual totals per `market_year` label**, then selects `mkt_year = crop_year + mkt_year_offset` (line 71; offset −1). The docstring's intent: "the **completed** prior year's export programme, known before the new crop year begins."

The correctness now depends entirely on which convention `silver_esr.market_year` uses:

- **ESR labels by END year (CONFIRMED):** `mkt_year = 2023` for crop-year 2024 selects MY **2022/23** — the intended completed year. So the current feature code is **correct-by-accident**: the label mismatch and the offset cancel. Nothing pins this; the next person to "fix" the offset breaks it silently — which is why the date-mapping rewrite + pin test below still matter.
- **If ESR labels by START year:** `mkt_year = 2023` selects MY **2023/24**, which is *in progress* at May planting — the annual sums then include Jun–Aug-2024 weeks. **That is look-ahead leakage** (unlike the PSD path, this computation has **no `release_date`/as-of cutoff at all** — it sums the whole labelled year).

**Fix (robust to either convention):** stop matching labels; map weeks to marketing years via the crop calendar you already have:
1. Derive each row's marketing year from `week_ending_date` + the commodity's crop calendar (`configs/features/crop_calendars.yaml`), ignoring the source's `market_year` label entirely.
2. Additionally apply a visibility cutoff: only weeks with `week_ending_date < crop_year_start(crop_year)` may enter a feature for that crop year (mirrors the `prior_history` rule every other computation obeys).
3. Pin with a regression test: an ESR row with `week_ending_date = 2024-03-15` for soybeans must land in MY 2023/24 features and be visible only to crop years ≥ 2025 (or 2024 post-planting stages, per your policy).
4. Document the per-source label convention in `docs/FEATURE_DICTIONARY.md`.

**Do not** copy the GraphRAG side's approach (`TableSpec.period_offset` in `src/leviathan/graphrag/numbers/`) — that is a query-compile translation for an interactive agent; the feature pipeline should map by date, which is convention-proof.

A ready-to-run task chip exists for this audit (spawned 2026-07-03: "Audit ESR-PSD market_year join misalignment in features").

### 3.2 F3 — WASDE region garbage must be excluded in code, not by memory

Your own Phase 0 audit quantifies it: per commodity, `unknown_review_required` regions carry **16K–60K rows** and `garbled_parser_artifact` adds hundreds more (rice: 516 unknown regions, 60,723 rows). Any WASDE aggregate or revision feature computed without a quality filter ingests this.

**Fix:** enforce the whitelist at the extractor: keep only `clean_origin` + explicitly reviewed `aggregate_region` entries; quarantine the rest behind a flag. One filter + a re-materialization; add a test asserting no `unknown_review_required` region reaches a feature row. (The quality classification already exists — it just isn't load-bearing yet.)

### 3.3 F4 — pin every source's year convention with contract tests (the ESR pattern, generalized)

The `mkt_year_offset` machinery is sound and well documented (`features/visibility.py:77-98`). But each computation *asserts* a source's year semantics without a test grounded in real data:

- `trade_flows.py` — CONAB safra year (`safra 2023/24` ↔ which crop_year?)
- `phase7_fundamentals.py:141,274,322,395` — NASS citrus season, SAGIS/CEC season, UNICA harvest year
- FGIS shipment years, WAP release years, MPOB calendar months → MY mapping
- FAOSTAT calendar years vs crop years

One of these being wrong looks exactly like ESR did: features quietly describing the wrong year, models mysteriously flat. **Fix (cheap, ~half a day):** one "convention pin test" per source — take one real, hand-verified row (e.g. "CONAB safra 2023/24 survey 5 belongs to crop_year 2024") and assert the computation places it there. Plus a one-page conventions table in `FEATURE_DICTIONARY.md` (start from the appendix below).

### 3.4 F1 — sample starvation: the strategy, not another gate

The numbers from your own artifacts: `training_windows.md` shows corn_cbot "full" = 431 features on a 15-year dense window; the diagnostics table shows `inseason_weather` at 437 features/173 rows with 430 features ≥50% missing; best bad-year negative recall across sets: 0.36. No detector/model tweak fixes p≫n.

**Strategy (in order of expected lift):**
1. **Snapshot-first.** The WASDE snapshot pipeline multiplies effective samples ×~8–12 (monthly releases per MY) with honest point-in-time structure — you built it; make it the primary experiment surface and treat annual-spine experiments as diagnostics only.
2. **Pool across commodities and origins.** One global model over all commodity×origin panels with `commodity`/`origin` as categoricals (LightGBM handles natively) turns ~44 rows into thousands. The reusable-blocks taxonomy you already wrote is exactly the shared feature space this needs. Per-commodity models remain as baselines to beat, not the default.
3. **Feature budgets as a hard gate:** cap features per experiment at ~n/10 (annual: ≤5–15 features; snapshot: ~50). Reject composites over budget in certification — mechanically, like the quality gates.
4. **Baselines define success:** every run must beat `prior_year_anomaly_baseline` and `trailing_mean_anomaly_baseline` (already computed in the target rows) out-of-fold before any deeper claim.

### 3.5 F5 — finish the event-label migration

Phase 0 shows `fixed_5pct`/`fixed_10pct` base rates of 38–58% — predicting those "events" is coin-flip territory, and the RCAs' "detector_overalerts_benign_cases" is the same problem from the other side. `history_quintile` (20% base rate) is the right family. **Fix:** deprecate fixed-threshold labels in serious runs (leave for diagnostics), evaluate with PR-AUC/F2 at explicit cost ratios (you already log F2), never accuracy.

### 3.6 F6 — keep the PSD-vintage block load-bearing

You already concluded `silver/psd` is latest-bulk, not true monthly vintages, and blocked `psd_monthly_vintage_features`. Two reinforcements: (a) make the block a **code-level** guard (certification rejects any feature set containing `psd_*_mom_revision` until a true-vintage source exists), not a doc note; (b) the same caveat applies to *any* new feature that implicitly assumes PSD history is as-published (e.g. "revision since first estimate" style features).

### 3.7 F7 — ESR feature provenance + tiny z windows

`esr_exports.py:77-83` broadcasts the same US-programme z-scores to **every origin country row** — for multi-origin commodities, Brazil/Argentina rows carry US export z-scores under a name that doesn't say so. Rename to `esr_us_*` (or emit only for `united_states`) so pooled models (§3.4-2) don't learn a fake origin signal. Separately, `trailing_baseline_z(window_years=5, min_years=3)` computes z-scores from as few as **3 annual observations** — that is noise wearing a z-score's clothes; widen to the 30y/5min defaults used elsewhere (`base.py`) or switch to percentile ranks.

### 3.8 F8 — lake hygiene (affects SQL consumers and future you)

Found while building the SQL agent; parquet-reading extractors are unaffected, but every Athena/ad-hoc consumer trips on these:
- **Date types are heterogeneous:** `silver_nasa_power.date`, `silver_esr.week_ending_date` are true DATEs; `silver_psd.release_date`, `silver_esr.as_of_date` are varchar. Comparisons fail with TYPE_MISMATCH unless cast.
- **Country naming differs per table:** snake_case (`united_states`) in weather/geographies/WASDE-snapshot keys; display case (`United States`) in PSD.
- **`silver_nasa_power` uses injected partition projection** on `commodity/country/region` — every query MUST carry static equality on each or Athena refuses.
- **`silver_esr` full-scans on GROUP BY/DISTINCT** (no useful partitioning) — multi-minute queries that also hog Athena concurrency.

**Fix:** document all four in `configs/datasets/source_contracts.yaml` (or FEATURE_DICTIONARY); longer-term, normalize date types at silver and consider partitioning silver_esr by commodity_name.

### 3.9 F9 — evaluation hygiene at tiny n (mostly fine; keep it that way)

Verified good: clone-per-fold models, no global imputation/scaling (LightGBM-native NaN), permutation certification (20 trials), grouped walk-forward with `GROUP_KEY` (prevents same-MY snapshot rows straddling folds). Keep: HPO minimal or absent at these sizes (a hyperparameter search over ~40 annual samples selects noise); prefer fixed shallow trees + regularized linear baselines; always report per-fold dispersion, not just means.

---

## 4. Verified HEALTHY — do not re-audit

| Component | Verdict | Evidence |
|---|---|---|
| Target construction | Clean, trailing-only | `psd_target_builder.py:186-205` — trend fit strictly on `year < target_year`; baselines trailing |
| Feature z-scores (core) | Prior-only | `computations/base.py:77-78` — `shift(1).rolling(...)` |
| Point-in-time choke point | Sound design | `visibility.py` — all silver access via `visible_slice`; PSD prior-MY + `release_date <= crop-year start`; handles the bulk-CSV partial-release trap (lines 86-91) |
| Model-ready leakage guards | Present | `TARGET_LEAKAGE_COLUMNS`/`PREFIXES` excluded in `wasde_snapshot_cv.py:16-19,83+` |
| CV structure | Grouped walk-forward, clone per fold | `wasde_snapshot_cv.py` |
| Static feature availability | Policy-enforced | `wasde_snapshot_static_join.py:245+` incl. `MARKET_SIGNAL_PATTERNS` excludes |
| Static join year semantics | Label-consistent for US row crops | `target_market_year` ↔ spine `crop_year` share the PSD start-year numbering (verify per-commodity for southern hemisphere via §3.3 pin tests) |
| Country standardization (PSD/FAOSTAT) | Correct | `extractors.py:512-516` + `_FAOSTAT_COUNTRY_ALIASES` |
| Imputation | None global | grep-verified: only label/weight fillna |

---

## 5. Efficient fix order (dependency-aware)

| Step | Work | Effort | Why this order |
|---|---|---|---|
| 1 | Run the §1 probe; pin ESR convention; rewrite `esr_exports` to map by `week_ending_date` + crop calendar; regression test | ~half day | Removes a live leak-or-stale landmine; probe unblocks everything ESR |
| 2 | WASDE region whitelist in the extractor + re-materialize + test | ~2 hrs | One filter kills the largest known contamination |
| 3 | Convention pin-tests for CONAB/NASS/UNICA/SAGIS/FGIS/WAP/MPOB + conventions table in FEATURE_DICTIONARY | ~half day | Prevents the next six ESR-class incidents; enables trusting §3.3 joins |
| 4 | Event labels → quintile/severity only in serious runs; PR-AUC/F2 reporting | ~2 hrs | Makes every subsequent experiment readable |
| 5 | Feature-budget gate in certification (≤n/10) + `esr_us_*` rename + z-window widening | ~half day | Cheap statistical honesty |
| 6 | Snapshot-first + pooled global model experiment (commodity/origin categoricals, shared blocks) | the real work | The only change with the leverage to move headline metrics |
| 7 | Hygiene docs (source_contracts/FEATURE_DICTIONARY) for §3.8 | ~1 hr | Stops future SQL consumers re-losing days |

Steps 1–5 are prerequisites in spirit: they make step 6's results interpretable. Doing 6 first on today's labels/features would produce another round of unreadable experiments.

---

## Appendix A — conventions table (seed; complete during step 3)

| Table | Year column | Convention | Country style | Date col types | Notes |
|---|---|---|---|---|---|
| silver_psd | market_year | MY **START** year (2023 = 2023/24) — verified | Display ("United States") | release_date: varchar | latest-bulk, NOT true vintages |
| silver_esr | market_year | **END year (CONFIRMED 2026-07-03)** | n/a (country_code int) | week_ending_date: DATE; as_of_date: varchar | one latest as_of snapshot per MY; full-scans on GROUP BY |
| silver_wasde | marketing_year | "2023/24" string | region taxonomy incl. garbage classes | release_date | quality classes exist — enforce |
| silver_nasa_power | (daily) | n/a | snake (united_states) | date: DATE | injected partitions: commodity/country/region equality REQUIRED |
| silver_production (FAOSTAT) | year | calendar year | snake after aliases | ingest_date | aliases in extractors.py:459 |
| CONAB / UNICA / SAGIS / NASS / WAP / FGIS / MPOB | various | **UNPINNED — step 3** | various | various | one pin-test each |

## Appendix B — what the GraphRAG side already fixed (don't duplicate)

- Athena `TYPE_MISMATCH` on DATE columns → CAST guard in `graphrag/numbers/query.py` (agent-side only).
- `silver_nasa_power` injected-partition equalities + snake-case country + per-commodity default station from `configs/geographies/`.
- ESR label translation for interactive lookups via `TableSpec.period_offset` (agent-side; features should use date-mapping instead, §3.1).
