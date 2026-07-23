"""CONVERGENCE_TIER1 register-surface lane (mirror of test_reroute_v2_surface.py): the T1 intensity
vocabulary and the T2a pace phrasings must pass EVERY register fence with 0 hits; the fenced valuation
words (overdone/overshot) and the momentum-class pace words (accelerating et al.) must FAIL their fence.
Pure/hermetic -- no AWS, no LLM, no pg."""
from __future__ import annotations

from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq


def _clean(text: str) -> bool:
    return not (reg.register_leaks(text) or reg.count_valuation_words(text) or reg.count_flow_words(text))


# -- T1 vocabulary: moderate/strong/extreme/elevated pass 0 fences ---------------------------------------
def test_t1_intensity_vocabulary_passes_all_fences():
    for w in ("moderate", "strong", "extreme", "elevated"):
        s = f"conditions consistent with a {w} stocks-to-use anomaly (z=-2.4)"
        assert _clean(s), f"{w!r} tripped a fence"
    # the full receipt shape the answer path renders
    assert _clean("ending_stocks_su_ratio (OBSERVED 0.08 S/U, z=-2.4, consistent with a strong anomaly, "
                  "psd_ending_stock_su_ratio 2012-08-10)")
    assert _clean("consistent with an elevated ONI anomaly (0.6)")


def test_t1_fenced_valuation_words_fail():
    # overdone/overshot are valuation-fenced (register.py R2) -- the T1 surface must never mint them
    assert reg.count_valuation_words("the move looks overdone") >= 1
    assert reg.count_valuation_words("stocks-to-use has overshot") >= 1
    assert reg.register_leaks("the rally is overdone")             # rides register_leaks too (Lane A)
    assert not reg.sanitize("The z is high. The rally is overdone.").count("overdone")   # strip, not paraphrase


# -- T2a pace phrasings: the three SAFE past-tense shapes pass 0 fences ----------------------------------
def test_t2_pace_phrasings_pass_all_fences():
    safe = ("rose in each of the last 3 weeks [N4]",
            "the weekly pace was 742.5, up 12.5 from the prior week [N5]",
            "the 4th-highest weekly reading in the series [N6]")
    for s in safe:
        assert _clean(s), f"pace phrasing tripped a fence: {s!r}"
        assert cq.pace_register_ok(s), f"pace phrasing tripped the momentum fence: {s!r}"
    # the engine's own emitted line shapes
    assert _clean("- [N7] change in weekly_exports_1000mt from the prior week (weekly pace): +50 1000 MT")
    assert _clean("- [N8] fell in each of the last 2 months")


def test_t2_momentum_class_fails_the_pace_fence():
    # BANNED on the pace surface (present-continuous / momentum-adjacent / forward-leaning). These are
    # deliberately NOT in register.py's global lexicons (fencing 'slowing'/'momentum' globally would strip
    # honest ag prose), so the fence that must catch them is cascade.pace_register_ok -- the only surface
    # that could mint them.
    for bad in ("export pace is accelerating", "shipments are decelerating", "upside momentum",
                "gaining steam into the new year", "demand is picking up", "the pace is slowing"):
        assert not cq.pace_register_ok(bad), f"momentum-class phrase passed the pace fence: {bad!r}"


def test_t2_engine_lines_filtered_by_the_pace_fence():
    # the belt inside _pace_legs: any line that somehow carried a banned word would be dropped, not served
    assert cq._PACE_BANNED_RX.search("momentum")
    assert not cq._PACE_BANNED_RX.search("rose in each of the last 3 weeks")


def test_squeeze_fence_unaffected_by_pace_vocab():
    # [SKEPTIC F3] regression: 'building' trips ONLY with a squeeze stem present; pace prose carries neither
    assert not reg.count_flow_words("stocks fell for 3 weeks; the pace was 742.5 [N1]")
    assert reg.count_flow_words("a squeeze is building")           # the squeeze-stem class still fences
