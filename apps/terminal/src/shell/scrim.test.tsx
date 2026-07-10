import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { OVERLAY_SCRIM } from '@/tokens/tokens';
import { CommandPalette } from './CommandPalette';
import { ShortcutSheet } from './ShortcutSheet';

// cmdk observes its list element on mount; jsdom has no ResizeObserver (vitest.setup leaves it out
// because app code guards on it) -- stub it per-file, the CascadeFlow test convention.
beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

/** P9-E2: every full-screen overlay dims through the ONE shared scrim constant — the hand-rolled
 *  surfaces are asserted here; the Radix Dialog.Overlay sites are asserted in their own modal tests. */
describe('overlay scrim consistency (P9-E2)', () => {
  it('the shortcut sheet backdrop carries OVERLAY_SCRIM', () => {
    render(<ShortcutSheet onClose={() => {}} />);
    expect(screen.getByTestId('shortcuts').className).toContain(OVERLAY_SCRIM);
  });

  it('the command palette backdrop carries OVERLAY_SCRIM', () => {
    render(<CommandPalette open onClose={() => {}} />);
    expect(screen.getByTestId('palette').className).toContain(OVERLAY_SCRIM);
  });
});
