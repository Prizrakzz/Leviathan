import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const galleryMock = vi.fn();
vi.mock('@/api/client', () => ({ getGallery: () => galleryMock() }));

import { EmptyState, pickStarters } from './EmptyState';
import type { GalleryItem } from '@/api/schema';

const item = (id: string, category: string, question: string, filled = true): GalleryItem => ({
  id,
  category,
  question,
  rc_target: 'default',
  filled,
});

// One row per category plus a SECOND convergence row, mirroring the shape gallery.yaml ships (12 rows over
// 7 categories) so the clamp is exercised against real proportions rather than a toy list.
const CONV_1 = item('conv_1', 'convergence', 'How close is the frost squeeze regime in coffee to firing right now?');
const CONV_2 = item('conv_2', 'convergence', 'The ethanol diversion regime in sugar is short of its threshold?');
const CROSS_1 = item('cross_1', 'cross_commodity', 'Compare palm oil and soybean oil?');
const CASCADE_1 = item('cascade_1', 'cascade', 'Walk me through the cascade in corn.');
const VERIFY_1 = item('verify_1', 'verification', 'Stocks in corn are the tightest in a decade, right?');
const RANK_1 = item('rank_1', 'ranking', 'Rank the largest exporters of sugar.');
const HORIZON_1 = item('horizon_1', 'horizon', 'What should I watch over weeks, months, and quarters in corn?');
const RECENCY_1 = item('recency_1', 'recency', 'What has changed in corn over the past 30 days?');
const ITEMS: GalleryItem[] = [CONV_1, CONV_2, CROSS_1, CASCADE_1, VERIFY_1, RANK_1, HORIZON_1, RECENCY_1];

function mount(onAsk: (q: string) => void = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EmptyState onAsk={onAsk} />
    </QueryClientProvider>,
  );
}

describe('EmptyState prompt gallery (D-AM-16)', () => {
  it('renders the filled gallery entries grouped under their category headings', async () => {
    galleryMock.mockResolvedValue({ items: ITEMS });
    mount();
    await waitFor(() => expect(screen.getByTestId('prompt-gallery')).toBeTruthy());
    // categories are headings, questions are the chips
    expect(screen.getByText('cross commodity')).toBeTruthy(); // underscores are display-stripped
    expect(screen.getByText('convergence')).toBeTruthy();
    expect(screen.getByText(CONV_1.question)).toBeTruthy();
    expect(screen.getByText(RECENCY_1.question)).toBeTruthy();
  });

  it('asks the FILLED question verbatim on click (the chip text is the query)', async () => {
    const onAsk = vi.fn();
    galleryMock.mockResolvedValue({ items: ITEMS });
    mount(onAsk);
    const chip = await screen.findByText(VERIFY_1.question);
    await userEvent.click(chip);
    expect(onAsk).toHaveBeenCalledWith(VERIFY_1.question);
  });

  it('never offers an unfilled template as a one-click starter', async () => {
    // Cold catalog: the server still returns the templates (the wire stays legible) but a click would fire a
    // turn on a literal `{contract}` placeholder, so the row must not be rendered as a starter at all.
    galleryMock.mockResolvedValue({
      items: [item('cold', 'recency', 'What has changed in {contract} over the past 30 days?', false)],
    });
    mount();
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeTruthy());
    expect(screen.queryByText(/\{contract\}/)).toBeNull();
    expect(screen.queryByTestId('prompt-gallery')).toBeNull();
  });

  it('renders the hero + composer with no starter row while loading and when the fetch fails', async () => {
    galleryMock.mockReturnValue(new Promise(() => {})); // never settles
    const { unmount } = mount();
    expect(screen.getByTestId('empty-state')).toBeTruthy();
    expect(screen.getByLabelText('ask a follow-up')).toBeTruthy();
    expect(screen.queryByTestId('prompt-gallery')).toBeNull(); // no hardcoded fallback list survives
    unmount();

    galleryMock.mockRejectedValue(new Error('down'));
    mount();
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeTruthy());
    expect(screen.queryByTestId('prompt-gallery')).toBeNull();
  });
});

describe('pickStarters clamp (D-AM-16)', () => {
  it('takes one per category before any category takes a second, in server order', () => {
    const groups = pickStarters(ITEMS);
    expect(groups.map(([c]) => c)).toEqual([
      'convergence',
      'cross_commodity',
      'cascade',
      'verification',
      'ranking',
      'horizon',
      'recency',
    ]);
    // 7 categories -> round 0 spends 7 of the 8 slots on ONE row each; only the leftover 8th slot goes to a
    // second row, and it lands on the first category in server order. (The return is GROUPED for rendering,
    // so a category's two rows sit together — the breadth-first claim is the per-category counts, not the
    // flattened order.)
    expect(groups.map(([c, i]) => [c, i.length])).toEqual([
      ['convergence', 2],
      ['cross_commodity', 1],
      ['cascade', 1],
      ['verification', 1],
      ['ranking', 1],
      ['horizon', 1],
      ['recency', 1],
    ]);
    expect(groups.flatMap(([, i]) => i)).toHaveLength(8);
  });

  it('honours the max, and no category may exceed PER_CATEGORY even when it is the only one', () => {
    const many = Array.from({ length: 9 }, (_, i) => item(`c${i}`, 'convergence', `q${i}`));
    expect(pickStarters(many).flatMap(([, i]) => i)).toHaveLength(2); // PER_CATEGORY, not MAX_STARTERS
    expect(pickStarters(ITEMS, 3).flatMap(([, i]) => i)).toHaveLength(3);
  });

  it('drops unfilled entries before clamping, so a cold row never consumes a slot', () => {
    const mixed = [item('cold', 'convergence', 'q {contract}', false), CROSS_1, CASCADE_1];
    expect(pickStarters(mixed).flatMap(([, i]) => i.map((x) => x.id))).toEqual(['cross_1', 'cascade_1']);
  });
});
