"""THE FETCH RE-ORDER, PINNED (PINK SHEET VINTAGES lane (a), 2026-09-03).

The shipped order lost a vintage on the one day it was unrecoverable: ``--skip-existing-s3``
returned on the PAGE LABEL's key BEFORE the download, so on the exact incident the content key was
written for -- the page advertising month M-1 while the workbook already held month M -- the label
key already existed, the job returned, and the workbook was never fetched.  And the advance fence
also keyed on the label, above any download, so a correctly-advancing workbook behind a stale label
went hard-RED.  Two rules for one fact, and both lose the vintage.

Every property below is a claim the re-order makes about a LIVE SCHEDULE, so each one is driven
through ``main()`` with the network, the clock and S3 doubled -- never asserted about the source
text.

AWS-free, network-free.
"""
from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest
from leviathan.common import pink_sheet_release as R

MODULE = "jobs.ingest.fetch_world_bank_pink_sheet"
FILENAME = "CMO-Historical-Data-Monthly.xlsx"
XLS_URL = f"https://thedocs.worldbank.org/en/doc/abc-0050012026/related/{FILENAME}"


def _page_html(label_month: str, label_year: int) -> str:
    return (f'<html><body>'
            f'<a href="{XLS_URL}">workbook</a>'
            f'<a href="https://thedocs.worldbank.org/x/CMO-Pink-Sheet-{label_month}-'
            f'{label_year}.pdf">pdf</a>'
            f'</body></html>')


def _workbook(release: str) -> bytes:
    """A real xlsx whose LAST MONTHLY ROW derives *release*."""
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = R.SHEET_NAME
    sheet.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    sheet.append(["Updated as of: whatever"])
    sheet.append([None])
    sheet.append([None])
    sheet.append(["Month", "Soybean oil"])
    for i, month in enumerate(R.expected_months(release)):
        sheet.append([month, 900.0 + i])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


class _Resp:
    def __init__(self, *, text="", content=b"", headers=None):
        self.text = text
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None


class _Session:
    """The network double. Records every GET so 'did it download?' is a MEASURED answer."""

    def __init__(self, page_html: str, body: bytes, headers=None):
        self.headers = {}
        self._page = page_html
        self._body = body
        self._body_headers = headers or {"Last-Modified": "Tue, 02 Sep 2026 11:04:00 GMT",
                                         "Content-Length": str(len(body))}
        self.gets: list[str] = []

    def get(self, url, **_kw):
        self.gets.append(url)
        if url.endswith(".xlsx"):
            return _Resp(content=self._body, headers=self._body_headers)
        return _Resp(text=self._page)

    def downloads(self):
        return [u for u in self.gets if u.endswith(".xlsx")]


@pytest.fixture
def harness(monkeypatch):
    """Drives the module's ``main()`` with the network, S3 and env all doubled."""
    mod = __import__(MODULE, fromlist=["main"])

    state = {
        "uploaded": {},          # key -> bytes
        "meta": {},              # key -> extra dict
        "exists": set(),         # keys already "in S3"
        "sidecars": {},          # meta key -> record
    }

    def _run(*, label=("August", 2026), derives="2026M09", argv=None, headers=None,
             exists=(), sidecars=None, body=None):
        # `body` lets a test hand in the EXACT bytes it also hashed. openpyxl stamps
        # docProps/core.xml with a creation timestamp, so two builds of the same workbook seconds
        # apart differ by a few bytes -- a sha assertion against a separately-built workbook is
        # order-dependent and fails only when the suite is slow. Caught 2026-09-03.
        session = _Session(_page_html(*label), body if body is not None else _workbook(derives),
                           headers=headers)
        state["exists"] = set(exists)
        state["sidecars"] = dict(sidecars or {})
        monkeypatch.setattr(mod.requests, "Session", lambda: session)
        monkeypatch.setattr(mod, "load_env", lambda: None)
        monkeypatch.setattr(mod, "get_required_env",
                            lambda name: {"LEVIATHAN_BUCKET": "b", "AWS_REGION": "r"}[name])
        monkeypatch.setattr(mod, "s3_object_exists",
                            lambda bucket, key, region: key in state["exists"])

        def _upload(data, bucket, key, region):
            state["uploaded"][key] = data
            state["exists"].add(key)

        def _write_meta(bucket, key, data, url, ctype, region, extra=None):
            state["meta"][key] = dict(extra or {})

        def _sidecar(bucket, key, region):
            if key in state["sidecars"]:
                return state["sidecars"][key]
            raise RuntimeError("no sidecar")

        # The 500 KB MIN_RAW_FILE_SIZES floor is a REAL shipped guard and it stays real in
        # production; it is stubbed here only because a synthetic 800-row workbook is ~16 KB and
        # padding one to 500 KB would test the padding. Nothing in this file is about file size.
        monkeypatch.setattr(mod, "check_min_file_size", lambda *a, **k: None)
        monkeypatch.setattr(mod, "upload_bytes_to_s3", _upload)
        monkeypatch.setattr(mod, "write_raw_s3_metadata", _write_meta)
        monkeypatch.setattr(mod, "download_s3_json", _sidecar)
        monkeypatch.setattr(sys, "argv",
                            ["fetch_world_bank_pink_sheet.py"] + list(argv or []))
        mod.main()
        return session

    return SimpleNamespace(mod=mod, state=state, run=_run)


class TestTheStaleLabelIncident:
    """The whole point. Page says M-1, workbook holds M, the LABEL key already exists."""

    def test_it_downloads_despite_the_label_key_existing(self, harness):
        label_key = f"raw/production/source=world_bank_pink_sheet/release=2026M08/{FILENAME}"
        session = harness.run(label=("July", 2026), derives="2026M09",
                              argv=["--skip-existing-s3", "--asof", "2026-09-08"],
                              exists=[label_key])
        assert session.downloads(), (
            "the workbook was never fetched -- --skip-existing-s3 returned on the label key, "
            "which is the exact defect the re-order exists to close")

    def test_it_lands_under_the_DERIVED_month(self, harness):
        harness.run(label=("July", 2026), derives="2026M09",
                    argv=["--skip-existing-s3", "--asof", "2026-09-08"])
        keys = list(harness.state["uploaded"])
        assert keys == [
            f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"]

    def test_it_logs_the_divergence_and_does_NOT_raise(self, harness, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            harness.run(label=("July", 2026), derives="2026M09", argv=["--asof", "2026-09-08"])
        assert any("content-key divergence" in r.getMessage() for r in caplog.records)

    def test_both_keys_are_recorded_in_the_metadata_sidecar(self, harness):
        harness.run(label=("July", 2026), derives="2026M09", argv=["--asof", "2026-09-08"])
        extra = next(iter(harness.state["meta"].values()))
        assert extra["derived_release_ym"] == "2026M09"
        assert extra["page_label_release_ym"] == "2026M07"
        assert extra["expected_month_count"] == 800
        assert extra["observed_month_count"] == 800
        assert extra["is_full_restatement"] is True
        # THE ORIGIN CLOCK MUST BE RECORDED AT CAPTURE OR IT IS GONE FOREVER -- rung 1 of the
        # release-clock ladder has no other source, and these objects serve NO ETag.
        assert extra["http_last_modified"] == "Tue, 02 Sep 2026 11:04:00 GMT"
        assert extra["http_content_length"]


class TestTheAdvanceFenceMeasuresAdvance:
    def test_a_correctly_advancing_workbook_behind_a_stale_label_PASSES(self, harness):
        """The old fence keyed on the LABEL above the download, so this went hard-RED."""
        harness.run(label=("June", 2026), derives="2026M09", argv=["--asof", "2026-09-08"])
        assert harness.state["uploaded"]

    def test_a_genuinely_stale_workbook_still_REDS_and_names_the_label(self, harness):
        with pytest.raises(SystemExit) as excinfo:
            harness.run(label=("September", 2026), derives="2026M07",
                        argv=["--asof", "2026-09-08"])
        message = str(excinfo.value)
        assert "ZERO-ADVANCE" in message
        assert "2026M07" in message          # the DERIVED month is what is fenced
        assert "2026M09" in message          # and the label it disagreed with is named

    def test_a_FUTURE_derived_month_is_refused(self, harness):
        with pytest.raises(SystemExit, match="FUTURE RELEASE"):
            harness.run(label=("August", 2026), derives="2026M11",
                        argv=["--asof", "2026-09-08"])

    def test_no_advance_fence_disables_it(self, harness):
        harness.run(label=("September", 2026), derives="2026M07",
                    argv=["--asof", "2026-09-08", "--no-advance-fence"])
        assert list(harness.state["uploaded"]) == [
            f"raw/production/source=world_bank_pink_sheet/release=2026M07/{FILENAME}"]


class TestFirstCaptureWins:
    def test_the_same_bytes_under_the_derived_key_skip_the_upload_and_exit_0(self, harness):
        import hashlib
        body = _workbook("2026M09")
        key = f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"
        harness.run(label=("August", 2026), derives="2026M09", argv=["--asof", "2026-09-08"],
                    exists=[key], body=body,
                    sidecars={f"raw_meta/{key}_meta.json":
                              {"sha256": hashlib.sha256(body).hexdigest()}})
        assert harness.state["uploaded"] == {}, "raw is immutable -- it must not be overwritten"

    def test_DIFFERENT_bytes_under_the_derived_key_are_a_HARD_refusal(self, harness):
        key = f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"
        with pytest.raises(SystemExit, match="SAME-KEY CONTENT COLLISION"):
            harness.run(label=("August", 2026), derives="2026M09", argv=["--asof", "2026-09-08"],
                        exists=[key],
                        sidecars={f"raw_meta/{key}_meta.json": {"sha256": "deadbeef"}})
        assert harness.state["uploaded"] == {}

    def test_force_overwrite_is_the_escape_and_it_actually_writes(self, harness):
        key = f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"
        harness.run(label=("August", 2026), derives="2026M09",
                    argv=["--asof", "2026-09-08", "--force-overwrite"],
                    exists=[key],
                    sidecars={f"raw_meta/{key}_meta.json": {"sha256": "deadbeef"}})
        assert key in harness.state["uploaded"]

    def test_an_unreadable_sidecar_keeps_first_capture_wins_rather_than_overwriting(self, harness):
        """A missing sidecar cannot certify a collision either way, so it is an ABSENT answer and
        the held bytes stay. Overwriting on a guess is the one thing raw immutability forbids."""
        key = f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"
        harness.run(label=("August", 2026), derives="2026M09", argv=["--asof", "2026-09-08"],
                    exists=[key], sidecars={})
        assert harness.state["uploaded"] == {}

    def test_force_overwrite_REPAIRS_the_interrupted_first_capture(self, harness, caplog):
        """THE CASE THE FLAG EXISTED FOR AND COULD NOT REACH.

        write_raw_s3_metadata runs AFTER the upload and never re-raises, so an interrupted first
        capture leaves an object with NO readable sidecar -- exactly the shape the flag's own help
        text names ('a truncated or wrong-month first capture'). With the overwrite branch nested
        inside `if held_sha and held_sha != new_sha`, `_held_sha256` returning None fell through to
        the 'already held' return and the owner's explicit --force-overwrite was ignored in
        silence. The flag is now answered BEFORE the comparison."""
        key = f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"
        with caplog.at_level("WARNING"):
            harness.run(label=("August", 2026), derives="2026M09",
                        argv=["--asof", "2026-09-08", "--force-overwrite"],
                        exists=[key], sidecars={})          # NO sidecar at all
        assert key in harness.state["uploaded"], (
            "--force-overwrite must write when the sidecar cannot be read -- that is the "
            "interrupted-capture shape it exists to repair")
        assert any("UNRECORDED" in r.getMessage() for r in caplog.records), (
            "the overwrite must SAY that no held sha was readable, not imply one was compared")
        # and the sidecar is rewritten, so the repaired object is no longer clock-less
        assert harness.state["meta"][key]["derived_release_ym"] == "2026M09"

    def test_force_overwrite_still_writes_when_the_sidecar_MATCHES(self, harness):
        """An identical-bytes capture is normally a no-op. Under the owner's flag it still writes:
        the flag means 'replace this object', and second-guessing it would reintroduce the silence
        this fix removed."""
        import hashlib
        body = _workbook("2026M09")
        key = f"raw/production/source=world_bank_pink_sheet/release=2026M09/{FILENAME}"
        harness.run(label=("August", 2026), derives="2026M09",
                    argv=["--asof", "2026-09-08", "--force-overwrite"],
                    exists=[key], body=body,
                    sidecars={f"raw_meta/{key}_meta.json":
                              {"sha256": hashlib.sha256(body).hexdigest()}})
        assert key in harness.state["uploaded"]


class TestTheCliHelpDescribesTheReorderedFETCH:
    """The module docstring was updated by the re-order; the argparse help was not -- and the help
    is what an operator reads at the console before running a live ingest."""

    @staticmethod
    def _help(mod, flag):
        import argparse
        import contextlib
        import io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
            with contextlib.suppress(argparse.ArgumentError):
                sys.argv = ["fetch_world_bank_pink_sheet.py", "--help"]
                mod.main()
        text = " ".join(buf.getvalue().split())
        assert flag in text, flag
        return text

    def test_release_month_no_longer_claims_to_key_the_object(self, harness):
        text = self._help(harness.mod, "--release-month")
        assert "S3 key partition" not in text, (
            "the label keys nothing after the re-order; the object is keyed on the DERIVED month")
        assert "KEYS NOTHING" in text

    def test_release_month_names_the_REAL_recovery_path_for_a_hole(self, harness):
        """It was the documented lever for recovering the declared 2026M06 hole and it cannot do
        that. An operator who reads this must be sent to the leg that can."""
        text = self._help(harness.mod, "--release-month")
        assert "backfill_pink_sheet_vintages.py" in text
        assert "2026M06" in text

    def test_dry_run_no_longer_promises_an_S3_key(self, harness):
        text = self._help(harness.mod, "--dry-run")
        assert "print the S3 key" not in text.lower()
        assert "CANNOT print the S3 key" in text

    def test_force_overwrite_help_names_the_sidecar_case_it_now_repairs(self, harness):
        text = self._help(harness.mod, "--force-overwrite")
        assert "BEFORE the sha compare" in text


class TestMagicBytesAndDryRun:
    def test_a_non_workbook_body_is_refused_by_KIND_before_anything_parses_it(self, harness,
                                                                              monkeypatch):
        mod = harness.mod
        session = _Session(_page_html("August", 2026), b"<!DOCTYPE html><html>nope</html>")
        monkeypatch.setattr(mod.requests, "Session", lambda: session)
        monkeypatch.setattr(mod, "load_env", lambda: None)
        monkeypatch.setattr(mod, "get_required_env",
                            lambda n: {"LEVIATHAN_BUCKET": "b", "AWS_REGION": "r"}[n])
        monkeypatch.setattr(mod, "s3_object_exists", lambda *a, **k: False)
        monkeypatch.setattr(sys, "argv", ["x", "--asof", "2026-09-08"])
        with pytest.raises(SystemExit, match="NOT A WORKBOOK"):
            mod.main()

    def test_a_legacy_ole2_body_is_named_as_a_FORMAT_problem_not_a_broken_response(
            self, harness, monkeypatch):
        mod = harness.mod
        session = _Session(_page_html("August", 2026),
                           b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 4096)
        monkeypatch.setattr(mod.requests, "Session", lambda: session)
        monkeypatch.setattr(mod, "load_env", lambda: None)
        monkeypatch.setattr(mod, "get_required_env",
                            lambda n: {"LEVIATHAN_BUCKET": "b", "AWS_REGION": "r"}[n])
        monkeypatch.setattr(mod, "s3_object_exists", lambda *a, **k: False)
        monkeypatch.setattr(sys, "argv", ["x", "--asof", "2026-09-08"])
        with pytest.raises(SystemExit) as excinfo:
            mod.main()
        assert "legacy .xls" in str(excinfo.value)

    def test_dry_run_performs_NO_download_and_prints_no_s3_key(self, harness, capsys):
        session = harness.run(label=("August", 2026), derives="2026M09", argv=["--dry-run"])
        assert session.downloads() == []
        out = capsys.readouterr().out
        assert "Page label : 2026M08" in out
        assert "raw/production/source=world_bank_pink_sheet/release=" not in out
        assert "--dry-run does not download" in out
        assert harness.state["uploaded"] == {}


class TestNotAFullRestatement:
    def test_a_holed_workbook_still_LANDS_but_is_counted_and_warned(self, harness, monkeypatch,
                                                                   caplog):
        """Raw is the ASSET. A hole makes the release unusable as a VINTAGE -- and the vintage
        builder's own gate is where that is refused -- but the bytes are still the latest-only
        chain's input, so they land, loudly."""
        import logging
        mod = harness.mod
        real = mod.monthly_rows
        monkeypatch.setattr(mod, "monthly_rows",
                            lambda b: [m for m in real(b) if m != "1971M04"])
        with caplog.at_level(logging.WARNING):
            harness.run(label=("August", 2026), derives="2026M09", argv=["--asof", "2026-09-08"])
        assert harness.state["uploaded"], "a holed release must still land as raw"
        assert any("NOT A FULL RESTATEMENT" in r.getMessage() for r in caplog.records)
        extra = next(iter(harness.state["meta"].values()))
        assert extra["is_full_restatement"] is False
        assert extra["observed_month_count"] == 799
        assert extra["expected_month_count"] == 800
