"""E4 sizing report (Phase 7 P3 / W0.3) -- hermetic, synthetic, zero-spend.

`e3_sizing` ranks doc FAMILIES by how many thin/empty driver slices each would fill, joining the E1
census `slices[]` with the coverage `drv` matrix. These tests pin every branch on SYNTHETIC fixtures --
an in-memory census dict + a stubbed node-source matrix -- and never touch S3, the real DAG/slice IP, or
an LLM. The two inputs are dependency-injected into `sizing()` directly, so no coverage/evidence import
or S3 client is exercised (main() -- the only S3/coverage caller -- is `# pragma: no cover` CLI glue).
"""
from __future__ import annotations

import json

from leviathan.graphrag import e3_sizing as e3


# A synthetic census that exercises every target/exclusion branch at the default thin=100:
#   keep_a  -- keep-orphan (3 ids, 0 props); cache routes props -> free_rebuild_win
#   keep_b  -- keep-orphan (1 id, 0 props); NO cache props -> needs new docs
#   thin_c  -- thin CONSUMED (2 ids, 40 props < 100) -> a target
#   at_100  -- exactly at the threshold (1 id, 100 props) -> NOT thin (< is strict) -> excluded
#   fat     -- well-populated (2 ids, 500 props) -> excluded
#   retire  -- props but NO id routes here (0 ids, 50 props) -> excluded (zero recall to fill)
#   empty   -- neither (0 ids, 0 props) -> excluded
def _census() -> dict:
    return {"report": "E1_darkness", "slices": [
        {"slice": "keep_a", "n_dag_ids": 3, "n_routed_props": 0, "consumed": False, "orphan_kind": "keep"},
        {"slice": "keep_b", "n_dag_ids": 1, "n_routed_props": 0, "consumed": False, "orphan_kind": "keep"},
        {"slice": "thin_c", "n_dag_ids": 2, "n_routed_props": 40, "consumed": True, "orphan_kind": None},
        {"slice": "at_100", "n_dag_ids": 1, "n_routed_props": 100, "consumed": True, "orphan_kind": None},
        {"slice": "fat", "n_dag_ids": 2, "n_routed_props": 500, "consumed": True, "orphan_kind": None},
        {"slice": "retire", "n_dag_ids": 0, "n_routed_props": 50, "consumed": False, "orphan_kind": "retire"},
        {"slice": "empty", "n_dag_ids": 0, "n_routed_props": 0, "consumed": False, "orphan_kind": "empty"},
    ]}


# Coverage drv matrix (cells are [prop_count, {doc_keys}], the coverage._cell shape):
#   wasde feeds keep_a (12) + thin_c (8) -> yield 2 over targets
#   esr   feeds keep_a (3)               -> yield 1
#   fx    feeds thin_c (2)               -> yield 1
#   reuters feeds retire (50) + fat (400) -> both EXCLUDED targets -> reuters must not appear
#   keep_b has no cells -> no family routes to it (needs genuinely new docs)
def _drv() -> dict:
    return {
        "keep_a": {"wasde": [12, {"d1", "d2"}], "esr": [3, {"d3"}]},
        "thin_c": {"wasde": [8, {"d1", "d4"}], "fx": [2, {"d5"}]},
        "at_100": {"wasde": [50, {"d1"}]},
        "fat": {"reuters": [400, {"d9"}]},
        "retire": {"reuters": [50, {"d8"}]},
    }


def test_is_thin_boundary_is_strict():
    # thinness flag at the threshold: props == thin is NOT thin (strict <); props == thin-1 IS thin.
    assert e3.is_thin({"n_routed_props": 99}, 100)
    assert not e3.is_thin({"n_routed_props": 100}, 100)
    assert not e3.is_thin({"n_routed_props": 101}, 100)
    assert e3.is_thin({"n_routed_props": 0}, 100)


def test_keep_orphans_identified_and_sorted():
    kos = e3.keep_orphans(_census()["slices"])
    # only n_dag_ids>=1 AND n_routed_props==0; sorted by n_dag_ids desc
    assert [k["slice"] for k in kos] == ["keep_a", "keep_b"]
    assert kos[0]["n_dag_ids"] == 3 and kos[1]["n_dag_ids"] == 1


def test_fillable_targets_excludes_retire_empty_and_at_threshold():
    tg = e3.fillable_targets(_census()["slices"], 100)
    names = [t["slice"] for t in tg]
    # keep-orphans + thin consumed only; at_100 (==thin), fat, retire (0 ids), empty (0 ids) excluded
    assert names == ["keep_a", "keep_b", "thin_c"]
    assert "at_100" not in names and "retire" not in names and "empty" not in names and "fat" not in names
    kinds = {t["slice"]: t["kind"] for t in tg}
    assert kinds == {"keep_a": "keep", "keep_b": "keep", "thin_c": "thin_consumed"}


def test_family_yield_ranking_is_correct():
    tg = e3.fillable_targets(_census()["slices"], 100)
    fams = e3.family_yield(tg, _drv())
    # wasde (yield 2) ranks first; esr and fx tie on yield 1 -> est_blocks desc breaks it (esr 3 > fx 2)
    assert [f["family"] for f in fams] == ["wasde", "esr", "fx"]
    w = fams[0]
    assert w["thin_slice_yield"] == 2 and sorted(w["slices"]) == ["keep_a", "thin_c"]
    assert w["est_blocks"] == 20 and w["n_docs"] == 3               # {d1,d2,d4} deduped by union
    assert w["est_cost_lo"] == 0.04 and w["est_cost_hi"] == 0.14    # 20 * 0.002 / 0.007
    # a family that only feeds EXCLUDED targets (reuters -> retire+fat) never appears
    assert "reuters" not in {f["family"] for f in fams}


def test_keep_orphan_free_rebuild_flag():
    doc = e3.sizing(_census(), _drv())
    ko = {k["slice"]: k for k in doc["keep_orphans"]}
    # keep_a: cache routes 15 props (wasde 12 + esr 3) -> a FREE rebuild win, families sorted by props desc
    assert ko["keep_a"]["cache_routable_props"] == 15 and ko["keep_a"]["free_rebuild_win"] is True
    assert ko["keep_a"]["families"][0]["family"] == "wasde"
    # keep_b: no cache props -> not a free rebuild, genuinely needs new docs
    assert ko["keep_b"]["cache_routable_props"] == 0 and ko["keep_b"]["free_rebuild_win"] is False


def test_sizing_totals():
    doc = e3.sizing(_census(), _drv())
    t = doc["totals"]
    assert t["n_fillable_targets"] == 3 and t["n_keep_orphans"] == 2 and t["n_thin_consumed"] == 1
    assert t["n_families_ranked"] == 3
    assert t["est_blocks_total"] == 25                              # wasde 20 + esr 3 + fx 2
    assert doc["thin_threshold"] == 100 and doc["report"] == "E3_sizing"


def test_thin_threshold_widens_target_set():
    # raising --thin pulls at_100 and fat into the target set (both have ids); retire/empty still excluded
    tg = e3.fillable_targets(_census()["slices"], 600)
    names = {t["slice"] for t in tg}
    assert {"keep_a", "keep_b", "thin_c", "at_100", "fat"} == names
    assert "retire" not in names and "empty" not in names


def test_write_emits_json_and_ascii_md(tmp_path, monkeypatch):
    out = tmp_path / "eval"
    monkeypatch.setattr(e3, "_OUT", out)
    doc = e3.sizing(_census(), _drv())
    md_path = e3.write(doc, upload=False)                           # local-only: no S3 even if env were set
    assert md_path.exists() and (out / "e3_sizing.json").exists()
    md = md_path.read_text(encoding="utf-8")
    md.encode("ascii")                                             # report body is ASCII-clean
    assert "E4 sizing report" in md and "Keep-orphans" in md and "thin-slice yield" in md
    loaded = json.loads((out / "e3_sizing.json").read_text(encoding="utf-8"))
    assert loaded["report"] == "E3_sizing" and loaded["totals"]["est_blocks_total"] == 25


def test_summary_lines_are_ascii():
    for line in e3._summary_lines(e3.sizing(_census(), _drv())):
        line.encode("ascii")                                       # cp1252 console safety on the stdout path


def test_missing_slice_in_matrix_is_safe():
    # a target with no drv entry (keep_b) must not crash yield or the keep-orphan detail
    tg = e3.fillable_targets(_census()["slices"], 100)
    fams = e3.family_yield(tg, {})                                 # empty matrix -> no families, no error
    assert fams == []
    doc = e3.sizing(_census(), {})
    assert doc["totals"]["n_families_ranked"] == 0
    assert all(k["cache_routable_props"] == 0 for k in doc["keep_orphans"])
