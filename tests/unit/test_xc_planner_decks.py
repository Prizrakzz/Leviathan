"""D-XT (2026-08-29) -- THE TWO FROZEN PLANNER INSTRUMENTS (spec section b / pin group K).

`configs/graphrag/xc_planner_boundary_deck_v1.yaml` (24 negative rows) and
`configs/graphrag/xc_open_typo_deck_v1.yaml` (6 positive rows) are FROZEN instruments: authored once,
never edited, and a new class gets a v2 file rather than a row appended here. They are scored by
`scripts/xc_planner_soak.py` through `dispatch.plan_turn(..., xc_open=True)` -- a PAID, sampled
instrument -- so this file certifies only what can be certified for free: that they parse, that the
held-out half is frozen and hashes to the value recorded IN the file's own freeze header, that the
round-3 `held_by` attribution field is gone (N7 dissolved by DELETION, not by correction), and that
importing the runner costs nothing and calls no API at collection time.

The hash is recomputed through `scripts/xc_fence.heldout_hash` -- THE SHIPPED PRODUCER (round-4 P8:
one producer, never two). `scripts/` is not a package, so it is imported by file location, exactly as
`tests/unit/test_xc_fence_deck.py` does.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_CFG = _REPO / "configs" / "graphrag"
BOUNDARY = _CFG / "xc_planner_boundary_deck_v1.yaml"
TYPO = _CFG / "xc_open_typo_deck_v1.yaml"

# configs/graphrag/ is the PRIVATE config layer (gitignored; the repo is public) -- mirror the
# test_xc_fence_deck.py tolerance: a checkout without the private configs skips this module wholesale.
if not (BOUNDARY.exists() and TYPO.exists()):
    pytest.skip("gitignored D-XT planner decks absent (private configs layer)",
                allow_module_level=True)

# The frozen digests, recorded in each deck's own freeze header before any prompt iteration. They are
# what makes "the boundary held" a claim about a FIXED instrument rather than about a moving one.
BOUNDARY_HELDOUT_HASH = "a4d58ff6ca5dc378"
TYPO_HELDOUT_HASH = "c9bce4891f0a1ee6"


def _load_producer():
    """`scripts/xc_fence.py` by file location -- the scripts dir is not a package."""
    spec = importlib.util.spec_from_file_location("xc_fence_producer", _REPO / "scripts" / "xc_fence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


xcf = _load_producer()


def _deck(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


BOUNDARY_DECK, TYPO_DECK = _deck(BOUNDARY), _deck(TYPO)


# ── parse + composition ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("deck,n,path", [(BOUNDARY_DECK, 24, BOUNDARY), (TYPO_DECK, 6, TYPO)])
def test_deck_parses_with_the_declared_composition(deck, n, path):
    assert deck["version"] == 1
    assert deck["deterministic"] is False                    # a SAMPLED instrument, and it says so
    rows = deck["rows"]
    assert len(rows) == n, path.name
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids)                         # no duplicate row ids
    for r in rows:
        assert r["id"] and r["category"] and r["question"] and r["split"] in ("tune", "heldout")


def test_boundary_deck_is_all_negative_and_carries_its_audit_annotation():
    rows = BOUNDARY_DECK["rows"]
    assert {r["expect"] for r in rows} == {"nofire"}
    # `boundary_class` REPLACED the round-3 `held_by` field: an AUDIT annotation recorded at freeze
    # time, not part of the row hash and not a pass condition.
    assert {r["boundary_class"] for r in rows} == {"reported", "negated", "deprecated", "withdrawn",
                                                   "declarative"}
    assert {r["category"] for r in rows} <= {"neg_reported_speech", "neg_negated_ask",
                                             "neg_deprecated_ask", "neg_pattern_regression"}


def test_typo_deck_is_all_positive_open_asks():
    rows = TYPO_DECK["rows"]
    assert {r["expect"] for r in rows} == {"fire_open"}
    assert {r["category"] for r in rows} == {"typo_open_ask"}
    assert {r["split"] for r in rows} == {"heldout"}          # all six are frozen held-out


# ── the freeze discipline ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("deck,path", [(BOUNDARY_DECK, BOUNDARY), (TYPO_DECK, TYPO)])
def test_every_heldout_row_is_frozen(deck, path):
    """D13's frozen-split law: a held-out row that is not marked frozen can be edited after the fact,
    which is exactly what a held-out split exists to prevent."""
    held = [r for r in deck["rows"] if r["split"] == "heldout"]
    assert held, path.name
    for r in held:
        assert r.get("frozen") is True, f"{path.name}:{r['id']}"


@pytest.mark.parametrize("deck,want,path", [
    (BOUNDARY_DECK, BOUNDARY_HELDOUT_HASH, BOUNDARY),
    (TYPO_DECK, TYPO_HELDOUT_HASH, TYPO),
])
def test_heldout_hash_recomputes_through_the_shipped_producer(deck, want, path):
    """P8: ONE producer. If this reds, a frozen row's content moved -- which voids every measurement
    taken against that deck, so the file gets a v2, never a correction in place."""
    assert xcf.heldout_hash(deck) == want, path.name
    header = path.read_text(encoding="utf-8")
    assert f"heldout_hash: {want}" in header                 # the file's own freeze header agrees


def test_boundary_deck_heldout_half_is_twelve_of_twentyfour():
    held = [r for r in BOUNDARY_DECK["rows"] if r["split"] == "heldout"]
    assert len(held) == 12                                   # the ~50/50 split the hash covers


def test_no_held_by_key_survives_anywhere_in_the_boundary_deck():
    """N7 DISSOLVED BY DELETION, not by correction. `held_by` recorded which of three REGEX guards held
    a row; under directive 1 there are no regex guards left to attribute to, so the field is gone --
    and the attribution error goes with it, by construction."""
    for r in BOUNDARY_DECK["rows"]:
        assert "held_by" not in r, r["id"]
    for r in TYPO_DECK["rows"]:
        assert "held_by" not in r, r["id"]
    # ...and no `held_by:` FIELD survives anywhere in the file either -- not on a commented-out row, not
    # under a nested key yaml.safe_load would fold away. The freeze header's PROSE still names the field
    # (in backticks) to record WHY it is gone, which is the point of dissolving it by deletion.
    assert "held_by:" not in BOUNDARY.read_text(encoding="utf-8")
    assert "held_by:" not in TYPO.read_text(encoding="utf-8")


def test_provenance_rows_one_to_six_are_the_refuters_measured_attacks():
    """The first six boundary rows are the round-2 refuter's six MEASURED firing attacks, verbatim --
    the deck's own provenance line, pinned so a re-order cannot quietly retire them."""
    assert [r["id"] for r in BOUNDARY_DECK["rows"][:6]] == [
        "rep_floor_asking_which_other_markets", "neg_dont_want_which_other_markets",
        "dep_wrong_question_which_other_markets", "rep_pm_keeps_asking_balance_sheets",
        "rep_last_weeks_piece_spillover", "rep_colleague_asked_whatever_else"]


def test_typo_misspellings_sit_on_the_ask_never_on_a_commodity_name():
    """The instrument's whole premise: the misspellings are on the ASK-BEARING tokens, so a pass cannot
    be earned by recognising a cleanly-spelled commodity token."""
    tokens = ("markrets", "efected", "casade", "whitch", "spil", "complx", "reech", "anywere",
              "wat", "dose", "othr", "teh")
    for r in TYPO_DECK["rows"]:
        q = r["question"].lower()
        assert any(t in q for t in tokens), r["id"]


# ── the runner is import-clean and spends nothing at collection ──────────────────────────────────
def test_soak_runner_imports_clean_and_calls_no_api_at_collection(monkeypatch):
    """A deck runner that reached the API on import would spend money every time pytest collected this
    file. The import must be inert: no call, no graph load, no key read."""
    from leviathan.graphrag import answer as _an

    def _boom(*a, **kw):
        raise AssertionError("the soak runner called the API at import time")

    monkeypatch.setattr(_an, "_call_opus", _boom, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = importlib.util.spec_from_file_location("xc_planner_soak",
                                                  _REPO / "scripts" / "xc_planner_soak.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SEAT == "claude-sonnet-4-6" and mod.MAX_CONTRACTS == 6
    assert set(mod.CELLS) == {"g1-0", "g1-a", "g1-c", "g1-d", "g1-e", "g1-f", "g1-g"}


def test_soak_runner_scores_rows_without_an_api_call():
    """The scoring half is PURE -- it reads a recorded draw, never the network. Pinned so the bars can
    be re-audited offline from the written artifact."""
    spec = importlib.util.spec_from_file_location("xc_planner_soak_score",
                                                  _REPO / "scripts" / "xc_planner_soak.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # a boundary row PASSES iff xc_explicit is False on every draw
    assert mod.row_verdict("nofire", [{"xc_explicit": False}] * 3)["pass"] is True
    assert mod.row_verdict("nofire", [{"xc_explicit": False}, {"xc_explicit": True}])["pass"] is False
    # a typo row PASSES at >=2/3 draws with xc_explicit True AND an OPEN (null-or-collective) target
    open_hit = {"xc_explicit": True, "xc_target": None}
    named = {"xc_explicit": True, "xc_target": "soybean oil"}
    assert mod.row_verdict("fire_open", [open_hit, open_hit, named])["pass"] is True
    assert mod.row_verdict("fire_open", [open_hit, named, named])["pass"] is False
    collective = {"xc_explicit": True, "xc_target": "other oilseed complexes"}
    assert mod.row_verdict("fire_open", [collective] * 3)["pass"] is True
    assert mod.row_verdict("fire_open", [collective] * 3)["invented"] == 0
    assert mod.row_verdict("fire_open", [named] * 3)["invented"] == 3     # G1-b: an INVENTED target
