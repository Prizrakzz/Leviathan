"""SILVER-F047: deproject + within-year compaction of the weather trio.

Proves: the compacted key preserves the ``year=`` path segment the feature extractor depends on
(Attack 3 finding #3); the coarse registered grain is [commodity, year] (~1,400 partitions/table, not
~590k month-grain catalog entries); compaction merges the 12 monthly frames into one deduplicated
object per (commodity, year); and the coarse layout still passes the extractor's year-bounded probe.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver import weather_compaction as wc


def _month_frame(month, region="r1", value=1.0):
    return pd.DataFrame({
        "date": [f"2020-{month:02d}-01"], "year": [2020], "month": [month], "day": [1],
        "country": ["brazil"], "region": [region], "commodity": ["corn_cbot"],
        "source": ["chirps"], "ingest_date": ["2026-06-16"],
        "variable": ["precipitation_mm"], "value": [value],
    })


class TestYearSegmentPreserved:
    def test_compacted_key_has_year_segment(self):
        key = wc.compacted_silver_key("chirps", "corn_cbot", 2020)
        assert "/year=2020/" in key
        assert wc.assert_year_segment_preserved(key) == 2020

    def test_key_drops_country_region_month_from_path(self):
        key = wc.compacted_silver_key("chirps", "corn_cbot", 2020)
        assert "country=" not in key and "region=" not in key and "month=" not in key

    def test_missing_year_segment_raises(self):
        with pytest.raises(ValueError, match="year="):
            wc.assert_year_segment_preserved("silver/weather/source=chirps/commodity=corn_cbot/part.parquet")

    def test_extractor_year_regex_matches_compacted_key(self):
        from leviathan.features.extractors import _year_from_path
        key = wc.compacted_silver_key("nasa_power", "corn_cbot", 1999)
        assert _year_from_path(key) == 1999


class TestCoarseGrain:
    def test_partition_keys_are_commodity_year(self):
        assert wc.COMPACTED_PARTITION_KEYS == ["commodity", "year"]

    def test_plan_partition_values(self):
        units = wc.compaction_plan("chirps", "silver_chirps", "corn_cbot", {2019: ["k1"], 2020: ["k2", "k3"]})
        assert [u.partition_values for u in units] == [["corn_cbot", "2019"], ["corn_cbot", "2020"]]
        assert units[1].source_month_objects == 2

    def test_plan_collapses_many_months_into_one_unit_per_year(self):
        by_year = {2020: [f"m{m}" for m in range(1, 13)]}  # 12 monthly objects
        units = wc.compaction_plan("chirps", "silver_chirps", "corn_cbot", by_year)
        assert len(units) == 1
        assert units[0].source_month_objects == 12  # 12 -> 1 object (the file collapse)


class TestCompactPartition:
    def test_merges_months_and_pins_schema_columns(self):
        frames = [_month_frame(m, value=float(m)) for m in range(1, 13)]
        out = wc.compact_partition(frames, "silver_chirps")
        # 12 months merged; one row per month (distinct dates).
        assert len(out) == 12
        # columns exactly the pinned LONG schema (commodity carried in-file for chirps).
        from leviathan.transforms.bronze_to_silver._weather_schema import CHIRPS_LONG_SCHEMA
        assert list(out.columns) == [f.name for f in CHIRPS_LONG_SCHEMA]

    def test_dedup_on_natural_key(self):
        dup = pd.concat([_month_frame(1, value=1.0), _month_frame(1, value=1.0)], ignore_index=True)
        out = wc.compact_partition([dup], "silver_chirps")
        assert len(out) == 1

    def test_empty_frames_raise(self):
        with pytest.raises(ValueError, match="no non-empty"):
            wc.compact_partition([pd.DataFrame(), None], "silver_chirps")

    def test_compacted_bytes_is_parquet(self):
        frames = [_month_frame(m) for m in range(1, 4)]
        out = wc.compact_partition(frames, "silver_chirps")
        body = wc.compacted_bytes(out, "silver_chirps")
        assert body[:4] == b"PAR1"


class TestExtractorProbeOnCompactedLayout:
    def test_year_bounded_probe_finds_compacted_objects(self, tmp_path):
        """The coarse commodity/year layout still returns non-empty year-bounded paths (the extractor
        probe's structural dependency)."""
        from leviathan.features.extractors import _paths_with_year_partitions
        import pyarrow.parquet as pq
        from leviathan.transforms.bronze_to_silver._weather_schema import CHIRPS_LONG_SCHEMA, enforce_arrow_schema
        # Write a compacted object at commodity/year grain on the local FS.
        out = wc.compact_partition([_month_frame(m) for m in range(1, 13)], "silver_chirps")
        d = tmp_path / "commodity=corn_cbot" / "year=2020"
        d.mkdir(parents=True)
        pq.write_table(enforce_arrow_schema(out, CHIRPS_LONG_SCHEMA), str(d / "part-000.parquet"))
        paths = _paths_with_year_partitions(str(tmp_path), 2019, 2021)
        assert len(paths) == 1
        assert "year=2020" in paths[0]
