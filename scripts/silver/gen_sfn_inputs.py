#!/usr/bin/env python
"""A-W6: render the committed per-family DAG chain descriptors into Step Functions
execution-input JSON (the A-W2 thin-contract input schema).

SOURCE OF TRUTH: ``configs/silver/dags/{schedule}.json`` -- one hand-authored chain descriptor
per Section-3 row of docs/private/A1A2_PLAN.md (24 schedules across 22 catalog families; the
world_bank + usda_nass + weather families each carry two schedules, and gold_weather_z folds into
the weather_daily gold phase). Each descriptor carries the family's cron, wave, publish class,
gate tables, retry policy, and the fetch/bronze/silver(/gold) task chain with the correct
invocation form ([m]=-m module, [s]=script .py, [g]=Glue StartJobRun).

This generator renders each descriptor into the SFN startExecution ``Input`` JSON matching the
A-W2 thin-contract state machine (infra/terraform/modules/step_functions/main.tf), whose shape is
proven by the LIVE Wave-0 reference entry ``module.eventbridge.schedules.fx_macro_daily`` in
infra/terraform/envs/dev/main.tf (ran end-to-end today incl. the autonomous KMS promote)::

    { family, asof, auth_mode, gate_tables, gate_baseline_uri,
      phases {fetch:{tasks:[]}, bronze:{tasks:[]}, silver:{tasks:[]}},   # OBJECT, not a list
      gate  {jobdef, queue, command},                                    # the silver_rebuild_gate task
      promote {mode, tasks} }

Shape rules the machine enforces (main.tf), which earlier renders violated:
  * ``phases`` is an OBJECT keyed fetch/bronze/silver -- each Map reads a fixed ``$.phases.<p>.tasks``
    ItemsPath, and a MISSING path errors the Map, so all three keys are ALWAYS emitted (empty
    ``{"tasks": []}`` when the descriptor lacks that phase). There is NO Gold Map: a ``gold`` phase
    folds into ``silver`` (weather's dependent gold_weather_z; see the weather caveat below).
  * ``gate`` is a first-class block (``$.gate.jobdef``/``$.gate.queue``/``$.gate.command``); a null
    gate crashes the [Gate] state.
  * every Batch task carries ``env`` as the ContainerOverrides.Environment LIST ``[{Name,Value}]``
    (never ``{}``); an autonomous promote task carries the KMS approval pair.
  * jobdefs are UNVERSIONED names (``leviathan-dev-b3-flat-silver`` etc.) so the schedule tracks the
    latest active revision; the ``:N`` revision suffix is stripped.

PLATFORM CONSTANTS (not descriptor-driven -- see the constants below): the scheduled thin contract
runs on the on-demand Fargate queue ``leviathan-dev-queue-ondemand`` (NOT the interruptible
FARGATE_SPOT ``leviathan-dev-queue``, which must never carry a mid-canonical-publish task); the gate
jobdef is ``leviathan-dev-silver-gate``; the promote leg runs under ``leviathan-dev-silver-publisher-
runner`` (which carries the silver-publisher role + kms:Sign) with the KMS approval env pair -- UNLESS
the descriptor sets the optional ``promote_jobdef`` self-promotion override (see below).

The scheduler's ``Input=`` is thus reproducible from the descriptors, never hand-typed. Rendered
inputs are written under ``configs/silver/dags/_rendered/{schedule}.input.json``.

The ``--render-schedule`` mode additionally emits, per family, the FULL ``StartExecution`` body
(``{StateMachineArn, Name, Input}``) under ``_rendered/{schedule}.schedule.json`` so a Terraform
schedule entry can ``file()`` the body instead of open-coding it in HCL. ``StateMachineArn`` is left
as the ``${state_machine_arn}`` placeholder for tf to fill; ``Name`` and the gate/asof carry the
``<aws.scheduler.*>`` context attributes the scheduler resolves at fire time; ``Input`` is the
execution-input JSON as an escaped string.

READ-ONLY of the descriptors; deterministic; AWS-free. Re-running produces a byte-identical
rendered tree -- the ``--check`` idempotency gate (exit 3 on drift), mirroring
``gen_registry_from_baseline.py``'s convention.

The publish-mode contract:
  * a silver/gold task with ``publish_mode == "shadow_canonical"`` runs ``--publish-mode shadow`` in
    the [Silver]/[Gold] phase and is re-run ``--publish-mode canonical`` (under the silver-publisher
    role) in [Promote];
  * ``latest_only`` (CLASS-B pre-retrofit + gate-protected weather per-source b2s / gold) writes
    directly, no shadow, never enters [Promote];
  * ``projected_canonical`` (FAOSTAT Glue) publishes with no shadow -- the gate is a post-publish
    audit (promote_mode == post_publish_audit).

Usage:
  python scripts/silver/gen_sfn_inputs.py                    write the {schedule}.input.json tree
  python scripts/silver/gen_sfn_inputs.py --render-schedule  write the {schedule}.schedule.json tree
  python scripts/silver/gen_sfn_inputs.py --check            byte-identity gate on the .input.json tree
  python scripts/silver/gen_sfn_inputs.py --render-schedule --check  byte-identity gate on .schedule.json

The descriptor lint (exit 2 on any violation) runs in every mode; ``--check`` exits 3 on drift.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
DAGS_DIR = _REPO / "configs" / "silver" / "dags"
RENDERED_DIR = DAGS_DIR / "_rendered"

GENERATED_BY = "scripts/silver/gen_sfn_inputs.py"

INVOCATION_FORMS = frozenset({"m", "s", "g"})
PUBLISH_MODES = frozenset({"shadow_canonical", "latest_only", "projected_canonical"})
PROMOTE_MODES = frozenset({"autonomous", "stop_and_notify", "post_publish_audit"})

# Store_true (valueless) option flags that MAY legitimately stand alone -- as a command's final
# token, or immediately before the next "--opt". Every OTHER "--opt" so positioned is a
# value-expecting option left dangling (the SFN container override passes the command verbatim, so a
# bare value-option makes the job's argparse exit 2 -- e.g. nass_task.py's ``--series`` with no
# value: "argument --series: expected one argument"). The lint below rejects that class fail-closed
# at render time so a truncated command can never reach the scheduler. Only add a flag here if it is
# genuinely store_true (NO value): a value-REQUIRED option (e.g. bronze_to_silver_esr_task's
# ``--vintage-mode {latest,all}``) must supply its value in the descriptor, never be whitelisted --
# whitelisting one is exactly the defect class this lint exists to catch.
_VALUELESS_TRAILING_FLAGS = frozenset({
    "--skip-existing-s3",   # fetch_usda_esr / fetch_usda_nass_citrus
    "--force-overwrite",    # yfinance_futures / gold_weather_z / nass_task
    "--current-season",     # fetch_usda_nass_citrus / fetch_unica_biweekly (season-scoped chain fetch, store_true)
    "--discover",           # fetch_unica_biweekly (enumerate bulletins via Playwright, store_true)
    "--reconcile-schema-widen",  # compact_weather_silver_task (F013 pure-widen partition-SD self-heal, store_true)
})

# --- Platform constants (NOT descriptor-driven; the scheduled thin contract is uniform) ---------
# The on-demand Fargate queue -- every Batch task + the gate run here. The descriptors' interruptible
# FARGATE_SPOT "leviathan-dev-queue" must never carry a scheduled canonical-publish task.
ONDEMAND_QUEUE = "leviathan-dev-queue-ondemand"
# The silver_rebuild_gate task (one gate jobdef for every family), invoked module-form.
GATE_JOBDEF = "leviathan-dev-silver-gate"
GATE_MODULE = "jobs.audit.silver_rebuild_gate"
# The promote leg's DEFAULT runner jobdef -- carries the silver-publisher role (jobRoleArn) + kms:Sign,
# so the rendered promote task needs no role field; the KMS approval mode + key travel in task.env.
PROMOTE_RUNNER_JOBDEF = "leviathan-dev-silver-publisher-runner"
KMS_KEY_ALIAS = "alias/leviathan-dev-publish-signer"

# OPTIONAL per-descriptor override of the promote runner. Read it as the answer to one question: does
# the promote leg run the SAME BUILD of the producer that the silver leg just ran?
#
# For every family whose producer lives in the shared b3-flat image, yes by construction -- the shared
# runner and the shared silver jobdef ride the same floating worker tag. For a family whose OWN silver
# jobdef is DIGEST-PINNED it is NO, and silently so: infra/terraform/modules/batch/main.tf pins
# futures-eod-silver to var.futures_eod_image_digest precisely because `databento` and `xlrd` are
# dependencies whose ABSENCE is silent, while leviathan-dev-silver-publisher-runner tracks whatever the
# last worker push produced. The machine re-running the identical command on the shared runner therefore
# promotes a shadow built by image A using image B.
#
# THE 2026-08-01 08:00Z DATABENTO PROMOTE IS THE PROOF: the silver phase ran the floor-fix image and
# published a clean shadow; the promote phase re-derived silver on the shared runner's OLDER image,
# certified 13/15 partitions and then exit-1'd on the two healthy-thin slugs (ZR, OJ) under the
# mode-blind row floor that image still carried. Certified-then-failed, after the write.
#
# THE ONLY LEGAL OVERRIDE IS SELF-PROMOTION: the value must be THE jobdef every shadow_canonical
# silver/gold publisher in this same descriptor already runs on. That is what keeps the two properties
# the shared runner otherwise supplies for free -- jobRoleArn=silver-publisher (glue:CreatePartition +
# kms:Sign) and a runnable copy of the producer -- because the silver phase re-proves both on that
# jobdef on every single fire. Naming any OTHER jobdef would be an unverified role/image claim, so
# lint_descriptor rejects it fail-closed.
PROMOTE_JOBDEF_FIELD = "promote_jobdef"

# Placeholders the scheduler / terraform substitute (never expanded here).
ASOF_PLACEHOLDER = "<aws.scheduler.scheduled-time>"          # the gate truncates the ISO to a date
SCHED_EXEC_ID = "<aws.scheduler.execution-id>"              # makes each fire's execution Name unique
STATE_MACHINE_ARN_PLACEHOLDER = "${state_machine_arn}"      # tf fills this in the schedule body

RENDERED_INPUT_SUFFIX = ".input.json"
RENDERED_SCHEDULE_SUFFIX = ".schedule.json"

# Fields every descriptor MUST carry (the lint rejects a missing one).
_REQUIRED_TOP = (
    "schedule", "family", "wave", "cron", "publish_class", "promote_mode", "auth_mode",
    "gate_tables", "gate_baseline_uri", "asof", "retry", "phases",
)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_descriptors(dags_dir: Path = DAGS_DIR) -> dict[str, dict]:
    """Load every top-level ``{schedule}.json`` descriptor.

    Skips the ``_rendered`` subdir (non-recursive glob) and the ``*.schema.json`` doc."""
    out: dict[str, dict] = {}
    for p in sorted(dags_dir.glob("*.json")):
        if p.name.endswith(".schema.json"):
            continue
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


# ---------------------------------------------------------------------------
# Lint (the schema/rule gate; plain asserts, no jsonschema runtime dep)
# ---------------------------------------------------------------------------
def lint_descriptor(desc: dict, stem: str) -> list[str]:
    """Return a (possibly empty) list of rule violations for one descriptor.

    Rejects: missing wave; missing/incomplete retry; missing cron; unknown invocation form; a
    module-form task not carrying '-m'; a CLASS-B family (retrofit_required, not yet landed) whose
    promote is autonomous; and other structural incoherence."""
    e: list[str] = []

    for k in _REQUIRED_TOP:
        if k not in desc:
            e.append(f"{stem}: missing required field '{k}'")

    # wave
    wave = desc.get("wave")
    if "wave" in desc and (not isinstance(wave, int) or isinstance(wave, bool) or wave not in (0, 1, 2, 3)):
        e.append(f"{stem}: wave must be an int in 0..3, got {wave!r}")

    # cron
    if not desc.get("cron"):
        e.append(f"{stem}: missing/empty 'cron'")

    # retry (an explicit block is mandatory -- omitting it re-inherits the EventBridge 185 default)
    retry = desc.get("retry") or {}
    if not isinstance(retry, dict) or "maximum_retry_attempts" not in retry \
            or "maximum_event_age_in_seconds" not in retry:
        e.append(f"{stem}: 'retry' must set maximum_retry_attempts + maximum_event_age_in_seconds")

    # identity / gate
    if desc.get("schedule") != stem:
        e.append(f"{stem}: schedule '{desc.get('schedule')}' != filename stem '{stem}'")
    if not desc.get("gate_tables"):
        e.append(f"{stem}: 'gate_tables' must be a non-empty list")
    if desc.get("promote_mode") not in PROMOTE_MODES:
        e.append(f"{stem}: unknown promote_mode {desc.get('promote_mode')!r}")

    # phases + tasks
    seen_ids: set[str] = set()
    for phase in desc.get("phases", []):
        pname = phase.get("name")
        if pname not in ("fetch", "bronze", "silver", "gold"):
            e.append(f"{stem}: unknown phase name {pname!r}")
        for t in phase.get("tasks", []):
            tid = t.get("id")
            if tid in seen_ids:
                e.append(f"{stem}: duplicate task id {tid!r}")
            seen_ids.add(tid)
            form = t.get("invocation_form")
            if form not in INVOCATION_FORMS:
                e.append(f"{stem}: task {tid!r} unknown invocation_form {form!r}")
                continue
            cmd = t.get("command", [])
            if form == "m":
                if t.get("integration") != "batch":
                    e.append(f"{stem}: module-form task {tid!r} must have integration=batch")
                if not cmd or cmd[0] != "-m":
                    e.append(f"{stem}: module-form task {tid!r} must carry '-m' as command[0]")
                elif len(cmd) < 2 or not cmd[1].startswith("jobs."):
                    e.append(f"{stem}: module-form task {tid!r} must name a jobs.* module at command[1]")
            elif form == "s":
                if t.get("integration") != "batch":
                    e.append(f"{stem}: script-form task {tid!r} must have integration=batch")
                if not cmd or not str(cmd[0]).endswith(".py"):
                    e.append(f"{stem}: script-form task {tid!r} command[0] must be a .py path")
            elif form == "g":
                if t.get("integration") != "glue":
                    e.append(f"{stem}: glue-form task {tid!r} must have integration=glue")
                if not t.get("glue_job"):
                    e.append(f"{stem}: glue-form task {tid!r} must set 'glue_job'")
                if t.get("jobdef"):
                    e.append(f"{stem}: glue-form task {tid!r} must not set 'jobdef'")
            # A value-expecting option must be followed by its value. A "--opt" token that is the
            # command's LAST token, OR is immediately followed by another "--opt" token, has no
            # value: the SFN container override is passed verbatim, so the job's argparse exits 2
            # ("expected one argument"). Known store_true flags are exempt. The trailing case is the
            # historically-observed defect (esr --vintage-mode dangling value, nass --series); the
            # mid-command case generalizes it (a value silently dropped between two flags).
            for i, tok in enumerate(cmd):
                if not (isinstance(tok, str) and tok.startswith("--")
                        and tok not in _VALUELESS_TRAILING_FLAGS):
                    continue
                nxt = cmd[i + 1] if i + 1 < len(cmd) else None
                if nxt is None:
                    e.append(
                        f"{stem}: task {tid!r} command ends on value-expecting option {tok!r} "
                        f"with no value (dangling arg -> argparse exit 2)"
                    )
                elif isinstance(nxt, str) and nxt.startswith("--"):
                    e.append(
                        f"{stem}: task {tid!r} command has value-expecting option {tok!r} "
                        f"immediately followed by another option {nxt!r} (missing value -> "
                        f"argparse exit 2)"
                    )

            # publishing tasks must declare a known publish_mode
            if t.get("publishes"):
                pm = t.get("publish_mode")
                if pm not in PUBLISH_MODES:
                    e.append(f"{stem}: publishing task {tid!r} has unknown publish_mode {pm!r}")

    # promote_jobdef override: SELF-PROMOTION ONLY (see the constant's rationale).
    if PROMOTE_JOBDEF_FIELD in desc:
        pj = desc.get(PROMOTE_JOBDEF_FIELD)
        if not isinstance(pj, str) or not pj:
            e.append(f"{stem}: '{PROMOTE_JOBDEF_FIELD}' must be a non-empty string, got {pj!r}")
        elif _is_versioned(pj):
            e.append(
                f"{stem}: '{PROMOTE_JOBDEF_FIELD}' {pj!r} carries a ':N' revision -- the promote leg "
                f"tracks the latest ACTIVE revision like every other rendered jobdef"
            )
        else:
            own = _shadow_canonical_jobdefs(desc)
            if not own:
                e.append(
                    f"{stem}: '{PROMOTE_JOBDEF_FIELD}' is set but the descriptor has no "
                    f"shadow_canonical publisher -- nothing promotes, so the override is dead config"
                )
            elif pj != PROMOTE_RUNNER_JOBDEF and own != {pj}:
                e.append(
                    f"{stem}: '{PROMOTE_JOBDEF_FIELD}' {pj!r} is neither the platform runner "
                    f"{PROMOTE_RUNNER_JOBDEF!r} nor THE single jobdef this descriptor's "
                    f"shadow_canonical publishers run on ({sorted(own)}) -- a promote may only re-run "
                    f"on the jobdef that produced the shadow (role + image parity)"
                )

    # CLASS-B autonomous-promote-before-retrofit (the A-W4 guard)
    if desc.get("retrofit_required") and not desc.get("retrofit_landed") \
            and desc.get("promote_mode") == "autonomous":
        e.append(
            f"{stem}: CLASS-B family enables autonomous promote before the A-W4 retrofit landed "
            f"(retrofit_required=true, retrofit_landed=false, promote_mode=autonomous)"
        )

    return e


def lint_all(descriptors: dict[str, dict]) -> list[str]:
    out: list[str] = []
    for stem, desc in sorted(descriptors.items()):
        out.extend(lint_descriptor(desc, stem))
    return out


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def _is_versioned(jobdef: str) -> bool:
    """True when ``jobdef`` carries a trailing ``:N`` Batch revision suffix."""
    _head, sep, tail = str(jobdef).rpartition(":")
    return bool(sep and tail.isdigit())


def _unversion(jobdef: str) -> str:
    """Strip a trailing ``:N`` revision so the schedule tracks the latest ACTIVE jobdef revision.

    ``leviathan-dev-b3-flat-silver:4`` -> ``leviathan-dev-b3-flat-silver``. A name with no numeric
    revision suffix (``leviathan-dev-silver-gate``) is returned unchanged; per-family jobdefs like
    ``leviathan-dev-mpob-silver:1`` are kept, just unversioned."""
    if not jobdef:
        return jobdef
    head, sep, tail = jobdef.rpartition(":")
    return head if (sep and tail.isdigit()) else jobdef


def _shadow_canonical_jobdefs(desc: dict) -> set[str]:
    """The UNVERSIONED jobdefs this descriptor's shadow_canonical silver/gold publishers run on.

    These are exactly the tasks the promote leg re-runs, so this set is the allowlist a
    ``promote_jobdef`` self-promotion override is checked against."""
    out: set[str] = set()
    for phase in desc.get("phases", []) or []:
        if phase.get("name") not in ("silver", "gold"):
            continue
        for t in phase.get("tasks", []) or []:
            if t.get("publishes") and t.get("publish_mode") == "shadow_canonical" and t.get("jobdef"):
                out.add(_unversion(t["jobdef"]))
    return out


def promote_jobdef(desc: dict) -> str:
    """The jobdef the promote leg runs on: the descriptor's self-promotion override, else the shared
    platform runner. ``lint_descriptor`` has already fenced the override to a jobdef this descriptor's
    own shadow_canonical publishers run on, so an unlinted descriptor can never reach here."""
    return _unversion(desc.get(PROMOTE_JOBDEF_FIELD) or PROMOTE_RUNNER_JOBDEF)


def _env_list(env) -> list[dict]:
    """Batch ContainerOverrides.Environment shape: a LIST of ``{Name, Value}`` -- never ``{}``.

    The machine reads ``$.task.env`` as this list; an object crashes the item. Accepts a descriptor
    ``{}``/``{K: V}`` (converted, key-sorted) or an already-rendered list; empty -> ``[]``."""
    if not env:
        return []
    if isinstance(env, list):
        return [{"Name": e["Name"], "Value": e["Value"]} for e in env]
    return [{"Name": k, "Value": v} for k, v in sorted(env.items())]


def _render_task(t: dict, *, publish_stage: str | None = None) -> dict:
    """Render one descriptor phase task into an SFN Map-item task (Batch or Glue).

    ``publish_stage`` ('shadow') is appended as ``--publish-mode <stage>`` ONLY for a shadow_canonical
    Batch publisher (latest_only / projected_canonical never take the flag; Glue never does)."""
    if t["integration"] == "glue":
        # Glue branch reads $.task.glue_job + $.task.arguments (a MISSING arguments path errors the
        # startJobRun Map item) -- so always emit arguments, defaulting to an empty map.
        return {
            "integration": "glue",
            "glue_job": t["glue_job"],
            "arguments": dict(t.get("arguments", {})),
        }
    cmd = list(t.get("command", []))
    if publish_stage and t.get("publishes") and t.get("publish_mode") == "shadow_canonical":
        cmd = cmd + ["--publish-mode", publish_stage]
    return {
        "integration": "batch",
        "jobdef": _unversion(t["jobdef"]),
        "queue": ONDEMAND_QUEUE,
        "command": cmd,
        "env": _env_list(t.get("env")),
    }


def _render_promote_task(desc: dict, t: dict) -> dict:
    """A shadow_canonical publisher's canonical re-run: the same command + ``--publish-mode canonical``
    under the promote jobdef (the shared silver-publisher-runner, or the descriptor's ``promote_jobdef``
    self-promotion override), carrying the KMS approval env pair. No ``role`` field -- both legal promote
    jobdefs bind jobRoleArn=silver-publisher (the machine reads no $.task.role)."""
    return {
        "integration": "batch",
        "jobdef": promote_jobdef(desc),
        "queue": ONDEMAND_QUEUE,
        "command": list(t.get("command", [])) + ["--publish-mode", "canonical"],
        "env": [
            {"Name": "LEVIATHAN_APPROVAL_MODE", "Value": desc["auth_mode"]},
            {"Name": "LEVIATHAN_KMS_KEY_ID", "Value": KMS_KEY_ALIAS},
        ],
    }


def _render_gate(desc: dict) -> dict:
    """The silver_rebuild_gate task block ($.gate). Platform-fixed jobdef/queue + module-form command;
    --tables is the comma-joined gate_tables, --asof is the scheduler placeholder (truncated to a date
    by the gate), --baseline-uri is the rolling per-schedule census."""
    return {
        "jobdef": GATE_JOBDEF,
        "queue": ONDEMAND_QUEUE,
        "command": [
            "-m", GATE_MODULE,
            "--tables", ",".join(desc["gate_tables"]),
            "--asof", ASOF_PLACEHOLDER,
            "--baseline-uri", desc["gate_baseline_uri"],
        ],
    }


def render_input(desc: dict) -> dict:
    """Render one descriptor into its A-W2 SFN execution-input JSON (object-keyed phases + gate)."""
    promote_mode = desc.get("promote_mode", "autonomous")

    # Bucket descriptor phases by name. The machine has fetch/bronze/silver Maps + no Gold Map, so a
    # 'gold' phase folds into 'silver' (its tasks run in the silver Map, ordered after the silver ones).
    by_name: dict[str, list] = {}
    for phase in desc.get("phases", []):
        by_name.setdefault(phase["name"], []).extend(phase.get("tasks", []))
    silver_src = list(by_name.get("silver", [])) + list(by_name.get("gold", []))

    phases_out = {
        "fetch": {"tasks": [_render_task(t) for t in by_name.get("fetch", [])]},
        "bronze": {"tasks": [_render_task(t) for t in by_name.get("bronze", [])]},
        "silver": {"tasks": [_render_task(t, publish_stage="shadow") for t in silver_src]},
    }

    # Only an autonomous family self-promotes (held stop_and_notify + post_publish_audit do not re-run
    # a canonical leg from the machine). Each shadow_canonical silver/gold publisher promotes once.
    promote_tasks: list[dict] = []
    if promote_mode == "autonomous":
        promote_tasks = [
            _render_promote_task(desc, t)
            for t in silver_src
            if t.get("publishes") and t.get("publish_mode") == "shadow_canonical"
        ]

    return {
        "family": desc["family"],
        "asof": ASOF_PLACEHOLDER,
        "auth_mode": desc["auth_mode"],
        "gate_tables": list(desc["gate_tables"]),
        "gate_baseline_uri": desc["gate_baseline_uri"],
        "phases": phases_out,
        "gate": _render_gate(desc),
        "promote": {"mode": promote_mode, "tasks": promote_tasks},
    }


def render_schedule(desc: dict) -> dict:
    """Render the FULL StartExecution body for a family's scheduler target (``--render-schedule``).

    StateMachineArn is the ${state_machine_arn} tf placeholder; Name carries the execution-id context
    attribute (unique per fire -> at-least-once double-fires collide into ExecutionAlreadyExists); Input
    is the execution-input JSON as an escaped string (compact, key-sorted)."""
    exec_input = render_input(desc)
    return {
        "StateMachineArn": STATE_MACHINE_ARN_PLACEHOLDER,
        "Name": f"{desc['family']}-sched-{SCHED_EXEC_ID}",
        "Input": json.dumps(exec_input, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    }


def _dump_json(obj: dict) -> str:
    """Canonical, byte-stable JSON: 2-space indent, sorted keys, ASCII-only, trailing newline."""
    return json.dumps(obj, indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def render_all(descriptors: dict[str, dict]) -> dict[str, str]:
    return {stem: _dump_json(render_input(desc)) for stem, desc in sorted(descriptors.items())}


def render_all_schedules(descriptors: dict[str, dict]) -> dict[str, str]:
    return {stem: _dump_json(render_schedule(desc)) for stem, desc in sorted(descriptors.items())}


def scan_unresolved_placeholders(descriptors: dict[str, dict]) -> list[str]:
    """FATAL lint: descriptor command args carrying an unresolved ``${...}`` template var.

    The scheduler only substitutes ``<aws.scheduler.*>`` context attributes, so a literal ``${X}`` in a
    command reaches the job UNRESOLVED (the job's argparse sees the literal string ``${RUN_ID}``, never
    a run id). ``generate()`` folds a non-empty result into the exit-2 lint gate (render AND --check),
    fail-closed, so a command with an unsubstitutable placeholder can never reach the scheduler."""
    import re
    pat = re.compile(r"\$\{[^}]+\}")
    out: list[str] = []
    for stem, desc in sorted(descriptors.items()):
        for phase in desc.get("phases", []):
            for t in phase.get("tasks", []):
                hits = [a for a in t.get("command", []) if isinstance(a, str) and pat.search(a)]
                if hits:
                    out.append(f"{stem}/{t.get('id')}: command carries unresolved placeholder(s) {hits}")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def generate(check: bool = False, render_schedule: bool = False) -> int:
    descriptors = load_descriptors()
    if not descriptors:
        print(f"no descriptors under {DAGS_DIR}", file=sys.stderr)
        return 4

    # The unresolved-placeholder scan is a FATAL lint (folded into the exit-2 gate below), NOT an
    # advisory: a command carrying a literal ${...} the scheduler cannot substitute reaches the job's
    # argparse verbatim. This gates BOTH render and --check paths (generate() returns before either).
    violations = lint_all(descriptors)
    unresolved = scan_unresolved_placeholders(descriptors)
    if violations or unresolved:
        print("DESCRIPTOR LINT FAILED:")
        for v in violations:
            print(f"  - {v}")
        for u in unresolved:
            print(f"  - unresolved placeholder: {u}")
        return 2

    if render_schedule:
        rendered = render_all_schedules(descriptors)
        suffix, label = RENDERED_SCHEDULE_SUFFIX, "StartExecution bodies"
    else:
        rendered = render_all(descriptors)
        suffix, label = RENDERED_INPUT_SUFFIX, "SFN inputs"

    if check:
        drift = []
        for stem, text in rendered.items():
            existing = RENDERED_DIR / f"{stem}{suffix}"
            if not existing.exists() or existing.read_text(encoding="utf-8") != text:
                drift.append(stem)
        if drift:
            print(f"RENDERED DRIFT ({suffix}, regenerate): " + ", ".join(sorted(drift)))
            return 3
        print(f"sfn-{'schedule' if render_schedule else 'input'} check OK: "
              f"{len(rendered)} {label} byte-identical (lint clean)")
        return 0

    RENDERED_DIR.mkdir(parents=True, exist_ok=True)
    for stem, text in rendered.items():
        (RENDERED_DIR / f"{stem}{suffix}").write_text(text, encoding="utf-8")
    print(f"wrote {len(rendered)} rendered {label} to {RENDERED_DIR} (lint clean)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="render to a buffer and fail (exit 3) if it differs from the checked-in tree")
    ap.add_argument("--render-schedule", action="store_true",
                    help="emit the {schedule}.schedule.json StartExecution bodies instead of .input.json")
    args = ap.parse_args()
    return generate(check=args.check, render_schedule=args.render_schedule)


if __name__ == "__main__":
    raise SystemExit(main())
