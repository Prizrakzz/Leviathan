import type { components } from './types.gen';
import graphArabica from './fixtures/graph.arabica.json';
import type { RespondResult, StageEvent } from './schema';
import type { StreamHandlers } from './sse';

type Schemas = components['schemas'];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── the canonical good turn (KC frost, from the design) ──────────────────────────────────────────────
const EVIDENCE = [
  {
    ref: 1,
    source: 'usda_gain_coffee',
    date: '2021-07-20',
    source_key: 's3://gain/kc-2021-07-20',
    text: 'A damaging frost hit southern Minas Gerais and Paraná coffee districts overnight.',
    contract: 'arabica_coffee',
    cited: true,
  },
  {
    ref: 2,
    source: 'usda_wasde',
    date: '2021-07-12',
    source_key: 's3://wasde/2021-07',
    text: '2021/22 Brazil arabica production lowered on frost and drought; stocks-to-use near multi-year lows.',
    contract: 'arabica_coffee',
    cited: true,
  },
  {
    source: 'ico_report',
    date: '2021-07-05',
    source_key: 's3://ico/2021-07',
    text: 'Global coffee balance narrowing into 2021/22 on lower Brazilian output.',
    contract: 'arabica_coffee',
    cited: false,
  },
  {
    source: 'usda_gain_coffee',
    date: '2021-06-28',
    source_key: 's3://gain/kc-2021-06-28',
    text: 'Dry conditions across the arabica belt through June ahead of the frost window.',
    contract: 'arabica_coffee',
    cited: false,
  },
];

const NUMBER_CALLS = [
  {
    ref: 'N1',
    query: { table: 'silver_psd', metric: 'su_ratio', commodity: 'arabica_coffee' },
    rows: [{ value: '0.36', z: '-1.4', knowledge_date: '2021-06-11', period: '2021' }],
    status: 'ok',
  },
  {
    ref: 'N2',
    query: { table: 'silver_oni', metric: 'oni' },
    rows: [{ value: '0.4', z: '0.3', knowledge_date: '2021-07-01', period: '2021-06' }],
    status: 'ok',
  },
  {
    ref: 'N3',
    query: { table: 'silver_psd', metric: 'ending_stocks_mt', commodity: 'arabica_coffee' },
    rows: [],
    status: 'not_yet_pub',
  },
];

function goodResult(question: string, asof: string): RespondResult {
  return {
    answer: '',
    structured: {
      tldr:
        'A July frost landing in an off-year would compound an already-thin buffer, producing a convex ' +
        '(larger-than-linear) ICE arabica spike. [1][2]',
      mechanism:
        "Radiative frost in Brazil's southern arabica belt kills buds → next crop ↓ [1]; in a biennial " +
        'off-year the amplifier interaction compounds the loss [2]; with tenderable stocks already low ' +
        '[N1] the price response steepens past the buffer kink.',
      diagram_mermaid: 'graph LR; frost-->stocks; stocks-->price',
      sources: [
        { ref: 1, source: 'usda_gain_coffee', date: '2021-07-20' },
        { ref: 2, source: 'usda_wasde', date: '2021-07-12' },
        { ref: 'N1', source: 'silver_psd', date: '2021-06-11' },
      ],
    },
    contract: 'arabica_coffee',
    contracts: ['arabica_coffee'],
    citations: [
      { kind: 'evidence', ref: 1, source: 'usda_gain_coffee', date: '2021-07-20' },
      { kind: 'evidence', ref: 2, source: 'usda_wasde', date: '2021-07-12' },
      { kind: 'number', ref: 'N1', source: 'silver_psd', date: '2021-06-11' },
    ],
    evidence: EVIDENCE,
    number_calls: NUMBER_CALLS,
    intent: 'hybrid',
    model: 'claude-sonnet-4-6',
    trace: {
      graph_version: '3a69acfb87c5',
      fired_regimes: [
        {
          contract: 'arabica_coffee',
          name: 'bullish_supply_squeeze',
          direction: '+',
          matched: ['frost', 'low_stocks'],
          threshold: 2,
        },
      ],
      drivers: ['frost', 'low_stocks'],
      citation_verifier: {
        enabled: true,
        checked: 3,
        stripped: 0,
        corrected: 0,
        by_rule: {},
        resolved: {
          '1': { source: 'usda_gain_coffee', date: '2021-07-20', text: EVIDENCE[0]!.text },
          '2': { source: 'usda_wasde', date: '2021-07-12', text: EVIDENCE[1]!.text },
          N1: { source: 'silver_psd', date: '2021-06-11', text: 'stocks-to-use 0.36 (z=-1.4)' },
        },
      },
    },
    asof,
    question,
  };
}

function degradedResult(q: string, asof: string): RespondResult {
  const r = goodResult(q, asof);
  r.model = 'claude-haiku-4-5';
  r.trace = { ...r.trace, degraded_model: 'claude-haiku-4-5' };
  return r;
}

function floorResult(q: string, asof: string): RespondResult {
  const r = goodResult(q, asof);
  r.structured = null;
  r.answer =
    '**Service notice.** The reasoning model tier is temporarily unavailable. Below is the retrieved, ' +
    'dated evidence this question would have been reasoned over — no synthesized conclusions.';
  r.model = '(floor)';
  r.trace = { graph_version: '3a69acfb87c5', floor: 'evidence_only' };
  r.number_calls = [];
  return r;
}

function refusalResult(q: string, asof: string): RespondResult {
  return {
    answer: 'This query was flagged by the input safety filter and was not processed. Please rephrase.',
    structured: null,
    contract: null,
    contracts: [],
    citations: [],
    evidence: [],
    number_calls: [],
    intent: 'refused',
    model: '(guardrail)',
    trace: { graph_version: '3a69acfb87c5', guardrail: { action: 'INTERVENED' } },
    asof,
    question: q,
  };
}

function noMatchResult(q: string, asof: string): RespondResult {
  return {
    answer: 'No tracked contract matched this question.',
    structured: null,
    contract: null,
    contracts: [],
    citations: [],
    evidence: [],
    number_calls: [],
    intent: 'reasoning',
    model: 'claude-sonnet-4-6',
    trace: { graph_version: '3a69acfb87c5', routed: [], suggestions: ['arabica_coffee', 'corn', 'raw_sugar'] },
    asof,
    question: q,
  };
}

/** Pick a result variant from the question text so a mock dev can exercise every state. */
function pickResult(q: string, asof: string): RespondResult {
  const s = q.toLowerCase();
  if (s.includes('degrad')) return degradedResult(q, asof);
  if (s.includes('floor')) return floorResult(q, asof);
  if (s.includes('ignore all') || s.includes('refuse')) return refusalResult(q, asof);
  if (s.includes('nomatch')) return noMatchResult(q, asof);
  return goodResult(q, asof);
}

export const MOCK_RESULT = goodResult('KC frost 2021', '2021-07-20');

/** The mock stream: the five ordered ticks the backend emits, then the terminal result. */
export async function mockRespondStream(
  params: { question: string; asof?: string },
  h: StreamHandlers,
  opts: { delay?: number } = {},
): Promise<void> {
  const delay = opts.delay ?? 55;
  const result = pickResult(params.question, params.asof ?? '2021-07-20');
  const floor = result.trace?.floor;
  const refused = result.intent === 'refused';
  const stages: StageEvent[] = refused
    ? [{ stage: 'accepted' }, { stage: 'planning', intent: 'refused' }]
    : floor
      ? [
          { stage: 'accepted' },
          { stage: 'planning', intent: 'hybrid', contracts: ['arabica_coffee'] },
          { stage: 'floor' },
        ]
      : [
          { stage: 'accepted' },
          { stage: 'planning', intent: result.intent, contracts: result.contracts },
          { stage: 'walking', nodes: 7, regimes: 1 },
          { stage: 'retrieving', props: 24 },
          { stage: 'numbers', calls: 3 },
          { stage: 'verifying', checked: 3, stripped: 0 },
        ];
  for (const st of stages) {
    await sleep(delay);
    h.onStage?.(st);
  }
  await sleep(delay);
  h.onResult?.(result);
}

// ── read-endpoint fixtures ───────────────────────────────────────────────────────────────────────────
export const MOCK_GRAPH = graphArabica as unknown as Schemas['GraphTopology'];

export const MOCK_REGIMES: Schemas['ConvergenceRow'] = {
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
    {
      name: 'demand_led_tightening',
      direction: '+',
      matched: ['low_stocks'],
      threshold: 2,
      fired: false,
      n_active: 1,
      proximity: 0.5,
    },
  ],
  drivers: [
    { id: 'frost', live: true, verdict: 'observed', z: -2.1, value: 0.09, unit: 'flag', ref: 'frost_event_flag', knowledge_date: '2021-07-15' },
    { id: 'low_stocks', live: true, verdict: 'observed', z: -1.4, value: 0.36, unit: 'ratio', ref: 'psd_su_ratio', knowledge_date: '2021-06-11' },
    { id: 'drought', live: false, verdict: null, z: null, value: null, unit: '', ref: null, knowledge_date: '' },
  ],
};

export const MOCK_SERIES: Schemas['Series'] = {
  table: 'silver_psd',
  metric: 'su_ratio',
  commodity: 'arabica_coffee',
  asof: '2021-07-20',
  unit: 'ratio',
  points: [
    { period: '2016', value: '0.58', knowledge_date: '2016-06-10' },
    { period: '2017', value: '0.55', knowledge_date: '2017-06-10' },
    { period: '2018', value: '0.62', knowledge_date: '2018-06-10' },
    { period: '2019', value: '0.49', knowledge_date: '2019-06-10' },
    { period: '2020', value: '0.44', knowledge_date: '2020-06-11' },
    { period: '2021', value: '0.36', knowledge_date: '2021-06-11' },
  ],
};

export const MOCK_CONVERGENCE: Schemas['ConvergenceMatrix'] = {
  asof: '2021-07-20',
  graph_version: '3a69acfb87c5',
  rows: [MOCK_REGIMES],
};
