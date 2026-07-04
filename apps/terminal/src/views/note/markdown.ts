import type { RespondResult } from '@/api/schema';

/** Render a note as forwardable markdown (the `y` copy action, design §4.1). */
export function noteToMarkdown(r: RespondResult): string {
  const s = r.structured;
  if (!s) return r.answer ?? '';
  const out: string[] = [`# ${r.contract ?? 'note'} — as-of ${r.asof ?? ''}`, '', `**TL;DR** ${s.tldr ?? ''}`];
  if (s.mechanism) out.push('', `**Why** ${s.mechanism}`);
  const srcs = (s.sources ?? []) as { ref?: unknown; source?: unknown; date?: unknown }[];
  if (srcs.length) {
    out.push('', '**Sources**');
    for (const x of srcs) out.push(`- [${String(x.ref)}] ${String(x.source)} ${String(x.date)}`);
  }
  const gv = (r.trace as { graph_version?: string } | undefined)?.graph_version;
  out.push('', `_served-by ${String(r.model ?? '?')} · graph ${String(gv ?? '?')}_`);
  return out.join('\n');
}
