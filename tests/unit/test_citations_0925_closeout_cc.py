"""09-25 CLOSE-OUT, LANE CC -- THE THREE SERVED-PAGE HALVES OF THE CITATION LABEL (VERIFY.md sec 6 item 4).

Each producer was built in fix round 3 (lane RT) and defaulted to HEAD; the served label never called it, so the
09-25 pages still printed the defect. Every pin below is a label the 09-25 re-smoke SERVED, rebuilt from the
trace's own served rows (``resmoke_0925/answers/*.trace.json`` ``served_rows``), and read UNDER THE ANALYST STAMP
(``display == "analyst"``, O-3 (b)) and OFF it (HEAD's bytes):

  * B-3 (RT-4, PM MAJOR-2, the WASDE year): deep-soy N3 printed "325 Million Bushels, 2025/26" -- the period as a
    trailing appositive the writer dropped. ``_figure_period`` already read the period's KIND off the card and the
    label dropped it; it now rides to ``rows.figure_token``: "325 Million Bushels for 2025/26".
  * B-2 (RT-2 / D11, the carried FATAL): deep-soy N164 printed "United States, one of several regional readings"
    over the DRIEST of ten April-2011 cells (the page wrote "US dryness at 0.90036 z"). The axis words now name
    WHICH cell, by its standing among the rows the read served at its own period (``render.cell_grain_words``),
    and the figure names the period that standing is at.
  * B-4 (RT-7, fact MAJOR-3): cocoa N1 is the ICCO's May-2026 release; the page called the gap to the February
    figure a "trust tier". The vintage card's level row now names its release in the token's period-role slot.

The lexical forms rejected (named in CLOSEOUT_CC.md): a WASDE-only "for" regex; a "US dryness" word map; a
publisher alias table; a trust-tier word swap.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import citations as cit

_ASOF = "2026-09-25"

# deep_rv_soybeans_state_2026_09_07 served_rows[163] (N164) -- the forty values VERBATIM in the trace's order:
# four month blocks (2011-01 .. 2011-04) of ten cells, each block sorted descending (the fact grade's reading).
# The headline row is the one the cascade pre-scaled (a float carrying unit "z"): rows[30], the April maximum.
_N164 = [
    ['2.7787671340878766', '2.295293409824487', '1.7281305635137305', '1.1743706029597594', '0.10019795466420646',
     '-0.3597540379559258', '-1.1055926026687415', '-1.1487915448520964', '-1.3595921362564491',
     '-1.4419279897218942'],
    ['3.0179387176451553', '0.31134992453861954', '-0.04973890160963866', '-0.20923384488011965',
     '-0.45280897873498666', '-0.8631671373460031', '-0.8942872859152978', '-0.9777741092557354',
     '-1.0011766186312248', '-1.7111599291401676'],
    ['0.21045462999062534', '0.10561150696967825', '-0.4344325943130835', '-0.6578368537453283',
     '-0.8481890967778524', '-0.8840115801105805', '-0.9543304707154598', '-1.056636751169537',
     '-1.0952145677879515', '-1.3255619751317091'],
    [0.9003603729220594, '0.22360679774997883', '-0.9909931939970745', '-1.1052358582314172',
     '-1.136394423597312', '-1.3431102193668325', '-1.519297358258059', '-1.6199559950018934',
     '-1.7140790708552462', '-1.910543822789871'],
]
# the served footer line (deep page, [N164]) -- HEAD's head, which the flag-off label must keep byte for byte
_N164_SERVED_HEAD = ("GOLD WEATHER Z drought z-score CBOT soybeans United States, one of several regional readings "
                     "2011-01-01..2011-04-01")


def _n164_call(*, stamped: bool, values=None, headline_unit="z") -> dict:
    rows = []
    for m, block in enumerate(values or _N164, start=1):
        for v in block:
            r = {"value": v, "country": "United States", "year": 2011, "month": m}
            if not isinstance(v, str):
                r["unit"] = headline_unit
            rows.append(r)
    c = {"query": {"table": "gold_weather_z", "metric": "drought_z", "commodity": "soybeans_cbot",
                   "country": "United States", "period": "2011-01-01..2011-04-01", "asof": _ASOF},
         "rows": rows, "status": "ok"}
    if stamped:
        c["display"] = "analyst"
    return c


def _head(label: str) -> str:
    return label.split(" = ", 1)[0].strip()


def _val(label: str) -> str:
    return label.split(" = ", 1)[1] if " = " in label else ""


def _needs(mod_attr: str):
    from leviathan.graphrag.state import render as R
    if getattr(R, mod_attr, None) is None:
        pytest.skip("lane RT's render.%s not on this tree" % mod_attr)


# ══ B-2: THE CELL SAYS WHICH CELL IT IS ═══════════════════════════════════════════════════════════════════
def test_CC2_the_deep_soy_N164_cell_reads_as_the_driest_of_ten_under_the_stamp_and_HEADs_words_off():
    _needs("cell_grain_words")
    off = cit.from_number(_n164_call(stamped=False), 164).label
    on = cit.from_number(_n164_call(stamped=True), 164).label
    # off the stamp: the served page's own head, byte for byte (HEAD's "one of several regional readings")
    assert _head(off) == _N164_SERVED_HEAD
    # under the stamp: WHICH cell -- its standing among the ten the read served at ITS period, and the figure
    # names that period (the standing is an order statistic AT April 2011, never over the Jan-Apr window)
    assert _head(on) == ("GOLD WEATHER Z drought z-score CBOT soybeans for one United States growing cell "
                         "(the driest of ten) 2011-01-01..2011-04-01")
    assert _val(on).startswith("0.9 z, April 2011")
    assert "one of several regional readings" not in on


def test_CC2_the_call_identity_carries_the_same_grain_as_the_label_one_phrase_one_preposition():
    _needs("cell_grain_words")
    on = cit.call_identity(_n164_call(stamped=True))
    off = cit.call_identity(_n164_call(stamped=False))
    assert on["scope_words"] == "for one United States growing cell (the driest of ten)"
    assert on["short"] == "CBOT soybeans drought z-score for one United States growing cell (the driest of ten)"
    assert on["period_words"] == "April 2011"
    assert "for for" not in on["short"]
    assert off["scope_words"] == "United States, one of several regional readings"          # HEAD's identity
    assert off["short"] == "CBOT soybeans drought z-score for United States, one of several regional readings"


def test_CC2_a_cell_that_is_not_the_extreme_is_ranked_from_its_nearer_end_in_the_cards_own_words():
    _needs("cell_grain_words")
    vals = [list(b) for b in _N164]
    vals[3][1], vals[3][2] = "1.5", "1.2"          # two April cells now read drier than the headline's 0.9
    lab = cit.from_number(_n164_call(stamped=True, values=vals), 164).label
    assert "for one United States growing cell (the third driest of ten)" in lab
    low = [list(b) for b in _N164]
    low[3][0] = -2.5                                # the headline is now the lowest April reading
    lab = cit.from_number(_n164_call(stamped=True, values=low), 164).label
    assert "for one United States growing cell (the wettest of ten)" in lab


def test_CC2_the_grain_fails_closed_to_HEADs_words_on_two_scales_a_lone_row_or_no_declared_words():
    _needs("cell_grain_words")
    # (a) a headline re-scaled into another unit than its siblings (the cascade's prescale on a scaled card):
    #     an order statistic over two scales is refused -- HEAD's words
    two = cit.from_number(_n164_call(stamped=True, headline_unit="%"), 164).label
    assert "one of several regional readings" in two and "driest" not in two
    # (b) one row at the headline's period is no cross-section -- HEAD's lone-row words
    lone = _n164_call(stamped=True)
    lone["rows"] = [r for r in lone["rows"] if r["month"] != 4] + [lone["rows"][30]]
    assert "one regional reading" in cit.from_number(lone, 164).label
    # (c) a metric whose side words nobody declared (the tail share) -- HEAD's words, never a guessed superlative
    ts = _n164_call(stamped=True)
    ts["query"]["metric"] = "drought_z_tail_share"
    assert "one of several regional readings" in cit.from_number(ts, 164).label


# ══ B-3: THE WASDE YEAR JOINS ITS FIGURE ══════════════════════════════════════════════════════════════════
_N3 = {"query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
                 "country": "united_states", "period": None, "asof": _ASOF},
       "rows": [{"period": "2025/26", "estimate_role": "estimate", "value": "325.0", "unit": "Million Bushels",
                 "country": "united_states", "knowledge_date": "2026-09-11", "revision_stamp": "estimate"},
                {"period": "2025/26", "estimate_role": "estimate", "value": "8.85", "unit": "MMT",
                 "country": "united_states", "knowledge_date": "2026-09-11", "revision_stamp": "estimate"}],
       "status": "ok"}


def test_CC3_the_deep_soy_N3_seat_row_joins_its_marketing_year_under_the_stamp_and_HEADs_bytes_off():
    off = cit.from_number(_N3, 3).label
    on = cit.from_number(dict(_N3, display="analyst"), 3).label
    assert _val(off).startswith("325 Million Bushels [")                          # HEAD: no token off the stamp
    assert _val(on).startswith("325 Million Bushels for 2025/26")                 # the kind the card declares
    assert "Bushels, 2025/26" not in on                                            # the dropped appositive


def test_CC3_the_token_names_its_kind_only_when_a_caller_passes_one():
    assert cit.figure_token_for("325", unit="Million Bushels", period_words="2025/26") == \
        "325 Million Bushels, 2025/26"                                             # HEAD's comma, byte for byte
    assert cit.figure_token_for("325", unit="Million Bushels", period_words="2025/26",
                                period_kind="marketing_year") == "325 Million Bushels for 2025/26"
    # a kind whose words are already a phrase keeps the comma (the join is the producer's DATA, never a regex)
    assert cit.figure_token_for("1.8 degC", period_words="July 2026", period_kind="month") == "1.8 degC, July 2026"


# ══ B-4: A VINTAGE ROW NAMES ITS RELEASE ══════════════════════════════════════════════════════════════════
_ICCO_ROWS = [
    ("2007/08", "0.4121277166621948", "2008-02-28"), ("2011/12", "0.4753889313950523", "2012-11-30"),
    ("2012/13", "0.4126357354392892", "2013-11-29"), ("2013/14", "0.3887066541705717", "2014-11-28"),
    ("2014/15", "0.3770413064361191", "2015-05-29"), ("2015/16", "0.34266570949988034", "2016-05-31"),
    ("2016/17", "0.41592713685193833", "2017-08-31"), ("2017/18", "0.3846322241681261", "2018-08-31"),
    ("2018/19", "0.3637884173113109", "2019-08-30"), ("2019/20", "0.3759447203627726", "2020-12-02"),
    ("2020/21", "0.4039094650205761", "2021-08-31"), ("2021/22", "0.3217665615141956", "2023-05-31"),
    ("2022/23", "0.34866053578568573", "2023-11-30"), ("2023/24", "0.2635948526359485", "2025-05-30"),
    ("2024/25", "0.28522039757994816", "2026-05-29")]
_N1 = {"query": {"table": "silver_icco_cocoa", "metric": "su_ratio", "commodity": None, "country": None,
                 "period": None, "asof": _ASOF},
       "rows": [{"period": p, "value": v, "knowledge_date": k} for p, v, k in _ICCO_ROWS], "status": "ok"}


def test_CC4_the_cocoa_N1_seat_row_is_the_ICCO_release_of_29_May_2026_under_the_stamp_only():
    _needs("release_role_words")
    off = cit.from_number(_N1, 1).label
    on = cit.from_number(dict(_N1, display="analyst"), 1).label
    assert "release" not in off and _val(off).startswith("0.28522 ratio")          # HEAD's bytes off the stamp
    # RE-BANKED 09-25 (the N8 restore, VERIFY MINOR-B): the season joins with its article (`rows.PERIOD_TOKEN_JOINS`)
    assert "28.52 % of grindings for the 2024/25 season, the ICCO release of 29 May 2026" in on
    assert "trust" not in on.lower()


def test_CC4_no_release_words_on_a_computed_statistic_or_a_card_that_declares_no_publisher():
    _needs("release_role_words")
    # the z-score OVER the ICCO series is a statistic of the series, not a row of the card -- no release words
    z = {"query": {"table": "compute_stat", "metric": "zscore", "commodity": None, "country": None, "period": None,
                   "asof": _ASOF},
         "rows": [{"value": -1.66, "unit": "sigma", "knowledge_date": "2026-05-29", "z_window": 15,
                   "z_series": "silver_icco_cocoa.su_ratio", "source_table": "silver_icco_cocoa",
                   "source_metric": "su_ratio"}], "status": "ok", "display": "analyst"}
    assert "release" not in cit.from_number(z, 7).label
    # the WASDE is not a vintage card: its token carries no release
    assert "release" not in cit.from_number(dict(_N3, display="analyst"), 3).label


def test_CC_every_stamped_move_is_off_the_stamp_HEADs_label():
    """The three moves ride the stamp alone: with no ``display`` the label is the one HEAD's producers print."""
    for call, k in ((_n164_call(stamped=False), 164), (_N3, 3), (_N1, 1)):
        lab = cit.from_number(call, k).label
        assert "driest" not in lab and " for 2025/26" not in lab and "release of" not in lab
