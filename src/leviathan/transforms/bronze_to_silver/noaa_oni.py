"""NOAA ONI bronze -> silver transform (SILVER-F057, full-orphan rebuild).

Extends the bronze (year, month, season, oni_total, oni_anom) into the canonical
``silver_noaa_oni`` feature table consumed by the numbers stack (``silverleg.py``,
``numbers/agent.py``) and the feature layer (``macro_climate.compute_oni_climate`` /
``compute_oni_lag``).

Every derived column below was reverse-engineered from the live physical silver
(915 rows, 1950-2026) and reproduces it bit-for-bit (validated in the F057 golden test):

phase / el_nino_flag / la_nina_flag
    Per-row threshold classification on ``oni_anom`` (NOT the "5 consecutive seasons"
    event rule -- the physical table classifies each row independently):
        oni_anom >= +0.5  -> "el_nino"  (el_nino_flag = 1)
        oni_anom <= -0.5  -> "la_nina"  (la_nina_flag = 1)
        otherwise          -> "neutral"
    A null anomaly stays "neutral" with both flags 0 (absent evidence is not an event;
    the null measure itself is never synthesized -- INV-4).

oni_lag3 / oni_lag6 / oni_lag9 / oni_lag12
    The ONI anomaly from 3 / 6 / 9 / 12 months earlier -- ``oni_anom.shift(N)`` on the
    chronologically-sorted series. Strictly backward-looking (no lookahead): the first N
    rows are ``NaN`` by construction, handled natively downstream by XGBoost.

la_nina_brazil_flag
    La Nina restricted to the DJF core (months 12, 1, 2) -- the Southern-Hemisphere summer
    peak that drives southern-Brazil drought risk for soy / coffee / sugar / cane.
    = la_nina_flag AND month in {12, 1, 2}.

argentina_la_nina_flag
    La Nina across the whole episode (the Argentine Pampas teleconnection is not gated to
    the DJF peak in the source table) -- identical to ``la_nina_flag``. Kept as a distinct
    semantically-named column because the feature layer surfaces it only for Argentine-origin
    commodities (``macro_climate._ARGENTINA_TELECONNECTION``).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.noaa_oni import (
    DATED_CLOCKS,
    ENSO_INDEX_FILES_BY_ID,
    SEASON_TO_MONTH,
    EnsoCapture,
    EnsoIndexFile,
    OfficialWindow,
    decode_capture_body,
    official_windows,
    parse_enso_index_text,
    season_end_month,
)

logger = get_logger(__name__)

_EL_NINO_THRESHOLD = 0.5
_LA_NINA_THRESHOLD = -0.5
_ONI_LAGS = (3, 6, 9, 12)

# The DJF-core months where the La Nina teleconnection is strongest for southern Brazil.
_BRAZIL_LA_NINA_MONTHS = frozenset({12, 1, 2})

PHASE_EL_NINO = "el_nino"
PHASE_LA_NINA = "la_nina"
PHASE_NEUTRAL = "neutral"

SILVER_COLUMNS: list[str] = [
    "year",
    "month",
    "season",
    "oni_anom",
    "phase",
    "oni_lag3",
    "oni_lag6",
    "oni_lag9",
    "oni_lag12",
    "el_nino_flag",
    "la_nina_flag",
    "la_nina_brazil_flag",
    "argentina_la_nina_flag",
    "source",
]


def classify_oni_phase(anom) -> str:
    """Classify one ONI anomaly into the ENSO phase (per-row threshold rule)."""
    if anom is None or (isinstance(anom, float) and pd.isna(anom)):
        return PHASE_NEUTRAL
    if anom >= _EL_NINO_THRESHOLD:
        return PHASE_EL_NINO
    if anom <= _LA_NINA_THRESHOLD:
        return PHASE_LA_NINA
    return PHASE_NEUTRAL


def build_oni_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform NOAA ONI bronze into the silver feature table.

    Args:
        df_bronze: Bronze DataFrame from
            :func:`~leviathan.transforms.raw_to_bronze.noaa_oni.extract_oni_bronze`; must
            carry ``year``, ``month``, ``season``, ``oni_anom``.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, one row per (year, month), sorted
        chronologically, with zero natural-key (year, month, season) duplicates.

    Raises:
        ValueError: If required columns are missing, the frame is empty, or the natural
            key is not unique.
    """
    required = {"year", "month", "season", "oni_anom"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"ONI bronze missing required columns: {sorted(missing)}")
    if df_bronze.empty:
        raise ValueError("ONI bronze DataFrame is empty")

    df = (
        df_bronze
        .sort_values(["year", "month"])
        .reset_index(drop=True)
        .copy()
    )

    dup = df.duplicated(subset=["year", "month", "season"]).sum()
    if dup:
        raise ValueError(f"ONI silver: {int(dup)} duplicate (year, month, season) rows in bronze")

    # Phase + binary flags (per-row threshold).
    df["phase"] = df["oni_anom"].apply(classify_oni_phase)
    df["el_nino_flag"] = (df["phase"] == PHASE_EL_NINO).astype("int64")
    df["la_nina_flag"] = (df["phase"] == PHASE_LA_NINA).astype("int64")

    # Backward-looking anomaly lags (no lookahead; first N rows are NaN).
    for n in _ONI_LAGS:
        df[f"oni_lag{n}"] = df["oni_anom"].shift(n)

    # Region-specific La Nina teleconnection flags.
    df["la_nina_brazil_flag"] = (
        (df["la_nina_flag"] == 1) & (df["month"].isin(_BRAZIL_LA_NINA_MONTHS))
    ).astype("int64")
    df["argentina_la_nina_flag"] = df["la_nina_flag"].astype("int64")

    df["source"] = "noaa_oni"

    result = df[SILVER_COLUMNS].reset_index(drop=True)

    logger.info(
        "ONI silver: %d rows  years=%d-%d  el_nino=%d  la_nina=%d  neutral=%d  "
        "brazil_lanina=%d  lag3_non_null=%d",
        len(result), int(result["year"].min()), int(result["year"].max()),
        int(result["el_nino_flag"].sum()), int(result["la_nina_flag"].sum()),
        int((result["phase"] == PHASE_NEUTRAL).sum()),
        int(result["la_nina_brazil_flag"].sum()),
        int(result["oni_lag3"].notna().sum()),
    )
    return result


# ===========================================================================
# silver_noaa_enso_vintages (data repairs 0929, lane ENSO: ENSO-1 + ENSO-2)
# ===========================================================================
# WHY A NEW TABLE AND NOT A COLUMN OR ROWS IN silver_noaa_oni. silver_noaa_oni is one row per
# (year, month): features/extractors.py `_check_contract` RAISES on a duplicate natural key, so a
# second vintage of a season can never live there; and a `roni_anom` column there would carry no known
# date of its own and would present RONI's restated history as known at centre-month end + the card's
# lag. silver_noaa_oni therefore stays byte-identical, and both indices, every held vintage, and the
# official-index dates live here.
#
# GRAIN. One row per (index, season, distinct published value): the first held vintage of an index
# contributes every season it prints; each later held vintage contributes ONLY the seasons whose value
# differs from the index's previous held vintage (a revision) or that it prints for the first time.
# An as-of read of index I at date D takes, per (year, month), the row with the greatest
# vintage_date <= D. A vintage that cannot be had is ABSENT (the build reports it), never invented.
VINTAGE_COLUMNS: list[str] = [
    "index_id",               # the file's identity from its URL (cpc_oni_ascii, cpc_roni_ascii)
    "source_url",             # the file's URL
    "season",                 # SEAS as printed (DJF .. NDJ)
    "year",                   # YR as printed (= the centre month's year)
    "month",                  # the CENTRE month, through the one SEASON_TO_MONTH
    "anom",                   # the published value, degC (NaN only where the publisher printed a sentinel)
    "vintage_date",           # 'YYYY-MM-DD' (UTC): the KNOWN date -- when the publisher's file carried it
    "vintage_evidence_utc",   # the exact publisher-clock instant behind vintage_date, ISO-8601 Z
    "vintage_date_source",    # origin_last_modified | archive_origin_last_modified | archive_capture
    "capture_ref",            # the raw key of the earliest held capture of this vintage
    "content_sha256",         # sha256 of the vintage's decoded file text
    "is_first_print",         # the season is the NEWEST season of this vintage (its first held print)
    "official_from",          # 'YYYY-MM-DD' the index became official, or NULL (no statement held)
    "official_until",         # 'YYYY-MM-DD' first day NOT official (successor's official_from), or NULL
    "official_statement",     # which publisher statement set those bounds, and what is not held
]
VINTAGE_NATURAL_KEY: list[str] = ["index_id", "year", "month", "vintage_date"]

_MONTH_TO_SEASON = {m: s for s, m in SEASON_TO_MONTH.items()}


def season_label(year: int, month: int) -> str:
    """'MAM 2026' for (2026, 4) -- the publisher's own SEAS + YR rendering."""
    return f"{_MONTH_TO_SEASON[int(month)]} {int(year)}"


def _ordinal(year: int, month: int) -> int:
    return int(year) * 12 + int(month)


def _from_ordinal(ordinal: int) -> tuple[int, int]:
    year, month0 = divmod(ordinal - 1, 12)
    return year, month0 + 1


def _same_value(a: float, b: float) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


@dataclass
class EnsoVintageBuild:
    """The vintages table and the full account of what went in, what was refused and what is absent."""

    frame: pd.DataFrame
    vintages: dict[str, list[dict]] = field(default_factory=dict)      # per index, accepted, oldest first
    quarantined: list[dict] = field(default_factory=list)              # refused captures, with reasons
    corroborating: list[dict] = field(default_factory=list)            # later captures of an unchanged content
    superseded_same_day: list[dict] = field(default_factory=list)      # intra-day vintages a later one replaced
    undated: list[str] = field(default_factory=list)                   # held bodies with no publisher clock
    absent_first_prints: dict[str, dict] = field(default_factory=dict)  # per index

    def summary(self) -> dict:
        return {
            "rows": int(len(self.frame)),
            "rows_by_index": {k: int(v) for k, v in self.frame.groupby("index_id").size().items()}
            if len(self.frame) else {},
            "vintages": {k: [(v["vintage_date"], v["newest_season"], v["clock"]) for v in vs]
                         for k, vs in self.vintages.items()},
            "quarantined": self.quarantined,
            "corroborating": len(self.corroborating),
            "superseded_same_day": self.superseded_same_day,
            "undated": self.undated,
            "absent_first_prints": self.absent_first_prints,
        }


def build_enso_vintages(
    captures: Iterable[EnsoCapture],
    *,
    index_files_by_id: Optional[dict[str, EnsoIndexFile]] = None,
    windows: Optional[dict[str, OfficialWindow]] = None,
) -> EnsoVintageBuild:
    """Build ``silver_noaa_enso_vintages`` from every held capture of the declared ENSO index files.

    Deterministic in its input set (order-free). A capture is REFUSED -- listed in ``quarantined`` with
    its reason, never raised, because this runs as a leg of the autonomous enso chain -- when: its index
    is not a declared file; its clock is unknown; its decoded text does not hash to the digest its key
    carries; it fails :func:`parse_enso_index_text` against its file's declared header; its publisher
    clock predates the END of its own newest season (a value cannot be known before its last month
    ends -- a clock or season-shift defect); it holds an OLDER newest season than an earlier-dated
    vintage (a stale replay); it drops seasons the previous vintage held; or two different contents
    claim one evidence instant. Same-content captures in sequence are ONE vintage dated by the earliest
    evidence (the rest are ``corroborating``); several vintages on one UTC date keep the last (the
    state at the end of that day; the others are ``superseded_same_day``)."""
    files = ENSO_INDEX_FILES_BY_ID if index_files_by_id is None else index_files_by_id
    wins = official_windows() if windows is None else windows
    build = EnsoVintageBuild(frame=pd.DataFrame(columns=VINTAGE_COLUMNS))

    def refuse(cap: EnsoCapture, reason: str) -> None:
        build.quarantined.append({"capture_ref": cap.key, "index_id": cap.index_id, "reason": reason})

    parsed: dict[str, list[dict]] = {}
    for cap in sorted(captures, key=lambda c: c.key):
        if cap.clock not in DATED_CLOCKS:
            if cap.evidence_utc is None:
                build.undated.append(cap.key)
            else:
                refuse(cap, f"unknown clock {cap.clock!r}")
            continue
        index_file = files.get(cap.index_id)
        if index_file is None:
            refuse(cap, f"index {cap.index_id!r} is not a declared ENSO index file")
            continue
        try:
            text = decode_capture_body(cap.body)
        except OSError as exc:
            refuse(cap, f"body does not decode: {exc}")
            continue
        if hashlib.sha256(text).hexdigest() != cap.sha256:
            refuse(cap, "decoded text does not hash to the digest the capture key carries")
            continue
        try:
            table = parse_enso_index_text(text, index_file.header)
        except (ValueError, UnicodeDecodeError) as exc:
            refuse(cap, f"parse refused: {exc}")
            continue
        newest_year, newest_month = int(table["year"].iloc[-1]), int(table["month"].iloc[-1])
        end_year, end_month = season_end_month(newest_year, newest_month)
        first_day_after = date(end_year + (end_month == 12), end_month % 12 + 1, 1)
        evidence_day = cap.evidence_utc.date()
        if evidence_day < first_day_after:
            refuse(cap, f"clock {evidence_day.isoformat()} precedes the end of its newest season "
                        f"{season_label(newest_year, newest_month)} (first possible day "
                        f"{first_day_after.isoformat()})")
            continue
        parsed.setdefault(cap.index_id, []).append({
            "cap": cap, "table": table, "newest": _ordinal(newest_year, newest_month),
            "url": index_file.url})

    rows: list[dict] = []
    for index_id in sorted(parsed):
        items = sorted(parsed[index_id], key=lambda it: (it["cap"].evidence_utc, it["cap"].key))
        # two different contents at one evidence instant: the order between them is unknowable
        by_instant: dict = {}
        for it in items:
            by_instant.setdefault(it["cap"].evidence_utc, set()).add(it["cap"].sha256)
        clash = {inst for inst, shas in by_instant.items() if len(shas) > 1}
        kept = []
        for it in items:
            if it["cap"].evidence_utc in clash:
                refuse(it["cap"], f"{len(by_instant[it['cap'].evidence_utc])} contents claim one "
                                  f"evidence instant {it['cap'].evidence_utc.isoformat()}")
            else:
                kept.append(it)
        # consecutive captures of one content are one vintage, dated by the earliest evidence
        vintages: list[dict] = []
        for it in kept:
            if vintages and vintages[-1]["cap"].sha256 == it["cap"].sha256:
                build.corroborating.append({"capture_ref": it["cap"].key, "index_id": index_id,
                                            "vintage_capture_ref": vintages[-1]["cap"].key})
                continue
            vintages.append(it)
        # a vintage never goes backwards and never drops a season the previous one held
        accepted: list[dict] = []
        for v in vintages:
            if accepted:
                prev = accepted[-1]
                if v["newest"] < prev["newest"]:
                    refuse(v["cap"], f"newest season {season_label(*_from_ordinal(v['newest']))} is older "
                                     f"than the earlier-dated vintage's {season_label(*_from_ordinal(prev['newest']))}")
                    continue
                prev_keys = set(zip(prev["table"]["year"], prev["table"]["month"]))
                dropped = prev_keys - set(zip(v["table"]["year"], v["table"]["month"]))
                if dropped:
                    refuse(v["cap"], f"drops {len(dropped)} season(s) the previous vintage held")
                    continue
            accepted.append(v)
        # the state at the END of each UTC day: the last accepted vintage of that date
        by_day: dict[str, dict] = {}
        for v in accepted:
            day = v["cap"].evidence_utc.date().isoformat()
            if day in by_day:
                build.superseded_same_day.append({"capture_ref": by_day[day]["cap"].key,
                                                  "index_id": index_id, "vintage_date": day,
                                                  "superseded_by": v["cap"].key})
            by_day[day] = v
        daily = [by_day[d] for d in sorted(by_day)]

        win = wins.get(index_id, OfficialWindow(None, None, "no publisher statement held"))
        state: dict[tuple[int, int], float] = {}
        first_printed: set[int] = set()
        build.vintages[index_id] = []
        for v in daily:
            cap = v["cap"]
            vdate = cap.evidence_utc.date().isoformat()
            evidence = cap.evidence_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            newest_year, newest_month = _from_ordinal(v["newest"])
            n_rows = 0
            for season, year, month, anom in v["table"].itertuples(index=False, name=None):
                k = (int(year), int(month))
                if k in state and _same_value(state[k], float(anom)):
                    continue
                first = (k == (newest_year, newest_month)) and k not in state
                if first:
                    first_printed.add(_ordinal(*k))
                rows.append({
                    "index_id": index_id, "source_url": v["url"], "season": season,
                    "year": k[0], "month": k[1], "anom": float(anom),
                    "vintage_date": vdate, "vintage_evidence_utc": evidence,
                    "vintage_date_source": cap.clock, "capture_ref": cap.key,
                    "content_sha256": cap.sha256, "is_first_print": bool(first),
                    "official_from": win.official_from, "official_until": win.official_until,
                    "official_statement": win.official_statement,
                })
                state[k] = float(anom)
                n_rows += 1
            build.vintages[index_id].append({
                "vintage_date": vdate, "evidence_utc": evidence, "clock": cap.clock,
                "capture_ref": cap.key, "newest_season": season_label(newest_year, newest_month),
                "rows_contributed": n_rows})
        if daily:
            lo, hi = daily[0]["newest"], daily[-1]["newest"]
            gaps = [season_label(*_from_ordinal(o)) for o in range(lo + 1, hi + 1) if o not in first_printed]
            build.absent_first_prints[index_id] = {
                "before_first_held_vintage": f"every season through {season_label(*_from_ordinal(lo - 1))}",
                "between_held_vintages": gaps,
            }

    frame = pd.DataFrame.from_records(rows, columns=VINTAGE_COLUMNS)
    if len(frame):
        frame = frame.sort_values(VINTAGE_NATURAL_KEY, kind="mergesort").reset_index(drop=True)
        frame["year"] = frame["year"].astype("int64")
        frame["month"] = frame["month"].astype("int64")
        frame["anom"] = frame["anom"].astype("float64")
        frame["is_first_print"] = frame["is_first_print"].astype(bool)
        dup = int(frame.duplicated(subset=VINTAGE_NATURAL_KEY).sum())
        if dup:  # an internal invariant, not a data condition: the by-day collapse makes it impossible
            raise AssertionError(f"silver_noaa_enso_vintages: {dup} duplicate natural keys")
    build.frame = frame
    logger.info("ENSO vintages: %d rows; vintages %s; refused %d; corroborating %d; undated %d",
                len(frame), {k: len(v) for k, v in build.vintages.items()}, len(build.quarantined),
                len(build.corroborating), len(build.undated))
    return build
