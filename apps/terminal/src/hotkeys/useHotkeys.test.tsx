import { fireEvent, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useHotkeys, type HotkeyHandlers } from './useHotkeys';

function Harness({ handlers }: { handlers: HotkeyHandlers }) {
  useHotkeys(handlers);
  return <input aria-label="cmd" />;
}

describe('useHotkeys', () => {
  it('⌘K opens the palette and ⌘↵ submits (even from an input)', () => {
    const onPalette = vi.fn();
    const onSubmit = vi.fn();
    render(<Harness handlers={{ onPalette, onSubmit }} />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    fireEvent.keyDown(document, { key: 'Enter', metaKey: true });
    expect(onPalette).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledOnce();
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
