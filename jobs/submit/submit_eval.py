"""Submit the GraphRAG v2 eval as a single Fargate Batch job (WS — cloud eval).

Runs the SAME `leviathan.graphrag.eval --run [--judge]` we run locally, but on the evidence-build image/queue
so the laptop stays off (the no-local-compute rule). The image bakes the causal DAGs + `eval_queries*.yaml`;
the report auto-persists to `s3://.../graphrag_evidence/eval/report_<model>_<stem>.md` (eval.main writes it there
when EVIDENCE_S3 is set), so it survives the container being reclaimed. The job reuses the evidence job-def's
`EVIDENCE_S3` env + the Anthropic secret (serving + judge models).

The eval holds every queried slice resident (`CACHE_INDEX=True`) PLUS the bge-m3 embedder and the
bge-reranker-v2-m3 cross-encoder, so we override the job-def's 16 GB up to 32 GB (a legal Fargate value for
8 vCPU; 30 GB is not) to avoid an OOM mid-run.

    # Free: print the exact submission (command + resource overrides), submit nothing
    python jobs/submit/submit_eval.py --dry-run

    # Gated: submit the v2 eval (Sonnet serving + Opus judge) — billed (~$2 of Anthropic API)
    python jobs/submit/submit_eval.py --queries configs/graphrag/eval_queries_v2.yaml --judge

    # Gated: the Bedrock-serving parity arm (convo eval; serving tokens bill to AWS, judge to Anthropic)
    python jobs/submit/submit_eval.py --convos configs/graphrag/eval_convos_v1.yaml --judge \
        --env GRAPHRAG_PROVIDER=bedrock
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3

from leviathan.common.batch_submit import write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_eval")

# Serving flags the eval MUST inherit or its measurement of that dimension is silently VACUOUS. The
# evidence-build job-def (reused as the eval image) does NOT bake these, but prod serving does, so we
# default them ON here. GRAPHRAG_REROUTE_V2: the judged-30 submit omitted it, making the rv2 (cross-
# commodity RV) eval dimension a no-op while prod (serving rev-50 taskdef) has it ON. A user --env
# override for the same key WINS (so an explicit A/B arm can still turn it off).
DEFAULT_JOB_ENV = {"GRAPHRAG_REROUTE_V2": "on"}

SERVING_FAMILY = "leviathan-dev-serving"

# S7: THE STORED ARM ENV BASE. Until this existed the base was RECONSTRUCTED BY HAND for every paid
# arm out of three layers no diff ever showed together (a job definition nobody read, DEFAULT_JOB_ENV,
# and a re-typed `--env` list), and its only record was the post-hoc `env_overrides` blob in the run
# record. That is how the V2-3 / V2-5 arms came to run GRAPHRAG_NUMBERS_THINKING OFF while production
# ran it ON. The FILE is the diffable thing; THE LIVE TASKDEF IS THE AUTHORITY -- `--from-taskdef`
# re-reads it and REFUSES a submission whose base has drifted.
DEFAULT_ENV_BASE = "configs/graphrag/arm_env_base.yaml"

# The three sections `--env-base` reads, and the one it refuses on.
_BASE_SECTIONS = ("copy_from_taskdef", "arm_only", "never_copy")


def load_env_base(path: str | Path) -> dict:
    """Parse an `arm_env_base/v1` file. Returns the whole mapping; raises on a shape that cannot be
    used, because a base that silently parsed to `{}` would submit an arm with no parity at all --
    the exact failure this file exists to close."""
    import yaml  # lazy: only an arm needs it

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"env base not found: {p}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict) or str(doc.get("schema") or "").split("/")[0] != "arm_env_base":
        raise ValueError(f"{p}: not an arm_env_base file (schema={doc.get('schema')!r})")
    td = doc.get("taskdef") or {}
    if not td.get("family") or not td.get("revision"):
        raise ValueError(f"{p}: taskdef.family / taskdef.revision are the base's own provenance and "
                         f"one of them is missing -- an arm whose env came from an unnamed revision "
                         f"cannot be reproduced")
    for sec in _BASE_SECTIONS:
        if not isinstance(doc.get(sec) or {}, dict):
            raise ValueError(f"{p}: section {sec!r} is not a mapping")
    both = set(doc.get("copy_from_taskdef") or {}) & set(doc.get("never_copy") or {})
    if both:
        raise ValueError(f"{p}: {sorted(both)!r} are in BOTH copy_from_taskdef and never_copy -- the "
                         f"base would both demand and forbid the same key")
    return doc


def env_from_base(doc: dict) -> dict[str, str]:
    """The env a base CONTRIBUTES: `copy_from_taskdef` then `arm_only`. `never_copy` contributes
    nothing by construction -- it is a list of things this function must not put in the env."""
    out: dict[str, str] = {}
    for sec in ("copy_from_taskdef", "arm_only"):
        for k, v in (doc.get(sec) or {}).items():
            out[str(k)] = "" if v is None else str(v)
    return out


def base_drift(doc: dict, serving_env: dict[str, str]) -> list[str]:
    """The REFUSAL list: every `copy_from_taskdef` key the LIVE taskdef no longer carries, or carries
    at a different value, plus every `never_copy` key that somehow reached the base's own env.

    THE TASKDEF IS THE AUTHORITY AND THE FILE IS THE RECORD, so drift is an error and never a warning:
    a stored base that no longer describes production is an arm measuring a seat nobody serves, which
    is the whole class this file was written to close. `serving_env` empty (a describe failure) yields
    NO drift -- the caller must decide whether to proceed without the authority, and says so."""
    if not serving_env:
        return []
    errs: list[str] = []
    for k, v in sorted((doc.get("copy_from_taskdef") or {}).items()):
        want = "" if v is None else str(v)
        if k not in serving_env:
            errs.append(f"{k}: in the stored base, ABSENT from the live taskdef")
        elif serving_env[k] != want:
            errs.append(f"{k}: base {want!r} != live {serving_env[k]!r}")
    for k in sorted(doc.get("never_copy") or {}):
        if k in (doc.get("arm_only") or {}):
            errs.append(f"{k}: never_copy and arm_only both name it")
    return errs


def base_new_in_serving(doc: dict, serving_env: dict[str, str]) -> list[str]:
    """Serving env keys the stored base CLASSIFIES NOWHERE -- neither copied nor refused.

    ADVISORY, NOT A REFUSAL, and the asymmetry is the point: a NEW serving flag is a decision the base's
    author has not made yet, and an unmade decision must be SHOWN rather than guessed either way.

    EVERY KEY, NOT ONLY THE `GRAPHRAG_*` HALF. This scanned the prefix alone until 2026-09-11, and the
    base itself disproves that scope: it classifies TEN non-GRAPHRAG serving keys by hand (the three
    `COGNITO_*`, `EVIDENCE_PG_POOL`, `EVIDENCE_PG_STATEMENT_TIMEOUT_MS` and the jobdef's own baked
    `PYTHONPATH`/`AWS_REGION`/`LEVIATHAN_*`/`EVIDENCE_*`), so a prefix filter declared the guard blind
    to the exact class the author had already found worth deciding. A new `EVIDENCE_*`, `COGNITO_*` or
    bare serving key was invisible. MEASURED against `leviathan-dev-serving:133` on 2026-09-11: all 73
    keys (63 GRAPHRAG_*, 10 others) classify, so widening the scan reports ZERO new lines today and
    costs nothing but the next unclassified key's visibility."""
    known = set(doc.get("copy_from_taskdef") or {}) | set(doc.get("never_copy") or {})
    known |= set(doc.get("container_env_on_jobdef") or {})
    # `arm_only` COUNTS AS CLASSIFIED even when serving happens to carry the key: the section means
    # "the arm sets its OWN value here", and `GRAPHRAG_STRIP_AUDIT` -- on in both arms, off in serving
    # -- is exactly that decision. Leaving it out reported the design's own ruling as an open question.
    known |= set(doc.get("arm_only") or {})
    return sorted(k for k in serving_env if k not in known)


def open_decision_keys(doc: dict) -> list[str]:
    """The base's own UNDECIDED keys, in file order -- `open_decisions[].key`.

    THE SECTION THAT WAS SILENCED BY CONSTRUCTION. `GRAPHRAG_RERANK_BACKEND` is parked here as
    "unresolved", and the file's own words call it "a GENUINE parity var" -- yet it also sits in
    `never_copy`, which is exactly the section `parity_warnings`' `skip` set suppresses, `base_drift`
    never walks, and `base_new_in_serving` counts as CLASSIFIED. MEASURED 2026-09-11: a `--dry-run`
    with `--env-base` + `--from-taskdef leviathan-dev-serving:133` printed ZERO lines about it, so a
    $30-55 paid arm would have submitted in total silence on the one key the base says nobody has
    decided. The resolution is not to unfile it (the never_copy reason is correct: the eval jobdef
    carries no `COHERE_API_KEY`, so copying it blind degrades or fails) -- it is to make the UNMADE
    DECISION LOUD at every submission, and to require the operator to name it out loud."""
    out: list[str] = []
    for item in doc.get("open_decisions") or ():
        key = (item or {}).get("key") if isinstance(item, dict) else None
        if key:
            out.append(str(key))
    return out


# ── THE BASE'S THREE PRECONDITIONS (S7 round 2) ─────────────────────────────────────────────────────
# The base's `job_definition:` block states THREE facts about the venue an arm must run in -- the job
# definition, the queue, and the secrets that definition must carry -- and until this round NOTHING READ
# THEM. They were prose in a file the submitter parsed for its env sections only, which is the same
# shape as the failure the file was written to close: a record nobody grades is a record that drifts.
# Each is enforced below as a PURE function (no AWS), so the deck can grade the rule itself.
#
# THE THREE DIFFER IN WHETHER A DEPARTURE CAN BE ACKNOWLEDGED, and the asymmetry is deliberate:
#   jobdef  -- an operator MAY depart, by naming the jobdef with `--job-definition` AND naming the
#              departure with `--accept-open-decision job_definition`. A second jobdef is a legitimate
#              thing to want (a probe, a repin under test); an UNNOTICED one is not.
#   queue   -- NO acknowledgement token. The base NAMES the queue; to run elsewhere, re-bank the base.
#              `leviathan-dev-queue` (submit_eval's own default) is SPOT, and a 30-turn arm reclaimed
#              mid-deck is a $30-55 loss with a half-populated artifact -- the failure an ack token
#              would let a tired operator wave through at 2am.
#   secrets -- NO acknowledgement token either, and it is the one check that must reach AWS: a Batch
#              `containerOverrides` CANNOT set secrets at all, so a jobdef missing `ANTHROPIC_API_KEY`
#              or `EVIDENCE_PG_DSN` cannot be repaired at submission time by any flag. It dies at
#              container start (`ResourceInitializationError`) or serves a board that declines
#              `pg_not_live` on every turn -- the artifact class with three prior instances.
#
# ALL THREE ARE INERT WITHOUT `--env-base`: no base, no `job_definition:` block, no preconditions, and
# every submission that predates S7 is byte-identical to what shipped.
#
# `job_definition` IS A RESERVED TOKEN NAME. `--accept-open-decision` now carries two namespaces at
# once -- the base's `open_decisions` KEYS and this one non-key token -- so a base that ever parked an
# open decision under the literal key `job_definition` would make one token mean two things at the same
# prompt. Nothing does today (measured: `open_decision_keys(base) == ['GRAPHRAG_RERANK_BACKEND']`), and
# the rule is written here rather than enforced because a base is a hand-written record: the place a
# future author reads before naming a key is this comment and the flag's own help text, both of which
# now say it. If a base ever needs that key, rename the key -- the token is the older claim.
_JOBDEF_DEPARTURE_TOKEN = "job_definition"


def jobdef_family(ref: str) -> str:
    """The FAMILY of a Batch job-definition reference: `family`, `family:12` and a full ARN all collapse
    to `family`. The comparison against the base must not turn on whether a revision was pinned."""
    return str(ref or "").split("/")[-1].split(":")[0]


def required_jobdef(doc: dict) -> str:
    """`job_definition.arm` -- the job definition an arm MUST run on, or "" when the base names none."""
    return str(((doc or {}).get("job_definition") or {}).get("arm") or "")


def required_queue(doc: dict) -> str:
    """`job_definition.queue` -- the queue an arm MUST run on, or "" when the base names none."""
    return str(((doc or {}).get("job_definition") or {}).get("queue") or "")


def required_secrets(doc: dict) -> list[str]:
    """`job_definition.secrets_required_on_jobdef` -- the secrets that CANNOT be supplied at submit."""
    got = ((doc or {}).get("job_definition") or {}).get("secrets_required_on_jobdef") or []
    return [str(s) for s in got if s]


def jobdef_refusal(doc: dict, *, job_definition: str, explicit: bool, accepted=()) -> str | None:
    """The refusal sentence when the resolved job definition is not the base's `arm`, else None.

    TWO DIFFERENT REFUSALS, because they are two different mistakes. Falling through to submit_eval's
    OWN default (`leviathan-dev-evidence-build`) is the silent one the base's text calls the first hard
    blocker: that definition carries ZERO GRAPHRAG_* flags and an image that predates the board wiring,
    so the arm would run, cost its full price, and measure a tree with no board in it. Naming ANOTHER
    definition on purpose is a decision, and a decision only needs to be said out loud."""
    want = required_jobdef(doc)
    if not want or jobdef_family(job_definition) == jobdef_family(want):
        return None
    acc = {str(a).strip() for a in (accepted or ())}
    # THE TOKEN ACQUITS ONLY A NAMED DEPARTURE, AND THE `and explicit` IS THE WHOLE RULE. S7's decision
    # reads "refuse any other jobdef unless --job-definition names one AND --accept-open-decision names
    # the departure", and round 1 shipped it as an OR: the token alone returned None BEFORE `explicit`
    # was ever read, so `--accept-open-decision job_definition` with NO `--job-definition` waved through
    # the SILENT fall-through to submit_eval's own `leviathan-dev-evidence-build` -- measured end to end
    # (full arm flags, --dry-run): EXIT 0, "VENUE DEPARTURE [ACCEPTED]", job_def=leviathan-dev-evidence-
    # build, "[DRY RUN] would submit". That is precisely the mistake this function's own docstring calls
    # the silent one, acquitted by a token whose sentence says "a departure is a decision, not a typo".
    # A token can only ever excuse a departure the operator NAMED; it can never excuse a default nobody
    # chose, because there is no decision in a fall-through to excuse.
    if _JOBDEF_DEPARTURE_TOKEN in acc and explicit:
        return None
    if not explicit:
        return (f"refusing to submit: the stored base names job_definition.arm = {want!r} and this "
                f"submission fell through to submit_eval's own default {job_definition!r}. That "
                f"definition carries ZERO GRAPHRAG_* flags and an image that predates the state-board "
                f"wiring -- the arm would bill in full and measure a tree with no board. Pass "
                f"--job-definition {want}:<rev>. NOTE that "
                f"--accept-open-decision {_JOBDEF_DEPARTURE_TOKEN} does NOT cover this either: the "
                f"token acquits a departure you NAMED with --job-definition, never a default nobody "
                f"chose -- there is no decision in a fall-through to acknowledge.")
    return (f"refusing to submit: the stored base names job_definition.arm = {want!r} and "
            f"--job-definition names {job_definition!r}. A departure from the base's own venue is a "
            f"decision, not a typo, so say it out loud: add "
            f"--accept-open-decision {_JOBDEF_DEPARTURE_TOKEN} (it rides the run record). NOTE that "
            f"`--accept-open-decision ALL` does NOT cover this: ALL accepts the base's open_decisions "
            f"KEYS, and a venue departure is not one of them.")


def queue_name(ref: str) -> str:
    """The NAME of a Batch job queue: a bare name and a full ARN
    (`arn:aws:batch:<region>:<acct>:job-queue/<name>`) both collapse to `<name>`.

    The jobdef check next door already collapses ARN/family/revision through `jobdef_family`, and the
    queue check compared raw strings -- so an operator who passed the base's own queue AS AN ARN would
    have been refused by a sentence telling him to pass the queue he had just passed. No caller spells
    it that way today (measured: every submit path passes the bare name), which is exactly why it was
    worth closing while it is still free: a fence whose refusal is unactionable is a fence that gets
    deleted at 2am. A queue has no revision suffix, so unlike `jobdef_family` this splits on `/` only."""
    return str(ref or "").split("/")[-1]


def queue_refusal(doc: dict, *, job_queue: str) -> str | None:
    """The refusal sentence when the resolved queue is not the base's, else None. NO ACK TOKEN.

    `leviathan-dev-queue` is the SPOT queue and submit_eval's own default, so the failure mode is the
    quiet one: an arm submitted with no `--queue` at all lands on Spot and can be reclaimed mid-deck.
    The base NAMES the on-demand queue; a different venue means re-banking the base, which is the only
    change that leaves a record."""
    want = required_queue(doc)
    if not want or queue_name(job_queue) == queue_name(want):
        return None
    return (f"refusing to submit: the stored base names job_definition.queue = {want!r} and this "
            f"submission would run on {job_queue!r}. In-VPC on the ON-DEMAND queue or the arm measures "
            f"nothing: off-VPC the board declines `pg_not_live` on every turn, and the estate's default "
            f"`leviathan-dev-queue` is SPOT -- a 30-turn arm reclaimed mid-deck is a paid run with a "
            f"half-populated artifact. Pass --queue {want}. There is NO --accept-open-decision token "
            f"for this one: to run an arm somewhere else, re-bank the base so the record says so.")


def missing_jobdef_secrets(doc: dict, present: list[str] | tuple[str, ...] | None) -> list[str]:
    """The base's required secrets ABSENT from a job definition's own `secrets` (sorted).

    `present` is the jobdef's secret NAMES as `describe_job_definitions` reports them. A Batch
    `containerOverrides` cannot set secrets at all, so this is not a warning: a missing one cannot be
    repaired by any flag at submission time. `present` empty is therefore a full refusal list, never a
    silent pass -- a definition with no secrets block is exactly the definition that fails at start."""
    have = {str(s) for s in (present or ())}
    return sorted(s for s in required_secrets(doc) if s not in have)


def _fetch_jobdef_secrets(region: str, ref: str) -> tuple[list[str], int | None]:
    """`(secret names, revision)` for a Batch job definition. RAISES, like `_fetch_taskdef`: this check
    is a PRECONDITION on a $30-55 arm, and a precondition that could not be read is a reason to stop.

    `family:rev` is looked up by ARN-ish reference (`jobDefinitions=[...]`, which accepts `name:rev`);
    a bare family resolves through `status=ACTIVE` and the HIGHEST revision ACROSS EVERY PAGE, which is
    what Batch itself would run -- and the caller warns that an arm should pin the revision rather than
    let it move."""
    batch = boto3.client("batch", region_name=region)
    if ":" in str(ref):
        resp = batch.describe_job_definitions(jobDefinitions=[str(ref)])
        defs = list(resp.get("jobDefinitions") or [])
    else:
        # THE BARE-FAMILY PATH MUST WALK EVERY PAGE, and round 1 read the FIRST one only. `max(revision)`
        # over page 1 of a family with more than a page of ACTIVE revisions grades a revision Batch would
        # NOT run -- and this is the single place whose whole job is to grade the right one. Benign as
        # measured today (evidence-build resolved to 135, graphrag-eval to 14, both the true highest, one
        # page each), which is the moment to close it: the check that quietly grades the wrong thing is
        # worse than no check, because it reports a pass.
        defs, _token = [], None
        while True:
            kw = {"jobDefinitionName": str(ref), "status": "ACTIVE"}
            if _token:
                kw["nextToken"] = _token
            resp = batch.describe_job_definitions(**kw)
            defs.extend(resp.get("jobDefinitions") or [])
            _token = resp.get("nextToken")
            if not _token:
                break
    if not defs:
        raise SystemExit(f"refusing to submit: Batch knows no ACTIVE job definition {ref!r}. The base's "
                         f"job_definition.arm precondition cannot be verified, and an unverified "
                         f"precondition before a paid arm is a stop.")
    jd = max(defs, key=lambda d: int(d.get("revision") or 0))
    names = [str(s.get("name")) for s in (jd.get("containerProperties") or {}).get("secrets") or []
             if s.get("name")]
    return names, jd.get("revision")


def _is_flag_on(value: str | None) -> bool:
    """A GRAPHRAG_* env value that reads as ENABLED (on/1/true/yes; anything else is off/unknown)."""
    return (value or "").strip().lower() in ("on", "1", "true", "yes")


def _graphrag_env_from_taskdef(taskdef: dict) -> dict[str, str]:
    """Pull the GRAPHRAG_* container env out of an ecs describe_task_definition response's taskDefinition."""
    out: dict[str, str] = {}
    for cd in taskdef.get("containerDefinitions", []) or []:
        for kv in cd.get("environment", []) or []:
            name = kv.get("name", "")
            if name.startswith("GRAPHRAG_"):
                out[name] = kv.get("value", "")
    return out


def parity_warnings(serving_env: dict[str, str], job_env: dict[str, str],
                    *, never_copy=()) -> list[str]:
    """serving-ON GRAPHRAG_* flags that are ABSENT from the job env being submitted (sorted).

    Pure/testable: no AWS. A serving flag set to an on-value but not present at all in the eval job
    env means the eval measures that dimension as if OFF -> the report comparison against prod is
    vacuous for it.

    `never_copy` IS THE BASE FILE'S OWN LIST and defaults to EMPTY, so the call with no base is
    byte-identical to the guard that shipped. Honouring it is what stops the warning crying about
    GRAPHRAG_AUTH, GRAPHRAG_CREDITS and GRAPHRAG_STORE on every single arm -- a guard that fires on
    keys nobody will ever copy trains its reader to ignore the one line that matters.
    """
    skip = set(never_copy or ())
    return sorted(
        k for k, v in serving_env.items()
        if k.startswith("GRAPHRAG_") and _is_flag_on(v) and k not in job_env and k not in skip
    )


def parity_mismatches(serving_env: dict[str, str], job_env: dict[str, str],
                      *, never_copy=(), allow=()) -> list[str]:
    """serving GRAPHRAG_* keys the job env carries AT A DIFFERENT VALUE (sorted `k: job != serving`).

    THE HALF THE ORIGINAL GUARD COULD NOT SEE, and it is the half that bit. `parity_warnings` only ever
    flagged ABSENCE -- so `GRAPHRAG_MODES=quick,deep` against a serving `quick,deep,max` was PRESENT,
    unflagged, and silently refused to honour a `--mode max` row; and `GRAPHRAG_NUMBERS_THINKING=off`
    against a serving `adaptive` would have passed the same way had the key been set at all.

    `allow` IS FOR DIVERGENCE THAT IS THE POINT (`GRAPHRAG_STRIP_AUDIT` on in an arm and off in
    serving, which the design names): a mismatch a human has already decided is not a finding, and
    listing it here is how the decision gets recorded instead of re-argued at every submission.
    """
    skip = set(never_copy or ()) | set(allow or ())
    return sorted(
        f"{k}: job {job_env[k]!r} != serving {v!r}"
        for k, v in serving_env.items()
        if k.startswith("GRAPHRAG_") and k in job_env and job_env[k] != v and k not in skip
    )


def _fetch_serving_graphrag_env(region: str, family: str = SERVING_FAMILY) -> dict[str, str]:
    """Latest ACTIVE task definition's GRAPHRAG_* env for `family`. Best-effort: any AWS error -> {}
    (the parity guard is advisory, so a describe failure must never block a submission)."""
    try:
        ecs = boto3.client("ecs", region_name=region)
        td = ecs.describe_task_definition(taskDefinition=family)["taskDefinition"]
        return _graphrag_env_from_taskdef(td)
    except Exception as exc:  # noqa: BLE001 - advisory guard, degrade gracefully
        logger.warning("serving-parity check skipped: could not describe task def %s (%s)", family, exc)
        return {}


def _all_env_from_taskdef(taskdef: dict) -> dict[str, str]:
    """EVERY container env name/value, prefix-free. The classification path reads this rather than the
    GRAPHRAG_* half, because the base classifies ten non-GRAPHRAG serving keys by hand and a scan that
    could not see them reported a decided key as a decision nobody made -- and, worse, could not see a
    NEW one at all. The advisory parity guard keeps its own prefix filter: it grades FLAGS."""
    out: dict[str, str] = {}
    for cd in taskdef.get("containerDefinitions", []) or []:
        for kv in cd.get("environment", []) or []:
            if kv.get("name"):
                out[kv["name"]] = kv.get("value", "")
    return out


def _fetch_taskdef(region: str, ref: str) -> tuple[dict[str, str], int | None]:
    """`(full container env, revision)` for an explicit `family` or `family:rev`. Unlike the advisory
    fetch above this one RAISES: `--from-taskdef` names the AUTHORITY the base is checked against, and
    an authority that could not be read is a reason to stop, not to proceed unchecked.

    The env is UNFILTERED: `base_drift` walks the base's own key list (all GRAPHRAG_* today) so a
    superset costs it nothing, `parity_warnings`/`parity_mismatches` apply their own prefix filter, and
    `base_new_in_serving` is the one caller that NEEDS the other ten keys to do its job."""
    ecs = boto3.client("ecs", region_name=region)
    td = ecs.describe_task_definition(taskDefinition=ref)["taskDefinition"]
    return _all_env_from_taskdef(td), td.get("revision")


def _emit_parity_warning(region: str, job_env: dict[str, str], *, base: dict | None = None,
                         serving_env: dict[str, str] | None = None) -> None:
    """Print an ASCII WARNING for any serving-ON GRAPHRAG_* flag ABSENT from the eval job env, plus any
    key present at a DIFFERENT VALUE. Advisory only (never raises, never hard-fails) -- the hard
    refusal lives in `--from-taskdef`, which is opt-in.

    ONE AUTHORITY PER SUBMISSION. `serving_env` is passed in by `--from-taskdef`, which has ALREADY
    described the NAMED revision. Re-describing `leviathan-dev-serving` here fetched the LATEST ACTIVE
    one instead, so a revision registered but not yet deployed made the refusal and the warning
    disagree about what "live" means -- two authorities inside one submission, and a second describe
    call to obtain the disagreement. Only the no-base / no-taskdef path still fetches, where "latest
    active" is the only authority there is.

    With a stored base loaded, the guard honours its `never_copy` list (so it stops crying about
    GRAPHRAG_AUTH) and its `arm_only` keys (a divergence the design DECIDED is not a finding).

    AN OPEN DECISION IS NEVER SILENCED BY `never_copy`, EVEN THOUGH IT SITS THERE. The two sections say
    different things -- never_copy says "the arm must not carry this", open_decisions says "nobody has
    decided" -- and the second must outrank the first inside a guard whose whole job is visibility. So
    the skip set below is never_copy MINUS the open keys. MEASURED 2026-09-11 on
    `leviathan-dev-serving:133`: this widening changes nothing by itself, because the one open key is
    `GRAPHRAG_RERANK_BACKEND=cohere` and `_is_flag_on("cohere")` is False, so the ABSENCE guard has no
    opinion about it at all. That is precisely why the open decision is ALSO printed unconditionally in
    the run header -- the header line is the half that always fires; this one is the half that catches
    the key the day it is set to an on-value or carried at a different one."""
    if serving_env is None:
        serving_env = _fetch_serving_graphrag_env(region)
    if not serving_env:
        return
    _open = set(open_decision_keys(base or {}))
    never = tuple(k for k in ((base or {}).get("never_copy") or ()) if k not in _open)
    allow = tuple((base or {}).get("arm_only") or ())
    missing = parity_warnings(serving_env, job_env, never_copy=never)
    if missing:
        logger.warning("SERVING-PARITY WARNING: serving-ON GRAPHRAG_* flags ABSENT from this eval job env: %s",
                       "; ".join(f"{k}={serving_env[k]}" for k in missing))
        logger.warning("  -> the eval measures these dimensions as if OFF; add --env <FLAG>=<val> if the "
                       "comparison against prod should hold. (Some divergence is legitimate.)")
    diverged = parity_mismatches(serving_env, job_env, never_copy=never, allow=allow)
    if diverged:
        logger.warning("SERVING-PARITY WARNING: GRAPHRAG_* keys set to a DIFFERENT VALUE than serving: %s",
                       "; ".join(diverged))
        logger.warning("  -> a present-but-different key is NOT absence and the old guard could not see it: "
                       "GRAPHRAG_MODES=quick,deep against a serving quick,deep,max silently refuses to "
                       "honour a --mode max row. List the key under arm_only if the divergence is the point.")


def build_command(*, queries: str | None, convos: str | None, model: str, judge: bool,
                  judge_model: str, k: int, workers: int | None = None,
                  via_orchestrator: bool = False, mode: str | None = None,
                  planner: str | None = None, only_ids: str | None = None) -> list[str]:
    """The container command (the image ENTRYPOINT is `python`, so this is the arg list to it)."""
    cmd = ["-m", "leviathan.graphrag.eval", "--run", "--model", model, "--k", str(k)]
    if convos:
        if only_ids:
            # --only-ids names ROWS of a queries deck; a convo deck has none. The eval CLI refuses the
            # same pairing -- refuse HERE too, before a job is submitted with a flag the container will
            # reject after it has already been billed for the container start.
            raise ValueError("--only-ids has no meaning with --convos")
        cmd += ["--convos", convos]
    else:
        cmd += ["--queries", queries]
        if only_ids:
            # D-HP B2 / plan E.6: a pre-registered NAMED SUBSET of a deck (G1's frozen 7-row hungry split)
            # runs through this flag. Forwarded verbatim; the container hard-errors on an unknown id, so a
            # typo fails the submission's job rather than quietly shrinking the population.
            cmd += ["--only-ids", only_ids]
    if via_orchestrator:
        # The intent-branch serving path (numbers_only/reasoning/hybrid) — REQUIRED for any run whose
        # intent accuracy is compared to the 22/30 baseline; plain answer() never sets out.intent
        # (P7-P0.1: the A1 baseline arm silently measured the one-hop path without this).
        cmd += ["--via-orchestrator"]
    if judge:
        cmd += ["--judge", "--judge-model", judge_model]
    if workers is not None:
        # e.g. --workers 1 for Bedrock-rerank arms: the Cohere Rerank quota is 3 req/min and each TURN is one
        # coalesced request, so concurrent turns (default 4 workers) would throttle -> silent bge contamination.
        cmd += ["--workers", str(workers)]
    if mode:
        # D-MW-16: the tier/preset arm lever, forwarded to eval --mode. Until this existed, a mode arm in
        # the cloud needed a HAND-REGISTERED job definition carrying the flag in its baked command, so an
        # arm's identity lived outside the submit record -- the gate could not prove which preset it ran.
        # The serving-side GRAPHRAG_MODES allowlist still decides whether the mode is HONORED (pass it via
        # --env GRAPHRAG_MODES=max,max_c0); the request is recorded either way, per row, in mode_decision.
        cmd += ["--mode", mode]
    if planner:
        cmd += ["--planner", planner]
    return cmd


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-evidence-build"        # reuse: same image + EVIDENCE_S3 env + Anthropic secret

    ap = argparse.ArgumentParser(description="Submit the GraphRAG v2 eval as a Fargate Batch job")
    ap.add_argument("--queries", default="configs/graphrag/eval_queries_v2.yaml",
                    help="queries yaml (path INSIDE the image; baked from configs/graphrag/)")
    ap.add_argument("--only-ids", default=None,
                    help="comma-separated row ids: run ONLY those rows of --queries, in deck order "
                         "(forwarded to eval --only-ids). The mechanism a PRE-REGISTERED NAMED SUBSET "
                         "executes through -- e.g. D-HP G1's frozen 7-row hungry split of "
                         "eval_queries_shape_esc_v1.yaml. An id absent from the deck hard-errors inside "
                         "the container before any spend; the artifact keeps the deck's stem as eval_set "
                         "and records the ids that ran in its top-level row_filter key")
    ap.add_argument("--convos", default=None,
                    help="conversations yaml (multi-turn session eval) — overrides --queries when set")
    ap.add_argument("--model", default="claude-sonnet-4-6", help="serving model (validated ~= Opus at ~1/5 cost)")
    ap.add_argument("--judge", action="store_true", help="add the independent Opus judge (usefulness/grounding)")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--via-orchestrator", action="store_true",
                    help="route queries through the full intent branch (orchestrator.respond) — the "
                         "serving path; required for intent-accuracy baselines (22/30 lives here)")
    ap.add_argument("--workers", type=int, default=None,
                    help="eval concurrency inside the container (forwarded to eval --workers). FAST-EVAL "
                         "RECIPE: pair --workers 4 with --env GRAPHRAG_PROVIDER=bedrock so LLM calls use the "
                         "Bedrock quota lane (the Anthropic API throttles a serial eval into 40-50min "
                         "single-turn stalls, worse now serving also runs on Anthropic). Eval rerank defaults "
                         "to LOCAL bge (rankers._rerank_backend), so workers is NOT capped by the Cohere "
                         "3-req/min quota — that cap ONLY bites if you also pass GRAPHRAG_RERANK_BACKEND=bedrock, "
                         "in which case drop to --workers 1.")
    ap.add_argument("--mode", default=None,
                    help="reasoning mode REQUESTED on every turn (quick|standard|deep|max|max_c0), "
                         "forwarded to eval --mode. Requires --via-orchestrator. Pair with "
                         "--env GRAPHRAG_MODES=<allowlist> or the mode is requested but never honored")
    ap.add_argument("--planner", default=None, choices=["l2", "onehop"],
                    help="forwarded to eval --planner: 'onehop' forces the single-contract baseline arm")
    ap.add_argument("--memory", type=int, default=32768, help="MiB; legal Fargate value for 8 vCPU (16/20/24/28/32 GB)")
    ap.add_argument("--vcpu", type=int, default=8)
    ap.add_argument("--queue", default=None,
                    help="override the Batch queue (e.g. leviathan-dev-queue-ondemand to dodge Spot interrupts)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VAL", dest="env_overrides",
                    help="extra container env var (repeatable) — e.g. GRAPHRAG_PROVIDER=bedrock for the "
                         "Bedrock-serving arm, GRAPHRAG_TIMELINE=on for a timeline arm")
    ap.add_argument("--job-definition", default=None, dest="job_definition",
                    help="Batch job definition (family or family:revision). DEFAULTS to "
                         "<project>-<env>-evidence-build, which is what every prior submission used — "
                         "so nothing existing changes. AN ARM MUST PASS THIS: evidence-build carries "
                         "ZERO GRAPHRAG_* flags and its image predates the state-board wiring, so an "
                         "arm submitted onto it measures a tree with no board. Use "
                         "leviathan-dev-graphrag-eval (20 baked env + the ANTHROPIC_API_KEY and "
                         "EVIDENCE_PG_DSN secrets, which a containerOverrides CANNOT set)")
    # DEFAULT=None IS DELIBERATE BACK-COMPAT AND IT IS ALSO THE REMAINING HOLE, said out loud rather
    # than left for the next reader to find: every submission that predates this flag (and every
    # non-arm one after it) must keep running unchanged, so the base is OPT-IN -- which means the
    # V2-3 / V2-5 failure class this file exists to close is still reachable by FORGETTING THE FLAG.
    # `DEFAULT_ENV_BASE` is the value an arm passes; it is not the argparse default on purpose.
    ap.add_argument("--env-base", default=None,
                    help=f"stored arm env base yaml -- AN ARM MUST PASS {DEFAULT_ENV_BASE} (this "
                         "defaults to NONE for back-compat with every pre-S7 submission, so omitting "
                         "it reopens the V2-3/V2-5 class: an arm whose env was retyped at the "
                         "prompt). Its copy_from_taskdef + arm_only sections become the job env UNDER "
                         "the --env overrides; its never_copy list is honoured by the parity guard. "
                         "Recorded in the run record so an arm's environment has a name")
    ap.add_argument("--from-taskdef", default=None, metavar="FAMILY[:REV]",
                    help="read that task definition and CLASSIFY it against --env-base: every "
                         "copy_from_taskdef key absent there or carrying a different value REFUSES "
                         "the submission, and so does a FAMILY that is not the one the base was "
                         "banked from. Requires --env-base. The stored file is the diffable thing; "
                         "the taskdef is the authority")
    ap.add_argument("--accept-open-decision", action="append", default=[], metavar="KEY",
                    dest="accept_open_decisions",
                    help="acknowledge one of --env-base's `open_decisions` keys (repeatable; ALL "
                         "accepts every one). A base that parks a key as undecided REFUSES the "
                         "submission until each is named here, because the undecided keys sit in "
                         "never_copy -- the one section the parity warning suppresses, base_drift "
                         "never walks and base_new_in_serving counts as classified -- so an arm would "
                         "otherwise submit in TOTAL SILENCE on the keys nobody has decided. Naming a "
                         "key here is the record that the arm report must state what it measured. IT "
                         "ALSO TAKES ONE NON-KEY TOKEN, `job_definition`, which acknowledges running "
                         "an arm on a job definition other than the base's own `job_definition.arm` "
                         "AND ONLY ALONGSIDE --job-definition (the token acquits a departure you "
                         "named, never a fall-through to the default); `ALL` does NOT cover that "
                         "token (ALL means the base's open_decisions keys, and a venue departure is "
                         "not one of them). `job_definition` IS THEREFORE A RESERVED TOKEN NAME: a "
                         "base that ever parked an open decision under that literal key would make "
                         "one token mean two things, so an open_decisions key must not be called it. "
                         "There is no token for the queue or for a missing jobdef secret -- neither "
                         "can be repaired at submit time")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.queue:
        job_queue = args.queue                               # e.g. on-demand so a long eval isn't Spot-reclaimed
    if args.job_definition:
        job_definition = args.job_definition

    aws_region = get_required_env("AWS_REGION")
    command = build_command(queries=args.queries, convos=args.convos, model=args.model,
                            judge=args.judge, judge_model=args.judge_model, k=args.k, workers=args.workers,
                            via_orchestrator=args.via_orchestrator, mode=args.mode, planner=args.planner,
                            only_ids=args.only_ids)
    overrides: dict = {
        "command": command,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(args.vcpu)},
            {"type": "MEMORY", "value": str(args.memory)},
        ],
    }
    env_pairs = [p.split("=", 1) for p in args.env_overrides if "=" in p]
    # PRECEDENCE, and it is one sentence: DEFAULT_JOB_ENV -> the stored base -> the user's --env.
    # THE USER ALWAYS WINS, because the one thing an arm must be able to do at the prompt is move the
    # single flag it is testing; the base exists to make every OTHER key reproducible, not to argue.
    base_doc: dict | None = None
    # The venue facts the preconditions below MEASURE, kept out here so they can ride the run record:
    # an arm that cannot prove which definition-revision and which secrets it ran on is an arm whose
    # `pg_not_live` decline cannot be told apart from a board that simply found nothing.
    jobdef_rev: int | None = None
    jobdef_secrets: list[str] = []
    if args.env_base:
        base_doc = load_env_base(args.env_base)          # raises on a shape that cannot be used
        _td = base_doc.get("taskdef") or {}
        logger.info("env base: %s  (from %s:%s read %s)", args.env_base, _td.get("family"),
                    _td.get("revision"), _td.get("read_utc"))
        # THE UNDECIDED KEYS, LOUD, AND BEFORE ANY SPEND. They are filed under `never_copy` (correctly
        # -- the eval jobdef has no COHERE_API_KEY), and `never_copy` is the ONE section the parity
        # warning suppresses, `base_drift` never walks and `base_new_in_serving` counts as classified.
        # The net effect measured on 2026-09-11 was a dry run that printed nothing at all about
        # GRAPHRAG_RERANK_BACKEND while the base's own text called it "a GENUINE parity var" and
        # "unresolved". A key nobody decided must not be a key nobody SEES.
        _open = open_decision_keys(base_doc)
        _accepted = {str(a).strip() for a in (args.accept_open_decisions or [])}
        _unaccepted = [k for k in _open if k not in _accepted and "ALL" not in _accepted]
        for _item in (base_doc.get("open_decisions") or ()):
            if not isinstance(_item, dict) or not _item.get("key"):
                continue
            _mark = "ACCEPTED" if _item["key"] not in _unaccepted else "UNDECIDED"
            logger.warning("OPEN DECISION [%s]: %s -- %s", _mark, _item["key"],
                           _item.get("question") or "no question recorded")
            if _item.get("fact"):
                logger.warning("  fact: %s", _item["fact"])
            logger.warning("  -> this key is in never_copy, so NO other guard in this file will "
                           "mention it again; the arm report must SAY what the arm measured.")
        if _unaccepted:
            raise SystemExit(
                f"refusing to submit: {args.env_base} parks {len(_unaccepted)} key(s) as UNDECIDED "
                f"({', '.join(_unaccepted)}). Resolve them in the base, or acknowledge each with "
                f"--accept-open-decision <KEY> (or --accept-open-decision ALL) and state in the arm "
                f"report what the arm actually measured.")
        # ── THE BASE'S THREE PRECONDITIONS, ENFORCED BEFORE ANY SPEND ───────────────────────────────
        # The `job_definition:` block was PROSE THE SUBMITTER NEVER READ until this round: it names the
        # job definition, the queue and the two secrets an arm's venue must carry, and the submitter
        # parsed the file for its env sections only. A record nobody grades is a record that drifts --
        # the same sentence this whole file exists to answer, one block down the same YAML.
        # They run HERE, inside the `--env-base` guard and BEFORE the dry-run return, so a $0 rehearsal
        # exercises the real checks (the `--from-taskdef` idiom) and so every submission without a base
        # is byte-identical to what shipped.
        _jd_err = jobdef_refusal(base_doc, job_definition=job_definition,
                                 explicit=bool(args.job_definition), accepted=_accepted)
        if _jd_err:
            raise SystemExit(_jd_err)
        if required_jobdef(base_doc) and \
                jobdef_family(job_definition) != jobdef_family(required_jobdef(base_doc)):
            # Reachable only with the departure token named above; it is a decision, so it is LOUD and
            # it rides the run record rather than living in one operator's memory of one evening.
            logger.warning("VENUE DEPARTURE [ACCEPTED]: job definition %s is NOT the base's "
                           "job_definition.arm (%s). The arm report must say which image, which baked "
                           "env and which secrets it actually ran on.",
                           job_definition, required_jobdef(base_doc))
        _q_err = queue_refusal(base_doc, job_queue=job_queue)
        if _q_err:
            raise SystemExit(_q_err)
        # THE ONE PRECONDITION THAT MUST REACH AWS. A Batch containerOverrides cannot set secrets at
        # all, so a definition missing one cannot be repaired by any flag at submission time: it dies
        # at container start with ResourceInitializationError, or -- worse, because it looks like a
        # result -- serves a board that declines `pg_not_live` on every single turn.
        _req_secrets = required_secrets(base_doc)
        if _req_secrets:
            if ":" not in str(job_definition):
                logger.warning("JOB DEFINITION IS NOT PINNED: %r names a family, so Batch resolves the "
                               "highest ACTIVE revision AT FIRE TIME and the arm's identity can move "
                               "between two submissions of the same command. Pass %s:<rev>.",
                               job_definition, job_definition)
            _jd_secrets, _jd_rev = _fetch_jobdef_secrets(aws_region, job_definition)
            jobdef_rev = _jd_rev
            jobdef_secrets = list(_jd_secrets)
            _missing = missing_jobdef_secrets(base_doc, _jd_secrets)
            if _missing:
                raise SystemExit(
                    f"refusing to submit: job definition {job_definition} (revision {_jd_rev}) is "
                    f"MISSING {len(_missing)} secret(s) the base requires: {', '.join(_missing)}. A "
                    f"Batch containerOverrides CANNOT set secrets, so no flag at this prompt can "
                    f"repair it -- register a revision carrying them (and confirm the execution role's "
                    f"GetSecretValue grant on each FIRST, or the container dies at start with "
                    f"ResourceInitializationError). Present today: "
                    f"{', '.join(_jd_secrets) or '(none)'}.")
            logger.info("jobdef precondition: %s (revision %s) carries every required secret (%s).",
                        job_definition, _jd_rev, ", ".join(_req_secrets))
    job_env: dict[str, str] = dict(DEFAULT_JOB_ENV)
    if base_doc:
        job_env.update(env_from_base(base_doc))
    job_env.update({k: v for k, v in env_pairs})
    # THE REFUSAL. `--from-taskdef` names the AUTHORITY; a base that no longer describes it is an arm
    # measuring a seat nobody serves, so this raises rather than warns. Opt-in, and it runs BEFORE the
    # dry-run return so a dry run is a real rehearsal of the check.
    taskdef_rev: int | None = None
    taskdef_rev_in_base: int | None = None
    _serving_env: dict[str, str] | None = None
    if args.from_taskdef:
        if not base_doc:
            raise SystemExit("--from-taskdef requires --env-base: there is nothing to classify against")
        _serving, taskdef_rev = _fetch_taskdef(aws_region, args.from_taskdef)
        _serving_env = _serving
        # THE BASE NAMES ITS OWN PROVENANCE AND THIS IS WHERE THE TWO ARE COMPARED. Without it a base
        # banked from `leviathan-dev-serving:133` could be "verified" against ANY family whose env
        # happens not to drift -- the check would pass, the run record would write `taskdef_checked`
        # straight from the CLI, and the file would go on claiming 133. A FAMILY mismatch is a refusal
        # (the base is a record OF that family; graded against another it grades nothing). A REVISION
        # mismatch is a loud warning and not a refusal: every copied key has just been graded against
        # the live revision by `base_drift` below, so a bump that moved only the image is a legitimate
        # state, and BOTH numbers now ride the run record so the artifact can never be ambiguous.
        _bt = base_doc.get("taskdef") or {}
        _bfam = str(_bt.get("family") or "")
        try:
            taskdef_rev_in_base = int(_bt.get("revision"))
        except (TypeError, ValueError):
            taskdef_rev_in_base = None
        _ref_fam = str(args.from_taskdef).split("/")[-1].split(":")[0]
        if _bfam and _ref_fam and _ref_fam != _bfam:
            raise SystemExit(f"refusing to submit: --env-base {args.env_base} was banked from "
                             f"{_bfam}:{_bt.get('revision')} but --from-taskdef names {_ref_fam!r}. A "
                             f"base graded against a family it did not come from grades nothing.")
        if taskdef_rev_in_base is not None and taskdef_rev is not None \
                and int(taskdef_rev) != taskdef_rev_in_base:
            logger.warning("TASKDEF REVISION MOVED: %s was banked at %s:%d, the authority resolved to "
                           "revision %s. Every copy_from_taskdef key is graded against the LIVE one "
                           "below; re-bank the file (taskdef.revision + read_utc + diff_vs_prior_base) "
                           "so the record stops claiming a revision nobody checked.",
                           args.env_base, _bfam or "?", taskdef_rev_in_base, taskdef_rev)
        _drift = base_drift(base_doc, _serving)
        _new = base_new_in_serving(base_doc, _serving)
        logger.info("taskdef %s (revision %s): %d env keys (%d GRAPHRAG_*); base copies %d, refuses %d",
                    args.from_taskdef, taskdef_rev, len(_serving),
                    sum(1 for _k in _serving if _k.startswith("GRAPHRAG_")),
                    len(base_doc.get("copy_from_taskdef") or {}), len(base_doc.get("never_copy") or {}))
        if _new:
            logger.warning("UNCLASSIFIED: %d serving env key(s) the base neither copies nor "
                           "refuses -- a decision nobody has made yet: %s", len(_new), "; ".join(_new))
        if _drift:
            for _d in _drift:
                logger.error("BASE DRIFT: %s", _d)
            raise SystemExit(f"refusing to submit: the stored base has drifted from {args.from_taskdef} "
                             f"on {len(_drift)} key(s). Re-bank {args.env_base} from the live taskdef.")
        logger.info("base matches %s on every copy_from_taskdef key.", args.from_taskdef)
    overrides["environment"] = [{"name": k, "value": v} for k, v in job_env.items()]
    stem = Path(args.convos or args.queries).stem
    job_name = f"eval-{stem.replace('_', '-')}-{args.model.replace('.', '-')}"
    if args.mode:
        # the two P3 arms are the SAME deck at the SAME model and differ only by mode -- without this the
        # two submissions are indistinguishable in the Batch console
        job_name += f"-{args.mode.replace('_', '-')}"
    if args.only_ids:
        # same argument as --mode above: a NAMED-SUBSET arm and a whole-deck arm are the same deck, model
        # and mode, so without this they are indistinguishable in the Batch console. The COUNT is the
        # distinguishing token (the ids themselves are in the run record and in the artifact's row_filter).
        job_name += f"-rows{len([t for t in args.only_ids.split(',') if t.strip()])}"
    for k, v in env_pairs:
        job_name += f"-{v.lower()[:12]}" if k == "GRAPHRAG_PROVIDER" else ""
    # THE ARM'S TWO CELLS MUST NOT SHARE A JOB NAME, and until 2026-09-11 they did: only
    # GRAPHRAG_PROVIDER contributed a suffix, so `--env GRAPHRAG_STATE_BOARD=on` (treatment) and the
    # bare control both rendered `eval-eval-queries-state-arm-a-v1-claude-opus-5-deep` -- MEASURED in a
    # dry run. That is the exact ambiguity `--mode` and `--only-ids` were given suffixes to fix, one
    # flag over. The run record's `job_env` recovers it after the fact; the Batch console does not, and
    # the console is where a human kills the wrong job. Keyed on the BASE's own `arm_flag`, so this is
    # byte-identical for every submission without a base (i.e. everything that shipped before S7).
    _arm_flag = str((base_doc or {}).get("arm_flag") or "")
    if _arm_flag:
        _armv = dict(env_pairs).get(_arm_flag)
        if _armv:
            job_name += "-" + (_arm_flag.replace("GRAPHRAG_", "").replace("_", "-").lower()
                               + "-" + str(_armv).lower())[:24]

    logger.info("queue=%s  job_def=%s  mem=%dMiB vcpu=%d", job_queue, job_definition, args.memory, args.vcpu)
    logger.info("command: python %s", " ".join(command))
    if env_pairs:
        logger.info("env overrides: %s", ", ".join(f"{k}={v}" for k, v in env_pairs))
    # THE OPEN DECISIONS, IN THE RUN HEADER, AT EVERY SUBMISSION -- not only in the warning block that
    # fires once when the base is loaded. The header is what an operator reads back off a terminal and
    # what gets pasted into an arm report, and the undecided key is the one sentence that report OWES.
    # It is printed with BOTH values because the answer is the difference between them: MEASURED on
    # `leviathan-dev-serving:133`, serving carries GRAPHRAG_RERANK_BACKEND=cohere and the job env
    # carries it not at all, so the arm reranks with local bge. No other guard in this file says that
    # out loud -- `never_copy` suppresses the absence warning, and `_is_flag_on("cohere")` is False, so
    # even the widened skip set has no opinion. This line does not depend on the value being flag-ish.
    _open_effective: dict[str, str | None] = {}
    for _k in open_decision_keys(base_doc or {}):
        _jv, _sv = job_env.get(_k), (_serving_env or {}).get(_k)
        _open_effective[_k] = _jv
        logger.warning("OPEN DECISION IN THIS RUN: %s = %s in the job env | %s on %s -- accepted at "
                       "this submission; the arm report must state what it measured.",
                       _k, repr(_jv) if _jv is not None else "<not set>",
                       repr(_sv) if _sv is not None else "<unread>",
                       args.from_taskdef or "serving (not read)")
    logger.info("report will persist to  s3://.../graphrag_evidence/eval/report_%s_%s.md", args.model, stem)

    # Serving-parity guard: WARN (never fail) if any serving-ON GRAPHRAG_* flag is missing from this
    # job env, so an eval dimension isn't silently measured as OFF vs prod. Runs on dry-run too.
    # ONE AUTHORITY: when --from-taskdef already described the NAMED revision, the guard grades against
    # THAT env rather than re-describing the family's latest ACTIVE one (a revision registered but not
    # deployed made the refusal and the warning disagree about "live", at the cost of a second call).
    _emit_parity_warning(aws_region, job_env, base=base_doc, serving_env=_serving_env)

    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s (nothing submitted).", job_name)
        return

    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted  job_name=%s  job_id=%s", job_name, resp["jobId"])

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"eval_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "queries": args.convos or args.queries, "model": args.model, "judge": args.judge,
                      "mode": args.mode, "planner": args.planner, "only_ids": args.only_ids,
                      # AN ARM'S IDENTITY BELONGS IN ITS ARTIFACT. `env_overrides` alone records what
                      # was TYPED and not what was RUN: which job definition (and therefore which
                      # image and which baked env), which stored base, and which taskdef revision that
                      # base was checked against. Without these three an arm cannot be reproduced and
                      # a gate cannot prove which tree it measured.
                      "job_definition": job_definition,
                      "job_queue": job_queue,
                      "env_base_file": args.env_base,
                      "taskdef_checked": args.from_taskdef,
                      "taskdef_rev": taskdef_rev,
                      # BOTH NUMBERS, because they can differ: `taskdef_checked` is what was TYPED,
                      # `taskdef_rev` is what the authority RESOLVED TO, and this is what the stored
                      # base CLAIMED. A record carrying only the first two lets a file go on claiming a
                      # revision nobody checked.
                      "taskdef_rev_in_base": taskdef_rev_in_base,
                      # THE UNDECIDED KEYS THE OPERATOR NAMED. An arm that ran with an open decision
                      # acknowledged is reproducible; one that ran with it silent is not.
                      "open_decisions_accepted": list(args.accept_open_decisions or []),
                      # AND WHAT EACH ONE ACTUALLY RESOLVED TO. `accepted` records that a human saw the
                      # question; this records the ANSWER the run gave it (None = the key was not set,
                      # i.e. the container's own default -- today, local bge rather than prod Cohere).
                      "open_decisions_effective": dict(_open_effective),
                      # THE VENUE, MEASURED RATHER THAN TYPED: which revision of the job definition
                      # Batch resolved and which secrets it carried. Both are preconditions the base
                      # states, and an arm that cannot prove them cannot tell a real decline from an
                      # off-VPC one.
                      "jobdef_revision": jobdef_rev,
                      "jobdef_secrets": list(jobdef_secrets),
                      "env_overrides": dict(env_pairs),
                      # THE FULL SUBMITTED ENV, not just the hand-typed half.
                      "job_env": dict(job_env)})


if __name__ == "__main__":
    main()
