import { describe, expect, it } from 'vitest';
import { CSS_VARS, PALETTE, RADIUS, TAILWIND_COLORS, TYPE_PX, injectTokens } from './tokens';

describe('design tokens (single source of truth)', () => {
  it('every palette token has a matching CSS var and a Tailwind color mapping', () => {
    for (const name of Object.keys(PALETTE)) {
      expect(CSS_VARS[`--${name}`]).toBe(PALETTE[name as keyof typeof PALETTE]);
      expect(TAILWIND_COLORS[name]).toBe(`var(--${name})`);
    }
    // no orphans in either direction
    expect(Object.keys(CSS_VARS).length).toBe(Object.keys(PALETTE).length);
    expect(Object.keys(TAILWIND_COLORS).length).toBe(Object.keys(PALETTE).length);
  });

  it('Tailwind colors are var() references only — no raw hex leaks into the theme', () => {
    for (const value of Object.values(TAILWIND_COLORS)) {
      expect(value).toMatch(/^var\(--[a-z0-9-]+\)$/);
      expect(value).not.toMatch(/#[0-9a-fA-F]{3,6}/);
    }
  });

  it('injectTokens sets every var value onto the target element', () => {
    const el = document.createElement('div');
    injectTokens(el);
    expect(el.style.getPropertyValue('--bg-0')).toBe(PALETTE['bg-0']);
    expect(el.style.getPropertyValue('--amber')).toBe(PALETTE.amber);
    expect(el.style.getPropertyValue('--cyan')).toBe(PALETTE.cyan);
  });

  it('type scale + radius match the spec (11..32 px; 2px chip / 4px panel)', () => {
    expect(Object.values(TYPE_PX)).toEqual([11, 12, 13, 14, 16, 18, 24, 32]);
    expect(RADIUS.chip).toBe('2px');
    expect(RADIUS.panel).toBe('4px');
  });
});
