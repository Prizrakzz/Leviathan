"""PRICE_AND_PLAYBOOKS W2 / D2-D4 -- the Databento raw(DBN) -> bronze transform.

WHAT THIS MODULE OWNS
---------------------
The vendor-specific half of ``silver_futures_eod``'s Databento leg, and NOTHING else:

  * :data:`ROOT_MAP` -- vendor root -> ``(dataset id, leviathan_slug)`` for the 16 covered
    contracts. It carries NO unit / currency / settle_kind / source: W1.0 moved that authority to
    :mod:`leviathan.silver.futures_eod_contracts` on purpose (ten producers land against one table,
    so a per-transform unit map is by construction not single-source). This module never writes a
    unit; the bronze_to_silver step reads ``contract_for(slug)``.
  * the OUTRIGHT filter (F1) -- regex AND an exact root match;
  * the symbol -> ``(leviathan_slug, contract_month)`` decode, including the DOWNLOAD-YEAR-ANCHORED
    decade rule for the single-digit GLBX year code (D2) and, for roots that DECLARE a listing
    horizon (:data:`GLBX_LISTING_HORIZON_MONTHS`), the LISTING-INTERVAL-ANCHORED form of it (V2-4
    M1: a December contract that terminates on the first business day of the NEXT month resolves
    inside the next calendar-year window, and the bare download-year rule lifts it a decade);
  * the SETTLEMENT-SPINE bronze for :data:`SETTLEMENT_TAPE_ROOTS` -- roots whose price history IS
    the statistics stream (settle/OI populated, OHLCV NULL, bars LEFT-joined if any exist);
  * the fixed-point 1e-9 price scaling and the undefined-sentinel masking;
  * the GLBX ``statistics`` reduction + join -> ``settle`` / ``open_interest`` (D3);
  * the ICE double-bar rule (D4, :data:`ICE_BAR_RULE`).

Pure: pandas + numpy + the house logger. NO boto3, NO S3, and the ``databento`` package is imported
LAZILY inside the two decode entry points, so every rule in here is unit-testable on a synthetic
DataFrame with no vendor dependency at all.

THE FOUR TRAPS THIS MODULE EXISTS TO NOT FALL INTO
--------------------------------------------------
1. **Parent symbology is discovery, never the pull (F1).** ``<ROOT>.FUT`` resolves butterflies,
   condors and calendar spreads -- outrights are 2.4%-24% of the result. The regex alone is NOT
   enough: the orchestrator's 2026-07-28 live smoke resolved ``ZC.FUT`` for 2016 and the bare GLBX
   regex ``^[A-Z0-9]{1,4}[FGHJKMNQUVXZ]\\d$`` admitted ``T12Q6`` -- a different root's outright.
   :func:`is_outright` therefore requires the regex AND that the symbol's own root token equal the
   requested root.
2. **The GLBX year code is ONE digit.** ``ZCH6`` is March 2016 in a 2016 file and March 2026 in a
   2026 file. The anchor is the RESOLUTION YEAR carried in the raw S3 path
   (``.../root=ZC/year=2016/...``), never ``datetime.now()`` -- a 2027 backfill re-run of the 2016
   raw bytes must decode identically.
3. **``ohlcv-1d`` close is NOT the settlement (F3).** GLBX ``settle`` comes from the ``statistics``
   schema (``stat_type`` 3) and the ohlcv close stays in ``close``; ICE has no affordable settlement
   series ($1,960) so its ``settle`` IS the close and the row is labelled ``settle_kind='close'``.
4. **ICE emits ~2 ohlcv-1d bars per contract per UTC day (F2).** A naive ingest double-counts every
   ICE contract-day. See :data:`ICE_BAR_RULE`.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Datasets and roots
# ---------------------------------------------------------------------------
# Vendor dataset id -> the snake-cased slug used in the raw S3 prefix AND as the
# `databento_<slug>` suffix of the CONTRACT_MAP `source` value. One vocabulary, three surfaces.
DATASET_SLUGS: dict[str, str] = {
    "GLBX.MDP3": "glbx_mdp3",
    "IFUS.IMPACT": "ifus_impact",
    "IFEU.IMPACT": "ifeu_impact",
}
GLBX = "GLBX.MDP3"
IFUS = "IFUS.IMPACT"
IFEU = "IFEU.IMPACT"
ICE_DATASETS: frozenset[str] = frozenset({IFUS, IFEU})

# The 16 Databento-covered contracts (plan lines 542-558; +CPO, V2-4 2026-09-02). The other 15
# slugs in CONTRACT_MAP are W1a/W1b/W1c legs (CZCE / DCE / JSE / CEPEA / MIAX / Euronext) and W2
# must never touch them.
# NOTE the IFEU white-sugar root is the SINGLE character "W" ("WS" is a 422) -- nothing here may
# assume a two-character root.
ROOT_MAP: dict[str, tuple[str, str]] = {
    # -- GLBX.MDP3 (CME/CBOT) -----------------------------------------------------------------
    "ZC": (GLBX, "corn_cbot"),
    "ZS": (GLBX, "soybeans_cbot"),
    "ZL": (GLBX, "soybean_oil_cbot"),
    "ZM": (GLBX, "soybean_meal_cbot"),
    "ZW": (GLBX, "soft_red_winter_wheat_cbot"),
    "KE": (GLBX, "hard_red_winter_wheat_kcbt"),
    "ZR": (GLBX, "rough_rice_cbot"),
    # V2-4 (2026-09-02): USD Malaysian Crude Palm Oil Calendar futures (CME rulebook 204) -- a
    # SETTLEMENT-MARK tape (Globex volume 0; OI in ClearPort swaps): see SETTLEMENT_TAPE_ROOTS.
    # $0 probe: data/batch_runs/cpo_databento_probe_20260902.json (120 outrights, stats $0.0894).
    # The slug is the EXISTING palm slug re-keyed from the parked Bursa MYR binding (Route B).
    "CPO": (GLBX, "malaysian_crude_palm_oil_cme"),
    # -- IFUS.IMPACT (ICE US; canola lives here, plan line 556) -------------------------------
    "KC": (IFUS, "arabica_coffee"),
    "SB": (IFUS, "raw_sugar"),
    "CC": (IFUS, "cocoa"),
    "CT": (IFUS, "cotton"),
    "OJ": (IFUS, "frozen_orange_juice"),
    "RS": (IFUS, "canola_ice"),
    # -- IFEU.IMPACT (ICE Europe) --------------------------------------------------------------
    "RC": (IFEU, "robusta_coffee"),
    "W": (IFEU, "white_sugar"),
}

# First USABLE trade date per root (plan lines 563-591). GLBX history begins 2010-06-06; ICE
# (both datasets) begins 2018-12-23 -- the 2017 assumption was REFUTED. KE is the exception: GLBX
# carries it only from 2013 (KCBT -> CME migration; every pre-2013 window is an HTTP 422) and 2013
# is a 74-bar stub, so the usable window opens 2014-01-01.
_GLBX_FIRST = "2010-06-06"
_ICE_FIRST = "2018-12-23"
ROOT_FIRST_DATE: dict[str, str] = {
    **{r: _GLBX_FIRST for r, (ds, _s) in ROOT_MAP.items() if ds == GLBX},
    **{r: _ICE_FIRST for r, (ds, _s) in ROOT_MAP.items() if ds in ICE_DATASETS},
    "KE": "2014-01-01",
    # CPO (V2-4 M2, MEASURED on data/batch_runs/cpo_databento_probe_20260902.json): the tape has a
    # ~7-month HOLE -- the 2015 window lists CPOF6..CPON6 while the 2016 window's first decoded
    # month is 2016-08 (Jan..Jul 2016 resolve NOTHING under CPO.FUT), and the 2010-2015 24-month
    # regime is UNVERIFIED (20-25 outrights/yr, 195-249 recycled instrument_ids). A blanket
    # 2010-06-06 floor would claim coverage the tape does not have (the KCBT/CEPEA hole shape), and
    # covers() would route a 2016-02..06 window to the table to decline no_tape_rows instead of
    # naming the floor. The usable window therefore opens at the 60-month regime's first session
    # month; the pre-2016 regime is a separate owner decision (docket).
    "CPO": "2016-08-01",
}
assert set(ROOT_FIRST_DATE) == set(ROOT_MAP), "ROOT_FIRST_DATE must cover exactly the ROOT_MAP roots"

# SETTLEMENT-TAPE ROOTS (V2-4): GLBX roots whose price history IS the statistics stream. The probe
# priced ohlcv-1d at $0.0000 for 2014-2026 (no Globex trade bars) while statistics priced non-zero
# every year; the bar-driven bronze (build_ohlcv_bronze -> LEFT-join statistics) would therefore
# land ZERO rows and red every unit. For these roots the fetch buys statistics ONLY and the bronze
# row skeleton is the reduced statistics keys with open/high/low/close/volume NULL
# (build_settlement_bronze). F3 holds: settle is never a close, and a close is never a settle.
SETTLEMENT_TAPE_ROOTS: frozenset[str] = frozenset({"CPO"})
assert SETTLEMENT_TAPE_ROOTS <= {r for r, (ds, _s) in ROOT_MAP.items() if ds == GLBX}, \
    "SETTLEMENT_TAPE_ROOTS must be GLBX roots (statistics is a GLBX-only leg)"

# LISTING HORIZON per root, in months (V2-4 M1). A root that DECLARES a horizon decodes its
# single-digit year code with the LISTING-INTERVAL-ANCHORED rule (resolve_glbx_contract_year) and
# lints every bronze row against it (lint_contract_horizon). CME lists CPO for 60 CONSECUTIVE
# months, and its contracts terminate on the last CME business day of the month OR the first
# business day of the NEXT month -- so CPOZ6 (Dec 2016) resolves inside the 2017 window, where the
# bare download-year rule reads the digit 6 as 2026 (measured: 2017 CPOZ6 -> 2026-12, 2019 CPOZ8
# -> 2028-12, ... 8 of the probe's 17 windows). A root ABSENT from this map keeps the shipped
# download-year rule byte-for-byte (the 7 live GLBX roots' December contracts expire mid-month and
# never straddle a window; none lists past ~3 years).
GLBX_LISTING_HORIZON_MONTHS: dict[str, int] = {"CPO": 60}
assert set(GLBX_LISTING_HORIZON_MONTHS) <= {r for r, (ds, _s) in ROOT_MAP.items() if ds == GLBX}, \
    "GLBX_LISTING_HORIZON_MONTHS must name GLBX roots only"
# The decode anchor is the symbol's resolved listing-interval start (d0) when the symbology
# artifact carries it, else the (root, year) WINDOW start -- which can sit up to 12 months before
# a contract's real listing date, so the decode horizon carries that slack on top of the declared
# listing depth. The ROW lint (trade_date vs contract_month) uses the bare declared horizon.
_HORIZON_WINDOW_SLACK_MONTHS = 12
# A contract may print on the first business day(s) AFTER its delivery month ends (the CPO
# termination rule), i.e. contract_month == trade month - 1. Never earlier.
_HORIZON_GRACE_MONTHS = 1


def root_years(root: str, through_year: int) -> list[int]:
    """Every backfill year for one root: its first USABLE year .. ``through_year`` inclusive.

    Lives HERE rather than in the producer because the ingest job and the silver task must agree
    on the unit set exactly -- a root/year the fetch skipped and the transform expects is a
    spurious failure, and the reverse is silently missing history."""
    first = datetime.strptime(ROOT_FIRST_DATE[root], "%Y-%m-%d").date()
    return list(range(first.year, int(through_year) + 1))


def year_window(root: str, year: int, *, through: Optional[date] = None) -> tuple[str, str]:
    """The request window for one ``(root, year)``: ``[start, end)``.

    END IS EXCLUSIVE everywhere in the Databento API (submit_job, get_cost, symbology.resolve).
    Clipped to the root's first usable date and, optionally, to ``through``."""
    first = datetime.strptime(ROOT_FIRST_DATE[root], "%Y-%m-%d").date()
    start = max(first, date(int(year), 1, 1))
    end = date(int(year) + 1, 1, 1)
    if through is not None and end > through:
        end = through
    if start >= end:
        raise ValueError(f"{root}/{year}: empty window {start}..{end} (root opens {first})")
    return start.isoformat(), end.isoformat()

# ---------------------------------------------------------------------------
# The outright filter (F1)
# ---------------------------------------------------------------------------
# Verified regexes (plan line 653). GLBX outrights are `<ROOT><MONTHCODE><single digit year>`;
# ICE outrights are fixed-width `<ROOT><pad>FM<MONTHCODE><4 digits>!`.
GLBX_OUTRIGHT_RE = re.compile(r"^[A-Z0-9]{1,4}[FGHJKMNQUVXZ]\d$")
ICE_OUTRIGHT_RE = re.compile(r"^[A-Z]{1,3}\s+FM[FGHJKMNQUVXZ]\d{4}!$")

MONTH_CODES: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}

# The delivery month is rendered as a zero-padded, lexicographically-sortable YYYY-MM string. It is
# part of the natural key [leviathan_slug, contract_month, trade_date], so the format is a contract:
# never emit a bare month code, and never emit a NULL on a futures row (lint_frame rejects it).
CONTRACT_MONTH_FMT = "%04d-%02d"


def symbol_root(symbol: str, dataset: str) -> Optional[str]:
    """The root token of a vendor symbol, or ``None`` if it is not an outright of any root.

    GLBX: everything before the trailing ``<month code><digit>`` pair. ICE: the token before the
    fixed-width padding. This is the conjunct that makes :func:`is_outright` tight -- ``startswith``
    alone lets root ``W`` (IFEU white sugar) swallow a hypothetical ``WS  FMZ0026!``, and the bare
    GLBX regex lets ``T12Q6`` through a ``ZC`` resolve (measured 2026-07-28)."""
    if not isinstance(symbol, str):
        return None
    if dataset == GLBX:
        return symbol[:-2] if GLBX_OUTRIGHT_RE.match(symbol) else None
    if dataset in ICE_DATASETS:
        if not ICE_OUTRIGHT_RE.match(symbol):
            return None
        return symbol.split()[0]
    raise ValueError(f"unknown dataset {dataset!r} (known: {sorted(DATASET_SLUGS)})")


def is_outright(symbol: str, root: str, dataset: str) -> bool:
    """True iff ``symbol`` is an OUTRIGHT delivery month of ``root`` on ``dataset``.

    Two conjuncts, both load-bearing (plan F1 + the orchestrator's live smoke):

      1. the verified per-dataset regex -- drops the spread complex on GLBX (``ZC`` full window:
         943 resolved -> 50 outright) and, on ICE, the ``_Z`` TAS suffixes and the numeric-id
         instruments (``SB   99   6512548``);
      2. the symbol's OWN root token equals ``root`` -- ``startswith(root)`` as the plan words it,
         but exact, because ``startswith`` is not sufficient for a 1-character root.

    The count of symbols this returns False for is the gate-2 metric, and it must be NON-ZERO for
    every root, GLBX included."""
    r = symbol_root(symbol, dataset)
    return r is not None and r == root and str(symbol).startswith(root)


def partition_symbols(symbols: Iterable[str], root: str, dataset: str) -> tuple[list[str], list[str]]:
    """``(outrights, dropped)`` -- sorted, de-duplicated. The gate-2 evidence, computed once at
    resolve time and persisted into the raw symbology artifact rather than recomputed later."""
    uniq = sorted({s for s in symbols if isinstance(s, str) and s})
    keep = [s for s in uniq if is_outright(s, root, dataset)]
    drop = [s for s in uniq if not is_outright(s, root, dataset)]
    return keep, drop


# ---------------------------------------------------------------------------
# The symbol decode (D2)
# ---------------------------------------------------------------------------
def resolve_glbx_year(year_digit: int, request_year: int) -> int:
    """The DOWNLOAD-YEAR-ANCHORED decade rule: the smallest year >= ``request_year`` whose final
    digit is ``year_digit``.

    ``ZCH6`` is March 2016 in the ``year=2016`` raw prefix and March 2026 in the ``year=2026`` one.
    The anchor is the resolution year carried in the S3 path, NEVER ``datetime.now()``: a backfill
    re-run in 2031 over the 2016 raw bytes must decode identically, and a wall-clock anchor would
    silently re-date fifteen years of history."""
    if not 0 <= int(year_digit) <= 9:
        raise ValueError(f"year_digit {year_digit!r} is not a single decimal digit")
    request_year = int(request_year)
    candidate = request_year - (request_year % 10) + int(year_digit)
    if candidate < request_year:
        candidate += 10
    return candidate


def window_anchor(root: str, request_year: int) -> date:
    """The DEFAULT decode anchor for one ``(root, request_year)``: the request window's first
    day (the root's first usable date inside its first year, Jan 1 otherwise). Deterministic,
    clock-free, and the same value the fetch job's ``year_window`` opens on."""
    first = datetime.strptime(ROOT_FIRST_DATE[root], "%Y-%m-%d").date()
    return max(first, date(int(request_year), 1, 1))


def _month_index(year: int, month: int) -> int:
    return int(year) * 12 + int(month) - 1


def resolve_glbx_contract_year(year_digit: int, month: int, root: str, anchor: date) -> int:
    """The LISTING-INTERVAL-ANCHORED decade rule (V2-4 M1), for roots that declare a horizon.

    The delivery month ``(year, month)`` is the unique decade candidate inside
    ``[anchor month - 1, anchor month + horizon + 12]`` where ``horizon`` is the root's declared
    listing depth (:data:`GLBX_LISTING_HORIZON_MONTHS`): a decade is 120 months apart and that
    window is at most 74 months wide for a 60-month listing, so exactly one candidate fits.

    ``anchor`` is the symbol's resolved listing-interval start (``d0`` from the symbology artifact)
    when the caller has it, else the window start (:func:`window_anchor`) -- the +12 slack exists
    for that fallback (a contract first listed in December of the window year sits 12 months past
    the window's January anchor). The one-month grace BEFORE the anchor is the CPO termination
    rule: a December contract prints on the first business day of January.

    Roots WITHOUT a declared horizon must not reach this function -- their decode is the shipped
    download-year rule, byte-for-byte."""
    horizon = GLBX_LISTING_HORIZON_MONTHS.get(root)
    if horizon is None:
        raise ValueError(f"root {root!r} declares no GLBX_LISTING_HORIZON_MONTHS entry")
    base = resolve_glbx_year(year_digit, anchor.year)     # smallest year >= anchor year
    lo = _month_index(anchor.year, anchor.month) - _HORIZON_GRACE_MONTHS
    hi = _month_index(anchor.year, anchor.month) + int(horizon) + _HORIZON_WINDOW_SLACK_MONTHS
    for candidate in (base - 10, base, base + 10):
        if lo <= _month_index(candidate, month) <= hi:
            return candidate
    raise ValueError(
        f"{root}: no decade candidate for year digit {year_digit} / month {month} lies inside "
        f"[{anchor} - {_HORIZON_GRACE_MONTHS}m, + {int(horizon) + _HORIZON_WINDOW_SLACK_MONTHS}m]"
    )


def decode_symbol(symbol: str, root: str, dataset: str, request_year: int,
                  *, anchor: Optional[date] = None) -> tuple[int, int]:
    """``(contract_year, contract_month_number)`` for one outright symbol. FAIL CLOSED.

    GLBX ``ZCH6`` -> month code ``H`` + single-digit year ``6``, disambiguated by
    :func:`resolve_glbx_year` against ``request_year`` -- or, for a root that declares a listing
    horizon (:data:`GLBX_LISTING_HORIZON_MONTHS`), by :func:`resolve_glbx_contract_year` against
    ``anchor`` (the symbol's resolved listing-interval start; the window start when absent).

    ICE ``KC  FMZ0026!`` -> month code ``Z`` + the fixed-width 4-digit field ``0026``. The plan
    calls that field a 4-digit year and it is UNAMBIGUOUS either way it is read (``0026`` -> 26 ->
    2026; a full ``2026`` -> 2026), so no decade rule is applied and ``request_year`` is unused on
    this branch -- which is precisely why the ICE leg cannot suffer the D2 decade defect."""
    if not is_outright(symbol, root, dataset):
        raise ValueError(
            f"{symbol!r} is not an outright of root {root!r} on {dataset} -- the outright filter "
            f"must run BEFORE the decode (plan F1); a spread/TAS/numeric-id symbol has no "
            f"delivery month"
        )
    if dataset == GLBX:
        code, digit = symbol[-2], symbol[-1]
        month = MONTH_CODES[code]
        if root in GLBX_LISTING_HORIZON_MONTHS:
            a = anchor if anchor is not None else window_anchor(root, request_year)
            return resolve_glbx_contract_year(int(digit), month, root, a), month
        return resolve_glbx_year(int(digit), request_year), month
    # ICE: ... FM<code><dddd>!
    body = symbol.split()[-1]           # "FMZ0026!"
    code = body[2]
    digits = int(body[3:7])
    if digits < 100:
        year = 2000 + digits
    elif 1900 <= digits <= 2100:
        year = digits
    else:
        raise ValueError(f"{symbol!r}: 4-digit year field {digits!r} is outside 1900..2100")
    return year, MONTH_CODES[code]


def contract_month_str(symbol: str, root: str, dataset: str, request_year: int,
                       *, anchor: Optional[date] = None) -> str:
    """The ``YYYY-MM`` delivery-month string for one outright symbol."""
    year, month = decode_symbol(symbol, root, dataset, request_year, anchor=anchor)
    return CONTRACT_MONTH_FMT % (year, month)


def symbol_anchors_from_artifact(artifact: Optional[dict]) -> dict[str, date]:
    """``{raw_symbol: earliest d0}`` over the symbology artifact's STEP-2 chunks -- the per-symbol
    resolved listing-interval start that anchors the decade decode for horizon-declaring roots.
    Empty when the artifact is absent or carries no usable ``d0`` (the decode then anchors on the
    window start, which the horizon slack is sized for)."""
    out: dict[str, date] = {}
    if not artifact:
        return out
    for chunk in artifact.get("resolve_step2") or []:
        if not isinstance(chunk, dict):
            continue
        for entries in (chunk.get("result") or {}).values():
            for e in entries or []:
                sym, d0 = e.get("s"), e.get("d0")
                if not sym or not d0:
                    continue
                try:
                    d = date.fromisoformat(str(d0)[:10])
                except ValueError:
                    continue
                if sym not in out or d < out[sym]:
                    out[sym] = d
    return out


def contract_month_map(symbols: Iterable[str], root: str, dataset: str, request_year: int,
                       anchors: Optional[dict[str, date]] = None) -> dict[str, str]:
    """``{raw_symbol: 'YYYY-MM'}`` for a set of outrights, each decoded against its own resolved
    listing anchor when one is known."""
    anchors = anchors or {}
    return {s: contract_month_str(s, root, dataset, request_year, anchor=anchors.get(s))
            for s in symbols}


def _anchor_fallbacks(symbols: Iterable[str], root: str, anchors: Optional[dict[str, date]],
                      *, label: str) -> Optional[int]:
    """How many outrights of a HORIZON-DECLARING root decode on the WINDOW anchor because the
    symbology artifact carried no resolved ``d0`` for them (an artifact with no STEP-2 chunks, or
    one re-landed by an older fetch). The fallback is bounded by the 74-month decode window and
    backstopped by the row lint, but a degraded anchor must be NAMED AND COUNTED (STEP-12 F10),
    never silent: the count rides in the unit record and is logged at INFO when non-zero. ``None``
    for a root that declares no horizon -- the anchor is inert there and a count would be noise
    (absence declared, not a zero)."""
    if root not in GLBX_LISTING_HORIZON_MONTHS:
        return None
    syms = list(symbols)
    have = anchors or {}
    missing = sorted(s for s in syms if s not in have)
    if missing:
        logger.info("%s: %d of %d outright(s) carry no resolved d0 anchor -- decoding them on "
                    "the window anchor instead (bounded by the decode window, linted by the "
                    "horizon fence): %s%s", label, len(missing), len(syms),
                    ", ".join(missing[:10]), " ..." if len(missing) > 10 else "")
    return len(missing)


def contract_horizon_violations(frame: pd.DataFrame, root: str) -> pd.DataFrame:
    """Rows whose ``contract_month`` sits more than the root's declared listing horizon AFTER
    ``trade_date``'s month, or more than one month BEFORE it (V2-4 M1's row-level lint). Empty for
    a root with no declared horizon. Pure; the caller decides whether to raise."""
    horizon = GLBX_LISTING_HORIZON_MONTHS.get(root)
    if horizon is None or frame is None or frame.empty:
        return pd.DataFrame(columns=["raw_symbol", "trade_date", "contract_month", "months_ahead"])
    td = pd.to_datetime(frame["trade_date"], errors="coerce")
    cm = pd.to_datetime(frame["contract_month"].astype(str) + "-01", errors="coerce")
    ahead = (cm.dt.year * 12 + cm.dt.month) - (td.dt.year * 12 + td.dt.month)
    bad = frame.loc[(ahead > int(horizon)) | (ahead < -_HORIZON_GRACE_MONTHS) | ahead.isna(),
                    ["raw_symbol", "trade_date", "contract_month"]].copy()
    bad["months_ahead"] = ahead[bad.index]
    return bad.reset_index(drop=True)


def lint_contract_horizon(frame: pd.DataFrame, root: str, *, label: str) -> None:
    """HARD FAIL when any bronze row lies outside the root's declared listing horizon -- the
    decade-lift shape (a January trade date carrying a delivery month ten years out) must never
    reach a registered surface. Inert for roots that declare no horizon."""
    bad = contract_horizon_violations(frame, root)
    if len(bad):
        detail = ", ".join(f"{r.raw_symbol}@{str(r.trade_date)[:10]}->{r.contract_month}"
                           f"({int(r.months_ahead) if pd.notna(r.months_ahead) else 'nan'}m)"
                           for r in bad.head(10).itertuples())
        raise ValueError(
            f"{label}: {len(bad)} row(s) carry a contract_month outside the declared listing "
            f"horizon of {GLBX_LISTING_HORIZON_MONTHS[root]} months (grace {_HORIZON_GRACE_MONTHS} "
            f"month before): {detail} -- the decade decode lifted a delivery month, refusing"
        )


# ---------------------------------------------------------------------------
# Fixed-point prices and the undefined sentinels
# ---------------------------------------------------------------------------
# Every DBN price is a fixed-point i64 where 1 unit = 1e-9 (databento_dbn FIXED_PRICE_SCALE).
FIXED_PRICE_SCALE = 1_000_000_000
# i64 max: the "no price" sentinel. `to_df(price_type="float")` substitutes NaN for it on PRICE
# fields -- but this module decodes with price_type="fixed" and does the substitution itself, so
# the scaling is explicit, version-independent and testable on a synthetic int frame.
UNDEF_PRICE = 9223372036854775807
# The SAME i64-max value on StatMsg.quantity -- and `to_df` does NOT mask it, because quantity is
# not a price field. An unmasked settlement row therefore leaks 9223372036854775807 straight into
# open_interest. On a DBN v1 file the field is i4 and the sentinel is i4 max instead.
UNDEF_STAT_QUANTITY = 9223372036854775807
UNDEF_STAT_QUANTITY_V1 = 2147483647
UNDEF_TIMESTAMP = 18446744073709551615


def scale_fixed_price(values) -> pd.Series:
    """Fixed-point i64 -> float, with :data:`UNDEF_PRICE` mapped to NaN.

    Applied ONCE, here. A second application would divide by 1e18."""
    s = pd.to_numeric(pd.Series(values).reset_index(drop=True), errors="coerce")
    return s.where(s != UNDEF_PRICE).astype("float64") / FIXED_PRICE_SCALE


def mask_stat_quantity(values) -> pd.Series:
    """StatMsg.quantity -> nullable Int64, with BOTH undefined sentinels masked (v1 i4 max and
    v2/v3 i8 max). ``to_df`` masks neither."""
    s = pd.to_numeric(pd.Series(values).reset_index(drop=True), errors="coerce")
    s = s.where(~s.isin([UNDEF_STAT_QUANTITY, UNDEF_STAT_QUANTITY_V1]))
    return s.astype("Int64")


# ---------------------------------------------------------------------------
# The statistics vocabulary (D3)
# ---------------------------------------------------------------------------
# databento_dbn.StatType integer values, verified against StatType.variants(). They arrive in a
# DataFrame as RAW INTS, never enums -- compare against these constants, never against a string.
STAT_TYPE_SETTLEMENT_PRICE = 3
STAT_TYPE_OPEN_INTEREST = 9
# databento_dbn.StatUpdateAction: a statistic is newly ADDED (1) or DELETED/retracted (2). The
# preliminary -> final settlement path F3 describes travels through exactly this field.
STAT_UPDATE_ACTION_NEW = 1
STAT_UPDATE_ACTION_DELETE = 2
# `stat_flags` promises a final-vs-preliminary / actual-vs-theoretical discriminator, but there is
# NO StatFlags enum anywhere in the installed databento or databento_dbn -- the bit layout is not
# decodable from the package. It is persisted RAW and never interpreted here; "which settlement is
# final" is decided by (ts_ref, ts_recv) ordering below. Do not guess bit positions.
STAT_FLAGS_COL = "stat_flags"

# DBN version handling, MEASURED against real purchased data (2026-07-29). The vendor's batch
# renderer is per-dataset inconsistent: every GLBX.MDP3 payload from the W2 buy arrived as DBN v1
# while every IFUS/IFEU payload arrived v3. The original guard here refused anything != 3 on the
# premise that `to_df` follows the FILE's struct layout as-is (i4 StatMsg.quantity in v1) -- that
# premise is FALSE for the installed client: databento-dbn 0.63 NORMALIZES old versions on read.
# Verified live on ZC/2016: ohlcv v1 -> 2,852 rows (the plan's measured bar count TO THE ROW),
# statistics v1 -> settlements 408-415c agreeing with same-year closes, OI quantities sane
# (median 5,257, max 812,073, none negative -- no truncated-struct garbage). So: accept every
# version the installed client demonstrably normalizes (1..MAX), FAIL CLOSED only on versions
# NEWER than the client knows, which it genuinely cannot decode.
MAX_DBN_VERSION = 3


# ---------------------------------------------------------------------------
# The ICE double-bar rule (D4 / F2)
# ---------------------------------------------------------------------------
# PROVISIONAL. F2 measured ICE emitting ~2 ohlcv-1d bars per contract per UTC day (KC FMZ0026! =
# 2,2,2,2,2 Mon-Fri) while GLBX emits exactly 1, and each raw_symbol maps to exactly one
# instrument_id so it is not a symbology artifact. The plan's hypothesis is that ICE sessions
# straddle the UTC-day bucket; the client-package recon offers a competing, sharper one:
# GLBX.MDP3 has ONE publisher (id 1) while each ICE dataset has TWO -- the venue and an
# off-exchange XOFF feed (IFEU 57/84, IFUS 97/98) -- which would also explain the observed
# VARIABILITY (RC FMX0026! = 1,2,2,1,1: an off-exchange bar exists only on days with block prints).
#
# ***  PROBE P3 RESOLVED ON REAL PURCHASED DATA (2026-07-29): FLIPPED.  ***
# Measured on KC/2025 raw batch bars: 3,350 of 4,700 rows sit in (raw_symbol, trade_date)
# duplicate pairs, EVERY pair splits by publisher (venue 97 vs XOFF 98), and under the
# provisional keep_last_by_ts_event the kept side was a 62/38 RANDOM MIX (XOFF printed later
# 1,037 times, venue later 638) -- worse than either pure rule. The venue-vs-XOFF close
# divergence is 0.72% MEDIAN with some XOFF closes zero/undefined sentinels, which is exactly
# gate 7's measured 0.8-5% parity drift vs the yfinance venue closes and gate 5's bar-internal
# inconsistencies. prefer_on_venue_publisher is deterministic, needs no timestamp heuristic,
# and an XOFF bar is a real but DIFFERENT market (block/EFP), so dropping it is a modelling
# choice rather than a dedupe. Either way gate 1 asserts POST-dedupe uniqueness table-wide and
# any surviving duplicate is a hard fail, never a silent dedupe.
ICE_BAR_RULE = "prefer_on_venue_publisher"
ICE_BAR_RULES: tuple[str, ...] = ("keep_last_by_ts_event", "prefer_on_venue_publisher")
# databento.common.publishers, verified numerically: the on-venue and off-exchange publisher ids.
ICE_ON_VENUE_PUBLISHER_IDS: frozenset[int] = frozenset({57, 97})    # IFEU_IMPACT_IFEU, IFUS_IMPACT_IFUS
ICE_OFF_EXCHANGE_PUBLISHER_IDS: frozenset[int] = frozenset({84, 98})  # ..._XOFF

BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "raw_symbol", "contract_month", "instrument_id",
    "publisher_id", "open", "high", "low", "close", "volume", "settle", "open_interest",
    "settle_flags", "dataset", "root",
]


# ---------------------------------------------------------------------------
# F-A: raw_symbol -> exactly ONE instrument_id PER DATE within a (root, year)
# ---------------------------------------------------------------------------
def assert_symbol_instrument_1to1(df: pd.DataFrame, *, label: str,
                                  ts_col: str = "ts_event") -> None:
    """HARD FAIL if any ``(raw_symbol, date)`` maps to more than one ``instrument_id``.

    AMENDED 2026-07-29, the transform-side twin of the fetch-side F-A amendment (25bc746d):
    GLBX RECYCLES instrument_ids across products, so one symbol may be carried by TWO ids on
    DISJOINT date ranges inside a year -- measured at resolve time on KEN4/KE-2021, then again
    HERE on ZCN4/ZC-2010 when the global 1:1 form of this check refused four roots' bronze.
    A disjoint re-listing is fully decodable: every ``(raw_symbol, date)`` still has exactly one
    id, the DBNStore symbology map is interval-scoped, and the ohlcv/statistics join keys on
    ``(instrument_id, date)``. What genuinely breaks F2's falsification test and the join is one
    symbol on two ids on the SAME date -- so that, exactly, is what is refused. Without a usable
    ``ts_col`` the check falls back to the strict global form (fail-closed when dates are
    unknowable). Disjoint re-listings are logged, never refused."""
    if df.empty or "raw_symbol" not in df.columns or "instrument_id" not in df.columns:
        return
    work = df[["raw_symbol", "instrument_id"]].copy()
    if ts_col in df.columns:
        ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        work["_d"] = ts.dt.tz_localize(None).dt.normalize()
    else:
        work["_d"] = pd.NaT  # no timestamp -> one NaT group == the strict global check
    pairs = work.dropna(subset=["raw_symbol", "instrument_id"]).drop_duplicates()
    counts = pairs.groupby(["raw_symbol", "_d"], dropna=False)["instrument_id"].nunique()
    bad = counts[counts > 1]
    if len(bad):
        detail = ", ".join(f"{sym}@{str(d)[:10]}->{int(n)} ids"
                           for (sym, d), n in bad.head(10).items())
        raise ValueError(
            f"{label}: {len(bad)} (raw_symbol, date) pair(s) map to MULTIPLE instrument_ids "
            f"({detail}) -- F-A violated; the ohlcv/statistics join key and the F2 dedupe rule "
            f"are both ambiguous"
        )
    global_counts = pairs.groupby("raw_symbol")["instrument_id"].nunique()
    recycled = global_counts[global_counts > 1]
    if len(recycled):
        logger.info(
            "%s: %d symbol(s) re-listed under a new instrument_id on disjoint dates (GLBX id "
            "recycling, decodable): %s", label, len(recycled),
            ", ".join(str(s) for s in recycled.index[:5]))


def dedupe_ice_bars(df: pd.DataFrame, *, rule: str = ICE_BAR_RULE) -> tuple[pd.DataFrame, dict]:
    """Collapse the F2 double bar to ONE row per ``(raw_symbol, trade_date)``.

    ``keep_last_by_ts_event`` (the provisional default) keeps the latest bar of the UTC day.
    ``prefer_on_venue_publisher`` keeps the on-venue publisher's bar and drops XOFF, falling back
    to the ts_event rule where the pair does not split by publisher. Returns the deduped frame and
    a stats dict the gate/probe records."""
    if rule not in ICE_BAR_RULES:
        raise ValueError(f"unknown ICE_BAR_RULE {rule!r} (known: {list(ICE_BAR_RULES)})")
    if df.empty:
        return df, {"rule": rule, "rows_in": 0, "rows_out": 0, "dropped": 0,
                    "dup_keys": 0, "publisher_split_keys": 0}
    key = ["raw_symbol", "trade_date"]
    dup_keys = int((df.groupby(key).size() > 1).sum())
    split = 0
    if "publisher_id" in df.columns:
        nun = df.groupby(key)["publisher_id"].nunique()
        split = int((nun > 1).sum())

    work = df.copy()
    # Deterministic ordering. `ts_event` is the F2 discriminator; `_on_venue` (1 = on-venue,
    # 0 = XOFF) is the competing publisher rule. Both orderings end on "take the last row".
    work["_on_venue"] = 0
    if "publisher_id" in work.columns:
        work["_on_venue"] = work["publisher_id"].isin(ICE_ON_VENUE_PUBLISHER_IDS).astype(int)
    sort_cols = key + (["_on_venue", "ts_event"] if rule == "prefer_on_venue_publisher"
                       else ["ts_event"])
    sort_cols = [c for c in sort_cols if c in work.columns]
    work = work.sort_values(sort_cols, kind="mergesort")
    out = work.drop_duplicates(subset=key, keep="last").drop(columns=["_on_venue"])
    out = out.sort_values(key, kind="mergesort").reset_index(drop=True)
    stats = {"rule": rule, "rows_in": int(len(df)), "rows_out": int(len(out)),
             "dropped": int(len(df) - len(out)), "dup_keys": dup_keys,
             "publisher_split_keys": split}
    logger.info("databento ICE dedupe [%s]: %d -> %d rows (dup_keys=%d publisher_split=%d)",
                rule, stats["rows_in"], stats["rows_out"], dup_keys, split)
    return out, stats


# ---------------------------------------------------------------------------
# ohlcv-1d -> bronze
# ---------------------------------------------------------------------------
_OHLCV_REQUIRED = ("ts_event", "instrument_id", "symbol", "open", "high", "low", "close", "volume")


def empty_ohlcv_frame() -> pd.DataFrame:
    """The decoded-ohlcv shape with ZERO rows -- what a settlement-tape root feeds
    :func:`build_ohlcv_bronze` when no ohlcv payload exists (the column check there runs BEFORE
    the empty check, so the columns must be present)."""
    return pd.DataFrame(columns=list(_OHLCV_REQUIRED))


def build_ohlcv_bronze(
    df: pd.DataFrame,
    *,
    dataset: str,
    root: str,
    request_year: int,
    prices_are_fixed: bool = True,
    ice_bar_rule: str = ICE_BAR_RULE,
    symbol_anchors: Optional[dict[str, date]] = None,
) -> tuple[pd.DataFrame, dict]:
    """One ``(dataset, root, request_year)`` ohlcv-1d frame -> bronze rows. PURE.

    ``df`` is a decoded DBN frame: the ``OHLCVMsg`` fields plus the ``symbol`` column the DBN
    metadata / ``symbology.json`` mapping supplies. ``ts_event`` may be the index or a column.

    ``prices_are_fixed=True`` means open/high/low/close are the raw fixed-point i64 values (the
    ``price_type="fixed"`` decode this module uses); the 1e-9 scaling and the UNDEF_PRICE masking
    happen here, exactly once.

    ``trade_date`` is the UTC calendar date of ``ts_event`` -- ohlcv-1d carries no ``ts_recv``, so
    ts_event IS the bar clock for this schema (statistics is windowed on ts_recv instead, which is
    why the two legs are joined on the statistics ``ts_ref`` trading date rather than on a shared
    request window)."""
    if dataset not in DATASET_SLUGS:
        raise ValueError(f"unknown dataset {dataset!r}")
    if ROOT_MAP.get(root, (None, None))[0] != dataset:
        raise ValueError(f"root {root!r} does not belong to dataset {dataset!r} (ROOT_MAP)")
    slug = ROOT_MAP[root][1]

    work = df.copy()
    if "ts_event" not in work.columns:
        work = work.reset_index()
    missing = [c for c in _OHLCV_REQUIRED if c not in work.columns]
    if missing:
        raise ValueError(f"databento ohlcv {root}/{request_year}: frame is missing {missing}")
    ohlcv_label = f"databento ohlcv {root}/{request_year}"
    if work.empty:
        return pd.DataFrame(columns=BRONZE_COLUMNS), {
            "rows_in": 0, "rows_out": 0, "outright_symbols": 0, "dropped_symbols": 0,
            "ice_dedupe": None, "root": root, "dataset": dataset, "year": int(request_year),
            "anchor_fallbacks": _anchor_fallbacks([], root, symbol_anchors, label=ohlcv_label)}

    keep, drop = partition_symbols(work["symbol"], root, dataset)
    work = work[work["symbol"].isin(set(keep))].copy()
    if work.empty:
        logger.warning("databento ohlcv %s/%s: every symbol was filtered out (%d dropped)",
                       root, request_year, len(drop))
        return pd.DataFrame(columns=BRONZE_COLUMNS), {
            "rows_in": int(len(df)), "rows_out": 0, "outright_symbols": 0,
            "dropped_symbols": len(drop), "ice_dedupe": None, "root": root,
            "dataset": dataset, "year": int(request_year),
            "anchor_fallbacks": _anchor_fallbacks([], root, symbol_anchors, label=ohlcv_label)}

    work = work.rename(columns={"symbol": "raw_symbol"})
    assert_symbol_instrument_1to1(work, label=f"databento ohlcv {root}/{request_year}")

    ts = pd.to_datetime(work["ts_event"], utc=True, errors="coerce")
    work["ts_event"] = ts
    work["trade_date"] = ts.dt.tz_localize(None).dt.normalize()

    month_by_symbol = contract_month_map(keep, root, dataset, request_year, symbol_anchors)
    anchor_fallbacks = _anchor_fallbacks(keep, root, symbol_anchors, label=ohlcv_label)
    work["contract_month"] = work["raw_symbol"].map(month_by_symbol)
    lint_contract_horizon(work, root, label=ohlcv_label)

    for col in ("open", "high", "low", "close"):
        work[col] = (scale_fixed_price(work[col].to_numpy()).to_numpy()
                     if prices_are_fixed
                     else pd.to_numeric(work[col], errors="coerce").astype("float64").to_numpy())
    work["volume"] = pd.to_numeric(work["volume"], errors="coerce").astype("Int64")
    work["instrument_id"] = pd.to_numeric(work["instrument_id"], errors="coerce").astype("Int64")
    if "publisher_id" in work.columns:
        work["publisher_id"] = pd.to_numeric(work["publisher_id"], errors="coerce").astype("Int64")
    else:
        work["publisher_id"] = pd.Series([pd.NA] * len(work), dtype="Int64")

    work["leviathan_slug"] = slug
    work["dataset"] = dataset
    work["root"] = root
    work["settle"] = np.nan            # GLBX fills from statistics (D3); ICE from close (D4)
    work["open_interest"] = pd.Series([pd.NA] * len(work), dtype="Int64")
    work["settle_flags"] = pd.Series([pd.NA] * len(work), dtype="Int64")

    dedupe_stats = None
    ice_probe = None
    if dataset in ICE_DATASETS:
        # PROBE P3 runs on the PRE-dedupe frame -- probing the deduped output is self-blinding
        # (dup_keys is 0 by construction after the collapse; that exact mistake shipped and
        # reported "no double bars in batch files" on 2026-07-29 while the dedupe was quietly
        # collapsing ~40% of ICE rows).
        ice_probe = probe_ice_bar_rule(work)
        work, dedupe_stats = dedupe_ice_bars(work, rule=ice_bar_rule)

    out = work[BRONZE_COLUMNS].sort_values(["raw_symbol", "trade_date"], kind="mergesort")
    out = out.reset_index(drop=True)
    stats = {"rows_in": int(len(df)), "rows_out": int(len(out)),
             "outright_symbols": len(keep), "dropped_symbols": len(drop),
             "ice_dedupe": dedupe_stats, "ice_probe": ice_probe, "root": root,
             "dataset": dataset, "year": int(request_year),
             "anchor_fallbacks": anchor_fallbacks}
    logger.info("databento ohlcv %s/%s: %d rows, %d outright symbols, %d dropped",
                root, request_year, len(out), len(keep), len(drop))
    return out, stats


# ---------------------------------------------------------------------------
# statistics -> settle + open_interest (D3)
# ---------------------------------------------------------------------------
_STATS_REQUIRED = ("ts_recv", "ts_ref", "instrument_id", "symbol", "price", "quantity",
                   "stat_type", "update_action")


def build_statistics_bronze(
    df: pd.DataFrame,
    *,
    root: str,
    request_year: int,
    prices_are_fixed: bool = True,
    keep_instrument_id: bool = False,
) -> pd.DataFrame:
    """GLBX ``statistics`` -> one row per ``(raw_symbol, trade_date)`` carrying ``settle`` /
    ``open_interest`` / ``settle_flags``. PURE.

    ``keep_instrument_id=True`` (the settlement-spine path, V2-4) appends the key's
    ``instrument_id`` as a sixth column; the default keeps the five-column shape the seven live
    GLBX roots' LEFT join has always consumed, byte-identical.

    Three rules, each for a measured reason:

      * **``trade_date`` comes from ``ts_ref``**, not from ``ts_recv`` or ``ts_event``. ``ts_ref``
        IS "the trading date of the settlement price" / "the trading date for which open interest
        was calculated". It is also what makes the join to ohlcv-1d sound: ``statistics`` carries
        ``ts_recv`` so the vendor windows it on a DIFFERENT clock than ohlcv-1d (``ts_event``), and
        a same-start/end request pair does NOT guarantee the same set of trade dates.
      * **deletes are honoured.** Within one ``(instrument_id, ts_ref, stat_type)`` the LAST record
        by ``ts_recv`` wins; if that record is ``update_action == DELETE`` the statistic was
        retracted and the key is dropped. This is the preliminary -> final settlement path of F3,
        resolved by arrival order rather than by guessing ``stat_flags`` bit positions (the package
        ships no decoder for them).
      * **``quantity`` is masked by hand** -- ``to_df`` NaN-substitutes UNDEF_PRICE on price fields
        only, so an unmasked settlement row leaks i64-max into ``open_interest``.
    """
    dataset = GLBX
    if ROOT_MAP.get(root, (None, None))[0] != dataset:
        raise ValueError(
            f"statistics is a GLBX-only leg (root {root!r} is not GLBX) -- the ICE statistics "
            f"schema costs $1,696 (IFUS) + $264 (IFEU) and is EXCLUDED by the plan"
        )
    cols = (["raw_symbol", "trade_date", "settle", "open_interest", "settle_flags"]
            + (["instrument_id"] if keep_instrument_id else []))
    work = df.copy()
    if "ts_recv" not in work.columns:
        work = work.reset_index()
    missing = [c for c in _STATS_REQUIRED if c not in work.columns]
    if missing:
        raise ValueError(f"databento statistics {root}/{request_year}: frame is missing {missing}")
    if work.empty:
        return pd.DataFrame(columns=cols)

    keep, _drop = partition_symbols(work["symbol"], root, dataset)
    work = work[work["symbol"].isin(set(keep))].rename(columns={"symbol": "raw_symbol"}).copy()
    if work.empty:
        return pd.DataFrame(columns=cols)
    assert_symbol_instrument_1to1(work, label=f"databento statistics {root}/{request_year}")

    work["stat_type"] = pd.to_numeric(work["stat_type"], errors="coerce").astype("Int64")
    work["update_action"] = pd.to_numeric(work["update_action"], errors="coerce").astype("Int64")
    work = work[work["stat_type"].isin([STAT_TYPE_SETTLEMENT_PRICE, STAT_TYPE_OPEN_INTEREST])]
    if work.empty:
        return pd.DataFrame(columns=cols)

    work["ts_recv"] = pd.to_datetime(work["ts_recv"], utc=True, errors="coerce")
    ref = pd.to_datetime(work["ts_ref"], utc=True, errors="coerce")
    work["trade_date"] = ref.dt.tz_localize(None).dt.normalize()
    work = work[work["trade_date"].notna()]
    if work.empty:
        return pd.DataFrame(columns=cols)

    # LAST record per (raw_symbol, trade_date, stat_type) by arrival, then drop retractions.
    work = work.sort_values(["raw_symbol", "trade_date", "stat_type", "ts_recv"], kind="mergesort")
    latest = work.drop_duplicates(subset=["raw_symbol", "trade_date", "stat_type"], keep="last")
    deleted = int((latest["update_action"] == STAT_UPDATE_ACTION_DELETE).sum())
    latest = latest[latest["update_action"] == STAT_UPDATE_ACTION_NEW]
    if latest.empty:
        logger.warning("databento statistics %s/%s: every statistic was retracted (%d deletes)",
                       root, request_year, deleted)
        return pd.DataFrame(columns=cols)
    # The key's instrument_id (one per (raw_symbol, date) by F-A, asserted above): the settlement
    # spine carries it into BRONZE_COLUMNS where the bar frame would otherwise have supplied it.
    iid = (latest.drop_duplicates(subset=["raw_symbol", "trade_date"], keep="last")
           [["raw_symbol", "trade_date", "instrument_id"]])

    settle_rows = latest[latest["stat_type"] == STAT_TYPE_SETTLEMENT_PRICE].copy()
    if prices_are_fixed:
        settle_rows["settle"] = scale_fixed_price(settle_rows["price"].to_numpy()).to_numpy()
    else:
        settle_rows["settle"] = pd.to_numeric(settle_rows["price"], errors="coerce").astype("float64").to_numpy()
    if STAT_FLAGS_COL in settle_rows.columns:
        settle_rows["settle_flags"] = pd.to_numeric(
            settle_rows[STAT_FLAGS_COL], errors="coerce").astype("Int64")
    else:
        settle_rows["settle_flags"] = pd.Series([pd.NA] * len(settle_rows), dtype="Int64")
    settle_rows = settle_rows[["raw_symbol", "trade_date", "settle", "settle_flags"]]

    oi_rows = latest[latest["stat_type"] == STAT_TYPE_OPEN_INTEREST].copy()
    oi_rows["open_interest"] = mask_stat_quantity(oi_rows["quantity"].to_numpy()).to_numpy()
    oi_rows = oi_rows[["raw_symbol", "trade_date", "open_interest"]]

    out = settle_rows.merge(oi_rows, on=["raw_symbol", "trade_date"], how="outer")
    out["open_interest"] = out["open_interest"].astype("Int64")
    out["settle_flags"] = out["settle_flags"].astype("Int64")
    if keep_instrument_id:
        out = out.merge(iid, on=["raw_symbol", "trade_date"], how="left")
        out["instrument_id"] = pd.to_numeric(out["instrument_id"], errors="coerce").astype("Int64")
    out = out[cols].sort_values(["raw_symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    logger.info("databento statistics %s/%s: %d (symbol, date) keys (%d retracted)",
                root, request_year, len(out), deleted)
    return out


def join_glbx_statistics(ohlcv: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """Attach ``settle`` / ``open_interest`` / ``settle_flags`` to GLBX bars (D3).

    LEFT join on ``(raw_symbol, trade_date)``: a bar with no settlement keeps ``settle`` NULL
    rather than falling back to ``close``. F3 is the whole point -- the ohlcv close is the last
    trade of the session and is NOT the exchange settlement, so a silent fallback would
    manufacture exactly the mislabel ``settle_kind`` exists to make impossible. ``close`` stays in
    ``close``."""
    if ohlcv.empty:
        return ohlcv
    base = ohlcv.drop(columns=[c for c in ("settle", "open_interest", "settle_flags")
                               if c in ohlcv.columns])
    if stats is None or stats.empty:
        base["settle"] = np.nan
        base["open_interest"] = pd.Series([pd.NA] * len(base), dtype="Int64")
        base["settle_flags"] = pd.Series([pd.NA] * len(base), dtype="Int64")
        return base[BRONZE_COLUMNS].reset_index(drop=True)
    out = base.merge(stats, on=["raw_symbol", "trade_date"], how="left")
    out["open_interest"] = out["open_interest"].astype("Int64")
    out["settle_flags"] = out["settle_flags"].astype("Int64")
    matched = int(out["settle"].notna().sum())
    logger.info("databento GLBX statistics join: %d/%d bars carry a settlement", matched, len(out))
    return out[BRONZE_COLUMNS].reset_index(drop=True)


def build_settlement_bronze(
    stats: Optional[pd.DataFrame],
    bars: Optional[pd.DataFrame],
    *,
    dataset: str,
    root: str,
    request_year: int,
    symbol_anchors: Optional[dict[str, date]] = None,
) -> tuple[pd.DataFrame, dict]:
    """The SETTLEMENT-SPINE bronze for a :data:`SETTLEMENT_TAPE_ROOTS` root (V2-4). PURE.

    The row skeleton is the reduced statistics keys -- ``(raw_symbol, ts_ref trade_date)`` with
    ``settle`` (stat_type 3) and ``open_interest`` (stat_type 9) outer-merged, last-by-ts_recv,
    deletes honoured, exactly what :func:`build_statistics_bronze` returns with
    ``keep_instrument_id=True``. Every key becomes a row carrying ``leviathan_slug`` / ``dataset`` /
    ``root`` / the decoded ``contract_month`` (the listing-interval-anchored decade rule) with
    ``open`` / ``high`` / ``low`` / ``close`` NaN and ``volume`` / ``publisher_id`` NULL. Bars, if
    any, LEFT-join onto those keys: a bar with no settlement on a mark tape is a stray and is
    dropped -- the mirror of :func:`join_glbx_statistics` stated in the row shape. F3 holds in
    both directions: no close ever becomes a settle, no settle ever becomes a close.

    ``stats`` empty -> zero rows (the caller's floor decides what that means); a non-member root
    raises (the seven live GLBX roots keep the bar-driven path byte-for-byte)."""
    if root not in SETTLEMENT_TAPE_ROOTS:
        raise ValueError(f"root {root!r} is not a settlement-tape root (SETTLEMENT_TAPE_ROOTS = "
                         f"{sorted(SETTLEMENT_TAPE_ROOTS)}); the bar-driven bronze owns it")
    if ROOT_MAP.get(root, (None, None))[0] != dataset:
        raise ValueError(f"root {root!r} does not belong to dataset {dataset!r} (ROOT_MAP)")
    slug = ROOT_MAP[root][1]
    label = f"databento settlement {root}/{request_year}"
    empty_stats = {"rows_in": 0, "rows_out": 0, "outright_symbols": 0, "dropped_symbols": 0,
                   "ice_dedupe": None, "root": root, "dataset": dataset, "year": int(request_year),
                   "settlement_base": True, "statistics_keys": 0, "bar_keys_attached": 0,
                   "bars_without_settlement_dropped": 0,
                   "horizon_months": GLBX_LISTING_HORIZON_MONTHS.get(root),
                   "rows_beyond_horizon": 0,
                   "anchor_fallbacks": _anchor_fallbacks([], root, symbol_anchors, label=label)}
    if stats is None or stats.empty:
        return pd.DataFrame(columns=BRONZE_COLUMNS), empty_stats

    keep, drop = partition_symbols(stats["raw_symbol"], root, dataset)
    base = stats[stats["raw_symbol"].isin(set(keep))].copy()
    if base.empty:
        return pd.DataFrame(columns=BRONZE_COLUMNS), dict(empty_stats, rows_in=int(len(stats)),
                                                          dropped_symbols=len(drop))
    base["trade_date"] = pd.to_datetime(base["trade_date"]).dt.normalize()
    base["contract_month"] = base["raw_symbol"].map(
        contract_month_map(keep, root, dataset, request_year, symbol_anchors))
    anchor_fallbacks = _anchor_fallbacks(keep, root, symbol_anchors, label=label)
    base["leviathan_slug"] = slug
    base["dataset"] = dataset
    base["root"] = root
    for col in ("open", "high", "low", "close"):
        base[col] = np.nan
    base["volume"] = pd.Series([pd.NA] * len(base), dtype="Int64", index=base.index)
    base["publisher_id"] = pd.Series([pd.NA] * len(base), dtype="Int64", index=base.index)
    if "instrument_id" in base.columns:
        base["instrument_id"] = pd.to_numeric(base["instrument_id"], errors="coerce").astype("Int64")
    else:
        base["instrument_id"] = pd.Series([pd.NA] * len(base), dtype="Int64", index=base.index)
    base["settle"] = pd.to_numeric(base["settle"], errors="coerce").astype("float64")
    base["open_interest"] = pd.to_numeric(base["open_interest"], errors="coerce").astype("Int64")
    base["settle_flags"] = pd.to_numeric(base["settle_flags"], errors="coerce").astype("Int64")

    attached = 0
    strays = 0
    if bars is not None and not bars.empty:
        # the bar columns that ATTACH to a statistics key (a projection, not a vocabulary)
        attach = ["raw_symbol", "trade_date", "open", "high", "low", "close", "volume",
                  "publisher_id"]
        b = bars[[c for c in attach if c in bars.columns]].copy()
        b["trade_date"] = pd.to_datetime(b["trade_date"]).dt.normalize()
        b = b.drop_duplicates(subset=["raw_symbol", "trade_date"], keep="last")
        keys = set(zip(base["raw_symbol"], base["trade_date"]))
        strays = int(sum((s, d) not in keys for s, d in zip(b["raw_symbol"], b["trade_date"])))
        merged = base.drop(columns=[c for c in attach[2:] if c in base.columns]).merge(
            b, on=["raw_symbol", "trade_date"], how="left")
        for col in ("open", "high", "low", "close"):
            merged[col] = pd.to_numeric(merged[col], errors="coerce").astype("float64")
        merged["volume"] = pd.to_numeric(merged["volume"], errors="coerce").astype("Int64")
        merged["publisher_id"] = pd.to_numeric(merged["publisher_id"], errors="coerce").astype("Int64")
        attached = int(merged["close"].notna().sum())
        base = merged

    assert_symbol_instrument_1to1(base, label=label, ts_col="trade_date")
    lint_contract_horizon(base, root, label=label)
    out = base[BRONZE_COLUMNS].sort_values(["raw_symbol", "trade_date"], kind="mergesort")
    out = out.reset_index(drop=True)
    rec = {"rows_in": int(len(stats)), "rows_out": int(len(out)), "outright_symbols": len(keep),
           "dropped_symbols": len(drop), "ice_dedupe": None, "root": root, "dataset": dataset,
           "year": int(request_year), "settlement_base": True, "statistics_keys": int(len(base)),
           "bar_keys_attached": attached, "bars_without_settlement_dropped": strays,
           "horizon_months": GLBX_LISTING_HORIZON_MONTHS.get(root),
           "rows_beyond_horizon": int(len(contract_horizon_violations(out, root))),
           "anchor_fallbacks": anchor_fallbacks}
    logger.info("databento settlement %s/%s: %d rows from %d statistics keys, %d bar keys "
                "attached (%d stray bars dropped)", root, request_year, len(out), len(base),
                attached, strays)
    return out, rec


def statistics_join_diagnostics(ohlcv: pd.DataFrame, stats: Optional[pd.DataFrame], *,
                                max_offset_days: int = 3) -> dict:
    """PROBE: is the GLBX statistics leg on the SAME calendar as the ohlcv leg?

    The two legs are windowed on DIFFERENT clocks. ``ohlcv-1d`` carries no ``ts_recv``, so its
    ``trade_date`` is the UTC calendar day of ``ts_event``; ``statistics`` is windowed on ``ts_recv``
    and its ``trade_date`` is the exchange TRADING date from ``ts_ref``. A systematic one-day skew
    between them makes :func:`join_glbx_statistics` match nothing -- and it fails SILENTLY, because
    the left join leaves ``settle`` NULL by design (F3, correctly) and gate 6 compares ``settle_kind``
    LABELS only, which are map-derived and do not depend on ``settle`` being non-null.

    Shifting the statistics dates by ``k`` days and counting ``(raw_symbol, trade_date)`` overlap for
    every ``k`` in ``[-max_offset_days, +max_offset_days]`` is a whole-frame set intersection, not a
    per-symbol loop. ``best_offset_days != 0`` means the join is matching on the wrong clock."""
    out: dict = {"stat_keys": 0, "bar_keys": 0, "overlap_by_offset": {}, "best_offset_days": None,
                 "matched_at_zero": 0}
    if ohlcv is None or stats is None or ohlcv.empty or stats.empty:
        return out
    need = {"raw_symbol", "trade_date"}
    if need - set(ohlcv.columns) or need - set(stats.columns):
        return out
    bars = set(zip(ohlcv["raw_symbol"].astype(str),
                   pd.to_datetime(ohlcv["trade_date"]).dt.normalize()))
    sym = stats["raw_symbol"].astype(str).to_numpy()
    sdate = pd.to_datetime(stats["trade_date"]).dt.normalize()
    overlap: dict[int, int] = {}
    for k in range(-int(max_offset_days), int(max_offset_days) + 1):
        shifted = sdate + pd.Timedelta(days=k)
        overlap[k] = len(bars & set(zip(sym, shifted)))
    best = max(overlap, key=lambda k: (overlap[k], -abs(k)))
    out.update({"stat_keys": int(len(stats)), "bar_keys": int(len(bars)),
                "overlap_by_offset": {str(k): int(v) for k, v in sorted(overlap.items())},
                "best_offset_days": int(best), "matched_at_zero": int(overlap.get(0, 0))})
    if best != 0 and overlap[best] > overlap.get(0, 0):
        logger.error("databento GLBX statistics: the best (raw_symbol, trade_date) overlap is at a "
                     "%+d day shift (%d keys) vs %d at zero -- the ts_ref trading date and the "
                     "ts_event UTC day are on DIFFERENT calendars and the settle join is matching "
                     "the wrong clock", best, overlap[best], overlap.get(0, 0))
    return out


def glbx_settle_coverage(bronze: pd.DataFrame) -> dict:
    """The GLBX ``settle`` non-null fraction on a JOINED bronze frame.

    This is the number nothing else looks at. ``join_glbx_statistics`` only logs it; the registry's
    ``value_columns``/``min_nonnull_frac`` floor fires at publish on a TABLE-WIDE collapse, and a
    GLBX-only miss is diluted below it by the ICE rows (where ``settle == close`` by construction).
    Returned per unit so the producer task can floor it."""
    if bronze is None or bronze.empty or "settle" not in bronze.columns:
        return {"rows": 0, "settle_nonnull": 0, "settle_nonnull_frac": None,
                "open_interest_nonnull_frac": None, "oi_keys_without_settle": None}
    n = int(len(bronze))
    settle = pd.to_numeric(bronze["settle"], errors="coerce")
    settle_n = int(settle.notna().sum())
    oi = bronze["open_interest"] if "open_interest" in bronze.columns else None
    return {
        "rows": n,
        "settle_nonnull": settle_n,
        "settle_nonnull_frac": round(settle_n / n, 4),
        "open_interest_nonnull_frac": (round(int(oi.notna().sum()) / n, 4)
                                       if oi is not None else None),
        # KP2's instrument (V2-4): 'settlement rows present for every OI-bearing key'. On a
        # settlement-spine root an OI key with no settle is a row the mark tape published OI for
        # but no mark -- counted, never silently NULL.
        "oi_keys_without_settle": (int((oi.notna() & settle.isna()).sum())
                                   if oi is not None else None),
    }


def month_continuity_holes(frame: pd.DataFrame, *, slug_col: str = "leviathan_slug",
                           date_col: str = "trade_date") -> dict[str, list[str]]:
    """``{slug: ['YYYY-MM', ...]}`` -- the calendar months INSIDE a slug's banked span that carry
    ZERO trade dates (V2-4 M2's month-continuity gate). PURE.

    Measured per maximal run of CONSECUTIVE calendar years present in the frame (a repair run over
    two non-adjacent years is two spans, not one hole), from the run's first trade date's month
    to its last trade date's month. An internal hole is the shape ``covers()`` cannot see: a
    window inside it routes to the table and declines ``no_tape_rows`` instead of naming the floor
    -- so a hole must fail the producer/gate, never land."""
    if frame is None or len(frame) == 0 or slug_col not in frame.columns or date_col not in frame.columns:
        return {}
    td = pd.to_datetime(frame[date_col], errors="coerce")
    work = pd.DataFrame({"slug": frame[slug_col].astype(str).to_numpy(),
                         "ym": (td.dt.year * 12 + td.dt.month - 1).to_numpy(),
                         "year": td.dt.year.to_numpy()}).dropna()
    holes: dict[str, list[str]] = {}
    for slug, g in work.groupby("slug"):
        years = sorted({int(y) for y in g["year"]})
        runs: list[list[int]] = []
        for y in years:
            if runs and y == runs[-1][-1] + 1:
                runs[-1].append(y)
            else:
                runs.append([y])
        present = {int(v) for v in g["ym"]}
        missing: list[str] = []
        for run in runs:
            sub = g[g["year"].isin(run)]
            lo, hi = int(sub["ym"].min()), int(sub["ym"].max())
            for ym in range(lo, hi + 1):
                if ym not in present:
                    missing.append(f"{ym // 12:04d}-{ym % 12 + 1:02d}")
        if missing:
            holes[str(slug)] = missing
    return holes


def apply_ice_settle(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """ICE leg (D4): ``settle`` IS the session ``close``; ``open_interest`` stays NULL.

    The ICE ``statistics`` schema -- the real settlement AND open-interest series -- costs $1,696
    (IFUS) + $264 (IFEU) and is excluded from the buy, so there is nothing else it could be. The
    row is labelled ``settle_kind='close'`` from CONTRACT_MAP, which is what makes the substitution
    honest rather than a mislabel."""
    if ohlcv.empty:
        return ohlcv
    out = ohlcv.copy()
    out["settle"] = pd.to_numeric(out["close"], errors="coerce").astype("float64")
    out["open_interest"] = pd.Series([pd.NA] * len(out), dtype="Int64")
    out["settle_flags"] = pd.Series([pd.NA] * len(out), dtype="Int64")
    return out[BRONZE_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# The DBN decode lane (the only place the vendor package is touched)
# ---------------------------------------------------------------------------
# The ten keys databento's ``InstrumentMap.insert_json`` validates -- a missing one raises.
SYMBOLOGY_RESOLVE_KEYS: tuple[str, ...] = (
    "result", "symbols", "stype_in", "stype_out", "start_date", "end_date",
    "partial", "not_found", "message", "status",
)


def symbology_from_artifact(artifact: Optional[dict]) -> Optional[dict]:
    """The raw symbology artifact -> ONE ``symbology.resolve``-shaped mapping, or ``None``.

    ONLY the STEP-2 chunks (``stype_in=instrument_id, stype_out=raw_symbol``) are merged.

    *** THIS FUNCTION EXISTS BECAUSE STEP 1 IS A TRAP. ***
    ``resolve_step1`` is ``stype_in=parent, stype_out=instrument_id``, so
    ``databento.common.symbology._resolve_mapping_tuple`` takes its ``stype_out == INSTRUMENT_ID``
    branch and returns ``(symbol_in, instrument_id)`` -- and ``symbol_in`` is the PARENT symbol.
    Inserting it maps EVERY instrument_id to the single literal string ``'ZC.FUT'``; the outright
    filter then drops 100% of the purchased bars, every unit trips the row floor, and the task exits
    1 -- discovered only AFTER the $45 is spent. The producer writes both steps into the artifact,
    so the consumer must pick, and it must pick step 2."""
    if not artifact:
        return None
    result: dict[str, list[dict]] = {}
    for chunk in artifact.get("resolve_step2") or []:
        if not isinstance(chunk, dict):
            continue
        for iid, entries in (chunk.get("result") or {}).items():
            for e in entries or []:
                if e.get("s"):
                    result.setdefault(str(iid), []).append(
                        {"d0": e.get("d0"), "d1": e.get("d1"), "s": e.get("s")})
    if not result:
        return None
    window = artifact.get("window") or {}
    return {
        "result": result,
        "symbols": sorted(result),
        "stype_in": "instrument_id",
        "stype_out": "raw_symbol",
        "start_date": window.get("start"),
        "end_date": window.get("end_exclusive"),
        "partial": [], "not_found": [], "message": "OK", "status": 0,
    }


def decode_dbn(raw_bytes: bytes, *, schema: str,
               symbology_json: Optional[dict] = None,
               max_version: Optional[int] = MAX_DBN_VERSION) -> pd.DataFrame:
    """``.dbn.zst`` bytes -> a decoded DataFrame with RAW fixed-point prices and a ``symbol`` column.

    ``databento`` is imported lazily so every rule above stays testable with no vendor dependency.

    ``price_type='fixed'`` is deliberate: this module owns the 1e-9 scaling and the sentinel
    masking (``to_df`` masks UNDEF_PRICE but never UNDEF_STAT_QUANTITY, so half-trusting it is
    worse than not trusting it at all).

    ``max_version`` is a CEILING, not an equality (amended 2026-07-29 on real purchased data --
    the vendor rendered every GLBX payload as DBN v1 and every IFUS/IFEU payload as v3 in the
    same buy). The installed client NORMALIZES old versions on read -- verified live on ZC/2016
    v1: 2,852 ohlcv rows matching the plan's measured bar count exactly, settlements agreeing
    with same-year closes, OI quantities sane -- so old versions decode correctly; a version
    NEWER than the client's max genuinely cannot, and fails closed."""
    try:
        from databento import DBNStore
    except ImportError as exc:  # pragma: no cover -- exercised by the batch task preflight
        raise ImportError(
            "the 'databento' package is required to decode DBN payloads -- add it to the "
            "[batch] extra and REBUILD the worker image before any cloud run"
        ) from exc

    store = DBNStore.from_bytes(raw_bytes)
    version = getattr(store.metadata, "version", None)
    if max_version is not None and version is not None and int(version) > int(max_version):
        raise ValueError(
            f"DBN version {version} is NEWER than the installed client's max {max_version}: "
            f"databento-dbn normalizes OLD versions on read (v1 verified live on ZC/2016, "
            f"2026-07-29) but cannot know a future struct layout -- refusing to decode. "
            f"Upgrade the databento/databento-dbn packages and re-run."
        )
    if symbology_json:
        # FAIL CLOSED on the step-1 shape. A `parent -> instrument_id` mapping inserts the literal
        # '<ROOT>.FUT' as the symbol of EVERY instrument, the outright filter then drops 100% of the
        # bars, and the only symptom is an empty frame. Never let that reach the decode.
        got_out = str(symbology_json.get("stype_out", "")).lower()
        got_in = str(symbology_json.get("stype_in", "")).lower()
        if got_out != "raw_symbol":
            raise ValueError(
                f"symbology.json has stype_out={got_out!r} (stype_in={got_in!r}) -- only a "
                f"stype_out='raw_symbol' mapping may be injected. A parent->instrument_id resolve "
                f"maps every instrument to the literal '<ROOT>.FUT' and the outright filter then "
                f"drops every purchased bar (use symbology_from_artifact, which merges STEP 2)"
            )
    # PREFER THE IN-BAND MAPPINGS. A batch DBN carries its own SymbolMappingMsg set; overwriting it
    # with clear_existing=True discards the vendor's authoritative, interval-correct mapping in
    # favour of a re-derived one. The artifact is the FALLBACK, for a payload that has none.
    if not getattr(store.metadata, "mappings", None):
        if not symbology_json:
            raise ValueError(
                "DBN payload carries no symbol mappings and no symbology.json was supplied -- the "
                "raw_symbol column would be all-None and every row would fail the outright filter"
            )
        store.insert_symbology_json(symbology_json, clear_existing=True)
    df = store.to_df(price_type="fixed", pretty_ts=True, map_symbols=True, schema=schema)
    return df.reset_index()


def extract_databento_bronze(
    ohlcv_bytes: Optional[bytes],
    *,
    dataset: str,
    root: str,
    request_year: int,
    statistics_bytes: Optional[bytes] = None,
    symbology_json: Optional[dict] = None,
    ice_bar_rule: str = ICE_BAR_RULE,
    symbol_anchors: Optional[dict[str, date]] = None,
) -> tuple[pd.DataFrame, dict]:
    """The module's single I/O-free-but-vendor-decoding entry point: raw bytes -> bronze rows.

    GLBX takes ``statistics_bytes`` (D3); ICE must not (the schema is excluded from the buy) and
    routes through :func:`apply_ice_settle` (D4). A :data:`SETTLEMENT_TAPE_ROOTS` root takes an
    ABSENT ``ohlcv_bytes`` (the fetch buys statistics only) and REQUIRES ``statistics_bytes`` --
    the tape IS the statistics stream, so 'no statistics payload' is a missing unit, never a
    settle-stays-NULL warning."""
    settlement_tape = root in SETTLEMENT_TAPE_ROOTS
    if ohlcv_bytes is None:
        if not settlement_tape:
            raise ValueError(f"{dataset} {root}/{request_year}: no ohlcv-1d payload and the root "
                             f"is not a settlement-tape root")
        raw = empty_ohlcv_frame()
    else:
        raw = decode_dbn(ohlcv_bytes, schema="ohlcv-1d", symbology_json=symbology_json)
    bronze, stats = build_ohlcv_bronze(raw, dataset=dataset, root=root,
                                       request_year=request_year, ice_bar_rule=ice_bar_rule,
                                       symbol_anchors=symbol_anchors)
    if dataset == GLBX:
        if statistics_bytes is None:
            if settlement_tape:
                raise ValueError(
                    f"{dataset} {root}/{request_year}: a settlement-tape root with NO statistics "
                    f"payload -- the tape IS the statistics stream (SETTLEMENT_TAPE_ROOTS)")
            logger.warning("databento %s/%s: no statistics payload -- settle stays NULL (F3: the "
                           "ohlcv close is NOT the settlement and is never substituted)",
                           root, request_year)
            stat_df = None
        else:
            stat_raw = decode_dbn(statistics_bytes, schema="statistics",
                                  symbology_json=symbology_json)
            stat_df = build_statistics_bronze(stat_raw, root=root, request_year=request_year,
                                              keep_instrument_id=settlement_tape)
        if settlement_tape:
            bronze, srec = build_settlement_bronze(stat_df, bronze, dataset=dataset, root=root,
                                                   request_year=request_year,
                                                   symbol_anchors=symbol_anchors)
            stats.update(srec)
        else:
            bronze = join_glbx_statistics(bronze, stat_df)
    else:
        if statistics_bytes is not None:
            raise ValueError(
                f"{dataset}: an ICE statistics payload was supplied, but the ICE statistics schema "
                f"is EXCLUDED from the buy ($1,960) -- ICE settle is the close (D4)"
            )
        bronze = apply_ice_settle(bronze)
    return bronze, stats


def probe_ice_bar_rule(df: pd.DataFrame) -> dict:
    """PROBE P3: does the F2 duplicate pair split by PUBLISHER, or only by ts_event?

    Recorded on real purchased data before the registered publish. A high
    ``publisher_split_frac`` confirms the recon hypothesis and
    :data:`ICE_BAR_RULE` should flip to ``prefer_on_venue_publisher``; near-zero leaves the
    provisional ts_event rule in place. Pure and read-only -- it decides nothing by itself."""
    key = ["raw_symbol", "trade_date"]
    if df.empty or any(c not in df.columns for c in key):
        return {"dup_keys": 0, "publisher_split_keys": 0, "publisher_split_frac": None,
                "publisher_mix": {}, "recommended_rule": ICE_BAR_RULE}
    sizes = df.groupby(key).size()
    dup_keys = int((sizes > 1).sum())
    split = 0
    if "publisher_id" in df.columns:
        nun = df.groupby(key)["publisher_id"].nunique()
        split = int((nun > 1).sum())
    frac = (split / dup_keys) if dup_keys else None
    mix = ({int(k): int(v) for k, v in df["publisher_id"].dropna().value_counts().items()}
           if "publisher_id" in df.columns else {})
    return {
        "dup_keys": dup_keys,
        "publisher_split_keys": split,
        "publisher_split_frac": round(frac, 4) if frac is not None else None,
        "publisher_mix": mix,
        "recommended_rule": ("prefer_on_venue_publisher"
                             if frac is not None and frac >= 0.99 else ICE_BAR_RULE),
    }
