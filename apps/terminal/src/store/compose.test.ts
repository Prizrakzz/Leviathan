import { beforeEach, describe, expect, it } from 'vitest';
import { EMPTY_VOCAB, fillWithSpans, optionsFor, slotsOf, useCompose } from './compose';

const VOCAB = {
  contracts: ['arabica coffee', 'corn', 'raw sugar'],
  regimes: ['Frost Squeeze (price-supportive)', 'Record Supply (price-pressuring)'],
  pairs: ['palm oil and soybean oil'],
};

const TPL = 'How close is the {regime} regime in {contract} to firing right now?';
const SEED = { regime: 'Frost Squeeze (price-supportive)', contract: 'arabica coffee' };
const FILLED =
  'How close is the Frost Squeeze (price-supportive) regime in arabica coffee to firing right now?';

const s = () => useCompose.getState();

beforeEach(() =>
  useCompose.setState({
    draft: '',
    rev: 0,
    focus: false,
    template: null,
    slots: [],
    values: {},
    options: {},
    spans: {},
  }),
);

describe('compose helpers (D-UX-1)', () => {
  it('reads the slot names in sentence order, de-duped', () => {
    expect(slotsOf(TPL)).toEqual(['regime', 'contract']);
    expect(slotsOf('{contract} vs {contract}')).toEqual(['contract']);
    expect(slotsOf('no blanks here')).toEqual([]);
  });

  it('maps each slot to its own vocabulary, and an unknown slot to an empty (still free-text) one', () => {
    expect(optionsFor('contract', VOCAB)).toEqual(VOCAB.contracts);
    expect(optionsFor('regime', VOCAB)).toEqual(VOCAB.regimes);
    expect(optionsFor('pair', VOCAB)).toEqual(VOCAB.pairs);
    expect(optionsFor('vintage', VOCAB)).toEqual([]);
    expect(optionsFor('contract', EMPTY_VOCAB)).toEqual([]);
  });

  it('keeps the brace for an empty value: a visible blank, never a hole in the sentence', () => {
    expect(fillWithSpans(TPL, SEED).text).toBe(FILLED);
    expect(fillWithSpans(TPL, { contract: 'corn' }).text).toBe(
      'How close is the {regime} regime in corn to firing right now?',
    );
    expect(fillWithSpans(TPL, { contract: '   ' }).text).toContain('{contract}');
  });

  it('anchors every slot at the span it occupies, so an edit rewrites that phrase and nothing else', () => {
    const { text, spans } = fillWithSpans(TPL, SEED);
    for (const [name, [a, b]] of Object.entries(spans))
      expect(text.slice(a, b)).toBe(SEED[name as keyof typeof SEED]);
    // an EMPTY slot anchors its brace -- the blank is what the next pick replaces
    const cold = fillWithSpans(TPL, {});
    expect(cold.text.slice(...cold.spans.contract!)).toBe('{contract}');
  });
});

describe('prefill (D-UX-1: the first design law: prefill, never submit)', () => {
  it('lands the SERVER fill verbatim, with the slot bar bound to the catalog vocabulary', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    expect(s().draft).toBe(FILLED); // byte-identical to the question the gallery advertises
    expect(s().slots).toEqual(['regime', 'contract']);
    expect(s().values).toEqual(SEED);
    expect(s().options.contract).toEqual(VOCAB.contracts);
    expect(s().rev).toBe(1);
    expect(s().focus).toBe(true);
  });

  it('bumps rev on a REPEAT choice, so choosing the same template twice re-fills the box', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    s().syncDraft('the analyst wandered off');
    s().prefillTemplate(TPL, SEED, VOCAB);
    expect(s().rev).toBe(2);
    expect(s().draft).toBe(FILLED);
  });

  it('a cold catalog prefills the BLANKS themselves and still offers free typing', () => {
    s().prefillTemplate(TPL, {}, EMPTY_VOCAB);
    expect(s().draft).toBe(TPL); // the fill-in-the-blank form IS the fallback product
    expect(s().options).toEqual({ regime: [], contract: [] });
  });

  it('a brace-free template is just a prefill: no bar to render', () => {
    s().prefillTemplate('Rank the largest exporters of corn.', {}, VOCAB);
    expect(s().slots).toEqual([]);
    expect(s().draft).toBe('Rank the largest exporters of corn.');
  });
});

describe('slot editing (D-UX-1: the text is the truth)', () => {
  it('rewrites only that slot span, leaving hand-typed edits alone', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    s().syncDraft(`${FILLED} and what would confirm it?`); // they kept typing
    s().setSlot('contract', 'corn');
    expect(s().draft).toBe(
      'How close is the Frost Squeeze (price-supportive) regime in corn to firing right now? and what would confirm it?',
    );
    expect(s().values.contract).toBe('corn');
    expect(s().focus).toBe(false); // never steals the caret back from the combobox
  });

  it('accepts a FREE-TYPED value the vocabulary never offered', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    s().setSlot('contract', 'hard red winter wheat');
    expect(s().draft).toContain('regime in hard red winter wheat to firing');
    expect(s().options.contract).toEqual(VOCAB.contracts); // the dropdown OFFERS; it does not fence
  });

  it('clearing a slot restores the visible blank rather than leaving a gap', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    s().setSlot('contract', '');
    expect(s().draft).toContain('regime in {contract} to firing');
    s().setSlot('contract', 'corn'); // and the blank is the anchor for the next pick
    expect(s().draft).toContain('regime in corn to firing');
  });

  it('DETACHES instead of clobbering when the analyst rewrote the slot span by hand', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    s().syncDraft('How close is the frost regime in the whole coffee complex to firing right now?');
    expect(s().template).toBeNull(); // the edit landed ON the slots: the template stops anchoring the text
    s().setSlot('contract', 'corn'); // and a late slot write can no longer rewrite anything
    expect(s().slots).toEqual([]);
    expect(s().draft).toBe(
      'How close is the frost regime in the whole coffee complex to firing right now?',
    ); // their words survive
  });

  it('detach keeps the question, clear takes everything (the turn went out)', () => {
    s().prefillTemplate(TPL, SEED, VOCAB);
    s().detach();
    expect(s().template).toBeNull();
    expect(s().draft).toBe(FILLED);

    s().prefillTemplate(TPL, SEED, VOCAB);
    s().clear();
    expect(s().draft).toBe('');
    expect(s().template).toBeNull();
    expect(s().slots).toEqual([]);
  });
});
