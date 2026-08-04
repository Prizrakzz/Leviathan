"""D-PR-3: the four defects of the ECR pin auditor, one fixture per defect class.

WHAT THESE TESTS ARE FOR. On 2026-08-02 ``sha256:eafc05ff`` was evicted from
``leviathan-dev-leviathan-worker`` while 19 ACTIVE jobdef families still pinned it. The auditor
ran. It printed **two** family names and the sentence ``FAIL: 1``. ``nasa-power-backfill:5`` --
which fired at 08:00Z and failed with CannotPullContainerError -- was in the truncated tail and was
never named. The report was not wrong about the digest; it was unreadable about the blast radius,
which is worse than silence, because "1" reads as small.

Every test below fails if its repair is reverted:
  (a) truncation      -> 19 broken families produce 19 named lines, tail included
  (b) family counting -> the FAIL count is 19 FAMILIES, not 1 digest
  (c) headroom        -> the aggregate "repo is at its cap" warn, and per-pin distance in BUILDS,
                         both against a cap READ LIVE (worker/eda are 100/60 since 2026-08-04)
  (d) tag pins        -> tag-referenced families are resolved and audited, not exempted
  (e) the docstring documents the flags that actually exist
  (f) the cap         -> "no policy" / "no count rule" / "unreadable" are three different verdicts,
                         and only the first may be called zero eviction risk. An age-based rule --
                         this guard's own namesake incident -- used to be certified as safe.
  (g) failed calls    -> an ECR call that THREW is UNPROVEN (rc 2, retry), never MISSING (rc 1,
                         re-register). One throttle on :latest used to order 26 healthy jobdef
                         families repinned.

NO AWS, NO NETWORK. ``build_report`` / ``render`` are pure; the tag resolver and the sidecar fetch
are injected callables.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUDITOR_PATH = _REPO_ROOT / "scripts" / "ops" / "check_ecr_pinned_digests.py"
_SOURCE = _AUDITOR_PATH.read_text(encoding="utf-8")
# Everything AFTER the module docstring. The structural assertions below are about the CODE: the
# docstring quotes the four defects verbatim on purpose, and that record must not be what a
# "the defect is gone" test reads.
_CODE = _SOURCE.split('"""', 2)[-1]

WORKER = "leviathan-dev-leviathan-worker"
EAFC = "sha256:eafc05ff8b0f3d2a1c4e5f60718293a4b5c6d7e8f90112233445566778899aabb"

# The 19 families that pinned sha256:eafc05ff at eviction time. The order matters to this test:
# nasa-power-backfill is DELIBERATELY placed past index 4, because the old report joined who[:4]
# and that is exactly the slice the outage's own jobdef fell out of.
NINETEEN = [
    "leviathan-dev-b3-flat-silver", "leviathan-dev-cepea-fetch", "leviathan-dev-chirps-fetch",
    "leviathan-dev-conab-fetch", "leviathan-dev-cot-fetch", "leviathan-dev-esr-compact",
    "leviathan-dev-fgis-fetch", "leviathan-dev-modis-fetch", "leviathan-dev-mpob-fetch",
    "leviathan-dev-nass-fetch", "leviathan-dev-nasa-power-backfill", "leviathan-dev-psd-fetch",
    "leviathan-dev-sagis-fetch", "leviathan-dev-silver-gate", "leviathan-dev-silver-publisher",
    "leviathan-dev-unica-fetch", "leviathan-dev-wap-fetch", "leviathan-dev-wasde-fetch",
    "leviathan-dev-weather-compact",
]


@pytest.fixture(scope="module")
def aud():
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "ops"))
    import importlib
    return importlib.import_module("check_ecr_pinned_digests")


def _listing(n: int) -> list[str]:
    """A repo listing of n synthetic digests, NEWEST FIRST (index 0 == furthest from eviction)."""
    return ["sha256:%064x" % i for i in range(n)]


def _at(listing: list[str], position: int) -> str:
    """The digest sitting at 1-based newest-first ``position``."""
    return listing[position - 1]


# ===========================================================================
# (a) TRUNCATION -- the mechanism behind the "7 of 19" under-report
# ===========================================================================
def test_every_broken_top_family_is_named_no_truncation(aud):
    refs = {(WORKER, EAFC): [aud.Ref(family=f, revision=5, top=True) for f in NINETEEN]}
    rep = aud.build_report(refs, {WORKER: _listing(30)}, {WORKER: 30})
    lines = aud.render(rep)

    missing = [l for l in lines if l.startswith("MISSING[TOP]")]
    assert len(missing) == 19, "expected one line per broken family, got %d" % len(missing)
    for family in NINETEEN:
        assert any(family in l for l in missing), \
            "%s was never named -- the tail is truncated" % family

    # The jobdef the 2026-08-02 fire actually ran, in the slice who[:4] used to drop.
    assert any("leviathan-dev-nasa-power-backfill:5[TOP]" in l for l in missing)
    # Each line carries its own blast radius, so ANY single line tells you it is a 19-family event.
    assert all("of 19 broken by this digest]" in l for l in missing)
    assert "[family 19 of 19 broken by this digest]" in "\n".join(missing)


def test_old_revision_references_are_listed_in_full(aud):
    """who[:2] hid 10 of every 12 non-top references. They are context for a repin -- print them."""
    olds = [aud.Ref(family="leviathan-dev-esr-compact", revision=r, top=False)
            for r in range(1, 13)]
    rep = aud.build_report({(WORKER, EAFC): olds}, {WORKER: _listing(30)}, {WORKER: 30})
    line = [l for l in aud.render(rep) if l.startswith("missing[old-rev]")]
    assert len(line) == 1 and "12 reference(s)" in line[0]
    for r in range(1, 13):
        assert "leviathan-dev-esr-compact:%d" % r in line[0]
    assert rep.rc == 0, "a non-top miss must never fail the audit"


def test_truncating_slices_are_gone_from_the_source(aud):
    """Structural: the three literal slices that caused the under-report must not come back."""
    for slice_expr in ("who[:4]", "who[:2]", "who[:3]"):
        assert slice_expr not in _CODE, \
            "%s is back -- defect (a) has been reintroduced" % slice_expr


# ===========================================================================
# (b) THE FAIL COUNT COUNTS FAMILIES, NOT DIGESTS
# ===========================================================================
def test_fail_count_is_families_not_digests(aud):
    refs = {(WORKER, EAFC): [aud.Ref(family=f, revision=5, top=True) for f in NINETEEN]}
    rep = aud.build_report(refs, {WORKER: _listing(30)}, {WORKER: 30})
    text = "\n".join(aud.render(rep))

    assert len(rep.broken_families) == 19
    assert "FAIL: 19 TOP-revision jobdef FAMILY(ies) cannot pull" in text
    assert "1 deleted digest(s)" in text, "the digest count must still be reported, alongside"
    assert not re.search(r"^FAIL: 1 ", text, re.M), "the old digest-keyed count is back"
    for family in NINETEEN:
        assert family in text.split("Families:", 1)[1]
    assert rep.rc == 1


def test_one_family_two_dead_digests_counts_once(aud):
    """The inverse shape: family counting must not double-count a family across digests."""
    other = "sha256:" + "1" * 64
    refs = {(WORKER, EAFC): [aud.Ref(family="leviathan-dev-esr-compact", revision=5, top=True)],
            (WORKER, other): [aud.Ref(family="leviathan-dev-esr-compact", revision=4, top=False)]}
    rep = aud.build_report(refs, {WORKER: _listing(30)}, {WORKER: 30})
    assert rep.broken_families == ["leviathan-dev-esr-compact"]
    assert "FAIL: 1 TOP-revision jobdef FAMILY(ies)" in "\n".join(aud.render(rep))


# ===========================================================================
# (c) HEADROOM -- aggregate AND per-pin, against a cap that is READ LIVE
# ===========================================================================
def test_aggregate_headroom_fires_at_cap_even_with_every_pin_safe(aud):
    """The 2026-08-04T06:08Z state: 30 images / cap 30, every pin at a comfortable position, and
    the old auditor printed NOTHING. "The repo is at its cap" was inexpressible."""
    listing = _listing(30)
    refs = {(WORKER, listing[0]): [aud.Ref(family="leviathan-dev-silver-gate", revision=11,
                                           top=True)]}
    rep = aud.build_report(refs, {WORKER: listing}, {WORKER: 30})
    text = "\n".join(aud.render(rep))
    assert rep.headroom == [(WORKER, 30, 30, 25)]
    assert "WARN headroom %s at 30/30 images" % WORKER in text
    assert "NEXT push evicts" in text
    assert rep.eviction == [], "the pin itself is at position 1 -- only the REPO is at risk"
    assert rep.rc == 0, "aggregate headroom warns, it does not fail"


def test_headroom_is_silent_at_the_raised_live_cap(aud):
    """Same 33 images, cap raised 30 -> 100 on 2026-08-04. A hardcoded 30 would scream here."""
    rep = aud.build_report({}, {WORKER: _listing(33)}, {WORKER: 100})
    assert rep.headroom == [] and rep.rc == 0
    assert "OK:" in "\n".join(aud.render(rep))


def test_pin_distance_is_quoted_in_builds_and_warns_where_margin_5_was_silent(aud):
    """sha256:3590b188 sat at position 22 of cap 30 and the old --margin 5 test (order[:25])
    printed nothing; one build later it was at 25, still nothing. One build == 3 manifests."""
    listing = _listing(30)
    for position in (22, 25):
        refs = {(WORKER, _at(listing, position)):
                [aud.Ref(family="leviathan-dev-b3-flat-silver", revision=23, top=True)]}
        rep = aud.build_report(refs, {WORKER: listing}, {WORKER: 30})
        assert len(rep.eviction) == 1, "position %d must be reported" % position
        sev, repo, _digest, pos, cap_, builds, who, _tags = rep.eviction[0]
        assert (sev, repo, pos, cap_) == ("WARN", WORKER, position, 30)
        assert builds == (30 - position) // 3
        assert who[0].family == "leviathan-dev-b3-flat-silver"
        line = [l for l in aud.render(rep) if l.startswith("WARN near-cap")][0]
        assert "build(s) of headroom" in line and "1 build = 3 manifests" in line
        assert rep.rc == 0


def test_one_build_from_eviction_is_a_FAIL_not_a_warning(aud):
    """D-PR-30: FAIL at N=1. A TOP pin inside one push of the chopping block is an outage with a
    date, not an advisory."""
    listing = _listing(30)
    refs = {(WORKER, _at(listing, 29)):
            [aud.Ref(family="leviathan-dev-b3-flat-silver", revision=23, top=True),
             aud.Ref(family="leviathan-dev-silver-gate", revision=11, top=True)]}
    rep = aud.build_report(refs, {WORKER: listing}, {WORKER: 30})
    assert [e[0] for e in rep.eviction] == ["FAIL"]
    assert rep.rc == 1
    text = "\n".join(aud.render(rep))
    assert "FAIL eviction-imminent" in text
    assert "0 build(s) from eviction and pins 2 TOP family(ies)" in text
    # both families named in the summary, no truncation on this path either
    assert "leviathan-dev-b3-flat-silver, leviathan-dev-silver-gate" in text


def test_non_top_pins_do_not_trip_the_eviction_check(aud):
    """Old revisions are not what the next fire runs. Warning on them is how a detector gets
    muted."""
    listing = _listing(30)
    refs = {(WORKER, _at(listing, 29)):
            [aud.Ref(family="leviathan-dev-b3-flat-silver", revision=9, top=False)]}
    rep = aud.build_report(refs, {WORKER: listing}, {WORKER: 30})
    assert rep.eviction == [] and rep.rc == 0


def test_cap_is_data_not_a_constant(aud):
    """THE SAME pin, at the SAME position, is a FAIL under cap 30 and silent under the live 100.

    This is the property the 2026-08-04 raise depends on: the auditor must learn the new cap from
    get_lifecycle_policy alone, with no edit here."""
    listing = _listing(120)
    refs = {(WORKER, _at(listing, 29)):
            [aud.Ref(family="leviathan-dev-b3-flat-silver", revision=23, top=True)]}
    assert aud.build_report(refs, {WORKER: listing[:30]}, {WORKER: 30}).rc == 1
    assert aud.build_report(refs, {WORKER: listing}, {WORKER: 100}).eviction == []

    # ...and structurally: the cap is fetched, never defaulted or overridable by a flag.
    assert "get_lifecycle_policy" in _SOURCE
    assert "--cap" not in _SOURCE, "a --cap flag would let an operator audit against a fiction"
    assert not re.search(r"^\s*cap\s*=\s*\d+", _SOURCE, re.M), "a hardcoded cap has appeared"


def test_repo_without_a_lifecycle_policy_is_named_never_warned(aud):
    """The embedder repo: 446 images, no policy. Unbounded COST, zero eviction risk -- and the
    plan forbids adding a cap there before this auditor has run against it."""
    embedder = "leviathan-dev-leviathan-embedder"
    rep = aud.build_report({}, {embedder: _listing(446)}, {embedder: None})
    text = "\n".join(aud.render(rep))
    assert rep.headroom == [] and rep.eviction == [] and rep.rc == 0
    assert "note: %s has 446 image(s) and NO lifecycle policy" % embedder in text


# ===========================================================================
# (d) TAG-REFERENCED JOBDEFS ARE NO LONGER EXEMPT
# ===========================================================================
def test_parse_image_classifies_every_reference_shape(aud):
    host = "668891723125.dkr.ecr.us-east-1.amazonaws.com"
    assert aud.parse_image("%s/%s@%s" % (host, WORKER, EAFC)) == ("digest", WORKER, EAFC)
    assert aud.parse_image("%s/%s:latest" % (host, WORKER)) == ("tag", WORKER, "latest")
    assert aud.parse_image("%s/%s:20260804T092135" % (host, WORKER)) == \
        ("tag", WORKER, "20260804T092135")
    assert aud.parse_image("%s/%s" % (host, WORKER)) == ("tag", WORKER, "latest")
    assert aud.parse_image("public.ecr.aws/lambda/python:3.12")[0] == "external"
    assert aud.parse_image("") is None
    # the OLD helper is what made them exempt: it still returns None for a tag, by design
    assert aud._pin("%s/%s:latest" % (host, WORKER)) is None


def test_resolved_tag_reference_is_audited_not_skipped(aud):
    """43 ACTIVE families reference an image by tag (measured 2026-08-04). They used to be
    invisible: _pin() returned None and they never entered refs at all."""
    listing = _listing(30)
    tag_refs = {(WORKER, "latest"): [aud.Ref(family="leviathan-dev-world-bank-pink-sheet-bronze",
                                             revision=1, top=True)]}
    resolution = {(WORKER, "latest"): {"digest": _at(listing, 1),
                                       "pushed_at": "2026-08-04 06:52:14+00:00"}}
    rep = aud.build_report({}, {WORKER: listing}, {WORKER: 30}, tag_refs=tag_refs,
                           tag_resolution=resolution)
    text = "\n".join(aud.render(rep))
    assert rep.tag_pairs == 1 and rep.rc == 0
    assert "tag-pin %s:latest resolves to" % WORKER in text
    assert "leviathan-dev-world-bank-pink-sheet-bronze:1[TOP]" in text
    # The honest limit, printed every run: existence is not vintage (D-PR-27 is still open).
    assert "does NOT prove the vintage is unchanged" in text


def test_tag_line_counts_top_families_and_still_names_the_old_revisions(aud):
    """The worker's :latest is referenced by 47 revisions but only ~25 TOP ones are exposed.
    Count the exposure, then name everything -- summarizing is fine, ELIDING is defect (a)."""
    listing = _listing(30)
    who = [aud.Ref(family="leviathan-dev-mpob-bronze", revision=1, top=True),
           aud.Ref(family="leviathan-dev-feature-spine", revision=13, top=True),
           aud.Ref(family="leviathan-dev-feature-spine", revision=1, top=False),
           aud.Ref(family="leviathan-dev-feature-spine", revision=2, top=False)]
    resolution = {(WORKER, "latest"): {"digest": listing[0],
                                       "pushed_at": "2026-08-04T06:52:14Z"}}
    rep = aud.build_report({}, {WORKER: listing}, {WORKER: 100},
                           tag_refs={(WORKER, "latest"): who}, tag_resolution=resolution)
    line = [l for l in aud.render(rep) if l.startswith("tag-pin")][0]
    assert ("2 TOP family(ies): leviathan-dev-feature-spine:13[TOP], "
            "leviathan-dev-mpob-bronze:1[TOP]") in line
    assert ("2 older reference(s): leviathan-dev-feature-spine:1, "
            "leviathan-dev-feature-spine:2") in line


def test_resolver_reports_push_time_in_utc(aud):
    """The host is UTC+3. boto3 renders imagePushedAt in the HOST zone, and every schedule in this
    estate is UTC -- a +03:00 stamp in an audit line is a misreading waiting to happen."""
    amman = timezone(timedelta(hours=3))

    class _FakeEcr:
        def describe_images(self, repositoryName, imageIds):
            return {"imageDetails": [{"imageDigest": "sha256:51f6b670",
                                      "imagePushedAt": datetime(2026, 8, 4, 9, 52, 14,
                                                                tzinfo=amman)}]}

    got = aud._tag_resolver(_FakeEcr())(WORKER, "latest")
    assert got == {"digest": "sha256:51f6b670", "pushed_at": "2026-08-04T06:52:14Z"}


def test_resolver_turns_an_empty_result_into_ImageNotFound(aud):
    """An empty imageDetails is ECR ANSWERING "not there" -- proven, so it may be reported as
    MISSING and remediated with a repin (contrast the thrown-call case under (g) below)."""
    class _EmptyEcr:
        def describe_images(self, repositoryName, imageIds):
            return {"imageDetails": []}

    assert aud._tag_resolver(_EmptyEcr())(WORKER, "gone") == {"error": "ImageNotFound",
                                                              "proven": True}


def test_a_tag_pin_is_evictable_like_any_other_reference(aud):
    """A tag confers no protection under a `tagStatus: any` count rule, so the resolved digest
    enters the same build-distance check."""
    listing = _listing(30)
    tag_refs = {(WORKER, "latest"): [aud.Ref(family="leviathan-dev-usda-wasde-raw-backfill",
                                             revision=1, top=True)]}
    resolution = {(WORKER, "latest"): {"digest": _at(listing, 29), "pushed_at": "x"}}
    rep = aud.build_report({}, {WORKER: listing}, {WORKER: 30}, tag_refs=tag_refs,
                           tag_resolution=resolution)
    assert [e[0] for e in rep.eviction] == ["FAIL"] and rep.rc == 1
    assert "via tag latest" in "\n".join(aud.render(rep))


def test_unresolvable_tag_on_a_top_family_fails_the_audit(aud):
    """The 2026-07-23 shape, in tag form: :latest was stolen by a newer push and the old image
    expired. An unproven tag is treated as broken, never as OK."""
    tag_refs = {(WORKER, "20260724v15"): [aud.Ref(family="leviathan-dev-b3-flat-silver",
                                                  revision=23, top=True),
                                          aud.Ref(family="leviathan-dev-b3-flat-silver",
                                                  revision=22, top=False)]}
    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: 30}, tag_refs=tag_refs,
                           tag_resolution={(WORKER, "20260724v15"): {"error": "ImageNotFound"}})
    text = "\n".join(aud.render(rep))
    assert rep.broken_families == ["leviathan-dev-b3-flat-silver"] and rep.rc == 1
    assert "MISSING[TOP] tag %s:20260724v15 does NOT resolve (ImageNotFound)" % WORKER in text
    assert "1 unresolvable tag(s)" in text


def test_an_api_error_is_unproven_not_healthy(aud):
    """Fail-closed. A throttle or endpoint error must not read as a live tag -- that is the I-2
    fail-open shape this estate has already paid for once."""
    tag_refs = {(WORKER, "latest"): [aud.Ref(family="leviathan-dev-silver-gate", revision=11,
                                             top=True)]}
    unreachable = {(WORKER, "latest"): {"error": "EndpointConnectionError"}}
    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: 30}, tag_refs=tag_refs,
                           tag_resolution=unreachable)
    assert rep.rc != 0, "an unreachable ECR must never exit green"
    assert "EndpointConnectionError" in "\n".join(aud.render(rep))


# ===========================================================================
# (g) A FAILED ECR CALL IS UNPROVEN, NOT AN OUTAGE
# ===========================================================================
def test_a_failed_ecr_call_is_never_rendered_as_a_broken_family(aud):
    """leviathan-dev-leviathan-worker:latest carries 26 TOP families (measured 2026-08-04). One
    throttled describe_images used to print "FAIL: 26 ... cannot pull" and instruct the operator to
    re-register 26 HEALTHY jobdefs. The call failing is not evidence about the image."""
    who = [aud.Ref(family="leviathan-dev-fam%02d" % i, revision=3, top=True) for i in range(26)]
    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: 100},
                           tag_refs={(WORKER, "latest"): who},
                           tag_resolution={(WORKER, "latest"): {"error": "ThrottlingException"}})
    text = "\n".join(aud.render(rep))

    assert rep.broken_families == [], "a throttle is not an outage"
    assert rep.unproven and rep.rc == 2, "unproven is its own exit code: retry, do not repin"
    assert "UNPROVEN[TOP] tag %s:latest could NOT be checked (ThrottlingException)" % WORKER in text
    assert "NOT evidence the tag is gone" in text
    assert "cannot pull" not in text, "the outage wording must not appear on a failed call"
    assert "Re-register" not in text, "26 healthy families must never be ordered repinned"
    assert "OK:" not in text, "unproven is not green either"
    for family in ("leviathan-dev-fam00", "leviathan-dev-fam25"):
        assert family in text, "every affected family is still named"


def test_only_an_ECR_answer_of_absent_is_a_missing_tag(aud):
    """The dividing line, both sides. ImageNotFound == ECR ANSWERED that the image is gone (the
    2026-07-23 shape) and the family really cannot pull; AccessDeniedException == the call failed."""
    who = [aud.Ref(family="leviathan-dev-b3-flat-silver", revision=23, top=True)]
    for reason, proven in (("ImageNotFound", True), ("ImageNotFoundException", True),
                           ("RepositoryNotFoundException", True), ("ThrottlingException", False),
                           ("AccessDeniedException", False), ("EndpointConnectionError", False),
                           ("ClientError", False), ("unresolved", False)):
        rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: 30},
                               tag_refs={(WORKER, "t"): who},
                               tag_resolution={(WORKER, "t"): {"error": reason}})
        assert bool(rep.unresolved_tags) is proven, "%s misclassified" % reason
        assert bool(rep.unproven_tags) is (not proven), "%s misclassified" % reason
        assert rep.rc == (1 if proven else 2)
    # an explicit "proven" from the resolver wins over the name
    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: 30}, tag_refs={(WORKER, "t"): who},
                           tag_resolution={(WORKER, "t"): {"error": "Weird", "proven": True}})
    assert rep.broken_families == ["leviathan-dev-b3-flat-silver"] and rep.rc == 1


def test_resolver_labels_a_thrown_call_unproven_and_an_empty_answer_proven(aud):
    """The classification is made where the evidence is -- at the boto3 call site."""
    class _Throttled:
        def describe_images(self, repositoryName, imageIds):
            raise type("ThrottlingException", (Exception,), {})()

    class _Empty:
        def describe_images(self, repositoryName, imageIds):
            return {"imageDetails": []}

    assert aud._tag_resolver(_Throttled())(WORKER, "latest") == {"error": "ThrottlingException",
                                                                 "proven": False}
    assert aud._tag_resolver(_Empty())(WORKER, "gone") == {"error": "ImageNotFound",
                                                           "proven": True}


# ===========================================================================
# (f) THE CAP DERIVATION KNOWS WHAT IT DID NOT UNDERSTAND
# ===========================================================================
_AGE_ONLY = {"rules": [{"rulePriority": 1, "description": "expire untagged after 1 day",
                        "selection": {"tagStatus": "untagged", "countType": "sinceImagePushed",
                                      "countUnit": "days", "countNumber": 1},
                        "action": {"type": "expire"}}]}


def test_an_age_rule_is_not_a_count_cap_and_is_never_called_zero_risk(aud):
    """THE NAMESAKE SHAPE. "expire untagged after 1 day" is the rule that broke 16 jobdef families
    on 2026-07-23. It carries no countNumber, so the old derivation produced None, which rendered
    as `NO lifecycle policy -- ... zero eviction risk` -- an affirmative all-clear, printed to the
    operator who ran this script "BEFORE any lifecycle-policy tightening" exactly as instructed."""
    pol = aud.summarize_lifecycle_policy(_AGE_ONLY)
    assert (pol.state, pol.cap) == ("no-count-rule", None)
    assert any("sinceImagePushed" in n for n in pol.notes), "the rule it declined to use is printed"

    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: None}, policy={WORKER: pol})
    text = "\n".join(aud.render(rep))
    assert rep.no_policy == [], "a policy EXISTS -- it is just not a count cap"
    assert rep.uncapped_policy and rep.rc == 2
    assert "zero eviction risk" not in text
    assert "NO lifecycle policy" not in text
    assert "CANNOT bound its eviction risk -- it is NOT zero" in text
    assert "sinceImagePushed" in text
    assert "OK:" not in text, "the green line asserts a positive this run cannot assert"


def test_a_scoped_count_rule_does_not_become_the_listings_cap(aud):
    """`min()` over every count rule ignored tagStatus. An {untagged, countNumber 5} rule caps only
    the untagged images; used as the cap for a 100-image listing it puts every pin past position 5
    into a FAIL -- a fabricated outage against healthy pins, and one that now exits 1."""
    mixed = {"rules": [
        {"rulePriority": 1, "selection": {"tagStatus": "untagged",
                                          "countType": "imageCountMoreThan", "countNumber": 5},
         "action": {"type": "expire"}},
        {"rulePriority": 2, "selection": {"tagStatus": "any", "countType": "imageCountMoreThan",
                                          "countNumber": 100}, "action": {"type": "expire"}}]}
    pol = aud.summarize_lifecycle_policy(mixed)
    assert (pol.state, pol.cap) == ("capped", 100), "the listing-wide rule is the listing's cap"
    assert any("untagged" in n for n in pol.notes), "the scoped rule is reported, not discarded"

    listing = _listing(100)
    refs = {(WORKER, _at(listing, 25)): [aud.Ref(family="leviathan-dev-b3-flat-silver",
                                                 revision=23, top=True)]}
    rep = aud.build_report(refs, {WORKER: listing}, {WORKER: pol.cap}, policy={WORKER: pol})
    assert rep.eviction == [] and rep.rc == 0, "position 25 of 100 is not an emergency"


def test_a_malformed_policy_is_unproven_not_a_traceback(aud):
    """main() indexed r["selection"]["countNumber"] inside a try that caught only
    LifecyclePolicyNotFoundException, so one bad rule killed the run and the other four
    repositories were never audited at all."""
    for policy in ({"rules": [{"selection": {"countType": "imageCountMoreThan"}}]},
                   "{not json", {"no_rules_key": 1}, [], 7):
        pol = aud.summarize_lifecycle_policy(policy)
        assert pol.state == "unreadable" and pol.cap is None, policy
    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: None},
                           policy={WORKER: aud.summarize_lifecycle_policy("{not json")})
    text = "\n".join(aud.render(rep))
    assert rep.unreadable_policy and rep.rc == 2
    assert "the cap is UNKNOWN" in text and "OK:" not in text


def test_a_good_cap_does_not_silence_a_rule_that_could_not_be_read(aud):
    """One layer down from defect (f): a policy can yield a valid listing-wide cap AND carry a rule
    this script cannot classify. The cap is still applied -- a known cap warns about more than no
    cap does -- but the opaque rule is named, because it may be a TIGHTER cap than the one used."""
    pol = aud.summarize_lifecycle_policy({"rules": [
        {"rulePriority": 1, "selection": {"tagStatus": "any", "countType": "imageCountMoreThan",
                                          "countNumber": 100}, "action": {"type": "expire"}},
        {"rulePriority": 2, "selection": {"tagStatus": "any", "countType": "imageCountMoreThan"}}]})
    assert (pol.state, pol.cap, pol.unread_rules) == ("capped", 100, 1)

    rep = aud.build_report({}, {WORKER: _listing(30)}, {WORKER: pol.cap}, policy={WORKER: pol})
    text = "\n".join(aud.render(rep))
    assert rep.partial_policy and rep.rc == 2
    assert "audited against cap 100" in text and "could NOT be read" in text
    assert "OK:" not in text


def test_the_three_uncapped_states_are_distinguishable(aud):
    """no policy / a policy with no listing-wide count rule / a policy that would not parse. Only
    the first may be reported as zero eviction risk, and the old code had one bucket for all three."""
    assert aud.summarize_lifecycle_policy(None).state == "none"
    assert aud.summarize_lifecycle_policy(_AGE_ONLY).state == "no-count-rule"
    assert aud.summarize_lifecycle_policy("{").state == "unreadable"
    capped = aud.summarize_lifecycle_policy(
        {"rules": [{"rulePriority": 1, "selection": {"tagStatus": "any",
                                                     "countType": "imageCountMoreThan",
                                                     "countNumber": 60}, "action": {}}]})
    assert (capped.state, capped.cap) == ("capped", 60)
    # an empty rule list is a policy that caps nothing -- not "no policy"
    assert aud.summarize_lifecycle_policy({"rules": []}).state == "no-count-rule"


def test_main_derives_the_cap_through_the_summary_not_a_min_over_all_rules(aud):
    """Structural: the expression that produced defect (f) must not come back, and the LIVE read is
    still the only source of the cap."""
    assert 'r["selection"]["countNumber"] for r in rules' not in _CODE, "defect (f) is back"
    assert "summarize_lifecycle_policy(" in _CODE
    assert "get_lifecycle_policy" in _CODE, "the cap is still read live, per defect (c)"


def test_resolve_tags_asks_once_per_tag(aud):
    calls = []

    def resolver(repo, tag):
        calls.append((repo, tag))
        return {"digest": "sha256:abc", "pushed_at": "t"}

    tag_refs = {(WORKER, "latest"): [aud.Ref(family="a", revision=1, top=True),
                                     aud.Ref(family="b", revision=2, top=True)],
                ("leviathan-dev-leviathan-trainer", "latest"): [aud.Ref(family="c", revision=1,
                                                                        top=True)]}
    out = aud.resolve_tags(tag_refs, resolver)
    assert len(calls) == 2 and len(out) == 2, "one describe_images per TAG, not per reference"


def test_config_drift_reads_the_sidecar_of_a_resolved_tag_pin(aud, capsys):
    """The other half of defect (d): --config-drift printed TAG-PINNED and moved on, so a
    :latest-referenced gate jobdef could not be shown to bake the config it is asked to gate."""
    pins = {"leviathan-dev-silver-gate": ("tag", "acct.dkr.ecr.x/worker:latest", WORKER,
                                          "sha256:deadbeef")}
    sidecar = {"git_commit": "e0a33bf2", "build_time_utc": "2026-07-24T11:13:53Z",
               "silver_tables": ["silver_cot"], "silver_tables_fp": "sha256:aaaaaaaaaaaaaaaa"}
    rc = aud.run_config_drift({"leviathan-dev-silver-gate": {"silver_futures_eod"}}, pins,
                              lambda r, d: sidecar, {"silver_cot", "silver_futures_eod"},
                              "sha256:bbbbbbbbbbbbbbbb")
    out = capsys.readouterr().out
    assert rc == 1
    assert "IMAGE-PREDATES-CONFIG" in out
    assert "leviathan-dev-silver-gate (via acct.dkr.ecr.x/worker:latest)" in out
    assert "silver_futures_eod" in out
    out.encode("ascii")


def test_config_drift_still_reports_an_unresolved_tag_without_inventing_a_verdict(aud, capsys):
    """Compatibility with the 2-tuple form: no digest means no sidecar to read, and the pass says
    so rather than guessing. (tests/unit/test_image_config_fence.py pins this shape too.)"""
    rc = aud.run_config_drift({"jd": {"silver_cot"}}, {"jd": ("tag", "acct.dkr.ecr/x:latest")},
                              lambda r, d: pytest.fail("must not fetch a sidecar for a tag with "
                                                       "no resolved digest"),
                              {"silver_cot"}, "sha256:1111111111111111")
    out = capsys.readouterr().out
    assert rc == 0 and "TAG-PINNED" in out


def test_config_drift_names_an_external_image_instead_of_crashing(aud, capsys):
    """public.ecr.aws/docker-hub images have no sidecar in this account. Named, never unpacked."""
    rc = aud.run_config_drift({"jd": {"silver_cot"}},
                              {"jd": ("external", "public.ecr.aws/lambda/python:3.12")},
                              lambda r, d: pytest.fail("no sidecar exists for an external image"),
                              {"silver_cot"}, "sha256:1111111111111111")
    assert rc == 0
    assert "not in this account's ECR" in capsys.readouterr().out


# ===========================================================================
# (e) THE DOCSTRING DOCUMENTS FLAGS THAT EXIST
# ===========================================================================
def test_usage_block_names_only_real_flags(aud):
    usage = _SOURCE.split("Usage:", 1)[1].split('"""', 1)[0]
    assert "--horizon" not in usage, "a documented flag that does not exist (defect (e))"
    for flag in ("--margin", "--warn-builds", "--fail-builds", "--config-drift"):
        assert flag in usage, "%s is undocumented" % flag
        assert 'ap.add_argument("%s"' % flag in _CODE, "%s is documented but not parsed" % flag
    assert "--horizon" not in _CODE, "the phantom flag is back in the parser"


# ===========================================================================
# HOUSE RULES
# ===========================================================================
def test_render_is_ascii_only(aud):
    """cp1252 console: one non-ASCII byte crashes the print, not just the formatting."""
    listing = _listing(30)
    refs = {(WORKER, EAFC): [aud.Ref(family=f, revision=5, top=True) for f in NINETEEN],
            (WORKER, _at(listing, 29)): [aud.Ref(family="leviathan-dev-b3-flat-silver",
                                                 revision=23, top=True)]}
    tag_refs = {(WORKER, "latest"): [aud.Ref(family="leviathan-dev-x", revision=1, top=True)]}
    rep = aud.build_report(refs, {WORKER: listing}, {WORKER: 30}, tag_refs=tag_refs,
                           tag_resolution={(WORKER, "latest"): {"digest": listing[0],
                                                                "pushed_at": "t"}})
    "\n".join(aud.render(rep)).encode("ascii")


def test_module_import_is_aws_free(aud):
    """The pure helpers must stay importable (and testable) without constructing a boto3 client."""
    head = _SOURCE.split("def main(", 1)[0]
    assert "import boto3" not in head, "boto3 must stay lazy, inside main()"
