import type { RespondResult } from '@/api/schema';

/** One resolved citation — the receipt a chip points at. `source` is the OFFICIAL display name (6.1/6.4);
 *  `text` is the 140-char snippet; `locator` carries a number citation's query for the provenance popover. */
export interface ResolvedCite {
  source?: string;
  date?: string;
  text?: string;
  locator?: Record<string, unknown>;
}
export type ResolvedMap = Record<string, ResolvedCite>;

type Src = { ref?: unknown; source?: unknown; date?: unknown; source_key?: unknown };
type Cit = { id?: unknown; kind?: unknown; locator?: { source_key?: unknown; snippet?: unknown; kind?: unknown } };

/** Unified resolved-citation map (6.4) — works for a LIVE result (trace.citation_verifier.resolved) AND a
 *  durable turn (structured.sources + citations[].locator.snippet), so chips hover the same official
 *  name + snippet either way. Official name comes from `structured.sources` (humanized in 6.1); the snippet
 *  from the live verifier text, else the durable `locator.snippet` joined by source_key. A chip renders
 *  only for refs present here (fabricated refs were stripped server-side). */
export function resolvedFor(r: {
  structured?: { sources?: unknown[] } | null;
  trace?: unknown;
  citations?: unknown[];
  sources?: unknown[];
}): ResolvedMap {
  const out: ResolvedMap = {};
  const structuredSources = (r.structured?.sources ?? []) as Src[];
  const cits = (r.citations ?? r.sources ?? []) as Cit[];
  const live = (r.trace as { citation_verifier?: { resolved?: Record<string, ResolvedCite> } } | undefined)
    ?.citation_verifier?.resolved;
  const snippetByKey = new Map<string, string>();
  const numLocByRef = new Map<string, Record<string, unknown>>();
  for (const c of cits) {
    const key = c.locator?.source_key;
    if (typeof key === 'string' && typeof c.locator?.snippet === 'string') snippetByKey.set(key, c.locator.snippet);
    if (c.locator?.kind === 'number' && typeof c.id === 'string') numLocByRef.set(c.id, c.locator as Record<string, unknown>);
  }
  const refs = new Set<string>([...Object.keys(live ?? {}), ...structuredSources.map((s) => String(s.ref))]);
  for (const ref of refs) {
    if (!ref || ref === 'undefined') continue;
    const ss = structuredSources.find((s) => String(s.ref) === ref);
    const lr = live?.[ref];
    const sk = ss?.source_key;
    const text = lr?.text ?? (typeof sk === 'string' ? snippetByKey.get(sk) : undefined);
    const source = (ss?.source as string | undefined) ?? lr?.source;
    if (source == null && text == null && !numLocByRef.has(ref)) continue; // nothing to show → no chip
    out[ref] = { source, date: (ss?.date as string | undefined) ?? lr?.date, text, locator: numLocByRef.get(ref) };
  }
  return out;
}

export type NoteSegment = { kind: 'text'; text: string } | { kind: 'cite'; ref: string; resolved: ResolvedCite };

const CITE = /\[([A-Za-z]?\d+)\]/g; // [1] [E2] [N1]

/** The verifier's resolved-citation map — a chip renders ONLY for refs in here (fabricated refs are
 *  stripped server-side, so an unresolved `[n]` stays plain text). */
export function resolvedMap(result: Pick<RespondResult, 'trace'>): ResolvedMap {
  const cv = (result.trace as { citation_verifier?: { resolved?: ResolvedMap } } | undefined)?.citation_verifier;
  return cv?.resolved ?? {};
}

/** Split note text into text + citation segments; only refs present in `resolved` become chips. */
export function tokenizeCitations(text: string, resolved: ResolvedMap): NoteSegment[] {
  const out: NoteSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    const ref = m[1] as string;
    const at = m.index ?? 0;
    if (resolved[ref]) {
      if (at > last) out.push({ kind: 'text', text: text.slice(last, at) });
      out.push({ kind: 'cite', ref, resolved: resolved[ref] });
      last = at + m[0].length;
    }
    // unresolved [n]: leave in place as text (handled by the trailing slice)
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}
