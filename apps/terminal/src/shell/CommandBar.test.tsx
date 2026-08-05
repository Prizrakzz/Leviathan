import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CommandBar } from './CommandBar';

describe('CommandBar', () => {
  it('plain Enter submits the trimmed value; a modified Enter belongs to the global hotkey', () => {
    const onSubmit = vi.fn();
    render(<CommandBar value="  KC frost 2021  " onChange={() => {}} onSubmit={onSubmit} disabled={false} />);
    const input = screen.getByLabelText('command');
    fireEvent.keyDown(input, { key: 'Enter', metaKey: true });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith('KC frost 2021');
  });

  it('D-TW-5c: locked while a turn streams, with the honest hint (the Composer idiom)', () => {
    const { rerender } = render(
      <CommandBar value="KC frost 2021" onChange={() => {}} onSubmit={() => {}} disabled={true} />,
    );
    const input = screen.getByLabelText('command') as HTMLInputElement;
    // Before this, an Enter here mid-turn silently ABORTED the live answer and started another one.
    expect(input.disabled).toBe(true);
    expect(input.placeholder).toContain('answering');
    rerender(<CommandBar value="KC frost 2021" onChange={() => {}} onSubmit={() => {}} disabled={false} />);
    expect(input.disabled).toBe(false);
    expect(input.placeholder).toContain('convexity question');
  });
});
