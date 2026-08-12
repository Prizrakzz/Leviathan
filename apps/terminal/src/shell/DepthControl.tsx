import { useQuery } from '@tanstack/react-query';
import { DOSSIER_QUOTA_KEY, getDossierQuota } from '@/api/dossier';
import { useCredits } from '@/api/useCredits';
import { utcDay } from '@/lib/time';
import {
  CHOICE_COPY,
  CHOICES,
  isMetered,
  useMode,
  type PickerChoice,
} from '@/store/mode';
import { useSession } from '@/store/session';
import { CHARGE_NOTE, CreditsBadge } from './CreditsBadge';

/**
 * D-MW-21 — the ask bar's DEPTH CONTROL (the D-DR-3 ModePicker, re-shaped).
 *
 * A NOTCHED SLIDER, not a menu, because the thing being chosen is now a RAMP: Scan -> Analysis ->
 * Deep Research is one axis with three stops, and a drop-down hides that ordering behind a click. The
 * control shows every stop at once, marks where you are on it, and reads its state out loud as a slider
 * (`role="slider"`, `aria-valuetext` = the tier label, never the internal identifier).
 *
 * THE TWO INVARIANTS CARRIED FORWARD FROM D-DR-3, unchanged:
 *  - Deep Research is the TOP notch and stays a different SUBMIT ROUTE — a dossier is a JOB, not a mode
 *    (Shell's branch, not this control's). Selecting it does not make the ask deeper; it makes the ask
 *    something else.
 *  - The control lives at the ASK BAR (the recorded depth-is-per-question amendment) and goes inert while
 *    a turn streams, for the same reason the textarea does: the selection that governs a submit is the one
 *    that was on screen at submit, and a control that moves mid-turn would imply otherwise.
 *
 * KEYBOARD, and the one judgement call in it: the slider owns the a11y contract (Left/Down step shallower,
 * Right/Up step deeper, Home/End jump to the ends) and the notches are POINTER affordances — `aria-hidden`,
 * `tabIndex={-1}` — so a screen reader hears one control with one value rather than three buttons and a
 * slider claiming to be the same thing. Stepping SKIPS an unavailable notch instead of stalling on it: with
 * Analysis out of credits, ArrowRight from Scan must still reach Deep Research. Nothing is hidden by that
 * skip, because the reason a notch was skipped is written under the control (`depth-blocked-*`) whether or
 * not it has focus — which is also how the reset date stays readable without the old menu's focusable-but-
 * unchoosable row trick.
 *
 * The hints are STATIC copy and deliberately RELATIVE ("one turn", "a longer turn", "minutes"). Per-mode
 * p50s exist only once the EMF `mode` dimension has traffic; a precise number here before then is a
 * measurement nobody made. The two BADGES are the exception and are not copy at all — they are the server's
 * own counts, from two SEPARATE meters: credits (monthly grant, spent by Analysis) and the dossier
 * allowance (4/month, spent by Deep Research). A credit does not buy a dossier and a dossier does not
 * spend a credit.
 */

/** A depth ramp, so the control reads as a LEVEL before any label is read at all. */
const GLYPH: Record<PickerChoice, string> = { quick: '▃', deep: '▅', deep_research: '▇' };

export function DepthControl({ disabled = false }: { disabled?: boolean }) {
  const choice = useMode((s) => s.choice);
  const setChoice = useMode((s) => s.setChoice);
  const ready = useSession((s) => s.ready);

  // The dossier's monthly allowance (D-DR-2b). ONE query key (api/dossier.DOSSIER_QUOTA_KEY) is shared with
  // the submit path, which invalidates it after every submission -- so the badge can never promise a run the
  // server just spent or refused. `null` data (not an error) is the DARK case: GRAPHRAG_DOSSIER absent -> 404.
  const quotaQ = useQuery({
    queryKey: DOSSIER_QUOTA_KEY,
    queryFn: getDossierQuota,
    enabled: ready,
    staleTime: 30_000,
  });
  const quota = quotaQ.data ?? null;
  const dossierDark = quotaQ.isSuccess && quota === null;
  const dossierGone = !!quota && quota.remaining <= 0;

  // The credit grant (D-MW-25). Same shape, same rules, different meter.
  const credits = useCredits();

  /** Why a notch cannot be chosen right now, or '' when it can. The refusal reason is the copy that wins. */
  const blockedReason = (c: PickerChoice): string => {
    if (c === 'deep_research') {
      if (dossierDark) return 'not enabled on this deployment';
      if (dossierGone) {
        const day = utcDay(quota?.reset_at);
        return day ? `none left — the allowance resets ${day} (UTC)` : 'none left this month';
      }
      return '';
    }
    // A metered ask notch is blocked only by a REAL exhausted balance. Metering dark, or a balance we could
    // not read, leaves it selectable: the same fail-open posture the server takes.
    if (isMetered(c) && credits.exhausted) {
      const day = utcDay(credits.balance?.reset_at);
      return day ? `no credits left — the grant resets ${day} (UTC)` : 'no credits left this month';
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
          // Refetch BOTH balances when the control takes focus: this is the moment the numbers are about to
          // be acted on, and a cached "97 of 100" on a page left open overnight is the lie they exist to
          // prevent. (The old menu did this on open; a slider has no open.)
          onFocus={() => {
            void quotaQ.refetch();
            credits.refetch();
          }}
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

        {/* Two meters, two badges, never merged. */}
        {choice === 'deep_research' && quota && (
          <span
            data-testid="dossier-quota-badge"
            className={`rounded-chip border px-1 font-mono text-11 ${
              dossierGone ? 'border-neg text-neg' : 'border-line text-text-faint'
            }`}
          >
            {quota.remaining} of {quota.limit} this month
          </span>
        )}
        <CreditsBadge />
      </div>

      <p data-testid="depth-hint" className="mt-0.5 font-sans text-11 leading-snug text-text-faint">
        {copy.detail}
      </p>

      {/* The charge trade, on screen exactly when it applies to what is selected. */}
      {isMetered(choice) && !credits.dark && (
        <p data-testid="credits-charge-note" className="font-sans text-11 leading-snug text-text-faint">
          {CHARGE_NOTE}
        </p>
      )}

      {/* Why a notch is unreachable -- always rendered, never behind focus or a hover. */}
      {CHOICES.filter(blocked).map((c) => (
        <p
          key={c}
          data-testid={`depth-blocked-${c}`}
          className="font-sans text-11 leading-snug text-amber"
        >
          {CHOICE_COPY[c].label}: {blockedReason(c)}
        </p>
      ))}
    </div>
  );
}
