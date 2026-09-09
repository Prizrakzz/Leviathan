import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { seriesChip, toContext } from '@/store/chips';
import { useUI } from '@/store/ui';
import { AttachedChips } from './AttachedChips';

/** The composer's context row (Composer.tsx mounts exactly this, above the ask box). Rendered directly:
 *  it reads the store rather than taking props, so this IS what the composer shows. */
const LOC = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'corn_cbot',
  contract_month: '2026-12',
};

describe('D-UX-4 — an attached chart is visible in the composer, and removable', () => {
  beforeEach(() => useUI.getState().clearChips());

  it('renders nothing at all when nothing is attached', () => {
    const { container } = render(<AttachedChips />);
    expect(container.innerHTML).toBe('');
  });

  it('shows the attached chart by name, under its own kind glyph', () => {
    useUI.getState().addChip(seriesChip({ ...LOC, label: 'corn cbot settle curve' }));
    render(<AttachedChips />);
    const row = screen.getByTestId('attached-chips');
    expect(row.textContent).toContain('corn cbot settle curve');
    // ∿ is the series glyph: without it an attached CHART wore the node diamond and read as a graph
    // gesture, and the tray's only way to tell the four attachment kinds apart is this character.
    expect(row.textContent).toContain('∿');
  });

  it('detaching clears it — from the row and from the wire array the next turn would carry', async () => {
    useUI.getState().addChip(seriesChip({ ...LOC, label: 'corn cbot settle curve' }));
    render(<AttachedChips />);
    expect(toContext(useUI.getState().attachedChips)).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: /remove corn cbot settle curve/i }));
    expect(useUI.getState().attachedChips).toHaveLength(0);
    expect(toContext(useUI.getState().attachedChips)).toEqual([]);
    expect(screen.queryByTestId('attached-chips')).toBeNull();
  });
});
