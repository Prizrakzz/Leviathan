import { useState } from 'react';
import type { RespondResult } from '@/api/schema';

/**
 * D-AM-14 — the "what ran" chip: a subtle, collapsed line on a finished turn saying which reasoning depth
 * actually governed it, expandable to the resolved knob values (the FindingsFeed toggle idiom: a rotating
 * ▸ and `aria-expanded`, not a second disclosure pattern).
 *
 * IT IS GATED ON THE KNOBS, NOT ON THE REQUEST. `intent_decision.mode.honored` rides every turn including
 * ones where the mode was accepted but NOT honored (the dark flag) and the exempt lanes (live /
 * numbers_only) where a honored mode consumes no knob at all. `trace.mode_knobs` is stamped only where a
 * non-standard depth genuinely ran — so requiring it is the difference between a chip that reports what
 * happened and a chip that repeats what was asked for. Standard turns, dark turns and exempt lanes render
 * NOTHING, which is also what makes this additive: a backend without D-AM stamps leaves the view as it was.
 */

/** Display order: the walk shape first (what the chip is really claiming), then the read caps, then the
 *  write-side effects. A knob this bundle has never heard of is appended rather than dropped. */
const KNOB_ORDER = [
  'depth',
  'node_budget',
  'max_seeds',
  'k_by_depth',
  'evidence_cap',
  'probe_cap',
  'fetch_k',
  'silver_cap',
  'scaffold_max_bullets',
  'scaffold_max_absence',
  'budget_scale',
  'xc_force',
] as const;

/**
 * NOT KNOBS, AND NEVER RENDERED (D-MW-30, 30f review). The unknown-key passthrough below exists so a new
 * WIDTH knob shows up in the chip the day the backend starts sending it. These two are not width: they are
 * the SYNTHESIS SEAT and a PROMPT flag that the escalated `esc`/`esc_r` bundles carry, and the passthrough
 * would have rendered them verbatim — showing "ran deep" above a row reading "synth model claude-opus-5"
 * on any escalated turn. That is a new disclosure of writer identity made by side effect, which is not
 * what the chip is for and not what F8 ("the escalation is invisible to the FE") intended.
 *
 * THE ESCALATION STAYS INVISIBLE, ON PURPOSE. Serving stamps honored=deep, `esc`/`esc_r` are never added
 * to mode.ts DARK_TIERS, and there is deliberately NO "escalated" badge here. A badge is real product
 * polish — "we spent more on this one for you" is a nice thing to be able to say — but it is a PRODUCT
 * decision with its own copy, its own expectation-setting and its own measurement, not a side effect of a
 * knob table growing two fields. Recorded as not-built, deliberately.
 */
const KNOB_DENY = ['synth_model', 'provenance_prompt'] as const;

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.join('/'); // k_by_depth [7,5,3] -> 7/5/3
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  return String(v);
}

export function ModeChip({ result }: { result: RespondResult }) {
  const [open, setOpen] = useState(false);
  const honored = result.intent_decision?.mode?.honored;
  const knobs = result.trace?.mode_knobs;
  if (!honored || honored === 'standard' || !knobs) return null;

  const known = KNOB_ORDER.filter((k) => knobs[k] !== undefined) as string[];
  const extra = Object.keys(knobs)
    .filter(
      (k) =>
        knobs[k] !== undefined &&
        !(KNOB_ORDER as readonly string[]).includes(k) &&
        !(KNOB_DENY as readonly string[]).includes(k),
    )
    .sort();
  const keys = [...known, ...extra];

  return (
    <div className="max-w-3xl" data-testid="mode-chip">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid="mode-chip-toggle"
        className="flex items-center gap-1.5 rounded-chip border border-line px-2 py-0.5 font-mono text-11 text-text-faint hover:border-cyan hover:text-cyan"
      >
        <span
          aria-hidden="true"
          className={`transition-transform duration-hover ${open ? 'rotate-90' : ''}`}
        >
          ▸
        </span>
        <span>ran {honored}</span>
      </button>
      {open && keys.length > 0 && (
        <dl
          className="mt-1 grid max-w-md grid-cols-2 gap-x-4 font-mono text-11"
          data-testid="mode-chip-knobs"
        >
          {keys.map((k) => (
            <div key={k} className="flex items-baseline justify-between gap-2">
              <dt className="truncate text-text-faint">{k.replace(/_/g, ' ')}</dt>
              <dd className="text-text-dim">{fmt(knobs[k])}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
