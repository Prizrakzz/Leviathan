"""D-SG G2-1(a) -- UNICA silent-no-op regression pins.

The 2026-08-12 fire was green on every leg while landing nothing: the annual
fetch re-downloaded 41 CLOSED seasons from a hardcoded manifest, and the biweekly
fetch reported "Discovery found no new bulletins" / "Downloading 0 bulletin(s)"
because the one bulletin the portal serves carried a season label derived from
the caller's loop year instead of its own publication month.

These tests pin the four fixes AND the two ways the new fences must NOT fire.
"""
from __future__ import annotations

import asyncio
import textwrap

import pytest

from jobs.ingest import fetch_unica, fetch_unica_biweekly
from leviathan.common.dates import current_harvest_season, harvest_seasons_through


# ---------------------------------------------------------------------------
# (a-i) the static manifest
# ---------------------------------------------------------------------------

def test_manifest_stale_season_exits(tmp_path, monkeypatch):
    """A bare fetch against a manifest that ends before the open season REFUSES."""
    manifest = tmp_path / "unica_sources.yaml"
    manifest.write_text(
        textwrap.dedent(
            """\
            source: unica
            harvest_years:
              - "2019/2020"
              - "2020/2021"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fetch_unica, "_MANIFEST_PATH", manifest)
    monkeypatch.setattr("sys.argv", ["fetch_unica.py", "--asof", "2026-08-12"])

    with pytest.raises(SystemExit) as exc:
        fetch_unica.main()

    msg = str(exc.value)
    assert msg.startswith("MANIFEST STALE")
    assert "2026/2027" in msg
    assert "2020/2021" in msg


def test_through_current_season_extends():
    seasons = harvest_seasons_through("1980/1981", "2026-08-12")
    assert seasons[0] == "1980/1981"
    assert seasons[-1] == "2026/2027"
    assert len(seasons) == 47


def test_current_harvest_season_advances_at_the_april_boundary():
    assert current_harvest_season("2026-03-31") == "2025/2026"
    assert current_harvest_season("2026-04-01") == "2026/2027"
    assert current_harvest_season("2026-12-31") == "2026/2027"
    assert current_harvest_season("2027-02-01") == "2026/2027"


# ---------------------------------------------------------------------------
# (a-iii) the season-scoped zero-advance fence
# ---------------------------------------------------------------------------

def test_zero_advance_open_season_fails():
    reason = fetch_unica_biweekly._exit_reason(
        0, 0, 0, 0, season="2026/2027", season_targets=0, as_of="2026-08-12"
    )
    assert reason is not None
    assert reason.startswith("ZERO-ADVANCE")


def test_quiet_fortnight_stays_green():
    """The anti-false-positive pin: bulletins already in S3 show as skipped>0."""
    assert (
        fetch_unica_biweekly._exit_reason(
            0, 21, 0, 0, season="2026/2027", season_targets=21, as_of="2026-08-12"
        )
        is None
    )


def test_season_inside_grace_stays_green():
    """Three weeks past 1 April is too early to call discovery dead."""
    assert (
        fetch_unica_biweekly._exit_reason(
            0, 0, 0, 0, season="2026/2027", season_targets=0, as_of="2026-04-20"
        )
        is None
    )


def test_unscoped_run_keeps_the_old_contract():
    """Without a season the fence is inert -- the manifest-wide fetch is unchanged."""
    assert fetch_unica_biweekly._exit_reason(0, 0, 0, 0) is None
    assert fetch_unica_biweekly._exit_reason(0, 0, 0, 3).startswith("No bulletins uploaded")
    assert fetch_unica_biweekly._exit_reason(0, 0, 2, 0).startswith("2 bulletin(s) failed")


# ---------------------------------------------------------------------------
# (a-iii) publication month beats the caller's loop year
# ---------------------------------------------------------------------------

class _FakeLocator:
    def __init__(self, attr: str | None):
        self._attr = attr

    @property
    def first(self):
        return self

    async def wait_for(self, **_kwargs):
        return None

    async def get_attribute(self, _name):
        return self._attr


class _FakePage:
    """Minimal duck-typed page: an iframe src and a download href."""

    def __init__(self, iframe_src: str, dl_href: str):
        self._iframe_src = iframe_src
        self._dl_href = dl_href

    def locator(self, selector: str):
        if "iframe" in selector:
            return _FakeLocator(self._iframe_src)
        return _FakeLocator(self._dl_href)


def test_publication_month_beats_loop_year():
    page = _FakePage(
        "https://unicadata.com.br/arquivos/pdfs/2026/04/x.pdf",
        "download_media.php?idM=32820684",
    )
    result = asyncio.run(fetch_unica_biweekly._extract_current_bulletin(page, "2025/2026"))
    assert result is not None
    assert result["idm"] == "32820684"
    assert result["published_ym"] == "2026/04"
    # The caller asked for 2025/2026; the evidence says otherwise and wins.
    assert result["harvest_year"] == "2026/2027"


def test_january_bulletin_closes_the_prior_season():
    page = _FakePage(
        "https://unicadata.com.br/arquivos/pdfs/2027/01/y.pdf",
        "download_media.php?idM=99999999",
    )
    result = asyncio.run(fetch_unica_biweekly._extract_current_bulletin(page, None))
    assert result["harvest_year"] == "2026/2027"


class TestEmptyShellGuard:
    """D-SG M-8: the portal's post-2020 'empty shell' (a <table>, 4 header rows, no
    data) passed the size+<table> bar and would have uploaded garbage weekly."""

    @staticmethod
    def _page(rows: int) -> bytes:
        body = b"<table>" + b"<tr><td>x</td></tr>" * rows + b"</table>"
        return body + b" " * 22000  # clears _MIN_HTML_BYTES like the real shells do

    def test_a_four_row_shell_is_refused(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("fu_t", "jobs/ingest/fetch_unica.py")
        fu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fu)
        with pytest.raises(RuntimeError, match="Empty table shell"):
            fu._assert_data_rows(self._page(4), "2026/2027")

    def test_a_real_page_row_count_passes(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("fu_t", "jobs/ingest/fetch_unica.py")
        fu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fu)
        fu._assert_data_rows(self._page(28), "2020/2021")  # the measured real shape
