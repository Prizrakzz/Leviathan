import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreditsBalance } from '@/api/credits';
import type { DossierQuota } from '@/api/schema';
import { DEFAULT_CHOICE, useMode } from '@/store/mode';
import { Composer } from './Composer';
import { DepthControl } from './DepthControl';

/**
 * D-MW-21 / D-MW-25 — the depth control's contract.
 *
 * Everything D-AM-14/D-DR-3 pinned about the old picker that is still TRUE of a slider is carried forward
 * verbatim (persistence, streaming-inertness, the labels-not-identifiers rule, the two separate meters,
 * full keyboard drive). What is new is the slider semantics, the credit notch, and the rule that a notch
 * you cannot choose still tells you WHY and WHEN, without needing focus.
 *
 * Only the two fetchers are stubbed, and `null` is not an error for either of them: it is the DARK case
 * (GRAPHRAG_DOSSIER / GRAPHRAG_CREDITS absent -> 404). Dark credits means NOTHING is metered.
 */
const hoisted = vi.hoisted(() => ({
  quota: { remaining: 2, limit: 4, reset_at: '2026-09-01T00:00:00Z' } as DossierQuota | null,
  credits: { remaining: 97, limit: 100, reset_at: '2026-09-01T00:00:00Z' } as CreditsBalance | null,
  quotaCalls: 0,
  creditCalls: 0,
}));

vi.mock('@/api/dossier', async (orig) => {
  const actual = await orig<typeof import('@/api/dossier')>();
  return {
    ...actual,
    getDossierQuota: () => {
      hoisted.quotaCalls += 1;
      return Promise.resolve(hoisted.quota);
    },
  };
});

vi.mock('@/api/credits', async (orig) => {
  const actual = await orig<typeof import('@/api/credits')>();
  return {
    ...actual,
    getCredits: () => {
      hoisted.creditCalls += 1;
      return Promise.resolve(hoisted.credits);
    },
  };
});

function mount(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const slider = () => screen.getByTestId('depth-slider');

beforeEach(() => {
  localStorage.clear();
  useMode.setState({ choice: DEFAULT_CHOICE });
  hoisted.quota = { remaining: 2, limit: 4, reset_at: '2026-09-01T00:00:00Z' };
  hoisted.credits = { remaining: 97, limit: 100, reset_at: '2026-09-01T00:00:00Z' };
  hoisted.quotaCalls = 0;
  hoisted.creditCalls = 0;
});

describe('DepthControl — the notched depth slider (D-MW-21)', () => {
  it('is a slider over exactly THREE notches, parked on Scan, and says so in its value text', () => {
    mount(<DepthControl />);
    const s = slider();
    expect(s.getAttribute('role')).toBe('slider');
    expect(s.getAttribute('aria-valuemin')).toBe('0');
    expect(s.getAttribute('aria-valuemax')).toBe('2');
    expect(s.getAttribute('aria-valuenow')).toBe('0');
    // The LABEL is what a screen reader reads out -- never the internal identifier.
    expect(s.getAttribute('aria-valuetext')).toBe('Scan');
    expect(s.textContent).not.toMatch(/quick|standard|deep_research/);

    expect(screen.getByTestId('depth-notch-quick')).toBeTruthy();
    expect(screen.getByTestId('depth-notch-deep')).toBeTruthy();
    expect(screen.getByTestId('depth-notch-deep_research')).toBeTruthy();
    // The retired roster: `standard` is not a notch, and no bundle-visible control can reach it.
    expect(screen.queryByTestId('depth-notch-standard')).toBeNull();
    // Nor are the DARK tiers offered (the P5 2-notch ship).
    expect(screen.queryByTestId('depth-notch-max')).toBeNull();
    expect(screen.queryByTestId('depth-notch-max_c0')).toBeNull();
  });

  it('the notches read as human labels with relative time words and their price', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    expect(screen.getByTestId('depth-value')).toHaveTextContent('Scan');
    expect(screen.getByTestId('depth-hint')).toHaveTextContent('no credit');

    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(screen.getByTestId('depth-value')).toHaveTextContent('Analysis');
    expect(screen.getByTestId('depth-hint')).toHaveTextContent('one credit');
    expect(slider().getAttribute('aria-valuetext')).toBe('Analysis');
    expect(slider().getAttribute('aria-valuenow')).toBe('1');
  });

  it('clicking a notch selects it and PERSISTS the choice', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(useMode.getState().choice).toBe('deep');
    const blob = JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as {
      state?: { choice?: string };
      version?: number;
    };
    expect(blob.state?.choice).toBe('deep');
    expect(blob.version).toBe(3);
  });

  it('a persisted choice is what the control boots showing', () => {
    useMode.setState({ choice: 'deep_research' });
    mount(<DepthControl />);
    expect(screen.getByTestId('depth-value')).toHaveTextContent('Deep Research');
    expect(slider().getAttribute('aria-valuenow')).toBe('2');
  });

  it('is fully keyboard-driven: arrows step the ramp, Home/End jump to its ends', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    slider().focus();

    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('deep');
    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('deep_research');
    await user.keyboard('{ArrowRight}'); // the top notch is the top: no wrap onto Scan
    expect(useMode.getState().choice).toBe('deep_research');

    await user.keyboard('{ArrowLeft}');
    expect(useMode.getState().choice).toBe('deep');
    await user.keyboard('{ArrowDown}'); // Down == shallower, the slider convention
    expect(useMode.getState().choice).toBe('quick');
    await user.keyboard('{ArrowLeft}');
    expect(useMode.getState().choice).toBe('quick');

    await user.keyboard('{End}');
    expect(useMode.getState().choice).toBe('deep_research');
    await user.keyboard('{Home}');
    expect(useMode.getState().choice).toBe('quick');
  });

  it('goes inert while a turn streams — the selection that governs a submit is the one that was on screen', async () => {
    const user = userEvent.setup();
    mount(<DepthControl disabled />);
    expect(slider().getAttribute('aria-disabled')).toBe('true');
    expect(slider().getAttribute('tabindex')).toBe('-1');
    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(useMode.getState().choice).toBe('quick');
  });

  it('focusing the control re-reads BOTH balances — a page left open overnight must not promise a spent turn', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(hoisted.quotaCalls).toBe(1));
    await waitFor(() => expect(hoisted.creditCalls).toBe(1));
    await user.click(slider());
    await waitFor(() => expect(hoisted.quotaCalls).toBe(2));
    await waitFor(() => expect(hoisted.creditCalls).toBe(2));
  });
});

describe('DepthControl — the two meters (D-MW-25)', () => {
  it('shows the credit balance from the server, and never invents one', async () => {
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('credits-badge')).toHaveTextContent('97 of 100 this month'));
  });

  it('with metering dark (404 -> null) there is NO badge and the metered notch is free', async () => {
    hoisted.credits = null;
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(hoisted.creditCalls).toBe(1));
    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(useMode.getState().choice).toBe('deep');
    expect(screen.queryByTestId('credits-badge')).toBeNull();
    // No meter, no charge trade to state.
    expect(screen.queryByTestId('credits-charge-note')).toBeNull();
    expect(screen.queryByTestId('depth-blocked-deep')).toBeNull();
  });

  it('states the disconnect-after-compute charge trade on screen while a metered notch is selected', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('credits-badge')).toBeTruthy());
    expect(screen.queryByTestId('credits-charge-note')).toBeNull(); // Scan is free: nothing to warn about
    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(screen.getByTestId('credits-charge-note')).toHaveTextContent('it still counts');
  });

  it('out of credits: the metered notch is un-choosable and the reason carries the RESET DATE in UTC', async () => {
    hoisted.credits = { remaining: 0, limit: 100, reset_at: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('depth-blocked-deep')).toBeTruthy());
    expect(screen.getByTestId('depth-blocked-deep')).toHaveTextContent('2026-09-01');
    expect(screen.getByTestId('credits-badge')).toHaveTextContent('0 of 100 this month');

    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(useMode.getState().choice).toBe('quick'); // nothing moved
  });

  it('a blocked notch is STEPPED OVER, not stalled on — Deep Research stays reachable with no credits left', async () => {
    hoisted.credits = { remaining: 0, limit: 100, reset_at: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('depth-blocked-deep')).toBeTruthy());
    slider().focus();
    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('deep_research');
  });

  it('the dossier allowance is its OWN meter: its badge shows on its own notch, and it blocks only itself', async () => {
    hoisted.quota = { remaining: 0, limit: 4, reset_at: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('depth-blocked-deep_research')).toBeTruthy());
    expect(screen.getByTestId('depth-blocked-deep_research')).toHaveTextContent('2026-09-01');
    // Credits are untouched by a spent dossier allowance -- two meters, never merged.
    expect(screen.queryByTestId('depth-blocked-deep')).toBeNull();
    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(useMode.getState().choice).toBe('deep');

    await user.click(screen.getByTestId('depth-notch-deep_research'));
    expect(useMode.getState().choice).toBe('deep'); // refused, and it says why above
  });

  it('with the dossier routes dark the top notch says so, and no allowance is invented', async () => {
    hoisted.quota = null;
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() =>
      expect(screen.getByTestId('depth-blocked-deep_research')).toHaveTextContent('not enabled'),
    );
    expect(screen.queryByTestId('dossier-quota-badge')).toBeNull();
    await user.click(screen.getByTestId('depth-notch-deep_research'));
    expect(useMode.getState().choice).toBe('quick');
  });

  it('the dossier badge rides the Deep Research notch only', async () => {
    useMode.setState({ choice: 'deep_research' });
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('dossier-quota-badge')).toHaveTextContent('2 of 4 this month'));
    // Both meters are readable at once, and they are different numbers.
    expect(screen.getByTestId('credits-badge')).toHaveTextContent('97 of 100');
  });
});

describe('Composer docks the depth control (both variants)', () => {
  it('the follow-up composer carries it, and the selection is what a later submit runs at', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    mount(<Composer onSubmit={onSubmit} streaming={false} autoFocus={false} />);
    expect(screen.getByTestId('depth-control')).toBeTruthy();

    await user.click(screen.getByTestId('depth-notch-deep'));
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    await user.type(ta, 'why is wheat tight?');
    await user.keyboard('{Enter}');

    // The composer stays a TEXT BOX: it submits the question and nothing else. The selection it made is
    // read back off the store by Shell at submit (Shell.tsx: `useMode.getState().choice`).
    expect(onSubmit).toHaveBeenCalledWith('why is wheat tight?');
    expect(useMode.getState().choice).toBe('deep');
  });

  it('the hero (empty-state) composer carries it too', () => {
    mount(<Composer onSubmit={() => {}} streaming={false} hero autoFocus={false} />);
    expect(screen.getByTestId('composer-hero')).toBeTruthy();
    expect(screen.getByTestId('depth-control')).toBeTruthy();
  });

  it('the control is inert exactly when the textarea is', () => {
    mount(<Composer onSubmit={() => {}} streaming={true} autoFocus={false} />);
    expect((screen.getByTestId('composer') as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.getByTestId('depth-slider').getAttribute('aria-disabled')).toBe('true');
  });
});
