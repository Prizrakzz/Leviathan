# ADR-003 -- `silver_fred_fx` source identity (SILVER-F040 / OP-6)

- **Status:** Accepted (2026-07-12)
- **Package:** SILVER-F040 (Ultimate Data Plan, Milestone R3)
- **Supersedes/relates:** OP-6 probe (`reports/silver_readiness/20260712_p65impl/probes/OP-6_fred_fx_source.json`), C-WRONG-8 (the orphan taxonomy)
- **Deciders:** silver-platform / numbers-platform

## Context

`silver_fred_fx` is an **orphan table**: it is consumed by the numbers `TableSpec`
(`configs/graphrag/numbers/tables.yaml#silver_fred_fx`), `cascade_map.yaml`
(`fred_fx_macro`), the pg mirror (`P1_TABLES`), and `features.yaml` (`fred_fx`), but there
is **no producer in the tracked estate** -- no `fetch_fred*`, no bronze->silver module, no
Batch task (confirmed C-WRONG-8; only aspirational FRED-shaped path helpers
`raw_fred_fx_key(series_id)` -> `raw/fx/source=fred/{series_id}.csv` exist, never wired to a
producer). Until a producer exists, the table cannot be regenerated deterministically.

**The provenance question (OP-6, CONFIRMED).** The physical silver object
(`silver/fred_fx/part-000.parquet`, 5,508 rows, 2004-12-31 -> 2026-06-04) carries
`source='frankfurter'` for **every** row -- not `FRED`. Yet the table name, the S3 path, the
FRED-shaped raw path helpers, and the numbers `TableSpec` unit labels
(`"BRL per USD (FRED)"`, `"Daily FX rates (FRED)"`) all name the provider as **FRED**. This is
a provenance mislabel that must be reconciled before the contract is frozen and a producer
built.

Physical columns (confirmed): `date, brl_usd, brl_usd_pct_change_90d, ars_usd,
ars_usd_pct_change_90d, cny_usd, cny_usd_pct_change_90d, source`. Sample values are the real
market rates (2004-12-31: BRL 2.6577, ARS 2.9733, CNY 8.277 -- CNY at its pre-2005 peg 8.2765).

### Forces

1. **Truthful-to-history:** all 5,508 existing rows were produced by Frankfurter (ECB
   reference-rate proxy). Re-sourcing from FRED would change historical values (different
   fixing/publication methodology) -- inventing a history the table never had.
2. **Reproducibility:** Frankfurter's public time-series endpoint deterministically returns
   the full history for the ECB currencies (BRL, CNY) on every request. FRED (St. Louis Fed)
   publishes `DEXBZUS` (BRL/USD) and `DEXCHUS` (CNY/USD) daily.
3. **The ARS gap (load-bearing):** ECB reference rates -- and therefore Frankfurter -- **do
   not include ARS** (Argentine peso). FRED **also has no clean daily ARS/USD spot series**
   (there is no `DEXARUS`). Yet the existing data carries plausible ARS values under
   `source='frankfurter'`, so the true ARS upstream is **unverified** by either candidate.
4. **Value-correctness:** the platform's consumers already depend on all three currencies. A
   FRED-only source that dropped ARS to null (INV-4: an absent measure stays null, never
   synthesized) would make `ars_usd` census-red -- an honest but disruptive regression of a
   currently-populated column.
5. **Consumer blast radius:** the table name / S3 path / `TableSpec` labels are referenced by
   the numbers registry, cascade map, pg mirror, and features config. A physical rename is a
   breaking cross-consumer migration (INV-8) and is out of scope for a single producer build.

## Decision

1. **Source of record = Frankfurter** (`frankfurter.dev`, ECB-published reference rates). It
   is the true provider of every historical row, is deterministically re-fetchable, and keeps
   all three currencies populated (value-correct). This is OP-6 option (a).

2. **The producer stamps `source='frankfurter'` truthfully** on every row and records the
   exact upstream provider, endpoint, base, and requested symbols in the bronze provenance +
   the run manifest. The `source` column is the authoritative provenance and now matches
   reality.

3. **Explicit series mapping + direction (frozen):**
   - `brl_usd` <- Frankfurter `BRL` (base=USD): **units of BRL per 1 USD**.
   - `cny_usd` <- Frankfurter `CNY` (base=USD): **units of CNY per 1 USD**.
   - `ars_usd` <- Frankfurter `ARS` (base=USD): **units of ARS per 1 USD** *if returned*;
     otherwise the column stays **null** (INV-4). Direction convention across all series:
     **local currency per 1 USD** (higher = weaker local currency), matching the existing data
     and the `TableSpec`.

4. **`_pct_change_90d` semantics (frozen):** for each series column `c`, `c_pct_change_90d`
   is the **percent** change (x100) of `c` versus the **last available observation at or
   before `date - 90 calendar days`** -- a **calendar-day** lag, NOT an observation-count lag
   (an obs-count variant would be named `_90obs`). Null when no such prior observation exists,
   or when either endpoint value is null/zero.

5. **Grain / integrity (frozen):** one row per valid source observation date
   (weekends/holidays are **not** synthesized -- only dates the source returns). The silver is
   wide (one row per date); `count(*) == count(DISTINCT date)` is asserted. Conflicting
   duplicate source records for the same (date, currency) **fail closed**.

6. **The table name `silver_fred_fx`, the S3 root `silver/fred_fx`, and the
   `raw/fx/source=fred/` path helpers are retained** as stable identifiers but documented as
   **legacy misnomers**. The producer writes raw/bronze under a truthful
   `.../source=frankfurter/` prefix; only the canonical silver object keeps the historical
   `silver/fred_fx/` location (renaming it is a separate breaking migration).

## Consequences

- **Follow-up (INV-8, not in this lane):** the numbers `TableSpec` unit labels `"(FRED)"`
  are inaccurate and should be corrected to `"(Frankfurter/ECB)"`. This is a consumer-config
  edit (`tables.yaml`) routed through the `silver_rebuild_gate`; it is flagged here and left
  to the consumer-sync owner rather than edited by the producer build (which must not mutate
  another lane's config).
- **ARS caveat (open item for BF-W3):** because neither Frankfurter/ECB nor FRED cleanly
  publishes daily ARS/USD, the `ars_usd` series provenance is the weakest. The producer
  requests ARS from Frankfurter; if the live endpoint returns no ARS the column stays null and
  the value census flags it -- surfacing the gap honestly rather than hiding it. Ratifying the
  authoritative ARS source is a gated BF-W3 backfill decision.
- **A physical rename is deferred**, not rejected. If a future migration renames the table to
  reflect Frankfurter, it must sequence through the full consumer-sync gate (numbers registry,
  cascade map, pg mirror, features, Glue/DDL) with a compatibility window.
- **Backfill:** a `BACKFILLED` catch-up from raw to current follows in BF-W3 (this lane ships
  code + tests + shadow evidence only; no canonical replacement).

## Alternatives considered

- **(b) Re-source from FRED to make the name truthful.** Rejected as the primary source:
  loses ARS (census-red for a currently-used column), changes historical BRL/CNY values away
  from the 5,508-row record, and still leaves ARS unsolved. FRED remains a viable *future*
  cross-check for BRL (`DEXBZUS`) / CNY (`DEXCHUS`).
- **Per-series `source` (FRED for BRL/CNY, Frankfurter for ARS).** Rejected: the wide schema
  has a single table-wide `source` column that cannot truthfully represent a per-series
  provider blend, and it would violate "conflicting duplicate source records fail closed".
- **Physical rename now.** Rejected as out-of-scope breaking cross-consumer change.
