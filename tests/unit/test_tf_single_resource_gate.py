"""scripts/ops/tf_single_resource_gate.py -- the single-resource terraform apply gate, pinned.

Hermetic: every test reads a SAVED plan JSON off disk and calls a pure function. No terraform, no
AWS, no network.

THE TWO FIXTURES ARE REAL PLANS, trimmed to the keys the gate reads.

  tests/fixtures/tf_plans/tf_plan_futures_jobdef.json   the 2026-09-06 futures_eod_silver repin:
      0 add / 1 change / 0 destroy, and the only thing that effectively moved is
      container_properties.image.  This is the plan a hand-written gate refused THREE times.
  tests/fixtures/tf_plans/tf_plan_sfn_definition.json   a Lane-B silver_thin_contract state
      machine update: only ``definition`` moved, and its address carries NO index.

Both keep all four ``resource_changes`` (the three no-ops included -- the gate's first clause
counts what is NOT a no-op, so a fixture stripped of them could not fail that clause) and drop
``configuration`` / ``prior_state`` / ``planned_values`` / ``variables``: ~1.1 MB apiece that no
code path in the gate touches.

EACH NO-OP IS A STUB: ``{"actions": ["no-op"]}`` and nothing else.  MEASURED 2026-09-06 (review of
the first build, which kept the no-op bodies): those three untouched resources carried the
AWS-minted discriminators of two secret ARNs -- ``...leviathan-dev-anthropic-api-key-Dqlwe6`` and
``...evidence-pg-dsn-VbjJwZ``, both at ZERO tracked files anywhere else in this PUBLIC repo -- plus
the full inline IAM policy documents of batch_execution_role / silver_publisher / sfn_exec, in a
class ``.gitignore:71`` already calls sensitive ("terraform saved plans (may embed sensitive
values)").  The gate reads NOTHING from a no-op but its ``actions``, so the stub keeps every clause
those fixtures exist for while the strings stop being published: the discriminators went 2 -> 0
each and the fixtures 20,203 -> 7,280 B and 44,816 -> 32,801 B.
``TestTheFixturesCarryNoSecretSurface`` is the pin that would have caught it.

WHAT EACH PIN CLOSES -- the three shapes that refused a correct apply, then the negatives:

  (1) the live address carries a count index          TestAddress
  (2) arn/revision are computed at apply time         TestComputedAttributes
  (3) AWS normalises the empties the config omits     TestNormalisation
  a second resource / a destroy / an envelope move / an env value hidden inside the descriptor
                                                      TestNegatives
  the four false PASSes the review measured           TestTheMeasuredFalsePasses
  the fixtures publish no secret surface              TestTheFixturesCarryNoSecretSurface
  the runbooks route the plan JSON somewhere ignored  TestTheRunbooksGateTheirApplies
"""
from __future__ import annotations

import ast
import contextlib
import copy
import importlib.util
import io
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "scripts" / "ops" / "tf_single_resource_gate.py"
_FIXTURES = _REPO / "tests" / "fixtures" / "tf_plans"   # the estate's one fixtures root

FUTURES_ADDRESS = "module.batch.aws_batch_job_definition.futures_eod_silver"
SFN_ADDRESS = "module.step_functions.aws_sfn_state_machine.silver_thin_contract"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("tf_single_resource_gate", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def futures_plan():
    return _load("tf_plan_futures_jobdef.json")


@pytest.fixture
def sfn_plan():
    return _load("tf_plan_sfn_definition.json")


def _moved(plan: dict) -> dict:
    return next(rc for rc in plan["resource_changes"] if rc["change"]["actions"] != ["no-op"])


def _container(change: dict, side: str) -> dict:
    return json.loads(change[side]["container_properties"])


def _set_container(change: dict, side: str, container: dict) -> None:
    change[side]["container_properties"] = json.dumps(container)


def _gate_futures(tool, plan, **kw):
    kw.setdefault("expect_unchanged_envelope", True)
    return tool.gate(plan, FUTURES_ADDRESS, ["container_properties.image"], **kw)


class TestTheFixturesAreTheRealPlans:
    def test_they_carry_the_no_ops_and_stay_small(self):
        """A fixture is only useful if it can fail the clause it exists for, and only welcome in
        the tree if it is not a data dump. Four resource_changes each, under 60 KB each."""
        for name, address in (("tf_plan_futures_jobdef.json", FUTURES_ADDRESS + "[0]"),
                              ("tf_plan_sfn_definition.json", SFN_ADDRESS)):
            blob = (_FIXTURES / name).read_bytes()
            assert len(blob) < 60_000, (name, len(blob))
            plan = json.loads(blob.decode("utf-8"))
            assert len(plan["resource_changes"]) == 4, name
            noop = [rc for rc in plan["resource_changes"] if rc["change"]["actions"] == ["no-op"]]
            assert len(noop) == 3, name
            assert _moved(plan)["address"] == address

    def test_every_no_op_change_is_a_bare_actions_stub(self):
        """The fix for the review's first standing finding, asserted as a shape rather than as a
        string blocklist: a no-op's before/after is what carried the secret ARNs and the inline
        IAM policy documents, and the gate reads only its ``actions``. Anything else in a no-op
        change is a body that came back."""
        for name in ("tf_plan_futures_jobdef.json", "tf_plan_sfn_definition.json"):
            plan = _load(name)
            for rc in plan["resource_changes"]:
                if rc["change"]["actions"] == ["no-op"]:
                    assert set(rc["change"]) == {"actions"}, (name, rc["address"],
                                                              sorted(rc["change"]))


class TestTheFixturesCarryNoSecretSurface:
    """THE PIN THE FIRST BUILD DID NOT HAVE. It shipped two AWS-minted secret-ARN discriminators
    (``Dqlwe6``, ``VbjJwZ``) and three inline IAM policy documents into a PUBLIC repo, under an
    exposure flag that said they were already present in 42 tracked files -- MEASURED false: both
    were at ZERO tracked files. These fixtures are the estate's first plan JSONs, and .gitignore:71
    calls saved plans a sensitive class, so what they may contain is asserted, not asserted-about.
    """

    # Everything with an account in it that the two fixtures may carry, enumerated. Each of these
    # identifiers appears in tracked files OUTSIDE tests/fixtures/tf_plans (measured 2026-09-06,
    # `git grep -l -F`: sfn-exec 1, silver-thin-contract 4, alerts 5, batch-execution-role 12,
    # futures-eod-silver 16, account id 42, silver-publisher 59) -- publishing them here adds no
    # identifier the repo did not already carry. A NEW arn in a re-captured fixture reddens this.
    ALLOWED_ARNS = {
        "arn:aws:batch:us-east-1:668891723125:job-definition/leviathan-dev-futures-eod-silver",
        "arn:aws:batch:us-east-1:668891723125:job-definition/leviathan-dev-futures-eod-silver:6",
        "arn:aws:iam::668891723125:role/leviathan-dev-batch-execution-role",
        "arn:aws:iam::668891723125:role/leviathan-dev-sfn-exec",
        "arn:aws:iam::668891723125:role/leviathan-dev-silver-publisher",
        "arn:aws:logs:us-east-1:668891723125:log-group:"
        "/aws/vendedlogs/states/leviathan-dev-silver-thin-contract:*",
        "arn:aws:sns:us-east-1:668891723125:leviathan-dev-alerts",
        "arn:aws:states:::batch:submitJob.sync",
        "arn:aws:states:::glue:startJobRun.sync",
        "arn:aws:states:::sns:publish",
        "arn:aws:states:us-east-1:668891723125:stateMachine:leviathan-dev-silver-thin-contract",
    }
    # secretsmanager: the two secret ARNs. Statement/Action/assume_role_policy: an IAM policy
    # document. AKIA/ASIA: a long-lived access key, which no plan should ever carry.
    FORBIDDEN = ("secretsmanager", "assume_role_policy", '"Statement"', '"Action"',
                 "AKIA", "ASIA", "PRIVATE KEY", "Dqlwe6", "VbjJwZ")

    @pytest.mark.parametrize("name", ["tf_plan_futures_jobdef.json", "tf_plan_sfn_definition.json"])
    def test_no_secret_or_policy_surface(self, name):
        text = (_FIXTURES / name).read_text(encoding="utf-8")
        for needle in self.FORBIDDEN:
            assert needle not in text, (name, needle)

    @pytest.mark.parametrize("name", ["tf_plan_futures_jobdef.json", "tf_plan_sfn_definition.json"])
    def test_every_arn_is_one_of_the_declared_ones(self, name):
        found = set(re.findall(r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:\d*:[A-Za-z0-9:/_.*-]*",
                               (_FIXTURES / name).read_text(encoding="utf-8")))
        assert found <= self.ALLOWED_ARNS, sorted(found - self.ALLOWED_ARNS)


class TestTheRealPlansPass:
    def test_the_futures_repin_passes(self, tool, futures_plan):
        ok, report = _gate_futures(tool, futures_plan)
        assert ok, "\n".join(report)

    def test_the_sfn_definition_update_passes(self, tool, sfn_plan):
        ok, report = tool.gate(sfn_plan, SFN_ADDRESS, ["definition"])
        assert ok, "\n".join(report)

    # Every informational (non-verdict) line the report may emit. The first build's clause here
    # was `or ":" in ln`, which every line satisfies by construction -- the one clause in this deck
    # that could not be made to go red. An enumerated set can: add an unprefixed report line and
    # this fails. The per-attribute line is a pattern rather than a name so that gating some third
    # attribute does not need this list edited (which would make it a rubber stamp again).
    INFO_PREFIXES = ("plan stamp:", "plan:", "  moved:", "computed after apply",
                     "excused by --allow-unknown", "excused (only apply-time-unknown",
                     "attributes moved (")
    INFO_PATTERN = re.compile(r"^\S+ keys moved \((RAW|NORMALISED)")

    @pytest.mark.parametrize("which", ["futures", "sfn"])
    def test_the_report_is_ascii_and_every_line_is_a_verdict_or_a_named_fact(self, tool, which,
                                                                            futures_plan,
                                                                            sfn_plan):
        if which == "futures":
            ok, report = _gate_futures(tool, futures_plan)
        else:
            ok, report = tool.gate(sfn_plan, SFN_ADDRESS, ["definition"])
        for line in report:
            line.encode("ascii")
            assert (line.startswith(("PASS ", "FAIL ") + self.INFO_PREFIXES)
                    or self.INFO_PATTERN.match(line)), line
        assert ok

    def test_the_plan_stamp_is_reported_so_a_stale_json_is_visible(self, tool, futures_plan):
        """Nothing binds --plan-json to the .tfplan that gets applied (module docstring says so).
        The stamp is the tripwire: it must be printed, and it must be the plan's own."""
        _, report = _gate_futures(tool, futures_plan)
        stamp = next(ln for ln in report if ln.startswith("plan stamp:"))
        assert futures_plan["timestamp"] in stamp
        assert futures_plan["terraform_version"] in stamp

    def test_the_envelope_is_read_and_stated(self, tool, futures_plan):
        """C-M2's law on the terraform side: the envelope is asserted, never assumed."""
        _, report = _gate_futures(tool, futures_plan)
        envelope = [ln for ln in report if "the envelope is unchanged" in ln]
        assert len(envelope) == 1
        assert "VCPU" in envelope[0] and "MEMORY" in envelope[0]


class TestAddress:
    """Refusal (1): the count-gated resource's live address is ...futures_eod_silver[0]."""

    def test_the_index_free_address_matches_the_indexed_live_address(self, tool, futures_plan):
        assert _moved(futures_plan)["address"] == FUTURES_ADDRESS + "[0]"
        ok, _ = _gate_futures(tool, futures_plan)
        assert ok

    def test_the_exact_indexed_address_also_matches(self, tool, futures_plan):
        ok, _ = tool.gate(futures_plan, FUTURES_ADDRESS + "[0]", ["container_properties.image"],
                          expect_unchanged_envelope=True)
        assert ok

    def test_a_different_resource_in_the_same_module_is_refused(self, tool, futures_plan):
        ok, report = tool.gate(futures_plan,
                               "module.batch.aws_batch_job_definition.futures_eod_bronze",
                               ["container_properties.image"])
        assert not ok
        assert any("the moved resource is the targeted address" in ln and ln.startswith("FAIL")
                   for ln in report)

    def test_an_indexed_expectation_is_matched_EXACTLY(self, tool):
        """D11's measured trap from the other side: a -target on the wrong for_each key is a LIVE
        schedule belonging to another lane, so an expectation that names its key never widens."""
        family = 'module.eventbridge.aws_scheduler_schedule.family'
        assert tool.address_matches(f'{family}["pink_sheet_monthly"]',
                                    f'{family}["pink_sheet_monthly"]')
        assert not tool.address_matches(f'{family}["pink_sheet_monthly"]',
                                        f'{family}["psd_monthly"]')
        # ... while the index-free form admits the index, which is the whole point of refusal (1).
        assert tool.address_matches(family, f'{family}["psd_monthly"]')

    def test_a_prefix_that_is_not_an_index_is_not_a_match(self, tool):
        assert not tool.address_matches("module.batch.aws_batch_job_definition.futures",
                                        "module.batch.aws_batch_job_definition.futures_eod[0]")


class TestComputedAttributes:
    """Refusal (2): arn and revision are minted by the register, and the plan says so."""

    def test_arn_and_revision_move_raw_and_are_excused_by_after_unknown(self, tool, futures_plan):
        change = _moved(futures_plan)["change"]
        assert change["before"]["arn"] and change["after"].get("arn") is None
        assert change["before"]["revision"] and change["after"].get("revision") is None
        _, report = _gate_futures(tool, futures_plan)
        raw = next(ln for ln in report if ln.startswith("attributes moved (RAW"))
        effective = next(ln for ln in report if ln.startswith("attributes moved (after removing"))
        assert "'arn'" in raw and "'revision'" in raw
        assert "'arn'" not in effective and "'revision'" not in effective
        assert "container_properties" in effective

    def test_the_unknown_mirror_is_read_RECURSIVELY_not_by_truthiness(self, tool, futures_plan):
        """MEASURED: this plan's after_unknown carries ``timeout: [{}]`` and
        ``platform_capabilities: [false]`` -- shapes with NO unknown inside them. The hand-written
        gate's truthiness test called both 'computed after apply' and would have excused a real
        move of either. Only arn and revision are actually computed here."""
        mirror = _moved(futures_plan)["change"]["after_unknown"]
        assert mirror["timeout"] == [{}] and mirror["platform_capabilities"] == [False]
        assert tool._has_unknown(mirror["arn"]) and tool._has_unknown(mirror["revision"])
        assert not tool._has_unknown(mirror["timeout"])
        assert not tool._has_unknown(mirror["platform_capabilities"])
        _, report = _gate_futures(tool, futures_plan)
        computed = next(ln for ln in report if ln.startswith("computed after apply"))
        assert "'arn'" in computed and "'revision'" in computed
        assert "timeout" not in computed and "platform_capabilities" not in computed

    def test_a_real_move_of_timeout_is_therefore_still_caught(self, tool, futures_plan):
        change = _moved(futures_plan)["change"]
        change["after"]["timeout"] = [{"attempt_duration_seconds": 60}]
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "unexpected" in ln and "timeout" in ln
                   for ln in report)

    def test_allow_unknown_excuses_it_when_the_operator_says_so(self, tool, futures_plan):
        change = _moved(futures_plan)["change"]
        change["after"]["timeout"] = [{"attempt_duration_seconds": 60}]
        ok, report = _gate_futures(tool, futures_plan, allow_unknown=["timeout"])
        assert ok, "\n".join(report)
        assert any("excused by --allow-unknown" in ln for ln in report)


class TestNormalisation:
    """Refusal (3): eight container keys read as moved raw; exactly one of them really moved."""

    def test_the_raw_diff_names_eight_keys_and_the_normalised_diff_names_one(self, tool,
                                                                            futures_plan):
        _, report = _gate_futures(tool, futures_plan)
        raw = next(ln for ln in report if ln.startswith("container_properties keys moved (RAW)"))
        normalised = next(ln for ln in report
                          if ln.startswith("container_properties keys moved (NORMALISED"))
        for key in ("environment", "fargatePlatformConfiguration", "image", "logConfiguration",
                    "mountPoints", "secrets", "ulimits", "volumes"):
            assert key in raw, key
        assert normalised.endswith("['image']"), normalised

    def test_each_provider_empty_is_undone_by_name(self, tool, futures_plan):
        """The four empty lists, the minted fargate block and the nested secretOptions, read off
        the plan rather than asserted from memory."""
        change = _moved(futures_plan)["change"]
        before, after = _container(change, "before"), _container(change, "after")
        for key in ("mountPoints", "secrets", "ulimits", "volumes"):
            assert before[key] == [] and key not in after, key
        assert before["fargatePlatformConfiguration"] == {"platformVersion": "LATEST"}
        assert after.get("fargatePlatformConfiguration") is None
        assert before["logConfiguration"]["secretOptions"] == []
        assert "secretOptions" not in after["logConfiguration"]
        n_b = tool.normalise_container_properties(before)
        n_a = tool.normalise_container_properties(after)
        moved = sorted(k for k in set(n_b) | set(n_a) if n_b.get(k) != n_a.get(k))
        assert moved == ["image"]

    def test_environment_is_order_free_but_value_sensitive(self, tool, futures_plan):
        """Order-normalising env is what lets the gate pass; it must not also hide a value."""
        change = _moved(futures_plan)["change"]
        after = _container(change, "after")
        assert len(after["environment"]) > 1
        reordered = dict(after, environment=list(reversed(after["environment"])))
        assert (tool.normalise_container_properties(reordered)
                == tool.normalise_container_properties(after))

    def test_command_order_is_NOT_normalised(self, tool, futures_plan):
        """Deliberate non-coverage: argv order is meaningful, so it is never sorted."""
        change = _moved(futures_plan)["change"]
        after = _container(change, "after")
        assert len(after["command"]) > 1
        flipped = dict(after, command=list(reversed(after["command"])))
        assert (tool.normalise_container_properties(flipped)
                != tool.normalise_container_properties(after))


class TestTheMeasuredFalsePasses:
    """Four plans the FIRST build signed for. Each one is a real refusal now."""

    def test_a_known_change_beside_an_unknown_leaf_is_no_longer_excused(self, tool, futures_plan):
        """MEASURED false PASS: `after['tags'] = {'owner': 'attacker'}` with
        `after_unknown['tags'] = {'computed_one': True}` PASSED, while the identical tags change
        with no unknown leaf FAILED. after_unknown was read per ATTRIBUTE; it is read per LEAF."""
        change = _moved(futures_plan)["change"]
        change["after"]["tags"] = {"owner": "attacker"}
        change["after_unknown"]["tags"] = {"computed_one": True}
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "unexpected" in ln and "tags" in ln for ln in report)

    def test_a_wholly_unknown_attribute_is_still_excused(self, tool, futures_plan):
        """The control: tightening the excusal must not un-excuse arn/revision, whose mirrors are
        plain `true` all the way down. Without this the fix would just be a stricter gate."""
        mirror = _moved(futures_plan)["change"]["after_unknown"]
        assert mirror["arn"] is True and mirror["revision"] is True
        ok, report = _gate_futures(tool, futures_plan)
        assert ok, "\n".join(report)
        excused = next(ln for ln in report if ln.startswith("excused (only apply-time-unknown"))
        assert "'arn'" in excused and "'revision'" in excused

    def test_a_DUPLICATE_environment_entry_is_no_longer_collapsed(self, tool, futures_plan):
        """MEASURED false PASS: environment was normalised into a NAME-KEYED dict, so one extra
        copy of an entry on one side and two on the other read as no diff at all. It is sorted
        (name, value) pairs now -- order-free, which is what the provider's reordering needs,
        without being count-free."""
        change = _moved(futures_plan)["change"]
        before, after = _container(change, "before"), _container(change, "after")
        dup = dict(before["environment"][0])
        before["environment"].append(dup)
        after["environment"].extend([dict(dup), dict(dup)])
        _set_container(change, "before", before)
        _set_container(change, "after", after)
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        normalised = next(ln for ln in report
                          if ln.startswith("container_properties keys moved (NORMALISED"))
        assert "environment" in normalised

    def test_allow_unknown_can_now_rescue_a_partly_unknown_EXPECTED_attribute(self, tool,
                                                                             futures_plan):
        """MEASURED dead end: excusing the EXPECTED attribute removed it from `effective` and the
        'every expected attribute actually moved' clause then fired, so NO flag combination
        admitted a plan whose expected attribute is partly computed -- the shape of refusal #4."""
        change = _moved(futures_plan)["change"]
        change["after_unknown"]["container_properties"] = True
        ok, report = tool.gate(futures_plan, FUTURES_ADDRESS, ["container_properties"],
                               allow_unknown=["container_properties"])
        assert ok, "\n".join(report)
        assert not any("did not move" in ln and ln.startswith("FAIL") for ln in report)

    def test_a_STILL_absent_expected_attribute_is_not_rescued_by_the_flag(self, tool,
                                                                         futures_plan):
        """The fail-closed half of the clause above: --allow-unknown excuses HOW an expected
        attribute moved, never WHETHER it moved. A vacuous plan stays a refusal."""
        change = _moved(futures_plan)["change"]
        change["after"]["container_properties"] = change["before"]["container_properties"]
        ok, report = tool.gate(futures_plan, FUTURES_ADDRESS, ["container_properties"],
                               allow_unknown=["container_properties"])
        assert not ok
        assert any(ln.startswith("FAIL") and "did not move" in ln for ln in report)

    @pytest.mark.parametrize("mutate, label", [
        (lambda c: c.__setitem__("image", ""), "empty string"),
        (lambda c: c.pop("image"), "key deleted"),
    ])
    def test_an_EMPTY_or_ABSENT_expected_subkey_is_refused(self, tool, futures_plan, mutate,
                                                           label):
        """MEASURED false PASS: both of these produce the normalised diff ['image'] and used to
        pass. The gate still never checks WHICH digest -- only that a value is there at all."""
        change = _moved(futures_plan)["change"]
        after = _container(change, "after")
        mutate(after)
        _set_container(change, "after", after)
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok, label
        assert any(ln.startswith("FAIL") and "still carries a value" in ln for ln in report), label


class TestNegatives:
    def test_a_SECOND_resource_in_the_plan_is_refused(self, tool, futures_plan):
        """The clause the whole tool exists for: one resource, or no apply."""
        noop = next(rc for rc in futures_plan["resource_changes"]
                    if rc["change"]["actions"] == ["no-op"])
        noop["change"]["actions"] = ["update"]
        # .get, not []: a no-op fixture entry is a bare {"actions": [...]} stub -- see the module
        # docstring on what its before/after used to publish.
        noop["change"]["after"] = dict(noop["change"].get("after") or {}, tags={"lane": "G"})
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "exactly ONE resource moves" in ln for ln in report)
        assert any(noop["address"] in ln for ln in report), "the report must NAME the intruder"

    def test_a_DESTROY_is_refused(self, tool, futures_plan):
        change = _moved(futures_plan)["change"]
        change["actions"] = ["delete", "create"]
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "pure in-place update" in ln for ln in report)

    def test_a_ZERO_change_plan_is_refused(self, tool, futures_plan):
        """MEASURED 2026-09-04: a -target on an address that resolves to nothing plans zero
        changes and reads as 'already armed'. Zero is not success."""
        _moved(futures_plan)["change"]["actions"] = ["no-op"]
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "0 moved" in ln for ln in report)

    def test_an_ENVELOPE_change_is_refused(self, tool, futures_plan):
        """A descriptor re-authored from constants reverts the post-OOM memory bump silently."""
        change = _moved(futures_plan)["change"]
        after = _container(change, "after")
        after["resourceRequirements"] = [
            {"type": r["type"], "value": "1024" if r["type"] == "MEMORY" else r["value"]}
            for r in after["resourceRequirements"]]
        _set_container(change, "after", after)
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "the envelope is unchanged" in ln for ln in report)

    def test_an_ENV_VALUE_hidden_inside_container_properties_is_refused(self, tool, futures_plan):
        """The value the normalisation must NOT swallow: same env keys, same order, one new value.
        A gate that only compared the image string would sign for this."""
        change = _moved(futures_plan)["change"]
        after = _container(change, "after")
        after["environment"][0] = dict(after["environment"][0], value="flipped-by-the-test")
        _set_container(change, "after", after)
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        normalised = next(ln for ln in report
                          if ln.startswith("container_properties keys moved (NORMALISED"))
        assert "environment" in normalised and "image" in normalised
        assert any(ln.startswith("FAIL") and "moved inside container_properties" in ln
                   for ln in report)

    def test_a_VACUOUS_plan_that_moves_nothing_expected_is_refused(self, tool, futures_plan):
        """The expected attribute did not move: the saved plan does not carry the change the
        operator is signing for. Same failure mode as the rev-110 vacuous gate."""
        change = _moved(futures_plan)["change"]
        change["after"]["container_properties"] = change["before"]["container_properties"]
        ok, report = _gate_futures(tool, futures_plan)
        assert not ok
        assert any(ln.startswith("FAIL") and "did not move" in ln
                   and "container_properties" in ln for ln in report)

    def test_the_sfn_gate_refuses_a_second_attribute(self, tool, sfn_plan):
        change = _moved(sfn_plan)["change"]
        change["after"]["role_arn"] = change["before"]["role_arn"] + "-swapped"
        ok, report = tool.gate(sfn_plan, SFN_ADDRESS, ["definition"])
        assert not ok
        assert any(ln.startswith("FAIL") and "role_arn" in ln for ln in report)

    def test_the_envelope_clause_refuses_a_resource_that_has_none(self, tool, sfn_plan):
        """--expect-unchanged-envelope is a Batch clause; asking for it on a state machine is an
        operator error and must not pass silently."""
        ok, report = tool.gate(sfn_plan, SFN_ADDRESS, ["definition"],
                               expect_unchanged_envelope=True)
        assert not ok
        assert any(ln.startswith("FAIL") and "container_properties" in ln for ln in report)

    def test_no_expectation_at_all_is_refused(self, tool, futures_plan):
        ok, report = tool.gate(futures_plan, FUTURES_ADDRESS, [])
        assert not ok
        assert "at least one --expect-changed" in "\n".join(report)


class TestCli:
    def test_main_exits_zero_on_the_real_plan_and_one_on_a_mutated_one(self, tool, tmp_path,
                                                                      capsys):
        good = _FIXTURES / "tf_plan_futures_jobdef.json"
        assert tool.main(["--plan-json", str(good), "--address", FUTURES_ADDRESS,
                          "--expect-changed", "container_properties.image",
                          "--expect-unchanged-envelope"]) == 0
        assert "TF SINGLE-RESOURCE GATE: PASS" in capsys.readouterr().out

        plan = copy.deepcopy(_load("tf_plan_futures_jobdef.json"))
        _moved(plan)["change"]["actions"] = ["delete", "create"]
        bad = tmp_path / "bad_plan.json"
        bad.write_text(json.dumps(plan), encoding="utf-8")
        assert tool.main(["--plan-json", str(bad), "--address", FUTURES_ADDRESS,
                          "--expect-changed", "container_properties.image"]) == 1
        assert "TF SINGLE-RESOURCE GATE: FAIL" in capsys.readouterr().out

    def test_a_BOM_stamped_plan_file_is_read(self, tool, tmp_path, capsys):
        """The operator's shell is PowerShell 5.1, where `| Out-File -Encoding utf8` stamps a BOM
        on the `terraform show -json` output. A utf-8 read dies at char 0 and the gate becomes the
        step everyone skips."""
        blob = (_FIXTURES / "tf_plan_futures_jobdef.json").read_text(encoding="utf-8")
        path = tmp_path / "bom_plan.json"
        path.write_text(blob, encoding="utf-8-sig")
        assert path.read_bytes()[:3] == b"\xef\xbb\xbf"
        assert tool.main(["--plan-json", str(path), "--address", FUTURES_ADDRESS,
                          "--expect-changed", "container_properties.image",
                          "--expect-unchanged-envelope"]) == 0
        capsys.readouterr()

    def test_expect_changed_is_repeatable(self, tool, tmp_path, capsys):
        plan = copy.deepcopy(_load("tf_plan_futures_jobdef.json"))
        change = _moved(plan)["change"]
        change["after"]["propagate_tags"] = not change["before"]["propagate_tags"]
        path = tmp_path / "two_attrs.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        assert tool.main(["--plan-json", str(path), "--address", FUTURES_ADDRESS,
                          "--expect-changed", "container_properties.image",
                          "--expect-changed", "propagate_tags"]) == 0
        capsys.readouterr()


def _load_runbook(name: str):
    path = _REPO / "scripts" / "ops" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _printed(mod) -> list[str]:
    return [cmd for _title, cmds in mod.steps("x") for cmd in cmds]


def _rollback_text(mod) -> str:
    """The rollback recipe. It is PRINTED, not returned, and it is not part of steps() -- which is
    exactly why the first build's apply pins could not see it."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.rollback()
    return buf.getvalue()


# The .gitignore rule that has to cover every plan JSON these runbooks tell an operator to write.
_TFPLAN_RULE = "infra/terraform/**/tfplan*"


def _covered_by_the_tfplan_rule(path: str) -> bool:
    """``infra/terraform/**/tfplan*`` spelled out: git's ``**`` spans zero or more directories, so
    the rule covers any file under infra/terraform/ whose own NAME begins with ``tfplan``.

    VERIFIED against the real matcher on 2026-09-06 -- ``git check-ignore -v`` calls
    ``infra/terraform/envs/dev/tfplan_pink_bronze.json`` IGNORED (.gitignore:72) and, from the
    other side, ``pink_bronze_plan.json`` / ``pink_schedule_plan.json`` / ``tf_plan.json`` at the
    repo root NOT IGNORED. This function is that result, frozen; the rule's presence in .gitignore
    is asserted separately, so deleting the rule reddens the pin rather than this stand-in.
    """
    parts = path.split("/")
    return parts[:2] == ["infra", "terraform"] and len(parts) >= 3 \
        and parts[-1].startswith("tfplan")


# The .gitignore rule that has to cover the OTHER half of the same step: the BINARY saved plan.
# It is not a second artifact, it is the same payload -- the 1.1 MB JSON is what
# ``terraform show -json`` renders FROM it -- and .gitignore:71's own comment is about the binary.
_SAVED_PLAN_RULE = "infra/terraform/**/*.tfplan"


def _covered_by_the_saved_plan_rule(path: str) -> bool:
    """``infra/terraform/**/*.tfplan`` spelled out, frozen exactly like the rule above.

    VERIFIED against the real matcher on 2026-09-07 -- ``git check-ignore -v`` calls
    ``infra/terraform/envs/dev/lane.tfplan`` IGNORED (.gitignore:73) and, from the other side,
    ``infra/terraform/envs/dev/tf.plan`` -- the spelling all three recipes used to carry -- NOT
    IGNORED, because ``tfplan*`` wants the NAME to start with tfplan and ``*.tfplan`` wants the
    extension, and ``tf.plan`` is neither.
    """
    parts = path.split("/")
    return parts[:2] == ["infra", "terraform"] and len(parts) >= 3 \
        and parts[-1].endswith(".tfplan")


def _resolved_by_chdir(line: str, target: str) -> str:
    """Where a saved-plan filename on this line actually lands.

    MEASURED 2026-09-07 with the real terraform v1.15.2 on an offline scratch config:
    ``-chdir=envs/dev plan -out=lane.tfplan`` lands at ``envs/dev/lane.tfplan`` and is ABSENT from
    the operator's cwd; ``-chdir=envs/dev show -json lane.tfplan`` reads it while
    ``show -json envs/dev/lane.tfplan`` cannot ("Failed to read the given file"); and
    ``| Out-File -Encoding utf8 envs/dev/tfplan_lane.json`` lands relative to the OPERATOR's
    location, not -chdir's. So terraform's own filename arguments resolve inside -chdir and the
    redirect does not -- which is why the JSON is spelled in full and the .tfplan is not.

    A recipe line carrying no ``-chdir`` therefore names an operator-cwd path (the repo root), and
    that is exactly the shape this pin exists to redden.
    """
    chdir = re.search(r"-chdir=(\S+)", line)
    return (chdir.group(1).rstrip("/") + "/" + target) if chdir else target


def _plan_artifacts(text: str) -> dict:
    """The five plan-artifact spellings a printed recipe carries, saved-plan paths resolved.

    ``apply`` is anchored on the ``.tfplan`` extension so the prose around these recipes -- "apply
    THAT FILE", "a saved-plan apply does not pause" -- is not read as a command.
    """
    outs: list[str] = []
    shows: list[str] = []
    applies: list[str] = []
    for line in text.splitlines():
        for match in re.finditer(r"-out=(\S+)", line):
            outs.append(_resolved_by_chdir(line, match.group(1)))
        for match in re.finditer(r"\bshow\s+-json\s+(\S+)", line):
            shows.append(_resolved_by_chdir(line, match.group(1)))
        for match in re.finditer(r"\bapply\s+(\S+\.tfplan)\b", line):
            applies.append(_resolved_by_chdir(line, match.group(1)))
    return {"-out=": outs, "show -json": shows, "apply": applies,
            "Out-File sink": re.findall(r"Out-File\s+-Encoding\s+utf8\s+(\S+)", text),
            "--plan-json": re.findall(r"--plan-json\s+(\S+)", text)}


def _tool_docstring_recipe() -> str:
    """THE RECIPE BLOCK AT THE TOP OF THE TOOL'S OWN MODULE DOCSTRING.

    It is the first thing anyone reads about this gate and the block an operator pastes, and it is
    where the review's standing finding survived TWO fix passes: the pin read the two runbooks and
    never opened the file the lane is named after. The block is the indented run that ends at the
    first blank line. The prose below it names artifact shapes (``--plan-json tfplan_x.json`` and
    ``apply x.tfplan``) as EXAMPLES of two files nothing binds together, not as a recipe, and is
    deliberately out of scope -- which is why this reads the block rather than the whole docstring.
    """
    doc = ast.get_docstring(ast.parse(_TOOL.read_text(encoding="utf-8")))
    lines = doc.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("    "))
    end = next(i for i in range(start, len(lines)) if not lines[i].strip())
    return "\n".join(lines[start:end])


_TOOL_DOCSTRING = "tf_single_resource_gate docstring"
# EVERY PLACE IN THIS REPO THAT PRINTS THE RECIPE. The review's standing finding was that a fix
# reached two of them while the pin could see only those same two; adding a third printed recipe
# without registering it here is the one gap this list cannot close by itself.
_RECIPE_SOURCES = (_TOOL_DOCSTRING, "pink_vintages_runbook", "esr_netcommitment_runbook")


def _recipe_text(source: str) -> str:
    if source == _TOOL_DOCSTRING:
        return _tool_docstring_recipe()
    module = _load_runbook(source)
    text = "\n".join(_printed(module))
    if source == "pink_vintages_runbook":
        text += "\n" + _rollback_text(module)
    return text


class TestTheRunbooksGateTheirApplies:
    """A tool nobody is told to run is not a gate. The two runbooks that hand a terraform apply
    must hand this one BETWEEN the plan and the apply -- and must apply the SAVED plan file,
    because a re-plan is a second shape the gate never read."""

    def test_pink_D2_and_D11_put_the_gate_between_plan_and_apply(self):
        printed = _printed(_load_runbook("pink_vintages_runbook"))
        commands = [(i, c) for i, c in enumerate(printed) if not c.lstrip().startswith("#")]
        plans = [i for i, c in commands if "terraform" in c and " plan " in c]
        gates = [i for i, c in commands if "tf_single_resource_gate.py" in c]
        applies = [i for i, c in commands if "terraform" in c and " apply " in c]
        assert len(plans) == len(gates) == len(applies) == 2, (plans, gates, applies)
        for plan_at, gate_at, apply_at in zip(plans, gates, applies):
            assert plan_at < gate_at < apply_at, (plan_at, gate_at, apply_at)

    def test_every_pink_apply_applies_the_SAVED_plan_file(self):
        printed = _printed(_load_runbook("pink_vintages_runbook"))
        applies = [c for c in printed
                   if not c.lstrip().startswith("#") and "terraform" in c and " apply " in c]
        assert applies
        for line in applies:
            assert line.rstrip().endswith(".tfplan"), line
            assert "-target=" not in line, line

    def test_the_pink_schedule_gate_carries_the_for_each_KEY(self):
        """D11's own finding: a -target on the wrong key is another lane's LIVE schedule, so the
        gate line must name the key rather than the bare family address."""
        printed = _printed(_load_runbook("pink_vintages_runbook"))
        line = next(c for c in printed
                    if "tf_single_resource_gate.py" in c and "aws_scheduler_schedule" in c)
        assert 'family["pink_sheet_monthly"]' in line

    def test_the_gitignore_rule_the_plan_JSON_paths_rely_on_is_still_there(self):
        rules = [ln.strip() for ln in (_REPO / ".gitignore").read_text(encoding="utf-8")
                 .splitlines()]
        assert _TFPLAN_RULE in rules, (
            "the runbooks route every rendered plan JSON to infra/terraform/.../tfplan*.json "
            "BECAUSE this rule ignores it; without the rule those files land untracked in a "
            "public repo working tree")

    def test_the_gitignore_rule_the_SAVED_PLANS_rely_on_is_still_there(self):
        """The other half of the same step. `terraform show -json` RENDERS the JSON from this
        file: same account id, same ARNs, same inline IAM policy documents, and .gitignore:71's
        comment ("terraform saved plans (may embed sensitive values)") is written about it."""
        rules = [ln.strip() for ln in (_REPO / ".gitignore").read_text(encoding="utf-8")
                 .splitlines()]
        assert _SAVED_PLAN_RULE in rules, (
            "every printed recipe names its saved plan <stem>.tfplan and lets -chdir drop it "
            "inside the env directory BECAUSE this rule ignores it there; without the rule the "
            "binary plan lands untracked in a public repo working tree")

    @pytest.mark.parametrize("source", _RECIPE_SOURCES)
    def test_every_printed_plan_JSON_lands_where_the_rule_covers_it(self, source):
        """THE REVIEW'S SECOND STANDING FINDING. The first build wrote pink_bronze_plan.json /
        pink_schedule_plan.json / tf_plan.json into the operator's cwd -- the repo root -- while
        the BINARY .tfplan from the same step was ignored. Backwards: the 1.1 MB human-readable
        rendering is the half carrying the account id, 35+ ARNs, two secret ARNs and the whole
        inline IAM policy surface, in a PUBLIC repo whose co-tenant agents race the git index.
        Both the `show -json` sink and the `--plan-json` the gate reads are checked, in comments
        too: an operator pastes a commented recipe with the `#` stripped.

        NOW OVER ALL THREE PRINTED RECIPES, including the tool's own module docstring -- which is
        where this finding survived the first fix pass: the fix reached the two runbooks and the
        pin read exactly those two, so the headline file kept printing `Out-File ... tf_plan.json`
        and stayed green."""
        found = _plan_artifacts(_recipe_text(source))
        sinks, asks = found["Out-File sink"], found["--plan-json"]
        assert sinks and asks, (source, sinks, asks)
        for path in sinks + asks:
            assert _covered_by_the_tfplan_rule(path), (source, path)
        # ... and the two halves name the SAME files, or the gate reads a different plan.
        assert set(sinks) == set(asks), (source, sorted(set(sinks)), sorted(set(asks)))

    @pytest.mark.parametrize("source", _RECIPE_SOURCES)
    def test_every_printed_SAVED_PLAN_lands_where_the_rule_covers_it(self, source):
        """THE HALF THE JSON FIX LEFT BEHIND, in all three recipes at once.

        `-out=tf.plan` reads like a saved plan and is ignored by NOTHING: `tfplan*` wants the name
        to start with tfplan and `*.tfplan` wants the extension. MEASURED 2026-09-07 --
        `git check-ignore -v infra/terraform/envs/dev/tf.plan` prints nothing, and the real
        terraform v1.15.2 puts that file exactly there, because -out is resolved inside -chdir's
        directory. It is a binary in a PUBLIC repo carrying the payload the JSON is rendered from.

        All three spellings of the saved plan are read -- the `-out=` that writes it, the
        `show -json` that reads it and the `apply` that consumes it -- so renaming any one of them
        back reddens this pin."""
        found = _plan_artifacts(_recipe_text(source))
        for label in ("-out=", "show -json", "apply"):
            assert found[label], (source, label, found)
            for path in found[label]:
                assert _covered_by_the_saved_plan_rule(path), (source, label, path)

    @pytest.mark.parametrize("source", _RECIPE_SOURCES)
    def test_the_recipe_is_ONE_shape_everywhere_it_is_printed(self, source):
        """THE DIVERGENCE PIN, which is what was actually missing: each of the three fixes was
        applied by hand to its own file, so a recipe could be individually well-formed and still
        disagree with the other two.

        One shape: plan -out=<stem>.tfplan -> show -json <stem>.tfplan -> Out-File
        <envdir>/tfplan_<stem>.json -> gate --plan-json <envdir>/tfplan_<stem>.json ->
        apply <stem>.tfplan. The stem pairing is what makes the two files legible as one step, and
        it is also the cheapest guard on the tripwire the tool discloses -- nothing BINDS the JSON
        to the binary, so a rollback that borrows the forward step's JSON name would gate against
        a stale rendering and read clean."""
        found = _plan_artifacts(_recipe_text(source))
        assert set(found["-out="]) == set(found["show -json"]) == set(found["apply"]), (
            source, found)
        stems = {path.rsplit("/", 1)[-1][:-len(".tfplan")] for path in found["-out="]}
        assert {path.rsplit("/", 1)[-1] for path in found["Out-File sink"]} == {
            "tfplan_" + stem + ".json" for stem in stems}, (source, found)

    def test_the_pink_ROLLBACK_apply_is_gated_like_the_forward_one(self):
        """A rollback plan is a single-resource plan too, and it is the one an operator runs in a
        hurry. rollback() is not steps(), so the apply pins above cannot see it -- this reads the
        printed rollback directly."""
        text = _rollback_text(_load_runbook("pink_vintages_runbook"))
        assert "re-apply" in text
        assert "scripts/ops/tf_single_resource_gate.py" in text
        assert 'family["pink_sheet_monthly"]' in text

    def test_the_esr_runbook_names_the_gate_and_still_applies_no_terraform(self):
        """That lane moves its four jobdefs with repin_jobdef_digest.py and plans no terraform at
        all -- so the gate appears there as the rule for the lanes that do, and this pin fails the
        day someone adds an apply to it."""
        printed = _printed(_load_runbook("esr_netcommitment_runbook"))
        text = "\n".join(printed)
        assert "scripts/ops/tf_single_resource_gate.py" in text
        assert "--expect-unchanged-envelope" in text
        live = [c for c in printed
                if not c.lstrip().startswith("#") and "terraform" in c and " apply " in c]
        assert live == [], live


class TestItMutatesNothing:
    def test_the_tool_shells_out_to_nothing_and_imports_no_sdk(self):
        """It is a GATE, not a deploy step: it never runs terraform and never calls AWS.

        Checked on the PARSE TREE, not on the text -- the module's usage recipe PRINTS the
        ``terraform ... apply`` line an operator pastes, and a substring scan would call the
        docstring a violation."""
        tree = ast.parse(_TOOL.read_text(encoding="utf-8"))
        imported: set[str] = set()
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in ("run", "check_output", "call", "Popen", "system"):
                    called.add(name)
        assert not (imported & {"boto3", "botocore", "subprocess", "os"}), sorted(imported)
        assert called == set(), sorted(called)


class TestTheNamedSet:
    """``--address`` is REPEATABLE (2026-09-11): a family that must move together -- the three cpc_soil
    jobdefs on one per-family digest -- cannot be three saved plans (the second is stale once the first
    applies), so the gate signs for exactly the NAMED SET and runs every per-resource clause on each."""

    SECOND = "module.batch.aws_batch_job_definition.cpc_soil_to_raw"

    @classmethod
    def _two_movers(cls, plan: dict) -> dict:
        two = copy.deepcopy(plan)
        rc = copy.deepcopy(_moved(two))
        rc["address"] = cls.SECOND
        two["resource_changes"].append(rc)
        return two

    def test_one_address_is_the_original_shape(self, tool, futures_plan):
        ok, _ = _gate_futures(tool, futures_plan)
        ok_list, _ = tool.gate(futures_plan, [FUTURES_ADDRESS], ["container_properties.image"],
                               expect_unchanged_envelope=True)
        assert ok and ok_list

    def test_two_names_on_a_one_mover_plan_fail(self, tool, futures_plan):
        ok, report = tool.gate(futures_plan, [FUTURES_ADDRESS, FUTURES_ADDRESS + "_b"],
                               ["container_properties.image"], expect_unchanged_envelope=True)
        assert not ok
        assert any("2 named, 1 moved" in line for line in report)

    def test_the_named_set_passes_when_every_mover_is_named(self, tool, futures_plan):
        two = self._two_movers(futures_plan)
        ok, report = tool.gate(two, [FUTURES_ADDRESS, self.SECOND], ["container_properties.image"],
                               expect_unchanged_envelope=True)
        assert ok, report
        assert sum(1 for line in report if line.startswith("-- resource ")) == 2

    def test_an_unnamed_mover_fails_even_when_the_named_one_is_clean(self, tool, futures_plan):
        two = self._two_movers(futures_plan)
        ok, report = tool.gate(two, [FUTURES_ADDRESS], ["container_properties.image"],
                               expect_unchanged_envelope=True)
        assert not ok
        assert any("1 named, 2 moved" in line for line in report)

    def test_a_named_set_where_one_member_moves_the_envelope_fails(self, tool, futures_plan):
        two = self._two_movers(futures_plan)
        rc2 = next(rc for rc in two["resource_changes"] if rc["address"] == self.SECOND)
        after = _container(rc2["change"], "after")
        for req in after["resourceRequirements"]:
            if req["type"] == "MEMORY":
                req["value"] = "8192"
        _set_container(rc2["change"], "after", after)
        ok, report = tool.gate(two, [FUTURES_ADDRESS, self.SECOND], ["container_properties.image"],
                               expect_unchanged_envelope=True)
        assert not ok
        assert any("the envelope is unchanged" in line and line.startswith("FAIL") for line in report)

    def test_the_cli_accepts_a_repeated_address(self, tool, futures_plan, tmp_path):
        two = self._two_movers(futures_plan)
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(two), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tool.main(["--plan-json", str(path), "--address", FUTURES_ADDRESS,
                            "--address", self.SECOND, "--expect-changed", "container_properties.image",
                            "--expect-unchanged-envelope"])
        assert rc == 0, buf.getvalue()
        assert "TF SINGLE-RESOURCE GATE: PASS" in buf.getvalue()
