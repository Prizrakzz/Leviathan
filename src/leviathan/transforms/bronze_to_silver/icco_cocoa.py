"""ICCO cocoa balance: the RELEASES table (one row per season per bulletin) and the served silver.

TWO BUILDERS, ONE SOURCE OF TRUTH (2026-09-29, data repairs ICCO-1..4)
-----------------------------------------------------------------------
``build_icco_releases`` reads the banked bulletin PAGES (never the JSON sidecars, which were minted
by whichever parser ran last month and are rewritten on a bucket with versioning suspended) and
writes ``silver_icco_cocoa_releases``: ONE ROW PER SEASON PER RELEASE -- what each bulletin itself
stated about each season, stamped with the date the bulletin became known (its dateline).

``build_icco_silver`` then rebuilds the served ``silver_icco_cocoa`` FROM that table, with its shape
unchanged (the same ten columns, one row per cocoa year): each season is the WHOLE row of the latest
release that stated it.  So a closed season carries its final revision (ICCO-1), no row mixes two
releases (ICCO-3), and an as-of reader that needs what was known earlier reads the releases table
(ICCO-4).

WHICH SEASON A COLUMN IS: THE HEADER IS A CLAIM, NOT A WITNESS (T-ICCO-1)
-------------------------------------------------------------------------
The publisher mislabelled its own table header twice (May-2023: both seasons shifted back a year;
Aug-2023: season A printed 2020/2021).  So a column's season is CONFIRMED by a witness the header
cannot corrupt, and the witnesses win over the header:

* THE RELEASE CHAIN.  A column marked a/ restates a figure "published in the previous Quarterly
  Bulletin".  The previous bulletin is the predecessor in the publisher's own sequence (Volume,
  Issue).  When the restated column equals, on all four balance figures, exactly one season the
  predecessor itself stated, that fixes the restated column's season -- and, because the table's
  season groups are consecutive cocoa years left to right, the season of every group beside it.
* THE INTRO STATEMENT.  The paragraph that carries the bulletin's identity names, BEFORE the identity
  statement, the seasons the release covers ("revised forecasts for the 2022/23 cocoa year and
  revised estimates ... for the 2021/22 cocoa year").  Every season it names must be on the table.

When the chain anchors the table, the chain decides and the intro statement must agree.  With no
chain (the predecessor is not captured, or the restated figures were edited), the header stands only
if the intro statement confirms it; if the intro statement names a consecutive pair the header does
not, the intro statement decides.  Anything else -- no witness, or witnesses that disagree -- writes
the release's rows MISSING with the reason, never a guess.  Every header the witnesses overruled is
listed in the run log.

THE ROW (T-ICCO-3, T-ICCO-4, T-ICCO-7, T-ICCO-8)
-----------------------------------------------
* The release's OWN statement of a season: the rightmost column of that season NOT marked a/.
  Restated columns are chain witnesses, never rows; a season the page prints only as a restatement
  (the 2026 layout's "Estimates a/") has no row in that release.
* ``figure_kind`` is the header's own word through ONE declared map (forecast, revised_forecast,
  estimate, revised_estimate); a season the Secretariat WITHHELD is a row with every figure MISSING,
  ``figure_kind`` withheld and ``missing_reason`` withheld, known at the release date.
* The identity production x (1 - loss) - grindings - surplus is computed on every row
  (``identity_gap_kt``) and flagged when it exceeds the publisher's kt rounding; a failing row is
  flagged, never dropped.  The loss is the share footnote b/ states: on the page when the page states
  it, else the one value every bulletin that states one agrees on (named in ``weight_loss_source``).

What the served table does NOT change (N-7, reported not redefined): ``grindings_3yr_trend`` is a
rolling mean over ROWS, so across a gap in the seasons it averages non-adjacent seasons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.icco_cocoa import (
    BALANCE_METRICS,
    MINTED_PAGE_NAME,
    PARSE_VERSION,
    ParsedPage,
    parse_qbcs_page,
    roman_to_int,
    season_label,
    season_start,
)

logger = get_logger(__name__)

_TREND_WINDOW = 3
_TREND_MIN_PERIODS = 2

#: The publisher prints each figure rounded to the kt, and computes the surplus from unrounded
#: figures: three rounded terms and a 1 % loss on a rounded production drift by at most ~1.5 kt.
#: 3 kt is that bound with a margin (T-ICCO-8).
IDENTITY_TOLERANCE_KT = 3.0

#: The rung a release date came from that never wins "latest" while a dated release exists.
FALLBACK_RELEASE_DATE_SOURCE = "bulletin_month_fallback"

SOURCE = "icco_qbcs"

SILVER_COLUMNS: list[str] = [
    "cocoa_year",
    "latest_release_date",
    "production_kt",
    "grindings_kt",
    "end_stocks_kt",
    "surplus_deficit_kt",
    "su_ratio",
    "grindings_3yr_trend",
    "grindings_trend_dev",
    "source",
]

#: silver_icco_cocoa_releases -- one row per (release_date, cocoa_year).  Order = writer order.
RELEASES_COLUMNS: list[str] = [
    "release_date",
    "release_date_source",
    "bulletin_volume",
    "bulletin_issue",
    "cocoa_year",
    "figure_kind",
    "header_season",
    "season_witnesses",
    "production_kt",
    "grindings_kt",
    "end_stocks_kt",
    "surplus_deficit_kt",
    "stocks_to_grindings_pct_published",
    "su_ratio",
    "weight_loss_pct",
    "weight_loss_source",
    "identity_gap_kt",
    "identity_status",
    "stocks_identity_gap_kt",
    "missing_reason",
    "source_url",
    "page_key",
    "page_sha256",
    "parse_version",
    "source",
]

#: The declared writer types of the releases table (INV-2 target tokens): the integrator's contract
#: must declare exactly these (a deck asserts it once the registry holds the table).
RELEASES_ARROW_TYPES: dict[str, str] = {
    **{c: "string" for c in RELEASES_COLUMNS},
    "bulletin_issue": "int64",
    **{c: "float64" for c in ("production_kt", "grindings_kt", "end_stocks_kt", "surplus_deficit_kt",
                              "stocks_to_grindings_pct_published", "su_ratio", "weight_loss_pct",
                              "identity_gap_kt", "stocks_identity_gap_kt")},
}

RELEASES_NATURAL_KEY = ["release_date", "cocoa_year"]


@dataclass(frozen=True)
class PageInput:
    """One banked page: its object key, its bytes, and the release_date= folder it sits in.

    The folder is where a past fetch filed it -- a CLAIM (the Aug-2017 bulletin sits under a folder
    its November-2019 URL chose), used only to prefer the capture whose folder agrees with the
    page's own dateline when one bulletin was filed twice.
    """

    key: str
    body: bytes
    folder_release_date: str | None = None


def _predecessor(identity: tuple[int, int]) -> tuple[int, int]:
    volume, issue = identity
    return (volume, issue - 1) if issue > 1 else (volume - 1, 4)


def _consecutive(seasons: Iterable[str]) -> bool:
    starts = [season_start(s) for s in seasons]
    return all(b == a + 1 for a, b in zip(starts, starts[1:]))


def _same_balance(a: dict, b: dict) -> bool:
    """Equal on all four balance figures, each present on both sides."""
    for m in BALANCE_METRICS:
        x, y = a.get(m), b.get(m)
        if x is None or y is None or (isinstance(x, float) and np.isnan(x)) or \
                (isinstance(y, float) and np.isnan(y)) or float(x) != float(y):
            return False
    return True


def _num(v) -> float:
    return float("nan") if v is None else float(v)


def _choose_primary(pages: list[tuple[PageInput, ParsedPage]]) -> tuple[PageInput, ParsedPage]:
    """One capture per bulletin identity: the one whose folder agrees with its own dateline, else
    the minting ``page.html`` over a later content-addressed capture, else the earliest folder."""
    def rank(item):
        pin, pp = item
        agrees = pin.folder_release_date == pp.release_date
        minted = pin.key.rsplit("/", 1)[-1] == MINTED_PAGE_NAME
        return (not agrees, not minted, pin.folder_release_date or "", pin.key)
    return sorted(pages, key=rank)[0]


def _statement(pp: ParsedPage) -> str:
    """A comparable digest of what a page states (for duplicate captures of one bulletin)."""
    cols = [(c.header_season, c.kind_text, c.restated, tuple(sorted(c.values.items())))
            for c in pp.columns]
    prose = [(r["cocoa_year"], tuple(sorted(r["values"].items()))) for r in pp.prose_rows]
    return repr((pp.release_date, cols, prose, tuple(pp.withheld_seasons)))


def _assign_table_seasons(pp: ParsedPage, predecessor_rows: dict[str, dict] | None,
                          log: dict) -> tuple[list[str] | None, dict[int, set], str | None]:
    """Seasons of the table's groups (left to right), each group's witnesses, or a refusal reason."""
    groups = sorted({c.group for c in pp.columns})
    header = [next(c.header_season for c in pp.columns if c.group == g) for g in groups]
    k = len(groups)
    x_header = header if _consecutive(header) and len(set(header)) == k else None
    ident = f"Vol. {pp.bulletin_volume} No. {pp.bulletin_issue} ({pp.release_date})"

    # (i) the release chain
    anchors: dict[int, str] = {}
    if predecessor_rows is not None:
        for c in pp.columns:
            if not c.restated:
                continue
            hits = [s for s, vals in predecessor_rows.items() if _same_balance(c.values, vals)]
            if len(hits) == 1:
                anchors.setdefault(groups.index(c.group), hits[0])
                if anchors[groups.index(c.group)] != hits[0]:
                    return None, {}, f"the chain names two seasons for one header group on {ident}"
            else:
                mine = predecessor_rows.get(c.header_season)
                log["chain_mismatches"].append({
                    "release": ident, "column": c.position, "header_season": c.header_season,
                    "restated": {m: c.values.get(m) for m in BALANCE_METRICS},
                    "predecessor_row_for_header_season": mine and {m: mine.get(m) for m in BALANCE_METRICS},
                    "matches": hits,
                })
    x_chain = None
    for gi, s in anchors.items():
        cand = [season_label(season_start(s) - gi + i) for i in range(k)]
        if x_chain is not None and cand != x_chain:
            return None, {}, f"two chain anchors disagree on {ident}: {x_chain} vs {cand}"
        x_chain = cand

    stated = list(pp.statement_seasons)
    chosen = None
    basis = None
    if x_chain is not None:
        if stated and not set(stated) <= set(x_chain):
            return None, {}, (f"the release chain puts {x_chain} on {ident} while the intro statement "
                              f"names {stated}")
        chosen, basis = x_chain, "chain"
    elif stated:
        if x_header is not None and set(stated) <= set(x_header):
            chosen, basis = x_header, "header"
        elif len(set(stated)) == k and _consecutive(sorted(stated)):
            chosen, basis = sorted(stated), "statement"
        else:
            return None, {}, (f"no witness confirms the header {header} on {ident}: the intro "
                              f"statement names {stated} and the predecessor is "
                              f"{'not captured' if predecessor_rows is None else 'not matched'}")
    else:
        return None, {}, f"no witness beyond the header {header} on {ident}"

    witnesses: dict[int, set] = {}
    for gi in range(k):
        w = set()
        if header[gi] == chosen[gi]:
            w.add("header")
        if basis == "chain":
            w.add("chain" if gi in anchors else "chain_adjacent")
        if chosen[gi] in stated:
            w.add("statement")
        witnesses[gi] = w
    if chosen != header:
        log["header_overruled"].append({"release": ident, "header": header, "witnessed": chosen,
                                        "basis": basis})
    return chosen, witnesses, None


def build_icco_releases(pages: list[PageInput]) -> tuple[pd.DataFrame, dict]:
    """Build ``silver_icco_cocoa_releases`` from the banked pages.  Returns (rows, run log).

    Never guesses: a page that cannot be parsed, a release whose seasons no witness confirms, a
    season the Secretariat withheld -- each is listed in the run log, and the last two are written
    as rows with every figure MISSING and the reason.
    """
    if not pages:
        raise ValueError("ICCO releases: no bulletin page to build from")
    log: dict = {"parse_version": PARSE_VERSION, "pages_read": len(pages), "unparsed_pages": [],
                 "duplicate_captures": [], "header_overruled": [], "chain_mismatches": [],
                 "unconfirmed_releases": [], "restated_only": [], "identity_exceeds_rounding": [],
                 "absent_bulletins": [], "volume_year_offsets": [], "date_rungs": {}}

    parsed: dict[tuple[int, int], list[tuple[PageInput, ParsedPage]]] = {}
    for pin in pages:
        pp = parse_qbcs_page(pin.body)
        if pp.failure or pp.identity is None:
            log["unparsed_pages"].append({"key": pin.key, "reason": pp.failure or "no bulletin identity"})
            continue
        parsed.setdefault(pp.identity, []).append((pin, pp))

    releases: dict[tuple[int, int], tuple[PageInput, ParsedPage]] = {}
    for ident, items in parsed.items():
        primary = _choose_primary(items)
        releases[ident] = primary
        for other in items:
            if other is primary:
                continue
            log["duplicate_captures"].append({
                "identity": list(ident), "kept": primary[0].key, "duplicate": other[0].key,
                "same_statement": _statement(other[1]) == _statement(primary[1])})

    offsets = sorted({pp.title_year - ident[0] for ident, (_, pp) in releases.items()
                      if pp.title_year is not None})
    log["volume_year_offsets"] = offsets
    if releases:
        lo, hi = min(releases), max(releases)
        cur = lo
        while cur < hi:
            nxt = (cur[0], cur[1] + 1) if cur[1] < 4 else (cur[0] + 1, 1)
            if nxt not in releases:
                log["absent_bulletins"].append(list(nxt))
            cur = nxt

    stated_losses = sorted({pp.weight_loss_pct for _, pp in releases.values()
                            if pp.weight_loss_pct is not None})

    own_rows: dict[tuple[int, int], dict[str, dict]] = {}
    rows: list[dict] = []
    for ident in sorted(releases):
        pin, pp = releases[ident]
        log["date_rungs"][pp.release_date_source] = log["date_rungs"].get(pp.release_date_source, 0) + 1
        pred = own_rows.get(_predecessor(ident))
        base = {
            "release_date": pp.release_date, "release_date_source": pp.release_date_source,
            "bulletin_volume": pp.bulletin_volume, "bulletin_issue": pp.bulletin_issue,
            "source_url": pp.source_url, "page_key": pin.key, "page_sha256": pp.page_sha256,
            "parse_version": PARSE_VERSION, "source": SOURCE,
        }
        if pp.weight_loss_pct is not None:
            loss, loss_src = pp.weight_loss_pct, "stated_on_page"
        elif len(stated_losses) == 1:
            loss, loss_src = stated_losses[0], "stated_in_other_bulletins"
        else:
            loss, loss_src = None, "not_stated" if not stated_losses else "bulletins_disagree"
        base.update(weight_loss_pct=loss, weight_loss_source=loss_src)

        mine: dict[str, dict] = {}
        release_rows: list[dict] = []
        if pp.layout == "table":
            seasons, witnesses, refusal = _assign_table_seasons(pp, pred, log)
            groups = sorted({c.group for c in pp.columns})
            if refusal:
                log["unconfirmed_releases"].append({"release_date": pp.release_date, "reason": refusal})
                for gi, g in enumerate(groups):
                    hs = next(c.header_season for c in pp.columns if c.group == g)
                    release_rows.append({**base, "cocoa_year": hs, "header_season": hs,
                                         "figure_kind": None, "season_witnesses": None,
                                         "missing_reason": f"season_unconfirmed: {refusal}"})
            else:
                by_season = {seasons[gi]: [c for c in pp.columns if c.group == g]
                             for gi, g in enumerate(groups)}
                for gi, season in enumerate(seasons):
                    own = [c for c in by_season[season] if not c.restated]
                    if not own:
                        log["restated_only"].append({"release_date": pp.release_date,
                                                     "cocoa_year": season})
                        continue
                    col = max(own, key=lambda c: c.position)
                    vals = dict(col.values)
                    mine[season] = vals
                    # the stocks identity reads the PRIOR season's closing stocks on the same page
                    # (its rightmost column, own or restated)
                    prev_cols = by_season.get(season_label(season_start(season) - 1)) or []
                    prior_stocks = (max(prev_cols, key=lambda c: c.position).values.get("end_stocks_kt")
                                    if prev_cols else None)
                    release_rows.append({
                        **base, "cocoa_year": season, "header_season": col.header_season,
                        "figure_kind": col.figure_kind,
                        "season_witnesses": "+".join(sorted(witnesses[gi])),
                        "_values": vals, "_prior_stocks": prior_stocks, "missing_reason": None,
                    })
        else:
            for r in pp.prose_rows:
                vals = dict(r["values"])
                w = {"statement"}
                if pred and r["cocoa_year"] in pred and _same_balance(vals, pred[r["cocoa_year"]]):
                    w.add("chain")
                mine[r["cocoa_year"]] = vals
                release_rows.append({**base, "cocoa_year": r["cocoa_year"],
                                     "header_season": None, "figure_kind": r["figure_kind"],
                                     "season_witnesses": "+".join(sorted(w)), "_values": vals,
                                     "_prior_stocks": None, "missing_reason": None})
        for s in pp.withheld_seasons:
            if any(r["cocoa_year"] == s for r in release_rows):
                continue
            release_rows.append({**base, "cocoa_year": s, "header_season": None,
                                 "figure_kind": "withheld", "season_witnesses": "statement",
                                 "missing_reason": "withheld"})
        own_rows[ident] = mine
        rows.extend(release_rows)

    out = []
    for r in rows:
        vals = r.pop("_values", None) or {}
        prior_stocks = r.pop("_prior_stocks", None)
        prod, grind = vals.get("production_kt"), vals.get("grindings_kt")
        stocks, surplus = vals.get("end_stocks_kt"), vals.get("surplus_deficit_kt")
        r.update(production_kt=_num(prod), grindings_kt=_num(grind), end_stocks_kt=_num(stocks),
                 surplus_deficit_kt=_num(surplus),
                 stocks_to_grindings_pct_published=_num(vals.get("stocks_to_grindings_pct")))
        r["su_ratio"] = (float(stocks) / float(grind)) if (stocks is not None and grind) else float("nan")
        loss = r.get("weight_loss_pct")
        if None not in (prod, grind, surplus) and loss is not None:
            gap = round(float(prod) * (1.0 - float(loss) / 100.0) - float(grind) - float(surplus), 3)
            r["identity_gap_kt"] = gap
            r["identity_status"] = "within_rounding" if abs(gap) <= IDENTITY_TOLERANCE_KT else "exceeds_rounding"
            if abs(gap) > IDENTITY_TOLERANCE_KT:
                log["identity_exceeds_rounding"].append({"release_date": r["release_date"],
                                                         "cocoa_year": r["cocoa_year"], "gap_kt": gap})
        else:
            r["identity_gap_kt"] = float("nan")
            r["identity_status"] = "not_computable"
        if None not in (stocks, surplus, prior_stocks):
            r["stocks_identity_gap_kt"] = round(float(stocks) - (float(prior_stocks) + float(surplus)), 3)
        else:
            r["stocks_identity_gap_kt"] = float("nan")
        out.append(r)

    df = pd.DataFrame(out, columns=RELEASES_COLUMNS)
    if df.empty:
        raise ValueError(f"ICCO releases: no page yielded a release ({log['unparsed_pages']})")
    df["bulletin_issue"] = df["bulletin_issue"].astype("int64")
    df = df.sort_values(["release_date", "cocoa_year"]).reset_index(drop=True)
    dup = df.duplicated(subset=RELEASES_NATURAL_KEY)
    if dup.any():
        raise ValueError(f"ICCO releases: duplicate (release_date, cocoa_year) rows: "
                         f"{df.loc[dup, RELEASES_NATURAL_KEY].values.tolist()}")
    if df.duplicated(subset=["bulletin_volume", "bulletin_issue", "cocoa_year"]).any():
        raise ValueError("ICCO releases: one bulletin states one season twice")
    log["releases"] = len(releases)
    log["rows"] = len(df)
    logger.info("ICCO releases: %d pages -> %d releases -> %d rows (%d header(s) overruled, %d "
                "unconfirmed, %d withheld)", len(pages), len(releases), len(df),
                len(log["header_overruled"]), len(log["unconfirmed_releases"]),
                int((df["missing_reason"] == "withheld").sum()))
    return df, log


def build_icco_silver(df_releases: pd.DataFrame) -> pd.DataFrame:
    """Rebuild ``silver_icco_cocoa`` (shape unchanged) from the releases table.

    Per season: the WHOLE row of the latest release that stated figures for it -- no metric is ever
    borrowed from an older release (ICCO-3), a withheld or unconfirmed row states nothing and never
    wins, and a release dated only by the month-end fallback never wins while a dated one exists.
    ``latest_release_date`` is that release's date.

    Raises:
        ValueError: If required columns are missing or no release states a figure.
    """
    required = {"release_date", "release_date_source", "bulletin_volume", "bulletin_issue",
                "cocoa_year", "missing_reason", "production_kt", "grindings_kt", "end_stocks_kt",
                "surplus_deficit_kt"}
    missing = required - set(df_releases.columns)
    if missing:
        raise ValueError(f"ICCO releases missing required columns: {sorted(missing)}")
    stated = df_releases[df_releases["missing_reason"].isna()].copy()
    if stated.empty:
        raise ValueError("ICCO releases hold no stated row")

    stated["_dated"] = stated["release_date_source"] != FALLBACK_RELEASE_DATE_SOURCE
    stated["_seq"] = [(roman_to_int(v), int(i)) for v, i in
                      zip(stated["bulletin_volume"], stated["bulletin_issue"])]
    stated = stated.sort_values(["cocoa_year", "_dated", "release_date", "_seq"])
    latest = stated.groupby("cocoa_year", as_index=False).tail(1)

    df = pd.DataFrame({
        "cocoa_year": latest["cocoa_year"].values,
        "latest_release_date": latest["release_date"].values,
        "production_kt": latest["production_kt"].astype(float).values,
        "grindings_kt": latest["grindings_kt"].astype(float).values,
        "end_stocks_kt": latest["end_stocks_kt"].astype(float).values,
        "surplus_deficit_kt": latest["surplus_deficit_kt"].astype(float).values,
    }).sort_values("cocoa_year").reset_index(drop=True)

    grind = df["grindings_kt"]
    df["su_ratio"] = np.where((grind.notna()) & (grind != 0), df["end_stocks_kt"] / grind, np.nan)
    # trailing 3-row grindings trend (no lookahead) + deviation -- over ROWS, unchanged (N-7)
    df["grindings_3yr_trend"] = (
        df["grindings_kt"].rolling(_TREND_WINDOW, min_periods=_TREND_MIN_PERIODS).mean()
    )
    df["grindings_trend_dev"] = df["grindings_kt"] - df["grindings_3yr_trend"]
    df["source"] = SOURCE

    dup = df.duplicated(subset=["cocoa_year"]).sum()
    if dup:
        raise ValueError(f"ICCO silver: {int(dup)} duplicate cocoa_year rows")

    result = df[SILVER_COLUMNS].reset_index(drop=True)
    logger.info("ICCO silver: %d cocoa years (%s..%s)", len(result),
                result["cocoa_year"].min(), result["cocoa_year"].max())
    return result
