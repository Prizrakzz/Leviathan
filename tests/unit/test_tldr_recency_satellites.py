"""D-RC-12 (TL;DR/body directional coherence -- detection only) + D-RC-13 (recency honesty).

D-RC-12 is an OBSERVATIONAL stamp: a pre-model driver-sign basis (`_direction_basis`, deterministic,
structurally unable to see prose) reconciled post-verify against the FINAL tldr FIELD via the closed
direction lexicon. No strip, no rewrite -- the strip rate cannot move. The stated limit: the basis
reads the model's PRIOR, not the observed state; v1 makes the divergence class visible, the remedy is
a v2 decision from the measured rate.

D-RC-13: `record_through` (the record's edge) stamped observationally on both bodies; the
GROUNDING-LEDGER record-edge sentence and the _SYSTEM_RECENCY dating directive ship ONLY under
GRAPHRAG_RECENCY_STAMP (default off, byte-identical prompt otherwise).
"""
from __future__ import annotations

from types import SimpleNamespace

from leviathan.graphrag import answer as an


def _graph(signs_by_contract):
    contracts = {}
    for cid, signs in signs_by_contract.items():
        drivers = [SimpleNamespace(sign=s) for s in signs]
        contracts[cid] = SimpleNamespace(drivers=drivers)
    return SimpleNamespace(contracts=contracts)


# ══ D-RC-12: the deterministic basis ═════════════════════════════════════════════════════════════════
def test_direction_basis_counts_and_nets():
    g = _graph({"cocoa": ["+", "+", "-"]})
    assert an._direction_basis(g, ["cocoa"]) == {"n_plus": 2, "n_minus": 1, "net": "two_sided"}
    g2 = _graph({"corn_cbot": ["+", "+"]})
    assert an._direction_basis(g2, ["corn_cbot"])["net"] == "higher"
    g3 = _graph({"raw_sugar": ["-"]})
    assert an._direction_basis(g3, ["raw_sugar"])["net"] == "lower"
    assert an._direction_basis(_graph({}), ["missing"])["net"] == "none"
    assert an._direction_basis(_graph({}), None)["net"] == "none"


# ══ D-RC-12: the reconcile stamp ═════════════════════════════════════════════════════════════════════
def test_tldr_direction_flag_off_is_empty(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_TLDR_COHERENCE", raising=False)
    g = _graph({"c": ["+"]})
    assert an._tldr_direction_trace({"tldr": "points toward higher prices"}, g, ["c"]) == {}


def test_tldr_direction_hard_clash_disagrees(monkeypatch):
    """The Malaysia probe shape: an all-plus prior... inverted. A basis of `lower` under a tldr that
    says `points toward higher prices` is the one combination stamped agree=False."""
    monkeypatch.setenv("GRAPHRAG_TLDR_COHERENCE", "on")
    g = _graph({"palm": ["-", "-"]})
    out = an._tldr_direction_trace(
        {"tldr": "The setup points toward higher prices into Q1."}, g, ["palm"])
    assert out["tldr_direction"] == {"basis": "lower", "tldr": "higher", "agree": False}


def test_tldr_direction_compatible_cases_agree(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TLDR_COHERENCE", "on")
    g_two = _graph({"c": ["+", "-"]})
    assert an._tldr_direction_trace({"tldr": "points toward higher prices"}, g_two, ["c"]
                                    )["tldr_direction"]["agree"] is True     # two_sided basis: no clash
    g_hi = _graph({"c": ["+"]})
    assert an._tldr_direction_trace({"tldr": "price-supportive on balance"}, g_hi, ["c"]
                                    )["tldr_direction"]["agree"] is True     # aligned
    assert an._tldr_direction_trace({"tldr": "The picture is genuinely mixed."}, g_hi, ["c"]
                                    )["tldr_direction"]["tldr"] == "none"    # no lexicon hit: compatible
    both = an._tldr_direction_trace(
        {"tldr": "price-supportive for KC but points toward lower prices in Chicago"}, g_hi, ["c"])
    assert both["tldr_direction"]["tldr"] == "mixed" and both["tldr_direction"]["agree"] is True


def test_tldr_direction_outlook_mood_words_classify(monkeypatch):
    """The OUTLOOK register re-permits bullish/bearish (register.py sanitize carve-out) -- the
    lexicon must read them or the outlook lane under-detects."""
    monkeypatch.setenv("GRAPHRAG_TLDR_COHERENCE", "on")
    g = _graph({"c": ["+"]})
    out = an._tldr_direction_trace({"tldr": "Net bearish into the mid-crop."}, g, ["c"])
    assert out["tldr_direction"]["tldr"] == "lower" and out["tldr_direction"]["agree"] is False


# ══ D-RC-13: the record's edge ═══════════════════════════════════════════════════════════════════════
_EV = [{"date": "2022-04-12", "source": "usda_gain_wheat", "text": "a"},
       {"date": "2026-04-02", "source": "usda_gain_soybean_oil", "text": "b"},
       {"date": "1970-01-01", "source": "sentinel", "text": "c"}]


def test_record_through_is_max_usable_date():
    assert an._record_through(_EV) == "2026-04-02"
    assert an._record_through([{"date": "1970-01-01"}]) is None
    assert an._record_through([]) is None
    assert an._record_through(None) is None


def test_recency_suffix_flag_gated(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_RECENCY_STAMP", raising=False)
    assert an._recency_ledger_suffix("2026-04-02") == ""
    monkeypatch.setenv("GRAPHRAG_RECENCY_STAMP", "on")
    s = an._recency_ledger_suffix("2026-04-02")
    assert "runs through 2026-04-02" in s and "knowledge dates" in s and "as-of" in s
    assert an._recency_ledger_suffix(None) == ""                   # dateless turn: no sentence, no lie


def test_system_recency_addendum_flag_threaded(monkeypatch):
    """`recency` is threaded DOWN like outlook/episodes: default False is byte-identical, True appends
    the STATIC dating directive last (the per-turn date never enters the cached persona)."""
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    base = an._system(outlook=False, episodes=False)
    with_rec = an._system(outlook=False, episodes=False, recency=True)
    assert an._SYSTEM_RECENCY not in base
    assert with_rec == base + an._SYSTEM_RECENCY
    assert "{" not in an._SYSTEM_RECENCY                           # static: no interpolation slot
