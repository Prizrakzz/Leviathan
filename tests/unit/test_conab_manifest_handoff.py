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


# ── the safra off-by-one fence (2026-08-22) ─────────────────────────────────────────────────────
def test_two_row_merged_header_attributes_the_bulletins_own_safra():
    """THE DEFECT: CONAB sheets carry a merged two-row header (group row spanning three columns,
    then 'Safra Y-1 | Safra Y | VAR. %'); the single-row parse pinned the group label to the FIRST
    column of the span -- the PRIOR safra's FINAL number -- so 13/13 bulletins stored last year's
    value under this year's label, identical across all four surveys (the measured zero revision
    signal). This fence reproduces the real sheet shape (verified against the live 2026-05
    bulletin) and pins: the canonical element carries the bulletin's OWN safra, the prior lands
    under _prior_safra, VAR under _yoy_var_pct."""
    import pandas as pd
    from leviathan.transforms.raw_to_bronze import conab_xls as m
    rows = [
        [None] * 10,
        [None] * 10,
        [None] * 10,
        ["REGIÃO/UF", "ÁREA EM PRODUÇÃO (ha)", None, None, "PRODUTIVIDADE (sc/ha)", None, None,
         "PRODUÇÃO (mil sacas beneficiadas)", None, None],
        [None, "Safra 2025", "Safra 2026", "VAR. % ", "Safra 2025", "Safra 2026", "VAR. % ",
         "Safra 2025", "Safra 2026", "VAR. % "],
        [None, " (a)", "(b)", "(b/a)", " (c)", " (d)", "(d/c)", "(e)", " (f)", "(f/e)"],
        ["BRASIL", 100.0, 110.0, 10.0, 50.0, 55.0, 10.0, 35763.1, 45772.8, 27.99],
    ]
    out = m._parse_sheet(pd.DataFrame(rows), "2 Café Arábica", safra_year=2026, survey=2)
    nat = out[out["region"] == "BRASIL"].set_index("element")["value"]
    assert nat["production_thousand_bags"] == 45772.8              # the bulletin's OWN safra
    assert nat["production_thousand_bags_prior_safra"] == 35763.1  # last year's FINAL, labeled as such
    assert abs(nat["production_thousand_bags_yoy_var_pct"] - 27.99) < 1e-9
    assert nat["area_in_production_ha"] == 110.0
    assert nat["yield_bags_per_ha"] == 55.0


def test_single_row_header_sheets_still_parse_unchanged():
    import pandas as pd
    from leviathan.transforms.raw_to_bronze import conab_xls as m
    rows = [
        ["REGIÃO/UF", "ÁREA EM PRODUÇÃO (ha)", "PRODUÇÃO (mil sacas)"],
        ["BRASIL", 100.0, 39598.4],
        ["MG", 60.0, 25000.0],
    ]
    out = m._parse_sheet(pd.DataFrame(rows), "2 Café Arábica", safra_year=2025, survey=1)
    nat = out[out["region"] == "BRASIL"].set_index("element")["value"]
    assert nat["production_thousand_bags"] == 39598.4
    assert nat["area_in_production_ha"] == 100.0
