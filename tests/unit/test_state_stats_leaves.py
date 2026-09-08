"""The STATE BOARD's four stats leaves -- STATE ENGINE DESIGN sec 2.5 (D14), sitting S1.

Every expectation below is HAND-COMPUTED and written out in the test, never read back from the function
under test: a fixture that asks the calculator what the answer is proves only that it is deterministic.
"""
import math

import pytest
from leviathan.graphrag.numbers import stats as st


# ── the AM-3 fence: four ENGINE calculators, and the agent's enum is untouched ────────────────────────
def test_the_four_leaves_are_public_and_outside_the_agent_tool_enum():
    for name in ("regime_flag", "flag_events", "pace_vs_prior", "rolling_zscore"):
        assert callable(getattr(st, name)), name
        assert name not in st.STAT_REGISTRY, f"{name} widened the AGENT's tool enum (AM-3 forbids it)"
        assert name in st.ENGINE_STAT_NAMES
        assert not st.is_banned_name(name)


def test_the_shipped_agent_enum_is_byte_identical_to_what_it_held():
    assert sorted(st.STAT_REGISTRY) == [
        "extrema", "percentile", "revision_count", "spread", "streak", "window_change", "yoy_delta",
        "zscore"]
    assert st.STAT_NAMES == frozenset(st.STAT_REGISTRY)


def test_the_floors_are_inherited_not_re_declared():
    """ONE floor family (the AM-3 rule the module states about MIN_QUANTILE_N). A second, laxer constant
    beside a new consumer is the drift these identities exist to make impossible."""
    assert st.MIN_FLAG_N is st.MIN_EXTREMA_N
    assert st.MIN_ROLLING_Z_N is st.MIN_ZSCORE_N


# ── regime_flag -- ORDERING ONLY ─────────────────────────────────────────────────────────────────────
def test_abs_bands_take_the_highest_matching_rung_and_below_the_first_there_is_no_label():
    bands, labels = [0.5, 1.0, 1.5, 2.0], ["elevated", "moderate", "strong", "extreme"]
    # hand-computed: |1.6| clears 1.5 and not 2.0 -> the 1.5 rung
    r = st.regime_flag(1.6, bands, labels, kind="abs_bands")
    assert (r["value"], r["band"], r["matched"]) == ("strong", 1.5, True)
    # the SIGN is not the label's business on an abs_bands kind: -2.4 is 'extreme' too (La Nina)
    assert st.regime_flag(-2.4, bands, labels, kind="abs_bands")["value"] == "extreme"
    # below the first cut: a real, stated outcome -- NOT a decline
    q = st.regime_flag(0.3, bands, labels, kind="abs_bands")
    assert q["declined"] is False and q["value"] is None and q["matched"] is False
    # exactly ON a cut takes it (>=)
    assert st.regime_flag(0.5, bands, labels, kind="abs_bands")["value"] == "elevated"


def test_percentile_bands_are_tail_cuts_and_the_most_extreme_match_wins():
    bands, labels = [10, 25, 75, 90], ["very tight", "tight", "ample", "very ample"]
    assert st.regime_flag(4.0, bands, labels, kind="percentile_bands")["value"] == "very tight"
    assert st.regime_flag(18.0, bands, labels, kind="percentile_bands")["value"] == "tight"
    assert st.regime_flag(50.0, bands, labels, kind="percentile_bands")["value"] is None
    assert st.regime_flag(80.0, bands, labels, kind="percentile_bands")["value"] == "ample"
    assert st.regime_flag(97.0, bands, labels, kind="percentile_bands")["value"] == "very ample"


def test_a_percentile_cut_at_fifty_is_refused_because_it_is_not_a_tail():
    r = st.regime_flag(60.0, [50], ["high"], kind="percentile_bands")
    assert r["declined"] is True and "not a tail" in r["reason"]


def test_pace_bands_are_signed_and_the_middle_is_unlabelled():
    bands, labels = [-10, 10], ["behind", "ahead"]
    assert st.regime_flag(-12.0, bands, labels, kind="pace_vs_prior_year")["value"] == "behind"
    assert st.regime_flag(0.0, bands, labels, kind="pace_vs_prior_year")["value"] is None
    assert st.regime_flag(11.0, bands, labels, kind="pace_vs_prior_year")["value"] == "ahead"
    # and NOT an absolute value: -12 must never read as 'ahead'
    assert st.regime_flag(-12.0, bands, labels, kind="pace_vs_prior_year")["value"] != "ahead"


def test_every_malformed_declaration_declines_loudly_because_the_bands_come_from_a_curated_yaml():
    assert st.regime_flag(1.0, [1.0], ["x"], kind="sigma")["declined"] is True
    assert st.regime_flag(1.0, [], [], kind="abs_bands")["declined"] is True
    assert st.regime_flag(1.0, [1.0, 2.0], ["only one"], kind="abs_bands")["declined"] is True
    assert st.regime_flag(1.0, [2.0, 1.0], ["a", "b"], kind="abs_bands")["declined"] is True   # unordered
    assert st.regime_flag(1.0, [1.0], ["x"], kind="pace_vs_prior_year")["declined"] is True    # one cut


# ── flag_events ──────────────────────────────────────────────────────────────────────────────────────
def test_flag_events_hand_computed():
    series = [0, 1, 0, 0, 1, 0, 0]
    dates = ["2020-01", "2020-02", "2020-03", "2020-04", "2020-05", "2020-06", "2020-07"]
    r = st.flag_events(series, dates, window_periods=4)
    # hand-computed: events at index 1 and 4; the last four periods are indices 3..6 -> one event
    assert r["events_total"] == 2
    assert r["events_in_window"] == 1
    assert r["value"] == 1.0
    assert r["last_event_date"] == "2020-05"
    assert r["periods_since"] == 2                      # index 6 minus index 4
    assert r["first_date"] == "2020-01" and r["last_date"] == "2020-07"


def test_zero_events_is_an_ANSWER_not_a_decline():
    r = st.flag_events([0, 0, 0], ["a", "b", "c"], window_periods=2)
    assert r["declined"] is False
    assert r["events_in_window"] == 0 and r["last_event_date"] is None and r["periods_since"] is None


def test_flag_events_needs_a_parallel_date_axis_or_the_event_has_no_date():
    r = st.flag_events([0, 1], ["only-one"], window_periods=1)
    assert r["declined"] is True and "parallel" in r["reason"]


def test_one_observation_is_readable_because_frequency_floors_deny_the_tail():
    r = st.flag_events([1], ["2026-01"], window_periods=1)
    assert r["declined"] is False and r["last_event_date"] == "2026-01"


# ── pace_vs_prior -- yoy_delta, delegated ────────────────────────────────────────────────────────────
def test_pace_vs_prior_is_yoy_delta_and_carries_its_contract():
    series = [10.0] + [0.0] * 51 + [12.5]               # 53 points: the latest is 52 periods on
    r = st.pace_vs_prior(series, periods_per_year=52)
    y = st.yoy_delta(series, periods=52)
    assert r["value"] == y["value"] == pytest.approx(2.5)
    assert r["pct_change"] == pytest.approx(25.0)       # hand-computed: 2.5 / 10.0
    assert r["periods_per_year"] == 52 and r["stat"] == "pace_vs_prior"


def test_pace_vs_prior_refuses_a_guessed_year():
    assert st.pace_vs_prior([1, 2, 3], periods_per_year=0)["declined"] is True
    # and declines honestly when the series does not reach a year back
    assert st.pace_vs_prior([1.0, 2.0], periods_per_year=52)["declined"] is True


# ── rolling_zscore ───────────────────────────────────────────────────────────────────────────────────
def test_rolling_zscore_is_the_z_of_every_prefix_against_its_own_trailing_window():
    series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    r = st.rolling_zscore(series, window=8)
    assert r["declined"] is False
    assert r["series"][:7] == [None] * 7                # a prefix shorter than the window is a HOLE
    # hand-computed for index 7 (values 1..8): mean 4.5, population var = 5.25, sd = sqrt(5.25)
    want = (8.0 - 4.5) / math.sqrt(5.25)
    assert r["series"][7] == pytest.approx(want)
    assert r["value"] == pytest.approx(r["series"][-1])
    assert r["n_computed"] == 2


def test_rolling_zscore_inherits_the_z_floor_and_refuses_a_short_history():
    assert st.rolling_zscore([1, 2, 3], window=4)["declined"] is True     # window below MIN_ZSCORE_N
    assert st.rolling_zscore([1, 2, 3], window=8)["declined"] is True     # history shorter than window


def test_a_flat_prefix_is_a_hole_not_a_zero():
    """Zero variance declines at THAT POSITION. A zero there would read as 'exactly average' -- a
    measured statement about a series that supports no statement at all."""
    r = st.rolling_zscore([5.0] * 8 + [9.0], window=8)
    assert r["series"][7] is None                       # the flat prefix
    assert r["series"][8] is not None                   # the prefix that moved
