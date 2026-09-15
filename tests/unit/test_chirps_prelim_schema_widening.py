"""THE SILVER WIDENING: one column for chirps, NOTHING for its two siblings, and the compaction that
would otherwise have raised on every historical year.

FOUR THINGS ARE PINNED HERE, and three of them are failure modes that would have shipped silently.

T-D2 -- THE ALIAS TRAP.  ``CHIRPS_LONG_SCHEMA`` and ``CPC_SOIL_LONG_SCHEMA`` were built from the SAME
Python list object, and ``CHIRPS_COMPACTED_SCHEMA IS CHIRPS_LONG_SCHEMA`` /
``CPC_SOIL_COMPACTED_SCHEMA IS CPC_SOIL_LONG_SCHEMA`` are the SAME OBJECTS, not copies.  Appending a
field to the shared list would have widened silver_cpc_soil AND both compacted schemas -- a meaningless
column in a table this lane has no business touching, its contract out of sync with its writer, and its
pinned deck red.  So SIX lengths are pinned, not two.

T-D1 -- THE COMPACTION THAT FAILS CLOSED.  ``enforce_arrow_schema`` RAISES on a missing column ("fails
closed rather than writing an inference-typed object") and ``compact_partition``'s ``reindex`` inserts
NaN for a column a frame lacks.  The moment ``CHIRPS_LONG_SCHEMA`` gained ``is_preliminary``, every
compaction of a pre-existing (commodity, year) -- all of 1981-2026 -- would have raised, silver_chirps
would have stopped advancing, and gold with it: the exact freeze class this arc exists to end.  The
backfill happens BEFORE the reindex, and it is the SOLE guard now that the column is a string (D-2
removed the alternative of teaching ``enforce_arrow_schema`` a boolean branch).

T-D3 -- THE SUPERSESSION THAT WAS POSITIONAL.  A fresh FINAL row beat a stale PRELIM row only because
the caller concatenates canonical frames before staging frames and ``drop_duplicates(keep="last")``
favours the later one.  ``is_preliminary`` is not in the natural key and could not break the tie, so one
``sorted()`` added for determinism would have let a PRELIM row overwrite a FINAL one -- no error, no
census signal.  Both frame orders are driven below and the FINAL must survive either way.

T-D7 / D-2 -- THE TYPE.  ``'0'``/``'1'`` STRING, per ``gold_board_crush.is_roll_boundary``, because
``enforce_arrow_schema`` coerces date / integer / floating / string and has NO boolean branch, and a
``pa.bool_()`` field over a reindex-produced NaN will not cast.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from leviathan.transforms.bronze_to_silver import _weather_schema as ws
from leviathan.transforms.bronze_to_silver.weather_compaction import (
    compact_partition,
    compacted_bytes,
    compacted_schema,
)

_PRELIM = ws.CHIRPS_IS_PRELIMINARY


# ---------------------------------------------------------------------------
# T-D2 -- six lengths, not two
# ---------------------------------------------------------------------------
class TestTheSplitWidenedExactlyOneTable:
    @pytest.mark.parametrize(
        "schema, length, name",
        [
            (ws.CHIRPS_LONG_SCHEMA, 12, "chirps long"),
            (ws.CHIRPS_COMPACTED_SCHEMA, 12, "chirps compacted"),
            (ws.CPC_SOIL_LONG_SCHEMA, 11, "cpc_soil long"),
            (ws.CPC_SOIL_COMPACTED_SCHEMA, 11, "cpc_soil compacted"),
            (ws.NASA_POWER_WIDE_SCHEMA, 15, "nasa_power wide"),
            (ws.NASA_POWER_COMPACTED_SCHEMA, 15, "nasa_power compacted"),
        ],
    )
    def test_the_six_pinned_lengths(self, schema, length, name):
        assert len(schema) == length, f"{name} is {len(schema)} fields, expected {length}"

    def test_cpc_soil_carries_NO_preliminary_column_at_either_grain(self):
        for schema in (ws.CPC_SOIL_LONG_SCHEMA, ws.CPC_SOIL_COMPACTED_SCHEMA):
            assert _PRELIM not in {f.name for f in schema}

    def test_nasa_power_carries_NO_preliminary_column_at_either_grain(self):
        for schema in (ws.NASA_POWER_WIDE_SCHEMA, ws.NASA_POWER_COMPACTED_SCHEMA):
            assert _PRELIM not in {f.name for f in schema}

    def test_cpc_soil_is_the_pre_lane_field_list_NAME_FOR_NAME_AND_TYPE_FOR_TYPE(self):
        """The 11 fields of the R0 baseline layout, in order. A reorder is as much a drift as a widen."""
        assert [(f.name, str(f.type)) for f in ws.CPC_SOIL_LONG_SCHEMA] == [
            ("date", "date32[day]"), ("year", "int64"), ("month", "int64"), ("day", "int64"),
            ("country", "string"), ("region", "string"), ("commodity", "string"),
            ("source", "string"), ("ingest_date", "string"), ("variable", "string"),
            ("value", "double"),
        ]

    def test_chirps_is_that_same_list_PLUS_ONE_TRAILING_FIELD(self):
        """A trailing ADD, never an insert: the publisher's schema-widen reconciliation only accepts a
        PURE TRAILING-COLUMN widen of the table SD, and a reorder fails closed there."""
        cpc = [(f.name, str(f.type)) for f in ws.CPC_SOIL_LONG_SCHEMA]
        chirps = [(f.name, str(f.type)) for f in ws.CHIRPS_LONG_SCHEMA]
        assert chirps[:-1] == cpc
        assert chirps[-1] == (_PRELIM, "string")

    def test_the_compacted_schemas_are_still_the_SAME_OBJECTS(self):
        """The alias is deliberate (compaction merges files, it never changes the column set) -- pinned
        so a future reader who splits somewhere other than the field list is caught here."""
        assert ws.CHIRPS_COMPACTED_SCHEMA is ws.CHIRPS_LONG_SCHEMA
        assert ws.CPC_SOIL_COMPACTED_SCHEMA is ws.CPC_SOIL_LONG_SCHEMA
        assert ws.NASA_POWER_COMPACTED_SCHEMA is ws.NASA_POWER_WIDE_SCHEMA
        assert compacted_schema("silver_chirps") is ws.CHIRPS_LONG_SCHEMA
        assert compacted_schema("silver_cpc_soil") is ws.CPC_SOIL_LONG_SCHEMA


# ---------------------------------------------------------------------------
# T-D7 -- the type, and why a boolean could not have been used
# ---------------------------------------------------------------------------
class TestTheTypeIsAString:
    def test_the_field_is_a_string_and_not_a_boolean(self):
        field = ws.CHIRPS_LONG_SCHEMA.field(_PRELIM)
        assert pa.types.is_string(field.type)
        assert not pa.types.is_boolean(field.type)

    def test_enforce_arrow_schema_STILL_has_no_boolean_branch(self):
        """The premise of the whole choice, asserted rather than assumed: if someone later adds a
        boolean branch, this deck says so and the type decision can be revisited deliberately."""
        import inspect
        src = inspect.getsource(ws.enforce_arrow_schema)
        assert "is_boolean" not in src

    def test_a_0_1_string_round_trips_through_the_pinned_writer(self):
        df = _chirps_frame(["0", "1", "0"])
        table = ws.enforce_arrow_schema(df, ws.CHIRPS_LONG_SCHEMA)
        assert table.schema.equals(ws.CHIRPS_LONG_SCHEMA)
        assert table.column(_PRELIM).to_pylist() == ["0", "1", "0"]

    def test_a_MISSING_preliminary_column_still_fails_the_writer_CLOSED(self):
        """The fail-closed behaviour is not weakened -- it is why the compaction backfill must exist."""
        df = _chirps_frame(["0"] * 3).drop(columns=[_PRELIM])
        with pytest.raises(ValueError, match="missing column"):
            ws.enforce_arrow_schema(df, ws.CHIRPS_LONG_SCHEMA)


# ---------------------------------------------------------------------------
# T-D1 -- the backfill, over a HISTORICAL (commodity, year) unit
# ---------------------------------------------------------------------------
def _chirps_frame(prelim_values, *, start_day: int = 1, value: float = 1.0) -> pd.DataFrame:
    n = len(prelim_values)
    days = list(range(start_day, start_day + n))
    return pd.DataFrame({
        "date": [pd.Timestamp(2018, 1, d).date() for d in days],
        "year": [2018] * n, "month": [1] * n, "day": days,
        "country": ["brazil"] * n, "region": ["r1"] * n, "commodity": ["corn_cbot"] * n,
        "source": ["chirps"] * n, "ingest_date": ["2026-06-16"] * n,
        "variable": ["precipitation_mm"] * n, "value": [value] * n,
        _PRELIM: list(prelim_values),
    })


def _legacy_frame(n: int = 3, *, value: float = 1.0) -> pd.DataFrame:
    """A pre-lane silver object: the ELEVEN-column layout every 1981-2026 canonical parquet carries."""
    return _chirps_frame(["0"] * n, value=value).drop(columns=[_PRELIM])


class TestCompactionBackfill:
    def test_a_PURELY_LEGACY_year_compacts_without_raising(self):
        """THE FREEZE THAT WOULD HAVE SHIPPED: without the backfill this raises for every historical
        (commodity, year), silver_chirps stops advancing, and gold_weather_z freezes behind it."""
        out = compact_partition([_legacy_frame(), _legacy_frame(3)], "silver_chirps")
        assert list(out.columns) == [f.name for f in ws.CHIRPS_LONG_SCHEMA]
        assert set(out[_PRELIM]) == {"0"}

    def test_and_it_SERIALISES_under_the_pinned_schema(self):
        """compact_partition returning a frame is not the proof -- ``compacted_bytes`` is where
        ``enforce_arrow_schema`` runs, and that is the call that would have raised."""
        body = compacted_bytes(compact_partition([_legacy_frame()], "silver_chirps"), "silver_chirps")
        assert body[:4] == b"PAR1"
        table = pq.read_table(io.BytesIO(body))
        assert table.schema.field(_PRELIM).type == pa.string()
        assert table.column(_PRELIM).to_pylist() == ["0", "0", "0"]

    def test_a_MIXED_year_backfills_only_the_legacy_half(self):
        legacy = _legacy_frame(3)
        fresh = _chirps_frame(["1", "1"], start_day=4)
        out = compact_partition([legacy, fresh], "silver_chirps")
        assert out.sort_values("day")[_PRELIM].tolist() == ["0", "0", "0", "1", "1"]

    def test_an_EXPLICIT_NULL_in_the_column_is_backfilled_too(self):
        """``reindex`` is not the only source of a null here -- a left merge at the b2s seam can miss.
        Both mean FINAL, for the same reason: prelim was unreachable when those bytes were written."""
        frame = _chirps_frame(["1", None, "0"])
        out = compact_partition([frame], "silver_chirps")
        assert out.sort_values("day")[_PRELIM].tolist() == ["1", "0", "0"]

    def test_the_backfill_NEVER_touches_the_two_sibling_tables(self):
        """``_ADDITIVE_BACKFILL`` is keyed on the column name and gated on the target schema declaring
        it, so a cpc_soil or nasa_power compaction cannot acquire the column by accident."""
        cpc = _legacy_frame()
        cpc["source"] = "cpc_soil"
        out = compact_partition([cpc], "silver_cpc_soil")
        assert _PRELIM not in out.columns
        assert len(out.columns) == 11


# ---------------------------------------------------------------------------
# T-D3 -- supersession must not depend on frame order
# ---------------------------------------------------------------------------
class TestSupersessionIsExplicitNotPositional:
    def _frames(self):
        prelim = _chirps_frame(["1", "1", "1"], value=7.6490)   # the stale canonical vintage
        final = _chirps_frame(["0", "0", "0"], value=6.5214)    # the landed block, same natural key
        return prelim, final

    def test_the_FINAL_survives_when_canonical_comes_first(self):
        prelim, final = self._frames()
        out = compact_partition([prelim, final], "silver_chirps")
        assert set(out[_PRELIM]) == {"0"}
        assert out["value"].tolist() == [6.5214] * 3

    def test_the_FINAL_survives_when_the_ORDER_IS_REVERSED(self):
        """The assertion the pre-lane code could not have made. Feeding the fresh FINAL frame FIRST is
        what a ``sorted()`` for determinism, or a parallel read returning out of order, would produce --
        and positionally that hands the win to the stale PRELIM row."""
        prelim, final = self._frames()
        out = compact_partition([final, prelim], "silver_chirps")
        assert set(out[_PRELIM]) == {"0"}, "a PRELIM row overwrote a FINAL one on frame order alone"
        assert out["value"].tolist() == [6.5214] * 3

    def test_two_FINAL_rows_still_resolve_keep_last_exactly_as_before(self):
        """The pre-lane tie-break is untouched for rows that agree on the flag: the LATER frame wins,
        which is how a re-fetched final month refreshes a value."""
        older = _chirps_frame(["0", "0", "0"], value=1.0)
        newer = _chirps_frame(["0", "0", "0"], value=2.0)
        out = compact_partition([older, newer], "silver_chirps")
        assert out["value"].tolist() == [2.0] * 3

    def test_two_PRELIM_rows_also_keep_last(self):
        older = _chirps_frame(["1", "1", "1"], value=1.0)
        newer = _chirps_frame(["1", "1", "1"], value=2.0)
        out = compact_partition([older, newer], "silver_chirps")
        assert out["value"].tolist() == [2.0] * 3

    def test_a_legacy_frame_beside_a_prelim_frame_resolves_to_the_LEGACY_final(self):
        """A backfilled '0' is a real final claim and must win the tie like any other."""
        out = compact_partition([_chirps_frame(["1", "1", "1"], value=9.9), _legacy_frame(value=1.1)],
                                "silver_chirps")
        assert set(out[_PRELIM]) == {"0"}
        assert out["value"].tolist() == [1.1] * 3

    def test_the_polarity_is_stated_in_the_module_rather_than_left_to_the_reader(self):
        """``is_preliminary`` TRUE is the row that LOSES -- the name is inverted relative to the winner,
        which is exactly the kind of thing a later reader 'fixes' into a bug."""
        from leviathan.transforms.bronze_to_silver import weather_compaction as wc
        assert wc._PRELIM_WINS_LAST_ASCENDING is False
        import inspect
        assert "POLARITY" in inspect.getsource(wc).upper()


# ---------------------------------------------------------------------------
# The contract the generator produced (T-D6, T-D8) -- declared, hidden, and SAID SO
# ---------------------------------------------------------------------------
class TestGeneratedContract:
    def test_the_column_is_declared_as_a_HIDDEN_physical_column(self):
        from leviathan.silver.registry import load_registry
        contract = load_registry().table("silver_chirps")
        col = next(c for c in contract["physical_columns"] if c["name"] == _PRELIM)
        assert col["glue_type"] is None, "a registered column would need a gated Glue ADD COLUMNS"
        assert col["target_arrow_type"] == "string"
        assert col["nullable"] is True

    def test_the_pinned_writer_schema_still_COVERS_the_contract(self):
        from leviathan.silver.registry import load_registry
        reg = load_registry()
        for table in ("silver_chirps", "silver_cpc_soil", "silver_nasa_power"):
            assert ws.assert_covers_registry(table, reg.table(table)) == [], table

    def test_it_is_NOT_a_value_column(self):
        """T-D4: every historical row is '0', so a censused constant trips the HARD KIND_ALL_CONSTANT
        gate row table-wide. The flag's own invariant is the producer's job, not the census's."""
        from leviathan.silver.registry import load_registry
        assert load_registry().table("silver_chirps")["value_columns"] == ["value"]

    def test_the_STALE_FINGERPRINT_is_declared_rather_than_silently_left(self):
        """T-D8, decided and STATED: physical_parquet_cols stays 11 beside a 12-column writer, because
        11 is still what every object on S3 carries. The contract says so in its own notes, so the next
        reader meets a declared state instead of a lie."""
        from leviathan.silver.registry import load_registry
        contract = load_registry().table("silver_chirps")
        assert contract["fingerprint"]["physical_parquet_cols"] == 11
        assert "FINGERPRINT BELOW IS STALE BY DESIGN" in contract["notes"]

    def test_the_write_recency_fields_did_NOT_move(self):
        """T-F6: ``publication_lag_days`` here is consumed as GRACE on a WRITE-RECENCY alarm, so
        declaring the source's 25 (or the prelim's 7) would quietly loosen it -- the category error
        ``dag_catalog.FRESHNESS_LAG_OVERRIDES`` exists to cancel. Both stay null."""
        from leviathan.silver.registry import load_registry
        contract = load_registry().table("silver_chirps")
        assert contract["publication_lag_days"] is None
        assert contract["freshness_sla"]["max_lag_days"] is None

    def test_the_two_sibling_contracts_declare_no_new_column(self):
        from leviathan.silver.registry import load_registry
        reg = load_registry()
        # The CONTRACT counts are not the pinned-schema counts: the contract lists the declared Glue
        # non-partition columns plus the partition-redundant id columns the producers also write, so
        # cpc_soil declares 9 and nasa_power 14 while their WRITER schemas are 11 and 15. Both numbers
        # are pinned -- the writer lengths above, the contract lengths here.
        assert len(reg.table("silver_cpc_soil")["physical_columns"]) == 9
        assert len(reg.table("silver_nasa_power")["physical_columns"]) == 14
        assert len(reg.table("silver_chirps")["physical_columns"]) == 10   # 9 + is_preliminary
        assert _PRELIM not in {c["name"] for c in reg.table("silver_cpc_soil")["physical_columns"]}
        assert _PRELIM not in {c["name"] for c in reg.table("silver_nasa_power")["physical_columns"]}

    def test_the_FINAL_PUBLICATION_BAND_IS_THE_MEASURED_ONE_IN_EVERY_COPY(self):
        """Close-out 2026-09-15. The 2026-08 block landed at +11 (ONE write, Last-Modified
        2026-09-11 21:10Z), which moved the lower bound down from the 12 the first cut of this lane
        carried. The band is quoted in FIVE places -- the fetcher, the daily task, the generator, the
        generated contract and this deck's sibling -- and a stale copy is exactly how the next reader
        re-derives a horizon the source does not keep. One string, pinned across all of them."""
        from pathlib import Path

        from leviathan.silver.registry import load_registry
        assert "+11..+16" in load_registry().table("silver_chirps")["notes"]
        repo = Path(__file__).resolve().parents[2]
        for rel in ("src/leviathan/ingestion/weather/chirps.py",
                    "jobs/batch/chirps_to_bronze_task.py",
                    "scripts/silver/gen_registry_from_baseline.py",
                    "tests/unit/test_chirps_prelim_fallback.py"):
            text = (repo / rel).read_text(encoding="utf-8")
            assert "+11..+16" in text, f"{rel} does not carry the measured band"
            assert "12-16 days past month-end" not in text, f"{rel} still carries the stale band"

    def test_the_generated_DDL_does_not_render_the_hidden_column(self):
        """The whole reason for choosing hidden: no ALTER, no catalog drift, nothing to apply -- and
        the one consumer that must read it reads S3 parquet directly, never Athena."""
        from leviathan.silver import ddl as D
        from leviathan.silver.registry import load_registry
        sql = D.render_ddl(load_registry().table("silver_chirps"))
        assert _PRELIM not in sql


# ---------------------------------------------------------------------------
# THE SEAM'S ONLY COERCION MUST NOT RAISE (close-out 2026-09-15, review minor)
# ---------------------------------------------------------------------------
# The pre-close cut read `pd.isna(v) is True else (v is True or v == 1 or ...)`. Driven over nine
# dtypes: a LIST cell is fine (`[1, 2] == 1` is plain False), but an NDARRAY cell RAISES
# `ValueError: The truth value of an array with more than one element is ambiguous` at the `v == 1`
# term -- and this is the transform's ONLY coercion, so the producer dies rather than writing '0'.
# Unreachable from either bronze builder today (both write a native bool); reachable from any reader
# that hands the seam an array-valued cell, and the blast radius is the partition, not the row.
_CELLS = [
    (True, "1"), (False, "0"),
    (np.bool_(True), "1"), (np.bool_(False), "0"),
    (1, "1"), (0, "0"), (1.0, "1"), (0.0, "0"),
    ("1", "1"), ("0", "0"), ("true", "1"), ("True", "1"), ("x", "0"),
    (None, "0"), (np.nan, "0"), (pd.NA, "0"),
    ([1, 2], "0"),                      # the dtype the OLD comment claimed was the dangerous one
    (np.array([1, 2]), "0"),            # the dtype that ACTUALLY raised
    (np.array([1]), "0"),               # a 1-element 1-d array is NOT a scalar (ndim 1): pre-close-out read it as True; pinned as "0"
    ([[1, 2], [3]], "0"),               # ragged: np.ndim itself raises on this under numpy >= 1.24
    ((1, 2), "0"), ({"a": 1}, "0"),
]


class TestTheCellCoercionCannotRaise:
    def test_every_dtype_a_reader_could_hand_it_maps_to_a_0_or_a_1(self):
        from leviathan.transforms.bronze_to_silver.chirps_weather import _to_prelim_string
        cells = [c for c, _ in _CELLS]
        out = _to_prelim_string(pd.Series(cells, dtype="object"))
        assert list(out) == [want for _, want in _CELLS]
        assert out.dtype == object
        assert set(out) <= {"0", "1"}

    def test_THE_NDARRAY_CELL_IS_THE_ONE_THAT_USED_TO_RAISE(self):
        """Stated as its own case so a future simplification back to the bare chain reddens HERE, with
        the reason, instead of in a fleet run. The pre-close expression is reproduced inline: it must
        still raise, which is what makes the guard above load-bearing rather than decorative."""
        def _pre_close(v):
            return False if pd.isna(v) is True else (
                v is True or v == 1 or (isinstance(v, str) and v.strip() in ("1", "true", "True")))

        with pytest.raises(ValueError, match="truth value of an array"):
            _pre_close(np.array([1, 2]))
        assert _pre_close([1, 2]) is False          # ...and the LIST never did

        from leviathan.transforms.bronze_to_silver.chirps_weather import _prelim_cell_truthy
        assert _prelim_cell_truthy(np.array([1, 2])) is False
        assert _prelim_cell_truthy(np.array(1)) is True   # a 0-d array IS a scalar and still counts

    def test_the_null_test_is_an_IDENTITY_test_and_stays_one(self):
        """`if pd.isna(v)` on an array-valued cell is itself ambiguous -- the identity comparison is
        the thing that makes step 1 safe, so it is pinned rather than left to a reader's judgement."""
        import inspect

        from leviathan.transforms.bronze_to_silver import chirps_weather as cw
        assert "pd.isna(v) is True" in inspect.getsource(cw._prelim_cell_truthy)


class TestTheFlagsDropOnTheMeltsOwnSubset:
    """The flags frame and the melt must discard the SAME rows. A dropna over [date, country, region]
    only (the pre-close cut) lets a row the melt threw away win `keep='last'` here and hand the
    surviving row the wrong flag."""

    @staticmethod
    def _bronze(rows):
        return pd.DataFrame(rows)

    def _row(self, day, prelim, year=2026, month=8):
        return {"commodity": "corn_cbot", "source": "chirps", "country": "us", "region": "ia",
                "date": f"2026-08-{day:02d}", "year": year, "month": month, "day": day,
                "latitude": 42.0, "longitude": -93.0, "precipitation_mm": 1.0,
                _PRELIM: prelim, "ingest_date": "2026-09-15"}

    def test_a_NULL_YEAR_duplicate_cannot_flip_the_kept_rows_flag(self):
        from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver
        good = self._row(1, False)
        # Same (date, country, region, source) -> same merge key; LAST in frame order, so keep='last'
        # would take it. The melt drops it for the null year, so the flags must drop it too.
        bad = self._row(1, True)
        bad["year"] = None
        silver = chirps_bronze_to_silver(self._bronze([good, bad]))
        assert len(silver) == 1
        assert list(silver[_PRELIM]) == ["0"], "a melt-dropped row won the flag"

    def test_the_same_row_WITH_a_valid_year_still_wins_keep_last(self):
        """The control: the guard must drop only what the melt drops, never more."""
        from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver
        silver = chirps_bronze_to_silver(self._bronze([self._row(1, False), self._row(1, True)]))
        assert len(silver) == 1
        assert list(silver[_PRELIM]) == ["1"]

    def test_the_two_subsets_are_ONE_list_and_not_two_that_agree(self):
        import inspect

        from leviathan.transforms.bronze_to_silver import _weather_long as wl
        from leviathan.transforms.bronze_to_silver import chirps_weather as cw
        assert cw._MELT_DROPNA_SUBSET == ["date", "year", "month", "day", "country", "region"]
        src = inspect.getsource(wl.melt_weather_to_long)
        assert 'dropna(subset=["date", "year", "month", "day", "country", "region"])' in src, (
            "the melt's dropna moved; _MELT_DROPNA_SUBSET must move with it")

    def test_the_returned_frame_is_still_merge_keys_plus_the_flag(self):
        """year/month/day are projected only to be dropped on; the merge shape must not widen or the
        left merge would suffix-collide with the melt's own year/month/day columns."""
        from leviathan.transforms.bronze_to_silver.chirps_weather import _preliminary_flags
        flags = _preliminary_flags(self._bronze([self._row(1, True), self._row(2, False)]))
        assert list(flags.columns) == ["date", "country", "region", "source", _PRELIM]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
