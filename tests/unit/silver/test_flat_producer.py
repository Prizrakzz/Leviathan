"""SILVER-F062 flat-producer runtime: INV-2 writer-schema pin + common-publisher glue.

Pure Python -- no S3/AWS (dry-run needs no client). Covers the arrow-schema build, the all-null
measure -> double guard (closing the null-type hazard), the DataFrame<->contract shape check, the
dry-run publish (nothing written, stops at VALIDATED), and the standard CLI + authorize helpers.
"""
from __future__ import annotations

import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.common.publish_guard import PublishMode
from leviathan.silver import value_census as vc
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    arrow_type_for,
    authorize_for_contract,
    build_flat_publish,
    encode_parquet,
    null_metrics_for,
    pa_schema_from_contract,
)
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry


@pytest.fixture(scope="module")
def contract():
    return load_registry().table("silver_mpoc_exports_by_country")


def _df(exports=(2.5e6, 1.8e6)):
    return pd.DataFrame({
        "year": [2023, 2023], "country": ["china", "india"],
        "exports_mt": list(exports), "source": ["mpoc", "mpoc"],
    })


class TestArrowSchema:
    def test_token_mapping(self):
        assert arrow_type_for("int64") == pa.int64()
        assert arrow_type_for("float64") == pa.float64()
        assert arrow_type_for("string") == pa.string()

    def test_unmapped_token_fails_closed(self):
        with pytest.raises(ValueError):
            arrow_type_for("decimal(10,2)")

    def test_schema_order_and_nullability(self, contract):
        sch = pa_schema_from_contract(contract)
        assert sch.names == ["year", "country", "exports_mt", "source"]
        assert sch.field("year").nullable is False        # natural-key column
        assert sch.field("exports_mt").nullable is True
        assert sch.field("exports_mt").type == pa.float64()


class TestEncode:
    def test_all_null_measure_is_double_not_null(self, contract):
        # the s3-lane null-type hazard: an all-null measure column must write as double.
        df = pd.DataFrame({"year": [2023], "country": ["china"], "exports_mt": [None],
                           "source": ["mpoc"]})
        t = pq.read_table(io.BytesIO(encode_parquet(df, contract)))
        assert t.schema.field("exports_mt").type == pa.float64()

    def test_shape_mismatch_fails_closed(self, contract):
        df = _df().drop(columns=["source"])
        with pytest.raises(ValueError):
            encode_parquet(df, contract)

    def test_extra_column_fails_closed(self, contract):
        df = _df().assign(bogus=1)
        with pytest.raises(ValueError):
            encode_parquet(df, contract)

    def test_null_metrics(self, contract):
        df = pd.DataFrame({"year": [1, 2], "country": ["a", "b"], "exports_mt": [1.0, None],
                           "source": ["x", "y"]})
        assert null_metrics_for(df, ["exports_mt"]) == {"exports_mt": 0.5}


class TestDryRunPublish:
    def test_stops_at_validated_nothing_written(self, contract):
        auth = authorize_for_contract(contract, publish_mode="dry-run")
        assert auth.mode is PublishMode.DRY_RUN and not auth.may_mutate_canonical
        plan = build_flat_publish(df=_df(), contract=contract,
                                  canonical_key="silver/mpoc_exports_by_country/part-000.parquet",
                                  auth=auth, s3_client=None, job="t")
        m = plan.run()
        assert m.state is ManifestState.VALIDATED
        assert m.outputs == []
        assert m.row_key_null_metrics["silver/mpoc_exports_by_country/part-000.parquet"]["exports_mt"] == 1.0

    def test_census_from_footer_matches(self, contract):
        body = encode_parquet(_df(exports=(2.5e6, None)), contract)
        md = pq.read_metadata(io.BytesIO(body))
        census = vc.census_column([vc.file_column_stat(md, "exports_mt")], "exports_mt")
        assert census.nonnull_fraction == 0.5 and not census.all_nan


class TestStandardCli:
    def test_publish_mode_default_dry_run(self):
        import argparse
        p = add_standard_producer_args(argparse.ArgumentParser())
        args = p.parse_args([])
        assert args.publish_mode == "dry-run"

    def test_shadow_and_canonical_choices(self):
        import argparse
        p = add_standard_producer_args(argparse.ArgumentParser())
        assert p.parse_args(["--publish-mode", "shadow"]).publish_mode == "shadow"
        with pytest.raises(SystemExit):
            p.parse_args(["--publish-mode", "bogus"])
