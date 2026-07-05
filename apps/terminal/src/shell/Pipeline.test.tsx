import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { StampedStage } from '@/api/useTurn';
import { Pipeline } from './Pipeline';

describe('Pipeline (5.6)', () => {
  it('shows retrieval progress, numbers table ticks, and the synthesizing row', () => {
    const stages: StampedStage[] = [
      { stage: 'planning', intent: 'hybrid', contracts: ['corn'], ts: 0 },
      { stage: 'walking', ts: 100 },
      { stage: 'retrieving', done: 3, total: 7, ts: 2000 },
      { stage: 'numbers', calls: 2, running: true, table: 'silver_psd', ts: 2500 },
      { stage: 'synthesizing', ts: 9000 },
    ];
    render(<Pipeline stages={stages} done={false} />);
    expect(screen.getByText('3/7 nodes filled')).toBeTruthy();
    expect(screen.getByText('2 looked up · silver_psd')).toBeTruthy();
    expect(screen.getByText('drafting the note…')).toBeTruthy();
    expect(screen.getByText('walking the cascade DAG…')).toBeTruthy();
  });

  it('final events replace progress ticks and elapsed renders', () => {
    const stages: StampedStage[] = [
      { stage: 'retrieving', done: 3, total: 7, ts: 1000 },
      { stage: 'retrieving', props: 24, ts: 4200 },
      { stage: 'synthesizing', ts: 4300 },
      { stage: 'verifying', checked: 3, stripped: 1, ts: 9000 },
    ];
    render(<Pipeline stages={stages} done={true} />);
    expect(screen.getByText('24 props @ ≤ as-of')).toBeTruthy();
    expect(screen.getByText('3 cited · 1 stripped')).toBeTruthy();
    expect(screen.getByText('3.3s')).toBeTruthy(); // retrieving: 1000 -> synthesizing first ts 4300
  });

  it('never crashes on an unknown stage name from a newer backend', () => {
    const stages: StampedStage[] = [
      { stage: 'planning', intent: 'reasoning', ts: 0 },
      { stage: 'quantum_flux', ts: 50 } as StampedStage,
    ];
    expect(() => render(<Pipeline stages={stages} done={false} />)).not.toThrow();
  });
});
