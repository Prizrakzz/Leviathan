import type { RespondResult, StageEvent } from './schema';
import type { StreamHandlers } from './sse';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A representative streamed turn (the KC-frost example from the design) — drives the whole Phase-2 gate. */
export const MOCK_RESULT: RespondResult = {
  answer:
    '**TL;DR** A severe July frost in Paraná tightens the arabica balance into an already-thin stocks regime — ' +
    'the response turns convex once the buffer is gone.\n\n' +
    'Frost damage to Brazilian arabica is the classic asymmetric shock: below the tipping buffer, further ' +
    'losses map non-linearly to price [1]. With stocks-to-use already low, the convergence conditions are ' +
    'consistent with a bullish supply squeeze [2].',
  structured: {
    tldr: 'A July frost tightens an already-thin arabica balance — the response turns convex past the buffer.',
    mechanism: 'frost → tree damage → lower output → thinner stocks-to-use → convex price response',
    diagram_mermaid: 'graph LR; frost-->stocks; stocks-->price',
    sources: [{ ref: 1, source: 'usda_gain_coffee' }, { ref: 2, source: 'usda_wasde' }],
  },
  contract: 'arabica_coffee',
  contracts: ['arabica_coffee'],
  citations: [
    { kind: 'evidence', ref: 1, source: 'usda_gain_coffee', date: '2021-07-20' },
    { kind: 'evidence', ref: 2, source: 'usda_wasde', date: '2021-07' },
  ],
  evidence: [
    { source: 'usda_gain_coffee', date: '2021-07-20', text: 'Frost hit key Paraná growing regions.' },
    { source: 'usda_wasde', date: '2021-07', text: 'Arabica stocks-to-use at multi-year lows.' },
  ],
  number_calls: [
    { query: { table: 'silver_psd', metric: 'su_ratio' }, rows: [{ value: '0.36', z: '-1.4' }] },
    { query: { table: 'silver_oni', metric: 'oni' }, rows: [{ value: '0.4' }] },
  ],
  intent: 'hybrid',
  model: 'claude-sonnet-4-6',
  trace: {
    graph_version: '3a69acfb87c5',
    fired_regimes: [{ contract: 'arabica_coffee', name: 'bullish_supply_squeeze' }],
  },
  asof: '2021-07-20',
};

/** The mock stream: the same five ordered ticks the backend emits, then the terminal result. */
export async function mockRespondStream(
  params: { question: string; asof?: string },
  h: StreamHandlers,
  opts: { delay?: number } = {},
): Promise<void> {
  const delay = opts.delay ?? 55;
  const stages: StageEvent[] = [
    { stage: 'accepted' },
    { stage: 'planning', intent: 'hybrid', contracts: ['arabica_coffee'] },
    { stage: 'walking', nodes: 7, regimes: 2 },
    { stage: 'retrieving', props: 24 },
    { stage: 'numbers', calls: 2 },
    { stage: 'verifying', checked: 4, stripped: 0 },
  ];
  for (const s of stages) {
    await sleep(delay);
    h.onStage?.(s);
  }
  await sleep(delay);
  h.onResult?.({ ...MOCK_RESULT, asof: params.asof ?? MOCK_RESULT.asof, question: params.question });
}

/** A tiny convergence fixture for the placeholder Convergence view (Phase 3 renders the real heatmap). */
export const MOCK_CONVERGENCE = {
  asof: '2021-07-20',
  graph_version: '3a69acfb87c5',
  rows: [
    {
      contract: 'arabica_coffee',
      regimes: [
        {
          name: 'bullish_supply_squeeze',
          direction: '+',
          matched: ['frost', 'low_stocks'],
          threshold: 2,
          fired: true,
          n_active: 2,
          proximity: 1,
        },
      ],
      drivers: [{ id: 'frost', live: true, verdict: 'observed', z: -2.1, value: 0.09, unit: 'ratio', ref: 'su' }],
    },
  ],
};
