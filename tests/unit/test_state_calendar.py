"""THE FORWARD RELEASE CALENDAR -- STATE ENGINE DESIGN sec 5.2 (D7) and the half of bar B11 that is
about ``next_release``: a windowed rule returns a WINDOW, never a point. Sitting S3.

NO CLOCK ANYWHERE. Every assertion below is a function of an as-of this file states, which is the whole
point of the producer: a fixture and a serving turn compute the same window, and a historical as-of
cannot leak a date the record did not hold.
"""
import datetime as _dt

import pytest
from leviathan.graphrag.state import calendar as C

ASOF = "2026-09-07"          # a Monday, and every weekday assertion below depends on that being true


def test_the_as_of_this_deck_uses_is_the_weekday_it_claims():
    """The one fact every weekday assertion here rests on, asserted rather than assumed."""
    assert _dt.date.fromisoformat(ASOF).weekday() == 0


# ── the five rule kinds ──────────────────────────────────────────────────────────────────────────────
def test_a_monthly_window_rule_returns_a_WINDOW_and_never_a_point():
    """Bar B11: "next_release on a windowed rule returns a window, never a point"."""
    r = C.next_release("silver_wasde", ASOF)
    assert r.fired and r.kind == "monthly_window"
    assert r.opens == "2026-09-09" and r.closes == "2026-09-12"
    assert r.date is None                       # a window rule can never name a day
    assert "between 2026-09-09 and 2026-09-12" in r.words
    assert r.dates == "2026-09-09 to 2026-09-12"


def test_a_monthly_window_rolls_to_the_next_month_once_this_month_HAS_CLOSED():
    """The window whose close is on or after the as-of. A window already past would be a forward date
    that has already happened."""
    assert C.next_release("silver_wasde", "2026-09-13").opens == "2026-10-09"
    still_open = C.next_release("silver_wasde", "2026-09-12")                   # the close itself
    assert still_open.closes == "2026-09-12"


def test_a_window_the_as_of_is_ALREADY_INSIDE_opens_at_the_as_of_and_never_behind_it():
    """An SB-W row calls this "the next scheduled print", and inside the publisher's own window the
    honest statement is "between today and the close". ``next_release('silver_wasde', '2026-09-11')``
    returned 2026-09-09..2026-09-12 -- a forward row naming a day already gone."""
    r = C.next_release("silver_wasde", "2026-09-11")
    assert (r.opens, r.closes) == ("2026-09-11", "2026-09-12")
    assert C.next_release("silver_wasde", "2026-09-12").opens == "2026-09-12"


def test_the_ONI_window_is_the_publishers_own_and_not_the_second_thursday():
    """DELTA PASS 1 item B4.1: CPC updates the ONI TABLE by the 5th; the second-Thursday habit belongs
    to the Diagnostic Discussion, a different product. The first landing of the config gave the
    Discussion's window to the table, and this pin is what keeps the correction."""
    r = C.next_release("silver_noaa_oni", ASOF)
    assert (r.opens, r.closes) == ("2026-10-01", "2026-10-05")


def test_a_weekday_rule_names_the_next_occurrence_STRICTLY_after_the_as_of():
    """On the print day itself the estate cannot know whether the print has landed, so naming today as
    a forward date would be a claim about the past wearing a future's clothes."""
    assert C.next_release("silver_esr", ASOF).date == "2026-09-10"        # Monday -> Thursday
    assert C.next_release("silver_esr", "2026-09-10").date == "2026-09-17"  # on Thursday -> next
    assert C.next_release("silver_cot", ASOF).date == "2026-09-11"        # Friday


def test_first_business_day_names_a_WEEK_and_never_a_DAY():
    """NASS and FGIS publish on "the first business day of each week" and the estate holds no holiday
    calendar for either (proved live: Labor Day moved the 2026-09-08 FGIS report off Monday). A rule
    that named a Monday would be wrong several times a year."""
    r = C.next_release("silver_fgis", ASOF)
    assert r.fired and r.kind == "first_business_day"
    assert r.week_of == "2026-09-14" and r.date is None
    assert "first business day" in r.words


def test_first_business_day_respects_the_publishers_own_SEASON():
    """NASS Crop Progress runs April 1 to November 30. A rule with no season would promise a January
    release no publisher will print."""
    winter = C.next_release("silver_nass_crop_progress", "2026-12-20")
    assert winter.week_of and winter.week_of >= "2027-04-01"
    summer = C.next_release("silver_nass_crop_progress", ASOF)
    assert summer.week_of == "2026-09-14"


def test_daily_sessions_names_no_day_at_all():
    """`venue_holidays.yaml` has empty GLBX years and is NOT read in V1, so naming a session date would
    be a claim the estate cannot back."""
    r = C.next_release("silver_futures_eod", ASOF)
    assert r.fired and r.dates == "" and r.date is None
    assert "next session" in r.words


def test_published_date_COMPUTES_NOTHING_and_says_so_with_a_closed_word():
    """The World Bank states a "Next update" DATE and follows no rule: the three observed 2026 prints
    share neither weekday nor day-of-month. `published_date` is mapped onto the closed `watch:` word
    `rule_unverified` (declared drift, sec 6.7's enum predates the kind) and the row says what it is."""
    r = C.next_release("silver_pink_sheet", ASOF)
    assert not r.fired and r.declined == "rule_unverified"
    assert r.dates == "" and "publisher states its next date" in r.words


# ── the absences ─────────────────────────────────────────────────────────────────────────────────────
def test_an_uncalendared_card_is_a_ROW_THAT_SAYS_SO():
    r = C.next_release("silver_noaa_iod", ASOF)
    assert r.declined == "no_calendar_rule"
    assert r.words == "no release rule is declared for this series"


def test_a_card_in_neither_map_declines_the_same_way():
    assert C.next_release("silver_not_a_card_at_all", ASOF).declined == "no_calendar_rule"


def test_an_unreadable_as_of_declines_rather_than_guessing():
    assert C.next_release("silver_wasde", "not-a-date").declined == "no_calendar_rule"


# ── the config's own contract with this consumer ─────────────────────────────────────────────────────
def test_every_declared_rule_kind_is_one_this_module_computes():
    """The consumer-side half of the lint: a kind the config declares and nobody implements would pass
    S0's lint and then decline at serve time with a word about the RULE when the fact is about the
    READER."""
    assert C.check_rule_kinds() == []


def test_every_declared_window_day_is_at_most_twenty_eight():
    """`_monthly_window` builds a date from the declared day with no clamping, which is safe only
    because every declared day exists in every month. The config's own comment says so; this asserts
    it."""
    for sid, src in (C.load_release_calendar().get("sources") or {}).items():
        rule = (src or {}).get("rule") or {}
        if rule.get("kind") != "monthly_window":
            continue
        assert 1 <= int(rule["day_min"]) <= 28, sid
        assert 1 <= int(rule["day_max"]) <= 28, sid
        assert int(rule["day_min"]) <= int(rule["day_max"]), sid


def test_a_table_appears_in_exactly_one_source_and_never_also_uncalendared():
    srcs, unc = C.table_sources(), C.uncalendared()
    assert not (set(srcs) & set(unc))
    seen: dict = {}
    for sid, src in (C.load_release_calendar().get("sources") or {}).items():
        for t in ((src or {}).get("tables") or ()):
            assert t not in seen, f"{t} in both {seen.get(t)} and {sid}"
            seen[t] = sid


@pytest.mark.parametrize("table", ["silver_wasde", "silver_esr", "silver_noaa_oni", "silver_mpob",
                                   "silver_fgis", "silver_futures_eod", "silver_pink_sheet",
                                   "silver_nass_crop_progress", "silver_cot"])
@pytest.mark.parametrize("asof", ["2026-01-01", "2026-02-28", "2026-09-01", "2026-09-07",
                                  "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12",
                                  "2026-09-13", "2026-10-05", "2026-12-31"])
def test_no_release_ever_names_a_date_before_the_as_of(table, asof):
    """PIT, restated as an invariant over every rule kind AND every as-of: whatever a rule computes, it
    is FORWARD. Parametrised over as-ofs INSIDE the declared windows, which is where the single-as-of
    version of this bar could not see: it passed only because 2026-09-07 sits outside every one of
    them."""
    r = C.next_release(table, asof)
    for d in (r.opens, r.closes, r.date, r.week_of):
        if d:
            assert d >= asof, (table, asof, d)
