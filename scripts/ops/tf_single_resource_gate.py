#!/usr/bin/env python
"""Gate a SINGLE-RESOURCE terraform apply on its own saved plan JSON, before the apply runs.

    terraform -chdir=infra/terraform/envs/dev plan -target=<addr> -out=lane.tfplan
    terraform -chdir=infra/terraform/envs/dev show -json lane.tfplan |
        Out-File -Encoding utf8 infra/terraform/envs/dev/tfplan_lane.json
    python scripts/ops/tf_single_resource_gate.py `
        --plan-json infra/terraform/envs/dev/tfplan_lane.json --address <addr> `
        --expect-changed container_properties.image --expect-unchanged-envelope
    terraform -chdir=infra/terraform/envs/dev apply lane.tfplan      # ONLY on exit 0

(That recipe is Windows PowerShell 5.1: continuations are a trailing pipe or a BACKTICK, never a
backslash, and there is no ``&&``.)

THE TWO FILENAMES ARE PART OF THE RECIPE, NOT PLACEHOLDERS, and this is the SAME shape both
runbooks print.  BOTH halves of a saved plan carry the account id, every ARN in the plan and the
inline IAM policy documents of every role in it -- ``.gitignore:71`` already calls saved plans
sensitive -- this repo is PUBLIC, and co-tenant agents race the git index, so BOTH have to land
where .gitignore already covers them.  ``-out`` and the argument to ``show`` are resolved by
terraform INSIDE ``-chdir``'s directory, while ``Out-File`` writes relative to YOUR cwd (the repo
root); that asymmetry is why one is spelled bare and the other in full.  MEASURED 2026-09-07 with
terraform v1.15.2 offline and with ``git check-ignore -v`` on every spelling: the saved plan lands
at ``infra/terraform/envs/dev/lane.tfplan``, IGNORED by ``infra/terraform/**/*.tfplan``
(.gitignore:73), and the rendering at ``infra/terraform/envs/dev/tfplan_lane.json`` is IGNORED by
``infra/terraform/**/tfplan*`` (.gitignore:72) -- while the spellings this recipe used to carry,
``tf.plan`` in the env directory and ``tf_plan.json`` at the repo root, are BOTH NOT IGNORED.
``tests/unit/test_tf_single_resource_gate.py`` reads this block and both runbooks' printed lines
and reddens on any divergence between them.

THE HOUSE LAW THIS TOOL IS.  A targeted apply is signed for on the plan's JSON and nothing else:
EXACTLY ONE resource moves, its action is ``["update"]``, its address is the one you targeted, and
ONLY the attribute(s) you named actually moved once the provider's own normalisations are undone.
``-target`` is not a gate: it is a filter, and a filter that resolves to nothing plans zero changes
and reads like success.

WHY IT EXISTS -- THREE MEASURED REFUSALS, ONE APPLY (2026-09-06, futures_eod_silver repin).  A
hand-written gate refused that repin three times before it applied, each time for a plan shape the
gate had not learned:

  1. THE LIVE ADDRESS CARRIES AN INDEX.  The resource is count-gated, so terraform calls it
     ``module.batch.aws_batch_job_definition.futures_eod_silver[0]`` while every runbook, tfvars
     and -target names it without the ``[0]``.  An equality test on the bare name refuses a
     correct plan.
  2. ATTRIBUTES ARE COMPUTED AT APPLY TIME.  ``arn`` and ``revision`` sit in ``before`` and read
     NULL in ``after`` -- not a deletion, a value the register mints -- and the plan says so in
     ``after_unknown``.  A raw before/after diff calls them changed and refuses.
  3. AWS NORMALISES WHAT THE CONFIG OMITS.  ``mountPoints`` / ``secrets`` / ``ulimits`` /
     ``volumes`` read ``[]`` on one side and are absent (or null) on the other,
     ``fargatePlatformConfiguration`` reads ``{"platformVersion": "LATEST"}`` against null,
     ``logConfiguration.secretOptions`` reads ``[]`` against absent, and ``environment`` comes back
     in the provider's order rather than the config's.  Both descriptors register the SAME job
     definition; a string or key-order comparison refuses a plan in which only the image moved.

WHAT IT DELIBERATELY DOES NOT COVER
-----------------------------------
* IT DOES NOT CHECK THE NEW VALUE.  There is no ``--expect-value``: the gate proves that only the
  image (or only the definition) moved, never that it moved to the digest you built.  The digest is
  proved AFTER the apply by reading the new revision back off AWS -- a digest-pinned jobdef makes a
  push a no-op, so a revision number read from the API is the only proof a repin landed.  The one
  thing it does assert about the value is PRESENCE: an expected SUBKEY that reads empty or absent
  after the apply is refused, because ``image: ""`` and a deleted ``image`` key both used to pass
  (MEASURED 2026-09-06 fix-pass) and neither is ever a repin.  A whole-attribute expectation
  (``--expect-changed definition``) has no such clause -- there is no subkey to look at.  READ
  THAT CLAUSE AS TRUTHINESS, WHICH IS WIDER THAN "empty or absent": it is ``not
  after[attribute][subkey]``, so a subkey moving to ``false`` or to ``0`` is refused with the same
  message (MEASURED 2026-09-07: ``container_properties.privileged`` true -> false, and a subkey
  5 -> 0, both FAIL).  Fail-closed, and unreachable for ``image``, but it is a nuisance rather
  than a hole -- name the attribute instead if you are gating a legitimately falsy leaf.
* ``--allow-unknown <ATTR>`` ON A WHOLE-ATTRIBUTE EXPECTATION LEAVES ONLY THE ENVELOPE.  The two
  flags compose, and the combination excuses the attribute outright: the subkey loop has no subkey
  to walk, so nothing inside it is compared.  MEASURED 2026-09-07 on the futures plan: with
  ``--expect-changed container_properties --allow-unknown container_properties``, an
  executionRoleArn swap, an extra ``command`` argument and an added ``secrets`` entry ALL PASS,
  while the identical three are each REFUSED under the SUBKEY form
  (``--expect-changed container_properties.image``).  Use the subkey form unless the whole
  attribute really is the unit you are signing for; neither runbook passes ``--allow-unknown``.
* THE ENVELOPE CLAUSE COMPARES STRINGS.  ``resource_requirements`` calls ``str()`` on each value,
  so a TYPE flip inside it (``MEMORY: "4096"`` -> ``4096``) reads as unchanged and the clause
  reports ``the envelope is unchanged -- {'VCPU': '1', 'MEMORY': '4096'} -> {'VCPU': '1',
  'MEMORY': '4096'}`` GREEN.  MEASURED 2026-09-07: the plan is still REFUSED, but by the outer
  container diff (``normalised diff ['image', 'resourceRequirements']``), not by the clause that
  exists for it -- so do not lean on this clause alone (see the ``--allow-unknown`` note above,
  where it would be the only clause left).
* AN INDEX-FREE EXPECTED ADDRESS ADMITS ANY INDEX.  ``...futures_eod_silver`` matches ``[0]`` and
  would equally match ``[1]``.  Pass the exact indexed address when the index is load-bearing --
  e.g. ``module.eventbridge.aws_scheduler_schedule.family["pink_sheet_monthly"]``, where the wrong
  key is a live schedule belonging to another lane.
* ONLY ``environment`` IS ORDER-NORMALISED, and only as an ORDER-FREE MULTISET of (name, value)
  pairs -- duplicates survive, so a second ``LEVIATHAN_ENV`` entry is a diff.  A reordered
  ``secrets``, ``ulimits``, ``mountPoints`` or ``volumes`` list reads as a diff and the gate
  REFUSES.  That is the fail-closed direction: the 2026-09-06 plan reordered environment and
  nothing else, and a normalisation nobody has seen fire is a hole, not a feature.  ``command``
  order is meaningful and is never sorted.
* IT READS A PLAN, NOT THE WORLD.  Drift between the saved plan and the live resource, and the
  plan's own ``resource_drift`` block, are outside it; save the plan and apply THAT FILE.
* NOTHING BINDS THE JSON TO THE BINARY PLAN.  ``--plan-json tfplan_x.json`` and ``apply x.tfplan``
  are two files, and only the order of the runbook's lines says the second is what the first
  describes; a stale JSON from an earlier plan would gate a fresh apply silently.  The gate's
  first report line therefore PRINTS the plan's own ``timestamp`` and terraform version -- read it
  and check it is the plan you just made.  That is a tripwire, not a binding.

ASCII-only output.
"""
from __future__ import annotations

import argparse
import json
import sys

# The provider-side empties: a value the config omits comes back as one of these, on ONE side of
# the diff only. Measured on the 2026-09-06 futures plan (mountPoints/secrets/ulimits/volumes).
EMPTY_SHAPES = (None, [], {})

# ``fargatePlatformConfiguration`` is minted with this exact body when the config omits it.
DEFAULT_FARGATE_PLATFORM = {"platformVersion": "LATEST"}

# Stands in for a leaf terraform will only know after the apply. It compares equal to ITSELF and to
# nothing else, so masking both sides of a change with it makes an apply-time value a non-diff
# while every KNOWN leaf beside it keeps its own value. See ``_known_only``.
UNKNOWN_LEAF = object()


class GateRefusal(RuntimeError):
    """The plan cannot be read as the shape asked for (malformed input, not a failed check)."""


def _strip_empties(value):
    """Drop the provider's empty leaves recursively; lists keep their order and their length."""
    if isinstance(value, dict):
        return {k: _strip_empties(v) for k, v in value.items() if v not in EMPTY_SHAPES}
    if isinstance(value, list):
        return [_strip_empties(v) for v in value]
    return value


def normalise_container_properties(container: dict) -> dict:
    """The EFFECTIVE descriptor: what AWS would register, not what the plan's JSON string says.

    MEASURED on the futures_eod_silver repin plan: ``before`` carries ``mountPoints: []``,
    ``secrets: []``, ``ulimits: []``, ``volumes: []``, ``fargatePlatformConfiguration:
    {"platformVersion": "LATEST"}`` and ``logConfiguration.secretOptions: []`` where ``after``
    omits them, and the two sides list ``environment`` in different orders.  Undo exactly those and
    nothing else -- an unexplained diff must survive into the report.

    It is applied to whatever JSON-object attribute carries subkeys, not only to
    ``container_properties``: on a state machine ``definition`` the environment/fargate clauses
    simply never fire, and the empty-leaf strip is the same normalisation either way.

    ``environment`` IS SORTED, NOT KEYED BY NAME.  MEASURED 2026-09-06 fix-pass: a name-keyed dict
    (the first build) COLLAPSES DUPLICATES -- one extra ``{"name": "X"}`` on one side and two on
    the other read as no diff at all.  Sorting (name, value) pairs is order-free in the way the
    provider's reordering needs and still counts every entry, so the duplicate is a diff again.
    """
    out: dict = {}
    for key, value in container.items():
        if value in EMPTY_SHAPES:
            continue
        if key == "fargatePlatformConfiguration" and value == DEFAULT_FARGATE_PLATFORM:
            continue
        if (key == "environment" and isinstance(value, list)
                and all(isinstance(e, dict) and "name" in e for e in value)):
            # str() in the sort key only orders the pairs; the VALUES compared are the originals,
            # so a null value and the string "None" never read as the same entry.
            value = sorted(([e["name"], e.get("value")] for e in value),
                           key=lambda pair: (pair[0], str(pair[1])))
        out[key] = _strip_empties(value)
    return out


def _has_unknown(mirror) -> bool:
    """Is anything under this ``after_unknown`` node computed at apply time?

    ``after_unknown`` MIRRORS the resource's shape with ``true`` at every value terraform will only
    know after the apply.  MEASURED on the futures plan the mirror reads ``{"arn": true,
    "revision": true, "timeout": [{}], "platform_capabilities": [false], "tags": {}, ...}``:
    ``[{}]`` and ``[false]`` contain NO unknown, so a plain truthiness test on the mirror (what the
    hand-written gate did) excuses two attributes that are fully known.  Recursing keeps the excuse
    list to the two that really are computed -- ``arn`` and ``revision`` -- and anything else that
    moves has to be named on the command line via ``--allow-unknown``.
    """
    if mirror is True:
        return True
    if isinstance(mirror, dict):
        return any(_has_unknown(v) for v in mirror.values())
    if isinstance(mirror, list):
        return any(_has_unknown(v) for v in mirror)
    return False


def _known_only(value, mirror):
    """``value`` with every leaf ``after_unknown`` marks apply-time-computed masked out.

    WHY THIS AND NOT ``_has_unknown`` AT THE ATTRIBUTE LEVEL.  The first build excused a whole
    ATTRIBUTE the moment one leaf under it was unknown.  MEASURED false PASS (2026-09-06 review):
    put ``tags = {"owner": "attacker"}`` in ``after`` and ``tags = {"computed_one": true}`` in
    ``after_unknown`` and the gate PASSED, while the identical tags change with no unknown leaf
    beside it FAILED.  One unknown leaf excused every known change next to it.

    Masking is per LEAF: both sides of an unknown leaf become the same sentinel and stop being a
    diff, and every known leaf keeps its own value, so ``arn``/``revision`` (unknown all the way
    down: ``true``) are still excused while ``tags.owner`` is not.  Shapes that mirror the value
    without any ``true`` in them -- MEASURED on this plan, ``timeout: [{}]`` and
    ``platform_capabilities: [false]`` -- mask to themselves and therefore excuse nothing.
    """
    if mirror is True:
        return UNKNOWN_LEAF
    if isinstance(mirror, dict) and isinstance(value, dict):
        return {k: _known_only(v, mirror.get(k, False)) for k, v in value.items()}
    if isinstance(mirror, list) and isinstance(value, list):
        return [_known_only(v, mirror[i] if i < len(mirror) else False)
                for i, v in enumerate(value)]
    return value


def address_matches(expected: str, actual: str) -> bool:
    """``expected`` matches the live address, with or without its count/for_each index.

    An expectation that carries its own index is matched EXACTLY: ``family["pink_sheet_monthly"]``
    must never be satisfied by ``family["psd_monthly"]``.  An index-free expectation admits any
    single index -- that is refusal (1) above, and its cost is in the non-coverage note.
    """
    if expected == actual:
        return True
    if expected.endswith("]"):
        return False
    return actual.startswith(expected + "[") and actual.endswith("]")


def parse_expectations(expect_changed) -> dict:
    """``["container_properties.image", "definition"]`` -> ``{"container_properties": {"image"},
    "definition": set()}``.  An empty subkey set means the whole attribute may move."""
    wanted: dict = {}
    for item in expect_changed:
        attribute, _, subkey = item.partition(".")
        if not attribute:
            raise GateRefusal("--expect-changed " + repr(item) + " names no attribute")
        wanted.setdefault(attribute, set())
        if subkey:
            wanted[attribute].add(subkey)
    return wanted


def _as_mapping(value, attribute: str, side: str) -> dict:
    """A JSON-string attribute (container_properties, definition) read as the object it encodes."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError as exc:
            raise GateRefusal(f"{side} {attribute} is not JSON ({exc})") from exc
        if not isinstance(decoded, dict):
            raise GateRefusal(f"{side} {attribute} decodes to {type(decoded).__name__}, not object")
        return decoded
    raise GateRefusal(f"{side} {attribute} is {type(value).__name__}, not an object or JSON string")


def resource_requirements(container: dict) -> dict:
    """``[{"type": "VCPU", "value": "2"}, ...]`` -> ``{"VCPU": "2", ...}``. THE ENVELOPE."""
    return {r["type"]: str(r.get("value")) for r in container.get("resourceRequirements", [])
            if isinstance(r, dict) and "type" in r}


def gate(plan: dict, address, expect_changed, *, expect_unchanged_envelope: bool = False,
         allow_unknown=()) -> tuple[bool, list[str]]:
    """Pure: ``(ok, report lines)``. Reads ``plan``; touches no file, no network, no terraform.

    ``address`` is one resource address or a list of them: the NAMED SET that must move together."""
    report: list[str] = []
    ok = True

    def check(passed: bool, line: str) -> bool:
        nonlocal ok
        report.append(("PASS " if passed else "FAIL ") + line)
        ok = ok and passed
        return passed

    try:
        wanted = parse_expectations(expect_changed)
    except GateRefusal as exc:
        return False, ["FAIL bad expectation: " + str(exc)]
    if not wanted:
        return False, ["FAIL nothing expected to change: pass at least one --expect-changed"]
    allowed_unknown = {a for a in allow_unknown if a}

    # THE ONLY THING TYING THIS JSON TO A PARTICULAR PLAN RUN. `--plan-json x.json` and
    # `apply x.tfplan` are two files; a JSON left over from an earlier plan would gate a fresh
    # apply and say nothing. Printing the stamp does not bind them -- it makes a stale one visible.
    report.append(f"plan stamp: terraform {plan.get('terraform_version')} "
                  f"at {plan.get('timestamp')} (format {plan.get('format_version')}) -- CHECK "
                  f"this is the plan you just saved")

    resource_changes = plan.get("resource_changes") or []
    moved = [rc for rc in resource_changes
             if (rc.get("change") or {}).get("actions") != ["no-op"]]
    report.append(f"plan: {len(resource_changes)} resource_changes read, {len(moved)} not no-op")
    for rc in moved:
        report.append(f"  moved: {rc.get('address')} {(rc.get('change') or {}).get('actions')}")

    # A -target that resolves to nothing plans ZERO changes and reads as 'already applied'.
    # MEASURED 2026-09-04: `-target=module.scheduler...` -- there is no module.scheduler in this
    # stack -- planned 0 changes while the live schedule still lacked the tasks the operator
    # believed were armed. Zero is a FAIL here, and so is a mover nobody named.
    #
    # THE NAMED SET (2026-09-11): `--address` is repeatable. A family whose jobdefs must move TOGETHER
    # (the three cpc_soil legs on one per-family digest) cannot be applied as three saved plans -- the
    # second saved plan is stale the moment the first applies -- so the gate signs for exactly the
    # named set: every named address moves, nothing unnamed moves, and every mover passes the same
    # per-resource clauses one at a time. One address is the original single-resource shape.
    addresses = [address] if isinstance(address, str) else [a for a in address if a]
    if not addresses:
        return False, ["FAIL no --address named"]
    head = ("exactly ONE resource moves" if len(addresses) == 1
            else f"exactly the {len(addresses)} NAMED resources move")
    if not check(len(moved) == len(addresses),
                 head + " (a zero-change plan is a -target that resolved to nothing, not an "
                 "applied change; an unnamed mover is never signed for) -- "
                 f"{len(addresses)} named, {len(moved)} moved"):
        return ok, report
    matched: list[dict] = []
    for wanted_addr in addresses:
        hits = [rc for rc in moved if address_matches(wanted_addr, rc.get("address", ""))]
        check(len(hits) == 1,
              f"the moved resource is the targeted address -- expected {wanted_addr}, plan carries "
              f"{[rc.get('address') for rc in hits] or [rc.get('address') for rc in moved]}")
        matched.extend(h for h in hits if h not in matched)
    unnamed = [rc.get("address") for rc in moved if rc not in matched]
    check(not unnamed,
          f"every moved resource is a targeted address -- unnamed movers {unnamed or 'none'}")

    def _one(rc: dict) -> None:
        if len(matched) > 1:
            report.append(f"-- resource {rc.get('address')}")
        change = rc.get("change") or {}
        actions = change.get("actions") or []
        check(actions == ["update"],
              "the action is a pure in-place update (a create/delete/replace is never a targeted "
              f"repin) -- actions {actions}")

        before = change.get("before") or {}
        after = change.get("after") or {}
        unknown_mirror = change.get("after_unknown") or {}
        computed = sorted(k for k, v in unknown_mirror.items() if _has_unknown(v))
        report.append(f"computed after apply (after_unknown): {computed or 'none'}")
        if allowed_unknown:
            report.append(f"excused by --allow-unknown: {sorted(allowed_unknown)}")

        raw_moved = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        report.append(f"attributes moved (RAW before/after): {raw_moved or 'none'}")
        # PER-LEAF, never per-attribute: an attribute is excused only when its KNOWN leaves are
        # identical on both sides. See _known_only for the measured false PASS this closes.
        effective, excused = [], []
        for key in raw_moved:
            mirror = unknown_mirror.get(key, False)
            if key in allowed_unknown or (_known_only(before.get(key), mirror)
                                          == _known_only(after.get(key), mirror)):
                excused.append(key)
            else:
                effective.append(key)
        report.append(f"attributes moved (after removing computed/excused): {effective or 'none'}")
        report.append(f"excused (only apply-time-unknown leaves moved, or --allow-unknown): "
                      f"{excused or 'none'}")

        unexpected = sorted(set(effective) - set(wanted))
        # An EXPECTED attribute the operator excused by hand still counts as moved: --allow-unknown on
        # the very attribute you expect is the shape of a partially-computed expected value, and
        # subtracting it here is what made that combination unreachable in the first build.
        excused_by_flag = {k for k in wanted if k in allowed_unknown and k in raw_moved}
        absent = sorted(set(wanted) - set(effective) - excused_by_flag)
        check(not unexpected, f"no attribute moved that was not expected -- unexpected {unexpected}")
        # An expected attribute that did NOT move is a VACUOUS apply: the saved plan does not carry
        # the change the operator is signing for. Same failure mode as the rev-110 vacuous gate.
        check(not absent, f"every expected attribute actually moved -- did not move {absent}")

        for attribute, subkeys in sorted(wanted.items()):
            if not subkeys or attribute not in raw_moved:
                continue
            try:
                b_obj = _as_mapping(before.get(attribute), attribute, "before")
                a_obj = _as_mapping(after.get(attribute), attribute, "after")
            except GateRefusal as exc:
                check(False, f"{attribute} can be read as an object -- {exc}")
                continue
            raw_inner = sorted(k for k in set(b_obj) | set(a_obj) if b_obj.get(k) != a_obj.get(k))
            n_b = normalise_container_properties(b_obj)
            n_a = normalise_container_properties(a_obj)
            inner = sorted(k for k in set(n_b) | set(n_a) if n_b.get(k) != n_a.get(k))
            report.append(f"{attribute} keys moved (RAW): {raw_inner or 'none'}")
            report.append(f"{attribute} keys moved (NORMALISED -- provider empties dropped, "
                          f"environment order-free): {inner or 'none'}")
            check(inner == sorted(subkeys),
                  f"only {sorted(subkeys)} moved inside {attribute} -- normalised diff {inner}")
            # NOT a value check -- a PRESENCE check. MEASURED 2026-09-06 fix-pass: `image: ""` and a
            # container_properties with the image key DELETED both produced the normalised diff
            # ['image'] and PASSED. Neither is ever a repin, and both are cheap to refuse.
            empty = sorted(s for s in subkeys if not a_obj.get(s))
            check(not empty, f"every expected subkey of {attribute} still carries a value after the "
                             f"apply (presence only -- WHICH value is never checked) -- empty or "
                             f"absent {empty}")

        if expect_unchanged_envelope:
            b_cp = before.get("container_properties")
            a_cp = after.get("container_properties")
            if b_cp is None and a_cp is None:
                check(False, "--expect-unchanged-envelope needs container_properties: this resource "
                             "has none (the clause is a Batch job definition clause)")
            else:
                try:
                    b_env = resource_requirements(_as_mapping(b_cp, "container_properties", "before"))
                    a_env = resource_requirements(_as_mapping(a_cp, "container_properties", "after"))
                except GateRefusal as exc:
                    check(False, f"the envelope can be read -- {exc}")
                else:
                    # WHAT THIS CLAUSE HAS ACTUALLY READ, and nothing more: the only envelope it has
                    # ever seen is {'VCPU': '1', 'MEMORY': '4096'} on the 2026-09-06 futures_eod_silver
                    # plan. The 12,288 MiB post-OOM bump people cite belongs to
                    # leviathan-dev-esr-bronze-to-silver and leviathan-dev-silver-publisher-runner,
                    # which are NOT terraform resources and can never reach this code path (MEASURED:
                    # `grep -c 12288 infra/terraform/modules/batch/main.tf` = 0; every MEMORY value in
                    # that module is one of 512/1024/2048/4096/8192/16384). The clause
                    # stands on its own shape -- a descriptor re-authored from constants moves the
                    # envelope silently on whichever jobdef it is aimed at -- not on that number.
                    check(b_env == a_env, f"the envelope is unchanged -- {b_env} -> {a_env}")


    for rc in matched:
        _one(rc)
    return ok, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate a single-resource terraform apply on its saved plan JSON "
                    "(read-only: it runs no terraform and mutates nothing)")
    parser.add_argument("--plan-json", required=True,
                        help="`terraform show -json <planfile>` output")
    parser.add_argument("--address", required=True, action="append",
                        help="the targeted resource address, with or without its count index; "
                             "REPEATABLE for a family that must move together -- the gate then "
                             "signs for exactly the named set")
    parser.add_argument("--expect-changed", action="append", default=[], metavar="ATTR[.SUBKEY]",
                        help="repeatable; e.g. container_properties.image, definition")
    parser.add_argument("--expect-unchanged-envelope", action="store_true",
                        help="Batch job definitions: resourceRequirements must not move")
    parser.add_argument("--allow-unknown", default="", metavar="ATTR,ATTR",
                        help="comma-separated attributes to excuse beyond after_unknown's own; "
                             "naming an EXPECTED attribute admits one whose value is only "
                             "partly known at plan time (it still has to move). NAMING THE SAME "
                             "ATTRIBUTE AS A WHOLE-ATTRIBUTE --expect-changed leaves only the "
                             "envelope: nothing inside it is compared. Prefer the ATTR.SUBKEY "
                             "form of --expect-changed")
    args = parser.parse_args(argv)

    # utf-8-SIG, not utf-8: the operator's shell is Windows PowerShell 5.1, where the natural way
    # to land `terraform show -json` output in a file stamps a BOM. A plain utf-8 read dies on it
    # with a JSONDecodeError at char 0 -- a gate that cannot be fed is a gate nobody runs. Plain
    # UTF-8 reads identically. MEASURED 2026-09-06 on this machine (PS 5.1.26100.9168): BOTH
    # `python ... > file` and `python ... | Out-File -Encoding utf8 file` wrote UTF-8 WITH a BOM
    # (first bytes 239,187,191). The runbooks still hand the Out-File form because it NAMES its
    # encoding, where a bare `>` inherits the host's -- not because a redirect was seen to write
    # UTF-16 here. If some other host does write UTF-16, utf-8-sig does not rescue it and the
    # symptom is a JSONDecodeError at char 0 all the same.
    with open(args.plan_json, encoding="utf-8-sig") as handle:
        plan = json.load(handle)
    ok, report = gate(plan, args.address, args.expect_changed,
                      expect_unchanged_envelope=args.expect_unchanged_envelope,
                      allow_unknown=[a.strip() for a in args.allow_unknown.split(",")])
    for line in report:
        print(line)
    print("TF SINGLE-RESOURCE GATE: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
