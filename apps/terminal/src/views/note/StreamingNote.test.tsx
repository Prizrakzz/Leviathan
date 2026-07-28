import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ResolvedMap } from './citations';
import { StreamingNote } from './StreamingNote';

// The synthesis is a forced tool call, so the draft is (partial) tool-input JSON.
const DRAFT = JSON.stringify({
  tldr: 'Export pace is running ahead of the WASDE path [1].',
  mechanism: 'Inspections confirm the pace [2] and stocks are tight [N1].',
});

const RESOLVED: ResolvedMap = {
  '1': { source: 'USDA FAS GAIN', date: '2026-07-18', text: 'weekly inspections ran ahead of pace' },
  '2': { source: 'USDA WASDE', date: '2026-07-11', text: 'export commitments raised' },
  N1: { source: 'silver_psd', date: '2026-06-11', text: 'stocks-to-use 0.36', locator: { kind: 'number', table: 'silver_psd' } },
};

describe('F7 citation rule: INERT while streaming, LIVE only after verified', () => {
  it('pre-verified: every handle renders as visible-but-inert — no button, no receipt', () => {
    render(<StreamingNote draft={DRAFT} />);
    const inert = screen.getAllByTestId('cite-inert');
    expect(inert.map((n) => n.dataset.ref)).toEqual(['1', '2', 'N1']);
    expect(inert[0]!.textContent).toBe('[1]'); // still READABLE — the analyst sees the note cite as it writes
    expect(inert[0]!.tagName).toBe('SPAN'); // not a button: nothing to click, nothing to focus
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByTestId('note-draft').getAttribute('aria-busy')).toBe('true');
  });

  it('post-verified: the SAME handles become live citation chips that open receipts', async () => {
    const onOpen = vi.fn();
    render(<StreamingNote draft={DRAFT} resolved={RESOLVED} live onOpen={onOpen} />);
    expect(screen.queryByTestId('cite-inert')).toBeNull();
    const chips = screen.getAllByRole('button');
    expect(chips.map((b) => b.textContent)).toEqual(['[1]', '[2]', '[N1]']);
    await userEvent.click(chips[0]!);
    expect(onOpen).toHaveBeenCalledWith('1');
    expect(screen.getByTestId('note-draft').getAttribute('aria-busy')).toBe('false');
  });

  it('the swap is the ONLY change: the same handles, in the same places, before and after', () => {
    const view = render(<StreamingNote draft={DRAFT} />);
    const before = screen.getAllByTestId('cite-inert').map((n) => n.dataset.ref);
    view.rerender(<StreamingNote draft={DRAFT} resolved={RESOLVED} live />);
    const after = screen.getAllByRole('button').map((b) => b.textContent);
    expect(after).toEqual(before.map((r) => `[${r}]`)); // nothing the user could click ever disappears
  });

  it('`live` WITHOUT receipts stays inert — a chip must never point at nothing', () => {
    render(<StreamingNote draft={DRAFT} resolved={{}} live />);
    expect(screen.getAllByTestId('cite-inert')).toHaveLength(3);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders the partial draft it is given and nothing at all before the first token', () => {
    const { container } = render(<StreamingNote draft="" />);
    expect(container.firstChild).toBeNull();
    render(<StreamingNote draft={'{"tldr":"Export pace is runn'} />);
    expect(screen.getByTestId('note-draft').textContent).toContain('Export pace is runn');
  });
});
