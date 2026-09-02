"""D-HP-25 -- THE BINDING VERIFIER: V1 (the `[N]` geo axis) + V2 (the `[E]` geo-containment pass).

WHAT THIS FILE OWNS, AND WHY IT IS ITS OWN FILE. `test_dhp_renderer.py` owns what the renderer does with
a parsed token and carries the FIVE `_handle_period_phrase` pins that are this build's factor-out proof;
those five are asserted here NOT AT ALL, on purpose -- a factor-out whose regression proof lives in the
same file as the factor is a proof of nothing. This file owns the GEOGRAPHY axis: the ownership core's
axis-agnosticism, the four fail-open laws, both receipt halves, and the [E] containment conjunction.

THE ONE PROPERTY EVERY TEST HERE SERVES: a geo verifier's failure mode is NOT missing a swap, it is
DELETING A CORRECT SENTENCE. So most of what follows asserts SILENCE, and each silence test is paired
with the would-convict-without-the-guard case that makes the silence meaningful (plan 10.30.3(vi)):
a guard with no such pair is indistinguishable from a detector that cannot fire at all.
"""
from __future__ import annotations

from leviathan.graphrag import answer as an
from leviathan.graphrag import emf
from leviathan.graphrag import geo_lexicon as gl
from leviathan.graphrag import tracekeys as tk


def _call(metric: str, value, unit: str = "MMT", commodity: str = "palm_oil",
          period: str | None = None, table: str = "silver_mpob",
          country: str | None = None, rows=None) -> dict:
    """One numbers-agent call record, in the shape `cit.from_number` reads."""
    q = {"table": table, "metric": metric, "commodity": commodity}
    if period:
        q["period"] = period
    if country:
        q["country"] = country
    return {"query": q, "rows": (rows if rows is not None else [{"value": value, "unit": unit}]),
            "status": "ok", "shown": [value]}


def _st(tldr: str, mechanism: str = "") -> dict:
    return {"tldr": tldr, "mechanism": mechanism}


def _ev(text: str) -> dict:
    """One evidence row in `answer._uniq_evidence`'s projection shape -- the FULL stored text, which is
    the only thing V2 is permitted to read (never the snippet, never the label)."""
    return {"date": "2026-01-01", "source": "test", "source_key": "k", "text": text,
            "event_date": None, "event_date_precision": None, "score": 1.0}


def _geo_of(text: str, marker: str = "[N1]") -> set[str]:
    s0, s1 = an._handle_sentence_span(text, text.index(marker))
    i = text.index(marker)
    return an._handle_geo_phrase(text, s0, s1, i, i + len(marker))


# ══ (i) THE FACTOR-OUT -- `_owned_token` IS AXIS-AGNOSTIC AND THE PERIOD WRAPPER IS UNCHANGED ═════════

def test_the_period_wrapper_is_the_factor_expressed_through_the_core():
    """THE FACTOR-OUT IS A MOVE, NOT A REWRITE (plan 10.30.3(i)). The five pins at
    `test_dhp_renderer.py:651, :652, :686, :687, :735` are the regression proof and they pass UNMODIFIED;
    what this test adds is the OTHER direction -- that the wrapper's answer is now literally the core's
    answer, so the two can never drift apart while both exist."""
    text = "Production fell from [N1] in MY2023 to [N2] in MY2024, a step-down of [N3]."
    s0, s1 = an._handle_sentence_span(text, text.index("[N2]"))
    sent = text[s0:s1]
    toks = [(m.start(), m.end()) for m in an._DECLARED_PERIOD_RX.finditer(sent)]
    for marker, expect in (("[N1]", "MY2023"), ("[N2]", "MY2024")):
        i = text.index(marker)
        k = an._owned_token(sent, i - s0, i + 4 - s0, toks, an._RIGHT_APPOS_RX)
        assert k is not None and sent[toks[k][0]:toks[k][1]] == expect
        assert an._handle_period_phrase(text, s0, s1, i, i + 4) == expect
    # ...and a handle that owns nothing gets None from the core and "" from the wrapper, one state.
    j = text.index("[N3]")
    assert an._owned_token(sent, j - s0, j + 4 - s0, toks, an._RIGHT_APPOS_RX) is None
    assert an._handle_period_phrase(text, s0, s1, j, j + 4) == ""


def test_the_core_reads_three_tuples_so_one_body_serves_a_regex_axis_and_a_lexicon_axis():
    """THE WHOLE REASON THE PARAMETER IS A LIST AND NOT A REGEX. The period axis mints token spans from a
    regex; the geo axis mints them from a LEXICON and carries a slug in a third element. A core that took
    a regex could only ever serve the first, and a second copy of a 45-line consumption ledger is how two
    axes come to disagree about what "this handle's own token" means."""
    sent = "Brazilian output reached [N1] this week."
    toks = gl.extract_geos(sent)
    assert toks and len(toks[0]) == 3
    k = an._owned_token(sent, sent.index("[N1]"), sent.index("[N1]") + 4, toks, an._GEO_RIGHT_APPOS_RX)
    assert k is not None and toks[k][2] == "brazil"


def test_the_two_axes_never_share_a_consumption_ledger():
    """PLAN 10.30.3(ii), AND IT IS FORBIDDEN BY CONSTRUCTION RATHER THAN BY CONVENTION. A shared `claimed`
    set would let a YEAR consume a slot a GEO token needed (or the reverse) -- a silent, ORDER-DEPENDENT
    bug. `_owned_token` builds its ledger per call, so running the period axis first cannot change what
    the geo axis owns, and this test asserts exactly that invariance."""
    text = "Brazilian production in MY2024 reached [N1] on the month."
    s0, s1 = an._handle_sentence_span(text, text.index("[N1]"))
    i = text.index("[N1]")
    before = an._handle_geo_phrase(text, s0, s1, i, i + 4)
    an._handle_period_phrase(text, s0, s1, i, i + 4)          # ...run the other axis in between
    after = an._handle_geo_phrase(text, s0, s1, i, i + 4)
    assert before == after == {"brazil"}
    assert an._handle_period_phrase(text, s0, s1, i, i + 4) == "MY2024"   # ...and it still owns its year


# ══ (ii) GEO OWNERSHIP -- THE TWO PASSES, THE SIBLING BOUNDS, THE MISSING WIDENING ════════════════════

def test_geo_ownership_right_attaches_across_one_scope_preposition():
    """PASS 1, the geo axis' own appositive set. "[N1] in Brazil" binds across whitespace and ONE scope
    preposition and nothing else."""
    assert _geo_of("Output stood at [N1] in Brazil last month.") == {"brazil"}
    assert _geo_of("Output stood at [N1] for Indonesia last month.") == {"indonesia"}


def test_geo_ownership_left_bridges_to_the_nearest_clean_preceding_token():
    """PASS 2. The era-pair grammar writes the geography BEFORE the handle at least as often as after it
    ("Malaysian stocks stood at [N1]"), and a right-only reading would make the axis silent on half the
    corpus for no safety gain."""
    assert _geo_of("Malaysian stocks stood at [N1].") == {"malaysia"}
    # ...but NOT across a clause break: `_LEFT_BRIDGE_BAD_RX` rejects the comma, exactly as on the
    # period axis, and the token stays unowned rather than being guessed at.
    assert _geo_of("In Malaysia, the wider vegoil complex tightened, and stocks stood at [N1].") == set()


def test_a_siblings_geography_is_never_reachable_across_the_window():
    """M1(a) ON THE GEO AXIS, AND THE ASYMMETRY L3 PRODUCES, PINNED AS A DECISION RATHER THAN DISCOVERED.

    The window is bounded by the PREVIOUS and NEXT `[N]` sibling, so a geography belonging to another
    handle can never convict this one -- the guarantee the period axis' 18 comparison-anchor false
    positives bought.

    L3 IS EVALUATED ON THE WINDOW'S *CONTENTS*, NOT ON THE OWNED TOKEN, and that is the QUIETER of the
    two readings of plan 10.30.3(vi) ("if the window owns MORE THAN ONE canonical geo, compared =
    False"). THE MEASURABLE CONSEQUENCE, RECORDED HERE SO IT IS NEVER READ AS A BUG: in a two-geography
    era-pair sentence the LEFT handle's window reaches BOTH countries and therefore DECLINES, while the
    RIGHT handle's window (left-bounded by the previous sibling) reaches only one and IS compared. The
    quieter direction is the only direction a deletion-armed check may be tuned in, and the cost is
    recorded as a coverage residual at plan 10.30.11 rather than bought back with a looser rule."""
    text = "Brazilian output reached [N1] while Indonesian output reached [N2]."
    s0, s1 = an._handle_sentence_span(text, text.index("[N1]"))
    i, j = text.index("[N1]"), text.index("[N2]")
    assert an._handle_geo_phrase(text, s0, s1, i, i + 4) == set()          # L3: two in the window
    assert an._handle_geo_phrase(text, s0, s1, j, j + 4) == {"indonesia"}  # ...one in this one
    # AND THE GUARANTEE ITSELF: [N2]'s own answer is its OWN geography, never the sibling's, which is
    # what the window exists to make impossible.
    assert an._handle_geo_phrase(text, s0, s1, j, j + 4) != {"brazil"}


def test_there_is_no_geo_span_widening():
    """THE SECOND DELIBERATE DIFFERENCE (plan 10.30.3(ii)): there is no geo analogue of "an endpoint is
    read as its whole span", and widening a country is how a region swallows a continent. The returned
    set is the ADDITIVE CLOSURE of ONE owned token and never a union over the sentence."""
    assert _geo_of("French output reached [N1] this season.") == {"france", "european_union"}
    assert gl.canon_closure("brazil") == {"brazil"}       # ...and a slug with no ancestor closes to itself


# ══ (iii) L1 -- AGGREGATE SENTINELS. AGGREGATES NEVER CONVICT, IN EITHER DIRECTION ════════════════════

def test_l1_an_aggregate_claim_is_silent_and_without_the_guard_it_would_convict():
    """THE PAIR THAT MAKES THE GUARD MEANINGFUL. "World production" against a France receipt is a
    CONTAINER against its CONTENTS and is not a disagreement; the second half of the test shows the same
    receipt DOES convict a real single-country claim, so the silence is the guard's and not the
    detector's inability to fire."""
    call = _call("production", 4.2, country="France")
    assert _geo_of("World production reached [N1] this season.") == set()
    assert an._slot_geo_mismatch(_geo_of("World production reached [N1] this season."), call, 1) \
        == (False, False)
    # ...the would-convict case, same receipt, a real claim
    assert an._slot_geo_mismatch(_geo_of("Brazilian production reached [N1] this season."), call, 1) \
        == (True, True)


def test_l1_an_aggregate_receipt_is_silent_too():
    """THE OTHER DIRECTION, and it is stated separately because "aggregates never convict" is a claim
    about BOTH sides. A `World` receipt compares against nothing."""
    assert an._receipt_geo_text(_call("production", 4.2, country="World")) == set()
    assert an._slot_geo_mismatch({"brazil"}, _call("production", 4.2, country="World"), 1) \
        == (False, False)


def test_l1_european_union_unaccompanied_is_an_aggregate_on_both_sides():
    """THE CONDITIONAL HALF OF L1, which only the caller can evaluate: `European Union` is a real
    country-level slug on the PSD/ESR tables, so it is not a sentinel WORD -- it is an aggregate exactly
    when no member state stands beside it."""
    assert _geo_of("European Union production reached [N1].") == set()
    assert an._receipt_geo_text(_call("production", 4.2, country="European Union")) == set()


# ══ (iv) L2 -- ANCESTOR CLOSURE, ADDITIVE ONLY. ANCESTOR/DESCENDANT PAIRS NEVER CONVICT ═══════════════

def test_l2_the_fold_is_additive_and_a_replacing_fold_would_have_convicted():
    """`numbers/cascade.py:529`'s `_PSD_COUNTRY_FOLD` maps France -> European Union. APPLIED AS A
    REPLACEMENT it turns a France claim into an EU claim and then convicts it against a France receipt,
    which is a correct sentence deleted by its own canonicalization. Applied ADDITIVELY the two closures
    intersect and nothing happens -- and this test asserts BOTH the additivity and its consequence."""
    assert gl.canon_closure("france") == {"france", "european_union"}
    assert "france" in gl.canon_closure("france")        # ADDS, never REPLACES
    claim = _geo_of("French production reached [N1] this season.")
    assert claim == {"france", "european_union"}
    compared, mismatch = an._slot_geo_mismatch(claim, _call("production", 4.2, country="France"), 1)
    assert (compared, mismatch) == (True, False)


def test_l2_a_descendant_claim_against_an_ancestor_receipt_never_convicts():
    """NON-EMPTY INTERSECTION OF THE TWO CLOSURES IS AGREEMENT, however distant the ancestor. The
    receipt half reaches this state through a table whose country column names the EU aggregate."""
    assert an._slot_geo_mismatch({"france", "european_union"},
                                 _call("production", 4.2, country="France"), 1) == (True, False)
    # ...and the would-convict pair, so the silence above is the closure's and not an inability to fire
    assert an._slot_geo_mismatch({"france", "european_union"},
                                 _call("production", 4.2, country="Brazil"), 1) == (True, True)


# ══ (v) L3 -- MULTI-GEO DECLINE, THE SELLER/BUYER TRAP ═══════════════════════════════════════════════

def test_l3_two_countries_in_the_window_decline_the_comparison_entirely():
    """"US sales to China" names two countries and the sentence is about a FLOW. No single-geo comparison
    is correct there and NONE IS ATTEMPTED -- the pass declines rather than picking the nearer one, which
    is the difference between a guard and a guess."""
    assert _geo_of("United States sales to China reached [N1] on the week.") == set()
    assert _geo_of("Brazilian shipments to Indonesia reached [N1].") == set()
    # ...and the ONE-country spelling of the same sentence is compared, so the decline is L3's
    assert _geo_of("Brazilian shipments reached [N1] on the week.") == {"brazil"}


def test_l3_the_direction_prepositions_are_excluded_from_the_geo_appositive_set():
    """THE PERIOD AXIS' VOCABULARY IS NOT PORTABLE, and this is the clause that says so: "in MY2024" is a
    SCOPE and "to China" is a DIRECTION. `from` / `to` / `into` may never right-attach a geography."""
    for prep in ("from", "to", "into"):
        assert an._GEO_RIGHT_APPOS_RX.fullmatch(f" {prep} ") is None
    for prep in ("in", "for", "of", "during", "at", "by"):
        assert an._GEO_RIGHT_APPOS_RX.fullmatch(f" {prep} ") is not None


def test_l3_a_multi_geo_receipt_declines_too():
    """The receipt half's own L3: a country string naming two countries compares against nothing."""
    assert an._receipt_geo_text(_call("exports", 1.0, country="Brazil and Argentina")) == set()


# ══ (vi) L4 -- NOT-A-SCOPE FORMS: BOUNDARIES, FOLLOWERS, HOMONYMS, AMBIGUITY ══════════════════════════

def test_l4a_matching_is_word_boundary_and_accent_insensitive():
    """NO SUBSTRING HITS, EVER -- the `harvest.build_matcher` idiom. And the accented spelling of the
    cocoa corpus' largest origin resolves to the same slug as the ASCII one, or the lexicon would be
    silent on the exact documents it exists to read."""
    assert gl.slugs_in("Cote d'Ivoire arrivals") == {"cote_divoire"}
    assert gl.slugs_in("Côte d’Ivoire arrivals") == {"cote_divoire"}   # accent + curly quote
    assert gl.slugs_in("indochinese trade") == set()                             # no substring 'china'
    assert gl.slugs_in("the ghanaians") == set()                                 # no substring 'ghana'


def test_l4b_a_currency_or_holiday_follower_mints_no_token_and_would_have_convicted():
    """THE "Brazilian real" AND "Chinese New Year" CLASSES. A demonym followed by a currency, a holiday
    or an instrument noun names the UNIT, the CALENDAR or the INSTRUMENT a fact is quoted in -- not the
    geography of the fact. The paired half shows the same demonym DOES mint on an ordinary follower."""
    assert gl.slugs_in("the Brazilian real weakened") == set()
    assert gl.slugs_in("Chinese New Year demand") == set()
    assert gl.slugs_in("Malaysian ringgit strength") == set()
    assert gl.slugs_in("German government bonds sold off") == set()
    assert gl.slugs_in("Brazilian soybean exports") == {"brazil"}       # ...the would-convict pair
    # ...and it reaches the claim side, which is where a false token would actually delete a sentence
    assert _geo_of("The Brazilian real weakened while palm stocks stood at [N1].") == set()


def test_l4c_homonyms_are_dropped_not_guessed():
    """"turkey" THE BIRD and "chile" THE PEPPER. The decision is `numbers/agent.py:96`'s and it is REUSED
    here rather than re-derived -- the existing comment already carries the exact reasoning. Neither is a
    slug in the table TODAY, so these entries are a fence against a future addition; the pin is what
    stops that fence rotting silently."""
    assert gl.slugs_in("feed demand from turkey producers") == set()
    assert gl.slugs_in("chile pepper prices") == set()
    assert "turkey" in {gl.normalize(s) for s in gl._DECOY_SURFACES}


def test_l4d_a_surface_reaching_two_slugs_is_dropped_and_a_decoy_consumes_its_container():
    """AMBIGUITY RESOLVES TO SILENCE, and it is COMPUTED at import rather than assumed -- a later edit to
    the table cannot introduce a silent guess. The decoy half is (a) and (d) meeting: "South American"
    CONTAINS "American" and is not the United States, and it wins the span longest-first so the shorter
    surface inside it cannot fire."""
    assert gl.AMBIGUOUS_SURFACES == frozenset()          # ...no collision in the shipped table today
    assert gl.slugs_in("South American crops improved") == set()
    assert gl.slugs_in("Gulf of Mexico basis firmed") == set()
    assert gl.slugs_in("American soybean exports") == {"united_states"}   # the would-convict pair
    assert gl.slugs_in("told us the number") == set()    # bare `us` is refused: see the module docstring


def test_the_lexicon_covers_every_config_geography_slug_and_imports_without_the_configs():
    """THE IMPORT-TIME LINT IS A DEVELOPER INSTRUMENT AND NEVER A RUNTIME DEPENDENCY (plan 10.30.3(vii)).
    It is SKIP-SILENT when `configs/geographies` is absent -- an image without it MUST import clean, which
    is the entire reason the lexicon lives in `src/` -- and when the directory IS present it must report
    no gap. A lexicon that refuses to import because a config drifted is a serving outage caused by a
    linter."""
    assert gl.LEXICON_LINT == []
    if gl.CONFIG_SLUGS:                                  # present in the repo, absent in a slim image
        assert gl.CONFIG_SLUGS <= set(gl._COUNTRIES)
        assert len(gl.CONFIG_SLUGS) == 33
    assert len(gl._COUNTRIES) == 34 and "russia" in gl._COUNTRIES


# ══ (vii) `_receipt_geo_text` -- TIGHTENING T1, THE SHIPPED `from_number` RULE MIRRORED EXACTLY ═══════

def test_the_receipt_reads_the_query_country_first():
    """QUERY FIRST -- it is what the drill-down re-runs and the only unambiguous statement of scope on a
    free-axis card."""
    assert an._receipt_geo_text(_call("production", 4.2, country="Brazil")) == {"brazil"}


def test_the_receipt_falls_back_to_a_unanimous_row_country_on_a_free_axis_table():
    """T1's SECOND CLAUSE, mirroring `citations.py:390-392`: the row's geo IS the fact's geography on a
    free-axis card, but ONLY when every returned row carries the same one."""
    rows = [{"value": 1.0, "unit": "MMT", "country": "Brazil"},
            {"value": 2.0, "unit": "MMT", "country": "Brazil"}]
    assert an._receipt_geo_text(_call("production", 1.0, rows=rows)) == {"brazil"}
    mixed = [{"value": 1.0, "unit": "MMT", "country": "Brazil"},
             {"value": 2.0, "unit": "MMT", "country": "Argentina"}]
    assert an._receipt_geo_text(_call("production", 1.0, rows=mixed)) == set()


def test_the_receipt_refuses_the_row_country_on_a_destination_coded_table():
    """THE BUYER FENCE, AND IT IS THE HALF THAT MATTERS. On a destination-coded table the country axis
    enumerates BUYERS of one national flow, so the row's country is not the fact's geography and reading
    it would convict correct sentences at scale. `silver_esr` IS that table: its country axis enumerates
    the buyers of one US national flow.

    THE UNKNOWN-TABLE CASE IS *NOT* THE HICCUP CASE, and mirroring that exactly is the whole of T1. A
    table the registry does not carry yields `spec is None` -> False -> the row geo IS read, precisely as
    `citations.py:383-389` behaves; only a REGISTRY EXCEPTION takes the fail-silent True branch. Guessing
    a different answer here would convict against a geography the reader's own label never showed."""
    rows = [{"value": 1.0, "unit": "MMT", "country": "China"}]
    assert an._receipt_dest_coded("silver_esr") is True
    assert an._receipt_geo_text(_call("exports", 1.0, table="silver_esr", rows=rows)) == set()
    # ...and the free-axis sibling of the same read DOES borrow the row geo (the fallback is alive)
    assert an._receipt_geo_text(_call("exports", 1.0, table="silver_mpob", rows=rows)) == {"china"}
    # THE HICCUP BRANCH, exercised directly: a registry failure fails toward NOT COMPARING.
    from leviathan.graphrag.numbers import registry as _reg
    real = _reg.load_registry

    def _boom():
        raise RuntimeError("registry hiccup")

    _reg.load_registry = _boom
    try:
        assert an._receipt_dest_coded("silver_mpob") is True          # fail-SILENT, never fail-loud
        assert an._receipt_geo_text(_call("exports", 1.0, table="silver_mpob", rows=rows)) == set()
    finally:
        _reg.load_registry = real


def test_the_receipt_refuses_the_query_country_on_a_destination_coded_table_too():
    """REVIEW BLOCKER, PINNED. THE BUYER FENCE IS A FACT ABOUT THE AXIS, SO IT COVERS BOTH HALVES. An
    ESR call's `query['country']` IS THE DESTINATION (`numbers/agent.py:197-205`: "country=<name> -> FAS
    code IN filter"), i.e. the BUYER of one US national flow -- the very thing `_receipt_dest_coded`
    exists to refuse. Reading it convicted `American export commitments reached [N1]` against a
    `country='China'` ESR read: a CORRECT sentence deleted, and one of R11's frozen 15 spent doing it.

    THE PAIR THAT MAKES THE SILENCE MEANINGFUL is the free-axis sibling of the identical call: there the
    query country IS the fact's geography and it is still read. This guard costs coverage (4.4% of stored
    [N] calls), never safety -- which is the trade every law in this build makes."""
    esr = _call("weekly_exports_1000mt", 1234.5, table="silver_esr", country="China",
                rows=[{"value": 1234.5, "unit": "1000 MT", "country": "China"}])
    assert an._receipt_geo_text(esr) == set()
    text = "American export commitments reached [N1] for the week."
    assert _geo_of(text) == {"united_states"}                    # the claim side still speaks...
    assert an._slot_geo_mismatch(_geo_of(text), esr, 1) == (False, False)   # ...and nothing is COMPARED
    st = _st(text)
    census = an._resolve_number_handles(st, [esr], handle_prose=True)
    assert census["geo_checked"] == 0 and census["geo_mismatch"] == 0
    # THE SENTENCE SURVIVES *AND* KEEPS ITS FIGURE: nothing is refused, so the solitary handle takes the
    # ordinary VALUE SPLICE. Before the fix this census read `binding_refused=1, sentences_dropped=1` and
    # `tldr` was the empty string -- a correct sentence deleted by the verifier meant to protect it.
    assert census["sentences_dropped"] == 0 and census["binding_refused"] == 0
    assert census["substituted"] == 1 and "[N1]" in st["tldr"]
    assert st["tldr"] == "American export commitments reached 1,234.5 1000 MT [N1] for the week."
    # THE FREE-AXIS SIBLING: same query country, a table whose country axis IS the fact's geography.
    free = _call("stocks", 1234.5, table="silver_mpob", country="China")
    assert an._receipt_geo_text(free) == {"china"}
    assert an._slot_geo_mismatch({"united_states"}, free, 1) == (True, True)


def test_the_receipt_is_empty_when_it_names_nothing_and_never_parses_the_label():
    """M1(b), INHERITED VERBATIM FROM THE PERIOD AXIS: a detector whose remedy is DELETION must never
    parse a RENDERING. The label carries `from_number`'s staleness tail, its print-kind tags and its
    formatted value; none of it may reach a comparison. Absence on the receipt side is SILENCE."""
    assert an._receipt_geo_text(_call("production", 4.2)) == set()
    assert an._receipt_geo_text(None) == set()
    assert an._receipt_geo_text({}) == set()


# ══ (viii) `_slot_geo_mismatch` -- THE FAIL-OPEN MATRIX ═══════════════════════════════════════════════

def test_the_fail_open_matrix_is_silent_unless_both_sides_speak():
    """`compared` COUNTS COMPARISONS AND NEVER ATTEMPTS (FIX Z12's contract, inherited). Every cell whose
    claim or receipt says nothing returns `(False, False)`, so `geo_checked` can never read as coverage
    on a handle whose clause named no geography -- the exact defect the period axis' row half committed
    on 131 of 186 cited comparisons."""
    call_br = _call("production", 4.2, country="Brazil")
    matrix = [
        (set(), call_br, (False, False)),                       # claim silent
        ({"brazil"}, _call("production", 4.2), (False, False)),  # receipt silent
        (None, call_br, (False, False)),                        # claim absent entirely
        ({"brazil"}, None, (False, False)),                     # no call at all
        ({"brazil"}, call_br, (True, False)),                   # both speak, they agree
        ({"indonesia"}, call_br, (True, True)),                 # both speak, DISJOINT -> convict
    ]
    for claim, call, expect in matrix:
        assert an._slot_geo_mismatch(claim, call, 1) == expect


def test_a_real_geo_mis_binding_is_convicted_end_to_end_and_charged_to_binding_refused():
    """THE OTHER DIRECTION, OR THE INSTRUMENT MEANS NOTHING. A handle whose own sentence says Indonesia
    and whose receipt says Brazil is a REAL, CITED, WRONG number -- the wave's #1 risk -- and it takes
    the SHIPPED ladder (`binding_refused`, never `unresolvable`: the receipt RESOLVED and was declined,
    which is H1 FIX Z2's distinction)."""
    st = _st("Indonesian output reached [N1] on the month.")
    census = an._resolve_number_handles(st, [_call("production", 4.2, country="Brazil")],
                                        handle_prose=True)
    assert census["geo_checked"] == 1 and census["geo_mismatch"] == 1
    assert census["binding_refused"] == 1 and census["substituted"] == 0
    assert census["unresolvable"] == 0
    assert "4.2" not in st["tldr"]


def test_one_handle_is_convicted_by_at_most_one_class_so_the_dedup_arithmetic_holds():
    """PLAN 10.30.6's DEDUP RULE, MADE STRUCTURAL. `emf`'s mis-bound expression sums the class counters,
    so a handle charged BOTH `slot_scope_mismatch` and `geo_mismatch` would consume two of R11's frozen
    fifteen for one event. The geo check is seated inside the direction check's `else`, so a
    period-convicted handle never reaches it -- and this sentence disagrees on BOTH facets."""
    st = _st("Indonesian output reached [N1] in MY2024.")
    census = an._resolve_number_handles(
        st, [_call("production", 4.2, country="Brazil", period="2019")], handle_prose=True)
    assert census["slot_scope_mismatch"] == 1
    assert census["geo_mismatch"] == 0 and census["geo_checked"] == 0
    assert census["binding_refused"] == 1              # ONE handle, ONE charge


# ══ (ix) V2 -- THE `[E]` GEO-CONTAINMENT CONJUNCTION ══════════════════════════════════════════════════

def test_v2_convicts_a_positive_contradiction():
    """THE CONJUNCTION, ALL THREE CLAUSES HOLDING: the claim owns exactly one geography, the receipt's
    FULL STORED TEXT does not name its closure, and it DOES name another country."""
    st = _st("Indonesian output tightened the balance [E1].")
    census = an._drop_evidence_geo_contradiction(
        st, [_ev("Brazilian crushers lifted throughput sharply in the period under review.")])
    assert census["convicted"] == 1
    assert census["sentences_dropped"] + census["handles_dropped"] >= 1
    assert "[E1]" not in st["tldr"]


def test_v2_is_silent_on_absence_which_is_the_whole_design():
    """CLAUSE (c) IS WHAT MAKES THIS A POSITIVE-CONTRADICTION DETECTOR. A receipt that names NO country
    is not evidence of the WRONG country, and without (c) this pass would convict every correctly-bound
    sentence whose supporting document simply never spells its geography out -- which is most of the
    corpus."""
    st = _st("Indonesian output tightened the balance [E1].")
    census = an._drop_evidence_geo_contradiction(
        st, [_ev("Crushers lifted throughput sharply in the period under review.")])
    assert census == {"convicted": 0, "handles_dropped": 0, "sentences_dropped": 0}
    assert st["tldr"] == "Indonesian output tightened the balance [E1]."


def test_v2_is_silent_when_the_receipt_contains_the_claims_own_closure():
    """CLAUSE (b), AND ITS L2 HALF: an `European Union` mention in a France receipt is the claim's OWN
    ANCESTOR and is therefore CONTAINMENT, not contradiction."""
    st = _st("French output tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(
        st, [_ev("France lifted its estimate this month.")])["convicted"] == 0
    st2 = _st("French output tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(
        st2, [_ev("The European Union raised its balance-sheet estimate this month.")])["convicted"] == 0


def test_v2_is_silent_on_aggregates_on_both_sides():
    """L1 APPLIES TO THE TEXT SCAN TOO (plan 10.30.4). A world receipt is a container, and a world claim
    compares against nothing."""
    st = _st("World output tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(
        st, [_ev("Brazilian crushers lifted throughput.")])["convicted"] == 0
    st2 = _st("Indonesian output tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(
        st2, [_ev("Global crush totals rose, led by Brazilian mills.")])["convicted"] == 0


def test_v2_never_lets_an_eu_only_receipt_convict_a_member_state_claim():
    """REVIEW MAJOR, PINNED. L1 SAYS AGGREGATES NEVER CONVICT IN EITHER DIRECTION, and `european_union`
    is the one aggregate `sentinel_hit` deliberately does not carry (its aggregate reading is CONDITIONAL
    and only the caller can evaluate it, `geo_lexicon.py:173-180`). V1 evaluates it; V2 did not, so an
    `EU wheat exports ...` receipt read as a POSITIVE contradiction of a German/Italian/Polish/Romanian/
    Hungarian claim and killed the sentence -- the five members that residual 3 leaves without an EU
    ancestor edge, on the stated grounds that L1 already covered them from the other side. It did not.

    THE PAIR THAT MAKES THE SILENCE MEANINGFUL is the third block: when a MEMBER STATE stands beside the
    EU in the same receipt, that slug still convicts on its own, so clause (c) loses nothing it was
    entitled to."""
    body = "EU wheat exports fell from 23.086 MMT to 16.728 MMT over the marketing year."
    for adj in ("German", "Italian", "Polish", "Romanian", "Hungarian", "French"):
        st = _st(f"{adj} wheat exports slowed [E1].")
        assert an._drop_evidence_geo_contradiction(st, [_ev(body)])["convicted"] == 0
        assert st["tldr"] == f"{adj} wheat exports slowed [E1]."
    # ...and a NON-member claim is equally safe: a container is not a disagreement with anything.
    st2 = _st("Brazilian wheat exports slowed [E1].")
    assert an._drop_evidence_geo_contradiction(st2, [_ev(body)])["convicted"] == 0
    # THE WOULD-CONVICT-WITHOUT-THE-GUARD CASE: a member state named beside the EU still convicts.
    st3 = _st("German wheat exports slowed [E1].")
    assert an._drop_evidence_geo_contradiction(
        st3, [_ev("EU wheat exports fell, with France accounting for the bulk of the decline.")]
    )["convicted"] == 1


def test_v2_declines_a_multi_geo_claim_and_an_unresolved_or_grouped_handle():
    """L3 ON THE [E] SIDE, plus the two structural declines: an index past the end of the menu is
    UNRESOLVED (that is `_resolve_evidence_handles`' population, never this one -- the H1 FIX Z2 error is
    not repeated) and a GROUPED token stands in for no single receipt."""
    st = _st("Indonesian shipments to China tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(
        st, [_ev("Brazilian crushers lifted throughput.")])["convicted"] == 0
    st2 = _st("Indonesian output tightened the balance [E9].")
    assert an._drop_evidence_geo_contradiction(
        st2, [_ev("Brazilian crushers lifted throughput.")])["convicted"] == 0
    st3 = _st("Indonesian output tightened the balance [E1, E2].")
    assert an._drop_evidence_geo_contradiction(
        st3, [_ev("Brazilian crushers lifted throughput."),
              _ev("Brazilian crushers lifted throughput.")])["convicted"] == 0


def test_v2_reads_the_full_stored_text_and_not_a_snippet():
    """CLAUSE (b) SAYS *FULL STORED TEXT*, NEVER THE 140-CHAR SNIPPET, and the reason is that a snippet
    is a DISPLAY ARTIFACT -- convicting on one measures TRUNCATION, not binding. This row's own
    geography appears only past the 140th character, and the pass must find it and stay silent."""
    body = ("Crushing margins improved through the quarter as freight eased and vessel line-ups cleared "
            "at the main terminals, with buyers stepping in on the break. Indonesian mills then lifted "
            "throughput.")
    assert len(body) > 140 and "Indonesian" not in body[:140]
    st = _st("Indonesian output tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(st, [_ev(body)])["convicted"] == 0


def test_v2_severs_rather_than_kills_when_the_sentence_keeps_another_receipt():
    """ITS OWN SEVER-VS-KILL LADDER, and it is the SMALLEST REMEDY THAT LEAVES THE JOIN TOTAL: sever the
    clause when the sentence keeps another receipt, drop the sentence when it does not. NEVER a splice --
    an [E] payload is a source, a date and a snippet, so there is no figure to write."""
    st = _st("Indonesian output tightened the balance [E1], and the wider complex firmed [E2].")
    census = an._drop_evidence_geo_contradiction(
        st, [_ev("Brazilian crushers lifted throughput."), _ev("The complex firmed.")])
    assert census["convicted"] == 1 and census["sentences_dropped"] == 0
    assert census["handles_dropped"] == 1
    assert "[E2]" in st["tldr"] and "[E1]" not in st["tldr"]


def test_v2_mints_its_own_seam_and_stays_out_of_the_slot_emptying_licence_set():
    """FIX X2's PROVENANCE RULE AND FIX X6's, BOTH. A WHOLE-SENTENCE producer names its own tag and is
    NOT in `_SLOT_EMPTYING_SEAM_SRCS` -- the sentence it cut is gone, so nothing it mints is evidence
    that a SURVIVING sentence was emptied, and conflating the two fail-opens the provenance check.

    THE SECOND SENTENCE IN THE FIXTURE IS LOAD-BEARING AND IS *ALSO* THE X6 PIN: `allow_empty` is False
    for a whole-sentence producer, so a FIELD-FINAL kill leaves no successor text and mints NO record at
    all. Both halves are asserted, because "the seam fired" and "the seam is correctly suppressed" are
    two different guarantees and a fixture that only ever exercises one of them proves neither."""
    class _Report:
        def __init__(self):
            self.strip_seams: list = []

    rep = _Report()
    st = _st("Indonesian output tightened the balance [E1]. Freight eased into the quarter.")
    an._drop_evidence_geo_contradiction(st, [_ev("Brazilian crushers lifted throughput.")], rep)
    assert rep.strip_seams and all(s.get("src") == an._SEAM_SRC_E_GEO for s in rep.strip_seams)
    assert an._SEAM_SRC_E_GEO not in an._SLOT_EMPTYING_SEAM_SRCS
    assert an._SEAM_SRC_E_GEO != an._SEAM_SRC_E_VALUE_SLOT      # its OWN constant, not a shared one
    # X6: the same kill at the END of the field mints nothing -- there is no successor text to key on.
    rep2 = _Report()
    st2 = _st("Indonesian output tightened the balance [E1].")
    assert an._drop_evidence_geo_contradiction(
        st2, [_ev("Brazilian crushers lifted throughput.")], rep2)["sentences_dropped"] == 1
    assert rep2.strip_seams == []


# ══ (x) ACCOUNTING + STAMP DISCIPLINE ════════════════════════════════════════════════════════════════

def test_both_classes_are_declared_arm_exclusive_and_mis_bound_but_never_killed():
    """PLAN 10.30.6, EVERY CLAUSE. G1 clause (4) is a CLASS SCAN over `by_rule`, so an UNDECLARED class
    FAILS THE CLAUSE ON ITS OWN REMEDY -- a verifier that breaks the gate by WORKING is a defect, not a
    result. They are MIS-BOUND because a wrong-geography receipt IS a wrong receipt (excluding them would
    be counting the finds and not the finding), and they are NOT KILLED because a RENDER conviction must
    not inflate `unconstructible_count` (plan 10.10(c))."""
    for cls in ("geo_mismatch", "evidence_geo_contradiction"):
        assert cls in emf.G1_DECLARED_CLASSES
        assert cls in emf.ARM_EXCLUSIVE_CLASSES
        assert cls in emf.MIS_BOUND_CLASSES
        assert cls not in emf.KILLED_CLASSES
    assert an._E_GEO_CONTRADICTION_CLASS == "evidence_geo_contradiction"
    assert "geo_mismatch" in an._RENDER_LEDGER_CLASSES     # the census key IS the class: one spelling


def test_the_ledger_fold_preserves_the_sum_invariant():
    """`sum(by_rule.values()) == stripped` IS THE LEDGER'S OWN INVARIANT, not bookkeeping garnish: every
    `by_rule[x] += 1` in verify.py is paired with `stripped += 1`, and a class folded in without its
    strip would break it. Both new classes ride `_fold_ledger_class`, the ONE writer."""
    v = {"by_rule": {}, "stripped": 0}
    an._fold_render_classes(v, {"geo_mismatch": 2, "slot_scope_mismatch": 1})
    an._fold_ledger_class(v, an._E_GEO_CONTRADICTION_CLASS, 3)
    assert v["by_rule"] == {"geo_mismatch": 2, "slot_scope_mismatch": 1,
                            "evidence_geo_contradiction": 3}
    assert sum(v["by_rule"].values()) == v["stripped"] == 6


def test_the_new_trace_key_is_appended_at_the_tail_and_v1_mints_none():
    """APPEND-NEVER-SORT (the 12f law): eval.py SPLATS the registry IN ORDER, so a sorted insert re-keys
    every historical artifact comparison. V1 mints NO top-level key at all -- its two counters ride
    inside `number_handles`, which is one registered key, one stamp site, one producer, and zero column
    shift.

    RE-ANCHORED (D-LD Sitting-A, 2026-08-18): `tables_queried` -- the per-table usage census -- was
    APPENDED after this key, so the tail moved by one. The invariant this pin actually protects is
    UNCHANGED and is re-stated positionally below: V2's key is still AFTER every older key and was never
    INSERTED ahead of one.

    RE-ANCHORED AGAIN (2026-09-01): five later appends moved the tail -- timing_ms, then xc_open_pair +
    xc_open_decline (the D-XT build, 08-29), then xc_regional_decline + quantify_rv_reading_fenced (the
    RV lane, 08-29). All five were APPENDED in order; same invariant, new offsets."""
    assert tk.TRACE_RECORD_KEYS[-10] == "evidence_geo_dropped"
    assert tk.TRACE_RECORD_KEYS[-9] == "tables_queried"
    assert tk.TRACE_RECORD_KEYS[-4] == "quantify_rv_reading_fenced"
    assert tk.TRACE_RECORD_KEYS[-3] == "quantify_derived_fenced"    # D-DA append, 09-01
    assert tk.TRACE_RECORD_KEYS[-2] == "quantify_cascade_walk"     # walk charter, 09-01 (10th 12f application)
    assert tk.TRACE_RECORD_KEYS[-1] == "quantify_wave_reads"      # A2 wave counter, same commit
    assert "geo_checked" not in tk.TRACE_RECORD_KEYS and "geo_mismatch" not in tk.TRACE_RECORD_KEYS
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)


def test_control_arm_invariance_is_absolute_absent_never_null():
    """CLAUSE (7), AND IT IS ABSOLUTE. With `handle_prose` off the census is the pre-D-HP FOUR KEYS
    byte-for-byte -- the two new counters are minted ONLY inside the `handle_prose` branch -- and the
    prose is untouched. D-HP-16's three-lane law is why ABSENT and not zero: a key that is `null` on
    control and `0` on a quiet treatment run is a key that cannot be pooled."""
    body = "Indonesian output reached [N1] on the month."
    off = _st(body, body)
    census = an._resolve_number_handles(off, [_call("production", 4.2, country="Brazil")],
                                        handle_prose=False)
    assert set(census) == {"substituted", "handles_dropped", "sentences_dropped", "unresolvable"}
    assert "geo_checked" not in census and "geo_mismatch" not in census
    assert off["tldr"] == body.replace("[N1]", "4.2 MMT [N1]")   # ...the pre-D-HP splice, unchanged
    # ...and a QUIET treatment turn stamps the keys at 0, which is what makes the arms poolable
    quiet = _st("Brazilian output reached [N1] on the month.")
    qc = an._resolve_number_handles(quiet, [_call("production", 4.2, country="Brazil")],
                                    handle_prose=True)
    assert qc["geo_checked"] == 1 and qc["geo_mismatch"] == 0


def test_v2_is_absent_not_null_when_nothing_fired():
    """THE SAME LAW ON THE [E] HALF: the census is ZERO-VALUED on a turn that convicted nothing, so the
    caller's `any(values)` stamp writes NO key -- absent, never null, on control and on a quiet
    treatment run alike."""
    st = _st("Output tightened the balance [E1].")
    census = an._drop_evidence_geo_contradiction(st, [_ev("Crushers lifted throughput.")])
    assert not any(census.values())
    assert an._drop_evidence_geo_contradiction(None, []) == {"convicted": 0, "handles_dropped": 0,
                                                             "sentences_dropped": 0}


# ══ (xi) THE RECORDED RESIDUAL -- GROUPED TOKENS ARE NOT COVERED, AND THAT IS MEASURED ════════════════

def test_the_grouped_token_residual_is_a_guard_and_is_recorded_as_one():
    """M-0(b)'s VERDICT, DISCHARGED AS A TEST RATHER THAN AS A SENTENCE. The census measured grouped
    tokens at 0% of resolved handles on r6 and 5.07% on r4+d2, both under the pre-registered 10% bar, so
    THE SOLITARY-ONLY GUARD STANDS and grouped is a RECORDED RESIDUAL -- named with its number, not
    quietly dropped (plan 10.30.7's M-0 descope rule).

    THIS IS A PASSING TEST THAT ASSERTS THE GUARD, deliberately, rather than an xfail asserting the gap:
    an xfail would go green the day someone widens the guard without re-reading the descope rule, which
    is precisely the edit that must not happen silently. If the guard is ever widened, THIS TEST IS THE
    THING THAT MUST BE EDITED, and editing it forces reading this note."""
    st = _st("Indonesian output reached [N1, N2] on the month.")
    census = an._resolve_number_handles(
        st, [_call("production", 4.2, country="Brazil"), _call("production", 4.3, country="Brazil")],
        handle_prose=True)
    assert census["geo_checked"] == 0 and census["geo_mismatch"] == 0   # NOT compared: grouped
    # ...and the [E] half's own solitary-only guard, same residual, same reason
    st2 = _st("Indonesian output tightened the balance [E1, E2].")
    assert an._drop_evidence_geo_contradiction(
        st2, [_ev("Brazilian crushers lifted throughput."),
              _ev("Brazilian crushers lifted throughput.")])["convicted"] == 0
