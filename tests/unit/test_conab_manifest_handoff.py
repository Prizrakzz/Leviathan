"""Cross-container discover->fetch manifest handoff for the conab chain (Wave-3 RCA).

On AWS Batch the discover task and the fetch task run in DIFFERENT containers, so the
container-local ``data/conab/conab_bulletin_excels.json`` written by discover is invisible
to fetch. discover mirrors the manifest to S3 when LEVIATHAN_BUCKET is set; fetch falls
back to that mirror when the local path is absent. Local (env-less) runs keep the old
local-only behavior.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load(relpath: str, name: str):
    import sys

    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses + PEP 563 annotations require the module to be registered in
    # sys.modules during exec (dataclasses._is_type does sys.modules.get(__module__)).
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def test_s3_manifest_keys_match_between_discover_and_fetch():
    disc = _load("jobs/ingest/discover_conab_bulletin_xls.py", "conab_discover")
    fetch = _load("jobs/ingest/fetch_conab_bulletin_xls.py", "conab_fetch")
    assert disc.S3_MANIFEST_KEY == fetch._S3_MANIFEST_KEY
    # The mirror must live OUTSIDE bulletin_xls/ -- conab_xls_task lists that prefix with
    # no suffix filter and would try to parse the JSON as a bulletin.
    assert "bulletin_xls/" not in disc.S3_MANIFEST_KEY
    assert disc.S3_MANIFEST_KEY.startswith("raw/production/source=conab/")


def test_discover_mirrors_to_s3_when_bucket_env_set(monkeypatch, tmp_path):
    disc = _load("jobs/ingest/discover_conab_bulletin_xls.py", "conab_discover2")
    calls = []
    monkeypatch.setattr(disc, "_upload_manifest_s3",
                        lambda bucket, key, data: calls.append((bucket, key, data)))
    monkeypatch.setattr(disc, "discover_entries", lambda **kw: [])
    out = tmp_path / "manifest.json"
    import sys
    monkeypatch.setattr(sys, "argv",
                        ["discover", "--output", str(out), "--no-preserve-existing"])
    monkeypatch.setenv("LEVIATHAN_BUCKET", "test-bucket")
    disc.main()
    assert out.exists()
    assert calls and calls[0][0] == "test-bucket" and calls[0][1] == disc.S3_MANIFEST_KEY


def test_discover_local_only_without_bucket_env(monkeypatch, tmp_path):
    disc = _load("jobs/ingest/discover_conab_bulletin_xls.py", "conab_discover3")

    def _boom(*a, **k):
        raise AssertionError("no S3 upload without LEVIATHAN_BUCKET")

    monkeypatch.setattr(disc, "_upload_manifest_s3", _boom)
    monkeypatch.setattr(disc, "discover_entries", lambda **kw: [])
    out = tmp_path / "manifest.json"
    import sys
    monkeypatch.setattr(sys, "argv",
                        ["discover", "--output", str(out), "--no-preserve-existing"])
    monkeypatch.delenv("LEVIATHAN_BUCKET", raising=False)
    disc.main()
    assert out.exists()


def test_fetch_falls_back_to_s3_mirror(monkeypatch, tmp_path):
    fetch = _load("jobs/ingest/fetch_conab_bulletin_xls.py", "conab_fetch2")
    manifest = [{"safra_year": 2026, "survey_no": 2, "filename": "x.xls",
                 "xls_url": "https://example/x.xls", "discovered_at": "2026-07-17T00:00:00"}]
    payload = json.dumps(manifest).encode()
    # point the local path into tmp (absent) and stub the S3 seam
    monkeypatch.setattr(fetch, "_MANIFEST_PATH", tmp_path / "data" / "conab" / "m.json")
    monkeypatch.setattr(fetch, "_download_manifest_s3", lambda b, k: payload)
    monkeypatch.setenv("LEVIATHAN_BUCKET", "test-bucket")
    import sys
    monkeypatch.setattr(sys, "argv", ["fetch", "--dry-run"])
    fetch.main()  # dry-run prints candidates and returns; must NOT parser.error
    assert (tmp_path / "data" / "conab" / "m.json").exists()


def test_fetch_errors_clearly_when_no_local_and_no_mirror(monkeypatch, tmp_path):
    fetch = _load("jobs/ingest/fetch_conab_bulletin_xls.py", "conab_fetch3")
    monkeypatch.setattr(fetch, "_MANIFEST_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(fetch, "_download_manifest_s3", lambda b, k: None)
    monkeypatch.setenv("LEVIATHAN_BUCKET", "test-bucket")
    import sys
    import pytest
    monkeypatch.setattr(sys, "argv", ["fetch", "--dry-run"])
    with pytest.raises(SystemExit) as ei:
        fetch.main()
    assert ei.value.code == 2  # argparse parser.error
