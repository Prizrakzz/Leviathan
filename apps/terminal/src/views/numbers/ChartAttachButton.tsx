import { useUI } from '@/store/ui';
import { MAX_ATTACH, chipKey, seriesChip } from '@/store/chips';
import { type ChartLocator, chartTitle } from './chartTriggers';

/** D-UX-4: "attach to next question" for a chart.
 *
 *  DELIBERATELY A LEAF. It owns no layout and no chart state: it takes a locator, calls the store, and
 *  renders one chip-sized button, so it can be mounted from a chart card's `action` slot or a chart tab's
 *  header with a single line and no edits inside either of those components.
 *
 *  WHAT ATTACHING MEANS (and does not): the attachment carries the LOCATOR only -- table, metric and the
 *  optional commodity/country/delivery-month dimensions. It carries no points and, pointedly, no `asof`:
 *  the backend re-reads the series under the NEXT turn's own as-of. So this is a "look here" gesture, not a
 *  paste of these numbers into the next question, and a chart left attached from an hour ago cannot drag
 *  that hour's vintage forward. The button says "attach" rather than "add data" for exactly that reason.
 *
 *  Attach is idempotent (the store dedupes by locator) and capped at MAX_ATTACH; when the cap is reached
 *  the button says so instead of silently no-opping, which is the failure the P2 chip cap already had. */
export function ChartAttachButton({ locator, className }: { locator: ChartLocator; className?: string }) {
  const chips = useUI((s) => s.attachedChips);
  const chip = seriesChip({ ...locator, label: chartTitle(locator) });
  const key = chipKey(chip);
  const attached = chips.some((c) => c.key === key);
  const full = !attached && chips.length >= MAX_ATTACH;

  return (
    <button
      data-testid="chart-attach"
      data-attached={attached ? 'yes' : 'no'}
      disabled={attached || full}
      aria-label={`attach ${chartTitle(locator)} to the next question`}
      title={
        attached
          ? 'already attached to your next question'
          : full
            ? `context is full (${MAX_ATTACH} attachments)`
            : 'steers the next question at this series; the numbers are re-read at that turn’s as-of'
      }
      onClick={() => useUI.getState().addChip(chip)}
      className={
        className ??
        'shrink-0 rounded-chip border border-line px-2 py-0.5 font-mono text-11 text-text-dim ' +
          'hover:border-cyan hover:text-cyan disabled:cursor-default disabled:opacity-60 disabled:hover:border-line disabled:hover:text-text-dim'
      }
    >
      {attached ? 'attached ✓' : full ? 'context full' : 'attach to next question'}
    </button>
  );
}
