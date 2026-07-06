import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mockThreadTurns } from '@/api/mock';
import type { components } from '@/api/types.gen';
import { PastTurn } from './AnswerView';

type TurnRecord = components['schemas']['TurnRecord'];

describe('PastTurn (S2.2 — citation chips need a Tooltip.Provider)', () => {
  it('renders a durable turn WITH resolved citations without throwing', () => {
    const turn = mockThreadTurns('t-mock1').turns[0] as unknown as TurnRecord;
    // Precondition: the fixture actually resolves [n] chips — otherwise this test proves nothing (the whole
    // reason the bug hid was an empty-sources fixture that produced no chips).
    render(<PastTurn t={turn} />);
    // The [1] chip is a CitationChip → a Radix Tooltip trigger button. BEFORE the fix, rendering it here
    // (a PastTurn with no Tooltip.Provider) threw "Tooltip must be used within TooltipProvider" — which,
    // being outside the answer boundary, blanked the whole terminal.
    const buttons = screen.getAllByRole('button');
    expect(buttons.some((b) => b.textContent?.includes('[1]'))).toBe(true);
    expect(screen.getByTestId('past-turn')).toBeTruthy();
  });
});
