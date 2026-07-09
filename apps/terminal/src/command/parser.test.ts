import { describe, expect, it } from 'vitest';
import { parseCommand } from './parser';

describe('parseCommand (function codes → intents)', () => {
  it('"C deep" and a bare ticker fold into an ask scoped to that contract (5.6 view-prune)', () => {
    expect(parseCommand('C deep')).toEqual({ kind: 'ask', contract: 'corn', question: 'C deep' });
    expect(parseCommand('KC')).toEqual({ kind: 'ask', contract: 'arabica_coffee', question: 'KC' });
  });

  it('"KC vs RC" folds into an ask (the compare view was removed)', () => {
    expect(parseCommand('KC vs RC')).toEqual({
      kind: 'ask',
      contract: 'arabica_coffee',
      question: 'KC vs RC',
    });
  });

  it('"SB su-ratio" is a numbers lookup (metric token)', () => {
    expect(parseCommand('SB su-ratio')).toEqual({
      kind: 'numbers',
      contract: 'raw_sugar',
      metric: 'su-ratio',
    });
  });

  it('"KC frost 2021" is an ask scoped to the contract', () => {
    expect(parseCommand('KC frost 2021')).toEqual({
      kind: 'ask',
      contract: 'arabica_coffee',
      question: 'KC frost 2021',
    });
  });

  it('an unrecognized head is a natural-language question', () => {
    expect(parseCommand('what would a July frost do to arabica?')).toEqual({
      kind: 'nl',
      question: 'what would a July frost do to arabica?',
    });
  });

  it('extracts an "as-of <date>" suffix without leaving it in the text', () => {
    expect(parseCommand('KC frost as-of 2013-03-01')).toEqual({
      kind: 'ask',
      contract: 'arabica_coffee',
      question: 'KC frost',
      asofOverride: '2013-03-01',
    });
    expect(parseCommand('is corn convex as-of 2024-01-15')).toEqual({
      kind: 'nl',
      question: 'is corn convex',
      asofOverride: '2024-01-15',
    });
  });
});
