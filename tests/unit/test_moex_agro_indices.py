"""MOEX agro indices -- the Russian grain indicative-price family. Hermetic: no network, no AWS.

``iss.moex.com`` answers from AWS and NOT from this machine (probed 2026-08-20: local http=000,
AWS 200), so every fixture under ``tests/fixtures/moex/`` was assembled from values an AWS-side probe
job measured. See that directory's ``capture_notes.md`` for exactly which cells are MEASURED and
which are null-by-construction.

The facts these tests exist to pin are the ones that would otherwise produce a plausible WRONG NUMBER
rather than an error:

  * ISS rows are POSITIONAL under a ``columns`` list, so a positional decode through an inserted
    column would silently re-label ``CLOSE`` as ``LOW``;
  * this family serves TWO currencies -- WHFOB prints ~229 USD/t beside WHCPT at ~12,000 RUB/t -- so
    a fixed-unit schema files one as the other, two orders of magnitude out;
  * an EMPTY history is DATA (a dormant index), and reading it as a failure would take down a leg
    every day that WH4CPTNOV stays quiet;
  * the raw key is dated by the payload's own ``TRADEDATE``, so first-capture-wins is meaningful --
    a fetch-dated key would mint a new object every run over the same window;
  * and no duty constant may be hardcoded anywhere in the package (FOLLOW-UP MOEX-DUTY-1).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml
from leviathan.storage.paths import (
    moex_agro_indices_secid_prefix,
    raw_moex_agro_indices_key,
)
from leviathan.transforms.bronze_to_silver import moex_agro_indices as S
from leviathan.transforms.raw_to_bronze import moex_agro_indices as T

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "tests" / "fixtures" / "moex"
_WHFOB = _FIXTURES / "history_WHFOB_2026-08-03_2026-08-19.json"
_WHCPT = _FIXTURES / "history_WHCPT_2026-08-03_2026-08-20.json"
_EMPTY = _FIXTURES / "history_WH4CPTNOV_empty.json"
_PAGE1 = _FIXTURES / "history_SYNTHETIC_paged_page1.json"
_PAGE2 = _FIXTURES / "history_SYNTHETIC_paged_page2.json"
_NOCURSOR = _FIXTURES / "history_SYNTHETIC_nocursor_page1.json"


def _load_script(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FETCH = _load_script("jobs/ingest/fetch_moex_agro_indices.py", "fetch_moex_agro_indices")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# The MEASURED values, restated here independently of the fixture builder so a corrupted fixture
# fails the test rather than agreeing with itself.
WHFOB_CLOSES = [
    ("2026-08-03", 230.1), ("2026-08-04", 229.8), ("2026-08-05", 230.7), ("2026-08-06", 230.4),
    ("2026-08-07", 230.4), ("2026-08-10", 231.1), ("2026-08-11", 231.5), ("2026-08-12", 231.4),
    ("2026-08-13", 231.4), ("2026-08-14", 230.2), ("2026-08-17", 229.3), ("2026-08-18", 229.3),
    ("2026-08-19", 229.3),
]
WHCPT_CLOSES = [
    ("2026-08-03", 14050.0), ("2026-08-04", 13991.0), ("2026-08-05", 13820.0),
    ("2026-08-06", 14000.0), ("2026-08-07", 13792.0), ("2026-08-10", 13716.0),
    ("2026-08-11", 13437.0), ("2026-08-12", 13437.0), ("2026-08-13", 13437.0),
    ("2026-08-14", 13437.0), ("2026-08-17", 12491.0), ("2026-08-18", 11400.0),
    ("2026-08-19", 11000.0), ("2026-08-20", 11000.0),
]


# ---------------------------------------------------------------------------
# The ISS envelope decode -- exact values, by name.
# ---------------------------------------------------------------------------
def test_whfob_fixture_parses_to_the_exact_measured_closes():
    rows = T.parse_history_rows(_read(_WHFOB), context="WHFOB")
    assert len(rows) == len(WHFOB_CLOSES) == 13
    got = [(r[T.COL_TRADEDATE], r[T.COL_CLOSE]) for r in rows]
    assert got == WHFOB_CLOSES
    assert {r[T.COL_CURRENCYID] for r in rows} == {"USD"}
    assert {r[T.COL_BOARDID] for r in rows} == {"RTSI"}
    assert {r[T.COL_SECID] for r in rows} == {"WHFOB"}


def test_whcpt_fixture_parses_to_the_exact_measured_closes():
    rows = T.parse_history_rows(_read(_WHCPT), context="WHCPT")
    assert len(rows) == len(WHCPT_CLOSES) == 14
    got = [(r[T.COL_TRADEDATE], float(r[T.COL_CLOSE])) for r in rows]
    assert got == WHCPT_CLOSES
    assert {r[T.COL_CURRENCYID] for r in rows} == {"RUB"}
    assert {r[T.COL_BOARDID] for r in rows} == {"AGRO"}


def test_the_two_indices_are_different_currencies_and_different_orders_of_magnitude():
    """The unit decision, stated as a test: a fixed-unit schema would file one as the other."""
    fob = T.parse_history_rows(_read(_WHFOB))
    cpt = T.parse_history_rows(_read(_WHCPT))
    assert {r[T.COL_CURRENCYID] for r in fob} == {"USD"}
    assert {r[T.COL_CURRENCYID] for r in cpt} == {"RUB"}
    assert max(float(r[T.COL_CLOSE]) for r in fob) < 250
    assert min(float(r[T.COL_CLOSE]) for r in cpt) > 10_000


def test_columns_are_read_by_name_not_by_position():
    """A venue that reorders (or inserts) columns must not re-label a single value."""
    doc = _read(_WHFOB)
    columns = doc["history"]["columns"]
    order = list(reversed(range(len(columns))))
    doc["history"]["columns"] = [columns[i] for i in order]
    doc["history"]["data"] = [[row[i] for i in order] for row in doc["history"]["data"]]
    rows = T.parse_history_rows(doc)
    assert [(r[T.COL_TRADEDATE], r[T.COL_CLOSE]) for r in rows] == WHFOB_CLOSES


def test_an_inserted_unknown_column_is_kept_and_never_fatal():
    doc = _read(_WHFOB)
    doc["history"]["columns"].insert(3, "RECALC_DATE")
    for row in doc["history"]["data"]:
        row.insert(3, "2026-08-20")
    rows = T.parse_history_rows(doc)
    assert [(r[T.COL_TRADEDATE], r[T.COL_CLOSE]) for r in rows] == WHFOB_CLOSES
    assert rows[0]["RECALC_DATE"] == "2026-08-20"


@pytest.mark.parametrize("column", list(T.REQUIRED_HISTORY_COLUMNS))
def test_a_missing_required_column_fails_closed(column):
    doc = _read(_WHFOB)
    idx = doc["history"]["columns"].index(column)
    doc["history"]["columns"].pop(idx)
    for row in doc["history"]["data"]:
        row.pop(idx)
    with pytest.raises(ValueError, match="missing"):
        T.parse_history_rows(doc)


def test_a_row_narrower_than_the_column_list_fails_closed():
    doc = _read(_WHFOB)
    doc["history"]["data"][0] = doc["history"]["data"][0][:-1]
    with pytest.raises(ValueError, match="cell"):
        T.parse_history_rows(doc)


def test_a_missing_history_block_is_never_read_as_no_rows():
    # An ISS error document, an HTML interstitial or a renamed block all arrive shaped like this,
    # and none of them may be read as "no sessions today" -- that is how a source outage becomes a
    # gap nobody notices.
    with pytest.raises(ValueError, match=r"carries no 'history' block"):
        T.parse_history_rows({"securities": {"columns": [], "data": []}})


# ---------------------------------------------------------------------------
# The DORMANT index: empty history is DATA.
# ---------------------------------------------------------------------------
def test_dormant_index_empty_history_is_zero_rows_and_no_error():
    doc = _read(_EMPTY)
    rows = T.parse_history_rows(doc, context="WH4CPTNOV")
    assert rows == []
    assert T.observations_from_rows(rows, secid="WH4CPTNOV") == []
    assert T.next_start(doc, start=0, rows_received=0) is None
    assert "WH4CPTNOV" in T.DORMANT_SECIDS


def test_dormant_index_produces_an_empty_silver_frame_with_the_full_column_set():
    out = S.transform_moex_agro_indices_bronze_to_silver([])
    assert list(out.columns) == S.SILVER_COLUMNS
    assert len(out) == 0


def test_the_run_loop_reports_a_dormant_secid_as_exit_zero_and_writes_a_log_line(caplog, monkeypatch):
    """Zero rows -> zero objects, one written line, exit 0. NOT an error."""
    calls = {"landed": 0}

    class _EmptyClient:
        calls = 0

        def get_json(self, url, params):
            return _read(_EMPTY)

    monkeypatch.setattr(FETCH, "raw_exists", lambda *a, **k: False)
    monkeypatch.setattr(FETCH, "land_bytes",
                        lambda *a, **k: calls.__setitem__("landed", calls["landed"] + 1))

    with caplog.at_level("INFO"):
        rc = FETCH.run(client=_EmptyClient(), secids=["WH4CPTNOV"], date_from="2026-08-01",
                       date_till="2026-08-20", bucket="b", region="us-east-1",
                       skip_existing=False, mode="daily")
    assert rc == 0
    assert calls["landed"] == 0
    text = caplog.text
    assert "ZERO history rows" in text
    assert "WH4CPTNOV" in text
    assert "DORMANT" in text


# ---------------------------------------------------------------------------
# Paging.
# ---------------------------------------------------------------------------
def test_cursor_block_decodes():
    cursor = T.history_cursor(_read(_PAGE1))
    assert cursor == {"INDEX": 0, "TOTAL": 5, "PAGESIZE": 3}


def test_next_start_follows_the_cursor_and_then_stops():
    page1, page2 = _read(_PAGE1), _read(_PAGE2)
    assert T.next_start(page1, start=0, rows_received=3) == 3
    assert T.next_start(page2, start=3, rows_received=2) is None


def test_iter_pages_walks_a_two_page_cursor_fixture():
    served = {0: _read(_PAGE1), 3: _read(_PAGE2)}
    seen: list[int] = []

    def fetch_page(start: int):
        seen.append(start)
        return served[start]

    rows = T.iter_pages(fetch_page, secid="SYNTH1")
    assert seen == [0, 3]
    assert len(rows) == 5
    assert [r[T.COL_TRADEDATE] for r in rows] == [
        "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
    ]


def test_iter_pages_falls_back_to_the_row_count_walk_without_a_cursor():
    """A renamed or absent cursor costs ONE extra request and never a row."""
    empty = {"history": {"columns": list(_read(_NOCURSOR)["history"]["columns"]), "data": []}}
    served = {0: _read(_NOCURSOR), 3: empty}
    seen: list[int] = []

    def fetch_page(start: int):
        seen.append(start)
        return served[start]

    rows = T.iter_pages(fetch_page, secid="SYNTH1")
    assert seen == [0, 3]
    assert len(rows) == 3


def test_a_cursor_that_does_not_advance_falls_through_instead_of_looping():
    doc = _read(_PAGE1)
    doc["history.cursor"]["data"] = [[0, 99, 0]]  # PAGESIZE 0 -> would never advance
    assert T.next_start(doc, start=0, rows_received=3) == 3


def test_the_paging_walk_is_bounded():
    def always_more(start: int):
        return _read(_PAGE1)

    with pytest.raises(RuntimeError, match="exceeded"):
        T.iter_pages(always_more, secid="SYNTH1", max_pages=4)


# ---------------------------------------------------------------------------
# The landed object + first-capture-wins key logic.
# ---------------------------------------------------------------------------
def test_the_raw_key_is_dated_by_tradedate_not_by_the_fetch_date():
    rows = T.parse_history_rows(_read(_WHFOB))
    docs = T.observations_from_rows(rows, secid="WHFOB")
    keys = [raw_moex_agro_indices_key("WHFOB", d["trade_date"]) for d in docs]
    assert keys[0] == (
        "raw/production/source=moex_agro_indices/secid=WHFOB/trade_date=2026-08-03/row.json"
    )
    assert len(set(keys)) == len(keys) == 13
    assert all(k.startswith(moex_agro_indices_secid_prefix("WHFOB")) for k in keys)
    # A second walk over the same window re-derives the SAME keys -- that is what makes
    # first-capture-wins meaningful rather than a name for "overwrite less often".
    again = [raw_moex_agro_indices_key("WHFOB", d["trade_date"])
             for d in T.observations_from_rows(rows, secid="WHFOB")]
    assert again == keys


def test_canonical_bytes_are_byte_stable_across_renderings():
    row = T.parse_history_rows(_read(_WHFOB))[0]
    a = T.canonical_observation_bytes(T.build_observation(secid="WHFOB", row=row))
    b = T.canonical_observation_bytes(T.build_observation(secid="WHFOB", row=dict(row)))
    assert a == b
    assert json.loads(a.decode("utf-8"))["close"] == 230.1


def test_build_observation_refuses_a_row_naming_another_security():
    row = T.parse_history_rows(_read(_WHCPT))[0]
    with pytest.raises(ValueError, match="under another"):
        T.build_observation(secid="WHFOB", row=row)


def test_a_null_close_is_never_landed_but_never_costs_the_window():
    rows = T.parse_history_rows(_read(_WHFOB))
    rows[4][T.COL_CLOSE] = None
    docs = T.observations_from_rows(rows, secid="WHFOB")
    assert len(docs) == 12
    assert "2026-08-07" not in {d["trade_date"] for d in docs}
    with pytest.raises(ValueError, match="null CLOSE"):
        T.build_observation(secid="WHFOB", row=rows[4])


def test_first_capture_wins_skips_an_identical_reserve_and_never_overwrites_a_divergence(monkeypatch):
    """The landed key is never written twice: identical -> skip, different -> log, keep the first."""
    rows = T.parse_history_rows(_read(_WHFOB))
    docs = T.observations_from_rows(rows, secid="WHFOB")
    landed: dict[str, bytes] = {
        raw_moex_agro_indices_key("WHFOB", docs[0]["trade_date"]):
            T.canonical_observation_bytes(docs[0]),
    }
    # The second date is already landed, but with a DIFFERENT close -- a divergence.
    diverged_doc = dict(docs[1])
    diverged_doc["close"] = 999.9
    diverged_key = raw_moex_agro_indices_key("WHFOB", docs[1]["trade_date"])
    landed[diverged_key] = T.canonical_observation_bytes(diverged_doc)

    writes: list[str] = []

    class _Client:
        calls = 0

        def get_json(self, url, params):
            return _read(_WHFOB) if not params.get("start") else {
                "history": {"columns": list(_read(_WHFOB)["history"]["columns"]), "data": []}}

    monkeypatch.setattr(FETCH, "raw_exists", lambda b, k, r: k in landed)
    monkeypatch.setattr(FETCH, "raw_read", lambda b, k, r: landed[k])
    monkeypatch.setattr(FETCH, "land_bytes",
                        lambda b, k, d, **kw: (writes.append(k), landed.__setitem__(k, d)))

    rc = FETCH.run(client=_Client(), secids=["WHFOB"], date_from="2026-08-03",
                   date_till="2026-08-19", bucket="b", region="us-east-1",
                   skip_existing=False, mode="backfill")
    assert rc == 0
    # 13 dates; the first was identical (skipped), the second diverged (kept), 11 written.
    assert len(writes) == 11
    assert diverged_key not in writes
    assert landed[diverged_key] == T.canonical_observation_bytes(diverged_doc)
    # And the divergence did NOT overwrite: the landed bytes still carry the original close.
    assert json.loads(landed[diverged_key].decode("utf-8"))["close"] == 999.9


def test_skip_existing_s3_short_circuits_before_any_comparison(monkeypatch):
    rows = T.parse_history_rows(_read(_WHFOB))
    docs = T.observations_from_rows(rows, secid="WHFOB")
    present = {raw_moex_agro_indices_key("WHFOB", d["trade_date"]) for d in docs}
    reads: list[str] = []
    writes: list[str] = []

    class _Client:
        calls = 0

        def get_json(self, url, params):
            return _read(_WHFOB) if not params.get("start") else {
                "history": {"columns": list(_read(_WHFOB)["history"]["columns"]), "data": []}}

    monkeypatch.setattr(FETCH, "raw_exists", lambda b, k, r: k in present)
    monkeypatch.setattr(FETCH, "raw_read", lambda b, k, r: reads.append(k) or b"")
    monkeypatch.setattr(FETCH, "land_bytes", lambda b, k, d, **kw: writes.append(k))

    rc = FETCH.run(client=_Client(), secids=["WHFOB"], date_from="2026-08-03",
                   date_till="2026-08-19", bucket="b", region="us-east-1",
                   skip_existing=True, mode="daily")
    assert rc == 0
    assert writes == []
    assert reads == []


# ---------------------------------------------------------------------------
# raw -> bronze.
# ---------------------------------------------------------------------------
def _bronze_for(fixture: Path, secid: str) -> pd.DataFrame:
    rows = T.parse_history_rows(_read(fixture))
    frames = []
    for doc in T.observations_from_rows(rows, secid=secid):
        blob = T.canonical_observation_bytes(doc)
        frame, _stats = T.build_bronze(blob, secid=secid, trade_date=doc["trade_date"])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def test_bronze_round_trips_the_measured_values():
    df = _bronze_for(_WHFOB, "WHFOB")
    assert list(df.columns) == T.BRONZE_COLUMNS
    assert len(df) == 13
    assert [(str(d), c) for d, c in zip(df["trade_date"], df["close"])] == WHFOB_CLOSES
    assert set(df["currency"]) == {"USD"}
    assert set(df["board"]) == {"RTSI"}


def test_bronze_refuses_a_mis_keyed_object():
    rows = T.parse_history_rows(_read(_WHFOB))
    doc = T.build_observation(secid="WHFOB", row=rows[0])
    blob = T.canonical_observation_bytes(doc)
    with pytest.raises(ValueError, match="mis-keyed|must agree"):
        T.build_bronze(blob, secid="WHFOB", trade_date="2026-08-04")
    with pytest.raises(ValueError, match="mis-keyed|must agree"):
        T.build_bronze(blob, secid="WHCPT", trade_date="2026-08-03")


def test_bronze_refuses_an_unknown_schema_tag():
    rows = T.parse_history_rows(_read(_WHFOB))
    doc = T.build_observation(secid="WHFOB", row=rows[0])
    doc["schema"] = "moex_agro_indices_history_row/v0"
    with pytest.raises(ValueError, match="schema"):
        T.build_bronze(T.canonical_observation_bytes(doc), secid="WHFOB",
                       trade_date="2026-08-03")


# ---------------------------------------------------------------------------
# bronze -> silver.
# ---------------------------------------------------------------------------
def test_silver_is_the_tidy_contract_and_keeps_both_currencies_unconverted():
    out = S.transform_moex_agro_indices_bronze_to_silver(
        [_bronze_for(_WHFOB, "WHFOB"), _bronze_for(_WHCPT, "WHCPT")]
    )
    assert list(out.columns) == S.SILVER_COLUMNS == [
        "secid", "trade_date", "close", "currency", "board", "source"]
    assert len(out) == 27
    assert set(out["source"]) == {"moex_agro_indices"}
    assert list(out["secid"]) == sorted(out["secid"])  # deterministic order

    fob = out[out["secid"] == "WHFOB"]
    cpt = out[out["secid"] == "WHCPT"]
    assert [(str(d), c) for d, c in zip(fob["trade_date"], fob["close"])] == WHFOB_CLOSES
    assert [(str(d), c) for d, c in zip(cpt["trade_date"], cpt["close"])] == WHCPT_CLOSES
    assert set(fob["currency"]) == {"USD"} and set(fob["board"]) == {"RTSI"}
    assert set(cpt["currency"]) == {"RUB"} and set(cpt["board"]) == {"AGRO"}
    # NOTHING is converted: the RUB levels are the published roubles, not a USD translation.
    assert cpt["close"].min() > 10_000


def test_silver_collapses_exact_duplicates_and_refuses_conflicting_ones():
    frame = _bronze_for(_WHFOB, "WHFOB")
    doubled = S.transform_moex_agro_indices_bronze_to_silver([frame, frame.copy()])
    assert len(doubled) == 13

    conflicting = frame.copy()
    conflicting.loc[0, "close"] = 1.0
    with pytest.raises(S.MoexConflictError, match="two different"):
        S.transform_moex_agro_indices_bronze_to_silver([frame, conflicting])


def test_silver_refuses_a_row_with_neither_currency_nor_board():
    frame = _bronze_for(_WHFOB, "WHFOB")
    frame.loc[0, "currency"] = ""
    frame.loc[0, "board"] = ""
    with pytest.raises(ValueError, match="neither a currency nor a board"):
        S.transform_moex_agro_indices_bronze_to_silver([frame])


def test_silver_refuses_a_null_trade_date():
    frame = _bronze_for(_WHFOB, "WHFOB")
    frame.loc[0, "trade_date"] = None
    with pytest.raises(ValueError, match="null trade_date"):
        S.transform_moex_agro_indices_bronze_to_silver([frame])


# ---------------------------------------------------------------------------
# The contract, and the two written laws.
# ---------------------------------------------------------------------------
def test_silver_columns_match_the_registry_contract():
    contract = yaml.safe_load(
        (_REPO / "configs" / "silver" / "tables" / "silver_moex_agro_indices.yaml")
        .read_text(encoding="utf-8")
    )
    assert [c["name"] for c in contract["physical_columns"]] == S.SILVER_COLUMNS
    assert contract["natural_key"] == S.NATURAL_KEY
    assert contract["knowledge_date_col"] == "trade_date"
    assert contract["knowledge_semantics"] == "data_date"
    assert contract["publication_lag_days"] == 0
    # The four-checkmark law: no numbers card may exist before proof-of-rows.
    assert contract["numbers_ref"] is None
    assert contract["cascade_ref"] is None
    assert contract["consumers"] == "none"


def test_no_duty_constant_is_hardcoded_anywhere_in_the_package():
    """FOLLOW-UP MOEX-DUTY-1: the derivation is DOCUMENTED, never computed.

    A base price or an FX rule living as a module constant is a guessed number with a provenance
    trail, which is worse than no number. The formula may appear in prose; it may not appear as
    code.
    """
    for module in (T, S, FETCH):
        public = [name for name in vars(module) if not name.startswith("_")]
        offenders = [
            name for name in public
            if any(token in name.upper()
                   for token in ("DUTY", "BASE_PRICE", "BASEPRICE", "RUB_PER_USD", "FX_RATE",
                                 "DAMPER"))
        ]
        assert offenders == [], f"{module.__name__} defines duty-derivation constant(s): {offenders}"
    # ...and the follow-up is NAMED where a reader will find it.
    assert "MOEX-DUTY-1" in (T.__doc__ or "")
    assert "MOEX-DUTY-1" in (S.__doc__ or "")


def test_the_aws_only_reachability_fact_is_stated_in_the_producer():
    doc = FETCH.__doc__ or ""
    assert "ONLY FROM AWS" in doc.upper()
    assert "--dry-run" in doc
    assert "http=000" in doc


def test_the_dry_run_makes_no_request_and_exits_zero(capsys):
    rc = FETCH.main(["--mode", "backfill", "--from", "2015-01-01", "--till", "2026-08-20",
                     "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "iss.moex.com" in out
    assert "trade_date={TRADEDATE}" in out
    for secid in FETCH.DEFAULT_SECIDS:
        assert secid in out
    assert "AWS ONLY" in out


def test_the_default_universe_is_the_five_measured_securities():
    assert FETCH.DEFAULT_SECIDS == ["BRFOB", "CRFOB", "WH4CPTNOV", "WHCPT", "WHFOB"]
    assert set(FETCH.DEFAULT_SECIDS) == set(T.MEASURED_SECURITIES)
    assert FETCH.DEFAULT_BACKFILL_FROM == "2015-01-01"


def test_the_producer_has_no_force_flag():
    """An overwrite flag on an immutable raw layer is a PIT violation with no undo."""
    with pytest.raises(SystemExit):
        FETCH.main(["--mode", "daily", "--force", "--dry-run"])


def test_the_sleep_floor_is_enforced():
    with pytest.raises(ValueError, match="floor"):
        FETCH.MoexClient(sleep_s=0.1)


# ---------------------------------------------------------------------------
# The existence probe FAILS CLOSED -- the one path that could destroy a capture
# ---------------------------------------------------------------------------
class TestRawExistsFailsClosed:
    """``raw_exists`` gates BOTH the --skip-existing-s3 short-circuit and the first-capture-wins
    byte comparison -- i.e. the only PUT on this leg's data plane.

    The EEX unrecoverability argument does NOT apply here: ISS serves history and a lost row is
    re-fetchable. The argument that does apply is this family's OWN law. It ships with no --force
    because "an overwrite flag on an immutable raw layer is a PIT violation with no undo" -- and the
    house idiom (``except Exception: return False``) grants exactly that overwrite silently, at
    random, on any throttle. Worse, it fires when the landed and re-served bytes DIFFER, converting
    a divergence finding into a quiet overwrite of the evidence.

    NOT LIVE-TESTABLE: iss.moex.com answers from AWS only, so this is the fetch_eex_freight shape
    verbatim under unit tests.
    """

    @staticmethod
    def _s3(monkeypatch, exc):
        class _S3:
            def head_object(self, **_kw):
                if exc is not None:
                    raise exc
                return {"ContentLength": 1}

        import leviathan.storage.s3 as S3MOD
        monkeypatch.setattr(S3MOD, "get_thread_local_s3_client", lambda region: _S3())

    @staticmethod
    def _client_error(code, status):
        from botocore.exceptions import ClientError
        return ClientError(
            {"Error": {"Code": code, "Message": "x"},
             "ResponseMetadata": {"HTTPStatusCode": status}},
            "HeadObject",
        )

    class _Client:
        """One WHFOB window, then an empty page -- the shape the other run tests use."""

        calls = 0

        def get_json(self, url, params):
            if params.get("start"):
                return {"history": {"columns": list(_read(_WHFOB)["history"]["columns"]),
                                    "data": []}}
            return _read(_WHFOB)

    def test_a_landed_object_is_reported_present(self, monkeypatch):
        self._s3(monkeypatch, None)
        assert FETCH.raw_exists("b", "k", "us-east-1") is True

    @pytest.mark.parametrize("code,status", [("404", 404), ("NotFound", 404), ("NoSuchKey", 404)])
    def test_only_a_genuine_404_means_absent(self, monkeypatch, code, status):
        """HeadObject has no body, so botocore spells the missing-key case '404'/'NotFound' rather
        than the 'NoSuchKey' a GetObject would raise. All three are the same fact."""
        self._s3(monkeypatch, self._client_error(code, status))
        assert FETCH.raw_exists("b", "k", "us-east-1") is False

    @pytest.mark.parametrize("code,status", [
        ("SlowDown", 503),
        ("InternalError", 500),
        ("ExpiredToken", 400),
        ("AccessDenied", 403),
        ("RequestTimeout", 400),
    ])
    def test_every_other_head_failure_RAISES_rather_than_fabricating_absence(
            self, monkeypatch, code, status):
        from botocore.exceptions import ClientError
        self._s3(monkeypatch, self._client_error(code, status))
        with pytest.raises(ClientError):
            FETCH.raw_exists("b", "k", "us-east-1")

    def test_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """End to end through ``run()``: every head throttles, so every date fails CLOSED, nothing
        is written, and the run exits 1. Both raw_exists call sites sit inside the per-date guard,
        which is what turns the raise into a recorded failure rather than an aborted secid."""
        written: list[str] = []
        self._s3(monkeypatch, self._client_error("SlowDown", 503))
        monkeypatch.setattr(FETCH, "land_bytes", lambda b, k, d, **kw: written.append(k))
        monkeypatch.setattr(FETCH, "raw_read", lambda b, k, r: b"")

        rc = FETCH.run(client=self._Client(), secids=["WHFOB"], date_from="2026-08-03",
                       date_till="2026-08-19", bucket="b", region="us-east-1",
                       skip_existing=False, mode="backfill")
        assert rc == 1
        assert written == [], "a throttled head must never be read as 'absent' and PUT over"

    def test_a_throttled_skip_existing_probe_fails_the_date_instead_of_re_landing_it(
            self, monkeypatch):
        """--skip-existing-s3 calls raw_exists first. An unanswerable probe there must not fall
        through to the comparison-and-write path either."""
        written: list[str] = []
        self._s3(monkeypatch, self._client_error("ExpiredToken", 400))
        monkeypatch.setattr(FETCH, "land_bytes", lambda b, k, d, **kw: written.append(k))
        monkeypatch.setattr(FETCH, "raw_read", lambda b, k, r: b"")

        rc = FETCH.run(client=self._Client(), secids=["WHFOB"], date_from="2026-08-03",
                       date_till="2026-08-19", bucket="b", region="us-east-1",
                       skip_existing=True, mode="daily")
        assert rc == 1 and written == []

    def test_the_same_drive_lands_every_date_when_the_head_answers_404(self, monkeypatch):
        """The positive control, so the tests above cannot pass vacuously."""
        written: list[str] = []
        self._s3(monkeypatch, self._client_error("404", 404))
        monkeypatch.setattr(FETCH, "land_bytes", lambda b, k, d, **kw: written.append(k))

        rc = FETCH.run(client=self._Client(), secids=["WHFOB"], date_from="2026-08-03",
                       date_till="2026-08-19", bucket="b", region="us-east-1",
                       skip_existing=False, mode="backfill")
        assert rc == 0
        assert written == [raw_moex_agro_indices_key("WHFOB", d) for d, _c in WHFOB_CLOSES]

    def test_main_exits_nonzero_on_a_throttled_head_and_writes_nothing(self, monkeypatch):
        """Through ``main()`` too, so the exit code a schedule would read is the asserted one."""
        written: list[str] = []
        outer = self

        class _StubClient:
            calls = 0

            def __init__(self, sleep_s=1.1):
                self._inner = outer._Client()

            def get_json(self, url, params):
                return self._inner.get_json(url, params)

        self._s3(monkeypatch, self._client_error("SlowDown", 503))
        monkeypatch.setattr(FETCH, "MoexClient", _StubClient)
        monkeypatch.setattr(FETCH, "land_bytes", lambda b, k, d, **kw: written.append(k))
        monkeypatch.setattr(FETCH, "raw_read", lambda b, k, r: b"")

        rc = FETCH.main(["--mode", "daily", "--secids", "WHFOB", "--from", "2026-08-03",
                         "--till", "2026-08-19", "--bucket", "b", "--aws-region", "us-east-1"])
        assert rc == 1 and written == []
