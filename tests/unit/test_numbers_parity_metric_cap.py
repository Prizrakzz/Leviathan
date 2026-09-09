"""THE PARITY METRIC CAP: the fence that quietly stopped proving pct_harvested.

THE DEFECT, measured. ``jobs/utils/numbers_parity.main`` built its grid as

    metric_list = list(ts.metrics) if ts.shape == "tall" else list(ts.metrics)[:4]

-- a TALL card's metrics are row VALUES so all of them ran, and a WIDE card was sampled at its first
four on the argument that "metrics == columns, cheap, representative at 4". The cap was SILENT. It
dropped ``silver_nass_crop_progress``'s fifth declared metric ``pct_harvested``: the D-SG G1-5
calendar-structural column, the ONE column on that card with its own season floor in the F010
registry (``min_nonnull_frac_season_overrides``), i.e. the one whose behaviour somebody had gone to
the trouble of calibrating. It was never compared on either backend, at any as-of, in any run of
this gate -- and the report said ``## verdict: N/N exact-match`` with no hint that a metric was
missing. Same class as the rest of the 2026-09-09 NASS gate RCA: a fence whose input was never
measured, in this case the fence's own coverage.

WHY THE FIX IS A WIDTH RULE AND NOT "LIFT THE CAP". Measured offline through the real numbers
registry on 2026-09-09: lifting it estate-wide takes the grid from 582 legs to 1,254 (+672, +115%),
and 630 of that comes from three sampler-shaped cards -- silver_pink_sheet (76 metrics, +432),
silver_fred_fx (28, +144), silver_psd (13, +54). pink_sheet's first four are DELIBERATELY ordered
for this panel (the W2 card spans price / fertilizer / energy / zscore), so comparing all 76 would
more than double a blocking in-VPC gate to re-prove a design decision. The rule is therefore by
WIDTH: a wide card of at most ``FULL_METRIC_MAX`` metrics is compared in full, a wider one keeps the
sample AND now NAMES what it dropped. Measured cost: +42 legs (582 -> 624, +7.2%) -- silver_cot
(+24) and silver_noaa_oni / silver_mpob / silver_nass_crop_progress (+6 each).

Pure + offline: ``metric_plan`` takes a shape and a metric list, and the registry assertions read the
tracked ``configs/graphrag/numbers/tables.yaml``. No Athena, no pg, no network.
"""
from __future__ import annotations

import pytest

from jobs.utils.numbers_parity import (
    AGGS,
    ASOFS,
    FULL_METRIC_MAX,
    SAMPLE_COMMODITY,
    WIDE_METRIC_CAP,
    metric_plan,
)


def _head_metric_list(shape, metrics):
    """Exactly what main() computed before this change -- the baseline every claim is measured against."""
    return list(metrics) if shape == "tall" else list(metrics)[:4]


# ---------------------------------------------------------------------------
# 1. The rule.
# ---------------------------------------------------------------------------
def test_a_narrow_wide_card_is_compared_in_full_and_drops_nothing():
    metrics = [f"m{i}" for i in range(FULL_METRIC_MAX)]
    compared, dropped = metric_plan("wide", metrics)
    assert compared == metrics and dropped == []


def test_a_card_one_metric_past_the_width_keeps_the_sample_and_names_the_rest():
    metrics = [f"m{i}" for i in range(FULL_METRIC_MAX + 1)]
    compared, dropped = metric_plan("wide", metrics)
    assert compared == metrics[:WIDE_METRIC_CAP]
    assert dropped == metrics[WIDE_METRIC_CAP:]
    assert compared + dropped == metrics, "every declared metric is accounted for, one side or the other"


def test_a_tall_card_is_always_compared_in_full():
    """Unchanged from HEAD (Attack 3 #4): a tall card's metrics are row values, so a dropped one is
    a whole series nobody compares."""
    metrics = [f"m{i}" for i in range(30)]
    assert metric_plan("tall", metrics) == (metrics, [])


def test_an_empty_card_is_not_a_crash():
    assert metric_plan("wide", []) == ([], [])


# ---------------------------------------------------------------------------
# 2. THE DEFECT ITSELF, on the real card.
# ---------------------------------------------------------------------------
def test_pct_harvested_now_builds_a_leg():
    """THE regression pin for this whole item. ``silver_nass_crop_progress`` declares five metrics
    and ``pct_harvested`` is the fifth; HEAD compared four."""
    from leviathan.graphrag.numbers.registry import load_registry

    ts = load_registry().get("silver_nass_crop_progress")
    metrics = list(ts.metrics)
    assert "pct_harvested" in metrics
    assert "pct_harvested" not in _head_metric_list(ts.shape, metrics), (
        "if this ever fails the card was re-ordered; the defect was the CAP, not the position, so "
        "re-derive the pin rather than deleting it")
    compared, dropped = metric_plan(ts.shape, metrics)
    assert "pct_harvested" in compared and dropped == []
    assert len(compared) * len(ASOFS) * len(AGGS) == 30, "5 metrics x 3 as-ofs x 2 aggs"


def test_the_floor_calibrated_columns_of_the_nass_cards_are_all_compared():
    """The narrower statement behind the pin: a column the F010 registry bothered to calibrate a
    floor for is a column the parity gate must actually compare. Both NASS cards, every metric."""
    from leviathan.graphrag.numbers.registry import load_registry
    from leviathan.silver.registry import load_registry as load_silver

    reg = load_registry()
    silver = load_silver()
    for tid in ("silver_nass_annual", "silver_nass_crop_progress"):
        compared, dropped = metric_plan(reg.get(tid).shape, reg.get(tid).metrics)
        assert dropped == [], tid
        contract = silver.table(tid)
        calibrated = set(contract.get("min_nonnull_frac_overrides") or {}) | set(
            contract.get("min_nonnull_frac_season_overrides") or {})
        assert calibrated <= set(compared), (tid, sorted(calibrated - set(compared)))


# ---------------------------------------------------------------------------
# 3. THE COST, measured through the real registry rather than asserted.
# ---------------------------------------------------------------------------
def test_the_measured_cost_of_the_width_rule_stays_bounded():
    """The number that justified the rule, re-derived here so a card growing wide enough to double
    the gate's runtime trips a test instead of a Tuesday. HEAD 582 legs -> 624 (+42, +7.2%)."""
    from leviathan.graphrag.numbers.registry import load_registry
    from jobs.utils.numbers_parity import PG_MIRROR_TABLES

    reg = load_registry()
    head = new = 0
    for tid in SAMPLE_COMMODITY:
        if tid not in reg.tables or tid not in PG_MIRROR_TABLES:
            continue
        ts = reg.get(tid)
        head += len(_head_metric_list(ts.shape, ts.metrics))
        new += len(metric_plan(ts.shape, ts.metrics)[0])
    legs = len(ASOFS) * len(AGGS)
    assert head * legs == 582
    assert new * legs == 624
    assert new * legs <= head * legs * 1.25, (
        "the width rule must stay a trim, not a doubling; if a card grew, re-measure and decide "
        "deliberately rather than letting the gate's runtime drift")


def test_the_three_sampler_cards_still_keep_the_cap_and_are_named():
    """pink_sheet / fred_fx / psd are the reason the cap exists at all. They must stay capped -- and
    the metrics they drop must be RETURNED, because a cap nobody can see is the defect."""
    from leviathan.graphrag.numbers.registry import load_registry

    reg = load_registry()
    for tid, declared in (("silver_pink_sheet", 76), ("silver_fred_fx", 28), ("silver_psd", 13)):
        ts = reg.get(tid)
        assert len(list(ts.metrics)) == declared, (tid, len(list(ts.metrics)))
        compared, dropped = metric_plan(ts.shape, ts.metrics)
        assert len(compared) == WIDE_METRIC_CAP
        assert len(dropped) == declared - WIDE_METRIC_CAP
        assert dropped, "a silent cap is the defect; main() prints these"


@pytest.mark.parametrize("tid", ["silver_nass_annual", "silver_nass_crop_progress"])
def test_the_nass_cards_still_carry_the_sample_commodity_the_rca_added(tid):
    """Guard rail: comparing all five metrics proves nothing if the spec cannot build. The
    SAMPLE_COMMODITY entry and the SPEC-INVALID-PANEL guard are what keep this honest."""
    assert SAMPLE_COMMODITY[tid] == "corn_cbot"
