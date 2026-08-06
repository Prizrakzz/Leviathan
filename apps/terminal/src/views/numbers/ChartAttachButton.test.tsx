import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { MAX_ATTACH, chipKey, seriesChip, toContext } from '@/store/chips';
import { useUI } from '@/store/ui';
import type { ChartLocator } from './chartTriggers';
import { ChartAttachButton } from './ChartAttachButton';

const LOC: ChartLocator = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'corn_cbot',
  contract_month: '2026-12',
  axis: 'curve',
  asof: '2026-06-08',
};

describe('D-UX-4 seriesChip — the attachment is a LOCATOR, never data', () => {
  beforeEach(() => useUI.getState().clearChips());

  it('drops axis and asof: steering carries no vintage and no drawing mode', () => {
    const chip = seriesChip({ ...LOC, label: 'corn settle curve' });
    expect(chip).toEqual({
      type: 'series',
      table: 'silver_futures_eod',
      metric: 'settle',
      commodity: 'corn_cbot',
      contract_month: '2026-12',
      label: 'corn settle curve',
    });
    expect(chip).not.toHaveProperty('asof'); // the NEXT turn's as-of governs the re-read
    expect(chip).not.toHaveProperty('axis');
    expect(chip).not.toHaveProperty('points');
  });

  it('omits absent optional dimensions instead of sending undefined', () => {
    const chip = seriesChip({ table: 'silver_oni', metric: 'oni' });
    expect(Object.keys(chip).sort()).toEqual(['label', 'metric', 'table', 'type']);
    expect(chip.label).toBe('oni'); // derived label when the caller gives none
  });

  it('the wire array carries the series attachment with no display-only fields', () => {
    useUI.getState().addChip(seriesChip(LOC));
    expect(toContext(useUI.getState().attachedChips)).toEqual([
      {
        type: 'series',
        table: 'silver_futures_eod',
        metric: 'settle',
        commodity: 'corn_cbot',
        contract_month: '2026-12',
      },
    ]);
  });

  it('every locator field rides the dedupe key (two months are two attachments)', () => {
    useUI.getState().addChip(seriesChip(LOC));
    useUI.getState().addChip(seriesChip(LOC)); // same locator -> dedupe
    expect(useUI.getState().attachedChips).toHaveLength(1);
    useUI.getState().addChip(seriesChip({ ...LOC, contract_month: '2027-03' }));
    useUI.getState().addChip(seriesChip({ ...LOC, country: 'BR' }));
    expect(useUI.getState().attachedChips).toHaveLength(3);
    expect(chipKey(seriesChip(LOC))).not.toBe(chipKey(seriesChip({ ...LOC, country: 'BR' })));
  });

  it('a thread switch clears an attached chart (the thread is the context boundary)', async () => {
    useUI.getState().addChip(seriesChip(LOC));
    const { useThread } = await import('@/store/thread');
    useThread.getState().newThread();
    expect(useUI.getState().attachedChips).toHaveLength(0);
  });
});

describe('D-UX-4 ChartAttachButton — the leaf action', () => {
  beforeEach(() => useUI.getState().clearChips());

  it('attaches the locator on click and then reports itself attached', async () => {
    render(<ChartAttachButton locator={LOC} />);
    const btn = screen.getByTestId('chart-attach');
    expect(btn).toHaveAttribute('data-attached', 'no');
    await userEvent.click(btn);
    expect(useUI.getState().attachedChips).toHaveLength(1);
    expect(screen.getByTestId('chart-attach')).toHaveAttribute('data-attached', 'yes');
    expect(screen.getByTestId('chart-attach')).toBeDisabled(); // idempotent: no second identical chip
  });

  it('says the context is full rather than silently no-opping at the cap', async () => {
    for (let i = 0; i < MAX_ATTACH; i++) {
      useUI.getState().addChip(seriesChip({ table: 't', metric: 'm', country: `C${i}` }));
    }
    render(<ChartAttachButton locator={LOC} />);
    const btn = screen.getByTestId('chart-attach');
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent('context full');
    await userEvent.click(btn);
    expect(useUI.getState().attachedChips).toHaveLength(MAX_ATTACH);
  });

  it('is a leaf: it renders one button and owns no chart state', () => {
    const { container } = render(<ChartAttachButton locator={LOC} />);
    expect(container.querySelectorAll('button')).toHaveLength(1);
    expect(screen.getByTestId('chart-attach')).toHaveAccessibleName(/attach .* to the next question/i);
  });
});
