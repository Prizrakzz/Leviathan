import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const galleryMock = vi.fn();
vi.mock('@/api/client', () => ({ getGallery: () => galleryMock() }));

import { EmptyState, pickStarters, utcDayOfYear } from './EmptyState';
import type { GalleryItem } from '@/api/schema';
import { useCompose } from '@/store/compose';

const item = (id: string, category: string, question: string, filled = true): GalleryItem => ({
  id,
  category,
  question,
  rc_target: 'default',
  filled,
});

// One row per category plus a SECOND convergence row, mirroring the shape gallery.yaml ships (12 rows over
// 7 categories) so the clamp is exercised against real proportions rather than a toy list.
// D-SG S1: 7 categories and a 3-chip page means the rotation is what decides WHICH three, so every
// assertion below either pins the UTC day or asserts something the rotation cannot move.
const CONV_1 = item('conv_1', 'convergence', 'How close is the frost squeeze regime in coffee to firing right now?');
const CONV_2 = item('conv_2', 'convergence', 'The ethanol diversion regime in sugar is short of its threshold?');
const CROSS_1 = item('cross_1', 'cross_commodity', 'Compare palm oil and soybean oil?');
const CASCADE_1 = item('cascade_1', 'cascade', 'Walk me through the cascade in corn.');
const VERIFY_1 = item('verify_1', 'verification', 'Stocks in corn are the tightest in a decade, right?');
const RANK_1 = item('rank_1', 'ranking', 'Rank the largest exporters of sugar.');
const HORIZON_1 = item('horizon_1', 'horizon', 'What should I watch over weeks, months, and quarters in corn?');
const RECENCY_1 = item('recency_1', 'recency', 'What has changed in corn over the past 30 days?');
const ITEMS: GalleryItem[] = [CONV_1, CONV_2, CROSS_1, CASCADE_1, VERIFY_1, RANK_1, HORIZON_1, RECENCY_1];

beforeEach(() =>
  useCompose.setState({
    draft: '',
    rev: 0,
    focus: false,
    template: null,
    slots: [],
    values: {},
    options: {},
    spans: {},
  }),
);

function mount(onAsk: (q: string) => void = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EmptyState onAsk={onAsk} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.useRealTimers());

describe('EmptyState prompt gallery (D-AM-16, clamped to 3 by D-SG S1)', () => {
  it('renders EXACTLY 3 unlabelled starters, rotated by the UTC day', async () => {
    // Only Date is faked (timers stay real, so waitFor and userEvent still tick). 2026-03-04 is day 62;
    // 62 % 7 categories = 6, so the round starts at the LAST category and wraps -- which is the whole point
    // of the rotation: without it the landing page would be frozen on convergence/cross_commodity/cascade.
    vi.useFakeTimers({ toFake: ['Date'], shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-03-04T09:00:00Z'));
    galleryMock.mockResolvedValue({ items: ITEMS });
    mount();
    const gallery = await waitFor(() => screen.getByTestId('prompt-gallery'));
    expect([...gallery.querySelectorAll('button')].map((b) => b.textContent)).toEqual([
      RECENCY_1.question,
      CONV_1.question,
      CROSS_1.question,
    ]);
    // the category headings are GONE: with one starter per category they labelled nothing
    expect(screen.queryByText('cross commodity')).toBeNull();
    expect(screen.queryByText('convergence')).toBeNull();
  });

  it('D-UX-1: a starter PREFILLS the hero composer verbatim and fires NO turn', async () => {
    // The revert. A starter used to submit on click, which made every landing question a decision taken by
    // a mouse: no chance to swap the contract, add a clause, or set the reasoning mode first. Now the chip
    // text lands in the box (byte-identical to what it used to submit) and Enter is what sends it.
    const onAsk = vi.fn();
    // a one-row catalog: which of the 7 categories the day happens to start on is the clamp's business
    galleryMock.mockResolvedValue({ items: [VERIFY_1] });
    mount(onAsk);
    const chip = await screen.findByText(VERIFY_1.question);
    await userEvent.click(chip);
    expect(onAsk).not.toHaveBeenCalled();
    const box = screen.getByTestId('composer-hero') as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe(VERIFY_1.question));

    await userEvent.keyboard('{Enter}'); // the prefill focuses the box, so Enter goes to it
    expect(onAsk).toHaveBeenCalledWith(VERIFY_1.question);
  });

  it('D-UX-1: a starter with slots prefills the SERVER fill and opens the slot bar for retargeting', async () => {
    const onAsk = vi.fn();
    galleryMock.mockResolvedValue({
      items: [
        {
          ...RANK_1,
          template: 'Rank the largest exporters of {contract}.',
          slots: { contract: 'sugar' },
          question: 'Rank the largest exporters of sugar.',
        },
      ],
      vocab: { contracts: ['sugar', 'corn'], regimes: [], pairs: [] },
    });
    mount(onAsk);
    const chip = await screen.findByText('Rank the largest exporters of sugar.');
    await userEvent.click(chip);

    const box = screen.getByTestId('composer-hero') as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe('Rank the largest exporters of sugar.'));
    // the same combobox the top-bar library gets: the landing page and the library share ONE prefill path
    const slot = screen.getByLabelText('contract slot') as HTMLInputElement;
    expect(slot.value).toBe('sugar');
    expect(
      [...screen.getByTestId('slot-vocab-contract').querySelectorAll('option')].map((o) => o.value),
    ).toEqual(['sugar', 'corn']);
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('never offers an unfilled template as a starter', async () => {
    // Cold catalog: the server still returns the templates (the wire stays legible), but this row is a
    // one-glance menu of questions the book can answer TODAY. A fill-in-the-blank belongs in the top-bar
    // template library, where the slot bar makes the blanks fillable. Unchanged by the D-UX-1 revert.
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

describe('pickStarters clamp (D-AM-16, re-pinned by D-SG S1)', () => {
  it('takes ONE per category, at most 3, in server order from the rotated start', () => {
    // Day 0 starts at the first category, so this is the un-rotated baseline: three consecutive categories
    // in gallery.yaml order, one row each. CONV_2 proves the second convergence row is never reached.
    expect(pickStarters(ITEMS, 3, 0).map((i) => i.id)).toEqual(['conv_1', 'cross_1', 'cascade_1']);
  });

  it('rotates the start category by UTC day, and the same day always picks the same three', () => {
    const ids = (day: number) => pickStarters(ITEMS, 3, day).map((i) => i.id);
    expect(ids(1)).toEqual(['cross_1', 'cascade_1', 'verify_1']);
    expect(ids(6)).toEqual(['recency_1', 'conv_1', 'cross_1']); // wraps past the last category
    expect(ids(7)).toEqual(ids(0)); // 7 categories -> the cycle closes
    expect(ids(3)).toEqual(ids(3)); // deterministic: no shuffle, no clock read inside the pick
    // the offset is a function of the DATE alone, in UTC -- two users on the same book on the same day
    // must see the same three, whatever their zone (Jan 1 is day 0).
    expect(utcDayOfYear(new Date('2026-01-01T23:59:59Z'))).toBe(0);
    expect(utcDayOfYear(new Date('2026-03-04T09:00:00Z'))).toBe(62);
  });

  it('honours the max, and no category may exceed PER_CATEGORY even when it is the only one', () => {
    const many = Array.from({ length: 9 }, (_, i) => item(`c${i}`, 'convergence', `q${i}`));
    expect(pickStarters(many, 3, 0)).toHaveLength(1); // PER_CATEGORY, not MAX_STARTERS
    expect(pickStarters(ITEMS, 2, 0)).toHaveLength(2);
    expect(pickStarters([], 3, 0)).toEqual([]); // an empty catalog must not divide by zero categories
  });

  it('drops unfilled entries before clamping, so a cold row never consumes a slot', () => {
    const mixed = [item('cold', 'convergence', 'q {contract}', false), CROSS_1, CASCADE_1];
    expect(pickStarters(mixed, 3, 0).map((x) => x.id)).toEqual(['cross_1', 'cascade_1']);
  });
});
