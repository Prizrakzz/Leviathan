import type { RespondResult } from '@/api/schema';

/** One resolved citation (from `trace.citation_verifier.resolved`) — the receipt a chip points at. */
export interface ResolvedCite {
  source?: string;
  date?: string;
  text?: string;
}
export type ResolvedMap = Record<string, ResolvedCite>;

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
