import * as Tooltip from '@radix-ui/react-tooltip';
import type { ReactNode } from 'react';
import type { RespondResult } from '@/api/schema';
import { resolvedFor } from './citations';
import { FormattedNote, renderInline } from './inlineFormat';
import { Sections } from './Sections';

/** The research note (design §4.1) — `structured.{tldr, mechanism, sources}` as a forwardable analyst
 *  note, with resolved citations as interactive chips. The floor/refusal/no-match states have no
 *  `structured` and render their banner instead (§5), so this returns null for them. */
export function Note({
  result,
  onOpenReceipts,
  afterTldr,
}: {
  result: RespondResult;
  onOpenReceipts: (ref?: string) => void;
  afterTldr?: ReactNode; // 6.3: the causal map renders here, between the TL;DR and "Why"
}) {
  const s = result.structured;
  if (!s) return null;
  const resolved = resolvedFor(result);
  const sources = (s.sources ?? []) as { ref?: unknown; source?: unknown; date?: unknown }[];
  const label = 'font-mono text-11 uppercase tracking-wider text-text-dim';
  return (
    <Tooltip.Provider delayDuration={150}>
      <article className="max-w-3xl" data-testid="note">
        <div className={label}>TL;DR</div>
        <p className="mt-1 font-sans text-18 font-semibold leading-snug text-text">
          {renderInline(s.tldr ?? '', resolved, onOpenReceipts)}
        </p>

        {afterTldr && <div className="mt-3">{afterTldr}</div>}

        {/* P9-C: typed sections (derived from mechanism) win when present; else the flat mechanism —
            old turns and flag-off answers carry no sections and keep today's render. */}
        {(s.sections?.length || s.mechanism) && (
          <>
            <div className={`mt-4 ${label}`}>Why</div>
            <div className="mt-1 font-sans text-14 leading-relaxed text-text">
              {s.sections?.length ? (
                <Sections sections={s.sections} resolved={resolved} onOpen={onOpenReceipts} />
              ) : (
                <FormattedNote text={s.mechanism ?? ''} resolved={resolved} onOpen={onOpenReceipts} />
              )}
            </div>
          </>
        )}

        {sources.length > 0 && (
          <>
            <div className={`mt-4 ${label}`}>Sources</div>
            <div className="mt-1 flex flex-wrap gap-3 font-mono text-11 text-text-dim">
              {sources.map((src, i) => (
                <button key={i} className="hover:text-cyan" onClick={() => onOpenReceipts(String(src.ref))}>
                  [{String(src.ref)}] {String(src.source)} {String(src.date)}
                </button>
              ))}
            </div>
          </>
        )}
      </article>
    </Tooltip.Provider>
  );
}
