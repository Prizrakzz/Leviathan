"""SILVER-F001 run_census -- the reconstructed R0 capture tool, pinned offline.

The tool's live halves (Glue/S3) are exercised by ``--check`` runs against stored records (two
green on 2026-08-26: silver_noaa_oni field-for-field with legacy hashes labeled; the
silver_psd_attributes v2 record round-trips hashes included). THIS suite is the AWS-free half:
the v2 hash recipe is verifiable offline against the stored records themselves -- which is the
entire point of recipe v2, and the defect the ghost tool had (its v1 hashes were searched for
exhaustively on 2026-08-26 -- hundreds of candidate serializations over every stored artifact,
the _raw captures and live source material -- and are NOT reproducible; they stay labeled legacy).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_TOOL = _REPO / "scripts" / "silver" / "run_census.py"
_TABLES = _REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "tables"
ZERO = "0" * 64


def _load_tool():
    spec = importlib.util.spec_from_file_location("run_census", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _records():
    if not _TABLES.exists():
        return {}
    out = {}
    for p in sorted(_TABLES.glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def test_the_cited_tool_exists_and_imports():
    """Three files cite run_census.census_one as the sanctioned re-capture mechanism
    (gen_registry_from_baseline.py:808,1549 / f011_ddl_diff_report.py:65 / this suite's sibling
    test_silver_registry_gen.py:35). Until 2026-08-26 the citation resolved to NOTHING in the repo
    -- the f091 no-git-ref class. This pin keeps the citation true."""
    mod = _load_tool()
    assert callable(mod.census_one)
    assert callable(mod.hash_block)
    assert mod.HASH_RECIPE_VERSION == 2


def test_recipe_v2_hashes_verify_offline_against_the_stored_record():
    """THE POINT OF RECIPE v2: every hash input is stored in the record, so any checkout verifies
    the hashes with no AWS call. Ground truth = every record stamped hash_recipe: 2."""
    mod = _load_tool()
    recs = _records()
    v2 = {n: d for n, d in recs.items() if d.get("glue", {}).get("hash_recipe") == 2}
    assert v2, "no recipe-v2 records found -- silver_psd_attributes was the first (2026-08-26)"
    for name, d in v2.items():
        g, ps = d["glue"], d["physical_sample"]
        assert mod.hash_block(g) == g["catalog_hash_sha256"], name
        assert mod.hash_block(ps) == ps["schema_fingerprint_sha256"], name
        assert g["catalog_hash_sha256"] != ZERO and ps["schema_fingerprint_sha256"] != ZERO


def test_recipe_v2_is_not_vacuous():
    """A recipe that ignores its inputs verifies anything. Mutate one column type -> the hash MUST
    move; strip the hash fields themselves -> the hash must NOT move (they are excluded from their
    own input, or the record could never round-trip)."""
    mod = _load_tool()
    recs = _records()
    name, d = next(iter(
        (n, r) for n, r in recs.items() if r.get("glue", {}).get("hash_recipe") == 2))
    g = json.loads(json.dumps(d["glue"]))
    baseline = mod.hash_block(g)
    g["nonpartition_columns"][0]["type"] = "MUTANT"
    assert mod.hash_block(g) != baseline, name
    g2 = {k: v for k, v in d["glue"].items() if k not in ("catalog_hash_sha256", "hash_recipe")}
    assert mod.hash_block(g2) == d["glue"]["catalog_hash_sha256"]


def test_legacy_records_keep_their_labeled_v1_hashes_untouched():
    """The ghost tool's hashes are unreproducible and therefore LABELED, never recomputed: a
    legacy record (no hash_recipe key) must keep non-zero 64-hex v1 hashes exactly as captured,
    and must NEVER carry a v2 stamp -- re-stamping without re-capturing would forge provenance.
    (Synthetic pre-publish records keep their explicit zeros until their first real capture.)"""
    recs = _records()
    legacy = {n: d for n, d in recs.items()
              if "hash_recipe" not in d.get("glue", {})
              and d.get("glue", {}).get("catalog_hash_sha256", ZERO) != ZERO}
    assert len(legacy) >= 40, "the 43 original captures should still be legacy-labeled"
    for name, d in legacy.items():
        ch = d["glue"]["catalog_hash_sha256"]
        sh = d["physical_sample"]["schema_fingerprint_sha256"]
        assert len(ch) == 64 and len(sh) == 64, name
        assert "hash_recipe" not in d["physical_sample"], name


def test_the_record_shape_matches_the_stored_population():
    """census_one's output keys must be the stored records' keys (modulo the v2 hash_recipe stamp
    and the optional 'refreshed' provenance key some records carry) -- a shape drift here is a
    record the baseline readers (gen_registry_from_baseline) silently misread."""
    recs = _records()
    v2 = next(d for d in recs.values() if d.get("glue", {}).get("hash_recipe") == 2)
    legacy = next(d for d in recs.values()
                  if "hash_recipe" not in d.get("glue", {})
                  and d.get("glue", {}).get("catalog_hash_sha256", ZERO) != ZERO)
    assert set(v2.keys()) == set(k for k in legacy.keys() if k != "refreshed")
    assert (set(v2["glue"].keys()) - {"hash_recipe"}
            == set(legacy["glue"].keys()) - {"catalog_hash_provenance_note"})
    assert set(v2["physical_sample"].keys()) - {"hash_recipe"} == set(legacy["physical_sample"].keys())


def test_every_legacy_record_verifies_under_the_recovered_v1_recipes():
    """THE RECOVERED GROUND TRUTH, held forever: the ghost tool's recipes were recovered verbatim
    from the estate's own session transcripts (2026-08-26; every Claude Code Write payload
    persists in JSONL -- the recovery lane for any lost gitignored file), and every legacy record
    must verify under them offline. The four documented post-mint mutations are named in the
    tool's own registries: two catalog values that are SILVER-F012 hashes mis-written into the
    F001 field (annotated in-record, never re-minted) and two arrow lists rewritten after minting
    (noaa_iod float->double; pink_sheet's F063 36->80 widening). verify_legacy() returning
    non-zero means a NEW unexplained mutation appeared -- investigate, never widen the
    registries to green it."""
    mod = _load_tool()
    if not _TABLES.exists():
        import pytest
        pytest.skip("readiness baseline tree absent from this checkout (gitignored)")
    assert mod.verify_legacy() == 0
