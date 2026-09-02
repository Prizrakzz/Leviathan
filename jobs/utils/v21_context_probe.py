"""V2-1 TERMINAL-DRIVER CONTEXT CELL -- step 1, the $0 in-VPC substrate probe (charter V2 HORIZON
RECON 2026-09-02, item V2-1 RE-SCOPED: the third-order board CHAIN is dead on measurement -- one live
second-order chain, ten structural declines -- and what survives is a NON-VERDICTED CONTEXT CELL).

THE SHAPE UNDER TEST. On a firing window whose driver slice is a livestock driver, render ONE extra
ROW-1-class cell beside the walk's existing price cells: the terminal driver's OWN dated series move
over the SAME window, with its own handle, its own units, and NO verdict line. "Over that same window
the world chicken price moved +Z.Z % [N4]." The directional claim stays on the BOARD cells and their
sign_agreement; the driver cell is evidence the shock was real, never a third leg of the read.

WHY IT CARRIES NO VERDICT, MEASURED not assumed: `_cw_fences` (cascade.py:6303-6319) reads its tenor
term off `contract_month`, which a monthly/weekly non-futures series does not have -> ma is None ->
tenor False BY CONSTRUCTION; and the realized-interval bar min(7 days, a tenth of the span) is blown by
a month-grain anchor on every measured window. So the cell needs its OWN grain fence and never enters
`stats.sign_agreement`. This probe measures the inputs that fence needs.

THE QUESTION THIS PROBE ANSWERS, per (firing window, series), THROUGH THE REAL CARD PATH:
 (1) VINTAGE. Does the card serve at asof = the window's END, and what stamp do the rows carry?
     silver_esr is knowledge_semantics=vintage (knowledge_date_col=as_of_date, YYYYMMDD, the latest
     vintage on/before the asof) -> WHICH snapshot does the collapse pick, and does it precede the
     window end? silver_pink_sheet is knowledge_semantics=data_date with knowledge_date_col=date --
     i.e. THE TABLE CARRIES NO VINTAGE COLUMN AT ALL: latest-only, WB revises months retroactively,
     provenance is one global `latest_release_ym` stamp. That is exactly the C-2 class the RV reading's
     `price_replay` belt exists for. THE PROBE DOES NOT ASSUME THE BELT'S ANSWER -- it reads each pink
     window TWICE, once at asof = the window END and once at asof = TODAY, and prints the difference.
     That difference IS the replay exposure, in the cell's own units.
 (2) THE MOVE the cell would print: first and last IN-WINDOW observation + their dates, computed
     engine-style -- `last/first - 1` as a percent for a price level (the `_cw_cell_line` convention,
     `{:+g} %`), the DIFFERENCE in native units for an ESR commitments level (1000 MT).
 (3) ROW COUNT and saturation against the NumberQuery `limit` (5000). Real risk on silver_esr read
     unscoped by destination: destinations x weeks.
 (4) ESR ONLY -- the honest "all destinations" total. The card says "OMIT country for the national
     total across all destinations", but the SERIES branch has no GROUP BY, so the rows come back per
     destination. This probe MEASURES the country vocabulary the card returns (post `_apply_country_names`
     display names) instead of guessing it: a bloc aggregate ("European Union") or a pseudo destination
     ("Unknown") inside those rows would make a naive per-week sum double-count. It also counts weeks
     carrying more than one `market_year` -- `grain_cols` includes market_year, so a window straddling a
     marketing-year boundary can serve the SAME week twice (the recon's unmeasured MY-boundary blocker).
 (5) THE UNIT STRINGS the card returns: the row's own unit column where one is declared, printed beside
     the card-declared metric unit (the two differ, and the V2-2 probe measured unit=None on rows).

THE ROSTER IS THE MEASURED ONE, NEVER A GUESS. The 10 serve-reachable livestock firings (recon 3c: the
SHIPPED injector `timeline.episodes_for` MAX_PER_NODE=4 biggest-first, then the walk's own three gates
CW_SPAN_MIN_DAYS=45 / CW_SPAN_MAX_DAYS=270 / t1 >= PRICE_COVERAGE_START) collapse to SEVEN distinct
(driver, window) pairs, because a driver window shared by two roots is ONE driver cell. `cattle_on_feed`
is deliberately ABSENT: 0 serve-reachable firings and no cattle-on-feed data at all (the NASS ANIMALS
sector is foreclosed by a fetcher filename regex) -- mapping it would mint the naming trap.

BUDGET AND BELTS. EIGHT cells over the seven pairs (5 pink: cattle_cycle 1 + avian 3 + broiler 1; 3 ESR:
cattle_beef 1 + hogs 2) = PLANNED 19 pg reads (10 pink = 5 cells x 2 asofs, 9 ESR = 3 cells x 3), hard
capped at MAX_READS = 60. Every read is belted: an exception is RECORDED on the cell and the probe walks
on, and each cell prints as it lands (a late crash must never eat the early answers). ASCII-only prints.

RUNS IN-VPC (the laptop cannot reach the RDS). The evidence image's ENTRYPOINT IS `python`, so the Batch
containerOverrides command is ["-c", SRC] and NEVER ["python", "-c", SRC] -- the r1 lesson banked in the
charter. This file is new to the tree, so either rebuild the evidence image from this tree and runpy the
baked path, or (cheaper, no rebuild) upload this file to
s3://leviathan-dev-shahem-001/graphrag_evidence/probes/src/v21_context_probe.py and submit:

    command = ["-c", (
        "import boto3,sys;"
        "s=boto3.client('s3').get_object(Bucket='leviathan-dev-shahem-001',"
        "Key='graphrag_evidence/probes/src/v21_context_probe.py')['Body'].read().decode();"
        "sys.argv=['v21_context_probe.py','--asof','2026-09-02'];"
        "exec(compile(s,'v21_context_probe.py','exec'),{'__name__':'__main__'})")]

on jobdef leviathan-dev-evidence-build (the revision carrying the EVIDENCE_PG_DSN secret), queue
leviathan-dev-queue-ondemand. Banks EVIDENCE_S3 probes/v21_context_probe_<asof>.json.

    python jobs/utils/v21_context_probe.py --asof 2026-09-02
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "src")

# -- REGISTERED BEFORE ANY RUN (the charter's own K-letter discipline) --------------------------------
MAX_READS = 60                    # hard cap; planned 19
SERIES_LIMIT = 5000               # NumberQuery.limit default -- saturation is measured against THIS
GRAIN_MIN_OBS = 3                 # the design's own grain fence: >= 3 in-window observations of the
#                                   series' native cadence before a move may be printed at all
PINK_TABLE = "silver_pink_sheet"
ESR_TABLE = "silver_esr"
ESR_LEVEL = "outstanding_sales_1000mt"    # a LEVEL -> the cell prints last - first, in 1000 MT
ESR_FLOW = "weekly_exports_1000mt"        # a FLOW  -> the honest window figure is a SUM
ESR_CONTROL_COUNTRY = "China"             # one destination-scoped control per ESR cell: proves the
#                                           esr_destinations.yaml name->code translation actually fires
#                                           and yields a clean single-destination weekly level series

# THE SEVEN DISTINCT (driver, window) PAIRS = the recon's 10 serve-reachable firings (a window shared by
# two roots is ONE driver cell). `roots` is carried so the artifact says which board rows the cell would
# sit beside; `span_days` is carried so the [45, 270] band is visible in the artifact without arithmetic.
FIRINGS = [
    {"driver": "cattle_cycle_herd_size", "t1": "2022-10-21", "t2": "2023-01-26",
     "roots": ["corn_cbot", "soybean_meal_cbot"], "span_days": 97, "n_props": 6},
    {"driver": "avian_influenza", "t1": "2024-11-08", "t2": "2025-05-01",
     "roots": ["soybean_meal_cbot"], "span_days": 174, "n_props": None},
    {"driver": "avian_influenza", "t1": "2021-10-04", "t2": "2022-06-23",
     "roots": ["soybean_meal_cbot"], "span_days": 262, "n_props": None},
    {"driver": "avian_influenza", "t1": "2025-11-14", "t2": "2026-04-16",
     "roots": ["soybean_meal_cbot"], "span_days": 153, "n_props": None},
    {"driver": "african_swine_fever", "t1": "2023-07-27", "t2": "2024-04-15",
     "roots": ["soybean_meal_cbot", "rapeseed_meal_zce"], "span_days": 263, "n_props": None},
    {"driver": "african_swine_fever", "t1": "2026-01-01", "t2": "2026-04-17",
     "roots": ["soybean_meal_cbot", "rapeseed_meal_zce"], "span_days": 106, "n_props": None},
    {"driver": "broiler_economics", "t1": "2026-01-01", "t2": "2026-08-12",
     "roots": ["soybean_meal_cbot"], "span_days": 223, "n_props": None},
]

# THE CURATED SLICE -> SERIES MAP under test (recon design sketch piece 2). `mapped` is the series the
# build would ship; `alternate` is measured beside it so the owner picks on numbers, not on prose.
# RESOLVE-OR-DECLINE: an unmapped slice renders no driver cell, silently, with a counted reason.
SLICE_SERIES = {
    "cattle_cycle_herd_size": [
        {"kind": "pink", "metric": "beef_usd_t", "role": "mapped",
         "why": "tables.yaml beef_usd_t desc names cattle_cycle_herd_size as a consumer"},
        {"kind": "esr", "commodity": "cattle_beef", "role": "alternate",
         "why": "weekly US beef export commitments -- the physical-flow alternative to the WB price"},
    ],
    "avian_influenza": [
        {"kind": "pink", "metric": "chicken_usd_t", "role": "mapped",
         "why": "the poultry output price; the WB world monthly average"},
    ],
    "broiler_economics": [
        {"kind": "pink", "metric": "chicken_usd_t", "role": "mapped",
         "why": "tables.yaml chicken_usd_t desc names broiler_economics as its consumer"},
    ],
    "african_swine_fever": [
        {"kind": "esr", "commodity": "hogs", "role": "mapped",
         "why": "weekly US hog export commitments; the WB carries no pork/hog price series"},
    ],
}

# ABSENCES ESTABLISHED FROM THE CARDS ALONE -- no pg read is spent on them, and each is written down
# because silence is not admission (the _xc_label discipline).
STRUCTURAL_ABSENCES = [
    {"driver": "avian_influenza", "table": ESR_TABLE,
     "reason": "no poultry slug in silver_esr commodity_values (cattle_beef and hogs are the only "
               "livestock codes; transform _COMMODITY_CODE_TO_NAME 1701/1702) -- no weekly poultry "
               "commitments series exists to read"},
    {"driver": "broiler_economics", "table": ESR_TABLE,
     "reason": "same as avian_influenza: silver_esr carries no poultry slug"},
    {"driver": "african_swine_fever", "table": PINK_TABLE,
     "reason": "no pork/hog price on the WB Pink Sheet roster (beef_usd_t and chicken_usd_t are the "
               "only livestock outputs the card declares)"},
    {"driver": "cattle_on_feed", "table": "*",
     "reason": "DELIBERATELY UNMAPPED: 0 serve-reachable firings (biggest-first selects pre-coverage "
               "clusters) and the NASS ANIMALS sector is not ingested at all -- a 'cattle on feed' "
               "line carried by a beef-price proxy is the naming trap a skeptic catches"},
]


# -- small helpers (no engine import; the probe must run even if a seam moves) ------------------------
def _obs_date(row) -> str:
    """The row's OBSERVATION date. silver_esr surfaces week_ending_date as `data_date`; the pink sheet's
    date_col IS its knowledge_date_col, so `_extras` emits it ONCE, as `knowledge_date`."""
    for k in ("data_date", "date", "week_ending_date", "knowledge_date", "period"):
        v = (row or {}).get(k)
        if v:
            return _iso_stamp(v)
    return ""


def _iso_stamp(v) -> str:
    """R2 LEXICAL-FORMAT TRAP, the card's own (tables.yaml silver_esr): as_of_date values are YYYYMMDD
    ('20240412') while every window bound here is ISO -- comparing them raw is lexically FALSE at the
    fifth character ('2' > '-'), which is exactly the class that once returned zero rows for a whole
    vintage guard. Normalize the stamp, never the comparison."""
    s = str(v or "")[:10]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _pct(last, first):
    if first in (None, 0) or last is None:
        return None
    return round((last / first - 1.0) * 100.0, 4)


def _days(a: str, b: str):
    try:
        return (dt.date.fromisoformat(str(b)[:10]) - dt.date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def _card_facts(reg) -> dict:
    """The PIT facts the CARDS carry, recorded from the loaded registry so the artifact is self-
    describing (and so a card edit between probe and build is visible as a diff, not as a surprise)."""
    out = {}
    for tid in (PINK_TABLE, ESR_TABLE):
        try:
            ts = reg.get(tid)
        except Exception as exc:                       # noqa: BLE001 -- record, never raise
            out[tid] = {"error": type(exc).__name__, "detail": str(exc)[:160]}
            continue
        out[tid] = {
            "cadence": ts.cadence, "shape": ts.shape,
            "date_col": ts.date_col, "knowledge_date_col": ts.knowledge_date_col,
            "knowledge_semantics": ts.knowledge_semantics,
            "publication_lag_days": ts.publication_lag_days,
            "provenance_col": ts.provenance_col,
            "period_col": ts.period_col, "period_type": ts.period_type,
            "country_col": ts.country_col, "country_name_ref": ts.country_name_ref,
            "unit_col": ts.unit_col,
            "commodity_values_n": len(ts.commodity_values or []),
            "livestock_commodity_values": [c for c in (ts.commodity_values or [])
                                           if c in ("cattle_beef", "hogs")],
            "metric_units": {m: (ts.metrics[m].unit if m in ts.metrics else None)
                             for m in ("beef_usd_t", "chicken_usd_t", ESR_LEVEL, ESR_FLOW)
                             if m in ts.metrics},
        }
    return out


def _series_shape(rows: list, t1: str, t2: str) -> dict:
    """n_rows / saturation / in-window rows / units, shared by both series kinds."""
    inw = []
    units = set()
    stamps = set()
    for r in rows or []:
        d = _obs_date(r)
        if r.get("unit") is not None:
            units.add(str(r.get("unit")))
        if r.get("revision_stamp") is not None:
            stamps.add(str(r.get("revision_stamp")))
        if d and t1 <= d <= t2:
            inw.append(r)
    return {"n_rows": len(rows or []), "saturated": len(rows or []) >= SERIES_LIMIT,
            "n_in_window": len(inw), "row_units": sorted(units)[:4],
            "revision_stamps": sorted(stamps)[:4], "_inw": inw}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-09-02")
    args = ap.parse_args()
    assert os.environ.get("EVIDENCE_PG_DSN"), "v21_context_probe requires EVIDENCE_PG_DSN (in-VPC)"
    os.environ.setdefault("GRAPHRAG_NUMBERS_BACKEND", "pg")
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry

    out: dict = {
        "probe": "v21_terminal_driver_context_cell",
        "asof": args.asof,
        "constants": {"MAX_READS": MAX_READS, "SERIES_LIMIT": SERIES_LIMIT,
                      "GRAIN_MIN_OBS": GRAIN_MIN_OBS, "esr_level_metric": ESR_LEVEL,
                      "esr_flow_metric": ESR_FLOW, "esr_control_country": ESR_CONTROL_COUNTRY},
        "firings": FIRINGS,
        "structural_absences": STRUCTURAL_ABSENCES,
        "card_facts": _card_facts(load_registry()),
        "cells": [],
        "summary": {},
    }
    print("[v21] card facts", json.dumps(out["card_facts"], default=str)[:900])

    state = {"reads": 0, "errors": 0}

    def read(**kw):
        """ONE card read, belted and budgeted. Returns (rows, err_or_None) -- never raises."""
        if state["reads"] >= MAX_READS:
            return [], {"error": "read_budget_exhausted", "detail": f"MAX_READS={MAX_READS}"}
        try:
            spec = Q.NumberQuery(**kw)
            rows = Q.run(spec, query_fn=pgnumbers.pg_query) or []
            state["reads"] += 1
            return rows, None
        except Exception as exc:                        # noqa: BLE001 -- record the failure, keep probing
            state["reads"] += 1
            state["errors"] += 1
            return [], {"error": type(exc).__name__, "detail": str(exc)[:220]}

    # -- PINK SHEET CELL: two reads, the same window at two asofs ------------------------------------
    def pink_cell(metric: str, t1: str, t2: str) -> dict:
        cell = {"table": PINK_TABLE, "metric": metric, "reads": {}}
        for tag, asof in (("at_window_end", t2), ("at_today", args.asof)):
            rows, err = read(table=PINK_TABLE, metric=metric, asof=asof, agg="series",
                             period_start=t1, period_end=t2)
            if err:
                cell["reads"][tag] = err
                continue
            sh = _series_shape(rows, t1, t2)
            inw = sorted(sh.pop("_inw"), key=_obs_date)
            first = inw[0] if inw else None
            last = inw[-1] if inw else None
            fv, lv = _num((first or {}).get("value")), _num((last or {}).get("value"))
            sh.update({
                "asof": asof,
                "first_obs": {"date": _obs_date(first) if first else None, "value": fv},
                "last_obs": {"date": _obs_date(last) if last else None, "value": lv},
                "move_pct_preview": _pct(lv, fv),
                "obs_dates": [_obs_date(r) for r in inw],
                "days_last_obs_to_window_end": _days(_obs_date(last), t2) if last else None,
                "clears_grain_fence": len(inw) >= GRAIN_MIN_OBS,
                "by_date": {_obs_date(r): _num(r.get("value")) for r in inw},
            })
            cell["reads"][tag] = sh
        # (1) THE REPLAY EXPOSURE, MEASURED: the same window, two asofs. A latest-only, retroactively
        # revised table can only be compared this way -- there is no vintage column to ask.
        a, b = cell["reads"].get("at_window_end"), cell["reads"].get("at_today")
        if isinstance(a, dict) and isinstance(b, dict) and "by_date" in a and "by_date" in b:
            shared = sorted(set(a["by_date"]) & set(b["by_date"]))
            diffs = []
            for d in shared:
                x, y = a["by_date"][d], b["by_date"][d]
                if x not in (None, 0) and y is not None:
                    diffs.append(abs(y / x - 1.0) * 100.0)
            mv_a, mv_b = a.get("move_pct_preview"), b.get("move_pct_preview")
            cell["replay"] = {
                "n_shared_dates": len(shared),
                "n_dates_only_at_today": len(set(b["by_date"]) - set(a["by_date"])),
                "n_dates_only_at_window_end": len(set(a["by_date"]) - set(b["by_date"])),
                "max_abs_value_revision_pct": round(max(diffs), 6) if diffs else None,
                "n_dates_revised": sum(1 for x in diffs if x > 1e-9),
                "move_pp_gap_end_vs_today": (round(mv_a - mv_b, 4)
                                             if (mv_a is not None and mv_b is not None) else None),
            }
        return cell

    # -- ESR CELL: three reads (unscoped level series, unscoped flow sum, one destination control) ----
    def esr_cell(slug: str, t1: str, t2: str) -> dict:
        cell = {"table": ESR_TABLE, "commodity": slug, "reads": {}}

        rows, err = read(table=ESR_TABLE, metric=ESR_LEVEL, asof=t2, agg="series",
                         commodity=slug, period_start=t1, period_end=t2)
        if err:
            cell["reads"]["level_series_all_destinations"] = err
        else:
            sh = _series_shape(rows, t1, t2)
            inw = sh.pop("_inw")
            weeks: dict = {}
            countries: dict = {}
            vintages = set()
            for r in inw:
                d = _obs_date(r)
                v = _num(r.get("value"))
                w = weeks.setdefault(d, {"total": 0.0, "n": 0, "periods": set(), "by_period": {}})
                if v is not None:
                    w["total"] += v
                    p = str(r.get("period"))
                    w["by_period"][p] = w["by_period"].get(p, 0.0) + v
                w["n"] += 1
                w["periods"].add(str(r.get("period")))
                c = str(r.get("country"))
                countries[c] = countries.get(c, 0.0) + (v or 0.0)
                if r.get("knowledge_date") is not None:
                    vintages.add(_iso_stamp(r.get("knowledge_date")))
            wk = sorted(weeks)
            multi = [d for d in wk if len(weeks[d]["periods"]) > 1]

            def _latest_my_total(d):
                bp = weeks[d]["by_period"]
                return bp[max(bp)] if bp else None

            f, l = (wk[0] if wk else None), (wk[-1] if wk else None)
            ft, lt = (weeks[f]["total"] if f else None), (weeks[l]["total"] if l else None)
            fl, ll = (_latest_my_total(f) if f else None), (_latest_my_total(l) if l else None)
            # (4) the country vocabulary the card RETURNS -- the aggregate/pseudo tell is a name, and a
            # naive per-week sum over rows carrying one would double-count the national total.
            top = sorted(countries.items(), key=lambda kv: -abs(kv[1]))[:10]
            flagged = [c for c in countries
                       if any(t in c.upper() for t in ("TOTAL", "UNKNOWN", "EUROPEAN UNION",
                                                       "OTHER", "UNIDENTIFIED", "WORLD"))]
            sh.update({
                "asof": t2,
                "n_weeks": len(wk), "first_week": f, "last_week": l,
                "n_destinations": len(countries),
                "top_destinations": [[c, round(v, 3)] for c, v in top],
                "aggregate_or_pseudo_names_present": flagged,
                "weeks_with_multiple_market_years": len(multi),
                "weeks_with_multiple_market_years_sample": multi[:4],
                "vintages_returned": sorted(vintages)[:4],
                "vintage_precedes_window_end": (max(vintages) <= t2) if vintages else None,
                "national_total_naive_sum": {"first": ft, "last": lt,
                                             "delta_1000mt": (round(lt - ft, 3)
                                                              if (ft is not None and lt is not None)
                                                              else None)},
                "national_total_latest_my_only": {"first": fl, "last": ll,
                                                  "delta_1000mt": (round(ll - fl, 3)
                                                                   if (fl is not None and ll is not None)
                                                                   else None)},
                "clears_grain_fence": len(wk) >= GRAIN_MIN_OBS,
                "days_last_week_to_window_end": _days(l, t2) if l else None,
            })
            cell["reads"]["level_series_all_destinations"] = sh

        rows, err = read(table=ESR_TABLE, metric=ESR_FLOW, asof=t2, agg="sum",
                         commodity=slug, period_start=t1, period_end=t2)
        cell["reads"]["flow_sum_all_destinations"] = err or {
            "n_rows": len(rows),
            "value": _num((rows[0] or {}).get("value")) if rows else None,
            "row_units": sorted({str(r.get("unit")) for r in rows if r.get("unit") is not None})[:2],
            "row_keys": sorted((rows[0] or {}).keys())[:12] if rows else [],
        }

        rows, err = read(table=ESR_TABLE, metric=ESR_LEVEL, asof=t2, agg="series",
                         commodity=slug, country=ESR_CONTROL_COUNTRY,
                         period_start=t1, period_end=t2)
        if err:
            cell["reads"]["level_series_one_destination"] = err
        else:
            sh = _series_shape(rows, t1, t2)
            inw = sorted(sh.pop("_inw"), key=_obs_date)
            fv = _num((inw[0] or {}).get("value")) if inw else None
            lv = _num((inw[-1] or {}).get("value")) if inw else None
            sh.update({
                "country_asked": ESR_CONTROL_COUNTRY,
                "country_returned": sorted({str(r.get("country")) for r in inw})[:3],
                "first_obs": {"date": _obs_date(inw[0]) if inw else None, "value": fv},
                "last_obs": {"date": _obs_date(inw[-1]) if inw else None, "value": lv},
                "delta_1000mt": (round(lv - fv, 3) if (fv is not None and lv is not None) else None),
            })
            cell["reads"]["level_series_one_destination"] = sh
        return cell

    # -- the walk over the roster --------------------------------------------------------------------
    for fr in FIRINGS:
        t1, t2 = fr["t1"], fr["t2"]
        for ser in SLICE_SERIES.get(fr["driver"], []):
            cell = {"driver": fr["driver"], "window": f"{t1}..{t2}", "span_days": fr["span_days"],
                    "roots": fr["roots"], "role": ser["role"], "why": ser["why"]}
            if ser["kind"] == "pink":
                cell.update(pink_cell(ser["metric"], t1, t2))
                r = cell["reads"].get("at_window_end") or {}
                rp = cell.get("replay") or {}
                print("[v21] {0} {1}..{2} pink:{3} n_in={4} move={5} fence={6} "
                      "replay_max_rev_pct={7} move_gap_pp={8} err={9}".format(
                          fr["driver"], t1, t2, ser["metric"], r.get("n_in_window"),
                          r.get("move_pct_preview"), r.get("clears_grain_fence"),
                          rp.get("max_abs_value_revision_pct"), rp.get("move_pp_gap_end_vs_today"),
                          r.get("error")))
            else:
                cell.update(esr_cell(ser["commodity"], t1, t2))
                r = cell["reads"].get("level_series_all_destinations") or {}
                print("[v21] {0} {1}..{2} esr:{3} rows={4} sat={5} dests={6} weeks={7} "
                      "multi_my_weeks={8} delta_naive={9} delta_latest_my={10} vintages={11} "
                      "fence={12} err={13}".format(
                          fr["driver"], t1, t2, ser["commodity"], r.get("n_rows"), r.get("saturated"),
                          r.get("n_destinations"), r.get("n_weeks"),
                          r.get("weeks_with_multiple_market_years"),
                          (r.get("national_total_naive_sum") or {}).get("delta_1000mt"),
                          (r.get("national_total_latest_my_only") or {}).get("delta_1000mt"),
                          r.get("vintages_returned"), r.get("clears_grain_fence"), r.get("error")))
            out["cells"].append(cell)

    served = 0
    fenced = 0
    for c in out["cells"]:
        rr = [v for v in c.get("reads", {}).values() if isinstance(v, dict) and "n_rows" in v]
        if any((v.get("n_in_window") or 0) > 0 for v in rr):
            served += 1
        if any(v.get("clears_grain_fence") for v in rr):
            fenced += 1
    out["summary"] = {
        "cells": len(out["cells"]),
        "pink_cells": sum(1 for c in out["cells"] if c.get("table") == PINK_TABLE),
        "esr_cells": sum(1 for c in out["cells"] if c.get("table") == ESR_TABLE),
        "cells_served_in_window": served,
        "cells_clearing_grain_fence": fenced,
        "pg_reads": state["reads"], "read_errors": state["errors"],
        "read_budget": MAX_READS,
    }
    print("[v21] SUMMARY", json.dumps(out["summary"]))

    base = os.environ.get("EVIDENCE_S3", "")
    if base.startswith("s3://"):
        try:
            import boto3
            bucket, _, prefix = base[5:].partition("/")
            key = f"{prefix.rstrip('/')}/probes/v21_context_probe_{args.asof}.json"
            boto3.client("s3").put_object(Bucket=bucket, Key=key,
                                          Body=json.dumps(out, indent=1, default=str).encode())
            print(f"[v21] banked s3://{bucket}/{key}")
        except Exception as exc:                        # noqa: BLE001 -- the prints ARE the answer
            print(f"[v21] BANK FAILED {type(exc).__name__}: {str(exc)[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
