"""D-SG G1-9 -- the declared-gap ledger in front of the per-day silver row floor.

Seven of the fourteen days' 41 failed scheduled executions were ONE missing slug-day: Euronext
never published EMA-DPAR for 2026-08-05, and the nightly floor re-failed on it every fire until the
day rolled out of the 5-day lookback. The floor was right every time; the REPETITION was the
defect, and seven identical reds are seven chances to stop reading the alarm.

What is pinned here is the shape of the cure, not just the cure: an UNDECLARED missing slug-day
still fails on the first fire exactly as it did before; a DECLARED day leaves the arithmetic only
while its slug is genuinely absent; a declared gap never speaks for another venue's leg; and a
ledger row that cannot be read is a hard error rather than a quietly skipped excuse.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[3]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_gaps")
EURONEXT = TASK.source_spec("euronext")

_MATIF = ("french_wheat_matif", "french_maize_matif", "french_rapeseed_matif")
_GAP_DAY = "2026-08-05"
# the gap day as the venue actually served it: wheat and rapeseed, no maize.
_WITHOUT_MAIZE = ("french_wheat_matif", "french_rapeseed_matif")


def _euronext_frame(day_to_slugs: dict[str, tuple[str, ...]], per_slug: int = 11
                    ) -> pd.DataFrame:
    """One euronext silver frame: ``{day: (slug, ...)}`` x ``per_slug`` delivery months each."""
    recs = [{"trade_date": pd.Timestamp(day), "leviathan_slug": slug,
             "source": "euronext_matif", "contract_month": f"2026-{m + 1:02d}"}
            for day, slugs in day_to_slugs.items() for slug in slugs for m in range(per_slug)]
    return pd.DataFrame(recs)


class TestTheFenceStaysHonest:
    def test_an_undeclared_missing_slug_day_still_fails_on_the_first_fire(self):
        df = _euronext_frame({"2026-08-04": _MATIF, _GAP_DAY: _WITHOUT_MAIZE})
        bad = TASK.assert_row_floor(df, EURONEXT, mode="incremental", declared_gaps={})
        assert len(bad) == 1 and bad[0].startswith(_GAP_DAY)

    def test_a_declared_day_whose_slug_did_publish_is_judged_like_any_other(self):
        # A stale ledger row must not excuse a real shortfall: maize published, wheat did not.
        df = _euronext_frame({_GAP_DAY: ("french_maize_matif", "french_rapeseed_matif")})
        bad = TASK.assert_row_floor(df, EURONEXT, mode="incremental",
                                    declared_gaps={_GAP_DAY: frozenset({"french_maize_matif"})})
        assert len(bad) == 1 and bad[0].startswith(_GAP_DAY)

    def test_another_legs_declared_gap_never_excuses_this_leg(self):
        df = _euronext_frame({_GAP_DAY: _MATIF[:2]})
        bad = TASK.assert_row_floor(df, EURONEXT, mode="incremental",
                                    declared_gaps={_GAP_DAY: frozenset({"corn_cbot"})})
        assert len(bad) == 1 and bad[0].startswith(_GAP_DAY)

    def test_a_second_shortfall_on_an_undeclared_day_is_untouched_by_the_ledger(self):
        df = _euronext_frame({_GAP_DAY: _WITHOUT_MAIZE, "2026-08-06": _MATIF[:1]})
        bad = TASK.assert_row_floor(df, EURONEXT, mode="incremental",
                                    declared_gaps={_GAP_DAY: frozenset({"french_maize_matif"})})
        assert len(bad) == 1 and bad[0].startswith("2026-08-06")


class TestTheRepetitionDies:
    def test_a_declared_absent_slug_day_leaves_the_arithmetic(self):
        df = _euronext_frame({"2026-08-04": _MATIF, _GAP_DAY: _WITHOUT_MAIZE})
        assert TASK.assert_row_floor(df, EURONEXT, mode="incremental",
                                     declared_gaps={_GAP_DAY: frozenset({"french_maize_matif"})}
                                     ) == []

    def test_the_exclusion_is_logged_by_name(self, caplog):
        df = _euronext_frame({_GAP_DAY: _WITHOUT_MAIZE})
        with caplog.at_level(logging.WARNING, logger="futures_eod_task"):
            TASK.assert_row_floor(df, EURONEXT, mode="incremental",
                                  declared_gaps={_GAP_DAY: frozenset({"french_maize_matif"})})
        msg = "\n".join(r.getMessage() for r in caplog.records)
        assert "EXCLUDED" in msg and "french_maize_matif" in msg and _GAP_DAY in msg
        assert "futures_gaps.yaml" in msg

    def test_the_committed_ledger_carries_the_ema_dpar_day(self):
        # The default path IS the fence's own configuration -- no argument, the real file.
        gaps = TASK.load_declared_gaps()
        assert gaps.get(_GAP_DAY) == frozenset({"french_maize_matif"})

    def test_the_committed_ledger_is_what_the_floor_uses_by_default(self):
        df = _euronext_frame({_GAP_DAY: _WITHOUT_MAIZE})
        assert TASK.assert_row_floor(df, EURONEXT, mode="incremental") == []


class TestTheLedgerFailsClosed:
    def _write(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "futures_gaps.yaml"
        p.write_text(body, encoding="utf-8")
        return p

    _GOOD = ("- slug: french_maize_matif\n"
             "  day: \"2026-08-05\"\n"
             "  first_observed: \"2026-08-05\"\n"
             "  evidence: venue published no rows\n"
             "  declared_by: D-SG G1-9\n")

    def test_a_well_formed_row_loads(self, tmp_path):
        assert TASK.load_declared_gaps(self._write(tmp_path, self._GOOD)) == {
            "2026-08-05": frozenset({"french_maize_matif"})}

    def test_an_absent_file_means_nothing_declared(self, tmp_path):
        assert TASK.load_declared_gaps(tmp_path / "nope.yaml") == {}

    @pytest.mark.parametrize("body, why", [
        (_GOOD.replace("  declared_by: D-SG G1-9\n", ""), "missing field"),
        (_GOOD.replace("  evidence: venue published no rows\n", "  evidence: ''\n"), "no evidence"),
        (_GOOD.replace("french_maize_matif", "not_a_slug"), "unknown slug"),
        (_GOOD.replace('day: "2026-08-05"', 'day: "the fifth"'), "unparseable date"),
        (_GOOD + _GOOD, "the same gap declared twice"),
        ("slug: french_maize_matif\n", "not a list"),
    ])
    def test_a_malformed_ledger_is_a_hard_error(self, tmp_path, body, why):
        with pytest.raises(ValueError):
            TASK.load_declared_gaps(self._write(tmp_path, body))

    def test_an_empty_ledger_is_legal(self, tmp_path):
        assert TASK.load_declared_gaps(self._write(tmp_path, "# nothing declared\n")) == {}
