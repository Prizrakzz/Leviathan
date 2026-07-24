"""CPC IODMI bronze -> silver producer path for ``silver_noaa_iod`` (the re-baseline).

ADR_IOD_SOURCE_SWITCH (RATIFIED 2026-07-24, Option B) re-bases the served IOD Dipole Mode
Index from the FROZEN NOAA PSL HadISST1.1 file onto the live NOAA CPC ERSSTv5 IODMI record.
This module is the silver half of that path. It owns nothing analytical: every derivation
(3-month mean, +/-0.4 phase band, Ethiopia lag-4, trailing-tail trim) is a pure function of
the ordered ``dmi_value`` series, so :func:`~leviathan.transforms.bronze_to_silver.noaa_iod.
build_iod_silver` is REUSED UNCHANGED and only the ``source`` stamp differs (ADR Section 5).

The two identities this file keeps straight
-------------------------------------------
They deliberately disagree, and conflating them is the failure mode this module exists to
prevent:

  * **provider stamp** = ``cpc_iodmi`` (:data:`SOURCE`). The ``source`` column names the TRUE
    provider of every row (ADR-003 rule 2). The re-baselined silver is CPC/ERSSTv5 data and
    says so, in the same column where the frozen snapshot still says ``noaa_iod``.
  * **served path** = ``silver/weather/source=noaa_iod/...`` (:func:`silver_key`). ADR
    decision 6.4 RETAINS the legacy s3_root, Glue table name and 8-column schema as stable
    identifiers, so the 15 causal DAGs, the numbers Card A, the feature family and the
    pg mirror need zero repointing. The path is a legacy misnomer (ADR-003 rule 6), NOT a
    claim about provenance -- the ``source`` column is the provenance authority.

Only raw + bronze move to a truthful ``source=cpc_iodmi`` capture prefix
(``raw_cpc_iodmi_key`` / ``bronze_cpc_iodmi_key``), because those layers are per-provider
captures rather than a served identity.

What this module does NOT do
----------------------------
It does not publish. The canonical swap is the gated republish (shadow-publish + parity gate
+ ``publish_flat_silver``, jobs/batch/noaa_iod_task.py); a silver frame built here is inert
until that path authorizes it. It also does not re-anomalize: ERSSTv5's fixed 1991-2020
climatology is the served anomaly basis exactly as published (ADR decision 5), which is why
historical magnitudes are RESTATED rather than continued (1997-11 peak 1.28 -> 1.55).
"""
from __future__ import annotations

import pandas as pd

from leviathan.storage.paths import silver_iod_key
from leviathan.transforms.bronze_to_silver.noaa_iod import (
    SILVER_ARROW_SCHEMA,
    SILVER_COLUMNS,
    build_iod_silver,
    silver_arrow_schema,
)
from leviathan.transforms.raw_to_bronze.cpc_iodmi import SOURCE

__all__ = [
    "SILVER_ARROW_SCHEMA",
    "SILVER_COLUMNS",
    "SOURCE",
    "build_cpc_iodmi_silver",
    "silver_arrow_schema",
    "silver_key",
]


def silver_key() -> str:
    """S3 key the CPC-basis silver lands on -- the LEGACY ``source=noaa_iod`` root.

    Deliberately the same object the HadISST basis wrote (ADR decision 6.4: legacy stable
    identifier, minimal consumer churn), so the re-baseline is an atomic overwrite of the
    served frame rather than a path migration. Kept as a named seam here so the producer
    path states the legacy-root retention out loud instead of leaving it implicit in a
    shared helper; the raw/bronze captures for this basis DO carry ``source=cpc_iodmi``.
    """
    return silver_iod_key()


def build_cpc_iodmi_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Build the ``silver_noaa_iod`` frame from CPC IODMI bronze, stamped ``cpc_iodmi``.

    Args:
        df_bronze: Bronze DataFrame from
                   :func:`~leviathan.transforms.raw_to_bronze.cpc_iodmi.extract_cpc_iodmi_bronze`.
                   Its ``wtio_value`` / ``setio_value`` box columns ride along and are dropped
                   by the shared :data:`SILVER_COLUMNS` projection -- the served schema stays
                   the same 8 columns on both bases (no widen, no DDL change).

    Returns:
        The silver frame described by
        :func:`~leviathan.transforms.bronze_to_silver.noaa_iod.build_iod_silver`, with every
        row's ``source`` = :data:`SOURCE`.

    Raises:
        ValueError: Propagated from the shared builder (missing columns, empty frame,
            duplicate ``(year, month)``, or an all-placeholder series).
    """
    return build_iod_silver(df_bronze, source=SOURCE)
