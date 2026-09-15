"""USDA WAP FETCH RCA (2026-09-15): the manifest-only freeze, and the skip that never skipped.

No deck existed for this entrypoint. Two measured defects and one missing instrument are pinned
here, each in BOTH directions, because the standing law is that a fence added one check at a time
takes five rounds:

F1  THE FREEZE. The scheduled fetch iterated ``configs/sources/usda_wap_manifest.yaml`` and nothing
    else. The manifest was last rebuilt 2026-07-17, so its newest entry was 2026-07; the August
    circular (published 2026-08-12) and the September one (2026-09-11) were never enumerated on any
    fire. Canonical ``silver/wap_table01_revisions`` sat at max ``release_month`` 2026-07, last
    written 2026-08-14 18:28Z -- 42 days -- and every instrument in the estate read it as healthy:
    the freshness alarm measures S3 object mtime and the silver task rewrites its shadow on every
    fire, the gate's data-freshness stage is dark and ``year_month``-keyed while this card is
    ``vintage``, and the fetch job itself reported ``errors=0``, truthfully. The remedy is an
    incremental tail (HEAD-probe the months after the manifest's newest entry) PLUS a staleness
    tripwire, because a tail alone would have closed this instance and left the class open.

F2  THE RE-UPLOAD. Every fire reported ``uploaded=287 skipped=0`` -- 1,051,731,539 bytes pulled from
    fas.usda.gov to rewrite objects that were already there -- although ``--skip-existing-s3`` was on
    the jobdef's default command. The deployed submission replaces the command array wholesale with
    ``['jobs/ingest/fetch_usda_wap.py']``, so the flag never reached argparse. The jobdef is
    terraform's and the DAG that overrides it belongs to another lane, so the CODE DEFAULT is the
    only lever, which is what ``argparse.BooleanOptionalAction`` + ``default=True`` buys.

AWS-free and network-free throughout: ``_head`` / ``_probe_tail`` / ``_fetch`` / ``s3_object_exists``
/ ``upload_bytes_to_s3`` / ``write_raw_s3_metadata`` / ``load_env`` are all monkeypatched, and every
drive passes ``--sleep-seconds 0``.
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest
import yaml

from jobs.ingest import fetch_usda_wap as mod

_REPO = Path(__file__).resolve().parents[2]

# The two months the freeze hid, and the sizes their CDN objects HEAD at (measured 2026-09-15).
_AUG = "2026-08"
_SEP = "2026-09"


# ---------------------------------------------------------------------------
# A hermetic run harness: one fake manifest, one fake S3, one fake CDN.
# ---------------------------------------------------------------------------

class _Run:
    """Records every S3 key the run HEADs and every key it WRITES, plus the URLs it fetched."""

    def __init__(self):
        self.head_keys: list[str] = []
        self.write_keys: list[str] = []
        self.fetched: list[str] = []
        self.probed: list[str] = []
        self.manifest_writes = 0


def _drive(monkeypatch, argv, manifest, *, probe=None, present=(), body=b"%PDF-1.7 " + b"x" * 4096,
           fetch_raises=None, record=None):
    """Run ``main()`` over a fake manifest / CDN / S3. Returns the :class:`_Run` record.

    ``probe`` maps a release month to one of the module's three outcome constants; a month with no
    entry is DECLINED (the CDN's honest answer for a month USDA has not published).
    ``present`` is the set of S3 keys that already exist.
    ``record`` lets a caller own the record BEFORE the run, which is how a drive that is expected to
    exit non-zero can still assert on what did and did not reach S3 before the exit -- an exit code
    without that half would leave 'wrote nothing' unproven.
    """
    run = record if record is not None else _Run()
    probe = probe or {}
    present = set(present)

    monkeypatch.setattr(mod, "_load_manifest", lambda: [dict(e) for e in manifest])

    def _fake_probe(ym, sleep_seconds=0.0):
        run.probed.append(ym)
        return probe.get(ym, mod._TAIL_DECLINED), mod._cdn_tail_url(ym)

    monkeypatch.setattr(mod, "_probe_tail", _fake_probe)

    def _fake_exists(bucket, key, region):
        run.head_keys.append(key)
        return key in present

    def _fake_upload(data, bucket, key, region):
        run.write_keys.append(key)
        present.add(key)

    def _fake_fetch(url, timeout=None, stream=False):
        run.fetched.append(url)
        if fetch_raises is not None:
            raise fetch_raises
        return _Resp(body)

    monkeypatch.setattr(mod, "s3_object_exists", _fake_exists)
    monkeypatch.setattr(mod, "upload_bytes_to_s3", _fake_upload)
    monkeypatch.setattr(mod, "write_raw_s3_metadata",
                        lambda *a, **k: None)
    monkeypatch.setattr(mod, "_fetch", _fake_fetch)
    monkeypatch.setattr(mod, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(mod, "get_required_env",
                        lambda name: {"LEVIATHAN_BUCKET": "fake-bucket",
                                      "AWS_REGION": "us-east-1"}[name])

    _guard_manifest_writes(monkeypatch, run)
    monkeypatch.setattr("sys.argv", ["fetch_usda_wap.py", "--sleep-seconds", "0", *argv])
    mod.main()
    return run


def _guard_manifest_writes(monkeypatch, run):
    """a1+: the manifest is a TRACKED file baked into the worker image. If the run path ever opened
    it for WRITE the fix would appear to work once and then silently stop, because a container write
    is lost on exit. Count -- and swallow -- any attempt."""
    real_open = Path.open

    def _guarded_open(self, *a, **k):
        mode = str(a[0]) if a else str(k.get("mode", ""))
        if self == mod._MANIFEST_PATH and "w" in mode:
            run.manifest_writes += 1
            return io.StringIO()
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", _guarded_open)


class _Resp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


def _entry(ym):
    return {"release_month": ym, "url": f"https://www.fas.usda.gov/sites/default/files/{ym}/production.pdf"}


def _today(monkeypatch, ym):
    """Freeze the wall-clock month the run reads.

    ONE patch point, because the module reads the clock ONCE, in UTC, through ``_today_ym``. It
    used to call ``date.today()`` inline -- local time, which on the owner's UTC+3 laptop reads the
    NEXT month between 21:00Z and midnight on the last day of a month.
    """
    monkeypatch.setattr(mod, "_today_ym", lambda: ym)


# ---------------------------------------------------------------------------
# (a2+) The tail's boundaries -- pure month arithmetic, no network at all
# ---------------------------------------------------------------------------

def test_tail_months_starts_after_the_manifest_and_stops_at_the_current_month():
    # The measured case: manifest max 2026-07, wall clock 2026-09 -> exactly the two lost circulars.
    assert mod._tail_months("2026-07", "2026-09") == ["2026-08", "2026-09"]
    # ...and on a 2026-10-12 fire, October joins them.
    assert mod._tail_months("2026-07", "2026-10") == ["2026-08", "2026-09", "2026-10"]
    # Strictly AFTER: a manifest that is already current probes NOTHING, so the steady state costs
    # zero HTTP requests rather than one wasted 404 a month.
    assert mod._tail_months("2026-09", "2026-09") == []
    # ...and never walks FORWARD past the current month into an unbounded run of 404s.
    assert mod._tail_months("2026-11", "2026-09") == []
    # Year boundaries are arithmetic, not string ordering.
    assert mod._tail_months("2026-11", "2027-01") == ["2026-12", "2027-01"]


def test_tail_months_is_hard_capped_at_the_newest_months_of_a_long_gap():
    """An image whose baked-in manifest has gone stale by years must not turn one fire into an
    unbounded probe walk. The cap keeps the NEWEST months, because currency is what the instrument
    exists for; the caller WARNs about the older half rather than leaving it to be inferred."""
    months = mod._tail_months("2020-01", "2026-09")
    assert len(months) == mod._TAIL_MAX_MONTHS == 6
    assert months == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


def test_ym_helpers_round_trip():
    for ym in ("2002-08", "2026-01", "2026-12", "2027-01"):
        assert mod._int_to_ym(mod._ym_to_int(ym)) == ym
    assert mod._ym_behind("2026-07", "2026-09") == 2
    assert mod._ym_behind("2026-10", "2026-09") == -1


# ---------------------------------------------------------------------------
# (a7+, a8-) The staleness tripwire predicate -- the instrument nothing else in the estate carries
# ---------------------------------------------------------------------------

def test_tail_is_frozen_truth_table():
    # ONE month behind is NORMAL and must never trip: the circular for month M lands on the 8th-12th
    # of M, and this chain fires at 18:00Z on days 12-14.
    assert mod._tail_is_frozen("2026-09", "2026-09") is False
    assert mod._tail_is_frozen("2026-09", "2026-10") is False
    # TWO or more is a freeze.
    assert mod._tail_is_frozen("2026-08", "2026-10") is True
    # The state MEASURED 2026-09-15, before this fix: newest reachable 2026-07, wall clock 2026-09.
    assert mod._tail_is_frozen("2026-07", "2026-09") is True
    # Nothing reachable at all is a freeze by definition, not a pass.
    assert mod._tail_is_frozen(None, "2026-09") is True
    assert mod._TAIL_FREEZE_MONTHS == 2


# ---------------------------------------------------------------------------
# (a4+, a5-, a6-) found / declined / unreachable -- and why the last two can never collapse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    (200, mod._TAIL_FOUND),
    (404, mod._TAIL_DECLINED),
    (410, mod._TAIL_DECLINED),
    (403, mod._TAIL_UNREACHABLE),      # Akamai refuses the client -- we could not ASK
    (500, mod._TAIL_UNREACHABLE),
    (503, mod._TAIL_UNREACHABLE),
])
def test_probe_tail_classifies_the_three_outcomes(monkeypatch, status, expected):
    monkeypatch.setattr(mod, "_head", lambda url, timeout=None: _Head(status))
    outcome, url = mod._probe_tail(_AUG)
    assert outcome == expected
    assert url == f"https://www.fas.usda.gov/sites/default/files/{_AUG}/production.pdf"


def test_a_transport_failure_is_unreachable_and_never_declined(monkeypatch, caplog):
    """THE LINE THIS DECK EXISTS FOR. 'The source said no' and 'we could not ask' are different
    facts. Reading the second as the first is how an FAS outage would trip the staleness tripwire
    and fail a whole chain over data that is perfectly fine."""
    def _boom(url, timeout=None):
        raise ConnectionError("dns")

    monkeypatch.setattr(mod, "_head", _boom)
    with caplog.at_level("INFO"):
        outcome, _ = mod._probe_tail(_AUG)
    assert outcome == mod._TAIL_UNREACHABLE
    assert "UNREACHABLE" in caplog.text and "ConnectionError" in caplog.text


def test_a_declined_month_is_named_with_the_url_that_was_tried(monkeypatch, caplog):
    """(a6-) The CDN folder is the UPLOAD month, not the release month; they did NOT coincide for
    2025-10 / 2025-11. Through a future reorganisation this probe 404s, so the decline must carry the
    URL it tried -- that is what puts the operator's next step (a --discover manifest refresh from a
    host FAS admits) in the log instead of in someone's head."""
    monkeypatch.setattr(mod, "_head", lambda url, timeout=None: _Head(404))
    with caplog.at_level("INFO"):
        mod._probe_tail("2026-10")
    assert "declined" in caplog.text
    assert "https://www.fas.usda.gov/sites/default/files/2026-10/production.pdf" in caplog.text


class _Head:
    def __init__(self, status):
        self.status_code = status


# ---------------------------------------------------------------------------
# (a1+, a3+) The tail rides the normal path, and never writes the manifest
# ---------------------------------------------------------------------------

def test_the_tail_fetches_the_lost_circulars_and_never_writes_the_manifest(monkeypatch, caplog):
    _today(monkeypatch, "2026-09")
    manifest = [_entry("2026-06"), _entry("2026-07")]
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, [], manifest,
                     probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND},
                     present={mod.raw_wap_key("2026-06"), mod.raw_wap_key("2026-07")})
    # The two manifest months skip (already in S3); the two tail months are downloaded and written.
    assert run.write_keys == [mod.raw_wap_key(_AUG), mod.raw_wap_key(_SEP)]
    assert "uploaded=2  skipped=2  errors=0" in caplog.text
    # a1+: the manifest file was NEVER opened for write on the run path.
    assert run.manifest_writes == 0
    # a3+: a tail entry has EXACTLY the manifest entry's shape, so it goes through the same
    # _upload_entry and there is no second place for the S3 key to be computed.
    assert run.fetched[-2:] == [mod._cdn_tail_url(_AUG), mod._cdn_tail_url(_SEP)]


def test_the_manifest_write_guard_itself_is_not_vacuous(monkeypatch):
    """The other direction of a1+, because a counter that is always zero proves nothing: the SAME
    guard, driven by a deliberate ``_save_manifest`` call, registers the write. ``--discover`` is
    still allowed to rebuild the file -- it is the run path, and only the run path, that must not."""
    run = _Run()
    _guard_manifest_writes(monkeypatch, run)
    mod._save_manifest([_entry("2026-08")])
    assert run.manifest_writes == 1


def test_a_declined_tail_month_is_not_an_error_and_is_named_in_the_summary(monkeypatch, caplog):
    """(a4+) USDA has not published on day 12 of a slipped month. A hard error there would stop
    bronze, silver, the gate and the promote for data that is fine."""
    _today(monkeypatch, "2026-10")
    manifest = [_entry("2026-07")]
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, [], manifest,
                     probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND,
                            "2026-10": mod._TAIL_DECLINED})
    assert run.write_keys == [mod.raw_wap_key("2026-07"), mod.raw_wap_key(_AUG),
                              mod.raw_wap_key(_SEP)]
    assert "errors=0" in caplog.text
    assert "declined=['2026-10']" in caplog.text
    assert "unreachable=[]" in caplog.text


def test_an_outage_on_one_fire_never_trips_and_the_manifest_still_runs(monkeypatch, caplog):
    """(a5-) THE FAIL-OPEN, RELOCATED. The whole manifest must still fetch during an FAS outage, and
    a single fire's outage must NOT exit non-zero.

    It no longer works by DISARMING the tripwire on any unreachable probe -- see the test below for
    the five-month freeze that rule made invisible. It works because the tripwire reads the newest
    month IN S3 against a threshold of two: a current table plus one unreachable fire is one month
    behind, which never trips. That is the same protection, granular."""
    _today(monkeypatch, "2026-10")
    manifest = [_entry("2026-08"), _entry(_SEP)]
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, [], manifest, probe={"2026-10": mod._TAIL_UNREACHABLE})
    assert "Tripwire: PASS" in caplog.text
    assert "unreachable=['2026-10']" in caplog.text
    # ...and every manifest month still ran to completion.
    assert run.write_keys == [mod.raw_wap_key("2026-08"), mod.raw_wap_key(_SEP)]


def test_one_unreachable_month_can_no_longer_hide_a_real_freeze(monkeypatch, caplog):
    """(REVIEW MINOR, driven) The rule this replaces disarmed the WHOLE tripwire whenever any ONE
    probe came back unreachable, even with four definitive declines in the same run: manifest max
    2026-07, wall clock 2026-12, 2026-08 unreachable and 2026-09..2026-12 cleanly declined logged
    'Tripwire DISARMED' and exited 0 on a five-month freeze.

    The doctrine behind that disarm is right about the SOURCE and this instrument does not measure
    the source -- it measures whether OUR PREFIX IS ADVANCING, which is equally untrue whether USDA
    stopped publishing or Akamai stopped answering. So the unreachable month is still classified,
    still logged, and NAMED in the exit message, and it no longer buys silence."""
    _today(monkeypatch, "2026-12")
    manifest = [_entry("2026-07")]
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, [], manifest, probe={_AUG: mod._TAIL_UNREACHABLE})
    msg = str(exc.value)
    assert msg.startswith("STALE-SOURCE")
    assert "2026-07" in msg and "2026-12" in msg
    # The two lists stay SEPARATE in the message, so the operator can tell which it is looking at.
    assert "could not ASK about ['2026-08']" in msg
    assert "declined ['2026-09', '2026-10', '2026-11', '2026-12']" in msg
    assert "Tripwire DISARMED" not in caplog.text


def test_an_all_unreachable_cdn_reorganisation_still_trips_once_the_table_is_stale(monkeypatch):
    """The NAMED RESIDUAL of the old rule, closed. FAS already answers 403 -- not 404 -- to this
    estate on /data/search, so a CDN reorganisation that 403s the production.pdf path made EVERY
    probe unreachable and disarmed the tripwire PERMANENTLY, with nothing but a logger.warning and
    nothing in the estate reading warnings. Now the first fire passes (one behind) and the second
    trips, which is exactly the granularity an outage deserves."""
    _today(monkeypatch, "2026-10")
    allbad = {m: mod._TAIL_UNREACHABLE for m in ("2026-08", _SEP, "2026-10", "2026-11")}
    _drive(monkeypatch, [], [_entry(_SEP)], probe=allbad)            # one behind: clean exit
    _today(monkeypatch, "2026-11")
    with pytest.raises(SystemExit) as exc:
        _drive(monkeypatch, [], [_entry(_SEP)], probe=allbad)        # two behind: trips
    assert str(exc.value).startswith("STALE-SOURCE")


# ---------------------------------------------------------------------------
# The tripwire ARMED -- the instrument that would have made the 42-day freeze visible
# ---------------------------------------------------------------------------

def test_a_frozen_source_writes_everything_then_exits_non_zero(monkeypatch, caplog):
    """The measured pre-fix state, replayed: manifest max 2026-07, wall clock 2026-09, the CDN
    declining both months (a reorganisation, not an outage). Everything fetchable is written FIRST
    -- the run refuses to report success, it does not refuse to work."""
    _today(monkeypatch, "2026-09")
    manifest = [_entry("2026-06"), _entry("2026-07")]
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, [], manifest,
                   probe={_AUG: mod._TAIL_DECLINED, _SEP: mod._TAIL_DECLINED})
    assert "STALE-SOURCE" in str(exc.value)
    assert "2026-07" in str(exc.value) and "2026-09" in str(exc.value)
    # The uploads happened BEFORE the exit -- the summary line is already in the log.
    assert "uploaded=2  skipped=0  errors=0" in caplog.text


def test_the_tripwire_passes_one_month_behind_on_a_day_12_fire(monkeypatch, caplog):
    """(a8-) A circular landing on the 13th must not fail the 12th's fire."""
    _today(monkeypatch, "2026-10")
    manifest = [_entry("2026-08"), _entry(_SEP)]
    with caplog.at_level("INFO"):
        _drive(monkeypatch, [], manifest, probe={"2026-10": mod._TAIL_DECLINED})
    assert "Tripwire: PASS" in caplog.text


@pytest.mark.parametrize("flag,word", [("--no-tail", "--no-tail"),
                                       ("--no-tail-tripwire", "--no-tail-tripwire")])
def test_the_tripwire_can_be_disarmed_deliberately(monkeypatch, caplog, flag, word):
    """Both disarms say WHICH one fired. A dark instrument nobody can see the state of is how the
    gate's own data-freshness stage went unnoticed for months."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        _drive(monkeypatch, [flag], [_entry("2026-07")])
    assert "Tripwire: disarmed by " + word in caplog.text


def test_no_tail_issues_zero_probes(monkeypatch, caplog):
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--no-tail"], [_entry("2026-07")])
    assert run.probed == []
    assert "Tail: disarmed (--no-tail)" in caplog.text


def test_a_current_manifest_issues_zero_probes(monkeypatch, caplog):
    """The steady state costs nothing: with the manifest already carrying the current month there is
    no month strictly after it, so the tail makes no HTTP request at all."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, [], [_entry(_SEP)])
    assert run.probed == []
    assert "nothing to probe" in caplog.text


# ---------------------------------------------------------------------------
# REVIEW MAJOR (driven): the tripwire was BLIND TO THE WRITE
#
# The first version computed its verdict BEFORE the upload loop, from the HEAD probe. A tail month
# that was FOUND and then failed to download still counted as progress: 'Tripwire: PASS', exit 0,
# raw prefix frozen -- the same failure this instrument exists to close, through a different door,
# and PERMANENT, because the next month it counted two such months as progress. The verdict now
# reads the LANDED set, and any error at all is non-zero before the verdict is even computed.
# ---------------------------------------------------------------------------

def test_a_found_but_unwritable_tail_month_can_never_report_pass(monkeypatch, caplog):
    """The reviewer's drive, verbatim, in the shape production actually has: manifest max 2026-09
    ALREADY IN S3 (287 of 289 keys are, measured 2026-09-15), wall clock 2026-10, 2026-10 FOUND,
    the fetch raises. Before: errors=1 AND 'Tripwire: PASS' in the same log, and exit 0 -- the
    newest month in S3 stuck at 2026-09 while the instrument asserted health.

    Both halves are pinned: the exit code, AND that the 2026-10 key never reached S3."""
    _today(monkeypatch, "2026-10")
    run = _Run()
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, [], [_entry(_SEP)], record=run,
                   present=[mod.raw_wap_key(_SEP)], probe={"2026-10": mod._TAIL_FOUND},
                   fetch_raises=RuntimeError("connection reset"))
    msg = str(exc.value)
    assert msg.startswith("FETCH-FAILED")
    assert "1 of 2 release month(s) could not be written: ['2026-10']" in msg
    assert "tail months among them: ['2026-10']" in msg
    assert "landed in raw S3 is 2026-09" in msg
    assert "Tripwire: PASS" not in caplog.text
    assert "errors=1" in caplog.text, "the count is still REPORTED; it is no longer ignored"
    assert run.write_keys == [], "nothing landed, and the exit code now says so"
    # The defect in one line: the OLD input was max(manifest_max, found) = 2026-10, which the
    # predicate calls healthy. Reading the probe instead of the write is the whole bug, and this
    # assertion keeps the test from going vacuous if someone re-derives the input from the tail.
    assert mod._tail_is_frozen("2026-10", "2026-10") is False


def test_every_download_failing_is_never_a_clean_exit(monkeypatch, caplog):
    """The reviewer's second drive: every manifest month's download raising -> errors=2, zero
    writes, 'Tripwire: PASS', exit 0. Two independent fences now catch it -- the error count, and a
    landed set that is EMPTY, which _tail_is_frozen has always called a freeze by definition."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, [], [_entry("2026-08"), _entry(_SEP)],
                   fetch_raises=RuntimeError("connection reset"))
    assert str(exc.value).startswith("FETCH-FAILED")
    assert "2 of 2 release month(s)" in str(exc.value)
    assert mod._tail_is_frozen(None, "2026-09") is True


def test_the_permanent_form_is_closed_too(monkeypatch):
    """THE REASON THIS WAS A MAJOR AND NOT A SLIP. Under the old rule the next month HEADed both
    2026-10 and 2026-11, both 200, both failed, and the verdict ADVANCED to 2026-11 -- the
    instrument actively asserting health while the table froze, for as many months as you like.
    Driven at the month AFTER the first failure: still non-zero, and the newest month it reports as
    written is still 2026-09."""
    _today(monkeypatch, "2026-11")
    with pytest.raises(SystemExit) as exc:
        _drive(monkeypatch, [], [_entry(_SEP)], present=[mod.raw_wap_key(_SEP)],
               probe={"2026-10": mod._TAIL_FOUND, "2026-11": mod._TAIL_FOUND},
               fetch_raises=RuntimeError("connection reset"))
    msg = str(exc.value)
    assert msg.startswith("FETCH-FAILED")
    assert "['2026-10', '2026-11']" in msg
    assert "landed in raw S3 is 2026-09" in msg


def test_an_already_present_month_counts_as_landed(monkeypatch, caplog):
    """The boundary between the two halves of 'landed'. A month the existence check finds in S3 was
    not written by THIS run and is still present at the end of it, so it counts -- otherwise the
    steady state (287 skips, nothing to upload) would trip the tripwire on every fire."""
    _today(monkeypatch, "2026-09")
    present = [mod.raw_wap_key("2026-08"), mod.raw_wap_key(_SEP)]
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, [], [_entry("2026-08"), _entry(_SEP)], present=present)
    assert run.write_keys == [] and run.fetched == []
    assert "newest written=2026-09" in caplog.text
    assert "Tripwire: PASS" in caplog.text


def test_tail_verdict_truth_table():
    """THE WHOLE RULE IN ONE PLACE, which is the point of it being one pure function. The threat
    model is enumerated here rather than discovered one round at a time."""
    V = mod._tail_verdict
    base = dict(armed=True, scope_narrowed=False, today_ym="2026-11", unlanded_found=[])
    # Current, and one behind on a day-12 fire: PASS.
    assert V(**{**base, "newest_written": "2026-11"}) == mod._V_PASS
    assert V(**{**base, "newest_written": "2026-10"}) == mod._V_PASS
    # Two behind, nothing narrowed: the freeze.
    assert V(**{**base, "newest_written": "2026-09"}) == mod._V_STALE
    assert V(**{**base, "newest_written": None}) == mod._V_STALE
    # The same facts under a hand run that asked a smaller question: reported, not acted on.
    assert V(**{**base, "newest_written": "2026-09", "scope_narrowed": True}) == mod._V_REPORT_ONLY
    # A found month that did not land BEATS a fresh-looking landed set -- this is the MAJOR.
    assert V(**{**base, "newest_written": "2026-11",
               "unlanded_found": ["2026-11"]}) == mod._V_UNLANDED
    # ...and scope_narrowed does not soften it: refusing a published month is not a smaller
    # question, it is a freeze with a flag on it.
    assert V(**{**base, "newest_written": "2026-11", "scope_narrowed": True,
               "unlanded_found": ["2026-11"]}) == mod._V_UNLANDED
    # The operator's word disarms everything, and is the ONLY thing that does.
    for extra in ({}, {"unlanded_found": ["2026-11"]}, {"newest_written": None}):
        assert V(**{**base, "newest_written": "2026-09", "armed": False, **extra}) \
            == mod._V_DISARMED
    # Five verdicts, all distinct strings: a caller can never confuse two.
    assert len({mod._V_PASS, mod._V_STALE, mod._V_UNLANDED, mod._V_REPORT_ONLY,
                mod._V_DISARMED}) == 5


def test_the_clock_is_read_in_utc_exactly_once(monkeypatch):
    """REVIEW MINOR. ``date.today()`` read LOCAL time: on the owner's UTC+3 laptop a run between
    21:00Z and midnight on the last day of a month read the NEXT month -- one guaranteed-404 probe
    and the tripwire's reference shifted by one. Batch runs UTC and the 18:00Z day-12-14 schedule
    never sits near the boundary, so this was hygiene; the class is gone either way."""
    import datetime as _dt
    import inspect

    # The name is GONE from the module, which is stronger than grepping for a call: nothing can
    # reach `date.today` here even by accident.
    assert not hasattr(mod, "date"), "the local-time clock must not be importable in this module"
    assert "datetime.now(timezone.utc)" in inspect.getsource(mod._today_ym)
    # 23:30 on the last day of a month, UTC+3: local says the next month, UTC says this one.
    local = _dt.datetime(2026, 9, 30, 23, 30, tzinfo=_dt.timezone(_dt.timedelta(hours=3)))
    assert local.strftime("%Y-%m") == "2026-09"
    assert local.astimezone(_dt.timezone.utc).strftime("%Y-%m") == "2026-09"
    assert mod._today_ym() == _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# (a11-) A filter that drops a tail month must SAY so
# ---------------------------------------------------------------------------

def test_year_to_drops_a_tail_month_loudly_and_exits_non_zero(monkeypatch, caplog):
    """``--year-to 2026`` is a latent 2027 cliff sitting in the jobdef's DEFAULT command, dormant
    only because the deployed override drops it. If anyone 'fixes' the DAG to stop overriding, the
    tail must die with an ALARM, not with a warning: a logger.warning nobody reads is precisely the
    class of instrument that let the 42-day freeze run. A month the CDN is SERVING that this run
    refused to fetch freezes the prefix exactly as a month that was never enumerated does."""
    _today(monkeypatch, "2027-01")
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, ["--year-to", "2026"], [_entry("2026-12")],
                   probe={"2027-01": mod._TAIL_FOUND})
    assert "dropped by --year-to 2026" in caplog.text        # the sentence, still there
    assert str(exc.value).startswith("UNLANDED-TAIL")        # ...and now an exit code with it
    assert "['2027-01']" in str(exc.value)
    assert "--year-to 2026" in str(exc.value)
    assert "--no-tail" in str(exc.value), "the message must name the deliberate form"


def test_a_scoped_backfill_that_keeps_the_tail_month_is_a_clean_exit(monkeypatch, caplog):
    """The other direction: --year-from narrows the scope but does NOT refuse the published month,
    so it lands, and the run is clean. A filter is only a problem when it drops the tail."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--year-from", "2026"],
                     [_entry("2025-12"), _entry("2026-07")], probe={_AUG: mod._TAIL_FOUND})
    assert mod.raw_wap_key(_AUG) in run.write_keys
    assert mod.raw_wap_key("2025-12") not in run.write_keys
    assert "Tripwire: PASS" in caplog.text


def test_an_empty_manifest_is_a_broken_image_and_exits_non_zero(monkeypatch, caplog):
    """The manifest YAML is baked into the worker image at build time. If it loads zero entries the
    run has nothing to fetch AND no newest entry to probe forward from -- and the old code exited 0,
    which is the same silence as the freeze itself: nothing written, nothing said, chain green."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, [], [])
    assert "loaded ZERO entries" in str(exc.value)
    assert "Tail: the manifest is empty" in caplog.text


def test_a_deliberately_narrow_hand_run_is_still_a_clean_exit(monkeypatch, caplog):
    """The other direction, and the reason the check above keys on the MANIFEST rather than on the
    filtered list: a hand run that scopes itself out of every entry wrote nothing on purpose. The
    DELIBERATE form says so with --no-tail, and that form has to stay a clean exit or the fence has
    made the tool unusable by hand."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--year-from", "2030", "--no-tail"], [_entry("2026-07")])
    assert run.write_keys == []
    assert "No entries to process after filtering." in caplog.text


def test_a_narrow_hand_run_that_refuses_a_published_month_is_not(monkeypatch, caplog):
    """...and the SAME narrow run, with the tail left on, refuses two months the CDN is serving.
    That is a freeze, self-inflicted, and it exits non-zero through the same door as a failed fetch
    -- reached BEFORE the upload loop, because every entry was filtered away."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, ["--year-from", "2030"], [_entry("2026-07")],
                   probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND})
    assert str(exc.value).startswith("UNLANDED-TAIL")
    assert "['2026-08', '2026-09']" in str(exc.value)


def test_limit_drops_a_tail_month_loudly(monkeypatch, caplog):
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, ["--limit", "1"], [_entry("2026-06"), _entry("2026-07")],
                   probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND})
    assert "dropped by --limit 1" in caplog.text
    assert str(exc.value).startswith("UNLANDED-TAIL")


def test_the_jobdefs_own_default_command_leaves_the_tripwire_ARMED(monkeypatch, caplog):
    """The command that actually reaches argparse when NOBODY overrides it (jobdef
    leviathan-dev-usda-wap-raw-backfill rev 16, read 2026-09-15): --skip-existing-s3 --year-from
    2002 --year-to 2026 --sleep-seconds 1.5. Neither year bound drops anything in 2026, so
    scope_narrowed stays FALSE and the tripwire is live -- a fence that the estate's own default
    invocation silently downgrades to REPORT-ONLY would be no fence at all.

    (The deployed DAG replaces this array with just the script path -- configs/silver/dags/wap.json
    -- which is why the CODE defaults are the lever. Both paths are pinned: this test for the
    jobdef's array, test_skip_existing_s3_defaults_to_on... for the bare one.)"""
    _today(monkeypatch, "2026-09")
    argv = ["--skip-existing-s3", "--year-from", "2002", "--year-to", "2026",
            "--sleep-seconds", "1.5"]
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, argv, [_entry("2026-07")],
                     probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND})
    assert "Tripwire: PASS" in caplog.text
    assert "REPORT-ONLY" not in caplog.text
    assert run.write_keys == [mod.raw_wap_key(m) for m in ("2026-07", _AUG, _SEP)]


def test_a_smoke_test_with_the_tail_off_is_a_clean_exit(monkeypatch, caplog):
    """The 1-5 file smoke the --limit help advertises still exits 0 -- with --no-tail, the form that
    says out loud that this run is not asking the estate's question. Pinned because a fence that
    makes the documented smoke impossible is a fence that gets disabled."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--limit", "1", "--no-tail"],
                     [_entry("2026-06"), _entry("2026-07")])
    assert run.write_keys == [mod.raw_wap_key("2026-06")]
    assert "Tripwire: disarmed by --no-tail" in caplog.text


# ---------------------------------------------------------------------------
# (F2 / b1+, b2+, b3+) --skip-existing-s3
# ---------------------------------------------------------------------------

def test_skip_existing_s3_defaults_to_on_and_the_opt_out_is_explicit(monkeypatch):
    """THE FIX FOR F2, at the only layer this lane owns. The jobdef default command carries the
    bare flag and the submitter passes it explicitly, so BooleanOptionalAction keeps both working
    verbatim while flipping the default that the DAG's command override exposed."""
    import sys

    # Bound ONCE, before any patching: re-reading the attribute inside _parsed would pick up the
    # previous call's spy and the second parse would exit before recording anything.
    real = argparse.ArgumentParser.parse_args

    def _parsed(argv):
        # No extra flags: the spy aborts AT parse time, so nothing downstream ever runs and the
        # namespace read back is exactly what the given argv produced.
        monkeypatch.setattr(sys, "argv", ["fetch_usda_wap.py", *argv])
        captured = {}

        def _spy(self, *a, **k):
            ns = real(self, *a, **k)
            captured["ns"] = ns
            raise SystemExit(0)

        monkeypatch.setattr(argparse.ArgumentParser, "parse_args", _spy)
        with pytest.raises(SystemExit):
            mod.main()
        return captured["ns"]

    assert _parsed([]).skip_existing_s3 is True                       # the scheduled path
    assert _parsed(["--skip-existing-s3"]).skip_existing_s3 is True   # the jobdef's own flag
    assert _parsed(["--no-skip-existing-s3"]).skip_existing_s3 is False
    assert _parsed([]).tail is True and _parsed(["--no-tail"]).tail is False
    assert _parsed([]).tail_tripwire is True
    assert _parsed(["--no-tail-tripwire"]).tail_tripwire is False


def test_the_existence_check_and_the_write_use_the_same_key(monkeypatch):
    """(b1+) The property that makes the skip mean anything, recorded from BOTH monkeypatched calls.
    A check that keys differently from the write is a skip that never fires -- which is
    indistinguishable, in the log, from the flag never arriving."""
    _today(monkeypatch, "2026-09")
    run = _drive(monkeypatch, [], [_entry("2026-07")],
                 probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND})
    assert run.head_keys == run.write_keys
    # ...and the literal, so a change to raw_wap_key has to be a deliberate one.
    assert mod.raw_wap_key(_AUG) == \
        "raw/production/source=usda_wap/release_month=2026-08/production.pdf"
    assert mod.raw_wap_key(_AUG) in run.head_keys and mod.raw_wap_key(_AUG) in run.write_keys


def test_an_existing_key_is_skipped_before_the_download(monkeypatch, caplog):
    """(b2+) The skip has to save the GET, not merely the PUT: 287 PDFs at 1-26 MB each is
    1,051,731,539 bytes per fire off fas.usda.gov. ``_fetch`` raising proves it is never reached."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--no-tail"], [_entry("2026-07")],
                     present={mod.raw_wap_key("2026-07")},
                     fetch_raises=AssertionError("the skip did not fire before the download"))
    assert run.fetched == [] and run.write_keys == []
    assert "uploaded=0  skipped=1  errors=0" in caplog.text


def test_a_missing_key_is_still_fetched_with_the_skip_on(monkeypatch, caplog):
    """(a10+) The other direction of the same flag: the tail must not become the only thing that can
    write. A manifest month absent from S3 is downloaded even in the default skip-on mode."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--no-tail"], [_entry("2026-06"), _entry("2026-07")],
                     present={mod.raw_wap_key("2026-06")})
    assert run.write_keys == [mod.raw_wap_key("2026-07")]
    assert "uploaded=1  skipped=1  errors=0" in caplog.text


def test_no_skip_existing_s3_forces_the_re_download(monkeypatch, caplog):
    """The opt-out still works, and it is the behaviour change a hand re-fetch now has to ask for."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--no-tail", "--no-skip-existing-s3"], [_entry("2026-07")],
                     present={mod.raw_wap_key("2026-07")})
    assert run.head_keys == []                    # the existence check is not even consulted
    assert run.write_keys == [mod.raw_wap_key("2026-07")]
    assert "uploaded=1  skipped=0  errors=0" in caplog.text


def test_a_re_run_the_same_day_is_a_no_op(monkeypatch, caplog):
    """(a9+) Days 12, 13 AND 14 all fire. The second and third runs must skip the month the first one
    fetched -- which is why the tail and the skip default had to land in the SAME change."""
    _today(monkeypatch, "2026-09")
    manifest = [_entry("2026-07")]
    present: set[str] = set()

    def _run():
        r = _drive(monkeypatch, [], manifest,
                   probe={_AUG: mod._TAIL_FOUND, _SEP: mod._TAIL_FOUND},
                   present=present)
        present.update(r.write_keys)
        return r

    first = _run()
    assert len(first.write_keys) == 3             # 2026-07 + the two tail months
    with caplog.at_level("INFO"):
        second = _run()
    assert second.write_keys == []
    assert "uploaded=0  skipped=3  errors=0" in caplog.text


def test_the_submitter_still_passes_the_flag_so_the_two_cannot_drift(monkeypatch):
    """(b4-) ``jobs/submit/submit_batch_wap_backfill.py`` passes ``--skip-existing-s3`` explicitly.
    The default flip leaves it working verbatim; this pin is what stops a later 'the default covers
    it, drop the flag' edit from silently coupling the hand-backfill path to a code default."""
    src = (_REPO / "jobs" / "submit" / "submit_batch_wap_backfill.py").read_text(encoding="utf-8")
    assert '"--skip-existing-s3"' in src


# ---------------------------------------------------------------------------
# The size floor -- a REPORT, never a refusal
# ---------------------------------------------------------------------------

def test_an_implausibly_small_pdf_is_named_and_still_written(monkeypatch, caplog):
    """MIN_RAW_FILE_SIZES carries no ``usda_wap`` entry, so ``check_min_file_size`` -- which reads
    like validation at its call site -- is a NO-OP for this source and the only real check is the
    4-byte %PDF magic. Three raw objects are implausibly small against a 1.6-26 MB norm (1999-09 at
    6,463 B; 2025-10 at 19,090 B; 2025-11 at 29,106 B) and two of those months are absent from
    silver. Re-fetching cannot help -- their URLs are wrong, so the same wrong bytes come back
    forever -- so the floor NAMES, it never refuses."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        run = _drive(monkeypatch, ["--no-tail"], [_entry("2026-07")], body=b"%PDF-1.7 tiny")
    assert run.write_keys == [mod.raw_wap_key("2026-07")]        # WRITTEN, not refused
    assert "SIZE-FLOOR 2026-07" in caplog.text
    assert "uploaded=1" in caplog.text


def test_a_normal_sized_pdf_raises_no_size_warning(monkeypatch, caplog):
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        _drive(monkeypatch, ["--no-tail"], [_entry("2026-07")],
               body=b"%PDF-1.7 " + b"x" * mod._SUSPICIOUS_PDF_BYTES)
    assert "SIZE-FLOOR" not in caplog.text


def test_a_non_pdf_body_is_an_error_not_an_upload(monkeypatch, caplog):
    """The one validation that IS real, pinned so the size-floor warning above can never be mistaken
    for it: a body that is not a PDF is refused, counted as an error, and -- since the review -- the
    run carrying it cannot report success, even with the tail and its tripwire both off. An Akamai
    HTML block page served under a 200 is exactly how this arrives in the wild."""
    _today(monkeypatch, "2026-09")
    with caplog.at_level("INFO"):
        with pytest.raises(SystemExit) as exc:
            _drive(monkeypatch, ["--no-tail", "--no-tail-tripwire"], [_entry("2026-07")],
                   body=b"<html>403</html>")
    assert "uploaded=0  skipped=0  errors=1" in caplog.text
    assert str(exc.value).startswith("FETCH-FAILED")
    assert "is not a PDF" in caplog.text


# ---------------------------------------------------------------------------
# The byte-identical set
# ---------------------------------------------------------------------------

def test_dry_run_stays_credential_free(monkeypatch, capsys):
    """BYTE-IDENTICAL item 6. ``--dry-run`` returns BEFORE ``load_env()`` / ``get_required_env``, and
    the tail probe sits on the network side of that line, so a dry run still works on any host with
    no AWS credentials at all."""
    _today(monkeypatch, "2026-09")

    def _boom(*a, **k):
        raise AssertionError("--dry-run must not touch AWS")

    monkeypatch.setattr(mod, "load_env", _boom)
    monkeypatch.setattr(mod, "get_required_env", _boom)
    monkeypatch.setattr(mod, "s3_object_exists", _boom)
    monkeypatch.setattr(mod, "upload_bytes_to_s3", _boom)
    monkeypatch.setattr(mod, "_load_manifest", lambda: [_entry("2026-07")])
    monkeypatch.setattr(mod, "_probe_tail",
                        lambda ym, sleep_seconds=0.0: (mod._TAIL_FOUND, mod._cdn_tail_url(ym)))
    monkeypatch.setattr("sys.argv",
                        ["fetch_usda_wap.py", "--dry-run", "--sleep-seconds", "0"])
    mod.main()
    out = capsys.readouterr().out
    assert "raw/production/source=usda_wap/release_month=2026-08/production.pdf" in out
    assert "(tail)" in out
    # ...and the tripwire is PREDICTED through the same pure function, never acted on: a preview
    # must not exit non-zero.
    assert "tripwire would report PASS" in out
    assert "newest release month this run would land: 2026-09" in out


def test_the_committed_manifest_is_additive_and_current():
    """BYTE-IDENTICAL item 1. The manifest is APPEND-ONLY: 287 entries at 2026-07-17, now 289 after
    2026-08 and 2026-09 were appended by hand on 2026-09-15 (their CDN URLs HEAD-verified at
    1,645,992 and 21,431,027 bytes -- ``--discover`` could not be re-run, because FAS returns Akamai
    403 to this estate's laptop for both the search pagination and the report home page). Every
    pre-existing line is byte-identical; ``git diff`` shows additions only."""
    data = yaml.safe_load(mod._MANIFEST_PATH.read_text(encoding="utf-8"))
    yms = [e["release_month"] for e in data["releases"]]
    assert len(yms) == 289
    assert min(yms) == "2002-08" and max(yms) == "2026-09"
    assert len(set(yms)) == len(yms), "a duplicate release month would fetch the same key twice"
    assert yms == sorted(yms), "the tail reads max(release_month); an unsorted manifest is a trap"
    assert yms[-2:] == [_AUG, _SEP]
    # The two appended URLs are the ones the tail itself would build, so the manifest and the probe
    # can never disagree about where a modern circular lives.
    for e in data["releases"][-2:]:
        assert e["url"] == mod._cdn_tail_url(e["release_month"])


def test_the_module_is_ascii_only():
    """BYTE-IDENTICAL item 7. The Windows console is cp1252: a log line carrying an EN DASH raises
    UnicodeEncodeError mid-run. The file had eleven of them (``--discover``'s own progress lines and
    the ``--limit`` help text) and they are corrected in this change."""
    src = (_REPO / "jobs" / "ingest" / "fetch_usda_wap.py").read_text(encoding="utf-8")
    bad = sorted({c for c in src if ord(c) > 126})
    assert bad == [], f"non-ASCII in fetch_usda_wap.py: {[hex(ord(c)) for c in bad]}"


def test_help_is_ascii_and_names_both_halves_of_each_toggle():
    parser_help = _build_help()
    bad = sorted({c for c in parser_help if ord(c) > 126})
    assert bad == []
    for flag in ("--skip-existing-s3", "--no-skip-existing-s3", "--tail", "--no-tail",
                 "--tail-tripwire", "--no-tail-tripwire"):
        assert flag in parser_help


def _build_help() -> str:
    """Render ``--help`` without spawning a process: drive main() to the parser and capture it."""
    import sys
    import unittest.mock as m

    with m.patch.object(sys, "argv", ["fetch_usda_wap.py", "--help"]):
        buf = io.StringIO()
        with m.patch.object(sys, "stdout", buf):
            with pytest.raises(SystemExit) as exc:
                mod.main()
        assert exc.value.code == 0
        return buf.getvalue()


def test_the_bronze_and_silver_tasks_need_no_edit_to_see_a_new_month():
    """BYTE-IDENTICAL item 3, asserted rather than asserted-about. Neither downstream task is
    touched by this change because both DISCOVER their work by listing S3 -- ``wap_task`` over the
    raw PDF prefix and ``wap_silver_task`` over the bronze prefix -- so a new raw month rides
    automatically. The pin is on that listing, because the day either one switches to a manifest or
    a hard-coded month list, the tail stops reaching silver and nothing else here would notice."""
    bronze = (_REPO / "jobs" / "batch" / "wap_task.py").read_text(encoding="utf-8")
    silver = (_REPO / "jobs" / "batch" / "wap_silver_task.py").read_text(encoding="utf-8")
    assert "list_s3_keys" in bronze and "raw/production/source=usda_wap" in bronze
    assert "list_s3_keys" in silver and "bronze/production/source=usda_wap" in silver
    for src in (bronze, silver):
        assert "usda_wap_manifest" not in src
