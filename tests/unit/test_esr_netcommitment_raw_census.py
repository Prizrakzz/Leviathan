"""jobs/utils/esr_netcommitment_raw_census.py -- the RAW-side measurement that sets the bound.

Hermetic: a fake S3 client, no AWS.

WHY IT EXISTS (C-M3). The rollout's re-bronze bound and its verdict sentence were going to be
``--as-of-min 20260813`` and "all five read 0.0 on every as_of < 20260813". That verdict cannot
fail: the 0.0 is guaranteed by the re-bronze SCOPE, not by the source, so it cannot distinguish
"the API did not publish" from "we did not re-bronze". The census answers the question on RAW
before anything is written, and the live answer refuted the bound:

    MEASURED 2026-09-04 over all 446 dated raw objects, s3://leviathan-dev-shahem-001:
    every one of the 12 as_of vintages (20260712 .. 20260904) carries ALL FIVE keys, 446/446.
    There is no pre-publication vintage in raw at all; 20260712 is simply the earliest vintage
    that exists.

These tests pin the instrument, not that answer: the brace-walking head parser, the presence /
non-null split, and the first-as_of derivations the runbook reads.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "jobs" / "utils" / "esr_netcommitment_raw_census.py"


@pytest.fixture(scope="module")
def census():
    spec = importlib.util.spec_from_file_location("esr_netcommitment_raw_census", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _record(with_five: bool, *, nulls=(), extra=None) -> dict:
    rec = {"commodityCode": 401, "country": "China", "weekEndingDate": "2026-08-13",
           "weeklyExports": 1.0, "outstandingSales": 2.0, "grossNewSales": 3.0, "unitId": 1}
    if with_five:
        rec.update({"accumulatedExports": 250000.0, "currentMYNetSales": 125000.5,
                    "currentMYTotalCommitment": 1250000.0, "nextMYOutstandingSales": 40000.0,
                    "nextMYNetSales": 15000.0})
        for key in nulls:
            rec[key] = None
    rec.update(extra or {})
    return rec


def _payload(record: dict, copies: int = 40) -> bytes:
    """A realistic body: a JSON ARRAY whose records all share one key set."""
    return json.dumps([record] * copies).encode("utf-8")


def _key(code: int, year: int, as_of: str | None) -> str:
    base = f"raw/production/source=usda_esr/commodity_code={code}/market_year={year}"
    return f"{base}/as_of={as_of}/all_countries.json" if as_of else f"{base}/all_countries.json"


class _Body:
    def __init__(self, blob):
        self._blob = blob

    def read(self):
        return self._blob


class FakeS3:
    """list_objects_v2 (paginated) + ranged get_object, the only two calls the census makes."""

    def __init__(self, objects: dict):
        self.objects = dict(objects)
        self.ranges: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix):  # noqa: N803
                contents = [{"Key": k, "Size": len(v)} for k, v in sorted(outer.objects.items())
                            if k.startswith(Prefix)]
                yield {"Contents": contents[:1]}
                yield {"Contents": contents[1:]}

        return _P()

    def get_object(self, Bucket, Key, Range=None):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        blob = self.objects[Key]
        if Range:
            self.ranges.append(Range)
            end = int(Range.split("-")[1])
            blob = blob[: end + 1]
        return {"Body": _Body(blob)}


class TestHeadParser:
    def test_it_reads_record_zero_out_of_a_TRUNCATED_array(self, census):
        blob = _payload(_record(True), copies=500)[:4096]
        rec = census._first_record(blob)
        assert rec is not None
        assert set(census.NET_COMMITMENT_KEYS) <= set(rec)

    def test_a_head_too_small_to_hold_one_record_returns_None(self, census):
        assert census._first_record(_payload(_record(True))[:20]) is None

    def test_braces_inside_strings_do_not_close_the_record(self, census):
        rec = census._first_record(_payload(_record(True, extra={"country": 'a "}" b'}))[:4096])
        assert rec is not None and rec["country"] == 'a "}" b'

    def test_a_non_json_body_returns_None(self, census):
        assert census._first_record(b"<html>403 Forbidden</html>") is None


class TestProbe:
    def test_presence_and_nonnull_are_reported_separately(self, census):
        """A key present with a NULL value still counts as PUBLISHED -- that is exactly the state
        the bronze INV-4 law preserves (absent stays null, and a real null stays null). Collapsing
        the two would make a published-but-null field look unpublished."""
        key = _key(401, 2025, "20260813")
        s3 = FakeS3({key: _payload(_record(True, nulls=("currentMYNetSales",)))})
        out = census.probe_key(s3, "b", key, 16384)
        assert out["ok"] is True
        assert out["keys_present"] == list(census.NET_COMMITMENT_KEYS)
        assert "currentMYNetSales" not in out["keys_nonnull"]
        assert len(out["keys_nonnull"]) == 4

    def test_an_old_shaped_payload_reports_none_present(self, census):
        key = _key(401, 2025, "20260601")
        s3 = FakeS3({key: _payload(_record(False))})
        out = census.probe_key(s3, "b", key, 16384)
        assert out["ok"] is True and out["keys_present"] == []

    def test_the_probe_is_a_RANGED_get(self, census):
        """The instrument must stay cheap enough to run over the whole prefix: one 16 KB range
        request per object, never a full download of a ~280 KB payload."""
        key = _key(401, 2025, "20260813")
        s3 = FakeS3({key: _payload(_record(True), copies=4000)})
        census.probe_key(s3, "b", key, 16384)
        assert s3.ranges == ["bytes=0-16383"]

    def test_a_missing_object_is_reported_not_raised(self, census):
        out = census.probe_key(FakeS3({}), "b", _key(401, 2025, "20260813"), 4096)
        assert out["ok"] is False and "GET failed" in out["note"]


class TestCensus:
    def _bucket(self):
        old, new = _payload(_record(False)), _payload(_record(True))
        return FakeS3({
            _key(401, 2025, "20260601"): old,
            _key(801, 2025, "20260601"): old,
            _key(401, 2025, "20260712"): new,
            _key(801, 2025, "20260712"): old,
            _key(401, 2025, "20260813"): new,
            _key(801, 2025, "20260813"): new,
            _key(401, 1990, None): new,          # an UNDATED backfill object
        })

    def test_it_splits_dated_from_undated_and_probes_only_the_dated(self, census):
        out = census.build_census(self._bucket(), "b", codes=None, head_bytes=16384,
                                  max_per_vintage=0)
        assert out["raw_objects_total"] == 7
        assert out["raw_objects_dated"] == 6
        assert out["raw_objects_undated"] == 1
        assert out["vintages"] == ["20260601", "20260712", "20260813"]
        assert sum(v["objects_probed"] for v in out["per_vintage"].values()) == 6

    def test_the_first_as_of_derivations_are_the_numbers_the_runbook_reads(self, census):
        out = census.build_census(self._bucket(), "b", codes=None, head_bytes=16384,
                                  max_per_vintage=0)
        assert out["first_as_of_with_any_field"] == "20260712"
        assert out["first_as_of_with_all_five"] == "20260712"
        assert set(out["first_as_of_per_field"].values()) == {"20260712"}
        assert out["per_vintage"]["20260601"]["objects_with_any"] == 0
        assert out["per_vintage"]["20260712"]["objects_with_any"] == 1
        assert out["per_vintage"]["20260813"]["objects_with_all_five"] == 2

    def test_per_commodity_first_vintage_is_per_commodity_never_averaged(self, census):
        """Frequency floors deny the tail: a slug that starts publishing later is a finding about
        THAT commodity, and it has to survive as its own row."""
        out = census.build_census(self._bucket(), "b", codes=None, head_bytes=16384,
                                  max_per_vintage=0)
        assert out["per_commodity_first_as_of"]["401"]["first_as_of_with_any"] == "20260712"
        assert out["per_commodity_first_as_of"]["801"]["first_as_of_with_any"] == "20260813"

    def test_a_code_filter_narrows_the_sweep(self, census):
        out = census.build_census(self._bucket(), "b", codes={401}, head_bytes=16384,
                                  max_per_vintage=0)
        assert sum(v["objects_probed"] for v in out["per_vintage"].values()) == 3

    def test_render_is_ascii_only(self, census):
        out = census.build_census(self._bucket(), "b", codes=None, head_bytes=16384,
                                  max_per_vintage=0)
        text = census.render(out)
        assert text.encode("ascii")
        assert "FIRST as_of carrying ALL five        : 20260712" in text


def test_the_tool_writes_nothing_it_was_not_asked_to():
    """A read-only instrument: the only put_object in the file is the operator-named --out."""
    src = _TOOL.read_text(encoding="utf-8")
    assert src.count("put_object") == 1
    assert "delete_object" not in src
    assert "register_job_definition" not in src
