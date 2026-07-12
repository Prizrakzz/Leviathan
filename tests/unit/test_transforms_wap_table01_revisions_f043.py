"""SILVER-F043 -- WAP Table 01 key inference + revision linkage.

Covers the two corrections:
  1. Key inference: a missing/ambiguous marketing_year is NEVER published as a null
     natural-key component -- the row is quarantined. The 2016-08 oilseeds block whose
     projection row carries a footnote (``proj. 1/``) is still inferred (generalised).
  2. Revision linkage: a revision links to the previous release in which the SAME
     complete logical key appears, not the previous GLOBAL release. Every non-first
     revision references an actual prior row for the same key; base and revisions share
     an identical business-key set; an in-release natural-key conflict fails closed.
"""
from __future__ import annotations

import math

import pandas as pd
import pyarrow as pa
import pytest

from leviathan.transforms.bronze_to_silver.wap_table01 import (
    BUSINESS_KEY,
    MODERN_COUNTRY_COLUMNS,
    REVISION_ARROW_SCHEMA,
    REVISION_COLUMNS,
    SILVER_COLUMNS,
    _derive_marketing_year_for_months,
    _is_projection_status,
    assert_identical_business_keys,
    build_long_table,
    build_long_table_with_quarantine,
    build_revision_table,
)


def _bronze_row(release_month: str, commodity: str, row_label: str, **country_values) -> dict:
    row = {"release_month": release_month, "commodity": commodity, "row_label": row_label}
    for col in MODERN_COUNTRY_COLUMNS:
        row[col] = country_values.get(col, 0.0)
    return row


def _bronze_df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# ---------------------------------------------------------------------------
# 1. Key inference / quarantine
# ---------------------------------------------------------------------------

class TestKeyInference:
    def test_projection_status_generalised(self):
        assert _is_projection_status("proj.")
        assert _is_projection_status("proj. 1/")   # 2016-08 oilseeds footnote
        assert _is_projection_status("Proj")
        assert not _is_projection_status("prel.")
        assert not _is_projection_status(None)

    def test_2016_08_oilseeds_footnoted_proj_infers_month_year(self):
        # The projection year row carries a footnote marker; a month row must still
        # inherit its marketing_year rather than be quarantined.
        rows = [
            {"release_month": "2016-08", "commodity": "oilseeds", "row_label": "2016/17 proj. 1/",
             "vintage_type": "year", "vintage_status": "proj. 1/", "marketing_year": "2016/17",
             "month_abbr": None},
            {"release_month": "2016-08", "commodity": "oilseeds", "row_label": "Jul",
             "vintage_type": "month", "vintage_status": None, "marketing_year": None,
             "month_abbr": "Jul"},
        ]
        out = _derive_marketing_year_for_months(pd.DataFrame(rows))
        month = out[out["vintage_type"] == "month"].iloc[0]
        assert month["marketing_year"] == "2016/17"

    def test_month_without_proj_is_quarantined_not_published(self):
        # A month row whose block has NO projection year cannot get a marketing_year.
        df = _bronze_df(_bronze_row("2020-05", "corn", "May", us=42.0))
        valid, quarantine = build_long_table_with_quarantine([df])
        # Never published with a null natural-key component.
        assert valid["marketing_year"].isna().sum() == 0
        assert (valid["commodity"] == "corn").sum() == 0
        # But captured in quarantine with a reason.
        assert (quarantine["quarantine_reason"] == "null_marketing_year").any()

    def test_ambiguous_block_year_quarantined(self):
        # Two DISTINCT projection years in one block -> ambiguous -> do NOT impute.
        rows = [
            {"release_month": "2019-06", "commodity": "soy", "row_label": "2019/20 proj.",
             "vintage_type": "year", "vintage_status": "proj.", "marketing_year": "2019/20",
             "month_abbr": None},
            {"release_month": "2019-06", "commodity": "soy", "row_label": "2018/19 proj.",
             "vintage_type": "year", "vintage_status": "proj.", "marketing_year": "2018/19",
             "month_abbr": None},
            {"release_month": "2019-06", "commodity": "soy", "row_label": "Apr",
             "vintage_type": "month", "vintage_status": None, "marketing_year": None,
             "month_abbr": "Apr"},
        ]
        out = _derive_marketing_year_for_months(pd.DataFrame(rows))
        month = out[out["vintage_type"] == "month"].iloc[0]
        assert month["marketing_year"] is None  # left null -> will be quarantined

    def test_no_null_marketing_year_in_published_output(self):
        df = _bronze_df(
            _bronze_row("2024-05", "wheat", "2024/25 proj.", us=100.0),
            _bronze_row("2024-05", "wheat", "May", us=99.0),   # inherits 2024/25
            _bronze_row("2024-05", "corn", "May", us=42.0),    # no proj -> quarantined
        )
        valid = build_long_table([df])
        assert valid["marketing_year"].notna().all()
        assert valid["marketing_year"].str.match(r"^\d{4}/\d{2}$").all()


# ---------------------------------------------------------------------------
# 2. Revision linkage
# ---------------------------------------------------------------------------

class TestRevisionLinkage:
    def _long(self, records) -> pd.DataFrame:
        rows = []
        for rm, commodity, my, val in records:
            rows.append({
                "release_month": rm, "commodity": commodity, "row_label": f"{my} proj.",
                "marketing_year": my, "vintage_type": "year", "vintage_status": "proj.",
                "month_abbr": None, "country": "us", "value_mmt": val,
            })
        return pd.DataFrame(rows, columns=SILVER_COLUMNS)

    def test_links_to_previous_release_where_key_appears(self):
        # wheat/us appears in 2024-03 and 2024-05 but NOT 2024-04. The revision at
        # 2024-05 must link to 2024-03 (previous where the key appears), NOT be null
        # because 2024-04 (the global previous release) lacks the key.
        df_long = self._long([
            ("2024-03", "wheat", "2024/25", 100.0),
            ("2024-04", "rice",  "2024/25", 50.0),   # a different key -> makes 2024-04 a release
            ("2024-05", "wheat", "2024/25", 104.0),
        ])
        rev = build_revision_table(df_long)
        w = rev[(rev["release_month"] == "2024-05") & (rev["commodity"] == "wheat")].iloc[0]
        assert w["prior_release_month"] == "2024-03"
        assert w["prior_value_mmt"] == pytest.approx(100.0)
        assert w["revision_mmt"] == pytest.approx(4.0)

    def test_first_appearance_has_nan_prior(self):
        df_long = self._long([("2024-03", "wheat", "2024/25", 100.0)])
        rev = build_revision_table(df_long)
        r = rev.iloc[0]
        assert r["prior_release_month"] is None or (isinstance(r["prior_release_month"], float) and math.isnan(r["prior_release_month"]))
        assert math.isnan(r["revision_mmt"])

    def test_every_nonfirst_revision_references_a_real_prior_row(self):
        df_long = self._long([
            ("2024-03", "wheat", "2024/25", 100.0),
            ("2024-05", "wheat", "2024/25", 104.0),
            ("2024-06", "wheat", "2024/25", 103.0),
        ])
        rev = build_revision_table(df_long)
        _SENT = "\x00NULL"
        # Fill nullable key cols with a shared sentinel so a None key still matches.
        prior = df_long.rename(
            columns={"release_month": "prior_release_month", "value_mmt": "expected_prior"}
        )[["prior_release_month"] + BUSINESS_KEY + ["expected_prior"]].copy()
        rev2 = rev.copy()
        for c in BUSINESS_KEY:
            prior[c] = prior[c].fillna(_SENT)
            rev2[c] = rev2[c].fillna(_SENT)
        merged = rev2.merge(prior, on=["prior_release_month"] + BUSINESS_KEY, how="left")
        nonfirst = merged[merged["prior_release_month"].notna()]
        # Every non-first revision matched an actual prior row (expected_prior not NaN)
        # and its prior_value_mmt equals that row's value.
        assert nonfirst["expected_prior"].notna().all()
        assert (nonfirst["prior_value_mmt"] == nonfirst["expected_prior"]).all()
        # The 2024-06 revision links to 2024-05 (the prior release where the key appears).
        r06 = rev[rev["release_month"] == "2024-06"].iloc[0]
        assert r06["prior_release_month"] == "2024-05"
        assert r06["revision_mmt"] == pytest.approx(-1.0)

    def test_natural_key_conflict_fails_closed(self):
        # Same (release_month + business key) twice -> unresolved conflict -> raise.
        df_long = self._long([
            ("2024-05", "wheat", "2024/25", 100.0),
            ("2024-05", "wheat", "2024/25", 101.0),
        ])
        with pytest.raises(ValueError, match="natural-key conflict"):
            build_revision_table(df_long)

    def test_output_columns_and_empty(self):
        rev = build_revision_table(pd.DataFrame(columns=SILVER_COLUMNS))
        assert list(rev.columns) == REVISION_COLUMNS
        assert len(rev) == 0


# ---------------------------------------------------------------------------
# 3. base vs revisions business-key parity + end-to-end
# ---------------------------------------------------------------------------

class TestBaseRevisionParity:
    def _two_release_bronze(self):
        return [
            _bronze_df(
                _bronze_row("2024-04", "wheat", "2024/25 proj.", us=100.0, brazil=30.0),
                _bronze_row("2024-04", "wheat", "Apr", us=10.0, brazil=3.0),
            ),
            _bronze_df(
                _bronze_row("2024-05", "wheat", "2024/25 proj.", us=102.0, brazil=31.0),
                _bronze_row("2024-05", "wheat", "Apr", us=10.5, brazil=3.1),
            ),
        ]

    def test_base_and_revisions_have_identical_business_keys(self):
        base = build_long_table(self._two_release_bronze())
        rev = build_revision_table(base)
        # Must not raise.
        assert_identical_business_keys(base, rev)

    def test_month_row_revision_uses_derived_year(self):
        base = build_long_table(self._two_release_bronze())
        rev = build_revision_table(base)
        apr_us = rev[
            (rev["release_month"] == "2024-05")
            & (rev["month_abbr"] == "Apr")
            & (rev["country"] == "us")
        ].iloc[0]
        assert apr_us["marketing_year"] == "2024/25"
        assert apr_us["prior_release_month"] == "2024-04"
        assert apr_us["revision_mmt"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 4. INV-2 schema reconciliation with the registry
# ---------------------------------------------------------------------------

_TARGET_TO_PA = {
    "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(),
    "bool": pa.bool_(), "date32[day]": pa.date32(), "timestamp[us]": pa.timestamp("us"),
}


def test_revision_schema_matches_registry():
    from leviathan.silver.registry import load_registry

    contract = load_registry().table("silver_wap_table01_revisions")
    expected = {c["name"]: _TARGET_TO_PA[c["target_arrow_type"]]
                for c in contract["physical_columns"]}
    actual = {f.name: f.type for f in REVISION_ARROW_SCHEMA}
    assert actual == expected
