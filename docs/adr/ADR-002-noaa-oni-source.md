# ADR-002 — NOAA ONI producer: the source of record for `silver_noaa_oni`

- **Status:** Accepted
- **Date:** 2026-07
- **Phase:** Ultimate Data Plan Milestone R3, SILVER-F057 (full-orphan producer rebuild).

## Context

`silver_noaa_oni` is consumed across the platform — the numbers stack (`silverleg.py`,
`numbers/agent.py`, `tables.yaml#silver_noaa_oni`, `cascade_map.yaml#oni_climate`) and the
feature layer (`macro_climate.compute_oni_climate` / `compute_oni_lag`) — yet the plan's recon
(C-WRONG-8) found **no `fetch_noaa_oni` and no ONI bronze→silver module** in the tracked estate:
the live silver (`silver/weather/source=noaa_oni/part-000.parquet`, 915 rows, DJF 1950 …
FMA 2026) was produced by code that no longer exists. F057 rebuilds the producer **from
scratch**, reversing the source, grain and every derived column from the physical schema. This
ADR records the source decision the plan requires.

The ONI (Oceanic Niño Index) is NOAA's canonical ENSO state: the 3-month running mean of the
ERSSTv5 sea-surface-temperature anomaly in the Niño-3.4 region (5°N–5°S, 120°W–170°W), with an
El Niño classified at ONI ≥ +0.5 °C and a La Niña at ≤ −0.5 °C. Several NOAA surfaces expose it.

## Options

| # | Source | Shape | Verdict |
|---|---|---|---|
| A | **CPC ascii record** `https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` | one row per overlapping 3-month season (`SEAS YR TOTAL ANOM`), **2-decimal** ANOM, DJF 1950→present, updated monthly in-place, no auth | **chosen** |
| B | CPC website ONI table (`ensostuff/ONI_v5.php`) | HTML matrix, **1-decimal** rounding | rejected |
| C | Raw Niño-3.4 monthly file (`detrend.nino34.ascii.txt`) | monthly SST + anomaly; ONI must be re-derived (3-month running mean + base-period logic) | rejected |

## Decision

**Adopt Option A — the CPC `oni.ascii.txt` record — as the single source of truth.**

Deciding evidence (matched against the live physical silver before writing a line of the
producer):

- The physical `oni_anom` is **2-decimal** and reproduces the ascii file exactly — e.g. the
  DJF 1950 anomaly is **−1.53**, which is the ascii file's first data row (`DJF 1950  24.72
  -1.53`). Option B publishes −1.5 (rounded); Option C would require us to re-implement NOAA's
  running-mean + shifting-base-period computation and would not byte-match.
- The physical `season` axis is exactly the ascii file's 12 overlapping 3-month labels
  (DJF…NDJ), each stamped to its **center month** in the silver (`DJF→1 … NDJ→12`), agreeing
  1:1 across all 915 rows.
- The record carries the **full history from DJF 1950** in every monthly release, so a single
  overwrite fetch (mirroring `fetch_noaa_iod.py`) always yields the complete series — no
  incremental/append state, no vintage retention needed (`vintage_retention: latest-only`).

Rejected: **B** loses a significant digit of precision that the downstream flags and lag
features depend on near the ±0.5 thresholds; **C** re-derives a NOAA product we can consume
directly, adding a base-period re-implementation risk (NOAA rebaselines the ONI every 5 years)
for no benefit.

## Consequences

- Producer stack: `jobs/ingest/fetch_noaa_oni.py` (raw + bronze),
  `transforms/raw_to_bronze/noaa_oni.py`, `transforms/bronze_to_silver/noaa_oni.py`,
  `jobs/batch/noaa_oni_task.py` (silver via the SILVER-F015 shadow publisher). The b2s transform
  reproduces the live silver **bit-for-bit** (validated in `tests/unit/test_transforms_noaa_oni.py`
  against the 915-row physical table).
- **Freshness/revision note:** NOAA rebaselines the ONI to a new 30-year climatology every ~5
  years, which slightly revises historical anomalies (e.g. the physical FMA 2026 = 0.11 vs the
  current-file 0.13). Because the source ships the whole history each month, a re-run simply
  adopts the latest vintage — expected and correct under `latest-only` retention; it is not a
  bug and the freshness contract (SILVER-V002) tolerates it.
- **Source identity is truthful** (unlike the FRED-FX `frankfurter` case, OP-6): the physical
  `source` column already reads `noaa_oni` and the URL is the genuine origin; no aliasing.
