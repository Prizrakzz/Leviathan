import { describe, expect, it } from 'vitest';
import {
  ACCENTS,
  CSS_VARS,
  FONTS,
  MONO_STACK,
  PALETTE,
  RADIUS,
  TAILWIND_COLORS,
  TYPE_PX,
  applyAccent,
  injectTokens,
} from './tokens';

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

describe('accent presets (6.6 — one swappable interactive accent)', () => {
  it('both accents reuse existing palette hex (no new token → bijection intact)', () => {
    expect(ACCENTS.cyan).toBe(PALETTE.cyan);
    expect(ACCENTS.amber).toBe(PALETTE.amber);
  });

  it('applyAccent overrides only the interactive-accent vars (--cyan/--live); cyan restores the default', () => {
    const el = document.createElement('div');
    injectTokens(el); // baseline: --cyan/--live are the teal default
    applyAccent('amber', el);
    expect(el.style.getPropertyValue('--cyan')).toBe(PALETTE.amber);
    expect(el.style.getPropertyValue('--live')).toBe(PALETTE.amber);
    // the canvas/brand tokens are untouched by an accent swap
    expect(el.style.getPropertyValue('--bg-0')).toBe(PALETTE['bg-0']);
    expect(el.style.getPropertyValue('--amber')).toBe(PALETTE.amber);
    applyAccent('cyan', el);
    expect(el.style.getPropertyValue('--cyan')).toBe(PALETTE.cyan);
    expect(el.style.getPropertyValue('--live')).toBe(PALETTE.cyan);
  });
});

describe('D-UX-5 chart inks — a data colour is never the interactive accent', () => {
  it('the amber accent DOES collapse --cyan onto --amber; that is why the charts moved off it', () => {
    const el = document.createElement('div');
    injectTokens(el);
    applyAccent('amber', el);
    // ACCENTS.amber IS PALETTE.amber -- the series colour. Under this (offered) preference, anything drawn
    // with `--cyan` becomes the same colour as the line beside it: OverlayChart's leg B against leg A, and
    // the as-of marker against the series it marks.
    expect(el.style.getPropertyValue('--cyan')).toBe(el.style.getPropertyValue('--amber'));
  });

  it("the two chart inks hold the SPEC's cyan through both accents, and stay legible against amber", () => {
    const el = document.createElement('div');
    injectTokens(el);
    for (const accent of ['amber', 'cyan'] as const) {
      applyAccent(accent, el);
      // §2.1 --cyan = #35D0E0; §4.4 "Amber curve, cyan current-marker".
      expect(el.style.getPropertyValue('--series-b')).toBe(PALETTE.cyan);
      expect(el.style.getPropertyValue('--asof')).toBe(PALETTE.cyan);
      // THE CONTRAST ASSERTION: leg B is never leg A, and the as-of line is never the series line.
      expect(el.style.getPropertyValue('--series-b')).not.toBe(el.style.getPropertyValue('--amber'));
      expect(el.style.getPropertyValue('--asof')).not.toBe(el.style.getPropertyValue('--amber'));
    }
  });

  it('the mono stack is a real font stack with a fallback, not the bare `monospace` it replaced', () => {
    expect(MONO_STACK).toBe(FONTS.mono.join(', '));
    expect(MONO_STACK.startsWith('"IBM Plex Mono"')).toBe(true);
    expect(MONO_STACK.endsWith('monospace')).toBe(true);
  });
});
