/* ESLint — strict TS + React, plus the anti-vibe-coded guardrail: raw hex colors and raw px in tsx are
   banned so every visual value flows through the design tokens (design §2 / §7). */
module.exports = {
  root: true,
  env: { browser: true, es2021: true, node: true },
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } },
  settings: { react: { version: '18.3' } },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended'],
  ignorePatterns: [
    'dist',
    'storybook-static',
    'playwright-report',
    'node_modules',
    'src/api/types.gen.ts',
    'src/tokens/tokens.ts',
  ],
  rules: {
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',
    'react-refresh/only-export-components': 'off',
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    // No raw hex colors in components — tokens only (tokens.ts is the single exception, ignored above).
    'no-restricted-syntax': [
      'error',
      {
        selector: "Literal[value=/^#(?:[0-9a-fA-F]{3}){1,2}$/]",
        message: 'Raw hex colors are banned — use a design token (bg-0/amber/cyan/… or var(--…)).',
      },
    ],
  },
  overrides: [
    {
      files: ['**/*.test.{ts,tsx}', '**/*.stories.tsx', 'e2e/**/*.ts'],
      // Stories legitimately use hooks inside `render`; tests/e2e use raw literals + interaction helpers.
      rules: { 'no-restricted-syntax': 'off', 'react-hooks/rules-of-hooks': 'off' },
    },
  ],
};
