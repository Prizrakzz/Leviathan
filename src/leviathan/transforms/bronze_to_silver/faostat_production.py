"""FAOSTAT bronze -> canonical ``silver_production`` transform (SILVER-F022).

``silver_production`` (the FAOSTAT/PSD production spine feeding the training LABEL + 4 faostat
families) is a projected table resolved at ``silver/production/commodity=<c>/year=<y>/`` with the
12-column contract pinned by the SILVER-F010 registry
(``configs/silver/tables/silver_production.yaml``):

    country, country_key, metric, unit, value, flag, is_official, note, source, dataset,
    ingest_date, source_file_name

The pre-F022 producer emitted a DIFFERENT shape (``variable`` instead of ``metric``; a single
``country`` holding the governed KEY with no display column; no ``note`` / ``dataset`` /
``source_file_name``) and wrote it beneath ``silver/production/source=faostat/`` -- a prefix the
canonical projection does NOT resolve, so the objects were invisible to the served table. This
transform:

  * preserves the DISPLAY country and derives the governed ``country_key`` (was collapsed to one
    column holding only the key);
  * renames ``variable`` -> ``metric`` via an explicit element map (no silent metric invention);
  * retains provenance (``note``, ``dataset``, ``source_file_name``);
  * resolves only logically-exact duplicates automatically and FAILS on a conflicting natural-key
    value (never a silent last-wins);
  * derives ``is_official`` from the release's OWN flag legend (:data:`FLAG_SEMANTICS`) and refuses
    any flag the legend does not carry (fail-closed on a scheme change, FAO-6);
  * emits exactly the 12 canonical physical columns -- ``commodity`` and ``year`` are the projected
    partition keys carried on the S3 path, never in the parquet body (INV-2 exact writer schema).

The batch/Glue writer enforces the INV-2 arrow schema from the registry contract, hard-guards the
canonical ``silver/production/commodity=/year=/`` layout (a ``source=faostat`` key is refused), and
routes through the shadow-first publisher.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# element (FAOSTAT) -> governed metric name (the explicit, validated variable->metric map).
#
# KEYS ARE THE LEGEND'S OWN STRINGS, byte-for-byte from the QCL ZIP's
# ``Production_Crops_Livestock_E_Elements.csv`` -- ten names across twenty element codes, of which
# these eight carry rows (the other two are refused in writing at
# ``raw_to_bronze.faostat_qcl._REFUSED_LEGEND_ELEMENTS``). Resolution is CASE-INSENSITIVE via
# :data:`_ELEMENT_LOOKUP`; see the note there for why the old ``str.capitalize()`` fold had to go.
#
# VALUES ARE GOVERNED NAMES, NOT FAO'S. Unlike silver_psd (whose card must spell USDA's own labels
# byte-for-byte), this surface has always renamed -- ``Area harvested`` -> ``area_harvested`` -- so
# the livestock five are named for what a reader of a citation needs to understand, and two of them
# are named DEFENSIVELY:
#
#   * ``Stocks`` -> ``live_animals``, NOT ``stocks``. In this estate ``stocks`` means balance-sheet
#     ENDING STOCKS in tonnes (silver_psd carries exactly that for these same slugs). A metric
#     literally named ``stocks`` on the production surface, holding head of cattle, would be read as
#     ending stocks by every consumer that has ever read a PSD number, and the row's own unit is the
#     only thing that would have said otherwise. The rename is the fence.
#   * ``Producing Animals/Slaughtered`` -> ``animals_producing_or_slaughtered``. FAO's string is
#     genuinely DUAL (the same element code is slaughtered head on a meat item and producing head on
#     an output item) and the honest governed name carries the ambiguity forward instead of
#     resolving it wrongly in one direction. ``Yield/Carcass Weight`` -> ``yield_per_animal`` for the
#     same reason: it is milk kg per milk-animal, carcass kg per slaughtered animal, and egg grammes
#     per bird, and "yield per animal" is the one reading true of all three.
ELEMENT_TO_METRIC = {
    # ── the crop three (pre-Lane-5, unchanged; the only elements the 43 crop items carry) ──────────
    "Area harvested": "area_harvested",
    "Production": "production_quantity",
    "Yield": "yield",
    # ── the livestock five (FAO-2, Lane 5) ────────────────────────────────────────────────────────
    "Stocks": "live_animals",
    "Milk Animals": "milk_animals",
    "Laying": "laying_birds",
    "Producing Animals/Slaughtered": "animals_producing_or_slaughtered",
    "Yield/Carcass Weight": "yield_per_animal",
}

# Case-insensitive element resolution. THIS REPLACES ``df["element"].str.capitalize()``, and the
# replacement is a correctness fix, not a tidy-up: ``str.capitalize()`` lower-cases everything after
# the first character, so it maps the release's own
#
#     "Producing Animals/Slaughtered" -> "Producing animals/slaughtered"
#     "Yield/Carcass Weight"          -> "Yield/carcass weight"
#     "Milk Animals"                  -> "Milk animals"
#
# -- three of the five livestock elements silently OFF the map above, i.e. three of five livestock
# element families dropped at ``df[df["element"].isin(ELEMENT_TO_METRIC)]`` with no error and no
# warning. It was invisible for the crop half only because all three crop element strings happen to
# be capitalize-STABLE ("Area harvested", "Production", "Yield"), which is exactly the coincidence
# that let a lossy fold sit in a validated map. Crop behaviour is byte-identical under this lookup
# (pinned both directions in tests/unit/test_transforms_faostat_silver.py).
_ELEMENT_LOOKUP: dict[str, str] = {k.strip().lower(): k for k in ELEMENT_TO_METRIC}

# ── THE UNIT FENCE (FAO-2 (c)) ─────────────────────────────────────────────────────────────────────
# ``unit`` is a free string on this table and the silver contract needs no schema change to carry
# ``An`` / ``1000 An`` / ``kg/An`` beside ``t`` and ``ha``. That freedom is precisely why the fence
# has to be explicit: nothing structural stops a head count from being written under a metric a
# consumer sums with tonnes.
#
# Governed (metric -> the units it may carry), MEASURED over all 4,209,110 rows of the tracked
# 2026-05-11 ZIP and banked at ``data/dec_p0/faostat_livestock_census.json``. Fail-closed in the
# ``FLAG_SEMANTICS`` posture: an unlisted (metric, unit) pair RAISES rather than publishing a number
# whose unit nobody has read.
METRIC_UNITS: dict[str, frozenset[str]] = {
    "area_harvested":                   frozenset({"ha"}),
    "production_quantity":              frozenset({"t"}),
    "yield":                            frozenset({"kg/ha"}),
    "live_animals":                     frozenset({"An", "1000 An"}),
    "milk_animals":                     frozenset({"An"}),
    "laying_birds":                     frozenset({"1000 An"}),
    "animals_producing_or_slaughtered": frozenset({"An", "1000 An"}),
    "yield_per_animal":                 frozenset({"kg/An", "g/An"}),
}

# THREE UNITS THE FILE CARRIES AND THIS MAP DELIBERATELY REFUSES, each measured and each a real
# number this fence stops rather than a hypothetical:
#
#   * ``production_quantity`` in ``1000 No`` (18,208 rows) and ``yield`` in ``No/An`` (16,761) --
#     both belong to the two EGG items alone (`Hen eggs in shell, fresh`; `Eggs from other birds in
#     shell, fresh, n.e.c.`), and both are parked at the item map. A thousand-eggs count admitted
#     under ``production_quantity [t]`` is a tonnage lie; eggs-per-bird admitted under
#     ``yield [kg/ha]`` is a units-category lie.
#   * ``live_animals`` in ``No`` (9,194 rows) -- a third unit on a metric that already carries two,
#     and no item Lane 5 admits uses it. Left out so a future admission fails LOUDLY here instead of
#     landing a third scale on a metric whose cross-slug comparison is already the card's headline
#     warning.
_REFUSED_UNITS: dict[tuple[str, str], str] = {
    ("production_quantity", "1000 No"): "egg items only (18,208 rows); a count, not a mass",
    ("yield", "No/An"):                 "egg items only (16,761 rows); eggs per bird, not kg/ha",
    ("live_animals", "No"):             "9,194 rows on items Lane 5 does not admit; a third scale",
}

# ── NARRATION CLASSES (FAO-2 (c)) ──────────────────────────────────────────────────────────────────
# What a citation may and may not do with a metric, declared once and consumed by the card lint so
# the prose fence and the code fence cannot drift apart.
#
# HEAD COUNTS MUST NEVER SUM WITH TONNES, and on THIS table the two now live side by side under one
# physical schema for the first time. The estate has met the hazard before from the other side:
# silver_psd REFUSES PSD codes 11000 / 13000 ("Animal Numbers, Cattle" 34,515 rows; "Animal Numbers,
# Swine" 23,991) with the words "a head count has no home in an all-tonnes schema ... Reopen by
# giving the schema a head-count column pair, not by adding a factor". silver_production's free-text
# ``unit`` column IS that home -- so this lane serves exactly the axis PSD declined, and it carries
# the obligation that came with the decline.
HEAD_COUNT_METRICS = frozenset({
    "live_animals", "milk_animals", "laying_birds", "animals_producing_or_slaughtered",
})
TONNAGE_METRICS = frozenset({"production_quantity"})
PER_ANIMAL_RATE_METRICS = frozenset({"yield_per_animal"})

# THE CROSS-SLUG SCALE TRAP, measured, and the single most citable fact on the livestock card:
# ``live_animals`` carries ``An`` for cattle_beef (13,831 rows) and hogs (12,824) but ``1000 An`` for
# broilers_poultry (13,932). A cross-slug comparison or sum that reads the number and not the row's
# own ``unit`` is wrong by exactly 1000x. This is the ``Cows In Milk`` disposition applied one level
# up: the hazard is CARRIED honestly on a per-row unit column, and the card is required to say so.
LIVESTOCK_METRICS = frozenset(HEAD_COUNT_METRICS | PER_ANIMAL_RATE_METRICS)

# The crop/livestock partition of ``configs/sources/faostat_item_map.yaml``'s key set. It lives in
# CODE, not in the map, for the reason the map's own header gives: that file IS the ingested universe
# and its flat ``slug: item`` shape is load-bearing (``run_faostat_backfill.ITEM_MAP`` reads it and
# ``--fao_item_name`` is a single scalar Glue argument), so a nested grouping key would break the
# runner. The two card fences read this constant: silver_production's ``commodity_values`` is the
# CROP half and silver_production_livestock's is this half, disjoint and together exactly the map.
FAOSTAT_LIVESTOCK_SLUGS = frozenset({"cattle_beef", "hogs", "broilers_poultry", "milk_fluid"})

# The 12 canonical physical columns, in registry order. ``commodity`` / ``year`` are partition keys
# (path-carried, NOT in the parquet body). This is the exact INV-2 writer column set for the body.
CANONICAL_PHYSICAL_COLUMNS = [
    "country",
    "country_key",
    "metric",
    "unit",
    "value",
    "flag",
    "is_official",
    "note",
    "source",
    "dataset",
    "ingest_date",
    "source_file_name",
]

SOURCE = "faostat"
DEFAULT_DATASET = "QCL"  # FAOSTAT Production_Crops_Livestock (QCL); overridden by a bronze `dataset`.

# ── FAOSTAT observation-status flags (FAO-6) ───────────────────────────────────────────────────────
# The descriptions are VERBATIM from the release's own legend, ``Production_Crops_Livestock_E_Flags.csv``,
# which ships INSIDE the same QCL ZIP this transform's bronze is cut from -- the legend and the data are
# one artefact, so the scheme can never be read from a stale doc.
#
# THIS REPLACES THE PRE-2022 SCHEME (``{"E","F","Fc","Im","*","A"}`` read as NON-official). FAOSTAT
# switched legends and the estate did not: MEASURED on the 2026-05-11 raw ZIP, all 4,209,110 rows carry
# exactly {A, E, X, I, M} and ZERO carry F / Fc / Im / ``*`` -- four dead keys, which is itself the proof
# the file changed schemes. Under the old set ``A`` (an OFFICIAL figure, 43.7% of the file) was marked
# UNOFFICIAL while ``I`` (imputed) and ``M`` (missing) were marked OFFICIAL, so ``is_official`` was
# inverted on the two ends that matter most. The ML label lane reads that column (`source_contracts.yaml`
# status: core), so this is a correctness fix, not a cosmetic one.
FLAG_SEMANTICS: dict[str, str] = {
    "A": "Official figure",
    "E": "Estimated value",
    "I": "Value imputed by a receiving agency",
    "M": "Missing value; data cannot exist",
    "X": "Figure from external organization",
}

# Officiality is ASSERTED, never inferred: only FAO's own "Official figure" marks a row official.
OFFICIAL_FLAGS = frozenset({"A"})

# ``M`` says the observation CANNOT EXIST. THIS IS A FORWARD GUARD, NOT A REPAIR: measured on the
# 2026-05-11 ZIP, all 94,355 M rows print an EMPTY Value cell, so pd.to_numeric has already made them
# NaN and this blanking moves zero rows on the current vintage (the Lane-4 review measured it to the
# row). It exists for the vintage where FAO does print a number beside M -- carrying that number
# forward would mint a measured-looking figure for a country-year FAO states cannot exist -- and it
# runs AFTER duplicate resolution so such a value still participates in conflict detection first
# (see _blank_no_value_flags). Neither official nor a value.
NO_VALUE_FLAGS = frozenset({"M"})

# Natural key for silver_production (commodity is fixed per call; year is the partition tuple key).
_NATURAL_KEY = ["country_key", "metric", "year"]


class FaostatMappingError(ValueError):
    """A FAOSTAT bronze row cannot be mapped onto the governed silver contract (fail-closed)."""


class SilverProductionLayoutError(ValueError):
    """A silver_production write key is not the canonical projected layout (fail-closed)."""


def assert_canonical_production_key(key: str) -> str:
    """Hard-guard the canonical ``silver/production/commodity=<c>/year=<y>/`` layout (SILVER-F022).

    Refuses the legacy ``silver/production/source=faostat/`` prefix (which the projection does NOT
    resolve, so its objects are invisible to the served table) -- and any ``source=`` segment, or a
    key outside ``silver/production/``. Called before every write so the wrong-prefix regression can
    never recur."""
    k = (key or "").lstrip("/")
    if not k.startswith("silver/production/"):
        raise SilverProductionLayoutError(
            f"silver_production key {key!r} is not under silver/production/"
        )
    if "source=" in k:
        raise SilverProductionLayoutError(
            f"silver_production key {key!r} carries a 'source=' segment -- the canonical layout is "
            "silver/production/commodity=<c>/year=<y>/ (SILVER-F022 forbids the source=faostat prefix)"
        )
    if "commodity=" not in k or "year=" not in k:
        raise SilverProductionLayoutError(
            f"silver_production key {key!r} is missing the commodity=/year= partition segments"
        )
    return key


def standardize_country_name(value: str) -> str:
    """Governed country KEY: NFKD-fold accents, drop non-ASCII, snake_case.

    "Cote d'Ivoire" -> "cote_divoire" (consistent with the weather-silver country key)."""
    s = unicodedata.normalize("NFKD", str(value).strip())
    s = s.encode("ascii", "ignore").decode("ascii")
    return (
        s.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("'", "")
        .replace("(", "")
        .replace(")", "")
    )


def load_bronze_faostat(bronze_root: str | Path) -> pd.DataFrame:
    bronze_root = Path(bronze_root)
    parquet_files = sorted(bronze_root.rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No bronze FAOSTAT Parquet files found under {bronze_root}")
    frames = [pd.read_parquet(path) for path in parquet_files]
    return pd.concat(frames, ignore_index=True)


def _resolve_duplicates_or_raise(silver: pd.DataFrame) -> pd.DataFrame:
    """Drop logically-exact duplicate rows; FAIL on a conflicting natural-key value.

    Two rows with the same ``(country_key, metric, year)`` may be collapsed automatically ONLY when
    their ``value`` agrees (byte/logically exact). A genuine value conflict is a data defect that
    must be triaged (documented flag precedence / quarantine), never silently last-wins."""
    dup_mask = silver.duplicated(subset=_NATURAL_KEY, keep=False)
    if dup_mask.any():
        conflicts = []
        for key, group in silver.loc[dup_mask].groupby(_NATURAL_KEY, dropna=False):
            if group["value"].dropna().round(9).nunique() > 1:
                conflicts.append(key)
        if conflicts:
            preview = ", ".join(str(c) for c in conflicts[:5])
            raise FaostatMappingError(
                f"FAOSTAT silver has conflicting duplicate values for natural key(s) {preview}. "
                "Resolve via flag precedence or quarantine before publishing."
            )
    return silver.drop_duplicates(subset=_NATURAL_KEY, keep="last")


def _apply_flag_semantics(df: pd.DataFrame) -> pd.DataFrame:
    """Derive ``is_official`` from :data:`FLAG_SEMANTICS` and blank the value of a ``M`` row (FAO-6).

    FAIL-CLOSED IN BOTH DIRECTIONS, and they are different directions on purpose:

      * a PRESENT flag the legend does not carry is a legend change -- raise, because the alternative
        is publishing an ``is_official`` whose meaning nobody has read. The four dead pre-2022 keys
        (F / Fc / Im / ``*``) reach this branch if FAO ever reverts, which is exactly when a silent
        default would re-inject the inverted column this replaced;
      * an ABSENT flag is an absence of an OFFICIALITY ASSERTION, not a scheme change -- the row keeps
        its value and reads ``is_official=False``. Measured: the 2026-05-11 ZIP carries no blank flag
        at all, so this branch exists for a future vintage and for hand-built frames, and it leans the
        only way that cannot manufacture officialness."""
    flags = df["flag"].astype("string").str.strip()
    unknown = sorted(set(flags.dropna().unique()) - set(FLAG_SEMANTICS))
    if unknown:
        raise FaostatMappingError(
            f"FAOSTAT bronze carries observation flag(s) {unknown} absent from the release legend "
            f"{sorted(FLAG_SEMANTICS)}. The flag scheme changed: re-read "
            "Production_Crops_Livestock_E_Flags.csv inside the QCL ZIP and re-derive is_official "
            "before publishing (FAO-6)."
        )
    df["is_official"] = flags.isin(OFFICIAL_FLAGS).fillna(False).astype(bool)
    return df


def _assert_units_are_governed(df: pd.DataFrame) -> pd.DataFrame:
    """RAISE on an ungoverned ``(metric, unit)`` pair (FAO-2 (c)) -- the head-vs-tonnes fence.

    Same fail-closed posture as :func:`_apply_flag_semantics`, and for a sharper reason: ``unit`` is
    a free string, so nothing structural stops a head count from being published under a metric a
    consumer sums with tonnes, and a wrong unit is undetectable downstream.

    TWO TIERS, and the split is deliberate rather than a softened fence:

      * every metric this lane INTRODUCED (:data:`LIVESTOCK_METRICS`) is fenced against its whole
        declared unit set -- the new axis is born fenced;
      * the three ``(metric, unit)`` pairs at :data:`_REFUSED_UNITS` are refused on ANY metric,
        including the three crop metrics that predate this lane.

    ON REAL BRONZE THE TWO TIERS ARE THE SAME FENCE, and that is the measurement that justifies the
    split rather than an argument. Over all 4,209,110 rows of the 2026-05-11 ZIP the crop elements
    carry exactly three units -- ``Area harvested``: {ha}; ``Production``: {t, 1000 No};
    ``Yield``: {kg/ha, No/An} -- so ``_REFUSED_UNITS`` already names EVERY unit a crop metric can
    physically receive that its card does not declare. The tiers diverge only on hand-built frames,
    where the estate's fixtures carry pre-F022 spellings the release has not printed for years
    (``tonnes``, ``hg/ha``): retro-fencing those in the change that introduces the livestock axis
    would couple this correctness fix to eleven fixture rewrites across four suites, and a fence that
    forces unrelated churn is how fences get relaxed. Promoting the crop tier to a hard fail is a
    named, separate step -- it needs the live silver objects' unit vocabulary measured first."""
    # Normalize ON THE FRAME, not on a scratch copy (Lane-5 review minor): the fence used to strip
    # a copy and publish the raw value, so unit ' An ' passed the check and reached silver padded --
    # on the column the card declares AUTHORITATIVE. The stripped value IS the published value now.
    df = df.copy()
    df["unit"] = df["unit"].astype("string").str.strip()
    pairs = df[["metric", "unit"]]
    bad: list[str] = []
    for metric, unit in pairs.drop_duplicates().itertuples(index=False):
        metric = str(metric)
        unit_s = None if pd.isna(unit) else str(unit)
        note = _REFUSED_UNITS.get((metric, unit_s or ""))
        allowed = METRIC_UNITS.get(metric)
        fenced = metric in LIVESTOCK_METRICS
        if note is None and not (fenced and (allowed is None or unit_s not in allowed)):
            continue
        bad.append(
            f"({metric!r}, {unit_s!r})"
            + (f" -- REFUSED BY NAME: {note}" if note else "")
            + (f"; governed units are {sorted(allowed)}" if allowed else "")
        )
    if bad:
        raise FaostatMappingError(
            "FAOSTAT bronze carries (metric, unit) pair(s) this table does not govern: "
            + "; ".join(sorted(bad))
            + ". A unit is a free string on silver_production, so an ungoverned pair publishes a "
              "number nobody has read the units of -- head counts and tonnes share one physical "
              "schema here (FAO-2). Widen METRIC_UNITS deliberately, with the row count measured off "
              "the release ZIP and the card's per-metric unit moved in the SAME change; never by "
              "adding a member to make a run go green."
        )
    # THE SAME-KEY MULTI-UNIT GUARD (Lane-5 review, major 3). The check above is PAIR-wise: 'An'
    # and '1000 An' are BOTH governed for live_animals, so one (country_key, metric, year) key
    # printed in both scales passes it -- and then either dies downstream in
    # _resolve_duplicates_or_raise as a VALUE conflict (the wrong diagnosis, the exact class the
    # fence-first ordering exists to prevent) or, when the two scales happen to print EQUAL values,
    # collapses silently on keep="last" and publishes a head count under whichever scale survived.
    # Unreachable on today's roster (measured: no admitted (item, element) pair prints two units --
    # the two multi-unit pairs in the whole file are both egg items, parked at the item map), which
    # is exactly why it is guarded HERE rather than trusted: the first admission that changes the
    # measurement must die loudly with the (metric, units) named, before the dedup can mis-diagnose
    # or swallow it.
    key_units = df.groupby(_NATURAL_KEY, dropna=False)["unit"].nunique(dropna=False)
    key_units = key_units[key_units > 1]
    if len(key_units):
        sample = [tuple(map(str, k if isinstance(k, tuple) else (k,)))
                  for k in key_units.index[:5]]
        raise FaostatMappingError(
            f"{int(len(key_units))} (country_key, metric, year) key(s) carry MORE THAN ONE unit "
            f"(examples: {sample}). The natural key holds no unit, so a multi-unit key either "
            "mis-diagnoses as a value conflict or silently collapses to one scale -- a 1000x "
            "hazard on the head-count metrics. The fix is a value-scale decision (which unit the "
            "estate serves) at the item map, never a key widening and never a METRIC_UNITS edit."
        )
    return df


def _blank_no_value_flags(df: pd.DataFrame) -> pd.DataFrame:
    """NULL the value of every :data:`NO_VALUE_FLAGS` row -- AFTER duplicate resolution, deliberately.

    Blanking before ``_resolve_duplicates_or_raise`` fails OPEN for exactly the future vintage this
    guard exists for: the conflict test drops NaN, so an M row carrying a printed number would vanish
    from conflict detection and ``keep="last"`` could silently publish the NaN M row over a real
    official figure -- the "never a silent last-wins" promise broken by ordering alone (Lane-4 review,
    minor 1). Run here, a numeric M cell first collides loudly with any sibling row, and only the
    survivor is blanked."""
    flags = df["flag"].astype("string").str.strip()
    # float NaN, not pd.NA: `value` is float64 by this point and the registry contract keeps it numeric.
    df.loc[flags.isin(NO_VALUE_FLAGS).fillna(False), "value"] = float("nan")
    return df


def transform_faostat_production_silver_df(
    df: pd.DataFrame,
    commodity: str,
) -> list[tuple[int, pd.DataFrame]]:
    """Clean an already-loaded bronze FAOSTAT DataFrame into the canonical ``silver_production`` shape.

    Returns a list of ``(year, silver_df)`` pairs. Each ``silver_df`` has EXACTLY the 12 canonical
    physical columns (:data:`CANONICAL_PHYSICAL_COLUMNS`); ``commodity`` (this call's arg) and
    ``year`` (the tuple key) are the projected partition keys, carried on the path, not in the body.
    """
    required = {"area", "item", "element", "year", "unit", "value", "flag"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required FAOSTAT bronze columns: {missing}")

    df = df.copy()

    # Resolve the element CASE-INSENSITIVELY onto the legend's own string (see _ELEMENT_LOOKUP: the
    # old str.capitalize() fold dropped three of the five livestock elements silently). An element
    # the map does not carry resolves to NA and is filtered out, exactly as before.
    df["element"] = (
        df["element"].astype(str).str.strip().str.lower().map(_ELEMENT_LOOKUP)
    )
    df = df[df["element"].isin(ELEMENT_TO_METRIC)].copy()
    if df.empty:
        return []

    # metric (was `variable`): explicit, validated map -- unmapped elements are already filtered out.
    df["metric"] = df["element"].map(ELEMENT_TO_METRIC)

    # display country (preserved) + governed country key.
    df["country"] = df["area"].astype(str).str.strip()
    df["country_key"] = df["area"].astype(str).map(standardize_country_name)

    df["source"] = SOURCE
    df["dataset"] = df["dataset"].astype(str) if "dataset" in df.columns else DEFAULT_DATASET
    df["note"] = df["note"] if "note" in df.columns else None
    df["source_file_name"] = df["source_file_name"] if "source_file_name" in df.columns else None
    if "ingest_date" not in df.columns:
        df["ingest_date"] = None

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df["flag"] = df["flag"].where(
        df["flag"].notna() & (df["flag"].astype(str).str.strip() != ""), other=None
    )
    df = _apply_flag_semantics(df)

    df = df.dropna(subset=["year", "metric", "country_key"]).copy()
    if df.empty:
        return []
    df["year"] = df["year"].astype(int)

    silver = df[CANONICAL_PHYSICAL_COLUMNS + ["year"]].copy()
    # BEFORE duplicate resolution, deliberately -- the mirror image of _blank_no_value_flags' reason.
    # `_NATURAL_KEY` is (country_key, metric, year) and carries NO unit, so a metric arriving in two
    # units collides on the key and `_resolve_duplicates_or_raise` reports it as a VALUE conflict.
    # That is the correct outcome (it is fail-closed either way), but the wrong DIAGNOSIS: it sends
    # the reader hunting a data defect when the answer is a units decision. Fencing first means the
    # run stops with the (metric, unit) pair named. MEASURED, this is not hypothetical: admitting
    # `Hen eggs in shell, fresh` would put `t` and `1000 No` on 13,801 of its 14,009 (area, year)
    # keys under one governed metric.
    silver = _assert_units_are_governed(silver)
    silver = _resolve_duplicates_or_raise(silver)
    silver = _blank_no_value_flags(silver)

    # Coverage warnings (unofficial-heavy sources). Under the FAO-6 scheme these carry signal: a
    # non-official row is E/I/X/M (estimated / imputed / external-org / missing), never an A.
    for (ckey, metric), group in silver.groupby(["country_key", "metric"]):
        if group["is_official"].sum() == 0:
            logger.warning(
                "No official rows for country_key=%s metric=%s -- every value is FAO-estimated, "
                "imputed or sourced from an external organization",
                ckey, metric,
            )
    non_official_pct = (~silver["is_official"]).mean() * 100
    if non_official_pct > 30:
        logger.warning(
            "%.1f%% of silver rows are non-official (FAO estimated/imputed/external). "
            "Review flag distribution before using in ML.",
            non_official_pct,
        )

    out: list[tuple[int, pd.DataFrame]] = []
    for year, year_df in silver.groupby("year"):
        body = year_df[CANONICAL_PHYSICAL_COLUMNS].reset_index(drop=True)
        out.append((int(year), body))
    return out
