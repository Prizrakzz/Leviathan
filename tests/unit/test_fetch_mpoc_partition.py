"""P11 pins for jobs/ingest/fetch_mpoc.py -- the release_type partition and the closed-year rule.

THE FIRE THESE ARE MEASURED AGAINST
-----------------------------------
On 2026-09-15 the MPOC monthly fire FAILED at the fetch leg and bronze, silver, gate and promote
never ran. The shape below is READ OUT of CloudWatch log stream
``leviathan-dev-b3-flat-silver/default/94fb9a0fc82642eab6f4246e75d23a26`` (721 events, re-read
2026-09-22, 248 ``Failed`` lines partitioned by the label each one names):

    uploaded            111
    skipped               0
    Failed              248   all of them ``429 Too Many Requests``
      market_highlights 236
      trade_statistics   11   years 2012-2020, 2022, 2023
      stock_comparison    1
    FIRST 429 of the run  12:01:17.671 on trade_statistics/2012  -- a DATA page, not an article
    non-article uploads   5   trade_statistics 2009/2010/2011/2021 + competitive_prices
    stock_comparison          NEVER landed; the estate still serves the 2026-08-15 snapshot

The round-1 report claimed this fire was ``data_errors=0, article_errors=248``. It was not: it was
TWELVE data failures against 236 articles, so the release_type partition ALONE would still have
exited non-zero and the family would still have died. That claim, and the pin that carried it, are
corrected here -- a CLOSED item may not re-present a measurement that is wrong by twelve.

WHAT ACTUALLY SAVES THAT FIRE, and what each rule below pins
------------------------------------------------------------
1. ``skip_policy`` never skips a LIVE snapshot (stock_comparison, competitive_prices), whatever
   flag the caller passes: an existence-only skip on a mutable page is the MPOB BEPI freeze
   (cea8818a) -- the forbidden shape.
2. ``trade_stats_year_is_closed`` / ``plan_entry``: a trade_statistics YEAR page two or more years
   old is a CLOSED, immutable archive object and is skipped when the estate holds it, while the
   CURRENT and PREVIOUS years are always fetched. All eleven year pages that 429'd on 2026-09-15
   were already banked (S3 mtimes 2026-08-15, measured), so this removes eleven of the twelve data
   requests -- and a closed year the estate does NOT hold is still fetched, and still fatal.
3. An UNDECLARED release_type fails CLOSED (treated as data), never into the non-fatal article
   bucket.
4. ``order_releases`` puts data first STRUCTURALLY, so a manifest re-ordering cannot cost the
   estate a balance sheet.
5. ``exit_reason`` reads ``data_errors`` and nothing else: 248 article failures cannot set the exit
   code, and a live page the run could not read after its retries were spent always does.
6. Retry-After / exponential backoff on 429 and 503, on the DATA leg as much as the article leg --
   the flat ``--sleep-seconds 1.0`` was never a backoff and walked into 248 consecutive 429s.
7. ROUND 3: ``--limit`` counts REQUESTS, and ``order_releases`` ranks by MUTABILITY. Rule 2 made
   the fifteen closed year pages skip; ranking data by CLASS left them at the head of the list;
   and slicing the PLAN at N therefore made ``--limit 1`` issue ZERO HTTP requests and exit 0 --
   a smoke that cannot fail, on the command the estate's pre-arm law names. Measured on the live
   manifest before the fix: the first FETCH appeared at N=16. Both halves are pinned below, in
   both directions, with ``today=2026-10-15`` and every key banked.
"""
from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_FETCHER = _REPO / "jobs" / "ingest" / "fetch_mpoc.py"

# The 2026-09-15 fire, as the log names it. The eleven year pages are the exact years that 429'd.
_FIRE_DATE = date(2026, 9, 15)
_FIRE_TRADE_STATS_FAILED_YEARS = (2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2022, 2023)
_FIRE_TRADE_STATS_UPLOADED_YEARS = (2009, 2010, 2011, 2021)
_FIRE_FAILED_LABELS = tuple(
    [f"trade_statistics/{y}" for y in _FIRE_TRADE_STATS_FAILED_YEARS]
    + ["stock_comparison"]
    + [f"market_highlights/slug-{i:03d}" for i in range(236)]
)


def _load_fetcher():
    spec = importlib.util.spec_from_file_location("fetch_mpoc_under_test", _FETCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fm = _load_fetcher()

# The day the request-budget pins fix, so an operator running the smoke in 2027 reads the same
# numbers this report does. It is the next scheduled fire after the round-3 fix.
_LIMIT_DAY = date(2026, 10, 15)


def _live_manifest() -> list[dict]:
    """The 359 real manifest entries -- the pins bind the shipped yaml, never a sample of it."""
    return yaml.safe_load(
        (_REPO / "configs" / "sources" / "mpoc_archive.yaml").read_text(encoding="utf-8")
    )["releases"]


def _banked_plan(entry: dict) -> str:
    """plan_entry with EVERY key banked -- the state the estate is really in (359 objects)."""
    return fm.plan_entry(entry["release_type"], year=entry.get("year"),
                         key_exists=lambda: True, today=_LIMIT_DAY)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """Replays a scripted sequence of responses and records every URL it was asked for."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url, timeout=None, allow_redirects=True):  # noqa: ANN001
        self.calls.append(url)
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# 1. The LIVE snapshots are never skipped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("release_type", ["stock_comparison", "competitive_prices"])
def test_skip_policy_never_skips_a_live_snapshot(release_type):
    """Not with the legacy flag, not with --refetch-articles, not by default, in any year.

    These two are single-key pages MPOC rewrites in place. An existence-only skip on either is
    the MPOB BEPI freeze -- the shape this estate has already paid for once.
    """
    for flag in (False, True):
        for refetch in (False, True):
            for refetch_years in (False, True):
                for year in (None, 2009, 2026):
                    assert fm.skip_policy(
                        release_type, year=year, refetch_articles=refetch,
                        refetch_years=refetch_years, skip_existing_flag=flag,
                        today=_FIRE_DATE,
                    ) is False


# ---------------------------------------------------------------------------
# 1b. The CLOSED-YEAR rule (round 2) -- the one permitted existence skip on a DATA class
# ---------------------------------------------------------------------------


def test_the_current_and_previous_year_pages_are_always_fetched():
    """A year page gains a month row while its own year runs, and a last one for December.

    A blanket skip on trade_statistics would re-create the MPOB BEPI freeze on the year page that
    is still filling. The lookback is stated in YEARS, so this stays true every January.
    """
    for today in (date(2026, 9, 15), date(2027, 1, 2), date(2030, 12, 31)):
        assert fm.trade_stats_year_is_closed(today.year, today) is False
        assert fm.trade_stats_year_is_closed(today.year - 1, today) is False
        assert fm.skip_policy("trade_statistics", year=today.year, today=today) is False
        assert fm.skip_policy("trade_statistics", year=today.year - 1, today=today) is False


def test_every_year_of_the_2009_2023_archive_is_closed_today():
    """monthly-palm-oil-trade-statistics-2024 and -2025 both 404 (re-measured 2026-09-22): the
    series ended at 2023, and a year page that can gain no row is an immutable archive object."""
    for year in range(2009, 2024):
        assert fm.trade_stats_year_is_closed(year, _FIRE_DATE) is True
        assert fm.skip_policy("trade_statistics", year=year, today=_FIRE_DATE) is True


def test_a_trade_statistics_entry_with_no_year_fails_closed():
    """A manifest row that lost its year is fetched, never skipped on a guess."""
    assert fm.skip_policy("trade_statistics", year=None, today=_FIRE_DATE) is False


def test_a_closed_year_page_the_estate_does_not_hold_is_still_fetched():
    """The skip is an EXISTENCE skip. The closed-year rule may not become a frozen pointer: a
    2012 page missing from S3 is fetched, and its failure is still fatal."""
    assert fm.plan_entry("trade_statistics", year=2012, key_exists=lambda: True,
                         today=_FIRE_DATE) == "skip"
    assert fm.plan_entry("trade_statistics", year=2012, key_exists=lambda: False,
                         today=_FIRE_DATE) == "fetch"


def test_a_live_snapshot_is_never_HEADed_at_all():
    """plan_entry short-circuits: the existence probe is only spent where a skip is possible."""
    calls = []

    def _exists():
        calls.append(1)
        return True

    assert fm.plan_entry("stock_comparison", key_exists=_exists, today=_FIRE_DATE) == "fetch"
    assert fm.plan_entry("competitive_prices", key_exists=_exists, today=_FIRE_DATE) == "fetch"
    assert calls == []


def test_the_closed_year_rule_removes_eleven_of_the_twelve_2026_09_15_data_requests():
    """The measured fire, replayed against the rule.

    All 15 year pages were banked before the fire (the eleven that 429'd carry 2026-08-15 S3
    mtimes), so the data leg issues TWO requests -- the two live snapshots -- instead of
    seventeen, and the eleven 429s that were each a candidate to kill promote cannot happen.
    """
    manifest = yaml.safe_load(
        (_REPO / "configs" / "sources" / "mpoc_archive.yaml").read_text(encoding="utf-8")
    )
    data_entries = [r for r in manifest["releases"] if not fm.is_article(r["release_type"])]
    assert len(data_entries) == 17

    banked = lambda: True  # noqa: E731 -- every one of the 17 data keys is on S3 (measured)
    fetched = [
        r for r in data_entries
        if fm.plan_entry(r["release_type"], year=r.get("year"), key_exists=banked,
                         today=_FIRE_DATE) == "fetch"
    ]
    assert sorted(r["release_type"] for r in fetched) == [
        "competitive_prices", "stock_comparison",
    ]
    # and none of the eleven years that 429'd is in the request list
    fetched_years = {r.get("year") for r in fetched}
    assert fetched_years.isdisjoint(_FIRE_TRADE_STATS_FAILED_YEARS)


def test_skip_policy_skips_a_banked_article_by_default():
    """All 342 article slugs are already on S3; re-walking them is what tripped the 429 wall."""
    assert fm.skip_policy(fm.ARTICLE_RELEASE_TYPE) is True


def test_refetch_articles_forces_the_full_archive():
    assert fm.skip_policy(fm.ARTICLE_RELEASE_TYPE, refetch_articles=True) is False


def test_an_undeclared_release_type_is_treated_as_data():
    """A fifth series added to the manifest must fail CLOSED, not inherit the article exemption."""
    assert fm.is_article("brand_new_series") is False
    assert fm.skip_policy("brand_new_series", refetch_articles=True) is False


def test_the_live_manifest_declares_only_the_four_known_classes():
    """A new release_type in the yaml has to come with a decision about its class, in code.

    Without this the manifest could silently grow a class whose failures never reach an exit code.
    """
    manifest = yaml.safe_load(
        (_REPO / "configs" / "sources" / "mpoc_archive.yaml").read_text(encoding="utf-8")
    )
    seen = {r["release_type"] for r in manifest["releases"]}
    declared = set(fm.DATA_RELEASE_TYPES) | {fm.ARTICLE_RELEASE_TYPE}
    assert seen <= declared, f"undeclared MPOC release_type(s): {sorted(seen - declared)}"


# ---------------------------------------------------------------------------
# 2. Ordering
# ---------------------------------------------------------------------------


def test_order_releases_puts_every_data_entry_before_every_article():
    """RESTATED in round 3: the rank is MUTABILITY, not class.

    Round 2 ranked by class alone, so a CLOSED 2019 year page -- an entry that now always skips --
    sorted ahead of the two live snapshots and became the first thing a truncated run touched.
    Every data entry still precedes every article; within the data classes the pages a fire
    really requests now come first.
    """
    releases = [
        {"release_type": "market_highlights", "slug": "a"},
        {"release_type": "trade_statistics", "year": 2019},
        {"release_type": "market_highlights", "slug": "b"},
        {"release_type": "stock_comparison"},
        {"release_type": "competitive_prices"},
    ]
    ordered = fm.order_releases(releases, _LIMIT_DAY)
    types = [r["release_type"] for r in ordered]
    assert types == [
        "stock_comparison", "competitive_prices", "trade_statistics",
        "market_highlights", "market_highlights",
    ]
    # every data entry still precedes every article
    assert all(not fm.is_article(r["release_type"]) for r in ordered[:3])
    # order is preserved WITHIN each rank
    assert [r["slug"] for r in ordered if r["release_type"] == "market_highlights"] == ["a", "b"]


def test_order_releases_is_stable_when_the_manifest_leads_with_articles():
    """The 2026-09-15 data legs landed first by luck of manifest order. Now it is structural."""
    releases = [{"release_type": "market_highlights", "slug": str(i)} for i in range(250)]
    releases.append({"release_type": "stock_comparison"})
    assert fm.order_releases(releases)[0]["release_type"] == "stock_comparison"


# ---------------------------------------------------------------------------
# 2b. MAJOR-A (round 3): the request budget, and the rank that makes it a smoke
# ---------------------------------------------------------------------------


def test_the_rank_is_mutability_and_not_class():
    """0 = a page every fire requests, 1 = the closed archive, 2 = an article."""
    rank = fm.release_fetch_rank
    assert rank("stock_comparison", today=_LIMIT_DAY) == 0
    assert rank("competitive_prices", today=_LIMIT_DAY) == 0
    assert rank("trade_statistics", year=2026, today=_LIMIT_DAY) == 0   # the current year
    assert rank("trade_statistics", year=2025, today=_LIMIT_DAY) == 0   # the previous year
    assert rank("trade_statistics", year=2024, today=_LIMIT_DAY) == 1   # closed
    assert rank("trade_statistics", year=2009, today=_LIMIT_DAY) == 1
    assert rank("market_highlights", today=_LIMIT_DAY) == 2
    # a year page with no year cannot be proven closed, so it ranks with the pages that are fetched
    assert rank("trade_statistics", year=None, today=_LIMIT_DAY) == 0
    # an UNDECLARED class ranks with the data, never with the articles
    assert rank("brand_new_series", today=_LIMIT_DAY) == 0


def test_a_current_year_page_sorts_ahead_of_the_closed_archive():
    """MPOC resuming the series must not push the live pages down the list either."""
    releases = [
        {"release_type": "trade_statistics", "year": y} for y in (2009, 2023, 2025, 2026)
    ] + [{"release_type": "stock_comparison"}]
    ordered = fm.order_releases(releases, _LIMIT_DAY)
    assert [(r["release_type"], r.get("year")) for r in ordered] == [
        ("trade_statistics", 2025), ("trade_statistics", 2026),
        ("stock_comparison", None),
        ("trade_statistics", 2009), ("trade_statistics", 2023),
    ]


def test_limit_1_issues_exactly_one_request_and_it_is_a_mutable_page():
    """THE ROUND-2 REGRESSION, pinned shut. today=2026-10-15, every key banked.

    Round 2 ordered DATA-by-class and sliced the PLAN at N, so the fifteen closed trade_statistics
    years led the list and `--limit 1` planned ['skip']: ZERO HTTP requests, nothing validated,
    `uploaded=0 skipped=1`, exit 0 -- on the one command the estate's pre-arm law tells an
    operator to run before a fire. Measured on the live manifest before the fix: the first FETCH
    appeared at N=16.
    """
    ordered = fm.order_releases(_live_manifest(), _LIMIT_DAY)
    planned = fm.plan_run(ordered, _banked_plan, 1)
    fetched = [e for e, d in planned if d == "fetch"]
    assert len(fetched) == 1
    assert fetched[0]["release_type"] == "stock_comparison"
    # and it is a MUTABLE page: no flag and no year makes it skippable
    assert fm.skip_policy("stock_comparison", refetch_articles=True,
                          refetch_years=True, skip_existing_flag=True,
                          today=_LIMIT_DAY) is False


def test_limit_counts_requests_and_never_plan_entries():
    """A run whose head is fifteen skips still spends its budget on a real page."""
    releases = [{"release_type": "trade_statistics", "year": y} for y in range(2009, 2024)]
    releases.append({"release_type": "stock_comparison"})
    planned = fm.plan_run(releases, _banked_plan, 1)
    assert [d for _e, d in planned] == ["skip"] * 15 + ["fetch"]
    assert sum(1 for _e, d in planned if d == "fetch") == 1
    # the skips are WALKED and reported -- they are the count line the next fire is verified by
    assert len(planned) == 16


def test_limit_2_takes_both_live_snapshots_and_limit_none_walks_everything():
    ordered = fm.order_releases(_live_manifest(), _LIMIT_DAY)
    two = [e["release_type"] for e, d in fm.plan_run(ordered, _banked_plan, 2) if d == "fetch"]
    assert two == ["stock_comparison", "competitive_prices"]
    for no_limit in (None, 0):
        planned = fm.plan_run(ordered, _banked_plan, no_limit)
        assert len(planned) == 359
        assert sum(1 for _e, d in planned if d == "fetch") == 2


def test_the_2026_10_15_request_budget_is_2_15_342_and_0():
    """The four numbers the next scheduled fire is READ against, computed off the live manifest.

    `Request budget: requested=2  skipped_closed_year=15  articles_skipped=342  data_errors=0`.
    Each is its own population: `articles_skipped` used to be `skipped - data_skipped`, which
    folded the entries the article BREAKER dropped into the banked bucket.
    """
    ordered = fm.order_releases(_live_manifest(), _LIMIT_DAY)
    planned = fm.plan_run(ordered, _banked_plan, None)
    requested = [e for e, d in planned if d == "fetch"]
    closed_year = [e for e, d in planned
                   if d == "skip" and not fm.is_article(e["release_type"])]
    articles = [e for e, d in planned if d == "skip" and fm.is_article(e["release_type"])]
    assert (len(requested), len(closed_year), len(articles)) == (2, 15, 342)
    assert sorted(e["release_type"] for e in requested) == [
        "competitive_prices", "stock_comparison",
    ]


def test_the_round_2_rule_really_did_empty_the_smoke_and_this_tree_does_not():
    """The regression, MEASURED both ways on the live manifest, so the claim can never drift.

    Round 2's rule, reproduced here in the test rather than trusted from a report: rank data 0 /
    articles 1, then take the first N PLAN ENTRIES. Its first fifteen entries are the closed
    trade_statistics years, every one a skip, and the first FETCH appears at N=16.
    """
    manifest = _live_manifest()
    round2_order = sorted(
        manifest,
        key=lambda r: 0 if r["release_type"] in fm.DATA_RELEASE_TYPES else 1,
    )
    round2_decisions = [_banked_plan(r) for r in round2_order[:15]]
    assert round2_decisions == ["skip"] * 15
    first_fetch_at = next(
        i for i, r in enumerate(round2_order, 1) if _banked_plan(r) == "fetch"
    )
    assert first_fetch_at == 16

    # and this tree: one request, at N=1
    this_tree = fm.order_releases(manifest, _LIMIT_DAY)
    assert _banked_plan(this_tree[0]) == "fetch"
    assert sum(1 for _e, d in fm.plan_run(this_tree, _banked_plan, 1) if d == "fetch") == 1


def test_refetch_years_forces_the_closed_archive_back_into_the_request_list():
    """The operator's answer to a banked year page found corrupt -- previously an S3 hand-delete."""
    assert fm.skip_policy("trade_statistics", year=2012, today=_LIMIT_DAY) is True
    assert fm.skip_policy("trade_statistics", year=2012, refetch_years=True,
                          today=_LIMIT_DAY) is False
    assert fm.plan_entry("trade_statistics", year=2012, key_exists=lambda: True,
                         refetch_years=True, today=_LIMIT_DAY) == "fetch"
    # it reaches the year pages and NOTHING else: articles keep their own flag
    assert fm.skip_policy(fm.ARTICLE_RELEASE_TYPE, refetch_years=True) is True
    ordered = fm.order_releases(_live_manifest(), _LIMIT_DAY)
    planned = fm.plan_run(
        ordered,
        lambda r: fm.plan_entry(r["release_type"], year=r.get("year"),
                                key_exists=lambda: True, refetch_years=True, today=_LIMIT_DAY),
        None,
    )
    assert sum(1 for _e, d in planned if d == "fetch") == 17


# ---------------------------------------------------------------------------
# 3. The exit-code partition
# ---------------------------------------------------------------------------


def test_the_measured_2026_09_15_partition_is_236_11_and_1():
    """The fire's real shape, asserted so the claim can never drift back to "all articles".

    248 Failed lines: 236 market_highlights, 11 trade_statistics year pages, 1 stock_comparison.
    """
    assert len(_FIRE_FAILED_LABELS) == 248
    by_class: dict[str, int] = {}
    for label in _FIRE_FAILED_LABELS:
        by_class[label.split("/")[0]] = by_class.get(label.split("/")[0], 0) + 1
    assert by_class == {
        "market_highlights": 236, "trade_statistics": 11, "stock_comparison": 1,
    }
    # 4 uploaded + 11 failed = the whole 15-year archive; competitive_prices was the 5th upload.
    assert len(set(_FIRE_TRADE_STATS_FAILED_YEARS) | set(_FIRE_TRADE_STATS_UPLOADED_YEARS)) == 15


def test_the_release_type_partition_ALONE_would_not_have_saved_the_2026_09_15_fire():
    """The corrected record. Twelve DATA failures is an exit code under this rule, and should be.

    The round-1 pin asserted ``exit_reason(0, 248) is None`` and called (0, 248) the measured
    shape of this fire. (0, 248) never occurred. What saves the fire is the request list, not the
    partition -- see test_the_closed_year_rule_removes_eleven_of_the_twelve... above.
    """
    data_failures = [
        lb for lb in _FIRE_FAILED_LABELS if not fm.is_article(lb.split("/")[0])
    ]
    article_failures = [lb for lb in _FIRE_FAILED_LABELS if fm.is_article(lb.split("/")[0])]
    assert (len(data_failures), len(article_failures)) == (12, 236)
    reason = fm.exit_reason(len(data_failures), len(article_failures), data_failures)
    assert reason is not None
    assert "trade_statistics/2012" in reason and "stock_comparison" in reason


def test_exit_reason_reads_data_errors_and_nothing_else():
    """What the function actually binds, stated as its own name.

    Any number of article failures exits 0; one data failure does not, at any article count.
    """
    for articles in (0, 1, 236, 248, 10_000):
        assert fm.exit_reason(data_errors=0, article_errors=articles) is None
        assert fm.exit_reason(data_errors=1, article_errors=articles) is not None


def test_the_exit_message_names_the_metered_article_failures_without_counting_them():
    """The operator reads one line at 12:00Z; it may not hide the other half of the fire."""
    reason = fm.exit_reason(1, 236, ["stock_comparison"])
    assert "1 DATA report(s) failed" in reason
    assert "236 market_highlights page(s) also failed and were metered" in reason


def test_one_data_failure_still_fails_the_run():
    reason = fm.exit_reason(data_errors=1, article_errors=0, failed_labels=["stock_comparison"])
    assert reason is not None
    assert "stock_comparison" in reason


def test_data_failures_fail_even_when_articles_are_clean():
    assert fm.exit_reason(data_errors=3, article_errors=0) is not None


# ---------------------------------------------------------------------------
# 4. Backoff
# ---------------------------------------------------------------------------


def test_retry_after_seconds_honours_a_numeric_header():
    resp = _FakeResponse(429, headers={"Retry-After": "12"})
    assert fm._retry_after_seconds(resp, attempt=0, base=2.0, cap=60.0) == 12.0


def test_retry_after_seconds_honours_an_http_date_header():
    when = datetime.now(timezone.utc) + timedelta(seconds=20)
    stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    resp = _FakeResponse(429, headers={"Retry-After": stamp})
    wait = fm._retry_after_seconds(resp, attempt=0, base=2.0, cap=60.0)
    assert 10.0 <= wait <= 25.0


def test_retry_after_is_capped_so_a_hostile_header_cannot_park_a_batch_job():
    resp = _FakeResponse(429, headers={"Retry-After": "86400"})
    assert fm._retry_after_seconds(resp, attempt=0, base=2.0, cap=60.0) == 60.0


def test_backoff_is_exponential_without_a_header():
    resp = _FakeResponse(429)
    waits = [fm._retry_after_seconds(resp, attempt=i, base=2.0, cap=60.0) for i in range(4)]
    assert waits == [2.0, 4.0, 8.0, 16.0]


def test_download_html_retries_a_429_and_then_succeeds():
    session = _FakeSession([
        _FakeResponse(429, headers={"Retry-After": "1"}),
        _FakeResponse(429),
        _FakeResponse(200, text="<html>ok</html>"),
    ])
    slept: list[float] = []
    out = fm._download_html("https://example.test/p", session, sleep=slept.append)
    assert out == "<html>ok</html>"
    assert len(session.calls) == 3
    assert slept == [1.0, 4.0]


def test_download_html_raises_rate_limited_when_the_attempts_are_spent():
    session = _FakeSession([_FakeResponse(429) for _ in range(3)])
    with pytest.raises(fm.RateLimited):
        fm._download_html("https://example.test/p", session, max_attempts=3, sleep=lambda _s: None)
    assert len(session.calls) == 3


def test_download_html_does_not_retry_a_404():
    session = _FakeSession([_FakeResponse(404)])
    with pytest.raises(RuntimeError):
        fm._download_html("https://example.test/p", session, sleep=lambda _s: None)
    assert len(session.calls) == 1


def test_the_DATA_leg_is_retried_exactly_like_the_article_leg():
    """One download path serves both classes, so the balance-sheet page gets the backoff too.

    On 2026-09-15 the FIRST 429 of the run hit trade_statistics/2012 and the flat one-second
    sleep made no second attempt. Here the same URL is tried four times with a real backoff, and
    the failure that survives it is a RateLimited the caller counts as DATA.
    """
    url = "https://mpoc.org.my/monthly-palm-oil-trade-statistics-2012/"
    session = _FakeSession([_FakeResponse(429) for _ in range(4)])
    slept: list[float] = []
    with pytest.raises(fm.RateLimited):
        fm._download_html(url, session, sleep=slept.append)
    assert session.calls == [url] * 4
    assert slept == [2.0, 4.0, 8.0]


def test_a_data_page_still_unfetched_after_the_retries_fails_closed():
    """The retries are spent BEFORE the counter is touched, so a DATA failure is never a warning."""
    assert fm.exit_reason(1, 0, ["stock_comparison"]) is not None
    assert fm.exit_reason(1, 236, ["trade_statistics/2012"]) is not None
