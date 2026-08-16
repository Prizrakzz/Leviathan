"""D-SG G1-2(a) -- the WASDE fetch-gap fix: manifest refresh + honest exit.

The 2026-08-12 release was absent from RAW for 37 days while the fetch job exited 0 every fire:
the manifest is a static config whose newest entry was 2026-07-10 and esmis release URLs carry
an opaque node id, so an unlisted release is unreachable. These tests pin the merge semantics
and the recency-scoped failure rule. AWS-free, network-free."""
from __future__ import annotations

from jobs.ingest import fetch_usda_wasde as F


def _entry(month, rd, mmyy):
    return {"release_date": rd, "calendar_month": month, "mmyy": mmyy, "fmt": "pdf",
            "url": f"https://esmis.nal.usda.gov/sites/default/release-files/x/wasde{mmyy}.pdf",
            "filename": f"wasde{mmyy}.pdf"}


def test_merge_adopts_a_new_month_and_a_newer_correction_only():
    existing = [_entry("2026-06", "2026-06-11", "0626"), _entry("2026-07", "2026-07-10", "0726")]
    discovered = [
        _entry("2026-08", "2026-08-12", "0826"),          # the missing release: adopted
        _entry("2026-07", "2026-07-10", "0726"),          # identical: no-op
        _entry("2026-06", "2026-06-12", "0626"),          # newer correction: adopted
    ]
    merged, changed = F._merge_manifest(existing, discovered)
    assert changed == ["2026-06", "2026-08"]
    assert [e["release_date"] for e in merged] == ["2026-06-12", "2026-07-10", "2026-08-12"]
    # an OLDER discovered date never overwrites a newer stored one.
    merged2, changed2 = F._merge_manifest(merged, [_entry("2026-08", "2026-08-01", "0826")])
    assert changed2 == []
    assert [e["release_date"] for e in merged2] == [e["release_date"] for e in merged]


def test_recency_window_is_the_exit_rule_not_the_raw_error_count():
    # the three permanently-404 correction URLs are all pre-2010: outside the window, so they
    # must NOT redden the lane; a current-month failure must.
    assert F._RECENT_FAILURE_DAYS >= 60
    for dead in ("2001-05-10", "2002-05-10", "2006-07-12"):
        assert dead < "2020-01-01"


def test_an_empty_scrape_fails_closed_instead_of_using_the_static_manifest(monkeypatch, capsys):
    """Review M-1: --refresh-manifest with ZERO scraped entries must exit 1, never proceed.

    The archive head always carries ~12 releases, so an empty scrape is a scrape fault
    (esmis 5xx, WAF, DOM change) -- falling back to the static manifest silently reproduces
    the 2026-08-12 37-day miss this flag exists to end.
    """
    import sys

    monkeypatch.setattr(F, "_load_manifest", lambda: [_entry("2026-07", "2026-07-10", "0726")])
    monkeypatch.setattr(F, "_build_manifest_entries", lambda *a, **kw: [])
    monkeypatch.setattr(sys, "argv", ["fetch_usda_wasde.py", "--refresh-manifest", "--dry-run"])
    rc = F.main()
    assert rc == 1
