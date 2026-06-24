"""Tests for deterministic registry-driven Athena DDLs."""
from __future__ import annotations

from pathlib import Path

from leviathan.catalog.ddl import render_registry_ddls
from leviathan.catalog.registry import load_dataset_registry


def test_all_checked_in_ddls_match_registry() -> None:
    registry = load_dataset_registry()
    rendered = render_registry_ddls(registry)
    ddl_dir = Path(__file__).resolve().parents[2] / "sql" / "athena" / "ddl"
    checked_in = {
        path.stem: path.read_text(encoding="utf-8")
        for path in ddl_dir.glob("*.sql")
    }
    assert checked_in == rendered


def test_production_ddl_cannot_scan_esr_or_conab_prefixes() -> None:
    ddl = render_registry_ddls(load_dataset_registry())["silver_production"]
    assert "commodity=${commodity}/year=${year}" in ddl
    assert "source=${source}" not in ddl
    assert "source=usda_esr" not in ddl
    assert "source=conab" not in ddl


def test_inventory_ddl_uses_symlink_parquet_input() -> None:
    ddl = render_registry_ddls(load_dataset_registry())["metadata_s3_inventory"]
    assert "ParquetHiveSerDe" in ddl
    assert "SymlinkTextInputFormat" in ddl
    assert "PARTITIONED BY (`dt` STRING)" in ddl
    assert "/leviathan-dev-weekly/hive/" in ddl


def test_fnc_tables_are_split_by_grain() -> None:
    tables = render_registry_ddls(load_dataset_registry())
    assert "silver_fnc_colombia" not in tables
    assert "production_bags_60kg" in tables["silver_fnc_colombia_monthly"]
    assert "area_ha" in tables["silver_fnc_colombia_area_department"]
    assert "coffee_type" in tables["silver_fnc_colombia_exports_port_type"]
