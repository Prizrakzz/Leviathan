"""PRICE_AND_PLAYBOOKS W1a/W1b -- the FREE-leg chain: unit discovery, the host end-to-end, and the
``futures_eod_free`` DAG descriptor. Hermetic: no network, no AWS, no .xls writer.

The per-leg parse suites live next door (``tests/unit/test_{jse_safex,cepea,miax}_eod.py``); this
file is about the seams BETWEEN them -- that the venues share one task, one contract, one floor
mechanism and one schedule without contaminating each other.

W1c's Euronext/MATIF leg joined the same descriptor on 2026-08-05 (D-PR-24), which makes it FIVE
venues on one cron. It is the only one whose CAPTURE leaves the shared fetch jobdef -- a
client-rendered quote table needs headless Chromium, which the worker image does not carry -- and
the only one whose silver leg was already implemented and floor-bound for a year before anything
fired it. Its declaration record lives at ``configs/silver/dags/unarmed/futures_eod_browser.json``
and is pinned by ``tests/unit/silver/test_matif_arm_declaration.py``.
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
# W1c's live captures, and the DCE suite's settled_daily() -- the landed fixture is the NOT_READY
# night-session shape, which the producer refuses to land and the parser refuses to read.
_W1C_FIXTURES = _REPO / "tests" / "fixtures" / "w1c"
_DCE_SUITE = _load("tests/unit/test_dce_eod.py", "dce_suite")

# V2-4 (2026-09-02): the Bursa leg is PARKED -- the SHIPPED roster (task.BURSA_CODES) and map
# (bursa_fcpo.BURSA_CODE_MAP) are EMPTY because the palm slug carries the CME USD tape. The seams
# below are exercised under the HISTORICAL binding, injected explicitly, so none of them goes
# vacuous; the shipped state is pinned alongside.
_BURSA_SLUG = "malaysian_crude_palm_oil_cme"
_PARKED_SOURCES = frozenset({"bursa"})


def _inject_bursa(monkeypatch) -> None:
    from leviathan.transforms.bronze_to_silver import bursa_fcpo as BS
    from leviathan.transforms.raw_to_bronze import bursa_fcpo as BT

    monkeypatch.setattr(BT, "BURSA_CODE_MAP", {"FCPO": _BURSA_SLUG})
    monkeypatch.setattr(BS, "_BURSA_SLUGS", frozenset({_BURSA_SLUG}))
    monkeypatch.setattr(TASK, "BURSA_CODES", ("FCPO",))
    # ... and the slug's HISTORICAL price record (MYR/t, source bursa): the projection writes
    # unit/currency/source from CONTRACT_MAP and the leg's floor scopes rows by source equality,
    # so the whole former state is what the seam runs under -- never a MYR bulletin labelled USD.
    monkeypatch.setattr(FC, "CONTRACT_MAP", {
        **FC.CONTRACT_MAP,
        _BURSA_SLUG: {"unit": "MYR/t", "currency": "MYR", "settle_kind": "settlement",
                      "source": "bursa"}})


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
    """W1c's three legs landed their raw -> bronze half FIRST, and the read side of the host is
    where the two halves of that wave MEET: the unit readers and the DCE parser are one
    implementer's, the euronext/bursa builders the other's. Nothing else in the estate exercises
    that join, so a rename on either side would otherwise surface for the first time on Fargate.
    (The bronze -> silver half has since landed too -- see TestHostEndToEnd -- and the lazy import
    in ``_lazy_bronze`` stays exactly as it was: it is what let the halves land independently.)

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
        # PARKED (V2-4): the shipped roster is EMPTY, so the reader discovers nothing ...
        assert TASK.BURSA_CODES == ()
        assert TASK.bursa_units(s3, "b") == []
        # ... and under the historical code it still sees only its own prefix.
        assert TASK.bursa_units(s3, "b", codes=["FCPO"]) == [raw_bursa_key("FCPO", "2026-07-29")]

    def test_the_euronext_loader_reaches_the_other_halves_builder(self):
        key = raw_euronext_key("EBM-DPAR", "2026-07-29")
        s3 = FakeS3({key: (self._W1C / "euronext_ebm_table.html").read_bytes()})
        bronze, stats = TASK.load_euronext_capture(s3, "b", key)
        assert len(bronze) == 12                       # the 12 rendered EBM expiries
        assert set(bronze["leviathan_slug"]) == {"french_wheat_matif"}
        assert stats

    def test_the_bursa_loader_reaches_the_other_halves_builder(self, monkeypatch):
        key = raw_bursa_key("FCPO", "2026-07-29")
        s3 = FakeS3({key: (self._W1C / "bursa_fcpo_api_sample.json").read_bytes()})
        # SHIPPED (parked): the transform fails closed on the code before any row is built.
        with pytest.raises(ValueError, match="not one of"):
            TASK.load_bursa_capture(s3, "b", key)
        # Under the injected historical binding the seam is intact.
        _inject_bursa(monkeypatch)
        bronze, stats = TASK.load_bursa_capture(s3, "b", key)
        assert len(bronze) == 24                       # the 24 listed delivery months
        assert set(bronze["leviathan_slug"]) == {_BURSA_SLUG}
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
        for source in ("jse", "cepea", "miax", "dce", "euronext", "bursa"):
            assert self._run(monkeypatch, {}, "--source", source, "--mode", "backfill") == 1

    # -- W1c, end to end. The three browser legs run the SAME spine as the four W1a/W1b venues:
    # units from the landed prefix -> bronze -> the projection -> the two uniqueness assertions ->
    # gate 5 -> the dry-run publish. Nothing here launches a browser; the bytes are the live
    # 2026-07-29 captures.
    def test_dce_backfill_is_green(self, monkeypatch):
        """One settled variety-capture. The per-day floor is 0 BY DESIGN on this leg (only one of
        the five varieties has ever been captured live), so what is green here is the chain, not a
        completeness claim."""
        objects = {raw_dce_daily_key("p", "2026-07-29"): _DCE_SUITE.settled_daily()}
        assert self._run(monkeypatch, objects, "--source", "dce", "--mode", "backfill") == 0

    def test_a_dce_night_capture_never_becomes_a_board_of_zero_prices(self, monkeypatch):
        """The landed fixture verbatim: tradeDate already rolled to T+1 with every settle 0.0. The
        parser refuses it, the unit fails, and with no other unit the run exits 1 -- a whole
        zero-price board dated into the FUTURE is what an unguarded parse would publish."""
        objects = {raw_dce_daily_key("p", "2026-07-29"): _DCE_SUITE.DAILY_RAW}
        assert self._run(monkeypatch, objects, "--source", "dce", "--mode", "backfill") == 1

    def test_euronext_backfill_is_green_across_the_three_products(self, monkeypatch):
        """All three MATIF products render the identical table (same id, same 12-column thead), so
        the one landed EBM capture models the day; the slug comes from the KEY's product segment,
        never from the page, which is exactly what makes that modelling legal here."""
        html = (_W1C_FIXTURES / "euronext_ebm_table.html").read_bytes()
        objects = {raw_euronext_key(p, "2026-07-29"): html for p in TASK.EURONEXT_PRODUCTS}
        assert self._run(monkeypatch, objects, "--source", "euronext", "--mode", "backfill") == 0

    def test_a_single_product_euronext_day_trips_the_floor(self, monkeypatch):
        """THE failure mode this leg's floor exists for: three independent page renders in one run,
        and one of them silently not arriving. 12 rows is under the 24-row day floor."""
        html = (_W1C_FIXTURES / "euronext_ebm_table.html").read_bytes()
        objects = {raw_euronext_key("EBM-DPAR", "2026-07-29"): html}
        assert self._run(monkeypatch, objects, "--source", "euronext", "--mode", "backfill") == 1
        assert self._run(monkeypatch, objects, "--source", "euronext", "--mode", "backfill",
                         "--row-floor", "report") == 0

    def test_bursa_backfill_is_parked_on_the_shipped_roster(self, monkeypatch, caplog):
        """V2-4: BURSA_CODES == () so the leg selects NO unit and exits 1 -- 'no session unit(s)
        selected' -- before a single byte is read. A landed capture cannot be published by it."""
        objects = {raw_bursa_key("FCPO", "2026-07-29"):
                   (_W1C_FIXTURES / "bursa_fcpo_api_sample.json").read_bytes()}
        assert self._run(monkeypatch, objects, "--source", "bursa", "--mode", "backfill") == 1
        assert "no session unit(s) selected" in caplog.text

    def test_bursa_backfill_is_green_under_the_historical_binding(self, monkeypatch):
        _inject_bursa(monkeypatch)
        objects = {raw_bursa_key("FCPO", "2026-07-29"):
                   (_W1C_FIXTURES / "bursa_fcpo_api_sample.json").read_bytes()}
        assert self._run(monkeypatch, objects, "--source", "bursa", "--mode", "backfill") == 0

    def test_a_bursa_night_capture_never_publishes_as_the_daily_settlement(self, monkeypatch,
                                                                            caplog):
        """The after-hours body is a COMPLETE, plausible 24-month table with different prices, so
        the refusal has to be a hard error all the way out to the exit code. Exercised under the
        injected binding (V2-4 m4): on the shipped empty roster the run exits 1 BEFORE any parser
        runs, which would make this pin vacuous -- the refusal reason is asserted, not the code."""
        _inject_bursa(monkeypatch)
        objects = {raw_bursa_key("FCPO", "2026-07-29"):
                   (_W1C_FIXTURES / "bursa_fcpo_api_night_sample.json").read_bytes()}
        assert self._run(monkeypatch, objects, "--source", "bursa", "--mode", "backfill") == 1
        assert "T+1" in caplog.text, "the refusal must be the night-session guard, not the roster"

    # Every leg in the table, and the W1c three that were the last to arrive. The split is PINNED
    # rather than tolerated: a leg is legal either wired end to end, or declared-only while it
    # refuses to run and names the module still to be written. Both halves of W1c have landed, so
    # all eight are wired -- and the refusal path is still exercised, below, on a synthetic spec.
    _SILVER_COMPLETE = {"databento", "czce", "jse", "cepea", "miax", "dce", "euronext", "bursa"}
    _W1C = {"dce", "euronext", "bursa"}

    def test_every_declared_source_is_implemented_and_wired(self):
        assert set(TASK._SOURCE_SPECS) == self._SILVER_COMPLETE
        for name in sorted(self._SILVER_COMPLETE):
            spec = TASK._SOURCE_SPECS[name]
            assert spec.implemented, f"{name} is still declared-only"
            assert spec.todo == "", f"{name} is implemented but still carries a todo"
            assert TASK._silver_builder(name) is not None

    def test_the_w1c_builders_are_the_modules_the_todo_strings_named(self):
        """The two halves of W1c landed independently and the todo strings were the contract
        between them: module path + entry point, verbatim. This is that contract, discharged."""
        from leviathan.transforms.bronze_to_silver.bursa_fcpo import build_bursa_fcpo_silver
        from leviathan.transforms.bronze_to_silver.dce_eod import build_dce_eod_silver
        from leviathan.transforms.bronze_to_silver.euronext_eod import build_euronext_eod_silver

        assert TASK._silver_builder("dce") is build_dce_eod_silver
        assert TASK._silver_builder("euronext") is build_euronext_eod_silver
        assert TASK._silver_builder("bursa") is build_bursa_fcpo_silver

    def test_a_declared_only_source_refuses_before_any_aws_call(self, monkeypatch):
        """The yfinance lesson: a leg that is not wired must FAIL, never write nothing quietly.

        Every real leg is wired now, so this runs against a SYNTHETIC declared-only spec -- the
        guard has to keep working for whatever lands next, and it must refuse BEFORE any AWS
        client is built (which is why the S3 factory raises here)."""
        def _boom(region):
            raise AssertionError("must not build an S3 client for an unimplemented leg")

        monkeypatch.setattr(TASK, "get_thread_local_s3_client", _boom)
        pending = TASK._SOURCE_SPECS["czce"]._replace(
            name="shfe", job="futures_eod_shfe", publication_sources=("shfe",),
            implemented=False,
            todo="src/leviathan/transforms/bronze_to_silver/shfe_eod.py::build_shfe_eod_silver")
        monkeypatch.setitem(TASK._SOURCE_SPECS, "shfe", pending)
        assert TASK.main(["--source", "shfe", "--bucket", "b", "--aws-region", "us-east-1"]) == 1
        with pytest.raises(NotImplementedError, match="bronze_to_silver"):
            TASK._silver_builder("shfe")

    def test_each_leg_writes_only_its_own_publication_source(self):
        """The floor scopes rows by source EQUALITY, so a leg that wrote a foreign source value
        fails loudly instead of being counted into someone else's day."""
        for name, spec in TASK._SOURCE_SPECS.items():
            if name == "databento":
                continue
            for src in spec.publication_sources:
                assert src in FC.SOURCES
                slugs = {s for s, r in FC.CONTRACT_MAP.items() if r["source"] == src}
                if src in _PARKED_SOURCES:
                    # V2-4: a PARKED leg keeps its spec and its vocabulary but owns no slug.
                    assert not slugs, f"{src} is parked and must own no CONTRACT_MAP slug"
                    continue
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

    def test_one_cron_after_the_latest_of_the_five_publications(self):
        """CZCE 07:00 UTC, JSE ~15:00, EURONEXT ~16:30 (18:30 Paris, CEST; 17:30Z under CET),
        MIAX ~19:35, CEPEA ~21:00. 22:30 clears all five, and it is deliberately NOT 23:00 -- that
        is the yfinance futures_prices chain's slot.

        The Euronext leg is the one with a CEILING as well as a floor: its rendered table carries
        no date, so the capture is filed under the fetch process's own UTC date and the fire must
        also sit BEFORE 00:00Z. 22:30Z is 5-6 hours after the publish and 90 minutes before the
        date rolls, in both halves of the year."""
        d = self._desc()
        assert d["cron"] == "cron(30 22 ? * MON-FRI *)"
        other = json.loads((_DAGS / "futures_prices.json").read_text(encoding="utf-8"))
        assert d["cron"] != other["cron"]
        # the UTC-midnight ceiling is the reasoning the descriptor must carry, not folklore
        assert "00:00Z" in d["euronext_capture_window_note"]

    def test_its_own_census_baseline(self):
        d = self._desc()
        assert d["gate_baseline_uri"].endswith("rolling/futures_eod_free/census.json")
        dbn = json.loads((_DAGS / "futures_eod_databento.json").read_text(encoding="utf-8"))
        assert d["gate_baseline_uri"] != dbn["gate_baseline_uri"]

    # The five venues this chain carries: the four W1a/W1b legs plus the W1c Euronext/MATIF leg
    # armed 2026-08-05 (D-PR-24). Stated once, so a sixth leg fails in one place.
    _VENUES = ["cepea", "czce", "euronext", "jse", "miax"]

    def test_it_promotes_behind_the_gate_and_never_from_the_silver_phase(self):
        """ARMED 2026-07-29: canonical was hand-published for all four W1a/W1b venues first (czce
        34,164 / miax 1,554 / cepea 12,922 / jse 18), union gates PASSED, and the P10 question this
        test used to guard closed itself -- the floors held across the whole 2,628-file CZCE
        backfill.

        What still must hold, and is the reason this test survives the flip: the SILVER phase
        stages shadow for every venue, and canonical happens only in the PROMOTE phase, which the
        state machine runs after the gate. One promote task per venue, so one venue's bad day
        cannot promote another's rows -- which is exactly why arming a FIFTH venue (euronext,
        2026-08-05) adds a fifth promote task rather than widening an existing one."""
        assert self._desc()["promote_mode"] == "autonomous"
        rendered = self._rendered()
        for task in rendered["phases"]["silver"]["tasks"]:
            cmd = task["command"]
            assert cmd[cmd.index("--publish-mode") + 1] == "shadow"
        promote = rendered["promote"]["tasks"]
        assert len(promote) == len(self._VENUES)
        sources = []
        for task in promote:
            cmd = task["command"]
            assert cmd[cmd.index("--publish-mode") + 1] == "canonical"
            sources.append(cmd[cmd.index("--source") + 1])
        assert sorted(sources) == self._VENUES

    def test_one_fetch_and_one_silver_task_per_venue(self):
        rendered = self._rendered()
        fetches = {t["command"][0] for t in rendered["phases"]["fetch"]["tasks"]}
        assert fetches == {
            "jobs/ingest/fetch_czce_eod.py", "jobs/ingest/fetch_jse_safex_daily.py",
            "jobs/ingest/fetch_cepea_daily.py", "jobs/ingest/fetch_miax_eod.py",
            "jobs/ingest/fetch_euronext_eod.py"}
        sources = []
        for task in rendered["phases"]["silver"]["tasks"]:
            cmd = task["command"]
            assert cmd[0] == "jobs/batch/futures_eod_task.py"
            sources.append(cmd[cmd.index("--source") + 1])
        assert sorted(sources) == self._VENUES
        assert all(s in TASK._SOURCE_SPECS for s in sources)

    def test_only_the_euronext_capture_leaves_the_shared_fetch_jobdef(self):
        """FOUR venues share leviathan-dev-futures-eod-free-fetch; the Euronext capture cannot.
        Its quote table is decrypted and rendered by the page's own JS, so the producer drives
        headless Chromium -- and playwright + Chromium live in docker/leviathan_browser, not in the
        worker image the shared fetch jobdef runs. A move back to the shared jobdef would fail on
        Fargate at import time on every single fire, so the split is asserted rather than assumed.

        The SILVER side does NOT split: raw -> bronze -> silver happens inside futures_eod_task.py
        on the one shared publisher, which is what keeps the self-promotion override legal."""
        rendered = self._rendered()
        by_jobdef = {}
        for t in rendered["phases"]["fetch"]["tasks"]:
            by_jobdef.setdefault(t["jobdef"], set()).add(t["command"][0])
        assert by_jobdef == {
            "leviathan-dev-futures-eod-free-fetch": {
                "jobs/ingest/fetch_czce_eod.py", "jobs/ingest/fetch_jse_safex_daily.py",
                "jobs/ingest/fetch_cepea_daily.py", "jobs/ingest/fetch_miax_eod.py"},
            "leviathan-dev-browser-runner": {"jobs/ingest/fetch_euronext_eod.py"},
        }
        assert {t["jobdef"] for t in rendered["phases"]["silver"]["tasks"]} == \
            {"leviathan-dev-futures-eod-silver"}

    def test_the_euronext_capture_carries_no_window(self):
        """Like CEPEA's, and for a stronger reason: the rendered page serves TODAY's quotes and
        publishes no date at all, so the raw key's as_of_date is the session's only authority and a
        lookback window would be meaningless. --skip-existing is the producer's default, so a
        re-fire inside the same UTC day costs no browser launch."""
        rendered = self._rendered()
        euronext = [t for t in rendered["phases"]["fetch"]["tasks"]
                    if t["command"][0].endswith("fetch_euronext_eod.py")][0]
        assert euronext["command"] == ["jobs/ingest/fetch_euronext_eod.py"]
        assert euronext["queue"] == "leviathan-dev-queue-ondemand"   # never the SPOT queue
        assert euronext["env"] == []

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
