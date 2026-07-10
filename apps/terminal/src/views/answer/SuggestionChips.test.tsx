import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SuggestionChips } from './SuggestionChips';

describe('SuggestionChips (6.2)', () => {
  it('renders chips and click fires onAsk with the question', () => {
    const onAsk = vi.fn();
    render(<SuggestionChips items={['How thin are stocks?', 'What about frost?']} onAsk={onAsk} />);
    const chips = screen.getByTestId('suggestion-chips');
    expect(chips.querySelectorAll('button')).toHaveLength(2);
    fireEvent.click(screen.getByText('What about frost?'));
    expect(onAsk).toHaveBeenCalledWith('What about frost?');
  });

  it('renders NOTHING for an empty list (chips are a nicety, never an error state)', () => {
    render(<SuggestionChips items={[]} onAsk={() => {}} />);
    expect(screen.queryByTestId('suggestion-chips')).toBeNull();
  });

  it('P9-E1a: watch chips render PREPENDED and click PREFILLS via onPrefill, never onAsk', () => {
    const onAsk = vi.fn();
    const onPrefill = vi.fn();
    render(
      <SuggestionChips
        items={['How thin are stocks?']}
        onAsk={onAsk}
        watchItems={['certified stocks through July']}
        onPrefill={onPrefill}
      />,
    );
    const buttons = screen.getByTestId('suggestion-chips').querySelectorAll('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0]!.textContent).toBe('certified stocks through July'); // watch chip first
    fireEvent.click(screen.getByTestId('watch-chip'));
    expect(onPrefill).toHaveBeenCalledWith('certified stocks through July');
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('P9-E1a: watch chips alone still render the row (server suggestions may be empty)', () => {
    render(<SuggestionChips items={[]} onAsk={() => {}} watchItems={['a']} onPrefill={() => {}} />);
    expect(screen.getByTestId('suggestion-chips')).toBeTruthy();
  });
});
