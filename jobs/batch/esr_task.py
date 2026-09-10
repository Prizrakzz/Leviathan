"""USDA FAS Export Sales Reporting (ESR) raw -> bronze Batch task.

Processes raw ESR JSON files from S3 raw/ and writes per-(commodity, year,
as_of_date) bronze Parquets.

Key design
----------
Two raw key shapes exist:

  Backfill  raw/production/source=usda_esr/
                commodity_code={code}/market_year={year}/all_countries.json
  Weekly    raw/production/source=usda_esr/
                commodity_code={code}/market_year={year}/as_of={YYYYMMDD}/all_countries.json

THE VINTAGE LAW (C-F1, 2026-09-04)
----------------------------------
A bronze partition's ``as_of`` comes from the RAW KEY, or from the raw object's
``raw_meta`` sidecar -- **never from today's date**.  ``silver_esr_compact`` is
the per-week point-in-time surface (INV-3); a vintage stamped "today" onto an
undated payload is a point-in-time that never existed, and it is indistinguishable
downstream from a real one.

Resolution order, one implementation (:func:`resolve_as_of`):

  1. the key's own ``as_of=YYYYMMDD`` segment      -> provenance ``raw_key``
  2. an EXPLICIT ``--backfill-as-of YYYYMMDD``     -> provenance ``operator``
  3. ``raw_meta/<raw_key>_meta.json``'s ``download_timestamp`` date, i.e. the day
     the bytes were actually fetched                -> provenance ``raw_meta``
  4. nothing  -> the key is REFUSED (counted, logged, never written)

Undated (backfill-shaped) raw keys are OUT OF SCOPE unless ``--include-backfill``
is passed.  MEASURED 2026-09-04 on ``s3://leviathan-dev-shahem-001``: the raw
prefix holds 1,901 JSON objects, of which 446 carry an ``as_of=`` segment and
1,455 do not.  Before this law the undated 1,455 were admitted by every run and
stamped with the run date, so a scheduled weekly fire minted a whole fabricated
vintage; now the default run touches only the 446 dated keys.

S3 key structure
----------------
  Bronze: bronze/production/source=usda_esr/
              commodity_code={code}/
              market_year={year}/
              as_of={YYYYMMDD}/
              part-000.parquet

Targeted re-bronze (``--as-of-min``)
------------------------------------
Bronze is strictly INCREMENTAL: ``_process`` returns ``"skipped"`` whenever the
bronze key already exists and ``--force-overwrite`` was not passed, and the
scheduled chain passes no ``--force-overwrite``.  So a transform change reaches
FUTURE as_of partitions only; vintages already bronzed by the old transform keep
the old column set forever.

A blanket ``--force-overwrite`` is the wrong tool for that: it would rewrite the
ENTIRE bronze history purely to add all-NULL columns to raw payloads that never
carried the fields.  So ``--force-overwrite`` REQUIRES ``--as-of-min``: there is
no default bound, because a default bound is a default that selects everything.
``--as-of-min YYYYMMDD`` narrows the rewrite to the vintages whose RAW actually
carries the new fields -- a bound that is MEASURED, never assumed.  For the
SILVER-F030 BF-W2 net-commitment five that measurement is
``jobs/utils/esr_netcommitment_raw_census.py``, which read all 446 dated raw
objects on 2026-09-04 and found every one of the 12 as_of vintages carrying all
five keys, so the bound is the earliest vintage raw holds:

    python jobs/batch/esr_task.py --force-overwrite --as-of-min 20260712

The bound is judged on the key's OWN ``as_of=`` segment.  An undated key has no
vintage to compare, so it is DROPPED from a bounded run (counted as
``dropped_undated=``) unless the operator both passes ``--include-backfill`` and
declares the vintage with ``--backfill-as-of``; the combination without the
declaration is refused rather than silently judged on a fetched-per-key date.

Read the terminal line: ``written=0`` means the filter matched nothing and any
measurement downstream of the run is vacuous; ``refused=`` counts admitted keys
whose vintage could not be resolved honestly.

THE AS_OF LAW'S TRIPWIRES -- COUNTER-ONLY SHADOW (``LEVIATHAN_ESR_ASOF_TRIPWIRE``)
----------------------------------------------------------------------------------
These two checks LOG WHAT THEY WOULD REFUSE AND REFUSE NOTHING.  No key is
dropped, no exit code moves, no byte changes.  They are instruments, and the
promotion from counter to gate is a separate, owner-gated step.

**3a -- OPEN-MARKETING-YEAR FRESHNESS.**  For a ``(commodity_code, market_year)``
that is the OPEN marketing year, flag ``max(week_ending_date)`` more than 8 days
before the vintage's derived release boundary.  The conditioning is not optional
and the measurement says why: applied FLAT to the 64 raw keys of ``as_of=20260903``
the same 8-day rule refuses **25 of 64 (39 %)**, and every single refusal is a
legitimately CLOSED marketing year -- codes 101-107/201/301/601/1001/1101 at
MY2026 (max week_ending 2026-06-04, lag 91 d) and the cotton/rice complex
1201/1301/1401-1404/1498/1499/1501-1505 at MY2026 (2026-08-06, lag 28 d).  An
absolute lag bound is a CLOSED-MARKETING-YEAR DETECTOR, not a staleness detector,
and it degrades monotonically: every closed MY recedes another 7 days from every
future release.  Conditioned on the open MY the refusal set on the 20260904 raw
set falls from **25 of 64 to 2 of 64** (``1001/MY2026`` and ``106/MY2026``, the
honest edge cases to adjudicate).

**3b -- NON-REGRESSION AGAINST THE PRIOR VINTAGE.**  For every ``(commodity_code,
market_year)``, ``max(week_ending_date)`` must not go BACKWARDS versus the most
recent prior vintage of the same pair.  This is the check that catches the real
defect and nothing in the estate does it today: corn ``401/MY2026`` went
``2026-08-27 -> 2026-05-14`` between the ``as_of=20260903`` and ``as_of=20260904``
bronze vintages built from **ETag-identical raw** (2,491 rows -> 1,734 rows;
28,035 B -> 22,026 B).  The truncation is in the raw->bronze leg, from identical
source bytes -- an OPEN DEFECT this task does not fix and this tripwire only
surfaces.  It is the more dangerous of the two ESR findings, because without a
sibling vintage to compare against a truncated partition is invisible.

POSTURE, SAID PLAINLY BECAUSE IT IS THE ONE MECHANISM IN THIS CHANGE THAT IS NOT
DEFAULT-OFF: an unset ``LEVIATHAN_ESR_ASOF_TRIPWIRE`` means ``shadow``, so this
instrument counts and logs on every weekly fire from the moment it lands.  That
is deliberate -- a counter that must be armed measures nothing, and the shadow is
counter-only: ``report_tripwires``' return value is discarded at its single call
site, no finding touches ``errors``, and neither ``sys.exit`` site's condition
changed shape from HEAD's (pinned structurally, on the parse tree, in
``tests/unit/silver/test_esr_vintage_stream.py``).  ``off`` is the way back and
it is the only way back: an unrecognised value falls through to ``shadow`` and
says so, because a typo must not be able to silently disable an instrument.

Cost, stated because it is I/O added to a live weekly job:

  ``off``           evaluate nothing.
  ``shadow``        DEFAULT.  3a and 3b from data already in hand -- zero extra
                    S3 calls.  3b then compares only against prior vintages this
                    run itself observed, which is a re-bronze run, not a weekly
                    one.
  ``shadow-prior``  additionally reads ONE prior bronze object per written pair
                    (``week_ending_date`` column only) so 3b is exact on a
                    single-vintage weekly fire.  ~1,478 extra GETs on a weekly
                    fire, against the 1,478 raw GETs the run already makes.

DELIBERATELY NOT COVERED: the release-date DERIVATION itself still lives at the
fetch (``jobs/ingest/fetch_usda_esr.py``, where the ``--as-of`` default launders
``datetime.date.today()`` into the key name); here the reference is the vintage
LABEL the key already carries, floored to its release boundary.  Retiring the
20260904 sibling, relabelling the three un-paired non-Thursday vintages, and the
raw->bronze truncation defect are all owner-gated work in their own lane.

Usage
-----
    python jobs/batch/esr_task.py [--bucket B] [--aws-region R]

Targeted re-bronze of the vintages that carry a newly-promoted field:
    python jobs/batch/esr_task.py --force-overwrite --as-of-min 20260712

Backfill (undated) keys, dated from their raw_meta sidecars:
    python jobs/batch/esr_task.py --include-backfill

Smoke test (first 5 files):
    python jobs/batch/esr_task.py --limit 5
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import pyarrow.parquet as pq
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

logger = get_logger("esr_task")

_RAW_PREFIX = "raw/production/source=usda_esr/"
# The raw_meta sidecar the fetcher writes next to every raw object
# (leviathan.storage.raw_metadata.write_raw_s3_metadata): raw_meta/<raw_key>_meta.json.
_RAW_META_PREFIX = "raw_meta/"
_WORKERS = 16

_BRONZE_PREFIX = "bronze/production/source=usda_esr/"

# Matches the as_of partition in a weekly raw key, e.g. "as_of=20260522"
_AS_OF_RE = re.compile(r"as_of=(\d{8})")
# The leading YYYY-MM-DD of the sidecar's ISO-8601 download_timestamp, e.g. "2026-07-12T13:02:44Z".
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# ---------------------------------------------------------------------------
# THE AS_OF LAW'S TRIPWIRES -- counter-only shadow (module docstring).
# ---------------------------------------------------------------------------
_TRIPWIRE_ENV = "LEVIATHAN_ESR_ASOF_TRIPWIRE"
TRIPWIRE_OFF, TRIPWIRE_SHADOW, TRIPWIRE_SHADOW_PRIOR = "off", "shadow", "shadow-prior"

# FAS ESR publishes weekly on Thursday ~12:30Z. Monday=0 in date.weekday().
_ESR_RELEASE_WEEKDAY = 3
# Clause 3a's bound. 8 days, not 7: a release covers the week ending the Saturday before it, so a
# healthy open-MY pair sits 5-7 days back and 8 is the first value that is unambiguously late.
_OPEN_MY_MAX_LAG_DAYS = 8

# MIRROR of jobs/ingest/fetch_usda_esr.py's marketing-year groups (:160-166). It is a mirror and
# not an import because these jobs run standalone -- `python jobs/batch/esr_task.py` puts
# jobs/batch on sys.path, not the repo root, and the fetcher pulls `requests`, which the bronze
# image need not carry. The estate's existing remedy for exactly this class (the Glue job and the
# Airflow DAG mirror the fetcher's commodity universe) is a test that pins every mirror EQUAL to
# the fetcher; tests/unit/silver/test_esr_vintage_stream.py does that here, behaviourally, over
# all 44 codes of the measured source universe.
_WHEAT_CODES = frozenset({101, 102, 103, 104, 105, 106, 107, 201})
_COTTON_CODES = frozenset({1201, 1202, 1203, 1301, 1401, 1402, 1403, 1404})
_RICE_CODES = frozenset({1498, 1499, 1501, 1502, 1503, 1504, 1505})

# ``shadow-prior``'s SEED index is written from _WORKERS threads. The GIL makes each store atomic
# but not the read-modify-write, so the seed is chosen under this lock and by a RULE rather than by
# arrival: see _record_prior. Not a collection -- it does not enter the F091 census.
_PRIORS_LOCK = threading.Lock()


def tripwire_mode(env=None) -> str:
    """``off`` | ``shadow`` (default) | ``shadow-prior``. Counter-only in every mode.

    THE ONE MECHANISM IN THIS CHANGE THAT IS NOT DEFAULT-OFF, said plainly because it changes the
    default behaviour of a live weekly job: an unset ``LEVIATHAN_ESR_ASOF_TRIPWIRE`` yields
    ``shadow``, which counts and logs on every fire. Design section 3 permits that because the
    shadow is counter-only -- ``report_tripwires``' return value is discarded at the single call
    site and no finding touches ``errors`` or either ``sys.exit`` -- and because ``shadow`` costs
    zero extra S3 calls. ``off`` is the way back. An UNRECOGNISED value also lands on ``shadow``
    (never on ``off``: an instrument must not be disabled by a typo), and says so in the log
    rather than falling through in silence.
    """
    raw = str((env if env is not None else os.environ).get(_TRIPWIRE_ENV, "")).strip().lower()
    if raw in {"off", "0", "false", "no"}:
        return TRIPWIRE_OFF
    if raw in {TRIPWIRE_SHADOW_PRIOR, "prior"}:
        return TRIPWIRE_SHADOW_PRIOR
    if raw not in {"", TRIPWIRE_SHADOW, "1", "true", "yes", "on"}:
        logger.warning(
            "%s=%r is not a recognised mode (off | shadow | shadow-prior) -- falling through to "
            "%s, which refuses nothing. Set it to 'off' to silence the instrument.",
            _TRIPWIRE_ENV, raw, TRIPWIRE_SHADOW,
        )
    return TRIPWIRE_SHADOW


def _record_prior(
    priors_out: dict | None,
    commodity_code: int,
    market_year: int,
    got: tuple[str, date],
) -> None:
    """Record ONE pair's out-of-run predecessor for 3b's seed, deterministically.

    A run that holds several vintages of the same pair (a re-bronze, never the weekly single-vintage
    fire this mode is meant for) computes a "prior" once per vintage, and the later vintages' priors
    are IN-RUN objects. Arrival order would then decide the seed. The EARLIEST candidate is the one
    that actually precedes the run, so that is the one kept -- 3b walks the in-run timeline itself
    from there. Advisory either way: a wrong seed can only SUPPRESS a finding on a multi-vintage
    re-bronze, never invent one.
    """
    if priors_out is None:
        return
    with _PRIORS_LOCK:
        current = priors_out.get((commodity_code, market_year))
        if current is None or got[0] < current[0]:
            priors_out[(commodity_code, market_year)] = got


def esr_release_on_or_before(day: date) -> date:
    """Floor a date to the FAS ESR release boundary at or before it (the most recent Thursday).

    Clause 2's derivation, as a pure function. A Friday 08:19Z re-run of the 2026-09-03 release
    floors to 20260903 and overwrites that partition; it mints no sibling. Used here only as the
    tripwires' REFERENCE -- this task changes no key.
    """
    return day - timedelta(days=(day.weekday() - _ESR_RELEASE_WEEKDAY) % 7)


def _marketing_year_start_month(commodity_code: int) -> int:
    """Mirror of the fetcher's :func:`_marketing_year_start_month`."""
    if commodity_code in _WHEAT_CODES:
        return 6  # Jun 1
    if commodity_code in _COTTON_CODES or commodity_code in _RICE_CODES:
        return 8  # Aug 1
    return 9  # Sep 1 (corn, soybeans, sorghum, oilseeds, livestock, hides)


def open_marketing_year(commodity_code: int, reference_date: date) -> int:
    """Mirror of the fetcher's :func:`_current_marketing_year`: the MY containing *reference_date*."""
    return (reference_date.year
            if reference_date.month >= _marketing_year_start_month(commodity_code)
            else reference_date.year - 1)


class BronzeVintageObservation(NamedTuple):
    """One bronze object as the tripwires see it. Built from the frame already in hand.

    NamedTuple, not @dataclass, and the reason is mechanical rather than stylistic: this module is
    loaded by its test decks through ``importlib.util.spec_from_file_location`` WITHOUT being
    registered in ``sys.modules``, and under ``from __future__ import annotations`` the dataclass
    machinery resolves each string annotation through ``sys.modules[cls.__module__]`` -- which is
    ``None`` for such a module, so every @dataclass in this file would explode at import time and
    take the whole existing deck with it. NamedTuple never performs that lookup.
    """

    commodity_code: int
    market_year: int
    as_of_date: str
    rows: int
    max_week_ending: date | None
    bronze_key: str


class TripwireFinding(NamedTuple):
    rule: str                 # "3a-open-my-freshness" | "3b-bronze-regression"
    commodity_code: int
    market_year: int
    as_of_date: str
    detail: str

    def line(self) -> str:
        return (f"{self.rule} commodity_code={self.commodity_code} "
                f"market_year={self.market_year} as_of={self.as_of_date}: {self.detail}")


def _as_of_to_date(as_of_date: str) -> date | None:
    try:
        return date(int(as_of_date[:4]), int(as_of_date[4:6]), int(as_of_date[6:8]))
    except (ValueError, IndexError):
        return None


def evaluate_open_my_freshness(
    observations: list[BronzeVintageObservation],
    *,
    max_lag_days: int = _OPEN_MY_MAX_LAG_DAYS,
) -> list[TripwireFinding]:
    """Clause 3a, conditioned on the OPEN marketing year. Refuses nothing; returns findings.

    A CLOSED marketing year is exempt BY CONSTRUCTION, and that exemption is the whole clause:
    unconditioned, this rule refuses 25 of the 64 raw keys of the very release it was written to
    protect, and all 25 are closed MYs whose tape legitimately stopped months ago.
    """
    findings: list[TripwireFinding] = []
    for obs in observations:
        label_day = _as_of_to_date(obs.as_of_date)
        if label_day is None or obs.max_week_ending is None:
            continue
        release = esr_release_on_or_before(label_day)
        if obs.market_year != open_marketing_year(obs.commodity_code, release):
            continue  # closed (or new-crop) marketing year -- exempt, and that is clause 3a
        lag = (release - obs.max_week_ending).days
        if lag > max_lag_days:
            findings.append(TripwireFinding(
                rule="3a-open-my-freshness",
                commodity_code=obs.commodity_code, market_year=obs.market_year,
                as_of_date=obs.as_of_date,
                detail=(f"open-MY payload is {lag} d stale -- max week_ending "
                        f"{obs.max_week_ending.isoformat()} vs derived release "
                        f"{release.isoformat()} (bound {max_lag_days} d); rows={obs.rows}; "
                        f"{obs.bronze_key}"),
            ))
    return findings


def evaluate_bronze_regression(
    observations: list[BronzeVintageObservation],
    prior: dict[tuple[int, int], tuple[str, date]],
) -> list[TripwireFinding]:
    """Clause 3b: ``max(week_ending_date)`` must not go BACKWARDS versus the prior vintage.

    *prior* is a SEED only: ``(commodity_code, market_year) -> (prior_as_of, prior_max_week_ending)``
    from OUTSIDE this observation set -- in ``shadow-prior`` mode, the prior bronze object on S3.
    Within the set the comparison walks each pair's own as_of timeline ascending, so a run holding
    several vintages of a pair judges each vintage against the one before it.

    THE TRAP THIS SHAPE AVOIDS, caught by the fixture: seeding the comparison with "the latest
    vintage this run saw" makes every observation its own predecessor, ``prior_as_of >=
    obs.as_of_date`` short-circuits, and the instrument reports zero findings on a corpus that
    contains a real regression. A tripwire that is silent because of how its baseline was built is
    worse than no tripwire.

    A pair with no prior is not a finding -- it is a first vintage, and inventing a baseline for it
    would be the frequency-floor mistake.
    """
    by_pair: dict[tuple[int, int], list[BronzeVintageObservation]] = defaultdict(list)
    for obs in observations:
        if obs.max_week_ending is not None:
            by_pair[(obs.commodity_code, obs.market_year)].append(obs)

    findings: list[TripwireFinding] = []
    for pair, group in by_pair.items():
        seed = prior.get(pair)
        previous = seed if (seed and seed[1] is not None) else None
        for obs in sorted(group, key=lambda o: o.as_of_date):
            if obs.max_week_ending is None:
                continue  # no observation (all-missing tape): never compared, never the new prior
            if previous is not None and previous[0] < obs.as_of_date \
                    and obs.max_week_ending < previous[1]:
                findings.append(TripwireFinding(
                    rule="3b-bronze-regression",
                    commodity_code=obs.commodity_code, market_year=obs.market_year,
                    as_of_date=obs.as_of_date,
                    detail=(f"max week_ending REGRESSED {previous[1].isoformat()} "
                            f"(as_of={previous[0]}) -> {obs.max_week_ending.isoformat()}, losing "
                            f"{(previous[1] - obs.max_week_ending).days} d of tape; "
                            f"rows={obs.rows}; {obs.bronze_key}"),
                ))
            if previous is None or obs.as_of_date > previous[0]:
                previous = (obs.as_of_date, obs.max_week_ending)
    return sorted(findings, key=lambda f: (f.as_of_date, f.commodity_code, f.market_year))


def priors_from_observations(
    observations: list[BronzeVintageObservation],
) -> dict[tuple[int, int], tuple[str, date]]:
    """The latest vintage each pair was seen at in *observations*, as a SEED for 3b.

    Only ever built from a set that is strictly EARLIER than the set being judged -- 3b walks the
    in-run timeline itself, so seeding it with the run's own latest would make every observation its
    own predecessor and silence the instrument.
    """
    best: dict[tuple[int, int], tuple[str, date]] = {}
    for obs in observations:
        if obs.max_week_ending is None:
            continue
        pair = (obs.commodity_code, obs.market_year)
        current = best.get(pair)
        if current is None or obs.as_of_date > current[0]:
            best[pair] = (obs.as_of_date, obs.max_week_ending)
    return best


def _max_week_ending(df) -> date | None:
    """max(week_ending_date) as a plain date, or None. Never raises: this is an instrument.

    NaT-SAFE (verify seat, 2026-09-07). ``isinstance(pd.NaT, datetime.date)`` is True (NaTType
    subclasses datetime), so the first cut's bare ``.max()`` handed pd.NaT back AS IF it were a date on
    an all-unparseable column, and both tripwire clauses then raised on it (``release - NaT``;
    ``NaT < date``) -- escaping report_tripwires and main(), i.e. the ONE way the counter-only shadow
    could move an exit code, on the one mechanism that ships default-on into the live weekly fire.
    Driven end to end through the real transform by the verify seat: weekEndingDate '' / 'n/a' ->
    datetime64 all-NaT -> NaT -> TypeError. THE FIX: coerce, DROP NaT, then max. An all-missing column
    reads None (the honest answer -- no observation), and one unparseable row no longer blinds the
    whole object (the mixed object-dtype case, where ``Series.max()`` raised inside the try and the
    instrument silently read None for a frame that carried 15 perfectly good dates).
    """
    try:
        if "week_ending_date" not in df.columns or not len(df):
            return None
        import pandas as pd  # local: this module must import without pandas on the fetch leg
        s = pd.to_datetime(df["week_ending_date"], errors="coerce").dropna()
        if s.empty:
            return None
        value = s.max()
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return None
    try:
        if isinstance(value, datetime):  # pd.Timestamp IS a datetime (and so a date): normalise first
            return value.date()
        if hasattr(value, "date") and not isinstance(value, date):
            return value.date()
        return value if isinstance(value, date) else None
    except Exception:  # noqa: BLE001
        return None


def build_prior_vintage_index(bronze_keys: list[str]) -> dict[tuple[int, int], list[str]]:
    """``(commodity_code, market_year) -> sorted as_of labels`` from ONE bronze listing.

    One paginated LIST for the whole run (8,920 keys measured 2026-09-07 = ~9 calls), never one
    LIST per key: ``list_s3_keys`` builds a fresh boto3 client per call, so a per-key listing would
    be 8,920 clients and 8,920 round trips to answer a question one listing already answers.
    """
    index: dict[tuple[int, int], list[str]] = defaultdict(list)
    for key in bronze_keys:
        code, year, as_of = (parse_hive_key(key, "commodity_code"),
                             parse_hive_key(key, "market_year"),
                             parse_hive_key(key, "as_of"))
        if not (code and year and as_of):
            continue
        try:
            index[(int(code), int(year))].append(as_of)
        except ValueError:
            continue
    return {pair: sorted(set(labels)) for pair, labels in index.items()}


def _prior_bronze_max_week_ending(
    s3_client, bucket: str, commodity_code: int, market_year: int, as_of_date: str,
    prior_as_ofs: list[str] | None,
) -> tuple[str, date] | None:
    """``shadow-prior`` only: the greatest as_of STRICTLY BEFORE *as_of_date* for this pair, and its
    max week_ending -- ONE GET of the ``week_ending_date`` column from the prior bronze object.
    Entirely best-effort: an instrument that can fail a bronze write is worse than no instrument.
    """
    earlier = [a for a in (prior_as_ofs or []) if a < as_of_date]
    if not earlier:
        return None
    prior_as_of = earlier[-1]
    prior_key = bronze_esr_key(commodity_code, market_year, prior_as_of)
    try:
        body = s3_download_with_retry(bucket, prior_key, s3_client)
        prior_max = _max_week_ending(
            pq.read_table(io.BytesIO(body), columns=["week_ending_date"]).to_pandas())
    except Exception:  # noqa: BLE001
        return None
    return (prior_as_of, prior_max) if prior_max is not None else None


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _validate_yyyymmdd(value: str, flag: str) -> str:
    """FAIL-CLOSED on a date-shaped CLI argument.

    A malformed bound must stop the run, never match nothing: a silently-empty
    match looks exactly like "the filter worked and there was nothing to do", and
    the operator's next action is to read ``written=`` and decide whether the
    measurement downstream is real.  The empty string is included -- it is the
    one shell/JSON form that yields a zero-length argument.
    """
    if not (len(value) == 8 and value.isdigit()):
        raise ValueError(
            f"{flag} must be YYYYMMDD (8 digits), got {value!r}. Refusing to run: an unparseable "
            "bound would silently select the wrong key set and look like a clean no-op."
        )
    return value


def _as_of_from_raw_key(raw_key: str) -> str | None:
    """The ``YYYYMMDD`` vintage the RAW KEY ITSELF carries, or ``None``.

    Weekly keys carry it in their ``as_of=`` partition.  Backfill keys carry no
    vintage at all -- and ``None`` is the honest answer, never today's date.
    """
    m = _AS_OF_RE.search(raw_key)
    return m.group(1) if m else None


def _as_of_from_raw_meta(s3_client, bucket: str, raw_key: str) -> str | None:
    """The ``YYYYMMDD`` the raw_meta sidecar records the bytes were FETCHED on.

    ``leviathan.storage.raw_metadata.write_raw_s3_metadata`` writes
    ``raw_meta/<raw_key>_meta.json`` beside every raw object with a
    ``download_timestamp``.  For an undated payload that fetch date is the only
    honest vintage there is: it is what was knowable when the bytes landed.

    Best-effort by construction -- the sidecar write is itself best-effort, so a
    missing or unparseable sidecar returns ``None`` and the caller REFUSES the
    key rather than inventing a date.
    """
    meta_key = f"{_RAW_META_PREFIX}{raw_key}_meta.json"
    try:
        body = s3_client.get_object(Bucket=bucket, Key=meta_key)["Body"].read()
        stamp = json.loads(body).get("download_timestamp")
    except Exception:  # noqa: BLE001 -- a missing/garbled sidecar is a refusal, not a crash
        return None
    if not isinstance(stamp, str):
        return None
    m = _ISO_DATE_RE.match(stamp)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


def resolve_as_of(
    raw_key: str, s3_client, bucket: str, backfill_as_of: str | None
) -> tuple[str | None, str]:
    """Return ``(as_of_YYYYMMDD, provenance)`` for a raw key -- THE VINTAGE LAW.

    Provenance is one of ``raw_key`` / ``operator`` / ``raw_meta``, or
    ``unresolvable`` with a ``None`` date.  There is deliberately no
    today's-date branch: see the module docstring.
    """
    own = _as_of_from_raw_key(raw_key)
    if own is not None:
        return own, "raw_key"
    if backfill_as_of is not None:
        return backfill_as_of, "operator"
    stamped = _as_of_from_raw_meta(s3_client, bucket, raw_key)
    if stamped is not None:
        return stamped, "raw_meta"
    return None, "unresolvable"


def _filter_by_as_of_min(
    raw_keys: list[str],
    as_of_min: str | None,
    *,
    include_backfill: bool = False,
    backfill_as_of: str | None = None,
) -> tuple[list[str], int]:
    """Keep the raw keys whose OWN as_of is >= *as_of_min*; return ``(kept, dropped_undated)``.

    Zero-padded ``YYYYMMDD`` sorts lexicographically the way it sorts
    chronologically, so a string compare is the whole test.

    An UNDATED key has no vintage to compare and is dropped -- counted, not
    silently swept in.  Admitting it on a fallback date is the C-F1 defect: with
    a today's-date fallback every one of the 1,455 undated raw objects satisfies
    any bound, so a flag advertised as narrowing the rewrite opened it to the
    whole history.  ``include_backfill`` + an EXPLICIT ``backfill_as_of`` is the
    only way in, because that is the only way the operator has declared a vintage
    the bound can honestly be judged against.
    """
    if as_of_min is None:
        return raw_keys, 0
    _validate_yyyymmdd(as_of_min, "--as-of-min")
    admit_undated = include_backfill and backfill_as_of is not None
    kept: list[str] = []
    dropped_undated = 0
    for key in raw_keys:
        as_of = _as_of_from_raw_key(key)
        if as_of is None:
            if not admit_undated:
                dropped_undated += 1
                continue
            as_of = backfill_as_of
        if as_of >= as_of_min:
            kept.append(key)
    return kept, dropped_undated


def select_raw_keys(raw_keys: list[str], args) -> list[str]:
    """Every CLI-level selection rule, in ONE seam so main()'s gates are testable.

    Order: the force/bound covenant, then the undated-key admission gate, then the
    vintage bound, then ``--limit``.  Raises ``ValueError`` on any refusal.
    """
    if args.force_overwrite and args.as_of_min is None:
        raise ValueError(
            "--force-overwrite requires --as-of-min: an unbounded forced rewrite would re-bronze "
            "the ENTIRE history to add all-NULL columns to payloads that never carried the "
            "fields. Name the vintage bound (e.g. --as-of-min 20260712)."
        )
    if args.backfill_as_of is not None:
        _validate_yyyymmdd(args.backfill_as_of, "--backfill-as-of")

    if not args.include_backfill:
        dated = [k for k in raw_keys if _as_of_from_raw_key(k) is not None]
        undated = len(raw_keys) - len(dated)
        if undated:
            logger.warning(
                "skipped %d undated raw key(s) (no as_of= segment): a bronze partition's as_of "
                "comes from the raw key or the raw_meta sidecar, NEVER from today's date. Pass "
                "--include-backfill to admit them.", undated,
            )
        raw_keys = dated
    elif args.as_of_min is not None and args.backfill_as_of is None:
        raise ValueError(
            "--include-backfill with --as-of-min requires an explicit --backfill-as-of: an "
            "undated key carries no vintage, so a bound cannot judge it. Declare the vintage or "
            "drop --include-backfill."
        )

    if args.as_of_min is not None:
        before = len(raw_keys)
        raw_keys, dropped_undated = _filter_by_as_of_min(
            raw_keys, args.as_of_min,
            include_backfill=args.include_backfill, backfill_as_of=args.backfill_as_of,
        )
        logger.info(
            "as-of-min=%s  selected=%d of %d raw key(s)  (dropped=%d, of which undated=%d)",
            args.as_of_min, len(raw_keys), before, before - len(raw_keys), dropped_undated,
        )

    if args.limit:
        raw_keys = raw_keys[: args.limit]
    return raw_keys


def report_tripwires(
    observations: list[BronzeVintageObservation],
    s3_priors: dict[tuple[int, int], tuple[str, date]] | None = None,
) -> tuple[list[TripwireFinding], list[TripwireFinding]]:
    """Log what 3a and 3b WOULD refuse. Refuses nothing; returns the two finding lists.

    Findings are named PER OBJECT, never counted into a rate: the regression set the design
    measured is 9 of 1,478 bronze pairs, small enough to name, and a frequency floor here would
    deny exactly the tail this instrument exists to see.
    """
    priors = dict(s3_priors or {})     # SEED ONLY -- 3b walks this run's own timeline itself.
    freshness = evaluate_open_my_freshness(observations)
    regressions = evaluate_bronze_regression(observations, priors)

    logger.info(
        "AS_OF TRIPWIRE SHADOW (counter-only, refused nothing): observations=%d  "
        "3a-open-my-freshness=%d  3b-bronze-regression=%d  priors=%d",
        len(observations), len(freshness), len(regressions), len(priors),
    )
    for finding in freshness + regressions:
        logger.warning("WOULD REFUSE (shadow only) %s", finding.line())
    return freshness, regressions


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    backfill_as_of: str | None,
    ingest_date: str,
    tripwire: str = TRIPWIRE_OFF,
    prior_index: dict[tuple[int, int], list[str]] | None = None,
    priors_out: dict | None = None,
) -> tuple[str, str, BronzeVintageObservation | None]:
    """Returns ``(status, raw_key, observation)``.

    The third element is the COUNTER-ONLY tripwire observation, built from the frame this call
    already holds -- it costs one ``max()`` over a column and changes nothing about what is
    written. It is ``None`` for every path that never built a frame (skipped/refused/error), which
    is the honest answer: a skipped key was not read, so nothing about it was measured.
    """
    s3 = get_thread_local_s3_client(aws_region)

    commodity_code_str = parse_hive_key(raw_key, "commodity_code")
    market_year_str = parse_hive_key(raw_key, "market_year")

    if not commodity_code_str or not market_year_str:
        logger.warning("Could not parse commodity_code/market_year from key: %s", raw_key)
        return "error", raw_key, None

    try:
        commodity_code = int(commodity_code_str)
        market_year = int(market_year_str)
    except ValueError:
        logger.warning("Non-integer commodity_code/market_year in key: %s", raw_key)
        return "error", raw_key, None

    as_of_date, provenance = resolve_as_of(raw_key, s3, bucket, backfill_as_of)
    if as_of_date is None:
        # THE VINTAGE LAW: no key segment, no operator declaration, no sidecar -> no honest as_of.
        # Refusing costs one payload; stamping today's date mints a point-in-time that never
        # existed in the surface whose entire purpose is point-in-time honesty.
        logger.debug("no resolvable as_of for %s -- refused (INV-3)", raw_key)
        return "refused", raw_key, None
    if provenance != "raw_key":
        logger.debug("as_of=%s for %s resolved from %s", as_of_date, raw_key, provenance)
    b_key = bronze_esr_key(commodity_code, market_year, as_of_date)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key, None

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key, None

    try:
        df = transform_esr_json_to_bronze(
            raw_bytes,
            commodity_code=commodity_code,
            market_year=market_year,
            as_of_date=as_of_date,
            ingest_date=ingest_date,
        )
    except (ValueError, Exception) as exc:  # noqa: BLE001
        logger.error("ESR transform failed  key=%s: %s", raw_key, exc)
        return "error", raw_key, None

    observation = None
    if tripwire != TRIPWIRE_OFF:
        observation = BronzeVintageObservation(
            commodity_code=commodity_code, market_year=market_year, as_of_date=as_of_date,
            rows=len(df), max_week_ending=_max_week_ending(df), bronze_key=b_key,
        )
        if tripwire == TRIPWIRE_SHADOW_PRIOR and priors_out is not None:
            got = _prior_bronze_max_week_ending(
                s3, bucket, commodity_code, market_year, as_of_date,
                (prior_index or {}).get((commodity_code, market_year)),
            )
            if got is not None:
                _record_prior(priors_out, commodity_code, market_year, got)

    try:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(
            Bucket=bucket,
            Key=b_key,
            Body=buf.getvalue(),
            ContentType="application/octet-stream",
        )
        logger.info(
            "bronze written  commodity=%d  year=%d  as_of=%s  rows=%d  %s",
            commodity_code, market_year, as_of_date, len(df), b_key,
        )
        return "written", raw_key, observation
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key, None


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface, factored out so the refusal gates are testable without AWS."""
    parser = argparse.ArgumentParser(description="USDA ESR raw -> bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true",
                        help="Rewrite bronze objects that already exist. REQUIRES --as-of-min.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap the number of raw keys processed (smoke test)")
    parser.add_argument(
        "--include-backfill",
        action="store_true",
        dest="include_backfill",
        help="Admit UNDATED raw keys (no as_of= partition). Their bronze as_of is then taken from "
             "an explicit --backfill-as-of, else from the raw_meta sidecar's download_timestamp; "
             "a key with neither is REFUSED. Never today's date.",
    )
    parser.add_argument(
        "--backfill-as-of",
        default=None,
        dest="backfill_as_of",
        help="YYYYMMDD vintage to DECLARE for undated keys. No default: an undated key's as_of "
             "comes from the raw_meta sidecar when this is absent, never from the run date.",
    )
    parser.add_argument(
        "--as-of-min",
        default=None,
        dest="as_of_min",
        help="YYYYMMDD lower bound: process only raw keys whose OWN as_of is >= this. Required by "
             "--force-overwrite, so a targeted re-bronze can never widen into the whole history.",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )

    load_env()

    args = build_parser().parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    today = datetime.now(timezone.utc)
    # NOTE the absence: there is no today's-date fallback for backfill_as_of. today is the INGEST
    # date (when this run read the bytes), never the VINTAGE (when the bytes were knowable).
    backfill_as_of = args.backfill_as_of
    ingest_date = today.date().isoformat()

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".json", aws_region=aws_region)
    raw_keys.sort()

    logger.info(
        "ESR task  bucket=%s  raw_keys=%d  force=%s  include_backfill=%s  backfill_as_of=%s  "
        "as_of_min=%s",
        bucket, len(raw_keys), args.force_overwrite, args.include_backfill,
        backfill_as_of, args.as_of_min,
    )

    try:
        raw_keys = select_raw_keys(raw_keys, args)
    except ValueError as exc:
        logger.error("REFUSING: %s", exc)
        sys.exit(2)

    # The as_of law's tripwires, COUNTER-ONLY (module docstring). `shadow-prior` buys the ONE
    # listing that makes 3b exact on a single-vintage weekly fire; `shadow` costs nothing at all.
    tripwire = tripwire_mode()
    prior_index: dict[tuple[int, int], list[str]] = {}
    if tripwire == TRIPWIRE_SHADOW_PRIOR:
        try:
            prior_index = build_prior_vintage_index(
                list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region))
        except Exception as exc:  # noqa: BLE001 -- the instrument degrades, the run does not fail
            logger.warning("tripwire prior index unavailable (%s) -- 3b falls back to in-run "
                           "priors only", exc)
    logger.info("as_of tripwire mode=%s (COUNTER-ONLY: refuses nothing)  prior_index_pairs=%d",
                tripwire, len(prior_index))

    start = datetime.now(timezone.utc)
    written = skipped = errors = refused = 0
    observations: list[BronzeVintageObservation] = []
    s3_priors: dict[tuple[int, int], tuple[str, date]] = {}

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process,
                key,
                bucket,
                aws_region,
                args.force_overwrite,
                backfill_as_of,
                ingest_date,
                tripwire,
                prior_index,
                s3_priors,
            ): key
            for key in raw_keys
        }
        refused_samples: list[str] = []
        for fut in as_completed(futures):
            try:
                status, key, observation = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
                errors += 1
                continue
            if observation is not None:
                observations.append(observation)
            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            elif status == "refused":
                refused += 1
                if len(refused_samples) < 3:
                    refused_samples.append(key)
            else:
                errors += 1

    if refused:
        logger.warning(
            "REFUSED %d admitted key(s) with no resolvable as_of (no as_of= segment, no "
            "--backfill-as-of, no raw_meta sidecar). Nothing was written for them: a bronze "
            "partition's as_of never comes from today's date. Sample: %s",
            refused, ", ".join(refused_samples),
        )

    if tripwire != TRIPWIRE_OFF:
        report_tripwires(observations, s3_priors)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  refused=%d  errors=%d  elapsed=%.1fs",
        written, skipped, refused, errors, elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
