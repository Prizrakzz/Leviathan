/**
 * Command-bar parser (design §3.3): terse function codes route to intents; anything unrecognized is a
 * natural-language question. A `… as-of YYYY-MM-DD` suffix stamps a single note without moving the global
 * horizon (§3.4) and is stripped before routing. Pure + fully unit-tested — the tickers/metrics tables are a
 * Phase-2 representative subset; the real universe (31 contracts) is injected from the backend in Phase 3.
 */

const TICKERS: Record<string, string> = {
  KC: 'arabica_coffee',
  RC: 'robusta_coffee',
  SB: 'raw_sugar',
  CC: 'cocoa',
  C: 'corn',
  S: 'soybeans',
  W: 'wheat_srw',
  KW: 'wheat_hrw',
  CT: 'cotton',
  BO: 'soybean_oil',
  SM: 'soybean_meal',
};

const METRICS = new Set([
  'su-ratio',
  'ending-stocks',
  'stocks',
  'oni',
  'fx',
  'crush-margin',
  'production',
  'exports',
]);

export type ParsedCommand =
  | { kind: 'numbers'; contract: string; metric: string; asofOverride?: string }
  | { kind: 'ask'; contract: string; question: string; asofOverride?: string }
  | { kind: 'nl'; question: string; asofOverride?: string };

const ISO = /\bas-of\s+(\d{4}-\d{2}-\d{2})\b/i;

function stripAsOf(input: string): { text: string; asofOverride?: string } {
  const m = input.match(ISO);
  if (!m) return { text: input.trim() };
  return { text: input.replace(ISO, '').replace(/\s+/g, ' ').trim(), asofOverride: m[1] };
}

const ticker = (t: string): string | undefined => TICKERS[t.toUpperCase()];

export function parseCommand(input: string): ParsedCommand {
  const { text, asofOverride } = stripAsOf(input);
  const withAsof = <T extends object>(o: T) => (asofOverride ? { ...o, asofOverride } : o);
  if (!text) return withAsof({ kind: 'nl', question: '' }) as ParsedCommand;

  const tokens = text.split(/\s+/);
  const head = tokens[0] as string;

  const c0 = ticker(head);
  if (c0) {
    const rest = tokens.slice(1);
    // "<T> <metric>" -> numbers (a single metric-looking token: in the table, or hyphenated)
    if (rest.length === 1) {
      const tok = (rest[0] as string).toLowerCase();
      if (METRICS.has(tok) || tok.includes('-')) {
        return withAsof({ kind: 'numbers', contract: c0, metric: tok }) as ParsedCommand;
      }
    }
    // Anything else with a leading ticker — a bare "<T>", "<T> deep", "<T> vs <T>", or "<T> <words…>" —
    // folds into an ask scoped to that contract, routed to the Answer view (5.6 view-prune: the deep-dive +
    // compare views were removed, so a leading code is now just a question about that contract).
    return withAsof({ kind: 'ask', contract: c0, question: text }) as ParsedCommand;
  }

  // No leading ticker/code -> a natural-language question.
  return withAsof({ kind: 'nl', question: text }) as ParsedCommand;
}
