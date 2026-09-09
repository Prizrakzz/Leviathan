"""THE BOARD CENSUS, ONE DECK PER FINDING CLOSED -- injected fakes only, no pg, no network.

WHY A SECOND FILE. ``test_state_census.py`` proves the census's own claims. This file proves the
claims the FIRST review found the census making FALSELY: a probe that read a table which does not
exist on the mirror and still printed the clean verdict, and a probe half that ran zero checks and
reported agreement. Every deck here is written to FAIL against the code as it stood, so a later
edit that reintroduces either shape is caught by a test whose name says which finding it was.

THE TWO MAJORS, in one line each:

  * ``destination_census`` built ``FROM leviathan_dev.<registry id>``. ``silver_esr``'s physical table
    is ``silver_esr_compact`` (``registry.athena_table``), so 8 of the 11 destination-grain series
    raised UndefinedTable into ``rec['error']`` -- and because ``at_cap`` can only count rows that
    carry the key, the verdict read "no ESR / FGIS series reaches the 5,000-row cap" over the series
    it never read. That is the exact figure Appendix B built the probe for.
  * P5's ``_anom_column`` tried ``dmi`` and the live IOD card serves ``dmi_value``, so the column
    resolved to None, every cell was None, and ``_lag_witness`` returned ``checked: 0`` beside the
    words "agree everywhere". The lag column on that card is ALSO a shift of the 3-month MEAN rather
    than of the anomaly, so simply resolving the column would have traded a vacuous pass for a
    fabricated whole-series mismatch -- both shapes are fenced below.
"""
from __future__ import annotations

import json

from leviathan.graphrag.state import board_census as BC


# ---------------------------------------------------------------------------------------------------
# THE IOD FIXTURE -- the LIVE card's own columns
# ---------------------------------------------------------------------------------------------------
def _iod_card_rows(revise=None, *, drop_value_column: bool = False) -> list:
    """Rows shaped like ``sql/athena/ddl/silver_noaa_iod.sql``: year, month, date, dmi_value,
    iod_dmi_3month_avg, iod_phase, iod_dmi_ethiopia_lag4, source.

    THE LAG COLUMN IS A SHIFT OF THE 3-MONTH MEAN, not of ``dmi_value``
    (``transforms/bronze_to_silver/noaa_iod.py``: "the lag here is applied against the already
    3-month-smoothed series"). A witness that compared it against the anomaly column would disagree
    on nearly every row of this clean fixture -- the false finding the deck below fences."""
    dmi: dict = {}
    avg: dict = {}
    rows: list = []
    for i in range(1, 25):
        y, m = 2025 + (i - 1) // 12, (i - 1) % 12 + 1
        dmi[f"{y:04d}-{m:02d}"] = round(0.05 * i, 4)
    ks = sorted(dmi)
    for j, k in enumerate(ks):
        w = [dmi[x] for x in ks[max(0, j - 2):j + 1]]
        avg[k] = round(sum(w) / len(w), 6) if len(w) >= 2 else None
    for k in ks:
        y, m = int(k[:4]), int(k[5:])
        lag = avg.get(BC._shift_month(y, m, -4))
        if revise and k in revise:
            lag = revise[k]
        row = {"year": y, "month": m, "date": k + "-01", "dmi_value": dmi[k],
               "iod_dmi_3month_avg": avg[k], "iod_phase": "positive",
               "iod_dmi_ethiopia_lag4": lag, "source": "hadisst"}
        if drop_value_column:
            row.pop("dmi_value")
        rows.append(row)
    return rows


def _iod_qfn(**kw):
    return lambda sql: (_iod_card_rows(**kw) if "iod" in sql else [])


# ---------------------------------------------------------------------------------------------------
# MAJOR 1 -- the destination census read a table that does not exist on the mirror
# ---------------------------------------------------------------------------------------------------
def test_destination_census_reads_the_physical_table_not_the_registry_id():
    """``silver_esr`` is the AGENT-FACING id; the physical Glue table -- and so the pg mirror's --
    is ``silver_esr_compact``. Every other read path in the tree resolves it the same way
    (``query.py`` ``ts.athena_table or spec.table``; ``load_pg_numbers.py`` ``physical =
    ts.athena_table or ts.id``)."""
    from leviathan.graphrag.numbers.registry import load_registry

    graph = BC.load_graph()
    seen: list = []
    got = BC.destination_census(
        graph, "2026-09-07",
        qfn=lambda sql: (seen.append(sql), [{"n": 12, "destinations": 4}])[1])
    reg = load_registry()
    assert seen, "the estate maps at least one destination-grain series"
    assert reg.get("silver_esr").athena_table == "silver_esr_compact", \
        "the card this whole deck rests on"

    esr = [r for r in got["rows"] if r["table"] == "silver_esr"]
    assert esr, "the estate maps ESR destination-grain series"
    for r in esr:
        assert r["physical_table"] == "silver_esr_compact"
    froms = {s.split(" FROM ")[1].split(" WHERE")[0].strip() for s in seen}
    assert "leviathan_dev.silver_esr_compact" in froms
    assert "leviathan_dev.silver_esr" not in froms, \
        "the registry id is not a table on the mirror; a read of it is an UndefinedTable"
    for r in got["rows"]:
        assert r["physical_table"] == (reg.get(r["table"]).athena_table or r["table"])


def test_destination_census_declines_by_name_when_a_series_could_not_be_read():
    """``at_cap`` can only ever count rows that CARRY the key, so a read that raised is invisible to
    it and the probe printed the clean verdict over series it never measured."""
    graph = BC.load_graph()

    def qfn(sql):
        if "silver_esr_compact" in sql:
            raise RuntimeError("UndefinedTable: relation silver_esr_compact does not exist")
        return [{"n": 40, "destinations": 6}]

    got = BC.destination_census(graph, "2026-09-07", qfn=qfn)
    assert got["errors"], "a read that raised is a FINDING the artifact carries"
    assert got["measured"] < got["series"]
    assert got["verdict"].startswith("DECLINED")
    assert "UNMEASURED" in got["verdict"]
    assert "no ESR / FGIS series reaches" not in got["verdict"], \
        "an unread series is not a series under its cap"
    assert all(e["table"] and e["error"] for e in got["errors"])


def test_destination_census_still_names_a_series_that_reads_at_its_cap():
    graph = BC.load_graph()
    got = BC.destination_census(graph, "2026-09-07",
                                qfn=lambda sql: [{"n": 5000, "destinations": 61}])
    assert got["errors"] == []
    assert got["at_cap"], "a read that comes back at its cap MUST be named, not averaged away"
    assert "truncate silently" in got["verdict"]


def test_the_settled_destination_row_carries_what_it_could_not_read():
    """The settled table is the half a reader quotes: a headroom over 3 of 11 series must never
    appear there without the 8 it could not read."""
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=BC.PROBES_OFFLINE, cascade_legs=False)
    row = art["summary"]["settled"]["esr_fgis_destination_counts"]
    assert "unread" in row["measured"] and "read" in row["measured"]
    assert row["state"].startswith("NOT RUN"), \
        "the offline pass cannot read the mirror and the settled row must say so"


# ---------------------------------------------------------------------------------------------------
# MAJOR 2 -- P5's IOD half ran zero checks and reported agreement
# ---------------------------------------------------------------------------------------------------
def test_anom_column_resolves_the_iod_cards_own_value_column():
    rows = _iod_card_rows()
    assert BC._anom_column(rows) == "dmi_value"
    assert BC._anom_column(
        [{"year": 2026, "month": 1, "oni_anom": 0.5, "oni_lag3": 0.2}]) == "oni_anom"
    # BACK-COMPAT with the shapes the first deck already fenced
    assert BC._anom_column([{"year": 2026, "month": 3, "dmi": -0.7}]) == "dmi"
    assert BC._anom_column([{"year": 2026, "month": 3, "iod_index": 0.1}]) == "iod_index"
    assert BC._anom_column([]) is None


def test_anom_column_never_picks_a_derived_column():
    """A rolling mean or a lagged copy is not the card's anomaly: a snapshot built on one could not
    be diffed against the source's own revision."""
    rows = [{"year": 2026, "month": 1, "iod_dmi_3month_avg": 0.4,
             "iod_dmi_ethiopia_lag4": 0.1, "iod_phase": "positive"}]
    assert BC._anom_column(rows) is None, \
        "None is the honest answer here, not the smoothed series"


def test_lag_witness_refuses_to_report_agreement_when_no_anomaly_column_resolved():
    """``available: True, checked: 0`` beside the words "agree everywhere" is a clean verdict over
    zero comparisons -- the absence-vs-silence confusion this package refuses everywhere else."""
    rows = _iod_card_rows(drop_value_column=True)
    lw = BC._lag_witness(rows, {}, "silver_noaa_iod", anom_col=None)
    assert lw["available"] is False
    assert "no anomaly column resolved" in lw["why"]
    assert not lw.get("checked")
    assert "agree" not in json.dumps(lw)


def test_lag_witness_compares_each_lag_column_against_the_column_it_is_a_shift_of():
    """``iod_dmi_ethiopia_lag4`` is ``iod_dmi_3month_avg`` shifted 4, NOT ``dmi_value`` shifted 4.
    A witness that compared it against the anomaly column would report a whole-series revision that
    is arithmetic, not a revision at all."""
    rows = _iod_card_rows()
    series = {f"{r['year']:04d}-{r['month']:02d}": r["dmi_value"] for r in rows}
    lw = BC._lag_witness(rows, series, "silver_noaa_iod", anom_col="dmi_value")
    assert lw["available"] is True
    assert lw["bases"] == {"iod_dmi_ethiopia_lag4": "iod_dmi_3month_avg"}
    assert lw["checked"] > 0
    assert lw["mismatches"] == 0, "this fixture is ONE clean load; a mismatch here is a false finding"
    assert lw["unmapped"] == []
    assert "NOT proof" in lw["reading"]

    # AND THE WITNESS STILL BITES: an in-place revision of that column is caught.
    dirty = _iod_card_rows(revise={"2026-06": 9.99})
    bad = BC._lag_witness(dirty, series, "silver_noaa_iod", anom_col="dmi_value")
    assert bad["mismatches"] == 1
    assert bad["examples"][0]["base_column"] == "iod_dmi_3month_avg"
    assert bad["max_delta"] > 9.0


def test_lag_witness_reports_an_unmapped_lag_column_rather_than_guessing_its_base():
    rows = [{"year": 2026, "month": m, "thing_anom": 0.1 * m, "mystery_lag2": 0.9}
            for m in range(1, 13)]
    lw = BC._lag_witness(rows, {}, "silver_made_up", anom_col="thing_anom")
    assert lw["available"] is False
    assert lw["unmapped"] == ["mystery_lag2"]
    assert "not a witness" in lw["why"]


def test_lag_base_column_falls_back_to_the_name_rule_for_an_undeclared_card():
    keys = ["year", "month", "temp_anom", "temp_anom_lag3"]
    assert BC._lag_base_column("silver_new_card", "temp_anom_lag3", keys) == "temp_anom"
    assert BC._lag_base_column("silver_new_card", "temp_anom_lag9", ["year", "month"]) is None
    # THE DECLARED MAP WINS, and it is what resolves today's two cards.
    assert BC.LAG_BASE_COLUMNS["silver_noaa_oni"]["oni_lag6"] == "oni_anom"
    assert BC.LAG_BASE_COLUMNS["silver_noaa_iod"]["iod_dmi_ethiopia_lag4"] == "iod_dmi_3month_avg"


def test_p5_measures_the_iod_half_and_names_the_card_it_could_not_read():
    got = BC.probe_p5("2026-09-07", qfn=_iod_qfn())
    iod = got["tables"]["silver_noaa_iod"]
    assert iod["value_column"] == "dmi_value"
    assert iod["non_null_values"] == iod["n_periods"] > 0
    assert iod.get("declined") is None
    assert iod["lag_witness"]["available"] is True and iod["lag_witness"]["checked"] > 0
    # THE OTHER CARD RETURNED NOTHING on this fixture, and the verdict must SAY so rather than
    # rolling an unmeasured card into a sentence about agreement.
    oni = got["tables"]["silver_noaa_oni"]
    assert oni["declined"] == "no_rows"
    assert "silver_noaa_oni: UNMEASURED" in got["verdict"]
    assert "silver_noaa_iod: 0 lag-column mismatch" in got["verdict"]


def test_p5_declines_the_prior_diff_rather_than_comparing_two_walls_of_nulls():
    """A snapshot with no values diffs to ``changed: 0, max_magnitude: 0.0`` -- a clean number over
    nothing that the artifact would carry as "no revision"."""
    nulls = {f"2026-{m:02d}": None for m in range(1, 13)}
    real = {f"2026-{m:02d}": 0.1 * m for m in range(1, 13)}
    got = BC._prior_diff(nulls, {"hash": "deadbeef", "snapshot": real})
    assert got["compared"] is False and "no value column" in got["why"]
    other = BC._prior_diff(real, {"hash": "x", "snapshot": nulls})
    assert other["compared"] is False and "PRIOR vintage" in other["why"]


# ---------------------------------------------------------------------------------------------------
# THE MINORS -- the counter, the checkpoint, the alternative pass, the settled state word
# ---------------------------------------------------------------------------------------------------
def test_the_tape_reader_reads_through_the_census_counter():
    """A fresh ``board_query_fn()`` per call read the mirror behind the executor's back: the
    per-board ledger stayed right and the estate banner undercounted by one read per tape board."""
    from leviathan.graphrag.state import feeders as F

    counter = BC.CountingExecutor(lambda sql: [], name="t")
    seen: dict = {}

    def fake_tape_state(slug, asof, qfn=None):
        seen["qfn"] = qfn
        return None

    real = F.tape_state
    try:
        F.tape_state = fake_tape_state
        BC._pg_tape_fn(counter)("soybeans_cbot", "2026-09-07")
        assert seen["qfn"] is counter, "the tape's reads land on the census's own executor"
    finally:
        F.tape_state = real


def test_the_checkpoint_banks_the_boards_before_the_first_probe_runs(tmp_path, monkeypatch):
    """144 board runs, then every probe, then the leg census, then the write: an attemptDuration
    kill or a put_object failure took the whole run down with it."""
    order: list = []
    real_p3 = BC.probe_p3

    def watched_p3(graph):
        order.append("probe")
        return real_p3(graph)

    def checkpoint(boards, keys):
        order.append("checkpoint")
        BC.write_checkpoint(boards, keys, "2026-09-07", out_dir=tmp_path)

    monkeypatch.setattr(BC, "probe_p3", watched_p3)
    BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
              state_fn_factory=BC._fixture_state_fn_factory,
              modes=("quick",), contracts=["soybeans_cbot"], alternative_pass="",
              probes=("P3",), cascade_legs=False, checkpoint=checkpoint)
    assert order == ["checkpoint", "probe"], "the boards are on disk before the probe block starts"
    assert (tmp_path / "checkpoint.json").exists()
    assert len(list((tmp_path / "boards").glob("*.json"))) == 1
    head = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert head["checkpoint"] is True and head["board_runs"] == 1


def test_a_checkpoint_that_raises_never_ends_the_census(capsys):
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"], alternative_pass="",
                    probes=(), cascade_legs=False,
                    checkpoint=lambda b, k: (_ for _ in ()).throw(OSError("disk full")))
    assert art["summary"]["board_runs"] == 1
    assert "checkpoint FAILED" in capsys.readouterr().out


def test_the_alternative_pass_is_rolled_up_rather_than_banked_unread():
    """It is ~25% of the wall whose only output was board JSONs nothing compared."""
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot", "corn_cbot"],
                    alternative_pass="quick", probes=(), cascade_legs=False)
    alt = art["summary"]["alternative_pass"]
    assert alt["ran"] is True and alt["compared"] == 2
    assert set(alt["pairs"][0]) >= {"net_reads_d2", "net_reads_alt", "top_row_d2", "top_row_alt"}
    assert alt["verdict"]
    assert BC.banner(art).count("ALTERNATIVE PASS") == 1


def test_a_pass_with_no_alternative_says_so_rather_than_reporting_an_empty_rollup():
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=(), cascade_legs=False)
    assert art["summary"]["alternative_pass"] == {"ran": False}
    assert "ALTERNATIVE PASS" not in BC.banner(art)


def test_p1_says_which_rows_it_ranked_the_alternative_tuple_over():
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=("P1",), cascade_legs=False)
    assert "the rows the D2 walk priced" in art["probes"]["P1"]["alternative_ranked_over"]


def test_the_settled_table_distinguishes_not_run_from_measured_nothing():
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=BC.PROBES_OFFLINE, cascade_legs=False)
    settled = art["summary"]["settled"]
    for name in ("pg_read_latency_ms", "pool_contention", "oni_iod_revision_magnitude"):
        assert settled[name]["state"].startswith("NOT RUN"), \
            f"{name}'s probe did not run on an offline pass; the row must not read 'measured'"
    assert settled["lag_declarations_parse"]["state"] == "measured"
    assert settled["board_rows_total"]["state"] == "measured"
    assert "[NOT RUN" in BC.banner(art)


def test_the_wave_two_figure_carries_the_rectangle_it_was_measured_under():
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=(), cascade_legs=False)
    dropped = art["summary"]["per_mode"]["quick"]["keys_dropped"]
    assert "analogs UNWIRED" in dropped["measured_under"]
    assert "leg B DARK" in dropped["measured_under"]


def test_the_contention_record_stamps_the_memos_state():
    """With ``GRAPHRAG_STATE_CACHE=on`` the agent thread's repeated keys become memo hits and the
    probe measures no contention at all -- a zero a reader would take for pool headroom."""
    graph = BC.load_graph()
    got = BC.probe_p0(graph, "2026-09-07", qfn=lambda sql: [], keys=2, widths=(1,))
    assert got["contention"]["state_cache"]
    assert got["contention"]["state_cache_note"]


def test_a_board_record_carries_its_own_physical_read_share():
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=(), cascade_legs=False)
    b = art["boards"][0]
    assert "physical_reads_board" in b
    assert set(b["physical_reads_board"]) == {"reads", "rows"}


def test_read_prior_reaches_a_banked_vintage_a_repo_relative_search_cannot(tmp_path):
    """The container runs the census from /tmp, so ``load_prior`` correctly returns None forever;
    ``--prior`` is the seam that reaches a banked vintage in-VPC."""
    p5 = {"tables": {"silver_noaa_oni": {"hash": "abc", "snapshot": {"2026-01": 0.4}}}}
    whole = tmp_path / "probes.json"
    whole.write_text(json.dumps({"P5": p5}), encoding="utf-8")
    assert BC.read_prior(str(whole))["tables"]["silver_noaa_oni"]["hash"] == "abc"
    bare = tmp_path / "p5.json"
    bare.write_text(json.dumps(p5), encoding="utf-8")
    assert BC.read_prior(str(bare))["tables"]["silver_noaa_oni"]["hash"] == "abc"
    assert BC.read_prior("") is None


# ---------------------------------------------------------------------------------------------------
# THE SUBMIT WRAPPER -- the entrypoint assumption and the retry that would re-run the whole wall
# ---------------------------------------------------------------------------------------------------
def _submit_module():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "submit_batch_board_census", root / "jobs" / "submit" / "submit_batch_board_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_wrapper_reads_the_jobdefs_entrypoint_rather_than_assuming_python():
    """The override is ``['-c', code] + args``, which reaches the census's argv only if the image's
    entryPoint is python. ``leviathan-dev-graphrag-eval`` is defined nowhere in this tree, so the
    assumption is unverified -- and an unverified assumption must be PRINTED, not held silently."""
    mod = _submit_module()
    assert "right shape" in mod.check_entrypoint({"entryPoint": ["/usr/local/bin/python"]})
    assert "UNVERIFIED" in mod.check_entrypoint({"image": "x"})
    assert "NOT a python binary" in mod.check_entrypoint({"entryPoint": ["/bin/sh", "-lc"]})
    assert "UNKNOWN" in mod.check_entrypoint({})


def test_the_wrapper_forwards_the_prior_and_defaults_to_one_attempt():
    mod = _submit_module()

    class A:
        asof, modes, contracts, width = "2026-09-07", "quick", "", 2
        container_out, s3_out, alternative_pass = "/tmp/x", "", "max"
        no_probes = no_cascade_census = no_tape = False
        prior = "s3://b/k/probes.json"

    args = mod.census_args(A())
    assert "--prior" in args and "s3://b/k/probes.json" in args
    A.prior = ""
    assert "--prior" not in mod.census_args(A())
