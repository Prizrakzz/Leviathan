"""SILVER-F082 freshness poller -- THE IN-IMAGE TASK.

Emits, per poll cycle: FreshnessLagDays{Table,Family}, FreshnessLagRatio{Table,Family} (D-PR-14),
FreshnessBreachCount{Family} (D-SG G3-1), and -- P6/P7, 2026-09-22 -- the DATA axis beside the write
axis: DataDateAgeDays{Table,Family}, DataDateAgeRatio{Table,Family}, DataDateUnread{Reason} and the
undimensioned FreshnessTargetsPolled. P8 (round 3) adds the LEDGER LIVENESS GAUGES --
CorpusFoldAgeDays{Family} and CorpusChunkAgeDays{Family}, one LIST each, no GET.

WHY A DAILY POLLER CARRIES THE LIVENESS OF A MONTHLY JOB. "It did not run" is the one datapoint a
dead job cannot publish, so round 2 asked the question with an M-of-N alarm over 35 daily periods --
a shape PutMetricAlarm REFUSES (Period x EvaluationPeriods <= 604,800 s; 86,400 x 35 = 3,024,000).
The ruling (owner, 2026-09-22) inverts it: the reporter that is alive every day reads the leg's own
LEDGER and emits its AGE, and the alarm is one daily evaluation of that age. See
``leviathan.silver.freshness.LEDGER_GAUGES`` for the declarations, the thresholds and their basis.

THE DATA AXIS, IN ONE PARAGRAPH. Everything this poller measured before P6 was S3 OBJECT MTIME, so
a producer that re-writes a byte-identical object on its fire cadence read 0 days forever while its
CONTENT was dead: silver_sagis_weekly_exports polled GREEN at 3.01 days on 2026-09-21 holding data
from 2024-04-26 -- 879 days, 46x its own ceiling -- and four unica/mpoc legs sat between 7x and 17x
under the same blindness. The estate had 52 alarms on write dates and ZERO on data dates. The data
date is now read from the target's OWN DECLARED axis (``registry.knowledge_date_col``): from the S3
KEY when that column is a partition key (free, exact, every object), and otherwise from the parquet
FOOTER statistics of at most four newest-written canonical objects (one ~64 KB ranged GET each --
MEASURED, not estimated). Nothing is sniffed, nothing is guessed, and a target whose axis cannot be
read emits NO data datapoint and increments a counted, alarmed ``DataDateUnread{Reason=unreadable}``
rather than a fabricated zero. ``--no-data-date`` restores the byte-identical pre-P6 WRITE-axis
payload and issues no GET at all -- plus the announcing datums ``DataDateUnread{Reason=...}`` over
the six declared ``UNREAD_REASONS`` (``disabled`` among them), so the rollback lever cannot itself
become a silent blindness.

TWO ROUND-2 CORRECTIONS (adversarial review, 2026-09-22). (M1) A target named in
``freshness.STATIC_DATA_TARGETS`` is excluded from the ALARM, never from the READING: round 1
skipped the footer read for all three, which deleted a live reading on the one of them whose axis is
fully declared and made the declaration's own removal trigger unobservable. (M3) A data date AHEAD
of the clock still publishes no age datapoint, but ``DataDateUnread{Reason=ahead}`` is now ALARMED:
a forward-stamped knowledge row is one guard away from a point-in-time leak, and round 1 left the
class recorded, unalarmed and unpinned -- a table could leave the content watch in silence.

WHY THIS FILE EXISTS, AND WHY scripts/silver/freshness_poller.py IS NOW A SHIM OVER IT.
The worker image COPYs src/ jobs/ configs/ sql/ and NOT scripts/, so the scheduled poller could
never invoke the script. infra/terraform/envs/dev/main.tf therefore carried a hand-transcribed
``python -c`` COPY of the script's emit loop inside the schedule's ContainerOverrides. That copy
has now drifted from the script TWICE, and both times silently:

  * R7a (found 2026-08-04): the inline loop called ``poll_targets()`` -- registry-pure by design --
    where the script had moved to ``all_poll_targets()``. The ONE artifact ``EXTRA_TARGETS`` exists
    for, ``graphrag_timeline_episodes``, was never polled: 0 datapoints over a 7-day window while
    the control family emitted daily.
  * D-SG (found 2026-08-16): the inline loop called
    ``metric_data_for(t.table, t.family, lag, timestamp=now)`` with NO ``expected=``, so
    ``metric_data_for`` took its ``ratio is None`` early return and D-PR-14's ``FreshnessLagRatio``
    was NEVER emitted in production. Measured: ``list-metrics --namespace Leviathan/Silver``
    returned FreshnessLagDays, BatchJobFailedScheduled, BatchJobFailedBackstop and nothing else,
    three months after the ratio was built, unit-tested and documented as live.

Two drifts in one quarter on one block is a CLASS, not two bugs. The class dies here: the
schedule now names a module that ships in the image, and terraform holds no python at all.

The age computation, the canonical-only exclusions, the ratio, its denominator and the breach
predicate all live in the pure core ``leviathan.silver.freshness`` and are unit-tested there. This
file is the thin boto3 wrapper: one ``list_objects_v2`` per prefix, no Athena, and -- since P6 --
at most four ~64 KB RANGED GETs per column-axis target for the parquet footer, and none at all under
``--no-data-date``.

EMPTY-PREFIX BEHAVIOUR: a table whose canonical prefix has zero objects emits NO lag/ratio
datapoint (logged EMPTY) and counts as a BREACH in its family's FreshnessBreachCount -- see
``freshness.is_breaching`` for why that asymmetry is deliberate. On the DATA axis it is recorded
ABSENT and never alarmed, because the write axis already says it at full volume and two tables in
this estate are deliberately empty (see ``freshness.UNREAD_ABSENT``).

THE ONE GET THIS FILE NOW MAKES, and the IAM line it depends on: the footer read needs
``s3:GetObject`` on the data-lake bucket. The jobdef the schedule actually targets today
(``leviathan-dev-raw-ingest-runner``) runs as ``leviathan-dev-batch-job-role``, which carries
``leviathan-dev-s3-data-lake-rw`` -- VERIFIED 2026-09-22, so no permission moves for the live path.
``jobs/utils/register_freshness_poller_jobdef.py`` declares a DEDICATED least-privilege role scoped
to ListBucket + PutMetricData; that role would refuse the footer read, and its docstring now says so.

ASCII-only stdout (Windows console cp1252).

    python -m jobs.observability.freshness_poller_task
    python -m jobs.observability.freshness_poller_task --dry-run
    python -m jobs.observability.freshness_poller_task --tables silver_fgis,silver_nass_citrus
    python -m jobs.observability.freshness_poller_task --no-ratio    # D-PR-14 rollback
    python -m jobs.observability.freshness_poller_task --no-breach-count   # G3-1 rollback
    python -m jobs.observability.freshness_poller_task --no-data-date      # P6 rollback
    python -m jobs.observability.freshness_poller_task --no-ledger-age     # P8 rollback
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import boto3

# Local runs (repo checkout, no editable install) need src/ on the path. Inside the image the
# package is pip-installed, so this is a no-op there.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.freshness import (  # noqa: E402
    AXIS_COLUMN,
    AXIS_INGEST,
    AXIS_PARTITION,
    AXIS_UNDECLARED,
    BREACH_METRIC_NAME,
    DATA_DATE_METRIC_NAME,
    LEDGER_GAUGES,
    METRIC_NAMESPACE,
    TARGETS_POLLED_METRIC_NAME,
    UNREAD_ABSENT,
    UNREAD_AHEAD,
    UNREAD_DISABLED,
    UNREAD_REASONS,
    UNREAD_STATIC,
    UNREAD_UNDECLARED,
    UNREAD_UNREADABLE,
    all_poll_targets,
    breach_counts,
    breach_metric_data,
    coerce_data_date,
    data_age_days,
    data_metric_data_for,
    is_ahead,
    lag_days,
    lag_ratio,
    ledger_metric_data,
    metric_data_for,
    partition_segment_of,
    scan_prefix,
    targets_polled_metric_data,
    unread_metric_data,
)

# CloudWatch caps PutMetricData at 1000 MetricDatum/request; 20 is the classic conservative batch
# size. MEASURED 2026-08-16: 46 targets x 4 datums + ~25 family breach datums = ~209 -> 11
# requests. Two orders of magnitude under the cap.
_PUT_CHUNK = 20

# P6. How many of a target's NEWEST-WRITTEN canonical objects a column-axis read samples.
#
# FOUR, and the number is a bound on COST whose error direction is a bound on SAFETY.
#
# COST: measured against a real 1.78 MB parquet, pyarrow's footer read over a seekable file object
# issued ONE ranged GET of 65,536 bytes -- it seeks to the tail and reads the footer, never the
# data. Four objects x ~46 targets is at most ~184 ranged GETs and ~12 MB per DAILY cycle. The
# silver_rebuild_gate refused a footer walk at "~1.4K GETs per gate run" for silver_chirps; that
# table declares NO data axis and is never footer-read here at all, and this bound is two orders of
# magnitude under the number the gate refused.
#
# SAFETY: for a FLAT table -- which is what the entire stale-green class is (sagis_weekly_exports,
# every unica leg, every mpoc leg, icco, mpob, psd, pink_sheet: one ``part-000.parquet`` under the
# prefix, verified by listing on 2026-09-22) -- four is not a sample, it is the whole table, and the
# reading is EXACT. For a partitioned table it IS a sample, and a MAX over a subset can only come
# out AT OR BELOW the true newest data date. Under-reading makes a table look OLDER, which fires the
# alarm; it can never make a dead table look fresh. That is the fail-CLOSED direction, and it is the
# direction this whole axis exists to guarantee.
#
# The two partitioned tables whose axis IS their partition key (silver_wasde, silver_esr_compact)
# never enter this path: their date is read from EVERY key in the listing, for free and exactly.
_DATA_DATE_MAX_OBJECTS = 4

# Only these are footer-read. A ``_SUCCESS`` marker or a stray .json under a canonical prefix is not
# a parquet file and must not be opened as one.
_PARQUET_SUFFIXES = (".parquet", ".parq", ".pq")


def _iter_objects(s3, bucket: str, prefix: str):
    """Yield ``(key, LastModified)`` for every object under ``prefix`` (paginated list, no GET)."""
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["LastModified"]


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class _S3RangeFile(io.RawIOBase):
    """A seekable read-only file over ONE S3 object, served by ranged ``get_object`` calls.

    WHY NOT JUST GET THE OBJECT. ``silver/psd_attributes/part-000.parquet`` is 6.1 MB and the estate
    has objects far larger; a poller that downloads every newest object to read one date would turn
    a 0.25-vCPU lister into a daily multi-gigabyte transfer. pyarrow, handed a seekable file, reads
    only the footer: MEASURED on a 1.78 MB parquet it made ONE call for 65,536 bytes at offset
    1,715,034. This class is what makes that seek reach S3 instead of a local buffer.

    ``bytes_fetched`` is carried so the poller can PRINT what its new axis costs, rather than the
    next reader having to infer it from a bill."""

    def __init__(self, s3, bucket: str, key: str, size: int):
        self._s3, self._bucket, self._key, self._size = s3, bucket, key, int(size)
        self._pos = 0
        self.bytes_fetched = 0
        self.calls = 0

    # -- the three things pyarrow's PythonFile asks of a handle --------------------------------
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self._size + offset
        if self._pos < 0:
            self._pos = 0
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._size - self._pos
        start = self._pos
        end = min(start + size, self._size) - 1
        if size <= 0 or start >= self._size or end < start:
            return b""
        resp = self._s3.get_object(
            Bucket=self._bucket, Key=self._key, Range=f"bytes={start}-{end}")
        body = resp["Body"].read()
        self.calls += 1
        self.bytes_fetched += len(body)
        self._pos = start + len(body)
        return body


def _footer_max_date(fileobj, column: str) -> tuple[date | None, str | None]:
    """The MAX of ``column``'s parquet footer statistics as a ``date`` -- or ``(None, reason)``.

    Every row group is coerced INDEPENDENTLY through ``coerce_data_date`` and the max is taken over
    the coerced dates, never over the raw statistic values. Two reasons, both load-bearing: the raw
    values are typed by the writer (``str`` for a UTF8 column, ``datetime.date`` for date32,
    ``int`` for an integer date) and comparing them across a schema change would raise; and one
    unparseable row group then costs that row group and not the whole file.

    pyarrow is imported INSIDE the function on the gate's precedent, so an image without it
    degrades this target to UNREADABLE -- one counted, alarmed blindness -- instead of failing the
    module import and taking all 26 write-axis metrics down with it."""
    try:
        import pyarrow.parquet as pq
    except Exception as e:  # noqa: BLE001
        return None, f"pyarrow unavailable ({type(e).__name__})"
    md = pq.ParquetFile(fileobj).metadata
    names = list(md.schema.names)
    if column not in names:
        return None, f"declared column '{column}' is absent from the parquet schema"
    idx = names.index(column)
    best: date | None = None
    saw_stats = False
    for rg in range(md.num_row_groups):
        stats = md.row_group(rg).column(idx).statistics
        if stats is None or not stats.has_min_max:
            continue
        saw_stats = True
        value = coerce_data_date(stats.max)
        if value is not None and (best is None or value > best):
            best = value
    if best is None:
        return None, (f"column '{column}' carries no usable min/max statistics"
                      if not saw_stats else
                      f"column '{column}' statistics did not parse as a date")
    return best, None


def _read_data_date(s3, target, scan) -> tuple[date | None, str | None, int]:
    """``(newest data date, reason it is None, bytes fetched)`` for ONE target. NEVER RAISES.

    The whole DATA axis is wrapped here. Every one of the 26 write-axis alarms is
    ``treat_missing_data = "breaching"``, so ONE unhandled exception anywhere in this new leg would
    stop the poll, withhold every ``FreshnessLagDays`` datapoint and page 21 owners at once -- "the
    fence that kills the thing it measures". So this function has exactly two outcomes, a date or a
    reason, and the reason is counted and alarmed as ``DataDateUnread{Reason=unreadable}``.

    PARTITION axis: the max is over EVERY canonical key the listing already returned -- exact, and
    no GET at all. COLUMN axis: the footers of at most :data:`_DATA_DATE_MAX_OBJECTS` newest-written
    canonical parquet objects."""
    if target.data_date_mode == AXIS_PARTITION:
        segment = partition_segment_of(target.table, target.data_date_col)
        value = scan.newest_partition_value
        if value is None:
            return None, (f"no '{segment}=' partition segment under the canonical "
                          f"prefix ({scan.canonical_objects} canonical object(s))"), 0
        parsed = coerce_data_date(value)
        if parsed is None:
            return None, f"partition value '{value}' did not parse as a date", 0
        return parsed, None, 0

    fetched = 0
    newest: date | None = None
    reasons: list[str] = []
    candidates = [(lm, key) for lm, key in scan.newest_written
                  if key.lower().endswith(_PARQUET_SUFFIXES)]
    if not candidates:
        return None, (f"no canonical parquet object under the prefix "
                      f"({scan.canonical_objects} canonical object(s))"), 0
    for _lm, key in candidates:
        try:
            head = s3.head_object(Bucket=target.bucket, Key=key)
            handle = _S3RangeFile(s3, target.bucket, key, head["ContentLength"])
            value, why = _footer_max_date(handle, target.data_date_col)
            fetched += handle.bytes_fetched
        except Exception as e:  # noqa: BLE001 -- a telemetry read may never stop the poll
            value, why = None, f"{type(e).__name__}: {str(e)[:120]}"
        if value is not None and (newest is None or value > newest):
            newest = value
        if why:
            reasons.append(f"{key.rsplit('/', 1)[-1]}: {why}")
    if newest is None:
        return None, "; ".join(reasons[:2]) or "no readable footer", fetched
    return newest, None, fetched


def _read_ledger_age(s3, gauge, now: datetime) -> tuple[float | None, str, str | None]:
    """``(age_days, source, reason it is None)`` for ONE ledger gauge. NEVER RAISES.

    Wrapped for the same reason :func:`_read_data_date` is: every one of the 26 write-axis alarms
    is ``treat_missing_data = "breaching"``, so one unhandled exception in a telemetry leg would
    withhold the whole cycle and page 21 owners at once. The failure is returned, printed, and
    owned by the gauge's own alarm -- never swallowed.

    The FALLBACK prefix is read ONLY when the primary lists empty, and the line says which one
    served the reading, so nobody has to infer from a number which artifact it came from.

    ``scan_prefix`` is reused rather than a bare max(), so the canonical-only exclusions
    (``/_shadow/``, ``/_staging/``, ``/_backup/``, ``/_manifests/``) govern this axis too. The four
    doors this estate has had to close were all fail-OPEN; a third axis that re-opened one would be
    a fifth."""
    tried: list[str] = []
    sources = [(gauge.prefix, "ledger")]
    if gauge.fallback_prefix:
        sources.append((gauge.fallback_prefix, "FALLBACK"))
    for prefix, label in sources:
        try:
            scan = scan_prefix(_iter_objects(s3, gauge.bucket, prefix),
                               partition_col=gauge.partition_key, keep_newest=1)
        except Exception as e:  # noqa: BLE001 -- a telemetry read may never stop the poll
            tried.append(f"{prefix}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if scan.newest is None:
            tried.append(f"{prefix}: no object")
            continue
        if gauge.partition_key:
            # THE CONTENT DATE, read from the KEY: free, exact, every object, and immune to the
            # bulk re-write that makes an mtime gauge read fresh over a frozen tip.
            value = scan.newest_partition_value
            if value is None:
                tried.append(f"{prefix}: no '{gauge.partition_key}=' partition segment "
                             f"({scan.canonical_objects} canonical object(s))")
                continue
            parsed = coerce_data_date(value)
            if parsed is None:
                tried.append(f"{prefix}: partition value '{value}' did not parse as a date")
                continue
            age = data_age_days(parsed, now)
            if is_ahead(age):
                # The same ruling the data axis carries: a future date is not a freshness figure.
                # No datum -- and because this gauge's alarm is breaching, the silence PAGES.
                tried.append(f"{prefix}: {gauge.partition_key}={value} is AHEAD of the clock by "
                             f"{-age:.0f}d")
                continue
            return (max(age, 0.0),
                    f"s3://{gauge.bucket}/{prefix}{gauge.partition_key}={value} "
                    f"({scan.canonical_objects} object(s))", None)
        key = scan.newest_written[0][1] if scan.newest_written else prefix
        age = lag_days(scan.newest, now)
        return age, f"s3://{gauge.bucket}/{key}" + ("" if label == "ledger" else f" [{label}]"), None
    return None, "", "; ".join(tried)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="SILVER-F082 freshness poller (FreshnessLagDays + FreshnessLagRatio + "
                    "FreshnessBreachCount)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + print the lags but do NOT put_metric_data (read-only)")
    ap.add_argument("--aws-region", default="us-east-1")
    ap.add_argument("--namespace", default=METRIC_NAMESPACE)
    ap.add_argument("--tables", default=None,
                    help="comma-separated table_name filter (default: every registered table). "
                         "NB a filtered run emits PARTIAL breach counts -- use --no-breach-count "
                         "with it unless you mean to overwrite a family's datapoint.")
    ap.add_argument("--no-ratio", action="store_true",
                    help="D-PR-14 rollback switch: suppress FreshnessLagRatio. Additive metric, "
                         "so this restores the exact pre-D-PR-14 payload without a redeploy.")
    ap.add_argument("--no-breach-count", action="store_true",
                    help="D-SG G3-1 rollback switch: suppress FreshnessBreachCount. Additive "
                         "metric; the day-based alarms never moved either way.")
    ap.add_argument("--no-data-date", action="store_true",
                    help="P6 rollback switch: suppress the DATA axis (DataDateAgeDays, "
                         "DataDateAgeRatio, the per-reason DataDateUnread tally) and issue no GET "
                         "at all. The WRITE-axis payload is then BYTE-IDENTICAL to the pre-P6 "
                         "poller; what remains on the data axis is the one-per-reason "
                         "DataDateUnread census, in which Reason=disabled carries the count of "
                         "darkened targets and the other five ride at ZERO so their alarms can "
                         "still clear. That is how the lever stays visible instead of going dark "
                         "in silence.")
    ap.add_argument("--no-ledger-age", action="store_true",
                    help="P8 rollback switch: suppress the LEDGER LIVENESS GAUGES "
                         "(CorpusFoldAgeDays, CorpusChunkAgeDays) and issue no LIST for them. "
                         "THE LEVER CANNOT GO DARK IN SILENCE: those alarms are "
                         "treat_missing_data=breaching, so a cycle that does not emit them pages "
                         "within one day. It exists for a broken prefix, never for quiet.")
    ap.add_argument("--data-date-objects", type=int, default=_DATA_DATE_MAX_OBJECTS,
                    help="how many newest-written canonical objects a COLUMN-axis footer read "
                         f"samples (default {_DATA_DATE_MAX_OBJECTS}); a partition-axis target "
                         "reads every key and ignores this.")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    targets = all_poll_targets()   # registry tables + the non-registry artifacts (FENCE 2 leg 3)
    filtered = False
    if args.tables:
        want = {t.strip() for t in args.tables.split(",") if t.strip()}
        targets = [t for t in targets if t.table in want]
        filtered = True

    s3 = boto3.client("s3", region_name=args.aws_region)
    cw = None if args.dry_run else boto3.client("cloudwatch", region_name=args.aws_region)

    emit_breach = not args.no_breach_count and not filtered
    # P7 (c): the same self-report the silver gate prints, so "the baked registry is five weeks
    # behind the repo" is readable in the poller's OWN log and not only by diffing two counts across
    # a CloudWatch dashboard. banner() never raises.
    try:
        from leviathan.common.image_stamp import banner  # noqa: PLC0415 -- telemetry, never fatal
        for line in banner("FRESHNESS-POLLER"):
            print(line)
    except Exception as e:  # noqa: BLE001
        print(f"FRESHNESS-POLLER IMAGE: provenance unavailable ({type(e).__name__})")
    data_axis = not args.no_data_date
    print(f"=== freshness_poller: {len(targets)} targets, asof {now.isoformat()} "
          f"(dry_run={args.dry_run} ratio={not args.no_ratio} breach={emit_breach} "
          f"data_date={data_axis}) ===")
    if filtered and not args.no_breach_count:
        print("  [breach] SUPPRESSED: --tables makes the per-family counts partial, and a "
              "partial count would overwrite the real one at this timestamp.")

    metric_data: list[dict] = []
    breach_rows: list[tuple[str, float | None, float | None]] = []
    empty: list[str] = []
    breaching: list[str] = []
    no_ceiling: list[str] = []
    unread: dict[str, int] = {reason: 0 for reason in UNREAD_REASONS}
    data_breaching: list[str] = []
    unreadable: list[str] = []
    ahead: list[str] = []
    polled = 0
    data_bytes = 0
    # PRINTED, never derived (review m1). Round 1's report said "0 -> 30 targets emitting" while
    # the run emitted 29, because the figure was reached by subtracting the unread tally from 53 --
    # and after M1 that subtraction is wrong in the other direction, since a STATIC target is
    # counted under its reason AND emits. The count of targets that actually produced a
    # DataDateAgeDays datum is now a number this loop carries.
    data_emitted = 0
    for t in sorted(targets, key=lambda x: x.table):
        # ONE listing pass serves BOTH axes. `keep_newest` is 0 unless a COLUMN-axis footer read is
        # actually going to happen, so a target that reads its date from the key -- or reads none at
        # all -- pays nothing for the heap.
        #
        # ROUND 2 (review M1): `t.static_reason` is NO LONGER a clause here. A declared closed
        # archive is excluded from the ALARM (freshness.data_date_alarm_targets), never from the
        # MEASUREMENT -- round 1 denied it the listing heap as well as the read, so
        # silver_mpoc_exports_by_country's fully declared axis went unread and the entry's own
        # removal trigger ("the day the source publishes again") became unobservable.
        wants_footer = data_axis and t.data_date_mode == AXIS_COLUMN
        scan = scan_prefix(
            _iter_objects(s3, t.bucket, t.prefix),
            partition_col=(partition_segment_of(t.table, t.data_date_col)
                           if data_axis and t.data_date_mode == AXIS_PARTITION else None),
            keep_newest=max(args.data_date_objects, 0) if wants_footer else 0,
        )
        polled += 1
        newest = scan.newest
        lag = lag_days(newest, now)
        expected = None if args.no_ratio else t.expected_lag_days
        # The breach row uses the table's OWN ceiling regardless of --no-ratio: --no-ratio is a
        # metric-suppression switch, never a redefinition of what "late" means.
        breach_rows.append((t.family, lag, t.expected_lag_days))
        if lag is None:
            empty.append(t.table)
            print(f"  {t.table:42s} EMPTY canonical prefix {t.prefix} "
                  f"-> NO lag datapoint (counts as a BREACH for family {t.family})")
            # An empty prefix has no bytes to read a data date out of. Recorded as ABSENT, never
            # as UNREADABLE: see freshness.UNREAD_ABSENT -- the write axis already says this at
            # full volume, and the two deliberately-empty pre-publish tables would otherwise arm
            # the blindness alarm permanently.
            if data_axis:
                unread[UNREAD_ABSENT] += 1
            continue
        ratio = lag_ratio(lag, expected)
        if ratio is None:
            if not args.no_ratio:
                no_ceiling.append(t.table)
            ratio_txt = "ratio=n/a"
        else:
            ratio_txt = (f"expected={expected:.0f}d ratio={ratio:.3f}"
                         f"{' BREACH' if ratio > 1.0 else ''}")
            if ratio > 1.0:
                breaching.append(t.table)
        # THE WRITE-AXIS DATUMS ARE APPENDED BEFORE THE DATA AXIS IS TOUCHED, and they are
        # byte-identical to the pre-P6 payload (census threat T8's BYTE-IDENTICAL SET). The new
        # axis is beside the old one, never in front of it.
        metric_data.extend(
            metric_data_for(t.table, t.family, lag, timestamp=now, expected=expected))

        data_txt = ""
        if data_axis:
            # EXACTLY ONE reason is charged per target, and the precedence is stated rather than
            # implied (round 2, review M1/M3): AHEAD outranks STATIC because a staleness exclusion
            # may never suppress a LEAK guard; STATIC outranks UNREADABLE because a closed archive
            # has no per-table alarm to be blind FOR, and charging it would arm the one alarm that
            # has to stay believable; STATIC outranks UNDECLARED because "closed" is the more
            # specific fact. Whatever the reason, the READING is attempted whenever the axis is
            # declared and the figure is printed and emitted when it exists.
            # ONE `data=` KEY PER LINE (review m4). A declared archive whose axis is also
            # undeclared used to print `data=STATIC (...) data=UNDECLARED (...)` -- harmless to a
            # human, ambiguous to a parser, and this line is the lane's own evidence surface. The
            # `data=STATIC` token therefore rides only where STATIC is the ONLY data-axis verdict
            # (a readable archive); everywhere else the declaration rides as a bracketed note
            # BESIDE the verdict, never instead of it.
            static_txt = ""
            static_note = ""
            if t.static_reason is not None:
                static_txt = f" data=STATIC ({t.static_reason[:60]})"
                static_note = f" [STATIC: {t.static_reason[:60]}]"
            if t.data_date_mode in (AXIS_UNDECLARED, AXIS_INGEST):
                unread[UNREAD_STATIC if t.static_reason is not None else UNREAD_UNDECLARED] += 1
                data_txt = (
                    " data=UNDECLARED (contract knowledge_date_col is null)"
                    if t.data_date_mode == AXIS_UNDECLARED else
                    f" data=INGEST-AXIS ('{t.data_date_col}' records the WRITE, not the "
                    f"period; reading it would restate FreshnessLagDays)") + static_note
            else:
                data_date, why, fetched = _read_data_date(s3, t, scan)
                data_bytes += fetched
                age = data_age_days(data_date, now)
                if data_date is None:
                    # A CLOSED archive that cannot be read is charged STATIC, not UNREADABLE: it
                    # carries no data_date_age_breach alarm, so there is no blindness to declare,
                    # and the failure is still on the log line in full.
                    unread[UNREAD_STATIC if t.static_reason is not None
                           else UNREAD_UNREADABLE] += 1
                    if t.static_reason is None:
                        unreadable.append(f"{t.table} ({why})")
                    data_txt = f" data=UNREADABLE ({why})" + static_note
                elif is_ahead(age):
                    # The bytes lead the clock past the tolerance. NO age datapoint -- a future
                    # date is not a freshness figure, on the gate's own ruling -- and since round 2
                    # the reason itself ALARMS, because a forward-stamped knowledge row is one
                    # guard away from a point-in-time leak. Charged even when STATIC.
                    unread[UNREAD_AHEAD] += 1
                    ahead.append(f"{t.table}={data_date.isoformat()}")
                    data_txt = (f" data_date={data_date.isoformat()} data=AHEAD by "
                                f"{-age:.0f}d -- NO datapoint (a future date is not freshness)"
                                + static_note)
                else:
                    if t.static_reason is not None:
                        unread[UNREAD_STATIC] += 1
                    age = max(age, 0.0)
                    data_ratio = lag_ratio(age, t.expected_lag_days)
                    if data_ratio is not None and data_ratio > 1.0:
                        # TAGGED, never dropped: a declared archive's breach is a true reading that
                        # simply earns no page, and a summary line that hid it would be the same
                        # deletion M1 found one level down.
                        data_breaching.append(
                            f"{t.table}={data_ratio:.2f}x"
                            + ("(STATIC,no-alarm)" if t.static_reason is not None else ""))
                    data_emitted += 1
                    data_txt = (static_txt + f" data_date={data_date.isoformat()} "
                                f"data_age_days={age:.0f}"
                                + ("" if data_ratio is None
                                   else f" data_ratio={data_ratio:.3f}"
                                        f"{' DATA-BREACH' if data_ratio > 1.0 else ''}"
                                        f"{' (declared STATIC: NO alarm)' if t.static_reason else ''}"))
                    metric_data.extend(data_metric_data_for(
                        t.table, t.family, age, timestamp=now,
                        expected=t.expected_lag_days))
        print(f"  {t.table:42s} family={t.family:14s} "
              f"newest={newest.isoformat()} lag_days={lag:.2f} {ratio_txt}{data_txt}")

    counts = breach_counts(breach_rows)
    if emit_breach:
        metric_data.extend(breach_metric_data(counts, timestamp=now))
    hot = {k: v for k, v in sorted(counts.items()) if v}
    print(f"[breach] {len(counts)} families scored; {len(hot)} with >=1 late member: {hot}")
    print(f"[ratio] {len(breaching)} table(s) over 1.0: {sorted(breaching)}")
    if no_ceiling:
        print(f"[ratio] {len(no_ceiling)} table(s) emitted days but NO ratio "
              f"(no declared ceiling): {sorted(no_ceiling)}")

    # P7: the count this poller has printed on line 1 since it was built and nothing has ever read.
    # SUPPRESSED under --tables for exactly the reason the breach counts are: a partial count would
    # overwrite the real one at this timestamp and read as a shrunken registry.
    emit_census = not filtered
    if emit_census:
        metric_data.extend(targets_polled_metric_data(polled, timestamp=now))
    else:
        print("  [census] FreshnessTargetsPolled SUPPRESSED: --tables makes the count partial.")
    if data_axis:
        if emit_census:
            metric_data.extend(unread_metric_data(unread, timestamp=now))
        print(f"[data] {data_emitted} target(s) emitted a data date; "
              f"{len(data_breaching)} over 1.0 on the DATA axis: {sorted(data_breaching)}")
        print(f"[data] unread: absent={unread[UNREAD_ABSENT]} "
              f"ahead={unread[UNREAD_AHEAD]} {sorted(ahead)[:4]} "
              f"static={unread[UNREAD_STATIC]} "
              f"undeclared={unread[UNREAD_UNDECLARED]} "
              f"unreadable={unread[UNREAD_UNREADABLE]} {sorted(unreadable)[:6]}")
        print(f"[data] footer bytes fetched this cycle: {data_bytes}")
    else:
        # review m2 -- THE ROLLBACK LEVER ANNOUNCES ITSELF. Without this datum --no-data-date takes
        # 31 notBreaching per-table alarms plus both global data-axis alarms dark in one flag while
        # FreshnessTargetsPolled keeps reporting 53, which is precisely the silent blindness this
        # leg exists to end. Unalarmed (it is a deliberate operator action) and impossible to miss.
        darkened = sum(1 for t in targets
                       if t.data_date_mode not in (AXIS_UNDECLARED, AXIS_INGEST))
        if emit_census:
            metric_data.extend(unread_metric_data({UNREAD_DISABLED: darkened}, timestamp=now))
        print(f"[data] DISABLED by --no-data-date: {darkened} target(s) with a declared axis were "
              f"NOT read this cycle (DataDateUnread{{Reason={UNREAD_DISABLED}}}={darkened})")
    # P8. THE LEDGER LIVENESS GAUGES. Suppressed under --tables for the same reason the census
    # and the breach counts are -- a filtered run is a spot check of named tables and these are
    # estate-wide gauges, not per-target datums -- and they cost ONE list_objects_v2 per gauge with
    # no GET at all.
    ledger_axis = not args.no_ledger_age and emit_census
    if ledger_axis:
        for gauge in LEDGER_GAUGES:
            age, source, why = _read_ledger_age(s3, gauge, now)
            if age is None:
                # NO datapoint and NO fabricated number: the alarm is breaching, so this silence
                # is a page within one day rather than a green (review M-A's whole point).
                print(f"  [ledger] {gauge.key:14s} {gauge.metric_name} UNREADABLE ({why}) "
                      f"-- NO datapoint; the alarm's treat_missing_data=breaching owns this "
                      f"silence")
                continue
            metric_data.extend(ledger_metric_data(gauge, age, timestamp=now))
            print(f"  [ledger] {gauge.key:14s} {gauge.metric_name}={age:.2f}d "
                  f"bound={gauge.threshold_days:.0f}d"
                  f"{' LIVENESS-BREACH' if age > gauge.threshold_days else ''} "
                  f"cadence={gauge.cadence} source={source}")
    elif not emit_census:
        print("  [ledger] SUPPRESSED: --tables makes this a spot check; the gauges are "
              "estate-wide.")
    else:
        print(f"  [ledger] DISABLED by --no-ledger-age: {len(LEDGER_GAUGES)} gauge(s) NOT read "
              f"({', '.join(g.metric_name for g in LEDGER_GAUGES)}). Those alarms are "
              f"treat_missing_data=breaching and go RED within one day.")
    print(f"[census] {TARGETS_POLLED_METRIC_NAME}={polled}")

    if args.dry_run:
        print(f"[dry-run] would put {len(metric_data)} datapoints to {args.namespace}; "
              f"{len(empty)} empty prefixes: {empty}")
        return 0

    put = 0
    for chunk in _chunks(metric_data, _PUT_CHUNK):
        cw.put_metric_data(Namespace=args.namespace, MetricData=chunk)
        put += len(chunk)
    n_data = sum(1 for d in metric_data if d["MetricName"] == DATA_DATE_METRIC_NAME)
    print(f"[emit] put {put} datapoints to {args.namespace} "
          f"(incl. {BREACH_METRIC_NAME} for {len(counts) if emit_breach else 0} families, "
          f"{DATA_DATE_METRIC_NAME} for {n_data // 2} tables); "
          f"{len(empty)} empty prefixes: {empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
