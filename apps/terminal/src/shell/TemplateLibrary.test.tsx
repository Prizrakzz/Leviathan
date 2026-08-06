import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const galleryMock = vi.fn();
vi.mock('@/api/client', () => ({ getGallery: () => galleryMock() }));

import type { GalleryItem, GalleryResponse } from '@/api/schema';
import { useCompose } from '@/store/compose';
import { Composer } from './Composer';
import { TemplateLibrary } from './TemplateLibrary';

/**
 * D-UX-1 acceptance. Three claims, and the first one is the one this wave exists for:
 *
 *   1. PREFILL, NEVER SUBMIT. Choosing a template puts the question in the ask box and stops. The mocked
 *      `onSubmit` standing in for a turn must not be called by any click in this file.
 *   2. AVAILABLE IN EVERY STATE. The library is a top-bar popover, not an empty-state row, so it opens with
 *      a live thread on screen -- the placement critique that opened the wave.
 *   3. THE SLOTS ARE THE ANALYST'S. Each blank gets a combobox that OFFERS the census-gated catalog values
 *      and ACCEPTS anything typed; editing one rewrites that span of the question, live, in the box.
 */
const CONV: GalleryItem = {
  id: 'conv_regime_proximity',
  category: 'convergence',
  rc_target: 'recency',
  filled: true,
  template: 'How close is the {regime} regime in {contract} to firing right now?',
  slots: { regime: 'Frost Squeeze (price-supportive)', contract: 'arabica coffee' },
  question:
    'How close is the Frost Squeeze (price-supportive) regime in arabica coffee to firing right now?',
};
const RANK: GalleryItem = {
  id: 'rank_exporters',
  category: 'ranking',
  rc_target: 'ranking',
  filled: true,
  template: 'Rank the largest exporters of {contract} and flag which is most at risk this season.',
  slots: { contract: 'raw sugar' },
  question: 'Rank the largest exporters of raw sugar and flag which is most at risk this season.',
};
const COLD: GalleryItem = {
  id: 'recency_whats_changed',
  category: 'recency',
  rc_target: 'recency',
  filled: false,
  template: 'What has changed in {contract} fundamentals over the past 30 days?',
  slots: {},
  question: 'What has changed in {contract} fundamentals over the past 30 days?',
};

const VOCAB = {
  contracts: ['arabica coffee', 'corn', 'raw sugar'],
  regimes: ['Frost Squeeze (price-supportive)', 'Record Supply (price-pressuring)'],
  pairs: ['palm oil and soybean oil'],
};
const GALLERY: GalleryResponse = { items: [CONV, RANK, COLD], catalog_warm: true, vocab: VOCAB };

/** The library and the composer are in different subtrees in the real app (top bar vs answer view); the
 *  store is the seam, so mounting them side by side is the honest unit. */
function mount(onSubmit: (q: string) => void = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TemplateLibrary />
      <div data-testid="live-thread">a turn is on screen</div>
      <Composer onSubmit={onSubmit} streaming={false} autoFocus={false} />
    </QueryClientProvider>,
  );
}

const box = () => screen.getByTestId('composer') as HTMLTextAreaElement;

async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByLabelText('template library'));
  return screen.findByTestId('template-library');
}

beforeEach(() => {
  galleryMock.mockResolvedValue(GALLERY);
  useCompose.setState({
    draft: '',
    rev: 0,
    focus: false,
    template: null,
    slots: [],
    values: {},
    options: {},
    spans: {},
  });
});

describe('TemplateLibrary: reachable in every state (D-UX-1)', () => {
  it('opens from the top bar with a thread on screen, and lists every template by category', async () => {
    const user = userEvent.setup();
    mount();
    expect(screen.getByTestId('live-thread')).toBeTruthy(); // NOT an empty state
    const panel = await open(user);

    expect(within(panel).getByText('convergence')).toBeTruthy();
    expect(within(panel).getByText('ranking')).toBeTruthy();
    expect(within(panel).getByText('recency')).toBeTruthy();
    // the COLD row is listed here even though the landing starter row drops it: fill-in-the-blank is
    // exactly what this surface is for.
    expect(within(panel).getByTestId(`template-row-${COLD.id}`)).toBeTruthy();
    // rows read as FORMS: the authored wording with its blanks as chips, not a pre-filled example
    expect(within(panel).getByTestId(`template-row-${CONV.id}`).textContent).toBe(
      'How close is the regime regime in contract to firing right now?',
    );
  });

  it('closes on choose and on an outside click', async () => {
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${RANK.id}`));
    expect(screen.queryByTestId('template-library')).toBeNull();

    await open(user);
    await user.click(screen.getByTestId('live-thread'));
    await waitFor(() => expect(screen.queryByTestId('template-library')).toBeNull());
  });
});

describe('TemplateLibrary: choosing PREFILLS, never submits (D-UX-1 law 1)', () => {
  it('lands the advertised question in the ask box with the turn unfired', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    mount(onSubmit);
    await open(user);
    await user.click(screen.getByTestId(`template-row-${CONV.id}`));

    // byte-identical to the question the gallery advertises: template + the server's own slot values
    await waitFor(() => expect(box().value).toBe(CONV.question));
    expect(onSubmit).not.toHaveBeenCalled(); // THE pin: no turn fired by a template click

    // ...and Enter in the box is what sends it, unchanged.
    await user.type(box(), '{Enter}');
    expect(onSubmit).toHaveBeenCalledWith(CONV.question);
  });

  it('a cold row prefills the BLANKS and parks the caret on the first one', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    mount(onSubmit);
    await open(user);
    await user.click(screen.getByTestId(`template-row-${COLD.id}`));

    await waitFor(() => expect(box().value).toBe(COLD.template));
    expect(box().selectionStart).toBe(COLD.template!.indexOf('{contract}'));
    expect(box().selectionEnd).toBe(COLD.template!.indexOf('{contract}') + '{contract}'.length);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submitting clears the slot bar with the box (the turn consumed the template)', async () => {
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${RANK.id}`));
    await waitFor(() => expect(screen.getByTestId('slot-bar')).toBeTruthy());

    await user.type(box(), '{Enter}');
    await waitFor(() => expect(screen.queryByTestId('slot-bar')).toBeNull());
    expect(box().value).toBe('');
  });
});

describe('TemplateLibrary: the slot comboboxes (D-UX-1 law 2)', () => {
  it('offers the catalog vocabulary per slot -- and only the census-gated set', async () => {
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${CONV.id}`));
    await screen.findByTestId('slot-bar');

    const contract = screen.getByLabelText('contract slot') as HTMLInputElement;
    expect(contract.value).toBe('arabica coffee');
    // it IS a combobox: the input names a datalist, and that list carries the vocabulary
    expect(contract.getAttribute('list')).toBe('slot-vocab-contract');
    const offered = (list: string) =>
      [...screen.getByTestId(`slot-vocab-${list}`).querySelectorAll('option')].map((o) => o.value);
    expect(offered('contract')).toEqual(VOCAB.contracts);
    expect(offered('regime')).toEqual(VOCAB.regimes);
    expect(screen.queryByTestId('slot-vocab-pair')).toBeNull(); // this template has no {pair} blank
  });

  it('picking an offered value rewrites that span of the question, live, without submitting', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    mount(onSubmit);
    await open(user);
    await user.click(screen.getByTestId(`template-row-${CONV.id}`));
    await screen.findByTestId('slot-bar');

    await user.clear(screen.getByLabelText('contract slot'));
    await user.type(screen.getByLabelText('contract slot'), 'corn');
    await waitFor(() =>
      expect(box().value).toBe(
        'How close is the Frost Squeeze (price-supportive) regime in corn to firing right now?',
      ),
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('ACCEPTS a free-typed value the vocabulary never offered', async () => {
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${RANK.id}`));
    await screen.findByTestId('slot-bar');

    const contract = screen.getByLabelText('contract slot');
    await user.clear(contract);
    await user.type(contract, 'hard red winter wheat');
    await waitFor(() =>
      expect(box().value).toBe(
        'Rank the largest exporters of hard red winter wheat and flag which is most at risk this season.',
      ),
    );
    // free typing does not shrink the dropdown -- it still offers what the engine can answer
    expect(
      [...screen.getByTestId('slot-vocab-contract').querySelectorAll('option')].map((o) => o.value),
    ).toEqual(VOCAB.contracts);
  });

  it('keeps a hand-typed addition when a slot is retargeted afterwards', async () => {
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${RANK.id}`));
    await screen.findByTestId('slot-bar');

    await user.type(box(), ' Cite the source.');
    await user.clear(screen.getByLabelText('contract slot'));
    await user.type(screen.getByLabelText('contract slot'), 'corn');
    await waitFor(() =>
      expect(box().value).toBe(
        'Rank the largest exporters of corn and flag which is most at risk this season. Cite the source.',
      ),
    );
  });

  it('dismissing the bar leaves the question in the box', async () => {
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${RANK.id}`));
    await screen.findByTestId('slot-bar');

    await user.click(screen.getByLabelText('dismiss slots'));
    expect(screen.queryByTestId('slot-bar')).toBeNull();
    expect(box().value).toBe(RANK.question);
  });

  it('renders no bar at all when nothing has been prefilled (every other compose path is untouched)', () => {
    mount();
    expect(screen.queryByTestId('slot-bar')).toBeNull();
    expect(box().value).toBe('');
  });
});

describe('TemplateLibrary: degradations', () => {
  it('a server without the D-UX-1 fields still prefills -- the question IS the template', async () => {
    galleryMock.mockResolvedValue({ items: [{ id: 'x', category: 'ranking', question: 'Rank corn exporters.' }] });
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    mount(onSubmit);
    await open(user);
    await user.click(screen.getByTestId('template-row-x'));
    await waitFor(() => expect(box().value).toBe('Rank corn exporters.'));
    expect(screen.queryByTestId('slot-bar')).toBeNull(); // no blanks to fill
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('a cold catalog still opens the library and still takes free typing', async () => {
    galleryMock.mockResolvedValue({ items: [COLD], catalog_warm: false });
    const user = userEvent.setup();
    mount();
    await open(user);
    await user.click(screen.getByTestId(`template-row-${COLD.id}`));
    await screen.findByTestId('slot-bar');

    expect(
      [...screen.getByTestId('slot-vocab-contract').querySelectorAll('option')],
    ).toHaveLength(0); // nothing to offer...
    await user.type(screen.getByLabelText('contract slot'), 'corn'); // ...but the blank is still fillable
    await waitFor(() =>
      expect(box().value).toBe('What has changed in corn fundamentals over the past 30 days?'),
    );
  });

  it('a failed fetch renders the button and an empty panel, never an error', async () => {
    galleryMock.mockRejectedValue(new Error('down'));
    const user = userEvent.setup();
    mount();
    const panel = await open(user);
    expect(within(panel).getByText('no templates')).toBeTruthy();
  });
});
