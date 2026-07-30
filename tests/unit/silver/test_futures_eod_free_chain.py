"""PRICE_AND_PLAYBOOKS W1a/W1b -- the FREE-leg chain: unit discovery, the host end-to-end, and the
``futures_eod_free`` DAG descriptor. Hermetic: no network, no AWS, no .xls writer.

The per-leg parse suites live next door (``tests/unit/test_{jse_safex,cepea,miax}_eod.py``); this
file is about the seams BETWEEN them -- that four venues share one task, one contract, one floor
mechanism and one schedule without contaminating each other.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.storage.paths import (
    raw_bursa_key,
    raw_cepea_wayback_key,
    raw_cepea_widget_key,
    raw_dce_daily_key,
    raw_dce_history_key,
    raw_euronext_key,
    raw_jse_safex_key,
    raw_miax_key,
)
from leviathan.transforms.raw_to_bronze import jse_safex as JT

_REPO = Path(__file__).resolve().parents[3]
_DAGS = _REPO / "configs" / "silver" / "dags"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_free")

# Reuse the per-leg fixtures rather than re-deriving them: one payload shape, one place.
_JSE_SUITE = _load("tests/unit/test_jse_safex_eod.py", "jse_suite")
_CEPEA_SUITE = _load("tests/unit/test_cepea_eod.py", "cepea_suite")
_MIAX_SUITE = _load("tests/unit/test_miax_eod.py", "miax_suite")


class FakeS3:
    """get_object / list_objects_v2 over an in-memory ``{key: bytes}`` map."""

    def __init__(self, objects: dict | None = None):
        self.objects = dict(objects or {})

    def get_object(self, *, Bucket, Key):  # noqa: N803 -- boto3 kwarg casing
        if Key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": _Body(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, **kw):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


# ---------------------------------------------------------------------------
class TestUnitDiscovery:
    """Units come from the LANDED raw prefix, never from a calendar. A venue holiday is simply an
    object that does not exist, so there is no curated holiday table to drift out of date."""

    def test_jse_units_are_captures_bounded_by_the_fetch_date(self):
        keys = {raw_jse_safex_key(d): b"" for d in ("2026-07-27", "2026-07-28", "2026-07-29")}
        s3 = FakeS3(keys)
        assert TASK.jse_units(s3, "b") == sorted(keys)
        assert TASK.jse_units(s3, "b", since="2026-07-29") == [raw_jse_safex_key("2026-07-29")]

    def test_miax_units_never_reach_below_the_csv_horizon(self):
        keys = {raw_miax_key(d): b"" for d in ("2025-09-09", "2026-01-05", "2026-07-28")}
        s3 = FakeS3(keys)
        assert TASK.miax_units(s3, "b") == sorted(keys)
        assert TASK.miax_units(s3, "b", since="2026-01-01") == [
            raw_miax_key("2026-01-05"), raw_miax_key("2026-07-28")]
        # A pre-horizon object, if one were ever landed by hand, is not selected.
        s3.objects[raw_miax_key("2024-07-29")] = b""
        assert raw_miax_key("2024-07-29") not in TASK.miax_units(s3, "b")

    def test_cepea_units_put_the_archive_first_and_the_widgets_last(self):
        """Load ORDER is load-bearing: the archive and the widgets overlap in time, and the silver
        step collapses identical (slug, date, settle) rows keeping the LAST -- so the fresher daily
        observation has to arrive after the snapshot."""
        objects = {
            raw_cepea_widget_key(23, "2026-07-28"): b"",
            raw_cepea_widget_key(77, "2026-07-28"): b"",
            raw_cepea_wayback_key(23, "20170708153249"): b"",
            raw_cepea_wayback_key(77, "20171027074000"): b"",
        }
        got = TASK.cepea_units(FakeS3(objects), "b")
        assert all("/history/" in k for k in got[:2])
        assert all("/history/" not in k for k in got[2:])

    def test_a_bounded_incremental_run_skips_the_whole_series_snapshots(self):
        objects = {
            raw_cepea_widget_key(23, "2026-07-28"): b"",
            raw_cepea_wayback_key(23, "20170708153249"): b"",
        }
        got = TASK.cepea_units(FakeS3(objects), "b", since="2026-07-01")
        assert got == [raw_cepea_widget_key(23, "2026-07-28")]

    def test_a_key_with_no_indicator_segment_refuses_to_guess(self):
        with pytest.raises(ValueError, match="indicator="):
            TASK._cepea_indicator_id("raw/production/source=cepea/widget.js")

    def test_a_missing_object_is_an_honest_file_not_found(self):
        s3 = FakeS3({})
        for loader, key in ((TASK.load_jse_capture, raw_jse_safex_key("2026-07-28")),
                            (TASK.load_cepea_capture, raw_cepea_widget_key(23, "2026-07-28")),
                            (TASK.load_miax_session, raw_miax_key("2026-07-28"))):
            with pytest.raises(FileNotFoundError):
                loader(s3, "b", key)


# ---------------------------------------------------------------------------
class TestW1cBrowserLegSeams:
    """W1c's three legs landed their raw -> bronze half only, and the read side of the host is
    where the two halves of that wave MEET: the unit readers and the DCE parser are one
    implementer's, the euronext/bursa builders the other's. Nothing else in the estate exercises
    that join, so a rename on either side would otherwise surface for the first time on Fargate.

    Nothing here launches a browser. The captures under ``tests/fixtures/w1c/`` are the real bytes
    the live 2026-07-29 session pulled."""

    _W1C = _REPO / "tests" / "fixtures" / "w1c"

    @staticmethod
    def _objects():
        return {
            raw_dce_history_key("p", 2016): b"",
            raw_dce_daily_key("p", "2026-07-29"): b"",
            raw_euronext_key("EBM-DPAR", "2026-07-29"): b"",
            raw_bursa_key("FCPO", "2026-07-29"): b"",
        }

    def test_each_reader_sees_only_its_own_prefix(self):
        s3 = FakeS3(self._objects())
        assert TASK.dce_units(s3, "b") == [raw_dce_history_key("p", 2016),
                                           raw_dce_daily_key("p", "2026-07-29")]
        assert TASK.euronext_units(s3, "b") == [raw_euronext_key("EBM-DPAR", "2026-07-29")]
        assert TASK.bursa_units(s3, "b") == [raw_bursa_key("FCPO", "2026-07-29")]

    def test_the_euronext_loader_reaches_the_other_halves_builder(self):
        key = raw_euronext_key("EBM-DPAR", "2026-07-29")
        s3 = FakeS3({key: (self._W1C / "euronext_ebm_table.html").read_bytes()})
        bronze, stats = TASK.load_euronext_capture(s3, "b", key)
        assert len(bronze) == 12                       # the 12 rendered EBM expiries
        assert set(bronze["leviathan_slug"]) == {"french_wheat_matif"}
        assert stats

    def test_the_bursa_loader_reaches_the_other_halves_builder(self):
        key = raw_bursa_key("FCPO", "2026-07-29")
        s3 = FakeS3({key: (self._W1C / "bursa_fcpo_api_sample.json").read_bytes()})
        bronze, stats = TASK.load_bursa_capture(s3, "b", key)
        assert len(bronze) == 24                       # the 24 listed delivery months
        assert set(bronze["leviathan_slug"]) == {"malaysian_crude_palm_oil_cme"}
        assert stats

    def test_a_key_missing_its_identity_segment_refuses_to_guess(self):
        for loader, key in ((TASK.load_euronext_capture, "raw/production/source=euronext/x.html"),
                            (TASK.load_bursa_capture, "raw/production/source=bursa/x.json")):
            with pytest.raises(ValueError, match="product=|code="):
                loader(FakeS3(), "b", key)


# ---------------------------------------------------------------------------
class TestHostEndToEnd:
    """main() over a fake S3: units -> bronze -> silver -> the two uniqueness assertions -> gate 5
    -> the dry-run publish."""

    @staticmethod
    def _run(monkeypatch, objects, *args):
        monkeypatch.setattr(TASK, "get_thread_local_s3_client", lambda region: FakeS3(objects))
        return TASK.main(["--bucket", "b", "--aws-region", "us-east-1", *args])

    def test_miax_backfill_is_green(self, monkeypatch):
        objects = {raw_miax_key("2026-07-28"): _MIAX_SUITE.settlement_csv("7/28/26"),
                   raw_miax_key("2026-07-27"): _MIAX_SUITE.settlement_csv("7/27/26")}
        assert self._run(monkeypatch, objects, "--source", "miax", "--mode", "backfill") == 0

    def test_a_thin_miax_session_fails_the_run(self, monkeypatch):
        objects = {raw_miax_key("2026-07-28"): _MIAX_SUITE.settlement_csv(
            "7/28/26", outrights=_MIAX_SUITE._OUTRIGHTS[:4])}
        assert self._run(monkeypatch, objects, "--source", "miax", "--mode", "backfill") == 1
        assert self._run(monkeypatch, objects, "--source", "miax", "--mode", "backfill",
                         "--row-floor", "report") == 0

    def test_cepea_incremental_is_green_and_writes_exactly_two_rows(self, monkeypatch):
        objects = {
            raw_cepea_widget_key(23, "2026-07-29"): _CEPEA_SUITE.widget(23),
            raw_cepea_widget_key(77, "2026-07-29"): _CEPEA_SUITE.widget(77, value="65,22"),
        }
        assert self._run(monkeypatch, objects, "--source", "cepea", "--mode", "incremental",
                         "--since", "2026-07-01", "--no-merge") == 0

    def test_a_half_published_cepea_day_fails_the_equality(self, monkeypatch):
        objects = {raw_cepea_widget_key(23, "2026-07-29"): _CEPEA_SUITE.widget(23)}
        assert self._run(monkeypatch, objects, "--source", "cepea", "--mode", "incremental",
                         "--since", "2026-07-01", "--no-merge") == 1

    def test_jse_backfill_is_green(self, monkeypatch):
        """The OLE read is monkeypatched at the module seam -- no library here can WRITE a legacy
        .xls, and the seam exists for exactly this reason."""
        monkeypatch.setattr(JT, "read_grid", lambda payload: json.loads(payload.decode("utf-8")))
        objects = {raw_jse_safex_key("2026-07-28"):
                   json.dumps(_JSE_SUITE.grid("2026-07-27")).encode("utf-8")}
        assert self._run(monkeypatch, objects, "--source", "jse", "--mode", "backfill") == 0

    def test_no_landed_object_is_an_honest_failure_not_an_empty_publish(self, monkeypatch):
        for source in ("jse", "cepea", "miax"):
            assert self._run(monkeypatch, {}, "--source", source, "--mode", "backfill") == 1

    # The legs whose bronze -> silver projection exists, and the W1c legs whose raw -> bronze half
    # has landed while theirs has not. The split is PINNED rather than tolerated: a declared-only
    # leg is legal exactly while it refuses to run and names the module still to be written.
    _SILVER_COMPLETE = {"databento", "czce", "jse", "cepea", "miax"}
    _W1C_DECLARED = {"dce", "euronext", "bursa"}

    def test_every_shipped_source_is_implemented_and_the_rest_declare_it(self):
        assert set(TASK._SOURCE_SPECS) == self._SILVER_COMPLETE | self._W1C_DECLARED
        for name in sorted(self._SILVER_COMPLETE):
            spec = TASK._SOURCE_SPECS[name]
            assert spec.implemented, f"{name} is still declared-only"
            assert TASK._silver_builder(name) is not None
        for name in sorted(self._W1C_DECLARED):
            spec = TASK._SOURCE_SPECS[name]
            assert not spec.implemented, f"{name} claims to be implemented -- wire its builder"
            assert "bronze_to_silver" in spec.todo, f"{name}'s todo must name the module to write"
            with pytest.raises(NotImplementedError, match="bronze_to_silver"):
                TASK._silver_builder(name)

    def test_a_declared_only_source_refuses_before_any_aws_call(self, monkeypatch):
        """The yfinance lesson: a leg that is not wired must FAIL, never write nothing quietly."""
        for source in sorted(self._W1C_DECLARED):
            assert self._run(monkeypatch, {}, "--source", source, "--mode", "backfill") == 1

    def test_each_leg_writes_only_its_own_publication_source(self):
        """The floor scopes rows by source EQUALITY, so a leg that wrote a foreign source value
        fails loudly instead of being counted into someone else's day."""
        for name, spec in TASK._SOURCE_SPECS.items():
            if name == "databento":
                continue
            for src in spec.publication_sources:
                assert src in FC.SOURCES
                slugs = {s for s, r in FC.CONTRACT_MAP.items() if r["source"] == src}
                assert slugs, f"{src} has no CONTRACT_MAP slugs"


# ---------------------------------------------------------------------------
class TestDescriptor:
    @staticmethod
    def _desc():
        return json.loads((_DAGS / "futures_eod_free.json").read_text(encoding="utf-8"))

    @staticmethod
    def _rendered():
        return json.loads((_DAGS / "_rendered" / "futures_eod_free.input.json")
                          .read_text(encoding="utf-8"))

    def test_family_is_futures_eod_never_futures(self):
        """dag_catalog maps silver_futures_eod to its own family; the `silver_futures` prefix would
        swallow the LIVE yfinance table."""
        d = self._desc()
        assert d["family"] == "futures_eod" and d["schedule"] == "futures_eod_free"
        assert d["wave"] == 3 and d["publish_class"] == "A (registered)"

    def test_one_cron_after_the_latest_of_the_four_publications(self):
        """CZCE 07:00 UTC, JSE ~15:00, MIAX ~19:35, CEPEA ~21:00. 22:30 clears all four, and it is
        deliberately NOT 23:00 -- that is the yfinance futures_prices chain's slot."""
        d = self._desc()
        assert d["cron"] == "cron(30 22 ? * MON-FRI *)"
        other = json.loads((_DAGS / "futures_prices.json").read_text(encoding="utf-8"))
        assert d["cron"] != other["cron"]

    def test_its_own_census_baseline(self):
        d = self._desc()
        assert d["gate_baseline_uri"].endswith("rolling/futures_eod_free/census.json")
        dbn = json.loads((_DAGS / "futures_eod_databento.json").read_text(encoding="utf-8"))
        assert d["gate_baseline_uri"] != dbn["gate_baseline_uri"]

    def test_it_promotes_behind_the_gate_and_never_from_the_silver_phase(self):
        """ARMED 2026-07-29: canonical was hand-published for all four venues first (czce 34,164 /
        miax 1,554 / cepea 12,922 / jse 18), union gates PASSED, and the P10 question this test
        used to guard closed itself -- the floors held across the whole 2,628-file CZCE backfill.

        What still must hold, and is the reason this test survives the flip: the SILVER phase
        stages shadow for every venue, and canonical happens only in the PROMOTE phase, which the
        state machine runs after the gate. One promote task per venue, so one venue's bad day
        cannot promote another's rows."""
        assert self._desc()["promote_mode"] == "autonomous"
        rendered = self._rendered()
        for task in rendered["phases"]["silver"]["tasks"]:
            cmd = task["command"]
            assert cmd[cmd.index("--publish-mode") + 1] == "shadow"
        promote = rendered["promote"]["tasks"]
        assert len(promote) == 4
        sources = []
        for task in promote:
            cmd = task["command"]
            assert cmd[cmd.index("--publish-mode") + 1] == "canonical"
            sources.append(cmd[cmd.index("--source") + 1])
        assert sorted(sources) == ["cepea", "czce", "jse", "miax"]

    def test_one_fetch_and_one_silver_task_per_venue(self):
        rendered = self._rendered()
        fetches = {t["command"][0] for t in rendered["phases"]["fetch"]["tasks"]}
        assert fetches == {
            "jobs/ingest/fetch_czce_eod.py", "jobs/ingest/fetch_jse_safex_daily.py",
            "jobs/ingest/fetch_cepea_daily.py", "jobs/ingest/fetch_miax_eod.py"}
        sources = []
        for task in rendered["phases"]["silver"]["tasks"]:
            cmd = task["command"]
            assert cmd[0] == "jobs/batch/futures_eod_task.py"
            sources.append(cmd[cmd.index("--source") + 1])
        assert sorted(sources) == ["cepea", "czce", "jse", "miax"]
        assert all(s in TASK._SOURCE_SPECS for s in sources)

    def test_the_jse_fetch_carries_no_lookback_window(self):
        """Its --mode backfill raises NotImplementedError by design (plan gate 8): the portal object
        is overwritten daily and has no history at all."""
        rendered = self._rendered()
        jse = [t for t in rendered["phases"]["fetch"]["tasks"]
               if t["command"][0].endswith("fetch_jse_safex_daily.py")][0]
        assert "--lookback-days" not in jse["command"]
        assert jse["command"] == ["jobs/ingest/fetch_jse_safex_daily.py", "--mode", "incremental"]

    def test_every_referenced_script_exists(self):
        rendered = self._rendered()
        for phase in ("fetch", "silver"):
            for task in rendered["phases"][phase]["tasks"]:
                assert (_REPO / task["command"][0]).exists(), task["command"][0]

    def test_the_gate_targets_the_one_table(self):
        d = self._desc()
        assert d["gate_tables"] == ["silver_futures_eod"]
        assert d["retry"]["maximum_retry_attempts"] == 3
        assert d["retry"]["maximum_event_age_in_seconds"] == 86400
