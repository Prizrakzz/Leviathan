"""D-CC-2 pairwise blind judge -- fixture-driven, ZERO API calls.

The four things that must be true before this instrument may decide anything:
  1. the presentation order is deterministic in the row id (a re-run reproduces the recorded blind);
  2. the answer text it judges is the SAME text the absolute judge saw -- pinned against eval.judge's
     own prompt, not against a copy of it;
  3. the pre-registered checklist yaml schema-matches the deck it was written for;
  4. the conversion counter's arithmetic is what the module says it is.
"""
from __future__ import annotations

import json

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as gev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import pairwise_judge as pj

_CFG = ex._CFG
_DECK = _CFG / "eval_queries_deepv2_width_v1.yaml"
_CHECKS = _CFG / "eval_checklists_deepv2_width_v1.yaml"

_ANSWER = (
    "**TL;DR.** Russia carries no dated policy row at the as-of.\n"
    "\n"
    "**Why.** ## Mechanism\n"
    "\n"
    "India's export ban is the only dated instrument in the record [E1]. Russia's floating export tax "
    "is discussed in general prose but has no dated row behind it.\n"
    "\n"
    "## Sources\n"
    "[1] USDA FAS GAIN Report - Wheat (2026-04-02): The Indian government extended its export ban on "
    "wheat and wheat products through the marketing year."
)


def _out(answer: str = _ANSWER) -> dict:
    return {"answer": answer, "contract": "soft_red_winter_wheat_cbot", "contracts": ["soft_red_winter_wheat_cbot"],
            "structured": {"tldr": "t", "mechanism": "m", "sources": [{"ref": 1}]},
            "evidence": [{"source": "usda_gain_wheat", "date": "2026-04-02", "text": "export ban"}],
            "intent": "hybrid", "number_calls": [], "citations": [], "model": "claude-sonnet-4-6",
            "trace": {"citation_verifier": {"enabled": True, "stripped": 0, "claim_count": 3, "checked": 2},
                      "raw_draft": {"tldr": "draft tldr", "mechanism": "draft mechanism"}}}


def _query(qid: str = "dv_xorigin_wheat_policy") -> dict:
    return {"id": qid, "category": "dv_cross_origin_rank", "contract": "soft_red_winter_wheat_cbot",
            "asof": "2026-08-06", "question": "How does the exporter ranking come out?"}


# -- 1. deterministic blind ------------------------------------------------------------------------
def test_presentation_order_is_deterministic_per_row_id():
    ids = [str(q["id"]) for q in gev.load_queries(_DECK)]
    once = {i: pj.presentation_order(i) for i in ids}
    assert once == {i: pj.presentation_order(i) for i in ids}          # stable within a process
    # and stable ACROSS processes -- blake2b, not the per-process-randomized str hash
    assert pj.presentation_order("dv_xorigin_wheat_policy") == \
        pj.presentation_order("dv_xorigin_wheat_policy", salt=pj._ORDER_SALT)
    assert {o[0] for o in once.values()} == {"A", "B"}                 # the deck actually gets both blinds
    flipped = [i for i in ids if pj.presentation_order(i, salt="other-salt") != once[i]]
    assert flipped                                                     # the salt is load-bearing


def test_verdict_labels_map_back_through_the_order():
    assert pj._to_arm("ANSWER_1", ("B", "A")) == "B"
    assert pj._to_arm("ANSWER_2", ("B", "A")) == "A"
    assert pj._to_arm("tie", ("B", "A")) == "tie"
    assert pj._to_arm("garbage", ("A", "B")) == "tie"                  # never silently credits an arm


# -- 2. render parity with eval.py's judge ---------------------------------------------------------
def test_render_fields_matches_answer_render():
    """_render_fields is a COPY of answer.render's tldr+mechanism line (answer.py:2033). Pin it."""
    d = {"tldr": " a tldr ", "mechanism": " a mechanism "}
    assert pj._render_fields(d["tldr"], d["mechanism"]) == an.render(d, include_ledger=False)


def test_resolved_text_is_byte_identical_to_what_eval_judge_renders():
    """The pairwise judge must see the SAME string eval.judge puts under '=== THE TOOL'S ANSWER ==='.
    Pinned against eval.judge itself via its injectable `call`, not against a re-implementation."""
    seen = {}

    def fake_call(client, system, user, *, model, max_tokens, tool):
        seen["user"] = user
        return {"usefulness": 4, "gaps": [], "verdict": "v"}, None

    gev.judge(_query(), _out(), graph=None, client=None, call=fake_call)
    row = gev._per_answer_record({"q": _query(), "out": _out(), "rubric": gev.score(_query(), _out()),
                                  "secs": 1.0}, "single")
    rep_md = gev.report([{"q": _query(), "out": _out(), "rubric": gev.score(_query(), _out()), "secs": 1.0}],
                        model="claude-sonnet-4-6")
    answers = pj.parse_report_answers(rep_md, [_query()["id"]])
    text, prov = pj.render_answer_for_judge(row, report_answers=answers)
    assert prov == "report_md"
    assert seen["user"].endswith("=== THE TOOL'S ANSWER ===\n" + text)  # byte-identical, footer included


def test_answer_text_ladder_prefers_exact_over_proxy():
    rid = "dv_sub_ddg_floor"
    rd_full = {"tldr": "raw t", "mechanism": "raw m", "verified_tldr": "ver t", "verified_mechanism": "ver m",
               "body_pre_sanitize": "BODY"}
    assert pj.render_answer_for_judge({"id": rid, "answer": "EXACT", "raw_draft": rd_full}) == ("EXACT", "answer")
    assert pj.render_answer_for_judge({"id": rid, "raw_draft": rd_full},
                                      report_answers={rid: "FROM REPORT"}) == ("FROM REPORT", "report_md")
    assert pj.render_answer_for_judge({"id": rid, "raw_draft": rd_full}) == ("BODY", "body_pre_sanitize")
    t, p = pj.render_answer_for_judge({"id": rid, "raw_draft": {k: v for k, v in rd_full.items()
                                                               if k != "body_pre_sanitize"}})
    assert p == "verified_fields" and "ver t" in t and "ver m" in t
    t, p = pj.render_answer_for_judge({"id": rid, "raw_draft": {"tldr": "raw t", "mechanism": "raw m"}})
    assert p == "raw_fields" and "raw t" in t
    assert pj.render_answer_for_judge({"id": rid}) == ("", "missing")
    assert pj.PROVENANCE["report_md"][0] is True and pj.PROVENANCE["raw_fields"][0] is False


def test_report_parser_survives_headings_inside_the_answer_body():
    """An answer body carries its own '## Mechanism' / '## Sources' headings, so the parser anchors on the
    deck's row ids -- a bare '^## ' scan would cut the answer in half."""
    rows = [{"q": _query(i), "out": _out(_ANSWER + f"\n(row {i})"),
             "rubric": gev.score(_query(i), _out()), "secs": 1.0}
            for i in ("dv_sub_ddg_floor", "dv_xorigin_wheat_policy")]
    md = gev.report(rows, model="claude-sonnet-4-6")
    got = pj.parse_report_answers(md, ["dv_sub_ddg_floor", "dv_xorigin_wheat_policy"])
    assert set(got) == {"dv_sub_ddg_floor", "dv_xorigin_wheat_policy"}
    assert got["dv_sub_ddg_floor"].endswith("(row dv_sub_ddg_floor)")
    assert "## Sources" in got["dv_xorigin_wheat_policy"] and "## dv_" not in got["dv_xorigin_wheat_policy"]


def test_report_parser_round_trip_is_byte_exact_including_a_trailing_newline():
    """report() appends exactly ONE separator line after each answer; the parser drops exactly that one,
    so a non-last row round-trips byte-for-byte even when the answer itself ends in a newline."""
    trailing = _ANSWER + "\n"
    rows = [{"q": _query("dv_sub_ddg_floor"), "out": _out(trailing),
             "rubric": gev.score(_query(), _out()), "secs": 1.0},
            {"q": _query("dv_xorigin_wheat_policy"), "out": _out(_ANSWER),
             "rubric": gev.score(_query(), _out()), "secs": 1.0}]
    got = pj.parse_report_answers(gev.report(rows, model="claude-sonnet-4-6"),
                                  ["dv_sub_ddg_floor", "dv_xorigin_wheat_policy"])
    assert got["dv_sub_ddg_floor"] == trailing                          # exact, newline preserved
    assert got["dv_xorigin_wheat_policy"] == _ANSWER                    # exact, last row, no trailing nl


# -- 3. the pre-registered instrument --------------------------------------------------------------
def test_checklists_load_and_schema_validate_against_the_deck():
    cfg = pj.load_checklists(_CHECKS)
    queries = gev.load_queries(_DECK)
    errs, warns = pj.validate_checklists(cfg, queries)
    assert errs == [] and warns == []                                   # every deck row is covered
    assert cfg["deck"] == _DECK.stem and cfg["checklist_version"] == "deepv2_width_v1"
    assert [r["id"] for r in cfg["rows"]] == [str(q["id"]) for q in queries]
    for r in cfg["rows"]:
        assert 3 <= len(r["items"]) <= 6
        assert r["beyond_quick_sources"] and all(e.get("markers") for e in r["beyond_quick_sources"])


def test_checklist_wording_is_arm_blind():
    """The pre-registration is neutral: an item that names a mode is an item that pre-decides the run."""
    text = _CHECKS.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    asks = " ".join(str(it["ask"]) for r in pj.load_checklists(_CHECKS)["rows"] for it in r["items"]).lower()
    for banned in ("quick", "deep", "deep_v2", "arm a", "arm b", "baseline"):
        assert banned not in asks, f"checklist item wording names an arm: {banned}"
    assert body.isascii()


def test_validation_rejects_a_mismatched_instrument():
    queries = gev.load_queries(_DECK)
    bad = {"checklist_version": "v", "deck": "d",
           "rows": [{"id": "not_a_deck_row", "items": [{"id": "a", "ask": "?"}],
                     "beyond_quick_sources": [{"key": "k"}, {"key": "k", "markers": ["m"]}]}]}
    errs, _ = pj.validate_checklists(bad, queries)
    joined = " | ".join(errs)
    assert "not a deck row id" in joined
    assert "1 items" in joined                                          # the 3-6 pre-registration law
    assert "no markers" in joined and "duplicate beyond_quick_sources key" in joined
    _, warns = pj.validate_checklists(bad, queries)
    assert len(warns) == len(queries)                                   # every real row flagged uncovered


# -- 4. the deterministic counter ------------------------------------------------------------------
_ENTRIES = [
    {"key": "driver_slice:russia_export_tax_quota", "markers": ["export tax", "export quota"],
     "context_markers": ["russia", "russian"]},
    {"key": "driver_slice:export_ban", "markers": ["export ban"]},
    {"key": "silver:silver_psd", "markers": ["psd", "production supply and distribution"]},
]


def test_conversion_counts_cited_block_and_flags_asserted_uncited():
    c = pj.count_conversion(_ANSWER, _ENTRIES)
    assert c["proxy"] is True and c["scope"] == "cited_sources_block" and c["has_sources_block"] is True
    assert c["n_documented"] == 3
    # the export-ban family is CITED (its vocabulary is in the footer prop text)
    assert c["cited"] == ["driver_slice:export_ban"] and c["cited_hits"] == 1
    # Russia's export tax is narrated in the body only -> a finding, never conversion
    assert c["asserted_uncited"] == ["driver_slice:russia_export_tax_quota"]
    assert c["body_hits"] == 2
    assert c["per_source"]["silver:silver_psd"] == {"width_basis": None, "cited": False, "body": False}


def test_conversion_context_markers_are_an_and_gate():
    txt = "**Why.** An export tax was announced.\n\n## Sources\n[1] Src: An export tax was announced."
    assert pj.count_conversion(txt, _ENTRIES)["cited_hits"] == 0        # no russia context -> no hit
    txt2 = txt.replace("An export tax", "Russia's export tax")
    assert pj.count_conversion(txt2, _ENTRIES)["cited_hits"] == 1


def test_conversion_matching_is_normalized():
    """ex._normalize folds accents and collapses hyphens/underscores, so the deck's markers match the
    prose the answers actually write (a tilde-n 'La Nina', 'stocks-to-use' vs 'stocks to use')."""
    ent = [{"key": "driver_slice:la_nina", "markers": ["la nina"]},
           {"key": "driver_slice:wasde_stocks_to_use", "markers": ["stocks to use"]}]
    txt = "body\n\n## Sources\n[1] Src: La Ni\u00f1a cut the crop and stocks-to-use fell."
    c = pj.count_conversion(txt, ent)
    assert c["cited_hits"] == 2


def test_source_label_markers_survive_the_footers_punctuation():
    """The footer renders 'USDA FAS GAIN Report (em-dash) Cotton (monthly) (2025-12-02)'. ex._normalize
    drops the em-dash and collapses separators but KEEPS parentheses, so the deck's one label-separable
    beyond-reach family has to be written '(monthly)' -- a marker of 'cotton monthly' silently never
    fires and the row would measure nothing."""
    footer = "b\n\n## Sources\n[4] USDA FAS GAIN Report \u2014 Cotton (monthly) (2025-12-02): HTBT cotton."
    ent = [e for r in pj.load_checklists(_CHECKS)["rows"] if r["id"] == "dv_vintage_india_cotton"
           for e in r["beyond_quick_sources"] if e["key"] == "source:usda_gain_cotton_monthly"]
    assert pj.count_conversion(footer, ent)["cited_hits"] == 1


def test_conversion_on_an_answer_with_no_sources_block():
    """A proxy-provenance answer (raw_draft fields) has no footer -- the counter must say so rather than
    silently score the body as cited."""
    c = pj.count_conversion("**TL;DR.** India's export ban stands.", _ENTRIES)
    assert c["has_sources_block"] is False and c["cited_hits"] == 0 and c["body_hits"] == 1
    assert c["asserted_uncited"] == ["driver_slice:export_ban"]


def test_split_sources_block_matches_evals_own_cut():
    body, srcs = pj.split_sources_block(_ANSWER)
    assert body == gev._prose({"answer": _ANSWER})                      # eval._prose cuts on the same regex
    assert srcs.startswith("\n[1] USDA")


# -- 5. the call shape (still no API) --------------------------------------------------------------
def test_judge_pair_pins_model_no_temperature_and_blind_labels():
    seen = {}

    def fake_call(client, system, user, *, model, max_tokens, tool, temperature=None):
        seen.update(system=system, user=user, model=model, tool=tool, temperature=temperature)
        return {"usefulness": "ANSWER_2"}, None

    items = [{"id": "rank_every_exporter", "ask": "Does it rank every exporter?"}]
    v, _ = pj.judge_pair("Q?", "2026-08-06", "TEXT ONE", "TEXT TWO", items, call=fake_call)
    assert seen["model"] == pj.MODEL == "claude-opus-4-8"
    # temperature must NOT be sent: claude-opus-4-8 rejects it with a 400 (measured 2026-08-07)
    assert seen["temperature"] is None
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "QUANTITATIVE RESEARCHER" in seen["system"][0]["text"]
    assert "composition_completeness" in seen["system"][0]["text"]
    # blindness: neutral labels only, no arm/mode word anywhere in the user turn
    assert "=== ANSWER 1 ===" in seen["user"] and "=== ANSWER 2 ===" in seen["user"]
    for banned in ("arm a", "arm b", "quick", "deep_v2", "baseline"):
        assert banned not in seen["user"].lower()
    assert "rank_every_exporter: Does it rank every exporter?" in seen["user"]
    t = seen["tool"]
    assert t["name"] == "pairwise_verdict"
    for ax in pj.AXES:
        assert t["input_schema"]["properties"][ax]["enum"] == ["ANSWER_1", "ANSWER_2", "tie"]
        assert ax in t["input_schema"]["required"] and f"{ax}_rationale" in t["input_schema"]["required"]
    assert "checklist" in t["input_schema"]["required"]
    assert v["usefulness"] == "ANSWER_2"


def test_tool_omits_checklist_when_a_row_has_no_items():
    t = pj._pairwise_tool([])
    assert "checklist" not in t["input_schema"]["properties"]
    assert "checklist" not in t["input_schema"]["required"]


# -- 6. reports + the dry-run CLI path -------------------------------------------------------------
def _results() -> list[dict]:
    return [
        {"id": "r1", "order": {"first": "A", "second": "B"}, "provenance": {"A": "report_md", "B": "report_md"},
         "verdicts": {"usefulness": {"winner": "B", "rationale": "wider"},
                      "grounding": {"winner": "tie", "rationale": "same"},
                      "composition_completeness": {"winner": "B", "rationale": "ranked all"}},
         "checklist": [{"item_id": "i1", "A": False, "B": True}, {"item_id": "i2", "A": True, "B": True}],
         "conversion": {"A": {"cited_hits": 1, "n_documented": 4, "asserted_uncited": ["x"],
                              "has_sources_block": False},
                        "B": {"cited_hits": 3, "n_documented": 4, "asserted_uncited": [],
                              "has_sources_block": True}}},
        {"id": "r2", "order": {"first": "B", "second": "A"}, "provenance": {"A": "raw_fields", "B": "raw_fields"},
         "verdicts": {"usefulness": {"winner": "A", "rationale": "tighter"},
                      "grounding": {"winner": "A", "rationale": "handles"},
                      "composition_completeness": {"winner": "tie", "rationale": "both thin"}},
         "checklist": [{"item_id": "i1", "A": True, "B": False}],
         "conversion": {"A": {"cited_hits": 2, "n_documented": 3, "asserted_uncited": [],
                              "has_sources_block": True},
                        "B": {"cited_hits": 2, "n_documented": 3, "asserted_uncited": ["y"],
                              "has_sources_block": True}}},
    ]


def test_report_tallies_rates_and_ascii_md():
    rep = pj.build_report(_results(), arms={"A": {"path": "a.json"}, "B": {"path": "b.json"}},
                          deck="eval_queries_deepv2_width_v1", checklist_version="deepv2_width_v1",
                          model=pj.MODEL, salt=pj._ORDER_SALT)
    assert rep["totals"]["usefulness"] == {"A": 1, "B": 1, "tie": 0}
    assert rep["totals"]["composition_completeness"] == {"A": 0, "B": 1, "tie": 1}
    assert rep["checklist"]["A"] == {"passed": 2, "answered": 3, "pass_rate": round(2 / 3, 4)}
    assert rep["checklist"]["B"] == {"passed": 2, "answered": 3, "pass_rate": round(2 / 3, 4)}
    assert rep["conversion"]["A"]["cited_hits"] == 3 and rep["conversion"]["B"]["cited_hits"] == 5
    assert rep["conversion"]["rows_arm_ahead"] == {"A": 0, "B": 1}
    # a row that rendered no cited-sources footer is counted, never read as failed conversion
    assert rep["conversion"]["A"]["rows_without_sources_block"] == 1
    assert rep["conversion"]["B"]["rows_without_sources_block"] == 0
    assert rep["order_balance"] == {"A": 1, "B": 1}
    assert [o["first"] for o in rep["order_log"]] == ["A", "B"]
    md = pj.report_md(rep)
    assert md.isascii()                                                 # cp1252 console law
    assert "Presentation order + answer-text provenance" in md and "raw_fields" in md
    assert "LEXICAL PROXY" in md and "| NONE |" in md


def test_dry_run_cli_plans_every_row_without_an_api_call(tmp_path, monkeypatch, capsys):
    """--dry-run must reach the plan and stop: any client construction here would raise (no key set)."""
    monkeypatch.delenv("ANTHROPIC_API", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ids = [str(q["id"]) for q in gev.load_queries(_DECK)]
    base = {"kind": "baseline_single", "eval_set": "eval_queries_deepv2_width_v1", "mode": "quick",
            "per_answer": [{"id": i, "raw_draft": {"tldr": f"t {i}", "mechanism": f"m {i}"}} for i in ids]}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(base), encoding="utf-8")
    b.write_text(json.dumps({**base, "mode": "deep_v2"}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["pairwise_judge", "--a", str(a), "--b", str(b),
                                     "--queries", str(_DECK), "--checklists", str(_CHECKS),
                                     "--out", str(tmp_path / "rep"), "--dry-run"])
    assert pj.main() == 0
    outp = capsys.readouterr().out
    assert "PAIRWISE DRY RUN -- no API calls, no spend" in outp
    for i in ids:
        assert f"{i}: shows " in outp
    assert "via raw_fields" in outp and "WARN A: PROXY" in outp     # proxy provenance is surfaced, loudly
    assert f"{len(ids)} rows x 1 claude-opus-4-8 call" in outp
    assert not (tmp_path / "rep.json").exists()                     # dry-run writes nothing


def test_run_rows_maps_verdicts_and_checklist_back_onto_the_arms(capsys):
    """End to end through the row loop with a stubbed call: on a B-FIRST row, ANSWER_1 must credit B and
    the item's answer_1 must land on B -- the one place a blind can silently invert a whole measurement."""
    plan = [{"id": "r_bfirst", "question": "Q1", "asof": "2026-08-06",
             "order": {"first": "B", "second": "A"},
             "text": {"A": "a body\n\n## Sources\n[1] Src: an export ban was extended.",
                      "B": "b body\n\n## Sources\n[1] Src: nothing relevant."},
             "provenance": {"A": "report_md", "B": "report_md"},
             "items": [{"id": "i1", "ask": "?"}, {"id": "i2", "ask": "?"}],
             "beyond_quick_sources": [{"key": "driver_slice:export_ban", "markers": ["export ban"]}],
             "width_class": "W1_seed"},
            {"id": "r_boom", "question": "Q2", "asof": None, "order": {"first": "A", "second": "B"},
             "text": {"A": "x", "B": "y"}, "provenance": {"A": "raw_fields", "B": "raw_fields"},
             "items": [], "beyond_quick_sources": [], "width_class": None}]

    calls = {"n": 0}

    def fake_call(client, system, user, *, model, max_tokens, tool, temperature=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("provider 529")
        return ({"usefulness": "ANSWER_1", "usefulness_rationale": "r1",
                 "grounding": "tie", "grounding_rationale": "r2",
                 "composition_completeness": "ANSWER_2", "composition_completeness_rationale": "r3",
                 "checklist": [{"item_id": "i1", "answer_1": True, "answer_2": False,
                                "evidence_1": "e1", "evidence_2": "e2"},
                               {"item_id": "not_an_item", "answer_1": True, "answer_2": True}]},
                None)

    res = pj.run_rows(plan, call=fake_call)
    assert len(res) == 2
    r = res[0]
    assert r["verdicts"]["usefulness"]["winner"] == "B"            # ANSWER_1 on a B-first row
    assert r["verdicts"]["composition_completeness"]["winner"] == "A"
    assert r["verdicts"]["grounding"]["winner"] == "tie"
    assert r["checklist"] == [{"item_id": "i1", "B": True, "A": False,
                               "evidence_B": "e1", "evidence_A": "e2"}]   # fabricated item dropped
    assert r["missing_items"] == ["i2"]
    # the deterministic counter is computed outside the judge call, so it survives a failed row
    assert r["conversion"]["A"]["cited_hits"] == 1 and r["conversion"]["B"]["cited_hits"] == 0
    boom = res[1]
    assert boom["error"].startswith("provider 529") and boom["verdicts"] == {}
    assert boom["conversion"]["A"]["n_documented"] == 0
    assert "WARN pairwise r_boom failed" in capsys.readouterr().out


def test_cli_refuses_a_checklist_that_does_not_match_the_deck(tmp_path, monkeypatch):
    bad = tmp_path / "bad.yaml"
    bad.write_text("checklist_version: v\ndeck: d\nrows:\n  - id: nope\n    items: []\n", encoding="utf-8")
    base = {"per_answer": []}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(base), encoding="utf-8")
    b.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["pairwise_judge", "--a", str(a), "--b", str(b),
                                     "--queries", str(_DECK), "--checklists", str(bad),
                                     "--out", str(tmp_path / "rep")])
    with pytest.raises(SystemExit):
        pj.main()
