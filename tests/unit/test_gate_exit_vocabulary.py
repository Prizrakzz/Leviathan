"""D-PR-8 + D-PR-10: the gate's EXIT-CODE VOCABULARY, and the two artifacts that consume it.

Before the split, `silver_rebuild_gate.main()` returned 1 for five different outcomes and an unhandled
exception exited 1 as well -- so "the gate REFUSED this rebuild" and "the gate never ran" were the same
observable. That is not an aesthetic complaint: census class D-iii was a `ModuleNotFoundError: psycopg`
inside the gate image, and it read to the operator exactly like a data refusal.

The vocabulary only pays off if the things that ACT on it agree with it, and those live in two other
files that no Python import can reach:

  * `infra/terraform/modules/batch/silver_gate.tf` -- the jobdef `retryStrategy`. Its whole safety
    argument is "the only retryable code is 72, and 72 cannot be a refusal". If a future edit renumbers
    EXIT_REFUSAL to 72, or adds a second retry rule, the gate starts retrying decisions.
  * `infra/terraform/modules/step_functions/main.tf` -- the [Gate] Catch classifier, which reads the
    Batch failure Cause and decides which of the two emails the owner gets.

So half of this file is a cross-artifact lint over the committed HCL, in the
tests/unit/test_pattern_records_cloud_legs.py idiom (text-shape asserts through a brace matcher; the
repo has no HCL parser dependency and `terraform validate` is the author-time gate). It is AWS-free and
terraform-free.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jobs.audit import silver_rebuild_gate as g

_REPO = Path(__file__).resolve().parents[2]
_GATE_TF = _REPO / "infra" / "terraform" / "modules" / "batch" / "silver_gate.tf"
_SFN_TF = _REPO / "infra" / "terraform" / "modules" / "step_functions" / "main.tf"


def _span(text: str, header: str, opener: str = "{", closer: str = "}", start: int = 0) -> str:
    """Return the block that `header` opens, by matching `opener`/`closer` from the header onward.

    Works for both `x = { ... }` and `x = [ ... ]`; the tests below need both, and a brace matcher
    handed a list header silently returns the FIRST element instead of the list."""
    i = text.index(header, start)
    begin, depth = i, 0
    while i < len(text):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[begin:i + 1]
        i += 1
    raise AssertionError(f"unbalanced {opener}{closer} after {header!r}")


def _block(text: str, header: str) -> str:
    """`{ ... }` convenience wrapper, anchored on a line start so that a header which is a SUFFIX of
    another state's name (FailNotify vs InfraFailNotify) cannot match the wrong one."""
    m = re.search(r"^\s*" + re.escape(header), text, re.M)
    assert m, f"{header!r} not found at a line start"
    return _span(text, header, start=m.start())


# =========================================================================================================
# 1. THE VOCABULARY ITSELF
# =========================================================================================================
def test_the_five_codes_are_pinned_and_distinct():
    """These literals are a wire contract with AWS Batch (`evaluateOnExit.onExitCode`) and with the state
    machine's Cause matcher. Renaming a constant is free; RENUMBERING one silently changes what gets
    retried in the cloud, which is why the numbers are asserted and not just their relationships."""
    assert (g.EXIT_PASS, g.EXIT_REFUSAL, g.EXIT_USAGE) == (0, 1, 64)
    assert (g.EXIT_INTERNAL, g.EXIT_PREFLIGHT, g.EXIT_BASELINE_FETCH) == (70, 71, 72)
    codes = [g.EXIT_PASS, g.EXIT_REFUSAL, g.EXIT_USAGE,
             g.EXIT_INTERNAL, g.EXIT_PREFLIGHT, g.EXIT_BASELINE_FETCH]
    assert len(set(codes)) == len(codes), "two outcomes sharing a code is the defect D-PR-8 removes"
    # 64/70 follow BSD sysexits so an operator reading a bare number has a prior.
    assert g.EXIT_USAGE == 64 and g.EXIT_INTERNAL == 70


def test_no_verdict_code_may_collide_with_the_refusal():
    """The retry rule is keyed on 72 alone. Every non-verdict code must therefore be something the jobdef
    will NOT confuse with a decision, and none of them may equal EXIT_REFUSAL."""
    for code in (g.EXIT_USAGE, g.EXIT_INTERNAL, g.EXIT_PREFLIGHT, g.EXIT_BASELINE_FETCH):
        assert code != g.EXIT_REFUSAL


# =========================================================================================================
# 2. ONE TEST PER CODE, THROUGH main()
# =========================================================================================================
def test_empty_tables_is_usage_not_refusal(capsys):
    """`--tables ","` reaches argparse fine and leaves an empty roster. Nothing was judged."""
    rc = g.main(["--tables", ","])
    assert rc == g.EXIT_USAGE
    assert "no --tables given" in capsys.readouterr().out


def test_argparse_rejection_is_usage_not_the_interpreters_exit_2():
    """argparse exits 2 on a missing required flag or an unknown one. 2 is not in the vocabulary, and
    leaving it raw would put a usage error one integer away from a refusal."""
    assert g.main([]) == g.EXIT_USAGE                                  # --tables is required
    assert g.main(["--tables", "silver_wasde", "--nope"]) == g.EXIT_USAGE


def test_help_still_exits_zero():
    """SystemExit(0) from `--help` must not be laundered into a failure by the wrapper."""
    assert g.main(["--help"]) == g.EXIT_PASS


def test_preflight_drift_is_the_image_fence_code(monkeypatch, tmp_path):
    """The I-1 image/config preflight refused: the container is wrong, no stage ever ran."""
    from leviathan.common import image_stamp
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {
        "ok": False, "reason": "image_predates_config", "lines": ["IMAGE IS STALE"],
        "red_tables": [(t, "stale") for t in tables], "image": image_stamp.image_facts()})
    rc = g.main(["--tables", "silver_wasde", "--json", str(tmp_path / "b.json")])
    assert rc == g.EXIT_PREFLIGHT
    assert rc != g.EXIT_REFUSAL


def test_unloadable_baked_registry_is_the_same_image_fence_code(monkeypatch, tmp_path):
    """The other half of the I-1 discrimination: a malformed yaml BAKED INTO THIS IMAGE. Same class as
    the preflight (the image is wrong), so the same code -- an operator gets one number to look up."""
    from leviathan.silver.registry import RegistryError

    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

    def boom(tables, **k):
        raise RegistryError("silver_cot.yaml: schema: expected type ['string'], got int")

    monkeypatch.setattr(g, "_build_live_context", boom)
    rc = g.main(["--tables", "silver_cot", "--json", str(tmp_path / "b.json")])
    assert rc == g.EXIT_PREFLIGHT


def test_baseline_fetch_error_is_the_one_retryable_code(monkeypatch):
    """72 is the ONLY code the jobdef retries. It has to mean a transient S3 GET and nothing else."""
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

    def boom(tables, **k):
        raise g.BaselineFetchError("baseline census fetch failed for s3://b/k: stubbed")

    monkeypatch.setattr(g, "_build_live_context", boom)
    assert g.main(["--tables", "silver_wasde"]) == g.EXIT_BASELINE_FETCH


def test_an_unhandled_crash_is_70_and_prints_its_traceback(monkeypatch, capsys):
    """THE CLASS THAT MOTIVATED THE SPLIT. `ModuleNotFoundError: psycopg` in the gate image used to exit
    1 through the interpreter -- indistinguishable from a refusal, and under the retry matrix it would be
    scored as a decision. It is now 70, and the traceback still reaches stdout because on the scheduled
    path the container log is the only durable record."""
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

    def boom(tables, **k):
        raise ModuleNotFoundError("No module named 'psycopg'")

    monkeypatch.setattr(g, "_build_live_context", boom)
    rc = g.main(["--tables", "silver_wasde"])
    out = capsys.readouterr()
    assert rc == g.EXIT_INTERNAL
    assert rc != g.EXIT_REFUSAL
    text = out.out + out.err
    assert "Traceback" in text and "psycopg" in text
    assert "INTERNAL ERROR" in out.out and "NO VERDICT" in out.out
    assert out.out.isascii()


def test_keyboard_interrupt_is_not_swallowed(monkeypatch):
    """The wrapper catches Exception, never BaseException. A killed container must not report a code."""
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

    def boom(tables, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(g, "_build_live_context", boom)
    with pytest.raises(KeyboardInterrupt):
        g.main(["--tables", "silver_wasde"])


def _bundle(verdict: str) -> dict:
    return {"run_id": "r1", "verdict": verdict, "results": [],
            "banner": {"tables": 1, "branch_a": 1, "branch_b": 0, "unknown": 0,
                       "red_tables": 0 if verdict == "PASS" else 1, "global_drift": 0,
                       "warn_tables": 0}}


@pytest.mark.parametrize("verdict,want", [("PASS", 0), ("FAIL", 1)])
def test_a_real_verdict_is_the_only_thing_that_produces_0_or_1(monkeypatch, tmp_path, verdict, want):
    """Exit 1 now means exactly one thing: the gate RAN, evaluated stages and REFUSED."""
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})
    monkeypatch.setattr(g, "_build_live_context", lambda tables, **k: object())
    monkeypatch.setattr(g, "run_gate", lambda tables, ctx: _bundle(verdict))
    rc = g.main(["--tables", "silver_wasde", "--json", str(tmp_path / f"{verdict}.json")])
    assert rc == want
    assert (rc == g.EXIT_PASS) is (verdict == "PASS")


# =========================================================================================================
# 3. CROSS-ARTIFACT: THE JOBDEF RETRY MATRIX (infra/terraform/modules/batch/silver_gate.tf)
# =========================================================================================================
def _gate_retry_block() -> str:
    return _block(_GATE_TF.read_text(encoding="utf-8"), "retry_strategy {")


def test_the_gate_matrix_fits_the_five_object_api_cap():
    """D-PR-37: `evaluateOnExit` accepts a MAXIMUM OF 5 objects and RegisterJobDefinition rejects more.
    The gate needs three; the assertion is the cap, so a fourth and fifth are allowed and a sixth fails
    here instead of at register time."""
    rules = _gate_retry_block().count("evaluate_on_exit {")
    assert rules == 3, "the gate matrix is {72 retry}, {ResourceInit* retry}, {'*' exit}"
    assert rules <= 5, "RegisterJobDefinition REJECTS a 6-object evaluateOnExit outright"


def test_only_the_baseline_fetch_code_is_retried_by_the_jobdef():
    """The safety property in one assertion: the sole `on_exit_code` in the whole matrix is 72, and its
    action is RETRY. A refusal, a usage error, a crash and an image fault all fall through to the
    terminal catch-all and EXIT."""
    block = _gate_retry_block()
    codes = re.findall(r'on_exit_code\s*=\s*"(\d+)"', block)
    assert codes == [str(g.EXIT_BASELINE_FETCH)], f"expected only {g.EXIT_BASELINE_FETCH}, got {codes}"

    # ...and the rule that names it is the RETRY one, not the exit one.
    rules = [_span(block, "evaluate_on_exit {", start=m.start())
             for m in re.finditer(r"evaluate_on_exit \{", block)]
    retrying = [r for r in rules if re.search(r'action\s*=\s*"RETRY"', r, re.I)]
    assert len(retrying) == 2, "exactly two rules may retry: exit 72 and ResourceInitializationError*"
    assert any(f'"{g.EXIT_BASELINE_FETCH}"' in r for r in retrying)
    assert any("ResourceInitializationError*" in r for r in retrying)

    for forbidden in (g.EXIT_REFUSAL, g.EXIT_USAGE, g.EXIT_INTERNAL, g.EXIT_PREFLIGHT):
        assert f'"{forbidden}"' not in block, (
            f"exit {forbidden} must never appear in the gate's retry matrix -- it is a non-retryable "
            f"outcome and naming it there is one edit away from retrying it")


def test_the_terminal_catch_all_is_present_and_exits():
    """NON-NEGOTIABLE. An `evaluateOnExit` no-match defaults to RETRY, so dropping this rule inverts the
    whole matrix and arms a retry on verdict FAIL."""
    block = _gate_retry_block()
    rules = [_span(block, "evaluate_on_exit {", start=m.start())
             for m in re.finditer(r"evaluate_on_exit \{", block)]
    catch_all = [r for r in rules if re.search(r'on_reason\s*=\s*"\*"', r)]
    assert len(catch_all) == 1, "the terminal catch-all rule is GONE (no-match defaults to RETRY)"
    assert re.search(r'action\s*=\s*"EXIT"', catch_all[0], re.IGNORECASE)
    assert rules[-1] is catch_all[0], "the catch-all must be LAST -- evaluateOnExit is first-match-wins"


def test_the_gate_jobdef_carries_a_per_attempt_timeout_and_two_attempts():
    """D-PR-11 (live rev 14 had none) and D-PR-8's `attempts: 2` -- one retry, for one class."""
    text = _GATE_TF.read_text(encoding="utf-8")
    assert re.search(r"attempts\s*=\s*2", _gate_retry_block())
    assert re.search(r"attempt_duration_seconds\s*=\s*3600", _block(text, "timeout {"))


def test_the_gate_jobdef_still_declares_both_secrets():
    """Terraform sends exactly what is declared. Dropping `secrets` registers a revision with no
    EVIDENCE_PG_DSN, and every Branch-A stage degrades to the offline/skip posture on the next fire --
    a gate that stops proving what it exists to prove, with no error anywhere."""
    text = _GATE_TF.read_text(encoding="utf-8")
    assert "EVIDENCE_PG_DSN" in text and "ANTHROPIC_API_KEY" in text
    # resolved BY NAME: the repo is public, so no suffixed secret ARN may be committed here.
    assert not re.search(r"secret:[A-Za-z0-9/_-]+-[A-Za-z0-9]{6}\b", text)


# =========================================================================================================
# 4. CROSS-ARTIFACT: THE STATE MACHINE (infra/terraform/modules/step_functions/main.tf)
# =========================================================================================================
def _sfn_text() -> str:
    return _SFN_TF.read_text(encoding="utf-8")


def test_the_classifier_reads_the_same_numbers_the_gate_writes():
    """THE DRIFT FENCE. The state machine cannot import Python, so it carries the exit codes as literals
    inside Cause patterns. This test is the only thing that keeps the two in step: renumber a constant in
    silver_rebuild_gate.py and the classifier starts routing the wrong email."""
    text = _sfn_text()

    refusal = re.search(r"gate_cause_refusal_patterns\s*=\s*\[(.*?)\]", text, re.S).group(1)
    assert f'ExitCode\\":{g.EXIT_REFUSAL},' in refusal
    for code in (g.EXIT_USAGE, g.EXIT_INTERNAL, g.EXIT_PREFLIGHT, g.EXIT_BASELINE_FETCH):
        assert f'ExitCode\\":{code},' not in refusal, "a non-verdict code must never route to FailNotify"

    listed = re.search(r"for c in \[([0-9,\s]+)\]", text).group(1)
    assert {int(x) for x in listed.split(",") if x.strip()} == {
        g.EXIT_USAGE, g.EXIT_INTERNAL, g.EXIT_PREFLIGHT, g.EXIT_BASELINE_FETCH}


def test_the_classifier_defaults_to_todays_behaviour():
    """A Choice state cannot carry a Catch, so an unrecognised Cause must land somewhere by design. It
    lands on FailNotify -- exactly what happens today -- so the classifier can only improve attribution,
    never lose a notification."""
    block = _block(_sfn_text(), "ClassifyGateFailure = {")
    assert re.search(r'Default\s*=\s*"FailNotify"', block)
    # every comparison is guarded, because an unguarded compare against a missing path is a
    # States.Runtime failure that no Catch can reach.
    assert block.count("IsPresent = true") == block.count("Or = [")


def test_the_gate_catch_order_puts_infra_ahead_of_the_states_all_arm():
    """`States.ALL` matches everything, so an arm placed after it is dead code."""
    block = _block(_sfn_text(), "Gate = {")
    catch = _span(block, "Catch = [", opener="[", closer="]")
    i_infra = catch.index("InfraFailNotify")
    i_classify = catch.index("ClassifyGateFailure")
    i_all = catch.index("States.ALL")
    assert i_infra < i_all and i_classify < i_all
    assert re.search(r'Next\s*=\s*"FailNotify"', catch), "the States.ALL arm still ends at FailNotify"


def test_the_gate_is_still_never_retried_into_a_green():
    """The Catch work rests on this: [Gate] retries ONLY transient Batch service faults. A red gate that
    is retried is a gate that can be argued out of its verdict."""
    block = _block(_sfn_text(), "Gate = {")
    retry = _span(block, "Retry = [", opener="[", closer="]")
    assert "States.TaskFailed" not in retry


def test_the_two_notifiers_say_different_things_and_both_end_failed():
    """One cause, one email -- but the RIGHT email. The infra text must not claim a verdict, and both
    paths must still drive the execution to FAILED (the ExecutionsFailed metric is D-PR-12's subject)."""
    text = _sfn_text()
    infra = _block(text, "InfraFailNotify = {")
    assert "NO GATE VERDICT" in infra and "NOT a refusal" in infra
    assert "canonical was never touched" in infra
    assert 'Next       = "PipelineInfraFailed"' in infra

    assert 'Error = "SilverPipelineInfraFailed"' in _block(text, "PipelineInfraFailed = {")
    # and the refusal path is untouched -- same Subject, same message, same Fail state.
    fail = _block(text, "FailNotify = {")
    assert "failed the silver_rebuild_gate" in fail and "Canonical left untouched (INV-6)" in fail
