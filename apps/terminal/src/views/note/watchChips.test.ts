import { describe, expect, it } from 'vitest';
import type { Section } from '@/api/schema';
import { deriveWatchChips } from './watchChips';

const watchSection = (body: string): Section => ({ kind: 'watch', heading: 'What to watch', body });

const MECHANISM =
  '## Mechanism\n- frost kills buds [1]\n' +
  '## What to watch\n- certified stocks through July [N1]\n- a second cold front before recovery [1]\n' +
  '## Sources\n- [1] USDA GAIN';

describe('deriveWatchChips (P9-E1a)', () => {
  it('PRIMARY: reads the typed watch section, ignoring the mechanism string', () => {
    const chips = deriveWatchChips({
      mechanism: '## What to watch\n- from the mechanism string',
      sections: [watchSection('- from the typed section [2]')],
    });
    expect(chips).toEqual(['from the typed section']);
  });

  it('FALLBACK: parses the ## What to watch block out of mechanism, stopping at the next heading', () => {
    expect(deriveWatchChips({ mechanism: MECHANISM })).toEqual([
      'certified stocks through July',
      'a second cold front before recovery',
    ]);
  });

  it('no watch heading -> zero chips; null/absent structured -> zero chips', () => {
    expect(deriveWatchChips({ mechanism: '## Mechanism\n- frost kills buds' })).toEqual([]);
    expect(deriveWatchChips(null)).toEqual([]);
    expect(deriveWatchChips({})).toEqual([]);
  });

  it('non-bullet lines in the watch block yield no chips', () => {
    expect(deriveWatchChips({ mechanism: '## What to watch\nplain prose, no bullets' })).toEqual([]);
  });

  it('caps the count at 4', () => {
    const body = ['- a', '- b', '- c', '- d', '- e', '- f'].join('\n');
    expect(deriveWatchChips({ sections: [watchSection(body)] })).toEqual(['a', 'b', 'c', 'd']);
  });

  it('caps chip text at ~90 chars, ellipsized at a word boundary', () => {
    const long =
      'watch the certified stocks number through the July frost window because a confirmed freeze ' +
      'historically cascades into outsized price moves';
    const [chip] = deriveWatchChips({ sections: [watchSection(`- ${long}`)] });
    expect(chip!.length).toBeLessThanOrEqual(91); // 90 + the ellipsis
    expect(chip!.endsWith('\u2026')).toBe(true);
    // word boundary: everything before the ellipsis is a prefix of the source ending on a whole word
    const stem = chip!.slice(0, -1);
    expect(long.startsWith(stem)).toBe(true);
    expect(long[stem.length]).toBe(' ');
  });

  it('dedupes against the server suggestion texts AND within the watch bullets', () => {
    const body = '- already suggested\n- fresh item\n- fresh item';
    expect(deriveWatchChips({ sections: [watchSection(body)] }, ['already suggested'])).toEqual([
      'fresh item',
    ]);
  });
});
