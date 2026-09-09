"""SILVER-V001 -- canonical value census unit tests.

Builds synthetic local parquet files (no AWS -- the F002 conftest guard is happy)
and drives the pure footer-statistics census + gate. Covers: all-NaN failure,
single-vintage (ESR-collapse) failure, a healthy pass, sentinel saturation, and the
floor-calibration case that must NOT false-fail a legitimately-sparse source.
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.silver.value_census import (
    KIND_ALL_NAN,
    KIND_NONNULL_BELOW_FLOOR,
    KIND_SENTINEL_SATURATED,
    KIND_SINGLE_VINTAGE,
    census_column,
    build_table_result,
    evaluate_gate,
    evaluate_warnings,
    file_column_stat,
    resolve_floor,
)


def _write(tmp_path, name, table: pa.Table):
    path = tmp_path / name
    pq.write_table(table, path)
    return pq.read_metadata(path)


def _stat(metadata, column):
    return file_column_stat(metadata, column)


# ---------------------------------------------------------------------------
# The module makes no Athena/AWS call (INV-3 structural tripwire).
# ---------------------------------------------------------------------------
def test_module_has_no_athena_or_boto_dependency():
    import leviathan.silver.value_census as vc

    src = __import__("inspect").getsource(vc).lower()
    # no AWS client construction and no Athena query call anywhere in the module.
    assert "import boto3" not in src
    assert "start_query_execution" not in src
    assert 'client("athena"' not in src and "client('athena'" not in src


# ---------------------------------------------------------------------------
# all-NaN detection (the CHIRPS class).
# ---------------------------------------------------------------------------
def test_all_nan_float_column_fails(tmp_path):
    # A float column that is entirely null -> parquet writes null_count == num_rows,
    # has_min_max False -> the census reads effective non-null 0.
    tbl = pa.table({"value": pa.array([None, None, None, None], type=pa.float64())})
    md = _write(tmp_path, "allnan.parquet", tbl)

    census = census_column([_stat(md, "value")], "value")
    assert census.all_nan is True
    assert census.nonnull_fraction == 0.0

    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5)
    assert len(rows) == 1
    assert rows[0].kind == KIND_ALL_NAN


def test_all_nan_via_float_nan_values(tmp_path):
    # NaN stored as an actual float value (not null): parquet excludes NaN from
    # min/max so has_min_max is False -> still detected as effectively all-missing.
    tbl = pa.table({"value": pa.array([float("nan")] * 6, type=pa.float64())})
    md = _write(tmp_path, "nan.parquet", tbl)
    stat = _stat(md, "value")
    # null_count is 0 (NaN is not null) but has_min_max is False.
    assert stat.null_count == 0
    assert stat.has_min_max is False
    census = census_column([stat], "value")
    assert census.all_nan is True


# ---------------------------------------------------------------------------
# non-null floor breach (partial nulls).
# ---------------------------------------------------------------------------
def test_below_floor_fails(tmp_path):
    tbl = pa.table({"value": pa.array([1.0, None, None, None], type=pa.float64())})  # 25% non-null
    md = _write(tmp_path, "sparse.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert census.nonnull_fraction == pytest.approx(0.25)
    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5)
    assert [r.kind for r in rows] == [KIND_NONNULL_BELOW_FLOOR]


def test_above_floor_passes(tmp_path):
    tbl = pa.table({"value": pa.array([1.0, 2.0, 3.0, None], type=pa.float64())})  # 75% non-null
    md = _write(tmp_path, "ok.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert census.nonnull_fraction == pytest.approx(0.75)
    assert evaluate_gate("t", {"value": census}, ["value"], 0.5) == []


# ---------------------------------------------------------------------------
# single-vintage / vintage-adequacy (the ESR class).
# ---------------------------------------------------------------------------
def test_single_vintage_fails(tmp_path):
    # one commodity partition, a single as_of value.
    a = pa.table({"as_of_date": pa.array(["20260528"] * 100)})
    b = pa.table({"as_of_date": pa.array(["20260528"] * 80)})
    mds = [_write(tmp_path, "a.parquet", a), _write(tmp_path, "b.parquet", b)]
    census = census_column([_stat(m, "as_of_date") for m in mds], "as_of_date")
    assert census.distinct_lower_bound == 1

    rows = evaluate_gate(
        "silver_esr_compact", {"as_of_date": census}, [], 0.5,
        knowledge_date_col="as_of_date", knowledge_census=census,
    )
    assert [r.kind for r in rows] == [KIND_SINGLE_VINTAGE]


def test_single_vintage_waiver_demotes_to_warn(tmp_path):
    """BF-W2 rider 6: a declared vintage_waiver DEMOTES the single_vintage hard row to a WARN that
    names the approval; every other kind stays hard; no waiver -> unchanged (evaluate_gate itself
    never consults the waiver, so the gate cannot be quietly disarmed)."""
    from leviathan.silver.value_census import apply_vintage_waiver

    a = pa.table({"ingest_date": pa.array(["2026-01-20"] * 100)})
    md = _write(tmp_path, "a.parquet", a)
    census = census_column([_stat(md, "ingest_date")], "ingest_date")
    rows = evaluate_gate(
        "silver_production", {"ingest_date": census}, [], 0.5,
        knowledge_date_col="ingest_date", knowledge_census=census,
    )
    assert [r.kind for r in rows] == [KIND_SINGLE_VINTAGE]      # the gate itself stays strict

    waiver = {"reason": "annual latest-only source; second vintage structurally impossible",
              "approved": "2026-07-15 BF-W2 rider 6 (user gate)"}
    kept, waived = apply_vintage_waiver(rows, waiver)
    assert kept == []                                            # hard-fail cleared...
    assert len(waived) == 1 and waived[0].kind == KIND_SINGLE_VINTAGE
    assert "WAIVED (2026-07-15 BF-W2 rider 6 (user gate))" in waived[0].detail  # ...but never silent

    kept_no, waived_no = apply_vintage_waiver(rows, None)        # no waiver -> nothing changes
    assert kept_no == rows and waived_no == []


def test_live_registry_carries_the_faostat_waiver():
    # the tracked contract (rider 6) validates against the strict schema and reaches consumers.
    from leviathan.silver.registry import load_registry as load_silver
    reg = load_silver()
    w = reg.tables["silver_production"].get("vintage_waiver")
    assert w and "FAOSTAT" in w["reason"] and "rider 6" in w["approved"]


def test_multi_vintage_passes(tmp_path):
    a = pa.table({"as_of_date": pa.array(["20260521"] * 50)})
    b = pa.table({"as_of_date": pa.array(["20260528"] * 50)})
    mds = [_write(tmp_path, "a.parquet", a), _write(tmp_path, "b.parquet", b)]
    census = census_column([_stat(m, "as_of_date") for m in mds], "as_of_date")
    assert census.distinct_lower_bound == 2
    rows = evaluate_gate(
        "t", {"as_of_date": census}, [], 0.5,
        knowledge_date_col="as_of_date", knowledge_census=census,
    )
    assert rows == []


# ---------------------------------------------------------------------------
# sentinel saturation is a hard fail; a benign constant is only a warning.
# ---------------------------------------------------------------------------
def test_sentinel_saturation_hard_fails(tmp_path):
    tbl = pa.table({"value": pa.array([-999.0] * 20, type=pa.float64())})
    md = _write(tmp_path, "sentinel.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert census.sentinel_saturated is True
    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5)
    assert [r.kind for r in rows] == [KIND_SENTINEL_SATURATED]


def test_benign_constant_is_warning_not_gate(tmp_path):
    # A legitimately-thin partition: one distinct non-sentinel value. Must NOT hard-fail
    # (OP-8/AV-11 calibration: the WASDE 1987 scanned release).
    tbl = pa.table({"estimate": pa.array([4.3] * 10, type=pa.float64())})
    md = _write(tmp_path, "thin.parquet", tbl)
    census = census_column([_stat(md, "estimate")], "estimate")
    assert census.all_constant is True
    assert evaluate_gate("t", {"estimate": census}, ["estimate"], 0.5) == []
    warns = evaluate_warnings("t", {"estimate": census}, ["estimate"])
    assert len(warns) == 1


# ---------------------------------------------------------------------------
# end-to-end table result serialisation + gate wiring.
# ---------------------------------------------------------------------------
def test_build_table_result_shape(tmp_path):
    good = pa.table({"value": pa.array([1.0, 2.0, 3.0]), "as_of_date": pa.array(["a", "b", "c"])})
    md = _write(tmp_path, "g.parquet", good)
    census = {
        "value": census_column([_stat(md, "value")], "value"),
        "as_of_date": census_column([_stat(md, "as_of_date")], "as_of_date"),
    }
    result = build_table_result(
        "silver_demo",
        partition_mode="flat",
        value_columns=["value"],
        min_nonnull_frac=0.5,
        knowledge_date_col="as_of_date",
        vintage_retention="per-vintage",
        census_by_column=census,
        files_sampled=1,
        sample_strategy="flat: 1 group",
    )
    assert result.passed is True
    d = result.to_dict()
    assert d["athena_queries_issued"] == 0
    assert d["package"] == "SILVER-V001"
    assert d["mechanism"] == "parquet_footer_statistics"
    assert "value" in d["columns"]


# ------------------------------------------------------- control-plane exclusion (BF-W1 hygiene)
def test_census_walker_skips_hidden_control_plane_segments():
    """The F015 publisher stages under <root>/_shadow/ and writes <root>/_manifests/; the
    census must never sample those as data groups (Hive hidden-path convention)."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "value_census_job", repo / "jobs" / "audit" / "value_census.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)  # type: ignore[union-attr]

    assert job._is_hidden("_shadow/")
    assert job._is_hidden("silver/weather/source=chirps/_shadow/commodity=cocoa/part-000.parquet")
    assert job._is_hidden("_manifests/silver_chirps-cocoa.json")
    assert job._is_hidden(".hidden/part.parquet")
    assert not job._is_hidden("commodity=cocoa/")
    assert not job._is_hidden("silver/weather/source=chirps/commodity=cocoa/year=1981/part-000.parquet")

# ---------------------------------------------------------------------------
# OP-8 per-column floor calibration (min_nonnull_frac_overrides, BF-W3 cotton).
# ---------------------------------------------------------------------------
def test_floor_override_calibrates_one_column(tmp_path):
    # 25% non-null passes under a calibrated 0.25 floor while the base floor stays 0.5.
    tbl = pa.table({"value": pa.array([1.0, None, None, None], type=pa.float64())})
    md = _write(tmp_path, "sparse_cal.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert evaluate_gate("t", {"value": census}, ["value"], 0.5,
                         floor_overrides={"value": 0.25}) == []
    # a column NOT named in the overrides keeps the base floor.
    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5,
                         floor_overrides={"other": 0.25})
    assert [r.kind for r in rows] == [KIND_NONNULL_BELOW_FLOOR]


def test_floor_override_does_not_waive_all_nan(tmp_path):
    # the calibration never waives the ALL-NaN hard gate: a dead column still fails at floor 0.
    tbl = pa.table({"value": pa.array([None, None], type=pa.float64())})
    md = _write(tmp_path, "dead_cal.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5,
                         floor_overrides={"value": 0.0})
    assert [r.kind for r in rows] == [KIND_ALL_NAN]


def test_live_registry_carries_the_cotton_calibration():
    # the tracked contract (BF-W3 lane COTTON) validates against the schema and reaches consumers.
    from leviathan.silver.registry import load_registry as load_silver
    reg = load_silver()
    ov = reg.tables["silver_ams_cotton_quality"].get("min_nonnull_frac_overrides")
    assert ov == {"samples_classed": 0.25}


# ---------------------------------------------------------------------------
# D-SG G1-5: the season-aware floor (the NASS pct_harvested class).
#
# The usda_nass gate refused on 2026-08-11 with "[commodity=corn_cbot] 'pct_harvested' non-null
# fraction 0.141 < floor 0.15". Nothing was wrong with the data -- NASS publishes no harvested row
# until harvest begins, so a mid-August census is legitimately sparse and a season-blind floor turns
# that into the same refusal, at the same point in the calendar, every year. The floor is now chosen
# by the month the census ran in; the refusal stays honest in the months the column is populated.
# ---------------------------------------------------------------------------
def _sparse_141(tmp_path, name="harvest.parquet"):
    tbl = pa.table({"pct_harvested": pa.array([1.0] * 141 + [None] * 859, type=pa.float64())})
    md = _write(tmp_path, name, tbl)
    return census_column([_stat(md, "pct_harvested")], "pct_harvested")


def test_season_floor_passes_in_august_and_still_refuses_in_november(tmp_path):
    census = _sparse_141(tmp_path)
    assert census.nonnull_fraction == pytest.approx(0.141)
    args = ("t", {"pct_harvested": census}, ["pct_harvested"], 0.5)
    kw = {"floor_overrides": {"pct_harvested": 0.15},
          "season_floor_overrides": {"pct_harvested": {"1-9": 0.10}}}
    # August: inside the pre-harvest window, so 0.141 clears the season floor.
    assert evaluate_gate(*args, as_of_month=8, **kw) == []
    # November: the harvest weeks have landed and the report is closing, so the SAME fraction is a
    # real regression and the full calibrated floor refuses it.
    rows = evaluate_gate(*args, as_of_month=11, **kw)
    assert [r.kind for r in rows] == [KIND_NONNULL_BELOW_FLOOR]
    assert rows[0].threshold == 0.15


def test_a_caller_that_cannot_say_when_gets_the_strict_floor(tmp_path):
    # The season floor is a statement about WHEN the census ran; without a month it stays inert.
    census = _sparse_141(tmp_path, "harvest_nomonth.parquet")
    rows = evaluate_gate("t", {"pct_harvested": census}, ["pct_harvested"], 0.5,
                         floor_overrides={"pct_harvested": 0.15},
                         season_floor_overrides={"pct_harvested": {"1-9": 0.10}})
    assert [r.kind for r in rows] == [KIND_NONNULL_BELOW_FLOOR]


def test_season_floor_does_not_waive_all_nan(tmp_path):
    # Loosening a month never disarms the gate: a dead column still hard-fails inside the window.
    tbl = pa.table({"pct_harvested": pa.array([None, None], type=pa.float64())})
    md = _write(tmp_path, "dead_season.parquet", tbl)
    census = census_column([_stat(md, "pct_harvested")], "pct_harvested")
    rows = evaluate_gate("t", {"pct_harvested": census}, ["pct_harvested"], 0.5,
                         season_floor_overrides={"pct_harvested": {"1-9": 0.10}}, as_of_month=8)
    assert [r.kind for r in rows] == [KIND_ALL_NAN]


def test_resolve_floor_layers_scalar_then_column_then_season():
    assert resolve_floor("c", 0.5) == 0.5
    assert resolve_floor("c", 0.5, {"c": 0.15}) == 0.15
    assert resolve_floor("c", 0.5, {"c": 0.15}, {"c": {"1-9": 0.10}}, 8) == 0.10
    # a month outside every window, and a column with no window of its own, fall back untouched.
    assert resolve_floor("c", 0.5, {"c": 0.15}, {"c": {"1-9": 0.10}}, 11) == 0.15
    assert resolve_floor("other", 0.5, {"c": 0.15}, {"c": {"1-9": 0.10}}, 8) == 0.5


def test_resolve_floor_windows_wrap_the_new_year_and_never_loosen_on_overlap():
    wrap = {"c": {"11-3": 0.05}}
    assert [resolve_floor("c", 0.5, None, wrap, m) for m in (11, 12, 1, 3)] == [0.05] * 4
    assert resolve_floor("c", 0.5, None, wrap, 4) == 0.5
    # overlapping windows resolve to the HIGHEST floor -- an ambiguous declaration cannot weaken
    # the gate below its author's strictest intent.
    assert resolve_floor("c", 0.5, None, {"c": {"1-9": 0.10, "8-10": 0.20}}, 8) == 0.20


def test_live_registry_carries_the_nass_season_calibration():
    # the tracked contract validates against the schema and reaches the census through the runner.
    from leviathan.silver.registry import load_registry as load_silver
    reg = load_silver()
    c = reg.tables["silver_nass_crop_progress"]
    assert c["min_nonnull_frac_season_overrides"] == {"pct_harvested": {"1-9": 0.10}}
    # the full-year floor is untouched: the season window refines it, it does not replace it.
    assert c["min_nonnull_frac_overrides"]["pct_harvested"] == 0.15
    # and no other contract gained a season window in this wave.
    with_season = sorted(n for n, t in reg.tables.items() if "min_nonnull_frac_season_overrides" in t)
    assert with_season == ["silver_nass_crop_progress"]


def test_live_registry_carries_the_esr_vintage_waiver():
    """D-SG G1-6 PATH A: the abandoned full silver_esr surface is frozen at one as_of vintage, so the
    V001 single_vintage row refused the ONE gate job that covers the whole usda_esr family -- and
    blocked promote for silver_esr_compact, the surface that actually carries the per-week vintages.
    The waiver demotes that row to a WARN naming the approval; every other V001 kind stays hard."""
    from leviathan.silver.registry import load_registry as load_silver
    reg = load_silver()
    w = reg.tables["silver_esr"]["vintage_waiver"]
    assert w["approved"] == "2026-08-16 D-SG G1-6 (user gate)"
    assert "silver_esr_compact" in w["reason"]
    # the certified serving surface is NOT waived -- its vintages are real.
    assert "vintage_waiver" not in reg.tables["silver_esr_compact"]


# ---------------------------------------------------------------------------
# NASS GATE RCA (2026-09-09): the DECLARED SOURCE ABSENCE of (group, column) PAIRS.
#
# THE MEASURED TRIGGER, not a hypothetical: the usda_nass silver chain refused three consecutive
# Tuesdays -- 2026-08-25 / 09-01 / 09-08 -- on three different gate images with byte-identical
# banners ("[commodity=cottonseed] 'yield_t_ha' footer carried no row-group statistics"), because
# USDA NASS publishes cottonseed as PRODUCTION ONLY: it is a byproduct of the cotton crop, and the
# acreage/yield series belong to the `cotton` slug. All 161 cottonseed partitions carry yield_t_ha
# and area_planted_ha as arrow `null` -- physical INT32 with NO Statistics struct at all -- and
# area_harvested_ha as a correctly-typed double that is 100% null. Canonical silver went 20 days
# stale on data that is exactly what the source published.
#
# The census had no vocabulary for a declared absence, and no floor could have supplied one:
# evaluate_gate checks files_with_stats == 0 and all_nan BEFORE the floor and `continue`s on both,
# so a floor of 0.0 disarms neither -- and widening a floor would blind the other nine commodities
# to a real all-null regression on the same column.
# ---------------------------------------------------------------------------
def _cottonseed_footer(tmp_path, name="cottonseed.parquet"):
    """The real cottonseed footer shape, reproduced in kind: yield_t_ha and area_planted_ha written
    as arrow `null` (physical INT32, statistics None -> has_stats False), area_harvested_ha a double
    that is 100% null (stats present, has_min_max False), production_mt fully populated. Verified
    against the live object
    s3://leviathan-dev-shahem-001/silver/nass_annual/commodity=cottonseed/year=1866/part-000.parquet
    (created_by 'parquet-cpp-arrow version 25.0.1', 12 rows, 1 row group)."""
    tbl = pa.table({
        "production_mt": pa.array([16329.3, 783807.6, 40000.0], type=pa.float64()),
        "yield_t_ha": pa.array([None] * 3, type=pa.null()),             # arrow null -> NO statistics
        "area_harvested_ha": pa.array([None] * 3, type=pa.float64()),   # double, 100% null
        "area_planted_ha": pa.array([None] * 3, type=pa.null()),        # arrow null -> NO statistics
    })
    md = _write(tmp_path, name, tbl)
    cols = ["production_mt", "yield_t_ha", "area_harvested_ha", "area_planted_ha"]
    return {c: census_column([_stat(md, c)], c) for c in cols}, cols


_ABSENCE_DECL = {
    "reason": "USDA NASS publishes cottonseed as PRODUCTION ONLY (a cotton byproduct)",
    "approved": "2026-09-09 NASS gate RCA (three Tuesday reds)",
    "groups": {"commodity=cottonseed": ["area_harvested_ha", "area_planted_ha", "yield_t_ha"]},
}


def test_the_cottonseed_footer_shape_is_what_the_gate_refused(tmp_path):
    """Pin the DEFECT first, so the fix below is measured against the real failure and not against a
    convenient one: two columns with NO footer statistics at all, one 100%-null double."""
    from leviathan.silver.value_census import KIND_STATS_UNAVAILABLE

    census, cols = _cottonseed_footer(tmp_path)
    assert census["yield_t_ha"].files_with_stats == 0          # arrow null -> statistics is None
    assert census["area_planted_ha"].files_with_stats == 0
    assert census["area_harvested_ha"].files_with_stats == 1 and census["area_harvested_ha"].all_nan
    assert census["production_mt"].nonnull_fraction == 1.0     # the one column NASS does publish

    rows = evaluate_gate("silver_nass_annual", census, cols, 0.5)
    assert [(r.column, r.kind) for r in rows] == [
        ("yield_t_ha", KIND_STATS_UNAVAILABLE),
        ("area_harvested_ha", KIND_ALL_NAN),
        ("area_planted_ha", KIND_STATS_UNAVAILABLE),
    ]
    # and no floor can reach them: both kinds are checked BEFORE the floor and both `continue`.
    at_zero = evaluate_gate("silver_nass_annual", census, cols, 0.5,
                            floor_overrides={c: 0.0 for c in cols})
    assert len(at_zero) == 3


def test_declared_absent_group_demotes_both_absence_kinds_to_warn(tmp_path):
    from leviathan.silver.value_census import KIND_STATS_UNAVAILABLE, apply_absent_group_waiver

    census, cols = _cottonseed_footer(tmp_path)
    rows = evaluate_gate("silver_nass_annual", census, cols, 0.5)
    kept, warned = apply_absent_group_waiver(rows, "commodity=cottonseed", _ABSENCE_DECL, cols)
    assert kept == []                                          # the gate is green...
    assert len(warned) == 3                                    # ...and every row is still REPORTED
    for w in warned:
        assert w.detail.startswith(
            "DECLARED-ABSENT (2026-09-09 NASS gate RCA (three Tuesday reds))")
        assert "PRODUCTION ONLY" in w.detail                   # the reason rides the row, always
    assert sorted(w.column for w in warned) == ["area_harvested_ha", "area_planted_ha", "yield_t_ha"]
    # the kind is preserved on the warn row -- a demotion, not a relabelling.
    assert {w.kind for w in warned} == {KIND_ALL_NAN, KIND_STATS_UNAVAILABLE}


def test_an_undeclared_group_with_the_identical_shape_still_hard_fails(tmp_path):
    """THE FAIL-CLOSED HALF. The same footer under a group nobody declared is a real regression --
    a corn partition whose statistics vanished must still refuse the chain."""
    from leviathan.silver.value_census import apply_absent_group_waiver

    census, cols = _cottonseed_footer(tmp_path, "corn_stats_vanished.parquet")
    rows = evaluate_gate("silver_nass_annual", census, cols, 0.5)
    kept, warned = apply_absent_group_waiver(rows, "commodity=corn_cbot", _ABSENCE_DECL, cols)
    assert len(kept) == 3 and warned == []                     # corn is NOT declared -> nothing moves
    assert [r.kind for r in kept] == [r.kind for r in rows]


def test_no_declaration_at_all_changes_nothing(tmp_path):
    from leviathan.silver.value_census import apply_absent_group_waiver

    census, cols = _cottonseed_footer(tmp_path, "nodecl.parquet")
    rows = evaluate_gate("silver_nass_annual", census, cols, 0.5)
    kept, warned = apply_absent_group_waiver(rows, "commodity=cottonseed", None, cols)
    assert kept == list(rows) and warned == []


def test_a_declared_column_that_starts_carrying_data_is_censused_normally(tmp_path):
    """The declaration speaks to ABSENCE only. The day NASS starts publishing cottonseed yield, a
    thin or sentinel-saturated column on that pair is a finding like any other -- only the two
    absence kinds are demotable, so a below-floor row stays HARD under the same declaration."""
    from leviathan.silver.value_census import apply_absent_group_waiver

    tbl = pa.table({"yield_t_ha": pa.array([1.0] + [None] * 9, type=pa.float64())})  # 10% non-null
    md = _write(tmp_path, "cottonseed_alive.parquet", tbl)
    census = {"yield_t_ha": census_column([_stat(md, "yield_t_ha")], "yield_t_ha")}
    rows = evaluate_gate("silver_nass_annual", census, ["yield_t_ha"], 0.5)
    assert [r.kind for r in rows] == [KIND_NONNULL_BELOW_FLOOR]
    kept, warned = apply_absent_group_waiver(rows, "commodity=cottonseed", _ABSENCE_DECL,
                                             ["yield_t_ha"])
    assert len(kept) == 1 and warned == []
    # ...and a sentinel-saturated column on a declared pair is equally untouchable.
    sent = pa.table({"yield_t_ha": pa.array([-999.0] * 8, type=pa.float64())})
    md2 = _write(tmp_path, "cottonseed_sentinel.parquet", sent)
    c2 = {"yield_t_ha": census_column([_stat(md2, "yield_t_ha")], "yield_t_ha")}
    r2 = evaluate_gate("silver_nass_annual", c2, ["yield_t_ha"], 0.5)
    assert [r.kind for r in r2] == [KIND_SENTINEL_SATURATED]
    assert apply_absent_group_waiver(r2, "commodity=cottonseed", _ABSENCE_DECL,
                                     ["yield_t_ha"])[0] == r2


def test_a_column_outside_value_columns_never_demotes(tmp_path):
    """Fail closed on the SET, not only on the kind: if a declared column is not (or is no longer) a
    governed value_column, the demotion must not fire. Otherwise a column quietly dropped from the
    numbers card would keep a stale waiver alive with nothing to say so."""
    from leviathan.silver.value_census import apply_absent_group_waiver

    census, cols = _cottonseed_footer(tmp_path, "narrowed.parquet")
    rows = evaluate_gate("silver_nass_annual", census, cols, 0.5)
    governed = ["production_mt", "area_harvested_ha"]           # yield/planted no longer governed
    kept, warned = apply_absent_group_waiver(rows, "commodity=cottonseed", _ABSENCE_DECL, governed)
    assert [w.column for w in warned] == ["area_harvested_ha"]
    assert sorted(r.column for r in kept) == ["area_planted_ha", "yield_t_ha"]


def test_live_registry_carries_the_cottonseed_absence_declaration():
    """The tracked contract validates against the strict schema (additionalProperties is false, so
    the key exists only because the schema declares it) and reaches the census through the runner."""
    from leviathan.silver.registry import load_registry as load_silver

    reg = load_silver()
    c = reg.tables["silver_nass_annual"]
    d = c["value_column_absent_groups"]
    assert d["groups"] == {"commodity=cottonseed":
                           ["area_harvested_ha", "area_planted_ha", "yield_t_ha"]}
    assert "2026-09-09" in d["approved"] and "PRODUCTION ONLY" in d["reason"]
    # PAIRS, never a whole column: production_mt stays governed and undeclared, and the other nine
    # commodities keep every one of the four value columns under the live gate.
    assert "production_mt" not in d["groups"]["commodity=cottonseed"]
    assert c["value_columns"] == ["production_mt", "yield_t_ha", "area_harvested_ha",
                                  "area_planted_ha"]
    enum = c["projection_domains"]["projection.commodity.values"].split(",")
    assert len(enum) == 10 and "cottonseed" in enum            # the partition is NOT hidden (F020)
    # no other contract gained a declaration in this wave.
    declared = sorted(n for n, t in reg.tables.items() if "value_column_absent_groups" in t)
    assert declared == ["silver_nass_annual"]


def test_the_generator_refuses_an_ungoverned_column_an_unknown_group_and_a_whole_column():
    """The three generation-time refusals. A demotion mechanism is exactly what an abuser reaches
    for, so a bad declaration must never render a contract at all."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "gen_registry_absence", repo / "scripts" / "silver" / "gen_registry_from_baseline.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)  # type: ignore[union-attr]

    def _contract():
        return {"table_name": "t", "physical_columns": [{"name": "a"}, {"name": "b"}],
                "value_columns": ["a", "b"],
                "projection_domains": {"projection.commodity.values": "x,y"}}

    def _decl(groups):
        return {"value_column_absent_groups": {"reason": "r" * 30, "approved": "a" * 10,
                                               "groups": groups}}

    original = dict(gen.CURATION_OVERRIDES)
    try:
        # (a) a column that is not a declared value_column
        gen.CURATION_OVERRIDES["t"] = _decl({"commodity=x": ["zzz"]})
        with pytest.raises(KeyError, match="not declared value_columns"):
            gen._apply_curation_overrides("t", _contract())
        # (b) a group outside the projection enum
        gen.CURATION_OVERRIDES["t"] = _decl({"commodity=nope": ["a"]})
        with pytest.raises(KeyError, match="not in the projection enum"):
            gen._apply_curation_overrides("t", _contract())
        # (c) a column declared absent in EVERY group == a whole-column absence in disguise
        gen.CURATION_OVERRIDES["t"] = _decl({"commodity=x": ["a"], "commodity=y": ["a"]})
        with pytest.raises(KeyError, match="EVERY projection group"):
            gen._apply_curation_overrides("t", _contract())
        # ...and the honest shape renders, sorted for byte-stability.
        gen.CURATION_OVERRIDES["t"] = _decl({"commodity=x": ["b", "a"]})
        c = _contract()
        gen._apply_curation_overrides("t", c)
        assert c["value_column_absent_groups"]["groups"] == {"commodity=x": ["a", "b"]}
    finally:
        gen.CURATION_OVERRIDES.clear()
        gen.CURATION_OVERRIDES.update(original)
