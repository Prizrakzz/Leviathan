"""The registry-vs-schedule lint (census P8 + refuter M4), pinned in both directions.

WHAT IT IS FOR, stated as the failure it prevents. On 2026-09-22 the estate could serve a numbers
card with no producer on any clock and nothing said so. ``gold_board_crush`` and
``gold_futures_spreads`` were both SERVED cards bound to board legs, produced ONCE BY HAND on
2026-08-2x, 33 and 32 days stale against daily inputs, with no descriptor, no job definition, no
schedule and no alarm. ``silver_psd_attributes`` had a producer phase that reached a descriptor and
never reached an apply. And three descriptors' ``chain_shape`` strings named a ``bronze`` phase
their own ``phases`` list lacks -- the string a reader trusts when deciding a leg exists, which is
exactly how ``sagis_weekly`` spent 879 days write-green and data-dead behind a bronze prefix no
phase writes.

The HEAD pin below rebuilds the pre-fix armed set and asserts the lint names all seven tables, so
this file fails on HEAD and passes after. The live-tree tests assert the state now.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "silver"))

import gen_dag_schedules_tfvars as T  # noqa: E402  (path-injected sibling; no package)
import gen_sfn_inputs as G  # noqa: E402

# The chain_shape divergences this lint found that belong to OTHER files, each an open docket of
# the same 2026-09-22 wave. The assertion is a SUBSET, so it keeps passing as they are fixed and
# fails the moment a NEW descriptor starts describing a leg it does not have.
#   icco_cocoa, mpoc -- refuter M4, owned by the mpoc/icco lane.
#   ams_cotton_quality -- found BY THIS LINT, not by the census: census P18(a) records the same
#     defect from the other end ("the silver task reads a bronze corpus that an untracked step
#     built once"), so the string and the missing producer are one docket.
KNOWN_CHAIN_SHAPE_DOCKETS = {"icco_cocoa", "mpoc", "ams_cotton_quality"}


@pytest.fixture(scope="module")
def descriptors() -> dict:
    return G.load_descriptors()


@pytest.fixture(scope="module")
def armed() -> dict:
    return json.loads(T.TFVARS.read_text(encoding="utf-8"))["dag_schedules"]


# --------------------------------------------------------------------- the served-table rule
def test_every_served_card_has_a_producer_on_a_clock(armed):
    """The live tree: no served card without an armed schedule or an explicit waiver."""
    violations = T.lint_served_tables_have_a_producer(armed)
    assert violations == [], "\n  - " + "\n  - ".join(violations)


def test_the_rule_fails_on_the_pre_fix_armed_set(armed, monkeypatch):
    """THE HEAD PIN. Rebuild the estate as it stood before this wave -- the two gold schedules
    absent, psd_monthly's gate covering silver_psd alone, and no waiver map at all -- and assert
    the lint names every one of the seven cards that had no producer on a clock."""
    head = {k: v for k, v in armed.items()
            if k not in ("gold_board_crush", "gold_futures_spreads")}
    body = json.loads(head["psd_monthly"]["input_json"])
    payload = json.loads(body["Input"])
    payload["gate_tables"] = ["silver_psd"]
    body["Input"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    head["psd_monthly"] = dict(head["psd_monthly"], input_json=json.dumps(body, sort_keys=True))
    monkeypatch.setattr(T, "NOT_ARMED_TABLES", {})

    named = {v.split(":")[0] for v in T.lint_served_tables_have_a_producer(head)
             if "SERVED" in v}
    assert named == {
        "gold_board_crush", "gold_futures_spreads", "silver_psd_attributes",
        "silver_minagro_grain_exports", "silver_production", "silver_production_livestock",
        "gold_pattern_records",
    }


def test_a_dead_waiver_is_a_violation(armed):
    """NOT_ARMED_TABLES is checked both ways: a waiver for a table that IS armed is dead config."""
    armed_tables = T.armed_gate_tables(armed)
    victim = sorted(armed_tables)[0]
    try:
        T.NOT_ARMED_TABLES[victim] = "synthetic"
        violations = T.lint_served_tables_have_a_producer(armed)
    finally:
        T.NOT_ARMED_TABLES.pop(victim)
    assert any(victim in v and "dead config" in v for v in violations)


def test_the_armed_input_is_read_not_the_descriptor(armed):
    """psd_monthly is why: a producer phase in a descriptor that never reached an apply is not on
    a clock, so the rule reads the ARMED input_json."""
    tables = T.armed_gate_tables(armed)
    assert "silver_psd_attributes" in tables
    assert tables["silver_psd_attributes"] == ["psd_monthly"]


def test_a_PARKED_entry_arms_nothing(armed):
    """ROUND-3 REVIEW MAJOR-2. Until 2026-09-22 this function read every entry in the file and
    never looked at `enabled`, so a family an operator had parked still satisfied the rule -- the
    fence certifying the exact state it was written from (a served card with nothing firing).
    `enabled: false` is not a nuance: envs/dev/main.tf passes the field through to
    modules/eventbridge/main.tf, which sets `state = each.value.enabled ? "ENABLED" :
    var.schedule_state` over a variable whose default is "DISABLED". The schedule exists in the
    account and never fires. MEASURED on this fixture before the fix: `armed_gate_tables` still
    named the table and the lint was GREEN."""
    parked = {k: dict(v) for k, v in armed.items()}
    parked["psd_monthly"]["enabled"] = False

    lost = set(T.armed_gate_tables(armed)) - set(T.armed_gate_tables(parked))
    assert lost == set(json.loads(json.loads(
        armed["psd_monthly"]["input_json"])["Input"])["gate_tables"])
    named = {v.split(":")[0] for v in T.lint_served_tables_have_a_producer(parked)
             if "SERVED" in v}
    assert lost <= named, "a parked producer's cards must reach the served-card rule as unarmed"


@pytest.mark.parametrize("value", [False, None, 0, "true", "<absent>"])
def test_an_enabled_value_that_is_not_the_boolean_true_is_UNARMED(armed, value):
    """FAIL CLOSED on the field that decides whether a clock exists. envs/dev/variables.tf types
    `enabled` as a bare `bool`, so the JSON boolean true is the only armed state this rule
    recognises; a string, a zero, a null or an absent key is an entry whose armed state cannot be
    read, and a fence that cannot read it must not certify it. All 27 live entries carry a real
    `true` (measured 2026-09-22), so this costs the clean tree nothing."""
    fixture = {k: dict(v) for k, v in armed.items()}
    if value == "<absent>":
        fixture["psd_monthly"].pop("enabled")
    else:
        fixture["psd_monthly"]["enabled"] = value
    assert "psd_monthly" not in [s for stems in T.armed_gate_tables(fixture).values()
                                 for s in stems]


def test_a_malformed_entry_is_skipped_and_never_raises(armed):
    """The enabled read may not turn a junk entry into a crash: the rule's job is to report, and a
    tfvars nobody can parse is the caller's RED to name, not an AttributeError here."""
    for junk in ("a string, not an object", None, 7, []):
        fixture = dict(armed)
        fixture["junk_family"] = junk
        assert T.armed_gate_tables(fixture) == T.armed_gate_tables(armed)


# ------------------------------------------------------------------------ the chain_shape rule
def test_live_chain_shape_divergences_are_only_the_known_dockets(descriptors):
    named = {v.split(":")[0] for v in T.lint_chain_shape_matches_phases(descriptors)}
    assert named <= KNOWN_CHAIN_SHAPE_DOCKETS, f"a NEW chain_shape divergence: {named}"


def test_sagis_weekly_no_longer_claims_a_bronze_phase(descriptors):
    """The B9 fix, at the descriptor: the string claimed 'fetch->bronze(shared parser)->silver x3'
    over phases [fetch, silver], and the producer read that non-existent bronze for 879 days."""
    desc = descriptors["sagis_weekly"]
    assert {p["name"] for p in desc["phases"]} == {"fetch", "silver"}
    assert not T.lint_chain_shape_matches_phases({"sagis_weekly": desc})


def test_the_chain_shape_rule_fires_on_a_claimed_phase():
    """Non-vacuity."""
    bad = {"x": {"chain_shape": "fetch->bronze->silver",
                 "phases": [{"name": "fetch"}, {"name": "silver"}]}}
    violations = T.lint_chain_shape_matches_phases(bad)
    assert len(violations) == 1 and "'bronze'" in violations[0]


@pytest.mark.parametrize("shape", [
    "MANUAL upload (no unattended fetch) -> bronze[g] -> silver_production[g]",
    "fetch x2 -> silver x3 (raw-direct; this chain has NO bronze phase)",
])
def test_a_phase_NAMED_IN_ORDER_TO_DENY_IT_is_not_a_claim(shape):
    """The two live strings that a substring rule would have flagged: both name a phase precisely
    to say the chain does NOT have it. A lint that punishes the clearest descriptors teaches
    everyone to write vaguer ones."""
    desc = {"chain_shape": shape,
            "phases": [{"name": "fetch"}, {"name": "bronze"}, {"name": "silver"}]}
    assert T.lint_chain_shape_matches_phases({"x": desc}) == []


# ------------------------------------------------------------------------------ the ARM list
def test_arm_and_not_armed_are_disjoint_and_both_name_real_descriptors(descriptors):
    assert not (set(T.ARM) & set(T.NOT_ARMED))
    for stem in list(T.ARM) + list(T.NOT_ARMED):
        assert stem in descriptors, f"{stem} is on a hold list with no descriptor (stale)"


def test_the_two_gold_schedules_are_armed_from_their_descriptors(armed, descriptors):
    """Arming is now the GENERATOR's write, authorised by ARM -- never a hand-seeded tfvars entry,
    which is what put a guaranteed-red production_faostat schedule live."""
    for stem in ("gold_board_crush", "gold_futures_spreads"):
        assert stem in T.ARM and stem in armed
        assert armed[stem]["enabled"] is True
        assert armed[stem]["cron"] == descriptors[stem]["cron"] == "cron(0 10 ? * TUE-SAT *)"
        payload = json.loads(json.loads(armed[stem]["input_json"])["Input"])
        assert payload["gate_tables"] == [stem]
        # a derived gold table writes DIRECTLY: no shadow, so the promote Map must be empty
        assert payload["promote"]["tasks"] == []
        assert [t["command"] for t in payload["phases"]["silver"]["tasks"]] == \
            [[f"jobs/batch/{stem}_task.py"]]


def test_an_unvouched_descriptor_is_still_refused(monkeypatch, descriptors):
    """The fail-closed rule ARM relaxes must still hold for anything ARM does not name."""
    monkeypatch.setitem(T.ARM, "sentinel", "synthetic")
    _obj, _changes, violations = T.assemble()
    assert any("sentinel" in v and "stale list" in v for v in violations)
