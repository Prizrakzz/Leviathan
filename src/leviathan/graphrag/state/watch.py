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


def convention_distance(row, *, conventions: Optional[dict] = None) -> Optional[dict]:
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
def watch_rows(bd, *, analogs=(), cap: Optional[int] = None, conventions: Optional[dict] = None,
               calendar_doc: Optional[dict] = None) -> list:
    """EVERY watch row this board can name, interleaved by kind and cut at the tier's render cap.

    THE INTERLEAVE IS WHY THE CAP DOES NOT EAT A KIND. A straight rank walk would fill an eight-row cap
    with kind-1 rows on a twelve-row loud set and the reader would never meet a lag window at all; the
    kinds are queued separately and drawn round-robin in the design's own numbering, and inside each
    queue a FIRED row always precedes a DECLINED one -- an absence is a row, but it never displaces a
    fact.

    THIS FUNCTION NEVER GUESSES A HANDLE POSITION. A kind-2 row carries the four numbers and the row
    object; the RENDER mints the line, because the handle it takes depends on how many magnitudes the
    block has already committed and only the block knows that."""
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
    DOMINANT closed word when every row is an absence, ``not_reached`` when the producer made none."""
    if not rows:
        return bd.stamp("watch", "not_reached")
    fired = [w for w in rows if not w.get("declined")]
    if fired:
        return bd.stamp("watch", "fired")
    counts: dict = {}
    for w in rows:
        counts[w["declined"]] = counts.get(w["declined"], 0) + 1
    word = sorted(counts, key=lambda x: (-counts[x], x))[0]
    return bd.stamp("watch", "declined", reason=word)
