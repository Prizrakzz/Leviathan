import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreditsBalance } from '@/api/credits';
import { DEEP_RESEARCH_DARK_TITLE, DEFAULT_CHOICE, useMode } from '@/store/mode';
import { Composer } from './Composer';
import { CHARGE_NOTE } from './CreditsBadge';
import { DepthControl } from './DepthControl';

/**
 * D-MW-21 / D-MW-25 / THE CASCADE NOTCH (2026-09-06) — the depth control's contract.
 *
 * Everything the earlier waves pinned that is still TRUE of a slider is carried forward verbatim
 * (persistence, streaming-inertness, the labels-not-identifiers rule, full keyboard drive, the credit
 * meter). What is new is the THIRD notch, the SERVED-ROSTER GATE that keeps it honest while `max` is a
 * dark backend preset, the AFFORDABILITY clause a two-credit tier needs and a 0/1 ladder never did, and
 * Deep Research as a standalone lights-off control rather than a notch.
 *
 * ONE fetcher is stubbed and `null` is not an error: it is the DARK case (GRAPHRAG_CREDITS absent -> 404),
 * and dark credits means NOTHING is metered. The DOSSIER quota fetcher is deliberately NOT stubbed any
 * more — this component no longer reads it, and that absence is itself pinned below.
 */
const hoisted = vi.hoisted(() => ({
  credits: { remaining: 97, limit: 100, reset_at: '2026-09-01T00:00:00Z' } as CreditsBalance | null,
  creditCalls: 0,
}));

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

/** A deployment whose GRAPHRAG_MODES NAMES the dark preset — i.e. one that has taken the Cascade flip. */
const CASCADE_SERVED = 'quick,deep,max';

beforeEach(() => {
  localStorage.clear();
  useMode.setState({ choice: DEFAULT_CHOICE });
  hoisted.credits = { remaining: 97, limit: 100, reset_at: '2026-09-01T00:00:00Z' };
  hoisted.creditCalls = 0;
  vi.stubEnv('VITE_MODES', CASCADE_SERVED);
});

afterEach(() => vi.unstubAllEnvs());

describe('DepthControl — the notched depth slider (Scan / Analysis / Cascade)', () => {
  it('is a slider over exactly THREE notches, parked on Scan, and says so in its value text', () => {
    mount(<DepthControl />);
    const s = slider();
    expect(s.getAttribute('role')).toBe('slider');
    expect(s.getAttribute('aria-valuemin')).toBe('0');
    expect(s.getAttribute('aria-valuemax')).toBe('2');
    expect(s.getAttribute('aria-valuenow')).toBe('0');
    // The LABEL is what a screen reader reads out -- never the internal identifier.
    expect(s.getAttribute('aria-valuetext')).toBe('Scan');
    expect(s.textContent).not.toMatch(/quick|standard|deep_research|max/);

    expect(screen.getByTestId('depth-notch-quick')).toBeTruthy();
    expect(screen.getByTestId('depth-notch-deep')).toBeTruthy();
    expect(screen.getByTestId('depth-notch-cascade')).toBeTruthy();
    // The retired roster: `standard` is not a notch, and no bundle-visible control can reach it.
    expect(screen.queryByTestId('depth-notch-standard')).toBeNull();
    // Deep Research left the RAMP (it is the standalone control below), and a notch is never named after
    // a wire identifier: Cascade's preset is `max`, its notch is `cascade`.
    expect(screen.queryByTestId('depth-notch-deep_research')).toBeNull();
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

    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(screen.getByTestId('depth-value')).toHaveTextContent('Cascade');
    expect(screen.getByTestId('depth-hint')).toHaveTextContent('two credits');
    expect(slider().getAttribute('aria-valuetext')).toBe('Cascade');
    expect(slider().getAttribute('aria-valuenow')).toBe('2');
    expect(useMode.getState().choice).toBe('cascade');
  });

  it('clicking a notch selects it and PERSISTS the choice', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(useMode.getState().choice).toBe('cascade');
    const blob = JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as {
      state?: { choice?: string };
      version?: number;
    };
    expect(blob.state?.choice).toBe('cascade');
    expect(blob.version).toBe(3);
  });

  it('a persisted choice is what the control boots showing', () => {
    useMode.setState({ choice: 'cascade' });
    mount(<DepthControl />);
    expect(screen.getByTestId('depth-value')).toHaveTextContent('Cascade');
    expect(slider().getAttribute('aria-valuenow')).toBe('2');
  });

  it('is fully keyboard-driven: arrows step the ramp, Home/End jump to its ends', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    slider().focus();

    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('deep');
    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('cascade');
    await user.keyboard('{ArrowRight}'); // the top notch is the top: no wrap onto Scan
    expect(useMode.getState().choice).toBe('cascade');

    await user.keyboard('{ArrowLeft}');
    expect(useMode.getState().choice).toBe('deep');
    await user.keyboard('{ArrowDown}'); // Down == shallower, the slider convention
    expect(useMode.getState().choice).toBe('quick');
    await user.keyboard('{ArrowLeft}');
    expect(useMode.getState().choice).toBe('quick');

    await user.keyboard('{End}');
    expect(useMode.getState().choice).toBe('cascade');
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

  it('focusing the control re-reads the balance — a page left open overnight must not promise a spent turn', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(hoisted.creditCalls).toBe(1));
    await user.click(slider());
    await waitFor(() => expect(hoisted.creditCalls).toBe(2));
  });
});

describe('DepthControl — the credit meter (D-MW-25), now over a 0/1/2 ladder', () => {
  it('shows the credit balance from the server, and never invents one', async () => {
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('credits-badge')).toHaveTextContent('97 of 100 this month'));
  });

  it('with metering dark (404 -> null) there is NO badge and every notch is free', async () => {
    hoisted.credits = null;
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(hoisted.creditCalls).toBe(1));
    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(useMode.getState().choice).toBe('cascade');
    expect(screen.queryByTestId('credits-badge')).toBeNull();
    // No meter, no charge trade to state.
    expect(screen.queryByTestId('credits-charge-note')).toBeNull();
    expect(screen.queryByTestId('depth-blocked-deep')).toBeNull();
    expect(screen.queryByTestId('depth-blocked-cascade')).toBeNull();
  });

  it('states the disconnect-after-compute charge trade on screen while a metered notch is selected', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('credits-badge')).toBeTruthy());
    expect(screen.queryByTestId('credits-charge-note')).toBeNull(); // Scan is free: nothing to warn about
    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(screen.getByTestId('credits-charge-note')).toHaveTextContent('they still count');
  });

  it('the charge trade is stated at the PRICE THAT IS SELECTED — never "a credit" under a two-credit tier', async () => {
    // The note was the singular constant under every metered notch, so a Cascade selection read "two
    // credits" in the hint one line above and "a credit is spent" in the note one line below. Two prices
    // for the same turn, on the same screen, is exactly what a credit surface exists to make impossible.
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('credits-badge')).toBeTruthy());

    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(screen.getByTestId('credits-charge-note').textContent).toBe(CHARGE_NOTE);
    expect(screen.getByTestId('depth-hint')).toHaveTextContent('one credit');

    await user.click(screen.getByTestId('depth-notch-cascade'));
    const note = screen.getByTestId('credits-charge-note').textContent ?? '';
    expect(note).toContain('two credits are spent when the answer is produced');
    expect(note).toContain('they still count');
    expect(note).not.toContain('a credit is spent'); // the singular is the defect, not a synonym
    expect(screen.getByTestId('depth-hint')).toHaveTextContent('two credits'); // and the two lines agree
  });

  it('out of credits: BOTH metered notches are un-choosable and each reason carries the RESET DATE in UTC', async () => {
    hoisted.credits = { remaining: 0, limit: 100, reset_at: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('depth-blocked-deep')).toBeTruthy());
    expect(screen.getByTestId('depth-blocked-deep')).toHaveTextContent('2026-09-01');
    expect(screen.getByTestId('depth-blocked-cascade')).toHaveTextContent('2026-09-01');
    expect(screen.getByTestId('credits-badge')).toHaveTextContent('0 of 100 this month');

    await user.click(screen.getByTestId('depth-notch-deep'));
    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(useMode.getState().choice).toBe('quick'); // nothing moved
  });

  it('a balance that cannot AFFORD the top notch blocks it and says the price — the clause a 0/1 ladder never needed', async () => {
    // One credit left is not "exhausted", but a Cascade turn costs two and the server refuses that at the
    // gate (429, before a byte streams). Analysis is still perfectly selectable at the same balance.
    hoisted.credits = { remaining: 1, limit: 100, reset_at: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('depth-blocked-cascade')).toBeTruthy());
    // THE WHOLE SENTENCE, not a substring of it — because it is HALF OF A PAIR. The server refuses the
    // same turn with `leviathan.graphrag.server._CREDITS_INSUFFICIENT_DETAIL`, which renders
    // "this tier costs two credits and you have 1 left; the grant resets 2026-09-01 (UTC)", and every
    // word from "costs" onward is deliberately identical to this line: a user can meet this refusal here
    // and then again as a toast (a balance up to 30s stale, a second tab, a direct API call), and two
    // vocabularies for one fact reads as two systems disagreeing about their money. The permitted
    // differences are the tier's NAME (this side has the label; the server's only name for it is the wire
    // identifier `max`) and the clause join. `config_check.check_cascade_notch` clause (vii) is the reader
    // that holds the pair together across the two languages; this pins this half of it verbatim.
    expect(screen.getByTestId('depth-blocked-cascade').textContent).toBe(
      'Cascade costs two credits and you have 1 left — the grant resets 2026-09-01 (UTC)',
    );
    expect(screen.queryByTestId('depth-blocked-deep')).toBeNull();

    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(useMode.getState().choice).toBe('quick'); // refused, and it says why
    await user.click(screen.getByTestId('depth-notch-deep'));
    expect(useMode.getState().choice).toBe('deep'); // one credit still buys one credit's worth
  });

  it('a blocked notch is STEPPED OVER, not stalled on — Cascade stays reachable past a blocked Analysis', async () => {
    // A deployment that serves Scan and Cascade but not Analysis is the cleanest way to block exactly one
    // middle notch; the property under test is the SKIP, not the reason for it.
    vi.stubEnv('VITE_MODES', 'quick,max');
    const user = userEvent.setup();
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('depth-blocked-deep')).toBeTruthy());
    slider().focus();
    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('cascade');
  });
});

describe('DepthControl — the served-roster gate (Cascade ships DARK)', () => {
  it('a deployment that does not name `max` renders the notch blocked, with the reason as its own sentence', async () => {
    // `max` is in reasoning_modes.DARK_NAMES: honored only where GRAPHRAG_MODES NAMES it, and never by the
    // wildcard. A build told nothing must therefore refuse the notch rather than sell a two-credit turn
    // the orchestrator would resolve to `standard`.
    // AND THE LINE BELOW IS PERMANENT ON SUCH A BUILD -- adjudicated 2026-09-07, kept on purpose. Every
    // other blocked reason is transient (a balance refills); this one is fixed for the life of the bundle,
    // so it stands under the ask bar for every user of a build that was told nothing. It STAYS, verbatim:
    // the notch is drawn (faint) whether or not it can be reached, and a visible stop with no sentence
    // saying why is the silent-drop trap with better manners. See DepthControl.blockedReason's first clause.
    vi.stubEnv('VITE_MODES', '');
    const user = userEvent.setup();
    mount(<DepthControl />);
    // The label prefix is dropped when the reason opens with it: the line is a sentence, not a stutter.
    expect(screen.getByTestId('depth-blocked-cascade').textContent).toBe(
      'Cascade is not yet enabled on this deployment',
    );
    expect(screen.queryByTestId('depth-blocked-quick')).toBeNull();
    expect(screen.queryByTestId('depth-blocked-deep')).toBeNull();

    await user.click(screen.getByTestId('depth-notch-cascade'));
    expect(useMode.getState().choice).toBe('quick');
  });

  it('the gate also stops the keyboard: End lands on Analysis, the deepest tier this deployment runs', async () => {
    vi.stubEnv('VITE_MODES', '');
    const user = userEvent.setup();
    mount(<DepthControl />);
    slider().focus();
    await user.keyboard('{End}');
    expect(useMode.getState().choice).toBe('deep');
    await user.keyboard('{ArrowRight}');
    expect(useMode.getState().choice).toBe('deep'); // and it does not step onto the wall
  });

  it('the WILDCARD does not unlock it — `on` means serving_names(), which excludes every dark preset', async () => {
    vi.stubEnv('VITE_MODES', 'on');
    mount(<DepthControl />);
    expect(screen.getByTestId('depth-blocked-cascade').textContent).toBe(
      'Cascade is not yet enabled on this deployment',
    );
  });

  it('a STORED Cascade selection is CORRECTED, not merely annotated — the gesture gate was never enough', async () => {
    // THE 2026-09-07 FIX, at the seam where it was measured to fail. `blocked()` fences `pick`, `step` and
    // `jump`; NONE of them runs for a value that is already in the store — a v3 blob written by a bundle
    // that was told `max`, or a direct setState. Before the fix this exact mount rendered the blocked
    // sentence AND kept aria-valuetext "Cascade" AND submitted mode=max (see Shell.dossier.test.tsx for the
    // wire half). What must be true now: the screen shows the tier that will actually run.
    vi.stubEnv('VITE_MODES', '');
    useMode.setState({ choice: 'cascade' });
    mount(<DepthControl />);

    expect(slider().getAttribute('aria-valuetext')).toBe('Analysis');
    expect(slider().getAttribute('aria-valuenow')).toBe('1');
    expect(screen.getByTestId('depth-value')).toHaveTextContent('Analysis');
    expect(screen.getByTestId('depth-hint')).toHaveTextContent('one credit');
    expect(screen.getByTestId('depth-hint')).not.toHaveTextContent('two credits');
    // The reason is still on screen: the correction explains itself rather than happening in silence.
    expect(screen.getByTestId('depth-blocked-cascade').textContent).toBe(
      'Cascade is not yet enabled on this deployment',
    );
    expect(screen.getByTestId('depth-notch-cascade').getAttribute('data-selected')).toBeNull();
    expect(screen.getByTestId('depth-notch-deep').getAttribute('data-selected')).toBe('true');
  });

  it('the correction goes DOWN the ladder, all the way to the free tier when it has to', async () => {
    vi.stubEnv('VITE_MODES', 'quick'); // a deployment running neither metered tier
    useMode.setState({ choice: 'cascade' });
    mount(<DepthControl />);
    expect(slider().getAttribute('aria-valuetext')).toBe('Scan');
    expect(screen.getByTestId('depth-blocked-deep')).toBeTruthy();
    expect(screen.getByTestId('depth-blocked-cascade')).toBeTruthy();
    // A corrected selection is never a metered one by accident: no charge note under a free tier.
    expect(screen.queryByTestId('credits-charge-note')).toBeNull();
  });
});

describe('DepthControl — Deep Research is a standalone control, lights off until V1.2', () => {
  it('renders at the right of the ask bar, disabled-but-focusable, visibly OFF, carrying the V1.2 sentence', () => {
    mount(<DepthControl />);
    const b = screen.getByTestId('deep-research-button');
    expect(b.textContent).toContain('Deep Research');
    expect(b.textContent?.toLowerCase()).toContain('v1.2'); // the tag on the pill, readable without hovering
    // NOT the `disabled` attribute: a disabled button takes no focus, and a tooltip nobody can reach by
    // keyboard is not a tooltip. `aria-disabled` + no handler is what makes it inert without hiding it.
    expect(b.getAttribute('aria-disabled')).toBe('true');
    expect(b.hasAttribute('disabled')).toBe(false);
    expect(b.getAttribute('tabindex')).toBe('0');
    // The accessible name carries the sentence verbatim for readers that never hover.
    expect(b.getAttribute('aria-label')).toContain(DEEP_RESEARCH_DARK_TITLE);
    expect(b.getAttribute('aria-label')).toContain('Deep Research will be available in Leviathan V1.2');
    // LIGHTS OFF, LEGIBLY (owner's word 2026-09-07 after the first cut was invisible at 40% opacity):
    // no opacity fade, a dashed border, an unlit lamp dot. The pin is on the CLASSES because the look
    // is the contract this time.
    expect(b.className).not.toMatch(/opacity-/);
    expect(b.className).toContain('border-dashed');
    expect(b.className).toContain('text-text-dim');
    expect(screen.getByTestId('deep-research-lamp')).toBeTruthy();
    // No native title: the sentence would otherwise show twice (browser tooltip + ours).
    expect(b.hasAttribute('title')).toBe(false);
  });

  it('the V1.2 sentence opens as the house tooltip on hover and on keyboard focus', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    const b = screen.getByTestId('deep-research-button');
    expect(screen.queryByRole('tooltip')).toBeNull();
    await user.hover(b);
    const tip = await screen.findByRole('tooltip');
    expect(tip.textContent).toContain(DEEP_RESEARCH_DARK_TITLE);
    expect(tip.textContent).toContain('lights off');
    await user.unhover(b);
    // Keyboard: focus alone opens it (a disabled button could never receive this focus).
    b.focus();
    expect((await screen.findByRole('tooltip')).textContent).toContain(DEEP_RESEARCH_DARK_TITLE);
  });

  it('clicking it does nothing at all — it is not a notch and it never submits', async () => {
    const user = userEvent.setup();
    mount(<DepthControl />);
    await user.click(screen.getByTestId('deep-research-button'));
    expect(useMode.getState().choice).toBe('quick');
    expect(slider().getAttribute('aria-valuetext')).toBe('Scan');
  });

  it('the dossier quota badge is GONE with it — no meter for a resource nobody can spend', async () => {
    mount(<DepthControl />);
    await waitFor(() => expect(screen.getByTestId('credits-badge')).toBeTruthy());
    // It rode the old top notch. Dropped, not moved: see the component header. The seam it read
    // (api/dossier.getDossierQuota + DOSSIER_QUOTA_KEY) is untouched and still used by the submit path.
    expect(screen.queryByTestId('dossier-quota-badge')).toBeNull();
  });
});

describe('Composer docks the depth control (both variants)', () => {
  it('the follow-up composer carries it, and the selection is what a later submit runs at', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    mount(<Composer onSubmit={onSubmit} streaming={false} autoFocus={false} />);
    expect(screen.getByTestId('depth-control')).toBeTruthy();

    await user.click(screen.getByTestId('depth-notch-cascade'));
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    await user.type(ta, 'why is wheat tight?');
    await user.keyboard('{Enter}');

    // The composer stays a TEXT BOX: it submits the question and nothing else. The selection it made is
    // read back off the store by Shell at submit (Shell.tsx: `useMode.getState().choice`).
    expect(onSubmit).toHaveBeenCalledWith('why is wheat tight?');
    expect(useMode.getState().choice).toBe('cascade');
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
