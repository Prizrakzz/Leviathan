import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { RespondResult } from '@/api/schema';
import { ModeChip } from './ModeChip';

const KNOBS = {
  node_budget: 16,
  depth: 3,
  max_seeds: 3,
  k_by_depth: [7, 5, 3],
  evidence_cap: 48,
  probe_cap: 36,
  fetch_k: 120,
  silver_cap: 12,
  scaffold_max_bullets: 12,
  scaffold_max_absence: 6,
  budget_scale: 1.5,
  xc_force: true,
};

const turn = (over: Partial<RespondResult> = {}): RespondResult =>
  ({ answer: 'a', ...over }) as RespondResult;

const deepTurn = () =>
  turn({
    intent_decision: { mode: { requested: 'deep', honored: 'deep', invalid: false } },
    trace: { mode_knobs: KNOBS },
  });

describe('ModeChip — what actually ran (D-AM-14)', () => {
  it('renders the honored mode name, collapsed', () => {
    render(<ModeChip result={deepTurn()} />);
    expect(screen.getByTestId('mode-chip-toggle')).toHaveTextContent('ran deep');
    expect(screen.getByTestId('mode-chip-toggle').getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByTestId('mode-chip-knobs')).toBeNull();
  });

  it('expands to the RESOLVED knob values (the trace-details idiom)', async () => {
    const user = userEvent.setup();
    render(<ModeChip result={deepTurn()} />);
    await user.click(screen.getByTestId('mode-chip-toggle'));

    const knobs = screen.getByTestId('mode-chip-knobs');
    expect(knobs).toHaveTextContent('depth');
    expect(knobs).toHaveTextContent('fetch k');
    expect(knobs).toHaveTextContent('120');
    expect(knobs).toHaveTextContent('7/5/3'); // k_by_depth arrives as a JSON list
    expect(knobs).toHaveTextContent('xc force');
    expect(knobs).toHaveTextContent('on'); // booleans read as on/off, not "true"
    expect(screen.getByTestId('mode-chip-toggle').getAttribute('aria-expanded')).toBe('true');

    await user.click(screen.getByTestId('mode-chip-toggle'));
    expect(screen.queryByTestId('mode-chip-knobs')).toBeNull();
  });

  it('a knob this bundle has never heard of still renders (open shape)', async () => {
    const user = userEvent.setup();
    render(
      <ModeChip
        result={turn({
          intent_decision: { mode: { requested: 'quick', honored: 'quick', invalid: false } },
          trace: { mode_knobs: { depth: 1, some_future_knob: 9 } },
        })}
      />,
    );
    await user.click(screen.getByTestId('mode-chip-toggle'));
    expect(screen.getByTestId('mode-chip-knobs')).toHaveTextContent('some future knob');
    expect(screen.getByTestId('mode-chip-knobs')).toHaveTextContent('9');
  });

  it('the escalated bundle stays invisible: the synthesis seat and the prompt flag never render', async () => {
    // D-MW-30 (30f review). An escalated turn is honored `deep` and stamps the ESCALATED knob dict, which
    // carries two fields that are not width: synth_model (the writer) and provenance_prompt (a prompt
    // flag). The open-shape passthrough above would have rendered both verbatim under a header reading
    // "ran deep" -- a new disclosure of writer identity, made by side effect. The width knobs still render.
    const user = userEvent.setup();
    render(
      <ModeChip
        result={turn({
          intent_decision: { mode: { requested: 'deep', honored: 'deep', invalid: false } },
          trace: {
            mode_knobs: {
              ...KNOBS,
              per_seed_budget: 63,
              synth_model: 'claude-opus-5',
              provenance_prompt: true,
            },
          },
        })}
      />,
    );
    expect(screen.getByTestId('mode-chip-toggle')).toHaveTextContent('ran deep');
    await user.click(screen.getByTestId('mode-chip-toggle'));

    const knobs = screen.getByTestId('mode-chip-knobs');
    expect(knobs).not.toHaveTextContent('synth model');
    expect(knobs).not.toHaveTextContent('claude-opus-5');
    expect(knobs).not.toHaveTextContent('provenance prompt');
    expect(knobs).toHaveTextContent('per seed budget'); // a genuine WIDTH knob still passes through
    expect(knobs).toHaveTextContent('63');
  });

  it('the Q-0 effort knob never renders: writer property, not width', async () => {
    // Q-0 (2026-08-29, review find F4). synth_effort rides the max family's knob dict; the open-shape
    // passthrough would have rendered "synth effort  max" under "ran max" -- the same
    // writer-identity-by-side-effect class the deny list exists for.
    const user = userEvent.setup();
    render(
      <ModeChip
        result={turn({
          intent_decision: { mode: { requested: 'max', honored: 'max', invalid: false } },
          trace: {
            mode_knobs: {
              ...KNOBS,
              per_seed_budget: 63,
              synth_effort: 'max',
            },
          },
        })}
      />,
    );
    await user.click(screen.getByTestId('mode-chip-toggle'));
    const knobs = screen.getByTestId('mode-chip-knobs');
    expect(knobs).not.toHaveTextContent('synth effort');
    expect(knobs).toHaveTextContent('per seed budget');
  });

  describe('renders NOTHING when nothing non-standard ran', () => {
    it('a standard turn', () => {
      render(
        <ModeChip
          result={turn({ intent_decision: { mode: { requested: null, honored: 'standard', invalid: false } } })}
        />,
      );
      expect(screen.queryByTestId('mode-chip')).toBeNull();
    });

    it('a DARK turn: deep was asked for, standard governed', () => {
      // GRAPHRAG_MODES off -> accepted, resolved, stamped, NOT honored. `honored` is the fact the chip
      // reports; `requested` is not.
      render(
        <ModeChip
          result={turn({ intent_decision: { mode: { requested: 'deep', honored: 'standard', invalid: false } } })}
        />,
      );
      expect(screen.queryByTestId('mode-chip')).toBeNull();
    });

    it('an EXEMPT lane: deep honored, but no knob was consumed so no knobs were stamped', () => {
      // live / numbers_only. Claiming "ran deep" here would name a depth that never ran -- the chip is
      // gated on the KNOBS, not on the request.
      render(
        <ModeChip
          result={turn({
            intent: 'numbers_only',
            intent_decision: { mode: { requested: 'deep', honored: 'deep', invalid: false } },
          })}
        />,
      );
      expect(screen.queryByTestId('mode-chip')).toBeNull();
    });

    it('an older backend with no mode stamps at all', () => {
      render(<ModeChip result={turn({ trace: { graph_version: 'gv' } })} />);
      expect(screen.queryByTestId('mode-chip')).toBeNull();
    });
  });
});
