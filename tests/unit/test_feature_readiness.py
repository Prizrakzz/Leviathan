"""FR-001 feature-readiness harness -- offline unit tests (no AWS).

Every test is hermetic: synthetic local parquet FOOTERS (the F002 conftest AWS guard stays happy) +
injected footer/probe backends. Covers the nine E1 fixtures the plan names plus the source-key
resolution, the commodity-partition classifier, and the Athena-firewall no-fire guard.
"""
from __future__ import annotations

import inspect
import types

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from jobs.audit import feature_readiness as fr
from leviathan.silver.value_census import (
    GateRow,
    apply_vintage_waiver,
    census_column,
    evaluate_gate,
    evaluate_warnings,
    file_column_stat,
)


# --------------------------------------------------------------------------------------------------
# A faithful offline census_d builder -- mirrors value_census.census_one_table's per-group assembly
# (jobs/audit/value_census.py:187-266) so the harness consumes exactly the real dict shape.
# --------------------------------------------------------------------------------------------------
def _census_d(tmp_path, table, *, value_columns, min_frac, groups, knowledge_col=None, waiver=None):
    """groups == {commodity_slug: {column: pyarrow_array}} (each group == one parquet file)."""
    target_cols = list(dict.fromkeys(value_columns + ([knowledge_col] if knowledge_col else [])))
    stats_by_key: dict = {}
    group_files: dict = {}
    all_keys: list = []
    for i, (slug, cols) in enumerate(groups.items()):
        path = tmp_path / f"{table}_{slug}_{i}.parquet"
        pq.write_table(pa.table(cols), path)
        md = pq.read_metadata(path)
        key = str(path)
        stats_by_key[key] = {c: file_column_stat(md, c) for c in target_cols}
        label = f"commodity={slug}"
        group_files.setdefault(label, []).append(key)
        all_keys.append(key)

    census_by_column = {
        col: census_column([stats_by_key[k].get(col) for k in all_keys], col) for col in target_cols
    }
    per_group_rows: list = []
    per_group_warns: list = []
    group_summaries: dict = {}
    for label, keys in group_files.items():
        g_census = {c: census_column([stats_by_key[k].get(c) for k in keys], c) for c in value_columns}
        for r in evaluate_gate(table, g_census, value_columns, min_frac):
            per_group_rows.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                          f"[{label}] {r.detail}"))
        for r in evaluate_warnings(table, g_census, value_columns):
            per_group_warns.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                           f"[{label}] {r.detail}"))
        group_summaries[label] = {c: g_census[c].to_dict() for c in value_columns}

    vintage_rows = evaluate_gate(
        table, census_by_column, [], min_frac, knowledge_date_col=knowledge_col,
        knowledge_census=census_by_column.get(knowledge_col) if knowledge_col else None)
    vintage_rows, waived_rows = apply_vintage_waiver(vintage_rows, waiver)

    gate_rows = [r.to_dict() for r in (per_group_rows + list(vintage_rows))]
    warn_rows = [r.to_dict() for r in (per_group_warns + list(waived_rows))]
    d = {
        "table": table,
        "passed": len(gate_rows) == 0,
        "gate_rows": gate_rows,
        "warn_rows": warn_rows,
        "per_group_value_census": group_summaries,
        "columns": {name: c.to_dict() for name, c in census_by_column.items()},
        "files_sampled": len(all_keys),
    }
    if waiver:
        d["vintage_waiver"] = dict(waiver)
    return d


def _probe(*, exists=True, num_files=3, num_rows=100, columns=(), files=()):
    return types.SimpleNamespace(exists=exists, num_files=num_files, num_rows=num_rows,
                                 columns=tuple(columns), files=tuple(files))


def _fake_backends(*, probe=None, stage=None, census_d=None, dups=0):
    return fr.Backends(
        probe_fn=lambda t, root: probe if probe is not None else _probe(),
        stage_probe_fn=lambda t, ctx: stage if stage is not None else types.SimpleNamespace(
            status="green", detail="ok"),
        census_fn=lambda contract: (None, census_d if census_d is not None else
                                    {"gate_rows": [], "warn_rows": [], "per_group_value_census": {},
                                     "columns": {}, "passed": True, "files_sampled": 0}),
        key_dup_fn=lambda t, nk, files, region: dups,
    )


# --------------------------------------------------------------------------------------------------
# 0. Source-key resolution + commodity-partition classifier (enumeration, 2.0 / 2.0.1 / F1-C01).
# --------------------------------------------------------------------------------------------------
def test_source_key_resolution_is_registry_derived():
    from leviathan.silver import registry as sreg
    reg = sreg.load_registry()
    res = fr.build_source_key_resolution(reg)
    # esr resolves to the COMPACT serving table + carries the raw exact-prefix fence (2.0.1).
    esr = res["esr"]
    assert esr["table_name"] == "silver_esr_compact" and esr["s3_prefix"] == "silver/esr"
    assert esr["raw_source"]["s3_prefix"] == "silver/production/source=usda_esr"
    # weather trio prefix is the source= exact prefix (NEVER the bare silver/weather/ root).
    assert res["weather:chirps"]["s3_prefix"] == "silver/weather/source=chirps"
    assert res["weather:chirps"]["commodity_partitioned"] is True
    assert res["psd"]["s3_prefix"] == "silver/psd" and res["psd"]["commodity_partitioned"] is False


def test_commodity_partition_set_matches_plan():
    from leviathan.silver import registry as sreg
    reg = sreg.load_registry()
    per_group = {t for t in reg.tables if fr.commodity_partitioned(reg.table(t))}
    # F1-C01/F1V-01: exactly the weather trio + faostat + esr_compact partition by commodity=.
    assert {"silver_chirps", "silver_nasa_power", "silver_cpc_soil", "silver_production",
            "silver_esr_compact"} <= per_group
    # in-file-commodity flat tables + release-partitioned wasde are table_level.
    for t in ("silver_psd", "silver_modis_ndvi", "silver_wasde"):
        assert fr.commodity_partitioned(reg.table(t)) is False


# --------------------------------------------------------------------------------------------------
# 1. all-NaN commodity -> crit-4 RED (the CHIRPS class), clean commodity stays GREEN.
# --------------------------------------------------------------------------------------------------
def test_all_nan_commodity_crit4_red(tmp_path):
    d = _census_d(
        tmp_path, "silver_chirps", value_columns=["value"], min_frac=0.5,
        groups={
            "cotton": {"value": pa.array([None, None, None, None], type=pa.float64())},
            "corn_cbot": {"value": pa.array([1.0, 2.0, 3.0, 4.0], type=pa.float64())},
        })
    verdicts = fr.crit4_per_commodity("silver_chirps", d, ["cotton", "corn_cbot"],
                                      per_commodity="per_group")
    assert verdicts["cotton"][0] == fr.RED
    assert "100% NaN" in verdicts["cotton"][1]["hard_rows"][0]
    assert verdicts["corn_cbot"][0] == fr.GREEN
    # a commodity that was never sampled -> INDETERMINATE (never a silent pass).
    v2 = fr.crit4_per_commodity("silver_chirps", d, ["rough_rice_cbot"], per_commodity="per_group")
    assert v2["rough_rice_cbot"][0] == fr.INDETERMINATE


def test_table_level_crit4_shares_one_verdict(tmp_path):
    # in-file-commodity flat table (modis/psd class): one table-wide value verdict for every commodity.
    d = _census_d(tmp_path, "silver_psd", value_columns=["production_mt"], min_frac=0.5,
                  groups={"(flat)": {"production_mt": pa.array([None, None], type=pa.float64())}})
    # sample_groups labels a flat group '' -> our builder uses commodity=(flat); table_level ignores labels.
    out = fr.crit4_per_commodity("silver_psd", d, ["corn_cbot", "cotton"], per_commodity="table_level")
    assert out["corn_cbot"][0] == fr.RED and out["cotton"][0] == fr.RED


# --------------------------------------------------------------------------------------------------
# 2. single-vintage -> crit-5 RED, then WAIVED under a declared vintage_waiver mapping.
# --------------------------------------------------------------------------------------------------
def test_single_vintage_crit5_red_then_waived(tmp_path):
    groups = {"corn_cbot": {"value": pa.array([1.0, 2.0]),
                            "ingest_date": pa.array(["2026-01-20", "2026-01-20"])}}
    # no waiver -> the census fires single_vintage -> crit-5 RED.
    d = _census_d(tmp_path, "silver_production", value_columns=["value"], min_frac=0.5,
                  groups=groups, knowledge_col="ingest_date")
    contract_no_waiver = {"knowledge_date_col": "ingest_date", "vintage_retention": "latest-only"}
    v, ev = fr.crit5_vintage("silver_production", contract_no_waiver, d)
    assert v == fr.RED and ev["measured_distinct_lower_bound"] == 1

    # a declared vintage_waiver MAPPING (reason/approved) -> WAIVED (never silently green).
    waiver = {"reason": "FAOSTAT QCL annual latest-only", "approved": "2026-07-15 BF-W2 rider 6"}
    dw = _census_d(tmp_path, "silver_production", value_columns=["value"], min_frac=0.5,
                   groups=groups, knowledge_col="ingest_date", waiver=waiver)
    contract_waiver = {"knowledge_date_col": "ingest_date", "vintage_retention": "latest-only",
                       "vintage_waiver": waiver}
    v2, ev2 = fr.crit5_vintage("silver_production", contract_waiver, dw)
    assert v2 == fr.WAIVED and ev2["approved"] == "2026-07-15 BF-W2 rider 6"


def test_per_vintage_without_knowledge_col_is_indeterminate():
    # the silent-pass hole (plan 3.2): per-vintage retention but knowledge_date_col unset -> INDETERMINATE.
    contract = {"knowledge_date_col": None, "vintage_retention": "per-vintage"}
    v, ev = fr.crit5_vintage("silver_sagis_cec", contract, {"columns": {}})
    assert v == fr.INDETERMINATE and "F-KDC" in ev["detail"]


# --------------------------------------------------------------------------------------------------
# 3. ESR 2-vintage with vintage_dates_real=false -> WAIVED-BOUNDED + pit_valid_from (F1-C02).
# --------------------------------------------------------------------------------------------------
def test_esr_two_vintage_waived_bounded(tmp_path):
    d = _census_d(
        tmp_path, "silver_esr_compact", value_columns=["weekly_exports_1000mt"], min_frac=0.5,
        groups={"corn_cbot": {"weekly_exports_1000mt": pa.array([1.0, 2.0]),
                              "as_of_date": pa.array(["20260524", "20260712"])}},
        knowledge_col="as_of_date")
    # even with 2 distinct vintages the census would say GREEN; the harness OVERRIDES to WAIVED-BOUNDED.
    assert d["columns"]["as_of_date"]["distinct_lower_bound"] == 2
    contract = {"knowledge_date_col": "as_of_date", "vintage_retention": "per-week"}
    v, ev = fr.crit5_vintage("silver_esr_compact", contract, d)
    assert v == fr.WAIVED_BOUNDED
    assert ev["vintage_dates_real"] is False and ev["pit_valid_from"] == "2026-05-24"
    assert ev["measured_distinct_lower_bound"] == 2


# --------------------------------------------------------------------------------------------------
# 4. commodity=-partitioned probe -> crit-4 per_group (driven off registry partition_mode, F1-C01).
# --------------------------------------------------------------------------------------------------
def test_esr_compact_probe_is_per_group(tmp_path):
    from leviathan.silver import registry as sreg
    reg = sreg.load_registry()
    contract = reg.table("silver_esr_compact")
    assert fr.commodity_partitioned(contract) is True   # registered + commodity partition key
    # a hard row on one commodity group is scoped to that commodity, not the whole table.
    d = _census_d(
        tmp_path, "silver_esr_compact", value_columns=["weekly_exports_1000mt"], min_frac=0.5,
        groups={"corn_cbot": {"weekly_exports_1000mt": pa.array([1.0, 2.0, 3.0, 4.0])},
                "soybeans_cbot": {"weekly_exports_1000mt": pa.array([None, None], type=pa.float64())}})
    out = fr.crit4_per_commodity("silver_esr_compact", d, ["corn_cbot", "soybeans_cbot"],
                                 per_commodity="per_group")
    assert out["corn_cbot"][0] == fr.GREEN and out["soybeans_cbot"][0] == fr.RED


# --------------------------------------------------------------------------------------------------
# 5. missing calendar slug -> crit-7 RED (weather stage-window family).
# --------------------------------------------------------------------------------------------------
def test_missing_calendar_slug_crit7_red():
    # corn_cbot has regions but is (in this fixture) NOT a calendar slug -> the calendar gate fails.
    v, ev = fr.crit7_coverage("silver_chirps", "corn_cbot",
                              calendar_slugs={"soybeans_cbot"}, regions_present=True,
                              calendar_required=True)
    assert v == fr.RED and "crop_calendars" in ev["detail"]
    # a calendar slug WITH both calendar + regions -> GREEN.
    v2, _ = fr.crit7_coverage("silver_chirps", "corn_cbot",
                              calendar_slugs={"corn_cbot"}, regions_present=True, calendar_required=True)
    assert v2 == fr.GREEN
    # a non-weather family (calendar N/A) with regions present -> GREEN, calendar not required.
    v3, ev3 = fr.crit7_coverage("silver_psd", "corn_cbot", calendar_slugs=set(),
                                regions_present=True, calendar_required=False)
    assert v3 == fr.GREEN and ev3["calendar"] == "n/a"
    # regions missing -> RED even when calendar is not required.
    v4, _ = fr.crit7_coverage("silver_psd", "corn_cbot", calendar_slugs=set(),
                              regions_present=False, calendar_required=False)
    assert v4 == fr.RED


# --------------------------------------------------------------------------------------------------
# 6. missing required column -> crit-2 RED (through the real stage_feature_probe, F1V-06).
# --------------------------------------------------------------------------------------------------
def test_missing_required_column_crit2_red(monkeypatch):
    from jobs.audit import silver_rebuild_gate as g
    import leviathan.features.extractors as extractors

    # a present source whose footer schema is MISSING a registry-required column.
    monkeypatch.setattr(extractors, "probe_source", lambda key, loc, **k: _probe(
        columns=("commodity", "year"), num_files=2, num_rows=10))

    silver = types.SimpleNamespace(
        table=lambda t: {"s3_root": "s3://leviathan-dev-shahem-001/silver/chirps",
                         "natural_key": ["commodity", "year"], "value_columns": ["value"]},
        value_columns=lambda t: ["value"])
    ctx = g.GateContext(numbers_reg=None, silver_reg=silver)
    stage = g.stage_feature_probe("silver_chirps", ctx)
    assert stage.status == g.RED and "missing required columns" in stage.detail

    (c1v, _), (c2v, c2e) = fr.crit12_from_stage(stage.status, stage.detail,
                                                _probe(columns=("commodity", "year")))
    assert c1v == fr.GREEN               # the source EXISTS (crit-1 passes)...
    assert c2v == fr.RED and "value" in c2e["detail"]   # ...but the schema is incomplete (crit-2 RED)


def test_crit12_absent_source_is_present_fail():
    (c1v, _), (c2v, _) = fr.crit12_from_stage("red", "no parquet at s3://.../silver/nope",
                                              _probe(exists=False, num_files=0, num_rows=0))
    assert c1v == fr.RED and c2v == fr.INDETERMINATE


# --------------------------------------------------------------------------------------------------
# 7. projected-table probe path never constructs an Athena client.
# --------------------------------------------------------------------------------------------------
def test_projected_table_probe_never_constructs_athena_client(tmp_path, monkeypatch):
    import boto3
    made: list = []
    real_client = boto3.client

    def _spy(service, *a, **k):
        made.append(service)
        if service == "athena":
            raise AssertionError("FR-001 must NEVER construct an Athena client")
        return real_client(service, *a, **k)

    monkeypatch.setattr(boto3, "client", _spy)

    d = _census_d(tmp_path, "silver_production", value_columns=["value"], min_frac=0.5,
                  groups={"corn_cbot": {"value": pa.array([1.0, 2.0])}})
    h = fr.build_harness(skip_aws=False, backends=_fake_backends(
        probe=_probe(columns=("value", "commodity", "year"), files=()), census_d=d))
    rec = h.evaluate_table("silver_production")   # silver_production is projection.enabled TODAY
    assert "athena" not in made
    assert rec["athena_queries_issued"] == 0
    # structural: the harness module never references an Athena call site.
    src = inspect.getsource(fr).lower()
    assert "start_query_execution" not in src
    assert 'client("athena"' not in src and "client('athena'" not in src


# --------------------------------------------------------------------------------------------------
# 8. >500-fragment prefix aborts loudly (F1-SAFE-03).
# --------------------------------------------------------------------------------------------------
def test_over_500_fragments_aborts_loudly():
    with pytest.raises(fr.FragmentCapExceeded):
        fr.enforce_fragment_cap("silver_chirps", _probe(num_files=501))
    # at the cap is fine; one over is not.
    fr.enforce_fragment_cap("silver_chirps", _probe(num_files=500))


def test_evaluate_table_records_abort_on_decompaction():
    h = fr.build_harness(skip_aws=False, backends=_fake_backends(probe=_probe(num_files=9001)))
    rec = h.evaluate_table("silver_chirps")
    assert rec["criteria"]["crit1_present"][0] == fr.ABORTED
    assert "aborted" in rec


# --------------------------------------------------------------------------------------------------
# 9. pg-mirror table off-VPC -> crit-6 PENDING-IN-VPC (F1-SAFE-01); non-mirror -> INDETERMINATE.
# --------------------------------------------------------------------------------------------------
def test_pg_mirror_off_vpc_crit6_pending():
    v, ev = fr.crit6_vocabulary("silver_psd", {}, pg_mirror=True, pg_reachable=False)
    assert v == fr.PENDING_IN_VPC and "in-VPC" in ev["detail"]
    # a non-mirror feature/projection table -> footer-bounds INDETERMINATE (never an Athena DISTINCT).
    v2, ev2 = fr.crit6_vocabulary("silver_chirps", {}, pg_mirror=False, pg_reachable=False)
    assert v2 == fr.INDETERMINATE and "Athena DISTINCT" in ev2["detail"]


def test_pg_mirror_set_includes_the_serving_esr_and_p1_tables():
    mirror = fr._pg_mirror_tables()
    assert {"silver_psd", "silver_wasde", "silver_production", "silver_fred_fx", "silver_noaa_oni",
            "silver_esr_compact"} <= set(mirror)


# --------------------------------------------------------------------------------------------------
# firewall: a full sweep under _athena_firewall never fires, and stamps athena_queries_issued=0.
# --------------------------------------------------------------------------------------------------
def test_sweep_under_athena_firewall_does_not_fire(tmp_path):
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.cascade_census import _athena_firewall

    d = _census_d(tmp_path, "silver_chirps", value_columns=["value"], min_frac=0.5,
                  groups={"corn_cbot": {"value": pa.array([1.0, 2.0, 3.0, 4.0])}})
    h = fr.build_harness(skip_aws=False, backends=_fake_backends(
        probe=_probe(columns=("value",), files=()), census_d=d))
    with _athena_firewall():                       # raises if Q.athena_query_fn is invoked / Q.STATS non-empty
        rec = h.evaluate_table("silver_chirps")
    assert rec["athena_queries_issued"] == 0
    assert not Q.STATS


def test_machine_summary_is_keyed_by_table_commodity_criterion(tmp_path):
    d = _census_d(tmp_path, "silver_chirps", value_columns=["value"], min_frac=0.5,
                  groups={"corn_cbot": {"value": pa.array([1.0, 2.0, 3.0, 4.0])}})
    h = fr.build_harness(skip_aws=False, backends=_fake_backends(
        probe=_probe(columns=("value",), files=()), census_d=d))
    rec = h.evaluate_table("silver_chirps")
    fr.write_artifacts([rec], tmp_path)
    import json
    summ = json.loads((tmp_path / "f1_machine_summary.json").read_text(encoding="utf-8"))
    assert summ["schema_version"] == "f1_machine_summary/1"
    keys = {(r["table_name"], r["commodity"], r["criterion"]) for r in summ["records"]}
    assert len(keys) == len(summ["records"])          # the (table, commodity, criterion) key is unique
    # table-level criteria land on the __table__ sentinel; per-commodity on the slug.
    assert ("silver_chirps", fr.TABLE_LEVEL, "crit1_present") in keys
    assert ("silver_chirps", "corn_cbot", "crit7_coverage_declared") in keys


def test_skip_aws_run_is_offline_and_writes_artifacts(tmp_path):
    rc = fr.run(tmp_path, ["silver_chirps", "silver_psd"], skip_aws=True)
    assert rc == 0
    assert (tmp_path / "silver_chirps.json").exists()
    assert (tmp_path / "f1_machine_summary.json").exists()
    assert (tmp_path / "FEATURE_READINESS_REPORT.md").exists()
