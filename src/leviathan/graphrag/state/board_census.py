"""THE BOARD CENSUS -- design sec 10.1(b) and sitting S4, the second of the two $0 censuses.

WHAT IT IS. One deterministic pass over the WHOLE estate at ONE as-of: every board (36 causal
contracts), every mapped ref, read through ``state.feeders`` behind a COUNTING executor, with the
walk run per mode (quick / deep / max) at the real budget, the block rendered, and every number the
design quoted as ``[A]`` / UNVERIFIED replaced by a MEASURED one. It costs no LLM call and no Athena
query; its only spend is pg-mirror reads on the numbers bulkhead.

WHY A SEPARATE MODULE AND NOT A DECK. Sec 10.1's exit for S4 is "caps, windows and sec 7's line
counts SET from the artifact" -- i.e. this run's output is an INPUT to the design, so it has to be
reproducible by anyone who reads the file, banked as an artifact, and runnable both in-VPC (against
the mirror) and offline (against ``state.__main__``'s fixtures) so the shape is provable with no
store. A scratch script satisfies none of those.

THE FIREWALL IS THE PSD RUNBOOK'S, BORROWED WHOLE (``cascade_census._athena_firewall``): the census
asserts ``GRAPHRAG_NUMBERS_BACKEND=pg`` and a DSN BEFORE anything runs, makes ``Q.athena_query_fn``
raise for the length of the run, and asserts ``Q.STATS`` empty at the end. A post-hoc
``ATHENA_CALLS == 0`` banner would only read zero AFTER an Athena call already executed.

THE SIX PROBES (sec 10.1, S0's P0-P5), each with its own function and its own verdict word:

  P0  SERIES READ LATENCY at pool widths 1 / 2 / 4 plus the contention round -- every latency figure
      in secs 3.8 and 7 is a projection until this exists.
  P1  THE FALSIFIER. At as-of 2026-09-07 ONI must be the loudest MEASURED state on the soybeans
      board under the D2 tuple. The census banks the loud set under BOTH tuples with every
      convention-crossed row's rank position, and P1 failing under the first is the ONE
      pre-registered way this design can be wrong -- with its branch (apply the alternative) written.
  P2  THE SPAN FENCE for the tape rider (leg B): 180 / 270 / 365-day windows across the tape roster.
  P3  THE LAG CENSUS: every lag declaration parses to a table key; the offset bands applied.
  P4  THE CALENDAR DRAFT: ``next_release`` over the next 60 days from the rules, printed to be
      eyeballed against the publishers' own statements.
  P5  THE IN-PLACE REVISION MAGNITUDE on the two latest-only climate cards.

and the three further counts sec 10.1 names in the same paragraph, each with its own function:
``destination_census`` (the per-slug ESR / FGIS destination counts and the 52-week window's headroom
under the 5,000-row cap), ``probe_oni_crossings`` (the crossing count and the closed 1-2q / 2-4q
windows the scenario-2 words narrate), and ``cascade_leg_census`` (sec 10.1(a)'s fresh HEAD leg
census, run in the SAME job at the SAME as-of so the two censuses can never disagree about the date).

EVERY COUNT THIS MODULE PRINTS IS DERIVED FROM AN OBJECT THE ENGINE BUILT, never from a second
opinion: the read counts are ``Board.ledger``'s, the loud sets are ``walk.loud_set``'s, the render
sizes are ``render.classify``'s over the rendered block's own lines, and the register trips are
``Block.trips``. A census that re-implemented any of them would measure itself.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as _dt
import hashlib
import json
import os
import statistics
import sys
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------------------------------
# THE DECLARED CONSTANTS -- every one of them the design's own, restated so the artifact is auditable
# ---------------------------------------------------------------------------------------------------

#: The census as-of. 2026-09-07 is a HISTORICAL as-of by the time S4 runs, and it is runnable only
#: because replay is a LABEL and not a mode (sec 1.4): a latest-only card serves its newest print and
#: SAYS SO through ``vintage_note`` rather than declining.
CENSUS_ASOF_DEFAULT = "2026-09-07"

#: The three tiers the board declares knobs for. ``standard`` and every unarmed preset return None
#: from ``board_knobs_of`` and are an OFF LANE by construction (sec 7).
MODES: tuple = ("quick", "deep", "max")

#: P1's board and P1's card. The falsifier is about ONI's rank on soybeans, and ONI is identified by
#: the TABLE its resolved series key reads -- never by a ref string, because ``same_series_as`` folds
#: ``oni_lag_climate`` onto ``oni_climate`` and both are the same read.
P1_BOARD = "soybeans_cbot"
P1_TABLE = "silver_noaa_oni"
P1_TOP_N = 10

#: P0's widths. 4 is the pool's own size (``pgnumbers._NUM_POOL_SIZE`` default 4), so the third rung
#: measures saturation rather than throughput -- which is the point: the board runs at width 2 and the
#: question sec 3.8 leaves open is what a 4-wide agent round beside it costs.
P0_WIDTHS: tuple = (1, 2, 4)
P0_KEYS = 24                      # one Scan wave's worth of distinct keys, the smallest honest sample

#: P2's windows, in days. 270 is ``cascade.CW_SPAN_MAX_DAYS`` (r2-certified to ~267 d, failures from
#: ~563 d); 365 is what a two-to-four-quarter band actually asks for; 180 is the lower anchor.
P2_WINDOWS: tuple = (180, 270, 365)

#: P4's horizon, in days -- sec 10.1's own "the next 60 days".
P4_HORIZON_DAYS = 60

#: P5's cards: the two the board declares latest-only (``feeders.LATEST_ONLY_CARDS``), restated here
#: because P5 is about those two by name and a probe that read the frozenset would silently widen the
#: day a third card joined it.
P5_TABLES: tuple = ("silver_noaa_oni", "silver_noaa_iod")

#: THE LAG WITNESS'S BASE COLUMNS, per card, DECLARED -- because on these two cards the base is NOT
#: the same column and a witness that assumed it manufactures findings on one card and none on the
#: other:
#:
#:   * ``silver_noaa_oni``: ``oni_lagN = oni_anom.shift(N)`` -- ``noaa_oni.py:125``
#:     (``df[f"oni_lag{n}"] = df["oni_anom"].shift(n)``), the same contract ``feeders`` rests its
#:     ``same_series_as`` fold on ("The alias's column IS the base shifted").
#:   * ``silver_noaa_iod``: ``iod_dmi_ethiopia_lag4 = iod_dmi_3month_avg.shift(4)`` -- ``noaa_iod.py``
#:     :225-235 and its own docstring, "the lag here is applied against the already 3-month-smoothed
#:     series". Comparing that column against ``dmi_value`` (the card's ANOMALY column) would disagree
#:     on nearly every row and report a whole-series revision that never happened.
#:
#: A lag column on a card with no declaration here falls to the NAME rule in :func:`_lag_base_column`
#: and, failing that, is reported UNMAPPED and left unchecked. A guess is never a witness.
LAG_BASE_COLUMNS: dict = {
    "silver_noaa_oni": {"oni_lag3": "oni_anom", "oni_lag6": "oni_anom",
                        "oni_lag9": "oni_anom", "oni_lag12": "oni_anom"},
    "silver_noaa_iod": {"iod_dmi_ethiopia_lag4": "iod_dmi_3month_avg"},
}

#: The lag witness's equality tolerance. A shift is a COPY, so two columns of one dtype agree exactly;
#: this is the float-round-trip allowance and nothing more, and it is stamped on the record so a
#: reader never has to guess what "agree" meant.
LAG_WITNESS_TOLERANCE = 1e-9

#: The analog likeness bands sec 10.1 asks the candidate count at, in sigma.
ANALOG_BANDS: tuple = (0.5, 1.0, 1.5)

#: Every probe this module owns, and the subset that needs the mirror. The split is what lets the
#: OFFLINE pass run the pg-free half honestly instead of reporting the other half as null.
PROBES_ALL: tuple = ("P0", "P1", "P2", "P3", "P4", "P5", "destinations", "oni_crossings")
PROBES_PG: tuple = ("P0", "P2", "P5", "destinations", "oni_crossings")
PROBES_OFFLINE: tuple = ("P1", "P3", "P4")

#: The fresh cascade census's PREDICTION -- design prediction #14 after D-10 sitting 9. The census
#: prints the measured split beside it and never adjusts one to the other.
CASCADE_PREDICTION: dict = {"legs": 792, "fires": 544, "declines": 248, "dark": 0, "probe_errors": 0}

#: The design's own quoted-but-unverified figures this artifact settles, by name. Each key is written
#: into ``summary["settled"]`` with its MEASURED value beside the quote, so a reader of the artifact
#: never has to hold the design open beside it.
UNVERIFIED_CLAIMS: dict = {
    "distinct_series_keys_estate": "Draft A's median 17 per contract / ~444 estate estimate; the "
                                   "390-key figure is config-derived and never replayed (Appendix B)",
    "distinct_series_keys_per_board": "Draft A's median 17 per contract (Appendix B)",
    "board_rows_total": "the design's 1,266 rows (sec 10.1(b), bar B14)",
    "pg_read_latency_ms": "every latency delta in secs 3.8 and 7 is a projection until P0 "
                          "(Appendix B)",
    "pool_contention": "the BoardPoolDeclined rate with a 4-wide agent round beside the wave "
                       "(sec 10.1)",
    "oni_iod_revision_magnitude": "the magnitude of any in-place ONI / IOD revision on the mirror -- "
                                  "no prior vintage exists (Appendix B)",
    "esr_fgis_destination_counts": "the per-slug ESR / FGIS destination counts and the 52-week "
                                   "window's headroom under the 5,000-row cap (Appendix B)",
    "per_anchor_line_counts": "sec 7's per-anchor line and token counts are [A]; the S4 artifact "
                              "adds the measured ones and sec 7 is re-derived from the MEDIAN board",
    "wave1_cap_binds": "sec 7's 'supply, not caps' (desk_cost F16): the caps are UPPER bounds and "
                       "the soybeans board carries 12-13 keys, not 24",
    "span_fence_365": "CW_SPAN_MAX_DAYS 270 is r2-certified to ~267 d and failures start ~563 d; "
                      "the gap is unmeasured while a 2-4q band is ~365 d (analogs.leg_b_rows)",
    "cascade_census_split": "790 = 541 FIRES / 249 DECLINES (commit 9b2cfb56) superseded by "
                            "prediction #14 = 792 = 544 / 248 / 0 / 0 after D-10 sitting 9",
    "p1_falsifier": "ONI's +0.98 degC against its own 120-month history is a modest sigma [A] and a "
                    "same-month weather z can out-rank it (sec 3.2)",
    "lag_declarations_parse": "S0's exit reads '1,412 declarations parse (18 + 8 strings, zero "
                              "unparsed)' (sec 11 row S0, P3)",
    "release_calendar_verified": "every publisher print time and window is owner curation, "
                                 "verified_against: null until confirmed (Appendix B, P4)",
    "oni_crossing_count": "the ONI crossing count since 1950 with closed 1-2q and 2-4q windows -- "
                          "the words scenario 2 narrates (sec 10.1)",
    "tape_roster": "the then/now design's roster measurement (20 boards) is QUOTED, not re-measured "
                   "(Appendix B); bar B19 names 'each of the ten tape-less boards'",
}


# ---------------------------------------------------------------------------------------------------
# THE COUNTING EXECUTOR (sec 10.1: "physical reads, pool declines, replay labels, borrow counts")
# ---------------------------------------------------------------------------------------------------
class CountingExecutor:
    """A ``qfn`` wrapper that counts what the board actually did to the mirror.

    IT COUNTS PHYSICAL READS, NOT LEDGER SEATS, and the two are different numbers on purpose. The
    board's ``Ledger`` counts the SEAT a row spent (which is what a cap is about); this counts the SQL
    that reached pg (which is what the mirror's load is about). With the memo off they agree; with
    ``GRAPHRAG_STATE_CACHE`` on they do not, and the difference IS the memo's measured value.

    IT NEVER SWALLOWS A DECLINE. ``feeders.board_query_fn`` raises ``BoardReadDecline`` by name for a
    pool wait or a statement timeout, and this wrapper records the word and re-raises -- a counter
    that ate the exception would turn a declined row into a read one.
    """

    def __init__(self, inner, *, name: str = "board"):
        self.inner = inner
        self.name = name
        self.reads = 0
        self.rows = 0
        self.ms: list = []
        self.declines: collections.Counter = collections.Counter()
        self.errors: collections.Counter = collections.Counter()
        self.by_table: collections.Counter = collections.Counter()
        self.max_concurrency = 0
        self._live = 0
        self._lock = threading.Lock()

    # -- the executor itself -------------------------------------------------------------------------
    def __call__(self, sql: str):
        from leviathan.graphrag.state import feeders as F

        with self._lock:
            self._live += 1
            if self._live > self.max_concurrency:
                self.max_concurrency = self._live
        t0 = time.perf_counter()
        try:
            out = self.inner(sql)
        except F.BoardReadDecline as d:
            with self._lock:
                self.reads += 1
                self.ms.append((time.perf_counter() - t0) * 1000.0)
                self.declines[d.status] += 1
                self._live -= 1
            raise
        except Exception as e:                          # noqa: BLE001 -- recorded by TYPE, never eaten
            with self._lock:
                self.reads += 1
                self.ms.append((time.perf_counter() - t0) * 1000.0)
                self.errors[type(e).__name__] += 1
                self._live -= 1
            raise
        with self._lock:
            self.reads += 1
            self.rows += len(out or [])
            self.ms.append((time.perf_counter() - t0) * 1000.0)
            self.by_table[_table_of(sql)] += 1
            self._live -= 1
        return out

    # -- the report ----------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            ms = list(self.ms)
            return {"name": self.name, "reads": self.reads, "rows": self.rows,
                    "ms": _ms_summary(ms), "declines": dict(self.declines),
                    "errors": dict(self.errors), "max_concurrency": self.max_concurrency,
                    "by_table": dict(self.by_table)}

    def reset(self) -> None:
        with self._lock:
            self.reads = 0
            self.rows = 0
            self.ms = []
            self.declines = collections.Counter()
            self.errors = collections.Counter()
            self.by_table = collections.Counter()
            self.max_concurrency = 0


def _table_of(sql: str) -> str:
    """The table a compiled statement reads, for the per-table read histogram. Best-effort and it says
    so: an unparsed statement counts under ``?`` rather than under a guess."""
    s = str(sql or "")
    low = s.lower()
    i = low.find(" from ")
    if i < 0:
        return "?"
    tail = s[i + 6:].strip().split()[0] if s[i + 6:].strip() else ""
    tail = tail.strip("()").split(".")[-1]
    return tail or "?"


def _ms_summary(ms: list) -> dict:
    """p50 / p90 / max / mean over a list of milliseconds, or an all-None dict when nothing ran.

    NONE, NEVER ZERO. A latency of 0 ms and a probe that made no read are two different facts, and the
    second one is exactly what an empty artifact must be able to say."""
    xs = sorted(float(x) for x in (ms or []))
    if not xs:
        return {"n": 0, "p50": None, "p90": None, "max": None, "mean": None, "total": None}
    return {"n": len(xs),
            "p50": round(statistics.median(xs), 2),
            "p90": round(xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))], 2),
            "max": round(xs[-1], 2),
            "mean": round(statistics.fmean(xs), 2),
            "total": round(sum(xs), 2)}


# ---------------------------------------------------------------------------------------------------
# THE FIREWALL AND THE ENV ASSERTS -- the psd runbook idiom, BEFORE anything runs
# ---------------------------------------------------------------------------------------------------
def assert_pg_only() -> dict:
    """The env asserts sec 10.1 mandates, run BEFORE the first read and returning what they read.

    Borrowed from ``cascade_census._run_live`` verbatim in shape so the two censuses in one job cannot
    disagree about what "pg-only" means."""
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers import query as Q

    backend = os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower()
    assert backend == "pg", \
        f"board_census requires GRAPHRAG_NUMBERS_BACKEND=pg (got {backend!r})"
    assert os.environ.get("EVIDENCE_PG_DSN"), "board_census requires EVIDENCE_PG_DSN"
    assert pgnumbers.enabled(), "board_census requires pgnumbers.enabled() (backend=pg + DSN)"
    assert not Q.STATS, f"board_census requires a clean Athena ledger (Q.STATS is {len(Q.STATS)})"
    return {"backend": backend, "dsn_present": True, "pgnumbers_enabled": True,
            "pool_size": int(os.environ.get("NUMBERS_PG_POOL", "4") or 4),
            "pool_wait_s": int(os.environ.get("NUMBERS_PG_POOL_WAIT_S", "5") or 5),
            "statement_timeout_ms": int(
                os.environ.get("NUMBERS_PG_STATEMENT_TIMEOUT_MS", "5000") or 5000),
            "state_cache": os.environ.get("GRAPHRAG_STATE_CACHE", "") or "off"}


@contextlib.contextmanager
def athena_firewall():
    """``cascade_census._athena_firewall``, re-exported under this module's own name so a caller
    reading the board census does not have to know which module owns the tripwire."""
    from leviathan.graphrag.numbers import cascade_census as CC
    with CC._athena_firewall():
        yield


# ---------------------------------------------------------------------------------------------------
# THE ESTATE'S OWN SHAPES -- zero reads, pure config
# ---------------------------------------------------------------------------------------------------
class _LegNode:
    """``cascade_census._LegNode``'s shape: anything carrying ``.contract``, ``.id`` and
    ``.prior['silver_ref' / 'region']``. Re-declared rather than imported so this module can be read
    without opening the cascade lane's file."""

    __slots__ = ("contract", "id", "prior", "evidence")

    def __init__(self, contract: str, driver_id: str, silver_ref, region) -> None:
        self.contract = contract
        self.id = driver_id
        self.prior = {"silver_ref": silver_ref, "region": region}
        self.evidence: list = []


def load_graph():
    """The shipped causal graph, as every serving path builds it."""
    from leviathan.graphrag import graph as G
    return G.CausalGraph(G.load_contracts(), silver=set(), version="board_census")


def series_key_census(graph) -> dict:
    """THE TRUE DISTINCT SERIES-KEY COUNT, per contract and estate-wide -- ZERO READS.

    This is the number the whole design is sized by and the one Appendix B deliberately left to the
    probe ("Draft A's median 17 / ~444 estimate -- P0 replaces it"; "the 390-key estimate is
    config-derived, not replayed"). It is computed through ``feeders.series_key_for``, the SAME
    zero-read prologue the walk's pricer uses, so the count is the pricer's own and not a second
    enumeration of the map."""
    from leviathan.graphrag.state import feeders as F

    per: dict = {}
    estate: set = set()
    tables: collections.Counter = collections.Counter()
    statuses: collections.Counter = collections.Counter()
    rows_total = 0
    mapped = 0
    for cname, c in sorted(graph.contracts.items()):
        keys: set = set()
        n_rows = 0
        for d in c.drivers:
            n_rows += 1
            rows_total += 1
            node = _LegNode(cname, d.id, d.silver_ref, d.region)
            try:
                plan = F.series_key_for(d.silver_ref, node)
            except Exception as e:                      # noqa: BLE001 -- a broken card is a FINDING
                statuses[f"key_error:{type(e).__name__}"] += 1
                continue
            if plan.key is None:
                statuses[plan.status or "unmapped_ref"] += 1
                continue
            mapped += 1
            statuses["keyed"] += 1
            keys.add(plan.key.label())
            estate.add(plan.key.label())
            tables[plan.table or "?"] += 1
        per[cname] = {"rows": n_rows, "keys": len(keys), "key_labels": sorted(keys)}
    counts = sorted(v["keys"] for v in per.values())
    return {"rows_total": rows_total, "rows_with_key": mapped,
            "distinct_keys_estate": len(estate),
            "keys_summed_over_boards": sum(counts),
            "per_board_keys": {"min": counts[0] if counts else 0,
                               "median": statistics.median(counts) if counts else 0,
                               "max": counts[-1] if counts else 0},
            "by_table": dict(tables.most_common()),
            "by_status": dict(statuses.most_common()),
            "per_board": per,
            "estate_key_labels": sorted(estate)}


# ---------------------------------------------------------------------------------------------------
# ONE BOARD, ONE MODE -- the walk at the real budget, the block rendered, everything banked
# ---------------------------------------------------------------------------------------------------
def board_run(graph, contract: str, mode: str, asof: str, *, state_fn, key_fn=None,
              tape_fn=None, alternative: bool = False, width: int = 2,
              receipts=None) -> dict:
    """ONE board at ONE mode: the walk (both stages), the tape, the analogs, the watch, the render.

    ``state_fn`` and ``tape_fn`` are INJECTED, exactly as ``walk`` takes them, which is what makes
    this function runnable against the mirror in-VPC and against ``state.__main__``'s fixtures on a
    laptop with the same code path. The census NEVER opens its own reader.

    THE RECTANGLE IS CHECKED AT THE END OF EVERY BOARD, not only at the estate roll-up: bar B1 is
    "at every early return", and a board whose rectangle is open is a finding about THAT board."""
    from leviathan.graphrag.state import analogs as A
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import narration as N
    from leviathan.graphrag.state import render as R
    from leviathan.graphrag.state import walk as W
    from leviathan.graphrag.state import watch as WA
    from leviathan.graphrag.state.rows import status_word

    t0 = time.perf_counter()
    kn = B.board_knobs_of(mode)
    anchors = W.resolve_anchors(named=(contract,), graph=graph)
    bd = W.walk(graph=graph, asof=asof, mode=mode, anchors=anchors, question="",
                state_fn=state_fn, key_fn=key_fn, receipts=dict(receipts or {}),
                knobs=kn, width=width, legb_on=False, alternative_rank=alternative,
                stage2=True, analog_reads=False)
    walk_ms = (time.perf_counter() - t0) * 1000.0

    # -- THE TAPE (D19): one mirror read per anchor board, priced by `render.price_tape` first -------
    tape: dict = {}
    tape_reads = 0
    if tape_fn is not None and bd.legs.get("board", {}).get("outcome") == "fired":
        for slug in R.price_tape(bd):
            tp = tape_fn(slug, bd.asof)
            if tp is not None:
                tape[slug] = tp
                tape_reads += int(getattr(tp, "reads", 0) or 0)
        if tape:
            R.attach_tape(bd, tape, reads_each=0)
            bd.ledger.tape_reads += int(tape_reads)
        bd.stamp("tape", "fired" if tape else "declined",
                 reason="" if tape else "no_tape_slug", reads=int(tape_reads))

    # -- THE PRODUCERS the render reads (all zero-read on this path) ---------------------------------
    t_prod = time.perf_counter()
    ana = A.analog_rows(bd, knobs=kn, benchmark_fn=None, receipt_fn=None) if kn else []
    A.analog_leg(bd, ana)
    wr = WA.watch_rows(bd, analogs=ana) if kn else []
    WA.watch_leg(bd, wr)
    ages: dict = {}
    for r in bd.rows:
        st = r.state
        if st is None or status_word(st.status) != "ok":
            continue
        clause = N.age_clause(st.knowledge_date, bd.asof, st.cadence)
        if clause:
            ages[r.key] = clause
    rec = N.recency_rows(bd, tape_edge=max(
        (str(getattr(t, "level_date", "") or "") for t in tape.values()), default=""))
    producers_ms = (time.perf_counter() - t_prod) * 1000.0
    t_render = time.perf_counter()
    blk = R.render_board(bd, analogs=ana, watch=wr, recency=rec, age_clauses=ages,
                         anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
    render_ms = (time.perf_counter() - t_render) * 1000.0
    bd.stamp("render", "fired" if not blk.trips else "declined",
             reason="template_register_trip" if blk.trips else "")
    total_ms = (time.perf_counter() - t0) * 1000.0

    return {"contract": contract, "mode": mode, "asof": bd.asof,
            "rank_rule": bd.rank_rule,
            "walk_ms": round(walk_ms, 1), "total_ms": round(total_ms, 1),
            "producers_ms": round(producers_ms, 1), "render_ms": round(render_ms, 1),
            "stage_ms": {str(k): round(float(v), 1) for k, v in sorted(bd.stage_ms.items())},
            "rows": _row_census(bd),
            "loud": _loud_census(bd, alternative=alternative),
            "fan": _fan_census(bd),
            "budget": _budget_census(bd),
            "render": _render_census(blk, bd),
            "legs": {k: dict(v) for k, v in sorted(bd.legs.items())},
            "declines": _decline_census(bd),
            "analogs": _analog_census(bd, ana),
            "watch": {"rows": len(wr), "fired": sum(1 for w in wr if not w.get("declined")),
                      "declined": sorted({str(w.get("declined")) for w in wr if w.get("declined")})},
            "tape": _tape_census(bd, tape),
            "notes": [dict(n) for n in bd.notes],
            # THE TRACE, MINUS THE TWO BLOCKS THE RECORD ALREADY CARRIES. `Board.trace()` is the
            # serving key's payload and it repeats `legs` and `ledger`, both of which are banked above
            # under their own names. Banking them a THIRD time would make the artifact bigger and give
            # a later reader two copies of one fact to reconcile; the trace is kept for the fields only
            # it has (rank_rule, stage_ms, rectangle, notes) and its own docstring's contract is
            # unchanged for every other caller.
            "trace": {k: v for k, v in bd.trace().items() if k not in ("legs", "ledger")}}


def _row_census(bd) -> dict:
    from leviathan.graphrag.state.rows import status_word

    tiers: collections.Counter = collections.Counter()
    statuses: collections.Counter = collections.Counter()
    vintage = 0
    context_only = 0
    for r in bd.rows:
        tiers[r.coverage_tier] += 1
        st = r.state
        if st is None:
            statuses["no_state"] += 1
            continue
        statuses[status_word(st.status)] += 1
        if st.vintage_note:
            vintage += 1
        if st.context_only:
            context_only += 1
    return {"total": len(bd.rows), "series_rows": len(bd.series),
            "by_coverage_tier": dict(tiers.most_common()),
            "by_status": dict(statuses.most_common()),
            "replay_labelled": vintage, "context_only": context_only,
            "anchors": list(bd.anchor_slugs), "anchor_source": bd.anchor_source}


def _row_rank_record(bd, row, seat: int) -> dict:
    """One row's rank card: the three figures the rank tuple reads plus the tie-breaks, so a reader
    can re-derive the position rather than trust it."""
    from leviathan.graphrag.state import walk as W
    from leviathan.graphrag.state.rows import status_word

    st = row.state
    def _v(measure):
        if not isinstance(measure, dict) or measure.get("declined"):
            return None
        return measure.get("value")

    return {"seat": seat, "contract": row.contract, "driver_id": row.driver_id,
            "series_key": row.series_key or None,
            "table": (st.table if st is not None else None),
            "status": (status_word(st.status) if st is not None else "no_state"),
            "coverage_band": W.coverage_band(row),
            "abs_z": round(W._abs_z(row), 4),
            "z": _v(st.z) if st is not None else None,
            "percentile": _v(st.percentile) if st is not None else None,
            "pct_extremity": round(W._pct_extremity(row), 4),
            "run_length": W._run_length(row),
            "run": (st.run if st is not None else None),
            "convention_hit": W._convention_hit(row),
            "band_crossed": bool(row.band_crossed),
            "event_open": bool(row.event_open),
            "window_note": (st.window_note if st is not None else ""),
            "n_obs": ((st.coverage or {}).get("n_obs") if st is not None else None),
            "loud": bool(row.legs.get("loud"))}


def _loud_census(bd, *, alternative: bool) -> dict:
    """THE LOUD SET UNDER BOTH TUPLES (sec 3.2, P1).

    The walk ran under ONE tuple -- ``bd.rank_rule`` -- and that is the set whose far states were
    priced. The OTHER tuple's order is computed here over the SAME rows, because a rank is a pure
    function of the rows and re-walking to learn an order would be a second read of the same mirror
    for a number arithmetic already has. Both orders are banked; only the walked one carries reads."""
    from leviathan.graphrag.state import walk as W

    kn = bd.knobs
    loud_k = int(getattr(kn, "loud_k", 0) or 0)
    out: dict = {"walked_rule": bd.rank_rule, "loud_k": loud_k}
    for rule, alt in (("d2", False), ("alternative", True)):
        order = W.rank_rows(bd.rows, alternative=alt)
        loud = W.loud_set(bd.rows, loud_k=loud_k, alternative=alt) if loud_k else []
        loud_keys = {r.key for r in loud}
        out[rule] = {
            "order": [_row_rank_record(bd, r, i) for i, r in enumerate(order[:P1_TOP_N])],
            "loud_n": len(loud),
            "loud": [{"contract": r.contract, "driver_id": r.driver_id,
                      "table": (r.state.table if r.state is not None else None)}
                     for r in loud],
            "convention_crossed_ranks": [
                {"contract": r.contract, "driver_id": r.driver_id, "seat": i,
                 "in_loud": r.key in loud_keys}
                for i, r in enumerate(order) if W._convention_hit(r)],
            "rank_words": W.rank_rule_words(alt),
        }
    out["order_identical"] = ([r["driver_id"] for r in out["d2"]["order"]]
                              == [r["driver_id"] for r in out["alternative"]["order"]])
    return out


def _fan_census(bd) -> dict:
    far_boards: set = set()
    far_rows = 0
    for e in bd.fan:
        for f in e.get("far") or ():
            far_rows += 1
            far_boards.add(f.get("contract"))
    return {"index_entries": len(bd.fan), "far_rows": far_rows,
            "far_boards": len(far_boards), "edges": len(bd.edges),
            "paths": len(bd.paths), "convergence": len(bd.convergence)}


def _budget_census(bd) -> dict:
    led = bd.ledger.to_dict()
    return {"net_reads": bd.net_reads(), "declared_cap": bd.declared_cap(),
            "headroom": bd.declared_cap() - bd.net_reads(),
            "rectangle": bd.rectangle(),
            "rectangle_closed": not bd.rectangle(),
            "ledger": led,
            "wave1_deferred": list(bd.ledger.waves[1].deferred_keys),
            "wave2_deferred": list(bd.ledger.waves[2].deferred_keys),
            "wave1_declined": list(bd.ledger.waves[1].declined_keys),
            "wave2_declined": list(bd.ledger.waves[2].declined_keys),
            "budget_capped": bd.ledger.budget_capped,
            "pool_declined": bd.ledger.pool_declined,
            "replay_labelled": bd.ledger.replay_labelled}


def _render_census(blk, bd) -> dict:
    """Render sizes PER CLASS -- lines and characters -- against sec 7's own line counts."""
    from leviathan.graphrag.state import render as R

    per_class_lines: collections.Counter = collections.Counter()
    per_class_chars: collections.Counter = collections.Counter()
    unclassified: list = []
    multi: list = []
    for line in blk.lines:
        names = R.classify(line)
        if not names:
            unclassified.append(line[:120])
            names = ("?",)
        elif len(names) > 1:
            multi.append({"line": line[:120], "classes": list(names)})
        per_class_lines[names[0]] += 1
        per_class_chars[names[0]] += len(line)
    text = blk.text()
    return {"lines": len(blk.lines), "chars": len(text),
            "est_tokens": round(len(text) / 4.0),
            "calls": len(blk.calls),
            "trips": [dict(t) if isinstance(t, dict) else str(t) for t in blk.trips],
            "trip_count": len(blk.trips),
            "welds": len(blk.welds),
            "by_class_lines": dict(per_class_lines.most_common()),
            "by_class_chars": dict(per_class_chars.most_common()),
            "unclassified": unclassified,
            "multi_class": multi,
            "caps": R.render_caps(bd.mode, getattr(bd, "knobs", None))}


def _decline_census(bd) -> dict:
    words: collections.Counter = collections.Counter()
    for leg, rec in bd.legs.items():
        if rec.get("outcome") == "declined":
            words[f"{leg}:{rec.get('reason')}"] += 1
    from leviathan.graphrag.state.rows import status_word
    row_words: collections.Counter = collections.Counter()
    for st in bd.series.values():
        row_words[status_word(st.status)] += 1
    return {"leg_declines": dict(words.most_common()),
            "row_status_words": dict(row_words.most_common()),
            "outcomes": collections.Counter(
                rec.get("outcome") for rec in bd.legs.values()).most_common()}


def _analog_census(bd, ana) -> dict:
    """The analog stanzas the board produced AND the candidate count per loud driver at the three
    likeness bands sec 10.1 names. The candidate count is a SELECTION fact and costs no read: the
    seed's own array is already in memory."""
    from leviathan.graphrag.state import analogs as A

    per_band: dict = {str(b): [] for b in ANALOG_BANDS}
    seeds_measured = 0
    kn = bd.knobs
    if kn and int(getattr(kn, "analog_dims", 0) or 0) > 0:
        order = {k: i for i, k in enumerate(bd.order)}
        loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                      key=lambda r: order.get(r.key, len(order)))
        for r in loud[: int(kn.analog_dims)]:
            st = r.state
            if st is None or not (st.inputs or {}).get(st.key.label()):
                continue
            try:
                hist = A.state_history(st, lag_days=A._lag_days_of(r))
                z_now = (float(st.z["value"]) if st.z and not st.z.get("declined") else None)
                dims = [{"id": r.driver_id, "hist": hist, "z_now": z_now}]
                seeds_measured += 1
                for band in ANALOG_BANDS:
                    n = 0
                    for d in (hist.get("dates") or ()):
                        lk = A.likeness(str(d)[:10], dims)
                        if lk is not None and lk.get("distance") is not None \
                                and float(lk["distance"]) <= float(band):
                            n += 1
                    per_band[str(band)].append({"driver_id": r.driver_id, "candidates": n,
                                                "history_n": len(hist.get("dates") or ())})
            except Exception as e:                      # noqa: BLE001 -- a probe never breaks a census
                per_band.setdefault("errors", []).append(
                    {"driver_id": r.driver_id, "error": f"{type(e).__name__}: {e}"[:200]})
    return {"stanzas": len(ana),
            "fired": sum(1 for a in ana if not a.get("declined")),
            "declined": dict(collections.Counter(
                str(a.get("declined")) for a in ana if a.get("declined")).most_common()),
            "seeds_measured": seeds_measured,
            "candidates_by_sigma_band": per_band}


def _tape_census(bd, tape) -> dict:
    out = []
    for slug, tp in sorted(tape.items()):
        out.append({"slug": slug, "status": getattr(tp, "status", None) or "ok",
                    "contract_month": getattr(tp, "contract_month", ""),
                    "level_date": getattr(tp, "level_date", None),
                    "reads": int(getattr(tp, "reads", 0) or 0),
                    "n_obs": (getattr(tp, "coverage", {}) or {}).get("n_obs"),
                    "truncated": (getattr(tp, "coverage", {}) or {}).get("truncated")})
    return {"boards": len(tape), "rows": out,
            "leg": dict(bd.legs.get("tape") or {})}


# ---------------------------------------------------------------------------------------------------
# P0 -- SERIES READ LATENCY AT WIDTHS 1 / 2 / 4, AND THE CONTENTION ROUND
# ---------------------------------------------------------------------------------------------------
def probe_p0(graph, asof: str, *, qfn, keys: int = P0_KEYS, widths=P0_WIDTHS) -> dict:
    """P0: the per-read millisecond figure on ``leviathan-dev-pg`` at pool widths 1 / 2 / 4, plus the
    ``BoardPoolDeclined`` rate with a 4-wide round running BESIDE a 2-wide wave.

    THE SAMPLE IS ONE SCAN WAVE'S WORTH OF REAL KEYS, taken from the estate's own key census in its
    own order, because a synthetic key would measure a plan the board never issues. The memo is
    CLEARED between rungs -- an unmeasured cache hit is a latency figure about nothing.

    THE CONTENTION ROUND IS THE POINT of the 4-wide rung: ``pgnumbers`` runs a 4-connection bulkhead
    (``NUMBERS_PG_POOL`` default 4) with a 5-second wait, so a 4-wide agent round beside the board's
    2-wide wave is the exact shape sec 3.8 leaves open. A decline here is a MEASUREMENT, not a
    failure: it is the number ``BoardPoolDeclined`` will carry in production."""
    from concurrent.futures import ThreadPoolExecutor

    from leviathan.graphrag.state import feeders as F

    plans = _p0_plans(graph, limit=keys)
    out: dict = {"keys_sampled": len(plans), "widths": {}, "contention": None,
                 "plans": [p["label"] for p in plans]}
    if not plans:
        out["declined"] = "no_priceable_keys"
        return out

    def _one(plan):
        counter = plan["counter"]
        t0 = time.perf_counter()
        status = "ok"
        try:
            st = F.series_state(plan["ref"], plan["node"], asof, qfn=counter,
                                windows=plan["windows"], conventions=plan["conventions"])
            status = str(getattr(st, "status", "ok") or "ok")
        except Exception as e:                          # noqa: BLE001
            status = f"raised:{type(e).__name__}"
        return {"label": plan["label"], "ms": (time.perf_counter() - t0) * 1000.0,
                "status": status}

    for width in widths:
        F.cache_clear()
        counter = CountingExecutor(qfn, name=f"p0_w{width}")
        for p in plans:
            p["counter"] = counter
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max(1, int(width))) as pool:
            rows = list(pool.map(_one, plans))
        wall = (time.perf_counter() - t0) * 1000.0
        snap = counter.snapshot()
        out["widths"][str(width)] = {
            "wall_ms": round(wall, 1),
            "per_read": snap["ms"],
            "physical_reads": snap["reads"],
            "rows_returned": snap["rows"],
            "observed_max_concurrency": snap["max_concurrency"],
            "declines": snap["declines"],
            "errors": snap["errors"],
            "per_key_ms": _ms_summary([r["ms"] for r in rows]),
            "statuses": dict(collections.Counter(r["status"] for r in rows).most_common()),
        }

    # -- THE CONTENTION ROUND: a 4-wide load beside a 2-wide wave ------------------------------------
    F.cache_clear()
    board_counter = CountingExecutor(qfn, name="p0_contention_board")
    agent_counter = CountingExecutor(qfn, name="p0_contention_agent")
    stop = threading.Event()

    def _agent_round():
        # A 4-WIDE ROUND, the shape a numbers-agent turn makes beside a board wave. It reads the SAME
        # keys, because a contention probe is about the POOL and not about the plan.
        with ThreadPoolExecutor(max_workers=4) as pool:
            while not stop.is_set():
                futs = []
                for p in plans[:4]:
                    futs.append(pool.submit(_agent_read, p, asof, agent_counter))
                for f in futs:
                    try:
                        f.result()
                    except Exception:                   # noqa: BLE001 -- the load is a load
                        pass

    thread = threading.Thread(target=_agent_round, daemon=True)
    thread.start()
    try:
        for p in plans:
            p["counter"] = board_counter
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(_one, plans))
        wall = (time.perf_counter() - t0) * 1000.0
    finally:
        stop.set()
        thread.join(timeout=30)
    bsnap, asnap = board_counter.snapshot(), agent_counter.snapshot()
    declined = sum(bsnap["declines"].values())
    # THE MEMO'S STATE IS STAMPED ON THE RECORD. The agent thread re-reads the same four keys in a
    # tight loop, so with `GRAPHRAG_STATE_CACHE=on` those become memo hits after the first round and
    # this probe measures no contention at all -- a zero that means "the cache worked", printed where
    # a reader will take it for "the pool has headroom". The board census's shipped pass runs with the
    # memo off; the record says which pass THIS was rather than assuming it.
    state_cache = os.environ.get("GRAPHRAG_STATE_CACHE", "") or "off"
    out["contention"] = {
        "state_cache": state_cache,
        "state_cache_note": (
            "the memo is OFF: every agent-thread read is a physical read and the load is real"
            if state_cache in ("off", "0", "false", "") else
            "the memo is ON: the agent thread's repeated keys become memo hits after the first "
            "round, so this contention figure UNDERSTATES a cold 4-wide round"),
        "board_wall_ms": round(wall, 1),
        "board_per_read": bsnap["ms"], "board_reads": bsnap["reads"],
        "board_declines": bsnap["declines"],
        "board_pool_declined_rate": (round(declined / bsnap["reads"], 4)
                                     if bsnap["reads"] else None),
        "board_statuses": dict(collections.Counter(r["status"] for r in rows).most_common()),
        "agent_reads": asnap["reads"], "agent_declines": asnap["declines"],
        "agent_per_read": asnap["ms"],
    }
    w2 = out["widths"].get("2", {})
    p50_alone = (w2.get("per_read") or {}).get("p50")
    p50_beside = bsnap["ms"].get("p50")
    out["contention"]["p50_alone_ms"] = p50_alone
    out["contention"]["p50_beside_agent_ms"] = p50_beside
    # `is not None`, NEVER truthiness: a p50 of 0.0 ms is a MEASUREMENT (a fixture executor, a memo
    # hit) and reading it as "no figure" would report the contention probe as un-run on exactly the
    # runs where the board was fastest.
    out["contention"]["slowdown_x"] = (
        round(p50_beside / p50_alone, 2)
        if (p50_alone not in (None, 0) and p50_beside is not None) else None)
    out["contention"]["slowdown_note"] = (
        "the alone-p50 is zero, so a ratio would divide by zero; compare the two p50s directly"
        if p50_alone == 0 else "")
    out["verdict"] = _p0_verdict(out)
    return out


def _agent_read(plan, asof, counter):
    from leviathan.graphrag.state import feeders as F
    return F.series_state(plan["ref"], plan["node"], asof, qfn=counter,
                          windows=plan["windows"], conventions=plan["conventions"])


def _p0_plans(graph, *, limit: int) -> list:
    """One Scan wave's worth of DISTINCT keys, in the estate's own declaration order."""
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state.lint import load_conventions

    try:
        conv = dict(load_conventions() or {})
    except Exception:                                   # noqa: BLE001
        conv = {}
    windows = dict(conv.get("windows") or {})
    blocks = dict(conv.get("conventions") or {})
    seen: set = set()
    plans: list = []
    for cname, c in sorted(graph.contracts.items()):
        for d in c.drivers:
            node = _LegNode(cname, d.id, d.silver_ref, d.region)
            try:
                kp = F.series_key_for(d.silver_ref, node)
            except Exception:                           # noqa: BLE001
                continue
            if kp.key is None or kp.key.label() in seen:
                continue
            seen.add(kp.key.label())
            plans.append({"label": kp.key.label(), "ref": d.silver_ref, "node": node,
                          "windows": windows, "conventions": blocks, "counter": None})
            if len(plans) >= int(limit):
                return plans
    return plans


def _p0_verdict(out: dict) -> str:
    w = out.get("widths") or {}
    if not w:
        return "declined:no_reads"
    p50s = {k: (v.get("per_read") or {}).get("p50") for k, v in w.items()}
    if any(v is None for v in p50s.values()):
        return "declined:incomplete"
    return ("measured: per-read p50 " + ", ".join(f"w{k}={p50s[k]} ms" for k in sorted(p50s)))


# ---------------------------------------------------------------------------------------------------
# P1 -- THE FALSIFIER
# ---------------------------------------------------------------------------------------------------
def probe_p1(boards: list, *, board: str = P1_BOARD, table: str = P1_TABLE) -> dict:
    """P1: at the census as-of, is ONI the LOUDEST MEASURED state on the soybeans board?

    "MEASURED" is the load-bearing word and it is read off the row rather than assumed: the candidate
    must sit in coverage band 0 or 1 (a series with a z, or a series with a percentile whose z
    declined for zero variance). A text-only or planned row cannot be the loudest measured state by
    construction, and a probe that ranked them together would pass for the wrong reason.

    THE VERDICT IS PER TUPLE AND BOTH ARE REPORTED. If D2 fails and the alternative passes, sec 3.2's
    pre-registered branch applies the alternative and P1 is re-run before S5 -- that branch is a
    DESIGN decision the owner takes on this artifact, so this function states it and never takes it.
    """
    # A BOARD THAT RAISED IS NOT A BOARD P1 CAN READ, and it must not be read as one: an errored
    # record carries no `loud` block, and treating its absence as "ONI did not lead" would fail the
    # falsifier for a reason that has nothing to do with the rank.
    present = [b for b in boards if b.get("contract") == board]
    rows = [b for b in present if b.get("loud")]
    if not rows:
        return {"declined": ("board_errored" if present else "board_absent"), "board": board,
                "errors": [b.get("error") for b in present if b.get("error")]}
    per_mode: dict = {}
    for b in rows:
        loud = b["loud"]
        entry: dict = {"mode": b["mode"], "walked_rule": b["rank_rule"]}
        for rule in ("d2", "alternative"):
            order = (loud.get(rule) or {}).get("order") or []
            measured = [r for r in order if r["coverage_band"] in (0, 1)]
            top = measured[0] if measured else None
            entry[rule] = {
                "top_measured": top,
                "oni_seat": next((r["seat"] for r in order if r.get("table") == table), None),
                "oni_row": next((r for r in order if r.get("table") == table), None),
                "passes": bool(top and top.get("table") == table),
                "top_10": order,
            }
        entry["verdict"] = ("d2" if entry["d2"]["passes"]
                            else ("alternative" if entry["alternative"]["passes"] else "neither"))
        per_mode[b["mode"]] = entry
    modes_pass_d2 = [m for m, e in per_mode.items() if e["d2"]["passes"]]
    modes_pass_alt = [m for m, e in per_mode.items() if e["alternative"]["passes"]]
    return {"board": board, "table": table, "per_mode": per_mode,
            "d2_passes_on": sorted(modes_pass_d2),
            "alternative_passes_on": sorted(modes_pass_alt),
            # WHERE THE ALTERNATIVE VERDICT COMES FROM, said out loud. Both orders here are computed
            # over the rows the D2 walk priced (`_loud_census` ranks the same rows twice; P1 is handed
            # the `pass == 'd2'` records only). That is sound on today's graph -- wave 1 defers zero
            # keys on every board, so the anchor row set is COMPLETE under either tuple and a re-rank
            # cannot reach a row that was never read -- but a reader will otherwise assume P1 consumed
            # the census's separate alternative PASS, which it does not. That pass is rolled up on its
            # own under `summary.alternative_pass`.
            "alternative_ranked_over": "the rows the D2 walk priced (re-ranked arithmetically); "
                                       "sound while wave 1 defers no keys, which summary.per_mode "
                                       "reports per mode",
            "verdict": ("d2" if len(modes_pass_d2) == len(per_mode) and per_mode else
                        ("alternative" if len(modes_pass_alt) == len(per_mode) and per_mode
                         else "neither")),
            "branch": ("none -- the shipped tuple stands"
                       if len(modes_pass_d2) == len(per_mode) and per_mode else
                       "sec 3.2's pre-registered branch: apply the alternative tuple and re-run P1 "
                       "before S5 -- an OWNER decision on this artifact, not taken here")}


# ---------------------------------------------------------------------------------------------------
# P2 -- THE SPAN FENCE (leg B, BLOCKING)
# ---------------------------------------------------------------------------------------------------
def probe_p2(asof: str, *, qfn, windows=P2_WINDOWS, slugs=None) -> dict:
    """P2: does a window of 180 / 270 / 365 days close cleanly on ONE contract, board by board?

    ``analogs.leg_b_rows`` prices a two-to-four-quarter band at ~365 days against
    ``cascade.CW_SPAN_MAX_DAYS`` 270, which is r2-certified to about 267 days with failures measured
    from about 563 -- the gap between them is what this probe closes. The measurement is
    ``outcomes.span_outcome``'s OWN verdict on a real frame, never a re-implementation of it: the
    same function leg B would call, on the same tape, at three spans.

    A DECLINE IS A RESULT. ``span_outcome`` declines by name (``no_anchor_session``, coverage,
    pending) and each of those is the fence saying something different; the artifact carries the word.
    """
    from leviathan.graphrag.numbers import outcomes as OC

    roster = list(slugs or _tape_slugs())
    counter = CountingExecutor(qfn, name="p2")
    per_slug: list = []
    for slug in roster:
        frame, note = _tape_frame_for(slug, asof, qfn=counter)
        row = {"slug": slug, "frame_rows": (0 if frame is None else len(frame)),
               "frame_note": note, "windows": {}}
        for n in windows:
            if frame is None or not len(frame):
                row["windows"][str(n)] = {"status": "declined:no_frame"}
                continue
            t1 = _add_days(asof, -int(n))
            try:
                res = OC.span_outcome(frame, slug=slug, span_start=t1, span_end=asof, asof=asof,
                                      event_key="board_census_p2")
                row["windows"][str(n)] = {
                    "status": str(res.get("status") or ""),
                    "decline_reason": res.get("decline_reason"),
                    "basis": res.get("basis"),
                    "span": [t1, asof],
                    "clean": not str(res.get("status") or "").startswith("declined"),
                }
            except Exception as e:                      # noqa: BLE001
                row["windows"][str(n)] = {"status": f"raised:{type(e).__name__}",
                                          "detail": str(e)[:200], "clean": False}
        per_slug.append(row)

    tally: dict = {}
    for n in windows:
        clean = [r["slug"] for r in per_slug if (r["windows"].get(str(n)) or {}).get("clean")]
        reasons = collections.Counter(
            str((r["windows"].get(str(n)) or {}).get("decline_reason")
                or (r["windows"].get(str(n)) or {}).get("status"))
            for r in per_slug if not (r["windows"].get(str(n)) or {}).get("clean"))
        tally[str(n)] = {"clean": len(clean), "of": len(per_slug),
                         "clean_slugs": sorted(clean),
                         "decline_words": dict(reasons.most_common())}
    fence = None
    for n in sorted(windows, reverse=True):
        if tally[str(n)]["of"] and tally[str(n)]["clean"] == tally[str(n)]["of"]:
            fence = n
            break
    return {"roster": roster, "per_slug": per_slug, "tally": tally,
            "reads": counter.snapshot(),
            "cw_span_max_days": _cw_span_max_days(),
            "widest_window_clean_on_every_board": fence,
            "verdict": (f"leg B may price the full band: {fence} days closes on every board"
                        if fence and fence >= 365 else
                        (f"leg B prices the LOWER end of the band and the row says so: the widest "
                         f"window clean on every board is {fence} days" if fence else
                         "no window is clean on every board; leg B stays dark and the row says so")),
            "blocking_for": "analogs.leg_b_rows (leg B, dark behind its rider)"}


def _cw_span_max_days() -> Optional[int]:
    try:
        from leviathan.graphrag.numbers import cascade as casc
        return int(getattr(casc, "CW_SPAN_MAX_DAYS", 270))
    except Exception:                                   # noqa: BLE001
        return None


def _tape_slugs() -> list:
    """Every board slug that carries a per-contract tape, from the roster the tape row itself reads
    (``futures_eod_contracts.PRICE_COVERAGE_START``) intersected with the graph's contracts."""
    try:
        from leviathan.silver import futures_eod_contracts as FC
        roster = set(FC.PRICE_COVERAGE_START or {})
    except Exception:                                   # noqa: BLE001
        return []
    try:
        contracts = set(load_graph().contracts)
    except Exception:                                   # noqa: BLE001
        contracts = set()
    return sorted(roster & contracts) if contracts else sorted(roster)


_TAPE_FRAMES: dict = {}


def _tape_frame_for(slug: str, asof: str, *, qfn):
    """The tape frame ``outcomes`` consumes, read ONCE per slug and memoized for the run.

    The column shape is ``cascade._tape_frame``'s (``leviathan_slug, trade_date, contract_month,
    settle, unit, currency, settle_kind``) and it is rebuilt here rather than imported because that
    helper is private to a file another lane holds; the SHAPE is the contract and it is asserted by
    the offline deck."""
    key = (slug, asof)
    if key in _TAPE_FRAMES:
        return _TAPE_FRAMES[key]
    try:
        import pandas as pd

        from leviathan.graphrag.numbers import query as Q
        from leviathan.graphrag.numbers.registry import load_registry
        from leviathan.graphrag.state import feeders as F

        load_registry().get(F.TAPE_TABLE)
        spec = F.board_spec(F.TAPE_TABLE, F.TAPE_METRIC, slug, None, asof, "daily")
        rows = Q.run(spec, query_fn=qfn, futures_newest_first="all", ym_lag=True)
        cols = ["leviathan_slug", "trade_date", "contract_month", "settle", "unit", "currency",
                "settle_kind"]
        recs = []
        for r in rows or []:
            kd = (r or {}).get("knowledge_date")
            if not kd:
                continue
            cm = (r or {}).get("contract_month")
            recs.append({"leviathan_slug": str(slug), "trade_date": str(kd)[:10],
                         "contract_month": (None if cm in (None, "") else str(cm)),
                         "settle": (r or {}).get("value"), "unit": (r or {}).get("unit"),
                         "currency": (r or {}).get("currency"),
                         "settle_kind": (r or {}).get("settle_kind")})
        frame = (pd.DataFrame(recs, columns=cols) if recs else pd.DataFrame(columns=cols))
        if len(frame):
            frame = frame.drop_duplicates(
                subset=["leviathan_slug", "trade_date", "contract_month"],
                keep="last").reset_index(drop=True)
        note = f"{len(frame)} rows; cap {getattr(spec, 'limit', None)}"
        _TAPE_FRAMES[key] = (frame, note)
    except Exception as e:                              # noqa: BLE001
        _TAPE_FRAMES[key] = (None, f"{type(e).__name__}: {e}"[:200])
    return _TAPE_FRAMES[key]


def _add_days(iso: str, days: int) -> str:
    return (_dt.date.fromisoformat(str(iso)[:10]) + _dt.timedelta(days=int(days))).isoformat()


# ---------------------------------------------------------------------------------------------------
# P3 -- THE LAG CENSUS
# ---------------------------------------------------------------------------------------------------
def probe_p3(graph) -> dict:
    """P3: every lag declaration in the estate parses to a table key, and the offset bands are applied.

    S0's exit reads "1,412 declarations parse"; the number this run measures is printed beside it and
    neither is adjusted to the other. Zero reads: the whole probe is over loaded YAML."""
    from leviathan.graphrag.state import lagbands as LB

    kinds: collections.Counter = collections.Counter()
    unparsed: list = []
    raws: collections.Counter = collections.Counter()
    bands: collections.Counter = collections.Counter()
    total = 0
    for cname, c in sorted(graph.contracts.items()):
        for d in c.drivers:
            total += 1
            raw = str(getattr(d, "lag", "") or "")
            raws[raw] += 1
            try:
                band = LB.parse_lag(raw)
            except Exception as e:                      # noqa: BLE001
                unparsed.append({"contract": cname, "driver_id": d.id, "lag": raw,
                                 "error": f"{type(e).__name__}: {e}"[:160]})
                continue
            kinds[band.kind] += 1
            if band.kind == "unspecified":
                unparsed.append({"contract": cname, "driver_id": d.id, "lag": raw,
                                 "error": "parsed to kind 'unspecified'"})
            bands[f"{band.min_q}-{band.max_q}"] += 1
    try:
        table_keys = list(LB.table_keys())
    except Exception:                                   # noqa: BLE001
        table_keys = []
    covered = sum(n for raw, n in raws.items() if raw in set(table_keys))
    return {"declarations": total, "by_kind": dict(kinds.most_common()),
            "distinct_lag_strings": len(raws),
            "distinct_bands": dict(bands.most_common()),
            "table_keys": sorted(table_keys),
            "table_key_count": len(table_keys),
            "declarations_hitting_a_table_key": covered,
            "unparsed": unparsed,
            "verdict": ("all declarations parse to a band"
                        if not unparsed else f"{len(unparsed)} declaration(s) do not parse")}


# ---------------------------------------------------------------------------------------------------
# P4 -- THE CALENDAR DRAFT
# ---------------------------------------------------------------------------------------------------
def probe_p4(asof: str, *, horizon_days: int = P4_HORIZON_DAYS) -> dict:
    """P4: ``next_release`` for every calendared card over the next 60 days, printed so the owner can
    eyeball it against the publishers' own statements.

    ``verified_against`` is carried through UNCHANGED. Sec 10.1's exit is "one rule per source,
    ``verified_against`` set only where the owner confirmed a publisher schedule", so a probe that
    filled it in would be the curation the design forbids."""
    from leviathan.graphrag.state import calendar as CAL

    doc = CAL.load_release_calendar()
    sources = dict((doc or {}).get("sources") or {})
    by_table = CAL.table_sources()
    horizon = _add_days(asof, horizon_days)
    rows: list = []
    kinds: collections.Counter = collections.Counter()
    for table in sorted(by_table):
        src = sources.get(by_table[table]) or {}
        try:
            rel = CAL.next_release(table, asof, doc=doc)
        except Exception as e:                          # noqa: BLE001
            rows.append({"table": table, "error": f"{type(e).__name__}: {e}"[:160]})
            continue
        kind = str(getattr(rel, "kind", "") or "")
        kinds[kind or "?"] += 1
        # THE WINDOW'S TWO ENDS, whichever shape the rule printed: `monthly_window` opens/closes, a
        # `weekly_dow` point, a `first_business_day` week, or nothing at all on `daily_sessions` and
        # `published_date`. The probe never invents an end the rule did not compute.
        start = (getattr(rel, "opens", None) or getattr(rel, "date", None)
                 or getattr(rel, "week_of", None))
        end = getattr(rel, "closes", None) or start
        rows.append({"table": table, "kind": kind, "source": getattr(rel, "source", "") or None,
                     "start": start, "end": end,
                     "is_window": bool(start and end and start != end),
                     "within_horizon": bool(start and str(start) <= horizon),
                     "words": getattr(rel, "words", ""),
                     "rule_words": getattr(rel, "rule_words", ""),
                     "declined": getattr(rel, "declined", None),
                     "verified": bool(getattr(rel, "verified", False)),
                     "verified_against": src.get("verified_against"),
                     "verified_on": src.get("verified_on"),
                     "publisher": src.get("publisher") or src.get("name")})
    try:
        uncal = CAL.uncalendared()
    except Exception:                                   # noqa: BLE001
        uncal = {}
    try:
        kind_findings = CAL.check_rule_kinds()
    except Exception as e:                              # noqa: BLE001
        kind_findings = [f"{type(e).__name__}: {e}"[:160]]
    inside = [r for r in rows if r.get("within_horizon")]
    verified = sum(1 for r in rows if r.get("verified_against"))
    declined = [r["table"] for r in rows if r.get("declined")]
    return {"asof": asof, "horizon": horizon, "rules": len(rows),
            "sources": len(sources),
            "by_kind": dict(kinds.most_common()),
            "releases_in_horizon": len(inside),
            "verified_against_set": verified,
            "declined_tables": declined,
            "uncalendared": uncal,
            "rule_kind_findings": kind_findings,
            "rows": rows,
            "verdict": (f"{len(rows)} calendared cards over {len(sources)} sources; {len(inside)} "
                        f"name a release inside the next {horizon_days} days; {verified} carry "
                        f"verified_against (owner curation, sec 10.1); "
                        f"{len(kind_findings)} rule-kind finding(s)")}


# ---------------------------------------------------------------------------------------------------
# P5 -- THE IN-PLACE REVISION MAGNITUDE
# ---------------------------------------------------------------------------------------------------
def probe_p5(asof: str, *, qfn, prior=None) -> dict:
    """P5: does the newest ONI / IOD vintage differ from the prior one, and by how much?

    THE HONEST ANSWER DEPENDS ON WHETHER A PRIOR EXISTS, and this probe says which case it is in
    rather than reporting a zero either way. THREE WITNESSES, in decreasing strength:

      (1) A BANKED PRIOR SNAPSHOT. ``prior`` is the newest ``oni_vintage`` block from an earlier
          board-census artifact. With one in hand the diff is a real vintage-to-vintage measurement
          and the artifact carries the per-(year, month) deltas. Appendix B's "no prior vintage
          exists" is closed by the FIRST run banking one, and by the SECOND run reading it.
      (2) THE INTERNAL LAG WITNESS, available on the FIRST run and every run after. The card carries
          ``oni_lag3 / 6 / 9 / 12`` beside ``oni_anom`` -- lagged copies of the SAME series -- so
          ``oni_lag3(y, m)`` must equal ``oni_anom(y, m - 3)`` if both were computed from one load.
          A mismatch is a value that CHANGED between the two computations, which is an in-place
          revision caught without a second vintage. Silence here is not proof of no revision (both
          columns may simply have been written in one pass) and the artifact says so in those words.
      (3) THE SNAPSHOT ITSELF, banked with a content hash so the next run has a prior.
    """
    from leviathan.graphrag.numbers import query as Q

    counter = CountingExecutor(qfn, name="p5")
    out: dict = {"asof": asof, "tables": {}}
    for table in P5_TABLES:
        rec: dict = {"table": table}
        try:
            rows = counter(
                f"SELECT * FROM {Q.ATHENA_DB}.{table} ORDER BY year, month")
        except Exception as e:                          # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
            out["tables"][table] = rec
            continue
        series: dict = {}
        anom_col = _anom_column(rows)
        for r in rows or []:
            y, m = r.get("year"), r.get("month")
            if y in (None, "") or m in (None, ""):
                continue
            try:
                key = f"{int(y):04d}-{int(m):02d}"
            except (TypeError, ValueError):
                continue
            v = r.get(anom_col) if anom_col else None
            series[key] = (None if v is None else float(v))
        rec["n_periods"] = len(series)
        rec["value_column"] = anom_col
        rec["columns"] = [str(k) for k in ((rows[0] or {}) if rows else {})]
        # AN EMPTY SNAPSHOT IS A DECLINE, NAMED. Without a value column every cell is None, the hash
        # is a hash of nothing, and every FUTURE `_prior_diff` against this vintage is vacuous too --
        # so it is stamped on the record rather than left for a reader to infer from a wall of nulls.
        rec["non_null_values"] = sum(1 for v in series.values() if v is not None)
        if not rows:
            rec["declined"] = "no_rows"
        elif anom_col is None:
            rec["declined"] = "no_value_column"
        elif not rec["non_null_values"]:
            rec["declined"] = "value_column_all_null"
        rec["first"] = min(series) if series else None
        rec["last"] = max(series) if series else None
        rec["hash"] = hashlib.sha256(
            json.dumps(series, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rec["snapshot"] = series
        rec["lag_witness"] = _lag_witness(rows, series, table, anom_col=anom_col)
        prior_block = ((prior or {}).get("tables") or {}).get(table) or {}
        rec["prior"] = _prior_diff(series, prior_block)
        out["tables"][table] = rec
    out["reads"] = counter.snapshot()
    any_prior = any((v.get("prior") or {}).get("compared") for v in out["tables"].values())
    out["verdict"] = _p5_verdict(out, any_prior)
    return out


def _anom_column(rows) -> Optional[str]:
    """The anomaly column on a climate card, by NAME from the row itself. ONI serves ``oni_anom``;
    IOD's own column is discovered rather than assumed, because a probe that hard-coded one card's
    column and fell through to None on the other would report "no revision" for a column it never
    read.

    ``dmi_value`` IS THAT COLUMN ON IOD and it is named here first-class. The live card is
    ``sql/athena/ddl/silver_noaa_iod.sql`` -- ``year, month, date, dmi_value, iod_dmi_3month_avg,
    iod_phase, iod_dmi_ethiopia_lag4, source`` -- so an exact list of ``dmi`` and a suffix rule of
    ``_anom`` / ``_index`` resolved to NOTHING on it, and the whole IOD half of P5 banked an all-None
    snapshot beside the reading "the lag columns and the anomaly column agree everywhere".

    THE DERIVED COLUMNS ARE EXCLUDED BY NAME. ``iod_dmi_3month_avg`` is a rolling mean and
    ``iod_dmi_ethiopia_lag4`` is that mean shifted; either would make the snapshot a smoothed series
    the next vintage's diff could not be read against the source's own revision."""
    if not rows:
        return None
    keys = [str(k) for k in (rows[0] or {})]

    def _derived(k: str) -> bool:
        kl = k.lower()
        return ("lag" in kl or "avg" in kl or "mean" in kl or "_ma" in kl)

    for want in ("oni_anom", "iod_anom", "dmi_value", "dmi", "anom", "value"):
        if want in keys and not _derived(want):
            return want
    for k in keys:
        if not _derived(k) and str(k).lower().endswith(("_anom", "_index")):
            return k
    for k in keys:
        kl = str(k).lower()
        if not _derived(k) and (kl.endswith("_value") or kl.startswith("dmi")):
            return k
    return None


def _lag_base_column(table: str, col: str, keys) -> Optional[str]:
    """The column a lag column is a SHIFT OF, from :data:`LAG_BASE_COLUMNS` first and the card's own
    names second. ``None`` means unmapped, and an unmapped lag column is reported rather than
    compared against a guess."""
    declared = (LAG_BASE_COLUMNS.get(str(table)) or {}).get(str(col))
    if declared and declared in set(keys):
        return declared
    # THE NAME RULE, for a card nobody has declared yet: `<base>_lagN` -> `<base>` when the card
    # actually carries `<base>`. It resolves neither of today's two cards (`oni_lag3` -> `oni`,
    # `iod_dmi_ethiopia_lag4` -> `iod_dmi_ethiopia`, and neither is a column), which is exactly why
    # the declared map above exists and why silence here is reported as UNMAPPED.
    low = str(col).lower()
    i = low.rfind("lag")
    if i > 0:
        stem = str(col)[:i].rstrip("_")
        if stem and stem in set(keys):
            return stem
    return None


def _lag_witness(rows, series: dict, table: str, *, anom_col: Optional[str] = None) -> dict:
    """Witness (2): the card's own lag columns against the column each one is a SHIFT OF.

    NOT against ``series`` blindly. ``series`` is built off the ANOMALY column, and on
    ``silver_noaa_iod`` the one lag column is a shift of the 3-month MEAN, not of ``dmi_value`` --
    so the base is resolved per column (:func:`_lag_base_column`) and read out of the rows
    themselves. A witness that compared every lag column against the anomaly column would report a
    whole-series disagreement on IOD that is arithmetic, not revision.

    AND IT REFUSES TO RUN SILENTLY. With no anomaly column resolved, or with no lag column whose base
    is known, it returns ``available: False`` with the reason -- never ``available: True, checked: 0``
    beside the words "agree everywhere", which is a clean verdict over zero comparisons."""
    if not rows:
        return {"available": False, "why": "no rows"}
    keys = [str(k) for k in (rows[0] or {})]
    if anom_col is None:
        return {"available": False,
                "why": f"no anomaly column resolved on {table} (columns: {sorted(keys)[:12]}) -- "
                       f"nothing could be compared and nothing is claimed"}
    lags = [(k, int(k.split("lag")[-1])) for k in keys
            if "lag" in k.lower() and k.split("lag")[-1].isdigit()]
    if not lags:
        return {"available": False, "why": f"{table} carries no lag columns"}

    bases: dict = {}
    unmapped: list = []
    for col, _n in lags:
        b = _lag_base_column(table, col, keys)
        if b is None:
            unmapped.append(col)
        else:
            bases[col] = b
    if not bases:
        return {"available": False, "columns": [c for c, _ in lags], "unmapped": unmapped,
                "why": f"{table}'s lag column(s) {unmapped} declare no base column in "
                       f"LAG_BASE_COLUMNS and no name rule resolves one -- a guessed base is not a "
                       f"witness"}

    # THE BASE ARRAYS, read from the rows under each base column's OWN name (`series` carries only
    # the anomaly column's).
    by_base: dict = {b: {} for b in set(bases.values())}
    for r in rows or []:
        y, m = r.get("year"), r.get("month")
        try:
            ym = f"{int(y):04d}-{int(m):02d}"
        except (TypeError, ValueError):
            continue
        for b in by_base:
            v = r.get(b)
            by_base[b][ym] = (None if v is None else float(v))

    checked = 0
    mismatches: list = []
    deltas: list = []
    per_column: collections.Counter = collections.Counter()
    for r in rows or []:
        y, m = r.get("year"), r.get("month")
        try:
            y, m = int(y), int(m)
        except (TypeError, ValueError):
            continue
        for col, n in lags:
            base_col = bases.get(col)
            if base_col is None:
                continue
            v = r.get(col)
            if v is None:
                continue
            ym = _shift_month(y, m, -int(n))
            base = (by_base.get(base_col) or {}).get(ym)
            if base is None:
                continue
            checked += 1
            per_column[col] += 1
            d = abs(float(v) - float(base))
            deltas.append(d)
            if d > LAG_WITNESS_TOLERANCE:
                mismatches.append({"period": f"{y:04d}-{m:02d}", "column": col,
                                   "lagged_value": float(v), "base_column": base_col,
                                   "base_at": ym, "base_value": float(base),
                                   "delta": round(d, 6)})
    if not checked:
        return {"available": False, "columns": [c for c, _ in lags], "bases": bases,
                "unmapped": unmapped, "checked": 0,
                "why": f"{table} resolved {len(bases)} lag/base pair(s) but no cell could be "
                       f"compared (every lagged value or its base was null) -- nothing is claimed"}
    return {"available": True, "columns": [c for c, _ in lags], "bases": bases,
            "unmapped": unmapped, "anomaly_column": anom_col,
            "tolerance": LAG_WITNESS_TOLERANCE,
            "checked": checked, "checked_by_column": dict(per_column.most_common()),
            "mismatches": len(mismatches),
            "max_delta": (round(max(deltas), 6) if deltas else None),
            "examples": mismatches[:20],
            "reading": (f"the {len(bases)} lag column(s) agree with the column each is a shift of "
                        f"over {checked} cell(s); this is CONSISTENT with one load and is NOT proof "
                        f"that no in-place revision happened"
                        if not mismatches else
                        f"{len(mismatches)} lagged cell(s) disagree with the column they are a shift "
                        f"of at the same period -- a value changed between the two computations")}


def _shift_month(year: int, month: int, delta: int) -> str:
    idx = (int(year) * 12 + int(month) - 1) + int(delta)
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _prior_diff(series: dict, prior_block: dict) -> dict:
    prior = (prior_block or {}).get("snapshot") or {}
    if not prior:
        return {"compared": False,
                "why": "no prior board-census vintage was banked; this run banks the first"}
    # A DIFF OVER TWO WALLS OF NULLS IS NOT A ZERO REVISION. If either vintage resolved no value
    # column, every cell is None, `changed` is 0 and `max_magnitude` is 0.0 -- a clean number over
    # nothing. It declines by name instead, and the caller's verdict repeats the word.
    if not any(v is not None for v in series.values()):
        return {"compared": False, "prior_hash": prior_block.get("hash"),
                "why": "this run's snapshot carries no values (no value column resolved), so a "
                       "diff against the prior would compare nulls"}
    if not any(v is not None for v in prior.values()):
        return {"compared": False, "prior_hash": prior_block.get("hash"),
                "why": "the PRIOR vintage carries no values (it was banked without a value column), "
                       "so it cannot be diffed against"}
    changed: list = []
    for k, v in sorted(series.items()):
        if k not in prior:
            continue
        pv = prior[k]
        if v is None or pv is None:
            if v != pv:
                changed.append({"period": k, "was": pv, "now": v, "delta": None})
            continue
        d = float(v) - float(pv)
        if abs(d) > 1e-9:
            changed.append({"period": k, "was": float(pv), "now": float(v), "delta": round(d, 6)})
    added = sorted(set(series) - set(prior))
    dropped = sorted(set(prior) - set(series))
    mags = [abs(c["delta"]) for c in changed if c["delta"] is not None]
    return {"compared": True, "prior_hash": prior_block.get("hash"),
            "prior_periods": len(prior), "overlap": len(set(series) & set(prior)),
            "changed": len(changed), "added": added[-12:], "dropped": dropped[-12:],
            "max_magnitude": (round(max(mags), 6) if mags else 0.0),
            "median_magnitude": (round(statistics.median(mags), 6) if mags else 0.0),
            "examples": changed[:20]}


def _p5_verdict(out: dict, any_prior: bool) -> str:
    """P5's one line, and it names the card that could not be measured rather than averaging it in.

    A table that resolved no value column, or whose witness ran zero comparisons, is a card this run
    reports NOTHING about -- and the verdict has to say so, because P5's whole purpose is a magnitude
    and an unmeasured magnitude read as a zero is the finding this probe exists to prevent."""
    words = []
    for t, rec in sorted((out.get("tables") or {}).items()):
        if rec.get("error"):
            words.append(f"{t}: UNMEASURED (the read raised: {rec['error']})")
            continue
        if rec.get("declined"):
            words.append(f"{t}: UNMEASURED ({rec['declined']}; columns "
                         f"{sorted(rec.get('columns') or [])[:8]})")
            continue
        if any_prior:
            p = rec.get("prior") or {}
            if p.get("compared"):
                words.append(f"{t}: {p.get('changed')} period(s) revised, max "
                             f"{p.get('max_magnitude')} over {p.get('overlap')} overlapping period(s)")
            else:
                words.append(f"{t}: no prior banked for this card ({p.get('why')})")
            continue
        lw = rec.get("lag_witness") or {}
        if lw.get("available"):
            words.append(f"{t}: {lw.get('mismatches')} lag-column mismatch(es) over "
                         f"{lw.get('checked')} checks against {sorted(set((lw.get('bases') or {}).values()))}")
        else:
            words.append(f"{t}: NO lag witness ({lw.get('why')})")
    head = ("measured against a banked prior vintage" if any_prior else
            "no prior vintage existed: this run BANKS the first snapshot and reports the internal "
            "lag witness only")
    return head + " -- " + "; ".join(words)


# ---------------------------------------------------------------------------------------------------
# THE ONI CROSSING COUNT -- "the words scenario 2 narrates" (sec 10.1)
# ---------------------------------------------------------------------------------------------------
def probe_oni_crossings(asof: str, *, qfn, ref: str = "oni_climate") -> dict:
    """How many times ONI has crossed a declared desk band since the record starts, and what its
    1-2q and 2-4q projection windows are from the newest crossing.

    Sec 10.1 asks for this by name because scenario 2's TL;DR narrates a COUNT ("the Pacific has been
    here N times before") and a count nobody measured is a number the writer would have to invent.
    ONE READ: the same ONI array every board on the estate folds onto.

    THE CROSSING RULE IS ``analogs.crossings``' OWN, with the convention row from
    ``state_conventions.yaml`` -- not a threshold this module chose. A card with no declared band
    yields the sign-change crossings the same function computes, and the artifact says which it got.
    """
    from leviathan.graphrag.state import analogs as A
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state import lagbands as LB
    from leviathan.graphrag.state.lint import load_conventions
    from leviathan.graphrag.state.rows import status_word

    counter = CountingExecutor(qfn, name="oni_crossings")
    try:
        conv_doc = dict(load_conventions() or {})
    except Exception:                                   # noqa: BLE001
        conv_doc = {}
    node = _LegNode(P1_BOARD, "El_Nino", ref, None)
    st = F.series_state(ref, node, asof, qfn=counter,
                        windows=dict(conv_doc.get("windows") or {}),
                        conventions=dict(conv_doc.get("conventions") or {}))
    out: dict = {"ref": ref, "asof": asof, "status": status_word(st.status),
                 "reads": counter.snapshot()}
    if status_word(st.status) != "ok":
        out["declined"] = st.status
        out["verdict"] = f"the ONI read declined by name: {st.status}"
        return out
    hist = A.state_history(st)
    conv = (conv_doc.get("conventions") or {}).get(ref)
    xs = A.crossings(hist, convention=conv)
    out.update({
        "history_start": (hist.get("dates") or [None])[0],
        "history_end": (hist.get("dates") or [None])[-1],
        "n_periods": len(hist.get("dates") or ()),
        "convention": conv,
        "convention_declared": conv is not None,
        "crossings": len(xs),
        "by_kind": dict(collections.Counter(str(c.get("kind")) for c in xs).most_common()),
        "dates": [str(c.get("date"))[:10] for c in xs],
        "newest": (str(xs[-1].get("date"))[:10] if xs else None),
    })
    # THE TWO CLOSED WINDOWS scenario 2 narrates, projected from the NEWEST crossing (its own anchor
    # date, never the as-of) through the walk's own `projection_window` -- the same arithmetic an
    # SB-J line prints, so the census cannot state a window the render would not.
    from leviathan.graphrag.state import walk as W
    anchor = out["newest"] or str(asof)[:10]
    out["projection_anchor"] = anchor
    out["windows"] = {
        "1_2q": W.projection_window(anchor, LB.LagBand("one to two quarters", "band", 1, 2)),
        "2_4q": W.projection_window(anchor, LB.LagBand("two to four quarters", "band", 2, 4)),
    }
    rule = ("a desk band is declared" if conv else
            "no desk band is declared, so the run-start rule applied")
    out["verdict"] = (f"ONI crossed {len(xs)} time(s) over {out['n_periods']} months from "
                      f"{out['history_start']} ({rule})")
    return out


# ---------------------------------------------------------------------------------------------------
# THE DESTINATION CENSUS -- ESR / FGIS headroom under the 5,000-row cap
# ---------------------------------------------------------------------------------------------------
def destination_census(graph, asof: str, *, qfn) -> dict:
    """The per-slug ESR / FGIS destination counts and the 52-week window's headroom (Appendix B).

    THE WINDOW IS THE BOARD'S OWN. ``feeders.CADENCE_READ_SPAN['weekly_destination']`` is 52 weeks
    and ``DESTINATION_GRAIN_TABLES`` is the pair; the cap is ``feeders.READ_LIMIT`` (5,000), which is
    ``NumberQuery.limit``'s default restated so the truncation detector has a number to compare
    against. Headroom is ``cap - rows``, and a NEGATIVE headroom means the read comes back at its cap
    and the row would be silently truncated -- which is exactly the finding this probe exists for."""
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.state import feeders as F

    counter = CountingExecutor(qfn, name="destinations")
    start = _add_days(asof, -364)
    wanted: dict = {}
    for cname, c in sorted(graph.contracts.items()):
        for d in c.drivers:
            node = _LegNode(cname, d.id, d.silver_ref, d.region)
            try:
                kp = F.series_key_for(d.silver_ref, node)
            except Exception:                           # noqa: BLE001
                continue
            if kp.key is None or kp.table not in F.DESTINATION_GRAIN_TABLES:
                continue
            wanted.setdefault((kp.table, kp.metric, kp.commodity, kp.country), set()).add(cname)

    from leviathan.graphrag.numbers.registry import load_registry

    reg = load_registry()
    rows: list = []
    for (table, metric, commodity, country), boards in sorted(
            wanted.items(), key=lambda kv: (kv[0][0], str(kv[0][2]), str(kv[0][3]))):
        rec = {"table": table, "metric": metric, "commodity": commodity, "country": country,
               "boards": sorted(boards)}
        try:
            # THE COLUMN NAMES COME FROM THE CARD, never from this module. `silver_esr` keys its
            # commodity on `commodity_name` and its destination on `country_code`; `silver_fgis` uses
            # `leviathan_slug` and `destination_country`. A probe that hard-coded one card's columns
            # would count zero rows on the other and report the headroom as infinite.
            ts = reg.get(table)
            com_col = str(getattr(ts, "commodity_col", "") or "")
            dst_col = str(getattr(ts, "country_col", "") or "")
            dat_col = str(getattr(ts, "date_col", "") or "week_ending_date")
            # AND SO DOES THE TABLE NAME. The registry id is the AGENT-FACING name; the physical Glue
            # table (and therefore the pg mirror's table) is `athena_table` when the card declares one
            # -- `silver_esr` serves from `silver_esr_compact` (registry.py:112), and every other read
            # path in the tree resolves it the same way (`query.py:1047` `ts.athena_table or
            # spec.table`; `load_pg_numbers.py:557` `physical = ts.athena_table or ts.id`). Building
            # the FROM out of the id instead raised UndefinedTable on 8 of the 11 destination-grain
            # series -- the ESR half, which is the exact half Appendix B asks this probe about.
            physical = str(getattr(ts, "athena_table", "") or table)
            rec.update({"commodity_col": com_col, "country_col": dst_col, "date_col": dat_col,
                        "physical_table": physical})
            where = [f"{com_col} = {Q._q(str(commodity))}"] if (com_col and commodity) else []
            where.append(f"{dat_col} >= {Q._q(start)}")
            where.append(f"{dat_col} <= {Q._q(asof)}")
            dsel = f"COUNT(DISTINCT {dst_col})" if dst_col else "NULL"
            sql = (f"SELECT COUNT(*) AS n, {dsel} AS destinations "
                   f"FROM {Q.ATHENA_DB}.{physical} WHERE " + " AND ".join(where))
            got = counter(sql)
            n = int((got[0] or {}).get("n") or 0) if got else 0
            dests = (got[0] or {}).get("destinations") if got else None
            rec.update({"rows_52w": n,
                        "destinations": (None if dests is None else int(dests)),
                        "cap": F.READ_LIMIT, "headroom": F.READ_LIMIT - n,
                        "at_cap": n >= F.READ_LIMIT})
        except Exception as e:                          # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        rows.append(rec)
    at_cap = [r for r in rows if r.get("at_cap")]
    headrooms = [r["headroom"] for r in rows if "headroom" in r]
    # AN UNREAD SERIES IS NOT A SERIES UNDER ITS CAP. `at_cap` can only ever count rows that carry the
    # key, so a read that RAISED lands in `rec['error']` and is invisible to it -- which is how a run
    # that measured 3 of 11 series printed the clean verdict over the other 8. The verdict DECLINES BY
    # NAME whenever any row errored, and the caller's settled block reads `errors` beside `at_cap`.
    errored = [r for r in rows if r.get("error")]
    measured = [r for r in rows if "headroom" in r]
    if errored:
        names = ", ".join(f"{r['table']}/{r.get('commodity')}" for r in errored[:6])
        verdict = (f"DECLINED: {len(errored)} of {len(rows)} destination-grain series could NOT be "
                   f"read ({names}{' ...' if len(errored) > 6 else ''}) -- the 5,000-row cap question "
                   f"is UNMEASURED for them; the {len(measured)} series that did read carry "
                   f"min headroom {min(headrooms) if headrooms else None}")
    elif at_cap:
        verdict = (f"{len(at_cap)} series read at the 5,000-row cap and would truncate silently: "
                   + ", ".join(str(r["commodity"]) for r in at_cap))
    else:
        verdict = (f"no ESR / FGIS series reaches the 5,000-row cap in its 52-week window "
                   f"({len(measured)} of {len(rows)} series read)")
    return {"window": [start, asof], "cap": F.READ_LIMIT, "series": len(rows), "rows": rows,
            "reads": counter.snapshot(),
            "measured": len(measured),
            "min_headroom": (min(headrooms) if headrooms else None),
            "at_cap": [r["commodity"] for r in at_cap],
            "errors": [{"table": r["table"], "physical_table": r.get("physical_table"),
                        "commodity": r.get("commodity"), "error": r["error"]} for r in errored],
            "verdict": verdict}


# ---------------------------------------------------------------------------------------------------
# THE FRESH CASCADE CENSUS (sec 10.1(a)) -- the same job, the same as-of
# ---------------------------------------------------------------------------------------------------
def cascade_leg_census(asof: str, *, qfn) -> dict:
    """The fresh HEAD leg census, run in THIS job at THIS as-of (sec 10.1(a), bar B14).

    It is the same ``cascade_census.census`` the rolling baseline reads; only the artifact's home
    changes. The prediction is printed beside the measurement and neither moves toward the other."""
    from leviathan.graphrag.numbers import cascade_census as CC

    t0 = time.perf_counter()
    art = CC.census(asof=asof, query_fn=qfn)
    banner = dict(art.get("banner") or {})
    legs = len(art.get("legs") or [])
    measured = {"legs": legs, "fires": banner.get("fires"), "declines": banner.get("declines"),
                "dark": banner.get("dark"), "probe_errors": banner.get("probe_errors")}
    return {"asof": asof, "ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "measured": measured, "prediction": dict(CASCADE_PREDICTION),
            "matches_prediction": measured == {k: CASCADE_PREDICTION[k] for k in measured},
            "banner": banner,
            "pairs": {"n": len(art.get("pairs") or []),
                      "fire": banner.get("pairs_fire"), "dark": banner.get("pairs_dark"),
                      "warn": banner.get("pairs_warn")},
            "artifact": art}


# ---------------------------------------------------------------------------------------------------
# THE ESTATE PASS
# ---------------------------------------------------------------------------------------------------
def census(*, asof: str = CENSUS_ASOF_DEFAULT, qfn, state_fn_factory=None, tape_fn=None,
           tape_fn_factory=None, modes=MODES, contracts=None, width: int = 2,
           alternative_pass: str = "max", probes=True, prior=None, cascade_legs: bool = True,
           checkpoint=None) -> dict:
    """THE WHOLE BOARD CENSUS. Returns ``{"summary": ..., "boards": [...], "probes": {...}}``.

    ``state_fn_factory(asof, counter) -> state_fn`` is injected so the same pass runs against the pg
    mirror (``_pg_state_fn_factory``) and against ``state.__main__``'s fixtures
    (``_fixture_state_fn_factory``) with no branch inside the census itself.
    ``tape_fn_factory(counter) -> tape_fn`` is the same seam for leg B's reader, and it exists so the
    tape's reads land on the census's OWN executor instead of a second connection nobody counts.

    ``checkpoint(boards, keys)`` IS CALLED THE MOMENT THE LAST BOARD LANDS, before a single probe
    runs. The probe block and the fresh leg census are the long tail of the wall, and an
    ``attemptDurationSeconds`` kill, a put_object failure or the closing ``ATHENA_CALLS == 0`` assert
    would otherwise take 144 finished board runs down with them. It is best-effort by construction: a
    checkpoint that raised would be a writer ending a census it exists to protect.

    THE MEMO IS CLEARED BETWEEN BOARDS, deliberately. With ``GRAPHRAG_STATE_CACHE`` off (the shipped
    default) the memo is a no-op and this changes nothing; with it ON, a board that inherited the
    previous board's arrays would report a read count no cold turn will ever pay. The census measures
    the COLD board, and the memo's value is reported separately by P0's own rungs."""
    from leviathan.graphrag.state import feeders as F

    graph = load_graph()
    roster = sorted(contracts or graph.contracts)
    t_start = time.perf_counter()
    started = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    keys = series_key_census(graph)

    boards: list = []
    read_counter = CountingExecutor(qfn, name="boards")
    factory = state_fn_factory or _pg_state_fn_factory
    tfn = tape_fn if tape_fn is not None else (
        tape_fn_factory(read_counter) if tape_fn_factory else None)
    passes: list = [(m, False) for m in modes]
    if alternative_pass and alternative_pass in modes:
        passes.append((alternative_pass, True))
    for mode, alt in passes:
        for contract in roster:
            F.cache_clear()
            # THE PER-BOARD PHYSICAL READ COUNT, off ONE shared executor. The counter is never reset
            # (the estate roll-up is the sum), so the board's own share is the DELTA across its run --
            # which is the number that makes the memo's value readable per board rather than only
            # estate-wide. Boards run one at a time; the width-2 threads inside one board are the
            # executor's own lock's problem, not this arithmetic's.
            before_reads, before_rows = read_counter.reads, read_counter.rows
            try:
                rec = board_run(graph, contract, mode, asof,
                                state_fn=factory(asof, read_counter),
                                tape_fn=tfn, alternative=alt, width=width)
            except Exception as e:                      # noqa: BLE001 -- one board never ends a census
                rec = {"contract": contract, "mode": mode, "asof": asof,
                       "rank_rule": "alternative" if alt else "d2",
                       "error": f"{type(e).__name__}: {e}"[:400]}
            rec["pass"] = "alternative" if alt else "d2"
            rec["physical_reads_board"] = {"reads": read_counter.reads - before_reads,
                                           "rows": read_counter.rows - before_rows}
            boards.append(rec)

    # THE BOARDS ARE ON DISK BEFORE THE PROBES START (see the docstring): everything below this line
    # is the long tail of the wall and none of it is worth 144 finished board runs.
    if checkpoint is not None:
        try:
            checkpoint(boards, keys)
        except Exception as e:                          # noqa: BLE001
            print(f"board_census: checkpoint FAILED ({type(e).__name__}: {e}) -- the census "
                  f"continues; the artifacts land at the end")

    # THE PG-FREE PROBES ARE NAMED, so an OFFLINE pass runs exactly the ones a fixture can answer
    # and DECLARES the rest rather than reporting them as null-because-nothing-ran.
    want = set(PROBES_ALL if probes is True else (probes or ()))
    probe_block: dict = {}
    if "P0" in want:
        probe_block["P0"] = _guarded(probe_p0, graph, asof, qfn=qfn)
    if "P1" in want:
        probe_block["P1"] = _guarded(probe_p1, [b for b in boards if b.get("pass") == "d2"])
    if "P2" in want:
        probe_block["P2"] = _guarded(probe_p2, asof, qfn=qfn)
    if "P3" in want:
        probe_block["P3"] = _guarded(probe_p3, graph)
    if "P4" in want:
        probe_block["P4"] = _guarded(probe_p4, asof)
    if "P5" in want:
        probe_block["P5"] = _guarded(probe_p5, asof, qfn=qfn, prior=prior)
    if "destinations" in want:
        probe_block["destinations"] = _guarded(destination_census, graph, asof, qfn=qfn)
    if "oni_crossings" in want:
        probe_block["oni_crossings"] = _guarded(probe_oni_crossings, asof, qfn=qfn)
    for name in sorted(set(PROBES_ALL) - want):
        probe_block[name] = {"declined": "not_run_on_this_pass",
                             "why": ("this probe reads the pg mirror and the pass was offline"
                                     if name in PROBES_PG else "excluded by the caller")}
    if cascade_legs:
        probe_block["cascade_census"] = _guarded(cascade_leg_census, asof, qfn=qfn)

    summary = _summarise(asof, boards, keys, probe_block, read_counter,
                         started=started, wall_s=round(time.perf_counter() - t_start, 1),
                         roster=roster, modes=list(modes))
    return {"summary": summary, "boards": boards, "probes": probe_block,
            "series_keys": keys}


def _guarded(fn, *a, **k) -> dict:
    """A probe that raises is a FINDING with a name, never a census that stopped."""
    try:
        return fn(*a, **k)
    except Exception as e:                              # noqa: BLE001
        import traceback
        return {"error": f"{type(e).__name__}: {e}"[:400],
                "traceback": traceback.format_exc()[-1200:]}


def _summarise(asof, boards, keys, probes, counter, *, started, wall_s, roster, modes) -> dict:
    from leviathan.graphrag.state import board as B

    # THE TAPE ROSTER IS A ZERO-READ FACT and is measured here rather than inside P2, so it is on the
    # artifact even when P2 could not run: `futures_eod_contracts.PRICE_COVERAGE_START` intersected
    # with the graph's own contracts is exactly the set `feeders.tape_state` will serve, and its
    # complement is bar B19's "ten tape-less boards" by name.
    with_tape = _tape_slugs()
    tape_roster = {"boards_with_tape": len(with_tape), "with_tape": with_tape,
                   "boards_without_tape": sorted(set(roster) - set(with_tape))}

    ok = [b for b in boards if "error" not in b]
    errored = [{"contract": b["contract"], "mode": b["mode"], "error": b["error"]}
               for b in boards if "error" in b]
    per_mode: dict = {}
    for mode in modes:
        rows = [b for b in ok if b["mode"] == mode and b.get("pass") == "d2"]
        if not rows:
            continue
        reads = sorted(b["budget"]["net_reads"] for b in rows)
        caps = sorted(b["budget"]["declared_cap"] for b in rows)
        lines = sorted(b["render"]["lines"] for b in rows)
        chars = sorted(b["render"]["chars"] for b in rows)
        toks = sorted(b["render"]["est_tokens"] for b in rows)
        rowsn = sorted(b["rows"]["total"] for b in rows)
        kn = B.board_knobs_of(mode)
        per_mode[mode] = {
            "boards": len(rows),
            "net_reads": {"min": reads[0], "median": statistics.median(reads), "max": reads[-1],
                          "sum": sum(reads)},
            "declared_cap": {"min": caps[0], "median": statistics.median(caps), "max": caps[-1]},
            "reads_over_cap": [b["contract"] for b in rows
                               if b["budget"]["net_reads"] > b["budget"]["declared_cap"]],
            "wave1_cap": int(getattr(kn, "wave1", 0) or 0),
            "wave1_binds_on": [b["contract"] for b in rows
                               if b["budget"]["wave1_deferred"]],
            "wave2_binds_on": [b["contract"] for b in rows
                               if b["budget"]["wave2_deferred"]],
            # THE PRICER'S VERDICT PER MODE (sec 10.1: "how many keys each cap drops, NAMED"). The
            # names ride each board's own record; this is the count, so the table is readable.
            #
            # THE CONDITION RIDES THE FIGURE. This wave-2 count is the EFFECTIVE cap's, not the
            # DECLARED one's: `board_run` walks with `legb_on=False` and `analog_reads=False` (it
            # wires no benchmark_fn / receipt_fn, and walk.py:1756 is explicit that reserving those
            # seats would put up to 15 UNSPENDABLE reads on the ceiling). Quoted against sec 3.8's
            # 58 without this line, the number reads like a contradiction instead of a measurement
            # of a different rectangle.
            "keys_dropped": {"wave1": sum(len(b["budget"]["wave1_deferred"]) for b in rows),
                             "wave2": sum(len(b["budget"]["wave2_deferred"]) for b in rows),
                             "boards_capped": sum(1 for b in rows
                                                  if b["budget"]["budget_capped"]),
                             "measured_under": "analogs UNWIRED (analog_reads=False) and leg B DARK "
                                               "(legb_on=False) -- the effective rectangle, not the "
                                               "declared cap"},
            "rectangle_open_on": [b["contract"] for b in rows
                                  if not b["budget"]["rectangle_closed"]],
            "register_trips": sum(b["render"]["trip_count"] for b in rows),
            "register_trip_boards": [b["contract"] for b in rows if b["render"]["trip_count"]],
            "rows": {"min": rowsn[0], "median": statistics.median(rowsn), "max": rowsn[-1]},
            "render_lines": {"min": lines[0], "median": statistics.median(lines),
                             "max": lines[-1]},
            "render_chars": {"min": chars[0], "median": statistics.median(chars),
                             "max": chars[-1]},
            "render_est_tokens": {"min": toks[0], "median": statistics.median(toks),
                                  "max": toks[-1]},
            "sec7_planned_lines": {"quick": "17-20", "deep": "~40", "max": "66-80"}.get(mode),
            "sec7_planned_tokens": {"quick": 1100, "deep": 2400, "max": 3900}.get(mode),
            "class_lines": _merge_counters(b["render"]["by_class_lines"] for b in rows),
            "class_chars": _merge_counters(b["render"]["by_class_chars"] for b in rows),
            "leg_declines": _merge_counters(b["declines"]["leg_declines"] for b in rows),
            "row_status_words": _merge_counters(b["declines"]["row_status_words"] for b in rows),
            "stage_ms": {"1": _ms_summary([b["stage_ms"].get("1", 0.0) for b in rows]),
                         "2": _ms_summary([b["stage_ms"].get("2", 0.0) for b in rows])},
            "total_ms": _ms_summary([b["total_ms"] for b in rows]),
            "walk_ms": _ms_summary([b["walk_ms"] for b in rows]),
            "render_ms": _ms_summary([b.get("render_ms", 0.0) for b in rows]),
            "producers_ms": _ms_summary([b.get("producers_ms", 0.0) for b in rows]),
        }

    trips = sum(b["render"]["trip_count"] for b in ok)
    rect_open = [f"{b['contract']}/{b['mode']}/{b['pass']}" for b in ok
                 if not b["budget"]["rectangle_closed"]]

    # THE ALTERNATIVE PASS IS ROLLED UP HERE OR IT IS 36 RUNS NOTHING READS. `_summarise`'s per-mode
    # table and P1 both filter to `pass == 'd2'` -- correctly, because `_loud_census` computes BOTH
    # orders arithmetically off the one walk, so the D2 pass already carries the alternative RANKING.
    # What the alternative PASS adds is the walk actually taken under that tuple: a different loud
    # set can select different rows to price, which is a different read count and a different render.
    # That delta is the only thing those runs can tell anyone, so it is measured by name.
    alt_rollup: dict = {"ran": False}
    alt_runs = [b for b in ok if b.get("pass") == "alternative"]
    if alt_runs:
        pairs = []
        for b in alt_runs:
            twin = next((d for d in ok if d.get("pass") == "d2"
                         and d["contract"] == b["contract"] and d["mode"] == b["mode"]), None)
            if not twin:
                continue
            a_top = ((b.get("loud") or {}).get("alternative") or {}).get("order") or []
            d_top = ((twin.get("loud") or {}).get("d2") or {}).get("order") or []
            pairs.append({
                "contract": b["contract"], "mode": b["mode"],
                "net_reads_d2": twin["budget"]["net_reads"],
                "net_reads_alt": b["budget"]["net_reads"],
                "lines_d2": twin["render"]["lines"], "lines_alt": b["render"]["lines"],
                "rows_d2": twin["rows"]["total"], "rows_alt": b["rows"]["total"],
                "top_row_d2": (d_top[0].get("driver_id") if d_top else None),
                "top_row_alt": (a_top[0].get("driver_id") if a_top else None),
                "same_top_row": bool(d_top and a_top
                                     and d_top[0].get("driver_id") == a_top[0].get("driver_id")),
            })
        changed = [p for p in pairs if not p["same_top_row"]]
        read_deltas = [p["net_reads_alt"] - p["net_reads_d2"] for p in pairs]
        alt_rollup = {
            "ran": True, "runs": len(alt_runs), "compared": len(pairs),
            "top_row_differs_on": [f"{p['contract']}/{p['mode']}" for p in changed],
            "net_read_delta": {"min": (min(read_deltas) if read_deltas else None),
                               "median": (statistics.median(read_deltas) if read_deltas else None),
                               "max": (max(read_deltas) if read_deltas else None),
                               "sum": sum(read_deltas)},
            "pairs": pairs,
            "verdict": (f"the alternative tuple selects a different top row on {len(changed)} of "
                        f"{len(pairs)} board/mode pair(s); net reads differ by "
                        f"{sum(read_deltas):+d} across the pass"),
        }
    p1 = probes.get("P1") or {}
    p0 = probes.get("P0") or {}
    p2 = probes.get("P2") or {}
    p5 = probes.get("P5") or {}
    p3 = probes.get("P3") or {}
    p4 = probes.get("P4") or {}
    onix = probes.get("oni_crossings") or {}
    dests = probes.get("destinations") or {}
    casc = probes.get("cascade_census") or {}

    settled = {
        "distinct_series_keys_estate": {
            "quoted": UNVERIFIED_CLAIMS["distinct_series_keys_estate"],
            "measured": keys["distinct_keys_estate"]},
        "distinct_series_keys_per_board": {
            "quoted": UNVERIFIED_CLAIMS["distinct_series_keys_per_board"],
            "measured": keys["per_board_keys"]},
        "board_rows_total": {
            "quoted": UNVERIFIED_CLAIMS["board_rows_total"],
            "measured": keys["rows_total"]},
        "wave1_cap_binds": {
            "quoted": UNVERIFIED_CLAIMS["wave1_cap_binds"],
            "measured": {m: {"cap": v["wave1_cap"], "binds_on": v["wave1_binds_on"],
                             "max_board_keys": keys["per_board_keys"]["max"]}
                         for m, v in per_mode.items()}},
        "pg_read_latency_ms": {
            "quoted": UNVERIFIED_CLAIMS["pg_read_latency_ms"],
            "measured": {w: (v.get("per_read") or {}) for w, v in (p0.get("widths") or {}).items()}},
        "pool_contention": {
            "quoted": UNVERIFIED_CLAIMS["pool_contention"],
            "measured": p0.get("contention")},
        "span_fence_365": {
            "quoted": UNVERIFIED_CLAIMS["span_fence_365"],
            "measured": {"tally": p2.get("tally"),
                         "widest_clean": p2.get("widest_window_clean_on_every_board"),
                         "verdict": p2.get("verdict")}},
        "oni_iod_revision_magnitude": {
            "quoted": UNVERIFIED_CLAIMS["oni_iod_revision_magnitude"],
            "measured": p5.get("verdict")},
        "esr_fgis_destination_counts": {
            "quoted": UNVERIFIED_CLAIMS["esr_fgis_destination_counts"],
            # `read` BESIDE `series`, and `errors` beside `at_cap`: a headroom computed over 3 of 11
            # series is not the estate's headroom, and the settled table is the half a reader quotes.
            "measured": {"series": dests.get("series"), "read": dests.get("measured"),
                         "min_headroom": dests.get("min_headroom"),
                         "at_cap": dests.get("at_cap"),
                         "unread": len(dests.get("errors") or []),
                         "verdict": dests.get("verdict")}},
        "per_anchor_line_counts": {
            "quoted": UNVERIFIED_CLAIMS["per_anchor_line_counts"],
            "measured": {m: {"lines": v["render_lines"], "est_tokens": v["render_est_tokens"],
                             "planned_lines": v["sec7_planned_lines"],
                             "planned_tokens": v["sec7_planned_tokens"]}
                         for m, v in per_mode.items()}},
        "cascade_census_split": {
            "quoted": UNVERIFIED_CLAIMS["cascade_census_split"],
            "measured": casc.get("measured")},
        "p1_falsifier": {
            "quoted": UNVERIFIED_CLAIMS["p1_falsifier"],
            "measured": {"verdict": p1.get("verdict"),
                         "d2_passes_on": p1.get("d2_passes_on"),
                         "alternative_passes_on": p1.get("alternative_passes_on")}},
        "lag_declarations_parse": {
            "quoted": UNVERIFIED_CLAIMS["lag_declarations_parse"],
            "measured": {"declarations": p3.get("declarations"),
                         "distinct_lag_strings": p3.get("distinct_lag_strings"),
                         "table_key_count": p3.get("table_key_count"),
                         "unparsed": len(p3.get("unparsed") or [])}},
        "release_calendar_verified": {
            "quoted": UNVERIFIED_CLAIMS["release_calendar_verified"],
            "measured": {"rules": p4.get("rules"), "sources": p4.get("sources"),
                         "verified_against_set": p4.get("verified_against_set"),
                         "releases_in_horizon": p4.get("releases_in_horizon"),
                         "uncalendared": sorted(p4.get("uncalendared") or {})}},
        "tape_roster": {
            "quoted": UNVERIFIED_CLAIMS["tape_roster"],
            "measured": tape_roster},
        "oni_crossing_count": {
            "quoted": UNVERIFIED_CLAIMS["oni_crossing_count"],
            "measured": {"crossings": onix.get("crossings"),
                         "history_start": onix.get("history_start"),
                         "n_periods": onix.get("n_periods"),
                         "windows": onix.get("windows")}},
    }

    # EVERY SETTLED ROW GETS THE ABSENCE-VS-SILENCE WORD ITS PROBE ALREADY HAS. `_probe_word` gives
    # the probe block that discipline and the settled table -- the half a reader quotes -- did not:
    # `pg_read_latency_ms: measured {}` printed beside `P0 DECLINED not_run_on_this_pass` is a row
    # that says "measured" about a probe that never ran.
    _sources = {"pg_read_latency_ms": "P0", "pool_contention": "P0", "span_fence_365": "P2",
                "oni_iod_revision_magnitude": "P5", "esr_fgis_destination_counts": "destinations",
                "p1_falsifier": "P1", "lag_declarations_parse": "P3",
                "release_calendar_verified": "P4", "oni_crossing_count": "oni_crossings",
                "cascade_census_split": "cascade_census"}
    for _name, _rec in settled.items():
        src = _sources.get(_name)
        _rec["source"] = src or "the board pass itself (no probe)"
        if src is None:
            _rec["state"] = "measured"
            continue
        if src not in probes:
            # NOT PRESENT AT ALL is its own case, and it is NOT "ran and found nothing": the cascade
            # leg census is skipped by `--no-cascade-census` and by every offline pass, so its key is
            # simply absent from the block rather than carrying a decline.
            _rec["state"] = f"NOT RUN: {src} was not part of this pass"
            continue
        blk = probes.get(src) or {}
        m = _rec.get("measured")
        if blk.get("declined"):
            _rec["state"] = f"NOT RUN: {src} declined {blk['declined']}"
        elif blk.get("error"):
            _rec["state"] = f"NOT RUN: {src} raised {str(blk['error'])[:120]}"
        elif m in (None, {}, [], ""):
            _rec["state"] = f"{src} ran and this figure came back EMPTY -- a finding, not a zero"
        else:
            _rec["state"] = "measured"

    return {
        "asof": asof, "started_utc": started, "wall_s": wall_s,
        "boards": len(roster), "modes": list(modes), "board_runs": len(boards),
        "alternative_pass": alt_rollup,
        "board_errors": errored,
        "series_keys_estate": keys["distinct_keys_estate"],
        "tape_roster": tape_roster,
        "rows_total": keys["rows_total"],
        "physical_reads": counter.snapshot(),
        "register_trips": trips,
        "register_trips_zero": trips == 0,
        "rectangles_open": rect_open,
        "per_mode": per_mode,
        "athena_calls": _athena_calls(),
        "p1_verdict": p1.get("verdict"),
        "p2_verdict": p2.get("verdict"),
        "p3_verdict": p3.get("verdict"),
        "p4_verdict": p4.get("verdict"),
        "p5_verdict": p5.get("verdict"),
        "p0_verdict": p0.get("verdict"),
        "oni_crossings_verdict": (probes.get("oni_crossings") or {}).get("verdict"),
        "destinations_verdict": dests.get("verdict"),
        "cascade_census": casc.get("measured"),
        "cascade_census_matches_prediction": casc.get("matches_prediction"),
        "settled": settled,
    }


def _merge_counters(dicts) -> dict:
    total: collections.Counter = collections.Counter()
    for d in dicts:
        total.update(d or {})
    return dict(total.most_common())


def _athena_calls() -> int:
    try:
        from leviathan.graphrag.numbers import query as Q
        return len(Q.STATS)
    except Exception:                                   # noqa: BLE001
        return -1


# ---------------------------------------------------------------------------------------------------
# THE STATE-FN FACTORIES -- the mirror and the fixtures, same code path
# ---------------------------------------------------------------------------------------------------
def _pg_state_fn_factory(asof: str, counter):
    """``(ref, node) -> (StateRow, reads)`` over the mirror, through the COUNTING executor."""
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state.lint import load_conventions

    try:
        conv = dict(load_conventions() or {})
    except Exception:                                   # noqa: BLE001
        conv = {}
    windows = dict(conv.get("windows") or {})
    blocks = dict(conv.get("conventions") or {})

    def _fn(ref, node):
        st = F.series_state(ref, node, asof, qfn=counter, windows=windows, conventions=blocks)
        return st, int(getattr(st, "reads", 0) or 0)
    return _fn


def _fixture_state_fn_factory(asof: str, counter):
    """The OFFLINE pass: ``state.__main__``'s fixture arrays, so the census shape is provable with no
    store at all. ``counter`` is accepted and ignored -- there is no mirror to count."""
    from leviathan.graphrag.state.__main__ import fixture_state_fn
    return fixture_state_fn(asof)


def _pg_tape_fn(counter=None):
    """The tape reader for the in-VPC pass, wired from ``feeders.tape_state``.

    IT TAKES THE CENSUS'S OWN COUNTER. Opening a fresh ``board_query_fn()`` per call read the mirror
    behind the executor's back, so the estate banner's ``physical mirror reads N`` undercounted by one
    read per tape board per run (~104 over a 144-run pass) while the per-board ledger -- which takes
    its ``tape_reads`` from the TapeState's own ``.reads`` -- stayed right. Two counts that disagree
    for a reason nobody can name is the one thing a census may not ship."""
    from leviathan.graphrag.state import feeders as F

    inner = counter if counter is not None else F.board_query_fn()

    def _fn(slug, asof):
        try:
            return F.tape_state(slug, asof, qfn=inner)
        except Exception:                               # noqa: BLE001
            return None
    return _fn


# ---------------------------------------------------------------------------------------------------
# THE BANNER (ASCII-ONLY STDOUT -- the Windows console is cp1252 and the container log is not a place
# for a character nobody can grep)
# ---------------------------------------------------------------------------------------------------
def banner(artifact: dict) -> str:
    s = artifact.get("summary") or {}
    probes = artifact.get("probes") or {}
    out: list = []
    A = out.append
    A("# BOARD CENSUS -- as-of " + str(s.get("asof")))
    A("")
    A(f"started {s.get('started_utc')}  wall {s.get('wall_s')} s  "
      f"boards {s.get('boards')}  runs {s.get('board_runs')}  "
      f"ATHENA_CALLS={s.get('athena_calls')}")
    phys = s.get("physical_reads") or {}
    A(f"physical mirror reads {phys.get('reads')} "
      f"(p50 {(phys.get('ms') or {}).get('p50')} ms, max {(phys.get('ms') or {}).get('max')} ms); "
      f"declines {phys.get('declines')}")
    A(f"distinct series keys estate-wide: {s.get('series_keys_estate')}   "
      f"board rows: {s.get('rows_total')}")
    A(f"REGISTER TRIPS: {s.get('register_trips')} (must be 0 -- "
      f"{'PASS' if s.get('register_trips_zero') else 'FAIL'})")
    A(f"OPEN RECTANGLES: {len(s.get('rectangles_open') or [])} "
      f"{(s.get('rectangles_open') or [])[:6]}")
    if s.get("board_errors"):
        A(f"BOARD ERRORS: {len(s['board_errors'])} -> {s['board_errors'][:4]}")
    A("")
    A("## per mode (D2 pass, all boards)")
    A("mode      boards  reads min/med/max  cap  lines min/med/max  tokens med  trips")
    for mode, v in (s.get("per_mode") or {}).items():
        r, ln = v["net_reads"], v["render_lines"]
        A(f"{mode:<9} {v['boards']:>6}  {r['min']:>3}/{r['median']:>5}/{r['max']:>3}      "
          f"{v['declared_cap']['max']:>3}  {ln['min']:>3}/{ln['median']:>5}/{ln['max']:>3}      "
          f"{v['render_est_tokens']['median']:>6}  {v['register_trips']:>4}")
    A("")
    A("## probes")
    for name in PROBES_ALL:
        A(f"{name} {_probe_word(probes.get(name))}")
    p1 = probes.get("P1") or {}
    if p1.get("per_mode"):
        A(f"     P1 detail: d2 passes on {p1.get('d2_passes_on')}, "
          f"alternative on {p1.get('alternative_passes_on')}; branch: {p1.get('branch')}")
    casc = probes.get("cascade_census")
    if not casc:
        A("CASCADE CENSUS not run on this pass (it reads the pg mirror)")
    elif casc.get("error"):
        A(f"CASCADE CENSUS ERROR {casc['error']}")
    else:
        A(f"CASCADE CENSUS measured {casc.get('measured')} vs prediction "
          f"{casc.get('prediction')} -> "
          f"{'MATCH' if casc.get('matches_prediction') else 'DIFFERS'}")
    alt = s.get("alternative_pass") or {}
    if alt.get("ran"):
        A(f"ALTERNATIVE PASS: {alt.get('verdict')}")
    A("")
    A("## the design's UNVERIFIED figures this artifact settles")
    for name, rec in (s.get("settled") or {}).items():
        state = str(rec.get("state") or "measured")
        # THE STATE WORD FIRST: "measured" and "NOT RUN" are different facts and the settled table is
        # the half a reader quotes out of this banner.
        A(f"- {name} [{state}]: {json.dumps(rec.get('measured'), default=str)[:400]}")
        A(f"    quoted: {rec.get('quoted')}")
    return "\n".join(_ascii(x) for x in out)


def _probe_word(block) -> str:
    """A probe's one line: its verdict, its named decline, or its error -- never a bare ``None``.

    A probe that did not run and a probe that ran and found nothing are two different facts, and a
    banner that printed ``None`` for both would be the exact absence-vs-silence confusion this whole
    package refuses everywhere else."""
    b = block or {}
    if b.get("verdict"):
        return str(b["verdict"])
    if b.get("declined"):
        return f"DECLINED {b['declined']} -- {b.get('why', '')}"
    if b.get("error"):
        return f"ERROR {b['error']}"
    return "no verdict (the probe returned a block with none -- a finding)"


def _ascii(s: str) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 or ch in "\n\t" else "?" for ch in str(s))


# ---------------------------------------------------------------------------------------------------
# ARTIFACT IO -- local and s3, per-board plus one summary, the banner beside them
# ---------------------------------------------------------------------------------------------------
def _repo_root():
    """The repo root when this module sits in the tree, ``None`` when it does not.

    IT MUST TOLERATE NOT BEING IN THE TREE (the in-VPC probe law): the jobdef's image predates this
    file, so the run seat uploads it to S3 and the container executes it from ``/tmp`` -- where
    ``parents[4]`` is not a repo and, on a short path, not even a directory. A default that raised
    there would make the artifact path the reason the census could not run."""
    from pathlib import Path
    here = Path(__file__).resolve()
    if len(here.parents) < 5:
        return None
    root = here.parents[4]
    return root if (root / "src" / "leviathan").exists() else None


def artifact_paths(asof: str, root=None):
    from pathlib import Path
    if root:
        return Path(root)
    repo = _repo_root()
    base = (repo if repo is not None else Path.cwd())
    return base / "data" / "board_census" / str(asof)[:10]


def write_artifacts(artifact: dict, asof: str, *, out_dir=None, s3_prefix: str = "") -> list:
    """One JSON per board, one estate summary, one markdown banner. Written LOCALLY always; also to
    S3 when a prefix is given, because an in-VPC container's filesystem is EPHEMERAL and an artifact
    that does not survive the container is an artifact nobody can read (the cascade census's own
    deck-authoring lesson, 2026-08-22)."""
    from pathlib import Path

    base = Path(out_dir) if out_dir else artifact_paths(asof)
    base.mkdir(parents=True, exist_ok=True)
    written: list = []

    def _dump(path, obj, *, text=None):
        body = text if text is not None else json.dumps(obj, indent=1, default=str)
        Path(path).write_text(body, encoding="utf-8", newline="\n")
        written.append(str(path))
        return body

    boards_dir = base / "boards"
    boards_dir.mkdir(parents=True, exist_ok=True)
    for b in artifact.get("boards") or []:
        name = f"{b.get('contract')}__{b.get('mode')}__{b.get('pass', 'd2')}.json"
        _dump(boards_dir / name, b)
    _dump(base / "summary.json", {"summary": artifact.get("summary"),
                                  "series_keys": artifact.get("series_keys")})
    _dump(base / "probes.json", artifact.get("probes"))
    text = banner(artifact)
    _dump(base / "banner.md", None, text=text)

    # THE ARTIFACT'S OWN SIZE, printed rather than discovered at `git add` time: ~57 KB per board file
    # over 144 runs is ~8 MB, and whether that is banked whole or subset is the owner's call to make
    # with the number in front of him.
    total = sum(Path(p).stat().st_size for p in written if Path(p).is_file())
    print(f"board_census: artifact {len(written)} file(s), "
          f"{total / 1048576.0:.2f} MB under {base}")
    if s3_prefix:
        written.append(_mirror_to_s3(written, base, s3_prefix))
    return written


def write_checkpoint(boards, keys, asof: str, *, out_dir=None, s3_prefix: str = "") -> list:
    """The board half of the artifact, written the moment the last board lands and BEFORE any probe.

    It is deliberately the cheap half: the per-board JSONs and a checkpoint header, no banner and no
    summary (both of which read the probe block). :func:`write_artifacts` re-writes the same board
    files at the end, so a completed run is byte-identical whether or not this ever ran."""
    from pathlib import Path

    base = Path(out_dir) if out_dir else artifact_paths(asof)
    boards_dir = base / "boards"
    boards_dir.mkdir(parents=True, exist_ok=True)
    written: list = []
    for b in boards or []:
        name = f"{b.get('contract')}__{b.get('mode')}__{b.get('pass', 'd2')}.json"
        p = boards_dir / name
        p.write_text(json.dumps(b, indent=1, default=str), encoding="utf-8", newline="\n")
        written.append(str(p))
    head = {"checkpoint": True, "asof": asof,
            "written_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "board_runs": len(boards or []),
            "board_errors": [b.get("contract") for b in (boards or []) if b.get("error")],
            "series_keys": keys,
            "why": "the boards are banked before the probe block and the leg census run; the "
                   "summary, the probes and the banner land at the end of the run"}
    p = base / "checkpoint.json"
    p.write_text(json.dumps(head, indent=1, default=str), encoding="utf-8", newline="\n")
    written.append(str(p))
    if s3_prefix:
        written.append(_mirror_to_s3(written, base, s3_prefix))
    print(f"board_census: CHECKPOINT wrote {len(written)} file(s) under {base}")
    return written


def _mirror_to_s3(paths, base, s3_prefix: str) -> str:
    """Every written path under ``base``, put to ``s3://bucket/key/<relative path>``."""
    import re as _re
    from pathlib import Path

    import boto3
    m = _re.match(r"s3://([^/]+)/(.+)", str(s3_prefix).rstrip("/"))
    if not m:
        raise ValueError(f"s3 prefix must look like s3://bucket/key, got {s3_prefix!r}")
    bucket, key_root = m.group(1), m.group(2)
    cli = boto3.client("s3")
    n = 0
    for path in list(paths):
        p = Path(path)
        if not p.exists() or not p.is_file():
            continue
        rel = str(p.relative_to(base)).replace("\\", "/")
        cli.put_object(Bucket=bucket, Key=f"{key_root}/{rel}", Body=p.read_bytes())
        n += 1
    return f"{str(s3_prefix).rstrip('/')}/ (uploaded {n} files)"


def read_prior(spec: str) -> Optional[dict]:
    """A prior P5 block from an EXPLICIT location -- a local path or an ``s3://`` key.

    IT EXISTS BECAUSE :func:`load_prior` CANNOT REACH THE IN-VPC PATH. The container runs this module
    from ``/tmp``, so ``_repo_root()`` correctly returns None and the repo-relative search finds
    nothing: without this flag every in-VPC run, forever, reports "no prior vintage existed" no matter
    how many vintages ``data/board_census/`` holds. The run seat passes the previous run's
    ``probes.json`` and P5 becomes the vintage-to-vintage measurement Appendix B asked for."""
    if not spec:
        return None
    doc: dict
    s = str(spec)
    if s.startswith("s3://"):
        import re as _re

        import boto3
        m = _re.match(r"s3://([^/]+)/(.+)", s)
        if not m:
            raise ValueError(f"--prior must look like s3://bucket/key, got {s!r}")
        body = boto3.client("s3").get_object(Bucket=m.group(1), Key=m.group(2))["Body"].read()
        doc = json.loads(body.decode("utf-8"))
    else:
        from pathlib import Path
        p = Path(s)
        if not p.exists():
            raise SystemExit(f"--prior not found: {p}")
        doc = json.loads(p.read_text(encoding="utf-8"))
    # EITHER SHAPE: a whole probes.json, or the P5 block itself.
    if (doc or {}).get("tables"):
        return doc
    p5 = (doc or {}).get("P5")
    return p5 if (p5 and (p5.get("tables") or {})) else None


def load_prior(asof: str, *, root=None) -> Optional[dict]:
    """The newest earlier board-census P5 block, for the vintage diff. Returns None when there is
    none -- which is the FIRST run's honest answer and is reported as such.

    IN-VPC THIS ALWAYS RETURNS None BY CONSTRUCTION (the module runs from /tmp and there is no repo
    around it); ``--prior`` / :func:`read_prior` is the seam that reaches a banked vintage there."""
    from pathlib import Path

    if root:
        base = Path(root)
    else:
        repo = _repo_root()
        if repo is None:
            return None
        base = repo / "data" / "board_census"
    if not base.exists():
        return None
    days = sorted((p for p in base.iterdir() if p.is_dir() and p.name < str(asof)[:10]),
                  key=lambda p: p.name, reverse=True)
    for d in days:
        f = d / "probes.json"
        if not f.exists():
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            continue
        p5 = (doc or {}).get("P5")
        if p5 and (p5.get("tables") or {}):
            return p5
    return None


# ---------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m leviathan.graphrag.state.board_census",
        description="The board census (design sec 10.1(b), sitting S4): every board, every mode, "
                    "the P0-P5 probes, the fresh leg census. pg-only, zero Athena, zero LLM.")
    ap.add_argument("--asof", default=CENSUS_ASOF_DEFAULT)
    ap.add_argument("--out", default=None, help="local artifact directory")
    ap.add_argument("--s3", default="", help="s3://bucket/prefix to mirror the artifacts to")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--contracts", default="", help="comma-separated subset (default: all 36)")
    ap.add_argument("--width", type=int, default=2)
    ap.add_argument("--alternative-pass", default="max",
                    help="the mode the ALTERNATIVE-tuple pass runs at ('' to skip)")
    ap.add_argument("--offline", action="store_true",
                    help="run against state.__main__'s fixtures; no pg, no env asserts")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--no-cascade-census", action="store_true")
    ap.add_argument("--no-tape", action="store_true")
    ap.add_argument("--prior", default="",
                    help="a previous run's probes.json (local path or s3://...) so P5 measures the "
                         "vintage-to-vintage diff; the repo-relative search cannot reach an in-VPC "
                         "run, which executes this module from /tmp")
    a = ap.parse_args(argv)

    modes = tuple(m.strip() for m in str(a.modes).split(",") if m.strip())
    contracts = [c.strip() for c in str(a.contracts).split(",") if c.strip()] or None

    def _checkpoint(boards, keys):
        write_checkpoint(boards, keys, a.asof, out_dir=a.out, s3_prefix=a.s3)

    if a.offline:
        print("board_census: OFFLINE pass (fixtures; no mirror, no env asserts)")
        art = census(asof=a.asof, qfn=_dead_qfn, state_fn_factory=_fixture_state_fn_factory,
                     tape_fn=None, modes=modes, contracts=contracts, width=a.width,
                     alternative_pass=a.alternative_pass,
                     probes=(() if a.no_probes else PROBES_OFFLINE), cascade_legs=False,
                     prior=read_prior(a.prior), checkpoint=_checkpoint)
        athena_calls = 0
    else:
        env = assert_pg_only()
        print(f"board_census: env {json.dumps(env)}")
        from leviathan.graphrag.state import feeders as F
        qfn = F.board_query_fn()
        prior = read_prior(a.prior) or load_prior(a.asof)
        print(f"board_census: P5 prior vintage {'LOADED' if prior else 'ABSENT'}"
              f"{' from ' + a.prior if (prior and a.prior) else ''}")
        with athena_firewall():
            art = census(asof=a.asof, qfn=qfn, state_fn_factory=_pg_state_fn_factory,
                         tape_fn_factory=(None if a.no_tape else _pg_tape_fn),
                         modes=modes, contracts=contracts, width=a.width,
                         alternative_pass=a.alternative_pass,
                         probes=(() if a.no_probes else PROBES_ALL), prior=prior,
                         cascade_legs=not a.no_cascade_census, checkpoint=_checkpoint)
        # THE FIREWALL'S CLOSING READ IS TAKEN HERE AND JUDGED AFTER THE ARTIFACT IS ON DISK. The
        # tripwire itself is the `athena_firewall` context above, which RAISES at the call; this is
        # the ledger check, and an `assert` at this line would have thrown a whole finished census
        # away over a number the artifact could have carried.
        athena_calls = _athena_calls()

    text = banner(art)
    print(text)
    written = write_artifacts(art, a.asof, out_dir=a.out, s3_prefix=a.s3)
    print(f"board_census: wrote {len(written)} artifact file(s)")
    for w in written[-6:]:
        print(f"  -> {w}")
    if not a.offline and athena_calls != 0:
        print(f"board_census: FAILED -- ATHENA_CALLS is {athena_calls}, expected 0 "
              f"(the artifact is banked above; the run is a FINDING)")
        return 1
    s = art.get("summary") or {}
    bad = (not s.get("register_trips_zero")) or bool(s.get("rectangles_open")) \
        or bool(s.get("board_errors"))
    return 1 if bad else 0


def _dead_qfn(sql: str):
    """The OFFLINE executor: it must never be called, and it says so rather than returning []."""
    raise RuntimeError("board_census --offline made a mirror read; the fixture path is not wired")


if __name__ == "__main__":                              # pragma: no cover
    sys.exit(main())
