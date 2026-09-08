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

STILL TO COME (named so each absence is a decision, not a gap): ``conventions.py`` -- the accessor for
``state_conventions.yaml``, whose blocks S1's feeders take as ARGUMENTS rather than read for themselves
-- then ``board.py``, ``walk.py``, ``analogs.py``, ``watch.py``, ``calendar.py``, ``render.py``,
``narration.py``, ``__main__.py`` -- S2 and S3.

ASCII-ONLY STDOUT is a law here (the Windows console is cp1252): every line any module in this package
PRINTS is ``.encode('ascii')``-safe, while the files themselves stay UTF-8.
"""
from __future__ import annotations

__all__ = ["lagbands", "lint", "rows", "transforms", "feeders"]
