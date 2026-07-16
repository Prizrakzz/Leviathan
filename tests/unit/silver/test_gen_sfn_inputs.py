"""A1-A2 A-W6: the per-family DAG chain descriptors + the SFN-input generator.

Asserts: every Section-3 descriptor validates (schema + rule lint); the generator round-trips
byte-identically (the --check idempotency gate); every module-form task carries '-m'; and the six
module-form producers named in the plan are EXACTLY the [m] set. AWS-free, deterministic.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_GEN = _REPO / "scripts" / "silver" / "gen_sfn_inputs.py"
_DAGS = _REPO / "configs" / "silver" / "dags"
_RENDERED = _DAGS / "_rendered"
_SCHEMA = _DAGS / "dag_descriptor.schema.json"

# The 24 Section-3 schedules (one descriptor each; gold_weather_z folds into weather_daily).
EXPECTED_SCHEDULES = {
    "fx_macro_daily", "enso_monthly", "pink_sheet_monthly", "mpob", "mpoc", "icco_cocoa",
    "ams_cotton_quality", "fnc_colombia", "production_conab", "nass_citrus", "sagis_weekly",
    "wap", "cot", "food_cpi", "futures_prices", "unica", "psd_monthly", "nass_crop_progress",
    "fgis", "modis_biweekly", "weather_daily", "esr_weekly", "wasde_monthly", "production_faostat",
}

# The six module-form producers named in A-W6 (invocation form [m] = -m jobs.batch.X).
EXPECTED_MODULE_PRODUCERS = {
    "frankfurter_fx", "noaa_iod", "wap_silver", "sagis_deliveries", "quandl_chris", "psd_silver",
}


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_sfn_inputs", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def descriptors(gen):
    return gen.load_descriptors()


# ---------------------------------------------------------------------------
# Coverage: every Section-3 row has a descriptor.
# ---------------------------------------------------------------------------
def test_every_section3_schedule_has_a_descriptor(descriptors):
    assert set(descriptors) == EXPECTED_SCHEDULES
    assert len(descriptors) == 24


def test_filename_stem_matches_schedule(descriptors):
    for stem, d in descriptors.items():
        assert d["schedule"] == stem, f"{stem}: schedule field != filename stem"


# ---------------------------------------------------------------------------
# Deliverable 4a: every descriptor validates (rule lint + declarative schema).
# ---------------------------------------------------------------------------
def test_all_descriptors_lint_clean(gen, descriptors):
    violations = gen.lint_all(descriptors)
    assert violations == [], "descriptor lint violations:\n  - " + "\n  - ".join(violations)


def test_all_descriptors_match_schema(descriptors):
    """Validate each descriptor against dag_descriptor.schema.json via the repo's self-contained
    subset validator (no external jsonschema dependency)."""
    from leviathan.silver.registry import _validate

    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    for stem, d in descriptors.items():
        errors: list[str] = []
        _validate(d, schema, stem, errors)
        assert errors == [], f"{stem}: schema errors {errors}"


# ---------------------------------------------------------------------------
# Deliverable 4b: the generator round-trips (deterministic + byte-identical --check).
# ---------------------------------------------------------------------------
def test_render_is_deterministic_in_memory(gen, descriptors):
    first = gen.render_all(descriptors)
    second = gen.render_all(descriptors)
    assert first == second


def test_checked_in_rendered_tree_matches_fresh_render(gen, descriptors):
    rendered = gen.render_all(descriptors)
    drift = []
    for stem, text in rendered.items():
        on_disk = _RENDERED / f"{stem}.input.json"
        if not on_disk.exists() or on_disk.read_text(encoding="utf-8") != text:
            drift.append(stem)
    assert drift == [], f"rendered-input drift; re-run gen_sfn_inputs.py: {drift}"


def test_check_mode_exit_zero(gen):
    assert gen.generate(check=True) == 0


def test_every_schedule_has_a_rendered_input(descriptors):
    on_disk = {p.name[: -len(".input.json")] for p in _RENDERED.glob("*.input.json")}
    assert on_disk == set(descriptors)


# ---------------------------------------------------------------------------
# Deliverable 4c/4d: module-form producers carry '-m'; the [m] set is EXACTLY the six.
# ---------------------------------------------------------------------------
def _iter_tasks(descriptors):
    for stem, d in descriptors.items():
        for phase in d["phases"]:
            for t in phase["tasks"]:
                yield stem, phase["name"], t


def test_module_form_tasks_carry_dash_m(descriptors):
    for stem, _phase, t in _iter_tasks(descriptors):
        if t.get("invocation_form") == "m":
            cmd = t.get("command", [])
            assert cmd and cmd[0] == "-m", f"{stem}/{t.get('id')}: module form must carry '-m'"
            assert cmd[1].startswith("jobs."), f"{stem}/{t.get('id')}: '-m' must name a jobs.* module"


def test_exactly_six_module_form_producers(descriptors):
    module_ids = {t["id"] for _s, _p, t in _iter_tasks(descriptors) if t.get("invocation_form") == "m"}
    assert module_ids == EXPECTED_MODULE_PRODUCERS


def test_module_form_only_on_silver_producers(descriptors):
    """The six -m tasks are all publishing silver producers (never fetch/bronze)."""
    for stem, phase, t in _iter_tasks(descriptors):
        if t.get("invocation_form") == "m":
            assert phase in ("silver", "gold"), f"{stem}/{t['id']}: -m task in {phase} phase"
            assert t.get("publishes") is True, f"{stem}/{t['id']}: -m task must be a publisher"


def test_invocation_forms_are_known(descriptors):
    for stem, _p, t in _iter_tasks(descriptors):
        assert t.get("invocation_form") in {"m", "s", "g"}, f"{stem}/{t.get('id')}"


# ---------------------------------------------------------------------------
# Rendered inputs conform to the A-W2 schema shape.
# ---------------------------------------------------------------------------
def test_rendered_inputs_have_aw2_keys(gen, descriptors):
    aw2_keys = {"family", "phases", "gate_tables", "asof", "gate_baseline_uri", "promote", "auth_mode"}
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        assert set(rendered) == aw2_keys, f"{stem}: rendered keys {set(rendered)}"
        assert rendered["promote"]["mode"] in {"autonomous", "stop_and_notify", "post_publish_audit"}


def test_glue_tasks_render_glue_job_not_jobdef(gen, descriptors):
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        for phase in rendered["phases"]:
            for t in phase["tasks"]:
                if t["integration"] == "glue":
                    assert "glue_job" in t and "jobdef" not in t, f"{stem}: glue task shape"
                else:
                    assert "jobdef" in t and "queue" in t, f"{stem}: batch task shape"


def test_shadow_canonical_publishers_promote_with_role(gen, descriptors):
    """An autonomous family's promote re-runs every shadow_canonical publisher --publish-mode
    canonical under the silver-publisher role; a held/audit family promotes nothing."""
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        promote = rendered["promote"]
        if promote["mode"] != "autonomous":
            assert promote["tasks"] == [], f"{stem}: non-autonomous family must not self-promote"
            continue
        n_shadow = sum(
            1
            for phase in d["phases"]
            for t in phase["tasks"]
            if phase["name"] in ("silver", "gold")
            and t.get("publish_mode") == "shadow_canonical"
            and t.get("publishes")
        )
        assert len(promote["tasks"]) == n_shadow, f"{stem}: promote task count"
        for t in promote["tasks"]:
            assert t.get("role") == gen.SILVER_PUBLISHER_ROLE
            assert t["command"][-2:] == ["--publish-mode", "canonical"], f"{stem}: canonical arg"


def test_silver_phase_shadow_publishers_get_shadow_flag(gen, descriptors):
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        # map rendered silver/gold task command tails back to descriptor publish_mode by position
        for phase, rphase in zip(d["phases"], rendered["phases"]):
            if phase["name"] not in ("silver", "gold"):
                continue
            for dt, rt in zip(phase["tasks"], rphase["tasks"]):
                if dt.get("publish_mode") == "shadow_canonical" and dt.get("publishes"):
                    assert rt["command"][-2:] == ["--publish-mode", "shadow"], f"{stem}/{dt['id']}"


# ---------------------------------------------------------------------------
# gate_tables reference real registry tables.
# ---------------------------------------------------------------------------
def test_gate_tables_are_real_registry_tables(descriptors):
    from leviathan.silver.registry import load_registry

    reg_names = set(load_registry().names())
    for stem, d in descriptors.items():
        for tbl in d["gate_tables"]:
            assert tbl in reg_names, f"{stem}: gate table {tbl!r} not in the silver registry"


def test_family_field_matches_catalog(descriptors):
    """Each descriptor's family is a real DAG catalog family key (schedules may share a family)."""
    from leviathan.silver.dag_catalog import build_catalog

    families = set(build_catalog())
    for stem, d in descriptors.items():
        assert d["family"] in families, f"{stem}: family {d['family']!r} not a catalog family"


# ---------------------------------------------------------------------------
# Deliverable 3: the lint REJECTS each forbidden category.
# ---------------------------------------------------------------------------
def _one_descriptor(descriptors, stem="fx_macro_daily"):
    return copy.deepcopy(descriptors[stem])


def test_lint_rejects_missing_wave(gen, descriptors):
    d = _one_descriptor(descriptors)
    del d["wave"]
    assert any("wave" in v for v in gen.lint_descriptor(d, d["schedule"]))


def test_lint_rejects_missing_cron(gen, descriptors):
    d = _one_descriptor(descriptors)
    d["cron"] = ""
    assert any("cron" in v for v in gen.lint_descriptor(d, d["schedule"]))


def test_lint_rejects_missing_retry(gen, descriptors):
    d = _one_descriptor(descriptors)
    del d["retry"]
    assert any("retry" in v for v in gen.lint_descriptor(d, d["schedule"]))


def test_lint_rejects_incomplete_retry(gen, descriptors):
    d = _one_descriptor(descriptors)
    d["retry"] = {"maximum_retry_attempts": 3}
    assert any("retry" in v for v in gen.lint_descriptor(d, d["schedule"]))


def test_lint_rejects_unknown_invocation_form(gen, descriptors):
    d = _one_descriptor(descriptors)
    d["phases"][0]["tasks"][0]["invocation_form"] = "x"
    assert any("invocation_form" in v for v in gen.lint_descriptor(d, d["schedule"]))


def test_lint_rejects_module_form_without_dash_m(gen, descriptors):
    d = _one_descriptor(descriptors)  # fx_macro_daily's sole task is module-form
    d["phases"][0]["tasks"][0]["command"] = ["jobs/batch/frankfurter_fx_task.py"]
    assert any("-m" in v for v in gen.lint_descriptor(d, d["schedule"]))


def test_lint_rejects_classb_autonomous_before_retrofit(gen, descriptors):
    d = _one_descriptor(descriptors, "cot")  # CLASS-B, retrofit not landed
    d["promote_mode"] = "autonomous"
    viol = gen.lint_descriptor(d, d["schedule"])
    assert any("autonomous promote before the A-W4 retrofit" in v for v in viol)


def test_lint_accepts_classb_after_retrofit_landed(gen, descriptors):
    """The guard clears once retrofit_landed flips true (the A-W4 completion signal)."""
    d = _one_descriptor(descriptors, "cot")
    d["retrofit_landed"] = True
    d["promote_mode"] = "autonomous"
    viol = gen.lint_descriptor(d, d["schedule"])
    assert not any("autonomous promote before the A-W4 retrofit" in v for v in viol)


# ---------------------------------------------------------------------------
# Wave / publish-class coherence (the A-W7 ladder invariants).
# ---------------------------------------------------------------------------
def test_all_classb_families_are_held_until_retrofit(descriptors):
    """Every retrofit_required + not-yet-landed family must be non-autonomous (held DISABLED)."""
    for stem, d in descriptors.items():
        if d.get("retrofit_required") and not d.get("retrofit_landed"):
            assert d["promote_mode"] != "autonomous", f"{stem}: CLASS-B must be held"


def test_wave2_is_exactly_the_classb_set(descriptors):
    wave2 = {s for s, d in descriptors.items() if d["wave"] == 2}
    retrofit = {s for s, d in descriptors.items() if d.get("retrofit_required") and not d.get("retrofit_landed")}
    assert wave2 == retrofit == {
        "cot", "food_cpi", "futures_prices", "unica", "psd_monthly",
        "nass_crop_progress", "fgis", "modis_biweekly",
    }


def test_wave0_is_the_single_platform_proof(descriptors):
    wave0 = {s for s, d in descriptors.items() if d["wave"] == 0}
    assert wave0 == {"fx_macro_daily"}
