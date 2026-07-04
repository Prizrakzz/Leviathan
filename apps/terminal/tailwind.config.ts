import type { Config } from 'tailwindcss';
import { FONTS, RADIUS, SPACE, TAILWIND_COLORS, TYPE_PX } from './src/tokens/tokens';

// Tailwind is skinned ENTIRELY from the design tokens (design §2). Every color resolves to a CSS var
// (no raw hex here, no default Tailwind palette) — tokens.ts is the single source; injectTokens() sets
// the var values at runtime. A raw hex in app code is an ESLint error; an orphan token is a test failure.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}', './.storybook/**/*.{ts,tsx}'],
  theme: {
    // Replace (not extend) colors so the default Tailwind palette can never leak into the "look".
    colors: TAILWIND_COLORS,
    fontFamily: { mono: FONTS.mono, sans: FONTS.sans },
    fontSize: Object.fromEntries(
      Object.entries(TYPE_PX).map(([k, v]) => [k, [`${v}px`, { lineHeight: '1.35' }]]),
    ),
    borderRadius: RADIUS,
    extend: {
      spacing: SPACE,
      transitionDuration: { hover: '120ms', panel: '200ms', chip: '90ms' },
    },
  },
  plugins: [],
} satisfies Config;
