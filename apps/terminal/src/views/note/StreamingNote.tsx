/** Live draft of the research note (design §4.1, streamed). The synthesis is a forced tool call, so the SSE
 *  `token` deltas are partial tool-input JSON — we best-effort pull the human text (tldr/mechanism) out so the
 *  note visibly writes itself instead of blocking on the full completion. Deliberately NO citation chips and
 *  NO integrity strip: those render only on the FINAL, verified structured note (Note.tsx / IntegrityStrip),
 *  preserving "trust machinery renders post-verify." */

function unescapeJson(s: string): string {
  return s.replace(/\\n/g, '\n').replace(/\\t/g, '  ').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
}

function field(raw: string, key: string): string {
  // a completed  "key":"…"  wins; otherwise the still-open  "key":"…(no close yet)
  const done = raw.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`))?.[1];
  if (done != null) return unescapeJson(done);
  const open = raw.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)$`))?.[1];
  return open != null ? unescapeJson(open) : '';
}

/** Extract the (possibly partial) tldr + mechanism from the accumulating tool-input JSON. */
export function streamingPreview(raw: string): { tldr: string; mechanism: string } {
  try {
    const o = JSON.parse(raw) as { tldr?: string; mechanism?: string };
    return { tldr: o.tldr ?? '', mechanism: o.mechanism ?? '' };
  } catch {
    return { tldr: field(raw, 'tldr'), mechanism: field(raw, 'mechanism') };
  }
}

export function StreamingNote({ draft }: { draft: string }) {
  const { tldr, mechanism } = streamingPreview(draft);
  if (!tldr && !mechanism) return null;
  const label = 'font-mono text-11 uppercase tracking-wider text-text-dim';
  const caret = <span className="ml-0.5 animate-pulse text-amber">▍</span>;
  return (
    <article className="max-w-3xl" data-testid="note-draft" aria-busy="true">
      <div className={label}>
        TL;DR <span className="text-amber">· drafting</span>
      </div>
      <p className="mt-1 whitespace-pre-wrap font-sans text-18 font-semibold leading-snug text-text">
        {tldr}
        {!mechanism && caret}
      </p>
      {mechanism && (
        <>
          <div className={`mt-4 ${label}`}>Why</div>
          <p className="mt-1 whitespace-pre-wrap font-sans text-14 leading-relaxed text-text">
            {mechanism}
            {caret}
          </p>
        </>
      )}
    </article>
  );
}
