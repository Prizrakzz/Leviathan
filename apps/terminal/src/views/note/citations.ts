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

/** D-TW-23: the open-receipts handler a citation chip fires, or NULL when this render has no receipts to
 *  open (a durable turn reopened from the thread store: TurnRecord is PIT-firewalled, so the drawer's
 *  evidence tiers do not exist client-side). NULL is the DECLARED "no receipts here" state -- chips render
 *  visibly inert and say why. It exists so the dead affordance can never come back as a silent `noop`,
 *  which is exactly how D-TW-23 shipped: the type could not tell a wired handler from a stub. */
export type CiteOpen = ((ref: string) => void) | null;

type Src = { ref?: unknown; source?: unknown; date?: unknown; source_key?: unknown; char_start?: unknown; offset_kind?: unknown };
type Cit = { id?: unknown; kind?: unknown; locator?: { source_key?: unknown; snippet?: unknown; kind?: unknown } };

/** The doc locator (6.5) a chip carries to open its source PDF: the text-layer `source_key` + the cited
 *  snippet, and — WHEN the structured source carries them (new/E4 props) — the char offset that lets the
 *  backend resolve an EXACT page. Offsets are passed through defensively (optional chaining): absent on
 *  legacy props, so their keys are OMITTED rather than set to undefined. Legacy props still get a locator
 *  (source_key + snippet), resolving via server-side snippet fuzzy-match. */
function docLocator(sourceKey: string, snippet: string | undefined, src?: Src): Record<string, unknown> {
  const loc: Record<string, unknown> = { kind: 'doc', source_key: sourceKey, snippet };
  if (src?.char_start !== undefined) loc.char_start = src.char_start;
  if (src?.offset_kind !== undefined) loc.offset_kind = src.offset_kind;
  return loc;
}

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
  const numLocByRef = new Map<string, Record<string, unknown>>();   // exact machine id, e.g. 'N4'
  // H1: the ledger `ref` a [N4] prose handle resolves through is the BARE DIGIT '4' (answer.py forces an
  // integer ref; the machine id stays typed 'N4'). Keyed by the digit here so a rendered [N] chip finds its
  // query-provenance. Kept in a SEPARATE map (not merged into numLocByRef) so the digit alias can never
  // shadow an evidence doc locator that shares that digit (E4 and N4 are independent sequences).
  const numLocByDigit = new Map<string, Record<string, unknown>>();
  for (const c of cits) {
    const key = c.locator?.source_key;
    if (typeof key === 'string' && typeof c.locator?.snippet === 'string') snippetByKey.set(key, c.locator.snippet);
    if (c.locator?.kind === 'number' && typeof c.id === 'string') {
      const nloc = c.locator as Record<string, unknown>;
      numLocByRef.set(c.id, nloc);
      numLocByDigit.set(c.id.replace(/^[A-Za-z]+/, ''), nloc);
    }
  }
  const refs = new Set<string>([...Object.keys(live ?? {}), ...structuredSources.map((s) => String(s.ref))]);
  for (const ref of refs) {
    if (!ref || ref === 'undefined') continue;
    const ss = structuredSources.find((s) => String(s.ref) === ref);
    const lr = live?.[ref];
    const sk = ss?.source_key;
    const text = lr?.text ?? (typeof sk === 'string' ? snippetByKey.get(sk) : undefined);
    const source = (ss?.source as string | undefined) ?? lr?.source;
    if (source == null && text == null && !numLocByRef.has(ref) && !numLocByDigit.has(ref)) continue; // nothing to show → no chip
    // Number locators keep precedence (a number ref keeps its query locator): the exact machine id first, then
    // the bare-digit alias ONLY when this ref has no doc source_key of its own (so an evidence [E4] never picks
    // up N4's number locator). Otherwise a structured source WITH a source_key gets a doc locator so the chip
    // can open its source PDF at the cited page (6.5).
    const numLoc = numLocByRef.get(ref) ?? (typeof sk === 'string' ? undefined : numLocByDigit.get(ref));
    const locator = numLoc ?? (typeof sk === 'string' ? docLocator(sk, text, ss) : undefined);
    out[ref] = { source, date: (ss?.date as string | undefined) ?? lr?.date, text, locator };
  }
  return out;
}

export type NoteSegment = { kind: 'text'; text: string } | { kind: 'cite'; ref: string; resolved: ResolvedCite };

const CITE = /\[([A-Za-z]?)(\d+)\]/g; // [1] [E2] [N1] — g1 = type prefix (E/N/''), g2 = the bare ledger integer

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
    const key = m[2] as string;                 // the bare ledger integer used to look the chip up
    const ref = (m[1] ?? '') + key;             // the full TYPED handle kept as the display ref
    const at = m.index ?? 0;
    if (resolved[key]) {
      if (at > last) out.push({ kind: 'text', text: text.slice(last, at) });
      out.push({ kind: 'cite', ref, resolved: resolved[key] });
      last = at + m[0].length;
    }
    // unresolved [n]: leave in place as text (handled by the trailing slice)
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}
