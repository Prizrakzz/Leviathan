"""SILVER-F082: the DAG catalog -- the orchestration-family grouping of the silver estate.

The observability layer (per-family Batch-failure alarms) and the incident-runbook completeness
lint both need ONE deterministic answer to "which orchestration family does table T belong to?".
The plan's Attacker-2 framing is an EventBridge+Step-Functions (or MWAA) estate of ~7-ish source
DAGs; a *family* here is one such orchestration unit: the set of silver/gold tables a single source
pipeline produces and that a single DAG would schedule/backfill together (e.g. the weather DAG owns
nasa_power + chirps + cpc_soil + modis + the gold_weather_z consumer; the USDA-ESR DAG owns
silver_esr + its silver_esr_compact serving copy).

This module derives the catalog **from the SILVER-F010 registry**, so it can never drift from the
canonical table set: every registry table maps to exactly one family via an explicit, ordered
table-name rule table (:data:`FAMILY_RULES`), and :func:`build_catalog` raises if any table fails to
map (a new table forces an explicit family decision -- completeness is enforced, not assumed).

Pure + AWS-free + deterministic. ``silver_model_predictions`` is grouped into the ``model_output``
family but flagged ``backfillable=False`` (generation-only; it has no source-backfill DAG and is out
of the R4 backfill boundary), so consumers can include or exclude it explicitly rather than by
guessing from the name.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from leviathan.silver.registry import SilverRegistry, load_registry

__all__ = [
    "FAMILY_RULES",
    "FAMILY_LABELS",
    "CADENCE_DEFAULT_LAG_DAYS",
    "FRESHNESS_LAG_OVERRIDES",
    "DagFamily",
    "family_of",
    "build_catalog",
    "effective_sla_lag_days",
]

# ---------------------------------------------------------------------------
# The family rule table. ORDERED: the first prefix that matches a table name
# wins, so the more specific multi-token prefixes (silver_wap_table01) precede
# the shorter ones. Keyed on the stable ``table_name`` (registry identity), NOT
# on a mutable producer path. gold_weather_z is the one non-``silver_`` name.
# ---------------------------------------------------------------------------
FAMILY_RULES: tuple[tuple[str, str], ...] = (
    # --- USDA source DAGs -------------------------------------------------
    ("silver_esr_compact", "usda_esr"),
    ("silver_esr", "usda_esr"),
    ("silver_wasde", "usda_wasde"),
    # NOTE this prefix DELIBERATELY swallows silver_psd_attributes, and that is the right answer
    # rather than an accident of `startswith`: the long companion is produced from the SAME bulk
    # object, on the SAME psd_monthly chain, with the same fetcher, the same failure vocabulary and
    # the same on-call answer -- a second family would page two people for one file. The ordering
    # hazard the futures_eod / ams_gtr notes below warn about is the REVERSE case (a short prefix
    # swallowing a table that needed its own home); this is the case where the swallow is the
    # decision. Re-open it only if the long table ever gains its own schedule.
    ("silver_psd", "usda_psd"),
    ("silver_wap_table01", "usda_wap"),          # + _revisions
    ("silver_nass_", "usda_nass"),               # nass_annual / nass_crop_progress / nass_citrus
    ("silver_fgis", "usda_fgis"),
    # --- Weather / climate ------------------------------------------------
    ("silver_nasa_power", "weather"),
    ("silver_chirps", "weather"),
    ("silver_cpc_soil", "weather"),
    ("silver_modis_ndvi", "weather"),
    ("gold_weather_z", "weather"),               # the gold weather serving consumer
    ("silver_noaa_", "noaa_climate"),            # noaa_iod / noaa_oni
    # --- Palm-oil complex (Malaysia) -------------------------------------
    ("silver_mpoc_", "mpoc"),
    ("silver_mpob", "mpob"),                     # mpob / mpob_annual
    # --- Brazil / Colombia / South Africa ---------------------------------
    ("silver_unica_", "unica"),
    ("silver_conab_coffee", "conab"),
    ("silver_fnc_colombia_", "fnc_colombia"),
    ("silver_sagis_", "sagis"),
    # --- Macro / prices / positioning -------------------------------------
    ("silver_fred_fx", "fred"),
    ("silver_food_cpi", "world_bank"),
    ("silver_pink_sheet", "world_bank"),
    ("silver_futures_prices", "futures"),
    # PRICE_AND_PLAYBOOKS W1.0: the per-delivery-month EOD table gets its OWN family, not the yfinance
    # `futures` one. Its producers are a different estate (CZCE / JSE / CEPEA / Bursa / MIAX / Euronext /
    # DCE / Databento, on their own venue-timezone crons), and W3 retires the yfinance chain -- so a
    # shared family would page the wrong on-call and make the `futures` label ("...(yfinance)") a lie.
    # NOTE the ordering hazard: never write this rule as ("silver_futures", ...) -- that prefix swallows
    # BOTH tables (family_of matches on startswith) and would silently re-home the live yfinance table.
    ("silver_futures_eod", "futures_eod"),
    # D-EC DK-13: gold_board_crush gets its OWN family and is NOT folded into `futures_eod`.
    # It is a CONSUMER of that table, not a producer of it: its input is our own published silver,
    # its schedule follows the eod chain rather than any venue timezone, and a shared family would
    # make the eod family's tightest-ceiling arithmetic and its on-call page cover two different
    # jobs. Same reasoning the note above gives for keeping futures_eod out of `futures`. It has no
    # SOURCE-backfill DAG at all (there is no external source to re-fetch -- a rebuild is a re-run of
    # the arithmetic), so its family joins _NON_BACKFILL_FAMILIES below.
    ("gold_board_crush", "board_crush"),
    # GN-2 W2.3: gold_futures_spreads -- the SAME consumer-of-our-own-silver shape as board_crush
    # (input = silver_futures_eod; no external source; rebuild = re-run the arithmetic), so its own
    # family for the same ceiling/on-call reasons, and _NON_BACKFILL_FAMILIES membership below.
    ("gold_futures_spreads", "futures_spreads"),
    ("silver_cot", "cftc"),
    # --- Single-source specialty ------------------------------------------
    ("silver_production", "faostat"),
    ("silver_ams_cotton_quality", "ams"),
    # AMS GTR: the SAME AGENCY as `ams` above and deliberately NOT the same family. A family here is
    # one orchestration unit, not one publisher: cotton quality is a classing-office bale file, GTR is
    # seven SODA datasets on data.gov behind their own weekly Thursday release, with their own fetcher
    # (jobs/ingest/fetch_ams_gtr.py), their own failure vocabulary (a SODA unit-declaration assert) and
    # their own on-call answer. Folding them would make the `ams` label ("cotton quality") a lie and
    # would page the cotton on-call for a barge-rate outage -- the same reasoning the futures_eod note
    # below gives for keeping it out of `futures`.
    # NOTE THE SAME ORDERING HAZARD: never write this rule as ("silver_ams", ...) -- that prefix
    # swallows BOTH tables (family_of matches on startswith) and would silently re-home the live
    # cotton-quality table into the freight family.
    ("silver_ams_gtr", "ams_gtr"),
    ("silver_icco_cocoa", "icco"),
    # MINAGRO: its OWN family, not folded into any grain family. The producer is a headless
    # BROWSER capture of a Ukrainian ministry page behind a Cloudflare managed challenge --
    # a different runtime (the browser image), a different failure vocabulary (rc 6 refused /
    # rc 7 challenge) and a different on-call answer from every other table here.
    ("silver_minagro_grain_exports", "minagro"),
    # MOEX AGRO INDICES: its OWN family, and not folded into `futures_eod` or `futures`. These are
    # INDICATIVE INDICES, not per-delivery-month settlements -- there is no contract month, no curve
    # and no venue-timezone settlement window to share. More decisively, the family's defining
    # operational fact is a NETWORK one nothing else here carries: iss.moex.com answers from AWS and
    # not from the estate's laptop, so its on-call answer to "the fetcher fails" starts somewhere no
    # other family's does, and its jobs can never be reproduced locally.
    ("silver_moex_agro_indices", "moex_agro"),
    # EEX FREIGHT: its OWN family, and specifically NOT `futures_eod` even though both are venue
    # settlement prices per contract month. Two facts separate them and both are operational. First,
    # the SOURCE SHAPE: api.eex-group.com serves a rolling ~5-TRADING-DAY window and no history at
    # all, so this leg is a FORWARD-ONLY ACCUMULATOR (write_mode append, first-capture immutable)
    # while every futures_eod venue can be re-fetched -- the two cannot share a backfill answer, and
    # `backfillable` is a per-FAMILY flag. Second, the CEILING: max_lag_days=5 here is the source's
    # own unrecoverability horizon (the fifth missed daily run is data lost forever), not a
    # preference, and folding it into futures_eod would let one family's tightest-member arithmetic
    # decide when a permanently-lossy leg gets to page.
    ("silver_eex_freight", "eex_freight"),
    # --- Model output (generation-only; NOT a source-backfill DAG) --------
    ("silver_model_predictions", "model_output"),
    # --- Observability ledger (T2B; generation-only engine replay) --------
    # gold_pattern_records is produced by the pattern-records sweep (an engine replay over the mapped
    # catalog), NOT ingested from an external source -- so it has no source-backfill DAG and carries no
    # F082 batch/freshness alarm (its own missed-sweep / zero-rows alarms are the T2B plan sec 8 set,
    # separate from this estate). Grouped like model_output: generation-only.
    ("gold_pattern_records", "pattern_records"),
)

# Human-facing family labels for runbook/alarm descriptions.
FAMILY_LABELS: dict[str, str] = {
    "usda_esr": "USDA FAS Export Sales (ESR)",
    "usda_wasde": "USDA WASDE",
    "usda_psd": "USDA PSD",
    "usda_wap": "USDA World Ag Production (WAP)",
    "usda_nass": "USDA NASS (QuickStats / crop progress / citrus)",
    "usda_fgis": "USDA FGIS grain inspections",
    "weather": "Weather + climate (NASA POWER / CHIRPS / CPC-soil / MODIS / gold z-score)",
    "noaa_climate": "NOAA climate indices (IOD / ONI)",
    "mpoc": "MPOC Malaysian palm-oil council",
    "mpob": "MPOB Malaysian palm-oil board",
    "unica": "UNICA Brazil sugar/ethanol",
    "conab": "CONAB Brazil coffee",
    "minagro": "MINAGRO Ukraine grain/pulse/flour exports (State Customs)",
    # The label says AWS-ONLY out loud: an on-call reading a failure page for this family must know
    # that the source is unreachable from a laptop before spending an hour proving it.
    "moex_agro": "MOEX Russian grain indicative indices (ISS; AWS-reachable only)",
    # The label says UNRECOVERABLE out loud, for the same reason the moex label says AWS-ONLY: the
    # first thing an on-call must know here is that a missed day cannot be re-fetched, so the
    # response to a failure page is "restore the daily fire NOW", never "re-run the backfill".
    "eex_freight": "EEX dry-bulk freight settlements (forward-only ~5-day window; NO backfill)",
    "fnc_colombia": "FNC Colombia coffee",
    "sagis": "SAGIS South Africa grain",
    "fred": "FRED FX rates",
    "world_bank": "World Bank (food CPI / Pink Sheet)",
    "futures": "Exchange futures prices (yfinance)",
    "futures_eod": "Exchange futures EOD per delivery month (CZCE / JSE / CEPEA / Bursa / MIAX / "
                   "Euronext / DCE / Databento)",
    "cftc": "CFTC Commitments of Traders",
    "faostat": "FAOSTAT production",
    "ams": "USDA AMS cotton quality",
    # The label names the THREE legs out loud because they lag differently (+1/+2 days weekly,
    # ~36 days monthly, ~7 months on the annual Ukraine edition), so an on-call reading a stale
    # page must know which leg it is looking at before deciding anything is wrong.
    "ams_gtr": "USDA AMS Grain Transportation Report freight (barge / ocean weekly+monthly / "
               "Ukraine quarterly)",
    "icco": "ICCO cocoa",
    "model_output": "Model predictions (generation-only)",
    "pattern_records": "Pattern-records ledger (T2B; generation-only engine replay)",
    # D-EC DK-13. The label says DERIVED out loud: an on-call reading a stale-freshness page for this
    # family must know the fix is upstream (the three CBOT legs of silver_futures_eod did not land)
    # far more often than it is here -- there is no vendor to chase.
    "board_crush": "CBOT board crush (derived from silver_futures_eod; no external source)",
    "futures_spreads": "front-month spread pairs (derived from silver_futures_eod; no external source)",
}

# Interim freshness-SLA lag ceilings per cadence, used when the registry
# ``freshness_sla.max_lag_days`` is still null (all tables today -- OP-8 / AV-11
# per-source calibration is deferred). A weekly source is stale past ~2 cycles,
# a daily one past ~3 days, etc. The certificate emits FreshnessLagDays and the
# F082 alarm fires when it exceeds this ceiling (plus any publication_lag grace).
CADENCE_DEFAULT_LAG_DAYS: dict[str, int] = {
    "daily": 3,
    "weekly": 14,
    "monthly": 45,
    "annual": 400,
}
# Fallback when cadence is unrecorded (6 tables). Conservative monthly-ish.
_CADENCE_FALLBACK_LAG_DAYS = 45

# Freshness-audit corrections (freshness-poller lane, 2026-07-23). A registry ``max_lag_days`` value
# that the freshness audit found MASKED a stalled producer -- the emitted family ceiling (and the
# per-table alarm in silver_alarms.BURNED_TABLE_FRESHNESS) use the corrected value instead. Keyed by
# ``table_name``; applied in :func:`build_catalog` and only ever TIGHTENS (``min`` with the registry-
# derived lag), so it is a no-op the moment the registry baseline is regenerated with the real fix.
#   silver_nass_crop_progress: cadence=weekly but the registry carried max_lag_days=170 (~24 weeks),
#   which let the weekly crop-progress producer sit stale-green for 6-10 weeks. Corrected to the
#   weekly cadence default (14) -- this is what drops the usda_nass family ceiling 170 -> 14.
FRESHNESS_LAG_OVERRIDES: dict[str, int] = {
    "silver_nass_crop_progress": 14,
    # D-LD (2026-08-18, review wf_31e951c7): the WRITE-recency ceilings for three newly-carded
    # tables, pinned against a category error. Their numbers cards declared MEASURED
    # publication_lag_days (fgis 13, fnc 45) for the AS-OF guard -- the axis that stops a card
    # serving data the source had not yet published. effective_sla_lag_days adds that lag as
    # GRACE, which is right for content-lag semantics but WRONG for these alarms: FreshnessLagDays
    # measures S3 write recency, and the producers WRITE on their fire cadence regardless of how
    # far the content lags (fgis fires every Thursday; fnc weekly-class). Without these pins the
    # fgis ceiling widened 14 -> 27 and the fnc_colombia FAMILY ceiling silently DOUBLED 45 -> 90
    # (undisclosed side effect, caught by the review). The two numbers protect different things
    # and must not be summed.
    "silver_fgis": 14,
    "silver_fnc_colombia_monthly": 45,
    "silver_fnc_colombia_exports_port_type": 45,
    # D-LD TRANCHE 2 (2026-08-18): the SAME law, applied to the three Tranche-2 cards that declare a
    # NON-ZERO publication_lag_days. Each pin equals that table's own cadence default, i.e. it cancels
    # the grace and changes NOTHING else -- the entries exist to stop `effective_sla_lag_days` adding a
    # CONTENT lag to a WRITE-recency ceiling, never to arm a tighter alarm.
    # MEASURED, not asserted (build_catalog run before and after the cards landed):
    #   silver_sagis_weekly_deliveries -- the only one where the widening reached a FAMILY ceiling. The
    #     card declares +5d (the ratified exports-sibling lag) and the sagis family ceiling moved
    #     14 -> 19 the moment it did, because this table WAS the family minimum at lag 0. The producer
    #     fires cron(0 12 ? * FRI *) and writes weekly whatever the content lag, so 14 (weekly cadence
    #     default, ~2 cycles) is the honest write ceiling and the family is held where it was. The
    #     silver_sagis_weekly_exports sibling keeps its own 19 UNPINNED and is deliberately not touched
    #     here: tightening a ratified ceiling is a separate decision, and the family min is 14 either way.
    #   silver_food_cpi -- +195d (MEASURED against the WDI `lastupdated` release stamp) over an ANNUAL
    #     cadence would make the ceiling 595 days for a producer that fires MONTHLY, cron(0 16 8 * ? *),
    #     beside pink_sheet. The world_bank family min is pink_sheet's 85 either way, so this pin moves
    #     no family ceiling -- it keeps the per-table number honest for BURNED_TABLE_FRESHNESS and for
    #     the day this table becomes the family minimum.
    #   silver_mpoc_exports_by_country -- +60d over an ANNUAL cadence would make it 460 for a producer
    #     that fires monthly, cron(0 12 15 * ? *). Same shape, same reason; the mpoc family min stays 45.
    # NOT PINNED, and that is a measurement rather than an omission: silver_ams_cotton_quality,
    # silver_nass_annual and silver_fnc_colombia_area_department all carry publication_lag_days 0/null
    # (their vintage/ingest anchors ARE the publication event), so there is no grace to add and no
    # ceiling moves at all -- an entry for any of them would be a pin against nothing.
    "silver_sagis_weekly_deliveries": 14,
    "silver_food_cpi": 400,
    "silver_mpoc_exports_by_country": 400,
    # D-LD TRANCHE 3 (2026-08-19): the SAME law again, and this time it reached the family ceiling on
    # the FIRST of the three cards. MEASURED with build_catalog run before and after the cards landed:
    # the `unica` family ceiling moved 14 -> 28 the moment silver_unica_biweekly_season_history
    # declared publication_lag_days 14, because that table WAS the family minimum at lag 0.
    # THE WRITE CADENCE IS THE ANSWER AND IT IS ONE FACT FOR ALL THREE: every unica silver table is
    # produced by the SAME DAG, and that DAG fires cron(0 12 ? * WED *) -- WEEKLY -- rewriting the
    # canonical parquet with --force-overwrite on every fire whatever the content lag (canonical
    # objects last written 2026-08-18, with the newest bulletin inside them dated 2026-02-01: the
    # clearest possible demonstration that write recency and content recency are different axes here).
    # publication_lag_days guards the AS-OF axis; FreshnessLagDays measures S3 write recency; summing
    # them is the banked category error, so each pin below equals that table's own cadence default and
    # cancels the grace, changing nothing else.
    #   silver_unica_biweekly_season_history -- 28 -> 14 (weekly default). This is the pin that holds
    #     the family where it was.
    #   silver_unica_corn_ethanol -- 28 -> 14 (weekly default). Its PRE-card ceiling was 45, but only
    #     because its cadence was NULL (value_columns and grain were both empty, so _cadence had
    #     nothing to read) and effective_sla_lag_days fell through to the fallback. Carding it ends
    #     that state whether or not this entry exists, so the honest comparison is 28-unpinned against
    #     14-pinned, not against the old placeholder -- and 14 is what its weekly producer earns.
    #   silver_unica_monthly_ethanol_sales -- 90 -> 45 (MONTHLY default, not weekly). Deliberately NOT
    #     tightened to the 14 its weekly-firing producer would justify: this table's pre-card ceiling
    #     was already 45, the family minimum is 14 either way, and arming a tighter alarm is a separate
    #     decision from cancelling a grace (the food_cpi precedent directly above, which likewise pinned
    #     the cadence default rather than the fire cadence).
    # NOT PINNED, as a measurement rather than an omission: silver_unica_annual_state (400, uncarded)
    # and silver_unica_biweekly_release_series (45 fallback, REFUSED a card this wave -- see the
    # tranche header in configs/graphrag/numbers/tables.yaml) declare no publication_lag_days at all,
    # so there is no grace to cancel and an entry for either would be a pin against nothing.
    "silver_unica_biweekly_season_history": 14,
    "silver_unica_corn_ethanol": 14,
    "silver_unica_monthly_ethanol_sales": 45,
}


def family_of(table_name: str) -> str:
    """The orchestration family a table belongs to. Raises ``KeyError`` if unmapped.

    First-match wins over :data:`FAMILY_RULES` (ordered specific-before-general)."""
    for prefix, family in FAMILY_RULES:
        if table_name == prefix or table_name.startswith(prefix):
            return family
    raise KeyError(
        f"{table_name!r} maps to no DAG family. Add an explicit FAMILY_RULES entry "
        f"(dag_catalog.py) -- a new silver table must declare its orchestration family."
    )


def effective_sla_lag_days(contract: dict) -> tuple[int, str]:
    """Return ``(max_lag_days, basis)`` -- the interim freshness ceiling for a table.

    Precedence: an explicit registry ``freshness_sla.max_lag_days`` (none set today) >
    the cadence default (:data:`CADENCE_DEFAULT_LAG_DAYS`) > the monthly-ish fallback. A
    ``publication_lag_days`` (e.g. ESR=7) is added as grace so the alarm never fires on the
    expected publication delay."""
    fs = contract.get("freshness_sla") or {}
    grace = int(contract.get("publication_lag_days") or 0)
    explicit = fs.get("max_lag_days")
    if explicit is not None:
        return int(explicit) + grace, "registry.max_lag_days"
    cadence = fs.get("cadence")
    if cadence in CADENCE_DEFAULT_LAG_DAYS:
        return CADENCE_DEFAULT_LAG_DAYS[cadence] + grace, f"cadence_default:{cadence}"
    return _CADENCE_FALLBACK_LAG_DAYS + grace, "cadence_default:fallback"


@dataclass(frozen=True)
class DagFamily:
    """One orchestration family: the tables a single source DAG produces/schedules together."""

    key: str
    label: str
    tables: tuple[str, ...]
    owner: str                              # dominant registry owner across the family
    cadences: tuple[str, ...]               # sorted distinct freshness cadences in the family
    batch_tasks: tuple[str, ...]            # distinct producer batch-task entrypoints
    backfillable: bool                      # False for model_output (generation-only)
    max_sla_lag_days: int = 0               # tightest interim freshness ceiling in the family
    sla_basis: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "tables": list(self.tables),
            "owner": self.owner,
            "cadences": list(self.cadences),
            "batch_tasks": list(self.batch_tasks),
            "backfillable": self.backfillable,
            "max_sla_lag_days": self.max_sla_lag_days,
            "sla_basis": self.sla_basis,
        }


# Families that carry no source-backfill DAG (generation-only outputs).
_NON_BACKFILL_FAMILIES = frozenset({"model_output", "pattern_records",
                                    # D-EC DK-13: derived from a PUBLISHED silver table, so there is
                                    # no external source to backfill FROM -- recovery is re-running
                                    # the transform, not re-fetching a vendor.
                                    "board_crush",
                                    "futures_spreads",   # GN-2 W2.3: same derived-no-source shape
                                    # MINAGRO: FORWARD-ACCUMULATION, the Bursa shape. The ministry
                                    # edits ONE standing URL in place and keeps no archive, so the
                                    # only release that exists to fetch is the current one and a
                                    # missed week is unrecoverable. A source-backfill DAG here could
                                    # never fetch anything historical; recovery is re-parsing the
                                    # landed raw captures, which is a rebuild and not a backfill.
                                    #
                                    # RE-OPEN THIS THE DAY A SCHEDULE IS ARMED. The flag also
                                    # exempts the family from the F082 batch/freshness alarm
                                    # coverage lint (test_silver_alarms), and a missed week is
                                    # PRECISELY what a freshness alarm is for on a forward-only
                                    # source. Today nothing is scheduled, so an alarm would watch
                                    # nothing; the moment the weekly fire exists, this family needs
                                    # its alarm pair in the observability tfvars whether or not it
                                    # can ever be backfilled.
                                    "minagro",
                                    # EEX FREIGHT: the SAME forward-only shape, MEASURED rather than
                                    # inferred -- api.eex-group.com answers a request widened to
                                    # startDate=2025-01-01 with exactly five settlPx points (probe
                                    # 2026-08-20), so the only settlements that exist to fetch are
                                    # the last ~5 trading days and a day not captured is gone. A
                                    # source-backfill DAG here would have nothing to ask for;
                                    # recovery is re-parsing landed raw captures, i.e. a rebuild.
                                    #
                                    # NOTE the flag is doing DOUBLE duty today and only one half is
                                    # permanent. Permanent: no source backfill, ever. Temporary: it
                                    # also keeps the family out of the F082 alarm set while the
                                    # canonical prefix is still EMPTY (no batch task, no jobdef, no
                                    # schedule) -- the same empty-prefix paging hazard that put
                                    # moex_agro in silver_alarms.PRE_PUBLISH_FAMILIES, which
                                    # backfillable families need stated explicitly and this one gets
                                    # incidentally (the gold_pattern_records precedent named in that
                                    # module). RE-OPEN THE DAY THE DAILY FIRE IS ARMED: on a source
                                    # whose fifth missed run is unrecoverable, a freshness alarm is
                                    # the single most load-bearing alarm in the estate, and this flag
                                    # currently suppresses it. Arming the schedule without giving
                                    # this family its alarm pair is the failure this comment exists
                                    # to prevent.
                                    "eex_freight"})


def build_catalog(registry: Optional[SilverRegistry] = None) -> dict[str, DagFamily]:
    """Group every registry table into its DAG family. Deterministic; raises on an unmapped table.

    Returns ``{family_key: DagFamily}`` ordered by family key. Each family's ``max_sla_lag_days`` is
    the *tightest* (minimum) interim ceiling across its tables (the family is stale as soon as its
    freshest-cadence member is)."""
    reg = registry or load_registry()
    grouped: dict[str, list[dict]] = {}
    for name in reg.names():
        grouped.setdefault(family_of(name), []).append(reg.table(name))

    out: dict[str, DagFamily] = {}
    for family in sorted(grouped):
        contracts = sorted(grouped[family], key=lambda c: c["table_name"])
        tables = tuple(c["table_name"] for c in contracts)
        owners = [c.get("owner") for c in contracts if c.get("owner")]
        owner = _dominant(owners)
        cadences = tuple(sorted({
            (c.get("freshness_sla") or {}).get("cadence")
            for c in contracts
            if (c.get("freshness_sla") or {}).get("cadence")
        }))
        batch_tasks = tuple(sorted({
            (c.get("producer") or {}).get("batch_task")
            for c in contracts
            if (c.get("producer") or {}).get("batch_task")
        }))
        lags = []
        for c in contracts:
            lag, basis = effective_sla_lag_days(c)
            override = FRESHNESS_LAG_OVERRIDES.get(c["table_name"])
            if override is not None and override < lag:
                lag, basis = override, f"audit_override(was {lag},{basis})"
            lags.append((lag, basis))
        tightest = min(lags, key=lambda t: t[0]) if lags else (_CADENCE_FALLBACK_LAG_DAYS, "none")
        out[family] = DagFamily(
            key=family,
            label=FAMILY_LABELS.get(family, family),
            tables=tables,
            owner=owner,
            cadences=cadences,
            batch_tasks=batch_tasks,
            backfillable=family not in _NON_BACKFILL_FAMILIES,
            max_sla_lag_days=tightest[0],
            sla_basis=tightest[1],
        )
    return out


def _dominant(values: list[str]) -> str:
    """Most frequent value (ties broken alphabetically); '' for an empty list."""
    if not values:
        return ""
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda k: (-counts[k], k))[0]
