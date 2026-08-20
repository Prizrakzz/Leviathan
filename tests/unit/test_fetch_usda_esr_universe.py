"""Unit tests for the ESR fetcher's commodity universe (INV-10 fidelity).

The fetcher used to request 10 of the source's 44 commodity codes, behind an
unclosed TODO that reserved cotton and rice "pending confirmation from
/api/esr/commodities once an API key is in hand".  The key was in hand; the
census measured the universe live (2026-08-20, GET /api/esr/commodities -> 44
rows) and the reserved list itself was wrong -- it carried 1302 and 3202, which
do not exist in the API, and omitted every real cotton (1401-1404) and rice
(1498/1499/1501-1505) code.

These tests pin the MEASURED universe so the list cannot silently narrow again,
and guard the two specific defects that made the old list wrong: phantom codes
that were never in the source, and named-but-absent commodities (beef, pork,
cotton, rice) that the census showed were the largest discarded blocks.

THE COPIES (added 2026-08-20 with the widening's remediation).  Four other files
carried their own version of this list or of the marketing-year groups, and each
one is a way for the widening to be silently undone: the two local backfill
scripts, the Glue raw->bronze job and the Airflow weekly DAG.  The backfill
scripts now IMPORT the fetcher's list; the Glue job and the DAG cannot (they run
standalone off a bootstrapped wheel / an Airflow worker), so they mirror it and
the tests below pin every mirror EQUAL to the fetcher.  The Glue job and the DAG
are read with ``ast`` rather than imported -- ``awsglue`` and ``airflow`` are not
installed in the unit environment.

No network: the universe below is the recorded measurement, not a live fetch.
Re-measure with the live GET before changing it.
"""
from __future__ import annotations

import ast
import datetime
import importlib
from pathlib import Path

import pytest

from jobs.ingest import fetch_usda_esr as F

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GLUE_JOB = _REPO_ROOT / "jobs" / "glue" / "raw_to_bronze_usda_esr.py"
_AIRFLOW_DAG = _REPO_ROOT / "dags" / "airflow" / "esr_weekly_ingest_dag.py"
_BACKFILL_MODULES = (
    "jobs.ingest.backfill_bronze_usda_esr",
    "jobs.ingest.backfill_silver_usda_esr",
)


def _module_constant(path: Path, name: str):
    """Return one module-level constant read from SOURCE, without importing it.

    Handles the ``frozenset({...})`` form the marketing-year groups use, which is
    a Call node and therefore outside ``ast.literal_eval``'s reach on its own.
    Raises AssertionError when the name is absent -- which is itself an assertion
    some tests below make deliberately.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if (isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Name)
                        and value.func.id == "frozenset"):
                    return frozenset(ast.literal_eval(value.args[0])) if value.args else frozenset()
                return ast.literal_eval(value)
    raise AssertionError(f"{name} is not assigned at module level in {path}")

# The measured source universe -- GET https://api.fas.usda.gov/api/esr/commodities
# on 2026-08-20 with the estate's FAS_API_KEY.  44 rows, code -> commodityName.
_MEASURED_UNIVERSE: dict[int, str] = {
    101: "Wheat - HRW",
    102: "Wheat - SRW",
    103: "Wheat - HRS",
    104: "Wheat - White",
    105: "Wheat - Durum",
    106: "Wheat - Mixed",
    107: "All Wheat",
    201: "Wheat Products",
    301: "Barley",
    401: "Corn",
    501: "Rye",
    601: "Oats",
    701: "Sorghum",
    801: "Soybeans",
    901: "Soybean cake & meal",
    902: "Soybean Oil",
    1001: "Flaxseed",
    1101: "Linseed Oil",
    1110: "Sunflowerseed Oil",
    1201: "Cottonseed",
    1202: "Cottonseed cake & meal",
    1203: "Cottonseed Oil",
    1301: "Cotton- Am Pima",
    1401: 'Cotton- Upland 1 1/16" & over',
    1402: 'Cotton- Upland 1"-1 1/16" & over',
    1403: 'Cotton- Upland under 1"',
    1404: "All Upland Cotton",
    1498: "Rice - LG Rough",
    1499: "Rice- Med, Short,Other Rough",
    1501: "Rice- LG Brown",
    1502: "Rice- Med,Short, Other Brown",
    1503: "Rice - Long Grain, Milled",
    1504: "Rice- Med,Short,Other Milled",
    1505: "All Rice",
    1601: "Cattle Hides - Whole - Excluding Wet Blues",
    1602: "Calf Skins - Whole - Excluding Wet Blues",
    1603: "Kip Skins - Whole - Excluding Wet Blues",
    1604: "Cattle Hides-Cut into Croupons, etc-excl Wet Blues",
    1605: "Cattle Hides and Skins-other-excluding Wet Blues",
    1606: "Cattle Wet Blues-Unsplit (Whole or Sided)",
    1607: "Cattle Wet Blues-Grain Splits (Whole or Sided)",
    1608: "Cattle Wet Blues-Splits-Excluding Grain Splits",
    1701: "Fresh, Chilled, or Frozen Muscle Cuts of Beef",
    1702: "Fresh, Chilled, or Frozen Muscle Cuts of Pork",
}

# The 10 codes the fetcher requested before the widening.  They must survive it:
# every one is a live silver partition with history back to 1990.
_LEGACY_CODES = [101, 102, 103, 104, 107, 401, 701, 801, 901, 902]

# Codes that never existed in the source but sat in the fetcher's reserved set.
_PHANTOM_CODES = [1302, 3202]

# The census's named-but-absent blocks -- the reason this widening exists.
_CRITICAL_CODES = [
    1401, 1402, 1403, 1404,                    # upland cotton
    1498, 1499, 1501, 1502, 1503, 1504, 1505,  # the full rice complex
    1701,                                      # beef muscle cuts
    1702,                                      # pork muscle cuts
]


class TestTargetCommodityCodes:
    def test_is_the_full_measured_universe(self):
        assert sorted(F._TARGET_COMMODITY_CODES) == sorted(_MEASURED_UNIVERSE)

    def test_universe_is_44_codes(self):
        assert len(F._TARGET_COMMODITY_CODES) == 44

    def test_no_duplicate_codes(self):
        assert len(set(F._TARGET_COMMODITY_CODES)) == len(F._TARGET_COMMODITY_CODES)

    def test_all_codes_are_ints(self):
        # bool is an int subclass -- require the exact type, since the code goes
        # straight into the S3 key and the request URL.
        assert all(type(code) is int for code in F._TARGET_COMMODITY_CODES)

    def test_codes_are_ascending(self):
        assert F._TARGET_COMMODITY_CODES == sorted(F._TARGET_COMMODITY_CODES)

    def test_legacy_ten_survive_the_widening(self):
        missing = [c for c in _LEGACY_CODES if c not in F._TARGET_COMMODITY_CODES]
        assert missing == []

    def test_critical_codes_present(self):
        missing = [c for c in _CRITICAL_CODES if c not in F._TARGET_COMMODITY_CODES]
        assert missing == []

    def test_phantom_codes_absent(self):
        present = [c for c in _PHANTOM_CODES if c in F._TARGET_COMMODITY_CODES]
        assert present == []

    def test_no_code_outside_the_measured_universe(self):
        extra = [c for c in F._TARGET_COMMODITY_CODES if c not in _MEASURED_UNIVERSE]
        assert extra == []


class TestReservedSetRemoved:
    def test_cotton_rice_frozenset_is_gone(self):
        # _COTTON_RICE_CODES held the two phantoms; it must not come back.
        assert not hasattr(F, "_COTTON_RICE_CODES")

    def test_no_phantom_in_any_marketing_year_group(self):
        groups = F._WHEAT_CODES | F._COTTON_CODES | F._RICE_CODES
        assert [c for c in _PHANTOM_CODES if c in groups] == []

    def test_marketing_year_groups_are_inside_the_universe(self):
        groups = F._WHEAT_CODES | F._COTTON_CODES | F._RICE_CODES
        assert [c for c in sorted(groups) if c not in _MEASURED_UNIVERSE] == []


class TestMarketingYearStartMonth:
    def test_wheat_group_opens_in_june(self):
        for code in (101, 102, 103, 104, 105, 106, 107, 201):
            assert F._marketing_year_start_month(code) == 6

    def test_cotton_complex_opens_in_august(self):
        for code in (1201, 1202, 1203, 1301, 1401, 1402, 1403, 1404):
            assert F._marketing_year_start_month(code) == 8

    def test_rice_complex_opens_in_august(self):
        for code in (1498, 1499, 1501, 1502, 1503, 1504, 1505):
            assert F._marketing_year_start_month(code) == 8

    def test_everything_else_falls_to_september(self):
        for code in (301, 401, 501, 601, 701, 801, 901, 902, 1001, 1101, 1110,
                     1601, 1608, 1701, 1702):
            assert F._marketing_year_start_month(code) == 9

    def test_every_code_resolves_to_a_start_month_in_jan_sep(self):
        # The weekly {current, current+1} pair only provably covers the true
        # marketing year when the start month is <= 9 (see the module comment).
        for code in F._TARGET_COMMODITY_CODES:
            assert 1 <= F._marketing_year_start_month(code) <= 9


class TestEveryCopyOfTheUniverseStaysEqual:
    """The latent re-narrowing: four files held their own 10-code default or their own
    marketing-year groups.  The fetcher is the ONLY authority; everything else imports
    it or is pinned equal to it here."""

    @pytest.mark.parametrize("module_name", _BACKFILL_MODULES)
    def test_backfill_scripts_use_the_fetcher_list_itself(self, module_name: str) -> None:
        mod = importlib.import_module(module_name)
        assert mod._DEFAULT_COMMODITY_CODES == list(F._TARGET_COMMODITY_CODES)

    @pytest.mark.parametrize("module_name", _BACKFILL_MODULES)
    def test_backfill_scripts_hold_no_private_code_literal(self, module_name: str) -> None:
        """An IMPORT, not a copy: a re-typed list is exactly how the widening gets undone."""
        source = Path(importlib.import_module(module_name).__file__).read_text(encoding="utf-8")
        assert "[101, 102, 103, 104, 107, 401, 701, 801, 901, 902]" not in source
        assert "_TARGET_COMMODITY_CODES" in source

    def test_glue_default_codes_are_the_full_measured_universe(self) -> None:
        """The Glue job runs standalone and cannot import the fetcher, so it mirrors the
        list -- and the mirror is pinned EQUAL here rather than trusted."""
        glue_codes = _module_constant(_GLUE_JOB, "_DEFAULT_COMMODITY_CODES")
        assert sorted(glue_codes) == sorted(F._TARGET_COMMODITY_CODES)
        assert len(glue_codes) == 44

    @pytest.mark.parametrize("group", ["_WHEAT_CODES", "_COTTON_CODES", "_RICE_CODES"])
    def test_glue_marketing_year_groups_equal_the_fetchers(self, group: str) -> None:
        assert _module_constant(_GLUE_JOB, group) == getattr(F, group)

    @pytest.mark.parametrize("group", ["_WHEAT_CODES", "_COTTON_CODES", "_RICE_CODES"])
    def test_dag_marketing_year_groups_equal_the_fetchers(self, group: str) -> None:
        assert _module_constant(_AIRFLOW_DAG, group) == getattr(F, group)

    @pytest.mark.parametrize("path", [_GLUE_JOB, _AIRFLOW_DAG])
    def test_the_phantom_frozenset_is_gone_from_both_mirrors(self, path: Path) -> None:
        """_COTTON_RICE_CODES held 1302 and 3202 -- codes that do not exist in the source --
        while omitting every real upland cotton and rice code.  It must not come back."""
        with pytest.raises(AssertionError):
            _module_constant(path, "_COTTON_RICE_CODES")

    @pytest.mark.parametrize("path", [_GLUE_JOB, _AIRFLOW_DAG])
    def test_no_mirror_carries_a_phantom_code_or_an_off_universe_code(self, path: Path) -> None:
        groups: set[int] = set()
        for group in ("_WHEAT_CODES", "_COTTON_CODES", "_RICE_CODES"):
            groups |= set(_module_constant(path, group))
        assert [c for c in _PHANTOM_CODES if c in groups] == []
        assert [c for c in sorted(groups) if c not in _MEASURED_UNIVERSE] == []


class TestWeeklyPairCoversCalendarYearCommodities:
    """ESR runs livestock/hides on a calendar year; the Sep 1 default must still
    reach it.  Weekly mode fetches {current, current+1} for every code."""

    def test_calendar_year_is_always_in_the_weekly_pair(self):
        for code in (1601, 1602, 1603, 1604, 1605, 1606, 1607, 1608, 1701, 1702):
            for month in range(1, 13):
                reference = datetime.date(2026, month, 15)
                current = F._current_marketing_year(code, reference)
                assert reference.year in (current, current + 1), (
                    f"code={code} month={month} pair={(current, current + 1)}"
                )
