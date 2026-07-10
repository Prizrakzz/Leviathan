import type { ReactNode } from 'react';
import { CitationChip } from './CitationChip';
import type { ResolvedCite, ResolvedMap } from './citations';

/** Phase 6.1 — a tiny, streaming-safe formatter for the research note. Renders a SAFE markdown subset
 *  (bold, italic, `-` bullets) plus citation chips, and STRIPS any stray/unpaired marker so a raw `*`
 *  or `**` can never reach the DOM (the guarantee the backend register-sanitizer can't give the live
 *  streaming draft). No `dangerouslySetInnerHTML` — nodes are built, so there is no HTML-injection
 *  surface. Pure functions over the already-revealed text; safe on partial (mid-stream) strings. */

type Tok =
  | { k: 'text'; v: string }
  | { k: 'strong'; v: Tok[] }
  | { k: 'em'; v: Tok[] }
  | { k: 'cite'; ref: string; resolved: ResolvedCite };

const CITE = /^\[([A-Za-z]?\d+)\]/; // [1] [E2] [N1] at the cursor

/** Tokenize inline markup. A `**bold**`/`*em*` with no closing marker (common mid-stream) has its
 *  marker DROPPED, never shown; an unresolved `[n]` stays literal text. */
export function parseInline(text: string, resolved: ResolvedMap): Tok[] {
  const out: Tok[] = [];
  let buf = '';
  let i = 0;
  const flush = () => {
    if (buf) {
      out.push({ k: 'text', v: buf });
      buf = '';
    }
  };
  while (i < text.length) {
    const rest = text.slice(i);
    const cm = rest.match(CITE);
    if (cm && resolved[cm[1] as string]) {
      flush();
      out.push({ k: 'cite', ref: cm[1] as string, resolved: resolved[cm[1] as string] as ResolvedCite });
      i += cm[0].length;
      continue;
    }
    if (rest.startsWith('**')) {
      const close = text.indexOf('**', i + 2);
      if (close !== -1) {
        flush();
        out.push({ k: 'strong', v: parseInline(text.slice(i + 2, close), resolved) });
        i = close + 2;
        continue;
      }
      i += 2; // unpaired ** -> strip the marker
      continue;
    }
    if (text[i] === '*') {
      const close = text.indexOf('*', i + 1);
      if (close !== -1 && close > i + 1) {
        flush();
        out.push({ k: 'em', v: parseInline(text.slice(i + 1, close), resolved) });
        i = close + 1;
        continue;
      }
      i += 1; // unpaired * -> strip
      continue;
    }
    buf += text[i];
    i += 1;
  }
  flush();
  return out;
}

function renderToks(toks: Tok[], onOpen: (r: string) => void, kp: string): ReactNode[] {
  return toks.map((t, i) => {
    const key = `${kp}.${i}`;
    if (t.k === 'text') return <span key={key}>{t.v}</span>;
    if (t.k === 'strong') return <strong key={key}>{renderToks(t.v, onOpen, key)}</strong>;
    if (t.k === 'em') return <em key={key}>{renderToks(t.v, onOpen, key)}</em>;
    return <CitationChip key={key} refId={t.ref} resolved={t.resolved} onOpen={onOpen} />;
  });
}

/** Inline-only render (bold/italic/citations) — for the TL;DR, which is a single short paragraph. */
export function renderInline(text: string, resolved: ResolvedMap, onOpen: (r: string) => void): ReactNode {
  return <>{renderToks(parseInline(text ?? '', resolved), onOpen, 'i')}</>;
}

/** Block render for the note body: blank-line-separated paragraphs + `-`/`*` bullet runs become real
 *  `<ul>`; inline markup + citations resolve within. Consecutive non-bullet lines join with a space
 *  (markdown soft-wrap) so the body reads as clean prose, not a log dump. */
export function FormattedNote({
  text,
  resolved,
  onOpen,
}: {
  text: string;
  resolved: ResolvedMap;
  onOpen: (r: string) => void;
}): ReactNode {
  const lines = (text ?? '').split('\n');
  const blocks: ReactNode[] = [];
  let para: string[] = [];
  let items: string[] = [];
  const flushPara = () => {
    if (para.length) {
      blocks.push(
        <p key={`p${blocks.length}`} className="whitespace-pre-wrap">
          {renderInline(para.join(' '), resolved, onOpen)}
        </p>,
      );
      para = [];
    }
  };
  const flushList = () => {
    if (items.length) {
      blocks.push(
        <ul key={`u${blocks.length}`} className="list-disc space-y-1 pl-5">
          {items.map((it, i) => (
            <li key={i}>{renderInline(it, resolved, onOpen)}</li>
          ))}
        </ul>,
      );
      items = [];
    }
  };
  for (const raw of lines) {
    // P9-A: '## ' headings render as real headings (the mentor scaffold + the '## Sources' footer);
    // checked BEFORE the bullet branch so a '#' line is never mistaken for prose.
    const heading = raw.match(/^\s*(#{1,3})\s+(.*)$/);
    if (heading) {
      flushPara();
      flushList();
      const level = (heading[1] ?? '').length; // 1..3
      const txt = (heading[2] ?? '').trim();
      const Tag = (level <= 1 ? 'h4' : 'h5') as 'h4' | 'h5';
      blocks.push(
        <Tag key={`h${blocks.length}`} className="mt-2 mb-0.5 text-[13px] font-semibold text-text">
          {renderInline(txt, resolved, onOpen)}
        </Tag>,
      );
      continue;
    }
    const bullet = raw.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      flushPara();
      items.push((bullet[1] ?? '').trim());
      continue;
    }
    if (raw.trim() === '') {
      flushPara();
      flushList();
      continue;
    }
    flushList();
    para.push(raw.trim());
  }
  flushPara();
  flushList();
  return <div className="space-y-2">{blocks}</div>;
}
