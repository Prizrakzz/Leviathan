"""BF-W2 D1 pin + pure-plan coverage for jobs/submit/submit_batch_esr_weekly_promote.py.

D1 (runbook B2_phase0 step 1): the submit wrapper targeted the NONEXISTENT jobdef name
"leviathan-dev-esr-bronze"; the registered Batch jobdef family is "leviathan-dev-usda-esr-bronze"
(aws batch describe-job-definitions, laneA_esr.md section 4.2). A wrong name dies at submit time
with ClientException -- AFTER the gated approval ceremony -- so the name is pinned here.

jobs/ is not an importable package (pytest pythonpath = ["src"] only); load by file path, the
test_submit_evidence_wrappers.py convention.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SUBMIT_DIR = Path(__file__).resolve().parents[2] / "jobs" / "submit"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SUBMIT_DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


promote = _load("submit_batch_esr_weekly_promote")

_RAW = "raw/production/source=usda_esr"


def test_jobdef_name_is_the_registered_family_d1_pin():
    # the "usda" infix is load-bearing: the short form does not exist in AWS Batch.
    assert promote._JOB_DEF_NAME == "leviathan-dev-usda-esr-bronze"


def test_plan_selects_only_the_target_as_of_weekly_keys():
    keys = [
        # weekly snapshot keys for two as_of vintages
        f"{_RAW}/commodity_code=401/market_year=2026/as_of=20260712/all_countries.json",
        f"{_RAW}/commodity_code=401/market_year=2025/as_of=20260712/all_countries.json",
        f"{_RAW}/commodity_code=801/market_year=2026/as_of=20260719/all_countries.json",
        # backfill keys carry NO as_of= segment and must never enter a weekly plan
        f"{_RAW}/commodity_code=401/market_year=1990/all_countries.json",
    ]
    plan = promote.build_promotion_plan(keys, "20260712")
    assert len(plan) == 2
    assert all(p["as_of"] == "20260712" for p in plan)
    assert {(p["commodity_code"], p["market_year"]) for p in plan} == {(401, 2025), (401, 2026)}


def test_plan_maps_raw_key_to_bronze_partition_layout():
    key = f"{_RAW}/commodity_code=401/market_year=2026/as_of=20260712/all_countries.json"
    plan = promote.build_promotion_plan([key], "20260712")
    assert plan[0]["bronze_key"] == ("bronze/production/source=usda_esr/commodity_code=401"
                                     "/market_year=2026/as_of=20260712/part-000.parquet")


def test_plan_skips_unparseable_keys():
    junk = [f"{_RAW}/as_of=20260712/stray.json",                       # no code/year segments
            f"{_RAW}/commodity_code=401/as_of=20260712/x.json"]        # no market_year
    assert promote.build_promotion_plan(junk, "20260712") == []
