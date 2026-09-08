"""SCAN RUNG 3 -- THE HEADLINE ROSTER: the Scan tier's numbers leg with the MODEL TAKEN OUT.

DESIGN OF RECORD: `docs/private/SCAN_RUNG3_ROSTER_DESIGN.md` (sections 1.1-1.6 for the roster itself,
section 2 for the zero-rounds decision, sections 12 and 13 for the two S2 probes that corrected it).
DARK AT BIRTH behind `GRAPHRAG_NUMBERS_ROSTER`, read ONCE in `orchestrator.run_hybrid` and carried as
`_nr`; nothing in this module reads an environment variable and nothing here reads a clock.

THE MEASURED TRIGGER, and it is the whole reason this file exists (design sections 0 and 1.1, the
25-turn Scan census over `scan_arm_*.json`):
  * M-2 -- the numbers leg is ~100% MODEL time. Per turn, `timing_ms.numbers` MINUS that turn's own
    summed API-call seconds is -0.05 to +0.21 s, p50 0.07 s, across 1 to 38 lookups. `rv_corn_sorghum`
    spent 0.1 s EXECUTING 35 lookups and 89.6 s planning them.
  * M-3 -- one agent round costs more than this design's whole modelled turn: first-round p50 29.1 s,
    out p50 3,659 tokens, 3 of 25 turns stopped on `max_tokens`.
  * 1.1 -- and what all that planning rediscovers every turn is a set of THREE CARDS. `tables_queried`
    over 15 banked rows names EIGHT tables out of the registry's 41 -- silver_psd 12/15,
    silver_psd_attributes 8/15, silver_wasde 7/15, silver_mpob 5/15, silver_pink_sheet 5/15,
    silver_mpoc_stock_comparison 3/15, silver_futures_eod 3/15, gold_board_crush 2/15 -- with
    distinct tables per turn of 1-5 and a p50 of 3.
THE ROSTER IS THAT SET, WRITTEN DOWN. It pays zero model tokens and issues 6-8 reads per routed leg
(measured below, and one over design 1.2's five -- see READ COUNT).

WHAT IT IS NOT. It is not a planner, it is not a fallback for the agent, and it never guesses a scope
it cannot prove: every branch below either binds a scope from an EXISTING helper or DECLINES with a
written reason of its own (design 1.5, six refusals). Fences here CORRECT or COMPUTE -- they rank the
rows, bind the scope and serve the series -- they never silently drop a figure without saying so, and
every decline lands in `numbers_budget['roster_declines']` where the arm can count it.

THE ARM NEEDS BOTH FLAGS, and that is worth one line here because the lane is invisible without the
second (review minor, measured): `GRAPHRAG_NUMBERS_ROSTER=on` runs the roster, but with
`GRAPHRAG_NUMBERS_BUDGET_NOTE` off `run_hybrid` threads `_nb = None`, `numbers_budget` is ABSENT from
the trace, and `roster_declines` / `roster_form` / `roster_ms` -- this lane's whole observation surface
-- are unreadable. Correct per the two-flag doctrine; it just means the arm recipe sets BOTH.

READ COUNT, MEASURED ON THIS BUILD (design 1.2 states 5 per leg, 10-16 on the pessimistic pair). Form A
issues FOUR PSD reads (su_ratio at the settled year AND at MY-1 -- the second is what pays for the
year-on-year fence -- production, the trade leg) plus R4 and R5: SIX per leg, one over the design's five,
and form A is a SINGLE-leg form by construction (`scope_form` takes the world branch on any second
balance-eligible leg). Measured offline through the real SQL stack at asof 2026-09-07: form A single leg
6 SQL / 8 call-records; form B two legs 15 SQL / 14 records; a two-leg WASDE pair with R6 firing 16 SQL /
10 records -- inside the design's 10-16 band on both pairs. The one-read overage on form A is a declared
drift and it buys the D-DA fence back (`_balance_primary`).

WHY A NEW MODULE AND NOT `agent.py` OR `derived.py` (design 1.6(5)). `agent.py` IS the model lane this
rung replaces. `derived.py` belongs to D-DA: its `DV_LANE_CAP`, its `DV_FETCH_CAP` and above all its
`DV_RENDER_METRICS` render table (THIRTEEN keys, none of them production, exports/imports, a
pink-sheet level or a year-on-year delta) are that wave's, and `_dv_call` additionally stamps
`country: None` and `table: "derived"` over the served payload -- which would erase the very scope
binding 1.5(c) exists to make. This module therefore imports `derived.su_standing` and
`derived.crush_share` (which mint their own rows on their own declared keys) and NEVER `_dv_call`.

THE ORCHESTRATOR'S SCOPE RULING ON THIS SITTING, RECORDED VERBATIM AS IT WAS HANDED DOWN (it is the
authority for the four edits this lane made outside its own allowlist, and it lives here so a later
reader finds the ruling beside the code it authorised rather than in a workflow log):

  ORCHESTRATOR'S SCOPE RULING (2026-09-08 21:05Z), record it verbatim in the roster.py module note and
  in the S1 report: the four out-of-allowlist edits the verifier listed are ACCEPTED as forced -- (a)
  apps/terminal/src/store/mode.ts + mode.test.ts: the DARK_TIERS literal must mirror
  reasoning_modes.DARK_NAMES name-for-name because config_check.check_cascade_notch clause (vi) asserts
  the parity, exactly as the Cascade-notch sitting (ff7923d4) did when it added its names; the FE bundle
  is NOT rebuilt (dark names render nothing); (b) check_scan_tier clause (iv) restated from the literal
  KNOB_FIELDS[-1] == "numbers_calls" to an ordinal against synth_effort, because the brief itself orders
  numbers_roster appended last; (c) the tests/unit/test_scan_tier.py:203 shift for the same reason.
  Whoever lands last owns the tail-order assertion, and this sitting landed last.
"""
from __future__ import annotations

import re
import time
from typing import Optional, Sequence

from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import stats as st

# ── THE TWO-SLUG CUT (design section 13, refuter MAJOR-2, MEASURED over all 14 deck rows) ────────────
# `orchestrator`'s `_mc` filters on contract MEMBERSHIP only and returns 4-11 slugs per relative-value
# question (p50 8). At 5-8 reads per slug that is 20-88 reads -- ~125 s sequential at the median on the
# Athena column, i.e. WORSE than the 65 s agent leg this rung replaces. The node-diverse cut to
# `max_contracts=2` lives on the ANSWER path (`answer.py`), not on the hoisted `_mc` block, so the
# roster takes the cut ITSELF or it is a regression. TWO is the routed PAIR: every banked `rv_*` deck
# row is a two-market ask, and design 1.4 runs one independent roster per routed slug in the order the
# router returned them.
ROSTER_CONTRACT_CAP = 2

# ── THE PSD COVERAGE SCREEN (design section 12, MEASURED 2026-09-07, wf_ed579938, 112 Athena reads) ──
# A per-slug census of silver_psd found 63 distinct `leviathan_slug` values and NONE of these three, at
# any country and any period. `corn` and `soybeans` are `graph.py`'s BASE-YAML duplicates of their
# tradeable siblings (loaded, off-hierarchy, node already served by a hierarchy contract) and they are
# reachable through `_mc`, so they arrive here as routed contracts; `cocoa` is a real market in the
# commodity hierarchy whose balance sheet USDA simply does not publish in PSD (silver_psd's own card
# says so: "PSD carries NO cocoa balance sheet at all -- cocoa supply/demand is silver_icco_cocoa").
# SCREENED BY NAME, BEFORE ANY READ, exactly as `cascade._RV_PRICE_ABSENCE` screens the price leg: an
# absence that is KNOWN is a decline with a written reason, never four empty reads and a shrug.
# THIS IS A BALANCE-ROW REFUSAL, NEVER A WHOLE-SLUG ONE -- cocoa IS in `_RV_PRICE_SERIES`, so its R5
# price standing renders while R1-R3 decline (the same shape sunflower_oil takes for a different
# reason).
_ROSTER_PSD_ABSENT: dict[str, str] = {
    "corn": ("USDA PSD publishes no balance sheet under this identifier: it is the base-sheet duplicate "
             "of the traded corn contract, and the balance rows are read on that contract instead"),
    "soybeans": ("USDA PSD publishes no balance sheet under this identifier: it is the base-sheet "
                 "duplicate of the traded soybean contract, and the balance rows are read on that "
                 "contract instead"),
    "cocoa": ("USDA PSD carries no cocoa balance sheet at all -- cocoa supply and demand is published "
              "by the ICCO and held on a different card, so no stocks-to-use, production or trade row "
              "is available from this sheet"),
}

# ── R3: WHICH SIDE OF THE TRADE LEG (design 1.2, the `esr_destination_scope` / `asked_month_window`
# idiom -- ONE compiled matcher, resolved ONCE up front, ambiguity failing toward the default) ───────
# The default is EXPORTS and that is a decision, not an oversight: every banked deck row is an
# origin-side relative-value ask, and PSD's exports column is the one both legs of such a pair carry.
_IMPORT_ASK_RX = re.compile(
    r"\bimport(?:s|ed|ing|er|ers)?\b|\bbuy(?:s|er|ers|ing)?\s+from\b|\bpurchas(?:e|es|ing)\s+from\b"
    r"|\binbound\s+(?:shipments?|cargo(?:es)?)\b|\barrivals?\b")
_EXPORT_ASK_RX = re.compile(
    r"\bexport(?:s|ed|ing|er|ers)?\b|\bship(?:s|ped|ping|ments?)\b|\bsales?\s+abroad\b|\boutbound\b")

# ── THE SCOPE FORM (design 1.3 SCOPE + 1.4; FATAL-3's close, and section 12's inversion of it) ──────
# TWO declared forms and a third branch, never a guess:
#   form A, A NAMED COUNTRY -- `cascade._primary_title(slug)`, which returns silver_psd's OWN surface
#     spelling ('united_states' -> 'United States'), folds EU members to 'European Union', and returns
#     None rather than guessing when no geography primary exists.
#   form B, THE WORLD -- which is a SYNTHESIS and not a country: `cascade._world_su_ratio` /
#     `cascade._world_sum` over each country's own latest vintage <= asof with the EU membership dedup.
#     A literal `country='World'` is NEVER issued.
# WHY THE CASING AND THE SCOPE ARE NOT STYLISTIC, MEASURED over the 25 arm rows' served silver_psd
# reads: `country='United States'` returned ok with rows 42 times while `country='united_states'`
# returned ZERO rows 137 times; `country='World'` returned zero rows 14 times and `'world'` 94 times.
# Section 12 re-measured it on the served table and found the cause: `build_sql` emits the caller's
# country string VERBATIM (silver_psd's country is not a partition column), so only the table surface
# title serves -- single-token 'brazil' 0 rows vs 'Brazil' 67 -- and a MIS-CASED scope is
# indistinguishable from an ABSENT one by STATUS (every casing control returned `not_known`, never
# `error`). ONLY THE ROW COUNT DISCRIMINATES, which is why every emptiness test in this file keys on
# ROWS and never on status.
_WORLD_ASK_RX = re.compile(
    r"\bworld\b|\bglobal(?:ly)?\b|\bworldwide\b|\binternational\b|\ball[- ]origin\b")

# ── 1.5(f): AN UNSETTLED MARKETING YEAR IS REFUSED BY NAME, not quietly answered with another year ──
# THE MEASURED REASON (FATAL-2): over the 25 arm rows the su_ratio periods served include MY2026 at a
# 2026-08-12 knowledge date -- USDA's PROJECTION year -- and `estimate_role` is NULL on all 371
# silver_psd rows served across all five arms, so the row carries no role to declare. `su_standing`
# declares its own projections off silver_wasde's revision stamp (`derived.py`), a field silver_psd has
# not got. The roster therefore serves `_settled_my_ceiling` and ONLY that -- and a question that asked
# about the projection year must be told so rather than handed the previous year under its own label.
# ONE COMPILED MATCHER, RESOLVED ONCE, AMBIGUITY FAILING TOWARD SERVING (the `asked_month_window` law):
# a named marketing year is admitted only when it parses unambiguously, and a bare "this year" is NOT
# a marketing-year token -- it routinely means the settled year in trade prose, so refusing on it would
# decline the roster's most ordinary ask.
_MY_TOKEN_RX = re.compile(r"\bMY\s?((?:19|20)\d{2})\b"
                          r"|\b((?:19|20)\d{2})\s?[/-]\s?(\d{2}|(?:19|20)\d{2})\b", re.I)
_NEW_CROP_RX = re.compile(
    r"\bnew[-\s]crop\b|\bcurrent marketing year\b|\bthis marketing year\b"
    r"|\bupcoming (?:crop|season|marketing year)\b|\bcoming (?:crop|season|marketing year)\b"
    r"|\bnext (?:crop year|season|marketing year)\b|\bprojected balance sheet\b")


def asks_projection_year(question: str, slug: str, asof) -> bool:
    """Does this question ask about a marketing year USDA has not closed? Pure -- two regexes and
    `cascade._covering_my`, which reads no clock. True -> 1.5(f): the balance rows are refused with
    their own written reason and the escalation to the paid tier is the product answer."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    if _NEW_CROP_RX.search(q):
        return True
    cover = cq._covering_my(str(asof)[:10], slug)
    if cover is None:
        return False
    for m in _MY_TOKEN_RX.finditer(q):
        year, second = m.group(1) or m.group(2), m.group(3)
        if second is not None and not _is_my_span(year, second):
            # m6 (fix pass 2026-09-08): the split form is a MARKETING YEAR only when the second half is
            # the SUCCESSOR of the first -- '2026/27', '2026-2027'. Without this test the pattern also
            # matched a bare ISO 'YYYY-MM': '2026-09' parsed as year 2026 and second '09', so a question
            # that merely QUOTED a month at or after the covering year took the 1.5(f) projection
            # refusal on a token that is not a marketing year at all. Narrow, and it failed toward
            # refusing rather than toward serving -- the wrong side of the `asked_month_window` law,
            # which this matcher's own block note cites.
            continue
        try:
            if int(year) >= int(cover):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _is_my_span(first: str, second: str) -> bool:
    """Is `first/second` a marketing-year span -- i.e. is `second` the year AFTER `first`? Accepts both
    spellings the trade uses ('2026/27' and '2026/2027'). Pure; never raises."""
    try:
        y, nxt = int(first), int(second)
    except (TypeError, ValueError):
        return False
    return nxt == (y + 1) or (len(str(second)) == 2 and nxt == (y + 1) % 100)


# ── THE ROSTER'S OWN TABLE CONSTANTS -- names, never a second copy of a card's contents ─────────────
_PSD = "silver_psd"
_SU = "su_ratio"
_PRODUCTION = "production_mt"
_EXPORTS = "exports_mt"
_IMPORTS = "imports_mt"
# R4's decline row, named once because TWO producers key on it: `_ABSENCE_ROWS` (what the absence
# sentence calls the missing row) and `_decline_label` (which reader name that sentence names the leg
# by -- a BOARD-level absence names a BOARD, never a world aggregate).
_BOARD_ROW = "settle"

# A minted row is a SYNTHETIC call-record, so its `commodity` field is a READER LABEL and never the raw
# contract slug -- `register.internal_leaks` charges a raw slug in reader prose, and `cascade._rv_call`'s
# own note records that pin firing twice.


def _num(v) -> Optional[float]:
    """A float from a served cell, or None. Commas stripped (Athena hands back formatted strings on
    some cards); never raises, because a roster row that cannot be read is a DECLINE and not a crash."""
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _shown_row(rec: Optional[dict]) -> dict:
    """THE ROW THIS RECORD'S `[N]` LABEL ACTUALLY PRINTS: `max(rows, key=citations._row_order_key)` --
    the SAME expression `citations.from_number` evaluates (citations.py:1341-1349) -- computed here
    UNCONDITIONALLY, so the roster's own arithmetic and the label that renders it cannot disagree about
    which observation was shown.

    NOT `cascade._headline_row`, AND THAT IS THE WHOLE OF THIS FUNCTION (fix pass 2026-09-08, review
    FATAL-1). That helper is KILL-SWITCHED on the module global `cascade._HEADLINE_ON`
    (cascade.py:1811), which is False by default and is written by `quantify()`'s `headline` kwarg ON
    THE CALLING THREAD -- while this module runs on the numbers POOL thread. Its own block note states
    the invariant that arrangement relies on ("Every fetch runs on the pool BEFORE any formatter, so no
    worker thread ever reads it"), and this lane breaks it: a roster turn reads the flag from a worker.
    Two consequences, both measured on a 60-row ASC pink-sheet window rising 800 -> 1,390:
      * WITH THE FLAG OFF (the default) `_headline_row` returns `rows[0]` -- the OLDEST month of the
        window -- while the served level row renders `max(rows, ...)`, the newest. The block handed to
        the writer read `= 1,390 USD/mt` beside `0.8 percentile` and `-1.7 sigma`, when the true
        standing of that level is the 100th percentile and +1.7 sigma. A SIGN-INVERTED price standing,
        labelled as this contract's.
      * AND IT IS A RACE: serving submissions carry `GRAPHRAG_CASCADE_HEADLINE=on`, so a COLD worker's
        first roster turn read False and a WARM one read True -- the same question, two different
        percentile and sigma figures, on the one lane whose entire claim is determinism.
    `cascade._endpoint_row` is the sibling that already took this decision for the synthetic-vintage
    stamp ("The ordering rule is `_headline_row`'s ... applied UNCONDITIONALLY here"); this is that
    same reading, taken at the citation side's own tie-break so the two never differ by a tie."""
    rows = _rows(rec)
    if not rows:
        return {}
    try:
        from leviathan.graphrag.citations import _row_order_key
        return max(rows, key=_row_order_key) or {}
    except Exception:  # noqa: BLE001 -- an unorderable row set degrades to the NEWEST-as-fetched row
        return rows[-1] or {}       # ASC total order (fetch_window's default) -> the freshest print


def _rows(rec: Optional[dict]) -> list:
    return list((rec or {}).get("rows") or [])


def _served(rec: Optional[dict]) -> bool:
    """Did this read actually serve? KEYED ON ROWS, NEVER ON STATUS (design section 12's casing law:
    a mis-cased or absent scope both return `not_known` with zero rows, so only the row count
    discriminates -- and 1.5(d) forbids reading an empty card as a zero)."""
    return bool(_rows(rec))


def _card_unit(reg, table: str, metric: str, slug: Optional[str] = None) -> str:
    """The unit the CARD declares for this metric, in the card's own words, with the per-commodity
    `unit_overrides` applied when the card carries them (silver_futures_eod's `settle` declares no
    blanket unit and 31 per-slug ones -- `corn_cbot: 'US cents/bushel'`, `canola_ice: 'CAD/t'`).

    Empty string when the card declares nothing, which 1.5(e) turns into a REFUSAL rather than a bare
    scale: MEASURED (section 13, 90 primary + 9 world reads), the silver_psd PAYLOAD carries no unit on
    ANY metric, so this declaration is the whole of the roster's unit knowledge on that card."""
    try:
        ts = (reg or _registry()).get(table)
        m = (getattr(ts, "metrics", None) or {}).get(metric)
        if m is None:
            return ""
        if slug and getattr(m, "unit_overrides", None):
            return str(m.unit_overrides.get(slug) or m.unit or "")
        return str(getattr(m, "unit", "") or "")
    except Exception:  # noqa: BLE001 -- an unreadable card declares nothing, and the row declines
        return ""


def _registry():
    from leviathan.graphrag.numbers.registry import load_registry
    return load_registry()


def _tag_leg(calls: list, first: int, slug: str) -> None:
    """Stamp the LEG that produced each of this slice's rows. A private key, on the same footing as
    `derived._dv_call`'s `_dv_metric_key`: every consumer of a call-record reads `query` and `rows` and
    ignores what it does not know, so this travels with the row without reaching a reader. It is what
    `_fold_shared_aggregates` keys on -- and what the arm's `roster_rows` census will count by leg.

    IT IS A RAW SLUG ON A PUBLISHED RECORD, DELIBERATELY, AND IT ADDS NO CLASS (review m3, kept with the
    reason written down rather than stripped). `fetch_window` already writes the raw slug into every
    served record's `query.commodity` -- that is the estate-wide shape of a call-record, not this lane's
    choice -- so `holder['calls']` carries slugs on the agent lane too. What the DESIGN's mint discipline
    forbids is a raw slug reaching a READER, and neither key does: `citations` resolves `query.commodity`
    through its commodity display map ('malaysian_crude_palm_oil_cme' renders "CME palm oil") and nothing
    renders an underscore-prefixed key at all. Stripping it would delete the ONLY per-leg key on a
    pink-sheet row (whose `commodity` is None by the card's shape) and with it the arm's per-leg census."""
    for c in calls[first:]:
        c["_roster_slug"] = slug


def _mint(*, table_label: str, metric_label: str, tag: str, value, unit: str, period: Optional[str],
          asof, country: Optional[str] = None, date: Optional[str] = None,
          scope_note: Optional[str] = None) -> dict:
    """The roster's OWN synthetic call-record -- the `derived._dv_call` / `cascade._rv_call` shape, and
    deliberately NOT either of those functions (design 1.3 UNIT and refutation MAJOR-1).

    `_dv_call` indexes `DV_RENDER_METRICS` directly and that dict has exactly thirteen keys, none of
    them production, exports/imports, a pink-sheet LEVEL or a year-on-year delta -- so four of this
    roster's rows would raise `KeyError`, and extending the dict means editing D-DA's render table,
    which 1.6(5) forbids. It also stamps `country: None` and `table: "derived"` over the served
    payload. This mint keeps the SOURCE table on the record (so `citations._source_label` names the
    real publisher and the `## Sources` row states the real card), declares the unit EXPLICITLY from
    the card, and carries the vintage stamp the fence tested.

    ONE ROW PER HANDLE. `tag` RIDES THE QUERY'S `commodity` SLOT AND MUST RENDER IN READER WORDS, which
    is a rule about what the WRITER SEES and not about the string's shape -- a raw contract slug reaching
    the model's copy surface is an `register.internal_leaks` charge, twice pin-caught on the sibling
    mint. TWO ADMITTED SPELLINGS, each right for its form (fix pass 2026-09-08):
      * FORM B and R5 pass a synthetic SERIES EXPRESSION ('world soybean oil', the World Bank benchmark
        name) -- there is no served row behind those and no slug that would render correctly.
      * FORM A passes the CONTRACT SLUG, exactly as the served `fetch_window` rows it is derived from
        do, because `citations` resolves it through the same commodity display map they take: measured,
        `commodity='malaysian_crude_palm_oil_cme'` renders "CME palm oil" on the mint and on the two
        levels beside it. Spelling the slug a second way here would make the derived row claim a
        different scope from its own inputs, which is the drift the mint exists to prevent."""
    row: dict = {"value": value, "unit": unit}
    if date:
        row["knowledge_date"] = date
    rec: dict = {"query": {"table": table_label, "metric": metric_label, "commodity": tag,
                           "country": country, "period": period, "asof": asof},
                 "rows": [row], "status": "ok"}
    if scope_note:
        rec["scope_note"] = scope_note
    v = _num(value)
    if v is not None:
        try:
            cq._shown(rec, v)          # the verifier's own testimony about what this line printed
        except Exception:  # noqa: BLE001
            pass
    return rec


def _trade_metric(question: str) -> str:
    """R3's side of the trade leg, from ONE compiled matcher over the question. An IMPORT ask with no
    competing export word takes `imports_mt`; everything else -- including an ambiguous ask naming
    both -- takes `exports_mt`, the origin-side column every banked deck row is about. Ambiguity fails
    toward the default, the `esr_destination_scope` law."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    if _IMPORT_ASK_RX.search(q) and not _EXPORT_ASK_RX.search(q):
        return _IMPORTS
    return _EXPORTS


def scope_form(question: str, slugs: Sequence[str]) -> str:
    """'world' or 'primary' -- THE TURN'S ONE SCOPE DECISION, taken before any read (design 1.4).

    THE DECISION IS TAKEN OVER THE BALANCE-ELIGIBLE LEGS ONLY, and the screen is applied HERE rather
    than at the call site (fix pass 2026-09-08, review MAJOR-1). A slug on `_ROSTER_PSD_ABSENT` issues
    no balance row at all -- it is refused BY NAME before any read -- so letting it vote on the form
    let a leg that never serves steer the leg that does. MEASURED in-process before the fix:
    `scope_form("where does US corn's balance sheet stand this year", ["corn_cbot"])` -> 'primary' but
    the same question with `["corn_cbot", "corn"]` -> 'world', because `corn` is a graph base-YAML
    duplicate that `_mc` reaches, has no `_primary_title`, and is already refused by name. A
    single-market US ask was silently answered off the WORLD sheet -- and that is the exact deck row
    design section 5 adds to measure the PRIMARY branch, so the arm could land on the wrong branch for
    its own scope-form measurement. The form is now decided from the slugs that will actually issue
    balance rows, which is the only set the decision is about.

    ONE FORM PER TURN, and that fences THE ROSTER'S OWN two forms: section 12 measured R1's two forms
    carrying DIFFERENT SCALES on the same metric -- corn_cbot's last su_ratio row is 0.1266 with a NULL
    payload unit while the world synthesis is pre-scaled to 22.911 '%' -- so form A and form B must
    never share a panel un-harmonised. A per-row unit declaration cannot fence a two-ROW scale split;
    refusing to MIX the forms can, and does.

    IT IS NOT THE K9-3 FENCE, AND THE DESIGN'S RESIDUAL IS STILL OPEN (corrected 2026-09-08, review
    MAJOR). Design section 5's honest ledger names this the one class the roster does NOT close: "THE
    K9-3 CLASS IS NOT UNCONSTRUCTIBLE -- IT IS LIVE ON THIS DECK TODAY ... only K9-3's own remedy
    closes it, and that is the K9 sitting's work, not this one's". The collision the design books is
    the roster's form-A row against THE CASCADE WALK's `_prescaled` '%' row, and the walk still runs on
    quick (n_cascade_rows 10-49, cw_rendered on 3 of 5 rows in every arm) -- so the two arrive in ONE
    panel and nothing here can prevent it. MEASURED on this build, real `answer_roster` + real
    `citations.render`, form A on malaysian_crude_palm_oil_cme at asof 2026-09-07: `[N1] USDA PSD
    stocks-to-use ratio CME palm oil Malaysia MY2024 = 0.1266 ratio [known 2026-08-12]` rendered beside
    a cascade twin reading `= 12.66 %` on the SAME table, metric, commodity, country, marketing year
    and knowledge date -- the judged K9-3 string exactly. AND K9-3's OWN REMEDY DOES NOT REACH IT:
    measured with `GRAPHRAG_NARRATE_SCALE=on`, `citations.narrate_scale('silver_psd', 'su_ratio')`
    returns None and `harmonise_declared_scale` returns the same objects, so the panel is unchanged.
    Form A's served rows carry NO payload unit on any of the four columns and no `shown` stamp, and
    `citations.from_number` falls back to the card's declared 'ratio'. Recorded here so the K9 lane
    does not look like a backstop that is already in place.

    THE WORLD FORM IS THE WIDE ONE, not the special case: section 12's probe resolved form B on 33 of
    36 enumerated slugs and form A on 30. It is taken when any of three things is true --
      (a) more than one BALANCE-ELIGIBLE contract is routed (every banked `rv_*` row is a two-market
          relative-value ask -- "whose stocks position moved more this year" -- which is a world
          question on both legs),
      (b) the question NAMES a world/global scope, or
      (c) any balance-eligible leg has NO primary country at all (`_primary_title` is None on barley,
          sorghum and sunflower_oil -- section 12's BIND_WORLD_ONLY three -- and a turn cannot serve
          one leg on a country and its twin on the world).
    Otherwise a single-market ask binds that market's own primary balance-sheet country. Both branches
    are PURE (a config read and two regexes); neither costs a lookup."""
    eligible = [s for s in (slugs or []) if s and s not in _ROSTER_PSD_ABSENT]
    if len(eligible) > 1:
        return "world"
    if _WORLD_ASK_RX.search(re.sub(r"\s+", " ", (question or "").lower())):
        return "world"
    for s in eligible:
        if not cq._primary_title(s):
            return "world"
    return "primary"


# ── THE SIX ROSTER ROWS, ONE ROUTED LEG AT A TIME ───────────────────────────────────────────────────
def _balance_primary(qfn, reg, slug: str, my: int, asof, title: str, trade: str,
                     calls: list, declines: list, guards: list) -> None:
    """R1-R3 on FORM A: the contract's own primary balance-sheet country, pinned to the newest SETTLED
    marketing year. THE CALL-RECORD IS THE ROW on all FOUR READS -- no served read is re-minted, so its
    payload and its locator drill-down survive to the panel (1.2, MAJOR-1). The ONE synthetic record
    this form makes is the year-on-year CHANGE, which has no served row behind it by construction.

    THE MARKETING YEAR IS `cascade._settled_my_ceiling(slug, asof)` AND NOT `max(period)`, and the
    difference is a forecast (FATAL-2): MEASURED over the 25 arm rows, the su_ratio periods served are
    MY1964 x156, MY1965 x4, MY2025 x14 and MY2026 x8 at a 2026-08-12 knowledge date -- MY2026 is
    USDA's PROJECTION year, `max(period)` selects it, and `estimate_role` is null on ALL 371 silver_psd
    rows served across all five arms, so the row itself carries no role to declare. A projection-year
    ask is refused by name (1.5(f)), never served under a settled label.

    THE YEAR-ON-YEAR ROW IS 1.2's OWN `stats.window_change` SHAPE, UNDER `stats.same_vintage`, AND IT
    WENT BACK TO THAT SHAPE IN THE FIX PASS (2026-09-08, review FATAL-2). The build reviewed served the
    card's `su_ratio_yoy_delta` COLUMN instead and justified dropping MAJOR-4's fence on two claims,
    both of which the card itself refutes in the comment block directly above that metric
    (`configs/graphrag/numbers/tables.yaml:72-83`):
      * "the PUBLISHER's own delta" -- it is not. Those are "four columns the PRODUCER has ALWAYS
        written": our own silver transform, not USDA.
      * "cannot span two knowledge dates by construction" -- the card RETRACTS exactly this. The
        apples-to-apples reading "was true only BY CONSTRUCTION under the retired clock ... Under the
        honest clock wasde_release_month is a CALENDAR month, so THE TWO COMPARED PRINTS CAN BE SEVERAL
        CALENDAR YEARS APART."
    And the fence could not be restored over that column even if the claim were kept, because the two
    endpoints it spans are INSIDE it: no test on the served rows can see them. So R1 reads the settled
    year AND MY-1 as two independent `agg='latest'` rows, each carrying its OWN release stamp, and the
    change between them is minted ONLY when `stats.same_vintage` proves the two prints share one
    release -- the identical construction form B already uses, and the D-DA law ("no derived row spans
    two knowledge dates") applied where it can actually be tested.

    BOTH LEVELS STAND EITHER WAY. On a vintage split the change is withheld with a written reason and
    the two years' rows still render with their own `[known ...]` stamps -- fences CORRECT or COMPUTE,
    never delete. THE MINT CARRIES THE SERVED ROWS' OWN QUERY SHAPE (`commodity=slug`, `country=title`)
    rather than a synthetic series tag: `citations` resolves that slug to the SAME reader words the two
    served levels beside it print ("CME palm oil Malaysia"), so the derived row cannot claim a scope
    its inputs did not have -- and no raw slug reaches the writer's copy surface.

    THE VINTAGE FENCE ALSO STILL RUNS ACROSS THIS LEG'S ROWS AND IS STILL STAMPED (MAJOR-4):
    `TableSpec.group_cols` resolves for silver_psd to `[leviathan_slug, country, market_year]`, so EACH
    marketing year inside one read independently takes its own latest release <= asof, and `cascade.py`
    states it outright -- "PSD vintages are DELTAS, so no single shared vintage exists". When the rows
    disagree the fact is recorded as a decline so the arm can count it."""
    first = len(calls)                      # this leg's own slice; a two-leg turn must not fence across legs
    levels: dict = {}
    for metric, per in ((_SU, my), (_SU, my - 1), (_PRODUCTION, my), (trade, my)):
        unit = _card_unit(reg, _PSD, metric, slug)
        if not unit:
            guards.append(f"roster: {_PSD}.{metric} declares no unit on its card; row declined "
                          f"rather than printed on a bare scale")
            declines.append({"row": metric, "slug": slug, "reason": "unit_undeclared",
                             "period": f"MY{per}",
                             "detail": "the card names no unit for this column, so the figure could "
                                       "only be printed on a bare scale and is refused instead"})
            continue
        rec = cq.fetch_window(qfn, table=_PSD, metric=metric, commodity=slug, country=title,
                              t1=None, t2=None, asof=asof, agg="latest",
                              period=per, period_type="marketing_year")
        if not _served(rec):
            declines.append({"row": metric, "slug": slug, "reason": "empty_card",
                             "scope": title, "period": f"MY{per}",
                             "detail": "the balance sheet served no row for this contract at this "
                                       "country and this marketing year at this as-of"})
            continue
        calls.append(rec)
        if metric == _SU:
            levels[per] = rec
    _yoy_primary(reg, slug, my, asof, title, levels, calls, declines)
    stamps = [_stamp(c) for c in calls[first:]]
    if len(stamps) > 1:
        ok, _shared = st.same_vintage(stamps)
        if not ok:
            declines.append({"row": "balance_vintage", "slug": slug, "reason": "vintage_split",
                             "detail": "the balance rows do not share one release; each renders with "
                                       "its own as-known stamp and no relation is minted across them"})


def _stamp(rec: Optional[dict]) -> Optional[str]:
    """The as-known stamp of the row this record PRINTS -- read off `_shown_row`, so the fence and the
    rendered `[known ...]` label can never test different observations."""
    h = _shown_row(rec)
    return h.get("knowledge_date") or h.get("data_date")


def _yoy_primary(reg, slug: str, my: int, asof, title: str, levels: dict, calls: list,
                 declines: list) -> None:
    """FORM A's year-on-year change: `stats.window_change` over the TWO served levels, minted only
    behind `stats.same_vintage` (design 1.2 R1, restored 2026-09-08 -- see `_balance_primary`).

    EVERY REFUSAL HAS ITS OWN REASON (1.5): a missing current year and a missing prior year are not the
    same fact, and neither is a vintage split -- the writer's absence sentence has to be true of the
    thing that actually failed."""
    now, prev = levels.get(my), levels.get(my - 1)
    if now is None or prev is None:
        declines.append({"row": "su_ratio_yoy", "slug": slug, "period": f"MY{my - 1}..MY{my}",
                         "reason": "no_prior_year" if now is not None else "no_current_year",
                         "detail": "only one of the two marketing years served a stocks-to-use row at "
                                   "this scope, so no change between them is taken"})
        return
    ok, shared = st.same_vintage([_stamp(prev), _stamp(now)])
    if not ok:
        declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "vintage_split",
                         "period": f"MY{my - 1}..MY{my}",
                         "detail": "the two marketing years' estimates do not share one release, so no "
                                   "change between them is minted; both levels stand with their own "
                                   "as-known stamps"})
        return
    a, b = _num(_shown_row(prev).get("value")), _num(_shown_row(now).get("value"))
    if a is None or b is None:
        declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "unreadable_level",
                         "period": f"MY{my - 1}..MY{my}",
                         "detail": "one of the two served levels carries no readable figure, so no "
                                   "change between them is computed"})
        return
    ch = st.window_change([a, b], 0, 1)
    if ch.get("declined"):
        declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "stat_declined",
                         "period": f"MY{my - 1}..MY{my}",
                         "detail": str(ch.get("reason") or "")[:160]})
        return
    calls.append(_mint(table_label=_PSD, metric_label="stocks-to-use ratio change (YoY)", tag=slug,
                       value=round(float(ch["value"]), 6),
                       unit=_card_unit(reg, _PSD, _SU, slug), period=f"MY{my - 1}..MY{my}",
                       asof=asof, country=title, date=shared))


def _world_total(qfn, slug: str, metric: str, my: int, asof) -> Optional[tuple]:
    """The world total for one PSD component at one marketing year: SUM over each country's OWN latest
    vintage <= asof with the EU membership dedup, through `cascade._psd_component_rows` +
    `cascade._world_sum` -- the SAME arithmetic `_world_su_ratio` runs, hoisted by that wave precisely
    so a second consumer cannot drift from it on dedup, on latest-wins or on the freshness stamp.

    THIS IS THE CORRECTION SECTION 13 FORCED (refuter MAJOR-1). The world form at design 1.2's literal
    shape -- `agg=latest, period=MY, country=None` -- does NOT bind scope: measured, it returns every
    PSD country (67 rows on barley, 74 on sorghum) and a headline row is then one arbitrary country's
    figure wearing a world label. That is the K9-2 'manufactured ranking' class exactly. Returns
    (total, n_countries, max_release) or None when the set cannot be summed honestly."""
    try:
        rows = cq._psd_component_rows(qfn, slug, metric, my, asof)
        got = cq._world_sum(rows, my)
    except Exception:  # noqa: BLE001 -- a world synthesis that cannot run is a DECLINE, never a raise
        return None
    if not got:
        return None
    total, n, release, _unit = got
    if not n:
        return None
    return (total, n, release)


def _balance_world(qfn, reg, slug: str, my: int, asof, trade: str,
                   calls: list, declines: list, guards: list) -> Optional[tuple]:
    """R1-R3 on FORM B: the world, which is a synthesis and not a country. Every row here is MINTED
    (there is no served single-row read behind a per-country sum), each carries an EXPLICIT unit and a
    reader label, and none of them issues `country='World'` -- silver_psd holds no such row.

    R1's SECOND ROW IS A GENUINE CROSS-ROW RELATION HERE, so MAJOR-4's fence is applied to it and
    binds: the settled year's world ratio and MY-1's are two independent per-country-latest unions with
    their own freshness stamps, and `stats.same_vintage` (exact string equality, fail-closed on an
    unstamped input) decides whether a delta between them may be minted at all. On disagreement the
    two LEVELS still render with their own stamps and the CHANGE row is not minted -- the D-DA law
    ("no derived row spans two knowledge dates") applied where it actually binds.

    R1's DECLINE NO LONGER TAKES R2 AND R3 WITH IT (fix pass 2026-09-08, review MAJOR). The build
    reviewed returned early when `_world_su_ratio` came back None, so the production row and the trade
    row were never attempted and never counted -- although each is an INDEPENDENT synthesis through
    `_psd_component_rows` + `_world_sum` that could have served. That breaks 1.5(d)'s PER-ROW refusal
    law and it corrupts the very signal this lane offers in exchange for the C2 shape record it loses
    (1.6(4): "`roster_declines` (S2) is the replacement signal"): two of three balance rows vanished
    UNCOUNTED on exactly the turns the signal exists to observe. Each row now refuses on its own.

    Returns (ratio_pct, my) for the settled year so the caller can detect the shared-aggregate
    collision of section 12, or None when R1 itself declined."""
    label = cq._xc_label(slug)
    try:
        now = cq._world_su_ratio(qfn, slug, my, asof)
    except Exception:  # noqa: BLE001
        now = None
    out: Optional[tuple] = None
    _world_noted = False
    if now is None:
        declines.append({"row": _SU, "slug": slug, "reason": "world_synthesis_declined",
                         "period": f"MY{my}",
                         "detail": "the world stocks-to-use synthesis found no summable set of "
                                   "country rows for this marketing year at this as-of"})
        declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "no_current_year",
                         "period": f"MY{my - 1}..MY{my}",
                         "detail": "the settled year's world total did not synthesise, so no change "
                                   "against the previous year is taken either"})
    else:
        pct, release, ncty = now
        out = (float(pct), my)
        calls.append(_mint(table_label=_PSD, metric_label="stocks-to-use ratio", tag=label,
                           value=round(float(pct), 4), unit="%", period=f"MY{my}", asof=asof,
                           date=release,
                           scope_note=(f"The stocks-to-use figure for {label} is the WORLD total -- "
                                       f"each country's own latest published estimate summed across "
                                       f"{ncty} reporting countries, with EU members counted once. It "
                                       f"is not any single country's balance sheet.")))
        try:
            prev = cq._world_su_ratio(qfn, slug, my - 1, asof)
        except Exception:  # noqa: BLE001
            prev = None
        if prev is None:
            declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "no_prior_year",
                             "period": f"MY{my - 1}",
                             "detail": "the previous marketing year's world total did not synthesise, "
                                       "so no change between the two years is taken"})
        else:
            ok, _shared = st.same_vintage([release, prev[1]])
            if not ok:
                declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "vintage_split",
                                 "detail": "the two marketing years' world totals do not share one "
                                           "release, so no change between them is minted; both levels "
                                           "stand with their own as-known stamps"})
            else:
                ch = st.window_change([float(prev[0]), float(pct)], 0, 1)
                if ch.get("declined"):
                    declines.append({"row": "su_ratio_yoy", "slug": slug, "reason": "stat_declined",
                                     "detail": str(ch.get("reason") or "")[:160]})
                else:
                    calls.append(_mint(table_label=_PSD,
                                       metric_label="stocks-to-use ratio change (YoY)",
                                       tag=label, value=round(float(ch["value"]), 4),
                                       unit="percentage points", period=f"MY{my - 1}..MY{my}",
                                       asof=asof, date=release))
    for metric, mlabel in ((_PRODUCTION, "production"), (trade, trade.replace("_mt", ""))):
        unit = _card_unit(reg, _PSD, metric, slug)
        if not unit:
            guards.append(f"roster: {_PSD}.{metric} declares no unit on its card; the world row is "
                          f"declined rather than printed on a bare scale")
            declines.append({"row": metric, "slug": slug, "reason": "unit_undeclared",
                             "period": f"MY{my}",
                             "detail": "the card names no unit for this column, so the world total "
                                       "could only be printed on a bare scale and is refused instead"})
            continue
        got = _world_total(qfn, slug, metric, my, asof)
        if got is None:
            declines.append({"row": metric, "slug": slug, "reason": "world_synthesis_declined",
                             "period": f"MY{my}",
                             "detail": "no summable set of country rows was served for this component "
                                       "at this marketing year and as-of, so no world total is taken"})
            continue
        total, n, release = got
        # ONE SCOPE NOTE PER LEG, AND IT RIDES WHICHEVER ROW COMES FIRST. `_numbers_block` renders the
        # notes as ONE sentence run, so a note per world row would put four near-identical sentences in
        # front of the writer per leg -- but the leg must never ship a world SUM with no statement that
        # it IS a sum. R1 carries it when R1 served; when R1 declined (which is now survivable, see the
        # docstring) the first surviving component row carries it instead, in the same words.
        note = None
        if out is None and not _world_noted:
            _world_noted = True
            note = (f"The balance-sheet figures for {label} are WORLD totals -- each country's own "
                    f"latest published estimate summed across {n} reporting countries, with EU members "
                    f"counted once. They are not any single country's balance sheet.")
        calls.append(_mint(table_label=_PSD, metric_label=mlabel, tag=label,
                           value=round(float(total), 4), unit=unit, period=f"MY{my}", asof=asof,
                           date=release, scope_note=note))
    return out


def _price_level(qfn, reg, slug: str, asof, calls: list, declines: list, guards: list) -> None:
    """R4: the board's OWN front-month settle, in its OWN currency, from silver_futures_eod. THE
    CALL-RECORD IS THE ROW -- one `agg='front_expiry'` read, the card's `publication_lag_days: 1` doing
    the withhold, and `select_front_expiry` naming the delivery month on the served row.

    R4's ROSTER IS `cascade._RV_EOD_FRESH`, IMPORTED AND NEVER RE-TYPED -- nine slugs, each carrying
    its own reader label. It is a STRICT SUBSET of what the card serves, and a slug the card serves but
    this rung does not (`rapeseed_oil_zce`, whose unit the card declares outright as 'CNY/t') is named
    as served-but-not-on-this-rung. R4 DOES NOT BORROW `_RV_PRICE_ABSENCE`'s reasons (MAJOR-3): those
    are World-Bank benchmark reasons written for R5's table, the two sets OVERLAP rather than
    complement, and lending sorghum's "the World Bank discontinued its benchmark after 2020-08" to a
    FUTURES decline would state a false cause -- sorghum has no futures contract on any slug the card
    carries. A scope sentence is the true one, so a scope sentence is what this row declines with.

    A DARK BOARD IS ITS OWN DECLINE, and it is LIVE (section 13): `futures_roll.roll_method_for` is
    'open_interest' on 7 of 9 boards and `select_front_expiry` fail-closes on a partial frame, so an
    as-of whose newest admitted session carries an all-blank open_interest column serves nothing --
    measured at 2/9 boards on 2026-09-07, with `malaysian_crude_palm_oil_cme` dark at every as-of
    tested (open_interest blank on 78% of its rows). That defect is the cascade price leg's too and is
    docketed outside this lane; here it is an honest empty read with a reason, never a guessed level."""
    eod = cq._RV_EOD_FRESH.get(slug)
    if eod is None:
        declines.append({"row": _BOARD_ROW, "slug": slug, "reason": "off_eod_roster",
                         "detail": "this rung's exchange-settle roster is the nine boards whose "
                                   "front-month settle carries a reader label here; the card may "
                                   "serve this contract, but no settle row is taken for it on this "
                                   "tier"})
        return
    metric, label = eod[0], eod[1]
    unit = _card_unit(reg, cq._RV_EOD_TABLE, metric, slug)
    if not unit:
        guards.append(f"roster: {cq._RV_EOD_TABLE}.{metric} declares no unit for {label}; the settle "
                      f"row is declined rather than printed on a bare scale")
        declines.append({"row": _BOARD_ROW, "slug": slug, "reason": "unit_undeclared",
                         "detail": "the futures card names no unit for this board, so its settle "
                                   "could only be printed on a bare scale and is refused instead"})
        return
    rec = cq.fetch_window(qfn, table=cq._RV_EOD_TABLE, metric=metric, commodity=slug, country=None,
                          t1=None, t2=None, asof=asof, agg="front_expiry",
                          period=None, period_type="date")
    if not _served(rec):
        declines.append({"row": _BOARD_ROW, "slug": slug, "reason": "board_dark",
                         "detail": "no front-month settle is admitted for this board at this as-of: "
                                   "the front-expiry rule needs the session's open-interest column "
                                   "and the newest admitted session does not carry it"})
        return
    calls.append(rec)


def _price_standing(qfn, reg, slug: str, asof, calls: list, declines: list,
                    guards: list) -> Optional[str]:
    """R5: the World Bank monthly benchmark, its trailing `cascade._RV_PRICE_MONTHS` window, and the
    two standings computed off that same window. ONE READ, up to THREE rows -- the served level (the
    call-record itself) plus a MINTED percentile and a MINTED sigma, both from `stats`, both declared
    in their own units, neither re-fetching anything.

    THE OFF-ROSTER DECLINE IS `cascade._RV_PRICE_ABSENCE`, IN THE DECLINING ROW'S OWN WORDS -- eight
    slugs, each with a written World-Bank reason, because R5 IS the World Bank row and those reasons
    are true of it. A slug in neither map declines with a scope sentence of its own.

    Returns the pink-sheet METRIC actually read, so the caller can apply section 13's 'one benchmark,
    two contracts' law: `_RV_PRICE_SERIES` maps 17 slugs onto 15 metrics, so a routed pair can land on
    ONE series (soybean_oil_cbot and soybean_oil_dce both read 1,660.0; soybean_meal_cbot and
    soybean_meal_dce both 398.0) and printing it twice would state one fact as two."""
    ser = cq._RV_PRICE_SERIES.get(slug)
    if ser is None:
        reason = cq._RV_PRICE_ABSENCE.get(slug)
        declines.append({"row": "price_standing", "slug": slug,
                         "reason": "no_benchmark" if reason else "off_price_roster",
                         "detail": reason or ("no World Bank monthly benchmark on this card "
                                              "corresponds to this contract, so no price standing is "
                                              "taken for it")})
        return None
    metric, label = ser[0], ser[1]
    unit = _card_unit(reg, cq._RV_PRICE_TABLE, metric)
    if not unit:
        guards.append(f"roster: {cq._RV_PRICE_TABLE}.{metric} declares no unit; the price rows are "
                      f"declined rather than printed on a bare scale")
        declines.append({"row": "price_standing", "slug": slug, "reason": "unit_undeclared",
                         "detail": "the benchmark card names no unit for this series, so neither "
                                   "the level nor its standing is printed on a bare scale"})
        return None
    rec = cq._rv_price_series(qfn, metric, asof)
    if not _served(rec):
        declines.append({"row": "price_standing", "slug": slug, "reason": "empty_card",
                         "detail": "the monthly benchmark served no observation inside its own "
                                   "trailing window at this as-of"})
        return None
    calls.append(rec)
    # THE SERIES IS READ THROUGH `cascade._rv_axes` AND THE STANDING IS TAKEN AT `vals[-1]` -- the
    # estate's OWN shipped idiom for this exact row (`cascade._rv_price_reading`, cascade.py:4535-4568:
    # `_rv_axes(...)` then `vals[-1]` / `dts[-1]` and `st.percentile(vals[-1], vals)`). REPLACED the
    # `_headline_row` reading in the fix pass (2026-09-08, review FATAL-1): that helper is kill-switched
    # on a module global written from ANOTHER thread and returns `rows[0]` when off -- the OLDEST month
    # of an ASC 60-month window -- so on a series rising 800 -> 1,390 the block printed the newest level
    # beside the OLDEST month's percentile and sigma, i.e. the exact inverse standing, and flipped
    # between cold and warm workers. `_rv_axes` also drops rows carrying no parseable date, which is the
    # right set to rank against: the join here is by date.
    hist, dts, _u = cq._rv_axes(rec, None)
    # SORTED BY DATE, NOT TRUSTED FROM FETCH ORDER, and that is a deliberate one-line strengthening of
    # the borrowed idiom: `_rv_axes` returns rows as fetched, and the ASC total order it relies on is
    # `fetch_window`'s DEFAULT rather than its only behaviour -- `futures_newest_first` compiles a
    # DESC order and no call in this module threads it, so the roster would silently invert if a later
    # wave ever did. `cascade._regional_series` already took exactly this decision on exactly this
    # ground ("Rows are SORTED by the `period` extra rather than trusting fetch order (a defensive
    # improvement over _rv_axes, pinned)"). ISO dates sort chronologically; FETCH POSITION is the
    # tiebreaker, so a duplicated stamp resolves the way an unsorted read already did.
    order = sorted(range(len(hist)), key=lambda i: (dts[i], i))
    hist, dts = [hist[i] for i in order], [dts[i] for i in order]
    # THE WINDOW IS THE SERVED ROWS' OWN SPAN, not the REQUEST's (m2, fix pass 2026-09-08): the card
    # carries a 40-day publication lag, so `_months_back(asof, 60)..asof` overstated the span by a month
    # at BOTH ends of what was actually ranked (stated 2021-09-01..2026-09-07 over a record covering
    # 2021-10-01..2026-09-01). `cascade`'s own row spells it `f"{dts[0]}..{dts[-1]}"` and so does this
    # one. IT MUST ALSO CARRY '..': `citations._period_label` prefixes "MY" to any period that neither
    # starts with 'MY' nor carries '..', which is the MYMY class one seam over.
    # AND THE SERVED LEVEL ROW IS RE-STAMPED TO THAT SAME SPAN (fix pass 2026-09-09, review minor). The
    # level row kept `_rv_price_series`'s REQUEST window while the percentile and the sigma minted off
    # it carried the served one, so R5's three rows -- ONE read, ONE window -- named TWO windows in one
    # panel, and the level's own line contradicted itself inside a single sentence: "2021-09-01..
    # 2026-09-07 = 1,390 USD/mt [60 rows served, covering 2021-10-01..2026-09-01]". A reader comparing
    # the level to its own percentile could not tell whether the two were ranked over the same months.
    # ONE SPAN, THE SERVED ROWS' OWN, on all three rows; the request span was never a served fact.
    if dts and isinstance(rec.get("query"), dict):
        rec["query"]["period"] = f"{dts[0]}..{dts[-1]}"
    if len(hist) < 2:
        declines.append({"row": "price_percentile", "slug": slug, "reason": "series_too_thin",
                         "n": len(hist),
                         "detail": "the monthly benchmark's own trailing window served too few dated "
                                   "observations to rank this level against"})
        return metric
    latest, stamp = hist[-1], dts[-1]
    window = f"{dts[0]}..{dts[-1]}"          # the ONE span, stamped above onto the level row as well
    pc = st.percentile(latest, hist)
    if pc.get("declined"):
        declines.append({"row": "price_percentile", "slug": slug, "reason": "stat_declined",
                         "n": pc.get("n"),
                         "detail": "the percentile of this level within its own served window "
                                   "could not be computed, so no rank is stated"})
    else:
        calls.append(_mint(table_label=cq._RV_PRICE_TABLE, metric_label="benchmark percentile",
                           tag=label, value=round(float(pc["value"]), 1), unit="percentile",
                           period=window, asof=asof, date=stamp))
    zs = st.zscore(latest, hist)
    if zs.get("declined"):
        declines.append({"row": "price_zscore", "slug": slug, "reason": "stat_declined",
                         "n": zs.get("n"),
                         "detail": "the standard-deviation distance of this level from its own "
                                   "served window could not be computed, so no sigma is stated"})
    else:
        calls.append(_mint(table_label=cq._RV_PRICE_TABLE, metric_label="benchmark sigma", tag=label,
                           value=round(float(zs["value"]), 2), unit="sigma", period=window,
                           asof=asof, date=stamp))
    return metric


def _derived_pair(qfn, slugs: Sequence[str], asof, calls: list, declines: list) -> None:
    """R6, THE DERIVED PAIR ROW -- the only row that fires on a two-leg question, and only ONE lane per
    turn (`derived.DV_LANE_CAP = 1` stands unchanged). It reaches `_dv_call` from INSIDE
    `derived.su_standing` / `derived.crush_share`, on the thirteen metric keys those producers already
    declare: the roster adds no key and edits no render table.

    BOTH PRODUCERS RETURN `(lines, calls, trace)`, and only the CALLS are taken. Their `lines` are the
    D-DA lane's own reader block, assembled for a different renderer and carrying `[N]` handles indexed
    off `base`; this lane consumes `calls` alone -- `_resolve` reads `nums["calls"]` and nothing else --
    so the handle arithmetic never has to agree with anyone.

    NOT MEASURED YET (section 13's own NOT-MEASURED list): neither producer has been exercised through
    this seam, so both are called inside a try and a failure is a counted decline rather than a lost
    turn. The lane order is the design's -- stocks-to-use standing when BOTH legs are WASDE legs, else
    the crush share when the pair sits inside the crush trio, else nothing and a counted decline."""
    from leviathan.graphrag.numbers import derived as dv
    a, b = slugs[0], slugs[1]
    base = len(calls)
    try:
        if a in dv._DV_WASDE_LEGS and b in dv._DV_WASDE_LEGS:
            _lines, dcalls, trace = dv.su_standing(cq.fetch_window, qfn, a, b, asof, base)
        elif {a, b} <= dv._DV_CRUSH_TRIO:
            _lines, dcalls, trace = dv.crush_share(cq.fetch_window, qfn, asof, base)
        else:
            declines.append({"row": "derived_pair", "slug": f"{a}+{b}", "reason": "no_lane",
                             "detail": "neither the stocks-to-use standing nor the crush share is "
                                       "defined for this pair of contracts"})
            return
    except Exception as e:  # noqa: BLE001 -- a derived lane must never take the roster down with it
        declines.append({"row": "derived_pair", "slug": f"{a}+{b}", "reason": "lane_error",
                         "detail": str(e)[:160]})
        return
    if not dcalls:
        declines.append({"row": "derived_pair", "slug": f"{a}+{b}", "reason": "lane_declined",
                         "detail": str((trace or {}).get("decline") or "")[:160]})
        return
    for c in dcalls:
        if isinstance(c, dict) and c.get("rows"):
            calls.append(c)


def answer_roster(question: str, asof, *, contracts: Optional[Sequence[str]] = None, qfn=None,
                  reg=None, route_error: bool = False) -> dict:
    """THE HEADLINE ROSTER for this turn: the deterministic replacement for `agent.answer_numbers` on
    the Scan lane. ZERO model rounds, ZERO agent tokens, ZERO clock reads (design section 2).

    RETURNS THE FULL SHAPE `orchestrator.run_hybrid._resolve` READS, not three keys of it (1.6(4)).
    `_resolve` copies `pattern_records`, then a fixed six-key tuple, then `numbers_budget` and
    `_ms_numbers`. The roster MINTS `calls`, `tables_queried` (its own census), `unit_mismatch_guard`
    (1.3's unit fence is exactly that guard's subject) and `numbers_budget` (the 1.5 stamp). It returns
    None BY DESIGN for `fork_basis` (`answer_numbers` mints none either, and the copy-back is guarded
    `is not None`), for `pattern_records` (no ledger leg on this lane) and for the three C2 shape keys
    -- the roster has no model plan to record a question shape against. THAT LAST ONE IS A REAL LOSS,
    not a null column, and it is named as such in the design's honest ledger; `roster_declines` on the
    budget stamp is the replacement signal and it is not the same signal.

    `numbers_budget` IS ALWAYS STAMPED, including on a turn that mints nothing. That is what makes the
    empty-leg SCOPE NOTE reachable (FATAL-1): `_numbers_block`'s existing empty-leg clause is gated on
    a budget record being present, so a refusing roster turn without one would ship "(none retrieved)"
    to the writer with no marker, no persona mandate and no trace stamp -- an absence presented as an
    ordinary thin read. `returned: True` with an empty `calls` list takes that existing clause verbatim
    (no new prompt); the OUTAGE clause beside it stays unreachable here, because this function returns
    a record on every path.

    NEVER RAISES, AND THAT IS NOW TRUE OF THE WHOLE FUNCTION AND NOT JUST OF THE READS (fix pass
    2026-09-08, review m1). Every read is `cascade.fetch_window`, which degrades to `rows=[]` on any
    failure, and every synthesis is wrapped -- but TWO paths sat outside all of it and were MEASURED to
    propagate: `reg = reg or _registry()` (an unloadable registry -> RuntimeError) and an `asof` that
    does not parse (`cascade._months_back` -> ValueError, reached through `_settled_my_ceiling` and
    `_rv_price_series`). Both now land inside the body guard below, which stamps a `lane_error` decline
    and returns the record -- so the floor the docstring claims is the floor the code has, and
    `numbers_budget` (which is what makes the writer's absence sentence reachable at all) is stamped on
    every path including a broken one.

    `route_error` IS THE ROUTER'S OWN CAUSE, THREADED (fix pass, review minor). `run_hybrid` swallows a
    `route_fn` exception to an empty contract list; a router that THREW is not a turn that routed
    nothing, and this module cites `_RV_PRICE_ABSENCE`'s law -- never one shared reason for two causes
    -- three times elsewhere. The two now decline under `route_error` and `unrouted` respectively."""
    t0 = time.perf_counter()
    calls: list = []
    declines: list = []
    guards: list = []
    try:
        form = _roster_body(question, asof, contracts, qfn, reg, route_error, calls, declines, guards)
    except Exception as e:  # noqa: BLE001 -- THE FLOOR: a refusal with a written reason, never a raise
        declines.append({"row": "roster", "slug": None, "reason": "lane_error",
                         "detail": "the lookup roster could not be assembled for this turn "
                                   f"({str(e)[:120]}), so no figure is taken from the record here"})
        form = None
    return _result(calls, declines, guards, t0, form=form)


def _roster_body(question: str, asof, contracts, qfn, reg, route_error: bool,
                 calls: list, declines: list, guards: list):
    """`answer_roster`'s body, split out so ONE guard covers every path (see its docstring). Returns
    the turn's scope form, or None when no leg was balance-eligible."""
    reg = reg or _registry()
    # ONE LEG PER CONTRACT, DE-DUPLICATED ONCE AT THE ENTRY AND BEFORE THE TWO-SLUG CUT (fix pass
    # 2026-09-09, verifier NEW). `_mc` filters on contract MEMBERSHIP and nothing there promises a SET:
    # one slug can be returned TWICE (an alias hit and a hierarchy hit on the same contract), and the
    # duplicate was not merely wasteful, it INVERTED two of this module's own laws. (1) THE FOLD ATE ITS
    # OWN KEEPER: `_fold_shared_aggregates` took `keep, drop = group[0], set(group[1:])`, so on a group
    # of [x, x] the keeper sat in the drop set, the twin filter removed the keeper's OWN rows and a leg
    # that HAD served rows rendered "(none retrieved)" -- a fence DELETING the only observation, which is
    # the one thing the fold doctrine forbids (it may drop a DUPLICATE, never the last copy). MEASURED
    # offline on the palm leg: `contracts=[palm, palm]` served SIX pink-sheet rows and shipped ZERO, with
    # no fold note either (the note is hung on a surviving call whose `_roster_slug` is the keeper, and
    # none survived). (2) AND THE WORLD SURFACE FOLDED NOTHING: `_collide` keys `world_r1` by SLUG, so a
    # duplicate collapses to ONE key, no group of two ever forms, and the identical world balance rows
    # printed TWICE unfolded -- one fact stated as two, on exactly the relative-value question section
    # 12's law exists for. De-duplicating here fixes both at the source and makes `contracts=[x, x]`
    # serve what `contracts=[x]` serves, row for row. ORDER-PRESERVING (`dict.fromkeys`), because design
    # 1.4 runs one roster per routed slug IN THE ORDER THE ROUTER RETURNED THEM, and BEFORE the cut, so
    # a `[x, x, y]` route still reaches the second distinct leg rather than spending the pair on one.
    slugs = list(dict.fromkeys(s for s in (contracts or []) if s))[:ROSTER_CONTRACT_CAP]

    if not slugs:
        # 1.5(a) NO ROUTED CONTRACT, including the planner-fallback turn (`plan is None` -> `_mc` empty).
        # Mints nothing and says why. The writer's absence sentence is `_numbers_block`'s existing
        # empty-leg clause, reused verbatim. TWO CAUSES, TWO REASONS: a router that RAISED is a
        # different fact from a turn that routed nothing, and the caller threads which one happened.
        if route_error:
            declines.append({"row": "roster", "slug": None, "reason": "route_error",
                             "detail": "the contract router failed on this turn, so no balance sheet, "
                                       "board or benchmark could be named to read -- the record was "
                                       "never asked, and this is not a finding that it holds nothing"})
        else:
            declines.append({"row": "roster", "slug": None, "reason": "unrouted",
                             "detail": "no contract was routed for this turn, so no balance sheet, "
                                       "board or benchmark could be named to read"})
        return None

    form = scope_form(question, slugs)
    trade = _trade_metric(question)
    world_r1: dict = {}
    price_metrics: dict = {}
    for slug in slugs:
        _leg_first = len(calls)
        absent = _ROSTER_PSD_ABSENT.get(slug)
        my = cq._settled_my_ceiling(slug, asof)
        if absent:
            declines.append({"row": "balance", "slug": slug, "reason": "psd_absent", "detail": absent})
        elif asks_projection_year(question, slug, asof):
            declines.append({"row": "balance", "slug": slug, "reason": "projection_year",
                             "detail": "this question asks about a marketing year USDA has not closed. "
                                       "The record holds a PROJECTION for that year and carries no "
                                       "field saying so on this sheet, so this lane does not print a "
                                       "forecast under a settled label; the last closed year is "
                                       f"MY{my} and a forecast read is a wider tier's answer"})
        elif my is None:
            declines.append({"row": "balance", "slug": slug, "reason": "no_marketing_year",
                             "detail": "no marketing-year calendar is held for this contract, so no "
                                       "settled year can be named and no balance row is taken"})
        elif form == "world":
            got = _balance_world(qfn, reg, slug, my, asof, trade, calls, declines, guards)
            if got is not None:
                world_r1[slug] = got
        else:
            title = cq._primary_title(slug)
            if not title:
                # 1.5(c) AN UNRESOLVED SCOPE -> the balance rows are not issued. This is the K9-2 fix
                # taken at the roster: the judged "manufactured ranking" was a query that NAMED NO
                # COUNTRY, served every PSD country and headlined one arbitrary row. MEASURED live on
                # this deck -- 7 of the 25 arm rows' served silver_psd reads carry `country=None` and
                # returned 3,750 to 4,759 rows apiece, all `ok`, all on the six-round control arms.
                # IT IS A BELT, NOT THE DESIGN'S LIVE THIRD BRANCH, and saying so is the honest reading
                # (fix pass 2026-09-08, review minor): `scope_form` returns 'primary' only when every
                # balance-eligible slug ALREADY has a truthy `_primary_title`, so this branch is
                # structurally unreachable through that door. It stands for the day the two producers
                # disagree -- a slug whose primary resolves at decision time and not at read time -- and
                # its pin reaches it by monkeypatching `scope_form`, which the pin says outright.
                declines.append({"row": "balance", "slug": slug, "reason": "scope_unresolved",
                                 "detail": "no primary balance-sheet country is declared for this "
                                           "contract, so no country-scoped balance row is taken"})
            else:
                _balance_primary(qfn, reg, slug, my, asof, title, trade, calls, declines, guards)
        _price_level(qfn, reg, slug, asof, calls, declines, guards)
        pm = _price_standing(qfn, reg, slug, asof, calls, declines, guards)
        if pm:
            price_metrics.setdefault(pm, []).append(slug)
        _tag_leg(calls, _leg_first, slug)

    if len(slugs) > 1:
        _derived_pair(qfn, slugs, asof, calls, declines)
    _fold_shared_aggregates(calls, declines, world_r1, price_metrics)
    _carry_absences(calls, declines)
    return form if any(s not in _ROSTER_PSD_ABSENT for s in slugs) else None


def _fold_shared_aggregates(calls: list, declines: list, world_r1: dict, price_metrics: dict) -> None:
    """ONE AGGREGATE, TWO CONTRACTS -- section 12's law, applied to both surfaces that carry it, and it
    DROPS ROWS rather than merely noting them.

    MEASURED (section 12, 36 slugs): world stocks-to-use ratios are NOT slug-distinct. Six collision
    groups cover 19 of the 33 resolving slugs -- five corn slugs all read 22.911 %, four wheat slugs
    34.277 %, three soybean slugs 29.080 %, three coffee slugs 12.814 %, and canola_ice equals
    french_rapeseed_matif at 12.012 % -- because those slugs fan onto ONE PSD aggregate sheet. A routed
    pair inside one group therefore has an IDENTICAL world balance on both legs. MEASURED AGAIN (section
    13) on the price surface: `_RV_PRICE_SERIES` maps 17 slugs onto 15 metrics, so soybean_oil_cbot and
    soybean_oil_dce read the SAME World Bank series (both 1,660.0), as do the two soybean meal slugs.

    PRINTING ONE FACT TWICE IS NOT REDUNDANCY, IT IS A MANUFACTURED SECOND OBSERVATION -- and on a
    relative-value question ("whose stocks position moved more this year", which is every banked deck
    row) two identical figures read as a MEASURED CONVERGENCE. So the later leg's twin rows are removed
    and the survivor carries a `scope_note` identifying the folded legs -- by name where the estate can
    tell them apart and by the aggregate-plus-count where it cannot, which `_fold_note` owns and
    explains (it could NOT name them apart before the 2026-09-08 fix pass, and printed one name twice).
    That note reaches the writer through `_numbers_block`'s EXISTING scope-note channel: no new prompt,
    no new seam.

    THE MATCH IS EXACT AND PER ROW, never "same group, drop everything". A row is a twin only when the
    survivor's set holds the same (table, metric, period, value) -- so the collision is proven for THAT
    figure rather than inferred from another one. Section 12's own straddling pair is why: at this as-of
    `_settled_my_ceiling` gives soybeans_cbot MY2025 and soybean_meal_cbot MY2024, so those two legs'
    balance rows carry DIFFERENT periods, are not twins, and must both stand."""
    groups = [("world", g) for g in _collide(world_r1).values() if len(g) > 1]
    groups += [("price", g) for g in price_metrics.values() if len(g) > 1]
    for kind, group in groups:
        # THE KEEPER IS EXCLUDED FROM THE DROP SET BY CONSTRUCTION (fix pass 2026-09-09, verifier NEW).
        # The routed slugs are de-duplicated at the roster's entry, so `group` cannot hold one slug
        # twice today and this subtraction is a BELT -- but it is the belt that makes the fold's
        # invariant structural instead of inherited: this function may only ever remove a DUPLICATE
        # observation, never the only one, and with the keeper inside `drop` the twin filter deleted the
        # keeper's own rows and left the leg empty. A fence CORRECTS or COMPUTES; it never deletes the
        # last copy of a figure.
        keep = group[0]
        drop = set(group[1:]) - {keep}
        # THE FOLD IS SCOPED TO THE SURFACE THAT COLLIDED, and that fence is load-bearing rather than
        # tidy: a WORLD group is evidence that two slugs share ONE PSD sheet and says nothing about
        # their price benchmarks, which are separate series with separate names. Without it a balance
        # collision could delete a genuinely distinct price row whose figure merely happened to match --
        # deleting a real observation to avoid printing a duplicate that was never one.
        surface = _PSD if kind == "world" else cq._RV_PRICE_TABLE
        here = [c for c in calls if (c.get("query") or {}).get("table") == surface]
        keys = {_fold_key(c) for c in here if c.get("_roster_slug") == keep}
        twins = [c for c in here if c.get("_roster_slug") in drop and _fold_key(c) in keys]
        if not twins:
            continue
        for c in twins:
            calls.remove(c)
        note = _fold_note(group, kind)
        _twin_keys = {_fold_key(t) for t in twins}
        for c in calls:
            if c.get("_roster_slug") == keep and _fold_key(c) in _twin_keys:
                # APPENDED, never substituted: R1's world-basis sentence ("each country's own latest
                # estimate, summed, EU members counted once") is a DIFFERENT fact from this one, and
                # `_numbers_block` renders the set of notes, so replacing it would drop a scope
                # statement to make room for a scope statement.
                c["scope_note"] = " ".join(x for x in (c.get("scope_note"), note) if x)
                break
        declines.append({"row": "shared_aggregate", "slug": "+".join(group),
                         "reason": "one_aggregate_two_contracts", "folded": len(twins),
                         "detail": note})


def _fold_note(group: Sequence[str], kind: str) -> str:
    """THE ONE PRODUCER of the fold's prompt-side sentence, and it MUST be able to identify the legs.

    THE DEFECT IT CLOSES (fix pass 2026-09-08, review MAJOR): both label producers speak the AGGREGATE's
    name -- which is precisely WHY the slugs collided -- so a naive join printed the same string twice.
    MEASURED at HEAD: soybean_oil_cbot / soybean_oil_dce both -> 'world soybean oil'; soybean_meal_cbot
    / soybean_meal_dce both -> 'world soybean meal'; corn_cbot / corn_dce / corn_matif all -> 'world
    corn'; the two wheat slugs -> 'world wheat (all classes)'. Section 12 names SIX collision groups over
    19 of 33 resolving slugs, so the tautology was the ORDINARY case, on the one prompt-side sentence
    whose whole job is to tell the writer a row was DROPPED.

    THREE SPELLINGS, TRIED IN ORDER, EACH TRUE. (1) The SURFACE vocabulary that collided, when it
    already separates the legs -- and it is tried first so this sentence and R1's own world-basis note
    call the same leg by the same name inside one SCOPE NOTE run. (2) Failing that, the CONTRACT-level
    reader label where the estate holds one (`cascade._RV_EOD_FRESH`, nine boards), which is what
    separates 'the CBOT soybean oil contract' from 'world soybean oil'. (3) Failing THAT, the aggregate
    stated ONCE plus the COUNT -- which says exactly what is known. Never the same string twice.

    SPELLING (2) IS NOW CONTRACT-LEVEL ON EVERY LEG OR IT DOES NOT FIRE AT ALL (fix pass 2026-09-09,
    review minor). The nine-board roster is a SUBSET, so the ordinary collision pair has a board label
    for one leg and not the other, and the missing half fell through to `surf[i]` -- the aggregate's own
    name, which is the string the disambiguation exists to stop using. MEASURED over every collision
    group this estate holds: SEVEN (pair, surface) cases over five distinct pairs named a leg that way
    -- 'the CBOT soybean oil contract, world soybean oil', 'the MATIF milling-wheat contract, world
    wheat (all classes)', both MGEX wheat pairs and both soybean pairs on each surface. The sentence was
    not FALSE, but it read as though one leg were a contract and the other the aggregate itself, on the
    one line whose job is to say the two are ONE observation. `_contract_name` supplies the missing half
    from the same contract-level vocabulary one rung down ('DCE soybean oil', 'MGEX hrs wheat'), and
    where the estate holds no such name for SOME leg the spelling is ABANDONED rather than mixed: the
    fold falls to (3), which states the aggregate ONCE with the count and misnames nothing. A MIXED
    SENTENCE IS THE ONE OUTCOME THAT IS NOT AVAILABLE -- it is exactly the reading the fix removes."""
    surf = [_leg_label(s, kind) for s in group]
    names = surf if len(set(surf)) == len(surf) else None
    if names is None:
        alt = [(cq._RV_EOD_FRESH.get(s) or (None, _contract_name(s)))[1] for s in group]
        names = alt if all(alt) and len(set(alt)) == len(alt) else None
    what = ("world balance-sheet aggregate" if kind == "world"
            else "World Bank monthly benchmark series")
    n = _count_word(len(group))
    body = (f"{', '.join(names)} resolve to the SAME published {what}" if names
            else (f"the {n} contracts routed for this turn resolve to the SAME published {what} "
                  f"-- {surf[0]}"))
    return (f"ONE AGGREGATE, {n} CONTRACTS: {body}, so the figures shown for it are ONE observation "
            f"covering all of them -- not one reading per contract. State it once, and make no "
            f"comparison, convergence or ranking between these contracts on it.")


def _fold_key(call: dict) -> tuple:
    q = call.get("query") or {}
    rows = call.get("rows") or [{}]
    return (q.get("table"), q.get("metric"), q.get("period"), _num(rows[0].get("value")))


def _leg_label(slug: str, kind: str) -> str:
    """The reader label for one leg, in the vocabulary of the surface that collided -- the price row's
    World Bank benchmark name for a price collision, the balance sheet's own aggregate name for a
    balance one. Never the raw slug (`register.internal_leaks`).

    IT SPEAKS THE AGGREGATE'S NAME BY DESIGN, which is why it can return the SAME string for two legs
    of one collision -- that identity IS the collision. `_fold_note` owns the disambiguation, in three
    ordered spellings; this function owns only "what is this surface's name for that leg", so the fold
    sentence and R1's own world-basis note call one leg by one name."""
    if kind == "price":
        ser = cq._RV_PRICE_SERIES.get(slug)
        if ser:
            return ser[1]
    return cq._xc_label(slug)


def _contract_name(slug: str) -> str:
    """The CONTRACT-level reader name for one leg -- the board's own name, CLAIMING NO SCOPE ('DCE
    soybean oil', 'MGEX hrs wheat'), or "" where the estate holds none.

    IT IS THE ESTATE'S OWN PRODUCER, NOT A SECOND ONE: `citations._contract_display` is the column the
    re-judge residual-leak census cleared, it reads the hierarchy through `display._contract_label`, and
    it de-underscores rather than emitting the slug -- so nothing here reaches the model's copy surface
    as an `register.internal_leaks` charge. Imported lazily and never allowed to raise, because both of
    this module's callers sit on the never-raises floor and a reader label is not worth a turn.

    WHY IT IS NEEDED BESIDE `_leg_label` (fix pass 2026-09-09, two review minors): `_leg_label` speaks
    the AGGREGATE's vocabulary by design, and there are two sentences where that vocabulary states
    something the row did not measure -- a BOARD's absence (a settle is not a world figure) and the
    fold's second spelling (naming one leg by the aggregate both legs share is what the disambiguation
    was for). `cascade._RV_EOD_FRESH`'s nine labels stay FIRST in both places; this is the rung below
    them, and the aggregate name is the last resort rather than the first fallback."""
    try:
        from leviathan.graphrag import citations as _cit
        name = str(_cit._contract_display(slug) or "")
    except Exception:  # noqa: BLE001 -- a reader label never takes a turn down
        return ""
    # THE TWO BELTS, AND BOTH ARE THE SAME LAW -- a slug is never a reader word, in any spelling
    # (`register.internal_leaks`), and an unresolvable label is "" so the caller falls back to a surface
    # name rather than printing an internal identity. (1) `citations._contract_display` returns its
    # INPUT UNCHANGED when the display layer will not import, and the input here is a raw slug. (2)
    # `display._contract_label` returns the DE-UNDERSCORED slug when the hierarchy holds no entry for it
    # -- 'corn dce' for `corn_dce` -- which is the slug with spaces and not a name the estate authored.
    # MEASURED: the hierarchy carries 31 contracts and `_RV_PRICE_SERIES`/`_xc_label` reach slugs it does
    # not, so without (2) the fold's spelling (2) would have printed 'corn dce, corn matif' where
    # spelling (3) states the aggregate ONCE with the count -- trading one honest sentence for a leak.
    return "" if name in (str(slug), str(slug).replace("_", " ")) else name


_COUNT_WORDS = ("no", "one", "TWO", "THREE", "FOUR", "FIVE", "SIX")


def _count_word(n: int) -> str:
    """A small count in words -- 'TWO CONTRACTS' reads as the estate's own sentence where '2 CONTRACTS'
    reads as a template. Falls back to the digits above the roster's own cap, which nothing can reach
    today (`ROSTER_CONTRACT_CAP = 2`) but which a wider cut would."""
    return _COUNT_WORDS[n] if 0 <= n < len(_COUNT_WORDS) else str(n)


# ── THE PARTIAL REFUSAL, CARRIED TO THE WRITER (fix pass 2026-09-08, review MAJOR) ──────────────────
# THE MEASURED DEFECT: `_numbers_block` reads `budget['returned']`, `budget['capped']` and the calls'
# `scope_note`, and NOTHING renders `roster_declines`. So only the ALL-EMPTY turn narrated. Measured on
# the real roster with the note flag on: a turn that minted 7 calls / 66 rows AND carried three declines
# (a dark board, an off-roster settle, a derived pair with no lane) rendered a block BYTE-IDENTICAL to
# `_numbers_block(calls)` -- no marker, no absence sentence. The design's OWN worked example is that
# shape: cocoa refuses R1-R3 by name and R5 renders, so a cocoa turn shipped a price standing and never
# told the writer the balance sheet was refused. Design 1.5 opens "six refusals, each with its own
# written reason SO THE WRITER'S ABSENCE NARRATION FIRES ON A TRUE SENTENCE rather than a shared one",
# and only the empty leg was wired -- which is exactly section 5's stated failure mode ("the failure is
# NOT a missing figure -- it is a writer that receives fewer rows and fills the gap with prose").
# NO NEW PROMPT SEAM: the sentence rides the EXISTING `scope_note` channel the fold already uses, which
# `_numbers_block` gathers into its SCOPE NOTE run. Reader words only -- `_leg_label` never emits a raw
# slug, so nothing here can reach the model's copy surface as an `register.internal_leaks` charge.
_ABSENCE_ROWS: dict[str, str] = {
    "balance": "no balance-sheet rows at all",
    _SU: "no stocks-to-use row",
    "su_ratio_yoy": "no year-on-year stocks-to-use change",
    _PRODUCTION: "no production row",
    _EXPORTS: "no exports row",
    _IMPORTS: "no imports row",
    _BOARD_ROW: "no exchange settle",
    "price_standing": "no benchmark price level",
    "price_percentile": "no benchmark percentile",
    "price_zscore": "no benchmark sigma",
    "derived_pair": "no paired standing across the two contracts",
    "roster": "no figures at all",
}
_ABSENCE_WHY: dict[str, str] = {
    "psd_absent": "no balance sheet is published for it on this sheet",
    "projection_year": "the marketing year asked about is not closed",
    "no_marketing_year": "no marketing-year calendar is held for it",
    "scope_unresolved": "no primary balance-sheet country is declared for it",
    "empty_card": "the record served no row at that scope and year",
    "world_synthesis_declined": "no summable set of country rows was served",
    "unit_undeclared": "the card declares no unit for it",
    "board_dark": "no front-month settle is admitted at this as-of",
    "off_eod_roster": "no exchange settle is taken for it on this tier",
    "no_benchmark": "no World Bank benchmark corresponds to it",
    "off_price_roster": "no World Bank benchmark corresponds to it",
    "series_too_thin": "its benchmark window served too few dated observations to rank against",
    "stat_declined": "the standing could not be computed from the window served",
    "unreadable_level": "one of the two levels carried no readable figure",
    "no_prior_year": "the previous marketing year did not serve",
    "no_current_year": "the settled marketing year did not serve",
    "vintage_split": "the two prints do not share one release",
    "no_lane": "no paired standing is defined for this pair of contracts",
    "lane_error": "the lookup could not be completed",
    "lane_declined": "the paired standing declined",
    "route_error": "the contract router failed on this turn",
    "unrouted": "no contract was routed for this turn",
}
# NOT NARRATED, each for its own reason: `shared_aggregate` already carries its OWN sentence (the fold's
# note, which says more than an absence line could) and `balance_vintage` WITHHELD NOTHING -- it records
# that this leg's served rows carry different stamps, which every row already prints for itself.
_ABSENCE_SKIP = frozenset({"shared_aggregate", "one_aggregate_two_contracts", "balance_vintage"})
_ABSENCE_CAP = 6


def _decline_label(row: str, slug: str) -> str:
    """Which reader name an ABSENCE sentence calls one leg by -- and it is NOT `_fold_note`'s choice,
    because the two sentences answer different questions. The fold says WHICH AGGREGATE two contracts
    share, so it speaks the aggregate's vocabulary first. An absence says WHICH ROUTED LEG has no row,
    so it prefers the CONTRACT-level label (`cascade._RV_EOD_FRESH`, nine boards) -- which names the leg
    while CLAIMING NO SCOPE. 'no exchange settle for CME palm oil' is exactly true; the same sentence
    over `_xc_label`'s 'world malaysian crude palm oil' would attach a world scope to a board's settle.

    AND THAT IS EXACTLY WHAT IT DID FOR EVERY SLUG OFF THE NINE-BOARD ROSTER (fix pass 2026-09-09,
    review minor): the `off_eod_roster` decline -- the R4 refusal that fires on every routed contract
    the nine-board roster does not carry, i.e. the ORDINARY case, `rapeseed_oil_zce` included -- has no
    `_RV_EOD_FRESH` entry by definition, fell through to `_xc_label`, and shipped 'no exchange settle
    for world rapeseed oil': a WORLD scope attached to a BOARD-level absence, in the one sentence this
    docstring already forbade it in. A BOARD-LEVEL ABSENCE NOW NAMES A BOARD -- the contract-level
    display name ('ZCE rapeseed oil') where the estate holds one. Only where it holds neither does the
    surface's own name stand, and the balance and benchmark rows are untouched: their surface names ARE
    the scope those rows would have carried."""
    eod = cq._RV_EOD_FRESH.get(slug)
    if eod:
        return eod[1]
    if str(row) == _BOARD_ROW:
        board = _contract_name(slug)
        if board:
            return board
    return _leg_label(slug, "price" if str(row).startswith("price") else "world")


def _carry_absences(calls: list, declines: list) -> None:
    """One sentence run naming what this turn REFUSED, appended to the first served call's `scope_note`.

    Fires only on a PARTIAL turn: with no calls there is nothing to hang a note on and
    `_numbers_block`'s empty-leg clause already narrates the whole absence, and with no narratable
    decline nothing is appended and the block is byte-identical."""
    if not calls:
        return
    items: list = []
    for d in (declines or []):
        row, reason = str(d.get("row") or ""), str(d.get("reason") or "")
        if row in _ABSENCE_SKIP or reason in _ABSENCE_SKIP:
            continue
        what, why = _ABSENCE_ROWS.get(row), _ABSENCE_WHY.get(reason)
        if not what or not why:
            continue
        slug = d.get("slug")
        who = _decline_label(row, slug) if (slug and "+" not in str(slug)) else ""
        frag = f"{what} for {who} ({why})" if who else f"{what} ({why})"
        if frag not in items:
            items.append(frag)
    if not items:
        return
    shown = items[:_ABSENCE_CAP]
    tail = ("" if len(items) == len(shown)
            else f"; and {len(items) - len(shown)} further rows refused, each with its own reason")
    note = ("WITHHELD ON THIS TURN, and every one of these is a refusal with a written reason rather "
            "than a thin read: " + "; ".join(shown) + tail + ". State the absence in words where it "
            "bears on the question, and put no estimate, no proxy and no figure from another scope in "
            "its place.")
    calls[0]["scope_note"] = " ".join(x for x in (calls[0].get("scope_note"), note) if x)


def _collide(world_r1: dict) -> dict:
    """(ratio, marketing year) -> the slugs that resolved to it. Exact equality on the rounded value:
    the collision is STRUCTURAL (two slugs fanning onto ONE PSD sheet), so the two reads return the
    identical float, and a tolerance would start folding genuinely different aggregates together."""
    out: dict = {}
    for slug, (pct, my) in (world_r1 or {}).items():
        out.setdefault((round(float(pct), 6), my), []).append(slug)
    return out


def _result(calls: list, declines: list, guards: list, t0: float, form) -> dict:
    """The return shape, assembled in ONE place so no branch above can ship half of it.

    THE DURATION RIDES `numbers_budget`, WHICH IS SURFACED (fix pass 2026-09-08, review minor). The
    top-level `_ms_roster` key is DEAD on the join: `_resolve` copies a fixed six-key tuple plus
    `numbers_budget` and `_ms_numbers`, and the trace surfaces `ms_numbers` -- which `_numbers()` stamps
    itself with the THREAD duration on every path (orchestrator.py:793), agent lane and roster lane
    alike. Section 12's NOT-PROBED list owes the arm `ms_roster`; as built the arm could not see it. It
    is stamped in BOTH places: the top-level key stays for a direct caller, and `roster_ms` inside the
    budget record is the one that actually reaches the trace. The two are the same measurement -- this
    function's own `t0` -- so they cannot drift."""
    tables = sorted({str((c.get("query") or {}).get("table") or "") for c in calls
                     if isinstance(c, dict)} - {""})
    rows = sum(len(c.get("rows") or []) for c in calls if isinstance(c, dict))
    ms = int((time.perf_counter() - t0) * 1000)
    budget: dict = {"roster": True, "lookups": len(calls), "returned": True,
                    "roster_rows": rows, "roster_form": form, "roster_ms": ms,
                    "roster_declines": list(declines)}
    return {"calls": calls,
            "tables_queried": tables,
            "numbers_budget": budget,
            "unit_mismatch_guard": list(guards) or None,
            "_ms_roster": ms,
            # None BY DESIGN, and each for its own reason (1.6(4)):
            "fork_basis": None,            # `answer_numbers` mints none either; the copy-back is guarded
            "pattern_records": None,       # no ledger leg on this lane
            "question_shape": None,        # the three C2 shape keys: no model plan to record a shape
            "shape_metric_states": None,   # against. A REAL loss, not a null column -- named in the
            "shape_decline_guard": None}   # design's honest ledger; `roster_declines` is the stand-in.
