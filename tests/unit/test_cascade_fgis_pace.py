"""GN-2 W1.4 -- the FGIS honest-pace seam, pinned as the recon's R1 FATAL made impossible.

silver_fgis's date_col IS its knowledge_date_col (week_ending_date), so query._extras surfaces the
week under ONLY the `knowledge_date` alias on live rows.  The legacy _pace_period_key alias list
deliberately excludes `knowledge_date` (load-bearing for silver_cot / silver_pink_sheet /
silver_mpob, one-row-per-period by grain), so the naive 2-constant edit -- PACE_TABLES entry +
collapse kind, nothing else -- leaves every FGIS row its own "period": the collapse never groups,
and the pace delta is destinationB-minus-destinationA INSIDE one week, a fabrication riding a real
minted [N] row.  The seam is the table-scoped _PACE_PERIOD_KEY_EXTRA alias; these tests pin the
defect on the exact live-row shape, the fix on the same rows, and the two-key coupling as a law.

Pure Python -- no S3, no AWS, no pg.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag.numbers import cascade as cq

# The LIVE row shape: per destination x week, the week surfaced ONLY as `knowledge_date` (the
# _extras dedup when date_col == knowledge_date_col).  Two weeks, two destinations; the national
# weekly flow FALLS 100,000 -> 80,000 MT.
_FGIS_ROWS = [
    {"value": "40000", "knowledge_date": "2026-08-07", "country": "JAPAN"},
    {"value": "60000", "knowledge_date": "2026-08-07", "country": "MEXICO"},
    {"value": "30000", "knowledge_date": "2026-08-14", "country": "JAPAN"},
    {"value": "50000", "knowledge_date": "2026-08-14", "country": "MEXICO"},
]


def _rec(rows) -> dict:
    return {"rows": rows, "status": "ok", "leg": ("pace", "week")}


# -- THE NAMED DEFECT: the naive entry alone ships a cross-destination delta ------------------------
def test_without_the_alias_every_row_is_its_own_period_and_the_delta_is_a_fabrication():
    """The R1 FATAL, demonstrated: on a table with no _PACE_PERIOD_KEY_EXTRA entry the live rows
    carry no recognized alias, every row keys ("_row", idx), the multi-row fail-safe never fires
    (no period ever has 2 rows), and the 'pace' delta is MEXICO minus JAPAN inside 2026-08-14:
    +20,000 UP on a national flow that FELL 20,000."""
    vals, collapsed = cq._pace_series(_rec(_FGIS_ROWS), "silver_fgis_shadow")   # naive: undeclared
    assert vals == [40000.0, 60000.0, 30000.0, 50000.0] and collapsed is None
    assert vals[-1] - vals[-2] == pytest.approx(+20000.0)      # two DESTINATIONS, one week -- inverted


# -- THE SEAM: same rows, the declared table -------------------------------------------------------
def test_fgis_groups_per_week_and_sums_destinations():
    vals, collapsed = cq._pace_series(_rec(_FGIS_ROWS), "silver_fgis")
    assert vals == [100000.0, 80000.0]                          # ONE value per WEEK, national sum
    assert collapsed == "sum"
    assert vals[-1] - vals[-2] == pytest.approx(-20000.0)       # DOWN -- the honest direction


def test_the_signs_genuinely_oppose_on_the_same_rows():
    naive, _ = cq._pace_series(_rec(_FGIS_ROWS), "silver_fgis_shadow")
    fixed, _ = cq._pace_series(_rec(_FGIS_ROWS), "silver_fgis")
    assert (naive[-1] - naive[-2]) * (fixed[-1] - fixed[-2]) < 0


# -- _pace_period_key: the extra alias is TABLE-SCOPED, the legacy list untouched -------------------
def test_period_key_extra_alias_scoped_not_global():
    row = {"value": "1", "knowledge_date": "2026-08-14"}
    assert cq._pace_period_key(row, 3) == ("_row", 3)                       # legacy: deliberate exclusion
    assert cq._pace_period_key(row, 3, ("knowledge_date",)) == "2026-08-14"  # scoped: the seam
    # a recognized legacy alias still wins ahead of the fallback, with or without extra
    row2 = {"value": "1", "data_date": "2026-08-14", "knowledge_date": "2026-08-15"}
    assert cq._pace_period_key(row2, 0, ("knowledge_date",)) == "2026-08-15"  # extra is PREPENDED
    assert cq._pace_period_key(row2, 0) == "2026-08-14"


# -- THE TWO-KEY LAW: the PACE_TABLES entry is only legal together with its alias -------------------
def test_fgis_pace_registration_is_complete_or_nothing():
    """The naive 2-constant edit is the recorded fabrication; this pin makes it unshippable. If
    silver_fgis is ever removed from ONE of these registries, this test names the other two."""
    assert cq.PACE_TABLES.get("silver_fgis") == "week"
    assert cq._PACE_COLLAPSE.get("silver_fgis") == "sum"
    assert "silver_fgis" in cq._PACE_PERIOD_KEY_EXTRA
    assert "knowledge_date" in cq._PACE_PERIOD_KEY_EXTRA["silver_fgis"]
    assert "silver_fgis" not in cq._PRICE_TABLES               # tonnage, never a price: sum is legal
