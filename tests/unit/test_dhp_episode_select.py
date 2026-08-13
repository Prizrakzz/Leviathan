"""D-HP-15 (H1b) -- EPISODES BECOME SELECT-ORDER-CONNECT: the span-membership validation pass.

THE ITEM, AND ITS MEASURED SCOPE. "The model picks episode ids and writes connective prose; dates,
magnitudes and citations render from data." The scope is SMALL BY DESIGN: the `## Episodes` section
carries 70 of 8,086 typed numerals (0.9%) and 15 of 974 strip rows (1.5%) in `data/dhp_census.json`.
D-HP-15 exists for CONSISTENCY with the wave, not for volume -- plan 10.10(c) forbids ANY gate clause
attributing an AC1 result to it, and nothing in this file claims one.

THE SHAPE IS DISPOSITION (b+), SELECT-ORDER-CONNECT IN PLACE. The model keeps authoring the section;
under `handle_prose` its SELECTION is validated against the windows the prompt actually carried, its
ORDER survives, and its connective prose is untouched. Full engine authorship was REJECTED (it collides
with D-RC-9, converts the five episode eval pins into scaffold tautologies, and opens a G2 fluency
surface larger than the 1.5% integrity upside).

WHAT IS PINNED HERE:

  A  THE HOLE, REPRODUCED. The digit-lint is structurally blind to an episode span, so today a wholly
     fabricated window ships while an honest prop-date count dies. This pass is the only fence.
  B  MEMBERSHIP, NEVER PARSING -- exact string membership against the STAMPED `episodes_injected` spans
     (`timeline.month_span` tokens), fail-closed on any other spelling.
  C  THE WHOLE-BULLET DROP: one line, section-scoped, order-preserving, heading kept.
  D  THE CENSUS POSTURE: the pass ALWAYS COUNTS and MUTATES ONLY UNDER the knob; control byte-identity.
  E  THE CHARGE: `episode_span_unbacked` through `_fold_ledger_class`, `sum(by_rule) == stripped`.
  F  INERT SEAMS -- the X6 decision: this producer mints NOTHING, and nothing could consume it if it did.
  G  THE ONE-HOP NO-OP, structural and pinned rather than assumed.
  H  END TO END, control versus treatment, through a real serving body.
  I  THE SAME-CHANGE LAW: the class is DECLARED in G1 clause (4) and budgeted by clause (e-ep) in the
     wave plan, in this change, or clause (4) is pre-registered to fail on the wave's own remedy.

All offline: no pg, no S3, no LLM, no AWS. ASCII-only output (the Windows console is cp1252).
"""
from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag import timeline as tl
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag import verify as vf

_PLAN = pathlib.Path(an.__file__).parents[3] / "docs" / "private" / "HANDLE_PROSE_WAVE_PLAN.md"

# The two windows the fixtures below inject, spelled by the ONE producer (`timeline.month_span`) so the
# test cannot drift from what `_l2_blocks` stamps and what the model is shown.
_EPS = [{"start": "1994-06-10", "end": "1994-08-01", "n": 11, "receipt": None},
        {"start": "2021-06-01", "end": "2021-08-20", "n": 3,
         "receipt": {"date": "2021-07-20", "text": "July frost hit Sul de Minas hard"}}]
_SPAN_A = tl.month_span(_EPS[0])                       # 1994-06..1994-08
_SPAN_B = tl.month_span(_EPS[1])                       # 2021-06..2021-08
# A window no injected line ever carried. ITS YEAR IS DELIBERATELY INSIDE `verify._claim_number_spans`'
# 1900-2099 calendar fence: outside it ('1812-01..1812-03') the digit-lint DOES charge the bullet, so a
# fixture built on an implausible year would prove the hole closed by an instrument that is not this one.
_FAKE = "2019-01..2019-03"


def _injected(spans=None, node="drivers/frost"):
    """One `trace['episodes_injected']` record in the shape `_l2_blocks` stamps."""
    eps = _EPS
    return [{"node": node, "line": tl.render_line(node, eps),
             "spans": [tl.month_span(e) for e in eps] if spans is None else list(spans),
             "windows": [{"start": tl.day_window(e)[0], "end": tl.day_window(e)[1],
                          "span": tl.month_span(e), "n": e.get("n")} for e in eps]}]


def _mech(*bullets, before="## The record\nFrost tightens the balance [E1].\n",
          after="## What to watch\nFurther cold fronts.\n"):
    return before + "## Episodes\n" + "".join(f"- {b}\n" for b in bullets) + after


_BACKED_A = f"{_SPAN_A} -- drivers/frost: no citable item in this window, so what happened is not narrated."
_BACKED_B = f"{_SPAN_B} -- the frost window: the mill reports damage [E1]; no priced move."
_UNBACKED = f"{_FAKE} -- the great disruption: no citable item in this window."


# ══ A -- THE HOLE THIS PASS EXISTS TO CLOSE, REPRODUCED ══════════════════════════════════════════════
def test_the_digit_lint_is_structurally_blind_to_a_fabricated_span():
    """MEASURED, NOT ARGUED. `verify._claim_number_spans` exempts a bare four-digit year and a year-range
    short tail, so an episode bullet's window is not a claim number to the D-HP-12 lint at all -- a
    WHOLLY FABRICATED window sails through untouched.

    AND THE INVERSION IS THE POINT: the same lint DOES delete an honest bullet that restates the injected
    prop-date COUNT. So before H1b the one section whose load-bearing token is a date range punished
    honesty and ignored invention. This pass is the only fence over that surface; verify.py stays
    episode-blind (H1b does not touch it)."""
    assert vf.bare_digit_verdict(f"- {_UNBACKED}") is None            # invention: invisible
    assert vf.bare_digit_verdict(f"- {_BACKED_A}") is None            # ...and so is the honest twin
    assert vf.bare_digit_verdict(f"- {_SPAN_A} -- frost (11 report dates): the record is thin.") \
        == "bare_digit"                                              # honesty: charged
    assert "episode" not in pathlib.Path(vf.__file__).read_text(encoding="utf-8").lower()


# ══ B -- MEMBERSHIP, NEVER PARSING ═══════════════════════════════════════════════════════════════════
def test_the_stamped_spans_are_read_off_spans_and_nothing_else():
    """`_stamped_episode_spans` reads the stamped `spans` list -- the `timeline.month_span` tokens the
    model was SHOWN -- and never `windows` (the DAY-GRAIN measurement pair, D-OJ-16). Deduped, in stamp
    order, and a FULLY FLOORED record (`spans: []` present-and-empty) contributes nothing without this
    function needing to know what `floored` means."""
    assert an._stamped_episode_spans(_injected()) == [_SPAN_A, _SPAN_B]
    assert an._stamped_episode_spans([{"node": "n", "spans": [], "windows": [], "floored": True}]) == []
    assert an._stamped_episode_spans(None) == [] and an._stamped_episode_spans([]) == []
    assert an._stamped_episode_spans(["not a record", 7, None]) == []
    dupes = [{"spans": [_SPAN_A, _SPAN_A]}, {"spans": [_SPAN_A, _SPAN_B]}]
    assert an._stamped_episode_spans(dupes) == [_SPAN_A, _SPAN_B]     # deduped, stamp order kept


@pytest.mark.parametrize("bullet,backed", [
    (_BACKED_A, True),                                                # exact, verbatim
    (_BACKED_B, True),
    (_UNBACKED, False),                                               # a window nothing injected
    (f"{_SPAN_A.replace('..', ' .. ')} -- frost: no citable item.", False),   # respaced -> UNBACKED
    (f"{_SPAN_A[:7]} -- frost: no citable item.", False),             # one endpoint only
    ("1994-06..1994-09 -- frost: no citable item.", False),           # endpoint moved by one month
    ("94-06..94-08 -- frost: no citable item.", False),               # two-digit years
    ("frost was bad in the 1990s: no citable item.", False),          # no window named at all
])
def test_the_test_is_exact_string_membership_and_fails_closed(bullet, backed):
    """THE FENCE IS MEMBERSHIP, and the alternative is what makes it load-bearing: parsing a span back
    out of the bullet and interpreting it would mint a SECOND definition of what an episode window is,
    which `timeline.month_span`'s own docstring names as exactly how its three readers drift apart.

    A DIFFERENTLY-SPELLED WINDOW IS UNBACKED BY DESIGN, not by oversight. NOTE THE COST HONESTLY
    (fold-2 record correction): the fence CAN drop prose the scorer would have credited -- a respaced
    but endpoint-equal window is a tier-1 `eval._line_targets` hit and still convicts here -- so a
    `min_episodes_cited` delta across the D-HP boundary is not purely the writer's. The wave accepts
    fail-closed losses; G2 reads the fluency cost (plan 10.13, corrected at fold-2).
    A bullet naming NO window is unbacked too -- the persona's own shape rule is "ONE '- ' bullet per
    injected episode WINDOW and NOTHING else", so a bullet naming no window is not an enumeration."""
    st = {"mechanism": _mech(bullet)}
    census = an._validate_episode_spans(st, _injected(), handle_prose=True)
    assert census["spans_checked"] == 1
    assert census["bullets_dropped"] == (0 if backed else 1)
    assert (bullet in st["mechanism"]) is backed


# ══ C -- THE WHOLE-BULLET DROP ═══════════════════════════════════════════════════════════════════════
def test_only_the_unbacked_bullet_goes_and_the_rest_is_byte_identical():
    """WHOLE-BULLET, and the surrounding page is untouched to the byte: the model's ORDER survives among
    the survivors (nothing downstream reads bullet order as meaning -- the scorer's matching is
    order-insensitive), its connective prose survives, and no other section is in scope."""
    before = _mech(_BACKED_A, _UNBACKED, _BACKED_B)
    st = {"mechanism": before}
    census = an._validate_episode_spans(st, _injected(), handle_prose=True)
    assert census == {"spans_checked": 3, "bullets_dropped": 1, "section_seen": True}
    assert st["mechanism"] == _mech(_BACKED_A, _BACKED_B)             # order preserved, one line gone
    assert "## The record" in st["mechanism"] and "## What to watch" in st["mechanism"]


def test_bullets_outside_the_episodes_section_are_never_in_scope():
    """The section walk is the scorer's, so a '- ' line in '## The record' -- which the model writes all
    the time -- is not an episode bullet and cannot be convicted as one."""
    mech = ("## The record\n- a bullet with no window at all\n- another one\n"
            "## Episodes\n" + f"- {_UNBACKED}\n" + "## What to watch\n- watch this\n")
    st = {"mechanism": mech}
    census = an._validate_episode_spans(st, _injected(), handle_prose=True)
    assert census == {"spans_checked": 1, "bullets_dropped": 1, "section_seen": True}
    assert "- a bullet with no window at all" in st["mechanism"]
    assert "- watch this" in st["mechanism"] and _UNBACKED not in st["mechanism"]


def test_the_heading_survives_a_section_whose_every_bullet_was_unbacked():
    """RECORDED RESIDUAL, NOT A DEFECT FIXED HERE (plan 10.13). The remedy is deletion of CONVICTED
    prose and a heading is not convicted; refusing the whole section is exactly the post-synthesis
    deletion D-RC-9 exempts, and it is the rejected disposition (a). `_cap_absence_bullets` is the
    precedent: it never removes the heading either."""
    st = {"mechanism": _mech(_UNBACKED)}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True)["bullets_dropped"] == 1
    assert "## Episodes" in st["mechanism"] and an._has_episode_section(st["mechanism"])


_WALK_CORPUS = (
    "",
    _mech(_BACKED_A),
    "## Episodes\n- x\n",                                            # the section is the whole mechanism
    "### Episodes\n- x\n",                                           # level 3 -- the scorer accepts it
    "###### Episodes\n- x\n",                                        # level 6 -- the widest it takes
    "## Episodes (3)\n- x\n",                                        # count suffix
    "## Episodes -- dated\n- x\n",                                   # dash suffix
    "   ## Episodes\n- x\n",                                         # indented heading
    "## Episodes\n- one\n## Mechanism\nm\n## Episodes\n- two\n",     # TWO sections: the LAST wins
    "```\n## Episodes\n- fenced, not a heading\n```\n",              # fence-aware
    "## Mechanism\n- not an episode bullet\n",                       # no section at all
    "## Episodes\nprose, not a bullet\n",                            # section with no bullets
    "## Episodes\n1. an ordered episode item\n2) another\n",         # FOLD-2: the shape F4 was ABOUT
    "## Episodes\n- a dash item\n1. and an ordered one\n",           # ...and the mixed-marker section
)

_ABSENCE = "no citable item in this window."


def _forced_absence(lines):
    """Every line a walk could put in scope, rewritten as a '- ' ABSENCE bullet -- headings, fences and
    blanks left alone so both walks still see the same structure. With `max_absence=0` the cap pass then
    drops exactly the lines inside ITS OWN bounds, so a count comparison against the shared walk is a
    comparison of BOUNDS and not merely of item scope."""
    out = []
    for ln in lines:
        s = ln.strip()
        out.append(ln if (not s or s.startswith("#") or s.startswith("```"))
                   else f"- {s} {_ABSENCE}")
    return "\n".join(out)


@pytest.mark.parametrize("mech", _WALK_CORPUS)
def test_the_bullet_walk_agrees_with_the_cap_pass_on_every_corpus_shape(mech):
    """THE DUPLICATION IS CHECKED RATHER THAN TRUSTED. `_episode_section_bounds` is a SECOND SPELLING of
    `_cap_absence_bullets`' walk (H1b's scope forbids editing that function -- both cap laws are frozen
    for this build), and a duplicated walk is how two readers come to disagree about which lines are in
    scope.

    IT ASSERTS THE SECTION BOUNDS, WHICH IS WHAT THE RECORD RELIES ON (fold-2 G-C's correction). Until
    fold-2 this test asserted full ITEM agreement -- `n == len(idx)` plus `_SCAFFOLD_BULLET_RX` on every
    returned index -- while plan 10.14 claimed it asserted the BOUNDS. Both were true only because
    `_WALK_CORPUS` contained no ordered item: adding one reddened the old form, and item agreement is
    exactly the property fold-1's F4 deliberately BROKE. So the corpus now carries the ordered shapes and
    the assertions say what they mean: BOUNDS agree exactly (every in-scope line, forced into a bullet
    both readers accept, is culled by the cap pass), and the ITEM divergence is one-directional (every
    line the cap pass calls a bullet, the fence calls an item too -- never the reverse)."""
    lines = mech.split("\n")
    idx = an._episode_bullet_indices(lines)
    bounds = an._episode_section_bounds(lines)
    # (1) BOUNDS: force EVERY line a walk could scope into an absence bullet, then let the cap pass
    #     cull everything it can see. What it removes is exactly what the shared walk put in scope.
    forced = _forced_absence(lines)
    capped, n = an._cap_absence_bullets(forced, max_absence=0)
    assert n == len(an._episode_bullet_indices(forced.split("\n"))), \
        f"bounds disagreement on {mech!r}: cap dropped {n}"
    assert an._episode_bullet_indices(capped.split("\n")) == []      # the section is empty afterwards
    # (2) ITEMS: the divergence is one-directional and recorded at both sites.
    cap_idx = ([i for i in range(*bounds) if an._SCAFFOLD_BULLET_RX.match(lines[i])]
               if bounds is not None else [])
    assert set(cap_idx) <= set(idx), f"the fence lost a cap-pass bullet on {mech!r}"


# ══ C2 -- FOLD-1: THE QUESTION IS UNIVERSAL, THE TOKENS HAVE BOUNDARIES, THE BULLET IS THE UNIT ══════
# The first build asked an EXISTENTIAL question -- `any(sp in line for sp in stamped)` -- so ONE honest
# window anywhere in the line backed the WHOLE bullet. The fold-1 review drove the consequence end to
# end and it was fail-open on the shape the SELECT persona INVITES. Everything under this rule is a
# regression pin: relax the universal back to the existential and the two reproductions below redden.
_MIXED_LEAD = f"{_FAKE} -- the great disruption: milder than the {_SPAN_A} frost [E1]."
_MIXED_BOTH = f"{_SPAN_A} and {_FAKE} -- twin frosts [E1]: no priced move."
_MIXED_HONEST = f"{_SPAN_A} and {_SPAN_B} -- twin frosts [E1]: no priced move."


@pytest.mark.parametrize("bullet,backed", [
    (_MIXED_LEAD, False),                      # the reviewer's reproduction, VERBATIM: fabricated LEAD
    (_MIXED_BOTH, False),                      # ...and the conjunction form, fabricated in the TAIL
    (_MIXED_HONEST, True),                     # THE HAPPY PATH: two windows, BOTH stamped -> survives
])
def test_fold1_f1_one_unstamped_token_convicts_the_whole_bullet(bullet, backed):
    """FIX F1, THE MAJOR. EVERY span-shaped token in the bullet must be an exact stamped member; one
    that is not convicts the whole bullet. Under the existential form both fabricated shapes SHIPPED
    with `bullets_dropped=0` and a clean `by_rule` -- so clause (e-ep)'s ceiling read CLEAN on rows that
    still shipped a fabricated window, and the gate that exists because this item can ship
    gate-invisible could not see the residual.

    THIS IS STILL MEMBERSHIP, NOT PARSING. `_episode_span_tokens` says where a token starts and ends and
    nothing else -- no year, no month, no calendar, no ordering -- and the verdict on each token is
    `token in stamped`, exact and whole. The third row is why the fence is a fence and not a mute: a
    bullet naming TWO windows the prompt actually carried is exactly what the SELECT leg asks for
    ("how it sits beside the others") and it survives untouched."""
    st = {"mechanism": _mech(bullet)}
    census = an._validate_episode_spans(st, _injected(), handle_prose=True)
    assert census["spans_checked"] == 1
    assert census["bullets_dropped"] == (0 if backed else 1)
    assert (bullet in st["mechanism"]) is backed
    assert (_FAKE in st["mechanism"]) is False              # the fabricated window never reaches a reader


@pytest.mark.parametrize("bullet", [
    f"1{_SPAN_A} -- frost [E7]",                            # '11994-06..1994-08': stamped is a SUBSTRING
    f"{_SPAN_A}..2025-01 -- frost [E7]",                    # a three-endpoint token, same direction
    f"{_SPAN_A[1:]} -- frost [E7]",                         # '994-06..1994-08': the pre-existing correct
])                                                          # ...drop, pinned so the fix cannot undo it
def test_fold1_f2_a_span_shaped_token_is_matched_whole_or_not_at_all(bullet):
    """FIX F2, the same missing tokenization in the opposite direction. Plain substring containment let a
    SUPERSTRING of a stamped token pass -- `1994-06..1994-08` is inside `11994-06..1994-08` -- so a
    boundary-broken window shipped uncharged. Matching WHOLE tokens is what makes the fence correct in
    both directions: the written token is span-shaped, it is not a member, it dies. Low likelihood from
    a real writer; recorded and pinned because an unrecorded gap between the clause and the fence is the
    class of defect this wave's review discipline exists to catch."""
    st = {"mechanism": _mech(bullet)}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True) == \
        {"spans_checked": 1, "bullets_dropped": 1, "section_seen": True}
    assert bullet not in st["mechanism"] and "## Episodes" in st["mechanism"]
    assert an._episode_span_tokens(bullet)[0] != _SPAN_A    # the WRITTEN token is not the stamped one


def test_fold1_f3_a_convicted_wrapped_bullet_takes_its_continuation_lines_with_it():
    """FIX F3. A wrapped bullet is ONE bullet. Removing only its first line left the convicted prose on
    the page as a dangling fragment under the heading. It is the Z4 orphan-fragment class H1 spent a
    fold arriving at "0 genuine fragments ship", and the pass owns the fragment itself: nothing later in
    the turn removes a stray markdown line. (Fold-1 argued this from POSITION -- "this pass runs after
    TIDY-2" -- which fold-2's move retired; the property is asserted here as behaviour instead, which is
    what it always should have been.)"""
    mech = ("## Episodes\n"
            f"- {_FAKE} -- invented:\n"
            "  the great disruption, no citable item.\n"
            f"- {_SPAN_A} -- real.\n")
    st = {"mechanism": mech}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True) == \
        {"spans_checked": 2, "bullets_dropped": 1, "section_seen": True}    # BULLETS, not lines
    assert st["mechanism"] == f"## Episodes\n- {_SPAN_A} -- real.\n"
    assert "the great disruption" not in st["mechanism"]                    # no orphaned fragment


def test_fold1_f3_an_innocent_wrapped_bullet_keeps_its_continuation_lines():
    """THE OTHER DIRECTION, which is what stops F3's fix from being a second whole-section remedy: the
    drop span is computed ONLY from convicted indices, so an innocent bullet's wrapped remainder is
    untouched -- as is a non-item line that merely follows one."""
    mech = ("## Episodes\n"
            f"- {_SPAN_A} -- real:\n"
            "  the frost ran into August, and the mills said so.\n"
            f"- {_FAKE} -- invented.\n")
    st = {"mechanism": mech}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True)["bullets_dropped"] == 1
    assert st["mechanism"] == ("## Episodes\n"
                               f"- {_SPAN_A} -- real:\n"
                               "  the frost ran into August, and the mills said so.\n")


def test_fold1_f4_ordered_items_are_in_scope_and_the_divergence_is_recorded_at_both_sites():
    """FIX F4, the fail-open half. `## Episodes\\n1. <fabricated> ...` was entirely outside
    `_SCAFFOLD_BULLET_RX`: the window shipped, nothing was charged, and nothing was stamped. A fence
    whose posture is fail-CLOSED may not be walked through by a list marker.

    THE WIDENING IS A RECORDED DIVERGENCE, not a silent one. `_cap_absence_bullets` keeps its '- '/'* '
    item scope (a frozen cap law on a producer H1b may not touch, whose own bullets are '- ' by
    construction); the validation pass is wider because its failure direction is the opposite one. Both
    sites say so, and the SECTION BOUNDS -- the thing the two passes must agree on -- still agree."""
    mech = f"## Episodes\n1. {_FAKE} -- invented.\n2) {_SPAN_A} -- real.\n"
    st = {"mechanism": mech}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True) == \
        {"spans_checked": 2, "bullets_dropped": 1, "section_seen": True}
    assert st["mechanism"] == f"## Episodes\n2) {_SPAN_A} -- real.\n"
    # the divergence is one-directional: everything the cap pass calls a bullet, this walk sees too
    lines = mech.split("\n")
    assert an._episode_bullet_indices(lines) == [1, 2]
    assert [i for i in (1, 2) if an._SCAFFOLD_BULLET_RX.match(lines[i])] == []
    src = inspect.getsource(an)
    assert "RECORDED DIVERGENCE (H1b fold-1 F4)" in src                 # the `_cap_absence_bullets` site
    assert "RECORDED\n    DIVERGENCE" in inspect.getsource(an._episode_bullet_indices)


def test_fold1_f4_the_key_is_stamped_whenever_the_section_exists():
    """FIX F4, the gate-blindness half, at the unit. `section_seen` is True for ANY '## Episodes'
    section -- even one with zero scanned items -- and absent when there is no section, which is what
    lets the two seams stamp the trace key on the distinction a G1 reader actually needs."""
    for mech, seen in ((_mech(_BACKED_A), True),
                       ("## Episodes\nprose, and not one bullet under it\n", True),
                       ("## Episodes\n", True),
                       ("## The record\nno episode section here at all\n", False),
                       ("```\n## Episodes\n- fenced, so not a section\n```\n", False)):
        census = an._validate_episode_spans({"mechanism": mech}, _injected(), handle_prose=True)
        assert census.get("section_seen", False) is seen, mech
        assert ("section_seen" in census) is seen                       # omitted when False, the idiom


# ══ C3 -- FOLD-2: THE FENCE WALKS MARKER-INTACT TEXT, AND THE CUT HAS A FLOOR ═══════════════════════
# Fold-1 fixed the item scope but left the fence running BEHIND `_drop_bare_digit_sentences`, which --
# on the treatment arm only -- eats an ordered item's '1. ' marker before the fence sees the line. Two
# residuals fell out of that one root: F4's widening was INERT on the arm that mutates, and an honest
# ordered item after a convicted bullet was read as a CONTINUATION and deleted uncharged. The fence
# moved above the lint (plan 10.15 G-A); these pin the behaviour the move buys, at the unit, with the
# end-to-end reproductions in section H.
def test_fold2_the_continuation_cut_never_crosses_a_line_that_names_a_stamped_window():
    """G-A's BELT-AND-BRACES GUARD, kept even though the move retired the shape that motivated it. ONE
    LINE AND ONE PIN, defence in depth: whatever a future pass does to the markers upstream, the reader
    may never lose a window the prompt actually carried to a NEIGHBOUR's conviction -- and the ledger
    may never undercount the loss if it did (H1 FIX W2's law: a bullet this pass removed is a bullet the
    reader lost, so it is charged).

    The shape is fold-1's exact reproduction with the marker already gone, which is what the treatment
    arm used to hand the fence: a convicted bullet, then a marker-less line that names a STAMPED
    window. Before the guard the second line rode the cut with charge 1; now the cut stops at it."""
    mech = ("## Episodes\n"
            f"- {_FAKE} -- invented.\n"
            f"  {_SPAN_A} -- real: no citable item in this window.\n")
    st = {"mechanism": mech}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True) == \
        {"spans_checked": 1, "bullets_dropped": 1, "section_seen": True}
    assert st["mechanism"] == f"## Episodes\n  {_SPAN_A} -- real: no citable item in this window.\n"
    assert _FAKE not in st["mechanism"] and _SPAN_A in st["mechanism"]
    # ...and the guard is a membership question, not a shape one: an UNSTAMPED window does not stop it
    st2 = {"mechanism": ("## Episodes\n"
                         f"- {_FAKE} -- invented.\n"
                         "  2018-04..2018-06 -- also invented.\n")}
    assert an._validate_episode_spans(st2, _injected(), handle_prose=True)["bullets_dropped"] == 1
    assert st2["mechanism"] == "## Episodes\n"


def test_fold2_an_honest_ordered_item_after_a_convicted_bullet_is_an_item_not_a_continuation():
    """THE MIXED-MARKER SHAPE, at the unit and on MARKER-INTACT text -- which is the whole of what the
    move buys. `_EPISODE_ITEM_RX` sees '1. ' as an item, so `_episode_continuation` refuses it, so the
    cut stops before it and the honest window stays on the page with a charge of exactly one.

    Under fold-1's position this shape reached the fence with the '1. ' already eaten, and the honest
    fully-backed item was deleted as a continuation while the ledger charged only the convicted bullet:
    a reader loss AND a ledger undercount. Two mechanisms now refuse it -- the item scope on
    marker-intact text, and the stamped-line guard above -- and that redundancy is deliberate."""
    mech = ("## Episodes\n"
            f"- {_FAKE} -- invented.\n"
            f"1. {_SPAN_A} -- real: no citable item in this window.\n")
    st = {"mechanism": mech}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True) == \
        {"spans_checked": 2, "bullets_dropped": 1, "section_seen": True}   # TWO items, one convicted
    assert st["mechanism"] == f"## Episodes\n1. {_SPAN_A} -- real: no citable item in this window.\n"


# ══ D -- THE CENSUS POSTURE: ALWAYS COUNT, MUTATE ONLY UNDER THE KNOB ════════════════════════════════
def test_the_control_arm_counts_and_changes_nothing():
    """H1'S CENSUS POSTURE, and the reason it is not simply an early return on the knob: the walk and the
    membership test run on BOTH arms, so the control lane exercises the identical code path and a walk
    defect cannot hide behind the flag.

    `bullets_dropped` COUNTS BULLETS ACTUALLY REMOVED, so a control row cannot carry the charge BY
    CONSTRUCTION rather than by a second `if` -- which is what makes G1's clause (e-ep) ("zero on every
    control row") an INSTRUMENT CHECK rather than a restatement of the gating."""
    before = _mech(_BACKED_A, _UNBACKED)
    st = {"mechanism": before}
    census = an._validate_episode_spans(st, _injected())              # kwarg OMITTED -- the control call
    assert census == {"spans_checked": 2, "bullets_dropped": 0,       # counted; nothing removed
                      "section_seen": True}
    assert st["mechanism"] == before                                  # byte-identical
    assert an._validate_episode_spans(dict(st), _injected(), handle_prose=False) == census


def test_the_kwarg_defaults_off_so_an_older_caller_is_byte_identical():
    """THE OMIT-WHEN-OFF IDIOM (`_scaffold_cap_kwargs`' own): `handle_prose` is keyword-only with a False
    default, so the control call is spelled without it, and an injected fake or a legacy caller carrying
    the older signature stays valid."""
    sig = inspect.signature(an._validate_episode_spans)
    p = sig.parameters["handle_prose"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is False
    src = inspect.getsource(an._answer_l2) + inspect.getsource(an.answer)
    assert src.count('**({"handle_prose": True} if _handles else {})') == 2   # both bodies, one spelling


def test_nothing_injected_means_every_window_in_the_section_was_minted():
    """RE-ANCHORED AT FOLD-2 (G-B), AND THE OLD READING WAS THE DEFECT. This test used to assert that a
    turn with NO stamped window "declines to judge rather than convicting every bullet". That is exactly
    backwards on the lane it describes: a FULLY-FLOORED record stamps `spans: []` and STILL renders its
    `DATED EPISODES` line, so the persona still asks for the section while the prompt carries no window
    at all -- and every window the model then writes is MINTED BY CONSTRUCTION. The first build shipped
    them, uncharged and unstamped, in the one lane where the fence's subject is guaranteed invention
    (the fold-1 verifier's third finding, driven end to end).

    UNIVERSAL MEMBERSHIP AGAINST THE EMPTY SET IS THE WHOLE MECHANISM: no written token can be a member
    of an empty stamped set, so every windowed bullet convicts, with no second rule and no special
    case."""
    st = {"mechanism": _mech(_UNBACKED)}
    for injected in (None, [], _injected(spans=[]), [{"node": "n", "spans": [], "floored": True}]):
        st2 = dict(st)
        assert an._validate_episode_spans(st2, injected, handle_prose=True) == \
            {"spans_checked": 1, "bullets_dropped": 1, "section_seen": True}
        assert _FAKE not in st2["mechanism"] and "## Episodes" in st2["mechanism"]
        # ...and the control arm still counts without touching a byte (the census posture is unmoved)
        st3 = dict(st)
        assert an._validate_episode_spans(st3, injected) == \
            {"spans_checked": 1, "bullets_dropped": 0, "section_seen": True}
        assert st3["mechanism"] == st["mechanism"]


def test_a_floored_lane_leaves_an_honest_prose_section_alone():
    """THE OTHER DIRECTION OF G-B, which is what stops the empty-set rule from being a whole-section
    remedy on the floored lane. A bullet that names NO window is DECLINED when nothing was stamped: the
    persona's "one bullet per injected WINDOW" clause has no subject on a turn that carried none, so a
    token-less bullet is not evidence of minting. Only a MINTED WINDOW is.

    (With windows carried, the same clause reads exactly as fold-1 pinned it -- a token-less bullet
    inside the section is not an enumeration of one -- and that row is asserted here beside it so the two
    readings cannot drift apart.)"""
    prose = ("## Episodes\nThe record floors every window on this driver, so none is enumerated.\n"
             "- the corpus is silent on the dating here\n")
    st = {"mechanism": prose}
    assert an._validate_episode_spans(st, [], handle_prose=True) == \
        {"spans_checked": 1, "bullets_dropped": 0, "section_seen": True}
    assert st["mechanism"] == prose                                   # byte-identical, floored or not
    # ...and the SAME bullet, on a turn that DID carry windows, is unbacked as fold-1 pinned it
    st2 = {"mechanism": prose}
    assert an._validate_episode_spans(st2, _injected(), handle_prose=True)["bullets_dropped"] == 1


@pytest.mark.parametrize("structured", [None, {}, {"mechanism": None}, {"mechanism": 7}, "not a dict"])
def test_the_instrument_never_raises_and_never_partially_writes(structured):
    """An instrument must not cost an answer. The mechanism is rebuilt ONCE, from one index set, after
    every decision is made, so there is no state in which half a section has been removed."""
    assert an._validate_episode_spans(structured, _injected(), handle_prose=True) == \
        {"spans_checked": 0, "bullets_dropped": 0}


# ══ E -- THE CHARGE: ONE STRIP LEDGER, ONE WRITER ═══════════════════════════════════════════════════
def test_the_class_folds_into_the_one_ledger_and_the_sum_invariant_holds():
    """H1 FIX W2's LAW, applied to the wave's newest remedy: a bullet this pass removed is a bullet the
    reader lost, so it is charged like every other render-side removal, `by_rule` and `stripped`
    together. `sum(by_rule.values()) == stripped` is the ledger's own invariant and is what makes the
    class scan (G1 clause (4)) a complete reading of the page loss."""
    verifier = {"enabled": True, "stripped": 2, "by_rule": {"no_lexical_overlap": 2}}
    assert an._fold_ledger_class(verifier, an._EPISODE_SPAN_UNBACKED_CLASS, 3) == 3
    assert verifier["by_rule"]["episode_span_unbacked"] == 3 and verifier["stripped"] == 5
    assert sum(verifier["by_rule"].values()) == verifier["stripped"]
    # ...and a zero charge is a no-op, which is why the control arm's ledger is byte-identical
    ctl = {"enabled": True, "stripped": 2, "by_rule": {"no_lexical_overlap": 2}}
    before = json.dumps(ctl, sort_keys=True)
    assert an._fold_ledger_class(ctl, an._EPISODE_SPAN_UNBACKED_CLASS, 0) == 0
    assert json.dumps(ctl, sort_keys=True) == before


def test_the_class_name_is_a_declared_constant_and_is_in_no_emf_successor_tuple():
    """THE SPELLING IS THE PIN. A class renamed at the charge site and not in the plan's declared set
    reads as an UNDECLARED class to G1 clause (4), which fails the gate on the wave's own remedy.

    IT IS IN NO `emf` SUCCESSOR TUPLE, and the reason is stronger here than for `slot_orphan`: plan
    10.10(c) forbids any gate clause attributing an AC1 result to D-HP-15, and `KILLED_CLASSES` IS the
    AC1 tuple -- pooling an episode-window conviction into `unconstructible_count` would make that
    attribution by arithmetic, in the wave's headline metric."""
    from leviathan.graphrag import emf
    cls = an._EPISODE_SPAN_UNBACKED_CLASS
    assert cls == "episode_span_unbacked"
    for tup in (emf.KILLED_CLASSES, emf.RESIDUAL_CLASSES, emf.MIS_BOUND_CLASSES, emf.BLINDED_CLASSES):
        assert cls not in tup
    assert cls != emf.BARE_DIGIT_CLASS
    emf_src = pathlib.Path(emf.__file__).read_text(encoding="utf-8")
    assert cls in emf_src and "NOT `KILLED_CLASSES`" in emf_src      # the exclusion is STATED, with why


def test_the_trace_key_is_registered_at_the_tail_with_its_denominator():
    """REGISTRATION IS THE LIFT: a key absent from `TRACE_RECORD_KEYS` reaches NO artifact, silently.
    It appends at the TAIL (eval.py splats the registry IN ORDER), and it carries the DENOMINATOR beside
    the charge -- two drops over 4 bullets and two over 90 are the same numerator and not the same fact,
    so a ceiling read off `bullets_dropped` alone is not computable."""
    assert tk.TRACE_RECORD_KEYS[-1] == "episode_spans_validated"
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)
    assert set(an._validate_episode_spans({"mechanism": _mech(_BACKED_A)}, _injected())) == \
        {"spans_checked", "bullets_dropped", "section_seen"}          # RE-ANCHORED, H1b fold-1 F4


# ══ F -- INERT SEAMS (the X6 decision) ══════════════════════════════════════════════════════════════
class _Report:
    """The seam carrier's shape: `_mint_strip_seam` reads `strip_seams` off the report by attribute."""

    def __init__(self):
        self.strip_seams: list = []


def test_this_producer_mints_no_strip_seam_and_could_not_be_consumed_if_it_did(monkeypatch):
    """THE X6 DECISION, PINNED ON ITS ONE SURVIVING LEG (the position leg was RETIRED at fold-2, when
    the pass moved ABOVE the seven-pass stack and seam consumers now run after it). This is a
    WHOLE-BULLET producer: nothing it removes can leave a value slot empty in a SURVIVING sentence, so
    it is not a slot-emptying producer, could never join `_SLOT_EMPTYING_SEAM_SRCS`, and a seam minted
    here would be a licence-shaped record standing for nothing -- which is exactly what X6 forbids.

    Asserted three ways: no seam constant exists for it, the function contains no mint call, and a live
    carrier is unchanged across a run that dropped a bullet (including under GRAPHRAG_STRIP_AUDIT, where
    the projection would otherwise show up on the verifier dict)."""
    assert an._EPISODE_SPAN_UNBACKED_CLASS not in an._SLOT_EMPTYING_SEAM_SRCS
    assert not [n for n in dir(an) if n.startswith("_SEAM_SRC_") and "episode" in n.lower()]
    assert "_mint_strip_seam" not in inspect.getsource(an._validate_episode_spans)
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    rep, vdict = _Report(), {"enabled": True, "stripped": 0, "by_rule": {}}
    st = {"mechanism": _mech(_BACKED_A, _UNBACKED)}
    assert an._validate_episode_spans(st, _injected(), handle_prose=True)["bullets_dropped"] == 1
    assert rep.strip_seams == [] and "strip_seams" not in vdict
    # RE-ANCHORED AT FOLD-2 (G-A): the pass now runs BEFORE the stack, so seam consumers DO remain in
    # the turn and the old "no consumer is left" leg is retired rather than quietly left standing. The
    # X6 conclusion is unchanged because its load-bearing reason was always the FIRST one -- a producer
    # that removes only WHOLE items mints nothing a consumer could want -- and that is now what is
    # asserted: the class is in no seam-source tuple at all, on either side of the stack.
    for body in ("_answer_l2", "answer"):
        src = inspect.getsource(getattr(an, body))
        assert src.index("_validate_episode_spans(structured,") < src.index("_tidy_strip_orphans(")
    assert an._EPISODE_SPAN_UNBACKED_CLASS not in {getattr(an, n) for n in dir(an)
                                                   if n.startswith("_SEAM_SRC_")}
    assert "RE-ARGUED AT FOLD-2 (G-A)" in inspect.getsource(an)     # the retired leg is recorded, not lost


# ══ G -- THE ONE-HOP LANE ═══════════════════════════════════════════════════════════════════════════
def test_the_one_hop_body_carries_the_same_fence_over_an_empty_stamped_set():
    """D-HP-16's THREE-LANE LAW: every seam ships on the L2 body AND the one-hop body, SPELLED
    IDENTICALLY. `tl.render_line` has exactly one call site (`_l2_blocks`), so the one-hop body injects
    no episode line and passes `injected=None` -- exactly as the scaffold call beside it does.

    RE-ANCHORED AT FOLD-2 (G-B). This pin used to read "a structural no-op on every one-hop turn", and
    that was only ever true because NOTHING WAS STAMPED there -- which is precisely the fully-floored
    lane's shape, the lane where fold-1's verifier proved the early return was fail-OPEN. Under the
    empty-set rule the one-hop lane is fenced by the same sentence as every other: a window the prompt
    never carried cannot be a member of what it carried, so it dies; a bullet naming no window is
    declined. NO ONE-HOP EPISODE PRODUCER IS BUILT -- that would be a scope increase on the documented
    `GRAPHRAG_PLANNER=onehop` rollback lane -- so what is pinned is the SPELLING and the empty-set
    behaviour, in the fail-closed direction the whole item takes."""
    src = inspect.getsource(an.answer)
    assert "_validate_episode_spans(structured, None," in src        # injected=None, like the scaffold
    assert "_maybe_scaffold_episodes(structured, verifier, injected=None" in src
    st = {"mechanism": _mech(_UNBACKED, _BACKED_A)}
    assert an._validate_episode_spans(st, None, handle_prose=True) == \
        {"spans_checked": 2, "bullets_dropped": 2, "section_seen": True}
    assert "## Episodes" in st["mechanism"]                          # the heading is never convicted
    assert _FAKE not in st["mechanism"] and _SPAN_A not in st["mechanism"]
    # ...and a one-hop turn with NO episode section is still untouched, key and all
    st2 = {"mechanism": "## The record\nNo episode section on this turn.\n"}
    assert an._validate_episode_spans(st2, None, handle_prose=True) == \
        {"spans_checked": 0, "bullets_dropped": 0}


# ══ H -- END TO END, CONTROL VERSUS TREATMENT ═══════════════════════════════════════════════════════
_DRAFT_MECH = _mech(_BACKED_A, _UNBACKED,
                    before="## The record\nThe corpus documents frost damage [E1].\n")


def _graph():
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost mech",
                           confidence="medium")],
        convergence=[], inter_commodity=[])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


# ONE report date per episode. With `timeline.MIN_PROPS` == 2 BOTH windows fall below the corroboration
# floor, so `_l2_blocks` takes LEG 1: it stamps `{'spans': [], 'windows': [], 'floored': True}` and STILL
# renders a `DATED EPISODES ...` line, so `_episodes_on` fires and the persona still asks for the section
# while the prompt carries NO window at all. That is the FULLY-FLOORED lane (fold-2 G-B).
_FLOORED_EPISODES = [{"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10"]},
                     {"start": "2021-06-01", "end": "2021-08-20", "dates": ["2021-07-20"]}]


def _turn(knobs, tmp_path, monkeypatch, *, scaffold=False, episodes=None):
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"arabica_coffee": episodes or [
        {"start": "1994-06-10", "end": "1994-08-01",
         "dates": ["1994-06-10", "1994-07-05", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20",
         "dates": ["2021-06-01", "2021-07-20", "2021-08-20"]}]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    if scaffold:                                                     # the OTHER producer, default OFF
        monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)
    tl.reset_cache()

    def fake_call(system, user, *, model, tool, **kw):
        return {"tldr": "Frost risk is the live question.", "diagram_mermaid": "",
                "mechanism": _DRAFT_MECH,
                "sources": [{"ref": 1, "source": "usda_gain", "date": "2021-07-20", "note": "frost"}]}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain",
                 "text": "July frost hit Sul de Minas hard"}]

    return an.answer("where do the arabica frost episodes disagree", graph=_graph(), planner="l2",
                     asof="2026-01-01", retrieve=fake_retrieve, call=fake_call,
                     route_fn=lambda q, gg: ["arabica_coffee"], mode_knobs=knobs)


def test_end_to_end_the_treatment_drops_the_invented_window_and_the_control_does_not(tmp_path,
                                                                                     monkeypatch):
    """THE ITEM'S CENTRAL CLAIM THROUGH A REAL SERVING BODY, one variable: the `deep_hp` knob dict.

    THE TURN IS SUSCEPTIBLE, and that is asserted rather than assumed -- an arm comparison over a turn
    that injected no window proves nothing. Both arms see the same draft, carrying one window the prompt
    CARRIED and one it never did.

    THE CONTROL ARM IS BYTE-IDENTICAL on the page, on the ledger and on the record: the invented window
    ships (which is the shipped behaviour H1b changes), `by_rule` carries no such class, and the trace
    carries no such key. That is what gives clause (e-ep) a control denominator."""
    ctl = _turn(rm.knobs("deep"), tmp_path, monkeypatch)
    trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
    # the turn WAS susceptible: two windows injected, spelled by the one producer
    assert ctl["trace"]["episodes_injected"][0]["spans"] == [_SPAN_A, _SPAN_B]
    # CONTROL: the invented window ships, no class, no column
    assert _FAKE in ctl["structured"]["mechanism"] and _FAKE in ctl["answer"]
    assert ctl["trace"]["citation_verifier"]["by_rule"].get("episode_span_unbacked", 0) == 0
    assert "episode_spans_validated" not in ctl["trace"]
    # TREATMENT: the invented window is gone, the backed one survives, and the loss is ACCOUNTED
    assert _FAKE not in trt["structured"]["mechanism"] and _FAKE not in trt["answer"]
    assert _SPAN_A in trt["structured"]["mechanism"]
    assert trt["trace"]["citation_verifier"]["by_rule"]["episode_span_unbacked"] == 1
    assert trt["trace"]["episode_spans_validated"] == {"spans_checked": 2, "bullets_dropped": 1,
                                                       "section_seen": True}
    vr = trt["trace"]["citation_verifier"]
    assert sum(vr["by_rule"].values()) == vr["stripped"]              # the ledger's own invariant


def test_end_to_end_fold1_the_mixed_bullet_dies_and_is_charged_on_the_treatment_arm(tmp_path,
                                                                                    monkeypatch):
    """FIX F1 THROUGH A REAL SERVING BODY, which is where the review found it and therefore where it is
    pinned. The draft's ONLY episode bullet names a stamped window AND a fabricated one -- the shape the
    SELECT persona invites. Under the existential form this row shipped the fabrication to the reader
    with `bullets_dropped=0`, a clean `by_rule` and a clean (e-ep) ceiling: gate-invisible, which is the
    exact failure mode clause (e-ep) was pre-registered to prevent.

    THE CONTROL ARM IS UNCHANGED by this fix, so the fold does not move the off arm: the fabricated
    window still ships there, no class, no key."""
    global _DRAFT_MECH
    keep = _DRAFT_MECH
    try:
        _DRAFT_MECH = _mech(_MIXED_LEAD, before="## The record\nThe corpus documents frost [E1].\n")
        ctl = _turn(rm.knobs("deep"), tmp_path, monkeypatch)
        trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
        assert ctl["trace"]["episodes_injected"][0]["spans"] == [_SPAN_A, _SPAN_B]   # susceptible turn
        assert _FAKE in ctl["structured"]["mechanism"] and _FAKE in ctl["answer"]
        assert "episode_spans_validated" not in ctl["trace"]
        assert _FAKE not in trt["structured"]["mechanism"] and _FAKE not in trt["answer"]
        assert "the great disruption" not in trt["answer"]             # the WHOLE bullet, not a fragment
        assert trt["trace"]["citation_verifier"]["by_rule"]["episode_span_unbacked"] == 1
        assert trt["trace"]["episode_spans_validated"] == {"spans_checked": 1, "bullets_dropped": 1,
                                                           "section_seen": True}
        vr = trt["trace"]["citation_verifier"]
        assert sum(vr["by_rule"].values()) == vr["stripped"]            # the ledger's own invariant
    finally:
        _DRAFT_MECH = keep


_ORDERED_DRAFT = ("## The record\nThe corpus documents frost [E1].\n"
                  "## Episodes\n"
                  f"1. {_FAKE} -- invented.\n"
                  f"2. {_SPAN_A} -- real: no citable item in this window.\n"
                  "## What to watch\nFurther cold fronts.\n")
_MIXED_MARKER_DRAFT = ("## The record\nThe corpus documents frost [E1].\n"
                       "## Episodes\n"
                       f"- {_FAKE} -- invented.\n"
                       f"1. {_SPAN_A} -- real: no citable item in this window.\n"
                       "## What to watch\nFurther cold fronts.\n")


def test_end_to_end_fold2_the_ordered_list_reproduction_dies_charged_on_the_treatment_arm(tmp_path,
                                                                                          monkeypatch):
    """THE FOLD-2 ROOT PIN (G-A), AND IT IS END TO END BECAUSE THAT IS WHERE FOLD-1's FIX WAS INERT.
    Fold-1 widened the fence's item scope to ordered markers and pinned it AT THE UNIT, where it passed;
    the fold-1 verifier then drove this exact draft through a real serving body and found the fabricated
    window STILL ON THE PAGE with a clean `by_rule`. The cause was position, not scope:
    `_drop_bare_digit_sentences` -- treatment-only -- ate the '1. ' marker as a bare-digit sentence
    BEFORE the fence walked the text, so a numbered `## Episodes` section had no items on the only arm
    that mutates (items found: [] on treatment, [3, 4] on control).

    THE FENCE NOW WALKS MARKER-INTACT TEXT, so an ordered item is an item: the fabricated window dies,
    is CHARGED, and both items are counted in the denominator. The honest one stays on the page.

    THE LINT'S OWN CHARGES ARE NOT THIS PASS'S BUSINESS and are deliberately not suppressed: the marker
    that survives the fence is still eaten downstream as a bare digit and charged as `bare_digit`, which
    is D-HP-12's shipped behaviour on the treatment arm. What the ledger must show is that this pass's
    loss is ITS OWN class and that the one invariant holds over both."""
    global _DRAFT_MECH
    keep = _DRAFT_MECH
    try:
        _DRAFT_MECH = _ORDERED_DRAFT
        ctl = _turn(rm.knobs("deep"), tmp_path, monkeypatch)
        trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
        assert ctl["trace"]["episodes_injected"][0]["spans"] == [_SPAN_A, _SPAN_B]   # susceptible turn
        # CONTROL: unchanged by this fold -- the ordered list ships whole, no class, no key
        assert ctl["structured"]["mechanism"] == _ORDERED_DRAFT
        assert _FAKE in ctl["answer"] and "episode_spans_validated" not in ctl["trace"]
        # TREATMENT: the fabricated window is gone, the honest one is not, and BOTH were counted
        assert _FAKE not in trt["structured"]["mechanism"] and _FAKE not in trt["answer"]
        assert "invented" not in trt["answer"]                        # the WHOLE item, not a fragment
        assert _SPAN_A in trt["structured"]["mechanism"] and _SPAN_A in trt["answer"]
        assert trt["trace"]["episode_spans_validated"] == {"spans_checked": 2, "bullets_dropped": 1,
                                                           "section_seen": True}
        vr = trt["trace"]["citation_verifier"]
        assert vr["by_rule"]["episode_span_unbacked"] == 1
        assert sum(vr["by_rule"].values()) == vr["stripped"]          # the ledger's own invariant
    finally:
        _DRAFT_MECH = keep


def test_end_to_end_fold2_the_honest_ordered_item_survives_a_convicted_neighbour(tmp_path, monkeypatch):
    """THE SECOND RESIDUAL FOLD-1 CREATED, DRIVEN AWAY AT THE SAME ROOT. With the fence behind the digit
    lint, the honest ordered item below was no longer an ITEM to the fence -- it was a marker-less line
    directly under a convicted bullet, i.e. a CONTINUATION -- so F3's cut swallowed it and the ledger
    charged only the convicted one. The verifier drove it pre-fold-versus-folded: the backed window was
    kept before fold-1 and GONE after, with the charge unchanged at 1. That is a reader loss AND a
    ledger undercount against H1 FIX W2's law.

    MARKER-INTACT TEXT MAKES IT AN ITEM AGAIN, and the belt-and-braces guard (`_episode_line_is_backed`)
    would stop the cut at it even if some future pass de-markered it anyway. One line and one pin,
    defence in depth -- the fold-1 verifier's own prescription."""
    global _DRAFT_MECH
    keep = _DRAFT_MECH
    try:
        _DRAFT_MECH = _MIXED_MARKER_DRAFT
        ctl = _turn(rm.knobs("deep"), tmp_path, monkeypatch)
        trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
        assert ctl["structured"]["mechanism"] == _MIXED_MARKER_DRAFT   # control untouched by the fold
        assert "episode_spans_validated" not in ctl["trace"]
        assert _FAKE not in trt["answer"] and "invented" not in trt["answer"]
        assert _SPAN_A in trt["structured"]["mechanism"] and _SPAN_A in trt["answer"]
        assert "real: no citable item in this window." in trt["structured"]["mechanism"]
        assert trt["trace"]["episode_spans_validated"] == {"spans_checked": 2, "bullets_dropped": 1,
                                                           "section_seen": True}
        vr = trt["trace"]["citation_verifier"]
        assert vr["by_rule"]["episode_span_unbacked"] == 1
        assert sum(vr["by_rule"].values()) == vr["stripped"]
    finally:
        _DRAFT_MECH = keep


def test_end_to_end_fold2_the_fully_floored_lane_convicts_every_minted_window(tmp_path, monkeypatch):
    """FOLD-2 G-B THROUGH A REAL SERVING BODY, on the lane where the fence's subject is guaranteed to be
    invention. Every window on this node falls below the corroboration floor, so `_l2_blocks` LEG 1
    stamps `spans: []` and STILL renders its `DATED EPISODES` line: the persona asks for the section
    while the prompt carries no window at all, so EVERY window the model writes is MINTED BY
    CONSTRUCTION. The first build returned early on `not stamped` and shipped them uncharged and
    unstamped -- fail-OPEN, in the one lane that cannot be anything else.

    UNIVERSAL MEMBERSHIP AGAINST THE EMPTY SET IS THE WHOLE MECHANISM: no written token is a member of
    an empty set, so both bullets die, both are charged, and the denominator says two were examined. The
    HEADING survives, as it does on every other row (a heading is not convicted).

    THE CENSUS POSTURE IS UNCHANGED AND THE CONTROL CONTRACT IS FOLD-1'S EXACTLY: no key, no charge, and
    a byte-identical page on the control arm."""
    global _DRAFT_MECH
    keep = _DRAFT_MECH
    try:
        _DRAFT_MECH = _mech(f"{_SPAN_A} -- the first frost: no citable item in this window.",
                            _UNBACKED, before="## The record\nThe corpus documents frost [E1].\n")
        ctl = _turn(rm.knobs("deep"), tmp_path, monkeypatch, episodes=_FLOORED_EPISODES)
        trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch, episodes=_FLOORED_EPISODES)
        # the lane really is the floored one: a record with the flag, no spans, and a rendered line
        rec = ctl["trace"]["episodes_injected"][0]
        assert rec["spans"] == [] and rec.get("floored") is True and rec["line"]
        # CONTROL: byte-identical page, no key, no charge -- fold-1's contract, unmoved
        assert ctl["structured"]["mechanism"] == _DRAFT_MECH
        assert _FAKE in ctl["answer"] and _SPAN_A in ctl["answer"]
        assert "episode_spans_validated" not in ctl["trace"]
        assert ctl["trace"]["citation_verifier"]["by_rule"].get("episode_span_unbacked", 0) == 0
        # TREATMENT: both minted windows die, both are charged, the heading stands
        assert _FAKE not in trt["answer"] and _SPAN_A not in trt["answer"]
        assert "## Episodes" in trt["structured"]["mechanism"]
        assert trt["trace"]["episode_spans_validated"] == {"spans_checked": 2, "bullets_dropped": 2,
                                                           "section_seen": True}
        vr = trt["trace"]["citation_verifier"]
        assert vr["by_rule"]["episode_span_unbacked"] == 2
        assert sum(vr["by_rule"].values()) == vr["stripped"]
    finally:
        _DRAFT_MECH = keep


def test_end_to_end_fold2_a_floored_prose_section_ships_untouched(tmp_path, monkeypatch):
    """THE INNOCENT HALF OF G-B, which is what keeps the empty-set rule a FENCE and not a whole-section
    remedy on the floored lane. The persona's own instruction to a fully-floored node is to say the
    record is thin and write NO window -- so a model that obeys it writes prose, and prose naming no
    window is exactly what the empty-set rule must leave alone.

    `_episode_bullet_unbacked` DECLINES a token-less bullet when nothing was stamped (the "one bullet per
    injected WINDOW" clause has no subject on a turn that carried none), so `section_seen` is stamped,
    the item is counted, and not one byte moves. Only a MINTED WINDOW dies."""
    global _DRAFT_MECH
    keep = _DRAFT_MECH
    try:
        _DRAFT_MECH = ("## The record\nThe corpus documents frost [E1].\n"
                       "## Episodes\nThe record floors every window here, so none is enumerated.\n"
                       "- the corpus is silent on the dating for this driver\n"
                       "## What to watch\nFurther cold fronts.\n")
        trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch, episodes=_FLOORED_EPISODES)
        assert trt["structured"]["mechanism"] == _DRAFT_MECH           # byte-identical, floored or not
        assert trt["trace"]["episode_spans_validated"] == {"spans_checked": 1, "bullets_dropped": 0,
                                                           "section_seen": True}
        assert "episode_span_unbacked" not in trt["trace"]["citation_verifier"]["by_rule"]
    finally:
        _DRAFT_MECH = keep


def test_end_to_end_the_model_authored_column_survives_disposition_b_plus(tmp_path, monkeypatch):
    """THE COLUMN-COLLAPSE RISK, CLOSED BY THE SHAPE CHOICE. Under the REJECTED disposition (a) -- full
    engine authorship -- `episodes_model_authored` could only ever be False on the treatment arm, which
    silently collapses a control-vs-treatment column the G1 artifact reads, and re-keys the five episode
    eval pins into scaffold tautologies. Under (b+) the MODEL still authors the section on BOTH arms and
    the column keeps measuring the writer. Read with the OTHER producer ON, which is the only
    configuration in which the column is stamped at all."""
    ctl = _turn(rm.knobs("deep"), tmp_path, monkeypatch, scaffold=True)
    trt = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch, scaffold=True)
    assert ctl["trace"]["episodes_model_authored"] is True
    assert trt["trace"]["episodes_model_authored"] is True
    assert trt["trace"]["episodes_scaffolded"]["fired"] is False      # the model wrote it; no synthesis
    # ...and the drop still happened, so (b+) is not "the scaffold branch does the work"
    assert trt["trace"]["episode_spans_validated"]["bullets_dropped"] == 1
    assert _FAKE in ctl["structured"]["mechanism"] and _FAKE not in trt["structured"]["mechanism"]


def test_end_to_end_a_clean_treatment_row_still_reports_its_denominator(tmp_path, monkeypatch):
    """THE ONE DEPARTURE FROM THE ABSENT-WHEN-NOTHING-FIRED IDIOM, and it is deliberate: a ceiling on
    drops is unreadable without the count of bullets examined, so a CLEAN treatment row still stamps
    `{spans_checked: n, bullets_dropped: 0}`.

    AND THE STAMP RULE IS `section_seen`, NOT `spans_checked` (H1b fold-1 F4). Three rows, three
    distinguishable readings: a section with items (denominator n), a section whose items were all out
    of scope (denominator 0, KEY STILL STAMPED), and NO SECTION AT ALL (no key). Stamping on
    `spans_checked` collapsed the middle row into the last one, which is precisely the blindness clause
    (e-ep)(ii)'s denominator exists to remove -- a G1 reader could not tell a row this fence never
    examined from a row it had nothing to examine."""
    global _DRAFT_MECH
    keep = _DRAFT_MECH
    try:
        _DRAFT_MECH = _mech(_BACKED_A, before="## The record\nFrost damage [E1].\n")
        clean = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
        assert clean["trace"]["episode_spans_validated"] == {"spans_checked": 1, "bullets_dropped": 0,
                                                             "section_seen": True}
        assert "episode_span_unbacked" not in clean["trace"]["citation_verifier"]["by_rule"]
        _DRAFT_MECH = ("## The record\nFrost damage [E1].\n"
                       "## Episodes\nThe record carries two windows and no enumeration of them.\n")
        bare = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
        assert bare["trace"]["episode_spans_validated"] == {"spans_checked": 0, "bullets_dropped": 0,
                                                            "section_seen": True}
        _DRAFT_MECH = "## The record\nNo episode section at all here [E1].\n"
        none = _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
        assert "episode_spans_validated" not in none["trace"]
    finally:
        _DRAFT_MECH = keep


def test_end_to_end_the_persona_carries_the_select_leg_on_the_treatment_arm_only(tmp_path, monkeypatch):
    """THE PROMPT HALF OF THE BUNDLE, read off the OUTSIDE. The select-order-connect variant reaches the
    model exactly when the treatment is active AND the episode mandate is already there -- one
    conjunction, and the control persona is byte-identical to today's."""
    seen: dict = {}
    real = an._system

    def spy(**kw):
        out = real(**kw)
        seen[bool(kw.get("handles"))] = out
        return out

    monkeypatch.setattr(an, "_system", spy)
    _turn(rm.knobs("deep"), tmp_path, monkeypatch)
    _turn(rm.knobs("deep_hp"), tmp_path, monkeypatch)
    assert an._SYSTEM_EPISODES in seen[False] and an._SYSTEM_EPISODES_SELECT not in seen[False]
    assert an._SYSTEM_EPISODES_SELECT in seen[True]


# ══ I -- THE SAME-CHANGE LAW: THE CLASS IS DECLARED AND BUDGETED IN THE PLAN ════════════════════════
def test_the_class_is_declared_in_g1_clause_4_and_budgeted_by_clause_e_ep():
    """THE `slot_orphan` PRECEDENT, APPLIED IN THE SAME CHANGE. G1 clause (4) is "zero classes outside
    THE D-HP DECLARED SET", pre-registered and frozen -- so a new charging class that is not added to it
    IN THIS CHANGE pre-registers the gate to fail on the wave's own remedy. G1 does not open until H1b
    lands with its pins (plan 10.10), which is exactly why the plan edit is part of the build and not a
    follow-up.

    AND THE ITEM MUST BE VISIBLE TO A GATE AT ALL: before H1b there was NO G1 clause that could fail if
    the episode behaviour were wrong. Clause (e-ep) is that clause, and it is read here so a later edit
    cannot quietly drop it."""
    plan = _PLAN.read_text(encoding="utf-8", errors="replace")
    head, _, tail = plan.partition("### D-HP-21: G1")
    clause4 = tail.partition("(5) REPLACED")[0]
    assert "episode_span_unbacked" in clause4, "clause (4) does not declare the class H1b charges"
    assert "(e-ep)" in tail and "episode_span_unbacked == 0" in tail
    assert "10.13" in plan and "D-HP-15" in head


def test_no_gate_clause_attributes_an_ac1_result_to_this_item():
    """PLAN 10.10(c), asserted rather than remembered. The item ships for CONSISTENCY with the wave, not
    for volume: 0.9% of typed numerals, 1.5% of strip rows. The (e-ep) clause is a REPORTED ceiling plus
    a control-arm zero -- it names none of the four AC1 classes, and the class it does name is in no
    `emf` successor tuple (pinned above)."""
    from leviathan.graphrag import emf
    plan = _PLAN.read_text(encoding="utf-8", errors="replace")
    e_ep = plan.partition("(e-ep)")[2].partition("\nALSO PRODUCED HERE")[0]
    for ac1 in emf.KILLED_CLASSES:
        assert ac1 not in e_ep, f"clause (e-ep) names an AC1 class ({ac1}) -- 10.10(c) forbids it"
