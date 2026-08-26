"""SILVER-F091 / INV-10: the source-universe lint's gate.

Loads the lint by file path (it is a ``scripts/`` tool, not an importable package) and pins the
three things the first cut has to get right.

  1. THE CENSUS PIN -- 161 universe-shaped literals across 92 files, out of 327 module-level
     collection literals in 125 files; docket 83 files / 142 literals; 9 files covered. The same
     numbers are banked in ``data/f091/source_universe_census.json`` (an untracked main-tree
     artifact, so they are pinned HERE as literals rather than read from it). They are re-derived
     over the COMMITTED producer files: an uncommitted new producer is not yet part of the pinned
     population, and enters this pin in the commit that adds it.
  2. NON-VACUITY -- the written refusal registries the estate already has must read as COVERED,
     asserted as a set equality BOTH directions. A gate that cannot go red has learned nothing:
     narrow the key rule and ``_RECORDED_CLASS_EXCLUSIONS`` drops out; widen the name rule and a
     decline-REASON enum is miscounted as a refusal.
  3. THE DOCKET IS REPORTED, NEVER FATAL -- day one is 83 uncovered files at rc==0. The only
     ``--strict`` failure is a source that does not PARSE, which is the estate's sole structural
     guard against the ``discover_unica_wayback.py`` class (a producer that stopped compiling and
     was caught by nothing for 85 days).

THE FENCE, restated because a green suite is the thing most likely to be misread: this cut proves
only that a written refusal EXISTS. Under-coverage -- ``ingested + refused < measured`` -- needs a
``measured_count`` network probe and is OUT OF SCOPE. No test here may be read as a coverage claim.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LINT = _REPO / "scripts" / "silver" / "f091_source_universe_lint.py"

# ---------------------------------------------------------------------------
# THE CENSUS PIN. Moves in the same change that moves the population.
# ---------------------------------------------------------------------------
# RE-MEASURED 2026-08-26 on the integrated projection-wave tree (the Lane-6 review's major 1: the
# original pins were cut at a stale worktree HEAD). The deltas vs the 2026-08-25 census artifact are
# each attributable by name: usda_psd_attributes.py landed (3 universe literals; the file enters
# PIN_UNIVERSE_FILE_LIST below), the NASS C-2 change added its two exclusion registries (usda_nass.py
# flips from docket to covered), and the job lane's psd_attributes task added its alias-gate map.
#
# RE-MEASURED AGAIN 2026-08-26 by PROJECTION WAVE Lane 5 (FAO-2), and every delta is attributable to
# that one change -- neither faostat file is new to PIN_UNIVERSE_FILE_LIST, so PIN_UNIVERSE_FILES does
# not move and only the literal counts and the coverage/docket SPLIT do:
#   +5 raw / +4 universe literals -- faostat_qcl.TARGET_ELEMENTS grew and gained
#     _REFUSED_LEGEND_ELEMENTS; faostat_production gained METRIC_UNITS, _REFUSED_UNITS,
#     HEAD_COUNT_METRICS / TONNAGE_METRICS / PER_ANIMAL_RATE_METRICS and FAOSTAT_LIVESTOCK_SLUGS.
#   10 -> 12 COVERED and 83 -> 81 DOCKET -- the two faostat files each gained a written refusal
#     registry, so they leave the docket. This is the first change to move the docket DOWN, which is
#     the lint's whole purpose: C-1 shipped it as a reported docket precisely so a lane closing two
#     of its files would show up here as a number rather than as a claim.
#   143 -> 140 docket literals -- the three literals the two files owed, now covered.
PIN_RAW_LITERALS = 339
PIN_RAW_FILES = 126
PIN_UNIVERSE_LITERALS = 169
PIN_UNIVERSE_FILES = 93
PIN_COVERED_FILES = 12
PIN_DOCKET_FILES = 81
PIN_DOCKET_LITERALS = 140

# The written refusals the estate holds today: (file, literal). The plan text said FOUR; the 08-25
# measurement said SEVEN in code plus one in config; the C-2 change added TWO more in usda_nass.py
# and FAO-2 (Lane 5) TWO more again, making TEN in code plus one in config;
# (the value-axis and commodity-axis registries), and the measurement is what is pinned. EVERY entry
# must be NON-EMPTY -- an empty registry is a stub the lint refuses to count as coverage (the
# false-GREEN fix), and the floor test below proves that refusal by mutation.
PIN_REFUSAL_REGISTRIES = frozenset({
    ("src/leviathan/transforms/bronze_to_silver/_weather_schema.py", "NASA_EXCLUDED_PARAMS"),
    ("src/leviathan/transforms/bronze_to_silver/usda_nass_annual.py", "_RECORDED_CLASS_EXCLUSIONS"),
    ("src/leviathan/transforms/bronze_to_silver/usda_nass_crop_progress.py",
     "_HARVESTED_UTIL_EXCLUSIONS"),
    ("src/leviathan/transforms/bronze_to_silver/usda_psd.py", "_PSD_UNMAPPED_CODES"),
    # PROJECTION WAVE Lane 5 (FAO-2): the two the livestock half added. `_REFUSED_LEGEND_ELEMENTS`
    # names the two release-legend element names that carry ZERO rows; `_REFUSED_UNITS` names the
    # three (metric, unit) pairs the file prints and silver_production will not serve. Both are
    # documentation-with-a-test in the `_PSD_UNMAPPED_CODES` idiom, and both carry the measured row
    # count that makes the refusal honest.
    ("src/leviathan/transforms/bronze_to_silver/faostat_production.py", "_REFUSED_UNITS"),
    ("src/leviathan/transforms/raw_to_bronze/faostat_qcl.py", "_REFUSED_LEGEND_ELEMENTS"),
    ("src/leviathan/transforms/raw_to_bronze/ams_gtr.py", "REFUSED_DATASETS"),
    ("src/leviathan/transforms/raw_to_bronze/eex_freight.py", "REFUSED_PRICINGS"),
    ("src/leviathan/transforms/raw_to_bronze/usda_nass.py", "_RECORDED_STAT_CAT_EXCLUSIONS"),
    ("src/leviathan/transforms/raw_to_bronze/usda_nass.py", "_RECORDED_COMMODITY_EXCLUSIONS"),
    ("src/leviathan/transforms/raw_to_bronze/world_bank_pink_sheet.py", "_REFUSED_SERIES"),
})
PIN_REFUSAL_REGISTRIES_CONFIG = frozenset({"configs/sources/cftc_cot.yaml::not_covered:"})

# The 92 files the census names, re-banked here because data/f091/source_universe_census.json is an
# UNTRACKED main-tree artifact this suite cannot read. The list is not decoration: a rename or a
# deletion moves the totals without changing their shape, and only the list says which file left.
PIN_UNIVERSE_FILE_LIST = (
    "jobs/batch/_sb_producer_publish.py",
    "jobs/batch/fnc_colombia_silver_task.py",
    "jobs/batch/gold_futures_outcomes_task.py",
    "jobs/batch/gold_pattern_outcomes_task.py",
    "jobs/batch/pattern_records_sweep_task.py",
    "jobs/glue/raw_to_bronze_usda_esr.py",
    "jobs/ingest/backfill_minagro_wayback.py",
    "jobs/ingest/discover_conab_bulletin_xls.py",
    "jobs/ingest/fetch_bursa_fcpo.py",
    "jobs/ingest/fetch_cepea_daily.py",
    "jobs/ingest/fetch_cepea_wayback_history.py",
    "jobs/ingest/fetch_czce_eod.py",
    "jobs/ingest/fetch_databento_eod.py",
    "jobs/ingest/fetch_dce_eod.py",
    "jobs/ingest/fetch_eex_freight.py",
    "jobs/ingest/fetch_euronext_eod.py",
    "jobs/ingest/fetch_jse_safex_daily.py",
    "jobs/ingest/fetch_miax_eod.py",
    "jobs/ingest/fetch_minagro_grain_exports.py",
    "jobs/ingest/fetch_moex_agro_indices.py",
    "jobs/ingest/fetch_usda_esr.py",
    "jobs/ingest/fetch_usda_nass_citrus.py",
    "src/leviathan/transforms/bronze_to_silver/_weather_schema.py",  # covered
    "src/leviathan/transforms/bronze_to_silver/ams_cotton_quality.py",
    "src/leviathan/transforms/bronze_to_silver/ams_gtr.py",
    "src/leviathan/transforms/bronze_to_silver/cftc_cot.py",  # covered
    "src/leviathan/transforms/bronze_to_silver/conab_coffee.py",
    "src/leviathan/transforms/bronze_to_silver/eex_freight.py",
    "src/leviathan/transforms/bronze_to_silver/euronext_eod.py",
    "src/leviathan/transforms/bronze_to_silver/faostat_production.py",
    "src/leviathan/transforms/bronze_to_silver/fnc_colombia.py",
    "src/leviathan/transforms/bronze_to_silver/frankfurter_fx.py",
    "src/leviathan/transforms/bronze_to_silver/icco_cocoa.py",
    "src/leviathan/transforms/bronze_to_silver/moex_agro_indices.py",
    "src/leviathan/transforms/bronze_to_silver/mpob.py",
    "src/leviathan/transforms/bronze_to_silver/mpob_annual.py",
    "src/leviathan/transforms/bronze_to_silver/mpoc_exports_by_country.py",
    "src/leviathan/transforms/bronze_to_silver/mpoc_stock_comparison.py",
    "src/leviathan/transforms/bronze_to_silver/mpoc_trade_stats_monthly.py",
    "src/leviathan/transforms/bronze_to_silver/nass_citrus.py",
    "src/leviathan/transforms/bronze_to_silver/noaa_iod.py",
    "src/leviathan/transforms/bronze_to_silver/noaa_oni.py",
    "src/leviathan/transforms/bronze_to_silver/pink_sheet.py",
    "src/leviathan/transforms/bronze_to_silver/sagis_cec.py",
    "src/leviathan/transforms/bronze_to_silver/sagis_deliveries.py",
    "src/leviathan/transforms/bronze_to_silver/sagis_weekly_exports.py",
    "src/leviathan/transforms/bronze_to_silver/unica_annual_state.py",
    "src/leviathan/transforms/bronze_to_silver/unica_biweekly.py",
    "src/leviathan/transforms/bronze_to_silver/usda_esr.py",
    "src/leviathan/transforms/bronze_to_silver/usda_fgis.py",
    "src/leviathan/transforms/bronze_to_silver/usda_nass_annual.py",  # covered
    "src/leviathan/transforms/bronze_to_silver/usda_nass_crop_progress.py",  # covered
    "src/leviathan/transforms/bronze_to_silver/usda_psd.py",
    "src/leviathan/transforms/bronze_to_silver/usda_psd_attributes.py",  # covered
    "src/leviathan/transforms/bronze_to_silver/usda_wasde_silver.py",
    "src/leviathan/transforms/bronze_to_silver/wap_table01.py",
    "src/leviathan/transforms/bronze_to_silver/world_bank_food_cpi.py",
    "src/leviathan/transforms/bronze_to_silver/yfinance_futures.py",
    "src/leviathan/transforms/gold/board_crush.py",
    "src/leviathan/transforms/gold/futures_spreads.py",
    "src/leviathan/transforms/gold/weather_z.py",
    "src/leviathan/transforms/raw_to_bronze/ams_gtr.py",  # covered
    "src/leviathan/transforms/raw_to_bronze/bursa_fcpo.py",
    "src/leviathan/transforms/raw_to_bronze/cepea.py",
    "src/leviathan/transforms/raw_to_bronze/cftc_cot.py",  # covered
    "src/leviathan/transforms/raw_to_bronze/conab_xls.py",
    "src/leviathan/transforms/raw_to_bronze/cpc_iodmi.py",
    "src/leviathan/transforms/raw_to_bronze/czce_eod.py",
    "src/leviathan/transforms/raw_to_bronze/databento_eod.py",
    "src/leviathan/transforms/raw_to_bronze/dce_eod.py",
    "src/leviathan/transforms/raw_to_bronze/eex_freight.py",  # covered
    "src/leviathan/transforms/raw_to_bronze/euronext_eod.py",
    "src/leviathan/transforms/raw_to_bronze/faostat_qcl.py",
    "src/leviathan/transforms/raw_to_bronze/fnc_excel.py",
    "src/leviathan/transforms/raw_to_bronze/frankfurter_fx.py",
    "src/leviathan/transforms/raw_to_bronze/icco_cocoa.py",
    "src/leviathan/transforms/raw_to_bronze/jse_safex.py",
    "src/leviathan/transforms/raw_to_bronze/miax_eod.py",
    "src/leviathan/transforms/raw_to_bronze/minagro_grain_exports.py",
    "src/leviathan/transforms/raw_to_bronze/moex_agro_indices.py",
    "src/leviathan/transforms/raw_to_bronze/mpob_html.py",
    "src/leviathan/transforms/raw_to_bronze/nass_citrus.py",
    "src/leviathan/transforms/raw_to_bronze/noaa_iod.py",
    "src/leviathan/transforms/raw_to_bronze/noaa_oni.py",
    "src/leviathan/transforms/raw_to_bronze/unica_biweekly_pdf.py",
    "src/leviathan/transforms/raw_to_bronze/unica_html.py",
    "src/leviathan/transforms/raw_to_bronze/usda_esr.py",
    "src/leviathan/transforms/raw_to_bronze/usda_nass.py",
    "src/leviathan/transforms/raw_to_bronze/usda_wasde.py",
    "src/leviathan/transforms/raw_to_bronze/wap_table01.py",
    "src/leviathan/transforms/raw_to_bronze/world_bank_food_cpi.py",
    "src/leviathan/transforms/raw_to_bronze/world_bank_pink_sheet.py",  # covered
    "src/leviathan/transforms/raw_to_bronze/yfinance_futures.py",
)


@pytest.fixture(scope="module")
def lint():
    spec = importlib.util.spec_from_file_location("f091_source_universe_lint", _LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def result(lint):
    return lint.scan_tree()


@pytest.fixture(scope="module")
def committed(lint):
    """The producer files git tracks, or None when git cannot answer (then nothing is filtered)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(_REPO), "ls-files", "--", *lint.SCAN_ROOTS],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - git absent
        return None
    if proc.returncode != 0:  # pragma: no cover - not a work tree
        return None
    return {line.strip() for line in proc.stdout.splitlines() if line.strip().endswith(".py")}


def _pinned_population(result, committed):
    records = result["records"]
    counts = result["literal_counts_by_file"]
    if committed is not None:
        records = [r for r in records if r["file"] in committed]
        counts = {f: n for f, n in counts.items() if f in committed}
    return records, counts


# ---------------------------------------------------------------------------
# 1. The census pin.
# ---------------------------------------------------------------------------
class TestCensusPin:
    def test_raw_literal_census(self, result, committed):
        _, counts = _pinned_population(result, committed)
        assert sum(counts.values()) == PIN_RAW_LITERALS
        assert len(counts) == PIN_RAW_FILES

    def test_universe_literal_census(self, result, committed):
        records, _ = _pinned_population(result, committed)
        files = {r["file"] for r in records}
        entered = sorted(files - set(PIN_UNIVERSE_FILE_LIST))
        left = sorted(set(PIN_UNIVERSE_FILE_LIST) - files)
        assert len(records) == PIN_UNIVERSE_LITERALS, (
            f"census moved: +{entered} -{left}; move every PIN_* constant AND the file list in the "
            f"same change that moved the population")
        assert len(files) == PIN_UNIVERSE_FILES

    def test_no_census_file_left_the_population_silently(self, result, committed):
        """A rename or a deletion moves the totals without changing their shape. The list is the
        only thing that names WHICH file went."""
        records, _ = _pinned_population(result, committed)
        files = {r["file"] for r in records}
        assert sorted(set(PIN_UNIVERSE_FILE_LIST) - files) == []

    def test_docket_and_coverage_census(self, result, committed):
        records, _ = _pinned_population(result, committed)
        covered = {r["file"] for r in records if r["has_refusal_companion"]}
        docket_literals = [r for r in records if not r["has_refusal_companion"]]
        docket = {r["file"] for r in docket_literals}
        assert len(covered) == PIN_COVERED_FILES
        assert len(docket) == PIN_DOCKET_FILES
        assert len(docket_literals) == PIN_DOCKET_LITERALS
        # A file is covered or docketed, never both: coverage is a FILE-level fact.
        assert not (covered & docket)

    def test_every_record_carries_the_report_fields(self, lint, result):
        for r in result["records"]:
            assert set(r) >= {"family", "name", "file", "cardinality", "has_refusal_companion"}
            assert r["cardinality"] >= lint.MIN_CARDINALITY


# ---------------------------------------------------------------------------
# 2. NON-VACUITY -- the written refusals must read as covered.
# ---------------------------------------------------------------------------
class TestNonVacuity:
    def test_refusal_registries_set_equality_both_directions(self, result, committed):
        found = {(r["file"], r["name"]) for r in result["refusal_registries"]}
        if committed is not None:
            found = {(f, n) for f, n in found if f in committed}
        assert found == PIN_REFUSAL_REGISTRIES

    def test_config_side_refusals_set_equality(self, result):
        assert set(result["refusal_registries_config"]) == PIN_REFUSAL_REGISTRIES_CONFIG

    def test_each_registry_file_reads_covered(self, result):
        """Every file holding a written refusal AND a universe literal must read covered.

        ``ams_gtr`` and ``eex_freight`` hold their refusal on the raw_to_bronze side, so the pin is
        on the file that holds the registry -- read the docket by FILE, never by family.
        """
        by_file = {}
        for r in result["records"]:
            by_file.setdefault(r["file"], []).append(r)
        for path, _name in PIN_REFUSAL_REGISTRIES:
            for rec in by_file.get(path, []):
                assert rec["has_refusal_companion"], (path, rec["name"])

    def test_recorded_class_exclusions_survives_the_compound_key(self, result):
        """The flagship refusal keys on ``(commodity, class)`` PAIRS with an ``_ANY_CLASS``
        sentinel in six of them. A constant-only key rule silently drops it and usda_nass_annual.py
        then reads UNCOVERED -- this pin is the tripwire on that regression."""
        hit = [r for r in result["refusal_registries"]
               if r["name"] == "_RECORDED_CLASS_EXCLUSIONS"]
        assert len(hit) == 1
        assert hit[0]["file"].endswith("bronze_to_silver/usda_nass_annual.py")
        assert hit[0]["cardinality"] >= 19

    def test_config_registry_covers_both_sides_of_its_family(self, result):
        """cftc_cot writes its refusal in configs/sources/cftc_cot.yaml, and the bronze AND silver
        transforms of that family must both read covered off it."""
        covered = {r["file"] for r in result["records"] if r["has_refusal_companion"]}
        assert "src/leviathan/transforms/bronze_to_silver/cftc_cot.py" in covered
        assert "src/leviathan/transforms/raw_to_bronze/cftc_cot.py" in covered

    def test_decline_reason_enum_is_not_a_refusal(self, result):
        """``CHAIN_DECLINE_REASONS`` / ``CASCADE_DECLINE_REASONS`` name WHY a row declined, never
        WHICH source members were left out. Counting them would read the sweep task green on a
        refusal it does not hold -- a false GREEN is the one failure this lint cannot afford."""
        names = {r["name"] for r in result["refusal_registries"]}
        assert "CHAIN_DECLINE_REASONS" not in names
        assert "CASCADE_DECLINE_REASONS" not in names
        assert "jobs/batch/pattern_records_sweep_task.py" in result["docket"]


# ---------------------------------------------------------------------------
# 3. The docket is reported, never fatal. Only an unparseable source fails --strict.
# ---------------------------------------------------------------------------
class TestGatePosture:
    def test_strict_is_green_today_with_a_live_docket(self, lint, result, capsys):
        rc = lint.run(strict=True, write=False)
        assert rc == 0
        assert len(result["docket"]) == PIN_DOCKET_FILES  # green WITH 81 files owed a refusal
        out = capsys.readouterr().out
        assert "FENCE" in out and "OUT OF SCOPE" in out
        assert "docket:" in out

    def test_every_producer_source_parses(self, result):
        """The guard the estate lacked: ``jobs/ingest/discover_unica_wayback.py`` did not compile
        from the day it landed (2026-06-01) and no gate said so for 85 days."""
        assert result["meta"]["parse_failures"] == []
        assert result["meta"]["files_parsed"] == result["meta"]["files_scanned"]

    def test_bom_source_is_parsed_not_dropped(self, result):
        """usda_psd.py opens with a BOM; plain ``ast.parse`` raises on it, so the reader is
        utf-8-sig. A dropped file reads as ZERO literals owed -- silence, not a finding."""
        psd = [r for r in result["records"]
               if r["file"] == "src/leviathan/transforms/bronze_to_silver/usda_psd.py"]
        assert {"_PSD_COMMODITY_TO_MYS", "_TARGET_ATTRS"} <= {r["name"] for r in psd}


class TestSyntaxErrorIsReported:
    """A source that does not parse is a FINDING, never a silent skip."""

    @pytest.fixture
    def broken_tree(self, tmp_path):
        good = tmp_path / "jobs" / "ingest"
        good.mkdir(parents=True)
        (good / "fetch_good.py").write_text(
            'SERIES_MAP = {"a": 1, "b": 2, "c": 3}\n', encoding="utf-8")
        (good / "fetch_broken.py").write_text(
            'CODES = ["a", "b", "c"]\nRESULTS.write_text(\n', encoding="utf-8")
        return tmp_path

    def test_parse_failure_is_named_in_the_report(self, lint, broken_tree):
        res = lint.scan_tree(broken_tree)
        failures = {p["file"] for p in res["meta"]["parse_failures"]}
        assert failures == {"jobs/ingest/fetch_broken.py"}
        assert res["meta"]["files_scanned"] == 2
        assert res["meta"]["files_parsed"] == 1
        # the sibling still lints: one bad file must not take the scan down with it
        assert [r["name"] for r in res["records"]] == ["SERIES_MAP"]

    def test_strict_exits_3_on_a_source_that_does_not_compile(self, lint, broken_tree):
        assert lint.run(root=broken_tree, strict=True, write=False) == 3
        # ...and the same tree is rc==0 without --strict: the docket never fails the gate.
        assert lint.run(root=broken_tree, strict=False, write=False) == 0

    def test_bom_is_read_not_refused(self, lint, tmp_path):
        d = tmp_path / "jobs" / "ingest"
        d.mkdir(parents=True)
        (d / "fetch_bom.py").write_bytes(
            b"\xef\xbb\xbfATTRS = ('a', 'b', 'c')\n")
        res = lint.scan_tree(tmp_path)
        assert res["meta"]["parse_failures"] == []
        assert [r["name"] for r in res["records"]] == ["ATTRS"]

    def test_an_empty_refusal_registry_is_a_stub_not_coverage(self, lint, tmp_path):
        """THE FALSE-GREEN FLOOR (Lane-6 review, major 2, fixed by mutation-proof): an EMPTY
        `_REFUSED_X = {}` was the cheapest ticket off the docket -- coverage without one written
        word of refusal, on the axis where a false GREEN is the one failure this lint cannot
        afford. A ONE-entry registry still covers (a written refusal is a written refusal); a
        ZERO-entry one is a stub and the file stays docketed."""
        d = tmp_path / "jobs" / "ingest"
        d.mkdir(parents=True)
        (d / "fetch_stub.py").write_text(
            'COMMODITY_MAP = {"a": 1, "b": 2, "c": 3}\n_REFUSED_CODES = {}\n', encoding="utf-8")
        (d / "fetch_real.py").write_text(
            'COMMODITY_MAP = {"a": 1, "b": 2, "c": 3}\n'
            '_REFUSED_CODES = {"z": "parked: no vendor feed"}\n', encoding="utf-8")
        res = lint.scan_tree(tmp_path)
        registries = {(r["file"], r["name"]) for r in res["refusal_registries"]}
        assert ("jobs/ingest/fetch_real.py", "_REFUSED_CODES") in registries
        assert ("jobs/ingest/fetch_stub.py", "_REFUSED_CODES") not in registries, \
            "an empty registry counted as a written refusal -- the false-GREEN path is open again"
        docket = set(res["docket"])
        assert "jobs/ingest/fetch_stub.py" in docket
        assert "jobs/ingest/fetch_real.py" not in docket


# ---------------------------------------------------------------------------
# The literal detector itself -- pure, no tree.
# ---------------------------------------------------------------------------
class TestLiteralDetection:
    def test_pair_is_not_a_universe(self, lint):
        out = lint.scan_source('CODES = ["a", "b"]\n', "jobs/ingest/x.py")
        assert out["records"] == []  # 2 members is a bound, not a universe

    def test_non_universe_name_is_not_a_claim(self, lint):
        out = lint.scan_source('RETRY_SLEEPS = [1, 2, 4]\n', "jobs/ingest/x.py")
        assert out["records"] == []

    def test_dict_counts_its_keys(self, lint):
        out = lint.scan_source('COMMODITY_MAP = {"a": 1, "b": 2, "c": 3, "d": 4}\n',
                               "jobs/ingest/x.py")
        assert [(r["name"], r["cardinality"]) for r in out["records"]] == [("COMMODITY_MAP", 4)]

    def test_wrapper_and_comprehension_keep_the_source_width(self, lint):
        src = ('SYMBOLS = frozenset({"a", "b", "c", "d"})\n'
               'SYMBOL_CODES = [s.upper() for s in SYMBOLS]\n')
        out = lint.scan_source(src, "jobs/ingest/x.py")
        assert [(r["name"], r["cardinality"]) for r in out["records"]] == [
            ("SYMBOLS", 4), ("SYMBOL_CODES", 4)]
        # DERIVED counts both routes -- the wrapper call and the comprehension. Neither is
        # hand-written, and the count exists to say how much of the census is second-hand.
        assert out["derived_collections"] == 2

    def test_filtered_comprehension_is_reported_as_an_upper_bound(self, lint):
        """A filtered comprehension over a universe literal IS a narrowing -- exactly what INV-10
        hunts. Its width is not statically knowable, so the source literal's count stands as an
        upper bound rather than the record being dropped."""
        src = ('SERIES_COLUMNS = ["a_t", "b_m3", "c", "d", "e"]\n'
               '_RELEASE_METRICS = [c for c in SERIES_COLUMNS if c.endswith(("_t", "_m3"))]\n')
        out = lint.scan_source(src, "jobs/ingest/x.py")
        assert ("_RELEASE_METRICS", 5) in [(r["name"], r["cardinality"]) for r in out["records"]]

    def test_dynamic_dict_is_not_a_literal(self, lint):
        out = lint.scan_source('MERGED_MAP = {**BASE, "z": 1}\n', "jobs/ingest/x.py")
        assert out["records"] == []

    def test_one_entry_refusal_still_covers(self, lint):
        """A one-line written refusal is a written refusal: NASA_EXCLUDED_PARAMS holds exactly one
        entry. The MIN_CARDINALITY floor is about universe CLAIMS, never about refusals."""
        src = ('TARGET_PARAMS = ["a", "b", "c"]\n'
               'EXCLUDED_PARAMS = ["d"]\n')
        out = lint.scan_source(src, "src/leviathan/transforms/bronze_to_silver/x.py")
        assert [r["name"] for r in out["refusals"]] == ["EXCLUDED_PARAMS"]

    def test_family_strips_the_job_affixes(self, lint):
        assert lint.family_of("jobs/ingest/fetch_usda_esr.py") == "usda_esr"
        assert lint.family_of("jobs/batch/fnc_colombia_silver_task.py") == "fnc_colombia"
        assert lint.family_of("src/leviathan/transforms/bronze_to_silver/usda_wasde_silver.py") == \
            "usda_wasde"
