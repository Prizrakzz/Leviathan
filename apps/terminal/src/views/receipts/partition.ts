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
  ref?: unknown;
  source?: string;
  date?: string;
}

export interface ReceiptRow {
  ref?: string;
  source: string;
  date: string;
  snippet?: string;
  kind: string; // 'evidence' | 'number'
}
export interface Receipts {
  cited: ReceiptRow[];
  uncited: ReceiptRow[];
  stripped: ReceiptRow[];
  strippedCount: number;
  asof: string;
}

const key = (s?: string, d?: string) => `${s}|${d}`;

/** Partition a turn's provenance into the three receipt tiers (design §4.3): the model's CITED items, the
 *  retrieved-but-uncited machine evidence, and any verifier STRIPS (normally 0, shown for auditability).
 *  Every row carries its date — all provably `≤ as-of`. Pure — unit-tested. */
export function partitionReceipts(r: RespondResult): Receipts {
  const ev = (r.evidence ?? []) as Ev[];
  const cits = (r.citations ?? []) as Cit[];
  const snippetFor = (c: Cit) => ev.find((e) => key(e.source, e.date) === key(c.source, c.date))?.text;

  const cited: ReceiptRow[] = cits.map((c) => ({
    ref: c.ref != null ? String(c.ref) : undefined,
    source: String(c.source ?? '?'),
    date: String(c.date ?? ''),
    snippet: snippetFor(c),
    kind: c.kind ?? 'evidence',
  }));
  const citedKeys = new Set(cits.map((c) => key(c.source, c.date)));
  const uncited: ReceiptRow[] = ev
    .filter((e) => !e.cited && !citedKeys.has(key(e.source, e.date)))
    .map((e) => ({ source: String(e.source ?? '?'), date: String(e.date ?? ''), snippet: e.text, kind: 'evidence' }));

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
