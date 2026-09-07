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
     remaining States.TaskFailed is classified by PARSING its Cause -- the DescribeJobs job
     detail -- and comparing NAMED fields, never substrings of the document. CannotPull and
     ResourceInitializationError arrive in StatusReason with no ExitCode at all; an OOM does
     NOT (corrected 2026-09-07: it arrives in the container reason, under the ordinary
     "Essential container in task exited", and shows itself in the exit code as 137). Only a
     Cause carrying an ExitCode BELOW the signal floor and non-zero -- the container ran and
     chose its own exit -- is tolerated; everything unrecognised DEFAULTS to infra.

  3. FETCH ONLY. Bronze, Silver and Promote render BYTE-IDENTICALLY to HEAD (1229 / 1227 /
     1233 bytes), because a silver leg writes the SHADOW table the gate judges and a promote
     leg IS the canonical write, after which Reconcile rolls the family's rolling baseline
     FORWARD over it. A stale baseline is recoverable; a poisoned one is not (INV-6).

WHAT THIS FILE DOES NOT CLAIM. It does not claim "zero silences created". The change adds
FIVE unprotected payload-template sites -- ScanFetchResults at top level, the two record Pass
states in the Fetch iterator, and (since the 2026-09-06 parse) ParseBatchCauseGate at top
level and ParseBatchCauseFetch in the iterator -- and a Pass state cannot carry a Catch. The
count was THREE until the parse landed and the comment did not follow it; it is measured on
the rendered document by test_the_unprotected_payload_template_sites_are_counted_correctly.
The two parse states are covered by a PRECONDITION instead (the error-NAME arm plus the `{*}`
shape guard), which for the non-JSON class is stronger than a Catch. It also does not
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
    # the five Fetch-only iterator states are named ONLY by the fetch-only locals
    assert code.count("ClassifyFailureFetch") == 2, "Catch Next + the extra-states key"
    assert code.count("ParseBatchCauseFetch") == 2, "the guard's Next + the extra-states key"
    assert code.count("ClassifyBatchCauseFetch") == 2, "the parse's Next + the extra-states key"
    assert code.count("RecordSourceFailureFetch") == 2, "classifier Next + the key"
    assert code.count("RecordInfraFailureFetch") == 6, (
        "batch Catch arm 1, glue Catch, the guard's Default, the parsed classifier's shared "
        "infra arms (ONE comprehension), the parsed classifier's Default, the key")


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
    """THE SAFETY PROPERTY OF THE DISCRIMINATOR, and it survived the 2026-09-06 rewrite. Both
    halves of the classification default to NOT TOLERATED: the error-name/shape guard sends
    everything that is not a States.TaskFailed carrying a JSON-object Cause straight to
    infra, and the reader over the parsed job detail defaults to infra as well. Tolerance is
    granted only on POSITIVE evidence that the container ran and chose a non-zero exit.

    WHAT CHANGED, AND WHY THIS PIN'S BODY MOVED. Until 2026-09-06 the discriminator was a
    substring test over the WHOLE Cause, and the Cause is the DescribeJobs job detail, which
    embeds the jobdef's own RetryStrategy -- naming CannotPullContainer* and
    ResourceInitializationError* on every jobdef in the estate. So the infra arm matched
    EVERY Batch failure and the source arm was unreachable code. Measured live: execution
    laneb-p1-20260906T234214Z, a plain `raise SystemExit(1)` fetch leg, classified INFRA and
    took the run to FAILED / SilverPipelineInfraFailed. The tolerance was granted to nothing.
    The fixture pins further down evaluate the RENDERED rules against that exact Cause."""
    code = _code_only(_sfn_text())
    guard = _block(code, "fetch_failure_classifier = {")
    assert 'Default = "RecordInfraFailureFetch"' in guard, "an unparseable cause must NOT continue"
    assert 'StringEquals = "States.TaskFailed"' in guard, "route by ERROR NAME before any parse"
    assert "local.batch_cause_is_parseable" in guard, "and by the JSON-object shape guard"
    assert 'Next = "ParseBatchCauseFetch"' in guard

    reader = _block(code, "fetch_parsed_cause_classifier = {")
    assert 'Default = "RecordInfraFailureFetch"' in reader, "the unknown case must NOT continue"
    assert "local.batch_cause_infra_guards" in reader
    assert "local.batch_cause_ran_to_an_exit_guards" in reader
    assert "NumericGreaterThan = 0" in reader, "tolerance needs a NON-ZERO exit code"
    order = re.findall(r'Next = "(Record\w+)"', reader)
    assert order == ["RecordInfraFailureFetch", "RecordSourceFailureFetch"], order

    # ONE PARSER, TWO READERS: the guard objects and the parse are defined once and read by
    # the fetch reader and the gate reader alike, so the two cannot drift.
    for shared, uses in (("batch_cause_parse_pass", 2), ("batch_cause_is_parseable", 2),
                         ("batch_cause_infra_guards", 2),
                         # the fetch source arm, the gate refusal arm, the gate no-verdict arm
                         ("batch_cause_ran_to_an_exit_guards", 3)):
        assert code.count("local.%s" % shared) == uses, shared
    assert code.count('"CannotPullContainer*"') == 1, "one roster, two readers"
    # and the substring roster that caused the defect is GONE from the module
    assert "container_never_started_patterns" not in code
    assert '"*CannotPullContainer*"' not in code, "a whole-Cause substring test came back"
    assert '"*\\"ExitCode\\":*"' not in code, "a whole-Cause substring test came back"


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
    exactly ONE class, "the publish did not go through", and States.ALL names it.

    THE ABSENCE IS MATCHED ON THE HCL ATTRIBUTE, not on the substring "Retry". It used to be
    the substring, and on 2026-09-07 that went red on prose: InfraFailNotify's message now
    explains that an unrecognised gate exit code used to be swallowed by a jobdef
    RetryStrategy. A notifier that has no `Retry = [` block has no retry, whatever its text
    says -- and the pattern is proven to fire on the one state that DOES retry, below, so the
    narrowing cannot be vacuous."""
    text = _code_only(_sfn_text())
    attribute = re.compile(r"^\s*Retry\s*=\s*\[", re.M)
    retry = _span(_block(text, "DegradedNotify = {"), "Retry = [", opener="[", closer="]")
    assert 'ErrorEquals     = ["States.ALL"]' in retry
    assert "MaxAttempts     = 2" in retry
    assert attribute.search(_block(text, "DegradedNotify = {")), "the pattern matches nothing"
    for other in ("FailNotify = {", "InfraFailNotify = {", "FetchInfraFailNotify = {"):
        assert not attribute.search(_block(text, other)), other


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
    offline-checkable and neither is visible to `terraform validate`.

    InfraFailNotify joined this loop on 2026-09-07, when its Message stopped being byte-
    identical to HEAD and grew an enumeration of the classes it gained. Same arity (1 Subject
    arg, 3 Message args), same single-quoted trap, and it is now the longest of the three."""
    text = _code_only(_sfn_text())
    for state in ("DegradedNotify = {", "FetchInfraFailNotify = {", "InfraFailNotify = {"):
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
    the reverse. The change also adds FIVE unprotected payload-template sites (a Pass
    cannot carry a Catch), so "zero silences created" is not a claim this lane may make."""
    text = _sfn_text()
    assert "UpdateStateMachine validates ASL SYNTAX only" in text
    assert "THROWAWAY PROBE EXECUTION IS THE GATE" in text
    # the phrase may appear exactly once, in the sentence that DENIES it
    hits = [ln.strip() for ln in text.splitlines() if "zero silences created" in ln.lower()]
    assert len(hits) == 1, hits
    assert 'does NOT claim "zero silences created"' in hits[0], hits
    assert "UNPROTECTED" in text and "FIVE of them" in text
    assert "THREE of them" not in text, (
        "the unprotected payload-template count went 3 -> 5 when the parse landed; the "
        "module comment must not still say three")


def test_the_unprotected_payload_template_sites_are_counted_correctly(rendered):
    """THE ARITHMETIC, MEASURED ON THE ARTIFACT rather than trusted from a comment.

    A Pass state cannot carry a Catch, so every Pass that carries a payload template is a
    place where a dereference of an absent path -- or, for the parse states, an intrinsic
    that raises -- fails the execution with no notification. HEAD has THREE such states. The
    2026-09-06 parse added TWO more and the module comment went on saying three; that stale
    count is what this pin exists to make impossible. Both new ones are the shared
    `batch_cause_parse_pass`, and ParseBatchCauseGate is TOP-LEVEL, not inside the iterator,
    so it is traversed on the gate path of all 25 families.

    The two parse states are the only two protected by a PRECONDITION instead of a Catch (the
    error-NAME arm plus the `{*}` shape guard, asserted separately in
    test_a_non_json_cause_never_reaches_the_parse), which for the non-JSON class is stronger
    than a Catch because that class never reaches the parse. That is why the count is
    reported as five WITH the distinction, not laundered into three."""
    sites = []
    for scope, states in (("", rendered["States"]),
                          ("Fetch/", rendered["States"]["Fetch"]["ItemProcessor"]["States"])):
        for name, state in states.items():
            if state.get("Type") == "Pass" and "Parameters" in state:
                sites.append(scope + name)
    assert sorted(sites) == [
        "Fetch/ParseBatchCauseFetch", "Fetch/RecordInfraFailureFetch",
        "Fetch/RecordSourceFailureFetch", "ParseBatchCauseGate", "ScanFetchResults",
    ], sorted(sites)
    assert len(sites) == 5

    # and none of the five carries a Catch, which is the reason the count matters at all
    for scope, states in (("", rendered["States"]),
                          ("Fetch/", rendered["States"]["Fetch"]["ItemProcessor"]["States"])):
        for name, state in states.items():
            if scope + name in sites:
                assert "Catch" not in state, scope + name

    # the module's own residual paragraph names all five, and names the two that are new
    text = _sfn_text()
    residual = text[text.index("# HONEST RESIDUAL, stated where it is created:"):]
    residual = residual[:residual.index("fetch_failure_record = {")]
    for needle in ("FIVE of them", "ScanFetchResults", "RecordSourceFailureFetch",
                   "RecordInfraFailureFetch", "ParseBatchCauseGate", "ParseBatchCauseFetch"):
        assert needle in residual, needle


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
    ONE machine all 25 schedules run on.

    RE-MEASURED 2026-09-07, because the prose had been carried over from an earlier draft and
    said "HEAD renders 24 names, this renders 31" while the assertion below already said
    (18, 17). Both renders, HEAD via `git show HEAD:...` through the same renderer: HEAD is 31
    names (top 16, nested 15) and this tree is 35 (top 18, nested 17), 0 duplicates in both.
    The change adds FOUR states, not three -- two at top level (ParseBatchCauseGate,
    ClassifyBatchCauseGate) and two in the Fetch iterator (ParseBatchCauseFetch,
    ClassifyBatchCauseFetch) -- and the iterator pair is stamped for Fetch alone."""
    mod = _load_renderer()
    top, nested = mod.state_names(rendered)
    names = top + nested
    assert len(names) == len(set(names)), sorted({n for n in names if names.count(n) > 1})
    assert (len(top), len(nested)) == (18, 17), (len(top), len(nested))
    assert {"ScanFetchResults", "AnyFetchLegFailed", "DegradedNotify",
            "FetchInfraFailNotify", "ParseBatchCauseGate", "ClassifyBatchCauseGate"} <= set(top)
    assert {"ClassifyFailureFetch", "ParseBatchCauseFetch", "ClassifyBatchCauseFetch",
            "RecordSourceFailureFetch", "RecordInfraFailureFetch"} <= set(nested)


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
    assert len(fetch_legs) == 8, sorted(fetch_legs)
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
    Measured: HEAD-before-Lane-B 9,762 bytes (0.931%), Lane B 14,859 (1.417%), the 2026-09-06
    parsed classifier 17,944 (1.711%), the 2026-09-07 fix 19,430 (1.853%), and the 2026-09-07
    fix-pass 21,687 (2.068%) -- delta +6,828 over Lane B. The last +2,257 is almost all
    OPERATOR TEXT: the two infra notifiers now enumerate every inbound class one sentence at a
    time (FetchInfraFailNotify 1,172 -> 2,141 bytes, InfraFailNotify 901 -> 1,969), which is
    the fix for an email that denied the mechanism that fired. About 330 bytes of it is the
    IsNumeric guard, rendered five times."""
    mod = _load_renderer()
    size = mod.definition_size_bytes(rendered)
    assert size < _DEFINITION_SIZE_CAP, size
    assert size < 23000, "the definition grew unexpectedly (%d bytes); re-measure" % size


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
    guard = legs["ClassifyFailureFetch"]
    assert guard["Default"] == "RecordInfraFailureFetch", "the unknown case is NOT tolerated"
    assert [c["Next"] for c in guard["Choices"]] == ["ParseBatchCauseFetch"]
    assert legs["ParseBatchCauseFetch"]["Parameters"] == {
        "job.$": "States.StringToJson($.error.Cause)"}
    cls = legs["ClassifyBatchCauseFetch"]
    assert cls["Default"] == "RecordInfraFailureFetch", "the unknown case is NOT tolerated"
    assert [c["Next"] for c in cls["Choices"]] == [
        "RecordInfraFailureFetch"] * 5 + [
        "RecordSourceFailureFetch"], "all five infra arms first; the SOURCE arm is last"
    assert legs["RecordSourceFailureFetch"]["Parameters"]["class"] == "source"
    assert legs["RecordInfraFailureFetch"]["Parameters"]["class"] == "infra"
    for rec in ("RecordSourceFailureFetch", "RecordInfraFailureFetch"):
        assert legs[rec]["End"] is True, rec
        assert legs[rec]["Parameters"]["cause.$"] == "States.JsonToString($.error)"


def test_the_gate_reader_and_the_fetch_reader_are_the_same_parser(rendered):
    """ONE PARSER, TWO READERS -- asserted on the ARTIFACT, which is the only place the claim
    can be checked. This pin REPLACES `test_rendered_gate_classifier_is_byte_identical_to_head`
    (2026-09-06). That pin froze the gate classifier's substring roster on the argument that
    sharing a list with the fetch classifier must not move the gate by one byte; the roster it
    froze is the DEFECT. The gate's Cause is the same DescribeJobs document as a fetch leg's --
    both are batch:submitJob.sync States.TaskFailed -- so it carried the same jobdef
    RetryStrategy, the same always-matching substrings, and the same dead Default. The freeze
    is therefore lifted for a named cause and replaced by the property that actually matters:
    the two readers are literally the same rendered objects."""
    states = rendered["States"]
    legs = states["Fetch"]["ItemProcessor"]["States"]

    # the parse is one local, so the two Pass states differ ONLY in Next
    gate_parse = dict(states["ParseBatchCauseGate"])
    fetch_parse = dict(legs["ParseBatchCauseFetch"])
    assert gate_parse.pop("Next") == "ClassifyBatchCauseGate"
    assert fetch_parse.pop("Next") == "ClassifyBatchCauseFetch"
    assert gate_parse == fetch_parse == {
        "Type": "Pass",
        "Parameters": {"job.$": "States.StringToJson($.error.Cause)"},
        "ResultPath": "$.batchCause",
    }

    # The FIVE shared infra arms are one local, so they differ ONLY in Next -- and since
    # 2026-09-07 they sit in the SAME POSITION in both readers: first, in the same order.
    #
    # THEY DID NOT USED TO. The gate tested its own vocabulary first and the module justified
    # the asymmetry by asserting the parsed arms are mutually exclusive. They are not, and the
    # counterexample is asserted below: one Cause on which the two readers disagreed.
    def _strip_next(arms, target):
        out = []
        for arm in arms:
            arm = dict(arm)
            assert arm.pop("Next") == target, arm
            out.append(arm)
        return out

    gate_infra = _strip_next(states["ClassifyBatchCauseGate"]["Choices"][:5], "InfraFailNotify")
    fetch_infra = _strip_next(legs["ClassifyBatchCauseFetch"]["Choices"][:5],
                              "RecordInfraFailureFetch")
    assert gate_infra == fetch_infra, (gate_infra, fetch_infra)
    assert gate_infra[0] == {"Variable": "$.batchCause.job.Container.ExitCode",
                             "IsPresent": False}, "arm 1 is 'the job never ran'"
    assert gate_infra[1] == {"And": [
        {"Variable": "$.batchCause.job.Container.ExitCode", "IsPresent": True},
        {"Variable": "$.batchCause.job.Container.ExitCode", "IsNumeric": True},
        {"Variable": "$.batchCause.job.Container.ExitCode",
         "NumericGreaterThanEquals": 128}]}, "arm 2 is 'a signal chose the exit, not the code'"
    for arm, field in zip(gate_infra[2:],
                          ("StatusReason", "Container.Reason", "Container.reason")):
        assert [g["StringMatches"] for g in arm["And"][1]["Or"]] == [
            "CannotPullContainer*", "ResourceInitializationError*", "OutOfMemory*",
            "Task failed to start*", "DockerTimeoutError*"], field
        assert all(g["Variable"] == "$.batchCause.job.%s" % field for g in arm["And"][1]["Or"])

    # and the gate's own vocabulary is bolted on top of the SHARED ran-to-an-exit guards
    gate_arms = states["ClassifyBatchCauseGate"]["Choices"]
    assert [c["Next"] for c in gate_arms] == ["InfraFailNotify"] * 5 + [
        "FailNotify", "InfraFailNotify"]
    assert gate_arms[5]["And"][-1] == {"Variable": "$.batchCause.job.Container.ExitCode",
                                       "NumericEquals": 1}, "exit 1 is the REFUSAL"
    assert [g["NumericEquals"] for g in gate_arms[6]["And"][-1]["Or"]] == [64, 70, 71, 72]
    shared = legs["ClassifyBatchCauseFetch"]["Choices"][-1]["And"][:-1]
    assert gate_arms[5]["And"][:-1] == gate_arms[6]["And"][:-1] == shared
    assert states["ClassifyGateFailure"]["Default"] == "FailNotify"
    assert states["ClassifyBatchCauseGate"]["Default"] == "FailNotify"


def test_the_two_readers_agree_on_every_cause_they_both_see(rendered):
    """THE ASYMMETRY THAT USED TO BE THERE, PINNED SHUT.

    The 2026-09-06 draft put the shared infra arms FIRST in the fetch reader and LAST in the
    gate reader, and defended the difference with the claim that under parsed fields the arms
    are mutually exclusive, "so the order is now a statement of intent rather than a safety
    property". The claim was false. One Cause breaks it: ExitCode 1 (a real gate refusal code)
    with the ordinary "Essential container in task exited" AND a container reason of
    "DockerTimeoutError: Could not transition to created". The infra arm and the ran-to-an-exit
    arm both matched, so whichever was tested first won -- fetch called it INFRA, the gate
    called it a REFUSAL, and "one parser, two readers" had two readers reading one document two
    ways.

    Both readers now test the shared arms first, in the same order. This pin asserts the
    agreement on the shape that exposed it, in BOTH spellings of the reason field, and on every
    fixture in the roster: whenever one reader takes an infra arm, so does the other."""
    for key in ("Reason", "reason"):
        job = json.loads(_fixture("batch_exit1_essential_container")["cause"])
        job["Container"][key] = "DockerTimeoutError: Could not transition to created"
        probe = {"error": "States.TaskFailed", "cause": json.dumps(job, separators=(",", ":"))}
        assert json.loads(probe["cause"])["Container"]["ExitCode"] == 1, "a refusal code"
        assert _classify_fetch(rendered, probe) == "RecordInfraFailureFetch", key
        assert _classify_gate(rendered, probe) == "InfraFailNotify", (
            "a container that never transitioned to created produced no verdict (%s)" % key)

    # AND ON THE WHOLE ROSTER, stated as the property that is actually true. The two readers
    # share their first FIVE arms and nothing else: past those, the fetch lane tolerates ANY
    # sub-signal non-zero exit while the gate reads an exact D-PR-8 vocabulary, and the two
    # Defaults are SUPPOSED to differ (the fetch lane refuses to continue on a shape nobody
    # classified; the gate still sends its ordinary email). So the claim is: whenever a Cause
    # takes one of the SHARED arms, both readers take THE SAME ONE, by index. That is the
    # property the old asymmetry broke, and it is checked by evaluating each rule rather than
    # by trusting that identical objects in different positions behave identically.
    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    fetch_reader = legs["ClassifyBatchCauseFetch"]
    gate_reader = rendered["States"]["ClassifyBatchCauseGate"]
    shared = 5

    def _first(reader, doc):
        return next((i for i, r in enumerate(reader["Choices"]) if _rule(doc, r)), None)

    landed = {}
    for name in _ALL_FIXTURES:
        fx = _fixture(name)
        if not (fx["cause"].startswith("{") and fx["error"] == "States.TaskFailed"):
            continue
        doc = _apply_parse(legs["ParseBatchCauseFetch"],
                           {"error": {"Error": fx["error"], "Cause": fx["cause"]}})
        f, g = _first(fetch_reader, doc), _first(gate_reader, doc)
        landed[name] = (f, g)
        if (f is not None and f < shared) or (g is not None and g < shared):
            assert f == g, ("%s takes shared arm %s in the fetch reader and %s in the gate"
                            % (name, f, g))
            assert _classify_fetch(rendered, fx) == "RecordInfraFailureFetch", name
            assert _classify_gate(rendered, fx) == "InfraFailNotify", name

    # the roll-call, so a fixture that stops exercising an arm is visible rather than silent:
    # never-ran 0, the three OOM spellings on the signal floor 1, the two ran-to-an-exit
    # documents past the shared block, and the unrecognised one on both Defaults.
    assert landed == {
        "batch_exit1_essential_container": (5, 5),
        "batch_cannotpull_never_started": (0, 0),
        "batch_oom_container_reason": (1, 1),
        "batch_oom_lowercase_reason": (1, 1),
        "batch_oom_attempt_reason_only": (1, 1),
        "batch_exit2_unknown_code": (5, None),
        "batch_attempt_timeout_unrecognised": (None, None),
    }, landed
    assert fetch_reader["Default"] == "RecordInfraFailureFetch"
    assert gate_reader["Default"] == "FailNotify", (
        "the ONE place the two readers are meant to differ, and it is the unknown case")


# ---------------------------------------------------------------------------------------
# THE EMAIL MUST NOT DENY THE MECHANISM THAT FIRED.
#
# Both infra notifiers ENUMERATE the classes that reach them, and an enumeration goes stale
# the moment an arm is added. The 2026-09-06 draft is the proof: it named the never-ran arm
# and the roster prefixes but not the signal-exit arm, so on exit 137 -- the OOM class the
# whole fix was built to catch -- the operator was told "the container never became the job"
# (false: it ran and was SIGKILLed) and sent hunting a StatusReason prefix that is not there.
#
# So the enumeration is not asserted as a list of magic strings. It is DERIVED from the
# rendered classifier arms, and an arm shape this reducer does not recognise RAISES -- which
# means a new arm cannot be added without this pin, and therefore the email, being updated.
# ---------------------------------------------------------------------------------------
_ROSTER_PREFIXES = ("CannotPullContainer", "ResourceInitializationError", "OutOfMemory",
                    "Task failed to start", "DockerTimeoutError")


def _infra_arm_mechanisms(reader, target):
    """Reduce the arms of a rendered reader that route to `target` to the MECHANISMS an
    operator has to be told about. Unknown shapes raise on purpose."""
    kinds = []
    for arm in reader["Choices"]:
        if arm.get("Next") != target:
            continue
        conj = arm.get("And", [arm])
        if len(conj) == 1 and conj[0].get("IsPresent") is False:
            kinds.append(("no-exit-code", conj[0]["Variable"]))
            continue
        floor = [c["NumericGreaterThanEquals"] for c in conj
                 if "NumericGreaterThanEquals" in c]
        if floor:
            kinds.append(("signal-floor", floor[0]))
            continue
        ors = [c["Or"] for c in conj if "Or" in c]
        if ors and all("StringMatches" in g for g in ors[0]):
            fields = {g["Variable"].split(".job.", 1)[1] for g in ors[0]}
            assert len(fields) == 1, ors[0]
            kinds.append(("reason-prefix", fields.pop(),
                          tuple(g["StringMatches"].rstrip("*") for g in ors[0])))
            continue
        if ors and all("NumericEquals" in g for g in ors[0]):
            kinds.append(("exit-codes", tuple(g["NumericEquals"] for g in ors[0])))
            continue
        raise AssertionError(
            "unrecognised infra arm -- teach this pin AND the notifier text: %r" % (arm,))
    return kinds


def _inbound(states, target):
    """Every state in one States container with an edge to `target`, by any mechanism."""
    found = set()
    for name, state in states.items():
        edges = [c.get("Next") for c in state.get("Choices", [])]
        edges += [c.get("Next") for c in state.get("Catch", [])]
        edges += [state.get("Default"), state.get("Next")]
        if target in edges:
            found.add(name)
    return found


def test_the_fetch_infra_email_describes_every_arm_that_can_route_to_it(rendered):
    """THE FETCH HALF, pinned against the classifier's own arm list so the two cannot drift.

    Six things reach FetchInfraFailNotify and the message must name all six in its own words:
    the five shared infra arms, the reader Default, the shape/name gate's Default, the Batch
    service faults caught by NAME, and a Glue leg (a Glue cause carries no exit code, so this
    lane never tolerates one). The mechanism list is read off the RENDERED arms; the needles
    are what an operator would have to see in order to look in the right place."""
    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    msg = rendered["States"]["FetchInfraFailNotify"]["Parameters"]["Message.$"].lower()

    kinds = _infra_arm_mechanisms(legs["ClassifyBatchCauseFetch"], "RecordInfraFailureFetch")
    assert kinds == [
        ("no-exit-code", "$.batchCause.job.Container.ExitCode"),
        ("signal-floor", 128),
        ("reason-prefix", "StatusReason", _ROSTER_PREFIXES),
        ("reason-prefix", "Container.Reason", _ROSTER_PREFIXES),
        ("reason-prefix", "Container.reason", _ROSTER_PREFIXES),
    ], kinds

    for kind in kinds:
        if kind[0] == "no-exit-code":
            assert "no exit code" in msg, "arm 0 (the job never became a job) is not described"
        elif kind[0] == "signal-floor":
            assert str(kind[1]) in msg and "137" in msg and "sigkill" in msg, (
                "arm 1 is the OOM class and the email must say an exit code at or above %d "
                "is a KILL, not a choice -- this is the arm the 09-06 draft omitted" % kind[1])
        elif kind[0] == "reason-prefix":
            where = "statusreason" if kind[1] == "StatusReason" else "container reason"
            assert where in msg, kind
            for prefix in kind[2]:
                assert prefix.lower() in msg, (kind[1], prefix)
    # both spellings of the container reason are named, because both are arms
    assert "reason or reason" in msg, "the email must say Batch may spell it either way"

    # and the edges that are NOT classifier arms
    assert _inbound(legs, "RecordInfraFailureFetch") == {
        "BatchSyncFetch", "GlueSyncFetch", "ClassifyFailureFetch", "ClassifyBatchCauseFetch",
    }, sorted(_inbound(legs, "RecordInfraFailureFetch"))
    assert "batch service fault" in msg and ".sync timeout" in msg, "the by-NAME Batch faults"
    assert "glue" in msg, "a Glue fetch leg is recorded infra and the email must say so"
    assert "could not be classified" in msg and "not a json object" in msg, "both Defaults"
    assert legs["ClassifyFailureFetch"]["Default"] == "RecordInfraFailureFetch"
    assert legs["ClassifyBatchCauseFetch"]["Default"] == "RecordInfraFailureFetch"

    # the sentence the review called AFFIRMATIVELY WRONG must be gone: the email may not offer
    # "the container never became the job" as the only reading of an infra-classed leg.
    assert "the container never became the job (no exit code" not in msg, (
        "the 09-06 wording folded five mechanisms into one false alternative")


def test_the_gate_infra_email_names_the_classes_it_gained(rendered):
    """THE GATE TWIN. InfraFailNotify closed with the D-PR-8 vocabulary and nothing else --
    "64 usage, 70 internal crash, 71 image/config fence, 72 baseline fetch" -- while its
    inbound classes grew by five arms. Milder than the fetch case (its text asserts no false
    mechanism: "the gate job did not run to a decision" is true of an OOM kill) but a partial
    list presented as the list. Same remedy, same derivation.

    It also carries the DIRECTION an earlier handoff report inverted: an exit code the gate
    CHOSE that is outside the vocabulary -- exit 2, the DSG-TAIL F1 shape -- moves the OTHER
    way, to the ordinary FailNotify email, which is the Default HEAD could not reach."""
    states = rendered["States"]
    msg = states["InfraFailNotify"]["Parameters"]["Message.$"].lower()

    kinds = _infra_arm_mechanisms(states["ClassifyBatchCauseGate"], "InfraFailNotify")
    assert kinds == [
        ("no-exit-code", "$.batchCause.job.Container.ExitCode"),
        ("signal-floor", 128),
        ("reason-prefix", "StatusReason", _ROSTER_PREFIXES),
        ("reason-prefix", "Container.Reason", _ROSTER_PREFIXES),
        ("reason-prefix", "Container.reason", _ROSTER_PREFIXES),
        ("exit-codes", (64, 70, 71, 72)),
    ], kinds

    for kind in kinds:
        if kind[0] == "no-exit-code":
            assert "no exit code" in msg, kind
        elif kind[0] == "signal-floor":
            assert str(kind[1]) in msg and "137" in msg and "sigkill" in msg, kind
        elif kind[0] == "reason-prefix":
            where = "statusreason" if kind[1] == "StatusReason" else "container reason"
            assert where in msg, kind
            for prefix in kind[2]:
                assert prefix.lower() in msg, (kind[1], prefix)
        elif kind[0] == "exit-codes":
            for code in kind[1]:
                assert str(code) in msg, code
    assert "reason or reason" in msg

    assert _inbound(states, "InfraFailNotify") == {"Gate", "ClassifyBatchCauseGate"}, sorted(
        _inbound(states, "InfraFailNotify"))
    assert "batch service fault" in msg and ".sync timeout" in msg, "the Gate Catch by NAME"

    # THE DIRECTION, in the text and on the artifact, so neither can be reported backwards.
    assert "outside the d-pr-8 vocabulary is not this email" in msg, msg
    assert _classify_gate(rendered, _fixture("batch_exit2_unknown_code")) == "FailNotify"


# =======================================================================================
# 9. THE FIXTURE PINS -- the rendered Choice rules, EVALUATED against real Causes
#
# WHY THIS SECTION EXISTS, IN ONE SENTENCE: every pin above this line reads the SHAPE of the
# classifier, and a classifier can be perfectly shaped and still never reach one of its arms.
#
# That is not hypothetical. Lane B shipped a two-arm Cause classifier whose arm 1 tested
# StringMatches "*CannotPullContainer*" against the WHOLE Cause, and whose arm 2 -- the only
# arm that grants the tolerance the entire lane exists for -- was UNREACHABLE, because the
# Cause of a batch:submitJob.sync failure is the DescribeJobs job detail and that document
# embeds the job's own RetryStrategy.EvaluateOnExit, which on every jobdef in this estate
# names CannotPullContainer* and ResourceInitializationError*. Nine shape pins were green.
# The machine was wrong on the first real failure it ever saw: execution
# laneb-p1-20260906T234214Z, 2026-09-06 23:42Z, a fetch leg whose command was literally
# `-c "raise SystemExit(1)"`, classified INFRA, terminal FAILED / SilverPipelineInfraFailed.
#
# So these pins do the one thing a shape pin cannot: they take the rendered rules and RUN
# them, with a small ASL Choice evaluator, against Cause documents from
# tests/fixtures/sfn_causes/ -- one of which is the real P1 Cause, byte for byte.
# =======================================================================================
_FIXTURES = _REPO / "tests" / "fixtures" / "sfn_causes"


class _MissingPath(Exception):
    """A comparison reached a path that does not exist.

    In the real machine that is a States.Runtime failure, which -- this module says so three
    separate times -- NO Catch can reach: it fails the execution outright, with no
    notification. The evaluator raises instead of returning False so that an unguarded
    comparison in a rendered rule is a RED TEST rather than a silent pass."""


def _resolve(doc, path: str):
    """Resolve an ASL reference path. Returns (found, value)."""
    assert path.startswith("$."), path
    node = doc
    for seg in path[2:].split("."):
        if not isinstance(node, dict) or seg not in node:
            return False, None
        node = node[seg]
    return True, node


def _string_matches(pattern: str, value: str) -> bool:
    r"""ASL StringMatches: `*` is the only wildcard; `\*` and `\\` are its escapes."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern) and pattern[i + 1] in ("*", "\\"):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "*" else re.escape(ch))
        i += 1
    return re.fullmatch("".join(out), value, re.S) is not None


def _rule(doc, node) -> bool:
    """Evaluate ONE ASL Choice rule (or nested boolean) against `doc`.

    And/Or evaluate IN ORDER and short-circuit, which is what the `And = [IsPresent, compare]`
    idiom this module uses everywhere depends on."""
    if "And" in node:
        return all(_rule(doc, k) for k in node["And"])
    if "Or" in node:
        return any(_rule(doc, k) for k in node["Or"])
    if "Not" in node:
        return not _rule(doc, node["Not"])
    found, value = _resolve(doc, node["Variable"])
    if "IsPresent" in node:
        return found is node["IsPresent"]
    if "IsNumeric" in node:
        # A TYPE test, not a value test, and -- like IsPresent -- it must never RAISE: it
        # answers False for a missing or non-numeric path. Every IsNumeric in the rendered
        # document sits behind an IsPresent conjunct anyway, so the missing-path half of
        # that is not load-bearing; the type half is, and it is the point of the guard.
        return (found and isinstance(value, (int, float))
                and not isinstance(value, bool)) is node["IsNumeric"]
    if not found:
        raise _MissingPath(node["Variable"])
    if "StringMatches" in node:
        return isinstance(value, str) and _string_matches(node["StringMatches"], value)
    if "StringEquals" in node:
        return value == node["StringEquals"]
    if "NumericEquals" in node:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            value == node["NumericEquals"])
    if "NumericGreaterThan" in node:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            value > node["NumericGreaterThan"])
    if "NumericGreaterThanEquals" in node:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            value >= node["NumericGreaterThanEquals"])
    raise AssertionError("the evaluator does not implement %s" % sorted(node))


def _choose(state, doc) -> str:
    """Run a rendered Choice state: the first matching rule wins, else Default."""
    assert state["Type"] == "Choice", state["Type"]
    for rule in state["Choices"]:
        if _rule(doc, rule):
            return rule["Next"]
    return state["Default"]


def _apply_parse(state, doc):
    """Run the rendered parse Pass for real, intrinsic and all.

    `json.loads` here plays the part States.StringToJson plays there: if a non-JSON Cause ever
    reached this state it would RAISE, and no Catch could reach it -- which is exactly the
    failure the error-name arm and the `{*}` shape guard exist to make unreachable."""
    assert state["Type"] == "Pass", state["Type"]
    assert set(state["Parameters"]) == {"job.$"}, state["Parameters"]
    m = re.fullmatch(r"States\.StringToJson\((\$\.[\w.]+)\)", state["Parameters"]["job.$"])
    assert m, state["Parameters"]
    found, raw = _resolve(doc, m.group(1))
    assert found, m.group(1)
    key = state["ResultPath"]
    assert key.startswith("$.") and "." not in key[2:], key
    return dict(doc, **{key[2:]: {"job": json.loads(raw)}})


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / (name + ".json")).read_text(encoding="utf-8"))


_ALL_FIXTURES = ["batch_exit1_essential_container", "batch_cannotpull_never_started",
                 "batch_oom_container_reason", "batch_oom_lowercase_reason",
                 "batch_oom_attempt_reason_only", "batch_exit2_unknown_code",
                 "batch_client_exception_not_json", "batch_attempt_timeout_unrecognised"]

# The three spellings of the ONE unmeasured field. All three are OOM-killed containers that
# ran and exited 137; they differ only in where -- and whether -- the reason text appears.
_OOM_FIXTURES = ["batch_oom_container_reason", "batch_oom_lowercase_reason",
                 "batch_oom_attempt_reason_only"]

# The three needles HEAD's classifier matched against the WHOLE Cause string. HEAD was WRONG
# about where they occur (they are printed inside every jobdef's own RetryStrategy) but RIGHT
# that a Cause carrying one of them OUTSIDE that block is not a blocked source. Keeping that
# half is the regression fence below.
_HEAD_INFRA_NEEDLES = ("CannotPullContainer", "ResourceInitializationError", "OutOfMemory")


def _classify_fetch(rendered, fx) -> str:
    """Walk a FAILED fetch leg exactly as the machine does: guard -> parse -> read."""
    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    doc = {"family": "probe",
           "task": {"jobdef": "leviathan-dev-b3-flat-silver",
                    "command": ["-c", "raise SystemExit(1)"]},
           "error": {"Error": fx["error"], "Cause": fx["cause"]}}
    nxt = _choose(legs["ClassifyFailureFetch"], doc)
    if nxt != "ParseBatchCauseFetch":
        return nxt
    doc = _apply_parse(legs[nxt], doc)
    return _choose(legs[legs[nxt]["Next"]], doc)


def _classify_gate(rendered, fx) -> str:
    """Walk a FAILED gate the same way. The Gate's Catch has already split the Batch service
    faults out BY NAME, so ClassifyGateFailure only has to establish the Cause's shape."""
    states = rendered["States"]
    doc = {"family": "probe", "error": {"Error": fx["error"], "Cause": fx["cause"]}}
    nxt = _choose(states["ClassifyGateFailure"], doc)
    if nxt != "ParseBatchCauseGate":
        return nxt
    doc = _apply_parse(states[nxt], doc)
    return _choose(states[states[nxt]["Next"]], doc)


def test_the_real_p1_cause_classifies_as_a_source_block(rendered):
    """THE PIN THAT WOULD HAVE CAUGHT THE DEFECT, and the reason this file now carries an
    evaluator at all.

    The fixture is the Cause of history event 11 of execution laneb-p1-20260906T234214Z,
    copied byte for byte: a fetch leg on jobdef leviathan-dev-b3-flat-silver rev 37 whose
    ContainerOverrides.Command was `["-c", "raise SystemExit(1)"]`. The container ran. It
    chose to exit 1. That is a SOURCE failure -- the one class Lane B exists to tolerate --
    and the shipped machine called it INFRA and failed the run.

    The second half evaluates the HEAD rules (reproduced literally) against the same fixture
    and asserts they get it WRONG, so this pin cannot pass vacuously against a classifier that
    never had the bug."""
    fx = _fixture("batch_exit1_essential_container")
    assert fx["error"] == "States.TaskFailed"
    assert len(fx["cause"]) == 2631, "the fixture is no longer the measured Cause"
    assert _classify_fetch(rendered, fx) == "RecordSourceFailureFetch"
    assert _classify_gate(rendered, fx) == "FailNotify", "an exit 1 IS a verdict"

    head_classifier = {
        "Type": "Choice",
        "Choices": [
            {"And": [{"Variable": "$.error.Cause", "IsPresent": True},
                     {"Or": [{"Variable": "$.error.Cause", "StringMatches": p}
                             for p in ("*CannotPullContainer*",
                                       "*ResourceInitializationError*", "*OutOfMemory*")]}],
             "Next": "RecordInfraFailureFetch"},
            {"And": [{"Variable": "$.error.Cause", "IsPresent": True},
                     {"Variable": "$.error.Cause", "StringMatches": '*"ExitCode":*'}],
             "Next": "RecordSourceFailureFetch"},
        ],
        "Default": "RecordInfraFailureFetch",
    }
    doc = {"error": {"Error": fx["error"], "Cause": fx["cause"]}}
    assert _choose(head_classifier, doc) == "RecordInfraFailureFetch", (
        "the HEAD classifier no longer reproduces the measured defect; re-read the incident")


def test_a_cause_whose_only_infra_substrings_live_in_the_retry_strategy_is_a_source_block(
        rendered):
    """THE MECHANISM, isolated. It is not that the old roster was too broad in general -- it is
    that the substrings it matched are printed inside EVERY Batch Cause in this estate, in the
    job's own RetryStrategy, because the D-SG matrix (infra/terraform/modules/batch/main.tf)
    sets on_status_reason = "CannotPullContainer*" and "ResourceInitializationError*" on every
    jobdef. This test proves those substrings really do occur ONLY there in the measured Cause,
    and that the parsed classifier is unmoved by them."""
    fx = _fixture("batch_exit1_essential_container")
    cause = fx["cause"]
    job = json.loads(cause)
    retry = json.dumps(job["RetryStrategy"], separators=(",", ":"))
    for needle in ("CannotPullContainer", "ResourceInitializationError"):
        assert needle in cause, needle
        assert needle in retry, needle
        assert cause.count(needle) == retry.count(needle), (
            "%s occurs outside RetryStrategy in the measured Cause" % needle)
    assert job["Container"]["ExitCode"] == 1
    assert job["StatusReason"] == "Essential container in task exited"
    assert job["StatusReason"] == job["Attempts"][-1]["StatusReason"], (
        "the top-level fields must BE the latest attempt -- the classifier reads them instead "
        "of indexing Attempts[-1], which is not a single-node reference path")
    assert job["Container"]["ExitCode"] == job["Attempts"][-1]["Container"]["ExitCode"]
    assert _classify_fetch(rendered, fx) == "RecordSourceFailureFetch"
    assert _classify_gate(rendered, fx) == "FailNotify"


@pytest.mark.parametrize("name", _ALL_FIXTURES)
def test_every_recorded_cause_classifies_the_way_its_fixture_declares(rendered, name):
    """The whole roster, both readers, one table. Each fixture carries its own expectation and
    its own provenance line (REAL vs SYNTHETIC), so a shape that was never measured cannot be
    quietly promoted to evidence."""
    fx = _fixture(name)
    assert fx["provenance"].startswith(("REAL.", "SYNTHETIC")), fx["provenance"]
    assert _classify_fetch(rendered, fx) == fx["expect"]["fetch"], name
    assert _classify_gate(rendered, fx) == fx["expect"]["gate"], name


def test_an_oom_is_infra_however_batch_spells_the_container_reason(rendered):
    """THE ORDERING PROOF, AND THE CLOSE OF THE 2026-09-07 MAJOR.

    An OOM-killed container DID run and DID exit (137), and Batch reports the ordinary
    "Essential container in task exited" as its StatusReason -- the live sample quoted in
    infra/terraform/modules/batch/main.tf puts the class in the CONTAINER REASON, which is why
    that retry rule keys on on_reason and not on on_status_reason. So every infra arm must
    precede the ran-to-an-exit arm or an OOM is tolerated as a blocked source.

    WHY THIS PIN IS PARAMETRIZED. The 2026-09-06 draft carried that whole class on
    `$.batchCause.job.Container.Reason` -- a key that appears in NO measured artifact in this
    repo. The measured P1 Cause's top-level Container has sixteen keys and no reason field in
    either casing; the DescribeJobs API itself spells it lowerCamelCase; and a runtime field
    might land only in Attempts[-1], which an ASL Choice `Variable` cannot address at all. The
    fixture that exercised the arm was written to match the arm, so classifier and fixture
    moved together and no offline pin could see the guess. Three spellings now go through the
    SAME rules and all three must be infra: PascalCase at the top level, lowerCamelCase at the
    top level, and PascalCase inside Attempts only (unreachable by any rule)."""
    for name in _OOM_FIXTURES:
        fx = _fixture(name)
        job = json.loads(fx["cause"])
        assert job["StatusReason"] == "Essential container in task exited", name
        assert job["Container"]["ExitCode"] == 137, name
        assert _classify_fetch(rendered, fx) == "RecordInfraFailureFetch", name
        assert _classify_gate(rendered, fx) == "InfraFailNotify", name

    # the three really are three different spellings, or this pin is one fixture repeated
    where = {}
    for name in _OOM_FIXTURES:
        job = json.loads(_fixture(name)["cause"])
        where[name] = (sorted(k for k in job["Container"] if k.lower() == "reason"),
                       sorted(k for k in job["Attempts"][-1]["Container"] if k.lower() == "reason"))
    assert where == {"batch_oom_container_reason": (["Reason"], ["Reason"]),
                     "batch_oom_lowercase_reason": (["reason"], ["reason"]),
                     "batch_oom_attempt_reason_only": ([], ["Reason"])}, where

    # THE ARM THAT CARRIES THE CLASS reads a MEASURED field. Strip BOTH reason arms out of the
    # rendered reader and the attempts-only fixture -- the one no reason arm can reach -- must
    # still be infra, which is what makes the key name non-load-bearing rather than merely
    # double-guessed.
    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    reader = legs["ClassifyBatchCauseFetch"]
    without_reason = dict(reader, Choices=[c for c in reader["Choices"]
                                           if "Container.Reason" not in json.dumps(c)
                                           and "Container.reason" not in json.dumps(c)])
    assert len(without_reason["Choices"]) == len(reader["Choices"]) - 2, "two reason arms"
    for name in _OOM_FIXTURES:
        fx = _fixture(name)
        doc = _apply_parse(legs["ParseBatchCauseFetch"],
                           {"error": {"Error": fx["error"], "Cause": fx["cause"]}})
        assert _choose(without_reason, doc) == "RecordInfraFailureFetch", name

    # ...and the reason arms still earn their place: an OOM whose container somehow exited
    # BELOW the signal floor is caught by them alone. This document is a RULE PROBE built here,
    # not evidence -- no such shape has been observed -- so it lives in the pin, not in the
    # fixture roster.
    for key in ("Reason", "reason"):
        job = json.loads(_fixture("batch_oom_container_reason")["cause"])
        job["Container"].pop("Reason")
        job["Container"][key] = "OutOfMemoryError: container killed due to memory usage"
        job["Container"]["ExitCode"] = 1
        probe = {"error": "States.TaskFailed", "cause": json.dumps(job, separators=(",", ":"))}
        assert _classify_fetch(rendered, probe) == "RecordInfraFailureFetch", key
        assert _classify_gate(rendered, probe) == "InfraFailNotify", key

    arms = legs["ClassifyBatchCauseFetch"]["Choices"]
    source_arm = next(i for i, c in enumerate(arms) if c["Next"] == "RecordSourceFailureFetch")
    assert source_arm == len(arms) - 1, "every infra arm precedes the ran-to-an-exit arm"


def test_no_producer_in_this_estate_can_choose_a_signal_exit_code(rendered):
    """THE WIDENING'S SAFETY, MEASURED RATHER THAN ASSERTED.

    The arm that carries the OOM class reads `Container.ExitCode >= 128` -- the POSIX signal
    convention, 137 = 128 + SIGKILL(9), which is what an OOM-killed Fargate container reports
    when the ECS agent stops the task and the process never returns a value of its own. That
    arm is on the INFRA side, so being wrong about it can only make a reader MORE conservative
    (fetch stops tolerating, the gate stops claiming a verdict) -- but it would still be a
    THEFT if any job in this estate deliberately exited above the floor, because the fetch lane
    would stop tolerating a real blocked source.

    So the floor is measured against the code that actually runs: every literal exit code in
    jobs/, src/leviathan/ and scripts/. Measured 2026-09-07: {0, 1, 2, 3, 5, 6, 7, 64, 70, 71,
    72}, maximum 72. The gate's own D-PR-8 vocabulary is the top of that range and its highest
    code sits 56 below the floor."""
    floor = re.search(r"batch_cause_signal_exit_floor\s*=\s*(\d+)", _sfn_text())
    assert floor and int(floor.group(1)) == 128, "the signal floor moved"
    floor = int(floor.group(1))

    literal = re.compile(r"(?:sys\.exit\(|SystemExit\(|EXIT_[A-Z_]+ = )(\d+)")
    seen: set[int] = set()
    for root in ("jobs", "src/leviathan", "scripts"):
        for path in sorted((_REPO / root).rglob("*.py")):
            seen.update(int(m) for m in literal.findall(path.read_text(encoding="utf-8",
                                                                      errors="replace")))
    assert seen, "the exit-code scan found nothing -- it has stopped measuring anything"
    assert max(seen) < floor, sorted(n for n in seen if n >= floor)
    assert {0, 1, 2, 64, 70, 71, 72} <= seen, sorted(seen)

    # and the floor is genuinely reachable by the rule, not dead config
    assert any("NumericGreaterThanEquals" in json.dumps(c) for c in
               rendered["States"]["ClassifyBatchCauseGate"]["Choices"])


def test_a_head_needle_in_a_failure_reason_field_is_never_tolerated(rendered):
    """THE REGRESSION FENCE, RE-STATED AS THE PROPERTY THAT IS ACTUALLY TRUE.

    THE PROPERTY, PLAINLY. If one of HEAD's three needles (CannotPullContainer,
    ResourceInitializationError, OutOfMemory) appears in a field of the job detail that says
    WHY THE LATEST ATTEMPT FAILED -- the top-level StatusReason, or the container reason in
    EITHER spelling -- then the fetch reader must not tolerate it and the gate reader must not
    credit it with a verdict. The needle is located by reading the DOCUMENT, scanning those
    fields for the substring, never by reading the rule's own field names: drop a field from
    the roster and this pin goes red while a pin keyed on the rule would follow the rule.

    WHAT THIS PIN USED TO CLAIM, AND WHY THAT WAS WRONG (review finding 2026-09-07, MINOR). It
    demanded that a needle surviving ANYWHERE in the document outside RetryStrategy be
    intolerable, and hid the over-reach behind `checked == 4`, a count that happened to select
    only documents where the claim held. Four shapes break it, and THE READER IS RIGHT IN ALL
    FOUR -- reading needles out of the whole document is the defect this lane exists to fix.
    They are asserted below as designed TOLERANCES, not skipped:
      (1) the needle inside RetryStrategy: every jobdef in this estate prints
          CannotPullContainer* and ResourceInitializationError* there, which is the measured
          defect (probe laneb-p1-20260906T234214Z);
      (2) the needle only in JobName;
      (3) the needle only in the resolved Container.Command;
      (4) the needle only in a PRIOR attempt, while the LATEST attempt chose exit 1. The
          top-level Container IS the latest attempt (measured on the P1 Cause), and with
          attempts=2 and CannotPullContainer* as a RETRY rule, attempt-1-CannotPull then
          attempt-2-ran is exactly the shape the D-SG matrix is built to produce -- so this is
          not exotic, and the day a real one is captured this pin must stay green."""
    witnessed = {}
    for name in _ALL_FIXTURES:
        fx = _fixture(name)
        if not fx["cause"].startswith("{"):
            witnessed[name] = []
            continue
        job = json.loads(fx["cause"])
        fields = {"StatusReason": job.get("StatusReason")}
        for key, value in job.get("Container", {}).items():
            if key.lower() == "reason":
                fields["Container." + key] = value
        hits = sorted({n for value in fields.values() if isinstance(value, str)
                       for n in _HEAD_INFRA_NEEDLES if n in value})
        witnessed[name] = hits
        if not hits:
            continue
        assert _classify_fetch(rendered, fx) == "RecordInfraFailureFetch", name
        assert _classify_gate(rendered, fx) == "InfraFailNotify", name

    # the roll-call, so a fixture that stops carrying its needle is visible rather than silent.
    # The attempts-only OOM has NO needle in a readable field -- no rule this module can write
    # reaches Attempts[-1] -- and it is infra anyway, on the signal-exit arm. That is the whole
    # reason the key name stopped being load-bearing.
    assert witnessed == {
        "batch_exit1_essential_container": [],
        "batch_cannotpull_never_started": ["CannotPullContainer"],
        "batch_oom_container_reason": ["OutOfMemory"],
        "batch_oom_lowercase_reason": ["OutOfMemory"],
        "batch_oom_attempt_reason_only": [],
        "batch_exit2_unknown_code": [],
        "batch_client_exception_not_json": [],
        "batch_attempt_timeout_unrecognised": [],
    }, witnessed
    assert sum(1 for v in witnessed.values() if v) == 3, witnessed

    # THE FOUR DESIGNED EXCLUSIONS, each built here and each asserted TOLERATED. The P1 Cause
    # is the real one; the other three are rule probes on the P1 envelope, labelled as such.
    p1 = _fixture("batch_exit1_essential_container")
    assert any(n in p1["cause"] for n in _HEAD_INFRA_NEEDLES), "the needles ARE in the Cause"
    assert _classify_fetch(rendered, p1) == "RecordSourceFailureFetch", "(1) RetryStrategy"

    def _probe(mutate) -> dict:
        job = json.loads(p1["cause"])
        mutate(job)
        return {"error": "States.TaskFailed",
                "cause": json.dumps(job, separators=(",", ":"))}

    def _set_job_name(job):
        job["JobName"] = "cepea-CannotPullContainer-probe"

    def _set_command(job):
        job["Container"]["Command"] = ["-c", "print('OutOfMemory')"]

    def _set_prior_attempt(job):
        first = json.loads(json.dumps(job["Attempts"][0]))
        first["StatusReason"] = "CannotPullContainerError: pull image manifest has been retried"
        first["Container"]["ExitCode"] = 1
        job["Attempts"] = [first] + job["Attempts"]
        job["RetryStrategy"]["Attempts"] = 2

    for label, mutate in (("(2) JobName", _set_job_name),
                          ("(3) Container.Command", _set_command),
                          ("(4) a PRIOR attempt", _set_prior_attempt)):
        probe = _probe(mutate)
        assert any(n in probe["cause"] for n in _HEAD_INFRA_NEEDLES), label
        assert _classify_fetch(rendered, probe) == "RecordSourceFailureFetch", label
        assert _classify_gate(rendered, probe) == "FailNotify", label

    # ...and HEAD gets all four WRONG, which is what makes them the lane, not a nicety.
    head_needle_arm = {"And": [{"Variable": "$.error.Cause", "IsPresent": True},
                               {"Or": [{"Variable": "$.error.Cause", "StringMatches": "*%s*" % n}
                                       for n in _HEAD_INFRA_NEEDLES]}],
                       "Next": "RecordInfraFailureFetch"}
    head = {"Type": "Choice", "Choices": [head_needle_arm],
            "Default": "RecordSourceFailureFetch"}
    for probe in (p1, _probe(_set_job_name), _probe(_set_command),
                  _probe(_set_prior_attempt)):
        doc = {"error": {"Error": probe["error"], "Cause": probe["cause"]}}
        assert _choose(head, doc) == "RecordInfraFailureFetch"


def test_an_unrecognised_cause_reaches_the_default_behaviourally(rendered):
    """THE DEFAULT, EVALUATED. Until this fixture existed every Cause in the roster matched some
    arm, so "an unrecognised shape is NOT tolerated" -- the strongest safety property in the
    lane -- rested on a string assertion over the HCL. A rendered mutant that flipped the fetch
    Default to RecordSourceFailureFetch turned exactly ONE pin red, and that pin read the
    Default as text.

    This document reaches it for real, on both readers: an ExitCode that is present, non-zero
    only in the sense of being 0, below the signal floor, no roster prefix in any reason field,
    and a StatusReason ("Job attempt duration exceeded timeout") that is not the
    ran-to-an-exit sentence -- so the tolerance arm cannot fire either. The two Defaults differ,
    which is the point: the fetch lane refuses to continue, the gate still sends its ordinary
    email."""
    fx = _fixture("batch_attempt_timeout_unrecognised")
    job = json.loads(fx["cause"])
    assert job["Container"]["ExitCode"] == 0
    assert job["StatusReason"] == "Job attempt duration exceeded timeout"
    assert not any(k.lower() == "reason" for k in job["Container"])

    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    reader = legs["ClassifyBatchCauseFetch"]
    doc = _apply_parse(legs["ParseBatchCauseFetch"],
                       {"error": {"Error": fx["error"], "Cause": fx["cause"]}})
    assert not any(_rule(doc, rule) for rule in reader["Choices"]), (
        "the fixture matched an arm, so it no longer exercises the Default")
    assert _choose(reader, doc) == reader["Default"] == "RecordInfraFailureFetch"

    gate = rendered["States"]["ClassifyBatchCauseGate"]
    gate_doc = _apply_parse(rendered["States"]["ParseBatchCauseGate"],
                            {"error": {"Error": fx["error"], "Cause": fx["cause"]}})
    assert not any(_rule(gate_doc, rule) for rule in gate["Choices"])
    assert _choose(gate, gate_doc) == gate["Default"] == "FailNotify"


def test_a_non_json_cause_never_reaches_the_parse(rendered):
    """A Pass state cannot carry a Catch -- ASL allows Retry/Catch on Task, Parallel and Map
    only -- so a Cause that cannot be parsed must never REACH the parse. A SubmitJob rejection
    (probe P2's shape: a jobdef that does not exist) arrives under Batch.ClientException with a
    plain English sentence as its Cause. Two independent stops: the error-NAME arm and the
    `{*}` JSON-object shape guard. This asserts BOTH, each on its own, then shows the trap is
    real by proving the parse would in fact have raised."""
    fx = _fixture("batch_client_exception_not_json")
    assert not fx["cause"].startswith("{")
    with pytest.raises(json.JSONDecodeError):
        json.loads(fx["cause"])

    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    assert _classify_fetch(rendered, fx) == "RecordInfraFailureFetch"
    assert _classify_gate(rendered, fx) == "FailNotify"

    # stop 1: the NAME alone is enough, even with a JSON-object cause
    good = _fixture("batch_exit1_essential_container")
    named = {"error": "Batch.ClientException", "cause": good["cause"]}
    assert _classify_fetch(rendered, named) == "RecordInfraFailureFetch"
    # stop 2: the SHAPE alone is enough, even under the right name
    shaped = {"error": "States.TaskFailed", "cause": fx["cause"]}
    assert _classify_fetch(rendered, shaped) == "RecordInfraFailureFetch"
    assert _classify_gate(rendered, shaped) == "FailNotify"
    assert legs["ClassifyFailureFetch"]["Default"] == "RecordInfraFailureFetch"


def test_every_classifier_comparison_is_ispresent_and_isnumeric_guarded(rendered):
    """The house idiom, checked STRUCTURALLY over the artifact rather than by counting the
    string "IsPresent = true" in the HCL. An unguarded comparison against a missing path is a
    States.Runtime failure that no Catch can reach, so every comparison in these five Choice
    states must sit in an And whose EARLIER conjuncts assert its variable IsPresent.

    SINCE 2026-09-07 THE SAME WALK ALSO ENFORCES THE TYPE GUARD, and it is a NEW obligation,
    not a restatement. Measured on the rendered documents: HEAD contains ZERO numeric
    comparators (IsPresent 7, StringMatches 21, StringEquals 4); this tree contains EIGHT, and
    all eight read one field, `$.batchCause.job.Container.ExitCode`, which States.StringToJson
    lifted out of a string AWS wrote. IsPresent does not cover present-but-wrong-type, ASL's
    behaviour when a Numeric* comparator meets a string is asserted nowhere in this repo, and a
    Choice state cannot carry a Catch -- so every Numeric* must ALSO sit behind an `IsNumeric`
    conjunct in the same And. With the guard, a non-numeric ExitCode simply fails to match and
    falls through to the reader Default, which on both readers is today behaviour.

    RouteIntegration* is deliberately NOT in this list: `$.task.integration` is put in scope by
    the Map ItemSelector on every item, so it is present by construction and has never been
    guarded."""
    legs = rendered["States"]["Fetch"]["ItemProcessor"]["States"]
    guarded_states = {
        "AnyFetchLegFailed": rendered["States"]["AnyFetchLegFailed"],
        "ClassifyGateFailure": rendered["States"]["ClassifyGateFailure"],
        "ClassifyBatchCauseGate": rendered["States"]["ClassifyBatchCauseGate"],
        "ClassifyFailureFetch": legs["ClassifyFailureFetch"],
        "ClassifyBatchCauseFetch": legs["ClassifyBatchCauseFetch"],
    }
    compared = []
    numeric = []
    _NUMERIC = ("NumericEquals", "NumericGreaterThan", "NumericGreaterThanEquals",
                "NumericLessThan", "NumericLessThanEquals")

    def check(node, present: set, is_num: set, name: str) -> None:
        if "And" in node:
            seen, seen_num = set(present), set(is_num)
            for conj in node["And"]:
                check(conj, seen, seen_num, name)
                if conj.get("IsPresent") is True:
                    seen.add(conj["Variable"])
                if conj.get("IsNumeric") is True:
                    seen_num.add(conj["Variable"])
            return
        if "Or" in node:
            for disj in node["Or"]:
                check(disj, present, is_num, name)
            return
        if "Not" in node:
            check(node["Not"], present, is_num, name)
            return
        if "IsPresent" in node or "IsNumeric" in node:
            return
        compared.append((name, node["Variable"]))
        assert node["Variable"] in present, (
            "%s compares %s without an IsPresent guard" % (name, node["Variable"]))
        if any(k in node for k in _NUMERIC):
            numeric.append((name, node["Variable"]))
            assert node["Variable"] in is_num, (
                "%s compares %s numerically without an IsNumeric guard in the same And -- a "
                "non-numeric value there is a States.Runtime failure no Catch can take"
                % (name, node["Variable"]))

    for name, state in guarded_states.items():
        for rule in state["Choices"]:
            check(rule, set(), set(), name)
    # 48 = AnyFetchLegFailed 4, ClassifyGateFailure 1, ClassifyBatchCauseGate 23
    # (0 never-ran + 1 signal floor + 5 StatusReason + 5 Container.Reason + 5 Container.reason
    # + 2 refusal + 5 no-verdict), ClassifyFailureFetch 2, ClassifyBatchCauseFetch 18 (the
    # same 16 shared + 2 for the ran-to-an-exit source arm). Not decoration: it is what stops
    # this pin passing vacuously if a future edit deletes the arms instead of guarding them.
    assert len(compared) == 48, sorted(set(compared))
    # ...and the same non-vacuity clause for the type guard: EIGHT numeric comparisons, all on
    # the one field. 2 = the shared signal-floor arm rendered once per reader; 1 = the fetch
    # lane's NumericGreaterThan 0; 5 = the gate's own vocabulary (1 refusal + 4 no-verdict).
    assert len(numeric) == 8, sorted(numeric)
    assert {v for _, v in numeric} == {"$.batchCause.job.Container.ExitCode"}, sorted(numeric)
