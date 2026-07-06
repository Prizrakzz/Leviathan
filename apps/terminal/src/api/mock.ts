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
        '(larger-than-linear) ICE arabica spike. **Net read: bullish.** [1][2]',
      mechanism:
        'The chain runs in three steps:\n\n' +
        "- Radiative frost in Brazil's southern arabica belt kills buds, cutting the next crop (bullish) [1]\n" +
        '- In a biennial off-year the loss compounds — the two effects amplify each other (bullish) [2]\n' +
        '- With tenderable stocks already low [N1], the price response steepens past the buffer kink',
      diagram_mermaid: 'graph LR; frost-->stocks; stocks-->price',
      sources: [
        { ref: 1, source: 'USDA FAS GAIN Report — Coffee', date: '2021-07-20', source_key: 's3://gain/kc-2021-07-20' },
        { ref: 2, source: 'USDA WASDE', date: '2021-07-12', source_key: 's3://wasde/2021-07' },
        { ref: 'N1', source: 'USDA PSD', date: '2021-06-11' },
      ],
    },
    contract: 'arabica_coffee',
    contracts: ['arabica_coffee'],
    citations: [
      // LIVE shape: keyed by `id` (E1/N1), raw source (drawer join), snippet + source_key on the locator (6.4)
      { kind: 'evidence', id: 'E1', ref: 1, source: 'usda_gain_coffee', date: '2021-07-20',
        locator: { kind: 'doc', source_key: 's3://gain/kc-2021-07-20', snippet: EVIDENCE[0]!.text } },
      { kind: 'evidence', id: 'E2', ref: 2, source: 'usda_wasde', date: '2021-07-12',
        locator: { kind: 'doc', source_key: 's3://wasde/2021-07', snippet: EVIDENCE[1]!.text } },
      { kind: 'number', id: 'N1', ref: 'N1', source: 'silver_psd', date: '2021-06-11',
        locator: { kind: 'number', table: 'silver_psd', metric: 'su_ratio', commodity: 'arabica_coffee', asof: '2021-07-20' } },
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

/** The mock stream (5.6): the full ordered tick sequence the backend emits — early walking, per-node
 *  retrieval progress, per-lookup numbers ticks, synthesizing, then bursty `token` deltas (exercises the
 *  typewriter) and the terminal result. */
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
          { stage: 'walking' },
          { stage: 'retrieving', done: 2, total: 7 },
          { stage: 'numbers', calls: 1, running: true, table: 'silver_psd' },
          { stage: 'retrieving', done: 5, total: 7 },
          { stage: 'numbers', calls: 2, running: true, table: 'silver_oni' },
          { stage: 'retrieving', done: 7, total: 7 },
          { stage: 'walking', nodes: 7, regimes: 1 },
          { stage: 'retrieving', props: 24 },
          { stage: 'numbers', calls: 3 },
          { stage: 'synthesizing' },
        ];
  for (const st of stages) {
    await sleep(delay);
    h.onStage?.(st);
  }
  if (!refused && !floor && result.structured) {
    // Bursty tool-JSON token deltas, like the real input_json_delta stream.
    const body = JSON.stringify({ tldr: result.structured.tldr, mechanism: result.structured.mechanism });
    for (let i = 0; i < body.length; i += 40) {
      await sleep(delay / 2);
      h.onStage?.({ stage: 'token', text: body.slice(i, i + 40) });
    }
    await sleep(delay);
    h.onStage?.({ stage: 'verifying', checked: 3, stripped: 0 });
  }
  await sleep(delay);
  h.onResult?.(result);
}

// ── mock threads (VITE_MOCK sidebar/conversation) ────────────────────────────────────────────────────
const MOCK_THREADS = [
  { id: 't-mock1', title: 'KC frost convexity 2021', title_auto: true, created_at: '2026-07-01T10:00:00Z', updated_at: '2026-07-04T18:30:00Z' },
  { id: 't-mock2', title: 'Sugar su-ratio regimes', title_auto: true, created_at: '2026-06-28T09:00:00Z', updated_at: '2026-07-02T12:00:00Z' },
];

export function mockListThreads(): { items: typeof MOCK_THREADS } {
  return { items: MOCK_THREADS };
}

export function mockThreadTurns(threadId: string): Schemas['ThreadTurns'] {
  if (threadId !== 't-mock1') return { thread_id: threadId, turns: [] };
  const r = MOCK_RESULT;
  return {
    thread_id: threadId,
    turns: [
      {
        question: 'KC frost 2021 — what happened to the convexity setup?',
        answer: 'TL;DR — ' + (r.structured?.tldr ?? '') + '\n\nWhy — ' + (r.structured?.mechanism ?? ''),
        structured: { tldr: r.structured?.tldr, mechanism: r.structured?.mechanism },
        asof: '2021-07-20',
        sources: [],
        graph_version: '3a69acfb87c5',
        contracts: ['arabica_coffee'],
        intent: 'hybrid',
        model: 'claude-sonnet-4-6',
        ts: '2026-07-04T18:30:00Z',
      },
    ],
  };
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

export const MOCK_EVENTS: Schemas['EventsFeed'] = {
  contract: 'arabica_coffee',
  asof: '2021-07-20',
  live: false,
  events: [
    {
      source: 'usda_gain_coffee',
      title: 'Frost damages southern Minas Gerais coffee districts',
      summary: 'Overnight radiative frost hit key arabica-producing districts in southern Brazil.',
      url: 'https://example.gov/gain/kc-2021-07-20',
      date: '2021-07-20',
      driver_id: 'frost',
      commodity: 'arabica_coffee',
    },
    {
      source: 'reuters',
      title: 'Arabica futures spike on Brazil frost reports',
      summary: 'ICE arabica jumped as traders assessed frost damage to the 2022 crop.',
      url: 'https://example.com/reuters/kc-frost',
      date: '2021-07-19',
      driver_id: null,
      commodity: 'arabica_coffee',
    },
  ],
};

// ── 6.2 query suggester ─────────────────────────────────────────────────────────────────────────────
/** Mock follow-ups: distinct sets for a turn packet vs an empty (thread-start) packet, after a short
 *  delay so loading states render in VITE_MOCK=1. */
export function mockSuggest(packet: Schemas['SuggestRequest']): Promise<Schemas['SuggestResponse']> {
  const followups = [
    'How thin are certified arabica stocks right now?',
    'What would a second July frost do to the KC curve?',
    'How does the biennial off-year interact with frost losses?',
  ];
  const starters = [
    'Which contracts have convergence regimes closest to firing?',
    'Walk me through the KC arabica frost convexity setup',
    'What does a weak BRL do to the sugar supply squeeze?',
    'US corn ending stocks vs the 5-year average - implications?',
  ];
  const items = packet.question || packet.tldr ? followups : starters;
  return new Promise((resolve) => setTimeout(() => resolve({ suggestions: items }), 300));
}
