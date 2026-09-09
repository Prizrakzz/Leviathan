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

/** BOTTOM-axis tick labels of the overlay's own svg (the @visx/text measuring scratch node is
 *  document-wide; and since D-UX-5 the overlay draws a left axis whose labels share the `text` tag). */
const ticks = () =>
  [...screen.getByRole('img', { name: /overlay/ }).querySelectorAll('.visx-axis-bottom text')].map(
    (t) => t.textContent,
  );

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

describe('OverlayChart D-UX-5 — two legs stay two legs, and the shared domain gets an axis', () => {
  it('draws the legs in TWO DIFFERENT inks, neither of them the swappable accent', () => {
    // Under `accent: 'amber'` the `--cyan` var resolves to `--amber`, i.e. leg A's colour -- so a leg drawn
    // with `stroke-cyan` became invisible against the other leg for any reader on the amber terminal.
    const { container } = render(<OverlayChart legs={[A, B]} />);
    const strokes = [...container.querySelectorAll('svg path[class*="stroke-"]')].map((p) =>
      p.getAttribute('class'),
    );
    expect(strokes).toEqual(['visx-linepath stroke-amber', 'visx-linepath stroke-series-b']);
    expect(container.querySelectorAll('.stroke-cyan, .fill-cyan, .text-cyan')).toHaveLength(0);
  });

  it('the legend swatch is the SAME token as the stroke it explains', () => {
    const { container } = render(<OverlayChart legs={[A, B]} />);
    const swatches = [...container.querySelectorAll('span[class*="text-"]')].map((s) =>
      s.getAttribute('class'),
    );
    expect(swatches).toContain('text-amber');
    expect(swatches).toContain('text-series-b');
  });

  it('states the magnitudes once, on the ONE shared y domain the refusal above buys', () => {
    // Both legs share one scale by construction (mixed units are refused, not dual-axised), so a single
    // left axis is the only honest one -- and it is what makes "these two moved together" readable.
    render(<OverlayChart legs={[A, B]} />);
    const svg = screen.getByRole('img', { name: /overlay/ });
    expect(svg.querySelectorAll('.visx-axis-left').length).toBe(1);
    expect([...svg.querySelectorAll('.visx-axis-left text')].length).toBeGreaterThan(0);
  });
});
