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
});
