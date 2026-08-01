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
        # accented id: W1 wired accent-folding INTO driver_alias(), so El_Nino now RESOLVES (folds onto the
        # 'el_nino' slice) instead of merely being fold-recoverable -> backed, reason 'alias', not recoverable
        # anymore (nothing net-new left to fold; fold_recoverable is the pre-registration ceiling).
        acc = by["El_Niño"]
        assert acc["backed"] and acc["reason"] == "alias" and acc["slice"] == "el_nino"
        assert not acc["fold_recoverable"]

        it = doc["id_totals"]
        assert it["n_ids"] == 4 and it["n_backed"] == 3 and it["n_dark"] == 1
        assert it["by_reason"] == {"exact": 1, "alias": 2, "unbacked": 1}
        assert it["n_fold_recoverable"] == 0                  # El_Nino now resolves in driver_alias() -> 0 left
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
        # el_nino: post-W1 the accented El_Nino folds ONTO this slice, so a dag id now routes here — but no
        # file exists -> a 'keep' orphan (an E1b build target), no longer 'empty'
        doc = ec.census()
        by = {r["slice"]: r for r in doc["slices"]}

        assert by["exact_slice"]["consumed"] and by["exact_slice"]["orphan_kind"] is None
        assert by["exact_slice"]["n_dag_ids"] == 1 and by["exact_slice"]["n_routed_props"] == 3
        assert by["alias_target"]["consumed"] and by["alias_target"]["n_routed_props"] == 2
        # retire orphan: has props, zero routed ids
        assert not by["orphan_corpus"]["consumed"] and by["orphan_corpus"]["orphan_kind"] == "retire"
        assert by["orphan_corpus"]["n_dag_ids"] == 0 and by["orphan_corpus"]["n_routed_props"] == 5
        # routed-but-empty slice: the folded El_Nino routes here, no file -> keep (build), not empty
        assert by["el_nino"]["n_dag_ids"] == 1 and by["el_nino"]["orphan_kind"] == "keep"

        st = doc["slice_totals"]
        assert st["n_slices"] == 4 and st["n_consumed"] == 2 and st["n_orphan"] == 2
        assert st["orphan_by_kind"] == {"retire": 1, "keep": 1}
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
        # n_dark == 1 post-W1: only lonely_dark stays dark (El_Nino folds onto its slice in driver_alias())
        assert loaded["id_totals"]["n_dark"] == 1 and loaded["census"] == "E1_darkness"
    finally:
        _reset()


# ── era classifier / facet-thinness (pure, hermetic — no S3/disk) ─────────────────────────────────────
def test_era_of_boundary_years():
    # every inclusive boundary of the six buckets, driven off the 'date' key (event_date absent).
    cases = {
        1989: "pre1990", 1990: "1990s", 1999: "1990s",
        2000: "2000s", 2009: "2000s", 2010: "2010_17",
        2017: "2010_17", 2018: "2018_26", 2026: "2018_26",
        2027: "undated",                                      # a year > 2026 -> data-quality note, not an era
    }
    for year, era in cases.items():
        assert ec._era_of({"date": f"{year}-06-15"}) == era, year


def test_era_of_none_and_garbage_are_undated():
    assert ec._era_of({"date": None, "event_date": None}) == "undated"
    assert ec._era_of({"date": "not-a-year"}) == "undated"
    assert ec._era_of({}) == "undated"                        # neither key present


def test_era_of_event_date_overrides_date():
    # event_date (what the prop is ABOUT) wins over date (publication) when present.
    assert ec._era_of({"event_date": "1985-03-01", "date": "2020-01-01"}) == "pre1990"


def test_era_of_event_date_none_falls_back_to_date():
    assert ec._era_of({"event_date": None, "date": "2005-07-01"}) == "2000s"


def test_era_hist_has_all_six_keys_with_explicit_zeros():
    recs = [{"date": "2019-01-01"}, {"event_date": "2020-01-01"}, {"date": "bad"}]
    h = ec._era_hist(recs)
    assert h == {"pre1990": 0, "1990s": 0, "2000s": 0, "2010_17": 0, "2018_26": 2, "undated": 1}
    assert set(h) == set(ec._ERAS)                            # zero-count eras are still present


def test_thin_eras_empty_when_slice_below_thick_min():
    # a small slice (< THICK_MIN) that is hollow everywhere is NOT judged -> thin_eras == [].
    hollow = {e: 0 for e in ec._ERAS}
    assert ec._thin_eras(ec.THICK_MIN - 1, hollow) == []


def test_thin_eras_flags_only_sub_threshold_real_eras_in_order():
    # thick slice hollow in pre1990 (0) and 1990s (5, < THIN_MAX); other real eras healthy; undated large.
    hist = {"pre1990": 0, "1990s": 5, "2000s": 120, "2010_17": 200, "2018_26": 175, "undated": 90}
    assert ec._thin_eras(150, hist) == ["pre1990", "1990s"]   # chronological, undated excluded


def test_thin_eras_never_includes_undated():
    # undated below THIN_MAX must NOT flag; a thick slice with all REAL eras healthy has no thin eras.
    hist = {"pre1990": 50, "1990s": 50, "2000s": 50, "2010_17": 50, "2018_26": 50, "undated": 0}
    assert ec._thin_eras(250, hist) == []


def test_slice_totals_counts_thick_with_thin_eras():
    recs = [
        {"consumed": True, "orphan_kind": None, "thin_eras": ["pre1990"]},
        {"consumed": True, "orphan_kind": None, "thin_eras": ["1990s", "2000s"]},
        {"consumed": True, "orphan_kind": None, "thin_eras": []},          # thick but no gap
        {"consumed": False, "orphan_kind": "retire", "thin_eras": []},     # thin slice, not judged
    ]
    st = ec.slice_totals(recs)
    assert st["n_thick_with_thin_eras"] == 2
    assert st["n_slices"] == 4 and st["n_consumed"] == 3      # existing keys intact


def _slice_dated(evdir, name, era_counts):
    """Write drivers/<name>.jsonl with records carrying event_date years, so the census era histogram is
    exercised end-to-end. era_counts maps a representative year -> count."""
    import json as _json
    d = evdir / "drivers"
    d.mkdir(exist_ok=True)
    lines = []
    for year, n in era_counts.items():
        for _ in range(n):
            lines.append(_json.dumps({"event_date": f"{year}-06-01", "date": f"{year}-06-01", "text": "x"}))
    (d / f"{name}.jsonl").write_text("\n".join(lines), encoding="utf-8")


def test_slice_census_emits_era_hist_and_thin_eras_end_to_end(tmp_path, monkeypatch):
    evdir = _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    try:
        # exact_slice: THICK (120 props) but hollow pre-2000 -> thin_eras pre1990 + 1990s; zero-count 2000s.
        _slice_dated(evdir, "exact_slice", {2019: 100, 2015: 20})
        # orphan_corpus: thin slice (< THICK_MIN) -> era_hist present but thin_eras == [] (not judged).
        _slice_dated(evdir, "orphan_corpus", {2019: 10})
        doc = ec.census()
        by = {r["slice"]: r for r in doc["slices"]}

        assert by["exact_slice"]["n_routed_props"] == 120
        assert by["exact_slice"]["era_hist"] == {
            "pre1990": 0, "1990s": 0, "2000s": 0, "2010_17": 20, "2018_26": 100, "undated": 0}
        assert by["exact_slice"]["thin_eras"] == ["pre1990", "1990s", "2000s"]

        assert by["orphan_corpus"]["n_routed_props"] == 10
        assert by["orphan_corpus"]["thin_eras"] == []         # sub-threshold slice is never judged
        assert by["orphan_corpus"]["era_hist"]["2018_26"] == 10

        assert doc["slice_totals"]["n_thick_with_thin_eras"] == 1
    finally:
        _reset()


def test_facet_thinness_md_section_renders_ascii(tmp_path, monkeypatch):
    evdir = _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    out = tmp_path / "eval"
    monkeypatch.setattr(ec, "_OUT", out)
    try:
        _slice_dated(evdir, "exact_slice", {2019: 120})       # thick, hollow in every historical era
        doc = ec.census()
        md = ec._md(doc)
        header = "## Facet thinness (thick slices with historical-era gaps)"
        assert header in md
        start = md.index(header)
        end = md.index("## Work items", start)                # bound to just the facet section (next header)
        section = md[start:end]
        section.encode("ascii")                               # its literals are ASCII (cp1252-safe report path)
        assert "exact_slice" in section and "pre1990" in section
    finally:
        _reset()


def test_facet_thinness_md_none_when_no_thick_gap(tmp_path, monkeypatch):
    evdir = _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    try:
        _slice_dated(evdir, "orphan_corpus", {2019: 5})       # only a thin slice -> no thick gap
        md = ec._md(ec.census())
        assert "none (no thick slice has a sub-threshold real era)" in md
    finally:
        _reset()


def test_summary_lines_are_ascii(tmp_path, monkeypatch):
    _wire(monkeypatch, tmp_path, causal_yaml=_CAUSAL, driver_yaml=_DRIVERS)
    try:
        for line in ec._summary_lines(ec.census()):
            line.encode("ascii")                              # cp1252 console safety on the stdout path
    finally:
        _reset()


# ── W1.3 standing gate: archive-before-overwrite + --diff regression logic ────────────────────────────
def _census_doc(*, n_dark: int, by_reason: dict, n_consumed: int, orphan: dict, slices) -> dict:
    """A minimal but census()-shaped artifact for the diff/archive tests. `slices` is a list of tuples
    (name, consumed[, orphan_kind]); orphan_kind defaults to 'retire' for orphans so a plain (name, False)
    reads as dead corpus. Synthetic ids/props — the diff never inspects real DAG/slice content."""
    sl = []
    for t in slices:
        name, consumed = t[0], t[1]
        kind = t[2] if len(t) > 2 else (None if consumed else "retire")
        sl.append({"slice": name, "n_dag_ids": 1, "n_routed_props": 1 if consumed else 0,
                   "consumed": consumed, "orphan_kind": kind})
    n_orphan = sum(1 for s in sl if not s["consumed"])
    return {"census": "E1_darkness", "basis": "synthetic",
            "id_totals": {"n_ids": n_dark + 10, "n_backed": 10, "n_dark": n_dark,
                          "by_reason": by_reason, "n_fold_recoverable": 0},
            "slice_totals": {"n_slices": len(sl), "n_consumed": n_consumed, "n_orphan": n_orphan,
                             "orphan_by_kind": orphan},
            "ids": [], "slices": sl}


def test_write_archives_prior_json_before_overwrite(tmp_path, monkeypatch):
    # The FIXED-filename census clobbers its own e1_census.json on a rerun; W1.3 must copy the prior to a
    # timestamped BEFORE snapshot first (the P2 overwrite lesson). Assert the prior survives and the primary
    # json now holds the NEW doc.
    import json
    out = tmp_path / "eval"
    out.mkdir()
    monkeypatch.setattr(ec, "_OUT", out)
    monkeypatch.delenv("EVIDENCE_S3", raising=False)          # local-only; upload=False below regardless
    (out / "e1_census.json").write_text('{"census": "E1_darkness", "sentinel": "BEFORE"}', encoding="utf-8")
    ec.write(_census_doc(n_dark=1, by_reason={"unbacked": 1}, n_consumed=2, orphan={},
                         slices=[("a", True)]), upload=False)
    # the primary json now holds the NEW census
    assert json.loads((out / "e1_census.json").read_text(encoding="utf-8"))["id_totals"]["n_dark"] == 1
    # ...and exactly one timestamped archive preserves the prior BEFORE-copy byte-for-byte
    archives = sorted(out.glob("e1_census_*.json"))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text(encoding="utf-8"))["sentinel"] == "BEFORE"


def test_write_archive_false_is_overwrite_only(tmp_path, monkeypatch):
    # archive=False restores the exact pre-W1.3 overwrite-only path (no BEFORE-copy).
    out = tmp_path / "eval"
    out.mkdir()
    monkeypatch.setattr(ec, "_OUT", out)
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    (out / "e1_census.json").write_text('{"sentinel": "old"}', encoding="utf-8")
    ec.write(_census_doc(n_dark=0, by_reason={}, n_consumed=1, orphan={}, slices=[("a", True)]),
             upload=False, archive=False)
    assert not list(out.glob("e1_census_*.json"))


def test_write_first_run_makes_no_archive(tmp_path, monkeypatch):
    # No prior e1_census.json -> nothing to archive (the archive is opt-out-able but also a no-op on run #1).
    out = tmp_path / "eval"
    out.mkdir()
    monkeypatch.setattr(ec, "_OUT", out)
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    ec.write(_census_doc(n_dark=0, by_reason={}, n_consumed=1, orphan={}, slices=[("a", True)]), upload=False)
    assert not list(out.glob("e1_census_*.json")) and (out / "e1_census.json").exists()


def test_diff_census_computes_deltas():
    base = _census_doc(n_dark=5, by_reason={"unbacked": 5, "exact": 3, "alias": 2},
                       n_consumed=8, orphan={"retire": 2, "keep": 1}, slices=[("a", True), ("b", True)])
    cur = _census_doc(n_dark=3, by_reason={"unbacked": 3, "exact": 3, "alias": 4},
                      n_consumed=10, orphan={"retire": 2, "keep": 0}, slices=[("a", True), ("b", True)])
    d = ec.diff_census(base, cur)
    assert d["d_dark"] == -2 and d["d_consumed"] == 2 and d["d_retire"] == 0
    assert d["by_reason_delta"] == {"alias": 2, "exact": 0, "unbacked": -2}
    assert d["n_dark"] == {"baseline": 5, "current": 3}
    assert not d["regressed"] and d["consumed_to_orphan"] == []


def test_run_diff_exit_zero_when_improved_and_ascii():
    base = _census_doc(n_dark=5, by_reason={"unbacked": 5}, n_consumed=8, orphan={"retire": 2},
                       slices=[("a", True), ("b", True)])
    cur = _census_doc(n_dark=3, by_reason={"unbacked": 3}, n_consumed=10, orphan={"retire": 2},
                      slices=[("a", True), ("b", True)])
    code, lines = ec.run_diff(cur, base)                      # run_diff(current, baseline)
    assert code == 0
    for line in lines:
        line.encode("ascii")                                  # cp1252 console safety


def test_run_diff_fails_when_retire_grows():
    base = _census_doc(n_dark=3, by_reason={}, n_consumed=10, orphan={"retire": 1}, slices=[("a", True)])
    cur = _census_doc(n_dark=3, by_reason={}, n_consumed=10, orphan={"retire": 3}, slices=[("a", True)])
    code, lines = ec.run_diff(cur, base)
    assert code == 1 and ec.diff_census(base, cur)["d_retire"] == 2
    assert any("retire count grew" in ln for ln in lines)


def test_run_diff_fails_on_consumed_to_orphan_transition():
    # slice 'a' was consumed, is now a 'keep' orphan (routed-but-empty) -> a stranding regression EVEN THOUGH
    # retire didn't grow: the two fail signals are independent.
    base = _census_doc(n_dark=3, by_reason={}, n_consumed=2, orphan={"retire": 0},
                       slices=[("a", True), ("b", True)])
    cur = _census_doc(n_dark=3, by_reason={}, n_consumed=1, orphan={"retire": 0, "keep": 1},
                      slices=[("a", False, "keep"), ("b", True)])
    d = ec.diff_census(base, cur)
    assert d["consumed_to_orphan"] == ["a"] and d["regressed"] and d["d_retire"] == 0
    code, _ = ec.run_diff(cur, base)
    assert code == 1


def test_run_diff_vanished_slice_is_not_a_regression():
    # A consumed slice that DISAPPEARS from the current census is a curation act (rename/retire), not a silent
    # stranding -> the gate must not fire on it.
    base = _census_doc(n_dark=3, by_reason={}, n_consumed=2, orphan={"retire": 0},
                       slices=[("a", True), ("gone", True)])
    cur = _census_doc(n_dark=3, by_reason={}, n_consumed=1, orphan={"retire": 0}, slices=[("a", True)])
    d = ec.diff_census(base, cur)
    assert d["consumed_to_orphan"] == [] and not d["regressed"]


def test_load_baseline_prefers_explicit_then_newest_local_archive(tmp_path, monkeypatch):
    out = tmp_path / "eval"
    out.mkdir()
    monkeypatch.setattr(ec, "_OUT", out)
    monkeypatch.delenv("EVIDENCE_S3", raising=False)          # no S3 fallback in this test
    (out / "e1_census_20260101T000000Z.json").write_text('{"tag": "old"}', encoding="utf-8")
    (out / "e1_census_20260707T120000Z.json").write_text('{"tag": "new"}', encoding="utf-8")
    # default -> newest archive (lexical == chronological on the zero-padded stamp)
    doc, label = ec.load_baseline(None)
    assert doc["tag"] == "new" and label.endswith("20260707T120000Z.json")
    # explicit --baseline path wins over the newest archive
    doc2, _ = ec.load_baseline(str(out / "e1_census_20260101T000000Z.json"))
    assert doc2["tag"] == "old"
    # a missing explicit path -> (None, reason), not a crash
    d3, r3 = ec.load_baseline(str(out / "nope.json"))
    assert d3 is None and "not found" in r3


def test_load_baseline_none_when_no_archive_and_no_s3(tmp_path, monkeypatch):
    out = tmp_path / "eval"
    out.mkdir()
    monkeypatch.setattr(ec, "_OUT", out)
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    doc, reason = ec.load_baseline(None)
    assert doc is None and "no baseline" in reason


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


# ── G3b: the census gate was ARMED AND INERT on two independent counts ─────────────────────────────────
def _pop_doc(pairs) -> dict:
    """A census-shaped artifact where each slice carries an explicit n_routed_props."""
    sl = [{"slice": name, "n_dag_ids": 1, "n_routed_props": n, "consumed": n >= 1, "orphan_kind": None}
          for name, n in pairs]
    return {"census": "E1_darkness", "basis": "synthetic",
            "id_totals": {"n_ids": 10, "n_backed": 10, "n_dark": 0, "by_reason": {}, "n_fold_recoverable": 0},
            "slice_totals": {"n_slices": len(sl), "n_consumed": len(sl), "n_orphan": 0,
                             "orphan_by_kind": {}},
            "ids": [], "slices": sl}


def test_the_coffee_rust_wipe_now_fails_the_gate():
    """THE RECEIPT. The live 2026-07-09 census records `coffee_rust_crop n_routed_props=505, n_dag_ids=1,
    consumed=True`; the file on S3 today holds 20 props. Because `consumed = n_ids >= 1 and n_props >= 1`
    stays True whatever the count does, and the verdict failed ONLY on consumed->orphan or a grown retire
    count, the armed gate would have passed that 96% wipe silently -- and all 40 shrinking slices at the
    2026-07-20 promote with it."""
    base, cur = _pop_doc([("coffee_rust_crop", 505)]), _pop_doc([("coffee_rust_crop", 20)])
    d = ec.diff_census(base, cur)
    assert d["regressed"] is True
    assert d["population_drops"] == [{"slice": "coffee_rust_crop", "before": 505, "after": 20,
                                      "lost": 485, "frac": 0.9604}]
    assert d["consumed_to_orphan"] == [] and d["d_retire"] == 0     # neither old signal fires: that was the bug
    code, lines = ec.run_diff(cur, base)
    assert code == 1 and any("REGRESSION population coffee_rust_crop: 505 -> 20 props" in x for x in lines)


def test_population_trip_lines_need_both_a_fraction_and_a_magnitude():
    # 10 -> 9 is a 10% drop on a tiny slice: noise, not a regression (POP_DROP_MIN_ABS). -263 of 1,238 is
    # `metals` at the promote: -21%, over both lines.
    assert ec.population_drops(_pop_doc([("x", 10)]), _pop_doc([("x", 9)])) == []
    assert ec.population_drops(_pop_doc([("x", 1000)]), _pop_doc([("x", 960)])) == []      # -4%: under
    assert [d["slice"] for d in ec.population_drops(_pop_doc([("metals", 1238)]),
                                                    _pop_doc([("metals", 975)]))] == ["metals"]
    # growth never trips, and a VANISHED slice is a curation act (the same doctrine consumed_to_orphan uses)
    assert ec.population_drops(_pop_doc([("x", 100)]), _pop_doc([("x", 400)])) == []
    assert ec.population_drops(_pop_doc([("x", 100)]), _pop_doc([("y", 100)])) == []


def test_an_explicit_baseline_that_vanishes_is_a_hard_failure_not_a_skip(tmp_path, monkeypatch):
    """G3b(2): `configs/graphrag/eval/` is in .dockerignore so there is no local archive in-image, and a
    shadow rebuild's <EVIDENCE_S3>/eval/ prefix does not exist -- both fallbacks return None and the gate
    prints "skipping the gate" and exits 0. Arming it on the shadow flow was a guaranteed silent pass."""
    monkeypatch.setattr(ec, "_OUT", tmp_path / "empty")
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    doc, label, hard = ec.resolve_baseline(str(tmp_path / "nope.json"))
    assert doc is None and hard is True and "not found" in label
    # a genuine first run (nothing NAMED, nothing found) stays a soft skip
    doc, label, hard = ec.resolve_baseline(None)
    assert doc is None and hard is False and "no baseline" in label
    # the 2-tuple wrapper is preserved for existing callers
    assert ec.load_baseline(None) == (None, label)


def test_explicit_baseline_reads_a_local_path(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(ec, "_OUT", tmp_path / "empty")
    p = tmp_path / "base.json"
    p.write_text(json.dumps(_pop_doc([("x", 5)])), encoding="utf-8")
    doc, label, hard = ec.resolve_baseline(str(p))
    assert hard is False and doc["slices"][0]["slice"] == "x" and label == str(p)


# ── G8 item 1 (F13): the TERM census -- dead terms + the cross-claim matrix ────────────────────────────
def _seed_chunk(tmp_path, name, texts):
    import hashlib
    import json
    d = tmp_path / "chunks"
    d.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(name.encode()).hexdigest()
    (d / f"{h}.jsonl").write_text("\n".join(json.dumps(
        {"id": f"{h}#{i}", "date": "2024-01-01", "source": "WB", "source_key": name, "text": t,
         "event_date": None}) for i, t in enumerate(texts)), encoding="utf-8")


def test_term_census_names_dead_terms_and_builds_the_cross_claim_matrix(tmp_path, monkeypatch):
    """G8 asked for TWO artifact-free items; only item 2 (the static config-vs-config collision lint) landed.
    Item 1 -- run it at full corpus, write the cross-claim matrix and the dead-term list beside the E1 census
    -- had no code and no committed harness, so "310 of 638 dead terms" and "1,319 multiply-claimed props"
    stayed a 20%-sample screening result with no standing baseline. The static lint by construction cannot
    produce either number: it compares terms to terms and never reads a prop."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "_driver_raw", lambda: {"drivers": {
        "freight": {"category": "logistics", "terms": ["freight", "unobtainium shipping"]},
        "rust": {"category": "disease", "terms": ["leaf rust"]},
        "coffee_rust": {"category": "disease", "terms": ["coffee leaf rust"]}}})
    _reset()
    try:
        _seed_chunk(tmp_path, "doc-a", ["Pacific freight rates doubled",
                                        "Coffee leaf rust spread across Minas Gerais",
                                        "an unrelated macro note"])
        doc = ec.term_census()
        assert doc["scope"]["n_props"] == 3 and doc["scope"]["n_terms"] == 4
        # the dead term is in the vocabulary, in the manifest digest, and claims NOTHING
        assert doc["dead_terms"] == [{"slice": "freight", "term": "unobtainium shipping"}]
        # "leaf rust" is a word-boundary substring of "coffee leaf rust", so ONE prop is claimed by BOTH --
        # the exact shape term_collision_warnings predicts statically, measured here against real props.
        assert doc["n_multi_claimed_props"] == 1
        assert doc["cross_claim_matrix"] == {"coffee_rust|rust": 1}
        assert doc["per_slice"]["freight"] == {"n_props_claimed": 1, "n_props_sole": 1}
        assert doc["per_slice"]["rust"] == {"n_props_claimed": 1, "n_props_sole": 0}
        # it is READ-ONLY over chunks/: no slice appears, nothing is embedded, nothing is written until asked
        assert not (tmp_path / "drivers").exists() and list(tmp_path.glob("*.jsonl")) == []
        out = ec.write_term_census(doc, upload=False)
        assert out.name.startswith("term_census_") and out.exists()
        assert any("dead terms (claim 0 props): 1 of 4" in ln for ln in ec._term_census_lines(doc))
    finally:
        _reset()
