import { fireEvent, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useHotkeys, type HotkeyHandlers } from './useHotkeys';

function Harness({ handlers }: { handlers: HotkeyHandlers }) {
  useHotkeys(handlers);
  return <input aria-label="cmd" />;
}

describe('useHotkeys', () => {
  it('⌘\\ toggles the thread sidebar (even from an input) and ⌘↵ submits from outside a text field', () => {
    const onToggleThread = vi.fn();
    const onSubmit = vi.fn();
    const { getByRole } = render(<Harness handlers={{ onToggleThread, onSubmit }} />);
    fireEvent.keyDown(getByRole('textbox'), { key: '\\', metaKey: true });
    fireEvent.keyDown(document, { key: 'Enter', metaKey: true });
    expect(onToggleThread).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('D-TW-14b/15: ⌘K and 1-4 are no longer bound — both fall through to the browser', () => {
    const onSubmit = vi.fn();
    const onHelp = vi.fn();
    render(<Harness handlers={{ onSubmit, onHelp }} />);
    // A handler-less binding must not merely be inert: ⌘K has to reach the browser (find-in-page/omnibox),
    // so the listener must not preventDefault it either.
    const k = new KeyboardEvent('keydown', { key: 'k', metaKey: true, cancelable: true, bubbles: true });
    document.dispatchEvent(k);
    expect(k.defaultPrevented).toBe(false);
    const one = new KeyboardEvent('keydown', { key: '1', cancelable: true, bubbles: true });
    document.dispatchEvent(one);
    expect(one.defaultPrevented).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onHelp).not.toHaveBeenCalled();
  });

  it('D-TW-5b: ⌘↵ is suppressed while typing — the focused field owns Enter', () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(<Harness handlers={{ onSubmit }} />);
    fireEvent.keyDown(getByRole('textbox'), { key: 'Enter', metaKey: true });
    fireEvent.keyDown(getByRole('textbox'), { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled(); // else the composer's ⌘↵ fired TWO turns
  });

  it(', and . step the as-of; Shift makes the step large', () => {
    const onAsOfStep = vi.fn();
    render(<Harness handlers={{ onAsOfStep }} />);
    fireEvent.keyDown(document, { key: ',' });
    fireEvent.keyDown(document, { key: '.', shiftKey: true });
    expect(onAsOfStep).toHaveBeenNthCalledWith(1, -1, false);
    expect(onAsOfStep).toHaveBeenNthCalledWith(2, 1, true);
  });

  it('does not hijack a single key while typing in an input', () => {
    const onHelp = vi.fn();
    const { getByRole } = render(<Harness handlers={{ onHelp }} />);
    fireEvent.keyDown(getByRole('textbox'), { key: '?' });
    expect(onHelp).not.toHaveBeenCalled();
  });
});
