import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Composer } from './Composer';

describe('Composer', () => {
  it('Enter submits + clears; Shift+Enter does not submit', () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} streaming={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'why is wheat tight?' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith('why is wheat tight?');
    expect(ta.value).toBe('');
  });

  it('is disabled while streaming and refocuses on completion', () => {
    const { rerender } = render(<Composer onSubmit={() => {}} streaming={true} autoFocus={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    expect(ta.disabled).toBe(true);
    rerender(<Composer onSubmit={() => {}} streaming={false} autoFocus={false} />);
    expect(ta.disabled).toBe(false);
    expect(document.activeElement).toBe(ta);
  });

  it('D-TW-5a: a MODIFIED Enter is left to the global hotkey — one keystroke, one turn', () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} streaming={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'why is wheat tight?' } });
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true });
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(ta.value).toBe('why is wheat tight?'); // and nothing was cleared out from under the user
  });

  it('ignores empty submissions', () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} streaming={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
