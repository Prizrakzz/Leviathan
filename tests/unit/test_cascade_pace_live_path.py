"""T2a P4 -- the LIVE-SHAPED pace-leg regression (PACE_REALIZATION_PLAN P4, P1 outcome (c)).

Every prior pace test drove the FIXTURE entry (cq._node_specs / cq._pace_legs / cq.quantify with
hand-built nodes that CARRY dated evidence). The live gap that slipped through: export_pace is a
WAIVERED numbers-lane driver with NO text slice, so ground() leaves it prior-only (planner._fill:
"no slice -> prior-only node"), _derive_windows returns [] -- and quantify's eras gate killed the
node BEFORE _node_specs ever saw the pace kwarg. quantify_pace was structurally ABSENT on every
live turn while the cascade fired via evidence-backed nodes, and no fixture test could catch it.

This test drives the REAL answer.py entry (an.answer -> _answer_l2 -> the cq.quantify seam with
the omit-when-off _pace_kw dict) with mocked call/retrieve/embed/qfn but the GENUINE walk ->
ground -> quantify chain, and a deliberately UNBACKED pace driver -- the exact live node shape:

  * flag ON  -> the dark `leg_mode: current` esr_exports node reaches _node_specs, fires its
               current + pace legs, and trace.quantify_pace is PRESENT with minted [N] rows;
  * flag OFF -> byte-identical to the pre-fix path: the dark node is skipped whole, no pace key.

Reads the real tracked cascade_map.yaml (the test_cascade `load_map()` convention); the
driver-slice backing is monkeypatched at the ev seam (driver_slices.yaml is a gitignored
config), pinning `export_pace` unbacked and `export_ban` backed deterministically."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g

ASOF = "2026-07-12"
# esr_pace_corn_2026's text (the deck's veteran row): the phrasing that grounds the export_pace
# driver -- the discriminator the P1 probe pinned.
QUESTION = ("US corn exports feel like they are running hot -- how does the current weekly "
            "export pace sit against the balance-sheet record?")


def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(
        contract="corn_cbot", aliases=["corn"],
        drivers=[
            # the REAL live driver shape (configs/graphrag/causal/corn_cbot.yaml `export_pace`):
            # numbers-lane state marker, esr_exports silver_ref, US region, NO text slice.
            cs.Driver(id="export_pace", type="state_marker", sign="+", region="US",
                      target_metric="price", silver_ref="esr_exports", silver_status="available",
                      mechanism=("Strong U.S. export sales/shipment pace draws down stocks and "
                                 "supports price; lagging pace pressures it.")),
            # an evidence-BACKED balance-sheet driver so the cascade also fires the way the live
            # G5 run did (rows minted off text-grounded nodes while the pace node died dark).
            cs.Driver(id="export_ban", type="policy_event", sign="+", region="US",
                      silver_ref="export", silver_status="available",
                      mechanism="Export restrictions elsewhere shift world demand to US supply."),
        ])
    return g.CausalGraph({"corn_cbot": corn}, silver=set())


def _fake_embed(texts, **k):
    out = []
    for t in texts:
        tl = (t or "").lower()
        if "export" in tl and "pace" in tl:
            out.append([1.0, 0.0])                    # the pace ask ~ the export_pace mechanism
        elif "export" in tl:
            out.append([0.8, 0.6])                    # export_ban: relevant, kept by the walk
        else:
            out.append([0.0, 1.0])
    return out


def _fake_retrieve(q, node, *, k=5, asof=None, near=None):
    return [{"date": "2025-10-05", "source": "usda_gain", "source_key": f"s3://{node}/1",
             "text": f"{node} export note"},
            {"date": "2025-10-20", "source": "usda_gain", "source_key": f"s3://{node}/2",
             "text": f"{node} follow-up"}]


def _fake_call(system, user, *, model, tool):
    return {"tldr": "observed", "mechanism": "record", "sources": []}


def _qfn(sql):
    """SQL-text-keyed stub (the test_cascade convention): ESR agg=latest -> the freshest week;
    ESR agg=series -> 4 ascending weekly totals (change +20, 3-week up-streak); PSD -> one MY row."""
    s = sql.lower()
    if "silver_esr" in s or "week_ending_date" in s:
        if "desc" in s and "limit 1" in s:
            return [{"value": "742.5", "week_ending_date": "2026-07-05"}]
        return [{"value": str(500.0 + 20 * i), "week_ending_date": f"2026-06-{7 + 7 * i:02d}"}
                for i in range(4)]
    return [{"value": "10000000", "market_year": 2009}]


def _wire(monkeypatch):
    """The live seams, pinned: real answer->walk->ground->quantify code, hermetic I/O."""
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(ev, "embed", _fake_embed)
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(slv, "_primary_country", lambda c: "united_states")
    # driver-slice backing at the ev seam: export_pace UNBACKED (the live waivered shape --
    # ground() must leave it prior-only), export_ban backed (its slice is its own id).
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: {"export_ban"})
    monkeypatch.setattr(ev, "slice_for_driver", lambda did: did if did == "export_ban" else None)


def _run():
    return an.answer(QUESTION, graph=_graph(), planner="l2", asof=ASOF, retrieve=_fake_retrieve,
                     call=_fake_call, numbers_lookup=_qfn, route_fn=lambda q, gr: ["corn_cbot"])


def test_live_path_pace_leg_fires_on_dark_current_node_when_flag_on(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_CASCADE_PACE_LEG", "on")
    out = _run()
    tr = out["trace"]
    # the live precondition that killed the leg: the pace driver grounded DARK (prior-only).
    legs = {tuple(d["key"][1:]): d for d in tr["driver_legs"]}
    ep = legs[("corn_cbot", "export_pace")]
    assert ep["dark"] is True and ep["n_evidence"] == 0
    # the cascade fired BEYOND the pace node (the G5 shape: evidence-backed rows minted)...
    qkeys = [tuple(t["node_key"]) for t in (tr.get("quantify") or [])]
    assert ("corn_cbot", "export_ban") in qkeys
    # ...AND the dark `leg_mode: current` node now reaches _node_specs and fires its current leg.
    assert ("corn_cbot", "export_pace") in qkeys
    esr = next(t for t in tr["quantify"] if tuple(t["node_key"]) == ("corn_cbot", "export_pace"))
    assert esr["current_status"] == "ok" and esr["era_statuses"] == {}
    # THE regression pin: quantify_pace PRESENT with the deterministic streak/change entry.
    pace = tr.get("quantify_pace")
    assert pace == [{"node_key": ["corn_cbot", "export_pace"], "table": "silver_esr",
                     "metric": "weekly_exports_1000mt", "grain": "week", "n_points": 4,
                     "streak": 3, "window_change": 20.0, "streak_direction": "up"}]
    assert "quantify_error" not in tr


def test_live_path_flag_off_stays_byte_identical_no_pace_no_esr_node(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_CASCADE_PACE_LEG", raising=False)   # default OFF, fail-closed
    out = _run()
    tr = out["trace"]
    assert "quantify_pace" not in tr                                 # absent, not null
    qkeys = [tuple(t["node_key"]) for t in (tr.get("quantify") or [])]
    assert ("corn_cbot", "export_pace") not in qkeys                 # the dark node skips whole
    assert ("corn_cbot", "export_ban") in qkeys                      # the cascade itself unchanged


def test_live_path_flag_on_injects_exactly_three_extra_rows(monkeypatch):
    """[N]-row accounting across the seam: ON adds EXACTLY the ESR current row + the two pace
    synth rows (change + streak) over the OFF arm -- nothing else moves (no era legs exist for a
    `leg_mode: current` node, so no delta/pct/divergence rows can ride in)."""
    _wire(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_CASCADE_PACE_LEG", raising=False)
    n_off = _run()["trace"]["injected_n"]
    monkeypatch.setenv("GRAPHRAG_CASCADE_PACE_LEG", "on")
    n_on = _run()["trace"]["injected_n"]
    assert n_on == n_off + 3


# ── A6 / F3 -- DarkRefNodes gets a WRITER ────────────────────────────────────────────────────────────
# `orchestrator.py` reads `trace['quantify_dark_refs']` and emits DarkRefNodes -- "the metric this entire
# plan is about" -- and the cascade stamped nothing, so the counter was permanently None and absent from
# every EMF line while the orchestrator test pinned the READER against a hand-authored trace. This drives
# the real seam with an UNMAPPED silver_ref and asserts the key.
def _dark_graph() -> g.CausalGraph:
    corn = cs.CausalContract(
        contract="corn_cbot", aliases=["corn"],
        drivers=[
            # `stage_precip_z` is one of the plan's own dark refs: 38 driver instances and NO gold metric
            # exists to bind it (C3 refused it with an Athena probe). A grounded node on it is exactly the
            # shape the counter is for -- the walk had a driver and the record had no series.
            cs.Driver(id="excess_rain", type="weather", sign="+", region="US",
                      silver_ref="stage_precip_z", silver_status="available",
                      mechanism="Excess rain at a critical stage cuts yield and supports price."),
            cs.Driver(id="export_ban", type="policy_event", sign="+", region="US",
                      silver_ref="export", silver_status="available",
                      mechanism="Export restrictions elsewhere shift world demand to US supply."),
        ])
    return g.CausalGraph({"corn_cbot": corn}, silver=set())


def _dark_embed(texts, **k):
    return [[1.0, 0.0] if "export" in (t or "").lower() else [0.9, 0.1] for t in texts]


def test_live_path_stamps_quantify_dark_refs_for_an_unmapped_grounded_ref(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(ev, "embed", _dark_embed)
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: {"export_ban", "excess_rain"})
    monkeypatch.setattr(ev, "slice_for_driver", lambda did: did)
    out = an.answer(QUESTION, graph=_dark_graph(), planner="l2", asof=ASOF, retrieve=_fake_retrieve,
                    call=_fake_call, numbers_lookup=_qfn, route_fn=lambda q, gr: ["corn_cbot"])
    tr = out["trace"]
    assert tr.get("quantify_dark_refs") == 1                 # the unmapped stage_precip_z node
    qkeys = [tuple(t["node_key"]) for t in (tr.get("quantify") or [])]
    assert ("corn_cbot", "export_ban") in qkeys               # ... and the mapped leg still fired
    assert ("corn_cbot", "excess_rain") not in qkeys


def test_a_fully_mapped_turn_stamps_zero_rather_than_omitting_the_key(monkeypatch):
    """0 is a MEASUREMENT, not an absence: the orchestrator distinguishes 'this turn quantified and found
    no dark ref' (0) from 'this turn never quantified' (key absent, metric omitted). Stamping only
    non-zero counts would make every healthy turn look like a numbers_only turn."""
    _wire(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_CASCADE_PACE_LEG", "on")
    assert _run()["trace"].get("quantify_dark_refs") == 0


def test_the_dark_count_survives_the_all_dark_early_return(monkeypatch):
    """THE shape the counter exists for -- a turn where EVERY grounded ref is dark -- takes quantify's
    `not groups` early return. Stamping after that return would blind the metric on exactly the turns it
    was built to see."""
    _wire(monkeypatch)
    monkeypatch.setattr(ev, "embed", _dark_embed)
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: {"export_ban", "excess_rain"})
    monkeypatch.setattr(ev, "slice_for_driver", lambda did: did)
    monkeypatch.setattr("leviathan.graphrag.numbers.cascade.load_map", lambda: {})
    out = an.answer(QUESTION, graph=_dark_graph(), planner="l2", asof=ASOF, retrieve=_fake_retrieve,
                    call=_fake_call, numbers_lookup=_qfn, route_fn=lambda q, gr: ["corn_cbot"])
    tr = out["trace"]
    assert tr.get("quantify_dark_refs") == 2                 # both grounded refs, none mapped
    assert not tr.get("quantify")                            # and nothing quantified


# ── A2b / F6 -- the headline rule is FLAGGED and threaded from the seam ──────────────────────────────
def test_headline_flag_is_read_at_the_seam_and_threaded_not_env_read(monkeypatch):
    """The flag lives at the answer.py quantify seam and reaches the engine as an ARGUMENT (the
    _pace_leg_on / price_request discipline): cascade.py reads no environment, so a mis-plumbed enable
    cannot fire it. Default OFF -- A2b's own rule is "defaulting to today's behaviour"."""
    from leviathan.graphrag.numbers import cascade as cq
    _wire(monkeypatch)
    seen: dict = {}
    real = cq.quantify

    def _spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(cq, "quantify", _spy)
    monkeypatch.delenv("GRAPHRAG_CASCADE_HEADLINE", raising=False)
    _run()
    assert "headline" not in seen and cq._HEADLINE_ON is False        # omit-when-off, and OFF is OFF
    monkeypatch.setenv("GRAPHRAG_CASCADE_HEADLINE", "on")
    _run()
    assert seen.get("headline") is True and cq._HEADLINE_ON is True
    cq._set_headline(False)                                          # leave the module as we found it
