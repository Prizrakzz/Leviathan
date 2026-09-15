"""THE WATCH-LIST PRODUCER -- STATE ENGINE DESIGN sec 5.1 (five kinds, ONE closed enum, ISO dates and
no other digits) over ``state/calendar.py``'s rules (5.2). Sitting S3.

THE ONE SENTENCE. Every watch row names a TABLE, a LEVEL, a DATE or a DOCUMENT; nothing here can
produce "watch the weather".

THE FIVE KINDS, and what each is made of:

  1. **next_release** -- the next scheduled print of a loud row's own card, from the RULE
     (:func:`calendar.next_release`). A card with no rule is a row that SAYS so, which is scenario 1's
     own CONAB item.
  2. **convention_distance** -- the distance to the nearest DECLARED desk line the reading has not
     crossed, minted as its own ``[N]`` through a registered ``window_change``-shaped subtraction, so
     it is a computed and RE-EXECUTABLE figure with a handle rather than a subtraction the reader must
     take on trust. THE ONLY KIND THAT CARRIES A FIGURE (sec 5.1); every other kind is words and ISO
     dates, which is why a copied watch row can never be charged a magnitude.
  3. **lag_window** -- the opening and closing of a declared lag window for a loud row or an open
     event, counted from the row's OWN printed anchor date (``walk.projection_window``).
  4. **analog_trigger** -- what the like state's consequence did by the band's close, sourced from the
     row already minted in the analog stanza. NO new read and NO new figure.
  5. **policy_date** -- a receipt published on or before the as-of whose ``event_date`` is AFTER it: a
     date the record already knew. PIT-safe because knowledge is the publication date, and the row
     prints BOTH dates. This is the only PIT-safe source of forward policy dates in the design and it
     needs no news producer.

WHY THE NEAREST UNCROSSED LINE, and it is DECLARED DRIFT from sec 0.3's scenario prose. That prose
measures a +0.98 degC ONI against the +1.5 degC strong line while the config declares four lines
(0.5 / 1.0 / 1.5 / 2.0, ``state_conventions.yaml``); picking the third when the reading sits just under
the second is a curator choosing which line matters, which is exactly what ruling 1 removes from the
engine. The rule here is the curation-free one -- the nearest line the reading has not crossed -- and
the S3 report names the difference rather than quietly reproducing the prose.

NO CLOCK, NO ENVIRONMENT, NO READ. Every input is threaded; the analog rows and the receipts arrive as
arguments, exactly as ``walk.walk`` takes its state producer.
"""
from __future__ import annotations

import re
from typing import Optional

from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import transforms as TR
from leviathan.graphrag.state.calendar import next_release
from leviathan.graphrag.state.rows import status_word

#: The ONE closed kind enum (sec 5.1). Order is the design's own numbering, and it is also the
#: interleave order of :func:`watch_rows` -- so a capped list always carries the earliest kinds first.
WATCH_KINDS: tuple = ("next_release", "convention_distance", "lag_window", "analog_trigger",
                      "policy_date")

#: The words each kind prints after "WATCH". A CLOSED map: the reader meets these five phrases and no
#: others, so a watch line's class is legible without reading its body.
KIND_WORDS: dict = {
    "next_release": "the next scheduled print",
    "convention_distance": "the level a convention names",
    "lag_window": "a declared lag window",
    "analog_trigger": "what the record did after a like state",
    "policy_date": "a date the record already knew",
}

#: SB-W rows RENDERED per tier -- sec 7's own line counts ("3 SB-W" on Scan, 6 on Analysis, 8 on
#: Cascade). It is a render cap and NOT one of the nine board knobs, because it prices no read: every
#: input above is already on the board. Declared here, beside its only consumer.
WATCH_RENDER_K: dict = {"quick": 3, "deep": 6, "max": 8}

#: The unit WORD each convention kind measures its distance in. ``abs_bands`` falls back to the row's
#: own narrate unit, because the distance is in the series' own unit and the config states it per ref.
DISTANCE_UNITS: dict = {"z_bands": "sigma", "percentile_bands": "percentile points",
                        "pace_vs_prior_year": "percentage points"}


def render_k(mode: str, knobs=None) -> int:
    """The tier's watch render cap. S6: ``knobs.render_watch`` WINS when the board carries the render
    fields, so this table is the DEFAULT rather than a second opinion -- and a board built from a
    nine-field knob tuple (the S2 fixtures, the census) still reads the table, because a missing
    attribute must never be read as a cap of zero."""
    from leviathan.graphrag import reasoning_modes as rm
    v = getattr(knobs, "render_watch", None) if knobs is not None else None
    if v is not None:
        return int(v)
    return int(WATCH_RENDER_K.get(rm.base_mode(mode), 6))


def _conventions() -> dict:
    """The desk-convention document. Read through ``state/lint.py``'s lru_cached loader rather than a
    second reader in this module -- one producer per config file is the rule this package keeps."""
    from leviathan.graphrag.state.lint import load_conventions
    return dict((load_conventions().get("conventions") or {}))


# ---------------------------------------------------------------------------------------------------
# kind 2 -- the distance to a declared line, as a RE-EXECUTABLE figure
# ---------------------------------------------------------------------------------------------------
def _crossed(kind: str, reading: float, band: float, bands: list) -> bool:
    """Has this reading already crossed this line, under the kind's own declared semantics
    (``band_semantics`` in ``state_conventions.yaml``)?"""
    if kind in ("abs_bands", "z_bands"):
        return abs(reading) >= band
    if kind == "percentile_bands":
        return reading <= band if band < 50 else reading >= band
    if kind == "pace_vs_prior_year":
        lo, hi = (min(bands), max(bands)) if bands else (band, band)
        return reading <= lo if band == lo else reading >= hi
    return False


def _measure_reading(kind: str, st) -> Optional[float]:
    """The reading a convention KIND is measured on, taken off the STATE ROW'S OWN MEASURES.

    IT EXISTS FOR THE OVERLAY AND FOR NOTHING ELSE (S7b, threat A-3). ``feeders._convention_label``
    computes ``st.convention['reading']`` only for refs that ``lint.load_conventions()`` carries, so a
    ref reached through the WATCH-ONLY overlay has a band and no reading and
    :func:`convention_distance` would return ``None`` on every one of them -- which is exactly the
    fifteen balance-sheet and livestock refs the curation is for. The arithmetic is
    ``_convention_label``'s own, restated over the same three fields, and ``pace_vs_prior_year`` is
    DELIBERATELY ABSENT: that kind's reading is a registered transform over the bundle, not a field,
    and inventing a second pace producer here is the duplicate-and-drift class this package refuses.
    An overlay entry of that kind therefore declines by returning ``None``, which is a silence on one
    kind and never on the row."""
    if st is None:
        return None
    if kind == "abs_bands":
        return TR.num_or_none(st.level)
    if kind == "z_bands":
        return None if (not st.z or st.z.get("declined")) else TR.num_or_none(st.z.get("value"))
    if kind == "percentile_bands":
        return (None if (not st.percentile or st.percentile.get("declined"))
                else TR.num_or_none(st.percentile.get("value")))
    return None


def convention_distance(row, *, conventions: Optional[dict] = None,
                        measure_fallback: bool = False) -> Optional[dict]:
    """The nearest DECLARED line this row's reading has not crossed, with its derivation record.

    Returns ``None`` when there is nothing to measure -- no convention for the ref, no reading, or a
    reading past every declared line. That last case is a SILENCE ON ONE KIND, never a silence on the
    row: the SB-1 line has already said which line the reading is past, so a watch row saying "there is
    no further line" would add a sentence and no fact.

    THE SUBTRACTION IS A REGISTERED TRANSFORM (sec 5.1 kind 2): ``window_change`` over the two-point
    bundle ``[band, reading]``, so the figure re-executes from its own inputs like every other magnitude
    on the board and ``feeders.re_execute_row``'s proof covers it."""
    st = row.state
    if st is None or status_word(st.status) != "ok":
        return None
    conv_doc = _conventions() if conventions is None else conventions
    ref = st.key.ref
    conf = conv_doc.get(ref) or {}
    kind = str(conf.get("kind") or (st.convention or {}).get("kind") or "")
    bands = [float(b) for b in (conf.get("bands") or [])]
    labels = list(conf.get("labels") or [])
    if not kind or not bands or len(labels) != len(bands):
        return None
    reading = (st.convention or {}).get("reading")
    if reading is None and measure_fallback:
        # THE OVERLAY'S ONE EXTRA STEP, and it is OFF BY DEFAULT so every HEAD-covered ref takes the
        # HEAD path byte for byte: a ref the served conventions document does not carry has no
        # ``st.convention`` at all, so its reading is read off the row's own measures instead.
        reading = _measure_reading(kind, st)
    if reading is None:
        return None
    reading = float(reading)

    # THE NEXT LINE IN THE DIRECTION THE READING ALREADY SITS, and that qualifier is the correction the
    # first cut needed. Nearest-uncrossed ALONE picked the line on the far side: a crush margin at the
    # 99.84th percentile, having crossed the 90th, measured itself "89.84 percentile points OVER the low
    # line at the 10th" -- arithmetic nobody asked for. A magnitude band (abs / z) has one direction by
    # construction; a percentile or pace band has two, and the reading's own side is the one a watch row
    # is about.
    shown0 = abs(reading) if kind in ("abs_bands", "z_bands") else reading
    best = None
    for b, lbl in zip(bands, labels):
        if _crossed(kind, reading, b, bands):
            continue
        if kind in ("percentile_bands", "pace_vs_prior_year"):
            mid = 50.0 if kind == "percentile_bands" else 0.0
            if (shown0 >= mid) != (b >= mid):
                continue
        gap = abs(shown0 - b)
        if best is None or gap < best[0]:
            best = (gap, b, lbl)
    if best is None:
        return None
    gap, band, label = best
    shown = shown0
    direction = "under" if shown < band else "over"

    key = f"{st.key.label()}#convention_distance"
    bundle = {key: {"values": [band, shown], "dates": [str(st.level_date or ""), str(st.level_date or "")],
                    "unit": st.narrate_unit or st.unit or ""}}
    res, rec = TR.run_transform("window_change", bundle, key=key,
                                params={"t1": 0, "t2": 1, "window_label": f"to the {label} line"})
    if res.get("declined"):
        return None
    unit_words = DISTANCE_UNITS.get(kind) or str(conf.get("unit") or st.narrate_unit or st.unit or "")
    return {"distance": abs(float(res["value"])), "band": band, "label": str(label),
            "kind": kind, "unit_words": unit_words, "direction": direction,
            "band_words": _band_words(kind, band, unit_words),
            "derivation": rec, "inputs": bundle, "reading": shown}


def _band_words(kind: str, band: float, unit_words: str) -> str:
    """The LINE ITSELF, in the reading's own vocabulary. A percentile band is an ORDINAL POSITION and
    not a quantity of points, so "at the tenth percentile" is what the line says; printing "at 10
    percentile points" would put a position and a distance in the same units on one row."""
    if kind == "percentile_bands":
        return f"the {R.ordinal(band)} percentile"
    if kind == "pace_vs_prior_year":
        return f"{R._fmt(band)} percent against the prior year"
    return f"{R._fmt(band)} {unit_words}".strip()


# ---------------------------------------------------------------------------------------------------
# the producer
# ---------------------------------------------------------------------------------------------------
def watch_overlay() -> dict:
    """THE WATCH-ONLY CONVENTIONS OVERLAY -- ``state_conventions.yaml``'s own ``watch_overlay:`` block.

    IT IS A SEPARATE TOP-LEVEL KEY AND THAT IS THE WHOLE DESIGN (threat A-3). The file's
    ``conventions:`` block is read by ``feeders._convention_label`` -> ``StateRow.convention`` ->
    ``walk._convention_hit``, which is a TERM OF ``walk.rank_key`` -- so curating fifteen refs into it
    would change ``bd.order``, and therefore every rendered line of every board-on turn, with every
    flag off. A config curation is the one change in this sitting that CANNOT be dark behind a code
    flag. Under its own key it reaches this producer alone, ``load_conventions()``'s consumers never
    see it, and SB-1's "past the line the desk convention calls X" clause is untouched.

    A LIVE CURATION IS A SEPARATE, DECLARED, NON-BYTE-IDENTICAL CHANGE with its own 144-turn census.
    This is the overlay, not that."""
    from leviathan.graphrag.state.lint import load_conventions
    return dict((load_conventions().get("watch_overlay") or {}))


def watch_rows(bd, *, analogs=(), cap: Optional[int] = None, conventions: Optional[dict] = None,
               calendar_doc: Optional[dict] = None, nonobvious: bool = False,
               overlay: Optional[dict] = None, loud_k: Optional[int] = None) -> list:
    """EVERY watch row this board can name, interleaved by kind and cut at the tier's render cap.

    ``nonobvious`` IS THE 09-11 RULING'S FLAG, threaded as a KWARG because this package reads no
    environment (two shipped doctrine tests assert it on the source). With it FALSE -- the default, and
    what every HEAD caller passes -- every byte below is HEAD's. With it TRUE the five-kind interleave
    is REPLACED by :func:`nonobvious_rows`' ranked 2N nomination: replaced and not appended, because
    the section is the writer's "what to watch" and two lists under one heading is two answers.

    THE INTERLEAVE IS WHY THE CAP DOES NOT EAT A KIND. A straight rank walk would fill an eight-row cap
    with kind-1 rows on a twelve-row loud set and the reader would never meet a lag window at all; the
    kinds are queued separately and drawn round-robin in the design's own numbering, and inside each
    queue a FIRED row always precedes a DECLINED one -- an absence is a row, but it never displaces a
    fact.

    THIS FUNCTION NEVER GUESSES A HANDLE POSITION. A kind-2 row carries the four numbers and the row
    object; the RENDER mints the line, because the handle it takes depends on how many magnitudes the
    block has already committed and only the block knows that."""
    if nonobvious:
        return nonobvious_rows(bd, analogs=analogs, cap=cap, conventions=conventions,
                               overlay=watch_overlay() if overlay is None else overlay,
                               calendar_doc=calendar_doc, loud_k=loud_k)
    k = cap if cap is not None else render_k(bd.mode, getattr(bd, "knobs", None))
    order = {key: i for i, key in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    queues: dict = {kind: [] for kind in WATCH_KINDS}

    from leviathan.graphrag.state.walk import projection_window

    for row in loud:
        st = row.state
        # -- kind 1: the next scheduled print of this row's own card --------------------------------
        table = (st.table if st is not None else "") or ""
        if table:
            rel = next_release(table, bd.asof, doc=calendar_doc)
            queues["next_release"].append({
                "kind": "next_release", "kind_words": KIND_WORDS["next_release"],
                "label": f"{R.humanise(row.driver_id)} on {R.board_label(row.contract)} ({R.table_words(table)})",
                # THE DATE-FREE SENTENCE, because the SB-W row prints the dates in its own tail.
                "what": rel.rule_words or rel.words, "dates": rel.dates, "declined": rel.declined,
                "source": rel.source, "row": row.key})
        # -- kind 2: the distance to the nearest uncrossed declared line ----------------------------
        cd = convention_distance(row, conventions=conventions)
        if cd is not None:
            # THE ROW OBJECT AND THE FOUR NUMBERS RIDE, and the RENDER mints the line -- because kind 2
            # renders in SB-V's own form (sec 5.1's "6.2's form is kept") and the handle it takes
            # depends on how many magnitudes the block has already minted. A producer that minted the
            # line here would have to guess that position.
            queues["convention_distance"].append({
                "kind": "convention_distance", "kind_words": KIND_WORDS["convention_distance"],
                "label": f"{R.humanise(row.driver_id)} on {R.board_label(row.contract)}",
                "what": (f"the reading sits {R._fmt(cd['distance'])} {cd['unit_words']} "
                         f"{cd['direction']} the {cd['label']} line at {cd['band_words']}"),
                "dates": str((st.level_date if st is not None else "") or ""),
                "declined": None, "call": True, "row_obj": row, "derivation": cd["derivation"],
                "distance": cd["distance"], "band": cd["band"], "conv_label": cd["label"],
                "unit_words": cd["unit_words"], "direction": cd["direction"],
                "band_words": cd["band_words"], "row": row.key})
        # -- kind 3: the declared lag window, counted from this row's own anchor date ---------------
        win_src = bd.windows.get(row.key) or {}
        anchor = row.event_date or win_src.get("near") or (st.level_date if st is not None else None)
        # A LABEL WALK'S OWN MONTH ARITHMETIC CANNOT READ IS NOT AN ANCHOR HERE. ``walk._add_months``
        # slices ``iso[5:7]``, and on the MARKETING-YEAR label ``feeders._period_dates`` legitimately
        # writes for a card that carries ``year`` and no month (a bare ``YYYY``) that slice is empty --
        # ``int("")`` raises, which is the same ``invalid literal for int() with base 10: ''`` the S4
        # in-VPC pass measured. ``""`` and ``None`` are already falsy and decline above; this is the
        # third form. It is a GUARD, not the fix: the fix is one line inside ``walk._add_months``
        # -- place the label through ``analogs.axis_date``, which knows all three forms, exactly as
        # ``analogs._window_end`` now does. THE FUNCTION IS CITED BY NAME AND NEVER BY LINE: the lane
        # that holds walk.py moved it (1052 -> 1077) while this comment was being reviewed, and a line
        # number is a citation that rots. walk.py is held by that lane, so the watch row declines by
        # name instead of ending the board and the defect is carried as a finding -- measured by
        # ``tests/unit/test_state_null_boundary.py`` sections 5 and 6, and gated at the door by
        # ``jobs/submit/submit_batch_board_census.annual_handover_open``.
        if anchor is not None and len(str(anchor)[:10]) < 7:
            anchor = None
        if anchor:
            w = projection_window(anchor, row.lag_band)
            if w.get("declined") or not w.get("opens"):
                queues["lag_window"].append({
                    "kind": "lag_window", "kind_words": KIND_WORDS["lag_window"],
                    "label": f"{R.humanise(row.driver_id)} on {R.board_label(row.contract)}",
                    "what": R.absence_why(w.get("declined") or "no_open_window"), "dates": "",
                    "declined": "no_open_window", "row": row.key})
            else:
                closes = w.get("closes")
                still = (closes is None) or (closes >= bd.asof)
                queues["lag_window"].append({
                    "kind": "lag_window", "kind_words": KIND_WORDS["lag_window"],
                    "label": f"{R.humanise(row.driver_id)} on {R.board_label(row.contract)}",
                    "what": (f"the {R.band_words(row.lag_band)} window the graph declares, counted "
                             f"from that reading's own date, "
                             + ("opens and does not close" if closes is None else
                                ("opens and closes on these dates" if still else
                                 "opened and has already closed on these dates"))),
                    "dates": (w["opens"] if closes is None else f"{w['opens']} to {closes}"),
                    "declined": None if still else "no_open_window", "row": row.key})
        # -- kind 5: a forward date the record already knew ------------------------------------------
        for rc in ((row.receipts or {}).get("top") or ()):
            ed = str(rc.get("event_date") or "")
            pub = str(rc.get("date") or "")
            if not ed or not pub or ed[:10] <= bd.asof or pub[:10] > bd.asof:
                continue
            queues["policy_date"].append({
                "kind": "policy_date", "kind_words": KIND_WORDS["policy_date"],
                "label": f"{R.humanise(row.driver_id)} on {R.board_label(row.contract)}",
                "what": (f"a document already on the record names a date still ahead "
                         f"(reported {pub})"),
                "dates": ed[:10], "declined": None, "row": row.key})

    # -- kind 4: the analog's own trigger, sourced from a row already minted ------------------------
    for a in analogs:
        if a.get("declined"):
            continue
        for o in (a.get("outcomes") or ()):
            if o.get("declined") or not o.get("far_date"):
                continue
            queues["analog_trigger"].append({
                "kind": "analog_trigger", "kind_words": KIND_WORDS["analog_trigger"],
                "label": f"{R.humanise(a['driver_id'])} on {R.board_label(a['contract'])}",
                "what": (f"after the like state dated {a['date']}, {o['label']} was read at the far "
                         f"end of that declared band"),
                "dates": o["far_date"], "declined": None, "row": (a["contract"], a["driver_id"])})
            break                                   # ONE trigger per stanza: the stanza is the source

    for kind in WATCH_KINDS:                        # a fired row never sits behind a declined one
        queues[kind].sort(key=lambda w: (1 if w.get("declined") else 0))

    out: list = []
    idx = {kind: 0 for kind in WATCH_KINDS}
    while len(out) < max(0, int(k)):
        progressed = False
        for kind in WATCH_KINDS:
            q, i = queues[kind], idx[kind]
            if i >= len(q):
                continue
            out.append(q[i])
            idx[kind] = i + 1
            progressed = True
            if len(out) >= max(0, int(k)):
                break
        if not progressed:
            break
    return out


def watch_leg(bd, rows) -> dict:
    """The ``watch`` leg's stamp (sec 6.7). ``fired`` when any row names a date, ``declined`` with the
    DOMINANT closed word when every row is an absence, ``not_reached`` when the producer made none.

    THE FOOTNOTE DOES NOT VOTE (review round 3, minor -- an unexercised path, fixed as one). A board
    that clears the admission floor with NOTHING but carries scheduled prints emits two declined rows:
    the honest absence line and the dated-releases footnote. The dominant-word sort is
    ``(-count, word)``, so at one each ``release_dates_only`` wins on the alphabet and the leg is
    stamped with the CALENDAR word -- masking, on the trace, the very state the 09-11 ruling asked the
    list to be able to report. The footnote is a note ABOUT what is not an item; it is excluded from the
    vote unless it is all there is. MEASURED: 0 of 108 replay seats and 0 of 9 armed cells reach this
    (no board produced a full absence), and no HEAD watch kind is ``release_footnote``, so the flag-off
    histogram cannot move."""
    if not rows:
        return bd.stamp("watch", "not_reached")
    fired = [w for w in rows if not w.get("declined")]
    if fired:
        return bd.stamp("watch", "fired")
    voters = [w for w in rows if w.get("kind") != "release_footnote"] or list(rows)
    counts: dict = {}
    for w in voters:
        counts[w["declined"]] = counts.get(w["declined"], 0) + 1
    word = sorted(counts, key=lambda x: (-counts[x], x))[0]
    return bd.stamp("watch", "declined", reason=word)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# THE NON-OBVIOUS WATCH LIST (owner ruling 2026-09-11), DARK behind ``nonobvious=``
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
"""WHAT TO WATCH IS THE TOP N OF NON-OBVIOUS, CONVEX / TAIL-ASYMMETRIC ITEMS, and every word of that
sentence is a rule below. This section is the RECORD of the PM-eye critique of the 09-11 prototype
(R1-R17): that critique exists as a digest in a memory file and in a task brief and has no banked
artefact of its own, so the rank it adopted is written here, in code, with each term's measured reason
beside it.

THE CEILINGS ARE CEILINGS AND NEVER QUOTAS (R2). Four backed items and one honest absence line beat
five rows where two are noise. :data:`WATCH_NONOBVIOUS_K` is 3 / 5 / 7 and the draw NEVER pads from a
lower queue to reach it. **AND THE CEILING IS SAID OUT LOUD**: every drawn row carries its pass, its
place and that pass's size, ``render.sb_watch`` prints "core item one of five" / "alternate two of
five", and :data:`WATCH_SELECTION_CLAUSE` tells the writer to keep at most the core. A ceiling the
writer cannot see is a cap on the draw and nothing else, which is what it was until review round 2's
MAJOR 2 -- measured at 6 / 10 / 12-14 indistinguishable nomination lines against HEAD's 3 / 6 / 8.

WHY THIS IS A SECOND CAP AND NOT AN EDIT TO :data:`WATCH_RENDER_K`. ``reasoning_modes``' knob table
declares ``render_watch`` 3 / 6 / 8 per tier and two shipped decks assert
``knobs.render_watch == WATCH_RENDER_K[mode]`` (``test_state_board.py:121``,
``test_state_seam.py:870``). ``reasoning_modes.py`` is not this lane's file, and editing the shipped
table would change deep and max with every flag OFF -- which the 09-10 no-cap law forbids outright. So
HEAD's cap keeps HEAD's numbers for HEAD's producer, and the non-obvious producer carries its own.

THE ADMISSION FLOOR (R1), five clauses, ANY-OF -- see :data:`FLOOR_CLAUSES`. A board that clears none
prints ZERO nomination rows and ONE honest absence line; it never prints a padded list.

THE RANK, in the 09-11 ruling's own order, each term an explicit field on the candidate record:

  ``T_AMPLIFIER``  a pattern at or past its own threshold CARRYING A DECLARED AMPLIFIER LINE first, a
                   pattern at its threshold second, and EVERYTHING ELSE NEUTRAL -- a pattern short of
                   its threshold and no pattern at all tie, because an unmet pattern is not evidence of
                   convexity. Three levels, named in :data:`AMPLIFIER_LEVELS` and graded by the lint;
                   the fourth value this term shipped with is review round 2's MAJOR 3 and the
                   measurement that removed it is beside the constant.
  ``T_NONLINEAR``  **INVERTED** (R5): past-the-line WITH THE RUN STILL GOING DEEPER outranks approaching
                   an uncrossed line. The first cut had it the other way round on the theory that an
                   uncrossed line is the "next event"; the critique's answer is that a line already
                   crossed with the run continuing is the convex state, and the approach is a forecast.
                   The unit-free progress fraction is printed for the APPROACHING case ONLY and only
                   when a run points at the line.
  ``T_TAIL``       BAND-FREE ``|pct - 50| / 50`` (R7). It is the ONLY term that can see the
                   balance-sheet and livestock family: fifteen silver refs carrying 463 of the banked
                   order rows have no ``state_conventions`` entry at all (measured over
                   ``board_census_run5``'s 144 traces), so every band-keyed term is structurally blind
                   to stocks, area, exports, crush and the cattle herd. This term reads ``percentile``
                   and NEVER ``conventions``.
  ``T_RUN``        consecutive prints in the tail's direction.
  ``T_PATHS``      declared upstream paths landing on THIS price, DEPTH BEFORE BREADTH (R11).
  ``T_BREADTH``    how many other boards carry the same reading.
  ``T_WINDOW``     LAST (R12), and it is the soonest window OPEN date. It is last because a window date
                   is a calendar fact about a lag band, not a statement about the state -- ranking on it
                   put the nearest lag ahead of the biggest asymmetry on 4 of the prototype's seats.

``T_NOVELTY`` IS COMPUTED ON THE RENDERED SENTENCE AND ITS FIGURES and is NOT one of those seven. The
ruling names it as a property of the MEASUREMENT -- "never asserted per kind" -- and gives the rank
above without it, so it sorts AFTER ``T_WINDOW`` and before the determinism stabiliser, where it
separates candidates the ruling's terms tie. :func:`novelty` carries the measurement that forced this:
the first cut asserted it per kind in all but name (0 of 94 candidates scored its top value across the
three fixtures) and, leading the tuple, cost ``past_the_line`` and ``tail_reading`` every ceiling slot
on every fixture.

THE BANS ARE ENFORCED AT NOMINATION AND NEVER AT RENDER (P-1). A lint that struck a rendered sentence
would be a fence that deletes, which this estate calls FATAL. A banned item is a candidate that is
never built, the refusal is a COUNTER on the trace, and no rendered line is ever removed:

  * NO RELEASE-CALENDAR ITEM. ``next_release`` is not a non-obvious kind and is not nominated; the
    scheduled prints are named ONCE, in a single dated footnote outside the ceiling. The ban is keyed
    on the KIND and asserted against ``calendar.KIND_WORDS`` / ``calendar.RULE_WORDS`` membership, so
    the eleven-of-thirty DECLINED release rows ("the venue calendar is not read here, so no day is
    named") are covered by construction rather than by a second vocabulary.
  * ``context_only`` IS NEVER AN ANCHOR unless the question names positioning -- ``NodeRow.subject``,
    Amendment 1's own exception. The prototype ranked ``cot mm positioning -> ICE arabica`` THIRD on
    every soybean seat.
  * A CLOSED WINDOW IS NEVER NOMINATED, and after the ``reading`` anchor lands in ``walk._stage2`` it
    cannot be built: 10 of the prototype's 60 rows rendered a 1997-1998 window for a 2026 reading
    because the window was counted from the RUN START rather than from the reading's own date.

SAY WHAT THE NUMBER IS (R13) and SAY THE SIDE (R15). A sentence carrying a figure carries that
figure's own metric words and unit -- the prototype printed "Brazil export tax" over ``level=118000000
MMT``, which is an export VOLUME under a node named for a tax -- and a reading folded to ``|v|`` by an
``abs_bands`` / ``z_bands`` convention says which tail it sits in.

DEDUPE ON THE SERIES KEY **AND** THE DECLARED OFFSET (R10). El Nino reaches 34 boards and two of them
read a six-month-offset series (``oni_lag_climate`` folded onto ``oni_climate`` through
``same_series_as``, ``StateRow.offset_months``); a dedupe on the driver id merges two different
readings and a dedupe on the label splits one.

NOMINATE 2N, THE WRITER SELECTS (R16). The board hands the writer twice the ceiling, each candidate
carrying its mechanism sentence, its backing row and a STATED FALSIFIER, and
:data:`WATCH_SELECTION_CLAUSE` is the licence the mandate gives the writer to keep, drop, merge,
reorder and -- once, with a named mechanism and a named row -- add. The coverage instrument records
candidates used against writer-added PER BULLET (round 4): a nomination is used when its [N] handle or
its series key appears in a shipped watch bullet, a bullet with neither is writer-added. Scoring each
armed block against its own rendered text -- the writer that added nothing and dropped nothing -- now
reads EXACTLY all-used / none-added on the nine armed cells, and ``render.NOMINATION_ZERO_WRITER_BASELINE``
records that measured zero; the retired per-sentence read had put three to seven "added" there.

EVERY ROW STILL RIDES **SB-W**. Not one new row class ships: the sentences are letters, ISO dates,
counts in words and a citation handle, which is exactly what ``render.FIGURE_CLASSES``' bar admits on a
letters-only class. A class with no sample would red ``lint._check_row_classes``, and the whole point
of the ruling is the CONTENT of the watch list, not a new shape for it.

NOT IN THIS BUILD, and said here rather than shipped as a kind that declines on every turn:
  * the "what followed" PRECEDENT clause on a recurrence -- it needs the window-scoped proposition
    fetch (V1.1);
  * KIND A, EXPIRIES -- they need the receipt leg on board turns, and the supply on the whole mirror
    today is SB-D 0/144, SB-R 0/144, ``policy_date`` 0 of 100 banked order rows, with ``event_date``
    reachable only from a fetched receipt that no census turn fetched;
  * ``analogs.co_loud_analogs`` as the recurrence producer -- it is written, docstring'd and unwired,
    and wiring it needs a ``benchmark_fn`` the SEAM injects (another lane's file) and carries an
    O(dates x anchors x dates) percentile pass. The recurrence kind reads the ORDINARY analog stanzas,
    which already fire on 96 of the 144 banked turns and already carry ``n_candidates``.
"""

#: The NON-OBVIOUS ceiling per tier -- the owner's 3 / 5 / 7 (2026-09-11). A CEILING, never a quota.
WATCH_NONOBVIOUS_K: dict = {"quick": 3, "deep": 5, "max": 7}

#: How many candidates the board NOMINATES per rendered ceiling slot. 2N is the owner's number: the
#: writer selects from twice the ceiling and narrates what it keeps.
NOMINATE_MULTIPLE: int = 2

#: The non-obvious kinds, in DECLARATION order. This is a vocabulary and not a rank -- the rank is
#: :func:`rank_terms` and nothing here is drawn round-robin: a ceiling filled by interleave would be a
#: quota by another name, which is exactly what the 09-11 ruling struck.
NONOBVIOUS_KINDS: tuple = ("past_the_line", "tail_reading", "approaching_line", "convergence_amplified",
                           "upstream_convergence", "spillover_reach", "recurrence")

#: The words each non-obvious kind prints after "WATCH". CLOSED, like :data:`KIND_WORDS`: a reader meets
#: these seven phrases and no others. None of them contains "met", "fires" or "the regime is" --
#: ``walk.CONVERGENCE_BANNED_WORDS`` is a bar on what a pattern row may say and a watch row that
#: narrates a pattern is under the same bar.
NONOBVIOUS_KIND_WORDS: dict = {
    "past_the_line": "a reading already past a declared line",
    "tail_reading": "a reading in its own record's tail",
    "approaching_line": "a reading running at a line it has not crossed",
    "convergence_amplified": "a declared pattern at its own threshold",
    "upstream_convergence": "declared upstream paths landing on one price",
    "spillover_reach": "one reading declared on several other markets",
    "recurrence": "a state the record has been in before",
    # THE VARIANTS' OWN WORDS (:data:`NONOBVIOUS_VARIANTS`). `render.sb_watch` PRINTS this phrase
    # ahead of the label, so a row whose sentence says the run points away from the line may not be
    # introduced as one "running at" it -- the header and the body would contradict each other inside
    # one line.
    "approaching_line_away": "a reading near a line it has not crossed, running away from it",
    "approaching_line_unplaced": "a reading near a line it has not crossed",
    "spillover_reach_unplaced": "one reading declared on several other markets",
}

# ---------------------------------------------------------------------------------------------------
# THE SENTENCES, AS TEMPLATES -- and the reason they are templates and not f-strings
# ---------------------------------------------------------------------------------------------------
"""THE WRITER COPIES THIS BLOCK'S VOCABULARY, so the block may not teach it the instrument's words.

MEASURED 2026-09-11 on nine banked real-seat answers: 195 internal-vocabulary hits -- ``board`` 64,
``row(s)`` 54, ``the graph`` 40, plus ``loud``, ``convention``, ``knowledge date``, ``state read``,
``node`` and ``receipt``. The first cut of this producer ADDED 41 / 34 / 49 more on the three
acceptance fixtures, every one of them in a new WATCH line ("sit among this board's loudest rows",
"the graph places three declared upstream paths"), while the sibling register lane was landing a
lint whose declared target is ZERO and whose remedy is a PAID rewrite call. One lane raising the
surface the other pays to clean is one lane too many, so the sentences are written in desk register
here, at the producer, where it costs nothing: ``register.desk_register_hits`` on every rendered
nomination is the bar, and it is measured in the deck.

THEY ARE ``str.format`` TEMPLATES AND NOT f-STRINGS FOR A SECOND REASON, and it is the novelty term's
(see :func:`novelty`). Novelty is computed on the RENDERED SENTENCE, which means the sentence's FIXED
words -- "decile", "hops", "route", "observations" -- would each be a constant every candidate of that
kind carries and no SB-1 line does, i.e. a per-kind assertion smuggled into a term the 09-11 ruling
says may never be asserted per kind. With the fixed words held here as templates, :data:`_GRAMMAR` is
derived FROM THEM at import, exactly and with no hand-kept second list, and the term sees only the
words the BOARD put in the sentence."""

#: THE VARIANT SENTENCES OF A KIND WHOSE CLAIM HAS MORE THAN ONE TRUE SHAPE, and the kind each one
#: belongs to. A VARIANT IS NOT A KIND: it does not enter :data:`NONOBVIOUS_KINDS`, the draw's
#: per-kind cap counts it under its own kind, and the trace stamps the kind -- what it owns is the
#: four reader-facing strings (words, body, mechanism, falsifier), because a sentence that says the
#: run points AWAY from a line may not be labelled "a reading running at a line" or carry a falsifier
#: about a run breaking before it. Declared here so :func:`_cand` cannot invent one and
#: ``lint._check_nonobvious_watch`` can grade every string each variant carries.
NONOBVIOUS_VARIANTS: dict = {
    "approaching_line_away": "approaching_line",
    "approaching_line_unplaced": "approaching_line",
    "spillover_reach_unplaced": "spillover_reach",
}

#: The MECHANISM each kind rests on -- one sentence, the ruling's own "its mechanism".
NONOBVIOUS_MECHANISMS: dict = {
    "past_the_line": "a declared desk line already crossed, with the series still moving away from it",
    "tail_reading": "a reading in its own record's tail, where the next move is not symmetric",
    "approaching_line": "a declared line not yet crossed, with the run pointing at it",
    "approaching_line_away": ("a declared line not yet crossed, with the run pointing away from it "
                              "and the distance to it the fact"),
    "approaching_line_unplaced": ("a declared line not yet crossed, with the distance to it measured "
                                  "and the run not placeable against it"),
    "spillover_reach_unplaced": ("one reading the declared model carries onto several markets at "
                                 "once, with no committed direction declared here to compare them "
                                 "with"),
    "convergence_amplified": ("several declared drivers of one pattern moving at once, which is not "
                              "additive"),
    "upstream_convergence": "one cause reaching the price down more than one declared path",
    "spillover_reach": "one reading the declared model carries onto several markets at once",
    "recurrence": "a like state whose consequence window has already closed on the record",
}

#: The STATED FALSIFIER each kind carries -- the ruling's "the reading that would show it wrong".
NONOBVIOUS_FALSIFIERS: dict = {
    "past_the_line": "the next print turns back inside that line, or the run breaks",
    "tail_reading": "the next print returns the series to the middle of its own record",
    "approaching_line": "the run breaks before the line, which leaves the reading where it is",
    "approaching_line_away": ("the run carries on, which widens the distance to that line rather than "
                              "closing it"),
    "approaching_line_unplaced": ("this run is not the one that closes the distance to that line, "
                                  "which leaves the reading where it is"),
    "convergence_amplified": ("one of the drivers that pattern names turns, which puts the count back "
                              "under its own threshold"),
    "upstream_convergence": ("the paths share a single upstream cause, in which case they are one "
                             "route counted twice"),
    "spillover_reach": ("that market's own declared edge carries no sign, in which case the reach is "
                        "a count and not a direction"),
    "spillover_reach_unplaced": ("the edge declared here takes a committed direction, in which case "
                                 "each of those markets can be placed with it or against it"),
    "recurrence": ("the like states cluster in one episode, in which case the count is one event and "
                   "not a rate"),
}

#: The BODY of each kind's sentence. Every ``{slot}`` is a word the BOARD supplies; every other word is
#: fixed and is therefore part of :data:`_GRAMMAR`.
NONOBVIOUS_BODIES: dict = {
    "past_the_line": ("the reading is past the line the desk convention calls {label} and its run has "
                      "not turned: {run_n} consecutive {periods} {run_words}, {side}{figure}"),
    # **THE LINE CLAUSE IS A SLOT AND NOT A FIXED SENTENCE** (review round 2, MAJOR 1). This body ended
    # unconditionally "; no desk line is declared for this series, so the record's own tail is the whole
    # fact" -- on a kind that fires whenever `record_tail` is in the floor and `past_a_declared_line` is
    # not, which INCLUDES every row whose ref does carry a declared line. MEASURED over the 144 banked
    # census seats: of 706 decile-loud rows, 397 rendered that clause -- 311 on refs whose only line is
    # the `watch_overlay` this same lane curated (every overlay band is [10, 90] and `TAIL_DECILE` is
    # 10.0, so an overlay ref clearing `record_tail` has crossed the overlay's own line BY
    # CONSTRUCTION), and 86 on base-convention refs that failed the floor's "and the run is still going
    # deeper" half. On the four-board deep replay 8 of 20 ceiling rows carried it, `oni_climate` among
    # them. The remedy is a CORRECTION and never a strike: the clause is chosen from the row's own line
    # fact (:func:`_declared_line`), and where a line IS declared and crossed the sentence NAMES it.
    "tail_reading": ("the reading sits in the {where} decile of this series' own record, {side}"
                     "{figure}{line}"),
    "approaching_line": ("the reading has not crossed the line the desk convention calls {label} and "
                         "its run points at it: {run_n} consecutive {periods} {run_words}, {side}"
                         "{progress}{figure}"),
    # **THE RUN'S DIRECTION IS TESTED AGAINST THE BAND'S OWN SIDE, AND THESE ARE THE OTHER TWO ANSWERS**
    # (review round 3, MAJOR 1). The claim above is the ruling's convexity fact -- a line not yet
    # crossed with the series running at it -- and the builder was asserting it off the run's LENGTH
    # alone: MEASURED on the 144 banked seats, 10 of 42 drawn rows ran AWAY from the line they named
    # and all 10 sat in a core slot (BRL FX at a z of -0.617 against an uncrossed |1.5| band, rising).
    # The row is CORRECTED and never struck: the distance to the line is a real fact about a real
    # reading, the sentence says which way the run actually points, and :func:`rank_terms` withholds
    # the T_RUN credit from a run that is not the claim's own.
    "approaching_line_away": ("the reading has not crossed the line the desk convention calls {label} "
                              "and its run points AWAY from it: {run_n} consecutive {periods} "
                              "{run_words}, {side}{progress}{figure}"),
    "approaching_line_unplaced": ("the reading has not crossed the line the desk convention calls "
                                  "{label} and this page cannot place its run against that line: "
                                  "{run_n} consecutive {periods} {run_words}, {side}{progress}"
                                  "{figure}"),
    "convergence_amplified": ("this reading is one of {n_matched} of the {n_declared} drivers the "
                              "pattern {pattern} declares that are moving furthest from their own "
                              "records here, and that pattern's own threshold is {threshold}{alone}"
                              "{amplifier}"),
    "upstream_convergence": ("{n_paths} declared upstream paths run through this reading onto this "
                             "price, the deepest {depth} hops up ({causes}), so one cause reaches the "
                             "price by more than one route"),
    # THE SPLIT HAS THREE WORDS BECAUSE THE GRAPH DECLARES THREE (review round 3, MAJOR 2). A two-way
    # split had to put every `0` edge -- "with no committed direction" in `rows.SIGN_WORDS`, and the
    # word the block's own SB-F edge line prints for it -- on one side or the other, and it put 88 of
    # them on the SAME side across 11 drawn rows. The third count is the estate's own third word, and
    # with it the sentence's arithmetic closes on the page: same + opposite + undirected == n_far.
    "spillover_reach": ("this same reading is declared on {n_far} other markets -- {n_same} in the "
                        "same direction, {n_opposite} in the opposite and {n_undirected} with no "
                        "committed direction -- so a move here is a move a desk has to price on "
                        "markets this page is not about{nearest}"),
    # AND WHERE THIS ROW'S OWN EDGE CARRIES NO DIRECTION, THERE IS NOTHING TO COMPARE THE FAR ONES
    # WITH. 11 of the 430 drawn rows are in that position on the banked population (every one of them
    # China state reserves, whose own declared edge is `0`), and a "same direction" count against an
    # uncommitted near edge is not a weaker claim -- it is a claim about a comparison that was never
    # made. The reach is still the fact, and the reach is what the sentence keeps.
    "spillover_reach_unplaced": ("this same reading is declared on {n_far} other markets, {n_directed} "
                                 "of them with a committed direction of their own and {n_undirected} "
                                 "without, and this page cannot place any of them with or against "
                                 "this reading because the edge declared here carries no committed "
                                 "direction either -- so a move here is a move a desk has to price on "
                                 "markets this page is not about{nearest}"),
    "recurrence": ("the record has been in a state like this one before: {n_like} like {states} in "
                   "{n_obs} observations of this series, the nearest dated {date}, so the base rate "
                   "is the record's and not a guess"),
}

#: The sub-clauses the bodies interpolate. They are templates for the SAME two reasons.
NONOBVIOUS_CLAUSES: dict = {
    "figure": "; the figure is {what}",
    "figure_and": ", and the figure is {what}",
    # THE FOUR TAIL-LINE CLAUSES (review round 2, MAJOR 1). Exactly one of them ends every
    # ``tail_reading`` sentence, chosen by :func:`_declared_line` from the row's own ref against
    # base-and-overlay. The fourth exists because a declared line can be UNPLACEABLE on this page -- an
    # ``abs_bands`` line needs the raw level and a ``z_bands`` line needs the z, and a board that holds
    # neither knows a line is declared and cannot say which side of it the reading sits on. Saying so is
    # the honest third state; asserting either of the other two would be the falsehood this fixes.
    "tail_no_line": ("; no desk line is declared for this series at all, so the record's own tail is "
                     "the whole fact"),
    "tail_past_line": ("; it is past the line the desk convention calls {label} as well, so the tail "
                       "and that line say the same thing here"),
    # THE LINE'S OWN BOOK IS NAMED WHEN IT IS THIS LIST'S (review round 3, minor). The clause above is
    # true of a SERVED line -- the one SB-1 itself prints -- and MEASURED on the 108-seat d2 replay it
    # was carried by 180 of the 196 past-the-line tail sentences on rows whose line comes from
    # `watch_overlay`, a watch-only curation no other line on the page reads. Every overlay entry is
    # `percentile_bands [10, 90]` and `TAIL_DECILE` is 10.0, so an overlay ref that cleared `record_tail`
    # has crossed the overlay's own band BY CONSTRUCTION: the reader was being shown a corroborating
    # "desk convention" that was this producer's own book and that says, by arithmetic, exactly what the
    # tail already said. Correcting the sentence is the fix -- the fact stays, its SOURCE is named, and
    # the tautology is disclosed in the clause rather than left for a reader to discover.
    "tail_past_overlay_line": ("; it is past the {label} band this list's own watch book sets for the "
                               "series -- a book no other line here reads, whose band is drawn at the "
                               "same decile this tail is measured by, so this clause and the tail are "
                               "one measurement said twice"),
    "tail_line_uncrossed": ("; a desk line is declared for this series and this reading has not "
                            "crossed it, so the record's own tail is the fact here"),
    "tail_line_unplaced": ("; a desk line is declared for this series and this page cannot place this "
                           "reading against it, so the record's own tail is the fact here"),
    # A THRESHOLD OF ONE IS NOT A CONVERGENCE, AND THE SENTENCE NOW SAYS SO (review round 3, minor).
    # Nine of the 339 declared patterns these boards carry declare `threshold: 1`, where ONE driver
    # satisfies the floor and lifts `T_AMPLIFIER` to its `met` level: MEASURED on the 108-seat replay, 6
    # such rows are drawn and 3 of them sit in a core. The pattern is real and declared and the row
    # keeps it -- a strike here would delete a fact the graph publishes -- but "one of one of the three
    # drivers ... and that pattern's own threshold is one" reads as convergence to anyone who does not
    # stop to do the arithmetic, so the row says plainly what a threshold of one means.
    "threshold_one": (", which a single reading satisfies on its own, so this is a declared pattern "
                      "and not a set of drivers moving with it"),
    # THE ADMISSION FACT, on the kinds whose OWN claim is not a floor clause (review round 2, minor a).
    "admitted": ", and what admits it here is that {fact}",
    "progress": ", about {percent} percent of the way there from zero",
    "amplifier": (", and an interaction among those drivers is declared that {effect} the effect"),
    "nearest": (", and the nearest of them is {market}, where it is declared {sign} with {band} at "
                "{confidence} confidence"),
    # IT NAMES THE ISO TAIL AS A SPAN (review round 2, minor e). The first wording read "opens ahead
    # and closes on these dates -- 2027-02-28 to 2027-08-31", which puts a plural "these dates" against
    # a pair that is one window's two ends; the tail is a SPAN and the sentence now says which end is
    # which.
    "window": (" The declared lag window, counted from that reading's own date, {opened}; the span "
               "this line ends on is {closes}"),
    "falsifier": "{body}; this reads wrong if {falsifier}.",
}

#: The FIVE admission-floor clauses (ANY-OF). A candidate that satisfies none is not nominated.
#:
#: Each is a property of the candidate's BACKING ROW or of the fact the candidate states, never of the
#: kind: the floor is what makes a nomination non-obvious, and a kind cannot assert that about itself.
FLOOR_CLAUSES: tuple = (
    "past_a_declared_line",     # past a declared line AND the run is still going deeper
    "record_tail",              # a top- or bottom-decile reading on the row's own record
    "pattern_member",           # a member of a declared pattern sitting at or past its own threshold
    "two_upstream_paths",       # a node where two or more declared upstream paths meet
    "base_rated_episode",       # an analog episode carrying a stated base rate
)

#: EACH FLOOR CLAUSE IN THE READER'S OWN WORDS (review round 2, minor a). The floor is a property of the
#: BACKING ROW and not of the claim, so a kind whose sentence does not itself state a floor clause was
#: admitted by a fact the reader never met: MEASURED on the armed fixtures, 27 of 44 ceiling rows and 24
#: of 43 tail rows narrated a claim satisfying none of :data:`FLOOR_CLAUSES`. Two kinds are in that
#: position by construction -- ``approaching_line`` claims a line NOT crossed and ``spillover_reach``
#: claims reach -- and they now carry the fact that admitted them. Desk register, like every other
#: sentence here, and part of :data:`_GRAMMAR` for the same reason the bodies are.
FLOOR_WORDS: dict = {
    "past_a_declared_line": ("this reading is already past a declared desk line with its run still "
                             "going deeper"),
    "record_tail": "this reading sits in a decile at the edge of its own record",
    "pattern_member": "this reading is one of the drivers a declared pattern at its own threshold names",
    "two_upstream_paths": "more than one declared upstream path meets here",
    "base_rated_episode": "the record carries like states here with a stated base rate",
}

#: THE FLOOR CLAUSE EACH KIND'S OWN SENTENCE ALREADY STATES. A kind absent from this map -- or one whose
#: stated clause is not in the row's floor -- carries :data:`NONOBVIOUS_CLAUSES`' ``admitted`` clause
#: instead, so no nomination is ever admitted by a fact its own sentence withholds.
FLOOR_STATED_BY_KIND: dict = {
    "past_the_line": "past_a_declared_line",
    "tail_reading": "record_tail",
    "convergence_amplified": "pattern_member",
    "upstream_convergence": "two_upstream_paths",
    "recurrence": "base_rated_episode",
}

#: ``T_AMPLIFIER``'s VALUE DOMAIN -- EXACTLY THE THREE LEVELS THE 09-11 RULING NAMES, and the fourth
#: value's removal is review round 2's MAJOR 3. :func:`_pattern_facts` returned 3 for a row in NO
#: pattern and :func:`rank_key` sorts the LEADING term ascending, so membership of an UNMET pattern
#: outranked every other term -- past-the-line, the tail, the run, path depth. MEASURED
#: (``scratchpad/s7b_verify/vprobe.py``): folding 3 onto 2 changes the top five on 2 of the 4 deep
#: replay boards; on ICE cocoa the only past-the-line item (IOD positive, past the desk line, run
#: intact, window open) moves from third to first instead of sitting behind a median-reading
#: (``T_TAIL`` 0.107) spillover row, and on CBOT corn the fold admits the cattle herd (tail 0.984,
#: run 5). THE ORCHESTRATOR'S DECISION, recorded here for the owner: an UNMET pattern is not evidence
#: of convexity, so the no-pattern value folds onto the short-pattern value and the term LIFTS only met
#: patterns -- with a declared amplifier line first, met second -- and is NEUTRAL otherwise.
#: ``lint._check_nonobvious_watch`` grades this domain, so a fourth value cannot come back unnamed.
AMPLIFIER_LEVELS: dict = {"met_with_amplifier": 0, "met": 1, "neutral": 2}

#: The SEVEN rank terms the 09-11 ruling names, IN ITS ORDER. Declared as data so the census, the deck
#: and the report read ONE list rather than three copies of it. ``T_NOVELTY`` is not among them: it is
#: the ruling's measurement clause, sorts after ``T_WINDOW``, and is named by :data:`RANK_TIEBREAK`.
#:
#: IT IS THE RULING'S LIST OF NAMES AND NOT AN INDEX INTO THE STAMPED RECORD (review round 3, minor).
#: The docstring above it counted eight and the tuple has always held seven; and ``T_PATHS`` is the
#: ruling's one word for the pair :func:`rank_terms` stamps as ``T_PATHS_DEPTH`` and ``T_PATHS_N``
#: (depth before breadth, R11), so a reader who used this tuple to index ``cand['terms']`` would meet
#: a KeyError on that one name. Nothing in the estate does -- ``lint._check_nonobvious_watch`` and the
#: deck grade the ORDER -- and the stamped keys are :data:`RANK_TERM_KEYS`, declared beside it.
RANK_TERMS: tuple = ("T_AMPLIFIER", "T_NONLINEAR", "T_TAIL", "T_RUN", "T_PATHS",
                     "T_BREADTH", "T_WINDOW")

#: The term that breaks a tie the ruling's seven cannot, and the two strings that make the sort
#: reproducible in a fresh process.
RANK_TIEBREAK: tuple = ("T_NOVELTY", "driver_id", "kind")

#: THE KEYS :func:`rank_terms` ACTUALLY STAMPS, which is the set a reader may index ``cand['terms']``
#: by -- ``T_PATHS`` is NOT one of them (it is the ruling's word for the two path halves) and
#: ``T_NOVELTY`` IS. Declared because :data:`RANK_TERMS` is the RULING's list and the two are not the
#: same list, which review round 3 caught as a KeyError waiting for its first consumer; graded against
#: the stamped record by ``lint._check_nonobvious_watch``.
RANK_TERM_KEYS: tuple = ("T_NOVELTY", "T_AMPLIFIER", "T_NONLINEAR", "T_TAIL", "T_RUN",
                         "T_PATHS_DEPTH", "T_PATHS_N", "T_BREADTH", "T_WINDOW")

#: The decile cut ``T_TAIL``'s floor clause uses. It is the SAME number the conventions file's own
#: "levels and spreads with no desk band" family uses for its ``[10, 90]`` percentile bands -- one
#: vocabulary, said once.
TAIL_DECILE: float = 10.0

#: The date a candidate with no placeable window sorts under. It sorts LAST inside ``T_WINDOW``, which
#: is where an unplaceable window belongs: the term asks "how soon", and "no date" is not soon.
_NO_WINDOW: str = "9999-99-99"

#: Words, ISO dates and bare figures -- the three things a rendered sentence can carry. ``T_NOVELTY``
#: reads this and nothing else, so "its figures" in the ruling's sentence is literal: a level, a
#: percentile and a date are tokens here exactly as a name is.
_TOKEN_RX = re.compile(r"[A-Za-z][A-Za-z'-]*|\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?")
_SLOT_RX = re.compile(r"\{[a-z_]+\}")


def _content_tokens(text) -> frozenset:
    """The lower-cased token set of a rendered string. Punctuation and case are not content."""
    return frozenset(t.lower() for t in _TOKEN_RX.findall(str(text or "")))


#: ORDINARY ENGLISH, said once. It is small and closed on purpose: the words that actually decide
#: novelty are names, markets, patterns, causes, dates and figures, and a long stopword list would
#: start deciding which of THOSE count.
_STOPWORDS: frozenset = frozenset(
    "a an and are as at be been by for from has have here if in into is it its of on one or so that "
    "the their them there this to under up was were what when where which who with".split())

#: EVERY FIXED WORD THE SEVEN SENTENCES CARRY, derived from the templates above at import.
#:
#: THIS IS THE WHOLE ANSWER TO "NEVER ASSERTED PER KIND". A novelty computed on the raw rendered
#: sentence would hand ``tail_reading`` a free point for "decile" and ``upstream_convergence`` two for
#: "hops" and "route" -- words no SB-1 line can carry, on every board, for every row -- which is a
#: per-kind constant wearing a sentence's clothes. Subtracting the templates' own words leaves exactly
#: the words the BOARD put there, which is what the ruling asks the term to see. Derived and never
#: hand-kept: a sentence edited above changes this set in the same commit, by construction.
#: The fixed phrases the two word-producers below emit. They are fixed the same way a template is --
#: ``_side_word`` says "on the high side" or "on the low side" and ``_metric_words`` says "in the unit
#: its own line prints" -- so their scaffolding words belong here for the same reason. "high" and "low"
#: stay OUT: which tail a reading sits in is a fact the board supplied, not scaffolding.
_FIXED_PHRASES: tuple = ("on the side", "a side this reading does not show",
                         "in the unit its own line prints")

_GRAMMAR: frozenset = _content_tokens(" ".join(
    [_SLOT_RX.sub(" ", s) for s in
     (list(NONOBVIOUS_BODIES.values()) + list(NONOBVIOUS_CLAUSES.values())
      + list(NONOBVIOUS_KIND_WORDS.values()) + list(NONOBVIOUS_MECHANISMS.values())
      + list(NONOBVIOUS_FALSIFIERS.values())
      # THE FLOOR WORDS ARE TEMPLATE WORDS TOO (minor a). They are chosen by the ROW's floor and not by
      # its kind, but each is a fixed sentence, so leaving them out would hand every `spillover_reach`
      # and `approaching_line` candidate the same free tokens -- the per-kind constant `novelty` is
      # written to refuse.
      + list(FLOOR_WORDS.values()))] + list(_FIXED_PHRASES))) | _STOPWORDS

#: The SELECTION LICENCE, handed to the writer through the flag-scoped mandate literal. It lives here
#: because the watch lane owns the rule and ``state/narration.py`` owns the mandate: the register lane
#: lands this constant verbatim and edits nothing else of this lane's (see
#: ``scratchpad/s7b/SEAM_PATCH_W.txt``). ASCII only, register-clean, and graded by
#: ``narration.check_literals`` beside every other literal that reaches a prompt.
#: IT IS ALSO DESK-REGISTER CLEAN, and that is not decoration: this string is handed to the WRITER. A
#: licence that said "the board nominated ... the row that backs it" would teach two of the exact
#: instrument words the sibling lane's mandate bans and its rewrite call pays to remove -- the prompt
#: teaching one thing and the mandate the opposite. Graded by the deck under
#: ``register.desk_register_hits`` beside every rendered nomination.
#:
#: **IT NOW NAMES THE NUMBER, AND THE BLOCK NAMES IT AGAIN** (review round 2, MAJOR 2). The tier ceiling
#: is sized by :func:`nonobvious_k` and stamped by the draw as ``slot``, and NEITHER reached the writer:
#: ``render.sb_watch`` emitted the same "- WATCH ..." line for a ceiling row and a nomination row, and
#: this clause named no count at all while illustrating with "four ... beat five" -- which at Scan,
#: whose ceiling is THREE, suggests four or five. MEASURED (``scratchpad/s7b_verify/ARMED.txt``): quick
#: rendered 6 indistinguishable nomination lines against HEAD's 3, deep 10, max 12-14. The 2N
#: nomination STAYS (it is the owner's) and N now binds: every rendered nomination says whether it is a
#: core item or an alternate AND how many of each there are, and this clause tells the writer to keep at
#: most the core.
#:
#: **AND THE NUMBER IT NAMES IS A BOUND, NOT A COUNT** (review round 3, minor). The first cut said "The
#: core is three items on a Scan, five on an Analysis and seven on a Cascade" flatly, which is untrue of
#: every block whose ceiling under-fills: MEASURED on the 108-seat d2 replay, 36 seats drew a core
#: SHORTER than the tier's ceiling (down to two of seven on barley at Cascade) and each of them printed
#: its own smaller number on every core mark while this sentence named the tier's. "KEEP AT MOST"
#: already carried the operative bound, so the repair is the sentence's own grammar plus a pointer to
#: the number that is actually true of the list in hand -- the block's own marks.
#:
#: THE TIER'S OWN NUMBER IS AVAILABLE TOO, through :func:`selection_clause`, and the mode-free constant
#: is what ``state/narration.py`` lands today: ``narration.watch_selection_mandate()`` takes no
#: argument, and threading the mode through ``answer._system`` is an edit to the REGISTER lane's two
#: files. The clause therefore names all three ceilings AND the rule the block itself carries, so it is
#: correct without the tier and exact with it (``scratchpad/s7b/SEAM_PATCH_W2.txt``).
WATCH_SELECTION_CLAUSE: str = (
    "The WATCH items are CANDIDATES nominated for you, not a list to reproduce. Each one carries the "
    "mechanism it rests on, the dated reading that backs it, the citation of the line where that "
    "figure is printed, and the reading that would show it wrong. KEEP AT MOST THE ITEMS MARKED A CORE "
    "ITEM: each of those says its own place and how many core items there are, and an item marked an "
    "alternate sits beyond that number -- take one only in place of a core item you drop. The core is "
    "at most three items on a Scan, five on an Analysis and seven on a Cascade, and each core item's "
    "own mark says how many this list actually drew. Keep what a desk would act on, "
    "drop what it would not, merge two items that are one idea, and order them as you judge. You may "
    "add ONE item of your own only if you name its mechanism and the dated reading it rests on, and it "
    "counts against that number. Fewer backed items and an honest line saying nothing else cleared the "
    "bar beat a full list where two of them are noise."
)


def nonobvious_k(mode: str, cap: Optional[int] = None) -> int:
    """The tier's non-obvious CEILING. An explicit ``cap`` wins, as it does for the HEAD producer."""
    if cap is not None:
        return max(0, int(cap))
    from leviathan.graphrag import reasoning_modes as rm
    return int(WATCH_NONOBVIOUS_K.get(rm.base_mode(mode), 5))


def selection_clause(mode: str, cap: Optional[int] = None) -> str:
    """:data:`WATCH_SELECTION_CLAUSE` with the TIER'S OWN ceiling in place of the three-tier sentence.

    OFFERED, NOT LANDED. ``narration.watch_selection_mandate()`` is the register lane's file and takes
    no mode; this is the one-line swap that makes the mandate exact per tier, and the seam patch that
    lands it is ``scratchpad/s7b/SEAM_PATCH_W2.txt``. Both forms carry the same rule and the same bound
    -- the block's own core marks -- so the mandate is never wrong, only less specific, until it lands.
    """
    n = nonobvious_k(mode, cap)
    return WATCH_SELECTION_CLAUSE.replace(
        "The core is at most three items on a Scan, five on an Analysis and seven on a Cascade, and "
        "each core item's own mark says how many this list actually drew.",
        f"The core of this list is at most {R.words_for_int(n)} items, and each core item's own mark "
        f"says how many this list actually drew.")


# ---------------------------------------------------------------------------------------------------
# the readings a candidate is built from -- every one already on the board, ZERO reads
# ---------------------------------------------------------------------------------------------------
def _num(measure) -> Optional[float]:
    """A stats.py measure that MEASURED something, as a float. ``None`` on a decline, a null or a hole.

    EVERY TERM GOES THROUGH IT (threat O-6). A ``None`` inside a sort tuple is a ``TypeError`` in the
    middle of a render, and this producer meets declined dicts on every field it reads."""
    if not measure or not isinstance(measure, dict) or measure.get("declined"):
        return None
    return TR.num_or_none(measure.get("value"))


def _run_of(st) -> tuple:
    """``(length, direction)`` off a state row's run, or ``(0, "")``."""
    r = getattr(st, "run", None) if st is not None else None
    if not r or r.get("declined"):
        return 0, ""
    try:
        return int(r.get("length") or 0), str(r.get("direction") or "")
    except (TypeError, ValueError):
        return 0, str(r.get("direction") or "")


def _band_side(kind: str, band, bands=()) -> str:
    """WHICH WAY A READING HAS TO MOVE TO GO FURTHER ALONG THIS DECLARED LINE'S OWN SIDE.

    ``"up"``, ``"down"``, or ``""`` where the line itself does not carry a side -- which is the
    MAGNITUDE kinds, whose band is a distance from zero and whose side is the READING's own sign
    (:func:`_run_with_the_line` reads it there).

    IT IS THE SAME RULE :func:`convention_distance` ALREADY USES TO PICK THE LINE, said once: a
    percentile band under 50 is a LOW line and a reading goes further into it by FALLING; a band at or
    over 50 is a high line and a reading goes further into it by RISING. ``pace_vs_prior_year`` is the
    same statement about its own midpoint of zero, and its two declared bands say which is which
    (``_crossed`` reads ``min``/``max`` for exactly this reason), so the sign fallback is only ever
    reached by a one-sided pace curation."""
    if band is None:
        return ""
    try:
        b = float(band)
    except (TypeError, ValueError):
        return ""
    if kind == "percentile_bands":
        return "down" if b < 50.0 else "up"
    if kind == "pace_vs_prior_year":
        bs = []
        for x in (bands or ()):
            try:
                bs.append(float(x))
            except (TypeError, ValueError):
                continue
        if len(bs) > 1 and b <= min(bs):
            return "down"
        if len(bs) > 1 and b >= max(bs):
            return "up"
        return "down" if b < 0.0 else "up"
    return ""


def _run_with_the_line(kind: str, band, reading, direction: str, bands=()) -> Optional[bool]:
    """DOES THIS RUN MOVE THE READING FURTHER ALONG THE SIDE OF THE BAND THE SENTENCE NAMES?

    ``True`` / ``False`` / ``None``, and the third state is the point of the function: a page that
    cannot place a run against a line may not assert either direction (review round 3, MAJOR 1).

    TWO SENTENCES REST ON IT AND BOTH WERE ASSERTING THE RULING'S OWN CONVEXITY FACT WITHOUT TESTING
    IT. ``approaching_line`` printed "its run POINTS AT IT" off the run's LENGTH alone, and
    :func:`_floor_of`'s first clause derived "the run is still going deeper" from the sign of ``z``,
    which is not the band's side for a ``percentile_bands`` row at all. MEASURED on the 144 banked
    census seats, flag on, through the shipped producer and ``render.render_board``: 10 of 42 drawn
    ``approaching_line`` rows had a run pointing AWAY from the line they named and 10 of 10 sat in a
    CORE slot; 8 of the 34 decidable drawn ``past_the_line`` rows had a run pointing BACK at the line
    they had crossed, 7 of them CORE.

    THE CORRECTION IS THE BAND'S OWN SIDE AND NOTHING NEW IS READ: :func:`_band_side` for the two
    signed-axis kinds, the SIGNED reading for the two magnitude kinds (whose band is a distance from
    zero, so a negative reading goes further past it by FALLING). A reading of exactly zero moves
    further from zero whichever way it runs, which is ``True`` and not a decline."""
    if direction not in ("up", "down"):
        return None
    side = _band_side(kind, band, bands)
    if not side:
        if kind not in ("abs_bands", "z_bands") or reading is None:
            return None
        try:
            r = float(reading)
        except (TypeError, ValueError):
            return None
        if r == 0.0:
            return True
        side = "up" if r > 0 else "down"
    return direction == side


def _tail_fraction(st) -> float:
    """BAND-FREE ``|pct - 50| / 50`` in ``[0, 1]``, and 0.0 where there is no percentile.

    IT READS ``percentile`` AND NOTHING ELSE. The whole reason this term exists is that fifteen silver
    refs -- ``export``, ``import``, ``area``, ``consumption``, ``production``, ``beginning_stock_region``,
    ``stock``, ``psd_feed_use``, ``sunflower_oil_supply``, ``psd_fsi_use``, ``herd_size_cattle``,
    ``production_region``, ``psd_food_use``, ``psd_meal_feed_waste_use``, ``psd_crush`` -- carry 463 of
    the banked order rows and have no ``state_conventions`` entry, so a term keyed on a declared band
    cannot see the balance sheet or the herd at all. A convention-less row still ranks."""
    p = _num(getattr(st, "percentile", None) if st is not None else None)
    if p is None:
        return 0.0
    return min(1.0, abs(float(p) - 50.0) / 50.0)


def _side_word(st, *, kind: str = "") -> str:
    """WHICH TAIL the reading sits in, in the reader's words (R15).

    ``_crossed`` folds ``abs_bands`` and ``z_bands`` to ``abs(reading)`` and ``convention_distance``
    returns ``shown = abs(reading)``, so "zero point nine sigma under the severe line" does not say
    which side of zero it is on. The side is taken from the SIGNED reading -- the z where there is one,
    else the percentile against its own midpoint -- and a reading this board cannot sign says so."""
    z = _num(getattr(st, "z", None) if st is not None else None)
    if z is not None and kind in ("z_bands", "abs_bands", ""):
        if z > 0:
            return "on the high side"
        if z < 0:
            return "on the low side"
    p = _num(getattr(st, "percentile", None) if st is not None else None)
    if p is not None:
        if p >= 50.0:
            return "on the high side"
        return "on the low side"
    if z is not None:
        return "on the high side" if z >= 0 else "on the low side"
    return "on a side this reading does not show"


def _metric_words(st) -> str:
    """WHAT THE NUMBER IS (R13): the reading's own metric label and unit, in reader words.

    The prototype's ``[G_supply_response] Brazil export tax -> ICE raw sugar`` carried
    ``level=118000000 MMT`` -- a PSD export VOLUME -- under a node named for a tax. A sentence naming
    the node and not the metric tells a reader the number is a tax rate. ``narrate_unit`` is the
    reader's unit where the card declares one; the raw ``unit`` is the fallback and the metric alone is
    the honest answer where neither is served.

    **A UNIT CARRYING A BARE DIGIT IS NOT PRINTED, AND IT IS NOT DROPPED EITHER.** This sentence rides
    SB-W, a letters-only class, and the estate's units spell their SCALE as a numeral -- ``1000 MT``,
    ``1000 HA``. MEASURED at this landing on the three acceptance fixtures: "the figure is weekly
    exports in 1000 MT" put a charged digit on four SB-W rows across all three blocks. The remedy is a
    CORRECTION and never a deletion -- the metric is still named, and the reader is pointed at the row's
    own SB-1 line, which is a FIGURE class, carries that exact unit beside the level, and is cited on
    this very row by its ``[N]``.

    **AN UNSERVED METRIC RETURNS THE EMPTY STRING AND THE CLAUSE IS NOT PRINTED AT ALL**, which is the
    correction the first cut needed. It fell back to ``R.table_words(st.table)`` -- the MEDALLION CARD
    name -- and the four-board replay rendered "the figure is psd", "the figure is psd attributes",
    "the figure is production livestock" and "the figure is gold weather z", a storage-tier name on a
    cocoa page. A card name is not what the number is, so answering R13 with one answers it falsely.
    Saying nothing here is not a deletion: the sentence keeps every other clause, the row's own SB-1
    line carries the level with its unit, and this row cites it by ``[N]``."""
    if st is None:
        return ""
    # THE METRIC CARRIES ITS SCALE TOO, and the same correction applies for the same reason: the
    # estate's metric ids spell a scale as a leading numeral (`weekly_exports_1000mt`,
    # `area_harvested_1000ha`). A token whose FIRST character is a digit is a scale token and the
    # scale is already on the row's own SB-1 line; a digit GLUED to letters (`section301`, `zscore_5yr`)
    # is part of a name, is exempt from `verify._claim_number_spans` by rule (c), and is kept.
    metric = R.humanise(str(getattr(st, "metric", "") or ""))
    metric = " ".join(t for t in metric.split() if not t[:1].isdigit()).strip()
    if not metric:
        return ""
    unit = str(getattr(st, "narrate_unit", "") or getattr(st, "unit", "") or "").strip()
    if not unit:
        return metric
    if any(ch.isdigit() for ch in unit):
        return f"{metric}, in the unit its own line prints"
    return f"{metric} in {unit}"


def _dedupe_key(row) -> tuple:
    """``(series key label, declared offset)`` -- R10's key, and the reason it is a PAIR.

    El Nino is declared on 34 boards; 2 of them read ``oni_lag_climate``, which ``same_series_as`` folds
    onto ``oni_climate``'s label with ``offset_months = 6``. On the LABEL alone those two boards are the
    same reading as the other 32, which they are not -- ``render.offset_words`` exists precisely because
    a declared offset is a different reading. On the DRIVER ID alone El Nino and La Nina are two
    candidates about one ONI print, which is the join the block itself corrects one class over.

    A row with no series key groups under its own driver id, alone: a text-only row is not the same
    reading as anything."""
    st = getattr(row, "state", None)
    if st is None or not getattr(st, "key", None):
        return ("#" + str(getattr(row, "driver_id", "")), 0)
    try:
        label = st.key.label()
    except Exception:                                   # noqa: BLE001 -- an unlabelled key groups alone
        return ("#" + str(getattr(row, "driver_id", "")), 0)
    try:
        off = int(getattr(st, "offset_months", 0) or 0)
    except (TypeError, ValueError):
        off = 0
    return (str(label or ("#" + str(row.driver_id))), off)


def _reading_window(bd, row) -> dict:
    """The declared lag window counted FROM THE READING'S OWN DATE (R6), never from the run start.

    ``bd.windows[key]['reading']`` is the field ``walk._stage2`` banks beside ``near``; ``near`` is
    SB-J's anchor and its own docstring declares the run start as its design, so this reader never
    touches it. ``fallback`` names WHICH anchor was used, and a non-zero count of ``run_start`` on an
    armed turn is the tell that a rebase took ``walk.py``'s "theirs" and silently reverted R6."""
    src = (bd.windows.get(row.key) or {}) if getattr(bd, "windows", None) else {}
    anchor = src.get("reading")
    fallback = ""
    if not anchor:
        st = getattr(row, "state", None)
        anchor = getattr(st, "level_date", None) if st is not None else None
        fallback = "level_date"
    if not anchor:
        anchor = src.get("near")
        fallback = "run_start"
    if anchor is not None and len(str(anchor)[:10]) < 7:
        # ``walk._add_months`` slices ``iso[5:7]``; a bare marketing-year label makes that ``int("")``.
        # The guard is the HEAD producer's own, restated -- see kind 3 above for the finding it carries.
        anchor = None
    if not anchor:
        return {"opens": None, "closes": None, "declined": "no_open_window", "anchor": None,
                "fallback": fallback}
    from leviathan.graphrag.state.walk import projection_window
    w = dict(projection_window(str(anchor), row.lag_band))
    w["anchor"] = str(anchor)
    w["fallback"] = fallback
    return w


def _window_open(w: dict, asof: str) -> bool:
    """Is this window still open at the as-of? A CLOSED window is never nominated (R6's assertion).

    A window that has NOT YET OPENED is open in this sense and is admitted: a declared lag band six
    months out from a CURRENT reading places its window ahead, which is a true forward item, and
    :func:`_window_clause` says in words which of the two the row is."""
    if not w or w.get("declined") or not w.get("opens"):
        return False
    closes = w.get("closes")
    return (closes is None) or (str(closes) >= str(asof)[:10])


# ---------------------------------------------------------------------------------------------------
# THE BASE RATE ON A RECURRENCE -- "n like states in m observations"
# ---------------------------------------------------------------------------------------------------
#: The closed decline words :func:`like_state_base_rate` can return. A base rate that cannot be stated
#: is a recurrence item that does not clear the admission floor -- STATED, never silently softened
#: into a recurrence claim with no denominator.
BASE_RATE_DECLINES: tuple = ("no_candidate_count", "no_observation_count",
                             "candidates_exceed_observations")


def like_state_base_rate(stanza: dict, row) -> dict:
    """``{'n', 'm', 'declined'}`` -- how many like states the selector found, over how many observations
    the seed's own record carries. ZERO READS, ZERO NEW LOOPS, and that is the whole point.

    **IT LIVES IN THIS FILE AND NOT IN ``state/analogs.py``**, and that placement is a review finding
    rather than a preference. It is the WATCH lane's producer, read at exactly one call site
    (:func:`nonobvious_candidates`) and tested in this lane's deck; ``analogs.py`` meanwhile carries a
    CO-TENANT lane's in-flight per-metric ``_lag_days_of`` rewrite, which is not this lane's work, is
    not byte-identical to HEAD with every flag off, and owes its own statement. Adding a function there
    would have made ``git add state/analogs.py`` this lane's only way to ship it -- and that command
    ships the co-tenant's change inside this commit. The function moved; ``analogs.py`` is no longer
    one of this lane's files.

    THE CENSUS'S ``candidates_by_sigma_band`` IS **NOT** THE PRODUCER HERE, and the difference is a cost
    the serving path cannot pay. That function (``board_census._analog_census``) re-runs
    ``analogs.likeness`` once per HISTORY DATE per seed per band -- three full passes over a
    324-observation daily tape for every one of ``analog_dims`` seeds, inside a bare
    ``except Exception``. It is a CENSUS fact ("banked 144/144"), not a live one, and wiring it into an
    answer would put an O(history x seeds x bands) loop in the answer path to print two integers.

    BOTH INTEGERS ARE ALREADY IN MEMORY. ``analogs.select_analogs`` returns ``n_candidates`` -- the
    count of crossings that passed the likeness gate AND whose outcome window has already closed AND
    that were observable on every declared dimension -- and ``analogs.analog_rows`` copies it onto every
    stanza, fired or declined. The denominator is the seed row's own ``coverage['n_obs']``, which
    ``feeders.series_state`` stamped when it read the series. So the base rate is two field reads and a
    bounds check, and the recurrence item can state its denominator without the board paying for it.

    WHAT THE TWO NUMBERS MEAN, said exactly, because a base rate whose population is vague is worse
    than none: ``n`` is like states the selector ADMITTED -- past crossings of this series' own
    declared line (or of its own run rule) whose consequence window has closed and whose every analog
    dimension was observable on that date; ``m`` is the observations this series' record carries over
    the window the row was read on. "Seven like states in one hundred thirty-one observations" is
    therefore a statement about this SERIES' record, never about the market.

    A DECLINE IS NAMED. ``candidates_exceed_observations`` cannot happen on a stanza and its own seed
    row and is checked anyway: it is the tell that a caller paired a stanza with the WRONG row, which
    would print a base rate over a denominator from another series -- a silently wrong figure, and the
    only failure of this producer that a reader could not see."""
    n = None
    if isinstance(stanza, dict) and stanza.get("n_candidates") is not None:
        try:
            n = int(stanza["n_candidates"])
        except (TypeError, ValueError):
            n = None
    if n is None or n < 0:
        return {"n": None, "m": None, "declined": "no_candidate_count"}
    st = getattr(row, "state", None)
    m = None
    if st is not None:
        try:
            m = int((st.coverage or {}).get("n_obs") or 0)
        except (TypeError, ValueError):
            m = None
    if not m or m <= 0:
        return {"n": n, "m": None, "declined": "no_observation_count"}
    if n > m:
        return {"n": n, "m": m, "declined": "candidates_exceed_observations"}
    return {"n": n, "m": m, "declined": None}


# ---------------------------------------------------------------------------------------------------
# THE CANDIDATE BUILDERS -- one per non-obvious kind, all over the board's OWN rows and traces
# ---------------------------------------------------------------------------------------------------
def _window_clause(win: dict, dates: str, asof: str = "") -> str:
    """THE WINDOW SENTENCE, and it is the LAST clause of the body for a grammatical reason.

    ``render.sb_watch`` appends " -- {dates}", so the sentence that introduces the dates has to be the
    one that ends the body. The first cut put it mid-body and every armed row read "...the window the
    graph declares from that reading's own date is; this reads wrong if ... -- 2026-09-04 to
    2026-12-04". The words are ``watch_rows``' own kind-3 literals, restated from the reading's anchor
    instead of the run's -- ONE vocabulary for the one fact both rows state.

    **IT SAYS WHETHER THE WINDOW HAS OPENED YET**, and that is the correction review found: the b40
    fixture's sixth ceiling row printed "2027-02-28 to 2027-08-31" at a 2026-09-07 as-of under a
    sentence that read "opens and closes on these dates", which a reader takes as a window running now.
    A lag band declared six months out from a current reading LEGITIMATELY opens in the future -- so
    the row is not refused (a refusal here would delete a true forward item, and ``T_WINDOW`` is last
    by the ruling precisely so a calendar fact never outranks a state); the sentence states which of
    the two it is, and the reader ranks it.

    **AND IT NAMES THE ISO TAIL AS A SPAN** (review round 2, minor e). "opens ahead and closes on these
    dates -- 2027-02-28 to 2027-08-31" answers the OPENED question and then calls one window's two ends
    "these dates", which reads as a list of two separate things; the clause now says the tail is that
    window's own open and close, or its open date alone where the band declares no close.

    **IT NEEDS A PLACED WINDOW AND NOT ONLY A DATE**, and that guard is a defect found at this landing.
    The ``recurrence`` kind's date tail is the LIKE STATE's date -- a past date by construction, since
    a like state's own consequence window has to have closed for it to be a like state at all -- and it
    is built with no window. Keyed on ``dates`` alone this clause then wrote "the declared lag window,
    counted from that reading's own date, opens and does not close -- 2024-12-31" onto two of the
    thirty-two window-bearing rows across the three fixtures, which named a lag window over a date that
    was never one."""
    if not dates or not win.get("opens"):
        return ""
    opened = bool(win.get("opens")) and str(win["opens"])[:10] <= str(asof)[:10] if asof else False
    return NONOBVIOUS_CLAUSES["window"].format(
        opened=("has already opened" if opened else "opens ahead"),
        closes=("its open date alone, because that window does not close"
                if win.get("closes") is None else "that window's own open and close"))


def _cand(kind: str, row, *, what: str, dates: str,
          floor: tuple, far_words: tuple = (), win: Optional[dict] = None, asof: str = "",
          identity: Optional[tuple] = None, variant: str = "",
          extra: Optional[dict] = None) -> dict:
    """ONE candidate, in the SB-W row shape the shipped renderer already takes.

    The dict is a superset of what :func:`watch_rows` emits, so ``render.sb_watch`` renders it with no
    new builder and no new row class -- and the extra fields (``floor``, ``terms``, ``falsifier``,
    ``mechanism``, ``far_words``) ride the board's trace, where the census and the arm read them.

    THE FALSIFIER IS PART OF THE SENTENCE AND NOT A SECOND LINE. A second line per candidate would
    double the section's height on a block whose Scan tier already needed render caps, and a falsifier
    the writer can drop separately from the claim is a falsifier nobody reads.

    THE MECHANISM AND THE FALSIFIER ARE READ FROM THE CLOSED MAPS and are no longer passed in: they are
    properties of the KIND, one place each, so a kind cannot ship two different falsifiers from two
    call sites and :data:`_GRAMMAR` can derive their words with the bodies'.

    **THE SENTENCE CARRIES THE FACT THAT ADMITTED THE ROW** (review round 2, minor a). The admission
    floor is a property of the BACKING ROW, so a kind whose own claim states none of
    :data:`FLOOR_CLAUSES` -- ``approaching_line``, which claims a line NOT crossed, and
    ``spillover_reach``, which claims reach -- was admitted by a fact the reader never met (27 of 44
    ceiling rows, 24 of 43 tail rows on the armed fixtures). The clause is added HERE, once, from
    :data:`FLOOR_STATED_BY_KIND` and the row's own floor tuple, so no builder can forget it and a kind
    that already states its floor never repeats itself.

    **THE VARIANT PICKS THE FOUR READER-FACING STRINGS, THE KIND STAYS THE KIND** (review round 3,
    MAJOR 1). ``variant`` must be a declared key of :data:`NONOBVIOUS_VARIANTS` that belongs to this
    kind -- a builder cannot invent one, and a variant cannot quietly become an eighth kind: the
    trace, the draw's per-kind cap and ``T_NONLINEAR`` all keep reading ``kind``, while the words, the
    mechanism and the falsifier come from the sentence the row actually got."""
    v = variant or kind
    if v != kind and NONOBVIOUS_VARIANTS.get(v) != kind:
        raise KeyError(f"watch: {v!r} is not a declared variant of {kind!r}")
    falsifier = NONOBVIOUS_FALSIFIERS[v]
    floor = tuple(floor)
    stated = FLOOR_STATED_BY_KIND.get(kind)
    admitted = ("" if (stated is not None and stated in floor) or not floor
                else NONOBVIOUS_CLAUSES["admitted"].format(fact=FLOOR_WORDS[floor[0]]))
    return {
        "kind": kind, "kind_words": NONOBVIOUS_KIND_WORDS[v],
        "label": f"{R.humanise(row.driver_id)} on {R.board_label(row.contract)}",
        "what": (NONOBVIOUS_CLAUSES["falsifier"].format(body=what + admitted, falsifier=falsifier)
                 + _window_clause(win or {}, dates, asof)),
        "dates": dates, "declined": None, "row": row.key,
        "nonobvious": True, "mechanism": NONOBVIOUS_MECHANISMS[v], "falsifier": falsifier,
        "variant": v, "floor": floor, "far_words": tuple(far_words),
        "dedupe": identity or _dedupe_key(row), "driver_id": row.driver_id,
        **(extra or {}),
    }


def _floor_of(row, *, pattern_rows=(), path_n: int = 0, base_rate=None, dist=None) -> tuple:
    """WHICH ADMISSION CLAUSES THIS ROW CLEARS (ANY-OF). Empty == not nominated.

    IT IS COMPUTED ON THE ROW AND ITS TRACES, NEVER ON THE KIND (threat O-1/O-4). A kind cannot assert
    that it is non-obvious; the floor is the assertion, and it is made of five facts the board already
    holds. A board that clears none of them prints an honest absence line -- never a padded list, and
    never a silence."""
    out: list = []
    st = getattr(row, "state", None)
    # (1) past a declared line AND the run still going deeper -- the convex state (R5)
    #
    # **"DEEPER" IS A DIRECTION AGAINST THE BAND'S OWN SIDE, NOT THE SIGN OF z** (review round 3,
    # MAJOR 1). This clause read the sign of ``z`` alone, which says nothing about which way a
    # ``percentile_bands`` line was crossed: MEASURED on the 144 banked seats, 8 of the 34 decidable
    # drawn ``past_the_line`` rows carried a run pointing BACK at the line they had crossed -- an ICE
    # arabica stocks-to-use ratio at the 20.1st percentile, past a `tight` line at the 25th and RISING
    # out of it, narrating "its run has not turned" in a core slot. The band's side is already known to
    # this module (:func:`_band_side`, the same rule :func:`convention_distance` picks the line with)
    # and the reading is the row's own, so the clause now tests the thing it claims.
    #
    # WHERE THE SIDE CANNOT BE PLACED THE SHIPPED RULE STANDS, and that is deliberate: an ``abs_bands``
    # row whose raw level this board never banked has no sign to read, and refusing the floor there
    # would drop a true convex row over a missing measure rather than over a fact. 68 of the 102 drawn
    # rows are in that position on the banked population.
    conv = getattr(st, "convention", None) if st is not None else None
    if conv and not conv.get("declined") and conv.get("matched"):
        n_run, direction = _run_of(st)
        kind = str(conv.get("kind") or "")
        reading = conv.get("reading")
        if reading is None:
            reading = _measure_reading(kind, st)
        placed = _run_with_the_line(kind, conv.get("band"), reading, direction)
        if placed is None:
            z = _num(getattr(st, "z", None) if st is not None else None)
            placed = ((direction == "up" and (z is None or z >= 0)) or
                      (direction == "down" and (z is None or z <= 0)))
        if bool(n_run >= 2 and placed):
            out.append("past_a_declared_line")
    # (2) a top- or bottom-decile reading on the row's OWN record -- band-free, so the balance sheet
    #     and the herd can clear the floor at all
    p = _num(getattr(st, "percentile", None) if st is not None else None)
    if p is not None and (p <= TAIL_DECILE or p >= (100.0 - TAIL_DECILE)):
        out.append("record_tail")
    # (3) a member of a declared pattern sitting AT OR PAST its own threshold
    if any(r for r in (pattern_rows or ())
           if row.driver_id in (r.get("matched") or ()) and
           int(r.get("n_matched") or 0) >= int(r.get("threshold") or 10 ** 6)):
        out.append("pattern_member")
    # (4) a node where TWO OR MORE declared upstream paths meet
    if int(path_n or 0) >= 2:
        out.append("two_upstream_paths")
    # (5) an analog episode carrying a STATED base rate -- a recurrence with no denominator is not one
    if base_rate is not None and not base_rate.get("declined"):
        out.append("base_rated_episode")
    return tuple(out)


def _pattern_facts(bd, row, pattern_rows) -> dict:
    """The best declared pattern this row is a member of, and whether it carries an amplifier line.

    **THE VALUE DOMAIN IS :data:`AMPLIFIER_LEVELS` AND IT HAS THREE LEVELS, NOT FOUR** (review round 2,
    MAJOR 3). This returned 3 for a row in NO pattern, which -- on a lexicographic tuple whose LEADING
    term this is, sorted ascending -- meant that being a member of an UNMET pattern outranked being past
    a declared line, sitting in a tail, carrying a run or standing where declared paths meet. An unmet
    pattern is not evidence of convexity: a pattern SHORT of its own threshold and no pattern at all are
    the same statement about asymmetry, and they now tie at ``neutral``. The term lifts a MET pattern
    (with a declared amplifier line first) and is neutral otherwise, which is the 09-11 ruling's own
    sentence with its fourth, unnamed value removed."""
    best = None
    for r in (pattern_rows or ()):
        if r.get("contract") != row.contract or row.driver_id not in (r.get("matched") or ()):
            continue
        at_threshold = int(r.get("n_matched") or 0) >= int(r.get("threshold") or 10 ** 6)
        amplified = any(i.get("rendered") for i in (r.get("interactions") or ()))
        rank = (AMPLIFIER_LEVELS["met_with_amplifier"] if (at_threshold and amplified)
                else (AMPLIFIER_LEVELS["met"] if at_threshold else AMPLIFIER_LEVELS["neutral"]))
        if best is None or rank < best[0]:
            best = (rank, r, at_threshold, amplified)
    if best is None:
        return {"rank": AMPLIFIER_LEVELS["neutral"], "row": None, "at_threshold": False,
                "amplified": False, "member": False}
    return {"rank": best[0], "row": best[1], "at_threshold": best[2], "amplified": best[3],
            "member": True}


def _declared_line(st, conventions: dict, *, overlay_refs: frozenset = frozenset()) -> dict:
    """WHETHER THIS SERIES HAS A DECLARED DESK LINE AT ALL, and whether this reading is past it.

    ``{'declared': bool, 'label': str|None, 'crossed': bool|None, 'source': str|None}``. It is the fact
    MAJOR 1's sentence needs and nothing more: the row's own ``convention`` first (the served, matched
    label wins, because it is what SB-1 printed on this very page), then the ref's entry in the doc the
    producer was handed -- which is base-and-overlay merged, so the fifteen overlay refs count as
    DECLARED here exactly as they do for :func:`convention_distance`.

    ``source`` IS THE BOOK THE LINE CAME FROM, and it is review round 3's minor. ``served`` is the row's
    own convention (SB-1 printed it), ``book`` is the file's ``conventions:`` block, and ``overlay`` is
    this lane's watch-only ``watch_overlay:`` curation -- whose fifteen refs all carry
    ``percentile_bands [10, 90]`` against a ``TAIL_DECILE`` of 10.0, so "past the line" is arithmetic
    restating the tail rather than a second, independent fact. 180 of the 196 past-the-line tail
    sentences on the 108-seat replay were in that position. The caller passes the overlay-ONLY refs;
    with none passed, nothing is attributed to a book this page does not print.

    ``crossed`` IS TRI-STATE AND THE THIRD STATE IS NOT A BUG. An ``abs_bands`` line needs the raw level
    and a ``z_bands`` line needs the z; a board holding neither knows a line is declared and cannot say
    which side of it the reading sits on. ``None`` is that, and the sentence says it in words rather
    than asserting either of the two facts it does not have.

    IT MINTS NOTHING AND RANKS NOTHING. No figure, no handle, no term: ``T_TAIL`` stays band-free, the
    floor is unmoved, and the only consumer is the tail sentence's closing clause."""
    if st is None or getattr(st, "key", None) is None:
        return {"declared": False, "label": None, "crossed": None, "source": None}
    conv = st.convention if (st.convention and not st.convention.get("declined")) else None
    if conv and conv.get("matched") and conv.get("label"):
        return {"declared": True, "label": str(conv["label"]), "crossed": True, "source": "served"}
    ref = str(getattr(st.key, "ref", "") or "")
    book = "overlay" if ref in (overlay_refs or frozenset()) else "book"
    conf = (conventions or {}).get(ref) or {}
    kind = str(conf.get("kind") or (conv or {}).get("kind") or "")
    bands = [float(b) for b in (conf.get("bands") or [])]
    labels = list(conf.get("labels") or [])
    if not kind or not bands or len(labels) != len(bands):
        # THE ROW'S OWN CONVENTION IS ITSELF A DECLARATION, and this branch is why that matters. A
        # caller may hand this producer a NARROWED document (the decks do); the row still carries what
        # ``feeders._convention_label`` computed off the served one, and a line the page already knows
        # about must not be denied because the document in hand does not repeat it.
        if conv and (conv.get("band") is not None or conv.get("label")):
            return {"declared": True, "label": (str(conv["label"]) if conv.get("matched")
                                                and conv.get("label") else None),
                    "crossed": bool(conv.get("matched")), "source": "served"}
        return {"declared": False, "label": None, "crossed": None, "source": None}
    reading = (conv or {}).get("reading")
    if reading is None:
        reading = _measure_reading(kind, st)
    if reading is None:
        return {"declared": True, "label": None, "crossed": None, "source": book}
    reading = float(reading)
    mid = 50.0 if kind == "percentile_bands" else 0.0
    crossed = [(b, l) for b, l in zip(bands, labels) if _crossed(kind, reading, b, bands)]
    if not crossed:
        return {"declared": True, "label": None, "crossed": False, "source": book}
    # THE FURTHEST LINE CROSSED, in the reading's own direction -- the same "which line does this row
    # name" rule `convention_distance` uses in the other direction, so one reading never names a weak
    # line on a page where SB-1 named the strong one.
    _band, label = max(crossed, key=lambda bl: abs(float(bl[0]) - mid))
    return {"declared": True, "label": str(label), "crossed": True, "source": book}


def _tail_line_clause(fact: dict) -> str:
    """The ONE closing clause a ``tail_reading`` sentence carries, from :func:`_declared_line`'s fact.

    THE LINE'S BOOK CHOOSES BETWEEN THE TWO PAST-THE-LINE SENTENCES (review round 3). A served or
    file-declared line is a second, independent fact and reads as one; a line from this lane's own
    ``watch_overlay`` is the same decile the tail is already measured by, and its sentence says so."""
    if not fact.get("declared"):
        return NONOBVIOUS_CLAUSES["tail_no_line"]
    if fact.get("crossed") is True:
        if not fact.get("label"):
            return NONOBVIOUS_CLAUSES["tail_line_unplaced"]
        key = ("tail_past_overlay_line" if str(fact.get("source") or "") == "overlay"
               else "tail_past_line")
        return NONOBVIOUS_CLAUSES[key].format(label=fact["label"])
    if fact.get("crossed") is False:
        return NONOBVIOUS_CLAUSES["tail_line_uncrossed"]
    return NONOBVIOUS_CLAUSES["tail_line_unplaced"]


def _paths_on(bd, row) -> dict:
    """``{'n', 'depth', 'tops'}`` -- the DECLARED UPSTREAM paths landing on THIS price through this row.

    DEPTH BEFORE BREADTH (R11): a cause three hops up that reaches the price through this node is a
    different claim from three causes one hop up, and the deeper one is the one a desk has not already
    priced. ``bd.paths`` is the walk's own full closure; this reader counts and never re-walks.

    **``tops`` COMES BACK DEEPEST-FIRST** (review round 3, minor). The sentence names its first three
    causes immediately after "the deepest {depth} hops up", and this returned them in PATH-ITERATION
    order: MEASURED on the 144 banked seats, 119 of 256 drawn upstream rows named a first cause that
    is not at the stated depth. The arithmetic in the tail ("and five further causes") always let a
    careful reader recover that the list is the whole ancestor set, so this is ambiguity and not
    falsehood -- and it closes by sorting what the reader is shown. Ties keep first-seen order, so the
    result is deterministic over one board (threat A-5)."""
    tops: list = []
    deepest: dict = {}
    depth = 0
    for p in (getattr(bd, "paths", ()) or ()):
        if p.get("contract") != row.contract:
            continue
        if p.get("bottom") != row.driver_id or p.get("ancestor") == row.driver_id:
            continue
        top = str(p.get("ancestor") or "")
        d = int(p.get("depth") or 0)
        tops.append(top)
        if top not in deepest or d > deepest[top][0]:
            deepest[top] = (d, len(deepest) if top not in deepest else deepest[top][1])
        depth = max(depth, d)
    seen = tuple(dict.fromkeys(tops))
    ordered = tuple(sorted(seen, key=lambda t: (-deepest[t][0], deepest[t][1])))
    return {"n": len(tops), "depth": depth, "tops": ordered}


#: THE TWO SIGNS THAT COMMIT TO A DIRECTION. ``rows.SIGN_WORDS`` declares a THIRD, ``"0"``, whose own
#: words are "with no committed direction" -- a DECLARED ambiguity, and a different fact from both of
#: these and from an edge the model does not carry at all.
_COMMITTED_SIGNS: frozenset = frozenset(("+", "-"))


def _fan_facts(bd, row) -> dict:
    """The far boards this row's SAME READING is declared on, split by declared sign. ZERO reads.

    **AN AMBIGUOUS EDGE IS ITS OWN BUCKET AND IS NEVER FOLDED INTO EITHER DIRECTION** (review round 3,
    MAJOR 2). The split was string equality against the near row's sign, which admitted ``"0"`` on both
    sides of the comparison: a ``0`` edge landed in ``same`` when the near row was also ``0`` and in
    ``opposite`` when it was not. MEASURED over the 144 banked seats, flag on: 11 of 430 drawn
    ``spillover_reach`` rows narrated 88 edges the graph declares WITH NO COMMITTED DIRECTION as "in
    the same direction", one of them a CORE item -- and the block's own SB-F edge line for that row
    said "declared to move CBOT soybeans with no committed direction" two lines away. Over the whole
    declared graph the fold reaches 138 such edges on 29 rows plus 12 on rows whose own edge is signed.

    FOUR COUNTS COME BACK AND THEY SUM TO ``n``: ``same`` and ``opposite`` (both sides committed),
    ``undirected`` (the FAR edge declares no direction) and ``unplaced`` (the far edge commits and THIS
    row's own edge does not, so there is nothing to compare it with). ``near_signed`` says which of the
    two sentences the builder owes the reader."""
    for e in (getattr(bd, "fan", ()) or ()):
        if e.get("contract") == row.contract and e.get("driver_id") == row.driver_id:
            far = list(e.get("far") or ())
            near = str(row.sign or "")
            committed = [f for f in far if str(f.get("sign") or "") in _COMMITTED_SIGNS]
            undirected = [f for f in far if f not in committed]
            if near in _COMMITTED_SIGNS:
                same = [f for f in committed if str(f.get("sign")) == near]
                opp = [f for f in committed if str(f.get("sign")) != near]
                unplaced: list = []
            else:
                same, opp, unplaced = [], [], list(committed)
            return {"n": len(far), "same": len(same), "opposite": len(opp),
                    "undirected": len(undirected), "unplaced": len(unplaced),
                    "near_signed": near in _COMMITTED_SIGNS, "far": far}
    return {"n": 0, "same": 0, "opposite": 0, "undirected": 0, "unplaced": 0,
            "near_signed": str(getattr(row, "sign", "") or "") in _COMMITTED_SIGNS, "far": []}


def _nearest_far(fan: dict):
    """The far board a reader should be pointed at first: highest declared confidence, then soonest
    declared band, then the board's own name -- a deterministic order, never the index's."""
    rank = {"high": 0, "medium": 1, "low": 2}
    best = None
    for f in (fan.get("far") or ()):
        if not f.get("sign"):
            continue
        band = f.get("lag_band")
        minq = 99 if (band is None or band.min_q is None) else int(band.min_q)
        k = (rank.get(str(f.get("confidence") or ""), 3), minq, str(f.get("contract") or ""))
        if best is None or k < best[0]:
            best = (k, f)
    return None if best is None else best[1]


def nonobvious_candidates(bd, *, analogs=(), conventions: Optional[dict] = None,
                          overlay: Optional[dict] = None) -> list:
    """EVERY non-obvious candidate this board can name, UNRANKED and already past the bans.

    NOTHING HERE READS. Every input is a field the walk already filled: the loud rows and their states,
    ``bd.convergence``, ``bd.paths``, ``bd.fan``, ``bd.windows`` and the analog stanzas the caller
    hands in. The producer is PURE over ``(bd, analogs, conventions, overlay)`` -- run it twice in one
    process or once in a fresh one and it returns the same list in the same order (threat A-5).

    ``overlay`` IS THE WATCH-ONLY CONVENTIONS CURATION and is merged HERE and nowhere else (threat A-3).
    ``state_conventions.yaml``'s ``conventions:`` block feeds ``feeders._convention_label`` ->
    ``walk._convention_hit``, which is a TERM OF ``rank_key`` -- so curating a ref into that block
    changes ``bd.order`` and therefore the whole block on every board-on turn with every flag off. The
    fifteen new entries therefore live under their own top-level key, which ``lint.load_conventions``'s
    consumers never read, and reach this producer as an ADDITIVE overlay: the base entry always wins."""
    asof = str(getattr(bd, "asof", "") or "")
    order = {key: i for i, key in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    conv_doc = dict(_conventions() if conventions is None else conventions)
    merged = dict(conv_doc)
    overlay_only: set = set()
    for ref, entry in (overlay or {}).items():
        if ref not in merged:
            # WHICH REFS THE OVERLAY ACTUALLY SUPPLIED, kept because the tail sentence has to NAME the
            # book its line came from (review round 3) and `merged` cannot answer that question once
            # the two documents are one dict.
            overlay_only.add(ref)
        merged.setdefault(ref, entry)          # THE BASE ALWAYS WINS -- an overlay never overrides
    overlay_refs = frozenset(overlay_only)
    patterns = list(getattr(bd, "convergence", ()) or [])
    stanza_by_row: dict = {}
    for a in (analogs or ()):
        if a.get("declined"):
            continue
        stanza_by_row.setdefault((a.get("contract"), a.get("driver_id")), a)

    out: list = []
    for row in loud:
        st = row.state
        if st is None or status_word(st.status) != "ok":
            continue
        # -- BAN 1: a context_only row is never a watch anchor unless the question names positioning --
        #    ``NodeRow.subject`` is Amendment 1's own exception and the ONLY one: the board sets it when
        #    the resolved subject IS this driver. The refusal is counted on the trace and never rendered.
        if row.context_only and not getattr(row, "subject", False):
            continue
        win = _reading_window(bd, row)
        # -- BAN 2, SAID AS THE CODE ACTUALLY IMPLEMENTS IT (review round 2, minor f). The first comment
        #    here read "a CLOSED window is never nominated", which this loop does not do and R6 does not
        #    require: what a closed window loses is its DATES. The row is still a candidate -- it cleared
        #    the admission floor on a fact about the STATE, and refusing it for a calendar fact would be
        #    the deletion `T_WINDOW`-last exists to prevent -- and it renders with no ISO tail and no
        #    window clause, so no reader is ever shown a stale 1998 window against a 2026 reading, which
        #    IS what R6 buys (10 of the prototype's 60 rows). The window dict still rides `extra` for
        #    the trace, so `T_WINDOW` can read a closed window's open date: that is the LAST term of the
        #    rank and it is named here rather than quietly changed, because zeroing it would move rows.
        open_win = _window_open(win, asof)
        dates = ("" if not open_win else
                 (str(win["opens"]) if win.get("closes") is None
                  else f"{win['opens']} to {win['closes']}"))
        pat = _pattern_facts(bd, row, patterns)
        paths = _paths_on(bd, row)
        fan = _fan_facts(bd, row)
        stanza = stanza_by_row.get(row.key)
        base = None
        if stanza is not None:
            base = like_state_base_rate(stanza, row)
        floor = _floor_of(row, pattern_rows=patterns, path_n=paths["n"], base_rate=base)
        if not floor:
            continue
        n_run, direction = _run_of(st)
        run_word = R.RUN_DIRECTION_WORDS.get(direction, "") or "in one direction"
        periods = R.period_noun(str(getattr(st, "cadence", "") or ""), max(2, n_run))
        side = _side_word(st, kind=str((st.convention or {}).get("kind") or ""))
        what_is = _metric_words(st)
        fig = NONOBVIOUS_CLAUSES["figure"].format(what=what_is) if what_is else ""
        fig_and = NONOBVIOUS_CLAUSES["figure_and"].format(what=what_is) if what_is else ""
        conv = st.convention if st.convention and not st.convention.get("declined") else None
        extra = {"pattern": pat["rank"], "paths": paths, "fan": fan,
                 "window": {k: win.get(k) for k in ("opens", "closes", "anchor", "fallback")},
                 "tail": _tail_fraction(st), "run_n": n_run, "run_direction": direction}

        # 1 PAST THE LINE, with the run still going deeper -- the convex state
        if "past_a_declared_line" in floor and conv and conv.get("label"):
            out.append(_cand(
                "past_the_line", row,
                what=NONOBVIOUS_BODIES["past_the_line"].format(
                    label=conv["label"], run_n=R.words_for_int(n_run), periods=periods,
                    run_words=run_word, side=side, figure=fig),
                dates=dates, win=win, asof=asof, floor=floor, extra=extra))

        # 2 THE RECORD'S OWN TAIL -- band-free, and the only kind the balance sheet can reach
        elif "record_tail" in floor:
            p = _num(st.percentile)
            where = "top" if (p is not None and p >= 50.0) else "bottom"
            # THE CLOSING CLAUSE IS THE ROW'S OWN LINE FACT, never a fixed sentence (MAJOR 1). `merged`
            # is base-and-overlay, which is the same document `convention_distance` is given three lines
            # below -- one reading of "does this series have a declared line", not two.
            line_clause = _tail_line_clause(_declared_line(st, merged, overlay_refs=overlay_refs))
            out.append(_cand(
                "tail_reading", row,
                what=NONOBVIOUS_BODIES["tail_reading"].format(where=where, side=side, figure=fig_and,
                                                              line=line_clause),
                dates=dates, win=win, asof=asof, floor=floor, extra=extra))

        # 3 RUNNING AT AN UNCROSSED LINE -- the progress fraction, and ONLY with a run pointing at it
        else:
            cd = convention_distance(row, conventions=merged, measure_fallback=True)
            if cd is not None and n_run >= 2 and dates:
                progress = None
                try:
                    span = abs(float(cd["band"]))
                    if span > 0:
                        progress = max(0.0, min(1.0, 1.0 - (float(cd["distance"]) / span)))
                except (TypeError, ValueError, ZeroDivisionError):
                    progress = None
                frac = ("" if progress is None else NONOBVIOUS_CLAUSES["progress"].format(
                    percent=R.words_for_int(int(round(progress * 100)))))
                # WHICH OF THE THREE SENTENCES THIS ROW HAS EARNED (review round 3, MAJOR 1). The
                # claim is "its run points at it" and the gate tested the run's LENGTH; the band's own
                # side decides it, read off `_band_side` for a signed-axis line and off the SIGNED
                # reading for a magnitude one -- `cd["reading"]` is `abs()` for the magnitude kinds by
                # construction, so it cannot answer this and the row's own measure is read instead.
                signed = (st.convention or {}).get("reading")
                if signed is None:
                    signed = _measure_reading(str(cd["kind"]), st)
                toward = _run_with_the_line(str(cd["kind"]), cd["band"], signed, direction,
                                            (merged.get(st.key.ref) or {}).get("bands") or ())
                variant = ("approaching_line" if toward is True else
                           ("approaching_line_away" if toward is False
                            else "approaching_line_unplaced"))
                out.append(_cand(
                    "approaching_line", row, variant=variant,
                    what=NONOBVIOUS_BODIES[variant].format(
                        label=cd["label"], run_n=R.words_for_int(n_run), periods=periods,
                        run_words=run_word, side=side, progress=frac, figure=fig),
                    dates=dates, win=win, asof=asof,
                    floor=floor, extra={**extra, "line_progress": progress,
                                        "line_label": cd["label"], "run_toward": toward}))

        # 4 A DECLARED PATTERN AT ITS OWN THRESHOLD, amplifier line first
        if pat["row"] is not None and pat["at_threshold"]:
            pr = pat["row"]
            amp = ""
            if pat["amplified"]:
                first = next(i for i in (pr.get("interactions") or ()) if i.get("rendered"))
                amp = NONOBVIOUS_CLAUSES["amplifier"].format(
                    effect=R.AMPLIFIER_EFFECT_WORDS.get(str(first.get("effect") or ""),
                                                        "is declared"))
            # A THRESHOLD OF ONE IS NOT A CONVERGENCE and the sentence says which one it is looking at
            # (review round 3). The clause is keyed on the DECLARED threshold and never on how many
            # drivers matched: a pattern needing one driver is a different claim from a pattern needing
            # three and holding one, and only the first is what this row is narrating.
            alone = (NONOBVIOUS_CLAUSES["threshold_one"]
                     if int(pr.get("threshold") or 0) == 1 else "")
            out.append(_cand(
                "convergence_amplified", row,
                what=NONOBVIOUS_BODIES["convergence_amplified"].format(
                    n_matched=R.words_for_int(int(pr.get("n_matched") or 0)),
                    n_declared=R.words_for_int(int(pr.get("n_declared") or 0)),
                    pattern=R.pattern_label(pr.get("name")),
                    threshold=R.words_for_int(int(pr.get("threshold") or 0)), alone=alone,
                    amplifier=amp),
                dates=dates, win=win, asof=asof,
                # THE IDENTITY OF A PATTERN CANDIDATE IS THE PATTERN, NOT THE ROW, and that is the
                # single largest correction this producer took at its own landing. MEASURED on the
                # b40 fixture at max: SEVEN of seven ceiling slots were pattern rows, and five of them
                # narrated TWO patterns -- "supply squeeze" five times under five different driver
                # names. Five rows saying one thing is one item, and the ruling's whole sentence is
                # that four backed items beat five where two are noise. The series-key fold cannot see
                # it, because those five rows ARE five different series.
                identity=(f"pattern:{row.contract}:{pr.get('name')}", 0),
                floor=floor, extra=extra))

        # 5 TWO OR MORE DECLARED UPSTREAM PATHS MEETING ON THIS PRICE
        if paths["n"] >= 2:
            out.append(_cand(
                "upstream_convergence", row,
                what=NONOBVIOUS_BODIES["upstream_convergence"].format(
                    n_paths=R.words_for_int(paths["n"]), depth=R.words_for_int(paths["depth"]),
                    causes=R.name_list([R.humanise(t) for t in paths["tops"]], 3, noun="causes")),
                dates=dates, win=win, asof=asof, floor=floor, extra=extra))

        # 6 THE SAME READING DECLARED ON OTHER MARKETS -- the spillover, with its own far-board words
        # TWO IS THE FLOOR AND NOT ONE, and the correction is the sentence's own grammar. At ``n >= 1``
        # a SINGLE far market rendered "a move here is a move a desk has to price on markets this page
        # is not about" -- MEASURED on the four-board replay, corn's `ethanol demand` took ceiling slot
        # one on a fan of one. One declared edge is a declared edge, which the block already prints as
        # a spillover row; the non-obvious claim this kind makes is REACH, and reach needs more than
        # one market for the same reason the floor's own upstream clause needs more than one path.
        if fan["n"] >= 2 and not row.context_only:
            near = _nearest_far(fan)
            near_words = ""
            far_tokens: tuple = ()
            if near is not None:
                near_words = NONOBVIOUS_CLAUSES["nearest"].format(
                    market=R.board_label(near["contract"]), sign=R.sign_words(near.get("sign")),
                    band=R.band_words(near.get("lag_band")),
                    confidence=R.CONFIDENCE_WORDS.get(str(near.get("confidence") or ""), "medium"))
                far_tokens = (R.board_label(near["contract"]),)
            # THE SPLIT IS A COMPARISON AND A COMPARISON NEEDS TWO SIGNED EDGES (review round 3,
            # MAJOR 2). Where this row's own declared edge carries no committed direction there is
            # nothing to place the far ones against, and the sentence says so instead of counting
            # them into a direction: 11 of 430 drawn rows on the banked population.
            if fan.get("near_signed"):
                variant = "spillover_reach"
                body = NONOBVIOUS_BODIES["spillover_reach"].format(
                    n_far=R.words_for_int(fan["n"]), n_same=R.words_for_int(fan["same"]),
                    n_opposite=R.words_for_int(fan["opposite"]),
                    n_undirected=R.words_for_int(int(fan.get("undirected") or 0)),
                    nearest=near_words)
            else:
                variant = "spillover_reach_unplaced"
                body = NONOBVIOUS_BODIES["spillover_reach_unplaced"].format(
                    n_far=R.words_for_int(fan["n"]),
                    n_directed=R.words_for_int(int(fan.get("unplaced") or 0)),
                    n_undirected=R.words_for_int(int(fan.get("undirected") or 0)),
                    nearest=near_words)
            out.append(_cand(
                "spillover_reach", row, variant=variant, what=body,
                dates=dates, win=win, asof=asof,
                floor=floor, far_words=far_tokens, extra=extra))

        # 7 A STATE THE RECORD HAS BEEN IN BEFORE -- with its base rate, or it is not nominated
        # A RECURRENCE WITH NO DATED LIKE STATE IS NOT A RECURRENCE. The base rate says how often, and
        # the sentence has to say WHEN the nearest one was -- a rate with no exemplar is a number the
        # reader cannot check against the record it claims to summarise.
        if base is not None and not base.get("declined") and stanza is not None and stanza.get("date"):
            out.append(_cand(
                "recurrence", row,
                what=NONOBVIOUS_BODIES["recurrence"].format(
                    n_like=R.words_for_int(base["n"]),
                    states=("state" if base["n"] == 1 else "states"),
                    n_obs=R.words_for_int(base["m"]), date=stanza.get("date")),
                dates=str(stanza.get("date") or ""), asof=asof,
                floor=floor, far_words=(str(stanza.get("date") or ""),) if stanza.get("date") else (),
                extra={**extra, "base_rate": dict(base)}))
    return out


# ---------------------------------------------------------------------------------------------------
# NOVELTY -- computed on the RENDERED SENTENCE, never asserted per kind
# ---------------------------------------------------------------------------------------------------
def sb1_vocabulary(bd, *, loud_k: Optional[int] = None) -> frozenset:
    """EVERY WORD AND EVERY FIGURE the block's own SB-1 lines will carry, as one token set.

    It is built from the tier's LOUD CUT off ``bd.order``,
    which is what ``render.render_board`` renders as SB-1 lines -- and from the FIELDS those lines
    print: the driver's display name and its market, the desk line the reading is past, what the number
    is, and the figures themselves (the level, the z, the percentile and the reading's own date). The
    figures are in here because the ruling's sentence says "and its figures": a watch row that repeats
    the level the reader has just read two lines above is as familiar as one that repeats the name.

    IT IS READ BEFORE THE RENDER AND STILL SEES WHAT THE RENDER WILL SAY, which is what lets novelty be
    a rank term at all: the rank runs first, and both sides read one cut of one ordered list."""
    k = int(loud_k if loud_k is not None
            else (getattr(getattr(bd, "knobs", None), "loud_k", 0) or 0))
    order = {key: i for i, key in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    if k:
        loud = loud[:k]
    parts: list = []
    for r in loud:
        st = r.state
        if st is None or status_word(st.status) != "ok":
            continue
        parts += [R.humanise(r.driver_id), R.board_label(r.contract), _metric_words(st),
                  str(getattr(st, "level_date", "") or "")]
        conv = st.convention if (st.convention and not st.convention.get("declined")) else None
        if conv and conv.get("label"):
            parts.append(str(conv["label"]))
        for measure in (getattr(st, "level", None), _num(getattr(st, "z", None)),
                        _num(getattr(st, "percentile", None))):
            v = TR.num_or_none(measure)
            if v is not None:
                parts.append(R._fmt(v))
    return _content_tokens(" ".join(parts)) - _STOPWORDS


def novelty(cand: dict, vocabulary: frozenset) -> int:
    """HOW MANY DISTINCT THINGS THIS CANDIDATE'S RENDERED SENTENCE SAYS THAT THE BLOCK'S SB-1 LINES DO
    NOT -- a COUNT, computed on the sentence and its figures, and never asserted per kind.

    THE FIRST CUT OF THIS TERM WAS THE PER-KIND ASSERTION IT WAS WRITTEN TO FORBID, and the measurement
    is the proof: it read ``driver_id``, ``kind`` and ``far_words`` and returned 2 only for a driver
    outside the SB-1 cut -- but the candidate population IS that cut, so across the three acceptance
    fixtures 0 of 94 candidates ever scored 2 and the distributions collapsed to {0, 1} split exactly
    by kind (1 for the four relational kinds, 0 for the three reading kinds). With the term leading the
    tuple, ``past_the_line`` and ``tail_reading`` -- the ruling's own first floor clause and the top of
    its inverted ``T_NONLINEAR`` -- took 0 of 19 ceiling slots, and 19 of 20 reading-kind candidates
    were never nominated.

    SO IT IS NOW A COUNT OVER TOKENS, and the tokeniser is the whole mechanism:

      * the candidate's RENDERED SENTENCE is its label, its body and its dates -- the exact string
        ``render.sb_watch`` prints, figures included;
      * :data:`_GRAMMAR` is subtracted, so the SEVEN TEMPLATES' own fixed words ("decile", "hops",
        "route", "observations") cannot hand a kind a constant. That subtraction is what makes the term
        sentence-computed rather than kind-computed, and it is derived from the templates themselves;
      * :func:`sb1_vocabulary` is subtracted, so a name, a market, a desk line, a metric, a date or a
        FIGURE the page already prints two lines above counts for nothing;
      * what remains is what this row adds to the page, and the count of it is the term.

    A CANDIDATE WHOSE SUBJECT THE PAGE ALREADY LEADS WITH STILL SCORES for the other market it names,
    the pattern it names or the like state it dates -- which is the "1" the old three-value scale meant
    to express and never measured. It scores LESS than the same sentence about a row the page did not
    lead with, which is the "2".

    **WHAT IT IS NOT, SAID PLAINLY** (review round 2, minor d): it subtracts the SB-1 lines and the
    seven templates, and NOTHING ELSE. It does not score a candidate against the other CANDIDATES, so
    two nominations that say the same new thing each score for it and neither is discounted for the
    other. That is deliberate at this landing -- the draw's series, row and kind caps are what bound
    repetition inside the ceiling, and a novelty that fell as a list grew would make the term depend on
    the draw ORDER, which is the same rank it feeds. It is also why the term sits last among the
    ruling's own: it separates candidates the ruling cannot, and it decides nothing the ruling does."""
    text = " ".join(str(cand.get(k) or "") for k in ("label", "what", "dates"))
    return len(_content_tokens(text) - _GRAMMAR - frozenset(vocabulary))


# ---------------------------------------------------------------------------------------------------
# THE RANK -- the ruling's seven terms, stamped as nine numbers, every one an explicit field
# ---------------------------------------------------------------------------------------------------
_NONLINEAR_RANK: dict = {"past_the_line": 0, "tail_reading": 1, "approaching_line": 2}


def rank_terms(cand: dict, vocabulary: frozenset) -> dict:
    """THE RANK TERMS AS NAMED NUMBERS, stamped on the candidate and banked with it. The ruling names
    SEVEN and this record carries NINE keys: ``T_PATHS`` is stamped as its two halves (depth, then
    breadth) and ``T_NOVELTY``, the ruling's measurement clause, rides with them. :data:`RANK_TERM_KEYS`
    is that key set, and :data:`RANK_TERMS` stays the ruling's own list of names.

    They are a DICT and not only a tuple because the census, the arm and the report all have to be able
    to say WHY a row ranked where it did -- the 09-11 prototype printed its terms beside every row for
    exactly that reason, and a rank whose terms exist only inside a sort key cannot be audited.

    EVERY TERM RETURNS A NUMBER WITH A DECLARED DEFAULT (threat O-6). This producer meets rows whose
    ``run``, ``z``, ``percentile``, ``convention`` and ``receipts`` are all ``None`` or declined -- a
    ``None`` inside a sort tuple is a ``TypeError`` in the middle of a render, so there are none.

    **T_RUN IS CREDIT FOR A RUN IN THE CLAIM'S OWN DIRECTION, AND A RUN POINTING AWAY FROM THE LINE
    THE SENTENCE NAMES EARNS NONE** (review round 3, MAJOR 1; the 09-15 ruling's own words). The term
    is "consecutive prints in the tail's direction", and a candidate carrying ``run_toward=False`` has
    been MEASURED against the band's side and moves the other way: it keeps its place on the list and
    its true run count in its sentence, and loses the rank credit it was taking for a run that is not
    the one its kind claims. ``None`` -- a run this page cannot place against the line -- keeps the
    credit: the run is real and only its bearing is unread, which is a different fact from a run
    measured to point the wrong way."""
    paths = cand.get("paths") or {}
    fan = cand.get("fan") or {}
    win = cand.get("window") or {}
    return {
        "T_NOVELTY": int(novelty(cand, vocabulary)),
        "T_AMPLIFIER": int(cand.get("pattern", AMPLIFIER_LEVELS["neutral"])),
        "T_NONLINEAR": int(_NONLINEAR_RANK.get(str(cand.get("kind") or ""), 3)),
        "T_TAIL": float(cand.get("tail", 0.0)),
        "T_RUN": (0 if cand.get("run_toward") is False else int(cand.get("run_n", 0))),
        "T_PATHS_DEPTH": int(paths.get("depth", 0)),
        "T_PATHS_N": int(paths.get("n", 0)),
        "T_BREADTH": int(fan.get("n", 0)),
        "T_WINDOW": str(win.get("opens") or _NO_WINDOW),
    }


def rank_key(cand: dict) -> tuple:
    """The lexicographic tuple, from the stamped terms. NO WEIGHTS AND NO NORMALISING CONSTANTS -- the
    board's own ``walk.rank_key`` discipline, because a weight is a threshold with a smooth edge.

    ``T_WINDOW`` IS LAST (R12) AMONG THE RULING'S OWN TERMS, and the ordering is what makes it last: a
    window date is a calendar fact about a declared lag band, not a statement about the state. The
    prototype ranked it third and put the nearest lag ahead of the biggest asymmetry.

    **THE ORDER IS THE 09-11 RULING'S, VERBATIM** -- ``T_AMPLIFIER``, then the inverted
    ``T_NONLINEAR``, then the band-free ``T_TAIL``, ``T_RUN``, ``T_PATHS`` (depth before breadth),
    ``T_BREADTH``, ``T_WINDOW`` last -- and the first cut's departure from it is the defect this
    restores. That cut led with ``T_NOVELTY``, which the ruling names as a PROPERTY OF THE
    MEASUREMENT ("computed on the rendered sentence and its figures ... never asserted per kind") and
    never as the head of the rank; with the term degenerate (see :func:`novelty`) it demoted
    ``T_AMPLIFIER`` behind a constant and cost the reading kinds every ceiling slot on all three
    fixtures. Novelty now sits AFTER the ruling's seven, ahead of the deterministic id stabiliser: it
    breaks ties between candidates the ruling's own terms cannot separate, which on a lexicographic
    tuple of counts is a real and frequent job, and it can no longer overrule a term the ruling put
    before it.

    THE TWO TRAILING STRINGS ARE NOT TERMS. They are the determinism stabiliser -- two candidates with
    an identical rank tuple and an identical novelty must still sort the same way in a fresh
    process, or one board prints two pages (threat A-5)."""
    t = cand.get("terms") or {}
    return (int(t.get("T_AMPLIFIER", AMPLIFIER_LEVELS["neutral"])),
            int(t.get("T_NONLINEAR", 3)),
            -float(t.get("T_TAIL", 0.0)),
            -int(t.get("T_RUN", 0)),
            -int(t.get("T_PATHS_DEPTH", 0)),
            -int(t.get("T_PATHS_N", 0)),
            -int(t.get("T_BREADTH", 0)),
            str(t.get("T_WINDOW", _NO_WINDOW)),
            -int(t.get("T_NOVELTY", 0)),
            str(cand.get("driver_id") or ""), str(cand.get("kind") or ""))


# ---------------------------------------------------------------------------------------------------
# THE DRAW -- a CEILING and never a quota, 2N nominated, one honest absence line
# ---------------------------------------------------------------------------------------------------
def release_footnote(bd, *, calendar_doc: Optional[dict] = None) -> Optional[dict]:
    """THE ONE-LINE DATED-RELEASES FOOTNOTE -- outside the ceiling, never a row of it.

    "Watch the WASDE" is the item the 09-11 ruling bans: a scheduled print is a date somebody else
    already published, it is on every desk's calendar, and 22 of the 68 rows on the shipped watch page
    (32.4%) were exactly that. The dates are still TRUE and still worth one line, so they are stated
    ONCE, as an absence-class note that no ceiling slot is spent on and that ``watch_leg`` can never
    read as a fired fact.

    IT CARRIES NO DIGIT BUT ITS ISO DATES. SB-X is a date-only class and the label is where the dates
    ride; the sentence itself is letters."""
    from leviathan.graphrag.state.calendar import next_release
    order = {key: i for i, key in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    seen: list = []
    for row in loud:
        st = row.state
        table = (st.table if st is not None else "") or ""
        if not table:
            continue
        rel = next_release(table, bd.asof, doc=calendar_doc)
        if rel.declined or not rel.dates:
            continue
        for d in str(rel.dates).replace(" to ", " ").split():
            if d not in seen:
                seen.append(d)
    if not seen:
        return None
    # THE DATES ARE A CALENDAR AND A CALENDAR IS CHRONOLOGICAL. The first cut printed them in the loud
    # ORDER -- "2026-10-01, 2026-10-05, 2026-09-10, 2026-09-09, 2026-09-12, 2026-09-11" -- which is a
    # rank the reader cannot see leaking through a line that reads as a diary. And a list cut at six
    # SAYS SO, in the estate's own idiom (`render.name_list`'s "and n further"), two SB-X lines away
    # from a truncation note that already reads that way.
    seen = sorted(set(seen))
    shown, more = seen[:6], max(0, len(seen) - 6)
    tail = f", and {R.words_for_int(more)} further" if more else ""
    return {"kind": "release_footnote", "form": "absence",
            "label": ("the prints already scheduled for the series named above ("
                      + ", ".join(shown) + tail + ")"),
            "reason": "release_dates_only", "declined": "release_dates_only",
            "what": "", "dates": "", "row": (), "nonobvious": True}


def absence_row(*, partial: bool = False, alternates: bool = False) -> dict:
    """THE HONEST ABSENCE LINE. A board that clears the floor with nothing prints THIS and not a padded
    list -- the ruling's own words: four backed items and one honest absence line beat five rows where
    two are noise, and zero backed items and one honest line beat three rows that are all noise.

    **THE PARTIAL FILL IS A DIFFERENT SENTENCE AND NOT A DIFFERENT LABEL**, which is the correction
    review found. The first cut changed the label to "a further forward item" and kept
    ``watch_floor_unmet``'s reason, so a block that had just printed six nominations closed with
    "nothing forward on this page clears the bar this list sets" -- a sentence contradicting the six
    rows immediately above it (REPRODUCED on el_nino_fanout at cap nine). The two cases are two facts:
    nothing cleared the bar, and nothing FURTHER cleared it, so they are two closed words with two
    sentences in ``render.ABSENCE_WHY``.

    **AND THERE ARE THREE CASES, NOT TWO** (review round 3, MAJOR). ``watch_nothing_further``'s sentence
    -- "nothing further on this page clears the bar this list sets, so no weaker item is offered to fill
    the space" -- is a statement about the ADMISSION BAR, and ``nonobvious_rows`` emitted it whenever the
    TIGHT pass under-filled, which is a statement about the DISTINCTNESS CAPS. MEASURED on the 108-seat
    d2 replay: 36 seats printed the note and ALL 36 printed it under alternates -- items that had
    cleared the same bar and were held back by the one-per-reading, one-per-source and third-of-a-kind
    caps, offered on the lines immediately above. The note was denying the items it sat under, which is
    the defect round 1 raised for the full-absence case re-entered one predicate to the left. So the
    caps get their own word: ``watch_core_capped`` where the pass was bounded by the caps and the
    held-back items are on the page, ``watch_nothing_further`` where the candidate list was genuinely
    exhausted and nothing is offered below. CORRECTED, never struck -- the reader is still told the core
    is short and is now told the true reason."""
    word = ("watch_core_capped" if (partial and alternates)
            else ("watch_nothing_further" if partial else "watch_floor_unmet"))
    label = ("a further core item on this page" if (partial and alternates)
             else ("a further forward item on this page" if partial
                   else "a forward item on this page"))
    return {"kind": word, "form": "absence", "label": label,
            "reason": word, "declined": word, "what": "", "dates": "", "row": (),
            "nonobvious": True}


def nonobvious_rows(bd, *, analogs=(), cap: Optional[int] = None,
                    conventions: Optional[dict] = None, overlay: Optional[dict] = None,
                    calendar_doc: Optional[dict] = None, loud_k: Optional[int] = None) -> list:
    """THE 2N NOMINATION, ranked, deduped, and cut at a CEILING that is never padded up to.

    THE DRAW IS NOT AN INTERLEAVE. :func:`watch_rows`' round-robin exists so a cap does not eat a KIND;
    this list is ranked end to end because the 09-11 ruling is about WHICH ITEMS, not about giving each
    kind a seat -- a kind guaranteed a seat is a quota, and the ruling struck quotas by name.

    THE DIVERSITY RULE IS ON THE SERIES KEY AND NOT THE KIND. Inside the ceiling a series key appears
    ONCE, so a board cannot spend three of its five slots on three facts about one ONI print; the
    nomination tail (slots N+1 .. 2N) relaxes that to twice, because the writer is choosing and a second
    angle on the loudest reading is a legitimate thing to offer it.

    RETURNS AT MOST ``2N`` NOMINATIONS PLUS AT MOST ONE FOOTNOTE, or exactly one absence row."""
    n = nonobvious_k(bd.mode, cap)
    vocabulary = sb1_vocabulary(bd, loud_k=loud_k)
    cands = nonobvious_candidates(bd, analogs=analogs, conventions=conventions, overlay=overlay)
    for c in cands:
        c["terms"] = rank_terms(c, vocabulary)
    cands.sort(key=rank_key)

    # ONE CANDIDATE PER (series key, offset) PER KIND -- R10's fold, applied before the draw so the
    # ranking never spends a comparison on two records of one reading.
    best: dict = {}
    ranked: list = []
    for c in cands:
        key = (c["dedupe"], c["kind"])
        if key in best:
            continue
        best[key] = c
        ranked.append(c)

    out: list = []
    per_series: dict = {}
    per_kind: dict = {}
    per_row: dict = {}
    ceiling, nominate = n, n * NOMINATE_MULTIPLE
    # NO KIND MAY TAKE MORE THAN A THIRD OF THE CEILING (rounded up). It is a CAP and not a quota: it
    # never promotes a kind and guarantees none a seat, it only bounds REPETITION -- which is the
    # failure the ruling names in its own words. MEASURED at this landing on the b40 fixture at max:
    # without it the ceiling was seven of seven pattern rows, five of them narrating two patterns.
    #
    # WHAT IT COSTS, MEASURED AND ACCEPTED (review round 3, minor -- the decision recorded where the
    # owner can read it). The cap moves a CLAIM and not a row: where a source's best-ranked claim is a
    # kind that is already full, the same source enters on its next-best claim instead. On the 108-seat
    # d2 replay that is 90 of 479 core items (18.8%), 63 of them a tail claim entering as a spillover.
    # The alternative -- skipping the source entirely once its best claim is capped -- drops a
    # top-decile reading out of the core to protect a sentence's variety, which is a worse trade for the
    # reader than a true second-best claim. AND THE STRONGER FACT IS NOT LOST: 63 of the 90 state it in
    # their own admission clause (minor (a)'s "what admits it here is that ..."), and 73 of the 90 carry
    # the blocked claim itself as an alternate below. Both numbers are this lane's replay, not a deck
    # pin: they are properties of the banked boards (scratchpad/s7b_w3/probe_demote.py), and what the
    # deck pins is the rule under them -- a claim that does not state its own floor clause carries the
    # admission clause that does.
    kcap = max(1, (ceiling + 2) // 3)

    def _draw(limit: int, series_cap: int, kind_cap: int, row_cap: int, slot: str) -> None:
        """One pass of the draw, up to ``limit`` rows, under one set of caps.

        ``slot`` IS THE PASS AND NOT THE POSITION. Labelling by ``len(out) < ceiling`` would stamp
        "ceiling" on a row the RELAXED pass admitted whenever the tight pass under-filled -- MEASURED on
        the banked cocoa board at deep, where the tight pass took four and the fifth row in the list was
        a second `drought` sentence wearing the ceiling's name. The trace has to say which bar a row
        cleared."""
        for c in ranked:
            if len(out) >= limit:
                return
            if c.get("slot"):
                continue                                # already taken by an earlier pass
            # THE SERIES CAP -- R10's fold: one reading per slot inside the ceiling.
            if per_series.get(c["dedupe"], 0) >= series_cap:
                continue
            # THE ROW CAP, a DIFFERENT fold, and it is needed because a pattern candidate's identity is
            # its PATTERN while a spillover candidate's is its SERIES KEY -- two identities, one driver.
            # MEASURED on the banked soybeans board at deep: the ceiling's first two rows were both
            # "China state reserves", once as a pattern member and once as a spillover; the palm board
            # did the same with "DMO". Two sentences about one row is one item, whichever kinds made
            # them.
            if per_row.get(c["row"], 0) >= row_cap:
                continue
            if per_kind.get(c["kind"], 0) >= kind_cap:
                continue
            per_series[c["dedupe"]] = per_series.get(c["dedupe"], 0) + 1
            per_kind[c["kind"]] = per_kind.get(c["kind"], 0) + 1
            per_row[c["row"]] = per_row.get(c["row"], 0) + 1
            c["slot"] = slot
            c["ceiling"] = ceiling
            out.append(c)

    # TWO PASSES, AND THE SECOND ONE IS WHY. A single pass that tightened its caps on ``len(out) <
    # ceiling`` never relaxes them on a board whose ceiling cannot be filled: MEASURED on the banked
    # cocoa board at deep, the draw stopped at FOUR rows with eight admitted candidates still on the
    # table, because the ceiling was never reached and the nomination tail's own rules were therefore
    # never applied. The ceiling is filled first under the tight caps -- that is what makes it a
    # ceiling of DISTINCT items -- and the nomination tail is then drawn under the relaxed ones.
    _draw(ceiling, 1, kcap, 1, "ceiling")
    taken = len(out)
    _draw(nominate, 2, 2 * kcap, 2, "nomination")
    # THE CEILING REACHES THE WRITER, and until this landing it did not (review round 2, MAJOR 2).
    # `nonobvious_k` sized the draw and `_draw` stamped the pass, but `render.sb_watch` printed the same
    # line for both passes and the selection licence named no number -- so a Scan block handed the
    # writer six indistinguishable nominations under a ceiling of three. Each drawn row now carries its
    # PLACE and its pass's SIZE, the render prints both in words, and `WATCH_SELECTION_CLAUSE` tells the
    # writer to keep at most the core. The 2N nomination is untouched: it is the owner's number, and
    # what changes is that N binds the selection rather than only the draw.
    for pass_name in ("ceiling", "nomination"):
        drawn = [c for c in out if c.get("slot") == pass_name]
        for i, c in enumerate(drawn, 1):
            c["slot_index"], c["slot_size"] = i, len(drawn)
    if not out:
        return [absence_row()]
    # THE HONEST ABSENCE LINE ALSO RIDES A PARTIAL FILL, and that is the ruling's own sentence: "four
    # backed items and one honest absence line beat five rows where two are noise". A tier whose
    # ceiling is five and whose board cleared the bar with four says so, in one line, rather than
    # letting the reader assume the list was cut at its own length.
    # WHICH SENTENCE THE NOTE CARRIES IS DECIDED BY WHAT IS ON THE PAGE (review round 3, MAJOR). `taken`
    # counts the TIGHT pass alone, so `taken < ceiling` says the DISTINCTNESS CAPS bound the core and
    # says nothing at all about the admission bar -- and the relaxed pass's rows, drawn under looser
    # caps from the very candidates the tight pass skipped, sit on the lines immediately above the note.
    # A page with alternates therefore takes the caps' word and a page with none takes the exhausted
    # one. MEASURED before this repair: 36 of 108 replay seats printed the note and 36 of 36 printed it
    # over alternates.
    rows = list(out)
    if taken < ceiling:
        rows.append(absence_row(partial=True, alternates=len(out) > taken))
    foot = release_footnote(bd, calendar_doc=calendar_doc)
    return rows + ([foot] if foot is not None else [])
