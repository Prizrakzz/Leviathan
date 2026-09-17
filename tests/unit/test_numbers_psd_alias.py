"""LANE C (prearm fix r1, 2026-09-17) -- THE ALIAS RESOLUTION AT THE COMMODITY REFUSAL SITE.

THE DEFECT THIS DECK PINS. The 2026-09-16 in-VPC pre-arm smoke issued ELEVEN lookups that came back
`silver_psd does not serve commodity 'wheat' / 'corn' / 'soybeans' / 'soybean_oil' / 'palm_oil'` -- the
agent asking the USDA balance-sheet cards by SHORT NAME where they are keyed by CONTRACT SLUG -- and on
one turn the retry after those refusals returned `(not known)` and the served answer told the reader
"USDA's world palm and world soyoil balance sheets for this marketing year carry NO figure at this
as-of". A false not-known is the most expensive thing this desk can serve.

THE TWO HALVES PINNED HERE:
  * RESOLUTION, and it is SAFE FOR A PRODUCER REASON rather than a judgement about names --
    `usda_psd._PSD_COMMODITY_TO_SLUGS` fans ONE published USDA sheet out over several slugs, so the
    members of a family are the same rows under different keys. `test_the_family_is_one_published_sheet`
    reads that producer map and proves it, which is what makes `agent.PSD_FANOUT_ALIAS` a keying table
    rather than a scope choice.
  * NON-RESOLUTION, which is the larger half. A card that is NOT a fan-out card resolves nothing; a
    single near-miss candidate is never offered as a recommendation; and the refusal message is
    BYTE-IDENTICAL to HEAD everywhere the new clause does not fire.
"""
from __future__ import annotations

import json
import types

import pytest
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers.registry import load_registry

PSD = "silver_psd"
PSDA = "silver_psd_attributes"

# The five names the smoke actually sent, and the card each was sent to (report_*_204824Z.md and
# report_*_204833Z.md): palm_oil x3 + soybean_oil x3 on the soyoil turn, corn and wheat on BOTH PSD
# cards on the corn/wheat turn, soybeans on the deep turn. Eleven refusals over five turns.
SMOKE_REFUSALS = (
    (PSD, "wheat"), (PSDA, "wheat"),
    (PSD, "corn"), (PSDA, "corn"),
    (PSD, "soybeans"),
    (PSD, "soybean_oil"), (PSDA, "soybean_oil"),
    (PSD, "palm_oil"), (PSDA, "palm_oil"),
)


def _spec(table, commodity):
    return types.SimpleNamespace(table=table, commodity=commodity)


def _reg():
    return load_registry()


# ── THE RESOLUTION ───────────────────────────────────────────────────────────────────────────────────
def test_every_short_name_the_smoke_sent_now_resolves_on_both_psd_cards():
    """THE HEADLINE PIN: none of the eleven refused lookups is a refusal any more, and each resolves to
    the family member the estate's own vocabulary names."""
    reg = _reg()
    want = {"wheat": "soft_red_winter_wheat_cbot", "corn": "corn_cbot", "soybeans": "soybeans_cbot",
            "soybean_oil": "soybean_oil_cbot", "palm_oil": "malaysian_crude_palm_oil_cme"}
    for table, name in SMOKE_REFUSALS:
        got = A._check_commodity_class(_spec(table, name), reg)
        assert got == want[name], f"{table}.{name} -> {got!r}"


def test_the_family_is_one_published_sheet_and_the_producer_map_says_so():
    """THE JUSTIFICATION, AS A PIN. Every alias target must sit in the producer's slug list for a code
    that ALSO contains the other members of its family -- i.e. the alias picks a KEY for one sheet, it
    never picks between two sheets. This is the whole argument for resolving rather than refusing a name
    that maps to four declared values, so it is asserted against the producer instead of a comment."""
    pytest.importorskip("pandas")
    from leviathan.transforms.bronze_to_silver.usda_psd import _PSD_COMMODITY_TO_SLUGS as FANOUT
    by_slug = {s: code for code, slugs in FANOUT.items() for s in slugs}
    for asked, target in A.PSD_FANOUT_ALIAS.items():
        assert target in by_slug, f"{target} is not emitted by any producer code"
        code = by_slug[target]
        siblings = set(FANOUT[code])
        # every DECLARED value the token rule would have offered as a candidate for `asked` must be a
        # sibling under the SAME code -- otherwise the word spans two sheets and must not resolve.
        cands = set(A._alias_candidates(asked, list(_reg().get(PSD).commodity_values or [])))
        assert cands <= siblings or not cands, f"{asked}: {sorted(cands - siblings)} are a second sheet"


def test_the_alias_table_agrees_with_the_estates_own_curated_resolver():
    """`complex_map._BARE_TO_SLUG` answers the same question for reroute v2. Where the two carry the
    same key they must give the same slug -- one estate, one vocabulary. (The lane's table is the
    SMALLER of the two on purpose: complex_map routes `canola`/`rapeseed` at the OIL level per the RV-W0
    curation, which is right for a relative-value pair and wrong on a card that serves the SEED under
    its own key, so those keys are deliberately absent here.)"""
    from leviathan.graphrag.complex_map import _BARE_TO_SLUG
    for asked, target in A.PSD_FANOUT_ALIAS.items():
        if asked in _BARE_TO_SLUG:
            assert _BARE_TO_SLUG[asked] == target, asked


def test_every_alias_target_is_declared_by_both_psd_cards():
    """The prose can never drift ahead of the fence (THREAT_MODEL_FIXES C.5 item 3): a target the card
    does not declare would be re-keyed into a refusal one line later."""
    reg = _reg()
    for card in (PSD, PSDA):
        declared = set(reg.get(card).commodity_values or [])
        for asked, target in A.PSD_FANOUT_ALIAS.items():
            assert target in declared, f"{card} does not declare {target} (for {asked})"


def test_the_resolution_is_stamped_on_the_payload_the_model_reads():
    note = A.alias_resolution_note("palm_oil", "malaysian_crude_palm_oil_cme")
    assert "palm_oil" in note and "malaysian_crude_palm_oil_cme" in note
    assert "nothing was substituted" in note.lower()
    # APPEND, NEVER OVERWRITE (the D-PQ EMPTY-1 discipline): a NO-ROWS marker outranks a keying note.
    p = A._stamp_alias({"scope_note": "NO ROWS RETURNED."}, ("palm_oil", "malaysian_crude_palm_oil_cme"))
    assert p["scope_note"].startswith("NO ROWS RETURNED.") and note in p["scope_note"]
    assert p["commodity_alias"] == {"asked": "palm_oil", "resolved": "malaysian_crude_palm_oil_cme"}
    # and a call that resolved nothing gets the SAME OBJECT back, untouched
    same = {"rows": []}
    assert A._stamp_alias(same, None) is same and "scope_note" not in same


# ── ROUND 2, REVIEW M-1: THE NOTE MUST NOT INSTRUCT THE MISLABEL THE CARD FORBIDS ────────────────────
def test_the_note_names_the_family_and_never_tells_the_model_to_say_the_contract_class():
    """THE DEFECT, VERBATIM FROM ROUND 1: "Say 'soft_red_winter_wheat_cbot''s own subject out loud when
    you state the figure" -- four tokens from the figure -- against this card's own notes, 250 kB up
    the cached prefix, saying the opposite in capitals: all four wheat keys carry USDA's ALL-CLASS
    aggregate, "never quote one as if it were that class's own balance sheet". The cost was already
    measured AT HEAD on the pre-arm corpus: `quick_rv_corn_wheat.md` served "soft red winter wheat's
    stocks-to-use reads 0.652178 [N34]" for a figure the producer map says is the all-class sheet.

    The note now names the KEY, the FAMILY, how many of that family THIS CARD serves, and hands the
    scope question back to the card prose."""
    reg = _reg()
    allowed = list(reg.get(PSD).commodity_values or [])
    note = A.alias_resolution_note("wheat", "soft_red_winter_wheat_cbot", allowed)
    # (a) the machine fact is still there -- what was asked, what was read
    assert "'wheat'" in note and "'soft_red_winter_wheat_cbot'" in note
    # (b) the family size is the CARD's count, not the producer's, and it is stated
    assert "one of 4 wheat contract keys" in note
    # (c) the reader words come from the estate's ONE display producer, never a second copy
    assert A._reader_words("soft_red_winter_wheat_cbot") in note
    # (d) THE INSTRUCTION IS GONE, and the opposite instruction is present
    assert "own subject out loud" not in note
    assert "own class balance sheet" in note and "mislabel" in note
    # (e) the card prose is named as the authority
    assert "card's own commodity note is the authority" in note.lower()
    # (f) every family word counts against the card it is asked on
    for asked, n in (("palm_oil", 2), ("soybeans", 3), ("corn", 5), ("soybean_meal", 2)):
        assert A._fanout_family_size(asked, allowed) == n, asked
        assert f"one of {n} " in A.alias_resolution_note(asked, A.PSD_FANOUT_ALIAS[asked], allowed)


def test_the_declared_family_members_are_the_producers_own_slug_lists():
    """`PSD_FANOUT_MEMBERS` is the note's source for "one of N", so it is pinned against the SAME
    producer map `PSD_FANOUT_ALIAS` is pinned against -- one fact, two tables, never allowed to drift.
    The alias TARGET of a family must also be one of its own members."""
    from leviathan.transforms.bronze_to_silver.usda_psd import _PSD_COMMODITY_TO_SLUGS as PROD
    by_slug = {s: code for code, slugs in PROD.items() for s in slugs}
    assert set(A.PSD_FANOUT_MEMBERS) == set(A.PSD_FANOUT_ALIAS)
    for asked, members in A.PSD_FANOUT_MEMBERS.items():
        target = A.PSD_FANOUT_ALIAS[asked]
        assert target in members, (asked, target)
        code = by_slug[target]
        assert sorted(members) == sorted(PROD[code]), (asked, code)


# ── ROUND 2, REVIEW M-2: THE NOTE SURVIVES THE TOOL-RESULT CUT ON A REAL PSD SERVE ───────────────────
def _psd_payload(n):
    rows = [{"value": 1.0 + i, "unit": "MT", "commodity": "soft_red_winter_wheat_cbot",
             "country": "United States", "period": 2000 + (i % 27), "knowledge_date": "2026-09-04",
             "estimate_role": "current", "release_date": "2026-09-04"} for i in range(n)]
    return {"query": {"table": PSD, "metric": "production_mt",
                      "commodity": "soft_red_winter_wheat_cbot", "country": "United States",
                      "asof": "2026-09-06"}, "rows": rows, "status": "ok", "truncated": False}


@pytest.mark.parametrize("n", [1, 20, 40, 76, 200])
def test_the_resolution_note_survives_the_six_thousand_char_tool_result_cut(n):
    """`answer_numbers` ships every tool_result as `json.dumps(content)[:6000]`. Round 1 appended the
    two alias keys LAST, so on a PSD-shaped serve the lane's stated safety mechanism -- "the resolution
    is said out loud on the tool_result the model reads" -- was cut mid-sentence at 40 rows and gone
    entirely at 76, which is the size of the smoke's OWN [N23]/[N24] serve. The round-1 pin could not
    see it because its fixture had ONE row. Insertion order is JSON order, so the keys ride at the
    FRONT and the cut can never reach them."""
    allowed = list(_reg().get(PSD).commodity_values or [])
    pair = ("wheat", "soft_red_winter_wheat_cbot", allowed)
    note = A.alias_resolution_note(*pair)
    stamped = A._stamp_alias(_psd_payload(n), pair)
    assert list(stamped)[:2] == ["commodity_alias", "scope_note"]      # the two keys are FIRST
    assert note in json.dumps(stamped)[:6000], n                       # ...so the model reads it whole
    # ...and nothing else about the payload moved: same keys, same rows, same order after the front
    assert list(stamped)[2:] == ["query", "rows", "status", "truncated"]
    assert stamped["rows"] == _psd_payload(n)["rows"]


# ── THE NON-RESOLUTION, WHICH IS THE LARGER HALF ─────────────────────────────────────────────────────
def test_a_non_fanout_card_resolves_nothing_and_names_its_candidates():
    """silver_fgis declares three wheat classes and they are THREE DIFFERENT INSPECTION PROGRAMS, not
    one sheet under three keys. The fence holds, and the refusal now says WHICH three."""
    reg = _reg()
    with pytest.raises(A.CommodityOffCard) as e:
        A._check_commodity_class(_spec("silver_fgis", "wheat"), reg)
    msg = str(e.value)
    assert "AMBIGUOUS, NOT ABSENT" in msg
    for slug in ("soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt",
                 "hard_red_spring_wheat_mgex"):
        assert slug in msg


def test_one_candidate_is_never_a_recommendation():
    """'corn' on silver_fgis matches exactly ONE declared value, and it is STILL refused with HEAD's
    message -- no candidate clause. Offering a lone near-miss is how `orange` would have become
    `frozen_orange_juice` on a card whose own notes say the fruit and the juice are two subjects."""
    reg = _reg()
    with pytest.raises(A.CommodityOffCard) as e:
        A._check_commodity_class(_spec("silver_fgis", "corn"), reg)
    assert "AMBIGUOUS" not in str(e.value)
    assert A._alias_candidates("corn", list(reg.get("silver_fgis").commodity_values or [])) == ["corn_cbot"]


@pytest.mark.parametrize("name", ["orange", "sunflower", "canola", "rapeseed", "cocoa", "oil", "sugar"])
def test_the_two_subject_words_resolve_on_no_card_in_the_registry(name):
    """THE NEGATIVE CORPUS, and it is the registry itself rather than a hand-built list. A pure
    token-contiguity resolver run over all 23 fenced cards while authoring this resolved 41 names, two
    of them across a subject boundary (`orange` -> frozen_orange_juice beside a declared fresh_citrus;
    `sunflower` -> sunflower_oil on silver_esr, where the seed and the oil are separate programs).
    None of these may resolve anywhere."""
    reg = _reg()
    for tid, spec in reg.tables.items():
        if name in (spec.commodity_values or []):
            continue
        if not (spec.commodity_values or []):
            continue
        with pytest.raises(A.CommodityOffCard):
            A._check_commodity_class(_spec(tid, name), reg)


def test_the_refusal_is_byte_identical_to_head_wherever_the_clause_does_not_fire():
    """HEAD's message, reproduced here in full, must come back verbatim for a genuinely off-card name
    with fewer than two candidates -- which is the overwhelming majority of every refusal in the estate
    (measured on the live registry while authoring: 191 of 217 name/card pairs tried)."""
    reg = _reg()
    tid, cid = PSD, "cocoa"
    allowed = list(reg.get(tid).commodity_values or [])
    head = (
        f"lookup REFUSED -- {tid} does not serve commodity {cid!r}. This card serves exactly these and "
        f"nothing else: {', '.join(allowed)}. It is a CLOSED set, not a default: there is no row for "
        f"{cid!r} here and no neighbouring commodity on this card stands in for it. Either re-issue the "
        f"call with one of the listed values (and say out loud, in the answer, which commodity and which "
        f"geography the figure belongs to), or find another table -- do NOT substitute a different "
        f"commodity's number for the one that was asked about. Nothing was queried.")
    with pytest.raises(A.CommodityOffCard) as e:
        A._check_commodity_class(_spec(tid, cid), reg)
    assert str(e.value) == head


def test_an_undeclared_card_and_a_blank_commodity_are_untouched():
    """The fence's own opt-in contract: no declaration, no behaviour -- and the resolver inherits it."""
    reg = _reg()
    assert A._check_commodity_class(_spec("silver_cot", "wheat"), reg) is None   # no declared set
    assert A._check_commodity_class(_spec(PSD, ""), reg) is None
    assert A._check_commodity_class(_spec("", "wheat"), reg) is None
    assert A._check_commodity_class(_spec("no_such_table", "wheat"), reg) is None


# ── THE CARD PROSE ───────────────────────────────────────────────────────────────────────────────────
def test_every_slug_the_psd_card_prose_names_is_a_declared_value():
    """THREAT_MODEL_FIXES C.8 pin 1. The notes teach the families by name; a slug there that the fence
    does not serve would teach a lookup that is refused the moment it is made."""
    reg = _reg()
    for card in (PSD, PSDA):
        spec = reg.get(card)
        declared = set(spec.commodity_values or [])
        notes = str(spec.notes or "")
        named = {w for w in declared if w in notes}
        assert len(named) >= 18, f"{card} names only {len(named)} family members"
        for token in ("_cbot", "_dce", "_matif", "_jse", "_cme"):
            for word in notes.replace("|", " ").replace(",", " ").split():
                w = word.strip(".;:()")
                if w.endswith(token) and "_" in w:
                    assert w in declared, f"{card} prose names {w!r}, which the card does not serve"


def test_the_prose_teaches_the_five_family_words_the_smoke_got_wrong():
    reg = _reg()
    notes = str(reg.get(PSD).notes or "")
    for word in ("wheat", "corn", "soybeans", "soybean_oil", "palm_oil"):
        assert word in notes, word
    assert "CONTRACT SLUG" in notes.upper()


# ── END TO END ───────────────────────────────────────────────────────────────────────────────────────
def _resp(content, stop):
    return types.SimpleNamespace(content=content, stop_reason=stop, usage=None)


class _FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        outer = self

        class _M:
            def create(self, **kw):
                outer.sent.append(kw)
                return outer.queue.pop(0)
        self.messages = _M()


def test_a_short_name_lookup_serves_a_row_and_the_turn_records_the_resolution():
    """The deep turn's own shape: one `silver_psd` lookup for 'soybeans'. At HEAD it returned
    `status: error` and burned a round; here it queries soybeans_cbot, serves the row, says so on the
    payload the model reads, and records the resolution on the turn."""
    captured = {}

    def query_fn(sql):
        captured["sql"] = sql
        return [{"value": "8847000", "knowledge_date": "2026-09-11"}]

    use = types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, id="t1", input={
        "table": PSD, "metric": "ending_stocks_mt", "commodity": "soybeans",
        "country": "United States", "period": "2025"})
    client = _FakeClient([
        _resp([use], "tool_use"),
        _resp([types.SimpleNamespace(type="text", text="US soybean ending stocks 8,847,000 MT.")], "end_turn"),
    ])
    out = A.answer_numbers("US soybean ending stocks?", asof="2026-09-16",
                           client=client, query_fn=query_fn)
    call = out["calls"][0]
    assert call["status"] == "ok" and call["rows"][0]["value"] == "8847000"
    assert call["query"]["commodity"] == "soybeans_cbot"          # the [N] row cites the real key
    assert "soybeans_cbot" in captured["sql"]
    assert call["commodity_alias"] == {"asked": "soybeans", "resolved": "soybeans_cbot"}
    assert "COMMODITY RE-KEYED" in call["scope_note"]
    assert "one of 3 soybeans contract keys" in call["scope_note"]      # the CARD's own family count
    assert out["commodity_aliases"] == {"soybeans": "soybeans_cbot"}
    # the model SEES it: the tool_result JSON carries the note
    tool_turn = [m for m in client.sent[-1]["messages"] if m["role"] == "user"][-1]
    assert "COMMODITY RE-KEYED" in json.dumps(tool_turn["content"])


def test_a_turn_that_resolves_nothing_writes_no_key():
    """Byte-identity by absence: the overwhelming majority of turns."""
    use = types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, id="t1", input={
        "table": PSD, "metric": "ending_stocks_mt", "commodity": "corn_cbot", "period": "2025"})
    client = _FakeClient([
        _resp([use], "tool_use"),
        _resp([types.SimpleNamespace(type="text", text="ok")], "end_turn"),
    ])
    out = A.answer_numbers("corn ending stocks?", asof="2026-09-16", client=client,
                           query_fn=lambda sql: [{"value": "1", "knowledge_date": "2026-09-11"}])
    assert "commodity_aliases" not in out
    assert "commodity_alias" not in out["calls"][0]
