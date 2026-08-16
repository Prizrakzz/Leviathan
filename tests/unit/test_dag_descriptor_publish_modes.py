"""D-SG G2-1 -- the bare-command / stale-descriptor class, pinned.

Two silent no-ops of the same shape have now been measured a month apart:

  * fgis (fixed 2026-07-23) -- ``jobs/batch/fgis_silver_task.py`` scheduled BARE,
    and the script defaults ``--publish-mode`` to ``dry-run``: canonical stayed
    frozen while every fire exited 0.
  * unica biweekly (fixed here) -- ``jobs/batch/unica_biweekly_silver_task.py``
    scheduled BARE for the same reason; three tables were never written by the
    schedule in ANY mode (2026-08-12 log: "mode=dry-run").

The flag is not always the descriptor's job. ``gen_sfn_inputs._render_task``
appends ``--publish-mode shadow`` to a publisher whose ``publish_mode`` is
``shadow_canonical``, and to no other kind. So the real contract is:

    every publishing silver/gold task must reach Batch with EXACTLY ONE
    ``--publish-mode``, whoever supplies it.

That single statement catches both failure directions -- the bare latest_only
publisher that silently dry-runs, and a descriptor that hand-writes the flag onto
a shadow_canonical task the renderer will flag again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "silver"))

import gen_dag_schedules_tfvars as T  # noqa: E402  (path-injected, no package)
import gen_sfn_inputs as G  # noqa: E402

# Publishers scheduled BARE whose task script defaults --publish-mode to dry-run,
# i.e. schedules that currently write NOTHING. Each entry is a live defect that is
# outside the D-SG G2-1 slice; the set may only ever SHRINK.
KNOWN_DRY_RUN_PUBLISHERS = {
    ("food_cpi", "food_cpi"),  # food_cpi_task.py:221 default="dry-run"; D-SG names it, W4 owns it
}


def _descriptors() -> dict[str, dict]:
    return G.load_descriptors()


def _rendered_silver_tasks(desc: dict) -> list[dict]:
    """The silver-phase tasks as the state machine will actually receive them."""
    return json.loads(json.dumps(G.render_input(desc)))["phases"]["silver"]["tasks"]


def _publishing_silver_tasks(desc: dict) -> list[dict]:
    src: list[dict] = []
    for phase in desc.get("phases", []):
        if phase["name"] in ("silver", "gold"):
            src.extend(phase.get("tasks", []))
    return src


def _defaults_to_dry_run(command: list[str]) -> bool:
    """True when the task script declares --publish-mode with a dry-run default.

    Read from the script itself, not a hand-kept list: a producer that has no
    --publish-mode at all (the weather bronze->silver legs) publishes
    unconditionally and a bare command is correct for it.
    """
    if not command:
        return False
    script = _REPO / command[0]
    if not script.is_file():
        return False
    text = script.read_text(encoding="utf-8")
    return '"--publish-mode", default="dry-run"' in text


@pytest.mark.parametrize("stem", sorted(_descriptors()))
def test_rendered_silver_commands_carry_at_most_one_publish_mode(stem):
    """A doubled flag is as broken as a missing one -- argparse takes the last win silently."""
    for task in _rendered_silver_tasks(_descriptors()[stem]):
        if task["integration"] != "batch":
            continue
        assert task["command"].count("--publish-mode") <= 1, (
            f"{stem}: rendered command {task['command']} repeats --publish-mode. "
            "shadow_canonical publishers get the flag from gen_sfn_inputs._render_task; "
            "do not also write it into the descriptor."
        )


def test_every_publishing_silver_task_declares_publish_mode():
    """Every dry-run-defaulting publisher reaches Batch with an explicit mode."""
    offenders = []
    for stem, desc in _descriptors().items():
        for task, cmd in zip(_publishing_silver_tasks(desc), _rendered_silver_tasks(desc)):
            if not task.get("publishes") or cmd["integration"] != "batch":
                continue
            if "--publish-mode" in cmd["command"]:
                continue
            if not _defaults_to_dry_run(cmd["command"]):
                continue
            if (stem, task["id"]) in KNOWN_DRY_RUN_PUBLISHERS:
                continue
            # cot / futures_prices are HAND_ARMED: the live tfvars carries the flag
            # while the descriptor must stay latest_only for the Wave-2 CLASS-B invariant.
            if stem in T.HAND_ARMED:
                continue
            offenders.append(f"{stem}.{task['id']} ({task.get('publish_mode')})")

    assert not offenders, (
        "publishing silver tasks scheduled with no --publish-mode against a script whose "
        f"default is dry-run -- these schedules write NOTHING, in any mode: {offenders}"
    )


def test_unica_biweekly_silver_is_no_longer_bare():
    """The exact 2026-08-12 regression: latest_only, so the renderer supplies nothing."""
    desc = _descriptors()["unica"]
    task = next(
        t for t in _publishing_silver_tasks(desc) if t["id"] == "unica_biweekly_silver"
    )
    assert task["publish_mode"] == "latest_only"
    assert task["command"][-2:] == ["--publish-mode", "shadow"]


def test_unica_annual_leg_leaves_the_flag_to_the_renderer():
    """It is shadow_canonical: the descriptor stays bare and the renderer adds the flag."""
    desc = _descriptors()["unica"]
    task = next(
        t for t in _publishing_silver_tasks(desc) if t["id"] == "unica_annual_state"
    )
    assert task["publish_mode"] == "shadow_canonical"
    assert "--publish-mode" not in task["command"]

    rendered = _rendered_silver_tasks(desc)[0]
    assert rendered["command"][-2:] == ["--publish-mode", "shadow"]


# ---------------------------------------------------------------------------
# descriptor <-> tfvars drift
# ---------------------------------------------------------------------------

# Schedules whose committed descriptor has moved AHEAD of the armed tfvars and are
# waiting on the hand-merge (the tfvars is never regenerated wholesale -- render to
# scratch, diff, hand-merge only the entries being changed). Every entry is a live
# schedule that has NOT yet received its fix. Empty it as the merges land.
PENDING_HAND_MERGE = {
    "unica",               # D-SG G2-1(a): fetch --through-current-season + biweekly --publish-mode
    "pink_sheet_monthly",  # D-SG G2-1(c): fetch --skip-existing-s3 --asof; cron 4th -> 8th (D23)
    "food_cpi",            # D-SG D23: cron 4th -> 8th, riding pink_sheet's fire minute
    "wasde_monthly",       # D-SG G1-2 (separate slice): fetch/silver window arguments
    "psd_monthly",         # D-SG G1-1a: silver+promote legs repointed to leviathan-dev-psd-silver
}


def test_descriptor_tfvars_assembly_has_no_violations():
    """Fail-closed set arithmetic: no unarmed descriptor, no orphan entry, no dead hold."""
    _obj, _changes, violations = T.assemble()
    assert violations == []


def test_descriptor_matches_rendered_tfvars():
    """No schedule silently drifts from its descriptor outside the declared merge queue."""
    _obj, changes, _violations = T.assemble()
    drifting = {line.split(":", 1)[0] for line in changes}
    assert drifting <= PENDING_HAND_MERGE, (
        f"schedules drifting from their descriptors with no declared merge: "
        f"{sorted(drifting - PENDING_HAND_MERGE)}"
    )
