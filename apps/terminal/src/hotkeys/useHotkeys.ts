import { useEffect, useRef } from 'react';

/**
 * The terminal hotkey system (design §3.3). Keyboard-first: mouse is supported but never required.
 * Global combos (⌘\, Esc) fire even while typing; ⌘↵ and every single-key binding are suppressed inside
 * inputs so the command bar is usable. `,`/`.` (the keys under `‹ ›`) step the as-of; Shift = a larger jump.
 * (The `g` view-switch leader was retired in the 5.6 view-prune — Answer is now the only view. ⌘K went with
 * the empty palette in D-TW-14b, and `1`-`4` with `focusedPanel` in D-TW-15 — it moved a store field
 * nothing read, so the keys did nothing observable.)
 */
export interface HotkeyHandlers {
  onSubmit?: () => void;
  onToggleThread?: () => void;
  onEscape?: () => void;
  onAsOfStep?: (dir: -1 | 1, large: boolean) => void;
  onHelp?: () => void;
  onCopy?: () => void;
  onReceipts?: () => void;
}

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el || typeof el.tagName !== 'string') return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable === true;
}

export function useHotkeys(handlers: HotkeyHandlers): void {
  const h = useRef(handlers);
  h.current = handlers;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      const H = h.current;

      // Global combos — active everywhere, including inside the command bar.
      // D-TW-5(b): ⌘↵ submits the COMMAND BAR, so it must not fire from another text surface. Every one
      // of them already owns Enter (the command bar, the composer, the thread-rename box), which made
      // ⌘↵ inside the composer send TWO different questions from one keystroke. Outside a text field it
      // keeps its job: submit whatever the command bar holds (a bell/watch-chip prefill, say).
      if (mod && e.key === 'Enter') {
        if (isTyping(e.target)) return; // the focused field owns Enter -- let it handle this
        return void (e.preventDefault(), H.onSubmit?.());
      }
      if (mod && e.key === '\\') return void (e.preventDefault(), H.onToggleThread?.());
      if (e.key === 'Escape') return void H.onEscape?.();
      if (mod) return; // leave other mod-combos to the browser
      if (isTyping(e.target)) return; // never hijack typing

      switch (e.key) {
        case ',':
          return void (e.preventDefault(), H.onAsOfStep?.(-1, e.shiftKey));
        case '<':
          return void (e.preventDefault(), H.onAsOfStep?.(-1, true));
        case '.':
          return void (e.preventDefault(), H.onAsOfStep?.(1, e.shiftKey));
        case '>':
          return void (e.preventDefault(), H.onAsOfStep?.(1, true));
        case '?':
          return void (e.preventDefault(), H.onHelp?.());
        case 'y':
          return void H.onCopy?.();
        case 'e':
          return void H.onReceipts?.();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
}
