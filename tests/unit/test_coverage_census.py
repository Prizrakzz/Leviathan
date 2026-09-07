"""Phase G sitting 1 -- the PURE cores of leviathan.graphrag.corpus_coverage.

WHAT EACH GROUP PINS AND WHY (every "why" is a measured trigger, not a preference):

* ALIAS-AWARENESS. The md5(source_key) join alone read `usda_gain_soybeans` at 58/127 = 45.7% and
  sent a brief to re-chunk 69 documents the store had already folded -- byte-identical co-filings of
  one GAIN Oilseeds-and-Products Annual, all 69 present in `_index/doc_aliases.jsonl` with
  `layer: store_path`. Forcing that run would have re-paid Haiku for 69 identical documents and
  minted a SECOND set of props under a second source_key. These tests pin that a store_path alias
  COUNTS AS COVERED and that a truly-unchunked document does not.
* G2. A key no rule recognises floors to Jan-1 today (evidence.py:318-324) -- leakage-permissive in
  exactly the field the as-of filter compares (evidence.py:639). And a NAMED refusal STILL FLOORS,
  which is why the gate refuses those too and why conab/mpob leave the write path.
* G1. No `datetime.now()` fallback anywhere in this lane: `bound_listing` takes `today` as a
  REQUIRED keyword, which these tests pin by calling it without one.
* CAPS. The tight estimator is evidence_batch.py:1907's own expression; the 3.5x fill band
  (:1886-1887) is printed beside it and must never be mistaken for the fence.
* METRIC CARDINALITY. 28 sources x 3 per-source metrics + 1 family = 85 custom metrics x $0.30 =
  $25.50/month against a lane total of $14.7. The four family-rolled metrics are $1.20/month. The
  cardinality pin is what stops that shape coming back.

NOT COVERED HERE, deliberately: anything that touches S3, Batch, CloudWatch or the network. The S3
readers in corpus_coverage are three LISTs and one GET and are exercised by the live dry runs, not by
this deck.
"""
from __future__ import annotations

from datetime import date

import pytest
from leviathan.graphrag import corpus_coverage as cc

# ---------------------------------------------------------------------------
# identity: the census must mint the SAME names the chunker does
# ---------------------------------------------------------------------------

_SOY = "text/source=usda_gain_soybeans/country=BR/publication_date=20260318/document.json"
_MEAL = "text/source=usda_gain_soybean_meal/country=BR/publication_date=20260318/document.json"


def test_path_fingerprint_matches_evidence_batch() -> None:
    """If the chunker's cross-source identity rule ever moves, the census must move with it or it
    starts scoring aliases as gaps again -- the exact defect this module exists for."""
    from leviathan.graphrag import evidence_batch as eb
    for k in (_SOY, _MEAL, "text/source=conab/crop_year=2024_25/survey=03/document.json"):
        assert cc.path_fingerprint(k) == eb._path_fingerprint(k)


def test_path_fingerprint_folds_the_source_segment_only() -> None:
    assert cc.path_fingerprint(_SOY) == cc.path_fingerprint(_MEAL)
    assert "source=" not in cc.path_fingerprint(_SOY)


def test_doc_cache_name_matches_evidence_batch() -> None:
    from leviathan.graphrag import evidence_batch as eb
    assert cc.doc_cache_name(_SOY) == eb._doc_cache_node(_SOY).split("/")[-1]


def test_source_of_reads_text_and_raw_keys() -> None:
    assert cc.source_of(_SOY) == "usda_gain_soybeans"
    assert cc.source_of("raw/production/source=sagis_cec/release_date=2026-08-26/CEC.pdf") == "sagis_cec"
    assert cc.source_of("nothing/here.json") == "unknown"


# ---------------------------------------------------------------------------
# the census -- alias awareness
# ---------------------------------------------------------------------------

_TODAY = date(2026, 9, 7)


def _census(text_keys, chunked_keys, alias_rows=(), raw_keys=()):
    return cc.build_census(list(text_keys), [cc.doc_cache_name(k) for k in chunked_keys],
                           list(alias_rows), list(raw_keys), today=_TODAY)


def test_a_store_path_alias_counts_as_covered() -> None:
    """THE PIN THE WHOLE MODULE EXISTS FOR. The soybeans co-filing is NOT in chunks/ -- its
    soybean_meal path twin is -- and the census must read the soybeans source at 100%, not 0%."""
    c = _census([_SOY, _MEAL], [_MEAL])
    soy = c["sources"]["usda_gain_soybeans"]
    assert soy["chunked"] == 0
    assert soy["aliased"] == 1
    assert soy["gap"] == 0
    assert soy["coverage_naive"] == 0.0
    assert soy["coverage"] == 1.0
    assert soy["newest_covered_pub"] == "2026-03-18"


def test_a_persisted_alias_row_counts_as_covered_even_without_a_path_twin() -> None:
    """The alias index is the store's own record of what it folded. A row whose canonical IS chunked
    covers its duplicate even when the two keys share no path fingerprint (the CONTENT layer's
    output, which this census cannot recompute without a GET per document)."""
    dup = "text/source=usda_gain_coffee/country=BR/publication_date=20260101/document.json"
    canon = "text/source=fnc/publication_date=2026-01-02/document.json"
    c = _census([dup, canon], [canon],
                alias_rows=[{"source_key": dup, "canonical_key": canon, "layer": "content"}])
    assert c["sources"]["usda_gain_coffee"]["aliased"] == 1
    assert c["sources"]["usda_gain_coffee"]["gap"] == 0
    assert c["sources"]["usda_gain_coffee"]["coverage"] == 1.0


def test_a_truly_unchunked_document_is_a_gap_not_an_alias() -> None:
    lone = "text/source=usda_gain_cotton/country=IN/publication_date=20220119/document.json"
    c = _census([lone, _MEAL], [_MEAL])
    cot = c["sources"]["usda_gain_cotton"]
    assert (cot["chunked"], cot["aliased"], cot["gap"]) == (0, 0, 1)
    assert cot["coverage"] == 0.0
    assert cot["newest_covered_pub"] is None


def test_an_alias_row_into_an_UNCHUNKED_canonical_is_scored_as_a_gap() -> None:
    """DedupGate's own LIVENESS law: an alias is a PROMISE that the canonical has props, and an
    unbacked canonical is COUNTED rather than promised (evidence_batch.py:685-700). The census takes
    the conservative direction -- it over-counts work to do, it never under-counts it."""
    dup = "text/source=usda_gain_rice/country=TH/publication_date=20260401/document.json"
    canon = "text/source=usda_gain_grain_monthly/country=TH/publication_date=20260401/document.json"
    c = _census([dup], [], alias_rows=[{"source_key": dup, "canonical_key": canon,
                                        "layer": "content"}])
    assert c["sources"]["usda_gain_rice"]["gap"] == 1
    assert c["sources"]["usda_gain_rice"]["aliased"] == 0


def test_naive_and_alias_aware_totals_disagree_in_the_measured_direction() -> None:
    """Corpus-wide the design measured naive 84.0% against alias-aware 87.8%. The shape, not the
    figure: alias-aware is ALWAYS >= naive, and the difference is exactly the aliased count."""
    c = _census([_SOY, _MEAL, "text/source=mpoc/date=20260123/document.json"], [_MEAL])
    t = c["totals"]
    assert t["docs"] == 3 and t["chunked"] == 1 and t["aliased"] == 1 and t["gap"] == 1
    assert t["coverage"] > t["coverage_naive"]
    # the ledger's ratios are rounded to 4dp (that is what an operator reads), so compare at 1e-3
    assert t["coverage"] - t["coverage_naive"] == pytest.approx(t["aliased"] / t["docs"], abs=1e-3)


def test_newest_raw_pub_and_fetch_lag_come_from_the_raw_listing() -> None:
    """The 110-day GAIN stall is the recency ceiling; a census that only scored chunk coverage would
    have read GREEN through all of it."""
    c = _census([_MEAL], [_MEAL],
                raw_keys=["raw/production/source=usda_gain_soybean_meal/country=BR/"
                          "publication_date=20260521/report.pdf"])
    meal = c["sources"]["usda_gain_soybean_meal"]
    assert meal["newest_raw_pub"] == "2026-05-21"
    assert meal["fetch_lag_days"] == (_TODAY - date(2026, 5, 21)).days == 109
    assert meal["raw_date_derivable"] is True


def test_an_undateable_raw_key_reads_as_UNAVAILABLE_not_as_fresh() -> None:
    """MEASURED 2026-09-07: `pub_date_layout`'s seven rules were written for TEXT keys, and four
    sources' RAW keys carry no segment any of them can read -- sagis_cec's bare
    `CEC_2026-08-26.pdf`, mpoc's `release_type=.../slug=...`, fnc's `bulk/Exportaciones-2026-2.xlsx`
    and icco_ewg_stocks' `season=2020-21/`. The design assumed `newest_raw_pub` was always
    derivable. A None here must be reported as UNAVAILABLE, never read as fresh."""
    c = _census(["text/source=sagis_cec/release_date=2026-06-25/document.json"], [],
                raw_keys=["raw/production/source=sagis_cec/CEC_2026-08-26.pdf",
                          "raw/production/source=sagis_cec/CEC_2026-07-28.pdf"])
    sc = c["sources"]["sagis_cec"]
    assert sc["n_raw_objects"] == 2
    assert sc["newest_raw_pub"] is None and sc["fetch_lag_days"] is None
    assert sc["raw_date_derivable"] is False
    assert c["totals"]["sources_without_a_derivable_raw_date"] == ["sagis_cec"]


# ---------------------------------------------------------------------------
# lags, breaches, metrics
# ---------------------------------------------------------------------------

def test_struck_sources_are_excluded_from_the_lags_and_the_breach_count() -> None:
    """conab and mpob carry NAMED refusals, so they can never derive a publication date. Including
    them would make the lag permanently None; excluding them is what makes it finite."""
    conab = "text/source=conab/crop_year=2024_25/survey=03/document.json"
    c = _census([conab, _MEAL], [_MEAL])
    assert c["sources"]["conab"]["struck_from_write_path"] is True
    assert c["sources"]["conab"]["struck_prerequisite"]
    assert "conab" not in cc.scored_sources(c)
    assert "conab" not in cc.breaching_sources(c)
    assert cc.chunk_lag_days_max(c) == (_TODAY - date(2026, 3, 18)).days


def test_breach_predicate_fires_on_coverage_and_on_lag() -> None:
    stale = "text/source=usda_gain_cotton/country=IN/publication_date=20220119/document.json"
    c = _census([stale, _MEAL], [stale, _MEAL])
    # cotton is 100% covered but 4+ years stale -> breaches on LAG alone
    assert "usda_gain_cotton" in cc.breaching_sources(c, coverage_floor=0.0,
                                                     chunk_lag_ceiling=7.0)
    # ... and with a generous lag ceiling it stops breaching
    assert cc.breaching_sources(c, coverage_floor=0.0, chunk_lag_ceiling=99999.0) == []
    # a gap breaches on COVERAGE even with an infinite lag ceiling
    c2 = _census([stale, _MEAL], [_MEAL])
    assert "usda_gain_cotton" in cc.breaching_sources(c2, chunk_lag_ceiling=99999.0)


def test_served_lag_reads_after_span_date_max_from_a_run_manifest() -> None:
    mf = {"slices": {"commodity": {"soybeans": {"after_span": {"date_max": "2026-08-12"}},
                                   "corn": {"after_span": {"date_max": "2026-07-01"}}},
                     "drivers": {"tariff": {"after_span": {"date_max": "2026-08-12"}}}}}
    assert cc.served_lag_days(mf, today=_TODAY) == (_TODAY - date(2026, 8, 12)).days == 26


def test_served_lag_is_None_not_zero_when_no_manifest_carries_a_span() -> None:
    """A missing span is a FINDING, never a fresh reading."""
    assert cc.served_lag_days(None, today=_TODAY) is None
    assert cc.served_lag_days({"slices": {}}, today=_TODAY) is None
    assert cc.served_lag_days({"slices": {"commodity": {"x": {"after_span": {}}}}},
                              today=_TODAY) is None


def test_exactly_four_family_rolled_metrics_and_no_per_source_dimension() -> None:
    """THE CARDINALITY PIN. 28 sources x 3 + 1 = 85 metrics x $0.30 = $25.50/month, more than the
    whole lane. Four family-rolled metrics + four alarms = $1.60/month, with the per-source detail
    on S3 for free. CloudWatch is the pager; S3 is the record."""
    c = _census([_SOY, _MEAL], [_MEAL],
                raw_keys=["raw/production/source=usda_gain_soybean_meal/country=BR/"
                          "publication_date=20260521/r.pdf"])
    data = cc.metric_payloads(c)
    assert [d["MetricName"] for d in data] == list(cc.FAMILY_METRIC_NAMES)
    assert len(data) == 4
    for d in data:
        assert d["Dimensions"] == [{"Name": "Family", "Value": "graphrag_evidence"}]
        assert len(d["Dimensions"]) == 1
    # the dimension VALUE is constant, so this is 4 metric streams forever, never 4 x n_sources
    assert len({tuple(sorted(dd.items())) for d in data for dd in d["Dimensions"]}) == 1


def test_a_metric_with_no_measurable_value_emits_no_datapoint() -> None:
    """freshness.py's own empty-prefix convention: no datapoint, and the alarm's
    treat_missing_data owns the silence -- never a fabricated 0."""
    c = _census(["text/source=conab/crop_year=2024_25/survey=03/document.json"], [])
    names = [d["MetricName"] for d in cc.metric_payloads(c)]
    assert cc.METRIC_CHUNK_LAG_MAX not in names          # nothing scoreable
    assert cc.METRIC_BREACH_COUNT in names               # ... but the count is always emittable


def test_ledger_document_carries_the_served_lag_and_the_struck_prerequisites() -> None:
    c = _census([_SOY, _MEAL], [_MEAL])
    led = cc.ledger_document(c, generated_at="2026-09-07T00:00:00Z", served_lag=26,
                             outstanding_batch_id="msgbatch_x", fulltext_cap=150000)
    assert led["served_lag_days"] == 26                  # ledger-only: NOT a fifth metric
    assert led["outstanding_batch_id"] == "msgbatch_x"
    assert led["fulltext_cap"] == 150000
    assert set(led["struck_from_write_path"]) == {"conab", "mpob"}
    assert led["sources"]["usda_gain_soybeans"]["coverage"] == 1.0


# ---------------------------------------------------------------------------
# G2 -- the key-layout gate
# ---------------------------------------------------------------------------

# ONE fixture key per rule in evidence._KEY_DATE_RULES, in declaration order.
_SEVEN_LAYOUTS = {
    "publication_date": "text/source=usda_gain_wheat/country=AR/publication_date=20260514/document.json",
    "publication_date_iso": "text/source=fnc/publication_date=2026-03-01/document.json",
    "release_date": "text/source=usda_wasde/release_date=2026-08-12/document.json",
    "article_date": "text/source=mpoc/date=20260123/document.json",
    "release_month": "text/source=usda_wap/release_month=2026-07/document.json",
    "release_ym": "text/source=wb_cmo_outlook/release=2026-04/document.json",
    "document_mmddyyyy": ("text/source=usda_gain_sugar/country=MX/"
                          "document=sugar_annual_mexico_05-15-2021/document.json"),
}


@pytest.mark.parametrize("layout,key", sorted(_SEVEN_LAYOUTS.items()))
def test_g2_passes_each_of_the_seven_layouts(layout: str, key: str) -> None:
    ok, reason, got = cc.key_layout_verdict(key)
    assert ok is True
    assert reason == cc.REASON_OK
    assert got == layout
    cc.assert_key_layout(key)                            # does not raise


def test_g2_refuses_an_unknown_layout() -> None:
    """`pub_date_layout`'s own docstring: an unknown layout should be read as *add a rule*, not as
    *this document has no date*. Nothing enforced that before this gate."""
    key = "text/source=ers_newsroom/some_new_shape/document.json"
    ok, reason, layout = cc.key_layout_verdict(key)
    assert (ok, reason, layout) == (False, cc.REASON_UNKNOWN_LAYOUT, "unknown")
    with pytest.raises(cc.KeyLayoutRefused) as exc:
        cc.assert_key_layout(key)
    assert exc.value.layout == "unknown"


@pytest.mark.parametrize("source,key,layout", [
    ("conab", "text/source=conab/crop_year=2024_25/survey=03/document.json",
     "conab_survey_is_not_a_month"),
    ("mpob", "text/source=mpob/release_type=overview_pdf/year=2016/document.json", "year_only"),
])
def test_g2_refuses_the_named_refusals_so_conab_and_mpob_leave_the_write_path(
        source: str, key: str, layout: str) -> None:
    """THE CLAUSE THE DRAFT WAS MISSING. A named refusal STILL FLOORS (evidence.py:318-324), so
    refusing only `unknown` would have let these two keep minting `year_floor` documents while the
    lane claimed 'zero new documents on year_floor'."""
    ok, reason, got = cc.key_layout_verdict(key)
    assert (ok, reason, got) == (False, cc.REASON_NAMED_REFUSAL, layout)
    assert cc.STRUCK_SOURCES[source][0] == layout
    with pytest.raises(cc.KeyLayoutRefused):
        cc.assert_key_layout(key)


def test_g2_counts_every_refusal_and_never_refuses_silently() -> None:
    cc.reset_refusals()
    cc.assert_key_layout(_SEVEN_LAYOUTS["release_date"])
    for bad in ("text/source=zzz/nothing/document.json",
                "text/source=conab/crop_year=2024_25/survey=03/document.json"):
        with pytest.raises(cc.KeyLayoutRefused):
            cc.assert_key_layout(bad)
    counts = cc.refusal_counts()
    assert counts["accepted"] == 1
    assert counts["refused"] == 2
    assert counts["refused:" + cc.REASON_UNKNOWN_LAYOUT] == 1
    assert counts["refused_layout:conab_survey_is_not_a_month"] == 1
    cc.reset_refusals()
    assert cc.refusal_counts() == {}


def test_g2_keys_on_the_layout_so_a_new_rule_re_admits_a_struck_source() -> None:
    """Deliberate: the gate does NOT hold a hard-coded source blocklist. The day a conab
    survey-calendar rule lands, a conab key parses and passes with no change here."""
    src = "text/source=conab/release_date=2026-03-11/document.json"      # a hypothetical future key
    ok, _reason, layout = cc.key_layout_verdict(src)
    assert ok is True and layout == "release_date"


def test_the_gate_flag_is_dark_by_default() -> None:
    assert cc.gates_enabled({}) is False
    assert cc.gates_enabled({cc.GATE_FLAG: ""}) is False
    assert cc.gates_enabled({cc.GATE_FLAG: "off"}) is False
    assert cc.gates_enabled({cc.GATE_FLAG: "on"}) is True
    assert cc.gates_enabled({cc.GATE_FLAG: "1"}) is True


# ---------------------------------------------------------------------------
# G1 -- ledger-bounded fetch
# ---------------------------------------------------------------------------

def test_g1_refuses_a_listing_entry_with_no_publication_date() -> None:
    """THE FENCE against the class the D-EC P0c census measured at 2,036 of 7,056 documents (28.9%)
    taking a Jan-1 floor. If the source did not state a date, the object is not written."""
    out = cc.bound_listing([{"id": "r1", "pub_date": None}], newest_raw_pub=None, today=_TODAY)
    assert out["counts"] == {"accepted": 0, "refused": 1, "skipped": 0, "bound": None}
    assert out["refused"][0]["reason"] == cc.REASON_NO_PUB_DATE


def test_g1_refuses_a_non_date_masquerading_as_one() -> None:
    out = cc.bound_listing([{"id": "r1", "pub_date": "2026-09-01"}], newest_raw_pub=None,
                           today=_TODAY)
    assert out["refused"][0]["reason"] == cc.REASON_NO_PUB_DATE


def test_g1_refuses_a_future_dated_entry() -> None:
    """A date after the run date is the wrong-early class the lane exists to make impossible."""
    out = cc.bound_listing([{"id": "r1", "pub_date": date(2026, 9, 8)}],
                           newest_raw_pub=None, today=_TODAY)
    assert out["refused"][0]["reason"] == cc.REASON_FUTURE_DATED


def test_g1_asks_only_for_releases_newer_than_the_ledger() -> None:
    entries = [{"id": "old", "pub_date": date(2026, 5, 20)},
               {"id": "same", "pub_date": date(2026, 5, 21)},
               {"id": "new", "pub_date": date(2026, 6, 1)}]
    out = cc.bound_listing(entries, newest_raw_pub=date(2026, 5, 21), today=_TODAY)
    assert [a["id"] for a in out["accepted"]] == ["new"]
    assert {s["id"] for s in out["skipped"]} == {"old", "same"}
    assert out["counts"]["bound"] == "2026-05-21"


def test_g1_first_fire_with_no_ledger_entry_accepts_every_dated_release() -> None:
    entries = [{"id": "a", "pub_date": date(2020, 1, 2)}, {"id": "b", "pub_date": None}]
    out = cc.bound_listing(entries, newest_raw_pub=None, today=_TODAY)
    assert [a["id"] for a in out["accepted"]] == ["a"]
    assert out["counts"]["refused"] == 1


def test_g1_buckets_are_exhaustive_nothing_is_silently_dropped() -> None:
    entries = [{"id": "a", "pub_date": date(2026, 6, 1)}, {"id": "b", "pub_date": None},
               {"id": "c", "pub_date": date(2020, 1, 1)}, {"id": "d", "pub_date": date(2030, 1, 1)}]
    out = cc.bound_listing(entries, newest_raw_pub=date(2025, 1, 1), today=_TODAY)
    assert sum(out["counts"][k] for k in ("accepted", "refused", "skipped")) == len(entries)


def test_g1_cannot_read_a_clock_even_by_accident() -> None:
    """`today` is a REQUIRED keyword with no default. That is the structural half of
    'no datetime.now() fallback anywhere in this lane'."""
    with pytest.raises(TypeError):
        cc.bound_listing([], newest_raw_pub=None)        # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# caps
# ---------------------------------------------------------------------------

def test_the_tight_estimator_is_evidence_batchs_own_expression() -> None:
    assert cc.TIGHT_USD_PER_REQUEST == pytest.approx(1500 * 0.5 / 1e6 + 1537 * 2.5 / 1e6)
    assert round(cc.TIGHT_USD_PER_REQUEST, 7) == 0.0045925


def test_caps_pass_a_steady_state_weekly_fire() -> None:
    """The estate's measured publication rate is ~5.5 documents/week -> ~77 windows/month."""
    assert cc.check_caps(n_docs=6, n_blocks=20) == []


def test_caps_refuse_over_the_document_cap_and_name_the_number() -> None:
    lines = cc.check_caps(n_docs=686, n_blocks=10, max_docs=200)
    assert len(lines) == 1
    assert "686" in lines[0] and "200" in lines[0] and "BACKFILL" in lines[0]


def test_caps_refuse_over_the_usd_cap_and_print_the_band_beside_the_tight_number() -> None:
    """The FILL dry-run prints a 3.5x band (evidence_batch.py:1886-1887); the tight estimator is a
    different constant for a different path. Printing both is what stops them being confused."""
    lines = cc.check_caps(n_docs=10, n_blocks=2213, max_docs=10000, max_usd=5.0)
    assert len(lines) == 1
    assert "10.16" in lines[0]                           # 2,213 x $0.0045925
    assert "evidence_batch.py:1907" in lines[0]
    assert "evidence_batch.py:1886-1887" in lines[0]


def test_price_blocks_reproduces_the_designs_backlog_figures() -> None:
    """S 10.1, re-measured: 2,213 windows -> $10.16 Haiku; the fill band for the same run reads
    ~$4-15."""
    p = cc.price_blocks(2213)
    assert p["tight_usd"] == pytest.approx(10.16, abs=0.01)
    assert (round(p["band_lo_usd"]), round(p["band_hi_usd"])) == (4, 15)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def test_render_table_is_ascii_only() -> None:
    """Windows console is cp1252; a non-ASCII byte in a Batch log is a UnicodeEncodeError."""
    c = _census([_SOY, _MEAL, "text/source=conab/crop_year=2024_25/survey=03/document.json"],
                [_MEAL])
    txt = cc.render_table(c)
    txt.encode("ascii")
    assert "[STRUCK]" in txt
    assert "TOTAL" in txt


# ---------------------------------------------------------------------------
# bind_evidence_prefix -- the ONE channel evidence_batch reads
# ---------------------------------------------------------------------------
# THE MEASURED DEFECT. `evidence_batch` exposes no `--evidence-s3` flag anywhere: `_cached_hashes`
# (evidence_batch.py:257-268), `store_path_index`, `DedupGate`, `_build_requests_from_docs`,
# `submit_docs`, `retrieve`, `_save_manifest` (:837-845) and `evidence._evid_write`
# (evidence.py:60-64) all resolve `evidence._evid_s3()` = `os.environ["EVIDENCE_S3"]`
# (evidence.py:42-43). A wrapper that took the prefix as a CLI argument and never touched the
# environment therefore ran two stores in one process. These pins are pure: `env` is injected, so no
# test here mutates the session's os.environ.

_LIVE_PREFIX = "s3://leviathan-dev-shahem-001/graphrag_evidence"
_SHADOW_PREFIX = "s3://leviathan-dev-shahem-001/graphrag_evidence/shadow_originpolicy"


def test_the_flag_is_written_into_the_environment_not_merely_returned() -> None:
    env = {}
    assert cc.bind_evidence_prefix(_SHADOW_PREFIX, env=env) == _SHADOW_PREFIX
    assert env[cc.EVIDENCE_ENV_VAR] == _SHADOW_PREFIX


def test_the_flag_beats_a_disagreeing_ambient_value_and_the_override_is_announced() -> None:
    """The jobdef bakes the LIVE prefix (submit_batch_evidence_maintenance.py:228), so every shadow
    rehearsal disagrees with the ambient value. The flag wins -- refusing here would refuse R2, the
    only safe way to exercise the fold -- and the rebind is printed, never silent."""
    env = {cc.EVIDENCE_ENV_VAR: _LIVE_PREFIX}
    said = []
    assert cc.bind_evidence_prefix(_SHADOW_PREFIX, env=env, echo=said.append) == _SHADOW_PREFIX
    assert env[cc.EVIDENCE_ENV_VAR] == _SHADOW_PREFIX
    assert any("REBOUND" in line and _LIVE_PREFIX in line for line in said)


def test_an_absent_flag_inherits_the_ambient_value_unchanged_and_says_nothing() -> None:
    env = {cc.EVIDENCE_ENV_VAR: _LIVE_PREFIX}
    said = []
    assert cc.bind_evidence_prefix(None, env=env, echo=said.append) == _LIVE_PREFIX
    assert said == []


def test_a_trailing_slash_is_not_a_different_prefix() -> None:
    """`_normalize_prefix` in the submitter drops it for the same reason: a prefix that differs only
    by a slash is the SAME store, and a rebind announcement there would be noise."""
    env = {cc.EVIDENCE_ENV_VAR: _LIVE_PREFIX + "/"}
    said = []
    assert cc.bind_evidence_prefix(_LIVE_PREFIX, env=env, echo=said.append) == _LIVE_PREFIX
    assert said == []


def test_require_refuses_a_prefix_that_is_neither_declared_nor_inherited() -> None:
    """MEASURED: with EVIDENCE_S3 unset `_cached_hashes()` returns an EMPTY set, so the idempotency
    skip, the store_path layer and the alias index are all dead -- `usda_gain_soybeans --all-gap`
    read 127 candidates / 1,352 blocks / $6.21 instead of 69 candidates / 0 blocks. The billed leg
    and the fold do not fall through to a hardcoded default."""
    with pytest.raises(SystemExit) as exc:
        cc.bind_evidence_prefix(None, env={}, require=True)
    msg = str(exc.value)
    assert "_cached_hashes" in msg and "1,352 blocks" in msg and "127 candidates" in msg


def test_a_read_only_caller_may_fall_back_but_the_fallback_is_still_bound_and_named() -> None:
    env = {}
    said = []
    got = cc.bind_evidence_prefix(None, env=env, require=False, echo=said.append)
    assert got == env[cc.EVIDENCE_ENV_VAR]
    assert got.startswith("s3://") and got == got.rstrip("/")
    assert any("neither declared nor inherited" in line for line in said)


def test_an_empty_string_is_not_a_prefix() -> None:
    """An env var set to "" (a common Batch override artefact) must read as UNSET, not as a store
    whose bucket is the empty string."""
    with pytest.raises(SystemExit):
        cc.bind_evidence_prefix("", env={cc.EVIDENCE_ENV_VAR: "  "}, require=True)


# ---------------------------------------------------------------------------
# G2's tally: "refuses loudly AND COUNTS" has to hold in a PRODUCER process
# ---------------------------------------------------------------------------

def test_a_refusal_registers_the_exit_time_tally_so_the_count_leaves_the_process() -> None:
    """MEASURED GAP: `refusal_counts()` had exactly one reader in the tree -- this deck. No producer
    and neither wrapper printed it, and each text producer is its own Fargate process, so an armed
    gate's Counter died with the task. The summary is registered lazily on the FIRST count, so a
    flag-off producer (which never imports this module at all) pays nothing."""
    import atexit
    cc.reset_refusals()
    cc._summary_registered = False
    registered = []
    orig = atexit.register
    atexit.register = lambda fn, *a, **k: registered.append(fn) or fn
    try:
        with pytest.raises(cc.KeyLayoutRefused):
            cc.assert_key_layout("text/source=zzz_unknown_layout/whatever/document.json")
    finally:
        atexit.register = orig
    assert len(registered) == 1
    assert cc.refusal_counts()["refused"] == 1
    cc.reset_refusals()


def test_the_exit_summary_is_registered_once_no_matter_how_many_refusals() -> None:
    import atexit
    cc.reset_refusals()
    cc._summary_registered = False
    registered = []
    orig = atexit.register
    atexit.register = lambda fn, *a, **k: registered.append(fn) or fn
    try:
        for i in range(5):
            with pytest.raises(cc.KeyLayoutRefused):
                cc.assert_key_layout("text/source=zzz_%d/x/document.json" % i)
    finally:
        atexit.register = orig
    assert len(registered) == 1
    assert cc.refusal_counts()["refused"] == 5
    cc.reset_refusals()


def test_the_exit_summary_is_ascii_and_can_never_raise(capsys) -> None:
    """An atexit handler that throws turns a clean task into a nonzero exit at teardown, and a
    non-ASCII byte in a Batch log line is a UnicodeEncodeError on the cp1252 console."""
    import atexit
    cc.reset_refusals()
    cc._summary_registered = False
    captured = []
    orig = atexit.register
    atexit.register = lambda fn, *a, **k: captured.append(fn) or fn
    try:
        with pytest.raises(cc.KeyLayoutRefused):
            cc.assert_key_layout("text/source=zzz_unknown/x/document.json")
    finally:
        atexit.register = orig
    captured[0]()
    out = capsys.readouterr().out
    out.encode("ascii")
    assert "G2 KEY-LAYOUT GATE tally" in out and "refused=1" in out
    cc.reset_refusals()
    captured[0]()                                    # empty tally: prints nothing, raises nothing
    assert capsys.readouterr().out == ""
