import type { RespondResult } from '@/api/schema';

interface Ev {
  source?: string;
  date?: string;
  text?: string;
  source_key?: string;
  cited?: boolean;
}
interface Cit {
  kind?: string;
  id?: string;
  ref?: unknown;
  source?: string;
  date?: string;
  locator?: { source_key?: string; snippet?: string; char_start?: number; char_end?: number; offset_kind?: string };
}
interface Src {
  ref?: unknown;
  source?: unknown; // OFFICIAL name (6.1)
  source_key?: unknown;
}

export interface ReceiptRow {
  ref?: string;
  source: string;
  date: string;
  snippet?: string;
  kind: string; // 'evidence' | 'number'
  sourceKey?: string; // 6.4: the pin/filter key
  // Phase F: char offsets ride to the PDF open so the drawer's `pdf ▸` resolves an exact page + highlight
  charStart?: number;
  charEnd?: number;
  offsetKind?: string;
}
export interface Receipts {
  cited: ReceiptRow[];
  uncited: ReceiptRow[];
  stripped: ReceiptRow[];
  strippedCount: number;
  asof: string;
}

const key = (s?: string, d?: string) => `${s}|${d}`;

/** D-TW-16: the driver NODE IDS this turn's cascade actually fired on — the fired-regime `matched` sets
 *  first (a regime names the drivers that tripped it), then the trace `drivers` list, deduped in that
 *  order. This is exactly the union CascadeFlow's `firingActiveSet` lights on the map, which is what makes
 *  each id a legal `focus` target for the graph tab. Defensive by design: `trace` is untrusted wire JSON,
 *  so every entry is string-checked and blanks are dropped — an id the topology does not know still costs
 *  nothing (seedWithFocus no-ops and the tab opens whole-graph). Pure — unit-tested. */
export function citedDrivers(r: RespondResult): string[] {
  const t = (r.trace ?? {}) as { fired_regimes?: unknown[]; drivers?: unknown[] };
  const seen = new Set<string>();
  const add = (v: unknown) => {
    if (typeof v === 'string' && v && !seen.has(v)) seen.add(v);
  };
  for (const g of Array.isArray(t.fired_regimes) ? t.fired_regimes : []) {
    const m = (g as { matched?: unknown }).matched;
    for (const d of Array.isArray(m) ? m : []) add(d);
  }
  for (const d of Array.isArray(t.drivers) ? t.drivers : []) add(d);
  return [...seen];
}

/** Partition a turn's provenance into the three receipt tiers (design §4.3): the model's CITED items, the
 *  retrieved-but-uncited machine evidence, and any verifier STRIPS (normally 0). CITED rows carry the
 *  OFFICIAL source name (joined from structured.sources by ref/source_key) + the durable 140-char snippet
 *  and their source_key for click-pinning (6.4). Every row is provably `≤ as-of`. Pure — unit-tested. */
export function partitionReceipts(r: RespondResult): Receipts {
  const ev = (r.evidence ?? []) as Ev[];
  const cits = ((r.citations ?? (r as { sources?: Cit[] }).sources) ?? []) as Cit[]; // live: citations; durable: sources
  const structuredSources = ((r.structured as { sources?: Src[] } | null)?.sources ?? []) as Src[];

  const officialByRef = new Map<string, string>();
  const officialByKey = new Map<string, string>();
  for (const s of structuredSources) {
    const name = typeof s.source === 'string' ? s.source : undefined;
    if (!name) continue;
    if (s.ref != null) officialByRef.set(String(s.ref), name);
    if (typeof s.source_key === 'string') officialByKey.set(s.source_key, name);
  }
  const refOf = (c: Cit) => String(c.ref ?? c.id ?? '');
  const evText = (c: Cit) =>
    c.locator?.snippet ?? ev.find((e) => key(e.source, e.date) === key(c.source, c.date))?.text;

  const cited: ReceiptRow[] = cits.map((c) => {
    const ref = refOf(c);
    const sk = c.locator?.source_key;
    const official = officialByRef.get(ref) ?? (sk ? officialByKey.get(sk) : undefined);
    return {
      ref: ref || undefined,
      source: official ?? String(c.source ?? '?'),
      date: String(c.date ?? ''),
      snippet: evText(c),
      kind: c.kind ?? 'evidence',
      sourceKey: sk,
      charStart: typeof c.locator?.char_start === 'number' ? c.locator.char_start : undefined,
      charEnd: typeof c.locator?.char_end === 'number' ? c.locator.char_end : undefined,
      offsetKind: typeof c.locator?.offset_kind === 'string' ? c.locator.offset_kind : undefined,
    };
  });
  const citedKeys = new Set(cits.map((c) => key(c.source, c.date)));
  const uncited: ReceiptRow[] = ev
    .filter((e) => !e.cited && !citedKeys.has(key(e.source, e.date)))
    .map((e) => ({ source: String(e.source ?? '?'), date: String(e.date ?? ''), snippet: e.text, kind: 'evidence', sourceKey: e.source_key }));

  const cv = (r.trace as { citation_verifier?: { stripped?: number; stripped_items?: ReceiptRow[] } } | undefined)
    ?.citation_verifier;
  return {
    cited,
    uncited,
    stripped: cv?.stripped_items ?? [],
    strippedCount: cv?.stripped ?? 0,
    asof: String(r.asof ?? ''),
  };
}
