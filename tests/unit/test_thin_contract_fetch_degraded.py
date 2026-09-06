"""LANE B -- the thin-contract Fetch Map tolerates a BLOCKED SOURCE, and only that.

THE INCIDENT THESE PINS EXIST FOR (measured, not hypothetical). On 2026-09-01, 09-03 and
09-04 the `futures_eod_free` schedule (`cron(30 22 ? * MON-FRI *)`, 5 fetch legs) failed at
fetch leg index 2 of 5: `jobs/ingest/fetch_cepea_daily.py` took HTTP 403 (Cloudflare) on both
indicators with the pinned CEPEA_USER_AGENT, reported `nothing_fetched` and exited 1. The
Fetch Map had NO Catch and `MaxConcurrency = 1`, so legs 3-4 never ran, and neither did any
of the 5 silver legs, the gate, the 5 promote legs or reconcile. ONE blocked venue staled
FIVE futures boards -- czce, jse, cepea, miax, euronext -- on 3 of 4 fires, including the
Zhengzhou rapeseed boards the live cross-currency lane reads. Source-side blocks are PARKED
by house law (no UA rotation, no bot evasion), so the DAG has to survive them.

THE THREE BOUNDS THIS FILE PINS, because the tolerance is worth nothing without them.

  1. BOUNDED (finding M1). A degraded fetch continues to Bronze ONLY when at least one leg
     SUCCEEDED. Measured over infra/terraform/envs/dev/dag_schedules.auto.tfvars.json, the
     fetch-leg histogram across the 25 enabled schedules is {0: 1, 1: 18, 2: 4, 3: 1, 5: 1}
     -- so for 18 of 25 schedules "one leg failed" IS "the whole acquisition phase failed",
     and those runs take the failure path with the same terminal status, the same untouched
     canonical and the same never-entered Bronze/Silver/Gate/Promote as today. Only the 6
     multi-leg families can ever run degraded.

  2. DISCRIMINATED (finding M2, design decision 2). A leg that never RAN is not a blocked
     source. The Batch service faults and the .sync timeout are split out by ERROR NAME; the
     remaining States.TaskFailed is classified on its Cause with the D-PR-10 idiom
     (CannotPullContainer / ResourceInitializationError / OutOfMemory arrive in StatusReason,
     never under their own error name). Only a Cause carrying an ExitCode -- the job ran and
     exited non-zero -- is tolerated; everything unrecognised DEFAULTS to infra.

  3. FETCH ONLY. Bronze, Silver and Promote render BYTE-IDENTICALLY to HEAD (1229 / 1227 /
     1233 bytes), because a silver leg writes the SHADOW table the gate judges and a promote
     leg IS the canonical write, after which Reconcile rolls the family's rolling baseline
     FORWARD over it. A stale baseline is recoverable; a poisoned one is not (INV-6).

WHAT THIS FILE DOES NOT CLAIM. It does not claim "zero silences created". The change adds
THREE unprotected payload-template sites (ScanFetchResults at top level, and the two record
Pass states in the Fetch iterator) and a Pass state cannot carry a Catch. It also does not
claim that a Catch reaches a runtime path/intrinsic fault -- it does not -- nor that
UpdateStateMachine validates the runtime semantics this lane depends on. It validates ASL
SYNTAX. The throwaway probe execution is the gate; see the acceptance block mirrored into
`infra/terraform/modules/step_functions/main.tf` above the state-machine resource.

WHY BOTH A TEXT LINT AND A RENDER PIN. `local.definition` is built out of HCL
comprehensions, `merge()` and `concat()`, and no rendered copy of the ASL document is
committed anywhere in the repo (the only other test that reads this file,
tests/unit/test_gate_exit_vocabulary.py, lints HCL TEXT through a brace matcher). The text
half catches an edit that reads wrong; the render half -- via
scripts/ops/render_sfn_definition.py, terraform-only, provider-free, no network and no AWS
credentials -- is the only thing that can see what the comprehensions actually PRODUCE.

BLAST RADIUS, because it sizes these pins: ONE state machine serves 25 of 25 enabled
schedules (21 distinct families). There is no per-family canary.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SFN_TF = _REPO / "infra" / "terraform" / "modules" / "step_functions" / "main.tf"
_SCHEDULES = _REPO / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"
_DAG_DESCRIPTORS = _REPO / "configs" / "silver" / "dags"
_RENDERER = _REPO / "scripts" / "ops" / "render_sfn_definition.py"

# AWS caps that bound the change. Both are hard service limits, not preferences.
_SNS_SUBJECT_CAP = 100
_DEFINITION_SIZE_CAP = 1048576

# A task whose command derives a layer rather than acquiring bytes. Frozen because the
# tolerance boundary is a DESCRIPTOR LABEL (`phase == "Fetch"`), not a property of the task.
_DERIVATION_COMMAND = re.compile(r"_to_bronze|_to_silver|bronze_to_|silver_to_|raw_to_")

# THE ONE ACCEPTED WIDENING, dated 2026-09-04 (finding N1). weather_daily's fetch phase
# contains a BRONZE WRITER: jobs/batch/chirps_to_bronze_task.py, whose own docstring is
# "CHIRPS COG -> bronze" and which imports leviathan.storage.paths.bronze_weather_key. It is
# therefore best-effort today. The real fix is a descriptor move (phases[0] -> phases[1])
# plus a tfvars regeneration, sequenced AFTER the pre-existing psd_monthly descriptor drift
# that the same regeneration would sweep up.
_ACCEPTED_FETCH_DERIVATION = [("weather_daily", "chirps_to_bronze",
                               "jobs/batch/chirps_to_bronze_task.py")]


# ---------------------------------------------------------------------------------------
# helpers -- the tests/unit/test_gate_exit_vocabulary.py idiom (the repo has no HCL parser)
# ---------------------------------------------------------------------------------------
def _span(text: str, header: str, opener: str = "{", closer: str = "}", start: int = 0) -> str:
    """Return the block `header` opens, matching `opener`/`closer` from the header onward.

    Works for `x = { ... }` and `x = [ ... ]` alike; a brace matcher handed a list header
    silently returns the FIRST element instead of the list."""
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
    raise AssertionError("unbalanced %s%s after %r" % (opener, closer, header))


def _block(text: str, header: str) -> str:
    """`{ ... }` wrapper anchored at a line start, so a header that is a SUFFIX of another
    state's name (FailNotify vs InfraFailNotify) cannot match the wrong one."""
    m = re.search(r"^\s*" + re.escape(header), text, re.M)
    assert m, "%r not found at a line start" % header
    return _span(text, header, start=m.start())


def _sfn_text() -> str:
    return _SFN_TF.read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Strip `#` comments, keeping every line (so brace matching and line anchors survive).

    This file is majority commentary by line count and the comments QUOTE the constructs
    they explain -- `phase == "Fetch"`, `merge(concat(...)...)`, and (since the M3 fix) the
    string `$$.Map.Item.Index` itself, in the paragraph explaining that it is GONE. A
    counting lint over the raw text would measure the prose, not the code. Quote state is
    tracked so a `#` inside a string literal is never treated as a comment."""
    out = []
    for line in text.splitlines():
        buf: list[str] = []
        in_str = esc = False
        for ch in line:
            if in_str:
                buf.append(ch)
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == "#":
                break
            else:
                buf.append(ch)
                if ch == '"':
                    in_str = True
        out.append("".join(buf).rstrip())
    return "\n".join(out)


def _families() -> list[str]:
    """Every `$.family` the machine can actually see, read from the committed schedules.

    NOT the tfvars map keys: the `futures_eod_free` schedule runs family `futures_eod`, so
    keying the SNS-subject pin on the map key would measure the wrong string."""
    sched = json.loads(_SCHEDULES.read_text(encoding="utf-8"))["dag_schedules"]
    return sorted({json.loads(json.loads(v["input_json"])["Input"])["family"]
                   for v in sched.values()})


def _fetch_leg_histogram() -> dict[int, int]:
    """{legs: schedules}, read from the committed tfvars -- the measurement M1 turns on."""
    sched = json.loads(_SCHEDULES.read_text(encoding="utf-8"))["dag_schedules"]
    hist: dict[int, int] = {}
    for v in sched.values():
        payload = json.loads(json.loads(v["input_json"])["Input"])
        n = len(payload["phases"]["fetch"]["tasks"])
        hist[n] = hist.get(n, 0) + 1
    return hist


# =======================================================================================
# 1. THE TEXT LINT -- only the Fetch phase is tolerant
# =======================================================================================
def test_only_the_fetch_phase_tolerates_a_failed_leg():
    """Three `phase == "Fetch" ?` guards, one per fetch-only fragment, and no fourth.

    The processor is ONE comprehension over ["Fetch", "Bronze", "Silver", "Promote"], so an
    unguarded fragment silently makes ALL FOUR phases best-effort -- which would let a dead
    silver or promote leg reach canonical. Measured on the rendered definition: Bronze,
    Silver and Promote are byte-identical to HEAD (1229 / 1227 / 1233 bytes each)."""
    code = _code_only(_sfn_text())
    guards = re.findall(r'phase == "Fetch" \? local\.(\w+) : \[\]', code)
    assert guards == [
        "fetch_only_batch_overrides",
        "fetch_only_glue_overrides",
        "fetch_only_extra_states",
    ], guards
    assert code.count('phase == "Fetch"') == 3, "a fourth Fetch guard appeared"
    # the three Fetch-only iterator states are named ONLY by the fetch-only locals
    assert code.count("ClassifyFailureFetch") == 2, "Catch Next + the extra-states key"
    assert code.count("RecordSourceFailureFetch") == 2, "classifier Next + the key"
    assert code.count("RecordInfraFailureFetch") == 5, (
        "batch Catch arm 1, glue Catch, classifier arm 1, classifier Default, the key")


def test_the_fetch_only_fragments_are_lists_not_objects():
    """A terraform typing law, not style. `phase == "Fetch" ? { Catch = ... } : {}` is
    REJECTED at validate time ("Inconsistent conditional result types ... includes object
    attribute Catch, which is absent in the false value"), because the conditional operator
    requires both result expressions to unify. Every fragment is therefore a ONE-ELEMENT
    LIST consumed through `merge(concat(...)...)` -- the same `cond ? [x] : []` idiom this
    file already uses for the optional PassThinContractRoles statement. Invisible to
    inspection, fatal at apply; this pin keeps a future edit from re-introducing it."""
    code = _code_only(_sfn_text())
    for name in ("fetch_only_batch_overrides", "fetch_only_glue_overrides",
                 "fetch_only_extra_states"):
        assert re.search(r"^  %s = \[\{" % name, code, re.M), name
    assert code.count("merge(concat([{") == 3, "the three merge(concat(...)) sites"
    assert code.count(")...)") == 3, "each merge(concat(...)) must close with the ... expansion"


def test_bronze_silver_promote_carry_no_catch_in_the_processor():
    """The fail-fast half of the lane, asserted where it is written. Inside
    `task_item_processors` the ONLY Catch that may appear is the one reached through a
    `phase == "Fetch"` guard, i.e. none at all in the shared body."""
    processors = _block(_code_only(_sfn_text()), "task_item_processors = {")
    assert "Catch" not in processors, "a Catch entered the shared per-phase processor body"
    assert "ResultSelector" not in processors


def test_the_narrowed_retry_lists_are_untouched():
    """D-PR-9 / D-PR-40 / D-PR-41 no-regression. A Catch is NOT a Retry: the jobdef
    evaluateOnExit matrix runs inside Batch first (exit 1 -> EXIT, one attempt), the .sync
    task fails, the narrowed SFN Retry does not match States.TaskFailed, and only then does
    the new Catch fire. Attempts per blocked fetch leg stay at 1 -- D-PR-41's ordering
    (narrow the SFN retry BEFORE arming jobdef attempts, never 3 x 3 = 9) is untouched."""
    text = _code_only(_sfn_text())
    batch_list = ('ErrorEquals     = ["States.Timeout", "Batch.ServerException", '
                  '"Batch.TooManyRequestsException"]')
    glue_list = 'ErrorEquals     = ["States.Timeout", "Glue.ConcurrentRunsExceededException"]'
    processors = _block(text, "task_item_processors = {")
    assert processors.count(batch_list) == 1, "the Batch narrowed list moved or multiplied"
    assert processors.count(glue_list) == 1, "D-PR-40's Glue transient moved or multiplied"

    # States.TaskFailed appears in the file (the Gate Catch arm) but must be in NO Retry.
    for m in re.finditer(r"Retry = \[", text):
        assert "States.TaskFailed" not in _span(text, "Retry = [", "[", "]", start=m.start()), (
            "States.TaskFailed re-entered a Retry list")


def test_promote_is_entered_only_from_the_gate():
    """INV-6, asserted on the text: canonical is reachable through the gate verdict alone.
    `Next = "Promote"` occurs exactly once in the whole module, inside the `Gate = {` block
    -- so no degraded path, and no new state, can route around the verdict."""
    text = _code_only(_sfn_text())
    hits = re.findall(r'Next\s+= "Promote"', text)
    assert len(hits) == 1, hits
    assert re.search(r'Next\s+= "Promote"', _block(text, "Gate = {"))


# =======================================================================================
# 2. FINDING M3 -- the Map context object is gone from the CODE
# =======================================================================================
def test_no_map_item_context_object_in_any_payload_template():
    """M3. An earlier draft put `"index.$" = "$$.Map.Item.Index"` in the OK-leg
    ResultSelector and in the failure record. Nothing read it (`$.fetchResults` is
    referenced nowhere in the repo outside this module and its test; the degraded Choice
    matches on `status`), and whether the Map context object resolves inside an INLINE
    ItemProcessor payload template is NOT settleable offline -- so it was pure first-fire
    risk on EVERY GREEN LEG OF ALL 25 FAMILIES. `$$.Map.Item.Value` in the ItemSelector is
    the one legitimate use and is unchanged: it is how a task reaches item scope at all."""
    code = _code_only(_sfn_text())
    assert "$$.Map.Item.Index" not in code
    assert code.count("$$.Map.") == 1, "the ONLY Map context path may be the ItemSelector"
    assert '"task.$"   = "$$.Map.Item.Value"' in code
    selector = _block(code, "fetch_ok_result_selector = {")
    assert selector.count("$") == 0, (
        "the green-leg ResultSelector must dereference NO path: %r" % selector)
    assert '"status" = "ok"' in selector


# =======================================================================================
# 3. FINDING M2 / decision 2 -- infra is discriminated, never swallowed
# =======================================================================================
def test_the_batch_fetch_catch_splits_infra_out_by_error_name_first():
    """Only the SubmitJob API faults and a .sync timeout arrive under their OWN error name;
    a job that STARTS and dies arrives as States.TaskFailed, the same name a source block
    uses. So arm 1 is a name test and arm 2 hands the rest to a Cause classifier -- the
    D-PR-10 structure, applied to producers. The four names are the same four the Gate's
    infra arm uses, so the two cannot disagree about what "never ran" means."""
    frag = _block(_code_only(_sfn_text()), "fetch_only_batch_overrides = [{")
    catch = _span(frag, "Catch = [", opener="[", closer="]")
    assert catch.count("ErrorEquals") == 2, "exactly two arms"
    assert "ErrorEquals = local.fetch_infra_error_names_batch" in catch
    assert 'Next       = "RecordInfraFailureFetch"' in catch
    assert 'ErrorEquals = ["States.ALL"]' in catch
    assert 'Next        = "ClassifyFailureFetch"' in catch
    assert catch.count('"$.error"') == 2, "BOTH arms must MERGE, not replace, the item input"
    names = _block(_code_only(_sfn_text()), "fetch_infra_error_names_batch = [")
    for n in ("Batch.ServerException", "Batch.TooManyRequestsException",
              "States.Timeout", "Batch.AWSBatchException"):
        assert n in names, n
    gate_infra = _span(_block(_code_only(_sfn_text()), "Gate = {"), "Catch = [",
                       opener="[", closer="]")
    for n in ("Batch.ServerException", "Batch.TooManyRequestsException",
              "States.Timeout", "Batch.AWSBatchException"):
        assert n in gate_infra, "the Gate infra arm and the fetch infra names must agree"


def test_the_cause_classifier_defaults_to_not_tolerated():
    """THE SAFETY PROPERTY OF THE DISCRIMINATOR. Tolerance is granted only on POSITIVE
    evidence that the job ran to an exit (an "ExitCode" in the Cause -- the measured shape
    from execution fred-refire-cotfence-20260804T071403Z). A container that never became the
    job announces itself in StatusReason, and those three patterns are tested FIRST because
    with jobdef attempts > 1 a Cause can carry both a CannotPull attempt and a later exit
    code, and infra is the not-tolerated side. Anything else -- an unknown Cause, no Cause at
    all -- takes the Default and is NOT tolerated, i.e. keeps today's behaviour."""
    block = _block(_code_only(_sfn_text()), "fetch_failure_classifier = {")
    assert 'Default = "RecordInfraFailureFetch"' in block, "the unknown case must NOT continue"
    order = re.findall(r'Next = "(Record\w+)"', block)
    assert order == ["RecordInfraFailureFetch", "RecordSourceFailureFetch"], order
    assert "local.container_never_started_patterns" in block
    assert 'StringMatches = "*\\"ExitCode\\":*"' in block
    # every comparison guarded -- an unguarded compare on a missing path is a runtime fault
    assert block.count("IsPresent = true") == 2
    # the pattern list is SHARED with the gate classifier so the two cannot drift
    code = _code_only(_sfn_text())
    assert code.count("local.container_never_started_patterns") == 2
    assert code.count('"*CannotPullContainer*"') == 1, "one definition, two readers"


def test_a_glue_fetch_leg_is_recorded_infra_not_tolerated():
    """34 of 34 fetch legs across the 25 enabled schedules are integration=batch, so no Glue
    fetch Cause shape has ever been observed here -- and a glue:startJobRun.sync Cause
    carries no "ExitCode", the discriminator the Batch classifier uses. Rather than tolerate
    a leg on a guessed Cause shape, the Glue arm records INFRA, which routes the run to the
    failure path exactly as today. The arm exists so a future Glue fetch leg fails LOUD and
    NAMED instead of throwing out of the Map."""
    frag = _block(_code_only(_sfn_text()), "fetch_only_glue_overrides = [{")
    catch = _span(frag, "Catch = [", opener="[", closer="]")
    assert catch.count("ErrorEquals") == 1
    assert 'Next        = "RecordInfraFailureFetch"' in catch
    assert "RecordSourceFailureFetch" not in frag, "a Glue leg must not reach the tolerated record"


def test_the_failed_leg_record_never_dereferences_an_optional_path():
    """`cause` carries `States.JsonToString($.error)` -- the WHOLE caught error object --
    and never `$.error.Cause`. `Cause` is OPTIONAL on some error names, and a payload
    template that dereferences an absent path raises a runtime fault that NO Catch can
    reach: a Cause-less fetch failure would FAIL the execution instead of degrading it.
    Same trap the D-PR-10 comment names for the gate classifier. The record NAMES the leg
    through `$.task` (jobdef + command), which is what the Catch ResultPath buys and what
    replaced the deleted context-object index."""
    record = _block(_sfn_text(), "fetch_failure_record = {")
    assert "States.JsonToString($.error)" in record
    assert "$.error.Cause" not in record
    assert '"task.$"  = "$.task"' in record
    assert '"status"  = "failed"' in record
    assert '"class"   = cls' in record, "the routing key the top-level Choice reads"
    assert 'for cls in ["source", "infra"]' in record, "one shape, two classes"
    assert "End = true" in record, "the item must END normally so the Map completes"


def test_the_catch_result_path_preserves_the_item_input():
    """ResultPath is load-bearing, not decoration. The DEFAULT (no ResultPath) REPLACES the
    state input with the error object, which would leave `$.task` unresolvable and the
    failure record unable to name the blocked leg. `$.error` MERGES instead."""
    text = _sfn_text()
    for local_name in ("fetch_only_batch_overrides", "fetch_only_glue_overrides"):
        frag = _block(text, "%s = [{" % local_name)
        assert re.search(r'ResultPath\s+= "\$\.error"', frag), local_name


# =======================================================================================
# 4. FINDING M1 -- the tolerance is BOUNDED
# =======================================================================================
def test_the_degraded_choice_is_bounded_guarded_and_defaults_to_todays_behaviour():
    """M1. Three arms, in order, and the ORDER is the safety property:
      1. any leg classed infra           -> FetchInfraFailNotify (FAILED)
      2. failed present AND ok ABSENT    -> FailNotify (FAILED)  <-- the bound
      3. failed present (so ok present)  -> DegradedNotify -> Bronze
    Arm 2 is the admission that "one blocked venue must not stale four others" has no force
    where there is no fourth. Default = "Bronze" is today's behaviour, so all-green families
    and the one zero-fetch-leg family (fx_macro_daily -> family `fred`: fetchResults == [],
    scan == "[]") match no arm and are unchanged."""
    block = _block(_sfn_text(), "AnyFetchLegFailed = {")
    assert block.count("IsPresent = true") == 3, "one guard per arm"
    assert block.count("StringMatches = ") == 4, "infra, failed, NOT ok, failed"
    assert re.search(r'Default = "Bronze"', block)
    assert "ArrayContains" not in block, (
        "States.ArrayContains tests EXACT element equality; no two failed legs are equal")
    order = re.findall(r'Next = "(\w+)"', block)
    assert order == ["FetchInfraFailNotify", "FailNotify", "DegradedNotify"], order
    assert 'StringMatches = "*\\"class\\":\\"infra\\"*"' in block
    assert block.count('StringMatches = "*\\"status\\":\\"failed\\"*"') == 2
    assert 'Not = { Variable = "$.fetchScan.all", StringMatches = "*\\"status\\":\\"ok\\"*" }' \
        in block, "the bound: nothing landed => the run does NOT continue"


def test_eighteen_of_the_twenty_five_schedules_cannot_run_degraded_at_all():
    """The measurement that gives arm 2 its scope, read from the committed tfvars rather
    than asserted. 18 of 25 enabled schedules carry EXACTLY ONE fetch leg, so for them a
    failed leg is the whole acquisition phase and arm 2 fires: same terminal status, same
    untouched canonical, same never-entered Bronze/Silver/Gate/Promote as today. Only the 6
    multi-leg schedules can reach DegradedNotify. If this histogram moves, the honest scope
    of the lane moved with it and the main.tf comment must be re-measured."""
    hist = _fetch_leg_histogram()
    assert hist == {0: 1, 1: 18, 2: 4, 3: 1, 5: 1}, hist
    assert sum(hist.values()) == 25
    assert sum(n for legs, n in hist.items() if legs > 1) == 6, "the degradable families"


# =======================================================================================
# 5. THE NOTIFIERS
# =======================================================================================
def test_the_degraded_notifier_uses_the_failnotify_topic_and_continues():
    """Same topic as FailNotify / InfraFailNotify (var.alerts_topic_arn ==
    module.alerting.topic_arn == leviathan-dev-alerts), so LANE B needs NO IAM change: the
    exec role's SnsPublishAlertTopics statement already grants sns:Publish on exactly that
    ARN. The Catch is deliberate and is not a swallow -- an uncaught SNS fault would FAIL an
    execution whose fetch phase merely degraded, handing one blocked venue exactly the
    five-stale-boards outcome this lane exists to prevent."""
    text = _code_only(_sfn_text())
    block = _block(text, "DegradedNotify = {")
    assert "TopicArn    = var.alerts_topic_arn" in block
    assert "TopicArn    = var.alerts_topic_arn" in _block(text, "FailNotify = {")
    catch = _span(block, "Catch = [", opener="[", closer="]")
    assert 'ErrorEquals = ["States.ALL"]' in catch
    assert re.search(r'Next\s+= "Bronze"', catch), "an SNS fault still continues to Bronze"
    assert re.search(r'ResultPath\s+= "\$\.degradedNotifyError"', catch)
    assert re.search(r'Next\s+= "Bronze"', block.replace(catch, "")), "the pipeline continues"


def test_only_the_degraded_notifier_retries_its_publish():
    """m4. FailNotify / InfraFailNotify / FetchInfraFailNotify are each followed by a Fail
    state, so a lost publish still shows as a FAILED execution. Losing the DEGRADED publish
    shows as a fully SUCCEEDED run with no signal at all, and that email is the lane's only
    new detector -- so this one state, and only this one, retries. D-PR-9's law is that a
    retry list names a CLASS: on a producer .sync task States.TaskFailed conflates a data
    verdict with an infra death, which is why it is banned there; on sns:publish there is
    exactly ONE class, "the publish did not go through", and States.ALL names it."""
    text = _code_only(_sfn_text())
    retry = _span(_block(text, "DegradedNotify = {"), "Retry = [", opener="[", closer="]")
    assert 'ErrorEquals     = ["States.ALL"]' in retry
    assert "MaxAttempts     = 2" in retry
    for other in ("FailNotify = {", "InfraFailNotify = {", "FetchInfraFailNotify = {"):
        assert "Retry" not in _block(text, other), other


def test_the_fetch_infra_notifier_reads_only_top_level_paths():
    """A SEPARATE notifier, not InfraFailNotify, for two measured reasons. (1) Wording:
    InfraFailNotify says "produced NO GATE VERDICT ... the gate job did not run to a
    decision", which is FALSE for a fetch-phase fault -- the gate was never reached.
    (2) Safety: InfraFailNotify reads `$.error.Error`, and on this path `$.error` was
    written by an ITEM-scoped Catch inside the Fetch iterator and does not exist at top
    level; dereferencing it here would be a runtime path fault no Catch reaches. This state
    reads only `$.family` and `$.fetchScan.all`, and ends on the EXISTING
    PipelineInfraFailed Fail state so the terminal error NAME is unchanged -- while that
    Fail state's CAUSE is widened to name this second inbound edge, because reusing the
    gate's cause verbatim puts the mislabel back into the one string DescribeExecution and
    the console show (NF-1)."""
    text = _code_only(_sfn_text())
    block = _block(text, "FetchInfraFailNotify = {")
    assert "$.error" not in block, "the item-scoped $.error is NOT reachable here"
    assert "TopicArn    = var.alerts_topic_arn" in block
    assert re.search(r'Next\s+= "PipelineInfraFailed"', block)
    assert '$.fetchScan.all' in block, "the email must NAME the legs"
    # the existing Fail state is reused, so SilverPipelineInfraFailed keeps its meaning
    fail_state = _block(text, "PipelineInfraFailed = {")
    assert 'Error = "SilverPipelineInfraFailed"' in fail_state
    # NF-1: ...but its CAUSE must name this path, not blame a gate that was never reached.
    assert "or a FETCH leg failed infra-side before the gate was reached" in fail_state, (
        "the terminal Cause an operator reads must name the fetch-phase infra edge")


def test_the_notifier_format_strings_are_well_formed():
    """`States.Format` is written inside SINGLE quotes in ASL, so ANY apostrophe in the text
    is a parse error at UpdateStateMachine time -- and the `{}` count must equal the argument
    count or the intrinsic fails at RUNTIME, mid-run, with no notification. Both are
    offline-checkable and neither is visible to `terraform validate`."""
    text = _code_only(_sfn_text())
    for state in ("DegradedNotify = {", "FetchInfraFailNotify = {"):
        block = _block(text, state)
        for label, nargs in (("Subject.$", 1), ("Message.$", 3)):
            line = next(ln for ln in block.splitlines() if label in ln)
            m = re.search(r"States\.Format\('(.*?)', (.+)\)\"\s*$", line)
            assert m, (state, label)
            text_part, args = m.group(1), m.group(2)
            assert "'" not in text_part, (
                "%s %s carries an apostrophe inside a single-quoted States.Format"
                % (state, label))
            assert text_part.count("{}") == nargs, (state, label)
            assert len(args.split(", ")) == nargs, (state, label, args)
            # `${local.name_prefix}` is a TERRAFORM interpolation, resolved before AWS sees
            # the string; strip it, then no unescaped brace may remain outside a {}.
            bare = text_part.replace("${local.name_prefix}", "leviathan-dev").replace("{}", "")
            assert "{" not in bare and "}" not in bare, (state, label)


def test_both_new_subjects_fit_the_sns_cap_for_every_family():
    """AWS caps an SNS Subject at 100 characters and rejects the publish above it -- which
    for DegradedNotify would take the Catch and lose the email the lane exists to send.
    Measured against the 21 distinct `$.family` values in the committed schedules: DEGRADED
    is 61 + 12 = 73 of 100, INFRA-in-FETCH is 56 + 12 = 68 of 100."""
    text = _sfn_text()
    fams = _families()
    assert len(fams) >= 20, "the schedule census shrank; re-measure before trusting this pin"
    longest = max(fams, key=len)
    for state in ("DegradedNotify = {", "FetchInfraFailNotify = {"):
        block = _block(text, state)
        line = next(ln for ln in block.splitlines() if "Subject.$" in ln)
        head = line.index("States.Format('") + len("States.Format('")
        literal = line[head:line.index("', $.family)")]
        literal = literal.replace("${local.name_prefix}", "leviathan-dev").replace("{}", "")
        assert len(literal) + len(longest) <= _SNS_SUBJECT_CAP, (state, literal, longest)


# =======================================================================================
# 6. FINDING M4 / m6 -- what the file CLAIMS must be true
# =======================================================================================
def test_the_fetch_map_catch_does_not_claim_to_reach_a_runtime_fault():
    """M4. The Fetch Map gains `States.ALL -> FailNotify`, closing the D-PR-44 FETCH
    QUARTER: `leviathan-dev-sfn-executions-failed` is metric-only (alarm_actions = [],
    D-PR-12 / D-ALARM-1) and FailNotify was reachable ONLY from Gate and Reconcile, so a
    Fetch Map that died produced ZERO notifications. But an earlier draft of that comment
    claimed the Catch also covers "a States.Runtime inside an iterator state" -- and this
    same file says three separate times that no Catch reaches that class. The comment now
    names only the CATCHABLE classes, so the module does not contradict itself.
    Bronze/Silver/Promote still carry no Map Catch, which is why
    `leviathan-dev-batch-job-failed-scheduled` STAYS ARMED."""
    text = _sfn_text()
    fetch = _block(text, "Fetch = {")
    catch = _span(fetch, "Catch = [", opener="[", closer="]")
    assert 'ErrorEquals = ["States.ALL"]' in catch
    assert 'Next        = "FailNotify"' in catch
    assert 'ResultPath  = "$.error"' in catch
    assert re.search(r'Next = "ScanFetchResults"', fetch)
    assert "States.Runtime" not in fetch, (
        "the Fetch Map comment must not claim a Catch reaches a runtime fault")
    assert "States.DataLimitExceeded is the measured one" in fetch
    for phase in ("Bronze = {", "Silver = {", "Promote = {"):
        assert "Catch" not in _block(text, phase), (
            "%s gained a Map Catch -- D-PR-44 is NOT discharged" % phase)


def test_the_module_never_claims_zero_silences_or_an_apply_time_semantic_gate():
    """M2 + M4, pinned as absences. `terraform validate` proves HCL types and
    UpdateStateMachine validates ASL SYNTAX -- error names, intrinsic arity, JSONPath
    syntax, Next-target existence. It does NOT prove that States.JsonToString accepts an
    array at that path, that a per-item Catch ends the item, or that an sns:publish reaches
    the topic. None of those fail closed at apply, and the module must say so rather than
    the reverse. The change also adds THREE unprotected payload-template sites (a Pass
    cannot carry a Catch), so "zero silences created" is not a claim this lane may make."""
    text = _sfn_text()
    assert "UpdateStateMachine validates ASL SYNTAX only" in text
    assert "THROWAWAY PROBE EXECUTION IS THE GATE" in text
    # the phrase may appear exactly once, in the sentence that DENIES it
    hits = [ln.strip() for ln in text.splitlines() if "zero silences created" in ln.lower()]
    assert len(hits) == 1, hits
    assert 'does NOT claim "zero silences created"' in hits[0], hits
    assert "UNPROTECTED" in text and "THREE of them" in text


def test_the_probe_acceptance_criteria_survive_a_clean_clone():
    """m6. The operator runbook lives at docs/private/LANE_B_FETCH_TOLERANCE_ROLLOUT.md and
    docs/private/ is gitignored (.gitignore:69) -- it does not survive a clean clone, and
    this is the ONE machine 25 of 25 schedules run on. The probe acceptance criteria are
    therefore mirrored into main.tf, which does survive, and this pin keeps them there."""
    text = _sfn_text()
    for marker in ("LANE B ACCEPTANCE, MIRRORED HERE ON PURPOSE",
                   "P1 two fetch legs", "P2 TWO fetch legs", "P3 ONE fetch leg",
                   "ROLL BACK"):
        assert marker in text, marker
    # NF-2. The mirrored copy is the one a clean-clone operator reads, so it must describe
    # the probes AS SHIPPED. Two slips were frozen here by the first version of this pin:
    # P2 was written as a single leg (it ships with two, and the green one is load-bearing
    # -- with one leg the probe cannot tell arm 1 from arm 2), and P3 was called "implied
    # by P2" (it is a separate probe with its own input, and the ONLY one that exercises
    # the M1 bound). Pin the corrected text, and pin the slips OUT.
    assert "P2 one fetch leg" not in text, "P2 ships with TWO legs, one green"
    assert "P3 (implied by P2)" not in text, "P3 is a separate probe, not implied"
    assert "DegradedNotify NEVER" in text, "the P2/P3 discriminator must be stated here"


# =======================================================================================
# 7. FINDING N1 -- the tolerance boundary is a DESCRIPTOR LABEL, and it is frozen
# =======================================================================================
def test_the_fetch_phase_carries_exactly_one_known_derivation_task():
    """N1. `phase == "Fetch"` keys on the name whoever wrote configs/silver/dags/*.json gave
    the phase, never on what the task does -- so the boundary is only as good as the
    descriptors, and NOTHING lints them. Measured today: exactly ONE fetch-phase task in the
    whole estate is a derivation step, weather_daily's `chirps_to_bronze`
    (jobs/batch/chirps_to_bronze_task.py, docstring "CHIRPS COG -> bronze", imports
    leviathan.storage.paths.bronze_weather_key). It runs BEST-EFFORT the day this lands.
    That is an ACCEPTED, DATED widening -- named in the shipped DEGRADED email rather than
    denied by it -- and the real fix is a descriptor move plus a tfvars regeneration,
    sequenced after the pre-existing psd_monthly drift. This pin FAILS the moment a SECOND
    fused fetch+derive task appears, which is the only thing that keeps the boundary honest
    as descriptors change."""
    found = []
    for path in sorted(_DAG_DESCRIPTORS.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for phase in doc.get("phases", []) or []:
            if str(phase.get("name", "")).lower() != "fetch":
                continue
            for task in phase.get("tasks", []) or []:
                head = (task.get("command") or [""])[0]
                if _DERIVATION_COMMAND.search(head) or _DERIVATION_COMMAND.search(
                        str(task.get("id", ""))):
                    found.append((path.stem, task.get("id"), head))
    assert found == _ACCEPTED_FETCH_DERIVATION, (
        "a fetch-phase task derives a layer and is NOT the accepted one: %s" % found)


def test_the_degraded_email_names_the_accepted_widening_instead_of_denying_it():
    """N1, on the shipped text. The alert must not tell an operator that "derivation and
    publication are not best-effort" while weather_daily's chirps bronze writer sits in a
    fetch phase. It names the exception, and it tells the operator what a REPEATED
    degradation means (m1: CEPEA has been blocked since 2026-09-01, so this condition is
    permanent until the source unblocks, not transient)."""
    msg = next(ln for ln in _block(_sfn_text(), "DegradedNotify = {").splitlines()
               if "Message.$" in ln)
    assert "chirps_to_bronze" in msg, "the one measured exception must be NAMED"
    assert "open a docket" in msg and "do not rotate a user agent" in msg
    assert "BLOCKED AT THE SOURCE" in msg and "exited non-zero" in msg, (
        "the email must say WHICH failure class it covers")


# =======================================================================================
# 8. THE RENDER PIN -- what the comprehensions actually PRODUCE
# =======================================================================================
def _load_renderer():
    spec = importlib.util.spec_from_file_location("render_sfn_definition", _RENDERER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["render_sfn_definition"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rendered():
    if shutil.which("terraform") is None:
        pytest.skip("terraform is not on PATH")
    return _load_renderer().render_definition()


def _naive_state_names(doc) -> list[str]:
    """An INDEPENDENT scan for every `{name: state}` map, used to prove the renderer's
    walker is not descending one level and passing vacuously (finding m3)."""
    names: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            states = node.get("States")
            if (isinstance(states, dict) and states
                    and all(isinstance(v, dict) and "Type" in v for v in states.values())):
                names.extend(states)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return names


def test_rendered_state_names_are_globally_unique(rendered):
    """AWS state names are GLOBAL and INLINE Map iterator states share that one namespace, so
    a duplicate is `DUPLICATE_STATE_NAME` at UpdateStateMachine time -- a failed apply for the
    ONE machine all 25 schedules run on. Measured: HEAD renders 24 names, this renders 31,
    0 duplicates in both. The three new iterator states are stamped for Fetch alone."""
    mod = _load_renderer()
    top, nested = mod.state_names(rendered)
    names = top + nested
    assert len(names) == len(set(names)), sorted({n for n in names if names.count(n) > 1})
    assert (len(top), len(nested)) == (16, 15), (len(top), len(nested))
    assert {"ScanFetchResults", "AnyFetchLegFailed", "DegradedNotify",
            "FetchInfraFailNotify"} <= set(top)
    assert {"ClassifyFailureFetch", "RecordSourceFailureFetch",
            "RecordInfraFailureFetch"} <= set(nested)


def test_the_render_walker_sees_every_state_in_the_document(rendered):
    """m3. The walker used to descend exactly ONE level into `ItemProcessor` -- correct for
    today's document and silently vacuous the day a Map is nested or a Parallel appears,
    which is the worst failure a pin can have. It now walks structurally, and this pin
    compares it against an INDEPENDENT naive scan so the two must agree."""
    mod = _load_renderer()
    top, nested = mod.state_names(rendered)
    assert sorted(top + nested) == sorted(_naive_state_names(rendered))
    assert len(mod.state_containers(rendered)) == 5, "top level + four phase iterators"


def test_rendered_retry_blocks_still_name_no_failure_class(rendered):
    """Eleven Retry blocks: the ten producer/gate/reconcile blocks byte-frozen from HEAD,
    plus DegradedNotify's (m4). `States.TaskFailed` is in none of them -- D-PR-9's law is
    about producer states, where that name conflates a data verdict with an infra death.
    A text lint can miss a Retry a comprehension synthesises; this reads the artifact."""
    mod = _load_renderer()
    blocks = mod.retry_blocks(rendered)
    assert len(blocks) == 11, sorted(blocks)
    batch = ["States.Timeout", "Batch.ServerException", "Batch.TooManyRequestsException"]
    glue = ["States.Timeout", "Glue.ConcurrentRunsExceededException"]
    gate = ["Batch.ServerException", "Batch.TooManyRequestsException", "States.Timeout"]
    for phase in ("Fetch", "Bronze", "Silver", "Promote"):
        assert blocks["BatchSync%s" % phase][0]["ErrorEquals"] == batch, phase
        assert blocks["GlueSync%s" % phase][0]["ErrorEquals"] == glue, phase
    assert blocks["Gate"][0]["ErrorEquals"] == gate
    assert blocks["Reconcile"][0]["ErrorEquals"] == gate
    assert blocks["DegradedNotify"] == [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5,
                                         "MaxAttempts": 2, "BackoffRate": 2.0}]
    assert "States.TaskFailed" not in json.dumps(blocks)
    for name in ("FailNotify", "InfraFailNotify", "FetchInfraFailNotify"):
        assert name not in blocks, "%s must not retry: it is followed by a Fail state" % name


def test_rendered_bronze_silver_promote_are_fail_fast(rendered):
    """The fail-fast invariant read off the ARTIFACT, not the source. No leg in Bronze,
    Silver or Promote carries a Catch or a ResultSelector, and none of those three Maps
    carries a Map-level Catch -- so a dead derivation or publication leg still stops the run
    before canonical."""
    for phase in ("Bronze", "Silver", "Promote"):
        state = rendered["States"][phase]
        assert "Catch" not in state, phase
        legs = state["ItemProcessor"]["States"]
        assert len(legs) == 3, (phase, sorted(legs))
        for leg in legs.values():
            assert "Catch" not in leg and "ResultSelector" not in leg, phase
    fetch_legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    assert len(fetch_legs) == 6, sorted(fetch_legs)
    assert fetch_legs["BatchSyncFetch"]["ResultSelector"] == {"status": "ok"}
    assert fetch_legs["BatchSyncFetch"]["Catch"][1]["Next"] == "ClassifyFailureFetch"
    assert fetch_legs["GlueSyncFetch"]["Catch"][0]["Next"] == "RecordInfraFailureFetch"


def test_rendered_promote_is_reachable_only_from_the_gate(rendered):
    """INV-6 on the artifact. Every transition into Promote, enumerated over the whole
    document -- Next fields, Choice arms and Catch arms alike."""
    entered_from = sorted(k for k, v in rendered["States"].items() if v.get("Next") == "Promote")
    assert entered_from == ["Gate"], entered_from
    for name, state in rendered["States"].items():
        if name == "Gate":
            continue
        assert "Promote" not in json.dumps(state.get("Choices", [])), name
        assert "Promote" not in json.dumps(state.get("Catch", [])), name


def test_rendered_definition_fits_the_aws_cap(rendered):
    """CreateStateMachine / UpdateStateMachine cap the definition at 1,048,576 bytes.
    Measured: HEAD 9,762 bytes (0.931%), this 14,859 bytes (1.417%), delta +5,097."""
    mod = _load_renderer()
    size = mod.definition_size_bytes(rendered)
    assert size < _DEFINITION_SIZE_CAP, size
    assert size < 20000, "the definition grew unexpectedly (%d bytes); re-measure" % size


def test_rendered_no_context_object_and_a_constant_green_leg(rendered):
    """M3 on the artifact: the whole rendered document contains no Map context path other
    than the ItemSelector's `$$.Map.Item.Value`, so nothing that runs on a GREEN leg of any
    of the 25 families depends on a construct this lane could not settle offline."""
    blob = json.dumps(rendered)
    assert "$$.Map.Item.Index" not in blob
    assert blob.count("$$.Map.") == 4, "one ItemSelector per phase Map, and nothing else"


def test_rendered_degraded_path_is_bounded_and_discriminated(rendered):
    """The whole M1 + decision-2 shape, read off the artifact. Three arms in order; the
    continuing arm is reachable only when an `ok` marker is present; the classifier and both
    records are stamped for Fetch alone; the infra notifier ends FAILED on the existing Fail
    state and never dereferences the item-scoped `$.error`."""
    states = rendered["States"]
    choices = states["AnyFetchLegFailed"]["Choices"]
    assert [c["Next"] for c in choices] == ["FetchInfraFailNotify", "FailNotify",
                                            "DegradedNotify"]
    assert states["AnyFetchLegFailed"]["Default"] == "Bronze"
    nots = [g for g in choices[1]["And"] if "Not" in g]
    assert len(nots) == 1 and nots[0]["Not"]["StringMatches"] == '*"status":"ok"*'
    assert all(any(g.get("IsPresent") is True for g in c["And"]) for c in choices)

    assert states["Fetch"]["Next"] == "ScanFetchResults"
    assert states["Fetch"]["Catch"][0]["Next"] == "FailNotify"
    assert states["ScanFetchResults"]["Parameters"] == {
        "all.$": "States.JsonToString($.fetchResults)"}

    fail_topic = states["FailNotify"]["Parameters"]["TopicArn"]
    assert states["DegradedNotify"]["Parameters"]["TopicArn"] == fail_topic
    assert states["FetchInfraFailNotify"]["Parameters"]["TopicArn"] == fail_topic
    assert states["DegradedNotify"]["Next"] == "Bronze"
    assert states["DegradedNotify"]["Catch"][0]["Next"] == "Bronze"
    assert states["FetchInfraFailNotify"]["Next"] == "PipelineInfraFailed"
    assert "$.error" not in json.dumps(states["FetchInfraFailNotify"]["Parameters"])

    legs = states["Fetch"]["ItemProcessor"]["States"]
    cls = legs["ClassifyFailureFetch"]
    assert cls["Default"] == "RecordInfraFailureFetch", "the unknown case is NOT tolerated"
    assert [c["Next"] for c in cls["Choices"]] == ["RecordInfraFailureFetch",
                                                   "RecordSourceFailureFetch"]
    assert [g["StringMatches"] for g in cls["Choices"][0]["And"][1]["Or"]] == [
        "*CannotPullContainer*", "*ResourceInitializationError*", "*OutOfMemory*"]
    assert cls["Choices"][1]["And"][1]["StringMatches"] == '*"ExitCode":*'
    assert legs["RecordSourceFailureFetch"]["Parameters"]["class"] == "source"
    assert legs["RecordInfraFailureFetch"]["Parameters"]["class"] == "infra"
    for rec in ("RecordSourceFailureFetch", "RecordInfraFailureFetch"):
        assert legs[rec]["End"] is True, rec
        assert legs[rec]["Parameters"]["cause.$"] == "States.JsonToString($.error)"


def test_rendered_gate_classifier_is_byte_identical_to_head(rendered):
    """Sharing `container_never_started_patterns` between the gate classifier and the new
    fetch classifier must not have moved the gate's rendered value by one byte -- the whole
    point of the share is that the two lists cannot drift, not that either one changed."""
    patterns = [g["StringMatches"]
                for g in rendered["States"]["ClassifyGateFailure"]["Choices"][1]["And"][1]["Or"]]
    assert patterns == [
        '*"ExitCode":64,*', '*"ExitCode":64}*',
        '*"ExitCode":70,*', '*"ExitCode":70}*',
        '*"ExitCode":71,*', '*"ExitCode":71}*',
        '*"ExitCode":72,*', '*"ExitCode":72}*',
        "*CannotPullContainer*", "*ResourceInitializationError*", "*OutOfMemory*",
    ], patterns
    assert rendered["States"]["ClassifyGateFailure"]["Default"] == "FailNotify"
