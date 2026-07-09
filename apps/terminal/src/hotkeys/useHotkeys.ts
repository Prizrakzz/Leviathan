import { useEffect, useRef } from 'react';

/**
 * The terminal hotkey system (design §3.3). Keyboard-first: mouse is supported but never required.
 * Global combos (⌘K, ⌘↵, ⌘\, Esc) fire even while typing; single-key bindings are suppressed inside inputs
 * so the command bar is usable. `,`/`.` (the keys under `‹ ›`) step the as-of; Shift = a larger jump. (The
 * `g` view-switch leader was retired in the 5.6 view-prune — Answer is now the only view.)
 */
export interface HotkeyHandlers {
  onPalette?: () => void;
  onSubmit?: () => void;
  onToggleThread?: () => void;
  onEscape?: () => void;
  onAsOfStep?: (dir: -1 | 1, large: boolean) => void;
  onPanel?: (n: number) => void;
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
      if (mod && e.key.toLowerCase() === 'k') return void (e.preventDefault(), H.onPalette?.());
      if (mod && e.key === 'Enter') return void (e.preventDefault(), H.onSubmit?.());
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
        default:
          if (/^[1-4]$/.test(e.key)) return void (e.preventDefault(), H.onPanel?.(Number(e.key)));
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
}
