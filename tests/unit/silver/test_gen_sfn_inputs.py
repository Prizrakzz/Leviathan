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

# The 24 Section-3 schedules (one descriptor each; gold_weather_z folds into weather_daily) PLUS
# the two PRICE_AND_PLAYBOOKS additions. Neither is a Section-3 row: they are the first new-wave
# class-A registered-partition chains (family futures_eod, wave 3), landed alongside the
# silver_futures_eod producers.
#   futures_eod_databento -- W2, the paid vendor leg, TUE-SAT 08:00 UTC (final settlements are
#       published the calendar day AFTER the session).
#   futures_eod_free      -- W1a/W1b, the four FREE venues (CZCE, JSE/SAFEX, CEPEA, MIAX) on ONE
#       cron at 22:30 UTC MON-FRI, which is after the latest of the four same-day publications.
#       They share one table and one gate, so one schedule rather than four keeps one census.
EXPECTED_SCHEDULES = {
    "fx_macro_daily", "enso_monthly", "pink_sheet_monthly", "mpob", "mpoc", "icco_cocoa",
    "ams_cotton_quality", "fnc_colombia", "production_conab", "nass_citrus", "sagis_weekly",
    "wap", "cot", "food_cpi", "futures_prices", "unica", "psd_monthly", "nass_crop_progress",
    "fgis", "modis_biweekly", "weather_daily", "esr_weekly", "wasde_monthly", "production_faostat",
    "futures_eod_databento", "futures_eod_free",
}

# The module-form producers named in A-W6 (invocation form [m] = -m jobs.batch.X).
# quandl_chris DEFERRED from the futures_prices chain 2026-07-17 (NASDAQ_API_KEY never
# provisioned; credentials are user-handled) -- re-add here when the task returns.
# quandl_chris RETIRED permanently 2026-07-17: Nasdaq paywalled CHRIS (403 on all
# series with a free key). yfinance is the futures source.
EXPECTED_MODULE_PRODUCERS = {
    "frankfurter_fx", "noaa_iod", "wap_silver", "sagis_deliveries", "psd_silver",
    "sagis_cec_silver",  # restored 2026-07-18 (task #118): raw->silver-direct era-aware producer
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
    assert len(descriptors) == 26


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


def test_module_form_producer_census(descriptors):
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
    aw2_keys = {"family", "phases", "gate_tables", "asof", "gate_baseline_uri", "promote",
                "auth_mode", "gate"}
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        assert set(rendered) == aw2_keys, f"{stem}: rendered keys {set(rendered)}"
        assert rendered["promote"]["mode"] in {"autonomous", "stop_and_notify", "post_publish_audit"}


def test_phases_render_as_object_with_fetch_bronze_silver(gen, descriptors):
    """The machine Maps over a fixed $.phases.<p>.tasks ItemsPath; a MISSING path errors the Map, so
    every rendered input carries EXACTLY {fetch, bronze, silver}, each an object with a tasks list.
    (There is no Gold Map -- a descriptor 'gold' phase folds into silver.)"""
    for stem, d in descriptors.items():
        phases = gen.render_input(d)["phases"]
        assert isinstance(phases, dict), f"{stem}: phases must be an OBJECT, not a list"
        assert set(phases) == {"fetch", "bronze", "silver"}, f"{stem}: phase keys {set(phases)}"
        for pname, pval in phases.items():
            assert set(pval) == {"tasks"} and isinstance(pval["tasks"], list), f"{stem}/{pname}"


def test_absent_phases_render_as_empty_task_lists(gen, descriptors):
    """fx_macro_daily declares only a silver phase; fetch+bronze must still be present (empty [] --
    a missing ItemsPath crashes the Map)."""
    for stem in ("fx_macro_daily",):
        phases = gen.render_input(descriptors[stem])["phases"]
        assert phases["fetch"]["tasks"] == [] and phases["bronze"]["tasks"] == [], stem
        assert phases["silver"]["tasks"], f"{stem}: silver must be populated"


def test_nass_citrus_is_fetch_bronze_silver(gen, descriptors):
    """SILVER-F056 stale-producer restore: nass_citrus is no longer silver-only -- its fetch phase
    runs the season-scoped citrus fetch and its bronze phase runs the tracked raw->bronze producer,
    so silver can advance past the frozen corpus."""
    phases = gen.render_input(descriptors["nass_citrus"])["phases"]
    fetch = " ".join(phases["fetch"]["tasks"][0]["command"])
    bronze = " ".join(phases["bronze"]["tasks"][0]["command"])
    assert "fetch_usda_nass_citrus.py" in fetch and "--current-season" in fetch
    assert "nass_citrus_bronze_task.py" in bronze
    assert phases["silver"]["tasks"], "silver must remain populated"


def test_unica_biweekly_fetch_discovers_current_season(gen, descriptors):
    """DISCOVERY RETROFIT: the unica biweekly fetch previously ran with NO args -- a manifest-only
    download (no --discover), so genuinely new bulletins (the whole 2026/27 season) never entered the
    manifest and the fetch was a green no-op forever. It must now run --discover --current-season
    --asof <scheduled-time> so the live JS-portal enumeration is scoped to the current harvest season
    and auto-advances each April."""
    d = descriptors["unica"]
    assert gen.lint_descriptor(d, "unica") == [], gen.lint_descriptor(d, "unica")
    fetch_tasks = gen.render_input(d)["phases"]["fetch"]["tasks"]
    biweekly = next(t for t in fetch_tasks if "fetch_unica_biweekly.py" in t["command"][0])
    assert biweekly["command"] == [
        "jobs/ingest/fetch_unica_biweekly.py",
        "--discover", "--current-season", "--asof", "<aws.scheduler.scheduled-time>",
    ], biweekly["command"]


def test_unica_promotes_both_legs_on_the_folded_self_jobdef(gen, descriptors):
    """DSG-TAIL A2 (2026-08-16): the shadow-only soak ENDED -- unica armed autonomous with the
    SAME fold shape as mpob's. This test's previous form pinned promote.tasks EMPTY (the held
    CLASS-B soak, canonical via manual KMS legs); it now pins the armed contract: BOTH silver
    legs (annual/state + biweekly) run AND promote on leviathan-dev-unica-annual-state (the
    digest-pinned fold target), each promote carries the KMS pair, and the biweekly leg carries
    --force-overwrite while the annual promote renders bare (its skip-existing canonical path is
    a proven clean no-op on the static-at-ceiling table)."""
    d = descriptors["unica"]
    assert d.get("retrofit_required") and d.get("retrofit_landed"), "unica retrofit is LANDED"
    assert d["promote_mode"] == "autonomous"
    assert d["promote_jobdef"] == "leviathan-dev-unica-annual-state"
    r = gen.render_input(d)
    promote = r["promote"]["tasks"]
    assert len(promote) == 2, f"annual + biweekly must both promote, got {len(promote)}"
    for t in promote:
        assert t["jobdef"] == "leviathan-dev-unica-annual-state", t["jobdef"]
        assert t["command"][-2:] == ["--publish-mode", "canonical"], t["command"]
        env = {e["Name"]: e["Value"] for e in t["env"]}
        assert env.get("LEVIATHAN_APPROVAL_MODE") == "kms"
    biweekly = next(t for t in promote if "unica_biweekly_silver_task.py" in t["command"][0])
    assert "--force-overwrite" in biweekly["command"]
    annual = next(t for t in promote if "unica_annual_state_task.py" in t["command"][0])
    assert "--force-overwrite" not in annual["command"], \
        "annual promote stays bare: skip-existing no-op on the static-at-ceiling table"
    # both silver-phase legs still stage shadow first
    shadow = [t for t in r["phases"]["silver"]["tasks"]
              if t["command"][-2:] == ["--publish-mode", "shadow"]]
    assert len(shadow) == 2, "both publishers must stage --publish-mode shadow in the silver phase"


def test_enso_iod_leg_is_cpc_and_republishes(gen, descriptors):
    """IOD RE-BASELINE (ADR_IOD_SOURCE_SWITCH, Option B): the enso chain must ingest the LIVE CPC
    ERSSTv5 IODMI, and every monthly fire must actually REPUBLISH.

    Three ways this silently regresses into a no-op, all locked here:
      * the fetch leg falling back to fetch_noaa_iod.py -- the HadISST basis frozen upstream at 2025-04
        (that script stays tracked for the _frozen provenance snapshot, but never on the schedule);
      * a missing --source cpc_iodmi -- noaa_iod_task still DEFAULTS to the legacy noaa_iod basis;
      * a missing --force-overwrite -- the task early-returns on an existing canonical object BEFORE
        the publish guard, so BOTH the shadow silver leg and the canonical promote become silent
        no-ops, canonical LastModified freezes, and the noaa_climate FreshnessLagDays alarm
        (statistic=Maximum) goes red ~45 days out and stays red.
    """
    d = descriptors["enso_monthly"]
    assert gen.lint_descriptor(d, "enso_monthly") == [], gen.lint_descriptor(d, "enso_monthly")
    r = gen.render_input(d)

    fetch_cmds = [" ".join(t["command"]) for t in r["phases"]["fetch"]["tasks"]]
    assert any("fetch_cpc_iodmi.py" in c for c in fetch_cmds), fetch_cmds
    assert not any("fetch_noaa_iod.py" in c for c in fetch_cmds), \
        "the frozen HadISST fetch must not run on the schedule"

    # the [m] IOD producer, in the silver (shadow) leg AND the canonical promote leg
    iod_legs = [t["command"] for t in r["phases"]["silver"]["tasks"] + r["promote"]["tasks"]
                if "jobs.batch.noaa_iod_task" in t["command"]]
    assert len(iod_legs) == 2, f"expected a shadow + a canonical IOD leg, got {iod_legs}"
    for cmd in iod_legs:
        assert "--source" in cmd, f"no --source: the task defaults to the frozen HadISST basis: {cmd}"
        assert cmd[cmd.index("--source") + 1] == "cpc_iodmi", cmd
        assert "--force-overwrite" in cmd, f"monthly re-run would early-return as a no-op: {cmd}"
    assert {tuple(c[-2:]) for c in iod_legs} == {("--publish-mode", "shadow"),
                                                ("--publish-mode", "canonical")}, iod_legs

    # IOD is a live monthly member of the family freshness alarm now, not a liveness-only poll
    assert "silver_noaa_iod" in d["gate_tables"]
    assert "silver_noaa_iod" not in (d.get("liveness_only_tables") or [])


def test_gold_phase_folds_into_silver(gen, descriptors):
    """weather_daily's dependent gold_weather_z has no Gold Map to run in; it folds into the silver
    phase (after the silver tasks) so it is produced before the gate."""
    r = gen.render_input(descriptors["weather_daily"])
    assert "gold" not in r["phases"], "gold must not be a rendered phase key"
    silver_cmds = [" ".join(t.get("command", [])) for t in r["phases"]["silver"]["tasks"]]
    assert any("gold_weather_z" in c for c in silver_cmds), "gold_weather_z must fold into silver"


def test_glue_tasks_render_glue_job_and_arguments_not_jobdef(gen, descriptors):
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        for phase in rendered["phases"].values():
            for t in phase["tasks"]:
                if t["integration"] == "glue":
                    assert "glue_job" in t and "jobdef" not in t, f"{stem}: glue task shape"
                    # the machine reads $.task.arguments (a missing path errors startJobRun)
                    assert isinstance(t.get("arguments"), dict), f"{stem}: glue task needs arguments"
                else:
                    assert "jobdef" in t and "queue" in t, f"{stem}: batch task shape"


def test_every_batch_task_env_is_a_list_never_object(gen, descriptors):
    """Batch ContainerOverrides.Environment shape is a LIST of {Name,Value}; {} crashes the item."""
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        tasks = [t for ph in rendered["phases"].values() for t in ph["tasks"]]
        tasks += rendered["promote"]["tasks"]
        for t in tasks:
            if t["integration"] == "batch":
                assert isinstance(t["env"], list), f"{stem}: env must be a list, got {type(t['env'])}"
                for e in t["env"]:
                    assert set(e) == {"Name", "Value"}, f"{stem}: env entry shape {e}"


def test_every_batch_jobdef_is_unversioned(gen, descriptors):
    """No trailing :N revision -- the schedule tracks the latest ACTIVE jobdef revision."""
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        jobdefs = [t["jobdef"] for ph in rendered["phases"].values() for t in ph["tasks"]
                   if t["integration"] == "batch"]
        jobdefs += [t["jobdef"] for t in rendered["promote"]["tasks"]]
        jobdefs.append(rendered["gate"]["jobdef"])
        for jd in jobdefs:
            head, sep, tail = jd.rpartition(":")
            assert not (sep and tail.isdigit()), f"{stem}: versioned jobdef {jd!r}"


def test_asof_is_the_scheduler_placeholder(gen, descriptors):
    for stem, d in descriptors.items():
        assert gen.render_input(d)["asof"] == gen.ASOF_PLACEHOLDER == "<aws.scheduler.scheduled-time>", stem


def test_gate_block_present_and_correct_for_every_family(gen, descriptors):
    """Every rendered input carries a first-class $.gate block (a null gate crashes [Gate]) with the
    platform-fixed jobdef/queue and the module-form silver_rebuild_gate command."""
    for stem, d in descriptors.items():
        gate = gen.render_input(d)["gate"]
        assert gate["jobdef"] == "leviathan-dev-silver-gate", f"{stem}: gate jobdef"
        assert gate["queue"] == "leviathan-dev-queue-ondemand", f"{stem}: gate queue"
        assert gate["command"] == [
            "-m", "jobs.audit.silver_rebuild_gate",
            "--tables", ",".join(d["gate_tables"]),
            "--asof", "<aws.scheduler.scheduled-time>",
            "--baseline-uri", d["gate_baseline_uri"],
        ], f"{stem}: gate command"


def test_shadow_canonical_publishers_promote_via_runner_with_kms(gen, descriptors):
    """An autonomous family's promote re-runs every shadow_canonical silver/gold publisher
    --publish-mode canonical under the PROMOTE JOBDEF with the KMS approval env pair (no role field --
    both legal promote jobdefs bind the publisher role). A held/audit family promotes nothing.

    The promote jobdef is the shared silver-publisher-runner UNLESS the descriptor declares a
    ``promote_jobdef`` self-promotion override, in which case it is that jobdef -- and the override is
    only ever THE jobdef this descriptor's own shadow_canonical publishers run on."""
    kms_env = [
        {"Name": "LEVIATHAN_APPROVAL_MODE", "Value": "kms"},
        {"Name": "LEVIATHAN_KMS_KEY_ID", "Value": "alias/leviathan-dev-publish-signer"},
    ]
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
        want_jobdef = d.get("promote_jobdef", "leviathan-dev-silver-publisher-runner")
        for t in promote["tasks"]:
            assert t["jobdef"] == want_jobdef, f"{stem}: promote jobdef"
            assert t["queue"] == "leviathan-dev-queue-ondemand", f"{stem}: promote queue"
            assert "role" not in t, f"{stem}: promote task must not carry a role field"
            assert t["env"] == kms_env, f"{stem}: promote env must carry the KMS pair"
            assert t["command"][-2:] == ["--publish-mode", "canonical"], f"{stem}: canonical arg"


# ---------------------------------------------------------------------------
# The promote-jobdef descriptor defect (W4/W5 leftover).
#
# THE DEFECT: gen_sfn_inputs rendered EVERY promote leg onto the shared platform runner
# leviathan-dev-silver-publisher-runner, which tracks the worker repo's floating :latest. The two
# futures_eod chains' silver jobdef leviathan-dev-futures-eod-silver is DIGEST-PINNED in terraform
# (modules/batch/main.tf, var.futures_eod_image_digest) because `databento` and `xlrd` are dependencies
# whose ABSENCE is silent -- so the machine promoted a shadow built by one image using another, and the
# digest pin bought nothing on the only leg that writes canonical.
#
# THE FAILURE IT PRODUCED, 2026-08-01 08:00Z: silver ran the floor-fix image and published a clean
# shadow; promote re-derived silver on the shared runner's older image, CERTIFIED 13/15 partitions and
# then exit-1'd on the healthy-thin ZR and OJ under the mode-blind row floor that image still carried.
# That run was completed by hand-swapping one execution's promote jobdef; these tests pin the durable
# fix so the next render cannot put it back.
# ---------------------------------------------------------------------------
FUTURES_EOD_SCHEDULES = ("futures_eod_databento", "futures_eod_free")
FUTURES_EOD_SILVER_JOBDEF = "leviathan-dev-futures-eod-silver"


def test_futures_eod_chains_self_promote_on_the_digest_pinned_jobdef(gen, descriptors):
    """Both futures_eod chains promote on leviathan-dev-futures-eod-silver, never on the shared runner
    -- in the descriptor, in the rendered input, and in the checked-in rendered tree."""
    for stem in FUTURES_EOD_SCHEDULES:
        d = descriptors[stem]
        assert d.get("promote_jobdef") == FUTURES_EOD_SILVER_JOBDEF, f"{stem}: descriptor promote_jobdef"
        promote = gen.render_input(d)["promote"]
        assert promote["mode"] == "autonomous", f"{stem}: expected an autonomous promote"
        assert promote["tasks"], f"{stem}: autonomous futures_eod chain must promote something"
        for t in promote["tasks"]:
            assert t["jobdef"] == FUTURES_EOD_SILVER_JOBDEF, f"{stem}: rendered promote jobdef"
            assert t["jobdef"] != "leviathan-dev-silver-publisher-runner", f"{stem}: shared runner back"
        on_disk = json.loads((_RENDERED / f"{stem}.input.json").read_text(encoding="utf-8"))
        assert [t["jobdef"] for t in on_disk["promote"]["tasks"]] == \
            [FUTURES_EOD_SILVER_JOBDEF] * len(promote["tasks"]), f"{stem}: checked-in tree"


def test_promote_runs_the_same_jobdef_the_shadow_ran(gen, descriptors):
    """THE INVARIANT, for every family: a promote task either runs on the shared platform runner or on
    THE jobdef the shadow it is promoting was produced by. Nothing else -- any third jobdef would be an
    unverified claim about a role (glue:CreatePartition + kms:Sign) and an image."""
    for stem, d in descriptors.items():
        own = gen._shadow_canonical_jobdefs(d)
        for t in gen.render_input(d)["promote"]["tasks"]:
            assert t["jobdef"] == "leviathan-dev-silver-publisher-runner" or t["jobdef"] in own, \
                f"{stem}: promote jobdef {t['jobdef']!r} is neither the runner nor one of {sorted(own)}"


def test_promote_jobdef_default_is_the_shared_runner(gen, descriptors):
    """Every family that does NOT declare the override still promotes on the shared runner -- the fix is
    opt-in per descriptor and changed nothing for the other 24 schedules."""
    plain = [s for s, d in descriptors.items()
             if "promote_jobdef" not in d and d.get("promote_mode") == "autonomous"]
    assert plain, "expected autonomous families without the override"
    assert set(descriptors) - set(plain) >= set(FUTURES_EOD_SCHEDULES)
    for stem in plain:
        for t in gen.render_input(descriptors[stem])["promote"]["tasks"]:
            assert t["jobdef"] == "leviathan-dev-silver-publisher-runner", f"{stem}: default runner"


def test_render_honours_a_promote_jobdef_override(gen, descriptors):
    """Mechanism, on a synthetic edit: flipping promote_jobdef moves every promote task."""
    d = copy.deepcopy(descriptors["futures_eod_free"])
    del d["promote_jobdef"]
    assert {t["jobdef"] for t in gen.render_input(d)["promote"]["tasks"]} == \
        {"leviathan-dev-silver-publisher-runner"}
    d["promote_jobdef"] = FUTURES_EOD_SILVER_JOBDEF
    assert {t["jobdef"] for t in gen.render_input(d)["promote"]["tasks"]} == {FUTURES_EOD_SILVER_JOBDEF}


def test_lint_rejects_a_foreign_promote_jobdef(gen, descriptors):
    """A promote_jobdef that is neither the platform runner nor this descriptor's own silver publisher
    is rejected: the whole safety argument is that the silver phase re-proves role + image on that
    jobdef every fire, and a third jobdef proves nothing."""
    d = copy.deepcopy(descriptors["futures_eod_databento"])
    d["promote_jobdef"] = "leviathan-dev-b3-flat-silver"
    viol = gen.lint_descriptor(d, "futures_eod_databento")
    assert any("promote_jobdef" in v for v in viol), viol


def test_lint_rejects_a_versioned_promote_jobdef(gen, descriptors):
    """A :N revision would freeze the promote leg on one Batch revision while the silver leg tracks the
    latest ACTIVE one -- the same image-parity defect wearing a different hat."""
    d = copy.deepcopy(descriptors["futures_eod_databento"])
    d["promote_jobdef"] = FUTURES_EOD_SILVER_JOBDEF + ":3"
    viol = gen.lint_descriptor(d, "futures_eod_databento")
    assert any("':N' revision" in v for v in viol), viol


def test_lint_rejects_promote_jobdef_with_no_shadow_publisher(gen, descriptors):
    """Dead config: an override on a descriptor whose silver leg never promotes."""
    d = copy.deepcopy(descriptors["futures_eod_databento"])
    for phase in d["phases"]:
        for t in phase["tasks"]:
            t.pop("publish_mode", None)
            t["publishes"] = False
    viol = gen.lint_descriptor(d, "futures_eod_databento")
    assert any("dead config" in v for v in viol), viol


def test_lint_accepts_the_explicit_platform_runner(gen, descriptors):
    """Writing the platform default out longhand stays legal (an unambiguous descriptor is not a
    violation)."""
    d = copy.deepcopy(descriptors["futures_eod_databento"])
    d["promote_jobdef"] = "leviathan-dev-silver-publisher-runner"
    assert gen.lint_descriptor(d, "futures_eod_databento") == []


# ---------------------------------------------------------------------------
# The GENERAL rule, derived from terraform rather than restated here: a producer whose jobdef is
# digest-pinned must promote on that same jobdef. Written this way it self-extends -- the day someone
# pins a second producer by digest, this test tells them the promote leg is owed the same treatment,
# which is precisely the step that was missed for futures_eod.
# ---------------------------------------------------------------------------
_BATCH_TF = _REPO / "infra" / "terraform" / "modules" / "batch" / "main.tf"


def _digest_pinned_jobdef_names() -> set[str]:
    """Names of aws_batch_job_definition resources whose image is NOT the floating worker :latest.

    Read-only parse of the module. A jobdef on "${var.ecr_repository_url}:latest" moves with every
    worker push (so the shared promote runner is image-equivalent to it); anything else is pinned to a
    build somebody verified, and that pin is only honoured end-to-end if the promote leg rides it too."""
    import re

    text = _BATCH_TF.read_text(encoding="utf-8")
    parts = re.split(r'^resource\s+"aws_batch_job_definition"\s+', text, flags=re.M)[1:]
    pinned: set[str] = set()
    for part in parts:
        block = re.split(r"^(?:resource|module|data|locals)\s", part, flags=re.M)[0]
        m_name = re.search(
            r'^\s*name\s*=\s*"\$\{var\.project_name\}-\$\{var\.environment\}-([a-z0-9_-]+)"',
            block, re.M)
        m_img = re.search(r"^\s*image\s*=\s*(\S.*?)\s*$", block, re.M)
        if not m_name or not m_img:
            continue
        if m_img.group(1) == '"${var.ecr_repository_url}:latest"':
            continue
        pinned.add(f"leviathan-dev-{m_name.group(1)}")
    return pinned


# ---------------------------------------------------------------------------
# mpob -- CLOSED (DSG-TAIL A1, 2026-08-16, owner-ratified). This block stood as a
# deliberate KNOWN RED from the same-day suite sweep until the fold landed hours later.
#
# WHAT STOOD HERE: mpob published shadow_canonical on TWO digest-pinned jobdefs
# (mpob-silver + mpob-annual-silver) while promote fell through to the shared runner on
# a floating image -- the mixed-vintage shape that burned futures_eod on 2026-08-01.
# Self-promotion was blocked twice over: (1) ROLE -- both jobdefs bound batch_job_role,
# which has no kms:Sign; (2) ARITY -- promote_jobdef is a scalar and the lint fences it
# to THE one jobdef every shadow_canonical publisher runs on, and mpob had two.
#
# THE FIX TAKEN: the fold (this block's own option b, first branch). mpob-annual-silver
# was spec-identical to mpob-silver (image/exec/network/1 vCPU/2048; the SFN overrides
# the command per task), so the annual leg moved onto mpob-silver, the annual jobdef was
# destroyed (tf resource + output removed), and the scalar promote_jobdef became legal
# (own == {mpob-silver}). jobRoleArn moved to silver-publisher in the same change. The
# arity fence was NOT relaxed -- it stays load-bearing, byte-identical.
#
# DELIBERATE DEVIATIONS from the walkthrough that stood here, both probe-driven:
#   - The retry matrix STAYS on mpob-silver. The old step (a) said drop it "per the
#     publishing-job doctrine (a retried publisher re-runs its write path)" -- but the
#     live matrix retries ONLY on CannotPullContainer*/ResourceInitializationError*
#     (pre-start failures that never ran a write; every real failure exits), and the
#     T2-armed self-promote jobdefs (modis rev 12, fgis rev 9) keep the identical matrix.
#   - PENDING_HAND_MERGE stayed EMPTY: the committed tfvars generator
#     (gen_dag_schedules_tfvars.py) splices the mpob entry semantically in the same
#     sitting as the apply, so no hand-merge window ever opens.
#   - The image facts in the old text were stale by close: live was rev 8 @ 53db13d5 on
#     both jobdefs (tf state current), not rev 7 @ 753dbcd1.
#
# test_digest_pinned_producers_must_self_promote below is the fence that was red; the
# descriptor now satisfies it. Do not weaken it -- it is what catches the NEXT family
# that pins an image without carrying its promote.
# ---------------------------------------------------------------------------
def test_digest_pinned_producers_must_self_promote(gen, descriptors):
    """Any descriptor whose shadow_canonical publisher runs on a DIGEST-PINNED jobdef must declare that
    jobdef as its promote_jobdef. Otherwise the promote leg re-derives silver on the shared runner's
    floating :latest and the pin protects only the throwaway shadow, never the canonical write."""
    pinned = _digest_pinned_jobdef_names()
    # Guard the parse itself: a refactor that stops matching must go RED, not silently green.
    assert FUTURES_EOD_SILVER_JOBDEF in pinned, (
        f"parse of {_BATCH_TF.name} found pinned jobdefs {sorted(pinned)} -- expected "
        f"{FUTURES_EOD_SILVER_JOBDEF} (pinned to var.futures_eod_image_digest)"
    )
    for stem, d in descriptors.items():
        exposed = sorted(gen._shadow_canonical_jobdefs(d) & pinned)
        if not exposed:
            continue
        assert d.get("promote_jobdef") in exposed, (
            f"{stem}: silver publishes on digest-pinned {exposed} but promotes on "
            f"{d.get('promote_jobdef', 'the shared runner (floating :latest)')!r} -- the promote leg "
            f"would re-derive silver with a different build than the shadow it promotes"
        )


def test_every_autonomous_family_promote_carries_kms_pair(gen, descriptors):
    """Directly: for EVERY autonomous family, every promote task carries the KMS approval pair,
    with LEVIATHAN_APPROVAL_MODE == the descriptor's auth_mode (kms)."""
    autonomous = [s for s, d in descriptors.items() if d.get("promote_mode") == "autonomous"]
    assert autonomous, "expected at least one autonomous family"
    for stem in autonomous:
        d = descriptors[stem]
        for t in gen.render_input(d)["promote"]["tasks"]:
            names = {e["Name"]: e["Value"] for e in t["env"]}
            assert names.get("LEVIATHAN_APPROVAL_MODE") == d["auth_mode"] == "kms", stem
            assert names.get("LEVIATHAN_KMS_KEY_ID") == "alias/leviathan-dev-publish-signer", stem


def test_silver_phase_shadow_publishers_get_shadow_flag(gen, descriptors):
    """Each descriptor silver/gold shadow_canonical publisher's rendered silver-phase task ends
    --publish-mode shadow (map by position over the folded silver+gold source order)."""
    for stem, d in descriptors.items():
        rendered = gen.render_input(d)
        by_name = {}
        for p in d["phases"]:
            by_name.setdefault(p["name"], []).extend(p["tasks"])
        silver_src = list(by_name.get("silver", [])) + list(by_name.get("gold", []))
        for dt, rt in zip(silver_src, rendered["phases"]["silver"]["tasks"]):
            if dt.get("publish_mode") == "shadow_canonical" and dt.get("publishes"):
                assert rt["command"][-2:] == ["--publish-mode", "shadow"], f"{stem}/{dt['id']}"


# ---------------------------------------------------------------------------
# The fx (Wave-0) render reproduces the LIVE terraform reference entry.
# ---------------------------------------------------------------------------
# Ground truth: infra/terraform/envs/dev/main.tf module.eventbridge.schedules.fx_macro_daily
# .input_json.Input (it ran end-to-end today incl. the autonomous KMS promote).
LIVE_FX_INPUT = {
    "family": "fred",
    "asof": "<aws.scheduler.scheduled-time>",
    "auth_mode": "kms",
    "gate_tables": ["silver_fred_fx"],
    "gate_baseline_uri": "s3://leviathan-dev-shahem-001/cascade_census/rolling/fx_macro_daily/census.json",
    "phases": {
        "fetch": {"tasks": []},
        "bronze": {"tasks": []},
        "silver": {"tasks": [{
            "integration": "batch",
            "jobdef": "leviathan-dev-b3-flat-silver",
            "queue": "leviathan-dev-queue-ondemand",
            "command": ["-m", "jobs.batch.frankfurter_fx_task", "--publish-mode", "shadow"],
            "env": [],
        }]},
    },
    "gate": {
        "jobdef": "leviathan-dev-silver-gate",
        "queue": "leviathan-dev-queue-ondemand",
        "command": ["-m", "jobs.audit.silver_rebuild_gate", "--tables", "silver_fred_fx",
                    "--asof", "<aws.scheduler.scheduled-time>",
                    "--baseline-uri",
                    "s3://leviathan-dev-shahem-001/cascade_census/rolling/fx_macro_daily/census.json"],
    },
    "promote": {"mode": "autonomous", "tasks": [{
        "integration": "batch",
        "jobdef": "leviathan-dev-silver-publisher-runner",
        "queue": "leviathan-dev-queue-ondemand",
        "command": ["-m", "jobs.batch.frankfurter_fx_task", "--publish-mode", "canonical"],
        "env": [{"Name": "LEVIATHAN_APPROVAL_MODE", "Value": "kms"},
                {"Name": "LEVIATHAN_KMS_KEY_ID", "Value": "alias/leviathan-dev-publish-signer"}],
    }]},
}


def test_fx_render_matches_live_terraform_entry(gen, descriptors):
    assert gen.render_input(descriptors["fx_macro_daily"]) == LIVE_FX_INPUT


# ---------------------------------------------------------------------------
# --render-schedule: the full StartExecution body per family.
# ---------------------------------------------------------------------------
def test_render_schedule_body_shape(gen, descriptors):
    for stem, d in descriptors.items():
        body = gen.render_schedule(d)
        assert set(body) == {"StateMachineArn", "Name", "Input"}, f"{stem}: schedule body keys"
        assert body["StateMachineArn"] == "${state_machine_arn}", f"{stem}: tf ARN placeholder"
        assert body["Name"] == f"{d['family']}-sched-<aws.scheduler.execution-id>", f"{stem}: Name"
        # Input is the execution-input JSON as an ESCAPED STRING that round-trips to render_input.
        assert isinstance(body["Input"], str), f"{stem}: Input must be a string"
        assert json.loads(body["Input"]) == gen.render_input(d), f"{stem}: Input round-trip"


def test_render_schedule_tree_is_byte_identical(gen):
    """The checked-in {schedule}.schedule.json tree matches a fresh render + --render-schedule --check."""
    assert gen.generate(check=True, render_schedule=True) == 0
    schedules = gen.render_all_schedules(gen.load_descriptors())
    for stem, text in schedules.items():
        on_disk = _RENDERED / f"{stem}.schedule.json"
        assert on_disk.exists() and on_disk.read_text(encoding="utf-8") == text, f"{stem}: schedule drift"


# The unresolved-${...}-placeholder scan is a FATAL lint (exit 2 in render AND --check). It is
# asserted on a SYNTHETIC descriptor fixture, NOT live-tree contents, so it stays true regardless of
# which live descriptors currently carry a placeholder (modis_biweekly's ${RUN_ID} awaits its
# sibling-lane fix this round; conab/wasde were already cleaned).
#
# CONSEQUENCE (expected, transitional): while modis_biweekly still carries ${RUN_ID}, the live tree
# no longer renders clean, so the two tests asserting generate()==0 on the LIVE tree --
# test_check_mode_exit_zero and test_render_schedule_tree_is_byte_identical -- will FAIL until the
# modis lane lands, then self-heal. They assert the correct steady state; they are deliberately NOT
# weakened (the fatal lint is doing its job: blocking a render of an unsubstitutable placeholder).
def _synthetic_dirty():
    """A minimal {stem: descriptor} pair: one task carrying an unresolved ${...}, one clean."""
    return {
        "synth_dirty": {"phases": [
            {"name": "bronze", "tasks": [
                {"id": "has_ph", "command": ["jobs/batch/x.py", "--run-id", "${RUN_ID}"]},
            ]},
        ]},
        "synth_clean": {"phases": [
            {"name": "silver", "tasks": [
                {"id": "no_ph", "command": ["-m", "jobs.batch.y", "--mode", "all"]},
            ]},
        ]},
    }


def test_scan_unresolved_placeholders_mechanism_on_synthetic_fixture(gen):
    """The scan MECHANISM: flag exactly the tasks whose command carries an unresolved ${...} the
    scheduler cannot substitute, leaving clean tasks alone. Synthetic fixture -> independent of the
    live tree."""
    hits = gen.scan_unresolved_placeholders(_synthetic_dirty())
    flagged = {h.split("/", 1)[0] for h in hits}
    assert flagged == {"synth_dirty"}, flagged
    assert any("${RUN_ID}" in h for h in hits), hits
    # a template var mid-command is caught the same as a trailing one
    only_clean = {"c": {"phases": [{"name": "silver", "tasks": [
        {"id": "t", "command": ["-m", "jobs.batch.z", "--mode", "all"]}]}]}}
    assert gen.scan_unresolved_placeholders(only_clean) == []


def test_generate_is_fatal_exit2_on_unresolved_placeholder(gen, descriptors, monkeypatch):
    """The FATAL behavior: a descriptor with an unresolved ${...} makes generate() exit 2 in BOTH the
    render and --check paths (the scan is folded into the exit-2 lint gate, no longer a WARN).
    Asserted on a SYNTHETIC tree (a lint-clean real descriptor + one injected placeholder) via a
    monkeypatched load_descriptors, so exit 2 is attributable solely to the placeholder."""
    clean = copy.deepcopy(descriptors["fx_macro_daily"])
    # Baseline: the pristine descriptor is lint- AND placeholder-clean, so any exit 2 below is the
    # placeholder alone (not a residual lint defect).
    assert gen.lint_descriptor(clean, "fx_macro_daily") == []
    assert gen.scan_unresolved_placeholders({"fx_macro_daily": clean}) == []

    dirty = copy.deepcopy(clean)
    # Append a bare ${...} positional (does NOT start with '--', so it trips ONLY the placeholder
    # scan, not the dangling-option lint).
    dirty["phases"][0]["tasks"][0]["command"].append("${UNSUBSTITUTABLE}")
    assert gen.lint_descriptor(dirty, "fx_macro_daily") == [], "placeholder must not be a plain lint hit"
    assert gen.scan_unresolved_placeholders({"fx_macro_daily": dirty})  # non-empty

    monkeypatch.setattr(gen, "load_descriptors", lambda *a, **k: {"fx_macro_daily": dirty})
    assert gen.generate(check=False) == 2, "render path must exit 2 on the placeholder"
    assert gen.generate(check=True) == 2, "--check path must exit 2 on the placeholder"
    assert gen.generate(check=True, render_schedule=True) == 2, "schedule --check path must exit 2"


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


def test_lint_rejects_dangling_value_option(gen, descriptors):
    """A command ending on a value-expecting option (bare ``--series``, no value) is rejected
    fail-closed at render time -- the SFN container override is passed verbatim, so this makes the
    job's argparse exit 2 ('expected one argument'). This is the Wave-2 nass_crop_progress bronze
    defect that failed BatchSyncBronze across all 3 retries."""
    d = _one_descriptor(descriptors, "nass_crop_progress")
    bronze = next(p for p in d["phases"] if p["name"] == "bronze")
    bronze["tasks"][0]["command"] = ["jobs/batch/nass_task.py", "--series"]  # value truncated
    viol = gen.lint_descriptor(d, d["schedule"])
    assert any("value-expecting option" in v and "'--series'" in v for v in viol), viol


def test_lint_accepts_known_valueless_trailing_flags(gen, descriptors):
    """The dangling-arg guard must NOT false-positive on legitimately-clean commands: futures_prices
    ends on the store_true --force-overwrite (whitelisted valueless), and esr_weekly's value-REQUIRED
    --vintage-mode is followed by its value 'all' (NOT whitelisted -- it must supply the value, and
    does)."""
    for stem in ("esr_weekly", "futures_prices"):
        d = descriptors[stem]
        viol = gen.lint_descriptor(d, stem)
        assert not any("value-expecting option" in v for v in viol), f"{stem}: {viol}"


def test_lint_rejects_dangling_vintage_mode_now_that_it_is_not_whitelisted(gen, descriptors):
    """Regression for the FIFTH occurrence of this defect class: --vintage-mode is a value-REQUIRED
    option (choices latest|all), so it was REMOVED from the valueless whitelist. A truncated esr
    command ending on a bare --vintage-mode (the historical dangling-value bug) must now be REJECTED
    rather than silently accepted."""
    assert "--vintage-mode" not in gen._VALUELESS_TRAILING_FLAGS
    d = _one_descriptor(descriptors, "esr_weekly")
    silver = next(p for p in d["phases"] if p["name"] == "silver")
    silver["tasks"][0]["command"] = ["jobs/batch/bronze_to_silver_esr_task.py", "--vintage-mode"]
    viol = gen.lint_descriptor(d, d["schedule"])
    assert any("value-expecting option" in v and "'--vintage-mode'" in v for v in viol), viol


def test_lint_rejects_mid_command_dangling_option(gen, descriptors):
    """The dangling-arg rule generalizes from the command TAIL to mid-command: a value-expecting
    option immediately followed by ANOTHER --opt (its value silently dropped) is rejected the same as
    a trailing dangle. (E.g. ``--series --publish-mode shadow`` -- argparse would consume
    ``--publish-mode`` as --series' value or exit 2.)"""
    d = _one_descriptor(descriptors, "nass_crop_progress")
    bronze = next(p for p in d["phases"] if p["name"] == "bronze")
    bronze["tasks"][0]["command"] = [
        "jobs/batch/nass_task.py", "--series", "--publish-mode", "shadow",
    ]
    viol = gen.lint_descriptor(d, d["schedule"])
    assert any("immediately followed by another option" in v and "'--series'" in v for v in viol), viol


def test_lint_accepts_store_true_flag_immediately_before_next_option(gen, descriptors):
    """The mid-command generalization must NOT false-positive on a genuine store_true flag sitting
    directly before the next --opt: --force-overwrite (whitelisted) before --publish-mode is clean."""
    d = _one_descriptor(descriptors, "fx_macro_daily")
    t = d["phases"][0]["tasks"][0]
    t["command"] = [
        "-m", "jobs.batch.frankfurter_fx_task", "--force-overwrite", "--publish-mode", "shadow",
    ]
    viol = gen.lint_descriptor(d, d["schedule"])
    assert not any("value-expecting option" in v for v in viol), viol


def test_discover_is_a_whitelisted_valueless_flag(gen, descriptors):
    """The unica biweekly fetch chains store_true flags: ``--discover --current-season --asof ...``.
    ``--discover`` (store_true, no value) sits directly before another --opt, so it MUST be in the
    valueless whitelist or the dangling-arg lint would false-positive on it. Guard both the whitelist
    membership and that a --discover immediately before the next option lints clean."""
    assert "--discover" in gen._VALUELESS_TRAILING_FLAGS
    d = _one_descriptor(descriptors, "fx_macro_daily")
    t = d["phases"][0]["tasks"][0]
    t["command"] = ["jobs/ingest/fetch_unica_biweekly.py", "--discover", "--current-season", "--asof",
                    "<aws.scheduler.scheduled-time>"]
    t["invocation_form"] = "s"
    viol = gen.lint_descriptor(d, d["schedule"])
    assert not any("value-expecting option" in v for v in viol), viol


def test_nass_crop_progress_bronze_renders_series_all(gen, descriptors):
    """Fixed path: the nass_crop_progress bronze task must render the COMPLETE
    ``nass_task.py --series all --force-overwrite`` command. ``all`` (not ``crop_progress``) because
    the one run must write BOTH bronze series -- the chain fans out to nass_crop_progress_silver
    (reads series=crop_progress) AND nass_annual_silver (reads series=annual), and both gate_tables
    gate. ``--force-overwrite`` (A-W4 crop_progress retrofit, 2026-07-23): nass_task.py skips an
    existing bronze partition unless forced, and bronze_nass_key is YEAR-granular, so without it the
    current-CY partition created mid-year is never refreshed by the weekly run (the ~1 GB QuickStats
    file is parsed unconditionally, so force adds only cheap re-PUTs of the already-parsed shards)."""
    rendered = gen.render_input(descriptors["nass_crop_progress"])
    bronze_tasks = rendered["phases"]["bronze"]["tasks"]
    assert len(bronze_tasks) == 1, "nass_crop_progress must have exactly one bronze task"
    assert bronze_tasks[0]["command"] == [
        "jobs/batch/nass_task.py", "--series", "all", "--force-overwrite"]
    # gate covers both series' silver tables (why bronze must be --series all, not crop_progress)
    assert set(rendered["gate_tables"]) == {"silver_nass_annual", "silver_nass_crop_progress"}


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
    # D-PQ publish-chain repair (2026-08-08): psd_monthly LANDED its A-W4 retrofit -- the
    # scheduled silver leg fired into dry-run (`--publish-mode` defaulted, writing NOTHING on
    # every day-8-13 window) while the citable flagship's canonical sat frozen at a single
    # 2026-07-18 manual session. Landing it is the 4-part M2 package (retrofit_landed, wave,
    # promote_mode+auth_mode, this literal); the stem leaves BOTH sets together or the
    # equality below is what catches a half-landed retrofit.
    # nass_crop_progress LANDED the same day (both silver legs armed with the value-typed
    # --force-overwrite true; annual's latest_only dry-run had produced ZERO shadow objects
    # ever). Same 4-part package, same rule.
    # D-SG T2 (2026-08-16, owner-ratified): modis_biweekly, fgis and food_cpi LANDED their
    # A-W4 retrofits and armed promote -- the same 4-part package (retrofit_landed, wave,
    # promote_mode+auth_mode, this literal); modis+fgis self-promote (digest-pinned jobdefs,
    # jobRoleArn moved to silver-publisher in the same change -- without it the unattended
    # canonical promote AccessDenies at kms:Sign); food_cpi promotes on the shared runner
    # (its producer is the CLI-managed b3-flat-silver, not a terraform pin). Each carries its
    # parser's force-overwrite spelling so promotes refresh existing partitions.
    # DSG-TAIL A2 (2026-08-16, owner-ratified): unica LANDED too, by the SAME FOLD as
    # mpob's: unica-annual-state IS a terraform digest pin (main.tf:3166) -- an earlier
    # "CLI-managed" recon claim was a truncated-grep false negative that
    # test_digest_pinned_producers_must_self_promote caught the moment mpob's
    # alphabetically-earlier red stopped masking its loop. The biweekly leg moved onto
    # unica-annual-state (SFN overrides commands per task), own-set collapsed to one,
    # scalar promote_jobdef became legal, jobRoleArn moved to silver-publisher in the
    # same change. Biweekly flipped to shadow_canonical (explicit shadow flag removed,
    # bare --force-overwrite added); the annual promote renders bare and skip-existings
    # into a clean no-op (probe P4, unica_annual_state_task.py:198-205). Remaining:
    # cot + futures_prices, the two hand-armed interim shapes. The stem leaves BOTH
    # sets together or the equality below is what catches a half-landed retrofit.
    assert wave2 == retrofit == {
        "cot", "futures_prices",
    }


def test_wave0_is_the_single_platform_proof(descriptors):
    wave0 = {s for s, d in descriptors.items() if d["wave"] == 0}
    assert wave0 == {"fx_macro_daily"}
