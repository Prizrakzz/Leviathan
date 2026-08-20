"""PRICE_AND_PLAYBOOKS W1a -- CEPEA bronze -> ``silver_futures_eod`` rows (the CASH references).

This is the one leg in the table whose rows are NOT futures, and every difference follows from
that single fact:

  * ``instrument_kind = 'cash_index'`` and ``contract_month`` is **NULL**. These two slugs are
    exactly ``futures_eod_contracts.CASH_INDEX_SLUGS``, and ``lint_frame`` enforces the iff in
    BOTH directions -- a futures row with a null month and a cash row with a month are equally
    rejected. That rule is load-bearing rather than tidy: ``contract_month`` is part of the natural
    key ``(leviathan_slug, contract_month, trade_date)``, so N rows with a null month collapse to
    ONE key and the contract's ``duplicate_check: full`` cannot see it, because SQL treats every
    NULL as distinct;
  * ``settle_kind = 'cash_index'`` (map-derived) -- the honesty label. This number is a published
    spot reference, not an exchange settlement and not a mark;
  * ``raw_symbol`` is **NULL**. There is no vendor contract symbol for a cash index, and inventing
    a synthetic one would violate the registry's "raw_symbol is verbatim and is NEVER parsed into
    meaning at ingest" note in the opposite direction. NOTE the consequence, which is handled in
    ``jobs/batch/futures_eod_task.py`` rather than here: the F2 assertion groups on
    ``(leviathan_slug, trade_date, raw_symbol)`` precisely so that two NULL-symbol cash rows on one
    date -- arabica and Campinas corn -- are not read as a duplicate;
  * OHLC, ``volume`` and ``open_interest`` are all NULL BY SOURCE: a cash reference publishes one
    number per day and nothing else. ``settle`` carries it;
  * ``futures_roll.ROLL_METHOD_BY_SOURCE`` routes ``cepea -> none`` and ``front_month`` DROPS these
    rows rather than passing them through -- naming a front month for a cash index is a category
    error, and that is decided there, not here.

SOURCE FIDELITY: the value is the published ``A vista R$`` figure, in BRL per 60-kg bag, unscaled
and unconverted. The archive workbook's ``A vista US$`` column is discarded upstream in the bronze
transform and never appears here in any form.

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.cepea import CEPEA_INDICATORS

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_CEPEA_SLUGS: frozenset[str] = frozenset(CEPEA_INDICATORS.values())

# ---------------------------------------------------------------------------
# D-PR-19 / D-PR-46 / D-PR-48 -- the SESSION-GAP assertion
# ---------------------------------------------------------------------------
# The producer's served-date verdict stops a stale capture from landing. It cannot make a LOST
# session come back: the widget serves the last value only, the fetch takes no window, and
# ``cepea_units(..., since=...)`` only re-enumerates raw objects that already landed. So the
# detector for "a session went missing" has to live here, on the assembled silver frame, and it has
# to fire at the NEXT fire rather than the one that lost the day.
#
# WHAT COUNTS AS A HOLE, AND WHY THE OBVIOUS TEST IS WRONG (D-PR-46). A bare business-day
# contiguity check reds every Brazilian holiday -- Jan 1, Carnival, Apr 21, May 1, Corpus Christi,
# Sep 7, Oct 12, Nov 2, Nov 15, Nov 20, Dec 25 -- roughly TEN false alarms a year, because a
# holiday leaves the series byte-identical to a lost session (the widget re-serves, the transform
# reads the payload date, ``drop_duplicates`` collapses the row). A curated BR holiday calendar was
# rejected on doctrine: this estate lets THE VENUE decide which days exist. So a hole is defined
# against a VENUE SESSION SET supplied by the caller -- days a Brazilian venue is known to have
# traded -- and never against a calendar this module invents.
#
# THE ASSERTION IS INERT WITHOUT ONE, ON PURPOSE. ``venue_sessions=None`` returns no violations and
# says so in the log. That is the honest failure mode: refusing to guess is a no-op, and a no-op
# that announces itself is recoverable, whereas ten false reds a year is the exact trade this wave
# exists to refuse.
#
# WINDOW-ONLY, AND WAIVED DATES (D-PR-48). The check is FRONTIER-RELATIVE: it looks only inside the
# window the frame itself covers, never at the whole series. Without that, one backfill spanning
# July would red permanently on the known 2026-07-29 hole -- a self-inflicted repeat offender
# introduced by the item meant to forbid them. ``CEPEA_WAIVED_SESSIONS`` is the explicit escape,
# seeded with that one date, and every entry in it is a DECLARED permanent absence, not a silence.

# Sessions this estate has declared permanently absent, with the reason. 2026-07-29 is measured and
# irrecoverable from the scheduled route: the only artifact that could hold it was fetched at
# 2026-07-29T18:47:23Z, BEFORE that day's ~21:00Z publication, so the bytes end at 07-28. Recovery
# is a USER DECISION on a CC BY-NC / robots-Disallow one-shot route (D-PR-21) and is not automated
# anywhere. If that decision lands the day, DELETE the entry -- do not leave a waiver over data.
CEPEA_WAIVED_SESSIONS: frozenset[str] = frozenset({"2026-07-29"})

# The canonical series D-PR-46 names as the session calendar.
#
# STATED PLAINLY BECAUSE IT MATTERS: this slug is one of the two CEPEA cash references
# (``CEPEA_INDICATORS[77]``), so a session set derived from it is derived from THIS LEG'S OWN
# OUTPUT. A day CEPEA never published is missing from that series too, which means the expected set
# and the present set omit the same day and the hole cancels out -- the detector reports GREEN on
# exactly the defect it exists to catch. :func:`session_calendar_conflicts` states that at runtime
# rather than letting a green report imply coverage. A genuinely independent Brazilian venue series
# has to name the calendar before this assertion can be armed.
CEPEA_SESSION_CALENDAR_SLUG = "campinas_corn_reference_bmf"


def build_cepea_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more CEPEA bronze frames (already concatenated) -> the silver producer frame."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "value_brl"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"cepea silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _CEPEA_SLUGS)
    if alien:
        raise ValueError(
            f"cepea silver: slug(s) {alien} are not CEPEA cash references -- this leg owns exactly "
            f"the {sorted(_CEPEA_SLUGS)} pair, which is also the ONLY pair permitted a NULL "
            f"contract_month"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    # NULL, and mandatory: the cash-index half of lint_frame's iff.
    out["contract_month"] = pd.Series(pd.NA, index=df.index, dtype="string")
    out["instrument_kind"] = "cash_index"
    # NULL, and deliberate: a cash reference has no vendor contract symbol to carry verbatim.
    out["raw_symbol"] = pd.Series(pd.NA, index=df.index, dtype="string")
    out["settle"] = pd.to_numeric(df["value_brl"], errors="coerce").astype("float64")
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    # NULL BY SOURCE: one published number per day, no session shape and no book behind it.
    for col in ("open", "high", "low", "close"):
        out[col] = pd.Series(float("nan"), index=df.index, dtype="float64")
    for col in ("volume", "open_interest"):
        out[col] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    out["unit"] = df["leviathan_slug"].map({s: r["unit"] for s, r in recs.items()})
    out["currency"] = df["leviathan_slug"].map({s: r["currency"] for s, r in recs.items()})
    out["expiry_date"] = pd.Series(pd.NaT, index=df.index).astype("datetime64[us]")
    out["source"] = df["leviathan_slug"].map({s: r["source"] for s, r in recs.items()})
    out["dataset"] = pd.Series(pd.NA, index=df.index, dtype="string")

    out["leviathan_slug"] = df["leviathan_slug"].astype("string")
    year = out["trade_date"].dt.year
    if year.isna().any():
        raise ValueError("cepea silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    # A cash reference publishes at most ONE value per slug per day. The widget re-serves the last
    # value on a holiday, and a backfill that re-reads the same snapshot would otherwise stack
    # exact duplicates -- both of which the natural-key assertion downstream would turn into a
    # hard fail with a confusing diagnosis. Identical rows are collapsed HERE, where the fact is
    # local; a genuine CONFLICT (two different values for one slug-day) is left to fail loudly.
    before = len(out)
    out = out.drop_duplicates(subset=["leviathan_slug", "trade_date", "settle"], keep="last")
    collapsed = before - len(out)

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "trade_date"], kind="mergesort").reset_index(drop=True)

    logger.info("cepea silver: %d rows (%d identical duplicate(s) collapsed), %d slug(s), %s..%s",
                len(out), collapsed, len(slugs),
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out


def session_calendar_conflicts(calendar_slug: str = CEPEA_SESSION_CALENDAR_SLUG) -> list[str]:
    """Reasons ``calendar_slug`` cannot serve as this leg's session calendar. Empty == usable.

    One reason today, and it is disqualifying: a CEPEA slug cannot decide which sessions CEPEA
    should have published. Every day this leg loses is absent from both sides of the comparison, so
    the difference is empty and the assertion returns GREEN on the very defect it was built for."""
    if calendar_slug in _CEPEA_SLUGS:
        return [f"{calendar_slug!r} is a CEPEA cash reference produced by THIS leg -- a session "
                f"calendar derived from it omits exactly the days CEPEA lost, so the hole cancels "
                f"out and the assertion cannot detect anything. Name an independent Brazilian "
                f"venue series, or leave the assertion inert"]
    return []


def cepea_session_gaps(silver: pd.DataFrame, *,
                       venue_sessions: Optional[Iterable] = None,
                       window_start=None, window_end=None,
                       waived: Iterable[str] = CEPEA_WAIVED_SESSIONS,
                       calendar_slug: str = CEPEA_SESSION_CALENDAR_SLUG) -> list[str]:
    """Sessions the venue traded that CEPEA did not publish, over THIS frame's window only.

    Returns the violating days as strings (empty == pass), the same shape
    ``futures_eod_task.assert_row_floor`` returns, so the caller decides what a violation costs.

    ``venue_sessions``  ISO dates a Brazilian venue is known to have traded. **Required for the
                        assertion to do anything**: with ``None`` this returns ``[]`` and logs that
                        it did nothing, because the only alternative -- a plain business-day
                        contiguity test -- fires on ~10 Brazilian holidays a year (D-PR-46).
    ``window_start/end`` default to the frame's own min/max ``trade_date``. FRONTIER-RELATIVE by
                        default and never whole-series (D-PR-48): a check that reached behind its
                        own window would red permanently on any known historical hole.
    ``waived``          declared permanent absences, seeded with 2026-07-29 (D-PR-21).

    Two violation classes, and the second is trap (ii) made visible: a HOLE is a session no CEPEA
    slug published, and a HALF-DAY is a session only SOME slugs published. The per-day floor is an
    equality (``== 2``), so a half-day is already a floor violation -- naming it here says WHICH
    indicator went missing, which the floor cannot."""
    if silver is None or len(silver) == 0:
        return []
    if venue_sessions is None:
        logger.warning(
            "cepea session-gap assertion: INERT -- no venue session calendar was supplied, so no "
            "hole can be asserted. This is deliberate: a bare business-day contiguity test reds "
            "every Brazilian holiday (~10/yr) and a curated holiday calendar is refused on "
            "doctrine. Supply venue_sessions from an independent canonical Brazilian venue series "
            "to arm it (D-PR-46)")
        return []
    for conflict in session_calendar_conflicts(calendar_slug):
        logger.error("cepea session-gap assertion: the configured session calendar is UNUSABLE and "
                     "a PASS from this call proves nothing -- %s", conflict)

    days = pd.to_datetime(silver["trade_date"], errors="coerce")
    present_by_slug: dict[str, set[str]] = {}
    for slug in sorted(set(silver["leviathan_slug"].dropna())):
        mask = silver["leviathan_slug"] == slug
        present_by_slug[str(slug)] = {str(d)[:10] for d in days[mask].dropna()}
    if not present_by_slug:
        return []

    lo = str(window_start)[:10] if window_start is not None else str(days.min())[:10]
    hi = str(window_end)[:10] if window_end is not None else str(days.max())[:10]
    waived_set = {str(d)[:10] for d in waived}
    in_window = {d for d in ({str(d)[:10] for d in venue_sessions}) if lo <= d <= hi}
    waived_in_window = in_window & waived_set
    expected = in_window - waived_set

    everywhere = set.intersection(*present_by_slug.values())
    anywhere = set.union(*present_by_slug.values())

    violations: list[str] = []
    for day in sorted(expected - anywhere):
        violations.append(
            f"{day}: the venue traded but CEPEA published NO value -- a lost session. It cannot be "
            f"recovered from the scheduled route (the widget serves the last value only), so this "
            f"is a permanent hole unless the one-shot series route is run under D-PR-21")
    for day in sorted((expected & anywhere) - everywhere):
        missing = sorted(s for s, seen in present_by_slug.items() if day not in seen)
        violations.append(
            f"{day}: a HALF day -- no value for {missing}. The per-day floor is an equality, so "
            f"this day is a floor violation too; the indicator(s) named here are why")
    logger.info("cepea session-gap assertion: window %s..%s, %d expected session(s), %d waived, "
                "%d violation(s)", lo, hi, len(expected), len(waived_in_window), len(violations))
    return violations
