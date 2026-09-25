"""09-24 FIX ROUND 2, LANE C -- THE LABEL HALVES OF K2 / K5 / K7 / K22 AND `call_identity` (K4).

Every test is a label the 2026-09-24 re-smoke served FALSE (grades/fact/*.md), rebuilt as a fixture call off
the banked served row, and the corrected label:

  * K7 / K2 (item 10; THREAT C-5 / C-6): the tariff footer printed "[N9] ... MY2026 = 0.11 ratio" beside
    "[N130] ... = 10.72 %" for ONE series; soyoil "0.547897 ratio"; the writer copied figures out of the
    numbers block with no basis and no period. Under the analyst stamp (board flag only, O-1 (b) / O-3 (b)) a
    LEVEL in the card's native unit prints the card's FULL display spec, and the value slot is the FIGURE
    TOKEN "<figure> <unit> <basis>, <period>". Off the stamp: HEAD's bytes.
  * K5 (items 5, 26; THREAT C-11): cocoa N181-N184 printed a CHANGE under the level's name ("drought z-score
    ... = 0.15 z" beside the level 0.00089 z for the same month); max N334 "production ... 2026..2026 = 0.5
    MMT". A `window_change` row now reads "<name> change from <from> to <to> = <signed figure>" (+ its pct).
  * K22 (item 12; THREAT C-7): the 2024 page printed the soybean MEAL sub-table as "US soybean production ...
    54,154 1 Thousand Short2 Tons 3 4". The card's governing unit prints (never the raw unit column), a row
    whose SHEET is not the asked commodity's own balance sheet is named by what the sheet prints, and a class
    slug's all-class row names its published family.
  * K4: `call_identity` -- the one reader of a call's identity, from the label's own producers.

Card fields other lanes declare this round (lane T's `figure_basis`; the WASDE `sheets` and the PSD
`commodity_families`) are INJECTED through `citations._card_metric` / `citations._registry_attr` -- the
accessors this module reads them by -- so the deck pins the rule before and after T lands.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import citations as cit

_ASOF = "2026-09-24"


def _call(table, metric, rows, *, commodity=None, country=None, period=None, sb=False, asof=_ASOF, **extra):
    c = {"query": {"table": table, "metric": metric, "commodity": commodity, "country": country,
                   "period": period, "asof": asof}, "rows": rows, "status": "ok"}
    if sb:
        c["_sb"] = True
    c.update(extra)
    return c


def _val(label: str) -> str:
    return label.split(" = ", 1)[1] if " = " in label else ""


class _Proxy:
    """A registry Metric with this round's fields laid over it (the real object answers everything else)."""

    def __init__(self, base, over):
        self._b, self._o = base, dict(over)

    def __getattr__(self, k):
        if k in self._o:
            return self._o[k]
        return getattr(self._b, k)


@pytest.fixture
def metric_fields(monkeypatch):
    """``metric_fields[(table, metric)] = {field: value}`` -- injected through ``cit._card_metric``."""
    real = cit._card_metric
    spec: dict = {}

    def _cm(t, m):
        base = real(t, m)
        over = spec.get((str(t), str(m)))
        return _Proxy(base, over) if over is not None else base
    monkeypatch.setattr(cit, "_card_metric", _cm)
    return spec


def _needs_shown_figure():
    from leviathan.graphrag.state import render as R
    if getattr(R, "shown_figure", None) is None:
        pytest.skip("lane R's render.shown_figure (CONTRACT C5) not landed on this tree")


# ── K7 + K2: THE SEAT ROW AT THE CARD'S DISPLAY SPEC, AS A FIGURE TOKEN, UNDER THE STAMP ONLY ─────────────
def test_K7_the_tariff_N9_seat_su_ratio_row_prints_the_cards_display_spec_under_the_stamp(metric_fields):
    """tariff F-J: "[N9] ... MY2026 = 0.11 ratio" beside "[N130] ... = 10.72 %" -- one series, two scales."""
    _needs_shown_figure()
    metric_fields[("silver_psd", "su_ratio")] = {"figure_basis": "of domestic use"}
    rows = [{"value": "0.107199613511830", "unit": "ratio", "knowledge_date": "2026-09-11", "period": "2026"}]
    base = _call("silver_psd", "su_ratio", rows, commodity="soybeans_cbot", country="United States",
                 period="2026")
    off = cit.from_number(base, 9)
    on = cit.from_number(dict(base, display="analyst"), 9)
    assert _val(off.label) == f"{cit._fmt(rows[0]['value'])} ratio" == "0.1072 ratio", \
        "off the stamp: HEAD's bytes (OWNER DECISION O-3 (b))"
    assert _val(on.label) == "10.72 % of domestic use, 2026/27", on.label
    assert on.label.rpartition(" = ")[0] == off.label.rpartition(" = ")[0], "the head (the pairing key) is one"
    assert (on.value, on.unit) == (off.value, off.unit) == ("0.107199613511830", "ratio"), \
        "Citation.value / .unit stay the ROW's pair -- a stand-in splice can never print 0.1072 %"


def test_K2_the_token_without_a_declared_basis_carries_the_period_alone():
    _needs_shown_figure()
    c = cit.from_number(_call("silver_psd", "su_ratio", [{"value": "0.2731", "unit": "ratio"}],
                              commodity="rough_rice_cbot", country="United States", period="2026",
                              display="analyst"), 20)
    val = _val(c.label)
    assert val.startswith("27.31 %") and val.endswith("2026/27"), c.label
    assert " ratio" not in val


def test_K7_the_months_of_cover_row_prints_its_declared_unit_never_the_bare_ratio_token():
    """soyoil N17 "0.547897 ratio" (MPOB months of export cover, whose card forbids the bare token)."""
    _needs_shown_figure()
    c = cit.from_number(_call("silver_mpob", "su_ratio", [{"value": "0.547897", "unit": "ratio",
                                                          "knowledge_date": "2026-08-01"}],
                              commodity="malaysian_crude_palm_oil_cme", display="analyst"), 17)
    assert _val(c.label).startswith("0.55 months of export cover"), c.label


def test_K7_a_CHANGE_or_a_computed_statistic_never_borrows_the_levels_display_spec():
    """A difference of a ratio x 100 is percentage POINTS, not percent -- that unit is the mint's to declare.
    A compute_stat window_change over su_ratio and a board change row keep their own unit."""
    _needs_shown_figure()
    stat = _call("compute_stat", "window_change",
                 [{"value": 0.0123, "unit": "ratio", "source_table": "silver_psd", "source_metric": "su_ratio",
                   "knowledge_date": "2026-09-11"}], display="analyst")
    c = cit.from_number(stat, 3)
    assert " %" not in _val(c.label) and "ratio" in _val(c.label), c.label
    chg = _call("silver_psd", "su_ratio", [{"value": 0.0123, "unit": "ratio", "stat": "window_change",
                                            "window": {"from": "2025", "to": "2026"}}],
                commodity="soybeans_cbot", country="United States", period="2025..2026", sb=True,
                display="analyst")
    assert " %" not in cit.from_number(chg, 4).label


@pytest.mark.parametrize("raw", [0.1072, 0.0998, 0.10004, 0.55555, 0.0001234, 1.0, 0.0, -0.0213])
def test_K7_C5_the_scaled_label_is_the_precision_producers_text_of_the_SCALED_value(raw):
    """C-5: label value == figure_text(value x display_scale) at the card's decimals -- the scaled figure
    the verifier's K7 half backs -- for every magnitude, sign and zero."""
    _needs_shown_figure()
    from leviathan.graphrag.state import render as R
    c = cit.from_number(_call("silver_psd", "su_ratio", [{"value": str(raw), "unit": "ratio"}],
                              commodity="soybeans_cbot", country="United States", period="2026",
                              display="analyst"), 1)
    want = R.shown_figure(raw, table="silver_psd", metric="su_ratio", unit="ratio", grouping=True)
    # the figure and its display unit lead the token; the card's basis (lane T's `figure_basis`, where
    # declared) or the period follows
    assert _val(c.label).startswith((want + ",", want + " ")), (c.label, want)


def test_K7_C6_the_line_guard_holds_on_the_scaled_path(monkeypatch):
    """C-6: a threshold declared on the DISPLAYED level (a 10 % tight line) is never rounded onto or across
    by the re-stated figure: 0.09996 prints 9.996 %, never 10 %; 0.10004 prints 10.004 %."""
    _needs_shown_figure()
    from leviathan.graphrag.state import render as R
    monkeypatch.setattr(R, "convention_lines", lambda t, m: (10.0,) if (t, m) == ("silver_psd", "su_ratio")
                        else ())
    for raw, side in ((0.09996, -1), (0.099999, -1), (0.10004, 1), (0.100049, 1), (0.1, 0)):
        c = cit.from_number(_call("silver_psd", "su_ratio", [{"value": str(raw), "unit": "ratio"}],
                                  commodity="soybeans_cbot", country="United States", period="2026",
                                  display="analyst"), 1)
        shown = float(_val(c.label).split(" ", 1)[0])
        got = 0 if shown == 10.0 else (1 if shown > 10.0 else -1)
        assert got == side, (raw, c.label)


# ── K5: A CHANGE ROW IS LABELLED AS A CHANGE ──────────────────────────────────────────────────────────────
def test_K5_cocoa_N181_N182_analog_change_rows_read_as_changes_beside_the_level():
    """cocoa F-N2: "[N182] GOLD WEATHER Z drought z-score ICE cocoa West Africa 2026-01..2026-07 = 0.15 z" beside
    the LEVEL "[N137] ... = 0.00089 z" for the same month. The level's label is untouched (C-11)."""
    lvl = _call("gold_weather_z", "drought_z", [{"value": 0.00089, "unit": "z", "knowledge_date": "2026-08-25"}],
                commodity="cocoa", country="West Africa", period="2026-07", sb=True)
    before = cit.from_number(lvl, 137).label
    chg = _call("gold_weather_z", "drought_z",
                [{"value": 0.1528, "unit": "z", "stat": "window_change",
                  "window": {"from": "2025-10", "to": "2026-07"}, "knowledge_date": "2026-08-25"}],
                commodity="cocoa", country="West Africa", period="2025-10..2026-07", sb=True)
    lab = cit.from_number(chg, 182).label
    assert "change from October 2025 to July 2026 = +0.1528 z" in lab, lab
    assert "2025-10..2026-07" not in lab
    assert cit.from_number(lvl, 137).label == before
    neg = dict(chg, rows=[dict(chg["rows"][0], value=-0.2327, window={"from": "2025-10", "to": "2026-01"})])
    assert "change from October 2025 to January 2026 = -0.2327 z" in cit.from_number(neg, 181).label


def test_K5_the_palm_rape_N11_seat_change_row_states_its_window_and_the_calculators_pct():
    """palm/rape F1: N11 "+10,289 MT" whose window the page could not state (period NULL). With lane T's
    window + pct_change on the row, the label names both ends and the calculator's own percent."""
    row = {"value": 10289.0, "unit": "MT", "stat": "window_change", "window": {"from": "2026-01-01",
                                                                               "to": "2026-08-01"},
           "pct_change": 0.3712, "source_table": "silver_mpob", "source_metric": "closing_stocks_palm_oil_mt",
           "knowledge_date": "2026-08-01"}
    c = cit.from_number(_call("compute_stat", "window_change", [row]), 11)
    assert "change from January 2026 to August 2026 = +10,289 MT (+0.37 %)" in c.label, c.label
    assert c.label.startswith("MPOB palm oil closing stocks change from"), \
        "a computed change is named by the SERIES it was computed over, never '(change over the window) change'"
    a = cit.from_number(_call("compute_stat", "window_change", [row], display="analyst"), 11)
    assert "change from January 2026 to August 2026 = +10,289 MT (+0.37 %)" in a.label, a.label


def test_K5_a_change_row_with_no_window_keeps_HEADs_head_and_a_level_row_is_untouched():
    """No window on the row and no <from>..<to> query period: the label keeps HEAD's head (never a guessed
    window) but still signs the change. A row with no `stat` is HEAD's label, byte for byte."""
    c = cit.from_number(_call("silver_psd", "production_mt", [{"value": 0.5, "unit": "MMT",
                                                               "stat": "window_change"}],
                              commodity="soybeans_cbot", country="Argentina", period="2026", sb=True), 334)
    assert "change from" not in c.label and " = +0.5 MMT" in c.label, c.label
    plain = _call("silver_psd", "production_mt", [{"value": 50.0, "unit": "MMT"}], commodity="soybeans_cbot",
                  country="Argentina", period="2026", sb=True)
    assert cit.from_number(plain, 220).label.endswith(" = 50 MMT")


# ── K22: THE CARD'S UNIT, THE ROW'S SHEET, THE PUBLISHED FAMILY ──────────────────────────────────────────
# Lane T's P-2 census measured that WASDE's `table_type` is only us | world and CANNOT tell the meal sub-table
# from the beans sheet: the sheet identity is the transform's own `source_table_id`, declared per sheet on the
# card (`sheets[<id>] = {commodity, scope, serves, unit}`, `registry.sheet_spec`), and the all-class rule is a
# published FAMILY (`registry.class_scope`). Both are injected here through `citations._registry_attr` -- the
# one accessor this module reads them by -- so the deck pins the rule before and after lane T lands.
_SHEETS = {
    "u_s_soybeans_supply_and_use": {"commodity": "soybeans", "scope": "us", "serves": "all_classes",
                                    "unit": "Million Bushels"},
    "u_s_soybean_meal_supply_and_use": {"commodity": "soybean_meal", "scope": "us", "serves": "all_classes",
                                        "unit": "Thousand Short Tons"},
    "u_s_soybeans_and_products_supply_and_use": {"commodity": "soybeans", "scope": "us",
                                                 "serves": "the soybean products sub-tables (meal, oil)",
                                                 "unit": ""},
    "u_s_long_grain_rice_supply_and_use": {"commodity": "rice", "scope": "us", "serves": "long-grain rice",
                                           "unit": "Million Hundredweight"},
}
_FAMILIES = {"soft_red_winter_wheat_cbot": {"family": "wheat", "class_scope": "all_classes", "basis": ""},
             "corn_cbot": {"family": "corn", "class_scope": "all_classes", "basis": ""},
             "south_african_white_maize_jse": {"family": "corn", "class_scope": "all_classes", "basis": ""},
             "soybeans_cbot": {"family": "soybeans", "class_scope": "", "basis": ""}}


@pytest.fixture
def k22(monkeypatch):
    fakes = {"sheet_spec": lambda t, sid: dict(_SHEETS.get(sid, {})) if t == "silver_wasde" else {},
             "class_scope": lambda t, c: dict(_FAMILIES.get(c, {})) if t in ("silver_psd", "silver_psd_attributes")
             else {}}
    monkeypatch.setattr(cit, "_registry_attr", lambda name: fakes.get(name))


def _wrow(value, sheet, unit, period="2023/24"):
    return {"value": value, "unit": unit, "period": period, "knowledge_date": "2024-02-08",
            "country": "united_states", "table_type": "us", "_sheet": sheet}


def test_K22_the_2024_N4_products_sheet_row_is_named_by_what_its_sheet_prints(k22):
    """2024 N-2 (FATAL-class): "US soybean production projected at 54,154 1 Thousand Short2 Tons 3 4 [N4]" --
    the products sheet's rows ARE the meal sub-table. Where such a row still serves (no own sheet printed the
    grain) the label names what its sheet prints, never "soybeans"; its unit is the sheet's ("" -- blank beats
    a false unit, lane T's stamp)."""
    c = cit.from_number(_call("silver_wasde", "production",
                              [_wrow("54154.0", "u_s_soybeans_and_products_supply_and_use", "")],
                              commodity="soybeans", country="united_states", asof="2024-03-01"), 4)
    assert "USDA WASDE production the soybean products sub-tables (meal, oil) united_states MY2023/24 = 54,154" \
        in c.label, c.label
    assert " soybeans " not in c.label and "Short2" not in c.label
    assert c.locator["commodity"] == "soybeans", "the drill-down still re-runs the query that was asked"


def test_K22_the_own_sheet_row_keeps_the_asked_commodity_and_prints_its_stamped_unit(k22):
    """The commodity's own balance sheet (lane T's precedence serves it first): the label is HEAD's words
    with the sheet's own unit, which the query layer stamped on the row."""
    c = cit.from_number(_call("silver_wasde", "production",
                              [_wrow("4165", "u_s_soybeans_supply_and_use", "Million Bushels")],
                              commodity="soybeans", country="united_states", asof="2024-03-01"), 4)
    assert c.label == "USDA WASDE production soybeans united_states MY2023/24 = 4,165 Million Bushels", c.label


def test_K22_another_commoditys_own_sheet_is_named_by_that_commodity(k22):
    c = cit.from_number(_call("silver_wasde", "production",
                              [_wrow("54154", "u_s_soybean_meal_supply_and_use", "Thousand Short Tons")],
                              commodity="soybeans", country="united_states", asof="2024-03-01"), 4)
    assert " soybean meal united_states MY2023/24 = 54,154 Thousand Short Tons" in c.label, c.label


def test_K22_a_class_sheet_under_the_commodity_lookup_names_its_class(k22):
    """rice 09-24: the LONG-GRAIN class (103.5 M cwt) answered "US rice" over the total (158.2)."""
    c = cit.from_number(_call("silver_wasde", "production",
                              [_wrow("103.5", "u_s_long_grain_rice_supply_and_use", "Million Hundredweight",
                                     period="2026/27")], commodity="rice", country="united_states"), 1)
    assert " long-grain rice united_states MY2026/27 = 103.5 Million Hundredweight" in c.label, c.label


def test_K22_an_undeclared_sheet_or_no_sheet_id_is_HEADs_label_byte_for_byte(k22):
    for row in (_wrow("54154.0", "some_ocr_fragment_id", "1 Thousand Short2 Tons 3 4"),
                {k: v for k, v in _wrow("54154.0", None, "1 Thousand Short2 Tons 3 4").items() if k != "_sheet"}):
        c = cit.from_number(_call("silver_wasde", "production", [row], commodity="soybeans",
                                  country="united_states", asof="2024-03-01"), 4)
        assert c.label == ("USDA WASDE production soybeans united_states MY2023/24 = 54,154 "
                           "1 Thousand Short2 Tons 3 4"), c.label


def test_K22_nothing_declared_is_HEADs_label_byte_for_byte():
    """No lane-T declaration reachable at all (a registry without the fields): the raw row, HEAD's words."""
    row = {"value": "54154.0", "unit": "1 Thousand Short2 Tons 3 4", "period": "2023/24",
           "knowledge_date": "2024-02-08", "country": "united_states"}
    c = cit.from_number(_call("silver_wasde", "production", [row], commodity="soybeans", country="united_states",
                              asof="2024-03-01"), 4)
    assert c.label == ("USDA WASDE production soybeans united_states MY2023/24 = 54,154 "
                       "1 Thousand Short2 Tons 3 4")


def test_K22_the_governing_unit_overrides_a_raw_unit_column_minted_outside_the_query_layer():
    """avg_farm_price declares `unit_overrides` (the GOVERNING unit); a row minted outside `Q.run` with the
    cotton bleed label 'Million 480 Pound Bales' on a c/lb value prints the card's unit."""
    row = {"value": "68.09", "unit": "Million 480 Pound Bales", "period": "2024/25", "knowledge_date": "2025-01-10"}
    c = cit.from_number(_call("silver_wasde", "avg_farm_price", [row], commodity="cotton", country="united_states",
                              asof="2025-02-01"), 1)
    assert c.label.endswith(" = 68.09 c/lb") and c.unit == "c/lb", c.label


def test_K22_an_all_class_row_under_a_CLASS_slug_says_so_and_a_whole_commodity_slug_is_unmoved(k22):
    """corn/wheat F: "0.652178 [N14] on soft red winter wheat" -- USDA's ALL-CLASS wheat sheet under the srw
    slug. The label names the family's all-class sheet; corn_cbot (the family's whole commodity by the
    contract hierarchy) and a family with no class rule (soybeans) are unmoved."""
    c = cit.from_number(_call("silver_psd", "su_ratio", [{"value": "0.652178", "unit": "ratio"}],
                              commodity="soft_red_winter_wheat_cbot", country="United States", period="2026"), 14)
    assert " wheat (all classes) United States MY2026 = 0.652178 ratio" in c.label, c.label
    assert "srw" not in c.label
    jse = cit.from_number(_call("silver_psd", "production_mt", [{"value": "15.0", "unit": "MMT"}],
                                commodity="south_african_white_maize_jse", country="South Africa",
                                period="2026"), 3)
    assert " corn (all classes) South Africa " in jse.label, jse.label
    for slug, disp in (("corn_cbot", "CBOT corn"), ("soybeans_cbot", "CBOT soybeans")):
        c = cit.from_number(_call("silver_psd", "su_ratio", [{"value": "0.1", "unit": "ratio"}], commodity=slug,
                                  country="United States", period="2026"), 1)
        assert f" {disp} United States MY2026 = " in c.label and "all classes" not in c.label, c.label


def test_K22_K23_the_join_reads_the_sheet_and_the_family(k22):
    """The store-period join (K23) reads the SAME declarations: a sub-table sheet joins nothing; another
    commodity's own sheet joins as that commodity; an all-class class slug joins as its family."""
    assert cit._join_commodity("silver_wasde", "soybeans",
                               _wrow("1", "u_s_soybeans_and_products_supply_and_use", "")) is None
    assert cit._join_commodity("silver_wasde", "soybeans",
                               _wrow("1", "u_s_soybean_meal_supply_and_use", "")) == "soybean_meal"
    assert cit._join_commodity("silver_psd", "soft_red_winter_wheat_cbot", {}) == "wheat"
    assert cit._join_commodity("silver_psd", "corn_cbot", {}) == "corn_cbot"


# ── K4: call_identity -- the label's own producers, one reader ────────────────────────────────────────────
def test_K4_call_identity_of_a_seat_call(metric_fields):
    metric_fields[("silver_psd", "su_ratio")] = {"figure_basis": "of domestic use"}
    ci = cit.call_identity(_call("silver_psd", "su_ratio", [{"value": "0.1072", "unit": "ratio"}],
                                 commodity="soybeans_cbot", country="United States", period="2026"))
    assert ci["name"] == "stocks-to-use ratio (ending stocks as a share of domestic use)"
    assert ci["short"] == "CBOT soybeans stocks-to-use ratio for United States"
    assert (ci["commodity_words"], ci["scope_words"]) == ("CBOT soybeans", "United States")
    assert (ci["period_words"], ci["period_kind"]) == ("2026/27", "marketing_year")
    assert (ci["unit_words"], ci["unit_family"]) == ("ratio", "ratio")
    assert ci["routing_words"] == "" and ci["row_id"] == ""
    assert set(ci) == {"name", "short", "commodity_words", "scope_words", "period_words", "period_kind",
                       "unit_words", "unit_family", "routing_words", "row_id", "period_role"}
    assert ci["period_role"] == ""                 # a PSD row IS its marketing year: no second period


def test_K4_call_identity_of_a_board_call_reads_the_routing_words_and_the_row_id():
    """rice "deliverable stocks [N172]": the block printed "read here for deliverable stocks" on the ending
    stocks row; lane R writes those words on the call as `routing`."""
    c = _call("silver_psd", "ending_stocks_mt", [{"value": 1.28, "unit": "MMT", "knowledge_date": "2026-09-11",
                                                  "axis_scope": "United States"}],
              commodity="rough_rice_cbot", country="United States", period="2026", sb=True,
              routing="deliverable stocks", _row_id="rough_rice_cbot|deliverable_stocks|x")
    ci = cit.call_identity(c)
    assert ci["routing_words"] == "deliverable stocks" and ci["row_id"] == "rough_rice_cbot|deliverable_stocks|x"
    # FIXER PASS (REVIEW_VC M5): rice's family DECLARES its basis, so the all-class milled words print on
    # the rice slug (the first cut folded the node "rice" onto the family name and dropped them)
    assert ci["name"] == "ending stocks"
    assert ci["short"] == "rice (all classes, milled basis) ending stocks for United States"
    assert ci["unit_family"] == "mmt"


def test_fixer_RA_M1_a_board_calls_identity_is_the_one_the_block_printed():
    """REVIEW_RA M1: a board call's short noun, its commodity words and whether its routing driver IS the
    series are the BLOCK's own (lane R stamps them on the SB-1 call row): a global series carries no
    commodity words (never " global"), the short is R's printed noun (never C's second derivation), and a
    driver that IS the series routes nothing to correct."""
    c = _call("silver_noaa_oni", "oni_anom", [{"value": 0.98, "unit": "degC", "knowledge_date": "2026-09-05",
                                              "routing": "El Nino", "commodity_words": "",
                                              "series_short": "the tropical Pacific sea-surface temperature anomaly"}],
              commodity="_global", period="2026-08", sb=True, _row_id="soybeans_cbot|El_Nino|oni")
    ci = cit.call_identity(c)
    assert ci["short"] == "the tropical Pacific sea-surface temperature anomaly"
    assert ci["commodity_words"] == "" and ci["routing_words"] == "El Nino"
    fx = _call("silver_fred_fx", "idr_usd", [{"value": 16000.0, "unit": "IDR per USD", "routing": "IDR USD",
                                             "commodity_words": "", "series_short": "IDR/USD exchange rate",
                                             "route_is_series": True}],
               commodity="_global", period="2026-09-18", sb=True, _row_id="palm|IDR_USD|fx")
    cf = cit.call_identity(fx)
    assert cf["short"] == "IDR/USD exchange rate" and cf["routing_words"] == ""


def test_K4_unit_family_comes_from_the_declared_vocabulary():
    """A percentile row and a duration written against it are different families (corn/wheat "98 years'
    standing ... [N53]" on a 98th-percentile row) -- read off tables.yaml's declared unit and duration
    spellings, never typed here."""
    assert cit._unit_family("percentile") == cit._unit_family("percentiles") == "percentile"
    assert cit._unit_family("years") == cit._unit_family("weeks") == "duration"
    assert cit._unit_family("percent") == cit._unit_family("%")
    assert cit._unit_family("") == ""
    ci = cit.call_identity(_call("silver_psd", "area_harvested_1000ha",
                                 [{"value": 98, "unit": "percentile"}], commodity="corn_cbot",
                                 country="United States", period="2026", sb=True))
    assert ci["unit_family"] == "percentile"


def test_K4_a_window_change_identity_reads_its_window_and_never_raises_on_garbage():
    c = _call("gold_weather_z", "drought_z", [{"value": 0.15, "unit": "z", "stat": "window_change",
                                               "window": {"from": "2025-10", "to": "2026-07"}}],
              commodity="cocoa", country="West Africa", period="2025-10..2026-07", sb=True)
    ci = cit.call_identity(c)
    assert ci["period_words"] == "October 2025 to July 2026" and ci["period_kind"] == "window"
    for junk in (None, {}, {"query": None, "rows": None}, {"query": {"table": 3}, "rows": ["x"]}):
        out = cit.call_identity(junk)
        assert isinstance(out, dict) and set(out) == set(ci)


# == FIXER PASS (fix round 2) -- the K2 token's basis and period, read off the card and the ROW ==========
def _stamped(c):
    return dict(c, display="analyst")


def test_fixer_F2_the_basis_rides_only_the_metrics_own_level():
    """REVIEW_VC F2: "31 percentile of domestic use" and "-0.72 sigma of domestic use" were false tokens --
    the card's `figure_basis` qualifies ONE observation of the metric's own quantity, so it rides the level
    in its native or display unit and nothing else (the real card, silver_psd.su_ratio)."""
    lvl = _call("silver_psd", "su_ratio", [{"value": 0.1072, "unit": None, "knowledge_date": "2026-09-11"}],
                commodity="soybeans_cbot", country="United States", period="2026")
    pct = _call("silver_psd", "su_ratio", [{"value": 23, "unit": "percentile", "stat": "percentile",
                                            "knowledge_date": "2026-09-11"}],
                commodity="soybeans_cbot", country="United States", period="2026", sb=True)
    sig = _call("silver_psd", "su_ratio", [{"value": -0.72, "unit": "sigma", "stat": "sigma",
                                            "knowledge_date": "2026-09-11"}],
                commodity="soybeans_cbot", country="United States", period="2026", sb=True)
    ls = [cit.from_number(_stamped(c), i).label for i, c in enumerate((lvl, pct, sig), 1)]
    assert "10.72 % of domestic use, 2026/27" in ls[0]
    assert "= 23 percentile, 2026/27" in ls[1] and "of domestic use, 2026/27" not in ls[1].split(" = ", 1)[1]
    assert "-0.72 sigma, 2026/27" in ls[2] and "sigma of domestic use" not in ls[2]


def test_fixer_M1_a_weekly_row_prints_its_week_and_the_marketing_year_as_its_role():
    """REVIEW_VC M1 / RA M8: the tariff N3 shape -- one ESR week, queried by its marketing year. The token
    and the identity carry the ROW's week at the card's precision; the query's marketing year is its role
    (the label's own "MY2026" slot is untouched -- no kind is read off that prefix)."""
    c = _call("silver_esr", "gross_new_sales_1000mt",
              [{"value": 0.0, "unit": "1000 MT", "period": "2027", "data_date": "2026-09-03",
                "knowledge_date": "2026-09-10", "country": "China"},
               {"value": 879.05, "unit": "1000 MT", "period": "2027", "data_date": "2026-09-10",
                "knowledge_date": "2026-09-17", "country": "China"}],
              commodity="soybeans_cbot", country="China", period="2026")
    lab = cit.from_number(_stamped(c), 3).label
    assert "= 879.05 1000 MT booked in the week, week to 10 September 2026, 2026/27 marketing year" in lab
    assert "MY2026" in lab                                             # the scope slot is HEAD's
    ci = cit.call_identity(c)
    assert (ci["period_words"], ci["period_kind"], ci["period_role"]) == (
        "week to 10 September 2026", "week", "2026/27 marketing year")
    assert cit.from_number(c, 3).label.endswith("= 879.05 1000 MT [2 rows served, covering 2026-09-03.."
                                                 "2026-09-10; newest shown]")   # unstamped: HEAD's value slot


def test_fixer_M9_an_aggregate_is_named_by_the_cards_aggregate_words_and_takes_no_basis():
    """REVIEW_RA M9 / WT MAJOR-4: the K24 closed-year companion is `agg="sum"` over the weekly series -- one
    YEAR, never one week. Under the stamp it is named by the card's `aggregate_labels` ("export
    shipments"), carries no per-observation basis ("shipped in the week") and its period is the SCOPE it
    summed (the query's 2025/26), with the producer's own role words. Unstamped: HEAD's label."""
    c = _call("silver_esr", "weekly_exports_1000mt",
              [{"value": 12357.0, "unit": "1000 MT", "period": "2026",
                "period_role": "the closed 2025/26 year, every week summed"}],
              commodity="soybeans_cbot", country="China", period="2025", agg="sum")
    c["query"]["agg"] = "sum"
    lab = cit.from_number(_stamped(c), 2).label
    assert "export shipments CBOT soybeans China MY2025 = 12,357 1000 MT, 2025/26, the closed 2025/26 " \
           "year, every week summed" in lab
    assert "in the week" not in lab and "weekly exports" not in lab
    assert "weekly exports" in cit.from_number(c, 2).label
    ci = cit.call_identity(c)
    assert ci["name"] == "export shipments" and ci["period_words"] == "2025/26"
