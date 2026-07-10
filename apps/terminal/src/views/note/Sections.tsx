import type { Section } from '@/api/schema';
import type { ResolvedMap } from './citations';
import { FormattedNote, renderInline } from './inlineFormat';

/** P9-C per-kind note body — renders `structured.sections`, the backend-DERIVED view of `mechanism`
 *  (never independently authored; mechanism stays canonical). Kinds unlock what a flat `## ` heading
 *  can't express: the disagreement fork LOOKS like a fork (amber callout), the record reads as a data
 *  card. Unknown kinds and kind "other" degrade to plain prose so a newer backend's sections never
 *  blank an older bundle. Cards stay compact — the chat panel can be 160px tall. */

/** Heading tier matches inlineFormat's `## ` branch (h5) so the sections path and the mechanism
 *  fallback read identically; text comes from `section.heading` (no hardcoded English). */
function Heading({
  text,
  tone,
  resolved,
  onOpen,
}: {
  text: string;
  tone?: 'amber';
  resolved: ResolvedMap;
  onOpen: (r: string) => void;
}) {
  if (!text) return null; // pre-prose section (empty heading): body only
  return (
    <h5 className={`mb-0.5 text-[13px] font-semibold ${tone === 'amber' ? 'text-amber' : 'text-text'}`}>
      {renderInline(text, resolved, onOpen)}
    </h5>
  );
}

export function Sections({
  sections,
  resolved,
  onOpen,
}: {
  sections: Section[];
  resolved: ResolvedMap;
  onOpen: (r: string) => void;
}) {
  return (
    <div className="space-y-2" data-testid="sections">
      {sections.map((s, i) => {
        const body = <FormattedNote text={s.body} resolved={resolved} onOpen={onOpen} />;
        if (s.kind === 'disagreement') {
          // The fork must look like a fork — the Banners.tsx amber-callout card idiom.
          return (
            <div
              key={i}
              data-testid="section-disagreement"
              className="rounded-panel border border-amber bg-bg-1 px-3 py-2"
            >
              <Heading text={s.heading} tone="amber" resolved={resolved} onOpen={onOpen} />
              {body}
            </div>
          );
        }
        if (s.kind === 'record') {
          // Compact data card (the Numbers.tsx panel idiom); v1 = styled prose, no table.
          return (
            <div key={i} data-testid="section-record" className="rounded-panel border border-line bg-bg-1 px-3 py-2">
              <Heading text={s.heading} resolved={resolved} onOpen={onOpen} />
              {body}
            </div>
          );
        }
        // mechanism / watch / other / any unknown kind: heading + plain prose.
        return (
          <div key={i} data-testid={`section-${s.kind}`}>
            <Heading text={s.heading} resolved={resolved} onOpen={onOpen} />
            {body}
          </div>
        );
      })}
    </div>
  );
}
