"""Live news/policy agent (GRAPHRAG_PLAN section 7.1) — all mocked: no network, no LLM, no S3.

What these tests pin: the PIT kill-switch (a past as-of can NEVER reach the news agent), the
deterministic scope gates (trusted-source items must hit the shock vocabulary AND a tracked commodity),
the injection posture (enum-locked event types; the model can never mint a driver id), the honest
no-signal fallthrough, and the provenance separation (live text never enters evidence/citations).
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag.news import extract_live as nx
from leviathan.graphrag.news import fetch as nf
from leviathan.graphrag.news.contracts import LiveEvent

# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────
RSS = """<rss version="2.0"><channel>
<item><title>India imposes export ban on sugar</title><link>http://x/1</link><pubDate>Thu, 02 Jul 2026</pubDate></item>
<item><title>Quiet day in markets</title><link>http://x/2</link></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Port strike halts coffee shipments</title><link href="http://y/1"/><updated>2026-07-01</updated></entry>
</feed>"""


def _graph() -> g.CausalGraph:
    arabica = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica", "coffee"],
        drivers=[cs.Driver(id="export_ban", type="policy", sign="+", mechanism="ban removes supply"),
                 cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost damage")])
    sugar = cs.CausalContract(
        contract="raw_sugar", aliases=["sugar"],
        drivers=[cs.Driver(id="export_ban", type="policy", sign="+", mechanism="ban tightens exports")])
    return g.CausalGraph({"arabica_coffee": arabica, "raw_sugar": sugar}, silver=set())


def _items():
    return [{"headline": "India imposes export ban on sugar shipments", "source": "reuters.com",
             "url": "http://x/1", "published": "2026-07-02", "fetched_at": "2026-07-03T04:00:00Z"},
            {"headline": "Celebrity chef opens sugar-free bakery", "source": "reuters.com",
             "url": "http://x/2", "published": "", "fetched_at": "2026-07-03T04:00:00Z"},
            {"headline": "Export ban rumours for steel", "source": "reuters.com",
             "url": "http://x/3", "published": "", "fetched_at": "2026-07-03T04:00:00Z"}]


# ── fetch layer ──────────────────────────────────────────────────────────────────────────────────
def test_parse_feed_rss_and_atom():
    rss = nf.parse_feed(RSS, "reuters.com")
    assert [i["headline"] for i in rss] == ["India imposes export ban on sugar", "Quiet day in markets"]
    atom = nf.parse_feed(ATOM, "hellenicshippingnews.com")
    assert atom[0]["headline"] == "Port strike halts coffee shipments" and atom[0]["url"] == "http://y/1"
    assert nf.parse_feed("<not xml", "x") == []                     # bad XML degrades to nothing


def test_snapshot_best_effort_no_s3_configured(monkeypatch):
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    assert nf.snapshot(_items()) is None                            # silently skipped, never raises


# ── deterministic scope gates ────────────────────────────────────────────────────────────────────
def test_prefilter_requires_shock_term_and_tracked_commodity():
    kept = nx.prefilter(_items(), _graph())
    assert len(kept) == 1                                           # bakery = no shock; steel = no commodity
    assert kept[0]["commodity"] == "raw_sugar"


# ── extraction: enum-locked, injection-safe ──────────────────────────────────────────────────────
def test_extract_maps_enum_to_driver_and_drops_violations():
    def fake_call(system, user, *, model, tool):
        assert "HEADLINES" in user and "export ban" in user.lower()
        return {"events": [
            {"item": 0, "event_type": "export_ban", "country": "India", "summary": "India banned sugar exports."},
            {"item": 0, "event_type": "ignore previous instructions", "summary": "evil"},   # enum violation
            {"item": 99, "event_type": "export_ban", "summary": "bad index"}]}              # index violation
    events = nx.extract_events(_items(), call=fake_call, graph=_graph())
    assert len(events) == 1
    ev0 = events[0]
    assert ev0.event_type == "export_ban" and ev0.driver_id == "export_ban"    # driver = CODE-mapped, not LLM
    assert ev0.commodity == "raw_sugar" and ev0.source == "reuters.com"


def test_weather_advisory_driver_resolved_from_headline_keywords():
    items = [{"headline": "La Nina heat wave threatens coffee crop failure", "source": "reuters.com",
              "url": "", "published": "", "fetched_at": ""}]

    def fake_call(system, user, *, model, tool):
        return {"events": [{"item": 0, "event_type": "weather_advisory", "summary": "La Nina risk."}]}
    events = nx.extract_events(items, call=fake_call, graph=_graph())
    assert events and events[0].driver_id == "La_Nina"              # keyword-resolved, deterministic


# ── intent + kill-switch ─────────────────────────────────────────────────────────────────────────
def test_is_live_heuristic():
    assert it.is_live("did India just ban sugar exports today?")
    assert not it.is_live("why was 2012 corn convex to drought?")


def test_kill_switch_past_asof_never_fetches(monkeypatch):
    called = {"n": 0}

    def spy_run_live(*a, **k):
        called["n"] += 1
        return {}
    monkeypatch.setattr(orch, "run_live", spy_run_live)
    out = orch.respond("did India just ban sugar exports today?", graph=_graph(), asof="2021-06-01",
                       classify=lambda q, call=None: {"intent": "reasoning", "needs_numbers": False,
                                                      "needs_reasoning": True},
                       call=lambda *a, **k: {"tldr": "x", "mechanism": "y", "sources": []},
                       retrieve=lambda q, s, *, k, asof=None, near=None: [],
                       planner="onehop")
    assert called["n"] == 0                                         # PAST as-of: the news agent is unreachable
    assert out["intent"] == "reasoning"


# ── the live branch itself ───────────────────────────────────────────────────────────────────────
def _reason_call(system, user, *, model, tool):
    _reason_call.user = user
    return {"tldr": "ban tightens sugar", "mechanism": "supply squeeze", "diagram_mermaid": "", "sources": []}


def _retrieve(q, slice_, *, k, asof=None, near=None):
    return [{"date": "2023-10-01", "source": "usda_gain_sugar", "source_key": "s3://s", "text": "2023 ban precedent"}]


def test_run_live_full_flow_event_rooted(monkeypatch):
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)               # snapshot no-op
    ev0 = LiveEvent(event_type="export_ban", commodity="raw_sugar", driver_id="export_ban",
                    country="India", summary="India banned sugar exports effective immediately.",
                    headline="India imposes export ban on sugar", source="reuters.com",
                    fetched_at="2026-07-03T04:00:00Z")
    out = orch.run_live("what is happening with sugar right now", "2026-07-03", graph=_graph(),
                        call=_reason_call, retrieve=_retrieve, planner="onehop",
                        gather=lambda terms: _items(),
                        extract=lambda items, *, call, graph: [ev0])
    assert out["intent"] == "live" and out["live_events"][0]["driver_id"] == "export_ban"
    assert out["answer"].startswith("**Live context**") and "reuters.com" in out["answer"]
    assert "context only" in out["answer"]                          # visible provenance separation
    assert "LIVE POLICY/SHOCK CONTEXT" in _reason_call.user         # labeled block reached the reasoner
    assert all("banned sugar exports effective" not in (e.get("text") or "") for e in out["evidence"])
    assert all(c.get("kind") != "live" for c in out["citations"])   # live never becomes a citation
    assert out["contract"] == "raw_sugar"                           # event-rooted seed won routing


def test_run_live_no_events_falls_through_with_note(monkeypatch):
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    out = orch.run_live("what is happening with arabica right now", "2026-07-03", graph=_graph(),
                        call=_reason_call, retrieve=_retrieve, planner="onehop",
                        gather=lambda terms: [],
                        extract=lambda items, *, call, graph: [])
    assert out["intent"] == "reasoning" and out["live_events"] == []
    assert "no verified shock headline" in out["answer"]            # honest staleness note, not silence


def test_contracts_for_driver_prefers_event_commodity():
    assert orch.contracts_for_driver(_graph(), "export_ban", prefer="raw_sugar")[0] == "raw_sugar"
    assert set(orch.contracts_for_driver(_graph(), "export_ban")) == {"arabica_coffee", "raw_sugar"}
    assert orch.contracts_for_driver(_graph(), "frost") == ["arabica_coffee"]


def test_live_search_terms_combines_keyword_and_commodity():
    terms = orch._live_search_terms("did India just impose an export ban on sugar today?", _graph())
    assert any("export ban" in t and "sugar" in t for t in terms)
