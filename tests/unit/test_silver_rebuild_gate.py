"""SILVER-C001 unit tests for the silver_rebuild_gate DISPATCHER.

Everything AWS/pg is mocked or injected; nothing touches the mirror/Athena/Batch. Covers the three plan
requirements: (1) branch selection for ALL 44 F010 tables from the `consumers` field, (2) a Branch-B
feature-only table NEVER calls load_pg_numbers (the crash class Attack 3 #1 fixed), (3) fail-closed on any
red stage. Plus the census --diff new-dark detector and the offline (no-pg) skip posture."""
from __future__ import annotations

import json
import types

import pytest

from jobs.audit import silver_rebuild_gate as g


# --- a tiny F010-silver-registry shim ---------------------------------------------------------------------
class _SilverReg:
    def __init__(self, tables):
        self.tables = tables            # {name: contract dict}

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


# ---------------------------------------------------------------------------
# (1) branch selection for all 45 tables from the F010 consumers field
# ---------------------------------------------------------------------------
# THE BRANCH-A ROSTER, PINNED BY NAME. This used to be an integer (`len(branch_a) == 17`) with a
# changelog of counts above it, and an integer pin fails as "18 == 17": it says a table moved, never
# WHICH, and the changelog only tells you what the count meant on some past date. Two of the entries
# below were added by waves that shipped a P1_TABLES edit without bumping the pin, and the 2026-08-01
# Branch-A ratification of silver_futures_eod tripped four separate count assertions at once. So the
# roster is the assertion now: the next addition or removal fails with the table's NAME in the diff.
_EXPECTED_BRANCH_A = frozenset({
    "silver_psd", "silver_wasde", "silver_production", "silver_esr", "silver_fred_fx",
    "silver_noaa_oni", "gold_weather_z",                       # the original 7
    "silver_icco_cocoa", "silver_mpob", "silver_sagis_cec",    # numbers-depth wave
    "silver_pink_sheet",                                       # PRICE_OBSERVABILITY W3.3
    "silver_cot",                                              # PRICE_OBSERVABILITY W4.2
    "silver_futures_prices",                                   # SEAM C (2026-07-23)
    "silver_noaa_iod", "silver_conab_coffee",                  # WIRING WAVE-1 (2026-07-23)
    "silver_sagis_weekly_exports",                             # WIRING WAVE-1 Card C (2026-07-24)
    "gold_pattern_records",                                    # T2b (2026-07-24)
    "silver_futures_eod",                                      # BRANCH-A RATIFICATION (2026-08-01)
    # D-CW-2a (2026-08-07): the weekly NASS crop-progress card. It enters Branch A because BOTH halves
    # of select_branch now hold -- the F010 `consumers` field went to "both" when the numbers card
    # landed, and it is in P1_TABLES because a SERVED numbers table must be MIRRORED (unmirrored + pg
    # backend = UndefinedTable -> silent Athena fallback, here onto a PARTITION-PROJECTED table).
    # Distinct from silver_nasa_power, the other projected numbers table, which stays Branch B on a
    # measured SIZE exclusion (tens of millions of rows); this one is ~142K.
    "silver_nass_crop_progress",
    # D-PQ tranche 1a (2026-08-07, commit 2f2b0620 "feat(dpq): D-PQ build + adversarial review +
    # fixes -- futures front-expiry anchor, MPOC card, ..."). The 20th, and it enters for the
    # SAME reason as the 19th: the MPOC numbers card landed in that change, so the table became
    # SERVED, and a served numbers table must be MIRRORED -- unmirrored + GRAPHRAG_NUMBERS_BACKEND
    # =pg raises UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA. What makes this entry
    # worth reading rather than counting: the fallback here would be CHEAP (272 rows, one object,
    # projection-forbidden), and it was added anyway. "Small enough not to matter" is precisely how
    # a silent-fallback path gets normalized, so the doctrine is applied on the small table too.
    # The load still has to run in-VPC before any serving flip, and numbers_parity deliberately
    # carries NO SAMPLE_COMMODITY row for it yet -- picking that commodity/as-of pair against the
    # first REAL mirror beats guessing it here (the reverse drift, sampled-but-unmirrored, is what
    # the silver_futures_eod pin forbids).
    "silver_mpoc_stock_comparison",
    # D-LD TRACK 1 (2026-08-18, LIGHT THE DARK). Six at once -- the 21st through the 26th -- and every
    # one of them enters for the SAME reason as the 19th and the 20th and for no other: its numbers card
    # landed in that wave, so the table became SERVED, and a served numbers table must be MIRRORED.
    # Unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and SILENTLY FALLS BACK
    # TO ATHENA -- and for the three PROJECTED tables here (silver_fgis, and both fnc_colombia_* tables)
    # that fallback lands on a projected partition grid, which is the Jul-2026 LIST-storm class rather
    # than mere latency. Two of the six additionally DISCHARGE a recorded D-PQ refusal: the WAP revision
    # ledger closed its 'free_axis' blocker in CODE (row_filters + grain_cols) and the MPOC trade archive
    # closed its 'stale' verdict by re-measurement (a CLOSED archive, not a stale one) -- both discharges
    # are held in tests/unit/test_dpq_dark_tables.py.
    # As with silver_mpoc_stock_comparison: the in-VPC load has NOT run yet, and numbers_parity carries
    # no SAMPLE_COMMODITY row for any of the six -- picking those pairs against the first REAL mirror
    # beats guessing them here.
    "silver_fgis",
    "silver_wap_table01_revisions",
    "silver_fnc_colombia_monthly",
    "silver_fnc_colombia_exports_port_type",
    "silver_nass_citrus",
    "silver_mpoc_trade_stats_monthly",
})


def test_branch_selection_all_45_tables():
    from leviathan.silver import registry as sreg
    silver = sreg.load_registry()
    names = silver.names()
    assert len(names) == 45, f"expected 45 F010 tables, got {len(names)}"

    branch_a = {t for t in names if g.select_branch(t, silver_reg=silver) == g.BRANCH_A}
    branch_b = {t for t in names if g.select_branch(t, silver_reg=silver) == g.BRANCH_B}

    # Branch A == exactly the pg-mirror tables (== load_pg_numbers.P1_TABLES); every other table -> B.
    assert branch_a == g.PG_MIRROR_TABLES, branch_a
    assert branch_a == _EXPECTED_BRANCH_A, {
        "added_to_branch_a": sorted(branch_a - _EXPECTED_BRANCH_A),
        "removed_from_branch_a": sorted(_EXPECTED_BRANCH_A - branch_a),
        "why_this_matters": "a table entering Branch A gains the pg reload + parity + the V001 floor; "
                            "a table LEAVING it loses its only mirror refresh path while staying "
                            "served -- update this roster deliberately, never to make a test pass"}
    assert len(branch_a) == 26                        # 20 + D-LD Track 1's six LIGHT-THE-DARK cards
    assert branch_a | branch_b == set(names)          # partition: no table is UNKNOWN in the real registry
    assert not (branch_a & branch_b)


def test_futures_eod_routes_branch_a_after_the_ratification():
    """PRICE_AND_PLAYBOOKS: silver_futures_eod was the 45th F010 contract and rode Branch B through
    W1/W2 -- the pg mirror was DEFERRED (D7 / probe P8) pending a measured size check. RATIFIED
    2026-08-01 on measurement, not assertion: pg load 455,334 rows / 12.1s, numbers_parity 6/6
    exact-match, partitions 269 == 269. select_branch reaches Branch A only when BOTH halves hold --
    numbers-served by the F010 `consumers` field AND actually in the mirror allowlist -- so both are
    pinned here rather than inferred from the roster set above."""
    from leviathan.silver import registry as sreg
    silver = sreg.load_registry()
    assert silver.table("silver_futures_eod")["consumers"] == "both"
    assert "silver_futures_eod" in g.PG_MIRROR_TABLES, (
        "silver_futures_eod is SERVED from pg and the Branch-A reload is its ONLY refresh path: "
        "removing it from load_pg_numbers.P1_TABLES freezes the mirror while the canonical table "
        "grows ~2,500 rows/week, and a missing relation falls back to Athena rather than failing")
    assert g.select_branch("silver_futures_eod", silver_reg=silver) == g.BRANCH_A


def test_nasa_power_is_branch_b_despite_numbers_consumer():
    """silver_nasa_power's F010 consumers == 'both', but it is a PROJECTION table excluded from the mirror
    (INV-3 + size) -> Branch B, never load_pg_numbers. This is the exact shape Attack 3 #1 mandates."""
    from leviathan.silver import registry as sreg
    silver = sreg.load_registry()
    assert silver.table("silver_nasa_power")["consumers"] == "both"
    assert "silver_nasa_power" not in g.PG_MIRROR_TABLES
    assert g.select_branch("silver_nasa_power", silver_reg=silver) == g.BRANCH_B


def test_unregistered_table_is_unknown_and_fails_closed():
    silver = _SilverReg({})
    assert g.select_branch("silver_nope", silver_reg=silver) == g.BRANCH_UNKNOWN
    res = g.run_table("silver_nope", _ctx(silver))
    assert not res.ok and res.branch == g.BRANCH_UNKNOWN


# ---------------------------------------------------------------------------
# (2) Branch-B on a feature-only table NEVER calls load_pg_numbers (the crash class)
# ---------------------------------------------------------------------------
def test_branch_b_never_calls_load_pg_numbers(monkeypatch):
    import leviathan.features.extractors as extractors

    from jobs.utils import load_pg_numbers

    called = {"load_table": 0}

    def _boom_load_table(*a, **k):
        called["load_table"] += 1
        raise AssertionError("load_pg_numbers.load_table MUST NOT run for a feature-only table")

    monkeypatch.setattr(load_pg_numbers, "load_table", _boom_load_table)
    # a healthy footer probe (no S3)
    monkeypatch.setattr(extractors, "probe_source",
                        lambda key, loc, **k: types.SimpleNamespace(
                            exists=True, num_files=3, num_rows=100,
                            columns=("commodity", "year", "value")))

    silver = _SilverReg({"silver_chirps": {
        "consumers": "feature_layer", "s3_root": "s3://leviathan-dev-shahem-001/silver/chirps",
        "natural_key": ["commodity", "year"], "value_columns": ["value"]}})
    ctx = _ctx(silver, value_census_fn=lambda t, reg: {"ok": True})

    res = g.run_table("silver_chirps", ctx)
    assert res.branch == g.BRANCH_B
    assert called["load_table"] == 0
    stage_names = {s.name for s in res.stages}
    assert stage_names == {"feature_probe", "value_census", "config_check"} or "config_check" in stage_names
    assert not any(s.name in ("pg_reload", "parity", "contract_check") for s in res.stages)


# ---------------------------------------------------------------------------
# (3) fail-closed on a red stage
# ---------------------------------------------------------------------------
def _green(name):
    return lambda t, ctx: g.StageResult(name, g.GREEN, "ok")


def _red(name):
    return lambda t, ctx: g.StageResult(name, g.RED, "boom")


def _skip(name):
    return lambda t, ctx: g.StageResult(name, g.SKIPPED, "deferred")


def test_red_stage_fails_the_table_and_run(monkeypatch):
    silver = _SilverReg({"silver_wasde": {"consumers": "both"}})
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"silver_wasde"}))
    ctx = _ctx(silver)
    bundle = g.run_gate(["silver_wasde"], ctx,
                        branch_a_stages=(_green("pg_reload"), _red("parity"), _green("config_check")))
    assert bundle["verdict"] == "FAIL"
    assert bundle["banner"]["red_tables"] == 1
    assert bundle["results"][0]["ok"] is False


def test_all_green_passes(monkeypatch):
    silver = _SilverReg({"silver_wasde": {"consumers": "both"}})
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"silver_wasde"}))
    ctx = _ctx(silver)
    bundle = g.run_gate(["silver_wasde"], ctx,
                        branch_a_stages=(_green("pg_reload"), _green("config_check"), _skip("eval_subset")))
    assert bundle["verdict"] == "PASS"
    assert bundle["banner"]["branch_a"] == 1
    assert "in_vpc_submit_command" in bundle and "silver_wasde" in bundle["in_vpc_submit_command"]


def test_all_skipped_is_not_a_pass():
    """Fail-closed: a table whose every stage skipped proved nothing -> NOT ok."""
    silver = _SilverReg({"silver_cot": {"consumers": "feature_layer"}})
    ctx = _ctx(silver)
    res = g.run_table("silver_cot", ctx,
                      branch_b_stages=(_skip("feature_probe"), _skip("value_census"), _skip("config_check")))
    assert not res.ok


# ---------------------------------------------------------------------------
# census --diff new-dark detector
# ---------------------------------------------------------------------------
def test_census_diff_flags_new_dark_only():
    prior = {"legs": [{"contract": "cocoa", "node_id": "grind", "verdict": "DARK-WITH-REASON"}]}
    current = {
        "banner": {"athena_calls": 0},
        "legs": [
            {"contract": "cocoa", "node_id": "grind", "verdict": "DARK-WITH-REASON"},   # pre-existing
            {"contract": "corn_cbot", "node_id": "export", "verdict": "FIRES"},
            {"contract": "wheat_cbot", "node_id": "eu", "verdict": "DARK-WITH-REASON",  # NEW dark
             "table": "silver_psd", "metric": "exports", "reason": "country-not-a-psd-title"},
        ],
    }
    problems = g._census_diff(prior, current)
    assert len(problems) == 1 and "wheat_cbot/eu" in problems[0]


def test_census_diff_flags_nonzero_athena():
    problems = g._census_diff({"legs": []}, {"banner": {"athena_calls": 3}, "legs": []})
    assert any("ATHENA_CALLS" in p for p in problems)


# ---------------------------------------------------------------------------
# BRANCH-A RATIFICATION (2026-08-01): the SILVER-V001 populatedness floor rides Branch A too.
# ---------------------------------------------------------------------------
def test_branch_a_carries_the_v001_populatedness_floor():
    """Ratifying a table into Branch A must not silently DELETE its populatedness assertion.

    Branch B was the ONLY pipeline that ever ran the SILVER-V001 floor (stage_value_census); Branch A
    had none at all. Nothing else in Branch A substitutes for it: pg_reload counts ROWS, parity
    compares pg against Athena (identically-wrong on BOTH backends is a clean PASS -- it proves the
    mirror, not the data), and contract_check is the C002 vocabulary check over the numbers registry's
    declared metrics, not the F010 min_nonnull_frac floor. Without this stage a promoted table could
    reload 455,334 rows, diff 6/6 exact against Athena, and still be a wall of NULL values with every
    stage green -- which is precisely what promotion out of Branch B would have bought."""
    assert g.stage_value_census in g._BRANCH_A_STAGES, (
        "the V001 floor was dropped from Branch A: every table ratified into the pg mirror now has "
        "NO populatedness assertion anywhere in its rebuild gate (silver_futures_eod measured "
        "settle non-null 445,888/455,882 = 0.9781 against a min_nonnull_frac of 0.5 on 2026-08-01)")
    assert g.stage_value_census in g._BRANCH_B_STAGES, "shared, not moved: Branch B still needs it"

    # ORDERING, pinned because the reason is not recoverable from the tuple: the census sits inside
    # the PER-TABLE block -- after the reload+parity that establish which bytes are under test, ahead
    # of the three cross-table stages -- which is the widening-scope convention the whole pipeline is
    # written in (this table -> the numbers vocabulary -> the cascade -> the repo lints -> the deck).
    # A cheap table-specific red must not be paid for behind a full cascade census.
    order = [s.__name__ for s in g._BRANCH_A_STAGES]
    assert order == ["stage_pg_reload", "stage_parity", "stage_value_census", "stage_contract_check",
                     "stage_cascade_census_diff", "stage_config_check", "stage_eval_subset"], order


# ---------------------------------------------------------------------------
# offline posture: a Branch-A table with no pg backend SKIPS pg stages (never crashes)
# ---------------------------------------------------------------------------
def test_branch_a_offline_skips_pg_stages(monkeypatch):
    silver = _SilverReg({"silver_wasde": {"consumers": "both"}})
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"silver_wasde"}))
    numbers_reg = types.SimpleNamespace(get=lambda t: types.SimpleNamespace(id=t))
    # real Branch-A stages, but no pg backend -> pg_reload/parity/contract_check/census skip, config_check
    # still runs. Assert no crash and the pg stages are skipped (not red).
    ctx = _ctx(silver, numbers_reg=numbers_reg, query_fn=None, conn=None,
               value_census_fn=lambda t, reg: {"ok": True})
    monkeypatch.setattr(g, "_run_config_check", lambda: [])
    res = g.run_table("silver_wasde", ctx)
    by = {s.name: s.status for s in res.stages}
    assert by["pg_reload"] == g.SKIPPED
    assert by["parity"] == g.SKIPPED
    assert by["contract_check"] == g.SKIPPED
    assert by["cascade_census_diff"] == g.SKIPPED
    assert by["config_check"] == g.GREEN
    # ...and the V001 floor is NOT one of them. It reads S3 footers off the F010 contract, never the
    # mirror, so it stays live on exactly the runs where pg wiring is absent or incomplete -- which is
    # when a silently-deleted floor would be hardest to notice.
    assert by["value_census"] == g.GREEN


# ---------------------------------------------------------------------------
# A-W3 step 1: --baseline-uri / CENSUS_BASELINE_S3 rolling-baseline census input.
#   * set   -> fetch census.json from S3 (stubbed) and USE it,
#   * unset -> the image-baked local path exactly as before (never touches S3),
#   * fetch error -> FAIL CLOSED (BaselineFetchError -> nonzero exit), NO fallback to the stale snapshot.
# S3 is stubbed via g._s3_client so no boto3/network is exercised.
# ---------------------------------------------------------------------------
class _FakeBody:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    """Minimal boto3 S3 client stand-in: records get_object calls, returns a body or raises."""

    def __init__(self, body=None, exc=None):
        self._body = body
        self._exc = exc
        self.calls = []

    def get_object(self, Bucket, Key):   # noqa: N803 -- boto3 kwarg names
        self.calls.append((Bucket, Key))
        if self._exc is not None:
            raise self._exc
        return {"Body": _FakeBody(self._body)}


def test_baseline_uri_stubbed_s3_census_is_used(monkeypatch):
    """--baseline-uri set: the census.json fetched from S3 (stubbed) is what _load_prior_census returns,
    and the s3://bucket/key is split into the right Bucket/Key."""
    census = {"banner": {"athena_calls": 0},
              "legs": [{"contract": "cocoa", "node_id": "grind", "verdict": "DARK-WITH-REASON"}]}
    fake = _FakeS3(body=json.dumps(census).encode("utf-8"))
    monkeypatch.setattr(g, "_s3_client", lambda: fake)

    uri = "s3://leviathan-dev-shahem-001/cascade_census/rolling/fx_macro_daily/census.json"
    out = g._load_prior_census("2026-02-15", baseline_uri=uri)

    assert out == census
    assert fake.calls == [("leviathan-dev-shahem-001",
                           "cascade_census/rolling/fx_macro_daily/census.json")]


def test_baseline_uri_unset_uses_local_path_and_never_touches_s3(monkeypatch):
    """Unset -> the image-baked local tree exactly as before; S3 is NEVER contacted (byte-identical
    legacy path). Returns None here iff the file is absent in this tree -- must not raise either way."""
    def _boom():
        raise AssertionError("S3 must NOT be touched when --baseline-uri is unset")

    monkeypatch.setattr(g, "_s3_client", _boom)
    out = g._load_prior_census("2026-02-15", baseline_uri=None)
    assert out is None or isinstance(out, dict)


def test_baseline_uri_fetch_error_fails_closed(monkeypatch):
    """A get_object error raises BaselineFetchError -- NO silent fallback to the image-baked snapshot."""
    fake = _FakeS3(exc=RuntimeError("EndpointConnectionError: could not connect to the endpoint"))
    monkeypatch.setattr(g, "_s3_client", lambda: fake)
    with pytest.raises(g.BaselineFetchError):
        g._load_prior_census("2026-02-15", baseline_uri="s3://leviathan-dev-shahem-001/missing.json")


def test_baseline_uri_bad_scheme_fails_closed(monkeypatch):
    """A non-s3:// URI fails closed before any S3 call."""
    monkeypatch.setattr(g, "_s3_client",
                        lambda: (_ for _ in ()).throw(AssertionError("no S3 for a bad URI")))
    with pytest.raises(g.BaselineFetchError):
        g._load_prior_census("2026-02-15", baseline_uri="https://not-s3/census.json")


def test_baseline_uri_unparseable_json_fails_closed(monkeypatch):
    """A fetched-but-corrupt baseline fails closed rather than silently degrading."""
    fake = _FakeS3(body=b"this is not json {{{")
    monkeypatch.setattr(g, "_s3_client", lambda: fake)
    with pytest.raises(g.BaselineFetchError):
        g._load_prior_census("2026-02-15", baseline_uri="s3://b/bad.json")


def _capture_build_live_context(store, *, raise_after_capture=True):
    """Return a _build_live_context stand-in that records the baseline_uri it was called with and (by
    default) fails closed, so main() short-circuits before run_gate / any real stage."""
    def _fn(tables, *, census_asof, baseline_uri=None):
        store["baseline_uri"] = baseline_uri
        if raise_after_capture:
            raise g.BaselineFetchError(f"baseline census fetch failed for {baseline_uri}: stubbed")
        raise AssertionError("unreachable in these tests")
    return _fn


def test_main_baseline_fetch_error_is_nonzero_exit(monkeypatch, capsys):
    """main() catches BaselineFetchError, prints a clean ASCII FAIL line, and returns nonzero (fail closed).
    Also proves --baseline-uri is threaded through to _build_live_context.

    D-PR-8: the code is now EXIT_BASELINE_FETCH (72), the ONE retryable outcome -- not 1."""
    store = {}
    monkeypatch.setattr(g, "_build_live_context", _capture_build_live_context(store))
    rc = g.main(["--tables", "silver_wasde", "--baseline-uri", "s3://b/k/census.json"])
    assert rc == g.EXIT_BASELINE_FETCH
    assert store["baseline_uri"] == "s3://b/k/census.json"
    out = capsys.readouterr().out
    assert "FAIL silver_rebuild_gate" in out and "baseline" in out.lower()
    assert out.isascii()


def test_main_baseline_uri_env_fallback(monkeypatch):
    """CENSUS_BASELINE_S3 supplies the baseline when --baseline-uri is omitted."""
    store = {}
    monkeypatch.setenv("CENSUS_BASELINE_S3", "s3://env-bucket/rolling/census.json")
    monkeypatch.setattr(g, "_build_live_context", _capture_build_live_context(store))
    rc = g.main(["--tables", "silver_wasde"])
    assert rc == g.EXIT_BASELINE_FETCH
    assert store["baseline_uri"] == "s3://env-bucket/rolling/census.json"


def test_main_cli_baseline_uri_overrides_env(monkeypatch):
    """CLI --baseline-uri wins over CENSUS_BASELINE_S3."""
    store = {}
    monkeypatch.setenv("CENSUS_BASELINE_S3", "s3://env-bucket/census.json")
    monkeypatch.setattr(g, "_build_live_context", _capture_build_live_context(store))
    rc = g.main(["--tables", "silver_wasde", "--baseline-uri", "s3://cli-bucket/census.json"])
    assert rc == g.EXIT_BASELINE_FETCH
    assert store["baseline_uri"] == "s3://cli-bucket/census.json"


# =========================================================================================================
# D-PR-5 -- THE GATE BLAST-RADIUS SEVERITY SPLIT.
#
# Exhibit A (2026-08-03): ONE cot vocabulary drift on `brazilian_arabica_coffee` legs redded THREE
# unrelated family gates in one morning, because `contract_check()` walks the whole estate and returns one
# flat error list while `TableResult.ok` reds on ANY red stage. The split partitions the VERDICT BINDING
# only -- the walk stays global, every error stays in the bundle -- so the family that OWNS a drift still
# reds and the bystanders WARN.
#
# The error strings below are the REAL emit formats, quoted from their source lines:
#   contract_check.py:207-208  commodity-slug family  ('{contract}/{did}: ... of {table} (...)')
#   contract_check.py:96-97    wide-metric family     ('{tid}: ... of {phys} (...)')
#   contract_check.py:106-107  tall-metric family     ('{tid}: ... of {phys} (...)')
#   contract_check.py:166-167  country family         ('{contract}/{did}: ... of {table} (...)')
# A test written against invented strings would pass while the live parser reads nothing.
# =========================================================================================================
# The 2026-08-03 incident, byte-faithful: brazilian_arabica_coffee is `not_covered` in cftc_cot.yaml:107
# and its cot leg is `cot_mm_positioning` (configs/graphrag/causal/brazilian_arabica_coffee.yaml:462), so
# with the COT_UNSERVED_SLUGS fence removed this is exactly what check_commodity_slug_vocabulary emits.
_COT_DRIFT = ("brazilian_arabica_coffee/cot_mm_positioning: commodity slug 'brazilian_arabica_coffee' "
              "not in DISTINCT leviathan_slug of silver_cot "
              "(commodity-slug-miss -- the PSD_SLUG_ALIAS class)")
_WASDE_DRIFT = ("silver_wasde: metric column 'Ending Stocks' is not a physical column of silver_wasde "
                "(declared wide metric absent -- the WASDE Title-Case drift class)")
# silver_esr is `shape: wide` with `athena_table: silver_esr_compact` (tables.yaml:262,301), so its
# wide-metric error is the one shipped emit that names a PHYSICAL table -- alongside the agent id in its
# own prefix. Both names must land on the same family.
_ESR_DRIFT = ("silver_esr: metric column 'weekly_exports_1000mt' is not a physical column of "
              "silver_esr_compact (declared wide metric absent -- the WASDE Title-Case drift class)")


class _NumbersReg:
    """Numbers-registry shim carrying the ONE property the split depends on: agent id -> physical table
    (`silver_esr` serves from `silver_esr_compact`). `.get` raises for an unknown id, like the real
    Registry (`registry.py:246-249`)."""

    def __init__(self, specs):
        self.tables = {tid: types.SimpleNamespace(id=tid, athena_table=phys)
                       for tid, phys in specs.items()}

    def get(self, tid):
        if tid not in self.tables:
            raise KeyError(tid)
        return self.tables[tid]


_NUMBERS = _NumbersReg({"silver_cot": None, "silver_wasde": None, "silver_fred_fx": None,
                        "silver_esr": "silver_esr_compact", "silver_psd": None})


def _drift_ctx(gate_table, errs, monkeypatch, **kw):
    """A Branch-A context whose contract_check returns `errs`. query_fn is non-None so the stage runs.

    Every `gate_table` used below is a REAL member of `load_pg_numbers.P1_TABLES`, so `select_branch`
    routes it to Branch A off the live allowlist -- `select_branch`'s `pg_mirror` default binds at
    definition, so monkeypatching `g.PG_MIRROR_TABLES` would not move a table anyway."""
    import leviathan.graphrag.numbers.contract_check as cch
    assert gate_table in g.PG_MIRROR_TABLES, gate_table
    monkeypatch.setattr(cch, "contract_check", lambda reg=None, **k: list(errs))
    silver = _SilverReg({gate_table: {"consumers": "both"}})
    return silver, _ctx(silver, numbers_reg=_NUMBERS, query_fn=lambda *a, **k: [], **kw)


# ---------------------------------------------------------------------------
# (1) THE INCIDENT FIXTURE: one cot drift -> the fred family PASSES, the cot family FAILS.
# ---------------------------------------------------------------------------
def test_incident_20260803_cot_drift_warns_the_fred_family_and_reds_the_cot_family(monkeypatch):
    """D-PR-5 acceptance, replayed: the 2026-08-03 input with the fence removed yields PASS + a
    `global_drift` banner for silver_fred_fx and FAIL for a silver_cot-gating run.

    This is the whole item. Before the split BOTH runs exited 1 and BOTH paged, so the operator got three
    emails naming three innocent families and none of them named the table that actually drifted."""
    # -- the bystander: fx_macro_daily gates silver_fred_fx, which the cot drift does not implicate.
    _s, ctx = _drift_ctx("silver_fred_fx", [_COT_DRIFT], monkeypatch)
    bundle = g.run_gate(["silver_fred_fx"], ctx,
                        branch_a_stages=(_green("pg_reload"), g.stage_contract_check))
    assert bundle["verdict"] == "PASS", bundle["results"]
    assert bundle["banner"]["global_drift"] == 1 and bundle["banner"]["warn_tables"] == 1
    assert bundle["banner"]["red_tables"] == 0
    stage = [s for s in bundle["results"][0]["stages"] if s["name"] == "contract_check"][0]
    assert stage["status"] == g.WARN
    # NEVER SILENTLY DROPPED: the full text rides the bundle even though it no longer binds the verdict.
    assert stage["errors"] == [_COT_DRIFT] and stage["global_errors"] == [_COT_DRIFT]
    assert "silver_cot" in stage["detail"] and "global_drift" in stage["detail"]

    # -- the owner: the SAME error, on the family whose own table it names, is RED exactly as before.
    _s2, ctx2 = _drift_ctx("silver_cot", [_COT_DRIFT], monkeypatch)
    bundle2 = g.run_gate(["silver_cot"], ctx2,
                         branch_a_stages=(_green("pg_reload"), g.stage_contract_check))
    assert bundle2["verdict"] == "FAIL"
    assert bundle2["banner"]["global_drift"] == 0 and bundle2["banner"]["red_tables"] == 1
    stage2 = [s for s in bundle2["results"][0]["stages"] if s["name"] == "contract_check"][0]
    assert stage2["status"] == g.RED and stage2["errors"] == [_COT_DRIFT]


def test_incident_drift_is_red_for_every_family_when_the_split_is_rolled_back(monkeypatch):
    """The rollback lever is real: severity_split=False restores the pre-split verdict for the SAME input,
    so a rollback is an env flip on the jobdef (GATE_SEVERITY_SPLIT=0), not an image rebuild."""
    _s, ctx = _drift_ctx("silver_fred_fx", [_COT_DRIFT], monkeypatch, severity_split=False)
    bundle = g.run_gate(["silver_fred_fx"], ctx,
                        branch_a_stages=(_green("pg_reload"), g.stage_contract_check))
    assert bundle["verdict"] == "FAIL" and bundle["banner"]["global_drift"] == 0
    monkeypatch.delenv("GATE_SEVERITY_SPLIT", raising=False)
    assert g._severity_split_enabled() is True                       # unset -> ON (the ratified default)
    monkeypatch.setenv("GATE_SEVERITY_SPLIT", "0")
    assert g._severity_split_enabled() is False


def test_split_scopes_by_the_owning_table_not_by_the_contract(monkeypatch):
    """Attribution is by the TABLE the leg implicates, not by the contract that names the leg. The
    2026-08-03 drift rode `brazilian_arabica_coffee` legs, so scoping by contract would have redded the
    coffee families and cleared the cot family -- the exact inversion of what the gate must do."""
    for gate_table, expect in (("silver_cot", g.RED), ("silver_fred_fx", g.WARN),
                               ("silver_psd", g.WARN)):
        _s, ctx = _drift_ctx(gate_table, [_COT_DRIFT], monkeypatch)
        assert g.stage_contract_check(gate_table, ctx).status == expect, gate_table


def test_agent_id_and_physical_table_are_the_same_family(monkeypatch):
    """`silver_esr` serves from `silver_esr_compact` (contract_check._physical, :48-50), so ONE table has
    TWO names in the error stream and both must bind to the one family that owns it.

    Measured scope, so the fence is not oversold: no shipped emit carries the physical name ALONE today --
    the wide-metric family prints `{tid}: ... of {phys}` (`:96-97`) and every cascade_map row names an
    agent id (`cascade_map.yaml:238` is `table: silver_esr`), so the prefix would carry attribution by
    itself. The alias map is the fence for the emit that does not: a physical-only string must never
    false-clear the owning family, because a false CLEAR is the only direction of this split that can
    hurt. Both are pinned below."""
    assert g._gate_table_aliases("silver_esr", _NUMBERS) == frozenset({"silver_esr",
                                                                       "silver_esr_compact"})
    _s, ctx = _drift_ctx("silver_esr", [_ESR_DRIFT], monkeypatch)
    assert g.stage_contract_check("silver_esr", ctx).status == g.RED
    _s2, ctx2 = _drift_ctx("silver_cot", [_ESR_DRIFT], monkeypatch)
    assert g.stage_contract_check("silver_cot", ctx2).status == g.WARN

    # SYNTHETIC (no lint emits this shape today): the physical name with no agent-id prefix to fall back
    # on. Without the alias map this reds nobody and clears the owner.
    phys_only = ("wheat_cbot/esr_commitments: region-resolved country 'EU' not in DISTINCT country_code "
                 "of silver_esr_compact (region_map resolve target absent -- the France->EU class)")
    assert g.implicated_tables(phys_only) == frozenset({"silver_esr_compact"})
    _s3, ctx3 = _drift_ctx("silver_esr", [phys_only], monkeypatch)
    assert g.stage_contract_check("silver_esr", ctx3).status == g.RED


def test_mixed_drift_reds_on_its_own_error_and_still_carries_the_others(monkeypatch):
    """A family implicated by ONE of three errors is RED -- and the two it does not own are still counted
    and still printed in full. A red verdict must never cost the operator the rest of the evidence."""
    errs = [_COT_DRIFT, _WASDE_DRIFT, _ESR_DRIFT]
    _s, ctx = _drift_ctx("silver_wasde", errs, monkeypatch)
    res = g.stage_contract_check("silver_wasde", ctx)
    assert res.status == g.RED
    assert res.errors == errs                      # all three, untruncated
    assert sorted(res.global_errors) == sorted([_COT_DRIFT, _ESR_DRIFT])
    assert "+2 global_drift on other tables" in res.detail


# ---------------------------------------------------------------------------
# (2) THE INVARIANT: the split may NEVER change the verdict of a table whose OWN stages are red.
# ---------------------------------------------------------------------------
def test_invariant_own_red_stage_verdict_is_identical_with_and_without_the_split(monkeypatch):
    """The ratified invariant (D-PR-5). A table with a red stage of its own PLUS an unrelated global drift
    must produce the same verdict either way -- the split changes which errors are RED, never what RED
    means. Asserted on the whole bundle verdict AND on the per-table ok, both directions."""
    def _bundle(split):
        _s, ctx = _drift_ctx("silver_fred_fx", [_COT_DRIFT], monkeypatch, severity_split=split)
        return g.run_gate(["silver_fred_fx"], ctx,
                          branch_a_stages=(_green("pg_reload"), _red("parity"), g.stage_contract_check))

    with_split, without_split = _bundle(True), _bundle(False)
    assert with_split["verdict"] == without_split["verdict"] == "FAIL"
    assert with_split["results"][0]["ok"] is without_split["results"][0]["ok"] is False
    assert with_split["banner"]["red_tables"] == without_split["banner"]["red_tables"] == 1
    # ...and the table's OWN red stage is byte-identical under both, so the operator's first line is too.
    own = [[s for s in b["results"][0]["stages"] if s["name"] == "parity"][0]
           for b in (with_split, without_split)]
    assert json.dumps(own[0], sort_keys=True) == json.dumps(own[1], sort_keys=True)


def test_invariant_holds_when_the_drift_implicates_the_red_table_itself(monkeypatch):
    """The other half of the invariant: when the global drift DOES name this table, the split is a no-op on
    every stage, not just on the verdict."""
    def _stages(split):
        _s, ctx = _drift_ctx("silver_cot", [_COT_DRIFT], monkeypatch, severity_split=split)
        b = g.run_gate(["silver_cot"], ctx,
                       branch_a_stages=(_green("pg_reload"), _red("parity"), g.stage_contract_check))
        assert b["verdict"] == "FAIL"
        return {s["name"]: s["status"] for s in b["results"][0]["stages"]}

    assert _stages(True) == _stages(False)
    assert _stages(True)["contract_check"] == g.RED


def test_warn_alone_is_not_a_pass():
    """WARN is not a green. A table whose only non-skipped stage WARNed proved nothing about itself, so
    `ok` stays False -- the split must not become a back door around the all-skipped fail-closed rule."""
    silver = _SilverReg({"silver_cot": {"consumers": "feature_layer"}})
    res = g.run_table("silver_cot", _ctx(silver), branch_b_stages=(
        _skip("feature_probe"), _skip("value_census"),
        lambda t, c: g.StageResult("config_check", g.WARN, "elsewhere", errors=["x"],
                                   global_errors=["x"])))
    assert res.warned is True and res.ok is False


# ---------------------------------------------------------------------------
# (3) UNATTRIBUTABLE -> RED (the ratified fail-closed default).
# ---------------------------------------------------------------------------
def test_unattributable_contract_error_is_red_everywhere(monkeypatch):
    """An error string carrying no parseable table name cannot be charged to anyone, so it is charged to
    everyone. Fail-closed on ambiguity is this estate's doctrine (BaselineFetchError, and the
    empty-glob-is-an-ERROR rule at config_check.py:1614-1621); the split removes FALSE breadth, it does
    not invent narrowness the parser cannot justify."""
    opaque = "vocabulary drift detected during the mirror walk"
    assert g.implicated_tables(opaque) == frozenset()
    for gate_table in ("silver_cot", "silver_fred_fx", "silver_wasde"):
        _s, ctx = _drift_ctx(gate_table, [opaque], monkeypatch)
        res = g.stage_contract_check(gate_table, ctx)
        assert res.status == g.RED, gate_table
        assert res.errors == [opaque] and res.global_errors == []


def test_config_check_lint_label_is_never_read_as_a_table(monkeypatch):
    """`_run_config_check` emits `f"{label}: {e}"` (`:237-255`), which is prefix-shaped exactly like the
    wide-metric family. Reusing the contract parser here would read the LINT LABEL as a table id and
    demote a real estate-wide failure to WARN on 24 families. So config errors attribute ONLY through an
    explicit opt-in marker, and no lint emits one today -- class C's config half stays UNKILLED (D-PR-29),
    which is stated, not hidden."""
    err = "vocab: 3 slugs in entity_vocabulary.yaml have no hierarchy node"
    assert g.implicated_tables(err) == frozenset({"vocab"})     # the trap the strict attributor avoids
    assert g._config_implicated(err) == frozenset()             # ...and it does avoid it
    silver = _SilverReg({"silver_fred_fx": {"consumers": "both"}})
    monkeypatch.setattr(g, "_run_config_check", lambda: [err])
    res = g.stage_config_check("silver_fred_fx", _ctx(silver, numbers_reg=_NUMBERS))
    assert res.status == g.RED and res.errors == [err]


def test_config_check_marker_is_the_declared_opt_in_seam(monkeypatch):
    """The seam D-PR-29 needs: a lint that CAN name its table becomes attributable by saying so. Pinned so
    the convention cannot be silently changed by a later wave, and so the opt-in stays opt-in."""
    marked = "cascade_map: leg brazilian_arabica_coffee/cot_mm_positioning is not_covered [table=silver_cot]"
    assert g._config_implicated(marked) == frozenset({"silver_cot"})
    silver = _SilverReg({"silver_fred_fx": {"consumers": "both"}})
    monkeypatch.setattr(g, "_run_config_check", lambda: [marked])
    assert g.stage_config_check("silver_fred_fx", _ctx(silver, numbers_reg=_NUMBERS)).status == g.WARN
    assert g.stage_config_check("silver_cot", _ctx(silver, numbers_reg=_NUMBERS)).status == g.RED


def test_stage_exception_is_unattributable_and_stays_red(monkeypatch):
    """An exception is not an error STRING -- there is no leg, no table, and a check that crashed proved
    nothing about ANY table. All three global stages keep the fail-closed exception arm."""
    import leviathan.graphrag.numbers.contract_check as cch

    def _boom(*a, **k):
        raise RuntimeError("pg mirror relation does not exist")

    monkeypatch.setattr(cch, "contract_check", _boom)
    silver = _SilverReg({"silver_fred_fx": {"consumers": "both"}})
    ctx = _ctx(silver, numbers_reg=_NUMBERS, query_fn=lambda *a, **k: [])
    res = g.stage_contract_check("silver_fred_fx", ctx)
    assert res.status == g.RED and "RuntimeError" in res.detail and res.errors


# ---------------------------------------------------------------------------
# The census-diff partition (plan Section 2.5: NOT optional -- prior_dark is empty estate-wide, so the
# first dark leg introduced anywhere would otherwise red every family at once).
# ---------------------------------------------------------------------------
def _census_ctx(gate_table, current, monkeypatch, prior=None):
    import leviathan.graphrag.numbers.cascade_census as cc
    monkeypatch.setattr(cc, "census", lambda **k: current)
    silver = _SilverReg({gate_table: {"consumers": "both"}})
    return _ctx(silver, numbers_reg=_NUMBERS, query_fn=lambda *a, **k: [], prior_census=prior)


def test_census_new_dark_leg_is_attributed_but_stays_promote_blocking(monkeypatch):
    """ATTRIBUTION happens; the VERDICT does not move. See fence (B) and the blocking test block below:
    a census drift is the one global finding the SAME execution re-judges downstream, on a criterion
    (the ABSOLUTE dark count) that this stage's baseline diff cannot pass either. So the bystander gets
    the drift ATTRIBUTED to silver_psd in `global_errors` and in the detail -- and still goes RED, because
    exit 0 here would publish canonical into an execution that [Reconcile] then fails."""
    current = {"banner": {"athena_calls": 0, "dark": 1},
               "legs": [{"contract": "wheat_cbot", "node_id": "eu", "verdict": "DARK-WITH-REASON",
                         "table": "silver_psd", "metric": "exports", "reason": "country-not-a-psd-title"}]}
    owner = g.stage_cascade_census_diff("silver_psd", _census_ctx("silver_psd", current, monkeypatch))
    assert owner.status == g.RED and not owner.global_errors     # its own drift: never "somebody else's"
    bystander = g.stage_cascade_census_diff(
        "silver_fred_fx", _census_ctx("silver_fred_fx", current, monkeypatch))
    assert bystander.status == g.RED
    assert bystander.global_errors and "silver_psd" in bystander.global_errors[0]
    assert "PROMOTE-BLOCKING" in bystander.detail and "silver_psd" in bystander.detail


def test_census_athena_banner_is_unattributable_and_reds_everywhere(monkeypatch):
    """ATHENA_CALLS is a property of the census RUN, not of any leg's table: a leaked Athena scan is the
    LIST-storm class and must never be demoted to somebody else's problem."""
    current = {"banner": {"athena_calls": 3, "dark": 0}, "legs": []}
    for t in ("silver_psd", "silver_fred_fx"):
        res = g.stage_cascade_census_diff(t, _census_ctx(t, current, monkeypatch))
        assert res.status == g.RED and "ATHENA_CALLS=3" in res.detail, t


def test_census_dark_leg_without_a_table_is_unattributable(monkeypatch):
    current = {"banner": {"athena_calls": 0, "dark": 1},
               "legs": [{"contract": "cocoa", "node_id": "grind", "verdict": "DARK-WITH-REASON",
                         "reason": "no table on the row"}]}
    assert g.stage_cascade_census_diff(
        "silver_fred_fx", _census_ctx("silver_fred_fx", current, monkeypatch)).status == g.RED


def test_census_diff_text_view_is_unchanged():
    """`_census_diff` keeps its list[str] contract -- the attributed form is a strictly additive view."""
    current = {"banner": {"athena_calls": 0},
               "legs": [{"contract": "wheat_cbot", "node_id": "eu", "verdict": "DARK-WITH-REASON",
                         "table": "silver_psd", "metric": "exports", "reason": "r"}]}
    texts = g._census_diff(None, current)
    assert texts == [t for t, _ in g._census_diff_attributed(None, current)]
    assert all(isinstance(t, str) for t in texts)


# ---------------------------------------------------------------------------
# D-PR-32 (the PRECONDITION): the bundle carries every error, untruncated.
# ---------------------------------------------------------------------------
def test_full_error_list_survives_the_five_error_detail_truncation(monkeypatch):
    """`detail` has always summarised at `errs[:5]`. Under the split a truncated WARN would ride a PASS
    instead of a promote-blocking RED, so an error past the fifth would vanish from every downstream
    reader. The bundle now carries the untruncated list and a count."""
    errs = [_COT_DRIFT.replace("cot_mm_positioning", f"leg_{i}") for i in range(7)]
    _s, ctx = _drift_ctx("silver_fred_fx", errs, monkeypatch)
    bundle = g.run_gate(["silver_fred_fx"], ctx,
                        branch_a_stages=(_green("pg_reload"), g.stage_contract_check))
    stage = [s for s in bundle["results"][0]["stages"] if s["name"] == "contract_check"][0]
    assert stage["error_count"] == 7 and stage["errors"] == errs
    assert stage["detail"].count("leg_") == 5           # the human summary is still capped at five
    assert json.loads(json.dumps(bundle))["banner"]["global_drift"] == 1   # bundle stays JSON-serializable


def test_clean_stage_dict_keeps_exactly_the_legacy_keys():
    """Backward compatibility, pinned: a green/skipped stage serializes to the same three keys it always
    did, so the SFN, reports/ tree and any dashboard reading these bundles are untouched by this wave."""
    assert set(g.StageResult("parity", g.GREEN, "clean").to_dict()) == {"name", "status", "detail"}
    assert set(g.StageResult("x", g.RED, "d", errors=["e"]).to_dict()) == {
        "name", "status", "detail", "error_count", "errors"}


def test_main_exits_zero_and_prints_a_grepable_warn_line(monkeypatch, capsys, tmp_path):
    """END TO END through main(), on the REAL Branch-A stage tuple: the fred family promotes (exit 0) over
    the cot drift, and the drift is still on stdout.

    A WARN is exit 0 -> no SFN failure -> no FailNotify -> no alarm, so the container log is its ONLY
    delivery mechanism today. The metric + alarm half is D-PR-28 and is explicitly NOT in this item; this
    test pins the one channel that does exist so the split cannot become silent."""
    import leviathan.graphrag.numbers.cascade_census as cc

    _s, ctx = _drift_ctx("silver_fred_fx", [_COT_DRIFT], monkeypatch,
                         value_census_fn=lambda t, reg: {"ok": True})
    monkeypatch.setattr(cc, "census", lambda **k: {"banner": {"athena_calls": 0, "dark": 0}, "legs": []})
    monkeypatch.setattr(g, "_run_config_check", lambda: [])
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})
    monkeypatch.setattr(g, "_build_live_context", lambda tables, **k: ctx)

    out_path = tmp_path / "bundle.json"
    rc = g.main(["--tables", "silver_fred_fx", "--json", str(out_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert out.isascii()                                    # cp1252 console -- ASCII-only stdout
    assert "WARN silver_fred_fx" in out and "global_drift=1" in out
    bundle = json.loads(out_path.read_text(encoding="utf-8"))
    assert bundle["verdict"] == "PASS" and bundle["banner"]["global_drift"] == 1
    stage = [s for s in bundle["results"][0]["stages"] if s["name"] == "contract_check"][0]
    assert stage["status"] == g.WARN and stage["errors"] == [_COT_DRIFT]
    # pg_reload/parity SKIP without a conn; the V001 floor is the GREEN that makes the pass a real pass.
    by = {s["name"]: s["status"] for s in bundle["results"][0]["stages"]}
    assert by["value_census"] == g.GREEN and by["pg_reload"] == g.SKIPPED


# =========================================================================================================
# FENCE (A) -- THE ORPHAN FENCE. A drift implicating a table NO family gates goes RED estate-wide.
#
# The set the checks WALK is not the set the schedules GATE. `contract_check` walks the numbers registry
# (`contract_check._numbers_table_ids` -- every registry table minus the projection trio); ownership is
# declared only by the 26 `configs/silver/dags/*.json` descriptors' `gate_tables`. The difference is not
# empty, so "charge the drift to the family that owns it" had a hole: a drift on an UNOWNED table is
# charged to nobody -- WARN on all 41 gated tables, RED on none, exit 0 everywhere, no alarm.
# =========================================================================================================
# The measured orphan roster, pinned BY NAME (the estate's convention: an integer pin says a table moved,
# never WHICH). gold_pattern_records is in the C002 walk and in nobody's gate_tables.
_EXPECTED_ORPHANS = frozenset({"gold_pattern_records"})


def test_the_c002_walk_set_is_wider_than_the_owned_set_and_the_orphan_is_named():
    """The measurement the fence exists for -- asserted against the LIVE registry and the LIVE descriptors,
    so it re-measures on every run rather than trusting a number written down on 2026-08-04."""
    from leviathan.graphrag.numbers import contract_check as cch
    from leviathan.graphrag.numbers.registry import load_registry

    walked = set(cch._numbers_table_ids(load_registry()))
    owned = g.gated_tables()
    assert owned is not None, "the dag descriptors must be readable from the repo/image tree"
    assert len(owned) >= 40, len(owned)     # a partial read would show up as invented orphans below
    assert walked - owned == set(_EXPECTED_ORPHANS), {
        "new_orphans": sorted(walked - owned - _EXPECTED_ORPHANS),
        "orphans_that_gained_an_owner": sorted(_EXPECTED_ORPHANS - (walked - owned)),
        "why_this_matters": "a C002-walked table absent from every family's gate_tables is checked by "
                            "26 gate runs and OWNED by none of them -- under the severity split its "
                            "drift would WARN on all 41 gated tables and red nobody. Adding it to a "
                            "family's gate_tables is the fix; widening this roster is not"}


def test_gated_tables_reads_the_descriptors_and_ignores_the_schema_and_rendered_payloads(tmp_path):
    """`gate_tables` comes from the DESCRIPTORS only. The rendered execution payloads live in
    `_rendered/` (a non-recursive glob never reaches them) and `dag_descriptor.schema.json` is the
    schema, not a family -- reading either as a descriptor would invent ownership that does not exist."""
    owned = g.gated_tables()
    assert {"silver_fred_fx", "silver_cot", "silver_wasde", "silver_psd"} <= owned
    assert "gold_pattern_records" not in owned

    (tmp_path / "_rendered").mkdir()
    (tmp_path / "_rendered" / "a.input.json").write_text(
        json.dumps({"gate_tables": ["silver_never_owned"]}), encoding="utf-8")
    (tmp_path / "dag_descriptor.schema.json").write_text(
        json.dumps({"gate_tables": ["silver_from_the_schema"]}), encoding="utf-8")
    (tmp_path / "fam.json").write_text(json.dumps({"gate_tables": ["silver_a", "silver_b"]}),
                                       encoding="utf-8")
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")   # skipped, never raises
    assert g.gated_tables(tmp_path) == frozenset({"silver_a", "silver_b"})


def test_gated_tables_is_none_when_ownership_cannot_be_established(tmp_path):
    """None is 'nobody owns anything', not 'no orphans' -- an empty/absent descriptor tree must not read
    as a clean bill of health."""
    assert g.gated_tables(tmp_path / "does-not-exist") is None
    (tmp_path / "no_gate_tables.json").write_text(json.dumps({"family": "x"}), encoding="utf-8")
    assert g.gated_tables(tmp_path) is None


# The shape contract_check's wide-metric family emits (`contract_check.py:96-97`), pointed at the one
# table the measurement above proves is unowned. gold_pattern_records declares zero metrics TODAY, so
# this exact string cannot fire yet -- the T2b writer upgrade (graded quantified firings) is what adds
# them, and the fence must already be standing when it does. The STRUCTURAL gap is what is pinned above;
# this is the emit that would ride it.
_ORPHAN_DRIFT = ("gold_pattern_records: metric column 'firing_rate' is not a physical column of "
                 "gold_pattern_records (declared wide metric absent -- the WASDE Title-Case drift class)")


def test_drift_on_an_unowned_table_is_red_for_every_gated_family(monkeypatch):
    """THE FENCE. No family's gate_tables lists gold_pattern_records, so no family would ever red for it:
    moving the error off this family's verdict moves it onto NOBODY's. Fail-closed -- RED everywhere."""
    assert g.implicated_tables(_ORPHAN_DRIFT) == frozenset({"gold_pattern_records"})
    for gate_table in ("silver_cot", "silver_fred_fx", "silver_wasde", "silver_psd"):
        _s, ctx = _drift_ctx(gate_table, [_ORPHAN_DRIFT], monkeypatch)
        res = g.stage_contract_check(gate_table, ctx)
        assert res.status == g.RED, gate_table
        assert res.errors == [_ORPHAN_DRIFT] and res.global_errors == []


def test_an_owned_table_in_the_same_error_defeats_the_orphan_rule(monkeypatch):
    """Precision, not a blunt instrument: an error naming an orphan AND an owned table is NOT orphaned --
    the owning family still reds, so the drift is not promoted over silently and the bystanders keep the
    split's benefit. Over-redding here would quietly undo the whole item."""
    mixed = ("gold_pattern_records: commodity slug 'x' not in DISTINCT leviathan_slug of silver_cot "
             "(commodity-slug-miss -- the PSD_SLUG_ALIAS class)")
    assert g.implicated_tables(mixed) == frozenset({"gold_pattern_records", "silver_cot"})
    _s, ctx = _drift_ctx("silver_fred_fx", [mixed], monkeypatch)
    assert g.stage_contract_check("silver_fred_fx", ctx).status == g.WARN
    _s2, ctx2 = _drift_ctx("silver_cot", [mixed], monkeypatch)
    assert g.stage_contract_check("silver_cot", ctx2).status == g.RED


def test_unreadable_ownership_map_charges_every_error_to_this_table(monkeypatch):
    """If the gate cannot read WHO OWNS WHAT it cannot narrow anything, so it narrows nothing. An image
    built without configs/silver/dags (the gitignored-configs class that has bitten this estate before)
    degrades to the pre-split verdict -- loud -- rather than to a silent estate-wide WARN."""
    monkeypatch.setattr(g, "gated_tables", lambda *a, **k: None)
    _s, ctx = _drift_ctx("silver_fred_fx", [_COT_DRIFT], monkeypatch)
    res = g.stage_contract_check("silver_fred_fx", ctx)
    assert res.status == g.RED and res.errors == [_COT_DRIFT] and res.global_errors == []


def test_split_by_blast_radius_orphan_arm_is_directly_pinned():
    """The partitioner's three RED arms in one place: mine / unattributable / orphan-only."""
    items = [("mine", frozenset({"silver_cot"})), ("bystander", frozenset({"silver_wasde"})),
             ("opaque", frozenset()), ("orphan", frozenset({"gold_pattern_records"}))]
    owned = frozenset({"silver_cot", "silver_wasde"})
    mine, others = g.split_by_blast_radius(items, {"silver_cot"}, owned)
    assert mine == ["mine", "opaque", "orphan"] and others == ["bystander"]
    # owned=None -> nobody owns anything -> everything is this table's problem.
    assert g.split_by_blast_radius(items, {"silver_cot"}, None)[1] == []


# =========================================================================================================
# FENCE (B) -- THE EXIT CODE AND THE PROMOTE DECISION ARE ONE VERDICT.
#
# The SFN reads the gate's EXIT CODE only (`step_functions/main.tf:38-40`) and `Gate.Next = "Promote"` is
# unconditional (`:176`), so exit 0 PUBLISHES CANONICAL. [Reconcile] then runs advance_rolling_census ->
# `cascade_census.main`, whose criterion is the ABSOLUTE un-waived DARK count (`cascade_census.py:623`),
# not this gate's baseline diff -- so a demoted census drift published canonical and THEN failed the
# execution, while [FailNotify] said "Canonical left untouched (INV-6)".
# =========================================================================================================
def _main_run(monkeypatch, tmp_path, *, gate_table, contract_errs=(), census=None, name="bundle.json"):
    """Drive main() end-to-end on the REAL Branch-A stage tuple with pg/S3/Batch fully mocked."""
    import leviathan.graphrag.numbers.cascade_census as cc

    _s, ctx = _drift_ctx(gate_table, list(contract_errs), monkeypatch,
                         value_census_fn=lambda t, reg: {"ok": True})
    monkeypatch.setattr(cc, "census",
                        lambda **k: census or {"banner": {"athena_calls": 0, "dark": 0}, "legs": []})
    monkeypatch.setattr(g, "_run_config_check", lambda: [])
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})
    monkeypatch.setattr(g, "_build_live_context", lambda tables, **k: ctx)
    out_path = tmp_path / name
    rc = g.main(["--tables", gate_table, "--json", str(out_path)])
    return rc, json.loads(out_path.read_text(encoding="utf-8"))


_PSD_DARK_CENSUS = {"banner": {"athena_calls": 0, "dark": 1},
                    "legs": [{"contract": "wheat_cbot", "node_id": "eu",
                              "verdict": "DARK-WITH-REASON", "table": "silver_psd",
                              "metric": "exports", "reason": "country-not-a-psd-title"}]}


def test_a_census_drift_on_another_table_never_promotes_canonical(monkeypatch, tmp_path, capsys):
    """The HIGH, end to end. A NEW un-waived dark leg on silver_psd while fx_macro_daily's gate runs:
    the gate exits NONZERO, so [Gate] raises States.TaskFailed -> Catch -> [FailNotify] and [Promote] is
    never entered (INV-6). The alert's "Canonical left untouched" is true again."""
    rc, bundle = _main_run(monkeypatch, tmp_path, gate_table="silver_fred_fx",
                           census=_PSD_DARK_CENSUS)
    assert rc == 1
    assert bundle["verdict"] == "FAIL" and bundle["banner"]["red_tables"] == 1
    assert bundle["banner"]["global_drift"] == 0 and bundle["banner"]["warn_tables"] == 0
    stage = [s for s in bundle["results"][0]["stages"] if s["name"] == "cascade_census_diff"][0]
    assert stage["status"] == g.RED
    # ...and the operator is still told WHOSE drift it is, on stdout, without opening a bundle.
    out = capsys.readouterr().out
    assert "FAIL silver_fred_fx" in out and "silver_psd" in out and "PROMOTE-BLOCKING" in out
    assert out.isascii()


def test_exit_code_and_bundle_verdict_are_the_same_verdict_on_every_arm(monkeypatch, tmp_path):
    """The invariant the fix must hold: rc==0 IFF the bundle says PASS. There is no arm where the gate
    exits 0 (-> canonical publishes) while the run's own verdict, or the execution's, is a failure."""
    for i, (errs, census, want_rc) in enumerate((
            ((), None, 0),                                   # clean
            (( _COT_DRIFT,), None, 0),                       # somebody else's VOCAB drift -> promotes
            ((), _PSD_DARK_CENSUS, 1),                       # somebody else's CENSUS drift -> blocks
            ((_COT_DRIFT,), _PSD_DARK_CENSUS, 1),            # both
    )):
        rc, bundle = _main_run(monkeypatch, tmp_path, gate_table="silver_fred_fx",
                               contract_errs=errs, census=census, name=f"b{i}.json")
        assert rc == want_rc, (i, bundle["results"])
        assert (rc == 0) is (bundle["verdict"] == "PASS"), (i, rc, bundle["verdict"])


def test_a_vocabulary_warn_still_promotes_because_reconcile_does_not_recheck_it(monkeypatch, tmp_path):
    """The split's benefit is NOT thrown away. [Reconcile] runs the census and only the census, so a
    contract_check drift on another table has no downstream re-judgement to contradict -- it stays a WARN
    and the bystander family still promotes. Only the stage the execution re-judges is blocking."""
    rc, bundle = _main_run(monkeypatch, tmp_path, gate_table="silver_fred_fx",
                           contract_errs=[_COT_DRIFT])
    assert rc == 0 and bundle["verdict"] == "PASS"
    assert bundle["banner"]["global_drift"] == 1 and bundle["banner"]["warn_tables"] == 1
    assert [s for s in bundle["results"][0]["stages"]
            if s["name"] == "contract_check"][0]["status"] == g.WARN


def test_census_blocking_survives_the_rollback_lever(monkeypatch, tmp_path):
    """GATE_SEVERITY_SPLIT=0 restores the pre-split verdict, which was ALSO red here -- so the rollback
    lever cannot be used to reopen the publish-then-fail window in either direction."""
    import leviathan.graphrag.numbers.cascade_census as cc
    monkeypatch.setattr(cc, "census", lambda **k: _PSD_DARK_CENSUS)
    for split in (True, False):
        _s, ctx = _drift_ctx("silver_fred_fx", [], monkeypatch, severity_split=split)
        assert g.stage_cascade_census_diff("silver_fred_fx", ctx).status == g.RED, split


# =========================================================================================================
# D-PR-32 ON THE SCHEDULED PATH -- the bundle is not a delivery mechanism; stdout is.
# =========================================================================================================
def test_no_scheduled_gate_command_carries_json_so_stdout_is_the_only_record():
    """WHY the stdout rule exists, measured against the rendered execution payloads that actually run.
    None of them passes --json, so the bundle is written INSIDE the Batch container to
    reports/silver_readiness/... and nothing uploads it. If a drift is not on stdout it is not anywhere."""
    rendered = sorted((g._REPO_ROOT / "configs" / "silver" / "dags" / "_rendered")
                      .glob("*.input.json"))
    assert len(rendered) == 26, len(rendered)
    with_json = [p.name for p in rendered
                 if "--json" in json.loads(p.read_text(encoding="utf-8"))["gate"]["command"]]
    assert with_json == [], with_json


def test_every_warn_error_reaches_stdout_untruncated(monkeypatch, tmp_path, capsys):
    """`detail` stops at five. With seven drifts the sixth and seventh existed ONLY in a bundle nobody
    uploads -- on an exit-0 PASS run, where before the split the same content at least rode an exit-1
    that paged. Every error must be on stdout, one per line, on the WARN path."""
    errs = [_COT_DRIFT.replace("cot_mm_positioning", f"leg_{i}") for i in range(7)]
    rc, bundle = _main_run(monkeypatch, tmp_path, gate_table="silver_fred_fx", contract_errs=errs)
    out = capsys.readouterr().out
    assert rc == 0 and bundle["verdict"] == "PASS"
    assert out.isascii()
    for i, e in enumerate(errs):
        assert e in out, f"drift {i} never reached the job log"
        assert f"error {i + 1}/7" in out
    assert out.count("leg_6") >= 1                      # the one `detail` truncation always dropped


def test_every_red_error_reaches_stdout_untruncated(monkeypatch, tmp_path, capsys):
    """Same guarantee on the RED path: the FAIL summary line is also an `errs[:5]` join, and a paging
    failure whose sixth cause is invisible is the same defect wearing a louder hat."""
    errs = [_WASDE_DRIFT.replace("Ending Stocks", f"Metric {i}") for i in range(7)]
    rc, bundle = _main_run(monkeypatch, tmp_path, gate_table="silver_wasde", contract_errs=errs)
    out = capsys.readouterr().out
    assert rc == 1 and bundle["verdict"] == "FAIL"
    for i, e in enumerate(errs):
        assert e in out, f"drift {i} never reached the job log"
        assert f"error {i + 1}/7" in out


def test_a_single_error_is_not_printed_twice(monkeypatch, tmp_path, capsys):
    """The common case stays quiet: one error is already the whole of `detail`, so the per-error lines
    only appear when `detail` actually dropped something."""
    rc, _b = _main_run(monkeypatch, tmp_path, gate_table="silver_fred_fx", contract_errs=[_COT_DRIFT])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.count(_COT_DRIFT) == 1 and "error 1/1" not in out


def test_main_no_baseline_is_unset_not_empty_string(monkeypatch):
    """With neither the flag nor the env var, _build_live_context receives baseline_uri=None (unset),
    so the legacy image-baked path is taken. Use raise_after_capture to short-circuit before run_gate."""
    store = {}
    monkeypatch.delenv("CENSUS_BASELINE_S3", raising=False)
    monkeypatch.setattr(g, "_build_live_context", _capture_build_live_context(store))
    # baseline_uri is None here, so main()'s except BaselineFetchError is inert to that resolution; the
    # stub still raises BaselineFetchError to avoid run_gate, but we only assert the resolved value.
    g.main(["--tables", "silver_wasde"])
    assert store["baseline_uri"] is None
