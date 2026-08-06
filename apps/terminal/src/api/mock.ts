import type { PdfPage } from './schema';
import type { components } from './types.gen';
import graphArabica from './fixtures/graph.arabica.json';
import graphSugar from './fixtures/graph.raw_sugar.json';
import type {
  ArtifactItem,
  FrozenSnapshot,
  GalleryItem,
  NotificationItem,
  RespondResult,
  Section,
  StageEvent,
} from './schema';
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

// P9-C typed sections -- the DERIVED per-kind view of `mechanism` (backend `_sectionize`). The mock keeps
// the round-trip by construction: GOOD_MECHANISM is REJOINED from these sections, so the sections path and
// the mechanism fallback show the same prose. rawSugarResult stays mechanism-only to demo the fallback.
const GOOD_SECTIONS: Section[] = [
  {
    kind: 'mechanism',
    heading: 'Mechanism',
    body:
      "- Radiative frost in Brazil's southern arabica belt kills buds, cutting the next crop (bullish) [1]\n" +
      '- In a biennial off-year the loss compounds — the two effects amplify each other (bullish) [2]\n' +
      '- With tenderable stocks already low [N1], the price response steepens past the buffer kink',
  },
  {
    kind: 'record',
    heading: 'The record',
    body:
      '- 1994 (double frost, off-year): the nearby roughly doubled inside two months [2]\n' +
      '- 2021 setup: stocks-to-use 0.36, z=-1.4 going into the frost window [N1]',
  },
  {
    kind: 'disagreement',
    heading: 'Where the record disagrees',
    body:
      '1975 spiked hardest off an ON-year crop, so the off-year amplifier is not load-bearing on its own — ' +
      'the thin buffer is what the episodes share [2]',
  },
  {
    kind: 'watch',
    heading: 'What to watch',
    body:
      '- Certified/tenderable stocks through the July frost window [N1]\n' +
      '- A second cold front before bud recovery locks in the cut [1]',
  },
];
// All headings are non-empty here, so the plain rejoin reproduces the mechanism (SECTION II invariant).
const GOOD_MECHANISM = GOOD_SECTIONS.map((s) => '## ' + s.heading + '\n' + s.body).join('\n');

function goodResult(question: string, asof: string): RespondResult {
  return {
    answer: '',
    structured: {
      tldr:
        'A July frost landing in an off-year would compound an already-thin buffer, producing a convex ' +
        '(larger-than-linear) ICE arabica spike. **Net read: bullish.** [1][2]',
      mechanism: GOOD_MECHANISM,
      sections: GOOD_SECTIONS,
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

// A SECOND commodity fixture (raw_sugar) so a mock walkthrough can tell answers apart by question — the
// single canned fixture made a sugar question render the arabica answer, which read as a stale-render bug.
const SUGAR_EVIDENCE = [
  {
    ref: 1,
    source: 'unica_brazil',
    date: '2024-05-30',
    source_key: 's3://unica/2024-05',
    text: 'Center-South mills lifted the ethanol mix as a weaker real raised parity, trimming the sugar share of the crush.',
    contract: 'raw_sugar',
    cited: true,
  },
  {
    ref: 2,
    source: 'usda_gain_sugar',
    date: '2024-05-15',
    source_key: 's3://gain/sb-2024-05',
    text: 'Brazil 2024/25 sugar output forecast eased as cane diverts to ethanol on stronger domestic parity.',
    contract: 'raw_sugar',
    cited: true,
  },
  {
    source: 'iso_report',
    date: '2024-05-02',
    source_key: 's3://iso/2024-05',
    text: 'Global sugar balance tightening on lower expected Center-South output.',
    contract: 'raw_sugar',
    cited: false,
  },
];

const SUGAR_NUMBERS = [
  {
    ref: 'N1',
    query: { table: 'silver_psd', metric: 'su_ratio', commodity: 'raw_sugar' },
    rows: [{ value: '0.41', z: '-1.1', knowledge_date: '2024-05-11', period: '2024' }],
    status: 'ok',
  },
];

function rawSugarResult(question: string, asof: string): RespondResult {
  return {
    answer: '',
    structured: {
      tldr:
        'A weaker BRL lifts domestic ethanol parity, nudging Center-South mills to divert cane from sugar ' +
        'to ethanol — tightening exportable supply into an already-snug balance. **Net read: mildly bullish.** [1][2]',
      mechanism:
        'The chain runs in three steps:\n\n' +
        '- A weaker real raises the ethanol-parity price mills receive domestically (bullish sugar) [1]\n' +
        '- Mills lift the ethanol mix, cutting the sugar share of the cane crush [2]\n' +
        '- With stocks-to-use already below trend [N1], the reduced export share steepens the price response',
      diagram_mermaid: 'graph LR; brl-->parity; parity-->supply; supply-->price',
      sources: [
        { ref: 1, source: 'UNICA Center-South Report', date: '2024-05-30', source_key: 's3://unica/2024-05' },
        { ref: 2, source: 'USDA FAS GAIN Report — Sugar', date: '2024-05-15', source_key: 's3://gain/sb-2024-05' },
        { ref: 'N1', source: 'USDA PSD', date: '2024-05-11' },
      ],
    },
    contract: 'raw_sugar',
    contracts: ['raw_sugar'],
    citations: [
      { kind: 'evidence', id: 'E1', ref: 1, source: 'unica_brazil', date: '2024-05-30',
        locator: { kind: 'doc', source_key: 's3://unica/2024-05', snippet: SUGAR_EVIDENCE[0]!.text } },
      { kind: 'evidence', id: 'E2', ref: 2, source: 'usda_gain_sugar', date: '2024-05-15',
        locator: { kind: 'doc', source_key: 's3://gain/sb-2024-05', snippet: SUGAR_EVIDENCE[1]!.text } },
      { kind: 'number', id: 'N1', ref: 'N1', source: 'silver_psd', date: '2024-05-11',
        locator: { kind: 'number', table: 'silver_psd', metric: 'su_ratio', commodity: 'raw_sugar', asof } },
    ],
    evidence: SUGAR_EVIDENCE,
    number_calls: SUGAR_NUMBERS,
    intent: 'hybrid',
    model: 'claude-sonnet-4-6',
    trace: {
      graph_version: '3a69acfb87c5',
      // real raw_sugar node ids, so the firing overlay + seed light actual sugar nodes on the sugar DAG
      fired_regimes: [
        {
          contract: 'raw_sugar',
          name: 'bullish_ethanol_pull',
          direction: '+',
          matched: ['sugar_ethanol_parity', 'India_ethanol_diversion'],
          threshold: 2,
        },
      ],
      drivers: ['sugar_ethanol_parity', 'India_ethanol_diversion'],
      citation_verifier: {
        enabled: true,
        checked: 3,
        stripped: 0,
        corrected: 0,
        by_rule: {},
        resolved: {
          '1': { source: 'unica_brazil', date: '2024-05-30', text: SUGAR_EVIDENCE[0]!.text },
          '2': { source: 'usda_gain_sugar', date: '2024-05-15', text: SUGAR_EVIDENCE[1]!.text },
          N1: { source: 'silver_psd', date: '2024-05-11', text: 'stocks-to-use 0.41 (z=-1.1)' },
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

export function numbersOnlyResult(q: string, asof: string): RespondResult {
  // W1.2: a pure-numeric turn — structured stays null (no walk ran) but contract/contracts ARE resolved
  // backend-side so the FE mounts the cascade map, and r.answer is the numbers markdown the FE must render.
  return {
    answer:
      'US arabica ending stocks for 2021/22 were about 3.2 million bags [N1], versus 3.9 the prior ' +
      'year [N1].\n\n## Sources\n[N1] USDA PSD — stocks (arabica_coffee)',
    structured: null,
    contract: 'arabica_coffee',
    contracts: ['arabica_coffee'],
    citations: [],
    evidence: [],
    number_calls: NUMBER_CALLS,
    intent: 'numbers_only',
    model: 'claude-haiku-4-5',
    trace: { graph_version: '3a69acfb87c5', numbers_verifier: { mismatched: false } },
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

/** Pick a result variant from the question text so a mock dev can exercise every state. Commodity keywords
 *  (sugar/BRL) route to the raw_sugar fixture so answers differ by question — otherwise a mock walkthrough
 *  renders the SAME arabica answer for every commodity (which looks like a stale-render bug). */
function pickResult(q: string, asof: string): RespondResult {
  const s = q.toLowerCase();
  if (s.includes('degrad')) return degradedResult(q, asof);
  if (s.includes('floor')) return floorResult(q, asof);
  if (s.includes('ignore all') || s.includes('refuse')) return refusalResult(q, asof);
  if (s.includes('nomatch')) return noMatchResult(q, asof);
  if (s.includes('numbers') || s.includes('ending stocks')) return numbersOnlyResult(q, asof);
  if (s.includes('sugar') || s.includes('brl')) return rawSugarResult(q, asof);
  return goodResult(q, asof);
}

/** The mock graph for a contract — the DAG must match the answered commodity (client.getGraph routes here in
 *  mock mode). raw_sugar → the sugar topology; everything else → arabica. */
export function mockGraph(contract: string): Schemas['GraphTopology'] {
  return /sugar/.test(contract) ? (graphSugar as unknown as Schemas['GraphTopology']) : MOCK_GRAPH;
}

export const MOCK_RESULT = goodResult('KC frost 2021', '2021-07-20');

/**
 * F7 content-bearing partials, DERIVED from the same fixture the terminal result carries — so the mock
 * findings feed is commodity-accurate (an arabica question streams arabica regimes) and can never drift
 * from the answer it precedes. Deterministic engine output only: slugs, tables, values, dates.
 */
function partialsFor(result: RespondResult): StageEvent[] {
  type Fired = { contract?: string; name?: string; direction?: string; matched?: string[] };
  type Ev = { source?: string; date?: string; cited?: boolean };
  type Call = { query?: { table?: string; metric?: string }; rows?: { value?: string; knowledge_date?: string }[] };
  const contract = result.contract ?? result.contracts?.[0] ?? '';
  const fired = (result.trace?.fired_regimes ?? []) as Fired[];
  const evidence = (result.evidence ?? []) as Ev[];
  const calls = (result.number_calls ?? []) as Call[];
  const dir = (d?: string) => (d === '+' ? 'bullish' : d === '-' ? 'bearish' : (d ?? ''));

  const regimes: StageEvent[] = fired.map((f) => {
    const basis: Record<string, { date?: string; source?: string }> = {};
    (f.matched ?? []).forEach((driver, i) => {
      const e = evidence[i];
      basis[driver] = { date: e?.date, source: e?.source };
    });
    return {
      stage: 'regime',
      contract: f.contract ?? contract,
      regime: f.name ?? 'regime',
      direction: dir(f.direction),
      basis,
    };
  });
  // Only RESOLVED lookups stream a `number` (the fixture carries an unresolved call too — the engine has
  // nothing to report for it, so neither does the feed).
  const numbers: StageEvent[] = calls
    .filter((c) => !!c.rows?.[0]?.value)
    .map((c) => ({
      stage: 'number',
      table: c.query?.table ?? '',
      metric: c.query?.metric ?? '',
      value: c.rows?.[0]?.value ?? '',
      unit: null,
      asof: c.rows?.[0]?.knowledge_date ?? '',
    }));
  const drivers = ((result.trace?.drivers ?? []) as string[]).slice(0, 3);
  const nodes: StageEvent[] = drivers.map((d, i) => ({ stage: 'evidence', node: d, kept: 12 - i * 3 }));
  const chain: StageEvent[] = drivers.length
    ? [{ stage: 'chain', chain_id: `${contract}_transmission`, hops: [...drivers, contract] }]
    : [];
  return [...regimes, ...numbers, ...nodes, ...chain];
}

/** D-AM-14 mock knobs: FABRICATED stand-ins for the values reasoning_modes.py resolves, present so the
 *  "what ran" chip is exercisable with `VITE_MOCK=1` (the whole point of the mock: the UI runs with no
 *  backend). Deliberately a SHORT dict, not a copy of the ratified preset table -- the chip renders
 *  whatever keys arrive, so a mock that mirrored every knob would only be a second place to go stale. */
const MOCK_MODE_KNOBS: Record<string, Record<string, unknown>> = {
  quick: { depth: 1, node_budget: 6, k_by_depth: [4, 2], evidence_cap: 12, fetch_k: 40 },
  deep: { depth: 3, node_budget: 16, k_by_depth: [7, 5, 3], evidence_cap: 48, fetch_k: 120 },
};

/** Stamp the mode decision (every turn, like the backend) and — only for a non-standard, knob-consuming
 *  mock lane — the resolved knobs. Returns the SAME object when there is nothing to stamp, so a standard
 *  mock turn is byte-identical to the fixture it has always been. */
function withMockMode(result: RespondResult, mode?: string): RespondResult {
  const requested = (mode ?? '').trim().toLowerCase() || null;
  const known = requested != null && ['quick', 'standard', 'deep'].includes(requested);
  const honored = known && requested ? requested : 'standard';
  const knobs = MOCK_MODE_KNOBS[honored];
  if (!requested && !result.intent_decision) return result;
  return {
    ...result,
    intent_decision: {
      ...(result.intent_decision ?? {}),
      mode: { requested, honored, invalid: requested != null && !known },
    },
    ...(knobs && result.structured ? { trace: { ...(result.trace ?? {}), mode_knobs: knobs } } : {}),
  };
}

/** The mock stream (5.6): the full ordered tick sequence the backend emits — early walking, per-node
 *  retrieval progress, per-lookup numbers ticks, synthesizing, then bursty `token` deltas (exercises the
 *  typewriter) and the terminal result. F7: the content-bearing partials ride the same sequence, so
 *  `VITE_MOCK=1` exercises the findings feed + the inert→live citation swap end to end. */
export async function mockRespondStream(
  params: { question: string; asof?: string; context?: unknown[]; mode?: string },
  h: StreamHandlers,
  opts: { delay?: number } = {},
): Promise<void> {
  const delay = opts.delay ?? 55;
  const result = withMockMode(pickResult(params.question, params.asof ?? '2021-07-20'), params.mode);
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
          { stage: 'plan', intent: result.intent ?? 'hybrid', contracts: result.contracts ?? [] },
          { stage: 'walking' },
          { stage: 'walk', nodes: 7, depth: 3 },
          { stage: 'retrieving', done: 2, total: 7 },
          { stage: 'numbers', calls: 1, running: true, table: 'silver_psd' },
          { stage: 'retrieving', done: 5, total: 7 },
          ...partialsFor(result),
          { stage: 'numbers', calls: 2, running: true, table: 'silver_oni' },
          { stage: 'retrieving', done: 7, total: 7 },
          { stage: 'walking', nodes: 7, regimes: 1 },
          { stage: 'retrieving', props: 24 },
          { stage: 'numbers', calls: 3 },
          { stage: 'synthesizing' },
          { stage: 'drafting' },
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
    // The verifier finished → the UI may activate citation handles (F7's one activation point).
    h.onStage?.({ stage: 'verified', strips: 0 });
  }
  await sleep(delay);
  h.onResult?.(result);
}

// ── 6.5 PDF click-to-page (VITE_MOCK) ──────────────────────────────────────────────────────────────
/** A fixed resolved-PDF pointer so the mock walkthrough / e2e can open the modal without a backend. The
 *  URL is an empty-doc-safe data: URI (pdf.js surfaces an error state, which the modal handles by keeping
 *  the raw-download escape) — the point is to exercise the chip/row -> modal wiring, not to raster bytes.
 *  Args are accepted (and ignored) so the mock matches `client.getPdfPage`'s signature. */
// A real (tiny) 1-page PDF so the mock click-to-pdf flow renders instead of erroring: the old empty
// data URL made pdf.js fail and the download save a 0-byte file on every mock walkthrough.
const MOCK_PDF_URL = 'data:application/pdf;base64,JVBERi0xLjQKMSAwIG9iaiA8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4gZW5kb2JqCjIgMCBvYmogPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4gZW5kb2JqCjMgMCBvYmogPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA2MTIgNzkyXSAvQ29udGVudHMgNCAwIFIgL1Jlc291cmNlcyA8PCAvRm9udCA8PCAvRjEgNSAwIFIgPj4gPj4gPj4gZW5kb2JqCjQgMCBvYmogPDwgL0xlbmd0aCA2MSA+PiBzdHJlYW0KQlQgL0YxIDI0IFRmIDcyIDcyMCBUZCAoTGV2aWF0aGFuIG1vY2sgc291cmNlIGRvY3VtZW50KSBUaiBFVAplbmRzdHJlYW0gZW5kb2JqCjUgMCBvYmogPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhID4+IGVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMDkgMDAwMDAgbiAKMDAwMDAwMDA1OCAwMDAwMCBuIAowMDAwMDAwMTE1IDAwMDAwIG4gCjAwMDAwMDAyNDEgMDAwMDAgbiAKMDAwMDAwMDM1MiAwMDAwMCBuIAp0cmFpbGVyIDw8IC9TaXplIDYgL1Jvb3QgMSAwIFIgPj4Kc3RhcnR4cmVmCjQyMgolJUVPRg==';

export function mockGetPdfPage(
  _sourceKey: string,
  _snippet?: string,
  _charStart?: number,
  _offsetKind?: string,
): Promise<PdfPage> {
  return new Promise((resolve) =>
    setTimeout(() => resolve({ url: MOCK_PDF_URL, page: 1, kind: 'pdf', expires_in: 900 }), 60),
  );
}

// ── 6.6 profile / settings / onboarding (VITE_MOCK) ────────────────────────────────────────────────
// Module-level so a mock PUT persists across the session (until a hard reload, which restarts the module —
// so onboarding re-demos on reload, matching a first-run). Starts un-onboarded to exercise the flow.
let _mockProfile: Schemas['Profile'] = {
  sub: 'mock-user',
  email: 'you@example.com',
  name: 'Mock Trader',
  facts: {},
  onboarded: false,
  turn_count: 12,
  first_seen: '2026-06-01T09:00:00Z',
  last_seen: '2026-07-04T18:30:00Z',
};

/**
 * D-TW-19 e2e seed: with `localStorage['lv-mock-onboarded'] = '1'` set BEFORE the app boots (Playwright's
 * addInitScript), the mock profile reports itself already onboarded.
 *
 * WHY state and not a click: onboarding is a Radix MODAL dialog -- scrim, focus trap, aria-hidden on
 * everything behind it -- and it mounts ~120ms after load, when this fetch resolves. That is precisely late
 * enough to race a "click Skip all first" step, and while it is up the command bar is unreachable, so every
 * assertion in the gate would flake on it. Seeding the state the modal gates on removes the race entirely.
 * Mock-only (nothing imports this without VITE_MOCK=1). Read PER CALL, not at module init, so a seeded
 * session can still exercise the flow through "Redo onboarding" (which goes via forceOnboarding).
 */
function seededOnboarded(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem('lv-mock-onboarded') === '1';
  } catch {
    return false; // storage can throw (blocked cookies / partitioned contexts) -- never break the mock over it
  }
}

export function mockGetProfile(): Promise<Schemas['Profile']> {
  const p = { ..._mockProfile, onboarded: _mockProfile.onboarded || seededOnboarded() };
  return new Promise((resolve) => setTimeout(() => resolve(p), 120));
}

export function mockPutProfile(update: Schemas['ProfileUpdate']): Promise<Schemas['Profile']> {
  if (update.facts != null) _mockProfile = { ..._mockProfile, facts: update.facts };
  if (update.onboarded != null) _mockProfile = { ..._mockProfile, onboarded: update.onboarded };
  return new Promise((resolve) => setTimeout(() => resolve({ ..._mockProfile }), 120));
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
        // Carry structured.sources + the citation pointers so the durable turn RESOLVES its [n] chips —
        // a real durable turn does. With empty sources the chips never rendered, which is exactly why the
        // PastTurn "Tooltip must be used within TooltipProvider" throw stayed latent through every test (S2.2).
        // P9-C: sections persist on durable turns too, so PastTurn's per-kind branch is exercised here.
        structured: {
          tldr: r.structured?.tldr,
          mechanism: r.structured?.mechanism,
          sources: r.structured?.sources,
          sections: r.structured?.sections,
        },
        asof: '2021-07-20',
        sources: (r.citations ?? []) as { [key: string]: unknown }[],
        graph_version: '3a69acfb87c5',
        contracts: ['arabica_coffee'],
        intent: 'hybrid',
        model: 'claude-sonnet-4-6',
        ts: '2026-07-04T18:30:00Z',
      },
    ],
  };
}

// ── D-AM-15 artifacts + share links (VITE_MOCK) ──────────────────────────────────────────────────────
// Module-level so a mock save lands in the sidebar and a mock share link RESOLVES on /s/{id} within the
// session — the whole point of the mock is to walk save -> open -> share without a backend. The freeze is
// server-side in prod; here it is imitated exactly (make_share's field set), never a different shape.
let _mockSeq = 0;
const _mockShares: Record<string, FrozenSnapshot> = {};
const _mockArtifacts: ArtifactItem[] = [];

function mockFreeze(body: { question?: string; asof?: string | null; payload?: unknown }): FrozenSnapshot {
  _mockSeq += 1;
  const payload = (body.payload ?? MOCK_RESULT) as RespondResult;
  return {
    id: `mock-frz-${_mockSeq}`,
    question: body.question ?? '',
    asof: body.asof ?? null,
    graph_version: (payload.trace?.graph_version as string | undefined) ?? null,
    created_at: new Date().toISOString(),
    payload,
  };
}

export function mockListArtifacts(): Promise<{ items: ArtifactItem[] }> {
  const items = [..._mockArtifacts].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
  return new Promise((resolve) => setTimeout(() => resolve({ items }), 80));
}

export function mockSaveArtifact(body: {
  name: string;
  question?: string;
  asof?: string | null;
  payload?: unknown;
}): Promise<{ id: string }> {
  const snapshot = mockFreeze(body);
  const item: ArtifactItem = {
    id: `mock-art-${_mockSeq}`,
    name: body.name || snapshot.question || 'untitled artifact',
    snapshot,
    created_at: snapshot.created_at,
    updated_at: snapshot.created_at,
  };
  _mockArtifacts.push(item);
  return Promise.resolve({ id: item.id });
}

export function mockDeleteArtifact(id: string): Promise<void> {
  const i = _mockArtifacts.findIndex((a) => a.id === id);
  if (i >= 0) _mockArtifacts.splice(i, 1);
  return Promise.resolve();
}

export function mockCreateShare(body: {
  question?: string;
  asof?: string | null;
  payload?: unknown;
}): Promise<{ id: string; url: string }> {
  const snap = mockFreeze(body);
  _mockShares[snap.id] = snap;
  return Promise.resolve({ id: snap.id, url: `/s/${snap.id}` });
}

export function mockGetShare(id: string): Promise<FrozenSnapshot> {
  // An unknown id resolves to the canonical fixture rather than rejecting: a mock reload drops the in-memory
  // map, and a dead reader page would look like the route is broken instead of the store being ephemeral.
  const snap =
    _mockShares[id] ??
    mockFreeze({ question: 'KC frost 2021 — what happened to the convexity setup?', asof: '2021-07-20', payload: MOCK_RESULT });
  return new Promise((resolve) => setTimeout(() => resolve(snap), 80));
}

// ── P3 Track D: notification digest (VITE_MOCK bell + badge) ─────────────────────────────────────────
/** Two sample items — one unseen (drives the badge), one already seen — dated today-ish so the PIT guard
 *  passes at a live as-of. */
const MOCK_NOTIFICATIONS: NotificationItem[] = [
  {
    notif_id: 'ntf-mock1',
    created_at: '2026-07-10T06:00:00Z',
    seen: false,
    event_type: 'export_ban',
    commodity: 'corn',
    date: '2026-07-10',
    country: 'Argentina',
    summary: 'Argentina announced a temporary halt on corn export registrations.',
    label: 'export ban - corn (Argentina)',
    query: 'Has export ban hit corn before? What cascaded?',
    driver_id: 'export_policy',
  },
  {
    notif_id: 'ntf-mock2',
    created_at: '2026-07-08T05:30:00Z',
    seen: true,
    event_type: 'frost',
    commodity: 'arabica_coffee',
    date: '2026-07-08',
    country: 'Brazil',
    summary: 'A cold front clipped the southern arabica belt overnight.',
    label: 'frost - arabica coffee (Brazil)',
    query: 'What did the last comparable Brazil frost do to the KC curve?',
    driver_id: 'frost_risk',
  },
];

export function mockListNotifications(): Promise<NotificationItem[]> {
  return new Promise((resolve) => setTimeout(() => resolve(MOCK_NOTIFICATIONS.map((n) => ({ ...n }))), 120));
}

// ── read-endpoint fixtures ───────────────────────────────────────────────────────────────────────────
export const MOCK_GRAPH = graphArabica as unknown as Schemas['GraphTopology'];

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

// ── D-AM-16 prompt gallery ──────────────────────────────────────────────────────────────────────────
/** A warm-catalog gallery: filled questions across the categories the real yaml carries, plus ONE unfilled
 *  row so the cold-catalog branch (a `{slot}` question, never offered as a one-click starter) is walkable
 *  in VITE_MOCK=1 without stopping the convergence warmer. */
export function mockGallery(): Promise<{ items: GalleryItem[] }> {
  const items: GalleryItem[] = [
    { id: 'conv_regime_proximity', category: 'convergence', rc_target: 'recency', filled: true,
      question: 'How close is the Frost Squeeze (price-supportive) regime in arabica coffee to firing right now?' },
    { id: 'conv_missing_drivers', category: 'convergence', rc_target: 'default', filled: true,
      question: 'The Ethanol Diversion (price-supportive) regime in raw sugar is short of its threshold -- which drivers still have to fire?' },
    { id: 'cross_rv_compare', category: 'cross_commodity', rc_target: 'compare', filled: true,
      question: 'Compare palm oil and soybean oil -- which is more exposed to the shared supply shock?' },
    { id: 'cascade_walk', category: 'cascade', rc_target: 'default', filled: true,
      question: 'Walk me through the cascade from a supply shock in corn to the price signal.' },
    { id: 'verify_premise', category: 'verification', rc_target: 'verification', filled: true,
      question: 'Stocks in arabica coffee are the tightest in a decade, right?' },
    { id: 'rank_exporters', category: 'ranking', rc_target: 'ranking', filled: true,
      question: 'Rank the largest exporters of raw sugar and flag which is most at risk this season.' },
    { id: 'horizon_ladder', category: 'horizon', rc_target: 'horizon', filled: true,
      question: 'What should I watch over the next weeks, months, and quarters in corn?' },
    { id: 'recency_whats_changed', category: 'recency', rc_target: 'recency', filled: false,
      question: 'What has changed in {contract} fundamentals over the past 30 days?' },
  ];
  return new Promise((resolve) => setTimeout(() => resolve({ items }), 200));
}
