import type { components } from '@/api/types.gen';

type DriverSignal = components['schemas']['DriverSignal'];
type RegimeCard = components['schemas']['RegimeCard'];
type EventItem = components['schemas']['EventItem'];

/** Drivers for the coverage panel: live/observed first, then by |z| desc (loudest signal on top), stable
 *  on id. */
export function orderDrivers(drivers: DriverSignal[]): DriverSignal[] {
  const rank = (d: DriverSignal) => (d.live ? 0 : 1);
  const mag = (d: DriverSignal) => (Number.isFinite(Number(d.z)) ? Math.abs(Number(d.z)) : -1);
  return [...drivers].sort(
    (a, b) => rank(a) - rank(b) || mag(b) - mag(a) || a.id.localeCompare(b.id),
  );
}

/** The fired-regime cards shaped for the CascadeDAG firing overlay (its `{matched}` list). */
export function firedRegimeOverlay(regimes: RegimeCard[]): { matched: string[] }[] {
  return regimes.filter((r) => r.fired).map((r) => ({ matched: r.matched }));
}

/** The ids of live drivers — the CascadeDAG's active `drivers` set. */
export function activeDriverIds(drivers: DriverSignal[]): string[] {
  return drivers.filter((d) => d.live).map((d) => d.id);
}

/** Regimes hottest-first (fired, then proximity desc) for the gauge row. */
export function orderRegimes(regimes: RegimeCard[]): RegimeCard[] {
  return [...regimes].sort(
    (a, b) => Number(b.fired) - Number(a.fired) || (b.proximity ?? 0) - (a.proximity ?? 0),
  );
}

/** Events most-recent-first, capped. Backend already enforces date ≤ as-of (point-in-time). */
export function recentEvents(events: EventItem[], cap = 12): EventItem[] {
  return [...events].sort((a, b) => (b.date ?? '').localeCompare(a.date ?? '')).slice(0, cap);
}
