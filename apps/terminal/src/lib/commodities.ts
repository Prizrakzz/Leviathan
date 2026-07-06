/**
 * A friendly shortlist of the commodities a researcher is most likely to follow — the toggle-chip options
 * for onboarding step 1 and the Settings "markets" editor (6.6). Deliberately NOT the full 33-contract
 * hierarchy: these are plain display labels stored verbatim in `facts.markets`, which the query suggester
 * reads as free text to personalize starters/follow-ups. The user can also type their own via the facts
 * editor, so this list only needs to cover the common cases.
 */
export const COMMODITIES = [
  'coffee',
  'robusta coffee',
  'sugar',
  'cocoa',
  'cotton',
  'corn',
  'soybeans',
  'soybean oil',
  'soybean meal',
  'wheat',
  'palm oil',
  'rice',
  'orange juice',
  'canola',
  'live cattle',
  'lean hogs',
] as const;

/** Onboarding step 2 — the user's seat / role. Stored in `facts.seat`. */
export const SEATS = ['trader', 'analyst', 'portfolio manager', 'other'] as const;
