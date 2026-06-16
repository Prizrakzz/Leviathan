# Feature Engineering Pre-Flight Checklist

Every new feature family must pass every gate below **in order** before being
merged into `features.yaml`.  A gate failure is a hard stop — fix the root
cause, do not paper over it.

Mistakes that prompted this document:
- `wasde_production_revision` / `wasde_stocks_revision`: added to the registry
  before verifying PSD bulk download has one snapshot per key, making `diff(1)`
  always NaN.
- Cocoa / FCOJ fan-out: assumed PSD commodity codes existed without checking.
- `stage_precip_z` range: set `[-6, 6]` by intuition; real data hit 8.29.
- ESR argparse: used `action="store_true"` which AWS Batch rejects.

---

## Gate 0 — Drop criteria (evaluate before writing any code)

Ask these four questions. A "yes" to any one is a hard drop.

| Question | Why it kills the feature |
|---|---|
| Does silver have < 5 crop years of data for this commodity? | Insufficient history for walk-forward CV; z-scores need ≥ 3 years (5 preferred) |
| Is the feature > 50 % null in the training window (1990–present)? | A feature that is missing for half the training window teaches nothing and inflates sparsity |
| Can I not guarantee a fresh value at the feature store cutoff date without custom scheduling? | Stale features at inference time contaminate live predictions |
| Would computing this feature require data not yet in silver? | Never register a feature against a silver table that does not exist yet — the spine job will silently emit nothing |

If all four are "no", proceed to Gate 1.

---

## Gate 1 — Silver data audit (read S3, not assumptions)

Before writing a single line of extractor or computation code, run this audit
against the actual silver parquet files.

```python
import boto3, io
import pandas as pd
import pyarrow.parquet as pq

s3 = boto3.client("s3")
bucket = "leviathan-dev-data"

def audit_silver(prefix: str) -> pd.DataFrame:
    keys = [
        o["Key"]
        for o in s3.get_paginator("list_objects_v2")
               .paginate(Bucket=bucket, Prefix=prefix)
               .search("Contents[].Key")
        if o
    ]
    frames = []
    for k in keys[:5]:  # sample first 5 partitions
        data = s3.get_object(Bucket=bucket, Key=k)["Body"].read()
        frames.append(pq.read_table(io.BytesIO(data)).to_pandas())
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

df = audit_silver("silver/<source>/")
```

Record all of the following **before proceeding**:

- [ ] Total row count
- [ ] Date / year range (`df["market_year"].agg(["min","max"])` or equivalent)
- [ ] Granularity: one row per (key, year)? or multiple per year?
- [ ] Null rate on every column I plan to use:
  `df[cols].isnull().mean().round(3)`
- [ ] Slug / commodity coverage:
  `df.groupby("leviathan_slug").size().sort_values()` — **every slug listed in
  `features.yaml` commodities must appear here**
- [ ] Whether multiple temporal snapshots exist per key (required for revision
  / diff features):
  `df.groupby(["leviathan_slug","country","market_year"]).size().describe()`

**Red flags that must be resolved before continuing:**

| Observation | Action |
|---|---|
| A slug in `commodities:` has zero rows | Remove that slug, or add it to the bronze→silver fan-out and rerun |
| Only one row per (key, year) | You cannot compute a revision / diff feature; drop it |
| Null rate > 50 % on the column you plan to use | Find a different column, aggregate from a lower level, or drop the feature |
| Year range starts after 2005 | Flag as short-history; note in yaml comment; z-scores unreliable before min 5 data points |

---

## Gate 2 — Granularity alignment

The spine is annual: **one scalar per (country, crop_year)**.

Map the source granularity to an aggregation strategy before writing any code:

| Source cadence | Strategy | Common pitfall |
|---|---|---|
| Annual (one row per year) | Direct lookup — no aggregation needed | Verify year definition matches crop-year, not calendar year |
| Monthly (12 rows per year) | Sum, mean, or last within the marketing year window | Do not average over a partial marketing year — filter to complete years only |
| Weekly (52 rows per year) | Annual aggregate (sum / mean) then 5-yr trailing z-score | Check that you aggregate first, then z-score — never z-score before aggregating |
| Daily | Rolling window to monthly or seasonal bucket, then aggregate to annual | Huge memory footprint; filter by crop stage first |
| Multi-year (e.g., biennial) | Repeat the value for each crop year in the window, or derive an annual YoY | Never leave NaN for off-years — if the source is biennial, interpolate or drop |
| Single snapshot (bulk file) | Only current-vintage values are available — no revision / diff possible | **This killed WASDE revisions.** Check explicitly: `df.groupby(key_cols).size().max()` — if always 1, there is no temporal depth |

---

## Gate 3 — Point-in-time correctness

Every feature must pass **exactly one** of these visibility classes without
leaking future information:

| Class | Definition | When to use |
|---|---|---|
| `crop_year_direct` | In-season data from within crop year Y | Weather (CHIRPS, NASA POWER), crop-progress indices |
| `prior_history` | All observations strictly before crop year Y starts | ESR annual aggregates, ENSO/IOD state, COT positioning, FAOSTAT production |
| `prior_marketing_year` | The most recent WASDE/PSD vintage published on or before crop-year start | PSD S/D balances, CONAB revisions |

Checklist:
- [ ] I know which visibility class this feature uses
- [ ] The `visible_slice()` call in the computation uses that class
- [ ] The cutoff date is based on `crop_year_start(Y)` from `crop_calendars.yaml`, not on a hardcoded date
- [ ] If the source is timestamped (weekly / monthly), I filter `timestamp < cutoff` — never `<=`
- [ ] I have confirmed the source actually has data available before the cutoff for at least 80 % of crop years in the training window

---

## Gate 4 — Normalization standard

Raw volumes and quantities must **never** reach the spine unnormalized.

| Value type | Required normalization | Reason |
|---|---|---|
| Volume / quantity (tonnes, bags, bushels) | 5-yr trailing z-score | Absolute scales differ by orders of magnitude across commodities and countries |
| Price level | 5-yr trailing z-score | Nominal prices drift; model needs relative position |
| YoY % change | Acceptable as-is if bounded; add value_range | Already dimensionless, but can explode on small bases |
| Ratio (S/U ratio, utilization rate) | Acceptable as-is; add value_range | Already dimensionless |
| Binary flag (0/1) | No normalization; value_range: [0.0, 1.0] | Already bounded |
| Z-score already computed upstream | Verify no double-normalization; value_range: [-10, 10] default | Check silver column names for `_z` or `_zscore` suffix |

**Trailing z-score formula** (never use full-sample statistics — that leaks):
```python
rolling = series.shift(1).rolling(window, min_periods=3)
z = (series - rolling.mean()) / rolling.std()
```
`shift(1)` excludes the current year.  `min_periods=3` prevents NaN for the
first years but note values are unreliable until at least 5 data points.

---

## Gate 5 — Value range calibration

Never set `value_range` by intuition.  Always derive it from real computed
output on the full silver history.

```python
result = compute_my_feature(ctx, spec)
print(result["value"].describe(percentiles=[.01, .05, .95, .99]))
```

Set `value_range` to approximately **[p1, p99]**, then round outward to the
nearest clean number.  Give 20–30 % headroom beyond observed extremes for
future data.

- Z-scores: default to `[-10.0, 10.0]`.  Tighten to `[-6.0, 6.0]` only after
  confirming no legitimate extreme event exceeds it.
- Ratios: derive from data, never assume [0, 1].
- Leave `value_range: null` only for features where unbounded values are
  genuinely expected (e.g., raw precipitation totals before they exist in
  silver).

The spine's hard-fail validator rejects any row outside `value_range`.  A
value that is "just barely" outside range means the range was wrong, not the
data.

---

## Gate 6 — Commodity slug coverage verification

Before registering any commodity in `features.yaml`, run:

```python
# Silver slug coverage
slugs_in_silver = set(df["leviathan_slug"].unique())

# Slugs you plan to register
planned = {"corn_cbot", "soybeans_cbot", ...}  # from your yaml draft

missing = planned - slugs_in_silver
if missing:
    raise ValueError(f"These slugs have no silver data: {missing}")
```

- [ ] Every slug in `commodities:` is present in silver with > 0 rows
- [ ] Run `df.groupby("leviathan_slug")["market_year"].agg(["min","max"])` and
  verify each slug has sufficient history
- [ ] If using `commodities: all` or `commodities: calendar`, audit the full
  slug list from `commodities.yaml` / `crop_calendars.yaml` against silver

Do not add a slug to `commodities:` with the plan to "add it to silver later."
The spine job runs immediately on the current silver state and will silently
produce NaNs.

---

## Gate 7 — Local dry run before Batch submission

Compute the feature locally on real silver data (sampled or full) and verify:

```python
# Must all be True before registering in features.yaml

non_null_rate = result["value"].notna().mean()
assert non_null_rate >= 0.80, f"Non-null rate {non_null_rate:.1%} — below 80% threshold"

assert result["value"].between(*value_range).all(), "Value range violation"

dupe_keys = result.duplicated(subset=["country","crop_year","feature"])
assert not dupe_keys.any(), f"Duplicate natural keys: {dupe_keys.sum()}"

assert (result["value"] != 0).mean() > 0.05, "Feature is suspiciously all-zero"
```

Only after all four assertions pass is the feature ready for `features.yaml`.

---

## Gate 8 — AWS Batch job patterns

Any new bronze→silver task that runs in AWS Batch must follow these rules:

**Argparse: never use `action="store_true"` for Batch parameters.**

Batch parameter substitution always injects the string `"true"` or `"false"`.
`action="store_true"` treats that string as an unrecognized positional argument
and crashes with `unrecognized arguments: true`.

Correct pattern:
```python
# WRONG — crashes in Batch:
parser.add_argument("--force-overwrite", action="store_true")

# CORRECT:
parser.add_argument("--force-overwrite", default="false", dest="force_overwrite")
# ...
if str(args.force_overwrite).lower() != "true":
    # check for existing silver file and skip
```

Every new Batch task must use the `default="false"` + `.lower() == "true"` pattern for all boolean parameters.

---

## Gate 9 — features.yaml registration

Only after Gates 0–8 pass, add the entry to `configs/features/features.yaml`:

```yaml
- family: my_new_feature
  sources: ["<source_key>"]           # must match extractors.py dispatch key
  visibility: prior_history           # one of the three classes
  commodities:                        # explicit list preferred over "all"
    - corn_cbot
    - soybeans_cbot
  value_range: [-10.0, 10.0]         # derived from Gate 5, never guessed
```

Final checklist before committing:
- [ ] `family` key exists in `COMPUTATIONS` dict in `computations/__init__.py`
- [ ] `sources` key(s) exist in `extract_all()` dispatch in `extractors.py`
- [ ] `value_range` was derived from observed p1/p99, not intuition
- [ ] All slugs in `commodities` passed Gate 6
- [ ] Local dry run passed Gate 7
- [ ] Corresponding silver data is written and verified non-empty in S3
- [ ] Pushed new ECR image with updated `src/` before submitting spine Batch job

---

## Drop decision: when to remove a feature vs. fix it

Drop immediately if:
- Null rate > 50 % and no aggregation strategy can fix it within the existing silver schema
- Source has a single snapshot per (key, year) and the feature requires temporal depth
- Source requires a custom ingestion schedule that would not be reliable at the feature store cutoff
- Feature has < 5 data points per slug after applying the visibility window

Aggregate / transform if:
- Source is sub-annual but an annual aggregate would be meaningful (sum, mean, last)
- Source is missing for some countries but available for the primary ones (emit NaN for missing, not 0)
- Source has short history (< 10 years) but covers the most recent regime — use it with a short z-score window (min_periods=3) and flag in the yaml comment

Do not work around null features with fill-forward, fill-zero, or imputation at the feature layer.
The label is real data; imputed features are not.  The model will find the imputation signal
and overfit to it.

---

## Quick reference: common sources and their known constraints

| Source | Temporal depth | Granularity to annual | Notes |
|---|---|---|---|
| CHIRPS | Daily per pixel | Sum / mean by crop stage | Stage windows from crop_calendars.yaml |
| NASA POWER | Daily per point | Mean by crop stage | Same |
| FAOSTAT | One row per (country, year) | Direct lookup | Year = harvest year; align to crop_year |
| PSD bulk (`psd_alldata.zip`) | **One snapshot per (commodity, country, market_year)** | Direct lookup | Cannot compute revisions; single-vintage only |
| WASDE monthly (if ingested) | One row per (release_month, commodity, country, year) | Max revision vs. prior month | Requires monthly bronze partitions, not bulk |
| ESR weekly | Weekly per (commodity, country) | Sum over marketing year, then z-score | Annual aggregate before any normalization |
| CFTC COT | Weekly per contract | Latest report before crop-year start | No country dimension |
| ONI / IOD | Monthly | Prior-month lookup | No country dimension |
| CONAB | One revision per season | Direct diff from prior estimate | Only BR production; align to coffee marketing year |
