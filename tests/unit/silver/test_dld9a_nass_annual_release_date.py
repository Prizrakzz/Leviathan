"""D-LD pre-step D-LD-9a: the derived ``release_date`` vintage anchor for ``silver_nass_annual``.

THE BLOCKER, MEASURED (2026-08-18, pyarrow over EVERY canonical object -- 593 parquet objects,
14,631 rows): the table carried NO date, vintage, ingest or month column of any kind. Its 14 body
columns were ``[leviathan_slug, country, state, year, marketing_year, area_planted_ha,
area_harvested_ha, yield_t_ha, production_mt, 4x *_cv_pct, source]``. ``year`` is the CROP year, not
a knowledge date, and there is no month -- so ``knowledge_col()`` returned ``None`` for every
semantics and ``query.build_sql`` raised *"no knowledge/date column to anchor the as-of guard"*.
There is no card-only construction for that; the fix has to come from the producer.

The remedy is the WIRING_WAVE1 idiom, coefficient for coefficient: ONE derived, conservative,
never-leak timing column (``silver_conab_coffee.survey_release_date`` /
``silver_sagis_weekly_exports.week_ending_date``). This file pins the three artifacts that must agree
about it -- the producer's column list, the checked-in Athena DDL, and the gated catalog migration --
plus the no-regression fences that keep the SILVER-F020 projection defect exactly where it is (that
enum is a separate, separately-gated SET TBLPROPERTIES, and the F020 tests measure it against the
CHECKED-IN enum).

AWS-free, no network: file reads + the pure transform module.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from leviathan.silver import ddl as D
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver.usda_nass_annual import (
    OUTPUT_COLUMNS,
    PRE_DLD_OUTPUT_COLUMNS,
    _release_date,
)

_REPO = Path(__file__).resolve().parents[3]
_TABLE = "silver_nass_annual"
_ANCHOR = "release_date"
_DDL_PATH = _REPO / "sql" / "athena" / "ddl" / f"{_TABLE}.sql"
_MIGRATION_PATH = (_REPO / "sql" / "athena" / "migrations" / "silver"
                   / "20260818T000000Z_silver_nass_annual_release_date_additive.json")


def _ddl_text() -> str:
    return _DDL_PATH.read_text(encoding="utf-8")


def _parsed():
    return D.parse_ddl(_ddl_text())


def _migration() -> dict:
    return json.loads(_MIGRATION_PATH.read_text(encoding="utf-8"))


def _contract() -> dict:
    return load_registry().table(_TABLE)


# ---------------------------------------------------------------------------
# The DDL carries the anchor -- appended LAST, nothing else moved.
# ---------------------------------------------------------------------------

def test_ddl_declares_the_anchor_as_the_appended_tail():
    """Appended LAST so the catalog order stays base-13 + this one additive tail. The order matters:
    jobs/utils/validate_athena_ddl_drift.py compares the hand DDL against live Glue IN ORDER, so the
    gated ADD COLUMNS append must line up with the append here."""
    cols = _parsed().columns
    assert cols[-1] == (_ANCHOR, "string")
    assert cols[-2][0] == "source"
    assert [n for n, _ in cols[:-1]] == [
        "leviathan_slug", "country", "state", "marketing_year",
        "area_planted_ha", "area_harvested_ha", "yield_t_ha", "production_mt",
        "area_planted_cv_pct", "area_harvested_cv_pct", "yield_cv_pct", "production_cv_pct",
        "source",
    ]


def test_ddl_partitioning_and_location_are_untouched():
    """The anchor is a BODY column, never a partition key: a date partition would multiply the
    projected (commodity x year) grid and re-open the S3 LIST-storm class this table is fenced
    against."""
    p = _parsed()
    assert p.partition_keys == (("commodity", "string"), ("year", "int"))
    assert p.partition_mode == "projected"
    assert p.location == _contract()["s3_root"]
    assert _ANCHOR not in {n for n, _ in p.partition_keys}


def test_every_column_the_dld_card_will_reference_resolves_in_the_ddl():
    """config_check.check_numbers_schema_pins resolves each card column with a word-boundary search
    against this file. Pinned here so the card's arrival cannot be the thing that discovers a gap --
    knowledge_date_col was the ONE failing pin in the D-LD package's section-5 table."""
    text = _ddl_text()
    for col in ("commodity", "state", "year", _ANCHOR,
                "production_mt", "yield_t_ha", "area_harvested_ha", "area_planted_ha"):
        assert re.search(rf"\b{re.escape(col)}\b", text), col


# ---------------------------------------------------------------------------
# Producer <-> DDL <-> migration agree about the same one column.
# ---------------------------------------------------------------------------

def test_producer_tail_matches_the_ddl_tail():
    assert OUTPUT_COLUMNS[-1] == _ANCHOR
    assert OUTPUT_COLUMNS[:-1] == PRE_DLD_OUTPUT_COLUMNS
    ddl_cols = [n for n, _ in _parsed().columns]
    # the DDL body list is the producer's list minus `year` (a partition key Athena serves from the
    # path, not from the catalog column list) -- and both end with the anchor.
    assert ddl_cols == [c for c in OUTPUT_COLUMNS if c != "year"]


def test_migration_is_authored_gated_and_applied():
    """INV-1 / the R2 convention: the repo change AUTHORED the catalog edit gated (applied:false);
    the orchestrator fired the ALTER on 2026-08-18 (Athena SUCCEEDED, D-LD tranche-2 landing batch)
    and flipped the record to applied:true in the same batch. This pin now guards the RECORD's
    truthfulness both ways: gated authorship stands, and applied reflects the live catalog."""
    m = _migration()
    assert m["table"] == _TABLE and m["database"] == "leviathan_dev"
    assert m["gated"] is True
    assert m["applied"] is True
    assert m["change_type"] == "additive_update"
    assert m["added_columns"] == [{"name": _ANCHOR, "glue_type": "string"}]
    assert m["apply_sql"] == (
        f"ALTER TABLE leviathan_dev.{_TABLE} ADD COLUMNS ({_ANCHOR} string);"
    )


def test_migration_added_column_is_exactly_what_the_ddl_appended():
    """One column, one type, one name -- said in three places, checked in one."""
    m = _migration()
    added = [(c["name"], c["glue_type"]) for c in m["added_columns"]]
    assert added == [_parsed().columns[-1]]


# ---------------------------------------------------------------------------
# The derivation itself: conservative, total, and a pure function of the crop year.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("crop_year,stamp", [
    (1866, "1867-02-01"),      # the corn/cotton history floor
    (1895, "1896-02-01"),      # rice
    (1924, "1925-02-01"),      # soybeans
    (2024, "2025-02-01"),
    (2025, "2026-02-01"),      # citable at a 2026-08-18 as-of
    (2026, "2027-02-01"),      # acreage-only row: correctly WITHHELD at any 2026 as-of
])
def test_derivation_is_the_february_first_after_the_january_summary(crop_year, stamp):
    assert _release_date(crop_year) == stamp


def test_the_2026_row_is_withheld_and_the_2025_row_is_citable_at_the_dld_asof():
    """The measured two-tier content ceiling: production/yield end at crop year 2025, while
    planted/harvested acreage additionally exists for 2026 (the June Acreage print). Under this
    vintage the 2026 row is not readable until 2027-02-01 -- deliberate, and the reason the card
    routes in-season questions to silver_nass_crop_progress."""
    asof = "2026-08-18"
    assert _release_date(2025) <= asof
    assert _release_date(2026) > asof


# ---------------------------------------------------------------------------
# NO-REGRESSION fences.
# ---------------------------------------------------------------------------

def test_silver_f020_projection_enum_is_untouched_by_this_change():
    """The invariant this pins is DDL == contract == live Glue -- unchanged. What changed is the
    VALUE both sides hold: SILVER-F020 was RESOLVED 2026-08-20 (D-EC wheat-lane flip) when the
    canonical promote landed all ten partitions and the Glue enum was ALTERed to the same ten in
    the same change (canola_ice un-hidden; the gated canola-only migration retired unapplied).
    The equality assertion below survives the flip verbatim: it never named the six, so it now
    pins the ten -- and it still catches the drift class it was written for (a hand edit to one
    side without the other)."""
    proj = dict(_parsed().projection)
    contract_proj = _contract()["projection_domains"]
    assert proj["projection.commodity.values"] == contract_proj["projection.commodity.values"]
    # The literal pins the POST-FLIP ten (2026-08-20): the six-value literal this replaced was the
    # F020-era state; live Glue was ALTERed to these ten in the same change as the canonical promote.
    assert proj["projection.commodity.values"] == (
        "corn_cbot,soybeans_cbot,rough_rice_cbot,cotton,"
        "soft_red_winter_wheat_cbot,hard_red_spring_wheat_mgex,"
        "canola_ice,cottonseed,upland_cotton,pima_cotton"
    )
    # Post-flip: canola_ice is IN the enum (un-hidden by the 2026-08-20 ten-value ALTER); the
    # F020 record stays applied:false because the canola-only migration was RETIRED UNAPPLIED --
    # superseded by the wider ALTER, not fired. Both directions pinned.
    assert "canola_ice" in proj["projection.commodity.values"]
    assert proj["projection.year.range"] == "1866,2035"
    f020 = json.loads(
        (_REPO / "reports" / "silver_readiness" / "R2_SA" / "F020_canola_migration.json")
        .read_text(encoding="utf-8")
    )
    assert f020["applied"] is False           # retired UNAPPLIED -- superseded, never fired
    assert "superseded" in f020               # the retirement is recorded, not implied


def test_the_weekly_nass_sibling_is_untouched():
    """silver_nass_crop_progress rides the SAME DAG and is the near neighbour this change must not
    disturb: it already has its own knowledge date and needs no anchor."""
    sibling = (_REPO / "sql" / "athena" / "ddl" / "silver_nass_crop_progress.sql").read_text(
        encoding="utf-8")
    assert _ANCHOR not in sibling


def test_the_anchor_never_touches_a_measured_value():
    """value_columns is the contract's list of what this table MEASURES; the anchor is timing only,
    so it must not appear there (and the F010 value SET must not have shifted).

    ASSERTED AS A SET, and the reason is a real change rather than a loosened pin. This test was
    written against the PRE-CARD contract, where value_columns fell through to the source_contract
    ``required_columns`` path and therefore came out in PHYSICAL COLUMN order. D-LD Tranche 2 landed
    the ``silver_nass_annual`` numbers card, and for a carded WIDE table ``build_contract`` derives
    value_columns from the CARD'S METRIC KEYS instead (gen_registry_from_baseline.py:549) -- INV-5's
    single authority moving from the source contract to the card, which is the whole point of carding
    a table. The card leads with ``production_mt`` because that is the metric order the MODEL reads,
    so the list is now [production_mt, yield_t_ha, area_harvested_ha, area_planted_ha]. MEMBERSHIP is
    byte-identical, nothing was added or dropped, and no consumer of value_columns is order-sensitive
    (it drives the per-column min_nonnull_frac floors). What this test actually guards -- that the
    timing anchor is not among the measured values -- is untouched and asserted below."""
    c = _contract()
    assert set(c["value_columns"]) == {
        "area_planted_ha", "area_harvested_ha", "yield_t_ha", "production_mt",
    }
    assert len(c["value_columns"]) == 4                  # no duplicates, no quiet additions
    assert _ANCHOR not in c["value_columns"]
    assert c["natural_key"] == ["commodity", "state", "year"]
