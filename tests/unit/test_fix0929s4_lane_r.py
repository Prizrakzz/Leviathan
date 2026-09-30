"""THE 09-29 FIX SITTING 4, LANE R -- render / rows / seam / register / the row-word books.

TWO LAWS (owner, 2026-09-27): a fix SERVES the writer -- it adds a FACT the writer reasons over, never a sentence it
must repeat -- and every item is proved OPEN on HEAD before it is built (the stale-note law). Each pin names the FACT
its item adds and the CHECK that guards it.

R4-1 (C4-9)   the series' SHORT name (``reading_short``) is the inline noun; the one splice producer enters it IN the
              writer's slot -- never in apposition, one determiner, the scope after the slot's head or dropped where
              the slot already names the place. The long card description stays the row line's and the footer's name.
R4-2 (C4-10)  a scaled unit prints its display words on the block ("1000 MT" -> "thousand tonnes"), each a spelling
              the verifier already reads as that unit; every other reader keeps the stored unit.
R4-4 (a)      the quorum's unread members by their reason (the walk's new words), never "absent"; a member counted by
              its dated action is listed by that action (C4-12).
R4-4 (c)      the block's own absence and scope sentences state the fact in the reader's objects, never "this turn".
R4-4 (d)(e)   the register table: the composed ``firing`` phrase repeats no word of any frame; the "cleared the bar"
              row's first replacement names the watch list.
R4-4 (f)      a head=True noun correction sets the scope after the stand-in head ("the exports series for India").
R4-5 (C4-11)  a strike never widens across a line break.
Call sites    C4-1 the tape's declined change by its reason (F4-1) and the netting tape part that skips it; C4-3 the
              standing book's attributive forms; C4-6 the threshold clause's noun on its scalar; C4-15 the product
              classes at the pair spread; C4-19 the watch window and ``watch_core_standing``; C4-18 the anchor note.
NOT LANE R (by file, THREAT_MODEL S4-B / S4-C): R4-3 (numbers/cascade ``_tail_legs``, lane T); R4-4 (b)
(numbers/query ``CYCLE_FALLBACK_NOTE``, lane T).

Every pin is offline and $0: the shipped books, cards, graph and the 2026-09-29 smoke / probe sentences quoted
verbatim where a pin reads prose.
"""
from __future__ import annotations

import inspect
import re
import types

import yaml

from leviathan.graphrag import graph as G
from leviathan.graphrag import register as REG
from leviathan.graphrag import verify as V
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS

DOC = L.load_conventions() or {}
TABLES = yaml.safe_load(L._cfg("numbers", "tables.yaml").read_text(encoding="utf-8")) or {}
HIER = yaml.safe_load(L._cfg("commodity_hierarchy.yaml").read_text(encoding="utf-8")) or {}


def _fields(w: str) -> str:
    return re.sub(r"\{[a-z]+\}", "", str(w))


def _fold(tokens) -> set:
    """The estate's crude plural fold (one trailing ``s``), applied to both sides of a content-word compare."""
    return {t[:-1] if (len(t) > 3 and t.endswith("s") and not t.endswith("ss")) else t for t in tokens}


def _card(table: str, metric: str) -> dict:
    ms = ((TABLES.get("tables") or {}).get(table) or {}).get("metrics") or {}
    return dict(ms.get(metric) or {}) if isinstance(ms, dict) else {}


# ══ THE BOOKS ══════════════════════════════════════════════════════════════════════════════════════════════════════
def test_R41_the_short_name_book_is_complete_clean_plain_and_names_the_series_never_its_driver():
    rs, rw = DOC["reading_short"], DOC["reading_words"]
    assert set(rs) == set(rw)                                          # complete over the long names' keys
    graph = G.load_contracts()
    bm = F.board_map()
    for key, short in rs.items():
        assert L._row_word_errs("reading_short %r" % key, short) == [], key
        assert ROWS._SPLICE_PLAIN_RX.fullmatch(short), (key, short)    # words only: it can stand in a slot
        table, metric = key.split(".", 1)
        metrics = ([metric] if metric != "*" else
                   list((((TABLES.get("tables") or {}).get(table) or {}).get("metrics") or {}).keys()))
        # THE SERIES, NEVER THE DRIVER (the 09-23 ruling): the words of every driver routed to this card
        refs = {ref for ref, r in bm.items() if r.get("table") == table and (metric == "*" or r.get("metric") == metric)}
        drivers = {d.id for c in graph.values() for d in c.drivers if getattr(d, "silver_ref", None) in refs}
        dwords = _fold(V._tokens(" ".join(x.replace("_", " ") for x in drivers)))
        # the card's own words: its description and the long name; its display LABEL only where the label's word is
        # not a driver's (the drought card's label is "drought z-score" -- a driver's word, which the 09-23 ruling
        # moved off the row's name)
        own, label = set(), set()
        for m in metrics:
            c = _card(table, m)
            own |= _fold(V._tokens(str(c.get("desc") or "")))
            label |= _fold(V._tokens(str(c.get("label") or "")))
        own |= _fold(V._tokens(str(rw[key])))
        allowed = own | (label - dwords)
        words = _fold(V._tokens(short))
        assert words <= allowed, (key, sorted(words - allowed))


def test_R42_every_display_word_is_a_spelling_the_verifier_reads_as_that_very_unit_and_the_book_is_complete():
    uw = DOC["unit_words"]
    for unit, words in uw.items():
        assert L._row_word_errs("unit_words %r" % unit, words) == [], unit
        assert V._unit_tokens(words) in V._row_unit_spellings(unit), (unit, words)
    # COMPLETE over the cards' declared units whose scale the verifier can say in a word (a declared scale word)
    scale_words = set(TABLES.get("unit_scale_words") or ())
    declared = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("unit", "display_unit") and isinstance(v, str):
                    declared.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(TABLES.get("tables") or {})
    need = {u for u in declared if any(sp and sp[0] in scale_words for sp in V._row_unit_spellings(u))}
    have = {ROWS._unit_key(k) for k in uw}
    assert {ROWS._unit_key(u) for u in need} <= have, sorted(need)
    assert "1000 MT" in need


def test_R42_display_unit_is_the_one_reader_and_never_blank():
    assert ROWS.display_unit("1000 MT") == "thousand tonnes"
    assert ROWS.display_unit("1000 mt") == "thousand tonnes"               # the same unit, another producer's case
    assert ROWS.display_unit("US cents/bushel") == "US cents/bushel"       # no entry: as stored
    assert ROWS.display_unit("1000 480 lb. Bales") == "1000 480 lb. Bales"  # no scale word says it: as stored
    assert ROWS.display_unit("") == ""


def test_C415_the_class_words_are_hierarchy_groups_declared_once():
    pcw = DOC["product_class_words"]
    assert set(pcw) <= set((HIER.get("groups") or {}).keys())
    assert pcw == {"oilseeds": "a seed", "vegetable_oils": "an oil", "oilseed_meals": "a meal", "grains": "a grain"}
    for k, w in pcw.items():
        assert L._row_word_errs("product_class_words %r" % k, w) == []


def test_C43_the_attributive_standing_is_appended_at_the_tail_and_the_printed_first_word_is_heads():
    psw = DOC["pair_standing_words"]
    assert psw["under"][:4] == ["under", "below", "at a discount to", "cheaper than"] and psw["under"][4] == "cheaper"
    assert psw["over"][:4] == ["over", "above", "at a premium to", "dearer than"] and psw["over"][4] == "dearer"
    for side in ("under", "over"):
        for w in psw[side]:
            assert L._row_word_errs("pair_standing_words", w) == []
        # only the attributive form of a comparative the book already declares -- never a new lexeme
        assert psw[side][4] + " than" in psw[side]


def test_R44a_the_quorum_reasons_are_count_words_only_and_the_unread_link_is_never_said_absent():
    qw = DOC["quorum_words"]
    for k in ("regime_action_unread", "regime_action_none_read", "marker_orientation_undeclared",
              "regime_action_polarity_undeclared"):
        assert L._row_word_errs("quorum_words %r" % k, qw[k]) == [], k
        for verdict in ("met", "in force", "at or past", "short of", "fires"):
            assert verdict not in f" {qw[k]} ", (k, verdict)
        assert "not counted" in qw[k]
    assert L._row_word_errs("quorum_words counted_by", qw["counted_by"], "{date}") == []
    # the smoke's false sentence: an UNREAD link said as an ABSENT action ("no ... policy action ... stands on the
    # record at this date") -- the none-read word says unread, the read-none word says what WAS read
    assert "stands on the record" not in qw["regime_action_none_read"] and "unread" in qw["regime_action_none_read"]
    assert "were read" in qw["regime_action_unread"]


def test_C41_the_tape_decline_words_name_the_session_and_the_window():
    w = DOC["tape_decline_words"]["base_not_a_price"]
    assert all(w.count(p) == 1 for p in ("{date}", "{n}", "{noun}"))
    assert L._row_word_errs("tape_decline_words", _fields(w)) == []


# ══ R4-1: THE SHORT NAME, IN THE SLOT ══════════════════════════════════════════════════════════════════════════════
def _drought_row(country="SE Asia Palm Belt", contract="malaysian_crude_palm_oil_cme"):
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="drought_z", commodity=contract, country=country),
                       status="ok", table="gold_weather_z", metric="drought_z", cadence="monthly", unit="z",
                       narrate_unit="z", scale=1.0, level=1.2491708897603446, level_date="2026-08",
                       knowledge_date="2026-09-25", asof="2026-09-26")
    st.z = {"value": 2.6650948688736418, "window_n": 120}
    st.percentile = {"value": 96.5909090909091}
    st.convention = F._convention_label(DOC["conventions"]["drought_z"], st, {}, st.key.label(), [])
    return types.SimpleNamespace(contract=contract, driver_id="drought", state=st, context_only=False, sign="+",
                                 lag_band=None, confidence="high", legs={"loud": True},
                                 series_key=st.key.label(), key=(contract, "drought"))


def test_R41_the_identity_names_the_row_inline_by_its_short_name_and_keeps_the_long_name_for_its_line():
    ident = R.row_identity_for(_drought_row())
    assert ident.short == "the dry-day run z-score"
    assert ident.short_words() == "the dry-day run z-score for SE Asia Palm Belt"
    assert ident.name == DOC["reading_words"]["gold_weather_z.drought_z"]     # the row line's and footer's name
    assert ident.head_words().startswith(ident.name)
    # a card whose name is short already, and the FX card whose label names it: HEAD's inline noun
    assert R.series_short_words("silver_psd", "exports_mt") == "exports"
    assert R.series_short_words("silver_fred_fx", "idr_usd", "", "IDR/USD exchange rate") == ""
    blank = ROWS.RowIdentity(row_id="x", contract="c", driver_id="d", series_key="k", table="t", metric="m",
                             name="the long name", scope="India")
    assert blank.short_words() == "the long name for India"                      # no short: HEAD's noun


def _apply(text, start, end, name="", **kw):
    a, b, rep = ROWS.splice(text, start, end, name, **kw)
    assert a <= start and b >= end                                               # never narrower than asked
    return text[:a] + rep + text[b:]


# THE SIX LIVE SENTENCES (smoke 2026-09-29, probe opus5_plain, arm A), the post-verify input verbatim; the name is the
# row identity's short noun the name correction writes (``short_words``)
LIVE = (
    ("carries a right-tailed drought reading past the severe [N14] line [N13] that the model works",
     "drought", "the dry-day run z-score for SE Asia Palm Belt",
     "carries a right-tailed dry-day run z-score reading for SE Asia Palm Belt past the severe [N14] line [N13] that"
     " the model works"),
    ("while the severe drought reading [N13] settles a higher one", "drought",
     "the dry-day run z-score for SE Asia Palm Belt",
     "while the severe dry-day run z-score reading for SE Asia Palm Belt [N13] settles a higher one"),
    ("the high-confidence stocks reading [N100] and the high-confidence drought reading [N24] point opposite ways.",
     "drought", "the dry-day run z-score for SE Asia Palm Belt",
     "the high-confidence stocks reading [N100] and the high-confidence dry-day run z-score reading for SE Asia Palm"
     " Belt [N24] point opposite ways."),
    ("ahead of pace. US flash drought reads -1.04 z [N29], 3rd percentile [N31]", "flash drought",
     "the dry-day run z-score for United States",
     "ahead of pace. US dry-day run z-score reads -1.04 z [N29], 3rd percentile [N31]"),
    ("Against them, US drought and flash-drought readings are on the wet side (-0.69 z, August 2026 [N67])",
     "flash-drought", "the dry-day run z-score for United States",
     # "US" sits in ANOTHER noun phrase of the clause ("US drought and ..."): the scope is kept, a true repeat
     "Against them, US drought and dry-day run z-score readings for United States are on the wet side (-0.69 z, "
     "August 2026 [N67])"),
    ("in force [N98]) and the cocoa flowering-stress reading (-0.24 z, less heat stress than usual [N124])",
     "flowering-stress", "the heat-stress anomaly for West Africa",
     "in force [N98]) and the cocoa heat-stress anomaly reading for West Africa (-0.24 z, less heat stress than usual"
     " [N124])"),
)


def test_R41_the_six_live_sentences_take_the_short_name_in_the_slot_never_in_apposition():
    for text, span, name, want in LIVE:
        i = text.index(span)
        out = _apply(text, i, i + len(span), name)
        assert out == want, (out, want)
        assert out.count("(") == text.count("(")                                  # no apposition
        assert not re.search(r"\b(the|a|an)\s+(?:[A-Za-z]+-[A-Za-z-]+\s+)*(the|a|an)\b", out, re.I)
        assert re.findall(r"\[N\d+\]", out) == re.findall(r"\[N\d+\]", text)      # no handle moved
        if "US " + span in text:
            assert "United States" not in out                                      # the slot's own place: said once


def test_R41_the_scope_rides_after_the_slots_head_and_is_dropped_only_where_the_slot_names_the_place():
    t = "the drought reading [N5] rose"
    i = t.index("drought")
    assert _apply(t, i, i + 7, "the dry-day run z-score for United States") == \
        "the dry-day run z-score reading for United States [N5] rose"
    t = "the US drought reading [N5] rose"
    i = t.index("drought")
    assert _apply(t, i, i + 7, "the dry-day run z-score for United States") == \
        "the US dry-day run z-score reading [N5] rose"                              # "US" is United States
    t = "the Brazil drought reading [N5] rose"
    i = t.index("drought")
    assert _apply(t, i, i + 7, "the dry-day run z-score for United States").endswith(
        "dry-day run z-score reading for United States [N5] rose")                   # another place: kept
    # the caller's own scope words are the scope where it passes them
    t = "India's export ban [N70] bites"
    i = t.index("export ban")
    assert _apply(t, i, i + 10, "exports for India", scope_words="India") == "India's exports [N70] bites"
    # sentence start keeps its capital and the article (the name opens its own noun phrase)
    t = "x.\n\nDrought at 1.25 z [N17] is"
    i = t.index("Drought")
    assert _apply(t, i, i + 7, "The dry-day run z-score for SE Asia Palm Belt") == \
        "x.\n\nThe dry-day run z-score for SE Asia Palm Belt at 1.25 z [N17] is"


def test_R44f_a_head_correction_keeps_the_number_neutral_head_with_the_scope_after_it():
    t = "counts the exportable supply [N70] and"
    i = t.index("exportable supply")
    out = _apply(t, i, i + len("exportable supply"), "exports for India", head=True)
    assert out == "counts the exports series for India [N70] and"                  # never "exports for India series"
    t = "while India's exportable supply sits at 25 MMT [N63]"
    i = t.index("exportable supply")
    assert _apply(t, i, i + len("exportable supply"), "exports for India", head=True) == \
        "while India's exports series sits at 25 MMT [N63]"                          # the slot names India: dropped
    # a short name whose own last word is a slot head keeps it (no stand-in)
    assert _apply("the stock figure [N3] sits", 4, 16, "the ending stocks figure", head=True, book=("series", "figure")) \
        == "the ending stocks figure [N3] sits"


def test_R45_a_strike_never_widens_across_a_line_break_and_heads_rejoins_are_unchanged():
    text = "the normal 3% tax paid.\n[N1] USDA FAS Export Sales = 0 1000 MT\n[N2] next"
    i = text.index("[N1]")
    a, b, rep = ROWS.splice(text, i, i + 4)
    assert "\n" not in text[a:b] and rep == ""
    t = "a line\t[E1]\nnext"
    i = t.index("[E1]")
    a, b, _ = ROWS.splice(t, i, i + 4)
    assert "\n" not in t[a:b] and t[:a] + t[b:] == "a line\t\nnext"          # a line break is never read as a blank
    # sitting 3's U-10 (a) re-joins, byte for byte (no line break near them)
    tariff = "duties spring 2018 [E1], [E4], with WASDE"
    i = tariff.index(" [E4]")
    assert _apply(tariff, i, i + 5) == "duties spring 2018 [E1], with WASDE"
    assert _apply("sits [E4] at", 5, 9) == "sits at" and _apply("sits [E4].", 5, 9) == "sits."


# ══ R4-2: THE DISPLAY UNIT ON THE BLOCK ════════════════════════════════════════════════════════════════════════════
def test_R42_a_block_level_prints_the_display_words_and_its_call_keeps_the_stored_unit():
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="esr_exports", commodity="corn_cbot", country=""),
                       status="ok", table="silver_esr", metric="weekly_exports_1000mt", cadence="weekly",
                       unit="1000 MT", narrate_unit="1000 MT", scale=1.0, level=1900.0, level_date="2026-09-17",
                       knowledge_date="2026-09-24", asof="2026-09-29")
    row = types.SimpleNamespace(contract="corn_cbot", driver_id="export_pace", state=st, context_only=False,
                                sign="+", lag_band=None, confidence="high", legs={"loud": True},
                                series_key=st.key.label(), key=("corn_cbot", "export_pace"))
    line, calls = R.sb_state(1, row, asof="2026-09-29")
    assert "1,900 thousand tonnes" in line or "1900 thousand tonnes" in line, line
    assert "1000 MT" not in line
    assert calls[0]["rows"][0]["unit"] == "1000 MT"                              # the backing is the stored unit
    # every other reader of the precision producer keeps the stored unit (the footer's read-back guard)
    assert R.shown_figure(1900.0, table="silver_esr", metric="weekly_exports_1000mt", unit="1000 MT").endswith("1000 MT")
    assert R.shown_figure(1900.0, table="silver_esr", metric="weekly_exports_1000mt", unit="1000 MT",
                          display=True).endswith("thousand tonnes")


# ══ C4-6: THE THRESHOLD CLAUSE'S NOUN ══════════════════════════════════════════════════════════════════════════════
def test_C46_every_threshold_scalar_carries_the_noun_its_clause_prints_and_the_clause_bytes_are_heads():
    assert R.THRESHOLD_CLAUSE_NOUN == "line"
    blk = R.Block(start=24)
    line, calls = R.sb_state(24, _drought_row(), asof="2026-09-26", block=blk)
    blk.add(line, calls)
    assert "past the line the desk convention calls severe" in line               # HEAD's bytes
    th = [s for s in blk.served_scalars() if s["kind"] == "card_threshold"]
    assert th and all(s.get("head_noun") == "line" for s in th)
    src = inspect.getsource(R.sb_convention)
    assert "{THRESHOLD_CLAUSE_NOUN}" in src and "\"head_noun\": THRESHOLD_CLAUSE_NOUN" in src


# ══ F4-1's PRINT (C4-1): A DECLINED CHANGE SAYS WHY; THE NETTING TAPE PART SKIPS IT ═════════════════════════════════
def _cocoa_tape(declined_reason="base_not_a_price"):
    ch63 = {"window": "63 sessions", "n_periods": 63, "declined": True, "delta": None, "pct": None,
            "base_date": "2026-01-12"}
    if declined_reason:
        ch63["reason"] = declined_reason
    return ROWS.TapeState(slug="cocoa_ice", asof="2026-04-15", level=3630.0, level_date="2026-04-14",
                          contract_month="2026-07", unit="USD/metric ton", currency="USD",
                          changes=[{"window": "1 sessions", "n_periods": 1, "delta": 12.0, "declined": False},
                                   {"window": "21 sessions", "n_periods": 21, "delta": -412.0, "declined": False},
                                   ch63],
                          percentile={"value": 40.0})


def test_F41d_the_declined_change_says_the_store_settle_is_not_a_price_and_heads_words_stand_without_a_reason():
    line, calls = R.sb_tape(51, _cocoa_tape(), asof="2026-04-15")
    assert ("the settle the store holds for 12 January 2026 is not a price, so no change is printed over "
            "sixty-three sessions") in line
    assert not any("63 sessions" in str(c["query"].get("metric")) for c in calls)   # no change call minted
    head_line, _ = R.sb_tape(51, _cocoa_tape(declined_reason=""), asof="2026-04-15")
    assert "the same contract carries no change to print" in head_line


def test_F41c_the_netting_tape_part_names_the_longest_printed_window_never_the_declined_one():
    tp = _cocoa_tape()
    nf = R.ask_netting_facts(types.SimpleNamespace(row=lambda *a: None), types.SimpleNamespace(rows_meta=[]),
                             slug="cocoa_ice", tape=tp, tape_first_handle=51)
    assert nf["tape"]["window"] == "21 sessions" and nf["tape"]["handle"] == 53
    assert nf["tape"]["direction"] == "down"


# ══ R4-4 (c): THE BLOCK'S OWN WORDS ════════════════════════════════════════════════════════════════════════════════
def test_R44c_no_block_sentence_names_the_machines_clock():
    for k, w in R.ABSENCE_WHY.items():
        assert "this turn" not in w and "read budget" not in w and "reader slot" not in w, (k, w)
    assert "this turn" not in R.sb_analog_leg_absence("", not_reached=True)
    ch = types.SimpleNamespace(terms={}, hops=(), scope={"events_in_corpus": False})
    assert "this turn" not in R.chain_arithmetic_words(ch)
    for kind in ("regime_in_force",):
        w1 = R._event_words(kind, event_date="2025-03-10", precision="month", published="2025-03-19")
        w2 = R._event_words(kind, event_date="", precision="", published="2025-03-19")
        assert "this turn" not in w1 and "this turn" not in w2 and "retrieved for this question" in w1


# ══ R4-4 (a) / W4-2 (C4-12): THE QUORUM'S MEMBERS BY THEIR REASON AND BY THEIR ACTION ══════════════════════════════
def test_R44a_a_member_the_walk_never_read_is_named_unread_by_its_reason():
    row = {"contract": "rough_rice_cbot", "name": "export_restriction_squeeze", "threshold": 3, "n_declared": 3,
           "n_with_band": 0, "matched_measured": ["ending_stocks"],
           "matched_unmeasured": ["India_export_ban", "tender_squeeze"],
           "unread_reason": {"India_export_ban": "regime_action_none_read",
                             "tender_squeeze": "marker_orientation_undeclared"}}
    line = R.sb_convergence(row)
    assert DOC["quorum_words"]["regime_action_none_read"] in line and "(India export ban)" in line
    assert DOC["quorum_words"]["marker_orientation_undeclared"] in line and "(tender squeeze)" in line
    assert "stands on the record at this date" not in line


def test_W42_a_member_counted_by_its_dated_action_is_listed_by_that_action_never_by_its_effect_series_z():
    row = {"contract": "malaysian_crude_palm_oil_cme", "name": "substitution_demand_pull", "threshold": 2,
           "n_declared": 3, "n_with_band": 0, "matched_measured": ["import_tariff", "stocks"],
           "matched_unmeasured": [],
           "counted_by": {"import_tariff": {"action_date": "2026-05-12", "e_handle": 7, "polarity": "cut"}}}
    line = R.sb_convergence(row)
    assert "import tariff, counted by its dated action of 12 May 2026 [E7]" in line
    assert "(stocks, with its own [N] z; import tariff, counted by its dated action of 12 May 2026 [E7])" in line
    base = dict(row)
    base.pop("counted_by")
    assert "counted by its dated action" not in R.sb_convergence(base)


# ══ C4-15 / C4-19 / C4-18: THE CALL SITES ═════════════════════════════════════════════════════════════════════════
def test_C415_the_classes_ride_the_call_only_where_the_calculator_takes_them_and_the_registry_names_both(monkeypatch):
    from leviathan.graphrag.numbers import registry as REGY

    def calc(*a, class_a=None, class_b=None, **k):
        return {}
    stats = types.SimpleNamespace(pair_level_spread=calc)
    monkeypatch.setattr(REGY, "product_class", lambda s: {"a": "oilseeds", "b": "vegetable_oils"}.get(s),
                        raising=False)
    assert R._pair_classes(stats, "a", "b") == {"class_a": "oilseeds", "class_b": "vegetable_oils"}
    assert R._pair_classes(stats, "a", "zzz") == {}                               # a leg with no class: HEAD's call
    assert R._pair_classes(types.SimpleNamespace(pair_level_spread=lambda *a, **k: {}), "a", "b") == {}


def test_C419_the_window_is_passed_only_where_the_producer_takes_it_and_the_standing_sentence_follows_its_word():
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import watch as WA
    if "window" in inspect.signature(WA.horizon_miss_clause).parameters:
        out = R._horizon_miss_clause("print", next_print="2026-10-01", window=("2026-10-01", "2026-10-05"))
        assert isinstance(out, str) and out
    else:
        assert R._horizon_miss_clause("print", next_print="2026-10-01", window=("2026-10-01", "2026-10-05")) == \
            R._horizon_miss_clause("print", next_print="2026-10-01")
    declared = "watch_core_standing" in tuple(getattr(B, "WATCH_REASONS", ()) or ())
    assert ("watch_core_standing" in R.ABSENCE_WHY) == declared                   # lint clause 9, both directions
    assert "this page" not in R._WATCH_CORE_STANDING_WHY and not any(c.isdigit() for c in R._WATCH_CORE_STANDING_WHY)


def test_S4_the_anchor_note_rides_the_header_only_where_the_anchor_pass_resolved_it(monkeypatch):
    from leviathan.graphrag.state import board as B
    # the resolver's closed words as CONTRACT C4-18 declares them (lane S's board.py); without them: HEAD's header
    monkeypatch.setattr(B, "ANCHOR_RESOLUTION_REASONS", (), raising=False)
    assert R.anchor_resolution_words(types.SimpleNamespace(anchors=(types.SimpleNamespace(
        contract="x", resolution="one_priced_contract", resolved_from="y", note="stands for y"),))) == ""
    monkeypatch.setattr(B, "ANCHOR_RESOLUTION_REASONS", ("priced", "one_priced_contract", "class_named",
                                                         "several_priced", "no_priced_contract"), raising=False)
    a1 = types.SimpleNamespace(contract="soybeans_cbot", resolution="one_priced_contract", resolved_from="soybeans",
                               note="stands for soybeans: the one soybeans contract with a price record")
    a2 = types.SimpleNamespace(contract="corn", resolution="several_priced", resolved_from="corn",
                               note="corn has several contracts with a price record: CBOT corn and DCE corn; none is picked")
    a3 = types.SimpleNamespace(contract="corn_cbot", resolution="priced", resolved_from="", note="named in the question")
    a4 = types.SimpleNamespace(contract="corn_cbot", note="named in the question")         # HEAD's anchor
    words = R.anchor_resolution_words(types.SimpleNamespace(anchors=(a1, a2, a3, a4)))
    assert words == (" %s stands for soybeans: the one soybeans contract with a price record." % R.board_label(
        "soybeans_cbot") + " corn has several contracts with a price record: CBOT corn and DCE corn; none is picked.")
    assert R.anchor_resolution_words(types.SimpleNamespace(anchors=(a3, a4))) == ""


# ══ R4-4 (d)(e): THE REGISTER TABLE ════════════════════════════════════════════════════════════════════════════════
def test_R44d_the_composed_firing_phrase_repeats_no_word_of_any_frame_it_is_composed_into():
    from leviathan.graphrag.state.narration import MANDATE_BLOCK_READER_NAME as PAGE
    e = REG.desk_phrase("firing", 1)
    frames = ("the dated window of one of the {E}", "name the dated window of that one of the {E} in words",
              "on the one dated window of one of the {E} that %s states" % PAGE,
              "measured over the dated window of X, one of the {E}, whose dated span rides the reading of this link")
    ew = _fold(re.findall(r"[a-z]{4,}", e.lower()))
    for f in frames:
        fw = _fold(re.findall(r"[a-z]{4,}", f.replace("{E}", "").lower()))
        assert not (ew & fw), (f, sorted(ew & fw))
    assert "like" not in e and REG.count_desk_register(e) == 0


def test_R44e_the_first_replacement_names_the_watch_list_and_nothing_head_taught_is_withdrawn():
    col = {n: r for n, _p, r in REG.DESK_REGISTER_TOKENS}
    assert REG.desk_phrase("cleared the bar", 0) == "made the watch list"
    for head_phrase in ("stands out on its own record", "is on the watch list"):
        assert head_phrase in col["cleared the bar"]
    for head_phrase in ("the times this reading sat this far out", "dated windows on the record", "occasions"):
        assert head_phrase in col["firing"]
    for n, _p, r in REG.DESK_REGISTER_TOKENS:
        assert REG.count_desk_register(r) == 0, n
