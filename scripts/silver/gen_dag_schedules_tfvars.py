#!/usr/bin/env python
"""Assemble ``infra/terraform/envs/dev/dag_schedules.auto.tfvars.json`` from the committed DAG
descriptors, WITHOUT reverting the entries that diverge from them on purpose.

WHY THIS SCRIPT EXISTS, STATED AS THE FAILURE IT PREVENTS
---------------------------------------------------------
``scripts/silver/gen_sfn_inputs.py --render-schedule`` is the house generator: it renders every
descriptor into ``configs/silver/dags/_rendered/{schedule}.schedule.json``, the full StartExecution
body a terraform schedule entry carries. That step has always been mechanical. The step AFTER it --
folding those bodies into the terraform tfvars -- never was: the tfvars was hand-assembled, entry by
entry, across a dozen commits.

Measured 2026-08-04, the two trees had drifted in FOUR places, and only ONE of them is a bug:

  * ``futures_eod_databento`` / ``futures_eod_free`` -- the tfvars promote leg still names
    ``leviathan-dev-silver-publisher-runner`` while the descriptors carry the
    ``promote_jobdef`` SELF-PROMOTION override (``leviathan-dev-futures-eod-silver``). This is the
    2026-08-01 08:00Z databento defect, unfixed in the only place that arms a fire: the silver leg
    publishes a shadow from the digest-pinned futures image, then the promote leg re-derives it on
    the shared runner's OLDER image and exit-1s after the write. **This is the fix that must reach
    the live schedules.**

  * ``cot`` / ``futures_prices`` -- the tfvars is HAND-ARMED to the shadow-first shape (silver leg
    carries ``--publish-mode shadow``; a canonical promote task exists) while the descriptors still
    declare ``publish_mode: latest_only`` and ``promote_mode: stop_and_notify``. **That divergence
    is deliberate and load-bearing**: ``futures_prices.json``'s own notes say the entry is
    hand-armed, and the descriptors cannot be updated to match because
    ``test_wave2_is_exactly_the_classb_set`` binds both families to the
    retrofit_required-and-not-landed set. A naive full regeneration DISARMS both -- it strips
    ``--publish-mode shadow`` from two live silver legs and deletes cot's canonical promote, which
    was ratified by the user in commit d46716cf. That is a silent live-behaviour regression riding
    inside a "regenerate the config" step.

  * ``production_faostat`` -- a descriptor with no tfvars entry, i.e. a family that is deliberately
    NOT armed. A naive regeneration CREATES a live EventBridge schedule for it.

So: the tfvars is descriptor-derived for most families and deliberately not for three. This script
makes that statement mechanical, declared and enforced instead of tribal.

WHAT IT DOES
------------
1. Renders every descriptor through the house generator (``gen_sfn_inputs.render_schedule``), so the
   descriptor lint and the unresolved-``${...}``-placeholder scan gate this path too.
2. For each entry already in the tfvars, compares the rendered body to the incumbent one
   SEMANTICALLY (parsed JSON equality on the decoded ``Input``, ``Name`` and ``StateMachineArn``).
3. Rewrites an entry ONLY when the semantics differ -- and only when the stem is not on a HOLD list.
   An entry whose semantics already match keeps its incumbent BYTES.

Point 3's second half is the blast-radius rule and it is not cosmetic. 15 of the 25 incumbent entries
were serialised with json's default ``", "``/``": "`` separators rather than the compact form; the
``input_json`` string is what EventBridge Scheduler stores verbatim, so re-serialising a
semantically-identical entry is still a live schedule UPDATE. Canonicalising all of them would turn a
two-schedule fix into a twenty-five-schedule apply for zero behavioural gain. Pass ``--rewrite-all``
to canonicalise deliberately; do not pass it by reflex.

THE HOLD LISTS ARE FAIL-CLOSED
------------------------------
``HAND_ARMED`` entries are preserved verbatim AND their divergence is asserted to still exist -- if a
descriptor ever catches up, the hold is dead config and this script says so rather than silently
holding nothing. ``NOT_ARMED`` stems are asserted ABSENT from the tfvars. A descriptor that is
neither armed nor on a list is an ERROR, not a create: arming a family is a deliberate act with a
day-0 review, never a side effect of running a generator.

Usage:
  python scripts/silver/gen_dag_schedules_tfvars.py            write the tfvars
  python scripts/silver/gen_dag_schedules_tfvars.py --check    exit 3 if the tfvars would change
  python scripts/silver/gen_dag_schedules_tfvars.py --diff     print the classified diff, write nothing
  python scripts/silver/gen_dag_schedules_tfvars.py --rewrite-all
                                                               also canonicalise byte-equal entries

Exit codes mirror the house generator: 0 ok, 2 lint/hold violation, 3 drift (--check), 4 no input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "silver"))

import gen_sfn_inputs as G  # noqa: E402  (path-injected sibling; this file has no package)

TFVARS = _REPO / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"

# --- The two hold lists. Every membership here is a decision with a citation. -----------------

# Entries whose tfvars shape DELIBERATELY diverges from their descriptor. Preserved verbatim.
#
# Both are CLASS-B families mid-retrofit: the descriptor must keep publish_mode=latest_only /
# promote_mode=stop_and_notify (test_wave2_is_exactly_the_classb_set binds them to the
# retrofit_required-and-not-landed set), while the ARMED entry is shadow-first because the
# retrofit landed in the worker image. The descriptor is the CLASS declaration; the tfvars is the
# live arm; they are allowed to disagree while the retrofit is in flight, and the day the
# retrofit is declared landed is the day this hold is removed -- not before.
HAND_ARMED: dict[str, str] = {
    "cot": (
        "shadow-first arm ratified 2026-07-22 (commit d46716cf: 'arm autonomous canonical "
        "promote'); descriptor stays latest_only/stop_and_notify for the Wave-2 CLASS-B invariant"
    ),
    "mpob": (
        "IMAGE GATE (D-LD MPOB retrofit 2026-08-18, review wf_051e926a confirmed): the descriptor's "
        "fetch command carries --refresh-manifest but the digest-pinned b3-flat-silver image still "
        "bakes the OLD fetch_mpob.py, whose argparse exits 2 on the unknown flag -- terminal after "
        "ONE attempt per the F1 probe (cb151695), reddening all three monthly fires. The live arm "
        "stays flag-less until the worker image carrying the new parser is built, pushed and "
        "registered as a new b3-flat-silver revision; remove this hold in that SAME change "
        "(variables.tf:278 pin-collision law)"
    ),
    "futures_prices": (
        "shadow-first arm per futures_prices.json's own notes ('the dag_schedules.auto.tfvars.json "
        "futures_prices entry is hand-armed to the shadow-first shape'); A-W4 retrofit landed in the "
        "worker image while retrofit_landed stays FALSE deliberately"
    ),
}

# Descriptors that exist but are DELIBERATELY not armed as a live schedule.
NOT_ARMED: dict[str, str] = {
    # production_faostat ARMED 2026-08-18 (D-LD Track 2 #2, owner-ratified "do the remaining
    # tracks"): the hold's own condition was met -- a deliberate decision with a day-0 review,
    # not a regeneration side effect. The trigger: FAOSTAT is a LIT numbers card (silver_production)
    # that recon wf_14e22400 measured 76d stale with ZERO eval coverage -- the estate's only true
    # built-but-unscheduled case on a served table (D-PQ F6). Day-0 smoke = a -manual- SFN fire of
    # the exact rendered command before the first natural cron (annual, 1st 06:00Z).
}


# --- Serialisation: match the incumbent file exactly ------------------------------------------
# 2-space indent, sorted keys, ASCII-only, trailing newline, CRLF. Verified byte-identical against
# the checked-in file before this script was written -- a formatting change here would rewrite all
# 25 entries in git even where terraform sees nothing.
def _dump_tfvars(obj: dict) -> str:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n").replace("\n", "\r\n")


def _compact(body: dict) -> str:
    """The canonical ``input_json`` string: compact separators, sorted keys, ASCII."""
    return json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _semantics(input_json: str) -> tuple:
    """The comparable content of an entry's ``input_json``, whitespace and key order removed.

    ``Input`` is itself a JSON STRING inside the StartExecution body, so it is decoded one more
    level -- otherwise two byte-different but semantically identical bodies compare unequal and the
    blast-radius rule does nothing."""
    body = json.loads(input_json)
    return (
        json.loads(body["Input"]),
        body.get("Name"),
        body.get("StateMachineArn"),
    )


def _load_tfvars() -> dict:
    if not TFVARS.exists():
        return {"dag_schedules": {}}
    return json.loads(TFVARS.read_text(encoding="utf-8"))


# --- Assembly ---------------------------------------------------------------------------------
def assemble(*, rewrite_all: bool = False) -> tuple[dict, list[str], list[str]]:
    """Return ``(tfvars_obj, changes, violations)``.

    ``changes`` is one human-readable line per entry this run would rewrite; ``violations`` is the
    fail-closed list (unarmed descriptor, unknown entry, dead hold)."""
    descriptors = G.load_descriptors()
    violations: list[str] = []

    lint = G.lint_all(descriptors) + [
        f"unresolved placeholder: {u}" for u in G.scan_unresolved_placeholders(descriptors)
    ]
    if lint:
        return ({}, [], lint)

    incumbent = _load_tfvars().get("dag_schedules", {})
    rendered = {stem: G.render_schedule(desc) for stem, desc in descriptors.items()}

    # Fail-closed set arithmetic BEFORE anything is written.
    for stem in sorted(set(rendered) - set(incumbent)):
        if stem not in NOT_ARMED:
            violations.append(
                f"{stem}: descriptor exists but the tfvars has no entry, and it is not on NOT_ARMED. "
                f"Arming a family creates a LIVE EventBridge schedule -- add it to NOT_ARMED with a "
                f"reason, or arm it deliberately in its own reviewed change."
            )
    for stem in sorted(set(incumbent) - set(rendered)):
        violations.append(
            f"{stem}: the tfvars arms a schedule with no descriptor at "
            f"configs/silver/dags/{stem}.json -- the entry is unreproducible and unauditable."
        )
    for stem in sorted(NOT_ARMED):
        if stem in incumbent:
            violations.append(
                f"{stem}: declared NOT_ARMED but the tfvars carries an entry. One of the two is a lie."
            )
        if stem not in rendered:
            violations.append(f"{stem}: declared NOT_ARMED but there is no such descriptor (stale list).")
    for stem in sorted(HAND_ARMED):
        if stem not in incumbent:
            violations.append(f"{stem}: declared HAND_ARMED but the tfvars has no entry to hold.")
        elif stem in rendered and _semantics(incumbent[stem]["input_json"]) == _semantics(
            _compact(rendered[stem])
        ):
            violations.append(
                f"{stem}: declared HAND_ARMED but the descriptor now renders the SAME schedule -- the "
                f"hold is dead config. Remove it from HAND_ARMED so this entry tracks the descriptor."
            )

    if violations:
        return ({}, [], violations)

    out: dict[str, dict] = {}
    changes: list[str] = []
    for stem in sorted(incumbent):
        entry = dict(incumbent[stem])
        desc = descriptors[stem]

        # cron is descriptor-owned; enabled is NOT (descriptors carry no `enabled` field, and the
        # armed/disarmed state of a live schedule is an operational decision, never a render).
        if entry.get("cron") != desc["cron"]:
            changes.append(f"{stem}: cron {entry.get('cron')!r} -> {desc['cron']!r} (descriptor-owned)")
            entry["cron"] = desc["cron"]

        if stem in HAND_ARMED:
            out[stem] = entry
            continue

        canonical = _compact(rendered[stem])
        if _semantics(entry["input_json"]) != _semantics(canonical):
            changes.append(f"{stem}: input_json REWRITTEN (semantic change from the descriptor)")
            entry["input_json"] = canonical
        elif rewrite_all and entry["input_json"] != canonical:
            changes.append(f"{stem}: input_json re-serialised (--rewrite-all; NO semantic change)")
            entry["input_json"] = canonical

        out[stem] = entry

    return ({"dag_schedules": out}, changes, [])


def _describe_semantic_diff(stem: str, old: str, new: str) -> list[str]:
    """Field-level description of one entry's semantic change, for the --diff report."""
    o, n = json.loads(json.loads(old)["Input"]), json.loads(json.loads(new)["Input"])
    lines: list[str] = []
    for field in sorted(set(o) | set(n)):
        if o.get(field) == n.get(field):
            continue
        lines.append(f"    {stem}.{field}:")
        lines.append(f"      old: {json.dumps(o.get(field), sort_keys=True)}")
        lines.append(f"      new: {json.dumps(n.get(field), sort_keys=True)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 3 if the tfvars would change; write nothing")
    ap.add_argument("--diff", action="store_true", help="print the classified diff; write nothing")
    ap.add_argument("--rewrite-all", action="store_true",
                    help="also canonicalise entries whose semantics are unchanged (expands the apply's "
                         "blast radius to every re-serialised schedule -- do not use casually)")
    args = ap.parse_args(argv)

    obj, changes, violations = assemble(rewrite_all=args.rewrite_all)
    if violations:
        print("DAG SCHEDULE TFVARS ASSEMBLY FAILED:")
        for v in violations:
            print(f"  - {v}")
        return 2
    if not obj.get("dag_schedules"):
        print("no schedules assembled -- refusing to write an empty tfvars", file=sys.stderr)
        return 4

    text = _dump_tfvars(obj)
    current = TFVARS.read_text(encoding="utf-8", newline="") if TFVARS.exists() else ""

    if args.diff:
        incumbent = _load_tfvars().get("dag_schedules", {})
        print(f"held HAND_ARMED (descriptor deliberately not followed): {sorted(HAND_ARMED)}")
        print(f"held NOT_ARMED  (descriptor deliberately not armed):    {sorted(NOT_ARMED)}")
        if not changes:
            print("no entry would change.")
            return 0
        print(f"{len(changes)} entr{'y' if len(changes) == 1 else 'ies'} would change:")
        for c in changes:
            print(f"  - {c}")
            stem = c.split(":")[0]
            if "REWRITTEN" in c:
                for line in _describe_semantic_diff(stem, incumbent[stem]["input_json"],
                                                    obj["dag_schedules"][stem]["input_json"]):
                    print(line)
        return 0

    if args.check:
        if text != current:
            print("DAG SCHEDULE TFVARS DRIFT (regenerate): "
                  + ", ".join(c.split(":")[0] for c in changes))
            return 3
        print(f"dag_schedules check OK: {len(obj['dag_schedules'])} entries byte-identical "
              f"(lint clean; {len(HAND_ARMED)} held hand-armed, {len(NOT_ARMED)} held unarmed)")
        return 0

    if text == current:
        print(f"dag_schedules unchanged: {len(obj['dag_schedules'])} entries")
        return 0
    TFVARS.write_text(text, encoding="utf-8", newline="")
    print(f"wrote {TFVARS} ({len(obj['dag_schedules'])} entries); changed:")
    for c in changes:
        print(f"  - {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
