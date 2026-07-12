"""Shared SAGIS snapshot parser + provenance (SILVER-F042, atomic fix 1 of 2).

SAGIS South Africa publishes *cumulative per-season* Excel snapshots for weekly
producer deliveries and imports/exports. Each snapshot is a full-season file updated
weekly under a new filename; historical seasons have one final file, the current season
accumulates one file per week. Overlapping snapshots therefore report the SAME
(season, crop, week_number) more than once, and the LATEST COMPLETE snapshot is
authoritative -- ranked by PUBLICATION METADATA, never filename lexical order.

This module owns the source-faithful, provider-agnostic pieces shared by every SAGIS
producer (deliveries here; exports/CEC in other packages):
  * filename -> (crop, season, week_number) parsing;
  * a :class:`SagisSnapshot` provenance record (s3 key, filename, dataset, crop, season,
    week, publication timestamp);
  * deterministic snapshot ranking by (published_at, week_number) with a stable tiebreak,
    and same-authority tie detection so a genuine conflict can be failed closed downstream.

It is PURE + AWS-free (the S3 ``LastModified`` publication timestamp is passed in by the
job). ASCII only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

# Season token: "2011/12", "2011-12", "2011_12", or "2011/2012" -> normalized "2011/12".
_SEASON_RE = re.compile(r"(19|20)(\d{2})[\-_/](\d{2,4})")
# Week token: "Week51", "Week_51", "Week-51", "wk51", or a trailing "_51".
_WEEK_RE = re.compile(r"(?:week|wk)[\s_\-]*(\d{1,2})", re.IGNORECASE)
_TRAILING_WEEK_RE = re.compile(r"[\-_](\d{1,2})(?=\.[A-Za-z]+$)")


def normalize_season(raw_start: str, raw_end: str) -> str:
    """Normalize a season to ``YYYY/YY`` (e.g. ('2011','12') or ('2011','2012') -> '2011/12')."""
    start = raw_start
    end = raw_end if len(raw_end) == 2 else raw_end[-2:]
    return f"{start}/{end}"


def parse_season(text: str) -> Optional[str]:
    """Extract a normalized ``YYYY/YY`` season from a filename, else None."""
    m = _SEASON_RE.search(text)
    if not m:
        return None
    century, yy, end = m.group(1), m.group(2), m.group(3)
    return normalize_season(f"{century}{yy}", end)


def parse_week_number(text: str) -> Optional[int]:
    """Extract a 1-53 week number from a filename, else None.

    Prefers an explicit ``Week NN`` token; falls back to a trailing ``_NN`` before the
    extension. Never guesses beyond these -- an unparseable week stays None (the record is
    quarantined by the producer rather than mis-keyed).
    """
    m = _WEEK_RE.search(text)
    if m:
        wk = int(m.group(1))
        return wk if 1 <= wk <= 53 else None
    # Trailing-week fallback: strip the season token first so a season end-year (the
    # '12' in '2011_12') can never be mistaken for a week number.
    season_m = _SEASON_RE.search(text)
    stripped = text[: season_m.start()] + text[season_m.end():] if season_m else text
    m = _TRAILING_WEEK_RE.search(stripped)
    if not m:
        return None
    wk = int(m.group(1))
    return wk if 1 <= wk <= 53 else None


@dataclass(frozen=True)
class SagisSnapshot:
    """Provenance identity for one SAGIS Excel snapshot.

    ``published_at`` is the publication metadata (the S3 object ``LastModified``), the
    PRIMARY ranking authority. ``week_number`` (the snapshot's latest week, from the
    filename) is the secondary authority. Filename lexical order is NEVER used.
    """

    s3_key: str
    filename: str
    dataset: str
    crop: str
    season: Optional[str]
    week_number: Optional[int]
    published_at: Optional[datetime] = None

    def authority_key(self) -> tuple:
        """Sortable authority key: (published_at, week_number). Missing values sort LOWEST
        so a snapshot with real publication metadata always outranks one without."""
        pub = self.published_at.timestamp() if self.published_at is not None else float("-inf")
        wk = self.week_number if self.week_number is not None else -1
        return (pub, wk)


def build_snapshot(
    *, s3_key: str, filename: str, dataset: str, crop: str,
    published_at: Optional[datetime] = None,
) -> SagisSnapshot:
    """Construct a :class:`SagisSnapshot`, parsing season + week from the filename."""
    return SagisSnapshot(
        s3_key=s3_key,
        filename=filename,
        dataset=dataset,
        crop=crop,
        season=parse_season(filename),
        week_number=parse_week_number(filename),
        published_at=published_at,
    )


def rank_snapshots(snapshots: Sequence[SagisSnapshot]) -> list[SagisSnapshot]:
    """Return snapshots ordered most-authoritative LAST (ascending authority_key).

    Ranking is by publication metadata then week number -- explicitly NOT filename order.
    A stable sort keeps input order as the final, deterministic tiebreak.
    """
    return sorted(snapshots, key=lambda s: s.authority_key())


def same_authority(a: SagisSnapshot, b: SagisSnapshot) -> bool:
    """True when two snapshots have IDENTICAL ranking authority (a genuine tie).

    Two records that disagree on a value while sharing the same authority cannot be
    resolved by ranking and must be failed closed by the producer.
    """
    return a.authority_key() == b.authority_key()
