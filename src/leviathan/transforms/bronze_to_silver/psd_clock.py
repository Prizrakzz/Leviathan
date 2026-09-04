"""THE PSD CLOCK -- one function, one implementation, three lanes.

WHAT THIS MODULE IS FOR
-----------------------
Until 2026-09 the PSD silver producer derived ``release_date`` from a MARKETING-YEAR
ROTATION: it read ``month_code`` as an MY-relative index and rotated it by the
commodity's marketing-year start month (``_PSD_COMMODITY_TO_MYS``).  MEASURED on
three banked bronze snapshots (2026-05-20, 2026-07-17, 2026-08-13):

  * the rotation is EXACT on 3,276 of 1,653,988 stamped rows (0.20%), fabricated
    EARLIER on 1,610,971 (97.4%) and LATER on 39,741 (2.4%);
  * ZERO of the 47 MAPPED commodity codes agree with the source at 100%;
  * it emits 809 distinct dates, of which 708 are dates USDA never published, and
    it never produces 338 dates that USDA did.  BOTH DAY RULES ARE STATED because
    only one of the two figures moves with the rule: the 338 is measured under
    E-day-B, the SHIPPED rule (the eight World Markets and Trade sheets on
    month-end); under E-day-A, a uniform WASDE day, the same count is 186.  The
    708 fabricated-only dates are IDENTICAL under both, because that count
    depends only on the fabricated side.

The bulk CSV already carries the truth in two columns -- ``Calendar_Year`` and
``Month`` -- and those two ARE the release stamp.  This module turns that stamp
into a date, and it is the ONLY implementation of that rule in the estate.  The
monthly wide producer, the long attribute companion and (when it lands) the
archive backfill all call it.  A per-lane copy is a guaranteed drift and a kill
condition: the next monthly promote would rewrite ``silver_psd`` under everyone
with a different clock.

THE STAMP IS THE MONTH; THE DAY IS A CONVENTION
-----------------------------------------------
USDA publishes a release month, not a release day, in this file.  The MONTH is
the source's own stamp and is never invented here.  The DAY comes from one of
FOUR declared conventions, each NAMED and COUNTED by :func:`psd_release_dates`
so no reader can mistake a convention for a measurement:

  ``registered_wasde_day``  the day of the WASDE release registered for that
                            calendar month in ``silver_wasde`` (days 8..14 over
                            2006+, with the declared 2008-10-28 exception once
                            that partition is backfilled).
  ``month_end_wmt``         the LAST day of the stamp month, for the EIGHT World
                            Markets and Trade circular sheets in
                            :data:`_PSD_MONTH_END_CODES`.  Those sheets do NOT
                            ride the WASDE day; month-end is the PIT-conservative
                            direction (late, never early).
  ``month_end_fallback``    the LAST day of the stamp month, for a stamp month
                            our OWN ``silver_wasde`` does not carry.  Measured
                            exposure today: exactly two months, 2006-07 and
                            2008-10, covering 51,415 of 247,294 wide rows
                            (20.79%) -- 51,259 and 156 -- 99.70% of it 2006-07.
                            THAT COUNT IS KEYED ON THE DISPOSITION, not on the
                            release month: 39 further wide rows (5 in 2006-07, 34
                            in 2008-10) are WM&T sheets that take ``month_end_wmt``
                            in those same months and land on the same day, and a
                            month-keyed counter reported 51,454 by absorbing them.
                            Month-end is PIT-conservative: an absent entry may only
                            make a number appear LATER, never earlier.
  ``mc_zero_anchor``        ``month_code == 0`` -- the pre-WASDE-tracking mass
                            (marketing years ~1960-2004).  Anchored to 1 January
                            of the MARKETING year, unchanged from the shipped
                            producer, so those rows stay visible to any crop-year
                            cutoff.  Their ``Calendar_Year`` is an observation-year
                            label, not a publication stamp: MEASURED on 245,315
                            in-scope mc==0 rows the difference (calendar_year -
                            market_year) is 0 on 73.3%, -1 on 24.3% and +1 on
                            2.4%, so re-anchoring them on Calendar_Year would move
                            59,544 rows EARLIER -- the leakage direction this whole
                            change exists to close.

FAIL CLOSED, NEVER FALL BACK ON THE FRESHEST RELEASE
----------------------------------------------------
A stamp month strictly NEWER than the newest month in the supplied calendar
RAISES.  It is never quietly given a month-end day.  ``silver_wasde``'s newest
partition and the newest PSD stamp advance in LOCKSTEP every month, so a silent
fallback there would move TODAY's citation by up to ~19 days with no counter.
The raise is the ordering alarm; it is not a staleness workaround, which is why
the calendar is READ AT RUN TIME from the registered partitions and never baked
into the worker image.

A MISSING STAMP IS A REFUSAL, NEVER A DEFAULT
---------------------------------------------
The stamp columns arrive from bronze already COERCED: ``raw_to_bronze/usda_psd.py``
casts ``month_code`` with ``pd.to_numeric(..., errors='coerce').astype('Int64')``,
so an unparseable value lands as NA with no log line, and ``calendar_year`` is not
in that cast's column set at all.  An earlier cut of this module answered a
``fillna(0)`` -- which turned a missing ``calendar_year`` into the INVENTED date
``0000-05-31`` on the ``month_end_fallback`` convention, and a missing or negative
``month_code`` into a silent ``mc_zero_anchor`` at ``market_year-01-01``.  Both
sort BEFORE every historical asof, so both are the leakage class this whole lane
exists to close, produced by the one module whose docstring promises it never
invents a date.  They now RAISE:

  * ``month_code`` NA or negative -> :class:`PsdClockError` (0 stays the declared
    pre-WASDE-tracking anchor; it is a value, not a gap);
  * ``calendar_year`` NA or non-positive on a STAMPED row (``month_code > 0``)
    -> :class:`PsdClockError`.

MEASURED: the three banked bronze snapshots carry ZERO nulls in either column,
in scope and out (0 of 2,088,504 / 2,090,920 / 2,092,687 rows), so this fence is
INERT on today's substrate.  It is a fence against a source-format change and
against a bronze re-parse, not a repair of a known hole.

PURE
----
No S3, no AWS, no module-level calendar, no import of the generated fixture.  The
calendar arrives as a ``{'YYYY-MM': day}`` dict, keyword-only and with NO DEFAULT,
at every seam.  A default is a silent fallback to a stale or empty calendar.
"""
from __future__ import annotations

from calendar import monthrange

import pandas as pd

# ---------------------------------------------------------------------------
# The eight World Markets and Trade sheet codes -- A LITERAL, never derived
# ---------------------------------------------------------------------------
# These sheets ship with USDA's WM&T circulars, NOT with the monthly WASDE, so
# the registered WASDE day is the wrong day for them and month-end is the
# PIT-conservative substitute.
#
# THE SET IS WRITTEN OUT AND IT MUST STAY WRITTEN OUT.  It cannot be generated
# from a publishing-cadence threshold, and trying is a measured kill condition:
# fifteen of the 47 mapped codes publish in fewer than twelve calendar months, so
# a cadence rule captures FIFTEEN codes, fires the ingest clamp 160 times over the
# three banked snapshots (64 / 40 / 56) and produces a minimum gap of -18 days.
# Three of the seven extra codes it would catch -- 224200 (butter), 224400 (NFDM)
# and 230000 (WMP) -- are dairy siblings of set members 223000 and 240000 with the
# IDENTICAL {7, 12} cadence, so NO threshold can separate them.  With this
# eight-member literal the clamp fires ZERO times on all three snapshots and the
# WM&T rows keep 13 days of headroom to their own snapshot's ingest date
# (measured over 333,744 stamped WM&T rows).
#
# Each code's MEASURED publishing months (three banked snapshots, mapped roster):
#   111000 cattle and beef     {4, 7, 10, 11, 12}
#   114200 broiler meat        {4, 10, 11}
#   223000 fluid milk          {7, 12}
#   240000 cheese              {7, 12}
#   571120 oranges             {1, 2, 4, 7, 8, 10}
#   585100 orange juice        {1, 2, 3, 4, 7, 8, 10}
#   612000 sugar, centrifugal  {5, 10, 11, 12}
#   711100 coffee, green       {6, 7, 12}
#
# The complement over the mapped roster has 39 members.  Their cadence is
# REPORTED and asserted NOWHERE: 32 publish in all twelve calendar months and
# SEVEN do not (113000, 115000, 224200, 224400, 230000, 459900, 814200).  Those
# seven take the registered WASDE day anyway, because they are not WM&T circular
# sheets.  That sentence is the whole reason this is a literal.
_PSD_MONTH_END_CODES: frozenset[int] = frozenset({
    111000,   # cattle and beef
    114200,   # broiler meat
    223000,   # fluid milk
    240000,   # cheese
    571120,   # oranges (fresh citrus)
    585100,   # orange juice
    612000,   # sugar, centrifugal
    711100,   # coffee, green
})

# The four declared day dispositions.  Every row lands in exactly one of them and
# every one of them is counted by the producer and read by the gate.
DISPOSITION_WASDE_DAY = "registered_wasde_day"
DISPOSITION_MONTH_END_WMT = "month_end_wmt"
DISPOSITION_MONTH_END_FALLBACK = "month_end_fallback"
DISPOSITION_MC_ZERO = "mc_zero_anchor"

# The THREE clamp dispositions.  The clock never produces these -- the wide
# producer's ingest clamp does, by REPLACING one of the four above when a computed
# date post-dates the bronze snapshot that observed it.  They live here so the
# vocabulary of ``day_dispositions`` has ONE home: a gate reading whose value set
# is spelled in two modules is a gate reading nobody can enumerate.  All three are
# expected 0; see usda_psd.py step 4b for the rule and its measurement.
DISPOSITION_CLAMPED_TO_WASDE_DAY = "clamped_to_wasde_day"
DISPOSITION_CLAMPED_TO_INGEST = "clamped_to_ingest"
DISPOSITION_CLAMPED_CROSS_MONTH_DECLINED = "clamped_cross_month_declined"


class PsdClockError(ValueError):
    """A stamp the calendar cannot date.  Always fatal -- never a silent fallback."""


def _stamp_int(value: object, field: str) -> int:
    """``int(value)``, or :class:`PsdClockError` -- NA is a REFUSAL, never a default.

    See the module docstring's "A MISSING STAMP IS A REFUSAL" section: bronze
    coerces these columns silently, so the only place a gap can be caught is here.
    """
    try:
        missing = value is None or bool(pd.isna(value))
    except (TypeError, ValueError):          # a non-scalar -- let int() judge it
        missing = False
    if missing:
        raise PsdClockError(
            "PSD clock: %s is MISSING (NA/None) on a row it must date. Bronze coerces this "
            "column silently, so a gap here would otherwise become an INVENTED date that "
            "sorts before every historical asof. Refusing to date it." % field
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PsdClockError(
            "PSD clock: %s=%r is not an integer stamp. Refusing to date it." % (field, value)
        ) from exc


def _calendar_max_month(calendar: dict[str, int]) -> str:
    if not calendar:
        raise PsdClockError(
            "PSD clock: the WASDE release calendar is EMPTY. The calendar is read at run "
            "time from the registered silver_wasde partitions and is required; an empty "
            "one would date every row by convention with no measurement behind it."
        )
    return max(calendar)


def psd_release_date_and_disposition(
    commodity_code: int,
    market_year: int,
    calendar_year: int,
    month_code: int,
    *,
    calendar: dict[str, int],
) -> tuple[str, str]:
    """Return ``(release_date, disposition)`` for ONE PSD sheet-cell stamp.

    Args:
        commodity_code: The PSD six-digit sheet code.  Only used to test
            membership of :data:`_PSD_MONTH_END_CODES`.
        market_year: The row's marketing year.  Only used for ``month_code == 0``.
        calendar_year: The bulk file's ``Calendar_Year`` -- the calendar year of
            the release that minted this value.
        month_code: The bulk file's ``Month`` -- the CALENDAR month of that
            release, or 0 for the pre-WASDE-tracking mass.
        calendar: ``{'YYYY-MM': day}`` built from the REGISTERED silver_wasde
            partitions.  Keyword-only, no default, read at run time.

    Returns:
        ``(YYYY-MM-DD, disposition)`` where disposition is one of the four
        ``DISPOSITION_*`` constants.

    Raises:
        PsdClockError: If *calendar* is empty; if the stamp month is strictly
            newer than the newest month the calendar carries; if *month_code* is
            NA or negative; or if *calendar_year* is NA or non-positive on a
            stamped row.
    """
    max_month = _calendar_max_month(calendar)
    mc = _stamp_int(month_code, "month_code")
    if mc < 0:
        raise PsdClockError(
            "PSD clock: month_code=%d is NEGATIVE. Only 0 (the declared pre-WASDE-tracking "
            "anchor) and 1..12 are stamps; a negative value would fall through to the mc == 0 "
            "anchor and hide itself at market_year-01-01." % mc
        )
    if mc == 0:
        # THE SAME REFUSAL ON THE ANCHOR'S OWN INPUT (post-fix re-review M1): market_year is in
        # bronze's errors='coerce' set too, so an NA here would print '0000-01-01' -- the date that
        # sorts before every historical asof -- under the one disposition that never consults the
        # calendar. NA or non-positive is a raise, never a default.
        my = _stamp_int(market_year, "market_year")
        if my <= 0:
            raise PsdClockError(
                "PSD clock: market_year=%d is not a real year on an mc == 0 row. The anchor is "
                "market_year-01-01 and a year-0000 anchor would sort before every asof." % my
            )
        return "%04d-01-01" % my, DISPOSITION_MC_ZERO

    cy = _stamp_int(calendar_year, "calendar_year")
    if cy <= 0:
        raise PsdClockError(
            "PSD clock: calendar_year=%d is not a real year on a STAMPED row (month_code=%d). "
            "Dating it anyway would emit '%04d-%02d-...', a date that sorts before every "
            "historical asof." % (cy, mc, cy, mc)
        )
    stamp = "%04d-%02d" % (cy, mc)
    if stamp > max_month:
        raise PsdClockError(
            "PSD clock: stamp month %s is NEWER than the newest registered WASDE month "
            "%s. Refusing to date it by convention -- silver_wasde and the PSD stamp "
            "advance in lockstep, so this is an ordering problem worth stopping for, not "
            "a stale-artifact problem. Ingest the missing silver_wasde partition first."
            % (stamp, max_month)
        )

    month_end = monthrange(cy, mc)[1]
    if _stamp_int(commodity_code, "commodity_code") in _PSD_MONTH_END_CODES:
        return "%s-%02d" % (stamp, month_end), DISPOSITION_MONTH_END_WMT
    day = calendar.get(stamp)
    if day is None:
        return "%s-%02d" % (stamp, month_end), DISPOSITION_MONTH_END_FALLBACK
    return "%s-%02d" % (stamp, int(day)), DISPOSITION_WASDE_DAY


def psd_release_date(
    commodity_code: int,
    market_year: int,
    calendar_year: int,
    month_code: int,
    *,
    calendar: dict[str, int],
) -> str:
    """The clock's pinned shape: the release date for one stamp, as a string."""
    return psd_release_date_and_disposition(
        commodity_code, market_year, calendar_year, month_code, calendar=calendar,
    )[0]


def psd_release_dates(
    commodity_code: pd.Series,
    market_year: pd.Series,
    calendar_year: pd.Series,
    month_code: pd.Series,
    *,
    calendar: dict[str, int],
) -> tuple[pd.Series, pd.Series]:
    """Vectorised form of :func:`psd_release_date_and_disposition`.

    THIS IS NOT A SECOND IMPLEMENTATION.  It reduces the frame to its DISTINCT
    ``(commodity_code, calendar_year, month_code)`` stamps, calls the scalar
    function once per stamp, and maps the answers back.  The ``month_code == 0``
    rows are handled separately because their date is a function of market_year,
    which the stamp key does not carry.

    Returns:
        ``(dates, dispositions)``, both aligned to the input index.

    Raises:
        PsdClockError: Exactly where the scalar form raises, and for the same
            reasons -- including on a frame carrying ONLY ``month_code == 0``
            rows, which still needs a measured calendar.
    """
    # VALIDATE THE CALENDAR ONCE, UP FRONT.  The scalar form reaches
    # _calendar_max_month on every path, mc == 0 included; the vectorised form
    # short-circuits the mc == 0 rows, so without this line an empty calendar
    # would return dates here and RAISE there.  "This is not a second
    # implementation" has to hold on the error paths too.
    _calendar_max_month(calendar)

    code_raw = pd.to_numeric(commodity_code, errors="coerce")
    n_code_missing = int(code_raw.isna().sum())
    if n_code_missing:
        raise PsdClockError(
            "PSD clock: commodity_code is MISSING (NA) on %d row(s). The code decides whether a "
            "row takes the WM&T month-end or the registered WASDE day; a coerced 0 would silently "
            "take the WASDE day (re-review minor 1; the scalar form refuses the same value)."
            % n_code_missing
        )
    code = code_raw.astype("int64")
    # A MISSING STAMP IS A REFUSAL, NEVER A DEFAULT -- see the module docstring.
    # These two checks run BEFORE any fillna, because the fillna is exactly what
    # turned a coerced NA into an invented date.
    mc_raw = pd.to_numeric(month_code, errors="coerce")
    n_mc_missing = int(mc_raw.isna().sum())
    if n_mc_missing:
        raise PsdClockError(
            "PSD clock: month_code is MISSING (NA) on %d row(s). Bronze casts this column with "
            "errors='coerce', so an unparseable value arrives as NA with no log line; dating it "
            "as the mc == 0 anchor would hide it at market_year-01-01, before every historical "
            "asof." % n_mc_missing
        )
    mc = mc_raw.astype("int64")
    n_mc_negative = int((mc < 0).sum())
    if n_mc_negative:
        raise PsdClockError(
            "PSD clock: month_code is NEGATIVE on %d row(s) (first: %r). Only 0 and 1..12 are "
            "stamps." % (n_mc_negative, sorted(set(mc[mc < 0].tolist()))[:5])
        )
    cy_raw = pd.to_numeric(calendar_year, errors="coerce")
    stamped_mask = mc > 0
    bad_cy = stamped_mask & (cy_raw.isna() | (cy_raw <= 0))
    n_bad_cy = int(bad_cy.sum())
    if n_bad_cy:
        raise PsdClockError(
            "PSD clock: calendar_year is MISSING or non-positive on %d STAMPED row(s) "
            "(month_code > 0). calendar_year is not in bronze's integer-cast column set at all, "
            "so this is the column most likely to arrive unparsed; dating those rows anyway "
            "emits a year-0000 date that sorts before every historical asof." % n_bad_cy
        )
    cy = cy_raw.fillna(0).astype("int64")
    my_raw = pd.to_numeric(market_year, errors="coerce")
    bad_my = (~stamped_mask) & (my_raw.isna() | (my_raw <= 0))
    n_bad_my = int(bad_my.sum())
    if n_bad_my:
        raise PsdClockError(
            "PSD clock: market_year is MISSING or non-positive on %d mc == 0 row(s). The anchor "
            "is market_year-01-01, and market_year IS in bronze's errors='coerce' set, so an NA "
            "arrives silently and would print '0000-01-01' -- the invented-date class this module "
            "exists to refuse (post-fix re-review M1)." % n_bad_my
        )
    my = my_raw.fillna(0).astype("int64")

    dates = pd.Series(index=code.index, dtype="object")
    disp = pd.Series(index=code.index, dtype="object")

    stamped = stamped_mask
    if bool(stamped.any()):
        keys = pd.MultiIndex.from_arrays(
            [code[stamped], cy[stamped], mc[stamped]]
        ).unique()
        lookup: dict[tuple[int, int, int], tuple[str, str]] = {}
        for c_, y_, m_ in keys:
            lookup[(int(c_), int(y_), int(m_))] = psd_release_date_and_disposition(
                int(c_), 0, int(y_), int(m_), calendar=calendar,
            )
        triples = list(zip(code[stamped].tolist(), cy[stamped].tolist(), mc[stamped].tolist()))
        dates.loc[stamped] = [lookup[t][0] for t in triples]
        disp.loc[stamped] = [lookup[t][1] for t in triples]

    zero = ~stamped
    if bool(zero.any()):
        # Unchanged from the shipped producer: mc == 0 anchors to 1 January of the
        # MARKETING year, never the calendar year.  See the module docstring for
        # the 73.3 / 24.3 / 2.4 measurement that refutes the calendar-year reading.
        dates.loc[zero] = my[zero].astype(str).str.zfill(4) + "-01-01"
        disp.loc[zero] = DISPOSITION_MC_ZERO

    return dates, disp
