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
A-W2 schema::

    { family, phases[], gate_tables, asof, gate_baseline_uri, promote, auth_mode }

The scheduler's ``Input=`` is thus reproducible from the descriptors, never hand-typed. Rendered
inputs are written under ``configs/silver/dags/_rendered/{schedule}.input.json``.

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

Usage:  python scripts/silver/gen_sfn_inputs.py [--check]
  --check : render to a buffer and fail (exit 3) if it differs from the checked-in rendered tree.
            Also runs the descriptor lint (exit 2 on any violation) in both modes.
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
SILVER_STAGE_PHASES = frozenset({"silver", "gold"})
SILVER_PUBLISHER_ROLE = "leviathan-dev-silver-publisher"

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
def _render_task(t: dict, *, publish_stage: str | None = None, role: str | None = None) -> dict:
    """Render one descriptor task into an SFN Map-item task.

    ``publish_stage`` ('shadow'|'canonical') is appended as ``--publish-mode <stage>`` ONLY for a
    shadow_canonical publisher; ``role`` (silver-publisher) is attached on the promote copy."""
    out: dict = {"integration": t["integration"]}
    if t["integration"] == "glue":
        out["glue_job"] = t["glue_job"]
    else:
        out["jobdef"] = t["jobdef"]
        out["queue"] = t.get("queue")
    cmd = list(t.get("command", []))
    if publish_stage and t.get("publishes") and t.get("publish_mode") == "shadow_canonical":
        cmd = cmd + ["--publish-mode", publish_stage]
    out["command"] = cmd
    out["env"] = dict(t.get("env", {}))
    if role:
        out["role"] = role
    return out


def render_input(desc: dict) -> dict:
    """Render one descriptor into its A-W2 SFN execution-input JSON."""
    promote_mode = desc.get("promote_mode", "autonomous")
    phases_out: list[dict] = []
    promote_tasks: list[dict] = []
    for phase in desc.get("phases", []):
        pname = phase["name"]
        stage = "shadow" if pname in SILVER_STAGE_PHASES else None
        tasks_out = []
        for t in phase.get("tasks", []):
            tasks_out.append(_render_task(t, publish_stage=stage))
            if pname in SILVER_STAGE_PHASES and t.get("publishes") \
                    and t.get("publish_mode") == "shadow_canonical":
                promote_tasks.append(
                    _render_task(t, publish_stage="canonical", role=SILVER_PUBLISHER_ROLE)
                )
        phases_out.append({"name": pname, "tasks": tasks_out})

    # only an autonomous family self-promotes; held (stop_and_notify) + post_publish_audit do not
    # re-run a canonical publish leg from the machine.
    if promote_mode != "autonomous":
        promote_tasks = []

    return {
        "family": desc["family"],
        "phases": phases_out,
        "gate_tables": list(desc["gate_tables"]),
        "asof": desc.get("asof", "${ASOF}"),
        "gate_baseline_uri": desc["gate_baseline_uri"],
        "promote": {"mode": promote_mode, "tasks": promote_tasks},
        "auth_mode": desc["auth_mode"],
    }


def _dump_json(obj: dict) -> str:
    """Canonical, byte-stable JSON: 2-space indent, sorted keys, ASCII-only, trailing newline."""
    return json.dumps(obj, indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def render_all(descriptors: dict[str, dict]) -> dict[str, str]:
    return {stem: _dump_json(render_input(desc)) for stem, desc in sorted(descriptors.items())}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def generate(check: bool = False) -> int:
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

    rendered = render_all(descriptors)

    if check:
        drift = []
        for stem, text in rendered.items():
            existing = RENDERED_DIR / f"{stem}.input.json"
            if not existing.exists() or existing.read_text(encoding="utf-8") != text:
                drift.append(stem)
        if drift:
            print("RENDERED-INPUT DRIFT (regenerate): " + ", ".join(sorted(drift)))
            return 3
        print(f"sfn-input check OK: {len(rendered)} inputs byte-identical (lint clean)")
        return 0

    RENDERED_DIR.mkdir(parents=True, exist_ok=True)
    for stem, text in rendered.items():
        (RENDERED_DIR / f"{stem}.input.json").write_text(text, encoding="utf-8")
    print(f"wrote {len(rendered)} rendered SFN inputs to {RENDERED_DIR} (lint clean)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="render to a buffer and fail (exit 3) if it differs from the checked-in tree")
    args = ap.parse_args()
    return generate(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
