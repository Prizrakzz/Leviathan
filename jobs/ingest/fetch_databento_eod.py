#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W2 / D1 + D5 -- the Databento EOD raw producer.

WHAT IT DOES, IN THE ORDER THE PLAN MANDATES
--------------------------------------------
Per ``(dataset, root, year)``:

  1. **Resolve, free, in TWO steps.** ``stype_in=parent, stype_out=raw_symbol`` is an HTTP 422
     (established by the live smoke, 2026-07-28): the recipe is ``<ROOT>.FUT`` -> instrument_id,
     then instrument_id -> raw_symbol in batches of <= 500. Both calls are free.
  2. **Filter to OUTRIGHTS (F1).** Parent symbology returns butterflies, condors and calendar
     spreads; outrights are 2.4%-24% of the result. Filtering is the difference between $43.24 and
     $140.31 -- i.e. between fitting in the $125 of credits and not. The filter is
     ``transforms.raw_to_bronze.databento_eod.is_outright``: the verified regex AND an exact root
     match, because the bare GLBX regex admitted ``T12Q6`` on a ``ZC`` resolve.
  3. **Assert F-A**: within one ``(root, year)`` every ``raw_symbol`` maps to exactly ONE
     ``instrument_id``. HARD FAIL otherwise -- F2's falsification test and the ohlcv/statistics
     join key both rest on it.
  4. **Persist the resolve verdict** to ``symbology_{root}_{year}.json`` under
     ``raw/production/source=databento/dataset={ds}/root={root}/year={year}/``. It carries the
     per-symbol outright/dropped verdict and the ``dropped_count`` that IS the gate-2 metric -- the
     evidence is written once, at resolve time, never recomputed from an S3 listing later. It is
     also the D2 decade anchor: the resolve year plus each mapping's ``d0``/``d1`` pins ``ZCH6`` to
     2016 rather than 2026 with no reference to ``datetime.now()``.
  5. **Buy by ``raw_symbol`` through the BATCH api**, never through timeseries streaming: batch
     bills once and re-downloads free for 30 days, streaming re-bills every call and has no resume
     (a dropped connection 90% through IFUS costs $34.28 again).
  6. **Download per file** (never the whole-job zip): only the per-file path verifies the sha256
     manifest and resumes by HTTP Range.

MODES
-----
``--mode backfill --root ZC --year 2016``
    One ``(root, year)`` unit, idempotent: an existing raw payload is skipped unless
    ``--force-overwrite``. The unit is per-YEAR because skeptic finding F-A is BINDING -- the
    symbol->instrument_id uniqueness assertion is only meaningful inside one resolve window.
``--mode incremental --since YYYY-MM-DD``
    D5. Re-resolves the CURRENT year, requests ``[since, today+1)`` and lands the payload in the
    same ``year={current}`` prefix under an as-of filename. Measured at $0.016/day for all 15
    original roots (+CPO's statistics-only leg, ~$0.001/day) -- a rounding error, and shaped to
    slot into ``jobs/batch/futures_eod_task.py``.

SETTLEMENT-TAPE ROOTS (V2-4)
----------------------------
A root in ``SETTLEMENT_TAPE_ROOTS`` (CPO) buys the ``statistics`` schema ONLY: its ohlcv-1d
prices at $0.0000 from 2014 (no Globex trade bars), and an empty DBN (~150-190 B) would fail the
200-byte floor inside ``land_bytes`` AFTER the vendor job -- a red every fire. ``--no-statistics``
on such a root buys nothing and is refused.

THE EXACT NON-BLOCKING CONTRACT (V2-4 m10, widened by the STEP-12 review F1/F2):

* ``--mode incremental`` (the nightly; the scheduled command carries no ``--root``, so all 16
  roots run in ONE task) -- the settlement-tape unit is NON-BLOCKING AS A WHOLE. ANY failure of
  that unit is logged with the exception class, counted and skipped, never ``failures += 1`` and
  never re-raised: a thin/empty statistics payload (the size floor, or a zero-file batch job:
  ``SETTLEMENT_TAPE_THIN``), and every other shape -- a vendor-job timeout past
  ``--max-wait-seconds``, an EXPIRED job, a STEP-2 / F-A ``SystemExit`` out of the resolve, a
  fail-closed ``raw_exists`` (``SETTLEMENT_TAPE_SKIPPED``). The SFN Fetch Map carries no Catch, so
  an exit 1 here would fail the execution before Silver and stale the other 15 roots' promote; the
  estate law is that the family must never be staled by the new root. ``KeyboardInterrupt`` is
  NOT caught (``SystemExit`` and ``Exception`` are caught by name, never ``BaseException``).
  Nothing is landed for a skipped unit, nothing is re-submitted, and the silver task's own
  per-unit verdict is where the missing session is judged.
* ``--mode backfill`` (operator-driven, ``--root CPO``) STAYS BLOCKING, exactly like the silver
  task's backfill units: a unit that lands nothing -- thin payload included -- is ``FAILED``,
  ``failures += 1``, exit 1, so the runbook's K6 ('any unit FAILED -> STOP') fires as written.
  There are no 15 roots to stale on an operator backfill, and an exit 0 that landed 10/11 raw
  units would be a lie.
``--cost-only``
    THE PRE-BUY GATE. Runs the full resolve + ``metadata.get_cost`` for every requested
    ``(root, year)`` and prints a per-root-per-year and per-DATASET cost table plus a grand total,
    WITHOUT submitting anything. The quote is to-the-cent reproducible because the submit that
    follows reuses the IDENTICAL ``dataset/symbols/schema/stype_in/start/end`` tuple.

    IT FAILS CLOSED, on two conditions, because a gate that only PRINTS a number is not a gate:
    a ZERO dropped-symbol count on any root (the outright filter did not run -- that is the
    $140.31 parent pull), and a grand total above ``--max-usd`` (default 50.00, itself capped at
    the 125.00 credit pool). The per-dataset subtotals exist so the quote can be diffed
    STRUCTURALLY against the plan's GLBX 2.7819 / IFUS 34.2813 / IFEU 6.1793 rather than only in
    aggregate. Under ``--mode incremental`` the quote prices the INCREMENTAL window, not the
    calendar year the payload lands in.

THE KEY
-------
Read from the environment variable ``DATABENTO_API_KEY``, which the ECS agent injects from Secrets
Manager secret ``leviathan/dev/databento-api-key`` (``valueFrom`` on the job definition -- the
FAS_API_KEY pattern, ``infra/terraform/modules/batch/main.tf``). When the variable is absent this
script will fetch that secret directly via ``secretsmanager:GetSecretValue``. It is NEVER logged,
NEVER placed in argv, and never echoed in an error message; ``--secret-id`` names the SECRET, not
the value.

COST DISCIPLINE
---------------
``symbols=None`` means ALL_SYMBOLS to Databento -- that is the $140.31 mistake -- so a ``None`` or
empty symbol list is refused before any billable call. Every billable entry point additionally
passes ``schema`` explicitly (the client defaults to ``trades``, which would price the wrong thing
by three orders of magnitude).

THE EXISTENCE PROBE FAILS CLOSED -- AND HERE THE ARGUMENT IS MONEY, NOT RECOVERABILITY
---------------------------------------------------------------------------------------
VERDICT 2026-08-20. ``raw_exists`` is the ONLY thing standing between a re-run and a re-submit, and
the estate house idiom (``except Exception: return False``) answers "absent" to a throttle, a 5xx,
an expired token or a denied head.

**Are the payload bytes re-derivable? YES.** Databento is a vendor, not a rolling window: the same
``dataset/symbols/schema/start/end`` tuple re-submits to the same DBN, and a done job re-downloads
FREE for 30 days. So this is not the ``fetch_eex_freight.py`` unrecoverability argument and it is
not claimed to be. The narrowing is bought for a different reason, and it is the one this leg cares
about most:

  **A FALSE "ABSENT" IS A PURCHASE.** The line below the probe is ``submit_unit`` -- a BILLABLE
  batch job. A throttled ``HeadObject`` therefore does not merely overwrite a good payload; it buys
  it again, outside the pre-buy gate that ``--cost-only`` exists to enforce. The measured unit
  prices make the size of that plain: IFUS is $34.28 and IFEU $6.18 against a $125 credit pool and
  a $45.00 recommended buy. An S3 hiccup must never be able to spend money.

So only a genuine 404 means absent; any other ``HeadObject`` error raises. The call site sits inside
the per-unit ``try``, so the raise becomes the ordinary recorded unit failure (``FAILED <ds>
<root>/<year>``, ``failures += 1``, run exits 1) -- the other units still run, nothing is submitted
for the failed one, and no payload is overwritten. Exit 1 is Class D EXIT in
``infra/terraform/modules/batch/main.tf`` ``local.producer_retry_rules`` (behind the mandatory
terminal ``on_reason = "*"`` rule), terminal after ONE attempt -- so a failed probe cannot become a
retry storm that submits the same paid job twice.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

# Batch invokes tasks by PATH, so `jobs.*` / `leviathan.*` need the repo root importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    databento_payload_filename,
    databento_symbology_filename,
    raw_databento_key,
)

# root_years / year_window live in the transform module so the fetch job and the silver task can
# never disagree about the unit set (a unit one skips and the other expects is either a spurious
# failure or silently missing history).
from leviathan.transforms.raw_to_bronze.databento_eod import (  # noqa: E402
    DATASET_SLUGS,
    GLBX,
    ROOT_FIRST_DATE,
    ROOT_MAP,
    SETTLEMENT_TAPE_ROOTS,
    partition_symbols,
    root_years,
    year_window,
)

logger = get_logger(__name__)

# The Secrets Manager secret the ECS agent injects as DATABENTO_API_KEY. The NAME is public; the
# value never leaves this process's memory.
DATABENTO_SECRET_ID = "leviathan/dev/databento-api-key"
DATABENTO_KEY_ENV = "DATABENTO_API_KEY"

OHLCV_SCHEMA = "ohlcv-1d"
STATISTICS_SCHEMA = "statistics"
# GLBX statistics is $1.76 for the whole backfill and carries the ONLY real settlements and the
# ONLY open interest in the wave. ICE statistics is $1,696 (IFUS) + $264 (IFEU) -- EXCLUDED.
STATISTICS_DATASETS: frozenset[str] = frozenset({GLBX})


def schemas_for(dataset: str, root: str, *, no_statistics: bool) -> list[str]:
    """The schemas ONE ``(dataset, root)`` unit buys, in submit order.

    SETTLEMENT_TAPE_ROOTS buy statistics ONLY: ohlcv-1d prices at $0.0000 from 2014 (no bars), and
    an empty DBN (~150-190 B) fails the 200-byte floor inside ``land_bytes`` AFTER the vendor job
    -- a red every fire. ``--no-statistics`` on such a root buys nothing (the caller refuses)."""
    if root in SETTLEMENT_TAPE_ROOTS:
        return [] if no_statistics else [STATISTICS_SCHEMA]
    out = [OHLCV_SCHEMA]
    if dataset in STATISTICS_DATASETS and not no_statistics:
        out.append(STATISTICS_SCHEMA)
    return out


class EmptyVendorPayload(RuntimeError):
    """A batch job that completed with NO ``.dbn.zst`` at all (a zero-record window). A distinct
    class, not a message match: ``got 2`` (a split or duplicated payload) is NOT 'nothing usable'
    and stays a plain ``RuntimeError`` -- a hard failure on every root, in every mode."""


def _is_thin_payload_error(exc: BaseException) -> bool:
    """The two 'the vendor delivered nothing usable' shapes a settlement-tape unit tolerates AS
    THIN: the raw size floor (an empty DBN is ~150-190 B against the 200-byte floor) and
    :class:`EmptyVendorPayload`. Nothing else -- a ``got N>1`` payload is a hard failure."""
    from leviathan.common.validation import SchemaValidationError

    return isinstance(exc, (SchemaValidationError, EmptyVendorPayload))

# symbology.resolve documents a 2,000-symbol cap; the orchestrator's live smoke batched step 2 at
# <= 500 and that conservative value is kept deliberately.
RESOLVE_CHUNK = 500
# databento's BentoHttpAPI._post has NO 429/Retry-After handling (only the batch DOWNLOAD path
# does), so every resolve/cost/submit call goes through this caller-side backoff.
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
POLITE_SLEEP_SECONDS = 0.5

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


# ---------------------------------------------------------------------------
# key handling
# ---------------------------------------------------------------------------
def load_api_key(secret_id: str = DATABENTO_SECRET_ID, region: str = "us-east-1") -> str:
    """The Databento key. Environment first (the ECS ``valueFrom`` injection), Secrets Manager
    second. NEVER logged, never returned in an exception message."""
    key = (os.environ.get(DATABENTO_KEY_ENV) or "").strip()
    if key:
        # PRESENT, never the length: the log stream is shared and a key length is a free bit of a
        # secret nobody needs. "present" is all an operator can act on anyway.
        logger.info("databento key: taken from env %s (present, value not logged)",
                    DATABENTO_KEY_ENV)
        return key
    import boto3

    logger.info("databento key: env %s absent, reading secret %s", DATABENTO_KEY_ENV, secret_id)
    sm = boto3.client("secretsmanager", region_name=region)
    payload = sm.get_secret_value(SecretId=secret_id)["SecretString"]
    try:
        parsed = json.loads(payload)
        key = str(parsed.get("api_key") or parsed.get(DATABENTO_KEY_ENV) or "").strip()
    except (TypeError, ValueError):
        key = str(payload).strip()
    if not key:
        raise RuntimeError(f"secret {secret_id} carries no usable Databento key (value not logged)")
    return key


def make_client(key: str):
    """A ``databento.Historical`` client. The vendor package is imported lazily and its absence is
    reported as the actionable "rebuild the worker image" error, not an opaque ImportError."""
    try:
        import databento as db
    except ImportError as exc:
        raise SystemExit(
            "the 'databento' package is not installed -- add it to pyproject's [batch] extra and "
            "REBUILD + REPIN the worker image before any cloud run (the yfinance ImportError "
            "silently wrote nothing for six weeks)"
        ) from exc
    return db.Historical(key)


# ---------------------------------------------------------------------------
# retry / windows
# ---------------------------------------------------------------------------
def call_with_backoff(fn, *args, attempts: int = MAX_ATTEMPTS, **kwargs):
    """Retry a Databento call on 429/5xx with exponential backoff. The client does not do this for
    ``_post`` / ``_get``; only the batch file download honours ``Retry-After``."""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- BentoClientError/BentoServerError + transport
            status = getattr(exc, "http_status", None)
            retryable = status is None or status == 429 or (isinstance(status, int) and status >= 500)
            if not retryable or i == attempts - 1:
                raise
            last = exc
            wait = BACKOFF_BASE_SECONDS * (2 ** i)
            logger.warning("databento call failed (status=%s), retrying in %.1fs [%d/%d]",
                           status, wait, i + 1, attempts)
            time.sleep(wait)
    raise last  # pragma: no cover -- unreachable, the loop either returns or raises


def _chunks(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ---------------------------------------------------------------------------
# step 1 + step 2: the free two-step resolve
# ---------------------------------------------------------------------------
# Per-dataset available-end cache (2026-07-28): the CURRENT year's natural window ends at
# Jan-1-next-year, which is past the dataset's available range, and the API 422s on it
# (data_end_date_after_available_end_date -- observed on KE/2026 after five other roots'
# 2026 units were, inconsistently, tolerated). metadata.get_dataset_range is free; its end
# is the same exclusive bound the 422 names, so clipping to it is exact, and past years
# (whose Jan-1 end is earlier) are unaffected by construction.
_DATASET_END_CACHE: dict[str, date] = {}


def dataset_available_end(client, dataset: str) -> date:
    if dataset not in _DATASET_END_CACHE:
        rng = call_with_backoff(client.metadata.get_dataset_range, dataset=dataset)
        raw = str(rng.get("end") or rng.get("end_date"))
        _DATASET_END_CACHE[dataset] = date.fromisoformat(raw[:10])
    return _DATASET_END_CACHE[dataset]


def incremental_window(client, dataset: str, since: date, today: date
                       ) -> Optional[tuple[str, str]]:
    """The ONLY constructor for an incremental ``[start, end)`` window.

    ``end`` is EXCLUSIVE and is clamped to ``metadata.get_dataset_range``'s end -- the exact
    quantity the 422 ``data_end_after_available_end`` names, so ``end_exclusive == avail_end``
    is LEGAL (do NOT add a day to it; that reproduces the rejected value).

    WHY THIS EXISTS (2026-07-31). :func:`resolve_outrights` already clamped correctly at the
    symbology step, and then the incremental branch in :func:`main` OVERWROTE the artifact
    window with a bare ``today + 1`` -- throwing the clamp away on the only path that submits.
    The vendor's available end LAGS the calendar day (measured 08:00Z: GLBX.MDP3 and
    IFUS.IMPACT both "available up to 2026-07-31" while the query asked for 2026-08-01), so
    the overshoot was exactly one day on EVERY run and the leg 422'd 15/15 units from the day
    it was armed. Not a weekend or holiday edge case -- a structural off-by-one.

    Returns None when the clamped window is empty or inverted: there is simply no new vendor
    data, which is a SKIP (exit 0), never a failure.
    """
    end = min(today + timedelta(days=1), dataset_available_end(client, dataset))
    if since >= end:
        return None
    return since.isoformat(), end.isoformat()


def _assert_sane_window(artifact: dict) -> None:
    """Fail-closed at the two BILLABLE chokepoints (``cost_for_unit`` / ``submit_unit``).

    Both read ``artifact["window"]`` verbatim, so any future code path that builds a window
    without going through :func:`incremental_window` gets caught HERE rather than as a vendor
    422 fifteen units later. ``end`` is EXCLUSIVE, so ``start == end`` is already degenerate."""
    w0 = str(artifact["window"]["start"])
    w1 = str(artifact["window"]["end_exclusive"])
    if w0 >= w1:
        raise ValueError(f"refusing a degenerate window {w0}..{w1} -- end is EXCLUSIVE")


def _is_server_error(exc: Exception) -> bool:
    status = getattr(exc, "http_status", None)
    return isinstance(status, int) and status >= 500


def _resolve_chunk_salvaging(client, dataset: str, chunk: list, start: str, end: str,
                             unresolvable: list) -> dict:
    """One step-2 chunk, salvage-bisecting on a PERSISTENT server 5xx.

    Observed live (2026-07-28): IFUS instrument_id 6512548 -- the ``SB   99   6512548``
    numeric-ID junk instrument -- 500s the symbology resolver ALONE on every window tried,
    surviving the full retry ladder. Junk numeric-ID instruments are dropped by the outright
    filter anyway, so their symbology is unlearnable AND worthless -- but a whole chunk must
    not die for one of them. On persistent 5xx the chunk is bisected (with a short retry
    ladder -- the poison is deterministic) down to single ids; singles that still fail are
    recorded in ``unresolvable`` and skipped. The CALLER enforces the fail-closed cap that
    distinguishes poison ids from an outage. Non-5xx errors propagate untouched."""
    try:
        return call_with_backoff(
            client.symbology.resolve, dataset=dataset, symbols=chunk,
            stype_in="instrument_id", stype_out="raw_symbol", start_date=start, end_date=end,
            attempts=2 if len(chunk) < RESOLVE_CHUNK else MAX_ATTEMPTS)
    except Exception as exc:  # noqa: BLE001
        if not _is_server_error(exc):
            raise
        if len(chunk) == 1:
            unresolvable.append(str(chunk[0]))
            return {"result": {}}
        mid = len(chunk) // 2
        left = _resolve_chunk_salvaging(client, dataset, chunk[:mid], start, end, unresolvable)
        right = _resolve_chunk_salvaging(client, dataset, chunk[mid:], start, end, unresolvable)
        merged = dict(left.get("result") or {})
        merged.update(right.get("result") or {})
        return {"result": merged}


def resolve_outrights(client, *, dataset: str, root: str, year: int,
                      through: Optional[date] = None) -> dict:
    """The full free discovery for one ``(dataset, root, year)`` + the F-A assertion.

    Returns the artifact persisted as ``symbology_{root}_{year}.json``: the outright set, the
    DROPPED set (gate 2's evidence), the symbol -> instrument_id mapping and the raw responses."""
    avail_end = dataset_available_end(client, dataset)
    eff_through = min(through, avail_end) if through is not None else avail_end
    start, end = year_window(root, year, through=eff_through)

    # STEP 1 (free): parent -> instrument_id. `<ROOT>.FUT` is upper-cased and validated as a smart
    # symbol by the client; `W.FUT` (the single-character IFEU root) is legal.
    r1 = call_with_backoff(
        client.symbology.resolve, dataset=dataset, symbols=f"{root}.FUT",
        stype_in="parent", stype_out="instrument_id", start_date=start, end_date=end)
    ids = sorted({e["s"] for entries in (r1.get("result") or {}).values()
                  for e in entries if e.get("s")}, key=int)

    # STEP 2 (free): instrument_id -> raw_symbol, batched. An EMPTY symbols list raises inside the
    # client, so the zero-instrument case (e.g. KE before 2013) short-circuits here.
    sym_to_ids: dict[str, set[str]] = {}
    sym_to_intervals: dict[str, list] = {}
    step2: list[dict] = []
    unresolvable: list[str] = []
    for chunk in _chunks(ids, RESOLVE_CHUNK):
        r2 = _resolve_chunk_salvaging(client, dataset, list(chunk), start, end, unresolvable)
        step2.append(r2)
        for iid, entries in (r2.get("result") or {}).items():
            for e in entries:
                sym = e.get("s")
                if sym:
                    sym_to_ids.setdefault(sym, set()).add(str(iid))
                    sym_to_intervals.setdefault(sym, []).append(
                        [e.get("d0"), e.get("d1"), str(iid)])
        time.sleep(POLITE_SLEEP_SECONDS)
    if unresolvable:
        # Fail-closed against outages, measured against reality twice (2026-07-28):
        # SB/2020 skipped 1 id, SB/2021 skipped 2, SB/2022 skipped 12 of 164 -- while KC/CC/CT/
        # OJ/RS resolved CLEAN in the same minutes. The junk-id density is per-root-per-year
        # (SB and RC are exactly the roots the F1 recon named), so a bare count cap cannot
        # separate a dense junk year from an outage. The CANARY can: ids that already resolved
        # in THIS unit must still resolve. Canary healthy = the server answers per-id = the
        # skips are genuine vendor defects on junk instruments; canary dead = outage = refuse.
        cap = max(3, len(ids) // 20)
        hard_ceiling = max(cap, len(ids) // 4)
        skipped = set(unresolvable)
        canary_ids = [i for i in ids if str(i) not in skipped][:3]
        if len(unresolvable) > hard_ceiling or not canary_ids:
            raise SystemExit(
                f"STEP-2 FAILURE {dataset} {root}/{year}: {len(unresolvable)} of {len(ids)} "
                f"instrument_ids unresolvable (hard ceiling {hard_ceiling}) -- refusing to "
                f"continue regardless of canary")
        if len(unresolvable) > cap:
            try:
                call_with_backoff(
                    client.symbology.resolve, dataset=dataset, symbols=canary_ids,
                    stype_in="instrument_id", stype_out="raw_symbol",
                    start_date=start, end_date=end, attempts=3)
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(
                    f"STEP-2 FAILURE {dataset} {root}/{year}: {len(unresolvable)} of {len(ids)} "
                    f"instrument_ids unresolvable AND the canary re-resolve of known-good ids "
                    f"failed ({type(exc).__name__}) -- this is an outage, refusing to continue"
                ) from exc
            logger.warning(
                "%s %s/%s: DENSE junk-id year -- %d of %d skipped, over the soft cap %d, but the "
                "canary re-resolve of known-good ids is HEALTHY, so the skips are per-id vendor "
                "defects, not an outage", dataset, root, year, len(unresolvable), len(ids), cap)
        logger.warning(
            "%s %s/%s: %d instrument_id(s) SKIPPED as unresolvable (server 5xx on the id alone; "
            "the measured case is IFUS 6512548 = the 'SB   99   6512548' numeric-ID junk the "
            "outright filter drops anyway): %s -- gate 3's bar-count reconciliation is the "
            "backstop if a real outright were ever lost this way",
            dataset, root, year, len(unresolvable), unresolvable[:10])

    outrights, dropped = partition_symbols(sym_to_ids.keys(), root, dataset)

    # F-A, BINDING -- AMENDED 2026-07-28 after the gate fired on real data. GLBX RECYCLES
    # instrument_ids across unrelated products (measured, KE/2021: KEN4 was iid 688493 for
    # Jan-01..Feb-25 and iid 234273 from Jun-30; between KEN4 tenures, 688493 carried an equity
    # option and 234273 a VIX option). A re-listing under a new id on DISJOINT date intervals is
    # fully decodable: every (raw_symbol, date) still has exactly ONE instrument_id, the DBNStore
    # symbology map is interval-scoped (symbology_from_artifact preserves d0/d1), and the
    # ohlcv/statistics join key (instrument_id, date) stays unambiguous. What genuinely breaks
    # the join and F2's dedupe is an OVERLAP -- one symbol on two ids on the SAME date -- so
    # that, exactly, is what refuses the buy. Only the OUTRIGHTS are asserted -- a spread symbol
    # legitimately re-uses ids across the complex and is dropped anyway.
    relisted: dict[str, list] = {}
    for s in outrights:
        ivs = sorted(sym_to_intervals.get(s, []), key=lambda iv: str(iv[0]))
        if len({iv[2] for iv in ivs}) > 1:
            relisted[s] = ivs
        for a, b in zip(ivs, ivs[1:]):
            end_a = a[1] or "9999-12-31"   # an open interval overlaps anything after it
            if str(end_a) > str(b[0]):     # d1 is EXCLUSIVE: d1 == next d0 is adjacency, not overlap
                raise SystemExit(
                    f"F-A VIOLATION {dataset} {root}/{year}: raw_symbol {s} maps to OVERLAPPING "
                    f"instrument_id intervals ({a} vs {b}) -- refusing to buy; the join key and "
                    f"the F2 dedupe rule would both be ambiguous"
                )
    if relisted:
        logger.info(
            "%s %s/%s: %d outright symbol(s) re-listed under a new instrument_id on disjoint "
            "intervals (GLBX id recycling, decodable): %s", dataset, root, year, len(relisted),
            ", ".join(f"{s}->{[iv[2] for iv in relisted[s]]}" for s in sorted(relisted)[:5]))

    artifact = {
        "producer": "jobs/ingest/fetch_databento_eod.py",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "dataset": dataset,
        "dataset_slug": DATASET_SLUGS[dataset],
        "root": root,
        "leviathan_slug": ROOT_MAP[root][1],
        "year": int(year),
        "window": {"start": start, "end_exclusive": end},
        "resolved_instrument_ids": len(ids),
        "resolved_symbols": len(sym_to_ids),
        "outright_count": len(outrights),
        "dropped_count": len(dropped),
        "outright_symbols": outrights,
        "dropped_symbols": dropped,
        "symbol_instrument_ids": {s: sorted(sym_to_ids[s]) for s in outrights},
        # disjoint-interval re-listings (GLBX id recycling) permitted by the amended F-A check;
        # rows of [d0, d1_exclusive, instrument_id] per affected outright. Gate evidence.
        "relisted_symbols": relisted,
        # ids skipped by the salvage-bisect (persistent server 5xx on the id alone; the measured
        # case is the numeric-ID junk instrument class). Gate evidence; capped fail-closed above.
        "unresolvable_instrument_ids": sorted(unresolvable, key=int),
        "resolve_step1": r1,
        "resolve_step2": step2,
    }
    logger.info("resolve %s %s/%s: %d instrument_ids -> %d raw symbols -> %d outrights "
                "(%d dropped)", dataset, root, year, len(ids), len(sym_to_ids),
                len(outrights), len(dropped))
    if outrights and not dropped:
        # A zero drop count on ANY root means the filter did not run (gate 2 formulation, which
        # corrects the earlier "zero for GLBX" wording that contradicted F1).
        logger.error("gate-2 PRECONDITION BREACH %s %s/%s: dropped_count is ZERO -- the outright "
                     "filter did not run", dataset, root, year)
    return artifact


# ---------------------------------------------------------------------------
# --cost-only: the pre-buy gate
# ---------------------------------------------------------------------------
def cost_for_unit(client, artifact: dict, schema: str) -> float:
    """``metadata.get_cost`` for one ``(root, year, schema)`` unit, on the EXACT symbols/window the
    submit will use. Free.

    ``schema`` is always passed explicitly (the client default is ``trades``) and ``symbols`` is
    never ``None`` (``None`` means ALL_SYMBOLS -- the $140.31 mistake). ``mode`` is deprecated and
    is not passed; ``stype_out`` is not a parameter of get_cost at all."""
    symbols = list(artifact["outright_symbols"])
    if not symbols:
        return 0.0
    _assert_sane_window(artifact)
    return float(call_with_backoff(
        client.metadata.get_cost,
        dataset=artifact["dataset"], symbols=symbols, schema=schema, stype_in="raw_symbol",
        start=artifact["window"]["start"], end=artifact["window"]["end_exclusive"]))


def build_cost_table(client, units: list[tuple[str, str, int]], *,
                     through: Optional[date] = None,
                     with_statistics: bool = True,
                     window_override: Optional[tuple[str, str]] = None) -> dict:
    """Resolve + price every requested ``(dataset, root, year)``. NO submit, no billable call.

    ``metadata.get_cost`` carries no job-shape parameter -- cost is billable-uncompressed-bytes
    only -- so this per-(root, year) quote is exactly what a per-(root, year) submit will charge.

    ``window_override`` is ``(start, end_exclusive)`` and MUST be passed whenever the caller is
    quoting a narrowed window. Without it an incremental ``--cost-only`` quotes the FULL calendar
    year -- ~250x the measured $0.016/day -- because :func:`resolve_outrights` windows on
    ``year_window`` and the incremental narrowing happens later, in the submit branch. get_cost is
    free, so nothing is billed either way; the printed number is simply not the one the run will
    charge, which is exactly what a pre-buy gate must never do."""
    rows: list[dict] = []
    for dataset, root, year in units:
        art = resolve_outrights(client, dataset=dataset, root=root, year=year, through=through)
        if window_override is not None:
            # Clamp INSIDE the loop: one override tuple spans several datasets and each carries
            # its own available end, so a single pre-computed end would be wrong for all but one.
            cap = dataset_available_end(client, dataset)          # cached + free
            end = min(date.fromisoformat(window_override[1]), cap).isoformat()
            art["window"] = {"start": window_override[0], "end_exclusive": end}
        # A settlement-tape root is never quoted on ohlcv-1d: the submit never buys it (schemas_for).
        ohlcv = 0.0 if root in SETTLEMENT_TAPE_ROOTS else cost_for_unit(client, art, OHLCV_SCHEMA)
        stats = (cost_for_unit(client, art, STATISTICS_SCHEMA)
                 if with_statistics and dataset in STATISTICS_DATASETS else 0.0)
        rows.append({
            "dataset": dataset, "root": root, "year": int(year),
            "leviathan_slug": art["leviathan_slug"],
            "outrights": art["outright_count"], "dropped": art["dropped_count"],
            "window_start": art["window"]["start"], "window_end_exclusive": art["window"]["end_exclusive"],
            "ohlcv_usd": round(ohlcv, 4), "statistics_usd": round(stats, 4),
            "total_usd": round(ohlcv + stats, 4),
        })
        time.sleep(POLITE_SLEEP_SECONDS)
    grand = round(sum(r["total_usd"] for r in rows), 4)
    by_root: dict[str, float] = {}
    by_dataset: dict[str, float] = {}
    for r in rows:
        by_root[r["root"]] = round(by_root.get(r["root"], 0.0) + r["total_usd"], 4)
        # PER-DATASET subtotals exist so the quote can be diffed STRUCTURALLY against the plan's
        # GLBX 2.7819 / IFUS 34.2813 / IFEU 6.1793 (lines 605-607). A single grand total cannot
        # distinguish "the outright filter ran" from "one dataset silently pulled the parent set".
        by_dataset[r["dataset"]] = round(by_dataset.get(r["dataset"], 0.0) + r["total_usd"], 4)
    return {"rows": rows, "by_root": by_root, "by_dataset": by_dataset,
            "ohlcv_usd": round(sum(r["ohlcv_usd"] for r in rows), 4),
            "statistics_usd": round(sum(r["statistics_usd"] for r in rows), 4),
            "grand_total_usd": grand,
            "zero_drop_roots": sorted({r["root"] for r in rows
                                       if r["outrights"] and not r["dropped"]})}


# The pre-buy budget ceiling. The plan's RECOMMENDED BUY is $45.00 (43.24 ohlcv + 1.76 statistics);
# the naive parent-symbology pull the outright filter exists to prevent is $140.31 and the credit
# pool is $125. DEFAULT_MAX_USD leaves headroom over the recommended buy without admitting anything
# near the parent number; HARD_CEILING_USD is the value --max-usd itself may not exceed, so the
# budget gate cannot be talked past on the command line.
DEFAULT_MAX_USD = 50.0
HARD_CEILING_USD = 125.0


def render_cost_table(table: dict) -> str:
    """ASCII-only cost report (the Windows console is cp1252)."""
    L = ["=== Databento W2 pre-buy cost reproduction (metadata.get_cost; NOTHING submitted) ===",
         "",
         "dataset       root year  outr drop      ohlcv$      stats$      total$",
         "----------------------------------------------------------------------"]
    for r in table["rows"]:
        L.append(f"{r['dataset']:<13s} {r['root']:<4s} {r['year']:<5d} {r['outrights']:<4d} "
                 f"{r['dropped']:<4d} {r['ohlcv_usd']:>11.4f} {r['statistics_usd']:>11.4f} "
                 f"{r['total_usd']:>11.4f}")
    L.append("----------------------------------------------------------------------")
    L.append("per-root totals:")
    for root in sorted(table["by_root"]):
        L.append(f"  {root:<4s} {table['by_root'][root]:>11.4f}")
    L.append("")
    L.append("per-DATASET totals (diff these against the plan: GLBX 2.7819 / IFUS 34.2813 / "
             "IFEU 6.1793):")
    for ds in sorted(table.get("by_dataset") or {}):
        L.append(f"  {ds:<13s} {table['by_dataset'][ds]:>11.4f}")
    L.append("")
    L.append(f"ohlcv-1d subtotal   : {table['ohlcv_usd']:>11.4f}")
    L.append(f"statistics subtotal : {table['statistics_usd']:>11.4f}")
    L.append(f"GRAND TOTAL         : {table['grand_total_usd']:>11.4f}")
    if table["zero_drop_roots"]:
        L.append("")
        L.append("GATE-2 PRECONDITION BREACH -- zero dropped symbols on root(s): "
                 + ", ".join(table["zero_drop_roots"]))
    L.append("")
    L.append("The submit reuses the IDENTICAL dataset/symbols/schema/stype_in/start/end tuple, so "
             "the charge matches this quote to the cent.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# the buy + the download
# ---------------------------------------------------------------------------
def submit_unit(client, artifact: dict, schema: str) -> dict:
    """Submit ONE batch job for one ``(root, year, schema)`` unit. BILLABLE.

    Identical tuple to :func:`cost_for_unit`. ``encoding='dbn'`` + ``compression='zstd'`` keeps the
    symbol mappings inside the payload (``map_symbols`` is a csv/json-only knob) and
    ``split_symbols=False`` keeps one file per unit instead of 50-114."""
    symbols = list(artifact["outright_symbols"])
    if not symbols:
        raise ValueError(f"{artifact['root']}/{artifact['year']}: refusing to submit with NO "
                         f"symbols -- an empty/None symbol set means ALL_SYMBOLS to Databento")
    _assert_sane_window(artifact)
    kwargs = dict(
        dataset=artifact["dataset"], symbols=symbols, schema=schema,
        start=artifact["window"]["start"], end=artifact["window"]["end_exclusive"],
        encoding="dbn", compression="zstd",
        stype_in="raw_symbol", stype_out="instrument_id",
        split_duration="none", split_symbols=False, delivery="download")

    # IDEMPOTENT SUBMIT (measured defect, 2026-07-29). submit_job is BILLABLE and the vendor has
    # no cancel endpoint, so a blind retry is a second charge. If the request reaches Databento
    # but the RESPONSE is lost -- a timeout, a dropped connection, a 5xx after acceptance -- the
    # retry creates a duplicate job for the same window. That is not hypothetical: the serial
    # backfill produced 3 duplicates (ZR/2024 statistics, SB/2021 + SB/2024 ohlcv-1d, each pair
    # ~30s apart, ~$2.25) and the nightly incremental would repeat the mechanism daily.
    # So: submit ONCE, and on failure ASK the vendor whether the job actually landed before
    # retrying. list_jobs is free.
    try:
        job = client.batch.submit_job(**kwargs)
    except Exception as first_error:  # noqa: BLE001
        logger.warning("submit %s %s/%s %s failed (%s) -- checking whether it landed before retry",
                       artifact["dataset"], artifact["root"], artifact["year"], schema,
                       type(first_error).__name__)
        existing = find_submitted_job(client, artifact, schema)
        if existing:
            logger.warning("submit ALREADY LANDED as job_id=%s -- reusing it instead of paying "
                           "for a duplicate", existing.get("id"))
            return existing
        job = call_with_backoff(client.batch.submit_job, **kwargs)
    logger.info("submitted %s %s/%s %s -> job_id=%s", artifact["dataset"], artifact["root"],
                artifact["year"], schema, job.get("id"))
    return job


def find_submitted_job(client, artifact: dict, schema: str) -> Optional[dict]:
    """A live, non-expired batch job already covering this exact (dataset, root, year, schema).

    The reconciliation key is the one the vendor echoes back: dataset + schema + start + the
    first requested symbol (which pins the root). Returns None on ANY lookup failure -- the
    caller then retries the submit, which is the safe direction: a duplicate costs money, but a
    missing payload costs the wave."""
    try:
        jobs = call_with_backoff(client.batch.list_jobs)
    except Exception:  # noqa: BLE001
        return None
    want_start = str(artifact["window"]["start"])[:10]
    want_syms = set(artifact["outright_symbols"])
    for j in jobs or []:
        if str(j.get("state", "")).lower() == "expired":
            continue
        if j.get("dataset") != artifact["dataset"] or j.get("schema") != schema:
            continue
        if str(j.get("start") or "")[:10] != want_start:
            continue
        syms = j.get("symbols")
        if isinstance(syms, str):
            syms = [s for s in syms.split(",") if s]
        if syms and set(syms) & want_syms:
            return j
    return None


def download_job_files(client, job_id: str, out_dir: str) -> list[str]:
    """Download every file of a done job INDIVIDUALLY.

    Per-file is the only path that verifies the sha256 from the job manifest and resumes by HTTP
    Range; the whole-job zip does neither. Re-download is FREE for 30 days, so this is also the
    rollback path -- never re-submit inside the window."""
    files = call_with_backoff(client.batch.list_files, job_id)
    paths: list[str] = []
    for entry in files:
        name = entry["filename"]
        got = call_with_backoff(client.batch.download, job_id, out_dir, filename_to_download=name)
        paths.extend(str(p) for p in got)
    logger.info("downloaded %d file(s) for job %s", len(paths), job_id)
    return paths


# ---------------------------------------------------------------------------
# raw landing
# ---------------------------------------------------------------------------
# The raw filenames are OWNED BY leviathan.storage.paths and shared with jobs/batch/futures_eod_task
# -- the writer and the reader run back to back in one Step Function, so two independent derivations
# is a chain that cannot read the payload it just bought. Re-exported under the local names the
# rest of this module (and its tests) use.
symbology_filename = databento_symbology_filename
payload_filename = databento_payload_filename


def land_bytes(bucket: str, key: str, data: bytes, *, source_label: str, content_type: str,
               region: str, min_size_source: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, min_size_source, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_label, content_type, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict. The
    payload IS re-derivable here; what the swallow-all idiom buys is a PURCHASE. The next statement
    after this probe returns False is ``submit_unit``, a billable batch job, so a throttled
    ``HeadObject`` re-buys a payload the estate already owns (IFUS $34.28, IFEU $6.18, against a
    $125 credit pool) and overwrites the good one with it. An S3 hiccup must not be able to spend.

    The 403-instead-of-404 trap does NOT apply on this leg: ``batch_job_role`` carries
    ``s3:ListBucket`` on the bucket (infra/terraform/modules/iam/main.tf, sid
    ``ListDataLakeBucket``), so a HeadObject against a key that does not exist answers 404 rather
    than AccessDenied -- the narrowing cannot brick a first-ever capture.
    """
    from botocore.exceptions import ClientError
    from leviathan.storage.s3 import get_thread_local_s3_client

    try:
        get_thread_local_s3_client(region).head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error = exc.response.get("Error") or {}
        code = str(error.get("Code") or "")
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        # HeadObject has no body, so botocore reports the missing-key case as "404"/"NotFound"
        # rather than the "NoSuchKey" a GetObject would raise. Accept all three spellings.
        if code in _ABSENT_ERROR_CODES or status == 404:
            return False
        raise


# ---------------------------------------------------------------------------
# unit selection
# ---------------------------------------------------------------------------
def select_units(roots: list[str], years: Optional[list[int]], through_year: int
                 ) -> list[tuple[str, str, int]]:
    """``[(dataset, root, year), ...]`` sorted, for the requested roots/years."""
    out: list[tuple[str, str, int]] = []
    for root in roots:
        dataset = ROOT_MAP[root][0]
        candidates = root_years(root, through_year)
        for year in (years if years else candidates):
            if year not in candidates:
                logger.info("skip %s/%s: before the root's first usable year (%s)",
                            root, year, ROOT_FIRST_DATE[root])
                continue
            out.append((dataset, root, int(year)))
    return sorted(out)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s -- %(message)s",
                        stream=sys.stderr)
    ap = argparse.ArgumentParser(description="Databento futures EOD raw producer (W2 / D1 + D5)")
    ap.add_argument("--mode", choices=["backfill", "incremental"], required=True)
    ap.add_argument("--root", action="append", dest="roots", default=None,
                    choices=sorted(ROOT_MAP), help="repeatable; default = all 16")
    ap.add_argument("--year", action="append", type=int, dest="years", default=None,
                    help="repeatable; backfill only. Default = every usable year for the root")
    ap.add_argument("--through-year", type=int, default=None,
                    help="last backfill year (default: the current UTC year)")
    ap.add_argument("--since", default=None,
                    help="incremental mode: inclusive first trade date, YYYY-MM-DD")
    ap.add_argument("--lookback-days", type=int, default=5,
                    help="incremental mode, used when --since is absent: request the last N "
                         "calendar days. The scheduler can only substitute <aws.scheduler.*> "
                         "context attributes, so the scheduled chain passes THIS rather than a "
                         "templated date. 5 matches the registry freshness_sla max_lag_days, and "
                         "re-requesting the overlap costs $0.08 at the measured $0.016/day")
    ap.add_argument("--cost-only", action="store_true",
                    help="resolve + get_cost and print the table; submit NOTHING (the pre-buy gate)")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD,
                    help=f"BUDGET CEILING for --cost-only: exit 1 when the grand total exceeds it "
                         f"(default {DEFAULT_MAX_USD:.2f}; may not exceed {HARD_CEILING_USD:.2f}). "
                         f"The recommended buy is $45.00; the naive parent pull the outright filter "
                         f"prevents is $140.31 against $125 of credits, so a gate that only PRINTS "
                         f"the number is not a gate")
    ap.add_argument("--no-statistics", action="store_true",
                    help="skip the GLBX statistics leg (it is $1.76 and load-bearing -- see the "
                         "plan's DO NOT OPTIMIZE AWAY note; this exists for repair runs only)")
    ap.add_argument("--download-dir", default=None,
                    help="local staging dir for batch downloads (default: a temp dir)")
    ap.add_argument("--poll-seconds", type=int, default=30)
    ap.add_argument("--max-wait-seconds", type=int, default=7200)
    ap.add_argument("--force-overwrite", action="store_true")
    ap.add_argument("--secret-id", default=DATABENTO_SECRET_ID,
                    help="Secrets Manager secret NAME holding the key (never the value)")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the units and the S3 keys, then return; no network, no key needed")
    args = ap.parse_args(argv)

    roots = args.roots or sorted(ROOT_MAP)
    through_year = args.through_year or datetime.now(tz=timezone.utc).year
    today = datetime.now(tz=timezone.utc).date()

    if args.mode == "incremental":
        since = (datetime.strptime(args.since, "%Y-%m-%d").date() if args.since
                 else today - timedelta(days=max(1, args.lookback_days)))
        args.since = since.isoformat()
        units = [(ROOT_MAP[r][0], r, since.year) for r in roots]
    else:
        units = select_units(roots, args.years, through_year)
    if not units:
        logger.error("no (root, year) units selected")
        return 1

    if args.dry_run:
        print(f"units: {len(units)}")
        for dataset, root, year in units:
            ds = DATASET_SLUGS[dataset]
            print(f"  {dataset:<13s} {root:<4s} {year}  ->  "
                  f"s3://<bucket>/{raw_databento_key(ds, root, year, symbology_filename(root, year))}")
            for schema in schemas_for(dataset, root, no_statistics=args.no_statistics):
                print(f"                              "
                      f"s3://<bucket>/{raw_databento_key(ds, root, year, payload_filename(schema, root, year))}")
            if root in SETTLEMENT_TAPE_ROOTS:
                fence = ("NON-BLOCKING unit: any failure is logged, counted and skipped"
                         if args.mode == "incremental" else
                         "BLOCKING unit: a thin/empty payload is FAILED, exit 1")
                print(f"                              (settlement-tape root: statistics ONLY, "
                      f"no ohlcv-1d; {args.mode}: {fence})")
        return 0

    load_env()
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    client = make_client(load_api_key(args.secret_id, aws_region))

    if args.cost_only:
        if args.max_usd > HARD_CEILING_USD:
            logger.error("--max-usd %.2f exceeds the hard ceiling %.2f (the credit pool) -- "
                         "refusing to quote against a ceiling that cannot be honoured",
                         args.max_usd, HARD_CEILING_USD)
            return 1
        # An incremental quote must price the INCREMENTAL window, not the calendar year it lands in.
        override = None
        if args.mode == "incremental":
            override = (args.since, (today + timedelta(days=1)).isoformat())
        table = build_cost_table(client, units, with_statistics=not args.no_statistics,
                                 window_override=override)
        print(render_cost_table(table))
        # Fail-closed: a zero drop count means the outright filter did not run, and buying on that
        # basis is how a $140.31 parent-symbology pull happens.
        if table["zero_drop_roots"]:
            return 1
        if table["grand_total_usd"] > args.max_usd:
            logger.error("BUDGET GATE: grand total $%.4f exceeds --max-usd $%.2f -- refusing. The "
                         "recommended buy is $45.00; $140.31 is the naive parent-symbology pull "
                         "the outright filter exists to prevent",
                         table["grand_total_usd"], args.max_usd)
            print(f"BUDGET GATE FAILED: {table['grand_total_usd']:.4f} > --max-usd {args.max_usd:.2f}")
            return 1
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    import tempfile
    out_dir = args.download_dir or tempfile.mkdtemp(prefix="databento_")

    failures = 0
    thin = 0
    skipped = 0
    skipped_units: list[str] = []
    for dataset, root, year in units:
        ds = DATASET_SLUGS[dataset]
        settlement_tape = root in SETTLEMENT_TAPE_ROOTS
        # The settlement-tape unit is non-blocking in the NIGHTLY only (see SETTLEMENT-TAPE ROOTS
        # in the module docstring). Computed ONCE per unit and consulted by every handler below:
        # backfill stays blocking, so an operator buy that lands nothing is FAILED / exit 1 (K6).
        nonblocking = settlement_tape and args.mode == "incremental"
        try:
            art = resolve_outrights(client, dataset=dataset, root=root, year=year)
            if args.mode == "incremental":
                since = datetime.strptime(args.since, "%Y-%m-%d").date()
                win = incremental_window(client, dataset, since, today)
                if win is None:
                    # SKIP, not a failure: `since` is at or past the vendor's available end, so
                    # there is nothing new to buy. Deliberately BEFORE the symbology land_bytes
                    # below -- an empty window must never overwrite a good artifact -- and it
                    # does NOT touch `failures`, so the run still exits 0.
                    logger.warning("%s %s/%s: SKIP -- since=%s is at or past the dataset "
                                   "available end %s; no new vendor data to buy",
                                   dataset, root, year, since.isoformat(),
                                   dataset_available_end(client, dataset).isoformat())
                    continue
                art["window"] = {"start": win[0], "end_exclusive": win[1]}
                art["mode"] = "incremental"
            as_of = today.strftime("%Y%m%d") if args.mode == "incremental" else None

            sym_key = raw_databento_key(ds, root, year, symbology_filename(root, year))
            land_bytes(bucket, sym_key,
                       json.dumps(art, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8"),
                       source_label=f"databento symbology.resolve {dataset} {root}.FUT {year}",
                       content_type="application/json", region=aws_region,
                       min_size_source="databento_symbology")
            if not art["outright_symbols"]:
                logger.warning("%s %s/%s: no outrights -- nothing to buy", dataset, root, year)
                continue

            schemas = schemas_for(dataset, root, no_statistics=args.no_statistics)
            if not schemas:
                raise RuntimeError(f"{root}/{year}: --no-statistics on a settlement-tape root "
                                   f"buys NOTHING (its tape IS the statistics stream)")
            for schema in schemas:
                key = raw_databento_key(ds, root, year, payload_filename(schema, root, year, as_of))
                # THE ONLY raw_exists CALL SITE ON THIS LEG, and the next statement is a BILLABLE
                # submit. raw_exists now fails CLOSED, and the raise deliberately gets NO handler of
                # its own: it falls to the per-unit `except` below, which is already the loud,
                # correct behaviour -- "FAILED <dataset> <root>/<year>", failures += 1, and the run
                # exits 1. Nothing is submitted for this unit, nothing is overwritten, and the other
                # units still run. There is no "nothing to fetch" exit-0 path on this producer for
                # such a run to fall through to: the only early return is the empty-unit-set exit 1
                # far above, and the final line is `return 1 if failures else 0`. (The ONE unit
                # that is skipped rather than FAILED is a settlement-tape root in incremental mode,
                # and it is skipped LOUDLY: SETTLEMENT_TAPE_SKIPPED + a counter in the done line.)
                if not args.force_overwrite and raw_exists(bucket, key, aws_region):
                    logger.info("skip %s (raw exists; --force-overwrite to replace)", key)
                    continue
                job = submit_unit(client, art, schema)
                job_id = job["id"]
                paths = wait_and_download(client, job_id, out_dir,
                                          poll_seconds=args.poll_seconds,
                                          max_wait_seconds=args.max_wait_seconds)
                payloads = [p for p in paths if p.endswith(".dbn.zst")]
                try:
                    if not payloads:
                        raise EmptyVendorPayload(
                            f"{root}/{year} {schema}: expected exactly ONE .dbn.zst from job "
                            f"{job_id} (split_duration='none'), got 0: the vendor job completed "
                            f"with NO payload file")
                    if len(payloads) != 1:
                        raise RuntimeError(
                            f"{root}/{year} {schema}: expected exactly ONE .dbn.zst from job "
                            f"{job_id} (split_duration='none'), got {len(payloads)}: {payloads}")
                    with open(payloads[0], "rb") as fh:
                        data = fh.read()
                    land_bytes(bucket, key, data,
                               source_label=f"databento batch {dataset} {schema} {root} job={job_id}",
                               content_type="application/zstd", region=aws_region,
                               min_size_source="databento")
                except Exception as exc:  # noqa: BLE001
                    if not (nonblocking and _is_thin_payload_error(exc)):
                        raise
                    # NON-BLOCKING (V2-4 m10) -- incremental (nightly) ONLY; backfill stays
                    # blocking (the raise above falls to the per-unit handler -> FAILED, exit 1).
                    # A thin/empty statistics payload on a settlement-MARK tape is logged and
                    # skipped, never a family-wide red. Nothing is landed for it (the size floor
                    # refused the bytes), the next fire re-covers the window, and the silver task
                    # judges the unit on its own verdict.
                    thin += 1
                    logger.warning(
                        "SETTLEMENT_TAPE_THIN %s %s/%s %s: %s: %s -- non-blocking (the mark tape "
                        "delivered nothing usable for this window; nothing landed, run continues)",
                        dataset, root, year, schema, type(exc).__name__, exc)
        except SystemExit as exc:
            # A STEP-2 / F-A SystemExit out of resolve_outrights. On any other root (or in
            # backfill) it aborts the process as it always did; on the nightly's settlement-tape
            # unit it must not strand the roots sorted after it (the DAG runs all 16 in one task).
            if not nonblocking:
                raise
            skipped += 1
            skipped_units.append(f"{root}/{year}")
            logger.error("SETTLEMENT_TAPE_SKIPPED %s %s/%s: %s: %s -- non-blocking (incremental "
                         "settlement-tape unit; nothing landed, nothing re-submitted, the run "
                         "continues so the other roots' promote is never staled by this root)",
                         dataset, root, year, type(exc).__name__, exc)
        except Exception as exc:  # noqa: BLE001 -- one unit's failure must not abort the rest
            if nonblocking:
                skipped += 1
                skipped_units.append(f"{root}/{year}")
                logger.error("SETTLEMENT_TAPE_SKIPPED %s %s/%s: %s: %s -- non-blocking "
                             "(incremental settlement-tape unit; nothing landed, nothing "
                             "re-submitted, the run continues so the other roots' promote is "
                             "never staled by this root)",
                             dataset, root, year, type(exc).__name__, exc)
                continue
            logger.exception("FAILED %s %s/%s", dataset, root, year)
            failures += 1

    logger.info("done -- units=%d failures=%d thin_settlement_tape_payloads=%d "
                "settlement_tape_skipped=%d%s",
                len(units), failures, thin, skipped,
                (" skipped_units=" + ",".join(skipped_units)) if skipped_units else "")
    return 1 if failures else 0


def wait_and_download(client, job_id: str, out_dir: str, *, poll_seconds: int = 30,
                      max_wait_seconds: int = 7200) -> list[str]:
    """Poll a batch job to ``done``, then download its files individually.

    ``list_jobs`` default filter hides EXPIRED, which is the only client-observable signal that the
    free 30-day re-download window has closed -- so it is polled explicitly here."""
    waited = 0
    while waited <= max_wait_seconds:
        detail = call_with_backoff(client.batch.get_job_details, job_id)
        state = str(detail.get("state", "")).lower()
        if state == "done":
            return download_job_files(client, job_id, out_dir)
        if state == "expired":
            raise RuntimeError(f"job {job_id} is EXPIRED -- the free 30-day re-download window "
                               f"has closed; a re-submit is a NEW charge")
        time.sleep(poll_seconds)
        waited += poll_seconds
    raise TimeoutError(f"job {job_id} did not reach 'done' within {max_wait_seconds}s")


if __name__ == "__main__":
    raise SystemExit(main())
