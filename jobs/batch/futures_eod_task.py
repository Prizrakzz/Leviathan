#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W2 + W1a + W1b -- the ``silver_futures_eod`` producer task, all sources.

ONE TASK, ``--source``-DISPATCHED
--------------------------------
``silver_futures_eod`` has one contract, one partition scheme, one row validator and one merge
rule, and roughly ten producers landing against it. So the publish spine -- authorization, the two
uniqueness assertions, the canonical merge, the registered-partition publish -- is shared, and only
two things are per-source: how a UNIT is read out of raw, and how its bronze becomes silver. Those
two hang off :data:`_SOURCE_SPECS`; adding a leg is a module plus one entry.

``--source databento`` (the DEFAULT, so every W2 invocation is unchanged)
    Units are ``(root, year)``. The vendor package is required and preflighted.
``--source czce``
    Units are SESSIONS -- one ``FutureDataDaily.txt`` per trading day, landed by
    ``jobs/ingest/fetch_czce_eod.py``. No vendor package, no key.
``--source jse``
    Units are CAPTURES -- one overwritten-daily ``NEW DAYAGR.xls`` per fetch, landed by
    ``jobs/ingest/fetch_jse_safex_daily.py``. The SESSION date comes from inside the sheet, not
    from the key. This leg has NO history and no backfill, by source.
``--source cepea``
    Units are per-INDICATOR objects of two kinds: the daily widget captures and the one-shot
    archive series. The rows are CASH REFERENCES -- ``instrument_kind='cash_index'`` with a NULL
    ``contract_month``, the only such rows in the table.
``--source miax``
    Units are SESSIONS -- one settlement CSV per trading day, landed by
    ``jobs/ingest/fetch_miax_eod.py``. No vendor package, no key; and no volume or open interest,
    which the file simply does not publish.

THE THREE W1c BROWSER LEGS (``dce``, ``euronext``, ``bursa``) ARE COMPLETE
--------------------------------------------------------------------------
They landed in two waves and the seam is worth remembering, because the machinery it left behind is
still load-bearing for the NEXT leg. First half: a headless-Chromium producer under ``jobs/ingest/``
plus a transform under ``transforms/raw_to_bronze/`` -- during which each spec carried
``implemented=False`` and a ``todo`` naming the exact module still to be written, so ``main()``
refused the source before building any AWS client and ``_silver_builder`` raised a
``NotImplementedError`` carrying the same string. Second half: the bronze -> silver projections
(``transforms/bronze_to_silver/{dce_eod,euronext_eod,bursa_fcpo}.py``), which is what flipped these
three to ``implemented=True``. Declaring ahead of implementing kept the floors, the unit readers and
the source vocabulary in ONE table throughout, and the refusal path stays wired for whatever lands
next -- an unimplemented leg must FAIL, never write nothing quietly (the yfinance lesson).

That a leg is implemented is NOT that it is scheduled: ``configs/silver/dags/futures_eod_free.json``
still carries the four W1a/W1b venues only, and arming these three is a separate decision behind
probe P10 (and, for DCE, behind a full five-variety live capture -- its per-day floor is 0).

``--source dce``
    Units are per-VARIETY objects of two kinds (the CEPEA shape): the daily quote captures and the
    per-``(variety, year)`` history workbooks. Five varieties, the whole ``source == "dce"`` set.
``--source euronext``
    Units are per-PRODUCT day captures -- the rendered ``future-prices-table`` outerHTML for each of
    EBM/EMA/ECO. Client-side rendering, no WAF.
``--source bursa``
    Units are per-CODE day captures of the ``ses=day`` derivatives-prices API (FCPO). A
    FORWARD-ACCUMULATION leg: the API takes no date parameter, so there is no backfill to run.

TWO DIFFERENT ROW FLOORS, NEVER CONFLATED
-----------------------------------------
:data:`_MIN_ROWS_PER_UNIT` (25) is DATABENTO'S: a per-``(root, year)`` BRONZE floor, whose
justification is that the thinnest legitimate full vendor year is 750 bars. The free legs' floor is
a different measurement entirely -- plan gate 5, a per-SOURCE per-DAY floor on the rows WRITTEN TO
SILVER for that leg's slugs (CZCE >= 10, JSE >= 14, CEPEA == 2, MIAX >= 6, EURONEXT >= 24,
BURSA >= 20, and DCE deliberately unarmed at 0). A CEPEA day is two rows
and would trip a 25-row unit floor; a CZCE raw file has 269 LINES and 13 kept rows, so a
line-counting floor would pass a leg that wrote nothing.

The plan's F-C warning is the reason the wording above is exact. Its JSE case: the sheet carries
four sections containing the substring "MAIZE", two of which are the separate GRADE 2 deliverable,
so a substring section match yields 22 rows/day where the correct parse yields 18 -- and a floor of
20 sits BETWEEN them, pushing whoever chases the red gate straight INTO the bug. Therefore, here:
floors are exact row COUNTS (``groupby(trade_date).size()``) over rows whose ``source`` column
EQUALS the leg's publication source -- never a substring test, never a line count, never a
``str.contains``. And per F-C the floors are armed only after probe P10 has recalibrated them
against a real backfill, which is what ``--row-floor report`` is for.

THE MONTH-CONTINUITY GATE (V2-4 M2) AND ``--continuity``
---------------------------------------------------------
A databento BACKFILL assembly must carry >= 1 trade date in every calendar month inside each slug's
banked span; a hole fails the run before a byte is staged, naming the months (the settlement-tape
backfill runs under the default ``enforce``). ``--continuity report`` mirrors ``--row-floor
report`` (STEP-12 F8): the holes are still logged as ``MONTH_CONTINUITY`` lines but the run
continues -- the lawful way to publish a shipped-root REPAIR backfill over a REAL vendor-outage
month. The 15 shipped roots' continuity has never been measured (KE from 2014, ICE from
2018-12-24, ZR's thin years), so without a report mode a re-derivation of e.g. KE/2015 after a
transform fix would exit 1 on a genuine historical gap with no way to publish the correct bytes.
The gate harness's gate 9 names the same holes again, scoped or waived on the operator's own
record. Incremental runs carry a 5-day window and are not a continuity claim in either mode.

THE PUBLISH CONTRACT, BY MODE
-----------------------------
``--publish-mode dry-run`` (the DEFAULT)
    Reads raw from S3, builds bronze + silver in memory, runs the row validator and the partition
    plan, writes NOTHING. No Glue client, and ``s3_client`` may be absent for the publish leg.
``--publish-mode shadow``
    Stages every partition object under the shadow prefix. A live S3 client is required
    (``build_partitioned_publish`` refuses a write mode with ``s3_client=None``). Nothing canonical
    is touched and NO Glue partition is registered.
``--publish-mode canonical``
    Write-verify-REGISTER through the F013 ``PartitionPublisher``: a live S3 client AND a live Glue
    client, an STS identity matching ``PROD_ENVIRONMENT``, a signed approval
    (``LEVIATHAN_APPROVAL_MODE=kms`` + ``LEVIATHAN_KMS_KEY_ID``, or the HMAC pair) and
    ``LEVIATHAN_READINESS`` absent. A partition already registered at a DIFFERENT location is a
    hard error unless a ``RepairAuthorization`` names that exact value tuple.

NEVER MSCK, NEVER PROJECTION. The registry pins ``partition_mode: registered`` +
``projection: forbidden``, and ``build_partitioned_publish`` refuses anything else.

THE ROW VALIDATOR IS MANDATORY
------------------------------
``futures_eod_contracts.lint_frame`` is passed as ``row_validator=`` on EVERY publish. It is the
only place the conditional invariants live -- ``contract_month IS NULL`` iff
``instrument_kind == 'cash_index'``, and per-slug ``unit``/``currency``/``settle_kind``/``source``
equality against ``CONTRACT_MAP``. The F010 contract can only express UNCONDITIONAL nullability, so
without this a producer that dropped the delivery month would write N rows collapsing to ONE
natural key and ``duplicate_check: full`` could not see it (SQL treats each NULL as distinct).

MODES OF OPERATION
------------------
``--mode backfill``  one or more units read from the raw prefix (Databento: ``(root, year)``; the
    free legs: sessions). A backfill unit OWNS its whole ``(leviathan_slug, trade_year)`` partition,
    so it may stage it outright.
``--mode incremental`` D5's nightly: the current-year prefix, ``--since`` bounded. It owns only
    ``--lookback-days`` of the year but stages the WHOLE ``trade_year`` object (one fixed key per
    partition, no append), so it FIRST unions with the existing canonical partitions --
    :func:`merge_with_canonical`. Without that union the nightly run silently truncates the
    current-year partition of every slug to five days, and nothing in the chain would notice:
    vintage_retention is latest-only, ``silver_rebuild_gate`` is a consumer-sync dispatcher that
    checks no row counts, and the standalone W2 gate script is never invoked by the DAG.

TWO UNIQUENESS ASSERTIONS RUN BEFORE ANY STAGING
------------------------------------------------
:func:`assert_no_duplicates` hard-fails on a duplicate natural key AND on a duplicate
``(leviathan_slug, trade_date, raw_symbol)`` -- F2's precondition, on the automated path. (The slug
joined that key when the CEPEA cash rows landed: they carry a NULL ``raw_symbol``, so without it the
two cash slugs collided on every date. See :data:`_F2_KEY`.) ``ICE_BAR_RULE`` is still
PROVISIONAL pending probe P3, ``build_partitioned_publish`` performs no duplicate check, and gate 1
lives in a script no chain phase runs. Correspondingly the DAG descriptor is
``promote_mode: stop_and_notify``: the machine publishes SHADOW only, and a human promotes after P3
and the eight gates.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.silver import futures_eod_contracts as FC  # noqa: E402
from leviathan.silver.flat_producer import authorize_for_contract  # noqa: E402
from leviathan.silver.partitioned_producer import build_partitioned_publish  # noqa: E402
from leviathan.silver.registry import CONFIGS_SILVER_DIR, load_registry  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    bursa_code_prefix,
    cepea_indicator_prefix,
    czce_year_prefix,
    databento_payload_filename,
    databento_payload_prefix,
    databento_symbology_filename,
    dce_variety_prefix,
    euronext_product_prefix,
    jse_safex_year_prefix,
    miax_year_prefix,
    raw_databento_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client  # noqa: E402
from leviathan.transforms.bronze_to_silver.bursa_fcpo import (  # noqa: E402
    build_bursa_fcpo_silver,
)
from leviathan.transforms.bronze_to_silver.cepea import build_cepea_silver  # noqa: E402
from leviathan.transforms.bronze_to_silver.czce_eod import build_czce_eod_silver  # noqa: E402
from leviathan.transforms.bronze_to_silver.databento_eod import (  # noqa: E402
    build_databento_eod_silver,
)
from leviathan.transforms.bronze_to_silver.dce_eod import build_dce_eod_silver  # noqa: E402
from leviathan.transforms.bronze_to_silver.euronext_eod import (  # noqa: E402
    build_euronext_eod_silver,
)
from leviathan.transforms.bronze_to_silver.jse_safex import build_jse_safex_silver  # noqa: E402
from leviathan.transforms.bronze_to_silver.miax_eod import build_miax_eod_silver  # noqa: E402
from leviathan.transforms.raw_to_bronze.cepea import (  # noqa: E402
    CEPEA_INDICATORS,
    build_cepea_history_bronze,
    build_cepea_widget_bronze,
)
from leviathan.transforms.raw_to_bronze.czce_eod import (  # noqa: E402
    CZCE_FIRST_TRADE_DATE,
    build_czce_bronze,
)
from leviathan.transforms.raw_to_bronze.databento_eod import (  # noqa: E402
    DATASET_SLUGS,
    GLBX,
    ICE_BAR_RULE,
    IFEU,
    IFUS,
    ROOT_MAP,
    SETTLEMENT_TAPE_ROOTS,
    apply_ice_settle,
    build_ohlcv_bronze,
    build_settlement_bronze,
    build_statistics_bronze,
    decode_dbn,
    empty_ohlcv_frame,
    glbx_settle_coverage,
    join_glbx_statistics,
    month_continuity_holes,
    root_years,
    statistics_join_diagnostics,
    symbol_anchors_from_artifact,
    symbology_from_artifact,
)
from leviathan.transforms.raw_to_bronze.dce_eod import (  # noqa: E402
    DCE_VARIETY_MAP,
    build_dce_bronze,
)
from leviathan.transforms.raw_to_bronze.jse_safex import build_jse_bronze  # noqa: E402
from leviathan.transforms.raw_to_bronze.miax_eod import (  # noqa: E402
    MIAX_CSV_FIRST_TRADE_DATE,
    build_miax_bronze,
)

logger = get_logger("futures_eod_task")

_TABLE = "silver_futures_eod"
_JOB = "futures_eod_databento"
# The two partition keys, in the contract's declared order (Glue keys positionally).
_PARTITION_COLS = ["leviathan_slug", "trade_year"]
# The table's column shape. TABLE-level, so it comes from the contract module and not from any one
# vendor's transform -- a free leg importing the Databento module for this list would be a fake
# dependency (the bronze_to_silver modules re-export the same names for their own callers).
SILVER_COLUMNS = FC.SILVER_COLUMNS
# DATABENTO'S floor, per (root, year) BRONZE unit -- BACKFILL-SHAPED UNITS ONLY: the thinnest
# legitimate full year in the plan's table is ZR 2019 at 750 bars, and the thinnest legitimate STUB
# is the ICE 2018 six-session opener at 32-66. A unit landing under this is a truncated download,
# not a thin market. It is NOT the free legs' floor -- see the per-source per-day silver floors
# below and the module docstring.
#
# 2026-08-01 RCA (the first-ever incremental databento fire): this flat floor was MODE-BLIND and it
# failed that fire. A --lookback-days 5 unit for a thin root is ~3-4 outrights x 5 sessions -- ZR
# delivered 17 rows with a COMPLETE 17/17 settlement join and OJ 14, both healthy, both under 25,
# both charged as truncated. Worse, the flat floor is simultaneously TOO WEAK for dense roots in
# incremental (corn truncated to 2 of 5 days still clears 25). Vendor truncation cuts WHOLE DAYS
# off a window; it does not thin a complete book -- so the incremental check is DAY COVERAGE per
# unit (every expected weekday session present, one-holiday margin), and this flat floor now
# applies only to backfill/full-year units. See _truncation_error.
_MIN_ROWS_PER_UNIT = 25

# D-PR-16, MEASURED 2026-08-16 on four consecutive green fires (2026-08-12/13/14/15, jobdef
# leviathan-dev-futures-eod-silver:4). The three databento datasets are NOT available to the same
# trade date at the 08:00Z fire: GLBX.MDP3 carries through T-1, both ICE datasets through T-2.
# Measured per fire as max(rows_out / outright_symbols) across each dataset's roots (an outright
# that traded every session pins the count exactly), corroborated by the assembled silver span
# (its max is GLBX's, = T-1, every fire) and by the canonical merge deltas (+133/+140/+132 rows =
# ONE new GLBX session + ONE new ICE session; an ICE-lag-1 world would have added ~205-230).
#
# WHY THIS IS A LAG DECLARATION AND NOT A WIDER MARGIN. Before this, `expected` came off a pure
# weekday calendar ending at T-1, so both ICE datasets sat at EXACTLY present == expected - 1 on
# all four fires: the one-holiday margin was fully consumed by structural lag, leaving the ICE legs
# one venue holiday away from a false truncation verdict on all 8 units, and degrading the check's
# real sensitivity from "lost >= 2 sessions" to "lost >= 1". Widening the margin to 2 would delete
# the only ICE liveness detector this leg has (D-PR-16's explicit refusal). Naming the lag instead
# moves `window_end` to the date the vendor ACTUALLY publishes to, and the margin goes back to
# meaning what it says.
#
# A dataset absent from this map falls back to 1, which reproduces the pre-D-PR-16 window_end
# byte-for-byte (bdate_range(end=today-1, periods=1)[0] IS the last weekday on or before today-1,
# and the old `today - 1 day` fed into bdate_range(since, ...) resolved to the same thing on a
# weekend). So the GLBX path is unchanged by construction, and only the ICE legs move.
_EXPECTED_LAG_SESSIONS: dict[str, int] = {GLBX: 1, IFUS: 2, IFEU: 2}


def _truncation_error(bronze, spec, *, mode: str, since: str | None,
                      dataset: str | None = None) -> str | None:
    """The truncated-download verdict for ONE bronze unit, or None when the unit is healthy.

    backfill: the flat per-unit floor (full-year semantics, unchanged).
    incremental: DAY COVERAGE -- distinct trade dates in the unit vs the weekday sessions in
    [since, window_end], one-holiday margin. ``window_end`` is the last session the UNIT'S OWN
    dataset publishes to, derived from _EXPECTED_LAG_SESSIONS (D-PR-16): T-1 for GLBX, T-2 for both
    ICE datasets. ``dataset`` is None for every non-databento leg, which resolves to lag 1 -- the
    pre-D-PR-16 behaviour, unchanged. Pure, so tests feed it frames directly."""
    if not spec.min_rows_per_unit:
        return None
    if mode != "incremental":
        if len(bronze) < spec.min_rows_per_unit:
            return (f"only {len(bronze)} bronze rows (floor {spec.min_rows_per_unit}) -- "
                    f"treating as a truncated download, not a thin market")
        return None
    if not since:                                       # incremental always computes since; belt only
        return None
    lag = _EXPECTED_LAG_SESSIONS.get(dataset or "", 1)
    # Step back `lag` WEEKDAY sessions from yesterday-UTC. periods=lag with end= pinned means
    # element [0] is the lag-th session back, and lag=1 collapses to "the last weekday on or before
    # yesterday" -- identical to what the old bare `today - 1 day` produced once it was fed to
    # bdate_range below. Never a calendar-day subtraction: a 2-day lag across a weekend is four
    # calendar days, and getting that wrong is the whole bug class this closes.
    window_end = pd.bdate_range(end=datetime.now(tz=timezone.utc).date() - timedelta(days=1),
                                periods=lag)[0].date()
    since_d = datetime.strptime(since, "%Y-%m-%d").date()
    # D-PR-45 / D-SG G1-7, the other half. A straddling window can be covered by TWO units and
    # neither can hold the other's sessions, so a unit is measured against the window CLIPPED TO ITS
    # OWN CALENDAR YEAR. The year is read from the frame (a Databento unit is per-year by
    # construction) rather than plumbed through the shared loop, so this function stays pure and the
    # tests keep feeding it frames directly. A frame spanning two years is left unclipped, i.e.
    # judged exactly as it is today.
    if len(bronze):
        years = set(pd.to_datetime(bronze["trade_date"]).dt.year.unique().tolist())
        if len(years) == 1:
            y = int(next(iter(years)))
            since_d = max(since_d, date(y, 1, 1))
            window_end = min(window_end, date(y, 12, 31))
            if since_d > window_end:
                return None
    expected = len(pd.bdate_range(since_d.isoformat(), window_end.isoformat()))
    if expected <= 0:
        return None
    present = int(bronze["trade_date"].nunique()) if len(bronze) else 0
    if present < expected - 1:                          # one-holiday margin; venue calendars differ
        return (f"only {present} of {expected} expected session(s) present "
                f"(window {since_d.isoformat()}..{window_end.isoformat()}) -- treating as a "
                f"truncated download, not a thin market")
    return None

# ---------------------------------------------------------------------------
# PLAN GATE 5 -- the per-SOURCE per-DAY floors, on rows WRITTEN TO SILVER for that leg's slugs.
# Every one is set BELOW a measured minimum with holiday margin, never guessed:
#   CZCE  measured 13/day on 2015-10-08 (7 RM + 6 OI) and 2026-07-24/27 -> floor 10
#   JSE   measured 18/day (WHITE MAIZE FUTURE 9 + YELLOW MAIZE FUTURE 9) -> floor 14.
#         NOT 20: the GRADE-2 substring parse yields 22, so a floor of 20 sits between the correct
#         answer and the bug and would push an implementer into it (plan F-C).
#   CEPEA measured 2/day, one per cash reference -> EXACTLY 2 (a third row is a defect, not a bonus)
#   MIAX  measured 7/day outrights on 2026-07-28 -> floor 6, PROVISIONAL: one observation, and the
#         W1b leg is not landed. Recalibrate before arming.
# Per F-C, probe P10 recalibrates all of these against a real backfill BEFORE the gate is armed --
# that is what `--row-floor report` is for.
# ---------------------------------------------------------------------------
_MIN_SILVER_ROWS_PER_DAY_CZCE = 10
_MIN_SILVER_ROWS_PER_DAY_JSE = 14
_SILVER_ROWS_PER_DAY_CEPEA = 2          # exact equality, not a floor
_MIN_SILVER_ROWS_PER_DAY_MIAX = 6       # provisional (single observation)
# ---------------------------------------------------------------------------
# The W1c browser legs' floors, on the SAME rule: below a MEASURED minimum, never guessed.
#   EURONEXT  measured 32/day live 2026-07-29 (EBM 12 expiries + EMA 10 + ECO 10) -> floor 24.
#             24 is not arbitrary: losing ANY ONE of the three products takes the day to 20-22, so
#             this floor catches a single-product failure, which is the actual failure mode (three
#             independent page renders, one run).
#   BURSA     measured 24/day live 2026-07-29 (recordsTotal == 24 delivery months, one product,
#             per_page=50 so pagination cannot truncate it) -> floor 20.
#   DCE       NOT SET, and that is the honest state: only ONE of the five varieties was captured
#             live (p, 12 contracts), so there is no measured whole-day minimum and any number here
#             would be a guess sitting somewhere between "correct" and "four varieties silently
#             missing" -- exactly the F-C trap that the JSE floor of 20 was. Arm it after the first
#             full five-variety capture (probe P10). The producer's own NOT_READY guard, not a row
#             floor, is what stops a partial DAILY capture from landing.
# ---------------------------------------------------------------------------
_MIN_SILVER_ROWS_PER_DAY_EURONEXT = 24
_MIN_SILVER_ROWS_PER_DAY_BURSA = 20

# The LIST bounds for the two W1c legs whose raw prefix is keyed on a vendor identity rather than a
# date. Both are enumeration bounds ONLY -- the authoritative product/code -> slug maps live in the
# transforms (linted against CONTRACT_MAP both ways), exactly as CEPEA_INDICATORS does.
EURONEXT_PRODUCTS: tuple[str, ...] = ("EBM-DPAR", "EMA-DPAR", "ECO-DPAR")
# PARKED 2026-09-02 (V2-4): the palm slug's price record moved to the CME USD tape (Databento root
# CPO), so no source=='bursa' slug exists and this roster is EMPTY -- bursa_units discovers nothing
# and `--source bursa` exits 1 ('no session unit(s) selected') until a bursa slug is minted.
# test_bursa_fcpo pins BURSA_CODES == tuple(BURSA_CODE_MAP), both empty.
BURSA_CODES: tuple[str, ...] = ()
# The contract's declared natural key. Asserted UNIQUE on the assembled frame before a single byte
# is staged: `duplicate_check` runs downstream of the write, `lint_frame` checks conditional
# nullability and per-slug label coherence only, and `build_partitioned_publish` performs no
# duplicate check at all -- so without this the F2 double bar reaches a registered surface and the
# plan's "no registered-contract surface consumes ICE bars until a (trade_date, raw_symbol)
# uniqueness assertion passes" precondition is enforced nowhere in the automated path.
_NATURAL_KEY = ["leviathan_slug", "contract_month", "trade_date"]
# The F2 key proper. `raw_symbol` is the vendor identity; two rows sharing it on one trade date is
# the ICE double bar surviving the ICE_BAR_RULE dedupe, which is a hard fail and never a dedupe.
#
# `leviathan_slug` IS part of this key, and that is a CORRECTION, not a weakening. The original
# (trade_date, raw_symbol) pair FALSE-FAILS the whole table the moment the CEPEA rows land: a cash
# reference has no vendor symbol, so both cash slugs write `raw_symbol` NULL, and `dropna=False`
# groups arabica and Campinas corn together on EVERY trade date -- size 2 -> "the F2 double bar
# survived the ICE_BAR_RULE dedupe", a nonsense diagnosis for a CEPEA frame that would block every
# publish including Databento's, since the assertion runs table-wide after the merge. The two other
# candidate fixes were rejected: scoping the assertion to Databento rows leaves the free legs
# unchecked, and writing a SYNTHETIC raw_symbol for the cash rows violates the registry's
# "raw_symbol is verbatim and is NEVER parsed into meaning at ingest" in the opposite direction.
# Adding the slug loses NO detection power for the defect this exists to catch: an ICE double bar
# is two bars of the SAME contract on the same date, so the pair shares its slug and still collides.
_F2_KEY = ["leviathan_slug", "trade_date", "raw_symbol"]


class SourceSpec(NamedTuple):
    """Everything that differs between one leg and the next. Everything else is shared.

    A NamedTuple rather than a dataclass on purpose: this module is loaded by
    ``spec_from_file_location`` (it is a ``jobs/`` script, not an importable package), and
    ``@dataclass`` resolves annotations through ``sys.modules[cls.__module__]``, which is None
    under that loader. The dataclass form imports fine in production and explodes at TEST
    collection -- the worst possible split."""

    name: str                               # the --source token
    job: str                                # the manifest `job` field (a label, never part of a key)
    publication_sources: tuple[str, ...]    # the CONTRACT_MAP `source` values this leg may write
    preflight_imports: tuple[str, ...] = ()  # packages that must exist BEFORE any AWS call
    min_rows_per_unit: int = 0              # a per-UNIT bronze floor (Databento only)
    rows_per_day: int = 0                   # plan gate 5: the per-DAY silver floor, 0 = none yet
    rows_per_day_exact: bool = False        # CEPEA is an equality, not a floor
    # The --mode values the per-day floor is MEANINGFUL in. Default: both.
    #
    # CEPEA is ("incremental",) and that is not a loophole. Its floor is an EQUALITY (exactly one
    # row per cash reference per day), and an equality is a statement about a DAILY publication.
    # The archive backfill loads two series whose first published rows are EIGHT YEARS APART --
    # arabica 1996-09-02, Campinas corn 2004-08-02 -- so every day in [1996, 2004) legitimately
    # carries ONE row, and enforcing "== 2" over that history would fail ~2,000 correct days. The
    # backfill's coverage question is probe P10's ("do the floors hold across holidays?"), answered
    # with `--row-floor report` against a real load, not by weakening the nightly gate.
    rows_per_day_modes: tuple[str, ...] = ("backfill", "incremental")
    implemented: bool = True
    todo: str = ""                          # what an unimplemented leg still needs
    unit_label: str = "unit"


_SOURCE_SPECS: dict[str, SourceSpec] = {
    "databento": SourceSpec(
        name="databento", job=_JOB,
        publication_sources=("databento_glbx_mdp3", "databento_ifus_impact",
                             "databento_ifeu_impact"),
        # The yfinance ImportError silently wrote nothing for six weeks with no freshness alarm.
        # This preflight is that lesson -- and it is SOURCE-CONDITIONAL, because a CZCE run has no
        # business failing on a missing vendor package it never calls.
        preflight_imports=("databento",),
        min_rows_per_unit=_MIN_ROWS_PER_UNIT,
        unit_label="(root, year)"),
    "czce": SourceSpec(
        name="czce", job="futures_eod_czce", publication_sources=("czce",),
        rows_per_day=_MIN_SILVER_ROWS_PER_DAY_CZCE, unit_label="session"),
    "jse": SourceSpec(
        name="jse", job="futures_eod_jse", publication_sources=("jse_safex",),
        # The legacy-OLE read needs xlrd. That is a CORE pyproject dependency (`xlrd>=2.0`), not a
        # [batch] extra, so no image rebuild is owed for it -- but the preflight stays anyway,
        # because the yfinance ImportError that wrote nothing for six weeks was ALSO "obviously
        # installed" until it wasn't, and a leg whose source object is overwritten daily cannot
        # afford a silent no-op.
        preflight_imports=("xlrd",), rows_per_day=_MIN_SILVER_ROWS_PER_DAY_JSE,
        unit_label="session"),
    "cepea": SourceSpec(
        name="cepea", job="futures_eod_cepea", publication_sources=("cepea",),
        # xlrd is needed by the ARCHIVE one-shot only (the daily widget is plain text), but the
        # backfill and the nightly run through the same task, so the preflight covers both.
        preflight_imports=("xlrd",), rows_per_day=_SILVER_ROWS_PER_DAY_CEPEA,
        rows_per_day_exact=True, rows_per_day_modes=("incremental",),
        unit_label="indicator-day"),
    "miax": SourceSpec(
        name="miax", job="futures_eod_miax", publication_sources=("miax",),
        rows_per_day=_MIN_SILVER_ROWS_PER_DAY_MIAX, unit_label="session"),
    # -- W1c, browser-landed. BOTH halves shipped: the producers + raw -> bronze landed first, the
    #    bronze -> silver projections followed (transforms/bronze_to_silver/{dce_eod,euronext_eod,
    #    bursa_fcpo}.py). The floors below are unchanged by that flip -- see the floor block above.
    "dce": SourceSpec(
        name="dce", job="futures_eod_dce", publication_sources=("dce",),
        # The history workbooks are xlsx. openpyxl is a CORE pyproject dependency, so no image
        # rebuild is owed -- but the preflight stays, because the yfinance ImportError that wrote
        # nothing for six weeks was also "obviously installed" until it wasn't.
        preflight_imports=("openpyxl",),
        rows_per_day=0,                     # deliberately unarmed -- see the floor block above
        unit_label="variety-capture"),
    "euronext": SourceSpec(
        name="euronext", job="futures_eod_euronext", publication_sources=("euronext_matif",),
        rows_per_day=_MIN_SILVER_ROWS_PER_DAY_EURONEXT,
        unit_label="product-day"),
    "bursa": SourceSpec(
        name="bursa", job="futures_eod_bursa", publication_sources=("bursa",),
        rows_per_day=_MIN_SILVER_ROWS_PER_DAY_BURSA,
        unit_label="session"),
}


def source_spec(name: str) -> SourceSpec:
    spec = _SOURCE_SPECS.get(name)
    if spec is None:
        raise ValueError(f"unknown --source {name!r} (known: {sorted(_SOURCE_SPECS)})")
    return spec


def preflight(spec: SourceSpec) -> bool:
    """Import-check the leg's packages BEFORE any AWS call. True when the leg may proceed."""
    for mod in spec.preflight_imports:
        try:
            __import__(mod)
        except ImportError:
            logger.error("the %r package is not installed -- the worker image predates the "
                         "pyproject [batch] %s pin; REBUILD + REPIN the worker image", mod, mod)
            return False
    return True


# ---------------------------------------------------------------------------
# D-SG G1-9 -- THE DECLARED-GAP LEDGER
#
# One missing slug-day (EMA-DPAR 2026-08-05, which the venue never published) re-failed EVERY
# nightly fire for seven fires, until the day rolled out of the 5-day lookback. The floor was
# right each time; the REPETITION was the defect. A day recorded in the ledger is excluded from
# the floor arithmetic BY NAME and only while the declared slug is genuinely absent -- so the
# first fire on an UNDECLARED missing day still fails exactly as it does today, and nothing is
# ever excluded quietly. See configs/silver/futures_gaps.yaml for the rules.
# ---------------------------------------------------------------------------
FUTURES_GAPS_PATH = CONFIGS_SILVER_DIR / "futures_gaps.yaml"
_GAP_FIELDS = ("slug", "day", "first_observed", "evidence", "declared_by")


def _gap_day(value, where: str) -> str:
    """One ISO ``YYYY-MM-DD`` date out of a ledger field (PyYAML may hand back a ``date``)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"{FUTURES_GAPS_PATH.name} {where}: {value!r} is not an ISO date") from exc


@lru_cache(maxsize=None)
def load_declared_gaps(path: Optional[Path] = None) -> dict[str, frozenset[str]]:
    """``{day: {slug, ...}}`` from the committed gap ledger. FAIL CLOSED on a malformed row.

    A row here EXCUSES a fence, so a row that cannot be read must never be silently dropped: that
    is the whole difference between "this gap was declared" and "this gap was mistyped". An absent
    file is legal and means "nothing declared"; a present-but-broken file is a hard error.
    """
    src = path or FUTURES_GAPS_PATH
    if not src.exists():
        return {}
    doc = yaml.safe_load(src.read_text(encoding="utf-8"))
    if doc is None:
        return {}
    if not isinstance(doc, list):
        raise ValueError(f"{src.name}: the ledger is a LIST of gap records, got {type(doc).__name__}")
    out: dict[str, set[str]] = {}
    seen: set[tuple[str, str]] = set()
    for i, rec in enumerate(doc):
        where = f"entry {i}"
        if not isinstance(rec, dict):
            raise ValueError(f"{src.name} {where}: expected a mapping, got {type(rec).__name__}")
        unknown = sorted(set(rec) - set(_GAP_FIELDS))
        missing = sorted(set(_GAP_FIELDS) - set(rec))
        if missing or unknown:
            raise ValueError(f"{src.name} {where}: missing {missing}, unknown {unknown} "
                             f"(required: {list(_GAP_FIELDS)})")
        slug = str(rec["slug"])
        if slug not in FC.CONTRACT_MAP:
            raise ValueError(f"{src.name} {where}: {slug!r} is not a silver_futures_eod slug")
        for field in ("evidence", "declared_by"):
            if not str(rec[field] or "").strip():
                raise ValueError(f"{src.name} {where}: {field} is empty -- a gap is declared with "
                                 f"what was checked at the venue, never on its own authority")
        day = _gap_day(rec["day"], f"{where} day")
        _gap_day(rec["first_observed"], f"{where} first_observed")
        if (slug, day) in seen:
            raise ValueError(f"{src.name} {where}: {slug} {day} is declared twice")
        seen.add((slug, day))
        out.setdefault(day, set()).add(slug)
    return {day: frozenset(slugs) for day, slugs in out.items()}


def assert_row_floor(df: pd.DataFrame, spec: SourceSpec,
                     mode: str = "incremental",
                     declared_gaps: Optional[dict[str, frozenset[str]]] = None) -> list[str]:
    """PLAN GATE 5. The per-day silver row count for this leg, as EXACT COUNTS.

    Returns the violating days (empty == pass). Three things this deliberately is NOT:

      * not a count of RAW lines -- CZCE's 269-line file yields 13 kept rows, so a line floor
        passes a leg that wrote nothing;
      * not a substring test on anything -- the F-C GRADE-2 defect is a substring section match
        that silently MERGES two deliverable contracts into one slug and lands a plausible wrong
        number. Rows are selected by ``source ==`` an exact publication-source value, and counted;
      * not a per-unit floor -- ``_MIN_ROWS_PER_UNIT`` is Databento's (root, year) bronze check and
        means something else entirely.

    ``declared_gaps`` (D-SG G1-9) defaults to the committed ledger; pass ``{}`` to judge every day.
    """
    if not spec.rows_per_day or df is None or df.empty:
        return []
    if mode not in spec.rows_per_day_modes:
        logger.info("row floor (%s): not evaluated in --mode %s (meaningful in %s)",
                    spec.name, mode, list(spec.rows_per_day_modes))
        return []
    scoped = df[df["source"].isin(list(spec.publication_sources))]
    alien = sorted(set(df["source"].dropna()) - set(spec.publication_sources))
    if alien:
        return [f"frame carries foreign publication source(s) {alien} for --source {spec.name}"]
    if scoped.empty:
        return [f"no rows with source in {list(spec.publication_sources)}"]
    gaps = load_declared_gaps() if declared_gaps is None else declared_gaps
    # A ledger entry only speaks for the leg that publishes its slug -- otherwise one venue's
    # declared gap would quietly excuse a day on another venue's leg.
    leg_slugs = {slug for slug, rec in FC.CONTRACT_MAP.items()
                 if rec["source"] in spec.publication_sources}
    per_day = scoped.groupby("trade_date", dropna=False).size()
    bad: list[str] = []
    for day, n in per_day.items():
        n = int(n)
        declared = set(gaps.get(str(day)[:10], ())) & leg_slugs
        if declared and _excluded_by_ledger(scoped, day, declared, spec, n):
            continue
        if (n != spec.rows_per_day) if spec.rows_per_day_exact else (n < spec.rows_per_day):
            rel = "==" if spec.rows_per_day_exact else ">="
            bad.append(f"{str(day)[:10]}: {n} row(s), floor {rel} {spec.rows_per_day}")
    return bad


def _excluded_by_ledger(scoped: pd.DataFrame, day, declared: set[str], spec: SourceSpec,
                        n_rows: int) -> bool:
    """True when a DECLARED slug is genuinely absent on ``day``, so the day leaves the arithmetic.

    Absence is re-checked against this run's rows rather than trusted: a ledger entry for a slug
    that DID publish that day is stale, and a stale entry must not excuse a real shortfall."""
    if "leviathan_slug" not in scoped.columns:
        return False
    present = set(scoped.loc[scoped["trade_date"] == day, "leviathan_slug"].dropna().astype(str))
    absent = sorted(declared - present)
    if not absent:
        return False
    logger.warning("row floor (%s): DAY %s EXCLUDED -- declared venue gap for %s "
                   "(configs/silver/futures_gaps.yaml); its %d row(s) are NOT judged against the "
                   "%d/day floor", spec.name, str(day)[:10], ", ".join(absent), n_rows,
                   spec.rows_per_day)
    return True


# ---------------------------------------------------------------------------
# CZCE units -- one SESSION per unit (W1a)
# ---------------------------------------------------------------------------
def czce_units(s3_client, bucket: str, *, since: Optional[str] = None,
               until: Optional[str] = None, years: Optional[list[int]] = None) -> list[str]:
    """The raw keys of the CZCE sessions to read, ascending.

    Discovered by LISTING the landed raw prefix rather than walking a calendar: the venue decides
    which days are sessions (a non-session day is simply a 404 at fetch time and no object is
    landed), so a curated holiday calendar here would be a second, drifting source of truth. The
    LIST is bounded to one ``year=`` prefix at a time -- the Jul-2026 26.8M-LIST storm discipline.
    """
    first = CZCE_FIRST_TRADE_DATE[:4]
    lo = (since or CZCE_FIRST_TRADE_DATE)[:10]
    hi = (until or "9999-12-31")[:10]
    if years:
        span = sorted({int(y) for y in years})
    else:
        last = min(int(hi[:4]), datetime.now(tz=timezone.utc).year) if until else \
            datetime.now(tz=timezone.utc).year
        span = list(range(max(int(first), int(lo[:4])), last + 1))
    keys: list[str] = []
    for year in span:
        for key in _list_keys(s3_client, bucket, czce_year_prefix(year)):
            day = _czce_key_date(key)
            if day is None or not (lo <= day <= hi):
                continue
            keys.append(key)
    return sorted(set(keys))


def _czce_key_date(key: str) -> Optional[str]:
    """``.../trade_date=20260727/FutureDataDaily.txt`` -> ``'2026-07-27'``; None if not a session
    object. The path segment is the ONLY trade-date authority on this leg -- it is also the decade
    anchor for the 3-digit contract code, which is why it is never recovered from the wall clock."""
    for seg in key.split("/"):
        if seg.startswith("trade_date=") and len(seg) == len("trade_date=") + 8:
            token = seg.split("=", 1)[1]
            if token.isdigit():
                return f"{token[:4]}-{token[4:6]}-{token[6:]}"
    return None


def load_czce_session(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed CZCE session object and return its bronze rows + a stats dict."""
    day = _czce_key_date(key)
    if day is None:
        raise ValueError(f"{key} carries no trade_date= segment -- refusing to guess the session")
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no CZCE session object at s3://{bucket}/{key}")
    return build_czce_bronze(payload, trade_date=day)


# ---------------------------------------------------------------------------
# The free-leg key readers (W1a/W1b). All three follow the CZCE doctrine: units are DISCOVERED by
# LISTING what actually landed, never by walking a calendar, so the venue -- not a curated holiday
# table -- decides which days exist, and there is no second source of truth to drift.
# ---------------------------------------------------------------------------
def _key_segment(key: str, prefix: str) -> Optional[str]:
    """The value of the first ``{prefix}=...`` path segment in a raw key, or None."""
    token = prefix + "="
    for seg in key.split("/"):
        if seg.startswith(token):
            return seg.split("=", 1)[1]
    return None


def _iso_from_segment(value: Optional[str]) -> Optional[str]:
    """A path date segment -> ``YYYY-MM-DD``. Accepts both the compact and the dashed form."""
    if not value:
        return None
    compact = value.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
    return None


def _years_span(first_iso: str, since: Optional[str], years: Optional[list[int]]) -> list[int]:
    """The ``year=`` prefixes to LIST, bounded (the Jul-2026 26.8M-LIST storm discipline)."""
    if years:
        return sorted({int(y) for y in years})
    lo = max(int(first_iso[:4]), int((since or first_iso)[:4]))
    return list(range(lo, datetime.now(tz=timezone.utc).year + 1))


# -- JSE ---------------------------------------------------------------------
# The JSE list is bounded from the first capture rather than a venue epoch, because there IS no
# venue epoch: the portal object is overwritten daily and holds no history, so this leg's series
# begins at the first run of the producer and nowhere earlier. 2026 is that first possible year.
JSE_FIRST_CAPTURE_YEAR = 2026


def jse_units(s3_client, bucket: str, *, since: Optional[str] = None,
              years: Optional[list[int]] = None) -> list[str]:
    """The raw keys of the JSE captures to read, ascending by ``as_of_date=``.

    ``since`` filters on the CAPTURE date, which is the only date in the key. The SESSION date is
    read from inside the sheet by the transform, so a capture whose header says T-1 still lands in
    the right partition."""
    lo = (since or "0000-01-01")[:10]
    span = years or list(range(JSE_FIRST_CAPTURE_YEAR,
                               datetime.now(tz=timezone.utc).year + 1))
    keys: list[str] = []
    for year in sorted({int(y) for y in span}):
        for key in _list_keys(s3_client, bucket, jse_safex_year_prefix(year)):
            day = _iso_from_segment(_key_segment(key, "as_of_date"))
            if day is None or day < lo:
                continue
            keys.append(key)
    return sorted(set(keys))


def load_jse_capture(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed JSE capture and return its bronze rows + a stats dict."""
    as_of = _iso_from_segment(_key_segment(key, "as_of_date"))
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no JSE capture at s3://{bucket}/{key}")
    return build_jse_bronze(payload, as_of_date=as_of)


# -- CEPEA -------------------------------------------------------------------
def cepea_units(s3_client, bucket: str, *, since: Optional[str] = None,
                indicators: Optional[list[int]] = None) -> list[str]:
    """The raw keys of the CEPEA captures to read: the archive one-shots FIRST, then the widgets.

    Ordering is load-bearing rather than cosmetic. The two payload classes overlap in time by
    construction (the archive snapshot ends 2025-06 and the widget accumulates forward), and the
    silver step collapses identical ``(slug, trade_date, settle)`` rows keeping the LAST -- so the
    daily capture, which is the fresher observation of any shared day, must arrive last.

    ``since`` filters the WIDGET captures by capture date only. The archive objects are whole-series
    one-shots with no date in their key, so a bounded incremental run skips them entirely."""
    ids = sorted({int(i) for i in (indicators or CEPEA_INDICATORS)})
    history: list[str] = []
    daily: list[str] = []
    lo = (since or "0000-01-01")[:10]
    for ind in ids:
        for key in _list_keys(s3_client, bucket, cepea_indicator_prefix(ind)):
            if "/history/" in key:
                if since is None:
                    history.append(key)
                continue
            day = _iso_from_segment(_key_segment(key, "as_of_date"))
            if day is None or day < lo:
                continue
            daily.append(key)
    return sorted(set(history)) + sorted(set(daily))


def _cepea_indicator_id(key: str) -> int:
    token = _key_segment(key, "indicator")
    if token is None or not token.isdigit():
        raise ValueError(f"{key} carries no indicator= segment -- refusing to guess the slug from "
                         f"the Portuguese product name")
    return int(token)


def load_cepea_capture(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed CEPEA object -- widget or archive -- and return bronze rows + stats."""
    indicator = _cepea_indicator_id(key)
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no CEPEA object at s3://{bucket}/{key}")
    if "/history/" in key:
        # Two history stems, two provenances: wayback_ (web.archive.org, 2017 captures) and
        # live_ (the origin's apex host, user-approved one-shot 2026-07-29). The bronze
        # payload_kind must say which -- a live workbook wearing "wayback" is exactly the
        # provenance lie the live_ stem exists to avoid.
        stem = key.rsplit("/", 1)[-1]
        for prefix, kind in (("wayback_", "wayback"), ("live_", "live")):
            if stem.startswith(prefix):
                ts = stem[len(prefix):-len(".xls")]
                return build_cepea_history_bronze(payload, indicator_id=indicator,
                                                  snapshot_ts=ts, payload_kind=kind)
        return build_cepea_history_bronze(payload, indicator_id=indicator, snapshot_ts=None)
    return build_cepea_widget_bronze(
        payload, indicator_id=indicator,
        as_of_date=_iso_from_segment(_key_segment(key, "as_of_date")))


# -- MIAX --------------------------------------------------------------------
def miax_units(s3_client, bucket: str, *, since: Optional[str] = None,
               years: Optional[list[int]] = None) -> list[str]:
    """The raw keys of the MIAX sessions to read, ascending."""
    lo = max((since or MIAX_CSV_FIRST_TRADE_DATE)[:10], MIAX_CSV_FIRST_TRADE_DATE)
    keys: list[str] = []
    for year in _years_span(MIAX_CSV_FIRST_TRADE_DATE, since, years):
        for key in _list_keys(s3_client, bucket, miax_year_prefix(year)):
            day = _iso_from_segment(_key_segment(key, "trade_date"))
            if day is None or day < lo:
                continue
            keys.append(key)
    return sorted(set(keys))


def load_miax_session(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed MIAX settlement CSV and return its bronze rows + a stats dict."""
    day = _iso_from_segment(_key_segment(key, "trade_date"))
    if day is None:
        raise ValueError(f"{key} carries no trade_date= segment -- refusing to guess the session")
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no MIAX session object at s3://{bucket}/{key}")
    return build_miax_bronze(payload, trade_date=day)


# -- The W1c browser legs (DCE, Euronext, Bursa) -----------------------------
# Same doctrine as every free leg: units are DISCOVERED by LISTING what actually landed. That the
# bytes were obtained through a headless browser is entirely the producer's business and leaves no
# trace here -- a browser-landed object is an ordinary raw object.
def dce_units(s3_client, bucket: str, *, since: Optional[str] = None,
              varieties: Optional[list[str]] = None) -> list[str]:
    """The raw keys of the DCE objects to read: the HISTORY workbooks first, then the daily captures.

    Ordering is load-bearing for the same reason it is on CEPEA: the two payload classes overlap in
    time by construction (the history workbook covers the whole calendar year INCLUDING days the
    daily capture has already landed), and the silver step resolves a natural-key collision in
    favour of the LAST row -- so the daily capture, which is the fresher and post-close observation
    of any shared session, must arrive last.

    ``since`` filters the DAILY captures by capture date only. The history workbooks are whole-year
    one-shots, so a bounded incremental run skips them entirely."""
    letters = sorted(set(varieties or DCE_VARIETY_MAP))
    history: list[str] = []
    daily: list[str] = []
    lo = (since or "0000-01-01")[:10]
    for variety in letters:
        for key in _list_keys(s3_client, bucket, dce_variety_prefix(variety)):
            if "/history/" in key:
                if since is None:
                    history.append(key)
                continue
            day = _iso_from_segment(_key_segment(key, "as_of_date"))
            if day is None or day < lo:
                continue
            daily.append(key)
    return sorted(set(history)) + sorted(set(daily))


def _dce_variety_of(key: str) -> str:
    variety = _key_segment(key, "variety")
    if variety not in DCE_VARIETY_MAP:
        raise ValueError(f"{key} carries no known variety= segment -- refusing to guess the slug "
                         f"from the Chinese commodity name inside the payload")
    return variety


def load_dce_capture(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed DCE object -- daily capture or history workbook -- and return bronze + stats.

    The payload KIND comes from the key (``history/`` is a path segment), never from sniffing the
    bytes: a truncated download must fail as a truncated download, not be re-read as the other
    format."""
    variety = _dce_variety_of(key)
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no DCE object at s3://{bucket}/{key}")
    if "/history/" in key:
        year = _key_segment(key, "year")
        return build_dce_bronze(payload, variety=variety, kind="history",
                                year=int(year) if (year or "").isdigit() else None)
    return build_dce_bronze(payload, variety=variety, kind="daily",
                            as_of_date=_iso_from_segment(_key_segment(key, "as_of_date")))


def _lazy_bronze(module: str, func: str, payload: bytes, **kwargs) -> tuple[pd.DataFrame, dict]:
    """Call a W1c raw->bronze builder that landed with the OTHER half of this wave.

    Imported at CALL time rather than at module scope, and that is the only trick here: the two
    halves of W1c land independently, so this task must import -- and its test suite must COLLECT --
    whether or not the euronext/bursa transforms are in the tree yet. (Both halves have since
    landed, and the bronze -> silver modules import their raw -> bronze counterparts at module
    scope, so the laziness no longer buys anything for THESE two legs. It stays because it is the
    seam the NEXT leg lands through, and because deleting it would re-introduce exactly the
    wave-order dependency it exists to remove.) Everything else is an ordinary
    call, deliberately: the keyword names are the seam, and passing them straight through means a
    rename on either side is an immediate TypeError rather than a silently defaulted argument (
    ``bursa_fcpo.build_bronze`` defaults ``code`` to ``"FCPO"``, so a filtered kwarg there would
    publish the wrong product's rows instead of failing). The join is exercised end to end against
    the live captures in tests/unit/silver/test_futures_eod_free_chain.py."""
    import importlib

    return getattr(importlib.import_module(module), func)(payload, **kwargs)


def euronext_units(s3_client, bucket: str, *, since: Optional[str] = None,
                   products: Optional[list[str]] = None) -> list[str]:
    """The raw keys of the Euronext product-day captures to read, ascending."""
    lo = (since or "0000-01-01")[:10]
    keys: list[str] = []
    for product in sorted(set(products or EURONEXT_PRODUCTS)):
        for key in _list_keys(s3_client, bucket, euronext_product_prefix(product)):
            day = _iso_from_segment(_key_segment(key, "as_of_date"))
            if day is None or day < lo:
                continue
            keys.append(key)
    return sorted(set(keys))


def load_euronext_capture(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed Euronext rendered-table capture and return its bronze rows + a stats dict."""
    product = _key_segment(key, "product")
    if not product:
        raise ValueError(f"{key} carries no product= segment -- refusing to guess which MATIF "
                         f"contract the table belongs to")
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no Euronext capture at s3://{bucket}/{key}")
    return _lazy_bronze("leviathan.transforms.raw_to_bronze.euronext_eod", "build_bronze", payload,
                        product=product,
                        as_of_date=_iso_from_segment(_key_segment(key, "as_of_date")))


def bursa_units(s3_client, bucket: str, *, since: Optional[str] = None,
                codes: Optional[list[str]] = None) -> list[str]:
    """The raw keys of the Bursa day-session captures to read, ascending.

    Forward-accumulation: the API takes no date parameter, so every key here is a capture this
    estate made and there is nothing earlier to walk back to."""
    lo = (since or "0000-01-01")[:10]
    keys: list[str] = []
    for code in sorted(set(codes or BURSA_CODES)):
        for key in _list_keys(s3_client, bucket, bursa_code_prefix(code)):
            day = _iso_from_segment(_key_segment(key, "as_of_date"))
            if day is None or day < lo:
                continue
            keys.append(key)
    return sorted(set(keys))


def load_bursa_capture(s3_client, bucket: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one landed Bursa derivatives-prices capture and return its bronze rows + a stats dict."""
    code = _key_segment(key, "code")
    if not code:
        raise ValueError(f"{key} carries no code= segment -- refusing to guess the contract")
    payload = _get(s3_client, bucket, key)
    if payload is None:
        raise FileNotFoundError(f"no Bursa capture at s3://{bucket}/{key}")
    return _lazy_bronze("leviathan.transforms.raw_to_bronze.bursa_fcpo", "build_bronze", payload,
                        code=code,
                        as_of_date=_iso_from_segment(_key_segment(key, "as_of_date")))


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical target. Module-level seam so tests monkeypatch it
    and unit runs stay AWS-free; an empty identity still fails the guard closed on canonical."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def _get(s3_client, bucket: str, key: str) -> Optional[bytes]:
    try:
        return s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001 -- a missing raw object is an ordinary "unit not fetched yet"
        return None


def _list_keys(s3_client, bucket: str, prefix: str) -> list[str]:
    """Every key under one raw prefix. ``list_objects_v2`` directly rather than a paginator so a
    test double only has to implement the one method the real client already exposes."""
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        try:
            page = s3_client.list_objects_v2(**kwargs)
        except Exception:  # noqa: BLE001 -- an unlistable prefix is an ordinary "nothing there yet"
            return keys
        keys.extend(obj["Key"] for obj in (page.get("Contents") or []))
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            return keys


def resolve_payload_key(s3_client, bucket: str, *, dataset: str, root: str, year: int,
                        schema: str, mode: str = "backfill") -> str:
    """The key of the payload to READ for one ``(root, year, schema)``.

    The name is derived by :func:`leviathan.storage.paths.databento_payload_filename`, the SAME
    function the fetch job writes with. In backfill mode that is deterministic. In INCREMENTAL mode
    the fetch job stamps the file with its own as-of date (``ohlcv-1d_ZC_20260728.dbn.zst``) and
    lands it in the same ``year={current}`` prefix, and the fetch and silver phases of one chain can
    straddle UTC midnight -- so the reader LISTS the prefix and takes the NEWEST as-of stamp rather
    than recomputing a date the writer already chose. A hard-coded ``{schema}_{root}_{year}`` here
    is the defect that makes the nightly chain read a stale backfill object, or nothing at all,
    while the session it just paid for never lands."""
    ds = DATASET_SLUGS[dataset]
    backfill = raw_databento_key(ds, root, year, databento_payload_filename(schema, root, year))
    if mode != "incremental":
        return backfill
    token = databento_payload_prefix(schema, root)
    suffix = ".dbn.zst"
    stamped: list[tuple[str, str]] = []
    for key in _list_keys(s3_client, bucket, raw_databento_key(ds, root, year, "")):
        name = key.rsplit("/", 1)[-1]
        if not (name.startswith(token) and name.endswith(suffix)):
            continue
        stem = name[len(token):-len(suffix)]
        if len(stem) == 8 and stem.isdigit():      # YYYYMMDD == an incremental as-of payload
            stamped.append((stem, key))
    if stamped:
        return max(stamped)[1]
    logger.warning("%s %s/%s %s: no as-of stamped incremental payload under the year prefix -- "
                   "falling back to the backfill object", dataset, root, year, schema)
    return backfill


def load_unit_bronze(s3_client, bucket: str, *, dataset: str, root: str, year: int,
                     ice_bar_rule: str = ICE_BAR_RULE,
                     mode: str = "backfill") -> tuple[pd.DataFrame, dict]:
    """Read one ``(dataset, root, year)`` raw unit and return its bronze rows + a stats dict.

    The DECADE ANCHOR is ``year`` -- the raw path segment, never ``datetime.now()``. The symbology
    artifact is read for its recorded ``dropped_count`` (the gate-2 evidence) and, when the payload
    carries no in-band mappings, as the symbology.json the decode needs -- built from the STEP-2
    chunks by :func:`symbology_from_artifact`. Never from ``resolve_step1``: that is
    ``parent -> instrument_id``, and injecting it maps every instrument to the literal ``'ZC.FUT'``
    so the outright filter drops 100% of the purchased bars."""
    ds = DATASET_SLUGS[dataset]
    settlement_tape = root in SETTLEMENT_TAPE_ROOTS
    sym_key = raw_databento_key(ds, root, year, databento_symbology_filename(root, year))
    # A settlement-tape root buys NO ohlcv-1d payload (fetch: schemas_for); its bar frame is the
    # empty decoded shape and the statistics stream is the row skeleton (build_settlement_bronze).
    ohlcv_key = None if settlement_tape else resolve_payload_key(
        s3_client, bucket, dataset=dataset, root=root, year=year, schema="ohlcv-1d", mode=mode)
    sym_raw = _get(s3_client, bucket, sym_key)
    artifact = json.loads(sym_raw.decode("utf-8")) if sym_raw else {}
    payload = None if ohlcv_key is None else _get(s3_client, bucket, ohlcv_key)
    if payload is None and not settlement_tape:
        raise FileNotFoundError(f"no ohlcv-1d payload at s3://{bucket}/{ohlcv_key}")

    symbology = symbology_from_artifact(artifact)
    # The per-symbol resolved listing-interval starts (d0) -- the decade-decode anchor for roots
    # that declare a listing horizon (V2-4 M1); inert for the others.
    anchors = symbol_anchors_from_artifact(artifact, root=root)
    raw = (empty_ohlcv_frame() if payload is None
           else decode_dbn(payload, schema="ohlcv-1d", symbology_json=symbology))
    bronze, stats = build_ohlcv_bronze(raw, dataset=dataset, root=root, request_year=year,
                                       ice_bar_rule=ice_bar_rule, symbol_anchors=anchors)
    stats["dropped_symbols_recorded"] = artifact.get("dropped_count")
    stats["settlement_base"] = settlement_tape

    if dataset == GLBX:
        stat_key = resolve_payload_key(s3_client, bucket, dataset=dataset, root=root, year=year,
                                       schema="statistics", mode=mode)
        stat_payload = _get(s3_client, bucket, stat_key)
        if stat_payload is None:
            if settlement_tape:
                raise FileNotFoundError(
                    f"{dataset} {root}/{year}: settlement-tape root with NO statistics payload at "
                    f"s3://{bucket}/{stat_key} -- the tape IS the statistics stream")
            logger.warning("%s %s/%s: no statistics payload -- settle stays NULL (F3: the ohlcv "
                           "close is NOT the settlement and is never substituted)",
                           dataset, root, year)
            stat_df = None
        else:
            stat_raw = decode_dbn(stat_payload, schema="statistics", symbology_json=symbology)
            stat_df = build_statistics_bronze(stat_raw, root=root, request_year=year,
                                              keep_instrument_id=settlement_tape, record=stats)
        # BEFORE the join, while both frames still exist: is the ts_ref trading date on the same
        # calendar as the ts_event UTC day? A systematic skew matches nothing and is otherwise silent.
        # (Inert on the empty bar frame of a settlement-tape root.)
        stats["statistics_join"] = statistics_join_diagnostics(bronze, stat_df)
        if settlement_tape:
            bronze, srec = build_settlement_bronze(stat_df, bronze, dataset=dataset, root=root,
                                                   request_year=year, symbol_anchors=anchors)
            stats.update(srec)
        else:
            bronze = join_glbx_statistics(bronze, stat_df)
        stats["glbx_settle_coverage"] = glbx_settle_coverage(bronze)
    else:
        # stats["ice_probe"] arrives from build_ohlcv_bronze, measured PRE-dedupe -- re-probing
        # the deduped bronze here is self-blinding (dup_keys 0 by construction; shipped once).
        bronze = apply_ice_settle(bronze)
    return bronze, stats


def _silver_builder(source: str):
    """The bronze -> silver projection for one leg. Each returns the SAME 17 physical + 2 partition
    columns and each writes unit/currency/settle_kind/source from ``CONTRACT_MAP``, so everything
    downstream of here -- the uniqueness assertions, the merge, the row validator, the publish --
    is source-agnostic."""
    builders = {
        "databento": build_databento_eod_silver,
        "czce": build_czce_eod_silver,
        "jse": build_jse_safex_silver,
        "cepea": build_cepea_silver,
        "miax": build_miax_eod_silver,
        # -- W1c, both halves landed.
        "dce": build_dce_eod_silver,
        "euronext": build_euronext_eod_silver,
        "bursa": build_bursa_fcpo_silver,
    }
    if source in builders:
        return builders[source]
    spec = source_spec(source)
    raise NotImplementedError(
        f"--source {source} is declared (job={spec.job}, per-day row floor "
        f"{'==' if spec.rows_per_day_exact else '>='} {spec.rows_per_day}) but not implemented. "
        f"Still needed: {spec.todo}"
    )


def build_silver(frames: list[pd.DataFrame], source: str = "databento") -> pd.DataFrame:
    """Concatenate bronze units and project onto the 17 physical + 2 partition columns."""
    build = _silver_builder(source)
    live = [f for f in frames if f is not None and len(f)]
    if not live:
        return build(pd.DataFrame())
    return build(pd.concat(live, ignore_index=True))


def assert_no_duplicates(df: pd.DataFrame) -> None:
    """HARD FAIL on a duplicate natural key or a duplicate F2 key.

    Runs on the assembled frame BEFORE a byte is staged. There is no other check on this path:
    ``build_partitioned_publish`` performs none, ``lint_frame`` checks conditional nullability and
    per-slug label coherence only, the contract's ``duplicate_check`` runs against the table AFTER
    the write, and gate 1 lives in a standalone script the chain never invokes. The F2 ICE double
    bar is exactly the failure this catches, ``ICE_BAR_RULE`` is still PROVISIONAL pending probe P3,
    and the plan is explicit that a survivor is a hard fail and never a silent dedupe."""
    if df is None or df.empty:
        return
    # LABEL AND DIAGNOSIS ARE PER-KEY, and that is a fix rather than polish. Both keys used to
    # render "the F2 double bar survived the ICE_BAR_RULE dedupe" -- an ICE diagnosis printed over a
    # South African maize frame or a Brazilian cash frame, which sends the operator chasing a
    # Databento rule that has nothing to do with the failure (the JSE holiday re-serve reproduced
    # exactly this). The F2 label ALSO still read "(trade_date, raw_symbol)" after `_F2_KEY` was
    # widened with `leviathan_slug`, so the message named a key the code no longer groups on.
    for label, key, why in (
        ("natural key (leviathan_slug, contract_month, trade_date)", _NATURAL_KEY,
         "two rows claim the same contract on the same session -- most likely a re-captured source "
         "file whose transform did not collapse the identical re-serve (JSE and CEPEA both "
         "overwrite ONE object in place), or an upstream revision, which is a real conflict"),
        ("F2 key (leviathan_slug, trade_date, raw_symbol)", _F2_KEY,
         "the F2 double bar survived the ICE_BAR_RULE dedupe"),
    ):
        cols = [c for c in key if c in df.columns]
        if len(cols) != len(key):
            raise ValueError(f"frame is missing {sorted(set(key) - set(cols))} -- cannot assert "
                             f"{label} uniqueness")
        sizes = df.groupby(cols, dropna=False).size()
        dups = sizes[sizes > 1]
        if len(dups):
            worst = ", ".join(f"{tuple(str(x)[:10] for x in (k if isinstance(k, tuple) else (k,)))}"
                              f"x{int(v)}" for k, v in dups.sort_values(ascending=False).head(5).items())
            raise ValueError(
                f"{len(dups)} duplicate {label} value(s) in the assembled frame ({worst}) -- {why}; "
                f"refusing to stage. This is a hard fail, never a dedupe: the rule is wrong, not "
                f"the data"
            )


def merge_with_canonical(df: pd.DataFrame, contract: dict, s3_client) -> tuple[pd.DataFrame, dict]:
    """Union a PARTIAL frame with whatever is already canonical in each partition it touches.

    *** WHY THIS EXISTS: THE NIGHTLY RUN OWNS FIVE DAYS AND WRITES A WHOLE YEAR. ***
    ``build_partition_objects`` emits ONE object per ``(leviathan_slug, trade_year)`` group at the
    FIXED key ``.../leviathan_slug=X/trade_year=YYYY/part-000.parquet``. It never reads or appends to
    the existing object, and the key is byte-identical every run, so the put REPLACES the partition.
    A backfill unit owns its whole ``(root, year)`` and that is fine. An INCREMENTAL run holds only
    ``--lookback-days`` of the current year, so publishing it unmerged silently truncates the
    current-year partition of every slug to five days -- automated, unalarmed destruction of
    canonical history (the registry's vintage_retention is latest-only, ``silver_rebuild_gate`` is a
    consumer-sync dispatcher and checks no row counts, and the standalone W2 gate is not in the
    chain).

    So: read the existing object for each touched partition, union, and let the NEW rows win on a
    natural-key collision (a corrected settlement must be able to land). A partition that shrinks is
    a hard fail -- never publish fewer rows than were already there."""
    empty_rec = {"partitions": 0, "partitions_merged": 0, "prior_rows": 0,
                 "rows_in": int(0 if df is None else len(df)), "rows_out": 0}
    if df is None or df.empty:
        return df, empty_rec
    if s3_client is None:
        raise ValueError("merge_with_canonical needs a live S3 client -- an incremental publish "
                         "that cannot read the existing partitions would overwrite them")
    import io

    import pyarrow.parquet as pq
    from leviathan.silver.partitioned_producer import (
        DEFAULT_OBJECT_NAME,
        partition_object_key,
        partition_value_str,
    )

    bucket = contract["s3_bucket"]
    prefix = contract["s3_prefix"]
    types = {pk["name"]: pk.get("glue_type") for pk in contract.get("partition_keys", [])}
    priors: list[pd.DataFrame] = []
    prior_rows_by_partition: dict[tuple, int] = {}
    partitions = 0
    for values, _group in df.groupby(_PARTITION_COLS, dropna=False, sort=True):
        partitions += 1
        values = list(values) if isinstance(values, tuple) else [values]
        rendered = [partition_value_str(c, v, types.get(c))
                    for c, v in zip(_PARTITION_COLS, values)]
        key = partition_object_key(prefix, _PARTITION_COLS, rendered,
                                   filename=DEFAULT_OBJECT_NAME)
        body = _get(s3_client, bucket, key)
        if body is None:
            continue
        prior = pq.read_table(io.BytesIO(body)).to_pandas()
        # The partition columns live in the PATH and were dropped from the body -- put them back
        # from the group's own values, so the round trip is exact.
        for col, val in zip(_PARTITION_COLS, values):
            prior[col] = val
        extra = sorted(set(prior.columns) - set(SILVER_COLUMNS))
        missing = sorted(set(SILVER_COLUMNS) - set(prior.columns))
        if extra or missing:
            raise ValueError(
                f"canonical object s3://{bucket}/{key} does not carry the contract shape "
                f"(missing={missing}, extra={extra}) -- refusing to merge against it"
            )
        prior_rows_by_partition[tuple(rendered)] = len(prior)
        priors.append(prior[SILVER_COLUMNS])
    if not priors:
        logger.info("merge: %d partition(s) touched, none exists canonically yet -- nothing to "
                    "merge", partitions)
        return df, {**empty_rec, "partitions": partitions, "rows_out": int(len(df))}

    # NEW rows LAST so keep='last' resolves a natural-key collision in favour of this run (a
    # corrected settlement, a preliminary->final revision).
    merged = pd.concat(priors + [df[SILVER_COLUMNS]], ignore_index=True)
    ck = merged["contract_month"].astype("object").where(merged["contract_month"].notna(), "\x00")
    merged = merged.assign(_ck=ck).drop_duplicates(
        subset=["leviathan_slug", "_ck", "trade_date"], keep="last").drop(columns=["_ck"])
    merged["trade_year"] = pd.to_numeric(merged["trade_year"], errors="coerce").astype("int64")
    merged = merged[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    # NO PARTITION MAY SHRINK. This is the whole point of the merge, asserted rather than assumed.
    after = merged.groupby(_PARTITION_COLS, dropna=False).size()
    for values, prior_n in prior_rows_by_partition.items():
        got = 0
        for idx, n in after.items():
            idx = idx if isinstance(idx, tuple) else (idx,)
            if tuple(partition_value_str(c, v, types.get(c))
                     for c, v in zip(_PARTITION_COLS, idx)) == values:
                got = int(n)
                break
        if got < prior_n:
            raise ValueError(
                f"partition {dict(zip(_PARTITION_COLS, values))} would shrink from {prior_n} to "
                f"{got} rows -- the merge lost history; refusing to publish"
            )
    rec = {"partitions": partitions, "partitions_merged": len(priors),
           "prior_rows": int(sum(prior_rows_by_partition.values())),
           "rows_in": int(len(df)), "rows_out": int(len(merged))}
    logger.info("merge: %s", json.dumps(rec, sort_keys=True))
    return merged, rec


def publish(df: pd.DataFrame, contract: dict, auth, s3_client, glue_client, *,
            run_id: Optional[str] = None, shadow_prefix: Optional[str] = None,
            job: str = _JOB):
    """Stage + run the registered-partition publish. ``row_validator`` is NOT optional here.

    ``job`` is a manifest FIELD and never part of an object key, so a per-source label
    (``futures_eod_czce``, ...) buys auditability for free and changes no address."""
    plan = build_partitioned_publish(
        df=df,
        contract=contract,
        auth=auth,
        job=job,
        partition_cols=_PARTITION_COLS,
        s3_client=s3_client,
        glue_client=glue_client,
        run_id=run_id,
        shadow_prefix=shadow_prefix,
        # MANDATORY for every silver_futures_eod producer -- the conditional invariants the F010
        # contract cannot express. Runs before a single byte is staged.
        row_validator=FC.lint_frame,
    )
    logger.info("staged %d partition(s), %d row(s) for %s",
                plan.partition_count, plan.row_count, contract["table_name"])
    return plan.run()


def _settlement_tape_thin_exception(exc: BaseException) -> bool:
    """The ONE except-path shape the nightly's settlement-tape unit may swallow (V2-4 m10, narrowed
    by STEP-12 F3): the statistics payload is ABSENT under the raw prefix -- the fetch side landed
    nothing because its 200-byte floor refused an empty DBN or the vendor job returned no file --
    and :func:`load_unit_bronze` raises ``FileNotFoundError`` naming the key. (The other thin
    shape, a landed-but-thin tape, is a FRAME, not an exception: it takes the truncation-verdict
    branch and its partial rows are KEPT.) Every other exception -- a bad row, a decode error, a
    transient S3 fault -- is a blocking FAILED: a skip there is the silent-hole class the review
    named."""
    return isinstance(exc, FileNotFoundError)


def _unit_root(label: str) -> Optional[str]:
    """The vendor root out of a databento unit label (``'GLBX.MDP3 CPO/2026'`` -> ``'CPO'``);
    None for any other leg's label."""
    try:
        _ds, tail = label.split(" ", 1)
        root, _year = tail.split("/", 1)
    except ValueError:
        return None
    return root if root in ROOT_MAP else None


def _incremental_unit_landed(s3_client, bucket: str, dataset: str, root: str, year: int) -> bool:
    """Has an ``ohlcv-1d`` payload (``statistics``, for a settlement-tape root -- the only schema it
    buys) actually landed under this ``(root, year)`` raw prefix?

    Asked ONLY of the year the January straddle ADDS. The fetch leg keys the whole incremental
    window under ``year(--since)`` (jobs/ingest/fetch_databento_eod.py, incremental branch: the
    unit list is built from ``since.year``), so in the first days of January the new year's raw
    prefix is legitimately empty -- and selecting it anyway raises FileNotFoundError in the loader,
    which is a NEW full-family red inside exactly the window the straddle fix exists to keep green.
    ``s3_client`` is None only where there is nothing to list (unit tests), and there the unit is
    shown rather than hidden."""
    if s3_client is None:
        return True
    token = databento_payload_prefix("statistics" if root in SETTLEMENT_TAPE_ROOTS else "ohlcv-1d",
                                     root)
    prefix = raw_databento_key(DATASET_SLUGS[dataset], root, year, "")
    return any(key.rsplit("/", 1)[-1].startswith(token) and key.endswith(".dbn.zst")
               for key in _list_keys(s3_client, bucket, prefix))


def select_units(args, s3_client, bucket: str, spec: SourceSpec
                 ) -> list[tuple[str, object, Optional[str]]]:
    """``[(label, loader, dataset)]`` for one leg -- ``loader()`` returns ``(bronze_frame, stats)``.

    ``dataset`` is the databento dataset code the unit came from (D-PR-16: it selects the unit's
    expected publication lag) and is None for every leg that has only one publication calendar.

    The ONLY per-source step on the read side. Everything after the loop (assembly, the two
    uniqueness assertions, the row floor, the merge, the publish) is shared."""
    if spec.name == "databento":
        roots = args.roots or sorted(ROOT_MAP)
        now_year = datetime.now(tz=timezone.utc).year
        # D-PR-45 / D-SG G1-7 (JANUARY STRADDLE). A Databento unit is one (root, CALENDAR YEAR)
        # payload and --since defaults to today-5d, so from Jan 1 to Jan 5 the window spans TWO
        # years. Taking only year(--since) cannot see a session the vendor filed under the new
        # year; taking only the current year drops the December tail. Both, always: root_years()
        # below already discards a year a root cannot have, and on 360 days of the year the set
        # collapses to one element, so a non-straddling window resolves to exactly the same units
        # it does today.
        since_year = None
        if args.mode == "incremental":
            since_year = datetime.strptime(args.since, "%Y-%m-%d").year
            end_year = (datetime.now(tz=timezone.utc).date() - timedelta(days=1)).year
            years = sorted({since_year, end_year})
        else:
            years = args.years
        units = []
        for root in roots:
            usable = root_years(root, now_year)
            for year in (years if years else usable):
                if int(year) not in usable:
                    continue
                dataset = ROOT_MAP[root][0]
                if (since_year is not None and int(year) != since_year
                        and not _incremental_unit_landed(s3_client, bucket, dataset, root,
                                                         int(year))):
                    logger.info("skip %s %s/%s: the straddle year holds no landed payload -- the "
                                "fetch leg keys this window under year(--since)=%s",
                                dataset, root, year, since_year)
                    continue
                units.append((dataset, root, int(year)))

        def _bind(dataset, root, year):
            return lambda: load_unit_bronze(s3_client, bucket, dataset=dataset, root=root,
                                            year=year, ice_bar_rule=args.ice_bar_rule,
                                            mode=args.mode)

        return [(f"{dataset} {root}/{year}", _bind(dataset, root, year), dataset)
                for dataset, root, year in sorted(units)]

    if spec.name == "czce":
        # The nightly walks the lookback window; a backfill walks whatever has landed (optionally
        # bounded by --since / --year). Sessions come from the LANDED raw prefix, never a calendar.
        keys = czce_units(s3_client, bucket, since=args.since, years=args.years)

        def _bind_key(key):
            return lambda: load_czce_session(s3_client, bucket, key)

        return [(_czce_key_date(key) or key, _bind_key(key), None) for key in keys]

    # The three remaining free legs are all "one landed object == one unit", differing only in
    # which key reader enumerates them and which loader parses them. Keeping them in one table
    # rather than three near-identical branches is the point of the dispatch.
    readers = {
        "jse": (lambda: jse_units(s3_client, bucket, since=args.since, years=args.years),
                load_jse_capture,
                lambda k: _iso_from_segment(_key_segment(k, "as_of_date")) or k),
        # CEPEA is bounded by INDICATOR, not by year: the two ids are the vendor's identity and the
        # archive one-shot has no date in its key at all.
        "cepea": (lambda: cepea_units(s3_client, bucket, since=args.since),
                  load_cepea_capture,
                  lambda k: ("history " if "/history/" in k else "")
                  + f"id={_key_segment(k, 'indicator')} "
                  + (_iso_from_segment(_key_segment(k, "as_of_date")) or "series")),
        "miax": (lambda: miax_units(s3_client, bucket, since=args.since, years=args.years),
                 load_miax_session,
                 lambda k: _iso_from_segment(_key_segment(k, "trade_date")) or k),
        # W1c. DCE is bounded by VARIETY (the letter is the vendor identity and the history
        # workbooks have no date in their key at all) -- the CEPEA shape, for the same reasons.
        "dce": (lambda: dce_units(s3_client, bucket, since=args.since),
                load_dce_capture,
                lambda k: ("history " if "/history/" in k else "")
                + f"variety={_key_segment(k, 'variety')} "
                + (_iso_from_segment(_key_segment(k, "as_of_date"))
                   or f"year={_key_segment(k, 'year')}")),
        "euronext": (lambda: euronext_units(s3_client, bucket, since=args.since),
                     load_euronext_capture,
                     lambda k: f"{_key_segment(k, 'product')} "
                     + (_iso_from_segment(_key_segment(k, "as_of_date")) or k)),
        "bursa": (lambda: bursa_units(s3_client, bucket, since=args.since),
                  load_bursa_capture,
                  lambda k: f"{_key_segment(k, 'code')} "
                  + (_iso_from_segment(_key_segment(k, "as_of_date")) or k)),
    }
    if spec.name in readers:
        enumerate_keys, loader, label_of = readers[spec.name]

        def _bind_obj(key):
            return lambda: loader(s3_client, bucket, key)

        return [(label_of(key), _bind_obj(key), None) for key in enumerate_keys()]

    raise NotImplementedError(
        f"--source {spec.name} has no unit reader yet. Still needed: {spec.todo}")


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="raw -> silver_futures_eod (W2 Databento + W1a free)")
    ap.add_argument("--source", default="databento", choices=sorted(_SOURCE_SPECS),
                    help="which publication leg to run. The default keeps every W2 invocation "
                         "unchanged")
    ap.add_argument("--row-floor", default="enforce", choices=["enforce", "report"],
                    dest="row_floor",
                    help="plan gate 5, the per-source per-day SILVER row floor. 'report' logs the "
                         "violations and continues -- that is probe P10, which derives the venue "
                         "holiday calendars empirically from a backfill BEFORE the gate is armed")
    ap.add_argument("--continuity", default="enforce", choices=["enforce", "report"],
                    dest="continuity",
                    help="V2-4 M2, the month-continuity gate on a databento BACKFILL assembly. "
                         "'report' logs the MONTH_CONTINUITY holes and continues -- the lawful "
                         "way to publish a shipped-root REPAIR backfill over a real vendor-outage "
                         "month (the 15 roots' continuity has never been measured). The default "
                         "stays enforce, which is what a settlement-tape backfill runs under")
    ap.add_argument("--mode", choices=["backfill", "incremental"], default="backfill")
    ap.add_argument("--root", action="append", dest="roots", default=None, choices=sorted(ROOT_MAP))
    ap.add_argument("--year", action="append", type=int, dest="years", default=None)
    ap.add_argument("--since", default=None, help="incremental: inclusive first trade date")
    ap.add_argument("--lookback-days", type=int, default=5,
                    help="incremental, used when --since is absent: keep the last N calendar days. "
                         "The scheduler substitutes only <aws.scheduler.*> attributes, so the "
                         "scheduled chain passes this rather than a templated date")
    ap.add_argument("--ice-bar-rule", default=ICE_BAR_RULE,
                    help="F2 double-bar rule (see transforms.raw_to_bronze.databento_eod)")
    ap.add_argument("--no-merge", action="store_true",
                    help="incremental only, REPAIR USE ONLY: stage the incremental window WITHOUT "
                         "unioning it with the existing canonical partitions. The staged object "
                         "REPLACES the whole (leviathan_slug, trade_year) partition, so this "
                         "truncates the current year to the lookback window. Never in the chain")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--shadow-prefix", default=None)
    ap.add_argument("--publish-mode", default="dry-run",
                    choices=["dry-run", "shadow", "canonical"], dest="publish_mode")
    ap.add_argument("--role-arn", default="", dest="role_arn")
    ap.add_argument("--account-id", default="", dest="account_id")
    args = ap.parse_args(argv)
    spec = source_spec(args.source)

    # Dependency preflight, ahead of every AWS call, and SOURCE-CONDITIONAL: the databento package
    # is Databento's requirement, and a CZCE run must not fail on a vendor library it never calls.
    # (The transform MODULES are pure pandas and import fine without any vendor package, which is
    # why they can stay at module scope.) The yfinance ImportError silently wrote nothing for six
    # weeks with no freshness alarm; this guard is that lesson, applied per leg.
    if not preflight(spec):
        return 1
    if not spec.implemented:
        logger.error("--source %s is declared but not implemented. Still needed: %s",
                     spec.name, spec.todo)
        return 1

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)

    if args.mode == "incremental" and not args.since:
        args.since = (datetime.now(tz=timezone.utc).date()
                      - timedelta(days=max(1, args.lookback_days))).isoformat()

    account_id, role_arn = args.account_id, args.role_arn
    if args.publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_for_contract(contract, publish_mode=args.publish_mode,
                                  role_arn=role_arn, account_id=account_id, env=os.environ)
    logger.info("publish authorized: mode=%s may_canonical=%s",
                auth.mode.value, auth.may_mutate_canonical)

    s3 = get_thread_local_s3_client(aws_region)
    publish_s3 = None if args.publish_mode == "dry-run" else s3
    glue = None
    if args.publish_mode == "canonical":
        import boto3
        glue = boto3.client("glue", region_name=aws_region)

    units = select_units(args, s3, bucket, spec)
    if not units:
        logger.error("no %s unit(s) selected for --source %s", spec.unit_label, spec.name)
        return 1

    frames: list[pd.DataFrame] = []
    failures = 0
    thin = 0
    thin_units: list[str] = []
    for label, loader, unit_dataset in units:
        # V2-4 m10 -- a SETTLEMENT-TAPE unit is NON-BLOCKING in the nightly: its mark tape can miss
        # a session (CME publishes marks web-only on months without OI) and the fetch side already
        # skips a thin payload, so the silver side must not turn that into a family-wide red either
        # (a truncation verdict or a missing statistics payload here would exit 1 after publishing
        # and the promote task would never run for the other 15 roots). Backfill units stay
        # BLOCKING: an operator-driven backfill with an empty year is a stop (K7), not a skip.
        #
        # STEP-12 F3 -- non-blocking is NOT 'drop the unit'. The nightly's window is 5 days and
        # merge_with_canonical unions only what THIS run holds, so a fire that dropped its partial
        # CPO frame left every session that sat only inside skipped windows PERMANENTLY absent
        # from canonical, silently (the shipped cadence loses a present Wednesday after a Mon+Tue
        # absence in three exit-0 fires). So: (1) a THIN verdict KEEPS the partial frame -- the
        # merge is a union, new-wins, so partial rows can never shrink canonical and every session
        # the tape delivered lands; (2) the except-path swallow is narrowed to the m10 shape (no
        # statistics payload under the raw prefix -> FileNotFoundError); anything else stays a
        # blocking FAILED; (3) the thin count and the unit ids are stamped machine-readably
        # (settlement_tape_thin=1 in the unit stats line, SETTLEMENT_TAPE_SKIPS {json} after the
        # loop) so an alarm or the census can count N consecutive thins.
        nonblocking = (args.mode == "incremental" and spec.name == "databento"
                       and _unit_root(label) in SETTLEMENT_TAPE_ROOTS)
        try:
            bronze, stats = loader()
            trunc = _truncation_error(bronze, spec, mode=args.mode, since=args.since,
                                      dataset=unit_dataset)
            if trunc:
                if nonblocking:
                    thin += 1
                    thin_units.append(label)
                    stats = dict(stats, settlement_tape_thin=1, settlement_tape_thin_reason=trunc,
                                 rows_kept=int(len(bronze)))
                    logger.error("SETTLEMENT_TAPE_THIN %s: %s -- non-blocking (the PARTIAL frame "
                                 "of %d row(s) is KEPT: the merge is a union, new-wins, so every "
                                 "session the tape delivered lands and canonical can never "
                                 "shrink; the family publishes with it)",
                                 label, trunc, len(bronze))
                    logger.info("unit %s: %s", label, json.dumps(
                        {k: v for k, v in stats.items() if k != "ice_dedupe"}, sort_keys=True))
                    if len(bronze):
                        frames.append(bronze)
                    continue
                logger.error("%s: %s", label, trunc)
                failures += 1
                continue
            logger.info("unit %s: %s", label, json.dumps(
                {k: v for k, v in stats.items() if k != "ice_dedupe"}, sort_keys=True))
            frames.append(bronze)
        except Exception as exc:  # noqa: BLE001 -- one unit's failure must not abort the rest
            if nonblocking and _settlement_tape_thin_exception(exc):
                thin += 1
                thin_units.append(label)
                logger.exception("SETTLEMENT_TAPE_THIN %s %s -- non-blocking (%s: no statistics "
                                 "payload landed for this fire; the unit is skipped and the "
                                 "family publishes without it)",
                                 spec.unit_label, label, type(exc).__name__)
                continue
            logger.exception("FAILED %s %s", spec.unit_label, label)
            failures += 1
    if thin:
        logger.warning("%d settlement-tape unit(s) thin this fire (partial rows kept / missing "
                       "payload skipped)", thin)
        # The machine-readable stamp: ONE JSON record a metric filter or the census can count.
        logger.info("SETTLEMENT_TAPE_SKIPS %s", json.dumps(
            {"settlement_tape_thin": thin, "settlement_tape_thin_units": thin_units},
            sort_keys=True))

    if not frames:
        logger.error("no bronze frames produced from %d %s(s)", len(units), spec.unit_label)
        return 1
    df = build_silver(frames, source=spec.name)
    if args.mode == "incremental" and args.since:
        df = df[df["trade_date"] >= pd.Timestamp(args.since)].reset_index(drop=True)
    if df.empty:
        logger.error("silver frame is EMPTY after assembly")
        return 1

    # The F2 precondition, enforced on the automated path rather than in a script nobody calls.
    assert_no_duplicates(df)

    # V2-4 M2 -- MONTH CONTINUITY on a backfill assembly: every calendar month inside a slug's
    # banked span (per run of consecutive years) must carry >= 1 trade date. An internal hole is
    # exactly what PRICE_COVERAGE_START cannot express -- covers() routes a window inside it to the
    # table, which then declines no_tape_rows instead of naming the floor -- so a hole FAILS the
    # run before a byte is staged, naming the missing months. Incremental runs carry a 5-day window
    # and are not a continuity claim. ``--continuity report`` (STEP-12 F8) mirrors ``--row-floor
    # report``: the holes are logged and the run continues -- a shipped-root REPAIR backfill over
    # a real vendor-outage month must have a lawful way to publish the correct bytes.
    if args.mode == "backfill" and spec.name == "databento":
        holes = month_continuity_holes(df)
        if holes:
            for slug, months in sorted(holes.items()):
                logger.error("MONTH_CONTINUITY %s: %d calendar month(s) inside the banked span "
                             "carry NO trade date: %s", slug, len(months), ", ".join(months))
            if args.continuity == "enforce":
                return 1
            logger.warning("--continuity report: continuing anyway (%d slug(s) carry holes -- a "
                           "shipped-root repair backfill over a real vendor-outage month; the "
                           "holes above are RECORDED, not fenced, and the gate harness's gate 9 "
                           "names them again)", len(holes))

    # PLAN GATE 5, on the rows THIS RUN produced -- before the merge, so a thin session is caught
    # rather than hidden inside a year of merged history.
    violations = assert_row_floor(df, spec, mode=args.mode)
    if violations:
        logger.error("row floor (%s, %s %d/day): %d violating day(s): %s", spec.name,
                     "==" if spec.rows_per_day_exact else ">=", spec.rows_per_day,
                     len(violations), "; ".join(violations[:20]))
        if args.row_floor == "enforce":
            return 1
        logger.warning("--row-floor report: continuing anyway (probe P10 -- derive the venue "
                       "holiday calendar from these days before arming the gate)")

    if args.mode == "incremental" and not args.no_merge:
        # An incremental run holds only --lookback-days of the current year but stages the WHOLE
        # (leviathan_slug, trade_year) partition, so it must first read back what it does not own.
        df, merge_rec = merge_with_canonical(df, contract, s3)
        assert_no_duplicates(df)
        logger.info("incremental merge: %s", json.dumps(merge_rec, sort_keys=True))

    manifest = publish(df, contract, auth, publish_s3, glue, job=spec.job,
                       run_id=args.run_id, shadow_prefix=args.shadow_prefix)
    logger.info("publish %s: source=%s state=%s rows=%d", auth.mode.value, spec.name,
                manifest.state.value, len(df))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
