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
runner`` (which carries the silver-publisher role + kms:Sign) with the KMS approval env pair.

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

# Store_true (valueless) option flags that MAY legitimately appear as a command's final token.
# Every OTHER trailing "--opt" token is a value-expecting option left dangling (the SFN container
# override passes the command verbatim, so a bare value-option makes the job's argparse exit 2 --
# e.g. nass_task.py's ``--series`` with no value: "argument --series: expected one argument").
# The lint below rejects that class fail-closed at render time so a truncated command can never
# reach the scheduler. New store_true flags used in a descriptor tail are added here.
_VALUELESS_TRAILING_FLAGS = frozenset({
    "--skip-existing-s3",   # fetch_usda_esr
    "--vintage-mode",       # bronze_to_silver_esr_task
    "--force-overwrite",    # yfinance_futures / gold_weather_z / nass_task
})

# --- Platform constants (NOT descriptor-driven; the scheduled thin contract is uniform) ---------
# The on-demand Fargate queue -- every Batch task + the gate run here. The descriptors' interruptible
# FARGATE_SPOT "leviathan-dev-queue" must never carry a scheduled canonical-publish task.
ONDEMAND_QUEUE = "leviathan-dev-queue-ondemand"
# The silver_rebuild_gate task (one gate jobdef for every family), invoked module-form.
GATE_JOBDEF = "leviathan-dev-silver-gate"
GATE_MODULE = "jobs.audit.silver_rebuild_gate"
# The promote leg's runner jobdef -- carries the silver-publisher role (jobRoleArn) + kms:Sign, so the
# rendered promote task needs no role field; the KMS approval mode + key travel in task.env.
PROMOTE_RUNNER_JOBDEF = "leviathan-dev-silver-publisher-runner"
KMS_KEY_ALIAS = "alias/leviathan-dev-publish-signer"

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
            # A command must not END on a value-expecting option flag (dangling value): the SFN
            # container override is passed verbatim, so a bare "--opt" makes the job's argparse
            # exit 2 ("expected one argument"). Known store_true flags are exempt.
            if cmd and isinstance(cmd[-1], str) and cmd[-1].startswith("--") \
                    and cmd[-1] not in _VALUELESS_TRAILING_FLAGS:
                e.append(
                    f"{stem}: task {tid!r} command ends on value-expecting option {cmd[-1]!r} "
                    f"with no value (dangling arg -> argparse exit 2)"
                )

            # publishing tasks must declare a known publish_mode
            if t.get("publishes"):
                pm = t.get("publish_mode")
                if pm not in PUBLISH_MODES:
                    e.append(f"{stem}: publishing task {tid!r} has unknown publish_mode {pm!r}")

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
def _unversion(jobdef: str) -> str:
    """Strip a trailing ``:N`` revision so the schedule tracks the latest ACTIVE jobdef revision.

    ``leviathan-dev-b3-flat-silver:4`` -> ``leviathan-dev-b3-flat-silver``. A name with no numeric
    revision suffix (``leviathan-dev-silver-gate``) is returned unchanged; per-family jobdefs like
    ``leviathan-dev-mpob-silver:1`` are kept, just unversioned."""
    if not jobdef:
        return jobdef
    head, sep, tail = jobdef.rpartition(":")
    return head if (sep and tail.isdigit()) else jobdef


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
    under the silver-publisher-runner jobdef, carrying the KMS approval env pair. No ``role`` field --
    the runner jobdef already binds jobRoleArn=silver-publisher (the machine reads no $.task.role)."""
    return {
        "integration": "batch",
        "jobdef": PROMOTE_RUNNER_JOBDEF,
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
    """Non-fatal advisory: descriptor command args carrying an unresolved ``${...}`` template var.

    The scheduler only substitutes ``<aws.scheduler.*>`` context attributes, so a literal ``${X}`` in a
    command reaches the job UNRESOLVED. Reported (not lint-failed) so the input tree still renders."""
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

    violations = lint_all(descriptors)
    if violations:
        print("DESCRIPTOR LINT FAILED:")
        for v in violations:
            print(f"  - {v}")
        return 2

    # Non-fatal advisory (does not gate rendering): unresolved ${...} command placeholders.
    for warn in scan_unresolved_placeholders(descriptors):
        print(f"WARN {warn}", file=sys.stderr)

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
