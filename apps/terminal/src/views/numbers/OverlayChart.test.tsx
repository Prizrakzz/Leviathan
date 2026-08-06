import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { OverlayLeg } from './chartTriggers';
import { OverlayChart } from './OverlayChart';

const pt = (period: string, value: number) => ({ period, value, knowledge_date: '', contract_month: '' });

const A: OverlayLeg = {
  label: 'soybean oil cbot',
  unit: '%',
  points: [pt('MY2018', 14.8), pt('MY2019', 13.0), pt('MY2020', 11.2)],
};
const B: OverlayLeg = {
  label: 'malaysian crude palm oil cme',
  unit: '%',
  points: [pt('MY2018', 12.1), pt('MY2020', 9.4)],
};

/** Tick labels of the overlay's own svg (the @visx/text measuring scratch node is document-wide). */
const ticks = () =>
  [...screen.getByRole('img', { name: /overlay/ }).querySelectorAll('text')].map((t) => t.textContent);

describe('OverlayChart (D-UX-3, the one new primitive)', () => {
  // Every svg query below is scoped to the render's own container: @visx/text measures strings by
  // appending a throwaway svg to the DOCUMENT, so a document-wide selector picks that scratch node up.
  it('draws BOTH legs in ONE svg, on ONE shared y domain', () => {
    const { container } = render(<OverlayChart legs={[A, B]} window="MY2018-MY2020" />);
    expect(screen.getAllByRole('img')).toHaveLength(1); // one picture, not two stacked charts
    expect(container.querySelectorAll('svg path[class*="stroke-"]')).toHaveLength(2);
    expect(container.querySelectorAll('svg circle')).toHaveLength(5); // 3 + 2 points
  });

  it('names both legs, their shared unit and the window', () => {
    render(<OverlayChart legs={[A, B]} window="MY2018-MY2020" />);
    const card = screen.getByTestId('overlay-chart');
    expect(card.textContent).toContain('soybean oil cbot');
    expect(card.textContent).toContain('malaysian crude palm oil cme');
    expect(card.textContent).toContain('%');
    expect(card.textContent).toContain('MY2018-MY2020');
  });

  it('domains x on the UNION of the legs, so a leg with an extra era keeps it', () => {
    // The legs are index-aligned eras on each commodity's OWN marketing year, so they can carry different
    // labels; intersecting would silently shorten a leg the answer quoted in full.
    render(<OverlayChart legs={[A, B]} />);
    expect(ticks()).toEqual(['MY2018', 'MY2019', 'MY2020']);
  });

  it('REFUSES mixed units with a plain note instead of a second y axis', () => {
    // A dual axis is how a correlation gets manufactured: the two scales are pinned independently, so the
    // apparent co-movement is an artifact of the pinning, not of the data.
    const { container } = render(<OverlayChart legs={[A, { ...B, unit: 'kt' }]} />);
    expect(screen.getByTestId('overlay-mixed-units').textContent).toContain('different units');
    expect(screen.queryByRole('img')).toBeNull();
    expect(container.querySelectorAll('svg')).toHaveLength(0);
  });

  it('draws nothing when a leg is too short to be a line', () => {
    const { container } = render(<OverlayChart legs={[A, { ...B, points: [pt('MY2018', 12.1)] }]} />);
    expect(container.innerHTML).toBe('');
  });
});
