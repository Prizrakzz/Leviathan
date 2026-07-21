"""LANE SA shadow-first publish + INV-2 encode proof for the changed producers (F022/F023/F024).

Every changed producer routes its write through the SILVER-F015 shadow-first publisher with the
INV-2 arrow writer schema from the F010 registry contract. These tests prove, per table:
  * dry-run stages NOTHING (canonical never touched);
  * shadow stages to the shadow prefix only (canonical never touched);
  * canonical promotes to the canonical key;
  * the INV-2 encode round-trips the exact contract schema (widened int64/float64, pinned string,
    timestamp[us] date).
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from leviathan.silver.flat_producer import build_flat_publish, encode_parquet, pa_schema_from_contract
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver.faostat_production import (
    CANONICAL_PHYSICAL_COLUMNS,
    transform_faostat_production_silver_df,
)
from leviathan.transforms.bronze_to_silver.pink_sheet import _SERIES_RENAME, build_silver

from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_REG = load_registry()
_BUCKET = "leviathan-test"


# --------------------------------------------------------------------------- pink_sheet (F023)
def _pink_silver() -> pd.DataFrame:
    # 120 months of history so the rolling 5-yr z-scores (min 36 months) are ~70% non-null -- the F010
    # value_columns now spans all 32 governed columns (W2), so the publisher's 0.5 non-null floor applies
    # to the 16 zscore columns too; a single-month frame would fail validation on all-null zscores.
    months = [date(2016 + (m // 12), (m % 12) + 1, 1) for m in range(120)]
    rows = [{
        "date": d, "series_name": bn, "value_usd": 100.0 + i + (j % 7),
        "release_ym": "2026M05", "source": "world_bank_pink_sheet",
    } for i, bn in enumerate(_SERIES_RENAME) for j, d in enumerate(months)]
    return build_silver([pd.DataFrame(rows)])


def test_pink_sheet_inv2_encode_roundtrips_36_cols():
    contract = _REG.table("silver_pink_sheet")
    table = pq.read_table(io.BytesIO(encode_parquet(_pink_silver(), contract)))
    assert table.schema.equals(pa_schema_from_contract(contract))
    assert table.num_columns == 36
    assert table.schema.field("date").type == pa.timestamp("us")
    assert table.schema.field("year").type == pa.int64()
    assert table.schema.field("brent_crude_usd_bbl").type == pa.float64()


def test_pink_sheet_dry_run_touches_nothing():
    contract = _REG.table("silver_pink_sheet")
    s3 = FakeS3()
    m = build_flat_publish(df=_pink_silver(), contract=contract,
                           canonical_key="silver/pink_sheet/part-000.parquet",
                           auth=dryrun_authorization(), s3_client=None, job="t").run()
    assert m.state is ManifestState.VALIDATED
    assert s3.keys() == []


def test_pink_sheet_shadow_never_writes_canonical():
    contract = _REG.table("silver_pink_sheet")
    s3 = FakeS3()
    build_flat_publish(df=_pink_silver(), contract=contract,
                       canonical_key="silver/pink_sheet/part-000.parquet",
                       auth=shadow_authorization(), s3_client=s3, job="t").run()
    assert "silver/pink_sheet/part-000.parquet" not in s3.keys()
    assert any("_shadow" in k for k in s3.keys())


# --------------------------------------------------------------------------- faostat (F022)
def _faostat_body() -> pd.DataFrame:
    bronze = pd.DataFrame({
        "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Production"], "year": [2020],
        "unit": ["tonnes"], "value": [9e5], "flag": [""], "ingest_date": ["2024-01-01"],
    })
    _, body = transform_faostat_production_silver_df(bronze, commodity="cocoa")[0]
    return body


def test_faostat_inv2_encode_roundtrips_12_cols():
    contract = _REG.table("silver_production")
    table = pq.read_table(io.BytesIO(encode_parquet(_faostat_body(), contract)))
    assert list(table.schema.names) == CANONICAL_PHYSICAL_COLUMNS
    assert table.num_columns == 12
    assert table.schema.field("is_official").type == pa.bool_()
    assert table.schema.field("value").type == pa.float64()


def test_faostat_canonical_promotes_to_projected_path():
    contract = _REG.table("silver_production")
    s3 = FakeS3()
    key = "silver/production/commodity=cocoa/year=2020/part-000.parquet"
    m = build_flat_publish(df=_faostat_body(), contract=contract, canonical_key=key,
                           auth=canonical_authorization(), s3_client=s3, job="t").run()
    assert m.state is ManifestState.CERTIFIED
    assert key in s3.keys()


def test_faostat_shadow_never_writes_canonical():
    contract = _REG.table("silver_production")
    s3 = FakeS3()
    key = "silver/production/commodity=cocoa/year=2020/part-000.parquet"
    build_flat_publish(df=_faostat_body(), contract=contract, canonical_key=key,
                       auth=shadow_authorization(), s3_client=s3, job="t").run()
    assert key not in s3.keys()


def test_encode_rejects_wrong_shape():
    contract = _REG.table("silver_production")
    with pytest.raises(ValueError):
        encode_parquet(_faostat_body().drop(columns=["value"]), contract)
