"""THE CATALOG DEBT A WRITER-SCHEMA PIN CREATES, and why it is not an owner's spare-time errand.

THE FINDING THIS DECK EXISTS FOR (review 2026-09-09, MAJOR). The sibling sweep flipped
``writer_schema_pinned`` on six contracts and every block note said the same reassuring thing:
"live bytes do not change until an owner-gated ``--force-overwrite`` canonical rewrite runs". THAT
IS FALSE. Measured in ``infra/terraform/envs/dev/dag_schedules.auto.tfvars.json``: all four families
have an ENABLED schedule whose Step Functions ``promote`` phase is ``"mode": "autonomous"`` and
whose command already IS that rewrite. ``modules/step_functions/main.tf`` enters ``Promote`` as a
plain ``Map`` over ``$.promote.tasks`` on any GREEN gate, and ``jobs/audit/silver_rebuild_gate`` is
a value/footer census -- ``src/leviathan/silver/publisher.py`` carries no ``glue_type``, no
``ALTER``, no type reconciliation of any kind, so NOTHING on that path can see a parquet-vs-Glue
mismatch. The trigger for the rewrite is therefore the WORKER IMAGE REPIN, not a human decision.

WHY THAT MATTERS ON EXACTLY TWO TABLES. INV-2 pins the contract's ``target_arrow_type``, which is
the SILVER-F062 WIDEN target -- deliberately wider than what the live objects carry. For four of the
six newly pinned contracts the widen is a no-op (the declared target already equals what the Glue
column declares). For ``silver_fgis`` and ``silver_modis_ndvi`` it is not, and a DOUBLE written
under a Glue ``float`` column, or an INT64 under an ``int``, is an Athena READ ERROR on every object
of the table -- 223 of them for fgis (next fire 2026-09-10 12:00Z), 10,532 for modis
(next fire 2026-09-14 09:00Z).

SO THE ORDER IS: land the catalog ALTERs (after the F011 DDL diff), or disable those two schedules,
BEFORE the worker image carrying the pins is repinned. This deck is what keeps that debt NAMED. It
does not enforce the order -- terraform and Glue are outside the lane -- it enforces that the list
of tables owing an ALTER is exactly the measured one, so a seventh contract cannot join the flag
carrying a silent widen, and so the day the ALTERs land somebody has to come back here and empty
the expectation.

AWS-free, no network: the tracked registry YAMLs, the tracked schedules tfvars, and source text.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[3]
_SCHEDULES = _REPO / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"

# A Glue column type -> the arrow/parquet type Athena expects to find in the object. Deliberately
# explicit and fail-closed: an unmapped glue type fails the deck rather than being assumed safe.
_GLUE_TO_ARROW = {
    "int": "int32", "bigint": "int64", "smallint": "int16", "tinyint": "int8",
    "float": "float32", "double": "float64", "string": "string",
    "date": "date32[day]", "timestamp": "timestamp[us]", "boolean": "bool", "bool": "bool",
}
# INV-2 target tokens and Glue spellings that name the SAME physical type.
_NORMALISE = {"double": "float64", "large_string": "string", "boolean": "bool", "float": "float32"}

# MEASURED 2026-09-09 over all 50 tracked contracts: the complete catalog debt of the 21 tables
# whose writer pins its schema. EMPTY THIS as each ALTER lands and the R0 baseline is re-captured.
EXPECTED_DEBT = {
    "silver_fgis": {"week_of_marketing_year": ("int", "int64")},
    "silver_modis_ndvi": {
        "year": ("smallint", "int64"),
        "period": ("tinyint", "int64"),
        "pixel_reliability": ("tinyint", "int64"),
        "latitude": ("float", "float64"),
        "longitude": ("float", "float64"),
        "ndvi_raw": ("float", "float64"),
        "ndvi": ("float", "float64"),
        "ndvi_z_score": ("float", "float64"),
        "baseline_mean": ("float", "float64"),
        "baseline_std": ("float", "float64"),
    },
}

# The four families the sibling sweep touched, and the schedule each rides.
_FAMILY_SCHEDULES = {
    "fgis": "cron(0 12 ? * THU *)",
    "modis_biweekly": "cron(0 9 ? * MON *)",
    "nass_crop_progress": "cron(0 9 ? * TUE *)",
    "fnc_colombia": "cron(0 12 15 * ? *)",
}


def _norm(token) -> str:
    t = str(token or "").strip().lower()
    return _NORMALISE.get(t, t)


def _catalog_debt(contract: dict) -> dict:
    """{column: (glue_type, pinned target)} for every column the pin would write untypeable."""
    debt = {}
    for col in contract.get("physical_columns") or []:
        glue = str(col.get("glue_type") or "").strip().lower()
        if not glue:
            continue                       # a column with no catalog declaration owes nothing
        assert glue in _GLUE_TO_ARROW, f"unmapped glue type {glue!r} on {col['name']!r}"
        if _norm(_GLUE_TO_ARROW[glue]) != _norm(col.get("target_arrow_type")):
            debt[col["name"]] = (glue, str(col.get("target_arrow_type")))
    return debt


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.fixture(scope="module")
def schedules():
    return json.loads(_SCHEDULES.read_text(encoding="utf-8"))["dag_schedules"]


def _promote(schedules: dict, family: str) -> dict:
    return json.loads(json.loads(schedules[family]["input_json"])["Input"])["promote"]


# ---------------------------------------------------------------------------
# 1. The debt itself.
# ---------------------------------------------------------------------------
def test_the_catalog_debt_of_every_pinned_writer_is_exactly_the_measured_two_tables(registry):
    """THE LIST, pinned. Any contract that joins ``writer_schema_pinned`` carrying a widen the Glue
    catalog does not declare breaks this test, and the person flipping the flag has to decide the
    ALTER-before-repin order before the flag can land."""
    got = {}
    for name in registry.names():
        c = registry.table(name)
        if not c.get("writer_schema_pinned"):
            continue
        debt = _catalog_debt(c)
        if debt:
            got[name] = debt
    assert got == EXPECTED_DEBT


def test_the_four_newly_pinned_families_owe_nothing_except_fgis_and_modis(registry):
    """The sweep's other four contracts are catalog-safe, which is WHY their autonomous promote may
    run on the repin while these two must not."""
    for name in ("silver_nass_annual", "silver_nass_crop_progress",
                 "silver_fnc_colombia_monthly", "silver_fnc_colombia_area_department",
                 "silver_fnc_colombia_exports_port_type"):
        c = registry.table(name)
        assert c.get("writer_schema_pinned") is True
        assert _catalog_debt(c) == {}, name


def test_every_debt_column_is_already_declared_as_an_f062_widen(registry):
    """The debt is not a discovery this deck invented: each column is in its contract's own
    ``drift_summary`` as a SILVER-F062 ``widen_*``. Pinning the two together means neither can drift
    from the other -- a widen dropped from the drift summary, or a target type changed without one,
    fails here."""
    for name, debt in EXPECTED_DEBT.items():
        drift = registry.table(name).get("drift_summary") or []
        widens = {e["column"]: e for e in drift if str(e.get("kind", "")).startswith("widen")}
        assert set(widens) == set(debt), name
        for col, (glue, target) in debt.items():
            assert widens[col]["glue_type"] == glue
            assert widens[col]["target"] == target
            assert widens[col]["owner_package"] == "SILVER-F062"

    for name in registry.names():
        c = registry.table(name)
        if not c.get("writer_schema_pinned") or name in EXPECTED_DEBT:
            continue
        widens = [e for e in (c.get("drift_summary") or [])
                  if str(e.get("kind", "")).startswith("widen")]
        assert widens == [], f"{name} declares an F062 widen but is not on the debt list"


# ---------------------------------------------------------------------------
# 2. The trigger: the promote phase nobody gates.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("family,cron", sorted(_FAMILY_SCHEDULES.items()))
def test_an_enabled_schedule_rewrites_canonical_with_no_human_in_the_loop(family, cron, schedules):
    """THE MEASUREMENT BEHIND THE CORRECTED BLOCK NOTES. While a family's schedule is ENABLED, its
    promote phase is autonomous and its command is the canonical ``--force-overwrite`` rewrite: the
    first GREEN gate after the worker image is repinned rewrites that family's objects. A family
    whose schedule has been DISABLED (the documented remedy for the two tables owing an ALTER) skips
    -- holding the DAG is a fix, not a regression."""
    entry = schedules[family]
    assert entry["cron"] == cron, (
        f"{family}'s cron moved to {entry['cron']!r}: the writers' block notes quote this schedule "
        "and the next-fire date derived from it, so update them in the same change")
    if not entry.get("enabled"):
        pytest.skip(f"{family} schedule is disabled -- canonical is held, which is the remedy")
    promote = _promote(schedules, family)
    assert promote.get("mode") == "autonomous"
    assert promote.get("tasks"), family
    for task in promote["tasks"]:
        cmd = task["command"]
        assert "canonical" in cmd, cmd
        assert any(a.startswith("--force") and "overwrite" in a for a in cmd), cmd


def test_the_two_debt_tables_ride_an_autonomous_promote_that_must_be_ordered(schedules):
    """The finding in one assertion: the tables that owe an ALTER are on schedules that will rewrite
    them without asking. Landing the ALTERs (then re-capturing the baseline so EXPECTED_DEBT empties)
    or disabling the schedule are the two ways this stops being true."""
    for family, table in (("fgis", "silver_fgis"), ("modis_biweekly", "silver_modis_ndvi")):
        assert table in EXPECTED_DEBT
        if not schedules[family].get("enabled"):
            continue                       # held: the ALTER is no longer a race
        assert _promote(schedules, family).get("mode") == "autonomous"


# ---------------------------------------------------------------------------
# 3. The retired sentence.
# ---------------------------------------------------------------------------
_CORRECTED_SOURCES = [
    "jobs/batch/nass_annual_silver_task.py",
    "jobs/batch/nass_crop_progress_silver_task.py",
    "jobs/batch/fgis_silver_task.py",
    "jobs/batch/fnc_colombia_silver_task.py",
    "jobs/batch/modis_ndvi_bronze_to_silver_task.py",
    "scripts/silver/gen_registry_from_baseline.py",
    "src/leviathan/silver/flat_producer.py",
    "tests/unit/silver/test_nass_annual_writer_schema_pin.py",
]


@pytest.mark.parametrize("rel", _CORRECTED_SOURCES)
def test_the_false_owner_gated_claim_does_not_come_back(rel):
    """A one-line regression pin on a MAJOR that was pure prose. Every one of these files told a
    reader the canonical rewrite waits for an owner; the promote phase says otherwise. The phrase is
    banned rather than the word: "owner-gated" is a true and useful description elsewhere in the
    estate (the ESR label promotion, the D-SG G1-6 supersede), just not of THIS rewrite."""
    text = (_REPO / rel).read_text(encoding="utf-8")
    for banned in ("Live bytes do not change until an owner-gated",
                   "Nothing changes until that owner-gated",
                   "do NOT change until an owner-gated",
                   "is an owner-gated operational step"):
        assert banned not in text, f"{rel}: the corrected claim was reverted ({banned!r})"
