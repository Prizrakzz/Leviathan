"""ESR destination filtering (ESR_DESTINATION_PLAN W1-W3) -- the query-side name<->code translation and the
agent honesty-guard DOWNGRADE. AWS-free: build_sql string shape, apply_pit_filter oracle parity, the
post-fetch code->name render, and the agent loop with a mocked LLM + injected query_fn.

Covers the folded skeptic findings:
  * S1 [HIGH]: the national (no-country) path keeps ``country`` OUT of the ``agg=latest`` _total_order
    tiebreak -> the esr_exports cascade leg value stays byte-stable (declaring country_col must not flip it).
  * S2 [MED]: the row's country_code is a STRING on both backends; the int-keyed reference render is
    str-normalized (parity can't see the label, so it needs its own unit coverage).
"""
from __future__ import annotations

import types

from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry


def _esr():
    return load_registry().get("silver_esr")


# ── build_sql: name -> code IN filter (sub-route A2, CAST-as-varchar backend-agnostic) ─────────────────
def test_named_destination_emits_cast_in_code_filter():
    ts = _esr()
    sql = Q.build_sql(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-05-20",
                                    commodity="corn_cbot", country="China", agg="sum"), ts)
    assert "CAST(country_code AS varchar) IN ('5700')" in sql        # China -> FAS 5700, quoted string IN
    assert "country_code = 'China'" not in sql                       # never the type-broken plain equality


def test_demonym_and_bloc_resolve():
    ts = _esr()
    chinese = Q.build_sql(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                        asof="2026-05-20", commodity="corn_cbot", country="chinese",
                                        agg="sum"), ts)
    assert "IN ('5700')" in chinese                                  # demonym resolves too
    eu = Q.build_sql(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-05-20",
                                   commodity="soybeans_cbot", country="the EU", agg="sum"), ts)
    assert "CAST(country_code AS varchar) IN ('1')" in eu            # EU bloc code 1


def test_unresolved_name_fails_closed_never_national():
    ts = _esr()
    sql = Q.build_sql(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-05-20",
                                    commodity="corn_cbot", country="Narnia", agg="sum"), ts)
    assert "CAST(country_code AS varchar) IN ('__unresolved_destination__')" in sql   # zero rows, not national


# ── S1: national (no-country) path -- country stays OUT of the agg=latest tiebreak ────────────────────
def test_national_agg_latest_drops_country_from_tiebreak():
    ts = _esr()
    sql = Q.build_sql(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-05-20",
                                    commodity="corn_cbot", agg="latest"), ts)
    order = sql.rsplit("ORDER BY", 1)[1]
    assert "country" not in order                                    # S1: no country in the LIMIT-1 tiebreak
    assert sql.strip().endswith("LIMIT 1")
    # and no country IN filter at all on the national path
    assert "country_code AS varchar) IN" not in sql
    assert "CAST(country_code" not in sql


def test_scoped_agg_latest_keeps_country_in_tiebreak():
    ts = _esr()
    sql = Q.build_sql(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-05-20",
                                    commodity="corn_cbot", country="China", agg="latest"), ts)
    assert "CAST(country_code AS varchar) IN ('5700')" in sql        # scoped: the filter is present
    assert "country" in sql.rsplit("ORDER BY", 1)[1]                 # and country participates when a dest is named


# ── apply_pit_filter oracle parity with the SQL code-IN filter ────────────────────────────────────────
_ROWS = [
    {"commodity_name": "corn_cbot", "market_year": 2026, "country_code": "5700",
     "week_ending_date": "2026-05-07", "as_of_date": "20260514", "weekly_exports_1000mt": 800.0},
    {"commodity_name": "corn_cbot", "market_year": 2026, "country_code": "2010",
     "week_ending_date": "2026-05-07", "as_of_date": "20260514", "weekly_exports_1000mt": 500.0},
]


def test_oracle_keeps_only_the_scoped_destination():
    ts = _esr()
    kept = Q.apply_pit_filter(_ROWS, Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                                   asof="2026-05-20", commodity="corn_cbot",
                                                   country="China"), ts)
    assert [r["country_code"] for r in kept] == ["5700"]            # only the China row


def test_oracle_national_keeps_all_destinations():
    ts = _esr()
    kept = Q.apply_pit_filter(_ROWS, Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                                   asof="2026-05-20", commodity="corn_cbot"), ts)
    assert {r["country_code"] for r in kept} == {"5700", "2010"}    # national: every destination


def test_oracle_unresolved_keeps_none():
    ts = _esr()
    kept = Q.apply_pit_filter(_ROWS, Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                                   asof="2026-05-20", commodity="corn_cbot",
                                                   country="Narnia"), ts)
    assert kept == []                                               # fail-closed, never a national total


# ── S2: post-fetch code -> display-name render off the STRING row code ─────────────────────────────────
def test_apply_country_names_renders_string_code():
    ts = _esr()
    rows = [{"value": "800.0", "country": "5700", "knowledge_date": "20260514"},
            {"value": "500.0", "country": "2010", "knowledge_date": "20260514"}]
    out = Q._apply_country_names(rows, Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                                     asof="2026-05-20"), ts)
    assert [r["country"] for r in out] == ["China", "Mexico"]       # int-keyed ref, str-normalized lookup


def test_apply_country_names_noop_without_ref():
    ts = load_registry().get("silver_psd")                          # no country_name_ref
    rows = [{"value": "1", "country": "Brazil"}]
    assert Q._apply_country_names(rows, Q.NumberQuery(table="silver_psd", metric="production_mt",
                                                      asof="2026-05-20"), ts)[0]["country"] == "Brazil"


# ── agent guard DOWNGRADE (W3.4) -- mocked LLM + injected query_fn ─────────────────────────────────────
def _tool_use(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=inp, id=tid)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(content):
    return types.SimpleNamespace(content=content, stop_reason="end_turn")


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class _FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


def _scoped_esr(country="China", tid="t1"):
    return _tool_use({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                      "country": country, "period": "2025", "agg": "sum"}, tid)


def _run(question, queue):
    return A.answer_numbers(question, asof="2026-05-20", client=_FakeClient(queue),
                            query_fn=lambda sql: [{"value": "1234.5", "knowledge_date": "20260514",
                                                   "country": "5700"}])


def test_scoped_named_destination_is_served_no_decline():
    # the model PASSED country='China' -> the destination is served, so NO national-total decline preface.
    model_text = "Corn sales to China were 1,234.5 thousand MT (report of 2026-05-14)."
    out = _run("How are corn sales to China pacing this marketing year?",
               [_resp([_scoped_esr("China")]), _resp([_text(model_text)])])
    assert out["esr_destination_guard"] == "China"
    assert out.get("esr_destination_served") == "China"
    assert out["answer"] == model_text                              # served as-is: no decline preface
    assert not out["answer"].startswith("One limitation to flag")
    assert "scope_note" not in out["calls"][0]                      # a real single country carries no national note


def test_unresolved_named_destination_still_declines():
    # the model passed an unresolved country -> NOT destination-scoped -> the honest national decline stands.
    model_text = "The figure is unavailable for that destination."
    out = _run("How are corn sales to Narnia pacing?",
               [_resp([_scoped_esr("Narnia")]), _resp([_text(model_text)])])
    # 'Narnia' is not a detected destination name, so the guard does not even flag it; the national ESR
    # lookup returns rows but the answer is byte-identical (no destination guard fired).
    assert "esr_destination_served" not in out


def test_national_lookup_for_named_dest_keeps_decline():
    # the model ran a NATIONAL ESR lookup (no country) for a China ask -> the national-total decline stands
    # (byte-identical to the pre-downgrade behavior).
    national = _tool_use({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                          "period": "2025", "agg": "latest"})
    out = A.answer_numbers("How are corn sales to China pacing?", asof="2026-05-20",
                           client=_FakeClient([_resp([national]),
                                               _resp([_text("Weekly corn exports were 1,234.5 thousand MT.")])]),
                           query_fn=lambda sql: [{"value": "1234.5", "knowledge_date": "20260514"}])
    assert out["esr_destination_guard"] == "China"
    assert "esr_destination_served" not in out
    assert out["answer"].startswith("One limitation to flag")       # national fallback decline
    assert out["calls"][0]["scope_note"].startswith("NATIONAL TOTAL")


def test_bloc_scoped_read_with_rows_gets_bloc_caveat():
    # A bloc code that ACTUALLY RETURNED a figure (here mocked non-empty) -> served WITH a bloc-aggregate
    # caveat, not a national decline and not a bare single-country claim. (Real silver_esr has no EU rows;
    # this pins the rows-present branch of the gate -- the empty branch is the next test.)
    model_text = "Soybean sales to the EU were 1,234.5 thousand MT (report of 2026-05-14)."
    out = A.answer_numbers("How are soybean sales to the EU pacing this year?", asof="2026-05-20",
                           client=_FakeClient([_resp([_scoped_esr("the EU")]), _resp([_text(model_text)])]),
                           query_fn=lambda sql: [{"value": "1234.5", "knowledge_date": "20260514",
                                                  "country": "1"}])
    assert out["esr_destination_guard"] == "the European Union"
    assert out.get("esr_destination_served") == "the European Union"
    assert out["answer"].startswith("One note on scope")            # bloc caveat, not the national decline
    assert model_text in out["answer"]
    assert out["calls"][0]["scope_note"].startswith("BLOC/REGIONAL AGGREGATE")


def test_bloc_scoped_read_empty_gets_no_caveat():
    # SKEPTIC fold (Finding 1): 'the EU' resolves to bloc code 1, which silver_esr does NOT carry (EU-27 is
    # absent from the data per the esr_destinations W0 audit -- aggregate_codes_present = [4461,5680,6860,7640],
    # no 1). So a REAL EU-scoped read returns ZERO rows. The bloc caveat ("the figure below covers the bloc")
    # must NOT preface an empty result, and no bloc scope_note may be stamped -- the model's honest no-data
    # narration stands. The caveat is gated on rows-returned.
    model_text = "No EU-specific export-sales figure is available from this lookup."
    out = A.answer_numbers("How are soybean sales to the EU pacing this year?", asof="2026-05-20",
                           client=_FakeClient([_resp([_scoped_esr("the EU")]), _resp([_text(model_text)])]),
                           query_fn=lambda sql: [])                  # EU code 1 absent -> zero rows (as in real data)
    assert out["esr_destination_guard"] == "the European Union"
    assert out.get("esr_destination_served") == "the European Union"   # routed to the dest cut, not national decline
    assert not out["answer"].startswith("One note on scope")           # no bloc caveat over an empty result
    assert not out["answer"].startswith("One limitation to flag")      # and not the national decline either
    assert out["answer"] == model_text                                 # honest no-data narration stands verbatim
    # D-PQ EMPTY-1 MOVED THIS ASSERTION, DELIBERATELY. The property under test is that no BLOC caveat is
    # stamped on an empty read, and it still holds. What is new is that an empty read now ALWAYS carries
    # the NO ROWS RETURNED marker -- the guard that stops "0.0 thousand MT" being narrated as a fact -- and
    # it is stamped by `_exec`, upstream of every destination branch. The two notes are about different
    # things (is there a figure at all / what scope would a figure have had) and the marker outranks.
    note = out["calls"][0].get("scope_note") or ""
    assert note.startswith("NO ROWS RETURNED (")
    assert "BLOC/REGIONAL AGGREGATE" not in note                       # no bloc note stamped on an empty read
