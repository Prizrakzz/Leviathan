"""SILVER-F082: the data-age (freshness) pure core for the freshness poller.

WHY THIS EXISTS (audit finding, 2026-07-23)
-------------------------------------------
The 21 per-family ``FreshnessLagDays`` alarms (``jobs/observability/silver_alarms.py`` +
``modules/silver_observability``) were HOLLOW: nothing ever emitted the metric, and the alarms
were ``treat_missing_data = "missing"`` -- so a stalled producer never breached. Four producers
(``silver_nass_crop_progress``, ``silver_unica_biweekly_season_history``, ``silver_fgis``,
``silver_nass_citrus``) ran stale-green for 6-10 weeks undetected. This module is the emitter's
pure core: given the canonical S3 listing for a registry table it computes the data AGE in days
(newest ``LastModified`` under the CANONICAL prefix, excluding the shadow/staging soak areas and
the backup areas), and builds the CloudWatch ``PutMetricData`` items dimensioned by both ``Table``
and ``Family``.

Design follows ``scripts/silver/day0_heartbeat.py``'s ``freshness_delta`` canonical-only exclusion
rule (a shadow publish never advances canonical, so shadow keys must not masquerade as fresh data),
extended with ``/_backup/`` per R7.2 below. Pure + AWS-free + deterministic so the age computation,
the non-canonical exclusions, and the empty-prefix behaviour are all unit-testable against a fake
S3 listing. The thin boto3 wrapper that
actually lists S3 and calls ``put_metric_data`` lives in ``scripts/silver/freshness_poller.py``.

D-PR-14 -- THE SECOND METRIC (``FreshnessLagRatio``), 2026-08-04
---------------------------------------------------------------
Five family alarms had been in ALARM since 2026-07-23/07-30 and, because CloudWatch notifies on
TRANSITION, were silent AND could never signal a NEW stall. The mechanism is arithmetic, not
mis-tuning: ``jobs/observability/silver_alarms.py`` thresholds a family at
``dag_catalog.build_catalog``'s ``max_sla_lag_days``, which is ``min()`` over the family's members
("the tightest interim ceiling"), and then evaluates it with ``statistic=Maximum`` over those same
members. A mixed-cadence family compares its FASTEST member's ceiling against its SLOWEST member's
lag, so it is GUARANTEED to breach (``usda_nass``: 14d ceiling vs ``silver_nass_annual`` at 64.83d;
``weather``: a 3d ceiling vs ``silver_modis_ndvi``, an 8-day composite -- arithmetically
unsatisfiable).

The fix is to NORMALIZE PER MEMBER BEFORE the family ``Maximum`` collapses them:
``FreshnessLagRatio = lag_days / <that table's own declared ceiling>``, so **1.0 is the universal
threshold** for annual, biweekly and daily tables alike.

TWO RULES THIS MODULE ENFORCES, both from the ratified decision:
  1. **ALONGSIDE, NEVER INSTEAD.** A metric RENAME would orphan all 26 existing ``FreshnessLagDays``
     alarms at once. :func:`metric_data_for` therefore still emits the two day-based datums
     unchanged and APPENDS the ratio ones; the alarm cutover is a separate terraform batch item that
     runs with both metrics live.
  2. **EMITTER-SIDE ONLY.** Nothing here creates, renames or reads an alarm, and the timeline alarm
     tfvars (D-EI-12) are untouched. Per-leg ``FreshnessLagDays`` granularity remains owned by
     D-EI-12/R7 -- referenced, not forked.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Iterable, Optional

from leviathan.silver.dag_catalog import (
    FRESHNESS_LAG_OVERRIDES,
    effective_sla_lag_days,
    family_of,
)
from leviathan.silver.registry import SilverRegistry, load_registry

__all__ = [
    "METRIC_NAMESPACE",
    "METRIC_NAME",
    "RATIO_METRIC_NAME",
    "BREACH_METRIC_NAME",
    "DATA_DATE_METRIC_NAME",
    "DATA_DATE_RATIO_METRIC_NAME",
    "DATA_DATE_UNREAD_METRIC_NAME",
    "TARGETS_POLLED_METRIC_NAME",
    "TABLE_CEILING_OVERRIDES",
    "RETIRED_WRITE_SURFACES",
    "STATIC_DATA_TARGETS",
    "DATA_DATE_AHEAD_KNOWN",
    "AXIS_PARTITION",
    "AXIS_COLUMN",
    "AXIS_UNDECLARED",
    "AXIS_INGEST",
    "DATA_DATE_AHEAD_TOLERANCE_DAYS",
    "PARTITION_SEGMENT_OVERRIDES",
    "is_ahead",
    "partition_segment_of",
    "UNREAD_UNREADABLE",
    "UNREAD_UNDECLARED",
    "UNREAD_STATIC",
    "UNREAD_ABSENT",
    "UNREAD_AHEAD",
    "UNREAD_DISABLED",
    "UNREAD_REASONS",
    "is_excluded_key",
    "PrefixScan",
    "scan_prefix",
    "newest_last_modified",
    "lag_days",
    "declared_ceiling_days",
    "lag_ratio",
    "is_breaching",
    "breach_counts",
    "breach_metric_data",
    "PollTarget",
    "poll_targets",
    "EXTRA_TARGETS",
    "all_poll_targets",
    "metric_data_for",
    "data_date_axis",
    "partition_value",
    "coerce_data_date",
    "data_age_days",
    "data_metric_data_for",
    "unread_metric_data",
    "targets_polled_metric_data",
    "data_date_alarm_targets",
    "data_date_undeclared_tables",
    "CLOUDWATCH_MAX_EVALUATION_SECONDS",
    "LedgerGauge",
    "LEDGER_GAUGES",
    "ledger_gauge",
    "ledger_metric_data",
    "alarm_window_seconds",
    "refuse_uncreatable_window",
]

METRIC_NAMESPACE = "Leviathan/Silver"
METRIC_NAME = "FreshnessLagDays"

# D-PR-14. The normalized companion metric. NEVER a rename of METRIC_NAME -- see rule 1 above.
RATIO_METRIC_NAME = "FreshnessLagRatio"

# D-SG G3-1, 2026-08-16. THE THIRD METRIC, and the one the family alarm should have been reading
# all along.
#
# FreshnessLagDays{Family} is evaluated with statistic=Maximum against a threshold that
# jobs/observability/silver_alarms.py takes as min() over the family's member ceilings -- the
# family's SLOWEST member measured against its FASTEST member's ceiling. For a mixed-cadence
# family that is not a mis-tuning, it is arithmetically unsatisfiable: ``weather`` carries a 3d
# ceiling while silver_modis_ndvi is an 8-day composite sitting at 80.7d (measured 2026-08-16),
# so leviathan-dev-freshness-sla-breach-weather has been latched ALARM since 2026-07-30 while
# all four daily weather tables sat at 0.12-0.14d.
#
# FreshnessLagRatio (D-PR-14) normalizes per member but is STILL collapsed by Maximum, so it
# answers "how bad is the worst member" -- a real improvement, and still not the question the
# alarm asks. FreshnessBreachCount answers the question directly: how MANY member tables are
# past THEIR OWN declared ceiling. Alarm on >= 1 and the weather artifact dies without losing
# modis coverage (its own 45d table ceiling still counts it the day it is truly dead).
BREACH_METRIC_NAME = "FreshnessBreachCount"

# ---------------------------------------------------------------------------
# P6 / L7, 2026-09-22. THE DATA AXIS -- the fourth and fifth metrics, and the ONE instrument the
# 2026-09-22 pipeline census says would have caught six of its fourteen blockers.
#
# THE MECHANISM, stated as a fact rather than a fear. Everything above this block measures S3
# OBJECT MTIME. A producer that re-writes a byte-identical object on its fire cadence therefore
# reads 0.0 days forever WHILE ITS CONTENT IS DEAD. Measured by the census on 2026-09-21/22 from
# the live estate:
#
#   silver_sagis_weekly_exports  newest object 2026-09-18T12:21:08Z (FreshnessLagDays 3.01,
#                                ratio 0.158, GREEN) -- newest DATA date 2024-04-26: 879 days,
#                                46x its own 19-day ceiling.
#   silver_unica_corn_ethanol    newest object 2026-09-16T12:17:51Z -- newest DATA date
#                                2026-02-01: 233 days against a 14-day ceiling, 16.6x.
#   silver_unica_biweekly_season_history   233 days against 21: 11.1x.
#   silver_unica_monthly_ethanol_sales     325 days against 45: 7.2x.
#   silver_mpoc_stock_comparison           113 days against 45: 2.5x.
#
# Five stale-green tables the whole 52-alarm estate could not see, because all 52 alarms are on the
# WRITE axis. The DATA axis is what the reader is actually served.
#
# WHY THIS NAME AND NOT A NEW ONE: ``jobs/audit/silver_rebuild_gate.py:200`` already mints
# ``DataDateAgeDays`` and has emitted it since 2026-09-11. Inventing a second name for the same
# quantity would give the estate two vocabularies for one fact.
#
# AND THE DIMENSION SETS ARE DELIBERATELY DIFFERENT, which is the one trap in this block. The gate
# emits ``DataDateAgeDays`` with the COMPOSITE dimension set ``[{Table},{Family}]`` into this same
# namespace; the poller emits ``[{Table}]`` and ``[{Family}]`` SEPARATELY, exactly as it already
# emits FreshnessLagDays. In CloudWatch a metric's identity is (namespace, name, dimension SET), so
# those are THREE distinct series and neither emitter can ever overwrite the other's datapoint --
# which is the point. The gate reads the PG MIRROR through a SQL aggregate and only for the ten
# tables that are IN the mirror and only when that family's gate RUNS (so a gate-BLOCKED family
# emits nothing exactly when it matters); the poller reads the CANONICAL BYTES for every target on
# every cycle. Two different measurements of one quantity must never share one series: that is the
# "two copies of the loop drift silently" class this module's own header is about, and letting them
# collide would make the more reliable emitter indistinguishable from the less reliable one.
#
# An alarm on ``DataDateAgeRatio{Table=X}`` therefore reads the POLLER and only the poller.
DATA_DATE_METRIC_NAME = "DataDateAgeDays"

# The ceiling-normalized companion, for exactly the reason FreshnessLagRatio exists (D-PR-14): a
# raw day count cannot be thresholded across annual, monthly, fortnightly and daily tables at once,
# and **1.0 is the universal breach threshold** once each table is divided by its OWN ceiling.
DATA_DATE_RATIO_METRIC_NAME = "DataDateAgeRatio"

# THE BLINDNESS COUNTER, and the reason the per-table data-date alarms can safely be
# ``notBreaching``. A per-table alarm that treats MISSING as breaching would, on the day it is
# applied and before the poller image carrying the emitter ships, put ~35 alarms into ALARM on one
# terraform apply -- the exact hazard modules/silver_observability's own header names ("else the
# pre-emit families instant-breach the shared topic"). So the ABSENCE of a data-date reading is
# alarmed ONCE, here, as a count: ``DataDateUnread{Reason=unreadable}`` > 0 means a target whose
# axis IS declared could not be read this cycle. Absence is caught; nothing is fail-open; and the
# estate gains one alarm for that class instead of thirty-five.
DATA_DATE_UNREAD_METRIC_NAME = "DataDateUnread"

# P7. THE POLLER'S OWN TARGET COUNT, which it has printed on line 1 of every run since it was built
# and which NOTHING has ever read. MEASURED 2026-09-21: the scheduled poller printed
# "=== freshness_poller: 46 targets ===" while the repo registry enumerated 53 -- a baked image five
# weeks behind HEAD, invisible for five weeks. Three contracts added after the image (gold_board_crush,
# gold_futures_spreads, silver_psd_attributes, silver_pink_sheet_vintages) had ZERO datapoints over a
# 7-day window, and the RETIRED silver_esr write surface -- excluded in code since 2026-08-18 -- was
# still polled at ratio 2.34 and had latched leviathan-dev-freshness-breach-count-usda-esr ALARM since
# 2026-09-04, hiding the leg that actually serves.
#
# Emitting the count and generating its EXPECTED value from the same registry the poller reads turns
# five weeks of invisibility into one poll cycle. UNDIMENSIONED, on the
# ``ValueCensusHardFailTables`` precedent: an estate-wide scalar needs no dimension, and an alarm
# needs an EXACT dimension set.
TARGETS_POLLED_METRIC_NAME = "FreshnessTargetsPolled"

# How a target's newest DATA date is read. DECLARED per target from the F010 contract, never
# sniffed: a reader that guesses which column is the date axis is a reader that will one day read
# the wrong column and certify a dead table as fresh.
AXIS_PARTITION = "partition"      # the declared knowledge_date_col IS a partition key -> read the KEY
AXIS_COLUMN = "column"            # a physical column -> read the parquet FOOTER statistics
AXIS_UNDECLARED = "undeclared"    # knowledge_date_col is null -> NOTHING is read, and it is counted
# The contract declares a knowledge column AND declares its semantics to be INGEST -- i.e. that
# column records WHEN THE ROW WAS WRITTEN, not what period the row is about. Reading it as a data
# date would be the WRITE axis wearing the DATA axis's name, which is worse than not measuring:
# it would report a watched content axis where none exists. MEASURED on the 2026-09-22 read-only
# poll, before this mode existed -- all three ingest-semantics tables returned a "data" age within
# a day of their own FreshnessLagDays (silver_production data 27d vs lag 27.02d;
# gold_pattern_records data 36d vs lag 35.57d; silver_fnc_colombia_area_department 112d vs lag
# 35.05d, where the difference is only that its ingest_date column is itself stale). Excluded.
AXIS_INGEST = "ingest"

# A data date AHEAD of the clock is NOT evidence of freshness, and this estate has already paid
# for learning that on the other axis. ``silver_rebuild_gate.stage_data_freshness`` returns SKIPPED
# rather than GREEN when the bytes lead the promise, for a stated reason: a future date can mean a
# legitimately forward-stamped vintage OR a measurement clock reading earlier than the data, and a
# staleness reader cannot tell which -- "a staleness stage may never certify on a number it cannot
# interpret". MEASURED here on 2026-09-22: silver_nass_annual's declared axis (release_date) holds
# 2027-02-01, 132 days ahead, and a clamp-to-zero would have published DataDateAgeRatio 0.000 and
# certified it fresh forever off a scheduled future release date.
#
# One day of tolerance absorbs timezone and clock skew (the honest zero); beyond that the target
# publishes NO ``DataDateAgeRatio`` datapoint -- a future date is not a freshness figure and the
# gate's own ruling forbids certifying on a number that cannot be interpreted.
#
# IT IS NOT SILENT, THOUGH, AND THAT IS ROUND 2's CORRECTION (review M3, 2026-09-22). Round 1
# recorded AHEAD and alarmed nothing, so a table could leave the content watch without a sound:
# its per-table alarm is treat_missing_data="notBreaching" and therefore reads OK forever, and the
# blindness alarm was scoped to ``unreadable`` alone. The ruling: an AHEAD reading ALARMS. A
# knowledge row stamped in the future is one guard away from a point-in-time LEAK -- the whole
# evidence estate is built on "never serve a row whose knowledge date is after the question's
# as-of" -- so a forward-dated declared axis is a finding in its own right, not a shrug. See
# :data:`UNREAD_AHEAD` and ``silver_alarms.build_alarms``'s ``data_date_ahead``.
DATA_DATE_AHEAD_TOLERANCE_DAYS = 1.0

# The ``DataDateUnread`` reasons. TWO are alarmed -- UNREADABLE (the blindness class) and AHEAD
# (the forward-stamp class, round 2 / review M3). UNDECLARED is a repo fact (pinned by a unit test
# that names every undeclared contract, so the list can only shrink deliberately), STATIC is a
# declared, reasoned exclusion, ABSENT is already the write axis's loudest word, and DISABLED is
# the rollback switch announcing itself.
UNREAD_UNREADABLE = "unreadable"
UNREAD_UNDECLARED = "undeclared"
UNREAD_STATIC = "static"
# A canonical prefix with ZERO objects. Recorded, NOT alarmed, and the distinction is evidenced
# rather than convenient: an empty prefix is already the LOUDEST thing the write axis says -- the
# poller emits no FreshnessLagDays datapoint at all, ``is_breaching`` scores it a breach by
# construction, and the per-table alarms are treat_missing_data="breaching". A second voice on the
# data axis adds no information, and it would page forever on the two tables this estate
# DELIBERATELY keeps empty: silver_moex_agro_indices and silver_ams_gtr are registered ahead of
# their producers under the four-checkmark law and are, for that exact reason, already excluded
# from the write-axis alarm set (``silver_alarms.PRE_PUBLISH_FAMILIES``). Charging them as
# BLINDNESS would arm on the one alarm that has to stay believable.
UNREAD_ABSENT = "absent"
# The declared axis was READ and it points into the future past the tolerance. ALARMED on its own
# dimension since round 2 -- see DATA_DATE_AHEAD_TOLERANCE_DAYS for why. Kept DISTINCT from
# UNREADABLE rather than folded into it, because the two say different things and carry different
# remedies: UNREADABLE means the estate cannot see the number (fix the read), AHEAD means the
# estate CAN see it and the number is in the future (fix the contract, or the producer). Folding
# them would make one alarm mean two things, and an operator would learn to read neither.
#
# PRECEDENCE, stated once: AHEAD is charged even for a target that :data:`STATIC_DATA_TARGETS`
# excludes from the age alarm. A closed archive stamped in the future is exactly as leaky as a live
# one; a STALENESS exclusion may never suppress a LEAK guard.
UNREAD_AHEAD = "ahead"
# ``--no-data-date`` was passed: the whole content axis is dark BY SWITCH. Recorded and never
# alarmed, but it must be VISIBLE (review m2): round 1's rollback lever took 31 notBreaching
# per-table alarms plus the blindness alarm dark in one flag while ``FreshnessTargetsPolled`` went
# on reporting 53 either way -- i.e. the lever reproduced, exactly, the five-week silent blindness
# this whole leg was built to end. The value is the count of targets that WOULD have been read, so
# a reader can see the size of what was switched off, not merely that something was.
UNREAD_DISABLED = "disabled"

# THE CLOSED SET, in one place, so a reason cannot be invented in the poller and then never
# emitted: :func:`unread_metric_data` iterates THIS tuple and the poller's tally is asserted
# against it in the unit deck. A reason added here starts emitting (at zero) on the next cycle,
# which is what lets its alarm ever CLEAR.
UNREAD_REASONS: tuple[str, ...] = (
    UNREAD_ABSENT, UNREAD_AHEAD, UNREAD_DISABLED, UNREAD_STATIC,
    UNREAD_UNDECLARED, UNREAD_UNREADABLE,
)

# Canonical-only: the shadow/staging soak areas, the BACKUP areas and the tasks manifest are NOT
# canonical data, so a shadow-published table (which by SFN doctrine never advances canonical) can
# never look fresh.
#
# ``/_backup/`` added 2026-08-01 (EVIDENCE_INTEGRITY_WAVE_PLAN R7.2, ratified D-EI-12). MEASURED:
# the EXTRA_TARGETS prefix ``graphrag_evidence/timeline/`` already held
# ``_backup/episodes_20260704_prerebuild.json``, so a pre-rebuild BACKUP copy -- written by the
# copy-prefix discipline, not by a rebuild -- was resetting the artifact's measured age and would
# have made the FreshnessLagDays fence fail OPEN in exactly the direction it was built to close
# (and kept a datapoint flowing after a DELETED artifact, contra silver_alarms.py's
# treat_missing_data='breaching' design note). Excluded as a SEGMENT rather than by narrowing any
# one poll prefix so it generalises to every future backup convention, anywhere in the tree.
#
# ``/_manifests/`` added 2026-08-07 (D-PQ recon V2): ShadowPublisher writes its RUN MANIFEST under
# the canonical root even on SHADOW publishes, so a shadow-only run was resetting the canonical
# freshness clock -- the SILVER-F082 fail-open through a second door. MEASURED false-greens at
# discovery: nass_crop_progress reported 3.0d vs 66.9d true, unica_annual_state 1.9 vs 67.7,
# modis 11.0 vs 72.6, fnc x3 21.5 vs 66.0, fgis 0.9 vs 14.9 -- six tables under their ceilings
# on manifest mtimes alone. A manifest is bookkeeping, never canonical data.
_EXCLUDE_SEGMENTS = ("/_shadow/", "/_staging/", "/_backup/", "/_manifests/")
_EXCLUDE_SUFFIXES = ("_tasks.json",)


def is_excluded_key(key: str) -> bool:
    """True for a key that is NOT canonical data (shadow / staging / backup area or the tasks manifest)."""
    if any(seg in key for seg in _EXCLUDE_SEGMENTS):
        return True
    return any(key.endswith(sfx) for sfx in _EXCLUDE_SUFFIXES)


@dataclass(frozen=True)
class PrefixScan:
    """Everything ONE pass over a canonical prefix's listing can say, for BOTH freshness axes.

    ONE PASS, because the poller must never list a prefix twice: a second ``list_objects_v2`` walk
    over silver_chirps is ~1.4K extra requests per cycle for a number the first walk already had.
    And O(1) MEMORY: ``newest_written`` is a bounded heap, never the whole key list, so a table
    with a hundred thousand partitions costs the same as a flat one.

    * ``newest`` -- newest canonical ``LastModified`` (the WRITE axis; identical to what
      :func:`newest_last_modified` returned before this dataclass existed, and pinned to it).
    * ``canonical_objects`` -- how many keys survived :func:`is_excluded_key`.
    * ``newest_partition_value`` -- the lexicographic MAX of the requested Hive partition value
      across canonical keys (the DATA axis, read for free from the listing).
    * ``newest_written`` -- the ``keep_newest`` most-recently-written canonical keys, NEWEST FIRST.
      These are the objects a footer read samples."""

    newest: Optional[datetime] = None
    canonical_objects: int = 0
    newest_partition_value: Optional[str] = None
    newest_written: tuple[tuple[datetime, str], ...] = ()


def scan_prefix(
    objects: Iterable[tuple[str, datetime]],
    *,
    partition_col: Optional[str] = None,
    keep_newest: int = 0,
    exclude: Callable[[str], bool] = is_excluded_key,
) -> PrefixScan:
    """One canonical-only pass over a ``(key, last_modified)`` listing -> :class:`PrefixScan`.

    ``exclude`` is applied ONCE here and governs BOTH axes, deliberately: a shadow or ``/_backup/``
    key that may not reset the WRITE clock must not be allowed to supply a DATA date either. The
    four exclusion doors this estate has had to close (shadow, staging, backup, manifests) were all
    fail-OPEN on the write axis; a data axis that re-opened any of them would be a fifth."""
    newest: Optional[datetime] = None
    newest_part: Optional[str] = None
    count = 0
    heap: list[tuple[datetime, str]] = []
    for key, last_modified in objects:
        if exclude(key):
            continue
        count += 1
        if newest is None or last_modified > newest:
            newest = last_modified
        if partition_col:
            value = partition_value(key, partition_col)
            if value is not None and (newest_part is None or value > newest_part):
                newest_part = value
        if keep_newest > 0:
            heapq.heappush(heap, (last_modified, key))
            if len(heap) > keep_newest:
                heapq.heappop(heap)
    return PrefixScan(
        newest=newest,
        canonical_objects=count,
        newest_partition_value=newest_part,
        newest_written=tuple(sorted(heap, reverse=True)),
    )


def newest_last_modified(
    objects: Iterable[tuple[str, datetime]],
    exclude: Callable[[str], bool] = is_excluded_key,
) -> Optional[datetime]:
    """Newest ``LastModified`` across the canonical objects, or ``None`` for an empty/all-excluded prefix.

    ``objects`` is an iterable of ``(key, last_modified)`` pairs (exactly what an S3 ``list_objects_v2``
    page yields). Excluded keys never count toward the age -- neither a shadow write nor a BACKUP copy
    may reset the clock, however new it is and even when it is the only recent object under the prefix.

    Now one field of :func:`scan_prefix`, so the two axes can never disagree about which keys are
    canonical. The behaviour is unchanged and the pre-existing tests pin that."""
    return scan_prefix(objects, exclude=exclude).newest


def lag_days(newest: Optional[datetime], now: datetime) -> Optional[float]:
    """Age in days of the newest canonical object, or ``None`` when the prefix has no canonical data.

    Clamped at 0 so clock skew / an object stamped slightly in the future can never emit a negative
    lag (which would read as impossibly-fresh and suppress a real stall)."""
    if newest is None:
        return None
    days = (now - newest).total_seconds() / 86400.0
    return days if days > 0 else 0.0


# ---------------------------------------------------------------------------
# P6: THE DATA AXIS'S READERS. Pure, AWS-free, and deliberately REFUSING rather than guessing.
# ---------------------------------------------------------------------------
# THE ONE PLACE A DECLARED PARTITION COLUMN AND ITS S3 PATH SEGMENT ARE ALLOWED TO DIFFER.
#
# MEASURED 2026-09-22, and it is not a defect in either half. ``silver_esr_compact`` declares
# ``partition_keys = [commodity, as_of_date]`` and its 272 canonical keys spell the second segment
# ``as_of=`` -- e.g. ``silver/esr/commodity=all_rice/as_of=20260827/part-000.parquet``. The table is
# ``partition_mode: registered-partition``, and for a registered partition Glue stores the VALUE
# against an explicit LOCATION, so the Glue key name and the path spelling are independent BY
# DESIGN. The contract is right, S3 is right, and a reader that assumed they were the same string
# read nothing (measured: UNREADABLE, "no 'as_of_date=' partition segment", 272 canonical objects).
#
# WHY A DECLARATION AND NOT A SNIFF. Every alternative is a guess with a failure mode: matching a
# segment whose name is a PREFIX of the declared column would bind ``date`` to ``as_of_date``;
# taking "the segment that parses as a date" would silently follow a producer that added a second
# dated segment. This estate has a standing ruling against exactly that class -- the S7b round-5
# alias edit was green locally and moved a reader nobody was looking at.
#
# IT FAILS CLOSED IF IT ROTS. If the producer ever changes the path spelling, the override finds no
# segment, the target reads UNREADABLE and DataDateUnread{Reason=unreadable} pages -- the same
# outcome as having no override at all, which is the only rot behaviour a hand-written string is
# allowed to have. Pinned by the unit deck: every key here must be a live partition-axis target.
PARTITION_SEGMENT_OVERRIDES: dict[str, str] = {
    "silver_esr_compact": "as_of",
}


def partition_segment_of(table: str, column: str) -> str:
    """The S3 path-segment NAME carrying ``column``'s value for ``table`` -- the column itself
    unless :data:`PARTITION_SEGMENT_OVERRIDES` declares otherwise."""
    return PARTITION_SEGMENT_OVERRIDES.get(table, column)


def partition_value(key: str, column: str) -> Optional[str]:
    """The Hive partition value for ``column`` in an S3 ``key``, or ``None`` when absent.

    ``silver/wasde/release_date=2026-09-11/part-000.parquet`` + ``release_date`` -> ``2026-09-11``.
    Matched on a whole PATH SEGMENT, so a column named ``date`` can never match a segment named
    ``as_of_date=...`` and a value is never taken out of a file NAME."""
    needle = column + "="
    for segment in key.split("/"):
        if segment.startswith(needle):
            return segment[len(needle):]
    return None


def coerce_data_date(value) -> Optional[date]:
    """A declared data-date value -> a ``date``, or ``None`` when this function will not sign for it.

    The value arrives from exactly two places and both are UNTYPED at the call site: a Hive
    partition VALUE (always a string) and a parquet footer STATISTIC (``str`` for a UTF8 column,
    ``datetime.date`` for date32, ``datetime.datetime`` for a timestamp, ``int`` for an integer
    date). Every accepted spelling is listed here; anything else returns ``None`` and is counted as
    UNREADABLE rather than parsed on a hunch.

    ``None`` IS THE WHOLE POINT OF THE SIGNATURE. A freshness reader that falls back to "today" on
    an unparsed value certifies a dead table as fresh -- the precise failure the DATA axis exists to
    end -- and one that falls back to the epoch invents a 20,000-day breach out of a parse bug. It
    refuses instead, and the refusal is alarmed once, as a count."""
    if value is None:
        return None
    if isinstance(value, datetime):        # BEFORE date: datetime IS a date subclass
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except Exception:  # noqa: BLE001 -- an undecodable statistic is simply unreadable
            return None
    if isinstance(value, bool):            # BEFORE int: bool IS an int subclass
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    if not text:
        return None
    # YYYY-MM-DD, and the leading date of a "YYYY-MM-DD HH:MM:SS" / ISO timestamp.
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    if len(text) == 8 and text.isdigit():                      # YYYYMMDD
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    # A MONTH-GRAIN axis reads as the FIRST of its month, never the last: the first is the date the
    # month's data is ABOUT, and the last would silently make every monthly table ~30 days fresher
    # than it is -- a fail-OPEN of up to one whole cadence on exactly the tables (MPOB, MPOC, PSD)
    # whose ceilings are 45 days.
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        try:
            return date(int(text[:4]), int(text[5:]), 1)       # YYYY-MM
        except ValueError:
            return None
    if len(text) == 6 and text.isdigit():                      # YYYYMM
        try:
            return date(int(text[:4]), int(text[4:]), 1)
        except ValueError:
            return None
    return None


def data_age_days(newest_data_date: Optional[date], now: datetime) -> Optional[float]:
    """SIGNED whole days between the newest DATA date and ``now``; negative means the bytes LEAD
    the clock. ``None`` only when nothing was read.

    WHOLE DAYS, not fractional: a data date is a calendar fact with no time of day, so a fractional
    age would be an artifact of the poll's wall clock (the same reading would be 875.1 at 02:30Z and
    875.9 at 21:30Z). The gate's own ``DataDateAgeDays`` datapoints are whole numbers -- 875.0, 47.0,
    21.0 -- and an operator comparing the two emitters must not see a spurious difference.

    SIGNED, and deliberately NOT clamped the way :func:`lag_days` is. A negative WRITE lag can only
    be clock skew, so clamping it is the honest reading; a negative DATA age can be a genuinely
    forward-stamped vintage, and silently clamping THAT to 0 publishes "this table is perfectly
    fresh" off a release date four months in the future. :func:`is_ahead` is where that decision is
    taken, once, with a stated tolerance."""
    if newest_data_date is None:
        return None
    return float((now.astimezone(timezone.utc).date() - newest_data_date).days)


def is_ahead(age: Optional[float]) -> bool:
    """True when a data date leads the clock by more than :data:`DATA_DATE_AHEAD_TOLERANCE_DAYS`.

    An AHEAD target publishes NO data datapoint: neither green nor red, exactly as
    ``silver_rebuild_gate.stage_data_freshness`` returns SKIPPED rather than GREEN for the same
    input and for the same stated reason."""
    return age is not None and age < -DATA_DATE_AHEAD_TOLERANCE_DAYS


def data_date_axis(contract: dict) -> tuple[str, Optional[str]]:
    """``(mode, column)`` -- HOW this table's newest data date is read, DECLARED by its own contract.

    The declaration is the F010 registry's ``knowledge_date_col``, which every one of the 53
    contracts carries as a field and 38 of them populate. Precedence:

      1. the declared column IS one of the declared ``partition_keys`` -> :data:`AXIS_PARTITION`.
         Read from the S3 KEY, which costs NOTHING (the listing already happened), covers EVERY
         object under the prefix rather than a sample, and cannot be defeated by a writer that
         disabled parquet statistics.
      2. otherwise it is a physical column -> :data:`AXIS_COLUMN`, read from the parquet FOOTER.
      3. ``knowledge_date_col`` is null -> :data:`AXIS_UNDECLARED`. NOTHING is read and nothing is
         guessed. ``coverage_axis`` reads like a date axis ("year x month") but is free PROSE, and
         sniffing a column by name is how a reader ends up measuring the wrong one.

    MEASURED at HEAD: 38 tables declare an axis (2 of them a partition key), 15 do not. The 15 are
    named in a unit test, so the list can only shrink, and only deliberately."""
    column = contract.get("knowledge_date_col")
    if not column:
        return AXIS_UNDECLARED, None
    if contract.get("knowledge_semantics") == "ingest":
        return AXIS_INGEST, column
    keys = {k.get("name") for k in (contract.get("partition_keys") or [])}
    if column in keys:
        return AXIS_PARTITION, column
    return AXIS_COLUMN, column


# ---------------------------------------------------------------------------
# D-PR-14: the DENOMINATOR. Per-table declared freshness ceilings that DIVERGE from the registry
# derivation, mirroring the per-table alarms' own declared ceilings in
# ``jobs/observability/silver_alarms.py`` (BURNED_TABLE_FRESHNESS + ARTIFACT_FRESHNESS).
#
# WHY A MIRROR RATHER THAN AN IMPORT: ``src/leviathan/`` has ZERO imports from ``jobs/`` (measured),
# ``jobs`` is not even a package (no ``__init__.py``), and inverting that layering to read an alarm
# module from the pure core would be worse than the duplication. The mirror is TEST-PINNED instead:
# tests/unit/silver/test_freshness_poller.py loads silver_alarms.py by importlib and asserts that
# :func:`declared_ceiling_days` reproduces EVERY declared per-table ceiling exactly, so a drift on
# either side is a red test, not a silently wrong denominator. silver_alarms is the direction of
# truth; this dict follows it.
#
# MEASURED 2026-08-04: exactly ONE registry table diverges. The other three burned tables
# (silver_nass_crop_progress 14 via FRESHNESS_LAG_OVERRIDES, silver_fgis 14, silver_nass_citrus 400)
# already fall out of the registry derivation unchanged, so they are deliberately NOT listed here --
# an entry that merely restates the derivation is a second source of truth for nothing.
#
#   silver_unica_biweekly_season_history 21  A FORTNIGHTLY release series. The registry carries
#       cadence=weekly, so the derivation yields 14 -- and 14 is exactly the miscalibration D-PR-14
#       exists to kill: a NORMAL 16-day-old fortnightly drop would score ratio 1.14 and fire the
#       > 1.0 threshold. 21 = ~1 cycle (14d) + a half-cycle grace, so a single delayed drop is
#       tolerated and a MISSED cycle still breaches.
TABLE_CEILING_OVERRIDES: dict[str, int] = {
    "silver_unica_biweekly_season_history": 21,
}


def declared_ceiling_days(contract: dict) -> float:
    """The table's own declared freshness ceiling in days -- the DENOMINATOR of ``FreshnessLagRatio``.

    Precedence: an explicit :data:`TABLE_CEILING_OVERRIDES` entry (the per-table alarm's declared
    ceiling, which LOOSENS a cadence the registry records too tightly) > the registry derivation
    ``dag_catalog.effective_sla_lag_days``, TIGHTENED by ``dag_catalog.FRESHNESS_LAG_OVERRIDES``.

    That second clause is deliberately the SAME per-member quantity ``build_catalog`` computes
    immediately before collapsing it with ``min()`` -- the ratio is that collapse undone, applied
    per member, which is the whole of D-PR-14."""
    name = contract["table_name"]
    override = TABLE_CEILING_OVERRIDES.get(name)
    if override is not None:
        return float(override)
    lag, _basis = effective_sla_lag_days(contract)
    tighten = FRESHNESS_LAG_OVERRIDES.get(name)
    if tighten is not None and tighten < lag:
        lag = tighten
    return float(lag)


def lag_ratio(lag: Optional[float], expected: Optional[float]) -> Optional[float]:
    """``lag / expected`` -- the normalized age, so **> 1.0 is the universal breach threshold**.

    ``None`` (no ratio datapoint) when the prefix has no canonical data, when no ceiling is
    declared, or when the ceiling is non-positive. A non-positive ceiling is refused rather than
    divided by: ZeroDivisionError would kill the whole poll cycle, and all 26 day-based alarms are
    ``treat_missing_data='breaching'``, so one bad denominator would page 21 owners at once."""
    if lag is None or expected is None:
        return None
    expected = float(expected)
    if expected <= 0:
        return None
    return float(lag) / expected


@dataclass(frozen=True)
class PollTarget:
    """One table to poll: its canonical S3 location, the DAG family it aggregates into, and the
    table's own declared freshness ceiling in days (the ``FreshnessLagRatio`` denominator).

    ``expected_lag_days`` defaults to ``None`` so a hand-built target still emits the day metric;
    it simply gets no ratio datapoint (the alarm posture on the day metric is unchanged)."""

    table: str
    family: str
    bucket: str
    prefix: str  # normalized with a single trailing slash
    expected_lag_days: Optional[float] = None
    # P6, the DATA axis. ``data_date_mode`` defaults to UNDECLARED so a hand-built target (and
    # every EXTRA_TARGETS artifact) keeps exactly its pre-P6 behaviour: it emits the two write-axis
    # metrics and nothing else. Opting IN is a declaration; nothing is read by default.
    data_date_mode: str = AXIS_UNDECLARED
    data_date_col: Optional[str] = None
    static_reason: Optional[str] = None


# D-LD Track 2 #1 (2026-08-18, recon wf_14e22400 Lens C -- THE ESR ALARM INVERSION): tables whose
# Glue-derived s3_prefix points at a RETIRED write surface. The estate's loudest freshness breach
# (ratio 6.08 for the whole measured window) was silver_esr's contract prefix
# silver/production/source=usda_esr -- a leg holding exactly ONE frozen vintage (as_of=20260524)
# that NOTHING reads: the numbers card serves silver_esr_compact (athena_table redirect, the $134
# LIST-storm fix), the writer writes silver/esr/, and esr_compact carries its OWN poll target and
# ceiling. Polling a retired leg is worse than noise -- it is "FreshnessLagDays blind to dead legs"
# INVERTED: a permanent red that trains operators to ignore the family while the leg that actually
# serves breaches unwatched. Excluded here WITH the story; delete the entry if the surface is ever
# re-activated (the contract prefix is Glue-derived, so fixing Glue would also fix this).
RETIRED_WRITE_SURFACES: dict[str, str] = {
    "silver_esr": "pre-compact write surface, frozen at vintage 20260524; serving + writing both "
                  "moved to silver/esr/ (silver_esr_compact, its own poll target)",
}

# P6 / census THREAT T8, 2026-09-22. CLOSED ARCHIVES: no ALARM is generated for them, because the
# source has stopped publishing BY DECLARATION and a permanently-red alarm is how an estate teaches
# its operators to stop reading the board -- "a loud board nobody believes is the failure this whole
# census is about".
#
# THE MEASUREMENT IS KEPT. Round 1 claimed that in this very comment and did the opposite: the
# poller skipped the footer read for any target named here, so no ``DataDateAgeDays`` and no
# ``DataDateAgeRatio`` datum was emitted -- MEASURED on the 2026-09-22 13:33Z dry run, "data=STATIC"
# on all three lines with zero ``data_age_days=`` beside them -- and silver_mpoc_exports_by_country
# declares a real, readable axis (``knowledge_date_col: year_ending_date``, contract lines 69-70),
# so a live reading was being DELETED. That is the fence doctrine inverted, and it also made this
# block's own removal trigger unreachable: "delete the entry the day the source publishes again"
# cannot be observed by an instrument that is not looking. Round 2 (review M1): a static target
# whose axis is DECLARED is read and emits its age exactly like any other target, tagged STATIC in
# the log and counted under :data:`UNREAD_STATIC`; the ALARM exclusion, which is the whole point,
# already happens independently in :func:`data_date_alarm_targets` and is unchanged.
#
# THIS IS NOT A SUPPRESSION AND IT MUST NEVER BECOME ONE. The distinction that earns an entry here
# is between a source that HAS NO NEXT RELEASE and a source that is simply LATE:
#
#   * silver_nass_citrus is 438 days past a 400-day ceiling because NASS has published no 2025-26
#     season. It is LATE, not closed -- a next release exists -- so it is NOT here and it alarms.
#   * silver_sagis_weekly_exports is 879 days behind and its sibling deliveries leg is current: the
#     producer is alive and reads the wrong raw surface (census P9). NOT here, and it is the single
#     loudest reading the new axis will produce. Making it quiet would be deleting the finding.
#
# The removal trigger is a SINGLE observed release: delete the entry the day the source publishes
# again, and the alarm generator arms the table on its next run. Each entry carries the measured age
# at declaration so a reader can see how old the silence was when the judgement was made.
#
# Two of these three carry ``knowledge_date_col: null`` TODAY and would therefore read as UNDECLARED
# anyway -- which is exactly why they are listed. Lane 4 of this same wave is editing the mpoc
# descriptors; the moment one of them declares its axis, an unlisted entry becomes a 1,025-day alarm
# on a dead archive with nobody having decided that. The declaration is the interlock, not bookkeeping.
STATIC_DATA_TARGETS: dict[str, str] = {
    "silver_mpoc_trade_stats_monthly":
        "SOURCE CLOSED: MPOC publishes one monthly page per year and stopped after 2023-12; "
        "measured data age 1,025d at declaration (2026-09-22). knowledge_date_col is null today",
    "silver_mpoc_exports_by_country":
        "SOURCE CLOSED: annual exports-by-country page frozen at 2023-12-31; measured data age "
        "996d at declaration (2026-09-22)",
    "silver_unica_annual_state":
        "STATIC BY THE ENDPOINT'S OWN CEILING: UNICA's annual state series ends at harvest "
        "2020/2021 and the endpoint serves nothing later; knowledge_date_col is null today",
}


# P6 round 2 / review M3, 2026-09-22. THE FORWARD-STAMPED AXES THIS ESTATE ALREADY HAS, declared so
# the ``data_date_ahead`` alarm's first red is a KNOWN finding with a named remedy and not a
# surprise. THIS MAP SUPPRESSES NOTHING -- it is documentation that the alarm generator reads into
# the alarm's own description, because a threshold that excused the known set would be the
# round-1 silence wearing a number (and a forward-dated knowledge row is a point-in-time LEAK risk
# whether or not somebody expected it).
#
# The removal trigger is the CONTRACT changing, not the clock: delete an entry when the table's
# declared knowledge axis stops pointing into the future -- for NASS annual that means declaring a
# data-PERIOD column instead of ``release_date``, which is a SCHEDULED future release date and was
# never a knowledge date (raised to the NASS descriptor owner in HANDOFF H3).
DATA_DATE_AHEAD_KNOWN: dict[str, str] = {
    "silver_nass_annual":
        "declared axis is release_date = 2027-02-01, 132d AHEAD of the clock measured 2026-09-22; "
        "release_date is a SCHEDULED FUTURE RELEASE, not the period the rows describe. Remedy: "
        "declare a data-period column on the NASS annual contract",
}


def poll_targets(registry: Optional[SilverRegistry] = None) -> list[PollTarget]:
    """Every registry table that has an ``s3_prefix`` (+ ``s3_bucket``), with its DAG family resolved.

    A table without an ``s3_prefix`` is skipped (nothing to list). Family is the existing
    ``dag_catalog.family_of`` derivation, so the ``Family`` dimension the poller emits lines up
    one-to-one with the per-family ``freshness_sla_breach`` alarms. ``expected_lag_days`` is the
    table's OWN ceiling (:func:`declared_ceiling_days`) -- never the family's tightest one, which is
    what makes the family ``Maximum`` stop being poisoned by its slowest member (D-PR-14).
    Tables in :data:`RETIRED_WRITE_SURFACES` are skipped with their reason on record."""
    reg = registry or load_registry()
    targets: list[PollTarget] = []
    for name in reg.names():
        if name in RETIRED_WRITE_SURFACES:
            continue
        contract = reg.table(name)
        prefix = contract.get("s3_prefix")
        bucket = contract.get("s3_bucket")
        if not prefix or not bucket:
            continue
        mode, column = data_date_axis(contract)
        targets.append(
            PollTarget(
                table=name,
                family=family_of(name),
                bucket=bucket,
                prefix=prefix.rstrip("/") + "/",
                expected_lag_days=declared_ceiling_days(contract),
                data_date_mode=mode,
                data_date_col=column,
                static_reason=STATIC_DATA_TARGETS.get(name),
            )
        )
    return targets


# ---------------------------------------------------------------------------
# FENCE 2 leg 3 (incident I-2, 2026-07-31): NON-REGISTRY artifacts that still deserve a freshness
# clock. graphrag_evidence/timeline/episodes.json was built 2026-07-04 and nothing measured its age
# while the store it describes grew ~74%; the feature stayed on and shipped zero episodes silently.
#
# WHY NOT JUST REGISTER IT IN THE SILVER-F010 REGISTRY (the obvious "reuse the machinery" move):
# that is a CATEGORY ERROR. ``load_registry()`` also feeds ``build_catalog`` (which would mint a
# phantom DAG family and a phantom ``batch_job_failed`` alarm for a family with no Batch DAG), DDL
# generation, the value census, projection validation and readiness certification -- a GraphRAG
# serving artifact would start appearing in silver readiness certificates. It would also break
# tests/unit/silver/test_freshness_poller.py:123-127 (`len(targets) == len(reg.names())`).
#
# So ``poll_targets`` stays REGISTRY-PURE and the extras ride alongside. What IS reused is
# everything that matters: the metric contract (Leviathan/Silver :: FreshnessLagDays{Table}), the
# per-table alarm resource (modules/silver_observability/main.tf:253-270), the SNS topic, and the
# existing daily schedule -- no parallel freshness system is invented.
#
# bucket/prefix mirror jobs/utils/register_evidence_jobdef.py:22-24
# (EVIDENCE_S3 = s3://leviathan-dev-shahem-001/graphrag_evidence).
#
# ``expected_lag_days`` is declared LITERALLY here because the artifact is not in the registry, so
# there is no contract to derive from. 10 = the weekly timeline rebuild (cron 0 3 ? * SUN *) + a 3d
# grace, mirroring silver_alarms.ARTIFACT_FRESHNESS -- and pinned to it by the same test that pins
# TABLE_CEILING_OVERRIDES. D-PR-14 emitter-side only: no alarm, and the timeline alarm tfvars stay
# held by D-EI-12.
EXTRA_TARGETS: tuple[PollTarget, ...] = (
    PollTarget(
        table="graphrag_timeline_episodes",
        family="graphrag_evidence",
        bucket="leviathan-dev-shahem-001",
        # D-SG D12 / D-EI-12 CALIBRATION, 2026-08-16 -- POINTED AT THE HEARTBEAT, NOT THE
        # DIRECTORY. This is an S3 list PREFIX that happens to name one full key, so
        # list_objects_v2 returns exactly last_run.json and nothing else.
        #
        # WHY: the weekly rebuild runs ``--run-if-changed``, so on an UNCHANGED week it writes NO
        # episodes.json -- correctly, R7.1 -- and touches only the heartbeat. What is being
        # measured is SCHEDULE LIVENESS, never content churn, and the applied alarm's own basis
        # string in silver_observability.auto.tfvars.json has said exactly that since 2026-08-05
        # while the emitter still pointed at the directory.
        #
        # WHAT THE DIRECTORY PREFIX GOT WRONG, precisely: ``newest_last_modified`` takes the MAX
        # over the prefix, so today it happens to return last_run.json (2026-08-09T03:01Z,
        # measured lag 6.40d) because the heartbeat is newer than episodes.json
        # (2026-08-04T07:17Z). The reading is right by ACCIDENT. A run that writes the artifact
        # and then fails before stamping the heartbeat would reset the clock off the artifact and
        # read fresh -- the fail-open direction R7.2 closed for /_backup/, through a third door.
        # Naming the object makes the measurement a declaration instead of a coincidence.
        #
        # THE FAILURE MODE THIS TAKES ON, stated: if the heartbeat object is ever renamed or
        # moved, this prefix lists EMPTY, the poller emits no datapoint, and the
        # treat_missing_data="breaching" alarm fires within one day. That is the correct
        # direction (fail closed) and it is pinned by
        # tests/unit/silver/test_freshness_poller.py, which asserts this prefix against
        # leviathan.graphrag.timeline's own ``_HEARTBEAT`` constant rather than a hand-copied
        # literal.
        prefix="graphrag_evidence/timeline/last_run.json",
        expected_lag_days=10.0,
    ),
)


def all_poll_targets(registry: Optional[SilverRegistry] = None) -> list[PollTarget]:
    """Every registry poll target PLUS the non-registry artifacts of :data:`EXTRA_TARGETS`.

    This is what the poller runs. ``poll_targets`` is left untouched and registry-pure so the
    registry-coverage pin (test_freshness_poller.py:123) keeps meaning what it says."""
    return poll_targets(registry) + list(EXTRA_TARGETS)


def metric_data_for(
    table: str,
    family: str,
    lag: float,
    *,
    timestamp: datetime,
    expected: Optional[float] = None,
) -> list[dict]:
    """CloudWatch ``MetricDatum`` dicts for one table's lag, dimensioned ``[Table]`` and ``[Family]``.

    The ``[Table]`` datapoint feeds the precise per-table alarm; the ``[Family]`` datapoint feeds the
    coarse per-family alarm (statistic=Maximum, so the family reads its stalest member). ``Unit`` is
    ``None`` -- CloudWatch has no "days" unit and the alarm thresholds are bare day counts.

    Returns TWO datums (``FreshnessLagDays`` x {Table, Family}) always, and FOUR when ``expected``
    yields a ratio -- the two extra being ``FreshnessLagRatio`` on the SAME two dimensions
    (D-PR-14). The day-based datums are byte-identical either way: the ratio is emitted ALONGSIDE,
    never instead of, because a rename would orphan all 26 live ``FreshnessLagDays`` alarms in one
    poll cycle. ``expected=None`` (or a non-positive ceiling) is a normal, non-fatal state -- the
    table simply keeps only its day metric."""
    base = {
        "MetricName": METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(lag),
        "Unit": "None",
    }
    data = [
        {**base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ]
    ratio = lag_ratio(lag, expected)
    if ratio is None:
        return data
    ratio_base = {
        "MetricName": RATIO_METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(ratio),
        "Unit": "None",
    }
    data.extend([
        {**ratio_base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**ratio_base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ])
    return data


def data_metric_data_for(
    table: str,
    family: str,
    age: float,
    *,
    timestamp: datetime,
    expected: Optional[float] = None,
) -> list[dict]:
    """``DataDateAgeDays`` (+ ``DataDateAgeRatio``) datums for one table -- the DATA-axis twin of
    :func:`metric_data_for`, with the SAME two-single-dimension grammar and the same alongside rule.

    THE DENOMINATOR IS THE TABLE'S OWN ``declared_ceiling_days``, the identical number
    ``FreshnessLagRatio`` divides by, and that reuse is the deliberate part. ``effective_sla_lag_days``
    builds it as *cadence default + publication_lag_days grace* -- and on THIS axis that grace is
    finally in its right home. ``dag_catalog.FRESHNESS_LAG_OVERRIDES`` and the D-LD ruling on
    silver_fgis both exist because a CONTENT lag wired into a WRITE-RECENCY ceiling LOOSENS the alarm
    it looks like it tightens ("the two numbers protect different things and must not be summed").
    The data axis is the content axis: "the newest data may be one cadence plus the source's own
    publication delay old" is exactly what a data-date ceiling should say, so no threshold is invented
    here and no existing one moves. The census computed this estate's worst readings with precisely
    this arithmetic -- 879/19 = 46.3 for silver_sagis_weekly_exports, 233/14 = 16.6 for
    silver_unica_corn_ethanol -- and those two numbers are this function's acceptance test.

    ``Unit`` is ``"None"``: the poller's own grammar for a bare day count, unchanged from
    :func:`metric_data_for`. (The gate stamps its composite-dimension series ``"Count"``; the two
    never meet -- see the DATA_DATE_METRIC_NAME block.)"""
    base = {
        "MetricName": DATA_DATE_METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(age),
        "Unit": "None",
    }
    data = [
        {**base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ]
    ratio = lag_ratio(age, expected)
    if ratio is None:
        return data
    ratio_base = {
        "MetricName": DATA_DATE_RATIO_METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(ratio),
        "Unit": "None",
    }
    data.extend([
        {**ratio_base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**ratio_base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ])
    return data


def unread_metric_data(counts: dict[str, int], *, timestamp: datetime) -> list[dict]:
    """One ``DataDateUnread{Reason}`` datum per reason in :data:`UNREAD_REASONS`, reason-ordered.

    EVERY reason is emitted on every cycle, INCLUDING at zero -- the same discipline
    :func:`breach_counts` applies for the same reason: an alarm that receives a datapoint only
    while it is breaching can never CLEAR, and a healthy estate that stopped emitting would be
    indistinguishable from a healthy estate."""
    return [
        {
            "MetricName": DATA_DATE_UNREAD_METRIC_NAME,
            "Timestamp": timestamp,
            "Value": float(counts.get(reason, 0)),
            "Unit": "Count",
            "Dimensions": [{"Name": "Reason", "Value": reason}],
        }
        for reason in UNREAD_REASONS
    ]


def targets_polled_metric_data(polled: int, *, timestamp: datetime) -> list[dict]:
    """The single UNDIMENSIONED ``FreshnessTargetsPolled`` datum -- how many targets this cycle read.

    Undimensioned on the ``ValueCensusHardFailTables`` precedent, because the alarm compares it
    against a count the ALARM GENERATOR writes from the same registry the poller reads. A baked
    image behind the repo then announces itself in ONE cycle instead of the five weeks it took in
    2026-08/09 (46 polled against 53 declared)."""
    return [{
        "MetricName": TARGETS_POLLED_METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(polled),
        "Unit": "Count",
        "Dimensions": [],
    }]


# ---------------------------------------------------------------------------
# P8 / L7 ROUND 3, 2026-09-22. LEDGER LIVENESS GAUGES -- A DAILY AGE FOR A LEG THAT FIRES
# MONTHLY, AND THE CLOUDWATCH BOUND THAT FORCED THE SHAPE.
#
# THE DEFECT THIS EXISTS FOR IS AN API CONTRACT, NOT A TASTE. Round 2 asked "did the MONTHLY fold
# fire?" with an M-of-N alarm over THIRTY-FIVE daily periods (SampleCount of CorpusFoldRuns,
# period 86400 x evaluation_periods 35). CloudWatch cannot create that alarm. botocore's own
# CloudWatch service model says so in PutMetricAlarm.Period, quoted verbatim from
# botocore/data/cloudwatch/2010-08-01/service-2.json.gz:
#
#     "An alarm's total current evaluation period can be no longer than seven days, so Period
#      multiplied by EvaluationPeriods can't be more than 604,800 seconds."
#
# 86,400 x 35 = 3,024,000 s = 5.0x the ceiling, so `terraform apply` would have failed with a
# ValidationError on a shape five unit tests certified as delivered -- and the same ceiling was
# breached by envs/dev/schedule_corpus.tf's corpus_lane_liveness at 86,400 x 10 = 864,000 s, which
# sat INSIDE a 52-add plan handed to the owner. Corroborated against the live account the same day:
# of 75 metric alarms the MAXIMUM Period x EvaluationPeriods is 86,400. Nothing in this estate has
# ever created a longer window, because nothing can.
#
# THE RULING (owner, 2026-09-22): LIVENESS OF A MONTHLY PROCESS IS A DAILY GAUGE. The poller reads
# the leg's own LEDGER once a cycle and emits its AGE IN DAYS; the alarm is ONE daily evaluation of
# that age against the cadence-derived bound. 86,400 x 1 = 86,400 s -- inside the ceiling by a
# factor of seven -- with the SAME semantics ("no fold in 35 days"), one property the M-of-N shape
# never had (it CLEARS on the next fold instead of needing 35 clean days), and one fewer dependency
# (the gauge is emitted by the DAILY poller, so it does not need the monthly job to be alive in
# order to report that the monthly job is dead).
#
# WHY THE POLLER AND NOT THE JOB. A job can only emit while it runs. "It did not run" is exactly
# the datapoint a dead job cannot publish, which is why round 2 reached for treat_missing_data and
# a 35-day window in the first place. A daily gauge inverts it: the reporter is alive every day and
# the NUMBER carries the silence.
CLOUDWATCH_MAX_EVALUATION_SECONDS: int = 7 * 24 * 3600   # 604,800 -- the quote above


# The ledger objects are written ONCE PER FIRE at the end of the fire, so the object's LastModified
# IS that fire's end within seconds. A gauge therefore costs ONE paginated LIST per cycle and
# issues NO GetObject at all -- no parse, no schema, no new IAM (the poller already lists this
# bucket for graphrag_timeline_episodes).
#
# THIS IS NOT THE WRITE-MTIME BLINDNESS THE DATA AXIS EXISTS TO END. That class is a producer
# re-writing a BYTE-IDENTICAL object on its cadence while its CONTENT is dead. A ledger's write IS
# the event being measured: a new fire writes a new ledger line, and a fire that does not happen
# writes nothing at all.
@dataclass(frozen=True)
class LedgerGauge:
    """One daily AGE gauge over a periodic leg's own durable ledger.

    ``prefix`` is an S3 LIST prefix that normally names ONE full key (the EXTRA_TARGETS precedent);
    ``fallback_prefix`` is read ONLY when the primary lists empty, and it must measure the SAME
    event by a different artifact -- never a softer question wearing this one's name.
    ``threshold_days`` is the bound the alarm reads, so the number in the alarm and the number in
    this declaration are ONE number."""

    key: str                      # gauge id: the log line, the deck, the handoff
    metric_name: str              # Leviathan/Silver :: <metric>{Family}
    family: str                   # the ONE constant dimension
    bucket: str
    prefix: str
    threshold_days: float         # the alarm's GreaterThanThreshold bound
    cadence: str                  # the schedule it is derived from, in words
    basis: str                    # WHY the threshold is this number and not a preference
    alarmed_by: str               # where the alarm resource lives, so neither half goes orphan
    fallback_prefix: Optional[str] = None
    fallback_note: str = ""
    # THE SOURCE OF THE AGE, and it is the difference between an instrument and a blindfold.
    #
    # None      -> the object's LastModified. Correct ONLY where the write IS the event: a ledger
    #              is written once per fire, so its mtime is that fire's end within seconds.
    # "<col>"   -> the newest Hive PARTITION VALUE of that column under the prefix. Correct where
    #              the objects are CONTENT whose keys carry their own date, and MANDATORY there:
    #              measured on text/source=usda_wasde/ on 2026-09-22, the newest object mtime is
    #              2026-08-20 (33.2 days, GREEN at a 40-day bound) while the newest release_date
    #              partition is 2026-08-12 (41.0 days, RED) -- the 2026-08-20 mtimes are a bulk
    #              re-write of documents whose release dates are months older. That is exactly the
    #              write-mtime blindness the P6 data axis exists to end, arriving through a third
    #              door, and it is why this field is declared per gauge instead of assumed.
    partition_key: Optional[str] = None


LEDGER_GAUGES: tuple[LedgerGauge, ...] = (
    LedgerGauge(
        key="corpus_fold",
        metric_name="CorpusFoldAgeDays",
        family="graphrag_evidence",
        bucket="leviathan-dev-shahem-001",
        # jobs/batch/corpus_fold_task.FOLD_LEDGER_SUFFIX = "fold/last_run.json", written at the END
        # of every fire on every outcome (green chain, failed chain, refused backup).
        prefix="graphrag_evidence/fold/last_run.json",
        # THE FALLBACK IS WHY THIS GAUGE IS READABLE TODAY. Measured read-only 2026-09-22:
        # graphrag_evidence/fold/ lists EMPTY (the ledger ships in an image whose pin predates it),
        # while eval/write_manifest_rebuild_20260821T212319Z.json is there at 2026-08-21T21:23:20Z.
        # The rebuild manifest is the fold's OWN durable record of the same event and predates the
        # ledger, so the gauge reads ~31.9d today instead of UNREADABLE.
        fallback_prefix="graphrag_evidence/eval/write_manifest_rebuild_",
        fallback_note="rebuild manifest (the fold's own write record), read ONLY when the ledger "
                      "prefix lists empty",
        threshold_days=35.0,
        cadence="monthly, cron(0 8 22 * ? *)",
        basis="the longest HEALTHY gap between two fires is 31 days (22 Jul -> 22 Aug), so 31 "
              "quiet days must not page; 35 is that worst case plus a four-day grace and can only "
              "be reached by a MISSED fire. A 30-day bound would go red across every 31-day month "
              "pair. Derived by the text/corpus lane and UNCHANGED by the reshape: round 2 spent "
              "the 35 as evaluation PERIODS, which CloudWatch refuses; it is spent here as 35 DAYS "
              "OF AGE, which is the same statement inside the API's bound.",
        alarmed_by="jobs/observability/silver_alarms.py::build_alarms "
                   "(failure_mode corpus_fold_liveness)",
    ),
    LedgerGauge(
        key="corpus_chunk",
        metric_name="CorpusChunkAgeDays",
        family="graphrag_evidence",
        bucket="leviathan-dev-shahem-001",
        # leviathan.graphrag.corpus_coverage.LEDGER_SUFFIX = "coverage/ledger.json", written at the
        # chunk pass's commit point on EVERY outcome that reaches a ledger -- the quiet ones
        # (NOTHING_TO_DO, NO_CANDIDATES, ALL_CACHED) included, which is what makes a missing object
        # mean "no fire recorded anything" instead of "a quiet week".
        prefix="graphrag_evidence/coverage/ledger.json",
        # NO FALLBACK, and the absence is a statement. chunks/ and _batches/ objects are written
        # only when a pass finds NEW work, so their newest mtime answers "when did the corpus last
        # GROW", never "when did the pass last RUN". Measured 2026-09-22: coverage/ lists EMPTY, so
        # this gauge is UNREADABLE until the first chunk fire from a current image writes its
        # ledger. That is the alarm's apply gate, stated -- not a defect.
        threshold_days=10.0,
        cadence="weekly (the corpus-chunk schedule)",
        basis="a healthy weekly cadence leaves at most 6 consecutive quiet days, so 10 days of age "
              "is ONE missed fire and can never be a healthy week -- the same 'weekly + 3d grace' "
              "basis the timeline rebuild's ceiling already uses (EXTRA_TARGETS, 10.0). Round 2 "
              "spent the 10 as daily evaluation PERIODS (864,000 s), which CloudWatch refuses; the "
              "age gauge spends it as 10 DAYS.",
        alarmed_by="infra/terraform/envs/dev/schedule_corpus.tf::corpus_lane_liveness "
                   "(the text/corpus lane's file; re-shaped in round 3 and handed back in "
                   "HANDOFF_L7_observability.md)",
    ),
    LedgerGauge(
        key="wasde_text",
        metric_name="WasdeTextAgeDays",
        family="usda_wasde",
        bucket="leviathan-dev-shahem-001",
        prefix="text/source=usda_wasde/",
        # THE PARTITION, NEVER THE MTIME -- handed by the text/corpus lane with the measurement
        # (H-L5-R3-2) and reproduced here read-only on 2026-09-22: 876 objects under this prefix,
        # newest mtime 2026-08-20T06:17:11Z (33.2d, GREEN at 40) and newest release_date partition
        # 2026-08-12 (41.0d, RED). The mtime form of this gauge would have read green on the exact
        # estate state the text lane was opened to end.
        partition_key="release_date",
        threshold_days=40.0,
        cadence="monthly (releases land on the 9th-12th); the chain fires on days 8-13, "
                "cron(0 18 8-13 * ? *)",
        basis="WASDE publishes monthly, so the longest HEALTHY gap between two release dates is 31 "
              "days and 31 days of tip age must not page; 40 is that worst case plus a nine-day "
              "grace, which leaves room for a correction re-issue. Derived by the text/corpus lane "
              "(H-L5-R3-2) against the defect that opened it: the tip stood at 41 days, so the "
              "bound catches the live condition by ONE day. A 35-day bound would also hold and is "
              "tighter; 40 is the number the ruling named.",
        alarmed_by="jobs/observability/silver_alarms.py::build_alarms "
                   "(failure_mode wasde_text_tip_stale)",
    ),
)


def ledger_gauge(key: str) -> LedgerGauge:
    """The one gauge with this key. Raises rather than returning None: every caller names a
    constant, so a miss is a typo and a typo must be loud."""
    for g in LEDGER_GAUGES:
        if g.key == key:
            return g
    raise KeyError(f"no LedgerGauge named {key!r}; declared: {[g.key for g in LEDGER_GAUGES]}")


def ledger_metric_data(gauge: LedgerGauge, age_days: float, *, timestamp: datetime) -> list[dict]:
    """The ONE datum a ledger gauge publishes: ``<metric>{Family} = age in days``.

    One dimension and one datum, matching the corpus lane's own family-rolled grammar. ``Unit`` is
    ``"None"`` -- this poller's grammar for a bare day count, identical to :func:`metric_data_for`
    and :func:`data_metric_data_for`.

    There is deliberately NO datum on the failure path. A fabricated 0 would read as "the fold ran
    today" and a fabricated 999 would invent a measurement nobody made. The failure is PRINTED and
    the alarm's ``treat_missing_data = "breaching"`` owns the silence -- the same contract the 26
    write-axis alarms have carried since F082."""
    return [{
        "MetricName": gauge.metric_name,
        "Timestamp": timestamp,
        "Value": float(age_days),
        "Unit": "None",
        "Dimensions": [{"Name": "Family", "Value": gauge.family}],
    }]


def alarm_window_seconds(period_seconds: int, evaluation_periods: int) -> int:
    """``Period x EvaluationPeriods`` -- the number CloudWatch caps at
    :data:`CLOUDWATCH_MAX_EVALUATION_SECONDS`."""
    return int(period_seconds) * int(evaluation_periods)


def refuse_uncreatable_window(label: str, period_seconds: int, evaluation_periods: int) -> None:
    """Raise ``ValueError`` if this (period, evaluation_periods) pair is one PutMetricAlarm refuses.

    A GENERATOR'S REFUSAL IS A SIGNAL. The round-2 defect was not that somebody chose 35 periods;
    it was that NOTHING between that choice and `terraform apply` could say no -- not the document,
    not the tfvars, not five green unit tests, not a plan that exited 0. This is that no, and it
    fails CLOSED: an alarm definition CloudWatch would refuse is never minted at all.

    It corrects nothing on its own -- the remedy is a SHAPE change and the message names it --
    because the alternative (silently clamping 35 periods to 7) would ship an alarm that says
    something other than what its author wrote, which is the deletion class wearing a fix's hat."""
    window = alarm_window_seconds(period_seconds, evaluation_periods)
    if window > CLOUDWATCH_MAX_EVALUATION_SECONDS:
        raise ValueError(
            f"{label}: period_seconds {period_seconds} x evaluation_periods {evaluation_periods} "
            f"= {window:,} s exceeds the PutMetricAlarm maximum of "
            f"{CLOUDWATCH_MAX_EVALUATION_SECONDS:,} s (seven days). CloudWatch REFUSES this alarm, "
            f"so terraform apply fails with a ValidationError. When the question is 'has this leg "
            f"fired in N days' and N > 7, the shape is a DAILY AGE GAUGE and not an M-of-N window: "
            f"emit <Leg>AgeDays once a cycle (see LEDGER_GAUGES) and alarm it at period 86400 x 1 "
            f"evaluation > N."
        )


def data_date_alarm_targets(registry: Optional[SilverRegistry] = None) -> dict[str, tuple[str, float, str]]:
    """``{table: (family, ceiling_days, basis)}`` -- every target that EARNS a data-date alarm.

    THE ONE SOURCE the alarm generator reads, and it lives here rather than in
    ``jobs/observability/silver_alarms.py`` deliberately. ``TABLE_CEILING_OVERRIDES`` above is a
    MIRROR of that module's declared per-table ceilings and needs a test to keep the two honest,
    because ``src/leviathan/`` may not import ``jobs/``. This set has no such problem: it is a pure
    function of the registry, so the generator IMPORTS it and there is exactly one copy. A table
    cannot gain a data-date alarm without gaining a data-date reading, by construction.

    A target is in when it (a) is polled at all, (b) DECLARES a data-date axis, and (c) is not a
    declared closed archive. It is out when its axis is undeclared -- nothing would ever feed the
    alarm -- or when :data:`STATIC_DATA_TARGETS` names it, which is the T8 fence against a board
    that is permanently red on archives nobody expects to move."""
    out: dict[str, tuple[str, float, str]] = {}
    for t in all_poll_targets(registry):
        if t.data_date_mode in (AXIS_UNDECLARED, AXIS_INGEST) or t.static_reason is not None:
            continue
        if not t.expected_lag_days or t.expected_lag_days <= 0:
            continue
        out[t.table] = (
            t.family,
            float(t.expected_lag_days),
            f"axis={t.data_date_mode}:{t.data_date_col}; ceiling={t.expected_lag_days:.0f}d "
            f"(declared_ceiling_days, the same denominator FreshnessLagRatio uses)",
        )
    return out


def data_date_undeclared_tables(registry: Optional[SilverRegistry] = None) -> list[str]:
    """Every polled target with NO declared data-date axis, sorted -- the repo's own blind list.

    Pinned by name in the unit deck so the list can only shrink, and only when somebody declares
    ``knowledge_date_col`` on purpose. A contract added with a null axis is otherwise invisible in
    exactly the way ``silver_psd_attributes`` was invisible for five weeks."""
    return sorted(t.table for t in all_poll_targets(registry)
                  if t.data_date_mode in (AXIS_UNDECLARED, AXIS_INGEST))


def is_breaching(lag: Optional[float], expected: Optional[float]) -> bool:
    """True when this table is past its OWN declared ceiling -- the per-member breach predicate.

    THE EMPTY PREFIX COUNTS AS A BREACH (``lag is None``), and that is load-bearing rather than
    convenient. The poller emits NO ``FreshnessLagDays`` datapoint for a table whose canonical
    prefix has zero objects; today that absence is caught only by ``treat_missing_data =
    'breaching'`` on the per-TABLE alarm, which exactly five tables have. The family breach-count
    datapoint is written on EVERY poll cycle, so scoring an empty prefix 0 here would make the
    replacement metric strictly WEAKER than the metric it replaces -- the failure mode this
    estate keeps re-learning.

    A table with no declared ceiling (``expected`` None or non-positive) CANNOT breach and scores
    0; :func:`breach_counts` still counts it as a member so the family keeps emitting."""
    if lag is None:
        return True
    ratio = lag_ratio(lag, expected)
    if ratio is None:
        return False
    return ratio > 1.0


def breach_counts(
    rows: Iterable[tuple[str, Optional[float], Optional[float]]],
) -> dict[str, int]:
    """``{family: number of member tables past their own ceiling}``, for EVERY family seen.

    ``rows`` is ``(family, lag_days_or_None, expected_or_None)`` -- one row per polled table.

    A family with zero breaches is present with value 0, DELIBERATELY. An alarm that only
    receives a datapoint while it is breaching can never CLEAR, and the breach-count alarms are
    ``treat_missing_data = 'breaching'`` (a poller that dies must page), so a healthy family that
    stopped emitting would page within one evaluation period."""
    counts: dict[str, int] = {}
    for family, lag, expected in rows:
        counts.setdefault(family, 0)
        if is_breaching(lag, expected):
            counts[family] += 1
    return counts


def breach_metric_data(counts: dict[str, int], *, timestamp: datetime) -> list[dict]:
    """One ``FreshnessBreachCount{Family}`` MetricDatum per family, ordered by family name.

    ``Unit`` is ``"Count"`` -- unlike the two lag metrics (which are bare day numbers CloudWatch
    has no unit for), this one really is a count of things."""
    return [
        {
            "MetricName": BREACH_METRIC_NAME,
            "Timestamp": timestamp,
            "Value": float(counts[family]),
            "Unit": "Count",
            "Dimensions": [{"Name": "Family", "Value": family}],
        }
        for family in sorted(counts)
    ]
