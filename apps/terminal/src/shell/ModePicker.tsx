import { useEffect, useRef, useState } from 'react';
import { DEFAULT_MODE, MODE_COPY, MODES, useMode, type ModeName } from '@/store/mode';

/**
 * D-AM-14 — the reasoning-mode selector, DOCKED AT THE ASK BAR.
 *
 * Deliberately NOT a settings toggle (user amendment). Depth is a per-question decision — "is this the
 * one worth 2-3x the wait?" is asked while typing the question, not once in a preferences dialog — so the
 * control lives where the question is written, in the smallest footprint that can still say what it does:
 * a chip that reads `▃ standard ▾`, opening a three-row menu with the time expectation on each row.
 *
 * The hints are STATIC v1 copy and deliberately RELATIVE ("faster", "~2-3x slower"). Per-mode p50s exist
 * only once stage-1 traffic has run through the EMF `mode` dimension; a precise number here before then
 * would be a measurement nobody made.
 *
 * Keyboard: the trigger is an ordinary button (Enter/Space opens, ArrowDown opens onto the list).
 * Inside, the three rows are `menuitemradio`s with roving focus — Up/Down/Home/End move, Enter/Space
 * choose, Escape closes and returns focus to the trigger. Choosing returns focus to the trigger too, so a
 * keyboard user lands one Shift+Tab from the textarea they came out of.
 *
 * Disabled while a turn streams, for the same reason the textarea is: the mode that governs a turn is the
 * one that was on screen at submit, and a control that moves mid-turn would imply otherwise.
 */

/** A depth ramp, so the control reads as a LEVEL before the label is read at all. */
const GLYPH: Record<ModeName, string> = { quick: '▁', standard: '▃', deep: '▆' };

export function ModePicker({ disabled = false }: { disabled?: boolean }) {
  const mode = useMode((s) => s.mode);
  const setMode = useMode((s) => s.setMode);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

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

  const choose = (m: ModeName) => {
    setMode(m);
    close(true);
  };

  const move = (delta: number) => {
    const els = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])];
    if (!els.length) return;
    const i = els.indexOf(document.activeElement as HTMLElement);
    // -1 (focus is elsewhere) + delta 1 lands on 0 -- the first row -- which is what ArrowDown should do.
    els[(i + delta + els.length) % els.length]?.focus();
  };

  const label = `reasoning mode: ${mode}`;

  return (
    <div className="relative" ref={wrapRef} data-testid="mode-picker">
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={`${label} — ${MODE_COPY[mode].time}, ${MODE_COPY[mode].detail}`}
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
        <span aria-hidden="true" className={mode === DEFAULT_MODE ? 'text-text-faint' : 'text-cyan'}>
          {GLYPH[mode]}
        </span>
        <span>{mode}</span>
        <span aria-hidden="true" className="text-text-faint">
          ▾
        </span>
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label="reasoning mode"
          data-testid="mode-menu"
          // The composer is docked at the BOTTOM of the shell, so the menu opens UPWARD.
          className="absolute bottom-full left-0 z-30 mb-1 w-64 rounded-panel border border-line bg-bg-1 p-1 shadow-lg"
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
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              role="menuitemradio"
              aria-checked={m === mode}
              data-testid={`mode-option-${m}`}
              onClick={() => choose(m)}
              className={`block w-full rounded-chip px-2 py-1 text-left hover:bg-bg-2 ${
                m === mode ? 'text-text' : 'text-text-dim'
              }`}
            >
              <span className="flex items-baseline gap-1.5 font-mono text-12">
                <span aria-hidden="true" className={m === mode ? 'text-cyan' : 'text-text-faint'}>
                  {GLYPH[m]}
                </span>
                <span>{m}</span>
                <span className="ml-auto text-11 text-text-faint">{MODE_COPY[m].time}</span>
              </span>
              <span className="mt-0.5 block font-sans text-11 leading-snug text-text-faint">
                {MODE_COPY[m].detail}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
