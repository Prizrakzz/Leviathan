"""E1 darkness census (Phase 7 P2.0 / W0.5) — hermetic, synthetic, zero-spend.

The census re-derives the P2 exit-gate denominator (dark id count, aliasable-via-fold ceiling, orphan
retire/keep list) as a pure function of the causal DAGs + driver_slices.yaml + on-disk slice counts.
These tests pin every branch on SYNTHETIC fixtures — a tmp causal dir + a tmp driver_slices.yaml + tmp
drivers/*.jsonl — never real DAG/slice content (that config is private IP). The evidence module caches
the alias map in three plain module globals (_DRIVER_CACHE/_DRIVER_ALIAS/_DRIVER_MATCHERS, NOT lru_cache)
and display.all_driver_ids() is lru_cached — both are reset in try/finally in every fixture so a synthetic
census never leaks into another test (mirrors the register-cache-poisoning discipline).
"""
from __future__ import annotations

from leviathan.graphrag import display as dp
from leviathan.graphrag import e1_census as ec
from leviathan.graphrag import evidence as ev


def _reset():
    """Clear the display lru_cache + the three evidence module globals the census reads through."""
    dp.all_driver_ids.cache_clear()
    ev._DRIVER_CACHE = None
    ev._DRIVER_ALIAS = None
    ev._DRIVER_MATCHERS = None


def _wire(monkeypatch, tmp_path, *, causal_yaml: str, driver_yaml: str):
    """Point display at a synthetic causal dir and evidence at a synthetic driver_slices.yaml + evidence
    dir, with all caches cleared. Returns the evidence dir (for writing drivers/<name>.jsonl slices)."""
    causal = tmp_path / "causal"
    causal.mkdir()
    (causal / "fixture.yaml").write_text(causal_yaml, encoding="utf-8")
    monkeypatch.setattr(dp, "_CFG", tmp_path)                 # display.all_driver_ids globs _CFG/causal/*.yaml
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text(driver_yaml, encoding="utf-8")
    evdir = tmp_path / "evidence"
    evdir.mkdir()
    monkeypatch.delenv("EVIDENCE_S3", raising=False)          # local mode: slices come from evdir/drivers/
    monkeypatch.setattr(ev, "_DRIVER_PATH", drv)
    monkeypatch.setattr(ev, "_EVID_DIR", evdir)
    _reset()
    return evdir


def _slice(evdir, name: str, n: int):
    """Write a drivers/<name>.jsonl with n synthetic records (only the count matters to the census)."""
    d = evdir / "drivers"
    d.mkdir(exist_ok=True)
    (d / f"{name}.jsonl").write_text("\n".join('{"text": "x"}' for _ in range(n)), encoding="utf-8")


# A single fixture that exercises every id-reason and every slice-kind at once:
#   drivers: exact_slice (identity), alias_target (aliased-to), orphan_corpus (props, no id)
#   dag_alias: alias_target <- aliased_id
#   causal ids: exact_slice (exact), aliased_id (alias), lonely_dark (unbacked), El_Nino (accented, dark;
#     folds to el_nino which is an exact slice -> fold_recoverable)
_CAUSAL = (
    "contract: test_contract\n"
    "drivers:\n"
    "- id: exact_slice\n"
    "- id: aliased_id\n"
    "- id: lonely_dark\n"
    "- id: "
    "El_Niño\n"                       # accented id, byte-disjoint from the ASCII 'el_nino' slice
)
_DRIVERS = (
    "drivers:\n"
    "  exact_slice: {category: hazard, terms: [frost]}\n"
    "  alias_target: {category: macro, terms: [rates]}\n"
    "  orphan_corpus: {category: macro, terms: [noise]}\n"
    "  el_nino: {category: teleconnection, terms: [enso]}\n"
    "dag_alias:\n"
    "  alias_target: [aliased_id]\n"
    "  el_nino: [El_Nino]\n"           # the ASCII case-mismatch alias (exists in prod); El_Nino IS backed
)


def test_id_census_reasons_and_fold(tmp_path, monkeypatch):
    _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    try:
        doc = ec.census()
        by = {r["id"]: r for r in doc["ids"]}
        # exact-name identity: backed, reason 'exact', routes to its own slice
        assert by["exact_slice"]["backed"] and by["exact_slice"]["reason"] == "exact"
        assert by["exact_slice"]["slice"] == "exact_slice"
        # curated dag_alias: backed, reason 'alias', routes to the alias target slice
        assert by["aliased_id"]["backed"] and by["aliased_id"]["reason"] == "alias"
        assert by["aliased_id"]["slice"] == "alias_target"
        # honestly dark: no identity, no alias -> unbacked, no slice
        assert not by["lonely_dark"]["backed"] and by["lonely_dark"]["reason"] == "unbacked"
        assert by["lonely_dark"]["slice"] is None
        # accented id: dark today (byte-exact miss) but folds onto the 'el_nino' exact slice -> recoverable
        acc = by["El_Niño"]
        assert not acc["backed"] and acc["reason"] == "unbacked" and acc["fold_recoverable"]

        it = doc["id_totals"]
        assert it["n_ids"] == 4 and it["n_backed"] == 2 and it["n_dark"] == 2
        assert it["by_reason"] == {"exact": 1, "alias": 1, "unbacked": 2}
        assert it["n_fold_recoverable"] == 1                  # only El_Nino; lonely_dark folds to itself
    finally:
        _reset()


def test_slice_census_consumed_and_orphans(tmp_path, monkeypatch):
    evdir = _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    try:
        # consumed slice: exact_slice has a routed id (itself) AND props on disk
        _slice(evdir, "exact_slice", 3)
        # alias_target: routed (aliased_id) AND props -> consumed
        _slice(evdir, "alias_target", 2)
        # orphan_corpus: props on disk but NO dag id routes here -> retire candidate
        _slice(evdir, "orphan_corpus", 5)
        # el_nino: no id routes here today (El_Nino is byte-dark pre-fold) and no file -> empty
        doc = ec.census()
        by = {r["slice"]: r for r in doc["slices"]}

        assert by["exact_slice"]["consumed"] and by["exact_slice"]["orphan_kind"] is None
        assert by["exact_slice"]["n_dag_ids"] == 1 and by["exact_slice"]["n_routed_props"] == 3
        assert by["alias_target"]["consumed"] and by["alias_target"]["n_routed_props"] == 2
        # retire orphan: has props, zero routed ids
        assert not by["orphan_corpus"]["consumed"] and by["orphan_corpus"]["orphan_kind"] == "retire"
        assert by["orphan_corpus"]["n_dag_ids"] == 0 and by["orphan_corpus"]["n_routed_props"] == 5
        # empty declared slice: no id, no props
        assert by["el_nino"]["orphan_kind"] == "empty"

        st = doc["slice_totals"]
        assert st["n_slices"] == 4 and st["n_consumed"] == 2 and st["n_orphan"] == 2
        assert st["orphan_by_kind"] == {"retire": 1, "empty": 1}
    finally:
        _reset()


def test_keep_orphan_is_routed_but_empty(tmp_path, monkeypatch):
    # A slice that DAG ids route to but has no props on disk is a 'keep' orphan (an E1b build target),
    # never a retire candidate — the census must not tell curation to drop a slice something needs.
    _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)   # no slice files written
    try:
        doc = ec.census()
        by = {r["slice"]: r for r in doc["slices"]}
        # alias_target is routed (aliased_id) but has zero props -> keep
        assert by["alias_target"]["n_dag_ids"] == 1 and by["alias_target"]["n_routed_props"] == 0
        assert not by["alias_target"]["consumed"] and by["alias_target"]["orphan_kind"] == "keep"
    finally:
        _reset()


def test_fold_helper():
    # NFKD + strip combining marks: accented forms collapse to ASCII; ASCII ids fold to themselves.
    assert ec.fold("El_Niño") == "El_Nino"
    assert ec.fold("La_Niña") == "La_Nina"
    assert ec.fold("frost") == "frost"


def test_write_emits_json_and_ascii_md(tmp_path, monkeypatch):
    evdir = _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    _slice(evdir, "orphan_corpus", 5)
    out = tmp_path / "eval"
    monkeypatch.setattr(ec, "_OUT", out)
    try:
        doc = ec.census()
        md_path = ec.write(doc, upload=False)                 # local-only: no S3 even if env were set
        assert md_path.exists() and (out / "e1_census.json").exists()
        md = md_path.read_text(encoding="utf-8")              # report FILE is UTF-8 (an accented id may appear)
        assert "E1 darkness census" in md and "retire candidates" in md
        import json
        loaded = json.loads((out / "e1_census.json").read_text(encoding="utf-8"))
        assert loaded["id_totals"]["n_dark"] == 2 and loaded["census"] == "E1_darkness"
    finally:
        _reset()


def test_summary_lines_are_ascii(tmp_path, monkeypatch):
    _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    try:
        for line in ec._summary_lines(ec.census()):
            line.encode("ascii")                              # cp1252 console safety on the stdout path
    finally:
        _reset()


def test_s3_mode_lists_drivers_prefix_once(tmp_path, monkeypatch):
    # In S3 mode the on-disk slice enumeration is ONE list_objects_v2 LIST of the drivers/ prefix — never
    # a per-slice existence probe (the July LIST-storm discipline). Assert exactly one paginate() call and
    # that only top-level drivers/<name>.jsonl keys are counted (a nested key is ignored).
    import types
    calls = {"paginate": 0}
    slice_store = {"drivers/orphan_corpus.jsonl": '{"text":"a"}\n{"text":"b"}',
                   "drivers/exact_slice.jsonl": '{"text":"c"}'}

    class _Pag:
        def paginate(self, Bucket, Prefix):
            calls["paginate"] += 1
            keys = ["drivers/orphan_corpus.jsonl", "drivers/exact_slice.jsonl",
                    "drivers/sub/nested.jsonl"]               # nested -> must be skipped by the '/' guard
            yield {"Contents": [{"Key": Prefix.rsplit("drivers/", 1)[0] + k} for k in keys]}

    class _S3:
        def get_paginator(self, _name):
            return _Pag()

        def get_object(self, *, Bucket, Key):
            rel = Key.split("graphrag/evidence/", 1)[-1]
            return {"Body": types.SimpleNamespace(read=lambda: slice_store[rel].encode())}

    causal = tmp_path / "causal"
    causal.mkdir()
    (causal / "fixture.yaml").write_text(_CAUSAL, encoding="utf-8")
    monkeypatch.setattr(dp, "_CFG", tmp_path)
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text(_DRIVERS, encoding="utf-8")
    monkeypatch.setattr(ev, "_DRIVER_PATH", drv)
    monkeypatch.setattr(ev, "_evid_s3", lambda: "s3://bkt/graphrag/evidence/")
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: _S3(), raising=False)
    _reset()
    try:
        doc = ec.census()
        by = {r["slice"]: r for r in doc["slices"]}
        # exactly one LIST for the whole slice enumeration
        assert calls["paginate"] == 1
        # nested key skipped; the two top-level slices counted by their S3 record counts
        assert "sub/nested" not in by and by["orphan_corpus"]["n_routed_props"] == 2
        assert by["exact_slice"]["n_routed_props"] == 1
    finally:
        _reset()
        ev._DRIVER_CACHE = None
        ev._DRIVER_ALIAS = None
        ev._DRIVER_MATCHERS = None
