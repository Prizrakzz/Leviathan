"""SILVER-C001 regression: partition-key columns are PATH-materialized, not FOOTER columns.

stage_feature_probe (jobs/audit/silver_rebuild_gate.py) checks that a rebuilt Branch-B table's
contract-required columns are present in the parquet FOOTER schema (probe.columns). Hive partition
keys (``commodity=`` for silver_nass_crop_progress, ``release_date=`` for silver_wasde) are
materialized in the S3 PATH and are NEVER in a footer, so a partitioned table whose ``natural_key``
includes its partition key would false-RED with "missing required columns ['commodity']"
(live-caught in the F1 sweep -- latent because every prior Branch-B table was flat). The root fix
subtracts declared partition keys before the miss computation: they count as PRESENT
(path-materialized), while genuinely-missing IN-FILE columns still RED.
"""
from __future__ import annotations

import types

from jobs.audit import silver_rebuild_gate as g


class _SilverReg:
    """Minimal F010-silver-registry shim: ``table(name)`` + ``value_columns(name)``."""

    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return self.tables[name]

    def value_columns(self, name):
        return list(self.tables[name].get("value_columns", []))


def _ctx(silver_reg, **kw):
    base = dict(numbers_reg=types.SimpleNamespace(get=lambda t: None), silver_reg=silver_reg,
                query_fn=None, conn=None, census_asof="2026-02-15", prior_census=None,
                eval_runner=None, value_census_fn=None)
    base.update(kw)
    return g.GateContext(**base)


def _probe(columns, *, num_files=4, num_rows=1000):
    """A footer-only SourceProbe stand-in (leviathan.features.extractors.probe_source shape)."""
    return types.SimpleNamespace(exists=True, num_files=num_files, num_rows=num_rows,
                                 columns=tuple(columns))


# ---------------------------------------------------------------------------
# (a) partitioned table whose natural_key INCLUDES the partition key, footer LACKS it -> GREEN.
# ---------------------------------------------------------------------------
def test_partition_key_in_natural_key_not_in_footer_is_green(monkeypatch):
    """silver_nass_crop_progress shape: ``commodity`` is both a natural_key member AND the Hive
    partition key, so it lives in the path (``commodity=``) and never in the parquet footer. Pre-fix
    this false-REDed with "missing required columns ['commodity']"; the fix treats it as present."""
    import leviathan.features.extractors as extractors

    contract = {
        "consumers": "feature_layer",
        "s3_root": "s3://leviathan-test/silver/nass_crop_progress",
        "natural_key": ["commodity", "state", "week_ending"],
        "value_columns": ["pct_complete"],
        "partition_keys": [{"name": "commodity", "glue_type": "string"}],
    }
    silver = _SilverReg({"silver_nass_crop_progress": contract})
    # Footer schema carries everything EXCEPT the path-materialized partition key ``commodity``.
    monkeypatch.setattr(extractors, "probe_source",
                        lambda key, loc, **k: _probe(("state", "week_ending", "pct_complete")))

    res = g.stage_feature_probe("silver_nass_crop_progress", _ctx(silver))

    assert res.status == g.GREEN, res.detail
    # Self-explaining evidence: the partition key was satisfied from the contract, not the footer.
    assert "1 partition-key column(s) path-materialized" in res.detail
    # And the pre-fix false-RED string must NOT appear.
    assert "missing required columns" not in res.detail


# ---------------------------------------------------------------------------
# (b) a genuinely-missing IN-FILE column -> RED naming ONLY that column (partition key excluded).
# ---------------------------------------------------------------------------
def test_genuinely_missing_in_file_column_is_red(monkeypatch):
    """silver_wasde shape: ``release_date`` is the Hive partition key (path-materialized -- must NOT
    RED), but ``estimate_role`` is a real additive F036 column physically absent from pre-2026-06
    partition files -> the REAL, reported finding, which must stay RED and name ONLY that column."""
    import leviathan.features.extractors as extractors

    contract = {
        "consumers": "feature_layer",
        "s3_root": "s3://leviathan-test/silver/wasde",
        "natural_key": ["release_date", "commodity"],
        "value_columns": ["value", "estimate_role"],
        "partition_keys": [{"name": "release_date", "glue_type": "string"}],
    }
    silver = _SilverReg({"silver_wasde": contract})
    # Footer has commodity + value, but LACKS the partition key release_date (fine) AND estimate_role.
    monkeypatch.setattr(extractors, "probe_source",
                        lambda key, loc, **k: _probe(("commodity", "value")))

    res = g.stage_feature_probe("silver_wasde", _ctx(silver))

    assert res.status == g.RED, res.detail
    # Names ONLY the genuinely-missing IN-FILE column ...
    assert "estimate_role" in res.detail
    # ... and never the path-materialized partition key (that was the false-RED bug).
    assert "release_date" not in res.detail


# ---------------------------------------------------------------------------
# regression guard: a flat table (no partition_keys) is unaffected -- the fix is purely additive.
# ---------------------------------------------------------------------------
def test_flat_table_without_partition_keys_unaffected(monkeypatch):
    """The pre-F1 status quo the bug hid behind: a flat Branch-B table (no ``partition_keys``) whose
    footer holds every contract column stays GREEN, with no path-materialized annotation and no
    KeyError on the absent ``partition_keys`` field."""
    import leviathan.features.extractors as extractors

    contract = {
        "consumers": "feature_layer",
        "s3_root": "s3://leviathan-test/silver/cot",
        "natural_key": ["commodity", "report_date"],
        "value_columns": ["net_long"],
    }
    silver = _SilverReg({"silver_cot": contract})
    monkeypatch.setattr(extractors, "probe_source",
                        lambda key, loc, **k: _probe(("commodity", "report_date", "net_long")))

    res = g.stage_feature_probe("silver_cot", _ctx(silver))

    assert res.status == g.GREEN, res.detail
    assert "path-materialized" not in res.detail
