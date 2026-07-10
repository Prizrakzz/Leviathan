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

describe('PastTurn sections branch (P9-C: durable turns render per-kind IN LOCKSTEP with the live Note)', () => {
  it('a durable turn persisted WITH sections renders the per-kind view (still the reduced turn shape)', () => {
    const turn = mockThreadTurns('t-mock1').turns[0] as unknown as TurnRecord;
    render(<PastTurn t={turn} />);
    expect(screen.getByTestId('sections')).toBeTruthy();
    expect(screen.getByTestId('section-disagreement').className).toContain('border-amber');
    // Reduced view stays reduced: no sources row, no numbers panel on past turns.
    expect(screen.queryByTestId('numbers')).toBeNull();
  });

  it('a mechanism-only durable turn (old Dynamo shape) keeps the flat fallback render', () => {
    const turn = {
      question: 'old turn',
      answer: '',
      structured: { tldr: 'Old headline.', mechanism: 'old flat mechanism body' },
      asof: '2021-07-20',
    } as unknown as TurnRecord;
    render(<PastTurn t={turn} />);
    expect(screen.queryByTestId('sections')).toBeNull();
    expect(screen.getByTestId('past-turn').textContent).toContain('old flat mechanism body');
  });
});
