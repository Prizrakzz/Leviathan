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

THE REGISTRY-VS-SCHEDULE LINT (``--lint``; census P8 + refuter M4)
------------------------------------------------------------------
``--lint`` answers one question the estate could not answer mechanically until 2026-09-22: **does
every table the engine SERVES have a producer on a clock?** It failed on HEAD naming SEVEN served
cards and TWO descriptors, and every one of them was a real defect:

  * ``gold_board_crush`` and ``gold_futures_spreads`` -- served numbers cards, in P1_TABLES, bound
    to board legs in cascade_map.yaml, with NO descriptor, NO job definition and NO schedule. Both
    were produced ONCE BY HAND on 2026-08-2x and were 33 and 32 days stale against daily inputs.
  * ``silver_psd_attributes`` -- a producer phase that exists in ``psd_monthly.json`` and has never
    reached an apply, so the LIVE schedule runs one silver task where the descriptor declares two.
    This is the rung a descriptor-only check would have missed: the lint reads the ARMED
    ``input_json``, not the descriptor, because the armed entry is what actually fires.
  * ``silver_minagro_grain_exports``, ``silver_production``, ``silver_production_livestock``,
    ``gold_pattern_records`` -- genuinely not armed, for reasons already written down elsewhere in
    the estate. They now say so HERE, in ``NOT_ARMED_TABLES``, instead of being indistinguishable
    from the four above.
  * ``icco_cocoa`` and ``mpoc`` -- descriptors whose ``chain_shape`` string names a ``bronze``
    phase their own ``phases`` list does not contain. That string is what a reader trusts when
    deciding a leg exists, and trusting it is exactly how ``sagis_weekly`` spent 879 days
    write-green and data-dead behind a bronze prefix no phase writes.

The lint is FAIL-CLOSED and carries no waiver for the chain_shape rule: a descriptor either
describes the chain it has, or it is fixed. Both remaining offenders are owned by other lanes of
the same wave.

Usage:
  python scripts/silver/gen_dag_schedules_tfvars.py            write the tfvars
  python scripts/silver/gen_dag_schedules_tfvars.py --check    exit 3 if the tfvars would change
  python scripts/silver/gen_dag_schedules_tfvars.py --diff     print the classified diff, write nothing
  python scripts/silver/gen_dag_schedules_tfvars.py --lint     registry-vs-schedule + chain_shape lint
  python scripts/silver/gen_dag_schedules_tfvars.py --rewrite-all
                                                               also canonicalise byte-equal entries

Exit codes mirror the house generator: 0 ok, 2 lint/hold violation, 3 drift (--check), 4 no input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "silver"))

import gen_sfn_inputs as G  # noqa: E402  (path-injected sibling; this file has no package)

TFVARS = _REPO / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"
NUMBERS_TABLES = _REPO / "configs" / "graphrag" / "numbers" / "tables.yaml"

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
    # mpob HOLD RELEASED 2026-08-18 (same day it was installed): the gate condition met --
    # b3-flat-silver rev 29 registered on the tranche-2 image e1fe1d82 whose baked fetch_mpob.py
    # carries --refresh-manifest, and the descriptors reference the jobdef UNVERSIONED so every
    # fire resolves latest-ACTIVE. The hold, its review provenance (wf_051e926a) and the exit-2
    # terminal-after-one rationale are preserved in git history and mpob.json's notes.
    "futures_prices": (
        "shadow-first arm per futures_prices.json's own notes ('the dag_schedules.auto.tfvars.json "
        "futures_prices entry is hand-armed to the shadow-first shape'); A-W4 retrofit landed in the "
        "worker image while retrofit_landed stays FALSE deliberately"
    ),
}

# Descriptors this generator is AUTHORISED to CREATE a tfvars entry for -- the third hold list, and
# the one that turns arming from a hand-seed into a declared act.
#
# WHY IT EXISTS. The fail-closed rule below refuses to create an entry for a descriptor nobody has
# vouched for, and that rule is right: arming a family creates a LIVE EventBridge schedule. But
# before this list the ONLY way past it was to hand-type an entry into the generated tfvars -- which
# is what put a guaranteed-red production_faostat schedule live, and which the estate's own standing
# law forbids ("never hand-edit a generator-owned file; edit the generator and RUN it"). A stem here
# is the declaration; the generator still does the writing, so the input_json can never diverge from
# the descriptor it claims to render.
#
# An entry here means the family is armed ENABLED at the next terraform apply. Membership is
# permanent once the entry exists (the generator then maintains it like any other), and a stem that
# names no descriptor is a stale list, checked below.
ARM: dict[str, str] = {
    "gold_board_crush": (
        "census B3 (2026-09-22): a SERVED numbers card, in P1_TABLES, bound to a board leg in "
        "cascade_map.yaml, produced ONCE BY HAND on 2026-08-22 and 33 days stale against its own "
        "5-day ceiling with no descriptor, no jobdef, no schedule and no alarm. The descriptor "
        "configs/silver/dags/gold_board_crush.json runs the existing producer on the existing "
        "shared runner leviathan-dev-b3-flat-silver at cron(0 10 ? * TUE-SAT *), two hours behind "
        "the databento chain that writes its three CBOT soy legs. No new infrastructure: the arm is "
        "a schedule over a producer that already runs."
    ),
    "gold_futures_spreads": (
        "census B14 (2026-09-22): the same absence as gold_board_crush, plus a null freshness "
        "cadence that hid it -- a 32-day-old DAILY table reported GREEN against the 46-day generic "
        "fallback. The cadence is now declared daily/5 in the registry generator's curation map and "
        "the descriptor arms the producer on the same TUE-SAT 10:00 UTC clock as its sibling."
    ),
}

# Descriptors that exist but are DELIBERATELY not armed as a live schedule.
NOT_ARMED: dict[str, str] = {
    "production_faostat": (
        "ARMED then DISARMED the same day, 2026-08-18, BY MEASUREMENT. The arming (D-LD Track 2 #2, "
        "owner-ratified 'do the remaining tracks') was premised on the family being runnable: "
        "FAOSTAT is a LIT numbers card (silver_production) measured 76d stale with zero eval "
        "coverage, the estate's only built-but-unscheduled case on a served table (D-PQ F6). The "
        "day-0 smoke the arming owed it FAILED in 60s on argparse exit 2: the fetch leg named "
        "upload_faostat.py, which declares --file required (none was passed) and reads a LOCAL "
        "path -- in Fargate there is no local zip, so NO argument value could have worked. That "
        "leg is now removed from the descriptor and the real operating model is written into its "
        "notes: FAOSTAT QCL is an annual bulk zip a HUMAN uploads, then the two Glue legs are "
        "fired manually. A cron over those legs alone re-derives the same zip forever. RE-ARM ONLY "
        "AFTER an unattended fetcher against FAOSTAT's bulk endpoint exists and its own day-0 "
        "smoke passes -- the generator's refusal to create this entry was RIGHT the first time, "
        "and overriding it by hand-seeding the tfvars is what put a guaranteed-red schedule live "
        "(EventBridge leviathan-dev-production_faostat, disabled by hand the same day)."
    ),
}

# --- The registry-vs-schedule lint's own hold list (census P8) ---------------------------------
# A table with a numbers-registry card that is DELIBERATELY not on any armed clock. Each entry
# names the decision that already exists elsewhere in the estate; this map is where a reader finds
# it without having to know which file to open. It is checked BOTH WAYS: an entry whose table IS
# armed is dead config, and an entry naming no card at all is a stale list.
NOT_ARMED_TABLES: dict[str, str] = {
    "silver_production": (
        "FAOSTAT. The production_faostat descriptor is on NOT_ARMED above with the full "
        "measurement; this card rides that same decision."
    ),
    "silver_production_livestock": (
        "FAOSTAT, the livestock companion of silver_production -- same descriptor, same "
        "NOT_ARMED decision."
    ),
    "silver_minagro_grain_exports": (
        "MINAGRO Ukraine. Producer and card exist; no schedule was armed in the wave that built "
        "them. dag_catalog._NON_BACKFILL_FAMILIES records the standing consequence in its own "
        "words -- 'RE-OPEN THIS THE DAY A SCHEDULE IS ARMED ... the moment the weekly fire "
        "exists, this family needs its alarm pair in the observability tfvars'. The source is a "
        "headless-browser capture of a Ukrainian ministry page behind a Cloudflare managed "
        "challenge that edits ONE standing URL in place, so arming it is a decision about an "
        "unrecoverable forward-only leg, not a config change. Remove this entry in the change "
        "that arms it, together with its alarm pair."
    ),
    "gold_pattern_records": (
        "GENERATION-ONLY. Not ingested from any source: it is the T2B engine-replay ledger over "
        "the mapped catalog, produced by the pattern-records sweep (jobdef "
        "leviathan-dev-pattern-records-sweep), and dag_catalog groups it with model_output for "
        "exactly that reason. Its missed-sweep and zero-row alarms are the T2B plan's own set, "
        "not a silver DAG's. A silver DAG schedule would have nothing to run."
    ),
}

_PHASE_WORDS = ("fetch", "bronze", "silver", "gold")


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
        if stem not in NOT_ARMED and stem not in ARM:
            violations.append(
                f"{stem}: descriptor exists but the tfvars has no entry, and it is on neither ARM "
                f"nor NOT_ARMED. Arming a family creates a LIVE EventBridge schedule -- add it to "
                f"ARM with the decision that authorises it, or to NOT_ARMED with the reason it "
                f"stays dark. Hand-seeding the tfvars is not the third option."
            )
    for stem in sorted(ARM):
        if stem not in rendered:
            violations.append(
                f"{stem}: declared ARM but there is no configs/silver/dags/{stem}.json (stale list)."
            )
        if stem in NOT_ARMED:
            violations.append(f"{stem}: declared both ARM and NOT_ARMED. One of the two is a lie.")
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

    # CREATE the entries ARM authorises, from the descriptor, before the maintenance pass below
    # folds them in exactly like any incumbent. `enabled` is true because that is what arming MEANS
    # -- for every other entry `enabled` stays operator-owned and is never rendered.
    incumbent = dict(incumbent)
    for stem in sorted((set(ARM) & set(rendered)) - set(incumbent)):
        incumbent[stem] = {
            "cron": descriptors[stem]["cron"],
            "enabled": True,
            "input_json": _compact(rendered[stem]),
        }
        changes.append(
            f"{stem}: entry CREATED and ENABLED from the descriptor (ARM) -- this arms a LIVE "
            f"EventBridge schedule at {descriptors[stem]['cron']}"
        )

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


# --- The registry-vs-schedule lint (census P8 + refuter M4) -----------------------------------
def _numbers_cards() -> list[str]:
    """Every table with a card in the served numbers registry, in file order.

    Read as plain YAML rather than through leviathan.graphrag.numbers.registry: this generator is
    AWS-free and dependency-light by design, and the card KEYS are all the lint needs."""
    import yaml

    doc = yaml.safe_load(NUMBERS_TABLES.read_text(encoding="utf-8")) or {}
    return sorted((doc.get("tables") or {}).keys())


def armed_gate_tables(tfvars: dict) -> dict[str, list[str]]:
    """``{table: [schedule, ...]}`` read from the ARMED entries' own ``input_json``.

    THE ARMED ENTRY, NOT THE DESCRIPTOR, AND THAT IS THE POINT. A descriptor is a statement of
    intent; the EventBridge target carries a fully materialised execution input compiled at APPLY
    time, so a producer phase that landed in a descriptor and never reached an apply is not on any
    clock. psd_monthly is the live case: the descriptor has carried silver_psd_attributes since
    2026-08-26 and the armed input still runs one silver task.

    AND ARMED MEANS ``enabled: true``, ONLY THAT (round-3 review MAJOR-2). Until 2026-09-22 this
    function read EVERY entry in the file and never looked at ``enabled``, so a family an operator
    had parked still satisfied the rule this feeds -- the fence would have certified the very state
    it was written from (a served card with nothing firing). The chain from that boolean to the
    clock, read end to end on 2026-09-22:
      infra/terraform/envs/dev/main.tf              for k, v in var.dag_schedules -> module
                                                    .eventbridge.schedules, enabled passed through
      infra/terraform/modules/eventbridge/main.tf   state = each.value.enabled ? "ENABLED"
                                                          : var.schedule_state
      .../eventbridge/variables.tf                  variable "schedule_state" default "DISABLED"
    So ``enabled: false`` is a schedule that EXISTS in the account and never fires, and the card it
    would produce is served off whatever the last manual run left behind. The field is
    OPERATOR-OWNED by design -- this generator renders it only on the ARM create path and never
    rewrites it afterwards -- so nothing but this read stands between parking a family and a green
    fence, and the estate has done exactly that once already (production_faostat, seeded by hand
    and disabled by hand the same day).

    FAIL CLOSED ON A FIELD IT CANNOT READ: anything that is not the boolean ``True`` -- absent,
    null, or the STRING "true", which terraform would still convert for a ``bool`` variable --
    counts as UNARMED here. The caller is expected to say WHICH entry it found and what value it
    carried (``config_check.check_dag_registry_schedule`` does), because "the entry exists but is
    parked" and "no entry names this table" are different facts with different remedies, and the
    27 live entries all carry a real ``true`` (measured 2026-09-22), so this branch costs the
    clean tree nothing."""
    out: dict[str, list[str]] = {}
    for stem, entry in sorted(tfvars.items()):
        try:
            if entry.get("enabled") is not True:
                continue  # parked: rendered state="DISABLED"; an entry is not a clock
            payload = json.loads(json.loads(entry["input_json"])["Input"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        for table in payload.get("gate_tables", []):
            out.setdefault(table, []).append(stem)
    return out


def lint_served_tables_have_a_producer(tfvars: dict) -> list[str]:
    """Every numbers-registry card must be on an armed schedule, or declared in NOT_ARMED_TABLES."""
    violations: list[str] = []
    armed = armed_gate_tables(tfvars)
    cards = _numbers_cards()
    for table in cards:
        if table in armed or table in NOT_ARMED_TABLES:
            continue
        violations.append(
            f"{table}: SERVED (it has a card in configs/graphrag/numbers/tables.yaml) but no armed "
            f"schedule produces it -- no entry in dag_schedules.auto.tfvars.json names it in "
            f"gate_tables. A contract the engine serves with no producer on a clock is the "
            f"gold_board_crush class: write the descriptor and arm it, or add an explicit "
            f"NOT_ARMED_TABLES entry with the reason it stays dark."
        )
    for table in sorted(NOT_ARMED_TABLES):
        if table in armed:
            violations.append(
                f"{table}: declared NOT_ARMED_TABLES but {armed[table]} arms it. The waiver is dead "
                f"config -- drop it so this table is covered by the rule like every other."
            )
        if table not in cards:
            violations.append(
                f"{table}: declared NOT_ARMED_TABLES but has no numbers card (stale list)."
            )
    return violations


def lint_chain_shape_matches_phases(descriptors: dict[str, dict]) -> list[str]:
    """A descriptor's ``chain_shape`` may not name a phase its own ``phases`` list lacks.

    That string is prose, and prose is what a reader trusts when deciding whether a leg exists.
    sagis_weekly is the measured cost of trusting it: 'fetch->bronze(shared parser)->silver x3'
    over phases [fetch, silver], a producer reading a bronze prefix NO phase writes, 879 days
    write-green and data-dead, and a served export-pace card whose newest week was two years old.
    Only the four real phase words are checked -- 'gate' and 'promote' are machine stages, not
    descriptor phases, and a chain_shape is free to mention them.

    A phase is CLAIMED only when it LEADS a '->' step, never merely because the word appears. Two
    live strings prove the distinction is needed and not pedantry: production_faostat's
    'MANUAL upload (no unattended fetch) -> bronze[g] -> ...' and sagis_weekly's
    '... (raw-direct; this chain has NO bronze phase)' both NAME a phase in order to DENY it, and a
    substring rule would flag the two descriptors that are telling the truth most explicitly. The
    rule therefore under-detects a phase buried mid-step rather than ever contradicting a
    descriptor that says what it does not have."""
    violations: list[str] = []
    for stem, desc in sorted(descriptors.items()):
        shape = desc.get("chain_shape")
        if not shape:
            continue
        have = {p.get("name") for p in desc.get("phases", []) or []}
        named = set()
        for step in re.split(r"->|-->", shape):
            token = step.strip().lower().lstrip("[( ")
            for word in _PHASE_WORDS:
                if token.startswith(word):
                    named.add(word)
                    break
        for missing in sorted(named - have):
            violations.append(
                f"{stem}: chain_shape {shape!r} names a {missing!r} phase, but this descriptor's "
                f"phases list is {sorted(have)}. Either add the phase or correct the string -- a "
                f"chain_shape that describes a leg the chain does not have is how a producer ends "
                f"up reading a prefix nothing writes (census B9)."
            )
    return violations


def lint(descriptors: dict[str, dict] | None = None,
         tfvars: dict | None = None) -> list[str]:
    """Every rule this generator enforces, as one ordered list. Empty means clean."""
    descriptors = descriptors if descriptors is not None else G.load_descriptors()
    tfvars = tfvars if tfvars is not None else _load_tfvars().get("dag_schedules", {})
    out = G.lint_all(descriptors)
    out += [f"unresolved placeholder: {u}" for u in G.scan_unresolved_placeholders(descriptors)]
    out += lint_chain_shape_matches_phases(descriptors)
    out += lint_served_tables_have_a_producer(tfvars)
    _obj, _changes, assembly = assemble()
    out += assembly
    return out


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
    ap.add_argument("--lint", action="store_true",
                    help="registry-vs-schedule + chain_shape lint (exit 2 on any violation); "
                         "write nothing")
    ap.add_argument("--rewrite-all", action="store_true",
                    help="also canonicalise entries whose semantics are unchanged (expands the apply's "
                         "blast radius to every re-serialised schedule -- do not use casually)")
    args = ap.parse_args(argv)

    if args.lint:
        problems = lint()
        if problems:
            print("REGISTRY-VS-SCHEDULE LINT FAILED:")
            for p in problems:
                print(f"  - {p}")
            return 2
        print(f"registry-vs-schedule lint OK: {len(_numbers_cards())} served cards all produced by "
              f"an armed schedule or declared NOT_ARMED_TABLES ({len(NOT_ARMED_TABLES)}); "
              f"every chain_shape matches its own phases")
        return 0

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
