import type { Section } from '@/api/schema';

/**
 * P9-E1a: deterministic, zero-LLM watch chips off the answer's "What to watch" section. PRIMARY source =
 * the Phase-C typed sections (kind === 'watch'); FALLBACK = the '## What to watch' heading parsed out of
 * the flat `mechanism` string (legacy turns + GRAPHRAG_ANSWER_V2 off). Both are server-sanitized before
 * the FE sees them, so no register handling here. A turn with no watch section yields zero chips.
 */

/** Watch items are full mentor sentences; the server-side 140-char suggest cap never sees this
 *  FE-derived path, so the chip needs its own display cap. */
const MAX_CHARS = 90;
const MAX_CHIPS = 4;

const WATCH_HEADING = /^\s*#{1,3}\s+what to watch\s*$/i;
const HEADING = /^\s*#{1,3}\s+/;
const BULLET = /^\s*[-*]\s+(.*)$/;
/** `[1]` / `[E2]` / `[N1]` citation markers (the inlineFormat CITE shape) -- noise in a chip/prefill. */
const CITE_MARK = /\[[A-Za-z]?\d+\]/g;

interface StructuredLike {
  mechanism?: string | null;
  sections?: Section[] | null;
}

/** Cap at a word boundary so a chip never cuts mid-word. */
function clip(text: string): string {
  if (text.length <= MAX_CHARS) return text;
  const cut = text.slice(0, MAX_CHARS);
  const space = cut.lastIndexOf(' ');
  return (space > 0 ? cut.slice(0, space) : cut).trimEnd() + '\u2026';
}

/** Lines of the watch block: typed section body first, else the mechanism heading parse (stops at the
 *  next heading, so the '## Sources' footer never leaks into chips). */
function watchLines(structured: StructuredLike | null | undefined): string[] {
  if (!structured) return [];
  const sec = structured.sections?.find((s) => s.kind === 'watch');
  if (sec) return sec.body.split('\n');
  const lines = (structured.mechanism ?? '').split('\n');
  const start = lines.findIndex((l) => WATCH_HEADING.test(l));
  if (start === -1) return [];
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((l) => HEADING.test(l));
  return end === -1 ? rest : rest.slice(0, end);
}

/**
 * Derive prefill chips (bullet lines only) from the watch section. `exclude` = the server suggestion
 * texts: SuggestionChips keys by chip text, so a duplicate would be a React key collision on top of a
 * redundant chip. Also dedupes within the watch bullets themselves.
 */
export function deriveWatchChips(
  structured: StructuredLike | null | undefined,
  exclude: string[] = [],
): string[] {
  const seen = new Set(exclude);
  const out: string[] = [];
  for (const line of watchLines(structured)) {
    const m = line.match(BULLET);
    if (!m) continue;
    const text = clip((m[1] ?? '').replace(CITE_MARK, '').replace(/\s+/g, ' ').trim());
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
    if (out.length >= MAX_CHIPS) break;
  }
  return out;
}
