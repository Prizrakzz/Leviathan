import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DossierQuota } from '@/api/schema';
import { DEFAULT_CHOICE, useMode } from '@/store/mode';
import { Composer } from './Composer';
import { ModePicker } from './ModePicker';

/**
 * D-AM-14's picker contract, carried forward to the D-DR-3 TWO-OPTION reality: the keyboard model, the
 * persistence, the click-outside and the streaming-inert behaviour are all preserved verbatim (same
 * assertions, new option set), and the quota badge is the one genuinely new surface.
 *
 * `getDossierQuota` is the only thing stubbed. `null` is NOT an error here -- it is the dark-flag case
 * (GRAPHRAG_DOSSIER absent -> 404), and the picker has to render it as "not enabled", never as broken.
 */
const hoisted = vi.hoisted(() => ({
  quota: { remaining: 2, limit: 3, reset_at: '2026-08-10T00:00:00Z' } as DossierQuota | null,
  calls: 0,
}));

vi.mock('@/api/dossier', async (orig) => {
  const actual = await orig<typeof import('@/api/dossier')>();
  return {
    ...actual,
    getDossierQuota: () => {
      hoisted.calls += 1;
      return Promise.resolve(hoisted.quota);
    },
  };
});

function mount(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

/** The badge only exists once the quota query has settled; every badge assertion waits for it. */
async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId('mode-trigger'));
  return screen.getByTestId('mode-menu');
}

beforeEach(() => {
  localStorage.clear();
  useMode.setState({ choice: DEFAULT_CHOICE });
  hoisted.quota = { remaining: 2, limit: 3, reset_at: '2026-08-10T00:00:00Z' };
  hoisted.calls = 0;
});

describe('ModePicker (D-DR-3 — two options, docked at the ask bar)', () => {
  it('renders Standard by default, with the menu closed', () => {
    mount(<ModePicker />);
    const trigger = screen.getByTestId('mode-trigger');
    expect(trigger).toHaveTextContent('Standard');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
  });

  it('opens to exactly TWO options — Standard and Deep Research — each with its expectation and reason', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    await openMenu(user);

    const options = screen.getAllByRole('menuitemradio');
    expect(options.map((o) => o.getAttribute('data-testid'))).toEqual([
      'mode-option-quick',
      'mode-option-deep_research',
    ]);
    // The old three-mode roster is GONE from the UI -- the internal names survive only on the wire.
    expect(screen.queryByTestId('mode-option-standard')).toBeNull();
    expect(screen.queryByTestId('mode-option-deep')).toBeNull();

    // Exactly one is checked, and it is the current selection.
    expect(options.filter((o) => o.getAttribute('aria-checked') === 'true')).toHaveLength(1);
    expect(screen.getByTestId('mode-option-quick').getAttribute('aria-checked')).toBe('true');

    // Labels are the human names; the internal identifier `quick` never reaches the screen.
    expect(screen.getByTestId('mode-option-quick')).toHaveTextContent('Standard');
    expect(screen.getByTestId('mode-option-quick')).not.toHaveTextContent('quick');
    expect(screen.getByTestId('mode-option-quick')).toHaveTextContent('one turn');
    expect(screen.getByTestId('mode-option-deep_research')).toHaveTextContent('Deep Research');
    expect(screen.getByTestId('mode-option-deep_research')).toHaveTextContent('minutes');
    expect(screen.getByTestId('mode-hint-deep_research')).toHaveTextContent('saved artifact');
  });

  it('the Deep Research row carries the remaining-uses badge from the server', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    await openMenu(user);
    await waitFor(() => expect(screen.getByTestId('dossier-quota-badge')).toHaveTextContent('2 of 3 this week'));
    // The badge belongs to the dossier row only -- Standard has no allowance to spend.
    expect(screen.getByTestId('mode-option-quick').querySelector('[data-testid="dossier-quota-badge"]')).toBeNull();
  });

  it('at zero it is un-choosable and the hint carries the RESET DATE, in UTC', async () => {
    hoisted.quota = { remaining: 0, limit: 3, reset_at: '2026-08-10T00:00:00Z' };
    const user = userEvent.setup();
    mount(<ModePicker />);
    await openMenu(user);
    await waitFor(() =>
      expect(screen.getByTestId('mode-option-deep_research').getAttribute('aria-disabled')).toBe('true'),
    );
    expect(screen.getByTestId('dossier-quota-badge')).toHaveTextContent('0 of 3 this week');
    expect(screen.getByTestId('mode-hint-deep_research')).toHaveTextContent('2026-08-10');

    // Clicking it changes NOTHING -- not the store, not the menu (the hint stays readable).
    await user.click(screen.getByTestId('mode-option-deep_research'));
    expect(useMode.getState().choice).toBe('quick');
    expect(screen.getByTestId('mode-menu')).toBeTruthy();
  });

  it('with the routes dark (404 -> null quota) the row says so, and no badge is invented', async () => {
    hoisted.quota = null;
    const user = userEvent.setup();
    mount(<ModePicker />);
    await openMenu(user);
    await waitFor(() =>
      expect(screen.getByTestId('mode-option-deep_research').getAttribute('aria-disabled')).toBe('true'),
    );
    expect(screen.getByTestId('mode-hint-deep_research')).toHaveTextContent('not enabled');
    expect(screen.queryByTestId('dossier-quota-badge')).toBeNull();
    await user.click(screen.getByTestId('mode-option-deep_research'));
    expect(useMode.getState().choice).toBe('quick');
  });

  it('opening the menu REFETCHES the balance — a page left open overnight must not promise a stale run', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    await waitFor(() => expect(hoisted.calls).toBe(1)); // the mount fetch
    await openMenu(user);
    await waitFor(() => expect(hoisted.calls).toBe(2));
  });

  it('choosing Deep Research updates the trigger, closes the menu, and PERSISTS', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    await openMenu(user);
    await user.click(screen.getByTestId('mode-option-deep_research'));

    expect(useMode.getState().choice).toBe('deep_research');
    expect(screen.getByTestId('mode-trigger')).toHaveTextContent('Deep Research');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    const blob = JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as { state?: { choice?: string } };
    expect(blob.state?.choice).toBe('deep_research');
  });

  it('a persisted choice is what the picker boots showing', () => {
    useMode.setState({ choice: 'deep_research' });
    mount(<ModePicker />);
    expect(screen.getByTestId('mode-trigger')).toHaveTextContent('Deep Research');
  });

  it('is fully keyboard-driven: ArrowDown opens onto the CURRENT choice, arrows move, Enter chooses', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    const trigger = screen.getByTestId('mode-trigger');
    trigger.focus();

    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('mode-menu')).toBeTruthy();
    // Focus enters at the state the user is in, so the next arrow is a relative move, not a hunt.
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-quick'));

    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-deep_research'));
    await user.keyboard('{ArrowDown}'); // wraps
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-quick'));
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-deep_research'));

    await user.keyboard('{Enter}');
    expect(useMode.getState().choice).toBe('deep_research');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    // Focus comes back to the trigger: a keyboard user lands one Shift+Tab from the textarea.
    expect(document.activeElement).toBe(screen.getByTestId('mode-trigger'));
  });

  it('an UNAVAILABLE row still takes keyboard focus — its hint is the only place the reset date is written', async () => {
    hoisted.quota = { remaining: 0, limit: 3, reset_at: '2026-08-10T00:00:00Z' };
    const user = userEvent.setup();
    mount(<ModePicker />);
    screen.getByTestId('mode-trigger').focus();
    await user.keyboard('{ArrowDown}');
    await waitFor(() =>
      expect(screen.getByTestId('mode-option-deep_research').getAttribute('aria-disabled')).toBe('true'),
    );
    await user.keyboard('{ArrowDown}');
    // `aria-disabled`, NOT `disabled`: a disabled button cannot be focused, and arrowing would dead-end.
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-deep_research'));
    await user.keyboard('{Enter}');
    expect(useMode.getState().choice).toBe('quick'); // focusable, still not choosable
  });

  it('Home/End jump to the ends of the list', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    await openMenu(user);
    await user.keyboard('{End}');
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-deep_research'));
    await user.keyboard('{Home}');
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-quick'));
  });

  it('Escape closes without choosing and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    mount(<ModePicker />);
    const trigger = screen.getByTestId('mode-trigger');
    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    expect(useMode.getState().choice).toBe('quick');
    expect(document.activeElement).toBe(trigger);
  });

  it('a click outside closes it', async () => {
    const user = userEvent.setup();
    mount(
      <div>
        <ModePicker />
        <button data-testid="elsewhere">elsewhere</button>
      </div>,
    );
    await user.click(screen.getByTestId('mode-trigger'));
    expect(screen.getByTestId('mode-menu')).toBeTruthy();
    await user.click(screen.getByTestId('elsewhere'));
    expect(screen.queryByTestId('mode-menu')).toBeNull();
  });

  it('goes inert while a turn streams, and any open menu closes with it', async () => {
    const user = userEvent.setup();
    const { rerender } = mount(<ModePicker disabled={false} />);
    await user.click(screen.getByTestId('mode-trigger'));
    expect(screen.getByTestId('mode-menu')).toBeTruthy();

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    rerender(
      <QueryClientProvider client={qc}>
        <ModePicker disabled={true} />
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    expect((screen.getByTestId('mode-trigger') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('Composer docks the picker (both variants)', () => {
  it('the follow-up composer carries it, and the selection is what a later submit runs at', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    mount(<Composer onSubmit={onSubmit} streaming={false} autoFocus={false} />);
    expect(screen.getByTestId('mode-picker')).toBeTruthy();

    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-deep_research'));

    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    await user.type(ta, 'why is wheat tight?');
    await user.keyboard('{Enter}');

    // The composer stays a TEXT BOX: it submits the question and nothing else. The selection it made is
    // read back off the store by Shell at submit (Shell.tsx: `useMode.getState().choice`).
    expect(onSubmit).toHaveBeenCalledWith('why is wheat tight?');
    expect(useMode.getState().choice).toBe('deep_research');
  });

  it('the hero (empty-state) composer carries it too', () => {
    mount(<Composer onSubmit={() => {}} streaming={false} hero autoFocus={false} />);
    expect(screen.getByTestId('composer-hero')).toBeTruthy();
    expect(screen.getByTestId('mode-picker')).toBeTruthy();
  });

  it('the picker is disabled exactly when the textarea is', () => {
    mount(<Composer onSubmit={() => {}} streaming={true} autoFocus={false} />);
    expect((screen.getByTestId('composer') as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByTestId('mode-trigger') as HTMLButtonElement).disabled).toBe(true);
  });
});
