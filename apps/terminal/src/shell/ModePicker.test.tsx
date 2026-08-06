import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_MODE, useMode } from '@/store/mode';
import { Composer } from './Composer';
import { ModePicker } from './ModePicker';

describe('ModePicker (D-AM-14 — docked at the ask bar)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ mode: DEFAULT_MODE });
  });

  it('renders standard by default, with the menu closed', () => {
    render(<ModePicker />);
    const trigger = screen.getByTestId('mode-trigger');
    expect(trigger).toHaveTextContent('standard');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
  });

  it('opens to exactly three options, each with its time expectation and its reason', async () => {
    const user = userEvent.setup();
    render(<ModePicker />);
    await user.click(screen.getByTestId('mode-trigger'));

    const options = screen.getAllByRole('menuitemradio');
    expect(options.map((o) => o.getAttribute('data-testid'))).toEqual([
      'mode-option-quick',
      'mode-option-standard',
      'mode-option-deep',
    ]);
    // Exactly one is checked, and it is the current selection.
    expect(options.filter((o) => o.getAttribute('aria-checked') === 'true')).toHaveLength(1);
    expect(screen.getByTestId('mode-option-standard').getAttribute('aria-checked')).toBe('true');

    // The per-mode expected-time hint (item 3): relative words, in the app's register.
    expect(screen.getByTestId('mode-option-quick')).toHaveTextContent('faster');
    expect(screen.getByTestId('mode-option-quick')).toHaveTextContent('narrower evidence');
    expect(screen.getByTestId('mode-option-standard')).toHaveTextContent('baseline');
    expect(screen.getByTestId('mode-option-deep')).toHaveTextContent('~2-3x slower');
    expect(screen.getByTestId('mode-option-deep')).toHaveTextContent('all cascade legs');
  });

  it('choosing a mode updates the trigger, closes the menu, and PERSISTS', async () => {
    const user = userEvent.setup();
    render(<ModePicker />);
    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-deep'));

    expect(useMode.getState().mode).toBe('deep');
    expect(screen.getByTestId('mode-trigger')).toHaveTextContent('deep');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    const blob = JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as { state?: { mode?: string } };
    expect(blob.state?.mode).toBe('deep');
  });

  it('a persisted choice is what the picker boots showing', () => {
    useMode.setState({ mode: 'quick' });
    render(<ModePicker />);
    expect(screen.getByTestId('mode-trigger')).toHaveTextContent('quick');
  });

  it('is fully keyboard-driven: ArrowDown opens onto the CURRENT choice, arrows move, Enter chooses', async () => {
    const user = userEvent.setup();
    render(<ModePicker />);
    const trigger = screen.getByTestId('mode-trigger');
    trigger.focus();

    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('mode-menu')).toBeTruthy();
    // Focus enters at the state the user is in, so the next arrow is a relative move, not a hunt.
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-standard'));

    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-deep'));
    await user.keyboard('{ArrowDown}'); // wraps
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-quick'));
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(screen.getByTestId('mode-option-deep'));

    await user.keyboard('{Enter}');
    expect(useMode.getState().mode).toBe('deep');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    // Focus comes back to the trigger: a keyboard user lands one Shift+Tab from the textarea.
    expect(document.activeElement).toBe(screen.getByTestId('mode-trigger'));
  });

  it('Escape closes without choosing and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    render(<ModePicker />);
    const trigger = screen.getByTestId('mode-trigger');
    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    expect(useMode.getState().mode).toBe('standard');
    expect(document.activeElement).toBe(trigger);
  });

  it('a click outside closes it', async () => {
    const user = userEvent.setup();
    render(
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
    const { rerender } = render(<ModePicker disabled={false} />);
    await user.click(screen.getByTestId('mode-trigger'));
    expect(screen.getByTestId('mode-menu')).toBeTruthy();

    rerender(<ModePicker disabled={true} />);
    expect(screen.queryByTestId('mode-menu')).toBeNull();
    expect((screen.getByTestId('mode-trigger') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('Composer docks the picker (both variants)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ mode: DEFAULT_MODE });
  });

  it('the follow-up composer carries it, and the selection is what a later ask runs at', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} streaming={false} autoFocus={false} />);
    expect(screen.getByTestId('mode-picker')).toBeTruthy();

    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-quick'));

    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    await user.type(ta, 'why is wheat tight?');
    await user.keyboard('{Enter}');

    // The composer stays a TEXT BOX: it submits the question and nothing else. The mode it selected is
    // read back off the store by Shell at submit (Shell.tsx: `mode: useMode.getState().mode`).
    expect(onSubmit).toHaveBeenCalledWith('why is wheat tight?');
    expect(useMode.getState().mode).toBe('quick');
  });

  it('the hero (empty-state) composer carries it too', () => {
    render(<Composer onSubmit={() => {}} streaming={false} hero autoFocus={false} />);
    expect(screen.getByTestId('composer-hero')).toBeTruthy();
    expect(screen.getByTestId('mode-picker')).toBeTruthy();
  });

  it('the picker is disabled exactly when the textarea is', () => {
    render(<Composer onSubmit={() => {}} streaming={true} autoFocus={false} />);
    expect((screen.getByTestId('composer') as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByTestId('mode-trigger') as HTMLButtonElement).disabled).toBe(true);
  });
});
