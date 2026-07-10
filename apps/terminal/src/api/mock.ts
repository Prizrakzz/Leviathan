import type { PdfPage } from './client';
import type { components } from './types.gen';
import graphArabica from './fixtures/graph.arabica.json';
import graphSugar from './fixtures/graph.raw_sugar.json';
import type { NotificationItem, RespondResult, Section, StageEvent } from './schema';
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

/** The mock stream (5.6): the full ordered tick sequence the backend emits — early walking, per-node
 *  retrieval progress, per-lookup numbers ticks, synthesizing, then bursty `token` deltas (exercises the
 *  typewriter) and the terminal result. */
export async function mockRespondStream(
  params: { question: string; asof?: string; context?: unknown[] },
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

export function mockGetProfile(): Promise<Schemas['Profile']> {
  return new Promise((resolve) => setTimeout(() => resolve({ ..._mockProfile }), 120));
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
