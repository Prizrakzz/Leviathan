/**
 * Design tokens — the SINGLE source of truth (design spec §2). Every color/type/space/radius/motion value
 * lives here exactly once. Consumers:
 *   - Tailwind (tailwind.config.ts) maps names -> `var(--…)` (never a raw hex).
 *   - `injectTokens()` sets the `--…` variable VALUES on :root at runtime (main.tsx + Storybook + tests).
 *   - App code references token names via Tailwind utilities (`bg-bg-0`, `text-amber`, …) only.
 * A raw hex in a component is an ESLint error; an orphan token is a tokens.test.ts failure. This file is the
 * one place hex values are allowed (it is ESLint-ignored).
 */

// ── §2.1 palette — the ONLY hex values in the app ──────────────────────────────────────────────────
export const PALETTE = {
  'bg-0': '#0B0C0E', // app canvas (near-black, faint blue-cool)
  'bg-1': '#121417', // panels / cards
  'bg-2': '#1A1D21', // raised / hover surfaces
  line: '#242830', // hairlines, panel borders, grid
  amber: '#F5A623', // primary / brand; active edges, key values, the mark
  'amber-dim': '#B67C1E', // secondary amber
  cyan: '#35D0E0', // interactive: selection, links, focus ring, DAG highlight
  text: '#E6E4E1', // primary text (warm off-white)
  'text-dim': '#8A8F98', // labels, metadata, axis
  'text-faint': '#5A5F68', // disabled, watermarks, dormant regimes
  pos: '#37B24D', // bullish / positive / verified
  neg: '#F03E3E', // bearish / negative / stripped
  warn: '#F5A623', // anomaly (z-score), armed regime (reuses amber)
  live: '#35D0E0', // live / as-of = today indicator
} as const;

export type TokenName = keyof typeof PALETTE;

const varName = (name: string): string => `--${name}`;

/** `{ '--bg-0': '#0B0C0E', … }` — what injectTokens writes to :root. */
export const CSS_VARS: Record<string, string> = Object.fromEntries(
  Object.entries(PALETTE).map(([name, hex]) => [varName(name), hex]),
);

/** `{ 'bg-0': 'var(--bg-0)', … }` — the Tailwind color map (no hex leaks into the theme). */
export const TAILWIND_COLORS: Record<string, string> = Object.fromEntries(
  Object.keys(PALETTE).map((name) => [name, `var(${varName(name)})`]),
);

// ── §2.2 typography ────────────────────────────────────────────────────────────────────────────────
export const FONTS = {
  mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
  sans: ['"IBM Plex Sans"', 'system-ui', '-apple-system', 'sans-serif'],
} as const;

/** Type scale steps (px): text-11 … text-32. */
export const TYPE_PX = { '11': 11, '12': 12, '13': 13, '14': 14, '16': 16, '18': 18, '24': 24, '32': 32 } as const;

// ── §2.4 spacing / radius / motion ───────────────────────────────────────────────────────────────
/** Tailwind defaults already cover the 8px rhythm (p-2=8 … p-8=32); we only add the 4px dense-row token. */
export const SPACE = { dense: '4px' } as const;

/** Deliberately tight — instrument-like. chip/input = 2px, panel/card = 4px. */
export const RADIUS = { none: '0px', DEFAULT: '2px', chip: '2px', panel: '4px' } as const;

/** Motion durations (ms): fast + functional, no decoration. */
export const MOTION = { hover: 120, panel: 200, chip: 90 } as const;

/** Regime-state -> token name (design §2.1). */
export const REGIME_STATE = { dormant: 'text-faint', armed: 'amber', firing: 'amber' } as const;

/**
 * Write the token variable values onto an element (default :root). Called once at app/Storybook/test start.
 * Idempotent; the single runtime bridge between tokens.ts and the CSS that references `var(--…)`.
 */
export function injectTokens(el: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(CSS_VARS)) el.style.setProperty(name, value);
}
