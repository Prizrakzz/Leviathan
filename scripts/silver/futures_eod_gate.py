#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W2 -- the nine deterministic gates for the Databento leg (eight from the
plan + gate 9, the V2-4 month-continuity gate).

    1. ``(leviathan_slug, trade_date, raw_symbol)`` UNIQUENESS across the entire table -- the F2
       trap. Any duplicate is a HARD FAIL, never a dedupe: the dedupe already happened in the
       transform under the named ``ICE_BAR_RULE``, so a survivor means the rule is wrong. The slug
       is part of the key because the CEPEA cash rows carry a NULL ``raw_symbol``.
    2. DROPPED-SYMBOL COUNT per root per year, and it must be NON-ZERO for EVERY root, ICE and
       GLBX alike. GLBX drops the spread complex (``ZC``: 943 resolved -> 50 outright); ICE
       additionally drops ``_Z`` TAS suffixes and numeric-id instruments. A ZERO drop count means
       the outright filter did not run -- and buying on that basis is the $140.31 parent pull.
    3. BAR-COUNT RECONCILIATION against the plan's per-year table, +/- 2%. A root landing 40%
       short means the outright filter over-dropped.
    4. NO-FORWARD-FILL (F5): for 20 deferred contracts the count of distinct ``trade_date`` values
       must be STRICTLY LESS than the business-day span. Equality means something filled -- and a
       forward fill would manufacture exactly the term-structure flatness W3 exists to measure.
    5. IFEU SANITY (F4): robusta + white sugar, ``low <= settle <= high`` and
       ``abs(close - settle) / settle < 0.05`` on >= 99% of rows; violators are logged.
       *** READ THE DEGENERACY NOTE ON :func:`gate5_ifeu_sanity` BEFORE TRUSTING THIS GATE. ***
    6. ``settle_kind`` x ``source`` CROSS-TAB is exactly the declared map -- PLUS, because
       ``settle_kind`` is map-derived and does not depend on ``settle`` being non-null, the rows
       labelled ``settlement`` must actually carry one, per ``(root, year)``.
    7. 12/12 FRONT-MONTH PARITY vs ``silver_futures_prices`` through the D8 rule. Divergence at
       rolls is EXPECTED and is reported, not asserted; the assertion is that AWAY from detected
       rolls the median absolute relative difference is < 0.5%.
    8. The W1a-style CHAIN HOOKS: registered/forbidden layout, the mandatory ``lint_frame`` row
       validator wiring, ``config_check`` (futures_eod + futures_roll), the DAG descriptor and its
       byte-identical render, and the emitted ``silver_rebuild_gate`` / ``numbers_parity`` commands.

NO ATHENA (INV-3, and the plan's post-ship verification says so in as many words): every frame is
read straight from parquet via boto3 / pyarrow, and every data-plane call goes through a read-only
allowlist proxy. The only write this tool can perform is the optional report artifact, and that key
is refused if it lands under ``raw/`` / ``bronze/`` / ``silver/`` / ``gold/``.

Every URI may be a LOCAL path instead, which is what makes all eight gates unit-testable on
synthetic frames with no AWS at all.

Usage (Git-Bash needs MSYS_NO_PATHCONV=1)::

    python scripts/silver/futures_eod_gate.py \\
        --eod-uri s3://leviathan-dev-shahem-001/silver/futures_eod \\
        --manifest-uri s3://leviathan-dev-shahem-001/raw/production/source=databento \\
        --futures-prices-uri s3://leviathan-dev-shahem-001/silver/futures_prices/part-000.parquet

Exit 0 iff VERDICT PASS. A gate whose input is absent is SKIPPED and the verdict is FAIL unless the
gate was explicitly waived with ``--skip N`` (recorded in the artifact) -- fail-closed, because a
silently skipped gate is indistinguishable from a passing one in a log.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver import futures_eod_contracts as FC  # noqa: E402
from leviathan.silver import futures_roll as FR  # noqa: E402
from leviathan.transforms.raw_to_bronze.databento_eod import (  # noqa: E402
    ICE_BAR_RULE,
    ROOT_MAP,
    SETTLEMENT_TAPE_ROOTS,
    month_continuity_holes,
)

SLUG_TO_ROOT: dict[str, str] = {slug: root for root, (_ds, slug) in ROOT_MAP.items()}
from leviathan.transforms.raw_to_bronze.databento_eod import ICE_DATASETS  # noqa: E402

# --- gate 3: the plan's measured outright ohlcv-1d bar counts (lines 574-589) -------------------
# Spot-check years only for the 15 plan roots -- that is what the plan measured. Encoded as a
# CONSTANT so a drift in the gate and a drift in the data cannot be confused for each other. The
# settlement-tape root CPO is the one exception and carries EVERY year: it has no plan row, and its
# rows come from the D3 silver dry-run, which measured all of them (see the block at the tail).
EXPECTED_BARS: dict[tuple[str, int], int] = {
    ("ZC", 2010): 2070, ("ZC", 2013): 3171, ("ZC", 2016): 2852, ("ZC", 2019): 2960,
    ("ZC", 2022): 3031, ("ZC", 2025): 2750, ("ZC", 2026): 1669,
    ("ZS", 2010): 2115, ("ZS", 2013): 3004, ("ZS", 2016): 2878, ("ZS", 2019): 3006,
    ("ZS", 2022): 3121, ("ZS", 2025): 2984, ("ZS", 2026): 1677,
    ("ZL", 2010): 1615, ("ZL", 2013): 3021, ("ZL", 2016): 2921, ("ZL", 2019): 3075,
    ("ZL", 2022): 3105, ("ZL", 2025): 3060, ("ZL", 2026): 1644,
    ("ZM", 2010): 1935, ("ZM", 2013): 2889, ("ZM", 2016): 3179, ("ZM", 2019): 3136,
    ("ZM", 2022): 3132, ("ZM", 2025): 3237, ("ZM", 2026): 1816,
    ("ZW", 2010): 1839, ("ZW", 2013): 2478, ("ZW", 2016): 2127, ("ZW", 2019): 2256,
    ("ZW", 2022): 2404, ("ZW", 2025): 2090, ("ZW", 2026): 1314,
    ("KE", 2013): 74, ("KE", 2016): 1850, ("KE", 2019): 1942,
    ("KE", 2022): 2067, ("KE", 2025): 1771, ("KE", 2026): 1109,
    ("ZR", 2010): 897, ("ZR", 2013): 928, ("ZR", 2016): 816, ("ZR", 2019): 750,
    ("ZR", 2022): 854, ("ZR", 2025): 900, ("ZR", 2026): 549,
    ("KC", 2019): 5649, ("KC", 2022): 4735, ("KC", 2025): 4686, ("KC", 2026): 2259,
    ("SB", 2019): 4537, ("SB", 2022): 5267, ("SB", 2025): 5151, ("SB", 2026): 2552,
    ("CC", 2019): 3871, ("CC", 2022): 3981, ("CC", 2025): 3461, ("CC", 2026): 1992,
    ("CT", 2019): 3259, ("CT", 2022): 3572, ("CT", 2025): 3247, ("CT", 2026): 1853,
    ("OJ", 2019): 2280, ("OJ", 2022): 1569, ("OJ", 2025): 1618, ("OJ", 2026): 713,
    ("RS", 2019): 2839, ("RS", 2022): 2677, ("RS", 2025): 2868, ("RS", 2026): 1646,
    ("RC", 2019): 3746, ("RC", 2022): 2975, ("RC", 2025): 3282, ("RC", 2026): 1931,
    ("W", 2019): 2879, ("W", 2022): 2983, ("W", 2025): 3682, ("W", 2026): 2124,
    # CPO (V2-4 M3, banked 2026-09-03): NOT a plan row -- the settlement tape was never in the
    # plan's table, so these are the D3 SILVER DRY-RUN's rows_out per (CPO, year) (job 062c52b8 on
    # futures-eod-silver rev 6: exit 0, publish state VALIDATED, 116,228 rows, and an independent
    # local reproduction over the same raw objects matched it exactly). That is the KE-2013 idiom
    # applied to a whole root: bank the MEASURED number as the assertion so a re-run is pinned
    # against the transform's own output. CPO is GLBX, so gate 3 reads it off the SILVER frame
    # (basis='silver') and the numbers are directly comparable. EVERY year is listed, not spot
    # checks, because the dry-run measured every year. 2026 is a PARTIAL year -- the window runs
    # 2016-08-01 .. 2026-09-01, exclusive of the vendor's available end -- so it is RECORDED, NOT
    # GATED through PARTIAL_YEARS, exactly like every other root's current year.
    ("CPO", 2016): 6456, ("CPO", 2017): 15111, ("CPO", 2018): 15147, ("CPO", 2019): 13358,
    ("CPO", 2020): 10347, ("CPO", 2021): 8223, ("CPO", 2022): 8926, ("CPO", 2023): 7429,
    ("CPO", 2024): 8142, ("CPO", 2025): 12937, ("CPO", 2026): 10152,
}
BAR_TOLERANCE = 0.02
# 2026 was a PARTIAL year when the plan measured it and it keeps growing, so an equality-with-2%
# assertion against it would fail purely with the calendar. Recorded, never gated. Every FULL year
# in the table above IS gated -- the gate can and must be able to fire.
PARTIAL_YEARS = frozenset({2026})
# Gate 7 per-lane floors (measured 2026-07-29): GLBX = real settlements, must be near-exact;
# ICE = our settle IS the venue close (settlements unpurchased, $1,960) while the reference
# lane prints settlements, so 0.005 is unattainable by construction. 0.02 is the measured
# venue-close-vs-settlement envelope; retire it when the free ICE settlement source lands.
PARITY_MEDIAN_FLOOR_ICE = 0.02
_ICE_ROOTS = frozenset(r for r, (ds, _s) in ROOT_MAP.items() if ds in ICE_DATASETS)
# (root, year) pairs that are RECORDED but NOT gated because the pipeline deliberately never fetches
# them. ('KE', 2013) is the whole set: the plan measured 74 bars there and says "usable from 2014"
# (KCBT -> CME migration), so ROOT_FIRST_DATE['KE'] is 2014-01-01, root_years('KE', ...) starts at
# 2014 and select_units explicitly skips a requested 2013. Gating a year that is by design never
# bought makes gate 3 unpassable: it fires "KE/2013: 0 bars vs expected 74 (-100.0%)" on a perfectly
# correct table. The row stays in EXPECTED_BARS as the plan's measurement; it is simply not an
# assertion. `test_every_gated_year_is_actually_fetched` keeps this pair in lockstep with
# ROOT_FIRST_DATE.
RECORDED_NOT_GATED: frozenset[tuple[str, int]] = frozenset({("KE", 2013)})
# Roots whose EXPECTED_BARS rows are NOT YET BANKED (V2-4 M3). EMPTY since 2026-09-03: the D3
# silver dry-run (job 062c52b8) ran and CPO's eleven rows are banked above on the 'silver' basis,
# so gate 3 now judges every ROOT_MAP root and nothing is waiting. The MECHANISM stays, because the
# next settlement-tape root arrives the same way: it has no plan-measured table, so it is named here
# from the moment its ROOT_MAP row lands until its own dry-run banks its rows. A pending root FAILS
# gate 3 by name ('not banked') rather than passing vacuously; the shadow harness waives gate 3 on
# purpose (--skip 3) while a root is pending, and the canonical harness runs only once this set is
# empty. Lint both ways: a pending root must have ZERO rows, and a root with rows must not be
# pending.
EXPECTED_BARS_PENDING: frozenset[str] = frozenset()
assert EXPECTED_BARS_PENDING <= set(ROOT_MAP), "EXPECTED_BARS_PENDING must name ROOT_MAP roots"
assert not {r for r, _y in EXPECTED_BARS} & EXPECTED_BARS_PENDING, \
    "a root with EXPECTED_BARS rows banked must be removed from EXPECTED_BARS_PENDING"
assert EXPECTED_BARS_PENDING <= SETTLEMENT_TAPE_ROOTS, \
    "only a settlement-tape root may be pending (its counts come from the D3 dry-run, not the plan)"

# --- gate 4 -------------------------------------------------------------------------------------
# The most-deferred contracts are sampled PER SLUG (STEP-12 F6). A table-wide top-20 by lead
# collapses onto whichever root lists furthest out -- CPO lists 60 months (~1,800 days of lead
# against ~1,000 for the deepest ZC/ZS month), so once palm is canonical all 20 slots would be palm
# and the F5 check would silently stop sampling the 15 shipped roots (the ZCZ8 measured case).
DEFERRED_SAMPLE_PER_SLUG = 3
DEFERRED_MIN_ROWS = 30

# --- gate 5 -------------------------------------------------------------------------------------
IFEU_SLUGS = ("robusta_coffee", "white_sugar")
IFEU_OK_FRAC = 0.99
IFEU_MAX_CLOSE_SETTLE_REL = 0.05

# --- gate 6 -------------------------------------------------------------------------------------
SETTLEMENT_KIND = "settlement"
# A SYSTEMATIC-MISS detector, not a per-bar completeness assertion. A ts_ref-vs-ts_event calendar
# skew makes the statistics join match ~0% and this fires; genuinely thin settlement publication on
# a deferred month does not. The floor deliberately matches the registry's table-wide
# min_nonnull_frac for `settle`, applied where it can actually SEE a GLBX-only miss (table-wide, the
# ICE rows dilute it away because ICE settle == close by construction). Retune on purchased data.
SETTLEMENT_MIN_NONNULL_FRAC = 0.5

# --- gate 7 -------------------------------------------------------------------------------------
# The 12 yfinance slugs of silver_futures_prices -- the retirement-gate parity set.
PARITY_SLUGS = (
    "corn_cbot", "soybeans_cbot", "soybean_oil_cbot", "soybean_meal_cbot",
    "soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt", "arabica_coffee", "cocoa",
    "cotton", "raw_sugar", "rough_rice_cbot", "frozen_orange_juice",
)
PARITY_LOOKBACK_DAYS = 250
PARITY_ROLL_PCT = 0.05          # |pct change| above this = a detected roll; divergence is EXPECTED
PARITY_MEDIAN_FLOOR = 0.005     # median |relative diff| away from rolls must be under 0.5%

# --- gate 8 -------------------------------------------------------------------------------------
# EVERY chain that publishes silver_futures_eod. One table, one task, one publisher, so gate 8 (d)
# checks all of them: futures_eod_databento is the W2 paid vendor leg and futures_eod_free carries
# the four W1a/W1b free venues (CZCE, JSE/SAFEX, CEPEA, MIAX) on one cron.
_DAG_SCHEDULES: tuple[str, ...] = ("futures_eod_databento", "futures_eod_free")
_PRODUCER_TASK = "jobs/batch/futures_eod_task.py"
_ROW_VALIDATOR_TOKEN = "row_validator=FC.lint_frame"

GATE_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
_FORBIDDEN_REPORT_PREFIXES = ("raw/", "bronze/", "silver/", "gold/")
_ALLOWLIST = frozenset({"get_object", "list_objects_v2", "head_object", "get_paginator"})


class _ReadOnlyClient:
    """boto3 S3 proxy with a fail-closed method allowlist (the day0_heartbeat idiom)."""

    def __init__(self, region: str):
        import boto3

        self._c = boto3.client("s3", region_name=region)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in _ALLOWLIST:
            raise RuntimeError(f"futures_eod_gate is READ-ONLY: boto3 method {name!r} is not allowlisted")
        return getattr(self._c, name)


# ---------------------------------------------------------------------------
# loading (the only impure lane) -- S3-DIRECT pyarrow, NEVER Athena
# ---------------------------------------------------------------------------
def split_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"not an s3 uri: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _hive_values(key: str) -> dict:
    """``.../leviathan_slug=corn_cbot/trade_year=2016/part-000.parquet`` -> the partition values.

    The partition columns live ONLY in the path (they are dropped from the parquet body), so a
    read that ignores the path loses both of them."""
    out: dict = {}
    for seg in key.split("/"):
        if "=" in seg:
            k, _, v = seg.partition("=")
            out[k] = v
    return out


def _read_parquet_bytes(body: bytes) -> pd.DataFrame:
    return pq.read_table(io.BytesIO(body)).to_pandas()


def collect_parquet_keys(s3, bucket: str, prefix: str) -> list[str]:
    """Every ``.parquet`` key under ``prefix``, excluding ``_shadow``/``_staging`` subtrees
    RELATIVE to the requested prefix -- not absolutely. The absolute form made
    ``--eod-uri .../_shadow`` self-defeating: every key under it contains the marker, so the
    shadow tree read as empty (measured 2026-07-29: 187 real objects invisible) while the whole
    point of the shadow phase is to gate THAT tree. A canonical-prefix read still excludes its
    nested shadow/staging subtrees via the relative path."""
    keys: list[str] = []
    pfx = prefix.rstrip("/") + "/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=pfx):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            rel = "/" + k[len(pfx):]
            if k.endswith(".parquet") and "/_shadow/" not in rel and "/_staging/" not in rel:
                keys.append(k)
    return keys


def load_eod_frame(uri: str, s3=None) -> pd.DataFrame:
    """Read ``silver_futures_eod`` from a registered-partition tree (or a local dir / file).

    Re-attaches ``leviathan_slug`` / ``trade_year`` from the Hive path segments."""
    frames: list[pd.DataFrame] = []
    if not uri.startswith("s3://"):
        p = Path(uri)
        files = [p] if p.is_file() else sorted(p.rglob("*.parquet"))
        for f in files:
            df = _read_parquet_bytes(f.read_bytes())
            for k, v in _hive_values(f.as_posix()).items():
                if k not in df.columns:
                    df[k] = v
            frames.append(df)
    else:
        bucket, key = split_s3_uri(uri)
        if key.endswith(".parquet"):
            keys = [key]
        else:
            keys = collect_parquet_keys(s3, bucket, key)
        for k in sorted(keys):
            df = _read_parquet_bytes(s3.get_object(Bucket=bucket, Key=k)["Body"].read())
            for pk, pv in _hive_values(k).items():
                if pk not in df.columns:
                    df[pk] = pv
            frames.append(df)
    if not frames:
        raise ValueError(f"no parquet objects under {uri}")
    out = pd.concat(frames, ignore_index=True)
    if "trade_year" in out.columns:
        out["trade_year"] = pd.to_numeric(out["trade_year"], errors="coerce").astype("Int64")
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    return out


def load_flat_frame(uri: str, s3=None) -> pd.DataFrame:
    if not uri.startswith("s3://"):
        return _read_parquet_bytes(Path(uri).read_bytes())
    bucket, key = split_s3_uri(uri)
    return _read_parquet_bytes(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def load_manifests(uri: str, s3=None) -> list[dict]:
    """Every ``symbology_{root}_{year}.json`` under the Databento raw prefix (gate 2's evidence)."""
    out: list[dict] = []
    if not uri.startswith("s3://"):
        for f in sorted(Path(uri).rglob("symbology_*.json")):
            out.append(json.loads(f.read_text(encoding="utf-8")))
        return out
    bucket, key = split_s3_uri(uri)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key.rstrip("/") + "/"):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.rsplit("/", 1)[-1].startswith("symbology_") and k.endswith(".json"):
                out.append(json.loads(s3.get_object(Bucket=bucket, Key=k)["Body"].read().decode("utf-8")))
    return out


# ---------------------------------------------------------------------------
# gate 1 -- (leviathan_slug, trade_date, raw_symbol) uniqueness, table-wide
# ---------------------------------------------------------------------------
# Sources whose `raw_symbol` is a delivery-MONTH LABEL rather than a vendor instrument id, so the
# same string is carried by MORE THAN ONE slug on every session BY CONSTRUCTION. JSE/SAFEX writes
# the sheet's expiry cell verbatim ("Dec-2026") and the white-maize and yellow-maize sections both
# publish it on the same date -- an unscoped cross-slug advisory would fire ~9 times a day, forever,
# on perfectly correct data. CEPEA writes raw_symbol NULL and is excluded by the notna() filter.
_MONTH_LABEL_SYMBOL_SOURCES: frozenset = frozenset({"jse_safex"})


def _cross_slug_symbol_advisory(df: pd.DataFrame) -> list[dict]:
    """ADVISORY, never a failure: one VENDOR symbol carried by two different slugs on one date.

    Widening the F2 key with `leviathan_slug` (futures_eod_task._F2_KEY) made this shape legal, and
    the widening was necessary -- see the note in gate1_uniqueness. What it gives up is narrow and
    is NOT reachable from any landed producer: every transform in this family maps one source row to
    exactly one slug, so none of them can emit it. The reachable path is a MAP CHANGE -- re-point a
    root in futures_eod_contracts.CONTRACT_MAP and the old canonical partitions keep the old slug
    while new runs write the new one, so one history exists twice under two names, in two different
    (leviathan_slug, trade_year) partitions that no uniqueness key spans. That double-count is worth
    REPORTING; it is not worth failing on, because a deliberate, correct re-map produces the
    identical shape until the superseded partitions are dropped.
    """
    need = {"leviathan_slug", "trade_date", "raw_symbol"}
    if not need <= set(df.columns):
        return []
    sub = df[df["raw_symbol"].notna()]
    if "source" in sub.columns:
        sub = sub[~sub["source"].isin(_MONTH_LABEL_SYMBOL_SOURCES)]
    if sub.empty:
        return []
    n_slugs = sub.groupby(["trade_date", "raw_symbol"])["leviathan_slug"].nunique()
    hits = n_slugs[n_slugs > 1]
    if not len(hits):
        return []
    out: list[dict] = []
    for k, v in hits.sort_values(ascending=False).head(10).items():
        rows = sub[(sub["trade_date"] == k[0]) & (sub["raw_symbol"] == k[1])]
        out.append({"trade_date": str(k[0])[:10], "raw_symbol": str(k[1]), "n_slugs": int(v),
                    "slugs": sorted(str(s) for s in set(rows["leviathan_slug"]))})
    return out


def gate1_uniqueness(df: pd.DataFrame) -> tuple[list[str], dict]:
    """HARD FAIL on any duplicate. Not a dedupe -- the ICE_BAR_RULE dedupe already ran in the
    transform, so a survivor means the F2 rule is wrong and no registered surface may consume it."""
    # `leviathan_slug` is part of the key, matching futures_eod_task._F2_KEY. Without it the CEPEA
    # cash rows -- which have NO vendor symbol and therefore write raw_symbol NULL -- group together
    # under `dropna=False` on every trade date and false-fail this gate table-wide. No detection
    # power is lost for the F2 double bar itself: an ICE double bar is two bars of the SAME contract
    # on one date, so the pair shares its slug and still collides. The ONE shape the widening does
    # let through -- one vendor symbol under two slugs -- is REPORTED as a non-blocking advisory by
    # _cross_slug_symbol_advisory rather than failed on; see that docstring for why.
    key = ["leviathan_slug", "trade_date", "raw_symbol"]
    missing = [c for c in key if c not in df.columns]
    if missing:
        return [f"(1) frame is missing {missing}"], {}
    sizes = df.groupby(key, dropna=False).size()
    dups = sizes[sizes > 1]
    rec = {"rows": int(len(df)), "keys": int(len(sizes)), "duplicate_keys": int(len(dups)),
           "worst": [{"leviathan_slug": str(k[0]), "trade_date": str(k[1])[:10],
                      "raw_symbol": str(k[2]), "rows": int(v)}
                     for k, v in dups.sort_values(ascending=False).head(10).items()],
           "cross_slug_symbol_advisory": _cross_slug_symbol_advisory(df)}
    if len(dups):
        return [f"(1) {len(dups)} (leviathan_slug, trade_date, raw_symbol) key(s) carry MULTIPLE "
                f"rows -- the F2 double bar survived the ICE_BAR_RULE dedupe; this is a hard fail"], rec
    return [], rec


# ---------------------------------------------------------------------------
# gate 2 -- dropped-symbol count, NON-ZERO for every root
# ---------------------------------------------------------------------------
def gate2_dropped_symbols(manifests: list[dict]) -> tuple[list[str], dict]:
    per_unit = []
    by_root: dict[str, int] = {}
    for m in manifests:
        root = m.get("root")
        per_unit.append({"root": root, "year": m.get("year"),
                         "resolved": m.get("resolved_symbols"),
                         "outrights": m.get("outright_count"),
                         "dropped": m.get("dropped_count")})
        by_root[root] = by_root.get(root, 0) + int(m.get("dropped_count") or 0)
    fails: list[str] = []
    if not manifests:
        return ["(2) NO symbology manifests found -- the dropped-symbol evidence is written once, "
                "at resolve time, and cannot be recomputed from an S3 listing"], {"per_unit": []}
    zero_units = [u for u in per_unit if (u["outrights"] or 0) > 0 and not (u["dropped"] or 0)]
    for u in zero_units:
        fails.append(f"(2) {u['root']}/{u['year']}: dropped_count is ZERO -- the outright filter "
                     f"did not run (GLBX drops the spread complex; ICE drops _Z TAS and numeric-id "
                     f"instruments; a zero on ANY root is the failure)")
    missing_roots = sorted(set(ROOT_MAP) - set(by_root))
    if missing_roots:
        fails.append(f"(2) no manifest at all for root(s) {missing_roots}")
    zero_roots = sorted(r for r, n in by_root.items() if n == 0)
    for r in zero_roots:
        fails.append(f"(2) root {r}: ZERO dropped symbols across every year")
    return fails, {"per_unit": sorted(per_unit, key=lambda u: (str(u["root"]), u["year"] or 0)),
                   "by_root": by_root, "zero_roots": zero_roots}


# ---------------------------------------------------------------------------
# gate 3 -- bar-count reconciliation vs the plan's table
# ---------------------------------------------------------------------------
def gate3_bar_counts(df: pd.DataFrame, *, tolerance: float = BAR_TOLERANCE,
                     ice_raw_counts: Optional[dict] = None) -> tuple[list[str], dict]:
    """BASIS (corrected 2026-07-29): EXPECTED_BARS is the plan's per-year table of RAW ohlcv
    bars -- measured pre-dedupe (CC/2019 raw file: 3,887 rows vs the table's 3,871, +0.4%).
    For ICE roots the silver row count is POST-dedupe (~35-46% lower: the F2 double bar is
    real in batch files), so comparing silver rows against the raw table failed every ICE
    unit by construction. ICE roots therefore compare on ``ice_raw_counts`` -- pre-dedupe
    row counts read from the raw payloads -- and GLBX (no doubles: silver == raw) stays on
    the silver frame. A gated ICE unit with no raw count FAILS: an unmeasurable basis must
    never read as a passing one."""
    if "leviathan_slug" not in df.columns:
        return ["(3) frame is missing leviathan_slug"], {}
    work = df.copy()
    work["root"] = work["leviathan_slug"].map(SLUG_TO_ROOT)
    work["year"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.year
    observed = work.groupby(["root", "year"]).size()
    ice_roots = {r for r, (ds, _s) in ROOT_MAP.items() if ds in ICE_DATASETS}
    rows, fails = [], []
    # A root whose EXPECTED_BARS rows are pending the D3 dry-run cannot pass this gate: an
    # unmeasurable basis is not a pass (V2-4 M3). Named, so the operator banks the rows.
    for root in sorted(EXPECTED_BARS_PENDING):
        fails.append(f"(3) {root}: EXPECTED_BARS rows NOT BANKED yet (pending the silver dry-run's "
                     f"rows_out per year on the 'silver' basis) -- bank them and empty "
                     f"EXPECTED_BARS_PENDING; an unmeasurable basis is not a pass")
    for (root, year), expected in sorted(EXPECTED_BARS.items()):
        basis = "raw" if root in ice_roots else "silver"
        if basis == "raw":
            got = (ice_raw_counts or {}).get((root, year))
        else:
            got = int(observed.get((root, year), 0))
        rel = ((got - expected) / expected) if (expected and got is not None) else None
        gated = year not in PARTIAL_YEARS and (root, year) not in RECORDED_NOT_GATED
        rec = {"root": root, "year": year, "expected": expected, "observed": got,
               "basis": basis, "rel_diff": round(rel, 4) if rel is not None else None,
               "gated": gated}
        rows.append(rec)
        if gated and got is None:
            fails.append(f"(3) {root}/{year}: NO raw bar count available for the ICE basis "
                         f"(supply --manifest-uri; an unmeasurable basis is not a pass)")
        elif gated and (rel is None or abs(rel) > tolerance):
            fails.append(f"(3) {root}/{year}: {got} bars vs expected {expected} "
                         f"({(rel or 0) * 100:+.1f}%, tolerance +/-{tolerance * 100:.0f}%, "
                         f"basis={basis})")
    return fails, {"rows": rows, "tolerance": tolerance,
                   "partial_years_recorded_not_gated": sorted(PARTIAL_YEARS),
                   "pairs_recorded_not_gated": sorted(f"{r}/{y}" for r, y in RECORDED_NOT_GATED),
                   "roots_pending_bank": sorted(EXPECTED_BARS_PENDING)}


# ---------------------------------------------------------------------------
# gate 9 -- month continuity per root (V2-4 M2)
# ---------------------------------------------------------------------------
def gate9_month_continuity(df: pd.DataFrame, *, slugs=None) -> tuple[list[str], dict]:
    """Every calendar month between a Databento root's first and last banked trade date carries
    >= 1 trade date (per run of consecutive years). An internal hole is invisible to
    PRICE_COVERAGE_START -- covers() routes a window inside it to the table, which declines
    no_tape_rows instead of naming the floor -- so a hole is a FAIL that names the months. The
    CPO tape's measured Jan-Jul 2016 hole is why the root's floor opens 2016-08-01; this gate is
    what keeps a second hole from ever landing silently. Free-leg slugs are outside ROOT_MAP and
    are not judged here (their legs are forward-accumulation captures with declared gaps).

    ``slugs`` (STEP-12 F7) SCOPES the judgement to the slugs a sitting touched. Unscoped, the gate
    judges every Databento root on the frame -- which at the CPO sitting's D8 includes the 15
    shipped roots' NEVER-MEASURED history (KE from 2014, ICE from 2018-12-24, ZR's thin years),
    so a pre-existing estate hole would red the sitting and roll a continuous CPO back. The
    runbook records the estate's pre-state on the canonical prefix BEFORE promote (D6b) and runs
    D8 scoped to the slug it touched; the scope is stamped in the artifact, and a scope that
    judges nothing is a FAIL, not a pass."""
    if "leviathan_slug" not in df.columns or "trade_date" not in df.columns:
        return ["(9) frame is missing leviathan_slug/trade_date"], {}
    work = df[df["leviathan_slug"].isin(set(SLUG_TO_ROOT))]
    scope = sorted(set(slugs)) if slugs else None
    if scope:
        unknown = [s for s in scope if s not in SLUG_TO_ROOT]
        if unknown:
            return [f"(9) scope names slug(s) outside the Databento roots: {', '.join(unknown)}"], \
                {"scope": scope, "holes": {}, "slugs_judged": []}
        work = work[work["leviathan_slug"].isin(set(scope))]
        if work.empty:
            return [f"(9) none of the scoped slug(s) carry rows on the frame: {', '.join(scope)} "
                    f"-- a scope that judges nothing is not a pass"], \
                {"scope": scope, "holes": {}, "slugs_judged": []}
    holes = month_continuity_holes(work)
    fails = [f"(9) {SLUG_TO_ROOT.get(slug, '?')}/{slug}: {len(months)} empty calendar month(s) "
             f"inside the banked span: {', '.join(months[:12])}"
             f"{' ...' if len(months) > 12 else ''}"
             for slug, months in sorted(holes.items())]
    return fails, {"holes": holes, "scope": scope,
                   "slugs_judged": sorted(set(work["leviathan_slug"].astype(str)))}


def load_ice_raw_bar_counts(s3, bucket: str, manifest_prefix: str) -> dict:
    """Pre-dedupe row counts per ICE ``(root, year)``, decoded from the raw ohlcv payloads.

    The gate's ONLY use of the vendor package; S3-direct, no Athena. Fails loudly if the
    package is unavailable -- gate 3's ICE basis would silently vanish otherwise."""
    from leviathan.transforms.raw_to_bronze.databento_eod import DATASET_SLUGS as _DS
    try:
        from databento import DBNStore
    except ImportError as exc:
        raise RuntimeError("gate 3's ICE raw basis needs the databento package") from exc
    counts: dict = {}
    pfx = manifest_prefix.rstrip("/") + "/"
    paginator = s3.get_paginator("list_objects_v2")
    ice_slugs = {_DS[ds] for ds in ICE_DATASETS}
    for page in paginator.paginate(Bucket=bucket, Prefix=pfx):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if not k.endswith(".dbn.zst") or "ohlcv-1d_" not in k:
                continue
            parts = dict(seg.split("=", 1) for seg in k.split("/") if "=" in seg)
            if parts.get("dataset") not in ice_slugs:
                continue
            root, year = parts.get("root"), parts.get("year")
            if not root or not year:
                continue
            body = s3.get_object(Bucket=bucket, Key=k)["Body"].read()
            counts[(root, int(year))] = len(DBNStore.from_bytes(body).to_df())
    return counts


# ---------------------------------------------------------------------------
# gate 4 -- no forward fill (F5)
# ---------------------------------------------------------------------------
def gate4_no_forward_fill(df: pd.DataFrame, *, sample: int = DEFERRED_SAMPLE_PER_SLUG,
                          min_rows: int = DEFERRED_MIN_ROWS) -> tuple[list[str], dict]:
    """The ``sample`` most DEFERRED contracts OF EVERY SLUG (largest lead from first print to
    delivery month) must each show distinct-trade-date < business-day span. ``ZCZ8`` returned 110
    bars against ~139 business days; equality means something filled, and a fill manufactures
    term-structure flatness. PER SLUG, never table-wide (STEP-12 F6): the furthest-listing root
    (CPO, 60 months out) would otherwise monopolise every slot and the 15 shipped roots would
    silently leave the sample."""
    need = {"leviathan_slug", "contract_month", "trade_date"}
    if need - set(df.columns):
        return [f"(4) frame is missing {sorted(need - set(df.columns))}"], {}
    work = df[["leviathan_slug", "contract_month", "trade_date"]].dropna().copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    # WEEKDAY dates only (measured 2026-07-29: ZCZ3 carries 70 SUNDAY-dated bars over its life --
    # the GLBX Sunday-evening session, UTC-bucketed by the vendor into sparse partial bars. Real
    # data, not fill; but counting them makes distinct-dates exceed the Mon-Fri business span by
    # construction. A forward-filler fills WEEKDAYS, so excluding weekends keeps the teeth.)
    work = work[work["trade_date"].dt.dayofweek < 5]
    grp = work.groupby(["leviathan_slug", "contract_month"])["trade_date"]
    agg = grp.agg(first="min", last="max", distinct="nunique").reset_index()
    agg = agg[agg["distinct"] >= min_rows]
    if agg.empty:
        return [f"(4) no contract carries >= {min_rows} trade dates -- cannot sample deferred "
                f"contracts"], {"sampled": []}
    month_start = pd.to_datetime(agg["contract_month"].astype("string") + "-01", errors="coerce")
    agg["lead_days"] = (month_start - agg["first"]).dt.days
    agg = agg.sort_values(["lead_days", "leviathan_slug", "contract_month"],
                          ascending=[False, True, True])
    # PER SLUG: the `sample` most-deferred contracts of EVERY slug on the frame, never a
    # table-wide top-N (which the furthest-listing root monopolises).
    agg = agg.groupby("leviathan_slug", sort=False).head(sample)
    agg["bdays"] = [int(np.busday_count(f.date(), l.date()) + 1)
                    for f, l in zip(agg["first"], agg["last"])]
    agg["filled"] = agg["distinct"] >= agg["bdays"]
    recs = [{"leviathan_slug": r.leviathan_slug, "contract_month": r.contract_month,
             "first": str(r.first)[:10], "last": str(r.last)[:10],
             "distinct_dates": int(r.distinct), "bday_span": int(r.bdays),
             "filled": bool(r.filled)} for r in agg.itertuples()]
    fails = [f"(4) {r['leviathan_slug']} {r['contract_month']}: {r['distinct_dates']} distinct "
             f"trade dates >= {r['bday_span']} business days -- NOT strictly less, something "
             f"forward-filled" for r in recs if r["filled"]]
    return fails, {"sampled": recs, "sample_size": len(recs), "per_slug": sample,
                   "slugs_covered": sorted(set(agg["leviathan_slug"].astype(str)))}


# ---------------------------------------------------------------------------
# gate 5 -- IFEU sanity (F4)
# ---------------------------------------------------------------------------
def gate5_ifeu_sanity(df: pd.DataFrame, *, ok_frac: float = IFEU_OK_FRAC
                      ) -> tuple[list[str], dict]:
    """Robusta + white sugar: ``low <= settle <= high`` and ``abs(close-settle)/settle < 0.05``.

    *** DEGENERACY, RECORDED HONESTLY ***
    On the data W2 actually buys, ICE rows carry ``settle_kind='close'`` and ``settle`` IS
    ``close`` (D4), because the ICE ``statistics`` schema costs $1,960 and is excluded. So
    ``abs(close - settle)/settle`` is identically 0 and clause 2 CANNOT FIRE, and clause 1 reduces
    to ``low <= close <= high``, which an OHLCV bar satisfies by construction unless the decode or
    the scaling is broken. The gate is implemented as the plan specifies because it becomes
    load-bearing the moment a free ICE Report Center settlement reference lands and ``settle``
    stops equalling ``close`` -- and it DOES fire today on a scaling/decode defect, which is a real
    failure mode. ``settle_is_close_frac`` is emitted so the degeneracy is visible in the artifact
    rather than mistaken for a pass, and the bar-internal consistency clause (open/close inside
    [low, high], high >= low) is added as the part that can fire on purchased data."""
    need = {"leviathan_slug", "settle", "low", "high", "close"}
    if need - set(df.columns):
        return [f"(5) frame is missing {sorted(need - set(df.columns))}"], {}
    work = df[df["leviathan_slug"].isin(IFEU_SLUGS)].copy()
    if work.empty:
        return ["(5) no robusta / white-sugar rows present"], {"rows": 0}
    # NO-PRINT ROWS (measured 2026-07-29): 4.35% of IFEU rows carry volume > 0 with EVERY price
    # field NULL -- the F4 class, outright volume attributed from spread/strategy trades with no
    # standalone print. They are REAL venue records (their volume feeds the ICE roll metric), the
    # schema permits NULL prices, and F5's doctrine is that a missing print is ABSENCE -- so they
    # stay in silver. But a price-sanity clause evaluated on a priceless row is vacuously FALSE
    # (NaN comparisons), which mislabels honest absence as corruption: the three clauses below
    # quantify over PRICED rows only, and the no-print count is REPORTED per slug instead.
    price_cols = ["open", "high", "low", "close", "settle"]
    have_price = work[[c for c in price_cols if c in work.columns]].notna().any(axis=1)
    no_print_by_slug = {s: int(v) for s, v in
                        work.loc[~have_price, "leviathan_slug"].value_counts().items()}
    work = work[have_price].copy()
    if work.empty:
        return ["(5) every robusta / white-sugar row is a no-print row -- nothing priced to check"],                {"rows": 0, "no_print_rows": no_print_by_slug}
    settle = pd.to_numeric(work["settle"], errors="coerce")
    low = pd.to_numeric(work["low"], errors="coerce")
    high = pd.to_numeric(work["high"], errors="coerce")
    close = pd.to_numeric(work["close"], errors="coerce")
    opn = pd.to_numeric(work.get("open"), errors="coerce") if "open" in work.columns else close

    in_band = (low <= settle) & (settle <= high)
    rel = (close - settle).abs() / settle.replace(0, np.nan)
    close_ok = rel < IFEU_MAX_CLOSE_SETTLE_REL
    bar_ok = (high >= low) & (close >= low) & (close <= high) & (opn >= low) & (opn <= high)
    n = int(len(work))
    rec = {
        "no_print_rows": no_print_by_slug,
        "rows": n,
        "in_band_frac": round(float(in_band.mean()), 4),
        "close_settle_frac": round(float(close_ok.mean()), 4),
        "bar_consistent_frac": round(float(bar_ok.mean()), 4),
        "settle_is_close_frac": round(float((settle == close).mean()), 4),
        "floor": ok_frac,
        "degenerate_clause2": bool((settle == close).mean() > 0.999),
        "violators": [
            {"leviathan_slug": r.leviathan_slug, "trade_date": str(r.trade_date)[:10],
             "raw_symbol": str(getattr(r, "raw_symbol", "")), "low": float(r.low),
             "settle": float(r.settle), "high": float(r.high), "close": float(r.close)}
            for r in work[~(in_band & close_ok & bar_ok)].head(20).itertuples()
            if pd.notna(r.settle)
        ],
    }
    fails = []
    if rec["in_band_frac"] < ok_frac:
        fails.append(f"(5) low <= settle <= high on only {rec['in_band_frac']:.4f} of IFEU rows "
                     f"(floor {ok_frac})")
    if rec["close_settle_frac"] < ok_frac:
        fails.append(f"(5) abs(close-settle)/settle < {IFEU_MAX_CLOSE_SETTLE_REL} on only "
                     f"{rec['close_settle_frac']:.4f} of IFEU rows (floor {ok_frac})")
    if rec["bar_consistent_frac"] < ok_frac:
        fails.append(f"(5) bar-internal consistency (high>=low, open/close inside the range) on "
                     f"only {rec['bar_consistent_frac']:.4f} of IFEU rows (floor {ok_frac}) -- the "
                     f"system-priced-leg contamination or a price-scaling defect")
    return fails, rec


# ---------------------------------------------------------------------------
# gate 6 -- settle_kind x source cross-tab
# ---------------------------------------------------------------------------
def gate6_settle_kind_cross_tab(df: pd.DataFrame) -> tuple[list[str], dict]:
    """The declared cross-tab PLUS the thing the cross-tab alone cannot see.

    ``settle_kind`` is MAP-DERIVED (bronze_to_silver reads CONTRACT_MAP), so it does not depend on
    ``settle`` being non-null: every GLBX row can carry ``settle_kind='settlement'`` with
    ``settle IS NULL`` and this comparison of LABELS still passes. That is precisely what a
    systematic ts_ref-vs-ts_event calendar skew in the statistics join produces -- and the registry's
    table-wide ``min_nonnull_frac`` floor cannot see it either, because the ICE rows (where
    ``settle == close`` by construction) dilute a GLBX-only miss below the threshold. So the
    settlement-labelled rows are also required to actually CARRY a settlement, per (root, year)."""
    need = {"source", "settle_kind"}
    if need - set(df.columns):
        return [f"(6) frame is missing {sorted(need - set(df.columns))}"], {}
    declared = {}
    for rec in FC.CONTRACT_MAP.values():
        declared.setdefault(rec["source"], set()).add(rec["settle_kind"])
    observed: dict[str, set] = {}
    for src, kind in df[["source", "settle_kind"]].drop_duplicates().itertuples(index=False):
        observed.setdefault(str(src), set()).add(str(kind))
    fails = []
    for src in sorted(observed):
        want = declared.get(src)
        if want is None:
            fails.append(f"(6) observed source {src!r} is absent from CONTRACT_MAP")
            continue
        if observed[src] != want:
            fails.append(f"(6) source {src!r}: observed settle_kind(s) {sorted(observed[src])} != "
                         f"declared {sorted(want)}")
        if len(observed[src]) != 1:
            fails.append(f"(6) source {src!r} carries MULTIPLE settle_kinds -- the cross-tab must "
                         f"stay 1:1")

    settle_cov: list[dict] = []
    if {"settle", "leviathan_slug", "trade_date"} <= set(df.columns):
        s = df[df["settle_kind"].astype(str) == SETTLEMENT_KIND].copy()
        if len(s):
            s["root"] = s["leviathan_slug"].map(SLUG_TO_ROOT)
            s["year"] = pd.to_datetime(s["trade_date"], errors="coerce").dt.year
            nonnull = pd.to_numeric(s["settle"], errors="coerce").notna()
            grouped = nonnull.groupby([s["root"], s["year"]])
            for (root, year), frac in grouped.mean().items():
                n = int(grouped.size().loc[(root, year)])
                rec = {"root": str(root), "year": int(year), "rows": n,
                       "settle_nonnull_frac": round(float(frac), 4)}
                settle_cov.append(rec)
                if float(frac) < SETTLEMENT_MIN_NONNULL_FRAC:
                    fails.append(
                        f"(6) {root}/{int(year)}: only {frac:.4f} of the {n} rows labelled "
                        f"settle_kind='{SETTLEMENT_KIND}' carry a non-null settle (floor "
                        f"{SETTLEMENT_MIN_NONNULL_FRAC}) -- the GLBX statistics join matched "
                        f"almost nothing; check the ts_ref trading date against the ts_event UTC day")
    return fails, {"observed": {k: sorted(v) for k, v in sorted(observed.items())},
                   "declared": {k: sorted(v) for k, v in sorted(declared.items())},
                   "settlement_coverage": sorted(settle_cov,
                                                 key=lambda r: (r["root"], r["year"])),
                   "settlement_min_nonnull_frac": SETTLEMENT_MIN_NONNULL_FRAC}


# ---------------------------------------------------------------------------
# gate 7 -- 12/12 front-month parity vs silver_futures_prices
# ---------------------------------------------------------------------------
def gate7_front_month_parity(eod: pd.DataFrame, flat: pd.DataFrame, *,
                             lookback: int = PARITY_LOOKBACK_DAYS,
                             roll_pct: float = PARITY_ROLL_PCT,
                             median_floor: float = PARITY_MEDIAN_FLOOR) -> tuple[list[str], dict]:
    """Apply the D8 rule to ``silver_futures_eod`` and compare to ``silver_futures_prices.close``.

    Divergence AT rolls is the point and is only reported. The assertion is on the away-from-roll
    median absolute relative difference.

    SELECTION + FLOORS (measured 2026-07-29, four-way corn comparison): the reference lane rolls
    BY VOLUME and its "close" is the settlement print -- front-by-volume x settle reproduced it
    with median 0.00000 (exact), while the D8 front-by-OI choice sits ~2.1% away (a calendar
    spread, not an error). The parity selection is therefore FR.legacy_lane_front (nearest eligible month) -- emulate
    the lane being retired, not the serving rule. Floors are per-lane: GLBX carries real
    settlements and must match near-exactly (0.005); ICE settlements were NOT purchased
    ($1,960), our ICE settle IS the venue close, and the reference prints settlements -- the
    measured venue-close-vs-settlement gap makes 0.005 unattainable there by construction, so
    ICE gates at 0.02 until the free ICE Report Center settlement source lands (the plan's own
    later increment)."""
    if flat is None or flat.empty:
        return ["(7) silver_futures_prices frame is empty"], {}
    front = FR.legacy_lane_front(eod)
    if front.empty:
        return ["(7) the D8 front-month rule selected NO contracts"], {}
    flat = flat.copy()
    date_col = "date" if "date" in flat.columns else "trade_date"
    flat[date_col] = pd.to_datetime(flat[date_col], errors="coerce")

    per_slug, fails = [], []
    for slug in PARITY_SLUGS:
        f = flat[flat["leviathan_slug"] == slug][[date_col, "close"]].dropna()
        e = front[front["leviathan_slug"] == slug][["trade_date", "settle", "contract_month"]].dropna(
            subset=["trade_date"])
        if f.empty or e.empty:
            fails.append(f"(7) {slug}: no overlapping rows (flat={len(f)}, eod={len(e)})")
            per_slug.append({"leviathan_slug": slug, "n": 0, "median_abs_rel": None,
                             "roll_days": None, "status": "NO_DATA"})
            continue
        f = f.sort_values(date_col).tail(lookback * 2)
        merged = e.merge(f, left_on="trade_date", right_on=date_col, how="inner",
                         suffixes=("_eod", "_flat"))
        merged = merged.sort_values("trade_date").tail(lookback)
        if merged.empty:
            fails.append(f"(7) {slug}: no matching trade dates in the last {lookback} rows")
            per_slug.append({"leviathan_slug": slug, "n": 0, "median_abs_rel": None,
                             "roll_days": None, "status": "NO_OVERLAP"})
            continue
        merged["rel"] = (merged["settle"] - merged["close"]).abs() / merged["close"].abs()
        # A roll is a level break in the CONTINUOUS series -- detect it on the flat close, which is
        # the series that carries the splice, and on a contract_month change in the eod series.
        chg = merged["close"].pct_change().abs()
        rolled = (chg > roll_pct) | (merged["contract_month"] != merged["contract_month"].shift(1))
        rolled = rolled.fillna(True)
        away = merged[~rolled]
        med = float(away["rel"].median()) if len(away) else None
        rec = {"leviathan_slug": slug, "n": int(len(merged)), "n_away": int(len(away)),
               "roll_days": int(rolled.sum()),
               "median_abs_rel": round(med, 6) if med is not None else None,
               "p90_abs_rel": round(float(away["rel"].quantile(0.9)), 6) if len(away) else None,
               "max_abs_rel_at_rolls": round(float(merged[rolled]["rel"].max()), 6)
                                       if int(rolled.sum()) else None,
               "status": "OK"}
        per_slug.append(rec)
        slug_floor = median_floor if SLUG_TO_ROOT.get(slug) not in _ICE_ROOTS else PARITY_MEDIAN_FLOOR_ICE
        rec["floor"] = slug_floor
        if med is None:
            fails.append(f"(7) {slug}: every compared day was a detected roll -- no away-from-roll "
                         f"sample to assert on")
        elif med >= slug_floor:
            fails.append(f"(7) {slug}: away-from-roll median |rel diff| {med:.5f} >= floor "
                         f"{slug_floor}")
    covered = {r["leviathan_slug"] for r in per_slug if r["status"] == "OK"}
    if len(covered) != len(PARITY_SLUGS):
        fails.append(f"(7) parity covered {len(covered)}/12 slugs; missing "
                     f"{sorted(set(PARITY_SLUGS) - covered)}")
    return fails, {"per_slug": per_slug, "lookback": lookback, "roll_pct": roll_pct,
                   "median_floor": median_floor, "roll_rule_version": FR.ROLL_RULE_VERSION}


# ---------------------------------------------------------------------------
# gate 8 -- the W1a-style chain hooks
# ---------------------------------------------------------------------------
def gate8_chain_hooks(repo: Path = _REPO) -> tuple[list[str], dict]:
    """Byte-identity shadow / F013 registered-partition verify / unit three-way lint /
    numbers_parity / silver_rebuild_gate -- wired, not merely intended.

    Everything checkable IN PROCESS is asserted here; the two that need a live account
    (``numbers_parity``, ``silver_rebuild_gate``) are EMITTED as exact commands so the orchestrator
    runs them rather than this validator reaching for AWS."""
    import yaml

    fails: list[str] = []
    rec: dict = {}

    # (a) the F010 contract: registered + projection forbidden + registered-partition write mode.
    contract_path = repo / "configs" / "silver" / "tables" / "silver_futures_eod.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    rec["partition_mode"] = contract.get("partition_mode")
    rec["projection"] = contract.get("projection")
    rec["write_mode"] = contract.get("write_mode")
    if contract.get("partition_mode") != "registered" or contract.get("projection") != "forbidden":
        fails.append("(8) registry is not partition_mode=registered + projection=forbidden")
    if contract.get("write_mode") != "registered-partition":
        fails.append("(8) registry write_mode is not 'registered-partition' (the F013 path)")

    # (b) the MANDATORY row validator wiring -- the conditional invariants the contract cannot
    #     express. A producer that drops it writes natural-key-colliding rows past every gate.
    task = repo / _PRODUCER_TASK
    rec["producer_task"] = _PRODUCER_TASK
    if not task.exists():
        fails.append(f"(8) producer task {_PRODUCER_TASK} is missing")
    else:
        text = task.read_text(encoding="utf-8")
        rec["row_validator_wired"] = _ROW_VALIDATOR_TOKEN in text
        if not rec["row_validator_wired"]:
            fails.append(f"(8) {_PRODUCER_TASK} does not pass {_ROW_VALIDATOR_TOKEN} to "
                         f"build_partitioned_publish")
        rec["uses_partitioned_publish"] = "build_partitioned_publish" in text
        if not rec["uses_partitioned_publish"]:
            fails.append(f"(8) {_PRODUCER_TASK} does not go through build_partitioned_publish")

    # (c) the unit three-way lint + the D8 roll lint.
    from leviathan.graphrag import config_check as cc
    eod_errs = cc.check_futures_eod()
    roll_errs = cc.check_futures_roll()
    rec["config_check_futures_eod"] = eod_errs
    rec["config_check_futures_roll"] = roll_errs
    fails += [f"(8) config_check futures_eod: {e}" for e in eod_errs]
    fails += [f"(8) config_check futures_roll: {e}" for e in roll_errs]

    # (d) EVERY futures_eod DAG descriptor + its byte-identical render. Both chains write to the
    #     SAME table through the SAME task and the same registered-partition publisher, so a
    #     descriptor drift on either one is a drift on this table -- checking only the Databento
    #     chain would leave the four free venues' schedule ungated.
    rec["descriptors"] = {}
    rec["crons"] = {}
    dags = repo / "configs" / "silver" / "dags"
    for schedule in _DAG_SCHEDULES:
        desc = dags / f"{schedule}.json"
        rendered = dags / "_rendered" / f"{schedule}.input.json"
        sched = dags / "_rendered" / f"{schedule}.schedule.json"
        per = {"descriptor": desc.exists(), "rendered_input": rendered.exists(),
               "rendered_schedule": sched.exists()}
        rec["descriptors"][schedule] = per
        if not desc.exists():
            fails.append(f"(8) DAG descriptor {desc.name} is missing")
            continue
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gen_sfn_inputs", repo / "scripts" / "silver" / "gen_sfn_inputs.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        d = json.loads(desc.read_text(encoding="utf-8"))
        viol = gen.lint_descriptor(d, schedule)
        per["descriptor_lint"] = viol
        fails += [f"(8) {schedule} descriptor lint: {v}" for v in viol]
        rec["crons"][schedule] = d.get("cron")
        if rendered.exists():
            want = json.dumps(gen.render_input(d), indent=2, ensure_ascii=True, sort_keys=True) + "\n"
            if rendered.read_text(encoding="utf-8") != want:
                fails.append(f"(8) {schedule} rendered .input.json has DRIFTED -- re-run "
                             f"gen_sfn_inputs.py")
        else:
            fails.append(f"(8) rendered input {rendered.name} is missing")
        if not sched.exists():
            fails.append(f"(8) rendered schedule {sched.name} is missing")
    # The two chains must not fire at the same instant: they publish to the same registered
    # partitions through the same fixed object keys, so an overlap is a lost-update race that
    # neither the shrink assertion nor the census would attribute correctly.
    crons = [c for c in rec["crons"].values() if c]
    if len(crons) != len(set(crons)):
        fails.append(f"(8) two futures_eod chains share a cron {sorted(rec['crons'].items())} -- "
                     f"they write the same partitions through the same object keys")

    # (e) the two live-account legs, emitted rather than run.
    #     One per chain: each descriptor names its OWN census baseline, and the gate diffs against
    #     whatever the descriptor names, so running only one of them would leave the other chain's
    #     rows looking like unexplained drift.
    rec["emitted_commands"] = [
        f"python -m jobs.audit.silver_rebuild_gate --tables silver_futures_eod "
        f"--asof <YYYY-MM-DD> --baseline-uri "
        f"s3://leviathan-dev-shahem-001/cascade_census/rolling/{schedule}/census.json"
        for schedule in _DAG_SCHEDULES
    ] + ["python -m jobs.utils.numbers_parity --tables silver_futures_eod"]
    return fails, rec


# ---------------------------------------------------------------------------
# evaluate + render
# ---------------------------------------------------------------------------
def evaluate(*, eod: pd.DataFrame = None, manifests: list[dict] = None,
             flat: pd.DataFrame = None, skip: set = frozenset(), repo: Path = _REPO,
             eod_uri: str = "", manifest_uri: str = "", flat_uri: str = "",
             ice_raw_counts: dict = None, continuity_slugs=None) -> dict:
    """Run all nine gates and build the artifact. PURE apart from the generated_at stamp and
    gate 8's repo reads. ``continuity_slugs`` scopes gate 9 (STEP-12 F7) and is stamped into the
    artifact as ``continuity_scope`` (None = every Databento root)."""
    results: dict = {}
    failures: list[str] = []

    def _run(num: int, fn, available: bool):
        if num in skip:
            results[num] = {"status": "WAIVED", "detail": {}}
            return
        if not available:
            results[num] = {"status": "SKIPPED", "detail": {}}
            failures.append(f"({num}) SKIPPED -- input not supplied; a silently skipped gate is "
                            f"indistinguishable from a passing one (waive with --skip {num})")
            return
        fails, detail = fn()
        results[num] = {"status": "FAIL" if fails else "PASS", "detail": detail,
                        "failures": fails}
        failures.extend(fails)

    has_eod = eod is not None and len(eod) > 0
    _run(1, lambda: gate1_uniqueness(eod), has_eod)
    _run(2, lambda: gate2_dropped_symbols(manifests or []), manifests is not None)
    _run(3, lambda: gate3_bar_counts(eod, ice_raw_counts=ice_raw_counts), has_eod)
    _run(4, lambda: gate4_no_forward_fill(eod), has_eod)
    _run(5, lambda: gate5_ifeu_sanity(eod), has_eod)
    _run(6, lambda: gate6_settle_kind_cross_tab(eod), has_eod)
    _run(7, lambda: gate7_front_month_parity(eod, flat), has_eod and flat is not None)
    _run(8, lambda: gate8_chain_hooks(repo), True)
    _run(9, lambda: gate9_month_continuity(eod, slugs=continuity_slugs), has_eod)

    return {
        "gate": "futures_eod_gate",
        "plan": "docs/private/PRICE_AND_PLAYBOOKS_PLAN.md W2 gates 1-8 + V2-4 gate 9",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "eod_uri": eod_uri, "manifest_uri": manifest_uri, "futures_prices_uri": flat_uri,
        # Stamped into every artifact: the F2 dedupe rule in force when these rows were built is
        # part of what "gate 1 passed" MEANS, and probe P3 can still flip it.
        "ice_bar_rule": ICE_BAR_RULE,
        "roll_rule_version": FR.ROLL_RULE_VERSION,
        "waived": sorted(skip),
        "continuity_scope": sorted(set(continuity_slugs)) if continuity_slugs else None,
        "gates": {str(k): v for k, v in sorted(results.items())},
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }


_GATE_TITLES = {
    1: "(leviathan_slug, trade_date, raw_symbol) uniqueness, table-wide",
    2: "dropped-symbol count NON-ZERO for every root",
    3: "bar-count reconciliation vs the plan table (+/-2%)",
    4: "no forward fill on the most-deferred contracts of EVERY slug (per-slug sample)",
    5: "IFEU sanity (robusta / white sugar)",
    6: "settle_kind x source cross-tab + settlement rows carry a settle",
    7: "12/12 front-month parity vs silver_futures_prices",
    8: "chain hooks (byte-identity / F013 / unit lint / parity)",
    9: "month continuity per Databento root (no empty calendar month inside the banked span; "
       "scoped by --continuity-slug when a sitting names its slugs)",
}


def render_report(art: dict) -> str:
    """ASCII-only report (the Windows console is cp1252)."""
    L = [f"=== silver_futures_eod W2 gate ({len(GATE_IDS)} deterministic checks) ===",
         f"generated_at   : {art['generated_at']}",
         f"eod            : {art['eod_uri'] or 'n/a'}",
         f"manifests      : {art['manifest_uri'] or 'n/a'}",
         f"futures_prices : {art['futures_prices_uri'] or 'n/a'}",
         f"ICE_BAR_RULE   : {art['ice_bar_rule']}   roll_rule: {art['roll_rule_version']}",
         f"gate 9 scope   : "
         f"{', '.join(art.get('continuity_scope') or []) or 'every Databento root (unscoped)'}",
         ""]
    for num in GATE_IDS:
        rec = art["gates"].get(str(num)) or {}
        L.append(f"[{rec.get('status', 'MISSING'):<7s}] gate {num}: {_GATE_TITLES[num]}")
        for f in rec.get("failures", [])[:5]:
            L.append(f"           - {f}")
    d1 = (art["gates"].get("1") or {}).get("detail") or {}
    if d1.get("cross_slug_symbol_advisory"):
        L.append("")
        L.append("gate 1 WARN (advisory, NOT a failure): one vendor raw_symbol under MORE THAN ONE "
                 "leviathan_slug on a date.")
        L.append("           The usual cause is a CONTRACT_MAP re-point whose superseded "
                 "(leviathan_slug, trade_year) partitions were never dropped, which double-counts "
                 "one history under two names.")
        for r in d1["cross_slug_symbol_advisory"]:
            L.append(f"  {r['trade_date']}  {r['raw_symbol']:<12s} n_slugs={r['n_slugs']}  "
                     f"{', '.join(r['slugs'])}")
    d3 = (art["gates"].get("3") or {}).get("detail") or {}
    if d3.get("rows"):
        L.append("")
        L.append("gate 3 detail (root/year expected vs observed):")
        for r in d3["rows"]:
            tag = "gated" if r["gated"] else "recorded"
            obs = "MISSING" if r["observed"] is None else str(r["observed"])
            rel = 0 if r["rel_diff"] is None else r["rel_diff"] * 100
            L.append(f"  {r['root']:<4s} {r['year']}  exp={r['expected']:<6d} obs={obs:<7s} "
                     f"rel={rel:+.1f}%  basis={r.get('basis', 'silver')}  [{tag}]")
    d5 = (art["gates"].get("5") or {}).get("detail") or {}
    if d5.get("degenerate_clause2"):
        L.append("")
        L.append("gate 5 NOTE: settle == close on every IFEU row (settle_kind='close'), so the "
                 "close-vs-settle clause is DEGENERATE by construction until a free ICE settlement "
                 "reference lands. The bar-consistency clause is the part that can fire today.")
    d7 = (art["gates"].get("7") or {}).get("detail") or {}
    if d7.get("per_slug"):
        L.append("")
        L.append("gate 7 distribution (away-from-roll |rel diff|):")
        for r in d7["per_slug"]:
            # every numeric field is None-safe: a NO_DATA slug (e.g. a root awaiting its last
            # vendor file) carries None counts, and the report must render, not crash
            n = r.get("n") or 0
            away = r.get("n_away") or 0
            rolls = r.get("roll_days") or 0
            med = "n/a" if r.get("median_abs_rel") is None else format(r["median_abs_rel"], ".5f")
            L.append(f"  {r['leviathan_slug']:<28s} n={n:<4d} away={away:<4d} "
                     f"rolls={rolls:<3d} median={med}  [{r['status']}]")
    d8 = (art["gates"].get("8") or {}).get("detail") or {}
    if d8.get("emitted_commands"):
        L.append("")
        L.append("gate 8 emitted (run these against the live account):")
        for c in d8["emitted_commands"]:
            L.append(f"  $ {c}")
    if art["failures"]:
        L.append("")
        L.append("FAILURES:")
        for f in art["failures"]:
            L.append(f"  - {f}")
    L.append("")
    L.append(f"VERDICT: {art['verdict']}")
    return "\n".join(L)


def _put_report(uri: str, art: dict, region: str) -> str:
    """Upload the JSON artifact. Refused if the key lands under a DATA prefix -- a validator must
    never be able to write a data surface."""
    import boto3

    bucket, key = split_s3_uri(uri)
    if any(key.startswith(p) for p in _FORBIDDEN_REPORT_PREFIXES):
        raise SystemExit(f"--report-s3 key '{key}' is under a data prefix -- refused")
    boto3.client("s3", region_name=region).put_object(
        Bucket=bucket, Key=key, Body=json.dumps(art, indent=2, sort_keys=True, default=str).encode("utf-8"),
        ContentType="application/json")
    return uri


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="silver_futures_eod W2 gates (read-only; NO Athena)")
    ap.add_argument("--eod-uri", default=None,
                    help="s3 prefix / local dir of the registered silver_futures_eod partitions")
    ap.add_argument("--manifest-uri", default=None,
                    help="s3 prefix / local dir holding symbology_{root}_{year}.json (gate 2)")
    ap.add_argument("--futures-prices-uri", default=None,
                    help="s3 uri / local path of silver_futures_prices (gate 7)")
    ap.add_argument("--skip", action="append", type=int, default=None, choices=list(GATE_IDS),
                    help="explicitly WAIVE a gate (recorded in the artifact); repeatable")
    ap.add_argument("--continuity-slug", action="append", default=None, dest="continuity_slugs",
                    help="SCOPE gate 9 (month continuity) to this leviathan_slug (repeatable): the "
                         "slug(s) a sitting touched. Unscoped judges every Databento root, which "
                         "includes the 15 shipped roots' never-measured history -- record that "
                         "pre-state on the canonical prefix BEFORE a promote (runbook D6b) and "
                         "scope the post-promote run; the scope is stamped in the artifact")
    ap.add_argument("--report-s3", default=None)
    ap.add_argument("--aws-region", default="us-east-1")
    args = ap.parse_args(argv)

    uris = [u for u in (args.eod_uri, args.manifest_uri, args.futures_prices_uri) if u]
    s3 = _ReadOnlyClient(args.aws_region) if any(u.startswith("s3://") for u in uris) else None

    eod = load_eod_frame(args.eod_uri, s3) if args.eod_uri else None
    manifests = load_manifests(args.manifest_uri, s3) if args.manifest_uri else None
    flat = load_flat_frame(args.futures_prices_uri, s3) if args.futures_prices_uri else None
    ice_raw_counts = None
    if args.manifest_uri and s3 is not None:
        # gate 3's ICE basis: PRE-dedupe row counts from the raw payloads (see gate3_bar_counts).
        try:
            _b, _k = split_s3_uri(args.manifest_uri)
            ice_raw_counts = load_ice_raw_bar_counts(s3, _b, _k)
        except Exception as e:  # noqa: BLE001 -- gate 3 then fails per-unit with the reason
            print(f"WARN: ICE raw bar counts unavailable ({type(e).__name__}: {e})")

    art = evaluate(eod=eod, manifests=manifests, flat=flat, skip=set(args.skip or []),
                   eod_uri=args.eod_uri or "", manifest_uri=args.manifest_uri or "",
                   flat_uri=args.futures_prices_uri or "", ice_raw_counts=ice_raw_counts,
                   continuity_slugs=set(args.continuity_slugs or []))
    print(render_report(art))
    if args.report_s3:
        print(f"report artifact -> {_put_report(args.report_s3, art, args.aws_region)}")
    return 0 if art["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
