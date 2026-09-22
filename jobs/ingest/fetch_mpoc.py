"""Fetch MPOC market intelligence pages (HTML) to raw S3.

Four report series are downloaded:

  trade_statistics   — "Monthly Palm Oil Trade Statistics {year}"
                       One HTML page per calendar year; Malaysian palm oil
                       exports/imports, top destination countries, production,
                       closing stocks, and monthly CPO prices.
                       Available years: 2009–2023 (15 pages).
                       mpoc.org.my/monthly-palm-oil-trade-statistics-{YYYY}/

  stock_comparison   — "Stock Comparison"
                       Single live page with oils & fats ending stock data
                       (Palm, Soy, Sunflower, Rapeseed) for China, India,
                       Pakistan, Bangladesh, and USA, plus analyst narrative
                       paragraphs per country.
                       mpoc.org.my/market-insight/stock-comparison/

  competitive_prices — "Daily Palm Oil Prices"
                       Single live page with a monthly CPO BMD+3 vs SBO ARG
                       FOB vs SFO Black Sea FOB price comparison and spread
                       table showing price premiums of substitute oils over CPO.
                       mpoc.org.my/market-insight/daily-palm-oil-prices/

  market_highlights  — Individual market analysis articles.
                       Each slug maps to one HTML page spidered from:
                       mpoc.org.my/market-insight/market-highlights/

Discovery strategy
------------------
All report URLs are stored in a static manifest produced by the probe scripts:
  configs/sources/mpoc_archive.yaml

MPOC (mpoc.org.my) is a WordPress site with no WAF; standard ``requests``
with a Chrome User-Agent works without fingerprint bypass.

S3 key structure
----------------
  trade_statistics:
    raw/production/source=mpoc/release_type=trade_statistics/
        year={YYYY}/mpoc_trade_stats_{YYYY}.html

  stock_comparison:
    raw/production/source=mpoc/release_type=stock_comparison/
        mpoc_stock_comparison.html

  competitive_prices:
    raw/production/source=mpoc/release_type=competitive_prices/
        mpoc_competitive_prices.html

  market_highlights:
    raw/production/source=mpoc/release_type=market_highlights/
        slug={slug}/mpoc_article_{slug}.html

Idempotency (P11, 2026-09-22; the closed-year rule added in round 2)
-------------------------------------------------------------------
The four series split into three fetch policies and the split is structural, not a flag the caller
may get wrong:

  LIVE SNAPSHOTS (stock_comparison, competitive_prices) -- one mutable key each, rewritten by MPOC
  whenever the underlying figures move.  ALWAYS re-fetched.  ``--skip-existing-s3`` is REFUSED for
  them and says so in the log: an existence-only skip on a mutable page is exactly the MPOB BEPI
  freeze (cea8818a) that froze 2026 at 111 rows from 2026-08-22 while the raw carried August.

  YEAR PAGES (trade_statistics) -- one page per calendar year.  A year page gains a month row only
  while its own year is running, so the CURRENT and PREVIOUS calendar years are ALWAYS re-fetched
  and every OLDER year is a closed, immutable archive object that may be skipped when the estate
  already holds it.  See :func:`trade_stats_year_is_closed`; the rule is stated in YEARS, never as
  a hard-coded list, so it stays correct if MPOC ever resumes the series (the current 2009-2023
  archive is closed: ``monthly-palm-oil-trade-statistics-2024`` and ``-2025`` both 404, re-measured
  2026-09-22).  A closed year page the estate does NOT hold is still fetched, and still fatal, and
  ``--refetch-years`` forces the whole archive back into the request list for the operator who
  finds a banked year page corrupt.

  ARTICLES (market_highlights) -- a published WordPress article under a stable slug, DECLARED
  immutable (``ARTICLE_RELEASE_TYPE``) and not measured: no content comparison of the 342 banked
  pages has been made.  These are skipped when the key already exists, BY DEFAULT, and
  ``--refetch-articles`` forces the full re-archive.  The declaration is one constant to change.

Why the defaults moved, from the 2026-09-15 fire (CloudWatch log stream
``leviathan-dev-b3-flat-silver/default/94fb9a0fc82642eab6f4246e75d23a26``, re-read 2026-09-22):
the monthly fire walked all 359 manifest entries and 248 of them returned ``429 Too Many
Requests``.  The 248 were NOT all articles -- they were 236 ``market_highlights``, ELEVEN
``trade_statistics`` year pages and ``stock_comparison`` -- and the FIRST 429 of the run
(12:01:17.671) hit ``trade_statistics/2012``, a DATA page.  The run had a single shared error
counter and a flat one-second sleep that was not a backoff, so it raised SystemExit and killed
bronze, silver, gate and promote for the whole family.

Three separate things had to change, and only all three together save that fire:

  1. the article archive stops being walked at all (342 slugs already banked) -- it removes 342 of
     the 359 requests and with them the rate-limit trigger;
  2. the eleven closed year pages that 429'd were ALL already banked (their S3 objects carry
     2026-08-15 mtimes, measured), so the closed-year rule removes them from the request list too:
     the data leg issues TWO requests instead of seventeen;
  3. every remaining request is retried with Retry-After / exponential backoff instead of a flat
     sleep -- and if a live snapshot is STILL unfetched when the retries are spent, the run FAILS
     CLOSED, because a balance-sheet page the estate could not read is an exit code, never a
     warning.

Exit contract (P11)
-------------------
The error counter is PARTITIONED by release_type.  A market_highlights failure is logged, counted
and emitted as a CloudWatch metric; it may never set the exit code.  Only a DATA-class failure
fails the run.  Data entries are also processed FIRST regardless of manifest order, so a throttled
article archive can never precede the balance sheet.  A run of consecutive rate-limit failures on
articles trips a breaker that stops fetching articles for the rest of the run -- the data is already
banked and there is nothing to gain from being throttled 200 more times.

The request budget (``--limit``), 2026-09-22 round 3
----------------------------------------------------
``--limit N`` counts REQUESTS -- pages actually fetched -- and never plan entries, and the run is
ordered by MUTABILITY (:func:`release_fetch_rank`) rather than by class: the live single-key pages
and any year page that can still gain a row come first, the closed-year archive second, the
articles last.  Both halves answer the same round-2 regression.  Ranking by class alone put the
fifteen closed ``trade_statistics`` years -- every one of them now a skip -- at the head of the
list, and slicing the PLAN at N meant ``--limit 1`` issued ZERO HTTP requests, validated nothing,
printed ``uploaded=0 skipped=1`` and exited 0 (measured on the live manifest: the first FETCH
appeared at N=16).  That is the estate's own pre-arm smoke command, and a smoke that cannot fail
is a false green.  ``--limit 1`` now fetches exactly one page and it is ``stock_comparison`` --
the mutable balance sheet the 2026-09-15 fire lost.

The end-of-run ``Request budget:`` line prints ``requested``, ``skipped_closed_year``,
``articles_skipped`` and ``data_errors`` as four separate populations, none of them derived by
subtracting another, and it is what the next scheduled fire is verified by.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.mpoc.adapter import find_table_by_header, parse_tables
from leviathan.storage.paths import (
    raw_mpoc_article_key,
    raw_mpoc_competitive_prices_key,
    raw_mpoc_stock_comparison_key,
    raw_mpoc_trade_stats_key,
)
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Validation markers per release type
_MARKER_TRADE_STATS = "EXPORTS TO MAJOR COUNTRIES"
_MARKER_STOCK_COMPARISON = "OILS AND FATS ENDING STOCKS"
_MARKER_COMPETITIVE_PRICES_A = "CPO"
_MARKER_COMPETITIVE_PRICES_B = "SBO"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "mpoc_archive.yaml"
)

# ---------------------------------------------------------------------------
# Release-type partition (P11)
# ---------------------------------------------------------------------------
# The three MUTABLE data classes. A failure here fails the run; an existence-only skip is REFUSED.
DATA_RELEASE_TYPES: tuple[str, ...] = (
    "trade_statistics",
    "stock_comparison",
    "competitive_prices",
)
# The immutable slug-keyed article archive. Failures are counted and metered, never fatal.
ARTICLE_RELEASE_TYPE = "market_highlights"

# The one DATA class whose keys are partitioned by calendar year.
YEAR_KEYED_RELEASE_TYPE = "trade_statistics"
# How many calendar years back from today stay MUTABLE. 1 = the current year AND the previous one
# are always re-fetched; everything older is a closed archive object. A year page gains a month row
# only while its own year is running, plus the few weeks in which the December row is added -- which
# is exactly what the previous year covers. Stated as a lookback in YEARS and never as a list of
# closed years, so the RULE stays correct if MPOC resumes the series -- but the RULE is not the
# whole fetcher: the work list comes from configs/sources/mpoc_archive.yaml, which enumerates
# 2009..2023, so a resumed 2027 page is never REQUESTED until that yaml gains it. The year pages
# are a frozen pointer for the same reason the article slugs are (see ARTICLE_RELEASE_TYPE), and
# discovery for both is owed to whoever owns that manifest.
_MUTABLE_YEARS_BACK = 1

# The estate's one custom-metric namespace; the batch job role already carries PutMetricData scoped
# to it by the freshness-put-metric inline policy, so this needs no new IAM.
METRIC_NAMESPACE = "Leviathan/Silver"
INGEST_LEG_FAILURE_METRIC = "IngestLegFailures"

# Statuses that mean "slow down", not "gone".
_RETRY_STATUS = (429, 503)
_DEFAULT_MAX_ATTEMPTS = 4
_DEFAULT_BACKOFF_BASE_S = 2.0
_DEFAULT_BACKOFF_CAP_S = 60.0
# Consecutive article rate-limits after which the run stops fetching articles altogether.
_DEFAULT_ARTICLE_BREAKER = 5


class RateLimited(RuntimeError):
    """The host throttled us and every retry was spent."""


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _retry_after_seconds(resp: requests.Response, attempt: int,
                         base: float, cap: float) -> float:
    """Seconds to wait before the next attempt: Retry-After when the host states one, else 2**n.

    ``Retry-After`` is either a decimal count of seconds or an HTTP-date; both are honoured, and
    both are capped so a hostile or mis-set header cannot park a Batch job for an hour.
    """
    raw = (resp.headers or {}).get("Retry-After")
    if raw:
        try:
            return max(0.0, min(float(raw), cap))
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(raw)
            if when is not None:
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                delta = (when - datetime.now(timezone.utc)).total_seconds()
                return max(0.0, min(delta, cap))
        except (TypeError, ValueError):
            pass
    return min(base * (2 ** attempt), cap)


def _download_html(
    url: str,
    session: requests.Session,
    timeout: int = 30,
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    backoff_base: float = _DEFAULT_BACKOFF_BASE_S,
    backoff_cap: float = _DEFAULT_BACKOFF_CAP_S,
    sleep=time.sleep,
) -> str:
    """GET *url* with Retry-After / exponential backoff on 429 and 503.

    A flat ``--sleep-seconds 1.0`` is not a backoff: on 2026-09-15 it walked into 248 consecutive
    429s without ever slowing down. Raises :class:`RateLimited` when the retries are spent, so the
    caller can count a throttle separately from a genuine fetch failure.
    """
    last_status = None
    for attempt in range(max_attempts):
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        last_status = resp.status_code
        if resp.status_code in _RETRY_STATUS:
            if attempt == max_attempts - 1:
                break
            wait = _retry_after_seconds(resp, attempt, backoff_base, backoff_cap)
            logger.warning(
                "HTTP %s from %s - attempt %d/%d, backing off %.1fs",
                resp.status_code, url, attempt + 1, max_attempts, wait,
            )
            sleep(wait)
            continue
        resp.raise_for_status()
        return resp.text
    raise RateLimited(f"HTTP {last_status} after {max_attempts} attempts: {url}")


def _assert_tables_parseable(html_text: str, rt: str, url: str) -> None:
    """Structural drift guard: assert the SILVER producers' target tables are actually resolvable.

    The loose text-marker check ("EXPORTS TO MAJOR COUNTRIES" etc.) passes even when the live layout
    has drifted (the phrase survives in the tab nav / JSON-LD while the table itself is unparseable).
    Resolving the tables by their header signature here -- the same finder the F053/F054/F055
    producers use -- makes a drifted page fail at FETCH, before it can overwrite an archived page.
    """
    tables = parse_tables(html_text)
    if rt == "trade_statistics":
        if find_table_by_header(tables, first_col="country") is None:
            raise RuntimeError(
                f"Structural drift: no COUNTRY-headed exports table resolvable in {url}"
            )
        if find_table_by_header(tables, header_all=["export", "import"]) is None:
            raise RuntimeError(
                f"Structural drift: no monthly Exports/Imports table resolvable in {url}"
            )
    elif rt == "stock_comparison":
        # each country renders a 'Country : <name>' header cell; require at least one.
        if find_table_by_header(tables, first_col="country") is None:
            raise RuntimeError(
                f"Structural drift: no per-country ending-stock table resolvable in {url}"
            )


# ---------------------------------------------------------------------------
# Release-type policy (P11) -- pure, so the pins bind the RULE, not a run
# ---------------------------------------------------------------------------


def release_fetch_rank(release_type: str, *, year: int | None = None,
                       today: date | None = None) -> int:
    """The ordering rank of one manifest entry: 0 MUTABLE, 1 CLOSED-YEAR archive, 2 article.

    The rank is MUTABILITY, not class, and that is the whole point. Ranking by class alone put
    the fifteen closed ``trade_statistics`` year pages -- every one of which now SKIPS -- ahead of
    the two live snapshots, so ``--limit 1`` planned a skip and the operator smoke issued no
    request at all (measured 2026-09-22 on the live manifest: the first FETCH appeared at N=16).

    Rank 0 is what a fire must never lose: the single-key live pages and any year page that can
    still gain a row (the current and previous calendar years). Rank 1 is the closed archive,
    which is fetched only when the estate does not already hold it. Rank 2 is the article archive.
    """
    if is_article(release_type):
        return 2
    if (release_type == YEAR_KEYED_RELEASE_TYPE
            and year is not None
            and trade_stats_year_is_closed(year, today)):
        return 1
    return 0


def order_releases(releases: list[dict], today: date | None = None) -> list[dict]:
    """MUTABLE pages first, the closed-year archive second, articles last; order kept within rank.

    Structural, not incidental: on 2026-09-15 the data legs happened to sit first in the manifest
    and landed before the 429 wall. A manifest re-ordering would have lost them.

    The rank is :func:`release_fetch_rank`, so the FIRST entry of an ordered run is always a page
    the fire really requests -- which is what makes ``--limit 1`` a smoke test instead of a
    no-op, and what makes ``stock_comparison`` (the page the 2026-09-15 fire lost) the first
    thing any truncated run touches.
    """
    return sorted(
        releases,
        key=lambda r: release_fetch_rank(r.get("release_type", ""),
                                         year=r.get("year"), today=today),
    )


def is_article(release_type: str) -> bool:
    """True only for the ONE declared immutable class.

    Stated positively on purpose. Testing the DATA tuple instead would make every release_type
    nobody has declared yet -- a fifth series added to the manifest -- default into the
    non-fatal, skip-if-exists article bucket. An undeclared class must fail CLOSED.
    """
    return release_type == ARTICLE_RELEASE_TYPE


def trade_stats_year_is_closed(year: int, today: date | None = None) -> bool:
    """True when a ``trade_statistics`` YEAR page can no longer gain a row.

    A year page is the calendar year's own ledger: it gains a month row while that year is running
    and a last one when the December figures are published, so the CURRENT year and the PREVIOUS
    year are mutable and every older year is a closed archive object.

    This is the ONE place an existence skip is permitted on a DATA class, and it is permitted
    because the object cannot change -- not because re-reading it is expensive. The forbidden shape
    is the blanket skip: on 2026-09-15 eleven of these pages were re-fetched into a 429 wall and
    each one was a candidate to kill promote for the whole family, while all eleven were already
    banked (their S3 objects carry 2026-08-15 mtimes) and none of them could have changed. The
    immutability is MEASURED, not declared: the live 2012 and 2023 pages, re-fetched 2026-09-22,
    parse to a table digest IDENTICAL to the banked objects (the ~14 KB of raw difference is site
    chrome the silver producers never read).

    What this does NOT do is DISCOVER a year. ``main`` builds its work list from
    ``configs/sources/mpoc_archive.yaml``, so a year the yaml does not list is never requested
    whatever this rule says -- see the note on ``_MUTABLE_YEARS_BACK``.
    """
    ref = today or date.today()
    return year <= ref.year - 1 - _MUTABLE_YEARS_BACK


def skip_policy(
    release_type: str,
    *,
    year: int | None = None,
    refetch_articles: bool = False,
    refetch_years: bool = False,
    skip_existing_flag: bool = False,
    today: date | None = None,
) -> bool:
    """True when an already-existing S3 key means "do not fetch this entry".

    ``skip_existing_flag`` is deliberately inert everywhere -- no caller flag can turn an
    existence skip on for a mutable page. The three answers:

    * ``stock_comparison`` / ``competitive_prices`` -- single-key LIVE snapshots. Always False.
      An existence-only skip on either is the MPOB BEPI freeze (cea8818a).
    * ``trade_statistics`` -- True only for a CLOSED year (see :func:`trade_stats_year_is_closed`).
      An entry that carries no year at all fails CLOSED and is fetched. ``--refetch-years`` forces
      the closed archive back into the request list, which is the operator's answer when a banked
      year page is found corrupt: before it existed, the only way to re-fetch one was to delete
      its S3 object by hand.
    * ``market_highlights`` -- True by default; ``--refetch-articles`` forces the full re-archive.
    """
    if is_article(release_type):
        return not refetch_articles
    if release_type == YEAR_KEYED_RELEASE_TYPE:
        if refetch_years:
            return False
        return year is not None and trade_stats_year_is_closed(year, today)
    return False


def plan_entry(
    release_type: str,
    *,
    year: int | None = None,
    key_exists: Callable[[], bool] = lambda: False,
    refetch_articles: bool = False,
    refetch_years: bool = False,
    skip_existing_flag: bool = False,
    today: date | None = None,
) -> str:
    """``"skip"`` or ``"fetch"`` for one manifest entry -- the COMPOSED rule, pinnable without S3.

    A skip is always an existence skip: the policy alone never declines to fetch. A closed 2012
    year page the estate does not hold is FETCHED (and its failure is fatal), which is what keeps
    the closed-year rule from becoming the second frozen pointer in this family.

    ``key_exists`` is a callable and not a bool so the S3 HEAD is only spent on the entries whose
    policy could actually skip -- the two live pages are never HEADed at all.
    """
    if not skip_policy(release_type, year=year, refetch_articles=refetch_articles,
                       refetch_years=refetch_years, skip_existing_flag=skip_existing_flag,
                       today=today):
        return "fetch"
    return "skip" if key_exists() else "fetch"


def plan_run(
    items: list,
    plan: Callable[[object], str],
    limit: int | None = None,
) -> list[tuple[object, str]]:
    """Decide each item in order and STOP once *limit* REQUESTS have been planned.

    ``--limit`` counts REQUESTS -- fetches actually attempted -- and never plan entries. That
    distinction is the whole of MAJOR-A: while the limit sliced the PLAN, the fifteen closed
    ``trade_statistics`` years sat at the head of the ordered list, every one of them a skip, so
    ``python jobs/ingest/fetch_mpoc.py --limit 1`` issued ZERO HTTP requests, validated nothing,
    printed ``uploaded=0 skipped=1`` and exited 0. A smoke that cannot fail is a false green, and
    the estate's own pre-arm law tells an operator to run exactly that command before a fire.

    Counting requests instead makes the budget mean what an operator reads it to mean: N pages
    really fetched. Skips are still WALKED and still reported -- they cost nothing and the
    partitioned count line is what the next scheduled fire is verified against -- but they can
    never consume the budget. With ``limit`` None or 0 the whole list is walked, as before.
    """
    out: list[tuple[object, str]] = []
    planned_requests = 0
    for item in items:
        if limit and planned_requests >= limit:
            break
        decision = plan(item)
        out.append((item, decision))
        if decision == "fetch":
            planned_requests += 1
    return out


def exit_reason(data_errors: int, article_errors: int = 0,
                failed_labels: list[str] | None = None) -> str | None:
    """The SystemExit message for this run, or None when the run may exit 0.

    THE PARTITION, in one expression: the exit code reads ``data_errors`` and NOTHING else. A
    market_highlights failure is counted, named and metered and can never reach it; a DATA page
    the run could not read after its retries were spent always does. ``article_errors`` is reported
    inside the message so the operator sees what else was wrong on the same fire, and it can never
    change the verdict.

    What this does NOT claim: the 2026-09-15 fire did not have zero data failures. It had TWELVE
    (eleven trade_statistics year pages plus stock_comparison) against 236 articles, so this
    partition ALONE would still have exited non-zero on it. What saves that fire is the request
    list shrinking from 359 to 2 -- see the module docstring and
    ``tests/unit/test_fetch_mpoc_partition.py``.
    """
    if data_errors <= 0:
        return None
    labels = ", ".join(failed_labels or []) or "see logs above"
    tail = (f"; {article_errors} {ARTICLE_RELEASE_TYPE} page(s) also failed and were metered, "
            f"not counted here" if article_errors else "")
    return f"{data_errors} DATA report(s) failed ({labels}) - see logs above{tail}."


def emit_leg_failure_metric(data_errors: int, article_errors: int) -> None:
    """Publish the partitioned failure counts to CloudWatch. NEVER raises.

    ZERO is emitted too: an alarm whose metric only appears while it is breaching is an alarm on
    missing data. boto3 is imported inside the function so the unit suite stays AWS-free, and
    telemetry may never change an exit code.
    """
    try:
        import boto3
        now = datetime.now(timezone.utc)
        data = [
            {"MetricName": INGEST_LEG_FAILURE_METRIC, "Timestamp": now,
             "Value": float(data_errors), "Unit": "Count",
             "Dimensions": [{"Name": "Source", "Value": "mpoc"},
                            {"Name": "Leg", "Value": "data"}]},
            {"MetricName": INGEST_LEG_FAILURE_METRIC, "Timestamp": now,
             "Value": float(article_errors), "Unit": "Count",
             "Dimensions": [{"Name": "Source", "Value": "mpoc"},
                            {"Name": "Leg", "Value": ARTICLE_RELEASE_TYPE}]},
        ]
        boto3.client("cloudwatch").put_metric_data(
            Namespace=METRIC_NAMESPACE, MetricData=data)
        logger.info("[metric] %s -> %s: data=%d %s=%d",
                    INGEST_LEG_FAILURE_METRIC, METRIC_NAMESPACE,
                    data_errors, ARTICLE_RELEASE_TYPE, article_errors)
    except Exception as exc:  # noqa: BLE001 -- telemetry must never change an exit code
        logger.warning("[metric] WARN could not emit %s (%s: %s) -- the exit code below stands",
                       INGEST_LEG_FAILURE_METRIC, type(exc).__name__, str(exc)[:160])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download MPOC market intelligence HTML pages to raw S3. "
            "Reads URLs from configs/sources/mpoc_archive.yaml."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help=(
            "LEGACY and now REFUSED for the three mutable DATA classes -- they are always "
            "re-fetched. Article pages are skipped when they already exist by DEFAULT; this "
            "flag only restates that."
        ),
    )
    parser.add_argument(
        "--refetch-articles",
        action="store_true",
        help=(
            "Re-download every market_highlights article even when its S3 key exists "
            "(a full re-archive). Off by default: all 342 slugs are already banked, and "
            "re-walking them is what tripped the 2026-09-15 rate limit."
        ),
    )
    parser.add_argument(
        "--refetch-years",
        action="store_true",
        help=(
            "Re-download every trade_statistics YEAR page even when its S3 key exists, "
            "including the closed archive. The operator's answer when a banked year page is "
            "found corrupt; without it the only way to force one was to delete its S3 object "
            "by hand. Off by default (a closed year page cannot change)."
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=_DEFAULT_MAX_ATTEMPTS,
        metavar="N",
        help=f"HTTP attempts per URL before giving up (default: {_DEFAULT_MAX_ATTEMPTS}).",
    )
    parser.add_argument(
        "--article-breaker",
        type=int,
        default=_DEFAULT_ARTICLE_BREAKER,
        metavar="N",
        help=(
            "Stop fetching market_highlights after N consecutive rate-limited articles "
            f"(default: {_DEFAULT_ARTICLE_BREAKER}; 0 disables the breaker). Never applies "
            "to the DATA classes."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all S3 keys and source URLs without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Stop after N REQUESTS (pages actually fetched). Skips are still walked and "
            "reported and never consume the budget, so `--limit 1` fetches exactly one page "
            "and it is a MUTABLE one - use it for a quick smoke test."
        ),
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only trade_statistics entries for this calendar year.",
    )
    parser.add_argument(
        "--release-type",
        choices=[
            "trade_statistics",
            "stock_comparison",
            "competitive_prices",
            "market_highlights",
        ],
        default=None,
        help="Process only this release type (default: all).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    releases: list[dict] = manifest_data["releases"]
    logger.info("Loaded %d entries from manifest %s", len(releases), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Apply filters
    # -----------------------------------------------------------------------
    if args.year is not None:
        releases = [r for r in releases if r.get("year") == args.year]
    if args.release_type is not None:
        releases = [r for r in releases if r["release_type"] == args.release_type]
    # MUTABLE pages first, the closed-year archive second, articles last -- see order_releases and
    # release_fetch_rank. `--limit` is NOT a slice of this list: it is a REQUEST budget spent in
    # the loop below, so a `--limit 1` smoke fetches a live page instead of planning a skip.
    releases = order_releases(releases)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        def _dry_policy(entry: dict) -> str:
            return (
                "skip"
                if skip_policy(entry["release_type"], year=entry.get("year"),
                               refetch_articles=args.refetch_articles,
                               refetch_years=args.refetch_years,
                               skip_existing_flag=args.skip_existing_s3)
                else "fetch"
            )

        # A dry run makes no S3 call, so it cannot know whether a skippable key really exists; it
        # reads the POLICY and says so. The request budget is spent on the ALWAYS-FETCH entries,
        # which is the same budget the real run spends whenever the estate holds what it declares.
        planned = plan_run(releases, _dry_policy, args.limit)
        print(
            f"Manifest: {_MANIFEST_PATH.name}  "
            f"({len(releases)} entries after filters, {len(planned)} walked"
            + (f" under --limit {args.limit} request(s), NO S3 lookup made" if args.limit else "")
            + ")"
        )
        for entry, decision in planned:
            rt = entry["release_type"]
            url = entry["stat_url"]
            if rt == "trade_statistics":
                s3_key = raw_mpoc_trade_stats_key(entry["year"])
            elif rt == "stock_comparison":
                s3_key = raw_mpoc_stock_comparison_key()
            elif rt == "competitive_prices":
                s3_key = raw_mpoc_competitive_prices_key()
            elif rt == ARTICLE_RELEASE_TYPE:
                s3_key = raw_mpoc_article_key(entry["slug"])
            else:
                s3_key = f"<UNKNOWN release_type {rt!r} - the run would FAIL on it>"
            policy = "SKIP-IF-EXISTS" if decision == "skip" else "ALWAYS-FETCH"
            print(f"  {rt:<22}  {policy:<15}  ->  {s3_key}")
            print(f"    {url}")
        n_live = sum(
            1 for e, d in planned
            if not is_article(e["release_type"]) and d == "fetch"
        )
        n_data = sum(1 for e, _d in planned if not is_article(e["release_type"]))
        print(f"  ---  {n_data} data entries, of which {n_live} ALWAYS-FETCH and "
              f"{n_data - n_live} CLOSED-YEAR skip-if-exists; "
              f"{len(planned) - n_data} article entries")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = 0
    data_skipped = articles_skipped = breaker_skipped = 0
    data_fetched = requested_urls = 0
    data_errors = article_errors = 0
    probe_failures = 0
    consecutive_article_throttles = 0
    article_breaker_tripped = False
    failed_labels: list[str] = []

    if args.skip_existing_s3:
        logger.warning(
            "--skip-existing-s3 is INERT and is ignored. stock_comparison and competitive_prices "
            "are MUTABLE live snapshots and are always re-fetched (an existence-only skip on a "
            "mutable source is the MPOB BEPI freeze); %s year pages are skipped when the year is "
            "CLOSED (<= %d) whether or not this flag is passed, and --refetch-years is the flag "
            "that overrides THAT; and %s is skipped by default, with --refetch-articles the "
            "override.",
            YEAR_KEYED_RELEASE_TYPE, date.today().year - 1 - _MUTABLE_YEARS_BACK,
            ARTICLE_RELEASE_TYPE,
        )

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # Resolve every entry's key and label FIRST. An undeclared class fails CLOSED here -- it is
    # counted as DATA, so it reaches the exit code -- and never enters the request budget.
    work: list[tuple[dict, str, str]] = []
    for entry in releases:
        rt = entry["release_type"]
        if rt == "trade_statistics":
            s3_key = raw_mpoc_trade_stats_key(entry["year"])
            label = f"trade_statistics/{entry['year']}"
        elif rt == "stock_comparison":
            s3_key = raw_mpoc_stock_comparison_key()
            label = "stock_comparison"
        elif rt == "competitive_prices":
            s3_key = raw_mpoc_competitive_prices_key()
            label = "competitive_prices"
        elif rt == ARTICLE_RELEASE_TYPE:
            s3_key = raw_mpoc_article_key(entry["slug"])
            label = f"{ARTICLE_RELEASE_TYPE}/{entry['slug']}"
        else:
            logger.error("Unknown release_type %r in %s - refusing to guess its key",
                         rt, _MANIFEST_PATH.name)
            data_errors += 1
            failed_labels.append(f"unknown release_type {rt!r}")
            continue
        work.append((entry, s3_key, label))

    def _plan(item: tuple[dict, str, str]) -> str:
        nonlocal probe_failures
        item_entry, item_key, item_label = item
        try:
            return plan_entry(
                item_entry["release_type"],
                year=item_entry.get("year"),
                key_exists=lambda: s3_object_exists(bucket, item_key, region),
                refetch_articles=args.refetch_articles,
                refetch_years=args.refetch_years,
                skip_existing_flag=args.skip_existing_s3,
            )
        except Exception as exc:  # noqa: BLE001 -- an unanswerable probe may not authorise a skip
            # The existence probe is the ONLY thing that can turn a policy into a skip. When S3
            # cannot answer it, the run FETCHES: a skip nobody could justify is the shape that
            # freezes an archive. The fetch itself is still counted by its own class below.
            probe_failures += 1
            logger.warning("S3 existence probe failed for %s (%s: %s) - FETCHING it instead",
                           item_label, type(exc).__name__, str(exc)[:160])
            return "fetch"

    # `--limit` is a REQUEST budget, never a slice of the plan: skips are walked and reported and
    # can never spend it. See plan_run.
    planned = plan_run(work, _plan, args.limit)
    if args.limit and len(planned) < len(work):
        logger.info(
            "--limit %d: stopping after %d request(s); %d of %d entries walked.",
            args.limit, args.limit, len(planned), len(work),
        )

    for (entry, s3_key, label), decision in planned:
        rt = entry["release_type"]
        url = entry["stat_url"]
        is_data = not is_article(rt)

        if decision == "skip":
            logger.info(
                "Skipping - already in S3 (%s): %s",
                "closed archive year" if is_data else "banked article", s3_key,
            )
            skipped += 1
            if is_data:
                data_skipped += 1
            else:
                articles_skipped += 1
            continue

        if article_breaker_tripped and not is_data:
            skipped += 1
            breaker_skipped += 1
            continue

        try:
            if is_data:
                data_fetched += 1
            requested_urls += 1
            logger.info("Downloading %s  %s …", label, url)

            html_text = _download_html(url, session, max_attempts=args.max_attempts)
            consecutive_article_throttles = 0
            html_upper = html_text.upper()

            # Validate content
            if rt == "trade_statistics":
                if _MARKER_TRADE_STATS not in html_upper:
                    raise RuntimeError(
                        f"Validation failed: '{_MARKER_TRADE_STATS}' not found in {url}"
                    )
                _assert_tables_parseable(html_text, rt, url)
                check_min_file_size(html_text.encode("utf-8"), "mpoc_trade_stats", context=url)

            elif rt == "stock_comparison":
                if _MARKER_STOCK_COMPARISON not in html_upper:
                    raise RuntimeError(
                        f"Validation failed: '{_MARKER_STOCK_COMPARISON}' not found in {url}"
                    )
                _assert_tables_parseable(html_text, rt, url)
                check_min_file_size(html_text.encode("utf-8"), "mpoc_stock_comparison", context=url)

            elif rt == "competitive_prices":
                if _MARKER_COMPETITIVE_PRICES_A not in html_upper or _MARKER_COMPETITIVE_PRICES_B not in html_upper:
                    raise RuntimeError(
                        f"Validation failed: 'CPO' or 'SBO' not found in {url}"
                    )
                check_min_file_size(html_text.encode("utf-8"), "mpoc_competitive_prices", context=url)

            else:  # market_highlights
                check_min_file_size(html_text.encode("utf-8"), "mpoc_article", context=url)

            payload = html_text.encode("utf-8")
            content_type = "text/html; charset=utf-8"

            upload_bytes_to_s3(payload, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket,
                s3_key,
                payload,
                url,
                content_type,
                region,
            )

            logger.info(
                "Uploaded %s  (%.1f KB) → s3://%s/%s",
                label,
                len(payload) / 1_024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            throttled = isinstance(exc, RateLimited)
            if is_data:
                # FAIL CLOSED: the retries are already spent by the time this is reached, so a
                # DATA page still unfetched here is a page the estate could not read at all.
                logger.error("FAILED (DATA, fatal) %s (%s): %s", label, url, exc)
                data_errors += 1
                failed_labels.append(label)
            else:
                logger.warning(
                    "failed (article, NOT fatal) %s (%s): %s", label, url, exc
                )
                article_errors += 1
                if throttled:
                    consecutive_article_throttles += 1
                    if (args.article_breaker > 0
                            and consecutive_article_throttles >= args.article_breaker):
                        article_breaker_tripped = True
                        logger.warning(
                            "ARTICLE BREAKER TRIPPED after %d consecutive rate-limited "
                            "articles - the remaining %s entries are skipped for this run. "
                            "The DATA classes are already done.",
                            consecutive_article_throttles, ARTICLE_RELEASE_TYPE,
                        )
                else:
                    consecutive_article_throttles = 0

        time.sleep(args.sleep_seconds)

    session.close()

    logger.info(
        "Done. uploaded=%d  skipped=%d  data_errors=%d  article_errors=%d",
        uploaded, skipped, data_errors, article_errors,
    )
    # The partitioned line is what the next fire is VERIFIED against: on 2026-10-15 it must read
    # requested=2 (the two live snapshots), skipped_closed_year=15, articles_skipped=342,
    # data_errors=0. Each number is its own population and none is derived by subtracting
    # another: `articles_skipped` used to be computed as `skipped - data_skipped`, which folded
    # the entries the article BREAKER dropped into the banked bucket and overstated it on the one
    # run where the line matters (`--refetch-articles`).
    logger.info(
        "Request budget: requested=%d  skipped_closed_year=%d  articles_skipped=%d  "
        "data_errors=%d  (data_requested=%d  articles_skipped_breaker=%d  article_errors=%d  "
        "s3_probe_failures=%d  limit=%s)",
        requested_urls, data_skipped, articles_skipped, data_errors,
        data_fetched, breaker_skipped, article_errors, probe_failures,
        args.limit if args.limit else "none",
    )

    emit_leg_failure_metric(data_errors, article_errors)

    if article_errors:
        logger.warning(
            "%d %s page(s) failed. This is COUNTED and METERED and does NOT set the exit "
            "code: a news archive may never kill a balance sheet.",
            article_errors, ARTICLE_RELEASE_TYPE,
        )

    reason = exit_reason(data_errors, article_errors, failed_labels)
    if reason:
        raise SystemExit(reason)


if __name__ == "__main__":
    main()
