"""AWS Batch Fargate task: bronze -> silver (registered/compact) for USDA ESR data.

Reads bronze ESR parquet under ``bronze/production/source=usda_esr/`` and writes the
``silver_esr_compact`` serving table under ``silver/esr/`` THROUGH the F015 shadow publisher
(shadow-first, atomic) + the F013 registered-partition publisher (exact / repairable). This is the
SILVER-F031 (option-b vintage path) + SILVER-F032 (registered-partition publication fail-safe)
producer.

Vintage mode (SILVER-F031)
--------------------------
``--vintage-mode latest`` (DEFAULT -- today's behaviour): keep the file with the latest ``as_of=``
per (commodity_code, market_year), merge to ONE file per commodity slug at
``silver/esr/commodity={slug}/part-000.parquet``; the compact table stays partitioned by
``commodity`` only. ``vintage_retention=latest-only``.

``--vintage-mode all`` (option-b, execution gated to BF-W2): retain EVERY ``as_of`` vintage. The
``_latest_snapshot_keys`` collapse is bypassed; the compact layout gains an ``as_of_date``
REGISTERED partition dimension -- one object per (commodity slug, as_of) at
``silver/esr/commodity={slug}/as_of={date}/part-000.parquet`` (NEVER re-projection, INV-3). This is
the per-week vintage surface that unblocks the pace/forward-commitment features (FR-002).

Publication safety (SILVER-F032 + the R0/F004 kill switch)
----------------------------------------------------------
``--publish-mode`` defaults to ``dry-run`` (plan only; nothing written, catalog untouched).
``shadow`` writes validated objects to a non-canonical shadow prefix. ``canonical`` is refused
without a signed post-R4 approval (publish_guard). The registered strategy delegates to the F013
PartitionPublisher: a new partition is validated-then-registered; an existing partition at a WRONG
location is never silently accepted; a registration failure fails the run (no false success marker),
and an identical rerun is an idempotent no-op. Bronze->silver ordering is asserted before any write
so the ``esr_weekly_ingest`` sibling-task race cannot silver-write ahead of bronze.

Memory envelope (SILVER-F030 BF-W2 widen, measured 2026-09-04)
--------------------------------------------------------------
``--vintage-mode all`` holds every per-file frame AND the ``pd.concat`` copy, then a parquet body
per staged object. This jobdef OOM-killed at 4 GB on the 2026-09-03 fire and was bumped to
12,288 MiB (``leviathan-dev-esr-bronze-to-silver`` rev 8, ``leviathan-dev-silver-publisher-runner``
rev 36 -- BOTH 2 vCPU / 12,288 MiB, verified live). Adding the five float64 columns makes the frame
13 -> 18 columns and **306.35 -> 346.35 bytes/row deep (+40.00 B/row, +13.1%)**, measured on 80
real bronze objects through both the HEAD and the widened transform. Over the whole bronze layer
(143,332,722 parquet bytes at 0.09711 rows/byte, ~13.92M rows) that is one copy 3.97 -> 4.49 GiB
and a two-copy concat peak 7.94 -> 8.98 GiB against a 12.0 GiB envelope: 66.2% -> 74.8%. It fits at
12,288 MiB and OOMs immediately at 4,096, so ANY re-registration of these two jobdefs must PRESERVE
the envelope -- copy the live revision with ``scripts/ops/repin_jobdef_digest.py``, never rebuild a
descriptor from constants (``jobs/submit/submit_batch_b2s_esr.py`` hardcodes ``MEMORY: "4096"``).
Read the shadow run's peak before the canonical promote; the shadow does the identical concat.

Reading ``partition_actions``
-----------------------------
The terminal line reports the OUTCOME SET, not a count against a denominator, and
``PartitionPublisher`` only walks the partitions THIS RUN STAGES (specs are built from ``objects``,
which come from bronze). A registered partition with no surviving bronze source is never repaired
and keeps its old StorageDescriptor, so after a widening ALTER Athena will not expose the new
columns there. Compare repaired+created against ``aws glue get-partitions --database-name
leviathan_dev --table-name silver_esr_compact --query 'length(Partitions)'``; any shortfall is an
orphan partition to reconcile deliberately, named one by one.

Per-vintage frame streaming (LEVIATHAN_ESR_VINTAGE_STREAM -- DARK, default off)
------------------------------------------------------------------------------
MEASURED TRIGGER, never a projection. ``--vintage-mode all`` holds three simultaneous residents:
``frames`` (one silver DataFrame per bronze object -- all 8,920 of them), the ``pd.concat`` copy,
and the staged bodies. The estate paid for it twice with exit 137 ("container killed due to memory
usage"): 2026-09-03T14:05:43Z on ``leviathan-dev-esr-bronze-to-silver:7`` (2 vCPU / 4,096 MiB) and
2026-09-04T08:46:27Z on ``leviathan-dev-silver-publisher-runner:35`` (1 vCPU / 4,096 MiB). At the
post-OOM 12,288 MiB the concat peak is 8.98 GiB = 74.8 % of the envelope TODAY. Weekly bronze
growth, measured off the last four vintages (21,592,636 B -> 2,096,860 rows -> 1.353 GiB of concat
peak per week), puts the **2026-09-17 fire at 97.4 %** -- inside the band that killed 09-03 -- and
the **2026-09-24 fire at 108.6 %: the one the arithmetic says cannot complete.**

THE MECHANISM (design revision 2 section 2.1): stream the FRAMES, accumulate the OBJECTS, publish
ONCE. The measurement that decides it: all 214 canonical bodies together are 64,433,701 B = 61.4
MiB = 0.50 % of the envelope, against frames of 8.98 GiB -- 150x. So there is no reason to stream
the publish at all, and ``src/leviathan/silver/publisher.py`` is NOT TOUCHED: ``run()`` still
receives all 214 objects, ``PartitionPublisher._repair`` still walks all 214 partitions, the
post-ALTER descriptor self-heal (``sql/athena/migrations/silver/silver_esr_f030_additive.sql``
:196-198) survives intact, and there is still exactly ONE manifest at the unchanged constant key
``silver/esr/_manifests/silver_esr_compact-all.json`` that ``scripts/ops/esr_netcommitment_runbook.py``
:156 hardcodes. Peak becomes the LARGEST SINGLE VINTAGE's frame (1.353 GiB) + the accumulated
bodies (61.4 MiB) = 1.41 GiB = 11.8 %, and the frame term is constant in history depth.

THE FENCE. The flag is INERT unless ``--vintage-mode all``. Under ``latest`` the selected keys span
many as_of vintages while ``build_staged_objects`` emits ONE object per slug, so a per-vintage loop
would mint the SAME canonical key in several vintages and the last promote would silently win --
row loss with no error. The producer logs that and falls back to the whole-set path rather than
streaming it. ``assert_bronze_ready`` stays at the top, on the FULL listing (design R4): a
per-vintage re-check would weaken the F032 guard to "this vintage has bronze", which is exactly the
``esr_weekly_ingest`` sibling-task race the guard exists to stop. The loop derives its work from the
BRONZE listing only and never LISTs ``silver/esr/`` (R7: the shadow prefix lives INSIDE the
canonical root and would double-count every partition).

THE ORDER FIX RIDES THE FLAG -- a deliberate choice between design 2.7's two shapes. HEAD collects
frames in ``as_completed`` order, so the row order inside every object is S3 download-COMPLETION
order. MEASURED on all 214 canonical objects: **89 (41.6 %) are not in ascending market_year block
order** (0 of 214 interleaved), and 18 of the 31 sibling slug pairs of 2026-09-03/04 hold identical
rows in a different order -- one process, one run, two orders. Collecting in SUBMIT order turns that
accident into a guarantee, and it REWRITES 89 of 214 parquet bodies. Applying it unconditionally
would make ``LEVIATHAN_ESR_VINTAGE_STREAM=off`` differ from HEAD on 89 objects, and the estate's own
convention for a dark producer lever is the opposite (``jobs/batch/futures_eod_task.py`` :459-461:
"LEVIATHAN_VENUE_CALENDAR=off has to restore the pre-Lane-A arithmetic BYTE FOR BYTE, not nearly.").
So submit-order collection is applied ONLY on the flag-on path -- flag OFF runs HEAD's algorithm
character for character, and the flag-off byte-identity pin is TRUE today with HEAD as its anchor.
Un-gating it (design sequencing step 2, post-S7) is one expression: ``submit_order=stream`` in
``build_objects``.

ARMING NOTE -- THE TWO ARMS DIVERGE IN FAILURE MODE, NOT ONLY IN MEMORY. Read this before the
armed shadow fire, not after it. Where a bronze key's ``as_of=`` segment disagrees with its own
frame's ``as_of_date`` column, flag OFF (HEAD) silently MERGES the duplicated rows into ONE object
and publishes it; flag ON raises ``VintageCollisionError`` and the whole fire fails. That is the
designed fail-closed behaviour -- silent row loss is the one failure this loop can cause that HEAD
cannot -- but arming the flag can therefore convert a SILENT DATA CONDITION into a HARD WEEKLY-FIRE
FAILURE. Both arms are pinned against the same mis-filed fixture in
``tests/unit/silver/test_esr_vintage_stream.py::TestFences``. No such disagreement is known on the
live surface today; the point of the note is that discovering one at the fire is the expensive way.

DELIBERATELY NOT COVERED. (a) The whole-history re-stage: all 214 objects are still re-staged,
re-hashed, re-written to shadow and re-promoted on every fire (88.2 % by byte / 85.5 % by object
unchanged) -- that rewrite IS the descriptor self-heal, and dropping it needs the catalog sweep
built first. (b) Partial-run atomicity: a kill mid-loop promotes nothing, exactly as today --
unchanged, not improved. (c) The jobdef envelope: 12,288 MiB stays, because the flag-off path must
still fit. (d) The 8,474 backfill-derived bronze objects (~95 % of the frame) are assumed to stay.
(e) The raw->bronze truncation defect (design R10) is not touched here.

Peak-memory instrument (ALWAYS ON, one log line, changes no output)
-------------------------------------------------------------------
AWS Batch on Fargate publishes NO memory metric, which is why the only memory evidence this estate
has is two exit-137s. At exit the producer logs ``resource.getrusage(RUSAGE_SELF).ru_maxrss``
(KiB on Linux) and the maximum of ``/sys/fs/cgroup/memory.peak`` (cgroup v2), falling back to
``/sys/fs/cgroup/memory/memory.max_usage_in_bytes`` (v1), sampled every 5 s by a daemon thread.
In-process, no Container Insights, costs nothing, and BOTH arms are measured on the same
instrument. It writes no S3 object and touches no manifest field.

Usage (all gated):
    python jobs/batch/bronze_to_silver_esr_task.py                      # dry-run, latest
    python jobs/batch/bronze_to_silver_esr_task.py --vintage-mode all   # dry-run, per-week plan
    python jobs/batch/bronze_to_silver_esr_task.py --publish-mode shadow --shadow-prefix silver/_shadow/esr
    LEVIATHAN_ESR_VINTAGE_STREAM=on python jobs/batch/bronze_to_silver_esr_task.py --vintage-mode all
"""
from __future__ import annotations

import argparse
import atexit
import io
import logging
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import pyarrow.parquet as pq

try:  # POSIX only -- absent on Windows, where the instrument degrades to the cgroup half (also absent).
    import resource as _resource
except ImportError:  # pragma: no cover -- the Fargate image is Linux; this is the dev-laptop path.
    _resource = None

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

logger = get_logger("bronze_to_silver_esr")

_BRONZE_PREFIX = "bronze/production/source=usda_esr/"
_SILVER_ESR_PREFIX = "silver/esr"
_DATABASE = "leviathan_dev"
_TABLE = "silver_esr_compact"
_WORKERS = 32

VINTAGE_LATEST = "latest"
VINTAGE_ALL = "all"

# --- LEVIATHAN_ESR_VINTAGE_STREAM (DARK, default off) -------------------------------------------
# Armed ONLY by adding it to "env" on the silver phase of configs/silver/dags/esr_weekly.json
# (today "env": {}) or by --container-overrides on a hand-submitted job. NO jobdef re-registration,
# so the 12,288 MiB envelope that two lane-C artifacts require preserved is never at risk from
# arming or disarming this.
_STREAM_ENV = "LEVIATHAN_ESR_VINTAGE_STREAM"
_ON_VALUES = frozenset({"on", "1", "true", "yes"})

# The silver frame's EMITTED column list, mirroring the transform's own final order
# (src/leviathan/transforms/bronze_to_silver/usda_esr.py: base + quantity + meta + the BF-W2 five
# at the TAIL). It is the streaming loop's reindex target and it closes design m9's latent risk:
# the four incumbent *_1000mt columns are emitted CONDITIONALLY (`if col in df.columns`, :354-358)
# while the BF-W2 five are unconditional (:365-369), so if a future vintage's bronze ever dropped
# `changes`, a whole-history concat and a per-vintage concat would resolve that column's union
# POSITION and dtype differently and the byte pin would fail for a reason unrelated to streaming.
# Measured today the risk is nil -- a stratified bronze sample across all 13 vintages returns
# exactly ONE schema (11 columns, `changes` present in every one) and all 214 canonical objects
# return exactly ONE schema -- so the reindex is a NO-OP on today's surface.
# tests/unit/silver/test_esr_vintage_stream.py pins this list EQUAL to what the real transform
# emits, so it cannot drift from the transform silently.
EMITTED_COLUMNS: tuple[str, ...] = (
    "commodity_code",
    "commodity_name",
    "market_year",
    "country_code",
    "week_ending_date",
    "outstanding_sales_1000mt",
    "weekly_exports_1000mt",
    "gross_new_sales_1000mt",
    "changes_1000mt",
    "source_unit_id",
    "as_of_date",
    "ingest_date",
    "source",
    "accumulated_exports_1000mt",
    "current_my_net_sales_1000mt",
    "current_my_total_commitment_1000mt",
    "next_my_outstanding_sales_1000mt",
    "next_my_net_sales_1000mt",
)

# Peak-memory instrument (always on; see the module docstring).
_PEAK_SAMPLE_SECONDS = 5.0
_CGROUP_PEAK_FILES = (
    "/sys/fs/cgroup/memory.peak",                       # cgroup v2 (Fargate platform 1.4+)
    "/sys/fs/cgroup/memory/memory.max_usage_in_bytes",  # cgroup v1 fallback
)

# The largest single frame (in ROWS) the last build_objects() call materialised. Observational
# only -- nothing branches on it. Flag OFF this is the whole-history row count; flag ON it is the
# largest single vintage, and the difference between those two numbers IS the change.
LAST_PEAK_FRAME_ROWS = 0

# Non-deprecated ESR measures reported into the run manifest as V001-style null metrics (observability;
# the real per-commodity floor is the SILVER-V001 census). changes_1000mt is DEPRECATED (SILVER-F030)
# and intentionally excluded from the producer's reported floor.
#
# The five BF-W2 net-commitment columns (2026-09-04) ARE listed -- this tuple is the ONLY per-
# (commodity, as_of) instrument that proves the promotion landed. _null_metrics reports
# notna().mean() per column per staged object and the publisher records it as
# row_key_null_metrics[<canonical key>] in the run manifest, so a shadow run answers "which slugs
# and which vintages actually carry the new fields" without a single Athena query.
#
# HOW TO READ IT, restated 2026-09-04 after the raw census (C-M3). The earlier reading -- "as_of >=
# 20260813 is non-zero and every earlier vintage is 0.0" -- could not fail: the 0.0 was guaranteed
# by the re-bronze SCOPE, not by the source. MEASURED over all 446 dated raw objects, every one of
# the 12 as_of vintages (20260712..20260904) carries all five keys, so there is no pre-publication
# vintage at all. The honest reading is therefore: every (commodity, as_of) object whose BRONZE was
# re-written reads NON-ZERO on all five, and a 0.0 is a PIPELINE finding (a bronze object the
# re-bronze did not reach -- e.g. one of the 8,474 backfill-derived bronze objects stamped with a
# run date before the vintage law landed), NEVER a statement about the source. Write any exception
# down PER COMMODITY; frequency floors deny the tail. Being in this tuple does NOT govern the five:
# ValidationHooks(min_nonnull_frac=0.0) below means an all-null new column can never block the
# publish, so the measurement cannot fail closed on itself.
_ESR_MEASURE_COLS = (
    "weekly_exports_1000mt",
    "outstanding_sales_1000mt",
    "gross_new_sales_1000mt",
    "accumulated_exports_1000mt",
    "current_my_net_sales_1000mt",
    "current_my_total_commitment_1000mt",
    "next_my_outstanding_sales_1000mt",
    "next_my_net_sales_1000mt",
)


class BronzeNotReadyError(RuntimeError):
    """Raised when silver would be written ahead of a complete bronze layer (F032 ordering guard)."""


class VintageCollisionError(RuntimeError):
    """Two per-vintage groups minted the SAME canonical key -- the streaming loop's fail-closed guard.

    The loop partitions work by the bronze KEY's ``as_of=`` segment while ``build_staged_objects``
    groups by the FRAME's ``as_of_date`` COLUMN. Design 2.1 asserts those agree ("a global
    (commodity_name, as_of_date) group is wholly contained in exactly one vintage"). If they ever
    disagree -- a bronze object filed under one as_of whose rows carry another, or an undated
    bronze key whose frame as_of collides with a dated vintage -- two StagedObjects would carry the
    same canonical key and the publisher's second copy_object would silently overwrite the first.
    Silent row loss is the one failure this loop can cause that HEAD cannot, so it is named and
    refused rather than counted.
    """


# ---------------------------------------------------------------------------
# The dark flag + the peak-memory instrument.
# ---------------------------------------------------------------------------
def vintage_stream_enabled(env=None) -> bool:
    """``LEVIATHAN_ESR_VINTAGE_STREAM=on`` arms per-vintage frame streaming. DEFAULT OFF.

    Default-off is the point: with the flag unset this producer runs HEAD's algorithm character for
    character -- same submit order, same ``as_completed`` collection, same single whole-history
    ``pd.concat``, same ``build_staged_objects`` call -- so ``off`` restores the pre-change bytes
    BYTE FOR BYTE, not nearly (the governing sentence at jobs/batch/futures_eod_task.py:459-461).
    """
    raw = (env if env is not None else os.environ).get(_STREAM_ENV, "")
    return str(raw).strip().lower() in _ON_VALUES


class PeakMemoryProbe:
    """Peak RSS + cgroup peak, sampled in-process. One log line at exit; changes no output.

    Batch/Fargate publishes no memory metric, so without this the only memory evidence the estate
    has is two exit-137s (2026-09-03 and 2026-09-04, both at 4,096 MiB). Deliberately dumb: a
    daemon thread, a 5 s interval, no dependency, and every read wrapped -- an instrument that can
    fail a run is worse than no instrument.
    """

    def __init__(self, interval: float = _PEAK_SAMPLE_SECONDS):
        self.interval = interval
        self.cgroup_peak_bytes = 0
        self.cgroup_source: str | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._reported = False

    @staticmethod
    def _read_cgroup_peak() -> tuple[int | None, str | None]:
        for path in _CGROUP_PEAK_FILES:
            try:
                with open(path, "r", encoding="ascii") as fh:
                    return int(fh.read().strip()), path
            except Exception:  # noqa: BLE001 -- absent/unreadable cgroup file is not a run failure
                continue
        return None, None

    def sample(self) -> None:
        value, path = self._read_cgroup_peak()
        self.samples += 1
        if value is not None and value > self.cgroup_peak_bytes:
            self.cgroup_peak_bytes, self.cgroup_source = value, path

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.sample()

    def start(self) -> "PeakMemoryProbe":
        self.sample()
        self._thread = threading.Thread(target=self._loop, name="esr-peak-mem", daemon=True)
        self._thread.start()
        atexit.register(self.report)
        return self

    def ru_maxrss_kib(self) -> int | None:
        """ru_maxrss is KiB on Linux (the Fargate image) and BYTES on macOS -- reported as read."""
        if _resource is None:
            return None
        try:
            return int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
        except Exception:  # noqa: BLE001
            return None

    def report(self) -> None:
        if self._reported:
            return
        self._reported = True
        self._stop.set()
        self.sample()
        rss_kib = self.ru_maxrss_kib()
        logger.info(
            "PEAK MEMORY  ru_maxrss=%s (KiB on Linux) = %s MiB  cgroup_peak=%s B = %s MiB  "
            "cgroup_source=%s  samples=%d  peak_frame_rows=%d  stream=%s",
            rss_kib,
            round(rss_kib / 1024.0, 1) if rss_kib else None,
            self.cgroup_peak_bytes or None,
            round(self.cgroup_peak_bytes / 1048576.0, 1) if self.cgroup_peak_bytes else None,
            self.cgroup_source,
            self.samples,
            LAST_PEAK_FRAME_ROWS,
            vintage_stream_enabled(),
        )


# ---------------------------------------------------------------------------
# Canonical object keys (compact serving layout).
# ---------------------------------------------------------------------------
def silver_esr_compact_key(commodity_slug: str) -> str:
    """latest-only layout: one file per commodity slug (partition key = commodity)."""
    return f"{_SILVER_ESR_PREFIX}/commodity={commodity_slug}/part-000.parquet"


def silver_esr_compact_vintage_key(commodity_slug: str, as_of_date: str) -> str:
    """option-b per-week layout: one file per (commodity slug, as_of) -- an as_of_date REGISTERED
    partition dimension (never re-projection, INV-3)."""
    return f"{_SILVER_ESR_PREFIX}/commodity={commodity_slug}/as_of={as_of_date}/part-000.parquet"


# ---------------------------------------------------------------------------
# Bronze key selection.
# ---------------------------------------------------------------------------
def _latest_snapshot_keys(all_keys: list[str]) -> list[str]:
    """Keep the file with the latest ``as_of=`` per (commodity_code, market_year) -- latest mode."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key in all_keys:
        code = parse_hive_key(key, "commodity_code")
        year = parse_hive_key(key, "market_year")
        if code and year:
            groups[(code, year)].append(key)
    latest: list[str] = []
    for group_keys in groups.values():
        latest.append(max(group_keys, key=lambda k: parse_hive_key(k, "as_of") or ""))
    return sorted(latest)


def _all_snapshot_keys(all_keys: list[str]) -> list[str]:
    """Retain EVERY as_of vintage (option-b): every parseable bronze key, no max() collapse."""
    return sorted(
        k for k in all_keys
        if parse_hive_key(k, "commodity_code") and parse_hive_key(k, "market_year")
    )


def _select_keys(all_keys: list[str], vintage_mode: str) -> list[str]:
    if vintage_mode == VINTAGE_ALL:
        return _all_snapshot_keys(all_keys)
    return _latest_snapshot_keys(all_keys)


def assert_bronze_ready(all_keys: list[str], keys_to_read: list[str]) -> None:
    """F032 ordering guard: never silver-write ahead of bronze. Raise if bronze is empty or if the
    selected key set is empty (the ``esr_weekly_ingest`` sibling-task race would otherwise let silver
    run before the raw->bronze promotion has landed the week)."""
    if not all_keys:
        raise BronzeNotReadyError(
            f"no bronze ESR objects under {_BRONZE_PREFIX} -- refusing to write silver ahead of "
            f"bronze (F032 ordering guard)."
        )
    if not keys_to_read:
        raise BronzeNotReadyError(
            "bronze exists but no (commodity_code, market_year) partitions parsed from it -- "
            "refusing to publish an empty silver set."
        )


# ---------------------------------------------------------------------------
# Read + transform + stage.
# ---------------------------------------------------------------------------
def _read_and_transform(key: str, bucket: str, aws_region: str) -> pd.DataFrame | None:
    market_year_str = parse_hive_key(key, "market_year")
    if not market_year_str:
        logger.warning("Could not parse market_year from: %s", key)
        return None
    try:
        market_year = int(market_year_str)
    except ValueError:
        logger.warning("Non-integer market_year in: %s", key)
        return None
    try:
        s3 = get_thread_local_s3_client(aws_region)
        data = s3_download_with_retry(bucket, key, s3)
        df = pq.read_table(io.BytesIO(data)).to_pandas()
        return transform_esr_bronze_to_silver(df, market_year)
    except Exception as exc:  # noqa: BLE001 -- per-file failures logged; loop continues
        logger.error("Failed to read/transform %s: %s", key, exc)
        return None


def _to_parquet_bytes(group: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    group.reset_index(drop=True).to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _null_metrics(group: pd.DataFrame) -> dict:
    out: dict[str, float] = {}
    n = len(group)
    if not n:
        return out
    for col in _ESR_MEASURE_COLS:
        if col in group.columns:
            out[col] = float(group[col].notna().mean())
    return out


def build_staged_objects(combined: pd.DataFrame, vintage_mode: str) -> list[StagedObject]:
    """Group the combined silver frame into the staged objects the publisher writes.

    latest -> one object per commodity slug, partition_values=[slug].
    all    -> one object per (commodity slug, as_of), partition_values=[slug, as_of]; the per-week
              vintages are NEVER collapsed to max(as_of)."""
    objects: list[StagedObject] = []
    if vintage_mode == VINTAGE_ALL:
        if "as_of_date" not in combined.columns:
            raise ValueError("option-b (all) mode requires an as_of_date column in the silver frame")
        for (name, as_of), group in combined.groupby(["commodity_name", "as_of_date"], sort=True):
            slug, asof = str(name), str(as_of)
            objects.append(StagedObject(
                canonical_key=silver_esr_compact_vintage_key(slug, asof),
                body=_to_parquet_bytes(group),
                partition_values=[slug, asof],
                row_count=len(group),
                null_metrics=_null_metrics(group),
            ))
    else:
        for name, group in combined.groupby("commodity_name", sort=True):
            slug = str(name)
            objects.append(StagedObject(
                canonical_key=silver_esr_compact_key(slug),
                body=_to_parquet_bytes(group),
                partition_values=[slug],
                row_count=len(group),
                null_metrics=_null_metrics(group),
            ))
    return objects


# ---------------------------------------------------------------------------
# Frame collection + the per-vintage streaming loop (design revision 2 section 2.1).
# ---------------------------------------------------------------------------
def _collect_frames(
    pool, keys: list[str], bucket: str, aws_region: str, *, submit_order: bool
) -> list[pd.DataFrame]:
    """Read+transform *keys* through the caller's 32-thread pool.

    The pool is passed IN rather than created here, and that is a measured choice, not tidiness:
    the streaming loop calls this once per as_of vintage (13 today), and a fresh pool per vintage
    would spawn 13 x 32 = 416 worker threads instead of 32, each one missing
    ``get_thread_local_s3_client``'s cache and paying a fresh boto3 client construction. That churn
    lands directly on measurement 6's duration budget (no more than +20 % on a 225 s shadow leg),
    for no benefit at all -- one pool serves every vintage.

    ``submit_order=False`` IS HEAD, transcribed: submit every key in ``keys`` order, then collect in
    ``as_completed`` order. The row order inside every staged object is therefore S3 download
    completion order -- measured, 89 of 214 canonical objects (41.6 %) sit in an order only thread
    timing explains.

    ``submit_order=True`` is design 2.7's move 1: same submits, results taken in KEY order. Because
    ``_all_snapshot_keys`` returns ``sorted(...)`` and ``market_year`` is a fixed-width 4-digit key
    segment, submit order IS ascending market_year within a slug. IT REWRITES 89 OF 214 BODIES --
    that is expected, it is the point, and it is why this rides the flag rather than landing
    unconditionally today (module docstring). Un-gating it later is the ``submit_order=`` argument
    at the two call sites below.
    """
    frames: list[pd.DataFrame] = []
    # A LIST of pairs, not a dict keyed by key: a duplicate key in *keys* must not collapse a
    # submission. (S3 listings do not repeat, so this is a guard, not a fix.)
    submitted = [(k, pool.submit(_read_and_transform, k, bucket, aws_region)) for k in keys]
    ordered = ([fut for _, fut in submitted] if submit_order
               else as_completed({fut: k for k, fut in submitted}))
    for fut in ordered:
        result = fut.result()
        if result is not None and not result.empty:
            frames.append(result)
    return frames


def _reindex_emitted(combined: pd.DataFrame) -> pd.DataFrame:
    """Pin one vintage's concat to the declared EMITTED_COLUMNS order (design 2.1's one line).

    A column the frame carries but the contract does not is REFUSED rather than dropped: silently
    discarding a column the transform started emitting is exactly the kind of loss this producer
    exists to prevent. A column the contract declares and this vintage lacks is materialised as
    NaN, which is what a whole-history ``pd.concat`` would do anyway as long as ANY vintage carries
    it.

    NOT COVERED -- TWO cases, both requiring a vintage whose bronze lacks an incumbent
    ``*_1000mt`` column, and the "pure memory change, zero data change" claim has an exception in
    each. MEASURED both ways on a three-vintage fixture, not projected:

      (a) NO vintage carries the column. The flag-on frame keeps the declared 18 columns while the
          flag-off concat emits 17. Deliberate -- the declared schema is the one the Glue table
          holds -- and it cannot happen without the bronze contract itself changing first.
      (b) SOME vintages carry it and some do not, which is the MORE REACHABLE of the two and is
          why it is written down. Column COUNT and ORDER agree (18 on both arms); the divergence
          is DTYPE. Flag OFF, the whole-history concat inherits ``float32`` from the vintages that
          do carry the column, and the deficient vintage's rows land in a parquet ``float``. Flag
          ON, that vintage is reindexed alone, pandas materialises the absent column at
          ``float64``, and its object lands as parquet ``double``. So the reindex closes design
          m9's union-POSITION risk and opens a dtype one in the same scenario.

    Neither is reachable on today's surface and (b) fails CLOSED if it ever becomes so.
    ``src/leviathan/transforms/raw_to_bronze/usda_esr.py::_ensure_nullable`` (:214-215) runs
    unconditionally over ``_NULLABLE_MEASURE_COLS``, which includes ``changes``, precisely so the
    silver schema does not depend on which vintage produced the frame -- so every object written by
    TODAY's raw->bronze carries all six. The residual exposure is the 8,474 objects (~95 % of the
    listing) written by OLDER backfill code, and the design's bronze sample across all 13 vintages
    was STRATIFIED, not exhaustive. If it ever happened, a retyped partition descriptor is REFUSED
    rather than published, and measurement 3's 214/214 sha256 comparison would name it before the
    flag could go default-on.
    """
    extra = [c for c in combined.columns if c not in EMITTED_COLUMNS]
    if extra:
        raise ValueError(
            f"silver frame carries column(s) not in EMITTED_COLUMNS: {extra}. Refusing to reindex: "
            "the reindex would DROP them silently. Update EMITTED_COLUMNS (and its pin in "
            "tests/unit/silver/test_esr_vintage_stream.py) alongside the transform."
        )
    return combined.reindex(columns=list(EMITTED_COLUMNS))


def _assert_no_vintage_collision(objects: list[StagedObject]) -> None:
    seen: dict[str, int] = defaultdict(int)
    for o in objects:
        seen[o.canonical_key] += 1
    dupes = sorted(k for k, n in seen.items() if n > 1)
    if dupes:
        raise VintageCollisionError(
            f"{len(dupes)} canonical key(s) minted by more than one as_of vintage group: "
            f"{dupes[:5]}{' ...' if len(dupes) > 5 else ''}. The bronze key's as_of= segment "
            "disagrees with the frame's as_of_date column; publishing would let the second "
            "copy_object silently overwrite the first."
        )


def build_objects(
    keys_to_read: list[str],
    bucket: str,
    aws_region: str,
    vintage_mode: str,
    *,
    stream: bool,
) -> list[StagedObject]:
    """Read bronze and return the staged objects, whole-set (flag off) or per vintage (flag on).

    Flag OFF is HEAD: one pool over every key, one ``pd.concat``, one ``build_staged_objects``.
    Flag ON walks ``sorted(as_of)`` ascending, holding ONE vintage's frames at a time, and sorts the
    accumulated objects by canonical key at the end -- which restores HEAD's exact object sequence,
    because HEAD's ``groupby(["commodity_name","as_of_date"], sort=True)`` yields objects ordered by
    (slug, as_of), and for ``silver/esr/commodity=<slug>/as_of=<asof>/part-000.parquet`` that IS
    canonical-key order. So even the manifest's inputs / outputs / partition_actions list order is
    identical.
    """
    global LAST_PEAK_FRAME_ROWS
    LAST_PEAK_FRAME_ROWS = 0

    if stream and vintage_mode != VINTAGE_ALL:
        # THE FENCE (module docstring). Under `latest` one object per slug is built from keys
        # spanning many as_of vintages; a per-vintage loop would mint that slug's canonical key
        # once per vintage and the last promote would win. Fall back loudly.
        logger.warning(
            "%s=on but --vintage-mode=%s: streaming is INERT under latest (one object per slug is "
            "built from keys spanning several as_of vintages, so a per-vintage loop would mint the "
            "same canonical key repeatedly). Falling back to the whole-set path.",
            _STREAM_ENV, vintage_mode,
        )
        stream = False

    if not stream:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            frames = _collect_frames(pool, keys_to_read, bucket, aws_region, submit_order=False)
        if not frames:
            return []
        combined = pd.concat(frames, ignore_index=True)
        LAST_PEAK_FRAME_ROWS = len(combined)
        logger.info(
            "Silver combined: %d rows across %d market_years / %d as_of vintages",
            len(combined),
            combined["market_year"].nunique() if "market_year" in combined.columns else 0,
            combined["as_of_date"].nunique() if "as_of_date" in combined.columns else 0,
        )
        return build_staged_objects(combined, vintage_mode)

    # --- flag ON: one vintage resident at a time ---------------------------------------------
    by_vintage: dict[str, list[str]] = defaultdict(list)
    for key in keys_to_read:
        by_vintage[parse_hive_key(key, "as_of")].append(key)

    objects: list[StagedObject] = []
    total_rows = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:   # ONE pool for every vintage
        for as_of in sorted(by_vintage):
            vintage_keys = sorted(by_vintage[as_of])
            frames = _collect_frames(pool, vintage_keys, bucket, aws_region, submit_order=True)
            if not frames:
                logger.warning("as_of=%s: all %d bronze read(s) failed or empty -- vintage "
                               "contributes no object", as_of or "<undated>", len(vintage_keys))
                continue
            combined = pd.concat(frames, ignore_index=True)
            del frames
            combined = _reindex_emitted(combined)
            rows = len(combined)
            total_rows += rows
            LAST_PEAK_FRAME_ROWS = max(LAST_PEAK_FRAME_ROWS, rows)
            vintage_objects = build_staged_objects(combined, vintage_mode)
            del combined
            objects.extend(vintage_objects)
            logger.info(
                "as_of=%s streamed: %d bronze file(s) -> %d rows -> %d object(s)  "
                "(running: %d object(s), peak frame %d rows)",
                as_of or "<undated>", len(vintage_keys), rows, len(vintage_objects),
                len(objects), LAST_PEAK_FRAME_ROWS,
            )

    if not objects:
        return []
    _assert_no_vintage_collision(objects)
    objects.sort(key=lambda o: o.canonical_key)
    logger.info(
        "Silver streamed: %d rows across %d as_of vintages -> %d object(s). Peak resident frame "
        "%d rows (%.1f%% of the whole-history frame this run would otherwise have held).",
        total_rows, len(by_vintage), len(objects), LAST_PEAK_FRAME_ROWS,
        (100.0 * LAST_PEAK_FRAME_ROWS / total_rows) if total_rows else 0.0,
    )
    return objects


def publish_esr_compact(
    objects: list[StagedObject],
    *,
    bucket: str,
    s3_client,
    glue_client,
    auth,
    vintage_mode: str,
    shadow_prefix: str | None = None,
    code_sha: str | None = None,
    run_id: str | None = None,
):
    """Publish the compact objects through the F015 shadow publisher + F013 registered-partition
    publisher. Returns the run manifest (persisted; FAILED runs included). No canonical mutation
    unless ``auth.may_mutate_canonical`` -- otherwise every partition action is PLANNED.

    ``reconcile_schema_widen=True`` (2026-09-04, the SILVER-F030 BF-W2 additive widen) is not
    cosmetic: it is what keeps the WHOLE family's promote alive across the Glue ``ADD COLUMNS``.
    PartitionPublisher.publish_one builds every partition's desired StorageDescriptor by copying
    the TABLE SD, so the moment the table widens from 12 to 17 columns EVERY already-registered
    partition diffs; with no RepairAuthorization and this flag False, publish_one calls _fail,
    ShadowPublisher._catalog raises PublisherError, and the canonical run exits 1 -- for the entire
    table, not just the new columns. The self-heal it enables is deliberately narrow:
    catalog.is_schema_widen admits ONLY a pure TRAILING-column append at an identical
    location/format/SerDe (measured: five columns at the tail -> True, the same five inserted at
    position 9 -> False), so F013's wrong-location protection is untouched. This flag must be LIVE
    on the image that runs the promote BEFORE the ALTER is applied; expect partition_actions
    'repaired' on every pre-existing partition on the first post-ALTER promote and 'existing' on
    the second."""
    publisher = ShadowPublisher(
        job="bronze_to_silver_esr",
        table=_TABLE,
        database=_DATABASE,
        bucket=bucket,
        canonical_root=f"s3://{bucket}/{_SILVER_ESR_PREFIX}",
        auth=auth,
        s3_client=s3_client,
        glue_client=glue_client,
        strategy=PublishStrategy.REGISTERED,
        shadow_prefix=shadow_prefix,
        validation=ValidationHooks(min_rows=1, min_nonnull_frac=0.0),
        code_sha=code_sha,
        registry_schema_version=1,
        run_id=run_id or f"{_TABLE}-{vintage_mode}",
        reconcile_schema_widen=True,
    )
    return publisher.run(objects)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    probe = PeakMemoryProbe().start()

    parser = argparse.ArgumentParser(description="USDA ESR bronze -> silver (compact, gated)")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--vintage-mode", default=VINTAGE_LATEST,
                        choices=[VINTAGE_LATEST, VINTAGE_ALL],
                        help="latest (default, single as_of per MY) | all (option-b per-week, BF-W2)")
    parser.add_argument("--publish-mode", default="dry-run",
                        help="dry-run (default) | shadow | canonical (signed approval required)")
    parser.add_argument("--shadow-prefix", default=None, dest="shadow_prefix")
    parser.add_argument("--force-overwrite", default="false", dest="force_overwrite",
                        help="retained for compatibility; the publisher's exact/repair semantics "
                             "supersede blind skip-existing")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    vintage_mode = args.vintage_mode

    # 1. List bronze + select keys for the chosen vintage mode.
    all_keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    logger.info("Found %d total bronze ESR files", len(all_keys))
    keys_to_read = _select_keys(all_keys, vintage_mode)
    logger.info("vintage-mode=%s -> selected %d bronze files", vintage_mode, len(keys_to_read))

    # 2. F032 ordering guard BEFORE any read/write.
    assert_bronze_ready(all_keys, keys_to_read)

    # 3. Download + transform + stage. Whole-set (HEAD) or per-vintage streaming (dark flag).
    stream = vintage_stream_enabled()
    logger.info("%s=%s -> %s path", _STREAM_ENV, "on" if stream else "off",
                "per-vintage streaming" if stream else "whole-history concat (HEAD)")
    objects = build_objects(keys_to_read, bucket, aws_region, vintage_mode, stream=stream)
    if not objects:
        logger.error("All bronze reads/transforms failed - nothing to write")
        sys.exit(1)

    # 4. Authorize + publish (shadow-first, registered, fail-safe). ONE run(), ONE manifest, ALL
    # objects -- the whole-history re-stage and its post-ALTER descriptor self-heal are preserved
    # on both arms (design 2.3).
    logger.info("Staged %d compact object(s) for vintage-mode=%s", len(objects), vintage_mode)

    import boto3
    sts = boto3.client("sts", region_name=aws_region)
    ident = sts.get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database=_DATABASE,
                      prefix=f"{_SILVER_ESR_PREFIX}/", role_arn=ident["Arn"], table=_TABLE),
        argv=sys.argv,
    )
    glue_client = boto3.client("glue", region_name=aws_region) if auth.may_mutate_canonical else None
    s3_client = get_thread_local_s3_client(aws_region)

    manifest = publish_esr_compact(
        objects, bucket=bucket, s3_client=s3_client, glue_client=glue_client, auth=auth,
        vintage_mode=vintage_mode, shadow_prefix=args.shadow_prefix,
    )
    logger.info(
        "ESR bronze->silver complete. mode=%s vintage=%s state=%s objects=%d partition_actions=%s",
        auth.mode.value, vintage_mode, manifest.state.value, len(objects),
        {a.get("outcome"): 1 for a in manifest.partition_actions} if manifest.partition_actions else {},
    )
    probe.report()
    if manifest.state == ManifestState.FAILED:
        logger.error("publish FAILED: %s", manifest.failure_reason)
        sys.exit(1)


if __name__ == "__main__":
    main()
