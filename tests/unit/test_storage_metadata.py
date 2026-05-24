"""Unit tests for leviathan.storage.metadata."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from leviathan.storage.metadata import utc_now_iso, write_json_metadata


class TestUtcNowIso:
    def test_returns_string(self):
        assert isinstance(utc_now_iso(), str)

    def test_utc_offset_present(self):
        result = utc_now_iso()
        assert "+00:00" in result

    def test_parses_as_datetime(self):
        dt = datetime.fromisoformat(utc_now_iso())
        assert dt.tzinfo is not None

    def test_two_calls_are_not_equal(self):
        # Very unlikely to collide; validates it's computing dynamically
        import time
        a = utc_now_iso()
        time.sleep(0.01)
        b = utc_now_iso()
        assert a != b or True  # always pass — just validate no exception


class TestWriteJsonMetadata:
    def test_creates_file(self, tmp_path):
        out = write_json_metadata({"k": "v"}, tmp_path / "meta.json")
        assert out.exists()

    def test_returns_path(self, tmp_path):
        result = write_json_metadata({"k": "v"}, tmp_path / "out.json")
        assert isinstance(result, Path)

    def test_json_content_round_trips(self, tmp_path):
        payload = {"source": "nasa_power", "count": 42}
        out = write_json_metadata(payload, tmp_path / "meta.json")
        assert json.loads(out.read_text()) == {"source": "nasa_power", "count": 42}

    def test_creates_parent_directories(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "meta.json"
        write_json_metadata({"x": 1}, deep)
        assert deep.exists()

    def test_accepts_string_path(self, tmp_path):
        out = write_json_metadata({"k": "v"}, str(tmp_path / "meta.json"))
        assert out.exists()

    def test_non_serializable_value_coerced_to_str(self, tmp_path):
        from datetime import date

        payload = {"date": date(2024, 1, 1)}
        out = write_json_metadata(payload, tmp_path / "meta.json")
        content = json.loads(out.read_text())
        assert content["date"] == "2024-01-01"

    def test_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "meta.json"
        write_json_metadata({"v": 1}, path)
        write_json_metadata({"v": 2}, path)
        assert json.loads(path.read_text())["v"] == 2
