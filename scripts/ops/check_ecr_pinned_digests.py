"""SILVER-F085 guard: every ECR image referenced by an ACTIVE Batch jobdef or the serving ECS
taskdef must resolve in its repository -- by digest OR by tag -- and no TOP-revision reference may
sit within one BUILD of that repository's lifecycle count cap.

Two prod-breaking incidents motivated this (both CannotPullContainerError at scheduled fires):
  - 2026-07-17 (A-W7 Wave-3): a hard cap of 5 evicted tagged digests during an 8-rebuild day
    and broke 8 ACTIVE jobdefs.
  - 2026-07-23 (this guard's namesake): the untagged-after-1-day rule expired latest-only
    pushes whose :latest tag had been stolen by a newer push; 16 jobdef families' TOP
    revisions pinned deleted digests and the 14:00 UTC usda_esr run failed.

Lifecycle policies cannot see external references, so this script is the referee. Run it:
  - BEFORE any ECR lifecycle-policy tightening;
  - after image-push bursts / jobdef re-registrations (a green run = nothing stranded).

D-PR-3 -- THE FOUR DEFECTS THIS FILE CARRIED, AND WHY EACH REPAIR IS SHAPED THE WAY IT IS.
The 2026-08-02 CannotPull outage (sha256:eafc05ff, gone) broke 18 jobdef families; the auditor
printed TWO of their names and the single word ``FAIL: 1``. The under-report was the whole failure:
an operator reads "1" and triages one jobdef.
  (a) TRUNCATED REFERENCE LISTS. The report joined ``who[:4]`` / ``who[:2]`` / ``who[:3]``.
      ``nasa-power-backfill:5`` sat in the truncated tail and was never named. FIXED: one line per
      broken TOP family, and every non-top reference listed in full. Nothing is ever elided.
  (b) THE FAIL COUNT COUNTED DIGESTS, NOT FAMILIES. One evicted digest breaking 18 families
      reported ``FAIL: 1``. FIXED: references are kept STRUCTURED (``Ref``), so the count is over
      distinct families and the digest count is reported alongside it, never instead of it.
  (c) NO AGGREGATE HEADROOM CHECK, AND THE PIN CHECK WAS POSITION-RELATIVE ONLY. At 30 images /
      cap 30 the old run emitted nothing, because every pin happened to sit at position <= 22.
      FIXED, in two halves: an aggregate ``len(images) >= cap - margin`` warn that is independent
      of pin positions, and a per-pin distance quoted in BUILDS (D-PR-30) -- WARN at
      ``position > cap - MANIFESTS_PER_BUILD * warn_builds``, FAIL at ``fail_builds`` (default 1).
      THE CAP IS ALWAYS READ LIVE from ``get_lifecycle_policy`` and never hardcoded: worker and eda
      were raised 30 -> 100 and 30 -> 60 on 2026-08-04, and a baked-in 30 would have reported a
      three-build emergency against 67 builds of real headroom.
  (d) TAG-REFERENCED JOBDEFS WERE STRUCTURALLY EXEMPT. ``_pin()`` returned None unless the image
      carried ``@sha256:``, so 43 tag-referenced ACTIVE families (measured 2026-08-04) never
      entered the audit, and ``--config-drift`` printed ``TAG-PINNED ... not auditable`` and moved
      on. FIXED: a tag reference is resolved through ``describe_images(imageIds=[{imageTag}])``,
      enters the existence check, enters the eviction check on its RESOLVED digest, and carries its
      resolved digest into ``--config-drift`` so its sidecar is read like any other.
      LIMIT, STATED: resolution proves the tag EXISTS. It cannot prove the vintage did not move --
      21 scheduled families float on ``:latest`` and all changed vintage at 2026-08-04T06:52:14Z
      with no repin. That gap is D-PR-27 and is NOT closed here; do not read a green tag line as
      "this jobdef runs the image it ran yesterday".
  (e) The docstring documented ``[--horizon 25]``, a flag that does not exist; the real knob was
      ``--margin``, default 5. Promoted to a fifth repair because a documented flag that silently
      does nothing is how an operator reaches for 25 positions of notice and gets 5.

TWO REPAIRS ADDED IN VERIFICATION -- both are the same error class: reporting a thing this script
DID NOT ESTABLISH as a thing it did.
  (f) A POLICY IT COULD NOT READ WAS REPORTED AS ZERO RISK. The cap was ``min(countNumber ...)``
      over ``imageCountMoreThan`` rules, and every empty result rendered as ``NO lifecycle policy
      -- unbounded cost, zero eviction risk``. A policy whose only rule is ``sinceImagePushed``
      yields no counts -- so the auditor affirmatively certified zero eviction risk for the EXACT
      rule shape of its own namesake incident (see 2026-07-23 above), to an operator who ran it
      "BEFORE tightening" as instructed. FIXED: ``summarize_lifecycle_policy`` returns a three-way
      ``PolicyCap.state`` (``none`` / ``capped`` / ``no-count-rule`` / ``unreadable``), only
      ``none`` may be called zero risk, and only a rule scoped ``tagStatus: any`` can BE the cap
      (a ``{untagged, countNumber: 5}`` rule used to win ``min()`` against a 100-image listing and
      would have invented a FAIL storm). It is also total: a malformed rule used to raise KeyError
      / JSONDecodeError past the ``LifecyclePolicyNotFoundException`` handler and kill the run.
  (g) A FAILED ECR CALL WAS REPORTED AS AN OUTAGE. ``_tag_resolver`` catches bare ``Exception``;
      any error made the tag "unresolved", which counted its families as broken, printed
      ``MISSING[TOP] ... cannot pull`` and prescribed ``Re-register EACH family``. One throttled
      ``describe_images`` on ``leviathan-dev-leviathan-worker:latest`` -- 26 TOP families -- would
      have ordered 26 healthy jobdefs re-registered. FIXED: only an answer from ECR that the image
      is absent (ImageNotFound / RepositoryNotFound) is MISSING; a call that FAILED is UNPROVEN,
      rendered as such, never counted as a broken family and never given a repin instruction.

Exit codes: 0 = every reference resolves, nothing is within ``--fail-builds`` of eviction, and every
repository's eviction risk could actually be BOUNDED; 1 = at least one TOP-revision reference is
PROVABLY missing/unresolvable, or a TOP pin is that close to the cap horizon; 2 = the audit could not
DECIDE something (an ECR call failed, or a lifecycle policy this script cannot read as a count cap)
-- RETRY, do not repin. Non-top misses and WARN-level headroom never fail.
ASCII-only stdout (cp1252 console).

Usage:
    python scripts/ops/check_ecr_pinned_digests.py
        [--region us-east-1] [--margin 5] [--warn-builds 3] [--fail-builds 1]
        [--manifests-per-build 3] [--config-drift]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path

_SERVING_CLUSTERS = ["leviathan-dev-serving"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_SCHEDULES = _REPO_ROOT / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"
SIDECAR_BUCKET = "leviathan-dev-shahem-001"

# The estate's push unit, MEASURED and not assumed: one `docker push` of the worker image lands
# THREE manifests (an OCI image INDEX plus its two untagged children) sharing a single
# imagePushedAt -- three digests at 2026-08-01T13:12:30, three at 2026-08-02T01:05:16, three at
# 2026-08-04T06:52:14. Headroom is therefore quoted in BUILDS (D-PR-30): a raw image margin
# under-reports the danger by exactly this factor, which is how sha256:3590b188 travelled from
# newest-first position 22 to 25 inside one session while the auditor printed nothing.
MANIFESTS_PER_BUILD = 3


def _pin(image: str) -> tuple[str, str] | None:
    """'...amazonaws.com/repo@sha256:abc' -> (repo, digest); None for tag-referenced images.

    Kept for callers that only care about digest pins. The AUDIT no longer goes through it --
    returning None for a tag reference is defect (d), and parse_image() is what main() uses.
    """
    if "@sha256:" not in image or ".ecr." not in image:
        return None
    repo = image.split("/")[-1].split("@")[0]
    return repo, "sha256:" + image.split("@sha256:")[-1]


def parse_image(image: str) -> tuple[str, ...] | None:
    """Classify ANY container image reference. Nothing is silently dropped (defect (d)).

    ('digest', repo, digest) -- a private-ECR digest pin
    ('tag',    repo, tag)    -- a private-ECR tag reference (resolved later, never exempted)
    ('external', image)      -- not this account's ECR (public.ecr.aws, docker hub): reported as
                                out-of-scope BY NAME, so "not audited" is a printed fact rather
                                than an invisible omission
    None                     -- no image at all (e.g. a multi-node jobdef's outer properties)
    """
    if not image:
        return None
    if ".dkr.ecr." not in image:
        return ("external", image)
    tail = image.split("/")[-1]
    if "@sha256:" in tail:
        return ("digest", tail.split("@", 1)[0], "sha256:" + tail.split("@sha256:", 1)[-1])
    if ":" in tail:
        repo, tag = tail.rsplit(":", 1)
        return ("tag", repo, tag)
    return ("tag", tail, "latest")  # bare repo name == :latest, per the OCI default


@dataclass(frozen=True)
class Ref:
    """ONE place an image is referenced from, kept structured rather than pre-formatted.

    Defect (b) existed because references were stored as the string "name:12[TOP]": counting
    FAMILIES then required re-parsing, so the code counted the (repo, digest) keys it happened to
    have instead. A dataclass makes the family the primary key it always should have been.
    """

    family: str                 # jobdef name, or "<cluster>/<taskdef-name>" for ECS
    revision: int | None = None
    top: bool = False           # TOP == the highest ACTIVE revision == what the next fire runs
    kind: str = "jobdef"        # "jobdef" | "taskdef"

    def label(self) -> str:
        rev = "" if self.revision is None else ":%d" % self.revision
        return "%s%s%s" % (self.family, rev, "[TOP]" if self.top else "")


def _sort_refs(refs) -> list[Ref]:
    return sorted(refs, key=lambda r: (r.family, r.revision if r.revision is not None else -1))


def _utc(ts) -> str:
    """boto3 hands back tz-aware datetimes rendered in the HOST's zone (this laptop is UTC+3).
    Every schedule, cron and log timestamp in this estate is UTC, so an audit line that quotes
    +03:00 invites exactly the kind of hour/weekday misreading the runbooks warn about."""
    if hasattr(ts, "astimezone"):
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(ts)


@dataclass(frozen=True)
class PolicyCap:
    """What a repository's lifecycle policy says about COUNT eviction -- and what it does NOT say.

    ``state`` is the primary field and is NEVER inferred from ``cap`` alone (defect (f)):
      ``none``          -- the repository has NO lifecycle policy. Nothing can be evicted by ECR,
                           so this is the ONLY state that may be reported as zero eviction risk.
      ``capped``        -- at least one ``imageCountMoreThan`` rule applies to EVERY image in the
                           listing (``tagStatus: any``); ``cap`` is the narrowest such countNumber
                           and the newest-first position audit is meaningful.
      ``no-count-rule`` -- a policy EXISTS but nothing in it bounds the whole listing by count:
                           age rules (``sinceImagePushed``), or count rules scoped to ``untagged``
                           / a tag prefix. Eviction risk is NOT zero and this auditor cannot bound
                           it. Reported as UNPROVEN; never green.
      ``unreadable``    -- the policy could not be parsed. UNPROVEN; never green.

    ``unread_rules`` is orthogonal to ``state``: a policy can yield a perfectly good listing-wide
    cap AND contain a rule this script could not read. The cap is still applied (a known cap warns
    about more than no cap does), but the audit must SAY that part of the policy was opaque to it --
    swallowing that is the same error as (f), one layer down.
    """

    state: str
    cap: int | None = None
    notes: tuple = ()      # every rule NOT used as the cap, rendered so the operator sees them
    detail: str = ""       # why, for the unreadable state
    unread_rules: int = 0  # rules that raised while being classified


def _describe_rule(rule) -> str:
    """One ASCII line for a lifecycle rule. Never raises: it runs on rules that are already suspect."""
    try:
        sel = rule.get("selection") or {}
        scope = str(sel.get("tagStatus", "any"))
        prefixes = sel.get("tagPrefixList") or []
        if prefixes:
            scope += "[" + ",".join(str(p) for p in prefixes) + "]"
        unit = sel.get("countUnit") or ""
        return ("priority %s: %s %s > %s %s" % (rule.get("rulePriority", "?"), scope,
                                                sel.get("countType", "?"),
                                                sel.get("countNumber", "?"), unit)).strip()
    except Exception:  # noqa: BLE001
        return "unreadable rule"


def summarize_lifecycle_policy(policy) -> PolicyCap:
    """Parsed policy document (dict or JSON text), or None for "repo has no policy" -> PolicyCap.

    TOTAL BY CONSTRUCTION -- this never raises. main() used to do ``json.loads(...)["rules"]`` and
    index ``r["selection"]["countNumber"]`` inside a try that caught ONLY
    ``LifecyclePolicyNotFoundException``, so one malformed policy killed the whole audit with a
    traceback and the other four repositories were never reported on at all.

    SCOPE IS PART OF THE DERIVATION. ``min()`` over every count rule ignored ``tagStatus``: an
    ``{tagStatus: untagged, countNumber: 5}`` rule caps only the untagged images, but as a cap for
    a 100-image listing it would have put every pin past newest-first position 5 into a FAIL that
    now exits 1. Only a listing-wide rule can be the listing's cap; every other rule is kept in
    ``notes`` and printed, so a rule this script declines to apply is still visible rather than
    silently discarded.
    """
    if policy is None:
        return PolicyCap(state="none")
    try:
        doc = json.loads(policy) if isinstance(policy, (str, bytes)) else policy
        rules = list(doc["rules"])
    except Exception as exc:  # noqa: BLE001
        return PolicyCap(state="unreadable", detail="%s: %s" % (type(exc).__name__, exc))

    counts: list[int] = []
    notes: list[str] = []
    bad = 0
    for rule in rules:
        try:
            sel = rule["selection"]
            listing_wide = str(sel.get("tagStatus", "any")).lower() == "any"
            if sel.get("countType") == "imageCountMoreThan" and listing_wide:
                counts.append(int(sel["countNumber"]))
            else:
                notes.append(_describe_rule(rule))
        except Exception:  # noqa: BLE001 -- a rule this script cannot read is a rule it must not
            bad += 1      # pretend to have understood; it is reported, never dropped
            notes.append("a rule could not be read (%s)" % _describe_rule(rule))
    if counts:
        return PolicyCap(state="capped", cap=min(counts), notes=tuple(notes), unread_rules=bad)
    if bad:
        return PolicyCap(state="unreadable", notes=tuple(notes), unread_rules=bad,
                         detail="%d rule(s) unreadable and no listing-wide count rule survived" % bad)
    return PolicyCap(state="no-count-rule", notes=tuple(notes))


# An ECR answer that the image is ABSENT. Anything else that came out of the resolver is a call
# that FAILED, which is not evidence about the image (defect (g)).
_PROVEN_ABSENT = frozenset({"ImageNotFound", "ImageNotFoundException",
                            "RepositoryNotFoundException", "RepositoryNotFound"})


def _proven_absent(res: dict) -> bool:
    """Did ECR ANSWER that the tag does not exist, or did the call merely fail?

    Rendering the second as the first is how one ThrottlingException tells an operator to
    re-register 26 healthy jobdef families. An explicit ``{"proven": bool}`` from the resolver
    wins; otherwise the error NAME decides, and an absent/unknown reason is UNPROVEN.
    """
    if "proven" in res:
        return bool(res["proven"])
    return str(res.get("error") or "") in _PROVEN_ABSENT


@dataclass
class Report:
    """The full finding set. Rendering is separate so tests assert on STRUCTURE, not on prose."""

    missing_top: list = field(default_factory=list)      # (repo, digest, Ref, idx, total)
    missing_old: list = field(default_factory=list)      # (repo, digest, [Ref])
    unresolved_tags: list = field(default_factory=list)  # (repo, tag, reason, [Ref]) -- PROVEN gone
    unproven_tags: list = field(default_factory=list)    # (repo, tag, reason, [Ref]) -- call failed
    resolved_tags: list = field(default_factory=list)    # (repo, tag, digest, pushed_at, [Ref])
    # (sev, repo, digest, position, cap, builds_left, [Ref], [tag])
    eviction: list = field(default_factory=list)
    headroom: list = field(default_factory=list)         # (repo, count, cap, threshold)
    no_policy: list = field(default_factory=list)        # (repo, count) -- NO policy at all
    uncapped_policy: list = field(default_factory=list)  # (repo, count, PolicyCap) -- not a count cap
    unreadable_policy: list = field(default_factory=list)  # (repo, count, PolicyCap)
    partial_policy: list = field(default_factory=list)   # (repo, count, PolicyCap) -- capped, but
    #                                                      part of the policy was opaque
    external: list = field(default_factory=list)         # (image, [Ref])
    digest_pairs: int = 0
    tag_pairs: int = 0
    repos: int = 0

    @property
    def broken_families(self) -> list[str]:
        """Every family whose TOP revision PROVABLY cannot pull. THIS is the FAIL count (defect (b)).

        A tag whose resolution merely FAILED is deliberately absent from this set (defect (g)): the
        FAIL line it feeds prescribes re-registering every family named, and that instruction must
        rest on evidence, not on a throttled API call.
        """
        fams = {r.family for _, _, r, _, _ in self.missing_top}
        fams |= {r.family for _, _, _, refs in self.unresolved_tags for r in refs if r.top}
        return sorted(fams)

    @property
    def imminent(self) -> list:
        return [e for e in self.eviction if e[0] == "FAIL"]

    @property
    def unproven(self) -> list[str]:
        """Everything this run could not DECIDE. Not evidence of an outage; a reason to re-run.

        Kept apart from broken_families so the two never share a remediation: a broken family is
        repinned, an unproven item is retried. It is also not silence -- an audit that could not
        read a repository's policy, or could not reach ECR for a tag, has not shown the estate is
        healthy, and exits 2 rather than 0.
        """
        out = ["tag %s:%s (%s)" % (repo, tag, reason)
               for repo, tag, reason, _who in self.unproven_tags]
        out += ["%s: lifecycle policy is not a listing-wide count cap" % repo
                for repo, _c, _p in self.uncapped_policy]
        out += ["%s: lifecycle policy could not be read" % repo
                for repo, _c, _p in self.unreadable_policy]
        out += ["%s: %d lifecycle rule(s) could not be read (the cap that WAS read is applied)"
                % (repo, pol.unread_rules) for repo, _c, pol in self.partial_policy]
        return out

    @property
    def rc(self) -> int:
        if self.broken_families or self.imminent:
            return 1
        return 2 if self.unproven else 0


def build_report(refs: dict, order: dict, cap: dict, *, tag_refs: dict | None = None,
                 tag_resolution: dict | None = None, margin: int = 5, warn_builds: int = 3,
                 fail_builds: int = 1, per_build: int = MANIFESTS_PER_BUILD,
                 policy: dict | None = None) -> Report:
    """Turn live ECR/Batch state into findings. PURE -- no boto3, no I/O, fully seedable.

    ``refs``           : (repo, digest) -> [Ref]
    ``tag_refs``       : (repo, tag)    -> [Ref]
    ``order``          : repo -> [digest] NEWEST FIRST (eviction is oldest-first, so index == the
                         distance from the chopping block)
    ``cap``            : repo -> live lifecycle countNumber, or None when no listing-wide count
                         rule exists. READ LIVE BY THE CALLER. Never defaulted here: worker/eda
                         moved 30 -> 100 and 30 -> 60 on 2026-08-04 and a hardcoded 30 would invent
                         an emergency.
    ``policy``         : repo -> PolicyCap, the caller's summary of the LIVE lifecycle policy. When
                         it is omitted a None cap is read as "no policy at all" -- the old two-way
                         reading, kept so cap-only callers still work, but main() always supplies
                         it because the difference between "no policy" and "a policy this script
                         could not read as a cap" is defect (f).
    ``tag_resolution`` : (repo, tag) -> {"digest":..., "pushed_at":...}
                                      | {"error": reason[, "proven": bool]}
    """
    tag_refs = tag_refs or {}
    tag_resolution = tag_resolution or {}
    policies = policy or {}
    rep = Report(digest_pairs=len(refs), tag_pairs=len(tag_refs), repos=len(order))

    # ---- existence, reported PER FAMILY (defects (a) + (b)) --------------------------------
    for (repo, digest), who in sorted(refs.items()):
        if digest in order.get(repo, ()):
            continue
        tops = _sort_refs([r for r in who if r.top])
        for i, ref in enumerate(tops, 1):
            # One line per family, and each line carries the blast radius of its own digest, so
            # "18 families are down" is legible from ANY single line of the report.
            rep.missing_top.append((repo, digest, ref, i, len(tops)))
        rest = _sort_refs([r for r in who if not r.top])
        if rest:
            rep.missing_old.append((repo, digest, rest))

    # ---- tag references: resolved, never exempted (defect (d)) -----------------------------
    for (repo, tag), who in sorted(tag_refs.items()):
        res = tag_resolution.get((repo, tag)) or {}
        if res.get("digest"):
            rep.resolved_tags.append((repo, tag, res["digest"], res.get("pushed_at"),
                                      _sort_refs(who)))
        elif _proven_absent(res):
            # ECR answered: the image is not there. This IS a CannotPull waiting for the next fire.
            rep.unresolved_tags.append((repo, tag, res.get("error") or "unresolved",
                                        _sort_refs(who)))
        else:
            # The call failed. Never green -- but never an outage either (defect (g)). The tag's
            # state is simply unknown, and the remediation is to run the audit again.
            rep.unproven_tags.append((repo, tag, res.get("error") or "unresolved",
                                      _sort_refs(who)))

    # ---- eviction distance, quoted in BUILDS (defect (c) / D-PR-30) ------------------------
    # Tag references join here on their RESOLVED digest: a tag confers no protection under a
    # `tagStatus: any` count rule, so :latest is evictable like anything else.
    top_by_digest: dict = defaultdict(list)
    for (repo, digest), who in refs.items():
        for ref in who:
            if ref.top:
                top_by_digest[(repo, digest)].append((ref, None))
    for (repo, tag), who in tag_refs.items():
        digest = (tag_resolution.get((repo, tag)) or {}).get("digest")
        if not digest:
            continue
        for ref in who:
            if ref.top:
                top_by_digest[(repo, digest)].append((ref, tag))

    for (repo, digest), entries in sorted(top_by_digest.items()):
        repo_cap = cap.get(repo)
        listing = order.get(repo) or []
        if not repo_cap or digest not in listing:
            continue                      # no policy == no count eviction; missing == already red
        pos = listing.index(digest) + 1   # 1-based, newest first
        fail_pos = max(repo_cap - per_build * fail_builds, 0)
        warn_pos = max(repo_cap - per_build * warn_builds, 0)
        sev = "FAIL" if pos > fail_pos else ("WARN" if pos > warn_pos else None)
        if sev:
            rep.eviction.append((sev, repo, digest, pos, repo_cap,
                                 max(repo_cap - pos, 0) // per_build,
                                 _sort_refs([r for r, _ in entries]),
                                 sorted({t for _, t in entries if t})))

    # ---- aggregate headroom: about the REPO, independent of where any pin sits -------------
    # THREE non-capped outcomes, not one (defect (f)): only a repository with no policy at all may
    # be reported as carrying no eviction risk.
    for repo in sorted(order):
        count = len(order[repo])
        pol = policies.get(repo)
        if pol is None:                       # cap-only caller: a None cap means "no policy"
            pol = (PolicyCap(state="capped", cap=cap.get(repo)) if cap.get(repo) is not None
                   else PolicyCap(state="none"))
        if pol.state == "capped" and pol.cap:
            if count >= pol.cap - margin:
                rep.headroom.append((repo, count, pol.cap, pol.cap - margin))
            if pol.unread_rules:
                rep.partial_policy.append((repo, count, pol))
        elif pol.state == "no-count-rule":
            rep.uncapped_policy.append((repo, count, pol))
        elif pol.state == "unreadable":
            rep.unreadable_policy.append((repo, count, pol))
        else:
            rep.no_policy.append((repo, count))
    return rep


def render(rep: Report) -> list[str]:
    """Findings -> ASCII lines. No truncation anywhere: that WAS defect (a)."""
    out = ["pinned references audited: %d digest pair(s) + %d tag reference(s) across %d repo(s)"
           % (rep.digest_pairs, rep.tag_pairs, rep.repos)]

    for repo, digest, ref, idx, total in rep.missing_top:
        out.append("MISSING[TOP] %s -> %s %s [family %d of %d broken by this digest]"
                   % (ref.label(), repo, digest[:19], idx, total))
    for repo, tag, reason, who in rep.unresolved_tags:
        sev = "MISSING[TOP]" if any(r.top for r in who) else "missing[old-rev]"
        out.append("%s tag %s:%s does NOT resolve (%s) <- %s"
                   % (sev, repo, tag, reason, ", ".join(r.label() for r in who)))
    for repo, tag, reason, who in rep.unproven_tags:
        # Deliberately NOT the MISSING wording and deliberately no repin instruction: the ECR call
        # failed, so nothing here is evidence about the image (defect (g)).
        sev = "UNPROVEN[TOP]" if any(r.top for r in who) else "unproven[old-rev]"
        out.append("%s tag %s:%s could NOT be checked (%s) -- the ECR call failed, so this is NOT "
                   "evidence the tag is gone; RETRY <- %s"
                   % (sev, repo, tag, reason, ", ".join(r.label() for r in who)))
    for repo, digest, who in rep.missing_old:
        out.append("missing[old-rev] %s %s <- %d reference(s): %s"
                   % (repo, digest[:19], len(who), ", ".join(r.label() for r in who)))

    for sev, repo, digest, pos, repo_cap, builds, who, tags in rep.eviction:
        via = (" via tag %s" % ",".join(tags)) if tags else ""
        out.append("%s %s %s %s at newest-first position %d of live cap %d = %d build(s) of "
                   "headroom (1 build = %d manifests, measured)%s <- %s"
                   % (sev, "eviction-imminent" if sev == "FAIL" else "near-cap", repo,
                      digest[:19], pos, repo_cap, builds, MANIFESTS_PER_BUILD, via,
                      ", ".join(r.label() for r in who)))
    for repo, count, repo_cap, threshold in rep.headroom:
        out.append("WARN headroom %s at %d/%d images (>= cap - margin = %d) -- the repo is at or "
                   "near its cap, so the NEXT push evicts the oldest manifest regardless of who "
                   "pins it" % (repo, count, repo_cap, threshold))
    for repo, count in rep.no_policy:
        # The ONE state that may be reported as safe, and it is still narrow: no policy means no
        # LIFECYCLE eviction. A digest can always be deleted by hand -- that is the 2026-08-02
        # incident -- which the existence check above, not this line, is responsible for catching.
        out.append("note: %s has %d image(s) and NO lifecycle policy -- unbounded cost, zero "
                   "lifecycle-eviction risk (do not add a cap before this auditor has run "
                   "against it)" % (repo, count))
    for repo, count, pol in rep.uncapped_policy:
        # The 2026-07-23 shape. An age rule is a policy that CAN evict; it just cannot be audited
        # by newest-first position. Saying "zero eviction risk" here was defect (f).
        out.append("UNPROVEN policy %s has %d image(s) and a lifecycle policy with NO count rule "
                   "covering all images, so this audit CANNOT bound its eviction risk -- it is NOT "
                   "zero. Rules not read as a cap: %s. An age rule (sinceImagePushed) is exactly "
                   "the 2026-07-23 shape that expired 16 families' images."
                   % (repo, count, "; ".join(pol.notes) or "none declared"))
    for repo, count, pol in rep.unreadable_policy:
        out.append("UNPROVEN policy %s has %d image(s) and a lifecycle policy this script could "
                   "not read (%s) -- the cap is UNKNOWN, so no eviction verdict is offered%s"
                   % (repo, count, pol.detail or "unparseable",
                      (". Rules seen: " + "; ".join(pol.notes)) if pol.notes else ""))
    for repo, count, pol in rep.partial_policy:
        out.append("UNPROVEN policy %s is audited against cap %d, but %d rule(s) of its lifecycle "
                   "policy could NOT be read: %s. A rule this script cannot classify may be a "
                   "TIGHTER cap than the one applied above."
                   % (repo, pol.cap, pol.unread_rules, "; ".join(pol.notes)))
    for image, who in rep.external:
        out.append("note: %s is not in this account's ECR -- NOT audited <- %s"
                   % (image, ", ".join(r.label() for r in who)))

    if rep.resolved_tags:
        for repo, tag, digest, pushed, who in rep.resolved_tags:
            # TOP families first and counted -- they are the exposure. Older revisions are still
            # named in full (nothing is elided, defect (a)), just after the count that matters.
            tops = [r for r in who if r.top]
            olds = [r for r in who if not r.top]
            out.append("tag-pin %s:%s resolves to %s pushed %s <- %d TOP family(ies)%s%s"
                       % (repo, tag, digest[:19], pushed, len(tops),
                          (": " + ", ".join(r.label() for r in tops)) if tops else "",
                          ("; %d older reference(s): %s"
                           % (len(olds), ", ".join(r.label() for r in olds))) if olds else ""))
        # Stated every run, because a green tag line is the easiest thing in this report to
        # over-read. D-PR-27 is open; this auditor does not close it.
        out.append("NOTE: tag resolution proves the tag EXISTS. It does NOT prove the vintage is "
                   "unchanged -- a moving :latest is D-PR-27, still open.")

    # The green line asserts a POSITIVE: every reference resolves and nothing is near the cap. It
    # must not print alongside anything the run could not decide (defects (f) + (g)).
    if not (rep.missing_top or rep.missing_old or rep.unresolved_tags or rep.unproven_tags
            or rep.eviction or rep.headroom or rep.uncapped_policy or rep.unreadable_policy
            or rep.partial_policy):
        out.append("OK: every reference resolves, none within the declared build horizon of its "
                   "repo's live lifecycle cap")

    fams = rep.broken_families
    if fams:
        digests = {(r, d) for r, d, _, _, _ in rep.missing_top}
        gone_tags = len([1 for _r, _t, _reason, who in rep.unresolved_tags
                         if any(r.top for r in who)])
        out.append("FAIL: %d TOP-revision jobdef FAMILY(ies) cannot pull -- %d deleted digest(s) "
                   "+ %d unresolvable tag(s). Families: %s"
                   % (len(fams), len(digests), gone_tags, ", ".join(fams)))
        out.append("      Re-register EACH family above on a live image before its next "
                   "scheduled fire.")
    for sev, repo, digest, pos, repo_cap, builds, who, _tags in rep.imminent:
        out.append("FAIL: %s %s is %d build(s) from eviction and pins %d TOP family(ies): %s"
                   % (repo, digest[:19], builds, len(who),
                      ", ".join(sorted({r.family for r in who}))))
    unproven = rep.unproven
    if unproven:
        out.append("UNPROVEN: %d item(s) this audit could NOT decide: %s"
                   % (len(unproven), "; ".join(unproven)))
        out.append("          Nothing above is evidence of an outage and NONE of it justifies a "
                   "repin. Clear the cause (throttling, credentials, or a lifecycle policy this "
                   "script cannot read as a count cap) and run again.")
    return out


# ===========================================================================
# --config-drift: the FENCE for incident I-1, at FLEET scope.
#
# The in-container preflight (leviathan.common.image_stamp, wired into
# jobs/audit/silver_rebuild_gate.py) can only speak once a job has already
# fired -- and only from images built AFTER the fence existed. This pass
# catches the same class BEFORE the fire, from the outside, for every
# digest-pinned jobdef: it compares what each TOP revision's image BAKED
# (published as an S3 manifest sidecar at push time) against what the
# scheduler ASKS that jobdef to gate (dag_schedules.auto.tfvars.json --
# terraform-applied, therefore always current).
#
# Run today and it goes RED on leviathan-dev-silver-gate the moment
# configs/silver/tables/silver_futures_eod.yaml lands, i.e. 2026-07-28 --
# four days before anyone read a gate log.
#
# SCOPING IS THE WHOLE DESIGN. RED is reserved for the SEMANTIC mismatch
# ("a table this jobdef is asked to gate is not in its baked set") and for
# UNKNOWN PROVENANCE (no sidecar => cannot prove it is current => treat as
# stale). Plain fingerprint drift is YELLOW, never RED: a blanket
# "fingerprint != HEAD" rule fires on all ~33 digest-pinned jobdefs on every
# config commit, and a fence that always fires gets muted.
# ===========================================================================
def parse_dag_asks(path=None) -> dict[str, set[str]]:
    """jobdef name -> the set of silver table configs that jobdef must have BAKED.

    Reads the same authority the scheduler itself uses: each family's ``input_json`` is a JSON
    string whose ``Input`` is another JSON string carrying ``gate`` (with ``jobdef`` + the argv
    containing ``--tables``), ``gate_tables``, ``phases`` and ``promote``.

    TWO kinds of exposure, both counted:
      * the GATE jobdef -- classifies the table against its baked F010 registry. This is the exact
        surface that produced incident I-1.
      * the family's PHASE/PROMOTE jobdefs (fetch/bronze/silver/promote tasks) -- the transform
        tasks read the same ``configs/silver/tables/<table>.yaml`` contract to write the table.
        Omitting them would have left ``leviathan-dev-b3-flat-silver`` unaudited, and that jobdef
        is pinned to sha256:3590b188 -- the very digest that caused I-1.

    Derived, never hand-maintained: a new gated family is covered the moment its tfvars entry is
    applied.
    """
    p = Path(path) if path is not None else DAG_SCHEDULES
    asks: dict[str, set[str]] = defaultdict(set)
    try:
        families = json.loads(p.read_text(encoding="utf-8"))["dag_schedules"]
    except Exception as exc:  # noqa: BLE001
        print("WARN: could not read %s (%s) -- no asks derived" % (p, type(exc).__name__))
        return {}
    for fam in families.values():
        try:
            payload = json.loads(json.loads(fam["input_json"])["Input"])
        except Exception:  # noqa: BLE001 -- a family without a parseable input contributes nothing
            continue
        gate = payload.get("gate") or {}
        family_tables: set[str] = set(payload.get("gate_tables") or [])
        argv = list(gate.get("command") or [])
        for i, tok in enumerate(argv):
            if tok == "--tables" and i + 1 < len(argv):
                family_tables.update(t.strip() for t in argv[i + 1].split(",") if t.strip())
        if not family_tables:
            continue
        worker_jobdefs = {gate.get("jobdef")}
        for phase in (payload.get("phases") or {}).values():
            for task in (phase or {}).get("tasks") or []:
                worker_jobdefs.add(task.get("jobdef"))
        for task in (payload.get("promote") or {}).get("tasks") or []:
            worker_jobdefs.add(task.get("jobdef"))
        for jd in worker_jobdefs:
            if jd:
                asks[jd].update(family_tables)
    return dict(asks)


def run_config_drift(asks: dict[str, set[str]], pins: dict[str, object],
                     sidecar_fetch, head_tables: set[str], head_fp: str) -> int:
    """Compare each jobdef's ASK against what its pinned image BAKED. Returns the exit code.

    ``pins``  : jobdef -> ("digest", repo, digest)
                        | ("tag", image, repo, resolved_digest)   <- D-PR-3(d), now auditable
                        | ("tag", image)                          <- unresolved: reported, skipped
                        | None
    ``sidecar_fetch(repo, digest)`` -> manifest dict, or None when no sidecar exists.

    RED (exit 1): an asked table absent from the baked set, or a digest with no sidecar at all.
    YELLOW (exit 0): baked table SET matches but the content fingerprint differs from HEAD.
    """
    red_stale: list[str] = []    # PROVEN: the image bakes a set that is missing an asked table
    red_unproven: list[str] = []  # UNPROVEN: no sidecar, so staleness cannot be ruled out
    yellow: list[str] = []
    print("--config-drift: %d jobdef(s) read silver table configs; repo HEAD has %d configs "
          "(fp %s)" % (len(asks), len(head_tables), head_fp))
    for jobdef in sorted(asks):
        ask = asks[jobdef]
        pin = pins.get(jobdef)
        if pin is None:
            # Either the scheduler names a jobdef that has no ACTIVE revision, or the top
            # revision declares no container image (a multi-node shape). Both are "nothing to
            # read", and saying which is unknowable from here.
            print("  skip %s: no ACTIVE jobdef found, or its top revision declares no image"
                  % jobdef)
            continue
        via_tag = None
        if pin[0] == "external":
            print("  skip %s: %s is not in this account's ECR -- no sidecar to read" % (jobdef,
                                                                                        pin[1]))
            continue
        if pin[0] == "tag":
            if len(pin) < 4 or not pin[3]:
                # The tag could not be resolved to a digest (or the caller did not try). Report
                # it exactly as before rather than inventing a verdict about an unknown image.
                print("  TAG-PINNED %s -> %s (tag did not resolve to a digest -- not auditable "
                      "by sidecar)" % (jobdef, pin[1]))
                continue
            # Resolved: this jobdef stops being exempt. Its sidecar is read like any digest pin;
            # the ONLY thing the tag changes is that tomorrow's fire may read a different one.
            via_tag, repo, digest = pin[1], pin[2], pin[3]
        else:
            _, repo, digest = pin
        label = jobdef if via_tag is None else "%s (via %s)" % (jobdef, via_tag)
        manifest = None
        try:
            manifest = sidecar_fetch(repo, digest)
        except Exception as exc:  # noqa: BLE001
            print("  WARN sidecar fetch failed for %s %s (%s)" % (repo, digest[:19],
                                                                  type(exc).__name__))
        if not manifest:
            sample = sorted(ask)
            red_unproven.append(
                "UNKNOWN-PROVENANCE %s -> %s %s has NO manifest sidecar, so it cannot PROVE it "
                "bakes the %d configs it reads (%s%s). Unproven is treated as stale."
                % (label, repo, digest[:19], len(ask), ", ".join(sample[:6]),
                   ", ..." if len(sample) > 6 else ""))
            continue
        baked = set(manifest.get("silver_tables") or [])
        missing = sorted(ask - baked)
        if missing:
            red_stale.append("IMAGE-PREDATES-CONFIG %s -> %s %s (commit %s, built %s) bakes %d "
                             "silver table configs; %s NOT among them. The CONFIG IS FINE -- THE "
                             "IMAGE IS STALE: rebuild + repin this jobdef."
                             % (label, repo, digest[:19], str(manifest.get("git_commit"))[:8],
                                manifest.get("build_time_utc"), len(baked), ", ".join(missing)))
        elif manifest.get("silver_tables_fp") != head_fp:
            yellow.append("CONTENT-DRIFT %s -> %s %s: baked table SET matches HEAD but content "
                          "fp %s != HEAD %s (an existing config was edited after this build)"
                          % (label, repo, digest[:19], manifest.get("silver_tables_fp"), head_fp))
    for line in red_stale:
        print("RED  " + line)
    for line in red_unproven:
        print("RED  " + line)
    for line in yellow:
        print("YELLOW " + line)
    if red_stale or red_unproven:
        # The two classes are reported SEPARATELY on purpose. A wall of identical UNKNOWN-
        # PROVENANCE lines is the expected BOOTSTRAP state -- no image in ECR carries a sidecar
        # until it is rebuilt through the fenced build script -- and it clears itself as images
        # are rebuilt. red_stale is the real incident signature and must never be lost inside it.
        print("FAIL --config-drift: %d jobdef(s) PROVABLY pinned to an image missing a config "
              "they read; %d more cannot be proved either way (no sidecar yet -- rebuild through "
              "scripts/build_push_worker.ps1 to publish one)."
              % (len(red_stale), len(red_unproven)))
        return 1
    print("OK --config-drift: every digest-pinned jobdef bakes every silver config it reads")
    return 0


def _head_silver_tables() -> tuple[set[str], str]:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from leviathan.common.image_stamp import baked_silver_tables
    stems, fp = baked_silver_tables()
    return set(stems), fp


def _sidecar_fetcher(s3):
    def fetch(repo: str, digest: str):
        key = "image_manifests/%s/%s.json" % (repo, digest.replace(":", "_"))
        try:
            body = s3.get_object(Bucket=SIDECAR_BUCKET, Key=key)["Body"].read()
        except Exception:  # noqa: BLE001 -- absent sidecar == unknown provenance (handled as RED)
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return fetch


def _tag_resolver(ecr):
    """(repo, tag) -> {"digest","pushed_at"} | {"error": reason, "proven": bool}.

    One describe_images per tag. ``proven`` is the whole point (defect (g)): ECR ANSWERING that the
    image is absent is a real outage for every TOP family on that tag, while a call that THREW
    (throttle, endpoint, expired credentials, a missing ecr:DescribeImages grant) says nothing at
    all about the image. Both are non-green; only the first may be rendered as MISSING and given a
    re-registration instruction.
    """
    def resolve(repo: str, tag: str) -> dict:
        try:
            details = ecr.describe_images(repositoryName=repo,
                                          imageIds=[{"imageTag": tag}])["imageDetails"]
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            return {"error": name, "proven": name in _PROVEN_ABSENT}
        if not details:
            return {"error": "ImageNotFound", "proven": True}
        top = details[0]
        return {"digest": top["imageDigest"], "pushed_at": _utc(top.get("imagePushedAt"))}
    return resolve


def resolve_tags(tag_refs: dict, resolver) -> dict:
    return {key: resolver(*key) for key in sorted(tag_refs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--margin", type=int, default=5,
                    help="AGGREGATE headroom: warn when a repo holds >= (live cap - margin) "
                         "images, independent of where any pin sits. Repos with no lifecycle "
                         "policy never warn.")
    ap.add_argument("--warn-builds", type=int, default=3,
                    help="warn when a TOP reference sits at newest-first position > cap - "
                         "(manifests-per-build * this). Headroom is quoted in BUILDS because the "
                         "push unit is measurably 3 manifests (D-PR-30).")
    ap.add_argument("--fail-builds", type=int, default=1,
                    help="FAIL at this distance. Default 1: a TOP pin one build from eviction is "
                         "an outage scheduled for the next push, not a warning.")
    ap.add_argument("--manifests-per-build", type=int, default=MANIFESTS_PER_BUILD,
                    help="manifests landed per docker push (measured 3: index + 2 children)")
    ap.add_argument("--config-drift", action="store_true",
                    help="FENCE (incident I-1): also verify that every jobdef the scheduler asks "
                         "to gate a silver table is pinned to an image that actually BAKES that "
                         "table's config. RED on a missing table or a digest with no manifest "
                         "sidecar; YELLOW on content-only drift.")
    args = ap.parse_args(argv)

    import boto3  # lazy: importing this module for its pure helpers must not need boto3

    batch = boto3.client("batch", region_name=args.region)
    ecs = boto3.client("ecs", region_name=args.region)
    ecr = boto3.client("ecr", region_name=args.region)

    refs: dict = defaultdict(list)       # (repo, digest) -> [Ref]
    tag_refs: dict = defaultdict(list)   # (repo, tag)    -> [Ref]
    external: dict = defaultdict(list)   # image          -> [Ref]
    top_rev: dict[str, int] = {}
    for page in batch.get_paginator("describe_job_definitions").paginate(status="ACTIVE"):
        for jd in page["jobDefinitions"]:
            top_rev[jd["jobDefinitionName"]] = max(top_rev.get(jd["jobDefinitionName"], 0),
                                                   jd["revision"])
    top_pin: dict[str, object] = {}
    for page in batch.get_paginator("describe_job_definitions").paginate(status="ACTIVE"):
        for jd in page["jobDefinitions"]:
            name, rev = jd["jobDefinitionName"], jd["revision"]
            image = jd.get("containerProperties", {}).get("image", "")
            parsed = parse_image(image)
            ref = Ref(family=name, revision=rev, top=(rev == top_rev[name]), kind="jobdef")
            if parsed is None:
                continue
            if parsed[0] == "digest":
                refs[(parsed[1], parsed[2])].append(ref)
                if ref.top:
                    top_pin[name] = parsed
            elif parsed[0] == "tag":
                tag_refs[(parsed[1], parsed[2])].append(ref)
                if ref.top:
                    top_pin[name] = ("tag", image)  # upgraded to a 4-tuple once resolved, below
            else:
                external[parsed[1]].append(ref)
                if ref.top:
                    top_pin[name] = parsed

    for cluster in _SERVING_CLUSTERS:
        try:
            svc_arns = ecs.list_services(cluster=cluster)["serviceArns"]
            for svc in ecs.describe_services(cluster=cluster, services=svc_arns)["services"]:
                td = ecs.describe_task_definition(taskDefinition=svc["taskDefinition"])["taskDefinition"]
                tail = td["taskDefinitionArn"].split("/")[-1]
                fam, _, rev = tail.rpartition(":")
                for cd in td["containerDefinitions"]:
                    parsed = parse_image(cd.get("image", ""))
                    if parsed is None:
                        continue
                    ref = Ref(family="%s/%s" % (cluster, fam or tail),
                              revision=int(rev) if rev.isdigit() else None,
                              top=True, kind="taskdef")
                    if parsed[0] == "digest":
                        refs[(parsed[1], parsed[2])].append(ref)
                    elif parsed[0] == "tag":
                        tag_refs[(parsed[1], parsed[2])].append(ref)
                    else:
                        external[parsed[1]].append(ref)
        except Exception as exc:  # noqa: BLE001 -- a missing cluster must not kill the audit
            print("WARN: cluster %s not audited (%s)" % (cluster, type(exc).__name__))

    # newest-first digest order + the repo's LIVE lifecycle count cap (None = no policy/no cap).
    # Both are read from AWS on every run. Nothing about the cap is baked into this file: the
    # 2026-08-04 raise (worker 30 -> 100, eda 30 -> 60) must land here for free.
    order: dict[str, list[str]] = {}
    cap: dict[str, int | None] = {}
    policy: dict[str, PolicyCap] = {}
    for repo in sorted({r for r, _ in refs} | {r for r, _ in tag_refs}):
        imgs = []
        for page in ecr.get_paginator("describe_images").paginate(repositoryName=repo):
            imgs += page["imageDetails"]
        imgs.sort(key=lambda i: i["imagePushedAt"], reverse=True)
        order[repo] = [i["imageDigest"] for i in imgs]
        # The POLICY, not just a number: "no count cap" and "no policy" are different worlds and
        # only one of them is safe (defect (f)). summarize_lifecycle_policy never raises, so a
        # malformed document costs one repo's verdict instead of the whole run.
        try:
            summary = summarize_lifecycle_policy(
                ecr.get_lifecycle_policy(repositoryName=repo)["lifecyclePolicyText"])
        except ecr.exceptions.LifecyclePolicyNotFoundException:
            summary = summarize_lifecycle_policy(None)
        except Exception as exc:  # noqa: BLE001
            summary = PolicyCap(state="unreadable",
                                detail="get_lifecycle_policy failed (%s)" % type(exc).__name__)
        policy[repo] = summary
        cap[repo] = summary.cap

    tag_resolution = resolve_tags(tag_refs, _tag_resolver(ecr))
    for name, pin in list(top_pin.items()):
        if pin[0] == "tag":
            parsed = parse_image(pin[1])
            res = tag_resolution.get((parsed[1], parsed[2])) or {}
            if res.get("digest"):
                top_pin[name] = ("tag", pin[1], parsed[1], res["digest"])

    rep = build_report(dict(refs), order, cap, tag_refs=dict(tag_refs),
                       tag_resolution=tag_resolution, margin=args.margin,
                       warn_builds=args.warn_builds, fail_builds=args.fail_builds,
                       per_build=args.manifests_per_build, policy=policy)
    rep.external = sorted(((img, _sort_refs(who)) for img, who in external.items()),
                          key=lambda t: t[0])
    for line in render(rep):
        print(line)
    rc = rep.rc

    if args.config_drift:
        print("")
        s3 = boto3.client("s3", region_name=args.region)
        head_tables, head_fp = _head_silver_tables()
        rc = max(rc, run_config_drift(parse_dag_asks(), top_pin, _sidecar_fetcher(s3),
                                      head_tables, head_fp))
    return rc


if __name__ == "__main__":
    sys.exit(main())
