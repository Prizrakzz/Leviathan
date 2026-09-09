"""K9 STOP CENSUS lane deck -- one file, one item per block, every pin measured on the banked panels.

Design: docs/private/K9_STOP_CENSUS_DESIGN.md. Every item ships DARK behind its own flag, and every block
below carries THREE pins in the order the design states them:
  RED   -- the judged panel's STOP sentence becomes impossible to render (or is charged), flag ON;
  GREEN -- the lines the fix must not touch render byte-identically, flag ON;
  OFF   -- with the flag off every label is byte-identical to HEAD, so the rollback is a no-op.

The fixtures are SYNTHETIC BUT REPRODUCING: each one was built in the K9-2 build sitting and verified to
render the banked panel line byte for byte at HEAD (57e523da) before a byte of the fix was written. The
banked artifacts themselves (cascade_baseline_control.json, cascade_baseline_treatment.json and the six
cascade_pair_*.md) are sitting scratch, not repo files, so the strings they produced are frozen here
instead of being re-read at test time.

ARM IDENTITY, because the mask key inverts per pair file: CONTROL = deep, TREATMENT = max.
"""
from __future__ import annotations

import re

from leviathan.graphrag import citations as cit

# ── K9-2 UNSCOPED HEADLINE -- class (7b), flag GRAPHRAG_SCOPE_WITHHOLD ────────────────────────────────
FLAG_K92 = "GRAPHRAG_SCOPE_WITHHOLD"

# The withheld head, verbatim. "geographic scopes" and not the design's "country scopes" because `_geos`
# counts distinct values of the CARD's country_col: measured across the 11 census-A serves, 114 distinct
# values including 'European Union', 'Belgium-Luxembourg', 'Former Yugoslavia' and 'Union of Soviet
# Socialist Repu', and the silver_wasde card's own notes record 'world' / 'major_exporters' /
# 'total_foreign' in its region column.
_WITHHELD = ("ONE SCOPE OF MANY (this read spans {k} geographic scopes and names none; the newest row is "
             "one of them, not a figure for the commodity)")

# 32 distinct PSD country-axis scopes -- the count `served_rows` carries for the deep rv_canola_rapeoil
# production_mt reads, and the number the withhold label must state.
_C32 = ["Algeria", "Argentina", "Austria", "Bangladesh", "Belarus", "Belgium-Luxembourg", "Brazil",
        "Canada", "Chile", "China", "Colombia", "Czechia", "Denmark", "Egypt", "Ethiopia", "France",
        "Germany", "India", "Iran", "Japan", "Kazakhstan", "Mexico", "Netherlands", "Pakistan", "Poland",
        "Romania", "Russia", "Sweden", "Ukraine", "United Kingdom", "United States", "Uruguay"]


def _unscoped_multigeo(metric: str, commodity: str, n_rows: int, head_value: str,
                       countries=_C32, first="2006-06-09", last="2026-08-12"):
    """A census-(A) call: the QUERY names no country, the rows span many, and `from_number` headlines
    `max(rows, _row_order_key)` -- ONE arbitrary country's row under a label that scopes nothing."""
    rows = [{"period": "1964", "value": "1000.0", "unit": None,
             "country": countries[k % len(countries)], "knowledge_date": first}
            for k in range(n_rows - 1)]
    rows.append({"period": "2026", "value": head_value, "unit": None,
                 "country": countries[0], "knowledge_date": last})
    return {"query": {"table": "silver_psd", "metric": metric, "commodity": commodity,
                      "country": None, "period": None, "asof": "2026-09-06"},
            "rows": rows, "status": "ok"}


# The four banked panel lines this item is pinned on, verbatim from the pair files (the `[N..]` handle and
# the trailing `[known ...]` stamp are added by the renderers above `from_number` and are not part of the
# label). deep = cascade_pair_rv_canola_rapeoil.md:589-590 (ANSWER B); max = the same file :375-376.
_BANKED = {
    "deep_N25": ("USDA PSD production ICE canola = 22,500,000 MT "
                 "[1931 rows served, covering 2006-06-09..2026-08-12; newest shown]"),
    "deep_N26": ("USDA PSD production ZCE rapeseed oil = 10,542,000 MT "
                 "[2391 rows served, covering 2006-06-09..2026-08-12; newest shown]"),
    "max_N9": ("USDA PSD stocks-to-use ratio ICE canola = 9 ratio "
               "[1907 rows served, covering 2006-06-09..2026-08-12; newest shown]"),
    "max_N10": ("USDA PSD stocks-to-use ratio ZCE rapeseed oil = 18.75 ratio "
                "[2216 rows served, covering 2006-06-09..2026-08-12; newest shown]"),
}
_CENSUS_A = {
    "deep_N25": _unscoped_multigeo("production_mt", "canola_ice", 1931, "22500000.0"),
    "deep_N26": _unscoped_multigeo("production_mt", "rapeseed_oil_zce", 2391, "10542000.0"),
    "max_N9": _unscoped_multigeo("su_ratio", "canola_ice", 1907, "9.0"),
    "max_N10": _unscoped_multigeo("su_ratio", "rapeseed_oil_zce", 2216, "18.75"),
}


def _one_row_scoped():
    """GREEN, deep rv_canola_rapeoil [N29]: the query NAMES Canada and one row answers it. Outside the
    class on both conditions, and the line the writer's one correct scoped sentence was built on."""
    return {"query": {"table": "silver_psd", "metric": "su_ratio", "commodity": "canola_ice",
                      "country": "Canada", "period": "2026", "asof": "2026-09-06"},
            "rows": [{"period": "2026", "value": 16.84722222222222, "unit": "%",
                      "country": "Canada", "knowledge_date": "2026-08-12"}],
            "status": "ok"}


def _zero_scope_fx():
    """GREEN, the measured ZERO-SCOPE class: 4 banked multi-row calls carry NO country value on any row
    (silver_fred_fx.inr_usd -- deep rv_palm_rapeoil N21/N22, max N8/N9). A read whose rows name no scope
    is not a read that names one of many, so the withhold may not touch it."""
    rows = [{"period": None, "value": v, "unit": None, "country": None, "knowledge_date": d}
            for v, d in (("68.14", "2017-01-02"), ("67.20", "2017-01-20"), ("66.608", "2017-02-24"))]
    return {"query": {"table": "silver_fred_fx", "metric": "inr_usd", "commodity": None,
                      "country": None, "period": None, "asof": "2017-03-01"},
            "rows": rows, "status": "ok"}


def _one_scope_free_axis():
    """GREEN, the ONE-SCOPE FREE-AXIS class -- the shape the first deck left unpinned (review MINOR-2), and
    the one a `len(_geos) > 1` -> `> 0` mutation would silently claim. The query names no country and the
    rows are UNANIMOUS on one, so `_dest_coded('silver_psd')` is False (the card declares no
    `country_name_ref` and no destination axis) and the free-axis fallback correctly stamps 'Canada'. A
    read that names ONE scope is not a read that names one of many: the value must survive."""
    return {"query": {"table": "silver_psd", "metric": "production_mt", "commodity": "canola_ice",
                      "country": None, "period": None, "asof": "2026-09-06"},
            "rows": [{"period": "2024", "value": "19000000.0", "unit": None,
                      "country": "Canada", "knowledge_date": "2024-08-12"},
                     {"period": "2025", "value": "20000000.0", "unit": None,
                      "country": "Canada", "knowledge_date": "2025-08-12"},
                     {"period": "2026", "value": "22500000.0", "unit": None,
                      "country": "Canada", "knowledge_date": "2026-08-12"}],
            "status": "ok"}


def _cotton_region_split():
    """GREEN, THE ONE-COUNTRY WIDENING -- the shape review MAJOR-1 reproduced on the real registry, and the
    reason the scope count never rides a value-bearing label. configs/graphrag/numbers/tables.yaml:455-457
    widens `cotton` to `region: ['u_s_cotton', 'united_states']` ("the US cotton farm price lives under
    BOTH region codes across the 2011 break"), so a read that NAMES `united_states` comes back with two
    distinct values in the row `country` alias -- ONE country under two region codes. A scope count here
    would mint "across 2 country scopes" onto a US series in the reader's `## Sources`: a false geographic
    fact, which is the very class this item exists to kill. Nothing may fire on it."""
    return {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "cotton",
                      "country": "united_states", "period": None, "asof": "2026-09-06"},
            "rows": [{"period": "2011/12", "value": "88.3", "unit": "c/lb", "country": "u_s_cotton",
                      "knowledge_date": "2011-08-11"},
                     {"period": "2018/19", "value": "70.3", "unit": "c/lb", "country": "united_states",
                      "knowledge_date": "2018-09-12"},
                     {"period": "2026/27", "value": "68.09", "unit": "c/lb", "country": "united_states",
                      "knowledge_date": "2026-07-10"}],
            "status": "ok"}


def _stale_span_unscoped():
    """A census-(A) call carrying BOTH provenance clauses the first build dropped: the staleness affordance
    (8 of the 11 banked census-A lines carry it) and the marker's `, covering {span}` (5 of 11). Both must
    survive the withhold -- the design authorized removing `value` and `unit`, and nothing else."""
    return {"query": {"table": "silver_psd", "metric": "production_mt", "commodity": "canola_ice",
                      "country": None, "period": None, "asof": "2026-09-06"},
            "rows": [{"period": "2006", "value": "1000.0", "unit": None, "country": "China",
                      "knowledge_date": "2006-06-09"},
                     {"period": "2006", "value": "391000.0", "unit": None, "country": "Canada",
                      "knowledge_date": "2016-04-12"}],
            "status": "ok"}


def _truncated_unscoped():
    """A census-(A) call that came back AT its row cap -- the worst case review MAJOR-2 reproduced. The
    class is live on the banked set (the largest census-A serve is 4,759 rows, max rv_soyoil_palm), and
    `orchestrator._numbers_block` gates its TRUNCATED directive on `agent.series_truncated` over the CALLS,
    never on the label, so a withheld line that dropped the annotation would leave the writer instructed to
    "state the span the marked line names" about a line carrying no marker."""
    rows = [{"period": str(2020 + k), "value": f"{1000 + k}.0", "unit": None,
             "country": _C32[k], "knowledge_date": f"2026-08-0{k + 1}"} for k in range(5)]
    return {"query": {"table": "silver_psd", "metric": "production_mt", "commodity": "canola_ice",
                      "country": None, "period": None, "agg": "series", "limit": 5,
                      "asof": "2026-09-06"},
            "rows": rows, "status": "ok"}


_EXTRAS = {"green_N29": _one_row_scoped, "green_fx": _zero_scope_fx,
           "green_one_scope": _one_scope_free_axis, "green_cotton": _cotton_region_split,
           "stale_span": _stale_span_unscoped, "truncated": _truncated_unscoped}


def _labels(monkeypatch, flag_value):
    """Every fixture's (label, value, unit) at one flag setting."""
    if flag_value is None:
        monkeypatch.delenv(FLAG_K92, raising=False)
    else:
        monkeypatch.setenv(FLAG_K92, flag_value)
    out = {}
    for k, call in list(_CENSUS_A.items()) + [(k, f()) for k, f in _EXTRAS.items()]:
        c = cit.from_number(call, 1)
        out[k] = (c.label, c.value, c.unit)
    return out


# ── OFF PIN: the rollback is a no-op ─────────────────────────────────────────────────────────────────
def test_k9_2_flag_off_is_byte_identical_to_the_banked_panel(monkeypatch):
    """The flag unset and the flag explicitly off both render the banked panel line byte for byte, on
    BOTH arms. Measured in the build sitting over all 509 banked calls of the 12 panels: 0 diffs against
    HEAD's `from_number` with the flag unset, 0 with it 'off', 11 with it 'on' -- and all 11 are the
    census-(A) lines pinned below."""
    for setting in (None, "off", ""):
        got = _labels(monkeypatch, setting)
        for key, banked in _BANKED.items():
            assert got[key][0] == banked, f"{key} moved with the flag {setting!r}"
        assert got["deep_N25"][1] == "22500000.0" and got["deep_N25"][2] == "MT"
        assert got["max_N9"][1] == "9.0" and got["max_N9"][2] == "ratio"
        # no label anywhere gains a scope clause, and "newest shown" is untouched
        for key, (label, _v, _u) in got.items():
            assert "geographic scopes" not in label and "newest withheld" not in label, key


# ── RED PINS: the judged STOP first, then the same engine shape one arm over ──────────────────────────
#
# WHICH LINE THE PANEL ACTUALLY STOPPED, because these two docstrings used to say the other one (verify
# K9-2-2-MAJOR-2). Cross-checked by [N] index against `cascade_panel.json`'s two stop lists: of the 11
# census-A lines, exactly TWO are named inside a recorded STOP -- max rv_canola_rapeoil [N9] and [N10],
# the ONE judged pair, printed in TWO stopped sentences. The deep [N25]/[N26] line is NOT a stop; the
# panel's `uncited` bucket calls its setting-aside "disclosed and correct". The remaining 9 census-A
# lines are prevention: the panel charged them nothing.
def test_k9_2_red_max_su_ratio_nine_ratio_cannot_be_rendered(monkeypatch):
    """THE JUDGED TRIGGER, RED. `cascade_panel.json` `stops.treatment[23]`, id rv_canola_rapeoil
    (TREATMENT = max; the sentence's home is cascade_pair_rv_canola_rapeoil.md:28, ANSWER A): "ICE canola
    stocks-to-use: 9 ratio [N9]; ZCE rapeseed oil stocks-to-use: 18.75 ratio [N10]; Canadian canola
    stocks-to-use for the current year: 16.8472% [N18] on 9.4 M ha harvested [N19]." The judge's own
    reason IS this withhold: "no scope label -- world, Canada, China -- is attached to N9 or N10 to make
    the pair commensurate", beside "a stocks-to-use of 9 'ratio' is 900 percent if the unit label is
    taken literally". The same pair is stopped again in the TL;DR at pair-file :12 (`stops.treatment[22]`
    and `[24]`), and `stops.treatment[25]` charges the derived line "Seed carries the thinner cushion on
    the served rows; oil carries the thicker one." on the same premise with no handle of its own. Flag ON
    neither ratio prints, so neither figure is there to copy. The banked labels are pair-file :375-376.
    THE SCOPE COUNT IN THE LAST ASSERTION IS THE FIXTURE'S ROSTER, NOT A MAX-ARM FIGURE, and stating that
    is the same discipline that re-led this pin. `_C32` is the DEEP production_mt count; `served_rows`
    banks 31 distinct country values for max [N9] and 33 for [N10] in 40 of 1,907 / 2,216 rows, and those
    are LOWER BOUNDS because `rows` is truncated in the artifact. So what this line pins is the SHAPE --
    a scope count, stated on the withheld label and nowhere else -- and the count over the live serve is
    in no artifact this deck can read."""
    got = _labels(monkeypatch, "on")
    assert "= 9 ratio" not in got["max_N9"][0] and got["max_N9"][1] is None
    assert "= 18.75 ratio" not in got["max_N10"][0] and got["max_N10"][1] is None
    assert "spans 32 geographic scopes" in got["max_N9"][0]


def test_k9_2_red_deep_canola_world_levels_cannot_be_rendered(monkeypatch):
    """THE SAME ENGINE SHAPE ON THE DEEP ARM, AND THE PANEL DID NOT STOP IT -- so this pin holds the
    RENDER half only, not a judged provenance. MEASURED: `cascade_panel.json` contains "World production"
    ZERO times, and its control stop list holds exactly four rv_canola_rapeoil entries, none of them this
    sentence (the N34/N37 uncited-prior pair, the N33 pace-streak direction twice, the "state reserve
    activity" driver). Where the panel speaks to the line it says the opposite of a stop: "B: [N25]
    22,500,000 MT and [N26] 10,542,000 MT are cited and then explicitly set aside as non-comparable --
    cited but not used, though the setting-aside is disclosed and correct."
    WHAT IS STILL WRONG WITH IT IS THE ENGINE'S HALF: at cascade_pair_rv_canola_rapeoil.md:404 (ANSWER B
    = control = DEEP) the writer supplies a scope no row carries, off a query naming no country over 32
    PSD country scopes, and the word he supplies is "World". Flag ON neither level prints, so that word
    has no figure to sit on. The sentence is quoted WHOLE, with the trailing disclosure the judge
    approved, in `_MECH_DEEP_CANOLA` below -- truncating it at the first em dash is what turned it into a
    "STOP sentence" in the first place. That disclosure stays on the page
    (`answer._sentence_has_resolved_handle`); nothing here licenses deleting it."""
    got = _labels(monkeypatch, "on")
    for key, token in (("deep_N25", "22,500,000"), ("deep_N26", "10,542,000")):
        label, value, unit = got[key]
        assert token not in label, f"{key} still prints the token the writer's sentence copied"
        assert value is None and unit is None      # `answer._number_handle_value` reads Citation.value
        assert _WITHHELD.format(k=32) in label
    # the commodity and the source still name themselves: the class is about the FIGURE, not the read
    assert got["deep_N25"][0].startswith("USDA PSD production ICE canola = ")
    assert got["deep_N26"][0].startswith("USDA PSD production ZCE rapeseed oil = ")


# ── THE WITHHELD LINE KEEPS ITS PROVENANCE (review MAJOR-2) ──────────────────────────────────────────
def test_k9_2_withheld_line_keeps_the_abundance_marker_and_its_span(monkeypatch):
    """The withhold replaces the `= {value} {unit}` head and NOTHING else. Measured over the 11 banked
    census-A lines at HEAD: all 11 carry the PA-8(a) marker, 5 carry its `, covering {span}` clause and 8
    carry the staleness clause -- the first build dropped every one of them, which `citations.render`
    passes straight to the reader's `## Sources` (label + `[known ...]`, nothing else)."""
    got = _labels(monkeypatch, "on")
    assert got["deep_N25"][0] == (
        "USDA PSD production ICE canola = " + _WITHHELD.format(k=32)
        + " [1931 rows served, covering 2006-06-09..2026-08-12; newest withheld]")
    # the ONE word the withhold makes false is the only one that moves
    assert got["deep_N25"][0].replace("newest withheld", "newest shown") == (
        _BANKED["deep_N25"].replace("= 22,500,000 MT", "= " + _WITHHELD.format(k=32)))


def test_k9_2_withheld_line_keeps_the_staleness_clause(monkeypatch):
    """8 of the 11 banked census-A lines carry `(latest available YYYY-MM-DD; as-of ...)`; deep
    rv_canola_rapeoil #25 carries it beside a span. Both ride the withheld label."""
    on, off = _labels(monkeypatch, "on"), _labels(monkeypatch, None)
    assert off["stale_span"][0] == ("USDA PSD production ICE canola = 391,000 MT "
                                    "(latest available 2016-04-12; as-of 2026-09-06) "
                                    "[2 rows served, covering 2006-06-09..2016-04-12; newest shown]")
    assert on["stale_span"][0] == ("USDA PSD production ICE canola = " + _WITHHELD.format(k=2)
                                   + " (latest available 2016-04-12; as-of 2026-09-06) "
                                     "[2 rows served, covering 2006-06-09..2016-04-12; newest withheld]")
    assert on["stale_span"][1] is None and on["stale_span"][2] is None


def test_k9_2_withheld_line_keeps_the_truncation_fence(monkeypatch):
    """D-PQ RENDER-3, the fence whose own note records the measured failure it exists to prevent (a
    5000-row-capped corn read sold as "the full-history trading range on record"). The withheld line must
    carry the annotation, because `orchestrator._numbers_block` still emits the directive that points at
    it -- that gate reads `agent.series_truncated` over the CALLS, not the labels."""
    from leviathan.graphrag.numbers.agent import series_truncated
    call = _truncated_unscoped()
    assert series_truncated(call) is True          # the directive WILL fire on this call
    on = _labels(monkeypatch, "on")
    assert on["truncated"][1] is None and on["truncated"][2] is None
    assert ("[TRUNCATED at the 5-row cap: NEWEST slice only, covering 2026-08-01..2026-08-05 "
            "-- not the complete record]") in on["truncated"][0]
    assert "[5 rows served; newest withheld]" in on["truncated"][0]


# ── GREEN PIN: what the fix must not touch ────────────────────────────────────────────────────────────
def test_k9_2_green_scoped_and_zero_scope_reads_are_byte_identical(monkeypatch):
    """deep [N29] renders byte-identically (a query that names Canada, one row that answers it), and so
    does the zero-scope silver_fred_fx.inr_usd class -- 4 banked multi-row calls carrying no country value
    on any row. Neither may gain a withhold."""
    off, on = _labels(monkeypatch, None), _labels(monkeypatch, "on")
    assert on["green_N29"] == off["green_N29"]
    assert on["green_N29"][0] == "USDA PSD stocks-to-use ratio ICE canola Canada MY2026 = 16.8472 %"
    assert on["green_fx"] == off["green_fx"]
    assert "ONE SCOPE OF MANY" not in on["green_fx"][0]
    assert on["green_fx"][1] == "66.608"           # the newest row still headlines, value intact
    assert "[3 rows served, covering 2017-01-02..2017-02-24; newest shown]" in on["green_fx"][0]


def test_k9_2_green_one_scope_free_axis_read_keeps_its_figure(monkeypatch):
    """MINOR-2: the query names NO country and the rows are unanimous on ONE, so the free-axis fallback
    names it. Measured 0 of the 509 banked calls fall in this shape (the 36 multi-row calls split 4
    zero-scope / 11 census-A / 21 query-scoped), which is exactly why it needs its own fixture: without
    it a `len(_geos) > 1` -> `> 0` mutation passes the whole deck."""
    off, on = _labels(monkeypatch, None), _labels(monkeypatch, "on")
    assert on["green_one_scope"] == off["green_one_scope"]
    assert on["green_one_scope"][0] == ("USDA PSD production ICE canola Canada = 22,500,000 MT "
                                        "[3 rows served, covering 2024-08-12..2026-08-12; newest shown]")
    assert on["green_one_scope"][1] == "22500000.0" and on["green_one_scope"][2] == "MT"


def test_k9_2_green_one_country_widening_gains_nothing(monkeypatch):
    """MAJOR-1, re-pinned on the shape that reproduced it: a scoped US cotton farm-price series whose rows
    carry BOTH `u_s_cotton` and `united_states` because the card widens the region filter across the 2011
    break. Two distinct country-column values, ONE country -- so no scope count may appear, on this label
    or any other value-bearing one, at any flag setting."""
    off, on = _labels(monkeypatch, None), _labels(monkeypatch, "on")
    assert on["green_cotton"] == off["green_cotton"]
    assert on["green_cotton"][0] == ("USDA WASDE average farm price ICE cotton united_states = 68.09 c/lb "
                                     "(latest available 2026-07-10; as-of 2026-09-06) "
                                     "[3 rows served, covering 2011-08-11..2026-07-10; newest shown]")
    assert "scopes" not in on["green_cotton"][0]
    # and the count never rides a value-bearing label anywhere: with the flag ON, every fixture that keeps
    # its figure keeps HEAD's label exactly.
    for key in ("green_N29", "green_fx", "green_one_scope", "green_cotton"):
        assert on[key] == off[key], key


def test_k9_2_withhold_and_zero_aggregate_are_disjoint_by_construction():
    """`agent._is_zero_esr_aggregate` requires `len(rows) == 1`; more than one distinct country value needs
    at least two rows. The branch is still ordered second so a pinned label never depends on that argument
    being re-made -- this test is the argument, made once."""
    from leviathan.graphrag.numbers.agent import _is_zero_esr_aggregate
    call = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "sum",
                      "commodity": "corn_cbot", "country": None, "period": "2025", "asof": "2026-09-06"},
            "rows": [{"value": "0.0", "country": "China", "knowledge_date": "2026-08-12"}],
            "status": "ok"}
    assert _is_zero_esr_aggregate(call) is True
    geos = {str(r.get("country")).strip() for r in call["rows"] if str(r.get("country") or "").strip()}
    assert len(geos) == 1                          # one row can never span two scopes


# ── K9-2 FIX-PASS (verify MAJOR-1): THE POST-HOC FENCE, MEASURED AND THEN MADE REAL ───────────────────
#
# THE FINDING, reproduced on the banked prose before a byte was written (both baselines, all 12
# `raw_draft`s, both `handle_prose` settings, flag ON): the K9-2 block note declared "a handle pointing at
# it is dropped AND ITS CLAUSE CUT after the writer has written it", and the census came back
# `{handles_dropped: 6, sentences_dropped: 0}` with NOT ONE clause cut -- `answer._resolve_number_handles`
# reaches the sever/kill rungs only through `standin` (the handle in a VALUE SLOT), and the census-A
# handles follow the model's own digit, so every one took the BARE TOKEN DROP. `_cited_sources_block`
# builds `## Sources` from the indices the PROSE still carries, so the figure stayed and its row left:
#   max rv_canola_rapeoil TL;DR, flag ON, before the fix
#     "ICE canola stocks-to-use reads 9 ratio against 18.75 ratio for ZCE rapeseed oil"
#     ## Sources rows LOST: [N9, N10]      (deep rv_canola_rapeoil: the same on [N25]/[N26])
# -- a stated figure with its receipt deleted, worse than HEAD, and invisible to the anti-suppression
# floor because `verify` computes `claim_count` on the PRE-resolution prose.
#
# THE SEVER VARIANT WAS BUILT AND MEASURED BEFORE IT WAS REJECTED. Forcing `standin = True` for the class
# over the same 12 answers gives `{handles_dropped: 2, sentences_dropped: 3}` (control lane, handle_prose
# False) and does NOT repair the pinned line: `_handle_clause_start` takes the last connective and then
# falls back to the value cue, and in front of `[N9]` the segment ends "... reads 9 ratio " -- neither --
# so the clause start degenerates to the handle and the "severance" IS the bare drop. Where it DOES fire
# it kills deep rv_canola_rapeoil's whole sentence, including the half `cascade_panel.json` recorded as
# CORRECT ("cited but not used, THOUGH THE SETTING-ASIDE IS DISCLOSED AND CORRECT"). So the fence
# CORRECTS instead: the handle stays, and the reader gets the withhold in his own `## Sources` row.
#
# ── RE-FIX PASS (verify K9-2-2-MAJOR-1): THAT "AFTER" WAS MEASURED ON THE WRONG CHAIN ────────────────
# It read "handles_dropped 0, sentences_dropped 0, Sources rows lost 0, withheld-class handles the
# reader still holds 6/6". True of `_resolve_number_handles` ALONE -- which is all the replay ran, and
# all the `handle_prose=True` leg below ran. But on that lane the production stack (answer.py:4216-4227
# and :10513-10517) runs `_drop_bare_digit_sentences` IMMEDIATELY BEFORE it, and THAT stage's
# sever-vs-kill discriminator `answer._sentence_has_resolved_handle` reads the same `Citation.value` the
# withhold empties. THE FLAG THEREFORE CONVERTED A SEVER INTO A KILL one seam upstream of the fence,
# and what it killed was the sentence the paragraph above says the rejected sever variant was not
# shipped in order to protect. MEASURED over the 12 banked answers in production order, flag off -> on:
#   bare-digit `{sentences_dropped 77, clauses_severed 90}` -> `{78, 89}`
#   deep rv_canola_rapeoil lost the WHOLE of "- World production levels exist for each side -- canola
#     22,500,000 MT [N25] and rapeseed oil 10,542,000 MT [N26] -- but these are tonnage levels of
#     different commodities and are not comparable to each other", the half `cascade_panel.json` calls
#     "cited but not used, though the setting-aside is disclosed and correct"
#   `## Sources` rows lost across the 12: 86 -> 87, and control rv_canola_rapeoil also lost [N26]
# THE REMEDY IS THE SAME DOCTRINE AT THE SEAM THAT CAN REACH IT: a withheld-and-kept token is a receipt
# the sentence keeps, so `_sentence_has_resolved_handle` counts it. RE-MEASURED, production order,
# flag off -> on: bare-digit `{77, 90, e_cited_kept 12}` IDENTICAL, `handles_dropped` 0 and
# `sentences_dropped` 0 IDENTICAL, `## Sources` rows lost 86 -> 86 IDENTICAL. The flag adds no deletion
# anywhere in the chain, and `test_k9_2_refix_the_stage_one_seam_earlier_may_not_convert_a_sever_to_a
# _kill` below pins the production stack rather than this pass alone.
# THE COVERAGE FIGURE IS RESTATED HONESTLY AND IT IS NOT 6/6. The model wrote 6 withheld-class handle
# INSTANCES (deep [N25] x1, [N26] x1; max [N9] x2, [N10] x2). In production order 2 reach the reader --
# AT BOTH FLAG SETTINGS. The other 4 sit in sentences the bare-digit stage deletes at HEAD too, the max
# rv_canola_rapeoil TL;DR clause of `_TLDR_MAX_CANOLA` among them, so they are a PRE-EXISTING loss this
# item neither mints nor repairs. Post-resolution coverage on the class: 2 of 6, off and on, delta zero.
_TLDR_MAX_CANOLA = (
    "On the newest served rows the seed sheet is the tighter of the two -- ICE canola stocks-to-use "
    "reads 9 ratio [N9] against 18.75 ratio for ZCE rapeseed oil [N10], and Canadian canola "
    "stocks-to-use for the current marketing year reads 16.8472% [N18] -- so the seed leg is where a "
    "supply shock turns convex first.")


def _prose_calls():
    """The banked max rv_canola_rapeoil call list, in the ONE respect the handle pass reads it: index 9
    and index 10 are the two census-A withheld reads, index 18 is the scoped one-row read the same
    sentence cites. Filler keeps the 1-based indices honest -- `[N]` handles are POSITIONAL."""
    return ([_one_row_scoped() for _ in range(8)]
            + [_CENSUS_A["max_N9"], _CENSUS_A["max_N10"]]
            + [_one_row_scoped() for _ in range(7)]
            + [_one_row_scoped()])


def _resolve(monkeypatch, flag_value, text, calls, handle_prose=False):
    from leviathan.graphrag import answer as an
    if flag_value is None:
        monkeypatch.delenv(FLAG_K92, raising=False)
    else:
        monkeypatch.setenv(FLAG_K92, flag_value)
    st = {"tldr": text, "mechanism": ""}
    census = an._resolve_number_handles(st, calls, handle_prose=handle_prose)
    return st["tldr"], census


def _sources_indices(text):
    """The [N] indices `answer._cited_sources_block` will emit a row for -- the reader's own prose is the
    authority in both directions (D-PQ HANDLE-4), so this IS the Sources row set."""
    from leviathan.graphrag import answer as an
    out = []
    for m in an._N_HANDLE_RX.finditer(text):
        for i in an._n_handle_members(m.group(0)):
            if i not in out:
                out.append(i)
    return out


def test_k9_2_fix_the_withheld_figures_receipt_is_never_the_thing_deleted(monkeypatch):
    """RED, and it is the verifier's own reproduced case: the max rv_canola_rapeoil TL;DR. Flag ON, the
    two withheld handles STAY on the page, `## Sources` keeps every row it carries at flag off, and
    nothing is dropped or killed. Before the fix this same fixture dropped both handles and lost both
    rows, leaving "reads 9 ratio against 18.75 ratio" with no receipt behind either figure."""
    off_text, off_census = _resolve(monkeypatch, None, _TLDR_MAX_CANOLA, _prose_calls())
    on_text, on_census = _resolve(monkeypatch, "on", _TLDR_MAX_CANOLA, _prose_calls())
    assert off_text == _TLDR_MAX_CANOLA            # OFF: the pass is inert on this shape
    assert on_text == _TLDR_MAX_CANOLA             # ON: and it stays inert on the PAGE
    assert "[N9]" in on_text and "[N10]" in on_text
    assert _sources_indices(on_text) == _sources_indices(off_text) == [9, 10, 18]
    assert on_census["handles_dropped"] == 0 and on_census["sentences_dropped"] == 0
    assert off_census["handles_dropped"] == 0 and off_census["sentences_dropped"] == 0
    # the figure the reader keeps now carries the correction, in the footer row he checks it in
    monkeypatch.setenv(FLAG_K92, "on")
    row = cit.from_number(_CENSUS_A["max_N9"], 9)
    assert row.value is None and _WITHHELD.format(k=32) in row.label
    # ...and the counters still record what the MODEL ADDRESSED, unchanged: a menu row carrying no value
    assert on_census["unresolvable"] == 2          # control census; treatment charges empty_row_addressed
    # ...and the same on the TREATMENT lane. Its own `handle_prose` splice moves the RESOLVED [N18] (it
    # splices "16.8472 %" in front of a prose "16.8472%" that `_figure_already_stated` does not recognise
    # across the space -- HEAD behaviour, both flag settings, and not this class), so the withheld halves
    # are asserted directly rather than through whole-field equality.
    hp_text, hp_census = _resolve(monkeypatch, "on", _TLDR_MAX_CANOLA, _prose_calls(), handle_prose=True)
    assert "reads 9 ratio [N9] against 18.75 ratio for ZCE rapeseed oil [N10]" in hp_text
    assert 9 in _sources_indices(hp_text) and 10 in _sources_indices(hp_text)
    assert hp_census["empty_row_addressed"] == 2 and hp_census["unresolvable"] == 0
    assert hp_census["handles_dropped"] == 0 and hp_census["sentences_dropped"] == 0
    # SCOPE OF THIS PIN, NAMED (re-fix pass): this leg runs `_resolve_number_handles` ALONE, which is one
    # stage of the treatment lane and not the lane. The stage that runs before it is pinned in
    # `test_k9_2_refix_the_stage_one_seam_earlier_may_not_convert_a_sever_to_a_kill`, and the reason the
    # split matters is that in production this very TL;DR clause is deleted by that stage at BOTH flag
    # settings -- a pre-existing loss, measured, and not repaired by anything in this item.


# The DEEP pin sentence, verbatim from cascade_pair_rv_canola_rapeoil.md:404 (ANSWER B = control = deep)
# and from that answer's banked `raw_draft.mechanism`. `cascade_panel.json` puts it in the `uncited`
# bucket with the verdict "cited but not used, THOUGH THE SETTING-ASIDE IS DISCLOSED AND CORRECT", so the
# trailing half is a judged-correct disclosure and deleting it to remove a marker is suppress-not-correct.
# The em dashes are the banked bytes (U+2014) and are NOT load-bearing: measured, the ASCII `--` spelling
# gives the identical census at both flag settings. They are kept because the pin claims verbatim.
_MECH_DEEP_CANOLA = (
    "- World production levels exist for each side — canola 22,500,000 MT [N25] and rapeseed oil "
    "10,542,000 MT [N26] — but these are tonnage levels of different commodities and are not "
    "comparable to each other;")


def _deep_prose_calls():
    """The banked deep rv_canola_rapeoil list in the ONE respect this stage reads it: 25 and 26 are the
    census-A withheld production reads. Filler keeps the 1-based indices honest -- `[N]` is POSITIONAL."""
    return [_one_row_scoped() for _ in range(24)] + [_CENSUS_A["deep_N25"], _CENSUS_A["deep_N26"]]


def _prod_stack(monkeypatch, flag_value, text, calls):
    """THE TREATMENT LANE IN PRODUCTION ORDER, answer.py:4216-4227 and :10513-10517 -- the bare-digit
    stage FIRST (it is gated on `_handles`, so it exists on this lane and only this lane), then the
    handle pass. Every earlier K9-2 measurement ran the second stage alone; that is the whole finding."""
    from leviathan.graphrag import answer as an
    if flag_value is None:
        monkeypatch.delenv(FLAG_K92, raising=False)
    else:
        monkeypatch.setenv(FLAG_K92, flag_value)
    st = {"tldr": "", "mechanism": text}
    bd = an._drop_bare_digit_sentences(st, calls, None, uniq=None)
    mid = st["mechanism"]
    nh = an._resolve_number_handles(st, calls, handle_prose=True)
    return bd, mid, nh, st["mechanism"]


def test_k9_2_refix_the_stage_one_seam_earlier_may_not_convert_a_sever_to_a_kill(monkeypatch):
    """RED (DEEP), verify K9-2-2-MAJOR-1, and it is the production stack rather than one stage of it.

    `_drop_bare_digit_sentences` runs immediately BEFORE `_resolve_number_handles` on the `handle_prose`
    lane, and its sever-vs-kill discriminator `_sentence_has_resolved_handle` reads the same
    `Citation.value` the K9-2 withhold empties. Before the re-fix the flag turned this sentence's SEVER
    into a WHOLE-SENTENCE KILL and took the judged-correct disclosure with it -- measured over the 12
    banked answers as `{sentences_dropped 77, clauses_severed 90}` -> `{78, 89}` and one more `## Sources`
    row lost. The fix is the doctrine the downstream pass already adopted, applied where it can reach:
    a withheld-and-kept token is a receipt the sentence keeps."""
    bd_off, mid_off, _nh_off, _end_off = _prod_stack(monkeypatch, None, _MECH_DEEP_CANOLA,
                                                     _deep_prose_calls())
    bd_on, mid_on, nh_on, end_on = _prod_stack(monkeypatch, "on", _MECH_DEEP_CANOLA,
                                               _deep_prose_calls())
    # THE BAR: the stage the flag must not move does not move, byte for byte and counter for counter.
    assert bd_off == bd_on == {"sentences_dropped": 0, "clauses_severed": 1, "e_cited_kept": 0}
    assert mid_off == mid_on
    # ...it SEVERS the unscoped clause and KEEPS the sentence, at both settings
    assert "22,500,000" not in mid_on
    assert "not comparable to each other" in mid_on         # the judged-correct disclosure survives
    # ...and the surviving withheld handle is still on the page, so `## Sources` still answers for it
    assert "[N26]" in end_on and 26 in _sources_indices(end_on)
    assert nh_on["handles_dropped"] == 0 and nh_on["sentences_dropped"] == 0
    assert nh_on["empty_row_addressed"] == 1                # the withhold's own accounting, unchanged
    # THE ASSERTION IS LOAD-BEARING: neutralise ONLY the new clause and the sentence dies whole, which is
    # the state the verifier measured. Without this leg the pin above would pass over a no-op.
    from leviathan.graphrag import answer as an
    monkeypatch.setattr(an, "_scope_withheld_token", lambda calls, pairs: False)
    bd_pre, mid_pre, _n, _e = _prod_stack(monkeypatch, "on", _MECH_DEEP_CANOLA, _deep_prose_calls())
    assert bd_pre == {"sentences_dropped": 1, "clauses_severed": 0, "e_cited_kept": 0}
    assert mid_pre.strip() == ""                            # disclosure and all


def test_k9_2_refix_the_discriminator_is_one_producer_and_fails_closed(monkeypatch):
    """`_sentence_has_resolved_handle` reads the withheld verdict through `_scope_withheld_token` -- the
    SAME producer, with the SAME `all`-not-`any` rule, as the pass downstream -- so the two stages can
    never disagree about which marker the reader ends up holding. Flag OFF it can never fire."""
    from leviathan.graphrag import answer as an
    calls = _deep_prose_calls()
    text = _MECH_DEEP_CANOLA
    s0, s1 = an._handle_sentence_span(text, text.find("World"))
    skip = (text.index("canola 22,500,000"), text.index("] and") + 1)
    monkeypatch.delenv(FLAG_K92, raising=False)
    assert an._sentence_has_resolved_handle(text, s0, s1, calls, skip=skip) is True   # [N26] resolves
    monkeypatch.setenv(FLAG_K92, "on")
    assert an._sentence_has_resolved_handle(text, s0, s1, calls, skip=skip) is True   # ...and is kept
    # FAILS CLOSED on a token the downstream pass would REMOVE: a mixed group is not a kept receipt here.
    # `[N99]` names no call, so `all(...)` is False and the token takes today's removal -- and with the
    # only other handle inside the cut, nothing outside it resolves. Flag ON is the interesting setting:
    # at flag OFF `[N26]` resolves on its own value and the question never reaches the new clause.
    mixed = "- World levels sit at 22,500,000 MT [N25] and 10,542,000 MT [N26, N99] on this read."
    m0, m1 = an._handle_sentence_span(mixed, 0)
    mskip = (mixed.index("22,500,000"), mixed.index("] and") + 1)
    assert an._sentence_has_resolved_handle(mixed, m0, m1, calls, skip=mskip) is False
    # FLAG OFF THE CLAUSE IS UNREACHABLE, and that is asserted by NEUTRALISING it rather than by naming a
    # verdict: with the flag off the function answers identically with and without it, on both shapes.
    for probe, p_skip in ((text, skip), (mixed, mskip)):
        p0, p1 = an._handle_sentence_span(probe, probe.find("World"))
        monkeypatch.delenv(FLAG_K92, raising=False)
        live = an._sentence_has_resolved_handle(probe, p0, p1, calls, skip=p_skip)
        monkeypatch.setattr(an, "_scope_withheld_token", lambda calls, pairs: False)
        assert an._sentence_has_resolved_handle(probe, p0, p1, calls, skip=p_skip) == live
        monkeypatch.undo()


def test_k9_2_fix_a_withheld_handle_in_a_value_slot_still_takes_the_ladder(monkeypatch):
    """THE FENCE IS NARROWED TO THE LEG THAT CAUSED THE FINDING, and this is the leg it must not touch. A
    withheld handle standing where the FIGURE belongs promised a number it cannot produce -- the D-PQ
    HANDLE-1 defect, a different fact -- so it still severs (the sentence keeps another resolved handle)
    or kills. Measured on the banked prose: 0 of the 6 withheld handles are in a value slot, so this is
    live code the replay does not exercise and a pin is the only thing that holds it."""
    text = ("ICE canola stocks-to-use stood at [N9], while Canadian canola stocks-to-use for the "
            "current marketing year reads 16.8472% [N18].")
    on_text, census = _resolve(monkeypatch, "on", text, _prose_calls())
    assert "[N9]" not in on_text and "[N18]" in on_text
    assert "stood at" not in on_text               # the clause that made the promise went with it
    assert census["handles_dropped"] == 1 and census["sentences_dropped"] == 0
    # and with NO other resolved handle in the sentence, the whole sentence goes
    solo, census2 = _resolve(monkeypatch, "on", "ICE canola stocks-to-use stood at [N9].", _prose_calls())
    assert solo.strip() == "" and census2["sentences_dropped"] == 1


def test_k9_2_fix_a_mixed_or_suffixed_token_fails_closed_to_todays_removal(monkeypatch):
    """`all`, not `any`. A group pairing a withheld member with an index nothing minted would leave a
    marker for a receipt that does not exist -- the dangling half of the D-PQ HANDLE-4 join -- so a mixed
    token keeps today's removal. Same for a suffixed member, which `_number_handle_value` refuses by
    definition (an invented sibling id is `unresolvable`, not a withheld read)."""
    calls = _prose_calls()
    mixed, census = _resolve(monkeypatch, "on", "Seed and oil both read thin [N9, N99].", calls)
    assert "[N9" not in mixed and census["handles_dropped"] == 2
    sfx, census2 = _resolve(monkeypatch, "on", "Seed reads thin [N9b].", calls, handle_prose=True)
    assert "[N9b]" not in sfx and census2["handles_dropped"] == 1


def test_k9_2_fix_the_prompt_side_directive_rides_the_flag(monkeypatch):
    """THE PROSPECTIVE HALF, on the empty-read directive's own shape and in its own words -- the half the
    first build declined (review MINOR-4) on the ground that the post-hoc cut "costs claim_count, which is
    exactly what the anti-suppression floor measures". It did not: with `sentences_dropped == 0` nothing
    landed on claim_count at all. AND IT MUST NOT CONTRADICT THE DIRECTIVE ABOVE IT: the empty-read clause
    tells the writer a value-less handle is removed with its clause, which is true of an empty read and
    false of this class, so this clause says so in its own first sentence."""
    from leviathan.graphrag import orchestrator as orch
    calls = [_CENSUS_A["max_N9"], _one_row_scoped()]
    monkeypatch.delenv(FLAG_K92, raising=False)
    off = orch._numbers_block(calls)
    monkeypatch.setenv(FLAG_K92, "on")
    on = orch._numbers_block(calls)
    assert "ONE SCOPE OF MANY" not in off          # the label itself only exists with the flag on
    assert "These are NOT the empty reads" not in off
    assert "These are NOT the empty reads" in on
    assert "State NO number from such a line" in on
    assert "unlike an empty row's handle it stays on the page" in on
    # a panel with no withheld read is byte-identical at both settings -- omit-when-off, measured
    monkeypatch.delenv(FLAG_K92, raising=False)
    plain_off = orch._numbers_block([_one_row_scoped(), _zero_scope_fx()])
    monkeypatch.setenv(FLAG_K92, "on")
    assert orch._numbers_block([_one_row_scoped(), _zero_scope_fx()]) == plain_off


def test_k9_2_fix_scope_withheld_is_one_producer_and_names_only_the_class(monkeypatch):
    """`cit.scope_withheld` reads the RENDERED label, so the directive, the handle pass and the reader's
    `## Sources` row can never disagree about which reads were withheld. It is False for every call with
    the flag off (the omit-when-off rollback reaches both new consumers), and False for every GREEN
    fixture with it on -- the scoped read, the zero-scope FX read, the one-scope free-axis read and the
    one-country widening."""
    greens = {"green_N29": _one_row_scoped(), "green_fx": _zero_scope_fx(),
              "green_one_scope": _one_scope_free_axis(), "green_cotton": _cotton_region_split()}
    monkeypatch.setenv(FLAG_K92, "on")
    for key, call in _CENSUS_A.items():
        assert cit.scope_withheld(call, 1) is True, key
    for key, call in greens.items():
        assert cit.scope_withheld(call, 1) is False, key
    for setting in (None, "off", "", "0", "false"):
        if setting is None:
            monkeypatch.delenv(FLAG_K92, raising=False)
        else:
            monkeypatch.setenv(FLAG_K92, setting)
        for key, call in list(_CENSUS_A.items()) + list(greens.items()):
            assert cit.scope_withheld(call, 1) is False, (key, setting)
    assert cit.scope_withheld(None) is False and cit.scope_withheld({"rows": "not a list"}) is False


# ── K9-3 DECLARED-SCALE DIVERGENCE -- class (2), flag GRAPHRAG_NARRATE_SCALE ──────────────────────────
#
# THE PANEL'S OWN STOP SENTENCE (cascade_panel.json, treatment STOP #12, id rv_beans_meal; TREATMENT =
# max): "US soybean stocks-to-use came in at 0.117499 ratio for MY2025 ... while US soybean meal
# stocks-to-use sat at 1.03033 % [N30] ..." -- STOP: "the same metric is carried on two scales inside one
# comparative clause ... so a reader ranking the two levels as printed gets the ranking backwards by a
# factor of about eleven; A never harmonises them." The judge even states the remedy in the fix's own
# arithmetic -- "in like units it is 11.75 % beans vs 1.03 % meal" -- which is what the RED pins below
# assert the engine now prints.
#
# THE FIXTURES ARE BYTE-VERIFIED AGAINST THE BANKED PANELS. Every call below was rendered through HEAD's
# `from_number` in the build sitting and reproduced its banked `## Sources` line EXACTLY -- 10 of the 11
# rows of `_K93_BANKED`, including both cascade mints (cascade_pair_rv_beans_meal.md:387-396 and
# cascade_pair_rv_soyoil_palm.md:645-648). THE ONE EXCEPTION IS NAMED: `max_N20` is a call the artifact
# banks in `served_rows` (index 20, raw 0.010303290487133514) whose HANDLE the writer never cited, and an
# uncited handle renders no footer line, so its `_K93_BANKED` entry is HEAD's own rendering of the banked
# RECORD rather than a transcribed panel line. It WAS the first build's convergence pin -- the agent's read
# of the very fact the cascade minted as [N30] -- and the table-axis fence took that away: `silver_psd.su_ratio`
# is refused, so `max_N20` now carries the STOP-#12-stays-at-HEAD pin instead and `max_N27`/`max_N32mint`
# carry the convergence.
# Census D itself was reproduced from `cascade_baseline_{control,treatment}.json` per_answer[].served_rows,
# truncated to each answer's agent-lane length: 25 calls / 345 rows (deep 5 / 101, max 20 / 244) -- that
# is the PRE-FENCE census, and the fence cut it to the three calls named in the next paragraph. The
# same-object figure is stated there too, re-measured on the whole 509-record corpus rather than on an
# agent-lane truncation whose partition this deck cannot reproduce.
#
# THE TABLE-AXIS FENCE (verify FATAL, 2026-09-07) CUT THIS ITEM'S REACH TO THREE CALLS, and the deck says
# so rather than pinning a reach the engine no longer has. A label prints the CARD'S ANALYST NAME for a
# metric, and 6 (moved, stayed) pairs across the live registry share both that name and the card unit, so
# harmonising one side put one printed name on two scales -- the class this item exists to remove, on the
# table axis. `citations.narrate_scale` now refuses the whole family fail-closed, which takes silver_psd's
# su_ratio, production_mt, exports_mt and ending_stocks_mt with it, and (through `_co_unit_sibling_scale`)
# the three changes that ride them. MEASURED by replaying all 509 banked call records: flag OFF 0 rewrites
# and 509 same-object returns, with the 455 HEAD can render byte-identical to HEAD; flag ON 3 calls / 3
# rows -- deep rv_soyoil_palm [N2] and max rv_soyoil_palm [N8] (silver_mpob.closing_stocks_palm_oil_mt)
# and max rv_beans_meal [N27] (silver_psd.consumption_mt). Every RED pin below is one of those three or a
# statement of what the fence now leaves at HEAD; the STOP-#12 pin is the second kind, and says so.
FLAG_K93 = "GRAPHRAG_NARRATE_SCALE"


def _k93(table, metric, commodity, country, period, rows, **extra):
    q = {"table": table, "metric": metric, "commodity": commodity, "country": country,
         "period": period, "asof": "2026-09-06"}
    return {"query": q, "rows": rows, "status": "ok", **extra}


def _row(period, value, unit=None, country=None, known=None):
    return {"period": period, "value": value, "unit": unit, "country": country,
            "knowledge_date": known}


# THE MAX rv_beans_meal PANEL (cascade_pair_rv_beans_meal.md:387-396, ANSWER A = treatment = max) and the
# DEEP rv_soyoil_palm PANEL (:645-647, ANSWER B = control = deep). Handles are the banked ones.
_K93_CALLS = {
    # agent-lane, census D: silver_psd has NO unit_col, so every row arrives RAW
    "max_N19": _k93("silver_psd", "su_ratio", "soybeans_cbot", "United States", "2025",
                    [_row("2025", 0.11749940234281617, None, "United States", "2026-08-12")]),
    "max_N20": _k93("silver_psd", "su_ratio", "soybean_meal_cbot", "United States", "2025",
                    [_row("2025", 0.010303290487133514, None, "United States", "2026-08-12")]),
    # THE DELTA TWINS (fix-pass, review FATAL): the SAME metric's own year-on-year change, cited in
    # ONE clause with the level above -- STOP #12 "came in at 0.117499 ratio ... and fell year on year
    # by -0.0178907 ratio [N19][N21]". Values verbatim from the banked record
    # (cascade_baseline_treatment.json, rv_beans_meal served_rows[20] and [21]).
    "max_N21": _k93("silver_psd", "su_ratio_yoy_delta", "soybeans_cbot", "United States", "2025",
                    [_row("2025", "-0.017890719625009238", None, "United States", "2026-08-12")]),
    "max_N22": _k93("silver_psd", "su_ratio_yoy_delta", "soybean_meal_cbot", "United States", "2025",
                    [_row("2025", "0.0026686082404580053", None, "United States", "2026-08-12")]),
    "max_N23": _k93("silver_psd", "ending_stocks_mt", "soybeans_cbot", "United States", "2025",
                    [_row("2025", "8847000.0", None, "United States", "2026-08-12")]),
    "max_N26": _k93("silver_psd", "production_mt", "soybean_meal_cbot", "United States", "2025",
                    [_row("2025", "57427000.0", None, "United States", "2026-08-12")]),
    # THE CONVERGENCE PAIR, RE-BASED ONTO A KEY THE TABLE FENCE LEAVES MOVING (verify FATAL). The
    # banked record carries the agent's OWN raw read of the very fact the cascade minted as [N32]:
    # cascade_baseline_treatment.json, rv_beans_meal served_rows[26] (handle N = index + 1 across this
    # whole panel -- [18]->N19, [22]->N23, [25]->N26, [29]->N30, [31]->N32), value '39599000.0',
    # unit None. `silver_psd.consumption_mt` shares its display name ('consumption') with no other
    # card, so it survives the display-name family fence that refuses su_ratio and production_mt.
    "max_N27": _k93("silver_psd", "consumption_mt", "soybean_meal_cbot", "United States", "2025",
                    [_row("2025", "39599000.0", None, "United States", "2026-08-12")]),
    "deep_N2": _k93("silver_mpob", "closing_stocks_palm_oil_mt", "malaysian_crude_palm_oil_cme", None,
                    None, [_row(None, "2628325.0", None, None, "2026-07-01")]),
    # GREEN, own-unit rows: silver_psd_attributes DOES declare a unit_col, so its rows are outside census D
    "max_N25": _k93("silver_psd_attributes", "Crush", "soybeans_cbot", "United States", "2025",
                    [_row("2025", "72257.0", "(1000 MT)", "United States", "2026-08-12")]),
    # GREEN, metrics the map declares NOTHING for (both live in the SAME deep panel as deep_N2)
    "deep_N1": _k93("silver_mpob", "production_cpo_mt", "malaysian_crude_palm_oil_cme", None, None,
                    [_row(None, "1792979.0", None, None, "2026-07-01")]),
    "deep_N3": _k93("silver_mpob", "su_ratio", "malaysian_crude_palm_oil_cme", None, None,
                    [_row(None, "1.88792309604088", None, None, "2026-07-01")]),
    "deep_N10": _k93("silver_pink_sheet", "palm_oil_cpo_usd_t", None, None, None,
                     [_row(None, "1101.0", None, None, "2026-07-01")]),
    # GREEN, the CASCADE's own pre-scaled mints in those same panels: the row carries narrate_unit already
    # (from these identical constants) and the record carries `shown`, so BOTH fences refuse it.
    "max_N30mint": _k93("silver_psd", "su_ratio", "soybean_meal_cbot", "United States", "2025",
                        [_row("2025", 1.0303290487133514, "%", "United States", "2026-08-12")],
                        shown=[1.0303290487133514]),
    "max_N32mint": _k93("silver_psd", "consumption_mt", "soybean_meal_cbot", "United States", "2025",
                        [_row("2025", 39.599, "MMT", "United States", "2026-08-12")], shown=[39.599]),
}

_K93_BANKED = {
    "max_N19": "USDA PSD stocks-to-use ratio CBOT soybeans United States MY2025 = 0.117499 ratio",
    "max_N20": "USDA PSD stocks-to-use ratio CBOT soybean meal United States MY2025 = 0.0103033 ratio",
    "max_N21": ("USDA PSD stocks-to-use ratio change (YoY) CBOT soybeans United States MY2025 "
                "= -0.0178907 ratio"),
    "max_N22": ("USDA PSD stocks-to-use ratio change (YoY) CBOT soybean meal United States MY2025 "
                "= 0.00266861 ratio"),
    "max_N23": "USDA PSD ending stocks CBOT soybeans United States MY2025 = 8,847,000 MT",
    "max_N26": "USDA PSD production CBOT soybean meal United States MY2025 = 57,427,000 MT",
    "max_N27": "USDA PSD consumption CBOT soybean meal United States MY2025 = 39,599,000 MT",
    "max_N25": "PSD ATTRIBUTES crush CBOT soybeans United States MY2025 = 72,257 (1000 MT)",
    "deep_N1": ("MPOB production crude palm oil CME palm oil = 1,792,979 MT "
                "(latest available 2026-07-01; as-of 2026-09-06)"),
    "deep_N2": ("MPOB palm oil closing stocks CME palm oil = 2,628,325 MT "
                "(latest available 2026-07-01; as-of 2026-09-06)"),
    "deep_N3": ("MPOB stocks-to-use ratio CME palm oil = 1.88792 ratio "
                "(latest available 2026-07-01; as-of 2026-09-06)"),
    "deep_N10": ("World Bank Pink Sheet crude palm oil price  = 1,101 USD/mt "
                 "(latest available 2026-07-01; as-of 2026-09-06)"),
    "max_N30mint": "USDA PSD stocks-to-use ratio CBOT soybean meal United States MY2025 = 1.03033 %",
    "max_N32mint": "USDA PSD consumption CBOT soybean meal United States MY2025 = 39.599 MMT",
}


def _k93_labels(monkeypatch, flag_value):
    """Every fixture's (label, value, unit) at one setting of the K9-3 flag, rendered the way the seam
    renders them: harmonise the published list ONCE, then `from_number` each record."""
    monkeypatch.delenv("GRAPHRAG_SCOPE_WITHHOLD", raising=False)
    if flag_value is None:
        monkeypatch.delenv(FLAG_K93, raising=False)
    else:
        monkeypatch.setenv(FLAG_K93, flag_value)
    keys = list(_K93_CALLS)
    out = cit.harmonise_declared_scale([_K93_CALLS[k] for k in keys])
    got = {}
    for i, k in enumerate(keys):
        c = cit.from_number(out[i], 1)
        got[k] = (c.label, c.value, c.unit)
    return got


# ── OFF PIN: the rollback is a no-op, by IDENTITY ────────────────────────────────────────────────────
def test_k9_3_flag_off_returns_the_callers_own_list_and_the_banked_labels(monkeypatch):
    """Flag unset, 'off' and '' all return the CALLER'S OWN LIST OBJECT -- not an equal copy -- so the
    published list, the prompt panel, the `## Sources` footer, `verify_citations` and `number_calls` are
    byte-identical to HEAD by identity rather than by comparison. RE-MEASURED by replaying all 509 banked
    call records (cascade_baseline_{control,treatment}.json, per_answer[].served_rows, every answer, both
    arms): with the flag off 0 are rewritten and all 509 come back as the SAME OBJECT."""
    src = [_K93_CALLS[k] for k in sorted(_K93_CALLS)]
    for setting in (None, "off", ""):
        if setting is None:
            monkeypatch.delenv(FLAG_K93, raising=False)
        else:
            monkeypatch.setenv(FLAG_K93, setting)
        assert cit.harmonise_declared_scale(src) is src, f"list rebuilt with the flag {setting!r}"
        got = _k93_labels(monkeypatch, setting)
        for key, banked in _K93_BANKED.items():
            assert got[key][0] == banked, f"{key} moved with the flag {setting!r}"


# ── THE JUDGED STOP THIS ITEM CANNOT CLOSE AT THIS REVISION, AND WHY (verify FATAL) ──────────────────
def test_k9_3_the_judged_stop_12_key_is_refused_by_the_table_fence_and_stays_at_head(monkeypatch):
    """cascade_panel.json treatment STOP #12, id rv_beans_meal: "US soybean stocks-to-use came in at
    0.117499 ratio for MY2025 ... while US soybean meal stocks-to-use sat at 1.03033 % [N30]" -- one
    metric, one country, one marketing year, two scales, and the judge measured the reader's error at
    "backwards by a factor of about eleven".

    THE FIRST BUILD CLOSED IT BY MOVING `silver_psd.su_ratio` TO '%', AND THAT MINTED THE SAME CLASS ON
    THE TABLE AXIS. The estate prints the analyst name 'stocks-to-use ratio' at card unit 'ratio' from
    THREE cards -- silver_psd (mapped 100/'%'), silver_mpob and silver_icco_cocoa (the map is silent
    about both) -- and silver_psd serves the palm and cocoa commodities those two cards are, so a
    half-move puts one printed name on two scales 100x apart. `narrate_scale` therefore refuses the
    whole family fail-closed (the block above `citations._display_family_index` carries the census and
    the reason the remedy is a refusal rather than a widening), and THIS STOP IS NOT CLOSED AT THIS
    REVISION: [N19] and [N20] render exactly as HEAD renders them, beside the cascade's own '%' mint.

    THE PATH BACK IS A DECLARATION, NOT A CODE CHANGE, and the build says so: with
    GRAPHRAG_NARRATE_SCALE on, `config_check._check_narrate_scale_family` fails naming
    silver_mpob.su_ratio and silver_icco_cocoa.su_ratio by address (pinned below). A cascade_map row
    for each lifts the refusal and this pin goes back to asserting 11.7499 %."""
    off, on = _k93_labels(monkeypatch, None), _k93_labels(monkeypatch, "on")
    for key in ("max_N19", "max_N20", "max_N21", "max_N22", "max_N30mint"):
        assert on[key] == off[key], key
        assert on[key][0] == _K93_BANKED[key], key
    assert cit.narrate_scale("silver_psd", "su_ratio") is None
    assert cit._map_scale("silver_psd", "su_ratio") == (100.0, "%")        # the MAP still declares it
    assert cit._family_scale_conflict("silver_psd", "su_ratio", (100.0, "%")) == [
        ("silver_icco_cocoa", "su_ratio"), ("silver_mpob", "su_ratio")]    # ...the family refuses it
    # and the change of a refused quantity is refused WITH it -- never a level and its delta apart
    assert cit.narrate_scale("silver_psd", "su_ratio_yoy_delta") is None


# ── RED PIN (TABLE AXIS): the half-move the verify FATAL measured is now unproducible ────────────────
def _k93_tbl(table, metric, commodity, country, period, value, known="2026-08-12"):
    return _k93(table, metric, commodity, country, period,
                [_row(period, value, None, country, known)])


def test_k9_3_red_the_table_axis_half_move_cannot_be_produced_on_any_measured_pair(monkeypatch):
    """THE PRE-FIX SHAPE, PINNED RED. The verify pass measured 6 (moved, stayed) pairs that share BOTH
    the metric display name AND the card unit, so at HEAD they printed the same unit token and the first
    build put them 100x or 1e6x apart. Reproduced through the REAL producer, flag off then on:
        OFF  NASS ANNUAL production CBOT corn United States MY2025 = 384,000,000 MT
             USDA PSD   production CBOT corn United States MY2025 = 384,000,000 MT
        ON   NASS ANNUAL production CBOT corn United States MY2025 = 384,000,000 MT
             USDA PSD   production CBOT corn United States MY2025 = 384 MMT
    One commodity, one country, one marketing year, one printed name, the SAME underlying value,
    printed as two figures a million apart -- and the su_ratio form is sharper still, because a reader
    ranks `15.12 %` above `1.88792 ratio` when in like units the second is the larger.

    THE PIN IS THE WHOLE MEASURED SET, NOT A SAMPLE: every pair the registry census names is rendered
    at both flag settings and must be byte-identical, so the day a map row lands for one of these
    tables this pin fails and the design is forced to land the row for the WHOLE family."""
    PAIRS = (("silver_psd", "su_ratio", "silver_mpob", "su_ratio", "malaysian_crude_palm_oil_cme"),
             ("silver_psd", "su_ratio", "silver_icco_cocoa", "su_ratio", "cocoa_ice"),
             ("silver_psd", "production_mt", "silver_nass_annual", "production_mt", "corn_cbot"),
             ("silver_psd", "exports_mt", "silver_mpoc_trade_stats_monthly", "exports_mt",
              "malaysian_crude_palm_oil_cme"),
             ("silver_psd", "exports_mt", "silver_mpoc_exports_by_country", "exports_mt",
              "malaysian_crude_palm_oil_cme"),
             ("silver_psd", "ending_stocks_mt", "silver_mpoc_stock_comparison", "ending_stocks_mt",
              "malaysian_crude_palm_oil_cme"))
    for at, am, bt, bm, commodity in PAIRS:
        v = "0.1512" if am == "su_ratio" else "384000000.0"
        panel = [_k93_tbl(at, am, commodity, "United States", "2025", v),
                 _k93_tbl(bt, bm, commodity, "United States", "2025", v)]
        monkeypatch.delenv(FLAG_K93, raising=False)
        off = [cit.from_number(c, i + 1) for i, c in enumerate(cit.harmonise_declared_scale(panel))]
        monkeypatch.setenv(FLAG_K93, "on")
        on = [cit.from_number(c, i + 1) for i, c in enumerate(cit.harmonise_declared_scale(panel))]
        assert [c.label for c in on] == [c.label for c in off], (at, am, bt, bm)
        assert len({c.unit for c in on}) == 1, (at, am, bt, bm)   # ONE printed unit token, one scale
    # the two label pairs the verify pass rendered, asserted as tokens rather than paraphrased
    monkeypatch.setenv(FLAG_K93, "on")
    corn = cit.harmonise_declared_scale(
        [_k93_tbl("silver_psd", "production_mt", "corn_cbot", "United States", "2025", "384000000.0")])
    assert cit.from_number(corn[0], 1).label.endswith("= 384,000,000 MT")   # never "= 384 MMT"
    palm = cit.harmonise_declared_scale(
        [_k93_tbl("silver_psd", "su_ratio", "malaysian_crude_palm_oil_cme", "Malaysia", "2025",
                  "0.1512")])
    assert cit.from_number(palm[0], 1).label.endswith("= 0.1512 ratio")     # never "= 15.12 %"


# ── GREEN PIN (TABLE AXIS): what the fence must NOT cost ─────────────────────────────────────────────
def test_k9_3_green_the_table_fence_refuses_only_the_colliding_family(monkeypatch):
    """THE FENCE IS A REFUSAL, AND A REFUSAL MUST BE NARROW. Measured over the whole live registry: 20
    (table, metric) keys carry a map scale != 1 or derive one from a co-unit parent, 7 of them are
    refused by the display-name family (silver_psd su_ratio / production_mt / exports_mt /
    ending_stocks_mt and the three changes that ride them), and the remaining 13 move exactly as they
    did. A fence that keyed on the metric slug, or on the card unit alone, would have taken all 20."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    moved = sorted(f"{t}.{m}" for t, s in reg.tables.items() for m in (getattr(s, "metrics", {}) or {})
                   if cit.narrate_scale(t, m))
    assert len(moved) == 13, moved
    for key in ("silver_mpob.closing_stocks_palm_oil_mt", "silver_psd.consumption_mt",
                "silver_psd.imports_mt", "silver_psd.beginning_stocks_mt",
                "silver_psd.area_harvested_1000ha", "silver_psd.consumption_mt_revision",
                "silver_psd_attributes.Crush", "silver_production_livestock.live_animals"):
        assert key in moved, key
    for key in ("silver_psd.su_ratio", "silver_psd.production_mt", "silver_psd.exports_mt",
                "silver_psd.ending_stocks_mt", "silver_psd.su_ratio_yoy_delta",
                "silver_psd.production_mt_revision", "silver_psd.ending_stocks_mt_revision"):
        assert key not in moved, key
    # THE DECK'S OWN BANKED CO-PANEL LINES ARE THE PROOF THE FAMILY LANDS ON ONE SCALE: deep_N3 is
    # `silver_mpob.su_ratio` and it never moved; its PSD twin, one lookup away in that panel, now does
    # not move either, so the deep rv_soyoil_palm panel prints 'stocks-to-use ratio' on ONE scale.
    off, on = _k93_labels(monkeypatch, None), _k93_labels(monkeypatch, "on")
    assert on["deep_N3"] == off["deep_N3"] and on["deep_N3"][0] == _K93_BANKED["deep_N3"]
    monkeypatch.setenv(FLAG_K93, "on")
    twin = cit.harmonise_declared_scale(
        [_K93_CALLS["deep_N3"],
         _k93_tbl("silver_psd", "su_ratio", "malaysian_crude_palm_oil_cme", "Malaysia", "2025",
                  "0.1512")])
    assert {cit.from_number(c, i + 1).unit for i, c in enumerate(twin)} == {"ratio"}
    # ...and the one deep call the item still moves is untouched by the family fence
    assert cit._family_scale_conflict(
        "silver_mpob", "closing_stocks_palm_oil_mt", (1e-06, "MMT")) == []
    assert on["deep_N2"][0].endswith("= 2.62832 MMT (latest available 2026-07-01; as-of 2026-09-06)")


def test_k9_3_red_max_the_agent_read_and_the_cascade_mint_become_one_sentence(monkeypatch):
    """THE HARMONISATION MINTS NOTHING, and this is the proof: [N27] is the AGENT's own read of the meal
    domestic consumption (banked raw '39599000.0', served_rows[26]) and [N32] is the CASCADE's pre-scaled
    mint of the same fact (banked 39.599 MMT, served_rows[31]). At HEAD they print `39,599,000 MT` and
    `39.599 MMT`. After the fix the agent's line is BYTE-IDENTICAL to the engine's own -- same scale, same
    unit, same constants, because both read `cascade.load_map()`.

    RE-BASED FROM su_ratio ONTO consumption_mt BY THE VERIFY FATAL, and the pair is no weaker for it: it
    is the same panel, the same table, the same marketing year and the same convergence, on a display
    name ('consumption') no other card in the registry prints -- so the table-axis fence has nothing to
    refuse. The su_ratio pair the first build used is now refused whole and is pinned at HEAD above."""
    off, on = _k93_labels(monkeypatch, None), _k93_labels(monkeypatch, "on")
    assert off["max_N27"][0] != off["max_N32mint"][0]
    assert on["max_N27"][0] == on["max_N32mint"][0] == _K93_BANKED["max_N32mint"]
    assert cit._family_scale_conflict("silver_psd", "consumption_mt", (1e-06, "MMT")) == []


def test_k9_3_the_tonnage_split_is_half_closed_and_the_open_half_is_named(monkeypatch):
    """The same defect on the tonnage axis, inside ONE sentence of the banked answer: "production
    57,427,000 MT [N26] against domestic consumption 39.599 MMT [N32]" -- the agent's raw MT read set
    against the cascade's pre-scaled MMT mint, 1.45-million-fold apart as printed.

    HALF OF THAT SENTENCE STAYS OPEN, AND THE HALF IS NAMED RATHER THAN QUIETLY DROPPED (verify FATAL).
    `silver_psd.production_mt` prints the analyst name 'production' at card unit 'MT', and so does
    `silver_nass_annual.production_mt`, which the map is silent about -- two cards that share 8
    commodities including corn_cbot and soybeans_cbot -- so the family fence refuses the key and [N26]
    renders at HEAD. `silver_psd.ending_stocks_mt` is refused the same way (silver_mpoc_stock_comparison)
    and `exports_mt` twice over (both silver_mpoc_ cards). What the item still closes in this panel is the
    consumption pair above; what it does not close is pinned here so no reader of this deck believes the
    sentence was fixed."""
    off, on = _k93_labels(monkeypatch, None), _k93_labels(monkeypatch, "on")
    for key in ("max_N23", "max_N26"):
        assert on[key] == off[key] and on[key][0] == _K93_BANKED[key], key
    assert "57,427,000 MT" in on["max_N26"][0] and "8,847,000 MT" in on["max_N23"][0]
    for metric, family in (("production_mt", [("silver_nass_annual", "production_mt")]),
                           ("ending_stocks_mt", [("silver_mpoc_stock_comparison", "ending_stocks_mt")]),
                           ("exports_mt", [("silver_mpoc_exports_by_country", "exports_mt"),
                                           ("silver_mpoc_trade_stats_monthly", "exports_mt")])):
        ns = cit._map_scale("silver_psd", metric)
        assert ns == (1e-06, "MMT"), metric                     # the map declares it
        assert cit._family_scale_conflict("silver_psd", metric, ns) == family, metric
        assert cit.narrate_scale("silver_psd", metric) is None, metric
        # ...and each refused parent takes its own change with it
    assert cit.narrate_scale("silver_psd", "production_mt_revision") is None
    assert cit.narrate_scale("silver_psd", "ending_stocks_mt_revision") is None


# ── RED PIN (DEEP): the one deep call K9-2 leaves for this item ──────────────────────────────────────
def test_k9_3_red_deep_mpob_closing_stocks_print_in_the_declared_unit(monkeypatch):
    """Deep reach after K9-2 is exactly ONE call, and this is it: 4 of the 5 deep census-D calls are also
    census-A unscoped multi-geo reads whose value K9-2 already withholds. `silver_mpob
    closing_stocks_palm_oil_mt` carries `scale: 1e-06, narrate_unit: MMT`, so the deep rv_soyoil_palm panel
    stops printing a bare-MT figure the prose then copied ("closing stocks of 2,628,325 MT").

    THE TOKEN IS 2.62832, NOT THE DESIGN'S 2.628325, AND THE CAUSE IS NAMED: `_fmt` is `f"{f:g}"` for
    |v| < 1000, i.e. SIX significant digits, so 2.628325 renders 2.62832. The design quoted the exact
    product; the panel prints the formatter's rendering of it, as it does for every sub-1000 magnitude on
    every line today."""
    on = _k93_labels(monkeypatch, "on")
    assert on["deep_N2"][0] == ("MPOB palm oil closing stocks CME palm oil = 2.62832 MMT "
                                "(latest available 2026-07-01; as-of 2026-09-06)")
    assert "2,628,325" not in on["deep_N2"][0]
    assert on["deep_N2"][2] == "MMT"


# ── GREEN PIN: what the fix must not touch ────────────────────────────────────────────────────────────
def test_k9_3_green_own_unit_unmapped_and_prescaled_rows_are_byte_identical(monkeypatch):
    """Three untouched classes, all measured on the banked panels:
      * a row carrying ITS OWN unit -- `silver_psd_attributes` declares a `unit_col`, so all 40 rows of the
        deep rv_corn_wheat Feed-Dom.-Consumption serve carry '(1000 MT)' and sit outside census D;
      * a (table, metric) the map declares NOTHING for -- `silver_mpob.production_cpo_mt` and
        `silver_mpob.su_ratio` sit in the SAME deep panel as the RED pin above and must not move;
      * a cascade `_prescaled` mint -- refused twice over (its row already carries narrate_unit, and the
        record carries `shown`)."""
    off, on = _k93_labels(monkeypatch, None), _k93_labels(monkeypatch, "on")
    for key in ("max_N25", "deep_N1", "deep_N3", "deep_N10", "max_N30mint", "max_N32mint"):
        assert on[key] == off[key], key
        assert on[key][0] == _K93_BANKED[key], key


def test_k9_3_green_a_call_carrying_shown_is_refused_outright(monkeypatch):
    """`shown` is the panel's own testimony about the magnitudes a LINE printed, and
    `verify._mismatch_pool` checks a cited figure against it IN PREFERENCE to the rows. Rescaling rows
    under a bound `shown` would silently break that binding, so such a record comes back as the SAME
    object -- fail-closed, since only `cascade._shown` / `numbers.derived` / `numbers.pattern_records`
    mint the key and none of them reaches this seam."""
    monkeypatch.setenv(FLAG_K93, "on")
    # ON A KEY THE TABLE FENCE LEAVES MOVING: built on su_ratio this pin would pass because the FAMILY
    # refused the key, and a mutation dropping the `shown` guard would survive it (verify FATAL).
    raw = _k93("silver_psd", "consumption_mt", "canola_ice", "Canada", "2026",
               [_row("2026", 16847200.0, None, "Canada", "2026-08-12")], shown=[16.8472])
    assert cit.narrate_scale("silver_psd", "consumption_mt") == (1e-06, "MMT")
    assert cit.harmonise_declared_scale([raw])[0] is raw
    assert cit.harmonise_declared_scale([{k: v for k, v in raw.items() if k != "shown"}])[0] \
        != raw                                             # ...and WITHOUT `shown` it does move
    # ... and a whole list that owes nothing comes back as the CALLER'S OWN LIST even with the flag ON:
    # a turn outside this class is byte-identical by identity, not merely equal. RE-MEASURED after the
    # table-axis fence, by replaying all 509 banked call records: with the flag ON exactly 3 are
    # rewritten and 506 come back as the same object. (The first build stated 248 of 273 here; that was
    # the PRE-fence count on an agent-lane truncation, and the fence made it wrong by an order of
    # magnitude in the direction the fence moved -- so it is re-based onto the corpus that can be
    # replayed rather than re-quoted.)
    src = [raw, _K93_CALLS["max_N25"], _K93_CALLS["deep_N1"], _K93_CALLS["max_N32mint"]]
    assert cit.harmonise_declared_scale(src) is src


def test_k9_3_green_the_empty_and_blank_read_shapes_are_invariant(monkeypatch):
    """`is_empty_read` is THE ONE PRODUCER for "this read produced no value at all", and three consumers
    share it (the label, `orchestrator._numbers_block`'s directive, `answer._addresses_empty_row`). A
    blank or None value raises inside the float cast and the row is left exactly as it is, so every one of
    those verdicts -- and the BLANK_VALUE_STATUS label K9-1 will key on -- is byte-identical."""
    monkeypatch.setenv(FLAG_K93, "on")
    # ...on `consumption_mt`, which the table-axis fence leaves moving, so the BLANK is what refuses the
    # row rather than the family (verify FATAL: su_ratio would have made this pin vacuous)
    blank = _k93("silver_psd", "consumption_mt", "canola_ice", "world", "2025",
                 [_row("2025", None, None, "world", "2026-08-12")])
    zero = dict(_k93("silver_psd", "consumption_mt", "canola_ice", "world", "2025", []),
                status="error")
    for call in (blank, zero):
        assert cit.is_empty_read(call) is True
        h = cit.harmonise_declared_scale([call])[0]
        assert h is call                                   # nothing owed -> the same object
        assert cit.is_empty_read(h) is True
        assert "NO ROWS RETURNED" in cit.from_number(h, 1).label


def test_k9_3_green_every_row_moves_and_the_headline_does_not(monkeypatch):
    """EVERY ROW, not the headline alone -- because `_mint_row_citations` (the FOOTER-1 extras path) labels
    a SIBLING row of the same call with the identical `row unit or card unit` rule, so a headline-only
    rescale would print `= 39.599 MMT` above `= 38,100,000 MT` for one metric inside ONE footer block.
    And the headline row itself cannot move: `_row_order_key`'s own note states "`unit` is not in this key
    at all", so stamping a unit changes no ordering term. Built on `consumption_mt` rather than the
    original `su_ratio` because the table-axis fence refuses su_ratio outright (verify FATAL) -- the rule
    under test is the ROW SWEEP, and it is identical on any key the fence leaves moving."""
    monkeypatch.setenv(FLAG_K93, "on")
    call = _k93("silver_psd", "consumption_mt", "soybean_meal_cbot", "United States", None,
                [_row("2024", 38100000.0, None, "United States", "2025-08-12"),
                 _row("2025", 39599000.0, None, "United States", "2026-08-12")])
    h = cit.harmonise_declared_scale([call])[0]
    assert [r["unit"] for r in h["rows"]] == ["MMT", "MMT"]
    assert [round(r["value"], 4) for r in h["rows"]] == [38.1, 39.599]
    head = cit.from_number(h, 27)
    assert head.label.startswith("USDA PSD consumption CBOT soybean meal United States = 39.599 MMT")
    assert cit._row_order_key(h["rows"][-1]) == cit._row_order_key(call["rows"][-1])
    extras = cit.extra_number_citations(h, 27, [38.1])
    assert [x.label for x in extras] == [
        "USDA PSD consumption soybean_meal_cbot United States MY2024 = 38.1 MMT"]
    # COPY-ON-WRITE: the agent's own record is never mutated under a caller that still holds it
    assert call["rows"][0]["value"] == 38100000.0 and call["rows"][0]["unit"] is None


def test_k9_3_green_rows_and_labels_move_together_so_verify_charges_nothing(monkeypatch):
    """The design's GREEN pin: "the harmonisation must mint none: rows and labels move together or the fix
    is wrong". `verify._mismatch_pool` falls back to `_row_vals` over the whole list for any call with no
    `shown` binding -- every agent-lane call -- so the pool and the label must speak one scale.

    AND THE DESIGN'S OWN REASON FOR THIS, CORRECTED BY MEASUREMENT: it said a label-only change "would
    charge `number_mismatch` on every CORRECT sentence". It would not: `verify._num_matches` walks the
    scale ladder (1, 1e2, 1e3, 1e6, 1e9) in BOTH directions, which covers every scale this map declares
    (100, 0.001, 1e-06). That same tolerance is what makes THIS fix charge-free too, which is the half of
    the claim that matters and the half this test pins."""
    from leviathan.graphrag import verify as vf
    monkeypatch.setenv(FLAG_K93, "on")
    for key in ("max_N19", "max_N21", "max_N23", "max_N26", "max_N27", "deep_N2"):
        call = _K93_CALLS[key]
        h = cit.harmonise_declared_scale([call])[0]
        # THE TOKEN THE WRITER SEES, not `Citation.value` (fix-pass, review MINOR): the writer copies
        # the LABEL, which is `_fmt`'s six-significant-digit rendering, and this fix moves values off
        # the comma-formatted >=1000 path (exact) onto the sub-1000 `f"{f:g}"` path (2,628,325 ->
        # 2.62832). A pin on the full-precision value cannot see a formatter-induced mismatch;
        # `verify._check_number_handle` only ever sees the printed magnitude.
        printed = float(cit.from_number(h, 1).label.split(" = ")[1].split(" ")[0].replace(",", ""))
        assert vf._num_matches([printed], vf._row_vals(h))         # the label backs against its own rows
        assert vf._num_matches([printed], vf._row_vals(call))      # ... and against the pre-fix rows
    # ... and the worst relative loss the formatter can inflict at these scales is measured, not assumed
    h = cit.harmonise_declared_scale([_K93_CALLS["deep_N2"]])[0]
    printed = float(cit.from_number(h, 1).label.split(" = ")[1].split(" ")[0].replace(",", ""))
    assert abs(printed - 2.628325) / 2.628325 < 1e-5


# ── THE DECLARED INTRA-K9 COLLISION: K9-2 SHIPS FIRST, AND STAYS FIRST ───────────────────────────────
def test_k9_3_does_not_resurrect_a_scope_withheld_headline(monkeypatch):
    """Section 3's declared collision: 4 of the 5 deep census-D calls are ALSO census-A unscoped multi-geo
    reads, and rescaling an unscoped headline 9 -> 900 % is the exact absurdity K9-2 exists to remove. The
    two never fight because they are DIFFERENT seams -- K9-3 rewrites ROWS before the list is published,
    K9-2 withholds a LABEL at render time, downstream of it -- so with both flags ON the line is
    byte-identical to the K9-2-only line and no rescaled figure reaches the reader."""
    monkeypatch.setenv("GRAPHRAG_SCOPE_WITHHOLD", "on")
    # ON A KEY THE TABLE FENCE LEAVES MOVING, or this pin proves nothing: `production_mt` (the banked
    # census-A shape) is now refused by the display-name family too, so a call built on it would come
    # back unrewritten for the WRONG reason and a mutation to `_unscoped_multi_geo` would survive here.
    # Same shape, same 32 scopes, on `consumption_mt`.
    call = _unscoped_multigeo("consumption_mt", "canola_ice", 1931, "22500000.0")
    assert cit.narrate_scale("silver_psd", "consumption_mt") == (1e-06, "MMT")
    monkeypatch.delenv(FLAG_K93, raising=False)
    k92_only = cit.from_number(cit.harmonise_declared_scale([call])[0], 1)
    monkeypatch.setenv(FLAG_K93, "on")
    both = cit.from_number(cit.harmonise_declared_scale([call])[0], 1)
    assert (both.label, both.value, both.unit) == (k92_only.label, k92_only.value, k92_only.unit)
    assert both.value is None and "22.5 MMT" not in both.label and "22,500,000" not in both.label
    assert _WITHHELD.format(k=32) in both.label


# ── THE PRODUCER'S FAIL-CLOSED RULES, MEASURED ON THE LIVE MAP ───────────────────────────────────────
def test_k9_3_narrate_scale_reads_the_cascades_own_map_and_fails_closed():
    """DELEGATED, NEVER COPIED: the constants come from `cascade.load_map()` itself, so an agent-lane read
    and a cascade mint of one metric cannot disagree about scale. None on every refusal, including the one
    the LIVE map already carries: `gold_futures_spreads.spread_value` is served by TWO refs that disagree
    about the unit ('US cents/bushel' under kc_chi_spread, 'ZAR/t' under white_yellow_spread). Both are at
    scale 1 so the key is out of this class today; the SHAPE is not, and a producer that took "the first
    ref that matches" would stamp one board's currency on the other's rows the day a scale is added.

    AND None ON A KEY THE MAP DOES DECLARE, when the printed name is shared (verify FATAL): su_ratio and
    production_mt are mapped at a real scale and still refused, because sibling cards print the same
    analyst name at the same card unit and the map is silent about them."""
    from leviathan.graphrag.numbers import cascade as csc
    assert cit.narrate_scale("silver_psd", "consumption_mt") == (1e-06, "MMT")
    assert cit.narrate_scale("silver_psd", "imports_mt") == (1e-06, "MMT")
    assert cit.narrate_scale("silver_psd_attributes", "Crush") == (0.001, "MMT")
    assert cit.narrate_scale("silver_mpob", "closing_stocks_palm_oil_mt") == (1e-06, "MMT")
    for table, metric in (("silver_pink_sheet", "palm_oil_cpo_usd_t"),   # unmapped
                          ("silver_mpob", "production_cpo_mt"),          # unmapped
                          ("silver_esr", "weekly_exports_1000mt"),       # mapped at scale 1
                          ("gold_futures_spreads", "spread_value"),      # two refs, two units
                          ("silver_psd", "su_ratio"),                    # mapped, table-fence refused
                          ("silver_psd", "production_mt"),               # mapped, table-fence refused
                          ("", "su_ratio"), ("silver_psd", None)):
        assert cit.narrate_scale(table, metric) is None, (table, metric)
    # the constants are the cascade's, not a second copy: every key this producer answers for is a row of
    # the same map the quantify loop pre-scales from.
    live = {(r.get("table"), r.get("metric")) for r in csc.load_map().values()}
    assert ("silver_psd", "su_ratio") in live and ("silver_mpob", "closing_stocks_palm_oil_mt") in live


def test_k9_3_two_map_refs_that_disagree_at_a_real_scale_are_refused(monkeypatch):
    """THE UNANIMITY FENCE, PINNED ON THE SHAPE BECAUSE THE LIVE MAP CANNOT PIN IT (adversarial pass, this
    sitting: a `sorted(declared)[0]` mutation survived the live-map test above, because
    `gold_futures_spreads.spread_value`'s two disagreeing refs both sit at scale 1 and the scale-1 guard
    catches them anyway). The map is keyed by silver_ref, so ONE (table, metric) may be served by many
    rows; the day two of them disagree at a real scale, a producer that took the first match would stamp
    one board's unit -- or one card's scale -- on the other's rows. Disagreement about EITHER term is a
    refusal, and a refusal renders exactly today's label."""
    from leviathan.graphrag.numbers import cascade as csc
    base = {"table": "silver_demo", "metric": "demo_metric", "scale": 1e-06, "narrate_unit": "MMT"}
    monkeypatch.setattr(csc, "load_map", lambda: {"a": dict(base)})
    assert cit.narrate_scale("silver_demo", "demo_metric") == (1e-06, "MMT")
    monkeypatch.setattr(csc, "load_map", lambda: {"a": dict(base), "b": dict(base, narrate_unit="ZAR/t")})
    assert cit.narrate_scale("silver_demo", "demo_metric") is None      # same scale, two units
    monkeypatch.setattr(csc, "load_map", lambda: {"a": dict(base), "b": dict(base, scale=0.001)})
    assert cit.narrate_scale("silver_demo", "demo_metric") is None      # same unit, two scales
    monkeypatch.setattr(csc, "load_map", lambda: {"a": dict(base, narrate_unit="")})
    assert cit.narrate_scale("silver_demo", "demo_metric") is None      # scale != 1 with no unit to stamp
    monkeypatch.setattr(csc, "load_map", lambda: {"a": dict(base, scale="not-a-number")})
    assert cit.narrate_scale("silver_demo", "demo_metric") is None      # a scale that does not parse

    def _boom():
        raise RuntimeError("map unreadable")

    monkeypatch.setattr(csc, "load_map", _boom)
    monkeypatch.setenv(FLAG_K93, "on")                                  # the flag is ON and it still refuses
    assert cit.narrate_scale("silver_psd", "su_ratio") is None          # a map hiccup renders today's label
    src = [_K93_CALLS["max_N19"]]
    assert cit.harmonise_declared_scale(src) is src


# ── THE SEAM: ONE CALL, AT THE ONE PLACE THE HYBRID LIST IS PUBLISHED ────────────────────────────────
def test_k9_3_rides_the_publish_seam_and_reaches_the_prompt_panel(monkeypatch):
    """`run_hybrid._resolve` fixes the list at `holder["calls"], holder["resolved"] = calls, True`, and
    that ONE list is what `_numbers_block` renders into the prompt, what answer.py unifies into `##
    Sources` and hands to `verify_citations`, and what `out["number_calls"]` publishes. The harmonise call
    must therefore sit BEFORE that publish and AFTER the futures/coverage guards, which read the served
    rows to decide whether a lookup is servable at all -- a verdict about the READ that no rescale may
    take part in."""
    import inspect
    from leviathan.graphrag import orchestrator as orch
    src = inspect.getsource(orch.run_hybrid)
    assert src.count("cit.harmonise_declared_scale(calls)") == 1
    assert (src.index("na.futures_eod_coverage_guard(calls)")
            < src.index("calls = cit.harmonise_declared_scale(calls)")
            < src.index('holder["calls"], holder["resolved"] = calls, True'))
    monkeypatch.setenv(FLAG_K93, "on")
    block = orch._numbers_block(cit.harmonise_declared_scale(
        [_K93_CALLS["max_N27"], _K93_CALLS["max_N32mint"]]))
    assert "= 39.599 MMT" in block and "39,599,000 MT" not in block
    monkeypatch.delenv(FLAG_K93, raising=False)
    off = orch._numbers_block([_K93_CALLS["max_N27"], _K93_CALLS["max_N32mint"]])
    assert "= 39,599,000 MT" in off                                 # the flag-off panel is today's panel


# ── RED PIN, THE FIX-PASS: a metric and its OWN change (review FATAL), NOW FENCE-AGNOSTIC ────
def test_k9_3_red_a_metric_and_its_own_change_never_split_whichever_fence_stops_the_parent(monkeypatch):
    """THE FIRST BUILD MINTED CLASS (2) INSIDE THIS ITEM'S OWN RED PIN. It moved `silver_psd.su_ratio`
    to '%' and left `silver_psd.su_ratio_yoy_delta` -- the SAME metric's own year-on-year change, an
    unmapped sibling key -- at the raw 'ratio'. At HEAD the two AGREED; with the flag on they were 100x
    apart, inside ONE clause of the judged answer (STOP #12: "came in at 0.117499 ratio for MY2025 and
    fell year on year by -0.0178907 ratio [N19][N21], while ... sat at 1.03033 % [N30] and rose year on
    year by 0.00266861 ratio [N22]").

    THE RULE IS NOW STATED THE ONLY WAY THAT SURVIVES A SECOND FENCE (verify FATAL): a change moves if
    and only if the quantity it is a change OF moves, whichever fence stopped the parent.
    `_co_unit_sibling_scale` reads `_fenced_map_scale` rather than the raw map, so the TABLE-axis
    refusal of su_ratio refuses su_ratio_yoy_delta with it -- the clause above stays whole at HEAD
    instead of splitting the other way. The live pair the rule still MOVES is consumption_mt and its
    own `_revision`, and the change unit is the estate's own word for it
    (`_XcMetricSpec(key="exports_mt", unit="MMT", delta_unit="MMT")`)."""
    off, on = _k93_labels(monkeypatch, None), _k93_labels(monkeypatch, "on")
    for key in ("max_N19", "max_N21", "max_N22"):                   # refused parent, refused change
        assert on[key] == off[key] and on[key][0] == _K93_BANKED[key], key
    for parent, child in (("su_ratio", "su_ratio_yoy_delta"),
                          ("production_mt", "production_mt_revision"),
                          ("ending_stocks_mt", "ending_stocks_mt_revision"),
                          ("consumption_mt", "consumption_mt_revision")):
        p, c = (cit.narrate_scale("silver_psd", parent), cit.narrate_scale("silver_psd", child))
        assert (p is None) == (c is None), (parent, child)           # together, or neither
    assert cit.narrate_scale("silver_psd", "consumption_mt_revision") == (1e-06, "MMT")
    # ...and a change still lands on the SAME scale as its parent, x1e-06 off the raw MT row
    rev = _k93("silver_psd", "consumption_mt_revision", "soybean_meal_cbot", "United States", "2025",
               [_row("2025", "1499000.0", None, "United States", "2026-08-12")])
    lvl = cit.from_number(cit.harmonise_declared_scale([_K93_CALLS["max_N27"]])[0], 27)
    chg = cit.from_number(cit.harmonise_declared_scale([rev])[0], 28)
    assert (lvl.unit, chg.unit) == ("MMT", "MMT")
    assert chg.label.endswith("= 1.499 MMT") and lvl.label.endswith("= 39.599 MMT")


def test_k9_3_green_a_sibling_that_is_not_its_parent_rescaled_never_moves():
    """THE UNIT-EQUALITY TERM IS WHAT FENCES THE DELTA RULE, and it is measured on the LIVE registry, not
    asserted: 67 prefix-sibling metric pairs exist and exactly 4 pass -- all four on silver_psd, all four
    ABSOLUTE changes in the parent's own units. The 63 refused are refused by unit inequality alone (38
    `_zscore_5yr` at 'sigma vs 5-yr mean' against 'USD/mt', 14 `_pct_change_90d` at 'pct', 5 `_cells`, 4
    `_tail_share`, 2 `_z_3yr`): a z-score is NOT its parent rescaled, and the card says so in the one
    place a producer may read. A name-derived rule would have moved all 67.

    THE UNIT-EQUALITY CENSUS IS UNCHANGED BY THE TABLE FENCE, and both halves are measured here so the
    two fences stay separable: 4 of the 67 pairs pass the CARD's unit-equality test beside a map-scaled
    parent (the derivation's own rule, unchanged), and 3 of those 4 are then refused end to end because
    their PARENT is refused on the table axis (verify FATAL). What survives both is
    consumption_mt_revision."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    pairs, co_unit, moved = 0, [], []
    for tid, spec in sorted(reg.tables.items()):
        for d in spec.metrics:
            for p in spec.metrics:
                if d == p or not d.startswith(p):
                    continue
                pairs += 1
                du = str(getattr(spec.metrics[d], "unit", "") or "").strip()
                pu = str(getattr(spec.metrics[p], "unit", "") or "").strip()
                if du and du == pu and cit._map_scale(tid, p) and d.startswith(p + "_"):
                    co_unit.append(f"{tid}.{d}")                 # the CARD's rule, before any fence
                if cit.narrate_scale(tid, p) and cit.narrate_scale(tid, d):
                    moved.append(f"{tid}.{d}")                   # ...and what survives every fence
    assert pairs == 67, pairs
    assert sorted(co_unit) == ["silver_psd.consumption_mt_revision",
                               "silver_psd.ending_stocks_mt_revision",
                               "silver_psd.production_mt_revision",
                               "silver_psd.su_ratio_yoy_delta"], co_unit
    assert sorted(moved) == ["silver_psd.consumption_mt_revision"], moved
    # the three the whole registry would have carried on a name rule, each refused by its own card
    for tid, metric in (("silver_pink_sheet", "palm_oil_cpo_usd_t_zscore_5yr"),
                        ("silver_fred_fx", "inr_usd_pct_change_90d"),
                        ("gold_weather_z", "drought_z_tail_share")):
        assert cit.narrate_scale(tid, metric) is None, (tid, metric)
    assert cit.narrate_scale("silver_psd", "consumption_mt_revision") == (1e-06, "MMT")


def test_k9_3_the_delta_sibling_derivation_fails_closed_on_every_missing_declaration(monkeypatch):
    """Every term of the rule is a DECLARATION, so every missing declaration is a refusal. Built on a
    synthetic card + map because the live estate carries none of these shapes -- which is the point: the
    day one lands, the harmonisation must switch OFF rather than guess."""
    from types import SimpleNamespace as NS

    from leviathan.graphrag.numbers import cascade as csc
    from leviathan.graphrag.numbers import registry as rg

    def _reg(**metrics):
        card = NS(metrics={k: NS(unit=v) for k, v in metrics.items()})
        return lambda: NS(get=lambda _t: card, tables={"silver_demo": card})

    monkeypatch.setattr(csc, "load_map", lambda: {"a": {"table": "silver_demo", "metric": "lvl",
                                                        "scale": 100, "narrate_unit": "%"}})
    monkeypatch.setattr(rg, "load_registry", _reg(lvl="ratio", lvl_delta="ratio"))
    assert cit.narrate_scale("silver_demo", "lvl_delta") == (100.0, "pp")   # the whole rule, satisfied

    monkeypatch.setattr(rg, "load_registry", _reg(lvl="ratio", lvl_delta="pct"))
    assert cit.narrate_scale("silver_demo", "lvl_delta") is None      # the card says NOT the same units
    monkeypatch.setattr(rg, "load_registry", _reg(lvl="ratio", lvl_delta=None))
    assert cit.narrate_scale("silver_demo", "lvl_delta") is None      # the sibling declares no unit
    monkeypatch.setattr(rg, "load_registry", _reg(lvl="ratio", other="ratio", lvl_delta="ratio"))
    assert cit.narrate_scale("silver_demo", "lvl_delta") == (100.0, "pp")  # `other` is not a prefix
    monkeypatch.setattr(rg, "load_registry", _reg(lvl="ratio", lvl_d="ratio", lvl_d_x="ratio"))
    assert cit.narrate_scale("silver_demo", "lvl_d_x") is None        # two co-unit parents, one unmapped
    monkeypatch.setattr(rg, "load_registry", _reg(lvl="ratio", lvl_delta="ratio"))
    monkeypatch.setattr(csc, "load_map", lambda: {"a": {"table": "silver_demo", "metric": "lvl",
                                                       "scale": 0.001, "narrate_unit": "MMT"},
                                                  "b": {"table": "silver_demo", "metric": "lvl_delta",
                                                        "scale": 1, "narrate_unit": "MMT"}})
    # THE MAP SPEAKS ABOUT THE SIBLING ITSELF -- its word wins, INCLUDING its silence about scale. The
    # parent here is mapped at a real scale AND its narrate_unit has a declared delta word, so a build
    # that dropped the map-speaks guard would return (0.001, 'MMT') and override an explicit scale-1
    # declaration; that is what this line is shaped to catch.
    assert cit.narrate_scale("silver_demo", "lvl") == (0.001, "MMT")
    assert cit.narrate_scale("silver_demo", "lvl_delta") is None
    monkeypatch.setattr(csc, "load_map", lambda: {"a": {"table": "silver_demo", "metric": "lvl",
                                                       "scale": 0.001, "narrate_unit": "M ha"}})
    assert cit.narrate_scale("silver_demo", "lvl_delta") is None      # no declared word for a delta of
    #                                                                  'M ha' -- this seam does not coin one


# ── THE FLAG PAIR: the order the design calls load-bearing is now CODE (review MAJOR-1) ──────────
def test_k9_3_an_unscoped_multi_geo_read_is_refused_at_every_setting_of_both_flags(monkeypatch):
    """K9-2's OWN ADVERTISED ROLLBACK used to light the absurdity the shipping order exists to prevent.
    `_scope_withhold_on`'s docstring advertises the env flip as taking effect without a redeploy, so
    (K9-2 off, K9-3 on) is reachable on the live serving process; MEASURED in that cell before the
    predicate was shared: `= 900 %` and `= 1,875 %` against `= 9 ratio` / `= 18.75 ratio` at HEAD.
    A flag interlock would have closed that ONE cell and retired wrongly the day K9-2's flag retires.
    The class is refused instead, so all four cells are safe and the built reach equals the design's
    stated reach (deep 1 call, max 14) by construction rather than by shipping order."""
    for k92 in (None, "on"):
        for k93 in (None, "on"):
            if k92 is None:
                monkeypatch.delenv(FLAG_K92, raising=False)
            else:
                monkeypatch.setenv(FLAG_K92, k92)
            if k93 is None:
                monkeypatch.delenv(FLAG_K93, raising=False)
            else:
                monkeypatch.setenv(FLAG_K93, k93)
            for key in ("max_N9", "max_N10", "deep_N25", "deep_N26"):
                c = cit.from_number(cit.harmonise_declared_scale([_CENSUS_A[key]])[0], 1)
                if k92 == "on":
                    assert c.value is None and _WITHHELD.format(k=32) in c.label, (key, k92, k93)
                else:
                    assert c.label == _BANKED[key], (key, k92, k93)   # HEAD, byte for byte
                assert "900 %" not in c.label and "1,875 %" not in c.label
                assert "22.5 MMT" not in c.label
            # THE FOUR BANKED CENSUS-A KEYS ARE NOW REFUSED TWICE OVER (su_ratio and production_mt are
            # both table-fence refusals), so the predicate is ALSO asserted on a key only IT can stop --
            # otherwise a mutation to `_unscoped_multi_geo` passes this cell on the fence's coat-tails.
            live = _unscoped_multigeo("consumption_mt", "canola_ice", 1907, "9.0")
            c = cit.from_number(cit.harmonise_declared_scale([live])[0], 1)
            assert "MMT" not in c.label, (k92, k93)
            if k92 == "on":
                assert c.value is None and _WITHHELD.format(k=32) in c.label, (k92, k93)
            else:
                assert (c.value, c.unit) == ("9.0", "MT"), (k92, k93)
                assert c.label.startswith("USDA PSD consumption ICE canola = 9 MT ["), (k92, k93)


def test_k9_3_the_unscoped_predicate_is_literally_shared_with_k9_2(monkeypatch):
    """ONE PREDICATE, TWO CONSUMERS -- asserted on the SOURCE, because the whole point is that the two
    items cannot drift into two readings of "unscoped multi-geo". A read that names ONE scope, and a read
    whose rows name NONE, are outside the class on both sides: their rescale survives."""
    import inspect
    assert "_unscoped_multi_geo(q, _geos)" in inspect.getsource(cit.from_number)
    assert "_unscoped_multi_geo(q, _geo_scopes(rows))" in inspect.getsource(cit._harmonised_call)
    monkeypatch.setenv(FLAG_K93, "on")
    monkeypatch.delenv(FLAG_K92, raising=False)
    # the K9-2 fixture reads silver_psd.production_mt, which the TABLE fence now refuses outright, so
    # the one-scope shape is asserted on the same query on a key the fence leaves moving. The predicate
    # under test is `_unscoped_multi_geo`, and it does not read the metric.
    one_scope = dict(_one_scope_free_axis())
    one_scope["query"] = dict(one_scope["query"], metric="consumption_mt")
    h = cit.harmonise_declared_scale([one_scope])[0]
    assert h is not one_scope and cit.from_number(h, 1).unit == "MMT"
    psd_prod = _one_scope_free_axis()                        # ...and the refused key is untouched here
    assert cit.harmonise_declared_scale([psd_prod])[0] is psd_prod
    zero_scope = _zero_scope_fx()                            # rows name no scope at all -- unmapped too
    assert cit.harmonise_declared_scale([zero_scope])[0] is zero_scope


# ── THE NEW INVARIANTS HAVE A LINT HOME (review MAJOR-2) ──────────────────────────────
def test_k9_3_the_cross_ref_and_delta_invariants_are_linted_not_fail_silent(monkeypatch):
    """Design section 9 names this file for K9-3 BY ADDRESS ("K9-3 extends the cascade_map lint
    neighbourhood at config_check.py:285-286"). Before the fix-pass both new invariants were fail-silent:
    `narrate_scale` returned None, the harmonisation switched off for the key, and the panel went back to
    two scales with no build error. The existing per-ref check is structurally blind to both -- it visits
    one silver_ref at a time."""
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag.numbers import cascade as csc
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    assert cc._check_narrate_scale_family(reg) == []      # GREEN on the live estate, and so is its home
    assert cc.check_cascade_map() == []

    # (i) the live map ALREADY carries two refs that disagree about the unit for one key
    # (gold_futures_spreads.spread_value: 'US cents/bushel' vs 'ZAR/t'). Both at scale 1, so no
    # harmonisation is owed and it is deliberately NOT an error -- the day such a key gains a scale it is.
    live = {r["narrate_unit"] for r in csc.load_map().values()
            if r.get("table") == "gold_futures_spreads" and r.get("metric") == "spread_value"}
    assert live == {"US cents/bushel", "ZAR/t"}
    two = {"kc": {"table": "gold_futures_spreads", "metric": "spread_value", "scale": 100,
                  "narrate_unit": "US cents/bushel"},
           "wy": {"table": "gold_futures_spreads", "metric": "spread_value", "scale": 100,
                  "narrate_unit": "ZAR/t"}}
    monkeypatch.setattr(csc, "load_map", lambda: two)
    errs = cc._check_narrate_scale_family(reg)
    assert any("DISAGREE about (scale, narrate_unit)" in e for e in errs), errs
    assert cit.narrate_scale("gold_futures_spreads", "spread_value") is None   # the silence it names

    # (ii) a co-unit sibling whose parent is narrated in a unit the estate has no word for a change of
    from types import SimpleNamespace as NS
    card = NS(metrics={"area": NS(unit="1000 ha"), "area_revision": NS(unit="1000 ha")})
    monkeypatch.setattr(csc, "load_map", lambda: {"a": {"table": "silver_demo", "metric": "area",
                                                       "scale": 0.001, "narrate_unit": "M ha"}})
    errs = cc._check_narrate_scale_family(NS(tables={"silver_demo": card}))
    assert any("declares no delta_unit for 'M ha'" in e for e in errs), errs


def test_k9_3_the_table_axis_refusal_has_a_lint_home_that_names_the_disagreeing_tables(monkeypatch):
    """INVARIANT (iii), the verify FATAL's other half: the refusal must never be silent. Two halves,
    and they fire on different days on purpose.

    (iii-b) is FLAG-GATED, AND NOT FOR THE REASON THE FIRST BUILD GAVE. That reason -- "with the flag
    off nothing is harmonised, so a family that disagrees costs the reader nothing" -- is FALSE, and
    the pin below this one measures it false: `cascade._prescaled` stamps the map's narrate_unit and
    scales the value with no flag involved, so the half-move is live at HEAD on all four families. The
    gate is about BLAST RADIUS instead: erroring at the default would fail every co-tenant's build
    today (tests/unit/test_cascade.py:563 asserts `check_cascade_map() == []`) for a HEAD defect this
    dark item neither caused nor can close from this seam -- only a cascade_map row for each silent
    sibling table closes it. What the gate buys is that the FLIP cannot ship a half-move: the live
    estate is GREEN at the default (measured: 0 errors, and `check_cascade_map()` empty), and the
    moment the flag is ON the build names all four families and every silent table BY ADDRESS.

    (iii-a) is UNCONDITIONAL, because the cascade pre-scales its OWN mints from these rows: a family
    the map narrates two ways prints one name on two scales at HEAD, flag or no flag. No live family
    does, so it is pinned on the shape."""
    from types import SimpleNamespace as NS

    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag.numbers import cascade as csc
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    monkeypatch.delenv(FLAG_K93, raising=False)
    assert cc._check_display_name_families(reg) == []          # GREEN at the default, and so is its home
    assert cc.check_cascade_map() == []

    monkeypatch.setenv(FLAG_K93, "on")
    errs = cc._check_display_name_families(reg)
    assert len(errs) == 4, errs
    joined = "\n".join(errs)
    for table in ("silver_mpob.su_ratio", "silver_icco_cocoa.su_ratio",
                  "silver_nass_annual.production_mt", "silver_mpoc_trade_stats_monthly.exports_mt",
                  "silver_mpoc_exports_by_country.exports_mt",
                  "silver_mpoc_stock_comparison.ending_stocks_mt"):
        assert f"{table}=UNMAPPED" in joined, table
    for name in ("'stocks-to-use ratio'", "'production'", "'exports'", "'ending stocks'"):
        assert name in joined, name
    assert "refuses the WHOLE family" in joined and cc.check_cascade_map() != []

    # (iii-a): two MAPPED members of one printed name, narrated two ways -- an error at EVERY setting
    card = NS(metrics={"a_mt": NS(unit="MT"), "b_mt": NS(unit="MT")})
    two = NS(tables={"silver_demo_a": NS(metrics={"a_mt": NS(unit="MT")}),
                     "silver_demo_b": NS(metrics={"a_mt": NS(unit="MT")})})
    monkeypatch.setattr(csc, "load_map", lambda: {
        "x": {"table": "silver_demo_a", "metric": "a_mt", "scale": 1e-06, "narrate_unit": "MMT"},
        "y": {"table": "silver_demo_b", "metric": "a_mt", "scale": 0.001, "narrate_unit": "1000 MT"}})
    monkeypatch.delenv(FLAG_K93, raising=False)
    errs = cc._check_display_name_families(two)
    assert any("narrated TWO WAYS by the map" in e for e in errs), errs
    assert "silver_demo_a.a_mt=1e-06/'MMT'" in errs[0] and "silver_demo_b.a_mt=0.001/'1000 MT'" in errs[0]
    # ...and the producer refuses BOTH sides of it rather than picking one
    from leviathan.graphrag.numbers import registry as rg
    monkeypatch.setattr(rg, "load_registry", lambda: two)
    assert cit.narrate_scale("silver_demo_a", "a_mt") is None
    assert cit.narrate_scale("silver_demo_b", "a_mt") is None
    assert cc._check_display_name_families(NS(tables={"silver_demo": card})) == []   # one member each


def test_k9_3_the_head_residual_under_one_printed_name_is_flag_independent(monkeypatch):
    """WHAT (iii-b) DECLINES TO ERROR ON AT THE DEFAULT, MEASURED RATHER THAN ASSERTED IN PROSE
    (verify MAJOR, re-fix). The first build gated (iii-b) on "with the flag off nothing is harmonised
    and no half-move is possible, so the divergence costs the reader nothing". That reason is FALSE.
    `cascade._prescaled` stamps `tgt['unit'] = row.get('narrate_unit')` and scales the value from the
    SAME cascade_map rows `citations.narrate_scale` reads, with no flag involved -- so the cascade's
    own mint already prints the map's narration while the silent sibling table prints the card's, at
    HEAD, at the default.

    RENDERED HERE THROUGH THE REAL PRODUCERS (`cascade._prescaled` then `citations.from_number`), one
    panel, one commodity, one country, one marketing year, the same underlying value: the corn line is
    the sharpest form, 384 MMT beside 384,000,000 MT under one printed name.

    THE FLAG MOVES NEITHER LINE, which is why this is a HEAD residual and not something this item
    mints: `narrate_scale` refuses all four colliding families, so flag-on is byte-identical to
    flag-off on the whole colliding panel. The price is written up in the (iii-b) clause of
    `config_check._check_narrate_scale_family`'s block: 4 families across 6 silent tables, closable
    only by a cascade_map row for each silent sibling table."""
    from leviathan.graphrag.numbers import cascade as cq
    monkeypatch.delenv("GRAPHRAG_SCOPE_WITHHOLD", raising=False)
    cmap = cq.load_map() or {}

    def maprow(table, metric):
        for _ref, r in sorted(cmap.items()):
            if isinstance(r, dict) and r.get("table") == table and r.get("metric") == metric:
                return r
        return None

    def rec(table, metric, commodity, country, period, value):
        return _k93(table, metric, commodity, country, period,
                    [_row(period, value, None, country, "2026-08-12")])

    cases = (
        (("silver_psd", "production_mt", 384000000.0),
         ("silver_nass_annual", "production_mt", 384000000.0),
         "corn_cbot", "United States", "2025",
         "USDA PSD production CBOT corn United States MY2025 = 384 MMT",
         "NASS ANNUAL production CBOT corn United States MY2025 = 384,000,000 MT"),
        (("silver_psd", "su_ratio", 0.1512),
         ("silver_mpob", "su_ratio", 1.88792309604088),
         "malaysian_crude_palm_oil_cme", "Malaysia", "2025",
         "USDA PSD stocks-to-use ratio CME palm oil Malaysia MY2025 = 15.12 %",
         "MPOB stocks-to-use ratio CME palm oil Malaysia MY2025 = 1.88792 ratio"),
    )
    for (mt, mm, mv), (st, sm, sv), commodity, country, period, want_mint, want_sib in cases:
        row = maprow(mt, mm)
        assert row is not None and float(row.get("scale", 1)) != 1, (mt, mm)
        # the two keys DO print under one name in one declared card unit -- that is the collision
        assert cit._metric_display_name(mt, mm) == cit._metric_display_name(st, sm)
        reg = cit._registry_or_none()
        assert cit._card_unit(reg, mt, mm) == cit._card_unit(reg, st, sm)
        for setting in (None, "on"):
            if setting is None:
                monkeypatch.delenv(FLAG_K93, raising=False)
            else:
                monkeypatch.setenv(FLAG_K93, setting)
            mint = cq._prescaled(rec(mt, mm, commodity, country, period, mv), row, 1)
            sib = rec(st, sm, commodity, country, period, sv)
            pub = cit.harmonise_declared_scale([mint, sib])
            assert cit.from_number(pub[0], 1).label == want_mint, (setting, mt, mm)
            assert cit.from_number(pub[1], 2).label == want_sib, (setting, st, sm)
        # ...and the flag buys nothing here because the family is refused outright
        assert cit.narrate_scale(mt, mm) is None
        assert cit._map_scale(mt, mm) is not None                 # the MAP still declares the scale
        assert (st, sm) in cit._family_scale_conflict(mt, mm, cit._map_scale(mt, mm))


# ── WHAT THE CONVERGENCE ARMS DOWNSTREAM (review MINOR) ────────────────────────────
def test_k9_3_the_convergence_arms_the_clone_dedup_and_the_pool_does_not_loosen(monkeypatch):
    """The proof that the harmonisation MINTS NOTHING is that the agent's [N27] becomes byte-identical to
    the cascade's mint [N32] -- and byte-identity is precisely `answer._number_row_clones`' clone
    predicate (it keys on `label + "  [known " + date + "]"`). So the convergence ARMS a dedup, which is
    that function's own definition working ("two lines matching there are two renderings of one fact"),
    and the report has to say so: claim_count / handles_checked / CitedN move with the flag on by
    DE-DUPLICATION, and section 8's anti-suppression floor reads those instruments.

    THE SURVIVOR IS THE LOWEST INDEX -- the agent's read, which carries no `shown` binding -- so
    `verify._mismatch_pool` falls back to `_row_vals`. MEASURED here rather than feared: after
    harmonisation that fallback pool is the mint's `shown` list exactly.

    RE-BASED FROM the su_ratio pair ONTO the consumption pair by the verify FATAL -- same panel, same
    table, same convergence, on a display name the table-axis fence has nothing to refuse."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import verify as vf
    calls = [_K93_CALLS["max_N27"], _K93_CALLS["max_N32mint"]]
    monkeypatch.delenv(FLAG_K93, raising=False)
    off = list(cit.harmonise_declared_scale(calls))
    st = {"tldr": "meal domestic use [N1] against the engine's own [N2].", "mechanism": ""}
    assert an._number_row_clones([1, 2], off) == {}
    assert an._dedup_number_handles(st, off) == 0 and "[N2]" in st["tldr"]
    monkeypatch.setenv(FLAG_K93, "on")
    on = list(cit.harmonise_declared_scale(calls))
    st = {"tldr": "meal domestic use [N1] against the engine's own [N2].", "mechanism": ""}
    assert an._number_row_clones([1, 2], on) == {2: 1}
    assert an._dedup_number_handles(st, on) == 1 and "[N2]" not in st["tldr"]
    # the survivor has no `shown`, and its row pool is the mint's `shown` list -- no looser, measured
    survivor = on[0]
    assert "shown" not in survivor
    assert (vf._mismatch_pool(survivor, vf._row_vals(survivor))
            == vf._mismatch_pool(on[1], vf._row_vals(on[1]))
            == [39.599])


# ── K9-6 THE FOUR-FIGURE LINE -- class (5), flag GRAPHRAG_XC_LEG_HANDLES ──────────────────────────────
FLAG_K96 = "GRAPHRAG_XC_LEG_HANDLES"

# THE MEASURED TRIGGER, quoted verbatim from the judged panel (cascade_panel.json, deep STOP entry #19,
# id rv_canola_rapeoil; CONTROL = deep, so this is ANSWER B):
#   "World soybean oil stocks-to-use MY2009: 10.1401%, versus MY2008 10.2351%, a change of -0.0950733pp
#    over the window [N34]."
# and its MAX twin (cascade_pair_rv_soyoil_palm.md TL;DR, TREATMENT = max): "loosened from 8.67531% ...
# correction -- palm went 20.9588% to 22.4415% [N34]" -- a retraction the writer shipped IN the answer.
# ONE handle carried THREE magnitudes, and the two it did not name were printed off the RAW float while
# the rows the engine minted carry `round(v, 4)`.
_K96_STOP_TOKEN_DEEP = "-0.0950733"       # the delta token the deep writer copied; no [N] resolves to it
_K96_STOP_TOKEN_MAX = "8.67531"           # the baseline token the max writer copied, then retracted


def _k96_pair(pair_id, a, b):
    """A minimal complex_map pair row -- the `_pair` shape test_reroute_v2_engine.py uses, restated here so
    this deck owns its fixture (both legs `world`/`material`, which is all `_xc_sides_ok` reads)."""
    import types
    return types.SimpleNamespace(
        id=pair_id, pair=(a, b), complex_name="vegoil_substitution", shared_event="soyoil_palm_premium",
        side_a={"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        side_b={"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        direction="opposing", focus_rule="query", materiality_tier="material")


def _k96_render(monkeypatch, pair, source, target, window, table, base, *, comove, handles):
    """Drive the ONE producer end to end. `_world_su_ratio` is stubbed with the RAW percentages the banked
    panel was rendered from, so `_leg_world_deltas` computes the same raw `d = b - a` the engine computed
    and `_xc_call` mints the same `round(v, 4)` rows. Returns (lines, calls, fired)."""
    from leviathan.graphrag.numbers import cascade as cq

    def fake(qfn, slug, my, asof):
        return (table[(slug, my)], "2026-05-10", 5) if (slug, my) in table else None
    monkeypatch.setattr(cq, "_world_su_ratio", fake)
    calls: list = []
    kw = {"xc_leg_handles": True} if handles else {}
    lines, fired = cq._reroute_xc(pair, source, target, window, None, "2026-09-06",
                                  calls, base, None, comove, **kw)
    return lines, calls, fired


# THE DEEP FIXTURE, reproducing the banked rv_canola_rapeoil block. The raw percentages were SOLVED this
# sitting so that all six minted rows equal the banked row values (N34 10.1401, N35 10.2351, N36 -0.0951,
# N37 14.9002, N38 14.9591, N39 -0.0589) AND the flag-off line prints the STOP sentence's own tokens
# (10.1401 / 10.2351 / -0.0950733). Both legs tighten, so this is the CO-MOVE fork -- as the banked turn
# was. `base=33` makes the handles read N34..N39, the banked numbering.
_K96_DEEP_PAIR = ("soybean_oil_cbot", "rapeseed_oil_zce")
_K96_DEEP_TABLE = {("soybean_oil_cbot", 2008): 10.2351234, ("soybean_oil_cbot", 2009): 10.1400501,
                   ("rapeseed_oil_zce", 2008): 14.9590812, ("rapeseed_oil_zce", 2009): 14.9002}
_K96_DEEP_WINDOW = [("2008-11-01", "2009-11-01")]        # Oct-start on both legs -> MY2008, MY2009

# THE MAX FIXTURE, reproducing the banked rv_soyoil_palm block: N34 22.4415, N35 20.9588, N36 1.4827,
# N37 9.9115, N38 8.6753, N39 1.2361, with the flag-off soyoil leg printing the retracted 8.67531.
_K96_MAX_PAIR = ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")
_K96_MAX_TABLE = {("malaysian_crude_palm_oil_cme", 2024): 20.9588,
                  ("malaysian_crude_palm_oil_cme", 2025): 22.4415,
                  ("soybean_oil_cbot", 2024): 8.675310123,
                  ("soybean_oil_cbot", 2025): 9.911450123}
_K96_MAX_WINDOW = [("2024-11-01", "2025-11-01")]

# THE DIVERGENCE FIXTURE (the CROSS-COMMODITY marker, the other half of fix (iii)): soyoil tightens while
# palm loosens, the shape test_reroute_v2_engine.py's sign-oppose test already pins at HEAD.
_K96_DIV_PAIR = ("soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
_K96_DIV_TABLE = {("soybean_oil_cbot", 2024): 9.4, ("soybean_oil_cbot", 2025): 8.1,
                  ("malaysian_crude_palm_oil_cme", 2024): 11.0,
                  ("malaysian_crude_palm_oil_cme", 2025): 12.6}

_K96_TAG = " [series: {slug}; country: World; table: USDA PSD]"

# Every RENDERED MAGNITUDE on a leg line, and nothing else: a numeral is a magnitude here only when a
# unit follows it ('%' or 'pp'). Deliberately unit-anchored rather than "every numeral" -- the line also
# carries handle digits ([N34]) and a marketing year (MY2009), and a bare-numeral scan would call those
# magnitudes and make the GREEN band pin measure the wrong tokens.
_MAGNITUDE_RX = re.compile(r"([-+]?[0-9][0-9.e+-]*)(?:%|pp)")

# HEAD's renders, frozen. Every one was produced by this fixture against HEAD's producer before a byte of
# the fix ran, and the flag-off path must reproduce them exactly.
_K96_HEAD = {
    "deep_legA": ("- [N34] world soybean oil stocks-to-use MY2009: 10.1401% "
                  "(vs MY2008 10.2351%, -0.0950733pp over the window)"
                  + _K96_TAG.format(slug="soybean_oil_cbot")),
    "deep_legB": ("- [N37] world rapeseed oil stocks-to-use MY2009: 14.9002% "
                  "(vs MY2008 14.9591%, -0.0588812pp over the window)"
                  + _K96_TAG.format(slug="rapeseed_oil_zce")),
    "deep_marker": ("CO-MOVE on su_ratio: both world soybean oil and world rapeseed oil tightened "
                    "(stocks-to-use 10.2351%->10.1401% and 14.9591%->14.9002%)"),
    "max_legB": ("- [N37] world soybean oil stocks-to-use MY2025: 9.91145% "
                 "(vs MY2024 8.67531%, +1.23614pp over the window)"
                 + _K96_TAG.format(slug="soybean_oil_cbot")),
    "max_marker": ("CO-MOVE on su_ratio: both world malaysian crude palm oil and world soybean oil "
                   "loosened (stocks-to-use 20.9588%->22.4415% and 8.67531%->9.91145%)"),
    "div_legA": ("- [N1] world soybean oil stocks-to-use MY2025: 8.1% (vs MY2024 9.4%, -1.3pp over the "
                 "window)" + _K96_TAG.format(slug="soybean_oil_cbot")),
    "div_marker": ("CROSS-COMMODITY on su_ratio: world soybean oil 8.1% (-1.3pp) vs "
                   "world malaysian crude palm oil 12.6% (+1.6pp) over MY2024-MY2025"),
}

# The post-fix renders the design's PIN section states, in its own shape:
#   `- [N34] ... MY2009: 10.1401% (vs MY2008 [N35] 10.2351%, [N36] -0.0951pp over the window)`
_K96_FIXED = {
    "deep_legA": ("- [N34] world soybean oil stocks-to-use MY2009: 10.1401% "
                  "(vs MY2008 [N35] 10.2351%, [N36] -0.0951pp over the window)"
                  + _K96_TAG.format(slug="soybean_oil_cbot")),
    "deep_legB": ("- [N37] world rapeseed oil stocks-to-use MY2009: 14.9002% "
                  "(vs MY2008 [N38] 14.9591%, [N39] -0.0589pp over the window)"
                  + _K96_TAG.format(slug="rapeseed_oil_zce")),
    "max_legB": ("- [N37] world soybean oil stocks-to-use MY2025: 9.9115% "
                 "(vs MY2024 [N38] 8.6753%, [N39] +1.2361pp over the window)"
                 + _K96_TAG.format(slug="soybean_oil_cbot")),
}


def _k96_deep(monkeypatch, handles):
    return _k96_render(monkeypatch, _k96_pair("canola_rapeoil_vegoil", *_K96_DEEP_PAIR),
                       *_K96_DEEP_PAIR, _K96_DEEP_WINDOW, _K96_DEEP_TABLE, 33,
                       comove=True, handles=handles)


def _k96_max(monkeypatch, handles):
    return _k96_render(monkeypatch, _k96_pair("soyoil_palm_vegoil", *_K96_MAX_PAIR),
                       *_K96_MAX_PAIR, _K96_MAX_WINDOW, _K96_MAX_TABLE, 33,
                       comove=True, handles=handles)


def _k96_div(monkeypatch, handles):
    return _k96_render(monkeypatch, _k96_pair("soyoil_palm_vegoil", *_K96_DIV_PAIR),
                       *_K96_DIV_PAIR, _K96_MAX_WINDOW, _K96_DIV_TABLE, 0,
                       comove=False, handles=handles)


def test_k9_6_flag_off_is_byte_identical_to_the_banked_panel(monkeypatch):
    """THE OFF PIN, and it is the rollback proof: with the kwarg absent every leg line and BOTH marker
    literals reproduce the banked bytes on all three forks -- the deep co-move, the max co-move and the
    divergence. Flipping GRAPHRAG_XC_LEG_HANDLES off returns the serving surface to HEAD exactly."""
    d_lines, d_calls, d_fired = _k96_deep(monkeypatch, handles=False)
    assert d_lines[0] == _K96_HEAD["deep_legA"]
    assert d_lines[1] == _K96_HEAD["deep_legB"]
    assert d_lines[2].startswith(_K96_HEAD["deep_marker"])
    # the STOP sentence's own token IS in HEAD's panel -- which is why the writer could copy it
    assert _K96_STOP_TOKEN_DEEP in d_lines[0]
    assert [c["rows"][0]["value"] for c in d_calls] == [10.1401, 10.2351, -0.0951,
                                                        14.9002, 14.9591, -0.0589]

    m_lines, m_calls, _m_fired = _k96_max(monkeypatch, handles=False)
    assert m_lines[1] == _K96_HEAD["max_legB"]
    assert m_lines[2].startswith(_K96_HEAD["max_marker"])
    assert _K96_STOP_TOKEN_MAX in m_lines[1] and _K96_STOP_TOKEN_MAX in m_lines[2]
    assert [c["rows"][0]["value"] for c in m_calls] == [22.4415, 20.9588, 1.4827,
                                                        9.9115, 8.6753, 1.2361]

    v_lines, _v_calls, _v_fired = _k96_div(monkeypatch, handles=False)
    assert v_lines[0] == _K96_HEAD["div_legA"]
    assert v_lines[2].startswith(_K96_HEAD["div_marker"])
    assert d_fired["window"] == "MY2008-MY2009"


def test_k9_6_red_deep_the_uncited_delta_token_is_not_in_the_panel_to_copy(monkeypatch):
    """RED (DEEP), design section 6: deep STOP entry #19. The writer's sentence transcribed a comparator
    and a delta that NO handle resolved to, and the delta token it printed (-0.0950733) was a second
    rendering of the raw float while the row [N36] carries -0.0951.

    After the fix the line the writer copies names [N35] and [N36] and prints the ROWS' own tokens, and
    the string -0.0950733 does not occur ANYWHERE in the rendered block -- so that sentence is
    unwritable from this panel."""
    lines, calls, _fired = _k96_deep(monkeypatch, handles=True)
    assert lines[0] == _K96_FIXED["deep_legA"]
    assert lines[1] == _K96_FIXED["deep_legB"]
    body = "\n".join(lines)
    assert _K96_STOP_TOKEN_DEEP not in body
    # and the tokens it DOES print are the values the named handles resolve to
    assert calls[1]["rows"][0]["value"] == 10.2351 and calls[2]["rows"][0]["value"] == -0.0951


def test_k9_6_red_max_the_retracted_baseline_token_is_not_in_the_panel_to_copy(monkeypatch):
    """RED (MAX, same fix), design section 6: rv_soyoil_palm's TL;DR shipped the retraction itself
    ("loosened from 8.67531% ... correction -- palm went 20.9588% to 22.4415% [N34]"). The token 8.67531
    is the raw-float rendering of the row [N38] carries as 8.6753.

    After the fix 8.67531 is absent from the leg line AND from the CO-MOVE marker, and 8.6753 prints
    under its own [N38]."""
    lines, _calls, _fired = _k96_max(monkeypatch, handles=True)
    assert lines[1] == _K96_FIXED["max_legB"]
    body = "\n".join(lines)
    assert _K96_STOP_TOKEN_MAX not in body
    assert "[N38] 8.6753%" in body


def test_k9_6_the_co_move_marker_names_a_handle_for_every_figure_it_restates(monkeypatch):
    """FIX (iii), the design's second half of this class: the CO-MOVE marker restated FOUR percentages of
    TWO commodities in one sentence with NO handle at all. Flag on, each arrow endpoint carries the handle
    of the row it came from -- baseline [N{h+1}] -> endpoint [N{h}] -- and prints that row's value."""
    lines, _calls, _fired = _k96_deep(monkeypatch, handles=True)
    marker = lines[2]
    assert ("CO-MOVE on su_ratio: both world soybean oil and world rapeseed oil tightened "
            "(stocks-to-use [N35] 10.2351%->[N34] 10.1401% and [N38] 14.9591%->[N37] 14.9002%)") in marker
    # four magnitudes, four handles -- counted, not eyeballed
    assert marker.count("%->") == 2
    assert sum(marker.count("[N%d]" % k) for k in (34, 35, 37, 38)) == 4
    assert _K96_STOP_TOKEN_DEEP not in marker


def test_k9_6_the_cross_commodity_marker_names_a_handle_for_every_figure_it_restates(monkeypatch):
    """FIX (iii) on the DIVERGENCE fork. The CROSS-COMMODITY marker restates both endpoints and both
    deltas; flag on it names [N1]/[N3] and [N4]/[N6], the endpoint and delta rows of each leg."""
    lines, _calls, fired = _k96_div(monkeypatch, handles=True)
    assert lines[0] == ("- [N1] world soybean oil stocks-to-use MY2025: 8.1% "
                        "(vs MY2024 [N2] 9.4%, [N3] -1.3pp over the window)"
                        + _K96_TAG.format(slug="soybean_oil_cbot"))
    marker = lines[2]
    assert ("CROSS-COMMODITY on su_ratio: world soybean oil [N1] 8.1% ([N3] -1.3pp) vs "
            "world malaysian crude palm oil [N4] 12.6% ([N6] +1.6pp) over MY2024-MY2025") in marker
    # the fork verdict itself is untouched: this item moves handles and value sources, never a sign
    assert fired["reroute_v2"] is True and "## Cross-commodity" in marker


def test_k9_6_green_every_magnitude_at_or_above_ten_prints_the_token_it_prints_today(monkeypatch):
    """GREEN, design section 6: "every |v| >= 10 magnitude on every leg line prints exactly the token it
    prints today". MEASURED here on the deep fixture, whose four level magnitudes all sit in [10, 100):
    10.1401 / 10.2351 / 14.9002 / 14.9591 are byte-identical off and on. Only the two sub-10 deltas move,
    which is the class.

    AND THE PIN IS NARROWED TO THE BAND THE FIX ACTUALLY HOLDS IN (review MINOR, 2026-09-07). The design
    wrote the GREEN as "|v| >= 10"; the build's own seeded measurement says that is FALSE above 100 --
    4,481 of 89,787 draws in [100, 1000) and 517 of 100,138 at or above 1000 move, by DOUBLE ROUNDING.
    So the claim this deck stands behind is [10, 100), stated as a measurement here rather than left as a
    sentence the code does not satisfy. The band above 100 is unreachable on THIS surface -- a World
    stocks-to-use ratio is a share of a year's use, and the twelve banked legs measure 8.1%-22.4% -- but
    "unreachable" is the reason the narrowing is safe, never a reason to leave the wider claim standing.
    The counterexample is asserted below so the narrowing has teeth: a value the design's GREEN covers
    and this fix moves."""
    off, _oc, _of = _k96_deep(monkeypatch, handles=False)
    on, _nc, _nf = _k96_deep(monkeypatch, handles=True)
    for tok in ("10.1401%", "10.2351%", "14.9002%", "14.9591%"):
        assert tok in off[0] + off[1] and tok in on[0] + on[1]
    # the ONLY tokens that moved are the two deltas, and they moved onto the rows' own values
    assert ("-0.0950733pp" in off[0]) and ("-0.0951pp" in on[0])
    assert ("-0.0588812pp" in off[1]) and ("-0.0589pp" in on[1])
    # EVERY |v| >= 10 magnitude on ALL THREE fixtures, not just the deep one: eight of them, unmoved.
    for fixture in (_k96_deep, _k96_max, _k96_div):
        o, _c1, _f1 = fixture(monkeypatch, handles=False)
        n, _c2, _f2 = fixture(monkeypatch, handles=True)
        for i in (0, 1):
            for tok in _MAGNITUDE_RX.findall(o[i]):
                if abs(float(tok)) >= 10:
                    assert tok in n[i], (tok, o[i], n[i])
    # THE NARROWING, measured: the design's own wording covers this value and the value SOURCE moves it.
    assert "%g" % 342.24745403 == "342.247" and "%g" % round(342.24745403, 4) == "342.248"


def test_k9_6_green_the_fired_trace_and_the_verdict_words_and_the_window_do_not_move(monkeypatch):
    """GREEN, design section 6: `xc_open_pair` and the `fired` trace keys (`su_ratio_A`, `dA`, `myA`, ...)
    are unchanged, and the block still renders its verdict words and its window. The flag moves RENDERED
    HANDLES and the VALUE SOURCE of already-rendered magnitudes -- nothing else."""
    for fixture in (_k96_deep, _k96_max, _k96_div):
        off_lines, off_calls, off_fired = fixture(monkeypatch, handles=False)
        on_lines, on_calls, on_fired = fixture(monkeypatch, handles=True)
        assert off_fired == on_fired                       # every key, every value
        assert len(off_lines) == len(on_lines) == 3
        assert len(off_calls) == len(on_calls) == 6
        # the marker's verdict/frame tail (everything after the last parenthesised magnitude) is untouched
        tail = "-- a complex-wide move, not a relative-value divergence, over "
        alt = "-- the shock reached a second balance sheet"
        assert (tail in off_lines[2]) == (tail in on_lines[2])
        assert (alt in off_lines[2]) == (alt in on_lines[2])
        assert off_lines[2].split(")")[-1] == on_lines[2].split(")")[-1]


def test_k9_6_green_the_n_stride_stays_three_and_the_shown_binding_is_untouched(monkeypatch):
    """GREEN, and the reason NEVER-DROP-THE-CALL matters: [N] indices are POSITIONAL. This item names rows
    the engine ALREADY minted -- it appends nothing and drops nothing, so the stride stays 3 per leg and
    every later handle keeps its position.

    `_shown` still binds the RAW magnitudes on the endpoint call only, deliberately: it is the panel's
    testimony to `verify`, not a rendered byte, and `_num_matches`' one-percent arm already spans the
    round-4 gap. Moving it would move an instrument this item was not asked to move."""
    off, off_calls, _of = _k96_deep(monkeypatch, handles=False)
    on, on_calls, _nf = _k96_deep(monkeypatch, handles=True)
    assert [c["query"] for c in off_calls] == [c["query"] for c in on_calls]
    assert [c["rows"] for c in off_calls] == [c["rows"] for c in on_calls]
    for calls in (off_calls, on_calls):
        assert calls[0]["shown"] == [10.1400501, 10.2351234, -0.09507330000000103]
        assert calls[3]["shown"] == [14.9002, 14.9590812, -0.05888120000000008]
        assert all("shown" not in calls[i] for i in (1, 2, 4, 5))
    assert off[0].startswith("- [N34]") and on[0].startswith("- [N34]")
    assert off[1].startswith("- [N37]") and on[1].startswith("- [N37]")


def test_k9_6_every_rendered_magnitude_is_the_value_its_own_handle_resolves_to(monkeypatch):
    """THE INVARIANT THE ITEM EXISTS FOR, checked as a property rather than as three literals: with the
    flag on, for every `[N{k}] <token>` pair a line prints, <token> is the rendering of the value the
    k-th call's row carries. Measured across all three fixtures -- 18 handle/token pairs."""
    import re
    from leviathan.graphrag.numbers import cascade as cq
    # the ADJACENT shape -- the comparator, the delta, and every marker restatement -- and the LEG-LINE
    # ENDPOINT, whose handle opens the line and whose magnitude closes it after the label and the MY.
    adjacent = re.compile(r"\[N(\d+)\] ([-+]?[0-9][0-9.e+-]*)(?:%|pp)")
    endpoint = re.compile(r"^- \[N(\d+)\] .*?: ([-+]?[0-9][0-9.e+-]*)%")
    seen = 0
    for fixture, base in ((_k96_deep, 33), (_k96_max, 33), (_k96_div, 0)):
        lines, calls, _fired = fixture(monkeypatch, handles=True)
        rows = {base + 1 + i: c["rows"][0]["value"] for i, c in enumerate(calls)}
        for ln in lines:
            for k, tok in adjacent.findall(ln) + endpoint.findall(ln):
                want = rows[int(k)]
                assert tok in ("%g" % want, cq._xc_signed(want)), (ln, k, tok, want)
                seen += 1
    # 3 fixtures x 10: per fixture the two leg lines carry 3 each (endpoint + comparator + delta) and the
    # marker restates 4 (both endpoints and, per fork, both deltas or both baselines).
    assert seen == 30


def test_k9_6_the_signed_delta_reproduces_the_head_format_spec_including_negative_zero():
    """`_fmt`/`_xl_fmt` emit no sign, so the design directs the '+' to be rendered separately -- and the
    obvious way to do that is WRONG on one input. `("+" if v >= 0 else "") + f"{v:g}"` prints '+-0' for
    -0.0, because `-0.0 >= 0` is True in Python while `f"{-0.0:g}"` is '-0'. Reading the sign off the
    RENDERED token instead reproduces `:+g` exactly, on every value including that one.

    -0.0 is REACHABLE, not hypothetical: `_xc_call` mints `round(float(d), 4)`, so any delta in
    (-5e-05, 0) rounds to -0.0 while `_sign` still calls it a move."""
    from leviathan.graphrag.numbers import cascade as cq
    assert ("+" if -0.0 >= 0 else "") + ("%g" % -0.0) == "+-0"      # the trap, stated
    assert cq._xc_signed(-0.0) == "%+g" % -0.0 == "-0"              # the fix, measured
    assert round(-1e-05, 4) == -0.0 and cq._xc_signed(round(-1e-05, 4)) == "-0"
    for v in (0.0, 1.4827, -0.0951, 1.2361, -1.3, 1.6, 12.5, -1234.5678, 1e-07):
        assert cq._xc_signed(v) == "%+g" % float(v)


def test_k9_6_the_precision_bands_reproduce_from_a_pinned_seed():
    """THE BLOCK NOTE'S OWN FIGURES, re-derived rather than recalled -- a comment stating an
    unreproducible measurement is the same class this item closes.

    Seed 20260907, 200,012 draws of `uniform(-2000, 2000)`. Two facts are pinned: (1) why the leg line
    KEEPS ':g' instead of switching to `citations._fmt` (they agree below 1000 and differ on every value
    at or above it), and (2) what the VALUE-SOURCE change actually moves, per band.

    An OWN `random.Random` instance, not `random.seed()`: the module-level functions are bound to one
    hidden generator, so seeding it here would reseed every later test in the session. Verified this
    sitting that `Random(s).uniform(...)` and `seed(s); uniform(...)` produce the identical sequence, so
    the block note's figures are reproducible either way."""
    import random
    from leviathan.graphrag import citations as cit

    rng = random.Random(20260907)
    draws = [rng.uniform(-2000.0, 2000.0) for _ in range(200012)]
    lo_n = sum(1 for v in draws if abs(v) < 1000)
    hi_n = len(draws) - lo_n
    assert (sum(1 for v in draws if abs(v) < 1000 and cit._fmt(v) != "%g" % v), lo_n) == (0, 99874)
    assert (sum(1 for v in draws if abs(v) >= 1000 and cit._fmt(v) != "%g" % v), hi_n) == (100138, 100138)
    assert cit._fmt(1234.5678) == "1,235" and "%g" % 1234.5678 == "1234.57"

    def band(lo, hi):
        vs = [v for v in draws if lo <= abs(v) < hi]
        return sum(1 for v in vs if "%g" % v != "%g" % round(v, 4)), len(vs)
    assert band(10, 100) == (0, 9067)                  # the GREEN band: nothing moves
    assert band(100, 1000) == (4481, 89787)            # double rounding only, unreachable on a su_ratio
    assert band(1000, float("inf")) == (517, 100138)   # ditto
    assert band(0, 10) == (922, 1020)                  # the class: every unbacked figure lives here


def test_k9_6_the_flag_is_read_at_the_answer_seam_and_threaded_never_read_in_the_engine(monkeypatch):
    """[SKEPTIC F3] IS LAW IN cascade.py: the module performs NO environment read of any kind, and two live
    doctrine tests (test_rv_regional, test_transmission_chain) substring-scan its own source for
    `os.environ` / `import os`. The K9-6 reader therefore lives at the answer.py quantify seam and rides
    down as an argument. Read PER CALL, never memoized, so the env-flip rollback is live."""
    from pathlib import Path
    from leviathan.graphrag import answer as an
    from leviathan.graphrag.numbers import cascade as cq

    src = Path(cq.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in src and "import os" not in src
    monkeypatch.delenv(FLAG_K96, raising=False)
    assert an._xc_leg_handles_on() is False
    monkeypatch.setenv(FLAG_K96, "on")
    assert an._xc_leg_handles_on() is True
    monkeypatch.setenv(FLAG_K96, "off")
    assert an._xc_leg_handles_on() is False


def test_k9_6_the_answer_seam_and_both_engine_seams_use_the_omit_when_off_idiom():
    """OMIT-WHEN-OFF, and it is load-bearing rather than cosmetic here: the reroute gate test replaces
    `_reroute_xc` with a lambda that takes positional args only, so an UNCONDITIONAL keyword would raise
    TypeError into the fail-closed swallow and the fork would decline INVISIBLY. Flag off -> the kwarg is
    absent at all three seams -> every default holds.

    BOTH `_reroute_xc` call sites are threaded, because `_xc_leg_lines` and the two marker literals are
    ONE producer rendered from two places (`_run_xc` and the transmission chain composer): a
    half-threaded flag would print handles on one and not the other at one setting of one flag. STATED
    AT ITS TRUE STRENGTH (review MINOR): `quantify` drives the chain composer and `_run_xc` in the SAME
    pass, so a half-threaded flag mixes handled and unhandled leg lines INSIDE ONE PANEL, not only
    between turns. That is why both are threaded -- and it is also why the regional fork's own share of
    the mixture (test_k9_6_the_regional_fork_..., below) is a declared residual rather than a
    non-event."""
    from pathlib import Path
    from leviathan.graphrag import answer as an
    from leviathan.graphrag.numbers import cascade as cq

    asrc = Path(an.__file__).read_text(encoding="utf-8")
    assert '_xlh_kw = {"xc_leg_handles": True} if _xc_leg_handles_on() else {}' in asrc
    # AND THE SPREAD LANDS BEFORE `**_eod_kw`, NOT AFTER IT -- pinned because it is load-bearing, not
    # stylistic. The g1x seam golden's producer (data/consequence_leg/xl_golden_seam_bank.py) locates
    # this block by two anchor STRINGS and knows exactly two; the second is the D-XL spread that closes
    # this call. An append landing ON it leaves the producer with NEITHER anchor, so it exits non-zero
    # and takes that whole gate down. K9-6's spread lands one term earlier, the anchor is where D-XL
    # left it, and the block's byte MOVE is measured in test_cascade_walk.py's g1x pin (`_g1x_sans`)
    # by cutting this insertion's own line set -- never by re-banking.
    # RE-ANCHORED BY K9-4 VINTAGE ROLE (same sitting): a SECOND omit-when-off kwarg now lands between
    # K9-6's spread and `**_eod_kw`, so the pin states the PROPERTY it always meant -- `**_xlh_kw` is
    # somewhere before `**_eod_kw` on the call line, and `**_eod_kw` is still the LAST term, which is
    # what keeps the producer's second anchor where D-XL left it. Not loosened: both halves are still
    # asserted, and the exact adjacency they had is now K9-4's own pin to hold.
    _call_tail = asrc[asrc.index("**_xlh_kw"):]
    _call_tail = _call_tail[:_call_tail.index("\n")]
    assert _call_tail.endswith("**_eod_kw)") and "**_xl_kw" not in _call_tail, _call_tail
    csrc = Path(cq.__file__).read_text(encoding="utf-8")
    assert csrc.count('_lh = {"xc_leg_handles": True} if xc_leg_handles else {}') == 2
    assert csrc.count("**_oa, **_lh)") == 2


def test_k9_6_the_regional_fork_is_deliberately_not_covered_and_keeps_heads_render():
    """DECLARED, NOT HIDDEN. `_xc_regional_leg_lines` is a FORK of `_xc_leg_lines` carrying the same
    one-handle-three-magnitudes shape, but the design's SEAM names `_xc_leg_lines` and the two World
    marker lines and nothing else, and the regional fork renders on NO banked turn of the twelve. It keeps
    HEAD's render and its own lane; extending this flag to it is a measurement, not a guess.

    Pinned on the source so the boundary is a build failure if someone half-extends it: the regional
    entrypoint takes no `xc_leg_handles` parameter and its call site passes only `**_oa`.

    AND THE RESIDUAL IS PINNED AT ITS TRUE WIDTH (review MINOR, 2026-09-07). The block note first
    justified threading both World seams with "a half-threaded flag would print handles on one turn and
    not the next", which UNDERSTATES what this boundary leaves standing: `_run_xc` chooses between the
    regional branch and `_reroute_xc` PER PAIR, inside the same call, and `quantify` runs `_run_xc` and
    the transmission chain composer in the SAME pass -- so with the flag on, one panel can carry a
    handled World leg line and an unhandled regional one. It renders on none of the twelve banked turns
    and the regional lane owns the extension; what this deck owes is that the exposure is written down
    where the next builder reads it, and machine-checked -- both branches below are asserted to live in
    ONE function body, which is the fact that makes it within-panel rather than across-turn."""
    import inspect
    from pathlib import Path
    from leviathan.graphrag.numbers import cascade as cq

    assert "xc_leg_handles" not in inspect.signature(cq._reroute_xc_regional).parameters
    assert "handles" not in inspect.signature(cq._xc_regional_leg_lines).parameters
    src = Path(cq.__file__).read_text(encoding="utf-8")
    assert "calls, len(calls), sg, comove, **_oa)" in src        # the regional call, unthreaded
    # THE WITHIN-PANEL FACT, measured on the source rather than asserted in prose: BOTH the unthreaded
    # regional call and the threaded World call are in `_run_xc`'s OWN body, selected per pair.
    run_xc = inspect.getsource(cq._run_xc)
    assert "calls, len(calls), sg, comove, **_oa)" in run_xc          # regional branch: HEAD's render
    assert "len(calls), sg, comove, **_oa, **_lh)" in run_xc          # World branch: threaded
    assert run_xc.count('_lh = {"xc_leg_handles": True} if xc_leg_handles else {}') == 1
    # ...and the composer that can render World links on the SAME quantify pass is threaded too, so the
    # ONLY unhandled leg-line producer reachable inside one panel is the regional fork this test declares.
    # THE SAME-PASS FACT ITSELF: `quantify` calls the transmission composer AND `_run_xc` in one body.
    quant = inspect.getsource(cq.quantify)
    assert "_transmission_legs(" in quant and "_run_xc(" in quant
    assert "xc_leg_handles" in inspect.signature(cq.quantify).parameters


def test_k9_6_the_seam_golden_is_re_anchored_on_this_insertion_and_not_re_banked():
    """THE CONSEQUENCE THIS ITEM PAID FOR, pinned so it cannot be undone quietly.

    K9-6 appends ONE kwarg inside `_answer_l2`'s kwarg-assembly block -- the block the D-XL flag-off
    seam golden (tests/unit/test_cascade_walk.py::test_g1x_...) banks byte-for-byte. That golden RED-ed
    on this build, and it red-ed the worst way: its producer locates the block by two anchor STRINGS,
    the second being the `**_eod_kw` spread D-XL left closing the call, so an append landing ON that
    spread left it with NEITHER anchor and it exited non-zero, taking the whole gate down rather than
    reporting a moved byte.

    REPAIRED ON A NAMED CAUSE, WITH THE PRE-BANK KEPT AND NOT ONE BYTE RE-BANKED:
      * the spread lands one term EARLIER, so the golden's end anchor is exactly where D-XL left it and
        the producer runs (asserted above, on the answer.py source);
      * the block's BYTES still move -- they must, this insertion is inside it -- and that move is
        MEASURED by `_g1x_sans`, which cuts K9-6's own line set with the producer's own line-set
        discipline and lands on the banked HEAD sha 2b4407f4...; its first return value re-derives the
        producer's own `sans_xl_sha256`, so the recomputation cannot silently drift from the subprocess;
      * the flags census gains exactly `_xc_leg_handles_on`, dark (False), named one by one.

    Pinned here, on the deck THIS item owns, so the K9-6 half of that repair travels with K9-6: reverting
    this item without reverting the g1x re-anchor reds this test, not a golden five hundred lines away."""
    import inspect
    import os
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    walk = (repo / "tests" / "unit" / "test_cascade_walk.py").read_text(encoding="utf-8")
    assert "_G1X_K96_CUT = (" in walk and "def _g1x_sans(" in walk
    assert "_sans_repro, _sans_head = _g1x_sans(producer)" in walk
    assert '_K96_ONE = ["_xc_leg_handles_on"]' in walk
    # the bank itself is UNTOUCHED: the HEAD sha the re-anchor lands on is the one D-XL banked
    bank = (repo / "data" / "consequence_leg" / "xl_golden_seam_off.json").read_text(encoding="utf-8")
    assert "2b4407f4b7701799036182180bcc09993f49a37f4593e84d86912865a686e074" in bank
    # ...and the producer is NOT edited by this lane -- the repair is a cut in the pin, not a new anchor
    prod = (repo / "data" / "consequence_leg" / "xl_golden_seam_bank.py").read_text(encoding="utf-8")
    assert "xc_leg_handles" not in prod and "_xlh_kw" not in prod

    # THE MEASUREMENT ITSELF, run here rather than only inside the 4-minute golden: the two shas the
    # g1x pin joins. This deck imports the helper from the walk deck by path, so it exercises the SAME
    # code the golden runs and needs no second clean-env subprocess.
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "_k96_walk_deck", str(repo / "tests" / "unit" / "test_cascade_walk.py"))
    _walk_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_walk_mod)
    _repro, _head = _walk_mod._g1x_sans(str(repo / "data" / "consequence_leg" / "xl_golden_seam_bank.py"))
    assert _head == "2b4407f4b7701799036182180bcc09993f49a37f4593e84d86912865a686e074", _head
    assert _repro != _head, "K9-6 is not in the seam block -- this pin has nothing to measure"
    assert os.environ.get("GRAPHRAG_XC_LEG_HANDLES") in (None, "", "off")  # and the flag stays dark
    from leviathan.graphrag import answer as an
    # RE-ANCHORED BY K9-4 (same sitting, same reason as the sibling pin above): K9-4's own spread now
    # sits between K9-6's and `**_eod_kw`, so the property asserted is the one that matters to the
    # producer -- K9-6's term is on the call line and `**_eod_kw` still closes it.
    _line = inspect.getsource(an._answer_l2)
    _line = _line[_line.index("**_xlh_kw"):]
    assert _line[:_line.index("\n")].endswith("**_eod_kw)"), _line[:_line.index("\n")]


# -- K9-6 FIX-PASS PINS (review 2026-09-07): one MAJOR closed as SCOPE, three MINORs closed as code ----
#
# THE OPEN DOCKET THIS ITEM SHIPS WITH, as data rather than as prose, so "K9-6 is 3 of 4" is a thing a
# test can read and not a sentence in a report no one re-reads. Each entry names the SEAM, WHY this lane
# could not close it, and the SYMBOL whose appearance means it HAS been closed -- which is what makes the
# tripwire below able to red in both directions.
K96_OPEN_DOCKET = (
    {"id": "design-fix-iv",
     "seam": "src/leviathan/graphrag/register.py",
     "symbol": "count_self_corrections",
     "shape": "the retraction COUNTER, on count_exec_words' / _SENT_ITER' shape",
     "blocked_by": "register.py is not on this lane's allowlist; relocating the counter to a seam the "
                   "design did not name would be a worse answer than reporting it unbuilt",
     "state": "ABSENT"},
    {"id": "g1x-insert-fold",
     "seam": "data/consequence_leg/xl_golden_seam_bank.py",
     "symbol": "XL_INSERTS",
     "shape": "fold K9-6's own line set into the producer's XL_INSERTS so sans_xl_sha256 joins to the "
              "bank standalone again, instead of only through test_cascade_walk._g1x_sans",
     "blocked_by": "the producer is not on this lane's allowlist; the repair was made in the PIN, which "
                   "is honest but leaves the producer emitting a sans that no longer reaches its bank",
     "state": "PRESENT"},
)


def test_k9_6_design_fix_iv_the_retraction_counter_is_unbuilt_and_docketed():
    """THE MAJOR, CLOSED AS SCOPE AND MACHINE-CHECKED -- because the only other two ways to close it are
    both worse than leaving it open honestly.

    Design section 6 FIX (iv) names `register.count_self_corrections(text)`, on the shape of
    `register.count_exec_words` / `register._SENT_ITER`. IT IS NOT BUILT. It is not built because
    register.py is not on this lane's allowlist, and because a counter relocated to a seam the design did
    not name is a different instrument wearing the same name. So K9-6 ships 3 OF 4 and THE ITEM STAYS
    OPEN; no K9-6 pin depends on (iv) -- the item's tier-1 settlement is three handles per leg line and
    the absence of the tokens 8.67531 and -0.0950733 -- which is exactly why the absence could otherwise
    be booked closed by accident.

    THE ADDRESS IS LIVE, NOT STALE -- asserted, because a docket naming a seam that no longer exists is
    worse than no docket: both `def count_exec_words` and `_SENT_ITER = re.compile(` are present in
    register.py at this HEAD, so (iv) is reachable work and not archaeology.

    THIS PIN REDS IN BOTH DIRECTIONS, which is the whole point:
      * someone BUILDS the counter and leaves cascade.py / answer.py still declaring it unbuilt -> red,
        with the message naming the two declarations and the docket entry to update;
      * someone DELETES one of those declarations while the counter is still absent -> red, so the scope
        of what actually shipped cannot be quietly widened by deleting the sentence that narrows it."""
    from pathlib import Path
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import register as rg
    from leviathan.graphrag.numbers import cascade as cq

    entry = [d for d in K96_OPEN_DOCKET if d["id"] == "design-fix-iv"][0]
    reg_src = Path(rg.__file__).read_text(encoding="utf-8")
    built = hasattr(rg, entry["symbol"]) or entry["symbol"] in reg_src
    assert not built, (
        "design fix (iv) has LANDED: register.count_self_corrections now exists. This pin is the "
        "tripwire that says so. Update, in ONE sitting: (1) the DELIBERATELY NOT COVERED bullet in "
        "cascade.py's K9-6 block note, (2) the _xc_leg_handles_on docstring paragraph in answer.py, "
        "(3) this deck's K96_OPEN_DOCKET entry 'design-fix-iv' -- and only then may K9-6 be booked 4 of 4.")
    # the seam the design names is LIVE, so the docket is actionable work rather than archaeology
    assert "def count_exec_words" in reg_src, "the design's named seam moved -- re-address the docket"
    assert "_SENT_ITER = re.compile(" in reg_src, "the design's named shape moved -- re-address the docket"
    # ...and the TWO source declarations that keep the item honestly open are both present
    csrc = Path(cq.__file__).read_text(encoding="utf-8")
    asrc = Path(an.__file__).read_text(encoding="utf-8")
    assert "K9-6 IS THEREFORE 3 OF 4 AND THE ITEM STAYS OPEN" in csrc, (
        "cascade.py's block note no longer declares (iv) unbuilt while it still is")
    assert "DESIGN FIX (iv) IS UNBUILT AND K9-6 IS 3 OF 4" in asrc, (
        "answer.py's flag docstring no longer declares (iv) unbuilt while it still is")
    assert entry["state"] == "ABSENT" and entry["blocked_by"]
    # this lane did not touch register.py: the remedy is a recorded SCOPE call, never a quiet edit
    assert "xc_leg_handles" not in reg_src and "K9-6" not in reg_src


def test_k9_6_the_round_four_floor_can_print_a_zero_magnitude_beside_a_directional_verb(monkeypatch):
    """THE MINOR THE FIX CREATES, PINNED RATHER THAN LEFT TO BE MET IN A PANEL.

    The co-move verb reads the RAW delta's sign (`_sign(A["d"])`) while the leg line now prints
    `_xc_signed(round(d, 4))`. Any |d| < 5e-05 therefore rounds away, and the panel reads '+0pp' or
    '-0pp' beside 'loosened' / 'tightened'. The band is REACHABLE, not hypothetical -- this deck already
    says so about -0.0 in test_k9_6_the_signed_delta_reproduces_... -- so it is measured here.

    WHAT IS PINNED, and it is the distinction that makes this a residual and not a defect:
      (1) THE SIGN NEVER DISAGREES. '%+g' prints '-0' for -0.0, and the co-move fork fires only when
          BOTH `_sign`s are non-zero, so a reader never sees a verb pointing the wrong way -- only a
          magnitude that rounds away beside a verb that is still correct.
      (2) THE LINE AND ITS ROW STILL AGREE, the invariant this whole item exists for: the row the [N]
          handle resolves to carries the SAME 0.0 / -0.0 the line prints.
      (3) HEAD IS NOT BETTER HERE. Flag off, the same fixture prints '+1e-05pp' -- a raw-float token no
          handle resolves to, the exact class K9-6 closes. The fix trades an unbacked token for a backed
          one that is small; it does not introduce the disagreement from a clean state.
    Reading `_sign` off the ROUNDED value instead would be strictly worse (it returns 0 for -0.0 and
    would call a genuinely tightening leg 'loosened' -- a vanished magnitude turned into an inverted
    verdict), which is why this ships as a fence and a pin rather than as a code change."""
    from leviathan.graphrag.numbers import cascade as cq

    # a co-move whose deltas are BELOW the round-4 grain on both legs, in both directions
    up = {("soybean_oil_cbot", 2008): 10.0, ("soybean_oil_cbot", 2009): 10.00001,
          ("rapeseed_oil_zce", 2008): 14.0, ("rapeseed_oil_zce", 2009): 14.00002}
    dn = {("soybean_oil_cbot", 2008): 10.0, ("soybean_oil_cbot", 2009): 9.99999,
          ("rapeseed_oil_zce", 2008): 14.0, ("rapeseed_oil_zce", 2009): 13.99998}
    for table, verb, tok, head_tok in ((up, "loosened", "+0pp", "+1e-05pp"),
                                       (dn, "tightened", "-0pp", "-1e-05pp")):
        on, on_calls, _f = _k96_render(
            monkeypatch, _k96_pair("canola_rapeoil_vegoil", *_K96_DEEP_PAIR), *_K96_DEEP_PAIR,
            _K96_DEEP_WINDOW, table, 33, comove=True, handles=True)
        off, off_calls, _g = _k96_render(
            monkeypatch, _k96_pair("canola_rapeoil_vegoil", *_K96_DEEP_PAIR), *_K96_DEEP_PAIR,
            _K96_DEEP_WINDOW, table, 33, comove=True, handles=False)
        assert verb in on[2] and verb in off[2]                 # the verb is the same off and on
        assert tok in on[0], (tok, on[0])                       # (1)+(2): the zero magnitude, flag ON
        assert head_tok in off[0], (head_tok, off[0])           # (3): HEAD's raw token, no handle backs it
        # (2) MEASURED: the row the delta's own handle resolves to carries exactly what the line printed
        assert cq._xc_signed(on_calls[2]["rows"][0]["value"]) == tok[:-2]
        assert on_calls[2]["rows"][0]["value"] == off_calls[2]["rows"][0]["value"]  # the ROW never moved
        # (1) MEASURED as a rule rather than as two literals: the printed sign matches the verb's sign
        assert tok.startswith("-") == (verb == "tightened")

    # THE BAND, stated exactly: round-4 is the grain, so 4.9e-05 vanishes and 6e-05 does not.
    assert round(4.9e-05, 4) == 0.0 and round(-4.9e-05, 4) == -0.0
    assert round(6e-05, 4) == 0.0001
    # ...and it is unreachable on every banked leg by three orders of magnitude: the smallest banked
    # |delta| is 0.0589pp, ~1,178x the floor.
    assert min(abs(v) for v in (0.0951, 0.0589, 1.4827, 1.2361, 1.3, 1.6)) / 5e-05 > 1000


def test_k9_6_the_seam_cut_span_is_measured_so_an_insertion_inside_it_cannot_escape():
    """THE MINOR THE G1X RE-ANCHOR LEAVES, CLOSED. `_G1X_K96_CUT` removes a line SET -- from K9-6's own
    leading comment through its own final assignment -- which is the producer's MINOR-6 discipline
    applied faithfully. But K9-6's line set is 14 lines of which 13 are comment, so a LATER insertion
    landing INSIDE that comment block would be cut away with it and escape the `sans` join in silence:
    the same hazard the producer's own MINOR-6 note was written to close, reopened one span over.

    CLOSED HERE, ON THE SPAN ITSELF: its sha, its line count, and the fact that it holds EXACTLY ONE
    statement. Any insertion inside it -- comment or code -- reds this pin, which is the whole ask. The
    honest end state is the DOCKETED one (fold K9-6's line set into the producer's own XL_INSERTS, so
    `sans_xl_sha256` reaches the bank standalone again); this pin is what makes the interim safe rather
    than merely declared."""
    import hashlib
    import importlib.util
    import inspect
    from pathlib import Path
    from leviathan.graphrag import answer as an

    repo = Path(__file__).resolve().parents[2]
    _spec = importlib.util.spec_from_file_location(
        "_k96_walk_deck_span", str(repo / "tests" / "unit" / "test_cascade_walk.py"))
    _walk = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_walk)
    start, stop = _walk._G1X_K96_CUT
    src = inspect.getsource(an._answer_l2)
    assert src.count(start) == 1 and src.count(stop) == 1
    a = src.rfind("\n", 0, src.index(start)) + 1
    b = src.find("\n", src.index(stop) + len(stop)) + 1
    span = src[a:b]
    # MEASURED 2026-09-07 on the shipped seam. If you edited K9-6's comment block DELIBERATELY, re-measure
    # these three constants AND re-run the g1x golden -- it must still land on 2b4407f4. If you did not,
    # something was inserted inside a span the seam measurement cuts away, which is what this pin is for.
    assert span.count("\n") == 14, span
    assert len(span) == 1353, len(span)
    assert hashlib.sha256(span.encode("utf-8")).hexdigest() == (
        "8c5add171cf85a3596a079d20856cf7d3a64256273eb22bf31f8f5f8285b2f3d"), span
    stmts = [ln.strip() for ln in span.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert stmts == [stop], stmts        # exactly one statement, and it is the cut's own stop anchor

    # THE DOCKET, so the interim does not become permanent by being forgotten: the producer still emits a
    # `sans_xl_sha256` that no longer joins to its own bank standalone, and the fold is owed.
    entry = [d for d in K96_OPEN_DOCKET if d["id"] == "g1x-insert-fold"][0]
    prod = (repo / "data" / "consequence_leg" / "xl_golden_seam_bank.py").read_text(encoding="utf-8")
    assert entry["symbol"] in prod and entry["state"] == "PRESENT"
    assert start not in prod, (
        "the K9-6 line set is now in the producer's XL_INSERTS: sans_xl_sha256 reaches the bank "
        "standalone again, so retire _G1X_K96_CUT from test_cascade_walk.py, drop this docket entry, "
        "and re-run the g1x golden to confirm it still lands on 2b4407f4")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K9-4 VINTAGE ROLE -- class (3) FORECAST AS SETTLED, flag GRAPHRAG_VINTAGE_ROLE
#
# THE MEASURED TRIGGER (design section 4), the judged panel's own STOP sentence, TREATMENT = max:
#   cascade_panel.json stops.treatment #10, id rv_beans_meal --
#   "The settled US soybean season-average farm price (a USDA survey actual, not a futures settle)
#    rose from $10.00/bu [N41] in MY2024/25 to $10.40/bu [N42] in MY2025/26."
#   -- STOP: "the MY2025/26 figure is a WASDE forecast at a vintage known 2026-08-12, inside a
#   marketing year that had not closed; labelling it a settled USDA survey actual is a retraction a
#   desk head would have to make." The panel flagged the SAME sentence twice; #14 names the seam --
#   "the parenthetical is an authority claim the row does not carry ... it is the one place A upgrades
#   a projection to a print."
#
# THE ITEM SHIPS 2 OF 3 AND SAYS SO IN CODE (K94_OPEN_DOCKET below): 3a in full (the price-leg label's
# three print sites + the [N] scope word + -- added by the fix pass, review MAJOR-1 -- the PERSONA's own
# SEAM-B paragraph, the assertion's FOURTH producer), 3b's `_SYSTEM_RECENCY` clause, and NOT 3b's
# `register.count_forecast_restatements` -- register.py is not on this lane's allowlist.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
FLAG_K94 = "GRAPHRAG_VINTAGE_ROLE"

# THE BANKED PANEL LINES, verbatim from cascade_pair_rv_beans_meal.md:400-401 (the `[N..]` handle and
# the trailing `[known ...]` stamp are added above `from_number` and are not part of the label):
#   [N41] USDA WASDE average farm price soybeans united_states MY2024/25 = 10 $/bu  [known 2026-08-12]
#   [N42] USDA WASDE average farm price soybeans united_states MY2025/26 = 10.4 $/bu [known 2026-08-12]
_K94_BANKED = {
    "N41": "USDA WASDE average farm price soybeans united_states MY2024/25 = 10 $/bu",
    "N42": "USDA WASDE average farm price soybeans united_states MY2025/26 = 10.4 $/bu",
}

# THE BANKED CENSUS this item is measured against, frozen from cascade_baseline_control.json and
# cascade_baseline_treatment.json (`per_answer[].served_rows`, the eval's bounded projection, whose
# role key is `estimate_role` because `eval._alias_col` reads BOTH names). Reproduced this sitting:
#   72 silver_wasde rows -- 10 actual (every one period 2024/25), 22 estimate (2025/26),
#   32 projection (2026/27), 8 with NO role, every one of the 8 an `avg_farm_price` row MINTED by the
#   price leg (period None, because the period lives on the synthetic query and not on the row).
# ONE FIGURE OF THE DESIGN'S DOES NOT REPRODUCE AND THE CORRECTED ONE IS PINNED BELOW: section 4's
# GREEN pin says "price_leg_fired is False on 10 of the 12 banked answers". Measured: `price_leg_fired`
# is TRUE on FOUR -- deep rv_corn_wheat, max rv_corn_wheat, max rv_beans_meal, max rv_beans_oil -- so
# it is False on EIGHT. The pin's SHAPE is unaffected (a non-firing turn is untouched, and 8 of 12 is
# still the majority), but the number is stated correctly here rather than copied.
_K94_BANKED_ROLE_CENSUS = {"actual": 10, "estimate": 22, "projection": 32, None: 8}
_K94_BANKED_PRICE_LEG_FIRED = ("deep:rv_corn_wheat", "max:rv_corn_wheat",
                               "max:rv_beans_meal", "max:rv_beans_oil")

# THE SCOPE HALF'S REACH, ADDED BY THE FIX PASS (review MINOR-2) AND MEASURED, NOT INFERRED. The green
# pin below used to open "every non-price-leg turn is untouched" and then check only the FOCUS half; the
# `from_number` half of the same flag touches ANY turn that reads a role-bearing silver_wasde row,
# whether or not the price leg fired. Reproduced this sitting over the same two banked baselines
# (`per_answer[].served_rows`): 64 silver_wasde CALLS carrying 72 rows, of which 52 calls have a
# HEADLINE row (the row `from_number` labels) that declares a role. Per answer, role-bearing rows:
_K94_BANKED_SCOPE_REACH = {"deep:rv_beans_meal": 28, "deep:rv_beans_oil": 10, "deep:rv_corn_wheat": 8,
                           "max:rv_beans_oil": 12, "max:rv_corn_wheat": 6}
# ...5 of the 12 answers, and TWO of those five -- deep rv_beans_meal and deep rv_beans_oil -- have
# `price_leg_fired` False. So "untouched" is true of the PRICE LEG on a non-price turn and FALSE of the
# scope word, which is the qualification this constant exists to force into the pin.
_K94_BANKED_SCOPE_REACH_NO_PRICE_LEG = ("deep:rv_beans_meal", "deep:rv_beans_oil")

# HEAD's price-leg render, frozen. Produced by the fixture below against HEAD's producer before a byte
# of the fix ran; the flag-off path must reproduce all three sites exactly.
_K94_TAG = " [series: soybeans; country: united_states; table: USDA WASDE]"
_K94_HEAD = {
    "N41": ("- [N41] US soybeans USDA season-average farm price, marketing-year "
            "(survey actual; not a futures settle) MY2024/25: $10.00/bu" + _K94_TAG),
    "N42": ("- [N42] US soybeans USDA season-average farm price, marketing-year "
            "(survey actual; not a futures settle) MY2025/26: $10.40/bu" + _K94_TAG),
    "response": ("PRICE-RESPONSE on avg_farm_price: US soybeans USDA season-average farm price, "
                 "marketing-year (survey actual; not a futures settle) rose from $10.00/bu [N41] "
                 "(MY2024/25) to $10.40/bu [N42] (MY2025/26) -- the settled USDA season-average farm "
                 "price (survey-based, revision_stamp actual at the session as-of; NOT a futures "
                 "settle, NOT a forecast); render under '## The record', the level is the [N] row and "
                 "the direction is prose."),
}


def _k94_node(contract="soybeans_cbot", dates=("2025-06-15", "2026-08-01")):
    from types import SimpleNamespace
    evd = [{"date": d, "source": "s", "source_key": f"k{i}", "text": "t"} for i, d in enumerate(dates)]
    return SimpleNamespace(contract=contract, id="price", prior={"silver_ref": "price", "region": "US"},
                           evidence=list(evd))


def _k94_qfn(values):
    """qfn(sql)->rows keyed by the marketing_year literal in the compiled SQL -- test_price_leg.py's own
    harness, plus the ONE column this item turns on. `revision_stamp` is what `numbers/query._extras`
    aliases `estimate_role` to, so a stub row carrying it is the shape a live fetch returns; a value of
    None emits NO key at all, which is the role-less row the fail-closed branch exists for."""
    import re

    def qfn(sql):
        m = re.search(r"marketing_year = '([^']*)'", sql)
        my = m.group(1) if m else None
        if my not in values:
            return []
        value, role = values[my]
        row = {"value": str(value)}
        if role is not None:
            row["revision_stamp"] = role
        return [row]
    return qfn


def _k94_pair(role_a, role_b, *, vintage_role, p_a="10.00", p_b="10.40", focus="soybeans_cbot"):
    """Drive the ONE producer end to end at `base=40`, so the handles read [N41]/[N42] -- the banked
    numbering of the STOP sentence this item is pinned on. Returns (lines, calls, fired)."""
    from types import SimpleNamespace
    from leviathan.graphrag.numbers import cascade as cq
    sg = SimpleNamespace(nodes=[_k94_node(focus)], trace={}, fired_regimes=[])
    calls: list = []
    kw = {"vintage_role": True} if vintage_role else {}
    lines, fired = cq._price_pair({"focus_contract": focus}, sg, None, [],
                                  _k94_qfn({"2024/25": (p_a, role_a), "2025/26": (p_b, role_b)}),
                                  "2026-09-06", "2025", calls, 40, **kw)
    return lines, calls, fired


def _k94_wasde_call(period="MY2025/26", role="estimate", value=10.4):
    """The agent-lane shape of the same read: a silver_wasde row that DECLARES its revision role under
    the `revision_stamp` alias, which is what every one of the 64 role-bearing banked WASDE rows is."""
    row = {"value": value, "unit": "$/bu", "knowledge_date": "2026-08-12"}
    if role is not None:
        row["revision_stamp"] = role
    return {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "soybeans",
                      "country": "united_states", "period": period, "asof": "2026-09-06"},
            "rows": [row], "status": "ok"}


def test_k9_4_flag_off_is_byte_identical_to_the_banked_panel(monkeypatch):
    """THE OFF PIN, and it is the rollback proof, across every surface this item touches: the two
    price-leg level lines, the PRICE-RESPONSE tail, the synthetic rows (the role key is ABSENT, not
    null), the [N] citation label, and the persona string. Flipping GRAPHRAG_VINTAGE_ROLE off returns
    every one of them to HEAD exactly."""
    from leviathan.graphrag import answer as an
    monkeypatch.delenv(FLAG_K94, raising=False)

    lines, calls, fired = _k94_pair("actual", "estimate", vintage_role=False)
    assert lines[0] == _K94_HEAD["N41"]
    assert lines[1] == _K94_HEAD["N42"]
    assert lines[2] == _K94_HEAD["response"]
    # the STOP sentence's own phrase IS in HEAD's panel -- which is why the writer could copy it
    assert "survey actual" in lines[0] and "NOT a forecast" in lines[2]
    # OMIT-WHEN-OFF ON THE ROW: absent, not null. A `revision_stamp: None` would be a new key every
    # downstream reader can see, which is not byte-identity.
    assert [c["rows"][0] for c in calls] == [{"value": 10.0, "unit": "$/bu"},
                                             {"value": 10.4, "unit": "$/bu"}]
    assert fired["price_leg"] is True and fired["p_lo"] == 10.0 and fired["p_hi"] == 10.4

    # the reader's `## Sources` label, against the bytes banked in cascade_pair_rv_beans_meal.md
    assert cit.from_number(_k94_wasde_call("MY2024/25", "actual", 10.0), 41).label == _K94_BANKED["N41"]
    assert cit.from_number(_k94_wasde_call("MY2025/26", "estimate", 10.4), 42).label == _K94_BANKED["N42"]
    # ...and the persona, whose 3b clause must not ship off-flag
    assert an._SYSTEM_RECENCY_MOOD not in an._system(recency=True)


def test_k9_4_red_max_beans_meal_the_settled_survey_actual_claim_cannot_be_rendered(monkeypatch):
    """RED (MAX), design section 4: TREATMENT STOP #10/#14, id rv_beans_meal. The writer's sentence
    called a MY2025/26 WASDE figure "a USDA survey actual" -- and it did so because the panel handed it
    that phrase three times over, on both level lines and again inside the PRICE-RESPONSE directive.

    After the fix, with the MY2025/26 endpoint carrying the role its row declares, the phrase "survey
    actual" does not occur ANYWHERE in the rendered block and neither does "NOT a forecast" -- so the
    STOP sentence has no source in the panel to copy. The design says which branch fires IS the
    measurement; this pin measures the branch, not a prediction about USDA's calendar."""
    monkeypatch.setenv(FLAG_K94, "on")
    lines, _calls, _fired = _k94_pair("actual", "estimate", vintage_role=True)
    body = "\n".join(lines)
    assert "survey actual" not in body
    assert "NOT a forecast" not in body
    assert "the settled USDA season-average farm price" not in body
    # ...and what stands in its place names the role the row carries, on every line
    assert body.count("an in-year USDA estimate at this as-of, not a settled survey figure") == 3
    assert "revision_stamp estimate" in lines[2]
    # THE MAGNITUDES AND HANDLES DO NOT MOVE -- this item removes an ASSERTION, never a figure
    assert "$10.00/bu [N41]" in lines[2] and "$10.40/bu [N42]" in lines[2] and "rose from" in lines[2]
    assert lines[0].endswith("MY2024/25: $10.00/bu" + _K94_TAG)
    assert lines[1].endswith("MY2025/26: $10.40/bu" + _K94_TAG)


def test_k9_4_red_max_beans_meal_the_handle_itself_states_the_role_the_row_carries(monkeypatch):
    """RED (MAX), the READER-facing half of the same sentence. STOP #14's charge is precise: "the cited
    row says only 'USDA WASDE average farm price soybeans united_states MY2025/26 = 10.4 $/bu [known
    2026-08-12]'" -- the label carried the marketing year and stopped, so nothing in `## Sources`
    contradicted the prose's "survey actual". With the flag on it does."""
    monkeypatch.setenv(FLAG_K94, "on")
    c41 = cit.from_number(_k94_wasde_call("MY2024/25", "actual", 10.0), 41)
    c42 = cit.from_number(_k94_wasde_call("MY2025/26", "estimate", 10.4), 42)
    assert c41.label == ("USDA WASDE average farm price soybeans united_states MY2024/25 USDA actual "
                         "= 10 $/bu")
    assert c42.label == ("USDA WASDE average farm price soybeans united_states MY2025/26 USDA estimate "
                         "= 10.4 $/bu")
    # THE ROLE RIDES THE SCOPE AND NOTHING ELSE MOVES: value, unit, date, locator and payload are the
    # bytes HEAD emits, so `answer._number_handle_value`, the drill-down and `verify._row_vals` are
    # untouched and no correct sentence can gain a `number_mismatch`.
    for c, banked in ((c41, _K94_BANKED["N41"]), (c42, _K94_BANKED["N42"])):
        assert c.label.replace(" USDA actual", "").replace(" USDA estimate", "") == banked
    assert (c42.value, c42.unit, c42.date) == ("10.4", "$/bu", "2026-08-12")
    assert c42.payload["rows"][0]["value"] == 10.4 and c42.locator["period"] == "MY2025/26"


def test_k9_4_the_one_producer_answers_for_all_three_print_sites(monkeypatch):
    """DESIGN MAJOR-3, MACHINE-CHECKED: "Fixing only the PRICE-RESPONSE literal leaves '(survey actual;
    not a futures settle)' in the prompt twice." One producer (`_price_role_terms`) feeds the `label`
    that both level lines print AND the tail that restates it, so the three sites cannot drift.

    Asserted structurally rather than by string search: the parenthetical appears exactly three times
    (twice as a level-line label, once inside the PRICE-RESPONSE restatement of that same label), and
    the tail exactly once -- on every branch, including the two the design's own text did not spell
    out (a mixed pair and a role-less endpoint)."""
    from leviathan.graphrag.numbers import cascade as cq
    monkeypatch.setenv(FLAG_K94, "on")
    for role_a, role_b in (("actual", "actual"), ("actual", "estimate"), ("projection", "projection"),
                           ("estimate", "projection"), (None, "estimate"), ("actual", None)):
        paren, tail = cq._price_role_terms(cq._row_role({"revision_stamp": role_a}),
                                           cq._row_role({"revision_stamp": role_b}))
        lines, _calls, _fired = _k94_pair(role_a, role_b, vintage_role=True)
        body = "\n".join(lines)
        assert body.count(f"marketing-year ({paren})") == 3, (role_a, role_b, body)
        assert body.count(tail) == 1, (role_a, role_b, body)
        # every branch keeps A3's futures-settle disclaimer -- the stated departure from the design's
        # branch text, and the whole reason it was made
        assert body.count("not a futures settle") == 3 and "NOT a futures settle" in lines[2]


def test_k9_4_fails_closed_when_an_endpoint_publishes_no_role(monkeypatch):
    """DESIGN MINOR-6, and the branch that makes the fix correct without a measurement this sitting
    cannot make. The role of the price leg's upstream `src_row` is in NO artifact of the judged sitting
    -- all 8 banked price-leg rows are the leg's OWN output, already role-less -- so v1's premise ("the
    MY2025/26 grain is `estimate`") was an inference. A role-less row therefore makes the line SAY the
    role is not published, and the "survey actual" and "NOT a forecast" claims still cannot render.

    A row whose stamp is outside the estate's three-word vocabulary takes the SAME branch: it is a
    stamp, not a role, and this seam does not invent a synonym for one."""
    monkeypatch.setenv(FLAG_K94, "on")
    for role_a, role_b in ((None, None), ("actual", None), (None, "actual"),
                           ("2026M08", "actual"), ("actual", "proj."), ("Actual", None)):
        lines, calls, _fired = _k94_pair(role_a, role_b, vintage_role=True)
        body = "\n".join(lines)
        assert body.count("the revision role is not published on this read") == 3, (role_a, role_b)
        assert body.count("revision_stamp not published on this read") == 1, (role_a, role_b)
        assert "survey actual" not in body and "NOT a forecast" not in body
        # the ROW still carries only what the vocabulary admits -- this seam renders, it does not edit
        for want, c in ((role_a, calls[0]), (role_b, calls[1])):
            expected = want.strip().lower() if isinstance(want, str) else None
            expected = expected if expected in ("actual", "estimate", "projection") else None
            assert c["rows"][0].get("revision_stamp") == expected


def test_k9_4_the_least_settled_endpoint_governs_and_can_only_under_claim(monkeypatch):
    """THE PAIR RULE, PINNED IN ITS ONE-SIDED DIRECTION. One `label` prints on two rows, so it cannot
    state two roles; the design's "when EITHER reads estimate or projection" is applied to the LEAST
    settled of the pair. The consequence is stated rather than discovered: on a mixed pair the SETTLED
    endpoint's line carries the pair's provisional wording, which UNDER-claims that row's finality --
    a missed warning, never a false one, and the opposite direction from the judged defect.

    THE PER-ROW TRUTH IS NOT LOST, which is what makes the trade acceptable: the other half of this
    same flag prints each row's OWN role in its own citation scope, checked here on the same pair."""
    monkeypatch.setenv(FLAG_K94, "on")
    for role_a, role_b, weak in (("actual", "estimate", "estimate"),
                                 ("estimate", "actual", "estimate"),
                                 ("actual", "projection", "projection"),
                                 ("projection", "estimate", "projection"),
                                 ("estimate", "estimate", "estimate")):
        lines, calls, _fired = _k94_pair(role_a, role_b, vintage_role=True)
        assert f"an in-year USDA {weak} at this as-of" in lines[0]
        assert f"revision_stamp {weak};" in lines[2]
        # the pair line under-claims; each handle carries its own row's fact
        assert cit.from_number(calls[0], 41).label.endswith(f"MY2024/25 USDA {role_a} = 10 $/bu")
        assert cit.from_number(calls[1], 42).label.endswith(f"MY2025/26 USDA {role_b} = 10.4 $/bu")


def test_k9_4_green_a_pair_whose_endpoints_both_read_actual_prints_heads_three_sites(monkeypatch):
    """GREEN, design section 4: "a price-leg turn whose endpoints both read `actual` is byte-identical
    at all three sites". Measured, and stated at exactly the strength it holds: the three PRINT SITES
    are byte-identical to HEAD, including the "NOT a forecast" clause the design emits only here. The
    synthetic ROWS gain the role key and the [N] labels gain the role word -- that is the other half of
    the same flag telling the truth about the row, not a print site moving."""
    monkeypatch.setenv(FLAG_K94, "on")
    lines, calls, fired = _k94_pair("actual", "actual", vintage_role=True)
    assert lines[0] == _K94_HEAD["N41"]
    assert lines[1] == _K94_HEAD["N42"]
    assert lines[2] == _K94_HEAD["response"]
    assert "NOT a forecast" in lines[2]
    assert fired == _k94_pair("actual", "actual", vintage_role=False)[2]
    assert [c["rows"][0]["revision_stamp"] for c in calls] == ["actual", "actual"]
    assert cit.from_number(calls[1], 42).label.endswith("MY2025/26 USDA actual = 10.4 $/bu")


def test_k9_4_green_a_non_farm_focus_and_a_falling_pair_are_untouched_at_both_settings(monkeypatch):
    """GREEN, the OTHER half of the design's own pin -- "every non-price-leg turn is untouched" -- AND
    THE QUALIFICATION THE FIX PASS ADDED TO IT (review MINOR-2), because the unqualified sentence is
    false of half this flag.

    THE PRICE LEG: a turn whose leg declines renders NOTHING at either flag setting, and a firing
    pair's DIRECTION word is prose the role never reaches. The design says price_leg_fired is False on
    10 of 12 banked answers; MEASURED it is False on EIGHT (the census constant above names the four
    that fired), which changes the count and not the pin.

    THE SCOPE WORD IS NOT SO CONFINED, and saying so is the point of the second half of this test.
    `from_number` touches any turn that reads a role-bearing silver_wasde row, price leg or no price
    leg: MEASURED, 5 of the 12 banked answers, TWO of them with `price_leg_fired` False. So the pin
    now checks the reach it actually has -- a role-bearing WASDE read moves with the flag while the
    price leg is nowhere in the picture, and a role-LESS read still does not."""
    monkeypatch.setenv(FLAG_K94, "on")
    for vr in (False, True):
        # `soybean_meal_decatur` is a market price, not a US farm-gate slug -> `_farm_wasde` is None
        assert _k94_pair("estimate", "estimate", vintage_role=vr,
                         focus="soybean_meal_decatur") == ([], [], None)
    off = _k94_pair("actual", "estimate", vintage_role=False, p_a="10.40", p_b="10.00")[0]
    on = _k94_pair("actual", "estimate", vintage_role=True, p_a="10.40", p_b="10.00")[0]
    assert all("fell from" in "\n".join(x) for x in (off, on))
    assert len(_K94_BANKED_PRICE_LEG_FIRED) == 4 and _K94_BANKED_ROLE_CENSUS[None] == 8
    # THE SCOPE HALF'S OWN REACH, on a read that has no price leg anywhere near it: an `ending_stocks`
    # WASDE row declaring a role gains the word, a role-less one does not, and neither call goes
    # through `_price_pair` at all. This is the shape of the two banked answers named below.
    stocks = {"query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
                        "country": "united_states", "period": "MY2025/26", "asof": "2026-09-06"},
              "rows": [{"value": 325.0, "unit": "Million Bushels", "revision_stamp": "estimate"}],
              "status": "ok"}
    roleless = {**stocks, "rows": [{"value": 325.0, "unit": "Million Bushels"}]}
    monkeypatch.delenv(FLAG_K94, raising=False)
    off_lbls = (cit.from_number(stocks, 9).label, cit.from_number(roleless, 9).label)
    monkeypatch.setenv(FLAG_K94, "on")
    on_lbls = (cit.from_number(stocks, 9).label, cit.from_number(roleless, 9).label)
    assert on_lbls[0] == off_lbls[0].replace("MY2025/26 ", "MY2025/26 USDA estimate ") != off_lbls[0]
    assert on_lbls[1] == off_lbls[1]          # role-less: byte-identical, the anti-vacuity half
    # ...and the banked census the qualification rests on, stated as data rather than as prose
    assert len(_K94_BANKED_SCOPE_REACH) == 5, _K94_BANKED_SCOPE_REACH
    assert sum(_K94_BANKED_SCOPE_REACH.values()) == 64 == (
        _K94_BANKED_ROLE_CENSUS["actual"] + _K94_BANKED_ROLE_CENSUS["estimate"]
        + _K94_BANKED_ROLE_CENSUS["projection"])
    # the two whose scope moves while their PRICE LEG never fired -- the half the old pin implied away
    assert set(_K94_BANKED_SCOPE_REACH_NO_PRICE_LEG) <= set(_K94_BANKED_SCOPE_REACH)
    assert not (set(_K94_BANKED_SCOPE_REACH_NO_PRICE_LEG) & set(_K94_BANKED_PRICE_LEG_FIRED))


def test_k9_4_the_scope_roster_is_closed_and_a_release_stamp_never_stands_in_for_a_role(monkeypatch):
    """THE FENCE, and the design's own FATAL-3 lesson applied before it could be re-learned.
    `revision_stamp` is DP-2's GENERIC provenance alias, not a role column: MEASURED on the live
    registry, 9 cards declare a `provenance_col` and EIGHT of them are not silver_wasde, routing six
    other columns through the same alias (`latest_release_ym`, `release_date`, `vintage_status`,
    `source_position_date`, `crush_rule_version`, `spread_rule_version`). A `_print_kind`-style
    fallback to the raw token would print a release stamp where a role belongs, so the mapping has
    NONE -- and the census is reproduced here rather than quoted."""
    from leviathan.graphrag.numbers import registry as _reg
    _prov = sorted((t, s.provenance_col) for t, s in _reg.load_registry().tables.items()
                   if getattr(s, "provenance_col", None))
    assert len(_prov) == 9 and ("silver_wasde", "estimate_role") in _prov
    assert sorted({c for t, c in _prov if t != "silver_wasde"}) == [
        "crush_rule_version", "latest_release_ym", "release_date", "source_position_date",
        "spread_rule_version", "vintage_status"]
    monkeypatch.setenv(FLAG_K94, "on")
    for stamp in ("2026M08", "2026-08-12", "prel.", "proj.", "crush_rule_v3", "spread_rule_v2",
                  "", "   ", None, "estimated", "projections", "actuals"):
        assert cit.from_number(_k94_wasde_call("MY2025/26", stamp, 10.4), 42).label == \
            _K94_BANKED["N42"], stamp
    # ...and the three that DO render, case-folded because the roster is a silver vocabulary
    for stamp, word in (("actual", "USDA actual"), ("ESTIMATE", "USDA estimate"),
                        (" Projection ", "USDA projection")):
        assert f"MY2025/26 {word} = " in cit.from_number(_k94_wasde_call("MY2025/26", stamp), 42).label


def test_k9_4_the_roster_is_the_estates_own_on_both_of_its_sources_of_truth():
    """THE ROSTER CANNOT DRIFT, because it is joined to the two places the estate already declares it:
    the silver transform that MINTS the column (`usda_wasde_silver.ESTIMATE_ROLES`, whose own comment
    reads "NO invented roles") and the numbers card that RANKS on it (silver_wasde's `vintage_tiebreak`
    role_order, tables.yaml:383). If a fourth role is ever minted, this reds rather than the label
    silently rendering nothing for it.

    The transform is imported HERE rather than in citations.py deliberately: a serving-path import of a
    bronze-to-silver module to read three strings would buy a heavyweight dependency for a fence a test
    can hold."""
    from leviathan.graphrag.numbers import registry as _reg
    from leviathan.graphrag.numbers import cascade as cq
    from leviathan.transforms.bronze_to_silver import usda_wasde_silver as _uw
    assert set(cit._ROLE_WORDS) == set(_uw.ESTIMATE_ROLES) == {"actual", "estimate", "projection"}
    spec = _reg.load_registry().tables["silver_wasde"]
    assert spec.provenance_col == "estimate_role"          # the column `_extras` aliases to the row key
    tb0 = spec.vintage_tiebreak[0]
    assert tb0.col == "estimate_role"
    assert set(tb0.role_order) == set(cit._ROLE_WORDS)
    # the ORDER the cascade branches on is the card's own ranking, least provisional first
    assert list(cq._ROLE_ORDER) == list(tb0.role_order) == ["actual", "estimate", "projection"]
    # every rendered phrase names the PUBLISHER, the `_SETTLE_KIND_WORDS` discipline
    assert all(v == "USDA " + k for k, v in cit._ROLE_WORDS.items())


def test_k9_4_green_every_role_less_read_in_the_estate_is_byte_identical(monkeypatch):
    """GREEN, THE WIDEST FORM: this item adds a scope WORD, and a row that declares no role adds none.
    Checked across the shapes this deck already holds -- the census-A unscoped multi-geo read K9-2
    withholds, a scoped one-row read, an empty read, and a WASDE read whose row carries no stamp -- at
    both settings of the flag, and with K9-2's own flag both off and on so the two items' labels are
    shown not to interact."""
    calls = {
        "census_a": _unscoped_multigeo("production_mt", "canola", 40, "22500000.0"),
        "scoped": {"query": {"table": "silver_psd", "metric": "su_ratio", "commodity": "canola",
                             "country": "Canada", "period": "MY2026", "asof": "2026-09-06"},
                   "rows": [{"value": "16.8472", "unit": "%", "country": "Canada"}], "status": "ok"},
        "empty": {"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption",
                            "commodity": "wheat", "country": "united_states", "period": "MY2026",
                            "asof": "2026-09-06"}, "rows": [], "status": "ok"},
        "wasde_roleless": _k94_wasde_call("MY2025/26", None, 10.4),
    }
    for k92 in ("off", "on"):
        monkeypatch.setenv("GRAPHRAG_SCOPE_WITHHOLD", k92)
        monkeypatch.delenv(FLAG_K94, raising=False)
        base = {name: cit.from_number(c, 7).label for name, c in calls.items()}
        monkeypatch.setenv(FLAG_K94, "on")
        assert {name: cit.from_number(c, 7).label for name, c in calls.items()} == base, k92


def test_k9_4_composes_with_k9_3_because_the_harmoniser_copies_the_row(monkeypatch):
    """THE CROSS-ITEM CELL, MEASURED RATHER THAN ASSUMED. K9-3's `_harmonised_call` rewrites ROWS
    before the list is published and K9-4 READS a row key at render time, so a harmoniser that rebuilt
    rows from scratch would silently drop the role on every rescaled call and this item would go dark
    on exactly the cards K9-3 lights. It does not: the rescale is copy-on-write (`nr = dict(r)`), so
    every key the row carried survives.

    THE TWO LIVE REACHES ARE DISJOINT TODAY, and that is the reason this pin exists rather than the
    reason it does not. MEASURED on the live estate: 16 (table, metric) keys carry `scale != 1`,
    across four tables -- silver_psd, silver_psd_attributes, silver_mpob, silver_production_livestock
    -- and NOT ONE of the four declares a `provenance_col`, while silver_wasde (the only card that
    does declare one for this vocabulary) is absent from cascade_map entirely. So no banked call is in
    both classes. This pin is the guard for the day a rostered card gains a provenance_col, and it
    fails the moment the harmoniser stops copying."""
    monkeypatch.setenv(FLAG_K94, "on")
    monkeypatch.setenv("GRAPHRAG_NARRATE_SCALE", "on")
    call = {"query": {"table": "silver_psd", "metric": "consumption_mt", "commodity": "soybeans",
                      "country": "United States", "period": "MY2025", "asof": "2026-09-06"},
            "rows": [{"value": "39599000.0", "unit": None, "country": "United States",
                      "revision_stamp": "estimate"}], "status": "ok"}
    out = cit.harmonise_declared_scale([call])[0]
    assert out is not call                                  # the rescale DID fire on this key
    assert out["rows"][0]["unit"] == "MMT" and round(out["rows"][0]["value"], 4) == 39.599
    assert out["rows"][0]["revision_stamp"] == "estimate"   # ...and the role rode through the copy
    assert cit.from_number(out, 27).label.endswith("MY2025 USDA estimate = 39.599 MMT")
    # the live reaches are disjoint: no cascade_map-scaled table declares a provenance_col
    from leviathan.graphrag.numbers import registry as _reg
    from leviathan.graphrag.numbers.cascade import load_map
    _R = _reg.load_registry()
    _scaled = {r["table"] for r in (load_map() or {}).values()
               if isinstance(r, dict) and r.get("table") and float(r.get("scale", 1) or 1) != 1}
    assert _scaled and "silver_wasde" not in _scaled
    assert all(getattr(_R.tables[t], "provenance_col", None) is None for t in _scaled if t in _R.tables)


def test_k9_4_the_letter_suffixed_extras_path_still_renders_the_raw_stamp(monkeypatch):
    """THE DECLARED DUPLICATION, PINNED RATHER THAN PAPERED OVER. `_mint_row_citations` already appends
    the RAW `revision_stamp` as a parenthetical tag on letter-suffixed extras, and
    `extra_number_citations`' docstring states the reason it is rendered ONLY there ("putting it on the
    headline would rewrite every existing footer in the estate") -- which is exactly why THIS change is
    dark behind a flag rather than unconditional.

    With the flag ON a WASDE row cited both ways carries its role twice, once in each dialect: the
    roster word inside the headline's scope, the raw column value in the extra's tag. That is a
    duplication, not a contradiction, and the extras path itself is byte-identical at both settings."""
    call = {"query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
                      "country": "united_states", "period": "MY2026/27", "asof": "2026-09-06"},
            "rows": [{"value": 325.0, "unit": "Million Bushels", "period": "2026/27",
                      "revision_stamp": "projection", "knowledge_date": "2026-08-12"},
                     {"value": 398.0, "unit": "Million Bushels", "period": "2025/26",
                      "revision_stamp": "estimate", "knowledge_date": "2026-08-12"}],
            "status": "ok"}
    monkeypatch.delenv(FLAG_K94, raising=False)
    off_extras = [c.label for c in cit.extra_number_citations(call, 5, [398.0])]
    off_head = cit.from_number(call, 5).label
    monkeypatch.setenv(FLAG_K94, "on")
    on_extras = [c.label for c in cit.extra_number_citations(call, 5, [398.0])]
    on_head = cit.from_number(call, 5).label
    assert off_extras == on_extras and off_extras and "(estimate)" in off_extras[0]
    assert on_head == off_head.replace("MY2026/27 ", "MY2026/27 USDA projection ")
    assert "USDA projection" not in off_head


def test_k9_4_3b_the_receipt_mood_clause_rides_the_recency_literal_only(monkeypatch):
    """DESIGN 3b's BUILT HALF, and design MAJOR-4's whole point. The J6 clause goes on `_SYSTEM_RECENCY`
    -- the DATING AND TENSE discipline, already a rule in the writer's voice and MEASURED shipping on
    both banked arms (GRAPHRAG_RECENCY_STAMP=on in both override files) -- and NOT on
    `_SYSTEM_PROVENANCE`, which is appended only under `if provenance:` with `provenance_prompt=True`
    set on exactly one preset, so the clause would have been inert on all 12 banked turns.

    THE MEASURED TRIGGER is TREATMENT STOP #4, id rv_soyoil_palm: "the evidence records that Indonesian
    palm exports rose in 2022/23 ... [E35] (STOP: [35] is WASDE 2022-05-12 saying exports 'are expected
    to increase for Indonesia in 2022/23' -- a forecast restated as a realized outturn)".

    J6 SHAPE: it says what to WRITE and names no forbidden phrase, so it cannot be satisfied by
    omission -- the failure mode of a prohibition, which buys a shorter answer and calls it a fix.

    THE FIX PASS ADDED THE SECOND PERSONA SURFACE THIS FLAG MOVES (review MAJOR-1): the SEAM-B
    paragraph substitution. So the equalities below are stated against `_system` WITH that
    substitution applied, which is what keeps this pin about 3b's clause and not about the other
    half -- and what makes it red if the mood clause ever starts riding something else."""
    from leviathan.graphrag import answer as an
    monkeypatch.delenv(FLAG_K94, raising=False)
    off_on, off_off = an._system(recency=True), an._system(recency=False)
    monkeypatch.setenv(FLAG_K94, "on")
    on_on, on_off = an._system(recency=True), an._system(recency=False)

    def _vr(text):        # the OTHER half of the same flag, applied so this pin isolates 3b's clause
        return text.replace(an._SYSTEM_CASCADE_PRICE_RESPONSE, an._SYSTEM_CASCADE_PRICE_RESPONSE_VR)

    assert on_on == _vr(off_on) + an._SYSTEM_RECENCY_MOOD     # appended, nothing else moved
    assert on_off == _vr(off_off)                             # no recency leg -> no clause, either way
    assert an._SYSTEM_RECENCY_MOOD not in off_on
    assert _vr(off_on) != off_on                              # the substitution really fired
    # it CONTINUES the recency paragraph rather than opening a fourth directive
    assert an._SYSTEM_RECENCY_MOOD.startswith(" When a receipt states")
    assert "\n" not in an._SYSTEM_RECENCY_MOOD
    assert on_on.index(an._SYSTEM_RECENCY) + len(an._SYSTEM_RECENCY) == on_on.index(
        an._SYSTEM_RECENCY_MOOD)
    # POSITIVE, NOT PROHIBITIVE: no "never" / "do not" / "avoid", and it names a thing to write
    low = an._SYSTEM_RECENCY_MOOD.lower()
    assert "never" not in low and "do not" not in low and "avoid" not in low
    assert "write your sentence in the mood the receipt uses" in low
    assert "name its report date" in low
    # ...and it did NOT land on the literal design MAJOR-4 measured as inert on both arms
    assert an._SYSTEM_RECENCY_MOOD not in an._SYSTEM_PROVENANCE


# -- THE FOURTH PRODUCER (fix pass, review MAJOR-1). The four pins below are the ones that were ---------
# -- missing when the build claimed "ONE PRODUCER AND THREE PRINT SITES": the persona's own SEAM-B ------
# -- paragraph is a fourth, it is not gated by anything this item minted, and at HEAD it hands the ------
# -- writer both words the judged STOP sentence used. The FOURTH pin is the second fix pass's (verify ---
# -- MAJOR): deleting the finality assertion is not enough while a ROLE-WORD directive still stands one -
# -- sentence later, so the flag-on paragraph must state the role rule exactly ONCE. --------------------
_K94_PERSONA_HEAD_ASSERTIONS = ("the settled US season-average FARM price",
                                "This is a survey-based USDA season-average actual (revision_stamp)")

# Every instruction of the paragraph that is NOT about the figure's revision role. Both literals must
# carry all of them VERBATIM, so the flag-on variant cannot buy its fix by deleting the price rule
# instead of re-wording it -- the J6 failure mode, checked rather than promised.
_K94_PERSONA_KEPT = (
    "If the block carries a line beginning 'PRICE-RESPONSE'",
    "put BOTH price LEVELS under '## The record', each cited by its [N] handle EXACTLY as printed",
    "narrate the DIRECTION in prose (rose/fell) -- the level is the [N] row, the direction is prose.",
    "NOT a futures settle and NOT your forecast",
    "observed price LEVELS arrive as [N] rows -- cite them with their [N] handle like any observed "
    "number; NEVER mint an uncited price figure.",
    "Render this ONLY when a 'PRICE-RESPONSE' line is present; never volunteer a price move from prose.",
)

# THE ONE CLAUSE THAT IS RE-WORDED RATHER THAN CARRIED OR CUT (verify MAJOR, second fix pass). HEAD's
# current/future-MY sentence names a ROLE WORD, which on the flag-on path is a second instruction on this
# item's own axis -- so it moves, and this roster is what stops the move being a deletion: the clause's
# three survivors (its MY scope, the not-our-forecast point, the three-word roster) must all be in the
# flag-on literal, in a form that defers the word instead of picking it.
# ...lowercase at the head because in HEAD's paragraph the clause follows a ';' rather than a '.'
_K94_PERSONA_ROLE_CLAUSE_HEAD = "a current- or future-MY value is a USDA PROJECTION and must be " \
                               "attributed as one."
_K94_PERSONA_ROLE_CLAUSE_VR = ("The same rule covers a current- or future-MY value: it is the USDA's own "
                               "read of a marketing year the record has not closed, never our forecast, "
                               "and the word for it is the revision role the record declares (actual / "
                               "estimate / projection).")
_K94_PERSONA_ROLE_CLAUSE_SURVIVORS = ("current- or future-MY value",     # the MY scope HEAD named
                                      "never our forecast",              # the not-our-forecast point
                                      "(actual / estimate / projection)")  # the roster, deferred to


def test_k9_4_red_the_persona_seam_b_paragraph_is_the_fourth_producer_and_stops_asserting_the_role(
        monkeypatch):
    """RED, AND THE ONE THE BUILD MISSED. The assertion this item exists to delete had a FOURTH
    producer: `_SYSTEM_CASCADE`'s SEAM-B paragraph, which told the writer -- as a standing rule, in the
    writer's own instruction voice -- "the settled US season-average FARM price" and "This is a
    survey-based USDA season-average actual (revision_stamp)". It is gated on the same 'PRICE-RESPONSE'
    line the leg emits and `GRAPHRAG_CASCADE_QUANT` defaults 'on', so it shipped on all 12 banked turns
    and on both serving tiers.

    THE FIX DEFERS INSTEAD OF RE-ASSERTING. The persona is assembled before any row is read, so it
    cannot know the pair's role without a new coupling; the flag-on paragraph therefore states no
    finality at all and tells the writer to COPY the role the line and the row declare -- fail-closed
    on all three `_price_role_terms` branches at once.

    THIS REDS AT HEAD in the plainest possible way: `_SYSTEM_CASCADE_VR` does not exist there."""
    from leviathan.graphrag import answer as an
    # ANTI-VACUITY: the phrases really are in HEAD's paragraph, which is `_SYSTEM_CASCADE` unchanged
    for phrase in _K94_PERSONA_HEAD_ASSERTIONS:
        assert phrase in an._SYSTEM_CASCADE_PRICE_RESPONSE, phrase
        assert phrase in an._SYSTEM_CASCADE, phrase

    monkeypatch.delenv(FLAG_K94, raising=False)
    off = an._system()
    assert an._SYSTEM_CASCADE_PRICE_RESPONSE in off
    assert an._SYSTEM_CASCADE_PRICE_RESPONSE_VR not in off

    monkeypatch.setenv(FLAG_K94, "on")
    on = an._system()
    assert an._SYSTEM_CASCADE_PRICE_RESPONSE_VR in on
    assert an._SYSTEM_CASCADE_PRICE_RESPONSE not in on
    # the two assertions are gone from the WHOLE assembled persona, not merely from the paragraph
    for phrase in _K94_PERSONA_HEAD_ASSERTIONS:
        assert phrase not in on, phrase
    # ...and the finality words the STOP sentence used are not handed over as a description of the
    # figure. "settled" survives ONLY in the two clauses that forbid upgrading to it.
    assert "season-average actual" not in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR
    assert "the settled" not in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR
    # THE DEFERRAL IS POSITIVE AND NAMES WHAT TO WRITE (J6), so it cannot be satisfied by omission
    assert "HOW SETTLED IT IS, THE RECORD DECLARES AND YOU COPY" in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR
    assert ("write the role in the words the line and the row use"
            in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR)
    assert "not published on this read" in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR
    # THE FIX IS NOT A DELETION: every non-finality instruction is in BOTH literals
    for kept in _K94_PERSONA_KEPT:
        assert kept in an._SYSTEM_CASCADE_PRICE_RESPONSE, kept
        assert kept in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR, kept


def test_k9_4_the_flag_on_prompt_cannot_contradict_its_own_block(monkeypatch):
    """THE FAILURE THE FIX PASS ACTUALLY CLOSED, reproduced end to end on the design's own mixed pair
    (MY2024/25 `actual` beside MY2025/26 `estimate`). Before the fix, a flag-on turn shipped a prompt
    that disagreed with itself: the BLOCK said "an in-year USDA estimate at this as-of, not a settled
    survey figure" three times while the PERSONA on the same turn still said "the settled US
    season-average FARM price" and "a survey-based USDA season-average actual" -- handing the writer
    back both words the judged STOP sentence used. That is the design's MAJOR-3 class ("a fix naming
    only the last of them leaves the claim in the prompt twice") one site further out, and it made
    flag-on strictly worse than HEAD, which at least agreed with itself.

    Both halves are asserted on ONE turn's bytes, because the contradiction only exists between
    them."""
    from leviathan.graphrag import answer as an
    monkeypatch.setenv(FLAG_K94, "on")
    block = "\n".join(_k94_pair("actual", "estimate", vintage_role=True)[0])
    persona = an._system()
    assert block.count("an in-year USDA estimate at this as-of, not a settled survey figure") == 3
    assert "revision_stamp estimate" in block
    for phrase in _K94_PERSONA_HEAD_ASSERTIONS:
        assert phrase not in persona, phrase
    # the counterfactual is measured, not asserted: HEAD's persona DOES carry both, so this pin is
    # about a real disagreement and cannot go vacuous if the block wording is ever softened
    assert all(p in an._SYSTEM_CASCADE for p in _K94_PERSONA_HEAD_ASSERTIONS)
    # and the surviving disclaimers agree with the producer on EVERY branch rather than by luck:
    # `_price_role_terms` keeps "survey-based" and the futures-settle clause on all three, so the
    # persona keeps them too.
    from leviathan.graphrag.numbers import cascade as cq
    for ra, rb in (("actual", "actual"), ("actual", "estimate"), ("estimate", "projection"),
                   (None, "estimate")):
        _paren, tail = cq._price_role_terms(cq._row_role({"revision_stamp": ra}),
                                            cq._row_role({"revision_stamp": rb}))
        assert "survey-based" in tail and "NOT a futures settle" in tail, (ra, rb)
    assert "survey-based" in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR
    assert "NOT a futures settle" in an._SYSTEM_CASCADE_PRICE_RESPONSE_VR


def test_k9_4_the_flag_on_paragraph_states_the_role_rule_exactly_once(monkeypatch):
    """THE VERIFY-SEAT MAJOR, PINNED (second fix pass). The first pass deleted the finality assertion and
    left HEAD's role-word directive standing as the very NEXT sentence, so the flag-on paragraph shipped
    TWO instructions on this item's own axis where HEAD shipped one. Measured on the paragraph split at
    sentence boundaries, they were [2] "HOW SETTLED IT IS, THE RECORD DECLARES AND YOU COPY ... write the
    role in the words the line and the row use" and [3] "A current- or future-MY value is a USDA
    PROJECTION and must be attributed as one."

    THE CONFLICT WAS MEASURABLE ON THIS PIN'S OWN TURN, which is why it is pinned here rather than
    described: the design's worked pair is MY2024/25 `actual` beside MY2025/26 `estimate`, HEAD's clause
    names BOTH current AND future MY so it reaches MY2025/26 either way, and the block said `estimate`
    three times while the persona told the writer to attribute the same figure as a PROJECTION -- the
    publisher's finality judgement mis-stated by our own prompt, the class this item exists to close.

    THE FIX IS SUBORDINATION, NOT DELETION. The clause keeps its MY scope, its not-our-forecast point and
    the three-word roster, and defers the WORD to the record like every other producer in the item. So
    this pin checks both directions at once: exactly one role rule, and none of the clause's substance
    lost -- a paragraph that simply dropped the sentence fails the second half."""
    from leviathan.graphrag import answer as an
    monkeypatch.setenv(FLAG_K94, "on")
    vr, head = an._SYSTEM_CASCADE_PRICE_RESPONSE_VR, an._SYSTEM_CASCADE_PRICE_RESPONSE

    # ANTI-VACUITY: the directive really is HEAD's, and really is gone from the variant. Case-folded on
    # the leading article only, the same fold the KEPT roster used to carry: HEAD's clause follows a ';'.
    assert _K94_PERSONA_ROLE_CLAUSE_HEAD in head
    assert _K94_PERSONA_ROLE_CLAUSE_HEAD.lower() not in vr.lower()
    assert "must be attributed as one" not in vr
    assert "is a USDA PROJECTION" not in vr

    # NOT A DELETION: the re-worded clause is present and carries every survivor
    assert _K94_PERSONA_ROLE_CLAUSE_VR in vr
    for survivor in _K94_PERSONA_ROLE_CLAUSE_SURVIVORS:
        assert survivor in _K94_PERSONA_ROLE_CLAUSE_VR, survivor
        assert survivor in vr, survivor
    # ...and it reads as a CONTINUATION of the copy rule rather than a second directive
    assert _K94_PERSONA_ROLE_CLAUSE_VR.startswith("The same rule covers")
    assert vr.index("HOW SETTLED IT IS, THE RECORD DECLARES AND YOU COPY") < vr.index(
        _K94_PERSONA_ROLE_CLAUSE_VR)

    # ONE INSTRUCTION ON THE AXIS, MEASURED ON SENTENCES rather than asserted: the three role words
    # appear in the whole paragraph exactly once each, all three inside the ONE roster parenthetical,
    # so no sentence anywhere names a single role word as the word for the figure.
    role_rx = re.compile(r"\b(?:actual|estimate|projection)s?\b", re.I)
    sents = [s.strip() for s in re.split(r"(?<=\.)\s+", vr.strip()) if s.strip()]
    carriers = [s for s in sents if role_rx.search(s)]
    assert len(carriers) == 1, carriers
    assert carriers[0] == _K94_PERSONA_ROLE_CLAUSE_VR
    assert [m.group(0) for m in role_rx.finditer(vr)] == ["actual", "estimate", "projection"]
    assert vr.count("(actual / estimate / projection)") == 1
    # the role-less fallback is likewise stated ONCE -- the fail-closed branch `_price_role_terms`
    # renders for the 8 role-None `avg_farm_price` mints of the banked census
    assert vr.count("not published on this read") == 1
    assert _K94_BANKED_ROLE_CENSUS[None] == 8

    # AND THE PROMPT NOW AGREES WITH ITS OWN BLOCK ON THE PAIR THAT EXPOSED IT: the block's word is
    # `estimate`, and no persona sentence supplies a competing one.
    block = "\n".join(_k94_pair("actual", "estimate", vintage_role=True)[0])
    assert block.count("an in-year USDA estimate at this as-of, not a settled survey figure") == 3
    assert "revision_stamp estimate" in block
    persona = an._system()
    assert _K94_PERSONA_ROLE_CLAUSE_VR in persona
    assert "USDA PROJECTION" not in persona
    # HEAD's persona DOES carry it, so the flag-off path is what it was and this pin cannot go vacuous
    assert "USDA PROJECTION" in an._SYSTEM_CASCADE


def test_k9_4_the_persona_split_is_byte_identical_to_head_and_moves_one_paragraph_only(monkeypatch):
    """THE OFF-PATH PROOF FOR THE FOURTH PRODUCER, and it is a byte-identity claim rather than a
    refactor note. The fix splits `_SYSTEM_CASCADE` into three parts so the ONE paragraph it must
    branch is a NAME -- not a `.replace()` on a 7,034-character persona and not a second copy of the
    clause's bytes. The attribute keeps HEAD's exact value: eight suites read it, three assert
    `_system(...) == _SYSTEM_MENTOR + _SYSTEM_CASCADE` and one SLICES it by marker offset, and all of
    them must be unmoved.

    THE SHA IS HEAD'S OWN, taken from `git show HEAD:src/leviathan/graphrag/answer.py` before the
    split and pinned here, so a later edit to any of the three parts reds with a cause instead of
    silently rewriting a persona nobody diffed."""
    import hashlib
    import inspect
    from leviathan.graphrag import answer as an
    assert len(an._SYSTEM_CASCADE) == 7034
    assert hashlib.sha256(an._SYSTEM_CASCADE.encode("utf-8")).hexdigest() == (
        "ec29629a4c115f4b2254a0af516768f0a252f04766a228fe6df341ab60ecbdff")
    # the composition, and the one-paragraph claim as an EQUALITY rather than a description
    assert an._SYSTEM_CASCADE == (an._SYSTEM_CASCADE_A + an._SYSTEM_CASCADE_PRICE_RESPONSE
                                  + an._SYSTEM_CASCADE_B)
    assert an._SYSTEM_CASCADE_VR == (an._SYSTEM_CASCADE_A + an._SYSTEM_CASCADE_PRICE_RESPONSE_VR
                                     + an._SYSTEM_CASCADE_B)
    assert an._SYSTEM_CASCADE.count(an._SYSTEM_CASCADE_PRICE_RESPONSE) == 1
    assert an._SYSTEM_CASCADE.replace(an._SYSTEM_CASCADE_PRICE_RESPONSE,
                                      an._SYSTEM_CASCADE_PRICE_RESPONSE_VR) == an._SYSTEM_CASCADE_VR
    # the assembled persona differs at exactly that one paragraph, at otherwise identical settings
    monkeypatch.delenv(FLAG_K94, raising=False)
    off = an._system()
    monkeypatch.setenv(FLAG_K94, "on")
    on = an._system()
    assert on == off.replace(an._SYSTEM_CASCADE_PRICE_RESPONSE, an._SYSTEM_CASCADE_PRICE_RESPONSE_VR)
    assert on != off
    # THE THIRD READ SITE IS IN `_system` AND IS PER-CALL, the same law as the other two: the env is
    # read at the seam, never memoized, so the rollback is an env flip and not a redeploy.
    src = inspect.getsource(an._system)
    assert "_SYSTEM_CASCADE_VR if _vintage_role_on() else _SYSTEM_CASCADE" in src
    # ...and the quantify half is still gated by GRAPHRAG_CASCADE_QUANT, which DEFAULTS ON -- which is
    # why this paragraph shipped on all 12 banked turns and why it had to be branched at all
    assert 'os.environ.get("GRAPHRAG_CASCADE_QUANT", "on") != "off"' in src


# -- THE OPEN DOCKET K9-4 SHIPS WITH, as data rather than as prose (the K9-6 precedent, same sitting) --
K94_OPEN_DOCKET = (
    {"id": "design-fix-3b-counter",
     "seam": "src/leviathan/graphrag/register.py",
     "symbol": "count_forecast_restatements",
     "shape": "the forecast-restatement COUNTER, on count_exec_words' / _SENT_ITER' shape, stamped on "
              "the trace beside register_leaks -- COUNTER ONLY, never a strip",
     "blocked_by": "register.py is not on this lane's allowlist; relocating the counter to a seam the "
                   "design did not name would be a worse answer than reporting it unbuilt",
     "state": "ABSENT"},
)


def test_k9_4_design_fix_3b_the_forecast_counter_is_unbuilt_and_docketed():
    """THE HALF OF 3b THAT DID NOT SHIP, CLOSED AS SCOPE AND MACHINE-CHECKED -- the K9-6 fix-(iv)
    precedent, same sitting, same reason, same tripwire shape.

    Design section 4 FIX 3b names `register.count_forecast_restatements(text, evidence)`. IT IS NOT
    BUILT. It is not built because register.py is not on this lane's allowlist, and because a counter
    relocated to a seam the design did not name is a different instrument wearing the same name. So
    K9-4 ships 2 OF 3 and THE ITEM STAYS OPEN; no K9-4 pin depends on the counter -- 3a's three print
    sites and the scope word are the item's tier-1 settlement -- which is exactly why the absence could
    otherwise be booked closed by accident.

    THE ADDRESS IS LIVE, NOT STALE: both `def count_exec_words` and `_SENT_ITER = re.compile(` are
    present in register.py at this HEAD, so 3b's counter is reachable work and not archaeology.

    THIS PIN REDS IN BOTH DIRECTIONS:
      * someone BUILDS the counter and leaves answer.py / cascade.py still declaring it unbuilt -> red;
      * someone DELETES one of those declarations while the counter is still absent -> red, so the
        scope of what actually shipped cannot be quietly widened by deleting the sentence that narrows
        it."""
    from pathlib import Path
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import register as rg
    from leviathan.graphrag.numbers import cascade as cq

    entry = [d for d in K94_OPEN_DOCKET if d["id"] == "design-fix-3b-counter"][0]
    reg_src = Path(rg.__file__).read_text(encoding="utf-8")
    built = hasattr(rg, entry["symbol"]) or entry["symbol"] in reg_src
    assert not built, (
        "design fix 3b's counter has LANDED: register.count_forecast_restatements now exists. This pin "
        "is the tripwire that says so. Update, in ONE sitting: (1) the DELIBERATELY NOT COVERED bullet "
        "in cascade.py's K9-4 block note, (2) the _vintage_role_on docstring paragraph in answer.py, "
        "(3) this deck's K94_OPEN_DOCKET entry -- and only then may K9-4 be booked 3 of 3.")
    assert "def count_exec_words" in reg_src, "the design's named seam moved -- re-address the docket"
    assert "_SENT_ITER = re.compile(" in reg_src, "the design's named shape moved -- re-address the docket"
    csrc = Path(cq.__file__).read_text(encoding="utf-8")
    asrc = Path(an.__file__).read_text(encoding="utf-8")
    assert "K9-4 IS THEREFORE 2 OF 3 AND" in csrc, (
        "cascade.py's block note no longer declares 3b's counter unbuilt while it still is")
    assert "DESIGN FIX 3b IS HALF-BUILT AND K9-4 IS 2 OF 3" in asrc, (
        "answer.py's flag docstring no longer declares 3b's counter unbuilt while it still is")
    assert entry["state"] == "ABSENT" and entry["blocked_by"]
    # this lane did not touch register.py: the remedy is a recorded SCOPE call, never a quiet edit
    assert "vintage_role" not in reg_src and "K9-4" not in reg_src


def test_k9_4_the_flag_is_read_at_the_two_permitted_seams_and_never_inside_the_engine():
    """[SKEPTIC F3] IS LAW IN cascade.py AND THIS ITEM HAS TWO READERS, so the split is pinned rather
    than trusted. cascade.py performs NO environment read of any kind (two live doctrine tests
    substring-scan its source), so the engine half is threaded from `answer._vintage_role_on()` as the
    `vintage_role` kwarg; citations.py reads the env directly, exactly as its two K9 siblings do.

    ONE FLAG NAME, TWO READERS, and the name is spelled identically in both -- a typo in one would ship
    a half-lit item no off-pin could catch, because each half's own off-pin would still pass."""
    import inspect
    from pathlib import Path
    from leviathan.graphrag import answer as an
    from leviathan.graphrag.numbers import cascade as cq

    csrc = Path(cq.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in csrc and "import os" not in csrc
    read = 'os.environ.get("GRAPHRAG_VINTAGE_ROLE", "").strip().lower() in ("on", "1", "true")'
    assert read in inspect.getsource(an._vintage_role_on)
    assert read in inspect.getsource(cit._vintage_role_on)
    # the engine is gated by the ARGUMENT alone, on both of the seams that carry it
    for fn in (cq.quantify, cq._price_pair):
        assert inspect.signature(fn).parameters["vintage_role"].default is False
    # ...and it is appended at the TAIL of quantify's signature, the g1x prefix rule.
    # S5 RE-ANCHOR (2026-09-08), by exactly ONE name and WITHOUT loosening the rule: STATE-ENGINE
    # PHASE 0 appends `xc_sublegs_on_composer` after it (design 9.1 / D9, GRAPHRAG_XC_SUBLEGS_ON_
    # COMPOSER, default False, dark). What K9-4 claims is that `vintage_role` LANDED AT THE TAIL and
    # moved nothing before it -- so the pin now reads it as the last name BEFORE the appends that
    # followed, each of which is OPTIONAL here, so reverting either item leaves this green.
    # S6 RE-ANCHOR (2026-09-09), by exactly ONE more name and on the SAME rule: STATE ENGINE PHASE 2
    # appends `board` (design 3.9 / D8, GRAPHRAG_STATE_BOARD, default None -- a PAYLOAD dict) after
    # phase 0's name. What K9-4 claims -- that `vintage_role` LANDED AT THE TAIL and moved nothing
    # before it -- is unchanged; each later append is OPTIONAL here, so reverting any of them leaves
    # this green.
    _qt = list(inspect.signature(cq.quantify).parameters)
    _after_k94 = [n for n in ("xc_sublegs_on_composer", "board") if n in _qt]
    assert _qt[len(_qt) - 1 - len(_after_k94)] == "vintage_role", _qt[-3:]
    assert _qt[len(_qt) - len(_after_k94):] == _after_k94, _qt[-3:]
    # THE DEPARTURE IS DECLARED IN SOURCE, NOT ONLY IN A REPORT. Design section 8 says K9-4 "rides
    # flags that are already on"; MEASURED, those are GRAPHRAG_CASCADE_PRICE_LEG and
    # GRAPHRAG_RECENCY_STAMP, BOTH `on` in cascade_control_overrides.json AND
    # cascade_treatment_overrides.json (59 env entries each), so riding them would have shipped a
    # reader-facing label change LIT on both serving tiers with no rollback of its own. This lane's law
    # is dark-behind-its-own-default-off-flag, so a flag was minted; both files declare that, and this
    # pin keeps the declaration from being deleted while the flag stays.
    assert "THE DESIGN NAMED NO FLAG FOR K9-4" in Path(cit.__file__).read_text(encoding="utf-8")
    assert "THE DESIGN NAMED NO FLAG AND THIS BUILD MINTS ONE" in inspect.getsource(an._vintage_role_on)


def test_k9_4_the_answer_seam_is_omit_when_off_and_its_span_is_measured():
    """THE SEAM, AND THE GOLDEN IT MOVES. K9-4 appends ONE omit-when-off kwarg to `_answer_l2`'s
    kwarg-assembly block -- the block the g1x seam golden hashes -- so the golden is RE-ANCHORED on
    this item's own named line set (`test_cascade_walk._G1X_K94_CUT`) and the banked HEAD sha
    2b4407f4 is NOT re-banked. That is the D-MF precedent: a golden that moves needs a named cause and
    the pre-bank kept.

    THE CUT ORDER IS LOAD-BEARING: each spread-undo regex requires its own kwarg to be LAST on the call
    line, and `**_vr_kw` now sits between `**_xlh_kw` and `**_eod_kw`. K9-4 is cut FIRST so K9-6's
    regex still finds the text it was written against. Pinned here so the order cannot be "tidied".

    The span constants are MEASURED on the shipped seam. If you edited this comment block DELIBERATELY,
    re-measure them AND re-run the g1x golden -- it must still land on 2b4407f4."""
    import hashlib
    import importlib.util
    import inspect
    from pathlib import Path
    from leviathan.graphrag import answer as an

    repo = Path(__file__).resolve().parents[2]
    _spec = importlib.util.spec_from_file_location(
        "_k94_walk_deck_span", str(repo / "tests" / "unit" / "test_cascade_walk.py"))
    _walk = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_walk)
    start, stop = _walk._G1X_K94_CUT
    src = inspect.getsource(an._answer_l2)
    assert src.count(start) == 1 and src.count(stop) == 1
    a = src.rfind("\n", 0, src.index(start)) + 1
    b = src.find("\n", src.index(stop) + len(stop)) + 1
    span = src[a:b]
    assert span.count("\n") == 4, span
    assert len(span) == 384, len(span)
    assert hashlib.sha256(span.encode("utf-8")).hexdigest() == (
        "7f9a643cf441ca76ce98aa3687f830290f5a536dbe713806c9fcf1615ef39728"), span
    stmts = [ln.strip() for ln in span.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert stmts == [stop], stmts        # exactly one statement, and it is the cut's own stop anchor
    # K9-4's own lines land AFTER K9-6's stop anchor, so K9-6's measured span is untouched
    assert src.index(_walk._G1X_K96_CUT[1]) < src.index(start)
    # the spread lands BEFORE `**_eod_kw`, which is the g1x producer's own end anchor.
    # S5 RE-ANCHOR (2026-09-08): PHASE 0's `**_xsc_kw` lands between `**_vr_kw` and `**_eod_kw`, on the
    # same law and for the same reason (an append ON the `**_eod_kw` spread leaves the producer without
    # its end anchor and takes the whole gate down). K9-4's OWN claim -- its spread sits immediately
    # after K9-6's and strictly before the producer's end anchor -- is unchanged and still asserted;
    # what moved is only what sits between it and `**_eod_kw`, and that is named rather than globbed.
    assert "**_xlh_kw, **_vr_kw, " in src
    _i = src.index("**_xlh_kw, **_vr_kw, ")
    # S6 RE-ANCHOR (2026-09-09): PHASE 2's `**_sb_kw` lands between `**_xsc_kw` and `**_eod_kw`, on
    # the same law and for the same reason (an append ON the `**_eod_kw` spread leaves the g1x
    # producer without its end anchor and takes the whole gate down). K9-4's OWN claim -- its spread
    # sits immediately after K9-6's and strictly before the producer's end anchor -- is unchanged and
    # still asserted; what moved is only what sits between it and `**_eod_kw`, named rather than
    # globbed, so a fourth append still reds this line instead of sliding past it.
    _tail = src[_i:src.index(")", _i) + 1]
    assert _tail in ("**_xlh_kw, **_vr_kw, **_eod_kw)",
                     "**_xlh_kw, **_vr_kw, **_xsc_kw, **_eod_kw)",
                     "**_xlh_kw, **_vr_kw, **_xsc_kw, **_sb_kw, **_eod_kw)"), _tail
    # and the recovery still reaches the banked HEAD block, cut order and all
    _repro, _head = _walk._g1x_sans(str(repo / "data" / "consequence_leg" / "xl_golden_seam_bank.py"))
    assert _head == "2b4407f4b7701799036182180bcc09993f49a37f4593e84d86912865a686e074"
