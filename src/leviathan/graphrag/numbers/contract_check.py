"""contract_check (SILVER-C002) -- the numbers-stack I1 vocabulary + value-populatedness gate.

The semantic registry (the numbers `TableSpec` + the cascade `region_map`) declares strings the serving
SQL/cascade layer FILTERS on -- metric names, commodity slugs, country titles, FX currencies. When one of
those strings is not in the physical DISTINCT vocabulary of the served table the query silently returns 0
rows and the answer loses a number with no error -- the WASDE Title-Case class (`'Ending Stocks'` declared,
physical column is `ending_stocks`), the `drought_z` declared-but-zero-row class, and the France->EU /
Cote d'Ivoire resolved-country class the cascade_census only catches at runtime. This module promotes all of
them to a PRE-SERVE gate.

SCOPE (Attack 3, finding #2 -- CONFIRMED-BROKEN if widened): the **numbers / pg-served tables only** -- the
tall/wide tables that are actually in the RDS mirror (WASDE, ESR->esr_compact, PSD, production, weather-z,
FX, ONI). The ~30 feature-only + flat + projection tables are NOT reachable by the pg mirror and are covered
by the FR-001 footer-derived distinct-vocabulary check instead. The projection-trio member present in the
numbers registry (`silver_nasa_power`) is EXCLUDED here (INV-3 forbids an Athena/pg DISTINCT on a projected
partition column -- the Jul-2026 LIST-storm mechanism); the FR-001 footer path owns it.

MECHANISM (mirrors cascade_census, DRY): every DISTINCT probe rides `cascade_census._distinct_set(table,
col, query_fn)` -- ONE `SELECT DISTINCT` against the **pg mirror** via `query_fn`, which MUST be
`pgnumbers.pg_query` (raise-on-failure), never a fallback closure (a pg hiccup would re-run the DISTINCT as a
full-table Athena scan). Wide-table metric names are checked FREE against the physical Glue/registry column
set (metric NAME == column name on a wide table -- no query). The live run installs the same Athena firewall
cascade_census uses and asserts Q.STATS stays empty end-to-end.

    python -m leviathan.graphrag.numbers.contract_check [--json OUT]

Runs IN-VPC in the SAME pg-mirror Batch job as cascade_census (needs GRAPHRAG_NUMBERS_BACKEND=pg +
EVIDENCE_PG_DSN). The pure check functions are import-only, AWS-free, and callable (the silver_rebuild_gate
Branch-A stage 3 calls `contract_check_ex(query_fn=...)` directly).

THE DECLARED, DATED, EXPIRING REGISTER (P3 / B2, 2026-09-22 -- THE WEATHER DEADLOCK). A
declared-but-zero-row TALL metric had exactly one verdict: RED, on every family's gate, forever. That
made a DEADLOCK possible and then real. On 2026-09-15 commit f2aabf90 declared three preliminary-stamp
metrics on `gold_weather_z` (`configs/graphrag/numbers/tables.yaml:1221-1223`); their rows can only reach
the pg mirror through a canonical `silver_chirps` promote; and the ONLY writer of canonical
`silver_chirps` is the promote THIS RED BLOCKS. Six consecutive weather gate FAILs (2026-09-17..22),
chirps/cpc/nasa frozen at 2026-09-16 against a 3-day ceiling, `drought_z` stuck at 2026-07 -- a card that
ran ahead of its producer stopped a family's canonical writes on a schedule with no human in the loop.

So the verdict is now GRADED, and the evidence is A DECLARATION, versioned in git, DATED, ARGUED per
entry and EXPIRING BY ITSELF -- `CARD_AHEAD_OF_PRODUCER` below, in the estate's existing
`cascade_census._WAIVERS` shape. For a declared tall metric the DISTINCT probe finds ABSENT:

  * the (registry table, metric) pair is REGISTERED and today is INSIDE its window -> a WARNING (the
    gate's global_drift / yellow): a human declared this card ahead by hand, on a date, with a reason;
  * anything else -- not registered, or registered and the window has EXPIRED -> RED, byte-identical to
    before, in HEAD's own words. That is every regression, every partial load, every loader-filter drop
    and every card nobody argued for;
  * a register entry that cannot be READ (a malformed date, a malformed value, an empty justification),
    or a caller that asked for no warning sink -> RED, exactly as before. Fail-closed by construction.

WHY NOT AN ALL-TIME ROW COUNT (the round-2 design, REFUTED 2026-09-22 by the reviewer's consistent-mirror
harness). Round 2 graded WARN when the metric's ALL-TIME `COUNT(*)` on the mirror was 0. But
`cascade_census._distinct_set` and that count are TWO UNWINDOWED READS OF THE SAME COLUMN OF THE SAME
TABLE: `DISTINCT(col)` IS, by SQL's own semantics, the set of values with >= 1 row, so "absent from
DISTINCT" and "COUNT(*) = 0" are ONE PREDICATE asked twice. The RED branch was DEAD CODE. MEASURED over
the real registry on a mirror where ONE store answers both statements, dropping each declared tall metric
alone: HEAD reds 51 of 51, round 2 reds 0 of 51 and WARNs 51 -- including `drought_z` itself, the weather
family's flagship, whose loss would have promoted canonical with a green gate. (The round-1 BASELINE
design was refuted before it for different reasons: `pg_rows` is a per-LEG fact blind to 30 of the 42
gradeable tall metrics, and an OLDER baseline is SAFER-looking because rows accrete and a red family
never advances its baseline. Both dead designs are gone from this file, keyword and all.)

WHY THE REGISTER IS SOUND WHERE THE COUNT WAS NOT. It is a DIFFERENT OBSERVATION from the probe -- a
dated human decision in git, not the same SELECT restated. A metric that ever carried rows is never in
the register, so every regression stays RED. It cannot be rescued by AGE, because age is what KILLS an
entry rather than what saves it. And there is NO fetched artifact, NO baseline URI and NO extra query:
the grade issues ZERO SQL, so this module's statement set is byte-identical to HEAD's on every input.

THE YELLOW CHANNEL CLEARS ITSELF, TWO WAYS (the reviewer's MAJOR 2). A WARN is exit 0 by design (D-PR-5),
so `leviathan-dev-gate-verdict-yellow` (`infra/terraform/modules/silver_observability/main.tf:467`,
`GateVerdict{Verdict=PASS_WITH_DRIFT}`, Sum/86400s, threshold 0) is its ONLY delivery mechanism -- and a
finding delivered onto an alarm that never clears is a finding nobody receives. This channel clears when
THE ROWS LAND (the metric enters DISTINCT and stops being graded at all) or when THE WINDOW EXPIRES (the
entry stops warranting a WARN and the gate goes RED again, loudly). There is no third outcome and no
permanent yellow. NOTE, not this lane's to fix: that alarm has been in ALARM continuously since
2026-09-16T23:51 local on the PRE-EXISTING PASS_WITH_DRIFT traffic, docketed separately.

WHAT THIS GRADE DOES NOT CLOSE, STATED RATHER THAN IMPLIED (the reviewer's MAJOR 1, docketed H-L2-2). The
register answers "was this absence declared"; it cannot answer "does a producer exist that will ever emit
this name". That second question belongs to a BUILD-TIME binding, and today
`tests/unit/test_contract_check.py::test_no_tall_card_runs_ahead_of_its_producer` binds exactly ONE card
-- `gold_weather_z` to `weather_z.ALL_METRICS | DERIVED_METRICS`, 18 of the 51 declared tall metric names.
The other 33 (`silver_wasde` 7, `silver_psd_attributes` 20, `silver_production` 3,
`silver_production_livestock` 4) are NAMED as unbound in that test and have no producer roster to bind to
yet. For them the register is the only fence, and it is a human one. H-L2-2 is BLOCKING for the next wave.
What the register does NOT weaken for them: an UNREGISTERED zero-row metric of an ORPHAN table -- one in
NOBODY's `gate_tables`, `silver_production_livestock` being the live example -- still reds EVERY family
through fence (A), exactly as HEAD did (pinned).

THE FAILURE TO FEAR IS A FALSE GREEN, NOT A FALSE RED (census threat model T1), so every unknown resolves
toward RED and the WARNING IS NEVER DROPPED: it keeps the full HEAD error text, gains a suffix naming the
declaration date, the reason and the day the grade expires, and rides back to the caller in the
`warnings` sink (`contract_check_ex`), the artifact and stdout. A fence here CORRECTS or COMPUTES -- it
never deletes. And this register is NOT the "parallel skip list" `_mapped_legs` forbids below: that rule
is about a second LEG waiver table with a second mechanism. This is the vocabulary family's own register,
in `_WAIVERS`' own shape, under `_WAIVERS`' own discipline -- argued per entry, deleted when the premise
dies -- and unlike a waiver it carries a date and dies by itself if nobody deletes it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from leviathan.graphrag.numbers import cascade as casc
from leviathan.graphrag.numbers import cascade_census as cc
from leviathan.graphrag.numbers.registry import load_registry

# The projection-trio member that lives in the numbers registry. NEVER DISTINCT-probed here (INV-3): the
# FR-001 footer-vocabulary check owns every projected table. Excluding it is what makes the "zero Athena
# against projection tables" acceptance structural rather than a runtime hope.
NUMBERS_PROJECTION_TABLES = frozenset({"silver_nasa_power"})  # D-LD review wf_31e951c7: fnc_monthly REMOVED -- C002 DISTINCT-probes the pg MIRROR, not Athena, so excluding a projected table deletes a live existence check for zero LIST-storm benefit (the fgis test two blocks earlier pins exactly this doctrine)


def _physical(ts) -> str:
    """The served Glue/pg table id (silver_esr serves from silver_esr_compact)."""
    return ts.athena_table or ts.id


def _numbers_table_ids(reg) -> list[str]:
    """The pg-served numbers tables C002 owns -- every registry table minus the projection trio."""
    return [tid for tid in sorted(reg.tables) if tid not in NUMBERS_PROJECTION_TABLES]


# ---------------------------------------------------------------------------
# Default Glue-column source for the wide-table metric check (AWS-free): read the F010 silver registry
# physical columns. metric NAME == column name on a wide table, so this is a free membership test.
# ---------------------------------------------------------------------------
def _f010_column_fn():
    """Build a `physical_table -> set[column]` resolver from the F010 silver registry. Falls back to an
    empty-set resolver if the silver registry is unavailable (then the wide-metric check errs conservatively,
    reporting every metric as unresolved rather than passing vacuously)."""
    try:
        from leviathan.silver import registry as sreg
        silver = sreg.load_registry()
    except Exception:  # noqa: BLE001 -- keep C002 usable even if F010 is mid-edit; fail-closed below
        return lambda _t: set()

    def _cols(physical: str) -> set[str]:
        return silver.columns(physical) if physical in silver.tables else set()

    return _cols


# ---------------------------------------------------------------------------
# CARD_AHEAD_OF_PRODUCER (P3 / B2) -- the declared, dated, EXPIRING register. No query, no baseline, no
# fetched artifact, no second SKIP list.
#
# WHAT A DECLARED-BUT-ZERO-ROW TALL METRIC ACTUALLY POSES is not a question the MIRROR can answer. Round 2
# asked the mirror "did this name ever carry a row here" with an all-time `COUNT(*)`, and that is the
# DISTINCT probe restated: `DISTINCT(col)` IS the set of values with >= 1 row, both statements are
# unwindowed reads of the same column of the same table, so the RED branch was unreachable (measured on a
# consistent mirror over the real registry: HEAD reds 51 of 51 declared tall metrics dropped one at a
# time, round 2 reds 0 and WARNs 51 -- `drought_z` included). A mirror snapshot cannot tell a card that
# LEADS its producer from a producer that STOPPED. Only a human can, and only in advance.
#
# SO THE WARRANT IS A DECLARATION, IN `cascade_census._WAIVERS`' OWN SHAPE (that dict is the precedent:
# keys to one-line justifications, argued per entry, DELETED when the premise dies -- five deletions on
# the record). Two differences, both deliberate: the value carries the ISO date the card declared the
# metric, and the entry EXPIRES `PENDING_WINDOW_DAYS` after that date whether or not anybody comes back.
#
#   registered AND today <= declared + PENDING_WINDOW_DAYS   -> GRADE_WARN  (the gate's yellow)
#   not registered, or the window has passed                 -> GRADE_RED   (HEAD's words, byte for byte)
#   the entry cannot be READ (bad date, bad shape, no reason) -> GRADE_RED  (fail-closed, names the class)
#
# WHY THIS CANNOT BECOME A FALSE GREEN. A metric that ever carried rows never enters the register, so a
# producer regression, a partial load and a loader-filter drop all stay RED -- that is the whole class
# round 2 lost. There is nothing to fetch and nothing to go stale: AGE KILLS AN ENTRY, it never rescues
# one. And the grade issues NO SQL, so the statement set this module sends to pg is byte-identical to
# HEAD's on every input -- the ungraded caller (`feature_readiness`) and the gate pay exactly the same.
#
# HOW AN ENTRY LEAVES. Either the rows land -- the metric enters DISTINCT, is never graded again, and the
# entry is DELETED at the next sitting under the `_WAIVERS` discipline -- or the window expires and the
# gate reds again, loudly, on a date the entry itself printed weeks earlier. A dead entry is a defect:
# `test_every_register_entry_names_a_metric_its_card_still_declares` refuses one whose card no longer
# declares the metric, and `test_every_register_entry_is_readable_dated_and_argued` goes RED the day an
# entry's window passes -- so the BUILD is the reminder and nobody has to remember the date.
# ---------------------------------------------------------------------------
GRADE_RED = "red"            # a true regression -- the promote-blocking verdict, HEAD's behaviour
GRADE_WARN = "warn"          # a card ahead by declaration -- the gate's global_drift / yellow

_GRADE_LEDGER = ("grades",)  # cache slot: (tid, metric, grade, reason) per graded finding

# How long a declaration warrants a yellow. 45 days is the observed distance between a card edit and the
# producer release that answers it (f2aabf90 2026-09-15 -> the chirps promote this red blocks), with room
# for one missed release train and none for a forgotten one.
PENDING_WINDOW_DAYS = 45

# (registry_table, metric) -> (ISO date the CARD declared the metric, one-line justification).
# ARGUE EVERY ENTRY. DELETE IT WHEN THE PREMISE DIES. It is not a waiver: it expires.
_PRELIM_WHY = ("rows arrive with the first canonical silver_chirps promote after the gate unblocks; "
               "f2aabf90 declared the stamp before that promote could run")
CARD_AHEAD_OF_PRODUCER: dict[tuple[str, str], tuple[str, str]] = {
    ("gold_weather_z", "drought_z_is_preliminary"): ("2026-09-15", _PRELIM_WHY),
    ("gold_weather_z", "drought_z_preliminary_share"): ("2026-09-15", _PRELIM_WHY),
    ("gold_weather_z", "drought_z_is_preliminary_cells"): ("2026-09-15", _PRELIM_WHY),
}

# The suffixes a graded line carries. BOTH ARE DELIBERATELY FREE OF THE TOKEN ` of <lowercase word>`: the
# gate's `silver_rebuild_gate.implicated_tables` reads every `\bof ([a-z][a-z0-9_]*)` as an implicated
# TABLE, so a casual "ahead of its producer" would enter the attribution set as the table `its` and turn
# the line unattributable -- which the severity split reads as RED-everywhere, i.e. the deadlock again.
# Pinned in the deck against the gate's REAL parser, not a copy of it.
REGISTERED_NOTE = ("DECLARED {declared} in CARD_AHEAD_OF_PRODUCER -- {why} -- graded WARN through "
                   "{expires} and RED from the day after, or the moment the rows land")
UNREADABLE_NOTE = "REGISTER ENTRY UNREADABLE -- graded RED, fail-closed"


def _today():
    """THE ONE CLOCK SEAM. Nothing else in this module reads a date, so a deck can move the register's
    whole window by monkeypatching exactly this."""
    from datetime import date
    return date.today()


def register_window(tid: str, metric: str):
    """`(declared_date, expires_date, justification)` for a REGISTERED pair, else None.

    RAISES on a malformed entry (bad ISO date, wrong shape, empty justification) rather than treating it
    as absent: an entry nobody can read is an unknown, and every unknown here resolves toward RED."""
    from datetime import date, timedelta
    entry = CARD_AHEAD_OF_PRODUCER.get((tid, metric))
    if entry is None:
        return None
    declared_s, why = entry                        # a wrong shape raises here -- fail-closed, on purpose
    declared = date.fromisoformat(str(declared_s))  # a malformed date raises here, likewise
    why = str(why).strip()
    if not why:
        raise ValueError(f"CARD_AHEAD_OF_PRODUCER[({tid!r}, {metric!r})] carries no justification")
    return declared, declared + timedelta(days=PENDING_WINDOW_DAYS), why


def grade_zero_row_metrics(tid: str, metrics, *, today=None) -> dict:
    """`{metric: (grade, suffix, reason)}` for the declared tall metrics the DISTINCT probe found ABSENT.

    REGISTERED and inside the window -> GRADE_WARN, HEAD's text plus the note naming the declaration, the
    reason and the day the yellow dies. Everything else -> GRADE_RED with an EMPTY suffix, so the error
    string stays byte-identical to HEAD. An unreadable entry -> GRADE_RED naming the failure class. There
    is no fourth outcome, no silent one, and no query."""
    out: dict = {}
    today = today or _today()
    for m in metrics:
        try:
            win = register_window(tid, m)
        except Exception as e:  # noqa: BLE001 -- an unreadable declaration is graded, never guessed at
            out[m] = (GRADE_RED, f" [{UNREADABLE_NOTE}: {type(e).__name__}]",
                      f"register entry unreadable ({type(e).__name__})")
            continue
        if win is None:
            out[m] = (GRADE_RED, "", "NOT REGISTERED")          # HEAD's words, byte for byte
            continue
        declared, expires, why = win
        if today > expires:
            out[m] = (GRADE_RED, "", f"registration {declared.isoformat()} EXPIRED {expires.isoformat()}")
            continue
        out[m] = (GRADE_WARN,
                  " [" + REGISTERED_NOTE.format(declared=declared.isoformat(), why=why,
                                                expires=expires.isoformat()) + "]",
                  f"registered {declared.isoformat()}, expires {expires.isoformat()}")
    return out


def grade_ledger(caches) -> list:
    """`[(registry_table, metric, grade, reason)]` in emission order -- the per-metric grade word the gate
    prints plus the register fact that decided it, so a reader of a container log sees WHY a line was
    yellow (or why it was red) and not merely that it was."""
    return list((caches or {}).get(_GRADE_LEDGER, ()) or ())


# ---------------------------------------------------------------------------
# Check family 1 -- metric vocabulary (WASDE Title-Case + drought_z zero-row classes).
# ---------------------------------------------------------------------------
def check_metric_vocabulary(reg, *, query_fn, column_fn=None, caches=None, warnings=None) -> list[str]:
    """Every registry-declared metric of every numbers table exists physically:
      * WIDE table (metric == column): the metric is a real physical column (free Glue/registry check).
      * TALL table (metric == row value): the metric is in DISTINCT(metric_col) on the pg mirror -- which is
        both an existence AND a >=1-row assertion (an absent metric == zero rows, the drought_z class).

    Returns the ERROR list, exactly as it always did. `warnings` is an optional sink list: supply one and
    a tall declared-but-zero-row metric that is REGISTERED in `CARD_AHEAD_OF_PRODUCER` and still inside
    its window is appended to `warnings` instead of `errs` (P3, the register block above). A caller that
    passes no sink gets HEAD's verdict byte for byte -- the grade can only move a finding into a list the
    caller asked for, never delete one, and it never runs for a caller that did not ask. EITHER WAY the
    SQL this function issues is HEAD's, statement for statement: the register costs no query."""
    column_fn = column_fn or _f010_column_fn()
    caches = caches if caches is not None else {}
    errs: list[str] = []
    for tid in _numbers_table_ids(reg):
        ts = reg.get(tid)
        phys = _physical(ts)
        if ts.shape == "wide":
            cols = column_fn(phys)
            for m in ts.metrics:
                if m not in cols:
                    errs.append(f"{tid}: metric column {m!r} is not a physical column of {phys} "
                                f"(declared wide metric absent -- the WASDE Title-Case drift class)")
        else:  # tall
            if not ts.metric_col:
                errs.append(f"{tid}: tall table declares metrics but no metric_col")
                continue
            present = caches.setdefault(("distinct", phys, ts.metric_col),
                                        cc._distinct_set(phys, ts.metric_col, query_fn))
            # The register is read for every absent metric of this CARD, and only when a sink exists.
            # It is keyed by the REGISTRY table id, not the physical: two cards can share one physical
            # (silver_production / silver_production_livestock) and a declaration belongs to the CARD
            # that made it. No query is issued here, on this branch or any other.
            missing = [m for m in ts.metrics if m not in present]
            grades = (grade_zero_row_metrics(tid, missing)
                      if (missing and warnings is not None) else {})
            for m in ts.metrics:          # declaration order preserved: the error list stays HEAD's order
                if m in present:
                    continue
                text = (f"{tid}: metric {m!r} not in DISTINCT {ts.metric_col} of {phys} "
                        f"(declared-but-zero-row -- the drought_z class)")
                grade, suffix, reason = grades.get(m, (GRADE_RED, "", "no warning sink"))
                if grade == GRADE_WARN:
                    warnings.append(text + suffix)
                else:
                    errs.append(text + suffix)
                if m in grades:
                    caches.setdefault(_GRADE_LEDGER, []).append((tid, m, grade, reason))
    return errs


# ---------------------------------------------------------------------------
# Leg enumeration reused by the country + slug checks (topology only; DRY with cascade_census).
# ---------------------------------------------------------------------------
def _mapped_legs():
    """Yield (contract, driver_id, row, node, commodity, country) for every MAPPED causal leg, resolving
    scope with the EXACT production helpers cascade_census replays (`map_row`/`_scope`/`_region_row`). country
    is `casc.SKIP_NODE` for an unresolved/compound region (the leg stays qualitative)."""
    for contract, c in sorted(cc._contract_index().items()):
        for d in c.drivers:
            row = casc.map_row(d.silver_ref)
            if row is None:
                continue
            if (contract, d.id) in cc._WAIVERS:
                # the census's own waiver table (honest data absence, argued per leg) governs HERE
                # too: a waived leg is declared DECLINES-HONESTLY, so flagging its vocabulary as
                # drift re-litigates a recorded decision every gate run (first hit: the sorghum
                # trio, waived 2026-08-21, re-flagged by the 2026-08-22 four-table gate). ONE
                # waiver mechanism, both consumers -- never a parallel skip list.
                continue
            node = cc._LegNode(contract, d.id, d.silver_ref, d.region)
            commodity, country = casc._scope(node, row)
            row2 = casc._region_row(node, row) if country is not casc.SKIP_NODE else row
            yield contract, d.id, row2, node, commodity, country


# ---------------------------------------------------------------------------
# Check family 2 -- country vocabulary (France->EU / Cote d'Ivoire resolved-country class).
# ---------------------------------------------------------------------------
def check_country_vocabulary(reg, *, query_fn, caches=None) -> list[str]:
    """Every country a `country_rule=region` leg RESOLVES to (via region_map) must exist in the DISTINCT
    country set of the numbers table the leg maps to -- the France->EU / Cote d'Ivoire class the cascade
    census catches at runtime, here promoted to a pre-serve gate. Currency-only region legs (fred_fx, no
    country column) and projection tables are skipped."""
    caches = caches if caches is not None else {}
    errs: list[str] = []
    seen: set[tuple] = set()
    for contract, did, row, node, _commodity, country in _mapped_legs():
        if country is casc.SKIP_NODE or country is None:
            continue
        if (row or {}).get("country_rule") != "region":
            continue
        table = (row or {}).get("table")
        if not table or table in NUMBERS_PROJECTION_TABLES:
            continue
        try:
            ts = reg.get(table)
        except Exception:  # noqa: BLE001 -- an unregistered table is check_cascade_map's problem, not C002's
            continue
        ccol = getattr(ts, "country_col", None)
        if not ccol:
            continue  # currency-routed region leg (fred_fx) -- no country vocabulary to assert
        country = str(country)
        key = (table, ccol, country)
        if key in seen:
            continue
        seen.add(key)
        # probe the PHYSICAL table: the leg carries the agent-facing id (silver_esr), which does not
        # exist in the pg mirror -- and on Athena would be the PROJECTED table (the LIST-storm class).
        # Live-caught at the first Branch-A gate fire (BF-W2 step 12.6).
        titles = caches.setdefault(("distinct", _physical(ts), ccol),
                                   cc._distinct_set(_physical(ts), ccol, query_fn))
        # country_name_ref tables (KEYING-KNOB gate fire 5aadd1c9, 2026-08-26): build_sql translates
        # the resolved NAME into the physical value(s) through the card's reference (FAO-3 --
        # 'United States' -> 'United States of America'), so an untranslated compare here red-flags
        # every region leg on such a table while the runtime read is CORRECT. The exact sibling of
        # cascade_census._dark_reason's fix, caught one cloud round later because the first sweep
        # fixed the instance instead of the CLASS. Resolve through the same loader the probe's SQL
        # uses; an unresolvable name still errs -- that is the France->EU class this check names.
        wanted = {country}
        if getattr(ts, "country_name_ref", None):
            try:
                from leviathan.graphrag.numbers import query as _q
                wanted = set(_q._country_ref(ts).resolve_codes(country)) or {country}
            except Exception:  # noqa: BLE001 -- a ref-load failure must not crash a vocab check
                pass
        if not (wanted & titles):
            errs.append(f"{contract}/{did}: region-resolved country {country!r} not in DISTINCT {ccol} "
                        f"of {table} (region_map resolve target absent -- the France->EU class)")
    return errs


# ---------------------------------------------------------------------------
# Check family 3 -- commodity-slug vocabulary (PSD slug-miss / PSD_SLUG_ALIAS class).
# ---------------------------------------------------------------------------
def check_commodity_slug_vocabulary(reg, *, query_fn, caches=None) -> list[str]:
    """Every commodity slug a mapped leg resolves to must exist in the DISTINCT commodity set of the numbers
    table the leg maps to -- the commodity-slug-miss class (silver_psd tracks no cocoa slug; it DOES track
    orange juice since the 2026-08-20 widening re-run, D-EC XC-7).
    Projection tables and slug-less tables (fred_fx/noaa_oni) are skipped."""
    caches = caches if caches is not None else {}
    errs: list[str] = []
    seen: set[tuple] = set()
    for contract, did, row, node, commodity, country in _mapped_legs():
        if country is casc.SKIP_NODE or commodity is None:
            continue
        table = (row or {}).get("table")
        if not table or table in NUMBERS_PROJECTION_TABLES:
            continue
        try:
            ts = reg.get(table)
        except Exception:  # noqa: BLE001
            continue
        scol = getattr(ts, "commodity_col", None)
        if not scol:
            continue
        commodity = str(commodity)
        if table == "silver_psd" and commodity in casc.PSD_UNSERVED_SLUGS:
            continue                          # declared-unserved (cascade SKIPs these legs at _scope)
        if table == "silver_cot" and commodity in casc.COT_UNSERVED_SLUGS:
            continue                          # declared-unserved (cftc_cot.yaml not_covered; SKIPped at _scope)
        key = (table, scol, commodity)
        if key in seen:
            continue
        seen.add(key)
        # PHYSICAL table, same as the country check above (agent id -> served table).
        slugs = caches.setdefault(("distinct", _physical(ts), scol),
                                  cc._distinct_set(_physical(ts), scol, query_fn))
        if commodity not in slugs:
            errs.append(f"{contract}/{did}: commodity slug {commodity!r} not in DISTINCT {scol} "
                        f"of {table} (commodity-slug-miss -- the PSD_SLUG_ALIAS class)")
    return errs


# ---------------------------------------------------------------------------
# The combined check (callable -- the silver_rebuild_gate Branch-A stage-3 entry point).
# ---------------------------------------------------------------------------
def contract_check(reg=None, *, query_fn, column_fn=None, caches=None, warnings=None) -> list[str]:
    """Run all three vocabulary families against the pg mirror and return the combined, ordered list of
    drift ERRORS (empty == green). `query_fn` MUST be pgnumbers.pg_query (or a test mock); `column_fn`
    defaults to the F010 silver-registry column resolver. `caches` is a per-run DISTINCT-set cache so each
    (table, col) is queried at most once (pass one in to share it with a caller).

    `warnings` (a sink list) turns on the P3 register grade for the TALL declared-but-zero-row family
    ONLY -- the country and commodity-slug families are untouched, because their evidence is a resolve
    target, not a declaration, and nothing about them deadlocked. Omit it and the return value is
    byte-identical to HEAD. No form of this call issues an extra query: the register is read from this
    module, never from pg. `contract_check_ex` is the two-list form."""
    reg = reg if reg is not None else load_registry()
    caches = caches if caches is not None else {}
    errs: list[str] = []
    errs += check_metric_vocabulary(reg, query_fn=query_fn, column_fn=column_fn, caches=caches,
                                    warnings=warnings)
    errs += check_country_vocabulary(reg, query_fn=query_fn, caches=caches)
    errs += check_commodity_slug_vocabulary(reg, query_fn=query_fn, caches=caches)
    return errs


def contract_check_ex(reg=None, *, query_fn, column_fn=None, caches=None) -> tuple[list[str], list[str]]:
    """`(errors, warnings)` -- the graded form, and the entry point a gate should call.

    `errors` is promote-blocking and means exactly what it meant before this wave. `warnings` is the
    REGISTERED-and-unexpired set: full text, counted, attributable by the same parser, and NEVER dropped.
    Pass a `caches` dict to read the grade ledger back out (`grade_ledger`) -- the gate prints the grade
    word and the register fact that decided it, per metric."""
    warns: list[str] = []
    errs = contract_check(reg, query_fn=query_fn, column_fn=column_fn, caches=caches, warnings=warns)
    return errs, warns


def _artifact(errs: list[str], *, distinct_queries: int, warnings=(), grades=()) -> dict:
    # The five new keys are ADDITIVE and the existing five are untouched: `verdict` is still PASS/FAIL on
    # ERRORS alone, so every shipped reader of this artifact keeps its meaning (a warning is not a drift
    # the gate must stop for, and inventing a third verdict word would change what PASS means). The
    # register is written out IN FULL beside the grades: a reader six weeks from now must be able to see
    # which declarations were in force without a git checkout, and which day each one dies.
    return {
        "check": "contract_check",
        "package": "SILVER-C002",
        "tables_checked": _numbers_table_ids(load_registry()),
        "projection_excluded": sorted(NUMBERS_PROJECTION_TABLES),
        "distinct_queries": distinct_queries,
        "errors": errs,
        "verdict": "PASS" if not errs else "FAIL",
        "warnings": list(warnings),
        "warning_count": len(list(warnings)),
        "grades": [{"table": t, "metric": m, "grade": g, "reason": r} for t, m, g, r in grades],
        "pending_window_days": PENDING_WINDOW_DAYS,
        "register": _register_rows(),
    }


def _register_rows() -> list:
    """`CARD_AHEAD_OF_PRODUCER` as artifact rows, with the expiry DERIVED rather than restated. An entry
    this function cannot read is emitted with `expires: None` and its reader class named -- the artifact
    never hides what the grade is about to red."""
    rows = []
    for (tid, metric) in sorted(CARD_AHEAD_OF_PRODUCER):
        try:
            declared, expires, why = register_window(tid, metric)
            rows.append({"table": tid, "metric": metric, "declared": declared.isoformat(),
                         "expires": expires.isoformat(), "why": why})
        except Exception as e:  # noqa: BLE001 -- see the docstring: an unreadable entry is shown, not hidden
            rows.append({"table": tid, "metric": metric, "declared": None, "expires": None,
                         "why": f"UNREADABLE ({type(e).__name__})"})
    return rows


def run_live(out_path=None) -> int:
    """The live pg-mirror run: env asserts + Athena firewall + artifact write + non-zero exit on drift. The
    firewall (reused from cascade_census) makes Q.athena_query_fn raise-on-invoke and asserts Q.STATS empty
    -- the observable ZERO-Athena guarantee (projection tables are never even reached).

    The P3 register grade is always on here (this CLI owns both lists); the per-metric grade word and the
    register fact that decided it are printed, never only the verdict."""
    from leviathan.graphrag.numbers import pgnumbers
    assert os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower() == "pg", \
        "contract_check requires GRAPHRAG_NUMBERS_BACKEND=pg (pg-mirror-only by construction)"
    assert os.environ.get("EVIDENCE_PG_DSN"), "contract_check requires EVIDENCE_PG_DSN"
    assert pgnumbers.enabled(), "contract_check requires pgnumbers.enabled() (backend=pg + DSN)"
    caches: dict = {}
    with cc._athena_firewall():
        errs, warns = contract_check_ex(query_fn=pgnumbers.pg_query, caches=caches)
    distinct_queries = sum(1 for k in caches if k and k[0] == "distinct")
    artifact = _artifact(errs, distinct_queries=distinct_queries, warnings=warns,
                         grades=grade_ledger(caches))

    if out_path:
        from pathlib import Path
        dest = Path(out_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(artifact, indent=1), encoding="utf-8")
        print(f"contract_check artifact -> {dest}")

    print(f"contract_check: {len(artifact['tables_checked'])} numbers tables, "
          f"{distinct_queries} DISTINCT probe(s), verdict={artifact['verdict']}")
    print(f"  grade: {len(grade_ledger(caches))} declared-but-zero-row metric(s) graded against a "
          f"{len(CARD_AHEAD_OF_PRODUCER)}-entry register, {PENDING_WINDOW_DAYS}-day window, 0 quer(ies)")
    for tid, metric, grade, reason in grade_ledger(caches):
        print(f"  grade {grade.upper():4s} {tid}.{metric} ({reason})")
    if warns:
        print(f"WARN contract_check: {len(warns)} declared-but-zero-row metric(s) REGISTERED as a card "
              f"ahead by declaration and still inside the window (global_drift, NOT promote-blocking):")
        for w in warns:
            print(f"  ~ {w}")
    if errs:
        print(f"FAIL contract_check: {len(errs)} vocabulary drift(s):")
        for e in errs:
            print(f"  - {e}")
    return 1 if errs else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="contract_check (SILVER-C002): numbers-stack I1 vocabulary gate")
    ap.add_argument("--json", dest="out", default=None, help="artifact output path (optional)")
    a = ap.parse_args(argv)
    return run_live(a.out)


if __name__ == "__main__":
    sys.exit(main())
