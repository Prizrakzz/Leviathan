/**
 * Phase F — locate a server-recovered citation span/sentence inside a pdf.js text layer (pure, unit-tested;
 * jsdom cannot run pdf.js, so everything DOM-adjacent stays in PdfViewer and everything decidable lives here).
 *
 * THE MEASURED MECHANIC (data/dec_p0/page_highlight.md §4, run against pdf.js 6.1.200 on 215 real props):
 * build the searchable page string EXACTLY as pdf.js's find controller does — concatenate `item.str`,
 * append '\n' when `item.hasEOL` — then RAW SUBSTRING search. On byte-exact replays that hits 99.4% at T0,
 * and the whole tolerance ladder bought ZERO additional hits; the single divergence class was accented
 * glyphs. So: `indexOf` first, then ONE normalized fallback (whitespace collapse + diacritic fold, with a
 * position map back to raw offsets) standing in for the server's difflib leg. A miss returns null and the
 * viewer keeps today's page-jump behaviour — the degrade is the design, never an error.
 *
 * INDEX ALIGNMENT LAW (pdf.mjs:14934-15005): `textContentItemsStr[i]` pairs 1:1 with `textDivs[i]`, but a
 * div is APPENDED to the container only when `str !== ''` — empty-string items produce a DETACHED span.
 * The run map therefore skips zero-length items entirely: their divs are not in the DOM and must never be
 * offset targets.
 */

export interface TextItemLike {
  str: string;
  hasEOL?: boolean;
}

export interface TextRun {
  divIndex: number; // index into layer.textDivs (and textContentItemsStr)
  start: number; // [start, end) in pageText
  end: number;
}

export interface PageTextMap {
  pageText: string;
  runs: TextRun[];
}

/** Concatenate items into the find-controller page string, recording each NON-EMPTY item's [start,end). */
export function buildPageMap(items: TextItemLike[]): PageTextMap {
  let text = '';
  const runs: TextRun[] = [];
  items.forEach((it, i) => {
    if (it.str !== '') {
      runs.push({ divIndex: i, start: text.length, end: text.length + it.str.length });
      text += it.str;
    }
    if (it.hasEOL) text += '\n';
  });
  return { pageText: text, runs };
}

/** Diacritic-fold + whitespace-collapse `s`, returning the folded string and a map from each folded index
 *  back to its RAW index. NFD splits base+combining mark; marks are dropped (never mapped); every run of
 *  whitespace folds to one space mapped to the run's first raw char. The trailing '...' a 140-char locator
 *  snippet carries is stripped by the CALLER (mirrors pdfpage._norm), not here. */
function foldWithMap(s: string): { folded: string; map: number[] } {
  let folded = '';
  const map: number[] = [];
  let pendingSpace = -1; // raw index of the first ws char of a pending run
  for (let raw = 0; raw < s.length; raw++) {
    const ch = s.charAt(raw);
    if (/\s/.test(ch)) {
      if (pendingSpace < 0) pendingSpace = raw;
      continue;
    }
    if (pendingSpace >= 0) {
      if (folded.length > 0) {
        folded += ' ';
        map.push(pendingSpace);
      }
      pendingSpace = -1;
    }
    const nfd = ch.normalize('NFD');
    for (const part of nfd) {
      if (/\p{M}/u.test(part)) continue; // combining mark: folded away
      folded += part;
      map.push(raw);
    }
  }
  return { folded, map };
}

/** Locate `needle` in the page map: raw indexOf first (the measured 99.4% path), else the folded fallback
 *  (accent/whitespace divergences). Returns RAW [start, end) into pageText, or null — never throws. */
export function locateInPage(map: PageTextMap, needle: string): { start: number; end: number } | null {
  const clean = needle.replace(/\.\.\.$/, '').trim();
  if (!clean) return null;
  const raw = map.pageText.indexOf(clean);
  if (raw >= 0) return { start: raw, end: raw + clean.length };
  const hay = foldWithMap(map.pageText);
  const ned = foldWithMap(clean);
  if (!ned.folded) return null;
  const at = hay.folded.indexOf(ned.folded);
  if (at < 0) return null;
  const start = hay.map[at];
  const last = hay.map[at + ned.folded.length - 1];
  if (start == null || last == null || last + 1 <= start) return null;
  return { start, end: last + 1 };
}

export interface DivRange {
  divIndex: number;
  startOffset: number; // character offsets LOCAL to that div's text node
  endOffset: number;
}

/** Slice a located [start, end) range into per-div local ranges — one DOM Range per overlapping run. The
 *  '\n' the map inserts for hasEOL belongs to NO run, so it never produces a range. */
export function rangesForSpan(map: PageTextMap, start: number, end: number): DivRange[] {
  const out: DivRange[] = [];
  for (const r of map.runs) {
    const s = Math.max(start, r.start);
    const e = Math.min(end, r.end);
    if (e > s) out.push({ divIndex: r.divIndex, startOffset: s - r.start, endOffset: e - r.start });
  }
  return out;
}
