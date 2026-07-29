"""PRICE_AND_PLAYBOOKS W2 -- the eight deterministic gates. Hermetic: synthetic frames, local
paths, no AWS, no Athena.

EVERY gate has BOTH a passing case AND a failing case. A gate that cannot fire is worse than no
gate: it reads green in a log and asserts nothing.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "futures_eod_gate", _REPO / "scripts" / "silver" / "futures_eod_gate.py")
G = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(G)

from leviathan.silver import futures_eod_contracts as FC  # noqa: E402


def _bdays(start: str, n: int) -> list[pd.Timestamp]:
    return list(pd.bdate_range(start, periods=n))


def rows(slug: str, month: str, dates, *, settle=None, close=None, low=None, high=None,
         volume=1000, oi=None, symbol=None) -> pd.DataFrame:
    rec = FC.contract_for(slug)
    n = len(dates)
    settle = [100.0] * n if settle is None else list(settle)
    close = settle if close is None else list(close)
    return pd.DataFrame({
        "trade_date": list(dates),
        "contract_month": [month] * n,
        "instrument_kind": ["futures"] * n,
        "raw_symbol": [symbol or f"{slug[:3]}{month}"] * n,
        "settle": settle,
        "settle_kind": [rec["settle_kind"]] * n,
        "open": close,
        "high": [s + 1.0 for s in settle] if high is None else list(high),
        "low": [s - 1.0 for s in settle] if low is None else list(low),
        "close": close,
        "volume": volume if isinstance(volume, list) else [volume] * n,
        "open_interest": oi if isinstance(oi, list) else [oi] * n,
        "unit": [rec["unit"]] * n,
        "currency": [rec["currency"]] * n,
        "expiry_date": [pd.NaT] * n,
        "source": [rec["source"]] * n,
        "dataset": ["GLBX.MDP3"] * n,
        "leviathan_slug": [slug] * n,
        "trade_year": [d.year for d in dates],
    })


@pytest.fixture
def eod() -> pd.DataFrame:
    """A small but STRUCTURALLY COMPLETE frame: GLBX settlement rows + IFEU close rows, holes in
    the deferred contract, one contract per slug."""
    d = _bdays("2026-01-05", 40)
    # F5: a real contract does NOT print every business day (ZCZ8: 110 bars against ~139 business
    # days). Keeping 2 of every 3 days makes distinct-trade-date strictly less than the span --
    # the state gate 4 asserts, and the state a forward fill would destroy.
    sparse_a = [x for i, x in enumerate(d) if i % 3]          # 27 dates over a 40-bday span
    sparse_b = [x for i, x in enumerate(d[:30]) if i % 3]     # 20 dates over a 30-bday span
    frames = [
        rows("corn_cbot", "2026-03", sparse_a, settle=np.linspace(400, 430, len(sparse_a)),
             oi=5000),
        rows("corn_cbot", "2026-12", sparse_b, settle=np.linspace(420, 450, len(sparse_b)),
             oi=200),
        rows("robusta_coffee", "2026-03", sparse_b, settle=np.linspace(3000, 3200, len(sparse_b))),
        rows("white_sugar", "2026-05", sparse_b, settle=np.linspace(500, 520, len(sparse_b))),
    ]
    for f in frames[2:]:
        f["source"] = "databento_ifeu_impact"
        f["dataset"] = "IFEU.IMPACT"
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
class TestGate1Uniqueness:
    def test_passes_on_a_clean_frame(self, eod):
        fails, rec = G.gate1_uniqueness(eod)
        assert fails == [] and rec["duplicate_keys"] == 0

    def test_fires_on_a_surviving_f2_double_bar(self, eod):
        dup = pd.concat([eod, eod.head(1)], ignore_index=True)
        fails, rec = G.gate1_uniqueness(dup)
        assert rec["duplicate_keys"] == 1
        assert any("hard fail" in f for f in fails)

    def test_reports_missing_columns(self):
        fails, _ = G.gate1_uniqueness(pd.DataFrame({"trade_date": [1]}))
        assert fails and "raw_symbol" in fails[0]

    def test_a_clean_frame_carries_no_cross_slug_advisory(self, eod):
        _, rec = G.gate1_uniqueness(eod)
        assert rec["cross_slug_symbol_advisory"] == []

    def test_the_cross_slug_advisory_fires_but_does_not_fail_the_gate(self, eod):
        """The ONE shape the widened F2 key lets through: one VENDOR symbol under two slugs on one
        date -- what a CONTRACT_MAP re-point leaves behind when the superseded partitions are not
        dropped. Reported, never failed: a deliberate correct re-map has the same shape."""
        d = _bdays("2026-01-05", 3)
        remapped = pd.concat([
            rows("corn_cbot", "2026-03", d, symbol="ZCH6"),
            rows("soybeans_cbot", "2026-03", d, symbol="ZCH6"),   # same vendor symbol, other slug
        ], ignore_index=True)
        fails, rec = G.gate1_uniqueness(remapped)
        assert fails == [], "the advisory must NOT fail the gate"
        adv = rec["cross_slug_symbol_advisory"]
        assert len(adv) == 3 and all(a["n_slugs"] == 2 for a in adv)
        assert adv[0]["slugs"] == ["corn_cbot", "soybeans_cbot"]
        assert "gate 1 WARN" in G.render_report(G.evaluate(eod=remapped, manifests=[], skip={2, 8}))

    def test_the_jse_month_label_shape_is_NOT_advised_on(self):
        """JSE raw_symbol is the sheet's expiry cell verbatim, so white and yellow maize BOTH carry
        'Dec-2026' on every session. An unscoped advisory would fire ~9x/day forever on correct
        data -- the exact alarm-fatigue shape. _MONTH_LABEL_SYMBOL_SOURCES excludes it."""
        d = _bdays("2026-01-05", 3)
        jse = pd.concat([
            rows("south_african_white_maize_jse", "2026-12", d, symbol="Dec-2026"),
            rows("south_african_yellow_maize_jse", "2026-12", d, symbol="Dec-2026"),
        ], ignore_index=True)
        assert set(jse["source"]) == {"jse_safex"}
        fails, rec = G.gate1_uniqueness(jse)
        assert fails == [] and rec["cross_slug_symbol_advisory"] == []


class TestGate2DroppedSymbols:
    def _manifest(self, root, year, dropped, outrights=5):
        return {"root": root, "year": year, "resolved_symbols": outrights + dropped,
                "outright_count": outrights, "dropped_count": dropped}

    def test_passes_when_every_root_dropped_something(self):
        mans = [self._manifest(r, 2026, 10) for r in G.ROOT_MAP]
        fails, rec = G.gate2_dropped_symbols(mans)
        assert fails == [] and rec["zero_roots"] == []

    def test_fires_on_a_zero_drop_root_glbx_included(self):
        mans = [self._manifest(r, 2026, 10) for r in G.ROOT_MAP]
        mans[0] = self._manifest(sorted(G.ROOT_MAP)[0], 2026, 0)
        # ...and use a root that appears exactly once so the per-root sum is zero too
        mans = [m for m in mans if m["root"] != sorted(G.ROOT_MAP)[0]]
        mans.append(self._manifest(sorted(G.ROOT_MAP)[0], 2026, 0))
        fails, rec = G.gate2_dropped_symbols(mans)
        assert any("did not run" in f for f in fails)
        assert rec["zero_roots"] == [sorted(G.ROOT_MAP)[0]]

    def test_fires_on_a_missing_root(self):
        mans = [self._manifest(r, 2026, 10) for r in list(G.ROOT_MAP)[:3]]
        fails, _ = G.gate2_dropped_symbols(mans)
        assert any("no manifest at all" in f for f in fails)

    def test_fires_on_no_manifests_at_all(self):
        fails, _ = G.gate2_dropped_symbols([])
        assert any("NO symbology manifests" in f for f in fails)

    def test_reads_manifests_from_a_local_dir(self, tmp_path):
        p = tmp_path / "dataset=glbx_mdp3" / "root=ZC" / "year=2016"
        p.mkdir(parents=True)
        (p / "symbology_ZC_2016.json").write_text(
            json.dumps(self._manifest("ZC", 2016, 893)), encoding="utf-8")
        mans = G.load_manifests(str(tmp_path))
        assert len(mans) == 1 and mans[0]["dropped_count"] == 893


class TestGate3BarCounts:
    def test_passes_within_tolerance(self, eod, monkeypatch):
        monkeypatch.setattr(G, "EXPECTED_BARS", {("ZC", 2026): 46})
        monkeypatch.setattr(G, "PARTIAL_YEARS", frozenset())
        fails, rec = G.gate3_bar_counts(eod)
        assert rec["rows"][0]["observed"] == 46 and rec["rows"][0]["gated"] is True
        assert fails == []

    def test_fires_when_a_root_lands_short(self, eod, monkeypatch):
        # "A root that lands 40% short means the outright filter over-dropped."
        monkeypatch.setattr(G, "EXPECTED_BARS", {("ZC", 2026): 85})
        monkeypatch.setattr(G, "PARTIAL_YEARS", frozenset())
        fails, _ = G.gate3_bar_counts(eod)
        assert any("bars vs expected 85" in f for f in fails)

    def test_the_partial_year_is_recorded_not_gated(self, eod, monkeypatch):
        monkeypatch.setattr(G, "EXPECTED_BARS", {("ZC", 2026): 99999})
        monkeypatch.setattr(G, "PARTIAL_YEARS", frozenset({2026}))
        fails, rec = G.gate3_bar_counts(eod)
        assert fails == [] and rec["rows"][0]["gated"] is False

    def test_the_shipped_table_covers_every_root_and_can_fire(self):
        # The constant is the plan's measured table; every root must appear, and at least one FULL
        # (gated) year per root -- otherwise the gate is decorative for that root.
        roots = {r for r, _y in G.EXPECTED_BARS}
        assert roots == set(G.ROOT_MAP)
        for root in roots:
            gated = [y for (r, y) in G.EXPECTED_BARS
                     if r == root and y not in G.PARTIAL_YEARS
                     and (r, y) not in G.RECORDED_NOT_GATED]
            assert gated, f"{root} has only ungated rows -- gate 3 could never fire on it"

    def test_every_gated_year_is_actually_fetched(self):
        """THE CONTRADICTION THAT MADE GATE 3 UNPASSABLE. ('KE', 2013) was gated at 74 bars, but
        ROOT_FIRST_DATE['KE'] is 2014-01-01 (plan: 2013 = 74 bars, 'usable from 2014'), so
        root_years never yields 2013 and the fetch job explicitly skips it -- the gate emitted
        'KE/2013: 0 bars vs expected 74 (-100.0%)' on a perfectly correct table. A GATED year must
        be a year the pipeline actually buys."""
        from leviathan.transforms.raw_to_bronze.databento_eod import root_years

        through = max(y for _r, y in G.EXPECTED_BARS)
        for (root, year) in sorted(G.EXPECTED_BARS):
            if year in G.PARTIAL_YEARS or (root, year) in G.RECORDED_NOT_GATED:
                continue
            assert year in root_years(root, through), (
                f"gate 3 gates {root}/{year}, but root_years({root}) never yields it -- the unit "
                f"is never fetched, so the assertion can only ever fail")

    def test_the_ke_2013_stub_is_recorded_but_not_gated(self):
        from leviathan.transforms.raw_to_bronze.databento_eod import root_years

        assert ("KE", 2013) in G.RECORDED_NOT_GATED
        assert G.EXPECTED_BARS[("KE", 2013)] == 74          # the plan's measurement, kept
        assert 2013 not in root_years("KE", 2026)
        # And against the REAL table an otherwise-correct frame does not trip gate 3 on it.
        df = rows("hard_red_winter_wheat_kcbt", "2016-12", _bdays("2016-01-04", 10))
        fails, rec = G.gate3_bar_counts(df)
        assert not any("KE/2013" in f for f in fails)
        assert any(r["root"] == "KE" and r["year"] == 2013 and r["gated"] is False
                   for r in rec["rows"])


class TestGate4NoForwardFill:
    def test_passes_when_deferred_contracts_have_holes(self, eod):
        fails, rec = G.gate4_no_forward_fill(eod, sample=5, min_rows=10)
        assert rec["sample_size"] >= 1
        assert fails == []

    def test_fires_when_every_business_day_is_present(self):
        # A contract quoted on EVERY business day of its span is the F5 forward-fill signature.
        d = _bdays("2026-01-05", 60)
        df = rows("corn_cbot", "2027-12", d, settle=np.linspace(400, 460, 60), oi=10)
        fails, rec = G.gate4_no_forward_fill(df, sample=5, min_rows=10)
        assert rec["sampled"][0]["filled"] is True
        assert any("something forward-filled" in f for f in fails)

    def test_reports_when_no_contract_is_long_enough(self, eod):
        fails, _ = G.gate4_no_forward_fill(eod, sample=5, min_rows=10_000)
        assert any("cannot sample deferred" in f for f in fails)


class TestGate5IfeuSanity:
    def test_passes_on_clean_ifeu_rows(self, eod):
        fails, rec = G.gate5_ifeu_sanity(eod)
        assert fails == []
        assert rec["rows"] == 40
        # The honest part: settle IS close on ICE, so clause 2 is degenerate and says so.
        assert rec["settle_is_close_frac"] == 1.0
        assert rec["degenerate_clause2"] is True

    def test_fires_when_settle_leaves_the_bar_range(self, eod):
        broken = eod.copy()
        mask = broken["leviathan_slug"] == "robusta_coffee"
        broken.loc[mask, "high"] = broken.loc[mask, "settle"] - 10.0
        broken.loc[mask, "low"] = broken.loc[mask, "settle"] - 20.0
        fails, rec = G.gate5_ifeu_sanity(broken)
        assert rec["in_band_frac"] < 1.0
        assert any("low <= settle <= high" in f for f in fails)

    def test_fires_on_a_price_scaling_defect(self, eod):
        # The clause that CAN fire on the data W2 actually buys: a close outside its own bar.
        broken = eod.copy()
        mask = broken["leviathan_slug"] == "white_sugar"
        broken.loc[mask, "close"] = broken.loc[mask, "high"] * 1000.0
        fails, _ = G.gate5_ifeu_sanity(broken)
        assert any("bar-internal consistency" in f for f in fails)

    def test_fires_when_close_and_settle_diverge_beyond_5pct(self, eod):
        # Load-bearing the moment a free ICE settlement reference lands and settle stops being close.
        broken = eod.copy()
        mask = broken["leviathan_slug"] == "robusta_coffee"
        broken.loc[mask, "close"] = broken.loc[mask, "settle"] * 1.2
        broken.loc[mask, "high"] = broken.loc[mask, "close"] + 1
        fails, rec = G.gate5_ifeu_sanity(broken)
        assert rec["degenerate_clause2"] is False
        assert any("abs(close-settle)" in f for f in fails)

    def test_reports_when_there_are_no_ifeu_rows(self, eod):
        fails, _ = G.gate5_ifeu_sanity(eod[eod["leviathan_slug"] == "corn_cbot"])
        assert any("no robusta / white-sugar rows" in f for f in fails)


class TestGate6CrossTab:
    def test_passes_on_the_declared_map(self, eod):
        fails, rec = G.gate6_settle_kind_cross_tab(eod)
        assert fails == []
        assert rec["observed"]["databento_glbx_mdp3"] == ["settlement"]
        assert rec["observed"]["databento_ifeu_impact"] == ["close"]

    def test_fires_when_a_glbx_row_is_labelled_close(self, eod):
        broken = eod.copy()
        broken.loc[0, "settle_kind"] = "close"
        fails, _ = G.gate6_settle_kind_cross_tab(broken)
        assert any("cross-tab must stay 1:1" in f or "!= declared" in f for f in fails)

    def test_fires_on_an_unmapped_source(self, eod):
        broken = eod.copy()
        broken.loc[0, "source"] = "databento_xnas_itch"
        fails, _ = G.gate6_settle_kind_cross_tab(broken)
        assert any("absent from CONTRACT_MAP" in f for f in fails)

    def test_settlement_labelled_rows_must_carry_a_settlement(self, eod):
        """settle_kind is MAP-DERIVED, so the label cross-tab passes with settle NULL on every
        GLBX row -- which is exactly what a ts_ref-vs-ts_event calendar skew in the statistics
        join produces. The registry's table-wide min_nonnull_frac cannot see it either: the ICE
        rows, where settle == close by construction, dilute a GLBX-only miss away."""
        broken = eod.copy()
        glbx = broken["settle_kind"].astype(str) == G.SETTLEMENT_KIND
        assert glbx.any(), "fixture must carry settlement rows"
        broken.loc[glbx, "settle"] = np.nan
        fails, rec = G.gate6_settle_kind_cross_tab(broken)
        assert any("carry a non-null settle" in f for f in fails)
        assert all(r["settle_nonnull_frac"] == 0.0 for r in rec["settlement_coverage"])

    def test_a_healthy_settlement_join_reports_full_coverage(self, eod):
        _fails, rec = G.gate6_settle_kind_cross_tab(eod)
        assert rec["settlement_coverage"], "GLBX rows must be reported per (root, year)"
        assert all(r["settle_nonnull_frac"] == 1.0 for r in rec["settlement_coverage"])


def _parity_dates() -> list[pd.Timestamp]:
    """30 quoted dates spread over a 40-business-day span -- sparse, so the same fixture also
    satisfies gate 4's no-forward-fill assertion."""
    return [x for i, x in enumerate(_bdays("2026-01-05", 40)) if i % 4]


def _parity_pair(*, drift: float = 0.0):
    """A 12-slug eod frame + the matching flat silver_futures_prices frame."""
    d = _parity_dates()
    n = len(d)
    half = n // 2
    eod_frames, flat_rows = [], []
    for slug in G.PARITY_SLUGS:
        near = np.linspace(100.0, 110.0, n)
        far = near * 1.10                      # the next delivery month sits 10% higher
        # BOTH activity metrics move together: the GLBX slugs roll by open interest and the ICE
        # ones by volume, so a fixture that only populated one would silently degrade half the set
        # to the nearest-month tie-break (exactly the F-L failure this gate exists to catch).
        front_first = [9000] * half + [10] * (n - half)
        front_second = [10] * half + [9000] * (n - half)
        eod_frames.append(rows(slug, "2026-03", d, settle=near, oi=front_first,
                               volume=front_first, symbol=f"{slug}-H"))
        eod_frames.append(rows(slug, "2026-05", d, settle=far, oi=front_second,
                               volume=front_second, symbol=f"{slug}-K"))
        # The flat continuous series follows the front contract and SPLICES at the roll.
        flat_close = list(near[:half] * (1 + drift)) + list(far[half:] * (1 + drift))
        flat_rows.append(pd.DataFrame({"date": d, "leviathan_slug": slug, "close": flat_close}))
    eod = pd.concat(eod_frames, ignore_index=True)
    eod["source"] = eod["leviathan_slug"].map(lambda s: FC.CONTRACT_MAP[s]["source"])
    eod["settle_kind"] = eod["leviathan_slug"].map(lambda s: FC.CONTRACT_MAP[s]["settle_kind"])
    return eod, pd.concat(flat_rows, ignore_index=True)


class TestGate7Parity:
    def test_passes_12_of_12_away_from_rolls(self):
        eod, flat = _parity_pair()
        fails, rec = G.gate7_front_month_parity(eod, flat)
        assert fails == [], fails
        assert len(rec["per_slug"]) == 12
        assert all(r["status"] == "OK" for r in rec["per_slug"])
        assert rec["roll_rule_version"]

    def test_roll_days_are_reported_not_asserted(self):
        eod, flat = _parity_pair()
        _fails, rec = G.gate7_front_month_parity(eod, flat)
        assert all(r["roll_days"] >= 1 for r in rec["per_slug"]), \
            "the front contract changes mid-window -- the roll must be DETECTED, not asserted away"

    def test_fires_on_a_systematic_level_divergence(self):
        eod, flat = _parity_pair(drift=0.05)     # 5% everywhere, not just at the roll
        fails, rec = G.gate7_front_month_parity(eod, flat)
        assert any("median |rel diff|" in f for f in fails)
        assert rec["per_slug"][0]["median_abs_rel"] > G.PARITY_MEDIAN_FLOOR

    def test_fires_when_a_slug_is_missing(self):
        eod, flat = _parity_pair()
        flat = flat[flat["leviathan_slug"] != "cocoa"]
        fails, _ = G.gate7_front_month_parity(eod, flat)
        assert any("cocoa" in f for f in fails)
        assert any("11/12" in f or "parity covered" in f for f in fails)

    def test_fires_on_an_empty_flat_frame(self):
        eod, _flat = _parity_pair()
        fails, _ = G.gate7_front_month_parity(eod, pd.DataFrame())
        assert fails


class TestGate8ChainHooks:
    def test_passes_against_the_real_repo(self):
        fails, rec = G.gate8_chain_hooks(_REPO)
        assert fails == [], fails
        assert rec["row_validator_wired"] is True
        assert rec["partition_mode"] == "registered" and rec["projection"] == "forbidden"
        # Both chains that publish this table are checked, not just the paid vendor one.
        assert set(rec["descriptors"]) == set(G._DAG_SCHEDULES)
        assert all(p["descriptor"] and p["rendered_input"] and p["rendered_schedule"]
                   for p in rec["descriptors"].values())
        # NOT 23:00 -- that is the yfinance futures_prices slot. See the descriptor notes.
        assert rec["crons"]["futures_eod_databento"].startswith("cron(0 8 ")
        assert rec["crons"]["futures_eod_free"].startswith("cron(30 22 ")
        assert len(set(rec["crons"].values())) == len(rec["crons"]), (
            "the two chains write the same partitions through the same object keys, so a shared "
            "cron would be a lost-update race")
        assert rec["emitted_commands"]

    def test_fires_when_the_row_validator_is_unwired(self, tmp_path):
        # Mirror just enough of the repo to make the producer-task check fail.
        import shutil
        repo = tmp_path / "repo"
        for rel in ("configs/silver/tables", "configs/silver/dags/_rendered", "jobs/batch",
                    "scripts/silver"):
            (repo / rel).mkdir(parents=True)
        shutil.copy(_REPO / "configs/silver/tables/silver_futures_eod.yaml",
                    repo / "configs/silver/tables/silver_futures_eod.yaml")
        for schedule in G._DAG_SCHEDULES:
            shutil.copy(_REPO / f"configs/silver/dags/{schedule}.json",
                        repo / f"configs/silver/dags/{schedule}.json")
        shutil.copy(_REPO / "scripts/silver/gen_sfn_inputs.py",
                    repo / "scripts/silver/gen_sfn_inputs.py")
        (repo / "jobs/batch/futures_eod_task.py").write_text(
            "build_partitioned_publish(df=df)\n", encoding="utf-8")
        fails, rec = G.gate8_chain_hooks(repo)
        assert rec["row_validator_wired"] is False
        assert any("row_validator=FC.lint_frame" in f for f in fails)

    def test_fires_when_the_descriptor_is_missing(self, tmp_path):
        import shutil
        repo = tmp_path / "repo"
        (repo / "configs/silver/tables").mkdir(parents=True)
        (repo / "jobs/batch").mkdir(parents=True)
        shutil.copy(_REPO / "configs/silver/tables/silver_futures_eod.yaml",
                    repo / "configs/silver/tables/silver_futures_eod.yaml")
        shutil.copy(_REPO / "jobs/batch/futures_eod_task.py",
                    repo / "jobs/batch/futures_eod_task.py")
        fails, _ = G.gate8_chain_hooks(repo)
        assert any("DAG descriptor" in f and "missing" in f for f in fails)


class TestEvaluate:
    def test_all_eight_run_and_pass_together(self, monkeypatch):
        monkeypatch.setattr(G, "EXPECTED_BARS", {("ZC", 2026): 60})
        monkeypatch.setattr(G, "PARTIAL_YEARS", frozenset())
        eod, flat = _parity_pair()
        # give the frame the IFEU rows gate 5 needs (sparse, like everything else)
        d = _parity_dates()
        n = len(d)
        ifeu = pd.concat([rows("robusta_coffee", "2026-03", d, settle=np.linspace(3000, 3100, n)),
                          rows("white_sugar", "2026-05", d, settle=np.linspace(500, 510, n))],
                         ignore_index=True)
        ifeu["source"] = ifeu["leviathan_slug"].map(lambda s: FC.CONTRACT_MAP[s]["source"])
        ifeu["settle_kind"] = "close"
        eod = pd.concat([eod, ifeu], ignore_index=True)
        mans = [{"root": r, "year": 2026, "resolved_symbols": 20, "outright_count": 5,
                 "dropped_count": 15} for r in G.ROOT_MAP]
        art = G.evaluate(eod=eod, manifests=mans, flat=flat, repo=_REPO)
        statuses = {k: v["status"] for k, v in art["gates"].items()}
        assert set(statuses) == {"1", "2", "3", "4", "5", "6", "7", "8"}
        assert art["verdict"] == "PASS", art["failures"]
        G.render_report(art).encode("ascii")

    def test_a_missing_input_SKIPS_and_fails_closed(self):
        art = G.evaluate(eod=None, manifests=None, flat=None, repo=_REPO)
        assert art["gates"]["1"]["status"] == "SKIPPED"
        assert art["verdict"] == "FAIL"
        assert any("SKIPPED" in f for f in art["failures"])

    def test_an_explicit_waiver_is_recorded_and_does_not_fail(self):
        art = G.evaluate(eod=None, manifests=None, flat=None, repo=_REPO,
                         skip={1, 2, 3, 4, 5, 6, 7})
        assert art["gates"]["1"]["status"] == "WAIVED"
        assert art["waived"] == [1, 2, 3, 4, 5, 6, 7]
        assert art["verdict"] == "PASS"

    def test_report_is_ascii_only_on_a_failing_run(self):
        art = G.evaluate(eod=None, manifests=None, flat=None, repo=_REPO)
        G.render_report(art).encode("ascii")


class TestLoaders:
    def test_hive_partition_columns_are_recovered_from_the_path(self, tmp_path, eod):
        # leviathan_slug / trade_year live ONLY in the path; a read that ignores it loses both.
        body = eod[[c for c in eod.columns if c not in ("leviathan_slug", "trade_year")]]
        p = tmp_path / "leviathan_slug=corn_cbot" / "trade_year=2026"
        p.mkdir(parents=True)
        body.head(5).to_parquet(p / "part-000.parquet", index=False)
        got = G.load_eod_frame(str(tmp_path))
        assert set(got["leviathan_slug"]) == {"corn_cbot"}
        assert set(got["trade_year"]) == {2026}

    def test_the_readonly_proxy_refuses_a_write_method(self, monkeypatch):
        class _Boto:
            @staticmethod
            def client(*_a, **_k):
                return object()

        monkeypatch.setitem(__import__("sys").modules, "boto3", _Boto)
        c = G._ReadOnlyClient("us-east-1")
        with pytest.raises(RuntimeError, match="READ-ONLY"):
            _ = c.put_object

    def test_no_athena_anywhere_in_the_gate(self):
        src = (_REPO / "scripts" / "silver" / "futures_eod_gate.py").read_text(encoding="utf-8")
        low = src.lower()
        assert "boto3.client(\"athena\"" not in low and "start_query_execution" not in low
        assert "pyarrow" in low
