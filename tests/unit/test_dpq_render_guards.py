"""D-PQ render guards -- the five DETERMINISTIC fixes cut from the WIRED-v3 dcw/dpq probe rows
(baseline_dcw_probe_v1 / baseline_dpq_probe_v1, 2026-08-07).

Every pin here is on CODE or CARD state, never on model wording: each one fails on an input the probe
actually produced and passes on the input the fix produces. In order:

  HANDLE-1  a literal `[N]` token must never reach the reader (`dcw_us_ethanol_margin` shipped nine)
  EMPTY-1   an empty read must never render, or offer, an asserted zero (`dcw_esr_china_corn`)
  CLASS-1   a card's commodity set is a CLOSED set enforced at spec level (`dcw_nass_conditions_split`,
            and the two prose-fence leaks before it)
  PIN-1     `expiry_labeled` must be able to read TRUE when the fact is true (`dpq_cbot_corn_front_settle`)
  CAP-1     absence bullets are capped and are never a majority of an Episodes section
            (`dcw_full_record_range`: 20 of 24 bullets said nothing)

Pure -- no AWS, no LLM, no network. The registry is read (tables.yaml is tracked).
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import registry as nreg


# ══ HANDLE-1: the [N] namespace render ═══════════════════════════════════════════════════════════════
def _call(value, *, table="silver_wasde", metric="ending_stocks", unit="mil bu", status="ok"):
    rows = [] if value is None else [{"value": value, "unit": unit, "knowledge_date": "2026-07-10"}]
    return {"query": {"table": table, "metric": metric, "commodity": "corn_cbot", "asof": "2026-08-07"},
            "rows": rows, "status": status}


def test_resolved_handle_standing_in_for_the_value_gets_the_value_spliced():
    """The measured shape: '... stands at [N5] against total use of [N4]' -- both rows resolved, both
    handles standing where a figure belongs. The value AND its unit are spliced in front of the handle,
    which stays: the citation is not what was broken."""
    st = {"tldr": "", "mechanism": "The MY2025/26 ending stocks projection stands at [N1] against "
                                   "total use of [N2] [known 2026-07-10]."}
    census = an._resolve_number_handles(st, [_call(51.31), _call(336.69)])
    assert "51.31 mil bu [N1]" in st["mechanism"]
    assert "336.69 mil bu [N2]" in st["mechanism"]
    assert census["substituted"] == 2 and census["unresolvable"] == 0
    assert "[N" in st["mechanism"]                       # the handles are KEPT -- only the gap was filled


def test_resolved_handle_beside_a_stated_number_is_untouched():
    """The ordinary citation shape. Moving it would rewrite every correct answer in the estate."""
    mech = "The December 2026 contract settled at 446 US cents per bushel [N1], known as of 2026-06-05."
    st = {"tldr": "", "mechanism": mech}
    census = an._resolve_number_handles(st, [_call(446.0, table="silver_futures_eod", metric="settle",
                                                   unit="US cents/bushel")])
    assert st["mechanism"] == mech
    assert census == {"substituted": 0, "handles_dropped": 0, "sentences_dropped": 0, "unresolvable": 0}


def test_unresolvable_handle_standing_in_for_the_value_drops_the_whole_sentence():
    """`dcw_us_ethanol_margin` verbatim: [N16] pointed at a cascade row that came back EMPTY, the
    sentence stated no figure of its own, and both verifier number rules therefore passed vacuously.
    There is nothing to substitute, so the sentence goes -- and NOTHING literal survives."""
    st = {"tldr": "", "mechanism": ("Ethanol absorbs a third of the crop. U.S. total domestic corn "
                                    "consumption stands at [N2] for MY2025. Demand growth is the "
                                    "backdrop.")}
    census = an._resolve_number_handles(st, [_call(3.15), _call(None, status="no_rows")])
    assert "[N" not in st["mechanism"]
    assert "stands at" not in st["mechanism"]
    assert "Ethanol absorbs a third of the crop." in st["mechanism"]
    assert "Demand growth is the backdrop." in st["mechanism"]
    assert census["sentences_dropped"] == 1 and census["unresolvable"] == 1


def test_an_abbreviation_ending_a_sentence_does_not_widen_the_kill_into_it():
    """CYCLE-3 BLOCKER 1. The abbreviation clause skipped EVERY initialism dot, so a sentence that
    legitimately ENDS on one ('...from the U.S.') was glued to the next, and one empty handle in the
    widened span deleted both -- the whole field, with census sentences_dropped:1. Only the sentence that
    made the unbackable promise may go."""
    st = {"tldr": "", "mechanism": "Exports were strong from the U.S. The December contract settled at [N9]."}
    census = an._resolve_number_handles(st, [_call(None, status="no_rows")] * 9)
    assert st["mechanism"] == "Exports were strong from the U.S."
    assert census["sentences_dropped"] == 1 and census["unresolvable"] == 1


def test_the_abbreviation_clause_still_holds_mid_sentence():
    """The other half of the same ambiguity, unmoved: 'U.S.' FOLLOWED BY A LOWER-CASE WORD is mid-sentence,
    so the kill must start at 'U.S.' and never leave it glued to the survivor."""
    st = {"tldr": "", "mechanism": "U.S. total domestic corn consumption stands at [N1] for MY2025. It grew."}
    an._resolve_number_handles(st, [_call(None, status="no_rows")])
    assert st["mechanism"] == "It grew."


def test_a_drop_never_crosses_a_line_boundary():
    """The outer fence on the same failure: an abbreviation at end-of-line cannot pull the next line's
    bullet into the kill."""
    st = {"tldr": "", "mechanism": "- Shipments cleared the U.S.\n- The nearby contract settled at [N1]."}
    an._resolve_number_handles(st, [_call(None, status="no_rows")])
    assert st["mechanism"] == "- Shipments cleared the U.S.\n"


def test_a_mixed_sentence_severs_the_empty_clause_and_keeps_the_backed_content():
    """CYCLE-3 BLOCKER 2. [N2] is backed and stands beside a stated figure; [N4] is unresolvable and stands
    where a figure belongs. Killing the sentence destroyed VERIFIED content to remove one empty promise, so
    only the promise's own clause goes."""
    st = {"tldr": "", "mechanism": "Ending stocks were 1,200 [N2] against use of [N4]."}
    census = an._resolve_number_handles(st, [_call(51.31), _call(1200.0), _call(51.31),
                                             _call(None, status="no_rows")])
    assert st["mechanism"] == "Ending stocks were 1,200 [N2]."
    assert census["sentences_dropped"] == 0
    assert census["handles_dropped"] == 1 and census["unresolvable"] == 1


def test_a_mixed_sentence_with_no_connective_severs_the_value_cue():
    """No clause opener to cut at -> the fallback is the value cue the handle stands behind, so the
    remainder is still prose ('... were 1,200 [N2] at.' would not be)."""
    st = {"tldr": "", "mechanism": "Ending stocks were 1,200 [N2] at [N4]."}
    an._resolve_number_handles(st, [_call(51.31), _call(1200.0), _call(51.31),
                                    _call(None, status="no_rows")])
    assert st["mechanism"] == "Ending stocks were 1,200 [N2]."


def test_an_unbacked_sentence_is_still_killed_whole():
    """The severance is fenced to the MIXED case: with no resolved handle in the sentence there is nothing
    to keep and the original whole-sentence law stands."""
    st = {"tldr": "", "mechanism": "Stocks stand firm. Ending stocks were [N3] against use of [N4]."}
    census = an._resolve_number_handles(st, [_call(51.31), _call(51.31), _call(None, status="no_rows"),
                                             _call(None, status="no_rows")])
    assert st["mechanism"] == "Stocks stand firm."
    assert census["sentences_dropped"] == 1 and census["unresolvable"] == 2


def test_an_orphaned_number_ref_is_pruned_from_the_sources_block():
    """CYCLE-3 BLOCKER 2, second half. `_cited_sources_block` reads structured['sources'], which the handle
    guard never touches -- so a handle whose sentence was dropped kept a `## Sources` row pointing at
    nothing the reader can find. The surviving handle keeps its row; the departed one does not."""
    st = {"tldr": "", "mechanism": "Ending stocks were 1,200 [N2] against use of [N4].",
          "sources": [{"ref": "N2"}, {"ref": "N4"}]}
    an._resolve_number_handles(st, [_call(51.31), _call(1200.0), _call(51.31),
                                    _call(None, status="no_rows")])
    block = an._cited_sources_block(st, {"resolved": {}},
                                    [_call(51.31), _call(1200.0), _call(51.31),
                                     _call(None, status="no_rows")])
    assert "[N2] " in block and "[N4]" not in block
    assert st["sources"] == [{"ref": "N2"}, {"ref": "N4"}]      # machine-side rows are NOT rewritten


def test_out_of_range_handle_beside_a_stated_number_drops_only_the_handle():
    """verify's own remedy for index_out_of_range, applied where the verifier could not see it: the
    number already answered for itself, so only the token that points nowhere is removed."""
    st = {"tldr": "", "mechanism": "Farm price fell to $1.94/bu [N9] in MY1998/99."}
    census = an._resolve_number_handles(st, [_call(51.31)])
    assert "[N9]" not in st["mechanism"] and "$1.94/bu" in st["mechanism"]
    assert census["handles_dropped"] == 1 and census["sentences_dropped"] == 0


def test_tldr_is_covered_too_and_a_clean_draft_is_byte_identical():
    st = {"tldr": "Urea sits near its five-year average.", "mechanism": "No handles here at all."}
    before = dict(st)
    census = an._resolve_number_handles(st, [_call(453.1)])
    assert st == before and sum(census.values()) == 0


def test_the_full_measured_paragraph_leaves_no_literal_and_keeps_the_backed_prose():
    """The `dcw_us_ethanol_margin` '## The record' paragraph, end to end. TWO unbackable sentences go,
    FOUR resolved handles get their figure, and the abbreviation clause keeps 'U.S.' from being cut in
    half (the naive boundary cut after 'U.' and left the drop starting mid-clause)."""
    mech = ("U.S. total domestic corn consumption stands at [N6] for MY2025. For context, U.S. "
            "consumption was [N7] in MY1997, a change of [N8]. The structural expansion is documented.\n\n"
            "The MY2025/26 ending stocks projection stands at [N2] against total use of [N1]. On current "
            "futures, the September contract settled at [N3] and the December contract at [N4].")
    st = {"tldr": "", "mechanism": mech}
    census = an._resolve_number_handles(st, [
        _call(336.69), _call(51.31),
        _call(449.25, table="silver_futures_eod", metric="settle", unit="US cents/bushel"),
        _call(472.5, table="silver_futures_eod", metric="settle", unit="US cents/bushel"),
        _call(3.15), _call(None, status="no_rows"), _call(None, status="no_rows"),
        _call(None, status="no_rows")])
    assert census == {"substituted": 4, "handles_dropped": 0, "sentences_dropped": 2, "unresolvable": 3}
    import re as _re
    out = st["mechanism"]
    survivors = list(_re.finditer(r"\[N\d+\]", out))
    assert len(survivors) == 4
    for m in survivors:                                  # every survivor carries its figure in front of it
        assert _re.search(r"\d", out[max(0, m.start() - 30):m.start()]), out[:m.start()][-40:]
    assert "U.S. total domestic corn consumption stands at" not in st["mechanism"]
    assert "U.S. consumption was" not in st["mechanism"]
    assert st["mechanism"].startswith("The structural expansion is documented.")
    assert "stands at 51.31 mil bu [N2] against total use of 336.69 mil bu [N1]" in st["mechanism"]
    assert "settled at 449.25 US cents/bushel [N3]" in st["mechanism"]


def test_the_guard_never_raises_on_a_malformed_call_record():
    st = {"tldr": "", "mechanism": "The reading is [N1]."}
    an._resolve_number_handles(st, [{"not": "a call"}])      # no query, no rows, no status
    assert "[N1]" not in st["mechanism"]                     # unresolvable -> the sentence goes


def test_the_guard_is_gated_on_the_verifier_in_both_bodies():
    """`GRAPHRAG_VERIFY=off` is the documented rollback for the whole citation-truth chain (it also
    selects the legacy two-list footer). This pass is that chain's LAST leg, so it rolls back with it --
    otherwise a flag-off turn has its prose deleted by a guard nobody asked to run. Asserted on the
    SOURCE because the alternative is an end-to-end turn, and this is a one-line invariant."""
    import pathlib
    src = pathlib.Path(an.__file__).read_text(encoding="utf-8")
    assert src.count('if verifier.get("enabled"):\n        sg.trace["number_handles"]') == 1
    assert 'if verifier.get("enabled") else None)' in src


def test_both_synthesis_bodies_call_the_guard_and_the_key_is_registered():
    """The seam itself, asserted on the SOURCE so a refactor that drops one body is loud. Placement is
    load-bearing: after verify_citations (only survivors are seen) and before _humanize_structured
    (a spliced figure rides the same sanitize as the rest of the prose)."""
    import pathlib
    src = pathlib.Path(an.__file__).read_text(encoding="utf-8")
    assert src.count("_resolve_number_handles(structured, extra_number_calls)") == 2
    from leviathan.graphrag import tracekeys as tk
    assert "number_handles" in tk.TRACE_RECORD_KEYS


# ══ EMPTY-1: an empty read is an absence of data, never a measured zero ══════════════════════════════
@pytest.mark.parametrize("status", ["no_rows", "not_known", "error", "declined", "record_silent", None])
def test_empty_read_label_carries_the_marker_and_no_value_or_unit(status):
    """THE PIN THE ESR ROW ASKED FOR: an empty read renders no numeric value anywhere in extras or
    labels. `= 0 1000 MT` and its bare-unit cousin `= (...) 1000 MT` are both unreachable."""
    call = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                      "country": "China", "period": "2025", "asof": "2026-08-07"},
            "rows": [], **({"status": status} if status else {})}
    c = cit.from_number(call, 1)
    assert c.label.split(" = ", 1)[1].startswith("NO ROWS RETURNED")
    assert c.value is None and c.unit is None
    assert "1000 MT" not in c.label.split(" = ", 1)[1]        # the unit is not offered without a value


def test_empty_read_stamps_the_no_rows_scope_note_taxonomy():
    for status, why in (("no_rows", "scope/coverage gap"), ("not_known", "not yet published"),
                        ("error", "the lookup failed")):
        note = na._no_rows_note(status)
        assert note.startswith("NO ROWS RETURNED (") and why in note
        assert "not zero" in note.lower() and "never a measured value of 0" in note


def test_zero_esr_aggregate_is_detected_and_caveated():
    """The `0.0 thousand MT (0 MT)` class. `_agg` collapses the week rows, so 'every week reported zero'
    and 'no week was reported' arrive as the SAME single row -- the caveat says so and forbids the
    'no purchases' editorial the probe shipped."""
    zero = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "sum"},
            "rows": [{"value": 0.0}], "status": "ok"}
    assert na._is_zero_esr_aggregate(zero) is True
    note = na._ESR_ZERO_AGG_NOTE.format(metric="weekly_exports_1000mt")
    assert "no purchases" in note and "measured quantity of zero" in note


@pytest.mark.parametrize("payload", [
    {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "sum"},
     "rows": [{"value": 12.0}]},
    {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "latest"},
     "rows": [{"value": 0.0}]},
    {"query": {"table": "silver_pink_sheet", "metric": "m", "agg": "sum"}, "rows": [{"value": 0.0}]},
    {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "sum"}, "rows": []},
    # CYCLE-3 BLOCKER 3: `_exec` drops NULL rows BEFORE this check, so a 0.0 arriving here always means
    # real rows summed to zero. A SIGNED metric cancels to zero on a busy window (bookings vs
    # cancellations) -- a measured net, never an absence -- and mean/max/min zeros are real observations
    # of the rows that came back, not the row-collapse the note describes.
    {"query": {"table": "silver_esr", "metric": "changes_1000mt", "agg": "sum"},
     "rows": [{"value": 0.0}]},
    {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "mean"},
     "rows": [{"value": 0.0}]},
    {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "max"},
     "rows": [{"value": 0.0}]},
    {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "min"},
     "rows": [{"value": 0.0}]},
])
def test_zero_aggregate_caveat_is_fenced_to_the_class_it_names(payload):
    """A 0.0 z-score, a 0 basis, a 0 change on any other card is a real observation. Not caveated."""
    assert na._is_zero_esr_aggregate(payload) is False


@pytest.mark.parametrize("metric", ["weekly_exports_1000mt", "outstanding_sales_1000mt",
                                    "gross_new_sales_1000mt"])
def test_every_unsigned_esr_metric_keeps_the_zero_sum_caveat(metric):
    """The named set is the card's own metric ids minus the one signed metric, and each is a quantity that
    cannot go negative -- so a sum of exactly 0 is still the indistinguishable state the note is about."""
    assert na._is_zero_esr_aggregate(
        {"query": {"table": "silver_esr", "metric": metric, "agg": "sum"},
         "rows": [{"value": 0.0}], "status": "ok"}) is True


def test_the_unsigned_set_is_the_cards_metrics_minus_the_signed_one():
    """The card expresses unit and description but no signedness, so the set lives in code -- pinned
    against the card here so a new ESR metric cannot be added to one and silently missed by the other."""
    card = set(nreg.load_registry().get("silver_esr").metrics)
    assert set(na._ESR_UNSIGNED_METRICS) | {"changes_1000mt"} == card


def test_numbers_panel_forbids_asserting_a_number_for_an_empty_read():
    """The HYBRID half: this lane shows the model only the citation labels, so the DIRECTIVE has to ride
    the prompt panel. Absent when every read returned rows -> the block is byte-identical."""
    empty = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot"},
             "rows": [], "status": "no_rows"}
    full = {"query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "corn_cbot"},
            "rows": [{"value": 51.31, "unit": "mil bu"}], "status": "ok"}
    block = orch._numbers_block([empty])
    assert "NO ROWS RETURNED" in block and "not zero" in block
    assert "SCOPE NOTE" in block
    assert "NO ROWS RETURNED" not in orch._numbers_block([full])


# ══ CLASS-1: the card's commodity set is a CLOSED set, enforced at spec level ════════════════════════
_NASS = "silver_nass_crop_progress"
_NASS_SLUGS = ("corn_cbot", "soybeans_cbot", "rough_rice_cbot", "cotton",
               "soft_red_winter_wheat_cbot", "hard_red_spring_wheat_mgex")


def test_the_card_declares_its_six_slugs():
    assert list(nreg.load_registry().get(_NASS).commodity_values) == list(_NASS_SLUGS)


def test_the_declared_set_and_the_teaching_notes_agree():
    """The yaml says the same fact twice on purpose -- `notes` teaches, `commodity_values` enforces.
    A slug added to one and not the other is exactly how a prose fence rots into a lie."""
    spec = nreg.load_registry().get(_NASS)
    for slug in spec.commodity_values:
        assert slug in spec.notes, f"{slug} is enforced but not taught in the card's notes"


class _Spec:
    def __init__(self, table, commodity):
        self.table, self.commodity = table, commodity


@pytest.mark.parametrize("slug", _NASS_SLUGS)
def test_every_declared_slug_passes_the_fence(slug):
    na._check_commodity_class(_Spec(_NASS, slug), nreg.load_registry())      # must not raise


@pytest.mark.parametrize("slug", ["french_wheat", "milling_wheat_matif", "corn", "barley", "durum",
                                  "wheat_zce", "sorghum"])
def test_a_commodity_off_the_card_is_refused_before_any_sql(slug):
    """v2 leaked french_wheat, v3 leaked across contracts. Membership is what IS decidable here, and it
    is decided at spec level -- nothing is queried and the message is the remedy."""
    with pytest.raises(na.CommodityOffCard) as e:
        na._check_commodity_class(_Spec(_NASS, slug), nreg.load_registry())
    msg = str(e.value)
    assert "lookup REFUSED" in msg and slug in msg and "Nothing was queried." in msg
    for s in _NASS_SLUGS:
        assert s in msg                                   # the legal values, enumerated for the repair


def test_the_refusal_message_reaches_the_model_untruncated():
    """`_spec_error` truncates a raw exception to 200 chars. This one must not be: the remedy IS the
    message, and the enumeration of six slugs is longer than that."""
    exc = na.CommodityOffCard("x" * 400)
    assert len(na._spec_error({"table": _NASS, "metric": "pct_good_excellent"}, exc,
                              nreg.load_registry())) == 400


def test_a_card_with_no_declaration_is_unfenced():
    """EMPTY commodity_values (every card but NASS today) -> no fence, byte-identical behaviour."""
    reg = nreg.load_registry()
    for tid, spec in reg.tables.items():
        if tid == _NASS or not spec.commodity_col:
            continue
        na._check_commodity_class(_Spec(tid, "anything_at_all"), reg)        # must not raise


# ══ PIN-1: expiry_labeled must be able to read TRUE when the fact is true ════════════════════════════
def _eod_out(prose, months=("2026-12",)):
    return {"structured": {"tldr": "", "mechanism": prose},
            "number_calls": [{"query": {"table": "silver_futures_eod", "contract_month": m},
                              "rows": [{"value": 446.0, "contract_month": m, "data_date": "2026-06-05"}]}
                             for m in months]}


@pytest.mark.parametrize("prose", [
    "The December 2026 CBOT corn contract settled at 446 US cents per bushel.",
    "The nearby December 2026 CBOT corn contract settled at 446.",
    "The December 2026 CME corn futures settled at 446.",
    "The December 2026 corn contract settled at 446.",          # the pre-fix form, still true
    "The December 2026 delivery settled at 446.",
])
def test_expiry_labeled_reads_true_on_the_house_style(prose):
    """dpq_cbot_corn_front_settle named its expiry FOUR times against a served 2026-12 row and the pin
    read False: the cue had to follow the year IMMEDIATELY and the house style puts the EXCHANGE in
    between. A pin that cannot read true on a true fact is broken, not strict."""
    hard, bare, soft = ev._expiry_tokens(prose)
    assert "2026-12" in (hard | soft), f"no delivery-month label recovered from: {prose}"
    got = ev._cascade_asserts({"expect": {"expiry_labeled": True}, "asof": "2026-06-08"}, _eod_out(prose))
    assert got["expiry_labeled"] is True


def test_the_exchange_slot_needs_a_year_so_the_false_branch_is_unmoved():
    """`bare` (yearless) is what the anti-invention `false` branch reads. The widening is confined to
    the year-carrying `soft` set, which is read only on the branch that can CREDIT -- so a yearless
    month plus an exchange token still mints nothing and can convict nobody."""
    hard, bare, soft = ev._expiry_tokens("The December CBOT board was quiet.")
    assert not hard and not soft and not bare
    hard, bare, soft = ev._expiry_tokens("The December contract was quiet.")
    assert bare == {12} and not hard and not soft            # the legacy yearless form, unchanged


def test_a_calendar_date_is_still_not_an_expiry():
    """'in June 2012 the continuous close was 738.50' has 'the' in the cue slot: adjacency holds."""
    hard, bare, soft = ev._expiry_tokens("In June 2012 the continuous close was 738.50.")
    assert not hard and not soft and not bare


# ══ CAP-1: absence bullets are capped, and are never a majority ══════════════════════════════════════
_ABSENCE = "no citable item in this window, so what happened is not narrated; no price record for this window."


def _section(n_present, n_absent):
    out = ["## Mechanism", "Frost tightens the sheet.", "", "## Episodes"]
    for i in range(n_present):
        out.append(f"- 20{10 + i:02d}-01..20{10 + i:02d}-06 -- CBOT corn: a dated item [E{i + 1}] recorded it.")
    for i in range(n_absent):
        out.append(f"- 19{70 + i:02d}-01..19{70 + i:02d}-06 -- CBOT corn: {_ABSENCE}")
    out += ["", "## What to watch", "- July weather."]
    return "\n".join(out)


def test_the_probe_shape_is_bounded_by_the_majority_rule():
    """`dcw_full_record_range` verbatim: 24 bullets, 4 receipted, 20 absence. min(max_absence=6,
    present=4) = 4, so the section lands at 8 bullets and absence is exactly half -- not a majority."""
    mech, dropped = an._cap_absence_bullets(_section(4, 20), max_absence=6)
    bullets = [ln for ln in mech.split("\n") if ln.startswith("- 1") or ln.startswith("- 2")]
    assert dropped == 16 and len(bullets) == 8
    assert sum(1 for b in bullets if an._is_absence_bullet(b)) == 4
    assert "## What to watch" in mech and "- July weather." in mech      # nothing else is disturbed


def test_the_hard_cap_binds_when_the_majority_rule_does_not():
    mech, dropped = an._cap_absence_bullets(_section(20, 9), max_absence=6)
    assert dropped == 3
    assert sum(1 for ln in mech.split("\n") if an._is_absence_bullet(ln)) == 6


def test_the_floor_keeps_a_sparse_section_at_the_decks_minimum():
    """CYCLE-3 BLOCKER 4, RE-PINNED. `min(max_absence, present)` alone STARVES a sparse answer: one
    receipted window kept exactly ONE absence bullet -- a two-bullet '## Episodes' section, under the
    decks' own `min_episode_lines: 3`, so the cap that was meant to raise quality reded the pin instead.
    The majority rule is now a CEILING over a floor of three."""
    mech, dropped = an._cap_absence_bullets(_section(1, 8), max_absence=6)
    bullets = [ln for ln in mech.split("\n") if ln.startswith("- 1") or ln.startswith("- 2")]
    assert dropped == 5 and len(bullets) == 4                    # 1 present + 3 absence
    assert sum(1 for b in bullets if an._is_absence_bullet(b)) == 3


def test_more_present_content_never_yields_a_smaller_section():
    """The other half of the same defect: the old law was NON-MONOTONIC (present=0 kept `max_absence`,
    present=1 kept one), so ADDING receipted content could shrink the section. `keep` is now
    non-decreasing in `present` by construction, and this walks it."""
    keeps = [sum(1 for ln in an._cap_absence_bullets(_section(p, 8), max_absence=6)[0].split("\n")
                 if an._is_absence_bullet(ln)) for p in range(1, 9)]
    assert keeps == sorted(keeps), keeps
    assert keeps[0] == 3 and keeps[-1] == 6                      # floored at 3, still ceilinged at 6


def test_a_compliant_section_is_byte_identical():
    src = _section(6, 3)
    mech, dropped = an._cap_absence_bullets(src, max_absence=6)
    assert dropped == 0 and mech == src


def test_a_receipted_bullet_that_merely_quotes_an_absence_is_not_culled():
    """The false-absence-through-the-corpus class: a bullet WITH a receipt whose restated source text
    says 'the record is silent on X' is a real bullet. The `[E` clause is what separates them."""
    line = "- 2021-01..2021-06 -- CBOT corn: the dated item [E3] recorded that the record is silent on yields."
    assert an._is_absence_bullet(line) is False
    assert an._is_absence_bullet(f"- 2021-01..2021-06 -- CBOT corn: {_ABSENCE}") is True


def test_no_episodes_section_means_no_edit():
    src = "## Mechanism\n- a bullet with no citable item in this window at all\n## What to watch\n- x"
    mech, dropped = an._cap_absence_bullets(src, max_absence=0)
    assert dropped == 0 and mech == src


def test_the_no_receipt_vocabulary_matches_the_scorer():
    """The `_SECTION_KINDS` idiom: answer cannot import eval, so the tuple is mirrored and pinned equal.
    Vocabulary drift fails here rather than reaching production as a silent fork."""
    assert set(an._SCAFFOLD_NO_RECEIPT_MARKERS) == set(ev._NO_CITABLE)


def test_the_model_authored_branch_now_applies_the_cap(monkeypatch):
    """THE BUG ITSELF: D-RC-11's caps lived inside the SYNTHESIS branch, and this shape returns from the
    model-authored branch at the top of the function -- so the knob existed and the section walked past
    it. The stamp reports the drop; `episodes_model_authored` stays True."""
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    st = {"tldr": "", "mechanism": _section(4, 20),
          "sources": [{"ref": 1, "source": "usda_gain", "date": "2021-07-20"}]}
    trace = an._maybe_scaffold_episodes(
        st, {"enabled": True, "resolved": {}},
        injected=[{"node": "drivers/frost", "spans": ["2021-01..2021-06"]}], nodes=[],
        evidence=[], n_positional=1, market_register="fenced", relevant=True)
    assert trace["episodes_model_authored"] is True
    assert trace["episodes_scaffolded"]["n_absence_capped"] == 16
    assert len([ln for ln in st["mechanism"].split("\n")
                if ln.startswith("- 1") or ln.startswith("- 2")]) == 8
