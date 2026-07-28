"""graphdev honest eval (GRAPHRAG_PLAN v2 Phase 2 WS-4 / WS-MS5).

Runs configs/graphrag/eval_queries.yaml through answer.answer() and writes a markdown report with a
lightweight auto-rubric (routed-right / expected-drivers-mentioned / regime-named / evidence-cited), an
LLM-judge quality score, and a SOURCE-DIVERSITY panel (distinct sources + trust-tiers cited, trust-ordering,
cross-tier disagreement flagged) — the WS-MS5 multi-source lift. Serving defaults to Sonnet (production),
with an Opus judge. The rubric is approximate — the report + a human read are the real judges.

    python -m leviathan.graphrag.eval --dry-run            # cost estimate, no spend
    python -m leviathan.graphrag.eval --run --model claude-sonnet-4-6
"""
from __future__ import annotations

import argparse

import yaml

from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import register as reg

_QUERIES = ex._CFG / "eval_queries.yaml"
_OUT = ex._CFG / "eval"


def load_queries(path=_QUERIES) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []


_NOT_KNOWN = ("not known", "not yet known", "not yet been", "no data", "not available", "wasn't published",
              "was not published", "not published", "not been published", "unavailable")

# ── P9-AB per-query cascade assertions (the v4 PRIMARY gate) ──────────────────────────────────────────
_DARK_STATUSES = ("not_known", "record_silent", "future_unpublished")
# TRANSMISSION CHAIN: the metric every transmission LEG row carries (cascade._xc_call's synthetic World
# su_ratio call-record -- the links reuse the RV2 pair machinery verbatim, 2.2). Keyed on here so the
# hop-citation counter reads the ENGINE's own row shape and can never count a per-country cascade su_ratio
# row as a transmission leg.
_XMIT_LEG_METRIC = "su_ratio_world"


def _num_citations(out: dict) -> list[dict]:
    return [c for c in (out.get("citations") or []) if c.get("kind") == "number"]


def _cascade_stats(out: dict) -> dict:
    """Deterministic cascade signals: the quantify trace + kind=number citations + POST-verify STRUCTURED
    prose. NEVER scan out['answer'] for handles — the '## Sources' footer re-renders every ledgered [N]
    line INCLUDING ones the verifier just stripped from prose, so the naive scan false-passes on
    fabrications (the primary-gate trap)."""
    tr = (out.get("trace") or {}).get("quantify") or []
    cits = _num_citations(out)
    st = out.get("structured") or {}
    prose = f"{st.get('tldr') or ''} {st.get('mechanism') or ''}"
    cited = [c for c in cits if f"[{c.get('id')}]" in prose]
    statuses: set = set()
    for t in tr:
        for ss in (t.get("era_statuses") or {}).values():
            statuses.update(ss)
        if t.get("current_status"):
            statuses.add(t["current_status"])
    # CHAIN ENGINE (CHAIN_ENGINE_PLAN sec 5.2): quantify_chain is ENGINE-written, present IFF a chain FIRED;
    # an attempted-and-declined chain writes quantify_chain_decline (a reason enum); a no-match turn leaves BOTH
    # absent. chain_fired = the pace_fired idiom (bool of the trace key). n_chain_hops_cited = the count of
    # DISTINCT chain-hop metrics the model actually CITED (base metric, _delta/_pct suffix stripped) -- the
    # min_chain_hops_cited pin (observational, flag+data-dependent, so a TRUE pin is calibrated live, D9).
    chain_tr = (out.get("trace") or {}).get("quantify_chain") or {}
    chain_dec = (out.get("trace") or {}).get("quantify_chain_decline") or {}
    chain_hop_metrics = {h.get("metric") for h in (chain_tr.get("hops") or [])
                         if h.get("metric") and "collapsed_into" not in h}

    def _base_metric(loc) -> str:
        mm = str((loc or {}).get("metric") or "")
        for suf in ("_delta", "_pct"):
            if mm.endswith(suf):
                mm = mm[:-len(suf)]
        return mm
    cited_chain_metrics = {_base_metric(c.get("locator")) for c in cited
                           if _base_metric(c.get("locator")) in chain_hop_metrics}
    # TRANSMISSION CHAIN (TRANSMISSION_CHAIN_PLAN sec 3.1/6.1): the HORIZONTAL engine's own keys -- DISTINCT
    # key, SHARED shape (3.1), so the T2b ledger reads both chain engines uniformly. quantify_transmission is
    # ENGINE-written IFF a transmission chain FIRED; an attempted-and-declined chain writes
    # quantify_transmission_decline (the vertical enum verbatim + the horizontal-only `link_comove`, 3.2); a
    # no-match turn leaves BOTH absent. transmission_fired = the chain_fired/pace_fired idiom.
    # n_transmission_hops_cited counts the LINKS whose BOTH legs' World su_ratio [N] rows the model actually
    # CITED. The link is the horizontal analogue of the vertical hop, but the vertical's DISTINCT-METRIC key
    # cannot be reused: every link carries the SAME metric (`su_ratio_world`, cascade._xc_call) on a World
    # basis, so a metric-keyed count collapses a 2-link chain to 1. The leg COMMODITY is the discriminator, and
    # BOTH endpoints must be cited -- a link is "cited" only when its rendered pair of legs is, so a shared hub
    # can never credit a downstream link the model never narrated.
    xmit_tr = (out.get("trace") or {}).get("quantify_transmission") or {}
    xmit_dec = (out.get("trace") or {}).get("quantify_transmission_decline") or {}
    cited_xmit_legs = {str((c.get("locator") or {}).get("commodity") or "") for c in cited
                       if str((c.get("locator") or {}).get("metric") or "") == _XMIT_LEG_METRIC} - {""}
    n_xmit_links_cited = sum(1 for lk in (xmit_tr.get("links") or [])
                             if {str((lk or {}).get("source") or ""),
                                 str((lk or {}).get("target") or "")} <= cited_xmit_legs)
    return {"fired": bool(tr), "n_rows": len(cits), "n_cited": len(cited),
            "chain_fired": bool(chain_tr), "chain_decline_reason": chain_dec.get("reason"),
            "n_chain_hops_cited": len(cited_chain_metrics),
            "transmission_fired": bool(xmit_tr),
            "transmission_decline_reason": xmit_dec.get("reason"),
            "n_transmission_hops_cited": n_xmit_links_cited,
            "cited_ids": [c.get("id") for c in cited],
            "divergence_nodes": sum(1 for t in tr if t.get("divergence")),
            # RF-5: quantify_reroute carries FIRED (opposite-sign) pairs ONLY -- same-sign candidates
            # record nothing, so this count never legitimizes a hallucinated fork heading.
            "reroute_pairs": len((out.get("trace") or {}).get("quantify_reroute") or []),
            # RV-v2 (C11): quantify_reroute_v2 is ENGINE-written, non-empty IFF the cross-commodity fork
            # FIRED this turn (never the orchestrator enable). The negative-pin battery asserts it EMPTY.
            "reroute_v2_pairs": len((out.get("trace") or {}).get("quantify_reroute_v2") or []),
            # SEAM A [SKEPTIC F7]: BOOLEAN semantics -- quantify_comove is ENGINE-written, present IFF a
            # complex-wide co-move rendered this turn. NOT a len() count (a co-move fires at most one pair/era):
            # the fired dict has ~13 keys, so len() would mislead a future exact-count assert -- bool() is honest.
            "comove_fired": bool((out.get("trace") or {}).get("quantify_comove")),
            # SEAM B (F2): quantify_price_leg is ENGINE-written, present IFF a settled farm-price pair rendered
            # this turn. BOOLEAN (mirror comove_fired [F7]) -- the fired dict has ~8 keys, so len() would mislead
            # a future exact-count assert. Judge-free soak/attribution signal; the deck pins ride price_cited /
            # unit_present (citation-based), not this stat.
            "price_leg_fired": bool((out.get("trace") or {}).get("quantify_price_leg")),
            # T2a (CONVERGENCE_TIER1): quantify_pace is ENGINE-written, non-empty IFF >=1 deterministic
            # streak/window_change pace row was emitted this turn. BOOLEAN (mirror comove_fired/
            # price_leg_fired [F7]) -- an honest decline (<2 points / annual grain / flag off) leaves the
            # key absent, so the negative pins read false, never KeyError.
            "pace_fired": bool((out.get("trace") or {}).get("quantify_pace")),
            # T2B pattern-records ledger signal (run_numbers_only copies answer_numbers' `pattern_records`
            # key onto the trace). injected>=1 iff the scalar-presence leg was injected; recorded_firings is
            # the cited COUNT; zero_materialized is the F8 honesty firing (a citable 0 was injected). The
            # pins read these the pace_fired way -- an absent key reads 0/False, never KeyError.
            "pattern_injected": int(((out.get("trace") or {}).get("pattern_records") or {}).get("injected") or 0),
            "pattern_recorded_firings": int(((out.get("trace") or {}).get("pattern_records")
                                             or {}).get("recorded_firings") or 0),
            "pattern_zero_materialized": bool(((out.get("trace") or {}).get("pattern_records")
                                               or {}).get("zero_materialized")),
            "statuses": sorted(statuses)}


def _pit_clean(out: dict, asof) -> bool:
    """PIT invariants over every injected number row: leg asof <= session asof; date windows ('t1..t2'
    period labels) end <= asof; MY labels bounded by the COVERING MY of asof (an MY window legitimately
    extends past asof — the window-end rule must NOT apply to 'MY<yyyy>' labels); provenance release_date
    <= the leg's own asof."""
    if not asof:
        return True
    import re as _re

    from leviathan.graphrag.numbers import cascade as _casc
    for c in _num_citations(out):
        loc = c.get("locator") or {}
        leg_asof = str(loc.get("asof") or "")
        if leg_asof and leg_asof > str(asof):
            return False
        per = str(loc.get("period") or "")
        if ".." in per and per.split("..")[-1] > str(asof):
            return False
        m = _re.fullmatch(r"MY(\d{4})", per)
        if m:
            cover = _casc._covering_my(str(asof), str(loc.get("commodity") or ""))
            if cover is not None and int(m.group(1)) > cover:
                return False
        rows = (c.get("payload") or {}).get("rows") or []
        prov = (rows[0] or {}).get("_provenance") if rows else None
        rd = str((prov or {}).get("release_date") or "")
        if rd and leg_asof and rd > leg_asof:
            return False
    return True


_CASCADE_EXPECT = ("cascade_fired", "min_cascade_cited", "delta_row", "fork", "absence",
                   "pit_clean", "su_prescaled", "ok_era_leg", "reroute_fired",
                   "opposite_country_legs", "two_countries_cited", "no_unbacked_fork",
                   "reroute_v2_expected", "detection_tier", "comove_expected", "pace_expected",
                   # CHAIN ENGINE (sec 6.1): multi-hop quantified-cascade pins. chain_fired (boolean; the
                   # negative pin is the realizable teeth -- an engine-dark chain MUST stay false),
                   # min_chain_hops_cited (>= N distinct chain-hop metrics cited; observational), and
                   # chain_decline_reason (the reasoned-decline enum / 'absent' for the negative rows).
                   "chain_fired", "min_chain_hops_cited", "chain_decline_reason",
                   # TRANSMISSION CHAIN (sec 6.1): the HORIZONTAL siblings. transmission_fired (boolean; the
                   # negative pin is the realizable teeth -- feed_grain is engine-dark BY DESIGN, D3),
                   # min_transmission_hops_cited (>= N links whose BOTH legs were cited; CALIBRATION-GATED --
                   # the per-link natures are window-contingent, fold-pass finding 2), and
                   # transmission_decline_reason (the shared decline enum + the horizontal-only `link_comove`,
                   # which is the reached-not-yet PAYOFF, not a failure -- 3.2/D4).
                   "transmission_fired", "min_transmission_hops_cited", "transmission_decline_reason",
                   # W3.6 price-observability pins: level-citation + unit discipline on the price tables,
                   # the NONE-tier decline guard, and the RAW (pre-sanitize, DP-6) valuation/flow/mismatch
                   # trace counters the bait + PIT + honesty rows assert to 0.
                   "price_cited", "unit_present", "price_decline_guard",
                   "banned_valuation", "banned_flow", "numbers_mismatched",
                   # T2B pattern-records pins (plan 6.1 / D12): pattern_cited (a backfill ENGINE base-rate
                   # [N] was injected + a real firing count cited), pattern_zero_cited (the F8 mechanism -- a
                   # materialized 0-count leg was injected and cited; FAILS if the card injects NOTHING), and
                   # pattern_register_clean (no signal/set-up/regime/trend/breakout/persistent on the answer).
                   "pattern_cited", "pattern_zero_cited", "pattern_register_clean")


def _cascade_asserts(q: dict, out: dict) -> dict | None:
    """The v4 per-query deterministic checks, keyed by expect.* (None when the query asserts none —
    every v3 query). Each value is the PASS boolean for that key."""
    exp = q.get("expect") or {}
    keys = [k for k in _CASCADE_EXPECT if k in exp]
    if not keys:
        return None
    cs = _cascade_stats(out)
    cits = _num_citations(out)
    mech = str((out.get("structured") or {}).get("mechanism") or "")
    tr = (out.get("trace") or {}).get("quantify") or []
    res: dict = {}
    for k in keys:
        want = exp[k]
        if k == "cascade_fired":
            res[k] = cs["fired"] == bool(want)
        elif k == "min_cascade_cited":
            res[k] = cs["n_cited"] >= int(want)
        elif k == "delta_row":
            got = any(str((c.get("locator") or {}).get("metric") or "").endswith("_delta") for c in cits)
            res[k] = got == bool(want)
        elif k == "fork":
            # RF-5 guard widening: a REROUTE render is a legitimate fork (pair-level -- neither node
            # carries divergence=True), so a fired reroute must not score as a hallucinated heading.
            fired = cs["divergence_nodes"] > 0 or cs["reroute_pairs"] > 0
            heading = "## Where the record disagrees" in mech
            # ONE-DIRECTIONAL text rule: a rendered fork heading without a trace fork is always a FAIL;
            # the converse (trace fork, no heading) is LLM-mediated and judged, not gated here.
            res[k] = (fired == bool(want)) and not (heading and not fired)
        elif k == "no_unbacked_fork":
            # PREMISE-CORRECTION alignment guard (retrieval-ROBUST half of the `fork` rule): a rendered
            # '## Where the record disagrees' heading with NO trace fork is a MODEL-manufactured
            # contradiction and always FAILS. Firing-direction is NOT pinned (doctrine: boolean pins on
            # retrieval-derived selection are brittle) -- a genuine data-true fork legitimately renders
            # the heading and PASSES. This is the deterministic teeth behind "never manufacture a
            # contradiction"; the premise being addressed correctly is judged + observational, not gated.
            fired = cs["divergence_nodes"] > 0 or cs["reroute_pairs"] > 0
            heading = "## Where the record disagrees" in mech
            res[k] = (not (heading and not fired)) if bool(want) else True
        elif k == "reroute_fired":
            res[k] = (cs["reroute_pairs"] > 0) == bool(want)
        elif k == "reroute_v2_expected":
            # RV-W4.5. The NEGATIVE pin is the load-bearing gate (single-commodity / pronoun follow-up /
            # context-mention MUST NOT fire); the positive pin is observational (firing depends on the focus
            # leg's retrieval-derived eras, so a boolean true-pin FLAPS -- C10/gating F3). Both branches also
            # require the dispatch planner actually ran: a p.fallback turn skips the v2 predicate entirely, so
            # a negative pin would false-green without ever exercising it (C11c). planner=='llm' == non-fallback.
            fired_v2 = cs["reroute_v2_pairs"] > 0
            heading = "## Cross-commodity" in mech
            non_fallback = ((out.get("intent_decision") or {}).get("planner")) == "llm"
            if bool(want):
                res[k] = fired_v2 and heading and non_fallback
            else:
                res[k] = (not fired_v2) and (not heading) and non_fallback
        elif k == "comove_expected":
            # SEAM A: mirrors reroute_v2_expected. The POSITIVE pin is observational (a co-move fires only when
            # the focus leg's retrieval-derived eras yield two SAME-sign World deltas AND no era diverges, so a
            # boolean true-pin FLAPS -- keep it non-load-bearing). The NEGATIVE pin is the realizable teeth
            # [SKEPTIC F2]: a pair with one leg absent from the era intersection renders NO co-move -> assert
            # comove_fired false + no '## Complex-wide move' heading. Both branches require the dispatch planner
            # actually ran (planner=='llm' == non-fallback) so a fallback turn can't false-green the pin.
            fired_cm = cs["comove_fired"]
            heading = "## Complex-wide move" in mech
            non_fallback = ((out.get("intent_decision") or {}).get("planner")) == "llm"
            if bool(want):
                res[k] = fired_cm and heading and non_fallback
            else:
                res[k] = (not fired_cm) and (not heading) and non_fallback
        elif k == "pace_expected":
            # T2a: trace-only boolean pin. quantify_pace is ENGINE-written, present IFF a deterministic
            # pace row (streak/window_change) rendered; pace has NO reserved heading (the [N] rows ride
            # the cascade block), so there is no heading half to gate. The NEGATIVE branches are the
            # realizable teeth (annual/MY grain and <2-point declines MUST leave the key absent); the
            # positive pin is flag-gated + data-dependent -> observational.
            res[k] = cs["pace_fired"] == bool(want)
        elif k == "chain_fired":
            # CHAIN ENGINE (sec 5.2/6.1): trace-only boolean pin (the pace_fired idiom). quantify_chain is
            # ENGINE-written IFF a chain fired; a no-match / declined turn leaves it absent -> false, never
            # KeyError. The NEGATIVE branch is the realizable teeth (an engine-dark chain, e.g. the SA-maize
            # IOD ask that matches NO v1 chain, MUST stay false); the positive is flag-gated + data-dependent.
            res[k] = cs["chain_fired"] == bool(want)
        elif k == "min_chain_hops_cited":
            # >= N DISTINCT chain-hop metrics actually cited in the STRUCTURED prose (observational: firing +
            # citing both depend on the turn, so this rides the ON arm and is calibrated against the live probe).
            res[k] = cs["n_chain_hops_cited"] >= int(want)
        elif k == "chain_decline_reason":
            # The reasoned-decline enum pin (D7). `want` is a reason string OR a list of accepted reasons;
            # the token 'absent' (or a literal null in the list) accepts NO decline key -- a no-match or a
            # FIRED turn. The negative row pins [absent, root_not_grounded]: an IOD ask engine-dark BY DESIGN.
            allowed = list(want) if isinstance(want, (list, tuple)) else [want]
            got = cs["chain_decline_reason"]
            res[k] = (got in allowed) or (got is None and ("absent" in allowed or None in allowed))
        elif k == "transmission_fired":
            # TRANSMISSION CHAIN (5.2/6.1): trace-only boolean pin (the chain_fired idiom). quantify_transmission
            # is ENGINE-written IFF a horizontal chain fired; a no-match / declined turn leaves it absent ->
            # false, never KeyError. The NEGATIVE branch is the realizable teeth (the corn/wheat feed ask matches
            # NO v1 chain -- feed_grain is a deg-1 isolated edge, D3 -- and MUST stay false); the positive is
            # flag-gated + data-dependent, and on the OFF arm it is the byte-identity assertion made
            # deterministic (flag absent -> the engine cannot write the key, so the pin cannot flap).
            res[k] = cs["transmission_fired"] == bool(want)
        elif k == "min_transmission_hops_cited":
            # >= N LINKS whose BOTH legs' World su_ratio [N] rows are cited in the STRUCTURED prose. CALIBRATION-
            # GATED (6.1, fold-pass finding 2): which links render divergence vs co-move is WINDOW-contingent, so
            # this rides the ON arm at a probe-verified asof and is re-calibrated against the live probe before
            # any flip. It never pins a link's NATURE -- only that the link was rendered AND cited.
            res[k] = cs["n_transmission_hops_cited"] >= int(want)
        elif k == "transmission_decline_reason":
            # The reasoned-decline enum pin (3.2/D7), same shape as chain_decline_reason: `want` is a reason
            # string OR a list; 'absent' (or a literal null) accepts NO decline key -- a no-match or a FIRED
            # turn. `link_comove` is an HONEST outcome (a co-move hub ended the divergence chain = the
            # reached-not-yet payoff, D4), never a failure, so rows legitimately accept [absent, link_comove].
            # It lands HERE when the co-move ends the chain at its HEAD link (nothing rendered upstream, so the
            # composer declines whole); when an upstream link already rendered, the chain FIRES and link_comove
            # rides the fired trace's `stop_reason` instead -> this key reads 'absent'. Either way the pin's
            # teeth hold: it FAILS a genuine hop_dark / hop_thin / cap / degenerate / error decline.
            allowed = list(want) if isinstance(want, (list, tuple)) else [want]
            got = cs["transmission_decline_reason"]
            res[k] = (got in allowed) or (got is None and ("absent" in allowed or None in allowed))
        elif k == "detection_tier":
            # RV2 W2 (D15 amended): the tier pin requires the dispatch planner ACTUALLY ran (the same C11c
            # fallback-vacuity guard as reroute_v2_expected) AND the stamped tier to match -- a fallback,
            # flag-off, or non-orchestrator out (answer.answer() has no intent_decision) yields False,
            # never KeyError. Meaningful only on --via-orchestrator runs by construction.
            dec = out.get("intent_decision") or {}
            res[k] = (dec.get("planner") == "llm") and ((dec.get("xc_detect") or {}).get("tier") == want)
        elif k == "opposite_country_legs":                            # the STRONG reroute assert: >=2
            pos, neg = set(), set()                                   # distinct countries whose injected
            for c in cits:                                            # *_delta rows carry OPPOSITE signs
                loc = c.get("locator") or {}
                if not (str(loc.get("metric") or "").endswith("_delta") and loc.get("country")):
                    continue
                try:
                    v = float(str(c.get("value")).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if v > 0:
                    pos.add(loc["country"])
                elif v < 0:
                    neg.add(loc["country"])
            got = bool(pos and neg and len(pos | neg) >= 2)
            res[k] = got == bool(want)
        elif k == "two_countries_cited":                              # cheap wiring canary (locator count)
            n_c = len({(c.get("locator") or {}).get("country") for c in cits} - {None, ""})
            res[k] = n_c >= int(want)
        elif k == "absence":
            res[k] = any(s in _DARK_STATUSES for s in cs["statuses"]) == bool(want)
        elif k == "pit_clean":
            res[k] = _pit_clean(out, q.get("asof")) == bool(want)
        elif k == "su_prescaled":
            lv = [c for c in cits if (c.get("locator") or {}).get("metric") == "su_ratio"]  # LEVELS only:
            try:                                                      # _delta/_pct rows are signed changes
                res[k] = bool(lv) and all(float(c["value"]) > 1 for c in lv if c.get("value") is not None)
            except (TypeError, ValueError):
                res[k] = False
        elif k == "ok_era_leg":                                       # anti-vacuity (pit backtest): >=1 era
            got = any(s == "ok" for t in tr                           # leg actually resolved a value
                      for ss in (t.get("era_statuses") or {}).values() for s in ss)
            res[k] = got == bool(want)
        elif k in ("price_cited", "unit_present"):
            # W3.6: PRICE-TABLE level discipline -- clone of the su_prescaled model (:192) but filtering on
            # locator.table (the price lanes) instead of a metric name. price_cited = at least one kind=number
            # citation resolves through a price table; unit_present = every such price citation carries a
            # non-empty unit (the USD/mt discipline).
            # A3 (2026-07-22): silver_wasde is BACK in the filter set -- the restoration wave re-whitelisted
            # avg_farm_price (silver_wasde rebuilt + promoted), so a WASDE farm-price citation (carrying a
            # per-commodity unit_override: $/bu, c/lb, $/cwt, $/s.t.) now legitimately satisfies price_cited /
            # unit_present, and the corn honesty row is a SERVED price row (not a decline).
            # SEAM C (2026-07-23): silver_futures_prices whitelisted -- a served front-month settle citation
            # (exchange units: c/bu, c/lb, USD/short ton, USD/metric ton, USD/cwt per the 12-slug unit_overrides)
            # now legitimately satisfies price_cited / unit_present too.
            # NEWCAP TRIAGE (2026-07-24): gate on value is not None -- a levels_only PIT-guard raise is
            # surfaced as a kind=number citation with value=None + empty unit ('(lookup error)'), and
            # counting those failed unit_present on SERVED-correct rows and scored a correct futures
            # decline as a price leak (3 flagship-futures rows). Rejected probes are not price citations.
            pc = [c for c in cits if (c.get("locator") or {}).get("table") in ("silver_pink_sheet", "silver_wasde", "silver_futures_prices")
                  and c.get("value") is not None]
            if k == "price_cited":
                res[k] = bool(pc) == bool(want)
            else:                                                     # unit_present
                res[k] = (bool(pc) and all((c.get("unit") or "").strip() for c in pc)) == bool(want)
        elif k == "price_decline_guard":                              # NONE-tier decline: trace-key equality to
            res[k] = ((out.get("trace") or {}).get("price_decline_guard")) == want   # the guard slug (agent.py:412)
        elif k == "banned_valuation":                                 # RAW DP-6 counter (pre-sanitize), the bait/
            res[k] = int((out.get("trace") or {}).get("banned_valuation_words") or 0) == int(want)   # honesty gate
        elif k == "banned_flow":                                      # RAW DP-6 counter (pre-sanitize)
            res[k] = int((out.get("trace") or {}).get("banned_flow_words") or 0) == int(want)
        elif k == "numbers_mismatched":                               # _verify_numbers_answer mismatch tally
            nv = (out.get("trace") or {}).get("numbers_verifier") or {}   # (orchestrator.py:75); absent -> 0
            res[k] = int(nv.get("mismatched", 0)) == int(want)
        elif k == "pattern_cited":                                    # T2B: a real ledger base-rate [N] injected
            res[k] = (cs["pattern_injected"] >= 1 and cs["pattern_recorded_firings"] > 0) == bool(want)
        elif k == "pattern_zero_cited":                               # T2B F8: a materialized-0 leg injected +
            res[k] = (cs["pattern_injected"] >= 1 and cs["pattern_zero_materialized"]) == bool(want)   # cited
        elif k == "pattern_register_clean":                           # T2B D8: no banned pattern-vocab in prose
            from leviathan.graphrag.numbers import pattern_records as _pr
            _txt = f"{(out.get('structured') or {}).get('tldr') or ''} {mech} {out.get('answer') or ''}"
            res[k] = (len(_pr.pr_register_leaks(_txt)) == 0) == bool(want)
    return res


def score(q: dict, out: dict) -> dict:
    """Approximate auto-rubric + v3 routing/point-in-time checks (expected_intent, leakage-trap)."""
    exp = q.get("expect") or {}
    ans = ex._normalize(out.get("answer") or "")
    drivers = exp.get("drivers") or []
    hit = [d for d in drivers if ex._normalize(d) in ans]
    exp_intent, routed_intent = q.get("expected_intent"), out.get("intent")
    leakage_ok = None
    if exp.get("not_known"):                                          # trap: the tool must SAY the value isn't known at asof
        leakage_ok = any(p in (out.get("answer") or "").lower() for p in _NOT_KNOWN)
    return {"routed_right": out.get("contract") == q["contract"],
            "intent_ok": (routed_intent == exp_intent) if exp_intent else None,
            "routed_intent": routed_intent, "expected_intent": exp_intent, "leakage_ok": leakage_ok,
            "drivers_hit": f"{len(hit)}/{len(drivers)}", "drivers_missed": [d for d in drivers if d not in hit],
            "regime_named": (ex._normalize(exp["regime"]) in ans) if exp.get("regime") else None,
            "evidence_cited": (len(out.get("evidence") or []) > 0) if exp.get("needs_evidence") else None,
            "cascade_asserts": _cascade_asserts(q, out)}


# ── E-W2: unfreezable + unlosable harness (per-turn watchdog, incremental JSONL, heartbeat) ───────────
def _turn_deadline(deadline: float | None = None) -> float:
    """Per-turn wall-clock ceiling. env GRAPHRAG_EVAL_TURN_DEADLINE (default 4200s = 70min) MUST exceed the
    ~3932s two-serial-call legal worst case so it never false-fires a healthy heavy turn (plan S2.4/AV3)."""
    import os as _os
    if deadline is not None:
        return float(deadline)
    return float(_os.environ.get("GRAPHRAG_EVAL_TURN_DEADLINE", "4200") or 4200)


def _timeout_row(q: dict, deadline: float) -> dict:
    """The row a watchdog fire records for a stalled turn -- SAME shape as run()'s except-branch row so
    _metrics / _baseline_json / report all treat it as a normal answered-with-error row. AV2:
    trace['degraded_model'] MUST be set so §4.4's transient policy counts a mid-transient watchdog kill as
    RETRY-TRANSIENT, not a code/quality failure; trace['error'] keeps the two causes distinguishable."""
    out = {"answer": f"(turn watchdog timeout at {deadline:.0f}s)", "contract": None, "structured": None,
           "evidence": [], "intent": None, "number_calls": [], "citations": [], "model": None,
           "trace": {"error": "watchdog_timeout", "degraded_model": "(watchdog_timeout)"}}
    return {"q": q, "out": out, "rubric": score(q, out), "secs": deadline}


def _per_answer_record(r: dict, run_kind: str) -> dict:
    """The per-answer baseline/JSONL record for ONE row -- the SINGLE source of truth so the incremental
    partial JSONL (_persist_partial) is byte-identical to the final _baseline_json per_answer entries
    (zero drift). run_kind 'single'|'convos' selects the id + intent_ok source."""
    out = r.get("out") or {}
    v = ((out.get("trace") or {}).get("citation_verifier")) or {}
    if run_kind == "convos":
        rid = f"{r.get('convo')}/{r.get('turn')}"                # convo rows have no single query id
        intent_ok = (r.get("mech") or {}).get("intent_ok")
    else:
        rid = str((r.get("q") or {}).get("id"))
        intent_ok = (r.get("rubric") or {}).get("intent_ok")
    j = r.get("judge") or {}
    cs = _cascade_stats(out)                                     # P9-AB: post-run-readable cascade record
    return {"id": rid,
            "strips": v.get("stripped", 0),
            "claim_count": v.get("claim_count", 0),
            "handles_checked": v.get("checked", 0),
            "by_rule": v.get("by_rule") or {},
            # W3 RCA: stripped-sentence audit rides the baseline ONLY when GRAPHRAG_STRIP_AUDIT is on
            # (verify omits the key when off) -- the per-turn text the by_rule counts can't give.
            "strip_audit": v.get("strip_audit") or None,
            "register_leaks": len(reg.register_leaks(str(out.get("answer") or ""))),
            "banned_mood_words": (out.get("trace") or {}).get("banned_mood_words", 0),
            "mechanism_scaffold_ok": _scaffold_ok(out),
            "n_sections": len((out.get("structured") or {}).get("sections") or []),   # P9-C derived view
            "intent": out.get("intent"),
            "intent_ok": intent_ok,
            "secs": r.get("secs"),
            "cascade_fired": cs["fired"],
            "n_cascade_rows": cs["n_rows"],
            "n_cascade_cited": cs["n_cited"],
            "divergence_nodes": cs["divergence_nodes"],
            "reroute_pairs": cs["reroute_pairs"],
            # RV2 W2 (D15): the v2 fork count + the detecting tier ride every record so a soak/eval readout
            # can attribute fires per tier post-run; None on non-orchestrator rows (no intent_decision).
            "reroute_v2_pairs": cs["reroute_v2_pairs"],
            "comove_fired": cs["comove_fired"],                # SEAM A boolean (F7): per-tier soak attribution
            "price_leg_fired": cs["price_leg_fired"],          # SEAM B boolean: settled farm-price pair rendered
            "pace_fired": cs["pace_fired"],                    # T2a boolean: deterministic pace row rendered
            "chain_fired": cs["chain_fired"],                  # CHAIN boolean: a multi-hop chain fired this turn
            "chain_decline_reason": cs["chain_decline_reason"],  # the reasoned-decline enum (D7 soak signal)
            # TRANSMISSION booleans ride the SAME record shape (3.1) so the T2b ledger + soak scans read the
            # vertical and horizontal chain engines uniformly, and `link_comove` (an HONEST reached-not-yet
            # truncation) stays distinguishable from a genuine dark/thin decline.
            "transmission_fired": cs["transmission_fired"],
            "transmission_decline_reason": cs["transmission_decline_reason"],
            "detection_tier": ((out.get("intent_decision") or {}).get("xc_detect") or {}).get("tier"),
            "cascade_asserts": (r.get("rubric") or {}).get("cascade_asserts"),
            # R3 F12: without degraded_model in the record a degraded turn is byte-indistinguishable from a
            # clean one and the transient-error policy is un-enforceable (set at answer.py:663,960; a
            # watchdog fire sets '(watchdog_timeout)'). Single highest-leverage gate-ENABLING line.
            "degraded_model": (out.get("trace") or {}).get("degraded_model"),
            "judge": {k: j[k] for k in ("usefulness", "convexity", "point_in_time", "grounding",
                                        "source_diversity", "continuity", "mechanism_voice")
                      if k in j} or None}


def _partial_path(eval_set: str, provider: str, *, judge: bool = False):
    """Stable (non-ts) partial-JSONL path so a KILLED run is findable + reconstructable; overwritten once at
    run start: partial_{eval_set}_{provider}.jsonl (judge=True -> partial_judge_{eval_set}_{provider}.jsonl,
    the AV5 sidecar that keeps every judge score across a kill during judging)."""
    stem = f"partial_judge_{eval_set}_{provider}.jsonl" if judge else f"partial_{eval_set}_{provider}.jsonl"
    return _OUT / stem


def _partial_s3_key(eval_set: str, provider: str, *, judge: bool = False) -> str | None:
    """s3://<EVIDENCE_S3>/eval/partial_... for the optional every-N durable mirror; None when EVIDENCE_S3 unset."""
    s3uri = ev._evid_s3()
    if not s3uri:
        return None
    return s3uri.rstrip("/") + "/eval/" + _partial_path(eval_set, provider, judge=judge).name


def _persist_partial(row: dict, handle, run_kind: str) -> None:
    """Append ONE per-answer record to the OPEN partial handle and flush immediately. Main-thread only (no
    lock). AV1: flush() pushes Python->OS and the OS page cache survives process death, so a kill -9 (exit
    137 -- the actual incident signal) leaves a readable partial; the handle is opened buffering=1 too (belt
    and braces). os.fsync is NOT needed (a process kill, not a host/kernel crash, is the threat model)."""
    import json as _json
    handle.write(_json.dumps(_per_answer_record(row, run_kind)) + "\n")
    handle.flush()


class _PartialWriter:
    """Owns the stable partial-JSONL handle for one run. main() opens it once, passes __call__ as the
    `persist` hook into run()/the judge drain, and flush+closes it immediately before os._exit(0) -- os._exit
    does NOT run TextIOWrapper.close(), so the buffered tail would truncate even on the clean path (AV1)."""

    def __init__(self, path, run_kind: str, *, s3_key: str | None = None, s3_every: int = 4):
        self.path = path
        self.run_kind = run_kind
        self._s3_key = s3_key
        self._s3_every = s3_every
        self._n = 0
        _OUT.mkdir(parents=True, exist_ok=True)
        self._h = open(path, "w", buffering=1, encoding="utf-8")    # line-buffered text mode (belt to flush's braces)

    def __call__(self, row: dict) -> None:
        _persist_partial(row, self._h, self.run_kind)
        self._n += 1
        if self._s3_key and self._n % self._s3_every == 0:          # optional durable mirror of the WHOLE jsonl
            try:
                import boto3
                b, k = ev._parse_s3(self._s3_key)
                boto3.client("s3").put_object(Bucket=b, Key=k, Body=self.path.read_bytes())
            except Exception as e:  # noqa: BLE001 -- a mirror failure must NEVER break the run
                print(f"  WARN partial S3 mirror failed -- {str(e)[:120]}", flush=True)

    def close(self) -> None:
        try:
            self._h.flush()
            self._h.close()
        except Exception:  # noqa: BLE001
            pass


def _drain(futs: dict, started: dict, *, ids: list, n: int, deadline: float, heartbeat_period: float,
           workers: int, on_complete, on_timeout, label: str = "turn") -> None:
    """Explicit-futures MAIN-THREAD drain shared by the answer phase (run) and the judge phase (AV5). Wakes
    on each completion OR every heartbeat_period; hands completed units to on_complete(idx, fut) and
    watchdog-orphans any in-flight unit whose turn (measured from `started[idx]` -- turn START, not
    submission) has run past `deadline`, handing it to on_timeout(idx). Python threads can't be force-killed,
    so an orphaned worker keeps grinding its read-timeout-bounded ladder and holds a slot; the
    LIVE-WORKER-FLOOR guard prints WATCHDOG-STALL when every slot is orphaned (the VOID signal). A daemon
    heartbeat (lock-free reads of started + the answered counter) makes silence diagnosable in real time."""
    import threading
    import time as _t
    from concurrent.futures import FIRST_COMPLETED
    from concurrent.futures import wait as _wait
    pending = set(futs)
    answered = [0]
    stop = threading.Event()

    def _heartbeat():                                              # daemon=True -> never blocks exit
        while not stop.wait(heartbeat_period):
            snap = dict(started)                                   # snapshot: lock-free, GIL-atomic
            now = _t.monotonic()
            qids = [ids[i] for i in sorted(snap)]
            oldest = max((now - s for s in snap.values()), default=0.0)
            print(f"heartbeat: n_answered={answered[0]}/{n} in_flight={qids} "
                  f"oldest_in_flight_secs={oldest:.0f}", flush=True)
    threading.Thread(target=_heartbeat, daemon=True).start()
    orphaned = 0
    stall_since = None
    try:
        while pending:
            done, pending = _wait(pending, timeout=heartbeat_period, return_when=FIRST_COMPLETED)
            for f in done:
                idx = futs[f]
                try:
                    on_complete(idx, f)
                except Exception as e:  # noqa: BLE001 -- one bad drain callback must not abort the run
                    print(f"  WARN drain {label} {ids[idx]}: {str(e)[:120]}", flush=True)
                answered[0] += 1
            now = _t.monotonic()
            for f in list(pending):
                idx = futs[f]
                st = started.get(idx)
                if st is not None and now - st > deadline:        # measured from turn START (plan S3.1)
                    on_timeout(idx)
                    answered[0] += 1
                    pending.discard(f)                            # orphan the thread; do NOT join
                    orphaned += 1
                    print(f"  WATCHDOG {ids[idx]}: {label} exceeded {deadline:.0f}s -- orphaning worker, "
                          f"recording timeout row", flush=True)
            live = sum(1 for f in pending if futs[f] in started)  # non-orphaned units actually running
            if pending and live == 0 and orphaned >= workers:     # every slot held by an orphan
                if stall_since is None:
                    stall_since = now
                elif now - stall_since > heartbeat_period:        # sustained > one heartbeat -> the VOID signal
                    print("WATCHDOG-STALL: all workers orphaned", flush=True)
                    stall_since = now                             # re-arm: repeat each heartbeat, don't spam within one
            else:
                stall_since = None
    finally:
        stop.set()


def run(graph: gph.CausalGraph, queries: list[dict], *, model: str = an.SONNET, k: int = 5, answer_fn=None,
        via_orchestrator: bool = False, numbers_client=None, call=None, planner: str | None = None,
        workers: int = 1, persist=None, deadline: float | None = None,
        heartbeat_period: float = 90.0) -> list[dict]:
    """Run each query through answer() (default) or — with via_orchestrator — the full intent branch
    orchestrator.respond() (numbers_only / reasoning / hybrid), passing each question's point-in-time asof.
    `planner='l2'` routes reasoning/hybrid through the deterministic grounded-subgraph walk (A/B vs one-hop).
    `workers>1` answers independent questions concurrently — the per-question chain is dominated by LLM
    network waits, so threads cut wall-clock ~workers-fold at identical API cost (psycopg3 connections,
    torch inference and the Anthropic client are all thread-safe). Row order always matches `queries`.

    E-W2: the concurrent path drains explicit futures on the MAIN thread (not pool.map) so a per-turn
    wall-clock watchdog (`deadline`, env GRAPHRAG_EVAL_TURN_DEADLINE) can record a `_timeout_row` for a
    stalled turn and continue, `persist(row)` can write an incremental partial JSONL as each turn lands, and
    a heartbeat makes silence diagnosable. `persist` is called on the MAIN thread only (no lock)."""
    answer_fn = answer_fn or an.answer
    import time as _time
    deadline = _turn_deadline(deadline)
    started: dict[int, float] = {}                                     # idx -> turn-START monotonic; watchdog reads it
    qfn = None
    if via_orchestrator:                                              # P9-AB G1: eval passes call=_call_opus, so the
        from leviathan.graphrag.numbers import query as Qn            # orchestrator NEVER builds a default qfn
        qfn = Qn.default_query_fn()                                   # (state None + call not None) and the cascade
                                                                      # seam is silently dead without this thread
    def _one(idx: int, q: dict) -> dict:
        t0 = _time.monotonic()
        started[idx] = t0                                             # publish turn START for the watchdog/heartbeat
        try:                                                          # one bad answer must NOT abort a billed run
            try:
                if via_orchestrator:
                    from leviathan.graphrag import orchestrator as orch
                    okw = dict(graph=graph, asof=q.get("asof"), model=model, numbers_client=numbers_client,
                               call=call, query_fn=qfn)
                    if planner:                                       # keep the call identical for injected fake respond()
                        okw["planner"] = planner
                    out = orch.respond(q["question"], **okw)
                else:
                    kw = dict(graph=graph, model=model, k=k, asof=q.get("asof"), near=q.get("near"))
                    if planner:                                       # keep the call identical for injected fake answer_fns
                        kw["planner"] = planner
                    out = answer_fn(q["question"], **kw)
                print(f"  answered {q.get('id')} in {_time.monotonic() - t0:.0f}s", flush=True)
            except Exception as e:  # noqa: BLE001
                out = {"answer": f"(answer failed: {str(e)[:200]})", "contract": None, "structured": None,
                       "evidence": [], "intent": None, "number_calls": [], "citations": [], "model": model,
                       "trace": {"error": str(e)[:300]}}
                print(f"  WARN {q.get('id')}: answer failed -- {str(e)[:120]}", flush=True)
            return {"q": q, "out": out, "rubric": score(q, out), "secs": round(_time.monotonic() - t0, 1)}
        finally:
            started.pop(idx, None)                                    # pop on return so the watchdog stops tracking it

    if workers <= 1:                                                  # sequential: persist per turn, no watchdog needed
        rows = []
        for idx, q in enumerate(queries):
            row = _one(idx, q)
            rows.append(row)
            if persist is not None:
                persist(row)
        return rows

    from concurrent.futures import ThreadPoolExecutor
    results: list = [None] * len(queries)                            # index-keyed so row order matches `queries`
    ids = [str(q.get("id")) for q in queries]
    pool = ThreadPoolExecutor(max_workers=workers)
    futs = {pool.submit(_one, idx, q): idx for idx, q in enumerate(queries)}

    def _complete(idx: int, fut) -> None:                            # MAIN thread
        row = fut.result()                                           # _one swallows its own exceptions -> never raises
        results[idx] = row
        if persist is not None:
            persist(row)

    def _timeout(idx: int) -> None:                                  # MAIN thread: a watchdog fire
        row = _timeout_row(queries[idx], deadline)
        results[idx] = row
        if persist is not None:
            persist(row)

    _drain(futs, started, ids=ids, n=len(queries), deadline=deadline, heartbeat_period=heartbeat_period,
           workers=workers, on_complete=_complete, on_timeout=_timeout, label="turn")
    pool.shutdown(wait=False)                                        # do NOT block on orphaned worker threads
    return results


# ── LLM-judge: a quant/hedge-fund analyst rates usefulness + exposes gaps ──────────────
def _judge_tool(continuity: bool = False) -> dict:
    n = {"type": "integer"}                                            # 1-5
    arr = {"type": "array", "items": {"type": "string"}}
    props = {"usefulness": n, "convexity": n, "point_in_time": n, "grounding": n, "source_diversity": n,
             "mechanism_voice": n,
             "hallucinations": arr, "gaps": arr, "improvements": arr, "verdict": {"type": "string"}}
    required = ["usefulness", "convexity", "point_in_time", "grounding", "source_diversity", "mechanism_voice",
                "gaps", "verdict"]
    if continuity:                                                     # multi-turn: did it read the conversation right?
        props["continuity"] = n
        required = required + ["continuity"]
    return {"name": "score_answer",
            "description": "A senior quant RESEARCHER's verdict on a fundamental convexity-shock answer.",
            "input_schema": {"type": "object", "properties": props, "required": required}}


_JUDGE_SYS = (
    "You are a SENIOR QUANTITATIVE RESEARCHER pressure-testing a FUNDAMENTAL CONVEXITY-SHOCK research tool (NOT a "
    "trading system). It helps researchers understand HOW supply/demand shocks propagate through commodity balance "
    "sheets and WHERE the price response turns convex (buffer exhaustion, tipping thresholds, regime switches). You "
    "are shown the QUESTION (with any as-of date), the curated causal graph + dated evidence + any OBSERVED NUMBERS "
    "the tool looked up, and the tool's ANSWER. CRITICAL: this is a research tool — do NOT expect or reward position "
    "sizing, price targets, or 'how much to trade'; that is OUT OF SCOPE. Reward mechanism, convexity/regime insight, "
    "point-in-time discipline, and grounding. Be demanding and specific:\n"
    "- usefulness (1-5): does it give a researcher real insight into the shock's STRUCTURE — mechanism, the drivers "
    "that matter, the regime — or is it vague restatement / textbook filler?\n"
    "- convexity (1-5): does it correctly locate WHERE the response is convex vs linear, the buffer/threshold that "
    "makes it tip, and through which channel? 5 = precise convexity mechanism; 1 = ignores convexity or asserts it "
    "with no mechanism. (If the question isn't about convexity, judge the shock-propagation reasoning instead.)\n"
    "- point_in_time (1-5): did it respect the as-of date — use AS-KNOWN values, correctly say a value was 'not "
    "known' when it wasn't yet published, never leak future data? 5 = clean; 1 = leaks/ignores the as-of. If the "
    "question has NO as-of, score 5.\n"
    "- grounding (1-5): are specific claims (drivers, signs, dated observed numbers) backed by the cited evidence, "
    "the looked-up NUMBERS, or the authoritative graph? (Naming the graph's own drivers/regimes/signs is "
    "AUTHORITATIVE, not hallucination.)\n"
    "- source_diversity (1-5): multiple sources across trust tiers (T1 official WASDE/FAS ... T4 macro), "
    "trust-ordered, disagreements flagged? Only high if multiple sources were actually AVAILABLE.\n"
    "- mechanism_voice (1-5): does it name WHAT tightens or loosens the balance sheet and WHY (5), or emit "
    "sign/mood labels and trading-bot verdicts (1)? Penalize 'bullish'/'bearish', price targets, position "
    "sizing. 5 = names the mechanism and its price direction; 1 = a mood/sign label with no mechanism.\n"
    "- hallucinations: any claim/number/sign/date supported by NEITHER the graph, the evidence, NOR the looked-up "
    "numbers.\n"
    "- gaps: what a researcher would still need — a missing propagation channel, no dated evidence, convexity "
    "asserted without a threshold, a missed regime or cross-commodity leg. Concrete.\n"
    "- improvements: concrete changes.\n- verdict: one blunt sentence.\n"
    "Emit via score_answer.")


def _judge_numbers_panel(out: dict, max_rows_per_call: int = 8) -> str:
    """The judge's OBSERVED-NUMBERS panel: EVERY retrieved row of every call, each with its period +
    knowledge date — never rows[0] alone. RCA 2026-07-24 (cocoa false-fabrication): the old first-row-only
    render showed a multi-row grindings series as '= 3727' (the 2007/08 row), so the judge convicted the
    answer's CORRECT latest-row 4628 (2024/25, kd 2026-05-29) as fabricated — grounding 2/5 on a right
    answer, three phantom 'hallucinations'. A narrated figure matching ANY row at its stated period is
    grounded; the panel now says so and shows the rows to check against. Bounded per call so a long
    series cannot blow the judge prompt."""
    lines: list[str] = []
    for c in out.get("number_calls") or []:                          # the observed values the tool actually looked up
        qy, rws = c.get("query", {}), (c.get("rows") or [])
        head = (f"- {qy.get('table')}.{qy.get('metric')} {qy.get('commodity','')} {qy.get('period','')} "
                f"asof {qy.get('asof','')}")
        if not rws:
            lines.append(head + " = (NOT KNOWN at asof)")
        elif len(rws) == 1:
            r = rws[0]
            kd = r.get("knowledge_date")
            lines.append(head + f" = {r.get('value')}" + (f"  [known {kd}]" if kd else ""))
        else:
            lines.append(head + f" -> {len(rws)} rows retrieved (a figure matching ANY row at its period is grounded):")

            def _row_line(r: dict) -> str:
                kd = r.get("knowledge_date")
                return (f"    period={r.get('period', '?')} value={r.get('value')}"
                        + (f" known={kd}" if kd else ""))

            if len(rws) <= max_rows_per_call:
                lines += [_row_line(r) for r in rws]
            else:
                # Tail-biased overflow (cocoa proof-run 2026-07-24): the first head-only bound hid the
                # LATEST rows — exactly the ones answers cite — and the judge downgraded a correct latest-row
                # figure to 'cannot be confirmed'. Answers overwhelmingly cite the most recent rows, so show
                # the first 2 + the last (max-2), and tell the judge hidden rows are UNVERIFIED, not wrong.
                n_tail = max_rows_per_call - 2
                hidden = rws[2:-n_tail]
                lines += [_row_line(r) for r in rws[:2]]
                lines.append(f"    ... +{len(hidden)} middle rows (periods "
                             f"{hidden[0].get('period', '?')}..{hidden[-1].get('period', '?')}) not shown -- "
                             f"a figure claimed for an unshown period is UNVERIFIED here, never 'fabricated'")
                lines += [_row_line(r) for r in rws[-n_tail:]]
    # P9-AB G3: cascade-injected rows never reach number_calls (the seam appends to a COPY) — they live only
    # in citations kind=number. Without this merge the judge's OBSERVED-NUMBERS panel reads '(none)' on a
    # cascade turn and flags every narrated [N] figure as a hallucination. Dedup vs agent rows by locator.
    seen_num = {((c.get("query") or {}).get("table"), (c.get("query") or {}).get("metric"),
                 (c.get("query") or {}).get("period"), (c.get("query") or {}).get("asof"))
                for c in out.get("number_calls") or []}
    for c in out.get("citations") or []:
        if c.get("kind") != "number":
            continue
        loc = c.get("locator") or {}
        if (loc.get("table"), loc.get("metric"), loc.get("period"), loc.get("asof")) in seen_num:
            continue
        lines.append(f"- [{c.get('id')}] {loc.get('table', '')}.{loc.get('metric', '')} "
                     f"{loc.get('commodity', '')} {loc.get('period', '')} asof {loc.get('asof', '')} "
                     f"= {c.get('value')} {c.get('unit') or ''}")
    return "\n".join(lines) + ("\n" if lines else "")


def judge(query: dict, out: dict, *, graph=None, client=None, model: str = "claude-opus-4-8", call=None,
          convo_history: str | None = None) -> dict:
    """The quant-researcher persona scores the answer — shown the SAME graph + evidence + looked-up NUMBERS the tool
    had, so it can tell grounded from invented and check point-in-time discipline. With `convo_history` (multi-turn
    eval) the judge also scores CONTINUITY: did the answer interpret the vague/pronoun follow-up correctly given
    the prior turns, and respect THIS turn's as-of rather than a stale one?"""
    call = call or ex.call_opus
    ctx = ""
    if graph is not None:
        from leviathan.graphrag import answer as an
        ctx = "\n\n".join(an._context_block(graph, c) for c in (out.get("contracts") or [out.get("contract")]) if c)
    ev_text = "\n".join(f"- ({e['source']}, {e['date']}) {e.get('text', '')}" for e in out.get("evidence") or [])
    num_text = _judge_numbers_panel(out)
    convo = ""
    if convo_history is not None:
        convo = (f"=== CONVERSATION SO FAR (prior turns; the current question may be vague/pronoun-based and "
                 f"must be read against these) ===\n{convo_history or '(first turn)'}\n\n"
                 "Also score `continuity` (1-5): 5 = the answer correctly resolved what the user meant from the "
                 "conversation AND respected THIS turn's as-of (not a stale one); 1 = it answered the wrong "
                 "referent, ignored the thread, or dragged stale state in.\n\n")
    user = (convo +
            f"QUESTION: {query['question']}\n"
            f"(as-of date: {query.get('asof') or 'none'}; the tool routed intent={out.get('intent')} to "
            f"{out.get('contracts') or out.get('contract')})\n\n"
            f"=== CAUSAL GRAPH THE TOOL COULD CITE (drivers/signs/regimes here are authoritative) ===\n{ctx}\n\n"
            f"=== DATED EVIDENCE THE TOOL WAS SHOWN ===\n{ev_text or '(none retrieved)'}\n\n"
            f"=== OBSERVED NUMBERS THE TOOL LOOKED UP (as-known at asof; multi-row calls list ALL retrieved "
            f"rows — a narrated figure that matches ANY listed row at its stated period is GROUNDED, not a "
            f"hallucination) ===\n{num_text or '(none)'}\n\n"
            f"=== THE TOOL'S ANSWER ===\n{out.get('answer')}")
    sys_blocks = [{"type": "text", "text": _JUDGE_SYS, "cache_control": {"type": "ephemeral"}}]  # judge calls share it
    scores, _ = call(client, sys_blocks, user, model=model, max_tokens=3200,
                     tool=_judge_tool(continuity=convo_history is not None))  # headroom for adaptive thinking
    # PARSE-TIME normalization (RCA-561): the model occasionally emits a list field as one prose
    # string; unvalidated, len() downstream counted its CHARACTERS (the 561 spike). Coerce at the
    # source so no consumer can ever see a degenerate shape: string -> [string], clip at 16 items.
    for fld in ("hallucinations", "gaps"):
        v = scores.get(fld)
        if isinstance(v, str):
            scores[fld] = [v] if v.strip() else []
        elif isinstance(v, list):
            scores[fld] = [str(x) for x in v][:16]
        elif v is not None:
            scores[fld] = [str(v)]
    return scores


def _metrics(r: dict) -> dict:
    """Per-row metrics for the grounding-depth + source-diversity aggregation."""
    out, j = r["out"], (r.get("judge") or {})
    # P9-A deterministic gates: banned mood words counted PRE-sanitize (the trace field — a post-sanitize scan
    # of out['answer'] would read 0 forever) + the fixed '##' scaffold order check.
    _mood = (out.get("trace") or {}).get("banned_mood_words", 0)
    cited_srcs = [s.get("source") for s in (out.get("structured") or {}).get("sources") or [] if s.get("source")]
    cited_tiers = [an.source_tier(s) for s in cited_srcs]
    ev_srcs = {e.get("source") for e in (out.get("evidence") or []) if e.get("source")}   # actual corpus sources
    ev_tiers = {an.source_tier(s) for s in ev_srcs}
    ans_l = (out.get("answer") or "").lower()
    leaks = reg.register_leaks(out.get("answer") or "")               # internal tokens that leaked into reader prose
    rb = r["rubric"]
    tr = out.get("trace") or {}                                       # L2 planner traversal trace (when planner=l2)
    kept = tr.get("kept") or []
    dkept = [k for k in kept if k and k[0] == "driver"]
    active = tr.get("active") or []
    return {"commodity": r["q"]["contract"], "category": r["q"].get("category", r["q"].get("type", "")),
            "register_leaks": len(leaks), "register_tokens": [t for t, _ in leaks],
            "is_l2": tr.get("planner") == "l2", "n_kept": len(kept),
            "n_contracts": len({k[1] for k in kept}) if kept else 0,
            "n_regimes": len(tr.get("fired_regimes") or []),
            "leg_grounded": (len(active) / len(dkept)) if dkept else None,
            "routed_ok": rb["routed_right"], "retrieved": len(out.get("evidence") or []), "cited": len(cited_srcs),
            # v3 intent-branch + point-in-time
            "intent_ok": rb.get("intent_ok"), "routed_intent": rb.get("routed_intent"),
            "expected_intent": rb.get("expected_intent"), "leakage_ok": rb.get("leakage_ok"),
            "n_numbers": len(out.get("number_calls") or []),
            "n_number_errors": sum(1 for c in (out.get("number_calls") or []) if c.get("status") == "error"),
            # source-diversity / trust-ranking (the multi-source lift)
            "ev_sources": len(ev_srcs), "ev_tiers": len(ev_tiers), "cited_sources": len(set(cited_srcs)),
            "multi_tier": len(ev_tiers) >= 2,                                  # store offered >=2 trust tiers
            "trust_ordered": len(cited_tiers) > 1 and cited_tiers == sorted(cited_tiers),  # most-trusted first
            "disagreement": any(w in ans_l for w in ("disagree", "conflict", "at odds", "contradict", "diverg")),
            "banned_mood_words": _mood, "mechanism_scaffold_ok": _scaffold_ok(out),
            "src_div": j.get("source_diversity"), "mech_voice": j.get("mechanism_voice"),
            "usefulness": j.get("usefulness"), "convexity": j.get("convexity"),
            "point_in_time": j.get("point_in_time"), "grounding": j.get("grounding"),
            "answer_chars": len(out.get("answer") or ""),              # 6.2 conciseness: deterministic length signal
            "halluc": _n_halluc(j), "gaps": j.get("gaps") or []}


_FIXED_SCAFFOLD = ("## Mechanism", "## The record", "## Where the record disagrees", "## What to watch")


def _scaffold_ok(out: dict) -> bool:
    """P9-A deterministic scaffold gate: a non-empty mechanism must OPEN with '## Mechanism' and keep the
    fixed relative order of whichever sections fire. Numbers-only turns (empty mechanism) pass vacuously.
    '##' headings are plain text between sentences, so they survive sanitize unchanged."""
    mech = str((out.get("structured") or {}).get("mechanism") or "")
    if not mech.strip():
        return True
    present = [h for h in _FIXED_SCAFFOLD if h in mech]
    positions = [mech.index(h) for h in present]
    return bool(present) and present[0] == "## Mechanism" and positions == sorted(positions)


def source_report(rows: list[dict]) -> list[str]:
    """The multi-source + trust-ranking lift panel — the WS-MS5 headline (was ~single-tier GAIN pre-fill)."""
    import statistics
    m = [_metrics(r) for r in rows]
    n = len(m) or 1

    def avg(key):
        xs = [x[key] for x in m if x.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None

    return ["## Source diversity + trust-ranking (multi-source lift)", "",
            f"- retrieved distinct **sources** avg **{avg('ev_sources')}** | distinct **trust-tiers** avg **{avg('ev_tiers')}**",
            f"- **multi-tier answers** (store offered >=2 tiers): **{sum(x['multi_tier'] for x in m)}/{n}**",
            f"- cited distinct sources avg {avg('cited_sources')} | **trust-ordered citations** (T1 first): "
            f"{sum(x['trust_ordered'] for x in m)}/{n}",
            f"- **cross-tier disagreement flagged**: {sum(x['disagreement'] for x in m)}/{n}",
            f"- judge **source_diversity** avg: {avg('src_div')}/5",
            f"- judge **mechanism_voice** avg: {avg('mech_voice')}/5"]


def routing_report(rows: list[dict]) -> list[str]:
    """v3 new-layers panel: intent-branch routing accuracy + point-in-time discipline + convexity."""
    import collections
    import statistics
    m = [_metrics(r) for r in rows]

    def avg(key):
        xs = [x[key] for x in m if x.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None

    intent = [x for x in m if x.get("expected_intent")]
    iok = sum(1 for x in intent if x.get("intent_ok"))
    routed = collections.Counter(x.get("routed_intent") for x in m if x.get("routed_intent"))
    leak = [x for x in m if x.get("leakage_ok") is not None]
    L = ["## Intent routing + point-in-time (new layers)", "",
         f"- **intent routed correctly**: **{iok}/{len(intent) or 1}** (vs expected_intent)",
         f"- routed intents: {dict(routed)}",
         f"- questions that triggered a number lookup: {sum(1 for x in m if x.get('n_numbers'))}/{len(m)}"]
    nerr = sum(x.get("n_number_errors", 0) for x in m)
    if nerr:                                                          # loud flag: data-access failure, NOT point-in-time
        L.append(f"- **number lookups that ERRORED (data-access failure, not 'not known'): {nerr}** <- investigate")
    if leak:
        L.append(f"- **leakage-trap handled** (said 'not known at asof'): {sum(1 for x in leak if x['leakage_ok'])}/{len(leak)}")
    L.append(f"- judge **convexity** avg: {avg('convexity')}/5 | **point_in_time** avg: {avg('point_in_time')}/5")
    return L


def planner_report(rows: list[dict]) -> list[str]:
    """L2 grounded-subgraph panel — the cascade-completeness signal for the l2-vs-one-hop A/B. Empty for one-hop
    runs (no trace.planner)."""
    import statistics
    m = [x for x in (_metrics(r) for r in rows) if x.get("is_l2")]
    if not m:
        return []
    n = len(m)

    def avg(key):
        xs = [x[key] for x in m if x.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None

    return ["## L2 planner (deterministic grounded-subgraph walk)", "",
            f"- **L2 answers: {n}/{len(rows)}**",
            f"- avg subgraph: **{avg('n_kept')}** grounded nodes across **{avg('n_contracts')}** contracts "
            f"(>1 contract = a cross-commodity cascade hop was grounded, not just described)",
            f"- avg **convergence regimes fired** (deterministic): {avg('n_regimes')}",
            f"- avg **leg-grounding rate** (kept drivers backed by dated evidence): {avg('leg_grounded')}"]


def register_report(rows: list[dict]) -> list[str]:
    """Output-register panel: how many answers leaked internal tokens (slugs, conf=, (+)/(-), 'the node fired')
    into reader-facing prose — the deterministic complement to the judge's register read."""
    import collections
    m = [_metrics(r) for r in rows]
    n = len(m) or 1
    leaky = [x for x in m if x.get("register_leaks")]
    tally = collections.Counter(t for x in m for t in (x.get("register_tokens") or []))
    L = ["## Output register (leaked internal tokens)", "",
         f"- **answers with leaks: {len(leaky)}/{n}** (clean = reader never sees a raw slug / `conf=` / `(+)` / graph jargon)"]
    if tally:
        top = ", ".join(f"`{t}`x{c}" for t, c in tally.most_common(8))
        L.append(f"- most-leaked tokens: {top}")
    else:
        L.append("- no internal tokens leaked into prose")
    mood = sum(x.get("banned_mood_words", 0) for x in m)
    L.append(f"- **banned mood words (pre-sanitize): {mood}** (mentor-voice HARD gate; must be 0)")
    scaffold_viol = sum(1 for x in m if not x.get("mechanism_scaffold_ok", True))
    L.append(f"- **scaffold violations: {scaffold_viol}** ('## Mechanism' opens; fixed section order; must be 0)")
    chars = [x["answer_chars"] for x in m if x.get("answer_chars")]
    if chars:                                                          # 6.2 conciseness gate: compare across runs
        import statistics
        L.append(f"- answer length: mean {statistics.mean(chars):.0f} chars, max {max(chars)} "
                 f"(conciseness signal — compare vs the prior run)")
    return L


def _n_halluc(j: dict) -> int:
    """Judge hallucination ITEM count, type-safe: a string-typed field is ONE claim, never its
    character count (the 561-vs-37 convo explosion needed this to be decomposable per turn)."""
    h = j.get("hallucinations")
    if isinstance(h, list):
        return len(h)
    return 1 if h else 0


def athena_panel() -> list[str]:
    """S3-LIST-storm tripwire (Jul-2026, $134): per-run Athena telemetry. Planning time is the
    projection-enumeration signature — the storm's ESR queries planned 26-31s to scan KBs. GATE:
    p95 planning < 3s; a breach means a query lost its sargable partition predicates."""
    from leviathan.graphrag.numbers import query as Q
    s = Q.stats_summary()
    if not s.get("n"):
        return []
    lines = ["", "## Athena panel (S3 LIST-storm tripwire)",
             f"- queries: **{s['n']}** | planning p50/p95/max: {s['planning_p50_ms']}/"
             f"**{s['planning_p95_ms']}**/{s['planning_max_ms']} ms (gate p95 < 3000) | "
             f"scanned: {s['scanned_mb']} MB"]
    if s["planning_p95_ms"] > 3000:
        lines.append("- **WARNING: planning p95 over gate — partition-projection enumeration suspected; "
                     "check partition predicates BEFORE running more evals (each breach bills S3 LISTs).**")
    return lines


def verifier_panel(traces: list[dict]) -> list[str]:
    """The deterministic citation_violations panel (plan sec 6.6) — counts fabricated attributions
    without a judge. Its absence made the 37->151 hallucination-tally diagnosis slow; never again."""
    vs = [t for t in traces if t and t.get("enabled")]
    if not vs:
        return []
    by: dict = {}
    for v in vs:
        for k, c in (v.get("by_rule") or {}).items():
            by[k] = by.get(k, 0) + c
    rules = ", ".join(f"{k} x{c}" for k, c in sorted(by.items(), key=lambda x: -x[1])) or "(none)"
    total_strips = sum(v.get("stripped", 0) for v in vs)
    total_claims = sum(v.get("claim_count", 0) for v in vs)          # sentence-claims (P7-P0.1 denominator)
    total_handles = sum(v.get("checked", 0) for v in vs)
    return ["", "## Citation verifier (deterministic) — PRIMARY cross-run quality signal", "",
            "_Judge-free + credit-independent: the un-gameable measure of fabricated citation. Compare THIS "
            "across runs; judge-hallucination deltas under ~8/25 turns are within measured judge noise (RCA-561)._",
            "",
            f"- handles checked: **{total_handles}** | "
            f"stripped: **{total_strips}** | "
            f"ledger dates corrected: {sum(v.get('corrected', 0) for v in vs)}",
            f"- **strip RATE: {total_strips / max(1, total_claims):.4f}** "
            f"(strips / {total_claims} sentence-claims; handle-rate "
            f"{total_strips / max(1, total_handles):.4f}) — the baseline-v0 comparison metric",
            f"- violations by rule: {rules}",
            f"- answers with >=1 strip: {sum(1 for v in vs if v.get('stripped'))}/{len(vs)}"]


def _is_slice_key(rel: str) -> bool:
    """True iff a key path RELATIVE to the evidence base is a retrieval slice: a root `<node>.jsonl`
    (commodity) or `drivers/<name>.jsonl`. Excludes chunks/ (doc cache), _raw/ (archives), eval/ (reports),
    live_events/ and anything else under the shared prefix — those don't change what retrieval returns."""
    if not rel.endswith(".jsonl"):
        return False
    head, _, tail = rel.partition("/")
    return (not tail) or (head == "drivers" and "/" not in tail)


def corpus_fingerprint() -> str:
    """12-hex identity of the evidence corpus a run retrieved from (P7-P0.1 baseline axis, independent of
    graph_version): S3 mode = ONE paginated LIST of the evidence base hashing every SLICE key+ETag (root
    `<node>.jsonl` + `drivers/*.jsonl` only — no downloads, bounded, not a LIST storm; chunks/_raw/eval keys
    are excluded so a doc-cache add or an eval report never flips it); local mode = slice filenames+sizes;
    plus the driver_slices.yaml bytes (so an alias/term edit flips the fingerprint even when no slice bytes
    moved). A slice rebuild or reroute flips THIS; a causal-YAML edit flips graph_version — the baseline
    keys both. (P7-P2.0 fix: this used to list a non-existent `evidence/` subprefix, hashing zero slice keys
    in S3 mode — a content rebuild was invisible.)"""
    import hashlib
    h = hashlib.sha256()
    try:
        s3uri = ev._evid_s3()
        if s3uri:
            import boto3
            b, prefix = ev._parse_s3(s3uri.rstrip("/") + "/")
            pag = boto3.client("s3").get_paginator("list_objects_v2")
            for page in pag.paginate(Bucket=b, Prefix=prefix):
                for o in page.get("Contents") or []:
                    if _is_slice_key(o["Key"][len(prefix):]):
                        h.update(f"{o['Key']}:{o.get('ETag', '')};".encode())
        else:
            for p in sorted(ev._EVID_DIR.glob("**/*.jsonl")):
                rel = p.relative_to(ev._EVID_DIR).as_posix()
                if _is_slice_key(rel):
                    h.update(f"{rel}:{p.stat().st_size};".encode())
        if ev._DRIVER_PATH.exists():
            h.update(ev._DRIVER_PATH.read_bytes())
    except Exception:  # noqa: BLE001 — a fingerprint failure must never break an eval run
        return "unknown"
    return h.hexdigest()[:12]


def _baseline_json(rows: list[dict], *, run_kind: str, model: str, judged: bool, eval_set: str,
                   graph_version: str | None, corpus_fp: str, via_orchestrator: bool = False) -> dict:
    """The machine-readable baseline artifact (P7-P0.1): per-answer strip/claim/leak/intent detail plus the
    run-level reproducibility keys. `register_leaks` here is RESIDUAL (post-sanitize) leakage — the answer
    body was already sanitized at synthesis; do not read it as raw pre-sanitize leakage."""
    import datetime as _dt
    import os as _os
    # ZERO-DRIFT: build every per-answer record through _per_answer_record, the SAME builder the incremental
    # partial JSONL (_persist_partial) uses -- so a killed run's partial equals this baseline's per_answer rows.
    per = [_per_answer_record(r, run_kind) for r in rows]
    total_strips = sum(p["strips"] for p in per)
    total_claims = sum(p["claim_count"] for p in per)
    total_handles = sum(p["handles_checked"] for p in per)
    return {"kind": f"baseline_{run_kind}",
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eval_set": eval_set, "model": model,
            "provider": _os.environ.get("GRAPHRAG_PROVIDER", "anthropic"),
            "judged": judged, "graph_version": graph_version, "corpus_fingerprint": corpus_fp,
            # which path the arm measured: True = the intent-branch serving path (intent 22/30 lives
            # there); False = plain one-hop answer() (intent is never set — do not compare intents)
            "via_orchestrator": via_orchestrator,
            # P9-AB arm identity: without these a flags-off control and a flags-on treatment are
            # byte-identical in every reproducibility key except ts
            "mentor_voice": _os.environ.get("GRAPHRAG_MENTOR_VOICE", "on"),
            "cascade_quant": _os.environ.get("GRAPHRAG_CASCADE_QUANT", "on"),
            "answer_v2": _os.environ.get("GRAPHRAG_ANSWER_V2", "off"),
            "n_answers": len(per),
            "total_strips": total_strips, "total_claims": total_claims, "total_handles": total_handles,
            "strip_rate": round(total_strips / max(1, total_claims), 6),
            "handle_strip_rate": round(total_strips / max(1, total_handles), 6),
            "register_leaks_total": sum(p["register_leaks"] for p in per),
            "banned_mood_words_total": sum(p.get("banned_mood_words", 0) for p in per),
            "scaffold_violations": sum(1 for p in per if not p.get("mechanism_scaffold_ok", True)),
            "intent_ok": sum(1 for p in per if p["intent_ok"]),
            "intent_n": sum(1 for p in per if p["intent_ok"] is not None),
            "per_answer": per}


def _write_baseline(doc: dict) -> None:
    """Persist the baseline artifact locally (gitignored configs/graphrag/eval/) and — when EVIDENCE_S3 is
    set — to s3://<EVIDENCE_S3>/eval/ (the durable copy; the local twin never reaches the public repo)."""
    import json as _json
    name = (f"baseline_{doc['eval_set']}_{doc['provider']}_"
            f"{doc['ts'].replace('-', '').replace(':', '')}.json")
    _OUT.mkdir(parents=True, exist_ok=True)
    p = _OUT / name
    p.write_text(_json.dumps(doc, indent=2), encoding="utf-8")
    s3uri = ev._evid_s3()
    if s3uri:
        import boto3
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/{name}")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=p.read_bytes())
        print(f"  baseline -> s3://{b}/{k}")
    print(f"  baseline json -> {p} (strip_rate {doc['strip_rate']}, {doc['total_claims']} claims, "
          f"leaks {doc['register_leaks_total']}, mood {doc.get('banned_mood_words_total', 0)}, "
          f"scaffold_viol {doc.get('scaffold_violations', 0)}, intent {doc['intent_ok']}/{doc['intent_n']})")


def grounding_report(rows: list[dict]) -> list[str]:
    """Per-commodity grounding-depth table — the decision input for where evidence is thin for real questions."""
    import collections
    import statistics
    by: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by[r["q"]["contract"]].append(_metrics(r))

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs), 1) if xs else None

    L = ["## Per-commodity grounding depth", "",
         "| commodity | Qs | routed | usefulness | grounding | ev.retrieved | ev.cited | halluc |",
         "|---|--|--|--|--|--|--|--|"]
    flags = []
    for c in sorted(by):
        m = by[c]
        g = avg([x["grounding"] for x in m])
        if g is not None and g < 3:
            flags.append(c)
        L.append(f"| {c} | {len(m)} | {sum(x['routed_ok'] for x in m)}/{len(m)} | {avg([x['usefulness'] for x in m])} "
                 f"| {g} | {avg([x['retrieved'] for x in m])} | {avg([x['cited'] for x in m])} "
                 f"| {sum(x['halluc'] for x in m)} |")
    L += ["", f"**Under-grounded (avg grounding < 3) -> candidates for broad-rebuild / corpus gap:** {flags or 'none'}"]
    return L


def _num_line(out: dict) -> str:
    parts = []
    for c in out.get("number_calls") or []:
        qy, rws = c.get("query", {}), (c.get("rows") or [])
        if not rws:
            val = "ERROR" if c.get("status") == "error" else "(not known)"
        elif len(rws) == 1:
            val = rws[0].get("value")
        else:
            # LATEST row, labeled — the old rows[0] render showed a series' oldest year as THE value
            # and seeded the cocoa false-fabrication mis-triage (RCA 2026-07-24)
            last = rws[-1]
            val = f"{last.get('value')}@{last.get('period', '?')} (latest of {len(rws)} rows)"
        parts.append(f"{qy.get('table','?')}.{qy.get('metric','?')}={val}")
    return ", ".join(parts)


def report(rows: list[dict], *, model: str, graph_version: str | None = None,
           judge_requested: bool = False) -> str:
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    judged = [r["judge"] for r in rows if r.get("judge")]
    intent_rows = [r for r in rows if r["rubric"].get("expected_intent")]
    lines = [f"# graphdev eval v3 — {model}", ""]
    # Run-validity gate (2026-07-19 RCA 8b): a run where the synthesis tier floored a material share
    # of turns measures the OUTAGE, not the pipeline -- its judge/strip aggregates must never be
    # compared against a healthy baseline (two such runs mis-attributed an Anthropic tier window to
    # a feature flag). 15% ~= one floored turn on the small decks.
    #
    # W8: keyed on the TRACE SLUG (`trace.floor`, a machine contract set by orchestrator._evidence_only)
    # and NOT on `out['model'] == "(unavailable)"`. That was a DISPLAY STRING -- the human-facing model
    # label rendered in the UI -- and a copy edit of it would have silently disarmed the gate that exists
    # to stop an outage being read as a quality regression. Presence, not equality: any floor variant
    # counts, and the bounded WHY rides `trace.floor_cause` (pg_statement_timeout / pg_operational /
    # model_download / llm_unavailable / other), reported below so a floored run says which outage it was.
    def _floor_of(r: dict) -> str | None:
        return ((r.get("out") or {}).get("trace") or {}).get("floor")

    floored_rows = [r for r in rows if _floor_of(r)]
    floored = len(floored_rows)
    if rows and floored / len(rows) > 0.15:
        import collections
        causes = collections.Counter(((r.get("out") or {}).get("trace") or {}).get("floor_cause")
                                     or "other" for r in floored_rows)
        why = ", ".join(f"{c} x{n}" for c, n in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0])))
        lines += [f"> **RUN INCONCLUSIVE -- {floored}/{len(rows)} turns floored to the evidence-only "
                  f"fallback (cause: {why}). Aggregates below measure the outage, not the "
                  "pipeline; do NOT compare against baselines.**", ""]
    if graph_version:
        lines.append(f"- graph: `{graph_version}` (causal-YAML content hash — the graph this run scored)")
    lines.append(f"- contract routed correctly: **{routed}/{len(rows)}**")
    if judge_requested and len(judged) < len(rows):    # a degraded JUDGED run must never masquerade as a
        # full one -- but a no-judge run is not degraded (the old unconditional guard printed a false
        # '30 judge call(s) FAILED' banner on every no-judge run; NEWCAP TRIAGE 2026-07-24)
        lines.append(f"- **JUDGED {len(judged)}/{len(rows)}** — {len(rows) - len(judged)} judge call(s) "
                     "FAILED (see WARNs in the job log); judge averages cover judged rows only")
    if intent_rows:
        iok = sum(1 for r in intent_rows if r["rubric"].get("intent_ok"))
        lines.append(f"- **intent routed correctly: {iok}/{len(intent_rows)}** (numbers_only / reasoning / hybrid)")
    if judged:
        j_avg = lambda key: sum(j.get(key, 0) for j in judged) / len(judged)  # noqa: E731
        halluc = sum(_n_halluc(j) for j in judged)
        lines.append(f"- judge **usefulness {j_avg('usefulness'):.1f}** · **convexity {j_avg('convexity'):.1f}** · "
                     f"**point_in_time {j_avg('point_in_time'):.1f}** · grounding {j_avg('grounding'):.1f} /5 · "
                     f"hallucinated claims: {halluc}")
    lines.append("")
    lines += routing_report(rows) + [""]                               # v3 new-layers panel
    if any((r["out"].get("trace") or {}).get("planner") == "l2" for r in rows):
        lines += planner_report(rows) + [""]                           # L2 grounded-subgraph cascade panel
    lines += register_report(rows) + [""]                              # output-register discipline (leaked internal tokens)
    lines += verifier_panel([(r["out"].get("trace") or {}).get("citation_verifier") for r in rows]) + [""]
    lines += athena_panel() + [""]                                     # S3 LIST-storm tripwire (planning-time gate)
    lines += source_report(rows) + [""]                                # multi-source lift (deterministic + judge)
    if judged:
        lines += grounding_report(rows) + [""]
    for r in rows:
        q, out, rb = r["q"], r["out"], r["rubric"]
        nums = _num_line(out)
        lines += [f"## {q['id']}  ({q.get('category', q.get('type', ''))})", f"**Q:** {q['question']}", "",
                  f"- intent: `{out.get('intent')}` (expected `{q.get('expected_intent')}`) | routed: "
                  f"`{out.get('contract')}` | evidence: {len(out.get('evidence') or [])} | "
                  f"numbers: {len(out.get('number_calls') or [])}"
                  + (f" [{rb.get('leakage_ok') and 'leakage OK' or 'LEAKAGE MISS'}]" if rb.get("leakage_ok") is not None else ""),
                  f"- evidence: {[(e['source'], e['date']) for e in out.get('evidence') or []][:6]}"]
        if nums:
            lines.append(f"- numbers looked up: {nums}")
        ca = rb.get("cascade_asserts")
        if ca is not None:                                             # v4 cascade query: the per-query gate line
            cs = _cascade_stats(out)
            lines.append(f"- cascade: fired={cs['fired']} cited={cs['n_cited']}/{cs['n_rows']} "
                         f"fork_nodes={cs['divergence_nodes']} statuses={cs['statuses']} "
                         f"asserts={'PASS' if all(ca.values()) else 'FAIL'} {ca}")
        leaks = reg.register_leaks(out.get("answer") or "")
        if leaks:                                                      # surface the exact leaked tokens + context
            lines.append(f"- **register leaks ({len(leaks)}):** "
                         + "; ".join(f"`{t}` (…{c}…)" for t, c in leaks[:6]))
        if r.get("judge"):
            j = r["judge"]
            lines += [f"- **judge:** usefulness {j.get('usefulness')}/5 · convexity {j.get('convexity')}/5 · "
                      f"point_in_time {j.get('point_in_time')}/5 · grounding {j.get('grounding')}/5 — "
                      f"_{j.get('verdict')}_",
                      f"  - gaps: {j.get('gaps')}",
                      f"  - hallucinations: {j.get('hallucinations') or 'none'}",
                      f"  - improvements: {j.get('improvements') or '—'}"]
        lines += ["", "**A:**", "", (out.get("answer") or "(no answer)"), ""]
    return "\n".join(lines)


_PRICE = {"claude-sonnet-4-6": (3.0 / 1e6, 15.0 / 1e6), "claude-opus-4-8": (5.0 / 1e6, 25.0 / 1e6),
          "claude-haiku-4-5": (1.0 / 1e6, 5.0 / 1e6)}


def estimate_cost(queries: list[dict], *, model: str, judge_model: str | None = None,
                  via_orchestrator: bool = False) -> dict:
    # rough: answer ~3.5K input (graph + evidence) + ~0.9K out; judge ~5K input (+ numbers) + ~0.9K out
    ap = _PRICE.get(model, _PRICE["claude-sonnet-4-6"])
    usd = len(queries) * (3500 * ap[0] + 900 * ap[1])
    out = {"queries": len(queries), "model": model, "answer_usd": round(usd, 2), "est_usd": round(usd, 2)}
    if via_orchestrator:                                          # numbers agent (Haiku): ~2 tool-loop calls per numbers/hybrid Q
        hp = _PRICE["claude-haiku-4-5"]
        nq = sum(1 for q in queries if q.get("expected_intent") in ("numbers_only", "hybrid"))
        nusd = nq * 2 * (2500 * hp[0] + 400 * hp[1])
        usd += nusd
        out.update(numbers_haiku_usd=round(nusd, 2), est_usd=round(usd, 2))
    if judge_model:
        jp = _PRICE.get(judge_model, _PRICE["claude-opus-4-8"])
        jusd = len(queries) * (5000 * jp[0] + 900 * jp[1])
        out.update(judge_model=judge_model, judge_usd=round(jusd, 2), total_usd=round(usd + jusd, 2),
                   est_usd=round(usd + jusd, 2))
    return out


# ── multi-turn conversation eval (session memory, all intents, all agents) ────────────────────────────────
def load_convos(path) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("conversations") or []


class _UsageTap:
    """Thread-local capture of Anthropic usage (cache reads = the caching headline). Convos run one-per-
    thread with sequential turns, so a threading.local ring is exact per turn."""

    def __init__(self):
        import threading
        self.local = threading.local()
        self._orig = None

    def start(self):
        import anthropic
        self._orig = anthropic.resources.messages.Messages.create
        tap = self

        def create(inner_self, **kw):
            resp = tap._orig(inner_self, **kw)
            u = getattr(resp, "usage", None)
            rec = getattr(tap.local, "records", None)
            if u is not None and rec is not None:
                rec.append({"read": getattr(u, "cache_read_input_tokens", 0) or 0,
                            "write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                            "input": getattr(u, "input_tokens", 0) or 0,
                            "output": getattr(u, "output_tokens", 0) or 0})
            return resp
        anthropic.resources.messages.Messages.create = create

    def begin_turn(self) -> list:
        self.local.records = []
        return self.local.records

    def stop(self):
        if self._orig is not None:
            import anthropic
            anthropic.resources.messages.Messages.create = self._orig


def _convo_mechanics(spec: dict, out: dict, prev_out: dict | None) -> dict:
    """Deterministic session-mechanics checks from the turn's expectations (the machine-checkable half;
    the continuity judge covers the semantic half)."""
    checks: dict = {}
    routed = [c for c in (out.get("contracts") or [out.get("contract")]) if c]
    if spec.get("expected_intent"):
        exp = spec["expected_intent"]                              # str OR list: hybrid/reasoning are not
        exp = exp if isinstance(exp, list) else [exp]              # mutually exclusive on quantitative turns
        checks["intent_ok"] = out.get("intent") in exp
    if spec.get("contracts_any_of"):
        checks["contract_ok"] = any(c in routed for c in spec["contracts_any_of"])
    if spec.get("carries_contracts") and prev_out is not None:
        prevc = {c for c in (prev_out.get("contracts") or [prev_out.get("contract")]) if c}
        checks["carry_contracts_ok"] = bool(set(routed) & prevc)
    if spec.get("carries_asof") and prev_out is not None:
        checks["carry_asof_ok"] = out.get("asof") == prev_out.get("asof")
    if spec.get("overrides_asof"):
        checks["override_asof_ok"] = out.get("asof") == str(spec.get("asof"))
    if spec.get("not_known"):
        checks["not_known_ok"] = any(p in (out.get("answer") or "").lower() for p in _NOT_KNOWN)
    if spec.get("uses_state"):
        checks["resolved_ok"] = bool(routed)
    return checks


def run_conversations(graph, convos: list[dict], *, model: str = an.SONNET, workers: int = 5,
                      numbers_client=None, call=None, respond_fn=None, store=None, persist=None,
                      deadline: float | None = None, heartbeat_period: float = 90.0) -> list[dict]:
    """Turns are SEQUENTIAL within a conversation (state dependency); CONVERSATIONS parallelize — the speed
    structure that makes 25 turns ~ one conversation's wall-clock. Each convo gets its own session_id; the
    session store is the real serving one (Dynamo in-container via rev-7 env, in-memory locally).

    E-W2: same explicit-futures MAIN-thread drain as run() — a per-CONVO watchdog + heartbeat + incremental
    persistence (`persist(row)` per completed convo's rows, MAIN thread only) so a killed convos run leaves a
    readable partial and a stalled convo costs only `deadline`."""
    import time as _time
    import uuid

    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import session as ssn
    respond_fn = respond_fn or orch.respond
    store = store or ssn.default_store()
    deadline = _turn_deadline(deadline)
    started: dict[int, float] = {}                                     # convo-idx -> START monotonic
    tap = _UsageTap()
    tap.start()
    run_tag = uuid.uuid4().hex[:6]

    def _one_convo(idx: int, cv: dict) -> list[dict]:
        started[idx] = _time.monotonic()
        try:
            rows, prev = [], None
            sid = f"eval-{cv['id']}-{run_tag}"
            for i, spec in enumerate(cv["turns"]):
                rec = tap.begin_turn()
                t0 = _time.monotonic()
                try:
                    out = respond_fn(spec["q"], graph=graph, asof=spec.get("asof"), model=model,
                                     numbers_client=numbers_client, call=call,
                                     session_id=sid, session_store=store)
                except Exception as e:  # noqa: BLE001 — one bad turn must not abort a billed run
                    out = {"answer": f"(turn failed: {str(e)[:200]})", "intent": None, "contract": None,
                           "contracts": [], "asof": spec.get("asof"), "evidence": [], "number_calls": [],
                           "structured": None, "trace": {"error": str(e)[:300]}}
                    print(f"  WARN {cv['id']} turn {i}: {str(e)[:120]}", flush=True)
                dt = _time.monotonic() - t0
                usage = {k: sum(r[k] for r in rec) for k in ("read", "write", "input", "output")} if rec else \
                    {"read": 0, "write": 0, "input": 0, "output": 0}
                print(f"  {cv['id']} turn {i} in {dt:.0f}s (cache_read {usage['read']})", flush=True)
                rows.append({"convo": cv["id"], "turn": i, "spec": spec, "out": out,
                             "mech": _convo_mechanics(spec, out, prev), "secs": round(dt, 1), "usage": usage})
                prev = out
            return rows
        finally:
            started.pop(idx, None)

    width = max(1, min(workers, len(convos)))
    if width <= 1:                                                    # sequential: persist per convo, no watchdog
        all_rows = []
        for idx, cv in enumerate(convos):
            rows = _one_convo(idx, cv)
            all_rows.extend(rows)
            if persist is not None:
                for row in rows:
                    persist(row)
        tap.stop()
        return all_rows

    from concurrent.futures import ThreadPoolExecutor
    results: list = [None] * len(convos)                             # convo-idx keyed so order is preserved
    ids = [str(cv.get("id")) for cv in convos]
    pool = ThreadPoolExecutor(max_workers=width)
    futs = {pool.submit(_one_convo, idx, cv): idx for idx, cv in enumerate(convos)}

    def _complete(idx: int, fut) -> None:                            # MAIN thread
        rows = fut.result()
        results[idx] = rows
        if persist is not None:
            for row in rows:
                persist(row)

    def _timeout(idx: int) -> None:                                  # MAIN thread: a stalled convo
        row = {"convo": ids[idx], "turn": 0, "spec": {"q": ""}, "mech": {}, "secs": deadline,
               "out": {"answer": f"(convo watchdog timeout at {deadline:.0f}s)", "intent": None,
                       "contract": None, "contracts": [], "evidence": [], "number_calls": [],
                       "structured": None, "trace": {"error": "watchdog_timeout",
                                                     "degraded_model": "(watchdog_timeout)"}}}
        results[idx] = [row]
        if persist is not None:
            persist(row)

    _drain(futs, started, ids=ids, n=len(convos), deadline=deadline, heartbeat_period=heartbeat_period,
           workers=width, on_complete=_complete, on_timeout=_timeout, label="convo")
    pool.shutdown(wait=False)
    tap.stop()
    return [r for rows in results if rows for r in rows]


def _convo_history(rows: list[dict], row: dict) -> str:
    prior = [r for r in rows if r["convo"] == row["convo"] and r["turn"] < row["turn"]]
    return "\n".join(
        f"turn {r['turn']}: Q: {r['spec']['q']} (as-of {r['out'].get('asof')}) -> A(tl;dr): "
        + str((r['out'].get('structured') or {}).get('tldr') or r['out'].get('answer') or '')[:180]
        for r in sorted(prior, key=lambda x: x["turn"]))


def convo_report(rows: list[dict], *, model: str, graph_version: str | None = None) -> str:
    import collections
    import statistics
    tally: dict = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        for k, ok in r["mech"].items():
            tally[k][1] += 1
            tally[k][0] += bool(ok)
    judged = [r["judge"] for r in rows if r.get("judge")]

    def javg(key):
        xs = [j.get(key) for j in judged if j.get(key) is not None]
        return round(statistics.mean(xs), 1) if xs else None
    later = [r for r in rows if r["turn"] > 0]
    cache_hit_turns = sum(1 for r in later if r["usage"]["read"] > 0)
    tot_read = sum(r["usage"]["read"] for r in rows)
    tot_in = sum(r["usage"]["input"] for r in rows)
    secs = [r["secs"] for r in rows]
    lines = [f"# conversation eval v1 — {model}", ""]
    if graph_version:
        lines.append(f"- graph: `{graph_version}` (causal-YAML content hash — the graph this run scored)")
    lines += ["", "## Session mechanics (deterministic)", ""]
    for k in sorted(tally):
        ok, n = tally[k]
        lines.append(f"- **{k}**: {ok}/{n}")
    lines += ["", "## Caching + speed", "",
              f"- turns 2+ with a prompt-cache HIT: **{cache_hit_turns}/{len(later)}**",
              f"- input tokens served from cache: **{tot_read:,}** vs {tot_in:,} uncached "
              f"({100 * tot_read / max(1, tot_read + tot_in):.0f}% of prompt volume)",
              f"- per-turn seconds: avg {statistics.mean(secs):.0f}, max {max(secs):.0f}"]
    if judged:
        lines += ["", "## Judge", "",
                  f"- **judged {len(judged)}/{len(rows)} turns**"
                  + ("" if len(judged) == len(rows) else
                     f" — {len(rows) - len(judged)} judge call(s) FAILED; averages cover judged turns only"),
                  f"- usefulness {javg('usefulness')} | convexity {javg('convexity')} | "
                  f"point_in_time {javg('point_in_time')} | grounding {javg('grounding')} | "
                  f"**continuity {javg('continuity')}** /5",
                  f"- hallucinated claims: {sum(_n_halluc(j) for j in judged)}"]
    lines += verifier_panel([(r["out"].get("trace") or {}).get("citation_verifier") for r in rows])
    lines += athena_panel()                                            # S3 LIST-storm tripwire (planning-time gate)
    for cid in dict.fromkeys(r["convo"] for r in rows):
        lines += ["", f"## {cid}", ""]
        for r in [x for x in rows if x["convo"] == cid]:
            j = r.get("judge") or {}
            mech = " ".join(f"{k}={'Y' if v else 'N'}" for k, v in r["mech"].items())
            lines += [f"### turn {r['turn']}: {r['spec']['q']}",
                      f"- intent `{r['out'].get('intent')}` | routed {r['out'].get('contracts') or r['out'].get('contract')} "
                      f"| asof {r['out'].get('asof')} | {r['secs']}s | cache_read {r['usage']['read']}",
                      f"- mechanics: {mech or '(none)'}"]
            vfr = (r["out"].get("trace") or {}).get("citation_verifier") or {}
            if vfr.get("stripped"):
                lines.append(f"- verifier: stripped {vfr['stripped']} ({', '.join(sorted(vfr.get('by_rule') or {}))})")
            if j:
                lines.append(f"- judge: usefulness {j.get('usefulness')} continuity {j.get('continuity')} "
                             f"PIT {j.get('point_in_time')} halluc {_n_halluc(j)} — _{j.get('verdict')}_")
            lines += ["", str(r["out"].get("answer") or "(no answer)"), ""]
    return "\n".join(lines)


def _convos_main(args, path) -> int:
    """The --convos entry: run the multi-turn session eval end to end."""
    convos = load_convos(path)
    n_turns = sum(len(c["turns"]) for c in convos)
    if args.dry_run or not args.run:
        est = n_turns * 0.10 + (n_turns * 0.06 if args.judge else 0)   # sonnet answers (cache-discounted) + opus judges
        print(f"DRY-RUN: {len(convos)} conversations, {n_turns} turns; est ~${est:.2f} "
              f"(judge={'on' if args.judge else 'off'})")
        return 0
    from leviathan.common import config
    config.load_env()
    ev.CACHE_INDEX = True
    graph = gph.CausalGraph.load()
    import os as _os
    from pathlib import Path

    import anthropic

    from leviathan.graphrag import batch_extract as bx
    from leviathan.graphrag import providers as pv
    client = anthropic.Anthropic(api_key=bx._api_key(), timeout=pv._client_timeout(), max_retries=0)  # E-W1 2.3
    provider = _os.environ.get("GRAPHRAG_PROVIDER", "anthropic")
    eval_set = Path(str(path)).stem
    pw = _PartialWriter(_partial_path(eval_set, provider), "convos", s3_key=_partial_s3_key(eval_set, provider))
    rows = run_conversations(graph, convos, model=args.model, workers=args.workers,
                             numbers_client=client, call=an._call_opus, persist=pw,
                             deadline=_turn_deadline(), heartbeat_period=90.0)
    deadline = _turn_deadline()
    if args.judge:
        def _judge_row(r: dict) -> None:
            try:
                r["judge"] = judge({"question": r["spec"]["q"], "asof": r["out"].get("asof")}, r["out"],
                                   graph=graph, client=client, model=args.judge_model,
                                   convo_history=_convo_history(rows, r))
                print(f"  judged {r['convo']} turn {r['turn']}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN judge {r['convo']} t{r['turn']} failed -- {str(e)[:120]}", flush=True)
        if args.workers > 1:                                          # AV5: same explicit-futures watchdog+persist
            pj = _PartialWriter(_partial_path(eval_set, provider, judge=True), "convos",
                                s3_key=_partial_s3_key(eval_set, provider, judge=True))
            import time as _jtime
            jstarted: dict[int, float] = {}

            def _judge_one(idx: int, r: dict) -> dict:
                jstarted[idx] = _jtime.monotonic()
                try:
                    _judge_row(r)
                    return r
                finally:
                    jstarted.pop(idx, None)

            from concurrent.futures import ThreadPoolExecutor
            jids = [f"{r.get('convo')}/{r.get('turn')}" for r in rows]
            jpool = ThreadPoolExecutor(max_workers=args.workers)
            jfuts = {jpool.submit(_judge_one, idx, r): idx for idx, r in enumerate(rows)}

            def _jc(idx: int, fut) -> None:
                fut.result()
                pj(rows[idx])

            def _jt(idx: int) -> None:
                rows[idx].setdefault("judge", None)
                pj(rows[idx])
                print(f"  WATCHDOG-JUDGE {jids[idx]}: judge exceeded {deadline:.0f}s -- skipping score", flush=True)

            _drain(jfuts, jstarted, ids=jids, n=len(rows), deadline=deadline, heartbeat_period=90.0,
                   workers=args.workers, on_complete=_jc, on_timeout=_jt, label="judge")
            jpool.shutdown(wait=False)
            pj.close()
        else:
            for r in rows:
                _judge_row(r)
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / f"report_convos_{Path(str(path)).stem}.md"
    out_path.write_text(convo_report(rows, model=args.model, graph_version=graph.version), encoding="utf-8")
    s3uri = ev._evid_s3()
    if s3uri:
        import boto3
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/report_convos_{Path(str(path)).stem}_{args.model}.md")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=out_path.read_bytes())
        print(f"  report -> s3://{b}/{k}")
    _write_baseline(_baseline_json(rows, run_kind="convos", model=args.model, judged=args.judge,
                                   eval_set=Path(str(path)).stem, graph_version=graph.version,
                                   corpus_fp=corpus_fingerprint(),
                                   via_orchestrator=True))     # convos always run orchestrator.respond
    mech_ok = sum(sum(bool(v) for v in r["mech"].values()) for r in rows)
    mech_n = sum(len(r["mech"]) for r in rows)
    print(f"convo eval: {len(convos)} convos / {len(rows)} turns; mechanics {mech_ok}/{mech_n} -> {out_path}")
    pw.close()                                                    # AV1 EXIT: flush the partial, then bypass the
    _os._exit(0)                                                  # atexit worker-join that an orphan would block
    return 0                                                      # unreachable; kept for readability


def main() -> int:
    ap = argparse.ArgumentParser(description="graphdev eval (routing + judge + source-diversity lift)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=an.SONNET)
    ap.add_argument("--judge", action="store_true", help="add an independent LLM-judge quality score")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--queries", default=None, help="queries yaml path (default configs/graphrag/eval_queries.yaml)")
    ap.add_argument("--via-orchestrator", action="store_true",
                    help="route each query through the intent branch (orchestrator.respond) — numbers/reasoning/hybrid")
    ap.add_argument("--planner", default=None, choices=[None, "l2", "onehop"],
                    help="reasoning engine: default = serving default (L2 via orchestrator; answer() alone stays "
                         "one-hop); 'onehop' forces the single-contract baseline for A/Bs")
    ap.add_argument("--workers", type=int, default=4,
                    help="concurrent questions (answer + judge phases; LLM-network-bound so cost is identical; "
                         "1 = legacy sequential)")
    ap.add_argument("--convos", default=None,
                    help="conversation yaml -> multi-turn session eval (turns sequential per convo, convos "
                         "parallel; mechanics + continuity judge + cache/speed panels)")
    args = ap.parse_args()
    from pathlib import Path
    if args.convos:
        return _convos_main(args, Path(args.convos))
    queries = load_queries(Path(args.queries)) if args.queries else load_queries()
    if args.dry_run or not args.run:
        print(f"DRY-RUN cost estimate: {estimate_cost(queries, model=args.model, via_orchestrator=args.via_orchestrator, judge_model=args.judge_model if args.judge else None)}")
        import collections
        cats = collections.Counter(q.get("category", q.get("type", "?")) for q in queries)
        intents = collections.Counter(q.get("expected_intent") for q in queries if q.get("expected_intent"))
        print(f"  {len(queries)} questions across {len(set(q['contract'] for q in queries))} contracts; "
              f"categories: {dict(cats)}; expected_intent: {dict(intents)}")
        return 0
    from leviathan.common import config
    config.load_env()                                 # load ANTHROPIC_API for the serving (+ judge) model
    import os as _os
    hf_uri = _os.environ.get("GRAPHRAG_HF_S3_CACHE")
    if hf_uri:                                        # P9-AB G5: the eval lane cold-downloads bge from HF (the
        try:                                          # cold-Spot hang) — warm from S3 exactly like serving does.
            from leviathan.graphrag import hf_cache   # An S3 hiccup must degrade to the HF download, never kill
            hf_cache.ensure(hf_uri)                   # a billed run (same try-guard as server.py).
            print(f"  hf cache warmed from {hf_uri}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  WARN hf cache warm failed -- {str(e)[:120]}", flush=True)
    try:                                              # warm the MODEL OBJECT single-threaded too: the file-cache
        ev.embed(["eval warm"])                       # warm above never constructs the model, and N workers racing
        print("  bge model warmed", flush=True)       # the first load = the meta-tensor all-rows crash (2026-07-12);
    except Exception as e:  # noqa: BLE001            # the load is also lock-guarded in evidence._bge_local now.
        print(f"  WARN bge model warm failed -- {str(e)[:120]}", flush=True)
    # No torch thread cap here: rankers.rerank_scores serializes the heavy cross-encoder behind a global
    # lock, so each rerank gets ALL cores instead of N workers thrashing at cores/N threads. The old
    # cpu//workers cap under the lock would have crippled every rerank to 2 threads.
    ev.CACHE_INDEX = True                             # the now-large slices load from S3 once, reused across queries
    graph = gph.CausalGraph.load()
    client = None
    if args.via_orchestrator or args.judge:           # one shared Anthropic client (numbers agent + judge + convos)
        import anthropic

        from leviathan.graphrag import batch_extract as bx
        from leviathan.graphrag import providers as pv
        # E-W1 2.3: the eval builds its OWN client (numbers-agent eval branch runs with NO tenacity, agent.py
        # pv=None -> resp=_one(); the judge is call_opus on this same client) so the make_client policy never
        # reaches it -- carry the read timeout + max_retries=0 here or these call sites stay un-timed/un-retried.
        client = anthropic.Anthropic(api_key=bx._api_key(), timeout=pv._client_timeout(), max_retries=0)
    # E-W2 §3.2: open the STABLE partial JSONL ONCE, before run(), and hold it open across the answer + judge
    # phases; flush+close it IMMEDIATELY before os._exit(0) below (os._exit truncates a buffered tail).
    provider = _os.environ.get("GRAPHRAG_PROVIDER", "anthropic")
    eval_set = (Path(args.queries).stem if args.queries else "default")
    pw = _PartialWriter(_partial_path(eval_set, provider), "single",
                        s3_key=_partial_s3_key(eval_set, provider))
    deadline = _turn_deadline()
    rows = run(graph, queries, model=args.model, k=args.k, via_orchestrator=args.via_orchestrator,
               numbers_client=client if args.via_orchestrator else None,
               call=an._call_opus if args.via_orchestrator else None, planner=args.planner,
               workers=args.workers, persist=pw, deadline=deadline)
    if args.judge:
        def _judge_row(r: dict) -> None:
            try:                                                      # a judge failure must not lose the whole run
                r["judge"] = judge(r["q"], r["out"], graph=graph, client=client, model=args.judge_model)
                print(f"  judged {r['q'].get('id')}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN judge {r['q'].get('id')} failed -- {str(e)[:120]}", flush=True)
        if args.workers > 1:                                          # AV5: same explicit-futures watchdog+persist
            # a SIGKILL mid-judging must keep every score computed so far -> drain judge futures on the MAIN
            # thread + re-persist each row (now carrying its judge scores) to a partial_judge sidecar.
            pj = _PartialWriter(_partial_path(eval_set, provider, judge=True), "single",
                                s3_key=_partial_s3_key(eval_set, provider, judge=True))
            import time as _jtime
            jstarted: dict[int, float] = {}

            def _judge_one(idx: int, r: dict) -> dict:
                jstarted[idx] = _jtime.monotonic()
                try:
                    _judge_row(r)                                     # mutates r in place, swallows exceptions
                    return r
                finally:
                    jstarted.pop(idx, None)

            from concurrent.futures import ThreadPoolExecutor
            jids = [str((r.get("q") or {}).get("id")) for r in rows]
            jpool = ThreadPoolExecutor(max_workers=args.workers)
            jfuts = {jpool.submit(_judge_one, idx, r): idx for idx, r in enumerate(rows)}

            def _jc(idx: int, fut) -> None:                           # MAIN thread
                fut.result()
                pj(rows[idx])

            def _jt(idx: int) -> None:                                # MAIN thread: a stalled judge call
                rows[idx].setdefault("judge", None)                  # keep the (already-persisted) answer, skip the score
                pj(rows[idx])
                print(f"  WATCHDOG-JUDGE {jids[idx]}: judge exceeded {deadline:.0f}s -- skipping score", flush=True)

            _drain(jfuts, jstarted, ids=jids, n=len(rows), deadline=deadline, heartbeat_period=90.0,
                   workers=args.workers, on_complete=_jc, on_timeout=_jt, label="judge")
            jpool.shutdown(wait=False)
            pj.close()
        else:
            for r in rows:
                _judge_row(r)
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / f"report_{args.model}.md"
    out_path.write_text(report(rows, model=args.model, graph_version=graph.version,
                               judge_requested=args.judge), encoding="utf-8")
    s3uri = ev._evid_s3()
    if s3uri:                                                     # persist so a Fargate run's report survives the container
        import boto3
        import datetime as _dt
        stem = Path(args.queries).stem if args.queries else "default"
        # ts-keyed (P9-AB): the old arm-invariant key meant a control arm's report was OVERWRITTEN by the
        # treatment arm's upload — and the athena/verifier panels exist only in the report md.
        rts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/report_{args.model}_{stem}_{rts}.md")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=out_path.read_bytes())
        print(f"  report -> s3://{b}/{k}")
    _write_baseline(_baseline_json(rows, run_kind="single", model=args.model, judged=args.judge,
                                   eval_set=(Path(args.queries).stem if args.queries else "default"),
                                   graph_version=graph.version, corpus_fp=corpus_fingerprint(),
                                   via_orchestrator=args.via_orchestrator))
    routed = sum(r["rubric"]["routed_right"] for r in rows)
    extra = ""
    if args.judge:
        use = sum((r.get("judge") or {}).get("usefulness", 0) for r in rows) / len(rows)
        gnd = sum((r.get("judge") or {}).get("grounding", 0) for r in rows) / len(rows)
        halluc = sum(len((r.get("judge") or {}).get("hallucinations") or []) for r in rows)
        extra = f", judge usefulness {use:.1f}/5 grounding {gnd:.1f}/5 ({halluc} halluc)"
    print(f"eval {args.model}: {len(rows)} queries, routed {routed}/{len(rows)}{extra} -> {out_path}")
    # AV1 EXIT: every report/baseline is already written (write_text is atomic open+write+close). Flush+close
    # the crash-survival partial handle, THEN os._exit(0) to bypass the concurrent.futures atexit hook that
    # would JOIN a watchdog-orphaned worker and block container teardown. os._exit skips TextIOWrapper.close,
    # so the flush above is what keeps the partial's tail (§3.1 Mitigation B / §6 F-V3 F1).
    pw.close()
    import os as _osx
    _osx._exit(0)
    return 0                                                      # unreachable; kept for type/readability


if __name__ == "__main__":
    raise SystemExit(main())
