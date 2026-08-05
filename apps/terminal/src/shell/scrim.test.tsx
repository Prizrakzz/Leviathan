import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { OVERLAY_SCRIM } from '@/tokens/tokens';
import { ShortcutSheet } from './ShortcutSheet';

/** P9-E2: every full-screen overlay dims through the ONE shared scrim constant — the hand-rolled
 *  surfaces are asserted here; the Radix Dialog.Overlay sites are asserted in their own modal tests.
 *  (D-TW-14b: the command palette was the other hand-rolled surface; it and its cmdk-driven
 *  ResizeObserver stub left with it.) */
describe('overlay scrim consistency (P9-E2)', () => {
  it('the shortcut sheet backdrop carries OVERLAY_SCRIM', () => {
    render(<ShortcutSheet onClose={() => {}} />);
    expect(screen.getByTestId('shortcuts').className).toContain(OVERLAY_SCRIM);
  });

  it('D-TW-14b/15: the sheet lists no binding the hotkey system dropped', () => {
    render(<ShortcutSheet onClose={() => {}} />);
    const sheet = screen.getByTestId('shortcuts');
    expect(sheet.textContent).not.toContain('⌘K'); // the palette is gone
    expect(sheet.textContent).not.toContain('1–4'); // focusedPanel is gone
    expect(sheet.textContent).not.toContain('g a'); // the view leader was retired in 5.6
    expect(sheet.textContent).toContain('⌘↵'); // the surviving bindings still render
  });
});
