"""PRICE_AND_PLAYBOOKS W1.0 -- silver_futures_eod surface tests. Pure/hermetic: no AWS, no LLM, no pg.

Covers the four things W1.0 actually ships and that a later wave could silently break:
  * the SERVING FENCE -- whitelist-absent, so the table is missing from the agent tool enum and every
    build_sql lookup fails closed with KeyError;
  * the THREE-WAY unit bind -- CONTRACT_MAP projection == the tracked lint constant == the card's
    unit_overrides, with drift in EACH of the three directions proven to fail the build;
  * the DAG-catalog mapping -- build_catalog raises on an unmapped table, so D1 without D2 is a
    build break, and the new family must not swallow the live yfinance table;
  * the F010 contract shape -- natural key, registered/forbidden/registered-partition, the INV-2
    column ORDER (declaration order IS writer order), and the nullability pair that makes a NULL
    contract_month legal only for the CEPEA cash references.
"""
from __future__ import annotations

import copy

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.silver import futures_eod_contracts as FC

TABLE = "silver_futures_eod"


# -- the serving fence ----------------------------------------------------------------------------
class TestFence:
    def test_registered_in_raw_yaml_but_whitelist_absent(self):
        # the card EXISTS (so the lint, the F010 reconcile and the DDL pins all have something to
        # bind), and is simultaneously fenced out of serving. Both halves matter: a fence over an
        # absent card would be a no-op symbol.
        doc = cc._load("numbers/tables.yaml")
        assert TABLE in (doc.get("tables") or {})
        assert TABLE in R.WHITELIST_ABSENT_DEFAULT

    def test_absent_from_the_served_registry_and_the_tool_enum(self):
        reg = R.load_registry()
        assert TABLE not in reg.tables
        # the agent's tool enum IS sorted(reg.tables) -- so the table cannot be named in a tool call.
        from leviathan.graphrag.numbers import agent as na
        assert TABLE not in na._visible_tables(reg)

    def test_build_sql_fails_closed(self):
        # every lookup for a whitelist-absent table raises KeyError -- fail-CLOSED, not empty rows.
        with pytest.raises(KeyError):
            R.load_registry().get(TABLE)
        with pytest.raises(KeyError):
            Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-01",
                                      commodity="corn_cbot", agg="latest"))

    def test_fence_stays_env_disjoint(self):
        # the code-default fence and the env kill-switch stay separate sets; the union happens once,
        # in load_registry. GRAPHRAG_NUMBERS_DISABLE remains the post-flip rollback lever.
        assert TABLE not in R._disabled_tables()


# -- the single-source map ------------------------------------------------------------------------
class TestContractMap:
    def test_covers_exactly_the_31_contract_slugs(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        slugs = {p.stem for p in (repo / "configs" / "commodities").glob("*.yaml")}
        assert set(FC.CONTRACT_MAP) == slugs
        assert len(FC.CONTRACT_MAP) == 31

    def test_vocabularies_are_clean(self):
        assert FC.lint_map() == []
        assert {r["settle_kind"] for r in FC.CONTRACT_MAP.values()} <= FC.SETTLE_KINDS
        assert {r["source"] for r in FC.CONTRACT_MAP.values()} <= FC.SOURCES

    def test_source_to_settle_kind_is_one_to_one(self):
        # the cross-tab the plan's post-ship verification asserts on real rows, enforced on the MAP so
        # a mislabeled row can never be authored: ICE is `close`, never `settlement`.
        by_source: dict[str, set] = {}
        for rec in FC.CONTRACT_MAP.values():
            by_source.setdefault(rec["source"], set()).add(rec["settle_kind"])
        assert all(len(v) == 1 for v in by_source.values()), by_source
        assert by_source["databento_glbx_mdp3"] == {"settlement"}
        assert by_source["databento_ifus_impact"] == {"close"}
        assert by_source["databento_ifeu_impact"] == {"close"}
        assert by_source["jse_safex"] == {"mark_to_market"}
        assert by_source["cepea"] == {"cash_index"}

    def test_cash_index_is_exactly_the_two_cepea_references(self):
        # only these rows may carry contract_month IS NULL (instrument_kind = cash_index).
        assert FC.CASH_INDEX_SLUGS == frozenset(
            {"brazilian_arabica_coffee", "campinas_corn_reference_bmf"})

    def test_contract_for_fails_closed_on_an_unmapped_slug(self):
        assert FC.contract_for("corn_cbot")["unit"] == "US cents/bushel"
        with pytest.raises(ValueError, match="missing from CONTRACT_MAP"):
            FC.contract_for("not_a_contract")


# -- the three-way unit bind ----------------------------------------------------------------------
def test_unit_map_three_way_equality():
    # single-source map projection == tracked lint constant == card unit_overrides. Three copies of
    # one fact, provably identical -- the FUTURES v1.5 lesson, at 31 slugs and ten currencies.
    assert FC.UNIT_MAP == cc._FUTURES_EOD_UNIT_OVERRIDES
    ov = cc._load("numbers/tables.yaml")["tables"][TABLE]["metrics"]["settle"]["unit_overrides"]
    assert ov == FC.UNIT_MAP


def test_check_futures_eod_green_on_the_live_config():
    assert cc.check_futures_eod() == []


def test_futures_eod_registered_in_main_lints():
    import inspect
    assert "check_futures_eod()" in inspect.getsource(cc.main)


class TestThreeWayDriftFails:
    """Each leg edited ALONE must fail the build. This is the whole point of the bind."""

    def test_card_only_drift_fails(self, monkeypatch):
        doc = cc._load("numbers/tables.yaml")
        doc["tables"][TABLE]["metrics"]["settle"]["unit_overrides"]["corn_cbot"] = "USD/bushel"
        monkeypatch.setattr(cc, "_load", lambda name: doc)
        assert any("unit_overrides" in e for e in cc.check_futures_eod())

    def test_map_only_drift_fails(self, monkeypatch):
        patched = dict(cc._FUTURES_EOD_UNIT_OVERRIDES)
        patched["rapeseed_oil_zce"] = "USD/metric ton"      # an FX conversion smuggled into the map
        monkeypatch.setattr(FC, "UNIT_MAP", patched)
        assert any("three-way drift" in e for e in cc.check_futures_eod())

    def test_lint_constant_only_drift_fails(self, monkeypatch):
        patched = dict(cc._FUTURES_EOD_UNIT_OVERRIDES)
        patched.pop("cocoa")
        monkeypatch.setattr(cc, "_FUTURES_EOD_UNIT_OVERRIDES", patched)
        errs = cc.check_futures_eod()
        assert any("unit_overrides" in e for e in errs) and any("three-way drift" in e for e in errs)

    def test_extra_served_metric_fails(self, monkeypatch):
        doc = cc._load("numbers/tables.yaml")
        doc["tables"][TABLE]["metrics"]["close"] = {"desc": "x"}
        monkeypatch.setattr(cc, "_load", lambda name: doc)
        assert any("settle-ONLY" in e for e in cc.check_futures_eod())

    def test_missing_card_fails(self, monkeypatch):
        monkeypatch.setattr(cc, "_load", lambda name: {"tables": {}})
        errs = cc.check_futures_eod()
        assert errs and "absent" in errs[0]

    def test_whitelist_regression_fails(self, monkeypatch):
        # lifting the fence without the W3 gate must fail the build, not quietly serve an empty table.
        monkeypatch.setattr(R, "WHITELIST_ABSENT_DEFAULT", frozenset())
        assert any("WHITELIST_ABSENT_DEFAULT" in e for e in cc.check_futures_eod())

    def test_dropping_a_served_dimension_or_the_partition_layout_fails(self, monkeypatch):
        # check_futures_eod is the ONLY lint that reads the RAW card while the table is registry-fenced
        # (check_numbers_schema_pins iterates load_registry(), which DROPS a whitelist-absent table), so
        # these five keys can only be pinned here pre-flip. Dropping settle_kind_col would otherwise
        # leave every lint green while an ICE session CLOSE started being cited as a settlement.
        for key in ("contract_month_col", "settle_kind_col", "currency_col", "partition_cols",
                    "year_col"):
            doc = cc._load("numbers/tables.yaml")
            doc["tables"][TABLE].pop(key)
            monkeypatch.setattr(cc, "_load", lambda name, _d=doc: _d)
            assert any(key in e for e in cc.check_futures_eod()), key
            monkeypatch.undo()

    def test_settle_kind_vocabulary_drift_fails(self, monkeypatch):
        bad = copy.deepcopy(FC.CONTRACT_MAP)
        bad["corn_cbot"]["settle_kind"] = "official"
        monkeypatch.setattr(FC, "CONTRACT_MAP", bad)
        assert any("settle_kind" in e for e in cc.check_futures_eod())

    def test_source_settle_kind_crosstab_drift_fails(self, monkeypatch):
        # an ICE row relabeled as a settlement -- the exact dishonesty settle_kind exists to prevent.
        bad = copy.deepcopy(FC.CONTRACT_MAP)
        bad["cocoa"]["settle_kind"] = "settlement"
        monkeypatch.setattr(FC, "CONTRACT_MAP", bad)
        assert any("1:1" in e for e in cc.check_futures_eod())


# -- the DAG catalog (D2) -------------------------------------------------------------------------
class TestDagCatalog:
    def test_build_catalog_maps_the_table_without_raising(self):
        from leviathan.silver.dag_catalog import FAMILY_LABELS, build_catalog, family_of
        assert family_of(TABLE) == "futures_eod"
        catalog = build_catalog()
        assert catalog["futures_eod"].tables == (TABLE,)
        assert FAMILY_LABELS["futures_eod"]                     # a runbook-facing label exists
        assert catalog["futures_eod"].backfillable is True

    def test_the_new_rule_does_not_swallow_the_live_yfinance_table(self):
        # the ordering hazard: a ("silver_futures", ...) prefix would re-home silver_futures_prices.
        from leviathan.silver.dag_catalog import family_of
        assert family_of("silver_futures_prices") == "futures"

    def test_family_ceiling_folds_the_publication_lag_grace(self):
        from leviathan.silver.dag_catalog import build_catalog, effective_sla_lag_days
        from leviathan.silver.registry import load_registry
        c = load_registry().table(TABLE)
        assert c["freshness_sla"] == {"cadence": "daily", "max_lag_days": 5}
        lag, basis = effective_sla_lag_days(c)
        assert (lag, basis) == (6, "registry.max_lag_days")     # 5 explicit + 1 publication lag
        assert build_catalog()["futures_eod"].max_sla_lag_days == 6


# -- the F010 contract shape ----------------------------------------------------------------------
class TestRegistryContract:
    @pytest.fixture(scope="class")
    def contract(self):
        from leviathan.silver.registry import load_registry
        return load_registry().table(TABLE)

    def test_identity_and_storm_safe_layout(self, contract):
        assert contract["layer"] == "silver" and contract["lifecycle_class"] == "source"
        assert contract["s3_root"] == "s3://leviathan-dev-shahem-001/silver/futures_eod"
        assert contract["layout"] == "partitioned"
        assert contract["partition_mode"] == "registered"
        assert contract["projection"] == "forbidden"           # NEVER the LIST-storm grid
        assert contract["write_mode"] == "registered-partition"
        assert [pk["name"] for pk in contract["partition_keys"]] == ["leviathan_slug", "trade_year"]
        assert not any(pk["projected"] for pk in contract["partition_keys"])
        assert contract["vintage_retention"] == "latest-only"  # prices do not revise

    def test_natural_key_and_value_columns(self, contract):
        assert contract["natural_key"] == ["leviathan_slug", "contract_month", "trade_date"]
        assert contract["value_columns"] == ["settle"]
        assert contract["min_nonnull_frac"] == 0.5
        # required_nonnull is deliberately NOT the natural key: contract_month is a KEY member that is
        # legitimately NULL on the CEPEA cash rows (the WASDE 7-of-9 precedent).
        assert "contract_month" not in contract["required_nonnull"]
        assert set(contract["required_nonnull"]) == {
            "leviathan_slug", "trade_date", "instrument_kind", "settle_kind", "unit", "source"}

    def test_inv2_column_order_is_the_ratified_writer_order(self, contract):
        assert [c["name"] for c in contract["physical_columns"]] == [
            "trade_date", "contract_month", "instrument_kind", "raw_symbol", "settle", "settle_kind",
            "open", "high", "low", "close", "volume", "open_interest", "unit", "currency",
            "expiry_date", "source", "dataset"]
        # partition keys live ONLY in partition_keys -- declaring them physically too is the
        # silver_esr_compact clash that forced load_pg_numbers to grow a per-load footer probe.
        assert "leviathan_slug" not in [c["name"] for c in contract["physical_columns"]]
        assert "trade_year" not in [c["name"] for c in contract["physical_columns"]]

    def test_nullability_pins_the_two_facts_the_key_cannot_express(self, contract):
        by = {c["name"]: c for c in contract["physical_columns"]}
        # a NULL delivery month is LEGAL (the CEPEA cash refs) despite contract_month being in the key
        assert by["contract_month"]["nullable"] is True
        # ...while four non-key label columns are non-null by contract
        for cn in ("instrument_kind", "settle_kind", "unit", "source"):
            assert by[cn]["nullable"] is False, cn
        assert by["trade_date"]["nullable"] is False
        assert by["settle"]["nullable"] is True

    def test_no_roll_or_continuous_column_ever(self, contract):
        import re
        names = [c["name"] for c in contract["physical_columns"]]
        assert not [n for n in names
                    if re.search(r"(?i)front_month|roll|log_return|adjusted|continuous", n)]

    def test_pit_fields_match_the_card(self, contract):
        card = cc._load("numbers/tables.yaml")["tables"][TABLE]
        assert contract["knowledge_date_col"] == card["knowledge_date_col"] == "trade_date"
        assert contract["knowledge_semantics"] == card["knowledge_semantics"] == "data_date"
        assert contract["publication_lag_days"] == card["publication_lag_days"] == 1
        assert card["date_col_type"] == "timestamp"            # DP-5, the pg-parity requirement
        assert contract["consumers"] == "both"
        assert contract["numbers_ref"].endswith(f"#{TABLE}")

    def test_arrow_writer_schema_round_trips_from_the_contract(self, contract):
        import pyarrow as pa
        from leviathan.silver.flat_producer import pa_schema_from_contract
        sch = pa_schema_from_contract(contract)
        assert sch.names[0] == "trade_date" and sch.names[-1] == "dataset"
        assert sch.field("trade_date").type == pa.timestamp("us")
        assert sch.field("settle").type == pa.float64()
        assert sch.field("volume").type == pa.int64()
        assert sch.field("contract_month").nullable is True
        assert sch.field("unit").nullable is False


# -- D7 / D8 wiring -------------------------------------------------------------------------------
def test_pg_mirror_deferral_is_recorded_not_implied():
    # D7 / probe P8: absence from P1_TABLES IS the exclusion mechanism (there is no named exclusion
    # set), so the deferral has to be WRITTEN DOWN or it reads as an oversight. Load the module by
    # path (jobs/ is not an importable package) and assert both halves.
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "jobs" / "utils" / "load_pg_numbers.py"
    spec = importlib.util.spec_from_file_location("load_pg_numbers_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert TABLE not in mod.P1_TABLES                       # DEFERRED until the W2 size check
    assert TABLE in path.read_text(encoding="utf-8")        # ...and the reason is recorded there


def test_parity_sample_entry_present_and_fence_guarded():
    # D8: the entry lands with the schema so the panel is never vacuous at the flip, and the loop
    # must SKIP (not crash on) a table that is registered-but-fenced.
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "jobs" / "utils" / "numbers_parity.py"
    src = p.read_text(encoding="utf-8")
    assert '"silver_futures_eod": "corn_cbot"' in src
    assert "SKIP-FENCED" in src
    assert "if tid not in reg.tables:" in src


def test_parity_skips_a_sampled_table_that_has_no_pg_mirror():
    # The D7/D8 SEQUENCING guard: the W3 whitelist flip is a one-line registry edit, while the
    # P1_TABLES addition is a separate decision gated on a measured size check. Without this branch
    # the flip alone would point every leg at a pg relation that was never created -- _cmp books each
    # as a PG-ERR MISMATCH and main() returns 1, i.e. one deferred table reddens the WHOLE gate.
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "jobs" / "utils" / "numbers_parity.py"
    src = p.read_text(encoding="utf-8")
    assert "SKIP-UNMIRRORED" in src
    assert "if tid not in PG_MIRROR_TABLES:" in src
    spec = importlib.util.spec_from_file_location("numbers_parity_probe", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # imported from load_pg_numbers, so the allowlist and the guard can never drift...
    assert TABLE in mod.SAMPLE_COMMODITY and TABLE not in mod.PG_MIRROR_TABLES
    # ...and every OTHER sampled table IS mirrored, so the guard changes nothing else today.
    assert set(mod.SAMPLE_COMMODITY) - mod.PG_MIRROR_TABLES == {TABLE}


def test_gate_baseline_seed_d6_is_deferred_in_writing():
    # D6 is the one W1.0 deliverable NOT shipped: a rolling gate baseline is a census of legs that
    # exist, and this table has zero objects, zero registered partitions and cascade_ref: null. The
    # deferral is RECORDED at the site the plan names (the D7 discipline), never implied by silence.
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "jobs" / "audit" / "advance_rolling_census.py"
    src = p.read_text(encoding="utf-8")
    assert "W1.0 / D6" in src and "deferred to W1a" in src
    assert "cascade_census/rolling/futures_eod/census.json" in src


# -- the conditional invariant the schema cannot express ------------------------------------------
class TestLintFrame:
    """contract_month IS NULL if and ONLY if instrument_kind == 'cash_index'.

    ``required_nonnull`` is unconditional, so the contract can only say ``nullable: true`` -- which
    makes a dropped delivery month LEGAL. It is not: contract_month is part of the natural key
    [leviathan_slug, contract_month, trade_date], so N futures rows with a NULL month collapse to ONE
    key, and source_contracts ``duplicate_check: full`` cannot flag it (SQL treats each NULL as
    distinct). lint_frame is the enforcement, wired in as build_partitioned_publish(row_validator=)."""

    @staticmethod
    def _frame(**over):
        import pandas as pd
        base = {"leviathan_slug": ["corn_cbot", "brazilian_arabica_coffee"],
                "instrument_kind": ["futures", "cash_index"],
                "contract_month": ["2026-12", None],
                "unit": ["US cents/bushel", "BRL/60-kg bag"],
                "currency": ["USD", "BRL"],
                "settle_kind": ["settlement", "cash_index"],
                "source": ["databento_glbx_mdp3", "cepea"]}
        base.update(over)
        return pd.DataFrame(base)

    def test_a_mixed_futures_plus_cash_frame_is_clean(self):
        assert FC.lint_frame(self._frame()) == []

    def test_a_futures_row_with_a_null_contract_month_is_rejected(self):
        errs = FC.lint_frame(self._frame(contract_month=[None, None]))
        assert any("NULL contract_month" in e for e in errs)

    def test_a_cash_index_row_with_a_contract_month_is_rejected(self):
        errs = FC.lint_frame(self._frame(contract_month=["2026-12", "2026-12"]))
        assert any("NON-NULL contract_month" in e for e in errs)

    def test_a_blank_string_counts_as_null(self):
        # '' / '   ' are how a CSV-ish producer expresses "no month"; they must not sneak past.
        errs = FC.lint_frame(self._frame(contract_month=["   ", None]))
        assert any("NULL contract_month" in e for e in errs)

    def test_instrument_kind_must_match_the_maps_cash_index_slugs(self):
        errs = FC.lint_frame(self._frame(instrument_kind=["cash_index", "cash_index"],
                                         contract_month=[None, None]))
        assert any("corn_cbot: instrument_kind" in e for e in errs)

    def test_instrument_kind_vocabulary_is_closed(self):
        errs = FC.lint_frame(self._frame(instrument_kind=["future", "cash_index"]))
        assert any("vocabulary drift" in e for e in errs)

    def test_an_unmapped_slug_is_rejected(self):
        errs = FC.lint_frame(self._frame(leviathan_slug=["not_a_slug", "brazilian_arabica_coffee"]))
        assert any("unmapped leviathan_slug" in e for e in errs)

    def test_a_row_unit_that_disagrees_with_the_map_is_rejected(self):
        # the ROW-level end of the three-way unit bind: a producer cannot write a guessed unit.
        errs = FC.lint_frame(self._frame(unit=["USD/bushel", "BRL/60-kg bag"]))
        assert any("do not match" in e for e in errs)

    def test_missing_columns_and_empty_frames_are_handled(self):
        import pandas as pd
        assert FC.lint_frame(self._frame().iloc[0:0]) == []
        errs = FC.lint_frame(pd.DataFrame({"leviathan_slug": ["corn_cbot"]}))
        assert len(errs) == 1 and "missing required column" in errs[0]
