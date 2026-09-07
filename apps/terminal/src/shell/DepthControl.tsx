import * as Tooltip from '@radix-ui/react-tooltip';
import { useCredits } from '@/api/useCredits';
import { utcDay } from '@/lib/time';
import {
  CHOICE_COPY,
  CHOICE_COST,
  CHOICES,
  DEEP_RESEARCH_DARK_TITLE,
  DEFAULT_CHOICE,
  DOSSIER_CHOICE,
  isChoice,
  isChoiceServed,
  isMetered,
  servedChoice,
  useMode,
  type PickerChoice,
} from '@/store/mode';
import { chargeNoteFor, creditWord, CreditsBadge } from './CreditsBadge';

/**
 * D-MW-21 / THE CASCADE NOTCH (2026-09-06) — the ask bar's DEPTH CONTROL.
 *
 * A NOTCHED SLIDER, not a menu, because the thing being chosen is a RAMP: Scan -> Analysis -> Cascade is
 * one axis with three stops, and a drop-down hides that ordering behind a click. The control shows every
 * stop at once, marks where you are on it, and reads its state out loud as a slider (`role="slider"`,
 * `aria-valuetext` = the tier label, never the internal identifier).
 *
 * WHAT MOVED, AND ON WHOSE WORD (owner, 2026-09-06): "add Cascade in place of Deep Research in the scaler,
 * have Deep Research as a standalone button on the right, but it's turned off (lights are off; it says to
 * the user when he hovers that it will be available in Leviathan V1.2)". So:
 *  - the TOP NOTCH is **Cascade** (`mode=max`, two credits, `synth_effort=max`, depth 2). It is still a
 *    DARK backend preset, honored only where `GRAPHRAG_MODES` names it, which is why it is gated: see
 *    `blockedReason`'s first clause and `store/mode.servedModes`.
 *  - **Deep Research** left the ramp entirely and is a standalone, lights-off control at the RIGHT of this
 *    row. It is `aria-disabled` and FOCUSABLE (a disabled button takes no focus, and a tooltip nobody can
 *    reach by keyboard is not a tooltip), carries the V1.2 sentence as its `title`, and has no submit path
 *    of any kind. The serving revision that ships this control sets `GRAPHRAG_DOSSIER=off`, so the button
 *    and the backend agree: every dossier route 404s.
 *  - THE DOSSIER QUOTA BADGE IS DROPPED, not moved. It rode the old top notch and rendered the 4/month
 *    allowance; a live meter beside a control nobody can press is noise about a resource nobody can spend,
 *    and reading it cost this component a query (DOSSIER_QUOTA_KEY) on every mount. It comes back with the
 *    button in V1.2 — the seam (`api/dossier.getDossierQuota`, its query key and its invalidation on
 *    submit) is untouched and still used by the submit path.
 *
 * THE INVARIANT CARRIED FORWARD FROM D-DR-3, unchanged: the control lives at the ASK BAR (the recorded
 * depth-is-per-question amendment) and goes inert while a turn streams, for the same reason the textarea
 * does — the selection that governs a submit is the one that was on screen at submit, and a control that
 * moves mid-turn would imply otherwise.
 *
 * KEYBOARD, and the one judgement call in it: the slider owns the a11y contract (Left/Down step shallower,
 * Right/Up step deeper, Home/End jump to the ends) and the notches are POINTER affordances — `aria-hidden`,
 * `tabIndex={-1}` — so a screen reader hears one control with one value rather than three buttons and a
 * slider claiming to be the same thing. Stepping SKIPS an unavailable notch instead of stalling on it: with
 * Analysis out of credits, ArrowRight from Scan must still reach Cascade. Nothing is hidden by that skip,
 * because the reason a notch was skipped is written under the control (`depth-blocked-*`) whether or not it
 * has focus.
 *
 * The hints are STATIC copy and deliberately RELATIVE ("one turn", "a longer turn", "the longest turn").
 * Per-mode p50s exist only once the EMF `mode` dimension has traffic; a precise number here before then is
 * a measurement nobody made. The BADGE is the exception and is not copy at all — it is the server's own
 * count of the monthly credit grant, the meter Analysis and Cascade both spend.
 */

/** A depth ramp, so the control reads as a LEVEL before any label is read at all. */
const GLYPH: Record<PickerChoice, string> = {
  quick: '▃',
  deep: '▅',
  cascade: '▇',
  deep_research: '◆', // the standalone control's mark; not a notch on the ramp
};

export function DepthControl({ disabled = false }: { disabled?: boolean }) {
  const stored = useMode((s) => s.choice);
  const setChoice = useMode((s) => s.setChoice);
  // A slider can only be parked on a SLIDER notch THIS DEPLOYMENT SERVES. Two coercions, and the second is
  // the 2026-09-07 fix:
  //  - `isChoice`: `deep_research` is still a `PickerChoice` (Shell's dossier route reads it) but is no
  //    longer in `CHOICES`, so a store set directly to it renders as Scan rather than as an off-ramp value
  //    with no notch under it.
  //  - `servedChoice`: BLOCKING A GESTURE IS NOT THE SAME AS CORRECTING A VALUE. `pick`/`step`/`jump` all
  //    consult `blocked`, and none of them runs when the store ALREADY holds `cascade` — which a v3 blob
  //    from a bundle that was told `max`, or a direct `setState`, can do. Measured before this line
  //    existed: the control rendered the blocked sentence, kept `aria-valuetext="Cascade"`, and Shell
  //    submitted `mode=max` to a deployment that resolves it to `standard` with no chip and no error. The
  //    correction is down-only (see `store/mode.servedChoice`), so it can never walk a selection up into a
  //    costlier tier, and the reason stays on screen below as `depth-blocked-cascade`.
  const choice: PickerChoice = servedChoice(isChoice(stored) ? stored : DEFAULT_CHOICE);

  // The credit grant (D-MW-25). ONE query key, shared with the badge and with every invalidation point.
  const credits = useCredits();

  /** Why a notch cannot be chosen right now, or '' when it can. The refusal reason is the copy that wins. */
  const blockedReason = (c: PickerChoice): string => {
    const label = CHOICE_COPY[c].label;
    // THE SERVED-ROSTER GATE, and the reason it is first: it is a fact about the DEPLOYMENT, not about this
    // user's balance. `max` is a dark backend preset — honored only where GRAPHRAG_MODES names it — and a
    // notch that asked for a tier the allowlist does not honor would be resolved to `standard` with no
    // signal at all, i.e. a two-credit selection delivering a free turn's depth. Blocked beats silent.
    // THIS CLAUSE IS ALSO WHY THE V1.2 DEEP RESEARCH RESTORATION IS TWO EDITS: `isChoiceServed` is `false`
    // for every choice whose `CHOICE_MODE` entry is `null`, and the dossier route's is `null` by design, so
    // a `deep_research` put back into `CHOICES` alone would render "not yet enabled on this deployment"
    // forever. Restoring the notch means restoring a dossier clause ABOVE this one, gated on its own flag
    // and monthly allowance (GET /v1/dossier/quota) rather than on GRAPHRAG_MODES.
    // AND IT IS A STANDING LINE ON A BUILD THAT WAS TOLD NOTHING — ADJUDICATED, NOT OVERLOOKED
    // (2026-09-07). Every other blocked reason is transient (a balance refills); this one is fixed for
    // the life of the bundle, so a build without `VITE_MODES` renders the amber paragraph
    // "Cascade is not yet enabled on this deployment" under the ask bar for every user, forever. IT
    // STAYS, and it is intended product copy: the notch is VISIBLE on that build (it is a stop on the
    // ramp, drawn faint), and a stop nobody can reach with no sentence saying why is the silent-drop
    // trap wearing a nicer coat. The owner's word of 2026-09-07 also makes the state short-lived where
    // it matters — the notch ships AVAILABLE and production names the flag (see `store/mode.servedModes`
    // and the flip recipe in `leviathan.graphrag.server`) — so the standing case is the mock/dev lane,
    // where "not yet enabled on this deployment" is exactly true and worth reading.
    if (!isChoiceServed(c)) return `${label} is not yet enabled on this deployment`;
    // A metered ask notch is blocked only by a REAL exhausted balance. Metering dark, or a balance we could
    // not read, leaves it selectable: the same fail-open posture the server takes.
    const cost = CHOICE_COST[c] ?? 0;
    const day = utcDay(credits.balance?.reset_at);
    if (cost > 0 && credits.exhausted) {
      return day ? `no credits left — the grant resets ${day} (UTC)` : 'no credits left this month';
    }
    // AND THE PRICE THIS NOTCH ACTUALLY COSTS. A balance of 1 is not "exhausted", but a Cascade turn needs
    // two — the server refuses that at the gate (429, before a byte streams), so the control must not offer
    // it. This clause exists because the ladder stopped being 0/1 the day Cascade was priced.
    // THE SENTENCE BELOW IS HALF OF A PAIR, and the other half is the server's 429 `detail`
    // (`leviathan.graphrag.server._CREDITS_INSUFFICIENT_DETAIL`): "this tier costs two credits and you
    // have 1 left; the grant resets 2026-09-01 (UTC)". Every word from "costs" onward is the same in
    // both, because a user can meet this refusal twice in ten seconds — here before the submit, and as a
    // toast after one this control could not block (a balance up to 30s stale, a second tab, a direct API
    // call) — and two vocabularies for one fact reads as two systems disagreeing about your money. The two
    // may differ in exactly two places: the tier's NAME (this side has the label; the server's only name
    // for it is the wire identifier `max`, which never reaches a screen) and the clause join. That
    // agreement has a reader, not a hope: `config_check.check_cascade_notch` clause (vii) renders both
    // templates and diffs them clause by clause.
    const left = credits.balance?.remaining;
    if (cost > 1 && typeof left === 'number' && left < cost) {
      const price = creditWord(cost);
      const have = `${left} left`;
      return day
        ? `${label} costs ${price} and you have ${have} — the grant resets ${day} (UTC)`
        : `${label} costs ${price} and you have ${have}`;
    }
    return '';
  };

  const blocked = (c: PickerChoice) => blockedReason(c) !== '';
  const index = Math.max(0, CHOICES.indexOf(choice));
  const copy = CHOICE_COPY[choice];

  const pick = (c: PickerChoice) => {
    if (disabled || blocked(c)) return; // the reason stays on screen; the selection does not move
    setChoice(c);
  };

  /** The next SELECTABLE notch in a direction, or the current one when there is none. */
  const step = (dir: 1 | -1) => {
    for (let i = index + dir; i >= 0 && i < CHOICES.length; i += dir) {
      const c = CHOICES[i];
      if (c && !blocked(c)) return pick(c);
    }
  };

  /** The first/last selectable notch (Home/End must not land on a wall either). */
  const jump = (from: 'start' | 'end') => {
    const order = from === 'start' ? [...CHOICES] : [...CHOICES].reverse();
    const c = order.find((x) => !blocked(x));
    if (c) pick(c);
  };

  return (
    <div className="min-w-0" data-testid="depth-control">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-11 uppercase tracking-wider text-text-faint">depth</span>

        <div
          role="slider"
          aria-label="answer depth"
          aria-valuemin={0}
          aria-valuemax={CHOICES.length - 1}
          aria-valuenow={index}
          aria-valuetext={copy.label}
          aria-orientation="horizontal"
          aria-disabled={disabled || undefined}
          tabIndex={disabled ? -1 : 0}
          data-testid="depth-slider"
          // Refetch the balance when the control takes focus: this is the moment the number is about to be
          // acted on, and a cached "97 of 100" on a page left open overnight is the lie it exists to
          // prevent. (The old menu did this on open; a slider has no open.)
          onFocus={() => credits.refetch()}
          onKeyDown={(e) => {
            if (disabled) return;
            if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
              e.preventDefault();
              step(1);
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
              e.preventDefault();
              step(-1);
            } else if (e.key === 'Home') {
              e.preventDefault();
              jump('start');
            } else if (e.key === 'End') {
              e.preventDefault();
              jump('end');
            }
          }}
          className={`flex items-center gap-0.5 rounded-chip border border-line px-1 py-0.5 focus:border-cyan focus:outline-none ${
            disabled ? 'opacity-40' : ''
          }`}
        >
          {CHOICES.map((c, i) => {
            const off = blocked(c);
            const on = i <= index && !off;
            return (
              <button
                key={c}
                type="button"
                // The SLIDER is the accessible control; these are the mouse's way of reaching a notch
                // directly. Hidden from the a11y tree and out of the tab order on purpose (see header).
                aria-hidden="true"
                tabIndex={-1}
                disabled={disabled}
                title={`${CHOICE_COPY[c].label} — ${CHOICE_COPY[c].time}`}
                data-testid={`depth-notch-${c}`}
                data-selected={c === choice || undefined}
                data-blocked={off || undefined}
                onClick={() => pick(c)}
                className={`px-0.5 font-mono text-12 leading-none ${
                  off ? 'text-text-faint opacity-40' : on ? 'text-cyan' : 'text-text-dim'
                }`}
              >
                {GLYPH[c]}
              </button>
            );
          })}
        </div>

        <span data-testid="depth-value" className="font-mono text-11 text-text">
          {copy.label}
        </span>
        <span className="font-mono text-11 text-text-faint">{copy.time}</span>

        <CreditsBadge />

        {/* DEEP RESEARCH -- standalone, at the right, LIGHTS OFF until V1.2 (owner's word 2026-09-07:
            "very dim that I couldn't see it the first time, design it well"). The first cut was the
            faint text colour at 40% opacity with a native `title` tooltip: invisible against the ground,
            and a title tooltip is a second-late whisper nobody waits for. THIS cut is legible and
            unmistakably OFF: full-contrast dim text, a DASHED border (a placeholder, not a control),
            an UNLIT LAMP (the empty dot) and a V1.2 tag on the pill; the sentence lives in the house
            Radix tooltip (the citation chips' shape), which opens on hover within 100 ms AND on
            keyboard focus. Not `disabled`: a disabled button takes no focus and fires no pointer
            events, which would take the tooltip down with the click. `aria-disabled` + a no-op handler
            is what makes it inert without making it invisible; the accessible name carries the
            sentence for readers that never hover. */}
        <Tooltip.Provider delayDuration={100}>
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <button
                type="button"
                data-testid="deep-research-button"
                aria-disabled="true"
                tabIndex={0}
                aria-label={`${CHOICE_COPY[DOSSIER_CHOICE].label} — ${DEEP_RESEARCH_DARK_TITLE}`}
                onClick={(e) => e.preventDefault()}
                className="ml-auto inline-flex cursor-not-allowed items-center gap-1.5 rounded-chip border border-dashed border-line px-2 py-0.5 font-mono text-11 text-text-dim hover:border-text-dim focus:outline-none focus-visible:border-cyan"
              >
                <span
                  aria-hidden="true"
                  data-testid="deep-research-lamp"
                  className="inline-block h-1.5 w-1.5 rounded-full border border-text-faint"
                />
                <span aria-hidden="true">{GLYPH[DOSSIER_CHOICE]}</span>
                {CHOICE_COPY[DOSSIER_CHOICE].label}
                <span className="rounded-chip border border-line px-1 text-11 uppercase tracking-wider text-text-faint">
                  v1.2
                </span>
              </button>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                side="top"
                sideOffset={6}
                className="z-50 max-w-xs rounded-panel border border-line bg-bg-1 p-2 font-sans text-12 text-text shadow-lg"
              >
                <div className="font-mono text-11 text-text-dim">
                  {GLYPH[DOSSIER_CHOICE]} {CHOICE_COPY[DOSSIER_CHOICE].label} · lights off
                </div>
                <div className="mt-1">{DEEP_RESEARCH_DARK_TITLE}</div>
                <div className="mt-1 text-text-dim">{CHOICE_COPY[DOSSIER_CHOICE].detail}</div>
                <Tooltip.Arrow className="fill-line" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        </Tooltip.Provider>
      </div>

      <p data-testid="depth-hint" className="mt-0.5 font-sans text-11 leading-snug text-text-faint">
        {copy.detail}
      </p>

      {/* The charge trade, on screen exactly when it applies to what is selected -- AND AT THE PRICE THAT IS
          SELECTED. The note used to be the singular constant under every metered notch, so a Cascade
          selection read "two credits" in the hint and "a credit" one line below it. */}
      {isMetered(choice) && !credits.dark && (
        <p data-testid="credits-charge-note" className="font-sans text-11 leading-snug text-text-faint">
          {chargeNoteFor(CHOICE_COST[choice] ?? 0)}
        </p>
      )}

      {/* Why a notch is unreachable -- always rendered, never behind focus or a hover. The label prefix is
          dropped when the reason already opens with it, so a deployment-gate line reads as the sentence it
          is ("Cascade is not yet enabled on this deployment") rather than stuttering the tier's name. */}
      {CHOICES.filter(blocked).map((c) => {
        const why = blockedReason(c);
        const label = CHOICE_COPY[c].label;
        return (
          <p
            key={c}
            data-testid={`depth-blocked-${c}`}
            className="font-sans text-11 leading-snug text-amber"
          >
            {why.startsWith(label) ? why : `${label}: ${why}`}
          </p>
        );
      })}
    </div>
  );
}
