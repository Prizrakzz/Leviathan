"""Silver transform for USDA FAS Export Sales Reporting (ESR) data.

Converts a bronze ESR DataFrame into a silver DataFrame.

Design notes
------------
* **Wide format** — one row per (country_code, week_ending_date).  Quantity
  columns appear side-by-side rather than melted into variable/value pairs.
  This makes feature engineering (pace ratios, z-scores) straightforward
  without a pivot step.

* **1000 MT units** — all quantity columns are divided by 1,000 so that values
  are expressed in *thousands of metric tonnes* (the USDA WASDE standard).
  Column names carry the ``_1000mt`` suffix to make the unit explicit.
  ``unit_id=1`` (raw metric tonnes) is the unit of 31 of the source's 44
  commodity codes; the other 13 publish bales or piece counts and are refused in
  writing by :data:`_NON_MASS_UNIT_CODES`.  If a code outside BOTH sets arrives
  with an unrecognised ``unit_id`` the transform raises ``ValueError`` rather
  than silently producing wrong values — unknown-unit drift stays fatal.

* **market_year parameter** — the ESR API response does not include the
  ``marketYear`` field in historical records.  The caller (backfill script or
  Airflow task) passes ``market_year`` directly because it is encoded in the
  bronze S3 partition path.

* **Immutable snapshots** — ``as_of_date`` is preserved from the bronze row so
  the silver layer retains full point-in-time history for backtesting.

SILVER-F030 semantic ADR (frozen)
---------------------------------
* ``changes_1000mt`` is a DEPRECATED, nullable column. A null bronze ``changes``
  (revision absent in a historical FAS record) propagates to a null
  ``changes_1000mt`` — it is NEVER synthesized as 0.0 (INV-4).
* **The five BF-W2 net-commitment columns are EMITTED** (2026-09-04):
  ``accumulated_exports_1000mt``, ``current_my_net_sales_1000mt``,
  ``current_my_total_commitment_1000mt``, ``next_my_outstanding_sales_1000mt``,
  ``next_my_net_sales_1000mt`` -- the ADR's frozen ``target_additive_schema_bf_w2``
  names, ``double``, nullable, FAS value / 1000. Three properties are load-bearing:

  1. They are emitted UNCONDITIONALLY. A bronze frame written before the promotion
     has none of the five; the transform creates them as NaN rather than omitting
     them, so EVERY returned frame carries the same 18 columns. Omitting them
     would make the parquet schema depend on the vintage, and the value census
     IGNORES files where a column is absent (``value_census.py`` keeps only
     ``s is not None``) -- a column missing from old files measures 1.000 non-null
     over the sample, i.e. a gate that passes because it is looking at nothing.
  2. They sit at the very END of the column list, AFTER ``source`` -- not grouped
     with the other ``*_1000mt`` columns. ``catalog.is_schema_widen`` admits ONLY a
     pure TRAILING append (measured: tail -> True, inserted at position 9 -> False),
     and that self-heal is what lets the compact producer repair
     already-registered partition StorageDescriptors after the Glue
     ``ADD COLUMNS``. Mid-list, every partition fails closed instead.
  3. They are float64, matching the Glue ``double`` the ADR declares. A parquet
     FLOAT under a ``double`` catalog is the ``silver_food_cpi`` HIVE_BAD_DATA
     class. The incumbent four stay float32 (the SILVER-F031 widen is separate).

  They are NULL for every vintage whose bronze predates the promotion, and they
  stay UNGOVERNED (out of ``value_columns``) until two measured vintages exist:
  at the 0.5 floor, one populated file of three sampled reads 0.333
  (``nonnull_below_floor``) and none populated reads ``all_nan``, which is the
  floor-INDEPENDENT rule that cost this family its 2026-08-27 and 2026-09-03
  promotes on ``changes_1000mt``.
* **Ending-year convention** — ``market_year`` is the FAS *start* year (e.g. 2024
  = the 2024/25 season). It is stored verbatim; the ending-year label used by the
  numbers layer is ``market_year + 1`` (``tables.yaml`` ``period_offset: +1``). A
  not-yet-started next marketing year is never fabricated from an empty endpoint.
* **Slug-coverage boundary** — the ESR commodity set includes USDA groupings
  (``all_wheat`` 107, ``grain_sorghum`` 701, ``white_wheat`` 104, and after the
  2026-08-20 widening ``all_rice`` 1505 and the rice/cotton class grains) that are
  NOT Leviathan contract slugs; the ``esr_exports`` cascade leg fires only for the
  contract-slug commodities. The transform maps every observed mass code (groupings
  included) so the canonical table stays source-faithful; consumer routing enforces
  the boundary.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Mapping from ESR commodity_code to the canonical Leviathan commodity slug.
# Codes without a direct futures contract (104, 107, 701) use descriptive
# strings so that Athena queries remain self-documenting.
#
# D-EC (2026-08-20) — THE 44-CODE WIDENING.  jobs/ingest/fetch_usda_esr.py now
# requests the FULL measured source universe (44 codes, GET /api/esr/commodities)
# instead of the legacy 10.  THIS MAP IS ON THE CRITICAL PATH OF THAT CHANGE:
# ``silver_esr_compact`` partitions by the NAME this map returns (the batch task
# groups on ``commodity_name``), so an unmapped code does not merely read
# "unknown" in a column — every unmapped code COLLAPSES INTO ONE
# ``commodity=unknown`` partition object.  All 21 new mass-unit (unit_id=1) codes
# are therefore mapped below before the next weekly fire.  The remaining 13 codes
# are non-mass and are refused in writing in :data:`_NON_MASS_UNIT_CODES`; they
# never reach this map because their rows are skipped first.
#
# NAMING LAW.  Where the estate already spells a slug for the same commodity that
# spelling is REUSED EXACTLY — cross-table joins (silver_psd ↔ silver_esr) key on
# it, so a variant spelling would silently un-join a family.  The authorities
# checked, code by code, are ``_PSD_COMMODITY_TO_SLUGS`` in
# transforms/bronze_to_silver/usda_psd.py, configs/graphrag/commodity_hierarchy.yaml
# and configs/graphrag/entity_vocabulary.yaml.  A slug is COINED only where all
# three hold nothing, and then it follows this map's own idiom (a descriptive
# snake_case publication grain, as ``white_wheat``/``all_wheat`` already are).
# Each new entry carries its provenance so the next reader does not have to
# re-derive it.
_COMMODITY_CODE_TO_NAME: dict[int, str] = {
    # ---- the legacy ten (UNCHANGED, byte for byte) ------------------------
    101: "hard_red_winter_wheat_kcbt",
    102: "soft_red_winter_wheat_cbot",
    103: "hard_red_spring_wheat_mgex",
    104: "white_wheat",
    107: "all_wheat",
    401: "corn_cbot",
    701: "grain_sorghum",
    801: "soybeans_cbot",
    901: "soybean_meal_cbot",
    902: "soybean_oil_cbot",
    # ---- D-EC 2026-08-20: the wheat classes and wheat products ------------
    # No estate slug exists for any of these three: `durum` is DELIBERATELY not a
    # `minor_cereals` member (commodity_hierarchy.yaml:164 — it is a wheat CLASS
    # riding the wheat classes' extra_terms) and NASS annual refuses it for want
    # of a contract node, so nothing anywhere spells it.  Coined on the
    # `white_wheat` pattern: the USDA class name, snake_case.
    105: "durum_wheat",        # COINED — no estate slug (white_wheat idiom)
    106: "mixed_wheat",        # COINED — NOT `mixed_grain`, which is PSD 459900,
                               #          a different sheet (all coarse grains)
    201: "wheat_products",     # COINED — flour/semolina etc, a processed grain
    # ---- D-EC 2026-08-20: the small grains --------------------------------
    301: "barley",             # REUSED — usda_psd 430000 + a declared context commodity
    501: "rye",                # REUSED — usda_psd 451000 (publication grain under `minor_cereals`)
    601: "oats",               # REUSED — usda_psd 452000 (same)
    # ---- D-EC 2026-08-20: the minor oilseeds ------------------------------
    # `flax`/`flaxseed`/`linseed` are ALIASES of the `minor_oilseeds` vocab node
    # (entity_vocabulary.yaml:315), which is a family gloss, not a publication
    # grain — and the seed and the oil are two separate ESR series that would
    # collide in one partition under one name.  So the numbers key stays per
    # sheet, exactly as PSD keeps `rye`/`oats` per sheet under `minor_cereals`.
    1001: "flaxseed",          # COINED — vocab has the WORD, no slug
    1101: "linseed_oil",       # COINED — same
    1110: "sunflower_oil",     # REUSED — usda_psd 4236000 + context commodity + vocab node
    # ---- D-EC 2026-08-20: the cottonseed crush complex --------------------
    # The three mass codes of the cotton complex.  The five LINT codes
    # (1301, 1401-1404) are running bales and are skipped, not mapped.
    1201: "cottonseed",        # REUSED — usda_psd 2223000 + D15 tier-1 context commodity
    1202: "cottonseed_meal",   # REUSED — usda_psd 813300
    1203: "cottonseed_oil",    # REUSED — usda_psd 4233000
    # ---- D-EC 2026-08-20: the rice complex --------------------------------
    # SEVEN codes, not eight: there is no 1500 in the source universe.  1498 is
    # long-grain ROUGH rice, which is exactly what the CBOT Rough Rice contract
    # trades, so it takes the CONTRACT slug on this map's own rule ("a direct
    # futures contract -> the contract slug") and finally gives `rough_rice_cbot`
    # an esr_exports lane.  It is the ONLY rice code that may hold that slug: the
    # other six are different milling/grain classes and one aggregate, and
    # sharing the name would merge several balance-of-trade series into one
    # partition file.  `all_rice` follows the `all_wheat` grouping idiom.
    1498: "rough_rice_cbot",           # REUSED — the CONTRACT slug (LG rough == the deliverable)
    1499: "medium_short_rough_rice",   # COINED
    1501: "long_grain_brown_rice",     # COINED
    1502: "medium_short_brown_rice",   # COINED
    1503: "long_grain_milled_rice",    # COINED
    1504: "medium_short_milled_rice",  # COINED
    1505: "all_rice",                  # COINED — the USDA grouping (all_wheat idiom)
    # ---- D-EC 2026-08-20: the meat demand layer ---------------------------
    # The two codes the projection census named as the LIVESTOCK layer's first
    # landing.  ESR publishes muscle CUTS while PSD publishes the carcass-weight
    # family sheet; that is a grain difference within one commodity, not a
    # different commodity, and joining them is the whole point of reusing the
    # name.  Quote the ESR figure as export commitments of muscle cuts.
    1701: "cattle_beef",       # REUSED — usda_psd 111000 (meat, beef and veal)
    1702: "hogs",              # REUSED — usda_psd 113000 (meat, swine)
}

# The 13 codes ESR publishes in a NON-MASS unit — the WRITTEN SKIP (D-EC,
# 2026-08-20).  Measured with the estate's own FAS_API_KEY alongside the 44-code
# universe census: the cotton LINT codes report unit_id=2 (running bales) and the
# hide/skin codes report unit_id=3/4/5 (piece counts).
#
# THE PARKED DECISION, stated rather than left as an absence: every quantity
# column in this table is named ``*_1000mt`` and CANNOT REPRESENT BALES OR
# PIECES.  Emitting them under a tonnage name would be a units lie no downstream
# consumer could detect (the same refusal usda_psd.py makes for its two
# animal-numbers head-count codes).  A native-unit column pair is a SCHEMA
# decision and is PENDING THE OWNER'S WORD; meanwhile raw and bronze accumulate
# these codes every Thursday, so nothing is lost and the decision can be taken
# later against real history.
#
# Until then these rows are DROPPED WITH A LOG LINE, not with an exception: the
# fetcher requests all 44 codes every week, so raising here would error-log 13
# codes on the live weekly chain forever.  The skip is deliberately narrow —
# ANY OTHER unrecognised unit_id still raises (unknown-unit drift is fatal), and
# a code listed here arriving as unit_id=1 ALSO raises, because that means USDA
# re-based the series onto mass and this refusal has silently stopped holding.
_NON_MASS_UNIT_CODES: dict[int, str] = {
    # cotton LINT — unit_id=2, RUNNING BALES
    1301: "unit_id=2 running bales (Cotton- Am Pima)",
    1401: 'unit_id=2 running bales (Cotton- Upland 1 1/16" & over)',
    1402: 'unit_id=2 running bales (Cotton- Upland 1"-1 1/16" & over)',
    1403: 'unit_id=2 running bales (Cotton- Upland under 1")',
    1404: "unit_id=2 running bales (All Upland Cotton)",
    # hides, skins and wet blues — unit_id=3/4/5, PIECE COUNTS
    1601: "unit_id=3/4/5 piece count (Cattle Hides - Whole - Excluding Wet Blues)",
    1602: "unit_id=3/4/5 piece count (Calf Skins - Whole - Excluding Wet Blues)",
    1603: "unit_id=3/4/5 piece count (Kip Skins - Whole - Excluding Wet Blues)",
    1604: "unit_id=3/4/5 piece count (Cattle Hides-Cut into Croupons, etc-excl Wet Blues)",
    1605: "unit_id=3/4/5 piece count (Cattle Hides and Skins-other-excluding Wet Blues)",
    1606: "unit_id=3/4/5 piece count (Cattle Wet Blues-Unsplit (Whole or Sided))",
    1607: "unit_id=3/4/5 piece count (Cattle Wet Blues-Grain Splits (Whole or Sided))",
    1608: "unit_id=3/4/5 piece count (Cattle Wet Blues-Splits-Excluding Grain Splits)",
}

# unit_id → multiplication factor to convert to 1000 MT.
# unit_id=1 is raw metric tonnes (MT); dividing by 1,000 gives 1000 MT.
# Every code this transform KEEPS uses unit_id=1 (measured across the 44-code
# universe, 2026-08-20); the non-mass codes are removed before this map is read.
_UNIT_TO_1000MT_FACTOR: dict[int, float] = {
    1: 0.001,  # MT → 1000 MT
}

# Quantity columns present in actual bronze ESR data (probe-verified 2026-05-24).
# These are the only fields the FAS API returns for the allCountries endpoint.
_QUANTITY_COLS: list[str] = [
    "outstanding_sales",
    "weekly_exports",
    "gross_new_sales",
    "changes",
]

# SILVER-F030 BF-W2 additive set (2026-09-04). SEPARATE from _QUANTITY_COLS on
# purpose: the same /1000 derivation, but a different ORDER (these five land at
# the TAIL of the silver column list, after `source`) and a different width
# (float64 -- the ADR's Glue `double`). See the module docstring for why both
# facts are load-bearing rather than stylistic. Order is the ADR's own.
_ADDITIVE_QUANTITY_COLS: list[str] = [
    "accumulated_exports",
    "current_my_net_sales",
    "current_my_total_commitment",
    "next_my_outstanding_sales",
    "next_my_net_sales",
]

# Columns that must be present in the bronze DataFrame.
_REQUIRED_COLS: frozenset[str] = frozenset({
    "commodity_code",
    "country_code",
    "week_ending_date",
    "unit_id",
    "as_of_date",
    "ingest_date",
    "source",
})


def transform_esr_bronze_to_silver(
    df: pd.DataFrame,
    market_year: int,
) -> pd.DataFrame:
    """Clean and normalise a single bronze ESR Parquet into silver.

    Args:
        df:          Bronze ESR DataFrame as loaded from Parquet.
        market_year: Marketing year start (e.g. 2024 = Sep 2024 – Aug 2025 for
                     corn).  Passed explicitly because the ESR API does not
                     include ``marketYear`` in its response payload.

    Returns:
        Wide-format silver DataFrame with all quantity columns expressed in
        1000 MT.  Row count is preserved except for rows where
        ``week_ending_date`` is null (dropped with a warning) and rows whose
        ``commodity_code`` is a written-down non-mass code (dropped with an info
        line).  A frame consisting ENTIRELY of non-mass rows — which is what a
        per-code bronze object for one of those 13 codes is — returns an EMPTY
        silver frame with the full column set; the batch producer skips empty
        results, so a skipped code contributes no partition and no error.

    Raises:
        ValueError: If required columns are absent from *df*; if an unrecognised
                    ``unit_id`` value is encountered on a KEPT row (which would
                    produce silently wrong unit conversions); or if a code listed
                    in :data:`_NON_MASS_UNIT_CODES` arrives with ``unit_id=1``
                    (source-universe drift — the written refusal has stopped
                    holding and must be re-decided, not silently re-applied).
    """
    # --- Validate required columns ---
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"ESR bronze DataFrame is missing required columns: {missing}. "
            f"Got: {list(df.columns)}"
        )

    df = df.copy()

    # --- Written skip: the non-mass codes (bales / piece counts) ---
    # bronze commodity_code/unit_id are NULLABLE Int16, so both masks are forced
    # to plain numpy bool: a masked array carrying pd.NA cannot index a frame.
    non_mass = df["commodity_code"].isin(_NON_MASS_UNIT_CODES).fillna(False).to_numpy(dtype=bool)
    if non_mass.any():
        # Universe drift FIRST: a written-off code arriving as metric tonnes means
        # the source re-based the series and the refusal below no longer describes
        # reality.  Raise rather than skip data that has become representable.
        is_mass_unit = (df["unit_id"] == 1).fillna(False).to_numpy(dtype=bool)
        drifted = sorted(
            {int(c) for c in df.loc[non_mass & is_mass_unit, "commodity_code"].dropna().unique()}
        )
        if drifted:
            raise ValueError(
                f"ESR bronze commodity_code(s) {drifted} arrived with unit_id=1 (metric tonnes) "
                "but are recorded in _NON_MASS_UNIT_CODES as bales/piece counts. The source "
                "universe has drifted: re-measure GET /api/esr/commodities, then either map the "
                "code(s) in _COMMODITY_CODE_TO_NAME or re-state the refusal -- do not skip a code "
                "whose rows this schema can now represent."
            )
        for code in sorted({int(c) for c in df.loc[non_mass, "commodity_code"].dropna().unique()}):
            logger.info(
                "ESR silver transform: SKIPPING commodity_code=%d (%d row(s)) -- %s; "
                "*_1000mt cannot represent it and the native-unit column is a pending schema "
                "decision (raw + bronze still accumulate it)",
                code,
                int((df["commodity_code"] == code).sum()),
                _NON_MASS_UNIT_CODES[code],
            )
        df = df.loc[~non_mass].reset_index(drop=True)

    # --- Validate unit_ids (on the KEPT rows only) ---
    unknown_units = set(df["unit_id"].dropna().unique()) - set(_UNIT_TO_1000MT_FACTOR)
    if unknown_units:
        raise ValueError(
            f"ESR bronze contains unrecognised unit_id value(s): {unknown_units}. "
            "Update _UNIT_TO_1000MT_FACTOR before proceeding."
        )

    # --- Drop rows with null week_ending_date ---
    null_dates = df["week_ending_date"].isna().sum()
    if null_dates:
        logger.warning(
            "market_year=%d: dropping %d row(s) with null week_ending_date",
            market_year,
            null_dates,
        )
        df = df.dropna(subset=["week_ending_date"]).reset_index(drop=True)

    # --- Add derived columns ---
    df["commodity_name"] = (
        df["commodity_code"].map(_COMMODITY_CODE_TO_NAME).fillna("unknown")
    )
    df["market_year"] = pd.array([market_year] * len(df), dtype="Int16")

    # --- Unit conversion: MT → 1000 MT ---
    factor_series = df["unit_id"].map(_UNIT_TO_1000MT_FACTOR)

    for col in _QUANTITY_COLS:
        if col in df.columns:
            df[f"{col}_1000mt"] = (df[col] * factor_series).astype("float32")
            df = df.drop(columns=[col])

    # The BF-W2 five, UNCONDITIONALLY (docstring point 1): a bronze frame written
    # before the promotion carries none of them, and an ABSENT column is invisible
    # to the value census, so the column is materialised as NaN first and then
    # converted. NaN * 0.001 = NaN, so a null bronze value propagates to a null
    # silver value with no special case -- the same mechanism `changes` uses.
    for col in _ADDITIVE_QUANTITY_COLS:
        if col not in df.columns:
            df[col] = float("nan")
        df[f"{col}_1000mt"] = (df[col] * factor_series).astype("float64")
        df = df.drop(columns=[col])

    # --- Rename unit_id to source_unit_id for audit clarity ---
    df = df.rename(columns={"unit_id": "source_unit_id"})

    # --- Final column order ---
    base_cols = [
        "commodity_code",
        "commodity_name",
        "market_year",
        "country_code",
        "week_ending_date",
    ]
    quantity_cols = [f"{c}_1000mt" for c in _QUANTITY_COLS if f"{c}_1000mt" in df.columns]
    meta_cols = ["source_unit_id", "as_of_date", "ingest_date", "source"]
    # TAIL placement (docstring point 2): the five come after `source`, never
    # inside the quantity block. is_schema_widen admits only a trailing append,
    # and a fixed emitted list also makes the producer's pd.concat union
    # order-stable regardless of which S3 read finishes first.
    additive_cols = [f"{c}_1000mt" for c in _ADDITIVE_QUANTITY_COLS]

    ordered = base_cols + quantity_cols + meta_cols + additive_cols
    df = df[[c for c in ordered if c in df.columns]]

    logger.info(
        "ESR silver transform: commodity_code=%s market_year=%d rows=%d",
        df["commodity_code"].iloc[0] if len(df) else "?",
        market_year,
        len(df),
    )

    return df
