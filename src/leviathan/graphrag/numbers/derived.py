"""D-DA -- the derived-arithmetic lane's shared machinery (design v2, round-2 SOUND-WITH-FIXES).

THE LANE'S ONE LAW: the writer NEVER divides. Every derived magnitude is a governed [N] row minted
here by a deterministic producer (stats.py does the arithmetic), the ENGINE mints any relational
sentence, and the writer transcribes. The desk panel's unanimous root cause ("it will not do
arithmetic it already has the inputs for") is closed by construction, never by prompting.

WHY A NEW MODULE: cascade.py is past 6,000 lines, and the R4c-style lint needs one greppable home
for the lane's constants (config_check._check_synthesized_derived_legs reads them from here).

THE VINTAGE LAW (round-2 F2 + the v2 rewrite): NO derived row spans two knowledge dates. Two rules
exist -- `identical` (stats.same_vintage: exact string equality, fail-closed on unstamped inputs)
and `same_observation` (a join by date-string equality, the pair_spread/crush discipline). A
statistic OF a history stamps its latest input one-sidedly (the `_rv_call(date=...)` precedent).
There is NO union rule and NO gap row: a relation across two stamps renders in WORDS citing the two
handles (the m5 words-only precedent, cascade.py's "Set against" sentence), never as a new row.

THE COPY-SURFACE LAW (K1, re-derived from the verifier's own extractor -- round-2 minor confirms):
window lengths render as MY-prefixed or ISO date spans, or hyphenated with a noun in verify.py's
_DURATION_NOUN set (year|yr|month|week|wk|day|quarter|qtr|season); "{n}-marketing-year" and
"{n}-session" are CHARGED (measured) and never rendered. Ordinals before 'percentile' ARE claims
(the _ORDINAL_AFTER carve-out), so every percentile row STORES the printed rounded integer.

THE KD10 PREDICATE LAW (round-2 F1): any pool census this lane is gated on runs verify.py's LIVE
guard call shape -- `_num_backed(v, allv, dec=d)` with each numeral's WRITTEN decimals from
`_claim_numbers_with_decimals` -- never the bare `dec=None` form, whose windows are up to 3x
narrower on small integers and under-count collisions (measured: 12.66 backs a stray '13' under
the live predicate and not under the bare one).
"""
from __future__ import annotations

import os
from typing import Sequence

# read-only imports from the verifier: the extractor identity that makes _dv_copy_ok and the live
# charge agree about what a claim magnitude IS. verify.py imports only os/re at module level
# (round-2 re-verified) -- no cycle.
from leviathan.graphrag.verify import _claim_numbers_with_decimals, _mask_handles, _num_backed

# ── the lane's constants (config_check reads these; the R4c pattern) ────────────────────────────────
DV_LANE_CAP = 1            # lanes rendered per turn in the measured arm (F5: the pool-densification
#                            fence -- one lane's rows, never a stacked pool)
DV_INBAND_CAP = 6          # injected values inside [0.5, 150] per block -- the P9-B collision band.
#                            Round-2 M2: this is ALSO a unit-scale filter on small-magnitude
#                            commodities (cotton in M-480lb-bales); the STEP-0 magnitude census
#                            decides the roster, and the decline reason NAMES the unit scale.
DV_INBAND_LO, DV_INBAND_HI = 0.5, 150.0
DV_SU_VERDICT_MARGIN = 10.0   # percentile points; inside it the verdict names NO leg (ROW 5)
DV_ATTRIB_MARGIN = 0.25       # sigma; inside it the attribution clause names NO leg (ROW 7)
DV_FETCH_CAP = 6              # per-turn ceiling on this lane's added reads (lane 1: 2 baseline +2
#                               lazy on an official-total-use miss, per leg)

# the plain-word RENDER tokens (register-clean, sanitize-stable, never a card metric id -- round-2
# m2: bare 'production'/'exports' ARE silver_wasde metric ids, so the render tokens carry an
# article-phrase form that can never collide with an id string)
DV_RENDER_METRICS = {
    "su_component_stocks": "the ending-stocks line",
    "su_component_use": "the total-use line",
    "su_component_production": "the production line",
    "su_level": "stocks-to-use",
    "su_percentile": "stocks-to-use percentile",
    "su_extreme": "stocks-to-use extreme",
    "leg_percentile": "monthly benchmark percentile",
    "leg_zscore": "monthly benchmark sigma",
    "crush_meal_value": "meal value per bushel",
    "crush_oil_value": "oil value per bushel",
    "crush_share": "oil share of the crush",
    "crush_share_percentile": "oil share percentile",
    "eod_level": "latest exchange settle",
}


def _dv_call(table_label: str, metric_key: str, tag: str, value, period: str, asof, *,
             unit: str, date: str | None = None, table: str = "derived") -> dict:
    """The `_rv_call` twin for the derived lane: a synthetic call-record so a derived magnitude IS a
    citable, value-checkable [N] row. `metric_key` indexes DV_RENDER_METRICS (the machine id stays
    module-side; the reader sees the plain-word token). Exactly ONE row per handle, an EXPLICIT unit
    string on it, and the fenced vintage stamp as knowledge_date (one-sided: derived-later-than-
    inputs, the _endpoint_row doctrine)."""
    row: dict = {"value": value, "unit": unit}
    if date:
        row["knowledge_date"] = date
    return {"query": {"table": table_label, "metric": DV_RENDER_METRICS[metric_key],
                      "commodity": tag, "country": None, "period": period, "asof": asof},
            "rows": [row], "status": "ok", "_dv_metric_key": metric_key, "_dv_table": table}


def _dv_shown(call: dict, *values) -> dict:
    """Bind every magnitude the row's LINE prints to its call record (cascade._shown's contract,
    restated here so derived.py never imports cascade at module level -- the import direction is
    cascade -> derived, lazily at the call site)."""
    vals = [float(v) for v in values if v is not None]
    if vals:
        call["shown"] = vals
    return call


def _dv_inband(vals: Sequence) -> int:
    """How many of `vals` land inside the P9-B collision-dense band [0.5, 150]."""
    n = 0
    for v in vals:
        try:
            f = abs(float(v))
        except (TypeError, ValueError):
            continue
        if DV_INBAND_LO <= f <= DV_INBAND_HI:
            n += 1
    return n


def _line_handles(line: str) -> list[int]:
    """The [N#] handle indices cited on one assembled line, in order."""
    import re
    return [int(m) for m in re.findall(r"\[N(\d+)\]", line or "")]


def _dv_copy_ok(lines: Sequence[str], shown_by_handle: dict[int, Sequence[float]]) -> bool:
    """The K1 lint, PER HANDLE (round-2 M1: the live charges are handle-scoped, so a block-scoped
    pool would pass a line the live number_mismatch then deletes). For every assembled line, run the
    VERIFIER'S OWN extractor over the handle-masked text, then require BOTH live-charge shapes:

      (a) the mismatch shape: for EVERY handle the line cites, at least one of the line's claim
          magnitudes must back against THAT handle's own shown pool (the per-handle
          `_mismatch_pool` check that killed the streak sentences);
      (b) the unbacked shape: EVERY claim magnitude on the line must back against the union of the
          line's cited handles' shown pools -- deliberately STRICTER than the live `_all_row_vals`
          pool, so a pass here can never depend on someone else's rows.

    Both arms run the LIVE predicate (`_num_backed` with written decimals -- the KD10 law). A block
    that fails is dropped WHOLE by the caller (fence-then-extend); this returns the verdict."""
    for line in (lines or []):
        handles = _line_handles(line)
        if not handles:
            continue
        nums, decs = _claim_numbers_with_decimals(_mask_handles(line))
        if not nums:
            continue
        union: list[float] = []
        for h in handles:
            pool = [float(v) for v in (shown_by_handle.get(h) or [])]
            union.extend(pool)
            if pool and not any(_num_backed(v, pool, dec=d) for v, d in zip(nums, decs)):
                return False                                     # arm (a): the mismatch shape
        for v, d in zip(nums, decs):
            if not _num_backed(v, union, dec=d):
                return False                                     # arm (b): the unbacked shape
    return True


def derived_arith_on() -> bool:
    """The lane's flag, read at the answer seam only (the `_rv_reading_on` idiom)."""
    return str(os.environ.get("GRAPHRAG_DERIVED_ARITH", "")).strip().lower() == "on"


# ── LANE 1: the US stocks-to-use standing (design v2 ROWS 1-5, probe-certified 2026-09-01) ──────────
# THE MEASURED CONTRACT (dda_probe r5, P6): a silver_wasde card series read serves rows
#   {country, knowledge_date, metric, period, revision_stamp, unit, value(STRING)}
# and WITHOUT filters carries every world-table country line and the "Con't" parse-garbage units.
# The two fences that make the series single-valued (P2b: the table_type "disagreements" are the
# SAME fact at two scopes/units -- us-table Million Bushels vs world-table MMT):
#   (1) country = the leg's own scope, passed on the READ;
#   (2) unit == the roster's declared unit, filtered on the ROW (unit rides every served row).
# After both, the producer asserts ONE row per marketing year and DROPS (counted) any MY still
# multi-valued -- fail-closed, never a silent pick.
# FETCH BUDGET (P1: no total_use attribute exists): 3 reads per leg (ending_stocks,
# domestic_total, exports) x 2 legs = 6 = DV_FETCH_CAP exactly; the production garnish row is
# NOT in v1 (docketed) -- the desk's "show your division" needs exactly the three the quotient uses.
_DV_WASDE_TABLE = "silver_wasde"
_DV_WASDE_LEGS = {
    # slug -> (wasde commodity, reader label, expected unit, country)
    "corn_cbot": ("corn", "US corn", "Million Bushels", "united_states"),
    "soft_red_winter_wheat_cbot": ("wheat", "US wheat (all classes)", "Million Bushels",
                                   "united_states"),
    "hard_red_winter_wheat_kcbt": ("wheat", "US wheat (all classes)", "Million Bushels",
                                   "united_states"),
}
_DV_SU_ATTRS = ("ending_stocks", "domestic_total", "exports")
DV_SU_COVERAGE_FLOOR = 0.80          # M7, AMENDED by the P8 RCA (2026-09-01): binds on the RECENT
#                                      window's coverage, never share-of-fetched -- ancient vintage
#                                      refusals are the fence WORKING and must not dark the lane
DV_SU_RECENT_WINDOW = 10             # the decision-relevant span the coverage floor measures
DV_SU_CONTIGUOUS_TAIL = 5            # ...and the most recent N MYs must all survive
_DV_ORD_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _dv_ordinal(p) -> str:
    """1 -> 1st, 2 -> 2nd ... (the cascade._rv_ordinal contract, restated locally so derived.py
    never imports cascade)."""
    p = int(p)
    if 10 <= p % 100 <= 20:
        return f"{p}th"
    return f"{p}{_DV_ORD_SUFFIX.get(p % 10, 'th')}"


def _dv_fmt(v: float) -> str:
    """One rendering per family: thousands-grouped, integers bare, else 2 dp (stored == printed)."""
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.2f}"


def _dv_leg_series(fetch, qfn, slug: str, asof):
    """The three component series for one leg, fenced. Returns ({attr: {my: (value, stamp, role)}},
    None) or (None, decline_tag)."""
    com, _label, unit_want, country = _DV_WASDE_LEGS[slug]
    out: dict = {"_dup_drops": 0}
    for attr in _DV_SU_ATTRS:
        rec = fetch(qfn, table=_DV_WASDE_TABLE, metric=attr, commodity=com, country=country,
                    t1=None, t2=None, asof=asof, agg="series", period=None,
                    period_type="marketing_year")
        if (rec or {}).get("status") != "ok":
            return None, "su_read_failed"
        by_my: dict = {}
        for r in (rec.get("rows") or []):
            if str(r.get("unit") or "").strip() != unit_want:
                continue                              # the P2b scope/unit fence + Con't garbage
            my = str(r.get("period") or "").strip()
            if not my:
                continue
            try:
                v = float(str(r.get("value")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if my in by_my:
                out["_dup_drops"] += 1
                by_my[my] = None                      # multi-valued after BOTH fences: drop the MY
                continue
            by_my[my] = (v, str(r.get("knowledge_date") or ""), str(r.get("revision_stamp") or ""))
        out[attr] = {k: v for k, v in by_my.items() if v is not None}
    return out, None


def su_standing(fetch, qfn, slug_a: str, slug_b: str, asof, base: int):
    """The lane-1 producer: raw levels WITH their components (the division shown), the mandatory
    numeral-free structural-basis caveat, each leg's OWN-history standing, and the engine-minted
    BALANCE-STANDING verdict (one negation site; margin-fenced; the exact KD2 token 'of its own
    history' on BOTH legs). Returns (lines, calls, trace)."""
    from leviathan.graphrag.numbers import stats as st

    if slug_a not in _DV_WASDE_LEGS or slug_b not in _DV_WASDE_LEGS:
        return [], [], {"decline": "su_no_roster"}
    legs = {}
    for slug in (slug_a, slug_b):
        series, err = _dv_leg_series(fetch, qfn, slug, asof)
        if err:
            return [], [], {"decline": err}
        legs[slug] = series

    lines: list = []
    calls: list = []
    shown_by_handle: dict = {}
    n = base
    standings: dict = {}
    hist_means: dict = {}
    trace: dict = {"fetches": 6, "dup_drops": sum(l["_dup_drops"] for l in legs.values()),
                   "vintage_refusals": 0}

    for slug in (slug_a, slug_b):
        com, label, unit_want, _country = _DV_WASDE_LEGS[slug]
        series = legs[slug]
        mys = sorted(set(series["ending_stocks"]) & set(series["domestic_total"])
                     & set(series["exports"]))
        if not mys:
            return [], [], {"decline": "su_no_shared_mys"}
        hist: list = []
        hist_mys: list = []
        survived: dict = {}
        for my in mys:
            es, dt, ex = (series[a][my] for a in _DV_SU_ATTRS)
            ok, stamp = st.same_vintage([es[1], dt[1], ex[1]])
            if not ok:
                trace["vintage_refusals"] += 1
                continue
            r = st.ratio(es[0], dt[0] + ex[0], scale=100.0)
            if r["declined"]:
                continue
            hist.append(r["value"])
            hist_mys.append(my)
            survived[my] = (es, dt, ex, stamp, r["value"])
        # THE FLOOR'S DENOMINATOR (P8 RCA, 2026-09-01, data/batch_runs/dda_p8_rca_20260901.json):
        # v1 measured share-of-FETCHED, and real corn came in at 14/18 = 0.778 -- under the floor by
        # 0.022 -- because the vintage fence CORRECTLY refused four ANCIENT marketing years
        # (2009/10-2012/13, whose final revisions genuinely landed across different releases) while
        # every recent year was clean. Punishing the lane for honest refusals of ancient scatter
        # inverts the fence's own purpose. The floor now binds where the standing's decision lives:
        # the RECENT window's coverage + the contiguous tail; the full-fetch share is TELEMETRY.
        n_f = len(mys)
        recent = mys[-DV_SU_RECENT_WINDOW:]
        cov_recent = (sum(1 for my in recent if my in survived) / len(recent)) if recent else 0.0
        trace[f"coverage_full_{slug}"] = round(len(hist) / n_f, 3) if n_f else None
        if not hist or cov_recent < DV_SU_COVERAGE_FLOOR \
                or any(my not in survived for my in mys[-DV_SU_CONTIGUOUS_TAIL:]):
            return [], [], {"decline": "su_history_gappy",
                            "coverage_recent": round(cov_recent, 3),
                            "coverage_full": round(len(hist) / n_f, 3) if n_f else None}
        cur_my = hist_mys[-1]
        es, dt, ex, stamp, level = survived[cur_my]
        role = " (a USDA projection)" if es[2] == "projection" else ""
        span = f"MY{hist_mys[0]}..MY{cur_my}"
        for attr_key, mk, val in (("ending_stocks", "su_component_stocks", es[0]),
                                  ("domestic_total", "su_component_use", dt[0]),
                                  ("exports", "su_component_use", ex[0])):
            n += 1
            word = {"ending_stocks": "the ending-stocks line",
                    "domestic_total": "the domestic-use line",
                    "exports": "the exports line"}[attr_key]
            c = _dv_shown(_dv_call("USDA WASDE", mk, label, val, f"MY{cur_my}", asof,
                                   unit=unit_want, date=stamp), val)
            calls.append(c)
            shown_by_handle[n] = c["shown"]
            lines.append(f"- [N{n}] {label}, {word} MY{cur_my}: {_dv_fmt(val)} "
                         f"{unit_want}{role}")
        lvl = round(level, 1)
        n += 1
        c = _dv_shown(_dv_call("USDA WASDE", "su_level", f"{label} stocks-to-use", lvl,
                               f"MY{cur_my}", asof, unit="%", date=stamp),
                      lvl, es[0], dt[0] + ex[0])
        calls.append(c)
        shown_by_handle[n] = c["shown"]
        lines.append(f"- [N{n}] {label}, stocks-to-use MY{cur_my}: {lvl}% -- "
                     f"{_dv_fmt(es[0])} over a use base of {_dv_fmt(dt[0] + ex[0])} "
                     f"(domestic use plus exports, one release)")
        pc = st.percentile(level, hist)
        if not pc.get("declined"):
            pv = int(round(pc["value"]))
            n += 1
            c = _dv_shown(_dv_call("USDA WASDE", "su_percentile", f"{label} stocks-to-use", pv,
                                   span, asof, unit="percentile", date=stamp), pv)
            calls.append(c)
            shown_by_handle[n] = c["shown"]
            lines.append(f"- [N{n}] where that stocks-to-use stands within {label}'s own "
                         f"{span} history: {_dv_ordinal(pv)} percentile")
            standings[slug] = (label, pv, n)
        elif len(hist) >= 2:
            # ordinal-when-thin (ROW 4): reached only at 2 <= n < the rank floor. At ONE surviving
            # MY there is nothing to place the level against -- the levels and the caveat still
            # render and NO standing row and NO verdict word is minted (the panel fixture's honest
            # output, F1's rewritten pin).
            ex_st = st.extrema(hist)
            hi2, lo2 = round(float(ex_st["max"]), 1), round(float(ex_st["min"]), 1)
            for tag, v in (("highest", hi2), ("lowest", lo2)):
                n += 1
                c = _dv_shown(_dv_call("USDA WASDE", "su_extreme", f"{label} stocks-to-use", v,
                                       span, asof, unit="%", date=stamp), v)
                calls.append(c)
                shown_by_handle[n] = c["shown"]
                lines.append(f"- [N{n}] the {tag} stocks-to-use across {label}'s own {span} "
                             f"history: {v}%")
        hist_means[slug] = (label, sum(hist) / len(hist))

    # the MANDATORY numeral-free structural-basis caveat (engine-computed direction; F1)
    (la_l, ma), (lb_l, mb) = hist_means[slug_a], hist_means[slug_b]
    hi_l, lo_l = (la_l, lb_l) if ma >= mb else (lb_l, la_l)
    lines.append(f"NOTE -- not comparable as levels: {hi_l}'s stocks-to-use has run structurally "
                 f"above {lo_l}'s across the whole history held, so the raw levels above never "
                 f"decide which sheet is tighter; the standing lines place each crop against ITS "
                 f"OWN history.")
    # the engine-minted verdict: ONE negation site (S/U is a LOOSENESS measure -- the LOWER
    # own-history percentile is the TIGHTER sheet), margin-fenced, exact KD2 token on BOTH legs
    if len(standings) == 2:
        al, ap, ah = standings[slug_a]
        bl, bp, bh = standings[slug_b]
        if abs(ap - bp) <= DV_SU_VERDICT_MARGIN:
            verdict = (f"BALANCE-STANDING: {al} stands at the {_dv_ordinal(ap)} percentile of its "
                       f"own history [N{ah}] while {bl} stands at the {_dv_ordinal(bp)} percentile "
                       f"of its own history [N{bh}] -- comparable points in their own histories, "
                       f"and neither sheet is named the tighter.")
        else:
            tight = al if ap < bp else bl
            verdict = (f"BALANCE-STANDING: {al} stands at the {_dv_ordinal(ap)} percentile of its "
                       f"own history [N{ah}] while {bl} stands at the {_dv_ordinal(bp)} percentile "
                       f"of its own history [N{bh}] -- on each crop's own history, {tight} is the "
                       f"tighter of the two.")
        verdict += (" TRANSCRIPTION: copy every figure as DIGITS exactly as printed; the standing "
                    "words carry the comparison and no new figure is ever derived from these rows.")
        lines.append(verdict)
    # the K1 lint + the in-band cap, fence-then-extend: breach -> the block declines WHOLE
    if not _dv_copy_ok(lines, shown_by_handle):
        return [], [], {"decline": "su_copy_surface"}
    inband = _dv_inband([v for c in calls for v in (c.get("shown") or [])])
    if inband > DV_INBAND_CAP:
        return [], [], {"decline": "su_unit_scale_inband", "inband": inband}
    trace["fired"] = True
    trace["inband"] = inband
    return lines, calls, trace


# ── LANE 3: the crush oil-share standing (design v2 ROWS 8-10, probe-certified P7 2026-09-01) ───────
# THE MEASURED CONTRACT (dda_probe --only P7): a gold_board_crush card series read serves rows
#   {knowledge_date, revision_stamp, value(STRING)}
# -- the SESSION DATE arrives as knowledge_date, the crush_rule_version as revision_stamp, and the
# three delivery-month columns exist in pg but are NOT served through the card (round-2 F4 measured:
# the block DECLARES that absence, never claims aligned months). The commodity filter is real
# (2,520 rows with soybeans_cbot vs 2,654 without -- the roll fence + foreign rows).
_DV_CRUSH_TABLE = "gold_board_crush"
_DV_CRUSH_COMMODITY = "soybeans_cbot"
_DV_CRUSH_METRICS = ("meal_value_usd_bu", "oil_value_usd_bu")
_DV_CRUSH_TRIO = frozenset({"soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot"})


def crush_share(fetch, qfn, asof, base: int):
    """The lane-3 producer: ONE session's two product values (the same_observation join on the
    session's knowledge_date -- v1's 'one row' claim was wrong, the honest rule is named), the
    oil share from stats.share, and the share's standing over every session the card serves.
    The desk defect this closes: 'it reports levels and never reports standing... an oil share
    near 52% is at or near the widest in the history of the modern complex, and that single
    sentence is the whole trade.' Returns (lines, calls, trace)."""
    from leviathan.graphrag.numbers import stats as st

    series: dict = {}
    for metric in _DV_CRUSH_METRICS:
        rec = fetch(qfn, table=_DV_CRUSH_TABLE, metric=metric, commodity=_DV_CRUSH_COMMODITY,
                    country=None, t1=None, t2=None, asof=asof, agg="series", period=None,
                    period_type="date")
        if (rec or {}).get("status") != "ok":
            return [], [], {"decline": "crush_read_failed"}
        by_day: dict = {}
        for r in (rec.get("rows") or []):
            d = str(r.get("knowledge_date") or "").strip()
            if not d:
                continue
            try:
                by_day[d] = (float(str(r.get("value")).replace(",", "")),
                             str(r.get("revision_stamp") or ""))
            except (TypeError, ValueError):
                continue
        series[metric] = by_day
    days = sorted(set(series[_DV_CRUSH_METRICS[0]]) & set(series[_DV_CRUSH_METRICS[1]]))
    if not days:
        return [], [], {"decline": "crush_no_shared_sessions"}
    cur = days[-1]
    meal, rule_m = series["meal_value_usd_bu"][cur]
    oil, rule_o = series["oil_value_usd_bu"][cur]
    sh = st.share(oil, [meal])
    if sh["declined"]:
        return [], [], {"decline": "crush_share_nonpositive"}
    share_hist = []
    for d in days:
        s_d = st.share(series["oil_value_usd_bu"][d][0], [series["meal_value_usd_bu"][d][0]])
        if not s_d["declined"]:
            share_hist.append(s_d["value"])

    lines: list = []
    calls: list = []
    shown_by_handle: dict = {}
    n = base
    for metric_key, mk, val in (("crush_meal_value", "crush_meal_value", meal),
                                ("crush_oil_value", "crush_oil_value", oil)):
        n += 1
        word = DV_RENDER_METRICS[mk]
        c = _dv_shown(_dv_call("CBOT board crush", mk, "the CBOT board crush", round(val, 4),
                               f"{cur}..{cur}", asof, unit="USD/bushel", date=cur), val)
        calls.append(c)
        shown_by_handle[n] = c["shown"]
        lines.append(f"- [N{n}] the CBOT board crush, {word}, session {cur}: {val:.4f} USD/bushel")
    sh2 = round(sh["value"], 1)
    n += 1
    c = _dv_shown(_dv_call("CBOT board crush", "crush_share", "the CBOT board crush oil share",
                           sh2, f"{cur}..{cur}", asof, unit="%", date=cur), sh2, round(oil, 4),
                  round(meal, 4))
    calls.append(c)
    shown_by_handle[n] = c["shown"]
    lines.append(f"- [N{n}] oil share of the crush, session {cur}: {sh2}% -- the oil value over "
                 f"the two product values together, one session")
    pc = st.percentile(sh["value"], share_hist)
    h_pc = None
    if not pc.get("declined"):
        pv = int(round(pc["value"]))
        n += 1
        h_pc = n
        c = _dv_shown(_dv_call("CBOT board crush", "crush_share_percentile",
                               "the CBOT board crush oil share", pv,
                               f"{days[0]}..{cur}", asof, unit="percentile", date=cur), pv)
        calls.append(c)
        shown_by_handle[n] = c["shown"]
        lines.append(f"- [N{n}] where that oil share stands across every session held, "
                     f"{days[0]}..{cur}: {_dv_ordinal(pv)} percentile")
    lines.append(f"NOTE -- one session, one rule: both product values above are the SAME session's "
                 f"prints under the {('board-crush rule ' + rule_m) if rule_m == rule_o else 'board-crush rules'} "
                 f"(the served rows carry no delivery-month labels, so no claim is made that the "
                 f"three legs share a delivery month), and a crush value is a margin component, "
                 f"never a price.")
    if h_pc is not None:
        lines.append(f"CRUSH-STANDING: the oil share of the crush stands at the "
                     f"{_dv_ordinal(int(round(pc['value'])))} percentile of every session the "
                     f"record holds [N{h_pc}] -- an observed standing of the split itself, and no "
                     f"statement is made about where it goes next. TRANSCRIPTION: copy every "
                     f"figure as DIGITS exactly as printed.")
    if not _dv_copy_ok(lines, shown_by_handle):
        return [], [], {"decline": "crush_copy_surface"}
    inband = _dv_inband([v for c in calls for v in (c.get("shown") or [])])
    if inband > DV_INBAND_CAP:
        return [], [], {"decline": "crush_unit_scale_inband", "inband": inband}
    return lines, calls, {"fired": True, "fetches": 2, "sessions": len(days), "inband": inband,
                          "rule": rule_m}
