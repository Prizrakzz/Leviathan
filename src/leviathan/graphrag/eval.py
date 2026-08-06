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
import re

import yaml

from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import register as reg
from leviathan.graphrag import tracekeys as tk

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

# ── W4 event playbooks: the '## Episodes' surface (D6 + skeptic F-J + W2b-D5) ────────────────────────
# The reserved heading the W4 D3 register paragraph renders, injected-only, in the _SYSTEM_CASCADE
# '## Cross-commodity' / '## Complex-wide move' shape. Heading TEXT only -- answer._sectionize strips
# the '## ' marker before the kind lookup, so these pins compare against the clean text.
_EPISODE_HEADING = "Episodes"
# Episode-CLASS separation for clustering CITED evidence dates. Serving's timeline default is 90 days
# (a within-season split); an episode CLASS -- "the 1994 frost" vs "the 2021 frost" -- is a year apart.
_EPISODE_GAP_DAYS = 365
# THE ENUMERATION CONTRACT, and the W4 D3 paragraph MUST instruct it: the '## Episodes' section is ONE
# BULLET (or numbered item) PER EPISODE, each carrying a 4-digit year. Prose sentences that merely
# mention a year are NOT episode lines -- counting them would inflate the count and destroy the
# confabulation half of min_episode_lines, which is an EQUALITY-shaped test.
_EPISODE_BULLET_RX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_EPISODE_YEAR_RX = re.compile(r"(?<!\d)(?:1[6-9]\d{2}|20\d{2})(?!\d)")
_N_HANDLE_RX = re.compile(r"\[N\d+\]")
# F-I, prose side. What an honestly-enumerated episode says when the retrieved top-K carried NO citable
# item inside its window -- timeline._NO_RECEIPT is the marker the reasoner is SHOWN, these are the
# phrasings it writes back. Lower-cased substring match (the register/sanitize passes never touch these).
# NB 'not in the record' was DELIBERATELY narrowed to 'not in this record' (fold-pass 2026-07-30): the
# broad form earned a min_episode_lines absence allowance on any line that used it loosely.
_NO_CITABLE = ("no citable item", "no cited item", "no citable source", "no dated item",
               "no dated source", "no citable evidence", "corpus is silent", "record is silent",
               "no source in this window", "not in this corpus", "not in the corpus",
               "not in this record")
# W2b-D5. The no-PRICE-record marker, DISTINCT from _NO_CITABLE: text evidence can exist while the
# per-contract price record does not, which is exactly the 1994 Brazil frost (11 text props;
# silver_futures_eod will never cover 1994 under this plan -- W2b.2). An episode enumerated with no
# magnitude AND no statement that the price record does not reach it is F-I in price form.
_NO_PRICE_RECORD = ("no price record", "not in the price record", "no per-contract price record",
                    "no price data", "no priced move", "price record does not", "price record is silent",
                    # R6 fold (2026-08-04): P2's honest absence bullet read "no single priced move for
                    # this full window" and the interposed word defeated the bare substring -- an
                    # eval-brittleness red, not a model defect. Accept the natural interposers.
                    "no single priced move", "no one priced move", "without a priced move",
                    "not in the price data", "no magnitude", "no observed magnitude",
                    "outside the price coverage", "before the price record")

# R6 residual fold (2026-08-04): the tuple above is a synonym treadmill -- P2 dodged the first fold
# with "no single priced move", then the next run minted yet another interposer. Normalize instead:
# an honest-absence marker is "no/without ... priced <noun>" or "price record/coverage ... <negation>"
# with a BOUNDED gap that never crosses a sentence boundary. The tuple stays for the fixed legacy
# phrases (and for the decline-detection site, which keeps tuple-only semantics on purpose); this
# regex serves ONLY the episode magnitude-or-absence pin, where D-4's injected-window requirement
# (`all(_adj)`) already guarantees the bullet is about a REAL window.
_NO_PRICE_RX = re.compile(
    r"\bno\b[^.;!?]{0,40}?\bpriced?\s+(?:move|record|data|magnitude|response|change)\b"
    r"|\bwithout\b[^.;!?]{0,30}?\bpriced?\s+(?:move|record|magnitude|response)\b"
    r"|\bprice\s+(?:record|coverage|data)\b[^.;!?]{0,30}?"
    r"\b(?:does\s+not|doesn'?t|is\s+silent|never|cannot|can'?t|stops?|ends?)\b"
    r"|\b(?:outside|before|beyond|predates?)\b[^.;!?]{0,30}?\bprice\s+(?:coverage|record|data)\b",
    re.I)


def _absence_marked(line: str) -> bool:
    """True when an episode bullet honestly declares the price record does not reach it."""
    return _has_any(line, _NO_PRICE_RECORD) or bool(_NO_PRICE_RX.search(line))


def _has_any(text: str, tokens) -> bool:
    low = str(text or "").lower()
    return any(t in low for t in tokens)


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
        # D-OJ-7(b): read the FIRST PRESENT guard-column stamp, not `release_date` alone. Only the
        # vintage tables carry `release_date`, so the backtest was a no-op on every data_date card --
        # including both new outcome legs, which stamp `_provenance` under the `date` key precisely so
        # this check has a day-grained value to read instead of the bare `year` a futures row carries.
        # The order is the guard-column order: the more specific publication axis wins where a row has
        # more than one.
        rd = ""
        for _k in ("release_date", "knowledge_date", "data_date", "week_ending_date", "date"):
            _v = str((prov or {}).get(_k) or "")
            if _v:
                rd = _v
                break
        if rd and leg_asof and rd > leg_asof:
            return False
    return True


def _cited_evidence(out: dict) -> list[dict]:
    """The kind=evidence citations the model actually CITED in its structured prose.

    Deliberately the _cascade_stats prose-scan idiom, NOT the structured.sources `ref` join the W4 plan
    sketches. The ledger `ref` is a BARE INTEGER matching the handle digit (answer.py:293-295), so [E1]
    and [N1] both reduce to ref 1 -- a ref join would credit an evidence citation on a turn where the
    model only ever wrote [N1], which is a false-pass on the exact axis these pins gate. And NEVER scan
    out['answer']: the '## Sources' footer re-renders every ledgered handle INCLUDING ones verify just
    stripped from prose (the primary-gate trap, _cascade_stats docstring)."""
    st = out.get("structured") or {}
    prose = f"{st.get('tldr') or ''} {st.get('mechanism') or ''}"
    return [c for c in (out.get("citations") or [])
            if c.get("kind") == "evidence" and f"[{c.get('id')}]" in prose]


def _cited_episode_clusters(out: dict) -> list[dict]:
    """Episode CLASSES implied by the dates of the cited evidence citations, via the shipped clustering
    primitive timeline.cluster() at episode-class grain. This is a CITATION-DATE SPREAD and nothing
    more -- see min_episodes_cited for what it can and cannot see."""
    from leviathan.graphrag import timeline as tl
    return tl.cluster([c.get("date") for c in _cited_evidence(out) if c.get("date")],
                      gap_days=_EPISODE_GAP_DAYS)


def _episode_section(mech: str) -> str | None:
    """The body of the reserved Episodes section, or None when it was not rendered.

    Fence-aware exactly as answer._sectionize is (a '## Episodes' inside a ```mermaid block is CONTENT),
    but two deliberate widenings over `_sectionize`'s exact-'## '-match (fold-pass 2026-07-30): the
    heading level may be `##`..`######`, and the heading text is matched on a NORMALISED PREFIX. The
    exact-match form scored zero lines for '## Episodes (3)', '## Episodes -- dated' and '### Episodes',
    reding min_episode_lines and episode_magnitude_or_absence on a correctly enumerated answer.

    The D3 producer LANDED 2026-07-31: answer._SYSTEM_EPISODES now fixes the shape at source (exactly
    '## Episodes', level two, one bullet per injected episode), gated on GRAPHRAG_TIMELINE. These two
    widenings STAY -- they are the fail-soft margin around a prompt-fixed shape, not a substitute for it,
    and a model that drifts to '### Episodes (3)' must still be scored on the episodes it enumerated."""
    body: list[str] | None = None
    in_fence = False
    for line in (mech or "").split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if body is not None:
                body.append(line)
            continue
        m = None if in_fence else re.match(r"^\s*#{2,6}\s+(.*)$", line)
        if m:
            if str(m.group(1)).strip().lower().startswith(_EPISODE_HEADING.lower()):
                body = []                                 # entering the section
            elif body is not None:
                break                                     # the next heading closes it
        elif body is not None:
            body.append(line)
    return "\n".join(body) if body is not None else None


def _episode_lines(out: dict) -> list[str]:
    """The dated-episode ENUMERATION lines of the reserved '## Episodes' section of structured.mechanism.

    Empty when the section was not rendered at all, which is why every pin built on this requires a
    NON-EMPTY list before it can pass -- `all([])` is vacuously true and an un-rendered section would
    otherwise false-green. Reads structured.mechanism (post-verify, post-sanitize), never out['answer']."""
    body = _episode_section(str((out.get("structured") or {}).get("mechanism") or ""))
    if body is None:
        return []
    return [ln for ln in body.split("\n")
            if _EPISODE_BULLET_RX.match(ln) and _EPISODE_YEAR_RX.search(ln)]


# ── W4-N1 / D-4: THE INJECTED-EPISODE GROUND TRUTH ───────────────────────────────────────────────────
# The set of episodes the engine ACTUALLY PUT IN THE PROMPT on this turn, stamped by answer._l2_blocks
# into trace['episodes_injected'] (records of {node, line, spans}). Before it existed, NOTHING downstream
# of the prompt could distinguish an ENUMERATED window from a MINTED one -- measured 2026-07-31: three
# wholly invented windows ("1873/1911/1962 pepper panics"), each saying only "no citable item in this
# window; no price record", greened ALL FIVE episode pins, and the same bullet repeated three times
# greened min_episode_lines: 3. Both exploits ran through _line_backed's absence branch, which is the
# 2026-07-30 fold-pass and MUST STAY (deleting it reds the HONEST receipt-less answer -- the exact
# behaviour W4 exists to reward). The fix is therefore not to remove the allowance but to require, on top
# of it, that the bullet's window is one the engine actually showed the model.
_YM_RX = re.compile(r"(?<!\d)((?:1[6-9]\d{2}|20\d{2}))-(0[1-9]|1[0-2])(?!\d)")
_SPAN_YEARS_CAP = 60                                      # a sane bound on year-fallback widening


def _injected_episodes(out: dict) -> list[dict]:
    """The dated episodes this turn's prompt actually carried, flattened across nodes.

    Reads the EXISTING trace plumbing (answer._l2_blocks -> sg.trace -> out['trace']); it never
    re-derives episodes from the artifact, because what must be graded is what the model was SHOWN, not
    what the artifact holds. Empty on the OFF arm by construction (timeline.episodes_for returns [] with
    the kill-switch off, so no line is rendered and no record is stamped) and empty on any turn whose
    trace was not captured -- which is FAIL-CLOSED for the pins below: a bullet can then match nothing."""
    eps: list[dict] = []
    for rec in ((out.get("trace") or {}).get("episodes_injected") or []):
        node = str((rec or {}).get("node") or "")
        for sp in (rec or {}).get("spans") or []:
            start, _, end = str(sp).partition("..")
            if len(start) >= 7:
                eps.append({"node": node, "span": str(sp), "start": start[:7], "end": (end or start)[:7]})
    return eps


def _span_years(ep: dict) -> set[str]:
    """Every calendar year an injected episode spans (inclusive), as strings."""
    try:
        y0, y1 = int(ep["start"][:4]), int(ep["end"][:4])
    except (KeyError, TypeError, ValueError):
        return set()
    if y1 < y0 or (y1 - y0) > _SPAN_YEARS_CAP:
        return {str(y0)}
    return {str(y) for y in range(y0, y1 + 1)}


def _line_targets(line: str, injected: list[dict]) -> set[int]:
    """Indices of the injected episodes a bullet could be enumerating; EMPTY = the window was minted.

    TWO-TIER, and WHICH TIER APPLIES IS DECIDED BY THE BULLET, not by whether tier 1 happened to hit.

    TIER 1 -- the bullet renders at least one YEAR-MONTH token. Then it must name an ENDPOINT of an
    injected span. That is the shape _SYSTEM_EPISODES instructs ('<YYYY-MM>..<YYYY-MM>', full four-digit
    years on both ends, read off the injected line, which renders the same e['start'][:7]/e['end'][:7]
    strings this record stamps), so a bullet precise enough to write year-months has no excuse for writing
    year-months the engine never showed it.
    TIER 2 -- the bullet renders NO year-month at all ('- 1994 Brazil frost: ...'). That is correct
    enumeration in a coarser hand, and reding it would manufacture the A-7 false-red class, so a
    YEAR-level overlap with the injected span is accepted.

    THE TIER-1 STRICTNESS IS DELIBERATE AND IT CLOSES A RESIDUAL. If tier 2 were a FALLBACK reached
    whenever tier 1 missed, a bullet could mint a narrower window INSIDE a real injected span --
    '2002-06..2002-09 -- the great drought: no citable item ...' against an injected 2001-11..2003-04 --
    and be scored as an enumeration of it. That is precisely the confabulation shape P3 exists to catch
    (a narrated event in a window the timeline does not carry), so it must red. The cost is a bullet that
    writes an interior month instead of the span it was shown; that is a departure from the instructed
    shape, and a false RED on a deterministic pin is visible in the row table while a false GREEN is not."""
    yms = {f"{y}-{m}" for y, m in _YM_RX.findall(line or "")}
    if yms:
        return {i for i, e in enumerate(injected) if yms & {e["start"], e["end"]}}
    years = set(_EPISODE_YEAR_RX.findall(line or ""))
    return {i for i, e in enumerate(injected) if years & _span_years(e)}


def _max_matching(adj: list[set[int]]) -> int:
    """Max bipartite matching lines -> injected episodes (Kuhn's). The DISTINCTNESS half of the fix.

    Counting `len(set().union(*adj))` would be wrong in the permissive direction and picking one 'best'
    target per line would be wrong in the restrictive one: three copies of ONE bullet must count as ONE
    enumerated episode (the repeat exploit), while two honest bullets whose year-fallback sets overlap
    (adjacent injected windows sharing a calendar year) must still count as TWO. A matching is the exact
    answer to 'how many DISTINCT injected episodes did this section enumerate'. Sizes are tiny (<= a
    handful of bullets, <= timeline.MAX_PER_NODE per node), so the O(V*E) form is free."""
    match_r: dict[int, int] = {}

    def _augment(u: int, seen: set[int]) -> bool:
        for v in sorted(adj[u]):
            if v in seen:
                continue
            seen.add(v)
            if v not in match_r or _augment(match_r[v], seen):
                match_r[v] = u
                return True
        return False

    return sum(1 for u in range(len(adj)) if _augment(u, set()))


def _episode_enumeration(out: dict) -> tuple[list[str], list[set[int]], int]:
    """(bullets, per-bullet injected-episode candidates, DISTINCT injected episodes enumerated)."""
    lines = _episode_lines(out)
    injected = _injected_episodes(out)
    adj = [_line_targets(ln, injected) for ln in lines]
    return lines, adj, _max_matching(adj)


# ── A5: THE RECEIPT-LESS EPISODE LABEL ───────────────────────────────────────────────────────────────
# W4 A/B (2026-07-31) measured the leak: on a window with NO citable item the model dressed the label slot
# into an event narrative -- "earlier Black Sea disruption window", "post-ban window" -- which the record
# cannot support, while the two ABSENCE slots underneath it were both stated correctly. `_SYSTEM_EPISODES`
# now says the CASE 1 label is the injected line's OWN label (the node name) copied verbatim; this is the
# deterministic reading of that rule, so the change is scored by the harness rather than by the panel.
#
# THE RULE, and why it is containment rather than equality: the label's tokens must be a SUBSET of the
# injected node id's tokens. Dropping a token ('black sea disruption' for `black_sea_export_disruption`)
# is a shortening, not an invention; ADDING one is exactly the failure -- every observed leak added a
# characterisation word. Equality would red an honest bullet for a dropped word, and a false RED on a
# deterministic pin is cheap only when it is rare.
_LABEL_SPLIT_RX = re.compile(r"\s+--\s+|\s+—\s+|\s+–\s+")
_LABEL_TOKEN_RX = re.compile(r"[a-z0-9]+")
# Structural words a label may carry without naming anything the record does not hold.
_LABEL_STOPWORDS = frozenset({"the", "a", "an", "of", "in", "for", "and", "to", "on", "window", "episode",
                              "period", "era"})


def _label_tokens(text: str) -> set[str]:
    return {t for t in _LABEL_TOKEN_RX.findall((text or "").lower())
            if t not in _LABEL_STOPWORDS and not t.isdigit()}


def _episode_label_of(line: str) -> str | None:
    """The LABEL slot of a bullet: the text between the span separator ('--') and the first ':'. None when
    the bullet does not carry the instructed shape at all (no separator or no colon) -- that is a shape
    failure the other episode pins already own, so this one declines to double-charge it."""
    body = _LABEL_SPLIT_RX.split(line or "", maxsplit=1)
    if len(body) < 2:
        return None
    head, sep, _rest = body[1].partition(":")
    return head.strip() if sep else None


def _absence_label_ok(line: str, targets: set[int], injected: list[dict]) -> bool:
    """One receipt-less bullet's label names one of the injected episodes it enumerates, and nothing else."""
    label = _episode_label_of(line)
    if label is None:
        return True                      # not the instructed bullet shape -- other pins own that failure
    toks = _label_tokens(label)
    if not toks:
        return True                      # an empty/structural label invents nothing
    return any(toks <= _label_tokens(str(injected[i].get("node") or "")) for i in sorted(targets))


# ── W3 CURVE / TERM-STRUCTURE pins (PRICE_AND_PLAYBOOKS item 23, plan :1014) ──────────────────────────
# silver_futures_eod is the PER-DELIVERY-MONTH table whitelisted 2026-07-30. Every pin below reads the
# ROWS the model was actually handed plus the PROSE it wrote about them -- never out['answer']'s '##
# Sources' footer, whose citation labels re-render figures the verifier may have stripped.
#
# WHERE THE ROWS COME FROM, and why it is two sources. `citations[].payload.rows` is TRUNCATED to the
# first three rows (citations.from_number:129); `out['number_calls']` is the FULL, untruncated list, and
# BOTH orchestrator lanes attach it (run_numbers_only:91, run_hybrid:296) -- but answer.answer()'s own
# return dict does NOT (answer.py:1045/1370), so a non-orchestrator consumer has only the slice. Reading
# both surfaces means the pins mean the same thing however the turn was produced, and the truncation
# cannot under-count a curve: `_total_order` sorts data_date first and contract_month ahead of unit, so
# the first three rows of a multi-expiry read at one as-of are three DIFFERENT expiries, while a
# single-expiry read across three dates is correctly NOT a curve.
_EOD_TABLE = "silver_futures_eod"
_EOD_MONTH_RX = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


def _eod_rows(out: dict) -> list[dict]:
    """Every VALUED silver_futures_eod row this turn (citation payloads + number_calls, deduped by the
    (contract_month, date, value) triple). A row with no value is a declined/errored probe, never a read."""
    seen: list[dict] = []
    for c in _num_citations(out):
        if (c.get("locator") or {}).get("table") == _EOD_TABLE:
            seen += [r for r in ((c.get("payload") or {}).get("rows") or []) if isinstance(r, dict)]
    for call in (out.get("number_calls") or []):
        if isinstance(call, dict) and ((call.get("query") or {}).get("table")) == _EOD_TABLE:
            seen += [r for r in (call.get("rows") or []) if isinstance(r, dict)]
    rows, keys = [], set()
    for r in seen:
        if r.get("value") in (None, ""):
            continue
        k = (str(r.get("contract_month") or ""), str(r.get("data_date") or r.get("knowledge_date") or ""),
             str(r.get("value")))
        if k not in keys:
            keys.add(k)
            rows.append(r)
    return rows


def _eod_months(out: dict) -> set[str]:
    """The DELIVERY MONTHS ('YYYY-MM') actually served this turn. Empty for the two CEPEA cash references
    (contract_month is NULL there by design -- `instrument_kind` makes that legal) and for every declined
    or coverage-routed turn, which is exactly what the `false` pins assert."""
    return {str(r.get("contract_month") or "")[:7] for r in _eod_rows(out)
            if _EOD_MONTH_RX.match(str(r.get("contract_month") or "")[:7])}


def _eod_requested(out: dict) -> set[str]:
    """The delivery months the recorded QUERIES named ('2026-12' or the comma-separated curve form). Served
    is what came back; requested is what was asked for -- and on the hybrid lane the two can differ purely
    because the citation payload is truncated, which is why the invention check reads their union."""
    out_set: set[str] = set()
    specs = [((c.get("payload") or {}).get("query") or {}) for c in _num_citations(out)]
    specs += [(c.get("query") or {}) for c in (out.get("number_calls") or []) if isinstance(c, dict)]
    for q in specs:
        if q.get("table") != _EOD_TABLE:
            continue
        for m in str(q.get("contract_month") or "").split(","):
            if _EOD_MONTH_RX.match(m.strip()):
                out_set.add(m.strip())
    return out_set


def _eod_rows_truncated(out: dict) -> bool:
    """True when the ONLY row surface is the citation payload's three-row slice and that slice is FULL --
    the point past which `served` may be a strict subset of what the engine actually returned. A turn
    produced by answer.answer() directly is in that state for any curve of four or more expiries, so the
    invention half of expiry_labeled is stood down there rather than convicting a correct answer for
    naming the fifth expiry of a curve whose payload stopped at three. On a --via-orchestrator run (how
    this deck is scored) BOTH lanes attach the full list, so the check stays live where it matters."""
    if out.get("number_calls"):
        return False
    return any(len(((c.get("payload") or {}).get("rows") or [])) >= 3
               for c in _num_citations(out) if (c.get("locator") or {}).get("table") == _EOD_TABLE)


def _eod_kinds(out: dict) -> set[str]:
    return {str(r.get("settle_kind") or "").strip() for r in _eod_rows(out)} - {""}


def _prose(out: dict) -> str:
    """The text these pins scan: STRUCTURED tldr+mechanism when the turn rendered one (hybrid/reasoning),
    else out['answer'] with the '## Sources' footer CUT. numbers_only turns have structured=None, so a
    structured-only scan would be silent on the whole numbers lane -- and the footer is cut because it
    re-renders every ledgered citation label (the primary-gate trap, _cascade_stats)."""
    st = out.get("structured") or {}
    if st:
        return f"{st.get('tldr') or ''}\n{st.get('mechanism') or ''}"
    return re.split(r"\n#{2,6}\s+Sources\b", str(out.get("answer") or ""))[0]


_MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTH_ALT = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
# HARD forms -- a delivery-month label and nothing else, in any prose: the ISO month ('2026-12', never the
# '2014-01-02' inside a full date) and the ticker form ('Dec-26', 'Dec-2026', "Dec '26"). The bare-space
# variant ('Dec 26') is DELIBERATELY EXCLUDED: it collides with a day-of-month ('May 26').
_EXPIRY_ISO_RX = re.compile(r"(?<!\d)(20\d{2})-(0[1-9]|1[0-2])(?!-?\d)")
_EXPIRY_TICKER_RX = re.compile(rf"\b({_MONTH_ALT})[a-z]*\.?\s?(?:[-–]\s?|['’])(\d{{2}}|\d{{4}})(?!\d)", re.I)
# CUE form -- a month, an OPTIONAL 4-digit year, then a contract/price cue IMMEDIATELY after ('December
# 2026 corn', 'the December contract', 'December 2026 settlement'). Adjacency is what keeps it honest:
# 'in June 2012 the continuous close was 738.50' has 'the' in the slot and does NOT match.
_EXPIRY_CUE_RX = re.compile(
    rf"\b({_MONTH_ALT})[a-z]*\.?\s+(?:(20\d{{2}})\s+)?"
    r"(?:corn|soybeans?|soybean|beans|wheat|coffee|cocoa|sugar|cotton|rice|canola|maize|"
    r"orange juice|palm|rapeseed|meal|oil|contract|contracts|expiry|expiries|expiration|delivery|"
    r"futures|board|settle|settles|settled|settlement|close)\b", re.I)


def _expiry_tokens(text: str) -> tuple[set[str], set[int], set[str]]:
    """(hard, bare, soft) delivery-month labels found in `text`.

    hard -- 'YYYY-MM' from the two UNAMBIGUOUS forms. These are the only ones the `false` branch reads,
            because they never occur in narrative prose except as an expiry label.
    bare -- month NUMBERS from a yearless named-contract form ('the December contract'), also unambiguous.
    soft -- 'YYYY-MM' from the year-carrying cue form. Read ONLY on the `true` branch. A four-digit year
            beside a month is genuinely ambiguous between a calendar date and an expiry ('December 2010
            corn was 629' vs 'between December 2009 and December 2010'), so it can CREDIT an answer that
            named its expiry but must never CONVICT one that merely dated a sentence. Say it plainly: on
            the `false` branch this pin cannot see an invented 'December 2010 corn' -- that half is the
            judge's, and the numbers_mismatched counter's."""
    hard: set[str] = set()
    bare: set[int] = set()
    soft: set[str] = set()
    for y, m in _EXPIRY_ISO_RX.findall(text or ""):
        hard.add(f"{y}-{m}")
    for mon, yy in _EXPIRY_TICKER_RX.findall(text or ""):
        yr = yy if len(yy) == 4 else f"20{yy}"
        hard.add(f"{yr}-{_MONTH_NUM[mon.lower()[:3]]:02d}")
    for mon, yr in _EXPIRY_CUE_RX.findall(text or ""):
        n = _MONTH_NUM[mon.lower()[:3]]
        if yr:
            soft.add(f"{yr}-{n:02d}")
        elif n != 5:
            bare.add(n)          # 'May' is also a modal verb: 'prices may close higher' is not an expiry.
            #                      With a year beside it ('May 2027 corn') the ambiguity is gone, so the
            #                      soft branch above keeps May; only the YEARLESS form drops it.
    return hard, bare, soft


# The settle_kind vocabulary a served row must be NARRATED with (the card: "ALWAYS cite it together with
# the row's settle_kind"). The MISLABEL half is the ICE trap the card names in as many words -- ohlcv-1d
# session closes must never be called an official settlement (the `statistics` settlement schema was
# deliberately not purchased) -- and it is scoped to that one high-precision phrase on purpose.
_SETTLE_KIND_PHRASES = {
    "settlement": (r"settlement", r"\bsettled\b", r"\bsettles\b"),
    "close": (r"session close", r"closing price", r"\bclose[sd]?\b"),
    # CEPEA's own published name for the series is the *Indicador*, so 'indicator' is the natural English
    # rendering and a five-phrase list made two of twelve deck rows ride on the model echoing the
    # settle_kind token verbatim: "the CEPEA arabica indicator ... a physical-market benchmark, not a
    # futures contract" and "a daily spot reference ... a physical quotation" both FAILED while being
    # exactly right. Widened 2026-07-31; every added form still excludes the futures vocabulary, which is
    # the only separation this pin needs.
    "cash_index": (r"cash index", r"cash[- ]market index", r"cash reference", r"spot index", r"physical cash",
                   r"\bindicator\b", r"spot (?:reference|quotation|price)",
                   r"physical(?:-| )market (?:reference|benchmark|quotation)"),
    "mark_to_market": (r"mark[- ]to[- ]market", r"\bMTM\b"),
}
_SETTLE_MISLABEL_RX = re.compile(r"official (?:exchange )?settlement|exchange settlement", re.I)
# An ABSENCE / negation cue. The mislabel test is a CLAIM test, not a keyword scan: the deck's ICE
# provenance row literally ASKS for "the official settlement price", so the most correct possible answer
# has to say those words in order to deny them ("there is no official settlement series for ICE cocoa in
# this data; what it carries is the ohlcv-1d session close"). A bare keyword scan convicted THAT answer
# and passed the evasive one that never says them -- the row rewarded evasion and punished the honest
# denial, on the deck's designated provenance trap. Scoped to the SENTENCE carrying the phrase, so a
# denial and a claim in the same answer are judged separately.
_SETTLE_NEGATION_RX = re.compile(
    r"(?:\bno\b|\bnot\b|n't|\bnever\b|\bnone\b|\bnothing\b|\bneither\b|\bnor\b|rather than|instead of|"
    r"as opposed to|\bunavailable\b|\babsent\b|\blacks?\b|\blacking\b|\bwithout\b|\bunpurchased\b|"
    r"\bisn\b|\baren\b|\bwasn\b|\bweren\b|\bdoesn\b|\bdon\b|\bcannot\b)", re.I)


def _settle_mislabeled(text: str) -> bool:
    """True only when an 'official/exchange settlement' phrase is ASSERTED of the served figure -- i.e. it
    appears in a sentence carrying no negation/absence cue."""
    for sent in re.split(r"(?<=[.;:!?])\s+|\n+", text or ""):
        if _SETTLE_MISLABEL_RX.search(sent) and not _SETTLE_NEGATION_RX.search(sent):
            return True
    return False


_CASCADE_EXPECT = ("cascade_fired", "min_cascade_cited", "delta_row", "fork", "absence",
                   "pit_clean", "su_prescaled", "ok_era_leg", "reroute_fired",
                   "opposite_country_legs", "two_countries_cited", "no_unbacked_fork",
                   # D-DT-2 c1: the BASIS-AWARE sibling of no_unbacked_fork. A SPLIT, never a loosening --
                   # no_unbacked_fork keeps byte-identical numeric semantics on the 5 cascade/pace rows it
                   # was designed for; fork_licensed replaces it on the 2 playbook rows where the numeric
                   # basis is structurally absent and the QUESTION TEXT demands the heading.
                   "fork_licensed",
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
                   "pattern_cited", "pattern_zero_cited", "pattern_register_clean",
                   # W4 EVENT PLAYBOOKS (D6 + skeptic F-J + W2b-D5). min_episodes_cited /
                   # min_episode_sources / episode_absence_stated are the D6 three; min_episode_lines is
                   # the F-J deterministic complement (enumeration is otherwise judge-only) and
                   # episode_magnitude_or_absence is the W2b-D5 price-side twin of F-I.
                   "min_episodes_cited", "min_episode_sources", "episode_absence_stated",
                   "min_episode_lines", "episode_magnitude_or_absence",
                   # A5's deterministic pin: on a receipt-less bullet the LABEL must be the injected
                   # line's own node label, never a characterisation the record cannot support.
                   "episode_absence_label_fixed",
                   # W5 OUTLOOK (D5b + D7 + the A2 fence). price_target_backed is the wave's PRIMARY
                   # deterministic teeth and REPLACES `banned_valuation: 0` as the outlook gate: every
                   # emitted level traces to a cited surface with its arithmetic shown. banned_exec is the
                   # A2 pin -- 0 on EVERY row, outlook included, because nothing can back an execution
                   # instruction. directional_claim_backed is the D7 companion on any row carrying a lean.
                   # max_banned_valuation / max_banned_flow are CEILINGS, not equalities: on an outlook row
                   # A1 and flow vocabulary are permitted BY DESIGN, so `banned_valuation: 0` is the wrong
                   # shape there -- but "permitted" must not mean "free", so the deck caps them instead.
                   # The existing zero-pins keep their equality semantics for every non-outlook deck.
                   "price_target_backed", "banned_exec", "directional_claim_backed", "outlook_rendered",
                   "max_banned_valuation", "max_banned_flow",
                   # W3 CURVE / TERM STRUCTURE (item 23). curve_cited = >=2 DISTINCT delivery months were
                   # served this turn (a term-structure read, not a level); expiry_labeled = the answer says
                   # WHICH expiry its number is -- the card's "never quote a bare level as 'the price'" --
                   # and its FALSE branch is the anti-invention half a cash-index or pre-coverage turn needs;
                   # settle_kind_stated = the served row's own settle_kind is narrated (and an ICE session
                   # close is never called an official settlement). futures_coverage_route is the W3.2
                   # decline-matrix teeth: trace-key equality (the price_decline_guard idiom) on the
                   # coverage verdict BOTH lanes stamp -- 'legacy' | 'straddle' | 'uncovered', list-tolerant
                   # like chain_decline_reason, with 'absent' accepting an un-routed (fully covered) turn.
                   "curve_cited", "expiry_labeled", "settle_kind_stated", "futures_coverage_route")


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
        elif k == "fork_licensed":
            # D-DT-2 c1. SAME one-directional text rule as no_unbacked_fork, SAME heading test, in the
            # same place (eval owns the heading, answer owns the basis -- the clean split 2.2(c) draws);
            # only the LICENSE INVENTORY is wider. FAIL iff the heading rendered and EVERY basis flag is
            # false. `numeric` is byte-for-byte the old predicate, so this is a STRICT SUPERSET: no turn
            # that passes no_unbacked_fork today can fail fork_licensed tomorrow.
            #
            # WHY THIS EXISTS. The old pin fires on two NUMERIC trace conditions written by the cascade
            # engine alone, while the persona licenses the heading at FOUR sites of which only one is
            # trace-backed. On pb_brazil_drought_vs_frost / pb_disagree_eras the numeric basis is
            # structurally unreachable (the episode layer contributes no fork) and the question asks
            # "where do the episodes disagree" -- so the red was the pin meeting a population it was not
            # written for, and it was UNINFORMATIVE rather than false.
            #
            # MISSING BASIS => UNLICENSED, deliberately fail-closed. Both answer.py bodies mint the key
            # (V-9), so an absent basis means the turn came from neither -- a numbers_only lane, which
            # carries no structured mechanism at all, so `heading` is False and the row passes anyway.
            basis = ((out.get("trace") or {}).get("fork_basis")) or {}
            licensed = any(bool(v) for v in basis.values())
            heading = "## Where the record disagrees" in mech
            res[k] = (not (heading and not licensed)) if bool(want) else True
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
            # W3 FLIP (2026-07-30): silver_futures_eod joins the set the day it is whitelisted. It is a
            # price table with GOVERNED units (unit_overrides, three-way lint-bound to CONTRACT_MAP), so a
            # served per-expiry settle satisfies price_cited, and unit_present becomes the exchange-unit
            # discipline on ten currencies (c/bu, USD/mt, BRL/60-kg bag, ...) with no FX conversion anywhere.
            pc = [c for c in cits if (c.get("locator") or {}).get("table") in ("silver_pink_sheet", "silver_wasde", "silver_futures_prices", "silver_futures_eod")
                  and c.get("value") is not None]
            if k == "price_cited":
                res[k] = bool(pc) == bool(want)
            else:                                                     # unit_present
                res[k] = (bool(pc) and all((c.get("unit") or "").strip() for c in pc)) == bool(want)
        elif k == "price_decline_guard":                              # NONE-tier decline: trace-key equality to
            res[k] = ((out.get("trace") or {}).get("price_decline_guard")) == want   # the guard slug (agent.py:412)
        elif k == "curve_cited":
            # W3 item 23. A TERM-STRUCTURE read: >= 2 DISTINCT delivery months came back VALUED this turn.
            # Row-based, not prose-based, for the same reason price_cited is: it asserts the engine actually
            # served a curve, which is the thing the flip made possible and the thing a decline must NOT do.
            # The FALSE branch is the load-bearing half -- a straddling window, an uncovered contract, a
            # pre-coverage legacy level and a CEPEA cash index must every one of them fail to produce two
            # expiries, and if one ever does, the coverage guard has been bypassed.
            res[k] = (len(_eod_months(out)) >= 2) == bool(want)
        elif k == "expiry_labeled":
            # W3 item 23, the card's "never quote a bare level as 'the price'" rendered deterministic.
            # TRUE  -- at least one expiry was SERVED and the prose NAMES one of the served months, and no
            #          UNAMBIGUOUS label (ISO / 'Dec-26' / 'the December contract') points at a month that
            #          was not served. Nearest-listed-expiry is a tie-break, not the front month: an answer
            #          that quotes the level without saying which delivery month it is fails here.
            # FALSE -- no unambiguous delivery-month label appears at all. This is the anti-invention half
            #          for the two CEPEA cash references (contract_month IS NULL), for a pre-coverage level
            #          off the roll-spliced continuous series, and for a declined curve. See _expiry_tokens
            #          for the one thing it cannot see (a year-carrying 'December 2010 corn' invention).
            served = _eod_months(out)
            hard, bare, soft = _expiry_tokens(_prose(out))
            served_nums = {int(m[5:7]) for m in served}
            if want:
                named = bool(((hard | soft) & served) or (bare & served_nums))
                # INVENTION reference = served UNION requested, and stood down entirely when the row
                # surface is a full three-row payload slice (see _eod_rows_truncated). The POSITIVE half
                # never relaxes: a served month must still be named.
                known = served | _eod_requested(out)
                known_nums = {int(m[5:7]) for m in known}
                invented = (bool(hard - known) or bool(bare - known_nums)) and not _eod_rows_truncated(out)
                res[k] = bool(served) and named and not invented
            else:
                res[k] = not hard and not bare
        elif k == "settle_kind_stated":
            # W3 item 23. Every DISTINCT settle_kind served this turn is narrated in the answer's own words
            # (settlement / session close / cash index / mark-to-market), AND the ICE mislabel is absent:
            # an ohlcv-1d session close called an "official settlement" fails even if the word 'close' also
            # appears, because that sentence is the exact provenance claim the card forbids.
            kinds = _eod_kinds(out)
            txt = _prose(out)
            said = bool(kinds) and all(any(re.search(p, txt, re.I) for p in _SETTLE_KIND_PHRASES.get(kd, ()))
                                       for kd in kinds)
            mislabel = "settlement" not in kinds and _settle_mislabeled(txt)
            res[k] = (said and not mislabel) == bool(want)
        elif k == "futures_coverage_route":
            # W3.2 decline matrix, live-lane teeth. Trace-key equality on the coverage verdict (the
            # price_decline_guard idiom), list-tolerant with an 'absent' token (the chain_decline_reason
            # idiom): BOTH lanes stamp trace.futures_coverage_guard -- run_numbers_only copies it off the
            # agent's return dict, run_hybrid reads it off the payload the reasoner consumes (#144). The
            # value is the ROUTE, decided before any SQL compiled, so this pin says which of serve/legacy/
            # straddle/uncovered the measured floor actually produced -- not what the prose claims.
            allowed = list(want) if isinstance(want, (list, tuple)) else [want]
            got = (out.get("trace") or {}).get("futures_coverage_guard")
            res[k] = (got in allowed) or (got is None and ("absent" in allowed or None in allowed))
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
        elif k == "price_target_backed":
            # W5.0, the wave's PRIMARY deterministic teeth. Reads the RAW pre-sanitize counter stamped at
            # answer.py, exactly like banned_valuation/banned_flow -- so it asserts the model never EMITTED
            # an unbacked level, which is strictly stronger than asserting the strip removed one. A level is
            # BACKED when it is cited, or when the unit shows spot -> moves -> implied levels with every
            # INPUT cited (register.outlook_derivation_ok). This REPLACES `banned_valuation: 0` as the
            # outlook gate and has teeth the lexicon never had: it catches the fabricated number
            # ('$4.85' with nothing behind it), which is the class this platform exists to refuse.
            res[k] = (int((out.get("trace") or {}).get("unbacked_levels") or 0) == 0) == bool(want)
        elif k == "banned_exec":
            # W5: A2 EXECUTION/ADVICE raw count. Pinned 0 on EVERY row including outlook -- the platform has
            # no position, no sizing and no risk model, so "go long here" is unbacked BY CONSTRUCTION, which
            # is the same test the now-permitted A1 passes and A2 cannot.
            res[k] = int((out.get("trace") or {}).get("banned_exec_words") or 0) == int(want)
        elif k == "outlook_rendered":                                 # the three-leg gate actually fired
            res[k] = bool((out.get("trace") or {}).get("outlook_mode")) == bool(want)
        elif k in ("max_banned_valuation", "max_banned_flow"):        # CEILINGS on the raw DP-6 counters
            _key = ("banned_valuation_words" if k == "max_banned_valuation" else "banned_flow_words")
            res[k] = int((out.get("trace") or {}).get(_key) or 0) <= int(want)
        elif k == "directional_claim_backed":
            # W5 D7. PLANNER-AWARE (the plan's version was L2-only): `fired_regimes` is stamped ONLY by
            # _answer_l2; the one-hop trace carries `regimes` instead, so a GRAPHRAG_PLANNER=onehop run --
            # the documented L2 rollback path -- would silently degrade this pin to its cascade disjunct.
            # Read BOTH keys plus the cited-cascade count, so the pin means the same thing on either planner.
            _tr = out.get("trace") or {}
            _fired = _tr.get("fired_regimes") or _tr.get("regimes") or []
            res[k] = (bool(_fired) or cs["n_cited"] > 0) == bool(want)
        elif k == "min_episodes_cited":
            # W4 D6. SAY IT PLAINLY (skeptic F-J): this is a CITATION-DATE-SPREAD pin and it CANNOT SEE
            # ENUMERATION. It clusters the DATES of the evidence citations the model actually cited and
            # asserts >= N distinct episode classes. An answer that smooths every episode into one
            # "usually" while citing items dated 1994, 2010 and 2022 PASSES this pin -- enumeration is a
            # property of the PROSE SHAPE and on that axis this key is silent. Enumeration is therefore
            # JUDGE-ONLY (the episode_enumeration axis -- which as of 2026-07-31 actually EXISTS in
            # _judge_tool and _JUDGE_SYS; until then this sentence, the deck's :497 and its :1498 all
            # deferred to an axis that was never built) plus the deterministic complement
            # min_episode_lines below; do not describe this key alone as "the deterministic teeth".
            # What it DOES buy: filtering to CITED citations makes it a CITATION pin rather than a
            # RETRIEVAL pin -- the doctrine distinction the RV2 pins draw at reroute_v2_expected.
            #
            # F-K, RECORDED HERE SO THE D8 DECK AUTHOR CANNOT MISS IT. Row P3 (pb_coffee_frost_honest,
            # the honesty flagship) must NOT pin min_episodes_cited: 2. That silently requires a
            # 1994-DATED citation to survive top-K, and the census says 1994 Brazil frost is 11 props,
            # single-source (wb_cmo_outlook) -- so P3 would fail on a CORRECT answer, the same failure
            # the plan explicitly anticipates for P6 and explicitly warns the judge about ("never
            # penalize honest thinness"). RESOLUTION: lower it, do not relabel it conditional. P6 is
            # allowed to be conditional because P6 is EXPECTED TO FAIL and that failure IS its finding;
            # P3 is the flagship and must PASS on the honest answer or the wave has no green flagship.
            # P3 pins: min_episodes_cited: 1, episode_absence_stated: true, min_episode_lines: 2,
            # episode_magnitude_or_absence: true -- the two-episode expectation moves to min_episode_lines
            # (which the honesty allowance below makes retrieval-ROBUST) and to the judge axis.
            res[k] = len(_cited_episode_clusters(out)) >= int(want)
        elif k == "min_episode_sources":
            # W4 D6. DISTINCT sources across the cited evidence citations -- the deterministic teeth
            # behind "show where the episodes disagree" (two sources that agree is still two sources,
            # but ONE source cannot disagree with itself). This is what would have failed the 1994-frost
            # row: 11 of 11 props are wb_cmo_outlook.
            srcs = {str(c.get("source") or "").strip() for c in _cited_evidence(out)} - {""}
            res[k] = len(srcs) >= int(want)
        elif k == "episode_absence_stated":
            # W4 D6. The honesty leg: the answer SAYS the record is thin / an episode is not in the
            # corpus / not in the price record, rather than quietly enumerating fewer episodes. Reuses
            # the shipped _NOT_KNOWN token scan (score():leakage_ok) widened by the two W4 marker
            # vocabularies. Scans STRUCTURED prose, not out['answer'] (the footer trap).
            _txt = f"{(out.get('structured') or {}).get('tldr') or ''} {mech}"
            got = _has_any(_txt, _NOT_KNOWN + _NO_CITABLE + _NO_PRICE_RECORD)
            res[k] = got == bool(want)
        elif k == "min_episode_lines":
            # SKEPTIC F-J's deterministic complement to min_episodes_cited: count the dated-episode
            # lines the '## Episodes' section actually enumerates and bound them by the cited episode
            # classes. Catches BOTH failure directions with no new engine:
            #   smoothing      -- fewer lines than cited episode classes (the "usually" answer)
            #   confabulation  -- more lines than cited episode classes (episodes minted from nothing)
            #
            # DELIBERATE DEVIATION from F-J's literal `episode_lines == len(clusters)`. Strict equality
            # FAILS THE HONESTY LEG BY CONSTRUCTION and would ship the very defect W4 exists to fix: an
            # episode whose window the semantic top-K missed (F-I: 1994 frost, USSR 1972-79, grain deal
            # 2023) contributes an enumeration LINE but no cited citation and therefore no cluster, so
            # the correct honest answer -- enumerate it and state it has no citable item -- would be
            # scored as confabulation.
            #
            # AND the AGGREGATE cluster bound is gone entirely (fold-pass 2026-07-30). `_n_cl` counts
            # CITATION-DATE clusters and `len(_lines)` counts PROSE lines; they are not the same quantity
            # and the old `_n_cl <= len(_lines) <= _n_cl + _n_abs` red a CORRECT answer in both
            # directions -- 3 correctly enumerated episodes that ALSO cite today's balance sheet and a
            # background item yield 5 clusters vs 3 lines and failed, and two cited items inside one
            # episode window yield 2 clusters vs 3 lines and failed. Citing extra context evidence is
            # desirable behaviour, not confabulation, and the lower bound had no honesty rationale at all
            # (smoothing is already caught by `len(_lines) >= want`).
            #
            # The replacement is PER LINE, which is what "confabulation" actually means and is immune to
            # how many unrelated items the answer cites. A line is BACKED when it (a) declares its own
            # absence, (b) names a year some CITED evidence item is dated in, or (c) carries the handle of
            # a citation the model actually cited.
            #
            # D-4, THE VACUITY FIX (2026-07-31). Backing alone is NOT enough, and the (a) branch is why:
            # a wholly INVENTED window that merely SAYS "no citable item in this window" satisfies (a), so
            # three minted "pepper panics" greened this pin and the same bullet repeated three times
            # greened `min_episode_lines: 3` -- MEASURED, not hypothesised. The absence branch cannot be
            # deleted (it is the 2026-07-30 fold-pass; without it the HONEST receipt-less enumeration --
            # the behaviour this wave exists to reward -- reds). So the pin now asserts TWO things about
            # every bullet, and the second one is the ground truth the scorer never had:
            #   BACKED    -- unchanged, `_line_backed` below;
            #   INJECTED  -- its window matches an episode the ENGINE ACTUALLY PUT IN THE PROMPT this turn
            #                (trace['episodes_injected'], stamped at answer._l2_blocks).
            # plus a DISTINCTNESS bound: `want` DISTINCT injected episodes must be enumerated, so N copies
            # of one bullet count once. An answer can no longer reach a count by minting windows or by
            # repeating one. Note this makes the pin fail-CLOSED on a turn with no injected record (OFF
            # arm, one-hop, dead artifact): those turns render no '## Episodes' section anyway, and a
            # false RED on a deterministic pin is visible in the row table while a false GREEN is not.
            _lines, _adj, _distinct = _episode_enumeration(out)
            _cited = _cited_evidence(out)
            _cyears = {str(c.get("date") or "")[:4] for c in _cited} - {""}
            _cids = {str(c.get("id") or "") for c in _cited} - {""}

            def _line_backed(ln: str) -> bool:
                if _has_any(ln, _NO_CITABLE):
                    return True
                if set(_EPISODE_YEAR_RX.findall(ln)) & _cyears:
                    return True
                return any(f"[{i}]" in ln for i in _cids)
            res[k] = (len(_lines) >= int(want) and _distinct >= int(want)
                      and all(_adj) and all(_line_backed(ln) for ln in _lines))
        elif k == "episode_magnitude_or_absence":
            # W2b-D5, the PRICE-side twin of F-I: an episode counted without a receipt was the original
            # +10-hallucination mode; an episode ENUMERATED without a magnitude and WITHOUT SAYING SO is
            # the same failure in price form. Every dated-episode line must carry either a magnitude or
            # an explicit no-price-record marker.
            # A magnitude here is an [N] HANDLE, not a numeral. Handle discipline (_SYSTEM_CASCADE) says
            # an OBSERVED number carries ONLY its [N] handle -- an uncited numeral on an episode line is
            # a fabrication wearing a magnitude, which is precisely what W2b.2 refuses. A bare 4-digit
            # year is not a magnitude either, and the [N]-handle rule excludes it for free.
            # Requires a non-empty section: `all([])` is vacuously true, so an answer that never renders
            # '## Episodes' must not pass a true-pin.
            # D-4 (2026-07-31): and the same INJECTED-WINDOW requirement as min_episode_lines. Measured
            # exploit `pb_covid_demand_shock`: four invented windows with ZERO citations passed this pin on
            # the _NO_PRICE_RECORD branch alone -- "no price record" is trivially true of a window that
            # never existed. A magnitude-or-absence claim is only meaningful ABOUT AN EPISODE THE ENGINE
            # SHOWED; `all(_adj)` is that requirement, and it is the same expression both pins use so they
            # can never disagree about which bullets are real.
            _lines, _adj, _ = _episode_enumeration(out)
            _ok = all(_adj) and all(_N_HANDLE_RX.search(ln) or _absence_marked(ln)
                                    for ln in _lines)
            res[k] = (bool(_lines) and _ok) == bool(want)
        elif k == "episode_absence_label_fixed":
            # A5's deterministic teeth (the one wave-A reader-facing change cheap enough to pin). Every
            # bullet that declares NO CITABLE ITEM must carry the injected line's OWN label -- see
            # _absence_label_ok. Requires a NON-EMPTY '## Episodes' section, the same anti-vacuity rule
            # episode_magnitude_or_absence uses: `all([])` is true and an un-rendered section must not
            # pass a true-pin. A bullet that targets NO injected episode fails by construction (there is
            # no label it could have copied), which is the same minted-window refusal as `all(_adj)`.
            _lines, _adj, _ = _episode_enumeration(out)
            _inj = _injected_episodes(out)
            _abs_lines = [(ln, tg) for ln, tg in zip(_lines, _adj) if _has_any(ln, _NO_CITABLE)]
            _ok = all(_absence_label_ok(ln, tg, _inj) for ln, tg in _abs_lines)
            res[k] = (bool(_lines) and _ok) == bool(want)
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
            # A4 (F9): the RAW PRE-SANITIZE draft, same flag, same absent-when-off contract. This
            # projection is a hard whitelist and is the SINGLE source of truth for both the partial JSONL
            # and _baseline_json, so a trace key not named here reaches no artifact -- A4's acceptance
            # check ("for every non-zero raw red, the exact offending sentence") was unreachable without
            # it even with the flag on. TRACE-ONLY / EVAL-ONLY discipline (answer.raw_draft_snapshot's
            # docstring): this is a diagnostic surface, never rendered to a reader.
            "raw_draft": (out.get("trace") or {}).get("raw_draft"),
            # C2 (F5): the question-shape record -- what an honest answer of this shape REQUIRED, what
            # state each requirement reached, and whether the deterministic decline fired. Written by the
            # agent, copied onto the trace by BOTH orchestrator lanes, and read back here: without this
            # line the four miss states (section 2.3) are unreadable from any artifact.
            "question_shape": (out.get("trace") or {}).get("question_shape"),
            "shape_metric_states": (out.get("trace") or {}).get("shape_metric_states"),
            "shape_decline_guard": (out.get("trace") or {}).get("shape_decline_guard"),
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
            # D-DT-2 c1 acceptance item 5: the census must be readable from the JSONL WITHOUT the report
            # body -- M7 measured that no artifact on this machine records WHICH headings rendered, so a
            # use-rate for the qualitative license was unobtainable. This projection is a hard whitelist
            # (see the raw_draft note above), so the basis reaches no artifact unless it is named here.
            # D-AM-3: the simple-lift columns DERIVE from the tracekeys registry — the C2/U3 class
            # ("a trace key not named here reaches NO artifact") is now structurally impossible for
            # this class of key: registering in tracekeys.py IS the artifact registration. Per-key
            # rationale lives beside each entry in tracekeys.py, not here.
            **{k: (out.get("trace") or {}).get(k) for k in tk.TRACE_RECORD_KEYS},
            **{col: (out.get("intent_decision") or {}).get(dk) for dk, col in tk.DECISION_RECORD_KEYS},
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
            # W5-D6: `directional_traceability` MUST be listed here -- this projection is a hard whitelist,
            # so an axis absent from the tuple is silently dropped from every baseline JSON and the deck
            # scores an axis nobody can read back.
            "judge": {k: j[k] for k in ("usefulness", "convexity", "point_in_time", "grounding",
                                        "source_diversity", "continuity", "mechanism_voice",
                                        "directional_traceability", "episode_enumeration")
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
        heartbeat_period: float = 90.0, mode: str | None = None) -> list[dict]:
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
                    if mode:                                          # D-AM-11: the REQUEST-level arm lever;
                        okw["mode"] = mode                            # omitted when unset (byte-identical call)
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
             # W5-D6: OPTIONAL, never required. The axis only means something on a turn that carries a
             # directional lean, and adding it to `required` would force the judge to invent a score on
             # every existing deck row -- which would move those decks' baselines for no reason.
             "directional_traceability": n,
             # W4-N1: OPTIONAL for the same reason, and it finally EXISTS. eval.py:802 and the playbooks
             # deck both deferred enumeration quality to "the judge's episode_enumeration axis" while no
             # such axis was in this schema or in _JUDGE_SYS -- so enumeration honesty had no grader on any
             # surface: not here, and not on the deterministic pins (which the D-4 vacuity exploit greened
             # on invented windows). Scored ONLY on a turn whose DATED EPISODES block is non-empty.
             "episode_enumeration": n,
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
    "sizing. 5 = names the mechanism and its price direction; 1 = a mood/sign label with no mechanism. "
    "(See the OUTLOOK EXCEPTION below -- it is the ONLY case where a price level is not a penalty.)\n"
    "- directional_traceability (1-5): score this ONLY when the answer carries a DIRECTIONAL LEAN or a "
    "level; omit it otherwise. Did EVERY directional claim trace to a fired surface -- a cited regime, a "
    "cited [N] buffer, a cited COT positioning row, or a cited dated episode? 5 = every leg of the lean is "
    "attached to something the record actually shows, and the disagreeing cases are named rather than "
    "smoothed away; 3 = the direction is right but one leg rests on assertion; 1 = a confident lean sourced "
    "from nothing shown. A lean that is HONESTLY THIN ('the record is silent for this era, so the read is "
    "mechanism-only') scores HIGH -- naming the thinness is traceability, not a gap.\n"
    "- episode_enumeration (1-5): score this ONLY when the DATED EPISODES block is non-empty; omit it "
    "otherwise. Did the answer ENUMERATE the windows it was shown -- each one as its own dated item, "
    "including the thin ones -- rather than smoothing them into a confident 'usually'? 5 = every shown "
    "window is listed, in its own words, with the ones carrying NO CITABLE ITEM stated as such and NOT "
    "narrated; 3 = some listed, some smoothed away; 1 = the windows were shown and the answer generalised "
    "over them, dropped the thin ones, or listed a window it was never shown. Stating that a window has no "
    "citable item and no priced move is the CORRECT answer for that window and scores HIGH -- it is the "
    "record, not a hedge. Listing a window absent from the DATED EPISODES block is the worst case here and "
    "is also a hallucination.\n"
    "- hallucinations: any claim/number/sign/date supported by NEITHER the graph, the evidence, the DATED "
    "EPISODES block, NOR the looked-up numbers. THE DATED EPISODES BLOCK IS GROUND TRUTH, exactly like the "
    "graph: a window, span or report-count the answer states that appears in that block is SUPPORTED and is "
    "NOT a hallucination, even when no evidence item is dated inside it -- those windows are derived from "
    "the tool's own dated prop store, and the tool was instructed to enumerate them and to say plainly that "
    "it has no citable item for them. Do NOT list an enumerated window under hallucinations merely because "
    "the evidence panel carries nothing in its date range; that absence is the very thing the answer is "
    "reporting. A dated window in NONE of the four sources IS a hallucination, and so is a narrated "
    "severity/outcome/magnitude attached to a window the block shows only as a timestamp span.\n"
    "- gaps: what a researcher would still need — a missing propagation channel, no dated evidence, convexity "
    "asserted without a threshold, a missed regime or cross-commodity leg. Concrete.\n"
    "- improvements: concrete changes.\n- verdict: one blunt sentence.\n"
    "\n"
    "OUTLOOK EXCEPTION -- applies IF AND ONLY IF the ANSWER renders a '## Outlook' section. On those turns "
    "the user EXPLICITLY asked where prices go from here, and a DERIVED PRICE RANGE is IN SCOPE. Do not "
    "penalize it for existing. Judge it on its DERIVATION instead: a level is good when the spot anchor and "
    "each episode move carry their [N]/[E] handles, the arithmetic from spot to implied levels is visible, "
    "and the DISAGREEMENT among the episodes is named rather than smoothed into one number. A BARE LEVEL "
    "WITH NO DERIVATION IS A SERIOUS GROUNDING AND TRACEABILITY FAILURE -- score it 1-2 on both axes and "
    "list it under hallucinations, because a number that came from the model's prior rather than from the "
    "record is exactly the failure this tool exists to refuse. On these turns 'bullish'/'bearish' and "
    "valuation words are NOT penalties either; the derivation is what you are grading. What stays OUT OF "
    "SCOPE even here, and IS a penalty: entry/exit levels, stops, take-profit, position sizing, "
    "risk/reward framing, and any 'go long / is this a buy' verdict -- this tool holds no position and no "
    "risk model, so an execution instruction is unbacked by construction. If the answer has no "
    "'## Outlook' section, ignore this paragraph entirely and apply the rules above unchanged.\n"
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

            def _row_line(r: dict, _tbl=qy.get("table")) -> str:
                # J3: label the row's real date axis (trade_date for futures_eod) instead of a bare
                # period=? -- the judge panel must never show a dated series as dateless.
                from leviathan.graphrag.numbers import agent as _na
                kd = r.get("knowledge_date")
                return (f"    {_na.row_date_label(r, _tbl)} value={r.get('value')}"
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


def _judge_episodes_panel(out: dict) -> str:
    """The judge's DATED-EPISODES panel: the episode lines the ENGINE actually injected into this turn's
    prompt, read straight off trace['episodes_injected'] (answer._l2_blocks).

    WHY IT EXISTS -- the same reason _judge_numbers_panel does, and a strictly worse version of the same
    bug. The judge is shown the graph, the evidence, the looked-up numbers and the answer; the injected
    episode lines were in NONE of them. And a receipt-less episode is BY CONSTRUCTION one with no evidence
    prop inside its window (timeline.episodes_for sets `receipt` only from an in-window prop), so on the
    live artifact -- 3,735 episodes, 2,070 of them single-date -- the normal case was an answer that
    correctly enumerated a real window and a judge with nothing to check it against. Under _JUDGE_SYS's
    own definition ("supported by NEITHER the graph, the evidence, NOR the looked-up numbers") that is a
    hallucination, so turning W4 ON RAISED the hallucination count mechanically, on the exact metric the
    A/B acceptance rule reads, worst on the honest-thinness rows the wave exists to reward.

    SYMMETRY -- the point that makes this a fix and not a new bias. The block is rendered on EVERY judged
    turn of BOTH arms and the rubric text is one shared constant, so the two arms are graded by the same
    instrument. On the OFF arm (and on every non-W4 deck) it renders '(none)', which is TRUE: no episode
    line was injected, so any dated window the answer invents there is still unsupported and still a
    hallucination. What changes is not the standard, only whether the judge can see the ground truth the
    standard already referred to."""
    lines = [str((rec or {}).get("line") or "").strip()
             for rec in ((out.get("trace") or {}).get("episodes_injected") or [])]
    return "\n".join(f"- {ln}" for ln in lines if ln)


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
    ep_text = _judge_episodes_panel(out)                              # W4-N1: the injected episode ground truth
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
            # W4-N1. ALWAYS RENDERED, on both arms and every deck -- '(none)' is the true statement for a
            # turn with no injected episodes, and an OPTIONAL block would grade the two A/B arms with two
            # different instruments, which is the bias this fix exists to remove rather than relocate.
            f"=== DATED EPISODES THE TOOL WAS SHOWN (report TIMESTAMPS derived from the prop store; a "
            f"window/date the ANSWER enumerates that appears HERE is GROUNDED even when no evidence item "
            f"is dated inside it -- 'NO CITABLE ITEM IN THIS WINDOW' means the tool was told to say so, "
            f"and saying it is CORRECT behaviour, not a gap. A dated window the answer states that appears "
            f"in NEITHER this block NOR the evidence/numbers above IS a hallucination) ==="
            f"\n{ep_text or '(none -- no dated-episode lines were injected on this turn)'}\n\n"
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
            # W5: the outlook row record. banned_exec is pinned 0 on EVERY row; unbacked_levels is the
            # derivation gate's raw count (0 == price_target_backed); outlook_mode says whether the
            # three-leg gate actually fired, so a soak can split outlook from non-outlook turns.
            "banned_exec_words": int(tr.get("banned_exec_words") or 0),
            "unbacked_levels": int(tr.get("unbacked_levels") or 0),
            "outlook_mode": bool(tr.get("outlook_mode")),
            "dir_trace": j.get("directional_traceability"),
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
            # `corrected` is NO LONGER dates-only. It counted ledger-date repairs inside
            # structured['sources'] metadata; A2a's fail-closed enforcement added NUMBER repairs -- a
            # single-magnitude, single-handle, non-comparative sentence whose figure mismatches its row has
            # the row's value substituted into the PROSE and is counted here too. Reading this line as
            # "dates" would under-report the one number the new enforcement lane exists to move, and the
            # by_rule breakdown below separates them (`number_mismatch_repaired`, verify.py:531).
            f"ledger dates + number repairs corrected: {sum(v.get('corrected', 0) for v in vs)}",
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
                   graph_version: str | None, corpus_fp: str, via_orchestrator: bool = False,
                   mode: str | None = None) -> dict:
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
            # D-AM-11: the arm identity above reads PROCESS ENV only, so a REQUEST-level arm (the
            # reasoning mode) was structurally invisible -- two mode arms would have been identical
            # in every reproducibility key except ts. `mode` is what the run ASKED FOR (None = the
            # field was never sent, which resolves to standard); what each turn actually RAN is the
            # per-answer `mode_decision` column, lifted from the decision dict via the tracekeys registry.
            "mode": mode,
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


def _baseline_git_commit() -> str:
    """The commit that produced this baseline, or "unknown". NEVER raises.

    Every other reproducibility key a baseline carries names the DATA (corpus_fingerprint, graph_version) or
    the ARM (model, provider, the three flag fields). None of them names the CODE, so two baselines taken
    across a serving revision are indistinguishable in the artifact -- which is exactly the shape of the
    c160bece episodes-omission regression, where the prompt moved and the only way to say which baselines
    predate it was the wall clock.

    THE FALLBACK CHAIN IS image_stamp's, not a new one. leviathan.common.image_stamp already solved "name my
    own commit from inside a container": the build bakes $BUILD_GIT_COMMIT into /app/IMAGE_MANIFEST.json
    (build_manifest), image_facts() reads it back, and an absent or corrupt manifest degrades to
    image_stamp.UNKNOWN == "unknown" instead of raising (load_manifest returns None on ANY exception).

      1. image_facts()["git_commit"] -- the CONTAINER's answer, and the only honest one there: docker/ copies
         src/, not the repo, so an eval running in-image has no .git and `git rev-parse` would say nothing.
      2. `git rev-parse HEAD` -- the WORKING TREE's answer. The eval lane runs on the laptop today, where
         there is no baked manifest, so this is the branch that actually fires in practice.
      3. "unknown" -- a plain string, and the fallback is graceful ON PURPOSE. A baseline that cannot name
         its code is still a valid baseline; refusing to write one would trade a provenance gap for a lost
         (and billed) run.

    image_stamp is imported lazily and inside try/except so eval.py gains no hard dependency on the silver
    stack (image_facts -> baked_silver_tables -> leviathan.silver.registry) merely to stamp a JSON field."""
    try:
        from leviathan.common import image_stamp as _stamp
        commit = str(_stamp.image_facts().get("git_commit") or "").strip()
        if commit and commit != _stamp.UNKNOWN:
            return commit[:40]
    except Exception:  # noqa: BLE001 -- provenance is never worth a failed eval run
        pass
    try:
        import subprocess as _sp
        from pathlib import Path as _Path
        root = _Path(__file__).resolve().parents[3]        # src/leviathan/graphrag/eval.py -> repo root
        r = _sp.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()[:40]
    except Exception:  # noqa: BLE001 -- no git binary, no .git, or a timeout: all mean "unknown"
        pass
    return "unknown"


def _write_baseline(doc: dict) -> None:
    """Persist the baseline artifact locally (gitignored configs/graphrag/eval/) and — when EVIDENCE_S3 is
    set — to s3://<EVIDENCE_S3>/eval/ (the durable copy; the local twin never reaches the public repo).

    The `git_commit` stamp is added HERE, not in _baseline_json, so it lands on EVERY persisted baseline
    (both call sites, convos and single) without a second field to keep in sync -- and an explicit value a
    caller already put in `doc` is honoured rather than overwritten."""
    import json as _json
    doc = {**doc, "git_commit": doc.get("git_commit") or _baseline_git_commit()}
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
    print(f"  baseline json -> {p} (commit {doc['git_commit'][:12]}, "
          f"strip_rate {doc['strip_rate']}, {doc['total_claims']} claims, "
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
            if c.get("status") == "error":
                # D-RC-15b: the error TEXT used to be dropped entirely, so a malformed model tool
                # call (metric omitted -> pydantic ValidationError) rendered as an unexplainable
                # 'table.?=ERROR'. Surface the truncated cause; when the metric key is absent,
                # echo the raw input keys so the omission is visible as the model's, not ours.
                err = re.sub(r"\s+", " ", str(c.get("error") or ""))[:120]
                val = f"ERROR[{err}]" if err else "ERROR"
                if "metric" not in qy:
                    val += f" (input keys: {sorted(qy)})"
            else:
                val = "(not known)"
        elif len(rws) == 1:
            val = rws[0].get("value")
        else:
            # LATEST row, labeled — the old rows[0] render showed a series' oldest year as THE value
            # and seeded the cocoa false-fabrication mis-triage (RCA 2026-07-24)
            last = rws[-1]
            # J3: the date axis comes from the card (trade_date for futures_eod), labeled -- the bare
            # "@?" shape rendered settles dateless, and a settle without its date cannot anchor a
            # PIT-safe claim (OUTCOMES_JOIN_PLAN J3; token primitive lives beside the agent's render).
            from leviathan.graphrag.numbers import agent as _na
            val = f"{last.get('value')}@{_na.row_date_token(last, qy.get('table'))} (latest of {len(rws)} rows)"
            # J3b/D-OJ-8: an `agg='series'` read that came back AT its row cap kept the OLDEST rows and
            # dropped the newest, so "latest of N rows" is honest-looking and wrong. The sentinel is the
            # ENGINE's (`_exec` stamps it at the count the query returned, before nulls are dropped).
            if _na.series_truncated(c):
                val += f" [TRUNCATED at row cap {qy.get('limit')}: OLDEST kept, NOT the latest print]"
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
    # ── W5 F-H: the SESSION-CARRY gate, the one seam a stateless deck structurally cannot see ─────────
    # An outlook turn's permitted A1/flow/mood vocabulary rides into turn N+1 through TurnRecord.answer_tldr
    # (state_block) and roll_summary's durable state. The orchestrator now re-fences both unconditionally,
    # and THIS is where that fix is proven end-to-end: put a non-outlook turn AFTER an outlook turn and
    # assert the follow-up shows no market-register vocabulary and no leaks. `fenced_follow_up: true` is
    # meaningless on turn 1 -- it is only a gate when a PREVIOUS turn relaxed the register.
    tr = out.get("trace") or {}
    if spec.get("outlook_rendered") is not None:
        checks["outlook_mode_ok"] = bool(tr.get("outlook_mode")) == bool(spec["outlook_rendered"])
    if spec.get("fenced_follow_up"):
        ans = out.get("answer") or ""
        checks["follow_up_fenced_ok"] = (
            not tr.get("outlook_mode")                                # this turn did NOT relax, and ...
            and int(tr.get("banned_flow_words") or 0) == 0            # ... carried none of the prior turn's
            and int(tr.get("banned_valuation_words") or 0) == 0       #     permitted vocabulary forward,
            and int(tr.get("banned_exec_words") or 0) == 0            #     nor any execution idiom,
            and not reg.register_leaks(ans))                          #     nor any register leak.
    if spec.get("banned_exec_zero"):                                  # assertable on ANY turn, outlook or not
        checks["banned_exec_ok"] = int(tr.get("banned_exec_words") or 0) == 0
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
    ap.add_argument("--mode", default=None,
                    help="D-AM-9 reasoning scale (quick|standard|deep) sent as the REQUEST field on every "
                         "turn -- the mode A/B's arm lever. Requires --via-orchestrator (answer() alone has "
                         "no request), and the serving-side GRAPHRAG_MODES allowlist still decides whether "
                         "it is honored; the arm stamp records what was ASKED FOR either way")
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
               workers=args.workers, persist=pw, deadline=deadline, mode=args.mode)
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
                                   via_orchestrator=args.via_orchestrator, mode=args.mode))
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
