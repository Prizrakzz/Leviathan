"""THE REGISTRY-VS-SCHEDULE LINT, WIRED INTO config_check -- the pins (census P8 + refuter M4).

WHAT ROUND 1 LEFT, AND WHY IT WAS NOT YET A FENCE. The rule was built as
``scripts/silver/gen_dag_schedules_tfvars.py --lint`` and its only caller was that flag: a script
somebody has to remember to run. The lane's own reviewer said so in one line -- "the lint is built,
red, and not wired, so it is not yet a pin" -- and the defects it had just found were not small:
``gold_board_crush`` and ``gold_futures_spreads`` were SERVED numbers cards bound to board legs,
produced ONCE BY HAND on 2026-08-2x, 33 and 32 days stale against daily inputs, with no descriptor,
no job definition, no schedule and no alarm; ``silver_psd_attributes`` was a producer phase that
reached a descriptor on 2026-08-26 and never reached an apply; and three ``chain_shape`` strings
named a ``bronze`` phase their own ``phases`` list lacks -- the exact prose that let
``sagis_weekly`` spend 879 days write-green and data-dead behind a bronze prefix no phase writes.

WHO RUNS IT, PINNED HERE AND NOT ONLY CLAIMED IN A DOCSTRING (L1 review MAJOR-2, where a report
claimed a lint had moved "to CI" and the gate would print its PASS line, and BOTH were false):
``config_check.main()`` is a manual CLI plus this deck. ``test_the_gate_keeps_its_own_ten`` and
``test_there_is_still_no_python_ci`` are the two assertions that go red the day either claim stops
being true, so the sentence in the clause's docstring cannot quietly rot.

WHAT FAILS ON HEAD, COUNTED HONESTLY (round-2 review MINOR-1, which caught this file's own
docstring over-claiming). 19 of the 21 tests collected here fail on HEAD, where
``config_check.check_dag_registry_schedule`` does not exist and ``gen_dag_schedules_tfvars.py``
defines no ``armed_gate_tables`` and no lint function at all (HEAD's copy is 321 lines, verified
by ``git show HEAD:`` on 2026-09-22 -- ``git stash`` was never used). The other TWO
-- ``test_the_gate_keeps_its_own_ten_and_this_clause_is_not_among_them`` and
``test_there_is_still_no_python_ci`` -- PASS on HEAD by design, and that is the point of them: they
pin a STANDING property of the repo that the clause's docstring asserts, so the day either stops
being true the docstring is corrected with them rather than quietly rotting.

AND WHAT IS RED BETWEEN THE COMMITS OF THIS PUSH (round-3 review MAJOR-1). The regenerated
``dag_schedules.auto.tfvars.json`` rides the LAST atom of this push, so at the tip of every earlier
commit EXACTLY TWO of the 21 fail, by construction and not by anybody's mistake:
``test_the_live_tree_passes`` (HEAD's tfvars against this tree's descriptors and registry is THREE
violations -- gold_board_crush, gold_futures_spreads, silver_psd_attributes -- and the folded
tfvars is ZERO; measured 2026-09-22) and
``test_a_served_card_with_no_producer_on_a_clock_is_a_config_check_FAIL`` (at those tips the two
gold entries it drops are absent already, so the clause names three cards where it asserts two).
Both go green at the final tip, neither is to be "fixed" in between, and the push is not to be
split to hide it. Every other test here is written to hold at BOTH tips -- including
``test_the_clause_names_exactly_the_three_cards_the_unfolded_tfvars_leaves_unarmed``, which
replays that pre-fold armed set from whatever is on disk, and
``test_a_parked_schedule_is_not_a_clock_and_the_clause_names_it``, which reads the parked entry's
own gate_tables instead of naming them.

AWS-free: descriptor JSON, the numbers registry YAML and the generated tfvars, all read from disk.
"""
from __future__ import annotations

import builtins
import inspect
import json
import sys
from pathlib import Path

import pytest
from leviathan.graphrag import config_check as cc

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "silver"))

import gen_dag_schedules_tfvars as T  # noqa: E402  (path-injected sibling; no package)
import gen_sfn_inputs as G  # noqa: E402

# A descriptor that describes a leg it does not have. THE FIXTURE THE BRIEF ASKS FOR: the clause
# must pass on the tree and fail on this.
BAD_DESCRIPTOR = {
    "fixture_family": {
        "chain_shape": "fetch->bronze->silver",
        "phases": [{"name": "fetch"}, {"name": "silver"}],
    }
}


def _served_cards_named(errs: list[str]) -> set[str]:
    """The TABLES a run of the clause names on its served-card half.

    The clause reports one trailing line carrying the remedy and the sequence property, which is
    not a card; filtering on the rule's own word keeps these assertions about cards."""
    return {e.split(": ", 1)[1].split(":")[0] for e in errs if "SERVED" in e}


@pytest.fixture(scope="module")
def armed() -> dict:
    return json.loads(T.TFVARS.read_text(encoding="utf-8"))["dag_schedules"]


@pytest.fixture(scope="module")
def descriptors() -> dict:
    return G.load_descriptors()


# ------------------------------------------------------------------- the state this change leaves
def test_the_live_tree_passes():
    """41 served cards against 27 armed entries, 28 descriptors (every one of them carrying a
    chain_shape), no violation. Measured 2026-09-22 after the orchestrator corrected
    ams_cotton_quality's chain_shape by hand -- the one descriptor the rule found that no lane
    owned."""
    errs = cc.check_dag_registry_schedule()
    assert errs == [], "\n  - " + "\n  - ".join(errs)


def test_the_clause_is_wired_into_config_check_main():
    """A lint whose only caller is its own deck is the state this change exists to end. Assert the
    roster entry exists and is at the TAIL -- the append-never-insert law this file keeps for its
    own roster (the same assertion sampler_totality carries)."""
    src = inspect.getsource(cc.main)
    assert '("dag_registry_schedule", check_dag_registry_schedule())' in src
    assert src.index('("dag_registry_schedule"') > src.index('("sampler_totality"'), "append at the tail"


def test_the_roster_is_forty_two_lints():
    """The count the wave reports. 40 at HEAD, 41 with lane 1's sampler_totality, 42 with this.
    MOVED 2026-09-24 (fix round 2, lane T): 43 -- `numbers_card_fields` APPENDED at the tail (the law this
    roster keeps); `dag_registry_schedule` is now the second-to-last clause, in its own place."""
    import re
    labels = re.findall(r'\("([a-z0-9_]+)", (?:check_|lint_)', inspect.getsource(cc.main))
    # The message matters more than the count (round-2 review MINOR-5): the 44th clause anyone adds
    # ANYWHERE in the estate reds a deck named for this lane, and a bare assert would tell its
    # author nothing about why a file they never opened is failing.
    assert labels[-2] == "dag_registry_schedule"
    assert len(labels) == 43 and labels[-1] == "numbers_card_fields", (
        f"the config_check roster is now {len(labels)} clauses ending {labels[-1]!r}. If you "
        f"APPENDED a clause at the tail, that is the law this roster keeps (append-never-insert) "
        f"and this count is the thing to update -- here and in check_dag_registry_schedule's "
        f"docstring. If your clause was INSERTED above dag_registry_schedule, move it to the tail."
    )


# ------------------------------------------------------------------------------- THE FIXTURE PIN
def test_a_chain_shape_that_names_a_phase_it_lacks_is_a_config_check_FAIL(armed):
    """THE PIN. One fixture descriptor, one violation, the DESCRIPTOR NAMED in the failure string
    (config_check's own convention: the label leads, the offender follows, so a reader of `FAIL
    dag_registry_schedule:` knows which file to open)."""
    errs = cc.check_dag_registry_schedule(descriptors=BAD_DESCRIPTOR, tfvars=armed)
    assert len(errs) == 1, errs
    assert errs[0].startswith("dag_registry_schedule: fixture_family:")
    assert "'bronze'" in errs[0] and "['fetch', 'silver']" in errs[0]


def test_the_violation_travels_through_main_as_a_FAIL(monkeypatch, capsys):
    """Not just the function -- the ROSTER. With the fixture in place `main()` must print
    `FAIL dag_registry_schedule` and return 1; a clause that binds only when called by hand is the
    thing round 1 already had."""
    monkeypatch.setattr(cc, "check_dag_registry_schedule",
                        lambda: ["dag_registry_schedule: fixture_family: synthetic"])
    rc = cc.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL dag_registry_schedule:" in out and "fixture_family" in out


def test_a_phase_NAMED_IN_ORDER_TO_DENY_IT_is_not_a_violation(armed):
    """The rule's own restraint, re-pinned at the clause: two live descriptors name a phase
    precisely to say the chain does NOT have it, and a lint that punishes the clearest descriptors
    teaches everyone to write vaguer ones."""
    deny = {"x": {"chain_shape": "fetch x2 -> silver x3 (raw-direct; this chain has NO bronze phase)",
                  "phases": [{"name": "fetch"}, {"name": "silver"}]}}
    assert cc.check_dag_registry_schedule(descriptors=deny, tfvars=armed) == []


def test_a_served_card_with_no_producer_on_a_clock_is_a_config_check_FAIL(descriptors, armed):
    """The other half, bound through the clause: drop the two gold schedules this wave armed and
    the clause must name both cards. This is the pre-wave estate, replayed."""
    pre_wave = {k: v for k, v in armed.items()
                if k not in ("gold_board_crush", "gold_futures_spreads")}
    errs = cc.check_dag_registry_schedule(descriptors=descriptors, tfvars=pre_wave)
    assert _served_cards_named(errs) == {"gold_board_crush", "gold_futures_spreads"}
    assert all(e.startswith("dag_registry_schedule: ") for e in errs)


def test_the_clause_names_exactly_the_three_cards_the_unfolded_tfvars_leaves_unarmed(descriptors,
                                                                                     armed):
    """THE SEQUENCE PIN (round-3 review MAJOR-1). The regenerated tfvars rides the LAST atom of
    this push, so between the commit that lands this clause and that fold, a checkout reds here --
    and the number is not a guess. This replays HEAD's armed set from the live one: HEAD has the
    same 25 entries less the two gold families this wave arms, and the ONLY other difference in
    any entry's gate_tables is psd_monthly's (HEAD ['silver_psd'], live ['silver_psd',
    'silver_psd_attributes']) -- both verified against `git show HEAD:` on 2026-09-22. Three
    violations, and zero once the fold lands."""
    head = {k: dict(v) for k, v in armed.items()
            if k not in ("gold_board_crush", "gold_futures_spreads")}
    body = json.loads(head["psd_monthly"]["input_json"])
    payload = json.loads(body["Input"])
    payload["gate_tables"] = ["silver_psd"]
    body["Input"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    head["psd_monthly"]["input_json"] = json.dumps(body, sort_keys=True)

    errs = cc.check_dag_registry_schedule(descriptors=descriptors, tfvars=head)
    assert _served_cards_named(errs) == {
        "gold_board_crush", "gold_futures_spreads", "silver_psd_attributes"}
    # and the reader meeting that red is told the remedy in the same output, not in a docstring
    remedy = [e for e in errs if "regenerate the tfvars" in e]
    assert len(remedy) == 1, errs
    assert "GENERATED artifact" in remedy[0] and "property of the SEQUENCE" in remedy[0]
    assert "gold_board_crush" in remedy[0] and "silver_psd_attributes" in remedy[0]


def test_a_parked_schedule_is_not_a_clock_and_the_clause_names_it(descriptors, armed):
    """THE ROUND-3 MAJOR-2 PIN. `enabled` is operator-owned -- the generator writes it once on the
    ARM create path and never again -- and terraform renders `enabled: false` as an EventBridge
    schedule in state DISABLED (modules/eventbridge/main.tf: state = each.value.enabled ?
    "ENABLED" : var.schedule_state, whose default is "DISABLED"). Until this round the rule read
    every entry in the file and never looked at that field, so parking a family left the fence
    GREEN on the very state it was written from: a served card with nothing firing. MEASURED on
    this fixture before the fix: 0 violations. After: both of psd_monthly's cards are named, and
    the message names the SCHEDULE and the value of its boolean -- "no entry names it" would be a
    false sentence in front of an entry that does."""
    fixture = {k: dict(v) for k, v in armed.items()}
    fixture["psd_monthly"]["enabled"] = False

    errs = cc.check_dag_registry_schedule(descriptors=descriptors, tfvars=fixture)
    named = _served_cards_named(errs)
    # EVERY card that entry was the only clock for is now named, whichever tip this runs at: on
    # the folded tfvars psd_monthly's gate_tables are ['silver_psd', 'silver_psd_attributes'] and
    # before the fold ['silver_psd'], so the set is read from the entry rather than written here.
    lost = set(T.armed_gate_tables(armed)) - set(T.armed_gate_tables(fixture))
    assert lost == set(json.loads(json.loads(
        armed["psd_monthly"]["input_json"])["Input"])["gate_tables"])
    assert lost <= named
    line = next(e for e in errs if e.split(": ", 1)[1].startswith("silver_psd:"))
    assert "PARKED: psd_monthly (enabled: False)" in line
    assert "An entry is not a clock." in line
    assert "regenerating the tfvars does NOT undo this" in line
    # the generator's own sentence for a genuinely absent entry must NOT be used here
    assert "no entry in dag_schedules.auto.tfvars.json names it" not in line


@pytest.mark.parametrize("value", [False, None, "true", "<absent>"])
def test_an_enabled_field_the_rule_cannot_read_is_UNARMED(armed, descriptors, value):
    """FAIL CLOSED on the field that turns the clock off. terraform types `enabled` as a bare
    `bool` (envs/dev/variables.tf), so only the JSON boolean true is the armed state this rule
    recognises; a string, a null or an absent key is an entry whose armed state cannot be read,
    and a fence that cannot read it must not certify it."""
    fixture = {k: dict(v) for k, v in armed.items()}
    if value == "<absent>":
        fixture["psd_monthly"].pop("enabled")
    else:
        fixture["psd_monthly"]["enabled"] = value
    assert "silver_psd" not in T.armed_gate_tables(fixture)
    assert "silver_psd" in _served_cards_named(
        cc.check_dag_registry_schedule(descriptors=descriptors, tfvars=fixture))


def test_an_empty_descriptor_roster_is_a_RED_and_not_a_clean_chain(armed):
    """THE FOURTH DOOR (round-2 review MINOR-2). `gen_sfn_inputs.load_descriptors` globs
    configs/silver/dags NON-RECURSIVELY and returns {} -- raising nothing -- when the directory is
    absent or empty, and a chain_shape rule over {} is vacuously clean. That green means "nothing
    was read", which is the 2026-08-18 inferred-floor class exactly. Live roster: 28."""
    errs = cc.check_dag_registry_schedule(descriptors={}, tfvars=armed)
    assert len(errs) == 1 and "roster is EMPTY" in errs[0]
    assert "an unread input is a RED" in errs[0]


# ----------------------------------------------------------------------------- fail-closed, twice
def test_the_clause_fails_closed_when_the_rule_module_cannot_be_imported(monkeypatch):
    """The rule's own code is this clause's input. An input it could not read is a RED, never a
    pass on an empty set -- the 2026-08-18 inferred-floor class."""
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "gen_dag_schedules_tfvars":
            raise ImportError("simulated: scripts/ not on sys.path")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    monkeypatch.delitem(sys.modules, "gen_dag_schedules_tfvars", raising=False)
    errs = cc.check_dag_registry_schedule()
    assert len(errs) == 1 and "cannot import the generator" in errs[0]


def test_a_missing_tfvars_names_the_missing_FILE_and_not_thirty_seven_innocent_cards(monkeypatch, tmp_path):
    """MEASURED, and it is why this branch exists: neither image carries `infra/`
    (docker/leviathan_worker/Dockerfile copies src/ jobs/ configs/ sql/ and not even scripts/;
    the embedder adds scripts/ and still not infra/). With the armed set absent, the served-card
    rule reports every unwaived card as unproduced -- `lint_served_tables_have_a_producer({})`
    returns 37 violations, measured -- blaming the cards for a file the layout never carried. One
    line, naming the file, and still not a pass."""
    assert len(T.lint_served_tables_have_a_producer({})) == 37, \
        "the report this branch exists to avoid: every unwaived served card blamed for one file"
    monkeypatch.setattr(T, "TFVARS", tmp_path / "absent.auto.tfvars.json")
    errs = cc.check_dag_registry_schedule()
    assert len(errs) == 1
    assert "absent.auto.tfvars.json is not in this layout" in errs[0]
    # the per-card violation's own sentence, which must NOT appear: no card is blamed here
    assert "no armed schedule produces it" not in errs[0]


def test_an_unparseable_tfvars_is_a_red_not_an_empty_armed_set(monkeypatch, tmp_path):
    broken = tmp_path / "broken.auto.tfvars.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(T, "TFVARS", broken)
    errs = cc.check_dag_registry_schedule()
    assert len(errs) == 1 and "present but unreadable" in errs[0]


def test_the_clause_says_so_when_the_generator_half_is_missing(monkeypatch):
    """The two-atom hazard, made loud. The clause and the generator's --lint mode are ONE change
    landing in TWO commits (config_check.py rides lane 1's atom, the generator rides lane 3's), so
    a checkout between them must say which half is absent rather than raise AttributeError."""
    monkeypatch.delattr(T, "lint_chain_shape_matches_phases")
    errs = cc.check_dag_registry_schedule()
    assert len(errs) == 1 and "does not define" in errs[0]
    assert "lint_chain_shape_matches_phases" in errs[0]


# --------------------------------------------------- the two claims the docstring makes about RUNNERS
def test_the_gate_keeps_its_own_ten_and_this_clause_is_not_among_them():
    """L1 review MAJOR-2, pinned. `silver_rebuild_gate._run_config_check` carries a HARDCODED list
    of ten lints and never calls `config_check.main()`, so nothing this file adds can red the
    12:00Z promote-blocking gate. That is deliberate: `_config_implicated` cannot attribute a lint
    string to a table, so a violation there would red the ESTATE over one descriptor's prose. The
    day someone changes that, this test goes red and the clause's docstring must be corrected with
    it."""
    sys.path.insert(0, str(_REPO))
    from jobs.audit import silver_rebuild_gate as gate
    src = inspect.getsource(gate._run_config_check)
    assert src.count('("') == 10, "the gate's hardcoded lint list is no longer ten"
    assert "dag_registry_schedule" not in src
    assert "config_check.main" not in src and "cfg.main" not in src


def test_there_is_still_no_python_ci():
    """The other half of the honest claim. One workflow, filtered to apps/terminal/**, so no python
    path can trigger it: `python -m leviathan.graphrag.config_check` runs when a human runs it."""
    workflows = sorted(p.name for p in (_REPO / ".github" / "workflows").glob("*.yml"))
    assert workflows == ["terminal-ci.yml"], \
        f"a new workflow landed ({workflows}) -- re-read it and correct check_dag_registry_schedule's docstring"
    body = (_REPO / ".github" / "workflows" / "terminal-ci.yml").read_text(encoding="utf-8")
    assert "apps/terminal/**" in body
    assert "config_check" not in body


def test_the_rules_are_imported_and_not_copied():
    """One rule, one implementation. A second copy inside config_check would be a second answer to
    the same question, and the two would diverge the first time either was edited."""
    src = inspect.getsource(cc.check_dag_registry_schedule)
    assert "_gen.lint_chain_shape_matches_phases(" in src
    assert "_gen.lint_served_tables_have_a_producer(" in src
    assert not hasattr(cc, "lint_chain_shape_matches_phases")
    assert not hasattr(cc, "lint_served_tables_have_a_producer")
