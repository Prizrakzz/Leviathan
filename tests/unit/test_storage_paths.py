"""Unit tests for leviathan.storage.paths."""
from __future__ import annotations

from leviathan.storage.paths import (
    bronze_production_key,
    bronze_weather_key,
    gold_feature_catalog_version_key,
    gold_feature_entity_map_version_key,
    gold_feature_group_map_version_key,
    gold_feature_matrix_version_key,
    gold_feature_spine_commodity_manifest_key,
    gold_feature_spine_manifest_key,
    gold_feature_spine_version_key,
    gold_training_windows_version_key,
    parse_hive_key,
    raw_cpc_tif_key,
    raw_production_key,
    raw_weather_key,
    silver_production_key,
    silver_weather_key,
)


class TestRawCpcTifKey:
    def test_contains_source_partition(self):
        key = raw_cpc_tif_key("w", "20240115", "w.20240115.tif")
        assert "source=cpc_soil" in key

    def test_contains_variable_partition(self):
        key = raw_cpc_tif_key("w", "20240115", "w.20240115.tif")
        assert "variable=w" in key

    def test_contains_date_partition(self):
        key = raw_cpc_tif_key("w", "20240115", "w.20240115.tif")
        assert "date=20240115" in key

    def test_starts_with_raw_weather(self):
        key = raw_cpc_tif_key("w", "20240115", "w.20240115.tif")
        assert key.startswith("raw/weather/")

    def test_filename_at_end(self):
        key = raw_cpc_tif_key("w", "20240115", "w.20240115.tif")
        assert key.endswith("w.20240115.tif")


class TestRawWeatherKey:
    def test_all_partitions_present(self):
        key = raw_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 3, "data.json")
        assert "source=nasa_power" in key
        assert "commodity=cocoa" in key
        assert "country=ghana" in key
        assert "region=gh_main" in key
        assert "year=2020" in key
        assert "month=03" in key

    def test_month_zero_padded_for_single_digit(self):
        key = raw_weather_key("chirps", "cocoa", "ghana", "gh_main", 2020, 1, "file.json")
        assert "month=01" in key

    def test_month_not_zero_padded_for_double_digit(self):
        key = raw_weather_key("chirps", "cocoa", "ghana", "gh_main", 2020, 12, "file.json")
        assert "month=12" in key

    def test_starts_with_raw_weather(self):
        key = raw_weather_key("chirps", "cocoa", "GH", "main", 2020, 6, "f.json")
        assert key.startswith("raw/weather/")

    def test_filename_at_end(self):
        key = raw_weather_key("chirps", "cocoa", "GH", "main", 2020, 6, "data.json")
        assert key.endswith("data.json")


class TestBronzeWeatherKey:
    def test_layer_is_bronze(self):
        key = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 1, "part.parquet")
        assert key.startswith("bronze/weather/")

    def test_all_partitions_match(self):
        key = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 12, "p.parquet")
        assert "source=nasa_power" in key
        assert "commodity=cocoa" in key
        assert "country=ghana" in key
        assert "region=gh_main" in key
        assert "year=2020" in key
        assert "month=12" in key

    def test_month_zero_padded(self):
        key = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2021, 5, "p.parquet")
        assert "month=05" in key


class TestSilverWeatherKey:
    def test_layer_is_silver(self):
        key = silver_weather_key("chirps", "cocoa", "ghana", "gh_main", 2020, 6, "part.parquet")
        assert key.startswith("silver/weather/")

    def test_differs_from_bronze_only_in_layer(self):
        bronze = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 3, "p.parquet")
        silver = silver_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 3, "p.parquet")
        assert bronze.replace("bronze/", "silver/") == silver


class TestParseHiveKey:
    def test_extracts_source(self):
        key = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 3, "p.parquet")
        assert parse_hive_key(key, "source") == "nasa_power"

    def test_extracts_commodity(self):
        key = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 3, "p.parquet")
        assert parse_hive_key(key, "commodity") == "cocoa"

    def test_extracts_year_as_string(self):
        key = bronze_weather_key("nasa_power", "cocoa", "ghana", "gh_main", 2020, 3, "p.parquet")
        assert parse_hive_key(key, "year") == "2020"

    def test_extracts_country(self):
        key = raw_weather_key("chirps", "corn_cbot", "brazil", "br_south", 2019, 7, "data.json")
        assert parse_hive_key(key, "country") == "brazil"

    def test_missing_field_returns_empty_string(self):
        key = "some/key/without/partitions/file.json"
        assert parse_hive_key(key, "nonexistent") == ""

    def test_round_trip_source_commodity_region(self):
        key = silver_weather_key("chirps", "cocoa", "ghana", "gh_main", 2021, 8, "out.parquet")
        assert parse_hive_key(key, "source") == "chirps"
        assert parse_hive_key(key, "commodity") == "cocoa"
        assert parse_hive_key(key, "region") == "gh_main"


class TestRawProductionKey:
    def test_contains_source_commodity_year(self):
        key = raw_production_key("faostat", "cocoa", 2020, "data.csv")
        assert "source=faostat" in key
        assert "commodity=cocoa" in key
        assert "year=2020" in key

    def test_starts_with_raw_production(self):
        key = raw_production_key("faostat", "cocoa", 2020, "data.csv")
        assert key.startswith("raw/production/")


class TestSilverProductionKey:
    def test_layer_is_silver(self):
        key = silver_production_key("cocoa", 2020, "part.parquet")
        assert key.startswith("silver/production/")

    def test_commodity_and_year_partitions(self):
        key = silver_production_key("cocoa", 2020, "part.parquet")
        assert "commodity=cocoa" in key
        assert "year=2020" in key


class TestBronzeProductionKey:
    def test_layer_is_bronze(self):
        key = bronze_production_key("faostat", "QCL", "cocoa", 2020, "part.parquet")
        assert key.startswith("bronze/production/")

    def test_contains_all_partitions(self):
        key = bronze_production_key("faostat", "QCL", "cocoa", 2020, "part.parquet")
        assert "source=faostat" in key
        assert "dataset=QCL" in key
        assert "commodity=cocoa" in key
        assert "year=2020" in key


class TestGoldVersionedPaths:
    def test_spine_version_key(self):
        key = gold_feature_spine_version_key("20260625T120000Z_abc123", "corn_cbot")
        assert key == (
            "gold/feature_spine_versions/"
            "dataset_version=20260625T120000Z_abc123/"
            "commodity=corn_cbot/"
            "part-000.parquet"
        )

    def test_matrix_version_key(self):
        key = gold_feature_matrix_version_key("v1", "soybeans_cbot")
        assert key == (
            "gold/feature_matrix_versions/"
            "dataset_version=v1/"
            "commodity=soybeans_cbot/"
            "part-0.parquet"
        )

    def test_catalog_version_key(self):
        assert gold_feature_catalog_version_key("v1") == (
            "gold/feature_catalog_versions/dataset_version=v1/feature_catalog.parquet"
        )

    def test_entity_map_version_key(self):
        assert gold_feature_entity_map_version_key("v1") == (
            "gold/feature_entity_map_versions/dataset_version=v1/feature_entity_map.parquet"
        )

    def test_group_map_version_key(self):
        assert gold_feature_group_map_version_key("v1") == (
            "gold/feature_group_map_versions/dataset_version=v1/feature_group_map.parquet"
        )

    def test_dataset_manifest_key(self):
        assert gold_feature_spine_manifest_key("v1") == (
            "gold/feature_spine_manifests/dataset_version=v1/manifest.json"
        )

    def test_commodity_manifest_key(self):
        assert gold_feature_spine_commodity_manifest_key("v1", "corn_cbot") == (
            "gold/feature_spine_commodity_manifests/"
            "dataset_version=v1/"
            "commodity=corn_cbot/"
            "run.json"
        )

    def test_training_windows_version_key(self):
        assert gold_training_windows_version_key("v1") == (
            "gold/training_windows_versions/dataset_version=v1/training_windows.parquet"
        )
