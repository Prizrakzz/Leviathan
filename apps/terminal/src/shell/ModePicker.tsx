import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { DOSSIER_QUOTA_KEY, getDossierQuota } from '@/api/dossier';
import { utcDay } from '@/lib/time';
import { CHOICE_COPY, CHOICES, DEFAULT_CHOICE, useMode, type PickerChoice } from '@/store/mode';
import { useSession } from '@/store/session';

/**
 * D-AM-14 / D-DR-3 — the ask-bar selector, now TWO entries.
 *
 * Deliberately NOT a settings toggle (user amendment). Depth is a per-question decision — "is this the one
 * worth minutes and one of four monthly runs?" is asked while typing the question, not once in a preferences
 * dialog — so the control lives where the question is written, in the smallest footprint that can still say
 * what it does: a chip that reads `▃ Standard ▾`, opening a two-row menu.
 *
 * D-DR-3 collapsed three modes to two entries, and the second one is NOT a mode. **Standard** is the label
 * for the `quick` preset (the FE sends `mode=quick`; see store/mode.ASK_MODE). **Deep Research** switches
 * the composer's submit into a dossier JOB — a different route, a different result, a monthly allowance. So
 * the second row carries a BADGE ("2 of 4 this month") and goes un-choosable at zero with the reset date in
 * its hint: a control that spends a scarce, monthly-replenished resource has to show the balance before the
 * click, not after it.
 *
 * The hints are STATIC copy and deliberately RELATIVE ("one turn", "minutes"). Per-mode p50s exist only once
 * the EMF `mode` dimension has traffic; a precise number here before then is a measurement nobody made. The
 * BADGE is the exception and is not copy at all — it is the server's own count.
 *
 * Keyboard (D-AM-14, preserved verbatim): the trigger is an ordinary button (Enter/Space opens, ArrowDown
 * opens onto the list). Inside, the rows are `menuitemradio`s with roving focus — Up/Down/Home/End move,
 * Enter/Space choose, Escape closes and returns focus to the trigger. An unavailable row is `aria-disabled`
 * rather than `disabled` ON PURPOSE: a disabled button cannot take focus, so arrowing onto it would silently
 * stall, and its hint — the one place the reset date is written — would be unreachable by keyboard.
 *
 * Disabled while a turn streams, for the same reason the textarea is: the selection that governs a submit is
 * the one that was on screen at submit, and a control that moves mid-turn would imply otherwise.
 */

/** A depth ramp, so the control reads as a LEVEL before the label is read at all. */
const GLYPH: Record<PickerChoice, string> = { quick: '▃', deep_research: '▆' };

export function ModePicker({ disabled = false }: { disabled?: boolean }) {
  const choice = useMode((s) => s.choice);
  const setChoice = useMode((s) => s.setChoice);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // The monthly allowance (D-DR-2b). ONE query key (api/useDossier.DOSSIER_QUOTA_KEY) is shared with the submit path,
  // which invalidates it after every submission — so the badge can never promise a run the server just
  // spent or refused. `null` data (not an error) is the DARK case: GRAPHRAG_DOSSIER absent -> 404.
  const ready = useSession((s) => s.ready);
  const quotaQ = useQuery({
    queryKey: DOSSIER_QUOTA_KEY,
    queryFn: getDossierQuota,
    enabled: ready,
    staleTime: 30_000,
  });
  const quota = quotaQ.data ?? null;
  const dossierDark = quotaQ.isSuccess && quota === null;
  const exhausted = !!quota && quota.remaining <= 0;
  const unavailable = (c: PickerChoice) => c === 'deep_research' && (dossierDark || exhausted);

  // Opening REFETCHES the balance: the menu is the one moment the number is being read, and a stale
  // cached "4 of 4" on a page left open overnight is exactly the lie this badge exists to prevent.
  const refetch = quotaQ.refetch;
  useEffect(() => {
    if (open) void refetch();
  }, [open, refetch]);

  // Click-outside closes (the UserMenu idiom -- one anchored-popover behaviour in this app, not two).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  // A turn starting closes the menu -- it is about to be inert, and an open inert menu is a lie.
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  // Opening moves focus INTO the list, onto the current choice: the keyboard entry point is the state the
  // user is in, so Up/Down is a relative move rather than a hunt.
  useEffect(() => {
    if (open) menuRef.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus();
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) btnRef.current?.focus();
  };

  const pick = (c: PickerChoice) => {
    if (unavailable(c)) return; // the row stays focusable so its hint can be read; it just cannot be chosen
    setChoice(c);
    close(true);
  };

  const move = (delta: number) => {
    const els = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])];
    if (!els.length) return;
    const i = els.indexOf(document.activeElement as HTMLElement);
    // -1 (focus is elsewhere) + delta 1 lands on 0 -- the first row -- which is what ArrowDown should do.
    els[(i + delta + els.length) % els.length]?.focus();
  };

  /** The badge text, or '' when there is no measured number to show. Never invents a balance. */
  const badge = quota ? `${quota.remaining} of ${quota.limit} this month` : '';

  /** What the Deep Research row says under its title: the refusal reason wins over the description. */
  const hintFor = (c: PickerChoice) => {
    if (c !== 'deep_research') return CHOICE_COPY[c].detail;
    if (dossierDark) return 'not enabled on this deployment';
    if (exhausted) {
      const day = utcDay(quota?.reset_at);
      return day ? `none left — the allowance resets ${day} (UTC)` : 'none left this month';
    }
    return CHOICE_COPY[c].detail;
  };

  const label = `research mode: ${CHOICE_COPY[choice].label}`;

  return (
    <div className="relative" ref={wrapRef} data-testid="mode-picker">
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={`${label} — ${CHOICE_COPY[choice].time}, ${CHOICE_COPY[choice].detail}`}
        data-testid="mode-trigger"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className="flex items-center gap-1 rounded-chip border border-line px-1.5 py-0.5 font-mono text-11 text-text-dim hover:border-cyan hover:text-cyan disabled:opacity-40"
      >
        <span aria-hidden="true" className={choice === DEFAULT_CHOICE ? 'text-text-faint' : 'text-cyan'}>
          {GLYPH[choice]}
        </span>
        <span>{CHOICE_COPY[choice].label}</span>
        <span aria-hidden="true" className="text-text-faint">
          ▾
        </span>
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label="research mode"
          data-testid="mode-menu"
          // The composer is docked at the BOTTOM of the shell, so the menu opens UPWARD.
          className="absolute bottom-full left-0 z-30 mb-1 w-72 rounded-panel border border-line bg-bg-1 p-1 shadow-lg"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              close(true);
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              move(1);
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              move(-1);
            } else if (e.key === 'Home' || e.key === 'End') {
              e.preventDefault();
              const els = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])];
              (e.key === 'Home' ? els[0] : els[els.length - 1])?.focus();
            } else if (e.key === 'Tab') {
              close(false); // Tab leaves the control entirely; do not yank focus back to the trigger
            }
          }}
        >
          {CHOICES.map((c) => {
            const off = unavailable(c);
            return (
              <button
                key={c}
                type="button"
                role="menuitemradio"
                aria-checked={c === choice}
                aria-disabled={off || undefined}
                data-testid={`mode-option-${c}`}
                onClick={() => pick(c)}
                className={`block w-full rounded-chip px-2 py-1 text-left hover:bg-bg-2 ${
                  off ? 'opacity-50' : ''
                } ${c === choice ? 'text-text' : 'text-text-dim'}`}
              >
                <span className="flex items-baseline gap-1.5 font-mono text-12">
                  <span aria-hidden="true" className={c === choice ? 'text-cyan' : 'text-text-faint'}>
                    {GLYPH[c]}
                  </span>
                  <span>{CHOICE_COPY[c].label}</span>
                  {c === 'deep_research' && badge && (
                    <span
                      data-testid="dossier-quota-badge"
                      className={`rounded-chip border px-1 text-11 ${
                        exhausted ? 'border-neg text-neg' : 'border-line text-text-faint'
                      }`}
                    >
                      {badge}
                    </span>
                  )}
                  <span className="ml-auto text-11 text-text-faint">{CHOICE_COPY[c].time}</span>
                </span>
                <span
                  data-testid={`mode-hint-${c}`}
                  className="mt-0.5 block font-sans text-11 leading-snug text-text-faint"
                >
                  {hintFor(c)}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
