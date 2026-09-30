"""Data repairs 0929, lane ENSO: silver_noaa_enso_vintages (ENSO-1 the Relative ONI beside the legacy
ONI with each index's official dates as data; ENSO-2 every held vintage, first prints included, with
the date it became known; absent vintages said absent, never invented).

The fixtures under tests/fixtures/noaa_oni/vintages/ are REAL captures of NOAA CPC's two files --
eleven web-archive captures (the legacy timestamps are CDX-listed; seven bodies are gzip bytes named
.txt, as the archive served them) and the two live files fetched 2026-09-29 whose Last-Modified was
2026-09-03 18:32:06 GMT -- each trimmed to its header plus every season with YR >= 2025, lines
verbatim. tests/fixtures/noaa_oni/pns26-05_excerpt.txt is a verbatim excerpt of NWS PNS 26-05.
"""
from __future__ import annotations

import gzip
import importlib
import io
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.transforms.bronze_to_silver import noaa_oni as S
from leviathan.transforms.raw_to_bronze import noaa_oni as R

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "noaa_oni"
_VINT = _FIX / "vintages"
_LM_20260903 = "Thu, 03 Sep 2026 18:32:06 GMT"
_LEGACY_HDR = R.ENSO_INDEX_FILES_BY_ID["cpc_oni_ascii"].header
_RONI_HDR = R.ENSO_INDEX_FILES_BY_ID["cpc_roni_ascii"].header


def _fixture_captures() -> list[R.EnsoCapture]:
    caps = []
    for f in sorted(_VINT.glob("*_2026*.txt")):
        prefix, ts = f.stem.split("_")
        url = R.ONI_LEGACY_URL if prefix == "oni" else R.RONI_URL
        caps.append(R.capture_from_archive(url, ts, {}, f.read_bytes()))
    for name, url in (("oni_live_lm20260903.txt", R.ONI_LEGACY_URL),
                      ("roni_live_lm20260903.txt", R.RONI_URL)):
        caps.append(R.capture_from_origin(url, {"Last-Modified": _LM_20260903}, (_VINT / name).read_bytes()))
    return caps


@pytest.fixture(scope="module")
def build() -> S.EnsoVintageBuild:
    return S.build_enso_vintages(_fixture_captures())


def _asof(frame: pd.DataFrame, index_id: str, asof: str) -> pd.DataFrame:
    """The as-of read the table is built for: per season, the greatest vintage_date <= asof."""
    v = frame[(frame.index_id == index_id) & (frame.vintage_date <= asof)]
    return v.sort_values("vintage_date").groupby(["year", "month"]).tail(1).set_index(["year", "month"])


# ---------------------------------------------------------------------------
# The parser: one per file, keyed on the file's own header, fail closed.
# ---------------------------------------------------------------------------
def test_header_keyed_parse_agrees_with_the_served_legacy_parser():
    body = (_FIX / "oni.ascii.sample.txt").read_bytes()
    new = R.parse_enso_index_text(body, _LEGACY_HDR)
    old = R.extract_oni_bronze(body)
    assert len(new) == len(old) == 600
    assert new[["season", "year", "month"]].equals(old[["season", "year", "month"]])
    assert (new["anom"].to_numpy() == old["oni_anom"].astype(float).to_numpy()).all()


def test_roni_parses_on_its_own_header_and_the_legacy_parser_cannot_read_it():
    body = (_VINT / "roni_live_lm20260903.txt").read_bytes()
    t = R.parse_enso_index_text(body, _RONI_HDR)
    assert (t.iloc[-1].season, int(t.iloc[-1].year), int(t.iloc[-1].month), t.iloc[-1].anom) == ("JJA", 2026, 7, 1.36)
    with pytest.raises(ValueError):          # the reason a second parser exists (HEAD behaviour, kept)
        R.extract_oni_bronze(body)


@pytest.mark.parametrize("body,header,match", [
    (b" SEAS  YR   TOTAL   ANOM\n  DJF 2026  26.11  -0.39\n", ("SEAS", "YR", "ANOM"), "header"),
    (b"SEAS   YR  ANOM\nDJF  2026 -0.90 7\n", ("SEAS", "YR", "ANOM"), "fields"),
    (b"SEAS   YR  ANOM\nXYZ  2026 -0.90\n", ("SEAS", "YR", "ANOM"), "season"),
    (b"SEAS   YR  ANOM\nDJF  2026 -0.90\nFMA  2026 -0.40\n", ("SEAS", "YR", "ANOM"), "follow"),
    (b"SEAS   YR  ANOM\nDJF  2026 -0.90\nDJF  2026 -0.90\n", ("SEAS", "YR", "ANOM"), "follow"),
    (b"SEAS   YR  ANOM\n", ("SEAS", "YR", "ANOM"), "no data"),
    (b"<html>Service Unavailable</html>\n", ("SEAS", "YR", "ANOM"), "header"),
])
def test_parse_fails_closed(body, header, match):
    with pytest.raises(ValueError, match=match):
        R.parse_enso_index_text(body, header)


def test_ndj_djf_year_boundary_is_the_centre_month():
    t = R.parse_enso_index_text(b"SEAS   YR  ANOM\nOND  2025 -0.98\nNDJ  2025 -1.04\nDJF  2026 -0.91\n", _RONI_HDR)
    assert list(zip(t.year, t.month)) == [(2025, 11), (2025, 12), (2026, 1)]
    assert R.season_end_month(2025, 12) == (2026, 1)
    assert R.SEASON_TO_MONTH is S.SEASON_TO_MONTH          # ONE map, imported, never copied


def test_index_id_is_the_url_never_a_display_name():
    assert R.index_id_for_url(R.ONI_LEGACY_URL) == "cpc_oni_ascii"
    assert R.index_id_for_url(R.RONI_URL) == "cpc_roni_ascii"
    assert set(R.ENSO_INDEX_FILES_BY_ID) == {"cpc_oni_ascii", "cpc_roni_ascii"}


# ---------------------------------------------------------------------------
# The capture: identity by decoded content, date by a publisher clock, never our fetch time.
# ---------------------------------------------------------------------------
def test_gzip_is_decided_by_magic_bytes_and_one_content_is_one_digest():
    plain = (_VINT / "roni_20260417090640.txt").read_bytes()
    gz = (_VINT / "roni_20260429192642.txt").read_bytes()
    assert gz[:2] == b"\x1f\x8b" and plain[:2] != b"\x1f\x8b"
    assert R.decode_capture_body(gz) == plain
    assert R.content_sha256(gz) == R.content_sha256(plain)


def test_origin_capture_clock_rules():
    body = (_VINT / "oni_live_lm20260903.txt").read_bytes()
    cap = R.capture_from_origin(R.ONI_LEGACY_URL, {"Last-Modified": _LM_20260903,
                                                   "Content-Length": str(len(body))}, body)
    assert cap.clock == R.CLOCK_ORIGIN_LAST_MODIFIED
    assert cap.evidence_utc == datetime(2026, 9, 3, 18, 32, 6, tzinfo=timezone.utc)
    assert R.parse_enso_capture_key(cap.key) == {"index_id": "cpc_oni_ascii", "clock": cap.clock,
                                                 "evidence_utc": cap.evidence_utc, "sha256": cap.sha256}
    assert cap.key.startswith(R.ENSO_CAPTURE_PREFIX)
    undated = R.capture_from_origin(R.ONI_LEGACY_URL, {}, body)
    assert undated.clock == R.CLOCK_UNDATED and undated.evidence_utc is None
    assert "/evidence=none/" in undated.key
    with pytest.raises(ValueError, match="Content-Length"):
        R.capture_from_origin(R.ONI_LEGACY_URL, {"Last-Modified": _LM_20260903, "Content-Length": "5"}, body)
    # under a Content-Encoding the header counts encoded bytes: no comparison
    R.capture_from_origin(R.ONI_LEGACY_URL, {"Last-Modified": _LM_20260903, "Content-Length": "5",
                                             "Content-Encoding": "gzip"}, body)


def test_archive_capture_clock_rules():
    body = (_VINT / "oni_20260405213541.txt").read_bytes()
    plain = R.capture_from_archive(R.ONI_LEGACY_URL, "20260405213541", {}, body)
    assert plain.clock == R.CLOCK_ARCHIVE_CAPTURE
    assert plain.evidence_utc == datetime(2026, 4, 5, 21, 35, 41, tzinfo=timezone.utc)
    rec = R.capture_from_archive(R.ONI_LEGACY_URL, "20260405213541",
                                 {"X-Archive-Orig-Last-Modified": "Fri, 03 Apr 2026 17:00:00 GMT",
                                  "Last-Modified": "Sun, 05 Apr 2026 21:35:41 GMT"}, body)
    assert rec.clock == R.CLOCK_ARCHIVE_ORIGIN_LAST_MODIFIED           # the archive's OWN LM is never read
    assert rec.evidence_utc == datetime(2026, 4, 3, 17, 0, 0, tzinfo=timezone.utc)
    later = R.capture_from_archive(R.ONI_LEGACY_URL, "20260405213541",
                                   {"X-Archive-Orig-Last-Modified": "Mon, 06 Apr 2026 00:00:00 GMT"}, body)
    assert later.clock == R.CLOCK_ARCHIVE_CAPTURE                      # an origin LM after the crawl is impossible


# ---------------------------------------------------------------------------
# The official index, from the publisher's own words.
# ---------------------------------------------------------------------------
def test_statement_quotes_are_verbatim_and_dates_are_extracted():
    saved = " ".join((_FIX / "pns26-05_excerpt.txt").read_text(encoding="utf-8").split())
    (stmt,) = R.ENSO_STATUS_STATEMENTS
    for quote in (stmt.issued_line, stmt.effective_quote, stmt.becomes_quote, stmt.ceases_quote):
        assert " ".join(quote.split()) in saved, quote
    assert R.statement_effective_date(stmt).isoformat() == "2026-02-01"
    assert R.statement_issued_date(stmt).isoformat() == "2026-01-13"
    assert stmt.becomes_official_url in saved                          # the statement names the RONI file


def test_official_windows_meet_with_no_gap_and_no_overlap():
    w = R.official_windows()
    legacy, roni = w["cpc_oni_ascii"], w["cpc_roni_ascii"]
    assert (roni.official_from, roni.official_until) == ("2026-02-01", None)
    assert (legacy.official_from, legacy.official_until) == (None, "2026-02-01")
    assert legacy.official_until == roni.official_from
    assert "no publisher statement held" in legacy.official_statement   # NULL with its reason, never a guess
    assert "NWS PNS 26-05 issued 2026-01-13" in roni.official_statement


# ---------------------------------------------------------------------------
# The table, built from the real captures.
# ---------------------------------------------------------------------------
def test_shape_key_and_types(build):
    f = build.frame
    assert list(f.columns) == S.VINTAGE_COLUMNS
    assert not f.duplicated(subset=S.VINTAGE_NATURAL_KEY).any()
    assert f["year"].dtype == "int64" and f["month"].dtype == "int64"
    assert f["anom"].dtype == "float64" and f["is_first_print"].dtype == bool
    assert build.quarantined == [] and build.undated == [] and build.superseded_same_day == []
    assert set(f.vintage_date_source) <= set(R.DATED_CLOCKS)


def test_first_prints_held_and_absent(build):
    fp = build.frame[build.frame.is_first_print]
    got = {(r.index_id, r.season, int(r.year)): (r.anom, r.vintage_date) for r in fp.itertuples()}
    assert got == {
        ("cpc_oni_ascii", "DJF", 2026): (-0.39, "2026-03-09"),
        ("cpc_oni_ascii", "JFM", 2026): (-0.16, "2026-04-05"),
        ("cpc_oni_ascii", "FMA", 2026): (0.11, "2026-05-11"),
        ("cpc_oni_ascii", "AMJ", 2026): (0.98, "2026-07-26"),
        ("cpc_oni_ascii", "JJA", 2026): (1.80, "2026-09-03"),
        ("cpc_roni_ascii", "DJF", 2026): (-0.90, "2026-03-23"),
        ("cpc_roni_ascii", "JFM", 2026): (-0.72, "2026-04-17"),
        ("cpc_roni_ascii", "MAM", 2026): (-0.06, "2026-06-11"),
        ("cpc_roni_ascii", "AMJ", 2026): (0.47, "2026-07-21"),
        ("cpc_roni_ascii", "MJJ", 2026): (0.98, "2026-08-20"),
        ("cpc_roni_ascii", "JJA", 2026): (1.36, "2026-09-03"),
    }
    assert build.absent_first_prints["cpc_oni_ascii"]["between_held_vintages"] == ["MAM 2026", "MJJ 2026"]
    assert build.absent_first_prints["cpc_roni_ascii"]["between_held_vintages"] == ["FMA 2026"]
    assert build.absent_first_prints["cpc_oni_ascii"]["before_first_held_vintage"] == \
        "every season through NDJ 2025"


def test_every_revision_of_jfm_2026_is_its_own_row(build):
    f = build.frame
    jfm = f[(f.year == 2026) & (f.month == 2)].sort_values(["index_id", "vintage_date"])
    assert list(zip(jfm.index_id, jfm.anom, jfm.vintage_date)) == [
        ("cpc_oni_ascii", -0.16, "2026-04-05"), ("cpc_oni_ascii", -0.15, "2026-05-11"),
        ("cpc_oni_ascii", -0.14, "2026-07-26"), ("cpc_oni_ascii", -0.21, "2026-09-03"),
        ("cpc_roni_ascii", -0.72, "2026-04-17"), ("cpc_roni_ascii", -0.71, "2026-06-11"),
        ("cpc_roni_ascii", -0.76, "2026-08-20"),
    ]


def test_asof_reads_what_noaa_had_printed(build):
    f = build.frame
    assert _asof(f, "cpc_oni_ascii", "2026-04-15").loc[(2026, 2), "anom"] == -0.16   # the store served -0.21
    assert _asof(f, "cpc_oni_ascii", "2026-09-10").loc[(2026, 2), "anom"] == -0.21
    assert _asof(f, "cpc_roni_ascii", "2026-09-10").loc[(2026, 7), "anom"] == 1.36
    assert _asof(f, "cpc_roni_ascii", "2026-03-15").empty                          # nothing held yet: absent
    # the newest vintage of each index equals NOAA's live file, season for season
    for iid, name, hdr in (("cpc_oni_ascii", "oni_live_lm20260903.txt", _LEGACY_HDR),
                           ("cpc_roni_ascii", "roni_live_lm20260903.txt", _RONI_HDR)):
        live = R.parse_enso_index_text((_VINT / name).read_bytes(), hdr).set_index(["year", "month"])
        cur = _asof(f, iid, "2026-09-29")
        assert cur["anom"].reindex(live.index).tolist() == live["anom"].tolist()


def test_no_row_is_known_before_its_season_ends_or_before_its_evidence(build):
    from datetime import date
    f = build.frame
    for r in f.itertuples():
        ey, em = R.season_end_month(r.year, r.month)
        first_possible = date(ey + (em == 12), em % 12 + 1, 1).isoformat()
        assert r.vintage_date >= first_possible, (r.season, r.year, r.vintage_date)
        assert r.vintage_date == r.vintage_evidence_utc[:10]
    assert f[f.index_id == "cpc_roni_ascii"].vintage_date.min() >= "2026-01-13"   # never before the index existed


def test_one_content_in_two_captures_is_one_vintage(build):
    refs = {(c["index_id"], c["capture_ref"].split("/evidence=")[1][:15]) for c in build.corroborating}
    assert ("cpc_roni_ascii", "20260429T192642") in refs          # gzip twin of the 04-17 plain capture
    assert ("cpc_oni_ascii", "20260907T074453") in refs           # the archive saw the 09-03 file on 09-07
    oni_vintages = [v["vintage_date"] for v in build.vintages["cpc_oni_ascii"]]
    assert oni_vintages == ["2026-03-09", "2026-04-05", "2026-05-11", "2026-07-26", "2026-09-03"]


def test_build_is_order_free():
    caps = _fixture_captures()
    random.Random(7).shuffle(caps)
    a = S.build_enso_vintages(caps).frame
    b = S.build_enso_vintages(sorted(caps, key=lambda c: c.key)).frame
    pd.testing.assert_frame_equal(a, b)


def test_official_columns_ride_every_row(build):
    f = build.frame
    legacy, roni = f[f.index_id == "cpc_oni_ascii"], f[f.index_id == "cpc_roni_ascii"]
    assert legacy.official_from.isna().all() and (legacy.official_until == "2026-02-01").all()
    assert (roni.official_from == "2026-02-01").all() and roni.official_until.isna().all()
    assert f.official_statement.notna().all()


# ---------------------------------------------------------------------------
# Refusals: listed with a reason, never raised, never landed.
# ---------------------------------------------------------------------------
def _cap(body: bytes, url=R.RONI_URL, ts="20260901000000") -> R.EnsoCapture:
    return R.capture_from_archive(url, ts, {}, body)


def test_a_clock_before_the_season_ends_is_refused():
    body = b"SEAS   YR  ANOM\nMJJ  2026  0.98\nJJA  2026  1.36\n"
    b = S.build_enso_vintages([_cap(body, ts="20260830000000")])   # JJA ends 08-31: not knowable on 08-30
    assert b.frame.empty and "precedes the end of its newest season JJA 2026" in b.quarantined[0]["reason"]


def test_digest_mismatch_undeclared_index_and_undated_are_refused_or_listed():
    good = _cap(b"SEAS   YR  ANOM\nJJA  2026  1.36\n")
    forged = R.EnsoCapture(good.index_id, good.source_url, good.clock, good.evidence_utc, "0" * 64, good.body)
    foreign = R.capture_from_archive("https://www.cpc.ncep.noaa.gov/data/indices/Rnino34.ascii.txt",
                                     "20260901000000", {}, b"YR   MTH   ANOM\n2026   8  1.67\n")
    undated = R.capture_from_origin(R.RONI_URL, {}, good.body)
    b = S.build_enso_vintages([forged, foreign, undated])
    reasons = sorted(q["reason"] for q in b.quarantined)
    assert any("does not hash" in r for r in reasons)
    assert any("not a declared ENSO index file" in r for r in reasons)
    assert b.undated == [undated.key] and b.frame.empty


def test_a_stale_replay_and_a_dropped_season_are_refused():
    newer = _cap(b"SEAS   YR  ANOM\nMJJ  2026  0.98\nJJA  2026  1.36\n", ts="20260905000000")
    stale = _cap(b"SEAS   YR  ANOM\nAMJ  2026  0.47\nMJJ  2026  0.98\n", ts="20260906000000")
    shorter = _cap(b"SEAS   YR  ANOM\nJJA  2026  1.36\nJAS  2026  1.70\n", ts="20261006000000")
    b = S.build_enso_vintages([newer, stale, shorter])
    reasons = {q["capture_ref"]: q["reason"] for q in b.quarantined}
    assert "is older than" in reasons[stale.key]
    assert "drops 1 season" in reasons[shorter.key]
    assert b.frame.vintage_date.unique().tolist() == ["2026-09-05"]


def test_two_contents_at_one_instant_are_both_refused_and_same_day_keeps_the_last():
    a = _cap(b"SEAS   YR  ANOM\nJJA  2026  1.36\n", ts="20260905000000")
    b_ = _cap(b"SEAS   YR  ANOM\nJJA  2026  1.40\n", ts="20260905000000")
    b = S.build_enso_vintages([a, b_])
    assert b.frame.empty and len(b.quarantined) == 2
    early = _cap(b"SEAS   YR  ANOM\nJJA  2026  1.36\n", ts="20260905010000")
    late = _cap(b"SEAS   YR  ANOM\nJJA  2026  1.38\n", ts="20260905230000")
    b2 = S.build_enso_vintages([early, late])
    assert b2.frame.anom.tolist() == [1.38] and b2.superseded_same_day[0]["capture_ref"] == early.key


# ---------------------------------------------------------------------------
# The publish: the contract the integrator generates, and the task leg end to end on a fake store.
# ---------------------------------------------------------------------------
# The F010 physical columns the generated contract of silver_noaa_enso_vintages must carry (the
# integrator's synthetic R0 record; HANDOFF). target_arrow_type, nullable.
VINTAGE_CONTRACT_COLUMNS = {
    "index_id": ("string", False), "source_url": ("string", False), "season": ("string", False),
    "year": ("int64", False), "month": ("int64", False), "anom": ("float64", True),
    "vintage_date": ("string", False), "vintage_evidence_utc": ("string", False),
    "vintage_date_source": ("string", False), "capture_ref": ("string", False),
    "content_sha256": ("string", False), "is_first_print": ("bool", False),
    "official_from": ("string", True), "official_until": ("string", True),
    "official_statement": ("string", True),
}


def _vintages_contract() -> dict:
    return {
        "table_name": "silver_noaa_enso_vintages", "schema_version": 1, "glue_database": "test_db",
        "s3_bucket": "test-bucket", "s3_root": "s3://test-bucket/silver/noaa_enso_vintages",
        "s3_prefix": "silver/noaa_enso_vintages",
        "physical_columns": [{"name": n, "target_arrow_type": t, "nullable": nl}
                             for n, (t, nl) in VINTAGE_CONTRACT_COLUMNS.items()],
        "value_columns": ["anom"], "min_nonnull_frac": 0.5,
        "natural_key": list(S.VINTAGE_NATURAL_KEY), "knowledge_date_col": "vintage_date",
    }


def test_contract_spec_is_the_builder_columns_in_order():
    assert list(VINTAGE_CONTRACT_COLUMNS) == S.VINTAGE_COLUMNS


def test_registered_contract_matches_the_spec_once_generated():
    from leviathan.silver.registry import load_registry
    reg = load_registry()
    if "silver_noaa_enso_vintages" not in reg.tables:
        pytest.skip("silver_noaa_enso_vintages is not generated yet (the INTEGRATOR's step)")
    c = reg.table("silver_noaa_enso_vintages")
    assert [(p["name"], p["target_arrow_type"], bool(p.get("nullable", True))) for p in c["physical_columns"]] == \
        [(n, t, nl) for n, (t, nl) in VINTAGE_CONTRACT_COLUMNS.items()]
    assert c["natural_key"] == S.VINTAGE_NATURAL_KEY and c["knowledge_date_col"] == "vintage_date"
    assert c["s3_prefix"].rstrip("/") == "silver/noaa_enso_vintages"


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)
        self.puts: dict[str, bytes] = {}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.puts[Key] = bytes(Body)
        return {"ETag": '"x"'}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        self.puts[Key] = self.puts[CopySource["Key"]]
        return {}


def _run_task(monkeypatch, fake: _FakeS3, mode: str | None):
    task = importlib.import_module("jobs.batch.noaa_oni_task")
    import leviathan.storage.s3 as s3mod

    class _Reg:
        def table(self, name):
            assert name == "silver_noaa_enso_vintages"
            return _vintages_contract()

    monkeypatch.setattr(task, "load_registry", lambda: _Reg())
    monkeypatch.setattr(task, "load_env", lambda: None)
    monkeypatch.setattr(task, "_caller_identity", lambda region: ("", ""))
    monkeypatch.setattr(s3mod, "get_thread_local_s3_client", lambda region: fake)
    monkeypatch.setattr(s3mod, "list_s3_keys", lambda bucket, prefix, suffix="", aws_region="": [
        k for k in fake.objects if k.startswith(prefix) and k.endswith(suffix)])
    monkeypatch.delenv("LEVIATHAN_PUBLISH_MODE", raising=False)
    argv = ["noaa_oni_task.py", "--table", "silver_noaa_enso_vintages", "--bucket", "b", "--aws-region", "r"]
    monkeypatch.setattr(sys, "argv", argv + (["--publish-mode", mode] if mode else []))
    task.main()


def test_task_dry_run_reads_the_bank_and_writes_nothing(monkeypatch):
    held = {c.key: c.body for c in _fixture_captures()}
    held[R.ENSO_CAPTURE_PREFIX + "stray.txt"] = b"not a capture"
    fake = _FakeS3(held)
    _run_task(monkeypatch, fake, None)
    assert fake.puts == {}


def test_task_shadow_lands_the_table_off_canonical(monkeypatch):
    fake = _FakeS3({c.key: c.body for c in _fixture_captures()})
    _run_task(monkeypatch, fake, "shadow")
    shadow = [k for k in fake.puts if "_shadow" in k and k.endswith(".parquet")]
    assert len(shadow) == 1 and "silver/noaa_enso_vintages/part-000.parquet" not in fake.puts
    table = pq.read_table(io.BytesIO(fake.puts[shadow[0]])).to_pandas()
    assert list(table.columns) == S.VINTAGE_COLUMNS and len(table) == len(S.build_enso_vintages(
        _fixture_captures()).frame)


def test_task_with_no_capture_exits_nonzero(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run_task(monkeypatch, _FakeS3({}), None)
    assert exc.value.code == 1


def test_task_refuses_year_bounds_on_the_vintages_table(monkeypatch):
    task = importlib.import_module("jobs.batch.noaa_oni_task")
    monkeypatch.setattr(task, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["t", "--table", "silver_noaa_enso_vintages", "--from-year", "2000"])
    with pytest.raises(SystemExit) as exc:
        task.main()
    assert exc.value.code == 2


def test_dry_run_publish_of_the_real_build_validates(build):
    plan = build_flat_publish(df=build.frame, contract=_vintages_contract(),
                              canonical_key="silver/noaa_enso_vintages/part-000.parquet",
                              auth=Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False,
                                                 readiness=True, reason="test"),
                              s3_client=None, job="test", manifest_store=lambda k, b: None)
    manifest = plan.run()
    assert manifest.state.value == "VALIDATED" and manifest.validation_result["ok"] is True


# ---------------------------------------------------------------------------
# The fetcher seams: bank never overwrites; a failure never fails the served leg; the archive is verified.
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, body: bytes, headers: dict, url: str = "", status: int = 200):
        self.content, self.headers, self.url, self.status_code = body, headers, url, status
        self.ok = status < 400

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fetcher():
    return importlib.import_module("jobs.ingest.fetch_noaa_oni")


def _dict_store():
    held: dict[str, bytes] = {}
    return held, (lambda k: k in held), (lambda k, body, meta: held.__setitem__(k, body))


def test_capture_live_banks_both_files_once_and_never_overwrites():
    F = _fetcher()
    bodies = {R.ONI_LEGACY_URL: (_VINT / "oni_live_lm20260903.txt").read_bytes(),
              R.RONI_URL: (_VINT / "roni_live_lm20260903.txt").read_bytes()}
    get = lambda u: _Resp(bodies[u], {"Last-Modified": _LM_20260903})   # noqa: E731
    held, exists, put = _dict_store()
    assert set(F.capture_live(get, exists=exists, put=put).values()) == {"banked"}
    assert len(held) == 2
    assert set(F.capture_live(get, exists=exists, put=put).values()) == {"held"}
    assert len(held) == 2


def test_capture_failure_is_logged_and_never_raised():
    F = _fetcher()
    legacy = (_VINT / "oni_live_lm20260903.txt").read_bytes()

    def get(u):
        if u == R.RONI_URL:
            raise ConnectionError("NOAA down")
        return _Resp(legacy, {"Last-Modified": _LM_20260903})
    held, exists, put = _dict_store()
    out = F.capture_live(get, exists=exists, put=put)
    assert out[R.ONI_LEGACY_URL] == "banked" and out[R.RONI_URL].startswith("failed: ConnectionError")
    html = lambda u: _Resp(b"<html>maintenance</html>", {"Last-Modified": _LM_20260903})  # noqa: E731
    out2 = F.capture_live(html, exists=exists, put=put)
    assert all(v.startswith("failed: ValueError") for v in out2.values()) and len(held) == 1


def test_archive_backfill_verifies_the_served_capture():
    F = _fetcher()
    body = (_VINT / "oni_20260405213541.txt").read_bytes()

    def get_json(url, params):
        if params["url"] == R.ONI_LEGACY_URL:
            return [["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
                    ["k", "20260405213541", R.ONI_LEGACY_URL, "text/plain", "200", "D", "7799"],
                    ["k", "20260511061808", R.ONI_LEGACY_URL, "text/plain", "200", "E", "7813"]]
        return []

    def get(url):
        if "20260511061808" in url:   # the archive answers an unmatched request with the NEAREST capture
            return _Resp(body, {}, url.replace("20260511061808", "20260405213541"))
        return _Resp(body, {"Memento-Datetime": "Sun, 05 Apr 2026 21:35:41 GMT"}, url)
    held, exists, put = _dict_store()
    tally = F.archive_backfill(get, get_json, from_year=2026, exists=exists, put=put, sleep=lambda s: None)
    assert tally["banked"] == 1 and len(tally["refused"]) == 1 and "served 20260405213541" in tally["refused"][0]
    (key,) = held
    assert "/clock=archive_capture/evidence=20260405T213541Z/" in key


def test_seed_needs_the_publisher_clock_and_a_matching_length():
    F = _fetcher()
    body = (_VINT / "roni_live_lm20260903.txt").read_bytes()
    head = F.parse_saved_headers(f"HTTP/1.1 200 OK\nLast-Modified: {_LM_20260903}\n"
                                 f"Content-Length: {len(body)}\nDate: Tue, 29 Sep 2026 17:37:38 GMT\n")
    held, exists, put = _dict_store()
    assert F.seed_from_saved(body, head, R.RONI_URL, exists=exists, put=put) == "banked"
    with pytest.raises(ValueError, match="Last-Modified"):
        F.seed_from_saved(body, {"Content-Length": str(len(body))}, R.RONI_URL, exists=exists, put=put)
    with pytest.raises(ValueError, match="Content-Length"):
        F.seed_from_saved(body, {"Last-Modified": _LM_20260903, "Content-Length": "1"}, R.RONI_URL,
                          exists=exists, put=put)
    with pytest.raises(ValueError, match="not a declared"):
        F.seed_from_saved(body, head, "https://www.cpc.ncep.noaa.gov/data/indices/Rnino34.ascii.txt",
                          exists=exists, put=put)


def test_gzip_fixture_bytes_are_gzip():
    # guards the .gitattributes: a checkout that rewrote these bytes would break every digest above
    assert (_VINT / "oni_20260309194143.txt").read_bytes()[:2] == b"\x1f\x8b"
    assert gzip.decompress((_VINT / "oni_20260309194143.txt").read_bytes()).startswith(b" SEAS  YR   TOTAL   ANOM\n")
