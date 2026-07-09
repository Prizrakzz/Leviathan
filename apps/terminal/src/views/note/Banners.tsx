import type { ReactNode } from 'react';
import type { RespondResult } from '@/api/schema';

type Tone = 'amber' | 'cyan' | 'neutral';
const TONE: Record<Tone, string> = {
  amber: 'border-amber text-amber',
  cyan: 'border-cyan text-cyan',
  neutral: 'border-line text-text-dim',
};

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <div className={`mb-3 rounded-panel border bg-bg-1 px-3 py-2 font-sans text-13 ${TONE[tone]}`} role="status">
      {children}
    </div>
  );
}

/** State banners (design §5): degraded / evidence-only floor / guardrail refusal / no-contract-match. The
 *  refusal + floor + no-match states replace the note; degraded rides above it. */
export function Banners({ result }: { result: RespondResult }) {
  const t = (result.trace ?? {}) as {
    degraded_model?: string; floor?: string; suggestions?: string[]; attachment_note?: string;
  };

  if (result.intent === 'refused') {
    return <Banner tone="neutral">This query was flagged by the input safety filter and was not processed.</Banner>;
  }
  if (t.floor) {
    return (
      <Banner tone="cyan">
        Reasoning tier unavailable — showing retrieved, cited evidence only, no synthesized conclusions.
      </Banner>
    );
  }
  // W1.1.2: numbers_only turns have structured=null BY DESIGN (no walk ran) — they must never claim
  // "no contract matched". By this line refused/floor already early-returned, so the only null-structured
  // states left are numbers_only and a genuinely-unrouted reasoning turn (which still banners).
  const noMatch =
    !result.structured &&
    result.intent !== 'numbers_only' &&
    (result.contracts ?? []).length === 0;
  return (
    <>
      {t.degraded_model && (
        <Banner tone="amber">
          Degraded — served by {t.degraded_model} after retries; treat with extra caution.
        </Banner>
      )}
      {noMatch && (
        <Banner tone="neutral">
          No tracked contract matched — did you mean {(t.suggestions ?? []).join(', ') || 'one of the 31 tickers'}?
        </Banner>
      )}
      {/* P2: a future-dated attached event was PIT-withheld — say so on every turn type (C1). */}
      {t.attachment_note && <Banner tone="neutral">{t.attachment_note}</Banner>}
    </>
  );
}
