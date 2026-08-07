/** The UTC calendar day of an ISO instant ("2026-08-10"), or '' when there isn't one.
 *
 *  Parsed and re-formatted rather than sliced: the string may carry any offset (`+03:00` is what the CLI
 *  renders here), and the dossier allowance resets on a UTC WEEK boundary -- so the day shown has to be the
 *  UTC day, not the local one, or a desk in Amman reads the reset as a day early. Never hand-labels a
 *  weekday; the date is the fact. */
export function utcDay(iso?: string): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  return new Date(t).toISOString().slice(0, 10);
}

/** Compact relative timestamp for the thread sidebar: "now", "5m", "3h", "4d", else "2026-07-01". */
export function relTime(iso: string | undefined, now: Date = new Date()): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.floor((now.getTime() - t) / 1000));
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 14 * 86400) return `${Math.floor(s / 86400)}d`;
  return iso.slice(0, 10);
}
