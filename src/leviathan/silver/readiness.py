"""Per-table readiness certification core (SILVER-F080) + the global R4 certificate
(SILVER-F083).

WHY THIS EXISTS
---------------
The original readiness campaign could certify a table GREEN while it shipped all-NaN
values (CHIRPS) or a single collapsed vintage (ESR), and it conflated "the producer
machinery is ready" with "the canonical data is current." This module keeps the FOUR
tracks the plan distinguishes strictly separate, so the certificate is HONEST: it names
exactly which correctness dimension is red for each table and which B-wave / R-package
work order closes it.

THE FOUR TRACKS (plan L785, L805)
---------------------------------
* PRODUCER      -- fetcher+transform+jobdef discoverable in the F010 registry, plus the
                   R2/R3 shadow-cert evidence where the table was (re)produced. An orphan
                   whose registry producer entrypoint is still null is BLOCKED even if
                   R3 built the code, because the registry has not adopted it yet.
* CATALOG       -- registry<->Glue<->DDL coherence: the R1 reconciliation lints
                   (unallowed divergences), the F011 DDL diff (physical-only / hidden
                   schema, order drift), and placeholder-partition cleanup.
* CURRENT_DATA  -- the V001 value census verdict (all-NaN / single-vintage / floor) plus
                   the V002 value_nonnull posture. A table with no census record at all is
                   BLOCKED-BY SILVER-V001 (the R4 DoD requires all 41 to have one).
* FRESHNESS     -- newest-object age vs the registry freshness_sla and the
                   silver.ingest_date >= bronze.ingest_date contract. Evaluated at B1-B3
                   by plan design, so with no R4 probe it is DEFERRED (non-green, but not a
                   table-specific defect); a KNOWN-stale table is BLOCKED-BY its B-wave.

HONESTY INVARIANT
-----------------
This core is PURE, AWS-free, and deterministic (no clock, no I/O). A table with a planned
or waived defect renders as ``BLOCKED-BY:<package>`` -- never silently green. ``CERTIFIED``
requires every applicable track PASS; the plan's R4 target ``BACKFILL_READY`` requires
producer+catalog+current-data PASS with freshness deferred to the B-waves. The global
certificate is ``signed=False`` here (the KMS milestone-boundary signature is a human step)
and goes GREEN only when zero tables are BLOCKED -- which is NOT the case today.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# Track + verdict vocabulary.
# ---------------------------------------------------------------------------
TRACK_PRODUCER = "producer"
TRACK_CATALOG = "catalog"
TRACK_CURRENT_DATA = "current_data"
TRACK_FRESHNESS = "freshness"
TRACKS = (TRACK_PRODUCER, TRACK_CATALOG, TRACK_CURRENT_DATA, TRACK_FRESHNESS)

PASS = "PASS"          # certified green
FAIL = "FAIL"          # red with no owning work order identified (generic)
BLOCKED = "BLOCKED"    # red, mapped to a named work-order package (the B-wave order)
DEFERRED = "DEFERRED"  # not evaluated at R4 by plan design (freshness w/o probe): non-green
NA = "NA"              # not applicable (value census on the generated ML table)

_NON_GREEN = frozenset({FAIL, BLOCKED})           # states that force a table BLOCKED
_OK_TRACK = frozenset({PASS, NA})                  # states that do not hold a table back

# Table readiness rollup states.
CERTIFIED = "CERTIFIED"            # all applicable tracks PASS (value current + fresh)
BACKFILL_READY = "BACKFILL_READY"  # producer+catalog+current-data PASS; freshness deferred
GENERATION_READY = "GENERATION_READY"  # the generated ML table (value census NA)
STATE_BLOCKED = "BLOCKED"          # >=1 track red -> rendered BLOCKED-BY:<pkgs>

# Work-order fallbacks when the evidence carries no more specific package.
WO_V001 = "SILVER-V001"
WO_BF_W1 = "BF-W1"
WO_BF_W2 = "BF-W2"
WO_BF_W3 = "BF-W3"
WO_F018 = "SILVER-F018"
WO_RECONCILE = "SILVER-F010-reconcile"
WO_CATALOG = "SILVER-F016"     # adopt hidden physical schema into the catalog
WO_PRODUCER = "SILVER-V002"    # producer-coverage contract (fetcher+transform+jobdef)

_PKG_RE = re.compile(r"SILVER-F0\d{2}")

# V001 gate-kind -> the backfill wave that repairs it.
_KIND_TO_WAVE = {
    "all_nan": WO_BF_W1,
    "nonnull_below_floor": WO_BF_W1,
    "sentinel_saturated": WO_BF_W1,
    "stats_unavailable": WO_BF_W1,
    "single_vintage": WO_BF_W2,
}


# ---------------------------------------------------------------------------
# Result model.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TrackResult:
    """One track's verdict for one table. ``blocking`` are the work-order package ids a
    reviewer must close; empty when PASS/NA."""

    track: str
    verdict: str
    blocking: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def is_green(self) -> bool:
        return self.verdict in _OK_TRACK

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "verdict": self.verdict,
            "blocking": list(self.blocking),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TableEvidence:
    """Raw, primitive inputs for one table's four tracks. Built by the runner from the
    registry + the R1/R2/R3 report artifacts; built directly by the unit tests. All fields
    are plain scalars/tuples so a synthetic record is trivial to construct."""

    table: str
    is_ml: bool = False
    # --- producer ---
    producer_status: str = "producer"          # producer | half-orphan | orphan
    transform: Optional[str] = None
    batch_task: Optional[str] = None
    shadow_cert_ok: Optional[bool] = None       # R2/R3 shadow-cert bit-for-bit result
    producer_package: Optional[str] = None       # R3 package that closes an orphan
    # --- catalog ---
    reconcile_divergences: tuple = ()            # unallowed divergence dicts {check,kind,detail}
    catalog_drift_rows: tuple = ()               # {dimension,disposition,detail,package}
    placeholder_partition_count: int = 0
    catalog_migration_package: Optional[str] = None
    # --- current-data (value census) ---
    census_present: bool = False
    census_passed: Optional[bool] = None
    census_gate_kinds: tuple = ()
    current_data_package: Optional[str] = None   # explicit BF-W1/BF-W2 override
    # --- freshness ---
    freshness_probe: Optional[dict] = None       # {silver_ingest_date,bronze_ingest_date,newest_age_days}
    max_lag_days: Optional[int] = None
    staleness_package: Optional[str] = None       # known-stale -> BF-W1/BF-W2


@dataclass(frozen=True)
class TableCertificate:
    table: str
    readiness_state: str
    label: str
    blocking: tuple[str, ...]
    tracks: tuple[TrackResult, ...]

    def track(self, name: str) -> TrackResult:
        for t in self.tracks:
            if t.track == name:
                return t
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "package": "SILVER-F080",
            "readiness_state": self.readiness_state,
            "label": self.label,
            "blocking": list(self.blocking),
            "tracks": {t.track: t.to_dict() for t in self.tracks},
        }


# ---------------------------------------------------------------------------
# Track evaluators (each pure; each returns a single TrackResult).
# ---------------------------------------------------------------------------
def evaluate_producer(ev: TableEvidence) -> TrackResult:
    """Producer readiness: a discoverable fetcher/transform/jobdef in the F010 registry,
    corroborated by shadow-cert where the table was (re)produced in R2/R3.

    An orphan/half-orphan whose registry entrypoint is still null is BLOCKED even when R3
    built the producer code -- the registry has not adopted it, and the canonical catch-up
    is BF-W3. A generated ML table legitimately carries a null batch_task."""
    reasons: list[str] = []
    blocking: list[str] = []

    if ev.producer_status in ("orphan", "half-orphan"):
        pkg = ev.producer_package or WO_PRODUCER
        blocking.append(pkg)
        blocking.append(WO_BF_W3)
        note = (f"registry producer.status={ev.producer_status} with null entrypoint "
                f"(R3 {pkg} builds it; canonical catch-up is BF-W3)")
        if ev.shadow_cert_ok is True:
            note += "; shadow-cert GREEN but registry producer field not yet repointed"
        reasons.append(note)
        return TrackResult(TRACK_PRODUCER, BLOCKED, tuple(blocking), tuple(reasons))

    if not ev.transform:
        blocking.append(ev.producer_package or WO_PRODUCER)
        reasons.append("no producer.transform entrypoint discoverable in the registry")
        return TrackResult(TRACK_PRODUCER, BLOCKED, tuple(blocking), tuple(reasons))

    if ev.shadow_cert_ok is False:
        reasons.append("shadow-cert REGRESSED (bit-for-bit reproduction failed)")
        return TrackResult(TRACK_PRODUCER, BLOCKED, (ev.producer_package or WO_PRODUCER,),
                           tuple(reasons))

    # transform is discoverable -> producer code is present. A null batch_task on a
    # status=producer table is a discoverability NOTE (the table runs via a shared
    # submit-batch / orchestrate_backfill entrypoint, not a dedicated jobdef), not a hard
    # block -- the producer artifact itself is reproducible.
    note = "transform discoverable"
    if not ev.batch_task and not ev.is_ml:
        note += "; no dedicated batch_task jobdef recorded (shared submit/orchestrator entrypoint)"
    if ev.shadow_cert_ok is True:
        note += "; shadow-cert green"
    reasons.append(note)
    return TrackResult(TRACK_PRODUCER, PASS, (), tuple(reasons))


def evaluate_catalog(ev: TableEvidence) -> TrackResult:
    """Catalog coherence: reconciliation lints + F011 DDL diff (hidden schema / order) +
    placeholder-partition cleanup + any pending catalog migration."""
    reasons: list[str] = []
    blocking: list[str] = []

    for d in ev.reconcile_divergences:
        blocking.append(WO_RECONCILE)
        reasons.append(f"reconcile {d.get('check')}::{d.get('kind')}: {d.get('detail')}")

    for row in ev.catalog_drift_rows:
        dim = row.get("dimension")
        disp = (row.get("disposition") or "")
        # Cosmetic/formatting or already-FIXED registry-bug rows do not block the catalog.
        if dim in ("formatting",) or "FIXED" in disp:
            continue
        pkg = row.get("package") or _parse_pkg(row.get("detail")) or WO_CATALOG
        blocking.append(pkg)
        reasons.append(f"DDL diff {dim} ({disp}): {row.get('detail')}")

    if ev.placeholder_partition_count > 0:
        blocking.append(WO_F018)
        reasons.append(f"{ev.placeholder_partition_count} placeholder partition(s) pending cleanup")

    if ev.catalog_migration_package:
        blocking.append(ev.catalog_migration_package)
        reasons.append(f"pending catalog migration {ev.catalog_migration_package}")

    if blocking:
        return TrackResult(TRACK_CATALOG, BLOCKED, _dedupe(blocking), tuple(reasons))
    return TrackResult(TRACK_CATALOG, PASS, (),
                       ("registry<->Glue<->DDL coherent (reconcile clean, DDL diff cosmetic)",))


def evaluate_current_data(ev: TableEvidence) -> TrackResult:
    """Current-data readiness from the V001 value census + V002 value_nonnull posture.

    * generated ML table                 -> NA (no value contract)
    * no census, table not published yet -> BLOCKED-BY the publishing wave (see below)
    * no census record at all            -> BLOCKED-BY SILVER-V001 (R4 DoD needs all 41)
    * census FAIL (all-NaN / single-vintage / floor) -> BLOCKED-BY the mapped B-wave
    * census PASS                        -> PASS
    """
    if ev.is_ml:
        return TrackResult(TRACK_CURRENT_DATA, NA, (),
                           ("generated ML predictions carry no value_columns contract",))
    if not ev.census_present:
        # A table registered AHEAD of its producers (the F010 contract lands first so the schema is
        # ratified, generated and linted before a single object exists -- silver_futures_eod,
        # PRICE_AND_PLAYBOOKS W1.0) has NOTHING to census: there are no canonical objects. That is
        # still BLOCKED and still red -- it is never silently green, and it is never faked with a
        # {"passed": true} census entry -- but attributing it to SILVER-V001 would be wrong: V001 is
        # "run the census on data that exists", and the work order that actually closes this row is
        # the wave that PUBLISHES the table. The runner supplies that package explicitly (a curated
        # map), so an ordinary uncensused table still lands on V001.
        if ev.current_data_package:
            return TrackResult(TRACK_CURRENT_DATA, BLOCKED, (ev.current_data_package,),
                               ("registered ahead of its producer: no canonical objects exist yet, so "
                                "no value census is possible; the publishing wave "
                                f"({ev.current_data_package}) closes this",))
        return TrackResult(TRACK_CURRENT_DATA, BLOCKED, (WO_V001,),
                           ("no value_census.json for this table; the R4 exit criterion "
                            "requires a census for every non-ML table (SILVER-V001)",))
    if ev.census_passed is False:
        pkg = ev.current_data_package or _wave_for_kinds(ev.census_gate_kinds)
        kinds = ", ".join(ev.census_gate_kinds) or "value-census hard fail"
        return TrackResult(TRACK_CURRENT_DATA, BLOCKED, (pkg,),
                           (f"value census FAIL ({kinds})",))
    return TrackResult(TRACK_CURRENT_DATA, PASS, (),
                       ("value census green (no all-NaN / single-vintage / floor breach)",))


def evaluate_freshness(ev: TableEvidence) -> TrackResult:
    """Freshness: newest-object age vs freshness_sla + silver.ingest_date >= bronze.

    Evaluated at B1-B3 by plan design, so with no R4 probe this is DEFERRED (non-green but
    not a table-specific defect). A known-stale table, or a probe showing silver older than
    bronze / past its SLA, is BLOCKED-BY its B-wave."""
    if ev.staleness_package:
        return TrackResult(TRACK_FRESHNESS, BLOCKED, (ev.staleness_package,),
                           (f"known-stale silver; catch-up is {ev.staleness_package}",))

    probe = ev.freshness_probe
    if probe:
        s = probe.get("silver_ingest_date")
        b = probe.get("bronze_ingest_date")
        if s is not None and b is not None and str(s) < str(b):
            pkg = ev.staleness_package or WO_BF_W1
            return TrackResult(TRACK_FRESHNESS, BLOCKED, (pkg,),
                               (f"silver ingest_date {s} < bronze ingest_date {b} "
                                f"(skip-existing declined a newer bronze)",))
        age = probe.get("newest_age_days")
        if ev.max_lag_days is not None and age is not None and age > ev.max_lag_days:
            return TrackResult(TRACK_FRESHNESS, BLOCKED, (WO_BF_W1,),
                               (f"newest object age {age}d > freshness_sla {ev.max_lag_days}d",))
        return TrackResult(TRACK_FRESHNESS, PASS, (),
                           ("silver >= bronze and within freshness_sla",))

    return TrackResult(TRACK_FRESHNESS, DEFERRED, (),
                       ("freshness is evaluated at B1-B3 (no R4 newest-object probe); "
                        "current canonical data is not rebuilt by R0-R4",))


# ---------------------------------------------------------------------------
# Table + global rollups.
# ---------------------------------------------------------------------------
def certify_table(ev: TableEvidence) -> TableCertificate:
    tracks = (
        evaluate_producer(ev),
        evaluate_catalog(ev),
        evaluate_current_data(ev),
        evaluate_freshness(ev),
    )
    by = {t.track: t for t in tracks}
    blocking = _dedupe([b for t in tracks for b in t.blocking])

    prod_ok = by[TRACK_PRODUCER].verdict == PASS
    cat_ok = by[TRACK_CATALOG].verdict == PASS
    data_v = by[TRACK_CURRENT_DATA].verdict          # PASS | NA | BLOCKED
    fresh_v = by[TRACK_FRESHNESS].verdict             # PASS | DEFERRED | BLOCKED

    any_red = any(t.verdict in _NON_GREEN for t in tracks)

    if ev.is_ml:
        # The generated table: value census NA, freshness deferred. Green iff the machinery
        # (producer + catalog) is clean.
        state = GENERATION_READY if (prod_ok and cat_ok) else STATE_BLOCKED
    elif any_red:
        state = STATE_BLOCKED
    elif all(t.verdict == PASS for t in tracks):
        state = CERTIFIED
    elif prod_ok and cat_ok and data_v == PASS and fresh_v == DEFERRED:
        # The plan's R4 target: machinery + values certified; the freshness catch-up is the
        # by-design B-wave. Ready to be backfilled, not yet current.
        state = BACKFILL_READY
    else:
        state = STATE_BLOCKED  # fail closed on any shape we did not explicitly bless

    label = f"BLOCKED-BY:{','.join(blocking)}" if state == STATE_BLOCKED else state
    return TableCertificate(ev.table, state, label, tuple(blocking), tracks)


def certify_all(evidence: Sequence[TableEvidence]) -> dict[str, Any]:
    """Build the global R4 Backfill-Ready certificate (SILVER-F083).

    Distinguishes the five correctness dimensions the plan requires and rolls the BLOCKED
    tables up into a ``work_orders`` map -- literally the B-wave backlog. Deterministic:
    inputs sorted, no clock. ``signed`` is always False here (KMS signing is a human
    milestone-boundary step); GREEN requires zero BLOCKED tables."""
    certs = [certify_table(ev) for ev in sorted(evidence, key=lambda e: e.table)]

    by_state: dict[str, list[str]] = {}
    for c in certs:
        by_state.setdefault(c.readiness_state, []).append(c.table)

    # work_orders: package -> the tables it unblocks (sorted, deterministic).
    work_orders: dict[str, list[str]] = {}
    for c in certs:
        for pkg in c.blocking:
            work_orders.setdefault(pkg, []).append(c.table)
    work_orders = {k: sorted(v) for k, v in sorted(work_orders.items())}

    # Per-track dimension tallies (producer / catalog / value-current-data / freshness).
    dims: dict[str, dict[str, int]] = {}
    for tr in TRACKS:
        counts: dict[str, int] = {}
        for c in certs:
            v = c.track(tr).verdict
            counts[v] = counts.get(v, 0) + 1
        dims[tr] = dict(sorted(counts.items()))

    blocked_tables = sorted(by_state.get(STATE_BLOCKED, []))
    verdict = "GREEN" if not blocked_tables else "RED"

    return {
        "package": "SILVER-F083",
        "certificate": "R4 Backfill-Ready",
        "verdict": verdict,
        "signed": False,
        "signing_note": ("KMS milestone-boundary attestation is a human step (INV-9); this "
                         "harness never self-signs. GREEN requires zero BLOCKED tables."),
        "table_count": len(certs),
        "state_counts": {k: len(v) for k, v in sorted(by_state.items())},
        "tables_by_state": {k: sorted(v) for k, v in sorted(by_state.items())},
        "correctness_dimensions": {
            "producer": dims[TRACK_PRODUCER],
            "catalog": dims[TRACK_CATALOG],
            "value_current_data": dims[TRACK_CURRENT_DATA],
            "freshness": dims[TRACK_FRESHNESS],
        },
        "blocked_tables": blocked_tables,
        "work_orders": work_orders,
        "tables": {c.table: c.to_dict() for c in certs},
        "honesty_note": ("Red rows are the B-wave work orders. current_data + freshness are "
                         "not rebuilt by R0-R4; producer orphans await R3 registry adoption + "
                         "BF-W3. This certificate must not be GREEN until those close."),
    }


# ---------------------------------------------------------------------------
# helpers.
# ---------------------------------------------------------------------------
def _parse_pkg(detail: Optional[str]) -> Optional[str]:
    if not detail:
        return None
    m = _PKG_RE.search(detail)
    return m.group(0) if m else None


def _wave_for_kinds(kinds: Sequence[str]) -> str:
    for k in kinds:
        if k in _KIND_TO_WAVE:
            return _KIND_TO_WAVE[k]
    return WO_BF_W1


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return tuple(sorted(seen))
