"""PRICE_AND_PLAYBOOKS W2 / D1 -- the Databento raw producer. Hermetic: a FAKE client, no network,
no AWS, no key.

Covers what a wrong producer would cost real money for:
  * the TWO-STEP resolve (parent -> instrument_id -> raw_symbol; the one-step form is a 422);
  * the outright filter feeding the buy, and the dropped-symbol count landing in the manifest;
  * the F-A hard fail;
  * the --cost-only pre-buy table assembled from a mocked get_cost, including the grand total and
    the zero-drop fail-closed;
  * ``symbols`` is never None (None means ALL_SYMBOLS -- the $140.31 mistake) and ``schema`` is
    always passed explicitly (the client default is ``trades``);
  * end-exclusive windows and the per-root first-usable date;
  * the raw key layout.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "fetch_databento_eod", _REPO / "jobs" / "ingest" / "fetch_databento_eod.py")
F = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(F)

from leviathan.storage.paths import raw_databento_key  # noqa: E402


class FakeSymbology:
    def __init__(self, owner):
        self.owner = owner

    def resolve(self, *, dataset, symbols, stype_in, stype_out, start_date, end_date):
        self.owner.resolve_calls.append(
            {"dataset": dataset, "symbols": symbols, "stype_in": stype_in,
             "stype_out": stype_out, "start_date": start_date, "end_date": end_date})
        if stype_in == "parent" and stype_out == "raw_symbol":
            raise AssertionError("parent -> raw_symbol is an HTTP 422; the recipe is TWO steps")
        if stype_in == "parent":
            return {"result": {symbols: [{"d0": start_date, "d1": end_date, "s": str(i)}
                                         for i in sorted(self.owner.id_to_symbol)]}}

        # a value may be "SYM" (full-window mapping) or ("SYM", d0, d1) for interval control
        # (the amended F-A check distinguishes disjoint re-listings from true overlaps).
        def _entry(i):
            v = self.owner.id_to_symbol[int(i)]
            if isinstance(v, tuple):
                s, d0, d1 = v
                return {"d0": d0, "d1": d1, "s": s}
            return {"d0": start_date, "d1": end_date, "s": v}

        return {"result": {str(i): [_entry(i)] for i in symbols}}


class FakeMetadata:
    # the exclusive available-end the real API names in its
    # data_end_date_after_available_end_date 422 (current-year windows clip to this)
    AVAILABLE_END = "2026-07-29"

    def __init__(self, owner):
        self.owner = owner

    def get_dataset_range(self, *, dataset):
        return {"start": "2010-06-06", "end": self.AVAILABLE_END}

    def get_cost(self, *, dataset, symbols, schema, stype_in, start, end, **kw):
        assert symbols is not None and len(symbols) > 0, "None/empty means ALL_SYMBOLS"
        assert schema in ("ohlcv-1d", "statistics"), "schema must always be explicit"
        assert "mode" not in kw, "the deprecated mode parameter must never be passed"
        self.owner.cost_calls.append({"dataset": dataset, "schema": schema, "n": len(symbols),
                                      "start": start, "end": end, "stype_in": stype_in})
        return self.owner.cost_per_symbol[schema] * len(symbols)


class FakeBatch:
    def __init__(self, owner):
        self.owner = owner

    def submit_job(self, **kw):
        self.owner.submits.append(kw)
        return {"id": f"JOB{len(self.owner.submits)}"}


class FakeClient:
    def __init__(self, id_to_symbol: dict, cost_per_symbol=None):
        self.id_to_symbol = id_to_symbol
        self.cost_per_symbol = cost_per_symbol or {"ohlcv-1d": 0.01, "statistics": 0.001}
        self.resolve_calls: list[dict] = []
        self.cost_calls: list[dict] = []
        self.submits: list[dict] = []
        self.symbology = FakeSymbology(self)
        self.metadata = FakeMetadata(self)
        self.batch = FakeBatch(self)


ZC_2016 = {101: "ZCH6", 102: "ZCZ6", 201: "ZCH6-ZCK6", 202: "T12Q6", 203: "ZC:BF H6-K6-N6"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(F.time, "sleep", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _fresh_dataset_end_cache(monkeypatch):
    # the module-level per-dataset available-end cache must not leak across tests
    monkeypatch.setattr(F, "_DATASET_END_CACHE", {})


class TestResolve:
    def test_two_step_recipe(self):
        c = FakeClient(ZC_2016)
        F.resolve_outrights(c, dataset="GLBX.MDP3", root="ZC", year=2016)
        steps = [(x["stype_in"], x["stype_out"]) for x in c.resolve_calls]
        assert steps[0] == ("parent", "instrument_id")
        assert all(s == ("instrument_id", "raw_symbol") for s in steps[1:])
        assert c.resolve_calls[0]["symbols"] == "ZC.FUT"

    def test_outrights_and_the_gate2_dropped_count(self):
        art = F.resolve_outrights(FakeClient(ZC_2016), dataset="GLBX.MDP3", root="ZC", year=2016)
        assert art["outright_symbols"] == ["ZCH6", "ZCZ6"]
        assert art["outright_count"] == 2
        assert art["dropped_count"] == 3        # NON-ZERO for GLBX too -- the gate-2 formulation
        assert "T12Q6" in art["dropped_symbols"]
        assert art["leviathan_slug"] == "corn_cbot"
        assert art["dataset_slug"] == "glbx_mdp3"

    def test_the_window_is_end_exclusive_and_clipped_to_the_first_usable_date(self):
        art = F.resolve_outrights(FakeClient(ZC_2016), dataset="GLBX.MDP3", root="ZC", year=2016)
        assert art["window"] == {"start": "2016-01-01", "end_exclusive": "2017-01-01"}
        assert F.year_window("ZC", 2010) == ("2010-06-06", "2011-01-01")
        assert F.year_window("KE", 2014) == ("2014-01-01", "2015-01-01")
        assert F.year_window("KC", 2018) == ("2018-12-23", "2019-01-01")

    def test_pre_coverage_year_is_refused(self):
        with pytest.raises(ValueError, match="empty window"):
            F.year_window("KE", 2012)

    def test_root_years_start_at_the_first_usable_year(self):
        assert F.root_years("ZC", 2026)[0] == 2010
        assert F.root_years("KE", 2026)[0] == 2014
        assert F.root_years("RC", 2026)[0] == 2018

    def test_fa_violation_is_a_hard_exit(self):
        # Two instrument ids resolving to the SAME outright raw_symbol.
        c = FakeClient({101: "ZCH6", 102: "ZCH6"})
        with pytest.raises(SystemExit, match="F-A VIOLATION"):
            F.resolve_outrights(c, dataset="GLBX.MDP3", root="ZC", year=2016)

    def test_fa_ignores_dropped_spread_symbols(self):
        # A spread symbol legitimately re-uses ids across the complex and is dropped anyway.
        c = FakeClient({101: "ZCH6", 201: "ZCH6-ZCK6", 202: "ZCH6-ZCK6"})
        art = F.resolve_outrights(c, dataset="GLBX.MDP3", root="ZC", year=2016)
        assert art["outright_symbols"] == ["ZCH6"]

    def test_fa_permits_disjoint_relisting_and_records_it(self):
        # The measured KEN4/KE-2021 shape (gate fired on real data 2026-07-28): GLBX recycles
        # instrument_ids, so the same outright appears on two ids with DISJOINT intervals.
        # Decodable (the DBNStore symbology map is interval-scoped) -> permitted + recorded.
        c = FakeClient({688493: ("KEN4", "2021-01-01", "2021-02-25"),
                        234273: ("KEN4", "2021-06-30", "2022-01-01"),
                        900001: "KEH1", 900002: "KEH1-KEK1"})
        art = F.resolve_outrights(c, dataset="GLBX.MDP3", root="KE", year=2021)
        assert "KEN4" in art["outright_symbols"]
        assert list(art["relisted_symbols"]) == ["KEN4"]
        assert [iv[2] for iv in art["relisted_symbols"]["KEN4"]] == ["688493", "234273"]

    def test_current_year_window_clips_to_the_dataset_available_end(self):
        # KE/2026 422'd on end_date=2027-01-01 (data_end_date_after_available_end_date);
        # the window must clip to metadata.get_dataset_range's exclusive end. Past years
        # are unaffected by construction (their Jan-1 end is earlier than the range end).
        c = FakeClient({101: "KEH6"})
        art = F.resolve_outrights(c, dataset="GLBX.MDP3", root="KE", year=2026)
        assert art["window"]["end_exclusive"] == FakeMetadata.AVAILABLE_END
        art16 = F.resolve_outrights(FakeClient(ZC_2016), dataset="GLBX.MDP3", root="ZC", year=2016)
        assert art16["window"]["end_exclusive"] == "2017-01-01"

    def test_poison_id_is_salvage_bisected_skipped_and_recorded(self):
        # The measured SB/2020 case: IFUS iid 6512548 ('SB   99   6512548' numeric-ID junk)
        # 500s the resolver ALONE on every window. The chunk must not die for it.
        class Boom(Exception):
            http_status = 500

        class PoisonSymbology(FakeSymbology):
            def resolve(self, *, symbols, stype_in, **kw):
                if stype_in == "instrument_id" and {int(s) for s in symbols} & {6512548}:
                    raise Boom()
                return super().resolve(symbols=symbols, stype_in=stype_in, **kw)

        c = FakeClient({101: "SB  FMH0020!", 102: "SB  FMK0020!", 6512548: "SB   99   6512548"})
        c.symbology = PoisonSymbology(c)
        art = F.resolve_outrights(c, dataset="IFUS.IMPACT", root="SB", year=2020)
        assert art["unresolvable_instrument_ids"] == ["6512548"]
        # the good ids survived the bisect
        assert art["outright_symbols"] == ["SB  FMH0020!", "SB  FMK0020!"]

    def test_mass_unresolvable_is_an_outage_and_fails_closed(self):
        # Every id 5xx-ing is an outage wearing a poison-id costume; skipping through it would
        # silently lose real symbology. With ALL ids failing there is no canary either.
        class Boom(Exception):
            http_status = 500

        class DeadSymbology(FakeSymbology):
            def resolve(self, *, stype_in, **kw):
                if stype_in == "instrument_id":
                    raise Boom()
                return super().resolve(stype_in=stype_in, **kw)

        c = FakeClient({100 + i: f"SB{code}0" for i, code in enumerate("FGHJK")})
        c.symbology = DeadSymbology(c)
        with pytest.raises(SystemExit, match="STEP-2 FAILURE"):
            F.resolve_outrights(c, dataset="IFUS.IMPACT", root="SB", year=2020)

    @staticmethod
    def _dense_junk_mapping(poison):
        # 48 UNIQUE good outrights (12 month codes x 4 delivery years -- repeated symbols would
        # trip the F-A overlap check) + the poison numeric-ID junk instruments.
        good = {}
        i = 0
        for yr in ("0022", "0023", "0024", "0025"):
            for code in "FGHJKMNQUVXZ":
                good[100 + i] = f"SB  FM{code}{yr}!"
                i += 1
        mapping = dict(good)
        mapping.update({p: f"SB   99   {p}" for p in poison})
        return mapping

    def test_dense_junk_year_passes_via_the_canary(self):
        # The measured SB/2022 shape: skips over the soft cap (9 of 57; cap = max(3, 57//20) = 3)
        # while the server answers every other id fine. The canary (re-resolving known-good ids)
        # proves health, so the unit proceeds with the skips recorded.
        class Boom(Exception):
            http_status = 500

        poison = set(range(7000, 7009))

        class DenseJunkSymbology(FakeSymbology):
            def resolve(self, *, symbols, stype_in, **kw):
                if stype_in == "instrument_id" and {int(s) for s in symbols} & poison:
                    raise Boom()
                return super().resolve(symbols=symbols, stype_in=stype_in, **kw)

        c = FakeClient(self._dense_junk_mapping(poison))
        c.symbology = DenseJunkSymbology(c)
        art = F.resolve_outrights(c, dataset="IFUS.IMPACT", root="SB", year=2022)
        assert len(art["unresolvable_instrument_ids"]) == 9
        assert art["outright_count"] == 48

    def test_dense_junk_with_dead_canary_is_an_outage(self):
        # Same density, but by canary time the server fails on EVERYTHING -> outage -> refuse.
        # The canary is the post-bisect call with exactly the 3 known-good ids; the fake flips
        # dead once the bisect has isolated all 9 poison singles.
        class Boom(Exception):
            http_status = 500

        poison = set(range(7000, 7009))

        class DeadByCanary(FakeSymbology):
            def __init__(self, owner):
                super().__init__(owner)
                self.poison_seen = set()   # DISTINCT poison singles (retries must not double-count)

            def resolve(self, *, symbols, stype_in, **kw):
                if stype_in == "instrument_id":
                    hit = {int(s) for s in symbols} & poison
                    if hit:
                        if len(symbols) == 1:
                            self.poison_seen.add(next(iter(hit)))
                        raise Boom()
                    if len(self.poison_seen) >= len(poison):
                        raise Boom()   # bisect done -> everything fails now, canary included
                return super().resolve(symbols=symbols, stype_in=stype_in, **kw)

        c = FakeClient(self._dense_junk_mapping(poison))
        c.symbology = DeadByCanary(c)
        with pytest.raises(SystemExit, match="outage"):
            F.resolve_outrights(c, dataset="IFUS.IMPACT", root="SB", year=2022)

    def test_fa_overlapping_relisting_is_still_a_hard_exit(self):
        # One symbol on two ids on the SAME date -- the case that genuinely breaks the
        # ohlcv/statistics join key and F2's dedupe rule. d1 is exclusive, so these overlap
        # by exactly one day.
        c = FakeClient({1: ("KEN4", "2021-01-01", "2021-07-01"),
                        2: ("KEN4", "2021-06-30", "2022-01-01")})
        with pytest.raises(SystemExit, match="OVERLAPPING"):
            F.resolve_outrights(c, dataset="GLBX.MDP3", root="KE", year=2021)

    def test_ice_root_resolves_its_fixed_width_symbols(self):
        c = FakeClient({1: "KC  FMZ0026!", 2: "KC  FMZ0026_Z!", 3: "SB   99   6512548"})
        art = F.resolve_outrights(c, dataset="IFUS.IMPACT", root="KC", year=2026)
        assert art["outright_symbols"] == ["KC  FMZ0026!"]
        assert art["dropped_count"] == 2

    def test_resolve_chunking_respects_the_cap(self, monkeypatch):
        monkeypatch.setattr(F, "RESOLVE_CHUNK", 2)
        c = FakeClient({100 + i: f"ZC{code}6" for i, code in enumerate("FGHJK")})
        F.resolve_outrights(c, dataset="GLBX.MDP3", root="ZC", year=2016)
        step2 = [x for x in c.resolve_calls if x["stype_in"] == "instrument_id"]
        assert len(step2) == 3 and all(len(x["symbols"]) <= 2 for x in step2)


class TestCostTable:
    def test_per_root_per_year_table_and_grand_total(self):
        c = FakeClient(ZC_2016, cost_per_symbol={"ohlcv-1d": 0.25, "statistics": 0.05})
        table = F.build_cost_table(c, [("GLBX.MDP3", "ZC", 2016), ("GLBX.MDP3", "ZC", 2017)])
        assert len(table["rows"]) == 2
        row = table["rows"][0]
        assert row["ohlcv_usd"] == pytest.approx(0.50)      # 2 outrights x 0.25
        assert row["statistics_usd"] == pytest.approx(0.10)
        assert row["total_usd"] == pytest.approx(0.60)
        assert table["grand_total_usd"] == pytest.approx(1.20)
        assert table["by_root"] == {"ZC": pytest.approx(1.20)}
        assert table["zero_drop_roots"] == []

    def test_statistics_is_glbx_only(self):
        c = FakeClient({1: "KC  FMZ0026!", 2: "KC  FMZ0026_Z!"})
        table = F.build_cost_table(c, [("IFUS.IMPACT", "KC", 2026)])
        assert table["statistics_usd"] == 0.0
        assert {x["schema"] for x in c.cost_calls} == {"ohlcv-1d"}

    def test_no_statistics_flag_drops_the_glbx_leg(self):
        c = FakeClient(ZC_2016)
        table = F.build_cost_table(c, [("GLBX.MDP3", "ZC", 2016)], with_statistics=False)
        assert table["statistics_usd"] == 0.0

    def test_cost_uses_the_same_symbols_and_window_as_the_submit(self):
        c = FakeClient(ZC_2016)
        art = F.resolve_outrights(c, dataset="GLBX.MDP3", root="ZC", year=2016)
        c.cost_calls.clear()
        F.cost_for_unit(c, art, "ohlcv-1d")
        F.submit_unit(c, art, "ohlcv-1d")
        cost, sub = c.cost_calls[0], c.submits[0]
        assert cost["dataset"] == sub["dataset"] and cost["schema"] == sub["schema"]
        assert cost["start"] == sub["start"] and cost["end"] == sub["end"]
        assert cost["n"] == len(sub["symbols"]) and cost["stype_in"] == sub["stype_in"]

    def test_zero_drop_is_recorded_as_a_gate2_breach(self):
        c = FakeClient({101: "ZCH6"})            # nothing to drop -> the filter did not run
        table = F.build_cost_table(c, [("GLBX.MDP3", "ZC", 2016)])
        assert table["zero_drop_roots"] == ["ZC"]
        assert "GATE-2 PRECONDITION BREACH" in F.render_cost_table(table)

    def test_per_dataset_subtotals_exist(self):
        """A grand total alone cannot distinguish 'the outright filter ran' from 'one dataset
        silently pulled the parent set'. The plan's per-dataset numbers (GLBX 2.7819 /
        IFUS 34.2813 / IFEU 6.1793) are only diffable against a per-dataset breakdown."""
        c = FakeClient(ZC_2016, cost_per_symbol={"ohlcv-1d": 0.25, "statistics": 0.05})
        table = F.build_cost_table(c, [("GLBX.MDP3", "ZC", 2016)])
        assert table["by_dataset"] == {"GLBX.MDP3": pytest.approx(0.60)}
        assert "per-DATASET totals" in F.render_cost_table(table)

    def test_window_override_prices_the_incremental_window(self):
        """``--mode incremental --cost-only`` must quote the incremental window, not the ~250x
        full-calendar-year one the resolve happens to carry."""
        c = FakeClient(ZC_2016)
        F.build_cost_table(c, [("GLBX.MDP3", "ZC", 2026)],
                           window_override=("2026-07-23", "2026-07-29"))
        assert {x["start"] for x in c.cost_calls} == {"2026-07-23"}
        assert {x["end"] for x in c.cost_calls} == {"2026-07-29"}

    def test_report_is_ascii_only(self):
        table = F.build_cost_table(FakeClient(ZC_2016), [("GLBX.MDP3", "ZC", 2016)])
        F.render_cost_table(table).encode("ascii")


class TestBudgetGate:
    """--cost-only is the PRE-BUY GATE. A gate that only prints the number is not a gate: the
    $140.31 parent pull the plan exists to prevent would print and return 0."""

    def _run(self, monkeypatch, argv, *, cost_per_symbol):
        client = FakeClient(ZC_2016, cost_per_symbol=cost_per_symbol)
        monkeypatch.setattr(F, "load_env", lambda *_a, **_k: None)
        monkeypatch.setattr(F, "get_required_env", lambda name: "us-east-1")
        monkeypatch.setattr(F, "load_api_key", lambda *_a, **_k: "not-a-real-key")
        monkeypatch.setattr(F, "make_client", lambda _key: client)
        return F.main(argv), client

    def test_a_quote_inside_the_ceiling_returns_zero(self, monkeypatch):
        rc, _ = self._run(monkeypatch,
                          ["--mode", "backfill", "--root", "ZC", "--year", "2016", "--cost-only"],
                          cost_per_symbol={"ohlcv-1d": 0.25, "statistics": 0.05})
        assert rc == 0

    def test_a_quote_over_the_ceiling_fails_closed(self, monkeypatch, capsys):
        rc, _ = self._run(monkeypatch,
                          ["--mode", "backfill", "--root", "ZC", "--year", "2016", "--cost-only",
                           "--max-usd", "1.0"],
                          cost_per_symbol={"ohlcv-1d": 40.0, "statistics": 1.0})
        assert rc == 1
        assert "BUDGET GATE FAILED" in capsys.readouterr().out

    def test_the_ceiling_itself_cannot_be_raised_past_the_credit_pool(self, monkeypatch):
        rc, client = self._run(monkeypatch,
                               ["--mode", "backfill", "--root", "ZC", "--year", "2016",
                                "--cost-only", "--max-usd", "500"],
                               cost_per_symbol={"ohlcv-1d": 0.25, "statistics": 0.05})
        assert rc == 1
        assert client.cost_calls == [], "it must refuse BEFORE quoting"

    def test_the_default_ceiling_sits_between_the_buy_and_the_parent_pull(self):
        assert 45.0 < F.DEFAULT_MAX_USD < 140.31
        assert F.HARD_CEILING_USD == 125.0

    def test_incremental_cost_only_quotes_the_incremental_window(self, monkeypatch):
        rc, client = self._run(
            monkeypatch,
            ["--mode", "incremental", "--root", "ZC", "--since", "2026-07-23", "--cost-only"],
            cost_per_symbol={"ohlcv-1d": 0.001, "statistics": 0.0001})
        assert rc == 0
        assert {x["start"] for x in client.cost_calls} == {"2026-07-23"}
        # END is exclusive and is today+1, never the calendar year end.
        assert all(not x["end"].endswith("-01-01") for x in client.cost_calls)

    def test_empty_symbol_set_costs_nothing_and_calls_nothing(self):
        c = FakeClient(ZC_2016)
        assert F.cost_for_unit(c, {"outright_symbols": [], "dataset": "GLBX.MDP3",
                                   "window": {"start": "a", "end_exclusive": "b"}},
                               "ohlcv-1d") == 0.0
        assert c.cost_calls == []


class TestSubmit:
    def test_submit_shape(self):
        c = FakeClient(ZC_2016)
        art = F.resolve_outrights(c, dataset="GLBX.MDP3", root="ZC", year=2016)
        F.submit_unit(c, art, "ohlcv-1d")
        sub = c.submits[0]
        assert sub["symbols"] == ["ZCH6", "ZCZ6"]
        assert sub["stype_in"] == "raw_symbol"
        assert sub["encoding"] == "dbn" and sub["compression"] == "zstd"
        assert sub["split_symbols"] is False and sub["split_duration"] == "none"
        assert sub["delivery"] == "download"

    def test_submit_refuses_an_empty_symbol_set(self):
        c = FakeClient(ZC_2016)
        with pytest.raises(ValueError, match="ALL_SYMBOLS"):
            F.submit_unit(c, {"outright_symbols": [], "dataset": "GLBX.MDP3", "root": "ZC",
                              "year": 2016, "window": {"start": "a", "end_exclusive": "b"}},
                          "ohlcv-1d")


class TestBackoff:
    def test_retries_a_429_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                exc = RuntimeError("rate limited")
                exc.http_status = 429
                raise exc
            return "ok"

        assert F.call_with_backoff(flaky) == "ok" and calls["n"] == 3

    def test_a_4xx_that_is_not_429_is_not_retried(self):
        def bad():
            exc = RuntimeError("unprocessable")
            exc.http_status = 422
            raise exc

        with pytest.raises(RuntimeError):
            F.call_with_backoff(bad)


class TestRawLayout:
    def test_key_layout(self):
        key = raw_databento_key("glbx_mdp3", "ZC", 2016, "ohlcv-1d_ZC_2016.dbn.zst")
        assert key == ("raw/production/source=databento/dataset=glbx_mdp3/root=ZC/year=2016/"
                       "ohlcv-1d_ZC_2016.dbn.zst")

    def test_single_character_root_survives(self):
        assert "/root=W/" in raw_databento_key("ifeu_impact", "W", 2026, "x.json")

    def test_filenames(self):
        assert F.symbology_filename("ZC", 2016) == "symbology_ZC_2016.json"
        assert F.payload_filename("ohlcv-1d", "ZC", 2016) == "ohlcv-1d_ZC_2016.dbn.zst"
        assert F.payload_filename("ohlcv-1d", "ZC", 2026, "20260728") == \
            "ohlcv-1d_ZC_20260728.dbn.zst"

    def test_the_filename_is_the_shared_one_the_silver_task_reads(self):
        """The writer and the reader must be the SAME function, not two that agree today: the
        nightly chain runs the fetch job and the silver task back to back in one Step Function."""
        from leviathan.storage.paths import (
            databento_payload_filename,
            databento_symbology_filename,
        )
        assert F.payload_filename is databento_payload_filename
        assert F.symbology_filename is databento_symbology_filename

    def test_min_file_size_floor_exists(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES
        # check_min_file_size returns SILENTLY when the source key is absent -- so the entry
        # existing is the whole guard.
        assert MIN_RAW_FILE_SIZES["databento"] > 0
        assert MIN_RAW_FILE_SIZES["databento_symbology"] > 0


class TestCli:
    def test_dry_run_prints_keys_and_touches_nothing(self, capsys):
        assert F.main(["--mode", "backfill", "--root", "ZC", "--year", "2016", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "dataset=glbx_mdp3/root=ZC/year=2016/symbology_ZC_2016.json" in out
        assert "ohlcv-1d_ZC_2016.dbn.zst" in out
        assert "statistics_ZC_2016.dbn.zst" in out

    def test_ice_dry_run_has_no_statistics_leg(self, capsys):
        assert F.main(["--mode", "backfill", "--root", "KC", "--year", "2026", "--dry-run"]) == 0
        assert "statistics_KC" not in capsys.readouterr().out

    def test_select_units_skips_pre_coverage_years(self):
        assert F.select_units(["KE"], [2012, 2014], 2026) == [("GLBX.MDP3", "KE", 2014)]

    def test_the_key_is_never_in_argv(self):
        src = (_REPO / "jobs" / "ingest" / "fetch_databento_eod.py").read_text(encoding="utf-8")
        assert "--api-key" not in src and "--key" not in src
        assert "DATABENTO_API_KEY" in src and "leviathan/dev/databento-api-key" in src

    def test_key_is_read_from_env_without_touching_secrets_manager(self, monkeypatch):
        monkeypatch.setenv("DATABENTO_API_KEY", "db-not-a-real-key")
        assert F.load_api_key() == "db-not-a-real-key"

    def test_key_value_never_reaches_the_log(self, monkeypatch, caplog):
        monkeypatch.setenv("DATABENTO_API_KEY", "db-secret-value-xyz")
        with caplog.at_level("INFO"):
            F.load_api_key()
        assert "db-secret-value-xyz" not in caplog.text
        assert "value not logged" in caplog.text

    def test_the_key_length_is_not_logged_either(self, monkeypatch, caplog):
        """A length is a free bit of a secret in a shared CloudWatch stream, and no operator can
        act on it. 'present' is the whole actionable content."""
        monkeypatch.setenv("DATABENTO_API_KEY", "db-secret-value-xyz")
        with caplog.at_level("INFO"):
            F.load_api_key()
        assert "len=" not in caplog.text
        assert str(len("db-secret-value-xyz")) not in caplog.text


class TestIdempotentSubmit:
    """(2026-07-29, measured) submit_job is BILLABLE and the vendor has no cancel endpoint, so a
    blind retry after a lost RESPONSE is a second charge. The serial backfill produced 3 such
    duplicates (~$2.25) and the nightly incremental would repeat it daily."""

    @staticmethod
    def _art():
        return {"dataset": "GLBX.MDP3", "root": "ZC", "year": 2016,
                "window": {"start": "2016-01-01", "end_exclusive": "2017-01-01"},
                "outright_symbols": ["ZCH6", "ZCZ6"]}

    def test_lost_response_reuses_the_job_instead_of_paying_twice(self):
        """The exact failure: the vendor ACCEPTED the submit, the response never arrived."""
        landed = {"id": "GLBX-X", "state": "queued", "dataset": "GLBX.MDP3",
                  "schema": "ohlcv-1d", "start": "2016-01-01", "symbols": ["ZCH6", "ZCZ6"]}

        class C:
            def __init__(self):
                self.submits = 0

            class _B:
                pass

            batch = None

        c = C()
        b = C._B()
        def submit(**kw):
            c.submits += 1
            raise TimeoutError("response lost after the server accepted it")
        b.submit_job = submit
        b.list_jobs = lambda *a, **k: [landed]
        c.batch = b
        got = F.submit_unit(c, self._art(), "ohlcv-1d")
        assert got["id"] == "GLBX-X", "must reuse the job the vendor already created"
        assert c.submits == 1, "must NOT re-submit -- that is the second charge"

    def test_genuine_failure_still_retries(self):
        """If the job truly did not land, the submit must be retried -- a missing payload costs
        the wave, which is worse than a duplicate."""
        class C:
            pass

        c, b = C(), C()
        state = {"n": 0}

        def submit(**kw):
            state["n"] += 1
            if state["n"] == 1:
                raise TimeoutError("nothing landed")
            return {"id": "GLBX-NEW"}

        b.submit_job = submit
        b.list_jobs = lambda *a, **k: []          # the vendor has no such job
        c.batch = b
        got = F.submit_unit(c, self._art(), "ohlcv-1d")
        assert got["id"] == "GLBX-NEW" and state["n"] == 2

    def test_reconciliation_does_not_match_a_different_unit(self):
        other = {"id": "GLBX-OTHER", "state": "queued", "dataset": "GLBX.MDP3",
                 "schema": "ohlcv-1d", "start": "2017-01-01", "symbols": ["ZCH7"]}
        expired = {"id": "GLBX-OLD", "state": "expired", "dataset": "GLBX.MDP3",
                   "schema": "ohlcv-1d", "start": "2016-01-01", "symbols": ["ZCH6"]}

        class C:
            pass

        c, b = C(), C()
        b.list_jobs = lambda *a, **k: [other, expired]
        c.batch = b
        # different year -> no match; expired -> never reused (its window has closed)
        assert F.find_submitted_job(c, self._art(), "ohlcv-1d") is None
        # a different SCHEMA at the same window is also a different unit
        same_window_other_schema = dict(other, start="2016-01-01", schema="statistics",
                                        symbols=["ZCH6"])
        b.list_jobs = lambda *a, **k: [same_window_other_schema]
        assert F.find_submitted_job(c, self._art(), "ohlcv-1d") is None

    def test_lookup_failure_falls_back_to_retry(self):
        class C:
            pass

        c, b = C(), C()
        b.list_jobs = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("list_jobs down"))
        c.batch = b
        assert F.find_submitted_job(c, self._art(), "ohlcv-1d") is None


# ---------------------------------------------------------------------------
# The existence probe FAILS CLOSED -- and here the argument is MONEY
# ---------------------------------------------------------------------------
class TestRawExistsFailsClosed:
    """``raw_exists`` is the only thing standing between a re-run and a re-SUBMIT.

    THE PAYLOAD IS RE-DERIVABLE -- Databento is a vendor, not a rolling window, and a done job
    re-downloads free for 30 days -- so this is NOT the EEX unrecoverability argument. The argument
    that bites here is that A FALSE "ABSENT" IS A PURCHASE: the statement after the probe is
    ``submit_unit``, a billable batch job, so a throttled HeadObject does not merely overwrite a
    good payload, it buys it again OUTSIDE the ``--cost-only`` pre-buy gate. IFUS is $34.28 and
    IFEU $6.18 against a $125 credit pool and a $45.00 recommended buy. An S3 hiccup must never be
    able to spend money."""

    @staticmethod
    def _client_error(code, status):
        from botocore.exceptions import ClientError
        return ClientError(
            {"Error": {"Code": code, "Message": "x"},
             "ResponseMetadata": {"HTTPStatusCode": status}},
            "HeadObject",
        )

    @staticmethod
    def _s3(monkeypatch, raiser):
        """Point ``raw_exists`` at a head_object driven by ``raiser(key)`` -> exception or None."""
        class _S3:
            def head_object(self, **kw):
                exc = raiser(kw["Key"])
                if exc is not None:
                    raise exc
                return {"ContentLength": 1}

        import leviathan.storage.s3 as S3MOD
        monkeypatch.setattr(S3MOD, "get_thread_local_s3_client", lambda region: _S3())

    @staticmethod
    def _expected():
        """``(symbology_key, ohlcv_key, statistics_key)`` for the ZC/2016 unit this class drives."""
        ds = "glbx_mdp3"
        return (
            raw_databento_key(ds, "ZC", 2016, F.symbology_filename("ZC", 2016)),
            raw_databento_key(ds, "ZC", 2016, F.payload_filename("ohlcv-1d", "ZC", 2016)),
            raw_databento_key(ds, "ZC", 2016, F.payload_filename("statistics", "ZC", 2016)),
        )

    def test_a_landed_object_is_reported_present(self, monkeypatch):
        self._s3(monkeypatch, lambda _key: None)
        assert F.raw_exists("b", "k", "us-east-1") is True

    @pytest.mark.parametrize("code,status", [("404", 404), ("NotFound", 404), ("NoSuchKey", 404)])
    def test_only_a_genuine_404_means_absent(self, monkeypatch, code, status):
        """HeadObject has no body, so botocore spells the missing-key case '404'/'NotFound' rather
        than the 'NoSuchKey' a GetObject would raise. All three are the same fact."""
        self._s3(monkeypatch, lambda _key: self._client_error(code, status))
        assert F.raw_exists("b", "k", "us-east-1") is False

    @pytest.mark.parametrize("code,status", [
        ("SlowDown", 503),
        ("InternalError", 500),
        ("ExpiredToken", 400),
        ("AccessDenied", 403),
        ("RequestTimeout", 400),
    ])
    def test_every_other_head_failure_RAISES_rather_than_fabricating_absence(
            self, monkeypatch, code, status):
        """Fail closed. Failing the unit costs a re-fire; reading a throttled head as 'absent'
        costs a re-buy that no pre-buy gate ever saw."""
        from botocore.exceptions import ClientError
        self._s3(monkeypatch, lambda _key: self._client_error(code, status))
        with pytest.raises(ClientError):
            F.raw_exists("b", "k", "us-east-1")

    @staticmethod
    def _drive(monkeypatch, tmp_path, raiser, *extra):
        """``main()`` for ONE unit (ZC/2016) through the REAL raw_exists over a stubbed head_object.
        Returns ``(exit_code, [landed keys], [submitted schemas])``."""
        landed: list[str] = []
        submitted: list[str] = []
        TestRawExistsFailsClosed._s3(monkeypatch, raiser)

        art = {"dataset": "GLBX.MDP3", "root": "ZC", "year": 2016,
               "outright_symbols": ["ZCH6", "ZCZ6"], "dropped_count": 7,
               "window": {"start": "2016-01-01", "end_exclusive": "2017-01-01"}}

        def _download(client, job_id, out_dir, **kw):
            path = tmp_path / f"{job_id}.dbn.zst"
            path.write_bytes(b"\x28\xb5\x2f\xfd" + b"x" * 512)
            return [str(path)]

        monkeypatch.setattr(F, "load_env", lambda *a, **k: None)
        monkeypatch.setattr(F, "load_api_key", lambda *a, **k: "not-a-real-key")
        monkeypatch.setattr(F, "make_client", lambda key: object())
        monkeypatch.setattr(F, "resolve_outrights", lambda client, **kw: dict(art))
        monkeypatch.setattr(F, "land_bytes",
                            lambda bucket, key, data, **kw: landed.append(key))
        monkeypatch.setattr(F, "submit_unit",
                            lambda client, artifact, schema: (submitted.append(schema)
                                                              or {"id": f"job-{schema}"}))
        monkeypatch.setattr(F, "wait_and_download", _download)
        rc = F.main(["--mode", "backfill", "--root", "ZC", "--year", "2016",
                     "--bucket", "test-bucket", "--aws-region", "us-east-1",
                     "--download-dir", str(tmp_path), *extra])
        return rc, landed, submitted

    def test_a_transient_head_failure_never_reaches_the_SUBMIT(self, monkeypatch, tmp_path):
        """THE ONE THAT MATTERS. The probe throttles, so the unit must fail LOUDLY (exit 1) with
        NOTHING submitted and no payload written. Under the old idiom this same head failure bought
        the payload again and overwrote the good one with it."""
        sym_key, ohlcv_key, stats_key = self._expected()
        rc, landed, submitted = self._drive(
            monkeypatch, tmp_path,
            lambda key: (None if key == sym_key else self._client_error("SlowDown", 503)))
        assert rc == 1
        assert submitted == [], "a throttled HeadObject must never become a billable re-buy"
        assert ohlcv_key not in landed and stats_key not in landed

    def test_the_same_drive_buys_and_lands_when_the_head_answers_404(self, monkeypatch, tmp_path):
        """The positive control, so the test above cannot pass vacuously: both GLBX schemas are
        submitted and landed when the probe can actually answer."""
        sym_key, ohlcv_key, stats_key = self._expected()
        rc, landed, submitted = self._drive(monkeypatch, tmp_path,
                                            lambda _key: self._client_error("404", 404))
        assert rc == 0
        assert submitted == ["ohlcv-1d", "statistics"]
        assert landed == [sym_key, ohlcv_key, stats_key]

    def test_an_already_landed_unit_still_short_circuits_without_buying(self, monkeypatch,
                                                                        tmp_path):
        """The skip path is unchanged and is the whole point of the probe: a head that ANSWERS
        'present' spends nothing."""
        sym_key, _ohlcv_key, _stats_key = self._expected()
        rc, landed, submitted = self._drive(monkeypatch, tmp_path, lambda _key: None)
        assert rc == 0 and submitted == []
        assert landed == [sym_key], "only the symbology artifact, which is re-derived every run"

    def test_force_overwrite_bypasses_the_probe_entirely(self, monkeypatch, tmp_path):
        """``--force-overwrite`` short-circuits before raw_exists is called, so a deliberate repair
        still works while S3 throttles HEADs."""
        rc, _landed, submitted = self._drive(monkeypatch, tmp_path,
                                             lambda _key: self._client_error("SlowDown", 503),
                                             "--force-overwrite")
        assert rc == 0 and submitted == ["ohlcv-1d", "statistics"]
