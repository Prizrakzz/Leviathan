"""09-24 FIX ROUND 2, LANE C -- THE ONE EVIDENCE LEDGER (CONTRACT K1; THREAT_MODEL C-1..C-4, B15).

THE MEASURED DEFECT (items 1 and 20). The board minted its own [E] numbers from `e_start = len(uniq) + 1`
while `cit.unify` numbered and `verify_citations` resolved against `uniq` alone, so an [E] the block printed
past the menu pointed at nothing the verifier held: deep 2026 served ZERO [E] rows (three receipts pruned),
the tariff turn's regime receipt [E46] was struck `fabricated_citation`, and one document named twice got two
addresses. `citations.EvidenceLedger` is now the ONE issuer: the menu is copied, every document the block
names is ADDRESSED (a held document keeps its address; a new one is appended), and `evidence()` is the one
positional list every consumer reads. Pinned here:

  * construction COPIES `uniq` (the caller's list never grows) and, with nothing registered, `evidence()` is
    `uniq` element for element -- the same objects -- so `unify` and every consumer are byte-identical (C-3);
  * `address` -- held -> its k; new -> appended at k = len; a differing TEXT under a held key -> a chunk under
    the same k; no source_key -> None and counted (C-4);
  * `unify(ledger.evidence())[k-1]` IS the document that minted k, for every address issued (C-2);
  * a board receipt that is a DIFFERENT CHUNK of a menu document keeps the menu's address and its text is
    remembered as a chunk of that address (C-1: the verifier's support pool for [Ek] is `chunks()[k]`);
  * `ledger_row` copies, never invents; `stamp()` counts.
"""
from __future__ import annotations

import copy

import pytest

from leviathan.graphrag import citations as cit


def _menu(n: int = 3) -> list:
    return [{"source": f"usda_gain_{i}", "source_key": f"text/doc{i}.json", "date": f"2025-0{i}-01",
             "text": f"menu chunk of document {i}", "contract": "soybeans_cbot", "tier": 2}
            for i in range(1, n + 1)]


def test_construction_copies_and_an_unused_ledger_IS_uniq():
    uniq = _menu()
    before = copy.deepcopy(uniq)
    led = cit.EvidenceLedger(uniq)
    ev = led.evidence()
    assert ev == uniq and all(a is b for a, b in zip(ev, uniq)), "the same objects, element for element"
    assert ev is not uniq and led.menu_n == 3
    led.address({"source": "x", "source_key": "text/new.json", "text": "t"})
    assert len(uniq) == 3 and uniq == before, "registering never grows or mutates the caller's list"
    assert led.stamp() == {"menu_n": 3, "registered": 1, "extra_chunks": 0, "unaddressed": 0}


def test_unify_over_an_unused_ledger_is_byte_identical_to_unify_over_uniq():
    uniq = _menu(5)
    a = [c.model_dump() for c in cit.unify(uniq)]
    b = [c.model_dump() for c in cit.unify(cit.EvidenceLedger(uniq).evidence())]
    assert a == b


def test_address_held_new_chunk_and_none():
    led = cit.EvidenceLedger(_menu())
    # HELD: the menu's own document, same text -> its address, nothing registered
    assert led.address({"source_key": "text/doc2.json", "text": "menu chunk of document 2"}) == 2
    assert led.stamp()["extra_chunks"] == 0
    # HELD, whitespace re-wrapped -> the same text, not a chunk
    assert led.address({"source_key": "text/doc2.json", "text": " menu  chunk of\ndocument 2 "}) == 2
    assert led.stamp()["extra_chunks"] == 0
    # HELD, a DIFFERENT chunk of the same document -> the SAME address, remembered once
    other = {"source": "usda_gain_2", "source_key": "text/doc2.json", "date": "2025-02-01",
             "text": "the board's chunk: the tariff took effect 10 March 2025", "event_date": "2025-03-10",
             "event_date_precision": "day"}
    assert led.address(other) == 2 and led.address(dict(other)) == 2
    assert led.stamp()["extra_chunks"] == 1
    # NEW: appended; its address is its position; asking again returns the same address
    new = {"source": "usda_gain_soybeans", "source_key": "text/tariff.json", "date": "2025-03-19",
           "text": "China announced additional tariffs", "tier": 1}
    assert led.address(new) == 4 and led.address(new) == 4
    # NO SOURCE KEY: no durable identity, no address, counted
    assert led.address({"source": "GAIN", "date": "2025-03-19", "text": "t"}) is None
    assert led.address({"source_key": "", "text": "t"}) is None
    assert led.stamp() == {"menu_n": 3, "registered": 1, "extra_chunks": 1, "unaddressed": 2}
    ch = led.chunks()
    assert list(ch) == [2]
    assert ch[2][0] is led.evidence()[1], "the address's own row first"
    assert ch[2][1]["text"].startswith("the board's chunk"), "then the chunk the block showed"


def test_the_ledgers_numbering_IS_unifys_numbering():
    """C-2: for every address issued, `unify(evidence())[k-1]` names the source_key that minted k -- the k
    the block printed, the k the verifier resolves and the k the footer prints are one number."""
    led = cit.EvidenceLedger(_menu(4))
    minted = {}
    recs = [{"source_key": "text/doc3.json", "text": "menu chunk of document 3"},
            {"source_key": "text/r1.json", "source": "mpoc", "date": "2023-03-28", "text": "a"},
            {"source_key": "text/doc1.json", "text": "another chunk of doc 1"},
            {"source_key": "text/r2.json", "source": "usda_gain_cocoa", "date": "2025-08-22", "text": "b"},
            {"source_key": "text/r1.json", "text": "a second chunk of r1"},
            {"source_key": "text/r3.json", "source": "usda_gain_soybeans", "date": "2025-03-19", "text": "c"}]
    for r in recs:
        minted[led.address(r)] = r["source_key"]
    cits = cit.unify(led.evidence())
    for k, sk in minted.items():
        assert cits[k - 1].id == f"E{k}"
        assert cits[k - 1].payload["source_key"] == sk
    assert sorted(minted) == [1, 3, 5, 6, 7]


def test_one_document_one_address_wherever_it_is_named():
    """The event row, the chain document row, the chain receipt and the analog receipt may all name ONE
    document: they all get ONE address (the round-1 `take_e` minted one per row)."""
    led = cit.EvidenceLedger([])
    r = {"source_key": "text/regime.json", "source": "usda_gain_soybeans", "date": "2025-03-19", "text": "x"}
    ks = {led.address(dict(r)) for _ in range(4)}
    assert ks == {1} and len(led.evidence()) == 1


def test_an_object_shaped_receipt_with_no_source_key_gets_no_address():
    """C-4: `walk.event_receipt_for` converts an object receipt into {date, source, text, tier, event_date}
    -- no source_key. It gets no address (the caller prints no [E] and counts it) and adds no unify row."""
    led = cit.EvidenceLedger(_menu(2))
    converted = {"date": "2025-03-19", "source": "GAIN", "text": "t", "tier": 3, "event_date": "2025-02-01"}
    assert led.address(converted) is None
    assert len(cit.unify(led.evidence())) == 2
    assert led.stamp()["unaddressed"] == 1

    class _Obj:                                         # an attribute-shaped record WITH a key is addressable
        source_key = "text/obj.json"
        source = "GAIN"
        date = "2024-01-01"
        text = "obj text"
    assert led.address(_Obj()) == 3
    assert led.evidence()[2] == {"source_key": "text/obj.json", "source": "GAIN", "date": "2024-01-01",
                                 "text": "obj text"}


def test_ledger_row_copies_never_invents():
    rec = {"source": "mpoc", "source_key": "k", "date": "2023-03-28", "text": "If the blend rate ...",
           "event_date": "2023-04-01", "event_date_precision": "month", "char_start": 3, "char_end": 9,
           "offset_kind": "exact", "tier": 2, "contract": "x", "score": 0.4}
    row = cit.ledger_row(rec)
    assert row == {k: rec[k] for k in ("source", "source_key", "date", "text", "event_date",
                                       "event_date_precision", "char_start", "char_end", "offset_kind")}
    assert cit.ledger_row({"source_key": "k"}) == {"source_key": "k"}, "an absent key stays absent"
    # and the footer's own citation reads it exactly as it reads a menu row
    c = cit.from_evidence(row, 7)
    assert c.id == "E7" and c.date == "2023-03-28" and c.payload["source_key"] == "k"
    assert c.locator["char_start"] == 3


def test_a_menu_with_a_keyless_or_duplicate_item_keeps_every_position():
    """Defensive construction: `_uniq_evidence` never hands one, but a caller that did must not shift any
    address -- positions are positions, and the FIRST holder of a key owns it."""
    uniq = [{"source_key": "a", "text": "1"}, {"text": "no key"}, {"source_key": "a", "text": "dup"}]
    led = cit.EvidenceLedger(uniq)
    assert led.address({"source_key": "a", "text": "1"}) == 1
    assert led.evidence() == uniq


@pytest.mark.parametrize("n_menu", [0, 1, 47])
def test_registered_addresses_start_past_the_menu_and_are_contiguous(n_menu):
    led = cit.EvidenceLedger(_menu(n_menu) if n_menu <= 9 else
                             [{"source_key": f"m{i}", "text": str(i)} for i in range(n_menu)])
    ks = [led.address({"source_key": f"new{i}", "text": "t"}) for i in range(3)]
    assert ks == [n_menu + 1, n_menu + 2, n_menu + 3]
    assert led.stamp()["registered"] == 3


def test_0925_AT3_the_menu_decision_is_the_callers_word_never_read_off_the_process():
    """09-25 CLOSE-OUT (lane AT, VERIFY MINOR-6). The VC-2 ledger issues the menu's ordinals when the turn's
    menu printed them -- and the first cut read that decision back out of `sys.modules`, so a ledger built by
    hand behaved one way before `answer` was imported and another way after. The decision is now HANDED IN by
    the one caller that builds the turn's ledger (`answer._evidence_ledger`, which passes the producer's own
    `_handle_menu_on()`), and a ledger nobody told printed no menu.

    Pinned on behaviour, both sides of the import: the SAME hand-built ledger issues nothing before and after
    the serving body is loaded; `menu_printed=True` issues every keyed menu ordinal; and the serving body's own
    builder passes its decision -- True by default, False under the dossier lane's override."""
    import sys
    menu = _menu(3) + [{"source": "keyless", "text": "a menu row with no durable key"}]
    before = cit.EvidenceLedger(menu)
    from leviathan.graphrag import answer as an  # the serving body, now certainly loaded
    assert "leviathan.graphrag.answer" in sys.modules and an._handle_menu_on() is True
    after = cit.EvidenceLedger(menu)
    for led in (before, after):
        assert led.menu_printed is False and led.issued() == {}, "a ledger nobody told printed no menu"
    told = cit.EvidenceLedger(menu, menu_printed=True)
    assert sorted(told.issued()) == [1, 2, 3], "every KEYED menu ordinal; a keyless row has no address"
    assert told.evidence() == menu and told.stamp() == before.stamp(), "issuing moves no address and no count"
    served = an._evidence_ledger(menu)                           # the serving body's builder: its own decision
    assert served.menu_printed is True and sorted(served.issued()) == [1, 2, 3]
    with an.handle_menu_override(False):                          # the dossier lane: the menu printed no ordinals
        dossier = an._evidence_ledger(menu)
    assert dossier.menu_printed is False and dossier.issued() == {}
    assert an._evidence_ledger(menu, menu_printed=False).issued() == {}   # the seam's threaded value wins
