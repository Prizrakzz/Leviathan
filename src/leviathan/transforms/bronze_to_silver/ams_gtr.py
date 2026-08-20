"""Silver transform for the USDA AMS Grain Transportation Report (GTR) freight family.

Folds the family's seven bronze frames -- two channels, three cadences, three units --
into ONE tidy long series:

    dataset | series | route_or_reach | period_date | rate | unit

plus the point-in-time columns that make the row usable in a backtest, and the
qualifiers (``forward_month_offset``, ``rate_month``, ``commodity``, ``vessel_size``)
that are part of a row's identity in the datasets that carry them.

No S3 or AWS dependencies: pure data transformation.

Why long and not wide
---------------------
The family has no common measure.  A percent-of-tariff barge quote (~600-800), a
dollars-per-ton barge quote (~14-17) and a dollars-per-metric-ton ocean quote (~35-75)
describe different things in different units, and two of them describe the SAME barge
move.  A wide table would have to either invent one column per (dataset, series,
route) pair -- hundreds of them, mostly null -- or silently mix units in one column.
Long format with an explicit ``unit`` on every row is the only shape that cannot lie,
and it is what the lane specified.

The unit is never inferred here
-------------------------------
``unit`` is copied from :data:`~leviathan.transforms.raw_to_bronze.ams_gtr.GTR_DATASETS`,
which records what the SOURCE declares about each column, and the fetcher asserts that
declaration against the live metadata on every run
(:func:`~leviathan.transforms.raw_to_bronze.ams_gtr.assert_soda_unit_declaration`).
Nothing in this module decides what a number means.

Point-in-time
-------------
Every row carries three PIT columns, and they say different things on purpose:

``as_of_date``
    OBSERVED.  The date the bytes were fetched.  Never derived, never wrong.
``knowledge_date``
    The RELEASE date -- the earliest date the row was publicly knowable -- derived per
    the D-LD derived-release-date idiom (rules in the bronze module's docstring).  The
    registry declares this column ``knowledge_semantics: vintage`` with
    ``publication_lag_days: 0``, because the column already IS the release date and the
    per-row derivation already carries all three of the family's cadences (weekly +1/+2
    days, monthly ~+36, Ukraine ~+7 months).  It is emphatically NOT the observation
    date -- that is ``period_date`` -- and mixing the two up is the report-date-vs-
    observation-date inversion :func:`_assert_pit` now refuses.
``knowledge_date_basis``
    WHICH derivation produced ``knowledge_date`` -- ``derived_gtr_thursday``,
    ``derived_gtr_thursday_month_end``, ``derived_ams_ukraine_annual_edition`` or
    ``observed_snapshot``.  A consumer that will not accept a derived date filters on
    this column and falls back to ``as_of_date``.

The invariants :func:`_assert_pit` enforces are small and load-bearing.  A release
cannot precede the period it reports on, and a row present in a snapshot taken at
``as_of_date`` was published on or before that date, so for every row

    period_date <= knowledge_date <= as_of_date

The right-hand bound catches a derivation that has outrun the publisher; the left-hand
bound catches the inversion -- a ``knowledge_date`` that has quietly become an
observation date again, which is the failure the vintage declaration exists to prevent.
Either way the transform raises instead of publishing a knowledge claim it cannot
support.

The null-versus-value duplicate (measured, not hypothetical)
-------------------------------------------------------------
``2n8s-739j`` publishes TWO rows for
(2022-09-30, Soybeans, "Odesa-Southern ports, China", 60,000-70,000): one with no
``rate`` field at all and one with ``rate = 85.99``.  Both are real rows in the
source; emitting both would put a null and a value on one natural key, and dropping
either blindly would be a guess.  :func:`_resolve_null_duplicates` keeps the quoted
value, drops the null twin, and logs it.  When a key carries two DIFFERENT non-null
rates that is a genuine source contradiction and it raises -- silently picking one
would be inventing a number.
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.ams_gtr import (
    AMS_UKRAINE_ANNUAL_EDITIONS,
    BASIS_GTR_THURSDAY,
    BASIS_GTR_THURSDAY_MONTH_END,
    BASIS_OBSERVED,
    BASIS_UKRAINE_ANNUAL,
    OCEAN_ROUTES,
    SOURCE_NAME,
    get_dataset,
)

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = [
    "dataset",
    "series",
    "route_or_reach",
    "period_date",
    "period_grain",
    "rate",
    "unit",
    "forward_month_offset",
    "rate_month",
    "commodity",
    "vessel_size",
    "knowledge_date",
    "knowledge_date_basis",
    "as_of_date",
    "ingest_date",
    "source_attribution",
    "source",
]

# Columns that together identify one observation.  Nullable members are part of the
# key on the datasets that carry them (commodity and vessel_size on the Ukraine leg,
# rate_month on the two forward curves) and are null everywhere else.
NATURAL_KEY: list[str] = [
    "dataset",
    "series",
    "route_or_reach",
    "period_date",
    "forward_month_offset",
    "rate_month",
    "commodity",
    "vessel_size",
]

_THURSDAY = 3  # date.weekday(): Monday = 0


# ---------------------------------------------------------------------------
# Knowledge-date derivation (the D-LD derived-release-date idiom)
# ---------------------------------------------------------------------------

def _first_thursday_after(day: _dt.date) -> _dt.date:
    """The first Thursday STRICTLY after *day*.

    GTR publishes weekly on Thursday, so a period that closes on *day* first appears
    in the report published on this date.  Strictly after, because a Thursday-dated
    period is carried by the NEXT Thursday's report, not the same morning's.
    """
    delta = (_THURSDAY - day.weekday()) % 7
    return day + _dt.timedelta(days=delta or 7)


def _month_end(day: _dt.date) -> _dt.date:
    """Last calendar day of *day*'s month."""
    if day.month == 12:
        return _dt.date(day.year, 12, 31)
    return _dt.date(day.year, day.month + 1, 1) - _dt.timedelta(days=1)


def _ukraine_edition_after(day: _dt.date) -> _dt.date | None:
    """Release date of the first AMS Ukraine annual edition strictly after *day*.

    Only the edition MONTH is known (AMS names the files by month), so the edition's
    LAST day is used: later is the safe direction for a knowledge claim.  Returns
    ``None`` when no edition follows, which is the normal state for a quarter that
    closed since the most recent edition -- the caller then falls back to the
    observed snapshot date.
    """
    for year, month, _filename in AMS_UKRAINE_ANNUAL_EDITIONS:
        release = _month_end(_dt.date(year, month, 1))
        if release > day:
            return release
    return None


def derive_knowledge_date(
    period_date: _dt.date,
    basis: str,
    as_of: _dt.date,
) -> tuple[_dt.date, str]:
    """Return ``(knowledge_date, basis_actually_used)`` for one row.

    Args:
        period_date: The period the observation describes.
        basis:       The dataset's declared derivation rule.
        as_of:       The snapshot date, used as the fallback and the ceiling.

    Returns:
        The earliest defensible public-knowledge date and the basis that produced it.
        The basis returned may be ``observed_snapshot`` even when a derivation was
        requested -- that happens when the derivation has no answer (a quarter with no
        annual edition after it yet), and it is reported honestly rather than papered
        over.
    """
    if basis == BASIS_GTR_THURSDAY:
        return _first_thursday_after(period_date), basis
    if basis == BASIS_GTR_THURSDAY_MONTH_END:
        return _first_thursday_after(_month_end(period_date)), basis
    if basis == BASIS_UKRAINE_ANNUAL:
        edition = _ukraine_edition_after(period_date)
        if edition is None:
            return as_of, BASIS_OBSERVED
        return edition, basis
    if basis == BASIS_OBSERVED:
        return as_of, BASIS_OBSERVED
    raise ValueError(f"ams_gtr: unknown knowledge-date basis {basis!r}")


def _assert_pit(df: pd.DataFrame, dataset: str) -> None:
    """Raise unless every row's ``knowledge_date`` is a defensible RELEASE date.

    The contract declares ``knowledge_semantics: vintage``, i.e. ``knowledge_date`` IS the
    release date rather than the observation date (which is ``period_date``), with
    ``publication_lag_days: 0`` because the per-row derivation already carries all three
    of the family's cadences.  Two bounds make that declaration enforced rather than
    merely asserted, and each catches a different half of the report-date-vs-observation-
    date inversion:

    ``period_date <= knowledge_date``
        A report cannot publish a period before the period closes.  A rule that produced
        an earlier date would have quietly turned the column back into an observation
        date -- the inversion itself -- and every backtest reading it would see figures
        days or months before they existed.

    ``knowledge_date <= as_of_date``
        A row that appears in a snapshot taken at ``as_of_date`` was published on or
        before that date, so a later release date describes a publication that had not
        happened.  The rule has drifted from the publisher and must be re-decided, not
        re-applied.
    """
    if df.empty:
        return
    as_of = pd.to_datetime(df["as_of_date"], format="%Y%m%d").dt.date
    knowledge = pd.to_datetime(df["knowledge_date"]).dt.date
    period = pd.to_datetime(df["period_date"]).dt.date

    early = df.loc[knowledge < period]
    if not early.empty:
        sample = early.head(3)[
            ["period_date", "knowledge_date", "as_of_date", "knowledge_date_basis"]
        ].to_dict("records")
        raise ValueError(
            f"ams_gtr {dataset}: {len(early)} row(s) carry a knowledge_date BEFORE the "
            f"period they describe. knowledge_date is the RELEASE date (the contract "
            f"declares knowledge_semantics: vintage); a release cannot precede its own "
            f"observation period. This is the report-date-vs-observation-date inversion "
            f"and it must be fixed in the derivation, not published. Sample: {sample}"
        )

    violations = df.loc[knowledge > as_of]
    if not violations.empty:
        sample = violations.head(3)[
            ["period_date", "knowledge_date", "as_of_date", "knowledge_date_basis"]
        ].to_dict("records")
        raise ValueError(
            f"ams_gtr {dataset}: {len(violations)} row(s) carry a knowledge_date AFTER "
            f"the snapshot that contains them, which is impossible -- the row was in "
            f"the payload, so it was published by then. The derivation has stopped "
            f"describing the publisher. Sample: {sample}"
        )


# ---------------------------------------------------------------------------
# The null-versus-value duplicate
# ---------------------------------------------------------------------------

def _resolve_null_duplicates(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Collapse natural-key duplicates that differ only by a missing rate.

    Measured on ``2n8s-739j``: one key carries a row with no ``rate`` field beside a
    row with ``rate = 85.99``.  Keep the quoted value; drop the null twin.

    Raises:
        ValueError: If a key carries two different non-null rates.  That is a source
            contradiction, and choosing between them would be inventing a number.
    """
    if df.empty:
        return df

    # Fill nulls with a sentinel ONLY for grouping -- the emitted columns are untouched.
    key_frame = df[NATURAL_KEY].astype(object).where(df[NATURAL_KEY].notna(), "\x00")
    duplicated = key_frame.duplicated(keep=False)
    if not duplicated.any():
        return df

    keep_mask = pd.Series(True, index=df.index)
    collapsed = 0
    grouped = df.loc[duplicated].groupby(
        [key_frame.loc[duplicated, col] for col in NATURAL_KEY], sort=False
    )
    for key, group in grouped:
        non_null = group.loc[group["rate"].notna()]
        distinct = {round(float(v), 10) for v in non_null["rate"]}
        if len(distinct) > 1:
            raise ValueError(
                f"ams_gtr {dataset}: natural key {key} carries {len(distinct)} "
                f"DIFFERENT non-null rates {sorted(distinct)}. The source contradicts "
                "itself on one observation; picking one would be inventing a number. "
                "Re-read the raw payload and decide deliberately."
            )
        if non_null.empty:
            # All-null duplicates: keep exactly one, they are indistinguishable.
            keep_mask.loc[group.index[1:]] = False
        else:
            keep_mask.loc[group.index] = False
            keep_mask.loc[non_null.index[0]] = True
        collapsed += len(group) - 1

    logger.info(
        "ams_gtr %s: collapsed %d natural-key duplicate row(s) that differed only by a "
        "missing rate -- the quoted value was kept, the null twin dropped.",
        dataset, collapsed,
    )
    return df.loc[keep_mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Bronze -> silver
# ---------------------------------------------------------------------------

def transform_gtr_bronze_to_silver(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Melt one GTR bronze frame into the family's tidy silver series.

    Args:
        df:      Bronze DataFrame for a SINGLE dataset, as produced by
                 :mod:`leviathan.transforms.raw_to_bronze.ams_gtr`.
        dataset: The dataset slug those rows belong to.

    Returns:
        Long-format DataFrame with :data:`OUTPUT_COLUMNS`, one row per
        (series, route, period, qualifier) observation.  Never silently empty: an
        empty input returns an empty frame carrying the full column set, which is what
        the Batch publisher skips.

    Raises:
        ValueError: If the bronze frame is for a different dataset, if a declared
            value column is absent, if a natural key carries contradictory rates, or
            if the PIT invariant fails.
    """
    spec = get_dataset(dataset)

    if df.empty:
        logger.warning("ams_gtr %s: empty bronze frame -- nothing to melt.", dataset)
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    if "dataset" in df.columns:
        observed = set(df["dataset"].dropna().unique())
        if observed - {dataset}:
            raise ValueError(
                f"ams_gtr: bronze frame carries dataset(s) {sorted(observed)} but the "
                f"transform was called for {dataset!r}. One frame per dataset -- a "
                "mixed frame would melt several units into one column."
            )

    missing = [c for c in spec.value_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"ams_gtr {dataset}: bronze frame is missing value column(s) {missing}. "
            f"Present: {sorted(df.columns)}"
        )
    for required in ("period_date", "as_of_date", "ingest_date"):
        if required not in df.columns:
            raise ValueError(
                f"ams_gtr {dataset}: bronze frame is missing required column "
                f"{required!r}."
            )

    frames: list[pd.DataFrame] = []
    for source_col, series_name in spec.value_cols.items():
        part = pd.DataFrame(index=df.index)
        part["dataset"] = dataset
        part["series"] = series_name

        if spec.key_col:
            part["route_or_reach"] = df["route_or_reach"].astype("string")
        else:
            # The xlsx ocean leg has no route column; the route IS the series, and the
            # label is spelled to match the monthly SODA leg so the two join.
            part["route_or_reach"] = pd.Series(
                [OCEAN_ROUTES.get(series_name, series_name)] * len(df),
                index=df.index, dtype="string",
            )

        part["period_date"] = df["period_date"]
        part["period_grain"] = spec.period_grain
        part["rate"] = pd.to_numeric(df[source_col], errors="coerce").astype("float64")
        part["unit"] = spec.unit
        part["forward_month_offset"] = spec.forward_month_offset

        # Int64, not Int16. INV-2's integer target IS int64, and this table has never been
        # written, so narrowing here would only mint a `widen_int` drift entry at birth for a
        # column that holds a month number. Physical == target == glue bigint; nothing to reconcile
        # later. (forward_month_offset is a plain python int below, so it is int64 already.)
        part["rate_month"] = (
            pd.to_numeric(df["rate_month"], errors="coerce").astype("Int64")
            if "rate_month" in spec.extra_key_cols and "rate_month" in df.columns
            else pd.Series([pd.NA] * len(df), index=df.index, dtype="Int64")
        )
        for qualifier in ("commodity", "vessel_size"):
            part[qualifier] = (
                df[qualifier].astype("string")
                if qualifier in spec.extra_key_cols and qualifier in df.columns
                else pd.Series([pd.NA] * len(df), index=df.index, dtype="string")
            )

        part["as_of_date"] = df["as_of_date"].astype(str)
        part["ingest_date"] = df["ingest_date"].astype(str)
        part["source_attribution"] = spec.attribution
        part["source"] = SOURCE_NAME
        frames.append(part)

    out = pd.concat(frames, ignore_index=True)

    # --- Knowledge date, derived per dataset and LABELLED ---
    as_of_dates = pd.to_datetime(out["as_of_date"], format="%Y%m%d").dt.date
    derived = [
        derive_knowledge_date(period, spec.knowledge_basis, as_of)
        for period, as_of in zip(out["period_date"], as_of_dates)
    ]
    out["knowledge_date"] = [d[0] for d in derived]
    out["knowledge_date_basis"] = [d[1] for d in derived]

    out = _resolve_null_duplicates(out, dataset)
    _assert_pit(out, dataset)

    fallbacks = int((out["knowledge_date_basis"] == BASIS_OBSERVED).sum())
    if fallbacks and spec.knowledge_basis != BASIS_OBSERVED:
        logger.info(
            "ams_gtr %s: %d row(s) fell back to %s because the declared basis %s had "
            "no answer for their period -- reported on the row, not papered over.",
            dataset, fallbacks, BASIS_OBSERVED, spec.knowledge_basis,
        )

    out = out[OUTPUT_COLUMNS].reset_index(drop=True)

    quoted = int(out["rate"].notna().sum())
    logger.info(
        "ams_gtr silver: dataset=%s rows=%d quoted=%d null=%d span=%s..%s unit=%s "
        "basis=%s",
        dataset, len(out), quoted, len(out) - quoted,
        out["period_date"].min(), out["period_date"].max(),
        spec.unit, spec.knowledge_basis,
    )
    return out
