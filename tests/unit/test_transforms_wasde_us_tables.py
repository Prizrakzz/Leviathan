"""Real-PDF regression tests for the modern WASDE US-table parser (W1).

The modern digital WASDE PDFs emit NO "=====" separators, so the US pages fell
through to _parse_columnar_page (World geometry) and yielded ZERO rows -- farm
price + acreage/yield/use US detail were dead post-2011.  These tests pin the new
transposed-table parser (_parse_us_columnar_page + the parse_wasde_pdf_digital
routing) against real page fixtures extracted from the four recon-era PDFs, plus
unit tests for the LOW-HIGH range tokenizer and the explicit item-label map.

Fixtures (single real PDF pages, tests/fixtures/wasde/us_pages/):
  us_wheat_2011_09_p10.pdf   RANGE era + wheat "by Class" sub-table (must be skipped)
  us_wheat_2026_07_p10.pdf   POINT era + by-class
  us_soy_2026_07_p14.pdf     SOYBEANS + OIL (c/lb) + MEAL ($/s.t.) via "avg. price" alias
  us_cotton_2026_07_p16.pdf  negatives ("Unaccounted") + bare Planted/Harvested labels
  world_wheat_2026_07_p17.pdf   World control (columnar path stays byte-identical)
  us_wheat_2026_in_window.pdf / world_wheat_2026_in_window.pdf
                             the same pages padded to index 7 (inside [7,30)) so the
                             parse_wasde_pdf_digital page-window + routing is exercised.
"""
from __future__ import annotations

import math
from pathlib import Path

import pdfplumber
import pytest

from leviathan.transforms.raw_to_bronze.usda_wasde import (
    _ATTRIBUTE_ALIASES,
    _is_us_transposed_heading,
    _match_reversed_us_year,
    _normalise_attr,
    _normalise_us_item,
    _parse_columnar_page,
    _parse_us_columnar_page,
    _strip_filler,
    _us_commodity_banner,
    _to_dataframe,
    _us_row_cells,
    parse_wasde_pdf_digital,
)

_WASDE_WHITELIST = {
    "avg_farm_price", "beginning_stocks", "crush", "domestic_total", "ending_stocks",
    "exports", "feed", "feed_residual", "food_use", "harvested_area", "imports",
    "loss", "planted_area", "production", "residual", "seed_use", "total_supply",
    "total_use", "yield",
}

FX = Path(__file__).parent.parent / "fixtures" / "wasde" / "us_pages"


def _parse_us(name: str, release_date: str) -> list[dict]:
    with pdfplumber.open(FX / name) as pdf:
        return _parse_us_columnar_page(pdf.pages[0], release_date)


def _rows_where(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


# ---------------------------------------------------------------------------
# Farm price: RANGE era (2011) -> midpoint + low/high; POINT era (2026)
# ---------------------------------------------------------------------------

def test_wheat_2011_range_farm_price_midpoint_and_bounds() -> None:
    rows = _parse_us("us_wheat_2011_09_p10.pdf", "2011-09-12")
    price = _rows_where(rows, attribute="avg_farm_price")
    by_key = {(r["market_year"], r["status"], r["projection_month"]): r for r in price}

    # settled + estimate columns are point values (no range)
    assert math.isclose(by_key[("2009/10", "", "")]["value"], 4.87)
    assert by_key[("2009/10", "", "")]["value_low"] is None
    assert math.isclose(by_key[("2010/11", "Est.", "")]["value"], 5.70)

    # the two 2011/12 projection columns are printed as "LOW - HIGH" ranges:
    aug = by_key[("2011/12", "Proj.", "August")]
    sep = by_key[("2011/12", "Proj.", "September")]
    assert math.isclose(aug["value"], 7.60)          # midpoint of 7.00 - 8.20
    assert math.isclose(aug["value_low"], 7.00)
    assert math.isclose(aug["value_high"], 8.20)
    assert math.isclose(sep["value"], 7.85)          # midpoint of 7.35 - 8.35
    assert math.isclose(sep["value_low"], 7.35)
    assert math.isclose(sep["value_high"], 8.35)
    assert aug["unit"] == "$/bu"                     # from the "($/bu)" label tag


def test_wheat_2026_point_farm_price() -> None:
    rows = _parse_us("us_wheat_2026_07_p10.pdf", "2026-07-10")
    price = _rows_where(rows, attribute="avg_farm_price", market_year="2026/27")
    assert len(price) == 2                            # both projection columns
    for r in price:
        assert math.isclose(r["value"], 6.00)
        assert r["value_low"] is None and r["value_high"] is None
    assert {r["projection_month"] for r in price} == {"June", "July"}


# ---------------------------------------------------------------------------
# Acreage / yield rows present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,date", [
    ("us_wheat_2011_09_p10.pdf", "2011-09-12"),
    ("us_wheat_2026_07_p10.pdf", "2026-07-10"),
    ("us_cotton_2026_07_p16.pdf", "2026-07-10"),
])
def test_planted_harvested_yield_present(name: str, date: str) -> None:
    attrs = {r["attribute"] for r in _parse_us(name, date)}
    assert {"planted_area", "harvested_area", "yield"} <= attrs


def test_wheat_2011_acreage_values() -> None:
    rows = _parse_us("us_wheat_2011_09_p10.pdf", "2011-09-12")
    planted = _rows_where(rows, attribute="planted_area", market_year="2009/10")[0]
    assert math.isclose(planted["value"], 59.2)


# ---------------------------------------------------------------------------
# by-class block: a THIRD geometry (classes-as-columns) that MUST yield zero
# ---------------------------------------------------------------------------

def test_wheat_by_class_block_yields_zero_rows() -> None:
    for name, date in (("us_wheat_2011_09_p10.pdf", "2011-09-12"),
                       ("us_wheat_2026_07_p10.pdf", "2026-07-10")):
        rows = _parse_us(name, date)
        # exactly ONE table (the main balance sheet); the "U.S. Wheat by Class"
        # sub-table never opens a year-column model, so nothing is emitted for it.
        assert {r["table_name"] for r in rows} == {"U.S. Wheat Supply and Use"}
        # region is always United States -- no wheat CLASS ("Hard Red Winter") leaks
        assert {r["region"] for r in rows} == {"United States"}
        # every attribute is a known whitelist term or a documented niche slug --
        # never a class figure mis-emitted as a year column.
        for r in rows:
            assert r["attribute"] in _WASDE_WHITELIST or r["attribute"] in {
                "ccc_inventory", "free_stocks", "outstanding_loans",
            }, r["attribute"]


# ---------------------------------------------------------------------------
# Soybean products: oil (c/lb) + meal ($/s.t.) via the "avg. price" label drift
# ---------------------------------------------------------------------------

def test_soy_three_subtables_distinct() -> None:
    rows = _parse_us("us_soy_2026_07_p14.pdf", "2026-07-10")
    assert {r["table_name"] for r in rows} == {
        "U.S. Soybeans Supply and Use",
        "U.S. Soybean Oil Supply and Use",
        "U.S. Soybean Meal Supply and Use",
    }


def test_soy_oil_meal_price_via_avg_price_alias() -> None:
    rows = _parse_us("us_soy_2026_07_p14.pdf", "2026-07-10")
    oil = _rows_where(rows, table_name="U.S. Soybean Oil Supply and Use",
                      attribute="avg_farm_price", projection_month="July")[0]
    meal = _rows_where(rows, table_name="U.S. Soybean Meal Supply and Use",
                       attribute="avg_farm_price", projection_month="July")[0]
    assert math.isclose(oil["value"], 70.00) and oil["unit"] == "c/lb"
    assert math.isclose(meal["value"], 310.00) and meal["unit"] == "$/s.t."


# ---------------------------------------------------------------------------
# Cotton: negative values + bare "Planted"/"Harvested" labels (Area header split)
# ---------------------------------------------------------------------------

def test_cotton_negatives_parsed() -> None:
    rows = _parse_us("us_cotton_2026_07_p16.pdf", "2026-07-10")
    un = _rows_where(rows, attribute="unaccounted", projection_month="July")
    assert un and math.isclose(un[0]["value"], -0.10)


# ---------------------------------------------------------------------------
# Two projection columns emitted with distinct months (D4: selection is downstream)
# ---------------------------------------------------------------------------

def test_two_projection_columns_distinct() -> None:
    rows = _parse_us("us_wheat_2026_07_p10.pdf", "2026-07-10")
    bs = _rows_where(rows, attribute="beginning_stocks", market_year="2026/27",
                     status="Proj.")
    by_month = {r["projection_month"]: r["value"] for r in bs}
    assert set(by_month) == {"June", "July"}
    assert not math.isclose(by_month["June"], by_month["July"])   # 935 vs 920


# ---------------------------------------------------------------------------
# World tables: the columnar path is untouched (byte-identical rows)
# ---------------------------------------------------------------------------

def test_world_page_columnar_path_unchanged() -> None:
    with pdfplumber.open(FX / "world_wheat_2026_07_p17.pdf") as pdf:
        world = _parse_columnar_page(pdf.pages[0], "2026-07-10")
    assert len(world) > 100
    assert any(r["region"] == "United States" for r in world)


def test_end_to_end_routing_world_matches_columnar() -> None:
    pdf_bytes = (FX / "world_wheat_2026_in_window.pdf").read_bytes()
    df = parse_wasde_pdf_digital(pdf_bytes, "2026-07-10")
    # The World page must route to the UNCHANGED _parse_columnar_page: the routed
    # frame equals _to_dataframe over that parser's rows exactly (the new value_low/
    # value_high columns are all-null for World rows and are excluded from the diff).
    with pdfplumber.open(FX / "world_wheat_2026_07_p17.pdf") as pdf:
        expected = _to_dataframe(_parse_columnar_page(pdf.pages[0], "2026-07-10"))
    cols = ["table_name", "region", "market_year", "status", "projection_month",
            "attribute", "value", "unit"]
    got = df[cols].reset_index(drop=True)
    exp = expected[cols].reset_index(drop=True)
    from pandas.testing import assert_frame_equal
    assert_frame_equal(got, exp)
    assert df["value_low"].isna().all() and df["value_high"].isna().all()


def test_end_to_end_routing_us_page() -> None:
    pdf_bytes = (FX / "us_wheat_2026_in_window.pdf").read_bytes()
    df = parse_wasde_pdf_digital(pdf_bytes, "2026-07-10")
    assert {"value_low", "value_high"} <= set(df.columns)
    price = df[(df["attribute"] == "avg_farm_price") & (df["market_year"] == "2026/27")]
    assert len(price) == 2
    assert (df["region"] == "United States").all()


# ---------------------------------------------------------------------------
# _is_us_transposed_heading: routing discriminator
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heading,expected", [
    ("U.S. Wheat Supply and Use 1/", True),
    ("U.S. Soybeans and Products Supply and Use (Domestic Measure) 1/", True),
    ("U.S. Cotton Supply and Use 1/", True),
    ("World Wheat Supply and Use 1/", False),
    ("World and U.S. Supply and Use for Grains", False),   # combined summary page
    ("World Soybean Oil Supply and Use", False),
])
def test_is_us_transposed_heading(heading: str, expected: bool) -> None:
    assert _is_us_transposed_heading(heading) is expected


# ---------------------------------------------------------------------------
# _normalise_us_item: EXPLICIT map -- core resolves, niche stays distinct
# (recon MISS #2: the greedy-prefix normaliser silently COLLAPSED distinct
# use-side lines onto core attributes; this map must NOT).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("Area Planted", "planted_area"),
    ("Planted", "planted_area"),                       # cotton bare form
    ("Area Harvested", "harvested_area"),
    ("Yield per Harvested Acre", "yield"),
    ("Supply, Total", "total_supply"),
    ("Use, Total", "total_use"),
    ("Domestic, Total", "domestic_total"),
    ("Domestic Use", "domestic_total"),
    ("Exports, Total", "exports"),
    ("Crushings", "crush"),
    ("Avg. Farm Price ($/bu) 2/", "avg_farm_price"),
    ("Avg. Price (c/lb) 2/", "avg_farm_price"),        # 2019+ oil/meal drift
    # niche lines: MUST stay distinct (never collapse onto a core attribute)
    ("Domestic & Residual 3/", "domestic_residual"),
    ("Food, Feed & other Industrial", "food_feed_other_industrial"),
    ("Domestic Disappearance", "domestic_disappearance"),
    ("Unaccounted 2/", "unaccounted"),
    ("Methyl Ester", "methyl_ester"),
    ("Milled (rough equiv.)", "milled"),
])
def test_normalise_us_item(label: str, expected: str) -> None:
    assert _normalise_us_item(label) == expected


def test_normalise_us_item_no_greedy_prefix_corruption() -> None:
    # these three would have collapsed onto domestic_total / food_use under the
    # generic _normalise_attr greedy prefix -- proving they now stay quarantined.
    for label in ("Domestic & Residual", "Food, Feed & other Industrial",
                  "Domestic Disappearance"):
        assert _normalise_us_item(label) not in _WASDE_WHITELIST


# ---------------------------------------------------------------------------
# Range tokenizer edge cases (unit-level: synthetic word groups)
# ---------------------------------------------------------------------------

def _w(text: str, x0: float, x1: float, top: float = 100.0) -> dict:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 9}


def test_range_tokenizer_midpoint() -> None:
    grp = [_w("Price", 40, 70),
           _w("7.00", 100, 120), _w("-", 122, 126), _w("8.20", 128, 148)]
    label, cells = _us_row_cells(grp)
    assert label == "Price"
    assert len(cells) == 1
    assert math.isclose(cells[0]["value"], 7.60)
    assert math.isclose(cells[0]["low"], 7.00)
    assert math.isclose(cells[0]["high"], 8.20)


def test_range_tokenizer_joined_token() -> None:
    grp = [_w("Price", 40, 70), _w("355.00-385.00", 100, 150)]
    _label, cells = _us_row_cells(grp)
    assert len(cells) == 1
    assert math.isclose(cells[0]["value"], 370.00)
    assert math.isclose(cells[0]["low"], 355.00)


def test_range_tokenizer_negatives_and_commas() -> None:
    grp = [_w("X", 40, 55),
           _w("-0.04", 100, 122), _w("2,993", 200, 230), _w("0", 300, 308)]
    _label, cells = _us_row_cells(grp)
    vals = [c["value"] for c in cells]
    assert len(cells) == 3
    assert math.isclose(vals[0], -0.04)
    assert math.isclose(vals[1], 2993.0)
    assert math.isclose(vals[2], 0.0)
    assert all(c["low"] is None for c in cells)       # none are ranges


def test_range_tokenizer_null_hyphens() -> None:
    # a standalone "-" / "--" FAR from its neighbours is a NULL cell (NaN), not a
    # range separator (the range gap guard: internal gap << column gap).
    grp = [_w("X", 40, 55),
           _w("5.0", 100, 120), _w("-", 200, 204), _w("--", 300, 308)]
    _label, cells = _us_row_cells(grp)
    assert len(cells) == 3
    assert math.isclose(cells[0]["value"], 5.0)
    assert math.isnan(cells[1]["value"]) and math.isnan(cells[2]["value"])


def test_range_tokenizer_footnote_markers_dropped() -> None:
    # "*"/"**" acreage-source markers between value columns are dropped, not
    # mistaken for cells (2026 Area rows carry them).
    grp = [_w("Area", 40, 60), _w("Planted", 62, 90),
           _w("46.3", 100, 120), _w("*", 130, 134), _w("42.7", 200, 220)]
    label, cells = _us_row_cells(grp)
    assert label == "Area Planted"
    assert [c["value"] for c in cells] == [46.3, 42.7]


# ---------------------------------------------------------------------------
# F1 blocker: range-era (2011) SECONDARY sub-tables must NOT merge into and
# overwrite the primary on the natural key.  The 2011-09 soybeans/products page
# and feed-grain/corn page carry the reversed+status-glued year header
# ("10/2009 .Est11/2010 .Proj12/2011") that the forward matcher missed, so
# Corn/Soybean Oil/Soybean Meal silently merged into (and, after keep-last
# dedup) clobbered Soybeans / Feed Grains -- destroying the genuine soybean and
# corn $/bu farm price.  These pin the reversed-year recognizer + hard boundary.
# ---------------------------------------------------------------------------

def test_reversed_glued_year_token() -> None:
    # the range-era secondary sub-table year header form
    assert _match_reversed_us_year("10/2009") == ("2009/10", "")
    assert _match_reversed_us_year(".Est11/2010") == ("2010/11", "Est.")
    assert _match_reversed_us_year(".Proj12/2011") == ("2011/12", "Proj.")
    # a forward YYYY/SS token is NOT a reversed token (the two never collide)
    assert _match_reversed_us_year("2009/10") is None
    assert _match_reversed_us_year("Argentina") is None


def test_soy_2011_three_subtables_distinct_no_clobber() -> None:
    # Soybeans + Soybean Oil + Soybean Meal must be THREE distinct tables, not one
    # merged blob; the reversed-glued year header now opens each sub-table.
    rows = _parse_us("us_soy_2011_09_p14.pdf", "2011-09-12")
    assert {r["table_name"] for r in rows} == {
        "U.S. Soybeans Supply and Use",
        "U.S. Soybean Oil Supply and Use",
        "U.S. Soybean Meal Supply and Use",
    }
    # the genuine soybean $/bu farm price SURVIVES the _to_dataframe keep-last dedup
    # (before the fix, the meal $/s.t. row shared the natural key and clobbered it).
    df = _to_dataframe(rows)
    soy_price = df[(df["table_name"] == "U.S. Soybeans Supply and Use")
                   & (df["attribute"] == "avg_farm_price")]
    by_key = {(r.market_year, r.status, r.projection_month): r
              for r in soy_price.itertuples()}
    settled = by_key[("2009/10", "", "")]
    assert math.isclose(settled.value, 9.59) and settled.unit == "$/bu"
    aug = by_key[("2011/12", "Proj.", "August")]
    assert math.isclose(aug.value, 13.50)          # midpoint of 12.50 - 14.50
    assert math.isclose(aug.value_low, 12.50) and math.isclose(aug.value_high, 14.50)
    assert aug.unit == "$/bu"                       # NOT the meal's $/s.t.


def test_soy_2011_oil_meal_units_and_prices() -> None:
    rows = _parse_us("us_soy_2011_09_p14.pdf", "2011-09-12")
    oil = _rows_where(rows, table_name="U.S. Soybean Oil Supply and Use",
                      attribute="avg_farm_price", projection_month="September")[0]
    meal = _rows_where(rows, table_name="U.S. Soybean Meal Supply and Use",
                       attribute="avg_farm_price", projection_month="September")[0]
    assert math.isclose(oil["value"], 57.00) and oil["unit"] == "c/lb"      # 55.00-59.00
    assert math.isclose(meal["value"], 375.00) and meal["unit"] == "$/s.t."  # 360.00-390.00
    # F2: the oil/meal balance-sheet unit banner ("FillerMillion Pounds") resolves
    # to a clean "Million Pounds" -- no "Filler" glyph-artifact prefix leaks through.
    oil_bs = _rows_where(rows, table_name="U.S. Soybean Oil Supply and Use",
                         attribute="beginning_stocks")
    assert oil_bs and all("Filler" not in str(r["unit"]) for r in oil_bs)
    assert any(r["unit"] == "Million Pounds" for r in oil_bs)


def test_feedgrain_2011_corn_distinct_from_feedgrains_no_contamination() -> None:
    # Feed Grains and Corn are DISTINCT tables; corn's Million-Bushel figures must
    # NOT contaminate feed grains' Metric-Ton balance sheet (the F1 evidence:
    # feed-grains domestic_total was overwritten by corn's 11,086).
    rows = _parse_us("us_feedgrain_2011_09_p11.pdf", "2011-09-12")
    assert {"U.S. Feed Grains Supply and Use",
            "U.S. Corn Supply and Use"} <= {r["table_name"] for r in rows}
    fg = _rows_where(rows, table_name="U.S. Feed Grains Supply and Use",
                     attribute="domestic_total", market_year="2009/10")[0]
    assert math.isclose(fg["value"], 295.1)         # feed grains (metric tons), NOT corn's 11,086
    corn = _rows_where(rows, table_name="U.S. Corn Supply and Use",
                       attribute="planted_area", market_year="2011/12", projection_month="September")[0]
    assert math.isclose(corn["value"], 92.3)        # corn's own acreage


# ---------------------------------------------------------------------------
# _us_commodity_banner: tolerant all-caps banner matcher (clean + shredded forms)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texts,expected", [
    (["SOYBEAN", "OIL"], "SOYBEAN OIL"),
    (["CORN"], "CORN"),
    (["TOTAL", "RICE"], "TOTAL RICE"),
    (["MEDIUM", "&", "SHORT-GRAIN", "RICE"], "MEDIUM & SHORT-GRAIN RICE"),
    # range-era shredded form: the reversed-year status markers spill onto the
    # banner line as trailing tokens (2011-2015 Sorghum/Barley/Oats page).
    (["BARLEY", ".Est", ".Proj", ".Proj"], "BARLEY"),
    (["OATS", ".Est", ".Proj", ".Proj"], "OATS"),
    # a normal mixed-case data label is NOT a banner
    (["Area", "Planted"], None),
    (["Beginning", "Stocks"], None),
    (["Ending", "stocks"], None),
])
def test_us_commodity_banner(texts, expected) -> None:
    assert _us_commodity_banner(texts) == expected


# ---------------------------------------------------------------------------
# F2 (_strip_filler): the glued "FillerMillion" glyph-artifact is stripped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("FillerMillion Pounds", "Million Pounds"),    # oil/meal unit banner (glued)
    ("FillerMillion", "Million"),
    ("Argentina filler 1.37", "Argentina  1.37"),  # standalone word (unchanged behavior)
    ("FILLER World", "World"),
    ("World 127.59", "World 127.59"),              # no filler -> untouched
])
def test_strip_filler_glued_prefix(raw: str, expected: str) -> None:
    assert _strip_filler(raw) == expected


# ---------------------------------------------------------------------------
# F2-avg-price finding: the shared bronze _ATTRIBUTE_ALIASES no longer carries a
# bare "avg. price" alias, so the greedy-prefix _normalise_attr on the colon-era
# US + World columnar paths (the byte-identical pre-2011 / World tables) is
# UNCHANGED.  The modern US oil/meal "Avg. Price" drift is handled by the
# transposed-US parser's own explicit map, verified above.
# ---------------------------------------------------------------------------

def test_avg_price_alias_absent_from_shared_bronze_table() -> None:
    assert "avg. price" not in _ATTRIBUTE_ALIASES
    assert _ATTRIBUTE_ALIASES["avg. farm price"] == "avg_farm_price"
    # on the shared/colon path, bare "Avg. Price" falls through (quarantined at
    # silver) exactly as it did pre-W1 -- it does NOT resolve to avg_farm_price.
    assert _normalise_attr("Avg. Price") != "avg_farm_price"
    # the modern US parser's explicit map still resolves the oil/meal drift
    assert _normalise_us_item("Avg. Price (c/lb) 2/") == "avg_farm_price"
