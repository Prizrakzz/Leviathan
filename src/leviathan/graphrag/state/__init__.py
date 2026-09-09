"""``leviathan.graphrag.state`` -- THE STATE OF THE WORLD, deterministic at the turn's as-of.

STATE ENGINE DESIGN: ``docs/private/STATE_ENGINE_DESIGN_2026-09-07.md`` (revision 3 + sec 16 owner
decisions). This package is the board: one unsigned state per ``(silver_ref, resolved scope)``, one
row per ``(contract, driver_id)`` instance, one state-driven walk, one narration contract. It is
LANE-FREE by construction -- nothing outside these files is edited until phase 2 -- and it is imported
by NOTHING on the serve path until the ``board=`` kwarg lands at S6.

WHAT EXISTS AT S0 (phase 1a, the dark + live halves, sec 9.2):
  * :mod:`leviathan.graphrag.state.lagbands` -- the lag-band parser over ``lag_bands.yaml`` (sec 2.3)
  * :mod:`leviathan.graphrag.state.lint`     -- ``check_state_board()``: every S0 lint clause, run by
    ``tests/unit/test_state_lint.py`` until ``config_check`` absorbs it after the K9 commit (sec 9.2)

and the four configs they grade: ``configs/graphrag/numbers/{lag_bands, state_conventions,
release_calendar, nass_states}.yaml``, plus the ``board_read`` rows in ``cascade_map.yaml`` and the
``ym_publication_lag_days`` keys on the three ``year_month`` registry cards.

WHAT S1 ADDS (phase 1b, THE PRODUCER, sec 11 row S1):
  * :mod:`leviathan.graphrag.state.rows`       -- ``StateRow`` (sec 1.2), the closed status and coverage
    word sets (1.3), the series key (1.1), and the tier derivation
  * :mod:`leviathan.graphrag.state.transforms` -- ``TRANSFORM_REGISTRY``: names + declared parameters
    over ``stats.py``, and the DERIVATION RECORD that re-executes (2.5). It defines NO stat function:
    the four new leaves (``regime_flag``, ``flag_events``, ``pace_vs_prior``, ``rolling_zscore``) land
    IN ``numbers/stats.py``, outside ``STAT_REGISTRY``, under the AM-3 rule
  * :mod:`leviathan.graphrag.state.feeders`    -- ``series_state()`` through ``query.run`` with an
    explicit window, an explicit cap, newest-first and ``ym_lag=True``; the destination-grain collapse;
    the memo on silverleg's key plus a params hash and the mirror epoch, LRU-bounded; ``tape_state()``
    -- the anchor board's SB-T row, one read (sec 6.2, D19); ``text_state()``; and the OFFLINE HARNESS
    path (``state_from_arrays`` / ``fixture_query_fn``) so every deterministic bar runs with no pg
    mirror

beside them, in files this package does not own: the ``ym_lag`` kwarg threaded through
``numbers/query.py``'s ``build_sql`` / ``run`` / ``apply_pit_filter`` (sec 1.4, D21), and the
``numbers/nass_states.py`` reference loader with its ``_COUNTRY_REF_LOADERS`` entry (sec 2.1).

WHAT S2 ADDS (phase 1b, THE WALK, sec 11 row S2):
  * :mod:`leviathan.graphrag.state.board` -- ``Board`` (sec 1.2's container), ``Anchor`` and the closed
    ``ANCHOR_SOURCES`` (3.1), ``NodeRow``, the two ``WaveLedger`` rectangles (3.8), ``BoardKnobs`` and
    the ELEVEN closed decline enums of 6.7, and ``Board.request()`` -- the ``board=`` payload S6 threads
  * :mod:`leviathan.graphrag.state.walk`  -- the D2 rank tuple and its banked alternative (3.2), the
    loud set's two inclusions, the anchor grammar incl. the amended driver-as-subject and the PRICED
    cold-start read set (3.1), the full ancestor closure with the render cap (3.4), edges / convergence
    proximity / amplifiers (3.5), the FREE fan index and the far-row rule (3.6), dated events and their
    projection windows (3.7), and the TWO priced atomic waves with both rectangles (3.8)

beside them, in a file this package does not own: the nine per-mode board knobs
(``reasoning_modes.BOARD_PRESETS`` / ``board_preset()``), dark by construction -- ``knobs()`` is
untouched, so no shipped preset's knob dict, trace stamp or eval column moves.

WHAT S3 ADDS (phase 1b, ANALOGS + WATCH + RENDER + NARRATION, sec 11 row S3):
  * :mod:`leviathan.graphrag.state.analogs`   -- likeness on the loud drivers' own numeric state
    history (4.1, 4.2), the outcome over the parent's declared band at BOTH ends (4.3, leg A shipped /
    leg B behind its rider), text receipts that EXPLAIN and an absence said plainly (4.4), event
    analogs through ``flag_events`` and the CO-LOUD analog for a driver-as-subject anchor
  * :mod:`leviathan.graphrag.state.calendar`  -- ``next_release()`` over the RULES-only
    ``release_calendar.yaml`` (5.2): a rule prints a WINDOW, never a time, and no future date rides
  * :mod:`leviathan.graphrag.state.watch`     -- the five watch kinds as ONE closed enum, ISO dates and
    no other digits, with the kind-2 distance as a re-executable figure (5.1)
  * :mod:`leviathan.graphrag.state.render`    -- the row classes of 6.2 with one compiled regex each,
    ``SB_MARKER_PREFIX``, the ``_cw_call``-shaped mint of 6.3 and the SB-X replacement fence of 6.6
  * :mod:`leviathan.graphrag.state.narration` -- the mandate literal of 6.4 and the per-layer recency
    constants of 6.5, ASCII, register-linted at build
  * :mod:`leviathan.graphrag.state.__main__`  -- THE OFFLINE HARNESS: the three acceptance scenarios of
    sec 0.3 rendered from fixture arrays on the REAL thirty-six DAGs, with the slot audit and the
    per-class row and token measurement, ASCII stdout, no read and no clock

STILL TO COME (named so each absence is a decision, not a gap): ``conventions.py`` -- the accessor for
``state_conventions.yaml``, whose blocks S1's feeders take as ARGUMENTS and which ``watch.py`` and
``analogs.py`` reach through ``lint.load_conventions`` until it lands; ``board_census.py`` -- S4.

ASCII-ONLY STDOUT is a law here (the Windows console is cp1252): every line any module in this package
PRINTS is ``.encode('ascii')``-safe, while the files themselves stay UTF-8.
"""
from __future__ import annotations

__all__ = ["lagbands", "lint", "rows", "transforms", "feeders", "board", "walk", "analogs",
           "calendar", "watch", "render", "narration"]
