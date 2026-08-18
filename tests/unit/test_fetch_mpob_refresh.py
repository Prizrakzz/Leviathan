"""D-LD MPOB retrofit -- the manifest-aging fix: constructive slot sweep + honest exit.

Month=05/2026 was permanently lost while the fetch job exited 0 every fire: BEPI's {YYYY}75
root serves only the LATEST published month (older val1 slots roll to an under-construction
placeholder once superseded), and the manifest's single monthly entry was a hand-bumped pin
that nobody bumped past June. These tests pin the URL grammar, the probe-year window, the
sweep classification, the adopt-if-absent merge, the zero-published fail-closed rule and the
comment-preserving manifest append. AWS-free, network-free (modeled on
test_fetch_usda_wasde_refresh.py)."""
from __future__ import annotations

import sys
from datetime import date

import requests
import yaml

from jobs.ingest import fetch_mpob as F


def _monthly(year, month):
    return {
        "release_type": "monthly_release",
        "year": year,
        "month": month,
        "stat_url": F._monthly_stat_url(year, month),
    }


def _annual(year):
    return {
        "release_type": "annual_summary",
        "year": year,
        "stat_url": F._annual_stat_url(year),
    }


# ---------------------------------------------------------------------------
# URL grammar + probe window
# ---------------------------------------------------------------------------

def test_stat_url_grammar_is_pinned():
    # Monthly: val={YYYY}75 with zero-padded val1. Annual: val={YYYY}84.
    # These are the manifest's confirmed live patterns -- a drift here would
    # make every sweep probe the wrong slots and fail closed at fire time.
    assert F._monthly_stat_url(2026, 7) == (
        "https://bepi.mpob.gov.my/stat/web_report1.php?val=202675&val1=07"
    )
    assert F._monthly_stat_url(2026, 12) == (
        "https://bepi.mpob.gov.my/stat/web_report1.php?val=202675&val1=12"
    )
    assert F._annual_stat_url(2027) == (
        "https://bepi.mpob.gov.my/stat/web_report1.php?val=202784"
    )


def test_probe_years_window_and_format_floor():
    # Current + previous year, floored at 2026 (2021-2025 have no monthly pages
    # in this format; 2020 serves all-placeholder). The previous year matters at
    # the January boundary: December publishes ~Jan 10 under the OLD year base.
    assert F._probe_years(date(2026, 8, 18)) == [2026]
    assert F._probe_years(date(2027, 1, 5)) == [2027, 2026]
    assert F._probe_years(date(2028, 6, 1)) == [2028, 2027]


# ---------------------------------------------------------------------------
# Sweep classification
# ---------------------------------------------------------------------------

class _StubResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _StubSession:
    """PUBLISHED for listed urls, error for listed urls, placeholder otherwise."""

    def __init__(self, published_urls=(), error_urls=()):
        self.published_urls = set(published_urls)
        self.error_urls = set(error_urls)
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.calls.append(url)
        if url in self.error_urls:
            raise requests.ConnectionError("connection reset")
        if url in self.published_urls:
            return _StubResponse("<html><body>... CRUDE PALM OIL ...</body></html>")
        return _StubResponse("This page is under construction")


def test_sweep_classifies_published_placeholder_and_error(monkeypatch):
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    sess = _StubSession(
        published_urls={F._monthly_stat_url(2026, 7)},
        error_urls={F._monthly_stat_url(2026, 3)},
    )
    published, placeholders, errors = F._sweep_stat_slots(sess, [2026], 0.0)
    assert published == [_monthly(2026, 7)]
    assert errors == 1
    # 12 monthly slots: 1 published, 1 error, 10 placeholder; +1 annual placeholder.
    assert placeholders == 11
    # Every slot probed exactly once: 12 monthly + 1 annual.
    assert len(sess.calls) == 13


def test_sweep_probe_error_is_counted_never_raised(monkeypatch):
    # One bad slot must not mask what the rest of the sweep proved.
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    sess = _StubSession(error_urls={F._monthly_stat_url(2026, m) for m in range(1, 13)})
    published, placeholders, errors = F._sweep_stat_slots(sess, [2026], 0.0)
    assert published == []
    assert errors == 12
    assert placeholders == 1  # the annual slot still answered (placeholder)


def test_sweep_adopts_the_annual_base_too(monkeypatch):
    # A new year's {YYYY}84 entry otherwise needs a hand-add every Q1 -- the
    # same aging class the monthly sweep closes.
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    sess = _StubSession(
        published_urls={F._annual_stat_url(2026), F._monthly_stat_url(2026, 7)}
    )
    published, _, errors = F._sweep_stat_slots(sess, [2026], 0.0)
    assert _annual(2026) in published
    assert _monthly(2026, 7) in published
    assert errors == 0


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------

def test_merge_adopts_absent_slots_only_and_never_reorders():
    existing = [_annual(2026), _monthly(2026, 6)]
    discovered = [_monthly(2026, 6), _monthly(2026, 7), _annual(2026)]
    merged, adopted = F._merge_manifest(existing, discovered)
    assert adopted == [_monthly(2026, 7)]
    # Existing entries stay untouched and in place (the manifest's section
    # layout is operator documentation); adopted entries append at the end.
    assert merged[:2] == existing
    assert merged[2:] == [_monthly(2026, 7)]


def test_merge_is_a_noop_on_a_quiet_day():
    existing = [_monthly(2026, 6)]
    merged, adopted = F._merge_manifest(existing, [_monthly(2026, 6)])
    assert adopted == []
    assert merged == existing


# ---------------------------------------------------------------------------
# Fail-closed rule (the WASDE M-1 analog)
# ---------------------------------------------------------------------------

def test_zero_published_sweep_fails_closed(monkeypatch):
    """--refresh-manifest with ZERO published monthly slots must exit 1, never proceed.

    The {YYYY}75 root serves the latest month whenever any month has published, so an
    all-placeholder (or all-error) sweep is a probe fault or a site regression --
    falling back to the static manifest silently reproduces the month=05/2026 loss
    this flag exists to end.
    """
    monkeypatch.setattr(F, "_sweep_stat_slots", lambda *a, **kw: ([], 24, 2))
    monkeypatch.setattr(sys, "argv", ["fetch_mpob.py", "--refresh-manifest", "--dry-run"])
    assert F.main() == 1


def test_annual_only_sweep_still_fails_closed(monkeypatch):
    # An annual hit proves the site is up but NOT that the monthly root works --
    # the zero-published rule is scoped to monthly slots on purpose.
    monkeypatch.setattr(
        F, "_sweep_stat_slots", lambda *a, **kw: ([_annual(2026)], 23, 0)
    )
    monkeypatch.setattr(sys, "argv", ["fetch_mpob.py", "--refresh-manifest", "--dry-run"])
    assert F.main() == 1


def test_published_month_is_adopted_and_reaches_the_dry_run_listing(monkeypatch, capsys):
    monkeypatch.setattr(
        F, "_sweep_stat_slots", lambda *a, **kw: ([_monthly(2026, 7)], 12, 0)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_mpob.py",
            "--refresh-manifest",
            "--dry-run",
            "--release-type",
            "monthly_release",
            "--year",
            "2026",
        ],
    )
    rc = F.main()
    assert rc is None
    out = capsys.readouterr().out
    # The adopted month flows through the merge into the ordinary fetch plan.
    assert "month=07/mpob_monthly_2026_07.html" in out
    # And the manifest's own June entry is still there beside it.
    assert "month=06/mpob_monthly_2026_06.html" in out


def test_without_the_flag_no_sweep_runs(monkeypatch, capsys):
    def _boom(*a, **kw):
        raise AssertionError("sweep must not run without --refresh-manifest")

    monkeypatch.setattr(F, "_sweep_stat_slots", _boom)
    monkeypatch.setattr(sys, "argv", ["fetch_mpob.py", "--dry-run", "--limit", "1"])
    assert F.main() is None


# ---------------------------------------------------------------------------
# Manifest append (--save-manifest)
# ---------------------------------------------------------------------------

def test_save_manifest_appends_valid_yaml_without_touching_the_body(tmp_path, monkeypatch):
    body = (
        "# operator documentation that a rewrite would destroy\n"
        "\n"
        "releases:\n"
        "\n"
        "  - release_type: monthly_release\n"
        "    year: 2026\n"
        "    month: 6\n"
        '    stat_url: "https://bepi.mpob.gov.my/stat/web_report1.php?val=202675&val1=06"\n'
    )
    m = tmp_path / "mpob_archive.yaml"
    m.write_text(body, encoding="utf-8")
    monkeypatch.setattr(F, "_MANIFEST_PATH", m)

    F._append_manifest_entries([_monthly(2026, 7), _annual(2027)])

    text = m.read_text(encoding="utf-8")
    assert text.startswith(body)  # byte-for-byte: comments and layout survive
    data = yaml.safe_load(text)
    assert _monthly(2026, 7) in data["releases"]
    assert _annual(2027) in data["releases"]
    assert len(data["releases"]) == 3


def test_the_checked_in_manifest_parses_and_carries_the_known_slots():
    # The real manifest must stay loadable by the exact loader main() uses, and
    # the retrofit must not have disturbed the entries the estate already holds.
    data = yaml.safe_load(F._MANIFEST_PATH.read_text(encoding="utf-8"))
    releases = data["releases"]
    assert _monthly(2026, 6) in releases
    assert {"release_type", "year", "stat_url"} <= set(releases[0].keys())
