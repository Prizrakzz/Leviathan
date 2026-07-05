import * as Tooltip from '@radix-ui/react-tooltip';
import type { RespondResult } from '@/api/schema';
import { CitationChip } from './CitationChip';
import { resolvedMap, tokenizeCitations, type ResolvedMap } from './citations';

function Inline({ text, resolved, onOpen }: { text: string; resolved: ResolvedMap; onOpen: (r: string) => void }) {
  const segs = tokenizeCitations(text, resolved);
  return (
    <>
      {segs.map((s, i) =>
        s.kind === 'text' ? (
          <span key={i}>{s.text}</span>
        ) : (
          <CitationChip key={i} refId={s.ref} resolved={s.resolved} onOpen={onOpen} />
        ),
      )}
    </>
  );
}

/** The research note (design §4.1) — `structured.{tldr, mechanism, sources}` as a forwardable analyst
 *  note, with resolved citations as interactive chips. The floor/refusal/no-match states have no
 *  `structured` and render their banner instead (§5), so this returns null for them. */
export function Note({ result, onOpenReceipts }: { result: RespondResult; onOpenReceipts: (ref?: string) => void }) {
  const s = result.structured;
  if (!s) return null;
  const resolved = resolvedMap(result);
  const sources = (s.sources ?? []) as { ref?: unknown; source?: unknown; date?: unknown }[];
  const label = 'font-mono text-11 uppercase tracking-wider text-text-dim';
  return (
    <Tooltip.Provider delayDuration={150}>
      <article className="max-w-3xl" data-testid="note">
        <div className={label}>TL;DR</div>
        <p className="mt-1 font-sans text-18 font-semibold leading-snug text-text">
          <Inline text={s.tldr ?? ''} resolved={resolved} onOpen={onOpenReceipts} />
        </p>

        {s.mechanism && (
          <>
            <div className={`mt-4 ${label}`}>Why</div>
            <p className="mt-1 whitespace-pre-wrap font-sans text-14 leading-relaxed text-text">
              <Inline text={s.mechanism} resolved={resolved} onOpen={onOpenReceipts} />
            </p>
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
