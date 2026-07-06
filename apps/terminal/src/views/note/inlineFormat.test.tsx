import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FormattedNote, parseInline, renderInline } from './inlineFormat';
import type { ResolvedMap } from './citations';

const resolved: ResolvedMap = { '1': { source: 'USDA WASDE', date: '2022-01-01', text: 'stocks tightened' } };

describe('parseInline (6.1 markup subset)', () => {
  it('renders paired **bold** and *em*', () => {
    expect(parseInline('a **b** c', {})).toEqual([
      { k: 'text', v: 'a ' },
      { k: 'strong', v: [{ k: 'text', v: 'b' }] },
      { k: 'text', v: ' c' },
    ]);
    expect(parseInline('x *y* z', {})).toEqual([
      { k: 'text', v: 'x ' },
      { k: 'em', v: [{ k: 'text', v: 'y' }] },
      { k: 'text', v: ' z' },
    ]);
  });

  it('STRIPS an unpaired ** so a raw asterisk never reaches the DOM', () => {
    expect(parseInline('a ** b', {})).toEqual([{ k: 'text', v: 'a  b' }]);
    expect(parseInline('lone * star', {})).toEqual([{ k: 'text', v: 'lone  star' }]);
  });

  it('is streaming-safe: a trailing open **marker keeps the text, drops the marker', () => {
    expect(parseInline('hello **wor', {})).toEqual([{ k: 'text', v: 'hello wor' }]);
    expect(parseInline('tail *', {})).toEqual([{ k: 'text', v: 'tail ' }]);
  });

  it('resolves a citation to a chip token, leaves an unresolved [n] as text', () => {
    expect(parseInline('see [1] now', resolved)).toEqual([
      { k: 'text', v: 'see ' },
      { k: 'cite', ref: '1', resolved: resolved['1'] },
      { k: 'text', v: ' now' },
    ]);
    expect(parseInline('see [9] gone', resolved)).toEqual([{ k: 'text', v: 'see [9] gone' }]);
  });
});

describe('render (no raw markers in the DOM)', () => {
  it('renderInline emits <strong> and no literal asterisks', () => {
    render(<div data-testid="w">{renderInline('the **key** driver', {}, () => {})}</div>);
    const el = screen.getByTestId('w');
    expect(el.querySelector('strong')?.textContent).toBe('key');
    expect(el.textContent).toBe('the key driver');
    expect(el.textContent).not.toContain('*');
  });

  it('FormattedNote turns "- " lines into a real <ul> and drops stray markers', () => {
    render(
      <div data-testid="n">
        <FormattedNote text={'lead in\n\n- first **point**\n- second'} resolved={{}} onOpen={() => {}} />
      </div>,
    );
    const el = screen.getByTestId('n');
    expect(el.querySelectorAll('ul li')).toHaveLength(2);
    expect(el.querySelector('strong')?.textContent).toBe('point');
    expect(el.textContent).not.toContain('*');
  });
});
